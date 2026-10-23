# -*- coding: utf-8 -*-
"""能不能停由 M 自己判（业主 2026-10-09 两句逐字）。

> 「是否收工不要用机械判据，由 M 制定的目标是否达成为准」
> 「所有智能体是否能停都是看自己被派的活有没有做完，M 也不例外，只是 M 需要根据
> 用户指令给自己设计任务列表」

⇒ 收工门的八格退成读数（`status` / `machine_pass`），`can_close` 由 M 的判据
（`m_verdict.met`）决定，判的依据是它自己列的任务列表（`tasks`）。
判据归 M ≠ 读数可以被盖掉：两者不一致时 `overrode` 逐格点名、自述与自己的列表对不上时
`verdict_conflicts` 逐项点名。

## 判据（正控 2 / 负控 2 / 反真空 1）

正控：① M 判"做完了"（列表全 done）⇒ `can_close=true`、退出码 0；
  ② M 判"做完了"而机器某几格红 ⇒ `can_close=true`，但 `overrode` 逐格点名（不许静默放行）。
负控：① M 判"没做完"而机器八格全 pass ⇒ `can_close=false`（机器不许替它说"可以交"）；
  ② M 说"做完了"而自己的列表里还有 `not_done`/`cannot` ⇒ `verdict_conflicts` 逐项点名。
反真空：M 没交判据 ⇒ `can_close=false` + 退出码 2 + 摘要写明"没有提交自己的判据"
  （"没人判过"不是"可以交"）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import closing as CL
from agentflow.store import Store

TS = "2026-10-09T00:00:00+08:00"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _report(ws: pathlib.Path) -> pathlib.Path:
    p = ws / "out" / "review" / "REPORT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 交付说明\n\n## 一、任务与范围\n审阅并完善论文包。\n", encoding="utf-8")
    return p


def _gate(st: Store, report: pathlib.Path, **kw):
    """只跑 `substance` 那一格：这一组判据问的是"谁判收工"，不是八格各自的判据。"""
    return CL.check_closing(st, checks=("substance",), project_dir=str(st.root),
                            report_path=str(report), **kw)


def test_m_says_done_and_that_is_the_verdict(tmp_path: pathlib.Path):
    """正控①：M 按自己的任务列表判"做完了" ⇒ 能停（机器那几格只是读数）。"""
    st = _store(tmp_path)
    rep = _gate(st, _report(st.root), goal="把论文包审完并交修订稿", goal_met=True,
                basis="P2/P7/P8/P9 全绿",
                task_list=[{"what": "逐条核引文", "state": "done"},
                           {"what": "形式化核两条定理", "state": "done"}])
    assert rep.can_close is True, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 0
    assert rep.m_verdict["counts"] == {"done": 2, "not_done": 0, "cannot": 0, "total": 2}
    assert rep.verdict_conflicts == [], rep.verdict_conflicts


def test_m_may_stop_against_a_red_cell_but_the_cell_is_named(tmp_path: pathlib.Path):
    """正控②：M 判"做完了"而机器有红格 ⇒ 能停，但 `overrode` 必须点名那一格。"""
    st = _store(tmp_path)
    # 空台账 ⇒ `substance` 那一格是 fail（机器有意见）
    rep = _gate(st, _report(st.root), goal="交付", goal_met=True,
                task_list=[{"what": "写报告", "state": "done"}])
    assert rep.machine_pass is False and rep.status["substance"] == "fail", rep.to_dict()
    assert rep.can_close is True, "判据归 M：机器有意见不阻断它停"
    assert [x["check"] for x in rep.overrode] == ["substance"], rep.overrode
    assert "substance" in rep.summary(), rep.summary()


def test_m_may_refuse_to_stop_even_when_the_machine_is_green(tmp_path: pathlib.Path):
    """负控①：机器八格全 pass 而 M 说"没做完" ⇒ 不许停（机器不许替它说可以交）。"""
    st = _store(tmp_path)
    from agentflow import schema as S

    lit = S.Literature(lit_id="0000", title="一篇文献", type="J", summary="摘要",
                       path=None, added_at=TS)
    lit.validate()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", lit.to_dict())
    stmt = S.Statement(stmt_id="0000", origin="external_lit", kind="theorem",
                       label="Theorem 0.1", statement_text="短版",
                       statement_full="若 A 则 B", proof_text="Proof. …",
                       source_lit_id="0000", quote_verified=True,
                       quote_span="p1:norm[4:40]",
                       quote_reason="逐字比对通过", evidence_kind="cross_check",
                       status="active", created_at=TS)
    stmt.validate()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", stmt.to_dict())
    rep = _gate(st, _report(st.root), goal="交付", goal_met=False,
                basis="还差引文逐条核验",
                task_list=[{"what": "逐条核引文", "state": "not_done", "why": "检索被 429 挡住"}])
    assert rep.machine_pass is True, ("这一条的前提是机器那一格真的绿了", rep.to_dict())
    assert rep.can_close is False, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 1, "M 说没做完 ⇒ 退出码 1（被拦住）"
    assert [x["check"] for x in rep.overrode] == ["*"], rep.overrode


def test_m_saying_done_while_its_own_list_has_open_items_is_named(tmp_path: pathlib.Path):
    """负控②：M 说"做完了"，而它自己的列表里还有没做完的项 ⇒ `verdict_conflicts` 点名。"""
    st = _store(tmp_path)
    rep = _gate(st, _report(st.root), goal="交付", goal_met=True,
                task_list=[{"what": "逐条核引文", "state": "done"},
                           {"what": "形式化核两条定理", "state": "not_done",
                            "why": "Lean 环境缺包"},
                           {"what": "重渲染附录", "state": "cannot", "why": "编译脚本缺"}])
    assert rep.can_close is True, "判据归 M：它说停就停"
    assert [x["what"] for x in rep.verdict_conflicts] == ["形式化核两条定理", "重渲染附录"], \
        rep.verdict_conflicts
    assert "对不上" in rep.summary(), rep.summary()


def test_without_a_verdict_nobody_said_it_may_close(tmp_path: pathlib.Path):
    """反真空：M 没交判据 ⇒ `can_close=false` + 退出码 2（"没人判过"不是"可以交"）。"""
    st = _store(tmp_path)
    rep = _gate(st, _report(st.root))
    assert rep.m_verdict is None and rep.can_close is False, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 2, rep.to_dict()
    assert "没有提交自己的判据" in rep.summary(), rep.summary()
    assert json.dumps(rep.to_dict(), ensure_ascii=False)  # 可落档


# ---------------------------------------------------------------- 上报（业主 2026-10-09 第三句）

def test_an_item_it_cannot_do_must_be_reported_to_the_user(tmp_path: pathlib.Path):
    """正控：M 列了"干不了"的项 ⇒ 会话里要有一次上行（问用户），否则 `escalation_gaps` 点名。

    业主逐字：「如果某代理认为某件任务自己无法胜任且无法通过派子代理解决，则会将情况上报
    父智能体。特别地，M 向用户上报。」
    """
    from agentflow import userio as U

    st = _store(tmp_path)
    report = _report(st.root)
    tasks = [{"what": "逐条核引文", "state": "done"},
             {"what": "重渲染附录并核锚", "state": "cannot", "why": "编译脚本缺"}]

    # ① 没上报 ⇒ gap 点名（判据仍归 M：它能停，但"闷着不说"看得见）
    quiet = CL.check_closing(st, checks=("substance",), project_dir=str(st.root),
                             report_path=str(report), session_root=str(st.root), sid="r1",
                             goal="交付", goal_met=True, task_list=tasks)
    assert quiet.can_close is True, quiet.to_dict()
    assert [x["what"] for x in quiet.escalation_gaps] == ["重渲染附录并核锚"], \
        quiet.readings["verdict_escalation"]
    assert "没上报的项" in quiet.summary(), quiet.summary()

    # ② 上报过（问用户：取不回原文那件事）⇒ 不再点名
    U.ask_user(st.root, role="M", question="重渲染附录并核锚这件事做不了（编译脚本缺），"
                                           "要我换个做法还是先交？", timeout_sec=0.0, sid="r2")
    told = CL.check_closing(st, checks=("substance",), project_dir=str(st.root),
                            report_path=str(report), session_root=str(st.root), sid="r2",
                            goal="交付", goal_met=True, task_list=tasks)
    assert told.escalation_gaps == [], told.readings["verdict_escalation"]
    assert [x["via"] for x in told.readings["verdict_escalation"]["escalations"]] == ["question"]


def test_the_escalation_reading_is_three_state(tmp_path: pathlib.Path):
    """反真空：会话读不成 ⇒ `checked=False`（"没读成"不是"没上报"，也不算"上报了"）。

    注意工作区根与会话根在设计上是同一个根（`check_closing` 的缺省），所以"没有会话根"
    这一档到不了；能到的第三态是读出来的坏行 —— 判据把 `problems` 非空落成
    `checked=False`，并且这时不报 gap（不把"没读成"折成"没上报"）。
    """
    st = _store(tmp_path)
    bad_root = tmp_path / "bad"
    (bad_root / "sessions").mkdir(parents=True, exist_ok=True)
    (bad_root / "sessions" / "r3.jsonl").write_text("{不是 JSON\n", encoding="utf-8")
    rep = CL.check_closing(st, checks=("substance",), project_dir=str(st.root),
                           report_path=str(_report(st.root)), session_root=str(bad_root),
                           sid="r3", goal="交付", goal_met=True,
                           task_list=[{"what": "某件干不了的活", "state": "cannot",
                                       "why": "缺环境"}])
    got = rep.readings["verdict_escalation"]
    assert got["checked"] is False and got["reason"], got
    assert rep.escalation_gaps == [], ("没读成时不许报 gap（那是把'没查成'折成'没上报'）", got)


# ------------------------------------------------- 整支卡住（业主 2026-10-09 第四句）

def test_all_active_children_blocked_is_a_stopping_state(tmp_path: pathlib.Path):
    """正控：在飞的直接子每一个都声明过"卡住" ⇒ `all_blocked=True`（一种停机状态）。

    业主逐字：「上述层层上报困难也会带来一种停机状态，即所有活跃子代理的状态都是 blocked」。
    载具：每个子在自己的收工那句话里带 `blocked:{what,why}` ⇒ 框架把落痕写到父那一行
    （`note_blocked`）⇒ 父读 `subtree_blocked` 就知道"委派这条路也堵死了"。
    """
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.store import Store

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")

    def kid(role: str, key: str) -> str:
        return cond._write_new_row({
            "task_id": "", "role": role, "action": "run_once", "called_by": "M",
            "parent_task_id": top, "depth": 2, "input_key": key, "status": "running",
            "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
            "error": None, "started_at": TS, "ended_at": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="start:%s" % role)

    a, b = kid("D", "k1"), kid("E", "k2")
    assert cond.subtree_blocked(top)["all_blocked"] is False, "都没声明 ⇒ 还留着路"
    assert cond.note_blocked(top, a, what="核引文", why="原文取不回")[0]
    one = cond.subtree_blocked(top)
    assert one["all_blocked"] is False and one["blocked"] == [a], one
    assert cond.note_blocked(top, b, what="跑实验", why="Lean 环境缺包")[0]
    both = cond.subtree_blocked(top)
    assert both["all_blocked"] is True, both
    assert sorted(both["blocked"]) == sorted([a, b]), both
    assert [x["why"] for x in both["details"]] == ["原文取不回", "Lean 环境缺包"], both["details"]
    # 幂等：同一条边第二次不写第二份
    assert cond.note_blocked(top, a, why="再说一遍") == ("", "已经记过（幂等：不写第二份）")


def test_no_active_children_is_not_all_blocked(tmp_path: pathlib.Path):
    """反真空：没有在飞的子 ⇒ `all_blocked=False` + 说清（"没有活跃子"不是"整支卡住"）。"""
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    got = cond.subtree_blocked(top)
    assert got["checked"] is True and got["all_blocked"] is False, got
    assert "没有在飞" in got["reason"], got
    assert cond.subtree_blocked("")["checked"] is False, "不知道我是谁 ⇒ 判不了"


def test_a_childs_blocked_declaration_lands_on_the_parent(tmp_path: pathlib.Path):
    """正控（端到端）：子那一趟带 `blocked` 收工 ⇒ 父那一行上有落痕；没带 ⇒ 什么都不写。"""
    from agentflow.agent_loop import AgentLoop
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": top, "depth": 2, "input_key": "k", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": TS, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="start:D")
    loop = AgentLoop(role="D", session_root=st.root, registry=None, seam=None, conductor=cond,
                     store=st, sid="blk", max_steps=1, auto_secretary=False)
    loop.my_task_id = child
    loop.parent_task_id = top
    # 没声明 ⇒ 什么都不做（老行为逐字不变）
    assert loop._note_blocked_declaration({"final": "收工"}) == {}
    # 少了 `needs` ⇒ 不是 blocked（业主第六句：说不出要请示什么，那多半是"职责之外"）
    bare = loop._note_blocked_declaration({"blocked": {"what": "某件活", "why": "不归我管"}})
    assert bare["recorded"] is False and "needs" in bare["problem"], bare
    assert cond.subtree_blocked(top)["all_blocked"] is False, "没落痕 ⇒ 不算 blocked"
    # 少了 `why` ⇒ 也不落痕（不许静默卡住）
    no_why = loop._note_blocked_declaration({"blocked": {"what": "某件活", "needs": "请定口径"}})
    assert no_why["recorded"] is False and "why" in no_why["problem"], no_why
    # 齐了（等上级指导细则）⇒ 落痕到父那一行，父读得出"整支卡住"
    got = loop._note_blocked_declaration({"blocked": {"what": "核引文", "why": "口径没定",
                                                      "needs": "请上级定『引文一致』的判定口径"}})
    assert got["recorded"] is True, got
    assert cond.subtree_blocked(top)["all_blocked"] is True, cond.subtree_blocked(top)

