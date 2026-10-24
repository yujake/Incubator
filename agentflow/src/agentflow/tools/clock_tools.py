# -*- coding: utf-8 -*-
"""时钟原生工具：`clock.*` 五件，所有角色都能用，到点同时落 mailbox 项与唤醒标记。

## 为什么时钟必须是系统原生工具（D-53 的业主口径）

业主原话（唯一权威）：

    「对于D53，把时钟做成系统原生工具，让M在派活完后启动计时器（计时器依托时钟实现），
      到点后时钟自动给M发消息检查，检查完成后M再启动计时器。如果其它人要看表
      （看时钟读数）或计时、定闹钟什么的也可以用。总之这是个通用工具。
      时钟只有一个，依附于其上的计时进程可以很多。」

改前的形态：M 派完活之后没有任何"过一会儿回来看看"的动作可用，只能靠外部
按时间叫醒它；而"按时间"这件事在工具面上不可见。本模块把时钟、计时器、闹钟
做成五件工具，挂在 `clock.` 这一个组下。

## 五件工具

| 工具 | 作用 |
|---|---|
| `clock.now` | 读数：现在几点、这一趟跑了多久、有没有等我消费的唤醒标记 |
| `clock.timer_start` | 起一个一次性计时器（`after_sec` 秒后到点） |
| `clock.alarm_start` | 定一个到绝对时刻的闹钟（`at` 是 ISO 时刻） |
| `clock.timer_list` | 列出计时器（待发 / 已到点 / 已取消）与唤醒标记读数 |
| `clock.timer_cancel` | 取消一条还没到点的计时器 |

## 到点动作必须是两件一起

D-53 的核心修复是"到点后时钟自动给 M 发消息"。今天 D-52 的 mailbox 投递还没修，
所以到点动作由 `_deliver_due` 一次做两件：

1. 落一条 mailbox 项：`tasks` 表一行 `kind="notice"`、`parent_task_id` 是收件人
   的台账号、`detail` 逐字以 "计时器到点：" 开头。这一件可审计；
2. 置一条唤醒标记：`<工作区>/out/clock/wake.json` 里一条事件，带 `task_id` /
   `timer_id` / `mailbox_item_id`。这一件让"正在等子的父"能立刻拿到一个回合，
   不依赖还没修的 mailbox 投递。

两件都做、任缺一件都不算投递成功（判据 `tests/test_clock_is_a_native_tool.py`
的第 6 条用打桩分别证明两件都是承重的）。

## 消费端还差哪一步（本模块不改 `agent_loop.py`）

消费端（D-52/D-53 统一接的那一处）需要：在等子代理的等待点上读
`clock.pending_wakes(root, my_task_id)` 或调 `clock.consume_wakes(root, my_task_id)`，
并把"有唤醒"折进它本来就有的唤醒判据。本模块只把落点做好、读口交出去。

## 两根轴为什么这样声明（2026-10-24 按业主裁定改为据实）

业主新裁定（逐字，唯一权威）：「通用能力根本不该出现谁能用这个说法」。
这条裁定把两根轴分开了：副作用轴说"它改不改我们拥有的东西"，可达性轴说
"它是不是通用能力"。此前把两根轴压在一起，代价是这三件写表的工具被声明成
`side_effect="read"` —— 只为让 `for_role` 不把只读角色剥掉。那是谎报：
读到声明的人会以为它们不写表，而 `_deliver_due` 与 `C.start_timer` 都会落盘。

现在的声明据实：

| 工具 | side_effect | 为什么 |
|---|---|---|
| `clock.now` / `clock.timer_list` | `read` | 只读 |
| `clock.timer_start` / `clock.alarm_start` | `write_local` | 写 `out/clock` 的状态，到点后落一条 `tasks` notice 行与一条唤醒标记 |
| `clock.timer_cancel` | `write_local` | 改 `out/clock` 的状态（取消之后不该再有 notice 行） |

可达性不再靠声明绕过去：它们登记在 `tools.UNIVERSAL_TOOLS`（通用能力的受控集合），
`ToolRegistry.for_role` 对通用工具不按副作用等级剥离，所以 C / H / V 三个只读角色
照样拿得到这五件（判据 `tests/test_clock_is_a_native_tool.py` 的第 8 条与
`tests/test_universal_tools_are_for_everyone.py`）。它们也不进
`READONLY_CALL_EXCEPTIONS` —— 通用能力不是"例外"。

硬约束（不许通用集合变成后门）：`UNIVERSAL_TOOLS` 里每件工具登记的写集只许落在
通信/簿记类表上（今天只有 `tasks`；事件流与 `out/clock` 是文件，不在表里）。
写 `statements` / `claims` / `literature` / `relations` / `documents` 这类知识表
⇒ 判据直接红，且它不会被发给只读角色。将来如果时钟改成写领域表，
那就不再是通用能力，必须撤出 `UNIVERSAL_TOOLS` 并走 FC-27 人审。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Mapping

from .. import clock as C
from .. import schema as S
from ..conductor import current_caller_role, current_task_id
from .base import ToolRegistry, ToolResult, fail, ok, tool

#: 五件工具挂给全部角色 + 主控。业主口径是"通用工具"，不是某一角色的专有能力。
_ROLES_ALL: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 到点动作落进 `tasks.detail` 的逐字前缀。判据按它认出"这是一条到点项"。
DUE_PREFIX: str = "计时器到点："

#: 工作区 -> 到点投递需要的运行期绑定（store / conductor）。
#:
#: 为什么是运行期字典而不是写进 `state.json`：Store 与 Conductor 都是进程内对象，
#: 落盘没有意义。重启之后由下一次工具调用重新绑定；没绑定时的到点计时器会以
#: `DueDeferred` 保持 pending（不丢、不误标成已投递）。
_BINDINGS: dict[str, dict[str, Any]] = {}


def _resolve_root(root: Any, store: Any) -> Path:
    """工作区根：显式 root 优先，其次 store.root，最后进程 CWD。"""
    if root:
        return Path(root).resolve()
    base = getattr(store, "root", None)
    if base:
        return Path(base).resolve()
    return Path.cwd().resolve()


def _bind(workspace: str | Path, store: Any, conductor: Any = None) -> None:
    _BINDINGS[str(Path(workspace).resolve())] = {"store": store, "conductor": conductor}


def _binding(workspace: str | Path) -> dict[str, Any]:
    return _BINDINGS.get(str(Path(workspace).resolve()), {})


def _find_task(store: Any, task_id: str) -> dict[str, Any] | None:
    """台账里按台账号找一行。读不成 => 抛（那是"没查成"，不是"没有这一行"）。"""
    if store is None or not str(task_id or "").strip():
        return None
    try:
        rows = store.rows("tasks")
    except Exception as exc:  # noqa: BLE001
        raise C.ClockStateError(f"tasks 台账读不成：{type(exc).__name__}: {exc}") from None
    want = str(task_id)
    return next((r for r in rows if str(r.get("task_id") or "") == want), None)


def _recipient(store: Any, to: Any) -> dict[str, Any]:
    """解析收件人：`to="self"` 取调用上下文，否则按台账号查台账。"""
    target = str(to or "self").strip()
    if target in ("self", ""):
        task_id = str(current_task_id() or "").strip()
        if not task_id:
            raise C.ClockNotFound(
                "to=\"self\" 但调用上下文里没有台账号 —— 不知道到点该叫醒谁"
                "（这不是'没有任务'，是'没有身份'）")
        row = _find_task(store, task_id)
        role = str(current_caller_role() or "")
        if not role and row is not None:
            role = str(row.get("role") or "")
        if not role:
            raise C.ClockNotFound(
                f"to=\"self\" 解析到 {task_id}，但读不出它的角色 —— "
                "到点项需要 role 才能落成一行 tasks（不许猜一个角色）")
        depth = int((row or {}).get("depth") or 1)
        return {"task_id": task_id, "role": role, "depth": depth}
    row = _find_task(store, target)
    if row is None:
        raise C.ClockNotFound(f"台账里没有 {target} 这一行 —— 到点没有收件人")
    role = str(row.get("role") or "")
    if not role:
        raise C.ClockNotFound(f"{target} 那一行没有角色 —— 到点项不知道开给谁")
    return {"task_id": target, "role": role, "depth": int(row.get("depth") or 1)}


def _mailbox_detail(timer: C.Timer) -> str:
    return f"{DUE_PREFIX}{timer.reason}"


def _open_mailbox_item(store: Any, timer: C.Timer, recipient: Mapping[str, Any],
                       *, conductor: Any = None) -> str:
    """落一条到点项（`tasks` 表一行 notice），返回它的 task_id。

    优先复用 Conductor 的 `open_item`（板项的唯一开项入口，含取号与全字段落盘）；
    主控不在手上时退到 `_write_mailbox_row`。为什么不去 `conductor_for(store)`
    顺手建一个：`cached_conductor` 的 docstring 逐字写着"绝不顺手建一个" ——
    先在装配之前叫它一次，后来的接线会按缓存静默复用到那个空壳。
    """
    if store is None:
        raise C.DueDeferred("没有 store => 到点项写不进 tasks 表")
    detail = _mailbox_detail(timer)
    summary = detail[:200]
    depth = int(recipient.get("depth") or 1) + 1
    box = conductor
    if box is None:
        # 只借"已经存在"的那一个；不存在就走直写，不建空壳。
        try:
            from .conductor_tools import cached_conductor

            box = cached_conductor(store)
        except Exception:  # noqa: BLE001 - 借不到就走下面那条路
            box = None
    if box is not None:
        item_id = box.open_item(
            kind="notice", role=str(recipient.get("role") or ""), expects="ack",
            action="notice", summary=summary, called_by="clock",
            parent_task_id=str(recipient.get("task_id") or ""),
            depth=depth, input_key=f"clock:{timer.timer_id}",
        )
        box.set_item_detail(item_id, detail)
        return str(item_id)
    return _write_mailbox_row(store, timer, recipient, detail=detail, depth=depth)


def _write_mailbox_row(store: Any, timer: C.Timer, recipient: Mapping[str, Any],
                       *, detail: str, depth: int) -> str:
    """直写 `tasks` 表一行 notice（没有 Conductor 时的退路）。

    与 `Conductor._write_new_row` 同一纪律：取号与写行在同一个 `store.tx` 临界区里
    完成，落盘行用 `Task.to_dict()` 补齐到全字段（I-9 的键序口径在这里也成立）。
    """
    from ..interactions import next_prefixed_id

    row = {
        "task_id": "",
        "role": str(recipient.get("role") or ""),
        "action": "notice",
        "called_by": "clock",
        "parent_task_id": str(recipient.get("task_id") or ""),
        "depth": max(1, int(depth)),
        "input_key": f"clock:{timer.timer_id}",
        "status": "pending",
        "outcome": None,
        "refusal_reason": None,
        "instance": "",
        "detail": detail,
        "error": None,
        "started_at": "",
        "ended_at": None,
        "tokens": 0,
        "usd": 0.0,
        "artifacts": [],
        "inputs": [],
        "kind": "notice",
        "expects": "ack",
        "item_state": "queued",
        "item_close": "",
        "seen_by": "",
        "seen_step": None,
        "keep_alive": False,
    }
    with store.tx("tasks", actor="clock", note="clock:fired") as tx:
        row["task_id"] = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        task = S.Task(
            **{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}
        )
        task.validate()
        tx.upsert("tasks", task.to_dict(), note="clock:fired")
    return str(row["task_id"])


def _record_wake(workspace: str | Path, timer: C.Timer,
                 mailbox_item_id: str) -> dict[str, Any]:
    """置一条唤醒标记（转发 `clock.record_wake`；判据在它上面打桩）。"""
    return C.record_wake(workspace, timer, mailbox_item_id=mailbox_item_id)


def _deliver_due(timer: C.Timer) -> dict[str, Any]:
    """到点动作：同时落 mailbox 项与唤醒标记。返回 receipt（由 `fire_due` 落盘）。

    两件刻意分开 try：一件失败不该把另一件也吞掉。两件的错误都写进 `note`，
    `fire_due` 仍把计时器标成 fired —— "到点这一刻"是已经发生的事实，失败的
    那一件必须留在审计里，而不是靠重复触发去补（那会产生重复的 mailbox 项）。
    """
    workspace = timer.workspace
    binding = _binding(workspace)
    store = binding.get("store")
    if store is None:
        raise C.DueDeferred(
            f"工作区 {workspace} 没有绑定 store => 到点项写不进台账（计时器保持 pending）")
    try:
        recipient = _recipient(store, timer.task_id)
    except C.ClockError as exc:
        raise C.DueDeferred(f"到点收件人解析不了：{exc}") from None
    mailbox_item_id = ""
    mailbox_error = ""
    try:
        mailbox_item_id = _open_mailbox_item(
            store, timer, recipient, conductor=binding.get("conductor"))
    except Exception as exc:  # noqa: BLE001 - 一件失败不带走另一件
        mailbox_error = f"{type(exc).__name__}: {exc}"
    wake: Mapping[str, Any] = {}
    wake_error = ""
    try:
        wake = _record_wake(workspace, timer, mailbox_item_id)
    except Exception as exc:  # noqa: BLE001
        wake_error = f"{type(exc).__name__}: {exc}"
    note_bits = [f"mailbox_item_id={mailbox_item_id or '（空）'}"]
    if wake:
        note_bits.append(f"wake_id={wake.get('wake_id') or ''}")
    if mailbox_error:
        note_bits.append(f"mailbox 失败：{mailbox_error}")
    if wake_error:
        note_bits.append(f"wake 失败：{wake_error}")
    return {"mailbox_item_id": mailbox_item_id,
            "wake_id": str(wake.get("wake_id") or "") if wake else "",
            "note": "；".join(note_bits)}


# ---------------------------------------------------------------- 读数辅助


def _elapsed(store: Any, task_id: str) -> tuple[float | None, str]:
    """这一趟跑了多久。三态：读不到 => (None, "unknown")。

    优先用台账里这一行的 `started_at`（"这一趟"的起点）；没有这一行时退到
    本进程启动那一刻（`clock.process_started()`）。两者都读不到 => unknown。
    """
    reading = C.now()
    if reading.wall is None:
        return None, "unknown"
    row: Mapping[str, Any] = {}
    if store and task_id:
        try:
            row = _find_task(store, task_id) or {}
        except C.ClockStateError:
            # 台账读不成时只影响 elapsed 这一格（它是读数，不是结论）；
            # 时钟本身仍然可用，不许把整个 clock.now 判成失败。
            row = {}
    started = str(row.get("started_at") or "")
    if started:
        try:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=reading.wall.tzinfo)
            return max(0.0, (reading.wall - start.astimezone(reading.wall.tzinfo)).total_seconds()), "task"
        except ValueError:
            return None, "unparsed"
    process = C.process_started()
    if process.wall is not None:
        return max(0.0, (reading.wall - process.wall).total_seconds()), "process"
    return None, "unknown"


def _after_seconds(timer: C.Timer) -> float | None:
    """起表时"多久之后"的读数：计时器直接用 after_sec；闹钟按 created -> due 算。"""
    if timer.after_sec is not None:
        return float(timer.after_sec)
    try:
        due = C.parse_iso(timer.due_at)
        created = C.parse_iso(timer.created_at)
        return (due - created).total_seconds()
    except Exception:  # noqa: BLE001 - 回显读不出来不该让起表失败
        return None


def _start_payload(timer: C.Timer) -> dict[str, Any]:
    reading = C.now()
    return {
        "timer_id": timer.timer_id,
        "kind": timer.kind,
        "state": timer.state,
        "to": timer.to,
        "task_id": timer.task_id,
        "role": timer.role,
        "reason": timer.reason,
        "after_sec": _after_seconds(timer),
        "due_at": timer.due_at,
        "at": timer.due_at,
        "remaining_sec": timer.remaining_seconds(reading),
        "created_at": timer.created_at,
        "clock_status": reading.status,
    }


# ---------------------------------------------------------------- 五件工具


@tool(
    "clock.now",
    "读系统时钟：现在几点（墙钟 + 单调计数）、这一趟跑了多久、有没有等我消费的唤醒标记。"
    "读不到时 status=unknown、wall/monotonic 都是 null（绝不折成 0）。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "include_wakes": {"type": "boolean",
                           "description": "是否一并读唤醒标记（缺省是）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES_ALL,
    returns=("{'clock','status','wall','monotonic','source','reason','task_id','role',"
             "'elapsed_sec','elapsed_from','pending_wakes','wakes_checked','wakes_reason'}"),
    tags=("clock", "time", "read"),
)
def clock_now(store: Any, root: Any, *, include_wakes: bool = True) -> ToolResult:
    """读一次时钟。不写任何东西。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    task_id = str(current_task_id() or "")
    role = str(current_caller_role() or "")
    elapsed_sec, elapsed_from = _elapsed(store, task_id)
    if include_wakes:
        wakes = C.pending_wakes(workspace, task_id or None)
        wake_count = int(wakes.get("count") or 0) if wakes.get("checked") else 0
        wakes_checked = bool(wakes.get("checked"))
        wakes_reason = str(wakes.get("reason") or "")
    else:
        wake_count, wakes_checked, wakes_reason = 0, False, "include_wakes=false"
    return ok({
        "clock": "agentflow.clock",
        "status": reading.status,
        "wall": reading.to_dict()["wall"],
        "monotonic": reading.monotonic,
        "source": reading.source,
        "reason": reading.reason,
        "task_id": task_id,
        "role": role,
        "elapsed_sec": elapsed_sec,
        "elapsed_from": elapsed_from,
        "pending_wakes": wake_count,
        "wakes_checked": wakes_checked,
        "wakes_reason": wakes_reason,
    })


@tool(
    "clock.timer_start",
    "起一个一次性计时器：after_sec 秒后到点。到点后时钟自动落一条 notice 板项给收件人"
    "（parent_task_id 是收件人台账号），并同时置一条唤醒标记。不自动重排：检查完成后"
    "再起一次。所有角色都能用。",
    {"type": "object",
     "properties": {
         "after_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                       "description": "多少秒之后到点（必须为正）"},
         "reason": {"type": "string", "minLength": 1, "maxLength": 500,
                    "description": "为什么叫醒（会进到点项的 detail）"},
         "to": {"type": "string",
                "description": "收件人：self（缺省，叫我这一趟）或 tasks 表的台账号"},
     },
     "required": ["after_sec", "reason"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'timer_id','kind','state','to','task_id','role','reason','after_sec',"
             "'due_at','at','remaining_sec','created_at','clock_status'}"),
    tags=("clock", "timer", "communication"),
)
def clock_timer_start(store: Any, root: Any, conductor: Any, *, after_sec: float,
                      reason: str, to: str = "self") -> ToolResult:
    """起计时器。参数不合法 / 读不到时钟 / 收件人不存在 => 受控失败，零写入。"""
    workspace = _resolve_root(root, store)
    _bind(workspace, store, conductor)
    try:
        recipient = _recipient(store, to)
        timer = C.start_timer(workspace, after_sec=after_sec, reason=reason, to=to,
                              task_id=str(recipient["task_id"]),
                              role=str(recipient["role"]))
    except C.ClockUnreadable as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True)
    except C.ClockNotFound as exc:
        return fail(str(exc), kind="not_found", checked=True)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    return ok(_start_payload(timer), timer_id=timer.timer_id)


@tool(
    "clock.alarm_start",
    "定一个一次性闹钟：到 at（ISO 时刻）时叫醒收件人。到点动作与 timer_start 相同"
    "（一条 notice 板项 + 一条唤醒标记），差别只在时间怎么给。所有角色都能用。",
    {"type": "object",
     "properties": {
         "at": {"type": "string", "minLength": 1,
                "description": "到点时刻（ISO；naive 按 UTC 解释；必须晚于现在）"},
         "reason": {"type": "string", "minLength": 1, "maxLength": 500,
                    "description": "为什么叫醒（会进到点项的 detail）"},
         "to": {"type": "string",
                "description": "收件人：self（缺省，叫我这一趟）或 tasks 表的台账号"},
     },
     "required": ["at", "reason"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'timer_id','kind','state','to','task_id','role','reason','after_sec',"
             "'due_at','at','remaining_sec','created_at','clock_status'}"),
    tags=("clock", "alarm", "communication"),
)
def clock_alarm_start(store: Any, root: Any, conductor: Any, *, at: str,
                      reason: str, to: str = "self") -> ToolResult:
    """定闹钟。at 已经过去 / 收件人不存在 => 受控失败，零写入。"""
    workspace = _resolve_root(root, store)
    _bind(workspace, store, conductor)
    try:
        recipient = _recipient(store, to)
        timer = C.start_alarm(workspace, at=at, reason=reason, to=to,
                              task_id=str(recipient["task_id"]),
                              role=str(recipient["role"]))
    except C.ClockUnreadable as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True)
    except C.ClockNotFound as exc:
        return fail(str(exc), kind="not_found", checked=True)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    return ok(_start_payload(timer), timer_id=timer.timer_id)


@tool(
    "clock.timer_list",
    "列出计时器：待发 / 已到点 / 已取消，各带 due_at、remaining_sec（读不到时钟时为 null）"
    "与到点项编号；同时给唤醒标记的读数。所有角色都能用。",
    {"type": "object",
     "properties": {
         "include_done": {"type": "boolean",
                          "description": "是否含已到点/已取消的（缺省是）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES_ALL,
    returns=("{'checked','clock','status','wall','monotonic','timers','count',"
             "'pending_count','fired_count','cancelled_count','pending_wakes',"
             "'wakes_checked','reason'}"),
    tags=("clock", "timer", "read"),
)
def clock_timer_list(store: Any, root: Any, *, include_done: bool = True) -> ToolResult:
    """读计时器与唤醒标记。读不成 => checked=False（不是"没有计时器"）。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    try:
        all_timers = C.timers(workspace)
    except C.ClockStateError as exc:
        return ok({
            "checked": False, "clock": "agentflow.clock", "status": reading.status,
            "wall": reading.to_dict()["wall"], "monotonic": reading.monotonic,
            "timers": [], "count": 0, "pending_count": 0, "fired_count": 0,
            "cancelled_count": 0, "pending_wakes": 0, "wakes_checked": False,
            "reason": str(exc),
        })
    shown = [t for t in all_timers if include_done or t.state == "pending"]
    rows = [t.row(reading) for t in shown]
    wakes = C.read_wakes(workspace)
    return ok({
        "checked": True,
        "clock": "agentflow.clock",
        "status": reading.status,
        "wall": reading.to_dict()["wall"],
        "monotonic": reading.monotonic,
        "timers": rows,
        "count": len(rows),
        "pending_count": sum(1 for t in all_timers if t.state == "pending"),
        "fired_count": sum(1 for t in all_timers if t.state == "fired"),
        "cancelled_count": sum(1 for t in all_timers if t.state == "cancelled"),
        "pending_wakes": int(wakes.get("count") or 0) if wakes.get("checked") else 0,
        "wakes_checked": bool(wakes.get("checked")),
        "reason": str(wakes.get("reason") or ""),
    })


@tool(
    "clock.timer_cancel",
    "取消一条还没到点的计时器/闹钟（到点后不再触发）。已到点或已取消的返回 "
    "cancelled=false + 它当前的状态（查过了，不是第二次取消）。所有角色都能用。",
    {"type": "object",
     "properties": {
         "timer_id": {"type": "string", "minLength": 1, "maxLength": 64,
                      "description": "clock.timer_start / alarm_start 返回的编号"},
     },
     "required": ["timer_id"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'checked','timer_id','cancelled','state','reason','timer',"
             "'pending_count','clock_status'}"),
    tags=("clock", "timer", "communication"),
)
def clock_timer_cancel(store: Any, root: Any, *, timer_id: str) -> ToolResult:
    """取消计时器。找不到不是失败（三态：查过了、没有这一条）。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    try:
        timer, state = C.cancel_timer(workspace, timer_id)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False, timer_id=timer_id)
    try:
        pending_count = len(C.book(workspace).pending())
    except C.ClockStateError:
        pending_count = 0
    reason = ""
    if timer is None:
        reason = f"没有 {timer_id} 这一条（不是'已经取消'）"
    elif state == "already_cancelled":
        reason = f"{timer_id} 早就是取消态（查过了，不是第二次取消成功）"
    elif state != "cancelled":
        reason = f"{timer_id} 当前状态是 {state}，不是待发"
    return ok({
        "checked": True,
        "timer_id": str(timer_id),
        "cancelled": state == "cancelled",
        "state": timer.state if timer is not None else "not_found",
        "reason": reason,
        "timer": timer.row(reading) if timer is not None else None,
        "pending_count": pending_count,
        "clock_status": reading.status,
    })


#: 工具与它需要的装配期依赖（`register` 只按位置把依赖绑上去）。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (clock_now, ("store", "root")),
    (clock_timer_start, ("store", "root", "conductor")),
    (clock_alarm_start, ("store", "root", "conductor")),
    (clock_timer_list, ("store", "root")),
    (clock_timer_cancel, ("store", "root")),
)


def register(registry: ToolRegistry, *, store: Any = None, root: Any = None,
             workspace_root: Any = None, conductor: Any = None,
             **_: Any) -> list[str]:
    """把五件 `clock.*` 装进注册表，返回工具名列表。

    同时做两件装配期的事：

    1. 把到点动作接到 `clock.set_due_handler`：这是"到点后时钟自动动作"的接线点；
    2. 把这一趟的工作区与 store 绑进运行期表：到点动作需要它写 mailbox 项。
    """
    C.set_due_handler(_deliver_due)
    workspace = _resolve_root(root if root else workspace_root, store)
    _bind(workspace, store, conductor)
    bound: dict[str, Any] = {
        "store": store,
        "root": workspace,
        "conductor": conductor,
    }
    names: list[str] = []
    for fn, deps in _TOOL_FUNCTIONS:
        spec = replace(fn.__tool_spec__,
                       handler=partial(fn, *[bound[k] for k in deps]))
        names.append(registry.register(spec).name)
    return names


__all__ = ["DUE_PREFIX", "register"]
