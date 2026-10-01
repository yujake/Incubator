"""角色 H 的动作 `list_findings`（`goal-7f5116c1` M6：从 `agent_h.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, ReviewError

class _ListFindings:
    def list_findings(self, **filters: Any) -> dict:
        """只读列举发现（走 H 的自由工具箱）。"""
        res = self.tools.call("review.list_findings", **filters)
        self.tool_calls.append({"tool": "review.list_findings", "ok": res.ok, "error": res.error})
        if not res.ok:
            raise ReviewError(f"review.list_findings 调用失败：{res.error}")
        return res.data
