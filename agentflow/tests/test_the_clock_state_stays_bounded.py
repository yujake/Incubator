"""D-05：`out/clock/state.json` 必须有界 —— 终态计时器不许无限累积。

真机读数（2026-10-28，`projects/paper-rewrite-78`，3 小时那一趟）：
```
50 分钟：state.json 158 KB / timers 82 条（fired+cancelled 72 条 = 88%）
110 分钟：350 KB / 172 条（终态 121 条）；斜率 1.6 KB/分钟、0.84 条/分钟
外推：10 小时 ≈ 1 MB / 500 条，24 小时 ≈ 2.4 MB / 1200 条
```
而 `TimerBook.save()` 每次整份重写（`_atomic_json(state_path, doc)`），
所以写放大随运行时长线性上升 —— 本项目常态就是小时级跑。

四条判据：① 终态被压在上限内；② pending 一条都不许动；
③ 清掉多少条必须有读数；④ 上限之内一条都不许动（不是"每次 save 都清空"）。
"""

from __future__ import annotations

import json
import pathlib

from agentflow import clock as C

WS = "ws"          # 工作区名（相对 tmp_path）


def _book(tmp_path: pathlib.Path) -> C.TimerBook:
    book = C.book(tmp_path)
    book.save()
    return book


def _one(book: C.TimerBook, *, purpose: str, after: float, to: str = "t-000001") -> C.Timer:
    """起一条一次性计时器（与工具层同一条工厂 + 同一个发号器）。"""
    timer = C._new_timer(book.workspace, kind="timer", reason=purpose, to=to,
                         task_id="t-000001", role="M", after_sec=after)
    # 号由簿记的发号器发（`_new_timer` 只造形状，`timer_id` 留给这一层）——
    # 忘了这一步会得到一堆空号，`add` 按同一个键互相覆盖（实测：5 条只剩 1 条）。
    timer.timer_id = book.allocate("tm")
    book.add(timer)
    return timer


def _finish(timer: C.Timer, at: str = "2026-10-28T00:00:00+00:00") -> None:
    """把它落成终态（fired）—— 纯历史，不进堆、不参与到点判定。"""
    timer.state = "fired"
    timer.fired_at = at


def _doc(tmp_path: pathlib.Path) -> dict:
    return json.loads((tmp_path / "out" / "clock" / "state.json").read_text(encoding="utf-8"))


def test_terminal_timers_are_bounded(tmp_path: pathlib.Path) -> None:
    """正控：终态条目超过上限之后，落盘的条数不许再涨。"""
    book = _book(tmp_path)
    for i in range(C.MAX_TERMINAL_KEPT + 60):
        _finish(_one(book, purpose=f"done-{i}", after=60.0 + i))
    book.save()
    terminal = [t for t in _doc(tmp_path)["timers"]
                if str(t.get("state")) in ("fired", "cancelled")]
    assert len(terminal) <= C.MAX_TERMINAL_KEPT, (
        f"终态条目 {len(terminal)} 条超了上限 {C.MAX_TERMINAL_KEPT} —— "
        "state.json 会随运行时长线性增长")


def test_pending_timers_are_never_pruned(tmp_path: pathlib.Path) -> None:
    """反真空：pending 一条都不能少（清掉它 = 那个人永远醒不了）。"""
    book = _book(tmp_path)
    pend = [_one(book, purpose=f"wait-{i}", after=3600.0 + i) for i in range(30)]
    for i in range(C.MAX_TERMINAL_KEPT + 40):
        _finish(_one(book, purpose=f"old-{i}", after=60.0 + i))
    book.save()
    still = {t["timer_id"] for t in _doc(tmp_path)["timers"]
             if str(t.get("state")) == "pending"}
    assert {t.timer_id for t in pend} <= still, "pending 被清掉了"


def test_the_pruning_is_recorded(tmp_path: pathlib.Path) -> None:
    """读得出来：清掉多少条必须有读数（不许静默丢历史）。"""
    book = _book(tmp_path)
    for i in range(C.MAX_TERMINAL_KEPT + 25):
        _finish(_one(book, purpose=f"done-{i}", after=60.0 + i))
    book.save()
    doc = _doc(tmp_path)
    assert int(doc.get("dropped_terminal") or 0) > 0, (
        "清了终态条目却没留下 dropped_terminal 读数 —— 那就成了静默丢历史")
    again = C.book(tmp_path)
    assert int(again.terminal_dropped()) == int(doc.get("dropped_terminal") or 0), (
        "重新装载之后读数丢了")


def test_under_the_cap_nothing_is_dropped(tmp_path: pathlib.Path) -> None:
    """负控：上限之内的终态条目一条都不许动（不是"每次 save 都清空"）。"""
    keep = max(1, C.MAX_TERMINAL_KEPT // 4)
    book = _book(tmp_path)
    for i in range(keep):
        _finish(_one(book, purpose=f"done-{i}", after=60.0 + i))
    book.save()
    doc = _doc(tmp_path)
    terminal = [t for t in doc["timers"] if str(t.get("state")) in ("fired", "cancelled")]
    assert len(terminal) == keep
    assert int(doc.get("dropped_terminal") or 0) == 0
