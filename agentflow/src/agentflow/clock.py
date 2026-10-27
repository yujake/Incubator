# -*- coding: utf-8 -*-
"""系统时钟：全系统唯一的取时口，计时器与闹钟都依附在它上面。

## D-53 的业主口径（唯一权威）

    「对于D53，把时钟做成系统原生工具，让M在派活完后启动计时器（计时器依托时钟实现），
      到点后时钟自动给M发消息检查，检查完成后M再启动计时器。如果其它人要看表
      （看时钟读数）或计时、定闹钟什么的也可以用。总之这是个通用工具。
      时钟只有一个，依附于其上的计时进程可以很多。」

## 这个模块负责什么，不负责什么

负责：

1. 唯一的读数口 `now()`：一次给出墙钟与单调计数，两者各自可能读不到；
2. 注入点：判据可以把假时钟装进来（`use(FakeClock(...))`），业务代码一律
   经 `now()` 取时，不许自己调 `time.time()`；
3. 计时器/闹钟的登记与落盘（`<工作区>/out/clock/state.json`），重启后仍在；
4. 到点判定 `is_due` 与"把到点的那些交出去"`fire_due()`；
5. 唤醒标记的落盘与读数（`<工作区>/out/clock/wake.json`），以及给消费端用的
   `consume_wakes()`。

不负责：把 mailbox 项写进 `tasks` 表。那件事需要 Store / Conductor，属于工具层
（`tools/clock_tools.py` 的 `_deliver_due`）。本模块只提供"谁到点了"这一份事实，
到点动作由工具层注册进来（`set_due_handler`）。这样切的理由：时钟要能被判据
单独喂假时钟、单独检查读数，不该为了一个 mailbox 写口把 Store 拖进来。

## 三态纪律（本模块的核心）

时钟读数有三个状态，不许折平：

- `ok`：墙钟与单调计数都读到了；
- `partial`：只读到一个来源（`source` 说明是哪一个）；
- `unknown`：两个都读不到。此时 `wall` 与 `monotonic` 都是 `None`，
  绝不是 0 —— 把"读不到"折成 0 会让"1970 年"变成一个看起来合法的时间点。

`timer_list` 里的 `remaining_sec` 同样是三态：读不到时钟时是 `None`，不是 0。
到点判定在读不到时钟时返回"判不了"（`is_due` 为假），于是计时器保持 pending，
等下一次时钟恢复；它不会被误触发，也不会被静默丢掉。

## 计时器与闹钟的区别

两者是同一个数据结构，只差 `kind` 与 due 是怎么算出来的：计时器给 `after_sec`
（相对现在多久之后），闹钟给 `at`（绝对 ISO 时刻）。两者都是
一次性：到点即消耗（`state="fired"`），不自动重排。业主口径是"检查完成后 M
自己再启动计时器"，所以重排必须是调用方显式再起一次。

## 重启之后怎么判 due

每条计时器同时记 `due_at`（墙钟，绝对时刻）与 `due_mono`（起表那个进程的单调
计数）。单调计数只在同一个时钟实例（`clock_token` 相同）里可比；重启后 token
变了，于是退化到按墙钟比较。这不是"两个来源二选一"的随意取舍：单调计数跨重启
没有意义（它从进程启动算起），而墙钟是重启后唯一还能对齐的绝对时刻。

## 消费端还差哪一步

D-52 的 mailbox 投递还没修，所以"到点唤醒正在等子的父"这件事今天由两件一起
保证：落一条 `tasks` 板项（可审计）与置一条唤醒标记（可读、可消费）。消费端
（`agent_loop` 的等待/续跑那一处，D-52/D-53 统一接）需要做的是：在等子代理的
等待点上读 `pending_wakes(root, my_task_id)`，或调
`consume_wakes(root, my_task_id)`，并把"有唤醒"折进它本来就有的唤醒判据。
本模块不改 `agent_loop.py`，只把可读的落点交出去。

## 业主 2026-10-25 的裁定（唯一权威）：计时类任务的申请形状

    「主时钟是否控制了所有计时类工作？如果不是，请规范所有计时类任务申请的形式为：
      等待时间（或等待谁）+目的（必填），例如M的巡视叫等待20分钟+周期性巡查。」

    「注意：让老的未依赖时钟的计时工具退场，当智能体忘填目的时不报错，只是让它追加目的。
      计时到点后向智能体发送信息"目的+等待时间+时间到"」

于是申请形状只有两半，两半各自成立：

1. 等待时间：`after_sec`（多久之后）或 `at`（到哪个钟点）；
2. 等待谁：`wait_for`（名册名 / 绝对编号 / `task:<号>` / `agent:<名>`），
   到被等对象收口时报醒。

两个都给 => 受控拒绝并说清只能选一个；一个都不给 => 受控拒绝。

目的缺了不再打回重来（上面第二句）：照常在给出的一半时序上受起表，读数带
`purpose_missing=true`，其后的读数与到点消息里追问一句；补一句目的走
`set_purpose`，同一条计时器被填上，不是新建一条。

## 周期性：M 的巡视就是这一类

`start_periodic(every_sec, purpose, ...)`：到点不消耗，`next_at` 前移到下一拍，
`fires` 递增，直到 `periodic_stop` / `until_sec` 到 / 被等的对象收口。
口径写死：M 的巡视是「等 20 分钟 + 周期性巡查」（`every_sec=1200`、
`purpose="周期性巡查"`），不许写成"睡 20 分钟"这种没有目的的形。

## 到点那条消息的格式（业主定死）

    时间到：<目的>｜等了 <时长>（起于 <HH:MM:SS>，到于 <HH:MM:SS>）
    巡查时间到：<目的>｜每 <间隔>一次（第 <N> 次）

目的缺了那一趟写 `（目的未填）` 并追问补一句。三样（目的 / 等待时间 / 时间到）
必须在同一句里，不许只报"到点了"。拼这句话的落点是 `due_message`（唯一实现），
工具层与唤醒标记都读它，不许各拼一份。

## 等待账：为什么框架内部的等待也要进这本账

"主时钟控制了所有计时类工作"这句话今天不成立，因为框架内部还有一批
`time.sleep` / 有界等待不在任何账上（下载重试、检索重试、调度轮询、排水轮询……）。
本模块因此提供两个入口，所有等待都必须走其中之一：

- `await_io(seconds, purpose, kind=..., where=...)`：真睡（保持原语义）并记一条账；
- `note_wait(seconds, purpose, kind=..., where=...)`：不睡，只记一条账 —— 给那些
  阻塞由同步原语/子进程调用完成、不能替换成 sleep 的等待用。

账记的是聚合而不是每一次：同一个 `(kind, where, purpose)` 只占一行，累加次数与
时长。几百次重试不会把账写成几万行。

机器判据是普查：`raw_wait_census()` 用 AST 扫 `src/agentflow` 下的全部模块，把
"没走上面两个入口的原始等待"逐个点出来（文件:行 + 所在函数 + 形态）。`coverage()`
把普查与"已记账的等待"合起来给一份读数，`clock.now` 的复合读数里就有
`waits_outside_clock`。它是"是否全被主时钟控制"的机器判据，不是一句声明。

三态纪律同样适用：扫描读不成 => `checked=false`，不许折成"0 处，很干净"。

允许的例外逐条登记在 `ALLOWED_RAW_WAITS` 里，每条必须写 `why` 与 `blocked_by`；
`coverage()` 把它们单列（`waits_exempt`），不并进 `waits_outside_clock` ——
"被禁改区挡住的等待"与"没人管的等待"是两件事，折平就等于把没做完的活报成做完了。

## 业主 2026-10-27 的四条裁定（唯一权威）

    「将计时器的"等谁"加强到可以等某程序，即运行一个程序时会自动启动一个计时器，
      程序运行完成时计时器会返回。」

    「再将"等子代理"的"目的"与名册机制的 task 结合，自动以 task 填充目的。」

    「注意：计时器不阻塞智能体动作，智能体可在多计时器同时存在时继续手上工作，
      直到它认为无事可做时，可启动计时器"等待任意计时器返回"。如果已无事可做且无计时器，
      这意味着它交差了，需要向父代理报告，父代理把它记为静默子代理。」

    「注意：如果一个子代理还有活跃子代理，必存在一个等待该子代理的计时器，所以"静默"
      定义良好。」

四条各自的机器落点（本节逐条对应）：

1. 等程序：`program_span(...)` 是起外部程序的唯一入口。进作用域就 `start_program`
   登记一条 `kind="program"` 的计时器，出作用域 `finish_program` 把它收口并写上
   结局（`exited` / `failed` / `timed_out` / `killed`）、`elapsed_sec`、`exit_code`。
   读数是 `programs(workspace)`。另有 `program_census()` 用 AST 把"起进程却没进
   程序计时器"的地方逐个点出来 —— "程序在跑而账上没有计时器"是机器判据，不是声明。
2. 目的自动填：`start_timer(wait_for=...)` 不给 `reason` 时，用"等谁"读口（
   `set_target_probe`）给出的 `task_text` 填目的，读数标 `purpose_source="target_task"`；
   显式给了就是 `given`；两边都拿不到还是 `purpose_missing=true` 加追问（原语义不变）。
3. 计时器不阻塞动作：计时器只是账上的一条，循环该调模型就调模型（`agent_loop._park_gate`
   的判据是"有没有 `wait_any` / 是不是真的无事可做"，不是"有没有计时器"）。
   显式要求"等待任意计时器返回"走 `request_wait_any(...)`，读数 `wait_any_reading(...)`。
4. 交差与静默：无事可做且一条计时器都没有 ⇒ `record_handoff(...)` 记下这次交差
   （父代理据此把它记为静默），父侧的读数是 `read_handoffs(workspace, parent_task_id=…)`。
   不变量（有活跃子代理 ⇒ 必有一条等它的计时器）由父代理派活时自动起表保证
   （`conductor` 的 summon 落点）并由 `conductor.child_wait_invariant` 判定。
"""

from __future__ import annotations

import ast
import contextlib
import contextvars
import json
import os
import signal
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from .canonical import json_default
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

UTC = timezone.utc

#: 时钟状态与唤醒标记的落盘位置（相对工作区根）。
STATE_REL: Path = Path("out") / "clock" / "state.json"
WAKE_REL: Path = Path("out") / "clock" / "wake.json"

#: 等待账的落盘位置（相对工作区根）。等待是一等公民的账，与计时器台账分开落。
WAITS_REL: Path = Path("out") / "clock" / "waits.json"

#: 两份落盘文件的 schema 版本。加字段不抬它；改字段含义或删字段才抬。
SCHEMA: int = 1

#: 读数状态的受控词表。三态，不许折平。
READING_STATES: tuple[str, ...] = ("ok", "partial", "unknown")

#: 计时器状态的受控词表。`fired` 与 `cancelled` 都是终态，不许回退。
TIMER_STATES: tuple[str, ...] = ("pending", "fired", "cancelled")

#: 计时器种类的受控词表。`periodic` 是"周期性巡查"那一档（到点不消耗）；
#: `program` 是"起了一个外部程序"那一档（业主 2026-10-27：「运行一个程序时会自动
#: 启动一个计时器，程序运行完成时计时器会返回」）。
TIMER_KINDS: tuple[str, ...] = ("timer", "alarm", "periodic", "program")

#: 程序计时器的结局受控词表（程序结束时写进 `outcome`；`exit_code` 单列一格）。
#:
#: 四档不许折平：`exited` 是"跑完了（退出码看 exit_code）"、`failed` 是"跑的路
#: 上抛了异常（没有退出码可读）"、`timed_out` 是"到上限被杀"、`killed` 是"有人喊停"。
#: 把后两档折进第一档会让"超时"与"跑完了但退出码非 0"长得一样。
PROGRAM_OUTCOMES: tuple[str, ...] = ("exited", "failed", "timed_out", "killed")

#: 目的的来源受控词表（业主 2026-10-27 的第二条裁定）。四档，不许折平：
#: `given` = 调用方显式给的；`target_task` = 从被等对象（那条子代理）的 task 文本自动填的；
#: `program` = 等程序那一条没给目的时，用程序名 + 命令行摘要自动填的
#: （业主同日第一条裁定：运行一个程序会自动起一条计时器，它当然也该有话可念）；
#: `unavailable` = 三条自动填的路都拿不到东西（此时 `purpose_missing` 为真，沿用既有追问语义）。
#:
#: 四档都要真落盘（`Timer.to_dict` 的 `purpose_source` 键）：只活在读数里的话，
#: "为什么这一条没目的"在盘上就退化成一句空串。
PURPOSE_SOURCES: tuple[str, ...] = ("given", "target_task", "program", "unavailable")

#: 从被等对象那一边抄目的时的截断长度（业主定死 200 字）。
PURPOSE_FROM_TARGET: int = 200

#: 程序计时器里 `argv_digest` 的截断长度（它是摘要，不是完整命令行）。
ARGV_EXCERPT: int = 200

#: 周期性条目状态的受控词表。三个都是终态，不许回退。
PERIODIC_STATES: tuple[str, ...] = ("running", "stopped", "until_reached", "cancelled")

#: `wait_for` 的三种指称（业主 2026-10-26："等别人"必须明确到等名册上的谁
#: 或等哪条程序）：
#: - `agent`：名册名（`agent:<名>` / 裸名字）；
#: - `task`：绝对编号（`task:<号>` / 裸编号）；
#: - `program`：某条程序计时器的句柄（`program:<tm-号>`，或直接给 `start_program`
#:   返回的那个 Timer 对象）。
WAIT_FOR_KINDS: tuple[str, ...] = ("agent", "task", "program")

#: 到点判定的五种触发。它们可以同时成立（等时间 + 等谁，先到者报醒）；
#: `program_exit` 是程序计时器那一档：程序结束（成功/失败/超时/被杀）就是它到点。
DUE_TRIGGERS: tuple[str, ...] = ("deadline", "target_closed", "target_event", "cap",
                                 "program_exit")

#: "为什么醒了"的受控词表（业主 2026-10-25 的 `woke_reason`）：
#: 等到了对方的事件 / 对方收口 / 到点没等到 / 被等对象已销号 / 程序跑完了。
WOKE_REASONS: tuple[str, ...] = ("event", "closed", "timeout", "retired", "program")

#: 等谁的三态读数（与 `Reading` 同一族纪律：不许把"没查成"折成"没到"）。
TARGET_STATES: tuple[str, ...] = ("open", "closed", "unjudgeable")

#: 挂机状态（业主 2026-10-25：「挂机是将进程挂在时钟上」）。
#:
#: `parked` = 已经登记在时钟上、控制权交还了；`woke` = 时钟放行了；`cancelled` = 撤了。
#: 它不是"轮询"：挂机期间这一趟不产生回合（判据数它的 `agent_step` 事件）。
PARK_STATES: tuple[str, ...] = ("parked", "woke", "cancelled")

#: "产生一个回合/一次模型调用"的会话事件种类。本框架里一步一次调用（一一对应），
#: 所以挂机区间里数它就能同时回答"有没有偷偷在跑"。
WORK_EVENT_KINDS: tuple[str, ...] = ("agent_step",)


class ClockError(RuntimeError):
    """时钟层的公共失败类型。调用方只需捕这一个。"""


class ClockUnreadable(ClockError):
    """读不到时钟（三态的 unknown）。调用方不许把它折成"现在时刻是 0"。"""


class ClockParamError(ClockError):
    """参数不合法（after_sec 不是正数、at 已经过去、reason 是空串等）。"""


class ClockNotFound(ClockError):
    """台账里没有这个收件人 / 没有这个计时器。"""


#: "等谁"解析不到一个具体对象的机器码（业主 2026-10-26：
#: 「"等别人"必须要明确到等名册上的谁……或者等哪条程序」）。
#:
#: 它是`ClockNotFound` 的子类：工具层那边按 `ClockNotFound` 折成 `not_found` 的口径
#: （`tools/clock_tools.py` 的 except 段不归这一批改），所以码本身写在拒信第一句，
#: 读的人与判据都按这一串认。记进 `errorstats` 码表（见那里的登记行）。
WAITER_NOT_RESOLVABLE: str = "waiter_not_resolvable"


class ClockWaiterNotResolvable(ClockNotFound):
    """`wait_for` 解析不到一个具体的等待对象（散文 / 查无此人 / 不是程序句柄）。

    与 `ClockNotFound` 的差别只在语义：那个是"你要找的那一条不存在"，
    这个是"你这句写法根本不指向任何一条"—— 后者要教人重写一次，所以拒信里
    必须把两条正路逐字给出来（`waiter_refusal()` 是唯一拼法）。
    """


class ClockNoTimersToWait(ClockParamError):
    """起意"等任意计时器返回"，而名下一条现存计时器都没有（码 `no_timers_to_wait`）。

    它是参数/前置条件不成立，不是"没查成"也不是"查无此人"：拒信由
    `no_timers_refusal()` 拼，逐字给两条正路（先起一条表 / 按交差收工）。
    """


#: "起意等任意计时器返回"时一条计时器都没有的机器码（业主 2026-10-26：
#: 「这个需要存在的计时器数大于等于1」）。
NO_TIMERS_TO_WAIT: str = "no_timers_to_wait"


def waiter_refusal(value: Any, *, why: str = "") -> str:
    """`wait_for` 解析不到时的拒信（逐字两条正路；判据按这两句认）。

    为什么拒信要写成"两条正路"而不是"参数不合法"：这句话是模型下一次重写的唯一依据。
    业主原话是「必须要明确到等名册上的谁……或者等哪条程序」—— 于是正路也只有两条：
    名册上的那一位（名册名或绝对编号）与某一条程序（`clock.start_program` 的句柄）。
    """
    detail = f"（{why}）" if str(why or "").strip() else ""
    return (
        f"{WAITER_NOT_RESOLVABLE}：wait_for={value!r} 没有指向一个具体的等待对象{detail}。"
        "两条正路：① 写名册上的谁——名册名或绝对编号"
        "（例如 wait_for=\"A1\" 或 wait_for=\"t-000002\"；父代理与子代理都一样），"
        "必须能在名册里解析到唯一一个台账号；"
        "② 等某条程序——用 clock.start_program(...) 拿到的那个句柄"
        "（wait_for=\"program:<那个 timer_id>\"）。"
        "不支持\"别人\"/\"外部\"/\"等结果\"这类散文：时钟按名字或编号找人，猜不出你指谁。")


def no_timers_refusal(*, role: str = "") -> str:
    """`request_wait_any` 在一条计时器都没有时的拒信（逐字两条正路）。"""
    who = f"（{role}）" if str(role or "").strip() else ""
    return (
        f"{NO_TIMERS_TO_WAIT}：你名下现在一条计时器都没有{who} —— "
        "\"等待任意计时器返回\"要求现存计时器数 >= 1（业主 2026-10-26），"
        "没有可等的东西就不该挂在这一档上。两条正路："
        "① 先起一条表：等子写 wait_for=<名册名或绝对编号>，等程序用 "
        "clock.start_program(...)，等时间用 after_sec=…；"
        "② 或者按交差收工：无事可做 + 无计时器 = 交差（父代理那一侧会把你记为静默）。")


class ClockStateError(ClockError):
    """状态文件读不成或写不成。这不是"没有计时器"，是"没查成"。"""


class DueDeferred(ClockError):
    """这一条到点了，但到点动作今天做不了（例如没有绑定 store）。

    刻意不把它折成"已经投递"：计时器保持 pending，下一次 `fire_due` 再试。
    """


# ---------------------------------------------------------------- 读数


@dataclass(frozen=True)
class Reading:
    """一次取时的读数。三个状态见模块 docstring。"""

    status: str
    wall: datetime | None = None
    monotonic: float | None = None
    source: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in READING_STATES:
            raise ValueError(f"status 必须是 {READING_STATES} 之一，收到 {self.status!r}")
        if self.status == "unknown" and (self.wall is not None or self.monotonic is not None):
            raise ValueError("unknown 读数不许带具体的墙钟/单调计数（那会把读不到折成一个数）")

    @property
    def known(self) -> bool:
        """能不能判时间。`partial` 也算能判（至少有一个来源）。"""
        return self.status != "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "wall": _iso(self.wall) if self.wall is not None else None,
            "monotonic": self.monotonic,
            "source": self.source,
            "reason": self.reason,
        }


def _reading(wall: datetime | None, monotonic: float | None,
             reasons: Iterable[str] = ()) -> Reading:
    """把两个来源的读数装成三态。缺一个 => partial；两个都缺 => unknown。"""
    why = [str(r) for r in reasons if str(r or "").strip()]
    if wall is not None and monotonic is not None:
        return Reading("ok", wall, monotonic, "wall+monotonic", "")
    if wall is not None:
        return Reading("partial", wall, None, "wall",
                       "；".join(why) or "单调计数读不到")
    if monotonic is not None:
        return Reading("partial", None, monotonic, "monotonic",
                       "；".join(why) or "墙钟读不到")
    return Reading("unknown", None, None, "none",
                   "；".join(why) or "墙钟与单调计数都读不到")


def _parse_iso(value: Any) -> datetime:
    """ISO 时刻 -> UTC aware datetime。naive 一律按 UTC（写在返回值之外的那条纪律）。

    为什么允许 naive：`at` 是模型写的参数，`2026-01-01T00:10:00` 这种写法在
    function-calling 里很常见。拒绝它只会把一次可用的调用变成参数错误；把它按
    UTC 解释并在读数里给出 `due_at` 的完整 ISO，读的人能看见时区是被补上的。
    """
    if isinstance(value, datetime):
        got = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ClockParamError("时刻是空串")
        try:
            got = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClockParamError(f"时刻不是 ISO 格式：{value!r}（{exc}）") from None
    if got.tzinfo is None:
        got = got.replace(tzinfo=UTC)
    return got.astimezone(UTC)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat()


#: ISO 解析/格式化的公开别名。工具层回显 `after_sec` 要用它；不要在别处再写
#: 第三份解析（naive 按 UTC 这条口径只留一个落点）。
parse_iso = _parse_iso
iso = _iso


# ---------------------------------------------------------------- 申请形状的两半


def _looks_like_task_id(text: str) -> bool:
    """这一串像不像一个绝对编号（`t-000012` 或老的 `t000012`）。

    为什么要把带横杠的那种也认进来：业主 2026-10-26 说的"绝对编号"就是指名册里
    印出来的那个形（`t-000002`），而改前只认 `t000012` —— 于是"等 t-000002"会被
    当成一个名册名去查，然后以"查无此人"被拒。大写开头的（`T1`）仍按名册名走：
    编号一律小写 `t`，大写 `T1` 只可能是人起的名字。
    """
    if not text or text[0] != "t":
        return False
    body = text[1:]
    if body.startswith("-"):
        body = body[1:]
    return bool(body) and body.isdigit()


def parse_wait_for(value: Any) -> tuple[str, str]:
    """把 `wait_for` 的写法解析成 `(指称, 代号)`。解析失败 => `ClockParamError`。

    认这几种写法（业主 2026-10-26：「"等别人"必须要明确到等名册上的谁……或者等哪条程序」；
    名册名 / 绝对编号两种写法是业主 2026-10-25 那条「值形如名册名 / 绝对编号 /
    `task:<号>` / `agent:<名>`」的原文）：

    | 写法 | 指称 | 代号 |
    |---|---|---|
    | `task:t000012` | `task` | `t000012` |
    | `t000012`（绝对编号） | `task` | `t000012` |
    | `agent:D1` | `agent` | `D1` |
    | `D1`（名册名） | `agent` | `D1` |
    | `program:tm-000003` | `program` | `tm-000003` |
    | `tm-000003`（裸句柄号） | `program` | `tm-000003` |
    | `start_program(...)` 返回的 Timer 对象 | `program` | 它的 `timer_id` |

    为什么这里只解析不核实存在：核实要读台账/名册，那是工具层的事（本模块不拖 Store
    进来）。存在性由注册进来的探针答（`set_target_probe`），三态见 `TARGET_STATES`；
    程序那一条不需要探针 —— 它就在本模块的簿记里（`target_state` 的 `program` 分支）。

    散文（`别人` / `外部` / `等结果`）在这里会当"名册名"往下走，在核实处被拒
    （`ClockWaiterNotResolvable`，拒信由 `waiter_refusal()` 拼，给两条正路）：
    解析层不知道名册里有什么，它没有资格判"这个名字不存在"。
    """
    if not isinstance(value, str):
        handle = str(getattr(value, "timer_id", "") or "")
        if handle:
            # `clock.start_program(...)` 的返回值本身就是句柄：直接给对象也算点名叫到。
            return "program", handle
    text = str(value or "").strip()
    if not text:
        raise ClockParamError(
            "wait_for 是空串 —— 等谁必须点名（名册名 / 绝对编号 / task:<号> / "
            "agent:<名> / program:<程序句柄>）")
    low = text.lower()
    if low.startswith("task:"):
        kind, ref = "task", text[5:].strip()
    elif low.startswith("agent:"):
        kind, ref = "agent", text[6:].strip()
    elif low.startswith("program:"):
        kind, ref = "program", text[8:].strip()
    elif low.startswith("tm-"):
        # 程序计时器的句柄号（`start_program` 的 `timer_id`）：它只可能是程序那一条。
        kind, ref = "program", text
    elif _looks_like_task_id(text):
        kind, ref = "task", text
    else:
        kind, ref = "agent", text
    if not ref:
        raise ClockParamError(f"wait_for 只给了前缀没有点名：{value!r}")
    if len(ref) > 200:
        raise ClockParamError(f"wait_for 太长（{len(ref)} 字符）：它应该是一个名字或一个编号")
    if any(ch.isspace() for ch in ref):
        raise ClockParamError(f"wait_for 里不许有空白：{value!r}（名字/编号里没有空格）")
    return kind, ref


def _hhmmss(value: datetime | None) -> str:
    """时刻读数的 `HH:MM:SS`（本地时区；读不到 => 空串，不折成 00:00:00）。"""
    if value is None:
        return ""
    try:
        return value.astimezone().strftime("%H:%M:%S")
    except Exception:  # noqa: BLE001 - 显示不出来不该让到点失败
        return ""


def human_sec(seconds: float | None) -> str:
    """时长的人话读数：「20 分钟」/「45 秒」/「1 小时 5 分钟」。读不到 => 空串。"""
    if seconds is None:
        return ""
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return ""
    if total < 0:
        total = 0.0
    if total < 60:
        return f"{total:.0f} 秒"
    minutes, rem = divmod(int(round(total)), 60)
    if minutes < 60:
        return f"{minutes} 分钟" if rem == 0 else f"{minutes} 分钟 {rem} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分钟" if minutes else f"{hours} 小时"


#: 到点消息里"目的未填"那一格的逐字写法（业主定死；判据按它认出缺目的那一趟）。
PURPOSE_MISSING_TEXT: str = "（目的未填）"

#: 缺目的时的追问句（逐字；到点消息、工具读数、唤醒标记、每步提示词四处读同一份）。
#:
#: 补法里点两样：`entry_id` 是那件工具真正收的参数名（写 `timer_id=` 会让模型的补写调用
#: 受控失败），`timer_id` 是盘上那一格的键名（读的人按它去 `out/clock/state.json` 对得上）。
PURPOSE_PROMPT: str = (
    "你起的这一次等待还没写目的 —— 补一句目的（例如「等待20分钟+周期性巡查」），"
    "否则到点那条报醒里就没有目的可念；补法："
    "clock.timer_purpose(entry_id=<那一条的 timer_id>, purpose=…)")


def near_seconds(value: float | None) -> float | None:
    """保留给读数回显的小工具（秒 -> 秒，None 原样）。"""
    return None if value is None else float(value)


#: 已经退役的计时入口 -> 改用哪一件 clock 工具（业主 2026-10-25：
#: 「让老的未依赖时钟的计时工具退场」）。
#:
#: 这份表是"退场"的机器可读落点：一个名字只要出现在这里，`retire_hint` 就会说清
#: "它没了，改用谁"。今天它装的是从未作为工具存在过的那几个名字（`sleep` /
#: `wait` / `clock.timer` 一类），这样别人写出来时得到的是一句指路而不是
#: "未注册的工具"四个字。代理由工具面的普查判据认（`tests/test_clock_governs_all_timed_work.py`
#: 的第 16 条），不是一句声明。
RETIRED_TIMING_TOOLS: dict[str, str] = {
    "sleep": "clock.timer_start",
    "wait": "clock.timer_start",
    "wait_for": "clock.timer_start",
    "sleep_until": "clock.alarm_start",
    "clock.sleep": "clock.timer_start",
    "clock.wait": "clock.timer_start",
    "clock.delay": "clock.timer_start",
    "clock.timer": "clock.timer_start",
    "clock.set_timer": "clock.timer_start",
    "clock.sleep_until": "clock.alarm_start",
    "clock.remind": "clock.periodic_start",
    "clock.schedule": "clock.periodic_start",
    "clock.loop": "clock.periodic_start",
}


def retire_hint(name: Any) -> str:
    """这个名字退役了没有？退役了就说清"改用谁、为什么"。没退役 => 空串。"""
    key = str(name or "").strip()
    replacement = RETIRED_TIMING_TOOLS.get(key)
    if not replacement:
        return ""
    return (f"{key} 已经退役：计时只有主时钟这一处 —— 改用 {replacement}"
            f"（等待时间用 after_sec，等待谁用 wait_for，周期性用 clock.periodic_start）；"
            "到点后由时钟把消息发给收件人，不再由调用方自己睡")


# ---------------------------------------------------------------- 异常清单（巡查报醒）
#
# 业主 2026-10-26：「这个是M定期巡查需要特别注意的异常行为，M可通过发送指导意见干预」。
#
# 于是"巡查时间到"那句话不许只有目的 / 间隔 / 第几次：它还要带一份当拍现算的异常清单。
# 只叫醒而不告诉 M 要看什么，那一拍就只是闹钟；清单里四类的口径见 `patrol_text`。
#
# 分工与 `set_due_handler` / `set_target_probe` 同一条切法：本模块只负责"把清单拼进报醒"
# 这一半。清单里每一条事实（停滞 / 静默 / 未消板项 / 被拦的结项原因）都要读台账、板项
# 与名册，那是工具层的事，经 `set_patrol_probe` 接进来 —— 本模块不拖 Store 进来。

# 停滞那一段的阈值从哪来：读口给的那一格（`stalled` 里 `threshold_sec`）。本模块刻意不写
# 自己的 N —— 判据的真身在 `conductor.agent_state`（`STALLED_AFTER_SEC` 加
# `out/steps/<台账号>.json` 那一刻），报醒只负责把它的 `stalled_sec` 与阈值念出来。
# 两处各写一个 N 的代价很具体：同一个子在巡查里"停滞"、在页面读数里"没停滞"。

#: 四类都空时那一格的逐字写法（业主 2026-10-26：不许不写，不写就分不清"没有"与"没查"）。
PATROL_CLEAN_TEXT: str = "本轮无异常"

#: 干预指引那一句的逐字开头。判据按它认出"这一拍给了 M 一条可执行的下一步"。
PATROL_GUIDE_HEAD: str = "可发指导意见"

#: 轮查的间隔（业主 2026-10-27 傍晚定死的那一句里的「20分钟计时」）。
#:
#: 为什么它是一个常量而不是一个参数：业主给的是一个数（20 分钟），这个数的意义是
#: "M 多久必须看一次全树"。做成参数就会变成每个工作区各调一个值 ⇒ "轮查"在不同工作区
#: 里成了不同强度的动作，而没有任何判据读得出这个差别。
PATROL_INTERVAL_SEC: float = 1200.0

#: 轮查计时器写在目的那一格（`reason`／`purpose`）里的受控常量：这是"这一条是轮查"的
#: 唯一标记（判据 `is_patrol_timer` 只读这一格）。
#:
#: 为什么不用一个新的 `kind`：`TIMER_KINDS` 是落盘契约（`out/clock/state.json` 的每一行
#: 都带 `kind`，它还是 `Timer.__post_init__` 的校验输入）。加一档要同步四处：`_new_timer`
#: 的分支、`Timer` 的校验、`PeriodicShot` 的转换、以及工具面读数与快照里的分组；
#: 而轮查与一次性计时器在时间语义上没有一处不同（after_sec 到点即消耗、不自动重排）——
#: 唯一的差别是"到点那一下的正文"（SOP，见 `patrol_sop_text`）。把差别放在 `reason` 上
#: 恰好合适：目的那一格本来就是"这一条为什么存在"的唯一落点，而"轮查"就是它的目的。
PATROL_REASON: str = "轮查"

#: 轮查是主控的角色动作（值等于 `schema.CONDUCTOR_ROLE`）。
#:
#: 为什么这里写字面量而不是 `from .schema import CONDUCTOR_ROLE`：本模块的纪律是
#: "不为一个查询把 Store / schema 拖进来"（与 `set_target_probe` 逐字同一条理由）。
#: 两处一致由判据钉住：轮查那一份判据断言 `PATROL_ROLE == schema.CONDUCTOR_ROLE`，
#: 漂了当场红，而不是等某个工作区里"轮查怎么不挂"。
PATROL_ROLE: str = "M"

#: 轮查那一档到点消息的抬头（逐字；判据按它认出"这一条是轮查的报醒"）。
#:
#: 为什么不沿用 `时间到：` / `巡查时间到：`：那两个前缀在业主口径里正是"只报一句到点了"
#: 的形态，而轮查的正文是一套要执行的动作（见 `patrol_sop_text`）。换抬头不是换格式，
#: 是为了让读的人（和人写的判据）一眼分得出"提醒"与"规范动作"。
PATROL_DUE_HEAD: str = "轮查到点："

#: 异常清单的读口：`probe(workspace, task_id) -> dict`。
#:
#: 键集见 `patrol_anomalies`；三态由它自己的 `checked` / `reason` 给。工具层在装配期
#: 用 `set_patrol_probe` 把它接上（与 `set_due_handler` 同一处：`clock_tools.register`）。
_PATROL_PROBE: Callable[[str, str], Mapping[str, Any]] | None = None


def set_patrol_probe(probe: Callable[[str, str], Mapping[str, Any]] | None
                     ) -> Callable[[str, str], Mapping[str, Any]] | None:
    """接上"当拍现算的异常清单"读口，返回被替换掉的那一个。

    签名是 `probe(workspace, task_id) -> dict`，必须回这五格：

    - `checked`：这一次查成没查成（读不成台账 / 没有主控实例 => False）；
    - `reason`：没查成的理由（读数要能读出"为什么这一拍没有清单"）；
    - `at`：当拍时刻（ISO；读不到时钟就是空串）；
    - `stalled` / `silent` / `open_items` / `refusals`：四类各一格，每格是
      `{"checked", "count", "rows", "reason"}`（`open_items` 另带 `ack` / `work`）。

    为什么放在工具层：这四类要读台账、板项与名册，而本模块的纪律是"能被判据单独喂假时钟、
    单独检查读数"，不为一个查询把 Store 拖进来（与 `set_target_probe` 逐字同一条理由）。
    """
    global _PATROL_PROBE
    previous = _PATROL_PROBE
    _PATROL_PROBE = probe
    return previous


def _patrol_cell(blank: Mapping[str, Any], raw: Any, *, name: str) -> dict[str, Any]:
    """把读口给的一格规整成 `{checked, count, rows, reason}`（缺格 => 没查成，不是 0）。

    缺格折成 0 会把"这一格没读"读成"这一类没有" —— 那正好是这一批要分开的那两件事。
    """
    if not isinstance(raw, Mapping):
        return {**dict(blank), "checked": False,
                "reason": f"读口没给 {name} 那一格 => 这一类没查成"}
    cell = {**dict(blank), **dict(raw)}
    cell["rows"] = [dict(r) for r in (cell.get("rows") or ()) if isinstance(r, Mapping)]
    if cell.get("count") is None and bool(cell.get("checked", True)):
        cell["count"] = len(cell["rows"])
    return cell


def patrol_anomalies(workspace: str | Path, *, task_id: str = "") -> dict[str, Any]:
    """当拍现算的异常清单（唯一入口；读口由工具层在装配期接上）。

    返回的键集固定（判据与 `patrol_text` 都按它读）：

    ```
    {"checked", "reason", "at", "task_id",
     "stalled":     {"checked", "count", "rows", "reason"},
     "silent":      {...},
     "open_items":  {"checked", "count", "ack", "work", "rows", "reason"},
     "refusals":    {...}}
    ```

    三态：`checked=False` 加 `reason` 就是"这一拍没查成"（读口没接 / 读口抛了 / 读口说
    没查成）。这一档绝不退回"四类都是 0"：那会把"没查"折成"没有"，而这一拍的全部价值
    正好在分得开这两件事。同理，某一格没给出来时那一类单独记"没查成"（`_patrol_cell`），
    其余三类照常报。

    为什么它是唯一入口：反真空判据要把"异常清单这一步"打桩成返回空，而在别处再算一份
    清单就没有那个桩可打 —— 桩打不到，判据证明的只是"打桩坏了"。
    """
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    blank: dict[str, Any] = {"checked": False, "count": None, "reason": "", "rows": []}
    out: dict[str, Any] = {"checked": False, "reason": "", "at": stamp,
                           "task_id": str(task_id or ""),
                           "stalled": dict(blank), "silent": dict(blank),
                           "open_items": {**blank, "ack": None, "work": None},
                           "refusals": dict(blank)}
    probe = _PATROL_PROBE
    if probe is None:
        out["reason"] = "没有接上异常清单的读口（set_patrol_probe 还没接）=> 这一拍没查成"
        return out
    try:
        got = dict(probe(str(Path(workspace).resolve()), str(task_id or "")) or {})
    except Exception as exc:  # noqa: BLE001 - 读口炸了是"没查成"，不是"没有异常"
        out["reason"] = f"异常清单读口抛了 {type(exc).__name__}: {exc}"
        return out
    if not got.get("checked"):
        out["reason"] = str(got.get("reason") or "读口说这一次没查成（没给理由）")
        return out
    out["checked"] = True
    out["at"] = str(got.get("at") or stamp)
    out["stalled"] = _patrol_cell(blank, got.get("stalled"), name="stalled")
    out["silent"] = _patrol_cell(blank, got.get("silent"), name="silent")
    out["refusals"] = _patrol_cell(blank, got.get("refusals"), name="refusals")
    items = _patrol_cell({**blank, "ack": None, "work": None},
                         got.get("open_items"), name="open_items")
    out["open_items"] = items
    return out


def _patrol_ids(cell: Mapping[str, Any]) -> list[str]:
    """一格里的绝对编号（去重、保序）。"""
    out: list[str] = []
    for row in cell.get("rows") or ():
        tid = str((row or {}).get("task_id") or "")
        if tid and tid not in out:
            out.append(tid)
    return out


def _first_sentence(text: Any, *, limit: int = 160) -> str:
    """一句话的首句（拒信要的是"首句"，不是整段）。空 => 空串。"""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    for mark in ("。", "；", "！"):
        head = body.split(mark, 1)[0]
        if head:
            body = head
            break
    return body[:limit]


def patrol_text(anomalies: Mapping[str, Any]) -> str:
    """把一份异常读数拼成报醒里那一段（唯一一份拼法）。

    四类各占一句，每句都带"条数"两个字（判据按它认出"这一类查过了"）：

        ① 停滞子：`status=running` 而超过阈值没有新步（点名绝对编号 + stalled_sec）
        ② 静默未销号的子：无工作、无计时器、无活跃子，却不是 retired（给销号指路）
        ③ 未消板项：`item_state != done` 的条数，按 expect 分 ack / work
        ④ 被拦的结项原因：最近一次 final_refused / 板项闸的拒信首句

    四类都空 => 末尾逐字写 `本轮无异常`。有异常子（① / ② 非空）=> 末尾给一句可执行的
    干预指引，并点名那个子的绝对编号（业主：「M可通过发送指导意见干预」）。
    某一类读不到 => 那一类写"条数读不到（理由）"，不许折成 0。
    """
    cells = {key: (anomalies.get(key) if isinstance(anomalies.get(key), Mapping) else {})
             for key in ("stalled", "silent", "open_items", "refusals")}

    def _count_of(cell: Mapping[str, Any], label: str) -> str:
        if not cell.get("checked", True) or cell.get("count") is None:
            return f"{label} 条数读不到（{str(cell.get('reason') or '没查成')}）"
        return f"{label} 条数 {int(cell.get('count') or 0)}"

    stalled = cells["stalled"]
    silent = cells["silent"]
    items = cells["open_items"]
    refusals = cells["refusals"]

    bits: list[str] = []
    if not stalled.get("checked", True) or stalled.get("count") is None:
        bits.append(_count_of(stalled, "① 停滞子"))
    elif int(stalled.get("count") or 0):
        threshold = stalled.get("threshold_sec")
        named = "、".join(
            f"{str(r.get('task_id') or '?')}（{str(r.get('role') or '?')}"
            f"，stalled_sec={int(float(r.get('stalled_sec') or 0))}"
            + (f"，阈值 {int(threshold)} 秒" if threshold else "")
            + (f"，最近一步在 {str(r.get('last_step_at') or '')}" if r.get("last_step_at") else "")
            + "）"
            for r in (stalled.get("rows") or ()))
        bits.append(f"① 停滞子 条数 {int(stalled['count'])}：{named}")
    else:
        bits.append("① 停滞子 条数 0")

    if not silent.get("checked", True) or silent.get("count") is None:
        bits.append(_count_of(silent, "② 静默未销号的子"))
    elif int(silent.get("count") or 0):
        named = "、".join(
            f"{str(r.get('task_id') or '?')}（{str(r.get('role') or '?')}"
            f"，{str(r.get('why') or '无工作、无计时器、无活跃子，却还在册')}；"
            "要销号它吗 —— 走 conductor.retire_child）"
            for r in (silent.get("rows") or ()))
        bits.append(f"② 静默未销号的子 条数 {int(silent['count'])}：{named}")
    else:
        bits.append("② 静默未销号的子 条数 0")

    if not items.get("checked", True) or items.get("count") is None:
        bits.append(_count_of(items, "③ 未消板项"))
    else:
        ack = int(items.get("ack") or 0)
        work = int(items.get("work") or 0)
        other = items.get("other")
        other = (int(other) if other is not None
                 else max(0, int(items["count"]) - ack - work))
        extra = f" / 未标 expect {other}" if other else ""
        line = (f"③ 未消板项 条数 {int(items['count'])}"
                f"（待 ack {ack} / 待 work {work}{extra}）")
        ids = _patrol_ids(items)
        bits.append(f"{line}：{'、'.join(ids)}" if ids else line)

    if not refusals.get("checked", True) or refusals.get("count") is None:
        bits.append(_count_of(refusals, "④ 被拦的结项原因"))
    elif int(refusals.get("count") or 0):
        rows = list(refusals.get("rows") or ())
        head = rows[0] if rows else {}
        text = _first_sentence(head.get("text"))
        kind = str(head.get("kind") or "final_refused")
        where = f"（{kind}" + (f"，{str(head.get('at') or '')}" if head.get("at") else "") + "）"
        bits.append(f"④ 被拦的结项原因 条数 {int(refusals['count'])}（最近一条）："
                    f"{text or '读不到拒信原文'}{where}")
    else:
        bits.append("④ 被拦的结项原因 条数 0")

    at = str(anomalies.get("at") or "")
    head = f"异常清单（当拍现算 {at or '时刻读不到'}）："
    all_checked = all(bool(cells[k].get("checked", True)) for k in cells)
    has_any = any(int(cells[k].get("count") or 0) for k in cells if cells[k].get("checked", True))
    if all_checked and not has_any:
        return f"{head}{'；'.join(bits)} => {PATROL_CLEAN_TEXT}"

    body = f"{head}{'；'.join(bits)}"
    targets = _patrol_ids(stalled) + [t for t in _patrol_ids(silent) if t not in _patrol_ids(stalled)]
    if targets:
        body = (f"{body}。干预指引：{PATROL_GUIDE_HEAD}给上面点名的那个子 —— 走既有的名册"
                f"寻址（名册名或绝对编号都行）与秘书链：用 message 到 {'、'.join(targets)}，"
                "正文只到链尾；发过之后它的下一步应该变：再读 conductor.tree / clock.now 时，"
                "上面点名那个子的步号要比现在大、或它的 status 转成终态；两样都没变就是没送到"
                "或它没听，再发一次，或按 ② 的指路把它销号")
    elif has_any:
        body = (f"{body}。处置指路：③ 的项逐条用 conductor.ack 确认（板项闸认的是"
                "item_state=done），④ 那一句就是下一次 final 会被拦的原因，先把整棵树销号"
                "再收工；这一拍没有异常子，所以不点名任何子")
    return body


def patrol_section(workspace: str | Path, *, task_id: str = "",
                   anomalies: Mapping[str, Any] | None = None) -> str:
    """这一拍报醒里要附的那一段（清单没查成 => 明说没查成，绝不写"本轮无异常"）。

    `anomalies` 给了就直接用（调用方刚算过一份，别为了拼文本再读一遍会话/台账）。

    两处 try 是同一个理由：这一段的任何失败都不许把"到点报醒"本身带走 —— 那一拍是
    M 唯一会醒来的凭据，清单坏掉只该少一段文字，不该少一次唤醒。
    """
    try:
        got = dict(anomalies) if isinstance(anomalies, Mapping) else \
            patrol_anomalies(workspace, task_id=task_id)
    except Exception as exc:  # noqa: BLE001 - 清单算不出来是"没查成"
        got = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not got.get("checked"):
        # 逐字不出现「本轮无异常」：那一句是"四类都空"的专用读数，这里能 grep 到它
        # 就等于把"没查成"伪装成了"没有异常"（而"没有"与"没查"正是要分开的那两件事）。
        return (f"异常清单没查成（{str(got.get('reason') or '读口没给理由')}）"
                " => 这一拍没有清单可报（没查到与没有是两件事）")
    try:
        return patrol_text(got)
    except Exception as exc:  # noqa: BLE001 - 拼不出来也不许吞掉这次唤醒
        return f"异常清单拼不出来（{type(exc).__name__}: {exc}）=> 这一拍没有清单可报"


# ------------------------------------------------------- 轮查：一个特殊计时器 + 一套动作
#
# 业主 2026-10-27 傍晚（唯一权威，逐字）：
#
#     「20分钟计时 -> 时间到立刻进自动审阅工具 -> 审完后 M 自由行动 -> M 无事可做后
#       启动轮查计时。注意：20分钟间隔内接收到任何其它消息 M 一样会被唤醒（这与计时器
#       不阻塞进程的设计一致，轮查也不阻塞进程，轮查只是个特殊计时器，到点后不是返回
#       一句提醒，而是一套需执行的规范动作）」
#
# 两半各落在哪：特殊计时器这一半是 `start_patrol_timer` / `next_patrol` /
# `is_patrol_timer`（本节），"到点那一下的正文是 SOP"这一半是 `patrol_sop_text`
# 与 `due_message` 的 `patrol_sop` 那一格。异常清单那一半不在这里另写 —— 它仍然只有
# `patrol_section` 一份（周期性巡查早就用它，轮查这一条读同一个落点）。


def patrol_sop_text(*, interval_sec: float | None = PATROL_INTERVAL_SEC) -> str:
    """轮查到点那一刻的正文：一套现在就要执行的规范动作（不是"时间到了"这种提醒句）。

    为什么正文必须是 SOP：业主给的那一句里说得最重的是最后半句 ——「到点后不是返回一句
    提醒，而是一套需执行的规范动作」。一句"时间到了"只告诉 M 一个它已经知道的事实
    （它在 20 分钟前自己挂的表到点了），而 M 缺的是"接下来做什么"；那件事今天已经有工具
    了（`conductor.patrol` / `conductor.patrol_verdict`，L1 落的三件），所以正文的任务是
    把工具按顺序摆到它面前，四步一步不少：

    ① 立刻调 `conductor.patrol`（一次拿全，不逐个 `review_child` 地去翻）；
    ② 对每一个活跃子代理给结论：`pass`（过）或 `guide`（指导意见）；
    ③ 结完这一轮，才允许做别的（自由行动）；
    ④ 无事可做（要挂机等）时，挂上下一个轮查计时器。

    第 ④ 步为什么还留在正文里、而框架其实会自动挂（`agent_loop._park_gate` 那一侧）：
    这一句是给 M 的"不要手工再起一条"的交代 —— 挂点那一侧保证的是"恰好一条"，模型读了
    SOP 又自己 `clock.timer_start(after_sec=1200, reason="轮查")` 一次，就变成两条、
    两个 20 分钟的报醒错开半分钟，而"轮查"这件事按定义同一时刻只有一条在跑。

    `interval_sec` 只用于正文里念间隔，不改任何计时行为（间隔的真身是
    `PATROL_INTERVAL_SEC`，挂表那一处读的就是它）。

    判据的"反真空"要能把它换成空串：`fire_due` 按名字调本函数（模块级），
    打桩之后到点那条正文里四步必须一句不剩 —— 于是"正文里真有 SOP"这件事是机器证明的，
    不是读代码读出来的。
    """
    every = human_sec(interval_sec if interval_sec is not None else PATROL_INTERVAL_SEC)
    return (
        f"【轮查】这是规范动作，不是提醒：按下面四步做完再干别的（每 {every}一次）。\n"
        "① 立刻调 conductor.patrol：一次拿全活跃子代理（在飞 / 待机）、名册绝对编码链、"
        "正在执行的任务、未做完的板项与现在在做哪项、计时器四格。\n"
        "② 对每一个活跃子代理给结论：conductor.patrol_verdict(code, \"pass\") 说「过」，"
        "或 conductor.patrol_verdict(code, \"guide\", text) 给指导意见"
        "（guide 走既有秘书链，正文只到链尾）；那一轮里漏掉任何一个活跃号都算没做完。\n"
        "③ 结完这一轮，才允许做别的（自由行动）。\n"
        "④ 无事可做（要挂机等）时，挂上下一个轮查计时器：框架在挂机那一下自动挂好"
        "（reason 是「轮查」的那一条），不要再手工起第二条。"
    )


def is_patrol_timer(entry: Any) -> bool:
    """这一条是不是轮查计时器（只读目的那一格）。

    收三种输入：`Timer`、盘上那一行、`record_wake` 落的唤醒事件 —— 三者都经
    `purpose_of` 取值，于是"哪一条是轮查"全仓只有一个读法（与 `purpose_of` 同一条纪律：
    各写一份取法迟早分家，而分家之后没有任何判据会红）。

    `kind` 刻意不参与判定：轮查复用 `kind="timer"`，理由见 `PATROL_REASON`。
    """
    return purpose_of(entry).strip() == PATROL_REASON


def next_patrol(workspace: str | Path) -> dict[str, Any]:
    """下一条还没到的轮查计时器（三态）。

    返回 `{"checked","pending","count","timer_id","due_at","remaining_sec","reason"}`。
    `pending=False` 是"查过了、现在没有轮查计时器"，`checked=False` 是"没查成"——
    挂下一轮那一处按前者决定"该挂"，后者只记一句"不知道"，两者不许折平。

    为什么要有这一格读数（两个读者，一处实现）：

    1. 挂点（`agent_loop._park_gate`）每一拍都要问"已经有一条了吗"；
    2. 挂机的一拍还要用它把睡眠封顶在轮查到点那一刻 —— 业主的口径是"时间到立刻进
       自动审阅工具"，而挂机的一拍最长 `PARK_SLICE_MAX_SEC`（300 秒），不封顶就会
       把"立刻"读成"最多晚 5 分钟"。
    """
    out: dict[str, Any] = {"checked": False, "pending": False, "count": 0, "timer_id": "",
                           "due_at": "", "remaining_sec": None, "reason": ""}
    try:
        rows = [t for t in book(workspace).pending() if is_patrol_timer(t)]
    except (ClockStateError, OSError) as exc:
        out["reason"] = f"计时器簿记读不成：{type(exc).__name__}: {exc}"
        return out
    out["checked"] = True
    out["count"] = len(rows)
    if not rows:
        return out
    rows.sort(key=lambda t: (str(t.due_at or ""), str(t.timer_id or "")))
    head = rows[0]
    out.update(pending=True, timer_id=str(head.timer_id or ""),
               due_at=str(head.due_at or ""), remaining_sec=head.remaining_seconds(now()))
    return out


def start_patrol_timer(workspace: str | Path, *, task_id: str = "", role: str = "",
                       to: str = "self") -> dict[str, Any]:
    """挂下一轮轮查计时器 —— 恰好一条（业主 2026-10-27 傍晚：「无事可做后启动轮查计时」）。

    两条规则，缺一条就会出两种相反的错：

    1. 只有主控（`PATROL_ROLE`）才挂：轮查要执行的动作是 `conductor.patrol` /
       `conductor.patrol_verdict`，那两件只有 M 有；子代理挂一条自己的"轮查"表既没有
       可执行的动作，又会把"无事可做"这个读数搅浑（它会永远有一条计时器在跑）；
    2. 已经有一条 pending 的轮查计时器就不再挂：挂点每一拍都会经过
       （`_park_gate` 的第 ①/④ 两支），不判重的话一分钟能挂出几十条，而"轮查"这件事
       按定义同一时刻只有一条在跑。

    返回 `{"checked","mounted","skipped","timer_id","interval_sec","remaining_sec","reason"}`。
    `mounted=False` 时 `skipped` 说清为什么（`role` / `already` / `unreadable` / `error`）：
    读数要能把"没挂"与"不该挂"分开，否则挂点那一侧只能把三件事写成一句话。

    三态：时钟读不到时 `start_timer` 抛 `ClockUnreadable`，这里折成 `checked=False`
    （不是"已经有一条"）—— 挂点据此知道"这一拍不知道"，下一拍还会再问一次。
    """
    out: dict[str, Any] = {"checked": False, "mounted": False, "skipped": "",
                           "timer_id": "", "interval_sec": float(PATROL_INTERVAL_SEC),
                           "remaining_sec": None, "reason": ""}
    who = str(role or "").strip()
    if who != PATROL_ROLE:
        out.update(checked=True, skipped="role",
                   reason=(f"轮查计时器只挂给主控（{PATROL_ROLE}）："
                           f"这一趟是 {who or '（没有角色）'} ⇒ 不挂"))
        return out
    known = next_patrol(workspace)
    if not known.get("checked"):
        out.update(checked=False, skipped="unreadable",
                   reason=str(known.get("reason") or "计时器簿记读不成 ⇒ 不知道有没有"))
        return out
    if known.get("pending"):
        out.update(checked=True, skipped="already",
                   timer_id=str(known.get("timer_id") or ""),
                   remaining_sec=known.get("remaining_sec"),
                   reason=(f"已经有一条 pending 的轮查计时器 {known.get('timer_id')}"
                           f"（还剩 {human_sec(known.get('remaining_sec')) or '读不到'}）"
                           "⇒ 不再挂第二条"))
        return out
    try:
        timer = start_timer(workspace, reason=PATROL_REASON, after_sec=PATROL_INTERVAL_SEC,
                            to=str(to or "self"), task_id=str(task_id or ""), role=who)
    except ClockUnreadable as exc:
        out.update(checked=False, skipped="unreadable", reason=str(exc))
        return out
    except ClockError as exc:  # 参数/簿记坏掉：照实报，不假装挂上了
        out.update(checked=False, skipped="error",
                   reason=f"{type(exc).__name__}: {exc}")
        return out
    out.update(checked=True, mounted=True, timer_id=str(timer.timer_id or ""),
               remaining_sec=timer.remaining_seconds(now()),
               reason=(f"挂上了下一条轮查计时器 {timer.timer_id}"
                       f"（每 {human_sec(PATROL_INTERVAL_SEC)}一次）"))
    return out


def due_message(*, purpose: str, waited_sec: float | None, created_at: Any,
                fired_at: Any, every_sec: float | None = None,
                fires: int | None = None, feedback: str = "",
                feedback_label: str = "", waited_target: str = "",
                woke_reason: str = "", patrol_section: str = "",
                patrol_sop: str = "") -> str:
    """到点那条消息的唯一拼法（业主 2026-10-25 定死格式）。

    一次性：

        时间到：<目的>｜等了 <时长>（起于 <HH:MM:SS>，到于 <HH:MM:SS>）

    周期性：

        巡查时间到：<目的>｜每 <间隔>一次（第 <N> 次）

    等谁的再加两样：等到了对方的事件就把它的反馈抄在后面（`feedback`），到点还没
    等到就写清"等的是 X，它还没交/没说"。缺目的那一趟把目的位置写成
    `（目的未填）` 并追问补一句。

    三样（目的 / 等待时间 / 时间到）必须在同一句里 —— 判据断言的是这句原文。

    周期性巡查那一档还多一段：`patrol_section`（当拍现算的异常清单 + 干预指引，唯一的
    拼法是 `patrol_text`）。它在末尾另起一句，不改上面三样的任何一个字节；空串 => 输出与
    没有这一格时完全一样（判据的"改前红"就靠这一条成立）。

    ## 轮查那一档（`patrol_sop` 非空；业主 2026-10-27 傍晚）

    正文 = 那一套要执行的动作（`patrol_sop_text` 的四步），不是"到点了"这种提醒句。
    抬头换成 `轮查到点：` 而不是 `时间到：` / `巡查时间到：`：后两个前缀的语义是
    "只有这一句"，而轮查要的恰好是相反的形态（一句抬头 + 四步 + 异常清单）。
    三样（目的 / 等待时长 / 到于何时）一个字节都没丢 —— 它们是"这是哪条表、等了多久"的
    唯一凭据，丢掉就分不清这一拍是 20 分钟前挂的那条还是刚补挂的。
    `patrol_section` 照旧在最后一段（轮查与周期性巡查共用同一份清单，不另写第二份）。
    `patrol_sop` 是空串时，本函数的输出与没有这一格时逐字相同（反真空判据要的就是这一条：
    把正文换成空串，四步必须一句不剩）。
    """
    body = str(purpose or "").strip()
    missing = not body
    shown = PURPOSE_MISSING_TEXT if missing else body
    section = str(patrol_section or "").strip()
    sop = str(patrol_sop or "").strip()
    start = _hhmmss(created_at if isinstance(created_at, datetime)
                    else (_parse_iso(created_at) if created_at else None))
    end = _hhmmss(fired_at if isinstance(fired_at, datetime)
                  else (_parse_iso(fired_at) if fired_at else None))
    if sop:
        # 轮查那一档（唯一例外，业主 2026-10-27 傍晚）：正文 = 一套要执行的动作，
        # 不是"到点了"这种提醒句。抬头仍然带齐三样（目的 / 等待时长 / 到于何时），
        # 因为那三样是"这一条表是哪一条、等了多久"的唯一凭据；措辞刻意不用
        # `时间到：` / `巡查时间到：` 这两个前缀 —— 它们是"只有这一句"的形态。
        head = (f"{PATROL_DUE_HEAD}{shown}｜等了 {human_sec(waited_sec)}"
                f"（起于 {start or '读不到'}，到于 {end or '读不到'}）")
        said = f"{head}\n{sop}"
        if missing:
            said = f"{said}\n{PURPOSE_PROMPT}"
        return f"{said}\n{section}" if section else said
    if every_sec is not None:
        head = f"巡查时间到：{shown}｜每 {human_sec(every_sec)}一次（第 {int(fires or 0)} 次）"
    else:
        head = (f"时间到：{shown}｜等了 {human_sec(waited_sec)}"
                f"（起于 {start or '读不到'}，到于 {end or '读不到'}）")
    tail = ""
    prose = str(feedback or "").strip()
    if prose:
        label = str(feedback_label or "它的话")
        tail = f"。{label}：{prose[:EVENT_EXCERPT]}"
    elif str(woke_reason or "") == "timeout" and str(waited_target or "").strip():
        tail = (f"。等的是 {str(waited_target).strip()}，它还没交/没说"
                "（到点先报你，接着等就再起一条）")
    if missing:
        said = f"{head}{tail}。{PURPOSE_PROMPT}"
    else:
        said = f"{head}{tail}"
    if section:
        # 分隔符按前一句的收尾挑：已经有句末标点就不再补一个"。"。
        sep = "" if said.endswith(("。", "；", "：")) else "。"
        return f"{said}{sep}{section}"
    return said


# ---------------------------------------------------------------- 时钟实现


class RealClock:
    """真时钟：墙钟走 `time.time()`，单调计数走 `time.monotonic()`。

    这两个调用是全仓库仅有的直接取时点；业务代码一律经 `clock.now()`。
    本类的两个 try 是分开的：一个来源坏掉不该把另一个也判成坏（partial 状态
    存在的理由）。
    """

    name = "real"

    def __init__(self) -> None:
        #: 进程令牌：单调计数只在同一个 token 里可比（见模块 docstring 的重启一节）。
        self.token: str = uuid.uuid4().hex

    def read(self) -> Reading:
        wall: datetime | None = None
        monotonic: float | None = None
        reasons: list[str] = []
        try:
            wall = datetime.fromtimestamp(time.time(), tz=UTC)
        except Exception as exc:  # noqa: BLE001 - 读不到是 unknown，不是 1970
            reasons.append(f"墙钟读不到：{type(exc).__name__}: {exc}")
        try:
            monotonic = float(time.monotonic())
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"单调计数读不到：{type(exc).__name__}: {exc}")
        return _reading(wall, monotonic, reasons)


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


#: 进程内唯一的时钟。判据用 `use(...)` 换掉它，生产里从不换。
_CLOCK: Any = RealClock()

#: 工作区 -> 计时器簿记。键是解析后的绝对路径（一个工作区一份，不是全局一份）。
_BOOKS: dict[str, "TimerBook"] = {}

#: 到点动作的注册点。工具层注册；没注册时到点的计时器保持 pending（DueDeferred）。
_DUE_HANDLER: Callable[["Timer"], Mapping[str, Any]] | None = None

#: 进程启动那一刻的读数（`clock.now` 的"这一趟跑了多久"在台账里没有 started_at 时
#: 的兜底）。它也是经同一个读数口取的。
_PROCESS_START: Reading = _CLOCK.read()


def current() -> Any:
    """当前时钟对象（真时钟或假时钟）。"""
    return _CLOCK


def use(clock: Any) -> Any:
    """装上另一个时钟（判据用）。返回装上去的那个。"""
    global _CLOCK
    if clock is None:
        clock = RealClock()
    if not callable(getattr(clock, "read", None)):
        raise ClockParamError(f"{type(clock).__name__} 没有 read()，不是时钟")
    _CLOCK = clock
    return clock


def reset() -> None:
    """恢复真时钟并清掉进程内的计时器簿记（判据之间的隔离点）。"""
    global _CLOCK, _PROCESS_START, _DEFAULT_WORKSPACE
    _CLOCK = RealClock()
    _PROCESS_START = _CLOCK.read()
    _BOOKS.clear()
    _DEFAULT_WORKSPACE = ""
    reset_programs()


def reset_books() -> None:
    """只清进程内簿记，不换时钟（模拟重启：盘上的状态仍然在）。"""
    _BOOKS.clear()


def now() -> Reading:
    """唯一取时口。业务代码只许走这里，不许自己调 `time.time()`。"""
    return _CLOCK.read()


def advance(seconds: float) -> Reading:
    """当前时钟若是假时钟就前进；真时钟没有"前进"这个动作。

    判据里更常见的写法是 `fake = FakeClock(...); use(fake); fake.advance(30)`；
    这个模块级别名只是为了少写一个变量名，语义与 `FakeClock.advance` 逐字相同
    （推进之后同样会跑一次 `fire_due()`）。
    """
    step = getattr(_CLOCK, "advance", None)
    if not callable(step):
        raise ClockParamError(
            f"当前时钟是 {type(_CLOCK).__name__}，没有 advance() —— 只有假时钟能前进")
    return step(seconds)


def state_path(workspace: str | Path) -> Path:
    """计时器状态的落盘路径（`<工作区>/out/clock/state.json`）。"""
    return Path(workspace).resolve() / STATE_REL


def process_started() -> Reading:
    """本进程启动那一刻的读数（`clock.now` 的 elapsed 兜底）。"""
    return _PROCESS_START


def set_due_handler(handler: Callable[["Timer"], Mapping[str, Any]] | None):
    """注册到点动作，返回上一个。工具层用它在 import/装配期接上。

    到点动作的签名是 `handler(timer) -> dict`，返回值里请带 `mailbox_item_id`
    与 `wake_id`（`fire_due` 把它们原样记进计时器的 `note`/落盘字段，供审计）。
    """
    global _DUE_HANDLER
    previous = _DUE_HANDLER
    _DUE_HANDLER = handler
    return previous


#: "等谁"的读口。工具层在装配期把"台账/名册里这个东西收口了没有"接上。
#:
#: 为什么不在这里直接读 Store / 名册：本模块的纪律是"能被判据单独喂假时钟、单独检查
#: 读数"，不该为了一个查询把 Store 拖进来（与 `set_due_handler` 同一条切法）。
_TARGET_PROBE: Callable[[str, str, str], Mapping[str, Any]] | None = None


def set_target_probe(probe: Callable[[str, str, str], Mapping[str, Any]] | None):
    """接上"等谁"的读口，返回上一个。

    读口的签名是 `probe(workspace, kind, ref) -> dict`，必须回这五格（三态不许折平）：

    - `checked`：这次查成没查成（没有台账/读不成 => False）；
    - `found`：台账/名册里有没有这个东西；
    - `closed`：它收口了没有（`found` 为假时无意义）；
    - `resolved`：解析成的具体对象（`task:t000012` / `agent:D1`），起表时落进台账；
    - `why`：没查成 / 没找到 / 还在跑的理由（读数要能读出"为什么还没到"）。
    """
    global _TARGET_PROBE
    previous = _TARGET_PROBE
    _TARGET_PROBE = probe
    return previous


def _probe_read(workspace: str | Path, kind: str, ref: str) -> dict[str, Any]:
    """问一次"等谁"的读口，把结果规整成五格（三态都在里面）。"""
    probe = _TARGET_PROBE
    if probe is None:
        return {"checked": False, "found": False, "closed": False,
                "resolved": f"{kind}:{ref}",
                "why": "没有接上'等谁'的读口（set_target_probe 还没接）=> 判不了它收口了没有"}
    try:
        got = dict(probe(str(Path(workspace).resolve()), str(kind), str(ref)) or {})
    except Exception as exc:  # noqa: BLE001 - 读口炸了是"没查成"，不是"没到"
        return {"checked": False, "found": False, "closed": False,
                "resolved": f"{kind}:{ref}",
                "why": f"读口抛了 {type(exc).__name__}: {exc}"}
    got.setdefault("resolved", f"{kind}:{ref}")
    got.setdefault("why", "")
    got.setdefault("checked", False)
    got.setdefault("found", False)
    got.setdefault("closed", False)
    #: 被等对象那一行的 task 原文（业主 2026-10-27：等子代理的目的自动用它填）。
    #: 读口拿不到就是空串 —— 空串只表示"这一格没有可用的原文"，不表示"它没有 task"。
    got.setdefault("task_text", "")
    return got


def _judge_target(got: Mapping[str, Any], kind: str, ref: str) -> tuple[str, str, str]:
    """把读口的五格折成 `(三态之一, 解析成的对象, 理由)`。折法见 `target_state`。"""
    resolved = str(got.get("resolved") or f"{kind}:{ref}")
    why = str(got.get("why") or "")
    if not got.get("checked"):
        return ("unjudgeable", resolved, why or "读口说这次没查成")
    if not got.get("found"):
        return ("closed", resolved,
                f"被等对象已不在台账/名册里（{why or '查过了、没有这一行'}）=> 按收口处置")
    if got.get("closed"):
        return ("closed", resolved, why or "它收口了")
    return ("open", resolved, why or "它还在跑")


def target_state(workspace: str | Path, kind: str, ref: str) -> tuple[str, str, str]:
    """问一次"被等的东西收口了没有"。返回 `(三态之一, 解析成的对象, 理由)`。

    三态（`TARGET_STATES`）：

    - `closed`：它收口了（或它在台账里已经消失了 —— 收口是唯一不挂死的解释，
      理由串里会逐字写明"台账里已经没有这一行"）；
    - `open`：还在，还没收口；
    - `unjudgeable`：没查成（没接读口 / 读口抛了 / 读口说 checked=False）。
      这一档绝不许折成 `open` 或 `closed`：折成 open 会让父永远不知道等到了没有，
      折成 closed 会让它以为等到了。这一档下计时器保持 pending，读数里带理由。
    """
    if kind not in WAIT_FOR_KINDS:
        raise ClockParamError(f"wait_for 的指称只认 {WAIT_FOR_KINDS}，收到 {kind!r}")
    if kind == "program":
        # 程序那一条不需要探针：它就在本模块的簿记里（`state` 变了就是"程序结束了"）。
        # 三态同族：簿记读不成 => `unjudgeable`（不是"程序还在跑"）。
        try:
            bucket = book(workspace)
        except ClockError as exc:
            return ("unjudgeable", f"program:{ref}",
                    f"时钟簿记读不成（{exc}）=> 判不了那条程序跑完没有")
        timer = bucket.get(str(ref))
        if timer is None:
            # 簿记里没有那一条：与"台账里已经没有这一行"同一口径（收口是唯一不挂死的解释）。
            return ("closed", f"program:{ref}",
                    f"程序计时器 {ref} 不在簿记里 ⇒ 按收口处置")
        if timer.kind != "program":
            return ("unjudgeable", f"program:{ref}",
                    f"{ref} 存在，但它是 kind={timer.kind!r} 而不是 program ⇒ 等错了东西")
        if str(timer.state) == "pending":
            return ("open", f"program:{ref}",
                    f"程序 {timer.program or ref} 还在跑（{timer.timer_id}）")
        return ("closed", f"program:{ref}",
                f"程序 {timer.program or ref} 结束了（{timer.outcome or timer.state}）")
    return _judge_target(_probe_read(workspace, kind, ref), kind, ref)


# ---------------------------------------------------------------- 计时器


@dataclass
class Timer:
    """一条计时器/闹钟。`kind` 只区分 due 是怎么算出来的，数据结构是同一份。"""

    timer_id: str
    kind: str
    reason: str
    to: str
    task_id: str
    role: str
    workspace: str
    created_at: str
    due_at: str
    due_epoch: float | None = None
    due_mono: float | None = None
    clock_token: str = ""
    state: str = "pending"
    fired_at: str = ""
    mailbox_item_id: str = ""
    wake_id: str = ""
    note: str = ""
    #: 等谁（原样保留调用方给的写法）。空 = 这一条等的是时间。
    wait_for: str = ""
    #: 起表时把 `wait_for` 解析成的具体对象（`task:t000012` / `agent:D1` / `program:tm-…`）。
    wait_for_resolved: str = ""
    #: "等谁"的结构化落盘（业主 2026-10-26 第 ② 条）：
    #: `{"kind": "roster"|"program", "name": <名册名/程序名>, "task_id": … 或 "program_id": …}`。
    #: 空表 = 这一条等的是时间（不是"等谁"）。
    #:
    #: 为什么不能只留 `wait_for` 那一串人话：读侧（时间线、页面、父代理的读数）要回答
    #: "在等 A1（t-000002）"或"在等程序 exp1"，而 `wait_for="A1"` 这一串既没有编号也
    #: 分不出是名册名还是别的什么。唤醒的那一刻这一格被清空（见 `fire_due`）——
    #: "还在等谁"与"等过了"必须分得开，留着它会让一条已经醒了 3 次的表看起来还在等。
    waiting_on: dict[str, Any] = field(default_factory=dict)
    #: 等谁的上限（秒）。`wait_for` 那一半没有钟点，这一格是"最多等多久"的闸。
    max_wait_sec: float | None = None
    #: 上一次判定时对被等对象的读数（三态之一；空 = 没判过 / 等的是时间）。
    wait_state: str = ""
    #: 这一条最终是被哪个触发叫醒的（`deadline` / `target_closed` / `cap`）。
    triggered_by: str = ""
    #: 为什么醒了（`WOKE_REASONS` 之一；空 = 还没醒）。
    woke_reason: str = ""
    #: 起表那一刻的事件序号（只有这之后发生的事件才算"被等对象的新动静"）。
    event_seq: int = 0
    #: 到点那一刻发给收件人的那句原话（`due_message` 的唯一产物；未到点为空）。
    message: str = ""
    #: 到点那一刻抄进来的对方反馈（子代理的话 / 收工摘要）。空 = 没有可抄的。
    feedback: str = ""
    #: 挂机起始时刻（`wait_for` 那一条才有；是"挂在时钟上"的那一刻）。
    parked_at: str = ""
    #: 时钟放行的时刻（醒来那一刻）。
    woke_at: str = ""
    #: 挂机期间这一趟产生的回合数与模型调用数（判据靠它们证明"没有轮询"）。
    parked_steps: int = 0
    parked_calls: int = 0
    #: 目的的来源（`PURPOSE_SOURCES`）：显式给的 / 从被等对象的 task 抄的 / 拿不到。
    #: 业主 2026-10-27：「将"等子代理"的"目的"与名册机制的 task 结合，自动以 task 填充目的」。
    purpose_source: str = ""
    #: 程序计时器那五格读数（业主 2026-10-27 点名的 `timer_id` / `program` / argv 摘要 /
    #: `pid` / `state` / `elapsed_sec` / `exit_code`；`state` 就是本类的 `state`）。
    #: 等谁/等时间的计时器这五格是空的 —— 空不是 0（"没有程序"与"程序跑了 0 秒"分得开）。
    program: str = ""
    argv_digest: str = ""
    pid: int | None = None
    elapsed_sec: float | None = None
    exit_code: int | None = None
    #: 程序结束的结局（`PROGRAM_OUTCOMES` 之一；非程序计时器是空串）。
    outcome: str = ""
    #: 运行期附加的字段（不落盘）：起表时调的 `after_sec`，只为回显。
    after_sec: float | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in TIMER_KINDS:
            raise ValueError(f"kind 必须是 {TIMER_KINDS} 之一，收到 {self.kind!r}")
        if self.state not in TIMER_STATES:
            raise ValueError(f"state 必须是 {TIMER_STATES} 之一，收到 {self.state!r}")
        if self.wait_state and self.wait_state not in TARGET_STATES:
            raise ValueError(f"wait_state 必须是 {TARGET_STATES} 之一，收到 {self.wait_state!r}")
        if self.triggered_by and self.triggered_by not in DUE_TRIGGERS:
            raise ValueError(
                f"triggered_by 必须是 {DUE_TRIGGERS} 之一，收到 {self.triggered_by!r}")
        if self.woke_reason and self.woke_reason not in WOKE_REASONS:
            raise ValueError(
                f"woke_reason 必须是 {WOKE_REASONS} 之一，收到 {self.woke_reason!r}")
        if self.purpose_source and self.purpose_source not in PURPOSE_SOURCES:
            raise ValueError(
                f"purpose_source 必须是 {PURPOSE_SOURCES} 之一，收到 {self.purpose_source!r}")
        if self.outcome and self.outcome not in PROGRAM_OUTCOMES:
            raise ValueError(
                f"outcome 必须是 {PROGRAM_OUTCOMES} 之一，收到 {self.outcome!r}")

    @property
    def purpose(self) -> str:
        """这一条的目的（与 `reason` 同一格；业主 2026-10-25 把它叫"目的"）。"""
        return str(self.reason or "")

    @property
    def is_park(self) -> bool:
        """这一条是不是"挂机"（等谁的那一条才是；等时间的是有目的的睡，不是挂机）。"""
        return bool(str(self.wait_for or "").strip())

    @property
    def park_state(self) -> str:
        """挂机状态（`PARK_STATES`）。等时间是空串（它不是挂机）。"""
        if not self.is_park:
            return ""
        if self.state == "cancelled":
            return "cancelled"
        if self.state == "fired":
            return "woke"
        return "parked"

    def parked_seconds(self, reading: Reading | None = None) -> float | None:
        """挂了多久（现场读数：从挂上到放行/现在）。不是挂机或读不到 => None。"""
        if not self.is_park:
            return None
        got = reading if reading is not None else now()
        if got.status == "unknown" or got.wall is None:
            return None
        try:
            start = _parse_iso(self.parked_at or self.created_at)
        except ClockError:
            return None
        end = got.wall
        stamp = self.woke_at or self.fired_at
        if stamp:
            try:
                end = _parse_iso(stamp)
            except ClockError:
                end = got.wall
        return max(0.0, (end - start).total_seconds())

    @property
    def purpose_missing(self) -> bool:
        """目的填了没有。缺了不是失败：条目照样受理，读数与到点消息里追问一句。"""
        return not self.purpose.strip()

    @property
    def is_program(self) -> bool:
        """这一条是不是"等某个程序"（业主 2026-10-27 的第一条裁定）。"""
        return self.kind == "program"

    def program_row(self) -> dict[str, Any]:
        """程序计时器的那一行读数（业主点名的那几格，键集稳定）。"""
        return {
            "timer_id": self.timer_id,
            "program": self.program,
            "argv_digest": self.argv_digest,
            "pid": self.pid,
            "state": self.state,
            "outcome": self.outcome,
            "elapsed_sec": self.elapsed_sec,
            "exit_code": self.exit_code,
            "purpose": self.purpose,
            "purpose_source": self.purpose_source,
            "task_id": self.task_id,
            "role": self.role,
            "at": self.created_at,
            "fired_at": self.fired_at,
            "message": self.message,
            "note": self.note,
        }

    def to_dict(self) -> dict[str, Any]:
        """落盘那一份（`out/clock/state.json` 的一行）。

        ## `purpose` 这一格为什么必须落盘，且为什么它是单一来源

        业主 2026-10-26 的真机读数是「timers 20 条，purpose 全为 None」，而同一次运行的
        到点消息里却有話可念（「时间到：认领检索请求 r-000004｜等了 2 分钟 27 秒」）。
        错位不在自动填，在两处取值口径：`purpose` 是 `@dataclass` 之外的一个
        `@property`（读的是 `reason` 字段），于是 `asdict` 不吐它 ⇒ 盘上那一行
        只有 `reason`，谁按行读 `row.get("purpose")` 都拿到 None，而 `fire_due` 用的是
        内存里的属性、念得出话。

        现在落两格：`reason`（原始字段）与 `purpose`（它的规范化视图）——
        视图这一句就是 `self.purpose`，与 `due_message` / `fire_due` / 三态读数用的是
        同一个访问器，于是"内存里念的"与"盘上读的"结构上不可能分家。
        读侧统一走 `purpose_of()`（先 `purpose` 再 `reason`），不许多拼一份。
        """
        got = asdict(self)
        got.pop("after_sec", None)
        #: 规范化视图：与 `self.purpose` 同源（同一个属性），不是第二份可漂的副本。
        got["purpose"] = self.purpose
        return got

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Timer":
        """从盘上那一行还原。`purpose` 是派生视图，不进字段表（只做"老行"的对账）。"""
        fields = {f for f in cls.__dataclass_fields__ if f != "after_sec"}
        got = {k: v for k, v in dict(raw).items() if k in fields}
        if not str(got.get("reason") or "").strip():
            # 手改过 / 老写入方只写了 `purpose` 的行：把那一句话认回 `reason`，
            # 否则这一条会在内存里变成"目的未填"，而盘上明明有一句。
            legacy = str(raw.get("purpose") or "").strip()
            if legacy:
                got["reason"] = legacy
        return cls(**got)

    def due_datetime(self) -> datetime | None:
        try:
            return _parse_iso(self.due_at)
        except ClockError:
            return None

    def deadline_passed(self, reading: Reading) -> bool:
        """钟点那一半：到 due 了没有。读不到时钟 => 判不了（False，不是"没到"）。

        单调计数只在同一个时钟实例（`clock_token` 相同）里可比；跨重启退化到墙钟
        （见模块 docstring 的"重启之后怎么判 due"）。
        """
        if self.state != "pending" or reading.status == "unknown":
            return False
        token = str(getattr(_CLOCK, "token", "") or "")
        if (self.clock_token and token and self.clock_token == token
                and self.due_mono is not None and reading.monotonic is not None):
            return reading.monotonic >= self.due_mono
        due = self.due_datetime()
        if due is not None and reading.wall is not None:
            return reading.wall >= due
        return False

    def cap_passed(self, reading: Reading) -> bool:
        """等谁的上限那一半：从起表到现在是否已经超过 `max_wait_sec`。"""
        if self.state != "pending" or self.max_wait_sec is None:
            return False
        if reading.status == "unknown" or reading.wall is None:
            return False
        try:
            created = _parse_iso(self.created_at)
        except ClockError:
            return False
        return (reading.wall - created).total_seconds() >= max(0.0, float(self.max_wait_sec))

    def due_reason(self, reading: Reading,
                   target: tuple[str, str, str] | None = None) -> tuple[str, str]:
        """到点判定的唯一实现。返回 `(触发串, 理由)`；触发串空 = 还没到或判不了。

        `target` 是 `target_state()` 的读数（`(三态, 解析对象, 理由)`），由调用方
        一次算好传进来 —— 每条计时器自己再去读一遍台账会让一次 `fire_due` 变成
        O(计时器数 x 台账行数) 次读盘。

        三个触发可以同时成立（等时间 + 等谁，先到者报醒）；`triggered_by` 记的是
        拼起来的串，读的人能看见是哪一个（或哪几个）到了。
        """
        if self.state != "pending":
            return "", ""
        if reading.status == "unknown":
            return "", "时钟读不到 => 判不了 due"
        hits: list[str] = []
        if self.deadline_passed(reading):
            hits.append("deadline")
        why = ""
        if self.wait_for:
            events = _event_hits(self)
            if events:
                hits.append("target_event")
                last = events[-1]
                why = (f"它{'交' if last.kind == 'submit' else '说'}了"
                       f"（{last.kind}@{last.at or '刚发生'}）：{last.content[:120]}")
            else:
                state, _resolved, why = target or target_state(
                    self.workspace, *parse_wait_for(self.wait_for))
                if state == "closed":
                    hits.append("target_closed")
        if self.cap_passed(reading):
            hits.append("cap")
        return ",".join(hits), why

    def woke_reason_of(self, trigger: str) -> str:
        """把触发串折成"为什么醒了"那一格（`WOKE_REASONS`；判不了 => 空）。

        - 有 `target_event` => 等到了对方的事件（`event`）；
        - 有 `target_closed` => 对方收口了（`closed`）；
        - 只有钟点/上限 => `timeout`（到点了，它还没交/没说）；
        - 等的是时间（没有 `wait_for`）=> 空（这不是"等谁"的那一档）。
        """
        parts = [p for p in str(trigger or "").split(",") if p]
        if "target_event" in parts:
            return "event"
        if "target_closed" in parts:
            return "closed"
        if parts and self.wait_for:
            return "timeout"
        return ""

    def is_due(self, reading: Reading) -> bool:
        """到点了没有（只看钟点与上限；"等谁"要调用方把读数传进 `due_reason`）。"""
        return bool(self.due_reason(reading)[0])

    def remaining_seconds(self, reading: Reading | None = None) -> float | None:
        """还剩多少秒。读不到时钟 => None（不是 0）；等谁且没设上限 => None（没有钟点）。"""
        got = reading if reading is not None else now()
        if self.state != "pending":
            return 0.0
        if got.status == "unknown":
            return None
        if self.due_datetime() is None:
            return None
        token = str(getattr(_CLOCK, "token", "") or "")
        if (self.clock_token and token and self.clock_token == token
                and self.due_mono is not None and got.monotonic is not None):
            return max(0.0, float(self.due_mono) - float(got.monotonic))
        due = self.due_datetime()
        if due is not None and got.wall is not None:
            return max(0.0, (due - got.wall).total_seconds())
        return None

    def waited_seconds(self, reading: Reading | None = None) -> float | None:
        """这一条"等了多久"：到点了算 created -> fired，没到算 created -> 现在。

        它是到点消息里"等了 <时长>"那一格的唯一来源。读不到 => None（不是 0）。
        """
        got = reading if reading is not None else now()
        if got.status == "unknown" or got.wall is None:
            return None
        try:
            created = _parse_iso(self.created_at)
        except ClockError:
            return None
        end = None
        if self.fired_at:
            try:
                end = _parse_iso(self.fired_at)
            except ClockError:
                end = None
        end = end or got.wall
        return max(0.0, (end - created).total_seconds())

    def row(self, reading: Reading | None = None) -> dict[str, Any]:
        """给工具面/判据读的一行（键集稳定，嵌套不深）。"""
        got = reading if reading is not None else now()
        return {
            "timer_id": self.timer_id,
            "kind": self.kind,
            "reason": self.reason,
            "purpose": self.purpose,
            "purpose_missing": self.purpose_missing,
            "to": self.to,
            "task_id": self.task_id,
            "role": self.role,
            "created_at": self.created_at,
            "due_at": self.due_at,
            "state": self.state,
            "fired_at": self.fired_at,
            "remaining_sec": self.remaining_seconds(got),
            "waited_sec": self.waited_seconds(got),
            "wait_for": self.wait_for,
            "wait_for_resolved": self.wait_for_resolved,
            "waiting_on": dict(self.waiting_on or {}),
            "waiting_on_text": waiting_on_text(self.waiting_on),
            "wait_state": self.wait_state,
            "max_wait_sec": self.max_wait_sec,
            "triggered_by": self.triggered_by,
            "woke_reason": self.woke_reason,
            "park_state": self.park_state,
            "parked_at": self.parked_at,
            "parked_sec": self.parked_seconds(got),
            "parked_steps": int(self.parked_steps),
            "parked_calls": int(self.parked_calls),
            "feedback": self.feedback,
            "message": self.message,
            "mailbox_item_id": self.mailbox_item_id,
            "wake_id": self.wake_id,
            "note": self.note,
            "purpose_source": self.purpose_source,
            "program": self.program,
            "argv_digest": self.argv_digest,
            "pid": self.pid,
            "elapsed_sec": self.elapsed_sec,
            "exit_code": self.exit_code,
            "outcome": self.outcome,
        }


def purpose_of(entry: Any) -> str:
    """一条计时器 / 周期性巡查 / 盘上那一行的目的 —— 全仓唯一的取值口。

    为什么要有这一个函数（业主 2026-10-26 的真机读数逼出来的）：真机上同一个目的有两个
    读者，一个念得出来、一个读到 None ——
    `fire_due` 走内存里的 `Timer.purpose`（属性，读 `reason`），
    而读数侧按 `state.json` 的行读 `row.get("purpose")`，那一格当时根本不存在。
    两个读者各写一份取法，迟早分家。所以只留这一处：

    - `Timer` / `Periodic`：`purpose` 属性（前者是 `reason` 的视图，后者是字段本身）；
    - 盘上那一行（`Mapping`）：先 `purpose`（`Timer.to_dict` 落的规范化视图），
      没有就退回 `reason`（`purpose` 是后加的键，老行只有 `reason`）；
    - 都没有 / `None` => 空串（不是 "None"、不是编一句）。

    空串只表示"这一条真的没写目的"，`purpose_missing` 就是按它判的。
    """
    if entry is None:
        return ""
    if isinstance(entry, Mapping):
        return str(entry.get("purpose") or entry.get("reason") or "").strip()
    return str(getattr(entry, "purpose", "") or getattr(entry, "reason", "") or "").strip()


def waiting_on_text(waiting_on: Any) -> str:
    """`waiting_on` 的人话读数（业主 2026-10-26 第 ② 条：读侧要能读出"在等谁"）。

    - 名册上的人：「在等 A1（t-000002）」；只给了编号时名字那一格是空的，
      这时只念编号（不编一个名字出来）；
    - 某条程序：「在等程序 exp1（tm-000003）」；
    - 空表（等的是时间）或读不成 => 空串（不是"在等 None"）。
    """
    row = dict(waiting_on) if isinstance(waiting_on, Mapping) else {}
    kind = str(row.get("kind") or "")
    name = str(row.get("name") or "").strip()
    if kind == "program":
        pid = str(row.get("program_id") or row.get("timer_id") or "").strip()
        label = name or pid
        if not label:
            return ""
        return f"在等程序 {label}（{pid}）" if pid and pid != label else f"在等程序 {label}"
    if kind == "roster":
        tid = str(row.get("task_id") or "").strip()
        label = name or tid
        if not label:
            return ""
        return f"在等 {label}（{tid}）" if tid and tid != label else f"在等 {label}"
    return ""


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


def _atomic_json(path: Path, doc: Mapping[str, Any]) -> None:
    """原子写一份 JSON（同目录 tmp + os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(dict(doc), ensure_ascii=False, indent=2, default=json_default)
    tmp.write_text(text + "\n", encoding="utf-8", newline="")
    os.replace(tmp, path)


@dataclass
class Periodic:
    """一条周期性巡查。M 的"巡视"就是这一类（等 20 分钟 + 周期性巡查）。

    与一次性计时器的区别只在"到点之后怎么走"：一次性到点即消耗，周期性到点不消耗、
    `next_at` 前移到下一拍、`fires` 递增，直到被 `periodic_stop` 停 / `until_sec` 到 /
    被等的那对象收口。三个终态都写进 `stopped_reason`（空 = 还在跑）。
    """

    periodic_id: str
    every_sec: float
    purpose: str
    to: str
    task_id: str
    role: str
    workspace: str
    created_at: str
    next_at: str
    state: str = "running"
    fires: int = 0
    last_fired_at: str = ""
    stopped_at: str = ""
    stopped_reason: str = ""
    until_sec: float | None = None
    wait_for: str = ""
    wait_for_resolved: str = ""
    wait_state: str = ""
    next_mono: float | None = None
    clock_token: str = ""

    def __post_init__(self) -> None:
        if self.state not in PERIODIC_STATES:
            raise ValueError(
                f"state 必须是 {PERIODIC_STATES} 之一，收到 {self.state!r}")
        if float(self.every_sec) <= 0:
            raise ValueError(f"every_sec 必须是正数，收到 {self.every_sec!r}")
        if self.wait_state and self.wait_state not in TARGET_STATES:
            raise ValueError(
                f"wait_state 必须是 {TARGET_STATES} 之一，收到 {self.wait_state!r}")

    @property
    def purpose_missing(self) -> bool:
        return not str(self.purpose or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Periodic":
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in dict(raw).items() if k in fields})

    def next_datetime(self) -> datetime | None:
        try:
            return _parse_iso(self.next_at)
        except ClockError:
            return None

    def elapsed_sec(self, reading: Reading | None = None) -> float | None:
        """从起表到现在跑了多久（`until_sec` 那条闸按它判）。读不到 => None。"""
        got = reading if reading is not None else now()
        if got.status == "unknown" or got.wall is None:
            return None
        try:
            return max(0.0, (got.wall - _parse_iso(self.created_at)).total_seconds())
        except ClockError:
            return None

    def remaining_sec(self, reading: Reading | None = None) -> float | None:
        """离下一拍还有多少秒。读不到时钟 => None（不是 0）。"""
        got = reading if reading is not None else now()
        if self.state != "running":
            return 0.0
        if got.status == "unknown":
            return None
        nxt = self.next_datetime()
        if nxt is None or got.wall is None:
            return None
        return max(0.0, (nxt - got.wall).total_seconds())

    def last_message(self, reading: Reading | None = None) -> str:
        """上一次报醒那句话（周期性巡查的定死格式；目的走唯一取值口）。"""
        return due_message(purpose=purpose_of(self), waited_sec=None,
                           created_at=None, fired_at=None,
                           every_sec=self.every_sec, fires=self.fires)

    def row(self, reading: Reading | None = None) -> dict[str, Any]:
        """给工具面/判据读的一行。业主点名的六格都在最前面。"""
        got = reading if reading is not None else now()
        return {
            "periodic_id": self.periodic_id,
            "every_sec": self.every_sec,
            "purpose": self.purpose,
            "fires": int(self.fires),
            "next_at": self.next_at,
            "stopped_reason": self.stopped_reason,
            "purpose_missing": self.purpose_missing,
            "state": self.state,
            "to": self.to,
            "task_id": self.task_id,
            "role": self.role,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
            "remaining_sec": self.remaining_sec(got),
            "until_sec": self.until_sec,
            "wait_for": self.wait_for,
            "wait_for_resolved": self.wait_for_resolved,
            "wait_state": self.wait_state,
            "stopped_at": self.stopped_at,
            "last_message": self.last_message(got) if self.fires else "",
        }


class TimerBook:
    """一个工作区的计时器簿记，落盘成 `<工作区>/out/clock/state.json`。

    一份簿记装两样东西：一次性的计时器/闹钟（`timers`）与周期性巡查（`periodics`）。
    两者共用同一个发号器（编号前缀不同：`tm` / `pd`），于是"这一条是几号"在同一个
    工作区里不会撞号，读的人也能从编号一眼看出它是哪一类。
    """

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._timers: dict[str, Timer] = {}
        self._periodics: dict[str, Periodic] = {}
        self._next_seq = 1
        self._loaded = False
        #: 读盘失败的理由。非空 = 这一份簿记没查成，不许读成"没有计时器"。
        self.load_error = ""

    @property
    def state_path(self) -> Path:
        return Path(self.workspace) / STATE_REL

    def load(self) -> "TimerBook":
        if self._loaded:
            return self
        self._loaded = True
        path = self.state_path
        if not path.is_file():
            return self
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
            self.load_error = f"计时器状态读不成：{type(exc).__name__}: {exc}"
            return self
        if not isinstance(doc, dict):
            self.load_error = "计时器状态不是对象"
            return self
        try:
            self._next_seq = max(1, int(doc.get("next_seq") or 1))
        except (TypeError, ValueError):
            self._next_seq = 1
        for raw in doc.get("timers") or ():
            try:
                timer = Timer.from_dict(raw)
            except Exception as exc:  # noqa: BLE001 - 坏行要留理由，不许静默丢
                self.load_error = (self.load_error + "；" if self.load_error else "") + \
                    f"有一条计时器读不成：{type(exc).__name__}: {exc}"
                continue
            self._timers[timer.timer_id] = timer
        for raw in doc.get("periodics") or ():
            try:
                periodic = Periodic.from_dict(raw)
            except Exception as exc:  # noqa: BLE001
                self.load_error = (self.load_error + "；" if self.load_error else "") + \
                    f"有一条周期性巡查读不成：{type(exc).__name__}: {exc}"
                continue
            self._periodics[periodic.periodic_id] = periodic
        # 发号器不许比盘上已有的号小（手工改过 state.json 之后也不撞号）。
        for tid in list(self._timers) + list(self._periodics):
            tail = tid.rsplit("-", 1)[-1]
            if tail.isdigit():
                self._next_seq = max(self._next_seq, int(tail) + 1)
        return self

    def save(self) -> None:
        if self.load_error:
            # 读坏的那一份不许被"保存一次空表"覆盖掉（那会把证据抹掉）。
            raise ClockStateError(self.load_error)
        reading = now()
        doc = {
            "schema": SCHEMA,
            "saved_at": _iso(reading.wall) if reading.wall is not None else "",
            "clock_token": str(getattr(_CLOCK, "token", "") or ""),
            "next_seq": self._next_seq,
            "timers": [t.to_dict() for t in
                       sorted(self._timers.values(), key=lambda t: (t.due_at, t.timer_id))],
            "periodics": [p.to_dict() for p in
                          sorted(self._periodics.values(),
                                 key=lambda p: (p.next_at, p.periodic_id))],
        }
        try:
            _atomic_json(self.state_path, doc)
        except OSError as exc:
            raise ClockStateError(f"计时器状态写不成：{type(exc).__name__}: {exc}") from None

    def require_loaded(self) -> "TimerBook":
        self.load()
        if self.load_error:
            raise ClockStateError(self.load_error)
        return self

    def allocate(self, prefix: str) -> str:
        self.require_loaded()
        seq = self._next_seq
        self._next_seq += 1
        return f"{prefix}-{seq:06d}"

    def add(self, timer: Timer) -> None:
        self.require_loaded()
        self._timers[timer.timer_id] = timer
        self.save()

    def get(self, timer_id: str) -> Timer | None:
        self.require_loaded()
        return self._timers.get(str(timer_id or ""))

    def all(self) -> list[Timer]:
        self.require_loaded()
        return sorted(self._timers.values(), key=lambda t: (t.due_at, t.timer_id))

    def pending(self) -> list[Timer]:
        return [t for t in self.all() if t.state == "pending"]

    def cancel(self, timer_id: str) -> tuple[Timer | None, str]:
        """取消一条计时器。返回 `(计时器或 None, 这一次的结果)`。

        结果的取值刻意区分"这一次真的取消了"与"它早就是取消态"：
        `cancelled`（首次迁移）/ `already_cancelled` / `fired` / `not_found`。
        把后两者折成 `cancelled` 会让"查过了、没有这一条"读成"第二次取消成功"。
        """
        timer = self.get(timer_id)
        if timer is None:
            return None, "not_found"
        if timer.state == "cancelled":
            return timer, "already_cancelled"
        if timer.state != "pending":
            return timer, timer.state
        timer.state = "cancelled"
        _unregister_parked(timer.timer_id)
        self.save()
        return timer, "cancelled"

    def set_purpose(self, entry_id: str, purpose: str,
                    *, source: str = "given") -> tuple[Any, str]:
        """给一条已受理的计时器/周期性巡查补上目的。返回 `(条目或 None, 结果)`。

        结果与 `cancel` 同一族纪律：`filled`（这一次填上了）/ `already_filled`
        （早有目的，不动它）/ `not_found` / `not_pending`（已到点/已取消的不许改）。
        为什么"早有目的"不覆盖：补目的是补空白，不是改历史 —— 覆盖掉会让"到点消息
        里念的那句目的"与"起表时写的那句"对不上，而两条都进过审计。

        `source` 记的是"这句目的到底从哪来"，必须落在 `PURPOSE_SOURCES` 里：

        - `given`（缺省）：有人显式写进去的一句（模型补的 / 调用方给的）；
        - `target_task`：这句是被等对象那一条子代理的 task 原文，只是名册那一行
          当时还没写成，于是由派活的那一处（`Conductor.arm_child_waiter`）把载荷里
          的同一句交过来。它仍然是"从被等对象的 task 抄来的"，不是人给的一句
          —— 记成 `given` 会让"目的自动填到底成没成"这件事在读数上漂掉。
        """
        want_source = str(source or "given").strip() or "given"
        if want_source not in PURPOSE_SOURCES:
            raise ClockParamError(
                f"purpose_source 必须是 {PURPOSE_SOURCES} 之一，收到 {want_source!r}")
        want = str(entry_id or "")
        timer = self._timers.get(want)
        if timer is not None:
            if timer.state != "pending":
                return timer, "not_pending"
            if not timer.purpose_missing:
                return timer, "already_filled"
            timer.reason = str(purpose or "").strip()
            timer.purpose_source = want_source
            self.save()
            return timer, "filled"
        periodic = self._periodics.get(want)
        if periodic is not None:
            if periodic.state != "running":
                return periodic, "not_pending"
            if not periodic.purpose_missing:
                return periodic, "already_filled"
            periodic.purpose = str(purpose or "").strip()
            self.save()
            return periodic, "filled"
        return None, "not_found"

    # ---------------------------------------------------------- 周期性巡查

    def add_periodic(self, periodic: Periodic) -> None:
        self.require_loaded()
        self._periodics[periodic.periodic_id] = periodic
        self.save()

    def get_periodic(self, periodic_id: str) -> Periodic | None:
        self.require_loaded()
        return self._periodics.get(str(periodic_id or ""))

    def all_periodics(self) -> list[Periodic]:
        self.require_loaded()
        return sorted(self._periodics.values(),
                      key=lambda p: (p.next_at, p.periodic_id))

    def running_periodics(self) -> list[Periodic]:
        return [p for p in self.all_periodics() if p.state == "running"]

    def stop_periodic(self, periodic_id: str, reason: str = "",
                      state: str = "stopped") -> tuple[Periodic | None, str]:
        """停一条周期性巡查。返回 `(条目或 None, 结果)`。

        结果与 `cancel` 同族：`stopped`（首次停）/ `already_stopped` / `not_found`。
        """
        periodic = self.get_periodic(periodic_id)
        if periodic is None:
            return None, "not_found"
        if periodic.state != "running":
            return periodic, "already_stopped"
        periodic.state = state
        periodic.stopped_reason = str(reason or "")
        reading = now()
        periodic.stopped_at = _iso(reading.wall) if reading.wall is not None else ""
        self.save()
        return periodic, "stopped"


def book(workspace: str | Path) -> TimerBook:
    """取（或建）这个工作区的计时器簿记；第一次取会读盘。"""
    root = str(Path(workspace).resolve())
    if root not in _BOOKS:
        _BOOKS[root] = TimerBook(root)
    return _BOOKS[root].require_loaded()


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
        clock_token=str(getattr(_CLOCK, "token", "") or ""),
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
        clock_token=str(getattr(_CLOCK, "token", "") or ""),
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
    """这个工作区的全部计时器（含已到点与已取消，按 due 排序）。"""
    return book(workspace).all()


# ---------------------------------------------------------------- 等程序（业主 2026-10-27 第一条）

#: 进程内"起了程序却没能在时钟上登记"的次数与理由。
#:
#: 为什么要有这一格：程序计时器的登记要有工作区（账落在 `<工作区>/out/clock`）。
#: 没有工作区的调用点（例如模块导入期的工具链探测）结构上登记不了 —— 那就如实
#: 记一条"没登记"，读数里看得见；绝不允许"程序在跑、账上没有、也没人知道"。
_PROGRAM_UNBOOKED: list[dict[str, Any]] = []

#: `program_census` 的缓存（按扫描根做键；`refresh=True` 强制重扫）。
#:
#: 为什么要缓存：`coverage()` 的 `programs_outside_clock` 那一格读它，而 `coverage()`
#: 又被 `clock.now` 每个回合读一次 —— 没有缓存就是每个回合把整棵 `src` AST 一遍。
_PROGRAM_CENSUS_CACHE: dict[str, Any] | None = None


def _workspace_of(workspace: str | Path | None) -> str:
    """这次要记到哪个工作区：显式给的 > 当前挂上的 > 进程缺省；都没有 => 空串。"""
    if workspace is not None and str(workspace).strip():
        return str(Path(workspace).resolve())
    return str(current_workspace() or "")


def argv_digest(argv: Iterable[Any] | None) -> str:
    """argv 的摘要（只读、稳定）：空格拼起来截断到 `ARGV_EXCERPT`；给了空就空串。

    为什么不存整条命令行：它可能有几百个字符（一长串 Lean 参数），而读的人要的是
    "跑的是哪个程序、带了哪些看得懂的参数"；截断处不做任何加工，读的人照样看得出
    它被截过（原文里那一截就在那里）。
    """
    parts = [str(a) for a in (argv or ()) if str(a)]
    if not parts:
        return ""
    return " ".join(parts)[:ARGV_EXCERPT]


def program_message(*, program: str, outcome: str, exit_code: int | None,
                    elapsed_sec: float | None, purpose: str = "") -> str:
    """程序计时器收口那句话的唯一拼法（结局 + 程序名 + 耗时 + 退出码）。"""
    outcome_text = {
        "exited": "跑完了",
        "failed": "跑的路上抛了异常",
        "timed_out": "到上限被杀（超时）",
        "killed": "被喊停后被杀",
    }.get(str(outcome or ""), str(outcome or "结束了"))
    bits = [f"程序{outcome_text}：{str(program or '（没记名字）')}"]
    if purpose:
        bits.append(f"目的：{purpose}")
    bits.append(f"耗时 {human_sec(elapsed_sec) or '读不到'}")
    bits.append(f"退出码 {exit_code}" if exit_code is not None else "退出码读不到")
    return "｜".join(bits)


def program_purpose(*, program: str, argv: Iterable[Any] | None = None) -> str:
    """等程序那一条的自动目的（业主 2026-10-27 第一条裁定 + 第二条的同一口径）。

    为什么程序这一档也要自动填：程序计时器是框架自己起的（`program_span` 的调用点
    大多不传 purpose），而到点消息的格式对每一档都一样 —— 不填，那一句就只能是
    「程序跑完了：lean.EXE｜耗时 0 秒｜退出码 0」，读的人看不出"等它是为了什么"。
    填法两半：程序名（只取基名，路径进摘要）+ 命令行摘要（`argv_digest`，截断到
    `ARGV_EXCERPT`）；两样都没有 => 空串（那一档退回 `unavailable` + 追问）。
    """
    raw = str(program or "").strip()
    name = ""
    if raw:
        try:
            name = Path(raw).name or raw
        except (OSError, ValueError):  # pragma: no cover - 坏路径退回原文
            name = raw
    digest = argv_digest(argv)
    if not name and not digest:
        return ""
    body = f"等程序跑完：{name or digest}"
    if digest and digest != name:
        body = f"{body}（{digest}）"
    return body[:PURPOSE_FROM_TARGET]


def _calling_identity() -> tuple[str, str]:
    """这一趟调用是谁：`(台账号, 角色)`；取不到 => `("", "")`。

    三个来源，按"离这次起程序有多近"排序：

    1. 这一趟 run（`current_run_identity`）：`AgentLoop.run` 在装配之前挂上
       （`clock.run_as`），于是装配期起的程序也有归属 —— 真机 `mp3-r4` 的
       `tm-000001`（`toolchain._version_of`）就是补这一档（同一局 13 条程序计时器里
       唯一空的那一条）；
    2. 这一次工具调用（`conductor.calling_as` 挂在 ContextVar 上的两格）：
       七个落点从工具层之下进来时走这一格；工具路径上它与第 1 档同号；
    3. 都没有 => `("", "")`：程序照跑，账上归属留空 —— 空就是"没记上"，绝不猜
       （`is_my_program` 那一侧把空一律判成"不是我的"）。

    ## 为什么 run 那一档排在 `calling_as` 前面

    召唤线程是 `copy_context()` 起的（`conductor.py:6152`），父的 `calling_as` 会一起
    被复制进去：子代理装配期若读 `calling_as`，就会把"父的号"写成"子起的程序"的归属
    —— 错归属比空归属危险（`program.stop` 会因此放行"父停子的程序"）。
    `run_as` 是"这一趟"自己挂的，所以它赢。工具路径上两者同号 ⇒ 逐字节相同
    （判据：`tests/test_g8_a_program_belongs_to_the_run.py` 的 a/b/f 三条）。

    ## 为什么是懒 import

    `conductor` 模块级就 `from . import clock`，所以 `clock` 顶层 import 它会成环；
    函数内 import 是安全的（本仓 `table_tools._caller_task_id` 与 `stopctl` 同一条写法）。
    取不到（模块没装好 / 上下文坏了）不算错：程序照跑，账上归属留空 —— 空就是
    "没记上"，绝不猜（`is_my_program` 那一侧把空一律判成"不是我的"）。
    """
    run_task, run_role = current_run_identity()
    if run_task or run_role:
        return run_task, run_role
    try:
        from .conductor import current_caller_role, current_task_id
    except Exception:  # noqa: BLE001 - 取不到身份不该拦住程序登记
        return "", ""
    try:
        return str(current_task_id() or ""), str(current_caller_role() or "")
    except Exception:  # noqa: BLE001 - 见 docstring 最后一段
        return "", ""


def start_program(workspace: str | Path, *, program: str, argv: Iterable[Any] | None = None,
                  where: str = "", purpose: str = "", to: str = "self",
                  task_id: str = "", role: str = "",
                  pid: int | None = None) -> Timer:
    """起一条程序计时器（`kind="program"`）：程序开始跑的那一刻登记，结束时收口。

    与时间/等谁那两档的差别只有一处：它没有 due —— 到点就是"程序结束"这件事，
    由 `finish_program` 写。所以它不会因为时钟读不到而被拒（登记用的是事件，不是钟点）；
    时钟读不到时 `created_at` 留空（不是编一个 1970）。

    目的（第四档）：没给 `purpose` 就用 `program_purpose`（程序名 + 命令行摘要）自动填，
    `purpose_source="program"`；显式给了是 `given`；两样都拿不到才是 `unavailable`
    （此时 `purpose_missing` 为真、追问照旧）。四档都真落盘（`Timer.to_dict`）。

    归属（业主 2026-10-26 的 G1）：`task_id` / `role` 没给时从这一趟的调用上下文现取
    （`_calling_identity`）。为什么必须写进去：`program.stop` 只许碰"自己起的"，
    而"自己起的"唯一的结构判据就是这两格相等 —— 账上不记，那个判据就一条都匹配不到
    （改前真机账上 1420 条程序计时器，`task_id` / `role` 全为空串）。
    """
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    body = str(purpose or "").strip()
    source = "given" if body else "program"
    if not body:
        body = program_purpose(program=program, argv=argv)
        if not body:
            source = "unavailable"
    owner_task, owner_role = str(task_id or ""), str(role or "")
    if not owner_task or not owner_role:
        ctx_task, ctx_role = _calling_identity()
        owner_task = owner_task or ctx_task
        owner_role = owner_role or ctx_role
    timer = Timer(
        timer_id="",
        kind="program",
        reason=body,
        to=str(to or "self"),
        task_id=owner_task,
        role=owner_role,
        workspace=str(Path(workspace).resolve()),
        created_at=stamp,
        due_at="",
        clock_token=str(getattr(_CLOCK, "token", "") or ""),
        state="pending",
        purpose_source=source,
        program=str(program or ""),
        argv_digest=argv_digest(argv),
        pid=(int(pid) if pid is not None else None),
        note=str(where or ""),
    )
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    return timer


def attach_program_pid(workspace: str | Path, timer_id: str,
                       pid: int | None) -> tuple[Timer | None, str]:
    """把 pid 补进那条程序计时器（起进程之后才读得到 pid）。返回 `(计时器, 结果)`。"""
    bucket = book(workspace)
    timer = bucket.get(timer_id)
    if timer is None:
        return None, "not_found"
    if timer.state != "pending":
        return timer, "not_pending"
    timer.pid = int(pid) if pid is not None else None
    bucket.save()
    return timer, "attached"


def finish_program(workspace: str | Path, timer_id: str, *, outcome: str = "exited",
                   exit_code: int | None = None, elapsed_sec: float | None = None,
                   note: str = "") -> tuple[Timer | None, str]:
    """收口一条程序计时器：写结局、耗时、退出码，状态转 `fired`。

    结果三态与 `cancel` 同族：`fired`（这一次真的收口）/ `already_fired`（早就收过，
    不许把第二次收口读成第一次）/ `not_found`。
    """
    if outcome not in PROGRAM_OUTCOMES:
        raise ClockParamError(f"程序结局只认 {PROGRAM_OUTCOMES}，收到 {outcome!r}")
    bucket = book(workspace)
    timer = bucket.get(timer_id)
    if timer is None:
        return None, "not_found"
    if timer.state == "fired":
        return timer, "already_fired"
    if timer.state != "pending":
        return timer, timer.state
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    timer.state = "fired"
    timer.fired_at = stamp
    timer.outcome = outcome
    timer.exit_code = (int(exit_code) if exit_code is not None else None)
    if elapsed_sec is not None:
        timer.elapsed_sec = round(float(elapsed_sec), 6)
    timer.triggered_by = "program_exit"
    timer.woke_reason = "program"
    if str(note or "").strip():
        timer.note = (timer.note + "；" if timer.note else "") + str(note).strip()
    timer.message = program_message(program=timer.program, outcome=outcome,
                                   exit_code=timer.exit_code,
                                   elapsed_sec=timer.elapsed_sec,
                                   purpose=purpose_of(timer))
    bucket.save()
    return timer, "fired"


# ---------------------------------------------------------------- 停程序（G1）

#: 停一条程序时给它的宽限秒数：先让它自己收尾，过了这个窗口才真杀。
#:
#: 为什么是常量而不是工具的参数（业主 2026-10-26 的 G1 施工单：「先 terminate、
#: 超时再 kill（给宽限秒数常量）」）：宽限是"这一刀的手感"，不是每一次调用该重新
#: 商量的口径。模型多给一个参数就多一种把宽限调成 0 的写法 —— 那是把"优雅"变成
#: "直接砍"，而读数上两者长得一样。
PROGRAM_STOP_GRACE_SEC: float = 3.0

#: 宽限与等待窗口里的轮询间隔（每一拍都进主时钟的等待账）。
PROGRAM_STOP_POLL_SEC: float = 0.1

#: 真杀之后最多再等它从进程表上消失多久；等不到就如实报 `timeout`。
PROGRAM_STOP_WAIT_SEC: float = 5.0

#: "停一条程序"的受控读数（`stop_program` 的 `result` 只取这几档，一档都不许折平）：
#:
#: - `killed`：真的把它停掉了（进程没了，那条程序计时器按 `outcome="killed"` 收口）；
#: - `already_exited`：它本来就结束了（幂等那一档：查过了、不是第二次杀成功，行不改）；
#: - `timeout`：杀不动 —— 窗口过了它还在跑（账上那条保持 pending，"它还在跑"必须读得出来）；
#: - `not_mine`：不是这一趟起的（受控拒绝；别人的与账上没有归属的都在这一档）；
#: - `not_found`：查过了、没有可停的那一条（编号不存在 / 不是程序计时器 / 账上没有 pid）。
#:
#: 为什么 `timeout` 与 `killed` 不许合并：合并之后"我杀了它"与"我没杀掉它"在读数上
#: 一样，而那正是这一批要修的东西（昨晚 15 个野进程是被"看起来杀了"留下的）。
PROGRAM_STOP_RESULTS: tuple[str, ...] = ("killed", "already_exited", "timeout",
                                         "not_mine", "not_found")


def program_owner(timer: Timer) -> dict[str, Any]:
    """这条程序账上记的归属：`task_id` / `role` / `to` 三格 + `attributed`。

    `attributed=False` 是"账上没记归属"（改前 1420 条全部如此），不是"零号"、
    也不是"大家共有的"。两种读数在别的格子上长得一样，所以它单列一格。
    """
    task_id = str(timer.task_id or "")
    return {"task_id": task_id, "role": str(timer.role or ""),
            "to": str(timer.to or ""), "attributed": bool(task_id)}


def is_my_program(timer: Timer, *, task_id: str = "", role: str = "") -> bool:
    """这条程序计时器是不是"我这一趟起的"（结构判据，不许靠名字猜）。

    判据与 `agent_loop._is_my_waiter` 同族，只多一条"没有归属就不归任何人"：

    1. `kind` 必须是 `program`（别的计时器不是"我起的程序"）；
    2. 我有台账号 ⇒ 只认 `timer.task_id == 我的台账号`（账上归属为空的旧行一律不算：
       空归属的存量一行都不能被读成"谁的"，否则每个人都会看见、也会动到别人的程序）；
    3. 我连台账号都没有 ⇒ 才退到"角色相等"（与 `_is_my_waiter` 的退路同一档）。
       这一档只用来读（`program.list`），停程序那一侧不接受它（见 `stop_program`）。
    """
    if not bool(getattr(timer, "is_program", False)):
        return False
    mine = str(task_id or "")
    if mine:
        return str(timer.task_id or "") == mine
    who = str(role or "")
    return bool(who) and str(timer.role or "") == who


def not_mine_refusal(timer: Timer, *, task_id: str, role: str = "") -> str:
    """不是这一趟起的程序时那句逐字拒信（判据按这几句认）。

    为什么逐字写死：这句话是模型下一次重试的唯一依据 —— "不是你的"必须点名
    "这条归谁（有没有归属）"与"你只能停自己起的"，否则它会换个编号再试一次。
    """
    owner = program_owner(timer)
    who = (f"它归台账号 {owner['task_id']!r}" if owner["attributed"]
           else "账上没记它的归属（空归属的旧行不归任何人）")
    me = f"台账号 {task_id!r}" if str(task_id or "") else \
        f"角色 {role!r}（这一趟没有台账号）"
    return (f"not_mine：{timer.timer_id}（{timer.program or '没记程序名'}）不是"
            f"{me}起的程序 —— {who}。停程序只许碰自己起的：先用 program.list 看我名下"
            "还在跑的那几条（它只列我的），再按编号停。")


def process_alive(pid: int) -> bool:
    """这个 pid 还活着吗（唯一判法在 `stopctl.alive`，本模块不另写一份）。

    为什么不在这里写 `os.kill(pid, 0)`：Windows 上那不是探活，它会
    `TerminateProcess`（把被探测的进程杀掉）；`tasklist` 在受限环境里又拿不到读数。
    `stopctl.alive` 两条路都实测过（`OpenProcess(SYNCHRONIZE)` +
    `WaitForSingleObject`）。探不了时它说"不活着" —— 调用方据此不杀，绝不假装杀过。

    代价写在明处：探不了的那一档，`stop_program` 会落成 `already_exited`（不杀是安全
    方向，但"没查成"与"它已经自己走了"在这一格分不开 —— 探活是唯一判法，它没有三态口）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        from . import stopctl as SC
    except Exception:  # noqa: BLE001 - 连探活模块都读不到：按"不活着"处置
        return False
    try:
        return bool(SC.alive(pid_int))
    except Exception:  # noqa: BLE001 - 见 docstring 最后一句
        return False


def _exit_code_of(pid: int) -> int | None:
    """被杀进程的退出码（读得到就给，读不到就是 None —— 不是 0）。

    两种平台各一条路，都不用 subprocess（`program_census` 会把 clock.py 里新出现的
    起进程点报成"程序在跑而账上没有计时器"）：

    - Windows：`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
      `GetExitCodeProcess`；`STILL_ACTIVE`（259）说明它其实还在跑 ⇒ None。
      句柄一关进程对象就没了 ⇒ 这条常常读不到，那是诚实的 None。
    - POSIX：只有自家子进程收得到（`waitpid(WNOHANG)`）；不是自家子进程的
      `ChildProcessError` ⇒ None（"读不到"与"退出码是 0"必须分得开）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_int <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k32.OpenProcess(0x1000, 0, pid_int)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    return None
                value = int(code.value)
            finally:
                k32.CloseHandle(ctypes.c_void_p(handle))
            return None if value == 259 else value   # 259 = STILL_ACTIVE
        except Exception:  # noqa: BLE001 - 读不到就是 None
            return None
    try:
        got, status = os.waitpid(pid_int, os.WNOHANG)
    except (ChildProcessError, OSError):
        return None
    if got != pid_int:
        return None
    return int(os.waitstatus_to_exitcode(status)) if hasattr(os, "waitstatus_to_exitcode") \
        else None


def _terminate_pid(pid: int) -> dict[str, Any]:
    """第一刀：请它自己停。如实报"这一刀走了哪条路、有没有真的发出去"。

    ## Windows 上"优雅"到底指什么（业主 2026-10-26 的裁定）

    本平台没有"发给 console 子进程的请停信号"：`os.kill` 在这里就是
    `TerminateProcess`，与 kill 是同一个系统调用 —— 所以 Windows 上"先请停再强杀"
    在信号语义上没有任何差别。这一批里"优雅"指的是时机与告知，不是信号语义：

    1. 先落一条"有人喊停"的账（这一条程序计时器的 note 与 `program.stop` 的读数），
       并且先给它一个宽限窗口让它自己退出（有的程序会看自己的哨兵文件、或收到自己的
       停机条件就收尾）；
    2. 只有宽限窗口过了、它还在，才真动手；动手那一刻读数里写着 `force_kill`。
    3. 真要发 CTRL_BREAK 必须有进程组（`CREATE_NEW_PROCESS_GROUP`）——今天七个起程序
       的落点都没有开进程组（只有网页端的 detached 起法开了），所以这一档不假装发过：
       `sent=False` 逐字写着"没发"。

    POSIX 上这一刀是真信号（SIGTERM），收尾机会就落在这一步里。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"sent": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGTERM)
            return {"sent": True, "via": "SIGTERM", "why": ""}
        except OSError as exc:
            return {"sent": False, "via": "SIGTERM", "why": f"{type(exc).__name__}: {exc}"}
    return {"sent": False, "via": "",
            "why": ("Windows 上没有可发给 console 子进程的请停信号（这一档由宽限窗口"
                    "承担：先等它自己退，过了窗口才强杀）")}


def _terminate_process_handle(pid: int, *, exit_code: int = 9) -> dict[str, Any]:
    """最后一刀（只在没有作业对象时用）：`TerminateProcess`，只收根进程。"""
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x0001, 0, int(pid))   # PROCESS_TERMINATE
        if not handle:
            return {"killed": False, "via": "TerminateProcess",
                    "why": f"OpenProcess 失败（错误码 {ctypes.get_last_error()}）"}
        try:
            ok = bool(k32.TerminateProcess(ctypes.c_void_p(handle), int(exit_code)))
            why = "" if ok else f"TerminateProcess 失败（错误码 {ctypes.get_last_error()}）"
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
        return {"killed": ok, "via": "TerminateProcess", "why": why,
                "note": "这条路只收根进程：它已经生出来的子孙不在这一刀里"}
    except Exception as exc:  # noqa: BLE001 - 杀不成要如实报，不许假装
        return {"killed": False, "via": "TerminateProcess",
                "why": f"{type(exc).__name__}: {exc}"}


def _force_kill_pid(pid: int) -> dict[str, Any]:
    """第二刀：真收掉它（Windows 优先走作业对象，一次收掉整棵传递树）。"""
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"killed": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGKILL)
            return {"killed": True, "via": "SIGKILL", "why": ""}
        except OSError as exc:
            return {"killed": False, "via": "SIGKILL", "why": f"{type(exc).__name__}: {exc}"}
    job_why = ""
    try:
        from . import jobobject as JO

        if JO.available():
            job = JO.create_job(f"agentflow-program-stop-{pid_int}")
            try:
                placed = JO.assign_tree(job, pid_int)
                ok = bool(JO.terminate(job, exit_code=9))
                left = JO.assigned_pids(job)
                return {"killed": ok or not process_alive(pid_int), "via": "job",
                        "why": "", "assigned": list(placed.get("assigned") or ()),
                        "failed": list(placed.get("failed") or ()),
                        "left": list(left.get("pids") or ())}
            finally:
                try:
                    JO.close(job)
                except Exception:  # noqa: BLE001 - 关句柄失败不该带走调用方
                    pass
        job_why = f"作业对象用不了：{JO.unavailable_reason()}"
    except Exception as exc:  # noqa: BLE001 - 这条路走不通就退回下一刀（读数里留着）
        job_why = f"作业对象那条路失败：{type(exc).__name__}: {exc}"
    got = dict(_terminate_process_handle(pid_int))
    if job_why:
        got["job_attempt"] = job_why
    return got


def _wait_until_gone(pid: int, seconds: float, *, purpose: str) -> float:
    """等这个 pid 从进程表上消失，返回实际等了多久（不抛）。

    每一拍都走 `await_io`（主时钟的等待账是"所有等一会儿"的唯一入口，也是
    `raw_wait_census` 的判据：clock.py 里不许出现裸 `time.sleep`）。轮询次数由
    `PROGRAM_STOP_POLL_SEC` 与窗口长度算出来 —— 装上假时钟时 `await_io` 不真睡，
    光靠单调计数会把这里变成忙转，所以圈数也要有上限。
    """
    limit = max(0.0, float(seconds))
    step = max(0.01, float(PROGRAM_STOP_POLL_SEC))
    rounds = max(1, int(limit / step) + 2)
    started = time.monotonic()
    for _ in range(rounds):
        if not process_alive(int(pid)):
            break
        left = limit - (time.monotonic() - started)
        if left <= 0:
            break
        await_io(min(step, left), purpose, kind="program_stop",
                 where="clock._wait_until_gone", waited_for=f"pid:{int(pid)}")
    return max(0.0, time.monotonic() - started)


def _elapsed_of(timer: Timer) -> float | None:
    """这条程序从登记到现在过了多久（读不到时钟 => None，不是 0）。"""
    got = now()
    if got.status == "unknown" or got.wall is None:
        return None
    try:
        created = _parse_iso(timer.created_at)
    except ClockError:
        return None
    return max(0.0, (got.wall - created).total_seconds())


def _wake_waiters(workspace: str | Path, timer_id: str) -> dict[str, Any]:
    """把"等这条程序"的那几条表推一次到点（走既有的 `fire_due`，不另拼一条报醒）。

    为什么不是在 `finish_program` 里直接投递：收口与投递是两件事（一条程序计时器收口
    之后可能根本没人等它），而投递的唯一实现在到点动作那一处（`_deliver_due`：落
    mailbox 项 + 唤醒标记）。这里只是"别等到下一步才推"。
    """
    out: dict[str, Any] = {"checked": False, "watching": 0, "woken": 0,
                           "wake_ids": [], "reason": ""}
    wanted = f"program:{str(timer_id)}"
    try:
        bucket = book(workspace)
        watching = [t for t in bucket.all()
                    if t.state == "pending"
                    and str(t.wait_for_resolved or t.wait_for or "") == wanted]
    except ClockStateError as exc:
        out["reason"] = f"等它的那几条表读不成（{exc}）"
        return out
    out["watching"] = len(watching)
    try:
        report = fire_due(workspace)
    except Exception as exc:  # noqa: BLE001 - 推不成是"没查成"，不许折成"没人等它"
        out["reason"] = (f"到点动作没推成（{type(exc).__name__}: {exc}）⇒ "
                         "等它的那几条保持 pending，下一次步进会再推")
        return out
    out["checked"] = bool(report.get("checked", True))
    ids = {str(t.timer_id) for t in watching}
    woken = [r for r in (report.get("fired") or ()) if str(r.get("timer_id")) in ids]
    out["woken"] = len(woken)
    out["wake_ids"] = [str(r.get("wake_id") or "") for r in woken if r.get("wake_id")]
    if not out["checked"]:
        out["reason"] = f"时钟读不到 ⇒ 判不了 due（{report.get('reason') or '没查成'}）"
    elif watching and not woken:
        out["reason"] = "等它的那几条还在 pending（到点动作没接上或被推迟）⇒ 这一刀没把它们叫醒"
    return out


def _stop_one_program(workspace: str | Path, timer_id: str, *, task_id: str,
                      role: str, grace_sec: float, wait_sec: float,
                      reason: str) -> dict[str, Any]:
    """停一条（`stop_program` 的真身：逐条读数与四档判据都在这里）。"""
    out: dict[str, Any] = {
        "checked": True, "timer_id": str(timer_id), "result": "not_found",
        "program": "", "argv_digest": "", "pid": None, "state": "", "outcome": "",
        "elapsed_sec": None, "exit_code": None, "mine": False,
        "task_id": "", "role": "", "owner": {}, "terminate": {}, "force_kill": {},
        "waited_sec": 0.0, "still_alive": [], "watching": 0, "woken": 0,
        "wake_ids": [], "reason": "",
    }
    bucket = book(workspace)      # 读不成抛 ClockStateError：由工具层报 checked=False
    timer = bucket.get(str(timer_id))
    if timer is None:
        out["reason"] = f"没有 {timer_id} 这一条程序计时器（不是'已经结束了'）"
        return out
    if not timer.is_program:
        out["state"] = timer.state
        out["reason"] = (f"{timer_id} 是 kind={timer.kind!r} 的条目，不是程序计时器 —— "
                         "停程序只认 kind='program' 那一条（等时间/等谁的表用 clock.timer_cancel）")
        return out
    out.update({"program": timer.program, "argv_digest": timer.argv_digest,
                "pid": timer.pid, "state": timer.state, "outcome": timer.outcome,
                "elapsed_sec": timer.elapsed_sec, "exit_code": timer.exit_code,
                "task_id": str(timer.task_id or ""), "role": str(timer.role or ""),
                "owner": program_owner(timer),
                "mine": is_my_program(timer, task_id=task_id, role=role)})
    if not out["mine"]:
        out["result"] = "not_mine"
        out["reason"] = not_mine_refusal(timer, task_id=task_id, role=role)
        return out
    if timer.state != "pending":
        out["result"] = "already_exited"
        out["reason"] = (f"{timer_id} 早就收口了（state={timer.state}, "
                         f"outcome={timer.outcome or '没记'}）—— 查过了，不是第二次杀掉；"
                         "这一行一个字都不改（幂等）")
        return out
    try:
        pid = int(timer.pid or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        out["reason"] = ("这一条账上没有 pid（attach_program_pid 没补上）⇒ 没有可停的对象；"
                         "程序行保持 pending，它还在不在看 program.list 的 running 那一格")
        return out
    if not process_alive(pid):
        out["result"] = "already_exited"
        out["reason"] = (f"pid {pid} 已经不在进程表上了 —— 查过了、它自己走掉的；"
                         "账上那条还是 pending（收口归起它的 program_span，这一刀不改行）")
        return out
    # ---- 第一刀 + 宽限窗口（"优雅"= 时机与告知，见 `_terminate_pid` 的 docstring）
    terminate = _terminate_pid(pid)
    out["terminate"] = terminate
    waited = _wait_until_gone(pid, float(grace_sec),
                              purpose="停程序：宽限期里等它自己收尾")
    # ---- 第二刀：只有还活着才动手（读数里写着走了哪条路）
    force: dict[str, Any] = {}
    if process_alive(pid):
        force = _force_kill_pid(pid)
        out["force_kill"] = force
        waited += _wait_until_gone(pid, float(wait_sec),
                                   purpose="停程序：真杀之后等它从进程表上消失")
    out["waited_sec"] = round(waited, 3)
    if process_alive(pid):
        out["result"] = "timeout"
        out["still_alive"] = [pid]
        out["state"] = timer.state
        out["reason"] = (f"pid {pid} 在 {float(grace_sec):g}+{float(wait_sec):g} 秒里没有消失"
                         f"（杀不动：{force.get('why') or terminate.get('why') or '原因没有读数'}）"
                         "—— 账上那条保持 pending、程序行不改：它还在跑这件事必须读得出来")
        return out
    # ---- 真没了：按 killed 收口（走既有的 finish_program），再推一次等它的人
    elapsed = _elapsed_of(timer)
    exit_code = _exit_code_of(pid)
    note_bits = [f"被点名停下（program.stop，操作者台账号 {task_id or '（没给）'}）"]
    if str(reason or "").strip():
        note_bits.append(str(reason).strip())
    if terminate.get("via"):
        note_bits.append(f"第一刀 {terminate['via']}")
    elif terminate.get("why"):
        note_bits.append(f"第一刀没发（{terminate['why']}）")
    if force.get("via"):
        note_bits.append(f"第二刀 {force['via']}")
    closed, state = finish_program(workspace, timer_id, outcome="killed",
                                   exit_code=exit_code, elapsed_sec=elapsed,
                                   note="；".join(note_bits))
    out.update({"result": "killed", "state": getattr(closed, "state", ""),
                "outcome": getattr(closed, "outcome", ""),
                "elapsed_sec": getattr(closed, "elapsed_sec", None),
                "exit_code": getattr(closed, "exit_code", None),
                "finish_state": state})
    out["reason"] = program_message(program=timer.program, outcome="killed",
                                    exit_code=out["exit_code"],
                                    elapsed_sec=out["elapsed_sec"],
                                    purpose=timer.purpose)
    wake = _wake_waiters(workspace, timer_id)
    out.update({"watching": int(wake.get("watching") or 0),
                "woken": int(wake.get("woken") or 0),
                "wake_ids": list(wake.get("wake_ids") or ()),
                "wake_checked": bool(wake.get("checked")),
                "wake_reason": str(wake.get("reason") or "")})
    return out


def stop_program(workspace: str | Path, timer_id: str, *, task_id: str,
                 role: str = "", grace_sec: float = PROGRAM_STOP_GRACE_SEC,
                 wait_sec: float = PROGRAM_STOP_WAIT_SEC,
                 reason: str = "") -> dict[str, Any]:
    """停掉一条"我这一趟起的"程序：先宽限、再真杀，然后按 `killed` 收口并唤醒等它的人。

    业主 2026-10-26 的 G1（逐字）：「重点完善子代理杀自己发出去的程序进程的工具」。

    ## 这个函数做四件，缺一件就等于没做

    1. 受控拒绝：不是这一趟起的（别人的 / 账上没有归属的）⇒ `result="not_mine"`，
       一个进程都不碰（`is_my_program` 是唯一判据，`not_mine_refusal` 是唯一拒信）；
    2. 先 terminate、超时再 kill：宽限 `PROGRAM_STOP_GRACE_SEC` 秒（`_terminate_pid`），
       过了窗口还在才 `_force_kill_pid`（Windows 上优先走作业对象，一次收整棵树）；
    3. 等它真的消失（`_wait_until_gone`，上限 `PROGRAM_STOP_WAIT_SEC`）——
       等不到就 `result="timeout"` 并点名还在跑的 pid，账上那条保持 pending；
    4. 收口 + 唤醒：真没了才 `finish_program(outcome="killed", elapsed_sec=…,
       exit_code=…)`，再推一次 `fire_due` 把等它的那几条叫醒。

    ## 不抛异常

    这四档是读数，不是异常（`PROGRAM_STOP_RESULTS`）。唯一的抛出是簿记读不成
    （`ClockStateError`）—— 那是"没查成"，由工具层折成 `checked=False`，
    绝不折成"没有这一条"。

    ## 已知边界（两条，都不假装）

    - pid 复用：这个 pid 是起进程那一刻记下的，且只在 pending 的账上；账上那条如果
      已经被别的进程占着同一个 pid，这一刀还是会落下去 —— pid 级杀法没有更强的
      身份校验（`Popen` 对象早就不在手上了）。
    - Windows 上的"优雅"是时机而不是信号语义（见 `_terminate_pid`）。
    """
    grace = max(0.0, float(grace_sec))
    wait = max(0.0, float(wait_sec))
    out = _stop_one_program(workspace, str(timer_id), task_id=str(task_id or ""),
                            role=str(role or ""), grace_sec=grace, wait_sec=wait,
                            reason=str(reason or ""))
    out["grace_sec"] = round(grace, 3)
    out["wait_sec"] = round(wait, 3)
    return out


def programs_owned(workspace: str | Path, *, task_id: str = "",
                   role: str = "", include_done: bool = False) -> dict[str, Any]:
    """这个工作区的程序按归属分桶（`program.list` 的读侧，判据也读这里）。

    四桶，一格都不折平：

    - `mine`：我这一趟起的（`is_my_program` 为真；`include_done` 决定含不含已收口的）；
    - `unowned`：账上没有归属的（改前存量的形态：`task_id` 空）—— 它们不归任何人，
      既不算我的，也不许被 `program.stop` 杀掉；单列出来是为了让人看见"存量还在"；
    - `others`：别人的（有归属、但不是我的）—— 只给条数，不给 pid（别人的程序不该
      在我的读数里被点名）；
    - 三态：簿记读不成 => `checked=False`（"没查成"不是"没有程序在跑"）。
    """
    out: dict[str, Any] = {"checked": False, "mine": [], "unowned": [], "others": 0,
                           "others_running": 0, "count": 0, "running": 0,
                           "reason": ""}
    try:
        rows = [t for t in book(workspace).all() if t.is_program]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"程序计时器读不成：{type(exc).__name__}: {exc}"
        return out
    if not include_done:
        rows = [t for t in rows if t.state == "pending"]
    mine: list[Timer] = []
    unowned: list[Timer] = []
    others = 0
    others_running = 0
    for timer in rows:
        if not str(timer.task_id or ""):
            unowned.append(timer)
        elif is_my_program(timer, task_id=task_id, role=role):
            mine.append(timer)
        else:
            others += 1
            if timer.state == "pending":
                others_running += 1
    out.update({"checked": True, "mine": mine, "unowned": unowned,
                "others": others, "others_running": others_running,
                "count": len(rows),
                "running": sum(1 for t in rows if t.state == "pending"),
                "reason": ""})
    return out


class ProgramSpan:
    """一条"等这个程序"的记账跨度（`program_span` 的产物，判据里的替身缝）。

    `start_program` 在进作用域时跑一次；`attach_pid` 起进程之后补 pid；
    `finish` 出作用域时收口。登记失败（没有工作区 / 簿记读不成）不拦程序运行，
    但必须留下 `problem` 与一条 `_PROGRAM_UNBOOKED` 读数 —— "账上没有"这件事本身
    要被读到，不许静默。
    """

    def __init__(self, *, program: str, argv: Iterable[Any] | None, workspace: str,
                 where: str, purpose: str, to: str, task_id: str, role: str) -> None:
        self.program = str(program or "")
        self.argv = [str(a) for a in (argv or ())]
        self.workspace = str(workspace or "")
        self.where = str(where or "")
        self.purpose = str(purpose or "")
        self.to = str(to or "self")
        self.task_id = str(task_id or "")
        self.role = str(role or "")
        self.timer: Timer | None = None
        self.started_monotonic: float = 0.0
        self.problem: str = ""
        self.outcome: str = ""

    # -- 登记 ---------------------------------------------------------
    def open(self) -> "ProgramSpan":
        self.started_monotonic = time.monotonic()
        if not self.workspace:
            self.problem = ("没有工作区 ⇒ 这条程序计时器登记不了"
                            "（程序照跑；这一格是「没登记」，不是「没有程序」）")
            _note_unbooked(self.program, self.argv, self.where, self.problem)
            return self
        try:
            self.timer = start_program(self.workspace, program=self.program,
                                       argv=self.argv, where=self.where,
                                       purpose=self.purpose, to=self.to,
                                       task_id=self.task_id, role=self.role)
        except Exception as exc:  # noqa: BLE001 - 登记失败不许拦住程序
            self.problem = f"程序计时器没登记成：{type(exc).__name__}: {exc}"
            _note_unbooked(self.program, self.argv, self.where, self.problem)
        return self

    def attach_pid(self, pid: int | None) -> None:
        """起好进程之后把 pid 补进账里（补不上不拦）。"""
        if self.timer is None or not self.workspace:
            return
        try:
            attach_program_pid(self.workspace, self.timer.timer_id, pid)
        except Exception as exc:  # noqa: BLE001 - 旁路
            self.problem = (self.problem + "；" if self.problem else "") + \
                f"pid 没补进程序计时器（{type(exc).__name__}: {exc}）"

    def finish(self, outcome: str = "exited", exit_code: int | None = None,
               note: str = "") -> dict[str, Any]:
        """收口这条跨度。返回读数（没登记成功时 `timer_id` 是空串 + `problem`）。"""
        if self.outcome:
            # 已经收过：第二次收口的读数照旧给，但不改账（与 `finish_program` 同一条纪律）。
            return self.reading()
        self.outcome = str(outcome or "exited")
        elapsed = max(0.0, time.monotonic() - self.started_monotonic)
        if self.timer is not None and self.workspace:
            try:
                finish_program(self.workspace, self.timer.timer_id, outcome=self.outcome,
                               exit_code=exit_code, elapsed_sec=elapsed, note=note)
            except Exception as exc:  # noqa: BLE001 - 旁路
                self.problem = (self.problem + "；" if self.problem else "") + \
                    f"程序计时器没收口成（{type(exc).__name__}: {exc}）"
        return self.reading()

    def reading(self) -> dict[str, Any]:
        if self.timer is None:
            return {"timer_id": "", "program": self.program, "argv_digest": argv_digest(self.argv),
                    "pid": None, "state": "unbooked", "outcome": self.outcome,
                    "elapsed_sec": None, "exit_code": None, "problem": self.problem}
        row = self.timer.program_row()
        row["problem"] = self.problem
        return row


@contextlib.contextmanager
def program_span(*, program: str, argv: Iterable[Any] | None = None,
                 workspace: str | Path | None = None, where: str = "",
                 purpose: str = "", to: str = "self", task_id: str = "",
                 role: str = "", exit_code: int | None = None,
                 outcome: str = "exited"):
    """在 `with` 里跑一个外部程序：进作用域登记一条程序计时器，出作用域收口。

    用法（每个"起程序并等它"的地方都用它，判据 `program_census()` 逐个数过）：

        with program_span(program="lean", argv=cmd, where="formalgw._default_run") as span:
            proc = subprocess.Popen(...)
            span.attach_pid(proc.pid)
            ...communicate(...)
            span.finish(outcome="exited", exit_code=proc.returncode)

    抛异常时自动收口成 `outcome="failed"`（异常照旧往外抛：记账不改语义）。
    `exit_code` 是给"单表达式"用法准备的：`with program_span(..., exit_code=rc)`
    出作用域时直接按它收口。
    """
    span = ProgramSpan(program=program, argv=argv, workspace=_workspace_of(workspace),
                       where=where, purpose=purpose, to=to, task_id=task_id, role=role).open()
    try:
        yield span
    except BaseException:
        span.finish(outcome="failed")
        raise
    else:
        span.finish(outcome=str(outcome or "exited"),
                    exit_code=(exit_code if exit_code is not None else None))


def _note_unbooked(program: str, argv: Iterable[Any], where: str, problem: str) -> None:
    with _EVENT_LOCK:
        _PROGRAM_UNBOOKED.append({"program": str(program or ""),
                                  "argv_digest": argv_digest(argv),
                                  "where": str(where or ""),
                                  "problem": str(problem or "")})
        del _PROGRAM_UNBOOKED[:-64]


def programs(workspace: str | Path) -> dict[str, Any]:
    """这个工作区里的程序计时器读数（业主 2026-10-27 点名的那几格）。

    三态：簿记读不成 => `checked=False`（不是"没有程序在跑"）。`running` 是
    `state == "pending"` 的那几条 —— 它是"现在真的有个程序在跑"的唯一账上证据。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "count": 0, "running": 0,
                           "unbooked": list(_PROGRAM_UNBOOKED), "reason": ""}
    try:
        rows = [t for t in book(workspace).all() if t.is_program]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"程序计时器读不成：{type(exc).__name__}: {exc}"
        return out
    out.update({"checked": True, "rows": [t.program_row() for t in rows],
                "count": len(rows),
                "running": sum(1 for t in rows if t.state == "pending"), "reason": ""})
    return out


def reset_programs() -> None:
    """清空进程内"没登记成的程序"那一格（判据之间的隔离点）。"""
    with _EVENT_LOCK:
        _PROGRAM_UNBOOKED.clear()


#: "起了进程"的调用名（`program_census()` 认这一张表）。
#:
#: 只认 `subprocess.<这些>` 与 `os.spawn*` / `os.system` / `os.popen` 这两族；
#: 光看末段名字会把 `prov.call(...)`、`self.run(...)` 这些普通调用一起算进来
#: （实测：按末段名字认会报出 130 多处假的"起进程"）。
PROGRAM_SPAWN_CALLS: tuple[str, ...] = ("Popen", "run", "call", "check_call",
                                        "check_output", "getoutput", "getstatusoutput")

#: `os` 那一族里算"起进程"的名字。
PROGRAM_OS_SPAWNS: tuple[str, ...] = ("spawnv", "spawnl", "spawnve", "spawnle",
                                      "system", "popen", "startfile")


#: 允许不进程序计时器登记的起进程点，逐条登记（与 `ALLOWED_RAW_WAITS` 同一档纪律）。
#:
#: 每条必须写 `why`（为什么它不该进账）与 `blocked_by`（谁挡着没改）。
#: 空 `blocked_by` = 这一处本来就不该进账（"它起的东西不是我们在等的那个程序"）。
PROGRAM_ALLOWED_RAW: tuple[dict[str, str], ...] = (
    {"path": "agentflow/webui/cacheface.py", "func": "_spawn_warm",
     "why": ("网页端「预热提示词缓存」那一下是脱手进程：起完立刻返回 pid 与日志路径，"
             "没有人等它 —— 它不属于「起一个程序并等它」；真正在等的那一趟循环自己记时钟"),
     "blocked_by": "webui/* 本轮禁改（边界：不许碰 webui/*）"},
    {"path": "agentflow/webui/writes.py", "func": "_spawn_run",
     "why": ("网页端「用一句话起一趟工作流」同样是脱手进程：返回 pid 就结束，等待发生在"
             "被起的那一趟循环里（它自己推时钟）"),
     "blocked_by": "webui/* 本轮禁改（边界：不许碰 webui/*）"},
    {"path": "agentflow/jobobject.py", "func": "selftest",
     "why": "作业对象那条路的自检（起一个睡的进程验证 job 句柄能把树收掉），不是生产路径",
     "blocked_by": ""},
)


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


class _SpawnVisitor(ast.NodeVisitor):
    """走一遍 AST，把"起进程"的调用点连它所在的函数一起记下来。"""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[dict[str, Any]] = []
        self.spans: list[str] = []

    def _enter(self, name: str) -> None:
        self.stack.append(str(name or "<anonymous>"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    @staticmethod
    def _dotted(node: ast.AST) -> str:
        """把 `a.b.c` 这种属性链还原成字符串（不是属性链 => 空串）。"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            head = _SpawnVisitor._dotted(node.value)
            return f"{head}.{node.attr}" if head else node.attr
        return ""

    @staticmethod
    def _spawn_of(node: ast.Call) -> str:
        """这个调用是不是"起进程"；是的话返回它的名字（`subprocess.run` 这种）。"""
        func = node.func
        if not isinstance(func, ast.Attribute):
            return ""
        owner = _SpawnVisitor._dotted(func.value)
        tail = owner.rsplit(".", 1)[-1] if owner else ""
        if tail == "subprocess" and func.attr in PROGRAM_SPAWN_CALLS:
            return func.attr
        if tail == "os" and func.attr in PROGRAM_OS_SPAWNS:
            return func.attr
        return ""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        func_name = "/".join(self.stack) or "<module>"
        spawn = self._spawn_of(node)
        if spawn:
            self.hits.append({"line": int(getattr(node, "lineno", 0) or 0),
                              "func": func_name, "call": spawn})
        else:
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if name == "program_span":
                self.spans.append(func_name)
        self.generic_visit(node)


def program_census(*, source_root: str | Path | Iterable[str | Path] | None = None,
                   refresh: bool = False) -> dict[str, Any]:
    """普查"起进程却没进程序计时器"的地方。返回 `{checked, findings, spans, files, reason}`。

    判据口径：一个起进程的调用点只要与某个 `program_span(...)` 落在同一个函数里，
    就算被管住了（`with` 把它包起来是调用方的事，这里是"这个函数里确实开了账"）。

    为什么用 AST 而不是正则：`program_span` 这几个字会出现在注释与 docstring 里
    （本文件就写着），正则会把说明文字算成"管住了"。

    ## 为什么要一份缓存（2026-10-27 补线时加的）

    它现在被 `coverage()` 调（`clock.coverage` 的 `programs_outside_clock` 那一格），
    而 `coverage()` 又被 `clock.now` 每个回合读一次 —— 没有缓存的话，一次 `clock.now`
    会把整棵 `src/agentflow` 重新 AST 一遍（实测 130 多个文件）。缓存与
    `raw_wait_census` 的 `_CENSUS_CACHE` 同一档：按扫描根做键、`refresh=True` 强制重扫。
    """
    global _PROGRAM_CENSUS_CACHE
    roots: list[Path]
    if source_root is None:
        roots = _census_roots()
    elif isinstance(source_root, (str, Path)):
        roots = [Path(source_root).resolve()]
    else:
        roots = [Path(r).resolve() for r in source_root]
    cache_key = "｜".join(str(r) for r in roots)
    if _PROGRAM_CENSUS_CACHE is not None and _PROGRAM_CENSUS_CACHE.get("key") == cache_key \
            and not refresh:
        return dict(_PROGRAM_CENSUS_CACHE["value"])
    findings: list[dict[str, Any]] = []
    governed: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    files = 0
    reasons: list[str] = []
    for root in roots:
        if not root.is_dir():
            reasons.append(f"扫描根不是目录：{root}")
            continue
        for path in _iter_py_files(root):
            files += 1
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception as exc:  # noqa: BLE001 - 读不成要说，不许当"没问题"
                reasons.append(f"{rel} 读不成：{type(exc).__name__}: {exc}")
                continue
            visitor = _SpawnVisitor()
            visitor.visit(tree)
            spanned = set(visitor.spans)
            for hit in visitor.hits:
                row = {"path": rel, "line": hit["line"], "func": hit["func"],
                       "call": hit["call"], "where": f"{rel}:{hit['line']}（{hit['func']}）"}
                if hit["func"] in spanned:
                    governed.append(row)
                    continue
                allowed = next((r for r in PROGRAM_ALLOWED_RAW
                                if r["path"] == rel
                                and (r["func"] == hit["func"]
                                     or hit["func"].endswith("/" + r["func"]))), None)
                if allowed is not None:
                    governed.append({**row, "why": allowed.get("why", ""),
                                     "blocked_by": allowed.get("blocked_by", "")})
                    continue
                findings.append(row)
            for func in sorted(spanned):
                spans.append({"path": rel, "func": func})
    findings.sort(key=lambda r: (r["path"], r["line"]))
    value = {"checked": not reasons, "files": files, "roots": [str(r) for r in roots],
             "findings": findings, "governed": governed, "spans": spans,
             "unbooked": list(_PROGRAM_UNBOOKED), "reason": "；".join(reasons)}
    _PROGRAM_CENSUS_CACHE = {"key": cache_key, "value": value}
    return dict(value)


def programs_running(workspace: str | Path) -> list[Timer]:
    """还在跑的程序计时器（账上 pending 的那几条）。读不成 => 空表 + 抛由调用方处置。"""
    return [t for t in book(workspace).all() if t.is_program and t.state == "pending"]


# ---------------------------------------------------------------- 等待任意计时器返回

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
        try:
            seq_mark = 0
            events = observed_events(since_seq=seq_mark)["events"]
        except Exception:  # noqa: BLE001 - 读不成只影响这一格
            events = []
        for e in events:
            if str(e.get("task_id") or "") != tid and str(e.get("from_task_id") or "") != tid:
                continue
            try:
                if since and str(e.get("at") or "") and _parse_iso(str(e["at"])) < _parse_iso(since):
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


# ---------------------------------------------------------------- 交差（业主 2026-10-27 第四条）

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
    rows = [dict(r) for r in doc.get("rows") or () if isinstance(r, Mapping)]
    if parent_task_id:
        want = str(parent_task_id)
        rows = [r for r in rows if str(r.get("parent_task_id") or "") == want]
    return {"checked": True, "rows": rows, "count": len(rows), "reason": "",
            "parent_task_id": str(parent_task_id or "")}


def reset_handoffs(workspace: str | Path) -> dict[str, Any]:
    """清空这个工作区的交差账（判据之间的隔离点；盘上的那一份一起清）。"""
    try:
        _atomic_json(handoff_path(workspace), {"schema": SCHEMA, "next_seq": 1, "rows": []})
    except OSError as exc:
        return {"checked": False, "reason": f"交差账写不成：{type(exc).__name__}: {exc}"}
    return {"checked": True, "reason": ""}


# ---------------------------------------------------------------- 工作区挂点

#: 进程缺省的工作区（装配期由工具层 / 循环设一次）。
#:
#: 为什么需要它：`program_span` 落在工具层之下（`agent_e` / `cancellation` /
#: `papercompile` …），那些地方拿不到 `AgentLoop.workspace_root`；而没有工作区就写不了
#: 程序计时器。挂点与 `_CURRENT_SESSION_ROOT` 同族（ContextVar + 一次进程缺省），
#: 于是"哪一趟在跑程序"这件事跟着执行上下文走，不会串到别的并发实例上。
_DEFAULT_WORKSPACE: str = ""
_CURRENT_WORKSPACE: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "agentflow_clock_workspace", default="")


def set_default_workspace(workspace: str | Path | None) -> str:
    """设进程缺省工作区（装配期一次）。返回设上去的那个绝对路径。"""
    global _DEFAULT_WORKSPACE
    _DEFAULT_WORKSPACE = str(Path(workspace).resolve()) if workspace else ""
    return _DEFAULT_WORKSPACE


def current_workspace() -> str:
    """此刻该往哪个工作区记账：挂上的 > 进程缺省 > 空串（= 这一层不知道）。"""
    got = str(_CURRENT_WORKSPACE.get() or "")
    return got or _DEFAULT_WORKSPACE


@contextlib.contextmanager
def using_workspace(workspace: str | Path):
    """在 `with` 里把时钟的工作区换成这个（循环跑一趟时用）。"""
    tok = _CURRENT_WORKSPACE.set(str(Path(workspace).resolve()) if workspace else "")
    try:
        yield
    finally:
        _CURRENT_WORKSPACE.reset(tok)


#: "这一趟 run 的号与角色"（业主 2026-10-27 的 G8：装配期起的程序也要有归属）。
#:
#: ## 为什么需要这一格
#:
#: `calling_as`（`conductor.py:2234`）只包住 `registry.call`（`agent_loop.py:9616`），
#: 于是装配期起的程序取不到号：真机 `projects/mp3-r4` 的 `tm-000001`
#: （`note="toolchain._version_of"`、`task_id=""`、`role=""`）正是
#: `agent_loop.py:6740` 拼提示词那一步起的。这不是少一格读数：`is_my_program`（`clock.py`
#: 的同名函数）把空归属一律判成"不是我的" ⇒ `program.stop` 对那一族结构性不可停。
#: 这一格回答的是"这一趟是谁"，不是"这一次工具调用是谁"（工具路径上两者同号）。
#:
#: 同一局真机的收场读数（14:00 停，44 条计时器）：13 条程序计时器里 12 条有号，
#: 全是工具路径起的（`agent_e._run_script` ×8、`papercompile.compile_paper` ×4）；
#: 唯一空的那一条就是装配期这条 `toolchain._version_of` —— 这一格补的正是它。
#:
#: ## 为什么另起两个 ContextVar，不去挂 `conductor._CURRENT_TASK_ID`
#:
#: 复用会让 `current_task_id()` 在装配期就有值 ⇒ `conductor._owner_task_id`、
#: `tools/table_tools._caller_task_id`、`secretary` 这些"读当前编号"的地方在装配期
#: 读到另一层语义。与 `_CURRENT_WORKSPACE` 同一条纪律：这一格只有时钟读。
#:
#: ## 为什么它比 `calling_as` 优先（顺序见 `_calling_identity`）
#:
#: 工具路径上两个来源是同一个号（`agent_loop.py:9616` 传的就是 `self.my_task_id`）
#: ⇒ 谁优先在工具路径上逐字节相同。差别只在召唤线程：`conductor.start_summon`
#: （`conductor.py:6152`）用 `copy_context()` 起线程，会把父的 `calling_as`
#: 复制进去 —— 子代理的装配期程序若读 `calling_as` 就会被记成父的；那是"错归属"，
#: 比空归属危险（`program.stop` 会因此放行"父停子的程序"）。真机今天没炸只因为
#: `agent_prompts._toolchain_readings` 是 `lru_cache`、根角色永远先跑。
#: 所以这一格必须赢：它回答"谁这一趟在跑"，而继承来的那个号回答"谁起的这个线程"。
#:
#: ## 已知缺口（不许留成暗坑）
#:
#: 作用域目前只包住装配那两行（`agent_loop.run` 的 `facts` 里那两次工具链读数）。
#: `run_as` 出作用域之后起的程序（循环正文、收尾那几个落点）仍然是空归属 ——
#: 它们要么在工具层之下由 `calling_as` 兜住，要么本来就没人拥有（`agentflow stop`
#: 那种 CLI 入口）。要连"收尾期"一起覆盖就得把作用域包到整趟 `run()`，那要重排
#: 那一段几百行缩进，收益只多那几个收尾落点 —— 业主 2026-10-27 裁定：先不包。
_CURRENT_RUN_TASK_ID: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "agentflow_run_task_id", default="")
_CURRENT_RUN_ROLE: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "agentflow_run_role", default="")


@contextlib.contextmanager
def run_as(task_id: str, role: str = ""):
    """在 `with` 里把"这一趟 run 是谁"挂上（挂法与 `using_workspace` 同形）。

    进作用域 set、出作用域 reset（异常也复位）。空号也照样挂（`task_id=""`）：
    空就是"这一趟没有号"，读数留空 —— 不猜一个。
    """
    token = _CURRENT_RUN_TASK_ID.set(str(task_id or ""))
    token_role = _CURRENT_RUN_ROLE.set(str(role or ""))
    try:
        yield
    finally:
        _CURRENT_RUN_TASK_ID.reset(token)
        _CURRENT_RUN_ROLE.reset(token_role)


def current_run_identity() -> tuple[str, str]:
    """这一趟 run 的 `(号, 角色)`；不在任何 run 里 ⇒ `("", "")`（没挂点，不是"零号"）。"""
    return _CURRENT_RUN_TASK_ID.get(), _CURRENT_RUN_ROLE.get()


# ---------------------------------------------------------------- 被时钟观测到的事件

#: 五类"必须被时钟观测到"的事件：
#: 子代理给父发消息、子代理收工提交、父给子答复（子挂机等父时同一个形）。
#: 2026-10-26 增两档（业主：「等父也要真的能醒」）：
#: - `handoff`：有人交差（`record_handoff`）—— 父代理不交差，所以它不能覆盖"等父"；
#: - `delivery`：一条话被投递（发件人 -> 收件人）。它与 `message` 的分工：
#:   `message` 认的是"谁产生了这条话"，`delivery` 认的是"这一趟投递真的发生了"，
#:   于是"等父/等子"两种方向都不必依赖发件人那一侧的措辞。
EVENT_KINDS: tuple[str, ...] = ("message", "submit", "reply", "handoff", "delivery")

#: 事件内容的截断长度（进到点消息的那一段摘要，不是全文）。
EVENT_EXCERPT: int = 300

#: 进程内的事件流上限：这是"最近发生了什么"的观测窗，不是审计账（审计在会话记录里）。
EVENT_BUFFER: int = 512


@dataclass
class ObservedEvent:
    """时钟观测到的一条事件。`target` 是"谁产生的"（被等的那一方）。"""

    kind: str
    target: str
    seq: int
    at: str = ""
    task_id: str = ""
    from_task_id: str = ""
    to_task_id: str = ""
    role: str = ""
    content: str = ""
    message_id: str = ""

    def row(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "target": self.target, "seq": self.seq, "at": self.at,
            "task_id": self.task_id, "from_task_id": self.from_task_id,
            "to_task_id": self.to_task_id, "role": self.role,
            "content": self.content, "message_id": self.message_id,
        }


_EVENTS: list[ObservedEvent] = []
_EVENT_COUNTS: dict[str, int] = {k: 0 for k in EVENT_KINDS}
_EVENT_SEQ = 0
_EVENT_LOCK = threading.Lock()


def observe_event(kind: str, *, task_id: str = "", from_task_id: str = "",
                  to_task_id: str = "", role: str = "", content: str = "",
                  message_id: str = "") -> ObservedEvent:
    """记一条"被时钟观测到的事件"（发消息 / 收工提交 / 答复）。

    它做两件事：把事件记进观测窗（`observed_events` 读），并让等这个对象的那几条
    `wait_for` 立刻可判 due（`due_reason` 会在下一个 `fire_due` 里认领它）。

    为什么在这里而不在会话/台账那一侧：时钟负责的是"挂机 — 唤醒 — 现场读数"，
    内容投递仍归 mailbox（业主 2026-10-25：「两条不许互相替代」）。这里只留"发生过
    一条什么事件、谁产生的、摘要是什么"，唤醒时把它抄进那句话里。
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
        return event


def observe_message(rec: Mapping[str, Any]) -> ObservedEvent | None:
    """从一条会话事件里认出"发消息 / 答复"，转成时钟事件。返回 `None` = 不关时钟的事。

    认法（三态归到三类里，不许漏）：

    - `kind != "agent_message"` => 不是消息，返回 `None`；
    - 有 `reply_to` => `reply`（对某条消息的答复）；
    - 其余 => `message`。

    `target`（谁产生的）优先取 `from_task_id`（发信人那件活），其次取 `from`
    （角色名）—— 等的是任务号就按任务号对上，等的是角色就按角色对上。
    """
    if str(rec.get("kind") or "") != "agent_message":
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


def waiters(workspace: str | Path) -> dict[str, Any]:
    """挂机读数：谁挂在时钟上、挂了多久、挂机期间它跑了几步。

    业主点名的三档：`parked` / `woke` / `cancelled`；`parked` 仍算活跃，但必须与
    "正在跑"分开列（`active = running + parked`），且 `parked` 的不许被当成卡住。
    """
    reading = now()
    bucket = book(workspace)
    rows: list[dict[str, Any]] = []
    for timer in bucket.all():
        if not timer.is_park:
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


def _event_seq() -> int:
    """当前事件序号（起表时记下来，只有这之后的事件才算"被等对象的新动静"）。"""
    with _EVENT_LOCK:
        return int(_EVENT_SEQ)


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


def _parse_target_loose(value: Any) -> tuple[str, str] | None:
    """解析 `wait_for` 的写法；解析不了返回 `None`（不抛 —— 调用方在判到点）。"""
    try:
        return parse_wait_for(value)
    except ClockError:
        return None


# ---------------------------------------------------------------- 到点动作


def due_timers(workspace: str | Path, *, reading: Reading | None = None) -> list[Timer]:
    """到期且还没被投递的计时器。读不到时钟 => 空表（不是"全部到点"）。"""
    got = reading if reading is not None else now()
    if got.status == "unknown":
        return []
    pending = book(workspace).pending()
    targets = _probe_targets(pending)
    out: list[Timer] = []
    for timer in pending:
        reason, _why = timer.due_reason(got, targets.get(_target_key(timer)))
        if reason:
            out.append(timer)
    return out


def _target_key(timer: Timer) -> str:
    """"等谁"的读口键：解析后的对象优先（起表时查过一次，不必每次重解析）。"""
    return timer.wait_for_resolved or timer.wait_for


def _probe_targets(timers: Iterable[Timer]) -> dict[str, tuple[str, str, str]]:
    """一次把这一批计时器等的东西各问一遍（同一个对象只问一次）。"""
    out: dict[str, tuple[str, str, str]] = {}
    for timer in timers:
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


def fire_due(workspace: str | Path | None = None) -> dict[str, Any]:
    """把到点的计时器与周期性巡查交给注册的到点动作；计时器成功的落成 fired。

    三态：`checked=False` 表示这一次没查成（时钟读不到 / 簿记读不成），
    调用方不许把它读成"没有到点的计时器"。

    周期性巡查不在这个函数里"到点即消耗"：它每响一次就把 `next_at` 前移一拍，
    同一拍里最多补 `MAX_CATCHUP_FIRES` 次（假时钟一次前进一小时而周期是 20 分钟时，
    三次报醒都要发出去，但不许因为时钟被拨得很远就无限补）。
    """
    reading = now()
    report: dict[str, Any] = {"checked": True, "fired": [], "deferred": [],
                              "errors": [], "periodic_fired": [], "reason": ""}
    if reading.status == "unknown":
        report["checked"] = False
        report["reason"] = f"时钟读不到（{reading.reason or '两个来源都不可用'}）=> 判不了 due"
        return report
    roots = [str(Path(workspace).resolve())] if workspace is not None else list(_BOOKS)
    for root in roots:
        try:
            bucket = book(root)
        except ClockStateError as exc:
            report["checked"] = False
            report["reason"] = (report["reason"] + "；" if report["reason"] else "") + str(exc)
            continue
        pending = bucket.pending()
        targets = _probe_targets(pending)
        for timer in pending:
            key = _target_key(timer)
            reason, why = timer.due_reason(reading, targets.get(key))
            if not reason:
                _remember_wait_state(bucket, timer, targets.get(key), why)
                continue
            if _DUE_HANDLER is None:
                report["deferred"].append({
                    "timer_id": timer.timer_id,
                    "reason": "没有注册到点动作（set_due_handler 还没接上）",
                })
                continue
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
                continue
            except Exception as exc:  # noqa: BLE001 - 一条坏掉不带走别的计时器
                timer.triggered_by = ""
                timer.woke_reason = ""
                timer.message = ""
                timer.feedback = ""
                report["errors"].append({"timer_id": timer.timer_id,
                                         "error": f"{type(exc).__name__}: {exc}"})
                continue
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
            try:
                bucket.save()
            except ClockStateError as exc:
                report["errors"].append({"timer_id": timer.timer_id, "error": str(exc)})
                continue
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
        report["periodic_fired"].extend(
            _fire_periodics(bucket, reading, report))
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


# ---------------------------------------------------------------- 等待账


def waits_path(workspace: str | Path) -> Path:
    """等待账的落盘路径（`<工作区>/out/clock/waits.json`）。"""
    return Path(workspace).resolve() / WAITS_REL


#: 进程内的等待账：`(kind, where, purpose, waited_for)` -> 一行聚合。
_LEDGER: dict[str, dict[str, Any]] = {}
_LEDGER_LOCK = threading.Lock()
_LEDGER_WRITTEN = 0


def _ledger_key(kind: str, where: str, purpose: str, waited_for: str) -> str:
    return "｜".join((str(kind or "io"), str(where or ""), str(purpose or ""),
                      str(waited_for or "")))


def note_wait(seconds: float, purpose: str, *, kind: str = "io", where: str = "",
              waited_for: str = "", slept: float | None = None,
              skipped: bool = False) -> dict[str, Any]:
    """记一条等待（不睡）。返回这一行聚合后的读数。

    `purpose` 在这里是必填的：调用点是框架自己的代码，写不出一句目的说明这个等待
    根本不该存在；缺了直接抛（与代理面"忘填目的不报错"刻意不同 —— 那边是人/
    模型的疏漏，这边是我们自己的账）。
    """
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "框架内部的等待必须写目的（purpose）：写不出目的的等待不许存在")
    try:
        asked = float(seconds)
    except (TypeError, ValueError):
        raise ClockParamError(f"等待时长必须是数，收到 {seconds!r}") from None
    if asked < 0:
        raise ClockParamError(f"等待时长不能是负数，收到 {seconds!r}")
    took = asked if slept is None else float(slept)
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    key = _ledger_key(kind, where, body, waited_for)
    global _LEDGER_WRITTEN
    with _LEDGER_LOCK:
        row = _LEDGER.get(key)
        if row is None:
            row = {"kind": str(kind or "io"), "where": str(where or ""),
                   "purpose": body, "waited_for": str(waited_for or ""),
                   "calls": 0, "asked_sec": 0.0, "slept_sec": 0.0,
                   "first_at": stamp, "last_at": stamp,
                   "skipped": 0}
            _LEDGER[key] = row
        row["calls"] = int(row["calls"]) + 1
        row["asked_sec"] = round(float(row["asked_sec"]) + asked, 6)
        row["slept_sec"] = round(float(row["slept_sec"]) + took, 6)
        row["last_at"] = stamp
        if skipped:
            row["skipped"] = int(row["skipped"]) + 1
        _LEDGER_WRITTEN += 1
        return dict(row)


def await_io(seconds: float, purpose: str, *, kind: str = "io", where: str = "",
             waited_for: str = "", sleep: Callable[[float], None] | None = None
             ) -> dict[str, Any]:
    """真睡 `seconds` 秒（保持原语义），并在主时钟的账上记一条。

    这是框架内部所有"等一会儿"的唯一入口。`kind` 说这是哪一类等待（`retry` /
    `rate_limit` / `poll` / `drain` / `user` …），`where` 说它落在哪个位置
    （`fetch._download_via` 这种），`purpose` 说为什么等 —— 三样都进账，
    `clock.now` 的复合读数把账汇总成 `waits_recorded`。

    假时钟在装的时候不免掉真睡是不可接受的：判据里等 20 分钟没有意义，而且
    "主时钟是假的"本来就意味着"时间由我拨"。所以当前时钟是假的时候真睡被免掉，
    账上照记，`skipped` 计数 +1（读数里看得见"这几条没真等"）。
    """
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "框架内部的等待必须写目的（purpose）：写不出目的的等待不许存在")
    step = float(seconds)
    if step < 0:
        raise ClockParamError(f"等待时长不能是负数，收到 {seconds!r}")
    fake = str(getattr(_CLOCK, "name", "real") or "") == "fake"
    do_sleep = sleep if sleep is not None else (None if fake else time.sleep)
    took = 0.0
    if do_sleep is not None and step > 0:
        start = time.monotonic()
        do_sleep(step)
        took = time.monotonic() - start
    return note_wait(step, body, kind=kind, where=where, waited_for=waited_for,
                     slept=took if do_sleep is not None else 0.0,
                     skipped=fake or do_sleep is None)


def note_process_wait(elapsed_sec: float, *, where: str, waited_for: str = "",
                      purpose: str = "等外部进程退出（实测耗时，不是 timeout 上限）"
                      ) -> dict[str, Any]:
    """记一次"等外部进程"的实测耗时（`kind="external_process"`）。

    为什么这些点不换成 `await_io`：阻塞发生在 `Popen.communicate(timeout=…)` 里面，
    换成 sleep 会把"进程一退就返回"变成"睡满才返回"，取消语义随之坏掉。账要的是
    "这一次实际等了多久"，那不需要改阻塞方式 —— 所以记的是实测耗时，不是 timeout。

    `where` 必须点名到"哪一个 communicate"：同一个函数里两处 timeout 不同的等待
    要能分开读（`agent_e._run_script/poll` 与 `/final`），不许合成一行。
    """
    return note_wait(elapsed_sec, purpose, kind="external_process", where=where,
                     waited_for=waited_for, slept=elapsed_sec)


def waits(*, kind: str | None = None) -> dict[str, Any]:
    """读等待账（进程内聚合）。返回 `{rows, count, calls, asked_sec, slept_sec, checked}`。"""
    with _LEDGER_LOCK:
        rows = [dict(r) for r in _LEDGER.values()
                if kind is None or str(r.get("kind") or "") == str(kind)]
    rows.sort(key=lambda r: (str(r.get("kind") or ""), str(r.get("where") or ""),
                             str(r.get("purpose") or "")))
    return {
        "checked": True,
        "rows": rows,
        "count": len(rows),
        "calls": sum(int(r.get("calls") or 0) for r in rows),
        "asked_sec": round(sum(float(r.get("asked_sec") or 0.0) for r in rows), 6),
        "slept_sec": round(sum(float(r.get("slept_sec") or 0.0) for r in rows), 6),
        "skipped": sum(int(r.get("skipped") or 0) for r in rows),
        "reason": "",
    }


def reset_waits() -> None:
    """清空进程内的等待账（判据之间的隔离点；盘上的那一份不动）。"""
    global _LEDGER_WRITTEN
    with _LEDGER_LOCK:
        _LEDGER.clear()
        _LEDGER_WRITTEN = 0


def flush_waits(workspace: str | Path) -> dict[str, Any]:
    """把等待账落到 `<工作区>/out/clock/waits.json`。返回读数（写不成 => checked=False）。"""
    got = waits()
    doc = {"schema": SCHEMA, "saved_at": "", "rows": got["rows"],
           "count": got["count"], "calls": got["calls"],
           "asked_sec": got["asked_sec"], "slept_sec": got["slept_sec"]}
    reading = now()
    doc["saved_at"] = _iso(reading.wall) if reading.wall is not None else ""
    try:
        _atomic_json(waits_path(workspace), doc)
    except OSError as exc:
        return {"checked": False, "reason": f"等待账写不成：{type(exc).__name__}: {exc}",
                **{k: got[k] for k in ("rows", "count", "calls", "asked_sec", "slept_sec")}}
    return {"checked": True, "reason": "", "path": str(waits_path(workspace)),
            **{k: got[k] for k in ("rows", "count", "calls", "asked_sec", "slept_sec")}}


# ---------------------------------------------------------------- 原始等待的普查


#: 普查认的三种形态。`sleep` 是"真睡"（计时类）；`wait` / `blocking_io` 是"阻塞在同步
#: 原语或子进程调用上"（等的是事件/进程本身，不是钟点）。
CENSUS_FORMS: tuple[str, ...] = ("sleep", "sleep_ref", "wait", "blocking_io")

#: 允许留在普查之外（不走 `await_io` / `note_wait`）的原始等待，逐条登记。
#:
#: 每条必须写 `why`（为什么它可以不记账）与 `blocked_by`（谁挡着没改）。
#: 空 `blocked_by` = 这一处本来就该留在账外（只有主时钟本体这一条）。
ALLOWED_RAW_WAITS: tuple[dict[str, str], ...] = (
    {"path": "agentflow/clock.py", "func": "await_io", "form": "sleep",
     "why": "主时钟本体的真睡：它就是这本账的写入口，不能再由别人来记",
     "blocked_by": ""},
    {"path": "agentflow/clock.py", "func": "await_io", "form": "sleep_ref",
     "why": "同上（`await_io` 里那个 `... else time.sleep` 的绑定是它的实现本体）",
     "blocked_by": ""},
)

#: 已经接上 `note_wait` 的原始等待（阻塞由原语完成，账照样记）。
#:
#: 登记在这里的作用是"普查能把它们与没人管的那些分开"：前者是记账的等待，
#: 后者才是缺口。`path/func` 用类名/函数名点路（行号会漂，名字不会）。
GOVERNED_PRIMITIVE_WAITS: tuple[tuple[str, str], ...] = (
    ("agentflow/conductor.py", "SummonHandle/wait"),
    ("agentflow/scheduler.py", "WaveHandle/wait_any"),
    ("agentflow/scheduler.py", "WaveHandle/wait_all"),
    ("agentflow/scheduler.py", "WaveHandle/_wait_wave"),
    ("agentflow/scheduler.py", "WaveHandle/_dispatch"),
    # 2026-10-25 第二批（业主放行）：三处 `communicate(timeout=)` 用
    # `note_wait(elapsed, kind="external_process")` 记账 —— 阻塞方式不变（换了会毁
    # 取消语义），账上记的是实测耗时。
    ("agentflow/cancellation.py", "run_cancellable"),
    ("agentflow/agent_e/core.py", "_run_script"),
)

#: 明确留在账外的"阻塞型"等待（等的是进程/事件本身，换成 sleep 会改变语义）。
#:
#: 今天这一栏是空的：上一批的三处已经全部接上 `note_wait`。留这张表是为了
#: "下次有人要加一处例外"时有一个必须写理由的落点（而不是散在代码注释里）。
EXEMPT_PRIMITIVE_WAITS: tuple[dict[str, str], ...] = ()

#: 普查的默认扫描根（`src`，于是 rel 路径形如 `agentflow/clock.py`）。
_CENSUS_ROOTS: list[str] | None = None
_CENSUS_CACHE: dict[str, Any] | None = None


def set_census_roots(roots: Iterable[str | Path] | None) -> None:
    """换普查的扫描根（判据用；`None` = 回到默认的包目录）。"""
    global _CENSUS_ROOTS, _CENSUS_CACHE, _PROGRAM_CENSUS_CACHE
    _CENSUS_ROOTS = [str(Path(r).resolve()) for r in roots] if roots is not None else None
    _CENSUS_CACHE = None
    _PROGRAM_CENSUS_CACHE = None


def _census_roots() -> list[Path]:
    if _CENSUS_ROOTS:
        return [Path(r) for r in _CENSUS_ROOTS]
    return [Path(__file__).resolve().parent.parent]


def _wait_form(node: ast.Call) -> str:
    """这个调用算不算"原始等待"，算的话是哪一形态。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr == "sleep":
            return "sleep"
        if attr in ("wait", "wait_for"):
            # `self.wait(...)` 是方法自调用（原语在别处，普查会在那一处点到），
            # 不算"这里又有一个原始等待"。
            if attr == "wait" and isinstance(func.value, ast.Name) \
                    and func.value.id == "self":
                return ""
            return "wait"
        if attr in ("communicate", "join") and any(
                getattr(k, "arg", None) == "timeout" for k in node.keywords):
            return "blocking_io"
        return ""
    if isinstance(func, ast.Name) and func.id == "sleep":
        return "sleep"
    return ""


class _WaitVisitor(ast.NodeVisitor):
    """走一遍一棵 AST，把原始等待点全部记下来（带所在函数/方法的名字）。

    两种形态都记：调用（`.sleep(...)`）与裸引用（`= time.sleep`）。只记调用会漏掉
    最要命的那一种回退 —— `self._sleep = sleep or time.sleep` 只是把真睡绑回来，
    之后再调 `self._sleep(...)` 时普查看不见那个绑定（实测：fetch / modelgw 的
    默认等待正是这一形，改回它不会有任何调用点叫 `time.sleep`）。
    """

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[dict[str, Any]] = []
        self.refs: list[dict[str, Any]] = []

    def _enter(self, name: str) -> None:
        self.stack.append(str(name or "<anonymous>"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (node.attr == "sleep" and isinstance(node.value, ast.Name)
                and node.value.id == "time"):
            self.refs.append({
                "line": int(getattr(node, "lineno", 0) or 0),
                "form": "sleep_ref",
                "func": "/".join(self.stack) or "<module>",
            })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        form = _wait_form(node)
        if form:
            self.hits.append({
                "line": int(getattr(node, "lineno", 0) or 0),
                "form": form,
                "func": "/".join(self.stack) or "<module>",
            })
        self.generic_visit(node)

    def findings(self) -> list[dict[str, Any]]:
        """调用点 + 那些"不是某个调用的被调者"的裸引用。"""
        call_lines = {(int(h["line"]), h["func"]) for h in self.hits
                      if h["form"] == "sleep"}
        out = list(self.hits)
        for ref in self.refs:
            if (int(ref["line"]), ref["func"]) in call_lines:
                continue   # `time.sleep(...)` 已经在调用点里记过一次
            out.append(ref)
        return out


def _iter_source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _exempt_for(path: str, func: str, form: str) -> dict[str, str] | None:
    """这条原始等待是不是逐条登记过的例外。`func` 按名字尾对齐（类名会加前缀）。"""
    for row in ALLOWED_RAW_WAITS + EXEMPT_PRIMITIVE_WAITS:
        if row["path"] != path or row["form"] != form:
            continue
        want = str(row.get("func") or "")
        if not want or want == func or func.endswith("/" + want):
            return row
    return None


def _primitive_governed(path: str, func: str) -> bool:
    return any(p == path and (f == func or func.endswith("/" + f))
               for p, f in GOVERNED_PRIMITIVE_WAITS)


def raw_wait_census(*, source_root: str | Path | Iterable[str | Path] | None = None,
                    refresh: bool = False) -> dict[str, Any]:
    """普查"没走主时钟账的原始等待"。返回 `{checked, findings, files, reason}`。

    它认三种形态（`CENSUS_FORMS`）：`time.sleep(...)` / `.wait(...)` /
    `communicate(timeout=...)`。用 AST 而不是正则：正则会命中注释、docstring 与
    字符串里的 `time.sleep`（实测：本仓库有一处 docstring 讲 `sleep(30)`，
    正则会把那段话算成一个等待点）。
    """
    global _CENSUS_CACHE
    roots: list[Path]
    if source_root is None:
        roots = _census_roots()
    elif isinstance(source_root, (str, Path)):
        roots = [Path(source_root).resolve()]
    else:
        roots = [Path(r).resolve() for r in source_root]
    cache_key = "｜".join(str(r) for r in roots)
    if _CENSUS_CACHE is not None and _CENSUS_CACHE.get("key") == cache_key \
            and not refresh:
        return dict(_CENSUS_CACHE["value"])
    findings: list[dict[str, Any]] = []
    exempt: list[dict[str, Any]] = []
    files = 0
    reasons: list[str] = []
    for root in roots:
        if not root.is_dir():
            reasons.append(f"扫描根不是目录：{root}")
            continue
        for path in _iter_source_files(root):
            files += 1
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception as exc:  # noqa: BLE001 - 读不成要说，不许当"没问题"
                reasons.append(f"{rel} 读不成：{type(exc).__name__}: {exc}")
                continue
            visitor = _WaitVisitor()
            visitor.visit(tree)
            for hit in visitor.findings():
                row = {"path": rel, "line": hit["line"], "func": hit["func"],
                       "form": hit["form"],
                       "where": f"{rel}:{hit['line']}（{hit['func']}）"}
                allowed = _exempt_for(rel, hit["func"], hit["form"])
                if allowed is not None:
                    exempt.append({**row, "why": allowed.get("why", ""),
                                   "blocked_by": allowed.get("blocked_by", "")})
                elif hit["form"] == "sleep":
                    findings.append(row)
                elif _primitive_governed(rel, hit["func"]):
                    findings.append({**row, "governed": True})
                else:
                    findings.append(row)
    findings.sort(key=lambda r: (r["path"], r["line"]))
    exempt.sort(key=lambda r: (r["path"], r["line"]))
    value = {
        "checked": not reasons,
        "files": files,
        "roots": [str(r) for r in roots],
        "findings": findings,
        "exempt": exempt,
        "reason": "；".join(reasons),
    }
    _CENSUS_CACHE = {"key": cache_key, "value": value}
    return dict(value)


def coverage(*, source_root: str | Path | Iterable[str | Path] | None = None,
             refresh: bool = False) -> dict[str, Any]:
    """"主时钟控制了所有计时类工作没有"的机器判据。返回一份复合读数。

    读数分四层，刻意不折平：

    - `waits_outside_clock`：真睡（`time.sleep` 一类）里没走主时钟账的处数。
      它是业主点名的那个判据，目标 0。
    - `waits_on_primitives_ungoverned`：阻塞在同步原语/子进程上、既没记账也没登记的处数。
    - `waits_exempt`：逐条登记在 `ALLOWED_RAW_WAITS` / `EXEMPT_PRIMITIVE_WAITS` 里的例外，
      每条带 `why` 与 `blocked_by`（是谁挡着没改）。
    - `covers_all_timed_work`：前两层都空且没有例外时才为真。今天它是假的 ——
      例外里有两处是被禁改区挡住的，把它们并进 0 就等于把没做完的活报成做完了。
    - `programs_outside_clock`：起进程却没进程序计时器的处数（`program_census()` 的
      findings 数）。它与 `waits_outside_clock` 是同一档纪律的两件事：前者问"等了没记账"，
      后者问"程序在跑而账上没有计时器"（业主 2026-10-27：「运行一个程序时会自动启动
      一个计时器」）。它不并进 `covers_all_timed_work`：那一格的口径是"计时类工作"，
      而程序计时器是这次新加的一档，并进去等于悄悄改了那条既有判据的含义。
    """
    census = raw_wait_census(source_root=source_root, refresh=refresh)
    ledger = waits()
    pcensus = program_census(source_root=source_root, refresh=refresh)
    if not census["checked"]:
        return {
            "checked": False, "waits_outside_clock": None,
            "waits_outside_where": [], "waits_exempt": [], "waits_exempt_count": None,
            "waits_master_clock": [], "waits_master_clock_count": None,
            "waits_on_primitives": None, "waits_on_primitives_ungoverned": None,
            "waits_recorded": None, "waits_recorded_sec": None,
            "covers_all_timed_work": None, "files_scanned": census["files"],
            "programs_checked": bool(pcensus.get("checked")),
            "programs_outside_clock": (len(pcensus.get("findings") or ())
                                       if pcensus.get("checked") else None),
            "programs_outside_where": [f["where"] for f in (pcensus.get("findings") or ())],
            "programs_files_scanned": pcensus.get("files"),
            "reason": census["reason"] or "普查没查成",
        }
    outside = [f for f in census["findings"] if f["form"].startswith("sleep")]
    prims = [f for f in census["findings"] if not f["form"].startswith("sleep")]
    ungoverned = [f for f in prims if not f.get("governed")]
    # 主时钟本体那一条不是"绕过账的等待"：它就是这本账的写入口。单列一格，
    # 不并进 `waits_exempt`（并进去会让"还有几处没进账"这个读数虚高一处）。
    exempt_all = list(census["exempt"])
    master = [e for e in exempt_all if str(e.get("path") or "").endswith("clock.py")]
    exempt = [e for e in exempt_all if not str(e.get("path") or "").endswith("clock.py")]
    blocked = [e for e in exempt if str(e.get("blocked_by") or "").strip()]
    reason = ""
    if outside:
        reason = f"还有 {len(outside)} 处真睡没走主时钟：{'; '.join(f['where'] for f in outside)}"
    elif ungoverned:
        reason = (f"还有 {len(ungoverned)} 处阻塞等待没记账也没登记："
                  f"{'; '.join(f['where'] for f in ungoverned)}")
    elif exempt:
        reason = (f"有 {len(exempt)} 处逐条登记的例外，其中 {len(blocked)} 处被禁改区挡着："
                  f"{'; '.join(e['where'] + '（' + (e.get('blocked_by') or '自带例外') + '）' for e in exempt)}")
    return {
        "checked": True,
        "waits_outside_clock": len(outside),
        "waits_outside_where": [f["where"] for f in outside],
        "waits_exempt": exempt,
        "waits_exempt_count": len(exempt),
        "waits_master_clock": master,
        "waits_master_clock_count": len(master),
        "waits_on_primitives": len(prims),
        "waits_on_primitives_ungoverned": len(ungoverned),
        "waits_recorded": int(ledger["calls"]),
        "waits_recorded_groups": int(ledger["count"]),
        "waits_recorded_sec": float(ledger["asked_sec"]),
        "covers_all_timed_work": not outside and not ungoverned and not exempt,
        "files_scanned": census["files"],
        "programs_checked": bool(pcensus.get("checked")),
        "programs_outside_clock": (len(pcensus.get("findings") or ())
                                   if pcensus.get("checked") else None),
        "programs_outside_where": [f["where"] for f in (pcensus.get("findings") or ())],
        "programs_files_scanned": pcensus.get("files"),
        "reason": reason,
    }


# ---------------------------------------------------------------- 唤醒标记


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


__all__ = [
    "ALLOWED_RAW_WAITS",
    "ARGV_EXCERPT",
    "CENSUS_FORMS",
    "ClockError",
    "ClockNotFound",
    "ClockNoTimersToWait",
    "ClockParamError",
    "ClockStateError",
    "ClockUnreadable",
    "ClockWaiterNotResolvable",
    "NO_TIMERS_TO_WAIT",
    "WAITER_NOT_RESOLVABLE",
    "no_timers_refusal",
    "waiter_refusal",
    "waiting_on_text",
    "DUE_TRIGGERS",
    "EVENT_BUFFER",
    "EVENT_EXCERPT",
    "EVENT_KINDS",
    "DueDeferred",
    "HANDOFF_REL",
    "HANDOFF_SUBJECT",
    "ObservedEvent",
    "PROGRAM_ALLOWED_RAW",
    "PROGRAM_OUTCOMES",
    "PROGRAM_SPAWN_CALLS",
    "PROGRAM_STOP_GRACE_SEC",
    "PROGRAM_STOP_POLL_SEC",
    "PROGRAM_STOP_RESULTS",
    "PROGRAM_STOP_WAIT_SEC",
    "PURPOSE_FROM_TARGET",
    "PURPOSE_SOURCES",
    "PATROL_DUE_HEAD",
    "PATROL_INTERVAL_SEC",
    "PATROL_REASON",
    "PATROL_ROLE",
    "ProgramSpan",
    "WAIT_ANY_REL",
    "WOKE_REASONS",
    "EXEMPT_PRIMITIVE_WAITS",
    "FakeClock",
    "GOVERNED_PRIMITIVE_WAITS",
    "MAX_CATCHUP_FIRES",
    "PERIODIC_STATES",
    "PURPOSE_MISSING_TEXT",
    "PURPOSE_PROMPT",
    "Periodic",
    "PeriodicShot",
    "READING_STATES",
    "Reading",
    "RealClock",
    "SCHEMA",
    "STATE_REL",
    "TARGET_STATES",
    "TIMER_KINDS",
    "TIMER_STATES",
    "Timer",
    "TimerBook",
    "WAITS_REL",
    "WAIT_FOR_KINDS",
    "WAKE_REL",
    "advance",
    "argv_digest",
    "attach_program_pid",
    "await_io",
    "book",
    "cancel_timer",
    "cancel_wait_any",
    "consume_wakes",
    "coverage",
    "current",
    "current_run_identity",
    "current_workspace",
    "due_message",
    "due_timers",
    "finish_program",
    "fire_due",
    "flush_waits",
    "handoff_path",
    "human_sec",
    "now",
    "note_wait",
    "observe_event",
    "observe_message",
    "observed_events",
    "parse_iso",
    "parse_wait_for",
    "pending_wakes",
    "periodics",
    "iso",
    "is_my_program",
    "not_mine_refusal",
    "process_alive",
    "process_started",
    "program_census",
    "program_message",
    "program_owner",
    "program_span",
    "programs",
    "programs_owned",
    "programs_running",
    "program_purpose",
    "purpose_of",
    "is_patrol_timer",
    "next_patrol",
    "patrol_sop_text",
    "raw_wait_census",
    "read_handoffs",
    "mark_handoff_seen",
    "read_wakes",
    "read_wait_any",
    "start_patrol_timer",
    "record_handoff",
    "record_wake",
    "request_wait_any",
    "reset_handoffs",
    "reset_programs",
    "retire_hint",
    "RETIRED_TIMING_TOOLS",
    "reset",
    "reset_books",
    "reset_observed_events",
    "reset_waits",
    "run_as",
    "set_census_roots",
    "set_default_workspace",
    "set_due_handler",
    "set_purpose",
    "set_target_probe",
    "start_alarm",
    "start_periodic",
    "start_program",
    "start_timer",
    "state_path",
    "stop_periodic",
    "stop_program",
    "target_state",
    "timers",
    "timers_missing_purpose",
    "use",
    "using_workspace",
    "wait_any_path",
    "wait_any_reading",
    "waits",
    "waits_path",
    "wake_path",
]
