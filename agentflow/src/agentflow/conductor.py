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

import contextvars
import hashlib
import inspect
import itertools
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
from .agentspec import AgentBrief, AgentSpec

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

#: 标记"这一行是受理过的召唤"（写进 `tasks.inputs`，与 `running` 行同一个事务写下）。
#:
#: 为什么需要它（题 21 选 B，2026-10-07 所有者裁定）：扇出口径是"受理数，不是尝试数"
#: （题 15 选 B），而区分"闸门拒掉、根本没跑"与"跑过又拒"的那条判据，上一轮的最小
#: 修法挂在了 `_SETTLED_MARK` 上 —— 那是 `_charge_and_settle` 末尾 `_set_usage`
#: 写的东西，属于"事后的记账写回"。它能炸：`_charge_and_settle` 刻意兜住记账异常
#: （钱已经花了、活已经干完了，不许让它翻转一次完成的召唤），兜住之后这一行就缺
#: `tokenmeter:settled` ⇒ 被 `_occupies_fanout_slot` 当成"没跑" ⇒ 扇出少算 1。
#: 那个少算的方向是危险的：名额被少占，扇出上限就被悄悄放宽。
#:
#: 所以标记必须打在"受理那一刻"、且与 `running` 行同一笔事务落盘：只有走过
#: `summon` 第 [5] 步（"写 running 行"）的召唤才带它 —— 闸门拒绝在写 running 行
#: 之前就 `_refuse` 返回了（`_refuse` 的行 `inputs=[]`，连调用方给的输入都不带），
#: 它拿不到这个标记。此后无论角色自己拒、记账写回炸、还是进程崩，标记都已经在盘上。
#:
#: 为什么落在 `inputs` 而不是给 `schema.Task` 加字段：与 `_SETTLED_MARK` 同一条理由
#: （见 `_set_usage` 的说明）—— `inputs` 是既有的 `set` 类数组字段，加一个元素不改变
#: 语义（它记的是"这次召唤与哪些东西打过交道"，受理标记正是其中之一），
#: 也不需要动 `schema.py`（禁改区）。老行（这一版之前落盘的）没有这个元素，
#: `_occupies_fanout_slot` 对它们退回读 `_SETTLED_MARK` —— 历史读数因此不变
#: （见那个函数）。
_ADMITTED_MARK = "conductor:admitted"


def _admitted_inputs(params: Mapping[str, Any]) -> list[str]:
    """`tasks.inputs` 的初值：调用方给的输入清单 + 受理标记。

    受理标记必须与 `running` 行一起、在同一笔事务里写下去（调用点在 `summon` 第 [5] 步
    的 row dict 里）—— 写在之后（无论写在哪一段收尾代码里）都会重新长出"收尾失败
    ⇒ 标记丢失"这个缺陷。这里顺带按值去重：`inputs` 是 `set` 类字段，
    重复元素是坏数据，而调用方可以自己传一个同名元素进来。
    """
    raw = params.get("inputs")
    items: list[Any] = list(raw) if isinstance(raw, list) else []
    if not any(str(x) == _ADMITTED_MARK for x in items):
        items.append(_ADMITTED_MARK)
    return items


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

    #: 声明注册表（`None` ⇒ 读内置那份）。类级默认值：子类若自己写 `__init__`
    #: 而没调 `super().__init__()`，仍然拿得到"用内置表"这个默认行为 ——
    #: 实测于 `tests/test_r5_orchestration_cost.py::_ProbeBackend`（三条取消语义用例）。
    _specs: Any = None

    def __init__(self, registry: Mapping[str, Any] | None = None,
                 specs: Any = None) -> None:
        self._specs = specs
        self.registry: dict[str, Any] = dict(registry or {})
        #: 缓存键是 `(角色, 实例标签)`：空标签 = 那个单例（默认行为逐字不变）；
        #: 显式标签 ⇒ 每个实例一个对象（"N 个 B 一起干活"要的是 N 个对象，
        #: 不是一个对象被 N 个线程共用）。
        self._instances: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def known_roles(self) -> list[str]:
        return sorted(self.registry)

    def resolve(self, role: str, instance: str = "") -> Any:
        """把注册项变成实例（惰性，按 `(角色, 实例)` 缓存）。

        - 传 `("factory", fn)`：按签名决定给不给 `store=` / `instance=`
          （见下面那段注释：靠 `try/except TypeError` 会把工厂内部的真错吞掉）；
        - 传 `("object", obj)`：直接用（显式实例标签下同一个对象会被复用 ——
          那是调用方自己选择"共享一个实例"，框架不替它分家）；
        - 传 `("class", cls)`：明确拒绝 —— 构造依赖无法自动满足，
          假装能建就是"猜依赖"（见类 docstring）。
        """
        key = (role, str(instance or ""))
        with self._lock:
            if key in self._instances:
                return self._instances[key]
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
            # 用签名决定怎么调，而不是 `try/except TypeError`（2026-09-30 修的坑）：
            # 旧写法把"工厂内部抛的 TypeError"也当成"它不接受这个参数"，
            # 于是真正的错（实测：`agent_b` 构造 LLM 抽取器时 client 不合规）
            # 被吞掉，最后抛出一句误导性的"需要一个 store" —— 那正是本项目
            # 最忌讳的形态（把没说清的说成说清了，而且指着错的地方）。
            try:
                params = inspect.signature(value).parameters
            except (TypeError, ValueError):
                params = {}
            takes_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
            kwargs: dict[str, Any] = {}
            if takes_kw or "store" in params:
                kwargs["store"] = self.store
            if takes_kw or "instance" in params:
                kwargs["instance"] = key[1]
            inst = value(**kwargs) if kwargs else value()
        else:
            inst = value
        with self._lock:
            self._instances[key] = inst
        return inst

    #: 由 `Conductor` 注入（不放进构造签名，是为了让 backend 可以被单测直接建）。
    store: Any = None

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken,
             instance: str = "", task_id: str = "") -> Any:
        """调一次 handler。

        参数名对不上就拒绝，不许静默丢弃。工具的 `ToolRegistry.call`
        是按 schema 校验后再调；这里的 handler 是角色的真实方法，
        它的形参名就是它与调用方的契约。把多出来的参数丢掉会让
        "我传了 `submit_requests=True` 但它被忽略了"看起来像一次成功 ——
        于是 `gaps()` 报告里说"已提交"，而请求一条也没有。

        ## `G-1`：token 不再"收下就扔"

        旧版末行是 `return fn(given)` —— `token` 收了，然后一个字都没往下传，
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
        spec = C.find_action(role, action, registry=self._specs)
        if spec is None:  # pragma: no cover - summon 已经查过，这里是纵深防御
            raise NotWiredError(f"{role} 没有动作 {action}")
        obj = self.resolve(role, instance)
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
        # `R1-A1-a`：召唤号与取消令牌同构（同一个临界区、同一个 finally 复位）——
        # 角色的 handler 通过 `current_task_id()` 读它，于是"这一趟召唤花了多少"
        # 有了以 `task_id` 为键的挂点（P-09 的粒度是召唤级）。
        id_var = _CURRENT_TASK_ID
        id_reset = id_var.set(str(task_id or ""))
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
            id_var.reset(id_reset)          # 异常路径也要复位（与 token 同一处）


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

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: CancelToken,
             instance: str = "", task_id: str = "") -> Any:
        """后端未接线：一律拒绝（`not_wired` 是一等状态，不是失败）。

        `instance` / `task_id` 收下但不使用（本层没有角色可建，谈实例没有意义）；
        形参必须与 `LocalBackend.call` 逐字同形 —— 两个后端共用一个契约。
        """
        raise NotWiredError(f"{role}.{action} 未接线：{self.reason}")


class NotWiredError(RuntimeError):
    """动作没有接线。不是失败 —— 对应 `refused/not_wired`（见 §2.2 的表）。"""


# ---------------------------------------------------------------- 主控


#: 角色代码故意抛出的领域错误类名 → 它们在任务台账里算"拒绝这次调用"（R-46）。
#:
#: 为什么按类名匹配而不是 import 那些类：conductor 在 import 图上位于 agent_* 之上
#: （agent 模块会 import conductor 的类型），直接 import 会成环。类名匹配的代价是
#: "改了类名这里就失效" —— 所以下面 `selftest`/用例要有一条正控真的抛一次
#: `ExperimentError` 并断言落 `refused/invalid_params`（判据不许只活在注释里）。
_BUSINESS_ERROR_NAMES = frozenset({
    "ExperimentError", "DocumentError", "PlanError", "ReviewError",
    "EvidenceError", "ConjectureError", "ToolError",
})


def _closure_suffix(reading: Mapping[str, Any]) -> str:
    """把职责 3 的收尾读数压成顶趟行 `detail` 里的一句话（谁没接手 / 谁没反馈 / 各几条）。

    三种情形分开写（三态纪律）：没查成（`checked=False`）不许写成"没有未闭环"，
    也不写成空串 —— 收尾行的读者要能从这一句里看出"这一格今天我到底查没查"。
    没有未闭环时给一句明确的"0 条"，而不是留空（留空会被读成"没查"）。
    """
    if not reading:
        return "；闭环提醒：没查（收尾读数缺）"
    if not reading.get("checked"):
        return f"；闭环提醒没查成（{str(reading.get('reason') or '')[:60]}）"
    count = int(reading.get("count") or 0)
    if count == 0:
        return "；闭环提醒：0 条未闭环"
    parts = "、".join(f"{k} {v} 条" for k, v in sorted((reading.get("by_state") or {}).items()))
    return f"；闭环提醒 {count} 条（{parts}；unclaimed=没人接手，pending/running=没有终态）"


#: "当前召唤号"（`R1-A1-a`）：与取消令牌（`cancellation._CURRENT_TOKEN`）同构 ——
#: 同一个临界区、同一个 `try/finally`、按执行上下文传。
#:
#: ## 为什么不能挂实例属性（`R1-A1` 的 P-09 挂点）

#: `LocalBackend.resolve(role)` 按角色缓存实例：两个并发召唤会共享同一个对象 ⇒
#: 把号挂在实例上，A 的号会盖掉 B 的（读出来的成本挂到别人的单子上）。
#: `conductor.py` 里那段给取消令牌写的理由逐字适用，所以这里用 ContextVar：
#: 号跟着这一次调用走，调用结束就复位。
_CURRENT_TASK_ID: contextvars.ContextVar[str] = contextvars.ContextVar("agentflow_task_id",
                                                                     default="")


def current_task_id() -> str:
    """这一趟召唤的号（不在任何召唤里 ⇒ 空串）。

    空串 = 没有挂点，不是"零号"：调用方（例如 `agent_d`）拿它去读 `usd_reading`
    时必须把"没号"与"挂上了但没记账"分开 —— 折成一个 0 正是本仓最贵的那个缺陷形态。
    """
    return _CURRENT_TASK_ID.get()


def _business_refusal_code(exc: BaseException) -> str | None:
    """这次异常算不算"角色拒绝了这次调用"？算就返回受控理由码，否则 `None`。

    两条来源，优先级从高到低：
    1. 异常自带 `refusal_reason`（显式协议，且必须是受控词表里的值）；
    2. 异常是上表里的领域错误类（角色故意抛的）。
    其余一律 `None` ⇒ 由调用方记 `failed`（"代码/环境崩了"）。
    """
    code = getattr(exc, "refusal_reason", None)
    if isinstance(code, str) and code in S.REFUSAL_REASONS:
        return code
    if type(exc).__name__ in _BUSINESS_ERROR_NAMES:
        return "invalid_params"
    return None


def _occupies_fanout_slot(row: Mapping[str, Any]) -> bool:
    """这条子行占不占父任务的扇出名额（题15 选B，2026-10-07）。

    ## 口径：扇出 = 受理数，不是尝试数

    闸门拒掉的召唤也落台账（`_refuse`：谁试过什么必须留痕），但它根本没跑，
    所以不占名额。若它占名额，父任务一旦触顶就再也派不出活，而每次尝试还会
    再占一格 —— 自我毒化、不可恢复。真机读数（工作区
    `agentflow/projects/p9-post-merge-probe` 的台账，2026-10-07）：顶趟行
    `t-0001` 名下 10 个子行，末 5 条（`t-0007`…`t-0011`）全是
    `refused/fanout_exceeded`，detail 里的读数从"已派生 5 个"一路涨到"已派生 9 个"
    （那就是自我毒化的机器形态）；本趟主控只成功派了 3 件活（A 检索 / D 立题 /
    D 登记猜想），E 的实验永远进不去 ⇒ `experiments=0`、收工门两格红。

    ## 判据为什么是"受理标记"而不是"拒绝理由"，也不是"结算标记"

    拒绝理由是受控词表（`schema.REFUSAL_REASONS`），闸门与角色共用它：角色
    跑完之后自己拒绝也落 `invalid_params`（真机 `t-0006` 就是这一档，
    `_business_refusal_code` 把领域错误映到这个词上）。按理由过滤会把
    "跑过又拒了"误判成"没跑"。区分二者的是这条事实：只有走完第 [5] 步
    （写 `running` 行）的召唤才带 `_ADMITTED_MARK`，而闸门拒绝在写 running 行
    之前就返回了。所以：

    - `outcome == "refused"` 且行上没有受理标记 ⇒ 闸门拒掉、根本没跑 ⇒ 不占名额；
    - 其余一切（`running` / `ok` / `failed` / `cancelled`、以及跑过又拒的）
      ⇒ 占名额。"跑了但失败"确实消耗了一次派活，必须仍然计入（有负控咬着：
      `tests/test_fanout_admission.py::test_ran_and_failed_child_still_counts`）。

    为什么不继续用 `_SETTLED_MARK`（题 21 选 B 改的就是这一处）：那是"事后"的
    记账写回打的标记，而记账能炸、炸了之后那一行就缺标记 ⇒ "跑了又拒"被当成
    "没跑" ⇒ 扇出少算（名额被少占，上限被悄悄放宽）。受理标记在受理那一刻
    就落盘，与后续收尾的成败无关。判据见
    `tests/test_fanout_admission.py::test_a_failed_charge_writeback_still_occupies_the_slot`。

    老行（本题之前落盘的）没有受理标记：它们退回读 `_SETTLED_MARK` ——
    历史台账里"跑过又拒"的行仍然算占名额，读数与这一版之前一致。
    """
    if row.get("outcome") != "refused":
        return True
    marks = {str(x) for x in (row.get("inputs") or [])}
    return _ADMITTED_MARK in marks or _SETTLED_MARK in marks


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
        specs: Any = None,
        secretary: Any = None,
    ) -> None:
        """`secretary`（A 线）：M 的派活路径上那一个钩子（`draft/54 §2` 的第 3 个落点）。

        它是可选对象（`None` = 没装配）：给了就"同 key 的既有终态行摆出来 + 一份
        委派评估建议"，不给也照样派活 —— 秘书的失败姿态是 fail-open，
        而"没装配"与"装配了但没判断"在读数上是两件事（前者连台账都没有）。
        """
        self.store = store
        self.policy = policy or P.Policy()
        #: 角色声明的注册表（`goal-7f5116c1` M5）：给了就从它读"有哪些角色、
        #: 每个角色有哪些动作、谁能召唤谁"；`None` ⇒ 读内置那份（今天的行为逐字不变）。
        #: 存在的理由：新增一个角色时，闸门不该只认源码里写死的那张表。
        self.specs = specs
        self.log = log
        self.token = token or CancelToken()
        if isinstance(backend, str):
            if backend == "local":
                be: Any = LocalBackend(registry, specs=specs)
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

        #: 主控（M）自己的秘书（A 线）。`None` = 没装配 ⇒ 只摆同 key 终态行、不做委派评估。
        #: 秘书不写任何库表、判断不构成任何门的通过条件（`draft/55` §4）。
        self.secretary = secretary
        #: 最近一次派活前摆出来的"同 key 既有终态行"（读数的第二个落点：日志之外）。
        self._last_duplicates: list[dict] = []
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
        #: B9 的预留令牌序号（`summon` 在锁内占位时用它造一个唯一令牌）。
        self._reserve_seq = itertools.count()
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

    def _admitted_children_of(self, task_id: str) -> list[str]:
        """`task_id` 受理过的子召唤（= 扇出判据的分子）。

        ## 与 `_children_of` 的分工（刻意两个方法、两个口径）

        - `_children_of` 数"台账里有几行子行"：展示面/审计面用，含被闸门拒掉的
          那些尝试（谁试过什么必须看得见，`SummonResult.children` 由它填）；
        - `_admitted_children_of` 数"真的派出去过几件"：扇出判据用。

        为什么不就地改 `_children_of`：它不只服务扇出（`summon` 末尾的
        `res.children` 也用它），把它的口径改窄等于顺手改坏展示面 ——
        那一改没有任何地方会报错，只会让"谁试过什么"从台账视图里静默消失。
        判据见 `tests/test_fanout_admission.py::test_display_face_still_lists_attempts`。

        占不占名额的判据在 `_occupies_fanout_slot`（含真机读数与"为什么不是
        按拒绝理由过滤"）。
        """
        return [str(r["task_id"]) for r in self._tasks()
                if r.get("parent_task_id") == task_id and _occupies_fanout_slot(r)]

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

    # ---------------------------------------------------------------- 顶趟（F1）
    def open_top_level_run(self, role: str, task: str, *, by: str = "user",
                           input_key: str = "") -> str:
        """给一次顶趟（不是被召唤的那些）开一条 `tasks` 行，返回它的 `task_id`。

        ## 为什么必须有它（F1 / `44 J-32` 的"往前走"半）

        真机读数：`usage_ledger` 里 51%~66% 的行 `task_id` 为空，而
        `agent_loop.run_role` 给顶趟传的是 `my_task_id=""` ⇒
        `llmseam._charge_ledger` 把空串归一成 `None` ⇒ 那些钱读不出"属于哪一次召唤"。

        只填 `task_id` 而不先建行是负收益（`44 J-32` 逐字）：按 `verify.py` 的
        `dangling_usage_task`，每一行都会变成一条 error 级读数 ⇒ 一次改动制造几千行 error。
        所以这两件事必须同批：先建行（本方法），再让这一趟的每一次 `seam.ask` 带上它。

        历史不回填：盘上存量那些 null 行是历史事件（`store.rebuild` 重放同一批），
        改代码不改写历史；而 `None` 不进 `dangling_usage_task` 的判据
        （`verify.py` 逐字 `if tk is not None and str(tk) not in task_by_id:`）⇒
        那是一条已知基线，不是红。

        这条行不占并发/总量配额（`max_concurrency` 约束的是"同时在跑的召唤"，
        而顶趟是那个正在派活的人本身）；它只是让"这一趟"在台账上有一个身份。
        """
        started = S.now_iso()
        key = str(input_key or "").strip() or f"top:{role}:{abs(hash(str(task))) & 0xFFFFFFFF:08x}"
        row = {
            "task_id": "",
            "role": role, "action": "run", "called_by": str(by),
            "parent_task_id": None, "depth": 1, "input_key": key,
            "status": "running", "outcome": None, "refusal_reason": None,
            "instance": "", "detail": str(task or "")[:200], "error": None,
            "started_at": started, "ended_at": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }
        tid = self._write_new_row(row, note=f"top:{role}")
        self._log(f"顶趟开行 {role} → {tid}", task_id=tid)
        return tid

    #: `consume_pending_search_requests` 的两处消费计数（"派活时 N 条 / 收尾时 M 条"）。
    #: 它是读数：让 (乙) 形态对"即"字的折扣可度量（主控批 (乙) 的条件之一）。
    _consume_counts: dict[str, int]

    def consume_pending_search_requests(self, *, by: str = S.CONDUCTOR_ROLE,
                                        limit: int = 1, trigger: str = "dispatch") -> list[Any]:
        """S-03（队列认领 · 乙形态）：把还没做完的检索请求交给 A 的 `run_once`。

        ## "即"字的折扣（写在明面上，不许藏）

        这里的"提交即被消费"读作"下一次 M 侧派活（`run_plan`）或 M 收尾时被消费"。
        若 M 之后不再动，请求会留着 pending —— 让它可见的两条链：

        1. F-05 的消费端（`secretary.pending_inbox` / `inbox_todos`，秘书职责 3 会提醒 M）；
        2. `closing` 的研究链缺口读数（E-04b 那一档）。

        所以"不可见地挂着"这个最坏形态不成立；而"即"的折扣由下面的两处计数可度量。

        为什么不是"提交那一刻"就消费（`44 J-07` 之外的设计题）：那要给 C/D 塞 `conductor`
        ⇒ 变成处理体内的递归召唤（深度/预算/并发语义现在都按"M 是唯一派活方"设计），
        还要动 `host.py`（FC-27）。让"提交那一刻"就消费的正确做法是改派活权的归属，
        那是另一个设计题、要人裁 —— 按现在的设计不做。

        ## 幂等（"无意义/重复的委托"那一类）

        同一条 `request_id` 只唤起一次：判据是 `tasks` 里已经有
        `input_key == "consume:<rid>"` 的行（含 running —— 已经消费过就别再来一次）。
        `input_key` 同时是幂等键的可见形态，测试与审计都按它查。
        """
        out: list[Any] = []
        try:
            rows = list(self.store.rows("search_requests"))
        except Exception as exc:  # noqa: BLE001 - 扫不到队就如实留痕（不当成"队是空的"）
            self._log(f"扫队失败（{trigger}）：{type(exc).__name__}: {exc}")
            return out
        seen = {str(r.get("input_key") or "") for r in self._tasks()}
        for row in rows:
            if row.get("done"):
                continue
            rid = str(row.get("request_id") or "")
            if not rid:
                continue
            key = f"consume:{rid}"
            if key in seen:
                continue                      # 幂等：这一条已经消费过（含正在跑的那一次）
            try:
                res = self.summon("A", "run_once", {}, by=by, input_key=key)
            except Exception as exc:  # noqa: BLE001 - 一条消费失败不许拖住其余
                self._log(f"队列认领失败（{trigger}，{rid}）：{type(exc).__name__}: {exc}")
                continue
            out.append(res)
            seen.add(key)
            if len(out) >= max(1, int(limit)):
                break
        if out:
            counts = getattr(self, "_consume_counts", None)
            if counts is None:
                counts = {}
                self._consume_counts = counts
            counts[str(trigger)] = counts.get(str(trigger), 0) + len(out)
            self._log(f"队列认领（{trigger}）：消费 {len(out)} 条",
                      task_ids=[str(getattr(r, "task_id", "")) for r in out])
        return out

    def finish_top_level_run(self, task_id: str, *, stop_reason: str,
                             detail: str = "") -> SummonResult:
        """收一次顶趟（与 :meth:`open_top_level_run` 配对）。

        三态：`stop_reason == "final"` ⇒ `ok`（它真的收了工）；其余一律 `no_result`
        （跑完了、但没给出结论 —— 停步数/停坏 JSON 都属于这一档，不是 `failed`：
        那是"代码崩了"，两件事的处置不同）。

        ## 花销必须从账本抄回这一行（否则制造一条 `usage_task_total_mismatch`）

        这一趟的账挂在这一行的 `task_id` 上（F1 的另一半），所以 `tasks.tokens/usd`
        必须由账本派生（与 `_charge_and_settle` 同一条纪律：`tokens_for()` 抄回，
        而不是自己累加）。实测过缺这一步的后果：库里 `tasks.tokens=0` 而账本 150
        ⇒ `verify_all` 报一条 warning `usage_task_total_mismatch`
        （"两处对同一次召唤的花销给出不同数字"）—— 判据见
        `tests/test_agent_loop.py::test_f1_...`。
        """
        tokens_of_top = 0
        usd_of_top = 0.0
        try:
            tokens_of_top = int(self.meter.tokens_for(task_id))
            usd_of_top = float(self.meter.usd_for(task_id))
        except Exception as exc:  # noqa: BLE001 - 抄不回来就留日志（不阻断收行）
            self._log(f"顶趟花销没抄回来（{task_id}）：{type(exc).__name__}: {exc}")
        done = str(stop_reason or "") == "final"
        # S-03 的第二个消费点（主控补的）：收尾前扫一次队 —— 只挂"下一次派活"的话，
        # 最需要它的时候（这一趟就要结束了）反而不会消费。计数分 trigger 记，
        # 于是"即"的折扣在读数上可度量（"派活时 N 条 / 收尾时 M 条"）。
        try:
            self.consume_pending_search_requests(trigger="finish")
        except Exception as exc:  # noqa: BLE001 - 扫队失败不许带走收行
            self._log(f"收尾扫队失败：{type(exc).__name__}: {exc}")
        # 秘书职责 3（闭环提醒）的生产调用点（`draft/53` §2；主控 2026-10-04 裁定"接上"）：
        # 与上面那处收尾消费同址 —— 理由见 `remind_closure_at_finish` 的 docstring。
        closure = self.remind_closure_at_finish()
        return self._end(task_id, status="done", outcome="ok" if done else "no_result",
                         detail=(f"顶趟收工：{stop_reason}"
                                 + (f"；{detail[:200]}" if detail else "")
                                 + _closure_suffix(closure)),
                         tokens=tokens_of_top, usd=usd_of_top)

    #: 职责 3（闭环提醒）最近一次的收尾读数（`stats()` 与测试读它）。
    _closure_reading: dict[str, Any]

    def remind_closure_at_finish(self) -> dict[str, Any]:
        """秘书职责 3（闭环提醒）的生产调用点：收尾时问一次"谁没接手 / 谁没反馈"。

        ## 为什么接在这里，而不是 `agent_loop` 每趟的收尾

        1. 职责 3 的形态是「经 M」（`draft/53` §2）：它问的是链条级的事实 ——
           "提交了却没人接手"、"有人接手却没有终态" —— 而顶趟收尾是唯一能看见
           整条链的收尾点；`agent_loop` 那一层只看得到本角色这一趟。
        2. 与 S-03 的收尾消费点同址（上面那一次
           `consume_pending_search_requests(trigger="finish")`）：一个收尾点只做一轮扫描，
           "认领"与"提醒"两件事落在一起 —— 读代码与读读数都是同一段。
        3. "这一趟的读数"有现成的落点：顶趟行的 `detail`（一句话摘要）与
           :meth:`stats` 的 `closure_reminders`（全量），每条提醒另进决定台账
           （`secretary.remind_closure` 逐条落 duty=3）。

        ## 三态与 fail-open（与其余四职责同姿态）

        - 没装配秘书 ⇒ `checked=False` + 理由："没查成"不是"没有未闭环"；
        - 秘书自己抛异常 ⇒ 记 `fail_open=True` 并照常收尾 —— 提醒绝不许打断收尾；
        - 读成了、确实没有未闭环 ⇒ `checked=True, count=0, reminded=[]`
          （反负控：这一格不许凭空列人）。

        `by_state` 的读法：`unclaimed` = 提交了没人接手；`pending` / `running` =
        有人接手但没有终态（没有反馈）。读数照原样给，不另造一套状态名。
        """
        sec = getattr(self, "secretary", None)
        if sec is None or not callable(getattr(sec, "remind_closure", None)):
            reading: dict[str, Any] = {
                "checked": False, "reason": "没有装配秘书 ⇒ 这一格没查成",
                "count": 0, "reminded": [], "by_state": {}, "by_to": {}}
        else:
            try:
                reminded = [dict(x) for x in (sec.remind_closure() or [])]
                by_state: dict[str, int] = {}
                by_to: dict[str, int] = {}
                for item in reminded:
                    state = str(item.get("state") or "unknown")
                    by_state[state] = by_state.get(state, 0) + 1
                    to = str(item.get("to") or S.CONDUCTOR_ROLE)
                    by_to[to] = by_to.get(to, 0) + 1
                reading = {
                    "checked": True, "reason": "", "count": len(reminded),
                    "reminded": reminded, "by_state": by_state, "by_to": by_to,
                    "note": ("只报事实（谁没接手 / 谁没有终态）与条数，不替本体做事、"
                             "不伪造反馈；要不要真叫由调用方按 `should_engage` 走。")}
            except Exception as exc:  # noqa: BLE001 - 秘书坏了不许打断收尾（fail-open）
                self._log(f"秘书的闭环提醒没跑成（照常收尾）：{type(exc).__name__}: {exc}")
                reading = {
                    "checked": False, "fail_open": True,
                    "reason": f"秘书的闭环提醒没跑成：{type(exc).__name__}: {exc}",
                    "count": 0, "reminded": [], "by_state": {}, "by_to": {}}
        self._closure_reading = reading
        return reading

    # ---------------------------------------------------------------- 委托质量（A 线）
    def duplicate_candidates(self, role: str, action: str, input_key: str) -> list[dict]:
        """同 `(role, action, input_key)` 的既有终态行（只读；不阻断派活）。

        `draft/53` §10 的口径：派活去重归发件方秘书（职责 2 的"该不该派"含
        "是不是重复"），机器只把同 key 的既有终态行摆出来。为什么机器不硬拦：

        - "同 key"不是"同一件事"的充分条件（正当重试、参数微调后的重派都同 key），
          硬拦会把合法重试也拦掉 —— 那正是 #1 的另一半（把该做的活拦住）；
        - 而"摆出来"是确定性的、可复核的：调用方与秘书看到的是同一份读数。

        `input_key` 为空 ⇒ 空列表（没有键就没有"同 key"，不许把"没给键"读成"重复"）。
        """
        want = str(input_key or "").strip()
        if not want:
            return []
        out: list[dict] = []
        for row in self._tasks():
            if str(row.get("role") or "") != str(role):
                continue
            if str(row.get("action") or "") != str(action):
                continue
            if str(row.get("input_key") or "") != want:
                continue
            if str(row.get("status") or "") not in TERMINAL_STATUSES:
                continue
            out.append(dict(row))
        return out

    def budget_note(self, *, scope: str = "summon") -> dict[str, Any]:
        """预算读数（F2 的"只记录"半）：记录得到，但判决不因此改变。

        真机基线（`draft/44` 的 E-02）：`tasks.tokens` 4127 行只有 15 行非零、
        `usage_ledger` 51% 的行 `task_id=null` —— "没有代价可读"与"花得少"分不开。

        这一格刻意不参与任何判决：预算判据只有一处（`_meter_guard` → `guard()`），
        这里只是把同一份读数取出来（`recorded_only=True` 是它的自证标记）——
        多一处判决会让"一处说还能花、另一处说不能"漂移。
        """
        try:
            spent = self.meter.spent()
        except Exception as exc:  # noqa: BLE001 - 读数拿不到如实报，不折成 0
            return {"recorded_only": True, "scope": str(scope), "checked": False,
                    "reason": f"预算读数没取到：{type(exc).__name__}: {exc}"}
        state = dict(P.budget_state(self.policy, spent_tokens=int(spent.get("tokens") or 0),
                                    spent_usd=float(spent.get("usd") or 0.0)))
        state["recorded_only"] = True
        state["checked"] = True
        state["scope"] = str(scope)
        state["over_budget"] = bool(
            (state.get("tokens_left") is not None and state["tokens_left"] <= 0)
            or (state.get("usd_left") is not None and state["usd_left"] <= 0)
        )
        return state

    def _note_delegation_quality(self, role: str, action: str, params: Mapping[str, Any], *,
                                 input_key: str, by: str) -> None:
        """派活前：摆同 key 既有终态行 + 让秘书给一份委派评估（全 fail-open）。"""
        try:
            dups = self.duplicate_candidates(role, action, input_key)
            self._last_duplicates = dups
            if dups:
                self._log(
                    f"{by} 要派 {role}.{action}，而同一 input_key 已有 {len(dups)} 条终态行"
                    "（机器只摆出来、不阻断；是不是重复由发件方秘书判断）",
                    input_key=str(input_key),
                    existing=[str(r.get("task_id") or "") for r in dups[:5]],
                )
            note = self.budget_note()
            self._log("预算读数（只记录，不阻断）", **{k: note.get(k) for k in
                                                    ("tokens_left", "usd_left", "over_budget")})
        except Exception as exc:  # noqa: BLE001 - 留痕/读数坏了不许带走派活
            self._log(f"派活前的质量读数没取到（照常派活）：{type(exc).__name__}: {exc}")
            self._last_duplicates = []
            return
        if self.secretary is None:
            return
        try:
            self.secretary.assess_delegation(to=role, action=action, params=dict(params or {}),
                                             input_key=str(input_key), duplicates=dups)
        except Exception as exc:  # noqa: BLE001 - 秘书自己出错 ⇒ fail-open + 留痕
            self._log(f"秘书的委派评估没跑成（照常派活）：{type(exc).__name__}: {exc}")

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
        instance: str = "",
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
            # `instance` 的位置必须与 `Task` 的字段顺序一致（见上面 `task_id` 那条注记）：
            # 它在 `refusal_reason` 之后、`detail` 之前。
            "instance": instance,
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
        # ---- E-03 的机器半（A 线）：拒绝也必须写 `task_end`
        #
        # 真机基线（`44 J-27` 复核过的数）：refused 905 行里 361 行没有 `task_end`
        # 会话事件。后果不是"少一条日志"，而是"留痕"与"被处理"分不开：
        # `_refuse` 走的是"还没有 running 行"的那条路（它自己在 `_write_new_row`
        # 里建行），于是它绕开了 `finish` 里唯一的 `task_end` 落点 ——
        # 读会话的人看到的是"这一趟从来没结束过"，而读台账的人看到的是"它 done/refused"。
        # 三态纪律在这里：`status`/`outcome`/`refusal_reason` 三格都要在叙事里。
        #
        # 闭环（谁去处理这条拒绝）不在这里：那是收件方秘书的职责 3（"留痕" ≠ "被处理"）。
        # 写失败绝不改终态（与 `finish` 同一条纪律），原因进日志。
        from . import sessions as _SESS

        _path, _problem = _SESS.append(getattr(self.store, "root", "."), {
            "kind": "task_end", "task_id": tid, "by": by, "role": row["role"],
            "action": action or "unknown", "status": "done", "outcome": "refused",
            "refusal_reason": reason, "detail": detail[:200], "artifacts": [],
        })
        if _problem:
            self._log(f"会话记录没写成（拒绝那一行）：{_problem}", task_id=tid)
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
        它不是把全局预算换掉。若只判后者，一个调用方就能用 `budget={"max_tokens": 109}`
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
        instance: str = "",
    ) -> SummonResult:
        """唯一的召唤入口。见模块 docstring 的完整流程。

        参数
        ----
        lineage : 祖先链（含父自身）。`scheduler` 会带过来；直接调用时可省略，
            此时从 `tasks` 表按 `parent_task_id` 重建。两者必须一致：
            前者是纯调度（无 store）场景的表达，后者是正常运行时的权威来源。
        instance : 实例标签（2026-09-30 加）。空串 = 这个角色只有那一个实例
            （与从前逐字同义）。显式给不同的标签 ⇒ 被 `LocalBackend` 解析成
            不同的对象，并允许同波并发（`policy.estimate_write_conflict`）。
            它只影响"哪个实例干活"，不进 `tasks` 行 —— `tasks` 的字段是
            schema 契约（禁改区），实例身份落在数据行的 `actor` 上（由 `host`
            按实例造对象时写死），那才是可审计的那一份。
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
        # [1a] 不可召唤要先于动作表判（`draft/28` §154 的 R-44）。
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
                instance=instance,
            )
        edge = P.check_action(role, action, registry=self.specs)
        if edge is not None:
            return self._refuse(
                role, action, reason=edge.reason, detail=edge.detail, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                instance=instance,
            )

        # ---- [2] 参数（结构问题在写 running 行之前判掉：跑一个注定炸的
        #          参数会让台账里多一条 failed，而它其实从来没被执行过）
        spec = C.find_action(role, action, registry=self.specs)
        assert spec is not None  # check_action 已经保证过（`specs=` 那份注册表）
        bad = self._check_params(spec, params)
        if bad is not None:
            # 理由码是 `invalid_params` 而不是 `unknown_action`（R-46）：
            # "参数不合法"与"角色没这个动作"是两件事，前者要改参数，后者要查能力表。
            return self._refuse(
                role, action, reason="invalid_params", detail=bad, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                instance=instance,
            )

        # ---- [2b] 委托质量（A 线）：同 key 既有终态行摆到派活前 + 秘书的委派评估
        #
        # 位置是判据的一部分：在参数过关之后、写 running 行之前。参数不过关的召唤
        # 已经在上一步落成 `invalid_params`，不必再摆一次重复候选（那只会让读数变吵）；
        # 而写在 running 行之前，是为了让"这条既有终态行是我自己"这件事不可能发生
        # （同 key 的重复候选里永远不该出现本次的 task_id）。
        self._note_delegation_quality(role, action, params, input_key=input_key, by=by)

        # ---- [3] 深度链
        try:
            depth, parent_role = self._depth_of(parent_task_id)
        except ValueError as e:
            # 父任务不存在 = 这次调用本身不成立（结构问题），同样落 `invalid_params`
            return self._refuse(
                role, action, reason="invalid_params", detail=str(e), by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=1,
                instance=instance,
            )

        # ---- [4] 策略判定（边 / 深度 / 循环 / 扇出 / 并发 / 总量 / 预算 / 墙钟）
        chain = tuple(lineage) if lineage is not None else self._ancestry(parent_task_id)
        # 扇出 = 受理数，不是尝试数（题15 选B，2026-10-07）：被闸门拒掉的召唤照旧
        # 落行（谁试过什么要留痕），但不占名额 —— 否则父任务一旦触顶就再也派不出活，
        # 而每次尝试还会再占一格（自我毒化、不可恢复；真机读数见
        # `_occupies_fanout_slot`，判据见 `tests/test_fanout_admission.py`）。
        # 上限那一档按发起方角色取（`by`），默认档与主控档都在 `policy` 里。
        fanout = len(self._admitted_children_of(parent_task_id)) if parent_task_id else 0
        # ---- B9（`draft/41-A` 的 B9）：判据与占位必须在同一个临界区里
        #
        # 旧顺序是"锁内读 `running`/`total` → 锁外判 → 写完 running 行（一次 fsync
        # 事务）之后才 `_running.add`"。于是同一瞬间有 N 个线程都读到 `running=3` 时
        # 会全部放行，`max_concurrency` 被超过 (N-1)；`Semaphore` 只在单次
        # `run_waves` 内生效，跨 plan / 跨进程都不约束。
        #
        # 修法：把"占位"提到锁内、与读计数同一临界区（判 + 预留 + 失败回滚），
        # I/O 仍留在锁外（"事务绝不包 handler"以及"锁内不做 I/O"两条纪律都不动）。
        # 预留用的是一个唯一的占位令牌（不是 task_id —— 那个要 `_write_new_row`
        # 拿到锁才分配）：于是 `len(self._running)` 的含义从"真的在跑的"扩成
        # "已接受、还没结束的"，而这正是上限想约束的那个量。
        with self._lock:
            # 两个数都按旧语义取：`running` 是"已经接受、还没结束"的条数
            # （不含本次自己），`total` 是"已经发生过"的次数（不含本次）——
            # 这样 `policy.check` 的 `>=` 边界一个字节都不动（改了语义等于偷偷收紧上限）。
            # 与旧实现的唯一差别是：别的线程的预留也在这个集合里了 ⇒ 那个窗口没了。
            running = len(self._running)
            total = self._started_total + self._cancelled_total
            self._started_total += 1                # 预留：与下面的令牌同进同出
            reserve = f"__reserving__{next(self._reserve_seq)}"
            self._running.add(reserve)
            self.peak_running = max(self.peak_running, len(self._running))

        def _release_reservation() -> None:
            """把这次预留还回去（判据说不、或建行失败时）。幂等。"""
            with self._lock:
                if reserve in self._running:
                    self._running.discard(reserve)
                    self._started_total = max(0, self._started_total - 1)

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
            _release_reservation()
            return self._refuse(
                role, action, reason="budget_exceeded", detail=grant.reason, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
                instance=instance,
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
        refusal = P.check(self.policy, d, registry=self.specs)
        if refusal is not None:
            # 墙钟到点：除了拒绝，还要协作式取消在跑的
            # （设计 §3.2："已在跑的协作式取消"）。
            if refusal.reason == "deadline_exceeded":
                self._signal_stop("deadline", refusal.detail, by="deadline")
            _release_reservation()
            return self._refuse(
                role, action, reason=refusal.reason, detail=refusal.detail, by=by,
                parent_task_id=parent_task_id, input_key=input_key, params=params, depth=depth,
                instance=instance,
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
            # 与 `Task` 的字段顺序一致（`refusal_reason` 之后、`detail` 之前）——
            # 顺序不一致会让 `tasks.json` 在 `rebuild()` 之后逐字节不同（I-9）。
            "instance": instance,
            "detail": spec.summary, "error": None, "started_at": started, "ended_at": None,
            "tokens": 0, "usd": 0.0,
            "artifacts": [],
            # `inputs` 的初值同时打上受理标记（题 21 选 B，2026-10-07 所有者裁定）：
            # 它与 `status="running"` 这一行同一笔事务落盘，因此扇出判据
            # （`_occupies_fanout_slot`）不再依赖后续任何一步（角色自己的拒绝、
            # 记账写回、甚至崩溃）是否成功。理由与负控见 `_ADMITTED_MARK`。
            "inputs": _admitted_inputs(params),
        }
        try:
            tid = self._write_new_row(row, note=f"start:{role}.{action}")
        except BaseException:
            # 建行失败（store 抛了什么）⇒ 预留必须还回去，否则"已接受、还没结束"的
            # 计数会永久高一个，后续每一次召唤都被自己上次的失败挤掉配额。
            _release_reservation()
            raise
        with self._lock:
            # 把占位令牌换成真 task_id：计数一个不增不减（预留已经计过了）。
            self._running.discard(reserve)
            self._running.add(tid)
        self._log(f"召唤 {by} → {role}.{action}（{tid}, depth={depth}"
                  + (f", instance={instance}" if instance else "") + "）")

        # ---- [6] 执行
        try:
            # `task_id` 传下去（2026-09-30）：并发多实例时"按角色找那条 running 行"
            # 会同时找到 N 条 ⇒ 后端拿不到自己的台账号。台账号是这一次召唤刚写下的，
            # 这里就是它唯一的权威来源，直接给，别让后端去猜。
            raw = self.backend.call(role, action, params, token=token, instance=instance,
                                    task_id=tid)
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
            # 角色代码故意抛出的领域错误（`ExperimentError` / `DocumentError` /
            # `PlanError` / `ReviewError` / `EvidenceError` / `ToolError`）表示
            # "这次调用不成立" —— 与 `refused` 同族；而 `TypeError` / `KeyError` /
            # `AttributeError` / `OSError` 这些是代码或环境崩了，必须留 `failed`。
            # 以前两者一律落 `failed / 执行中异常`：实测 4 条 `E.run_experiment`
            # （我把 `name`/`imports` 与 `method="numeric"` 一起传）就这么被记成"崩了"，
            # 而它其实是一次参数拒绝 —— 读台账的人会去查代码，而该改的是调用。
            #
            # 刻意不把裸 `ValueError` 算进拒绝：它既可能是校验（业务），
            # 也可能是判据自身的 bug；宁可把它留在 `failed`（过度报失败比把 bug
            # 伪装成"策略说不"安全）。
            code = _business_refusal_code(e)
            if code is not None:
                res = self._end(tid, status="done", outcome="refused", refusal_reason=code,
                                detail=f"{role}.{action} 拒绝了这次调用：{e}")
            else:
                res = self._end(tid, status="failed", outcome="failed",
                                error=f"{type(e).__name__}: {e}",
                                # 详情里也要带原话（`draft/39` §6.29 的 D41）：真机读数
                                # （T2 第 7 趟 `p6i` 与第 11 趟 `p6m`）里主控连着三次收到
                                # "E.run_experiment 执行中异常"这一句，而它修不了脚本 ——
                                # 不知道是导入失败、语法错、还是脚本自己抛的。
                                # 三态纪律在这一层：失败要留下能据以改的原话。
                                detail=f"{role}.{action} 执行中异常"
                                       f"（{type(e).__name__}: {e}）")
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
        # 展示面：`children` 列的是全部子行（含被闸门拒掉的尝试，谁试过什么要看得见），
        # 与扇出判据（`_admitted_children_of`）刻意两个口径 —— 判据面不许把展示面改窄。
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
            error = str(raw["error"]) if raw.get("error") else None
            refusal = str(raw["refusal_reason"]) if raw.get("refusal_reason") else None
            if refusal is not None and refusal not in S.REFUSAL_REASONS:
                # 自由文本当拒绝理由：不许进受控词表。原来的写法是把它透传给
                # `Task.validate` ⇒ 那里抛 `ValueError` ⇒ 整步落 failed
                # —— 一次"拒绝"被记成"崩溃"，理由反而看不见了。
                detail = f"[handler_refusal_reason={refusal!r} 不在受控词表] {detail}".strip()
                refusal = None
            if status == "done" and (outcome is None or raw.get("ok") is False):
                if raw.get("ok") is False:
                    # ---- §88：handler 自己说了"这次没做成"，就不许记成 ok。
                    #
                    # T1 第 2 趟真机的根因：`B.register_statement` 有 8 次返回
                    # `{"ok": False, "kind": "missing_quote_reason"…}`，而台账把它们
                    # 全记成 `outcome=ok`（detail 还写着"按有产出处理"）⇒ 主控以为
                    # 命题登记好了，而 `statements` 是 0 行；它因此不再改参数，
                    # 那条链就在这一步静默停住。同一趟里另外 6 次抛异常反倒记成了
                    # `failed` —— "拒绝"与"崩溃"同形，"成功"与"什么都没写"也同形。
                    #
                    # 分档：handler 声明了受控的 `refusal_reason` ⇒ `refused`
                    # （词表的定义就是"这次调用本身不成立"）；只说 `ok=False` 而
                    # 没分类 ⇒ `failed`（那是"执行了、没成功"，理由合成在 error 上）。
                    # 声明的 `outcome` 无论是不是任务级词表，都不许把 `ok=False`
                    # 洗成 ok —— 那正是下面那条"外来判定折叠成 ok"的规则会做的事，
                    # 所以这里必须先接住（判据：自相矛盾与外来判定两条负控）。
                    kind = str(raw.get("kind") or "")
                    declared = str(outcome or "")
                    stamp = f"[handler_ok=False kind={kind or '未声明'}]"
                    if declared == "ok":
                        stamp += "[同时声明 outcome=ok：自相矛盾，按没做成分档]"
                    elif declared:
                        stamp += f"[同时声明 outcome={declared}：不是任务级词表，按没做成分档]"
                    detail = f"{stamp} {detail or error or ''}".strip()
                    if refusal is not None:
                        outcome = "refused"
                    else:
                        status = "failed"
                        outcome = "failed"
                        error = error or f"{stamp} handler 返回 ok=False，未声明受控的 refusal_reason"
                elif outcome is None:
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
                error=error,
                # 角色拒绝时它的理由必须能传到行上：`Task.validate` 逐字要求
                # `outcome=refused` 带受控的 `refusal_reason`，而这里此前没透传它
                # ⇒ 角色一拒绝就落 `failed`（"策略说不"被记成"代码崩了"）。
                # 实测（2026-09-29）：这正是 `test_refused_outcome_is_not_rewritten` 咬出来的。
                refusal_reason=refusal,
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
        写失败不影响终态：原因记进日志并返回空串 —— "有产出但摘要没写成"
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
                # ---- 读数键提到顶层（`R1-A2`，真机回放抓出来的）
                #
                # 口径：凡 payload 里以 `_reading` 结尾的键（今天是 `llm_reading`，
                # 角色 D 那三类三态读数都在里面）原样放在这一格，不截断。
                # 为什么必须这样：`payload_preview` 的天花板是 2000 字，而读数的作用
                # 就是被读到 —— 放进预览等于"有时读得到、有时读不到"（真机实测：
                # `t-0056` 那一趟 `payload_keys` 里有 `llm_reading`，而 preview 里没有，
                # 于是"这次到底问没问模型、问成没问成"在盘上读不出来）。
                # 空的时候给 `{}` 而不是省略这个键：省略会让"这一步没有读数"与
                # "这是旧格式的摘要"长得一样（三态纪律：没读到与没有要分得开）。
                "readings": ({str(k): v for k, v in payload.items()
                              if str(k).endswith("_reading")}
                             if isinstance(payload, Mapping) else {}),
            }
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                              encoding="utf-8")
        except (OSError, TypeError, ValueError) as e:  # noqa: BLE001 - 见 docstring
            self._log(f"任务产出摘要没写成：{type(e).__name__}: {e}", task_id=task_id)
            return ""
        return rel

    def _write_completion_manuscript(self, row: Mapping[str, Any], *, task_id: str, status: str,
                                     outcome: str | None, detail: str, error: str | None,
                                     payload: Any) -> None:
        """动作驱动的一趟结束时，按已发生的事实代写一份交接手稿（`draft/39` §6.6 F1）。

        写什么：任务号 / 角色.动作 / 状态与结论 / 详情 / 产物路径 / 参数摘要；
        `to` = 召唤者（`called_by`），`note` 明写"框架据动作结果派生"。
        纪律三条：
        ① 不重复：同一 `task_id` 下已经有该角色的行（循环驱动那一趟自己填的 `notify`）⇒ 跳过；
        ② 不带走向：留痕失败只进日志，绝不改变任务的终态（与会话记录/产物登记同一条纪律）；
        ③ `cancelled` 不写：没干完的活不是"交接"（这一条由调用方保证）。
        """
        root = getattr(self.store, "root", ".")
        role = str(row.get("role") or "")
        caller = str(row.get("called_by") or "")
        if not role or not caller:
            return
        from . import manuscripts as _MS

        try:
            if _MS.rows_for_task(root, task_id, sender=role):
                return
            action = str(row.get("action") or "")
            verdict = str(outcome or status or "")
            one_line = f"{action}：{verdict}" + (f"（{detail[:60]}）" if detail else "")
            lines = [f"## 这一趟干了什么", "",
                     f"- 任务号：`{task_id}`", f"- 角色.动作：{role}.{action}",
                     f"- 状态：`{status}` / 结论：`{verdict}`"]
            if detail:
                lines.append(f"- 详情：{detail[:400]}")
            if row.get("refusal_reason"):
                lines.append(f"- 拒绝理由：`{row['refusal_reason']}`")
            if error:
                lines.append(f"- 错误：{str(error)[:300]}")
            arts = list(row.get("artifacts") or [])
            if arts:
                lines += ["", "## 产物", ""] + [f"- `{a}`" for a in arts[:10]]
            params = dict(row.get("params") or {})
            if params:
                lines += ["", "## 参数摘要",
                          f"```json\n{json.dumps(params, ensure_ascii=False)[:600]}\n```"]
            if payload is not None:
                lines += ["", "## 返回值摘要",
                          f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)[:600]}\n```"]
            lines += ["", "## 这一行是怎么来的",
                      "这一趟是**动作驱动**（框架代跑 Python 技能），没有模型收工那一刻，"
                      "所以框架按动作结果派生这一行：内容全部取自 `tasks` 那一行与它的返回值。"]
            _MS.write(root, sender=role, recipient=caller, summary=one_line,
                      body="\n".join(lines) + "\n", task_id=task_id,
                      note="留痕来源：框架据动作结果派生（动作驱动的一趟没有 final 可填）")
        except Exception as e:  # noqa: BLE001 - 留痕不是判据本身，绝不许带走终态
            self._log(f"交接留痕没写成：{type(e).__name__}: {e}", task_id=task_id)

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
            # 为什么必须落：`tasks` 表不存 payload ⇒ `outcome=ok` 无法自证有产出
            # （实测 83 行 detail 是"handler 未声明 outcome，按有产出处理"，
            # 读台账的人判不出这一步到底产出了什么，见 `draft/28` §154 的 S3/R-47）。
            # 摘要落 `<workspace>/out/tasks/<task_id>.json`（键集 + 规范化哈希 + 截断预览），
            # 表里只多一个 artifacts 引用 —— `tasks` 表结构不动（它在 FC-27 禁改区）。
            #
            # ---- B12（`draft/41-A` 的 B12）：这一处是已决定的例外
            #
            # 它是"锁内写盘"（持 `tasks`+`counters` 文件锁期间写 `out/tasks/<id>.json`），
            # 而 `summon` 的注释明确写过"事务绝不包 handler"。但这一处挪不出去：
            # 这次 I/O 的内容不是"与台账无关"的 —— 它被本事务体内的一次读-判门住
            # （上面那两行 `if row.get("status") in TERMINAL_STATUSES: return`）：
            # 只有抢到终态的那一次才走到这里。把写文件挪到事务之前会把这个门去掉，
            # 于是后到的写者也能改这份摘要（同一个 task_id、两份 payload，输家覆盖赢家）。
            # 判据：`tests/test_e13_concurrency.py::`
            # `test_b12_the_digest_write_stays_inside_the_winner_transaction`。
            #
            # 规则那句话按此精确化：事务体内不做 I/O 的例外是"这次 I/O 的内容取决于
            # 事务内的读-判结果" —— 那时把 I/O 挪出去等于换掉判据本身。
            # 顺带核实（主控要求）：`closing` 第八格 `artifact_ledger` 只数台账行
            # （`missing`/`unreadable`/`changed` 都相对"登记过的产物"算），
            # 不扫盘上多出来的文件 ⇒ 本例外不会在那一格里造出 `missing`/`changed` 读数。
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
        # 写失败不改变终态：叙事不是判据本身，原因进日志。
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
        # ---- 产物归属登记（`R-52` 余；`draft/28` §153 的 A3/A4）。
        #
        # 为什么在这里而不是每个智能体自己记：`tasks.artifacts` 只回答"这次召唤产出了
        # 哪些引用"，不回答"这个路径归谁产" —— A3（两份断言台账同义不同物）与
        # A4（六个产生验收读数的脚本既非 experiments 行也非 documents 行）都是这个缺口
        # 的形态，而两条都发生在"框架自己落下的产物"上。摘要是这条链路上唯一由框架
        # own 的产物落点，登记它就有了第一条真记录（而不是一个空转的模块）。
        # 纪律与会话记录逐条相同：写失败不改终态，原因进日志。
        if digest_rel:
            from . import artifacts as _ART

            try:
                _ART.record(getattr(self.store, "root", "."), path=digest_rel,
                            producer=str(row.get("role") or "M"), kind="task-result",
                            task_id=task_id, note=f"outcome={outcome}")
            except Exception as e:  # noqa: BLE001 - 登记不是判据本身，不许带走终态
                self._log(f"产物归属没登记成：{type(e).__name__}: {e}", task_id=task_id)
        # ---- 交接留痕：动作驱动的一趟结束。
        #
        # 2026-10-06 改（`draft/39` §6.49 的 D64，用户裁定）：这里不再代写交接手稿。
        # 原来的理由（`draft/39` §6.6 F1）是"动作驱动的趟没有 final 可填，账本会缺这一格"；
        # 真机把它证伪了：T1–T5 五趟的 `manuscripts/handoffs.jsonl` 里 92 / 96 / 118 / 62 / 94
        # 行全是框架派生的模板，`refs` 逐行全空、正文是"从/到/一句话/时间/引用"的填空 ——
        # 用户的原话是「handoffs 里面没有几条有效信息全在强调纪律」。
        # 这类行的信息与 `tasks` / `out/tasks/*.json` 逐字重复 ⇒ 它的落点是那里，不是交接账本。
        # 账本从此只装"模型自己写的、带编号的"交接（派活时带 `notify`、收工时 `final.notify`）；
        # 谁在什么时候把什么交给了谁，靠那些行才查得出来。
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
        # ---- S-03 的第一个消费点（队列级认领 · 乙形态）：派活时顺手把还没做完的
        # 检索请求交给 A 的 `run_once`（幂等：同一条 request_id 只唤起一次）。
        # 放在派活之前：这一波 plan 之后，队里那条 pending 就该有人做了。
        # 扫队失败不许拖住这一波派活（它只是"顺手多做一件"）。
        try:
            self.consume_pending_search_requests(trigger="dispatch")
        except Exception as exc:  # noqa: BLE001 - 见上
            self._log(f"派活前扫队失败：{type(exc).__name__}: {exc}")
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
            # ---- 两套口径并存，必须写明（F1 之后它们不再相等）
            #
            # F1 之后 `tasks` 里多了顶趟行（`action="run"`，由 `open_top_level_run` 开、
            # `finish_top_level_run` 收）。于是这一屏上：
            #
            # - `total` / `by_role` / `by_status` / `by_outcome` / `by_depth`
            #   = 台账全量（上面 `rows = self._tasks()` ⇒ 含顶趟行）；
            # - `started_total` / `peak_running` = 本实例发起的召唤数（只在 `summon`
            #   里自增；顶趟不占并发/总量配额，所以它不进这两个数）。
            #
            # 两个数不一样不是 bug，是两件事：一个问"台账里有什么"，一个问"我派了几次活"。
            # 但不写清就会变成"同一屏里两个读数各说一件事"——本项目最忌的形态，
            # 所以把口径连同 `top_level_runs` 这个分类计数一起给出来（读者不必自己减）。
            "calibers": {
                "total / by_*": "tasks 台账全量（含顶趟行 action=run）",
                "started_total / peak_running": "本实例发起的召唤数（顶趟不计）",
            },
            "top_level_runs": sum(1 for r in rows if str(r.get("action") or "") == "run"),
            # S-03：两处消费点各消费了几条（"派活时 N / 收尾时 M"）——让"即"的折扣可度量。
            "consume_counts": dict(getattr(self, "_consume_counts", {}) or {}),
            # 职责 3（闭环提醒）：最近一次顶趟收尾时的读数（谁没接手 / 谁没反馈 / 各几条）。
            # 它是一格读数，不是门（`draft/55` §4：秘书不新增机器判据）。
            "closure_reminders": dict(getattr(self, "_closure_reading", {}) or {}),
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
#: 本角色的声明（`goal-7f5116c1` M3）。
#:
#: 真身在 `specs/m.py` —— 那里就是权限面的落点（`.noai-paths` 保护它）。
#: 这里只做再导出：`agentspec.builtin_registry()`、判据与调用方都按 `mod.SPEC` 取，
#: 于是"角色模块里能读到自己的声明"这件事仍然成立，而不会多出第二份拷贝。
from .specs.m import SPEC  # noqa: E402,F401




# ---------------------------------------------------------------- S-02 的读数


#: `uncalled_actions_reading` 的口径（2026-10-02 主控现场更正，逐字的意思）：
#: 它数的是 `store.rows("tasks")` —— tasks 台账的落盘行，而不是全量召唤流水。
#: 权威读数是 `sessions/*.jsonl` 里的 `events`（重放能重建 tasks）。实测：某个工作区的
#: `tasks.json` 只有 2 行，而同目录的 `events.jsonl` 有 1161 行 ⇒ 两个口径的数
#: 差得很远，谁也不是"数据缩水"。所以这条读数把自己的口径印在返回里：
#: 凡"数召唤行数"的读数都必须自带口径，跨口径比大小是错的那种用法。
_UNCALLED_ACTIONS_CALIBER = (
    "按 store.rows(\"tasks\") 数（tasks 台账的落盘行，可能只是缓存/最近一次落盘）；"
    "权威读数是 sessions/*.jsonl 的 events 重放 —— 两个口径的数不许互相比"
)


def uncalled_actions_reading(store: Any) -> dict:
    """S-02 的读数：声明了、但一条召唤行都没有的动作（只读，不加闸门）。

    ## 它回答的那个问题（`44 S-02`）

    D 的五个核心动作（`assess`/`submit_gaps`/`adjudicate`/`trace_question`/`trace_l3`）
    都在声明表里、各有 handler，而真机 4127 行 `tasks` 里一次都没被召唤过。
    "声明了但没人召唤过"这件事，今天没有任何读数在说：
    `Conductor.stats()` 只有 `by_role`/`by_status`/`by_outcome`/`by_depth`，没有
    `by_action` —— 于是真机 0 次调用只能在临时探针里看见。

    这是一条纯读数：它服务的是 #1（无意义/重复的委托）的可见性，
    不是判决 —— "该不该派这个动作"归秘书（`J-37`/`J-40`：切勿全写死成机器判据），
    所以这里不接 handler、不进工具面、不加任何闸门。

    ## 口径（2026-10-02 主控现场更正）

    数的是 `store.rows("tasks")`（台账的落盘行），不是全量召唤流水；权威读数是
    `sessions/*.jsonl` 里的 `events` 重放。返回里的 `caliber` 逐字写这件事 ——
    跨口径比大小是错的用法（实测某个工作区 `tasks.json` 2 行、同目录
    `events.jsonl` 1161 行，两者谁也不是"数据缩水"）。

    ## 三态

    - `checked=True`：声明表与 `tasks` 都读到了，`uncalled` 是做差的结果；
    - `checked=False` + `reason`：读不到（`tasks` 或声明表）⇒ 不许折成"全都没被调用"。
      （"全都没被调用"是一个很强的结论，只有真读到两边才配下。）

    `called` 是"至少有一条召唤行"的那个集合（`refused` 也算 —— 它是一次真的提出过
    的召唤，台账上留着行）；`declared_total` / `called_total` 给分母，便于看比例。
    """
    try:
        rows = list(store.rows("tasks"))
    except Exception as exc:  # noqa: BLE001 - 读不出来如实报
        return {"checked": False, "reason": f"tasks 读不出来：{type(exc).__name__}: {exc}",
                "uncalled": [], "declared_total": 0, "called_total": 0,
                "caliber": _UNCALLED_ACTIONS_CALIBER}
    try:
        from . import capabilities as _C

        table = dict(getattr(_C, "CAPABILITIES", None) or {})
    except Exception as exc:  # noqa: BLE001 - 同上
        return {"checked": False, "reason": f"声明表读不出来：{type(exc).__name__}: {exc}",
                "uncalled": [], "declared_total": 0, "called_total": 0,
                "caliber": _UNCALLED_ACTIONS_CALIBER}
    declared = {(str(role), str(getattr(spec, "action", "") or ""))
                for role, specs in table.items() for spec in specs}
    declared.discard(("", ""))
    called = {(str(r.get("role") or ""), str(r.get("action") or "")) for r in rows}
    uncalled = sorted(p for p in declared - called if p[1])
    return {
        "checked": True,
        "reason": "",
        "caliber": _UNCALLED_ACTIONS_CALIBER,
        "uncalled": [{"role": role, "action": action} for role, action in uncalled],
        "count": len(uncalled),
        "declared_total": len(declared),
        "called_total": len(declared & called),
        "note": ("这条读数只回答\"声明了但没被召唤过\"：为什么没人派、该不该派，"
                 "归秘书判断（`J-37`）；本读数不构成任何门的通过条件。"),
    }
