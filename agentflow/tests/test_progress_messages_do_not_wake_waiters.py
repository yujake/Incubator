# -*- coding: utf-8 -*-
"""判据（D11 第③件）：进度留言只落消息，不唤醒等待。

## 这一条钉的是什么

审计（`temp/_audit_steps_and_timeouts.md` §2.1）确认：`observe_message` 把**任何**
`agent_message` 记成时钟事件，而 `_event_hits` 按 `task_id / from_task_id` 命中 ⇒
子的「步数报告」被父的等待计时器当成「它说了话」，生成「时间到」notice（真机 33 条
「时间到」里有 8 条就是这么来的）。

改法：发送侧给进度留言带 `extra={"progress": True}`；观测侧读到这一格就**只落消息、
不 `observe_event`**（消息本身已由 `send_message` 落进会话，父下一步照常读到）。

## 三条判据（两条正控 + 一条反真空）

1. 带 `progress` 的留言：`observe_message` 返回 `None`，事件窗里 `message` / `delivery`
   都是 0，那条等它的计时器仍是 `pending`，下一拍 `fire_due` 一条都不投；
2. 同一条留言**摘掉** `progress`：它立刻被记成事件、消账命中那条计时器，下一拍以
   `target_event` 投出去 —— 这就是「把标记摘掉 ⇒ 不该唤醒的唤醒又出现」的反真空；
3. 留言本身仍送达：`send_message(..., extra={"progress": True})` 落盘带 `progress=True`，
   `read_messages` 从父的收件箱读得到（"不唤醒"不等于"没送到"）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import sessions as SS

WALL = "2026-11-09T10:00:00+00:00"


@pytest.fixture()
def bench(tmp_path: Path):
    """假时钟 + 清空进程内簿记；产出 `(workspace, target_probe 计数)`。"""
    CLK.reset()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.use(CLK.FakeClock(wall=WALL, monotonic=1000.0))
    ws = tmp_path / "ws"
    probes = {"n": 0}

    def probe(workspace: str, kind: str, ref: str) -> dict[str, Any]:
        probes["n"] += 1
        return {"checked": True, "found": True, "closed": False,
                "resolved": f"{kind}:{ref}", "why": "还在跑", "task_text": ""}

    CLK.set_target_probe(probe)
    CLK.set_due_handler(_Sink())
    try:
        yield ws, probes
    finally:
        CLK.set_target_probe(None)
        CLK.set_due_handler(None)
        CLK.reset()
        CLK.reset_parked()
        CLK.reset_observed_events()


class _Sink:
    """替身到点动作：只记下投了哪几条，不写盘、不碰 store。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, timer: CLK.Timer) -> Mapping[str, Any]:
        self.seen.append(timer.timer_id)
        return {"mailbox_item_id": f"mx-{timer.timer_id}", "wake_id": "", "note": "stub"}


def _row(seq: int, *, workspace: Path, wait_for: str = "") -> dict[str, Any]:
    """一行 `state.json` 的计时器：等 `wait_for`，无钟点、无上限。"""
    created = datetime.fromisoformat(WALL).isoformat()
    return {
        "timer_id": f"tm-{seq:06d}", "kind": "timer", "reason": f"第 {seq} 条", "to": "self",
        "task_id": "t-000001", "role": "M", "workspace": str(workspace.resolve()),
        "created_at": created, "due_at": "", "due_epoch": None, "due_mono": None,
        "clock_token": "", "state": "pending", "fired_at": "", "mailbox_item_id": "",
        "wake_id": "", "note": "还在跑", "wait_for": wait_for,
        "wait_for_resolved": wait_for,
        "waiting_on": ({"kind": "roster", "name": "", "task_id": wait_for[5:]}
                       if wait_for else {}),
        "max_wait_sec": None, "wait_state": ("open" if wait_for else ""),
        "triggered_by": "", "woke_reason": "", "event_seq": 0, "message": "",
        "feedback": "", "parked_at": (created if wait_for else ""), "woke_at": "",
        "parked_steps": 0, "parked_calls": 0, "purpose_source": "given",
        "program": "", "argv_digest": "", "pid": None, "elapsed_sec": None,
        "exit_code": None, "outcome": "",
    }


def _write(workspace: Path, rows: list[dict[str, Any]]) -> None:
    path = workspace / "out" / "clock" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": CLK.SCHEMA, "saved_at": WALL, "clock_token": "", "next_seq": 1,
           "timers": [dict(r) for r in rows], "periodics": []}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8", newline="")


def _progress_rec(**over: Any) -> dict[str, Any]:
    """生产形态的那条留言（发送侧 `send_message(..., extra={"progress": True})`）。"""
    rec = {
        "kind": "agent_message", "msg_id": "m0001", "from": "A", "to": "M",
        "subject": "步数报告：A 已用 30 步（不是上限）",
        "body": "步数报告（第 1 次，仅上报）：已用 30 步（阈值 30，不是上限）；…",
        "from_task_id": "t-000042", "progress": True,
    }
    rec.update(over)
    return rec


def _seed_waiter(ws: Path) -> None:
    """一本台账：一条等 `task:t-000042` 的表；推一拍把索引建起来。"""
    _write(ws, [_row(1, workspace=ws, wait_for="task:t-000042")])
    CLK.fire_due(str(ws))


def test_a_progress_message_does_not_wake_the_waiter(bench) -> None:
    """正控：带 `progress` ⇒ 不记事件、不消账、下一拍不投，表仍是 pending。"""
    ws, _probes = bench
    _seed_waiter(ws)
    closed_before = CLK.event_close_reading()["count"]

    got = CLK.observe_message(_progress_rec())
    assert got is None, ("进度留言被记成时钟事件了 ⇒ `_event_hits` 会把它当成"
                         "「被等对象说话了」", got)
    counts = CLK.observed_events()["counts"]
    assert int(counts.get("message") or 0) == 0, counts
    assert int(counts.get("delivery") or 0) == 0, ("进度留言仍然记了投递事件 ⇒ "
                                                   "「等父」那一档会被叫醒", counts)
    assert CLK.event_close_reading()["count"] == closed_before, (
        "进度留言触发了消账（判定到点）", CLK.event_close_reading()["last"])

    timer = CLK.book(str(ws)).get("tm-000001")
    assert timer is not None and timer.state == "pending", timer.state if timer else None
    fired = CLK.fire_due(str(ws))["fired"]
    assert fired == [], ("下一拍仍然把这条表投出去了（进度留言应当只落消息）", fired)


def test_without_the_progress_marker_the_wake_comes_back(bench) -> None:
    """反真空：同一条留言摘掉 `progress` ⇒ 立刻被当成「它说话了」，下一拍投出去。

    这一条就是「把 progress 标记摘掉 ⇒ 那条不该唤醒的唤醒又出现」的机器读数：
    它必须红在"没有 progress"的那一半，而不是红在夹具上。
    """
    ws, _probes = bench
    _seed_waiter(ws)
    closed_before = CLK.event_close_reading()["count"]

    rec = _progress_rec()
    rec.pop("progress")
    got = CLK.observe_message(rec)
    assert got is not None and got.kind == "message", got
    closed = CLK.event_close_reading()
    assert closed["count"] > closed_before, (
        "摘掉 progress 之后没有消账 ⇒ 这一条测不出「唤醒」那一半", closed["last"])
    assert closed["last"]["judged"] == ["tm-000001"], (
        "摘掉 progress 之后没有消账 ⇒ 这一条测不出「唤醒」那一半", closed["last"])

    report = CLK.fire_due(str(ws))
    assert [r["timer_id"] for r in report["fired"]] == ["tm-000001"], report["fired"]
    assert report["fired"][0]["triggered_by"] == "target_event", report["fired"][0]
    assert "步数报告" in report["fired"][0]["message"], report["fired"][0]["message"]


def test_a_progress_message_still_reaches_the_parents_inbox(tmp_path: Path, bench) -> None:
    """正控（送达）：`progress` 只关掉"唤醒"，不关掉"留言" —— 父收件箱里照常有它。"""
    root = tmp_path / "sess"
    mid, problem = AL.send_message(
        root, sender="A", to="M",
        subject="步数报告：A 已用 30 步（不是上限）",
        body="步数报告（第 1 次，仅上报）：…", from_task_id="t-000042",
        extra={"progress": True})
    assert not problem, problem
    events, problems = SS.read_session(root)
    assert not problems, problems
    rec = next(e for e in events if e.get("msg_id") == mid)
    assert rec.get("progress") is True, rec
    msgs, problems = AL.read_messages(root, "M")
    assert not problems, problems
    assert [m["msg_id"] for m in msgs] == [mid], msgs
    # 生产钩子拿到的就是这条落盘记录：喂给时钟仍然不唤醒。
    assert CLK.observe_message(rec) is None, rec
