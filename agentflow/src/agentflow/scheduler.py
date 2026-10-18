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

import concurrent.futures as cf
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
    #: 本次召唤的**钱**上限（`{"max_usd": 0.05}`）。None = 用全局预算。
    #: ⚠️ 2026-10-15 业主裁定 A7：这里此前写的是 `{"max_tokens": 5000}` ——
    #: token 那一轴已删（「我们不卡 token，只卡总花销的钱」）。
    budget: Mapping[str, Any] | None = None
    lineage: tuple[tuple[str, str, str], ...] | None = None
    #: 实例标签（2026-09-30 加）：同一角色的第 N 个并发实例，例如 `"1"` / `"2"`。
    #: 空串 = "这个角色只有那一个实例"，与从前逐字同义（写集冲突照旧按角色算）。
    #: 显式给两个不同的标签 ⇒ 这两个调用允许同波并发（见 `policy.estimate_write_conflict`）。
    instance: str = ""


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
    """
    calls = list(calls)
    if not calls:
        return []
    P.assert_policy_complete(policy)
    token = token or getattr(conductor, "token", None) or CancelToken()

    out: list[Any] = [None] * len(calls)
    # 信号量是第二道闸：划分已经保证单波 ≤ max_concurrency，
    # 但如果有人绕过划分（直接调 `_guarded`）或将来改了划分，它兜底。
    sem = threading.Semaphore(max(1, int(policy.max_concurrency)))
    probe = probe if probe is not None else ConcurrencyProbe()
    # 把探针挂回 conductor：`peak_running` 会低估真并发（落 running 行
    # 本身要花时间），而探针不会。验收时不希望调用方自己去建探针再传进来
    # （那会让"忘了传"变成"没观测到"）。见 `ConcurrencyProbe` 的对照表。
    conductor._last_probe = probe

    for wave in P.waves_of(calls, limit=policy.max_concurrency):
        if not wave:
            continue
        if len(wave) == 1:
            # 单元素波不建线程池：线程池会让"串行的两个任务"也各自开一个
            # 线程，而"波内并发"的判据本该是"同一个波里有几个元素"。
            # 更重要的是：不起线程 ⇒ 主线程直接跑 ⇒ 台账里这一行的
            # `started_at`/`ended_at` 与调用栈一致，调试时不会"跳线"。
            i = wave[0]
            out[i] = _guarded(calls[i], conductor=conductor, token=token, sem=sem, probe=probe)
        else:
            with cf.ThreadPoolExecutor(max_workers=min(len(wave), policy.max_concurrency)) as pool:
                futures = {
                    pool.submit(_guarded, calls[i], conductor=conductor, token=token, sem=sem, probe=probe): i
                    for i in wave
                }
                for fut in cf.as_completed(futures):
                    i = futures[fut]
                    # `_guarded` 自己兜住所有异常并返回 SummonResult；
                    # 走到这里还有异常说明是它自己坏了（例如返回类型不对）。
                    # 那种情况下必须炸出来，而不是填一个 None ——
                    # 见上面"列表长度恒等"的说明。
                    out[i] = fut.result()
    return out


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
