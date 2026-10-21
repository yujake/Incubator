# -*- coding: utf-8 -*-
"""S4-b：停止沿边下发，且 ack 才算传达到（业主 T2 / `draft/84` §2.2）。

`draft/84` §2.2：先根后子按边逐层落停止通知；每个收到者记 ack、停派新活、把通知再传给自己的子；收尾等子交差（有界），超时如实记 pending，不冒充"子已交差"。

本批落地：① `Conductor.notify_children_of_stop` 给我还在飞的直接子各开一条 `notice`/`ack` 板项 + 父那一行留一行落痕；② 循环在停机那一步最后调它；③
循环读到 `notice`/`ack` 项时框架替这一趟 ack（对象是"这一趟进程"，不是要模型交付的活）；④ `stop_edge_readings`
把 `notified_at / acked_at / settled_at / timeout` 分开报；⑤ 没有 ack 就不许消边。

判据（正控 3 / 负控 2 / 反真空 1）：

正控：① 沿边下发：两条在飞的边 ⇒ 两条 `notice`/`ack` 项 + 两行落痕，已通知过的边不重复下发（幂等）；② 子那一趟读到之后框架替它 ack ⇒ `acked_at`
非空、`item_state="done"`、`item_close` 以 `acked@` 开头；③ 真跑一趟循环 ⇒ 它收工前把通知发给了名下在飞的子。
负控：① 抹掉 ack（通知了但没被读）⇒ 消边判据拒绝；② 台账/父行读不成 ⇒ `stop_edge_readings` 三态 `checked=False`（不许把"没读成"报成"没有边"）。
反真空：名下没有在飞的子 ⇒ `notified=[]` + 说清（不是"通知过了"）。"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import stopctl
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s4b"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str], *, on_call: Any = None) -> None:
        self.replies = list(replies)
        self.systems: list[str] = []
        self.on_call = on_call

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        if self.on_call is not None:
            self.on_call(len(self.systems))
        text = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tool_calls": (),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    return st, cond, ws, top


def _child(cond: Conductor, parent: str, *, role: str, key: str, status: str = "running",
           ended: str | None = None) -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-09T00:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:%s.run_once" % role)


# ------------------------------------------------------------------ 正控

def test_the_stop_travels_along_every_open_edge(tmp_path: pathlib.Path):
    """正控①：两条在飞的边 ⇒ 两条 `notice`/`ack` 项 + 两行落痕；重复调用是幂等的。"""
    st, cond, _ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4b@d")
    e = _child(cond, top, role="E", key="s4b@e")
    done = _child(cond, top, role="F", key="s4b@f", status="done",
                  ended="2026-10-09T00:01:00+08:00")     # 已经收工 ⇒ 不必通知

    got = cond.notify_children_of_stop(top, reason="user", by="M")
    assert got["checked"] is True, got
    assert sorted(x["child_task_id"] for x in got["notified"]) == sorted([d, e]), got
    assert done not in [x["child_task_id"] for x in got["notified"]], "收工的子不必通知"
    rows = {str(r["task_id"]): r for r in st.rows("tasks")}
    for item in [x["item_id"] for x in got["notified"]]:
        assert str(rows[item]["kind"]) == "notice", rows[item]
        assert str(rows[item]["expects"]) == "ack", rows[item]
    again = cond.notify_children_of_stop(top, reason="user", by="M")
    assert again["notified"] == [] and len(again["skipped"]) == 2, again

    readings = cond.stop_edge_readings(top)
    assert readings["checked"] is True and len(readings["edges"]) == 2, readings
    for edge in readings["edges"]:
        assert edge["notified_at"] and not edge["acked_at"], edge
        assert edge["timeout"] is True, edge                 # 都还没写终态


def test_the_child_acks_when_it_reads_the_notice(tmp_path: pathlib.Path):
    """正控②：子读到通知 ⇒ 框架替这一趟 ack（`acked_at` 非空、`item_close=acked@…`）。"""
    st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4b@d")
    got = cond.notify_children_of_stop(top, reason="user", by="M")
    item = got["notified"][0]["item_id"]

    loop = _loop(ws, cond, task_id=d, role="D")
    loop.parent_task_id = top          # ack 的时刻落在父那一行的落痕里
    # 真实顺序：渲染那一步先标 seen，紧接着框架替这一趟 ack
    # （`_set_item` 不许"没 seen 就 done"——空口 ack 的机器形态，既有判据）。
    _state, why = cond.mark_item_seen(item, by_task_id=d, step=1)
    assert not why, why
    assert loop._ack_stop_notice(item, 1) != ""
    readings = cond.stop_edge_readings(top)
    edge = readings["edges"][0]
    assert edge["acked_at"], edge
    row = {str(r["task_id"]): r for r in st.rows("tasks")}[item]
    assert str(row["item_state"]) == "done", row
    assert str(row["item_close"]) == "acked", row
    # 幂等：再 ack 一次不写第二份（已经 done）
    assert loop._ack_stop_notice(item, 2) == ""


def test_a_stopping_loop_notifies_its_children(tmp_path: pathlib.Path):
    """正控③（端到端）：停机开关在盘上 ⇒ 那一趟收工前把通知发给了名下在飞的子。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    my_row: dict[str, Any] = {}

    def on_call(n: int) -> None:
        if n == 1:
            # 第一次模型调用之后：写停机开关 + 认出我这一趟的编号，再造一个在飞的子。
            # 下一步的停机判据才会读到这把开关（它是"步边界"看的）。
            tid = next(str(r["task_id"]) for r in st.rows("tasks")
                       if str(r.get("role")) == "M" and str(r.get("action")) == "run")
            my_row["tid"] = tid
            stopctl.request_stop(ws, reason="user", by="user")
            _child(backend.conductor, tid, role="D", key="s4b@mid")

    backend = LlmBackend(inner=LocalBackend({}), loops={("D", "write_report"): {}},
                         session_root=ws, max_steps=4, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    gate = _Gate([json.dumps({"tool": "table.list", "args": {"table": "tasks"}},
                             ensure_ascii=False),
                  json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)],
                 on_call=on_call)
    run = run_role("M", "被叫停的一趟", store=st, registry=built.registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=ws, gateway=gate, price=(0.0, 0.0),
                                sid=SID),
                   workspace_root=str(ws), sid=SID, max_steps=4, from_env=False)
    assert run.stop_reason == "stop_file", run.stop_reason
    tid = str(my_row.get("tid") or "")
    assert tid, "夹具没认出这一趟的编号"
    readings = cond.stop_edge_readings(tid)
    assert readings["checked"] is True, readings
    assert readings["edges"] and readings["edges"][0]["notified_at"], readings
    assert any("沿边下发" in n for n in run.notes), run.notes


# ------------------------------------------------------------------ 负控

def test_without_an_ack_the_edge_cannot_be_released(tmp_path: pathlib.Path):
    """负控①（核心）：通知了但一直没被读 ⇒ 消边判据拒绝（ack 才算传达到）。"""
    _st, cond, _ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4b@d")
    cond.notify_children_of_stop(top, reason="user", by="M")
    # 子写终态（收工了）——但通知项还挂在 queued（从没被读）
    cond.finish(d, status="done", outcome="ok", detail="收工")
    mark, why = cond.note_edge_release(top, child_task_id=d, attempt=1)
    assert mark == "" and "ack" in why, (mark, why)

    # 补上 ack（渲染那一步先标 seen，再 ack）⇒ 同一次消边放行
    item = cond.stop_edge_readings(top)["edges"][0]["item_id"]
    loop = _loop(pathlib.Path(str(_st.root)), cond, task_id=d, role="D")
    loop.parent_task_id = top
    assert not cond.mark_item_seen(item, by_task_id=d, step=1)[1]
    assert loop._ack_stop_notice(item, 1) != ""
    mark2, why2 = cond.note_edge_release(top, child_task_id=d, attempt=1)
    assert mark2 and not why2, (mark2, why2)


def test_the_readings_are_three_state_when_the_ledger_is_unreadable(tmp_path: pathlib.Path):
    """负控②：父行不存在 / 台账读不成 ⇒ `checked=False`（不许报成"没有边"）。"""
    _st, cond, _ws, _top = _env(tmp_path)
    missing = cond.stop_edge_readings("t-没这行")
    assert missing["checked"] is False and missing["edges"] == [], missing
    assert "没有" in missing["reason"], missing


def test_no_open_edges_is_a_readable_zero(tmp_path: pathlib.Path):
    """反真空：名下没有在飞的子 ⇒ `notified=[]` + 说清（不是"通知过了"）。"""
    _st, cond, _ws, top = _env(tmp_path)
    got = cond.notify_children_of_stop(top, reason="user", by="M")
    assert got["checked"] is True and got["notified"] == [], got
    assert "没有在飞" in str(got.get("note") or ""), got
    assert cond.stop_edge_readings(top)["edges"] == []


def _loop(ws: pathlib.Path, cond: Conductor, *, task_id: str, role: str):
    from agentflow.agent_loop import AgentLoop

    loop = AgentLoop(role=role, session_root=ws, registry=None, seam=None, conductor=cond,
                     sid=SID, store=None, max_steps=1, auto_secretary=False)
    loop.my_task_id = task_id
    return loop
