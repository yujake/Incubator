"""角色 D 的动作 `assess`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import analyze_gaps, question_keywords

class _Assess:
    def assess(self, qid: str, evidence: dict | None = None) -> dict:
        """评估证据是否足够（§4.4 的可核实判据）。

        返回 ``{"sufficient", "insufficient", "criteria", "priority", "confidence",
        "hits", "contradictions", "degree", ...}`` —— 全部中间值都在里面，
        因为 D 的结论必须能被逐项复核（§3.4 对 C 的同一要求适用于 D）。

        ## I1：评估阶段也点一次菜

        判据本身（关键词命中 / 度数 / 矛盾）只依赖 D 侧溯源，不需要 C。
        但"这个问题的结论有没有 C 侧证据"必须在评估阶段就定下来：
        报告要用它决定措辞（无 C 侧证据时不许给确定语气）。所以这里在
        evidence 里还没有 ``c_queries`` 时补一次 :meth:`probe_c`；
        已经有（research 先查过）就复用，绝不重复查。
        """
        ev = evidence if evidence is not None else self.trace_question(qid)
        if ev.get("c_queries") is None:
            ev["c_queries"] = self.probe_c(qid)
        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None) or {}
        concepts = ev.get("l2") or []
        degree = max((int(c.get("degree") or 0) for c in concepts), default=0)

        keywords = question_keywords(
            qrow.get("question") or ev.get("question") or "",
            extra=[c.get("name") or "" for c in concepts],
        )
        verdict = analyze_gaps(
            [c["relation_id"] for c in ev.get("claims") or []],
            ev.get("claims") or [],
            keywords=keywords,
            degree=degree,
            degree_threshold=self.degree_threshold,
            concept_count=len(concepts),
        )
        verdict.update(
            {
                "question_id": qid,
                "keywords": keywords,
                "trace_mode": ev.get("trace_mode"),
                "claim_count": len(ev.get("claims") or []),
                "sufficient": not verdict["insufficient"],
                "l3_needed": self._l3_needed(verdict, ev),
                "c_queries": list(ev.get("c_queries") or []),
                "c_evidence": self._c_summary(ev.get("c_queries") or []),
                "c_wiring": dict(self.c_wiring),
            }
        )
        self.last_assessment = verdict
        return verdict
