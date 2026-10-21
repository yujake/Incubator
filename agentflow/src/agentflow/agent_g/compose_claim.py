"""角色 G 的动作 `compose_claim`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, DT, Mapping, Sequence

class _ComposeClaim:
    def compose_claim(
        self,
        text: str,
        *,
        citations: Sequence[str],
        evidence_kind: str,
        section: str,
        is_negative: bool = False,
        negation_kind: str | None = None,
        claim_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        proof_location: str | None = None,
        numeric_evidence: Mapping[str, Any] | None = None,
        counterexamples: Sequence[Any] | None = None,
        frozen: bool = False,
        freeze_reason: str = "",
        allowed_use: str | None = None,
        scope_caveat: str = "",
        revision_hash: str = "",
        errata_ids: Sequence[str] | None = None,
    ) -> dict:
        """构造一条合规断言（转发 `doc_tools.compose_claim`）。
        判据只有一份：这里不重新实现检查，直接复用工具层的纯函数 ——两套判据必然漂移，而漂移的后果是"G 认为合规、H 认为违规"这种没有任何报错的静默分裂。
        委托给工具层而不是直接 import 一个私有实现，也让"G 与 LLM 用同一套构造入口"成为事实：`doc.compose_claim` 工具最终调的就是这个函数。
        ## §8.3 的生命周期字段（本轮新增，全部可选）
        `kind` / `status` / `proof_location` / `numeric_evidence` /`counterexamples` / 
        `frozen`+`freeze_reason` / `allowed_use` /`scope_caveat` / `revision_hash` / 
        `errata_ids`。
        不给就是不写（不是写一个假默认）：`status='验'` 与"没有 `status`"是两件事，前者是"这条断言当前只被数值验过"，后者是"这条断言的生命周期还没被登记
        " —— 把后者悄悄当成前者，正是 `DEVELOPMENT.md` §3 纪律 1 说的那个坑（"下游把'我们没查'读成了'查了没有'"）。
        """
        return DT.compose_claim(
            text,
            citations=citations,
            evidence_kind=evidence_kind,
            section=section,
            is_negative=is_negative,
            negation_kind=negation_kind,
            claim_id=claim_id,
            kind=kind,
            status=status,
            proof_location=proof_location,
            numeric_evidence=numeric_evidence,
            counterexamples=counterexamples,
            frozen=frozen,
            freeze_reason=freeze_reason,
            allowed_use=allowed_use,
            scope_caveat=scope_caveat,
            revision_hash=revision_hash,
            errata_ids=errata_ids,
        )
