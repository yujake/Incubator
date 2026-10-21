"""智能体 G：论文撰写。
## G 到底在做什么
把 D（研究结论）/ F（攻坚过程）/ E（实验证据）的结论汇编成一份每条断言都带引用的稿件，并把它渲染成人能读的 markdown。
G 的产出被两条结构性约束钉死：
1. 无引用的断言不可能进稿。这不是文风要求 —— 数学断言的价值完全取决于"它来自哪里"，允许无引用断言就等于允许一份"听起来很合理"的文本。
`schema.Document.validate` 是最后一道闸，G 侧的第一道闸在:meth:`AgentG.compose_claim` / :meth:
`AgentG.build_document`：在构造断言的那一刻就报错，因为那时手里还拿着"是哪一句话"。 2. 证据等级不许被夸大。`cross_check`（数值/穷
举交叉验证）的断言由结构强制带上"不构成证明"的声明（FC-22），"已证明"这类措辞出现在非 proof 断言里直接抛错。
## G 与 H 的分工（为什么这个分工是结构性的，而不是礼貌性的）
H 提发现（`review_findings`），G 改稿（`documents`）。G 只能改自己的稿：
- 改稿：`revise()` 只动 `documents.claims/status/review_rounds`；- 对 H 的发现，G 只能改它的 `status` 
与 `resolution_note`，`kind/level/target/evidence/message` 一个字都不许动 —— 那是 H 当初的判断依据；- 而且
G 自称"已修复"不作数：H 的 `verify_fixes` 会重跑检查，仍复现就把发现重新打开（`review_tools._apply_finding_status`）。
## 工具面（FC-06：角色即权限面）
`install_g_tools()` 按角色 `"G"` 装配。写工具（`doc.build_document` /`doc.register_dependency`）的
角色被收窄到 `("G",)`：H 拿不到它们，于是"发现问题的人"与"改写稿件的人"在结构上不是同一个。
`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——拆包不许改变 import 面，所以原来能在 
`agentflow.agent_g` 下 import 到的名字（含私有名，也包括住在 `core.py` 的`_selftest` / `selftest`）都逐个再导
出；动作各自在 `agent_g/<动作>.py`，`python -m agentflow.agent_g` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentG
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, CA, Callable, DT, DocumentError, Mapping, 
    Path, S, SIG, SPEC, Sequence, Store, ToolRegistry, _UNSPECIFIED, annotations, 
    build_registry, install_g_tools,
)
from ..specs.g import SPEC

__all__ = ["AgentG", "DocumentError", "install_g_tools", "SPEC"]
