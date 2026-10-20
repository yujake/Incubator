"""角色 A 的动作 `run_once`（`goal-7f5116c1` M6：从 `agent_a.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。

⚠️ 2026-10-20 业主口径（待新增文献列表）之后，上面那句"逐字未改"**不再成立**：
本方法多了一段"先暂存、后入库"的接线（见 `_rehearse_stage` 的说明与
`agentflow/litstage.py` 的模块 docstring）。原来那条判据是迁移期的临时锚点，
它守的是"拆文件没有顺手改行为"；本轮是**业主明确要求的行为变更**，
所以锚点让位给新判据（`tests/test_agent_a*.py` 与新判据文件）。
"""
from __future__ import annotations

from ._support import ARunResult, D, Path, S, T, X, make_lease, shutil, tempfile
from .. import litstage as L

class _RunOnce:
    def run_once(self) -> ARunResult:
        """处理至多一条待办请求，返回本轮的完整审计结果。

        三态纪律在这里的落点：取不到请求时不返回一个"看起来正常的空结果"，
        而是把"没做"的原因原样带出来（`skipped_reason` 四选一，取值与优先级见 `_claim`）。
        `processed/registered/...` 全是计数（"做了多少"），`skipped_reason` 是
        "为什么没做" —— 两者正交，调用方必须分别看。

        ## 2026-10-20 接线：登记文献这一步改成「先 stage 后 admit」

        业主口径（逐字）：

        > 把 A 的 `search_literature`（或它对应的动作）在"登记文献"那一步改为先 stage
        > 后 admit：广搜结果先进待新增列表，A（或它的审内容步骤）筛完再入库。

        落点就是这个方法的阶段 1/2 之间，具体三道：

        1. **暂存**（`litstage.stage_entries`）：本轮的每个候选先落一行
           `lit_candidates`（`request_id` = 这一次委托、`batch=1`、槽位号只增不复用）。
           这一步**不设条数上限** —— 广搜可以超过 10 篇；
        2. **入库判断**（`litstage.admission_plan`，`on_over_cap="truncate"`）：
           本委托的入库配额（`MAX_ADMIT_PER_DELEGATION=10`）与重叠检查都在那一处判，
           本文件不重写一份。通过的才下载、才登记；被重叠挡掉的落
           `rejected(overlap_without_new_content)`；超配额的落 `cleared(over_cap)`；
        3. **结算 + 报告**（`litstage.apply_settlement` / `write_report`）：
           候选行回到终态，并写 `reports/lit-<request_id>.md`（已入库 + 未入库两块）。

        为什么用 `duplicate_branch_ok=True`：本轮的"重叠"里有一档是**同一篇**（DOI 完全相同）。
        那一档的正确处置不是"拒收"，而是走**现有的判重分支** —— 只把
        `source_request_ids` 追加到既有行，不新建行（`dedup.literature_keys` 的口径）。
        两件事（"同一篇只留一个 lit_id" 与 "内容重叠要不要新内容"）因此各归各的判据。
        """
        result = ARunResult()
        claim = self._claim()
        # 取任务侧的审计信息先落进结果，再决定要不要早退 —— 否则
        # "有 high 在队里但全被租约占着 / 全在退避中"这类信息会随着 skipped_reason
        # 一起丢掉，外部就只剩一个"什么都没做"。
        result.queue_pending = claim.pending
        result.skipped_lease_active = claim.skipped_lease_active
        result.skipped_lease_backoff = claim.skipped_lease_backoff
        result.gave_up = claim.gave_up
        req = claim.request
        if req is None:
            result.skipped_reason = claim.skipped_reason
            return result
        # I7：把"本轮取了哪条、它是什么优先级"暴露出来 —— 这是从外部唯一能
        # 观察到优先级真的生效的地方（文献表里看不出来）。
        result.request_id = req.get("request_id")
        result.priority = req.get("priority")
        result.priority_rank = X.priority_rank(req.get("priority"))
        result.submitted_by = req.get("submitted_by")

        candidates, search_errors, readings = self._search(req)
        # 这一轮"问了谁、问得怎么样"的读数先落进结果：它是唯一能证明
        # "请求行点名的源真的被问了"的机器读数（三态：没点名 / 点名了 /
        # 点名了一个不认识的源，三者在 `providers_requested` 与 `sources` 上不同形）。
        result.providers_requested = list(readings.get("providers_requested") or [])
        result.role_providers = list(readings.get("role_providers") or [])
        result.sources = list(readings.get("sources") or [])
        result.cost = dict(readings.get("cost") or {})

        staging = Path(tempfile.mkdtemp(prefix="agentflow-stage-", dir=str(self.store.library)))
        try:
            # ---- 阶段 0（无锁、只写候选表）：候选先规范化，再**暂存进待新增列表**。
            # 这里不分配 lit_id、不写 literature，因此失败/崩溃都不会留下半成品文献行。
            prepared: list[dict] = []
            for cand in candidates:
                title = getattr(cand, "title", "") or ""
                if not title.strip():
                    continue
                prepared.append({
                    "title": title,
                    "type": getattr(cand, "type_code", "Z") or "Z",
                    "summary": T.clip(getattr(cand, "summary", ""), 1200),
                    "doi": getattr(cand, "doi", None),
                    "year": getattr(cand, "year", None),
                    "authors": list(getattr(cand, "authors", []) or []),
                    "venue": getattr(cand, "venue", None),
                    "language": getattr(cand, "language", None),
                    "provider": getattr(cand, "provider", "?"),
                    "raw": getattr(cand, "raw", {}) or {},
                })

            # ---- 阶段 1a：暂存（`lit_candidates`，按委托）+ 入库判断（上限 + 重叠）。
            # `plan["admitted"]` 才是这一轮"可以进 literature"的那些；
            # 它不是 `prepared` 的同义词：超配额的、被重叠挡掉的都在另外两栏里。
            plan = None
            slot_of_index: list[str] = []
            entry_by_slot: dict[str, dict] = {}
            if prepared:
                staged = L.stage_entries(
                    self.store,
                    [{"title": e["title"], "doi": e["doi"], "provider": e["provider"],
                      "year": e["year"], "type_code": e["type"], "summary": e["summary"],
                      "url": str(getattr(e["raw"], "get", lambda *_: None)("pdf_url") or "")}
                     for e in prepared],
                    request_id=req["request_id"], actor=self.actor, note="a.run_once.stage",
                )
                slot_of_index = [s["slot"] for s in staged["staged"]]
                entry_by_slot = {slot: prepared[i] for i, slot in enumerate(slot_of_index)}
                plan = L.admission_plan(
                    self.store, request_id=req["request_id"], slots=slot_of_index,
                    on_over_cap="truncate", duplicate_branch_ok=True,
                )
            admit_slots = [str(it["slot"]) for it in (plan or {}).get("admitted") or []]

            # ---- 阶段 1（无锁）：只给**要入库的那些**下载到 staging。
            # 没通过入库判断的候选不下载：它们是"待审/已挡"的行，下载一份不会带来
            # 任何新信息，只会让 staging 里多出一堆永远不会被引用的字节。
            downloads = 0
            for i, entry in enumerate(prepared):
                slot = slot_of_index[i] if i < len(slot_of_index) else ""
                if slot not in admit_slots:
                    entry["download"] = {"status": "skipped", "error": "not_admitted",
                                         "http_status": None, "bytes": 0, "sha256": None}
                    continue
                if downloads < self.max_downloads:
                    dl = self._stage_download(candidates[i], staging)
                    downloads += 1 if dl.get("status") != "skipped" else 0
                    entry["download"] = dl
                else:
                    entry["download"] = {"status": "skipped", "error": "max_downloads_reached",
                                         "http_status": None, "bytes": 0, "sha256": None}

            # ---- 阶段 2（锁内，短）：重新判重 → 分配 ID → 落行 → 搬文件 → 结算候选 → 标记请求完成。
            with self.store.tx("search_requests", "literature", "lit_candidates",
                               actor=self.actor, note="register") as tx:
                lit_rows = tx.rows("literature")
                new_ids: list[str] = []
                lit_id_by_slot: dict[str, str] = {}
                fail_by_slot: dict[str, str] = {}
                for slot in admit_slots:
                    entry = entry_by_slot[slot]
                    existing, hit_key = D.find_existing_literature(
                        lit_rows, entry["title"], entry["year"], entry["doi"]
                    )
                    if existing is not None:
                        # 同一篇被另一个请求（或另一个 A 实例）先登记了：只追加来源，不新建行
                        src = set(existing.get("source_request_ids") or [])
                        src.add(req["request_id"])
                        existing["source_request_ids"] = sorted(src)
                        # ---- 补下载（`draft/30` §T0-10）：在库但没有可用全文的行，
                        # 允许这一次把字节补上。没有这一步，"某篇在库却没有文件"就是个
                        # 死局：候选每次都被判重跳过，而 P1 要求必查的那几篇必须落盘。
                        old_dl = existing.get("download") or {}
                        needs_file = (not existing.get("path")) or str(old_dl.get("status")) != "ok"
                        got_path, dl_clean = self._attach_staged(
                            str(existing["lit_id"]), dict(entry.get("download") or {}))
                        backfilled = bool(needs_file and got_path)
                        # 真的试过（不是"没有 PDF URL"/"预算用尽"那种 skipped）就记账 ——
                        # 与新建行那一支同一个口径：新建行会让失败留在行上，
                        # 补下载若什么都不记，"这一篇试过但没拿到"就只活在计数里。
                        tried = needs_file and str(dl_clean.get("status")) in (
                            "ok", "failed", "content_mismatch")
                        if backfilled:
                            existing["path"] = got_path
                            existing["download"] = {
                                **dl_clean, "backfilled": True,
                                "previous": {"status": old_dl.get("status"),
                                             "error": old_dl.get("error")},
                            }
                            result.downloaded += 1
                            if str(dl_clean.get("status")) == "content_mismatch":
                                result.download_suspect += 1
                        elif tried:
                            existing["download"] = {
                                **dl_clean, "backfill_attempt": True,
                                "previous": {"status": old_dl.get("status"),
                                             "error": old_dl.get("error")},
                            }
                            if str(dl_clean.get("status")) == "failed":
                                result.download_failed += 1
                            else:
                                result.download_suspect += 1
                        note = f"dup_by:{hit_key}" + ("+backfill" if backfilled else "")
                        tx.upsert("literature", existing, note=note)
                        result.duplicated += 1
                        new_ids.append(existing["lit_id"])
                        lit_id_by_slot[slot] = str(existing["lit_id"])
                        continue

                    lit_id = tx.alloc_id("lit")

                    # 这里刻意不建 `<library>/<lit_id>/` 目录（`draft/28` §154 的 R-49）。
                    # 以前这一处无条件 `mkdir`，于是"下载被跳过（没有 PDF URL）"或
                    # "下载失败"的行也会留下一个空目录：实测 98 行里留下 60 个空目录，
                    # 目录树看起来有 98 篇文献，实际只有 38 个文件。
                    # 建目录的唯一责任人现在是 `_attach_staged` —— 它只在真的有字节要搬
                    # 时才建（同文件 389-390 那一处），判据因此只有一份。
                    dl = entry.get("download") or {}
                    rel_path, dl_clean = self._attach_staged(lit_id, dict(dl))
                    st = dl.get("status")
                    if rel_path:
                        if st == "ok":
                            result.downloaded += 1
                        else:
                            result.download_suspect += 1
                    elif st == "failed":
                        result.download_failed += 1

                    keys = D.literature_keys(entry["title"], entry["year"], entry["doi"])
                    row = S.Literature(
                        lit_id=lit_id,
                        title=entry["title"],
                        type=entry["type"],
                        summary=entry["summary"],
                        path=rel_path,
                        processed=False,  # B 负责置 true
                        source_request_ids=[req["request_id"]],
                        dedup_key=keys[0] if keys else f"title:{T.normalize(entry['title'])}|*",
                        doi=D.normalize_doi(entry["doi"]),
                        year=entry["year"],
                        authors=entry["authors"],
                        venue=entry["venue"],
                        language=entry["language"],
                        added_at=S.now_iso(),
                        download={k: v for k, v in dl.items() if not k.startswith("_")},
                    )
                    row.validate()
                    rowd = row.to_dict()
                    # 把全部候选键挂上行内（供判重诊断；不进 schema 校验的强约束）
                    rowd["_keys"] = keys
                    tx.upsert("literature", rowd, note=f"provider:{entry['provider']}")
                    # 注意：`lit_rows` 就是 `tx.rows("literature")` 返回的那个列表本身，
                    # upsert 已经把行放进去了；这里不能再 append，否则会出现重复 ID。
                    new_ids.append(lit_id)
                    lit_id_by_slot[slot] = str(lit_id)
                    result.registered += 1

                # ---- 结算候选行：入库成功的落 admitted；被重叠/登记挡掉的落 rejected；
                # 超配额的落 cleared(over_cap)。**绝不物理删**（可追）。
                if plan is not None:
                    for slot in admit_slots:
                        if slot not in lit_id_by_slot:
                            fail_by_slot[slot] = "登记路径没有给出 lit_id"
                    L.apply_settlement(
                        tx, L.decisions_from_plan(plan, lit_id_by_slot, fail_by_slot))

                # 重新读取请求行（可能已被并发修改），再决定这一轮的终局
                fresh = tx.find("search_requests", request_id=req["request_id"]) or dict(req)
                fresh["result_lit_ids"] = S.sorted_unique(new_ids)
                fresh["claimed_by"] = None

                if new_ids:
                    fresh["done"] = True
                    fresh["outcome"] = "ok"
                    fresh["lease_until"] = None
                    fresh["last_error"] = None
                elif search_errors:
                    # DESIGN.md §5.3：搜索失败不等于这条请求结束。
                    # 如果这里就置 done，那么"租约到期重试"和"超过 max_attempts 才放弃"
                    # 两条规则就都失效了 —— 一次网络抖动会把请求永久判死。
                    #
                    # 但"这一问根本没发出去"（第三态）不在这条规则里：它是确定性的，
                    # 重试不会变。混进重试那一档的代价是白烧三次配额 + 读数上"没问"与
                    # "问了失败"长得一样（`draft/28` §205）。所以先分档：
                    not_sent, transient = self._split_errors(search_errors)
                    exhausted = int(fresh.get("attempts") or 0) >= self.max_attempts
                    if not_sent and not transient:
                        fresh["done"] = True
                        # 词表里没有第四档（`schema.SEARCH_OUTCOMES` 是禁改区契约），
                        # 所以 outcome 仍是 `search_failed`；区别写在 `last_error` 里，
                        # 逐字带第三态名，并明说"不重试"。
                        fresh["outcome"] = "search_failed"
                        fresh["lease_until"] = None
                        fresh["last_error"] = (
                            "这一问没有发给上游（第三态，重试不会变）：" + "; ".join(not_sent))[:500]
                    elif not_sent and transient:
                        # 一部分 provider 没发出去、另一部分发出去失败了：
                        # 按可重试处理（那一条真失败的可能下次就好了），
                        # 但把"没发出去"的那几条也如实写进同一个字段。
                        fresh["done"] = False
                        fresh["outcome"] = None
                        fresh["lease_until"] = make_lease(self.retry_backoff_seconds)
                        fresh["last_error"] = "; ".join(search_errors)[:500]
                    elif exhausted:
                        fresh["done"] = True
                        fresh["outcome"] = "search_failed"
                        fresh["lease_until"] = None
                        fresh["last_error"] = "; ".join(search_errors)
                    else:
                        fresh["done"] = False
                        fresh["outcome"] = None
                        # 退避租约：既让重试可行，又不会在本进程里立刻重打同一个 API
                        fresh["lease_until"] = make_lease(self.retry_backoff_seconds)
                        fresh["last_error"] = "; ".join(search_errors)
                else:
                    # 搜索正常执行但零命中 —— 这是一个有效结论，不是错误
                    fresh["done"] = True
                    fresh["outcome"] = "no_results"
                    fresh["lease_until"] = None
                    fresh["last_error"] = None

                if search_errors:
                    tx.info("search_errors", request_id=req["request_id"], errors=search_errors)
                # 注意：事务里拿到的是 dict，不能直接调 .validate()；用行对象校验一遍
                S.row_from_dict("search_requests", fresh).validate()
                tx.upsert("search_requests", fresh, note=f"finish:{fresh.get('outcome')}")
                result.processed = 1
                result.outcome = fresh.get("outcome")
                # 注意：这里不再碰 `result.gave_up`。放弃（gave_up）只发生在
                # `_claim()` 里 —— 请求被放弃后根本不会被取出来跑，所以"跑到提交阶段
                # 才发现 outcome=gave_up"是一个不可能发生的分支。原来那行
                # `result.gave_up = 1 if fresh.get("outcome") == "gave_up" else 0`
                # 因此恒为 0，把 `_claim()` 里真正数到的放弃条数覆盖成 0：
                # 字段存在、名字合理、永远是 0 —— 典型的"看起来在统计、实际恒为假"。

            # ---- 阶段 3（锁外）：写**委托报告**（业主 2026-10-20 第 3 条：这是交付物）。
            # 放在事务之后：报告写的是"这一轮结束时盘上的样子"，而盘上的样子由事务定。
            # 写失败不许吞掉整轮结果（文献已经落库了）—— 但它必须可见：
            # `ARunResult.note` 里有它，`reports/lit-<request_id>.md` 不在盘上也能查出来。
            if prepared:
                try:
                    rep = L.write_report(self.store, req["request_id"])
                    result.report_path = str(rep.get("path") or "")
                    result.report_admitted = int(rep.get("admitted") or 0)
                    result.report_not_admitted = int(rep.get("not_admitted") or 0)
                except Exception as exc:  # noqa: BLE001 —— 报告失败不该把已落库的文献判成失败
                    result.report_path = ""
                    result.report_error = f"{type(exc).__name__}: {exc}"
        finally:
            # staging 目录里的残留下载一并清掉（成功搬走的已经不在里面了）
            shutil.rmtree(staging, ignore_errors=True)

        return result
