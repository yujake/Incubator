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
from .. import interactions as IX
from .. import schema as S
from ..store import Store
from ..tools import attack_tools as AT
from ..tools.base import ToolError, ToolRegistry
from ..agentspec import AgentBrief, AgentSpec
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
TERMINAL_STATUSES = AT.TERMINAL_STATUSES
UNWIRED_OWNERS = ("C", "D", "F")
ACTIONS = (
    "run_experiment",
    "submit_search_request",
    "submit_reprocess_request",
    "no_change",
    "stop",
)
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
from ..specs.f import SPEC  # noqa: E402,F401

