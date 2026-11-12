"""G 包内部件共用的小工具（口径与包入口同一份）。

职责与两条结构性约束（无引用断言进不了稿 / 证据档位不许被夸大）见
`agent_g/__init__.py` 的模块 docstring —— 这里不复制一份会漂的副本。本文件只放
`DocumentError` 与 `install_g_tools`。
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
    角色即权限面（FC-06），装配结果必须可枚举、可比对；手工挑会在"新增工具时忘了给 G"
    这种地方静默漏水。

    「注册面」与「可调用面」是两件事，混起来会多算工具：`scoped_to("G")` 给的是同一个
    注册表的视图，它仍然登记全部 spec（`names()` 是全集，含 G 根本调不到的写侧工具）；
    "G 到底能调什么"必须问 `call_surface("G")` 或 `for_role("G")`。`build_for_role` 那条
    老路会先把 spec 裁成子表（于是 `names()` 恰好等于工具面），代价是装配期的属性
    （FC-17 的 `default_budget` / `default_spill_root`、`P-14` 的 `bound_role`）静默留空
    —— 所以这里走 `scoped_to`，方向是拿回那两格，不是放宽权限面。

    为什么还要检查 `doc.*` 是否在里面：装配会容忍模块缺失（并行开发的现实），而 G 没有
    doc 工具就什么也做不了。这种降级必须显式补上并留痕，而不是让 G 悄悄少一只手
    （FC-08：不得静默降级为空）。
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

