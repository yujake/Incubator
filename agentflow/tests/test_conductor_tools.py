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
    "conductor.closing",
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
    assert "五条" not in text, "描述里还写着旧条数（五条）—— 条数一变它就是假的"


def test_m_tool_surface_is_orchestration_only(tmp_path: Path):
    """M 拿到的正好是 `M_TOOL_FACE`（编排面 11 + 文件面白名单 6）；只读角色拿不到编排面工具。

    这条判据改过两次：2026-10-02 按用户裁定（`draft/37` §38）从"只有 `conductor.*`"
    变成"`conductor.*` + 文件面白名单五件"；2026-10-03 按 §57 的裁定再加一件 `fs.edit`
    （真机读数：`fs.write` 单独改不了 26 KB 的稿子）。两次扩的都不是"能不能碰盘"这条
    边界，而是边界的口径 —— `fs.delete` / `fs.move` 仍然一件不给（`M_TOOL_FACE` 里
    没有它们，而这里的断言是相等，所以多一件就会红）。
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

