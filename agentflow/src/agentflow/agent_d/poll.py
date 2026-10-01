"""角色 D 的动作 `poll`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, IX, S, _UNSPECIFIED

class _Poll:
    def poll(self, *, relations: Any = _UNSPECIFIED) -> dict:
        """检查等待中的请求，把就绪的问题拉回 ``researching``（§4.2 + §3.2）。

        为什么这一步不能靠猜：D 每轮开头能看到"库里多了几篇文献"，
        但无法判断这些文献是不是我提的请求带回来的 —— 只有在
        ``waiting_request_ids`` 里记过请求号的 D 才知道该等谁。
        本方法只依据三样落盘数据判断（请求 ``done``/``outcome``、
        文献 ``processed``），因此不需要 LLM，也不会随措辞变化而漂移。

        ## §3.2：再加一层"新证据真的回答了那个问题吗"

        旧判据（请求 done 且其文献都 processed）只说明"消化完了"，
        不说明"这些新证据真的回答了那个问题"。后果是：一个查不到东西的问题
        会反复触发同一件事的检索，把 A 的产能烧在同一个空洞上。
        所以这里把该请求带来的新落库关系交给
        ``interactions.evidence_relevance``：

        - ``relevant`` ⇒ 就绪，按原逻辑拉回 researching 并并入新关系/文献；
        - ``irrelevant`` ⇒ 不推进，notes 记 ``evidence_arrived_but_irrelevant``，
          并降低该问题优先级（high→medium→low，low 不再降）；
        - ``checked is False`` ⇒ 不推进，且只记"没检查"
          （``evidence_relevance_unchecked``）—— 绝不写成一个看起来像结论的
          "不相关"。

        ``relations=None`` 显式表示"调用方无法提供关系快照"（三态），
        与"提供了空列表 = 查了、这批文献没带来新关系"必须能区分。

        ## 为什么矛盾问题不降优先级

        ``kind="contradiction"`` 的优先级来自"知识内部可能互相冲突"这一事实，
        它不会因为一次检索落空而变得不重要；I2 的收敛靠轮数上限 + 全局配额
        而不是靠降优先级。所以那一类只记笔记、不改 priority。
        """
        data = self._call("research.poll_waiting")
        if data is None:
            return {"ok": False, "error": "research.poll_waiting 调用失败", "ready": [], "waiting": []}
        ready = list(data.get("ready") or [])
        waiting = list(data.get("waiting") or [])
        promoted: list[str] = []
        merged: dict[str, list[str]] = {}
        held: list[dict] = []
        relevance_map: dict[str, dict] = {}

        if ready:
            with self.store.tx("research_questions", "relations", actor=self.actor, note="poll") as tx:
                if relations is _UNSPECIFIED:
                    rels: list[dict] = tx.rows("relations")
                    can_check = True
                elif relations is None:
                    rels = []
                    can_check = False  # 调用方明确表示"没有能力提供关系快照"
                else:
                    rels = [dict(r) for r in relations]
                    can_check = True
                for item in ready:
                    qid = str(item.get("question_id"))
                    qrow = tx.find("research_questions", question_id=qid)
                    if qrow is None or qrow.get("status") not in ("needs_evidence", "open"):
                        continue
                    cids = set(qrow.get("related_concept_ids") or [])
                    new_lits = {str(x) for x in (item.get("new_lit_ids") or [])}
                    #: "这些文献新落库的关系" = 该请求带回来的文献所产生的关系。
                    candidate_rels = (
                        [r for r in rels if str(r.get("lit_id") or "") in new_lits] if can_check else []
                    )
                    relevance = IX.evidence_relevance(
                        qrow, new_relations=candidate_rels if can_check else None
                    )
                    relevance["question_id"] = qid
                    relevance["new_relation_count"] = len(candidate_rels)
                    relevance_map[qid] = relevance

                    if not relevance.get("checked"):
                        # ---- 三态之"没查"：既不推进，也不当作"不相关"，更不降级
                        line = (
                            f"[poll] evidence_relevance_unchecked：{relevance.get('reason')}"
                            " ⇒ 本轮不推进（这是「没检查」，不是「不相关」；等待集与优先级都不动）"
                        )
                        qrow["notes"] = self._append_note_once(qrow, line)
                        qrow["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", qrow).validate()
                        tx.upsert("research_questions", qrow, note="poll_unchecked")
                        held.append({"question_id": qid, "why": "unchecked", "reason": relevance.get("reason")})
                        continue
                    if relevance.get("relevance") != "relevant":
                        # ---- 证据到了但与问题无关：不推进 + 降优先级（§3.2）
                        line = (
                            f"[poll] evidence_arrived_but_irrelevant: 新到 {len(candidate_rels)} 条关系"
                            f"（文献 {sorted(new_lits)}），没有一条落在本问题的概念集 "
                            f"{sorted(cids)} 上 ⇒ 不推进，避免反复检索同一个空洞"
                        )
                        before = str(qrow.get("priority") or "")
                        if str(qrow.get("kind") or "gap") == "contradiction":
                            line += (
                                "；但本问题是矛盾驱动（kind=contradiction），其优先级来自"
                                "「知识内部可能互相冲突」，不因一次检索落空而降级"
                                "（I2 的收敛靠轮数上限与全局配额）"
                            )
                        else:
                            line += f"；优先级 {before} → {self._lower_priority(qrow)}"
                        qrow["notes"] = self._append_note_once(qrow, line)
                        qrow["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", qrow).validate()
                        tx.upsert("research_questions", qrow, note="poll_irrelevant")
                        held.append(
                            {"question_id": qid, "why": "irrelevant", "priority_before": before,
                             "priority": qrow.get("priority")}
                        )
                        continue

                    new_rids = sorted(
                        str(r.get("relation_id"))
                        for r in rels
                        if cids & set(r.get("concept_ids") or [])
                        and str(r.get("relation_id")) not in set(qrow.get("related_relation_ids") or [])
                    )
                    qrow["related_relation_ids"] = S.sorted_unique(
                        list(qrow.get("related_relation_ids") or []) + new_rids
                    )
                    qrow["evidence_lit_ids"] = S.sorted_unique(
                        list(qrow.get("evidence_lit_ids") or []) + list(item.get("new_lit_ids") or [])
                    )
                    qrow["status"] = "researching"
                    qrow["updated_at"] = self._stamp()
                    line = (
                        f"[poll] 等待的请求 {item.get('waiting_request_ids')} 已结束且文献已被 B 消化，"
                        f"新并入 {len(new_rids)} 条关系 / {len(item.get('new_lit_ids') or [])} 篇文献 => researching；"
                        f"证据相关性判据：relevant（落在问题概念集上的新关系 "
                        f"{relevance.get('relevant_relation_ids')}）"
                    )
                    qrow["notes"] = (qrow.get("notes") or "") + "\n" + line
                    qrow["notes"] = qrow["notes"][:20000]
                    S.row_from_dict("research_questions", qrow).validate()
                    tx.upsert("research_questions", qrow, note="poll_promote")
                    promoted.append(qid)
                    merged[qid] = new_rids

        self.last_poll = {
            "ok": True,
            "ready": [i.get("question_id") for i in ready],
            "waiting": [i.get("question_id") for i in waiting],
            "promoted": promoted,
            "merged_relations": merged,
            "held": held,
            "relevance": relevance_map,
            "counts": data.get("counts") or {},
            "reasons": {i.get("question_id"): i.get("reason") for i in waiting},
        }
        return self.last_poll
