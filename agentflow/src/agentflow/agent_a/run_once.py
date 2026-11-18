"""角色 A 的动作 `run_once`：处理至多一条待办请求。

"先暂存、后入库"的接线见 `agentflow/litstage.py` 的模块 docstring 与 `stage_entries` /
`admission_plan` 的说明。拆文件的判据是"源码非空行与拆分前逐字相同"；这一条随后因为
「广搜结果先进待新增列表、A 筛完再入库」的行为变更而让位给新判据
（`tests/test_agent_a*.py`）—— 它守的是"不要顺手改行为"，而明确要求的行为变更不算。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from ._support import ARunResult, D, Path, S, T, X, make_lease, shutil, tempfile
from .. import litstage as L


def _candidate_identity(title: Any, doi: Any) -> tuple[str, str | None]:
    """一条候选在"同一次委托"里的身份：(规范化标题, 规范化 DOI)。

    为什么两格都要规范化：候选行上存的是原始字符串，而同一次检索里同一个源
    可能把同一篇交回两次（大小写、URL 前缀、句末标点不同）。直接比原串会让
    "同一篇"又多堆一行，而堆出来的行在读数上与"真的又检索到一篇"同形。
    """
    return T.normalize(str(title or "")), D.normalize_doi(doi)


def _declined_reason_counts(rows: Iterable[dict]) -> dict[str, int]:
    """本次委托里没入库的候选行，按受控理由码分组计数（没给码的按状态记）。

    只数没入库的那些：`admitted` 的行没有"为什么没入库"这一格，把它们混进
    分布会让理由分布里出现一个不存在的理由。
    """
    out: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        if status == "admitted":
            continue
        key = str(row.get("reason_code") or "") or f"status={status}"
        out[key] = out.get(key, 0) + 1
    return out


def _hits_reading(hits: int, rows: Sequence[dict], *, registered: int) -> str:
    """「检索到几条、入库几条、几条还待裁、其余为什么没入」的一句话读数。

    为什么它必须进 `last_error`：`search_requests.outcome` 的词表是禁改区契约
    （`schema.SEARCH_OUTCOMES`），里面没有"找到了但一条都没入库"这一档 ——
    那种情形只能落在 `no_results` 上。不补一句读数的话，它与"一条都没检索到"
    在盘上完全同形：审计读数就是 `registered=0` / `outcome=no_results`，
    而同一次的三条候选其实全被本地重叠闸拒收（`overlap_without_new_content`）。

    读数里必须有"命中数"与"理由码分布"两格：只给一个总数答不出"是被挡了
    还是丢了"，只给理由分布答不出"一共找回几条"。

    还要有 `待裁 N 条`：A 的自动链路不再能整批入库（候选没有 `relevance` 就进不了库），
    于是"入库 0 条"最常见的原因是"这几条还在等 A 逐条判" —— 不写这一格，它就会与
    "全被重叠闸挡掉"同形。
    """
    declined = _declined_reason_counts(rows)
    distribution = ("、".join(f"{code}={n}" for code, n in sorted(declined.items()))
                    or "无（候选行还停在 pending）")
    waiting = sum(1 for row in rows if L.judged_state(row) == "pending")
    return (f"检索命中 {int(hits)} 条、入库 {int(registered)} 条、待裁 {waiting} 条"
            f"（待裁的还没逐条判过：没有 relevance 进不了库）；"
            f"未入库理由分布：{distribution}")[:480]


def _source_failure_reading(errors: Sequence[str], sources: Sequence[dict]) -> str:
    """「哪几个源失败了」的一句话读数（没有源失败时返回空串）。

    为什么有命中也要写：`outcome=ok` 只说"至少登记了一篇"，它答不出
    "这一问是不是还有源没交货"。不写这一格的话，"两个源被限流、第三个源交回 1 篇"
    与"三个源都正常、其中两个 0 命中"在盘上同形，而前者意味着这篇文献的证据面
    可能少了一半来源。
    """
    failed: list[str] = []
    refused: list[str] = []
    for s in sources:
        name = str(s.get("name") or "")
        if not name:
            continue
        if str(s.get("status") or "") == "failed":
            failed.append(name)
        if bool(s.get("refused")):
            refused.append(name)
    parts: list[str] = []
    if failed:
        parts.append(f"{len(failed)} 个源失败：{'、'.join(failed)}")
    if refused:
        parts.append(f"{len(refused)} 个源没把这一问发出去：{'、'.join(refused)}")
    if parts:
        return ("本次检索有 " + "；".join(parts)
                + "；其余源交回的结果已登记（这一条不是「检索正常」）")[:480]
    if errors:
        return ("本次检索有源级报错（逐源读数里没有失败行）："
                + "; ".join(str(e) for e in errors))[:480]
    return ""


def _wanted_request_ids(request_ids: Sequence[str] | None) -> list[str]:
    """调用方点名的那些委托号（去空、去重、保序）。"""
    out: list[str] = []
    for raw in request_ids or ():
        rid = str(raw or "").strip()
        if rid and rid not in out:
            out.append(rid)
    return out


def _pending_scope(store: Any) -> dict:
    """全表待裁的按委托读数（唯一实现是 `litstage.pending_all_delegations`）。

    这一格是"旧委托的 pending 对 A 隐身"那条缺陷的出口：A 的每一轮都读全表，
    而不是只读"槽位号最大那一行所属的委托"。
    """
    return L.pending_all_delegations(store.rows("lit_candidates"))


def _fill_pending(store: Any, result: ARunResult) -> None:
    """把全表待裁读数落进这一轮的结果（每一轮都填；读不到就让它抛，不折成 0）。"""
    scope = _pending_scope(store)
    result.pending_total = int(scope.get("total") or 0)
    result.pending_by_delegation = [dict(g) for g in scope.get("by_delegation") or []]


def _claim_pending(store: Any, actor: str, wanted: Sequence[str],
                   result: ARunResult) -> list[str]:
    """认领"还有待裁行的委托"（行上落认领 + `lit.claim_pending` 事件）并填 `claim_note`。

    `wanted` 空 ⇒ 认领全部还有 pending 的委托（真机那段"队列全 done、30 条没人判"
    就靠这一档被看见）；非空 ⇒ 只认领点名的那些。点名了却没有待裁行的，如实写进
    `claim_note`（"已判完或已清表"），不冒充成"清过了"。

    ## AL-11（2026-11-19）：认领要落在行上，不只落事件

    改前这里只 `tx.info("lit.claim_pending", …)`：事件是 append-only 的审计面，它答不了
    "这一批现在归谁"（不是"现在"）。两个 A 实例同时进来（队列空、还有 pending 行）时二者
    都"认领"同一批委托，盘上没有一处互斥 —— 而这正是审计要的那条读数。现在每一笔认领都过
    `litstage.claim_delegation`：租约还在别人手上 ⇒ 不写一个字节（`state="other"`），
    行上的 `claimed_by` / `lease_until` / `claimed_at` 就是"这一批归谁"的那一处。
    事件照旧写（可回放的那一半不丢），但它不再是唯一落点。
    """
    scope = _pending_scope(store)
    by = {str(g.get("request_id") or ""): g for g in scope.get("by_delegation") or []}
    targets = list(wanted) or list(by)
    claimed: list[str] = []
    denied: list[str] = []
    for rid in targets:
        if rid not in by:
            continue
        got = L.claim_delegation(store, rid, actor=actor)
        if got.get("claimed"):
            claimed.append(rid)
        else:
            denied.append(rid)
    clean = [rid for rid in targets if rid not in by]
    result.claimed_delegations = claimed
    note = ""
    if claimed:
        note = ("已认领 " + str(len(claimed)) + " 个还有待裁行的委托："
                + "、".join(f"{rid}={int(by[rid].get('pending') or 0)}" for rid in claimed)
                + "。这些行不在这一次自动链路里判：逐条 `lit.admit` 判收 / "
                "`lit.stage_reject` 判拒，再逐委托 `lit.admit_all` 提交（清表）。")
    if denied:
        note += (" " if note else "") + (
            "另一个 A 实例还持着这些委托（行上的租约未到期），这一轮不认领："
            + "、".join(denied) + "。")
    if clean:
        note += (" " if note else "") + (
            "点名但没有待裁行（已判完或已清表）：" + "、".join(clean) + "。")
    result.claim_note = note
    return claimed


class _RunOnce:
    def run_once(self, *, request_ids: Sequence[str] | None = None) -> ARunResult:
        """处理至多一条待办请求，返回本轮的完整审计结果。

        三态纪律的落点：取不到请求时不返回"看起来正常的空结果"，而是把"没做"的原因原样带出来
        （`skipped_reason` 四选一，取值与优先级见 `_claim`）；计数（"做了多少"）与它正交，必须分别看。
        本轮是「先 stage 后 admit」（广搜结果先进待新增列表，A 筛完再入库）：
        ① `litstage.stage_entries` 暂存每个候选（`batch=1`、槽位号只增不复用，不设条数上限）；
        ② `litstage.admission_plan`（`on_over_cap="truncate"`）判库配额与重叠 —— 本文件不重写一份；
        ③ `litstage.apply_settlement` / `write_report` 结算并写报告。
        `duplicate_branch_ok=True` 的理由："重叠"里有一档是同一篇（DOI 相同），正确处置是走现有判重分支
        —— 只把 `source_request_ids` 追加到既有行、不新建行（`dedup.literature_keys` 的口径）。

        ## 2026-11-17（FX1）：跨委托的待裁行也要能认领

        真机 `projects/lp-ball-3` 的收工门 blocker「30 条 pending」：队列里的检索请求全是
        `done=true`，`_claim()` 只能报 `no_pending_request`，于是 A 被派来"结清"却什么都没做；
        而候选表里两个委托各有 15 条停在 `pending`。所以本方法多了两件事：

        - 每一轮都把全表待裁的按委托读数落进结果（`pending_total` /
          `pending_by_delegation`）—— A 因此不再只看"当前委托"；
        - 队列里没有可领的检索请求时，最后一档是认领全部还有 pending 的委托
          （`claimed_delegations` + `lit.claim_pending` 事件 + `claim_note`）；
          `request_ids` 给了就只认领点名的那些（留给编排层/判据点名用）。

        两格读数不互相代替：`skipped_reason` 说的是检索队列那一档
        （队列空仍是 `no_pending_request`，它不是"什么都没做"），
        `claimed_delegations` / `claim_note` 说的才是这一轮认领了哪些待裁委托。
        """
        result = ARunResult()
        wanted = _wanted_request_ids(request_ids)
        if wanted:
            # 点名档：只认领点名的委托。不给就跳过队列领取 —— 调用方问的是
            # "这几个委托清完了没有"，不是"队列还有没有活"。
            if not _claim_pending(self.store, self.actor, wanted, result):
                result.skipped_reason = "no_pending_delegation"
            _fill_pending(self.store, result)
            return result
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
            # 队列真的空了（不是"全被别人占着 / 全在退避"）时，最后一个出口是
            # 把"还有待裁行的委托"认领下来：不这么做，这一轮只会带回
            # `no_pending_request` —— 而候选表里那几十条既没人看见、也没人判
            # （真机 lp-ball-3 正是这个形态）。队列有活但领不到时不认领：
            # 那一档的读数（leased / backoff / gave_up）本身就是要报给运维的原因。
            if claim.pending == 0:
                _claim_pending(self.store, self.actor, [], result)
            _fill_pending(self.store, result)
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
            # ---- 阶段 0（无锁、只写候选表）：候选先规范化，再「暂存进待新增列表」。
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
                    # 下载要的是"这一条候选"本身（`pdf_url` 只活在它上面）。
                    # 以前按下标去 `candidates[i]` 取，而 `prepared` 会跳过空题名的
                    # 候选 ⇒ 下标一错位就下错文件；挂在这里之后映射只有一份。
                    "cand": cand,
                })

            # ---- 阶段 1a：暂存（`lit_candidates`，按委托）+ 入库判断（上限 + 重叠）。
            # 暂存之前先做一次"本次委托已有哪些 pending"的 find：同一委托重跑
            # （崩溃后重领、或调用方重复驱动同一行请求）时，同一篇候选不许再追加
            # 一个槽位。审计读数：同一个主题的两次委托把 `lit_candidates` 从 4 行
            # 堆到 8 行，第二组 4 行的标题与 DOI 与第一组逐字相同。
            # 身份口径是 `_candidate_identity`（规范化标题 + 规范化 DOI），
            # 不是原字符串：同一篇换个大小写/URL 前缀不该换行。
            pending_identity = {
                _candidate_identity(row.get("title"), row.get("doi"))
                for row in self.store.rows("lit_candidates")
                if str(row.get("request_id")) == req["request_id"]
                and str(row.get("status")) == "pending"
            }
            fresh_entries = [e for e in prepared
                             if _candidate_identity(e["title"], e["doi"]) not in pending_identity]
            # `plan["admitted"]` 才是这一轮"可以进 literature"的那些；
            # 它不是 `prepared` 的同义词：超配额的、被重叠挡掉的都在另外两栏里。
            plan = None
            slots: list[str] = []
            entry_by_slot: dict[str, dict] = {}
            if fresh_entries:
                staged = L.stage_entries(
                    self.store,
                    [{"title": e["title"], "doi": e["doi"], "provider": e["provider"],
                      "year": e["year"], "type_code": e["type"], "summary": e["summary"],
                      "url": str(getattr(e["raw"], "get", lambda *_: None)("pdf_url") or "")}
                     for e in fresh_entries],
                    request_id=req["request_id"], actor=self.actor, note="a.run_once.stage",
                )
                slots = [s["slot"] for s in staged["staged"]]
                entry_by_slot = dict(zip(slots, fresh_entries))
                plan = L.admission_plan(
                    self.store, request_id=req["request_id"], slots=slots,
                    on_over_cap="truncate", duplicate_branch_ok=True,
                    # 这条路是"整批提交"（一次把这一轮暂存的全部候选搬进 literature），
                    # 所以它要走同一道提交闸。而它暂存的候选没有 relevance（自动链路
                    # 读不懂"为什么相关"）⇒ 闸会整批拒，一条也进不了库 —— 这是口径要
                    # 的效果，不是回退：入库只能逐条判过（A 的模型动作），自动链路只
                    # 负责把它们暂存进列表。
                    require_judged=True,
                    # 回读闸（业主裁定 ①）：自动链路也不许"没回读就提交"。它与上面
                    # 那条闸不重复：一条管"判过没有"，一条管"A 看过此刻的清单没有"。
                    require_readback=True,
                )
            admit_slots = [str(it["slot"]) for it in (plan or {}).get("admitted") or []]

            # ---- 阶段 1（无锁）：给「要入库的那些」下载到 staging。
            # 没通过入库判断的候选不下载：它们是"待裁/已挡"的行，下载一份不会带来
            # 任何新信息，只会让 staging 里多出一堆永远不会被引用的字节。
            #
            # 那一个例外：这一篇已经在库里、只是缺文件的候选照样下载。
            # 理由是两件事：入库（要逐条判过）与"给已登记的那一行补上字节"
            # （`draft/30` §T0-10 的补下载）不是同一件事 —— 后者不新增任何 literature
            # 行、也不改任何候选行的状态。不把这一档捞出来，自动链路落地就会顺手砍掉
            # 补下载这条路。
            lit_rows_now = self.store.rows("literature")
            known_slots: set[str] = set()
            downloads = 0
            # "已在库"的判定与"要不要下载"共用这一趟遍历：两件事读的是同一份
            # `lit_rows_now`，而下载只往 staging 写、不改这张表（改前分了两趟）。
            for entry, slot in zip(fresh_entries, slots):
                hit, _key = D.find_existing_literature(
                    lit_rows_now, entry["title"], entry["year"], entry["doi"])
                if hit is not None:
                    known_slots.add(str(slot))
                if slot not in admit_slots and str(slot) not in known_slots:
                    entry["download"] = {"status": "skipped", "error": "not_admitted",
                                         "http_status": None, "bytes": 0, "sha256": None}
                    continue
                if downloads < self.max_downloads:
                    dl = self._stage_download(entry["cand"], staging)
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
                # 只有"判过要入库的"能新建 literature 行；"已在库、来补文件"的那一批
                # 只走判重分支（见下面 `existing is None ⇒ continue`）。
                walk_slots = ([s for s in admit_slots]
                              + [str(s) for s in slots
                                 if str(s) not in admit_slots and str(s) in known_slots])
                for slot in walk_slots:
                    entry = entry_by_slot[slot]
                    existing, hit_key = D.find_existing_literature(
                        lit_rows, entry["title"], entry["year"], entry["doi"]
                    )
                    if existing is None and slot not in admit_slots:
                        continue
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
                        existing_id = str(existing["lit_id"])
                        got_path, dl_clean = self._attach_staged(
                            existing_id, dict(entry.get("download") or {}))
                        # 这一格下面三处分支都要读，先算一次（`_attach_staged` 之后不再改）。
                        dl_status = str(dl_clean.get("status"))
                        backfilled = bool(needs_file and got_path)
                        # 真的试过（不是"没有 PDF URL"/"预算用尽"那种 skipped）就记账 ——
                        # 与新建行那一支同一个口径：新建行会让失败留在行上，
                        # 补下载若什么都不记，"这一篇试过但没拿到"就只活在计数里。
                        tried = needs_file and dl_status in (
                            "ok", "failed", "content_mismatch")
                        if backfilled:
                            existing["path"] = got_path
                            existing["download"] = {
                                **dl_clean, "backfilled": True,
                                "previous": {"status": old_dl.get("status"),
                                             "error": old_dl.get("error")},
                            }
                            # 计数口径与下面新建行那一支逐字一致：只有 `status == "ok"`
                            # 才进 `downloaded`，其余带字节的那一档（`content_mismatch`）
                            # 只进 `download_suspect`。改前这里无条件 `downloaded += 1`
                            # 再额外加一格 suspect，于是"下到了网页"同时出现在两个计数里
                            # —— "下到论文"那个数字被一次可疑补下载抬高了（B3）。
                            # `_attach_staged` 只认两档带字节的状态（`ok` / `content_mismatch`），
                            # 所以这个二分与那一处是同一份口径。
                            if dl_status == "ok":
                                result.downloaded += 1
                            else:
                                result.download_suspect += 1
                        elif tried:
                            existing["download"] = {
                                **dl_clean, "backfill_attempt": True,
                                "previous": {"status": old_dl.get("status"),
                                             "error": old_dl.get("error")},
                            }
                            if dl_status == "failed":
                                result.download_failed += 1
                            else:
                                result.download_suspect += 1
                        note = f"dup_by:{hit_key}" + ("+backfill" if backfilled else "")
                        tx.upsert("literature", existing, note=note)
                        result.duplicated += 1
                        new_ids.append(existing["lit_id"])
                        lit_id_by_slot[slot] = existing_id
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
                # 超配额的落 rejected(over_cap)。「绝不物理删」（可追）。
                # 注意最常见的结局不在这三类里：整批被判据拦下（候选没有 relevance
                # ⇒ `missing_relevance`）时，一行都不结算，它们留在 pending 等 A 逐条
                # 判 —— 那一档由 `_hits_reading` 的「待裁 N 条」如实报出来。
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
                    # 有命中不等于"每个源都正常"：只要有一个源失败（或这一问没
                    # 发出去），`last_error` 就不许写 null —— 否则"两个源被限流、
                    # 第三个源交回一篇"与"三个源都正常"在盘上同形。
                    fresh["last_error"] = _source_failure_reading(
                        search_errors, result.sources) or None
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
                    # 搜索正常执行但零命中 —— 这是一个有效结论，不是错误。
                    # 但"零命中"只在真的没有候选时才成立：有候选、只是全被本地
                    # 重叠闸/配额挡掉，`outcome` 词表里没有对应的一档（它是禁改区
                    # 契约），所以读数的区别必须落在 `last_error` 上：
                    # 命中数 / 入库数 / 理由码分布。否则"找到了、全被拒"与
                    # "什么都没找到"在盘上同形（审计读数：registered=0、
                    # outcome=no_results，而同一次三条候选全是
                    # overlap_without_new_content）。
                    fresh["done"] = True
                    fresh["outcome"] = "no_results"
                    fresh["lease_until"] = None
                    cand_rows = [
                        row for row in tx.rows("lit_candidates")
                        if str(row.get("request_id")) == req["request_id"]
                    ]
                    fresh["last_error"] = (
                        _hits_reading(len(prepared), cand_rows, registered=len(new_ids))
                        if prepared else None
                    )

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

            # ---- 阶段 3（锁外）：写「委托报告」（报告是交付物，不是可选）。
            # 放在事务之后：报告写的是"这一轮结束时盘上的样子"，而盘上的样子由事务定。
            # 写失败不许吞掉整轮结果（文献已经落库了）—— 但它必须可见：
            # `ARunResult.note` 里有它，`reports/lit-<request_id>.md` 不在盘上也能查出来。
            #
            # 2026-11-16（Q1）：这一份是进度报告（`phase="draft"`，报告头逐字标
            # "未定稿"）。自动链路只负责把候选暂存进列表，判收与提交是 A 的模型动作：
            # 交报告那一刻的无号原件（`.submitted.md`）与注册回填之后的定稿都由
            # `lit.admit_all` 落。这里写"定稿"会是一句谎（行还停在 pending/qualified）。
            if prepared:
                try:
                    rep = L.write_report(self.store, req["request_id"], phase="draft")
                    result.report_path = str(rep.get("path") or "")
                    result.report_admitted = int(rep.get("admitted") or 0)
                    result.report_not_admitted = int(rep.get("not_admitted") or 0)
                except Exception as exc:  # noqa: BLE001 —— 报告失败不该把已落库的文献判成失败
                    result.report_path = ""
                    result.report_error = f"{type(exc).__name__}: {exc}"
        finally:
            # staging 目录里的残留下载一并清掉（成功搬走的已经不在里面了）
            shutil.rmtree(staging, ignore_errors=True)

        # 收工时再把全表待裁读一遍（跨委托）：这一轮的暂存会让本委托多出 pending，
        # 而旧委托的那几条也在同一份读数里 —— A 的下一步因此有完整的对象清单。
        _fill_pending(self.store, result)
        return result
