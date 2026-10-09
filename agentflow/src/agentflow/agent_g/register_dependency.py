"""角色 G 的动作 `register_dependency`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any

class _RegisterDependency:
    def register_dependency(
        self,
        used_by: str,
        kind: str,
        label: str,
        *,
        source_lit_id: str | None = None,
        source_experiment_id: str | None = None,
        source_stmt_id: str | None = None,
        path_group: int = 1,
        page_range: Any = None,
        quote: str = "",
        status: str = "dangling",
        status_reason: str = "",
    ) -> dict:
        """登记外部依赖（转发 `doc.register_dependency`，第一道闭合闸在工具层）。

        `status="closed"` 时会用真实数据核 `literature`/`experiments`/`statements` 表：
        schema 只能查"字段非空"，查不出"这个 lit_id 根本不存在"。
        引用一篇不存在的文献，就是把外部结论当成了自己的结论。

        `source_stmt_id`（2026-10-09 加的第四种来源）：被依赖的是我们自己的一条命题
        （定理用到定理 / 用到某个概念）—— 那条边此前无处安放，承重链断在命题之间。
        `path_group`：证明路径不唯一时它是组号（同一 `used_by` 下组内都要、组间任一）。
        """
        data = self._call(
            "doc.register_dependency",
            used_by=used_by,
            kind=kind,
            label=label,
            source_lit_id=source_lit_id,
            source_experiment_id=source_experiment_id,
            source_stmt_id=source_stmt_id,
            path_group=path_group,
            page_range=list(page_range) if isinstance(page_range, (list, tuple)) else page_range,
            quote=quote,
            status=status,
            status_reason=status_reason,
        )
        self._emit(f"登记依赖 dep:{data.get('dep_id')} status={data.get('status')}")
        return data
