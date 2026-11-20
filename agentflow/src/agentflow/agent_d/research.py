"""角色 D 的动作 `research`（一动作一文件；判据 `tests/test_agent_split_is_one_action_one_file.py`）。"""
from __future__ import annotations

from ._support import C_NO_EVIDENCE, S, conclusion_consistency_reading

class _Research:
    def research(self, qid: str) -> dict:
        """对就绪问题做初步研究，产出研究笔记（§4.1 的第 5 步）。
        产出 ``{"question_id","confidence","analysis","conclusion","suggestions","evidence","llm_used","c_queries","c_evidence","conclusion_consistency"}``。
        置信度由:func:`evidence_confidence` 决定；LLM 只能把它调低（``_rank_min``）。
        ## I1：研究前必须先向 C 点一次菜
        ``research()`` 一定会带上 ``c_queries``（每条含
        ``{api, params, checked, truncated, digest, reason}``），参数由该问题的``related_concept_ids``
        / ``related_relation_ids`` 现场推导。这不是"顺便查一下"：结论里"这两个概念之间还有没有别的链条/别的矛盾关系"这类判断只能来自 C 的图查询，
        而报告本身是上一次分析的快照。
        一条 C 查询都没成功时，结论会被 :meth:`_apply_c_evidence_caveat`显式标注「无 C 侧证据」并放弃确定语气 —— 不允许把"没问到"写成"
        查不到"，更不允许在没问到的情况下给出看起来已被核实的判断。
        """
        ev = self.trace_question(qid)
        if ev.get("c_queries") is None:
            ev["c_queries"] = self.probe_c(qid)
        verdict = self.assess(qid, ev)
        if verdict.get("l3_needed") and not ev.get("l3"):
            ev = self.trace_l3(ev)

        confidence = verdict["confidence"]
        analysis, conclusion, suggestions, llm_used = self._compose(ev, verdict)
        conclusion, suggestions = self._apply_c_evidence_caveat(ev, verdict, conclusion, list(suggestions))
        # ---- S-09（非 LLM 半）：措辞与置信度方向一致吗（`_support.conclusion_consistency_reading`）
        # 这一格是读数不是闸：判据只钉"低档说满了 / 高档留余地"两个方向，不拦这一段
        # 结论（内容对错归 V）。它必须落进返回值才能在报告侧被读到 —— 改前这个判据只有
        # 测试在调，`research` 一次都没算过，于是"数字 0.3 而措辞写'证明了'"在盘上
        # 没有任何读数。`confidence` 是档名（high/medium/low），判据自己把它折成门槛上的数字。
        consistency = conclusion_consistency_reading(conclusion=conclusion,
                                                     confidence=confidence)

        # ---- 落库：笔记 + 证据文献 + 状态
        lit_ids = S.sorted_unique([str(c.get("lit_id")) for c in ev.get("claims") or [] if c.get("lit_id")])
        try:
            with self.store.tx("research_questions", actor=self.actor, note="research") as tx:
                row = tx.find("research_questions", question_id=qid)
                if row is not None:
                    row["evidence_lit_ids"] = S.sorted_unique(list(row.get("evidence_lit_ids") or []) + lit_ids)
                    # ---- 状态由判据现算，不由调用顺序决定（CS-5）
                    # `verdict["sufficient"]` = `analyze_gaps` 的三条可核实判据一条都没触发 ⇒ `answered`
                    # （终态）；仍不足 ⇒ 留 `researching`（下一步回到 `submit_gaps`，由它写成 `needs_evidence`）。
                    # 为什么必须在这里写：`researching → answered` 这条边早在
                    # `research_tools.LEGAL_TRANSITIONS` 里，但缺口这条路上没有代码走它 ⇒ `pipeline.py:428`
                    # 与 `agent_d/core.py`（`_adjudicate_ready_contradictions`）那两道"已下结论就跳过"的过滤
                    # 永远不生效（真机 118 行 `research_questions` 里 `answered` 0 行）。不用 `confidence`
                    # 当门槛：置信度衡量证据强度，`sufficient` 衡量"有没有触发'不足'的判据"，两者不是一回事。
                    if verdict["sufficient"]:
                        row["status"] = "answered"
                        # 终态必须清空等待集：不清的话 `verify` 会报 `stale_waiting` ——
                        # 与矛盾闭环 `agent_d/adjudicate.py`（`verdict == "resolved"` 那一支）
                        # 同一条纪律。
                        row["waiting_request_ids"] = []
                    elif row.get("status") in ("open", "needs_evidence"):
                        row["status"] = "researching"
                    row["updated_at"] = self._stamp()
                    csum = self._c_summary(ev.get("c_queries") or [])
                    claims = ev.get("claims") or []
                    note = (
                        f"[research] 置信度={confidence}（判据：{'/'.join(c['id'] for c in verdict['criteria']) or '无'}；"
                        f"证据 {len(claims)} 条，quote_verified=True "
                        f"{sum(1 for c in claims if c.get('quote_verified') is True)} 条；"
                        f"C 查询成功 {csum['ok']}/{csum['attempted']}；"
                        f"LLM={'yes' if llm_used else 'no'}）"
                        + ("" if consistency.get("verdict") in ("", "consistent") else
                           " ⚠️ 结论措辞与置信度方向不一致（"
                           f"{consistency.get('verdict')}：{consistency.get('reason')}）")
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
            # S-09（非 LLM 半）的读数：`checked` / `verdict`（overstated / understated /
            # consistent）/ `reason` / 命中的措辞。报告侧按它说清"这一段的话说得比数字满"。
            "conclusion_consistency": consistency,
            "evidence": ev,
            "llm_used": llm_used,
            # 三态读数（`R1-A1`）：`llm_used=False` 分不出"没接线"与"接了但失败"，
            # 这一格说清是哪一种（`{kind,state,reason,model,calls,task_id}`）。
            # 它是这一趟的读数：既随返回值出去（落 `out/tasks/<task_id>.json`），
            # 也是"这一次召唤内调了几次模型"的落点（P-09 的召唤级口径）。
            "llm_reading": dict(getattr(self, "last_llm_reading", {}) or {}),
            "trace_mode": ev.get("trace_mode"),
            "c_queries": list(ev.get("c_queries") or []),
            "c_evidence": verdict.get("c_evidence") or self._c_summary(ev.get("c_queries") or []),
        }
        self.last_research = getattr(self, "last_research", {})
        self.last_research[qid] = result
        return result
