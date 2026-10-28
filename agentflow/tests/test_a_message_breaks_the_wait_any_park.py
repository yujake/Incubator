# -*- coding: utf-8 -*-
"""判据：挂着"等任意计时器返回"时，有新消息也要打断（业主 2026-10-28）。

## 现场

页面上 `B-reg` 那一格：`待机` + `未读 2` —— 两条留言没人读。手上有计时器在等的时候，
`_park_gate` 的第 ① 支是这么写的：

```python
elif want.get("waiting") and pending_timers:      # ① 显式要求等 + 还有计时器 ⇒ 挂机
    ... 睡 ...
```

它不看 `_pending_work`（而第 ④ 支看：`elif parked["count"] and not work.get("busy")`）。
于是同一件事在两条挂机支上口径不一致：隐式挂机（④）会被新投递打断，显式"等任意计时器"
（①）不会 —— 留言被 `_deliver_mailbox` 投进上下文之后，模型要等计时器到点才有下一拍。
业主的口径是"无事可做才挂"，而"这一拍有新留言"正是"有事可做"。

## 这一组守什么

1. 正题：显式 wait_any + 还有计时器 + 这一拍有新留言 ⇒ 不许挂（`skip_model=False`），
   理由点名"有活"；
2. 正控：同样条件、这一拍没有新投递 ⇒ 照旧挂机（别把挂机整个废掉）；
3. 等待意图被撤：给了模型一拍之后，那条"等任意计时器"的意图按既有口径撤掉
   （它不是一个持续状态；要再等就再要一次）—— 否则下一拍会被旧意图按回挂机；
4. 负控：把"新留言"那一格拿掉（`msg_ids=[]`）⇒ 判据 1 必红（证明是这一格在起作用）；
5. 反真空：读数没查成（`checked=False`）时照旧"不挂、问模型"，绝不把"没查成"当"在等"。
"""
from __future__ import annotations

import pathlib
import types
from typing import Any, Sequence

import pytest

from agentflow import clock as CLK
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "probe-park-msg"
TASK = "挂机时来消息要打断"


@pytest.fixture()
def bench():
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall="2026-10-28T09:00:00+00:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws


def _agent(cond: Conductor, parent: str, *, status: str = "running", role: str = "D") -> str:
    ended = None if status in ("pending", "running") else "2026-10-28T09:00:05+08:00"
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"parkmsg@{role}",
        "status": status, "outcome": ("ok" if ended else None), "refusal_reason": None,
        "instance": "", "detail": "子代理", "error": None,
        "started_at": "2026-10-28T09:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, me: str) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=None, price=(0.0, 0.0),
                                  sid=SID),
                     store=st, sid=SID, max_steps=6, workspace_root=str(ws),
                     my_task_id=me)


def _mailbox(*, msg_ids: Sequence[str] = (), item_ids: Sequence[str] = (),
             wake_ids: Sequence[str] = ()) -> dict[str, Any]:
    """一份最小的 mailbox 读数（`_pending_work` 只读这五个键）。"""
    return {"msg_ids": list(msg_ids), "item_ids": list(item_ids),
            "wake_ids": list(wake_ids), "children": {"settled": []},
            "messages": [], "items": []}


def _run_obj() -> Any:
    return types.SimpleNamespace(park={}, notes=[], summons=[], messages_sent=[])


def _armed(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path, str, str]:
    """铺好：一条在跑的计时器 + 一条"等任意计时器"的意图。返回 (store, cond, ws, me, 子号)。"""
    st, cond, ws = _ws(tmp_path)
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="running")
    CLK.start_timer(ws, wait_for=f"task:{child}", task_id=me, reason="等子跑完")
    CLK.request_wait_any(ws, task_id=me, role="M", purpose="等任意计时器返回")
    return st, cond, ws, me, child


def test_a_new_message_breaks_the_wait_any_park(tmp_path: pathlib.Path, bench):
    """正题：显式"等任意计时器"+ 还有计时器 + 这一拍有新留言 ⇒ 不许挂机。"""
    st, cond, ws, me, _child = _armed(tmp_path)
    loop = _loop(st, cond, ws, me)
    got = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox(msg_ids=["m000001"]))
    assert got["skip_model"] is False, got
    assert got["decision"] != "park", got
    assert "有活" in str(got["reason"]) or "留言" in str(got["reason"]), got["reason"]
    assert got["pending_work"] is True, got


def test_without_a_message_the_wait_any_park_still_parks(tmp_path: pathlib.Path, bench):
    """正控（别把挂机整个废掉）：同一条件、这一拍没有新投递 ⇒ 照旧挂机。"""
    st, cond, ws, me, _child = _armed(tmp_path)
    loop = _loop(st, cond, ws, me)
    got = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert got["skip_model"] is True and got["decision"] == "park", got
    assert got["pending_work"] is False, got


def test_the_wait_intent_is_cancelled_once_the_model_gets_a_turn(tmp_path: pathlib.Path, bench):
    """给了模型一拍之后那条意图要撤（它不是持续状态；否则下一拍又被按回挂机）。"""
    st, cond, ws, me, _child = _armed(tmp_path)
    assert CLK.read_wait_any(ws)["rows"], "前置没铺上（意图不在盘上）"
    loop = _loop(st, cond, ws, me)
    got = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox(msg_ids=["m000001"]))
    assert got["skip_model"] is False, got
    assert CLK.read_wait_any(ws)["rows"] == [], "要了模型一拍却没撤等待意图"


def test_negative_control_without_the_message_it_would_park(tmp_path: pathlib.Path, bench):
    """负控：同一份读数只把新留言那一格换成空 ⇒ 结论必须翻成"挂机"。

    没有这一条，"有消息就打断"可能只是恰好别的判据也亮了。
    """
    st, cond, ws, me, _child = _armed(tmp_path)
    loop = _loop(st, cond, ws, me)
    with_msg = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox(msg_ids=["m1"]))
    without = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert with_msg["skip_model"] is False and without["skip_model"] is True, (with_msg, without)


def test_an_unreadable_reading_still_refuses_to_park(tmp_path: pathlib.Path, bench,
                                                     monkeypatch: pytest.MonkeyPatch):
    """反真空：读数没查成 ⇒ 照旧"问模型"，不把"没查成"折成"在等"（既有口径，不许被这次改坏）。"""
    st, cond, ws, me, _child = _armed(tmp_path)
    loop = _loop(st, cond, ws, me)
    monkeypatch.setattr(AgentLoop, "_wait_any_reading",
                        lambda self: {"checked": False, "requested": True, "waiting": True,
                                      "pending": [], "reason": "打桩：读不成", "wait_id": ""},
                        raising=True)
    got = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert got["skip_model"] is False, got
