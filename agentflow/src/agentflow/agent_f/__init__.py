"""智能体 F：多轮难题攻坚。

设计基线：`test/test1/DESIGN-ROLES.md` §2.2 与 `schema.AttackPlan` 的硬约束。循环：
立项（带三维预算）→ 选子目标（确定性次序）→ 按 owner 分派一个动作 → 记一轮 history →
判断能否继续（不能 ⇒ 交出 best_partial（`stalled`）或如实收口（`resolved`））。

1. 终止条件是预算，不是"看起来差不多了"（FC-18）：`rounds` 的上界由
   `budget.max_rounds` 硬性给出，用尽即 `stalled`（不是失败，也不是成功）。
2. `step` 按子目标的 `owner` 分派，而"分派"必须落在真的被接线的动作上：`E` ⇒
   `AgentE.run_experiment`（带 `script_path` 时）；`A` / `B` ⇒ 各自的准入闸门 + 写请求
   行；`C`/`D`/`F` ⇒ 没有自动推理可调，记 `outcome="no_change"`。最后一行是刻意的：
   本框架尚未接线自动推理，所以 F 只能如实写"未推进"；把它写成
   `outcome="progress"` + 空证据是静默失败的典型形态。
3. 数值支持不能关闭子目标（FC-22）：E 返回 `evidence_kind="cross_check"` 时子目标最多
   标 `supported_not_proved`；`closed` 只认由 V 会审成立的穷举证明
   （`proof_reason=exhaustion`，签名 `signed_by=V`）。形式化不在 E 身上
   （`method="formal"` 以 `formal_not_in_e` 拒绝），F 也不传 `method="formal"`。

与 `attack_tools` 的分工：`check_budget` / `can_round` / `pick_next_subgoal` /
`can_derive` 的唯一实现在 `tools/attack_tools.py`，本模块只转发；`attack.*` 四个工具
转发到本模块 —— 写入逻辑只有一份。拆包只做入口与命名空间保持：import 面不许变，
动作各自在 `agent_f/<动作>.py`。
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
