# -*- coding: utf-8 -*-
"""O1（2026-10-27）：时钟底层的性能治本 —— 到点判定 / 等谁 / 每拍早退。

## 这一批改了什么（一句话一段）

改前每一拍 `fire_due` 都做三件 O(全表) 的事：

1. `TimerBook.pending()` 把整本台账（含已 fired / cancelled 的行）排序一遍；
2. `_probe_targets` 对每个不同的等待对象各问一次 `target_state`（一次台账读）；
3. 逐条 `due_reason`（每条还要抄一遍事件窗）。

改后三条各有落点：

- 到点判定：内存最小堆 `(due_at, seq)` + `next_due()` O(1) peek；`state.json` 一个字节
  不改，堆只是内存派生索引，`load` 时重建；
- 等谁：`waiters_by_target` 反查索引（`add` / `cancel` / 到点 / `load` 四处同步）+
  事件消账（事件到达当场判，判到的进热表，下一次 pump 只投它，不扫表）+
  补偿对账（`RECONCILE_EVERY_SEC`，漏发事件的唯一兜底）；
- 每拍早退：`now < min(堆顶, 下次对账, 下一次周期性巡查)` 且两个来源都读到时，
  立刻返回"查过了、没有到点的"，不扫表、不问 `target_state`。

## 判据（每条都写清"改前红在哪"，每条都反真空）

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| `test_a_the_heap_order_matches_the_linear_scan` | a) 堆给出的到点集合与顺序 == 线性扫（含同刻到期的顺序、已 fired / 已 cancelled 的不许冒出来） | 改前没有堆（`next_due` 不存在）；本条按"堆路径的 `fired` 次序 == 线性扫算出来的次序"钉 |
| `test_b_the_index_matches_the_full_table_scan` | b) `waiters_by_target` 反查 == 按 `wait_for` 过滤全表，且在 add / cancel / 到点 / 重载 四处同步之后仍然相等 | 改前没有反查索引（`waiters_of` 不存在） |
| `test_c_an_event_settles_the_waiter_before_the_next_pump` | c) 事件到达 ⇒ 那条表在下一次 pump 之前就被判到点（时延读数 ≈ 0），且下一次 pump 不扫表 | 改前只能等下一拍全扫（时延 = 一个 pump 的间隔，读数里没有这一格） |
| `test_c3_the_patrol_timer_is_not_swallowed_by_the_early_exit` | 早退不许吃掉 PATROL 那一档的到点 | 改前没有早退这一档（这一条是正控，改后必须绿） |
| `test_d_a_missed_event_is_still_caught_by_the_reconcile` | d) 故意漏发事件 ⇒ 对账之后仍然判掉（安全阀） | 改前每一拍都全扫，漏发事件也能扫到 |
| `test_d2_the_reconcile_is_load_bearing` | d) 的反真空：把对账打桩成"永远不对账" ⇒ d 的读数必红 | 改前没有对账这一处可打桩 |
| `test_e_the_readings_are_byte_identical_to_the_before_tree` | e) 一批夹具的输出 `sha256` == 改前树量到的那个数 | 正控（改前量出来的数就是被钉的那个） |
| `test_f_the_quiet_pump_costs_a_constant` | f) 同一本书上"早退的一拍"必须比"全扫的一拍"快一个数量级，且 `target_probe_count == 0` | 改前两档是同一件事（每拍都全扫） |
| `test_f2_the_full_scan_is_what_costs` | f) 的反真空：把"照旧全扫"打桩成每一拍都成立 ⇒ 探针数与耗时回退到改前 | 改前每一拍本来就全扫 |
| `test_g_the_root_cache_follows_the_workspace_switch` | g) `_resolve_root` 的解析缓存不许把两个工作区并成一个：切工作区之后读数必须立刻跟过去（同一目录的多种写法仍须解析成同一个根） | 改前没有解析缓存（`_resolve_root` 不存在） |

## 边界

全部 tmp 工作区、假时钟、替身探针与替身到点动作：零真实模型调用、零真睡、零网络。
时间只在两处被拨：`FakeClock.advance`（它会顺带推一拍，凡是要"没推过的拍"的地方
都先把 `clock.fire_due` 换成空桩再拨，见 `_tick`）。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from agentflow import clock as CLK

WALL = "2026-10-27T09:00:00+00:00"
SEED = 20261027


# ------------------------------------------------------------------ 夹具底座


@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（簿记 / 挂机视图 / 事件窗 / 两份读数都是进程级的）。

    "改后才有的那两份读数"用 `_reset_optional` 清：这一份判据要在改前树上也跑得起来，
    否则"先红后绿"红在夹具报错上，而不是红在被判的那件事上。
    """
    CLK.reset()
    CLK.reset_parked()
    CLK.reset_observed_events()
    _reset_optional()
    fake = CLK.use(CLK.FakeClock(wall=WALL, monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.set_target_probe(None)
        CLK.set_due_handler(None)
        CLK.reset()
        CLK.reset_parked()
        _reset_optional()


def _tick(monkeypatch: pytest.MonkeyPatch, bench, seconds: float) -> None:
    """拨假时钟，但不推那一拍。

    `FakeClock.advance` 会顺带调一次 `clock.fire_due()`（那是它的既有语义，判据不许改它）；
    而要证明"早退的那一拍"或"事件之后的第一拍"，就必须拿到一个没有被顺带推过的拍。
    于是这里把模块级的 `fire_due` 临时换成空桩 —— `advance` 里那一句 `fire_due()`
    走的是模块全局查找，所以桩打得进去；调用方自己用返回的真身去推。
    """
    real = CLK.fire_due
    monkeypatch.setattr(CLK, "fire_due", lambda *a, **k: {"checked": True, "fired": []})
    try:
        bench.advance(seconds)
    finally:
        monkeypatch.setattr(CLK, "fire_due", real)


def _row(seq: int, *, workspace: Path, due_after: float | None = None,
         wait_for: str = "", cap: float | None = None,
         state: str = "pending", kind: str = "timer",
         created_at: float = 0.0, note: str = "还在跑",
         wait_state: str = "open") -> dict[str, Any]:
    """一行 `state.json` 的计时器（键集与 `Timer.to_dict` 一致）。"""
    tid = f"tm-{seq:06d}"
    base = datetime.fromisoformat(WALL)
    created = (base + timedelta(seconds=created_at)).isoformat()
    due_at = ""
    due_epoch = None
    due_mono = None
    if due_after is not None:
        due = base + timedelta(seconds=due_after)
        due_at = due.isoformat()
        due_epoch = due.timestamp()
        due_mono = 1000.0 + due_after
    return {
        "timer_id": tid, "kind": kind, "reason": f"第 {seq} 条", "to": "self",
        "task_id": "t-000001", "role": "M", "workspace": str(workspace.resolve()),
        "created_at": created, "due_at": due_at, "due_epoch": due_epoch,
        "due_mono": due_mono, "clock_token": "", "state": state,
        "fired_at": (created if state == "fired" else ""),
        "mailbox_item_id": "", "wake_id": "", "note": note,
        "wait_for": wait_for, "wait_for_resolved": wait_for,
        "waiting_on": ({"kind": "roster", "name": "", "task_id": wait_for[5:]}
                       if wait_for else {}),
        "max_wait_sec": cap, "wait_state": (wait_state if wait_for else ""),
        "triggered_by": "", "woke_reason": "", "event_seq": 0, "message": "",
        "feedback": "", "parked_at": (created if wait_for else ""), "woke_at": "",
        "parked_steps": 0, "parked_calls": 0, "purpose_source": "given",
        "program": "", "argv_digest": "", "pid": None, "elapsed_sec": None,
        "exit_code": None, "outcome": "",
    }


def _write(workspace: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """把一本台账写到盘上（直接写 `state.json`：几百条时逐条走 `start_timer` 会写成千兆）。"""
    path = workspace / "out" / "clock" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": CLK.SCHEMA, "saved_at": WALL, "clock_token": "", "next_seq": 1,
           "timers": [dict(r) for r in rows], "periodics": []}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8", newline="")


def _probe(closed: bool = False) -> Any:
    """替身"等谁"读口：被等的对象一律 found=True，`closed` 决定它收口没有。"""
    def probe(workspace: str, kind: str, ref: str) -> dict[str, Any]:
        return {"checked": True, "found": True, "closed": bool(closed),
                "resolved": f"{kind}:{ref}", "why": "收口了" if closed else "还在跑",
                "task_text": ""}
    return probe


class _Sink:
    """替身到点动作：只记下"投了哪几条、按什么次序"，不写盘、不碰 store。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, timer: CLK.Timer) -> Mapping[str, Any]:
        self.seen.append(timer.timer_id)
        return {"mailbox_item_id": f"mx-{timer.timer_id}", "wake_id": "", "note": "stub"}


def _mixed_rows(workspace: Path, n: int = 200) -> list[dict[str, Any]]:
    """判据 a/b 的混合形：纯计时 / 等谁带上限 / 等谁无上限 / 已 fired / 已 cancelled。

    其中有 3 条同一时刻到点的纯计时（用来钉 tie-break：同刻到期按台账顺序），
    也有"due_at 已经过去但 state=fired/cancelled"的行（用来钉"终态不许冒出来"）。
    """
    rng = random.Random(SEED)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        pick = i % 5
        if pick == 0:
            # 到点都在 5 秒之后：第一拍（对账）一条都不该到，第二拍（拨 6.5 秒）到一批。
            rows.append(_row(i + 1, workspace=workspace,
                             due_after=rng.choice([5.0, 6.0, 30.0, 600.0 + i])))
        elif pick == 1:
            rows.append(_row(i + 1, workspace=workspace,
                             wait_for=f"task:t-{i:06d}", cap=900.0))
        elif pick == 2:
            rows.append(_row(i + 1, workspace=workspace,
                             wait_for=f"task:t-{i:06d}", cap=None))
        elif pick == 3:
            rows.append(_row(i + 1, workspace=workspace, state="fired",
                             due_after=-100.0 - i))
        else:
            rows.append(_row(i + 1, workspace=workspace, state="cancelled",
                             due_after=-200.0 - i))
    # 同刻到期的一簇（tie-break 的钉子）：三条不同的行都落在 WALL + 30 秒。
    for k in range(3):
        rows.append(_row(n + 100 + k, workspace=workspace, due_after=30.0))
    return rows


def _linear_due(bucket: CLK.TimerBook, reading: CLK.Reading) -> list[str]:
    """线性扫的参考实现（判据 a 要比的那一半）：按台账序逐条 `due_reason`。"""
    out: list[str] = []
    for timer in bucket.pending():
        reason, _why = timer.due_reason(reading, None)
        if reason:
            out.append(timer.timer_id)
    return out


# ------------------------------------------------------------------ a) 堆 == 线性扫


def test_a_the_heap_order_matches_the_linear_scan(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) 混合书上，"堆给出的到点集合与顺序"与"线性扫的结果"逐条相同。

    容器：200 条混合 + 3 条同刻到期 + 40 条终态行（due 在过去）。
    顺序：`fired` 的次序必须与 `_linear_due` 逐条相等 —— 同刻那 3 条按台账顺序。
    反真空：那 40 条终态行的 due 全在过去，它们一条都不许出现在 `fired` 里。
    """
    ws = tmp_path / "ws"
    rows = _mixed_rows(ws, 200)
    _write(ws, rows)
    CLK.set_target_probe(_probe(closed=False))
    sink = _Sink()
    CLK.set_due_handler(sink)
    dead = [r["timer_id"] for r in rows if r["state"] != "pending"]
    assert dead, "夹具里没有终态行 ⇒ 反真空那一半在空转"

    # 第一拍是对账（改前的行为也是第一拍全扫）；夹具里一条都不该在这一拍到点。
    first = CLK.fire_due(str(ws))
    assert first["fired"] == [], ("夹具在该到点的时候已经到点了", first["fired"])

    # 拨 6.5 秒（< 对账间隔 ⇒ 这一拍走的是堆路径），同一刻算出线性扫的结果再比。
    bucket = CLK.book(str(ws))
    _tick(monkeypatch, bench, 6.5)
    expect = _linear_due(bucket, CLK.now())
    assert expect, "线性扫一条到点的都没有 ⇒ 这条判据在空转"
    sink.seen.clear()
    report = CLK.fire_due(str(ws))
    got = [str(r.get("timer_id")) for r in (report.get("fired") or ())]
    assert got == expect, ("堆给出的到点集合与顺序 != 线性扫", got, expect)
    assert sink.seen == expect, (sink.seen, expect)
    assert not [t for t in got if t in set(dead)], ("终态行被当成到点投了出去", got)
    cost = CLK.cost_reading(str(ws))
    assert cost["checked"] is True, cost
    assert cost["early_exit"] is False, cost


def test_a2_the_heap_peek_is_the_next_due(tmp_path: Path, bench) -> None:
    """a) 的另一半：`next_due()` 的 peek 就是"下一条到点"，且它是 O(1) 的那一格。

    反真空：把最早到点的那一条取消 ⇒ peek 必须前移到下一条（堆不许留着它）。
    """
    ws = tmp_path / "ws"
    _write(ws, [_row(1, workspace=ws, due_after=600.0),
                _row(2, workspace=ws, due_after=5.0),
                _row(3, workspace=ws, due_after=900.0)])
    CLK.set_target_probe(_probe())
    CLK.set_due_handler(_Sink())
    peek = CLK.next_due(str(ws))
    assert peek["checked"] is True, peek
    assert peek["timer_id"] == "tm-000002", peek
    assert 4.9 <= float(peek["due_in_sec"]) <= 5.1, peek

    CLK.cancel_timer(str(ws), "tm-000002")
    peek = CLK.next_due(str(ws))
    assert peek["timer_id"] == "tm-000001", ("取消之后 peek 没有前移", peek)
    assert 599.0 <= float(peek["due_in_sec"]) <= 601.0, peek


# ------------------------------------------------------------------ b) 索引 == 全表扫


def test_b_the_index_matches_the_full_table_scan(
        tmp_path: Path, bench) -> None:
    """b) `waiters_by_target` 反查出的集合与"按 `wait_for` 过滤全表"逐条相同。

    四个同步点各查一遍：add（新起一条）/ cancel / 到点 / load（重建）。
    反真空：取消一条之后，索引里必须也没有它（否则这一条判据只测了 add）。
    """
    ws = tmp_path / "ws"
    rows = [_row(i + 1, workspace=ws, wait_for=f"task:t-{i % 4:06d}",
                 cap=(900.0 if i % 2 else None)) for i in range(12)]
    rows += [_row(100 + i, workspace=ws, due_after=600.0) for i in range(3)]
    _write(ws, rows)
    CLK.set_target_probe(_probe())
    CLK.set_due_handler(_Sink())
    bucket = CLK.book(str(ws))

    def compare(tag: str) -> None:
        keys = sorted({str(t.wait_for_resolved or t.wait_for)
                       for t in bucket.all() if t.state == "pending"
                       and (t.wait_for_resolved or t.wait_for)})
        assert keys, f"{tag}：一个等待对象都没有 ⇒ 判据在空转"
        for key in keys:
            got = [t.timer_id for t in bucket.waiters_of(key)]
            want = [t.timer_id for t in bucket.all()
                    if t.state == "pending"
                    and str(t.wait_for_resolved or t.wait_for) == key]
            assert got == want, (tag, key, got, want)
        # 反向：索引里不许有"全表扫不出来"的键
        for key in list(bucket._waiters):
            assert bucket.waiters_of(key), (tag, "索引里有一个空的键", key)

    compare("add 之后")

    cancelled = bucket.get("tm-000001")
    assert cancelled is not None and cancelled.wait_for
    CLK.cancel_timer(str(ws), "tm-000001")
    compare("cancel 之后")
    assert "tm-000001" not in [t.timer_id for t in bucket.waiters_of(
        str(cancelled.wait_for_resolved))], "取消之后索引里还有它"

    # 到点那一条（等谁 + 上限已经过了）之后，索引里也不许留着它
    CLK.set_due_handler(_Sink())
    later = CLK.now().wall
    assert later is not None
    fired_rows = [_row(200, workspace=ws, wait_for="task:t-000009", cap=1.0,
                       created_at=-10.0)]
    _write(ws, list(rows) + fired_rows)
    CLK.reset_books()
    bucket = CLK.book(str(ws))
    CLK.fire_due(str(ws))
    compare("到点之后")
    row = bucket.get("tm-000200")
    assert row is not None and row.state == "fired", (row.state if row else None)
    assert "tm-000200" not in [t.timer_id for t in bucket.waiters_of("task:t-000009")]

    CLK.reset_books()
    reloaded = CLK.book(str(ws))
    compare("load 重建之后")
    assert reloaded.pending_count() == len(reloaded.pending())


# ------------------------------------------------------------------ c) 事件消账


def test_c_an_event_settles_the_waiter_before_the_next_pump(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 投递一条"某子代理交差"的事件 ⇒ 等它的那条表在下一次 pump 之前就被判到点。

    读数三格：
    - `event_close_reading()["last"]["judged"]` 里有那一条（判发生在事件到达那一刻）；
    - `latency_ms` ≈ 0（改前是"一个 pump 的间隔"，读数里根本没有这一格）；
    - 下一次 pump 只投它、不问 target_state（`target_probe_count == 0`），
      而事件的正文仍逐字进到点消息里。
    """
    ws = tmp_path / "ws"
    _write(ws, [_row(1, workspace=ws, wait_for="task:t-000042")])
    probe_calls = {"n": 0}

    def counting(workspace: str, kind: str, ref: str) -> dict[str, Any]:
        probe_calls["n"] += 1
        return {"checked": True, "found": True, "closed": False,
                "resolved": f"{kind}:{ref}", "why": "还在跑", "task_text": ""}

    CLK.set_target_probe(counting)
    sink = _Sink()
    CLK.set_due_handler(sink)
    CLK.fire_due(str(ws))                      # 第一拍：对账（这一拍照旧全扫）

    CLK.observe_event("submit", task_id="t-000042", from_task_id="t-000042",
                      to_task_id="t-000001", role="D", content="交付：命题 P 已证")
    closed = CLK.event_close_reading()
    assert closed["checked"] is True, closed
    assert closed["last"]["judged"] == ["tm-000001"], closed
    assert closed["latency_ms"] is not None and closed["latency_ms"] < 200.0, closed
    assert closed["stats"]["observe_event"]["attempts"] >= 1, closed["stats"]
    assert closed["stats"]["observe_event"]["judged"] >= 1, closed["stats"]

    timer = CLK.book(str(ws)).get("tm-000001")
    assert timer is not None and timer.state == "pending", (
        "事件到达那一刻就把它投出去了 ⇒ 会把'本步刚派出去的子代理已经回来了'变成一次抢占",
        timer.state if timer else None)

    # 下一次 pump：只投热表里那一条，不扫表、不问 target_state
    probe_calls["n"] = 0
    _tick(monkeypatch, bench, 1.0)
    report = CLK.fire_due(str(ws))
    assert [r["timer_id"] for r in report["fired"]] == ["tm-000001"], report["fired"]
    assert probe_calls["n"] == 0, ("事件消账之后这一拍仍然问了 target_state", probe_calls)
    cost = CLK.cost_reading(str(ws))
    assert cost["target_probe_count"] == 0, cost
    assert cost["early_exit"] is False, cost
    fire = report["fired"][0]
    assert fire["triggered_by"] == "target_event", fire
    assert fire["woke_reason"] == "event", fire
    assert "命题 P 已证" in fire["message"], fire["message"]
    assert CLK.book(str(ws)).get("tm-000001").state == "fired"


def test_c2_the_event_settles_only_the_object_it_names(
        tmp_path: Path, bench) -> None:
    """c) 反真空：事件的对象键不对 ⇒ 一条都不判（不许"随便判一条"）。"""
    ws = tmp_path / "ws"
    _write(ws, [_row(1, workspace=ws, wait_for="task:t-000042"),
                _row(2, workspace=ws, wait_for="agent:D1")])
    CLK.set_target_probe(_probe())
    CLK.set_due_handler(_Sink())
    CLK.fire_due(str(ws))

    CLK.observe_event("submit", task_id="t-000777", from_task_id="t-000777", role="Z")
    closed = CLK.event_close_reading()
    assert closed["checked"] is True, closed
    assert closed["last"]["judged"] == [], ("键对不上却判了某一条", closed["last"])
    assert closed["last"]["waiters"] == 0, closed["last"]

    CLK.observe_event("message", task_id="t-000001", from_task_id="t-000042",
                      role="D", content="说话")
    closed = CLK.event_close_reading()
    assert closed["last"]["judged"] == ["tm-000001"], closed["last"]

    CLK.observe_event("message", task_id="t-000001", from_task_id="t-000999",
                      role="D1", content="说话")
    closed = CLK.event_close_reading()
    assert closed["last"]["judged"] == ["tm-000002"], ("按名册名等的那一条没被判", closed)


# ------------------------------------------------------------------ c2) 轮查不许被早退吃掉


def test_c3_the_patrol_timer_is_not_swallowed_by_the_early_exit(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """早退不许吃掉轮查那一档的到点（轮查计时器也在堆里，它到期必须被投）。

    反真空：轮查还没到期时那一拍必须早退（`early_exit is True` 且探针 0 次），
    到期那一拍必须不早退、且轮查被投出去 —— 两头都钉，才是"没被跳过"。
    """
    ws = tmp_path / "ws"
    CLK.set_target_probe(_probe())
    sink = _Sink()
    CLK.set_due_handler(sink)
    mounted = CLK.start_patrol_timer(str(ws), task_id="t-000001", role="M")
    assert mounted["checked"] is True and mounted["mounted"] is True, mounted
    timer = CLK.book(str(ws)).get(str(mounted["timer_id"]))
    assert timer is not None and CLK.is_patrol_timer(timer) is True, timer
    fired = timer.due_datetime()
    assert fired is not None

    CLK.fire_due(str(ws))                      # 第一拍：对账
    # 一小步一小步地拨（每一小步都 < 对账间隔 ⇒ 这些拍真的走的是早退那一档），
    # 于是"轮查到期那一拍不早退"是逐拍读出来的，不是靠一次大跳碰上的。
    real = CLK.fire_due
    monkeypatch.setattr(CLK, "fire_due", lambda *a, **k: {"checked": True, "fired": []})
    quiet_pumps = 0
    reconciles = 0
    fired_at: list[str] = []
    try:
        for _ in range(130):                   # 130 × 10 秒 = 1300 秒 > 1200 秒
            bench.advance(10.0)
            report = real(str(ws))
            cost = CLK.cost_reading(str(ws))
            got = [r["timer_id"] for r in report["fired"]]
            if got:
                fired_at = got
                assert cost["early_exit"] is False, (
                    "轮查到期那一拍居然早退了", cost)
                break
            if cost["reconcile_count"] == 1:
                # 每 30 秒一次补偿对账（`RECONCILE_EVERY_SEC`）：这一拍本来就该全扫。
                reconciles += 1
                continue
            assert cost["early_exit"] is True, ("安静的一拍没有早退", cost)
            quiet_pumps += 1
    finally:
        monkeypatch.setattr(CLK, "fire_due", real)
    assert quiet_pumps > 60, ("安静拍太少 ⇒ 这条判据没测到早退那一档", quiet_pumps)
    assert reconciles > 30, ("一路上一次对账都没发生 ⇒ 读数不对", reconciles)
    assert fired_at == [timer.timer_id], ("轮查到点被早退吃掉了", fired_at)
    message = CLK.book(str(ws)).get(timer.timer_id)
    assert message is not None and message.state == "fired", message.state
    assert message.message.startswith(CLK.PATROL_DUE_HEAD), message.message[:80]
    assert "【轮查】" in message.message, message.message[:80]


# ------------------------------------------------------------------ d) 补偿对账


def test_d_a_missed_event_is_still_caught_by_the_reconcile(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 故意不发事件（把产生点打桩掉）⇒ 下一次对账仍然把那条表判掉。

    这是安全阀：没有它，事件驱动就是"漏一个事件 ⇒ 那条表永久挂起"。
    """
    ws = tmp_path / "ws"
    _write(ws, [_row(1, workspace=ws, wait_for="task:t-000042")])
    CLK.set_target_probe(_probe(closed=False))
    CLK.set_due_handler(_Sink())
    CLK.fire_due(str(ws))

    # 被等的对象收口了，但一个事件都不发（等价于事件产生点漏发 / 被改坏）。
    CLK.set_target_probe(_probe(closed=True))
    _tick(monkeypatch, bench, 1.0)
    report = CLK.fire_due(str(ws))
    assert report["fired"] == [], (
        "没发事件却在下一拍就判掉了 ⇒ 这一条测不到对账", report["fired"])

    # 拨到对账时刻（RECONCILE_EVERY_SEC）之后：照样判掉。
    _tick(monkeypatch, bench, CLK.RECONCILE_EVERY_SEC + 0.5)
    report = CLK.fire_due(str(ws))
    got = [r["timer_id"] for r in report["fired"]]
    assert got == ["tm-000001"], ("对账没有把它救回来", got, report)
    assert report["fired"][0]["triggered_by"] == "target_closed", report["fired"][0]
    assert CLK.cost_reading(str(ws))["reconcile_count"] == 1, CLK.cost_reading(str(ws))


def test_d2_the_reconcile_is_load_bearing(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 的反真空：把对账打桩成"永远不对账" ⇒ 漏发的那一条永远判不掉。

    打桩点是 `TimerBook.needs_full_scan`（对账的唯一入口）：换成永远"不用对账"
    之后，d 的那条读数必须红 —— 于是"d 读的正是对账"是机器证明的。
    """
    ws = tmp_path / "ws"
    _write(ws, [_row(1, workspace=ws, wait_for="task:t-000042")])
    CLK.set_target_probe(_probe(closed=False))
    CLK.set_due_handler(_Sink())
    CLK.fire_due(str(ws))

    monkeypatch.setattr(CLK.TimerBook, "needs_full_scan",
                        lambda self, reading: (False, "打桩：永远不对账"))
    CLK.set_target_probe(_probe(closed=True))
    _tick(monkeypatch, bench, CLK.RECONCILE_EVERY_SEC * 3)
    report = CLK.fire_due(str(ws))
    assert report["fired"] == [], ("对账被打桩掉了却仍然判掉了 ⇒ d 读的不是对账",
                                   report["fired"])


# ------------------------------------------------------------------ e) 语义不变


#: 改前树（2026-10-27，commit c6bd3ec + 当时的工作树）量出来的读数摘要。
#:
#: 它怎么来的：`python -B temp/_clock_digest.py` 在改前树与改后树上各跑一遍，
#: 两次输出必须逐字相等（`_clock_digest.py` 的正文里写着复现步骤）。
#: 本判据把它钉成常量，于是"读数字节不变"是机器判据，不是一句声明。
#: 摘要里把 `HH:MM:SS` 与本机时区相关的那几位统一换成 `<T>`（它们随机器时区变，
#: 不是被钉的那件事），把 `clock_token`（uuid）与 `workspace`（tmp 绝对路径）换成
#: `<masked>`（随环境变，也不是读数）；正文的其余每一个字都在摘要里。
BEFORE_DIGEST = "cabe0992c91c981f4f38bc18f914a9cb61f84dd539366934acddcc875e5398f6"


#: 摘要里要抹掉的"随环境变、但不属于读数"的键：
#:
#: - `clock_token` 是每个 `FakeClock` 实例现取的 uuid（同一份夹具两次跑都不一样）；
#: - `workspace` 是 tmp 目录的绝对路径（pytest 每次给一个新目录）。
#:
#: 两个都不是"读数"：一个是时钟实例的身份、一个是临时目录名。抹掉它们之后，
#: 摘要剩下的每一个字都是语义。
_MASK_KEYS = frozenset({"clock_token", "workspace"})


def _mask(obj: Any) -> Any:
    """把本机时区相关的 `HH:MM:SS` 换成 `<T>`，把随环境变的键换成占位（其余一个字不动）。"""
    if isinstance(obj, str):
        return re.sub(r"\d\d:\d\d:\d\d", "<T>", obj)
    if isinstance(obj, Mapping):
        return {k: ("<masked>" if k in _MASK_KEYS else _mask(v))
                for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_mask(v) for v in obj]
    return obj


def _reset_optional() -> None:
    """清空"改后才有的"那两份读数（改前树没有它们 —— 这一份夹具要在两棵树上都跑得起来，
    否则"改前/改后同一批夹具"这句话就是假的）。"""
    for name in ("reset_costs", "reset_event_close"):
        fn = getattr(CLK, name, None)
        if callable(fn):
            fn()


def build_semantics_batch(ws: Path) -> dict[str, Any]:
    """同一批夹具（改前/改后各跑一遍，输出必须逐字相同）。

    覆盖被判据 e 点名的那几格：`due_message` 正文 / `Timer.row` / `waiters` /
    `clock.now` 读数 / `timer_list`。
    """
    CLK.reset()
    CLK.reset_parked()
    CLK.reset_observed_events()
    _reset_optional()
    fake = CLK.use(CLK.FakeClock(wall=WALL, monotonic=1000.0))
    CLK.set_target_probe(_probe(closed=False))
    sink = _Sink()
    CLK.set_due_handler(sink)
    out: dict[str, Any] = {}

    # 1. 纯计时 + 闹钟 + 等谁带上限 + 等谁无上限（目的缺一条）
    t1 = CLK.start_timer(str(ws), after_sec=90.0, reason="等 90 秒",
                         task_id="t-000001", role="M")
    t2 = CLK.start_alarm(str(ws), at="2026-10-27T09:05:00+00:00", reason="点名闹钟",
                         task_id="t-000001", role="M")
    t3 = CLK.start_timer(str(ws), wait_for="task:t-000042", reason="等 D 交回结论",
                         max_wait_sec=600.0, task_id="t-000001", role="M")
    t4 = CLK.start_timer(str(ws), wait_for="task:t-000043", task_id="t-000001", role="M")
    out["started"] = [t1.timer_id, t2.timer_id, t3.timer_id, t4.timer_id]

    # 2. 拨一拍：什么都没到点（读数里那句"下一拍多少秒后醒"不在摘要里 —— 它是耗时段）
    fake.advance(10.0)
    out["timer_list_step1"] = [_mask(t.row()) for t in CLK.timers(str(ws))]
    out["now_step1"] = _mask(CLK.now().to_dict())
    out["waiters_step1"] = _mask(CLK.waiters(str(ws)))

    # 3. 事件到达（子代理交差）→ 下一拍把等它的那条投出去
    #
    # 这一格刻意不进摘要：`event_close_reading()` 是改后才有的读数，改前树根本没有它
    # （"同一批夹具两棵树都跑得起来"是这一节的前提）。事件消账的判据在 `test_c` 里单列。
    CLK.observe_event("submit", task_id="t-000042", from_task_id="t-000042",
                      to_task_id="t-000001", role="D", content="交付：命题 P 已证")
    fake.advance(1.0)

    # 4. 上限到点（等 t-000043 的那条带 600 秒上限）
    fake.advance(600.0)
    out["due_messages"] = [t.message for t in CLK.timers(str(ws))
                           if t.state == "fired"]
    out["timer_list_step2"] = [_mask(t.row()) for t in CLK.timers(str(ws))]
    out["waiters_step2"] = _mask(CLK.waiters(str(ws)))
    out["now_step2"] = _mask(CLK.now().to_dict())
    out["timers_missing_purpose"] = _mask(CLK.timers_missing_purpose(str(ws)))

    # 5. 落盘那一份（`state.json` 的 timers 行；`saved_at` 与 `clock_token` 不算读数）
    doc = json.loads((Path(ws) / "out" / "clock" / "state.json").read_text(encoding="utf-8"))
    out["state_rows"] = _mask(doc.get("timers"))
    out["state_next_seq"] = doc.get("next_seq")
    out["sink"] = list(sink.seen)
    return _mask(out)


def test_e_the_readings_are_byte_identical_to_the_before_tree(tmp_path: Path) -> None:
    """e) 一批夹具的输出 `sha256` == 改前树量到的那个数（逐字相同）。"""
    got = build_semantics_batch(tmp_path / "ws")
    digest = hashlib.sha256(
        json.dumps(got, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert digest == BEFORE_DIGEST, (
        "读数字节变了 —— 语义不变的硬约束被碰了",
        digest, BEFORE_DIGEST, sorted(got))


# ------------------------------------------------------------------ f) 成本


def test_f_the_quiet_pump_costs_a_constant(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 同一本书上"早退的一拍"必须比"全扫的一拍"快一个数量级，探针 0 次。

    两档在同一进程、同一本书上量（跨机器的绝对值会漂，比值不漂）：
    - 全扫那一拍 = `due_timers`（它就是"按台账逐条判"的那一份）；
    - 早退那一拍 = `fire_due`（对过账之后、什么都没到点的那一拍）。

    反真空：`early_exit` 必须是 True，`target_probe_count` 必须是 0 ——
    否则"更快"可能只是书变小了。
    """
    ws = tmp_path / "ws"
    rows = [_row(i + 1, workspace=ws,
                 due_after=600.0 + i if i % 2 else None,
                 wait_for=("" if i % 2 else f"task:t-{i:06d}"),
                 cap=(900.0 if i % 4 == 0 else None)) for i in range(400)]
    _write(ws, rows)
    calls = {"n": 0}

    def counting(workspace: str, kind: str, ref: str) -> dict[str, Any]:
        calls["n"] += 1
        return {"checked": True, "found": True, "closed": False,
                "resolved": f"{kind}:{ref}", "why": "还在跑", "task_text": ""}

    CLK.set_target_probe(counting)
    CLK.set_due_handler(_Sink())
    CLK.fire_due(str(ws))                      # 第一拍：对账

    import time as _time
    _tick(monkeypatch, bench, 1.0)
    calls["n"] = 0
    t0 = _time.perf_counter()
    report = CLK.fire_due(str(ws))
    quiet = (_time.perf_counter() - t0) * 1000.0
    quiet_probes = calls["n"]
    assert report["fired"] == [], report["fired"]
    cost = CLK.cost_reading(str(ws))
    assert cost["early_exit"] is True, cost
    assert quiet_probes == 0, ("早退那一拍仍然问了 target_state", quiet_probes)
    assert cost["target_probe_count"] == 0, cost

    _tick(monkeypatch, bench, 1.0)
    t0 = _time.perf_counter()
    CLK.due_timers(str(ws))
    full = (_time.perf_counter() - t0) * 1000.0
    assert full > 0.0, full
    assert quiet * 10.0 < full, (
        "早退那一拍没有比全扫快一个数量级", {"quiet_ms": round(quiet, 4),
                                            "full_ms": round(full, 4)})


def test_f2_the_full_scan_is_what_costs(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 的反真空：把"照旧全扫"打桩成每一拍都成立 ⇒ 探针数与耗时回退到改前。

    打桩点选 `TimerBook.needs_full_scan`（全扫的唯一判据），不是 `can_early_exit`：
    改后"什么都不用扫"的那一档有两条兄弟路（早退与堆路径），只把早退打桩掉，
    那一拍会落到堆路径上，探针照样是 0 —— 那不是"回退到改前"。真正的回退到改前，
    是让这一拍重新全表扫一遍。所以这条判据钉两件：

    1. 打桩之前：安静的一拍探针 0 次（O(1)）；
    2. 把 `needs_full_scan` 打桩成永远 True（= 改前的每一拍）：探针 30 次
       （= 不同的等待对象个数），于是 f 读的确实是"有没有全扫"。
    """
    ws = tmp_path / "ws"
    rows = [_row(i + 1, workspace=ws, wait_for=f"task:t-{i:06d}", cap=None)
            for i in range(30)]
    _write(ws, rows)
    calls = {"n": 0}

    def counting(workspace: str, kind: str, ref: str) -> dict[str, Any]:
        calls["n"] += 1
        return {"checked": True, "found": True, "closed": False,
                "resolved": f"{kind}:{ref}", "why": "还在跑", "task_text": ""}

    CLK.set_target_probe(counting)
    CLK.set_due_handler(_Sink())
    CLK.fire_due(str(ws))                      # 第一拍：对账
    _tick(monkeypatch, bench, 1.0)
    calls["n"] = 0
    CLK.fire_due(str(ws))
    assert calls["n"] == 0, ("没打桩之前就在问 target_state", calls["n"])
    assert CLK.cost_reading(str(ws))["early_exit"] is True, CLK.cost_reading(str(ws))

    monkeypatch.setattr(CLK.TimerBook, "needs_full_scan",
                        lambda self, reading: (True, "打桩：每一拍都照旧全扫"))
    calls["n"] = 0
    _tick(monkeypatch, bench, 1.0)
    CLK.fire_due(str(ws))
    assert calls["n"] == len(rows), (
        "打桩成'每一拍全扫'之后仍然不问 target_state ⇒ f 读的不是全扫",
        calls["n"], len(rows))
    cost = CLK.cost_reading(str(ws))
    assert cost["reconcile_count"] == 1, cost
    assert cost["target_probe_count"] == len(rows), cost


# ------------------------------------------------------------------ g) 解析缓存的失效面


def test_g_the_root_cache_follows_the_workspace_switch(
        tmp_path: Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_resolve_root` 的缓存不许把两个工作区并成一个：切工作区必须立刻读到新根。

    缓存今天靠"同一个字符串 -> 同一个绝对路径"这条纯函数性站着，但"切工作区"是
    "同一个字符串、可能不同的现实"那个边界（符号链接换指向 / 大小写 / 盘符映射）。
    两面都钉：

    - 正控（安全的那一面）：同一目录的三种写法（原样 / 全大写 / 末尾 `.`）必须解析成
      同一个根 —— 否则同一个工作区会被开出第二份簿记，读数分家；
    - 钉子（危险的那一面）：`using_workspace` 切到另一个目录之后，`current_workspace()`
      与刚跑的那一拍的读数必须都是新根的（A 有 1 条 pending、B 有 2 条，可区分）。

    反真空：把 `_resolve_root` 打桩成"恒返回第一次解析出来的那个根" ⇒ 上面那条钉子必红
    （读数会留在旧根上）。这里直接让那条断言在桩下重跑一次、要求它抛 `AssertionError`。
    """
    ws_a = tmp_path / "wsA"
    ws_b = tmp_path / "wsB"
    _write(ws_a, [_row(1, workspace=ws_a, due_after=600.0)])
    _write(ws_b, [_row(1, workspace=ws_b, due_after=600.0),
                  _row(2, workspace=ws_b, due_after=700.0)])
    CLK.set_target_probe(_probe())
    CLK.set_due_handler(_Sink())
    root_a = str(ws_a.resolve())
    root_b = str(ws_b.resolve())

    # 正控：三种写法 -> 同一个根（不会为同一个工作区开出第二份簿记）
    spellings = {CLK._resolve_root(str(ws_a)),
                 CLK._resolve_root(str(ws_a).upper()),
                 CLK._resolve_root(f"{ws_a}{os.sep}.")}
    assert spellings == {root_a}, ("同一个目录的几种写法解析成了不同的根", spellings)

    with CLK.using_workspace(str(ws_a)):
        assert CLK.current_workspace() == root_a
        CLK.fire_due(CLK.current_workspace())
        cost_a = CLK.cost_reading()
    assert cost_a["workspace"] == root_a, cost_a
    assert cost_a["pending_count"] == 1, cost_a

    with CLK.using_workspace(str(ws_b)):
        assert CLK.current_workspace() == root_b, ("切工作区之后缺省还是旧根",
                                                   CLK.current_workspace(), root_b)
        CLK.fire_due(CLK.current_workspace())
        cost_b = CLK.cost_reading()
    assert cost_b["workspace"] == root_b, ("切工作区之后读数还留在旧根上", cost_b)
    assert cost_b["pending_count"] == 2, cost_b

    # 反真空：缓存打桩成"恒返回第一次的根" ⇒ 上面那条钉子必须红
    monkeypatch.setattr(CLK, "_resolve_root", lambda workspace: root_a)
    CLK.reset_costs()
    CLK.reset_books()
    with CLK.using_workspace(str(ws_b)):
        CLK.fire_due(CLK.current_workspace())
        stuck = CLK.cost_reading()
    assert stuck["workspace"] == root_a, ("打桩之后居然还读到了 B ⇒ 桩没打进去", stuck)
    assert stuck["pending_count"] == 1, stuck
    with pytest.raises(AssertionError):
        assert stuck["workspace"] == root_b, "打桩：切到 B 之后读数必须跟着走"
