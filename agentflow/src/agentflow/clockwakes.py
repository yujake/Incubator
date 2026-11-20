# -*- coding: utf-8 -*-
"""唤醒标记与兜底计时器（lifeline）：到点之后"叫醒谁"的那一层。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十二刀。
两件事共用同一份"进程内活着的循环"读数：`record_wake` 落一条可读、可消费的唤醒标记
（`out/clock/wake.json`），`consume_wakes` 是消费端；而兜底计时器 `lifeline` 靠
`_LIVE_LOOPS` 判"这条环还在不在"，`_renew_lifeline` 在到点消耗之后立刻续一条。
`_DUE_HANDLER`（`clockfire.py`）在自己的投递路径里调 `_renew_lifeline` —— 所以本模块
必须坐在到点层之下。

## 装了什么

`wake_path` / `_load_wake_doc` / `record_wake` / `read_wakes` / `pending_wakes` /
`consume_wakes`；`lifeline_of` / `arm_lifeline` / `_new_lifeline_timer` /
`_renew_lifeline` / `_LIFELINE_WAKE_HANDLER` / `set_lifeline_wake_handler` /
`_LIVE_LOOPS` / `loop_started` / `loop_ended` / `loop_is_live` / `live_loops` /
`lifeline_suppressed` / `kill_lifeline`。

## 可变量与依赖

`_LIFELINE_WAKE_HANDLER` 的唯一写点（`set_lifeline_wake_handler`）与唯一读点
（`_renew_lifeline`）同处一份；`_LIVE_LOOPS` 是进程内清单，四个读口与两处写口也都在这里。
依赖方向单向：`board` / `book` 在 `clocktimer.py`，本模块在它之上；`clockfire.py` 反过来
import `_renew_lifeline`。纯搬移，逐名 AST dump 全等，`clock.py` 原样再导出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import json
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockStateError,
    LIFELINE_KIND,
    LIFELINE_REASON,
    LIFELINE_SUPPRESSED,
    SCHEMA,
    WAKE_REL,
    _iso,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _event_seq,
    _register_parked,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _atomic_json,
    is_lifeline,
    lifeline_key,
    now,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    Timer,
    book,
)

def wake_path(workspace: str | Path) -> Path:
    """唤醒标记的落盘路径（读侧与消费端都用它，不另拼一份）。"""
    return Path(workspace).resolve() / WAKE_REL


def _load_wake_doc(workspace: str | Path) -> tuple[dict[str, Any], str]:
    path = wake_path(workspace)
    empty = {"schema": SCHEMA, "next_seq": 1, "events": []}
    if not path.is_file():
        return empty, ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        return empty, f"唤醒标记读不成：{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
        return empty, "唤醒标记不是 {events: [...]} 形态"
    return doc, ""


def record_wake(workspace: str | Path, timer: Timer,
                mailbox_item_id: str = "") -> dict[str, Any]:
    """给收件人置一条唤醒标记（落盘）。返回那一条事件。

    它和 mailbox 项是两个独立落点：D-52 的投递还没修，所以"能立刻拿到一个回合"
    必须由这条标记单独保证。两件都做，任缺一件都不算投递成功（判据第 6 条）。
    """
    doc, error = _load_wake_doc(workspace)
    if error:
        raise ClockStateError(error)
    try:
        seq = max(1, int(doc.get("next_seq") or 1))
    except (TypeError, ValueError):
        seq = 1
    reading = now()
    event = {
        "wake_id": f"wk-{seq:06d}",
        "task_id": str(timer.task_id or ""),
        "role": str(timer.role or ""),
        "timer_id": str(timer.timer_id or ""),
        "kind": str(timer.kind or ""),
        "reason": str(timer.reason or ""),
        "purpose": str(timer.purpose or ""),
        "purpose_missing": bool(timer.purpose_missing),
        "message": str(timer.message or ""),
        "waited_sec": timer.waited_seconds(reading),
        "triggered_by": str(timer.triggered_by or ""),
        "wait_for": str(timer.wait_for or ""),
        "due_at": str(timer.due_at or ""),
        "fired_at": _iso(reading.wall) if reading.wall is not None else "",
        "mailbox_item_id": str(mailbox_item_id or ""),
        "state": "pending",
    }
    doc["schema"] = SCHEMA
    doc["next_seq"] = seq + 1
    doc["events"].append(event)
    try:
        _atomic_json(wake_path(workspace), doc)
    except OSError as exc:
        raise ClockStateError(f"唤醒标记写不成：{type(exc).__name__}: {exc}") from None
    return event


def read_wakes(workspace: str | Path) -> dict[str, Any]:
    """读全部唤醒标记（消费端与判据共用）。三态：读不成 => checked=False。"""
    doc, error = _load_wake_doc(workspace)
    if error:
        return {"checked": False, "events": [], "count": 0, "reason": error}
    events = [dict(e) for e in doc.get("events") or () if isinstance(e, Mapping)]
    return {"checked": True, "events": events, "count": len(events), "reason": ""}


def pending_wakes(workspace: str | Path, task_id: str | None = None) -> dict[str, Any]:
    """按收件人读"还没被消费"的唤醒标记。没有 task_id => 全部。"""
    got = read_wakes(workspace)
    if not got["checked"]:
        return {**got, "task_id": str(task_id or "")}
    events = got["events"]
    if task_id is not None:
        want = str(task_id or "")
        events = [e for e in events if str(e.get("task_id") or "") == want]
    return {"checked": True, "events": events, "count": len(events), "reason": "",
            "task_id": str(task_id or "")}


def consume_wakes(workspace: str | Path, task_id: str,
                  *, wake_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """消费（删除）某个收件人的唤醒标记，返回被消费的那些。

    为什么消费端要用它而不是自己删文件：删除与"返回被删的那几条"必须在同一个
    读-改-写里完成，否则"读到了"与"删掉了"之间断一次就丢一次唤醒。今天没有
    并发写者（单进程），但接口按"调用方只需要一次调用"来设计。
    """
    doc, error = _load_wake_doc(workspace)
    if error:
        return {"checked": False, "consumed": [], "count": 0, "reason": error,
                "task_id": str(task_id or "")}
    want_task = str(task_id or "")
    wanted_ids = {str(w) for w in (wake_ids or ())}
    kept: list[dict[str, Any]] = []
    consumed: list[dict[str, Any]] = []
    for event in doc.get("events") or ():
        if not isinstance(event, Mapping):
            continue
        hit = str(event.get("task_id") or "") == want_task
        if wanted_ids:
            hit = hit and str(event.get("wake_id") or "") in wanted_ids
        (consumed if hit else kept).append(dict(event))
    if consumed:
        doc["schema"] = SCHEMA
        doc["events"] = kept
        try:
            _atomic_json(wake_path(workspace), doc)
        except OSError as exc:
            return {"checked": False, "consumed": [], "count": 0,
                    "reason": f"唤醒标记写不成：{type(exc).__name__}: {exc}",
                    "task_id": want_task}
    return {"checked": True, "consumed": consumed, "count": len(consumed),
            "reason": "", "task_id": want_task}


def lifeline_of(workspace: str | Path, task_id: str) -> list[dict[str, Any]]:
    """这个台账号名下还挂着的兜底计时器（正常恰好一条）。"""
    want = str(task_id or "").strip()
    if not want:
        return []
    rows: list[dict[str, Any]] = []
    for timer in book(workspace).pending():
        if not is_lifeline(timer):
            continue
        if str(timer.task_id or "") != want:
            continue
        rows.append({"timer_id": str(timer.timer_id or ""), "task_id": want,
                     "role": str(timer.role or ""), "state": str(timer.state or ""),
                     "wait_for": str(timer.wait_for or "")})
    return rows


def arm_lifeline(workspace: str | Path, *, task_id: str, role: str = "",
                 reason: str = "") -> dict[str, Any]:
    """挂上兜底计时器；同一个台账号同时恰好一条（幂等）。

    三态纪律：挂不上不是"静默"，必须如实说没挂上（`armed=False` + `skipped`），
    让读数分得开"没有它"与"有它"。
    """
    want = str(task_id or "").strip()
    if not want:
        return {"armed": False, "skipped": "no_task_id", "task_id": "", "timer_id": "",
                "reason": "没有台账号 ⇒ 兜底计时器挂不上"}
    already = lifeline_of(workspace, want)
    if already:
        return {"armed": False, "skipped": "already", "task_id": want,
                "timer_id": already[0]["timer_id"],
                "reason": "这个台账号已经有一条兜底计时器了（不重复挂）"}
    if lifeline_suppressed(workspace, want):
        # 销过号的号不许再挂（业主 2026-10-29：已销号 = 彻底没有了）。
        return {"armed": False, "skipped": "suppressed", "task_id": want, "timer_id": "",
                "reason": "这个台账号已销号 ⇒ 兜底表永久抑制，不再挂"}
    timer = _new_lifeline_timer(workspace, task_id=want, role=str(role or ""),
                                reason=str(reason or LIFELINE_REASON))
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    _register_parked(timer)
    return {"armed": True, "skipped": "", "task_id": want,
            "timer_id": str(timer.timer_id or ""), "reason": ""}


def _new_lifeline_timer(workspace: str | Path, *, task_id: str, role: str,
                        reason: str) -> Timer:
    """组装一条兜底计时器（不含 ID）。

    刻意不走 `_new_timer`：它要求"等一段时间 / 等谁"二选一，且"等谁"要先探针解析出
    具名对象；兜底计时器两样都不是（它等的是"与我有关的任何东西"）。
    """
    reading = now()
    timer = Timer(timer_id="", kind=LIFELINE_KIND, reason=str(reason or LIFELINE_REASON),
                  to="self", task_id=str(task_id or ""), role=str(role or ""),
                  workspace=str(Path(workspace).resolve()),
                  created_at=(_iso(reading.wall) if reading.wall is not None else ""),
                  due_at="", wait_for=lifeline_key(task_id))
    timer.purpose_source = "given"
    timer.event_seq = _event_seq()
    return timer


def _renew_lifeline(timer: Timer) -> dict[str, Any]:
    """一条兜底计时器被打掉之后，立刻续一条新的（幂等：同一台账号恰好一条）。

    除了续，还要叫醒它：兜底表被打掉就是有与我有关的东西来了（业主 2026-10-29 第 1、2 条）。
    叫醒由运行期注入的钩子做（`set_lifeline_wake_handler`）—— 时钟不 import 编排层。
    失败不抛：续不上、叫不醒都要能被读数看见，而不是把一次投递搞崩。
    """
    if not is_lifeline(timer):
        return {"armed": False, "skipped": "not_lifeline", "woke": False}
    out: dict[str, Any] = {"armed": False, "skipped": "", "woke": False, "wake_reason": ""}
    try:
        out.update(arm_lifeline(timer.workspace, task_id=str(timer.task_id or ""),
                                role=str(timer.role or "")))
    except Exception as exc:  # noqa: BLE001 - 续不上不许带走这次投递
        out.update({"armed": False, "skipped": "error",
                    "reason": f"{type(exc).__name__}: {exc}"})
    handler = _LIFELINE_WAKE_HANDLER
    if loop_is_live(str(timer.task_id or "")):
        # 它自己的循环就在跑：那条消息会进它自己的收件箱，再叫一次就是复制一个自己
        #（2026-10-29 实测的挂死根因）。续照旧做了，上面那一步已经完成。
        out["wake_reason"] = ("它自己的循环在跑（进程内登记）⇒ 不另起一个同号循环；"
                              "那条消息会进它自己的收件箱")
        return out
    if handler is None:
        out["wake_reason"] = ("没有接叫醒钩子（set_lifeline_wake_handler 未接线）"
                              "：这次只是续上，没人被叫起来")
        return out
    try:
        got = handler(str(timer.task_id or ""))
    except Exception as exc:  # noqa: BLE001 - 叫不醒也要如实记
        out["wake_reason"] = f"叫醒失败（{type(exc).__name__}: {exc}）"
        return out
    out["woke"] = True
    out["wake_reason"] = str(got.get("reason") or "") if isinstance(got, Mapping) else ""
    return out


#: 兜底表被打掉时"把那个代理叫起来"的钩子（运行期注入；未接线时读数里写得出来）。
#:
#: 唤醒的边界（业主 2026-10-29 两句话，合起来才是完整口径）：
#:   · 不做自动唤醒、不做跨进程扫描：整趟停机之后再起一个进程，不许它自己把
#:     盘上所有还挂着兜底表的代理一股脑拉起来。理由是 M 那一侧的记忆：
#:     它还以为"全组停机了"，自动唤醒会让 M 感到非常意外。
#:   · 但"手上有活没结掉"的代理是需要唤醒的 —— 走两条被动路径：
#:     ① M 侧发指令（一条委托 / 一条消息）把它叫起来；
#:     ② 它接收到任何别的指令之后被动唤起。
#:   · 而且不是无脑全部重启（业主同日第三句）：M 要评估哪些活值得继续做，
#:     再按评估结果一条条发指令。一句话概括业主的裁定：「总之就是听上级指挥」——
#:     唤起由上级（M）指挥，不由框架自己决定。
#: 所以"随叫随到"的准确说法是：同一个进程还活着时随叫随到；跨进程要靠 M 发指令。
_LIFELINE_WAKE_HANDLER: Callable[[str], Any] | None = None


def set_lifeline_wake_handler(handler: Callable[[str], Any] | None):
    """接上/摘掉叫醒钩子（照 `set_due_handler` 的形状；参数是台账号，返回读数）。"""
    global _LIFELINE_WAKE_HANDLER
    _LIFELINE_WAKE_HANDLER = handler
    return handler


#: 进程内"这个台账号此刻有活着的循环"的登记（业主 2026-10-29 第 2 条的落地形态）。
#:
#: 为什么要有它：兜底表是在这一趟循环里被打掉的。这时再去 resume，就会另起一个同号
#: 循环 —— 两个自己互相喂事件，直到把进程挂死（实测两次超时）。判"它是不是在跑"不能
#: 读台账 status：起跑那一瞬那一行可能还没落、或还是 pending，闸门因此看不见它。
#: 进程内登记没有这个时序问题：循环开跑时登记、收工时注销。
_LIVE_LOOPS: set[str] = set()


def loop_started(task_id: str) -> str:
    """登记"这个台账号的循环起来了"（起跑处调一次）。"""
    tid = str(task_id or "").strip()
    if tid:
        _LIVE_LOOPS.add(tid)
    return tid


def loop_ended(task_id: str) -> str:
    """注销（收工处调一次；幂等）。"""
    tid = str(task_id or "").strip()
    _LIVE_LOOPS.discard(tid)
    return tid


def loop_is_live(task_id: str) -> bool:
    """这个台账号此刻有没有活着的循环（进程内读数）。"""
    return str(task_id or "").strip() in _LIVE_LOOPS


def live_loops() -> list[str]:
    """当前在跑的台账号（读数用，按字典序）。"""
    return sorted(_LIVE_LOOPS)


def lifeline_suppressed(workspace: str | Path, task_id: str) -> bool:
    """这个台账号的兜底表是不是被永久抑制了（销过号）。"""
    want = str(task_id or "").strip()
    if not want:
        return False
    for timer in book(workspace).all():
        if not is_lifeline(timer):
            continue
        if str(timer.task_id or "") != want:
            continue
        if str(timer.note or "") == LIFELINE_SUPPRESSED:
            return True
    return False


def kill_lifeline(workspace: str | Path, *, task_id: str, reason: str = "") -> dict[str, Any]:
    """永久撤掉兜底表并落抑制标记（同一次原子写）。

    这是销号那一步的时钟侧落点。顺序纪律：调用方在"台账还没动"之前先调它，
    于是只可能出现"叫不醒了、名字还没销"（可重试），不可能出现"已销号但仍会醒"（不可逆）。
    """
    want = str(task_id or "").strip()
    if not want:
        return {"checked": False, "killed": [], "suppressed": False,
                "reason": "没有台账号 ⇒ 撤不掉"}
    bucket = book(workspace)
    killed: list[str] = []
    for timer in list(bucket.pending()):
        if not is_lifeline(timer):
            continue
        if str(timer.task_id or "") != want:
            continue
        timer.state = "cancelled"
        timer.note = LIFELINE_SUPPRESSED
        if reason:
            timer.feedback = str(reason)[:200]
        bucket.sync_index(timer)
        killed.append(str(timer.timer_id or ""))
    if not killed:
        # 没有待发的那条也要留痕：抑制是"这个号永久不复用"事实的一部分。
        mark = _new_lifeline_timer(workspace, task_id=want, role="", reason=reason or LIFELINE_REASON)
        mark.timer_id = bucket.allocate("tm")
        mark.state = "cancelled"
        mark.note = LIFELINE_SUPPRESSED
        bucket.add(mark)
        killed.append(str(mark.timer_id or ""))
    try:
        bucket.save()
    except Exception as exc:  # noqa: BLE001 - 撤不掉必须让调用方看见
        return {"checked": False, "killed": [], "suppressed": False,
                "reason": f"落盘失败（{type(exc).__name__}: {exc}）"}
    return {"checked": True, "killed": killed, "suppressed": True, "reason": ""}
