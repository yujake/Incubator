# -*- coding: utf-8 -*-
"""报告强制（业主 2026-10-08 T17：「A-H每个任务跑完都要往回报告的」）。

真机读数（`draft/89` §3）：25 个工作区 1562 行手稿全部是框架派生
（`note` 写着「框架据动作结果派生」或「框架据派活派生」），模型自撰 = 0。
⇒ 缺口不是"没人要求回报"，而是"回报这条链没跑通"。这一批补两件事：

1. 通报由框架保证：模型没写 `notify` ⇒ 框架开一条 `kind="notice"` 的板项，
   body 逐字「（它没有留下结论）」（对齐 DSH 的 `It left no closing message.`）；
2. 模型自撰那条路要能对回实例：`_do_handoff` 补传 `task_id`（形参本来就在，
   缺的是调用点不传 —— 那 593 行没有 `task_id` 的正是这条路）。

判据三半：正控（没填 ⇒ 恰一条 notice）/ 负控（填了 ⇒ 不补第二条）/
反真空（不是终态 ⇒ 不补；没有 conductor ⇒ 如实留一句读数，不静默）。
"""
from __future__ import annotations

import json
import pathlib

from test_llm_work_reaches_the_ledger import NOTIFY, _run

from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _board(st: Store) -> list[dict]:
    return [r for r in st.rows("tasks") if str(r.get("kind") or "")]


def _store_of(ws: pathlib.Path) -> Store:
    return Store(ws)


def test_a_missing_notify_still_leaves_exactly_one_report(tmp_path: pathlib.Path):
    """正控：模型没填 `notify` ⇒ 板上恰好一条 `notice`，body 是那句逐字兜底。"""
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "这一趟做完了，但我没填 notify", "evidence": []}, ensure_ascii=False)}])
    assert run.stop_reason == "final", run.to_dict()
    st = _store_of(ws)
    items = _board(st)
    assert len(items) == 1, items
    it = items[0]
    assert it["kind"] == "notice" and it["expects"] == "ack", it
    assert it["item_state"] == "queued", it                    # 还没人读
    assert it["detail"] == "这一趟做完了，但我没填 notify", it  # 模型给了结论 ⇒ 落结论本身
    # 读数：这一条"补通报"这件事本身也进了会话（读得到"框架为什么补了它"）
    found: list[str] = []
    for info in SS.list_sessions(ws):
        evs, _bad = SS.read_session(ws, info["sid"])
        found += [str(e.get("kind")) for e in evs]
    assert "agent_settlement_item" in found, found


def test_a_written_notify_is_not_duplicated_by_the_framework(tmp_path: pathlib.Path):
    """负控（最重要的一条）：模型自己写了 ⇒ 框架不许再补一份。

    没有这一条，"报告强制"可以靠"框架每次再补一条"变绿 —— 那会把模型的内容淹掉，
    于是读板的人永远看到框架那句模板（真机 1562 行全是模板，正是这个形态的静态版）。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "照常收工", "evidence": [], "notify": NOTIFY}, ensure_ascii=False)}])
    assert run.stop_reason == "final", run.to_dict()
    assert run.handoffs == ["0000"], run.to_dict()             # 模型那条手稿落了
    st = _store_of(ws)
    assert _board(st) == [], _board(st)                         # 板上没有 notice


def test_the_settlement_uses_the_verbatim_fallback_when_there_is_no_conclusion(
        tmp_path: pathlib.Path):
    """正控（兜底句逐字）：模型连 `final` 都没给 ⇒ body 是「（它没有留下结论）」。

    这里用最小替身 + 真的 `Conductor`（板要真落一行才算数），不跑整趟循环：
    这条判据问的是"没有结论时那句兜底是什么"。
    """
    from agentflow.agent_loop import AgentLoop

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    stub = type("S", (), {"conductor": cond, "role": "D", "session_root": ws, "sid": "x",
                          "my_task_id": "t-0007", "depth": 2})()
    run = type("R", (), {"stop_reason": "final", "handoffs": [], "final": ""})()
    note = AgentLoop._emit_settlement(stub, run)
    items = _board(st)
    assert len(items) == 1, items
    assert items[0]["detail"] == "（它没有留下结论）", items[0]
    assert items[0]["parent_task_id"] == "t-0007", items[0]
    assert "已落板" in note, note


def test_handoffs_written_by_the_loop_carry_the_instance_id(tmp_path: pathlib.Path):
    """正控（T14 的连带）：走循环那条路写出来的手稿行带 `task_id`（实例号）。

    真机 593 行没有这一格，正是这条路；补的是两个调用点的实参。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "照常收工", "evidence": [], "notify": NOTIFY}, ensure_ascii=False)}])
    rows, bad = __import__("agentflow.manuscripts", fromlist=["x"]).read_rows(ws)
    assert not bad, bad
    assert rows and str(rows[0]["task_id"]).startswith("t-"), (
        "走循环那条路写出来的手稿行必须带实例号（真机 593 行缺它）：", rows[0])


def test_no_conductor_is_reported_not_swallowed(tmp_path: pathlib.Path):
    """反真空：没有 conductor 句柄 ⇒ 如实留一句读数（不许静默当成"不用报告"）。

    这里用最小替身而不是造一个完整 `AgentLoop`：这条判据只问"没有句柄时它说什么"。
    """
    from agentflow.agent_loop import AgentLoop

    stub = type("S", (), {"conductor": None, "role": "D", "session_root": tmp_path,
                          "sid": "x", "my_task_id": "", "depth": 1})()
    run = type("R", (), {"stop_reason": "final", "handoffs": [], "final": "收工"})()
    note = AgentLoop._emit_settlement(stub, run)
    assert "没有 conductor" in note, note


def test_a_non_terminal_run_is_not_reported(tmp_path: pathlib.Path):
    """负控（边界）：没停在终态（还在等用户 / 还没有定论）⇒ 不补通报 —— 它不是"跑完了"。

    名单换过一格（裁定 12-K）：改前这里还有 `"max_steps"`，因为那时步数用尽是真的会
    收工的一档；现在循环不再因步数收工（步数只上报、由父代理决定放行还是刹停），
    那一格就成了一个永远不会为真的分支，与它一起从名单与源码里删掉。
    """
    from agentflow.agent_loop import AgentLoop

    stub = type("S", (), {"conductor": object(), "role": "D", "session_root": tmp_path,
                          "sid": "x", "my_task_id": "", "depth": 1})()
    for reason in ("waiting_for_user", ""):
        run = type("R", (), {"stop_reason": reason, "handoffs": [], "final": "x"})()
        assert AgentLoop._emit_settlement(stub, run) == "", reason
    # 正控对照（判据不许空转）：换成真的终态理由，它就必须去落板 ——
    # 这里用替身 conductor（`object()`）让它落不成，于是读数是那句"没落板"。
    done = type("R", (), {"stop_reason": "final", "handoffs": [], "final": "x"})()
    assert "终态回报没落板" in AgentLoop._emit_settlement(stub, done)
