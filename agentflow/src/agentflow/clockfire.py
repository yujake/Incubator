# -*- coding: utf-8 -*-
"""到点那一整层：`_DUE_HANDLER` / `fire_due` / 投递 / 周期补拍 / 成本读数 / 假时钟。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十三刀。
"到点了把活交出去"是一条不能拆开的链：`fire_due` 挑出到点的那些 → `_deliver_one`
在 `_FIRE_LOCK` 里认领 → `_deliver_one_locked` 拼到点消息、调 `_DUE_HANDLER`、落 fired、
清 `waiting_on`、续兜底表 → `_fire_periodics` 给周期性巡查补拍 → `PeriodicShot` 是那一拍。
`_DUE_HANDLER` 是进程级可变量：`set_due_handler` 唯一写，`_deliver_one_locked` 与
`_fire_periodics` 读 —— 三个点必须同处一份，否则 `from .clock import _DUE_HANDLER`
拿到的是快照（SPLIT-1 的第二刀就栽在这一条上）。

## 装了什么

`_DUE_HANDLER` / `set_due_handler` / `_FIRE_LOCK` / `_deliver_one` / `_deliver_one_locked` /
`fire_due` / `_remember_wait_state` / `_fire_periodics` / `PeriodicShot` /
`MAX_CATCHUP_FIRES` / `_probe_targets` / `due_timers` / `_select_due` / `waiters` /
`next_due`；成本读数 `_COST` / `_COST_LAST` / `COST_FIELDS` / `_cost_blank` / `_cost_note` /
`cost_reading` / `reset_costs`（`fire_due` 每一拍记一次成本，它们与到点同一拍不拆）；
以及 `FakeClock`（`advance` 顺带调一次 `fire_due`，判据的"拨表"就是它）。

## 依赖与可变量

本模块只向下 import：`clocktimer`（簿记 / 到点判定）、`clockpatrol`（到点正文两半）、
`clockwakes`（续兜底表）、`clockprobe`、`clockrun`、`clockbase`。可变量
`_DUE_HANDLER` / `_FIRE_LOCK` / `_COST` / `_COST_LAST` 的全部读写点都在本模块内。
`clock.py` 里只剩 `_wake_waiters` 还在按名字调 `fire_due`（它随停程序那一刀走），
再导出保证它照旧可用。纯搬移，逐名 AST dump 全等。
"""

from __future__ import annotations

from datetime import timedelta
import threading
import time
import uuid
from .clockbookindex import _target_key
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockParamError,
    ClockStateError,
    DueDeferred,
    _iso,
    _parse_iso,
    _reading,
    human_sec,
    parse_wait_for,
)
from .clockcost import (  # noqa: F401 — 这些名字由 clockcost 定义
    _cost_note,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _event_hits,
    _register_parked,
    _unregister_parked,
)
from .clockpatrol import (  # noqa: F401 — 这些名字由 clockpatrol 定义
    patrol_section,
    patrol_sop_text,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _BOOKS,
    _PROBE_CALLS,
    _resolve_root,
    due_message,
    is_lifeline,
    is_patrol_timer,
    now,
    purpose_of,
    waiting_on_text,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    Timer,
    book,
    target_state,
)
from .clockwakes import (  # noqa: F401 — 这些名字由 clockwakes 定义
    _renew_lifeline,
)

class FakeClock:
    """假时钟：判据专用。可以前进、可以只坏一个来源、可以整个读不到。

    `advance()` 在推进时间之后调一次 `fire_due()`：这是"到点后时钟自动动作"在
    判据里的形态。它不替调用方决定投递什么 —— 到点动作由工具层注册的
    `set_due_handler` 决定。
    """

    name = "fake"

    def __init__(self, *, wall: Any = "2026-01-01T00:00:00+00:00",
                 monotonic: float = 1000.0) -> None:
        self.token: str = uuid.uuid4().hex
        self._wall: datetime = _parse_iso(wall)
        self._monotonic: float = float(monotonic)
        self._mode: str = "ok"
        self._reason: str = ""

    def read(self) -> Reading:
        if self._mode == "unknown":
            return _reading(None, None, [self._reason or "假时钟读不到"])
        wall = self._wall if self._mode in ("ok", "wall_only") else None
        monotonic = self._monotonic if self._mode in ("ok", "mono_only") else None
        reasons = []
        if wall is None:
            reasons.append(self._reason or "假时钟的墙钟被关掉了")
        if monotonic is None:
            reasons.append(self._reason or "假时钟的单调计数被关掉了")
        return _reading(wall, monotonic, reasons)

    def set_mode(self, mode: str, reason: str = "") -> None:
        """改读数模式：`ok` / `unknown` / `wall_only` / `mono_only`。

        `wall_only` 与 `mono_only` 是 partial 的两个方向；`unknown` 是两个都坏。
        """
        if mode not in ("ok", "unknown", "wall_only", "mono_only"):
            raise ClockParamError(
                f"假时钟模式只认 ok / unknown / wall_only / mono_only，收到 {mode!r}")
        self._mode = mode
        self._reason = str(reason or "")

    def advance(self, seconds: float) -> Reading:
        """前进 `seconds` 秒（可小数），然后让到点的计时器动作。"""
        step = float(seconds)
        if step < 0:
            raise ClockParamError(f"假时钟只能前进，不能后退（收到 {seconds!r}）")
        self._wall = self._wall + timedelta(seconds=step)
        self._monotonic += step
        fire_due()
        return self.read()


#: 到点动作的注册点。工具层注册；没注册时到点的计时器保持 pending（DueDeferred）。
_DUE_HANDLER: Callable[["Timer"], Mapping[str, Any]] | None = None


def set_due_handler(handler: Callable[["Timer"], Mapping[str, Any]] | None):
    """注册到点动作，返回上一个。工具层用它在 import/装配期接上。

    到点动作的签名是 `handler(timer) -> dict`，返回值里请带 `mailbox_item_id`
    与 `wake_id`（`fire_due` 把它们原样记进计时器的 `note`/落盘字段，供审计）。
    """
    global _DUE_HANDLER
    previous = _DUE_HANDLER
    _DUE_HANDLER = handler
    return previous


def waiters(workspace: str | Path) -> dict[str, Any]:
    """挂机读数：谁挂在时钟上、挂了多久、挂机期间它跑了几步。

    业主点名的三档：`parked` / `woke` / `cancelled`；`parked` 仍算活跃，但必须与
    "正在跑"分开列（`active = running + parked`），且 `parked` 的不许被当成卡住。

    ## 兜底表不是"挂机等谁"

    兜底表 `wait_for="task:<自己>"`，所以 `Timer.is_park` 为真、会混进这份读数。
    但它不是"它在等的活"：业主 2026-10-29 第 3 条的口径是"它是框架的保活账、
    代理对它无感"（`conductor.agent_state` 的 docstring 逐字）。这一份读数给模型
    与页面看"我等谁/谁在等"，把保活列进去等于告诉它们"我在等我自己"。
    所以这里按 `is_lifeline` 剔掉 —— 与 `AgentLoop._park_reading` /
    `_wait_any_reading` 同一句口径（那两处早就剔了；2026-11-24 全量 #21 抓到的
    正是"只有这一份没剔"）。它仍然真的挂着：`clock.lifeline_of` / `state.json`
    里看得到（判据 `test_lifeline_arm_does_not_leak_into_waiters`）。
    """
    reading = now()
    bucket = book(workspace)
    rows: list[dict[str, Any]] = []
    for timer in bucket.all():
        if not timer.is_park:
            continue
        if is_lifeline(timer):
            continue
        if timer.state == "pending":
            # 进程重启后盘上的 waiter 不在内存视图里：读到它时顺手补登记，
            # 否则"它挂机期间又跑了几步"会被记成 0（读成"没在跑"）。
            _register_parked(timer)
        row = timer.row(reading)
        rows.append({k: row[k] for k in (
            "timer_id", "purpose", "purpose_missing", "wait_for", "wait_for_resolved",
            "waiting_on", "waiting_on_text",
            "wait_state", "state", "park_state", "parked_at", "parked_sec",
            "parked_steps", "parked_calls", "woke_reason", "feedback", "message")})
    parked = [r for r in rows if r["park_state"] == "parked"]
    return {
        "checked": True,
        "waiters": rows,
        "count": len(rows),
        "parked": len(parked),
        "woke": sum(1 for r in rows if r["park_state"] == "woke"),
        "cancelled": sum(1 for r in rows if r["park_state"] == "cancelled"),
        "parked_sec": round(sum(float(r["parked_sec"] or 0.0) for r in parked), 3),
        "parked_steps": sum(int(r["parked_steps"] or 0) for r in parked),
        "parked_calls": sum(int(r["parked_calls"] or 0) for r in parked),
        "reason": "",
    }


def due_timers(workspace: str | Path, *, reading: Reading | None = None) -> list[Timer]:
    """到期且还没被投递的计时器。读不到时钟 => 空表（不是"全部到点"）。

    它与 `fire_due` 走同一套判定（堆给出候选 + `due_reason` 判），但不投递、不落盘：
    它是"现在谁到点了"这一份事实的只读口。次序与改前的线性扫逐条相同
    （`(due_at, timer_id)`，见 `TimerBook._heap_due` 与 `_seq_of` 的赋值顺序）。
    """
    got = reading if reading is not None else now()
    root = _resolve_root(workspace)
    if got.status == "unknown":
        _cost_note(root, source="due_timers", checked=False,
                   reason=f"时钟读不到（{got.reason or '两个来源都不可用'}）=> 判不了 due",
                   scan_ms=None, probes=None, bucket=None, reading=got,
                   reconcile=None, early_exit=False)
        return []
    probes_before = _PROBE_CALLS[0]
    started = time.perf_counter()
    try:
        bucket = book(root)
        out = _select_due(bucket, got)
    except ClockStateError as exc:
        _cost_note(root, source="due_timers", checked=False, reason=str(exc),
                   scan_ms=None, probes=None, bucket=None, reading=got,
                   reconcile=None, early_exit=False)
        raise
    _cost_note(root, source="due_timers", checked=True, reason="",
               scan_ms=(time.perf_counter() - started) * 1000.0,
               probes=_PROBE_CALLS[0] - probes_before, bucket=bucket, reading=got,
               reconcile=0, early_exit=False)
    return out


def _select_due(bucket: TimerBook, reading: Reading) -> list[Timer]:
    """把这一拍到点的计时器按台账序取出来（只读的全扫口：`due_timers` 用它）。

    它不投递、不落盘、不记读数 —— 是"现在谁到点了"这一份事实的唯一只读实现。
    `fire_due` 的补偿对账那一支走同一个判据（`pending()` + `_probe_targets` +
    逐条 `due_reason`），差别只有"非到点的那几条顺手把 `wait_state` 记进盘"
    与"到点的交给 `_deliver_one`"这两件事 —— 那两件是投递侧的事，不属于这个只读口。

    `due_reason` 仍然是唯一判据：候选进了未必真到点（例如同一刻但被等对象说还在跑），
    这一点与改前一样。返回值按台账序排好（不是堆序），于是"谁先被投递"与改前逐条相同。
    """
    pending = bucket.pending()
    targets = _probe_targets(pending)
    out: list[Timer] = []
    for timer in pending:
        reason, _why = timer.due_reason(reading, targets.get(_target_key(timer)))
        if reason:
            out.append(timer)
    return out


def next_due(workspace: str | Path) -> dict[str, Any]:
    """堆顶那一条的到点时刻 —— O(1) peek，不扫表、不问 target_state。

    返回 `{"checked", "due_epoch", "due_in_sec", "next_wake_sec", "timer_id",
    "pending_count", "reason"}`：

    - `due_epoch` 是墙钟纪元（`None` = 堆里没有到点）；
    - `due_in_sec` 是"还有多少秒"（已经过了按 0 读）；
    - `next_wake_sec` 是 `TimerBook.next_wake_epoch` 的口径（堆顶 / 对账 / 周期性巡查取早）；
    - `checked=False` 加 `reason` = 没查成（簿记读不成 / 时钟读不到）—— 这一档下
      `due_epoch` 与 `due_in_sec` 都是 `None`，不许读成"没有到点"。
    """
    out: dict[str, Any] = {"checked": False, "reason": "", "due_epoch": None,
                           "due_in_sec": None, "next_wake_sec": None,
                           "timer_id": "", "pending_count": None}
    root = _resolve_root(workspace)
    try:
        bucket = book(root)
    except ClockStateError as exc:
        out["reason"] = str(exc)
        return out
    bucket._ensure_index()
    if bucket.load_error:
        out["reason"] = bucket.load_error
        return out
    reading = now()
    now_epoch = reading.wall.timestamp() if reading.wall is not None else None
    if now_epoch is None:
        out["reason"] = (f"墙钟读不到（{reading.reason or '只知道单调计数'}）=> "
                         "判不了还有多少秒")
        return out
    due = bucket.next_due_epoch()
    wake = bucket.next_wake_epoch()
    out["checked"] = True
    out["pending_count"] = bucket.pending_count()
    out["due_epoch"] = due
    out["due_in_sec"] = None if due is None else round(max(0.0, due - now_epoch), 6)
    out["next_wake_sec"] = None if wake is None else round(max(0.0, wake - now_epoch), 6)
    # 堆顶那一条是谁（读数用；惰性删除已经把它判过一遍，这里只补编号）
    for _due, _seq, tid in list(bucket._heap):
        timer = bucket._timers.get(tid)
        if timer is not None and timer.state == "pending" and tid in bucket._in_heap:
            if due is not None and abs(_due - due) < 1e-9:
                out["timer_id"] = tid
                break
    return out


def _probe_targets(timers: Iterable[Timer]) -> dict[str, tuple[str, str, str]]:
    """一次把这一批计时器等的东西各问一遍（同一个对象只问一次）。

    兜底计时器不问：它等的键是它自己的台账号，而"我那一行已经是 done"正是
    "收工后仍续"的常态 —— 去问就必然被判成 `target_closed`，30 秒对账就把保活表打掉。
    """
    out: dict[str, tuple[str, str, str]] = {}
    for timer in timers:
        if is_lifeline(timer):
            continue
        key = _target_key(timer)
        if not key or key in out:
            continue
        try:
            kind, ref = parse_wait_for(timer.wait_for_resolved or timer.wait_for)
        except ClockError:
            out[key] = ("unjudgeable", key, "wait_for 的写法解析不了（台账里的旧行？）")
            continue
        out[key] = target_state(timer.workspace, kind, ref)
    return out


#: 到点投递的"谁的谁投"闸（REHEARSAL-FLAKE，2026-11-26）。
#:
#: ## 为什么要有这一条（一次真红，不是推测）
#:
#: `fire_due(workspace)` 按工作区扫全部待发计时器、不区分收件人；每个代理的循环都在推
#: 它，于是"父在等子、子代理的步进点替父把到点项推响"被当成设计优点（`agent_loop._pump_clock`
#: 的文档逐字写着）。但投递是一笔写：它落一条 `expects="ack"` 的 notice 板项 + 一条唤醒标
#: 记。收件人那一拍如果已经走过了 `_take_wakes`（`_deliver_mailbox` 里"先推、再读唤醒"），
#: 这笔投递就落在它这一拍之外 —— 而它随口就是 `final`：板项停在 `queued`，收件人的号已收工，
#: 再也没有任何一拍会渲染它（"渲染即 ack"是唯一收口口），父的 `retire_child` / `final`
#: 于是被"名下还有 1 条未消的板项"永久拒（`max_final_refused=3` ⇒ rc=5）。
#:
#: 全量 #43 的现场（`temp/rehearsalflake/REPORT.md`）：F 的等子表 `tm-000009` 被 B 的
#: `_pump_clock` 投成 `t-000014`（`data/tasks.json` 里 `item_state="queued"`、`instance=""`），
#: F 的下一拍已经发过 `final` ⇒ M 连拒 3 拍 ⇒ `final_refused`。同一棵树的全量 #44 里，
#: 同一条表由 F 自己的步进投递、同一拍被 `_take_wakes` 消费掉（`item_state="done"`），
#: 于是 rc=0。两趟的差别只有"谁先推响了这一拍"。
#:
#: ## 判据（只认这一档，别的一律照旧）
#:
#: 1. 兜底表（`is_lifeline`）不在此列：它不投件、不记唤醒，谁推都一样（`_renew_lifeline` 那半）；
#: 2. 只认 `wait_for` 解析后是 `task:<号>` 的那一档（派活时 `arm_child_waiter` 起的那条）——
#:    它等的对象是另一个代理的号，天然有"收件人"；时间类 / 闹钟 / 程序句柄没有这个问题；
#: 3. 进程里读不到"正在推时钟的是谁"（判据直接调 `fire_due` / `autonomy` 的轮边界）⇒ 照旧投，
#:    三态不许折成"都不投"；
#: 4. 读到的推钟者就是收件人 ⇒ 投（这正是"它自己那一拍"）。
#:
#: 被挡下的一律 `DueDeferred`：计时器保持 pending，由收件人自己的下一次 `_pump_clock` 投
#: —— 那一拍紧跟着 `_take_wakes`，投与消费在同一段里，板项不会停在 `queued`。
def _deferred_to_its_owner(timer: Timer) -> str:
    """这条到点项该不该留给收件人自己投？返回理由（空串 = 现在就投）。"""
    if is_lifeline(timer):
        return ""
    wait = str(timer.wait_for_resolved or timer.wait_for or "")
    if not wait.startswith("task:"):
        return ""
    recipient = str(timer.task_id or "")
    if not recipient:
        return ""
    try:
        # 惰性 import：conductor 在导入期会拉 clock，模块头写死会成环。
        from .conductor import current_task_id
        caller = str(current_task_id() or "")
    except Exception:  # noqa: BLE001 —— 读不到推钟者不是"没有推钟者"
        return ""
    if not caller or caller == recipient:
        return ""
    return (f"这条计时器等的是 {recipient} 的活；投递留给它自己那一拍"
            f"（{caller} 只是替它推了时钟）")


def _deliver_one(bucket: TimerBook, timer: Timer, reason: str, why: str,
                 reading: Reading, report: dict[str, Any]) -> bool:
    """把一条到点的计时器交给到点动作（投递的唯一实现）。

    `fire_due` 的全扫路径与事件消账（`_close_waiters_for_event`）都调它，于是"到点那一下做什么"
    只有一份代码：拼 `due_message`、调 `_DUE_HANDLER`、落 fired、清 `waiting_on`、
    写 `report["fired"]` 那一格。两处各写一份的话，事件那一侧一定会先漂。

    返回 True = 这一次真的落成 fired；False = 没投递（没有到点动作 / 被推迟 / 抛了），
    计时器保持 pending 由下一次判定再试（三态与改前逐字相同）。

    `why` 是 `due_reason` 的第二格（"为什么还没到"或"它收口了"）；投递这一段不读它，
    收着是为了让签名与 `due_reason` 的返回形状对得上，读的人不必回去猜。
    """
    # ---- 谁的谁投：等子代理的那一条只由收件人自己那一拍投（见 `_deferred_to_its_owner`）
    # 放在锁外：它是纯读（读一个 ContextVar 与计时器的两格），不必占着 `_FIRE_LOCK` 等
    # store 事务。返回 False 的处置与"没有到点动作"同一条：保持 pending，下一拍再判。
    deferred = _deferred_to_its_owner(timer)
    if deferred:
        report["deferred"].append({"timer_id": timer.timer_id, "reason": deferred})
        return False
    # ---- D-07：整段串行（读 pending → 调 handler → 标 fired → save）
    # 为什么在函数入口就锁：`_deliver_one` 的两处调用方（全扫路径与事件消账）都会调它，
    # 把锁放在这里就等于"无论谁把它叫起来，同一条计时器只有一个投递者"。
    # 锁是可重入场景安全的（本函数内部不再次调用自己），代价是一次 store 事务的时长。
    with _FIRE_LOCK:
        # 认领：拿到锁之后再看一眼状态 —— 前一个持锁者可能已经把它投递掉了。
        if str(getattr(timer, "state", "")) != "pending":
            return False
        return _deliver_one_locked(bucket, timer, reason, why, reading, report)


def _deliver_one_locked(bucket: TimerBook, timer: Timer, reason: str, why: str,
                        reading: Reading, report: dict[str, Any]) -> bool:
    """`_deliver_one` 的持锁主体（真正的投递）。由 `_deliver_one` 在 `_FIRE_LOCK` 里调。"""
    if _DUE_HANDLER is None:
        report["deferred"].append({
            "timer_id": timer.timer_id,
            "reason": "没有注册到点动作（set_due_handler 还没接上）",
        })
        return False
    timer.triggered_by = reason
    timer.woke_reason = timer.woke_reason_of(reason)
    events = _event_hits(timer) if timer.wait_for else []
    feedback = events[-1].content if events else ""
    label = ""
    if events:
        label = "它交的是" if events[-1].kind == "submit" else "它说的是"
    timer.feedback = feedback
    # 轮查那一档（业主 2026-10-27 傍晚）：到点那一下的正文是 SOP 四步，不是
    # "时间到了"。`patrol_sop_text` 与 `patrol_section` 都按名字调（模块级），
    # 于是反真空判据能把其中任何一个换成空串、当场看正文少掉哪一半。
    patrol = is_patrol_timer(timer)
    timer.message = due_message(
        # 到点这句念的目的走 `purpose_of`（唯一取值口）—— 与盘上那一行
        # `purpose` 是同一个来源，于是"内存里念的"与"从 state.json 读回来的"
        # 结构上不会分家（真机那次的错位就是两处各取一套）。
        purpose=purpose_of(timer), waited_sec=timer.waited_seconds(reading),
        created_at=timer.created_at,
        fired_at=_iso(reading.wall) if reading.wall is not None else "",
        feedback=feedback, feedback_label=label,
        waited_target=timer.wait_for, woke_reason=timer.woke_reason,
        patrol_sop=(patrol_sop_text() if patrol else ""),
        # 异常清单不另写第二份：轮查与周期性巡查读同一个 `patrol_section`。
        patrol_section=(patrol_section(timer.workspace, task_id=timer.task_id)
                        if patrol else ""))
    try:
        receipt = _DUE_HANDLER(timer)
    except DueDeferred as exc:
        # 到点了，但今天做不了：保持 pending，下一次再试。
        timer.triggered_by = ""
        timer.woke_reason = ""
        timer.message = ""
        timer.feedback = ""
        report["deferred"].append({"timer_id": timer.timer_id,
                                   "reason": str(exc)})
        return False
    except Exception as exc:  # noqa: BLE001 - 一条坏掉不带走别的计时器
        timer.triggered_by = ""
        timer.woke_reason = ""
        timer.message = ""
        timer.feedback = ""
        report["errors"].append({"timer_id": timer.timer_id,
                                 "error": f"{type(exc).__name__}: {exc}"})
        return False
    got = dict(receipt or {})
    timer.state = "fired"
    timer.fired_at = _iso(reading.wall) if reading.wall is not None else ""
    timer.woke_at = timer.fired_at
    _unregister_parked(timer.timer_id)
    # 醒了就不再"在等谁"：`waiting_on` 清空（业主 2026-10-26 第 ②/③ 条）。
    # 为什么要清而不是留着："还在等 A1"与"等 A1 等到了"必须分得开 —— 留着它，
    # 一条已经醒了三条的表在读数上仍然挂着，父代理那边的销号闸也永远有话拦；
    # 而"等过谁"这件事已经由 `wait_for` / `wait_for_resolved` / `message` 三格留档。
    woke_from = dict(timer.waiting_on or {})
    timer.waiting_on = {}
    timer.mailbox_item_id = str(got.get("mailbox_item_id") or "")
    timer.wake_id = str(got.get("wake_id") or "")
    timer.note = str(got.get("note") or "")
    # 索引的第三个同步点：它转 fired 了，不该再出现在反查索引与堆顶里。
    bucket.sync_index(timer)
    # 兜底计时器：被打掉就立刻续一条（业主 2026-10-29 第 2 条「它一直会续」）。
    # 落点必须在这里 —— 交差之后循环就结束了（`_park_gate` 的 handoff 支 ⇒ break），
    # 只有时钟的消耗路径能覆盖"收工之后仍续"这一态。
    _renew_lifeline(timer)
    try:
        bucket.save()
    except ClockStateError as exc:
        report["errors"].append({"timer_id": timer.timer_id, "error": str(exc)})
        return False
    report["fired"].append({
        "timer_id": timer.timer_id,
        "kind": timer.kind,
        "task_id": timer.task_id,
        "triggered_by": timer.triggered_by,
        "woke_reason": timer.woke_reason,
        "wait_for": timer.wait_for,
        # 醒的那一句里带上"刚被清掉的那一格"：读的人看得出它等的是谁，
        # 而盘上 `waiting_on` 已经是空表（"还在等"与"等到了"分得开）。
        "waiting_on": dict(timer.waiting_on or {}),
        "woke_from": woke_from,
        "woke_from_text": waiting_on_text(woke_from),
        "purpose": timer.purpose,
        "purpose_missing": timer.purpose_missing,
        "waited_sec": timer.waited_seconds(reading),
        "feedback": timer.feedback,
        "message": timer.message,
        "mailbox_item_id": timer.mailbox_item_id,
        "wake_id": timer.wake_id,
    })
    return True


#: 到点消费的串行闸（D-07，真机 2026-10-28 实测）。
#:
#: 为什么必须有它：`_deliver_one` 的顺序是「先调 `_DUE_HANDLER`（它会开一条 mailbox
#: 板项 = 一笔 store 事务），之后才 `state = "fired"` 并 `save()`」。中间那一整段
#: 没有锁，于是两个线程同时 pump 时钟时都会看见 pending、都投递一次 ——
#: 真机上的形态是两条 notice 的 `input_key` 完全相同（`clock:tm-000088`）、相隔 1 秒，
#: 5 轮轮查里复现 2 轮。这把锁把「读 pending → 调 handler → 标 fired → save」圈成一段。
#: 它是进程内的：跨进程那一半由投递的幂等键（`clock:<timer_id>`）兜底，见
#: `Conductor.open_item` 的同键复用。
_FIRE_LOCK = threading.Lock()


def fire_due(workspace: str | Path | None = None) -> dict[str, Any]:
    """把到点的计时器与周期性巡查交给注册的到点动作；计时器成功的落成 fired。

    三态：`checked=False` 表示这一次没查成（时钟读不到 / 簿记读不成），
    调用方不许把它读成"没有到点的计时器"。

    周期性巡查不在这个函数里"到点即消耗"：它每响一次就把 `next_at` 前移一拍，
    同一拍里最多补 `MAX_CATCHUP_FIRES` 次（假时钟一次前进一小时而周期是 20 分钟时，
    三次报醒都要发出去，但不许因为时钟被拨得很远就无限补）。

    ## 每一拍走哪条路（业主 2026-10-27 的施工单第 ④ 条：每拍早退）

    - 早退（`TimerBook.can_early_exit`）：`now < min(堆顶, 下次对账, 下一次周期性巡查)`
      且时钟/簿记都读得成、单调计数走动过 ⇒ 立刻返回"查过了、没有到点的"：
      不扫表（`pending()` 那一次整表排序）、不问 `target_state`（一次台账读）、
      不重建任何东西。真机上绝大多数拍就是这一档（一局几千条计时器、几十个子代理，
      而绝大多数拍什么都没到点）。早退与"真扫一遍"给出的到点集合逐条相同的钉子：
      `tests/test_the_clock_scales_with_the_book.py` 的
      `test_a_the_heap_order_matches_the_linear_scan`（堆 == 线性扫）与
      `test_f_the_quiet_pump_costs_a_constant`（安静拍不扫表、不问 target_state）；
    - 热表（事件消账的产物）：`_close_waiters_for_event` 已经判成到点的那几条，
      这一拍只投它们（O(候选数)）；
    - 堆路径：堆顶有到点，只判堆给的候选（O(候选数 log N)）；
    - 全扫（对账）：`pending()` + `_probe_targets` + 逐条 `due_reason`，
      与改前逐字相同。它在三个时刻发生：第一拍 / `RECONCILE_EVERY_SEC` 到点 /
      时钟没走动（`needs_full_scan`）。

    三态一条不少：时钟读不到 / 簿记读不成 => `checked=False` 加理由；
    早退只在两个来源都读到、而且这一拍确实"什么都没到"时才成立。
    """
    reading = now()
    report: dict[str, Any] = {"checked": True, "fired": [], "deferred": [],
                              "errors": [], "periodic_fired": [], "reason": ""}
    if reading.status == "unknown":
        report["checked"] = False
        report["reason"] = f"时钟读不到（{reading.reason or '两个来源都不可用'}）=> 判不了 due"
        if workspace is not None:
            _cost_note(_resolve_root(workspace), source="fire_due", checked=False,
                       reason=report["reason"], scan_ms=None, probes=None,
                       bucket=None, reading=reading, reconcile=None, early_exit=False)
        return report
    roots = [_resolve_root(workspace)] if workspace is not None else list(_BOOKS)
    for root in roots:
        started = time.perf_counter()
        probes_before = _PROBE_CALLS[0]
        try:
            bucket = book(root)
        except ClockStateError as exc:
            report["checked"] = False
            report["reason"] = (report["reason"] + "；" if report["reason"] else "") + str(exc)
            _cost_note(root, source="fire_due", checked=False, reason=str(exc),
                       scan_ms=None, probes=None, bucket=None, reading=reading,
                       reconcile=None, early_exit=False)
            continue
        full, why_full = bucket.needs_full_scan(reading)
        if not full:
            # 热表：事件消账已经判成到点的那几条 —— 只投它们，O(候选数)，不扫全表。
            hot = bucket.pop_hot()
            if hot:
                for timer in hot:
                    reason, detail = timer.due_reason(reading, None)
                    if not reason:
                        continue
                    if not _deliver_one(bucket, timer, reason, detail, reading, report):
                        # 投递被推迟/抛了：它还是到点的，下一拍再投（不许静默丢掉）。
                        bucket.mark_hot(timer)
                report["periodic_fired"].extend(
                    _fire_periodics(bucket, reading, report))
                _cost_note(root, source="fire_due", checked=True, reason="",
                           scan_ms=(time.perf_counter() - started) * 1000.0,
                           probes=_PROBE_CALLS[0] - probes_before, bucket=bucket,
                           reading=reading, reconcile=0, early_exit=False,
                           hot=len(hot))
                continue
            early, why = bucket.can_early_exit(reading)
            if early:
                _cost_note(root, source="fire_due", checked=True, reason="",
                           scan_ms=(time.perf_counter() - started) * 1000.0,
                           probes=_PROBE_CALLS[0] - probes_before, bucket=bucket,
                           reading=reading, reconcile=0, early_exit=True)
                continue
            # 堆顶有到点：只判堆给的候选（O(k log N)），不扫全表。
            for timer in bucket.pop_due(reading):
                reason, detail = timer.due_reason(reading, None)
                if not reason:
                    continue
                if not _deliver_one(bucket, timer, reason, detail, reading, report):
                    # 没投成（被"谁的谁投"挡下 / 到点动作推迟 / 抛了）：堆条目已经被
                    # `pop_due` 摘走，必须记进热表，否则它要等下一轮全表对账才再被看见
                    # —— 而收件人自己那一拍可能就在那之前发生（REHEARSAL-FLAKE）。
                    bucket.mark_hot(timer)
            report["periodic_fired"].extend(
                _fire_periodics(bucket, reading, report))
            _cost_note(root, source="fire_due", checked=True, reason="",
                       scan_ms=(time.perf_counter() - started) * 1000.0,
                       probes=_PROBE_CALLS[0] - probes_before, bucket=bucket,
                       reading=reading, reconcile=0, early_exit=False)
            continue
        # 全表对账（第一拍 / 对账到点 / 时钟没走动 / 读不全）：与改前逐字相同。
        pending = bucket.pending()
        targets = _probe_targets(pending)
        for timer in pending:
            key = _target_key(timer)
            reason, detail = timer.due_reason(reading, targets.get(key))
            if not reason:
                _remember_wait_state(bucket, timer, targets.get(key), detail)
                continue
            _deliver_one(bucket, timer, reason, detail, reading, report)
        report["periodic_fired"].extend(
            _fire_periodics(bucket, reading, report))
        # 对账已经把每一条都判过一遍 => 热表清空（它的意义是"判过、还没投"）。
        bucket.clear_hot()
        bucket.mark_reconciled(reading)
        _cost_note(root, source="fire_due", checked=True, reason="",
                   scan_ms=(time.perf_counter() - started) * 1000.0,
                   probes=_PROBE_CALLS[0] - probes_before, bucket=bucket,
                   reading=reading, reconcile=1, early_exit=False)
    return report


#: 一次推进里，同一条周期性巡查最多补几拍（时钟被拨远时的上界，不是周期本身的上界）。
MAX_CATCHUP_FIRES: int = 1000

def _remember_wait_state(bucket: TimerBook, timer: Timer,
                         target: tuple[str, str, str] | None,
                         why: str) -> None:
    """把"还在等谁/判不了"的读数记进这一条（只在变了的时候落一次盘）。"""
    if not timer.wait_for or target is None:
        return
    state = target[0]
    if timer.wait_state == state and timer.note == why:
        return
    timer.wait_state = state
    timer.note = why
    try:
        bucket.save()
    except ClockStateError:
        # 记不下来不该让到点判定失败：读数会在下一次判定里再试。
        pass


def _fire_periodics(bucket: TimerBook, reading: Reading,
                    report: dict[str, Any]) -> list[dict[str, Any]]:
    """让到期的那几拍报醒。返回这一趟的读数（进 `fire_due` 的 `periodic_fired`）。

    三态与一次性那条同一族：没有到点动作时保持 running（不假装报醒了），
    被等对象收口 / `until_sec` 到 => 停，并把原因写进 `stopped_reason`。
    """
    out: list[dict[str, Any]] = []
    for periodic in bucket.running_periodics():
        if periodic.wait_for:
            try:
                kind, ref = parse_wait_for(periodic.wait_for_resolved or periodic.wait_for)
            except ClockError:
                periodic.wait_state = "unjudgeable"
                continue
            state, _resolved, why = target_state(periodic.workspace, kind, ref)
            periodic.wait_state = state
            if state == "closed":
                periodic.state = "stopped"
                periodic.stopped_reason = f"被等对象收口：{periodic.wait_for_resolved or periodic.wait_for}（{why}）"
                periodic.stopped_at = _iso(reading.wall) if reading.wall is not None else ""
                bucket.save()
                out.append({"periodic_id": periodic.periodic_id, "fires": periodic.fires,
                            "action": "stopped", "stopped_reason": periodic.stopped_reason})
                continue
        elapsed = periodic.elapsed_sec(reading)
        if periodic.until_sec is not None and elapsed is not None \
                and elapsed >= float(periodic.until_sec):
            periodic.state = "until_reached"
            periodic.stopped_reason = (
                f"until_sec 到了：{human_sec(periodic.until_sec)} 的上限已用完"
                f"（已跑 {human_sec(elapsed)}，共响 {periodic.fires} 次）")
            periodic.stopped_at = _iso(reading.wall) if reading.wall is not None else ""
            bucket.save()
            out.append({"periodic_id": periodic.periodic_id, "fires": periodic.fires,
                        "action": "until_reached", "stopped_reason": periodic.stopped_reason})
            continue
        fired_this_round = 0
        while fired_this_round < MAX_CATCHUP_FIRES:
            nxt = periodic.next_datetime()
            if nxt is None or reading.wall is None or reading.wall < nxt:
                break
            if _DUE_HANDLER is None:
                report["deferred"].append({
                    "periodic_id": periodic.periodic_id,
                    "reason": "没有注册到点动作（set_due_handler 还没接上）",
                })
                break
            periodic.fires += 1
            periodic.last_fired_at = _iso(nxt)
            timer = PeriodicShot(periodic, shot_at=nxt, reading=reading).as_timer()
            try:
                receipt = _DUE_HANDLER(timer)
            except DueDeferred as exc:
                periodic.fires -= 1
                report["deferred"].append({"periodic_id": periodic.periodic_id,
                                           "reason": str(exc)})
                break
            except Exception as exc:  # noqa: BLE001 - 一拍坏掉不带走整条巡查
                periodic.fires -= 1
                report["errors"].append({"periodic_id": periodic.periodic_id,
                                         "error": f"{type(exc).__name__}: {exc}"})
                break
            got = dict(receipt or {})
            timer.state = "fired"
            timer.fired_at = _iso(nxt)
            timer.mailbox_item_id = str(got.get("mailbox_item_id") or "")
            timer.wake_id = str(got.get("wake_id") or "")
            timer.note = str(got.get("note") or "")
            periodic.next_at = _iso(nxt + timedelta(seconds=periodic.every_sec))
            if periodic.next_mono is not None:
                periodic.next_mono = periodic.next_mono + periodic.every_sec
            fired_this_round += 1
            out.append({
                "periodic_id": periodic.periodic_id,
                "fires": periodic.fires,
                "at": _iso(nxt),
                "purpose": periodic.purpose,
                "purpose_missing": periodic.purpose_missing,
                "message": timer.message,
                "mailbox_item_id": timer.mailbox_item_id,
                "wake_id": timer.wake_id,
            })
        if fired_this_round:
            bucket.save()
    return out


class PeriodicShot:
    """把"周期性巡查的某一拍"装成一条 `Timer`，好让它走同一个到点动作。

    为什么要转换而不是让到点动作认两种类型：到点动作（`_deliver_due`）只认一条
    `Timer`（它拿 `task_id`/`role`/`reason`/`timer_id` 去落板项与唤醒标记）。
    宁可在这里做一次显式转换，也不在两处各写一份投递逻辑 —— 那两份一定会漂。
    """

    def __init__(self, periodic: Periodic, *, shot_at: datetime,
                 reading: Reading) -> None:
        self.periodic = periodic
        self.shot_at = shot_at
        self.reading = reading

    def as_timer(self) -> Timer:
        per = self.periodic
        return Timer(
            timer_id=per.periodic_id,
            kind="periodic",
            reason=per.purpose,
            to=per.to,
            task_id=per.task_id,
            role=per.role,
            workspace=per.workspace,
            created_at=per.created_at,
            due_at=_iso(self.shot_at),
            due_epoch=self.shot_at.timestamp(),
            due_mono=per.next_mono,
            clock_token=per.clock_token,
            state="pending",
            wait_for=per.wait_for,
            wait_for_resolved=per.wait_for_resolved,
            wait_state=per.wait_state,
            message=due_message(purpose=purpose_of(per), waited_sec=None,
                                created_at=None, fired_at=None,
                                every_sec=per.every_sec, fires=per.fires,
                                # 业主 2026-10-26：巡查的报醒要带当拍现算的异常清单。
                                # 在这里算而不是在 `Periodic` 上算：这一拍是"现场"，
                                # 而 `Periodic` 是那条巡查的账（它的 row 只回显上一句）。
                                patrol_section=patrol_section(per.workspace,
                                                              task_id=per.task_id)),
        )
