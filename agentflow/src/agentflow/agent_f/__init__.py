"""智能体 F：多轮难题攻坚。
设计基线：``test/test1/DESIGN-ROLES.md`` §2.2 与 `schema.AttackPlan` 的硬约束。
立项（带三维预算） → 选子目标（确定性次序） → 按 owner 分派一个动作→ 记一轮 history → 判断是否还能继续├─ 还能 → 下一轮└─ 不能 → 交出 best_partial（`stalled`）或如实收口（`resolved`）
1. 终止条件是预算，不是"看起来差不多了"（FC-18）因此 `rounds` 的单调上界由 `budget.max_rounds` 硬性给出，用尽即 `stalled`（不是失败，也不是成功，见 `ATTACK_STATUSES` 的注释）。
`step` 按子目标的 `owner` 分派，而"分派"必须落在真的被接线的动作上：
| owner | 动作 | 状态 ||---|---|---|| `E` | 调 `AgentE.run_experiment`（带 `script_path` 时） | 已接线 || `A` | 
`interactions.admit_search_request` 过闸门 → 写 `search_requests` | 已接线 || `B` | `interactions.admit_reprocess_request` 过闸门 → 
写 `reprocess_requests` | 已接线 || `C`/`D`/`F` | 没有任何自动推理可调 | 记 `outcome="no_change"` |
`C`/`D`/`F` 那一行是刻意的：本框架尚未接线自动推理，所以 F 只能如实写"该子目标需要 C/D/F 的推理，本框架尚未接线 ⇒ 未推进"。
为什么这一条必须写死：把它写成"做了但没结果"（例如`outcome="progress"` + 空证据）是静默失败的典型形态 —— 计划看起来在推进、 history 里每一轮都有记录、`rounds` 在增长，而实际上什么也没发生。本项目最
痛的教训（`11-...md` §10.4 #7：D 没接工具却把"查不到"写成一条听起来很合理的研究发现）就是这种形态。
3. 数值支持不能关闭子目标（FC-22）E 返回 `evidence_kind="cross_check"` 时子目标最多标 `supported_not_proved`；只有 `proof` 级实验（`method="formal"` + 
非空 `verifier_output`）才进`proof_experiment_ids`、才允许 `closed`。
与 `attack_tools` 的分工- `check_budget` / `can_round` / `pick_next_subgoal` / `can_derive` 唯一实现在`tools/attack_tools.py`，本模块只转
发。- `attack.create_plan` / `attack.step` / `attack.status` / `attack.list_plans`四个工具转发到本模块（见 attack_tools 的 docstring）：写入逻
辑只有一份。
`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——拆包不许改变 import 面，所以原来能在 `agentflow.agent_f` 下 import 到的名字（含私有名，也包括住在 
`core.py` 的`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_f/<动作>.py`，`python -m agentflow.agent_f` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentF
from .core import (default_llm, set_default_llm, selftest,
)
from ._support import (ACTIONS, AT, AgentBrief, AgentSpec, Any, IX, Mapping, NO_PROGRESS_NOTE, 
    Path, PlanError, S, SPEC, STEP_OUTCOMES, Sequence, Store, TERMINAL_STATUSES, ToolError, 
    ToolRegistry, UNWIRED_OWNERS, _budget_left, _short, _step_outcome, _subgoal, annotations, 
    install_f_tools, re,
)
from ..specs.f import SPEC

__all__ = ["AgentF", "PlanError", "STEP_OUTCOMES", "default_llm", "install_f_tools",
           "selftest", "set_default_llm", "SPEC"]
