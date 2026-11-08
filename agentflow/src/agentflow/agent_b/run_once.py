"""角色 B 的动作 `run_once`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import BRunResult, D, I, Iterable, NO_EXTRACTOR_ERROR, QUOTE_OUT_OF_DECLARED_RANGE, S, T, check_quote, make_lease
from .. import conceptrows as _CR   # 并表过渡层：老表写完同步一份新标准（两处同号）
from .. import litread as _LR       # M2/M3：`path` 两基准解析 + `download.fulltext` 三档的唯一实现
from .. import quoteevidence as _QE   # D1：三态判决 ⇒ 可复核的区间/理由/调用指纹
from ..extract import DocumentText as _DT
from pathlib import Path as _Path


class _RunOnce:
    #: 工作区里那份「正文」的候选落点（审阅型项目：`out/paper/main.tex` 是可改稿，
    #: `source/main.tex` 是只读基线）。逐字档先试它 —— 理由见 `_manuscript_doc`。
    MANUSCRIPT_RELS: tuple[str, ...] = ("out/paper/main.tex", "source/main.tex")

    def _manuscript_doc(self) -> tuple[object | None, str, str]:
        """工作区那份正文的文本视图：返回 `(doc, 用的是哪一份, 读不出来的原因)`。

        为什么要它（业主 2026-10-14 的两档口径）：「逐字命中是第一档、且不花模型钱」，
        而审阅型项目里的引文常常逐字取自工作区那份 LaTeX 正文（作者自己的稿子）——
        文献 PDF 却因为页码是估算的、或者正文在 LaTeX 源里而不在 PDF 的可抽层里，
        于是"真逐字"的引文落到第二档去问模型（既有判错的风险，又白花钱）。

        这一档「不另写判据」：仍然把材料交给 `quoteverify.check_quote` 那一个实现，
        只换一份材料（`DocumentText(pages=[全文])`），并把"命中的是哪一份文件"
        写进关系的 `quote_reason` —— 读数不说清来路，就等于把两种证据混成一种。
        """
        try:
            root = _Path(self.store.root)
        except Exception as exc:  # noqa: BLE001 - 读不到工作区根就是"没有这份材料"
            return None, "", f"工作区根读不出来（{type(exc).__name__}: {exc}）"
        for rel in self.MANUSCRIPT_RELS:
            path = root / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return None, "", f"{rel} 读不出来：{type(exc).__name__}: {exc}"
            if not text.strip():
                continue
            return _DT(text=text, pages=[text], source_kind="tex"), rel, ""
        return None, "", "工作区里没有 out/paper/main.tex 也没有 source/main.tex"

    def run_once(self) -> BRunResult:
        """处理至多一篇未处理文献，返回本轮的完整审计结果。
        ## 概念配额（2026-10-21，本批缺陷一第三处：一轮灌进 1143 条）
        配额是「轮」预算，挂在实例上（`self._concept_quota`）：`B.run` 在轮首建一个、逐篇共用；单独调 `run_once()` 时这一调用自己建一个（上
        限 `conceptrows.CONCEPTS_PER_ROUND_MAX`）—— 于是"每轮几十条以内"这条口径在两条入口上都成立，而不会因为"没人传"就变成无限。
        为什么挂在实例上而不是加一个形参：`run_once` 的方法签名在`tests/golden/agent_surface_snapshot.json` 里被冻结（禁改区），
        改签名等于重冻那份快照 —— 而"这一轮建了多少概念"是「轮」状态，本来也不该出现在动作的调用面上（模型不该能传一个配额进来）。
        1. 取不到文献不等于"队列空了"：`skipped_reason` 由 `_claim()` 的三态给出（`no_unprocessed_literature` / 
        `pending_literature_all_leased` /`pending_literature_all_in_backoff` / 
        `no_claimable_literature`），并同时暴露`skipped_lease_active` / `skipped_lease_backoff` / 
        `gave_up` 三个计数。 2. 抽取失败不等于处理完了：不置 `processed`，只留 `last_mine_error`，并写下一条退避租约（`D-2`：写了就
        必须有人认它 —— `_claim` 的跳过判据在 2026-10-02 之前要求 `claimed_by` 非空，于是这条租约写了等于没写）。
        """
        res = BRunResult()
        # 概念配额：`B.run` 在轮首放好的那个（`self._concept_quota`）优先；
        # 单跑一篇时这里建一个（上限同源）—— 口径见方法 docstring。
        quota = getattr(self, "_concept_quota", None)
        if not isinstance(quota, _CR.ConceptQuota):
            quota = _CR.ConceptQuota()
            self._concept_quota = quota
        claim = self._claim()
        # 领取前归一化掉了哪些存量 `library/` 前缀行 —— 改盘必须可查（缺陷 1 的处置读数）。
        if claim.path_normalizations:
            res.details.append({"stage": "claim",
                                "normalized_paths": list(claim.path_normalizations)})
        # 取文献侧的审计信息先落进结果，再决定要不要早退 —— 否则"有活但全被别人
        # 占着"这类信息会随着 skipped_reason 一起丢掉，外部只剩一个"什么都没做"。
        res.skipped_lease_active = claim.skipped_lease_active
        res.skipped_lease_backoff = claim.skipped_lease_backoff
        res.gave_up = claim.gave_up
        lit = claim.literature
        if lit is None:
            res.skipped_reason = claim.skipped_reason
            return res

        lit_id = lit["lit_id"]
        dl_status = (lit.get("download") or {}).get("status")
        # ---- M2（2026-11-05）：`literature.path` 的读侧有两个基准，而抽取入口改前
        # 只走 `store.library_path`（只认 `library/`）。写入侧 `_adopt_file` 明写
        # 「先 `library/`，不存在再按 workspace」—— 于是一条按工作区相对写下的
        # `library/000001/…` 在这里被解析成 `library/library/000001/…`，判
        # `file_missing`，而读数上"文件真的不在"与"在另一个基准下"同形。
        # 解析口径不另发明：`litread.resolve_literature_path` 与 `search_tools._lit_file`
        # 同一套（先 library、再 workspace、两条路都钉在工作区内），区别只有一条 ——
        # workspace 回退只对以 `library/` 开头的串启用（其余旧行仍只认 `library/`）。
        #
        # 缺陷 1（2026-11-05）之后：存量 `library/…` 行在 `_claim` 里已经归一并落盘，
        # 所以这里若照常解盘上那一份，`path_base=workspace` 永远不会出现。`_claim`
        # 因此把"归一化之前解原串"的读数一起带回来 —— 那个读数才是"这一行当时
        # 按哪个基准读得到"的证据，`res.path_base` 用它。
        legacy = claim.legacy_path_reading
        if legacy is not None:
            resolved = legacy["resolution"]
        else:
            resolved = _LR.resolve_literature_path(self.store.root, self.store.library,
                                                   lit.get("path"))
        path = resolved.path
        if path is not None:
            # 哪一基准解析的必须能读出来：`path_base=workspace` 是这一档的唯一读数，
            # 没有它，下次再有人读到 `file_missing` 仍然分不清是"没文件"还是"基准错"。
            res.path_base = resolved.base
            detail = {"lit_id": lit_id, "stage": "resolve",
                      "path_base": resolved.base,
                      "path": str(lit.get("path") or ""),
                      "resolved": str(path)}
            if legacy is not None:
                # 归一化改了盘：这里同时给出归一化前那一串（`path_base` 是对它解的）。
                detail["path_before_normalize"] = legacy["before"]
                detail["normalized_to"] = legacy["after"]
            res.details.append(detail)
        # 三种"没有可抽取内容"的情况都要标为已处理并记明原因，否则它们会永远
        # 堵在队首（每次 run 都重新领取同一行）。注意 content_mismatch 单独列出来：
        # 文件其实存在（是证据），只是它按内容类型判定不是论文 —— 实测碰到过
        # 12.4 MB 的 HTML 被当成 PDF 存下来，若照常抽取会把网页导航文字当概念。
        unreadable_reason = None
        if dl_status == "content_mismatch":
            unreadable_reason = f"content_type_mismatch: {path.name if path else '?'}"
        elif not str(lit.get("path") or "").strip():
            # 行上没有本地字节，但可能带着定位符（一键迁移登记的行会把候选 url
            # 写进 `download.url`，并标 `fulltext=no_fulltext`）。
            # 那种情形的原因必须点到定位符：一句说不出位置的原因，在读数上与
            # "这一篇从哪来都不知道"同形 —— 而两者的处置相反（前者可以按 url
            # 重取，后者要人去补来源）。
            dl_row = dict(lit.get("download") or {})
            locator = str(dl_row.get("url") or "").strip()
            unreadable_reason = (f"no_fulltext_this_time: {locator}" if locator
                                 else "no_local_file")
        elif path is None:
            # 两个基准都不存在 ⇒ 原因里必须写出「两个」候选绝对路径（只写一个会让
            # "另一个基准下其实有文件"这件事在读数上消失，`file_missing` 也就说不出
            # 到底试过哪两处）。
            unreadable_reason = resolved.reason

        if unreadable_reason is not None:
            with self.store.tx("literature", actor=self.actor, note="unreadable") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["processed"] = True
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = unreadable_reason
                # ---- M3（2026-11-05）：这一支是"这一趟没抽"的落点，`download.fulltext`
                # 要按「盘上事实」现算一次：没有字节 ⇒ `no_fulltext`；有字节（例如
                # content_mismatch 存下来的落地页）⇒ 这一处没抽过文本 ⇒ 不算档（None），
                # 由 `with_fulltext` 把改前留下的旧标签清掉。写点与清除点是同一个函数。
                row["download"] = _LR.with_fulltext(
                    dict(row.get("download") or {}),
                    _LR.fulltext_tier(bytes_on_disk=_LR.bytes_on_disk(path), pages=None))
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
                # 刻意不置 `processed`：接线 LLM 之后这一行还要被重新领到。
                # 但要留退避租约（`D-2`）：这一档不是"抽取出错"，而是"这台机器还没有
                # 够格的抽取器"——不写租约的话每一轮 run 都会把它重领一次，
                # 而 `_claim` 每次都会给它 `mine_attempts += 1` ⇒ 它会因为排队次数
                # 用尽被判死（一次都没真抽过；所以到上限时那句结论必须如实说
                # "从未真抽"，见 `core._give_up_note`）。
                #
                # `R3-⑩` 之后这一档不再烧计数：`mine_attempts` 只在真正调抽取器的
                # 两处 +1，而这一支在调用之前就返回了 ⇒ 它的读数恒为"真抽 0 次"，
                # 那条"用尽"的路也不再可能因为拒抽而触发。这一行只留退避租约，
                # 让下一轮（或接线 LLM 之后）还能重新领到它。
                row["lease_until"] = make_lease(self.lease_seconds)
                row["last_mine_error"] = NO_EXTRACTOR_ERROR
                tx.upsert("literature", row, note="skipped_no_extractor")
            res.skipped_no_extractor += 1
            res.details.append({"lit_id": lit_id, "stage": "extract",
                                "skipped": NO_EXTRACTOR_ERROR,
                                "why": "规则回退抽取器会把碎片当概念/关系（R-56）"})
            return res

        try:
            doc = self.extract_text(path)
            concepts, relations = self.extractor.extract(
                doc, lit_id, self._extraction_meta(lit)
            )
        except Exception as e:
            # 抽取失败：不置 processed，写退避租约让到点后重试（`D-2`：修复前这里
            # 把 `lease_until` 也清成 None，而 `_claim` 的跳过判据要求 `claimed_by`
            # 非空 ⇒ 所谓"让租约过期后重试"其实没有任何租约存在，同一趟里立刻重领）。
            with self.store.tx("literature", actor=self.actor, note="extract_failed") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["claimed_by"] = None
                row["lease_until"] = make_lease(self.lease_seconds)
                row["last_mine_error"] = f"{type(e).__name__}: {e}"
                # `R3-⑩`：真抽过了（抽取器被调用了、抛了）⇒ 这一格 +1。计数点在这里
                # 而不是 `_claim`，理由见 `core._claim` 的 docstring：领取不等于抽取。
                row["mine_attempts"] = int(row.get("mine_attempts") or 0) + 1
                tx.upsert("literature", row, note="extract_failed")
            res.failed += 1
            res.details.append({"lit_id": lit_id, "stage": "extract", "error": f"{type(e).__name__}: {e}"})
            return res

        # ---- 引文校验（无锁；只依赖文档）
        # 逐字那一档先试文献 PDF；「没中再试工作区那份正文」（同一份 `check_quote`，
        # 只换材料）—— 审阅型项目的引文常常逐字取自 `out/paper/main.tex` 那份 LaTeX，
        # 而 PDF 的页码是估算的，于是"真逐字"被推到第二档去花模型钱（还可能判错）。
        mdoc, mrel, mwhy = self._manuscript_doc()
        verified_rels: list[dict] = []
        for rel in relations:
            quote = getattr(rel, "quote", "") or ""
            chk = check_quote(
                doc,
                quote,
                getattr(rel, "page_range", None),
                widen=self.widen_pages,
                allow_fulltext_fallback=self.allow_fulltext_fallback,
            )
            hit_note = ""
            # 命中的是哪一份材料必须跟着判决走：`quoteevidence.enforce_quote_evidence`
            # 要拿"判它的那一份文档"去定位区间（PDF 与工作区 LaTeX 是两种证据，
            # 拿错那一份定位出来的页码是另一个坐标系里的数字）。
            hit_doc = doc
            if chk.verified is not True and mdoc is not None:
                mchk = check_quote(mdoc, quote, None,
                                   widen=self.widen_pages,
                                   allow_fulltext_fallback=True)
                if mchk.verified is True:
                    chk = mchk
                    hit_doc = mdoc
                    hit_note = f"逐字命中工作区正文 {mrel}"
                    res.details.append({"lit_id": lit_id, "stage": "quote_manuscript",
                                        "rel": getattr(rel, "description", "")[:80],
                                        "where": mrel})
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
            verified_rels.append({"rel": rel, "check": chk, "note": hit_note,
                                  "doc": hit_doc})

        # ---- 提交（锁内，短）
        # 声明哪几张表由过渡层决定（`concepts` 落刀之后不再存在 ⇒ 声明它会以"未知表"失败）。
        with self.store.tx(*_CR.tables_for_concept_write("literature", "relations"),
                           actor=self.actor, note="commit") as tx:
            concept_rows = _CR.view_tx(tx, shape="legacy")["rows"]
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
                        # 一处调用同时办两件事：老表还在时先写老表那一份，再同步新标准
                        # （同一个号）；老表已退役 ⇒ 只写新标准。见 conceptrows。
                        _CR.upsert_legacy_shaped(tx, existing, actor=self.actor,
                                                 note="alias_merge")
                    res.concepts_reused += 1
                    return existing["concept_id"]
                # ---- 概念配额（2026-10-21，本批缺陷一第三处）：超上限「受控拒绝」，
                # 不静默丢。拒绝时返回空串，调用方（关系那一段）据此跳过这一条关系，
                # 并把"因为配额被推迟"写进 details —— 于是"这一轮写了多少、还差多少"
                # 在读数上看得见（`res.concepts_refused` / `quota.reading()`）。
                if not quota.admit(name):
                    res.concepts_refused += 1
                    res.details.append({
                        "lit_id": lit_id, "stage": "concept_quota", "refused": str(name),
                        "limit": int(quota.limit), "written": int(quota.written),
                        "why": quota.reading()["why"],
                    })
                    return ""
                # 概念号与命题号是同一个号空间（业主 D2「同表同分配器不可能撞号」）
                # ⇒ 这里从 `stmt` 发号；落刀之后 `concept` 这一档连计数器都没有了。
                #
                # 2026-11-08（D2 后门）：先判同一性、再发号。`conceptrows.upsert`
                # 那条老路的判词在发号之后，判不了只能放过（后门）或留 `id_gap`；
                # 这里在 `alloc_id` 之前过同一个闸（唯一判据 `same_concept`），
                # 没判成 ⇒ 这一条概念受控拒、不占号（关系那一段据此跳过它）。
                from ..secretary import concept_identity_gate as _concept_gate
                _gate = _concept_gate(tx, label=name, full=definition)
                if not _gate.get("checked"):
                    res.concepts_refused += 1
                    res.details.append({
                        "lit_id": lit_id, "stage": "concept_identity",
                        "refused": str(name),
                        "refused_code": "concept_identity_unjudged",
                        "why": str(_gate.get("reason") or ""),
                    })
                    return ""
                cid = tx.alloc_id("stmt")
                row = S.Concept(
                    concept_id=cid,
                    name=name,
                    definition=definition,
                    related_concepts=[],
                    normalized_name=T.normalize(name),
                    aliases=[a for a in S.sorted_unique(list(aliases or [])) if T.normalize(a) != T.normalize(name)],
                    # 这一格记的是"这个术语是从哪一篇抽出来的"（概念行的出处），
                    # 不是"定义逐字抄自那里"。所以「一律」给这一篇：即使定义还没抽到，
                    # 术语的来路也是清楚的 —— 而 `origin` 的正确口径就靠它
                    # （`conceptrows.resolve_concept_origin`：有出处 ⇒ external_lit）。
                    definition_source_lit_id=lit_id,
                    created_at=S.now_iso(),
                    updated_at=S.now_iso(),
                )
                row.validate()
                d = row.to_dict()
                concept_rows.append(d)
                # `sync_from_legacy` 把这一格带进新标准那一行 ⇒ 记成
                # `origin="external_lit"`。真机 mp3 的 1142/1143 条概念行都有文献出处，
                # 却因为写死 `own_result` 被读成"我们自己的结果"（本批缺陷一第二处）。
                _CR.upsert_legacy_shaped(tx, d, actor=self.actor, note="created")
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
                resolved = [resolve_concept(n) for n in names]
                if any(not cid for cid in resolved):
                    # 有概念被配额拒了 ⇒ 这条关系「这一轮」写不了（它要指着一个不存在的号）。
                    # 不许静默丢：逐条点名 + 计数。剩下的按业主的口径"下一轮或写进报告"——
                    # 这一轮的 literature 行照常标 processed（理由见下面那一格），
                    # 所以它的可见形态是「这一趟的结果」，不是"下一轮自己会回来"。
                    res.relations_deferred += 1
                    res.details.append({
                        "lit_id": lit_id, "stage": "relation", "skipped": "concept_quota",
                        "names": names,
                        "why": ("这条关系要用的概念这一轮被配额拒了（见 concept_quota 那一条）⇒"
                                " 关系这一轮不写，读数里点名；剩下的下一轮或写进报告"),
                    })
                    continue
                cids = S.sorted_unique(resolved)
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
                # ---- D1（2026-10-22）：逐字那一档必须留下"核了哪一段、在第几页"。
                #
                # 真机读数：`relations` 这一侧的判决本来是对的（`check_quote` 会回
                # `matched_page` / `window` / `reason`），而落盘只写了 `quote_reason`
                # 一格 —— `quote_span` 与 `quote_call_sha256` 从来没写过。于是"逐字命中"
                # 在盘上只剩一句人话，复核的人找不到那一页的哪一段。
                # 判决不从这一格改：这里只把 `QuoteCheck` 的三态翻成四栏（唯一实现
                # 在 `quoteevidence.evidence_fields`；`semantic` 那一档由 H 判，不走这里）。
                evidence = _QE.evidence_fields(
                    chk, doc=item.get("doc"), quote=quote, page_range=pr,
                    field=f"relations.quote（lit:{lit_id}）",
                    note=str(item.get("note") or ""))

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
                    # 这一档是「逐字」回验（`quoteverify.check_quote`）—— 业主 2026-10-14
                    # 之后"通过"还多一档"语义相同（H 判）"，所以方式必须写实：
                    # 逐字命中记 `verbatim`，其余（不一致 / 没查）归空串。
                    quote_mode=str(evidence.get("quote_mode") or ""),
                    # 逐字命中「工作区正文」那一档要把来路写实（`item["note"]`）：
                    # 命中的是 PDF 还是我们手上那份 LaTeX，是两种不同的证据。
                    # 理由由 `evidence_fields` 拼：来路 + 试过的窗口 + 区间 +
                    # "没有模型调用"（D1：空栏不说明时，"没调用"与"忘了记"分不开）。
                    quote_reason=str(evidence.get("quote_reason") or ""),
                    # D1 的两栏证据：区间（`p{页}:norm[{起}:{止}]`，该页归一化文本的
                    # 字符偏移）与调用指纹（逐字档恒空 —— 确实没有模型调用）。
                    quote_span=str(evidence.get("quote_span") or ""),
                    quote_call_sha256=str(evidence.get("quote_call_sha256") or ""),
                    statement=description,
                    concept_group_key=group_key,
                    dedup_key=D.relation_dedup_key(group_key, quote),
                    status=status,
                    duplicate_of=decision.existing_id if decision.kind == "suspect" else None,
                    created_at=S.now_iso(),
                    # 12-C（业主裁定 甲）：并表时间只在"这一条真的进了概念图"时写 ——
                    # `suspect`/`rejected` 的行留在待议/被拒那一档，它还没有并进去
                    # （写了会让"哪天进来的"读出一个不存在的时刻，而 schema 的校验
                    # 也会当场拒；两处判据同一个口径）。
                    merged_at=S.now_iso() if status == "active" else "",
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

            # 4) 由关系表整体派生 related_concepts（老表专有的一格）
            #
            # 并表之后这一格没有承载点：新标准里"哪些概念相关"由 `relations` 表本身回答
            # （读侧现算，`dedup.derive_related_concepts` 仍是唯一实现），落一行镜像
            # 只会把派生结果又抄一份回老字段名上。所以这一支在落刀之后整段不跑。
            for cid in sorted(touched) if _CR.legacy_present(self.store).get("present") else []:
                target = next((c for c in concept_rows if c["concept_id"] == cid), None)
                if target is None:
                    continue
                want = D.derive_related_concepts(cid, relation_rows, include_suspect=True)
                if target.get("related_concepts") != want:
                    target["related_concepts"] = want
                    target["updated_at"] = S.now_iso()
                    _CR.upsert_legacy_shaped(tx, target, actor=self.actor,
                                             note="related_recomputed")

            # 5) 标记文献处理完成（与实体写入同一事务 —— 见 DESIGN.md §2.4）
            lit_row = tx.find("literature", lit_id=lit_id) or lit
            lit_row["processed"] = True
            lit_row["claimed_by"] = None
            lit_row["lease_until"] = None
            # 配额拒过东西时「不动」 `last_mine_error`：那一格是"这一篇为什么没抽成"
            # （`no_local_file` / 抽取异常），不是"抽成了但概念配额满了"。
            # 把配额写进去会让两种完全不同的处置读成同一件事。
            #
            # 为什么仍然标 `processed=True`（而不是"留到下一轮"）：这篇文献的概念是按
            # 抽取顺序产出的，下一轮重领它还会按「同一个顺序」撞同一个配额（前 30 条照旧、
            # 后面的照旧被拒）—— 要真"留到下一轮"就得新增一份持久游标，那是新的磁盘契约。
            # 业主给的口径是"剩下的下一轮「或写进报告」"：所以这一点落在「本轮的结果」里
            # （`res.concept_quota` / `res.concepts_refused` / `res.relations_deferred` /
            # `res.details[*stage=concept_quota]`），它随这一趟的 task 结果进台账 ——
            # "不许静默丢弃"要的是它出现在读数里，而不是它被塞进一个语义不符的字段。
            lit_row["last_mine_error"] = None
            # ---- M3（2026-11-05）：`download.fulltext` 的三档现算，写点在这里、
            # 清除点也在这里（同一个 `with_fulltext`）—— 改前全仓只有一处写点
            # （`search_tools._mark_candidate_locator`）而清除点为零，于是"上次的标签"
            # 永远留着：真机 6 条 `download.status=ok` 的行却写着"没有全文"。
            # 这一趟真的抽过 ⇒ docs 的逐页文本是机器证据，档位按它判：
            # 有非空页 ⇒ ok；有字节但一页可抽文本都没有（扫描件）⇒ no_text_layer。
            doc_pages = list(getattr(doc, "pages", []) or [])
            tier = _LR.fulltext_tier(
                bytes_on_disk=_LR.bytes_on_disk(path), pages=doc_pages)
            lit_row["download"] = _LR.with_fulltext(
                dict(lit_row.get("download") or {}), tier)
            res.details.append({"lit_id": lit_id, "stage": "fulltext",
                                "fulltext": tier, "pages": len(doc_pages)})
            # `R3-⑩`：真抽过了（抽取器返回了结果）⇒ 这一格 +1，与失败那一支同一个计数点。
            lit_row["mine_attempts"] = int(lit_row.get("mine_attempts") or 0) + 1
            tx.upsert("literature", lit_row, note="processed")
            res.processed = 1

        # 配额的读数随结果一起出去（`B.run` 逐篇汇总 ⇒ 一轮的总读数）。
        res.concept_quota = quota.reading()
        return res
