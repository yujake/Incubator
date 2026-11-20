# -*- coding: utf-8 -*-
"""计时器与簿记的环核：`Timer` / `TimerBook` / `book()` / `target_state()`。

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第六刀。
四者是一个运行期成环的整体，必须同处一个模块：`Timer.due_reason` 在没给读数时问
`target_state`；`target_state` 问 `book`；`book` 造 `TimerBook`；`TimerBook` 存 `Timer`。
拆成两个模块，任一方向 import 都是环。索引面（24 个方法）上一刀已抽成
`clockbookindex._BookIndexMixin`，于是这一份落进 800 行内。

可变量归谁：本模块没有模块级可变量；`_BOOKS` 在 `clockrun.py`，`book()` 只经
`_resolve_root` + `_BOOKS` 读它（写点仍只有 `clockrun.reset_books` / `reset` 两处）。
依赖方向单向：`clockbase` / `clockrun` / `clockbookindex` / `clockprobe` → 本模块。
逐名 AST dump 全等（纯搬移），`clock.py` 原样再导出，调用点一个字没改。
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import json
from .clockbookindex import MAX_TERMINAL_KEPT
from .clockbookindex import Periodic
from .clockbookindex import _BookIndexMixin
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockParamError,
    ClockStateError,
    DUE_TRIGGERS,
    PROGRAM_OUTCOMES,
    PURPOSE_SOURCES,
    SCHEMA,
    STATE_REL,
    TARGET_STATES,
    TIMER_KINDS,
    TIMER_STATES,
    WAIT_FOR_KINDS,
    WOKE_REASONS,
    _iso,
    _parse_iso,
    parse_wait_for,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _event_hits,
    _unregister_parked,
)
from .clockprobe import (  # noqa: F401 — 这些名字由 clockprobe 定义
    _judge_target,
    _probe_read,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _BOOKS,
    _PROBE_CALLS,
    _atomic_json,
    _resolve_root,
    current,
    is_lifeline,
    now,
    waiting_on_text,
)

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
    _PROBE_CALLS[0] += 1
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
        token = str(getattr(current(), "token", "") or "")
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
                # 兜底计时器不问目标（业主 2026-10-29 第 2 条）：
                # 它等的键就是它自己的台账号，而"我那一行已经 done"正是"收工后仍续"的常态；
                # 一旦去问，`target_state` 必然判 `closed`，30 秒对账就把保活表打掉、
                # 零事件也醒，而且一声不吭。
                if not is_lifeline(self):
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
        token = str(getattr(current(), "token", "") or "")
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


class TimerBook(_BookIndexMixin):
    """一个工作区的计时器簿记，落盘成 `<工作区>/out/clock/state.json`。

    一份簿记装两样东西：一次性的计时器/闹钟（`timers`）与周期性巡查（`periodics`）。
    两者共用同一个发号器（编号前缀不同：`tm` / `pd`），于是"这一条是几号"在同一个
    工作区里不会撞号，读的人也能从编号一眼看出它是哪一类。
    """

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(_resolve_root(workspace))
        self._timers: dict[str, Timer] = {}
        self._periodics: dict[str, Periodic] = {}
        self._next_seq = 1
        self._loaded = False
        #: 读盘失败的理由。非空 = 这一份簿记没查成，不许读成"没有计时器"。
        self.load_error = ""
        #: 已经被压掉的终态条目总数（读数：不许静默丢历史，见 MAX_TERMINAL_KEPT）。
        self._terminal_dropped: int = 0
        # ---- 内存派生索引（盘上的格式一个字节都不改，`load` 时重建）----
        #
        #: `target_key -> 等它的计时器编号集合`（`_target_key` 的键空间）。
        #: 它替掉的是"按 `wait_for` 过滤全表"那一次 O(全表) 扫（改前的 `_probe_targets`
        #: 与 `_wake_waiters` 都各自扫过一遍）。
        self._waiters: dict[str, set[str]] = {}
        #: `(到点时刻的墙钟纪元, 台账序号, 计时器编号)` 的最小堆。到点时刻取"钟点"与
        #: "等谁的上限"两者较早的那一个（见 `_heap_due`）。纯等待（既没有钟点也没有上限）
        #: 不进堆 —— 它只由事件消账与补偿对账判。
        self._heap: list[tuple[float, int, str]] = []
        #: 编号 -> 它在台账里的序号。序号的赋值顺序就是 `state.json` 的行序
        #: （`(due_at, timer_id)`），于是堆的次序与今天线性扫的次序逐条相同。
        self._seq_of: dict[str, int] = {}
        self._order_seq = 0
        #: 还在堆里的编号（惰性删除：取消/到点之后堆里那一条留着，弹出时按 state 判掉）。
        self._in_heap: set[str] = set()
        #: 还 pending 的编号（`pending_count` 因此是 O(1)，不必数全表）。
        self._pending: set[str] = set()
        self._index_ready = False
        #: 最近一次对账的墙钟纪元与当时的单调计数（早退的判据要它们）。
        self._last_reconcile_at: float | None = None
        self._last_scan_mono: float | None = None
        self._reconcile_count = 0

    @property
    def state_path(self) -> Path:
        return Path(self.workspace) / STATE_REL

    # ---------------------------------------------------------- 派生索引
    #
    # 这一节的四个入口（`add` / `cancel` / `到点` / `load`）是索引唯一的同步点。
    # 任何一处漏掉都会让"堆 == 线性扫"与"索引 == 全表扫"这两条差分判据当场红。

























    def load(self) -> "TimerBook":
        if self._loaded:
            return self
        self._loaded = True
        path = self.state_path
        if not path.is_file():
            self._rebuild_index()
            return self
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
            self.load_error = f"计时器状态读不成：{type(exc).__name__}: {exc}"
            self._rebuild_index()
            return self
        if not isinstance(doc, dict):
            self.load_error = "计时器状态不是对象"
            self._rebuild_index()
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
        self._terminal_dropped = int(doc.get("dropped_terminal") or 0)
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
        # 派生索引的第四个同步点（也是唯一的重建点）：盘上的格式一个字节都不改，
        # 堆与反查索引全部从这一份全列表里现算出来。
        self._rebuild_index()
        return self

    def terminal_dropped(self) -> int:
        """已经被压掉的终态条目总数（读数：清了就要说得出来）。"""
        return int(self._terminal_dropped)

    def _prune_terminal(self) -> int:
        """把终态计时器压到 `MAX_TERMINAL_KEPT` 条以内，返回这一趟丢了几条。

        只动终态（`fired` / `cancelled`）：pending 一条都不许碰 —— 清掉一条 pending
        等于让那个"还在等"的人永远醒不了，而这件事没有任何地方会报错。
        丢的顺序是最老的先丢（按 `fired_at`，没有就按 `created_at`），于是留下的总是最近那批。
        """
        terminal = [t for t in self._timers.values()
                    if str(getattr(t, "state", "")) in ("fired", "cancelled")]
        over = len(terminal) - int(MAX_TERMINAL_KEPT)
        if over <= 0:
            return 0
        terminal.sort(key=lambda t: (str(getattr(t, "fired_at", "") or ""),
                                     str(getattr(t, "created_at", "") or ""),
                                     str(getattr(t, "timer_id", ""))))
        for timer in terminal[:over]:
            self._timers.pop(timer.timer_id, None)
        self._terminal_dropped += int(over)
        # 索引与堆都是派生量：删了行就重算一次（终态本不在堆里，这一步只是保一致）
        self._rebuild_index()
        return int(over)

    def save(self) -> None:
        if self.load_error:
            # 读坏的那一份不许被"保存一次空表"覆盖掉（那会把证据抹掉）。
            raise ClockStateError(self.load_error)
        reading = now()
        # 终态条目先压到上限内再落盘（D-05：state.json 不许随运行时长线性增长）。
        # 压在 save 里而不是每次到点后压：save 本来就要遍历全表建 doc，
        # 在这里做的代价是 O(终态数)，而终态数已被上面的上限钉住。
        self._prune_terminal()
        doc = {
            "schema": SCHEMA,
            "saved_at": _iso(reading.wall) if reading.wall is not None else "",
            "clock_token": str(getattr(current(), "token", "") or ""),
            "next_seq": self._next_seq,
            # 终态条目的上限与它清掉了多少（读数：清了就要说得出来）
            "dropped_terminal": self._terminal_dropped,
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
        # 索引的第一个同步点（另三处：`cancel` / 到点动作成功后 / `load`）。
        self.sync_index(timer)
        self.save()

    def get(self, timer_id: str) -> Timer | None:
        self.require_loaded()
        return self._timers.get(str(timer_id or ""))

    def all(self) -> list[Timer]:
        self.require_loaded()
        return sorted(self._timers.values(), key=lambda t: (t.due_at, t.timer_id))

    def pending(self) -> list[Timer]:
        """还 pending 的那些（按台账序）。到点判定的全扫路径读它；早退路径不读。"""
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
        # 索引的第二个同步点：取消之后它既不在反查索引里、也不该再从堆顶冒出来。
        self.sync_index(timer)
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
    root = _resolve_root(workspace)
    if root not in _BOOKS:
        _BOOKS[root] = TimerBook(root)
    return _BOOKS[root].require_loaded()
