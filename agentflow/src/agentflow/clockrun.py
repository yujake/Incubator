# -*- coding: utf-8 -*-
"""系统时钟的取时口与进程内簿记：唯一取时、复位、工作区与身份注入、到点消息拼句。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第二刀。它坐在
`clockbase`（词表与三态读数）之上，只 import `clockbase` 与标准库；上层
（`clockevents` / `clocktimer` / `clockbook` / `clockprogram` / `clockfire` …）单向 import 这里。

## 装了什么

* 唯一取时口：`RealClock` / `_CLOCK` / `current` / `use` / `now` / `advance` /
  `state_path` / `process_started` / `_PROCESS_START`；假时钟类本身在 `clockfire.py`
  （它 `advance` 之后要真的 `fire_due`，那一跳必须摆在到点调度那一层）；
* 进程内簿记容器：`_BOOKS`（一个工作区一份的计时器簿记）、`_PROGRAM_UNBOOKED`
  （起进程却没进程序计时器的登记）、`_RESOLVED_ROOTS`（根路径解析缓存）、`_PROBE_CALLS`
  （探针调用计数）；
* 工作区与身份的注入点：`_DEFAULT_WORKSPACE` / `_CURRENT_WORKSPACE` /
  `_CURRENT_RUN_TASK_ID` / `_CURRENT_RUN_ROLE` 与 `current_workspace` /
  `using_workspace` / `run_as` / `current_run_identity` / `set_default_workspace`；
* 复位三条：`reset`（真时钟 + 清簿记 + 清程序账 + 清默认工作区）/ `reset_books` /
  `reset_programs`；
* 到点消息的唯一拼句 `due_message`（业主定死的格式：「时间到：<目的>｜等了 <时长>
  （起于 <HH:MM:SS>，到于 <HH:MM:SS>）」）—— 工具层与唤醒标记都读它，不许各拼一份；
* `_atomic_json`（先写临时文件再换名，落盘不半截）、`purpose_of` / `waiting_on_text`
  两条目的读法、`is_patrol_timer` / `is_lifeline` / `lifeline_key` 三条口径判定、
  `_resolve_root`（根路径解析的唯一实现）。

## 为什么"重新赋值的量"与"它的每一个读写点"必须同处一个模块

Python 的 `global X; X = ...` 只改本模块命名空间里的 `X`；`from .clockrun import X`
拿到的是 import 那一刻的快照，再赋值不会传过来。所以可变量没有"跨模块共享"这回事，
只有"归谁所有"。本模块拥有的每一个可变量，它的全部读写点都在本文件里：
`_CLOCK`（写：`use` / `reset`；读：`now` / `advance` / `current` / `state_path` …）、
`_PROCESS_START`（写：`reset`；读：`process_started`）、
`_DEFAULT_WORKSPACE`（写：`reset` / `set_default_workspace`；读：`current_workspace`）。

`_CLOCK` 在别处（`clocktimer` / `clockprogram`）的读取点一律走 `current()` 这个读口
（2026-11-20 的 2d47ea0f 就是那次改指向）；`_DUE_HANDLER` 与 `_TARGET_PROBE` 同理，
它们跟着自己的读写点留在 `clockfire.py` / `clocktimer.py`。这条约束由
`temp/split1_move.py` 的守门判据机械核（第一刀曾踩过一次 split-brain，见 cff86fe6）。

## 与 `clock.py` 的关系

`clock.py` 是门面：它 `from .clockrun import ...` 再导出，调用点一个字都不用改。
拆分前后每个顶层名的 AST dump 逐字相同（判据 `temp/split1_move.py` 的 [equiv] 自检）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping
import contextlib
import contextvars
import json
import os
import threading
import time
import uuid
from .canonical import json_default
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockParamError,
    EVENT_EXCERPT,
    LIFELINE_KIND,
    PATROL_DUE_HEAD,
    PATROL_REASON,
    PURPOSE_MISSING_TEXT,
    PURPOSE_PROMPT,
    STATE_REL,
    UTC,
    _EVENT_LOCK,
    _hhmmss,
    _parse_iso,
    _reading,
    human_sec,
)

def is_patrol_timer(entry: Any) -> bool:
    """这一条是不是轮查计时器（只读目的那一格）。

    收三种输入：`Timer`、盘上那一行、`record_wake` 落的唤醒事件 —— 三者都经
    `purpose_of` 取值，于是"哪一条是轮查"全仓只有一个读法（与 `purpose_of` 同一条纪律：
    各写一份取法迟早分家，而分家之后没有任何判据会红）。

    `kind` 刻意不参与判定：轮查复用 `kind="timer"`，理由见 `PATROL_REASON`。
    """
    return purpose_of(entry).strip() == PATROL_REASON


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


#: 进程内唯一的时钟。判据用 `use(...)` 换掉它，生产里从不换。
_CLOCK: Any = RealClock()

#: 工作区 -> 计时器簿记。键是解析后的绝对路径（一个工作区一份，不是全局一份）。
_BOOKS: dict[str, "TimerBook"] = {}


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
    step = getattr(current(), "advance", None)
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


#: 进程内的工作区解析缓存：`Path(workspace).resolve()` -> 绝对路径。
#:
#: 为什么要缓存（2026-10-27 的实测）：Windows 上 `resolve()` 要调
#: `nt._getfinalpathname` 再 `stat`，一次 ~350 微秒；而 `target_state` 每问一次"被等的
#: 东西收口了没有"都要把工作区解析一遍。真机上 26 个不同的等待对象 = 26 次解析
#: = 9 毫秒，比它要做的判定本身贵两个数量级（`temp/_clock_bench.py` 的 before 读数：
#: N=53 时 fire_due 一拍的 13.6ms 里 9ms 是这一处）。解析结果是纯函数（同一个字符串
#: 永远解析成同一个绝对路径），所以缓存它不改变任何读数。
_RESOLVED_ROOTS: dict[str, str] = {}

_RESOLVED_ROOTS_LOCK = threading.Lock()

#: 解析缓存的上界。它不是性能参数，是"不泄漏"的上界：一个进程里工作区数远小于它。
RESOLVED_ROOTS_MAX: int = 4096


def _resolve_root(workspace: str | Path) -> str:
    """把工作区解析成绝对路径（进程内缓存一次）。读不成 => 原样返回（不抛）。"""
    raw = str(workspace)
    got = _RESOLVED_ROOTS.get(raw)
    if got is not None:
        return got
    try:
        got = str(Path(raw).resolve())
    except OSError:
        return raw
    with _RESOLVED_ROOTS_LOCK:
        if len(_RESOLVED_ROOTS) >= RESOLVED_ROOTS_MAX:
            _RESOLVED_ROOTS.clear()
        _RESOLVED_ROOTS[raw] = got
    return got


#: 本进程问了几次"被等对象收口了没有"（`target_state` 的进入次数）。
#:
#: 它是成本读数 `cost_reading()["target_probe_count"]` 的真身：改前一次 `fire_due`
#: 要为每个不同的等待对象各问一次，于是这一格等于"不同等待对象数"；改后在没有事件的
#: 安静拍上它必须等于 0（早退之后一次都不问）。计数是进程级的累加；`fire_due` 用
#: 前后差值把它折成"这一拍问了几次"。
_PROBE_CALLS: list[int] = [0]


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


def _atomic_json(path: Path, doc: Mapping[str, Any]) -> None:
    """原子写一份 JSON（同目录 tmp + os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(dict(doc), ensure_ascii=False, indent=2, default=json_default)
    tmp.write_text(text + "\n", encoding="utf-8", newline="")
    os.replace(tmp, path)


#: 进程内"起了程序却没能在时钟上登记"的次数与理由。
#:
#: 为什么要有这一格：程序计时器的登记要有工作区（账落在 `<工作区>/out/clock`）。
#: 没有工作区的调用点（例如模块导入期的工具链探测）结构上登记不了 —— 那就如实
#: 记一条"没登记"，读数里看得见；绝不允许"程序在跑、账上没有、也没人知道"。
_PROGRAM_UNBOOKED: list[dict[str, Any]] = []


def reset_programs() -> None:
    """清空进程内"没登记成的程序"那一格（判据之间的隔离点）。"""
    with _EVENT_LOCK:
        _PROGRAM_UNBOOKED.clear()


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
#: `agent_loop.py::AgentLoop.run` 拼提示词那一步起的。这不是少一格读数：`is_my_program`（`clock.py`
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


def is_lifeline(timer: Any) -> bool:
    """这条计时器是不是兜底计时器。唯一判据，别处不许各写一份。"""
    return str(getattr(timer, "kind", "") or "") == LIFELINE_KIND


def lifeline_key(task_id: str) -> str:
    """兜底计时器的等待键：只认"与我有关"的事件（业主 2026-10-29 第 1 条）。

    为什么不写成"全体通配"：通配会让一条广播把在场所有静默代理一起叫醒
    （成本 = 事件 x 静默者数），也会破坏"扇出不抢占"那条既有保证。
    """
    return f"task:{str(task_id or '').strip()}"
