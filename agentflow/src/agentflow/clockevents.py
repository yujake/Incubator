# -*- coding: utf-8 -*-
"""系统时钟的观测窗与消账：事件总线、观测读数、被等对象收口时的消账。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第三刀。它坐在
`clockbase`（事件原语与词表）与 `clockrun`（唯一取时口 / 进程内簿记）之上，
上层（`clocktimer` / `clockfire` / `clockprogram` …）单向 import 这里。

## 装了什么

* 观测窗：`EVENT_BUFFER`（进程内上限）、`_EVENT_SEQ`（序号）、`_event_seq()`（唯一读口）
  与 `observe_event` / `observe_message` / `observe_work` / `observed_events` /
  `reset_observed_events`；`_event_hits(timer)` 是"这条计时器等的东西有没有新动静"；
* 挂机表：`_PARKED` / `_register_parked` / `_unregister_parked` / `reset_parked`；
* 收口消账：`_CLOSE` 计数、`_close_waiters_for_event`（一条事件落地时把在等它的计时器
  叫醒）、`event_close_reading` / `reset_event_close` 两份读数；
* `_CLOSE_LOCK` / `_CLOSE_DEPTH`：消账的锁与重入深度。

## 为什么 `_EVENT_SEQ` 必须留在这个模块

它被 `observe_event` / `reset_observed_events` 重新赋值（`global _EVENT_SEQ`），
而 `_event_seq()` 与 `observe_event` 读它。模块级可变量的重新赋值不会跨模块传播
（`from .mod import X` 拿的是快照），所以"写它的两处 + 读它的两处"必须同处一个模块。
第一刀曾把它单独搬到最底层，结果事件序号静默地不前进（修在 cff86fe6）。

`_PARKED: dict[str, Timer]` 的 `Timer` 只出现在注解里（`from __future__ import annotations`
之下是字符串），所以本模块不需要 import `Timer` —— 依赖方向仍然是单向的：本模块不 import
`clocktimer`。

## 与 `clock.py` 的关系

`clock.py` 是门面：它 `from .clockevents import ...` 再导出，调用点一个字都不用改。
拆分前后每个顶层名的 AST dump 逐字相同（判据 `temp/split1_move.py` 的 [equiv] 自检）。
"""

from __future__ import annotations

import threading
import time
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockParamError,
    EVENT_CLOSE_HOOKS,
    EVENT_EXCERPT,
    EVENT_KINDS,
    ObservedEvent,
    WORK_EVENT_KINDS,
    _EVENTS,
    _EVENT_COUNTS,
    _EVENT_LOCK,
    _iso,
    _parse_target_loose,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _BOOKS,
    now,
)

#: 进程内的事件流上限：这是"最近发生了什么"的观测窗，不是审计账（审计在会话记录里）。
EVENT_BUFFER: int = 512

#: 事件序号：观测窗内的先后次序由它给（`_event_seq()` 是它唯一的读口）。
#: 它必须和两个重新赋值的落点（`observe_event` / `reset_observed_events`）同处一个模块
#: —— 跨模块 `global` 只会改到本模块自己那一份，序号会静默地不前进。
_EVENT_SEQ = 0


def _event_seq() -> int:
    """当前事件序号（起表时记下来，只有这之后的事件才算"被等对象的新动静"）。"""
    with _EVENT_LOCK:
        return int(_EVENT_SEQ)


def observe_event(kind: str, *, task_id: str = "", from_task_id: str = "",
                  to_task_id: str = "", role: str = "", content: str = "",
                  message_id: str = "") -> ObservedEvent:
    """记一条"被时钟观测到的事件"（发消息 / 收工提交 / 答复）。

    它做三件事：

    1. 把事件记进观测窗（`observed_events` 读）；
    2. 事件消账（业主 2026-10-27 第二条）：用这条事件带的对象键哈希查一次反查索引
       （`TimerBook.waiters_of`），把等它的那几条就地判成到点并交给 `_DUE_HANDLER`
       —— 不用等下一拍扫表。时延读数在 `event_close_reading()` 里（改前是一个 pump
       的间隔，改后是本进程量到的几毫秒）；
    3. 事件的摘要在到点那一刻被抄进那句话里（`_deliver_one` 的 `feedback`）。

    为什么在这里而不在会话/台账那一侧：时钟负责的是"挂机 — 唤醒 — 现场读数"，
    内容投递仍归 mailbox（业主 2026-10-25：「两条不许互相替代」）。这里只留"发生过
    一条什么事件、谁产生的、摘要是什么"，唤醒时把它抄进那句话里。

    消账的判据与全扫逐条相同（`_close_waiters_for_event` 里调的是同一个 `due_reason`），
    所以"事件先到"与"下一拍才扫到"给出来的 `triggered_by` / `woke_reason` /
    `due_message` 逐字一样 —— 这一处只改"什么时候判"，不改"判成什么"。
    """
    if kind not in EVENT_KINDS:
        raise ClockParamError(f"事件种类只认 {EVENT_KINDS}，收到 {kind!r}")
    global _EVENT_SEQ
    with _EVENT_LOCK:
        _EVENT_SEQ += 1
        seq = _EVENT_SEQ
        _EVENT_COUNTS[kind] = int(_EVENT_COUNTS.get(kind, 0)) + 1
        reading = now()
        event = ObservedEvent(
            kind=kind,
            target=str(task_id or from_task_id or ""),
            seq=seq,
            at=_iso(reading.wall) if reading.wall is not None else "",
            task_id=str(task_id or ""),
            from_task_id=str(from_task_id or ""),
            to_task_id=str(to_task_id or ""),
            role=str(role or ""),
            content=str(content or "")[:EVENT_EXCERPT],
            message_id=str(message_id or ""),
        )
        _EVENTS.append(event)
        if len(_EVENTS) > EVENT_BUFFER:
            del _EVENTS[: len(_EVENTS) - EVENT_BUFFER]
    # 事件先落进观测窗、再消账：消账调的是 `due_reason`，而它的 `_event_hits`
    # 要看得见这一条，否则判成 `target_closed` 而不是 `target_event` —— 那一格变了，
    # 到点消息里的 "它交的是…" 就没了（而那正是判据要比的正文）。
    # 消账放在锁外：`_event_hits` 自己也要拿这把锁。
    try:
        _close_waiters_for_event("observe_event", _event_target_keys(event), reading=reading)
    except Exception as exc:  # noqa: BLE001 - 消账是旁路，炸了不许把写路径带坏
        with _CLOSE_LOCK:
            _CLOSE["problems"] = (list(_CLOSE.get("problems") or ())
                                  + [f"observe_event 消账失败：{type(exc).__name__}: {exc}"])[-20:]
    return event


def observe_message(rec: Mapping[str, Any]) -> ObservedEvent | None:
    """从一条会话事件里认出"发消息 / 答复"，转成时钟事件。返回 `None` = 不关时钟的事。

    认法（三态归到三类里，不许漏）：

    - `kind != "agent_message"` => 不是消息，返回 `None`；
    - `progress` 为真 => 「只落消息、不记事件」，返回 `None`（D11 第③件：进度对账
      不许唤醒"等它"的计时器；消息本身已由 `send_message` 落在会话里，父照常读得到）；
    - 有 `reply_to` => `reply`（对某条消息的答复）；
    - 其余 => `message`。

    `target`（谁产生的）优先取 `from_task_id`（发信人那件活），其次取 `from`
    （角色名）—— 等的是任务号就按任务号对上，等的是角色就按角色对上。
    """
    if str(rec.get("kind") or "") != "agent_message":
        return None
    if rec.get("progress"):
        #: 进度上报（D11 第③件，2026-11-09）：`send_message(..., extra={"progress": True})`
        #: 标记的是"还在跑"的对账（每满 N 步的步数报告），不是"被等对象说了话"。
        #: 消息本身已经落进会话（`send_message` 先 append，本钩子只是旁路）⇒ 父下一步
        #: 照常从收件箱读到；这里只是「不」把它记成时钟事件 ⇒ 不参与 `_event_hits`、
        #: 也不触发 `target_event` 唤醒（否则父的等待计时器会被一条进度留言叫醒，
        #: 真机 33 条「时间到」里有 8 条就是这么来的）。
        return None
    body = str(rec.get("body") or "")
    subject = str(rec.get("subject") or "")
    content = f"{subject}：{body}" if subject else body
    kind = "reply" if str(rec.get("reply_to") or "") else "message"
    sender = str(rec.get("from_task_id") or "")
    recipient = str(rec.get("to") or "")
    event = observe_event(
        kind,
        task_id=sender,
        from_task_id=sender,
        to_task_id=recipient,
        role=str(rec.get("from") or ""),
        content=content,
        message_id=str(rec.get("msg_id") or ""),
    )
    # 投递这一侧再记一格（业主 2026-10-26：「等父也要真的能醒」）：`message` 认的是
    # "谁说的"，而"等父"要认的是"父给我投来了一条话" —— 父不交差（那是 handoff），
    # 它只会发消息；两档分开记，读的人（与判据）能看见投递这件事真的发生过。
    try:
        observe_event("delivery", task_id=sender, from_task_id=sender,
                      to_task_id=recipient, role=str(rec.get("from") or ""),
                      content=content, message_id=str(rec.get("msg_id") or ""))
    except ClockError:  # pragma: no cover - 受控词表刚加这一档，这里只做防御
        pass
    return event


def observe_work(rec: Mapping[str, Any]) -> dict[str, Any] | None:
    """从一条会话事件里认出"这一趟又产生了回合/模型调用"，记到挂机中的 waiter 上。

    业主 2026-10-25 的判据是"挂机区间内 `steps == 0` 且 `calls == 0`，而 `parked_sec > 0`"
    —— 没有这一格，"挂机"与"每 5 秒轮一次"在读数上分不开。返回受影响的 waiter 读数
    （`None` = 这条事件不是工作事件）。
    """
    if str(rec.get("kind") or "") not in WORK_EVENT_KINDS:
        return None
    task_id = str(rec.get("task_id") or "")
    role = str(rec.get("role") or "")
    touched: list[dict[str, Any]] = []
    with _EVENT_LOCK:
        for item in _PARKED.values():
            if item.state != "pending" or not item.is_park:
                continue
            if task_id and task_id in (item.task_id, str(item.task_id or "")):
                pass
            elif role and role == str(item.role or ""):
                pass
            else:
                continue
            item.parked_steps = int(item.parked_steps) + 1
            item.parked_calls = int(item.parked_calls) + 1
            touched.append({"timer_id": item.timer_id, "task_id": item.task_id,
                            "parked_steps": item.parked_steps,
                            "parked_calls": item.parked_calls})
    return {"kind": str(rec.get("kind") or ""), "touched": touched,
            "count": len(touched)}


#: 挂机中的 waiter（进程内视图；盘上的那一份在 `state.json` 里）。
#:
#: 为什么要有这个内存视图：`observe_work` 由会话写路径的旁路钩子调用，它必须能在
#: 不读盘、不拿 Store 的前提下把"这一趟又在跑了"记到对应的 waiter 上。
_PARKED: dict[str, Timer] = {}


def _register_parked(timer: Timer) -> None:
    if not timer.is_park:
        return
    with _EVENT_LOCK:
        _PARKED[timer.timer_id] = timer


def _unregister_parked(timer_id: str) -> None:
    with _EVENT_LOCK:
        _PARKED.pop(str(timer_id or ""), None)


def reset_parked() -> None:
    """清空挂机视图（判据之间的隔离点）。"""
    with _EVENT_LOCK:
        _PARKED.clear()


def observed_events(*, since_seq: int = 0, task_id: str = "",
                    role: str = "") -> dict[str, Any]:
    """读观测窗。`counts` 三档各多少（业主点名的 `observed_events` 读数）。"""
    with _EVENT_LOCK:
        counts = dict(_EVENT_COUNTS)
        events = [e for e in _EVENTS
                  if int(e.seq) > int(since_seq or 0)
                  and (not task_id or e.task_id == str(task_id)
                       or e.from_task_id == str(task_id))
                  and (not role or e.role == str(role))]
        total = sum(counts.values())
    return {"checked": True, "counts": counts, "total": total,
            "events": [e.row() for e in events], "count": len(events),
            "reason": ""}


def reset_observed_events() -> None:
    """清空观测窗（判据之间的隔离点）。"""
    global _EVENT_SEQ
    with _EVENT_LOCK:
        _EVENTS.clear()
        _EVENT_SEQ = 0
        for key in EVENT_KINDS:
            _EVENT_COUNTS[key] = 0


def _event_hits(timer: Timer) -> list[ObservedEvent]:
    """这一条等的东西在起表之后产生过哪些事件（认领唤醒的依据）。"""
    if not timer.wait_for:
        return []
    target = _parse_target_loose(timer.wait_for_resolved or timer.wait_for)
    if not target:
        return []
    kind, ref = target
    since = int(timer.event_seq or 0)
    with _EVENT_LOCK:
        events = list(_EVENTS)
    out: list[ObservedEvent] = []
    for event in events:
        if int(event.seq) <= since:
            continue
        if kind == "task":
            if ref in (event.task_id, event.from_task_id) or \
                    (timer.wait_for_resolved and ref == event.target):
                out.append(event)
        elif event.role == ref:
            out.append(event)
    return out


def _event_target_keys(event: "ObservedEvent") -> list[str]:
    """一条事件该去撞哪些"等待对象键"（写法与 `_target_key` 同一套，复用 `parse_wait_for`）。

    键集与 `_event_hits` 的认法逐条对齐，不多不少：

    - `task:<号>`：`task_id` / `from_task_id`（事件是谁产生的 —— 这两个就是
      `_event_hits` 拿来比的那两格）、以及 `target`（= 前者之一，留它是为了老行）；
    - `agent:<名>`：`role`（`_event_hits` 对 `agent` 那一档就是比 `role`）。

    刻意不放 `to_task_id`：那是收件人，不是产生者。把收件人也算进来会让"父给子发了
    一条话"去判"等父"的那条表 —— 与 `_event_hits` 的认法分家，那正是这一批不许发生的
    语义漂移。
    """
    keys: list[str] = []
    for tid in (event.task_id, event.from_task_id, event.target):
        text = str(tid or "")
        if not text:
            continue
        key = f"task:{text}"
        if key not in keys:
            keys.append(key)
    role = str(event.role or "")
    if role:
        key = f"agent:{role}"
        if key not in keys:
            keys.append(key)
    return keys


#: 每个产生点被叫到几次、其中消掉几条表（判据按它断言"表里每一行都真的走到过"）。
_CLOSE_STATS: dict[str, dict[str, int]] = {}

#: 最近一次消账的读数（时延、键、命中几条、消掉几条）。
_CLOSE: dict[str, Any] = {"count": 0, "latency_ms": None, "last": {},
                          "problems": []}

_CLOSE_LOCK = threading.Lock()


#: 递归保护：`_DUE_HANDLER` 自己可能又发出一个事件（它写 mailbox 行），那一层只记账。
_CLOSE_DEPTH: list[int] = [0]


def event_close_reading() -> dict[str, Any]:
    """消账的读数：改前"事件到达 -> 一条等它的表被判到点"是一个 pump 的间隔，
    改后是这一格里量到的几毫秒（本进程最近一次消账的时延）。

    返回 `{"checked", "count", "latency_ms", "last", "stats", "problems", "reason"}`。
    三态：一次都还没消过账 => `checked=False`（不是"时延 0"）。

    ## 它是读数，不是门；今天只有判据读它

    这一格的读者今天只有 `tests/test_the_clock_scales_with_the_book.py`（与
    `temp/_clock_digest.py` 的取证）。谁都不许拿它做闸 —— 不许因为 `latency_ms` 超过
    某个数就让 `observe_event` 抛、不许因为 `problems` 非空就停掉消账。消账炸了已经按
    旁路处理（`observe_event` 记 `problems` 并继续），这一格只是把"炸过"如实留着。

    待办（下一批，不在这一批的范围内）：M 的巡查（`conductor.patrol`）可以把它作为一格
    读出来（例如 `last["judged"]` 与 `latency_ms` 并进那一拍的四格，回答"上一次子代理
    交差之后，等它的那条表多久被判到"），但接线时只许读、不许加闸。
    """
    with _CLOSE_LOCK:
        stats = {k: dict(v) for k, v in _CLOSE_STATS.items()}
        count = int(_CLOSE.get("count") or 0)
        latency = _CLOSE.get("latency_ms")
        last = dict(_CLOSE.get("last") or {})
        problems = list(_CLOSE.get("problems") or ())
    return {"checked": latency is not None or count > 0,
            "count": count,
            "latency_ms": latency,
            "last": last,
            "stats": stats,
            "problems": problems,
            "reason": "" if (latency is not None or count > 0) else "本进程还没消过账"}


def reset_event_close() -> None:
    """清空消账读数（判据之间的隔离点）。"""
    with _CLOSE_LOCK:
        _CLOSE_STATS.clear()
        _CLOSE["count"] = 0
        _CLOSE["latency_ms"] = None
        _CLOSE["last"] = {}
        _CLOSE["problems"] = []
    _CLOSE_DEPTH[0] = 0


def _close_waiters_for_event(source: str, keys: Iterable[str], *,
                             reading: Reading | None = None) -> dict[str, Any]:
    """按"等待对象键"反查索引，把等它的那几条就地判到点（消账的唯一实现）。

    `source` 必须已经登记在 `EVENT_CLOSE_HOOKS` 里（未登记 => `ClockParamError`）：
    这条纪律是为了让"将来加一个收工路径"没法悄悄退回"等下一拍扫表"。

    ## 它做什么、不做什么

    做：对反查出来的每一条调 `timer.due_reason(reading, None)`（唯一判据），判到点就
    `bucket.mark_hot(...)`。于是"扫表"这件事消失了：下一次 `fire_due` 只按热表投那几条，
    成本 O(候选数)，与台账行数无关。

    不做：不在这里调 `_DUE_HANDLER`。

    ### 为什么不做当场投递（业主 2026-10-27 的裁定，逐字留档）

    当场投递会写 mailbox 行 + 唤醒标记，而 `agent_loop._wait_for_children` 的既有判据是
    "读到时钟唤醒就提前返场" ⇒ 每一次扇出都被第一件回来的子代理抢占，父代理多花一个
    模型回合。业主的口径是"以后开深度/扇出全力跑大课题"，所以"不抢占"必须保住。

    实测证据（这不是推测，是同一份夹具里当场跑出来的两档）：
    `tests/test_agent_loop.py::test_a_role_can_fan_out_a_batch_in_one_step` 在"当场投递"
    的版本下从 `{'count': 2, 'ok_count': 2}` 变成
    `{'count': 2, 'ok_count': 1, 'preempted': True}` —— 第二件活没在这一步里回来。

    这不是没做，是不做：扇出抢占的代价 > 下一拍投递的收益。 将来有人读到这里时，
    要看见的是"为什么不做"，而不是以为我们漏了；要改成当场投递，先让
    `_wait_for_children` 不再把"子代理落定写的时钟唤醒"当成本步的抢占信号。

    所以消账的收益落在两处，两处都是读数：
    1. 判的时延 ≈ 0（`event_close_reading()["latency_ms"]`，改前是一个 pump 的间隔）；
    2. 投递那一拍是 O(候选数)，不是 O(全表)（`cost_reading()["hot_count"]`）。

    判据与全扫逐条相同：`due_reason` 自己判事件那一档（`target_event`）与收口那一档
    （`target_closed`），于是"事件消账"与"下一拍扫表"给出的 `triggered_by` /
    `woke_reason` / `due_message` 逐字相同 —— 消账只改"什么时候判"，不改"判成什么"。

    返回 `{"checked", "source", "keys", "waiters", "judged", "latency_ms", "reason"}`；
    `judged` 是"判成到点、已进热表"的那几格（`timer_id` / `triggered_by` / `why`）。
    """
    if source not in EVENT_CLOSE_HOOKS:
        raise ClockParamError(
            f"消账的产生点 {source!r} 没有登记在 EVENT_CLOSE_HOOKS 里"
            f"（已登记：{tuple(EVENT_CLOSE_HOOKS)}）—— 加一个收工路径必须同时登记一行，"
            "否则那条路径会退回'等下一拍扫表'，而这件事在读数上是看不出来的")
    key_list: list[str] = []
    for key in keys:
        text = str(key or "")
        if text and text not in key_list:
            key_list.append(text)
    out: dict[str, Any] = {"checked": False, "source": source, "keys": list(key_list),
                           "waiters": 0, "judged": [], "latency_ms": None, "reason": ""}
    with _CLOSE_LOCK:
        stats = _CLOSE_STATS.setdefault(source, {"attempts": 0, "judged": 0})
        stats["attempts"] = int(stats.get("attempts") or 0) + 1
    if not key_list:
        out["checked"] = True
        out["reason"] = "这一条事件没有可查的对象键（没有 task/agent 归属）=> 不消账"
        return out
    if _CLOSE_DEPTH[0] > 0:
        out["checked"] = True
        out["reason"] = "已经在一趟消账里（递归保护）=> 这一条不再重复判"
        return out
    got = reading if reading is not None else now()
    if got.status == "unknown":
        out["reason"] = (f"时钟读不到（{got.reason or '两个来源都不可用'}）=> "
                         "判不了到点（那条表保持 pending，等下一次对账）")
        return out
    started = time.perf_counter()
    _CLOSE_DEPTH[0] += 1
    try:
        for root in list(_BOOKS):
            bucket = _BOOKS.get(root)
            if bucket is None or not bucket._index_ready:
                continue
            seen: set[str] = set()
            for key in key_list:
                for timer in bucket.waiters_of(key):
                    if timer.timer_id in seen:
                        continue
                    seen.add(timer.timer_id)
                    out["waiters"] += 1
                    verdict, why = timer.due_reason(got, None)
                    if not verdict:
                        continue
                    bucket.mark_hot(timer)
                    out["judged"].append({"timer_id": timer.timer_id,
                                          "triggered_by": verdict,
                                          "why": why})
    finally:
        _CLOSE_DEPTH[0] -= 1
    out["checked"] = True
    out["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 4)
    if not out["judged"]:
        out["reason"] = "查过了：这几个对象上没有到点的等待"
    with _CLOSE_LOCK:
        _CLOSE["count"] = int(_CLOSE.get("count") or 0) + len(out["judged"])
        _CLOSE["latency_ms"] = out["latency_ms"]
        _CLOSE["last"] = {
            "source": source,
            "keys": list(key_list),
            "waiters": int(out["waiters"]),
            "judged": [str(r.get("timer_id") or "") for r in out["judged"]],
            "triggered_by": [str(r.get("triggered_by") or "") for r in out["judged"]],
            "at": _iso(got.wall) if got.wall is not None else "",
            "latency_ms": out["latency_ms"],
        }
        st = _CLOSE_STATS.setdefault(source, {"attempts": 0, "judged": 0})
        st["judged"] = int(st.get("judged") or 0) + len(out["judged"])
    return out
