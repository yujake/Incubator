"""智能体 G：论文撰写。

G 把 D（研究结论）/ F（攻坚过程）/ E（实验证据）的结论汇编成一份每条断言都带引用的
稿件，并渲染成人能读的 markdown。它的产出被两条结构性约束钉死：

1. 无引用的断言不可能进稿。这不是文风要求 —— 数学断言的价值完全取决于"它来自哪里"，
   允许无引用断言就等于允许一份"听起来很合理"的文本。`schema.Document.validate` 是
   最后一道闸，G 侧的第一道闸在 :meth:`AgentG.compose_claim` / :meth:`AgentG.
   build_document`：在构造断言的那一刻就报错，因为那时手里还拿着"是哪一句话"。
2. 证据档位不许被夸大。`cross_check`（数值/穷举交叉验证）的断言由结构强制带上
   "不构成证明"的声明（FC-22），"已证明"这类措辞出现在非 proof 断言里直接抛错。

G 与 H 的分工（结构性的，不是礼貌性的）：H 提发现（`review_findings`），G 改稿
（`documents`）。G 只能改自己的稿 —— 改稿只动 `documents.claims/status/review_rounds`；
对 H 的发现只能改 `status` 与 `resolution_note`，`kind/level/target/evidence/message`
一个字都不许动（那是 H 当初的判断依据）；G 自称"已修复"不作数：H 的 `verify_fixes`
会重跑检查，仍复现就把发现重新打开（`review_tools._apply_finding_status`）。

工具面（FC-06：角色即权限面）：`install_g_tools()` 按角色 `"G"` 装配。写工具
（`doc.build_document` / `doc.register_dependency`）的角色被收窄到 `("G",)`：H 拿不到
它们，于是"发现问题的人"与"改写稿件的人"在结构上不是同一个。

拆包只做入口与命名空间的保持 —— import 面不许变，原来能在 `agentflow.agent_g` 下
import 到的名字（含私有名）逐个再导出；动作各自在 `agent_g/<动作>.py`，自检入口在
同目录 `__main__.py`。
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
