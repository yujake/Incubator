# -*- coding: utf-8 -*-
"""程序计时器：起程序、挂 pid、收口、读程序账、`program_span` 上下文。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第九刀。
"起一个程序并等它"在时钟这一侧是一条完整的链：`start_program` 建表 → `attach_program_pid`
把 pid 挂上 → 跑完时 `finish_program` 收口（退出码 / outcome / 到点消息）→ `programs`
是读侧。`ProgramSpan` / `program_span` 是这条链的调用形状：起进程失败不许带走程序，
但必须留下一条 `_note_unbooked` 读数（"起了却没进账"不许静默）。

## 装了什么

`argv_digest` / `program_message` / `program_purpose`（命令摘要与目的自动填）/
`_calling_identity`（台账号与角色的取法）/ `start_program` / `attach_program_pid` /
`finish_program` / `program_owner` / `is_my_program` / `not_mine_refusal` /
`ProgramSpan` / `program_span` / `_note_unbooked` / `_workspace_of` / `programs` /
`programs_running`。

## 依赖与可变量

`Timer` / `TimerBook` / `book` 在 `clocktimer.py`，本模块在它之上；停程序那一层
（`clockstop.py`）反过来 import 本模块的收口口（`finish_program` / `is_my_program` /
`not_mine_refusal`），依赖方向单向。可变量：`_PROGRAM_UNBOOKED` 在 `clockrun.py`
（唯一写点跟着它），本模块不写任何模块级可变量。纯搬移，逐名 AST dump 全等，
`clock.py` 原样再导出。
"""

from __future__ import annotations

from pathlib import Path
import contextlib
import time
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ARGV_EXCERPT,
    ClockParamError,
    PROGRAM_OUTCOMES,
    PURPOSE_FROM_TARGET,
    _EVENT_LOCK,
    _iso,
    human_sec,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _close_waiters_for_event,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _PROGRAM_UNBOOKED,
    current,
    current_run_identity,
    current_workspace,
    now,
    purpose_of,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    Timer,
    book,
)

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
        clock_token=str(getattr(current(), "token", "") or ""),
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
    # 程序收口就是"等它的那几条"的事件产生点（业主 2026-10-27 第二条）：
    # 按 `program:<号>` 查一次反查索引，把它们就地判掉，不必等下一拍扫表。
    # 三态/推迟/异常都在 `_close_waiters_for_event` 里各自记读数，这里不另写一个 if。
    _close_waiters_for_event("finish_program", [f"program:{timer.timer_id}"], reading=reading)
    return timer, "fired"


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


def programs_running(workspace: str | Path) -> list[Timer]:
    """还在跑的程序计时器（账上 pending 的那几条）。读不成 => 空表 + 抛由调用方处置。"""
    return [t for t in book(workspace).all() if t.is_program and t.state == "pending"]
