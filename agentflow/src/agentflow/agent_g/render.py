"""角色 G 的动作 `render`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, DT, Mapping, _UNSPECIFIED

class _Render:
    def render(self, doc: Mapping[str, Any], *, dependencies: Any = _UNSPECIFIED) -> str:
        """渲染 markdown（转发 `doc_tools.render_markdown`）。

        风格沿用 `agent_d.write_report`：中文、表格优先、每条断言带代号。
        `dependencies` 不传 = 自己去库里读该稿件的依赖；显式传 `None` = "没查"
        （渲染结果会如实写"未提供"，而不是写"0 条"）。
        """
        deps: Any = dependencies
        if deps is _UNSPECIFIED:
            doc_id = str(doc.get("doc_id") or "")
            deps = DT.dependencies_for_doc(self.store.rows("dependencies"), doc_id)
        elif deps is not None:
            deps = [dict(d) for d in deps]
        return DT.render_markdown(doc, dependencies=deps)
