"""主控工具（T0-9）的判据：M 有手（派活）、有眼（台账/状态）、能停（优雅停止）。

依据 `draft/30` §T0-9。这一组钉住四件事：

1. M 的工具面非空且只有编排面（只读角色一件也拿不到）；
2. 派活过闸门、被拒留痕（越权 / 未接线 / 非法目标都是 refused，不是静默成功）；
3. 优雅停止五条：不再新开任务、无僵尸行、有续跑简报、幂等、不自动重试；
4. 冷/热由 M 决定，四态如实给（别人的目录绝不被当工作区初始化）。

刻意不测计划质量：那由 K 线与人工复核看，工具层只保证"合法且可审计"。
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from agentflow import capabilities as C
from agentflow import projects as P
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

#: M 的完整工具面（`draft/37` §38 的用户裁定 + §57 追加 `fs.edit`）：
#: 编排面 11 件 + 文件面白名单 6 件（只读四件 + `fs.write` + `fs.edit`）。
#:
#: 这份集合被判据用来断言"相等"（而不是"包含"）是刻意的：M 的面是权限面，
#: 多一件少一件都要有人看见 —— 而 `fs.delete` / `fs.move` 故意不在里面
#: （一个真删、一个换位置，都是不可逆的）。`fs.edit` 是 2026-10-03 按真机读数补进来的：
#: `fs.write` 单独改不了 26 KB 的稿子（整文件重写会被输出额度截断在字符串中间）。
M_TOOL_FACE = {
    "conductor.summon", "conductor.summon_many", "conductor.ledger", "conductor.stop",
    "conductor.resume_brief", "conductor.cancel", "conductor.ensure_project",
    "conductor.state", "conductor.role_spec", "conductor.acceptance",
    "conductor.closing", "conductor.status_report",
    # 工作项板（业主 2026-10-08 裁 A1=甲）：M 的**编排面**看"还挂着什么"。
    # A–H 的那一半是 `manuscripts.items` / `manuscripts.ack`（领域动作面），不在这里。
    "conductor.board",
    "fs.list", "fs.read", "fs.search", "fs.stat", "fs.write", "fs.edit",
}
#: 旧的别名（只守编排面那 11 件）；留给"编排面本身"的判据用。
ORCHESTRATION_TOOLS = {n for n in M_TOOL_FACE if n.startswith("conductor.")}


class _FakeE:
    """E 的替身：只实现一个无必填参数的动作，用来验证"派活真的到了角色手里"。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_experiments(self) -> dict:
        self.calls.append({})
        return {"experiments": [], "count": 0}


def _wired(tmp_path: Path, *, role_registry=None):
    """造一个工作区 + 一个主控 + 装了主控工具的注册表。"""
    store = Store(tmp_path)
    store.init()
    c = Conductor(store, registry=role_registry if role_registry is not None else {})
    reg = build_registry(store=store, conductor=c).registry
    return store, c, reg


def test_acceptance_without_a_table_reports_no_table_instead_of_crashing(tmp_path: Path):
    """负控（2026-10-02 的真机 bug）：没有验收表时必须如实说"没查成"，而不是抛 NameError。

    这个 bug 的形态值得单记：`conductor_acceptance` 在"表不在盘上"那条分支里调了 `fail(...)`，
    而 `fail` 没有 import（模块只 import 了 `ok`）。它活了很久，因为
    `tests/test_conductor_tools.py` 里那条验收表用例每次都先造一张表 ——
    没人测的分支就是没被守的分支。真机那一次（`draft/37` §37）没有 ACCEPTANCE.md，
    于是 M 看到的是 `NameError: name 'fail' is not defined`，白烧一步。
    """
    _store, _c, reg = _wired(tmp_path)
    res = reg.call("conductor.acceptance", role="M")
    assert res.ok is False, res
    assert res.meta.get("kind") == "no_acceptance_table", res.meta
    assert "NameError" not in str(res.error or ""), res.error
    assert "没查成" in str(res.error or ""), res.error


# ============================================================ CC-02：验收表的解析容错


def _acceptance_md(root: Path, body: str) -> None:
    """把一张验收表写进工作区（`conductor.acceptance` 的缺省路径）。"""
    d = root / "out" / "paper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ACCEPTANCE.md").write_text(body, encoding="utf-8", newline="\n")


#: 一张"写法与默认不同、但语义清楚"的验收表（`编号/名称/结论/读数` + `通过/未通过`）。
_WORDED_DIFFERENTLY = """# 验收表（措辞与默认不同）

结论：「大部分成立」

| 编号 | 名称 | 结论 | 读数 |
|---|---|---|---|
| P1 | 立题 | 通过 | 3 行 |
| P2 | 检索 | 通过 | 8 条 |
| P3 | 造 | 未通过 | 0 条 |
"""

#: 一张坏表：空 id、重复 id、结论格是 `？`（读不懂）。
_BAD_TABLE = """# 验收表（坏表）

| 判据 | 名称 | 结论 | 读数 |
|---|---|---|---|
|  | 没有编号 | 成立 | 1 |
| P1 | 重复的编号 | 成立 | 2 |
| P1 | 又一个重复 | 成立 | 3 |
| P2 | 结论读不懂 | ？ | 4 |
"""


def test_cc02_a_differently_worded_but_clear_table_is_read_row_by_row(tmp_path: Path):
    """CC-02①：表头/结论写法不同但语义清楚 ⇒ 必须读出真行数（旧口径读成 0 行）。

    旧口径是逐字判据：表头 `cells[0] == "判据"`、结论 `cells[2].strip() == "成立"`
    ⇒ 这张表（`编号` + `通过`/`未通过`）一行都读不出来。判据里把旧条件写出来当反真空：
    它今天仍然为假 —— 也就是说"读出行数"这件事只能由新口径带来。
    """
    store, _c, reg = _wired(tmp_path)
    _acceptance_md(tmp_path, _WORDED_DIFFERENTLY)
    res = reg.call("conductor.acceptance", role="M")
    assert res.ok, res.error
    data = res.data
    # 反真空：旧判据在这张表上必然读成 0 行
    first_cells = [c.strip() for c in "| 编号 | 名称 | 结论 | 读数 |".strip().strip("|").split("|")]
    assert first_cells[0] != "判据", "这张表就是为'表头不是判据'而造的"
    assert data["row_count"] == 3, data
    assert data["ok_count"] == 2 and data["not_ok_count"] == 1, data
    assert data["row_ids"] == ["P1", "P2", "P3"], data
    assert all(r["state"] == "computed" for r in data["rows"]), data["rows"]
    assert data["problems"] == [], data["problems"]


def test_cc02_an_unreadable_verdict_is_not_guessed_and_not_ok(tmp_path: Path):
    """默认方向（写死）：认不出的结论一律 `unreadable`，永不猜成"成立"。

    两条各一条判据：① `？` ⇒ `unreadable`（不是 ok、也不是"不成立"）；
    ② `不成立` 绝不读成 `成立`（旧实现的坑：`"成立" in cells[2]`）。
    """
    store, _c, reg = _wired(tmp_path)
    _acceptance_md(tmp_path, _BAD_TABLE)
    res = reg.call("conductor.acceptance", role="M")
    assert res.ok, res.error
    rows = {r["id"]: r for r in res.data["rows"] if r["id"]}
    assert rows["P2"]["state"] == "unreadable", rows["P2"]
    assert rows["P2"]["ok"] is None, rows["P2"]
    unreadable = [r for r in res.data["rows"] if r["state"] == "unreadable"]
    assert len(unreadable) == 3, res.data["rows"]      # 空编号 / 重复编号 / 结论认不出
    assert res.data["ok_count"] == 1, res.data         # 只有第一个 P1 那行读得懂且成立
    assert res.data["not_ok_count"] == 0, "读不懂的行不许算进'不通过'（那是另一个结论）"
    assert any("读不懂" in p for p in res.data["problems"]), res.data["problems"]

    _acceptance_md(tmp_path, """# 表

| 判据 | 名称 | 结论 | 读数 |
|---|---|---|---|
| P1 | 一件事 | 不成立 | 0 |
""")
    res2 = reg.call("conductor.acceptance", role="M")
    assert res2.data["ok_count"] == 0 and res2.data["not_ok_count"] == 1, res2.data


def test_cc02_zero_rows_and_unreadable_rows_are_not_folded(tmp_path: Path):
    """CC-02③ 三态：表里 0 行（表头没认出来）与有行但读不懂必须分得开。"""
    store, _c, reg = _wired(tmp_path)
    _acceptance_md(tmp_path, """# 表头不认识

| 甲 | 乙 | 丙 |
|---|---|---|
| 1 | 2 | 3 |
""")
    none_read = reg.call("conductor.acceptance", role="M").data
    assert none_read["row_count"] == 0 and none_read["problems"], none_read

    _acceptance_md(tmp_path, _BAD_TABLE)
    some_unreadable = reg.call("conductor.acceptance", role="M").data
    assert some_unreadable["row_count"] == 4, some_unreadable
    assert some_unreadable["ok_count"] == 1, some_unreadable
    assert any(r["state"] == "unreadable" for r in some_unreadable["rows"]), some_unreadable
    assert "读不懂" in "；".join(some_unreadable["problems"]), some_unreadable["problems"]


def test_cc02_the_parser_and_the_closing_reading_agree_on_unreadable(tmp_path: Path):
    """CC-02②（这一批最重要的一条）：两边在"读不出来"这一档上结论一致。

    防的是"同一张表两种读法"（CC-02 要治的形态）。做法：口径只有一处 ——
    我的解析器产出的每个 `state` 都必须落在 `closing.ROW_STATES` 里，且
    `unreadable` 那一档的判定与 `closing` 对等价 JSON 行给出的判定一致：
    空 `id` / 重复 `id` / 词表外的 `kind` 两边都算"读不出来"。
    """
    from agentflow import closing as CL

    store, _c, reg = _wired(tmp_path)
    _acceptance_md(tmp_path, _BAD_TABLE)
    data = reg.call("conductor.acceptance", role="M").data

    # ① 词表只有一处：解析器不许自造状态名
    assert {r["state"] for r in data["rows"]} <= set(CL.ROW_STATES), data["rows"]
    # ② 与 `closing` 的读法一致：等价的坏形状在 C 那一侧同样是 `unreadable`
    assert CL.acceptance_row_state({"id": "", "state": "unreadable"}) == "unreadable"
    assert "unreadable" in CL.ROW_STATES
    assert CL.acceptance_kinds_with_state(
        [{"id": "P1", "kind": "k", "state": "unreadable"}], "unreadable") == {"k"}
    # ③ 我这边的 `unreadable` 行集合 = C 那一侧按状态分出来的集合（同一处定义）
    mine = {r["id"] for r in data["rows"] if r["state"] == "unreadable"}
    theirs = {str(r.get("id") or "") for r in data["rows"]
              if CL.acceptance_row_state(r) == "unreadable"}
    assert mine and mine == theirs, (mine, theirs)
    # ④ 反负控：把一张好表喂进去 ⇒ 一行 unreadable 都没有（判据不是永远报异常）
    _acceptance_md(tmp_path, _WORDED_DIFFERENTLY)
    ok = reg.call("conductor.acceptance", role="M").data
    assert {r["state"] for r in ok["rows"]} == {"computed"}, ok["rows"]


def test_role_spec_carries_the_brief_not_only_the_actions(tmp_path: Path):
    """判据（`draft/37` §108）：`conductor.role_spec` 要连声明层的画像一起给。

    派活错的形态是"不知道这个伙伴交付什么、不许做什么"，而它此前只返回
    `actions` / `tools` / `summonable` —— M 于是只有半张画像（§107 第一节）。
    """
    from agentflow import agentspec as AS

    reg = _wired(tmp_path)[2]
    res = reg.call("conductor.role_spec", role="M", role_name="A")
    assert res.ok, res.error
    brief = AS.builtin_registry().get("A").brief
    assert res.data["deliverable"] == brief.deliverable, res.data
    assert res.data["duty"] == brief.duty, res.data
    assert list(res.data["boundary"]) == list(brief.boundary), res.data
    assert res.data["signature_error"] == brief.signature_error, res.data
    assert res.data["actions"], "动作那几格不能被这次加厚挤掉"


def test_the_closing_tool_advertises_every_gate_cell(tmp_path: Path):
    """判据（`draft/37` §94）：`conductor.closing` 的描述必须点名收工门的每一格。

    为什么单列：§86 加 `substance`、§94 加 `acceptance` 时，描述里那句"五条"都成了
    陈旧读数 —— 而模型是照描述决定"跑这个工具能不能告诉我缺什么"的。
    判据直接对着 `closing.DEFAULT_CHECKS` 比：加一格却忘了改描述，这条当场红。
    """
    from agentflow import closing as CL

    reg = _wired(tmp_path)[2]
    spec = next(s for s in reg.for_role("M") if s.name == "conductor.closing")
    text = str(spec.summary) + str(spec.returns)
    missing = [name for name in CL.DEFAULT_CHECKS if name not in text]
    assert not missing, f"收工门有这些格，而工具描述里没点名：{missing}"
    # 旧口径是"描述里不许出现『五条』"—— 那是按字面堵，而这份描述里现在还会说
    # 另一件东西的条数（内容级验收的判据数）⇒ 字面堵会把一句正确的话判红
    # （2026-10-07 实测：`draft/68` 题 17 在描述里加了那一句之后本判据当场红）。
    # 改成按对象比，并把新对象的条数也钉上：
    #   ① 收工门自己的格数：描述里那句"收工门（N格）"的 N 必须等于 `len(DEFAULT_CHECKS)`；
    #   ② 描述里若说了内容级验收的条数，那个数必须等于 `reviewaccept.CRITERIA` 的真身。
    # 为什么①不能写成 `assert "八格" in text`：那样别的字样也能满足它 —— 我第一版就是
    # 那么写的，把 `（八格）` 改成 `（五条）` 的负控因此没咬住（实测）。也不能用 `\d+` 抠：
    # 描述里的格数是中文数字（"八格"），实测抠不到（第一版正则就是这么错的）。
    _cn = "零一二三四五六七八九十"

    def _as_written(n: int) -> str:
        return _cn[n] if n <= 10 else str(n)

    gate_claim = f"收工门（{_as_written(len(CL.DEFAULT_CHECKS))}格）"
    assert gate_claim in text, (
        f"描述里读不到 `{gate_claim}` 这一句 ⇒ 判据失去对象（改写法要同步改本条，"
        "不许让它静默变真空）"
    )
    for stale in ("五条全过", "六格全过", "七格全过", "五格全过"):
        assert stale not in text, f"描述里还写着收工门的旧条数（{stale}）"
    from agentflow import reviewaccept as RX

    # ① 的功能可见性钉子（反真空）：把那一句整段删掉不该让本条静默失去对象 ——
    # 题 17/B 加它的理由就是"主控要在提示词里看得见这一栏"，删掉那句话这个理由就没了。
    assert "review_acceptance" in text, (
        "描述里不再广告 `review_acceptance` 那一栏 ⇒ `draft/68` 题 17/B 加它的理由"
        "（主控在工具面上看得见内容级验收）没了；要撤这一栏请连同本条一起改"
    )
    # ② 同一条道理用在另一个对象上：描述里若说了内容级验收的条数，它必须与真身逐字同形。
    # 这里同样不能用 `\d+` 抠 —— 描述里写的是中文数字（"五条"），实测抠不到。
    if "内容级验收的" in text:
        rx_claim = f"内容级验收的{_as_written(len(RX.CRITERIA))}条判据"
        assert rx_claim in text, (
            f"描述里说了内容级验收的条数，但真身是 `{rx_claim}`（{len(RX.CRITERIA)} 条）"
            "—— 判据数一变这句话就是假的"
        )


def test_m_tool_surface_is_orchestration_only(tmp_path: Path):
    """M 拿到的正好是 `M_TOOL_FACE`（编排面 12 + 文件面白名单 6）；只读角色拿不到编排面工具。

    这条判据改过两次：2026-10-02 按用户裁定（`draft/37` §38）从"只有 `conductor.*`"
    变成"`conductor.*` + 文件面白名单五件"；2026-10-03 按 §57 的裁定再加一件 `fs.edit`
    （真机读数：`fs.write` 单独改不了 26 KB 的稿子）。两次扩的都不是"能不能碰盘"这条
    边界，而是边界的口径 —— `fs.delete` / `fs.move` 仍然一件不给（`M_TOOL_FACE` 里
    没有它们，而这里的断言是相等，所以多一件就会红）。
    2026-10-08 晚第三次：按业主裁 A1=甲/T16 加 `conductor.board`（板是**编排面**的读数；
    A–H 看板走 `manuscripts.items`，那一半不进 M 的面）。
    """
    _store, _c, reg = _wired(tmp_path)
    assert {s.name for s in reg.for_role("M")} == M_TOOL_FACE
    # 只读角色拿不到编排面工具（原来守的就是这一条）
    for read_only in ("C", "H"):
        assert not ({s.name for s in reg.for_role(read_only)} & ORCHESTRATION_TOOLS)
    # 反真空：只读角色也拿不到写类文件工具（它们是只读角色，结构性剥离）
    for read_only in ("C", "H"):
        got = {s.name for s in reg.for_role(read_only)}
        assert "fs.write" not in got and "fs.edit" not in got, read_only


def test_summon_runs_the_role_and_lands_a_ledger_row(tmp_path: Path):
    """正控：主控派活 → 角色真的被调用 → 台账里有一行 `by=agent-M` 的终态行。"""
    fake = _FakeE()
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", fake)})
    res = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert res.ok, res.error
    assert res.data["status"] == "done" and res.data["outcome"] == "ok"
    assert fake.calls == [{}], "派活必须真的到角色手里"
    rows = store.rows("tasks")
    assert len(rows) == 1
    assert rows[0]["called_by"] == "M" and rows[0]["role"] == "E"
    assert rows[0]["ended_at"], "每个 start 必须恰好有一个 end"


def test_summon_many_fans_out_the_same_role_in_parallel(tmp_path: Path):
    """S-1（§198 的核心判据）：`conductor.summon_many` 让同一角色的多个实例真的并发。

    为什么要有这条：并发引擎（`run_plan` → `scheduler.run_waves` → 线程池 + 探针）
    早就存在，但生产路径上零调用，而 M 的工具面只能一次派一个；
    更硬的一道是分波按"角色级写集"，于是 3 个 B 会被排成 3 波串行（实测峰值真并发 1）。
    用户要的形态是"一次任务要读一大批文献，就并发几个 B 一起干"。

    判据四条一起看：① `count` 恒等于输入长度；② 三个不同 `instance` 落同一波；
    ③ `concurrent_peak == 3`（探针读数，不是墙钟）；④ 三条任务行各自独立、都是 done/ok。
    """
    class _SlowE:
        """替身：睡 0.2s 并记录自己被哪个实例标签调用过。"""

        def __init__(self) -> None:
            self.instances: list[str] = []
            self._lock = __import__("threading").Lock()

        def list_experiments(self) -> dict:
            import threading as _t
            with self._lock:
                self.instances.append(_t.current_thread().name)
            __import__("time").sleep(0.2)
            return {"experiments": [], "count": 0}

    store, _c, reg = _wired(tmp_path, role_registry={
        "E": ("factory", lambda *, store=None, instance="": _SlowE())})
    res = reg.call("conductor.summon_many", role="M", why="探针：三个实例同波",
                   targets=[{"target_role": "E", "action": "list_experiments", "instance": str(i)}
                            for i in (1, 2, 3)])
    assert res.ok, res.error
    data = res.data
    assert data["count"] == 3 and len(data["results"]) == 3
    assert data["waves"] == [3], data["waves"]
    assert data["concurrent_peak"] == 3, data["concurrent_peak"]
    assert [r["instance"] for r in data["results"]] == ["1", "2", "3"]
    assert all(r["status"] == "done" and r["outcome"] == "ok" for r in data["results"])
    assert len({r["task_id"] for r in data["results"]}) == 3
    assert len(store.rows("tasks")) == 3


def test_summon_many_auto_assigns_instances_for_a_repeated_role(tmp_path: Path):
    """正控（自动实例标签，2026-09-30）：同一角色在一批里出现多次、没给标签 ⇒ 自动补序号。

    为什么要这条：模型写一批 target 时经常不写 `instance`，而"同角色不同实例"
    是并发的唯一开关 —— 不补的话三个 B 会被排成三波串行，而台账看起来是
    "派了三份活、都成功了"（一种不会报错的失败）。判据：`waves == [3]`、
    `concurrent_peak == 3`，且每一项都标了 `auto_instance=True`。
    """
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    res = reg.call("conductor.summon_many", role="M",
                   targets=[{"target_role": "E", "action": "list_experiments"} for _ in range(3)])
    assert res.ok, res.error
    assert res.data["waves"] == [3], res.data["waves"]
    assert res.data["concurrent_peak"] == 3, res.data["concurrent_peak"]
    assert [r["instance"] for r in res.data["results"]] == ["E#1", "E#2", "E#3"]
    assert all(r["auto_instance"] is True for r in res.data["results"])
    assert len(store.rows("tasks")) == 3


def test_summon_many_does_not_relax_cross_role_conflicts(tmp_path: Path):
    """负控（自动标签不许顺手放宽跨角色）：A 与 B 都写 `literature` ⇒ 仍必须分波串行。

    自动补标签解决的是"同角色的 N 个实例"，不是"不同角色会不会改同一张表"。
    这条与 `test_scheduler.py::test_instance_axis_only_relaxes_the_same_role` 同族，
    只是换到工具面上再验一遍。
    """

    class _A:
        def run_once(self) -> dict:
            return {"outcome": "ok"}

    class _B:
        def run_once(self) -> dict:
            return {"outcome": "ok"}

    store, _c, reg = _wired(tmp_path, role_registry={"A": ("object", _A()),
                                                     "B": ("object", _B())})
    res = reg.call("conductor.summon_many", role="M",
                   targets=[{"target_role": "A", "action": "run_once"},
                            {"target_role": "B", "action": "run_once"}])
    assert res.ok, res.error
    assert res.data["waves"] == [1, 1], res.data["waves"]
    assert res.data["concurrent_peak"] == 1, res.data["concurrent_peak"]
    assert all(r["auto_instance"] is False for r in res.data["results"]), res.data["results"]


def test_summon_many_refuses_a_bad_target_shape(tmp_path: Path):
    """负控（参数）：targets 里塞一个非对象 ⇒ 当场拒绝（不许静默跳过那一项）。

    工具层把异常转成 `ok=False` 的结果（不抛给调用方）—— 所以判据看 `ok` 与 `error`，
    并且要确认一条任务都没落（"拒绝了"与"跳过那一项、其余照跑"是两回事）。
    """
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    res = reg.call("conductor.summon_many", role="M", targets=["E.list_experiments"])
    assert res.ok is False and res.error, res
    assert "targets" in str(res.error) and "对象" in str(res.error), res.error
    assert store.rows("tasks") == []


def test_ledger_relays_view_reports_pending_and_fulfilled(tmp_path: Path):
    """代唤申请的可判定视图（§199）：留言是给人看的，这个视图是给主控看的。

    判据：一条 `agent_summon_request` 算"已受理"，当且仅当台账里存在一条同
    (角色, 动作) 且 `started_at >= 申请时刻` 的任务行。三态：读不到会话目录时
    `relay_pending` 必须是 `None`（没查成），不是 `0`（没有申请）。
    """
    from agentflow import schema as S
    from agentflow import sessions as SS

    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    root = Path(store.root)
    SS.append(root, {"kind": "agent_summon_request", "role": "H", "wants_role": "A",
                     "wants_action": "run_once", "refusal_reason": "forbidden_edge",
                     "ts": "2026-01-01T00:00:00+00:00"}, sid="probe")

    # ① 还没有人派 A ⇒ 待受理 1 条
    got = reg.call("conductor.ledger", role="M", view="relays")
    assert got.ok, got.error
    assert got.data["relay_pending"] == 1, got.data
    assert got.data["relays"][0]["fulfilled"] is False, got.data["relays"]

    # ② 台账里出现一条之后的 A.run_once ⇒ 视为已受理（判据是台账事实，不是承诺）
    with store.tx("tasks", actor="probe") as tx:
        row = S.Task(task_id="t-9001", role="A", action="run_once", called_by="M",
                     status="done", outcome="ok", input_key="A.run_once",
                     detail="探针：模拟主控替 H 派了 A",
                     started_at="2026-01-01T00:00:01+00:00",
                     ended_at="2026-01-01T00:00:02+00:00").to_dict()
        tx.upsert("tasks", row)
    got2 = reg.call("conductor.ledger", role="M", view="relays")
    assert got2.data["relay_pending"] == 0, got2.data
    assert got2.data["relays"][0]["fulfilled"] is True, got2.data["relays"]
    assert got2.data["relays"][0]["fulfilled_by_task"] == "t-9001"

    # ③ 负控（三态）：会话目录不在 ⇒ `None`（没查成），不是 0
    import shutil

    shutil.rmtree(root / "sessions")
    got3 = reg.call("conductor.ledger", role="M", view="relays")
    assert got3.data["relay_pending"] is None, got3.data
    assert got3.data["relay_note"], got3.data


def test_summon_without_wiring_refuses_and_still_writes_the_row(tmp_path: Path):
    """负控：角色没接线 ⇒ refused/not_wired，而且拒绝也落台账（不许静默）。"""
    store, _c, reg = _wired(tmp_path)
    res = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert res.ok, res.error
    assert res.data["outcome"] == "refused" and res.data["refusal_reason"]
    rows = store.rows("tasks")
    assert len(rows) == 1, "拒绝也是一次召唤，必须留痕"
    assert rows[0]["outcome"] == "refused"


def test_summon_refuses_illegal_targets(tmp_path: Path):
    """负控：派给不可召唤的角色（主控自己）与不存在的动作 ⇒ 都被拒。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    to_m = reg.call("conductor.summon", role="M", target_role="M", action="list_experiments", input_key="E.list_experiments")
    assert to_m.data["outcome"] == "refused", to_m.data
    bad_action = reg.call("conductor.summon", role="M", target_role="E", action="没有这个动作", input_key="x")
    assert bad_action.data["outcome"] == "refused"
    assert "unknown_action" in str(bad_action.data["refusal_reason"])


def test_stop_is_graceful_and_idempotent(tmp_path: Path):
    """优雅停止：停后再派活不产生新任务、无僵尸行、有续跑简报、第二次不改理由。"""
    _store, c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")

    first = reg.call("conductor.stop", role="M", reason="user")
    assert first.ok, first.error
    assert first.data["verify"] == [], "停止后不许留 running/pending 的僵尸行"
    brief_path = Path(first.data["resume_brief"]["path"])
    assert brief_path.is_file(), "优雅停止必须留下续跑简报（否则就是粗暴 kill）"

    # ① 停后不再新开任务：再派一次，台账不许多一行
    before = len(c.tree())
    again = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert again.data["outcome"] in ("cancelled", "refused")
    assert len(c.tree()) == before, "停止之后不许再产生新任务"

    # ⑤ 幂等：第二次 stop 不改第一次的理由
    second = reg.call("conductor.stop", role="M", reason="budget")
    assert second.data["detail"] == first.data["detail"]
    assert second.data["reason"] == "user"


def test_resume_brief_reads_back_what_stop_wrote(tmp_path: Path):
    """续跑简报读得回来，且带"做了什么"的事实（不是建议）。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    reg.call("conductor.stop", role="M", reason="user")
    got = reg.call("conductor.resume_brief", role="M")
    assert got.ok and got.data["present"] is True
    brief = got.data["brief"]
    assert brief["tasks_total"] == 1
    assert brief["outcome_counts"].get("ok") == 1
    assert "how_to_continue" in brief


def test_ensure_project_decides_cold_then_warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """冷/热由 M 决定：第一次冷启动建目录，第二次热启动复用；四态如实给。"""
    monkeypatch.setenv("AGENTFLOW_PROJECTS_DIR", str(tmp_path / "projects"))
    _store, _c, reg = _wired(tmp_path)
    cold = reg.call("conductor.ensure_project", role="M", project_name="project1", start="cold")
    assert cold.ok, cold.error
    assert cold.data["mode"] == "cold" and cold.data["created"] is True
    assert cold.data["state"] == "workspace"

    warm = reg.call("conductor.ensure_project", role="M", project_name="project1", start="auto")
    assert warm.data["mode"] == "warm" and warm.data["created"] is False
    assert warm.data["state"] == "workspace"


def test_ensure_project_refuses_foreign_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """负控：目录不空且不是本框架的工作区 ⇒ 明确失败，绝不被当工作区初始化。"""
    root = tmp_path / "projects"
    foreign = root / "manual-notes"
    foreign.mkdir(parents=True)
    (foreign / "notes.txt").write_text("别人的东西", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_PROJECTS_DIR", str(root))
    _store, _c, reg = _wired(tmp_path)

    res = reg.call("conductor.ensure_project", role="M", project_name="manual-notes", start="auto")
    assert res.ok is False, "存在但不是工作区时必须失败"
    assert "manual-notes" in str(res.error)
    assert sorted(p.name for p in foreign.iterdir()) == ["notes.txt"], "绝不往别人的目录里写东西"


def test_ensure_project_refuses_inside_an_existing_workspace(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """正控（`draft/37` §37.4 ④ / §41）：已经在项目里、又没说项目落哪 ⇒ 拒绝，且一个目录都不建。

    这条门是怎么来的（不是设计洁癖，是真机读数）：
    `projects_dir` 的缺省不是当前工作区，而是 `projects.projects_dir(None)`
    —— 一个与本工作区无关的默认落点。于是 M 在一个已存在的工作区里调这一件，
    得到的是在别处新建的一个空项目，而不是"热启动当前项目"：

    - §37 那趟真机 23 步里有 4 步在 `ensure_project`，其中一次真的建出了
      `D:\\Incubator\\projects\\project11`（`project.json` 的 `created_at`
      与那次运行同秒级）。当时账本上没有任何一步显示"我建了个项目"。
    - 同一天本仓库自己的普查探针（没给 `projects_dir`）也建了 `project12`/`project13`
      —— 写探针的人同样踩，说明缺省值才是因。

    判据取三条，缺一条都算这件事没修好：
    1. `ok is False` 且 `kind == "already_a_project"`（不是含糊的失败）；
    2. 缺省落点里一个条目都没多（"拒绝了但顺手建了目录"是最坏的形态）；
    3. 消息里点名出口（显式给 `projects_dir`）—— 只会说"不行"的守卫会把人卡死。
    """
    projects_root = tmp_path / "default-projects"
    projects_root.mkdir()
    monkeypatch.setattr(P, "DEFAULT_PROJECTS_DIR", projects_root, raising=True)
    monkeypatch.delenv(P.ENV_PROJECTS_DIR, raising=False)
    before = sorted(p.name for p in projects_root.iterdir())

    # 工作区必须是另一个目录：`Store.init()` 会拒绝在非空目录里建工作区
    # （`draft/28` §136.3 事故 B 那道闸）。夹具自己先撞一次那条闸，是这道守卫值钱的旁证。
    store, _c, reg = _wired(tmp_path / "ws")
    assert P.classify(store.root)[0] == "workspace", "夹具前提：当前根确实是一个工作区"

    res = reg.call("conductor.ensure_project", role="M", start="auto")
    assert res.ok is False, res
    assert res.meta.get("kind") == "already_a_project", res.meta
    err = str(res.error or "")
    assert "不要另建项目" in err and "projects_dir" in err, err
    assert sorted(p.name for p in projects_root.iterdir()) == before, (
        "拒绝时必须一个目录都不建（缺省落点里多了东西就是没修好）")


def test_ensure_project_still_works_when_the_landing_is_explicit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """负控（守卫不能是"一律拒绝"）：显式说清项目落哪 ⇒ 冷启动照旧能建。

    这也是既有两条用例（`test_ensure_project_decides_cold_then_warm` /
    `test_ensure_project_refuses_foreign_directory`）赖以成立的形态：
    它们在一个工作区里、把项目建到另一个显式指定的目录，是正当用法。
    """
    monkeypatch.delenv(P.ENV_PROJECTS_DIR, raising=False)
    landing = tmp_path / "elsewhere"
    _store, _c, reg = _wired(tmp_path)

    res = reg.call("conductor.ensure_project", role="M", project_name="p1", start="cold",
                   projects_dir=str(landing))
    assert res.ok, res.error
    assert res.data["created"] is True and res.data["mode"] == "cold"
    assert (landing / "p1" / ".agentflow-workspace").is_file(), "显式落点下必须真的建出来"

    # 环境变量同样是"操作者说了落在哪"的一种说法（CI / 本机配置都走它）。
    env_landing = tmp_path / "via-env"
    monkeypatch.setenv(P.ENV_PROJECTS_DIR, str(env_landing))
    res2 = reg.call("conductor.ensure_project", role="M", project_name="p2", start="cold")
    assert res2.ok, res2.error
    assert (env_landing / "p2" / ".agentflow-workspace").is_file()


def test_conductor_selftest_passes_and_has_teeth(monkeypatch: pytest.MonkeyPatch):
    """正控 + 两条负控（`draft/37` §41）：工具模块的自检必须是绿的，而且真的在看东西。

    这一件 2026-10-02 之前恒返回 1：里面写死"应有 9 个"，而编排面早就是 11 件了 ——
    而全仓没有任何判据跑 `tools/*_tools.py` 的 `selftest()`（13 个工具模块里只有这一个有），
    于是它烂在那里没人看见。一条恒红的自检与一条恒绿的自检一样没有信息量。

    两条负控分别盯它现在真在看的两个方向（不是"把数字改小就红"那种假牙）：
    ① 注册面比声明面少一件（`register` 漏了一件）⇒ 必须红；
    ② 只读角色拿到主控工具（权限泄漏）⇒ 必须红。
    """
    assert CT.selftest() == 0

    real_register = CT.register

    def _dropping(registry, **kw):
        return real_register(registry, **kw)[:-1]

    monkeypatch.setattr(CT, "register", _dropping, raising=True)
    assert CT.selftest() == 1, "少注册了一件而自检仍然绿 ⇒ 这条自检没有牙"
    monkeypatch.undo()

    def _leak_probe() -> object:
        return CT.ok()

    _leak_probe.__tool_spec__ = dataclasses.replace(  # type: ignore[attr-defined]
        CT.conductor_state.__tool_spec__, name="conductor.leak_probe", roles=("C",))
    monkeypatch.setattr(CT, "_TOOL_FUNCTIONS",
                        (*CT._TOOL_FUNCTIONS, (_leak_probe, ())), raising=True)
    assert CT.selftest() == 1, "只读角色拿到了主控工具而自检仍然绿 ⇒ 权限那条检查是空转的"


def test_conductor_hand_line_lists_its_real_write_tools(tmp_path: Path):
    """正控 + 红线（`draft/37` §41）：M 的「手」那一档必须与它真拿到的写工具一致。

    这一条与 `tests/test_agent_prompts.py::test_the_conductor_hand_is_minor_not_a_forbidden_line`
    是一对，差别只在注册表：那一份不带 `workspace_root`（没有 fs 工具），
    这一份带 —— 于是它能核到用户裁定给 M 的那支笔（`fs.write`）真的出现在提示词里。
    两半合起来才是"提示词与工具面一致"这件事的完整判据。

    红线那一半（负控）：M 的写工具清单里不许出现任何领域写工具 ——
    `table.*`（知识表）、`doc.build_document`（稿件）、`fs.edit` / `fs.delete` / `fs.move`
    都不在它的面上。"有笔"不等于"有知识表写面"，这正是 §38 那条被收窄
    （而不是作废）的红线。
    """
    from agentflow import agent_prompts as AP

    _store, _c, reg = _wired(tmp_path)
    assert AP.FACULTY_EMPHASIS["M"]["手"] == "minor", "档位必须与工具面一致（denied 会印成结构禁止）"
    text = AP.faculties_text("M", reg)
    hand_line = next((ln for ln in text.splitlines() if "手＝" in ln), "")
    assert hand_line, f"次要官能那一行里没有'手'：{text[-300:]}"
    for name in ("conductor.summon", "conductor.summon_many", "fs.write", "fs.edit"):
        assert name in hand_line, (name, hand_line)
    for name in ("table.create", "table.update", "doc.build_document",
                 "fs.delete", "fs.move"):
        assert name not in hand_line, (name, hand_line)
    assert "可改 7 件" in hand_line, hand_line


def test_state_and_role_spec_are_read_only_views(tmp_path: Path):
    """状态视图与角色规格：都与既有单一来源同源，且不写任何字节。"""
    store, _c, reg = _wired(tmp_path)
    st = reg.call("conductor.state", role="M")
    assert st.ok and st.data["tables"].get("tasks") == 0
    spec = reg.call("conductor.role_spec", role="M", role_name="C")
    actions = {a["action"] for a in spec.data["actions"]}
    assert "hottest" in actions, "角色规格必须来自 capabilities"
    assert spec.data["summonable"] is True
    assert reg.call("conductor.role_spec", role="M", role_name="M").data["summonable"] is False
    assert len(store.rows("tasks")) == 0, "只读视图不许写台账"


def test_state_shows_the_request_queues_backlog(tmp_path: Path):
    """判据（`draft/39` §6.45 的 D56）：状态视图要读出「队列里还有几条没人做」。

    为什么需要这一格：`tables` 只给行数 —— `search_requests: 4` 读不出"其中 1 条
    `done=false`"。真机读数（T5 第 5 趟 `p8e-fermat-shorter-proof`）：F 的攻坚子目标
    用 `submit_search_request` 提了一条请求，整趟没人做，计划停在「等 A 完成检索请求」，
    而主控的眼睛（状态视图）与收工门都看不出这件事。
    """
    store, _c, reg = _wired(tmp_path)
    with store.tx("search_requests", actor="agent-F", note="probe") as tx:
        tx.upsert("search_requests", {
            "request_id": "r-0001", "timestamp": "2026-10-06T00:00:00+08:00",
            "topic": "a", "mode": "precise", "content_description": "probe a",
            "done": True, "outcome": "ok", "submitted_by": "agent-A", "attempts": 1,
            "result_lit_ids": ["0000"], "priority": "low", "submit_note": "",
        }, note="probe")
        tx.upsert("search_requests", {
            "request_id": "r-0002", "timestamp": "2026-10-06T00:00:01+08:00",
            "topic": "b", "mode": "precise", "content_description": "probe b",
            "done": False, "submitted_by": "agent-F", "attempts": 0,
            "result_lit_ids": [], "priority": "low", "submit_note": "",
        }, note="probe")

    st = reg.call("conductor.state", role="M")
    queues = st.data["queues"]
    assert queues["search_requests"]["rows"] == 2, queues
    assert queues["search_requests"]["unfinished"] == 1, queues
    assert queues["search_requests"]["unfinished_ids"] == ["r-0002"], queues
    assert queues["search_requests"]["submitted_by"] == ["agent-F"], queues
    # 两条队列都要出现在读数里（重抽取那条今天 0 条 —— 0 是读数，不是"没查成"）
    assert queues["reprocess_requests"]["rows"] == 0, queues
    assert queues["reprocess_requests"]["unfinished"] == 0, queues
    assert "run_once" in queues["note"], queues
    del store


def test_ledger_views(tmp_path: Path):
    """台账四个视图都能出读数（tree/stats/issues/verify）。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    for view in ("tree", "stats", "issues", "verify"):
        got = reg.call("conductor.ledger", role="M", view=view)
        assert got.ok, (view, got.error)
        assert got.data["task_count"] == 1


def test_capabilities_unchanged_for_the_conductor(tmp_path: Path):
    """红线：主控拿到工具没有改变"它不产出领域对象"这条约束。"""
    assert C.CAPABILITIES["M"] == ()
    assert not C.WRITE_SETS["M"], "主控的领域写集必须仍为空"
    assert C.CONDUCTOR_WRITE_SET == frozenset({"tasks"})
    assert "M" in C.NON_SUMMONABLE, "主控仍不可被召唤"


def test_resume_brief_absent_is_reported_honestly(tmp_path: Path):
    """没有停止过就没有简报：如实说"没有"，不许编一份空的当有。"""
    _store, _c, reg = _wired(tmp_path)
    got = reg.call("conductor.resume_brief", role="M")
    assert got.ok and got.data["present"] is False
    assert got.data["brief"] == {}
    assert json.dumps(got.data, ensure_ascii=False)

