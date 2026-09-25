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

import threading
import time
from dataclasses import dataclass


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
    #: 谁发起的取消（"user" / "conductor.dispose" / "deadline" / "budget"）。
    by: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "detail": self.detail,
            "outcome_known": self.outcome_known,
            "by": self.by,
        }


#: 受控的取消原因。与 `schema.REFUSAL_REASONS` 分开：拒绝是策略的决定，
#: 取消是外部的决定（人按了停止、时间到了、预算没了）。
CANCEL_CODES: tuple[str, ...] = (
    "user",              # 人/调用方显式取消
    "deadline",          # 墙钟截止
    "budget",            # 预算耗尽
    "dispose",           # Conductor 被销毁
    "cancelled",         # 未分类（不要用它：它等于没写原因）
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
    - `token_budget`：预算耗尽与取消走同一个信号 —— 因为处置完全一样
      （停止派新任务 + 协作式取消在跑的），分成两套信号会让"停止"出现两条路径。
    """

    __slots__ = ("_lock", "_reason", "_deadline", "_token_budget", "_tokens_used", "_cancelled_flag")

    def __init__(self, *, deadline: float | None = None, token_budget: int | None = None) -> None:
        self._lock = threading.Lock()
        self._reason: CancelReason | None = None
        self._deadline = deadline
        self._token_budget = token_budget
        self._tokens_used = 0
        self._cancelled_flag = False

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
            if self._token_budget is not None and self._tokens_used >= self._token_budget:
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
            if self._token_budget is not None and self._tokens_used >= self._token_budget:
                return CancelReason(
                    "budget",
                    f"token 预算已耗尽（{self._tokens_used}/{self._token_budget}）",
                    outcome_known=False,
                    by="budget",
                )
            return None

    @property
    def tokens_used(self) -> int:
        with self._lock:
            return self._tokens_used

    @property
    def token_budget(self) -> int | None:
        return self._token_budget

    # ---------------------------------------------------------------- 动作
    def cancel(self, reason: str = "user", *, detail: str = "", by: str = "unknown") -> CancelReason:
        """取消。幂等且 first-wins：第二次调用不改变第一次的理由。

        为什么 reason 也不能改：它会被写进台账的 `detail`，而
        "为什么停的"必须只有一个答案 —— 两个答案等于没有答案。
        （`Task.validate` 的"终态先到先得"防的是同一件事的另一面：
        先写下的 `ended_at` 决定了这一行说什么，后来的取消只能什么都不做。）

        返回第一次定下的那个理由（而不是 None）：调用方拿它去写台账，
        于是"是谁先喊的停"是可审计的。
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
            return self._reason

    def consume_tokens(self, n: int) -> bool:
        """记一笔 token 消耗。返回这次消耗之后是否仍然没超预算。

        为什么返回 bool 而不是抛：预算耗尽的处置与取消完全一样，
        而"抛异常"会让调用方以为这是一次失败（`failed`），
        把"预算到了"写成"代码崩了"——正是本项目最忌讳的那类折叠。
        """
        with self._lock:
            self._tokens_used += max(0, int(n))
            if self._token_budget is None:
                return True
            return self._tokens_used < self._token_budget

    def raise_if_cancelled(self) -> None:
        """在 handler 的关键点调用它 —— 协作式取消的全部实现。

        为什么不做抢占式（`threading.Thread.kill` 之类）：本项目不自己 spawn
        进程/线程去跑角色（那会让离线、确定性、可复现全部失守，设计 §1.3）。
        更实际的理由是：在事务中间强杀会让"已写了半张表"成为常态，
        而半张表比"慢一点"危险得多。所以取消是请求，执行单元在
        它能安全停下的点上响应。
        """
        if self.cancelled:
            r = self.reason
            raise CancelRequested(detail_of(r) if r else "cancelled")

    def to_dict(self) -> dict:
        """台账/日志形态。`reason` 为 None 时原样是 None（不折叠成默认理由）。"""
        r = self.reason
        return {
            "cancelled": self.cancelled,
            "reason": r.to_dict() if r is not None else None,
            "tokens_used": self.tokens_used,
            "token_budget": self.token_budget,
        }


def detail_of(reason: CancelReason | None) -> str:
    """把理由渲染成人可读的一句话。None ⇒ 明确写"未给出理由"。

    这里不返回空串：空串在台账里与"这一列没填"长得一样，
    而"取消了但说不出为什么"是一件需要被看见的事。
    """
    if reason is None:
        return "取消（未给出理由）"
    return f"取消[{reason.code}] {reason.detail}".strip()
