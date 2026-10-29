# -*- coding: utf-8 -*-
"""判据：静默要分「可叫醒」与「不可叫醒」两档 —— 业主 2026-10-29 的两条裁定。

业主原话：「静默的意思是"我的工作完成了，我彻底休息了。但如果需要我，给我再发消息或
委托，我随叫随到"」「已销号是彻底没有了。如果父代理想给销号子代理发消息，秘书要拦」。

`conductor.agent_state` 是纯函数，所以这三条可以用字典直接钉：
1. 已完成、未销号 ⇒ 静默 ∧ `wakeable=True`（号还在、随叫随到）；
2. 已销号 ⇒ 静默 ∧ `wakeable=False`（彻底没有了）；
3. 还在跑（running）⇒ 在飞 ∧ `wakeable=False`（不需要叫，它已经在跑）。
"""
from __future__ import annotations

from agentflow import conductor as C

CLOCK = {"checked": True, "rows": [], "pending_total": 0}


def _state(*, status: str, retired: bool = False) -> dict:
    row = {"task_id": "t-000012", "role": "D", "status": status}
    item = {"name": "D4", "task_id": "t-000012", "retired": retired}
    return C.agent_state(row=row, item=item, wait=CLOCK)


def test_a_finished_agent_is_silent_and_wakeable():
    """①+③：已完成、号还在 ⇒ 静默且可叫醒。"""
    got = _state(status="done")
    assert got["state"] == C.AGENT_STATE_SILENT, got
    assert got["wakeable"] is True, got


def test_a_retired_agent_is_silent_but_not_wakeable():
    """②：已销号 ⇒ 静默但不可叫醒（彻底没有了），两档不许折平。"""
    got = _state(status="done", retired=True)
    assert got["state"] == C.AGENT_STATE_SILENT, got
    assert got["wakeable"] is False, got


def test_a_running_agent_is_not_wakeable_because_it_is_already_flying():
    """反真空：还在跑的不用叫（它本来就在飞），所以 wakeable 必须是 False。"""
    got = _state(status="running")
    assert got["state"] == C.AGENT_STATE_FLYING, got
    assert got["wakeable"] is False, got
