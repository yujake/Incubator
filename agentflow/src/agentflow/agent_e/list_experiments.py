"""角色 E 的动作 `list_experiments`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import VT

class _ListExperiments:
    def list_experiments(self, *, claim_key: str | None = None, limit: int | None = None) -> dict:
        """只读列出实验记录。"""
        return VT.list_experiments(self.store, claim_key=claim_key, limit=limit)
