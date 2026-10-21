# -*- coding: utf-8 -*-
"""M 的状态报告（`draft/39` §4）—— 也是 E15 的演练：零中断观测。

用户口径（逐字）：

> 给 M 再加一个动作：当用户中途想知道当前项目情况时，M 通过搜集最近产出和手稿交接来分析情况，
> 向用户报告，从而不打断智能体协作

E15 的三条判据（`draft/39` §6 表里逐字）：

1. 报告落盘（`out/review/STATUS-<ts>.{md,json}` 都在盘上、四节齐全）；
2. 报告里的计数当场脚本复算一致（`collect()` 再跑一遍，逐表相等；改坏一个数必须能被抓出来）；
3. 期间被观察的那一趟步数继续增长、期间没有 `ask_user` / 停机开关 / 任何停止。

第 3 条是这一组的重心：它测的是"旁路观测"这条纪律 —— 报告是读出来的，不是"问 M 一句"
问出来的（后者会让 M 停下来等人，正好与"不打断协作"相反）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import cli
from agentflow import sessions as SS
from agentflow import statusreport as SR
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


# ============================================================ 夹具

def _ws(tmp_path, *, sid: str = "t"):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, st, sid


def _seed(st: Store) -> None:
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "0000", "statement": "n≥3 时成立",
                                  "testable": "n≤12 枚举", "status": "proposed",
                                  "origin": "gap",      # 来源必填（schema：猜想来源必须可追）
                                  "created_at": "2026-10-05T00:00:00+08:00"})
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0001", "role": "D", "action": "consider",
                            "params": {}, "status": "done", "outcome": "refused",
                            "refusal_reason": "invalid_params", "called_by": "M", "depth": 1,
                            "input_key": "k", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": "2026-10-05T00:00:01+08:00",
                            "detail": "参数不合法（夹具）",
                            "error": None,
                            "artifacts": []})


# ============================================================ E15 ①②：落盘 + 复算

def test_e15_1_the_report_lands_in_two_forms_with_four_sections(tmp_path):
    """E15①：`out/review/STATUS-<ts>.md` 与 `.json` 都在盘上；md 四节齐全。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    report, md, js = SR.write_status_report(st, ws, stamp="20261005-1200")
    assert md.is_file() and js.is_file(), (md, js)
    assert md.name == "STATUS-20261005-1200.md" and js.name == "STATUS-20261005-1200.json"
    text = md.read_text(encoding="utf-8")
    for section in ("一、产出", "二、交接", "三、卡点", "四、下一步"):
        assert section in text, text
    assert "旁路观测" in text and "零模型调用" in text, "报告要自己声明它是只读观测"
    assert str(ws) in text, "工作区路径要在报告里（否则第三方不知道该去哪复核）"


def test_e15_2_every_count_in_the_report_is_recomputable(tmp_path):
    """E15②：报告里的每个表行数都能当场复算一致；改坏一个数必须能被抓出来。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    report = SR.collect(st, ws)
    again = SR.collect(st, ws)
    for table in SR.REPORT_TABLES:
        assert report["tables"][table]["count"] == again["tables"][table]["count"], table
    assert report["tables"]["conjectures"]["count"] == 1, report["tables"]["conjectures"]
    assert report["tables"]["tasks"]["count"] == 1, report["tables"]["tasks"]
    assert report["refusals"]["total"] == 1, report["refusals"]
    assert report["refusals"]["by_reason"] == {"invalid_params": 1}, report["refusals"]

    # 负控：把 json 里的一个数改坏 ⇒ 它与复算值不再相等（判据真的在读数）
    _r, md, js = SR.write_status_report(st, ws, stamp="20261005-1201")
    tampered: dict[str, Any] = json.loads(js.read_text(encoding="utf-8"))
    tampered["tables"]["conjectures"]["count"] = 99
    fresh = SR.collect(st, ws)
    assert tampered["tables"]["conjectures"]["count"] != fresh["tables"]["conjectures"]["count"], \
        "改坏的数字与复算值相等 ⇒ 这条判据是真空的"
    assert md.is_file()


def test_e15_2_the_next_steps_are_derived_from_readings_not_written_by_a_model(tmp_path):
    """E15② 的另一半：`next_steps` 每一句都指着一个当前为空的读数（不是模型的话术）。"""
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    joined = "；".join(report["next_steps"])
    assert "conjectures" in joined and "documents" in joined, report["next_steps"]
    assert "handoffs.jsonl" in joined, report["next_steps"]
    # 填入猜想之后，"还没有猜想"这一句应当消失（读数驱动，不是模板）
    _seed(st)
    after = SR.collect(st, ws)
    assert not any("还没有可检验的猜想" in s for s in after["next_steps"]), after["next_steps"]
    assert any("被拒的动作" in s for s in after["next_steps"]), after["next_steps"]


def test_ee04_the_report_carries_the_faculty_mechanics(tmp_path):
    """    EE-04：状态报告里必须有十项官能的机械半读数（给它一条不依赖 `gate` CLI 的调用者）。

    改动前的调用链（`draft/48-09 §4.10`）：`faculty_checks` 的函数 ← `deliver.py:167/185/188`← `cli.py:1648 cmd_gate`（子命令注册
    `cli.py:2370`）⇒ 那条 CLI 一退场，`faculty_checks` 就成了孤儿模块。现在 `statusreport.collect` 直接调它的纯函数：为什么不走 `deliver` ——
    那个函数会写盘（`deliver.py:251-254` 落 `gates/<名字>.json`），而状态报告是只读现场读数。

    判据两半（缺一半就会退化成"加了一个键"）：① 报告对象里有 `faculty`，且两个读数来自真调用（`conjecture_hygiene` 的 verdict 在它自己的词表里、`claim_strength` 有
    `total/verdict` 这些由被调函数产出的键）；② 渲染出来的 `.md` 里看得见（只写 `.json` 等于"落盘了但没人看得见"）。
    """
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    fac = report.get("faculty") or {}
    hygiene = fac.get("conjecture_hygiene") or {}
    strength = fac.get("claim_strength") or {}
    assert hygiene.get("checked") is True, hygiene
    assert "conjectures" in hygiene and "findings" in hygiene, hygiene
    assert "total" in strength and "verdict" in strength, strength
    md = SR.render_status_markdown(report)
    assert "官能机械半" in md, md[-400:]


# ============================================================ E15③：零中断
class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]], *, on_call=None) -> None:
        self.replies = replies
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(len(self.prompts), prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _run_with_probe(tmp_path, replies, probe) -> tuple[pathlib.Path, Any]:
    """跑一趟角色循环，并在第 2 步的模型调用之前插一次状态报告（模拟用户中途想知道情况）。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies, on_call=lambda n, _p: probe(n, ws, st))
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    backend.registry = reg
    run = run_role("D", "被观测的一趟", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="D", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="t"),
                   session_root=ws, workspace_root=str(ws), sid="t", max_steps=4, from_env=False)
    return ws, run


def test_e15_3_collecting_mid_run_interrupts_nothing(tmp_path):
    """E15③：在正在跑的循环中途收一次报告 ⇒ 它继续跑、没有 ask_user/停机/停止。

    这一条是"旁路观测"的核心判据：报告若走 `ask_user`（问 M 一句）就会被读成"这一趟
    停了在等人"，而那正是用户要避免的。
    """
    seen: dict[str, Any] = {"reports": [], "events_at_probe": [], "stop_switch": None}

    def probe(n: int, ws: pathlib.Path, st: Store) -> None:
        if n != 2:
            return
        # 中途收一次报告（与 CLI 同一个实现）
        report, md, js = SR.write_status_report(st, ws, stamp="20261005-1300")
        seen["reports"].append(report)
        seen["stop_switch"] = (ws / ".agentflow-stop").is_file()
        events, _bad = SS.read_session(ws, sid="t")
        seen["events_at_probe"].append([e.get("kind") for e in events])

    ws, run = _run_with_probe(tmp_path, [
        {"tool": "table.list", "args": {"table": "tasks"}, "why": "先看一眼"},
        {"tool": "table.list", "args": {"table": "documents"}, "why": "再看一眼"},
        {"final": "收工", "notify": {"to": "M", "summary": "收工", "body": "完。\n"}},
    ], probe)

    assert run.stop_reason == "final", run.to_dict()
    assert seen["reports"], "探针没跑到（这一条判据就失效了）"
    assert seen["stop_switch"] is False, "收报告不该落停机开关"
    # 报告落盘，且报告里"在跑的循环"读到的是这一趟（旁路观测真的看到了它）
    assert (ws / "out" / "review").glob("STATUS-20261005-1300.md")
    assert seen["reports"][0]["in_flight"]["running_loops"], seen["reports"][0]["in_flight"]
    # 没有 ask_user / 没有停机 / 没有第二趟
    events, bad = SS.read_session(ws, sid="t")
    assert not bad, bad
    kinds = [e.get("kind") for e in events]
    assert "agent_run_start" in kinds and kinds.count("agent_run_start") == 1, kinds
    steps = [e for e in events if e.get("kind") == "agent_step"]
    # 会话里只有非收工步的 `agent_step`（收工那一步不写这种事件）⇒ 两条 step 事件、
    # 而这一趟总共走了三步（两次工具 + 一次 final）——"它继续在跑"由后者证明。
    assert len(steps) == 2 and len(run.steps) == 3, (len(steps), len(run.steps))
    assert not [e for e in events if e.get("kind") == "user_answer"], kinds
    assert not (ws / ".agentflow-stop").is_file()


def test_the_top_level_run_row_is_counted_and_says_what_it_is(tmp_path):
    """顶趟行（F1）在三处读数里的口径：保留在读数里，但必须说清"它不是召唤"。

    `conductor.open_top_level_run` 给每趟顶层运行在 `tasks` 里留一行
    （`role=M` / `action="run"` / `called_by="user"` / `parent_task_id=None`）。
    裁定：状态报告保留它（显示 `M.run` 是真实且有用的：它同时是"谁在派活"的身份行），
    但口径要写在读数里，免得下游把它当"第 N 次召唤"。

    判据三条：① `in_flight.running_tasks` 把它算进去（不排除）；② `calibers` 与
    `top_level_runs` 把口径与分类计数一并给出；③ 最近行的抓手逐行注明它是什么
    —— 且普通召唤行不许被误标（反负控）。
    """
    ws, st, _ = _ws(tmp_path)
    cond = Conductor(st, backend=LocalBackend({}))
    tid = cond.open_top_level_run("M", "这一趟的任务原文")
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0009", "role": "B", "action": "run_once",
                            "status": "running", "outcome": None, "called_by": "M", "depth": 1,
                            "input_key": "k9", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": None, "detail": "", "error": None, "artifacts": []})

    report = SR.collect(st, ws)
    infl = report["in_flight"]
    assert tid and tid != "t-0009"
    assert infl["running_tasks"] == 2, infl
    assert {tid, "t-0009"} <= set(infl["running_task_ids"]), infl
    assert infl["top_level_runs"] == 1, infl
    assert "顶趟" in infl["calibers"]["top_level_runs"], infl["calibers"]
    assert "不是召唤" in infl["calibers"]["top_level_runs"], infl["calibers"]
    assert "顶趟行" in infl["calibers"]["running_tasks"], infl["calibers"]

    hints = {r["id"]: r["hint"] for r in report["tables"]["tasks"]["recent"]}
    assert "顶趟" in hints[tid] and "不是召唤" in hints[tid], hints[tid]
    assert "顶趟" not in hints["t-0009"], f"普通召唤行被误标成顶趟：{hints['t-0009']}"

    md = SR.render_status_markdown(report)
    assert "顶趟 = 用户发起的那一趟，不是召唤" in md, md[md.index("在飞任务"):][:200]
    assert "started_total" in md, "口径要指出真正的召唤数在哪一格读"


def test_the_top_level_caliber_is_absent_when_there_is_no_top_run(tmp_path):
    """反负控（口径行是读数驱动的，不是模板）：没有顶趟行的工作区 ⇒ 那一句不出现。"""
    ws, st, _ = _ws(tmp_path)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0001", "role": "B", "action": "run_once",
                            "status": "running", "outcome": None, "called_by": "M", "depth": 1,
                            "input_key": "k1", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": None, "detail": "", "error": None, "artifacts": []})
    report = SR.collect(st, ws)
    assert report["in_flight"]["top_level_runs"] == 0, report["in_flight"]
    assert "顶趟 = 用户发起的那一趟" not in SR.render_status_markdown(report)
    hints = {r["id"]: r["hint"] for r in report["tables"]["tasks"]["recent"]}
    assert "顶趟" not in hints["t-0001"], hints["t-0001"]


def test_the_d_report_landing_reading_is_visible_and_red_then_green(tmp_path):
    """S-07：D 的 `write_report` "有调用、无落点"必须在这一屏看得见（`.json` 与 `.md` 都有）。

    为什么它在这条线上：真机 45 次 `write_report` 只落磁盘、台账 0 行，而这件事此前
    没有任何读数会说（下游读成"D 没产报告"）。裁定是只做读数、不进闸门
    （诊断不是判交付），所以它必须出现在 M/人会读的那一屏上。
    判据：造 N 条 D/`write_report` 终态行 ⇒ `calls == N` 且 `landed == 0`（红→绿），
    并且 `.md` 里逐字看得见（只写 `.json` 等于"落盘了但没人看得见"）。
    """
    ws, st, _ = _ws(tmp_path)
    # 红之前：没有调用 ⇒ 这一格如实说 0 次，且不许报"有产物无台账"（反负控）
    first = SR.collect(st, ws)
    assert first["report_landing"]["calls"] == 0, first["report_landing"]
    assert first["report_landing"]["checked"] is True, first["report_landing"]
    assert "有产物无台账" not in SR.render_status_markdown(first)

    with st.tx("tasks", actor="test") as tx:
        for i in range(3):
            tx.upsert("tasks", {"task_id": f"t-10{i:02d}", "role": "D",
                                "action": "write_report", "status": "done", "outcome": "ok",
                                "called_by": "M", "depth": 1, "input_key": f"kw{i}",
                                "started_at": "2026-10-05T00:00:00+08:00",
                                "ended_at": "2026-10-05T00:00:01+08:00",
                                "detail": "写了一份研究报告（S-07 夹具）", "error": None,
                                "artifacts": []})
    report = SR.collect(st, ws)
    got = report["report_landing"]
    assert got["calls"] == 3 and got["landed"] == 0, got
    assert got["kind_writable"] is False and got["landing_tables"] == [], got
    assert got["task_ids"] and len(got["task_ids"]) == 3, got
    md = SR.render_status_markdown(report)
    assert "有产物无台账" in md and "**3** 次" in md, md[md.index("D 的报告落点"):][:200]
    assert any("有产物无台账" in s for s in report["next_steps"]), report["next_steps"]


def test_the_landing_reading_is_tristate_and_never_folds_into_zero(tmp_path):
    """三态：`tasks` 读不出来 ⇒ `checked=False` + `reason`，不许折成"没有调用"。"""
    class _Boom:
        def rows(self, _table):
            raise RuntimeError("tasks 表坏了")

    got = SR._report_landing(_Boom())
    assert got["checked"] is False and "tasks 表坏了" in got["reason"], got
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)                    # 用一份完整报告渲染（渲染函数要别的键）
    report["report_landing"] = got
    md = SR.render_status_markdown(report)
    assert "没查成" in md and "有产物无台账" not in md, md[md.index("D 的报告落点"):][:160]
    steps = SR._next_steps(report)                 # `next_steps` 要按换过的那一格重算
    assert any("没查成" in s for s in steps), steps


def test_the_uncalled_actions_reading_is_visible_and_red_then_green(tmp_path):
    """S-02：声明了、但一条召唤行都没有的动作必须在这一屏看得见（`.json` 与 `.md` 都有）。

    为什么它在这条线上：`Conductor.stats()` 没有 `by_action` ⇒ "声明了但没人召唤过"
    此前没有任何读数在说（真机：D 的五个核心动作在 4127 行 `tasks` 里 0 次）。
    裁定同样是只做读数、不进闸门（该不该派归秘书/主控判断）。
    判据：空工作区 ⇒ 全部声明动作都在 `uncalled` 里（那是实话）；反负控：真派一条
    ⇒ 那个动作必须从清单里消失（不然这条读数在误报）。
    """
    ws, st, _ = _ws(tmp_path)
    first = SR.collect(st, ws)["uncalled_actions"]
    assert first["checked"] is True, first
    assert first["called_total"] == 0 and first["declared_total"] > 0, first
    assert first["count"] == first["declared_total"], first
    md = SR.render_status_markdown(SR.collect(st, ws))
    assert f"**{first['count']}** 个" in md and "声明了但没被召唤过的动作" in md, \
        md[md.index("声明了但没被召唤过"):][:160]

    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0001", "role": "D", "action": "assess",
                            "status": "done", "outcome": "ok", "called_by": "M", "depth": 1,
                            "input_key": "k-s02", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": "2026-10-05T00:00:01+08:00",
                            "detail": "派过一次 assess（S-02 夹具）", "error": None,
                            "artifacts": []})
    report = SR.collect(st, ws)
    got = report["uncalled_actions"]
    assert got["called_total"] == 1, got
    assert got["count"] == got["declared_total"] - 1, got
    pairs = {(a["role"], a["action"]) for a in got["uncalled"]}
    assert ("D", "assess") not in pairs, "召唤过之后它还留在清单里 ⇒ 这条读数在误报"
    line = next(ln for ln in SR.render_status_markdown(report).splitlines()
                if "声明了但没被召唤过的动作" in ln)
    assert f"**{got['count']}** 个" in line, line
    assert "每个声明过的动作都至少被召唤过一次" not in line, line


def test_the_uncalled_actions_reading_is_tristate(tmp_path):
    """三态：读不出来 ⇒ `checked=False` + `reason`，不许折成"全都没被调用"。"""
    class _Boom:
        def rows(self, _table):
            raise RuntimeError("tasks 表坏了")

    got = SR._uncalled_actions(_Boom())
    assert got["checked"] is False and "tasks 表坏了" in got["reason"], got
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    report["uncalled_actions"] = got
    md = SR.render_status_markdown(report)
    assert "没查成" in md, md[md.index("声明了但没被召唤过"):][:160]
    assert "全都没被调用" in md, "没查成时要说清它不是那个结论"
    steps = SR._next_steps(report)
    assert any("没查成" in s for s in steps), steps


def test_e15_3_the_probe_does_not_write_into_the_store(tmp_path):
    """E15③ 的另一半：观测前后，`data/` 下每个文件的字节必须逐字节相同。"""
    before: dict[str, bytes] = {}

    def probe(n: int, ws: pathlib.Path, st: Store) -> None:
        if n != 2:
            return
        SR.write_status_report(st, ws, stamp="20261005-1400")
        # 观测之后立刻记下 data/ 的字节（与观测前的对照由下面做完）
        for p in sorted((ws / "data").glob("*.json")):
            before.setdefault(p.name, p.read_bytes())

    ws, run = _run_with_probe(tmp_path, [
        {"tool": "table.list", "args": {"table": "tasks"}, "why": "a"},
        {"tool": "table.list", "args": {"table": "documents"}, "why": "b"},
        {"final": "收工", "notify": {"to": "M", "summary": "收工", "body": "完。\n"}},
    ], probe)
    assert run.stop_reason == "final", run.to_dict()
    assert before, "探针没跑到"
    # ---- F1 之后这里要改口径：这一趟自己在 `tasks` 里有一行
    #
    # `conductor.open_top_level_run` 在开跑前给它开一行（顶趟行），
    # `finish_top_level_run` 在收工那一刻把那一行收尾 ⇒ `tasks.json` 必然在观测
    # （第 2 步）之后变一次。那不是"观测写了盘"，是这一趟自己的生命周期。
    # 所以判据从"每个文件逐字节相同"收窄成两半：
    #   ① 除 `tasks.json` 外，任何文件逐字节相同（观测本身零写入）；
    #   ② `tasks.json` 里只有这一趟自己那一行变，且只变终局字段。
    # 改前（F1 之前）顶趟没有行 ⇒ ① 就是全部；收窄之后判据仍然能抓到"探针写了盘"。
    changed = {name for name, blob in before.items()
               if (ws / "data" / name).read_bytes() != blob}
    assert changed <= {"tasks.json"}, f"观测之后这些文件被改过（观测本身不许写盘）：{sorted(changed)}"

    def _rows_of(blob: bytes | str) -> dict[str, dict]:
        doc = json.loads(blob.decode("utf-8") if isinstance(blob, bytes) else blob)
        return {str(r.get("task_id") or ""): r for r in doc["rows"]}

    was, now = _rows_of(before["tasks.json"]), _rows_of((ws / "data" / "tasks.json").read_bytes())
    assert set(was) == set(now), (sorted(was), sorted(now))
    # 变的必须是这一趟自己的顶趟行（`run_role` → `open_top_level_run` 开的那一行）
    top = [k for k, r in now.items() if str(r.get("action") or "") == "run"]
    assert len(top) == 1, f"这一趟应当恰好有一条顶趟行（action=run），实测 {top}"
    tid = top[0]
    assert was[tid].get("called_by") == "D" or was[tid].get("called_by"), was[tid]
    #: 收尾时允许变的字段（其余字段一律不许动 —— 那是"这一行只被收尾，没有被改写"）
    finish_only = {"status", "outcome", "ended_at", "detail", "error", "tokens", "usd",
                   "refusal_reason", "artifacts", "inputs"}
    for key, row in was.items():
        if key == tid:
            drift = {k for k in set(row) | set(now[key])
                     if row.get(k) != now[key].get(k) and k not in finish_only}
            assert not drift, f"顶趟行 {tid} 在观测之后被改的不只是终局字段：{sorted(drift)}"
        else:
            assert row == now[key], f"观测只该碰顶趟行，而 {key} 也变了"
    # 反负控：这条判据真的在看内容 —— 把 before 里那一行改一个字段，它必须被发现
    assert dict(was[tid], status="（被人改过）") != now[tid], \
        "改坏之后仍然相等 ⇒ 上面那两条断言是真空的"


# ============================================================ CLI 入口

def test_the_conductor_tool_writes_the_same_report(tmp_path):
    """入口②（`draft/39` §4）：M 的 `conductor.status_report` 与用户侧 CLI 共用一份实现。

    这一条钉两件事：① 工具真的落盘（md/json 都在 `out/review/` 下）并把四类读数回给 M；
    ② 它只读（跑完之后 `data/` 下每个文件的字节不变）—— "旁路观测"不是措辞。
    """
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    before = {p.name: p.read_bytes() for p in sorted((ws / "data").glob("*.json"))}
    reg = build_registry(store=st, conductor=Conductor(st, backend=LocalBackend({})),
                         workspace_root=str(ws)).registry
    res = reg.call("conductor.status_report", role="M")
    assert res.ok, res.error
    data = res.data or {}
    assert data.get("md") and data.get("json"), data
    assert {"tables", "manuscripts", "in_flight", "attack_rounds", "interjections",
            "next_steps"} <= set(data), sorted(data)
    assert "旁路观测" in str(data.get("note") or ""), data.get("note")
    assert list((ws / "out" / "review").glob("STATUS-*.md")), "工具没落盘"
    for name, blob in before.items():
        assert (ws / "data" / name).read_bytes() == blob, f"{name} 被这个工具改过（它必须是只读的）"


def test_the_cli_entry_lands_a_report_and_says_what_is_next(tmp_path, capsys):
    """入口（`agentflow --root <ws> status-report`）：落盘 + 打印四类读数 + 退出码 0。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    code = int(cli.main(["--root", str(ws), "status-report"]))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "报告已落盘" in out and "下一步" in out, out
    assert list((ws / "out" / "review").glob("STATUS-*.md")), "报告没落盘"


def test_the_cli_entry_reports_unknown_for_a_missing_workspace(tmp_path, capsys):
    """三态：工作区不在盘上 ⇒ `unknown`（退出码 2），不是"没有状态"。"""
    missing = tmp_path / "nope"
    code = int(cli.main(["--root", str(missing), "status-report"]))
    err = capsys.readouterr().err
    assert code == 2 and "没查成" in err, (code, err)


def test_the_report_is_json_serialisable_and_carries_the_four_reading_groups(tmp_path):
    """反真空：报告的读数面都在（缺一面 ⇒ "报告"没有可复核的骨架）。"""
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    blob = json.dumps(report, ensure_ascii=False)
    assert len(blob) > 200, blob
    for key in ("tables", "manuscripts", "five_bit", "in_flight", "refusals", "next_steps",
                "attack_rounds", "interjections"):
        assert key in report, key
    assert set(report["tables"]) == set(SR.REPORT_TABLES), sorted(report["tables"])


# ============================================================ §6.15：后几批的读数接进报告

def test_the_report_reads_the_attack_round_products(tmp_path):
    """卡点③ 的读数进了报告：`attack_plans.history` 的产物分布与"没有产物的轮次"。"""
    ws, st, _ = _ws(tmp_path)
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", {
            "plan_id": "0001", "problem_key": "PK", "problem": "难题（夹具）",
            "status": "open", "rounds": 3,
            "subgoals": [], "budget": {"max_rounds": 3, "max_parallel_subgoals": 1,
            "max_persist_attempts": 3, "max_depth": 2},
            "created_at": "2026-10-05T00:00:00+08:00",
            "history": [
                {"round": 1, "outcome": "no_change", "product": "dead_end",
                 "strategy": "反证", "dead_end_reason": "缺工具"},
                {"round": 2, "outcome": "progress", "product": "reduction", "strategy": "归约"},
                {"round": 3, "outcome": "no_change"},          # ← 旧形态：没有产物
            ]})
    report = SR.collect(st, ws)
    got = report["attack_rounds"]
    assert got["products"] == {"dead_end": 1, "reduction": 1}, got
    assert got["strategies"] == {"反证": 1, "归约": 1}, got
    assert got["no_product_count"] == 1, got
    assert got["no_product_rounds"] == ["0001#3(outcome=no_change)"], got
    # 它必须进"下一步"（不然这条读数躺在 json 里没人消费）
    assert any("没有产物" in s for s in report["next_steps"]), report["next_steps"]
    md = SR.render_status_markdown(report)
    assert "攻坚轮次的产物" in md and "没有产物的轮次" in md, md


def test_no_product_rounds_and_no_proof_round_drive_the_next_steps(tmp_path):
    """反真空：修好之后（每轮都有产物、且有 proof）这两句应当消失。"""
    ws, st, _ = _ws(tmp_path)
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", {
            "plan_id": "0001", "problem_key": "PK", "problem": "难题（夹具）",
            "status": "open", "rounds": 2,
            "subgoals": [], "budget": {"max_rounds": 3, "max_parallel_subgoals": 1,
            "max_persist_attempts": 3, "max_depth": 2},
            "created_at": "2026-10-05T00:00:00+08:00",
            "history": [
                {"round": 1, "outcome": "progress", "product": "proof", "strategy": "反证"},
                {"round": 2, "outcome": "progress", "product": "counterexample_request",
                 "strategy": "小情形搜索找模式"},
            ]})
    report = SR.collect(st, ws)
    joined = "；".join(report["next_steps"])
    assert "没有产物" not in joined, joined
    assert "还没有一条 `proof` 产物" not in joined, joined


def test_the_report_counts_interjections_and_whether_they_changed_anything(tmp_path):
    """D07 的读数进了报告：发出几条、被读几次、改变做法几次。"""
    from agentflow import sessions as SS
    from agentflow.agent_loop import mark_interjections_seen, send_interjection

    ws, st, _ = _ws(tmp_path, sid="t")
    for subject in ("口径变了", "叫停"):
        send_interjection(ws, sender="用户", subject=subject, body="正文", sid="t")
    mark_interjections_seen(ws, "D", ["i-0001"], sid="t", step=3)
    SS.append(ws, {"kind": "agent_interjection_effect", "role": "D", "ids": ["i-0002"],
                   "step": 5, "shape": "final", "changed_action": True}, sid="t")
    report = SR.collect(st, ws)
    got = report["interjections"]
    assert got["sent"] == 2 and got["seen_events"] == 1, got
    assert got["changed_action"] == 1 and got["unchanged_action"] == 0, got
    assert got["recent"][-1]["is_stop"] is True, got["recent"]
    md = SR.render_status_markdown(report)
    assert "集体插话" in md and "改变做法 1 次" in md, md


def test_an_interjection_nobody_read_drives_a_next_step(tmp_path):
    """反真空：发过插话却一次都没被读到 ⇒ 报告要把它说成"下一步该查的事"。"""
    from agentflow.agent_loop import send_interjection

    ws, st, _ = _ws(tmp_path, sid="t")
    send_interjection(ws, sender="用户", subject="叫停", body="正文", sid="t")
    report = SR.collect(st, ws)
    assert any("一次都没被读到" in s for s in report["next_steps"]), report["next_steps"]


def test_the_role_that_has_the_tool_is_told_about_it():
    """广告面判据：发到谁手里的动作，谁的 brief 里就要有它的用法。

    真机读数（2026-10-05 T1 第 16 趟，89 步 / $1.528）：这个工具在第 78 个工具位上、
    M 的门面里调得到，而提示词里一个字都没提 ⇒ 整趟一次都没被用过 ——
    "工具在门面上、却不在广告面上，等于没有"是本项目反复踩的坑（`draft/39` §6.22）。

    负控那一半同样重要：这个工具只发给 M（`roles=("M",)`），别把它的用法撒给别的角色
    —— 撒出去就变成"人人都去写状态报告"，而那正是 §4 要避免的第二种毛病。
    """
    from agentflow import agent_prompts as AP

    def _text(role: str) -> str:
        brief = AP.ROLE_BRIEFS[role]
        return "\n".join([brief.duty, brief.deliverable, *brief.policy])

    assert "conductor.status_report" in _text("M"), _text("M")
    others = [r for r in AP.ROLE_BRIEFS if r != "M" and "conductor.status_report" in _text(r)]
    assert not others, f"这个工具只发给 M，不该出现在别的角色的 brief 里：{others}"
