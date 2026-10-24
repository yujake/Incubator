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
"""

from __future__ import annotations

import json
import os
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

#: 两份落盘文件的 schema 版本。加字段不抬它；改字段含义或删字段才抬。
SCHEMA: int = 1

#: 读数状态的受控词表。三态，不许折平。
READING_STATES: tuple[str, ...] = ("ok", "partial", "unknown")

#: 计时器状态的受控词表。`fired` 与 `cancelled` 都是终态，不许回退。
TIMER_STATES: tuple[str, ...] = ("pending", "fired", "cancelled")

#: 计时器种类的受控词表。
TIMER_KINDS: tuple[str, ...] = ("timer", "alarm")


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
    global _CLOCK, _PROCESS_START
    _CLOCK = RealClock()
    _PROCESS_START = _CLOCK.read()
    _BOOKS.clear()


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
    #: 运行期附加的字段（不落盘）：起表时调的 `after_sec`，只为回显。
    after_sec: float | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in TIMER_KINDS:
            raise ValueError(f"kind 必须是 {TIMER_KINDS} 之一，收到 {self.kind!r}")
        if self.state not in TIMER_STATES:
            raise ValueError(f"state 必须是 {TIMER_STATES} 之一，收到 {self.state!r}")

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

    def is_due(self, reading: Reading) -> bool:
        """到点判定的唯一实现。读不到时钟 => 判不了（False，不是"没到"）。"""
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

    def remaining_seconds(self, reading: Reading | None = None) -> float | None:
        """还剩多少秒。读不到时钟 => None（不是 0）。"""
        got = reading if reading is not None else now()
        if self.state != "pending":
            return 0.0
        if got.status == "unknown":
            return None
        token = str(getattr(_CLOCK, "token", "") or "")
        if (self.clock_token and token and self.clock_token == token
                and self.due_mono is not None and got.monotonic is not None):
            return max(0.0, float(self.due_mono) - float(got.monotonic))
        due = self.due_datetime()
        if due is not None and got.wall is not None:
            return max(0.0, (due - got.wall).total_seconds())
        return None

    def row(self, reading: Reading | None = None) -> dict[str, Any]:
        """给工具面/判据读的一行（键集稳定，嵌套不深）。"""
        got = reading if reading is not None else now()
        return {
            "timer_id": self.timer_id,
            "kind": self.kind,
            "reason": self.reason,
            "to": self.to,
            "task_id": self.task_id,
            "role": self.role,
            "created_at": self.created_at,
            "due_at": self.due_at,
            "state": self.state,
            "fired_at": self.fired_at,
            "remaining_sec": self.remaining_seconds(got),
            "mailbox_item_id": self.mailbox_item_id,
            "wake_id": self.wake_id,
            "note": self.note,
        }


def _atomic_json(path: Path, doc: Mapping[str, Any]) -> None:
    """原子写一份 JSON（同目录 tmp + os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(dict(doc), ensure_ascii=False, indent=2)
    tmp.write_text(text + "\n", encoding="utf-8", newline="")
    os.replace(tmp, path)


class TimerBook:
    """一个工作区的计时器簿记，落盘成 `<工作区>/out/clock/state.json`。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._timers: dict[str, Timer] = {}
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
        # 发号器不许比盘上已有的号小（手工改过 state.json 之后也不撞号）。
        for timer in self._timers.values():
            tail = timer.timer_id.rsplit("-", 1)[-1]
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
        self.save()
        return timer, "cancelled"


def book(workspace: str | Path) -> TimerBook:
    """取（或建）这个工作区的计时器簿记；第一次取会读盘。"""
    root = str(Path(workspace).resolve())
    if root not in _BOOKS:
        _BOOKS[root] = TimerBook(root)
    return _BOOKS[root].require_loaded()


def _new_timer(workspace: str | Path, *, kind: str, reason: str, to: str,
               task_id: str, role: str, after_sec: float | None = None,
               at: Any = None) -> Timer:
    """组装一条待发计时器（不含 ID），并算出 due。"""
    body = str(reason or "").strip()
    if not body:
        raise ClockParamError("reason 不能为空：到点消息要能说明为什么叫醒收件人")
    reading = now()
    if reading.status == "unknown" or reading.wall is None:
        raise ClockUnreadable(
            f"时钟读不到（{reading.reason or '两个来源都不可用'}）=> 到点判不了，"
            "这一条不排（不许折成 0）")
    if kind == "timer":
        if after_sec is None:
            raise ClockParamError("计时器必须给 after_sec")
        step = float(after_sec)
        if step <= 0:
            raise ClockParamError(f"after_sec 必须是正数，收到 {after_sec!r}")
        if step > 10 * 366 * 24 * 3600:
            raise ClockParamError("after_sec 超过十年：这不是计时器，是许愿")
        due = reading.wall + timedelta(seconds=step)
        due_mono = (reading.monotonic + step
                    if reading.monotonic is not None else None)
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
    assert due is not None
    return Timer(
        timer_id="",
        kind=kind,
        reason=body,
        to=str(to or "self"),
        task_id=str(task_id or ""),
        role=str(role or ""),
        workspace=str(Path(workspace).resolve()),
        created_at=_iso(reading.wall),
        due_at=_iso(due),
        due_epoch=due.timestamp(),
        due_mono=due_mono,
        clock_token=str(getattr(_CLOCK, "token", "") or ""),
        state="pending",
        after_sec=(float(after_sec) if after_sec is not None else None),
    )


def start_timer(workspace: str | Path, *, after_sec: float, reason: str,
                to: str = "self", task_id: str = "", role: str = "") -> Timer:
    """起一个一次性计时器（相对现在多久之后）。"""
    timer = _new_timer(workspace, kind="timer", reason=reason, to=to,
                       task_id=task_id, role=role, after_sec=after_sec)
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    return timer


def start_alarm(workspace: str | Path, *, at: Any, reason: str,
                to: str = "self", task_id: str = "", role: str = "") -> Timer:
    """定一个到绝对时刻的闹钟（一次性）。"""
    timer = _new_timer(workspace, kind="alarm", reason=reason, to=to,
                       task_id=task_id, role=role, at=at)
    bucket = book(workspace)
    timer.timer_id = bucket.allocate("tm")
    bucket.add(timer)
    return timer


def cancel_timer(workspace: str | Path, timer_id: str) -> tuple[Timer | None, str]:
    """取消一条计时器。返回 `(计时器或 None, 落成的状态或 not_found)`。"""
    return book(workspace).cancel(timer_id)


def timers(workspace: str | Path) -> list[Timer]:
    """这个工作区的全部计时器（含已到点与已取消，按 due 排序）。"""
    return book(workspace).all()


# ---------------------------------------------------------------- 到点动作


def due_timers(workspace: str | Path, *, reading: Reading | None = None) -> list[Timer]:
    """到期且还没被投递的计时器。读不到时钟 => 空表（不是"全部到点"）。"""
    got = reading if reading is not None else now()
    if got.status == "unknown":
        return []
    return [t for t in book(workspace).pending() if t.is_due(got)]


def fire_due(workspace: str | Path | None = None) -> dict[str, Any]:
    """把到点的计时器交给注册的到点动作；成功的落成 fired。

    三态：`checked=False` 表示这一次没查成（时钟读不到 / 簿记读不成），
    调用方不许把它读成"没有到点的计时器"。
    """
    reading = now()
    report: dict[str, Any] = {"checked": True, "fired": [], "deferred": [],
                              "errors": [], "reason": ""}
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
        for timer in bucket.pending():
            if not timer.is_due(reading):
                continue
            if _DUE_HANDLER is None:
                report["deferred"].append({
                    "timer_id": timer.timer_id,
                    "reason": "没有注册到点动作（set_due_handler 还没接上）",
                })
                continue
            try:
                receipt = _DUE_HANDLER(timer)
            except DueDeferred as exc:
                # 到点了，但今天做不了：保持 pending，下一次再试。
                report["deferred"].append({"timer_id": timer.timer_id,
                                           "reason": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 - 一条坏掉不带走别的计时器
                report["errors"].append({"timer_id": timer.timer_id,
                                         "error": f"{type(exc).__name__}: {exc}"})
                continue
            got = dict(receipt or {})
            timer.state = "fired"
            timer.fired_at = _iso(reading.wall) if reading.wall is not None else ""
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
                "mailbox_item_id": timer.mailbox_item_id,
                "wake_id": timer.wake_id,
            })
    return report


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
    "ClockError",
    "ClockNotFound",
    "ClockParamError",
    "ClockStateError",
    "ClockUnreadable",
    "DueDeferred",
    "FakeClock",
    "READING_STATES",
    "Reading",
    "RealClock",
    "SCHEMA",
    "STATE_REL",
    "TIMER_KINDS",
    "TIMER_STATES",
    "Timer",
    "TimerBook",
    "WAKE_REL",
    "advance",
    "book",
    "cancel_timer",
    "consume_wakes",
    "current",
    "due_timers",
    "fire_due",
    "now",
    "parse_iso",
    "pending_wakes",
    "iso",
    "process_started",
    "read_wakes",
    "record_wake",
    "reset",
    "reset_books",
    "set_due_handler",
    "start_alarm",
    "start_timer",
    "state_path",
    "timers",
    "use",
    "wake_path",
]
