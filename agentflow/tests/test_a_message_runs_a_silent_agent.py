# -*- coding: utf-8 -*-
"""判据：板项落盘之后，收件人得有人读它 —— 「静默的唤醒就是接到消息被唤醒」。

业主 2026-10-29：「这和计时器到点时给代理发消息唤醒一样，静默的唤醒就是接到消息被唤醒」。
所以叫醒不是另一个动作：`Conductor.open_item` 是两条来源的唯一写入口
（计时器到点落 `kind="notice"`，同伴发言落 `kind="message"`），判定就挂在那里。

这一组钉判定次序（不依赖真起循环：执行侧由 `resume_runner` 接）：
1. 终态且未销号 ⇒ 判定为"该跑起来"，并把同一个号交给执行侧；
2. 已销号 ⇒ 不跑它（"彻底没有了"）；
3. 还在跑 ⇒ 不动它（下一拍它自己读到）；
4. 反真空：不是来信的 kind（板项）⇒ 不算叫醒。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top)


def _child(cond: Conductor, parent: str, *, status: str = "done") -> str:
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@x", "status": status,
        "outcome": "ok" if status == "done" else None, "refusal_reason": None,
        "instance": "D#1", "detail": "研究包已交回", "error": None,
        "started_at": BR, "ended_at": BR if status == "done" else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="probe:child")


def test_a_message_to_a_silent_agent_asks_the_execution_side_to_run_it(tmp_path):
    """①：终态未销号 ⇒ 判定为"该跑起来"，执行侧拿到的是同一个号。"""
    cond, parent = _env(tmp_path)
    child = _child(cond, parent)
    calls: list[dict] = []
    cond.resume_runner = lambda tid, **kw: calls.append({"tid": tid, **kw})
    item = cond.open_item(kind="message", role="D", expects="ack", action="message",
                          summary="来自 M 的一条留言", called_by="M",
                          parent_task_id=child, depth=3)
    got = getattr(cond, "last_consumer_reading", {})
    assert got.get("started") is True, (got, calls)
    assert calls and calls[0]["tid"] == child, calls
    assert calls[0]["item_id"] == item, calls
    assert "同号继续" in str(got.get("reason") or ""), got


def test_a_retired_agent_is_not_run(tmp_path):
    """②：已销号 ⇒ 不跑它（"彻底没有了"）。"""

    class _Sec:
        retired_names = ["t-999999"]

    cond, parent = _env(tmp_path)
    child = _child(cond, parent)
    cond.secretary = _Sec()          # 只有退役名单这一个读数
    calls: list[str] = []
    cond.resume_runner = lambda tid, **kw: calls.append(tid)
    cond._is_retired_task = lambda tid: True  # noqa: SLF001 —— 这一格要测的是"已销号就不跑"
    cond.open_item(kind="message", role="D", expects="ack", action="message",
                   summary="x", called_by="M", parent_task_id=child, depth=3)
    got = getattr(cond, "last_consumer_reading", {})
    assert got.get("started") is False, got
    assert "彻底没有了" in str(got.get("reason") or ""), got
    assert calls == [], calls


def test_a_running_agent_is_left_alone(tmp_path):
    """③：还在跑 ⇒ 不动它（板项它下一拍自己读到）。"""
    cond, parent = _env(tmp_path)
    child = _child(cond, parent, status="running")
    calls: list[str] = []
    cond.resume_runner = lambda tid, **kw: calls.append(tid)
    cond.open_item(kind="message", role="D", expects="ack", action="message",
                   summary="x", called_by="M", parent_task_id=child, depth=3)
    got = getattr(cond, "last_consumer_reading", {})
    assert got.get("started") is False, got
    assert "还在跑" in str(got.get("reason") or ""), got
    assert calls == [], calls


def test_a_plain_board_item_is_not_a_wake_up(tmp_path):
    """④ 反真空：不是来信的 kind ⇒ 不算叫醒（"板上有活"不是"接到消息"）。"""
    cond, parent = _env(tmp_path)
    child = _child(cond, parent)
    calls: list[str] = []
    cond.resume_runner = lambda tid, **kw: calls.append(tid)
    cond.open_item(kind="report", role="D", expects="work", action="report",
                   summary="x", called_by="M", parent_task_id=child, depth=3)
    got = getattr(cond, "last_consumer_reading", {})
    assert got.get("attempted") is False, got
    assert calls == [], calls
