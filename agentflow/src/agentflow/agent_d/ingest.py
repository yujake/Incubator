"""角色 D 的动作 `ingest`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Any, IX, Mapping, S, _as_report_dict

class _Ingest:
    def ingest(self, report: Any, *, c_contradictions: Mapping[str, Any] | None = None) -> list[str]:
        """读 C 报告 → 提取候选问题 → 建 ``research_questions`` 行。

        返回新建的 ``question_id`` 列表（只有新建的）。
        每份报告最多提 ``max_questions`` 个（默认 5，§8 待决问题 2）：
        不设上限的话，一份 hottest 报告就能提出几十个问题，D 的循环会被自己的
        产出淹掉，人也读不完。

        ## 三级去重（缺一不可）

        1. 按 ``origin``：同一份报告重复 ingest 是幂等的（同一 ``report_id``）。
        2. 按内容键（:meth:`_content_key`）：不同报告指向同一条关系链时
           不新建行，而是把新来源追加进该问题的笔记里。多份报告指向同一个
           研究点，本身就是"这个点更值得做"的信号 —— 所以既要去重，也要留痕。
        3. 按等价类（§3.1，``interactions.find_equivalent_question``）：
           内容键只覆盖"关系代号完全一样"的情形；同一份报告里两条不同链条
           共享 ≥1 个关系代号（或概念集 Jaccard ≥ 阈值）时，它们说的是同一件事，
           内容键判不出来。这一层把候选的 ``origin`` 合并进已有问题的 notes
           （写成 ``merged_origins: ...``），而不是新建一行。

        "命中等价问题所以没新建"与"新建了"必须能区分：前者进
        ``last_ingest["equivalent_matched"]``，后者进 ``last_ingest["created"]``，
        每个候选的处置都记在 ``last_ingest["decisions"]`` 里（不靠返回值推断 ——
        返回值按既有契约只含新建的 id）。要一个同时给出两者的返回值，
        用 :meth:`ingest_detailed`。

        ## I2：矛盾的吸收

        ``c_contradictions`` 允许调用方把 I1 的 ``c.contradictions()`` 结果直接喂进来；
        不传时按 :meth:`_contradiction_candidates` 的三态顺序取来源（报告 payload →
        C 服务的有界查询）。矛盾候选一律是 ``kind="contradiction"`` + ``priority="high"``。

        Raises
        ------
        Exception
            任何写入期异常（``schema`` 的 ``ValueError``、``store`` 的
            ``StoreError``、``store.tx`` 的锁超时……）。这是刻意的：
            本方法在 ``try/except`` 里先把原因记进 ``last_ingest["error"]``
            （于是"这一轮到底为什么没建成问题"在报告里看得见），然后原样重抛。
            为什么重抛而不是吞掉：``ingest`` 是写路径，半个事务静默成功会让
            上层以为"报告已吸收"，而事实是候选全丢了 —— 那比崩掉更难查。
            这里显式写出来，是因为它原先只在代码里、docstring 只字未提，
            调用方无法从签名/文档判断"要不要自己包一层"（机械审计把它标成
            ``body_raises_but_docstring_silent``）。
        """
        info = _as_report_dict(report)
        self.last_ingest = {
            "report_id": info["report_id"],
            "kind": info["kind"],
            "candidates": [],
            "skipped": [],
            "merged": [],
            "equivalent_matched": [],
            "decisions": [],
            "contradictions": {},
        }
        if info["kind"] not in self.enabled_kinds:
            self.last_ingest["skipped"].append(f"kind={info['kind']} 不在 enabled_kinds={self.enabled_kinds}")
            return []

        candidates = self._candidates_from(info)
        contra = self._contradiction_candidates(info, c_contradictions)
        self.last_ingest["contradictions"] = {
            "source": contra["source"],
            "checked": contra["checked"],
            "reason": contra["reason"],
            "raw_count": contra["raw_count"],
            "skipped": contra["skipped"],
            "weak_clues": contra["weak_clues"],
        }
        candidates = candidates + contra["candidates"]
        self.last_ingest["candidates"] = [
            {"origin": c["origin"], "kind": c["kind"], "priority": c["priority"],
             "question_kind": c.get("question_kind", "gap"),
             "content_key": list(self._content_key(c["kind"], c["related_concept_ids"], c["related_relation_ids"]))}
            for c in candidates
        ]
        if not candidates:
            self.last_ingest["skipped"].append("payload 里没有可识别的结构化发现（见 _candidates_from 的假设形状）")
            # 没有候选问题不等于"弱线索可以丢"：它仍要落进台账/报告（但同样不追问）。
            if contra["weak_clues"]:
                self.last_ingest["weak_clues_noted"] = self._note_weak_clues(contra["weak_clues"])
            return []

        # 排序：priority 高在前，再按 origin 稳定排序 —— 截断时被丢掉的必须是
        # "最不重要"的那几个，而不是"恰好排在后面"的那几个。
        prio_rank = {p: i for i, p in enumerate(S.PRIORITIES)}
        candidates.sort(key=lambda c: (prio_rank.get(c.get("priority"), 9), str(c.get("origin") or "")))

        rows_now = self.store.rows("research_questions")
        existing_origins = {str(r.get("origin")) for r in rows_now} if self.dedup_by_origin else set()
        #: 内容键 -> 已存在问题号。每次 ingest 都从盘上重建，因此跨进程/跨轮次
        #: 都能识别"另一份报告提过同一个研究点"。
        by_key: dict[tuple, str] = {}
        for r in rows_now:
            key = self._content_key(
                self._kind_of_origin(str(r.get("origin") or "")),
                r.get("related_concept_ids") or [],
                r.get("related_relation_ids") or [],
            )
            by_key.setdefault(key, str(r.get("question_id")))
        #: §3.1 的等价类匹配要看到本次 ingest 里刚建出来的行，否则同一份报告内
        #: 的两条等价链（第 2 条共享第 1 条的关系代号）谁也看不见谁，还是会建两条。
        working: list[dict] = [dict(r) for r in rows_now]
        decisions: list[dict] = self.last_ingest["decisions"]

        new_ids: list[str] = []
        merged: list[dict] = []
        equivalent: list[dict] = []
        try:
            with self.store.tx("research_questions", actor=self.actor, note="ingest") as tx:
                for cand in candidates:
                    if len(new_ids) >= self.max_questions:
                        self.last_ingest["skipped"].append(
                            f"达到 max_questions={self.max_questions}，其余候选被截断（防爆炸，§8 待决问题 2）"
                        )
                        break
                    key = self._content_key(cand["kind"], cand["related_concept_ids"], cand["related_relation_ids"])
                    hit = by_key.get(key)
                    if hit is not None:
                        # ---- 内容等价：不新建行，只把新来源追加进去
                        row = tx.find("research_questions", question_id=hit)
                        if row is None:
                            continue
                        note = (
                            f"[ingest] 另见报告 {info['report_id']}（kind={info['kind']}）的同一条链："
                            f"origin={cand['origin']}。多份报告指向同一研究点 = 该点更值得做的信号。"
                        )
                        old = row.get("notes") or ""
                        if note not in old:
                            row["notes"] = (old + "\n" + note)[:20000]
                        # 重复出现且优先级更高时提升优先级（信号更强，不是更弱）
                        if prio_rank.get(cand["priority"], 9) < prio_rank.get(row.get("priority"), 9):
                            row["priority"] = cand["priority"]
                        row["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", row).validate()
                        tx.upsert("research_questions", row, note=f"ingest_merge:{info['report_id']}")
                        merged.append({"question_id": hit, "origin": cand["origin"], "from_report": info["report_id"]})
                        decisions.append({"origin": cand["origin"], "action": "merged_by_content_key", "question_id": hit})
                        continue
                    if self.dedup_by_origin and cand["origin"] in existing_origins:
                        self.last_ingest["skipped"].append(f"origin 已存在：{cand['origin']}")
                        decisions.append({"origin": cand["origin"], "action": "skipped_origin_exists"})
                        continue
                    # ---- §3.1 等价类：内容键之外的第二层判据
                    eq = IX.find_equivalent_question(
                        working,
                        concept_ids=cand["related_concept_ids"],
                        relation_ids=cand["related_relation_ids"],
                    )
                    if eq and eq.get("matched") and eq.get("question_id"):
                        row = tx.find("research_questions", question_id=str(eq["question_id"]))
                        if row is not None:
                            note = (
                                f"merged_origins: {cand['origin']}（§3.1 等价类命中：{eq.get('detail')}；"
                                f"来源报告 {info['report_id']}）"
                            )
                            old = row.get("notes") or ""
                            if cand["origin"] not in old:
                                row["notes"] = (old + "\n" + note)[:20000]
                            if prio_rank.get(cand["priority"], 9) < prio_rank.get(row.get("priority"), 9):
                                row["priority"] = cand["priority"]
                            row["updated_at"] = self._stamp()
                            S.row_from_dict("research_questions", row).validate()
                            tx.upsert("research_questions", row, note=f"ingest_equivalent:{info['report_id']}")
                            equivalent.append(
                                {
                                    "question_id": str(eq["question_id"]),
                                    "origin": cand["origin"],
                                    "by": eq.get("by"),
                                    "detail": eq.get("detail"),
                                    "from_report": info["report_id"],
                                }
                            )
                            decisions.append(
                                {"origin": cand["origin"], "action": "merged_by_equivalence",
                                 "question_id": str(eq["question_id"]), "by": eq.get("by")}
                            )
                            continue
                    qid = tx.alloc_id("question")
                    row = S.ResearchQuestion(
                        question_id=qid,
                        question=cand["question"],
                        origin=cand["origin"],
                        # 代号溯源：问题必须带着"它从哪条链/哪个概念来"，否则
                        # 报告里的结论无法被回到关系表里去核对。
                        related_concept_ids=S.sorted_unique(cand["related_concept_ids"]),
                        related_relation_ids=S.sorted_unique(cand["related_relation_ids"]),
                        status="open",
                        priority=cand["priority"],
                        # I2：矛盾驱动的问题必须显式带 kind 与矛盾对，不靠解析 origin 字符串。
                        kind=str(cand.get("question_kind") or "gap"),
                        contradiction_relation_ids=S.sorted_unique(cand.get("contradiction_relation_ids") or []),
                        notes=f"[ingest] 来源报告 {info['report_id']}（kind={info['kind']}）。理由：{cand['why']}",
                        created_at=self._stamp(),
                        updated_at=self._stamp(),
                    )
                    row.validate()
                    tx.upsert("research_questions", row.to_dict(), note=f"ingest:{info['kind']}")
                    new_ids.append(qid)
                    existing_origins.add(cand["origin"])
                    by_key[key] = qid
                    working.append(row.to_dict())
                    decisions.append({"origin": cand["origin"], "action": "created", "question_id": qid})
        except Exception as e:
            self.last_ingest["error"] = f"{type(e).__name__}: {e}"
            raise
        self.last_ingest["created"] = new_ids
        self.last_ingest["merged"] = merged
        self.last_ingest["equivalent_matched"] = equivalent

        # ---- 弱线索落痕（I2）：`strength != strong` 的矛盾对不建问题、不追问，
        # 但也不能丢 —— 它们可能在别的证据到位后变成真问题。落点有两个：
        #   1. 与该线索共享关系代号的已有问题的 notes（研究台账里看得到）；
        #   2. `last_ingest["contradictions"]["weak_clues"]` + 报告审计一节。
        if contra["weak_clues"]:
            self.last_ingest["weak_clues_noted"] = self._note_weak_clues(contra["weak_clues"])
        return new_ids
