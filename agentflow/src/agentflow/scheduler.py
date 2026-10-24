"""调度：按写集互斥分波并发（`DESIGN-CONDUCTOR.md` §5）。

## 为什么用"写集"而不是"依赖图"

依赖图需要每个动作声明前置，那会逼所有角色改签名（`capabilities.py` 里的
动作签名是从真实代码推出来的，加一个 `requires=` 就等于要求每个角色方法
都多一个参数）。写集是从角色推出来的（`WRITE_SETS`），零成本、可判定、可测。

代价是它比真依赖图保守（可能少并发）。这个方向是刻意的：
保守的代价是多花时间，激进的代价是数据被改坏 —— 而后者不会报错。

## 三条硬要求，以及它们各自的实现落点

1. 波内并发、波间串行 —— `run_waves` 里每波 `ThreadPoolExecutor`，
   一波结束才进下一波。
2. 合并顺序按输入顺序 —— 结果先按下标放进 `out`，最后按原顺序返回。
   完成顺序绝不影响输出顺序（"可复现性优先于速度"，设计 §5）。
3. 峰值并发 ≤ max_concurrency —— 两道闸：划分时单波容量就是上限
   （`policy.waves_of(limit=...)`），运行时再加一个 `Semaphore`。
   两道都要：划分保证正常路径不超，信号量保证即使有人绕过划分也不超。
   为什么不靠 `ThreadPoolExecutor(max_workers=...)` 兜底：那只是线程数上限，
   而"同时运行的任务数"是可以大于线程数的（一个线程里串行跑两个任务时，
   两个任务的重叠窗口仍然只有一个线程，但线程池不是那个语义的判据来源）。

## 部分失败语义

任一 call 被 refused / failed / cancelled 不中断其它 call。
"子任务可降级，整体绝不谎报成功"：返回列表里每一项都如实带自己的
`status`/`outcome`，没有任何一处把"没做"折进"做了"。
"""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import capabilities as C
from . import policy as P
from . import schema as S
from .cancellation import CancelToken


@dataclass
class TaskCall:
    """一次召唤请求（还没执行）。`Conductor.run_plan` 接收的就是它的序列。

    为什么把 `parent_task_id` / `input_key` 放在这里而不是让调用方直接传
    `depth`：深度是从链上推出来的（`parent.depth + 1`，I-3），
    让调用方自己填 depth 就等于允许它填错，而填错的症状是"深度上限静默失效"。
    调用方只能给"我的父是谁"，深度由 `Conductor` 从 `tasks` 表读出来算。

    `lineage`：祖先链上已出现过的 `(role, action, input_key)`（含父自己）。

    缺省是 `None`（不是 `()`） —— `44 J-32` / `draft/56 §2 主线 A` 的第一条
    零风险改动。`()` 与"这条链上什么都没有"长得一样，于是 `scheduler` 每一次
    都把一个空链塞给 `Conductor`，而 `Conductor` 那边"给了 lineage 就不重建"
    ⇒ `policy` 的 `cycle` 判据（`d.key in d.ancestry`）永远不可达：真机读数里
    `cycle/depth/fanout/concurrency` 全 0、`parent_task_id` 全空、`depth` 全 1。

    `None` 的语义是"调用方没表达过祖先链" ⇒ `Conductor` 从 `tasks` 表按
    `parent_task_id` 重建（跨进程/跨会话之后调用栈就没了，台账是唯一的权威来源）。
    纯调度的测试要表达"链上已经有过什么"时显式给一个非空元组。
    """

    role: str
    action: str
    params: Mapping[str, Any] = field(default_factory=dict)
    #: 谁召唤的（`"M"` / `"A"`…）。决定边判定与子任务的 `called_by`。
    by: str = S.CONDUCTOR_ROLE
    parent_task_id: str | None = None
    input_key: str = ""
    #: 本次召唤的钱上限（`{"max_usd": 0.05}`）。None = 用全局预算。
    #: 2026-10-15 业主裁定 A7：这里此前写的是 `{"max_tokens": 5000}` ——
    #: token 那一轴已删（「我们不卡 token，只卡总花销的钱」）。
    budget: Mapping[str, Any] | None = None
    lineage: tuple[tuple[str, str, str], ...] | None = None
    #: 实例标签（2026-09-30 加）：同一角色的第 N 个并发实例，例如 `"1"` / `"2"`。
    #: 空串 = "这个角色只有那一个实例"，与从前逐字同义（写集冲突照旧按角色算）。
    #: 显式给两个不同的标签 ⇒ 这两个调用允许同波并发（见 `policy.estimate_write_conflict`）。
    instance: str = ""
    #: 名册登记要用的那几格（`brief` / `task` / `name` / `reuse`；2026-10-21）。
    #:
    #: 为什么挂在 TaskCall 上而不是让 `summon` 从台账读：`schema.Task` 里没有
    #: `brief` / `task` 两格（禁改区），而"父给的那句简介"只活在派活的那个载荷里
    #: （`_do_summon_many` 的每个 target）。批量那条路上 `summon` 是由 `scheduler`
    #: 逐个调起来的，中间只传 `TaskCall` ⇒ 这一格是那份材料唯一的载体。
    #: `None` = 这一路没有材料（例如 `pipeline` / `deliver`），秘书按任务原文代写。
    roster: Mapping[str, Any] | None = None


class MemoryBudgetTracker:
    """本次 run 的即时视图 —— 只回答"这次 run 还能不能再召唤"。

    ## 它不是账（主控裁决，FC-19）

    权威账在 `usage_ledger`（由 `tokenmeter.TokenMeter` 写与读）；
    两处口径若不一致，以台账为准。

    `tasks.tokens/usd` 也由台账派生（`Conductor._charge_and_settle` 先
    `charge()`、再 `tokens_for()` 抄回来），所以这不是"两份账但愿它们相等"，
    而是"一份账 + 一个视图"。

    为什么还要留着这个视图：它回答的是编排层的瞬时问题 ——
    "本次 run 到现在花了多少、还能不能再派一个任务"，问一次不必去扫全表；
    而"这次部署累计花了多少、预算还剩多少"是台账的问题（可能跨 run、
    跨进程）。两个问题本来就不同，所以是两个对象，不是一个对象兼两职。

    它不再声称是账：`spend()` 只把它自己的计数器往前推，`reconcile()`
    负责把它对齐到权威账。唯一读取方是 `Conductor.stats()` 与观测代码 ——
    策略判定不读它：预算只由 `TokenMeter.guard()` 判（单一来源），
    否则"一处说还能花、另一处说不能"会漂移。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens = 0
        self._usd = 0.0

    @property
    def tokens(self) -> int:
        with self._lock:
            return self._tokens

    @property
    def usd(self) -> float:
        with self._lock:
            return self._usd

    def spend(self, tokens: int = 0, usd: float = 0.0) -> None:
        """推高本次 run 的视图。不写账 —— 写账是 `TokenMeter.charge` 的事。"""
        with self._lock:
            self._tokens += max(0, int(tokens))
            self._usd += max(0.0, float(usd))

    def reset(self) -> None:
        """清空（只给新的 run 用）。为什么需要它：`Conductor` 是可重入的
        （同一个实例可以跑多个 plan），而"这次 run 花了多少"必须是每次 run
        的量，不是实例的生命周期量。"""
        with self._lock:
            self._tokens = 0
            self._usd = 0.0

    def reconcile(self, *, tokens: int, usd: float) -> None:
        """把视图对齐到权威账给出的量。方向只有一个：以账为准。

        为什么必须能对账：视图与账一旦漂移（一条路径记了视图没记账、或反过来），
        "还能不能再召唤"就会与"账上还剩多少"给出不同答案 —— 而那正是
        `verify.py` 的 `usage_task_total_mismatch` 要问的问题。
        """
        with self._lock:
            self._tokens = max(0, int(tokens))
            self._usd = max(0.0, float(usd))

    def state(self, policy: P.Policy) -> dict:
        """三态视图：`None` = 不限。不折叠成 0（`None` 与 0 是两件事）。"""
        return P.budget_state(policy, spent_tokens=self.tokens, spent_usd=self.usd)


class ConcurrencyProbe:
    """峰值并发探针。

    为什么需要它：断言"峰值 ≤ 上限"必须从运行时观测，不能只看
    `max_workers=4` 这行代码 —— 那是"我打算这么做"，不是"实际发生了什么"。
    探针记三件事：当前并发数、峰值、以及每个窗口的 `[start, end]` 区间
    （区间让测试能直接问"这两个任务真的重叠了吗"，而不必比较总耗时）。

    它与 `Conductor.peak_running` 不是同一个量，两者都要留着：

    | 量 | 数的是什么 | 会不会低估真并发 |
    |---|---|---|
    | `probe.peak` | 真的在跑的任务数（进执行窗口 +1、出窗口 -1） | 不会 —— 它是"真并发"的判据 |
    | `conductor.peak_running` | 已登记 `running` 且未写终态的行数 | 会 —— 落 `running` 行本身要花时间（一次 fsync 事务），先落完的可能已经跑完了 |

    把两者混为一谈会让"峰值并发"的断言偶发失败（取决于机器快慢），
    而那正是"时间断言要给足余量"要防的东西。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.windows: list[dict] = []

    def enter(self, label: str) -> int:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            return self.current

    def leave(self) -> None:
        with self._lock:
            self.current -= 1

    def record(self, label: str, start: float, end: float, peak: int) -> None:
        with self._lock:
            self.windows.append(
                {"label": label, "start": start, "end": end, "concurrent": peak}
            )

    def overlapped(self, a: str, b: str) -> bool:
        """两个标签的窗口是否真的重叠（半开区间 `[start,end)`）。

        用窗口而不是总耗时来判"真并发"：总耗时是一个受 CI 负载影响的
        统计量，而区间重叠是结构性事实。两者都断言（见测试），
        但只有后者是"真并发"的判据 —— 前者会被"机器很慢"变成假阴性。
        """
        with self._lock:
            wa = [w for w in self.windows if w["label"] == a]
            wb = [w for w in self.windows if w["label"] == b]
        return any(x["start"] < y["end"] and y["start"] < x["end"] for x in wa for y in wb)


#: 兼容旧名（内部曾叫 `_ConcurrencyProbe`）。指同一个类，不是第二份实现。
_ConcurrencyProbe = ConcurrencyProbe


def _time() -> float:
    import time

    return time.monotonic()


def run_waves(
    calls: Sequence[TaskCall],
    *,
    conductor: Any,
    policy: P.Policy,
    token: CancelToken | None = None,
    probe: ConcurrencyProbe | None = None,
) -> list[Any]:
    """按写集分波执行 calls，结果按输入顺序返回。

    返回列表的长度恒等于 `len(calls)`：没有任何一项会因为异常而消失。
    "某一项没有结果"这件事由那一项自己的 `SummonResult.status/outcome`
    表达（例如 `failed`），不由列表变短表达 —— 变短的列表会让调用方
    静默地把"第 3 个失败了"读成"只有 2 个任务"。

    D-64：这是同一台引擎的阻塞式拼法（`start_waves(...).results()`）。
    要"派完立刻返回句柄、父代理继续拿回合"就用 `start_waves`。
    两条拼法共用一份分派代码，所以结果集/顺序/refusal 不可能漂移。
    """
    return start_waves(calls, conductor=conductor, policy=policy, token=token,
                       probe=probe).results()


#: 一批派活里"还没轮到的波"在协调线程里等上一波落定时的轮询上限（秒）。
#: 它不是忙等的判据（`WaveHandle` 用条件变量等，见 `_wait_wave`），只是
#: 取消/墙钟那种"没人来通知"的外部事件也要被看一眼的那个间隔。
_WAVE_POLL_SEC = 0.2


class CallTicket:
    """一批里的一项：`TaskCall` 本身 + 它的句柄（`Conductor.SummonHandle`）。

    `begin_done` 是"前半跑完了"的信号（派活方据此保证句柄返回时 `task_id`
    已经成立），它与"这一项跑完了"（句柄落定）是两件事。
    """

    __slots__ = ("index", "call", "handle", "started_at", "begin_done")

    def __init__(self, index: int, call: TaskCall) -> None:
        self.index = index
        self.call = call
        self.handle: Any = None
        self.started_at = _time()
        self.begin_done = threading.Event()

    @property
    def task_id(self) -> str | None:
        return getattr(self.handle, "task_id", None) if self.handle is not None else None

    def describe(self) -> dict:
        """已派出的那一项（句柄读数，不含结果）。"""
        got = {}
        if self.handle is not None and hasattr(self.handle, "describe"):
            got = dict(self.handle.describe())
        got.setdefault("role", self.call.role)
        got.setdefault("action", self.call.action)
        got.setdefault("instance", str(getattr(self.call, "instance", "") or ""))
        got["index"] = self.index
        return got


class WaveHandle:
    """一批派活的句柄：派完第一波就返回，不等到全部完成（D-64）。

    ## 为什么是"第一波"而不是"全部"

    分波是正确性判据（写集相交的两个 call 不许同时跑，见模块头第 1 条）。
    第一批已经在跑的那些必须同步派出去（`summon_begin` 落 running 行 +
    名册登记 + 发线程），否则"派没派出去"会变成一个稍后才成立的事实；
    而后面几波必须等前一波落定才能派（那是分波的定义）。于是句柄返回那一刻
    能诚实说出的是"已派出哪几个 + 还在跑哪几个"，后面的波会在协调线程里陆续
    出现（`dispatched()` 会跟着变多）。

    ## 与"忙等"的区别

    `wait_any` 走条件变量（落定就 `notify_all`），不是空转轮询；
    `_WAVE_POLL_SEC` 只用于"没有落定、但外部事件（取消/墙钟）该被看一眼"
    的那个兜底间隔。

    ## 列表兼容（为什么它像 list）

    `run_waves` / `Conductor.run_plan` 的既有调用方（含禁改区的
    `tools/conductor_tools.py`）都是"把返回值当列表用"（`len` / `zip` /
    `[... for r in results]` / `== []`）。本类实现 `__len__` / `__iter__` /
    `__getitem__` / `__eq__`，语义是"等全部落定再给你那一份" —— 于是
    "阻塞式拼法"不需要第二个类型，那批调用方一个字节都不用改。
    """

    def __init__(self, calls: Sequence[TaskCall], *, conductor: Any, policy: P.Policy,
                 token: CancelToken, probe: ConcurrencyProbe) -> None:
        self.calls = list(calls)
        self.conductor = conductor
        self.policy = policy
        self.token = token
        self.probe = probe
        self.waves: list[list[int]] = []
        self._tickets: list[CallTicket] = [CallTicket(i, c) for i, c in enumerate(self.calls)]
        self._cv = threading.Condition()
        self._settled: list[bool] = [False] * len(self.calls)
        self._new: list[int] = []
        self._all_done = threading.Event()
        self._coordinator: threading.Thread | None = None
        self._sem = threading.Semaphore(max(1, int(policy.max_concurrency)))
        self._started_at = _time()

    # ---------------------------------------------------------- 只读读数
    @property
    def count(self) -> int:
        return len(self.calls)

    def dispatched(self) -> list[dict]:
        """已经派出去的那些（按输入顺序）：每项带 role / action / instance / task_id。"""
        with self._cv:
            return [t.describe() for t in self._tickets if t.handle is not None]

    def running(self) -> list[str]:
        """还在跑的编号（按输入顺序）。已被拒/没派出去的不算在跑。"""
        out: list[str] = []
        with self._cv:
            tickets = list(self._tickets)
        for t in tickets:
            h = t.handle
            if h is not None and getattr(h, "running", None) and h.running():
                tid = getattr(h, "task_id", None)
                if tid:
                    out.append(str(tid))
        return out

    def settled(self) -> list[Any]:
        """已经落定的结果（按输入顺序，只含落定的那些）。"""
        return [self.settled_by_index()[i] for i in sorted(self.settled_by_index())]

    def settled_by_index(self) -> dict[int, Any]:
        """已经落定的那些，按输入下标给（`_do_summon_many` 要按输入顺序拼 results）。"""
        out: dict[int, Any] = {}
        with self._cv:
            ready = [i for i in range(len(self.calls)) if self._settled[i]]
        for i in ready:
            h = self._tickets[i].handle
            got = h.poll() if h is not None else None
            if got is not None:
                out[i] = got
        return out

    def take_settled(self) -> list[Any]:
        """把"上次取走之后新落定的"那几条结果取走（返场点用，每一条只投一次）。"""
        with self._cv:
            fresh = list(self._new)
            self._new.clear()
        out: list[Any] = []
        for i in fresh:
            h = self._tickets[i].handle
            got = h.poll() if h is not None else None
            if got is not None:
                out.append(got)
        return out

    def done(self) -> bool:
        """全部落定了没有（"没派出去的被拒项"也算落定）。"""
        return self._all_done.is_set()

    def poll(self) -> dict:
        """不等的一份读数：已派几个 / 在跑哪几个 / 落定几个 / 全完了没有。"""
        return {"dispatched": self.dispatched(), "running": self.running(),
                "settled": len(self.settled()), "count": len(self.calls),
                "done": self.done(), "waves": [list(w) for w in self.waves]}

    def wait_any(self, timeout: float | None = None) -> bool:
        """等到"又有东西落定"或到点。返回"到点时已经有东西落定"。

        为什么不是 `wait_all`：可抢占的语义是"等到有动静就返场"，不是
        "等到全部完成"。全部完成那一档是 `results()`（阻塞式拼法）。
        """
        deadline = None if timeout is None else _time() + max(0.0, float(timeout))
        with self._cv:
            if self._new:
                return True
            remain = None if deadline is None else max(0.0, deadline - _time())
            self._cv.wait_for(lambda: bool(self._new) or self._all_done.is_set(), timeout=remain)
            return bool(self._new)

    def wait_all(self, timeout: float | None = None) -> bool:
        """等到全部落定（或到点）。返回"落定了没有"。"""
        return self._all_done.wait(None if timeout is None else max(0.0, float(timeout)))

    def results(self) -> list[Any]:
        """阻塞式拼法：等全部落定，按输入顺序给出每一项的结果（长度恒等于输入长度）。"""
        self.wait_all()
        out: list[Any] = []
        for t in self._tickets:
            h = t.handle
            if h is None:  # pragma: no cover - 分派失败那条路会造一个已落定的句柄
                out.append(None)
            else:
                out.append(h.result())
        return out

    def elapsed_sec(self) -> float:
        return _time() - self._started_at

    # ---------------------------------------------------------- 列表语义
    def __len__(self) -> int:
        return len(self.results())

    def __iter__(self) -> Any:
        return iter(self.results())

    def __getitem__(self, index: Any) -> Any:
        return self.results()[index]

    def __eq__(self, other: Any) -> Any:
        if isinstance(other, WaveHandle):
            return self.results() == other.results()
        if isinstance(other, list):
            return self.results() == other
        return NotImplemented

    __hash__ = None            # 列表语义：不可哈希

    def __repr__(self) -> str:  # pragma: no cover - 只为调试可读
        return (f"WaveHandle(count={len(self.calls)}, dispatched={len(self.dispatched())},"
                f" running={len(self.running())}, done={self.done()})")

    # ---------------------------------------------------------- 分派与协调
    def start(self) -> "WaveHandle":
        """算出分波、把第一波同步派出去，然后把剩下的交给协调线程。"""
        self.waves = P.waves_of(self.calls, limit=self.policy.max_concurrency)
        if not self.calls:
            self._all_done.set()
            return self
        self._dispatch(0)
        ctx = contextvars.copy_context()
        th = threading.Thread(target=self._coordinate, args=(ctx,),
                              name="agentflow-waves", daemon=True)
        self._coordinator = th
        th.start()
        return self

    def _coordinate(self, ctx: Any) -> None:
        """协调线程：等这一波落定 → 派下一波 → 全落定就收。

        每一波的分派都用调用方的上下文（`ctx.copy().run`）：`consuming_as` /
        `calling_as` 是 ContextVar，丢了它，第二波派出去的活就"不知道自己是谁"。
        """
        try:
            for n in range(len(self.waves)):
                self._wait_wave(n)
                if n + 1 < len(self.waves):
                    ctx.copy().run(self._dispatch, n + 1)
        except BaseException as exc:  # noqa: BLE001 - 不许让协调线程静默死掉
            self._fail_remaining(exc)
        finally:
            self._all_done.set()
            with self._cv:
                self._cv.notify_all()

    def _wait_wave(self, n: int) -> None:
        indexes = list(self.waves[n]) if n < len(self.waves) else []
        with self._cv:
            while not all(self._settled[i] for i in indexes):
                self._cv.wait(timeout=_WAVE_POLL_SEC)

    def _dispatch(self, n: int) -> None:
        """把第 n 波派出去：每一项一条线程（前半 + 后半都在那条线程里）。

        ## 为什么前半也在线程里（而不是在派活方这一侧顺序写台账）

        两条理由，任一条都足够：

        1. 探针的口径。`concurrent_peak` 回答的是"同一时刻在飞几个"，
           而"在飞"从这一项被派出那一刻起算（与改前 `_guarded` 逐字同口径：
           它也是先 `enter` 再调 `Conductor.summon`）。如果 begin 在派活方
           顺序跑，秒级就能跑完的那几个会"一个接一个地开始并结束"
           ——`concurrent_peak` 会读成 2 而不是 3（实测：三个实例同波）。
        2. 真并发。begin 里有几笔台账写（落 running 行、名册登记），
           顺序跑它们等于把"并发开 3 个 B"变成"串行写 3 行再并发跑"。

        ## 但句柄必须"派完就有编号"

        所以这一波的所有线程都起来之后，这里等每一张票的 `begin_done`
        （不是等它跑完）。于是 `start_waves` 返回那一刻，`dispatched()`
        里的 `task_id` 一个不少 —— 而孩子可能一个都没跑完。
        """
        if n >= len(self.waves):
            return
        ctx = contextvars.copy_context()
        threads: list[threading.Thread] = []
        for i in self.waves[n]:
            th = threading.Thread(target=ctx.copy().run,
                                  args=(self._item_thread, i),
                                  name=f"agentflow-item-{i}", daemon=True)
            threads.append(th)
        for th in threads:
            th.start()
        for i in self.waves[n]:
            self._tickets[i].begin_done.wait(timeout=600.0)

    def _item_thread(self, i: int) -> None:
        """一张票的一生：open 句柄 → 前半 → （派得出去就）后半 → 落定。"""
        call = self.calls[i]
        ticket = self._tickets[i]
        label = _label(call)
        began = _time()
        peak = self.probe.enter(label)
        try:
            start = self.conductor.summon_begin(
                call.role, call.action, dict(call.params or {}),
                by=call.by, parent_task_id=call.parent_task_id,
                input_key=call.input_key,
                budget=dict(call.budget) if call.budget else None,
                token=self.token,
                lineage=call.lineage,
                instance=str(getattr(call, "instance", "") or ""),
                roster=dict(call.roster) if call.roster else None,
            )
        except BaseException as exc:  # noqa: BLE001 - 见 `_settle_failure`
            self._close_window(label, began, peak)
            self._settle_failure(i, exc)
            return
        handle = self.conductor.open_handle(
            start, on_settle=lambda h, _i=i: self._on_settle(_i))
        ticket.handle = handle
        ticket.begin_done.set()
        if getattr(start, "refusal", None) is not None:
            # 没派出去：窗口立刻关（它没有执行窗口可言，与改前一致）。
            self._close_window(label, began, peak)
            handle.settle(start.refusal)
            return
        self._sem.acquire()
        try:
            res = self.conductor.summon_run(start)
        except BaseException as exc:  # noqa: BLE001 - 后台没人接的异常会丢结果
            handle.fail(exc)
        else:
            handle.settle(res)
        finally:
            self._close_window(label, began, peak)
            self._sem.release()

    def _close_window(self, label: str, began: float, peak: int) -> None:
        self.probe.record(label, began, _time(), peak)
        self.probe.leave()

    def _run_one(self, start: Any, *, began: float, peak: int, label: str) -> Any:
        """在一张票的后台线程里跑后半：信号量在这一层，探针窗口已由派活方打开。"""
        self._sem.acquire()
        try:
            return self.conductor.summon_run(start)
        finally:
            self._close_window(label, began, peak)
            self._sem.release()

    def _on_settle(self, i: int) -> None:
        with self._cv:
            if not self._settled[i]:
                self._settled[i] = True
                self._new.append(i)
            self._cv.notify_all()

    def _settle_failure(self, i: int, exc: BaseException) -> None:
        """前半就炸了（存储层）：如实落一张"失败"的票，不让这一批变短。

        改前这条异常经线程池的 `fut.result()` 炸给 `run_waves` 的调用方 ⇒
        整批丢结果。"列表长度恒等于输入长度"因此更强了，不是更弱。
        """
        from .conductor import SummonResult, SummonStart

        call = self.calls[i]
        detail = (f"派活前半炸了（{type(exc).__name__}: {exc}）；"
                  "这一项没有台账行，但它在结果列表里的位置照旧保留")
        failure = SummonResult(role=str(call.role), action=str(call.action),
                               status="failed", outcome="failed",
                               error=f"{type(exc).__name__}: {exc}", detail=detail)
        start = SummonStart(role=str(call.role), action=str(call.action),
                            params=dict(call.params or {}), by=str(call.by),
                            parent_task_id=call.parent_task_id,
                            input_key=str(call.input_key),
                            instance=str(getattr(call, "instance", "") or ""),
                            token=self.token, refusal=failure)
        handle = self.conductor.start_summon(
            start, on_settle=lambda _h, _i=i: self._on_settle(_i))
        self._tickets[i].handle = handle

    def _fail_remaining(self, exc: BaseException) -> None:
        """协调线程炸了：还没派出去的那些如实标成 failed（不许静默消失）。"""
        with self._cv:
            left = [i for i in range(len(self.calls)) if not self._settled[i]]
        for i in left:
            if self._tickets[i].handle is None:
                self._settle_failure(i, exc)


def start_waves(
    calls: Sequence[TaskCall],
    *,
    conductor: Any,
    policy: P.Policy,
    token: CancelToken | None = None,
    probe: ConcurrencyProbe | None = None,
) -> WaveHandle:
    """按写集分波派出去，派完第一波就返回句柄（D-64 的可抢占拼法）。

    与 `run_waves` 的唯一差别是"什么时候返回"：这一支不等结果，
    父代理因此可以继续拿回合（watch / guide / 补派 / 收口），
    孩子的结果在下一次返场时由 `agent_loop` 的投递点读走。

    返回的 `WaveHandle` 同时是列表兼容的（`results()` 语义），所以
    "要那一份完整列表"的调用方可以照旧 `list(handle)` / `handle.results()`。
    """
    calls = list(calls)
    P.assert_policy_complete(policy)
    token = token or getattr(conductor, "token", None) or CancelToken()
    probe = probe if probe is not None else ConcurrencyProbe()
    # 把探针挂回 conductor：`peak_running` 会低估真并发（落 running 行
    # 本身要花时间），而探针不会。验收时不希望调用方自己去建探针再传进来
    # （那会让"忘了传"变成"没观测到"）。见 `ConcurrencyProbe` 的对照表。
    conductor._last_probe = probe
    return WaveHandle(calls, conductor=conductor, policy=policy, token=token,
                      probe=probe).start()



def _label(call: TaskCall) -> str:
    return f"{call.role}.{call.action}@{call.parent_task_id or 'root'}"


def _guarded(
    call: TaskCall,
    *,
    conductor: Any,
    token: CancelToken,
    sem: threading.Semaphore,
    probe: ConcurrencyProbe,
) -> Any:
    """执行一个 call，保证返回一个 SummonResult（异常在 `Conductor` 内被转成行）。

    为什么 `finally` 里一定要出信号量和探针：`summon` 理论上可能抛
    （例如 SQLite/文件锁层面的 `StoreError`）。漏掉一次 release 会让
    信号量永久少一个名额，于是后续所有并发静默降级为串行 ——
    一种"跑得慢但一切正常"的故障，最难查。
    """
    label = _label(call)
    sem.acquire()
    start = _time()
    peak = probe.enter(label)
    try:
        return conductor.summon(
            call.role,
            call.action,
            dict(call.params or {}),
            by=call.by,
            parent_task_id=call.parent_task_id,
            input_key=call.input_key,
            budget=dict(call.budget) if call.budget else None,
            token=token,
            # `call.lineage` 原样传（`None` = 没表达过 ⇒ `Conductor` 从台账重建；
            # 见 `TaskCall.lineage` 那段：把它折成 `()` 会让 `cycle` 判据不可达）。
            lineage=call.lineage,
            instance=str(getattr(call, "instance", "") or ""),
            roster=dict(call.roster) if call.roster else None,
        )
    finally:
        end = _time()
        probe.record(label, start, end, peak)
        probe.leave()
        sem.release()


def run_tasks(calls: Sequence[TaskCall], *, policy: P.Policy, conductor: Any, token: CancelToken | None = None) -> list[Any]:
    """`run_waves` 的别名（设计 §5 的伪代码用的是这个名字）。

    保留两个名字是因为设计文档里的名字与实现里的名字不一致本身就是
    一种文档漂移。这里两个都导出，且指向同一个实现（不是第二份代码）。
    """
    return run_waves(calls, conductor=conductor, policy=policy, token=token)


def wave_summary(calls: Sequence[TaskCall], *, policy: P.Policy) -> list[dict]:
    """只算不跑：把分波结果显示成人可读的摘要（CLI / 报告用）。

    为什么值得一个公开函数：分波是唯一决定"谁和谁并发"的地方。
    能把它单独打印出来，就让"为什么这两个任务串行了"有一个可读的答案，
    而不是只能靠读代码猜。
    """
    calls = list(calls)
    waves = P.waves_of(calls, limit=policy.max_concurrency)
    return [
        {
            "wave": n,
            "size": len(w),
            "calls": [
                {"role": calls[i].role, "action": calls[i].action,
                 "write_set": sorted(C.write_set_of(calls[i].role))}
                for i in w
            ],
        }
        for n, w in enumerate(waves)
    ]
