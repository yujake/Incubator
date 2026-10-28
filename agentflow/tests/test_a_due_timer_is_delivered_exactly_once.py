"""D-07：同一条计时器的"到点"只许投递一次（并发 pump 不许各投一次）。

真机铁证（2026-10-28，projects/paper-rewrite-78）：
```
t-000093 / t-000094 两条 notice 的 input_key 完全相同（'clock:tm-000088'），
相隔 1 秒；而 state.json 里 tm-000088 只有一条、fired 一次、mailbox_item_id 只记着后者。
5 轮轮查里 2 轮双发 ⇒ 间歇竞态：两个线程同时 pump 时钟，都看见 pending，都调了一次到点动作。
根因在 `clock._deliver_one`：先调 `_DUE_HANDLER(timer)`（它会开一条板项 = 一笔 store 事务），
之后才 `timer.state = "fired"` 并 `bucket.save()` —— 中间那一整段没有任何锁。
```
三条判据：① 两个线程同时 pump，同一条到点 timer 只许投递一次；
② 板项按 input_key 幂等（同一键已有行 ⇒ 复用，不新建）；
③ 负控：把锁换成 no-op ⇒ 上面那条必须变红（证明锁是承重的）。
"""

from __future__ import annotations

import json
import pathlib
import threading
import time

from agentflow import clock as C


def _due_timer(tmp_path: pathlib.Path) -> tuple[C.TimerBook, C.Timer]:
    book = C.book(tmp_path)
    book.save()
    timer = C._new_timer(book.workspace, kind="timer", reason="并发投递探针",
                         to="t-000001", task_id="t-000001", role="M", after_sec=0.01)
    timer.timer_id = book.allocate("tm")
    book.add(timer)
    return book, timer


def _slow_handler(receipts: list[dict]) -> None:
    """把到点动作换成一个"慢"的：窗口越宽，竞态越容易复现。"""

    def handler(timer: C.Timer) -> dict:
        time.sleep(0.05)
        receipts.append({"timer_id": timer.timer_id})
        return {"mailbox_item_id": f"item-{len(receipts)}"}

    C.set_due_handler(handler)


def test_one_due_timer_is_delivered_once_under_concurrency(tmp_path: pathlib.Path) -> None:
    """正控：两个线程同时推进时钟，同一条计时器只许投递一次。"""
    book, timer = _due_timer(tmp_path)
    receipts: list[dict] = []
    _slow_handler(receipts)
    try:
        time.sleep(0.05)          # 让它真到点（堆按 due_at 建，直接改字段不进堆）
        barrier = threading.Barrier(2)

        def pump() -> None:
            barrier.wait()
            C.fire_due(tmp_path)

        threads = [threading.Thread(target=pump) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
    finally:
        C.set_due_handler(None)
    assert len(receipts) == 1, (
        f"同一条计时器被投递了 {len(receipts)} 次 —— 真机上这就是 M 每 20 分钟做两遍轮查")
    again = C.book(tmp_path)
    got = again.get(timer.timer_id)
    assert got is not None and str(got.state) == "fired"


def test_the_mailbox_item_is_idempotent_by_input_key(tmp_path: pathlib.Path) -> None:
    """② 板项按 input_key 幂等：同一个 `clock:<timer_id>` 只该有一条行。"""
    from agentflow import store as ST
    from agentflow import conductor as CD

    st = ST.Store(tmp_path)
    st.init()
    box = CD.Conductor(st)
    first = box.open_item(kind="notice", role="M", expects="ack", action="notice",
                          summary="到点 1", called_by="clock", depth=1,
                          input_key="clock:tm-000777")
    second = box.open_item(kind="notice", role="M", expects="ack", action="notice",
                           summary="到点 2", called_by="clock", depth=1,
                           input_key="clock:tm-000777")
    rows = [r for r in box._tasks() if str(r.get("input_key")) == "clock:tm-000777"]
    assert len(rows) == 1, f"同一 input_key 落了两行（{first} / {second}）—— 真机上就是两条重复的轮查"
    assert first == second, "第二次应该复用那一行"


def test_the_lock_is_load_bearing(tmp_path: pathlib.Path, monkeypatch) -> None:
    """③ 负控：把锁换成 no-op ⇒ 上一条正控必须变红（否则那条判据在空跑）。"""
    book, timer = _due_timer(tmp_path)
    receipts: list[dict] = []
    _slow_handler(receipts)
    monkeypatch.setattr(C, "_FIRE_LOCK", _NoopLock())
    try:
        time.sleep(0.05)
        barrier = threading.Barrier(2)

        def pump() -> None:
            barrier.wait()
            C.fire_due(tmp_path)

        threads = [threading.Thread(target=pump) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
    finally:
        C.set_due_handler(None)
    assert len(receipts) > 1, (
        "把锁换成 no-op 之后仍然只投递一次 ⇒ 这条正控不是被锁守着的（判据空跑）")


class _NoopLock:
    def __enter__(self) -> "_NoopLock":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False
