"""智能体 H：审校（只读）。

## 为什么 H 必须是只读的

若审校者能直接改稿，它就同时是"发现者"与"修正者"，于是
"发现问题"与"掩盖问题"在结构上无法区分 —— 这不是分工洁癖，
而是"审校记录能不能被信任"的前提。把这条做成结构约束（而不是写在提示词里），
是它唯一可靠的落地方式。

## "H 只读"在这里由三件事共同保证（缺一条就只剩口号）

1. 工具面只读：`install_h_tools()` 只把 `side_effect in ("none","read")`
   的工具放进 H 的自由工具箱，并在构造时断言这一点（拿到不合规的注册表
   就 fail-closed 拒绝启动）。被拒的写工具会记进 `registry.refused_write_tools`，
   不静默丢弃。
2. 落库代理被钉死：H 唯一会写盘的动作（写 `review_findings`、
   改 `documents.status`）走的是显式的"代理注册表"（`self.writers`，
   `include_writers=True`），而这两个工具的落点固定：不碰 `claims`，
   不碰任何知识表。
3. 可核对的运行期断言：审校前后 `concepts/relations/literature` 逐字节不变；
   `documents.json` 的唯一变化点是 `status`（连 `updated_at` 都不碰）。

## H 的三态纪律

`dependencies` 没查（显式 `None`）与"查了、依赖都闭合"是两件事：
前者必须报 `dep_check.checked is False` 且不许判 `accepted`。
AgentD 的 `_UNSPECIFIED` 哨兵在这里沿用同一种语义。

`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与命名空间的保持 ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_h` 下 import 到的名字（含私有名，也包括住在 `core.py` 的
`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_h/<动作>.py`，
`python -m agentflow.agent_h` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentH
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, CROSS_CHECK_DISCLAIMER, Callable, Iterable, 
    Mapping, Path, READONLY_CALL_EXCEPTIONS, RV, ReviewError, S, SIDE_EFFECTS_WRITE, SPEC, 
    Sequence, Store, ToolRegistry, ToolSpec, _H_READONLY_SIDE_EFFECTS, _H_WRITABLE_TOOLS, 
    _SELFTEST_HARNESS, _UNSPECIFIED, _inject_raw_document, _seed_document, annotations, 
    build_registry, filter_readonly_h_surface, install_h_tools,
)
from ..specs.h import SPEC

__all__ = ["AgentH", "ReviewError", "filter_readonly_h_surface", "install_h_tools", "SPEC"]
