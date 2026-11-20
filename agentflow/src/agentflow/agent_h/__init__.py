"""智能体 H：审校（只读）。

为什么 H 必须是只读的：若审校者能直接改稿，它就同时是"发现者"与"修正者"，于是"发现
问题"与"掩盖问题"在结构上无法区分 —— 这不是分工洁癖，而是"审校记录能不能被信任"的
前提。把这条做成结构约束（而不是写在提示词里），是它唯一可靠的落地方式。

"H 只读"由三件事共同保证（缺一条就只剩口号）：① 工具面只读 —— `install_h_tools()`
只把 `side_effect in ("none","read")` 的工具与 `tools.UNIVERSAL_TOOLS` 里登记过的通用
能力放进 H 的自由工具箱（判据本体是 `h_free_toolbox_accepts`），并在构造时断言
（拿到不合规的注册表就 fail-closed 拒绝启动）。通用能力也在里面，是因为"通用能力根本
不该出现谁能用这个说法"—— `clock.timer_start` 据实是 `write_local`，而它必须对所有
角色可用；硬约束是通用能力的写集只许落在通信/簿记类表上。被拒的写工具会记进
`registry.refused_write_tools`，不静默丢弃。② 落库代理被钉死 —— H 唯一会写盘的动作
（写 `review_findings`、改 `documents.status`）走显式的"代理注册表"（`self.writers`，
`include_writers=True`），这两个工具的落点固定：不碰 `claims`，不碰任何知识表。
③ 可核对的运行期断言 —— 审校前后 `concepts/relations/literature` 逐字节不变；
`documents.json` 的变化点只有 `status` 与审核轴三格（`review_verdict` / `reviewed_at` /
`reviewed_by`）以及跟着复审走的 `review_rounds`（连 `updated_at` 都不碰）。

H 的三态纪律：`dependencies` 没查（显式 `None`）与"查了、依赖都闭合"是两件事 ——
前者必须报 `dep_check.checked is False` 且不许判 `accepted`；`AgentD` 的
`_UNSPECIFIED` 哨兵在这里沿用同一种语义。

拆包只做入口与命名空间保持：import 面不许变，动作各自在 `agent_h/<动作>.py`，自检
入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentH
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, CROSS_CHECK_DISCLAIMER, Callable, Iterable, 
    Mapping, Path, READONLY_CALL_EXCEPTIONS, RV, ReviewError, S, SIDE_EFFECTS_WRITE, SPEC, 
    Sequence, Store, ToolRegistry, ToolSpec, _H_READONLY_SIDE_EFFECTS, _H_WRITABLE_TOOLS, 
    _SELFTEST_HARNESS, _UNSPECIFIED, _inject_raw_document, _seed_document, annotations, 
    build_registry, filter_readonly_h_surface, h_free_toolbox_accepts, install_h_tools,
)
from ..specs.h import SPEC

__all__ = ["AgentH", "ReviewError", "filter_readonly_h_surface", "install_h_tools", "SPEC"]
