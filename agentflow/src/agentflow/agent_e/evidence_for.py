"""角色 E 的动作 `evidence_for`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import VT

class _EvidenceFor:
    def evidence_for(self, claim_key: str | None = None, *, for_question_id: str | None = None) -> dict:
        """三态查询某条命题 / 某个研究问题的实验证据。实现见 `verify_tools.evidence_for`。"""
        out = VT.evidence_for(self.store, claim_key, for_question_id=for_question_id)
        self.last_evidence_query = out
        return out
