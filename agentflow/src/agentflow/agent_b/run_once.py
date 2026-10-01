"""角色 B 的动作 `run_once`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import BRunResult, D, I, Iterable, QUOTE_OUT_OF_DECLARED_RANGE, S, T, check_quote

class _RunOnce:
    def run_once(self) -> BRunResult:
        """处理至多一篇未处理文献，返回本轮的完整审计结果。

        三态纪律在这里有两个落点：

        1. 取不到文献不等于"队列空了"：`skipped_reason` 由 `_claim()` 的三态给出
           （`no_unprocessed_literature` / `pending_literature_all_leased` /
           `no_claimable_literature`），并同时暴露 `skipped_lease_active` / `gave_up`
           两个计数。原先无论哪种情况都写"no_unprocessed_literature"，是误导运维。
        2. 抽取失败不等于处理完了：不置 `processed`，只留 `last_mine_error`，
           由租约到期重试（模块 docstring 第 4 条）。
        """
        res = BRunResult()
        claim = self._claim()
        # 取文献侧的审计信息先落进结果，再决定要不要早退 —— 否则"有活但全被别人
        # 占着"这类信息会随着 skipped_reason 一起丢掉，外部只剩一个"什么都没做"。
        res.skipped_lease_active = claim.skipped_lease_active
        res.gave_up = claim.gave_up
        lit = claim.literature
        if lit is None:
            res.skipped_reason = claim.skipped_reason
            return res

        lit_id = lit["lit_id"]
        dl_status = (lit.get("download") or {}).get("status")
        path = self.store.library_path(lit.get("path"))
        # 三种"没有可抽取内容"的情况都要标为已处理并记明原因，否则它们会永远
        # 堵在队首（每次 run 都重新领取同一行）。注意 content_mismatch 单独列出来：
        # 文件其实存在（是证据），只是它按内容类型判定不是论文 —— 实测碰到过
        # 12.4 MB 的 HTML 被当成 PDF 存下来，若照常抽取会把网页导航文字当概念。
        unreadable_reason = None
        if dl_status == "content_mismatch":
            unreadable_reason = f"content_type_mismatch: {path.name if path else '?'}"
        elif path is None:
            unreadable_reason = "no_local_file"
        elif not path.exists():
            unreadable_reason = f"file_missing:{path}"

        if unreadable_reason is not None:
            with self.store.tx("literature", actor=self.actor, note="unreadable") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["processed"] = True
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = unreadable_reason
                tx.upsert("literature", row, note="skipped_unreadable")
            res.unreadable += 1
            res.processed = 1
            res.details.append({"lit_id": lit_id, "stage": "acquire", "skipped": unreadable_reason})
            return res

        # ---- `R-56`：回退抽取器拒抽（判据与理由见 `__init__` 里那一段）。
        # 位置在"不可读"之后：没有文件的行该报 `no_local_file`（原因不同），
        # 而这一条说的是"有文件、但我们没有够格的抽取器"。
        if self.extractor_is_fallback:
            with self.store.tx("literature", actor=self.actor, note="no_extractor") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = "no_llm_extractor"
                # 刻意不置 `processed`：接线 LLM 之后这一行还要被重新领到
                tx.upsert("literature", row, note="skipped_no_extractor")
            res.skipped_no_extractor += 1
            res.details.append({"lit_id": lit_id, "stage": "extract",
                                "skipped": "no_llm_extractor",
                                "why": "规则回退抽取器会把碎片当概念/关系（R-56）"})
            return res

        try:
            doc = self.extract_text(path)
            concepts, relations = self.extractor.extract(
                doc, lit_id, self._extraction_meta(lit)
            )
        except Exception as e:
            # 抽取失败：不置 processed，让租约过期后重试
            with self.store.tx("literature", actor=self.actor, note="extract_failed") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = f"{type(e).__name__}: {e}"
                tx.upsert("literature", row, note="extract_failed")
            res.failed += 1
            res.details.append({"lit_id": lit_id, "stage": "extract", "error": f"{type(e).__name__}: {e}"})
            return res

        # ---- 引文校验（无锁；只依赖文档）
        verified_rels: list[dict] = []
        for rel in relations:
            chk = check_quote(
                doc,
                getattr(rel, "quote", "") or "",
                getattr(rel, "page_range", None),
                widen=self.widen_pages,
                allow_fulltext_fallback=self.allow_fulltext_fallback,
            )
            if chk.verified is True:
                res.quotes_verified += 1
                # `E-11`：引文逐字存在、但落在声明的页码之外。判据取 `reason`
                # 而不是 `window` 前缀（`check_quote` 里只有这一条分支会给出这个
                # reason，见 `quoteverify.check_quote` 的 widen 分支）。
                if chk.reason == QUOTE_OUT_OF_DECLARED_RANGE:
                    res.quotes_out_of_declared_range += 1
            elif chk.verified is False:
                res.quotes_failed += 1
            else:
                res.quotes_unknown += 1
            verified_rels.append({"rel": rel, "check": chk})

        # ---- 提交（锁内，短）
        with self.store.tx("literature", "concepts", "relations", actor=self.actor, note="commit") as tx:
            concept_rows = tx.rows("concepts")
            relation_rows = tx.rows("relations")
            touched: set[str] = set()

            def resolve_concept(name: str, definition: str = "", aliases: Iterable[str] | None = None) -> str:
                nonlocal concept_rows
                existing = D.find_concept(concept_rows, name, list(aliases or []))
                if existing is not None:
                    # 合并别名（需求未要求，但别名不合并会导致后续同义名重复建概念）
                    merged = S.sorted_unique(list(existing.get("aliases") or []) + [name] + list(aliases or []))
                    merged = [a for a in merged if T.normalize(a) != (existing.get("normalized_name") or "")]
                    if merged != (existing.get("aliases") or []):
                        existing["aliases"] = merged
                        existing["updated_at"] = S.now_iso()
                        tx.upsert("concepts", existing, note="alias_merge")
                    res.concepts_reused += 1
                    return existing["concept_id"]
                cid = tx.alloc_id("concept")
                row = S.Concept(
                    concept_id=cid,
                    name=name,
                    definition=definition,
                    related_concepts=[],
                    normalized_name=T.normalize(name),
                    aliases=[a for a in S.sorted_unique(list(aliases or [])) if T.normalize(a) != T.normalize(name)],
                    definition_source_lit_id=lit_id if definition else None,
                    created_at=S.now_iso(),
                    updated_at=S.now_iso(),
                )
                row.validate()
                d = row.to_dict()
                concept_rows.append(d)
                tx.upsert("concepts", d, note="created")
                res.concepts_created += 1
                return cid

            # 1) 显式概念草稿先建（它们带定义，是概念的权威来源）
            for cd in concepts:
                resolve_concept(cd.name, cd.definition, cd.aliases)

            # 2) 关系：解析概念 → 判重 → 写入
            written: list[str] = []
            for item in verified_rels:
                rel = item["rel"]
                chk = item["check"]
                names = [n for n in (getattr(rel, "concept_names", []) or []) if n and n.strip()]
                if len(names) < 2:
                    res.details.append(
                        {"lit_id": lit_id, "stage": "relation", "skipped": "fewer_than_two_concepts", "names": names}
                    )
                    continue
                cids = S.sorted_unique(resolve_concept(n) for n in names)
                if len(cids) < 2:
                    res.details.append(
                        {"lit_id": lit_id, "stage": "relation", "skipped": "concepts_collapsed", "names": names}
                    )
                    continue

                quote = getattr(rel, "quote", "") or ""
                description = getattr(rel, "description", "") or ""
                group_key = T.concept_group_key(cids)
                decision = D.decide_relation(
                    relation_rows,
                    concept_group_key=group_key,
                    quote=quote,
                    description=description,
                    dup_strong=self.dup_strong,
                    dup_review=self.dup_review,
                )
                if decision.kind == "duplicate":
                    res.relations_duplicate += 1
                    res.details.append(
                        {
                            "lit_id": lit_id,
                            "stage": "relation",
                            "skipped": "duplicate",
                            "duplicate_of": decision.existing_id,
                            "score": round(decision.score, 4),
                        }
                    )
                    continue

                rid = tx.alloc_id("relation")
                # 引文校验失败/无法校验 → 降级为 suspect（不丢弃，保留证据）
                quote_failed = chk.verified is not True
                status = decision.status
                if quote_failed:
                    status = "suspect"
                pr = getattr(rel, "page_range", None)
                if not isinstance(pr, S.PageRange):
                    pr = S.PageRange.from_dict(pr if isinstance(pr, dict) else None)

                # ---- I6 写入期一致性闸门 ----
                # 已有关系必须在同一个 tx 内读（`_conflict_scope`），再交给纯函数：
                # 闸门里没有 store，因此不可能在这里重入 filelock（见模块 docstring 第 5 条）。
                # 代价是它只能看见"本事务已经读到的图"—— 这正是我们想要的语义：
                # 检查的是"按我即将提交的视图，这条矛盾吗"。
                draft = {
                    "relation_id": rid,
                    "concept_ids": list(cids),
                    "concept_group_key": group_key,
                    "statement": description,
                    "description": description,
                    "quote": quote,
                    "lit_id": lit_id,
                }
                cinfo = I.check_conflict(draft, existing_relations=self._conflict_scope(tx))
                if cinfo.get("checked"):
                    res.conflict_checks_run += 1
                else:
                    # 三态纪律：`checked=False` 不是"不冲突"。
                    # 行里会留下 `_conflict_check.checked=False` 作为证据，
                    # 同时计数器 +1，让"没检查"在统计里也看得见。
                    res.conflict_checks_skipped += 1
                    res.details.append(
                        {
                            "lit_id": lit_id,
                            "stage": "conflict_gate",
                            "skipped": "conflict_check_unavailable",
                            "reason": cinfo.get("reason"),
                        }
                    )
                conflicts_with = list(cinfo.get("conflicts_with") or []) if cinfo.get("conflict") else []
                if cinfo.get("conflict") is True:
                    # 矛盾比"引文可疑"更强，但落库动作相同：照写 + 标黄。
                    # 丢掉它等于隐藏最值钱的信号（文献之间的真实分歧）。
                    res.conflicts_detected += 1
                    status = "suspect"

                row = S.Relation(
                    relation_id=rid,
                    concept_ids=cids,
                    description=description,
                    lit_id=lit_id,
                    page_range=pr,
                    quote=quote,
                    quote_normalized=T.normalize_for_quote(quote),
                    quote_verified=chk.verified,
                    statement=description,
                    concept_group_key=group_key,
                    dedup_key=D.relation_dedup_key(group_key, quote),
                    status=status,
                    duplicate_of=decision.existing_id if decision.kind == "suspect" else None,
                    created_at=S.now_iso(),
                )
                row.validate()
                d = row.to_dict()
                d["_quote_check"] = chk.to_dict()
                # 诊断字段一律带上：即使"检查过、不冲突"也留痕，否则无法区分
                # "闸门说没问题"与"闸门根本没跑"。
                d["_conflict_check"] = cinfo
                if conflicts_with:
                    d["conflicts_with"] = conflicts_with
                relation_rows.append(d)
                tx.upsert("relations", d, note=f"status:{status},quote:{chk.reason},conflict:{cinfo.get('conflict')}")
                written.append(rid)
                touched.update(cids)
                # 按最终落库状态计数，而不是按判重结论计数：
                # 引文校验失败、以及 I6 闸门发现矛盾，都会把 status 降级为 suspect，
                # 只统计判重那条路径会让报告的 suspect 数与表里的实际条数对不上。
                if status == "suspect":
                    res.relations_suspect += 1
                    if quote_failed and decision.kind != "suspect":
                        res.suspect_by_quote += 1
                else:
                    res.relations_added += 1

            # 3) 概念自身涉及的旧关系也要重算 related_concepts（例如新建的概念与既有概念相连）
            for d in relation_rows:
                if d.get("lit_id") == lit_id or set(d.get("concept_ids") or []) & touched:
                    touched.update(d.get("concept_ids") or [])

            # 4) 由关系表整体派生 related_concepts
            for cid in sorted(touched):
                target = next((c for c in concept_rows if c["concept_id"] == cid), None)
                if target is None:
                    continue
                want = D.derive_related_concepts(cid, relation_rows, include_suspect=True)
                if target.get("related_concepts") != want:
                    target["related_concepts"] = want
                    target["updated_at"] = S.now_iso()
                    tx.upsert("concepts", target, note="related_recomputed")

            # 5) 标记文献处理完成（与实体写入同一事务 —— 见 DESIGN.md §2.4）
            lit_row = tx.find("literature", lit_id=lit_id) or lit
            lit_row["processed"] = True
            lit_row["claimed_by"] = None
            lit_row["lease_until"] = None
            lit_row["last_mine_error"] = None
            tx.upsert("literature", lit_row, note="processed")
            res.processed = 1

        return res
