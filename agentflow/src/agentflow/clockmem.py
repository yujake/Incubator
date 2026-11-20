# -*- coding: utf-8 -*-
"""计时器/闹钟/周期巡查的申请面：起表、补目的、取消、读清单。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第七刀。
这一层是"申请形状"的落点：`start_timer` / `start_alarm` / `start_periodic` 三档都经
`_new_timer` 一处建表（目的缺失的追问、被等对象的解析、编号分配都在那一处），
`set_purpose` 补的是同一条而不是新建一条，`timers` / `periodics` / `timers_missing_purpose`
是它们的读侧。整层一起搬，申请的写口与读口才不会分家。

## 装了什么

`_new_timer`（唯一建表点）/ `_waiter_handle_hint`（等谁那一格的提示句）/
`start_timer` / `start_alarm` / `start_periodic` / `stop_periodic` / `periodics` /
`set_purpose` / `timers_missing_purpose` / `cancel_timer` / `timers`。

## 依赖方向

只在 `clocktimer` / `clockprobe` / `clockrun` / `clockbase` 之上：簿记与到点判定都往下取，
本模块不 import 程序层、巡查层、到点层。可变量：没有（`_PROBE_CALLS` 在 `clockrun.py`）。
纯搬移，逐名 AST dump 全等，`clock.py` 原样再导出。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from .clockbookindex import Periodic
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockParamError,
    ClockUnreadable,
    ClockWaiterNotResolvable,
    PURPOSE_FROM_TARGET,
    PURPOSE_PROMPT,
    _iso,
    _parse_iso,
    parse_wait_for,
    waiter_refusal,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _event_seq,
    _register_parked,
)
from .clockprobe import (  # noqa: F401 — 这些名字由 clockprobe 定义
    _judge_target,
    _probe_read,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    current,
    is_lifeline,
    now,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    Timer,
    book,
)

def _waiter_handle_hint(workspace: str | Path) -> str:
    """拒信的后半句：这个工作区现在有哪些程序句柄可以等（没有就说"一条都没有"）。

    为什么要列出来：拒信是模型重写那一次的唯一依据。只说"句柄不对"它还是猜不出来；
    列出 `tm-…（lean，pending）` 它就能直接照抄一个。
    三态：簿记读不成 => 空串（不编一份清单）。
    """
    try:
        rows = [t for t in book(workspace).all() if str(getattr(t, "kind", "")) == "program"]
    except ClockError:
        return ""
    if not rows:
        return ("\n（这个工作区现在一条程序计时器都没有：先 clock.start_program(...) "
                "拿到句柄，再拿它当 wait_for）")
    shown = "、".join(f"{t.timer_id}（{t.program or '没记名字'}，{t.state}）" for t in rows[-5:])
    return f"\n这个工作区现有的程序句柄：{shown}"


def _new_timer(workspace: str | Path, *, kind: str, reason: str, to: str,
               task_id: str, role: str, after_sec: float | None = None,
               at: Any = None, wait_for: str = "",
               max_wait_sec: float | None = None) -> Timer:
    """组装一条待发计时器（不含 ID），并算出 due。

    申请形状（业主 2026-10-25）：等待时间 或 等待谁 + 目的。目的缺了照样受理
    （业主同日第二句：不报错，只让它追加目的）；时间与对象两个都不给、或两个都给
    => 受控拒绝并说清只能选一个。

    目的自动填（业主 2026-10-27 第二条裁定）：等谁那一条没给目的时，用"等谁"读口
    返回的 `task_text`（名册/台账里那一行的 task 原文）填，截断到
    `PURPOSE_FROM_TARGET` 字，读数标 `purpose_source="target_task"`；显式给了就是
    `given`；两边都拿不到还是 `unavailable`（`purpose_missing` 照旧为真，追问不变）。
    """
    body = str(reason or "").strip()
    purpose_source = "given" if body else "unavailable"
    target = str(wait_for or "").strip()
    cap: float | None = None
    if max_wait_sec is not None:
        cap = float(max_wait_sec)
        if cap <= 0:
            raise ClockParamError(f"max_wait_sec 必须是正数，收到 {max_wait_sec!r}")
        if cap > 10 * 366 * 24 * 3600:
            raise ClockParamError("max_wait_sec 超过十年：这不是等待上限，是许愿")
    reading = now()
    if reading.status == "unknown" or reading.wall is None:
        raise ClockUnreadable(
            f"时钟读不到（{reading.reason or '两个来源都不可用'}）=> 到点判不了，"
            "这一条不排（不许折成 0）")
    wait_kind, wait_ref, resolved, wait_state = "", "", "", ""
    waiting_on: dict[str, Any] = {}
    if kind == "timer":
        if after_sec is not None and target:
            raise ClockParamError(
                "after_sec 与 wait_for 只能选一个：等时间给 after_sec（多久之后），"
                "等谁给 wait_for（名册名 / 绝对编号 / program:<程序句柄>）；"
                "两个都给就不知道按哪一个判到了，这一条不排")
        if after_sec is None and not target:
            raise ClockParamError(
                "必须给 after_sec（等多久）或 wait_for（等谁）之一 —— "
                "计时类任务的申请形状是「等待时间（或等待谁）+ 目的」，"
                "例如 M 的巡视写 after_sec=1200 + reason=周期性巡查")
    if target:
        wait_kind, wait_ref = parse_wait_for(target)
        if wait_kind == "program":
            # 等程序：句柄必须是本工作区簿记里一条真的程序计时器（业主 2026-10-26：
            # 「等哪条程序」也是"点名"的一种，散文在这里同样要拒）。
            handle = book(workspace).get(str(wait_ref))
            if handle is None or str(getattr(handle, "kind", "")) != "program":
                raise ClockWaiterNotResolvable(
                    waiter_refusal(target, why=(f"{wait_ref} 不是本工作区簿记里的程序计时器"))
                    + _waiter_handle_hint(workspace))
            resolved = f"program:{handle.timer_id}"
            wait_state = ("open" if str(handle.state) == "pending" else "closed")
            waiting_on = {"kind": "program",
                          "name": str(handle.program or handle.timer_id),
                          "program_id": str(handle.timer_id),
                          "timer_id": str(handle.timer_id)}
            if not body:
                from_program = " ".join(str(handle.purpose or "").split())
                if from_program:
                    # 被等的那条程序自己写了目的 ⇒ 抄它（比程序名摘要更贴切）。
                    body = from_program[:PURPOSE_FROM_TARGET]
                    purpose_source = "program"
        else:
            probe = _probe_read(workspace, wait_kind, wait_ref)
            wait_state, resolved, why = _judge_target(probe, wait_kind, wait_ref)
            if probe.get("checked") and not probe.get("found"):
                # 查过了、没有这一行 ⇒ 受控拒绝（业主 2026-10-26：等谁必须指名道姓）。
                # 查不成（`checked=False`）不在这里拒：那不是"不存在"，是三态里的 unknown，
                # 这一条照样受理，`wait_state="unjudgeable"` 如实写着。
                raise ClockWaiterNotResolvable(
                    waiter_refusal(target, why=str(probe.get("why") or "查过了、没有这一行")))
            task_ref = ""
            if str(resolved or "").startswith("task:"):
                task_ref = str(resolved)[5:]
            elif wait_kind == "task":
                task_ref = str(wait_ref)
            name_ref = str(wait_ref) if wait_kind == "agent" else str(probe.get("name") or "")
            waiting_on = {"kind": "roster", "name": name_ref, "task_id": task_ref,
                          "resolved": str(resolved or "")}
            if not body:
                from_target = " ".join(str(probe.get("task_text") or "").split())
                if from_target:
                    # 业主 2026-10-27：等子代理的目的自动用名册/台账里那一行 task 填。
                    body = from_target[:PURPOSE_FROM_TARGET]
                    purpose_source = "target_task"
    if kind == "timer":
        if after_sec is not None:
            step = float(after_sec)
            if step <= 0:
                raise ClockParamError(f"after_sec 必须是正数，收到 {after_sec!r}")
            if step > 10 * 366 * 24 * 3600:
                raise ClockParamError("after_sec 超过十年：这不是计时器，是许愿")
            due = reading.wall + timedelta(seconds=step)
            due_mono = (reading.monotonic + step
                        if reading.monotonic is not None else None)
        else:
            # 等谁的那一条没有钟点：`due_at` 留空（不是假的 1970，也不是"已到点"），
            # 到点与否由被等对象收口（或 max_wait_sec 那道闸）决定。
            due = None
            due_mono = None
    elif kind == "alarm":
        if at is None:
            raise ClockParamError("闹钟必须给 at")
        due = _parse_iso(at)
        if due <= reading.wall:
            raise ClockParamError(
                f"at 已经过去（{_iso(due)} < 现在 {_iso(reading.wall)}）=> 不排这一条")
        due_mono = (reading.monotonic + (due - reading.wall).total_seconds()
                    if reading.monotonic is not None else None)
    else:  # pragma: no cover - 受控词表已经在 Timer 里判过
        raise ClockParamError(f"未知计时器种类：{kind!r}")
    return Timer(
        timer_id="",
        kind=kind,
        reason=body,
        to=str(to or "self"),
        task_id=str(task_id or ""),
        role=str(role or ""),
        workspace=str(Path(workspace).resolve()),
        created_at=_iso(reading.wall),
        due_at=_iso(due) if due is not None else "",
        due_epoch=due.timestamp() if due is not None else None,
        due_mono=due_mono,
        clock_token=str(getattr(current(), "token", "") or ""),
        state="pending",
        wait_for=target,
        wait_for_resolved=(resolved if target else ""),
        waiting_on=waiting_on,
        max_wait_sec=cap,
        wait_state=wait_state,
        event_seq=(_event_seq() if target else 0),
        parked_at=(_iso(reading.wall) if target else ""),
        purpose_source=purpose_source,
        after_sec=(float(after_sec) if after_sec is not None else None),
    )


def start_timer(workspace: str | Path, *, reason: str = "",
                after_sec: float | None = None, wait_for: str = "",
                max_wait_sec: float | None = None, to: str = "self",
                task_id: str = "", role: str = "") -> Timer:
    """起一个一次性计时器：等一段时间（`after_sec`）或等谁收口（`wait_for`），二选一。

    `wait_for` 必须指名道姓（业主 2026-10-26）：名册上的谁（名册名 / 绝对编号）或
    某条程序（`clock.start_program(...)` 的句柄）。解析不到 ⇒ `ClockWaiterNotResolvable`
    （码 `waiter_not_resolvable`，拒信逐字给两条正路），不是"起一条永远不醒的表"。
    """
    timer = _new_timer(workspace, kind="timer", reason=reason, to=to,
                       task_id=task_id, role=role, after_sec=after_sec,
                       wait_for=wait_for, max_wait_sec=max_wait_sec)
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    _register_parked(timer)
    return timer


def start_alarm(workspace: str | Path, *, at: Any, reason: str = "",
                wait_for: str = "", max_wait_sec: float | None = None,
                to: str = "self", task_id: str = "", role: str = "") -> Timer:
    """定一个到绝对时刻的闹钟（一次性）。`wait_for` 可选：到点或等到谁，先到者报醒。"""
    timer = _new_timer(workspace, kind="alarm", reason=reason, to=to,
                       task_id=task_id, role=role, at=at,
                       wait_for=wait_for, max_wait_sec=max_wait_sec)
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    _register_parked(timer)
    return timer


def start_periodic(workspace: str | Path, *, every_sec: float, purpose: str = "",
                   until_sec: float | None = None, wait_for: str = "",
                   to: str = "self", task_id: str = "",
                   role: str = "") -> Periodic:
    """起一条周期性巡查（M 的巡视：`every_sec=1200` + `purpose="周期性巡查"`）。

    三样参数各有它的判据：

    - `every_sec`：每一拍隔多久（正数，十年封顶 —— 与 `after_sec` 同一条闸）；
    - `purpose`：目的。缺了照样受理（业主 2026-10-25：「不报错，只是让它追加目的」），
      读数带 `purpose_missing=true`，到点消息里写"（目的未填）"并追问；
    - `until_sec`：整条巡查最多跑多久（到点即收，`stopped_reason` 写清楚是这一档收的）；
    - `wait_for`：等谁收口。它一收口就停巡查（`stopped_reason` 点名是谁）。
    """
    step = float(every_sec)
    if step <= 0:
        raise ClockParamError(f"every_sec 必须是正数，收到 {every_sec!r}")
    if step > 10 * 366 * 24 * 3600:
        raise ClockParamError("every_sec 超过十年：这不是周期，是许愿")
    until: float | None = None
    if until_sec is not None:
        until = float(until_sec)
        if until <= 0:
            raise ClockParamError(f"until_sec 必须是正数，收到 {until_sec!r}")
    target = str(wait_for or "").strip()
    resolved, wait_state = "", ""
    if target:
        wait_kind, wait_ref = parse_wait_for(target)
        if wait_kind == "program":
            # 周期性巡查等的是"谁收口 ⇒ 停巡查"；程序那一条的收口已经在计时器账上，
            # 让它当巡查的停止条件会把两档混成一个。明确拒，并指路（等程序用 timer_start）。
            raise ClockParamError(
                f"周期性巡查不能等程序：{target} —— 等程序请用 clock.timer_start"
                "（wait_for=\"program:<句柄>\"，程序退出时那一条会报醒）；"
                "周期性巡查的 wait_for 只等名册上的谁（名册名 / 绝对编号）")
        probe = _probe_read(workspace, wait_kind, wait_ref)
        wait_state, resolved, why = _judge_target(probe, wait_kind, wait_ref)
        if probe.get("checked") and not probe.get("found"):
            raise ClockWaiterNotResolvable(
                waiter_refusal(target, why=str(probe.get("why") or "查过了、没有这一行")))
    reading = now()
    if reading.status == "unknown" or reading.wall is None:
        raise ClockUnreadable(
            f"时钟读不到（{reading.reason or '两个来源都不可用'}）=> 下一拍算不出来，"
            "这一条不排（不许折成 0）")
    due = reading.wall + timedelta(seconds=step)
    bucket = book(workspace)
    periodic = Periodic(
        periodic_id=bucket.allocate("pd"),
        every_sec=step,
        purpose=str(purpose or "").strip(),
        to=str(to or "self"),
        task_id=str(task_id or ""),
        role=str(role or ""),
        workspace=str(Path(workspace).resolve()),
        created_at=_iso(reading.wall),
        next_at=_iso(due),
        until_sec=until,
        wait_for=target,
        wait_for_resolved=resolved,
        wait_state=wait_state,
        next_mono=(reading.monotonic + step
                   if reading.monotonic is not None else None),
        clock_token=str(getattr(current(), "token", "") or ""),
    )
    bucket.add_periodic(periodic)
    return periodic


def stop_periodic(workspace: str | Path, periodic_id: str,
                  reason: str = "") -> tuple[Periodic | None, str]:
    """停一条周期性巡查。返回 `(条目或 None, 结果)`；`already_stopped` 不是"又停了一次"。"""
    return book(workspace).stop_periodic(periodic_id, reason=reason)


def periodics(workspace: str | Path) -> list[Periodic]:
    """这个工作区的全部周期性巡查（含已停的，按下一拍排序）。"""
    return book(workspace).all_periodics()


def set_purpose(workspace: str | Path, entry_id: str,
                purpose: str, *, source: str = "given") -> tuple[Any, str]:
    """给一条已受理的等待补上目的（同一个编号，不是新建一条）。

    `source` 缺省 `given`（有人显式写的一句）。派活那一处的兜底支传
    `source="target_task"`：那一句来自被等对象那件活的 task 原文，不是人给的目的
    （见 `TimerBook.set_purpose`）。
    """
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "补的目的还是空的 —— 补目的就是为了让到点那条报醒里有话可念，"
            "别拿空串去填它")
    return book(workspace).set_purpose(entry_id, body, source=source)


def timers_missing_purpose(workspace: str | Path, *,
                           for_task_id: str = "") -> list[dict[str, Any]]:
    """还没写目的的待发条目（读数用：谁的报醒里会没有目的）。

    每行带 `id` / `kind` / `task_id` / `to` / `role` / `state` / `prompt`：

    - `for_task_id` 非空时只留"归这个台账号的"那几条（`task_id` 或 `to` 等于它）——
      每步提示词那一处（`agent_loop._prompt`）必须按它筛，否则每个代理都会被别人的
      缺目的刷屏，而"刷屏"与"没人管"在读数上一样糟；
    - `prompt` 就是 `PURPOSE_PROMPT`（唯一一份追问句，工具读数 / 到点消息 /
      每步提示词三处读的是同一个常量）。
    """
    want = str(for_task_id or "").strip()
    rows: list[dict[str, Any]] = []
    bucket = book(workspace)
    for timer in bucket.pending():
        if not timer.purpose_missing:
            continue
        if want and want not in (str(timer.task_id or ""), str(timer.to or "")):
            continue
        rows.append({"id": timer.timer_id, "kind": timer.kind,
                     "task_id": str(timer.task_id or ""), "to": str(timer.to or ""),
                     "role": str(timer.role or ""), "state": str(timer.state or ""),
                     "prompt": PURPOSE_PROMPT})
    for periodic in bucket.running_periodics():
        if not periodic.purpose_missing:
            continue
        if want and want not in (str(periodic.task_id or ""), str(periodic.to or "")):
            continue
        rows.append({"id": periodic.periodic_id, "kind": "periodic",
                     "task_id": str(periodic.task_id or ""), "to": str(periodic.to or ""),
                     "role": str(periodic.role or ""), "state": str(periodic.state or ""),
                     "prompt": PURPOSE_PROMPT})
    return rows


def cancel_timer(workspace: str | Path, timer_id: str) -> tuple[Timer | None, str]:
    """取消一条计时器。返回 `(计时器或 None, 落成的状态或 not_found)`。"""
    return book(workspace).cancel(timer_id)


def timers(workspace: str | Path) -> list[Timer]:
    """这个工作区的全部计时器（含已到点与已取消，按 due 排序）。

    兜底计时器（`lifeline`）不在这里：它是框架的保活账，代理对它无感
    （业主 2026-10-29 第 2 条）。要看它请用 `lifeline_of(workspace, task_id)`。
    这条过滤是"对模型不可见"的落点之一 —— 模型查"我手上还有哪些表"读的就是本函数。
    """
    return [t for t in book(workspace).all() if not is_lifeline(t)]
