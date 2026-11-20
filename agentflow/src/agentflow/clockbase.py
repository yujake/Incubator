# -*- coding: utf-8 -*-
"""系统时钟的底座：词表、三态读数、时间格式、错误与拒绝、事件原语。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py`（6,777 行）按依赖方向由底向上拆。
这一层是依赖图的最底：只 import 标准库与 `canonical.json_default`，不 import 本包内
任何时钟模块。上层（`clockrun` / `clocktimer` / `clockbook` / `clockprogram` /
`clockfire` …）各自单向 import 这里 —— 方向写死为「上层 → 本层」，不许反向。

## 装了什么

* 状态词表与落盘位置常量（`READING_STATES` / `TIMER_STATES` / `STATE_REL` / `SCHEMA` …）；
* 时钟异常族（`ClockError` 及子类）与两条受控拒绝的拼句（`waiter_refusal` /
  `no_timers_refusal`）；
* 三态读数 `Reading` 与时间往返（`_reading` / `_iso` / `_parse_iso` / `human_sec` /
  `near_seconds`）—— 「读不到不折成 0」这条纪律的落点；
* `wait_for` 的解析 `parse_wait_for`（名册名 / 绝对编号 / `task:` / `agent:` 四种指称）；
* 周期性巡查的文案常量（M 的巡视口径写死在这里，`due_message` 与 `clockpatrol` 共用）；
* 事件总线的原语（`ObservedEvent` / `_EVENTS` / `_EVENT_LOCK` / `EVENT_KINDS` …）——
  只放"谁记着这件事"，`observe_event` 那扇门在 `clockevents.py`。

## 与 `clock.py` 的关系

`clock.py` 现在是门面：它 `from .clockbase import ...` 再导出（`from .clock import X`
的调用点一个字都没改）。名字、实现、语义与拆分前逐字相同 —— 判据见
`temp/split1_move.py` 的 AST 比对（每个顶层名的 AST dump 拆前拆后逐字相同）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
import threading

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
#: `lifeline` 是"兜底计时器"那一档（业主 2026-10-29）：框架维护、代理无感、被打掉即续、
#: 收工后仍续；三态里"只挂着它"就是静默（判据 `clock.is_lifeline`）。
TIMER_KINDS: tuple[str, ...] = ("timer", "alarm", "periodic", "program", "lifeline")

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

#: 补偿对账的间隔（秒）。为什么是 30 秒，三个理由缺一不可：
#:
#: 1. 它是"事件漏发"的唯一兜底（见下面的 `EVENT_CLOSE_HOOKS`）。比它更短的间隔换不到
#:    正确性，只换来更勤的全表扫；更长则一条漏发事件的等待最多挂 30 秒才被救回来，
#:    而业主给的最短的一档等待是 M 的巡视 20 分钟（`PATROL_INTERVAL_SEC`）——
#:    30 秒是它的 1/40，读的人分不出"漏发被救回"与"事件当场到"。
#: 2. 一次对账的成本是 O(全表行数) + O(不同等待对象个数)（实测 N=3000 时 ~9ms）。
#:    30 秒做一次 ≈ 0.03% 的占空比；若改成每拍都对账（改前的行为），几千条计时器时
#:    每一步要付两次 9ms。
#: 3. 它同时是 `next_wake_in_sec` 的一个上界：挂机的一拍最多睡到下一次对账，
#:    于是"漏发事件"最迟在对账那一刻被救回来，而挂机不许用一个长拍把这一格压过去。
#:
#: 它与 `PARK_SLICE_MAX_SEC`（300 秒）的先后：300 秒是"没有更早的事情时最多睡多久"，
#: 30 秒是本模块自己的安全阀 —— 两者取较早者，所以对账永远先到。
RECONCILE_EVERY_SEC: float = 30.0

#: "该查一次反查索引了"的登记表（消账的唯一登记处）。
#:
#: 键是产生点（`clock` 模块里的函数名），值是这个产生点凭什么对象键去查索引。
#: 为什么是一张表而不是散落的 if：将来再加一个收工路径时，"漏登记"要能被机器扫出来。
#: 强制点在 `_close_waiters_for_event`：`source` 不在这张表里 => 当场 `ClockParamError`
#: （不是"静默不消账"）。判据 `test_event_hooks_are_all_registered` 逐行断言这张表
#: 的每一行都真的被走到过。
#:
#: 覆盖关系（谁把谁的路径带进来）：
#:
#: - `observe_event`：事件流的唯一漏斗。子代理收工（`conductor.SummonHandle.settle`
#:   的 `_observe_submit`）、消息/答复到达（`observe_message`，会话写路径的旁路钩子）、
#:   交差（`record_handoff`）都汇到它这一处 ⇒ 它们不必各自再登记一行；
#: - `finish_program`：程序收口（`ProgramSpan.finish` / `stop_program` / 超时杀）
#:   都走它，于是等 `program:<号>` 的表在这里消账；
#: - `stop_program`：停机开关让"等这条程序"的表立刻收口（它内部也会调
#:   `finish_program`，单列一行是为了让读数分得清是谁触发的）。
EVENT_CLOSE_HOOKS: dict[str, str] = {
    "observe_event": "事件流：message / submit / reply / handoff / delivery 五类各按对象键撞一次索引",
    "record_handoff": "交差：父侧等 task:<子> 的那几条当场判掉（它自己也发 handoff 事件）",
    "finish_program": "程序收口：等 program:<号> 的那几条当场判掉",
    "stop_program": "停机：被停的程序按 killed 收口之后，等它的表立刻收口",
}

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
        "② 或者按交差收工：干完活、又没有你在等的表 ⇒ 就停在这里（父代理那一侧把它记为静默；父的消息或你的表回来会把你叫起来）。")


class ClockStateError(ClockError):
    """状态文件读不成或写不成。这不是"没有计时器"，是"没查成"。"""


class DueDeferred(ClockError):
    """这一条到点了，但到点动作今天做不了（例如没有绑定 store）。

    刻意不把它折成"已经投递"：计时器保持 pending，下一次 `fire_due` 再试。
    """


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


def _event_seq() -> int:
    """当前事件序号（起表时记下来，只有这之后的事件才算"被等对象的新动静"）。"""
    with _EVENT_LOCK:
        return int(_EVENT_SEQ)


def _parse_target_loose(value: Any) -> tuple[str, str] | None:
    """解析 `wait_for` 的写法；解析不了返回 `None`（不抛 —— 调用方在判到点）。"""
    try:
        return parse_wait_for(value)
    except ClockError:
        return None


#: 兜底计时器的 kind。它由框架维护、代理对它无感（不进模型可见读数）、每次被打掉
#: （事件命中、到点被投递）就自动续一条、收工之后仍续。三态里"只挂着它"就是静默；
#: 挂着模型自己起的表才是待机（业主 2026-10-29 第 2、5 条）。
LIFELINE_KIND: str = "lifeline"

#: 兜底计时器的目的文本：非空 ⇒ `purpose_missing` 天然为假，不会被"缺目的"追问
#: （照 `PATROL_REASON` 的先例：框架自己起的表必须自带目的，别让模型去补）。
LIFELINE_REASON: str = "保活：等与你有关的东西（框架自带，代理不用管它）"


#: 抑制标记：兜底表被"永久撤掉"（销号）时写进 `note`。
#: 为什么要有它：被销号的代理可能还睡在自己的挂机里，醒来会按"被打掉就续"再挂一条，
#: 于是盘上出现"号已销、计时器回来了"——那是不可逆的鬼读数，谁也没法复原。
LIFELINE_SUPPRESSED: str = "suppressed:retired"
