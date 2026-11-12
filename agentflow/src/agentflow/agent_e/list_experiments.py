"""角色 E 的动作 `list_experiments`。"""
from __future__ import annotations

from ._support import VT

class _ListExperiments:
    def list_experiments(self, *, claim_key: str | None = None, limit: int | None = None) -> dict:
        """只读列出实验记录。"""
        return VT.list_experiments(self.store, claim_key=claim_key, limit=limit)
