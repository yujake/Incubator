"""智能体 G：论文撰写。

## G 到底在做什么

把 D（研究结论）/ F（攻坚过程）/ E（实验证据）的结论汇编成一份
每条断言都带引用的稿件，并把它渲染成人能读的 markdown。

G 的产出被两条结构性约束钉死：

1. 无引用的断言不可能进稿。这不是文风要求 —— 数学断言的价值完全取决于
   "它来自哪里"，允许无引用断言就等于允许一份"听起来很合理"的文本。
   `schema.Document.validate` 是最后一道闸，G 侧的第一道闸在
   :meth:`AgentG.compose_claim` / :meth:`AgentG.build_document`：
   在构造断言的那一刻就报错，因为那时手里还拿着"是哪一句话"。
2. 证据等级不许被夸大。`cross_check`（数值/穷举交叉验证）的断言由结构
   强制带上"不构成证明"的声明（FC-22），"已证明"这类措辞出现在非 proof 断言里
   直接抛错。

## G 与 H 的分工（为什么这个分工是结构性的，而不是礼貌性的）

H 提发现（`review_findings`），G 改稿（`documents`）。G 只能改自己的稿：

- 改稿：`revise()` 只动 `documents.claims/status/review_rounds`；
- 对 H 的发现，G 只能改它的 `status` 与 `resolution_note`，
  `kind/level/target/evidence/message` 一个字都不许动 —— 那是 H 当初的判断依据；
- 而且 G 自称"已修复"不作数：H 的 `verify_fixes` 会重跑检查，
  仍复现就把发现重新打开（`review_tools._apply_finding_status`）。

## 工具面（FC-06：角色即权限面）

`install_g_tools()` 按角色 `"G"` 装配。写工具（`doc.build_document` /
`doc.register_dependency`）的角色被收窄到 `("G",)`：H 拿不到它们，
于是"发现问题的人"与"改写稿件的人"在结构上不是同一个。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from .. import claimanatomy as CA
from .. import schema as S
from .. import signatures as SIG
from ..store import Store
from ..tools import build_registry
from ..tools import doc_tools as DT
from ..tools.base import ToolRegistry
from ..agentspec import AgentBrief, AgentSpec
__all__ = ["AgentG", "DocumentError", "install_g_tools"]
class DocumentError(ValueError):
    """稿件层面的问题（稿件不存在 / 发现不属于本稿 / 工具调用失败）。

    继承 `ValueError`：调用方无论是"参数拿错了"还是"数据不合规"，
    处置都一样 —— 立刻失败并说清是哪一件。不发明第二个异常体系。
    """
_UNSPECIFIED: Any = object()
def install_g_tools(
    store: Store,
    *,
    workspace_root: str | Path | None = None,
    registry: ToolRegistry | None = None,
) -> ToolRegistry:
    """装配 G 的工具栏。

    为什么按角色装配（`build_registry(...).scoped_to("G")`）而不是手工挑几个工具：
    角色即权限面（FC-06），装配结果必须可枚举、可比对；手工挑会在"新增工具时忘了
    给 G"这种地方静默漏水。

    「注册面」与「可调用面」是两件事，混起来会多算工具（`R7-AN-2` 的教训）：
    `scoped_to("G")` 给的是同一个注册表的视图，它仍然登记全部 spec
    （`names()` 是全集，含 G 根本调不到的写侧工具）；"G 到底能调什么"必须问
    `call_surface("G")` 或 `for_role("G")` —— 实测两者相等。
    `build_for_role` 那条老路会先把 spec 裁成子表（于是 `names()` 恰好等于工具面），
    代价是装配期的属性（FC-17 的 `default_budget` / `default_spill_root`、`P-14` 的
    `bound_role`）静默留空 —— 所以这里走 `scoped_to`，方向是拿回那两格，
    不是放宽权限面。

    为什么还要检查 `doc.*` 是否在里面：装配会容忍模块缺失
    （并行开发的现实），而 G 没有 doc 工具就什么也做不了。这种降级必须
    显式补上并留痕，而不是让 G 悄悄少一只手（FC-08：不得静默降级为空）。
    """
    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    if registry is not None:
        reg = registry
    else:
        # `scoped_to` 不裁 spec 表（`names()` 仍是全集），`build_for_role` 会裁成子表
        # （`names()` 就等于工具面）。这里要的是 `build_registry` 的完整装配：FC-17 的
        # 上下文预算（`default_budget` / `default_spill_root`）与 `P-14` 的
        # `bound_role="G"` 跟着过来，走 `build_for_role` 那两格会静默留空。
        # G 只通过 `self.tools.call(...)` 用工具，没有绑定角色的注册表会让每次调用都被拒。
        # "G 到底能调什么"由 `call_surface("G")` / `for_role("G")` 回答，不是 `names()`。
        reg = build_registry(store=store, workspace_root=root).registry.scoped_to("G")
    if not any(n.startswith("doc.") for n in reg.names()):
        DT.register(reg, store=store, root=root, workspace_root=root)
        setattr(reg, "doc_fallback_reason", "这次 scoped_to('G') 装配的结果里没有任何 doc.* 工具")
    if reg.bound_role is None:
        reg.bound_role = "G"
    return reg
from ..specs.g import SPEC  # noqa: E402,F401

