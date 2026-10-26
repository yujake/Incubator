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
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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

#: 目的的来源受控词表（业主 2026-10-27 的第二条裁定）：
#: `given` = 调用方显式给的；`target_task` = 从被等对象的 task 文本自动填的；
#: `unavailable` = 两边都没有（此时 `purpose_missing` 为真，沿用既有追问语义）。
PURPOSE_SOURCES: tuple[str, ...] = ("given", "target_task", "unavailable")

#: 从被等对象那一边抄目的时的截断长度（业主定死 200 字）。
PURPOSE_FROM_TARGET: int = 200

#: 程序计时器里 `argv_digest` 的截断长度（它是摘要，不是完整命令行）。
ARGV_EXCERPT: int = 200

#: 周期性条目状态的受控词表。三个都是终态，不许回退。
PERIODIC_STATES: tuple[str, ...] = ("running", "stopped", "until_reached", "cancelled")

#: `wait_for` 的两种指称：等某个代理（名册名 / `agent:<名>`）、等某件活（绝对编号 / `task:<号>`）。
WAIT_FOR_KINDS: tuple[str, ...] = ("agent", "task")

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


def parse_wait_for(value: Any) -> tuple[str, str]:
    """把 `wait_for` 的写法解析成 `(指称, 代号)`。解析失败 => `ClockParamError`。

    认这几种写法（业主 2026-10-25：「值形如名册名 / 绝对编号 / `task:<号>` / `agent:<名>`」）：

    | 写法 | 指称 | 代号 |
    |---|---|---|
    | `task:t000012` | `task` | `t000012` |
    | `t000012`（绝对编号） | `task` | `t000012` |
    | `agent:D1` | `agent` | `D1` |
    | `D1`（名册名） | `agent` | `D1` |

    为什么这里只解析不核实存在：核实要读台账/名册，那是工具层的事（本模块不拖 Store
    进来）。存在性由注册进来的探针答（`set_target_probe`），三态见 `TARGET_STATES`。
    """
    text = str(value or "").strip()
    if not text:
        raise ClockParamError(
            "wait_for 是空串 —— 等谁必须点名（名册名 / 绝对编号 / task:<号> / agent:<名>）")
    low = text.lower()
    if low.startswith("task:"):
        kind, ref = "task", text[5:].strip()
    elif low.startswith("agent:"):
        kind, ref = "agent", text[6:].strip()
    elif low.startswith("t") and text[1:].isdigit():
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

#: 缺目的时的追问句（逐字；到点消息、工具读数、唤醒标记三处读同一份）。
PURPOSE_PROMPT: str = (
    "你起的这一次等待还没写目的 —— 补一句目的（例如「等待20分钟+周期性巡查」），"
    "否则到点那条报醒里就没有目的可念；补法：clock.timer_purpose(purpose=…)")


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


def due_message(*, purpose: str, waited_sec: float | None, created_at: Any,
                fired_at: Any, every_sec: float | None = None,
                fires: int | None = None, feedback: str = "",
                feedback_label: str = "", waited_target: str = "",
                woke_reason: str = "") -> str:
    """到点那条消息的唯一拼法（业主 2026-10-25 定死格式）。

    一次性：

        时间到：<目的>｜等了 <时长>（起于 <HH:MM:SS>，到于 <HH:MM:SS>）

    周期性：

        巡查时间到：<目的>｜每 <间隔>一次（第 <N> 次）

    等谁的再加两样：等到了对方的事件就把它的反馈抄在后面（`feedback`），到点还没
    等到就写清"等的是 X，它还没交/没说"。缺目的那一趟把目的位置写成
    `（目的未填）` 并追问补一句。

    三样（目的 / 等待时间 / 时间到）必须在同一句里 —— 判据断言的是这句原文。
    """
    body = str(purpose or "").strip()
    missing = not body
    shown = PURPOSE_MISSING_TEXT if missing else body
    if every_sec is not None:
        head = f"巡查时间到：{shown}｜每 {human_sec(every_sec)}一次（第 {int(fires or 0)} 次）"
    else:
        start = _hhmmss(created_at if isinstance(created_at, datetime)
                        else (_parse_iso(created_at) if created_at else None))
        end = _hhmmss(fired_at if isinstance(fired_at, datetime)
                      else (_parse_iso(fired_at) if fired_at else None))
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
        return f"{head}{tail}。{PURPOSE_PROMPT}"
    return f"{head}{tail}"


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
    #: 起表时把 `wait_for` 解析成的具体对象（`task:t000012` / `agent:D1`）。
    wait_for_resolved: str = ""
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
        got = asdict(self)
        got.pop("after_sec", None)
        return got

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Timer":
        fields = {f for f in cls.__dataclass_fields__ if f != "after_sec"}
        return cls(**{k: v for k, v in dict(raw).items() if k in fields})

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


def _atomic_json(path: Path, doc: Mapping[str, Any]) -> None:
    """原子写一份 JSON（同目录 tmp + os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(dict(doc), ensure_ascii=False, indent=2)
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
        """上一次报醒那句话（周期性巡查的定死格式）。"""
        return due_message(purpose=self.purpose, waited_sec=None,
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

    def set_purpose(self, entry_id: str, purpose: str) -> tuple[Any, str]:
        """给一条已受理的计时器/周期性巡查补上目的。返回 `(条目或 None, 结果)`。

        结果与 `cancel` 同一族纪律：`filled`（这一次填上了）/ `already_filled`
        （早有目的，不动它）/ `not_found` / `not_pending`（已到点/已取消的不许改）。
        为什么"早有目的"不覆盖：补目的是补空白，不是改历史 —— 覆盖掉会让"到点消息
        里念的那句目的"与"起表时写的那句"对不上，而两条都进过审计。

        填上之后 `purpose_source` 记成 `given`（这是有人显式写进去的一句，不是从被等
        对象的 task 抄来的）：于是读数能回答"这句目的到底从哪来"。
        """
        want = str(entry_id or "")
        timer = self._timers.get(want)
        if timer is not None:
            if timer.state != "pending":
                return timer, "not_pending"
            if not timer.purpose_missing:
                return timer, "already_filled"
            timer.reason = str(purpose or "").strip()
            timer.purpose_source = "given"
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
    if kind == "timer":
        if after_sec is not None and target:
            raise ClockParamError(
                "after_sec 与 wait_for 只能选一个：等时间给 after_sec（多久之后），"
                "等谁给 wait_for（名册名 / 绝对编号 / task:<号> / agent:<名>）；"
                "两个都给就不知道按哪一个判到了，这一条不排")
        if after_sec is None and not target:
            raise ClockParamError(
                "必须给 after_sec（等多久）或 wait_for（等谁）之一 —— "
                "计时类任务的申请形状是「等待时间（或等待谁）+ 目的」，"
                "例如 M 的巡视写 after_sec=1200 + reason=周期性巡查")
    if target:
        wait_kind, wait_ref = parse_wait_for(target)
        probe = _probe_read(workspace, wait_kind, wait_ref)
        wait_state, resolved, why = _judge_target(probe, wait_kind, wait_ref)
        if probe.get("checked") and not probe.get("found"):
            raise ClockNotFound(
                f"等的东西不存在：{target}（按 {wait_kind}:{wait_ref} 去台账/名册里找过，"
                f"没有这一行 —— {probe.get('why') or '查过了、没有'}）；"
                "别等一个不存在的东西，先确认它的名字或编号")
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
    """起一个一次性计时器：等一段时间（`after_sec`）或等谁收口（`wait_for`），二选一。"""
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
        probe = _probe_read(workspace, wait_kind, wait_ref)
        wait_state, resolved, why = _judge_target(probe, wait_kind, wait_ref)
        if probe.get("checked") and not probe.get("found"):
            raise ClockNotFound(
                f"等的东西不存在：{target}（按 {wait_kind}:{wait_ref} 找过，没有这一行 —— "
                f"{probe.get('why') or '查过了、没有'}）；别等一个不存在的东西")
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
                purpose: str) -> tuple[Any, str]:
    """给一条已受理的等待补上目的（同一个编号，不是新建一条）。"""
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "补的目的还是空的 —— 补目的就是为了让到点那条报醒里有话可念，"
            "别拿空串去填它")
    return book(workspace).set_purpose(entry_id, body)


def timers_missing_purpose(workspace: str | Path) -> list[dict[str, Any]]:
    """还没写目的的待发条目（读数用：谁的报醒里会没有目的）。"""
    rows: list[dict[str, Any]] = []
    bucket = book(workspace)
    for timer in bucket.pending():
        if timer.purpose_missing:
            rows.append({"id": timer.timer_id, "kind": timer.kind, "prompt": PURPOSE_PROMPT})
    for periodic in bucket.running_periodics():
        if periodic.purpose_missing:
            rows.append({"id": periodic.periodic_id, "kind": "periodic",
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


def start_program(workspace: str | Path, *, program: str, argv: Iterable[Any] | None = None,
                  where: str = "", purpose: str = "", to: str = "self",
                  task_id: str = "", role: str = "",
                  pid: int | None = None) -> Timer:
    """起一条程序计时器（`kind="program"`）：程序开始跑的那一刻登记，结束时收口。

    与时间/等谁那两档的差别只有一处：它没有 due —— 到点就是"程序结束"这件事，
    由 `finish_program` 写。所以它不会因为时钟读不到而被拒（登记用的是事件，不是钟点）；
    时钟读不到时 `created_at` 留空（不是编一个 1970）。
    """
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    timer = Timer(
        timer_id="",
        kind="program",
        reason=str(purpose or "").strip(),
        to=str(to or "self"),
        task_id=str(task_id or ""),
        role=str(role or ""),
        workspace=str(Path(workspace).resolve()),
        created_at=stamp,
        due_at="",
        clock_token=str(getattr(_CLOCK, "token", "") or ""),
        state="pending",
        purpose_source=("given" if str(purpose or "").strip() else "unavailable"),
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
                                   purpose=timer.purpose)
    bucket.save()
    return timer, "fired"


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
    """
    tid = str(task_id or "").strip()
    if not tid:
        raise ClockParamError("等待任意计时器返回要一个台账号：不知道该让谁挂机")
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


# ---------------------------------------------------------------- 被时钟观测到的事件

#: 三类"必须被时钟观测到"的事件（业主 2026-10-25）：
#: 子代理给父发消息、子代理收工提交、父给子答复（子挂机等父时同一个形）。
EVENT_KINDS: tuple[str, ...] = ("message", "submit", "reply")

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
    return observe_event(
        kind,
        task_id=str(rec.get("from_task_id") or ""),
        from_task_id=str(rec.get("from_task_id") or ""),
        to_task_id=str(rec.get("to") or ""),
        role=str(rec.get("from") or ""),
        content=content,
        message_id=str(rec.get("msg_id") or ""),
    )


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
            timer.message = due_message(
                purpose=timer.purpose, waited_sec=timer.waited_seconds(reading),
                created_at=timer.created_at,
                fired_at=_iso(reading.wall) if reading.wall is not None else "",
                feedback=feedback, feedback_label=label,
                waited_target=timer.wait_for, woke_reason=timer.woke_reason)
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
            message=due_message(purpose=per.purpose, waited_sec=None,
                                created_at=None, fired_at=None,
                                every_sec=per.every_sec, fires=per.fires),
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
    "ClockParamError",
    "ClockStateError",
    "ClockUnreadable",
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
    "PURPOSE_FROM_TARGET",
    "PURPOSE_SOURCES",
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
    "process_started",
    "program_census",
    "program_message",
    "program_span",
    "programs",
    "programs_running",
    "raw_wait_census",
    "read_handoffs",
    "mark_handoff_seen",
    "read_wakes",
    "read_wait_any",
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
