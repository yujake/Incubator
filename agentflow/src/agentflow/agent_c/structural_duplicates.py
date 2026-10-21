"""角色 C 的动作 `structural_duplicates`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import SERVICE_MAX_STRUCTURAL_PAIRS, _cfg_int, _service_int

class _StructuralDuplicates:
    def structural_duplicates(self, *, limit: int | None = None) -> dict:
        """结构重复概念候选（I5 的检测侧，同步、只读、有界）。
        
        返回----``{"checked", "candidates", "truncation_notice", "truncated", "scanned_concepts","scanned_relations", "method", "method_note", "reason"}``
        
        判据全部来自 `interactions.structural_duplicate_pairs`（不另写一份）：邻域完全相同 且 两者之间没有直接关系 且 邻域非空。
        
        `is_truncation_notice=True` 的那条单独放进 `truncation_notice`，不混进`candidates`：它是一句"枚举被上限截断"的
        元信息，形状却是"一个概念对"。一旦混在一起，下游（尤其是不看这个字段的 LLM）会把它当成第 N 对候选，去 B 那里请求合并两个代号为空的概念。
        
        `method_note` 与 `proposal` 一起表达同一件事：结构等价 ≠ 同义。两个不同的概念完全可能都连着同一批邻居，所以只有结构证据时
        `proposal="review"`（其 `reason` 里写着"不得据此合并"），合并决定权在 B，且 B 必须给出理由。
        """
        g = self._g()
        checked, why = self._service_checkable(g)
        lim = max(1, _cfg_int(self.cfg, "service_max_structural_pairs", SERVICE_MAX_STRUCTURAL_PAIRS))
        if limit is not None:
            lim = max(1, min(_service_int(limit, name="limit", default=lim), lim))
        meta = {
            "method": "structural_neighborhood_equality",
            "method_note": (
                "只做'邻域完全相同 + 两者之间无直接关系'的结构判据；"
                "结构等价 ≠ 同义（两个不同概念可能连着同一批邻居），"
                "因此只有结构证据时只给 proposal=review，合并决定权在 B"
            ),
            "limit": lim,
        }
        if not checked:
            return {**meta, "checked": False, "candidates": [], "truncation_notice": None,
                    "truncated": False, "scanned_concepts": 0, "scanned_relations": 0, "reason": why}

        pairs = self._structural_pairs(g)
        notices = [p for p in pairs if p.get("is_truncation_notice")]
        cands = [p for p in pairs if not p.get("is_truncation_notice")]
        truncated = bool(notices) or len(cands) > lim
        kept = cands[:lim]
        merge_n = sum(1 for p in kept if p.get("proposal") == "merge")
        reason = (
            f"扫描 {len(g.concept_by_id)} 个概念、{len(g.relations)} 条关系，"
            f"命中 {len(cands)} 对结构等价候选（其中 {merge_n} 对名字侧也有证据 ⇒ proposal=merge，"
            f"其余 {len(kept) - merge_n} 对只有结构证据 ⇒ proposal=review，**不得据此合并**）"
        )
        if len(cands) > lim:
            reason += f"；⚠️ 仅返回前 {lim} 对（truncated=True）：不能说'只有这些结构重复'"
        if notices:
            reason += "；枚举本身触及 interactions 的 max_pairs 上限，已单列 truncation_notice"
        if not cands:
            reason += "。这是'查过了、没有'（checked=True），不是'没查'"
        return {
            **meta,
            "checked": True,
            "candidates": kept,
            "truncation_notice": notices[0] if notices else None,
            "truncated": truncated,
            "scanned_concepts": len(g.concept_by_id),
            "scanned_relations": len(g.relations),
            "reason": reason,
        }
