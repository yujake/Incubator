"""智能体 F：多轮难题攻坚。

设计基线：``test/test1/DESIGN-ROLES.md`` §2.2 与 `schema.AttackPlan` 的硬约束。

## F 到底在做什么

把一个难题变成多轮、可终止、可交接的攻坚过程：

    立项（带三维预算） → 选子目标（确定性次序） → 按 owner 分派一个动作
        → 记一轮 history → 判断是否还能继续
            ├─ 还能 → 下一轮
            └─ 不能 → 交出 best_partial（`stalled`）或如实收口（`resolved`）

## 三条不可让步的设计

### 1. 终止条件是预算，不是"看起来差不多了"（FC-18）

"还没做出来"永远成立，所以一个没有预算的攻坚循环会一直跑下去 —— 而且它跑得
越久越像在工作。因此 `rounds` 的单调上界由 `budget.max_rounds` 硬性给出，
用尽即 `stalled`（不是失败，也不是成功，见 `ATTACK_STATUSES` 的注释）。

### 2. 只做框架内真实存在的事（本模块最重要的一条）

`step` 按子目标的 `owner` 分派，而"分派"必须落在真的被接线的动作上：

| owner | 动作 | 状态 |
|---|---|---|
| `E` | 调 `AgentE.run_experiment`（带 `script_path` 时） | 已接线 |
| `A` | `interactions.admit_search_request` 过闸门 → 写 `search_requests` | 已接线 |
| `B` | `interactions.admit_reprocess_request` 过闸门 → 写 `reprocess_requests` | 已接线 |
| `C`/`D`/`F` | 没有任何自动推理可调 | 记 `outcome="no_change"` |

`C`/`D`/`F` 那一行是刻意的：本框架尚未接线自动推理，所以 F 只能如实写
"该子目标需要 C/D/F 的推理，本框架尚未接线 ⇒ 未推进"。

为什么这一条必须写死：把它写成"做了但没结果"（例如
`outcome="progress"` + 空证据）是静默失败的典型形态 —— 计划看起来在推进、
history 里每一轮都有记录、`rounds` 在增长，而实际上什么也没发生。
本项目最痛的教训（`11-...md` §10.4 #7：D 没接工具却把"查不到"写成一条
听起来很合理的研究发现）就是这种形态。三态纪律在这里的具体形态是：

    outcome="no_change" 且 detail 里写明"未推进"  ≠  outcome="progress" 且证据为空

### 3. 数值支持不能关闭子目标（FC-22）

E 返回 `evidence_kind="cross_check"` 时子目标最多标 `supported_not_proved`；
只有 `proof` 级实验（`method="formal"` + 非空 `verifier_output`）才进
`proof_experiment_ids`、才允许 `closed`。schema 会拒绝违规组合，
F 的职责是不制造这种组合（而不是"写了再靠 schema 兜"）。

## 与 `attack_tools` 的分工

- `check_budget` / `can_round` / `pick_next_subgoal` / `can_derive` 唯一实现在
  `tools/attack_tools.py`，本模块只转发。理由：排序与预算口径一旦有两份，
  "F 认为该做 A、验收方认为该做 B"不会报任何错。
- `attack.create_plan` / `attack.step` / `attack.status` / `attack.list_plans`
  四个工具转发到本模块（见 attack_tools 的 docstring）：写入逻辑只有一份。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import re

from . import interactions as IX
from . import schema as S
from .store import Store
from .tools import attack_tools as AT
from .tools.base import ToolError, ToolRegistry
from .agentspec import AgentBrief, AgentSpec

__all__ = ["AgentF", "PlanError", "STEP_OUTCOMES", "install_f_tools", "selftest"]


class PlanError(ToolError):
    """攻坚计划无法创建 / 推进（预算不完整、计划不存在、子目标非法）。

    ## 为什么继承 `ToolError`（而不是裸 `RuntimeError`）

    `attack.create_plan` / `attack.step` / `attack.status` / `attack.list_plans`
    的处理函数直接调 `agent_f` 的方法，而 `attack_tools.py` 里没有
    `guard_result` 之类的守卫（该文件不属于本次交付）。于是本类原先作为
    裸 `RuntimeError` 一路穿出工具层，被 `ToolRegistry.call` 的
    `except Exception` 兜成 `kind="unexpected"` —— 调用方只看到"出了个意外"，
    看不到"这是攻坚计划层面的拒绝、原因是什么"。

    继承 `ToolError` 之后，同一个异常在工具层被映射成
    `kind="tool_error"` 且消息原样保留，失败类型信息不再丢失。
    注意 `ToolError` 本身是 `RuntimeError` 的子类，所以既有
    `except PlanError` / `except RuntimeError` 的调用点行为不变。

    （`agent_e.ExperimentError` 刻意不这样改：`verify_tools` 的
    `_run_experiment_tool` 用 `except ToolError: raise` 把 ToolError 排在
    `except RuntimeError` 之前，改基类会让那条精心写的"实验执行失败"
    分支永远不再命中、退化成一条泛泛的错误。两者的处置不同是有意的。）
    """


#: 终局状态。与 `attack_tools.TERMINAL_STATUSES` 是同一个元组对象（别名，
#: 不是拷贝）："哪些状态算终结"只能有一处定义，否则 `create_plan` 的查重口径
#: 与 `step` 的终止口径会静默分裂。
TERMINAL_STATUSES = AT.TERMINAL_STATUSES

#: 尚未接线的 owner。它们不是错误（框架确实还没接），所以不抛异常、
#: 也不标记 `dropped`，而是如实记一轮 `no_change` 并让子目标回到可重试的位置。
UNWIRED_OWNERS = ("C", "D", "F")

#: 子目标在历史里的 `action` 词表（受控字符串，便于审计与统计）。
ACTIONS = (
    "run_experiment",
    "submit_search_request",
    "submit_reprocess_request",
    "no_change",
    "stop",
)

#: 一轮推进的 `outcome` 词表（`G-24②`）。
#:
#: ## 它与 `schema.TASK_OUTCOMES` 是两套命名空间（同形、不同义）
#:
#: 两者都是"结果"词表（短小写英文词，都用于记账），所以它们看起来同形；
#: 而它们回答的是两个不同的问题：
#:
#: - `schema.TASK_OUTCOMES`（`("ok","no_result","not_applicable","refused","failed",
#:   "cancelled")`）说的是一次任务的终局 —— 它写进 `tasks.outcome`，
#:   由 `schema.Task.validate` 机械校验，取值面是"这次召唤最后怎么了"；
#: - `STEP_OUTCOMES`（本表）说的是一轮推进的结果 —— 它写进
#:   `AttackPlan.history[i]["outcome"]` 与 `AgentF.step` 的返回值，
#:   取值面是"这一轮有没有让计划往前走"。
#:
#: 裁定依据（读代码得来，不是猜）：`step` 把本表的值写进 `history` 的那一条
#: 记录（`{"round","sid","action","outcome","detail","evidence","at"}`），
#: 而同一行里还有 `action` / `sid` / `round` —— 它记的是一个子目标的一轮；
#: 一个计划要跑很多轮才可能到达终局，`resolved` / `stalled` 那些终局状态
#: 走的是 `schema.ATTACK_STATUSES`（`row["status"]`），不是本表。
#: `stall_after_no_progress_rounds` 的提前停止判据也是逐轮读本表
#: （连续 N 轮 `no_change`）—— 终局词表里没有任何一个值是"这一轮没进展"。
#:
#: 所以：不许互相赋值。把 `outcome="progress"` 写进 `tasks.outcome`
#: 会被 schema 当场拒（那是好事），而把 `"refused"` 之类写进 history
#: 会让停滞检测永远算不出 `no_change`（那是静默的：`len(recent) == stall_after`
#: 仍然成立，只是 `all(o == "no_change")` 恒假，于是"连续无进展"再也测不出来）。
#: 两个词表的取值集合不重叠这件事由导入期断言钉住（见下面的 assert）。
STEP_OUTCOMES: tuple[str, ...] = ("no_change", "progress", "blocked")

assert not (set(STEP_OUTCOMES) & set(S.TASK_OUTCOMES)), (
    f"STEP_OUTCOMES={STEP_OUTCOMES} 与 schema.TASK_OUTCOMES={S.TASK_OUTCOMES} 有交集 "
    f"{sorted(set(STEP_OUTCOMES) & set(S.TASK_OUTCOMES))} —— 两者是两套命名空间"
    "（一轮推进的结果 vs 一次任务的终局），取值一旦重叠，互相赋值就再也拦不住"
)


def _step_outcome(value: Any) -> str:
    """把一轮 `outcome` 收口到 `STEP_OUTCOMES`（fail-closed）。

    为什么要有这一道（而不是只留一张词表）：词表本身没有消费者时，它就是注释
    —— 一个拼错的 `outcom="progres"` 会原样写进 `history`，而没有任何地方会报错。
    写的两个落点（history 与 `step` 的返回值）都过这道闸，于是"词表外的取值"
    在写入的那一刻就炸，而不是等审计去猜它想说什么。
    """
    s = str(value)
    if s not in STEP_OUTCOMES:
        raise PlanError(
            f"一轮推进的 outcome 必须是 {STEP_OUTCOMES} 之一，收到 {value!r} —— "
            "它与 `schema.TASK_OUTCOMES`（一次任务的终局）是两套命名空间，"
            "不许互相赋值；词表外的值会让停滞检测静默失效"
        )
    return s

#: `status="stalled"` 时，如果连一轮都没跑过，`best_partial` 必须写的如实说明。
#: 为什么不许留空：`AttackPlan.validate` 要求非空（"攻坚停下来了却什么都不交出去，
#: 等于把已经得到的中间成果丢掉"）。但"非空"不等于"可以编" —— 没有任何成果时
#: 就照实写"尚未取得任何部分结果"，而不是写一句听起来像成果的话。
NO_PROGRESS_NOTE = "尚未取得任何部分结果（预算已用尽，攻坚停在此处；这不是失败，也不是成功）"


def _subgoal(
    sid: str,
    text: str,
    owner: str,
    *,
    status: str = "todo",
    evidence_ids: Sequence[str] = (),
    experiment_ids: Sequence[str] = (),
    proof_experiment_ids: Sequence[str] = (),
    blocked_reason: str = "",
    attempts: int = 0,
    negation_kind: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict:
    """规整一个子目标。所有字段都显式给默认值。

    为什么不用 `dict(raw)` 了事：`AttackPlan.validate` 只在少数几处检查字段，
    其余字段缺失时会在下游（`step` 的分派、`pick_next_subgoal` 的排序）
    以 `KeyError` 或"静默按空值处理"的形式表现。在入口处补齐默认值，
    让"缺字段"变成一个当场可见的形状问题。
    """
    sg = {
        "sid": str(sid),
        "text": str(text),
        "owner": str(owner),
        "status": str(status),
        "evidence_ids": [str(x) for x in evidence_ids],
        "experiment_ids": [str(x) for x in experiment_ids],
        "proof_experiment_ids": [str(x) for x in proof_experiment_ids],
        "blocked_reason": str(blocked_reason),
        "attempts": int(attempts),
        "negation_kind": negation_kind,
    }
    if extra:
        # 额外键（如 `script_path`、`relation_ids`、`topic`）原样保留：
        # 它们是分派动作的参数，schema 不管它们，但它们不能丢。
        for k, v in extra.items():
            if k not in sg:
                sg[k] = v
    return sg


class AgentF:
    """多轮难题攻坚智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`create_plan` —— 立项（预算不完整即拒绝，不写库）；
    - :meth:`step` —— 推进一轮（唯一会改计划的方法）；
    - :meth:`status` / :meth:`list_plans` —— 只读视图。

    构造签名刻意比 A–E 简单（没有 `workspace_root`）：F 自己不跑脚本，
    实验执行是 E 的职责；F 只持有 store 与配置。
    """

    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        log: Any | None = None,
        e: Any | None = None,
        tools: ToolRegistry | None = None,
        actor: str = "agent-F",
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        self.llm = llm
        self.log = log

        # ---- 阈值全部来自 config（与 A–E 的既有做法一致）
        #: 一轮里最多推进几个子目标（瞬时并发，FC-18 的 `max_parallel_subgoals`）。
        #: 默认 1：一次推进多个子目标会让"这一轮发生了什么"变成一串并列事件，
        #: 而 `history` 的用途正是"按顺序把这个难题读一遍"。
        self.max_subgoals_per_round = int(self.cfg.get("max_subgoals_per_round", 1))
        #: A 的检索请求默认 mode（`broad`/`topical`/`precise`）。
        #: 攻坚里的检索请求面向某个具体子目标，因此默认 `precise`
        #: —— 但 `precise` 在 schema 里要求非空 `content_description`，
        #: 所以本模块一定会把子目标文本作为描述带上（见 `_deploy_a`）。
        self.search_mode = str(self.cfg.get("search_mode", "precise"))
        #: 检索请求的优先级。默认 None = 交给冻结契约查表
        #: （`interactions.resolve_priority`，见 `schema.SUBMITTER_DEFAULT_PRIORITY`）。
        #: 查表结果可能是 `"low"`：`"agent-F"` 不在那张表里，于是走
        #: "未登记的提交方一律 low"这条规则。这是契约规定的保守默认，
        #: 不是缺陷；要让 F 的请求排在前面，就在 config 里显式给一个优先级
        #: （那是一个有意的决定，而不是替框架猜）。
        self.search_priority = self.cfg.get("search_priority")
        #: 提交方身份（决定默认优先级）。不用 `actor`：`actor` 是"这次运行的标签"，
        #: `submitted_by` 是"提交方身份"，混用会让运行标签落到"未登记提交方"上，
        #: 默认优先级静默从 medium 掉到 low（C 那边踩过同一个坑）。
        self.submitter = str(self.cfg.get("submitter", "agent-F"))

        #: E 的实例（惰性构造）。注入点存在是有意的：验收测试可以塞一个假的 E，
        #: 而生产路径用真的。`None` 表示"还没构造"，不是"禁用 E"。
        self._e = e

        self.last_step: dict[str, Any] = {}
        self.last_tool_errors: list[dict] = []
        self.tools = tools if tools is not None else install_f_tools(self.store)
        # ---- 绑定角色（`P-14`）：注入的注册表同样要绑（`AgentD` 那条注释同族）。
        if self.tools.bound_role is None:
            self.tools.bound_role = "F"

    # ------------------------------------------------------------ 小工具

    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断攻坚
                pass

    def _stamp(self) -> str:
        return S.now_iso()

    @property
    def e(self) -> Any:
        """E 的惰性实例。

        为什么惰性：E 与 F 是并行开发的两个模块，F 必须能在 E 缺席时被导入、
        自检、跑测试。真正需要时（要跑实验的子目标）才构造 ——
        而如果那时 E 不可用，必须显式失败（见 `_deploy_e`），
        不允许静默跳过（FC-08）。
        """
        if self._e is None:
            from .agent_e import AgentE  # 惰性：agent_e 反过来 import agent_f 的话也不成环

            sub = self.cfg.get("agent_e")
            self._e = AgentE(
                self.store,
                config=dict(sub) if isinstance(sub, Mapping) else {},
                workspace_root=self.cfg.get("workspace_root"),
                log=self.log,
            )
        return self._e

    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 `ToolResult`；失败返回 None 并留痕（同 `AgentD._call`）。"""
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data

    def _plan_row(self, plan_id: str) -> dict | None:
        return next(
            (r for r in self.store.rows("attack_plans") if str(r.get("plan_id")) == str(plan_id)),
            None,
        )

    def _default_budget(self) -> dict:
        """本次运行的默认预算。

        默认值是 `tools/attack_tools.DEFAULT_BUDGET`，但构造时可以按维度覆盖
        （例如 cfg 里给 `max_rounds=3`）。

        为什么要留这个口子：如果 cfg 被悄悄忽略，调用方写 `AgentF(st, config=
        {"max_rounds": 3})` 会得到一个 6 轮的计划 —— 而没有任何地方会报错，
        只是"预算比你说的多了一倍"。这类"配置被静默忽略"是最难发现的一类缺陷，
        所以这里既读 cfg，也在返回值里让调用方看得见实际用了什么。
        """
        out = dict(AT.DEFAULT_BUDGET)
        for k in AT._REQUIRED_BUDGET_KEYS:  # noqa: SLF001 - 同一层内部约定，不另抄一份键名
            if k in self.cfg:
                out[k] = int(self.cfg[k])
        return out

    # ------------------------------------------------------------ [1] 立项

    def create_plan(
        self,
        problem: str,
        problem_key: str,
        *,
        for_question_id: str | None = None,
        subgoals: Sequence[Mapping[str, Any]] | None = None,
        budget: Mapping[str, Any] | None = None,
        depth: int = 0,
        parent_plan_id: str | None = None,
    ) -> dict:
        """为一个难题立项。

        返回 ``{"created", "plan_id", "reason", "duplicate", "status", "budget"}``。

        三条硬规矩：

        1. 预算必须完整（`check_budget`），不完整就拒绝创建 ——
           `budget=None` 表示"没给"，此时用本次运行的默认预算
           （`DEFAULT_BUDGET`，可用构造 config 按维度覆盖，见 `_default_budget`）；
           显式给了一个缺键的 dict 则是"给了但不完整"，拒绝
           （返回 `created=False`，不写库）。这两种情况必须分开，
           否则"我们忘了配预算"会被默认值掩盖。
        2. 同一 `problem_key` 已有未终结的计划 ⇒ 不新建，返回已存在的
           `plan_id`。理由：攻坚是多轮的，而"再立一个项"这个动作看起来
           无害，实际会让同一个难题被并行地攻两遍，两边的 history 各自长，
           谁也看不到对方已经证否的路径。
        3. 子目标必须能被 `AttackPlan.validate` 接受 —— 所以在事务外先建行并
           `validate()`，非法就当场抛，绝不把非法行交给事务。
        """
        default_budget = self._default_budget()
        chk = AT.check_budget(dict(budget) if budget is not None else dict(default_budget))
        if not chk["complete"]:
            return {
                "created": False,
                "plan_id": None,
                "duplicate": False,
                "reason": (
                    f"拒绝创建：{chk['reason']}。"
                    "（预算不完整时不立项，而不是先用默认值把洞补上再跑）"
                ),
                "missing": chk["missing"],
                "budget": dict(budget or {}),
            }

        if not str(problem).strip():
            raise PlanError("problem 不能为空")
        if not str(problem_key).strip():
            raise PlanError("problem_key 不能为空（没有它就无法判重）")

        existing = None
        for r in self.store.rows("attack_plans"):
            if str(r.get("problem_key")) == str(problem_key) and str(r.get("status")) not in TERMINAL_STATUSES:
                existing = r
                break
        if existing is not None:
            return {
                "created": False,
                "plan_id": str(existing.get("plan_id")),
                "duplicate": True,
                "status": existing.get("status"),
                "reason": (
                    f"problem_key={problem_key!r} 已有未终结的计划 {existing.get('plan_id')}"
                    f"（status={existing.get('status')}）⇒ 不新建。"
                    "重复立项会让同一个难题被并行攻两遍，两边的 history 互相看不见"
                ),
            }

        goal_rows = [self._normalize_subgoal(s, i) for i, s in enumerate(subgoals or [])]
        with self.store.tx("attack_plans", actor=self.actor, note="f.create_plan") as tx:
            pid = tx.alloc_id("plan")
            try:
                row = S.AttackPlan(
                    plan_id=pid,
                    problem=str(problem),
                    problem_key=str(problem_key),
                    for_question_id=for_question_id,
                    status="open",
                    rounds=0,
                    budget={k: int(v) for k, v in dict(budget or default_budget).items()},
                    subgoals=goal_rows,
                    history=[],
                    depth=int(depth),
                    parent_plan_id=parent_plan_id,
                    best_partial="",
                    created_at=self._stamp(),
                    updated_at=self._stamp(),
                    created_by=self.actor,
                )
                # 早炸：非法子目标/深度/预算在写入前就会被拒，事务里什么都留不下。
                row.validate()
            except ValueError as e:
                # 不吞异常：这里只是把 `schema` 的 `ValueError` 换成语义正确的
                # `PlanError`（`ToolError` 子类），好让工具层给出
                # `kind="tool_error"` + 具体原因，而不是无声的 `kind="unexpected"`。
                # 失败本身照旧发生、事务照旧回滚 —— 这正是"炸得要响、还要说清为什么"。
                raise PlanError(
                    f"计划参数不合 schema 硬约束（plan 未创建）：{e}。"
                    f"problem_key={problem_key!r}，深度 {depth}，子目标 {len(goal_rows)} 个。"
                    "非法计划不许落库：落进去之后每一轮 step 都会在同一个坏行上再炸一次"
                ) from e
            tx.upsert("attack_plans", row.to_dict(), note=f"create_plan:{problem_key}")

        out = {
            "created": True,
            "plan_id": pid,
            "duplicate": False,
            "status": row.status,
            "budget": dict(row.budget),
            "subgoals": len(row.subgoals),
            "reason": f"已立项 {pid}（深度 {depth}，子目标 {len(row.subgoals)} 个，预算 {row.budget}）",
        }
        self._log(f"plan {pid} created", problem_key=problem_key)
        return out

    @staticmethod
    def _normalize_subgoal(raw: Mapping[str, Any], index: int) -> dict:
        """把一个子目标规整成 `AttackPlan.subgoals` 要求的形状。

        `sid` / `text` / `owner` 缺失时当场抛（带下标），而不是交给 schema
        报一个"subgoals[i] 缺少 sid" —— 两者信息量差不多，但这里的错误可以
        带上调用方给的原始下标，便于定位。
        """
        if not isinstance(raw, Mapping):
            raise PlanError(f"subgoals[{index}] 必须是对象，收到 {type(raw).__name__}")
        sid = str(raw.get("sid") or "").strip()
        text = str(raw.get("text") or "").strip()
        owner = str(raw.get("owner") or "").strip()
        if not sid:
            raise PlanError(f"subgoals[{index}] 缺少 sid")
        if not text:
            raise PlanError(f"subgoals[{index}] 缺少 text（子目标必须说清要做什么）")
        if not owner:
            raise PlanError(f"subgoals[{index}] 缺少 owner（owner 是权限面的一部分，不能默认）")
        return _subgoal(
            sid,
            text,
            owner,
            status=str(raw.get("status") or "todo"),
            evidence_ids=list(raw.get("evidence_ids") or []),
            experiment_ids=list(raw.get("experiment_ids") or []),
            proof_experiment_ids=list(raw.get("proof_experiment_ids") or []),
            blocked_reason=str(raw.get("blocked_reason") or ""),
            attempts=int(raw.get("attempts") or 0),
            negation_kind=raw.get("negation_kind"),
            # 只透传已经规范化过的那九个字段之外的键。
            # 曾经这里是 `{k: v for k, v in raw.items() if k not in {"sid", "text", "owner"}}`
            # —— 于是调用方给的 `status` / `evidence_ids` / `attempts` 覆盖了上面
            # 那几个规范化参数（`_subgoal` 最后才 update extra）。后果是
            # "调用方给什么状态就是什么状态"，`status="todo"` 的默认值形同虚设，
            # 而且缺 `status` 的子目标会原样带着 `None` 落库。这类"参数被后写覆盖"
            # 是纯粹的静默错误：没有异常、没有告警，只有一条形状不对的子目标。
            extra={
                k: v
                for k, v in raw.items()
                if k
                not in {
                    "sid", "text", "owner", "status", "evidence_ids", "experiment_ids",
                    "proof_experiment_ids", "blocked_reason", "attempts", "negation_kind",
                }
            },
        )

    # ------------------------------------------------------------ [2] 推进一轮

    def step(self, plan_id: str) -> dict:
        """推进一轮。

        返回 ``{"plan_id","round","sid","action","outcome","status","budget_left","reason"}``。

        `outcome` 取本模块的 :data:`STEP_OUTCOMES`
        （``no_change`` / ``progress`` / ``blocked``）：它说的是这一轮推进的结果，
        与 `schema.TASK_OUTCOMES`（一次任务的终局）是两套命名空间，不许互相赋值
        —— 裁定依据与后果写在 `STEP_OUTCOMES` 的注释里。写入前会过一次
        :func:`_step_outcome` 的收口，词表外的取值当场炸。

        流程（每一步的理由都写在旁边的注释里）：

        1. 读计划 → 终结状态不再推进（不自动重入）；轮数用尽 ⇒ `stalled` + `best_partial`；
        2. `pick_next_subgoal` 选目标（复用工具层的排序，不另写一套）；
        3. 按 owner 分派（见模块 docstring 的表格）；
        4. 追加一条 history，`rounds += 1`；
        5. 判定计划状态；
        6. 一个事务写回。
        """
        row = self._plan_row(plan_id)
        if row is None:
            raise PlanError(f"攻坚计划 {plan_id} 不存在")

        status = str(row.get("status") or "open")
        budget = dict(row.get("budget") or {})
        rounds = int(row.get("rounds") or 0)
        budget_left = _budget_left(budget, rounds)

        # ---- 终结状态：不再推进（终态先到先得，不许被重入改写）
        if status in TERMINAL_STATUSES:
            return {
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": status,
                "budget_left": budget_left,
                "reason": (
                    f"计划已是终结状态 {status!r} ⇒ 不再推进。"
                    "**「不再推进」不是「推进了但没有进展」**：终态先到先得，"
                    "自动重入会把它当活计划重新拾起，于是终止条件形同虚设"
                ),
            }

        subgoals: list[dict] = [dict(s) for s in (row.get("subgoals") or [])]
        history: list[dict] = [dict(h) for h in (row.get("history") or [])]

        # ---- [1] 轮数用尽 ⇒ stalled + best_partial（必须非空，且必须如实）
        #
        # 在它之前先判一次连续无进展（来自对 dsh 数学模式的观摩）：
        # 那种模式要求"连续 N 轮无进展就提前终止"。我们此前只按 `max_rounds` 停，
        # 而 `history[i]["outcome"] == "no_change"` 这个信号已经被生产出来却无人消费 ——
        # 这正是本项目自己总结过的 P4（"检测到了却没有消费"）的又一处实例。
        # 后果：一个"卡在未接线子目标上"的攻坚计划会把预算完整烧完才停，
        # 而它从第一轮起就不可能再有任何进展。
        stall_after = int(self.cfg.get("stall_after_no_progress_rounds", 3))
        recent = [str(h.get("outcome") or "") for h in (row.get("history") or [])][-stall_after:]
        if stall_after > 0 and len(recent) == stall_after and all(o == "no_change" for o in recent):
            row["status"] = "stalled"
            row["best_partial"] = (
                f"[提前停止] 连续 {stall_after} 轮无进展（全部 outcome=no_change）⇒ 不再烧预算。\n"
                + self._compose_best_partial(subgoals, rounds)
            )
            row["updated_at"] = self._stamp()
            self._write_plan(row, note=f"f.step:stall_after_{stall_after}_no_progress")
            self._log(f"plan {row.get('plan_id')} stalled after {stall_after} no-progress rounds")
            out = {
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stall_detected",
                "outcome": "no_change",
                "status": "stalled",
                "budget_left": _budget_left(budget, rounds),
                "reason": (
                    f"连续 {stall_after} 轮 outcome=no_change ⇒ 提前判 stalled。"
                    "**不是失败，也不是成功**：当前最好的部分结果已写入 best_partial。"
                    "（这个信号此前被生产出来却无人消费 —— 见 LESSONS 的 P4）"
                ),
            }
            self.last_step = out
            return out
        #
        # 这里显式传 depth=0：`can_round` 会同时检查轮数与深度，而"深度到顶"
        # 的后果是"不能再分子问题"，不是"这个计划该停了"。把后者也当成终止判据，
        # 会让一个深度恰好到顶的计划连第一轮都跑不了 —— 那是把"不能再分子问题"
        # 读成了"这个问题不能做"（见 attack_tools 模块 docstring 的同一段说明）。
        if not AT.can_round(budget, rounds_done=rounds, depth=0)["allowed"]:
            row["status"] = "stalled"
            row["best_partial"] = self._compose_best_partial(subgoals, rounds)
            detail = (
                f"轮数已用尽（{rounds}/{budget.get('max_rounds')}）⇒ 停止并交出 best_partial。"
                "**stalled 既不是失败也不是成功**：它表示'预算内没做出来'"
            )
            # 只有还有位子时才追加 history：`AttackPlan.validate` 要求
            # `len(history) <= max_rounds × 子目标数`（"有轮次没被预算约束"的守卫）。
            # 轮数用尽时正好顶到那个上限 —— 再追加一条"停止"记录会违反 schema，
            # 于是这条计划永远写不回去（"说停"本身被 schema 挡住了）。
            # 所以把停止理由记进计划级的 best_partial（它是计划级的交接记录），
            # 而不是挤进已经被预算占满的 history。
            if len(history) < int(budget.get("max_rounds", 0)) * max(1, len(subgoals)):
                history.append(
                    {
                        "round": rounds + 1,
                        "sid": None,
                        "action": "stop",
                        "outcome": "no_change",
                        "detail": detail,
                        "evidence": [],
                        "at": self._stamp(),
                    }
                )
            row["best_partial"] = f"[停止] {detail}\n{row['best_partial']}"
            row["history"] = history
            row["updated_at"] = self._stamp()
            self._write_plan(row, note="f.step:stalled")
            self._log(f"plan {row.get('plan_id')} stalled")
            return {
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": "stalled",
                "budget_left": _budget_left(budget, rounds),
                "best_partial": row["best_partial"],
                "reason": detail,
            }

        # ---- [2] 选子目标（复用 attack_tools.pick_next_subgoal）
        #
        # 先摘掉 `in_flight` 的子目标：它们这一轮已经"交出去等回填"了
        # （A/B 的请求在别人手里，C/D/F 的推理本框架还没接）。
        # 不过滤的话，`pick_next_subgoal` 会一轮又一轮地选中同一个子目标，
        # 于是 history 被同一条事实灌满，而真正待办的子目标永远轮不到。
        # 过滤只影响"这一轮选谁"，不改子目标的状态：它们在表里仍然是 blocked，
        # 卡点仍然对人可见（`blocked_reason` 非空）。
        pickable = [s for s in subgoals if not s.get("in_flight")]
        picked = AT.pick_next_subgoal(pickable)
        if not picked["picked"]:
            # 无可推进的子目标：这在两种情况下发生 —— 全 closed（成功收口）、
            # 或全是 dropped/blocked（需要人来解开卡点）。两者都不该静默变成"没轮次"。
            history.append(
                {
                    "round": rounds + 1,
                    "sid": None,
                    "action": "stop",
                    "outcome": "no_change",
                    "detail": f"没有可推进的子目标：{picked['reason']}",
                    "evidence": [],
                    "at": self._stamp(),
                }
            )
            row["subgoals"] = subgoals
            row["history"] = history
            row["rounds"] = rounds + 1
            row["status"] = self._derive_status(subgoals, row)
            row["updated_at"] = self._stamp()
            row["best_partial"] = self._compose_best_partial(subgoals, rounds + 1)
            self._write_plan(row, note="f.step:no_pickable")
            return {
                "plan_id": row.get("plan_id"),
                "round": rounds + 1,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": row["status"],
                "budget_left": _budget_left(budget, rounds + 1),
                "reason": picked["reason"],
            }

        sg = picked["subgoal"]
        sid = str(sg.get("sid"))

        # ---- [3] 分派
        deploy = self._deploy(sg, plan=row)

        # ---- 把分派结果写回子目标
        if deploy.get("experiment_ids"):
            sg["experiment_ids"] = sorted(set(list(sg.get("experiment_ids") or []) + list(deploy["experiment_ids"])))
        if deploy.get("proof_experiment_ids"):
            sg["proof_experiment_ids"] = sorted(
                set(list(sg.get("proof_experiment_ids") or []) + list(deploy["proof_experiment_ids"]))
            )
        if deploy.get("evidence_ids"):
            sg["evidence_ids"] = sorted(set(list(sg.get("evidence_ids") or []) + list(deploy["evidence_ids"])))
        if deploy.get("negation_kind") is not None:
            sg["negation_kind"] = deploy["negation_kind"]
        if deploy.get("status"):
            sg["status"] = deploy["status"]
        if deploy.get("blocked_reason"):
            sg["blocked_reason"] = deploy["blocked_reason"]
        if deploy.get("in_flight") is not None:
            sg["in_flight"] = bool(deploy["in_flight"])
        sg["attempts"] = int(sg.get("attempts") or 0) + (1 if deploy.get("count_attempt") else 0)

        history.append(
            {
                "round": rounds + 1,
                "sid": sid,
                "action": deploy["action"],
                # 收口到 `STEP_OUTCOMES`（`G-24②`）：词表外的取值在写入前就炸，
                # 而不是原样落进 history（那里它会让停滞检测静默失效）。
                "outcome": _step_outcome(deploy["outcome"]),
                "detail": deploy["detail"],
                "evidence": list(deploy.get("evidence") or []),
                "at": self._stamp(),
            }
        )
        row["subgoals"] = subgoals
        row["history"] = history
        row["rounds"] = rounds + 1
        row["status"] = self._derive_status(subgoals, row)
        row["updated_at"] = self._stamp()
        row["best_partial"] = self._compose_best_partial(subgoals, rounds + 1)
        if row["status"] == "stalled" and not str(row["best_partial"]).strip():
            row["best_partial"] = NO_PROGRESS_NOTE
        self._write_plan(row, note=f"f.step:{deploy['action']}")

        out = {
            "plan_id": row.get("plan_id"),
            "round": rounds + 1,
            "sid": sid,
            "action": deploy["action"],
            "outcome": _step_outcome(deploy["outcome"]),
            "status": row["status"],
            "budget_left": _budget_left(budget, rounds + 1),
            "reason": deploy["detail"],
        }
        self.last_step = out
        return out

    # ------------------------------------------------------------ 分派

    def _deploy(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """按 `owner` 分派一个动作。只做框架内真实存在的事。

        返回统一的动作描述 ``{action, outcome, detail, evidence, status?,
        experiment_ids?, proof_experiment_ids?, negation_kind?, blocked_reason?,
        count_attempt}``，由 `step` 负责写回子目标与 history。
        """
        owner = str(sg.get("owner") or "")
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")

        if owner == "E":
            return self._deploy_e(sg, plan=plan)
        if owner == "A":
            return self._deploy_a(sg, plan=plan)
        if owner == "B":
            return self._deploy_b(sg, plan=plan)
        if owner in UNWIRED_OWNERS:
            # 不允许把"没做"写成"做了但没结果"。
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid}（{text}）需要 {owner} 的推理，但**本框架尚未接线自动推理** "
                    f"⇒ **未推进**（这一轮什么都没做，不是'做了但没结果'）。"
                    f"要把 owner={owner} 的子目标真正推起来，需要 {owner} 侧先接上可调用的推理入口；"
                    "在此之前 F 只如实记账，绝不用空证据冒充进展"
                ),
                "evidence": [],
                # 标 `blocked` 而不是 `in_progress` 是刻意的：`in_progress` 会被
                # `pick_next_subgoal` 排在最前，于是接下来每一轮都会重新选中它、
                # 每一轮都记一次"未推进"，把 history 灌满。`blocked` 排在最后，
                # 且必须给出 blocked_reason —— 这正是"不许静默卡住"要求的形态。
                "status": "blocked",
                "blocked_reason": f"未接线：本框架尚无可自动调用的 {owner} 侧推理入口",
                # `in_flight` = "这一轮之后没有新事情可做，别再自动重试它"。
                # 它与 `status="blocked"` 是两件事：schema 的 blocked 说的是
                # "卡住了，必须有人来解"（必须留在表里、必须能被人看见），
                # 而 `in_flight` 只是 `step` 的选目标过滤器：没有它，下一轮
                # 又会选中同一个子目标、又记一次"未推进"，history 会被灌满
                # 而同一条事实重复 N 遍。
                "in_flight": True,
                "count_attempt": False,
            }
        raise PlanError(
            f"子目标 {sid} 的 owner={owner!r} 不在 {S.SUBGOAL_OWNERS} 里。"
            "owner 是权限面的一部分，拼错会让子目标派给不存在的人"
        )

    def _deploy_e(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """E 的子目标：跑实验并登记。

        幂等：如果这个子目标已经跑过实验（`experiment_ids` 非空），不重跑。
        为什么必须幂等：每一轮重跑同一个脚本会让 experiments 表堆满重复记录、
        `attempts` 虚高，而"这条子目标到底试过几次"就再也答不上来了。
        要重跑必须由人显式清空 `experiment_ids`（那是一个有意的动作）。
        """
        sid = str(sg.get("sid") or "")
        claimed = sorted(set(list(sg.get("experiment_ids") or []) + list(sg.get("proof_experiment_ids") or [])))
        if claimed:
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 已有实验记录 {claimed} ⇒ 本轮**不重复执行**"
                    "（重复登记会让 experiments 表堆满同一件事，attempts 虚高）"
                ),
                "evidence": claimed,
                "status": None,
                "count_attempt": False,
            }

        script_path = str(sg.get("script_path") or "").strip()
        if not script_path:
            # 这不是失败，是我没法做：缺执行参数。如实记，并让子目标保持在
            # 可重试位置（下一次有人补上 script_path 就能跑）。
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 E，但没有给 `script_path` ⇒ **未推进**"
                    "（没有脚本就没有实验可跑；这不是'跑了但没结果'）"
                ),
                "evidence": [],
                "status": "todo",
                "count_attempt": False,
            }

        try:
            agent_e = self.e
        except Exception as ex:  # noqa: BLE001 - E 不可用时必须显式失败，不许静默跳过
            return {
                "action": "no_change",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 E，但 E **不可用**（{type(ex).__name__}: {ex}）⇒ **未推进**。"
                    "未接线/不可用必须是显式事实，不许静默降级为空"
                ),
                "evidence": [],
                "status": "in_progress",
                "blocked_reason": f"E 不可用：{type(ex).__name__}: {ex}",
                "count_attempt": False,
            }

        # E 执行失败必须被降级成"这一轮卡住了"，而不是让整个攻坚炸掉。
        #
        # 实测过这个缺口：子目标引用的脚本不存在时，`run_experiment` 抛
        # `ExperimentError`，它一路穿过 `_deploy_e` → `step` → 调用方，
        # 于是一个缺失的脚本文件会中止整个攻坚循环，连其它子目标都没机会跑。
        # 这与 FC-21（部分失败语义）冲突：子任务可以降级，但整体绝不谎报成功。
        #
        # 所以这里把它记成 `outcome="blocked"` + `status="blocked"` + `blocked_reason`：
        # 事实完整保留（E 的原始错误文本在 detail 里），子目标留在表里等人来解，
        # 而其它子目标继续跑。注意这不是"成功降级为无害" ——
        # `blocked` 会让计划永远无法标 `resolved`（除非有人把 proof 级证据补上）。
        try:
            res = agent_e.run_experiment(
                str(sg.get("claim") or sg.get("text") or ""),
                str(sg.get("claim_key") or f"{plan.get('problem_key')}#{sid}"),
                script_path,
                params=dict(sg.get("params") or {}) or None,
                method=str(sg.get("method") or "numeric"),
                for_question_id=plan.get("for_question_id"),
                timeout=int(sg.get("timeout") or self.cfg.get("timeout", 600)),
                # `P-8`：形式化子目标要把"核哪个声明、加载哪些库"传下去 ——
                # 不传的话 E 只能用文件名词干 + 检查器默认库，而"库不可得"
                # （`import_unavailable`）会让这次检查根本没发生 ⇒ 永远拿不到 proof。
                # 两个键对计算类子目标不存在（取到 None），E 那一侧因此不会拒绝。
                name=sg.get("name"),
                imports=sg.get("imports"),
            )
        except Exception as ex:  # noqa: BLE001 - 任何 E 侧失败都降级为 blocked，不中止攻坚
            return {
                "action": "experiment_failed",
                "outcome": "blocked",
                "detail": (
                    f"子目标 {sid} 的实验**执行失败**：{type(ex).__name__}: {ex}"
                    f"（脚本 {script_path!r}）。已如实记为 blocked 并保留错误原文；"
                    "**其它子目标继续推进**，但本计划在这一点解决前不可能标记为 resolved"
                ),
                "evidence": [],
                "status": "blocked",
                "blocked_reason": f"实验执行失败：{type(ex).__name__}: {ex}",
                "count_attempt": True,
            }
        eid = str(res.get("experiment_id"))
        kind = str(res.get("evidence_kind"))
        result = str(res.get("result"))
        if kind == "proof":
            # 只有 proof 级证据才允许关闭子目标（FC-22）。E 只有在
            # method="formal" 且拿到检查器输出时才会给出这个等级。
            return {
                "action": "run_experiment",
                "outcome": "progress",
                "detail": (
                    f"实验 {eid}：result={result}，evidence_kind=proof ⇒ 子目标 {sid} 可关闭"
                ),
                "evidence": [eid],
                "experiment_ids": [eid],
                "proof_experiment_ids": [eid],
                "status": "closed",
                "negation_kind": res.get("negation_kind"),
                "count_attempt": True,
            }
        if result == "supports":
            # 数值/穷举支持只能标 supported_not_proved，不能标 closed。
            return {
                "action": "run_experiment",
                "outcome": "progress",
                "detail": (
                    f"实验 {eid}：result=supports，evidence_kind={kind} ⇒ 子目标 {sid} 标 "
                    "supported_not_proved（**数值支持不是证明**，FC-22）"
                ),
                "evidence": [eid],
                "experiment_ids": [eid],
                "status": "supported_not_proved",
                "negation_kind": res.get("negation_kind") or "not_proved",
                "count_attempt": True,
            }
        return {
            "action": "run_experiment",
            "outcome": "no_change",
            "detail": (
                f"实验 {eid}：result={result}（negation_kind={res.get('negation_kind')}，"
                f"exit_code={res.get('exit_code')}）⇒ 子目标 {sid} **未取得可判定结论**，"
                "保持 in_progress（崩溃/无结论不得被写成支持）"
            ),
            "evidence": [eid],
            "experiment_ids": [eid],
            "status": "in_progress",
            "negation_kind": res.get("negation_kind") or "no_local_evidence",
            "count_attempt": True,
        }

    def _deploy_a(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """A 的子目标：过 I7 闸门后提交一条 `search_requests`（同一事务）。"""
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")
        topic = str(sg.get("topic") or text).strip()
        mode = str(sg.get("mode") or self.search_mode)
        if mode not in S.SEARCH_MODES:
            raise PlanError(f"子目标 {sid} 的 mode={mode!r} 不在 {S.SEARCH_MODES} 里")
        if mode == "precise" and not text:
            raise PlanError(f"子目标 {sid} 是 precise 检索但没有文本可作 content_description")
        if not topic:
            raise PlanError(f"子目标 {sid} 没有 topic（空 topic 会让检索无从构造）")

        with self.store.tx("search_requests", actor=self.actor, note="f.step:submit_search") as tx:
            rows = tx.rows("search_requests")
            gate = IX.admit_search_request(
                rows,
                submitted_by=self.submitter,
                explicit_priority=self.search_priority,
                for_question_id=plan.get("for_question_id"),
                max_inflight=self.cfg.get("max_inflight_requests"),
            )
            if not gate["admitted"]:
                # 闸门拒绝 ⇒ 不产生任何写入（这是 I7 的全部意义：显式拒绝把压力
                # 传导回提交方，而不是无限排队把 A 的产能摊薄）
                return {
                    "action": "submit_search_request",
                    "outcome": "no_change",
                    "detail": f"检索请求被闸门拒绝（**未提交任何请求**）：{gate['reason']}",
                    "evidence": [],
                    "status": "blocked",
                    "blocked_reason": gate["reason"],
                    # 闸门拒绝也标 in_flight：再试一次会得到同一个答案
                    # （在途数没有变），重复提交只会重复消耗同一份拒绝理由。
                    "in_flight": True,
                    "count_attempt": False,
                }
            # `prefix` 只给 `"r"`：`IX.next_prefixed_id` 自己会补上连接号
            # （`f"{prefix}-{n:04d}"`）。传 `"r-"` 会得到 `"r--0001"` —— 而它
            # 恰好还能通过 `SearchRequest.validate`（那条只查非空），
            # 于是会静默写进表里、下一轮取号又认不出来（前缀匹配不上），
            # 每次都重新从 1 开始找，很快撞上已占用的号。属"看起来能用"的静默缺陷。
            req_id = IX.next_prefixed_id(rows, "request_id", "r")
            req = S.SearchRequest(
                request_id=req_id,
                timestamp=self._stamp(),
                topic=topic,
                mode=mode,  # type: ignore[arg-type]
                content_description=text,
                done=False,
                submitted_by=self.submitter,
                priority=gate["priority"],
                for_question_id=plan.get("for_question_id"),
                submit_note=f"agent-F 攻坚计划 {plan.get('plan_id')} 子目标 {sid}：{text}",
            )
            req.validate()
            tx.upsert("search_requests", req.to_dict(), note=f"f.step:{sid}")
        return {
            "action": "submit_search_request",
            "outcome": "progress",
            "detail": (
                f"已向 A 提交检索请求 {req_id}（priority={gate['priority']}，mode={mode}）"
                f"⇒ 子目标 {sid} 转 in_progress 并等 A 的回填（**在这一轮里它还没有证据**）"
            ),
            "evidence": [req_id],
            # `evidence` 与 `evidence_ids` 是两个不同的落点，不能省掉任何一个：
            # `evidence` 进 history 的当轮记录（"这一轮依据/产生了什么"），
            # `evidence_ids` 进子目标（"这条子目标攒到了哪些证据"）。
            # 只写前者会让子目标看起来"一条证据都没有过" —— 而复用同一个键
            # 又会让两处的语义漂移。
            "evidence_ids": [req_id],
            "status": "in_progress",
            "blocked_reason": f"等 A 完成检索请求 {req_id}",
            # 派给 A 之后这一轮就没别的事可做了：请求在 A 手里，结果不会
            # 在同一个 step 里回来。不标 in_flight 的话，下一轮会再次选中同一个
            # 子目标、再提交一条请求 —— 那是把"等回填"变成了"每轮重发"。
            "in_flight": True,
            "count_attempt": True,
        }

    def _deploy_b(self, sg: Mapping[str, Any], *, plan: Mapping[str, Any]) -> dict:
        """B 的子目标：过 I4 闸门后提交一条 `reprocess_requests`。"""
        sid = str(sg.get("sid") or "")
        text = str(sg.get("text") or "")
        rids = sorted({str(x) for x in (sg.get("relation_ids") or []) if x})
        reason = str(sg.get("reason") or self.cfg.get("reprocess_reason") or "need_context")
        if not rids:
            # 无目标的重抽取会退化成全量重抽（I4 的幂等陷阱），所以这里必须拦住。
            return {
                "action": "submit_reprocess_request",
                "outcome": "no_change",
                "detail": (
                    f"子目标 {sid} 派给 B，但没有给 `relation_ids` ⇒ **未推进**"
                    "（无目标的重抽取会退化成全量重抽，是 I4 明令禁止的）"
                ),
                "evidence": [],
                "status": "todo",
                "count_attempt": False,
            }
        with self.store.tx("reprocess_requests", actor=self.actor, note="f.step:submit_reprocess") as tx:
            rows = tx.rows("reprocess_requests")
            gate = IX.admit_reprocess_request(
                rows,
                relation_ids=rids,
                reason=reason,
                max_per_relation=self.cfg.get("max_reprocess_per_relation"),
            )
            if not gate["admitted"]:
                return {
                    "action": "submit_reprocess_request",
                    "outcome": "no_change",
                    "detail": f"重抽取请求被闸门拒绝（**未提交**）：{gate['reason']}",
                    "evidence": [],
                    "status": "blocked",
                    "blocked_reason": gate["reason"],
                    "in_flight": True,
                    "count_attempt": False,
                }
            # 同 A：prefix 只给 `"p"`（函数自己补连接号）
            rid = IX.next_prefixed_id(rows, "reprocess_id", "p")
            req = S.ReprocessRequest(
                reprocess_id=rid,
                timestamp=self._stamp(),
                reason=reason,
                submitted_by=self.submitter,
                relation_ids=rids,
                detail=f"agent-F 攻坚计划 {plan.get('plan_id')} 子目标 {sid}：{text}",
                status="pending",
            )
            req.validate()
            tx.upsert("reprocess_requests", req.to_dict(), note=f"f.step:{sid}")
        return {
            "action": "submit_reprocess_request",
            "outcome": "progress",
            "detail": (
                f"已提交重抽取请求 {rid}（reason={reason}，目标关系 {rids}）"
                f"⇒ 子目标 {sid} 转 in_progress 并等 B 处理"
            ),
            "evidence": [rid],
            "evidence_ids": [rid],  # 见 `_deploy_a` 里对这两个键的说明
            "status": "in_progress",
            "blocked_reason": f"等 B 处理重抽取请求 {rid}",
            # 同 A：请求已经交出去了，本轮到此为止（见 `_deploy_a` 的说明）。
            "in_flight": True,
            "count_attempt": True,
        }

    # ------------------------------------------------------------ 计划状态

    def _derive_status(self, subgoals: Sequence[Mapping[str, Any]], row: Mapping[str, Any]) -> str:
        """按子目标的状态推导计划状态（FC-22 / FC-25 的落地）。"""
        if not subgoals:
            # 空计划：没有待办也没有证据。这与"全部 closed"在字面上true，
            # 但在语义上是"这个计划什么都没做" —— 所以不当成 resolved。
            return str(row.get("status") or "open")

        statuses = [str(s.get("status") or "") for s in subgoals]
        if all(st == "closed" for st in statuses):
            return "resolved"

        proof_ids = {str(x) for s in subgoals for x in (s.get("proof_experiment_ids") or [])}
        if all(st in ("closed", "supported_not_proved") for st in statuses):
            if not proof_ids:
                # 关键一分：子目标都有数值支持，但一条 proof 级证据都没有。
                # 这时若返回 resolved 就是把 cross_check 当成了证明（FC-22 要防的正是这件事）。
                return "supported_not_proved"
            return "resolved"
        return "attacking"

    def _compose_best_partial(self, subgoals: Sequence[Mapping[str, Any]], rounds: int) -> str:
        """由各子目标的实际进展合成一段 `best_partial`。

        它必须如实：有进展就写清进展落在哪个子目标上（带实验/请求代号），
        什么都还没有就写 :data:`NO_PROGRESS_NOTE`。编一句听起来像成果的话，
        比留空更坏 —— 因为留空至少 schema 会拦，编的话没人拦得住。
        """
        if not subgoals:
            return NO_PROGRESS_NOTE

        def brief(s: Mapping[str, Any]) -> str:
            bits = [f"{s.get('sid')}（owner={s.get('owner')}，status={s.get('status')}）: {s.get('text')}"]
            if s.get("proof_experiment_ids"):
                bits.append(f"proof 级实验 {s['proof_experiment_ids']}")
            elif s.get("experiment_ids"):
                bits.append(f"实验 {s['experiment_ids']}（**仅交叉验证，不构成证明**）")
            if s.get("evidence_ids"):
                bits.append(f"证据 {s['evidence_ids']}")
            if s.get("blocked_reason"):
                bits.append(f"卡点：{s['blocked_reason']}")
            return "；".join(bits)

        ranked = sorted(
            subgoals,
            key=lambda s: (
                {"closed": 0, "supported_not_proved": 1, "in_progress": 2, "todo": 3, "blocked": 4, "dropped": 5}.get(
                    str(s.get("status") or ""), 9
                ),
                str(s.get("sid") or ""),
            ),
        )
        parts = [f"已进行 {rounds} 轮。子目标进展（按'离终结有多近'排序）："]
        parts += [f"- {brief(s)}" for s in ranked]
        parts.append("**以上均为过程记录**：标了 supported_not_proved 或只有 experiment_ids 的条目都还不是证明。")
        return "\n".join(parts)

    def _write_plan(self, row: Mapping[str, Any], *, note: str) -> None:
        """写回计划（一个事务）。校验在写入前完成，非法即炸（不吞异常）。

        `schema` 抛的 `ValueError` 在这里被换成语义正确的 `PlanError`
        （`ToolError` 子类）—— 见 `PlanError` 的 docstring：这不是"吞掉"，
        是让工具层拿到 `kind="tool_error"` 与具体原因，而不是无声的
        `kind="unexpected"`。异常照旧冒泡，写入照旧不发生。
        """
        try:
            obj = S.row_from_dict("attack_plans", dict(row))
            if obj.status == "stalled" and not str(obj.best_partial).strip():
                obj.best_partial = NO_PROGRESS_NOTE
            obj.validate()
        except ValueError as e:
            raise PlanError(
                f"计划 {row.get('plan_id')!r} 的写回内容不合 schema 硬约束 ⇒ **未写回**：{e}"
            ) from e
        with self.store.tx("attack_plans", actor=self.actor, note=note) as tx:
            tx.upsert("attack_plans", obj.to_dict(), note=note)

    # ------------------------------------------------------------ [3] 只读视图

    def status(self, plan_id: str) -> dict:
        """一个计划的完整可读视图：子目标状态计数、预算余量、history 尾部。"""
        row = self._plan_row(plan_id)
        if row is None:
            return {
                "checked": False,
                "plan_id": plan_id,
                "reason": f"计划 {plan_id} 不存在 ⇒ **没查**（不是'查了、没有内容'）",
            }
        subgoals = [dict(s) for s in (row.get("subgoals") or [])]
        counts: dict[str, int] = {}
        for s in subgoals:
            st = str(s.get("status") or "")
            counts[st] = counts.get(st, 0) + 1
        budget = dict(row.get("budget") or {})
        rounds = int(row.get("rounds") or 0)
        tail_n = int(self.cfg.get("history_tail", 5))
        # ---- `R-53`（`draft/28` §158）：查出陈话卡点。
        #
        # F 的推进是拉取式的：子目标在 A 的回答落地后要再派一次 `F.step` 才推进。
        # M 一停手，子目标就永久停在 `in_flight`，而 `blocked_reason` 还写着
        # "等 A 完成检索请求 r-0019" —— 实测那两个请求早已 `done/ok`（§154 的 A5）。
        # 这里在只读视图里对当前状态重算一次：请求已终结 ⇒ 把这句"等"标成已过期，
        # 并逐条列进 `stale_blocked`（不隐藏、也不改写盘上那一行 —— 历史不改写）。
        # ---- `R-61`（`draft/28` §163）：陈话还得分新旧 —— 只读地从 `history` 反推
        #
        # `stale_blocked` 原来只答"是不是陈话"，不答"陈了多久"，于是读者分不出
        # "我刚停手 1 分钟"与"这个卡点停了 3 天" —— 而在拉取式推进下，"停了多久"
        # 恰恰是唯一能用来排队的量。
        #
        # 前置查证（`temp/_r61_recon.py`，只读 p2-review）：`history` 的条目里记了 `sid`
        # （键并集 = `action/at/detail/evidence/outcome/round/sid`）⇒ 这条只读路成立，
        # 不必给子目标加 `last_pushed_at`（那是 schema 变更，属禁改区）。
        # 取"该 sid 的最后一次触碰"：按 `at` 最大，`at` 缺省时退回最大 `round`；
        # 一条都没有 ⇒ 如实留空（不编一个时间出来）。
        last_touch: dict[str, dict] = {}
        for entry in (row.get("history") or []):
            sid = str(entry.get("sid") or "")
            if not sid:
                continue
            at = str(entry.get("at") or "")
            try:
                rnd = int(entry.get("round") or 0)
            except (TypeError, ValueError):
                rnd = 0
            prev = last_touch.get(sid)
            if prev is None or (at, rnd) >= (str(prev.get("at") or ""), int(prev.get("round") or 0)):
                last_touch[sid] = {"at": at, "round": rnd}
        req_state = {str(x.get("request_id")): str(x.get("outcome") or "")
                     for x in self.store.rows("search_requests")}
        stale_blocked: list[dict] = []
        for s in subgoals:
            reason = str(s.get("blocked_reason") or "")
            ids = sorted(set(re.findall(r"\br-\d{4}\b", reason)))
            if not ids:
                continue
            # 判据是"已终结"，不是"成功了"：`search_failed` / `gave_up` 同样意味着
            # "等 A 完成"这句话已经过期（A 完成了，只是失败）—— 那更该露出来。
            # 取值域直接读 `S.SEARCH_OUTCOMES`，不另抄一份（抄一份就会与 schema 漂移）。
            ended = [i for i in ids if req_state.get(i, "") in S.SEARCH_OUTCOMES]
            if ended and len(ended) == len(ids):
                s["blocked_stale"] = True
                touch = last_touch.get(str(s.get("sid") or ""))
                # `R-61`：把"最后一次被触碰"也放进只读视图（不改盘上那一行）
                s["last_touched_at"] = str((touch or {}).get("at") or "")
                s["last_touched_round"] = (touch or {}).get("round")
                hint = (
                    f"；该子目标最后一次被触碰是第 {touch['round']} 轮（{touch['at']}）"
                    "⇒ 从那以后没有人再推进" if touch else
                    "；`history` 里查不到这个子目标的触碰记录 ⇒ **它从立项起就没动过**"
                )
                s["blocked_reason"] = (
                    f"{reason}（**已过期**：{ended} 已经结束 —— 现在的卡点是"
                    f"『没有人再推进一步』，不是『还在等』{hint}）"
                )
                stale_blocked.append({"sid": s.get("sid"), "requests": ended,
                                      "last_touched_at": str((touch or {}).get("at") or ""),
                                      "last_touched_round": (touch or {}).get("round")})
        return {
            "checked": True,
            "plan_id": row.get("plan_id"),
            "problem": row.get("problem"),
            "problem_key": row.get("problem_key"),
            "for_question_id": row.get("for_question_id"),
            "status": row.get("status"),
            "rounds": rounds,
            "budget": budget,
            "budget_left": _budget_left(budget, rounds),
            "depth": row.get("depth"),
            "parent_plan_id": row.get("parent_plan_id"),
            "subgoals": subgoals,
            "subgoal_counts": counts,
            "stale_blocked": stale_blocked,
            "best_partial": row.get("best_partial") or "",
            "history_len": len(row.get("history") or []),
            "history_tail": list(row.get("history") or [])[-max(0, tail_n) :],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "reason": f"计划 {row.get('plan_id')} 当前 status={row.get('status')}，已 {rounds} 轮",
        }

    def list_plans(self, *, problem_key: str | None = None, include_terminal: bool | None = True) -> dict:
        """列出攻坚计划。`include_terminal=False` 只给"还活着的"计划。

        ## 为什么参数收 `None`，以及为什么 `None` 必须等于 `True`

        `attack.list_plans` 的 schema 把 `include_terminal` 声明成
        ``{"type": "boolean"}``，默认值是 `True`（`attack_tools.py` 的 handler）。
        但 JSON 里的 `null` 会通过参数校验（`base.validate_params` 对 `None`
        跳过类型检查），于是"模型明确写了个 null"和"模型没给这个键"是两条不同的
        输入路径，而省略键得到 `True`。

        修之前这里是 `if not include_terminal:`：`not None is True` ⇒ 显式 `null`
        被静默当成 `False`，与声明的默认值正好相反。同一个意图（"我没有偏好"）
        在两条输入路径上给出相反的答案，而且不报错、不留痕 —— 这是本项目最忌讳的
        "把'没给'折叠成'给了 False'"。所以这里把 `None` 显式解读为声明的默认值，
        让"省略"与"显式 null"重新一致；要过滤终局计划必须明确写 `False`。
        """
        if include_terminal is None:
            include_terminal = True
        rows = [r for r in self.store.rows("attack_plans") if problem_key is None or r.get("problem_key") == problem_key]
        rows.sort(key=lambda r: str(r.get("plan_id") or ""))
        if not include_terminal:
            rows = [r for r in rows if str(r.get("status")) not in TERMINAL_STATUSES]
        return {
            "checked": True,
            "total": len(rows),
            "plans": [
                {
                    "plan_id": r.get("plan_id"),
                    "problem_key": r.get("problem_key"),
                    "status": r.get("status"),
                    "rounds": r.get("rounds"),
                    "max_rounds": (r.get("budget") or {}).get("max_rounds"),
                    "subgoals": len(r.get("subgoals") or []),
                    "depth": r.get("depth"),
                }
                for r in rows
            ],
            "reason": f"共 {len(rows)} 个计划（include_terminal={include_terminal}）",
        }


def _budget_left(budget: Mapping[str, Any], rounds: int) -> dict:
    """预算余量。四类键都给，缺的那类如实标 None。"""
    out: dict[str, Any] = {}
    out["max_rounds_left"] = (int(budget["max_rounds"]) - rounds) if "max_rounds" in budget else None
    out["max_parallel_subgoals"] = budget.get("max_parallel_subgoals")
    out["max_persist_attempts"] = budget.get("max_persist_attempts")
    out["max_depth"] = budget.get("max_depth")
    return out


def install_f_tools(store: Store, *, registry: ToolRegistry | None = None) -> ToolRegistry:
    """装配 F 的工具栏（`attack.*`）。写入逻辑只有一份（见 `attack_tools` 的 docstring）。"""
    reg = registry if registry is not None else ToolRegistry(name="agent-F")
    AT.register(reg, store=store)
    # 绑定角色（`P-14`）：这张注册表代表 F。F 是 `attack.*` 的唯一写侧主人
    # （`_WRITE_ROLES = ("F",)`），而读侧还有 D/G/H —— 所以"代表 F"必须显式写下来，
    # 否则 `AgentF._call` 的每次调用都会因为"调用方没有声明角色"被拒。
    if reg.bound_role is None:
        reg.bound_role = "F"
    return reg


def _short(text: Any, width: int = 90) -> str:
    """单行化 + 截断。自检输出用（与 `agent_d._digest` 同形）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回失败数。

    运行方式::

        cd D:\\Incubator\\test\\test1\\src
        $env:PYTHONIOENCODING='utf-8'; python -m agentflow.agent_f

    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：

    1. 立项：预算完整才成功；缺键不写库；
    2. 同一 problem_key 第二次不新建（避免同一难题被并行攻两遍）；
    3. 分派：E 真的跑实验、A 真的写检索请求、C/D/F 如实记 no_change；
    4. 终止性：轮数用尽即 stalled + best_partial 非空，且恰好 max_rounds 轮；
    5. FC-22：数值证据不得关闭子目标；
    6. 工具层的 `attack.*` 与 `AgentF` 方法口径一致。
    """
    import sys as _sys
    import tempfile

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        okk = bool(cond)
        if not okk:
            failures += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agentf-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    # 一个"总是给出数值支持"的脚本：
    (root / "probe.py").write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check',"
        "'observations':{'n':10},'counterexample':None,'negation_kind':'not_proved'}))\n",
        encoding="utf-8",
    )

    f = AgentF(st, config={"workspace_root": root})
    print(f"[1] 工具栏：{f.tools.names()}")

    # ---- 1. 预算不完整 ⇒ 不创建
    bad = dict(AT.DEFAULT_BUDGET)
    bad.pop("max_depth")
    r_bad = f.create_plan("难题甲", "P-bad", budget=bad)
    print(f"[2] 缺 max_depth 的预算 ⇒ created={r_bad['created']} missing={r_bad.get('missing')}")
    check("预算缺键 ⇒ created=False", r_bad["created"] is False)
    check("预算缺键 ⇒ 一行都没写", st.rows("attack_plans") == [])

    # ---- 2. 正向立项
    r1 = f.create_plan(
        "证明 Spec K(m)=[-m,m]",
        "P-1",
        subgoals=[
            {"sid": "s1", "text": "数值验证 m<=32", "owner": "E", "script_path": "probe.py",
             "claim": "SpecK(m)=[-m,m]", "claim_key": "P-1#s1"},
            {"sid": "s2", "text": "查文献中的谱刻画", "owner": "A", "topic": "spectrum of K(m)"},
            {"sid": "s3", "text": "需要 D 做结构化推理", "owner": "D"},
        ],
    )
    print(f"[3] 立项 ⇒ {r1}")
    check("完整预算 ⇒ created=True", r1["created"] is True)
    check("plan_id 是 4 位十进制", len(str(r1["plan_id"])) == 4 and str(r1["plan_id"]).isdigit())

    r_dup = f.create_plan("同一个难题再来一次", "P-1")
    print(f"[4] 同 problem_key 再立项 ⇒ {r_dup['reason']}")
    check("同 problem_key ⇒ 不新建，返回已有 plan_id",
          r_dup["created"] is False and r_dup["plan_id"] == r1["plan_id"])
    check("attack_plans 仍只有一行", len(st.rows("attack_plans")) == 1)

    # ---- 3. 分派
    pid = r1["plan_id"]
    s1 = f.step(pid)
    print(f"[5] step#1 ⇒ action={s1['action']} outcome={s1['outcome']} sid={s1['sid']} status={s1['status']}")
    check("第一轮派给 E 并跑出实验", s1["action"] == "run_experiment" and s1["outcome"] == "progress")
    row = f.status(pid)
    s1sg = next(s for s in row["subgoals"] if s["sid"] == "s1")
    check("E 子目标拿到 experiment_id", bool(s1sg["experiment_ids"]))
    check("数值实验**不许**关闭子目标（FC-22）",
          s1sg["status"] == "supported_not_proved" and s1sg["proof_experiment_ids"] == [])
    check("计划状态随之变成 supported_not_proved（无任何 proof）", row["status"] == "attacking")

    s2 = f.step(pid)
    print(f"[6] step#2 ⇒ action={s2['action']} outcome={s2['outcome']} sid={s2['sid']}")
    check("第二轮派给 A 并写出检索请求",
          s2["action"] == "submit_search_request" and len(st.rows("search_requests")) == 1)

    s3 = f.step(pid)
    print(f"[7] step#3 ⇒ action={s3['action']} outcome={s3['outcome']} sid={s3['sid']}")
    check("D 的子目标如实记 no_change", s3["action"] == "no_change" and s3["outcome"] == "no_change")
    check("detail 明说'未推进'", "未推进" in s3["reason"])
    _s3 = next(s for s in f.status(pid)["subgoals"] if s["sid"] == "s3")
    check("没有伪造任何证据", _s3["evidence_ids"] == [])
    check("卡点写进 blocked_reason（不许静默卡住）", bool(str(_s3["blocked_reason"]).strip()))
    check("同一未接线子目标不会被反复重选（in_flight 过滤）", f.step(pid)["sid"] is None)

    # ---- 4. 终止性：两条路径都要能到 stalled
    #
    # (a) 预算内出现连续无进展 ⇒ 提前停止（新加，来自对本地先例 dsh 数学模式的观摩：
    #     那个模式要求"连续 N 轮无进展就终止"。我们此前只按 `max_rounds` 停，
    #     而 `history[i]["outcome"]=="no_change"` 这个信号已经生产出来却无人消费，
    #     正是本项目自己总结的 P4「检测到了却没有消费」的又一处实例）。
    # (b) 轮数用尽 ⇒ 强制停止。
    #
    # 这里不再断言 "rounds 恰好 == max_rounds"：那等于把"一定要把预算烧完"
    # 写成不变量，而"烧完预算"恰恰是 (a) 要避免的事。改成断言"停下来了 + 停在哪条路径上写清楚了"。
    max_rounds = AT.DEFAULT_BUDGET["max_rounds"]
    for _ in range(max_rounds + 2):
        last = f.step(pid)
        if last["status"] == "stalled":
            break
    st_row = f.status(pid)
    print(f"[8] 终止 ⇒ status={st_row['status']} rounds={st_row['rounds']} "
          f"best_partial={_short(st_row['best_partial'])}")
    check("终止 ⇒ stalled", st_row["status"] == "stalled")
    check("轮数不超过 max_rounds", st_row["rounds"] <= max_rounds)
    check("best_partial 非空（且如实）", bool(st_row["best_partial"].strip()))
    check(
        "停止路径写清楚了（提前停止 或 轮数用尽）",
        ("提前停止" in st_row["best_partial"]) or st_row["rounds"] == max_rounds,
    )
    after = f.step(pid)
    check("stalled 后不再推进（终态不可重入）",
          after["status"] == "stalled" and after["round"] == st_row["rounds"])

    # ---- 4b. 另一条终止路径：把"连续无进展提前停止"关掉，验证轮数用尽那一支
    killed = AgentF(st, config={"stall_after_no_progress_rounds": 0})
    pid2 = killed.create_plan("预算烧干路径", "selftest:burn", subgoals=[
        {"sid": "t1", "text": "未接线的子目标", "owner": "D", "status": "todo"},
    ])["plan_id"]
    for _ in range(max_rounds + 3):
        if killed.step(pid2)["status"] == "stalled":
            break
    row2 = killed.status(pid2)
    print(f"[8b] 提前停止关闭后 ⇒ status={row2['status']} rounds={row2['rounds']}")
    check("提前停止关闭时，轮数真的跑到 max_rounds（两个方向都测到）",
          row2["status"] == "stalled" and row2["rounds"] == max_rounds)

    # ---- 5. FC-22 负控：数值证据不得关闭子目标
    rejected = False
    try:
        S.AttackPlan(
            plan_id="0000", problem="p", problem_key="k",
            budget=dict(AT.DEFAULT_BUDGET), rounds=0, status="open",
            subgoals=[{"sid": "s", "text": "t", "owner": "E", "status": "closed",
                       "experiment_ids": ["0000"], "proof_experiment_ids": []}],
        ).validate()
    except ValueError as ex:
        rejected = "proof" in str(ex)
    check("只有数值证据却标 closed ⇒ schema 抛（FC-22）", rejected)

    # ---- 6. 工具层与 AgentF 口径一致
    print(f"[9] 工具 attack.*：{f.tools.names()}")
    t = f.tools.call("attack.status", plan_id=pid)
    check("attack.status 可用且返回同一计划", t.ok and t.data["plan_id"] == pid)
    t2 = f.tools.call("attack.create_plan", problem="工具建的", problem_key="P-tool")
    check("attack.create_plan 可用", t2.ok and t2.data["created"] is True)
    t3 = f.tools.call("attack.list_plans")
    # 到这一步库里应当有 3 个计划：主计划 + [8b] 的"预算烧干"路径 + 上面工具建的这一个。
    # 断言写成"至少 3 且包含刚建的那个"，而不是写死 `== 2`：
    # 写死数字会让"新增一条覆盖率更高的自检"变成一次失败 —— 而测试应当对行为
    # 断言，不该对"我数了几个对象"断言。
    check("attack.list_plans 可用",
          t3.ok and t3.data["total"] >= 3
          and any(p.get("problem_key") == "P-tool" for p in t3.data["plans"]))

    print("=" * 72)
    print(f"SELF-CHECK {'DONE' if failures == 0 else 'FAILED'}（agent_f）：失败 {failures} 项")
    return failures


# ---------------------------------------------------------------- 声明（`goal-7f5116c1` M2）
#
# `SPEC` 是这个角色自己的声明：职责与门面、十项官能的轻重、它自己那几句话、
# 只读与否、能不能被召唤、能召唤谁、会写哪些表、实现类。
# 今天这些格子散在 `agent_prompts` / `capabilities` / `tools/__init__` / `host.py`，
# 每一处都有对账判据（`tests/test_agent_spec_reconciliation.py`）。
# 动作表与构造工厂还没搬过来（M3 / M4），所以这里不复制那两份数据。
SPEC = AgentSpec(
    role='F',
    brief=AgentBrief(
        duty='多轮难题攻坚：在预算内一轮一轮逼近平息或反例，并如实报告进展',
        boundary=(
            '终止条件是预算与轮次，不是感觉：预算耗尽必须停手并如实写未推进。',
            '不许把没推进写成已完成；台账里的每一步都要能看出这一轮做了什么、为什么停。',
            '不许自己改结论或证据：你的产出是攻击计划与进展，结论由 D 或人收口。',
            '需要 C/D/E 的推理而框架没接线时，如实写未接线，不许编一个中间结果顶上。',
        ),
        policy=('每一轮先挑一个可判定的子目标，做完就落台账；子目标不可判定时先把它拆小。',),
        signature_error='把无变化写成有进展。',
        deliverable='attack_plans 行的子目标进展与终止原因。',
        stance=(
            "攻坚的产物是'离解决还差什么'，不是'我们做了很多轮'：每一轮都要让卡点更具体一点。",
            '允许提猜想：把猜想写成可判定的形式（谁、在什么条件下、能不能被一个反例推翻），然后交给 E 或 D 去验。',
            "被预算逼停时，把'停在哪里、下一步该从哪继续'写清楚 —— 那是下一轮能接着干的唯一理由。",
        ),
    ),
    emphasis={
        '眼睛': 'minor',
        '耳朵': 'core',
        '脑子': 'core',
        '手': 'minor',
        '能讨论': 'core',
        '高观点': 'minor',
        '能互动': 'core',
        '能思辨': 'core',
        '敢创新': 'core',
        '有品味': 'minor',
    },
    local_notes={
        '耳朵': "D/E/C 的回信决定下一轮往哪打；预算耗尽时把'停在哪、下一步从哪继续'说清楚。",
        '能互动': '阶段性汇报是交付的一部分：每一轮都要让卡点比上一轮更具体；要被放手跑多轮时，把「下一轮从哪继续」写清楚。',
        '敢创新': '猜想要写成可判定的形式（谁、什么条件下、能不能被一个反例推翻）。',
        '脑子': "每一轮都要让卡点更具体：从'不会做'到'缺这一条引理'。",
        '能讨论': '把进展与卡点摊给 D/E/C 看，让他们决定要不要换角度。',
        '能思辨': '此路不通时换一条独立的路，而不是把同一招做得更用力。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'A',
        'B',
        'C',
        'D',
        'E',
    ),
    write_set=frozenset((
                     'attack_plans',
                     'reprocess_requests',
                     'search_requests',
                 )),
    class_path='agentflow.agent_f:AgentF',
)


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())
