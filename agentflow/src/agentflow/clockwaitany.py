# -*- coding: utf-8 -*-
"""`wait_any` 与交差账：等任意计时器返回的意图账 + 交接（handoff）的读写。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十刀。
业主 2026-10-27 第三条裁定：「可启动计时器等待任意计时器返回」。它不是一个计时器：
计时器是"等某个具体的东西"，而这一格是"我手上没事了，谁先回来都行，回来叫我"。
所以它单独落一份（`out/clock/wait_any.json`）、按台账号读，醒没醒只能由"有没有到点 /
事件"现算 —— 写一个布尔值就会与事实漂开。交差账（`out/clock/handoff.json`）是同一层
的另一格：父要能读到"子交回了什么"，而这件事必须与时钟事件分得开（消息 ≠ 交差）。

## 装了什么

`WAIT_ANY_REL` / `wait_any_path` / `_load_wait_any` / `request_wait_any` / `read_wait_any` /
`_fired_after` / `wait_any_reading` / `cancel_wait_any`；`HANDOFF_REL` / `HANDOFF_SUBJECT` /
`handoff_path` / `_load_handoffs` / `record_handoff` / `mark_handoff_seen` / `read_handoffs` /
`reset_handoffs`。

## 依赖与可变量

两者都只读 `book`（`clocktimer.py`）与落盘原语（`clockrun._atomic_json` / `clockbase`），
没有模块级可变量；`request_wait_any` 的前置判据（名下现存计时器数 >= 1）就在建表那一处。
纯搬移，逐名 AST dump 全等，`clock.py` 原样再导出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import json
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockNoTimersToWait,
    ClockParamError,
    ClockStateError,
    SCHEMA,
    _iso,
    _parse_iso,
    no_timers_refusal,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _CLOSE,
    _CLOSE_LOCK,
    _close_waiters_for_event,
    _event_seq,
    observe_event,
    observed_events,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _atomic_json,
    now,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    book,
)

#: "等待任意计时器返回"的意图账（业主 2026-10-27 第三条裁定）。
#:
#: 它不是一个计时器：计时器是"等某个具体的东西"，而这一格是"我手上没事了，谁先回来
#: 都行，回来叫我"。所以它单独落一份、按台账号读，状态由 `wait_any_reading` 现算
#: （不落盘"醒没醒"：醒了没有只能由"有没有到点/事件"回答，写一个布尔值就会与事实漂开）。
WAIT_ANY_REL: Path = Path("out") / "clock" / "wait_any.json"


def wait_any_path(workspace: str | Path) -> Path:
    """等待意图账的落盘路径。"""
    return Path(workspace).resolve() / WAIT_ANY_REL


def _load_wait_any(workspace: str | Path) -> tuple[dict[str, Any], str]:
    path = wait_any_path(workspace)
    empty: dict[str, Any] = {"schema": SCHEMA, "next_seq": 1, "rows": []}
    if not path.is_file():
        return empty, ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        return empty, f"等待意图账读不成：{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list):
        return empty, "等待意图账不是 {rows: [...]} 形态"
    return doc, ""


def request_wait_any(workspace: str | Path, *, task_id: str, role: str = "",
                     purpose: str = "") -> dict[str, Any]:
    """记一条"等待任意计时器返回"（业主 2026-10-27：「可启动计时器等待任意计时器返回」）。

    返回那一条读数。同一个台账号只留最新的一条（再要一次就是"继续等"，不叠账）。

    ## 前置判据：现存计时器数 >= 1（业主 2026-10-26）

        「当然他可以起计时器叫"等任意计时器返回"，这个需要存在的计时器数大于等于1」

    一条都没有 ⇒ 受控拒绝（码 `no_timers_to_wait`，拒信由 `no_timers_refusal()` 拼：
    要么先起一条表，要么按交差收工）。为什么拒而不是"受理并记 requested=false"：
    两种结局并存会让读侧又要分第三档，而"无事可做 + 无计时器 = 交差"是业主已经拍过
    的既有口径 —— 那一档不该再从 wait_any 这条路进来。

    "名下"的判据与 `wait_any_reading` 逐字相同（`task_id == 我` 或 `to == 我`）：
    两处各写一套，就会出现"受理时算有、读数时算没有"的分家。
    程序计时器常常 `task_id=""`（框架自己起的），那种表不算谁的 —— 等它要按
    `wait_for="program:<句柄>"` 点名（见 `parse_wait_for`）。
    """
    tid = str(task_id or "").strip()
    if not tid:
        raise ClockParamError("等待任意计时器返回要一个台账号：不知道该让谁挂机")
    try:
        bucket = book(workspace)
        live = [t for t in bucket.all()
                if str(t.state) == "pending"
                and tid in (str(t.task_id or ""), str(t.to or ""))]
        live += [p for p in bucket.all_periodics()
                 if str(p.state) == "running"
                 and tid in (str(p.task_id or ""), str(p.to or ""))]
    except ClockError:
        # 簿记读不成是"没查成"，不是"没有计时器"：不许把它折成受控拒绝。
        raise
    if not live:
        raise ClockNoTimersToWait(no_timers_refusal(role=role))
    doc, error = _load_wait_any(workspace)
    if error:
        raise ClockStateError(error)
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    try:
        seq = max(1, int(doc.get("next_seq") or 1))
    except (TypeError, ValueError):
        seq = 1
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    rows = [r for r in rows if str(r.get("task_id") or "") != tid]
    row = {"wait_id": f"wa-{seq:06d}", "task_id": tid, "role": str(role or ""),
           "purpose": str(purpose or "").strip(), "at": stamp,
           # 起意那一刻的观测窗事件序号：读数拿它当基线，只数这之后的事件。
           # 2026-10-29 真因：这一格原先没有，读数于是把基线写死 0（`seq_mark = 0`），
           # 而观测窗是进程全局的 —— 长跑里前面几百个用例的事件全都算"起意之后回来了"
           # （同台账号 + 假时钟把旧的真实时间比成"更新"），于是新起意的等待当场就被判成
           # "该回模型"，挂机永远不成立。真机：31 条。
           "at_seq": _event_seq(),
           "workspace": str(Path(workspace).resolve())}
    rows.append(row)
    doc.update({"schema": SCHEMA, "next_seq": seq + 1, "rows": rows})
    try:
        _atomic_json(wait_any_path(workspace), doc)
    except OSError as exc:
        raise ClockStateError(f"等待意图账写不成：{type(exc).__name__}: {exc}") from None
    return row


def read_wait_any(workspace: str | Path) -> dict[str, Any]:
    """读全部"等待任意计时器返回"的意图（三态：读不成 => `checked=False`）。"""
    doc, error = _load_wait_any(workspace)
    if error:
        return {"checked": False, "rows": [], "count": 0, "reason": error}
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    return {"checked": True, "rows": rows, "count": len(rows), "reason": ""}


def _fired_after(timer: Timer, since: str) -> bool:
    """这条计时器是不是在 `since` 之后收口的（时间读不到 => 按存在性保守判）。"""
    if timer.state != "fired":
        return False
    if not since or not timer.fired_at:
        return True
    try:
        return _parse_iso(timer.fired_at) >= _parse_iso(since)
    except ClockError:
        return True


def wait_any_reading(workspace: str | Path, task_id: str) -> dict[str, Any]:
    """这个代理此刻的"等待任意计时器返回"读数。

    `{"checked", "requested", "waiting", "wait_id", "purpose", "pending": [...],
    "woke": [...], "reason"}`：
    - `requested=True` ⇒ 它显式要求过"等待任意计时器返回"（意图在账上），
      且还没有任何东西回来；
    - `waiting=True` ⇒ `requested` 而且是"确实还有计时器没回来"（这才是"挂机"那一档）；
    - `requested` 而 `pending` 为空 ⇒ 没有可等的东西（无事可做 + 无计时器 ⇒ 交差）；
    - `woke` 非空 ⇒ 起意之后有计时器回来了（或它自己收到了事件）——
      这些就是"醒"的那一条证据，循环读它决定回不回模型。

    三态：任一份簿记读不成 => `checked=False`，此时循环不许把"没查成"读成"可以交差"。
    """
    tid = str(task_id or "").strip()
    out: dict[str, Any] = {"checked": False, "requested": False, "waiting": False,
                           "wait_id": "", "purpose": "", "pending": [], "woke": [],
                           "reason": ""}
    if not tid:
        out["reason"] = "没有台账号 => 这一格读不到（不是「没有在等」）"
        return out
    doc, error = _load_wait_any(workspace)
    if error:
        out["reason"] = error
        return out
    row = next((dict(r) for r in (doc.get("rows") or ())
                if isinstance(r, Mapping) and str(r.get("task_id") or "") == tid), None)
    if row is None:
        out.update(checked=True, reason="它没有要求过等待任意计时器返回")
        return out
    out.update(wait_id=str(row.get("wait_id") or ""),
               purpose=str(row.get("purpose") or ""),
               checked=True)
    since = str(row.get("at") or "")
    try:
        timers = [t for t in book(workspace).all()
                  if str(t.task_id or "") == tid or str(t.to or "") == tid]
        periodics = [p for p in book(workspace).all_periodics()
                     if str(p.task_id or "") == tid or str(p.to or "") == tid]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"计时器簿记读不成：{type(exc).__name__}: {exc}"
        return out
    pending = [t.timer_id for t in timers if t.state == "pending"]
    pending += [p.periodic_id for p in periodics if p.state == "running"]
    woke = [{"id": t.timer_id, "kind": t.kind,
             "outcome": t.outcome, "woke_reason": t.woke_reason,
             "message": t.message}
            for t in timers if _fired_after(t, since)]
    if not woke:
        # 事件也是"任一计时器返回"之外的醒源（子代理发消息 / 收工提交）：它同样该
        # 结束这一档挂机，否则"等我孩子说话"会一直挂到超时。
        #
        # 基线取"起意那一刻的事件序号"（`at_seq`），不是 0：
        # 观测窗是进程全局的，写死 0 会把前面所有用例的事件都算成"起意之后回来了"
        # —— 同台账号（多数判据都在新工作区里开 t-000001）加上假时钟让旧事件的时间看起来
        # 更新，于是新起的等待当场判"该回模型"，挂机永远不成立（真机 `31 条回来了`）。
        # 墙钟那一支只对老行（没有 `at_seq`）生效：假时钟下它必然错位。
        try:
            try:
                seq_mark = int(row.get("at_seq") or 0)
            except (TypeError, ValueError):
                seq_mark = 0
            events = observed_events(since_seq=seq_mark)["events"]
        except Exception:  # noqa: BLE001 - 读不成只影响这一格
            events = []
        legacy = not row.get("at_seq")
        for e in events:
            if str(e.get("task_id") or "") != tid and str(e.get("from_task_id") or "") != tid:
                continue
            if legacy and since and str(e.get("at") or ""):
                try:
                    if _parse_iso(str(e["at"])) < _parse_iso(since):
                        continue
                except ClockError:
                    # 时间戳解析不出来（老事件行的 at 不是 ISO）：按"这一条算新的"处理 ——
                    # 少算一条会让"醒"这件事丢失，多算一条只会让这一拍多回一次模型。
                    pass
            woke.append({"id": f"event:{e.get('seq')}", "kind": str(e.get("kind") or ""),
                         "outcome": "", "woke_reason": "event",
                         "message": str(e.get("content") or "")[:120]})
    out["pending"] = pending
    out["woke"] = woke
    # `requested` 与 `waiting` 是两件事：前者是"它要求过等"（意图），后者是"它要求过等
    # 且确实还有东西没回来"（挂机那一档）。折成一格会让"要求等、而一条计时器都没有"
    # 与"没要求过等"长得一样 —— 前者该交差，后者该继续问模型。
    out["requested"] = not woke
    out["waiting"] = bool(pending) and not woke
    if not out["reason"]:
        if out["waiting"]:
            out["reason"] = f"它要求等任意计时器返回；还有 {len(pending)} 条没回来"
        elif woke:
            out["reason"] = f"起意之后有 {len(woke)} 条回来了 ⇒ 该回模型了"
        else:
            out["reason"] = "它要求等任意计时器返回，而一条计时器都没有 ⇒ 无事可做"
    return out


def cancel_wait_any(workspace: str | Path, task_id: str) -> dict[str, Any]:
    """撤掉某代理的等待意图（回模型之后由循环调；找不到不是失败）。"""
    tid = str(task_id or "").strip()
    doc, error = _load_wait_any(workspace)
    if error:
        return {"checked": False, "cancelled": 0, "reason": error}
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    kept = [r for r in rows if str(r.get("task_id") or "") != tid]
    gone = len(rows) - len(kept)
    if gone:
        doc.update({"schema": SCHEMA, "rows": kept})
        try:
            _atomic_json(wait_any_path(workspace), doc)
        except OSError as exc:
            return {"checked": False, "cancelled": 0,
                    "reason": f"等待意图账写不成：{type(exc).__name__}: {exc}"}
    return {"checked": True, "cancelled": gone, "reason": ""}


#: 交差账（父代理据它把子代理记为静默）。
#:
#: 口径（业主原话）：「如果已无事可做且无计时器，这意味着它交差了，需要向父代理报告，
#: 父代理把它记为静默子代理」。写侧只记事实（谁向谁交差、为什么、当时账上是什么样），
#: "静默"这一档由 `conductor.agent_state` 从盘上事实算出来，不在这里另存一个布尔。
HANDOFF_REL: Path = Path("out") / "clock" / "handoffs.json"

#: 交差报告的标题（父代理按它在收件箱里认出"孩子交差了"）。
#:
#: 它是那条既有消息通道上的一句 subject，不是新开一条通道（业主：「需要向父代理报告」
#: 沿用既有的收工/消息通道）。
HANDOFF_SUBJECT: str = "交差"


def handoff_path(workspace: str | Path) -> Path:
    """交差账的落盘路径。"""
    return Path(workspace).resolve() / HANDOFF_REL


def _load_handoffs(workspace: str | Path) -> tuple[dict[str, Any], str]:
    path = handoff_path(workspace)
    empty: dict[str, Any] = {"schema": SCHEMA, "next_seq": 1, "rows": []}
    if not path.is_file():
        return empty, ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return empty, f"交差账读不成：{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list):
        return empty, "交差账不是 {rows: [...]} 形态"
    return doc, ""


def record_handoff(workspace: str | Path, *, task_id: str, parent_task_id: str = "",
                   role: str = "", reason: str = "",
                   timers: Iterable[str] = (), children: Iterable[str] = ()) -> dict[str, Any]:
    """记一条交差：某个代理无事可做且一条计时器都没有，向父代理报告。

    同一个 `task_id` 只记一条（交差是一次性的）：第二次调用返回同一条并标
    `duplicate=True` —— "又交了一次"与"第一次交差"必须分得开。
    """
    tid = str(task_id or "").strip()
    if not tid:
        raise ClockParamError("交差要一个台账号：不知道是谁交的差")
    doc, error = _load_handoffs(workspace)
    if error:
        raise ClockStateError(error)
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    for row in rows:
        if str(row.get("task_id") or "") == tid:
            return {**row, "duplicate": True, "checked": True, "reason": ""}
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    try:
        seq = max(1, int(doc.get("next_seq") or 1))
    except (TypeError, ValueError):
        seq = 1
    row = {"handoff_id": f"ho-{seq:06d}", "task_id": tid,
           "parent_task_id": str(parent_task_id or ""), "role": str(role or ""),
           "reason": str(reason or ""), "at": stamp,
           "timers": [str(x) for x in (timers or ())],
           "children": [str(x) for x in (children or ())]}
    rows.append(row)
    doc.update({"schema": SCHEMA, "next_seq": seq + 1, "rows": rows})
    try:
        _atomic_json(handoff_path(workspace), doc)
    except OSError as exc:
        raise ClockStateError(f"交差账写不成：{type(exc).__name__}: {exc}") from None
    # 交差也是一次"被时钟观测到的动静"（业主 2026-10-26：「被等的那一位交差/汇报时，
    # 时钟要唤醒等待者」）。父代理不会交差 —— 它给子发的是指导意见（走 `delivery`）——
    # 所以这两条路各记一格：等子靠 handoff，等父靠 delivery。
    try:
        observe_event("handoff", task_id=tid,
                      from_task_id=tid,
                      to_task_id=str(parent_task_id or ""),
                      role=str(role or ""),
                      content=(f"交差：{reason}" if str(reason or "").strip() else "交差"))
    except ClockError:
        # 观测窗记不下不该让"交差"这件事本身失败（交差已经落盘了）。
        pass
    # 消账的登记行（`EVENT_CLOSE_HOOKS["record_handoff"]`）：上面那一条 `handoff` 事件
    # 已经把 `task:<tid>` 撞过一遍，这里再按同一个键撞一次是幂等的 —— 它存在的意义是
    # "交差这条路登记过"，于是把观测窗打桩掉（漏发事件）时这一处仍然能消账。
    try:
        _close_waiters_for_event("record_handoff", [f"task:{tid}"], reading=reading)
    except Exception as exc:  # noqa: BLE001 - 消账是旁路，不许把交差带下水
        with _CLOSE_LOCK:
            _CLOSE["problems"] = (list(_CLOSE.get("problems") or ())
                                  + [f"record_handoff 消账失败：{type(exc).__name__}: {exc}"])[-20:]
    return {**row, "duplicate": False, "checked": True, "reason": ""}


def mark_handoff_seen(workspace: str | Path, *, task_id: str,
                      by_task_id: str) -> dict[str, Any]:
    """父代理把某个子代理的交差"记成看到了"（`seen_by` = 父的台账号）。

    这是"父代理把它记为静默"那一笔写在盘上的动作：行本来就由子代理交差时落下
    （`record_handoff`），这里只补"谁接收了它"。找不到那一行 ⇒ `found=False`
    （不是失败：孩子可能不是交差走的，例如它用 `final` 收工）。
    """
    tid = str(task_id or "")
    by = str(by_task_id or "")
    doc, error = _load_handoffs(workspace)
    if error:
        return {"checked": False, "found": False, "reason": error}
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    hit = None
    for row in rows:
        if str(row.get("task_id") or "") == tid:
            row["seen_by"] = by
            hit = row
            break
    if hit is None:
        return {"checked": True, "found": False,
                "reason": f"交差账里没有 {tid} 那一行（它可能不是交差走的）"}
    doc.update({"schema": SCHEMA, "rows": rows})
    try:
        _atomic_json(handoff_path(workspace), doc)
    except OSError as exc:
        return {"checked": False, "found": False,
                "reason": f"交差账写不成：{type(exc).__name__}: {exc}"}
    return {"checked": True, "found": True, "row": hit,
            "reason": "", "parent_task_id": str(hit.get("parent_task_id") or "")}


def read_handoffs(workspace: str | Path, *, parent_task_id: str = "") -> dict[str, Any]:
    """读交差账。给 `parent_task_id` 就只看它名下收到的那些（父代理的那一格读数）。

    三态：读不成 => `checked=False`（不是"没人交差"）。
    """
    doc, error = _load_handoffs(workspace)
    if error:
        return {"checked": False, "rows": [], "count": 0, "reason": error,
                "parent_task_id": str(parent_task_id or "")}
    rows = [dict(r) for r in doc.get("rows") or ()
            if isinstance(r, Mapping)
            and (not parent_task_id
                 or str(r.get("parent_task_id") or "") == str(parent_task_id))]
    return {"checked": True, "rows": rows, "count": len(rows), "reason": "",
            "parent_task_id": str(parent_task_id or "")}


def reset_handoffs(workspace: str | Path) -> dict[str, Any]:
    """清空这个工作区的交差账（判据之间的隔离点；盘上的那一份一起清）。"""
    try:
        _atomic_json(handoff_path(workspace), {"schema": SCHEMA, "next_seq": 1, "rows": []})
    except OSError as exc:
        return {"checked": False, "reason": f"交差账写不成：{type(exc).__name__}: {exc}"}
    return {"checked": True, "reason": ""}
