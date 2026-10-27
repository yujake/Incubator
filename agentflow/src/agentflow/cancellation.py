"""取消语义（FC-20 的四条纪律，`DESIGN-CONDUCTOR.md` §4）。

## 为什么取消要单独一个模块

因为它是跨层的东西：主控要能取消、调度器要把取消传进每个在飞任务、
每个 handler 要在关键点 `raise_if_cancelled()`。把它们各写一份的后果是
"取消只对某一层生效" —— 而那种失效不会报错，只会表现为"点了停止之后，
有三个任务还在跑"。

## 四条纪律（照 `04-…md` §B5 的 DSH 设计）

1. 一个共享 signal 覆盖所有在飞与待启动的任务（不是逐个取消 —— 逐个会漏）。
   实现形态：`CancelToken` 是一个对象，`Conductor` 把它同时交给
   `scheduler.run_waves` 与每一次 `summon`。于是"漏掉一个在飞任务"这件事
   在结构上不可能发生：那个任务读的是同一个 token。
2. 终态先到先得：`ended_at` 一旦写下就不再改写。
   本模块的对应物是 `cancel()` 的幂等 + first-wins：第二次取消不改变
   第一次的 reason。为什么连 reason 都不能改：reason 会被写进台账的 `detail`，
   而"为什么停的"必须只有一个答案 —— 两个答案等于没有答案。
3. 每个 start 事件有且仅有一个 end 事件：即使是被强杀或抛异常的任务，
   也必须合成一个 `cancelled` 的 end（否则台账里会有永远"在跑"的僵尸）。
   这一条由 `Conductor.dispose()` 与 `finish()` 负责实现，本模块提供
   "到底有没有被取消"的唯一判据（`token.cancelled`）。
4. 取消后不自动重试，并把结果记成 unknown outcome：
   一个被中途砍掉的实验可能已经写了半张表，声称它"失败"是过度声称。
   实现形态：`Reason` 里带 `outcome_known=False`，而 `Conductor` 把它写进
   `detail`（"因 dispose 而终止，结果未知"）。

## 三态纪律在这里的落点

`cancelled` 是 `bool`（不是 `None`）—— "取消了没有"这个问题永远有答案
（有 / 没有），不存在"没查"。但为什么取消（`reason`）在没取消时是 `None`：
"没有理由"与"理由是空字符串"必须能区分。
"""

from __future__ import annotations

import contextvars
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class CancelRequested(Exception):
    """协作式取消信号。

    它不是错误。`Conductor` 抓到它之后写的是
    `status="cancelled"`（不是 `failed`）—— 见 `schema.TASK_STATUSES` 的说明：
    `done` 与 `failed`/`cancelled` 必须分开，否则无法回答"这条结论是在一次
    成功完成的召唤里产出的、还是在一次崩溃里被顺手写下的"。

    继承 `Exception` 而不是 `BaseException`：它需要能被普通的
    `except Exception` 边界捕获（否则会穿过 `finish()` 的兜底逻辑，
    让任务永远停在 running —— 一个僵尸）。
    """

    def __init__(self, reason: str = "cancelled") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CancelReason:
    """一次取消的完整理由。没有任何字段可以是"猜的"。"""

    #: 受控的原因词。自由文本的原因无法统计，也无法被 verify 检查。
    code: str
    #: 人可读的补充说明。
    detail: str = ""
    #: 结果是否已知。被中途砍掉的任务它必须是 False ——
    #: 一个跑了一半的实验可能已经写了半张表，声称它"失败"是过度声称。
    outcome_known: bool = False
    #: 谁发起的取消。取值见 `CANCEL_BY_VALUES`（不是硬枚举，理由见那里）。
    by: str = "unknown"

    def __post_init__(self) -> None:
        """`code` 必须是受控词表里的一员（`G-10`）。

        ## 为什么这一条必须在这里，而不是只在 `Conductor._signal_stop` 里

        `_signal_stop` 早就有 `if code not in CANCEL_CODES: raise ValueError(...)`
        —— 但那只覆盖编排层那一个入口。`CancelReason` 是公开的值对象，
        任何地方都能直接构造它，而在此之前构造器不做任何校验：
        实测（`temp/batchG-g10.txt`）`CancelReason("乱写")` 通过、
        `CancelToken().cancel("reason-7")` 也通过并把编外 code 原样记下。

        词表自己的 docstring 写着"自由文本的原因无法统计，也无法被 verify 检查"
        —— 那句话只有在对所有构造路径成立时才是真的。核对方式是"两处实现
        互相印证"：同一族的 `policy.Refusal` 在 `__post_init__` 里就拒词表外的值，
        而 `CancelReason` 不拒 —— 同一件纪律两种强度，正是本项目点名的
        "同一件事两个落位"的形态。

        ## 只校 `code`，刻意不校 `by`

        `by` 回答的是"谁喊的停"，它是一个审计标签：`Conductor.cancel(..., by=...)`
        是公开参数，调用方用自定义标签标自己是谁（`tests/test_cancellation.py`
        里有 `by="caller-1"` 这类用法，`CANCEL_BY_VALUES` 的注释逐字写明
        "不是『别人不许传别的』的闸门"）。把 `by` 也锁成枚举会让审计信息变少
        —— 抓一条缺陷的时候不许顺手砍掉另一条已登记的约定。
        """
        if self.code not in CANCEL_CODES:
            raise ValueError(
                f"CancelReason.code={self.code!r} 不在受控词表 {CANCEL_CODES} 里。"
                "取消的理由必须可枚举：自由文本的原因无法被统计，也无法被 verify 检查"
                "（`G-10`）。若这是一个新的、真实的停止来源，请先把它登记进 "
                "`CANCEL_CODES` 并写出它的产出点；不要用自由文本绕过词表。"
            )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "detail": self.detail,
            "outcome_known": self.outcome_known,
            "by": self.by,
        }


#: 受控的取消原因。与 `schema.REFUSAL_REASONS` 分开：拒绝是策略的决定，
#: 取消是外部的决定（人按了停止、时间到了、钱花光了）。
CANCEL_CODES: tuple[str, ...] = (
    "user",              # 人/调用方显式取消
    "deadline",          # 墙钟截止
    "budget",            # 钱花光了（`budget` 注册表 / M 主动喊停）—— 不是 token
    "dispose",           # Conductor 被销毁
    "cancelled",         # 未分类（不要用它：它等于没写原因）
)

#: `CancelReason.by` 的受控词表：本模块与 `Conductor` 自己会产出的那些取值。
#:
#: 与 `CANCEL_CODES` 是两个字段、两件事，不许互换：
#: `code` 回答"为什么停"（封闭词表，`Conductor._signal_stop` 会拒绝词表外的 code）；
#: `by` 回答"谁喊的停"，它是一个审计标签。
#:
#: 为什么 `by` 刻意不做成硬枚举（与 `code` 不同）：
#: `Conductor.cancel(..., by=...)` 是公开参数，调用方用它标自己是谁
#: （`tests/test_cancellation.py` 里就有 `by="caller-1"` / `by="t1"` 这类
#: 调用方自定义标签）。把它锁成枚举会拒掉合法的调用方，并且会让"谁喊的停"
#: 这条审计信息变少，而不是变准。所以这里是"我们自己产出哪些值"的登记，
#: 不是"别人不许传别的"的闸门。
#:
#: 每一条的产出点（改这里时同改，`tests/test_cancellation.py` 有对齐用例）：
#:   unknown            —— `CancelReason.by` 的默认值（没记谁喊的）
#:   user               —— `Conductor.cancel` 的默认 `by="user"`
#:   deadline           —— `CancelToken.reason` 的惰性路径 + `Conductor` 的 `_signal_stop("deadline", ...)`
#:   budget             —— `agent_loop` 的美元预算停止点（`by="budget"`； 2026-10-15 裁定
#:                         A1/A2/A3 之后不再由 `CancelToken` 的 token 预算产出）
#:   conductor.dispose  —— `Conductor.dispose` 合成终态时
CANCEL_BY_VALUES: tuple[str, ...] = (
    "unknown",
    "user",
    "deadline",
    "budget",
    "conductor.dispose",
)


class CancelToken:
    """一个可以被多方共享的取消开关。

    ## 线程安全

    `Conductor` 会在主线程 `cancel()`，而 `scheduler` 的工作线程在读
    `cancelled`。所有读写都在同一把 `threading.Lock` 里 ——
    不加锁的后果不是"偶尔读到旧值"那么轻：CPython 里 `bool` 赋值是原子的，
    但"先设 flag 再设 reason"是两步，中间被读到就会得到一个
    "已取消但没有理由"的状态，而那个状态会被写进台账。

    ## 可选上限

    - `deadline`（单调时钟的绝对时刻）：到点后 `cancelled` 自己变 True，
      不需要任何人来按按钮。为什么用 `time.monotonic` 而不是墙钟：
      系统时间被 NTP 往回拨时，墙钟会让"到点"变成"还没到"（或反之），
      而这种抖动在测试里表现为偶发失败。

    `token_budget` 这一格已删（2026-10-15 业主裁定 A1/A2/A3：
    「我们不卡 token，只卡总花销的钱」）。它此前是一条真实的强杀路径
    （`_tokens_used >= _token_budget` ⇒ `cancelled` 变 True ⇒ 在跑的 handler
    在下一个 `raise_if_cancelled` 点被掀掉）。为什么必须删而不是留着不用：
    它把"想得多"变成了一种过错 —— 而 T5 实测（`draft/121`）里
   卡住智能体的正是它。`tokens_used` 仍然记（`consume_tokens`），
    它只是读数，不再有任何一处在它上面说"停"。
    钱的闸门在 `tokenmeter.TokenMeter.guard()`（那才是现在唯一会拒绝的地方）。
    """

    __slots__ = ("_lock", "_reason", "_deadline", "_tokens_used",
                 "_cancelled_flag", "_spawned")

    def __init__(self, *, deadline: float | None = None) -> None:
        self._lock = threading.Lock()
        self._reason: CancelReason | None = None
        self._deadline = deadline
        self._tokens_used = 0
        self._cancelled_flag = False
        #: 本 token 名下正在跑的子进程（`G-1`）。`cancel()` 会主动杀掉它们 ——
        #: 一个跑 600 秒的 Lean 检查不会自己发现"有人按了停止"。
        self._spawned: list[Any] = []

    # ------------------------------------------------- `G-1` 子进程出生表
    def _is_cancelled_locked(self) -> bool:
        """持锁状态下的三态取消判定（与 `cancelled` 同一判据，不重复实现）。

        为什么要单独一个"持锁版"：`_register_spawned` 已经在锁里，
        而 `cancelled` 自己会再抢一次同一把非重入锁 ⇒ 直接调它会死锁
        （实测：`deadline` 到点时 `run_cancellable` 永久卡住）。
        所以这里只能内联同一套条件，并且必须与 `cancelled` 同步改。
        """
        if self._cancelled_flag:
            return True
        if self._deadline is not None and time.monotonic() >= self._deadline:
            return True
        return False

    def _register_spawned(self, proc: Any) -> None:
        with self._lock:
            # `R5-F2`（重审实测）：守卫旧版只判 `_cancelled_flag` —— 那个标志
            # 只由显式 `cancel()` 置位，于是 `deadline` 到点这条惰性取消路径下，
            # 新起的子进程照样被登记进表、没有人会去杀它（端到端实测：
            # `deadline=0.20s` 的 token 起 `sleep(30)` ⇒ 阻塞 30.06 秒才返回，
            # 子进程活到最后）。判据必须与 `cancelled` 逐条一致：两条路都算"已取消"。
            if self._is_cancelled_locked():
                # 取消与起进程的竞态：已经取消了就别留下一个没人管的进程。
                _kill(proc)
                return
            self._spawned.append(proc)

    def _unregister_spawned(self, proc: Any) -> None:
        with self._lock:
            try:
                self._spawned.remove(proc)
            except ValueError:
                # 已经被 `cancel()` 从表里摘掉了（它清空整张表）—— 这正是
                # "取消与收尾同时发生"的形态，摘不到是期望的结果，不是错误。
                # 唯一不能做的是因此抛出去：那会让一次正常的收尾看起来像失败。
                pass

    def _kill_spawned(self) -> int:
        """杀掉本 token 名下所有在跑的子进程，返回杀掉的个数。"""
        with self._lock:
            procs = list(self._spawned)
            self._spawned.clear()
        for p in procs:
            _kill(p)
        return len(procs)

    @property
    def spawned_count(self) -> int:
        """当前在跑的子进程数（`0` = 没有）。诊断/报告用，不是判据。"""
        with self._lock:
            return len(self._spawned)

    # ---------------------------------------------------------------- 构造
    @classmethod
    def with_deadline(cls, seconds: float, **kw) -> "CancelToken":
        """在 `seconds` 秒后自动取消（单调时钟）。"""
        if seconds is None or seconds <= 0:
            raise ValueError(f"with_deadline 的秒数必须为正，收到 {seconds!r}")
        return cls(deadline=time.monotonic() + float(seconds), **kw)

    # ---------------------------------------------------------------- 状态
    @property
    def cancelled(self) -> bool:
        """是否已取消。到点的 deadline 也算取消（不需要谁来按按钮）。"""
        with self._lock:
            if self._cancelled_flag:
                return True
            if self._deadline is not None and time.monotonic() >= self._deadline:
                return True
            return False

    @property
    def reason(self) -> CancelReason | None:
        """取消的理由；没取消时是 `None`（不是空串，也不是"默认理由"）。

        deadline 到点时的理由在这里才生成（惰性），因为可能没有线程
        去"通知"它 —— 这不是缺陷：`deadline` 的性质就是"没人按按钮它也会到"。
        """
        with self._lock:
            if self._reason is not None:
                return self._reason
            if self._deadline is not None and time.monotonic() >= self._deadline:
                return CancelReason(
                    "deadline",
                    f"墙钟截止已到（deadline={self._deadline:.3f}，单调时钟）",
                    outcome_known=False,
                    by="deadline",
                )
            return None

    @property
    def tokens_used(self) -> int:
        """这一趟花了多少 token —— 读数（2026-10-15 裁定 A1 之后不再是判据）。"""
        with self._lock:
            return self._tokens_used

    # ---------------------------------------------------------------- 动作
    def cancel(self, reason: str = "user", *, detail: str = "", by: str = "unknown") -> CancelReason:
        """取消。幂等且 first-wins：第二次调用不改变第一次的理由。

        为什么 reason 也不能改：它会被写进台账的 `detail`，而
        "为什么停的"必须只有一个答案 —— 两个答案等于没有答案。
        （`Task.validate` 的"终态先到先得"防的是同一件事的另一面：
        先写下的 `ended_at` 决定了这一行说什么，后来的取消只能什么都不做。）

        返回第一次定下的那个理由（而不是 None）：调用方拿它去写台账，
        于是"是谁先喊的停"是可审计的。

        ## `G-1`：取消同时杀掉本 token 名下的子进程

        在锁内先收集、在锁外杀（`kill` 是系统调用，持锁做它会拖住所有读
        `cancelled` 的线程）。取消位只在第一次调用时置，但子进程表每次都清：
        第二次取消时若又起了新进程，那一个也该被杀（"先到先得"管的是 reason，
        不是"以后新起的进程就没人管了"）。

        ## `G-10`：`reason` 由 `CancelReason` 校一次受控词表

        这里不另写一份 `if reason not in CANCEL_CODES` —— 判断只在
        `CancelReason.__post_init__` 一处（同一件事两个落位是本项目反复踩的形态）。
        于是词表外的 code 会在这里以 `ValueError` 结束，而不会留下一个
        半取消的状态：`CancelReason` 构造失败发生在 `self._reason` 赋值之前，
        `_cancelled_flag` 也没被置位。

        为什么这条校验是必要的而不是多余的：`_signal_stop` 那一层的守卫只覆盖
        编排层入口，而 `cancel()` 本身是公开 API —— 实测它此前接受
        `"reason-7"` 这类编外值并原样写进台账的 `detail`（`temp/batchG-g10.txt`）。
        """
        with self._lock:
            if self._reason is None:
                # 先写理由，再置 flag。反过来会让"由 deadline/预算路径先看到
                # flag 为 True"的线程读到一个 `_reason is None` 的中间态，
                # 于是 `detail_of(None)` 把"预算耗尽"写成"未给出理由" ——
                # 一条内容错误但看起来正常的台账。锁保护的是读的原子性，
                # 而写入顺序保护的是状态的中间态不存在。
                self._reason = CancelReason(
                    code=reason, detail=detail, outcome_known=False, by=by
                )
                self._cancelled_flag = True
            reason_obj = self._reason
        # 杀子进程这一步走 `_kill_spawned`（"持锁取表 → 清表 → 锁外逐个杀"的唯一实现）。
        # 原来这里是同一段逻辑的第二份内联副本，而 `_kill_spawned` 的唯一调用者是一个
        # 全仓 0 调用的公开方法 `cancel_children()`（它的 docstring 还写着"`cancel()`
        # 已经会自动调它"——假话）。2026-10-27：删掉那个公开方法，内联副本收回来。
        # 注意顺序：`_kill_spawned` 自己会抢同一把非重入锁，所以必须等上面那个 `with` 退出。
        self._kill_spawned()
        return reason_obj

    def consume_tokens(self, n: int) -> int:
        """记一笔 token 消耗，返回累计值（读数，不是判据）。

        2026-10-15 业主裁定 A1/A2/A3 之后这个方法的语义变了：它此前返回
        "这次消耗之后是否仍然没超预算"（一个 bool），并在超预算时把
        `cancelled` 置起来 —— 那是一条强杀路径。现在它只记账：
        "这一趟花了多少"必须看得见，但花多少都不会让这一趟停。

        为什么仍然返回一个数而不是 `None`：调用方就地能拿到累计值
        （写成 `None` 的话，想看这个数的人得再抢一次锁读属性），
        而且"返回一个数"本身就把"这里不再说停"写在了签名上。
        """
        with self._lock:
            self._tokens_used += max(0, int(n))
            return self._tokens_used

    def raise_if_cancelled(self) -> None:
        """在 handler 的关键点调用它 —— 协作式取消的全部实现。

        为什么不做抢占式（`threading.Thread.kill` 之类）：本项目不自己 spawn
        进程/线程去跑角色（那会让离线、确定性、可复现全部失守，设计 §1.3）。
        更实际的理由是：在事务中间强杀会让"已写了半张表"成为常态，
        而半张表比"慢一点"危险得多。所以取消是请求，执行单元在
        它能安全停下的点上响应。

         子进程是这条纪律的例外（`G-1`）：一个跑 600 秒的 Lean 检查
        "能在安全停下的点上响应"这件事不成立 —— 它根本没有那样的点。
        所以由 `cancel()` 主动杀（`_kill_spawned`），而不是等它自己发现。
        杀子进程不破坏上面那条理由：子进程不写我们的表，它写的是自己的工作目录。
        """
        if self.cancelled:
            r = self.reason
            raise CancelRequested(detail_of(r) if r else "cancelled")

    def to_dict(self) -> dict:
        """台账/日志形态。`reason` 为 None 时原样是 None（不折叠成默认理由）。

        `token_budget` 那一格已删（2026-10-15 裁定 A1）；`tokens_used` 留着当读数。
        """
        r = self.reason
        return {
            "cancelled": self.cancelled,
            "reason": r.to_dict() if r is not None else None,
            "tokens_used": self.tokens_used,
        }


def detail_of(reason: CancelReason | None) -> str:
    """把理由渲染成人可读的一句话。None ⇒ 明确写"未给出理由"。

    这里不返回空串：空串在台账里与"这一列没填"长得一样，
    而"取消了但说不出为什么"是一件需要被看见的事。
    """
    if reason is None:
        return "取消（未给出理由）"
    return f"取消[{reason.code}] {reason.detail}".strip()


# ---------------------------------------------------------------- `G-1`：取消要到达 handler
#
# ## 缺陷（2026-09-26 全面体检 · 子代理 G 实测，`temp/auditG-probe1.txt`）
#
# `LocalBackend.call` 的签名收下了 `token: CancelToken`，但末行是 `return fn(**given)`
# —— token 收下就扔了。全仓 `raise_if_cancelled` 的调用点为 0，
# 用 AST 扫 CAPABILITIES 里全部 ActionSpec 的 handler，形参里带 token 的一个都没有。
# 行为实测：两个各睡 0.6s 的任务，0.15s 时取消 ⇒ 已经在跑的那个照样以
# `done/ok` 结束，只有还没进 summon 的那一个被取消。
#
# ## 修法（口径：把 signal 送到两个真正的执行面上）
#
# 1. handler：`LocalBackend.call` 在调用期间把 token 放进一个 `ContextVar`，
#    handler 通过 `current_token()` / `raise_if_cancelled()` 读它。
#    为什么用 ContextVar 而不是给实例挂属性：`resolve(role)` 是按角色缓存实例的，
#    两个并发调用会共享同一个对象 ⇒ 挂实例属性会让 A 的 token 被 B 覆盖（静默串味）。
#    ContextVar 按执行上下文隔离，正是这里要的语义。
# 2. 子进程：`run_cancellable()` 起进程并注册到 token 自己的出生表上；
#    `cancel()` 会立刻杀掉所有已注册的子进程（formalgw 的 Lean、以及将来任何
#    "调用方决定内容"的子进程）。为什么必须由 `cancel()` 主动杀而不是等 handler
#    下一次检查：一个正在跑 600 秒的 Lean 检查，协作式取消只能等到它跑完 ——
#    那不是"按了停止也停不下来"的修复。
#
# 三态纪律在这里的形态：`run_cancellable` 在取消时返回 `cancelled=True`
# （既不是 `timed_out`，也不是普通的非零退出码），而调用方必须把它读成
# "没查成" —— 它与"超时"的处置不同（超时是加时间，取消是有人喊停）。

#: 当前执行上下文里的取消 token；`LocalBackend.call` 在调用 handler 期间设置它。
_CURRENT_TOKEN: contextvars.ContextVar["CancelToken | None"] = contextvars.ContextVar(
    "agentflow_cancel_token", default=None
)

#: `run_cancellable` 等待子进程时每一段的长度（秒）。见那里的注释：
#: 一次等到超时会让"在长超时下被取消"这件事晚 `timeout_sec` 才被发现
#: （实测：`timeout_sec=10`、0.15 秒时取消 ⇒ 旧版要等到 kill 生效才返回，
#: 而分段等待让它在该段结束时就返回）。这个值越小，取消越灵敏、轮询越密。
_CANCEL_POLL_SEC: float = 0.05

#: 杀掉子进程之后，把管道抽干净最多再等多久（秒）。见 `_drain_after_kill`。
#:
#: 为什么要一个值而不是"等到 EOF"：被杀之后输出通常几十毫秒就抽完了，而这个上限
#: 只在"管道写端被孙子进程握着"那种病态形态下才真的花掉。2 秒足够抽干，又不至于
#: 让每一次超时的 Lean 检查白白多等（实测同一形态：不限 = 20.19s、5s = 5.69s、
#: 2s = 2.69s；见 `temp/rbe3_repro_wait.py`）。
_KILL_GRACE_SEC: float = 2.0


def current_token() -> "CancelToken | None":
    """当前 handler 执行上下文里的 token（不在 handler 里时是 `None`）。

    返回 `None` 是诚实的："没有取消信号"与"有信号且没取消"是两件事，
    把它折叠成一个默认 token 会让"这段代码从来没被接进取消面"永远看不见。
    """
    return _CURRENT_TOKEN.get()


def current_reason_text() -> str:
    """取消理由的人可读文本；没 token 或没取消时返回空串。"""
    tok = _CURRENT_TOKEN.get()
    if tok is None:
        return ""
    r = tok.reason
    return detail_of(r) if r is not None else ""


def raise_if_cancelled() -> None:
    """handler 关键点的协作式检查（模块级形态，供没有实例的地方调用）。

    与 `CancelToken.raise_if_cancelled` 逐字同一个判据，只是从当前上下文取 token；
    没有 token 时什么都不做（不抛）：那说明这段代码跑在取消面之外，
    而"投递一个假信号"比"没有信号"更糟。
    """
    tok = _CURRENT_TOKEN.get()
    if tok is not None:
        tok.raise_if_cancelled()


def run_cancellable(
    cmd: Sequence[str], *,
    cwd: str | None = None,
    timeout_sec: float,
    token: "CancelToken | None" = None,
    stdin_devnull: bool = True,
    workspace: str | None = None,
    purpose: str = "",
) -> dict:
    """起一个可被取消的子进程，返回与 `formalgw._default_run` 同形的 dict。

    返回值多两个键（`_normalize_run` 会忽略它们，但调用方要读）：
    `cancelled: bool` 与 `timed_out: bool`。取消时 `cancelled=True` 且
    `timed_out=False` —— 两者都落在"没查成"那一档，但处置不同：
    "超时"是给它更多时间，"取消"是有人喊了停、不该重试。

    实现：`Popen` + `communicate(timeout=...)`，并在 `finally` 里把进程从
    token 的出生表摘掉。取消不靠轮询：`CancelToken.cancel()` 会主动 kill
    已注册的进程（见 `_kill_spawned`），所以这个函数等到的是"进程被杀"，
    而不是"下一次轮询发现取消了"。

    ## 程序计时器（业主 2026-10-27 第一条裁定）

    「运行一个程序时会自动启动一个计时器，程序运行完成时计时器会返回」。所以起进程
    之前先 `clock.program_span(...)` 登记一条 `kind="program"` 的计时器，进程结束时
    它收口并带上结局（`exited` / `timed_out` / `killed`）、耗时与退出码。读数在
    `clock.programs(workspace)`：`program` / `argv_digest` / `pid` / `state` /
    `elapsed_sec` / `exit_code`。

    `workspace` 不给时用 `clock.current_workspace()`（循环/装配期挂上的那个）；
    两者都没有时程序照跑，但会留一条"没登记"的读数（`programs()["unbooked"]`）。
    """
    tok = token if token is not None else _CURRENT_TOKEN.get()
    if tok is not None:
        tok.raise_if_cancelled()  # 已经取消了就别起了
    from . import clock as CLK

    program = str(cmd[0]) if cmd else ""
    with CLK.program_span(program=program, argv=list(cmd),
                          workspace=(workspace or CLK.current_workspace() or None),
                          where="cancellation.run_cancellable",
                          purpose=(purpose or "等外部程序退出（可取消的子进程）")) as prog:
        kwargs: dict[str, Any] = {}
        if stdin_devnull:
            kwargs["stdin"] = subprocess.DEVNULL
        proc = subprocess.Popen(
            list(cmd), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **kwargs,
        )
        prog.attach_pid(int(getattr(proc, "pid", 0) or 0) or None)
        if tok is not None:
            tok._register_spawned(proc)
        try:
            # `R5-F2`：等待必须是分段的，且每一段之后都看一次"这次取消了吗"。
            # 旧版只有一次 `communicate(timeout=timeout_sec)`，它有两个后果：
            #   ① `deadline` 到点与预算耗尽这两条惰性取消路径下，新起的子进程
            #      没有人会 kill，于是这个函数一直等到子进程自己结束
            #      （实测 `deadline=0.20s` + `sleep(30)` ⇒ 阻塞 30.06 秒）；
            #   ② 显式取消时，返回时刻取决于 kill 何时让 `communicate` 解开 ——
            #      而它的超时上限是整个 `timeout_sec`。
            # 现在：每段最多等 `_CANCEL_POLL_SEC`，段后先看取消、再看是不是到点了。
            waited = 0.0
            out = err = ""
            timed_out = False
            while True:
                slice_sec = _CANCEL_POLL_SEC
                if timeout_sec is not None:
                    slice_sec = min(_CANCEL_POLL_SEC, max(0.001, timeout_sec - waited))
                t_call = time.monotonic()
                try:
                    out, err = proc.communicate(timeout=slice_sec)
                    _note_process_wait(time.monotonic() - t_call)
                    break
                except subprocess.TimeoutExpired:
                    _note_process_wait(time.monotonic() - t_call)
                    waited += slice_sec
                    if tok is not None and tok.cancelled:
                        _kill(proc)
                        out, err = _drain_after_kill(proc)
                        prog.finish(outcome="killed")
                        return {"exit_code": None, "stdout": out or "", "stderr": err or "",
                                "timed_out": False, "cancelled": True,
                                "program_timer": prog.reading()}
                    if timeout_sec is not None and waited >= timeout_sec:
                        timed_out = True
                        _kill(proc)
                        out, err = _drain_after_kill(proc)
                        break
            if timed_out:
                prog.finish(outcome="timed_out")
                return {"exit_code": None, "stdout": out or "", "stderr": err or "",
                        "timed_out": True, "cancelled": False,
                        "program_timer": prog.reading()}
            if tok is not None and tok.cancelled:
                # 取消是在 `communicate` 返回前发生的（kill 由 `cancel()` 发出）⇒
                # 退出码是 -15/-9 那一类，不是检查器对这份输入给出的结论。
                prog.finish(outcome="killed")
                return {"exit_code": None, "stdout": out or "", "stderr": err or "",
                        "timed_out": False, "cancelled": True,
                        "program_timer": prog.reading()}
            prog.finish(outcome="exited", exit_code=int(proc.returncode))
            return {"exit_code": int(proc.returncode), "stdout": out or "",
                    "stderr": err or "", "timed_out": False, "cancelled": False,
                    "program_timer": prog.reading()}
        finally:
            if tok is not None:
                tok._unregister_spawned(proc)


def _kill(proc: "subprocess.Popen") -> None:
    """尽力杀掉一个子进程；杀不掉不抛（真正的失败由调用方那一条报出来）。"""
    try:
        proc.kill()
    except Exception:  # noqa: BLE001 - 已经退出 / 句柄关了，都无所谓
        pass


def _drain_after_kill(proc: "subprocess.Popen", grace: float | None = None) -> tuple[str, str]:
    """杀完之后把管道抽干净 —— 这一等必须带上限（改前它没有），而且必须进等待账。

    为什么必须带上限：`communicate()` 等的是管道 EOF，不是"这个 pid 死了"。
    外部检查器自己会起子进程（Lean 那一族都会），而管道写端被孙子继承 ⇒
    杀掉父进程之后 EOF 仍然等不到，`communicate()` 就一直挂着。
    实测（`temp/rbe3_repro_wait.py`，2026-10-27）：`timeout_sec=0.5` 的调用
    要 20.19 秒才返回 —— 超时判据形同虚设，而调用方读到的仍是 `timed_out=True`，
    看不出"它其实没停下来"。

    加档之后：杀完最多再等 `grace` 秒，超过就按"抽不到"给空串，并把进程句柄收掉
    （结局仍由 `prog.finish(outcome=...)` 如实写下 —— 不冒充成功，也不改返回值
    的任何键，`formalgw._normalize_run` 的契约不动）。

    为什么这里的等待要记账（业主 2026-10-25 那条纪律：计时类工作一律进主时钟的账）：
    这两处等的都是"子进程 / 管道的 EOF"，不是钟点，所以它们不会被 `Deadline` 掐掉 ——
    "不在任何人的账上、又能挂住 20 秒"正是普查要抓的形态。它们各自记一条
    `kind="external_process"` 的等待（`where` 同一个落点，`waited_for` 分得清是哪一处）：
    量的是实测耗时，不是上限。`GOVERNED_PRIMITIVE_WAITS` 里有本函数的登记，
    于是普查把这两处算"已记账"而不是缺口。
    """
    limit = _KILL_GRACE_SEC if grace is None else float(grace)
    t_call = time.monotonic()
    try:
        out, err = proc.communicate(timeout=limit)
        _note_process_wait(time.monotonic() - t_call,
                           waited_for="_drain_after_kill:communicate(timeout=_KILL_GRACE_SEC)")
        return out or "", err or ""
    except subprocess.TimeoutExpired:
        _note_process_wait(time.monotonic() - t_call,
                           waited_for="_drain_after_kill:communicate(timeout=_KILL_GRACE_SEC)")
        # 管子还被别人握着（孙子进程）。这里刻意不关管道：关它反而更慢 ——
        # Windows 上 `close()` 要等读线程放掉缓冲锁，而读线程正卡在 `read()` 里
        # 等 EOF（实测：关它要 14.5 秒）。读线程是 daemon，随管道 EOF 自行结束。
        # 所以只把进程句柄收掉，输出按"抽不到"给空串。
        t_reap = time.monotonic()
        try:
            proc.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, OSError):  # noqa: BLE001 - 收尸失败无所谓：
            # 上面已经把进程杀了，这里等不到只是句柄晚一点被回收；不能因此把一次
            # 已经成立的"取消/超时"改写成异常（那会让调用方读成"没查成"之外的第三态）。
            pass
        _note_process_wait(time.monotonic() - t_reap,
                           waited_for="_drain_after_kill:wait(timeout=1.0)")
        return "", ""


def _note_process_wait(elapsed_sec: float, *,
                       waited_for: str = "communicate(timeout=slice_sec)") -> None:
    """把"这一次等子进程等了多久"记进主时钟那本账（旁路：记账炸了不许带坏等待）。

    阻塞方式刻意不动：`communicate(timeout=…)` 是"进程一退就返回"，换成 sleep 会把
    取消语义（段间看 token）一起毁掉。记的是实测耗时，不是 `slice_sec` 那个上限 ——
    两者相等只是巧合，进程早退时前者远小于后者。

    `waited_for` 说清"是哪一处"在等（轮询那一段 / 杀完之后抽管道那两段）：
    同一本账上三处都用 `where="cancellation.run_cancellable"`（同一个落点），
    靠这一格分开 —— 少了它，"这一笔 2.7 秒是杀之前还是杀之后"就读不出来。
    """
    try:
        from . import clock as CLK

        CLK.note_process_wait(elapsed_sec, where="cancellation.run_cancellable",
                              waited_for=waited_for)
    except Exception:  # noqa: BLE001 - 旁路
        pass
