"""角色 B 的动作 `resolve_structural_duplicate`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, Mapping

class _ResolveStructuralDuplicate:
    def resolve_structural_duplicate(self, candidate: Mapping[str, Any] | None) -> dict:
        """决定 + 执行合并（I5）。返回决定字段加执行摘要。

        为什么在一个事务里"先复核再执行"：候选是 C 用无锁快照算出来的，
        等 B 拿到它时图可能已经变了（另一个 B 实例刚写了新关系、或刚合并了别的对）。
        因此决定必须基于本事务读到的行重算一遍，而不是采信候选里的结论。
        判成 `reject` 时一行数据都不写（只返回理由）。

        关系改写的后果是想清楚的
        ------------------------
        把被合并方换成 survivor 之后，可能产生重复关系（两条关系变成同一概念组、
        同一引文）。这里不自己造一套判据，而是把改写后的行喂给既有的
        `dedup.decide_relation`：判成 `duplicate` 的行标 `status="rejected"` +
        `duplicate_of` 指向幸存关系（保留行，删了就无从审计）；判成 `suspect`
        的行降级为 `suspect`；其余保持原状态。
        改写还会影响 `related_concepts`，因此所有受影响的概念都用
        `dedup.derive_related_concepts` 整体重算（派生而非增量，DESIGN.md §6.2）。
        """
        with self.store.tx("concepts", "relations", "statements", actor=self.actor,
                           note="structural_merge") as tx:
            decision = self.decide_structural_duplicate(
                candidate, concepts=tx.rows("concepts"), relations=tx.rows("relations")
            )
            if decision["verdict"] != "merge":
                return {
                    **decision,
                    "applied": False,
                    "rewritten_relation_ids": [],
                    "rejected_relation_ids": [],
                    "skipped_relation_ids": [],
                }
            summary = self._apply_merge(tx, decision)
        return {**decision, **summary}
