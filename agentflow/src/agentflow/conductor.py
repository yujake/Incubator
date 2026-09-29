"""主控编队：把"一次召唤"做成可审计、可拒绝、可取消、可重建的台账行。

## 主控是什么（以及它不是什么）

用户只对主控说话。主控负责：理解 → 拆解 → 召唤 → 汇总 → 报告。

它不是一个额外的"智能层"：它不产出知识、不写关系、不改稿件。
它的产出只有两类：(a) 召唤、(b) 给用户的汇总。
这条约束让它可测试：主控的"正确性"= 它发出的召唤序列是否满足策略与预算，
而不是"它聪不聪明"。所以本模块里没有任何 LLM 调用 ——
真 LLM 主控由 `SubagentBackend` 承担（本轮显式未接线）。

## 两个最容易写错的地方，以及本模块的处理

### 1. 拒绝是 `status="done", outcome="refused"`

`refused` 是一次成功的执行 —— 框架正确地说了"不"（越权 / 超预算 /
超深度 / 循环）。把它写成 `failed` 会让"策略拦住了"与"代码崩了"混在一起，
而这两件事需要完全不同的处置。`schema.Task.validate` 已经把这条钉死
（`outcome=refused` ⇒ `status` 必须是 `done`），本模块只是不去违反它。

拒绝也落台账：不写这一行，"我们拒绝了它"这件事就无可审计 ——
而"我拒绝过"恰恰是事后最需要回答的问题（是策略太紧，还是有人越权）。

### 2. `finish()` 必须幂等

对已结束的任务再调 ⇒ 零变更。实现方式不是在 `finish` 里"判断要不要写"，
而是在事务内重读当前行：只有 `status in ("pending","running")` 才写。
于是并发下两条路径同时想结束同一个任务时，先到的那条赢，
后到的那条读到终态后什么都不做 —— 这正是 FC-20 的"终态先到先得"，
而它由 `schema.Task.validate`（`pending/running` 却已有 `ended_at` ⇒ 拒）
从数据层再次兜住。

## 三态纪律在本模块的落点

| 场景 | 禁止 | 本模块的做法 |
|---|---|---|
| 角色没有这个动作 | 只写一句人话 | `refusal_reason="unknown_action"` |
| 动作没接线 | 抛异常 / 返回空 | `refusal_reason="not_wired"`（backend=subagent 亦然） |
| handler 返回 None | 当成 `ok` | `outcome="no_result"` |
| 查询没法做 | `checked=True, empty=True` | 原样透传 `checked=False` + `reason` |
| 被 dispose 砍掉 | 记成 `failed` | `status=cancelled` + detail 写"结果未知" |
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import capabilities as C
from . import cancellation as CX
from . import policy as P
from . import schema as S
from .cancellation import CANCEL_CODES, CancelRequested, CancelToken, detail_of
from .policy import Decision
from .scheduler import MemoryBudgetTracker, TaskCall
from .store import StoreError
#: 不在这里另定义 `ParamError`（曾经有过一份，被 linter 规则 R003 抓到）。
#:
#: 判据是"同一判据两处实现"：调用方按 `except ParamError` 捕获"参数不合法"时，
#: 若两处各有一个同名类，漏掉一半没有任何报错。`tools.base.ParamError`
#: 的语义本来就是"参数不合法，与『执行中失败』分开"，与本模块要的完全一致，
#: 所以选 import 同一份，而不是换名字（换名字会留下两个概念表达同一件事）。
from .modelcost import settle_key
from .tokenmeter import Charge, TokenMeter
from .tools.base import ParamError

#: 一次召唤的终局状态（`status`），与 `schema.TASK_STATUSES` 一致。
TERMINAL_STATUSES: tuple[str, ...] = ("done", "cancelled", "failed")

#: 标记"这一行已经结过账"（写进 `tasks.inputs`）。
#:
#: 为什么需要它：`finish()` 是幂等的（终态先到先得），而记账发生在 `finish`
#: 之后。若某一行在本轮 `finish` 之前已经是终态（另一个写者赢了），
#: 再记一次账会让 `usage_ledger` 的汇总变成 `tasks.tokens` 的两倍 ——
#: 而 `verify.py` 会（正确地）报 `usage_task_total_mismatch`。
#: 标记必须在同一事务内可读，所以它落在行上而不是内存里。
_SETTLED_MARK = "tokenmeter:settled"


@dataclass
class SummonResult:
    """一次召唤的结构化结果。永远不抛业务异常（设计 §2）。

    `status` 回答"跑完了没有"，`outcome` 回答"跑出了什么"。
    二者正交，六个组合都是有意义且必须能区分的：

    | status | outcome | 含义 |
    |---|---|---|
    | done | ok / no_result / not_applicable / refused | 跑完了（可能"确实没有"，也可能"框架拒绝了"） |
    | failed | failed | 执行中异常 |
    | cancelled | cancelled / refused | 没跑完（被取消 / 因超预算被拒） |

    `refused` 不是 `failed`：拒绝是策略的决定，失败是执行的结果。

    `task_id` 可以是 `None`：取消之后不产生新任务，此时没有台账行
    （没有 start 就没有 end，这与"每个 start 有且仅有一个 end"不冲突）。
    把它写成 `""` 或编一个 id 会让调用方以为"有一条对应的行"，那是谎报。
    """

    task_id: str | None = None
    role: str = ""
    action: str = ""
    status: str = "pending"
    outcome: str | None = None
    refusal_reason: str | None = None
    detail: str = ""
    error: str | None = None
    payload: Any = None
    artifacts: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    tokens: int = 0
    usd: float = 0.0
    depth: int = 1
    elapsed_sec: float = 0.0
    #: 本次召唤又召唤出了哪些任务（父 → 子的可读视图）。
    children: list[str] = field(default_factory=list)
    #: 三态：这个结果查过没有。`None` = 这个动作不适用"查"这个概念
    #: （例如"写一行 documents"）；`False` = 没法查（`payload` 里必须有 reason）。
    checked: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        """"成功"的判据只有一处：`status=="done" and outcome=="ok"`。

        为什么 `refused` 不算 ok（它在 status 层是 done）：调用方问
        `res.ok` 时想知道的几乎总是"东西做出来了吗"，而不是"框架运转正常吗"。
        把 refusal 算成 ok 会让"越权被拦住"在调用方看来像一次成功交付。
        """
        return self.status == "done" and self.outcome == "ok"


# ---------------------------------------------------------------- backend


class LocalBackend:
    """在进程内调用角色的 Python 实现（确定性、离线 —— 测试与验收走这条）。

    ## 显式接线（为什么不"自动创建"角色实例）

    角色的构造签名各不相同且都需要真实依赖：`AgentA` 要 `providers`、
    `AgentB` 要 `extractor` + `extract_text`、`AgentD` 要 `tools`……
    一个"自动 new 一个 AgentB"的 backend 只能靠猜依赖，而猜错的形态是
    静默少抽取一篇文献。所以本 backend 要求调用方显式给接线
    （`registry`），没给接线就明确拒绝（`not_wired`），绝不假装成功。
    """

    name = "local"

    def __init__(self, registry: Mapping[str, Any] | None = None) -> None:
        self.registry: dict[str, Any] = dict(registry or {})
        self._instances: dict[str, Any] = {}
        self._lock = threading.Lock()

    def known_roles(self) -> list[str]:
        return sorted(self.registry)

    def resolve(self, role: str) -> Any:
        """把注册项变成实例（惰性，且只建一次）。

        - 传 `("factory", fn)`：调 `fn(store=...)`；
        - 传 `("object", obj)`：直接用；
        - 传 `("class", cls)`：明确拒绝 —— 构造依赖无法自动满足，
          假装能建就是"猜依赖"（见类 docstring）。
        """
        with self._lock:
            if role in self._instances:
                return self._instances[role]
        entry = self.registry.get(role)
        if entry is None:
            raise NotWiredError(f"{role} 没有接线（registry 里没有它）")
        kind, value = entry if isinstance(entry, tuple) and len(entry) == 2 else ("object", entry)
        if kind == "class":
            raise NotWiredError(
                f"{role} 只注册了类 {value!r}：角色的构造依赖各不相同（providers/extractor/tools…），"
                "自动 new 只能靠猜，而猜错会静默少做事。请注册一个工厂或实例"
            )
        if kind == "factory":
            try:
                inst = value(store=self.store)
            except TypeError:
                inst = value()
        else:
            inst = value
        with self._lock:
            self._instances[role] = inst
        return inst

    #: 由 `Conductor` 注入（不放进构造签名，是为了让 backend 可以被单测直接建）。
    store: Any = None

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken) -> Any:
        """调一次 handler。

        参数名对不上就拒绝，不许静默丢弃。工具的 `ToolRegistry.call`
        是按 schema 校验后再调；这里的 handler 是角色的真实方法，
        它的形参名就是它与调用方的契约。把多出来的参数丢掉会让
        "我传了 `submit_requests=True` 但它被忽略了"看起来像一次成功 ——
        于是 `gaps()` 报告里说"已提交"，而请求一条也没有。

        ## `G-1`：token 不再"收下就扔"

        旧版末行是 `return fn(**given)` —— `token` 收了，然后一个字都没往下传，
        于是"取消"只覆盖待启动的任务：已经在跑的 handler 照样跑完，
        以 `done/ok` 结束（实测 `temp/auditG-probe1.txt`）。

        现在的形态：调用期间把 `token` 放进一个 `ContextVar`，handler 通过
        `cancellation.current_token()` / `raise_if_cancelled()` 读它，
        起子进程时用 `cancellation.run_cancellable(..., token=...)`。
        为什么用 ContextVar 而不是给实例挂属性：`resolve(role)` 按角色
        缓存实例，两个并发召唤会共享同一个对象 ⇒ 挂实例属性会让 A 的 token
        被 B 覆盖（静默串味：A 按了停止却停掉了 B）。ContextVar 按执行上下文隔离。

        调用前先查一次 token：已经取消的召唤不该进 handler（否则会白干一轮，
        还可能写半张表）。
        """
        spec = C.find_action(role, action)
        if spec is None:  # pragma: no cover - summon 已经查过，这里是纵深防御
            raise NotWiredError(f"{role} 没有动作 {action}")
        obj = self.resolve(role)
        fn = getattr(obj, spec.handler_name, None)
        if not callable(fn):
            # 装配期 `assert_capabilities` 核过类上有这个方法；走到这里说明
            # 实例上被屏蔽了（属性遮蔽 / 动态删除）。必须炸，不许当成"没接"。
            raise NotWiredError(f"{role} 的实例上没有可调用的 {spec.handler_name}")
        sig = inspect.signature(fn)
        accepts_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        declared = {n for n, p in sig.parameters.items() if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
        given = dict(params or {})
        if not accepts_kw:
            unknown = sorted(set(given) - declared)
            if unknown:
                raise ParamError(
                    f"{role}.{action}（{spec.handler_name}）不认这些参数：{unknown}；"
                    f"它只接 {sorted(declared)}。静默丢弃会让'我传了但它没看'看起来像成功"
                )
        # `G-1`：把 signal 送进 handler 的执行上下文；已取消 ⇒ 不进 handler
        token.raise_if_cancelled()
        var = CX._CURRENT_TOKEN
        reset = var.set(token)
        try:
            # 显式声明了 `token` / `cancel_token` 形参的 handler 直接收到它 ——
            # 这让"这个 handler 支持取消"在签名上可见（AST 扫得出来），
            # 而不必读实现才知道。没声明的走 ContextVar（今天全部如此）。
            for name in ("token", "cancel_token"):
                if name in declared:
                    given[name] = token
                    break
            return fn(**given)
        finally:
            var.reset(reset)


class SubagentBackend:
    """把同一次召唤交给 DSH 的 `subagent` / `workflow` 工具（本轮未接线）。

    ## 为什么它必须"显式拒绝"而不是"执行成功但没结果"

    设计 §6 说同一个角色规格驱动两种 backend。但本会话的 `Conductor` 是
    进程内、确定性的东西，它没有能力去调 DSH 的工具（那需要 harness 的
    权限面，而调用方是一个库）。于是这里只有两条诚实的路：

    - 假装跑通并返回空 ⇒ 台账里会留下 `outcome="ok"` 而 `payload=None` 的行。
      下游会把"我们没做"读成"做了但没有" —— 这正是本项目在引文校验、
      OCR、D 溯源、C 预算截断四处踩过的同一个坑。
    - 明确 `refused/not_wired` ⇒ 台账里留下"这里有一个尚未接线的执行面"。

    选后者。`detail` 里写清由谁承担。
    """

    name = "subagent"

    def __init__(self, reason: str = "") -> None:
        self.reason = reason or "由 DSH 的 subagent/workflow 承担（本进程内的 Conductor 没有该权限面）"

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken) -> Any:
        raise NotWiredError(f"{role}.{action} 未接线：{self.reason}")


class NotWiredError(RuntimeError):
    """动作没有接线。不是失败 —— 对应 `refused/not_wired`（见 §2.2 的表）。"""


# ---------------------------------------------------------------- 主控


#: 角色代码**故意抛出**的领域错误类名 → 它们在任务台账里算"拒绝这次调用"（R-46）。
#:
#: 为什么按**类名**匹配而不是 import 那些类：conductor 在 import 图上位于 agent_* 之上
#: （agent 模块会 import conductor 的类型），直接 import 会成环。类名匹配的代价是
#: "改了类名这里就失效" —— 所以下面 `selftest`/用例要有一条正控真的抛一次
#: `ExperimentError` 并断言落 `refused/invalid_params`（判据不许只活在注释里）。
_BUSINESS_ERROR_NAMES = frozenset({
    "ExperimentError", "DocumentError", "PlanError", "ReviewError",
    "EvidenceError", "ConjectureError", "ToolError",
})


def _business_refusal_code(exc: BaseException) -> str | None:
    """这次异常算不算"角色拒绝了这次调用"？算就返回受控理由码，否则 `None`。

    两条来源，优先级从高到低：
    1. 异常自带 `refusal_reason`（显式协议，且必须是受控词表里的值）；
    2. 异常是上表里的领域错误类（角色**故意**抛的）。
    其余一律 `None` ⇒ 由调用方记 `failed`（"代码/环境崩了"）。
    """
    code = getattr(exc, "refusal_reason", None)
    if isinstance(code, str) and code in S.REFUSAL_REASONS:
        return code
    if type(exc).__name__ in _BUSINESS_ERROR_NAMES:
        return "invalid_params"
    return None


class Conductor:
    """主控：确定性的策略执行者（本轮不做 LLM 推理，设计 §8 待决问题 1）。

    "想做什么"由调用方给出 plan（一串 `TaskCall`），主控负责：
    过策略 → 落台账 → 派给 backend → 写终态 → 汇总。
    """

    def __init__(
        self,
        store: Any,
        *,
        policy: P.Policy | None = None,
        registry: Mapping[str, Any] | None = None,
        backend: str | LocalBackend | SubagentBackend = "local",
        log: Callable[..., None] | None = None,
        token: CancelToken | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or P.Policy()
        self.log = log
        self.token = token or CancelToken()
        if isinstance(backend, str):
            if backend == "local":
                be: Any = LocalBackend(registry)
            elif backend == "subagent":
                be = SubagentBackend()
            else:
                # 未知 backend 不接受（fail-closed）：`backend="local "` 这种
                # 拼法若被当成"未知 ⇒ 大概无所谓"，就会得到一个既不本地也不
                # subagent 的执行面，而它的行为取决于后面哪一行 `if` 先命中。
                raise ValueError(
                    f"未知 backend={backend!r}（只支持 'local' / 'subagent'，或直接传 backend 对象）"
                )
        else:
            be = backend
        self.backend = be
        if isinstance(be, LocalBackend):
            be.store = store

        #: 本次 run 的即时视图（不是账）：只回答"这次 run 还能不能再召唤"。
        #: 权威账在 `usage_ledger`（由 `self.meter` 写、读）；两处口径若不一致，
        #: 以台账为准 —— 见 `MemoryBudgetTracker` 的 docstring。
        self.budget = MemoryBudgetTracker()
        #: 权威账（FC-19）。主控裁决：`usage_ledger` 是权威账，
        #: `tasks.tokens/usd` 由它派生（见 :meth:`_charge_and_settle`），
        #: 于是 `verify.py` 的 `usage_task_total_mismatch` 是由构造保证相等，
        #: 而不是"两处各算一遍但愿它们相等"。
        #:
        #: 预算上限取自 `Policy`：策略是判据的单一来源，这里只是把它交给守卫
        #: （不另写第二份上限）。`Policy.token_budget=None` ⇒ 守卫返回
        #: `limited=False, allowed=True`，即"没设预算 ⇒ 不限制"（这与其
        #: 语义"够用"是两件事，见 `MeterReading` 的 docstring）。
        self.meter = TokenMeter(
            store,
            budget_tokens=self.policy.token_budget,
            budget_usd=self.policy.usd_budget,
            log=log,
        )
        self._lock = threading.Lock()
        self._id_lock = threading.Lock()
        #: 正在运行的任务数（瞬时）。由本类维护，因为 backend 不知道全局。
        self._running: set[str] = set()
        self.peak_running = 0
        self._started_total = 0
        #: dispose 后一律拒绝新召唤（幂等）。
        self._disposed = False
        #: 墙钟起点与截止（`time.monotonic()`，不受 NTP 回拨影响）。
        self._start = time.monotonic()
        wall = self.policy.wall_clock_sec
        self.deadline: float | None = (self._start + float(wall)) if wall else None
        #: 第一个"停止"信号的人话说明（用于所有被它终止的任务）。
        self._cancel_detail: str | None = None
        #: 最近一次 `run_plan` 留下的并发探针（由 `scheduler.run_waves` 注入）。
        #: 它是"真并发"的观测口径 —— `peak_running` 会低估（见 `ConcurrencyProbe`）。
        self._last_probe: Any = None
        #: 本次 run 里已经开始的任务数（用于 max_tasks_per_run 判定）。
        self._started_total = 0
        #: 被取消而没有落台账的召唤数。必须计入总量：否则"取消了就不限次"
        #: 会成为绕过 `max_tasks_per_run` 的路径（取消一次不算数 ⇒ 取消一百万次
        #: 也不算数）。它与 `_started_total` 分开记，因为
        #: `stats()["started_total"]` 说的是"真的跑过几个"，两件事不能混。
        self._cancelled_total = 0

    # ---------------------------------------------------------------- 路径
    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self._start

    @property
    def deadline_hit(self) -> bool:
        """墙钟是否到点。`None` 的 deadline 表示"不限"（不是"立刻到点"）。"""
        if self.deadline is None:
            return False
        return time.monotonic() >= self.deadline

    def _log(self, message: str, **extra: Any) -> None:
        if self.log is None:
            return
        try:
            self.log(message, **extra)
        except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断编排（与各 agent 的 _log 同约定）
            pass

    # ---------------------------------------------------------------- 台账读写
    def _tasks(self) -> list[dict]:
        return self.store.rows("tasks")

    def _task(self, task_id: str) -> dict | None:
        return next((r for r in self._tasks() if r.get("task_id") == task_id), None)

    def _children_of(self, task_id: str) -> list[str]:
        return [str(r["task_id"]) for r in self._tasks() if r.get("parent_task_id") == task_id]

    def _ancestry(self, task_id: str | None) -> tuple[tuple[str, str, str], ...]:
        """重建 `(role, action, input_key)` 的祖先链（含起点自身）。

        为什么从台账重建而不是用调用栈：跨进程/跨会话之后调用栈就没了，
        而台账是唯一的权威来源（`schema.Task.parent_task_id` 的注释原话）。
        链上有环时（数据被手工改坏）用 `seen` 截断 —— 一个"为了报错而写死循环"
        的溯源函数是没法用的。
        """
        chain: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        cur = task_id
        while cur and cur not in seen:
            seen.add(cur)
            row = self._task(cur)
            if row is None:
                break
            chain.append((str(row.get("role") or ""), str(row.get("action") or ""),
                          str(row.get("input_key") or "")))
            cur = row.get("parent_task_id")
        return tuple(reversed(chain))

    def _depth_of(self, parent_task_id: str | None) -> tuple[int, str]:
        """子任务的深度 = 父的深度 + 1（I-3：深度单调不减，resume 后不重置）。

        主控发起 = 1，所以必须从父行读，不能从"当前调用栈有几层"推 ——
        后者在 `run_plan` 并发时是错的（工作线程的栈深度与召唤链深度无关）。
        """
        if parent_task_id is None:
            return 1, S.CONDUCTOR_ROLE
        row = self._task(parent_task_id)
        if row is None:
            raise ValueError(
                f"parent_task_id={parent_task_id!r} 在 tasks 表里不存在 —— "
                "凭空挂一个父会让深度链断裂（I-3 要求子 depth 恒等于父 depth+1）"
            )
        return int(row.get("depth") or 0) + 1, str(row.get("role") or "unknown")

    # ---------------------------------------------------------------- 写台账
    def _write_row(self, row: dict, *, note: str) -> None:
        """写一行 tasks。先构造 `Task` 并 validate，再落库。

        为什么显式 `validate()`：`store.tx` 提交时也会 `validate_table`，
        但那时的错误信息是 `tasks.rows[7] 校验失败：…`，读的人得自己数第 7 行
        是哪一条。这里先校验，错误信息里能带上 role/action/task_id。
        不 try/except 吞掉它 —— 缺陷掩盖比崩溃更危险。
        """
        S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
        with self.store.tx("tasks", actor="conductor", note=note) as tx:
            tx.upsert("tasks", row, note=note)

    def _write_new_row(self, row: dict, *, note: str) -> str:
        """取号 + 建行在同一个临界区内完成，返回 `task_id`。

        ## 为什么"先算号、再写行"是一个真实缺陷（不是防御性编程）

        `interactions.next_prefixed_id` 是纯函数（取 max+1 并跳过已占用），
        它没有计数器。所以分开做在并发下必错：

        1. 线程 C 算出 `t-0003`，还没写行就出了临界区；
        2. 线程 H 进来读 `tasks`，看不见 C 那一行（它还没被写），
           于是也算出 `t-0003`；
        3. 两行按主键 upsert ⇒ 后写的静默覆盖先写的。

        实测症状（`tests/test_conductor.py::test_concurrent_summons_never_share_a_task_id`
        就是它的回归测试）：同一个 `task_id` 出现在两个不同召唤的返回值里，
        台账里凭空少一次召唤，而没有任何地方报错。
        它与 `store.alloc_id` docstring 里记录的那次真实缺陷同族
        （`test_store_alloc_guard.py` 覆盖了 4 位空间那一半）。

        ## 另一个细节：`task_id` 必须是行 dict 的第一个键

        传入的 `row` 必须已经带 `task_id`（值先留空也行，这里会覆盖）。
        为什么这一点重要：快照是按 dict 的键顺序序列化的，而 `rebuild()` 用
        `Task.to_dict()`（= dataclass 字段顺序，`task_id` 在最前）重建行。
        如果第一次落盘时 `task_id` 被排在最后，`rebuild()` 之后键顺序会变，
        于是 `tasks.json` 逐字节不一致（I-9 直接失败）——
        数据没错，但"可重建"这条承诺破了。
        """
        with self._id_lock:
            with self.store.tx("tasks", actor="conductor", note=note) as tx:
                from .interactions import next_prefixed_id

                row["task_id"] = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
                ordered = {"task_id": row["task_id"]}
                ordered.update({k: v for k, v in row.items() if k != "task_id"})
                S.Task(
                    **{k: v for k, v in ordered.items() if k in S.Task.__dataclass_fields__}
                ).validate()
                tx.upsert("tasks", ordered, note=note)
        return str(row["task_id"])

    # ---------------------------------------------------------------- 拒绝
    def _refuse(
        self,
        role: str,
        action: str,
        *,
        reason: str,
        detail: str,
        by: str,
        parent_task_id: str | None,
        input_key: str,
        params: Mapping[str, Any],
        depth: int,
    ) -> SummonResult:
        """写一条"拒绝"的台账行并返回。拒绝也落台账（否则无可审计）。

        `status="done"` 是刻意的：拒绝是一次成功的执行 —— 框架正确地说了"不"。
        把它写成 `failed` 会让"策略拦住了"与"代码崩了"需要不同处置的这两件事
        长得一样（`schema.Task.validate` 会把 `outcome=refused` 且 `status!=done`
        直接判为非法，所以这里也没有第二种写法）。
        """
        started = S.now_iso()
        row = {
            # `task_id` 放第一个键：快照按 dict 的键顺序序列化，而 `rebuild()`
            # 用 `Task.to_dict()`（dataclass 字段顺序）重建 —— 顺序不一致会让
            # `tasks.json` 在 rebuild 后逐字节不同（I-9）。见 `_write_new_row`。
            "task_id": "",
            "role": role if role in (*S.ROLES, S.CONDUCTOR_ROLE) else S.CONDUCTOR_ROLE,
            "action": action or "unknown",
            "called_by": by,
            "parent_task_id": parent_task_id,
            "depth": max(1, depth),
            "input_key": input_key,
            "status": "done",
            "outcome": "refused",
            "refusal_reason": reason,
            "detail": detail,
            "error": None,
            # 拒绝没有真的跑，所以 started_at == ended_at。为什么不留空：
            # `status="done"` 要求 `ended_at` 非空（每个 start 有且仅有一个 end），
            # 而"它一毫秒也没跑"这件事由 detail 里的人话说明，不靠留空表达
            # （留空是非法行，会被 schema 直接拒）。
            "started_at": started,
            "ended_at": started,
            "tokens": 0,
            "usd": 0.0,
            "artifacts": [],
            "inputs": [],
        }
        # 取号与建行同一临界区（见 `_write_new_row` 的缺陷说明）——
        # 被拒的召唤也是并发写台账的（拒绝不需要抢策略的并发配额）。
        tid = self._write_new_row(row, note=f"refused:{reason}")
        self._log(f"拒绝 {by} → {role}.{action}：{reason}", detail=detail)
        return SummonResult(
            task_id=tid, role=row["role"], action=action, status="done", outcome="refused",
            refusal_reason=reason, detail=detail, depth=row["depth"],  # type: ignore[arg-type]
        )

    # ---------------------------------------------------------------- 记账（FC-19）
    def _meter_guard(self, role: str, budget: Mapping[str, Any] | None) -> Any:
        """开工前的预算守卫。返回 `tokenmeter.MeterReading`。

        双重预算（两条上限都要过）：

        1. 全局预算 —— `self.meter` 的 `budget_tokens/usd`，取自 `Policy`；
        2. 本次调用的预算 —— 调用方给的 `budget={"max_tokens": …}`。

        为什么两条都要：`summon(..., budget=...)` 的语义是"这一单最多准花多少"，
        它不是把全局预算换掉。若只判后者，一个调用方就能用 `budget={"max_tokens": 10**9}`
        绕过全局上限 —— 那正是"只有一类上限时另几类都可被绕过"（FC-18）的同族形态。

        实现方式：只有当本次调用给了预算时才派生一个 meter（读同一张
        `usage_ledger`，所以它看到的"已花"与权威账一致），否则直接用共享的那一个。
        每次现建是刻意的：`TokenMeter` 是无状态的（`spent()` 每次都读表），
        所以派生不带成本、也不会让"哪一份预算在生效"变得含糊。
        """
        est_tokens = 0
        if budget and budget.get("max_tokens") is not None:
            est_tokens = max(0, int(budget["max_tokens"]))
        if budget and (budget.get("max_tokens") is not None or budget.get("max_usd") is not None):
            per_call = TokenMeter(
                self.store,
                budget_tokens=(None if budget.get("max_tokens") is None
                               else int(budget["max_tokens"])),
                budget_usd=(None if budget.get("max_usd") is None else float(budget["max_usd"])),
            )
            reading = per_call.guard(est_tokens, role=role, scope="summon")
            if not reading.allowed:
                return reading
            # 本次预算过了，还要看全局（"这一单允许"不等于"全局还有钱"）
            return self.meter.guard(0, role=role, scope="summon")
        return self.meter.guard(0, role=role, scope="summon")

    def _charge_and_settle(self, res: SummonResult, *, role: str) -> SummonResult:
        """把这次召唤的花销记进权威账，再把账上的累计值写回 `tasks`。

        零值也记（`tokenmeter` 的设计②）：一次"跑了但没花 token"的召唤
        必须留下一条零值行，否则"没记账"与"花了零"无法区分，而"预算还剩多少"
        就永远答不准。`UsageEntry.validate` 要求零值必须带 `note`，所以这里
        无条件给一个说明。

        ## 幂等键同时进 `note` 与 `idem_key` 字段

        键由 `modelcost.settle_key(task_id)` 生成（幂等键的唯一生成处），
        由 `charge_once` 同时写进那一行的 `note` token 与 `idem_key` 字段。
        少了字段那一层，`schema.validate_table` 的字段级唯一性断言与
        `verify.duplicate_idem_key` 在真实路径上就永远没有输入 ——
        它们会在测试里常绿而在生产上从不生效。

        ## 接线各 agent 的 `_call` 时必须读这一段（否则会双记）

        现在的粒度是召唤级：这一条 `Charge(scope="summon", tokens_out=res.tokens)`
        是这一次召唤的唯一一笔。等各 agent 的 `_call` 也接上 `charge()`
        （细到每次工具调用 / 每次重试）之后，这里必须改成"只记零值兜底"：

        - `_call` 记的细账已经进了台账 ⇒ `summon` 再记一次会让
          `usage_ledger` 的汇总变成真实花销的两倍（而 `tasks.tokens`
          是从台账派生的，所以两边会一起虚高 —— 它们仍然"相等"，
          但相等的是错的数，这比不等更危险）；
        - 正确的形态：`_call` 记细账；`summon` 只在这一 task 还一条账都没有时
          补一条零值行（`tokens_for(task_id) == 0`），理由是"零值也要记"。

        记账失败不许让一次已经完成的召唤变成失败（钱已经花了、活已经干完了）：
        这里兜住异常并写进日志。但这不是静默失败 —— 后果（`tasks.tokens`
        与台账不等）会由 `verify.py` 的 `usage_task_total_mismatch` 报出来，
        而那正是"两处口径不一致"该被看见的地方。
        """
        note = f"{role}.{res.action} via {res.status}/{res.outcome}"
        spent = int(res.tokens or 0)
        try:
            # 恰好记一次。`finish()` 是幂等的（终态先到先得）：若这一行
            # 在本次 `finish` 之前已经是终态（另一个写者赢了），那么
            # 它当初就该被记过一次账 —— 再记一次会让 `usage_ledger` 的汇总
            # 变成 `tasks.tokens` 的两倍，而 `verify.py` 会（正确地）报
            # `usage_task_total_mismatch`。判据落在台账行的 `inputs` 里，
            # 因为那是一个能在同一事务内读到的既有标记位。
            row = self._task(res.task_id) if res.task_id else None
            already = bool(row and any(str(x) == _SETTLED_MARK for x in (row.get("inputs") or [])))
            if already:
                self._log(f"跳过重复记账（{res.task_id} 已结算）", task_id=res.task_id)
                return res
            charge = Charge(
                role=role if role in (*S.ROLES, S.CONDUCTOR_ROLE) else S.CONDUCTOR_ROLE,
                scope="summon",
                tokens_out=spent,          # 召唤层只知道总量；in/out 的细分由各 agent 的 _call 记
                usd=float(res.usd or 0.0),
                task_id=res.task_id,
                note=note,
            )
            if res.task_id:
                # 判重的权威在账本里（`charge_once` 的锁内比对），不在
                # `tasks.inputs` 的标记上。那个标记读得早（`self._task()` 是无锁
                # 快照读），两个实例同时结算同一行时两边都会读到"还没结算"，
                # 于是两笔账都落下去 —— 而两行的 `usage_id` 不同，按主键去重救不了。
                # `charge_once` 把判重搬进 `charge` 本来就持有的那把锁，
                # 后到的那个一定看得见前一笔。标记保留为便宜的快速通道。
                #
                # 键由 `modelcost.settle_key` 生成（幂等键的唯一生成处），
                # `charge_once` 会把它同时写进 `note` 的 token 与 `idem_key` 字段：
                # `note` 那一层跨版本可用，字段那一层有表级唯一性断言。
                outcome = self.meter.charge_once(charge, idem_key=settle_key(res.task_id))
                if outcome["duplicate"]:
                    # `G-8`：这一支不许早退。
                    #
                    # 走到这里说明账上已经有这一笔 —— 典型现场是"账已落、
                    # `tasks` 还没写回就崩了"（或两个写者竞争，其中一个先落了账）。
                    # 早退会把下面的 `tokens_for()` 抄回与 `_set_usage()` 一起跳过，
                    # 于是 `tasks.tokens` 停在旧值（0）而账本是 1500：
                    # `verify_all` 报 `usage_task_total_mismatch`，
                    # `stats()['budget']` 也跟着与权威账分家 —— 同一件事两个数字。
                    #
                    # 修法是"落到同一条路径上"：`tokens_for()` 与 `_set_usage()`
                    # 读写的都是账本上的值（不是累加），所以重放是幂等的 ——
                    # "先 charge 再抄回"这条构造性等式因此在重放路径上也成立。
                    self._log(
                        f"重复记账（{res.task_id} 的账已存在）⇒ 不再落账，"
                        f"但仍把账上的值抄回 tasks（`G-8`）",
                        task_id=res.task_id,
                    )
            else:
                # 没有 `task_id` ⇒ 没有稳定的身份 ⇒ 构不成幂等键。
                # 如实退化成"每次都记"（与既有行为一致），不假装它幂等。
                self.meter.charge(charge)
            if res.task_id:
                # 从账本读回来写进 tasks ⇒ 两处按构造相等
                res.tokens = self.meter.tokens_for(res.task_id)
                res.usd = self.meter.usd_for(res.task_id)
        except Exception as e:  # noqa: BLE001 - 见 docstring：不许让记账问题翻转一次完成的召唤
            self._log(f"记账失败（{res.task_id}）：{type(e).__name__}: {e}",
                      task_id=res.task_id, tokens=spent)
            return res
        self.budget.spend(res.tokens, res.usd)   # 即时视图（唯一消费者：stats/观测）
        if res.task_id:
            self._set_usage(res.task_id, res.tokens, res.usd)
        return res

    def _set_usage(self, task_id: str, tokens: int, usd: float) -> None:
        """把账本上的花销写回 `tasks` 行，并打上"已结算"标记。

        为什么单独一个方法而不是在 `finish` 里写：一次召唤的花销只有跑完才知道，
        而 `finish` 在它之前就调了（终态必须先写下去 —— 中途崩溃时台账要能回答
        "它跑到哪一步了"）。所以这里是"终态已定，补上花销"的一步，它不是终态改写
        （`status`/`outcome`/`ended_at` 一个都不碰），`Task.validate` 允许。

        `_SETTLED_MARK` 写进 `inputs`：它是"这一行已经结过账"的可读证据，
        让重复结算变成可判定的事（见 `_charge_and_settle` 的说明）。
        用 `inputs` 而不是新开字段：它是审计用的"这次召唤读过什么"，
        加一个 `tokenmeter:settled` 元素不改变语义，也不需要动 schema（禁改区）。
        """
        with self.store.tx("tasks", actor="conductor", note="charge") as tx:
            row = tx.find("tasks", task_id=task_id)
            if row is None:  # pragma: no cover - finish 刚写过，走到这里说明表被清了
                raise ValueError(f"记账写回失败：{task_id} 不在 tasks 表里")
            row["tokens"] = int(tokens or 0)
            row["usd"] = float(usd or 0.0)
            inputs = [str(x) for x in (row.get("inputs") or [])]
            if _SETTLED_MARK not in inputs:
                row["inputs"] = inputs + [_SETTLED_MARK]
            S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
            tx.upsert("tasks", row, note="charge")
    # ---------------------------------------------------------------- 召唤
    def summon(
        self,
        role: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        by: str = S.CONDUCTOR_ROLE,
        parent_task_id: str | None = None,
        input_key: str = "",
        budget: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        lineage: Sequence[tuple[str, str, str]] | None = None,
    ) -> SummonResult:
        """唯一的召唤入口。见模块 docstring 的完整流程。

        参数
        ----
        lineage : 祖先链（含父自身）。`scheduler` 会带过来；直接调用时可省略，
            此时从 `tasks` 表按 `parent_task_id` 重建。两者必须一致：
            前者是纯调度（无 store）场景的表达，后者是正常运行时的权威来源。
        """
        params = dict(params or {})
        token = token or self.token
        t0 = time.monotonic()

        # ---- [0] 取消 / 销毁：不产生新任务
        #
        # 这一条与"拒绝也落台账"不冲突：拒绝是策略对一次召唤说的"不"
        # （那次召唤真的被提出过），而"取消之后不产生新任务"说的是
        # 不再有新的召唤发生。给被取消的召唤补一行台账，恰恰违反了它。
        # 返回 `task_id=None` 而不是编一个号：没有 start 就没有 end，
        # 编一个号会让调用方去查一条不存在的行。
        if token.cancelled:
            r = token.reason
            with self._lock:
                self._cancelled_total += 1
            return SummonResult(
                task_id=None, role=role, action=action, status="cancelled", outcome="cancelled",
                detail=f"未启动：{detail_of(r)}", elapsed_sec=time.monotonic() - t0,
            )
        if self._disposed:
            with self._lock:
                self._cancelled_total += 1
            return SummonResult(
                task_id=None, role=role, action=action, status="cancelled", outcome="cancelled",
                detail="未启动：Conductor 已 dispose（dispose 之后不再产生新任务）",
                elapsed_sec=time.monotonic() - t0,
            )

        # ---- [1] 角色 / 动作存在性（不落台账的只有"取消"这一种，见上）
        #
        # [1a] 不可召唤要**先于**动作表判（`draft/28` §154 的 R-44）。
        # 以前 `summon(role="M")` 拿到的是 `unknown_action`（"这个角色没这个动作"），
        # 而真相是"召唤主控这件事本身不允许"（`NON_SUMMONABLE`）。两者的处置相反：
        # 前者让人去查名字，后者要求改设计。专用判据 `policy.check` 一直是对的
        # （`G-11` 修的就是它的可达性），是这条入口把顺序放反了。
        if str(role) == S.CONDUCTOR_ROLE:
            return self._refuse(
                role, action, reason="forbidden_edge",
                detail=(f"{S.CONDUCTOR_ROLE} 不可被召唤（NON_SUMMONABLE）：主控就是派活方，"
                        "没有『召唤 M』这条边"),
                by=by, parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
            )
        edge = P.check_action(role, action)
        if edge is not None:
            return self._refuse(
                role, action, reason=edge.reason, detail=edge.detail, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
            )

        # ---- [2] 参数（结构问题在写 running 行之前判掉：跑一个注定炸的
        #          参数会让台账里多一条 failed，而它其实从来没被执行过）
        spec = C.find_action(role, action)
        assert spec is not None  # check_action 已经保证过
        bad = self._check_params(spec, params)
        if bad is not None:
            # 理由码是 `invalid_params` 而不是 `unknown_action`（R-46）：
            # "参数不合法"与"角色没这个动作"是两件事，前者要改参数，后者要查能力表。
            return self._refuse(
                role, action, reason="invalid_params", detail=bad, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
            )

        # ---- [3] 深度链
        try:
            depth, parent_role = self._depth_of(parent_task_id)
        except ValueError as e:
            # 父任务不存在 = 这次调用本身不成立（结构问题），同样落 `invalid_params`
            return self._refuse(
                role, action, reason="invalid_params", detail=str(e), by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
            )

        # ---- [4] 策略判定（边 / 深度 / 循环 / 扇出 / 并发 / 总量 / 预算 / 墙钟）
        chain = tuple(lineage) if lineage is not None else self._ancestry(parent_task_id)
        fanout = len(self._children_of(parent_task_id)) if parent_task_id else 0
        with self._lock:
            running = len(self._running)
            total = self._started_total + self._cancelled_total
        want_tokens = None
        want_usd = None
        if budget:
            if budget.get("max_tokens") is not None:
                want_tokens = int(budget["max_tokens"])
            if budget.get("max_usd") is not None:
                want_usd = float(budget["max_usd"])
        # ---- [4a] FC-19 预算守卫：在开工之前问一句"还允不允许"。
        #
        # 顺序是判据的一部分：`guard()` 必须在写 `running` 行之前跑。
        # "干完再拒"不是同一个功能 —— 它的后果是钱已经花掉了才说不该花，
        # 而且台账里会多一条 `failed`（看起来像执行出错，其实是策略拦截）。
        # 拒绝理由走现成的 `budget_exceeded`：拒绝是一次成功的执行
        # （框架正确地说"不"），不是失败。
        grant = self._meter_guard(role, budget)
        if not grant.allowed:
            return self._refuse(
                role, action, reason="budget_exceeded", detail=grant.reason, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
            )
        d = Decision(
            frm=by, to=role, action=action, depth=depth, fanout=fanout, running=running,
            total=total, ancestry=chain, key=(role, action, input_key),
            # 预算不再在这里判：`Decision.tokens_left/usd_left` 用的是
            # 本次 run 的即时视图，而权威账在 `usage_ledger`。
            # 同一件事两处判会漂移（一处说还能花、另一处说不能），
            # 所以预算只由上面那一次 `guard()` 判 —— 单一来源。
            deadline_hit=self.deadline_hit,
        )
        refusal = P.check(self.policy, d)
        if refusal is not None:
            # 墙钟到点：除了拒绝，还要协作式取消在跑的
            # （设计 §3.2："已在跑的协作式取消"）。
            if refusal.reason == "deadline_exceeded":
                self._signal_stop("deadline", refusal.detail, by="deadline")
            return self._refuse(
                role, action, reason=refusal.reason, detail=refusal.detail, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
            )

        # ---- [5] 写 running 行（带 started_at），然后放掉锁再去跑 handler
        #
        # 事务只包台账那一行，绝不包 handler。理由有两条，任一条都足够：
        # (a) handler 可能要跑几分钟（实验脚本、网络检索），持锁会让所有其它
        #     角色饿死 —— 那是"并发"变成"排队"的最隐蔽形态；
        # (b) handler 内部自己会 `store.tx(...)`，在锁内重入锁是死锁。
        #
        # 但取号与建行必须在同一个临界区里（见 `_write_new_row`）——
        # 那是本次实现里真实修掉的一个并发缺陷：分开做会让两个线程拿到同一个
        # `task_id`，后写的静默覆盖先写的。
        started = S.now_iso()
        row = {
            "task_id": "",
            "role": role, "action": action, "called_by": by,
            "parent_task_id": parent_task_id, "depth": depth, "input_key": input_key,
            "status": "running", "outcome": None, "refusal_reason": None,
            "detail": spec.summary, "error": None, "started_at": started, "ended_at": None,
            "tokens": 0, "usd": 0.0,
            "artifacts": [],
            "inputs": list(params["inputs"]) if isinstance(params.get("inputs"), list) else [],
        }
        tid = self._write_new_row(row, note=f"start:{role}.{action}")
        with self._lock:
            self._running.add(tid)
            self._started_total += 1
            self.peak_running = max(self.peak_running, len(self._running))
        self._log(f"召唤 {by} → {role}.{action}（{tid}, depth={depth}）")

        # ---- [6] 执行
        try:
            raw = self.backend.call(role, action, params, token=token)
            res = self._end_from_payload(tid, raw)
        except CancelRequested as e:
            res = self._end(tid, status="cancelled", outcome="cancelled",
                            detail=f"被协作式取消：{e.reason}")
        except NotWiredError as e:
            # 未接线不是失败：它是一次拒绝（框架正确地说了"这里还没接"）。
            res = self._end(tid, status="done", outcome="refused", refusal_reason="not_wired",
                            detail=str(e))
        except Exception as e:  # noqa: BLE001 —— 这里必须兜住一切，否则僵尸 running
            # ---- R-46：业务拒绝 ≠ 崩溃（`draft/28` §154）
            #
            # 角色代码**故意抛出**的领域错误（`ExperimentError` / `DocumentError` /
            # `PlanError` / `ReviewError` / `EvidenceError` / `ToolError`）表示
            # "这次调用不成立" —— 与 `refused` 同族；而 `TypeError` / `KeyError` /
            # `AttributeError` / `OSError` 这些是**代码或环境崩了**，必须留 `failed`。
            # 以前两者一律落 `failed / 执行中异常`：实测 4 条 `E.run_experiment`
            # （我把 `name`/`imports` 与 `method="numeric"` 一起传）就这么被记成"崩了"，
            # 而它其实是一次参数拒绝 —— 读台账的人会去查代码，而该改的是调用。
            #
            # 刻意**不**把裸 `ValueError` 算进拒绝：它既可能是校验（业务），
            # 也可能是判据自身的 bug；宁可把它留在 `failed`（过度报失败比把 bug
            # 伪装成"策略说不"安全）。
            code = _business_refusal_code(e)
            if code is not None:
                res = self._end(tid, status="done", outcome="refused", refusal_reason=code,
                                detail=f"{role}.{action} 拒绝了这次调用：{e}")
            else:
                res = self._end(tid, status="failed", outcome="failed",
                                error=f"{type(e).__name__}: {e}",
                                detail=f"{role}.{action} 执行中异常")
        finally:
            with self._lock:
                self._running.discard(tid)
        # ---- [7] 记账：权威账是 `usage_ledger`，`tasks.tokens/usd` 由它派生
        #
        # 为什么"先 charge、再把账本的值抄进 tasks"，而不是 `summon` 自己累加一遍：
        # `verify.verify_all` 的 `dangling_usage_task`（账本行挂不到任务行）与
        # `usage_task_total_mismatch`（`tasks.tokens` 与 `usage_ledger` 里该 task 的
        # 汇总不等，文案是"预算判断会按哪一份？"）两条检查都在这条链上 ——
        # 它们要的是同一件事：两处对同一次召唤的花销必须给出同一个数字。
        # 自己累加的那个相等只是"两处各算一遍但愿它们相等" —— 任何一条漏记
        # （一次重试、一个还没接线的 `_call`）都会让它静默不等。
        # 现在的写法让相等由构造保证。
        res = self._charge_and_settle(res, role=role)
        if res.tokens:
            # 共享取消信号也吃 token 预算：预算耗尽与取消走同一个信号，
            # 因为处置完全一样（停止派新任务 + 协作式取消在跑的）。
            self.token.consume_tokens(res.tokens)
        res.children = self._children_of(tid)
        res.elapsed_sec = time.monotonic() - t0
        return res

    # ---------------------------------------------------------------- 参数校验
    @staticmethod
    def _check_params(spec: C.ActionSpec, params: Mapping[str, Any]) -> str | None:
        """按 `ActionSpec.params` 校验。返回错误说明或 `None`。

        判据只有一份：`tools.base.validate_params`（与工具层同一套）。
        为什么不在 `summon` 里另写一遍校验：两套校验必然漂移，而漂移的形态是
        "主控放行了工具层会拒的参数"，那不会报错 —— 它会一路跑到 handler 里。
        """
        try:
            from .tools.base import validate_params

            validate_params(spec.params, dict(params))
        except Exception as e:  # noqa: BLE001 - ParamError 及子 schema 的错误都归为"这次没这么调"
            return f"{spec.role}.{spec.action} 的参数不合法：{e}"
        return None

    # ---------------------------------------------------------------- 结束态
    def _end_from_payload(self, tid: str, raw: Any) -> SummonResult:
        """把 handler 的返回值映射成终态。三态纪律在这里的落点。

        | handler 返回 | status | outcome |
        |---|---|---|
        | `None` | done | `no_result`（跑完了，确实没有） |
        | dict 带 `status/outcome` | 取它（角色自己更清楚） | 取它 |
        | 其它任何值 | done | `ok` |

        `None` 不许映射成 `ok`：那正是"把『没做』与『做了没结果』
        折叠成同一个值"—— 本项目在引文校验、OCR、D 溯源、C 预算截断四处
        踩过它，每一次的后果都是下游把"我们没查"读成了"查了没有"。
        """
        if raw is None:
            return self._end(tid, status="done", outcome="no_result",
                             detail="执行完成，本动作没有产出（no_result）")
        if isinstance(raw, Mapping):
            status = str(raw.get("status") or "done")
            # 角色返回的 status 只认终态词表；中间的 pending/running 在这里没有意义
            if status not in TERMINAL_STATUSES:
                status = "done"
            outcome = raw.get("outcome")
            detail = str(raw.get("detail") or raw.get("summary") or "")
            if status == "done" and outcome is None:
                # 一个返回了 dict 但没声明 outcome 的 handler：按有产出处理，
                # 但把这件事写进 detail（不许悄悄当成 ok）。
                outcome = "ok"
                detail = detail or "执行完成（handler 未声明 outcome，按有产出处理）"
            if outcome is not None and str(outcome) not in S.TASK_OUTCOMES:
                # ---- 两套词表不许折叠（实测缺陷，2026-09-29 验收 P1）
                #
                # 角色有自己的判定词表（F 的子目标判定是 `progress` / `no_change` /
                # `blocked` …），而这里要的是任务级结果词表
                # （`TASK_OUTCOMES = ok/no_result/not_applicable/refused/failed/cancelled`）。
                # 以前这里把角色的判定原样透传 ⇒ `Task.validate` 抛 `ValueError`
                # ⇒ 整步落 failed，而活其实已经干完了（事务已提交）。
                # 实测：20/20 条 `F.step` 台账是 `failed`，而 14 条检索请求已经提交、
                # 11 条以 ok 收尾 —— 台账说"失败"，实际成功。这直接毁掉 P10 的
                # "台账能重建 M 的决策序列"。
                #
                # 处置：任务级结果按"执行完成"记 `ok`，角色的判定原样留在 detail 里
                # （可见，不是静默丢弃 —— 静默丢弃是本项目最忌的形态）。
                detail = f"[handler_outcome={outcome}] {detail}".strip()
                outcome = "ok"
            if status == "failed":
                outcome = "failed"
            if status == "cancelled":
                outcome = outcome if outcome in ("cancelled", "refused") else "cancelled"
            return self._end(
                tid, status=status, outcome=str(outcome) if outcome else None,
                detail=detail or "执行完成",
                error=str(raw["error"]) if raw.get("error") else None,
                # 角色拒绝时它的理由必须能传到行上：`Task.validate` 逐字要求
                # `outcome=refused` 带受控的 `refusal_reason`，而这里此前没透传它
                # ⇒ 角色一拒绝就落 `failed`（"策略说不"被记成"代码崩了"）。
                # 实测（2026-09-29）：这正是 `test_refused_outcome_is_not_rewritten` 咬出来的。
                refusal_reason=str(raw["refusal_reason"]) if raw.get("refusal_reason") else None,
                payload=raw.get("payload", raw.get("data", raw)),
                artifacts=list(raw.get("artifacts") or []),
                checked=raw.get("checked", None),
                tokens=int(raw.get("tokens") or 0),
                usd=float(raw.get("usd") or 0.0),
            )
        return self._end(tid, status="done", outcome="ok", detail="执行完成", payload=raw)

    def _end(
        self,
        task_id: str,
        *,
        status: str,
        outcome: str | None,
        detail: str = "",
        error: str | None = None,
        refusal_reason: str | None = None,
        payload: Any = None,
        artifacts: Sequence[str] = (),
        checked: bool | None = None,
        tokens: int = 0,
        usd: float = 0.0,
    ) -> SummonResult:
        """写终态。幂等：见 :meth:`finish`。"""
        return self.finish(
            task_id, status=status, outcome=outcome, detail=detail, error=error,
            refusal_reason=refusal_reason, payload=payload, artifacts=list(artifacts),
            checked=checked, tokens=tokens, usd=usd,
        )

    # ---------------------------------------------------------------- finish
    def _write_task_digest(self, row: Mapping[str, Any], *, payload: Any, status: str,
                           outcome: str | None, detail: str) -> str:
        """把一次召唤的返回值摘要写成 `<workspace>/out/tasks/<task_id>.json`；返回相对路径。

        `payload is None` ⇒ 返回空串（没产出就不写文件，免得留下"看起来有产出"的空壳）。
        写失败**不**影响终态：原因记进日志并返回空串 —— "有产出但摘要没写成"
        与"没有产出"必须分得开，而终态那一行不能因为日志写不了就丢掉。
        """
        if payload is None:
            return ""
        task_id = str(row.get("task_id") or "")
        if not task_id:
            return ""
        root = Path(getattr(self.store, "root", ".") or ".")
        rel = f"out/tasks/{task_id}.json"
        try:
            blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            doc = {
                "task_id": task_id,
                "role": str(row.get("role") or ""),
                "action": str(row.get("action") or ""),
                "status": status,
                "outcome": outcome,
                "detail": detail,
                "at": S.now_iso(),
                "payload_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                "payload_bytes": len(blob.encode("utf-8")),
                # 键集是"这一步产出了什么形状的东西"的最小可读证据；
                # 预览截断到 2 KB，避免把大对象整份塞进产物。
                "payload_keys": sorted(str(k) for k in payload) if isinstance(payload, Mapping) else [],
                "payload_preview": blob[:2000],
            }
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                              encoding="utf-8")
        except (OSError, TypeError, ValueError) as e:  # noqa: BLE001 - 见 docstring
            self._log(f"任务产出摘要没写成：{type(e).__name__}: {e}", task_id=task_id)
            return ""
        return rel

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        outcome: str | None,
        detail: str = "",
        error: str | None = None,
        refusal_reason: str | None = None,
        payload: Any = None,
        artifacts: Sequence[str] = (),
        checked: bool | None = None,
        tokens: int = 0,
        usd: float = 0.0,
    ) -> SummonResult:
        """把任务写成终态。幂等：对已结束的任务再调 ⇒ 零变更（逐字节）。

        实现上不看内存状态，而是在事务里重读那一行：
        只有当前 `status in ("pending","running")` 才写。
        为什么不信内存：`finish` 的调用方可能有多个（worker 正常返回、
        dispose 的兜底、deadline 的取消），它们并发跑在不同的线程里；
        靠一个内存标志去串行化，等于把正确性押在"锁的粒度刚好够"上。
        重读磁盘的代价是一次文件读，收益是"终态先到先得"变成结构事实。

        `status` 与 `outcome` 的合法性由 `schema.Task.validate` 保证
        （例如 `outcome=refused` 时 status 必须是 done、cancelled 时 outcome
        只能是 cancelled/refused）—— 本方法不替它兜底，非法就抛。
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(
                f"finish 只接受终态 {TERMINAL_STATUSES}，收到 {status!r}。"
                "中间态由 summon 在开始时写（那时才有 started_at）"
            )
        ended = S.now_iso()
        with self.store.tx("tasks", actor="conductor", note=f"finish:{status}") as tx:
            row = tx.find("tasks", task_id=task_id)
            if row is None:
                raise ValueError(f"finish 的任务 {task_id!r} 不在 tasks 表里（没有 start 就没有 end）")
            if row.get("status") in TERMINAL_STATUSES:
                # ---- 幂等分支：什么都不做（连事件都不追加）
                existing = dict(row)
                return SummonResult(
                    task_id=task_id, role=str(existing.get("role") or ""),
                    action=str(existing.get("action") or ""),
                    status=str(existing.get("status")), outcome=existing.get("outcome"),
                    refusal_reason=existing.get("refusal_reason"),
                    detail=str(existing.get("detail") or ""), error=existing.get("error"),
                    artifacts=list(existing.get("artifacts") or []),
                    tokens=int(existing.get("tokens") or 0), usd=float(existing.get("usd") or 0.0),
                    depth=int(existing.get("depth") or 1),
                )
            if not row.get("started_at"):
                row["started_at"] = ended
            row["status"] = status
            row["outcome"] = outcome
            row["refusal_reason"] = refusal_reason if outcome == "refused" else None
            row["detail"] = detail
            row["error"] = error
            row["ended_at"] = ended
            row["tokens"] = int(tokens or 0)
            row["usd"] = float(usd or 0.0)
            # ---- R-47：把这次调用的返回值摘要落成产物，并把路径记进 `artifacts`。
            # 为什么必须落：`tasks` 表不存 payload ⇒ `outcome=ok` **无法自证有产出**
            # （实测 83 行 detail 是"handler 未声明 outcome，按有产出处理"，
            # 读台账的人判不出这一步到底产出了什么，见 `draft/28` §154 的 S3/R-47）。
            # 摘要落 `<workspace>/out/tasks/<task_id>.json`（键集 + 规范化哈希 + 截断预览），
            # 表里只多一个 artifacts 引用 —— `tasks` 表结构不动（它在 FC-27 禁改区）。
            digest_rel = self._write_task_digest(row, payload=payload, status=status,
                                                 outcome=str(outcome) if outcome else None,
                                                 detail=detail)
            if digest_rel:
                artifacts = list(artifacts) + [digest_rel]
            if artifacts:
                # 合并而不是覆盖：`artifacts` 是 append-only 的产出引用。
                # 覆盖会让"分两次登记产出"的第二次抹掉第一次。
                merged = list(row.get("artifacts") or []) + [a for a in artifacts if a]
                row["artifacts"] = S.sorted_unique(merged)
            S.Task(**{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}).validate()
            tx.upsert("tasks", row, note=f"finish:{status}")
        # ---- 会话记录（按项目存放）：一次终态 = 一条叙事行（`agentflow.sessions`）。
        #
        # 为什么在这里写：`tasks` 是运行时状态，而"这次运行的叙事"（谁在何时对谁说了什么、
        # 产出了什么）以前只活在会话里。落进 `<项目根>/sessions/<会话号>.jsonl` 之后，
        # 每个项目自带一段可读历史，翻 p2-review 不必读全局目录（学 harness 的按工作区存放）。
        # 写失败**不**改变终态：叙事不是判据本身，原因进日志。
        from . import sessions as _SESS

        _path, _problem = _SESS.append(getattr(self.store, "root", "."), {
            "kind": "task_end",
            "task_id": task_id,
            "by": str(row.get("called_by") or ""),
            "role": str(row.get("role") or ""),
            "action": str(row.get("action") or ""),
            "status": status,
            "outcome": outcome,
            "refusal_reason": row.get("refusal_reason"),
            "detail": detail[:200],
            "artifacts": list(row.get("artifacts") or []),
        })
        if _problem:
            self._log(f"会话记录没写成：{_problem}", task_id=task_id)
        return SummonResult(
            task_id=task_id, role=str(row.get("role") or ""), action=str(row.get("action") or ""),
            status=status, outcome=outcome, refusal_reason=row.get("refusal_reason"),
            detail=detail, error=error, payload=payload, artifacts=list(row.get("artifacts") or []),
            tokens=int(tokens or 0), usd=float(usd or 0.0),
            depth=int(row.get("depth") or 1), checked=checked,
        )

    # ---------------------------------------------------------------- 计划
    def run_plan(self, plan: Sequence[TaskCall], *, token: CancelToken | None = None) -> list[SummonResult]:
        """把一串 call 交给 `scheduler.run_waves`。

        返回列表长度恒等于 `len(plan)` 且顺序与 plan 一致（I-10）。
        并发度不改变结果顺序 —— 这是"可复现"的判据本身。
        """
        from . import scheduler as SC

        token = token or self.token
        P.assert_policy_complete(self.policy)
        self._log(f"run_plan：{len(plan)} 个召唤，policy={self.policy.to_dict()}")
        return SC.run_waves(plan, conductor=self, policy=self.policy, token=token)

    # ---------------------------------------------------------------- 停止
    def _signal_stop(self, code: str, detail: str, *, by: str) -> str:
        """喊一次停：设置共享 token，并记下第一次的说明。

        为什么记"第一次"：FC-20 第 2 条（终态先到先得）。后来者不能改写
        "为什么停的" —— 两个答案等于没有答案。`CancelToken.cancel` 自身
        已经是 first-wins，这里再记一份是为了让 dispose 能拿到它写进
        `detail`（token 的 reason 是受控对象，而台账要的是人话）。
        """
        if code not in CANCEL_CODES:
            raise ValueError(f"未知取消原因 {code!r}（受控词表 {CANCEL_CODES}）")
        r = self.token.cancel(code, detail=detail, by=by)
        with self._lock:
            if self._cancel_detail is None:
                self._cancel_detail = detail or detail_of(r)
            return self._cancel_detail

    def cancel(self, reason: str = "user", *, detail: str = "", by: str = "user") -> dict:
        """一个共享 signal 覆盖所有在飞与待启动的任务（FC-20 第 1 条）。

        不逐个取消 —— 逐个会漏。返回此刻的在飞任务列表（供调用方观察，
        但不需要拿它去做什么：取消是协作式的，任务自己会读到同一个 token）。
        """
        text = self._signal_stop(reason, detail, by=by)
        with self._lock:
            inflight = sorted(self._running)
        self._log(f"取消：{text}", inflight=inflight)
        return {"reason": reason, "detail": text, "inflight": inflight}

    def cancel_inflight(self) -> list[str]:
        """给当前在飞任务合成的取消说明的便捷入口（dispose 用）。

        它不逐个写终态：在飞任务的 worker 会在自己的 `except CancelRequested`
        里写下终态（那是"每个 start 恰好一个 end"的正常路径）。
        `dispose()` 只处理没人再管的那些（进程要走了）。
        """
        with self._lock:
            return sorted(self._running)

    # ---------------------------------------------------------------- dispose
    def dispose(self) -> dict:
        """幂等销毁：把仍在 `pending`/`running` 的任务合成 end 事件（`cancelled`）。

        三条纪律全在这里落地：

        - 每个 start 有且仅有一个 end：即使是被强杀的任务，也必须合成一个
          `cancelled` 的 end（否则台账里会有永远"在跑"的僵尸）。
        - 结果未知：`detail` 必须写明"因 dispose 而终止，结果未知"。
          一个被中途砍掉的实验可能已经写了半张表，声称它"失败"是过度声称
          （设计 §4 第 4 条）。
        - 不自动重试：本方法只是写终态，不做任何重发。

        幂等：第二次调用时已经没有任何 `pending/running` 的行（第一次全写完了），
        于是返回 `{"disposed": ..., "closed": []}` —— 且零字节变更
        （`finish` 的幂等分支连事件都不追加）。
        """
        first = not self._disposed
        self._disposed = True
        text = self._signal_stop("dispose", "因 dispose 而终止，结果未知", by="conductor.dispose")
        closed: list[str] = []
        for row in self._tasks():
            if row.get("status") in ("pending", "running"):
                tid = str(row["task_id"])
                self.finish(
                    tid, status="cancelled", outcome="cancelled",
                    detail=f"{text}（dispose 时该任务仍在 {row.get('status')}，结果未知）",
                )
                closed.append(tid)
        # 在飞集合由 worker 的 `finally` 清空；dispose 不替它们清 ——
        # 清了会让一个仍在跑的 worker 在自己写终态时找不到那一行吗？不会：
        # 它写的是磁盘上的行，而这里已经把它写成终态，于是 `finish` 走幂等分支。
        with self._lock:
            still = sorted(self._running)
        self._log(f"dispose：关闭 {len(closed)} 个未完成任务", closed=closed)
        return {"disposed_was_first": first, "closed": closed, "still_running": still}

    # ---------------------------------------------------------------- 可读视图
    def tree(self, root_task_id: str | None = None) -> list[dict]:
        """父子链视图（从 `tasks` 表读出来，不碰内存状态）。

        为什么从表读：跨会话恢复之后内存里什么都没有，而表才是权威。
        返回的是扁平的行列表（每行带 `children`），而不是嵌套结构 ——
        台账天然是扁平的，"嵌套"只是展示层的事，库不应该替展示层做决定。
        """
        rows = self._tasks()
        by_parent: dict[str | None, list[dict]] = {}
        for r in rows:
            by_parent.setdefault(r.get("parent_task_id"), []).append(r)
        out: list[dict] = []

        def walk(tid: str | None, level: int) -> None:
            for r in sorted(by_parent.get(tid, []), key=lambda x: str(x.get("task_id"))):
                kids = by_parent.get(r.get("task_id"), [])
                out.append({
                    "task_id": r.get("task_id"), "role": r.get("role"), "action": r.get("action"),
                    "status": r.get("status"), "outcome": r.get("outcome"),
                    "depth": r.get("depth"), "level": level,
                    "called_by": r.get("called_by"), "parent_task_id": r.get("parent_task_id"),
                    "children": [k.get("task_id") for k in kids],
                    "detail": r.get("detail"),
                })
                walk(r.get("task_id"), level + 1)

        if root_task_id is not None:
            root = self._task(root_task_id)
            if root is None:
                raise ValueError(f"tree(root_task_id={root_task_id!r})：台账里没有这个任务")
            # 从 root 自己开始（而不是它的子树）—— "这棵树的根"包含根。
            out.append({
                "task_id": root.get("task_id"), "role": root.get("role"), "action": root.get("action"),
                "status": root.get("status"), "outcome": root.get("outcome"),
                "depth": root.get("depth"), "level": 0, "called_by": root.get("called_by"),
                "parent_task_id": root.get("parent_task_id"),
                "children": [k.get("task_id") for k in by_parent.get(root_task_id, [])],
                "detail": root.get("detail"),
            })
            walk(root_task_id, 1)
        else:
            walk(None, 0)
        return out

    def stats(self) -> dict:
        """台账的可读统计。每一项都从表里数出来，不缓存。

        为什么 `unknown_outcome` 单列：它不是"失败"，是"我们不知道"
        （例：dispose 的取消）。把它并进 `cancelled` 的计数里，
        "有几件事我们其实不知道结果"这个数字就永远看不见了。
        """
        rows = self._tasks()
        # 视图与权威账对账（以账为准）：`stats()` 是唯一读这个视图的地方，
        # 每次问都先对齐 —— 这样"本次 run 花了多少"不会因为某条路径漏推视图
        # 而与台账给出不同的数字。
        #
        # `G-8`：对账的来源必须是权威账（`usage_ledger`），不是 `tasks` 求和。
        # `tasks.tokens/usd` 是派生列，而"派生"不等于"随时同步"：
        # 崩溃窗口（账已落、写回没做）里它停在旧值 —— 拿它去 reconcile
        # 等于"把视图对齐到另一份可能过期的派生数据"，而
        # `MemoryBudgetTracker` 的契约逐字是"以账为准"（见它的 docstring
        # 与 `reconcile()` 的说明）。`TokenMeter.spent()` 每次都从
        # `usage_ledger` 现读，是账本口径的唯一读取口。
        ledger = self.meter.spent()
        self.budget.reconcile(tokens=int(ledger["tokens"]),
                              usd=round(float(ledger["usd"]), 6))
        by_role: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_depth: dict[str, int] = {}
        refused_reasons: dict[str, int] = {}
        for r in rows:
            by_role[str(r.get("role"))] = by_role.get(str(r.get("role")), 0) + 1
            by_status[str(r.get("status"))] = by_status.get(str(r.get("status")), 0) + 1
            oc = r.get("outcome")
            key = str(oc) if oc is not None else "<未结束>"
            by_outcome[key] = by_outcome.get(key, 0) + 1
            by_depth[str(r.get("depth"))] = by_depth.get(str(r.get("depth")), 0) + 1
            if r.get("refusal_reason"):
                rr = str(r["refusal_reason"])
                refused_reasons[rr] = refused_reasons.get(rr, 0) + 1
        unknown = sum(
            1 for r in rows
            if r.get("status") == "cancelled" and "结果未知" in str(r.get("detail") or "")
        )
        return {
            "total": len(rows),
            "by_role": by_role,
            "by_status": by_status,
            "by_outcome": by_outcome,
            "by_depth": by_depth,
            "refusal_reasons": refused_reasons,
            "unknown_outcome": unknown,
            "peak_running": self.peak_running,
            "started_total": self._started_total,
            "budget": self.budget.state(self.policy),
            "policy": self.policy.to_dict(),
            "disposed": self._disposed,
            "deadline_hit": self.deadline_hit,
        }

    # ---------------------------------------------------------------- 自检
    def task_issues(self) -> list[C.TaskIssue]:
        """台账问题的结构化视图（带机器可读的码）。

        判据只有一份：`capabilities.audit_task_ledger`。为什么收在那里 ——
        `verify_all`（全库离线审计）与 `verify_tasks`（刚跑完一次 run 的即时自检）
        问的是同一个问题，两处各写一份判据必然漂移，而漂移的形态是
        "其中一处永远说没问题"。`tests/test_conductor.py::test_task_ledger_audit_matches_verify_all`
        钉住两者的码集合相等（`DEVELOPMENT.md` §10 点名的那条）。
        """
        with self._lock:
            in_flight = frozenset(self._running)
        return C.audit_task_ledger(self._tasks(), store=self.store, in_flight=in_flight)

    def verify_tasks(self) -> list[str]:
        """本模块的不变式自检：返回人可读的问题说明列表（空 = 自洽）。

        与 `verify.py` 的分工：`verify_all` 是全库审计、由 CLI 跑；
        这里回答"我刚跑完一次 run，台账是否自洽"，不需要跑全库。
        判据不在这里 —— 它来自 `capabilities.audit_task_ledger`（唯一实现，
        见 :meth:`task_issues`）。

        任何一条不成立就返回说明列表（不抛）：调用方决定要不要当成失败
        （"拒绝 ≠ 失败"的同一条纪律：把"台账有可疑行"变成异常，会逼调用方
        用 try/except 包住它，而 try/except 会连真正的编程错误一起吞掉）。
        """
        return [
            # 码在前、行号在后：`verify.Issue` 也是这个形态，便于机器比对与人工定位
            f"{i.task_id}: [{i.code}] {i.message}" for i in self.task_issues()
        ]
