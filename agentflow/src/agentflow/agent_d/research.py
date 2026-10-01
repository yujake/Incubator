"""角色 D 的动作 `research`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import C_NO_EVIDENCE, S

class _Research:
    def research(self, qid: str) -> dict:
        """对就绪问题做初步研究，产出研究笔记（§4.1 的第 5 步）。

        产出 ``{"question_id","confidence","analysis","conclusion","suggestions",
        "evidence","llm_used","c_queries","c_evidence"}``。置信度由
        :func:`evidence_confidence` 决定；LLM 只能把它调低（``_rank_min``）。

        ## I1：研究前必须先向 C 点一次菜

        ``research()`` 一定会带上 ``c_queries``（每条含
        ``{api, params, checked, truncated, digest, reason}``），参数由该问题的
        ``related_concept_ids`` / ``related_relation_ids`` 现场推导。这不是
        "顺便查一下"：结论里"这两个概念之间还有没有别的链条/别的矛盾关系"这类
        判断只能来自 C 的图查询，而报告本身是上一次分析的快照。

        一条 C 查询都没成功时，结论会被 :meth:`_apply_c_evidence_caveat`
        显式标注「无 C 侧证据」并放弃确定语气 —— 不允许把"没问到"写成
        "查不到"，更不允许在没问到的情况下给出看起来已被核实的判断。
        """
        ev = self.trace_question(qid)
        if ev.get("c_queries") is None:
            ev["c_queries"] = self.probe_c(qid)
        verdict = self.assess(qid, ev)
        if verdict.get("l3_needed") and not ev.get("l3"):
            ev = self.trace_l3(ev)

        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None) or {}
        confidence = verdict["confidence"]
        analysis, conclusion, suggestions, llm_used = self._compose(ev, verdict)
        conclusion, suggestions = self._apply_c_evidence_caveat(ev, verdict, conclusion, list(suggestions))

        # ---- 落库：笔记 + 证据文献 + 状态
        lit_ids = S.sorted_unique([str(c.get("lit_id")) for c in ev.get("claims") or [] if c.get("lit_id")])
        try:
            with self.store.tx("research_questions", actor=self.actor, note="research") as tx:
                row = tx.find("research_questions", question_id=qid)
                if row is not None:
                    row["evidence_lit_ids"] = S.sorted_unique(list(row.get("evidence_lit_ids") or []) + lit_ids)
                    if row.get("status") in ("open", "needs_evidence"):
                        row["status"] = "researching"
                    row["updated_at"] = self._stamp()
                    csum = self._c_summary(ev.get("c_queries") or [])
                    note = (
                        f"[research] 置信度={confidence}（判据：{'/'.join(c['id'] for c in verdict['criteria']) or '无'}；"
                        f"证据 {len(ev.get('claims') or [])} 条，quote_verified=True "
                        f"{sum(1 for c in ev.get('claims') or [] if c.get('quote_verified') is True)} 条；"
                        f"C 查询成功 {csum['ok']}/{csum['attempted']}；"
                        f"LLM={'yes' if llm_used else 'no'}）"
                        + ("" if csum["any_success"] else f" ⚠️ {C_NO_EVIDENCE}：结论未经 C 的图查询核对")
                    )
                    row["notes"] = ((row.get("notes") or "") + "\n" + note)[:20000]
                    S.row_from_dict("research_questions", row).validate()
                    tx.upsert("research_questions", row, note="researched")
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:research", "error": f"{type(e).__name__}: {e}"})

        result = {
            "question_id": qid,
            "question": ev.get("question"),
            "origin": ev.get("origin"),
            "priority": verdict.get("priority"),
            "confidence": confidence,
            "criteria": [c["id"] for c in verdict["criteria"]],
            "criteria_detail": verdict["criteria"],
            "hits": verdict["hits"],
            "contradictions": verdict["contradictions"],
            "analysis": analysis,
            "conclusion": conclusion,
            "suggestions": suggestions,
            "evidence": ev,
            "llm_used": llm_used,
            "trace_mode": ev.get("trace_mode"),
            "c_queries": list(ev.get("c_queries") or []),
            "c_evidence": verdict.get("c_evidence") or self._c_summary(ev.get("c_queries") or []),
        }
        self.last_research = getattr(self, "last_research", {})
        self.last_research[qid] = result
        return result
