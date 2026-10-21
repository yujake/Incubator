"""角色 A 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_a/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

import time

from ._support import Any, ClaimOutcome, Iterable, Path, S, Store, T, X, lease_expired, make_lease, shutil
from .run_once import _RunOnce
from .run import _Run
from .search_literature import _SearchLiterature
from .ingest_local import _IngestLocal
from .shelf_search import _ShelfSearch
from .walk_citations import _WalkCitations


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        providers: Iterable[Any],
        downloader: Any | None = None,
        config: dict | None = None,
        actor: str = "agent-A",
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
    ):
        self.store = store
        self.providers = list(providers)
        self.downloader = downloader
        self.cfg = config or {}
        self.actor = actor
        self.llm = llm
        self.lease_seconds = int(self.cfg.get("lease_seconds", 900))
        self.max_attempts = int(self.cfg.get("max_attempts", 3))
        self.limits = self.cfg.get("limits", {"broad": 20, "topical": 15, "precise": 10})
        self.max_downloads = int(self.cfg.get("max_downloads_per_request", 25))
        self.do_download = bool(self.cfg.get("download", True))
        # 搜索失败后的退避租约：既允许重试，又避免在同一进程里立刻重打同一个 API。
        # 它靠 `_claim` 的跳过判据生效（判据只看 `lease_until` 是否仍在有效期内，
        # 不要求 `claimed_by` 非空）—— 失败分支会把 `claimed_by` 置空，
        # 若判据额外要求 `claimed_by` 非空，这条租约就写了等于没写。
        # `order_pending_requests` 的分桶只负责让它在排序上不抢占，不负责拦住它。
        # 置 0 是合法配置：等价于关闭退避（租约当场过期 ⇒ 立即可重领），
        # 不是"没配"。所以这里用 `get(..., 60)` 而不是 `... or 60`。
        self.retry_backoff_seconds = int(self.cfg.get("retry_backoff_seconds", 60))
        # `search()` 一次最多领跑几轮（每轮一条请求）。它只影响这个新动作：
        # `run_once` / `run` 的语义一个字没动。
        self.search_max_rounds = int(self.cfg.get("search_max_rounds", 3))
    def _enqueue_search(self, topic: str, mode: str, description: str,
                        providers: Iterable[str] | None = None) -> dict:
        """把一条按主题的检索请求入队（过 I7 准入闸门 + 取号 + 落行）。

        与 CLI `submit` 同一套口径：同一个事务、同一个取号函数（`interactions.next_prefixed_id`）、
        同一份行校验。差别只有一处且是有意的：这里先过准入闸门（`admit_search_request` 的 docstring
        逐字写了理由 —— 人在 CLI 上知道自己在提交什么，角色在循环里提问必须受在途上限约束）。
        `providers` 原样落进 `SearchRequest.providers`：空 = 按角色级接线查（与加这一格之前一致）；
        非空 = 这一行只问这几个源。它是行上的属性，不改角色级接线 —— 一条请求点名的源不许影响
        下一条请求（那会让"谁提的"在链路上丢失）。
        """
        with self.store.tx("search_requests", actor=self.actor, note="a.search") as tx:
            rows = tx.rows("search_requests")
            gate = X.admit_search_request(rows, submitted_by=self.actor)
            if not gate.get("admitted"):
                return gate
            rid = X.next_prefixed_id(rows, "request_id", "r")
            row = S.SearchRequest(
                request_id=rid,
                timestamp=S.now_iso(),
                topic=topic,
                mode=mode,
                content_description=str(description or ""),
                done=False,
                submitted_by=self.actor,
                priority=str(gate.get("priority") or "medium"),
                providers=[str(x) for x in (providers or [])],
            )
            row.validate()                 # 先校验后落盘（与 store 同一条纪律）
            tx.upsert("search_requests", row.to_dict(), note="a.search")
        out = dict(gate)
        out["request_id"] = rid
        return out
    def _request_row(self, request_id: str) -> dict | None:
        """读一条请求行（无锁快照读；只用于汇报，不用它做判断依据）。"""
        for r in self.store.rows("search_requests"):
            if str(r.get("request_id")) == str(request_id):
                return dict(r)
        return None
    def _literature_brief(self, lit_ids: Iterable[str]) -> list[dict]:
        """把 `result_lit_ids` 变成召唤方读得懂的几行（标题/年份/DOI/有没有全文）。"""
        want = {str(x) for x in lit_ids}
        out: list[dict] = []
        for r in self.store.rows("literature"):
            if str(r.get("lit_id")) not in want:
                continue
            out.append({
                "lit_id": str(r.get("lit_id")),
                "title": str(r.get("title") or ""),
                "year": r.get("year"),
                "doi": r.get("doi"),
                "has_fulltext": bool(r.get("path")),
            })
        out.sort(key=lambda x: x["lit_id"])
        return out
    def _claim(self) -> ClaimOutcome:
        """在锁内按 I7 优先级领取一条待办请求：置 claimed_by / lease_until / attempts+=1。

        排序键全权由 `interactions.order_pending_requests` 决定，这里不另写排序（两套判据必然漂移，
        而漂移的表现是"高优先级静默沉底"，不会报错）；A 只排队、不抢占，高优先级请求在下一轮
        `_claim()` 时自然排到队首。租约唯一判据是"是否仍在有效期内"（用 `store.lease_expired`）：
        在未来 ⇒ 不得被取走（哪怕 high）；为空或已过期 ⇒ 可以抢。`claimed_by` 不参与"要不要跳过"，
        只用来把两种跳过分开：`skipped_lease_active`（别人在做）/ `skipped_lease_backoff`（我们自己的
        退避）。这一格曾少读一半：退避租约是 ``claimed_by=None`` + 未来的 `lease_until`，若额外要求
        `claimed_by` 非空，那条租约永远读不到 ⇒ 同一实例下一轮再领同一条、连打同一个 API。
        没取到时 `skipped_reason` 逐个命名：``"no_pending_request"`` / ``"pending_requests_all_leased"`` /
        ``"pending_requests_all_in_backoff"`` / ``"no_claimable_request"``（优先级即这个顺序）。
        """
        with self.store.tx("search_requests", actor=self.actor, note="claim") as tx:
            rows = tx.rows("search_requests")
            # 只拿 order_pending_requests 的输出，不自己再造一份顺序。
            ordered = X.order_pending_requests(rows)
            pending = len(ordered)
            skipped_lease_active = 0
            skipped_lease_backoff = 0
            gave_up = 0
            for r in ordered:
                # 先判租约，再判 attempts：一条租约还在走的请求不该由我们来"放弃"，
                # 否则会把别人手上的活（或我们自己刚失败、正在退避的活）单方面判死。
                # 判据是租约是否仍在有效期内，不附加 `claimed_by` 条件：
                # 搜索失败的退避租约正是 `claimed_by=None` + 未来的 `lease_until`，
                # 一旦这里要求 `claimed_by` 非空，那条租约就写了等于没写。
                # `claimed_by` 只决定这条被跳过的活记进哪个计数（别人 / 我们自己）。
                if not lease_expired(r.get("lease_until")):
                    if r.get("claimed_by"):
                        skipped_lease_active += 1  # 别人正在做
                    else:
                        skipped_lease_backoff += 1  # 我们自己上次失败留下的退避
                    continue
                attempts = int(r.get("attempts") or 0)
                if attempts >= self.max_attempts:
                    # 显式放弃：done=true + last_error，避免无限重试
                    r["done"] = True
                    r["outcome"] = "gave_up"
                    r["last_error"] = f"超过最大尝试次数 {self.max_attempts}，已放弃。上一次错误：{r.get('last_error')}"
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("search_requests", r, note="give_up")
                    gave_up += 1
                    continue
                r["claimed_by"] = self.actor
                r["lease_until"] = make_lease(self.lease_seconds)
                r["attempts"] = attempts + 1
                tx.upsert("search_requests", r, note="claimed")
                # 把"为什么是这一条"写进事件日志：ARunResult 只活在调用方内存里，
                # 而事后复盘（"那条 high 为什么排在后面"）靠的是 events.jsonl。
                tx.info(
                    "claim_order",
                    request_id=r.get("request_id"),
                    priority=r.get("priority"),
                    priority_rank=X.priority_rank(r.get("priority")),
                    pending=pending,
                    skipped_lease_active=skipped_lease_active,
                    skipped_lease_backoff=skipped_lease_backoff,
                    order=[x.get("request_id") for x in ordered],
                )
                return ClaimOutcome(
                    request=dict(r),
                    pending=pending,
                    skipped_lease_active=skipped_lease_active,
                    skipped_lease_backoff=skipped_lease_backoff,
                    gave_up=gave_up,
                )
            if pending == 0:
                reason = "no_pending_request"
            elif skipped_lease_active == pending:
                reason = "pending_requests_all_leased"
            elif skipped_lease_backoff == pending:
                # 不能并进上面那一类：那句诊断说的是"别人持着"，
                # 而这里的活全是我们自己上次失败留下的退避。
                reason = "pending_requests_all_in_backoff"
            else:
                reason = "no_claimable_request"
            return ClaimOutcome(
                pending=pending,
                skipped_lease_active=skipped_lease_active,
                skipped_lease_backoff=skipped_lease_backoff,
                gave_up=gave_up,
                skipped_reason=reason,
            )
    @staticmethod
    def _query_description(topic: str, description: str) -> str:
        """挑"能进查询串的那一份 description"：只留英文关键词，非 ASCII 的部分丢掉。

        真机实测（2026-09-30，`temp/_probe_precise_desc.py`）：G 写了一段中文 description，`precise`
        把它拼进查询串 ⇒ OpenAlex 0 条；同一句 topic 换成英文短语 ⇒ 8 条里 7 条对题。中文描述不是
        "信息少"，而是把检索带偏；而两层闸门都不拦它 —— `providers` 只对纯中文题面 fail-closed
        （抛 `query_not_applicable_cjk`），题面+中文描述混排走 `applicable_as_is`，于是静默清零。
        判据不是"含不含 ASCII 字母"（第一版就是这条，被 `used_by=main.tex:introduction` 这种"中文里
        夹一个英文路径"骗过）：丢掉非 ASCII 后至少还剩两个英文词才拿它当查询描述，否则传空串
        （provider 只用题面构造查询）。
        留痕不受影响：`content_description` 在请求行上原样保留；`search_literature` 的返回里另给
        `query_description`，让调用方知道实际用了什么。
        """
        raw = str(description or "")
        ascii_only = "".join(ch if ch.isascii() else " " for ch in raw)
        words = [w for w in ascii_only.split() if any(c.isalpha() for c in w)]
        return " ".join(words) if len(words) >= 2 else ""
    _NOT_SENT_STATES: tuple[str, ...] = ()
    def _not_sent_states(self) -> tuple[str, ...]:
        """懒取第三态取值（不在导入期去碰 providers，免得凭空多一条导入边）。"""
        if not self._NOT_SENT_STATES:
            from .. import providers as P

            type(self)._NOT_SENT_STATES = (P.QUERY_NOT_APPLICABLE_CJK, P.QUERY_EMPTY)
        return self._NOT_SENT_STATES
    def _split_errors(self, errors: Sequence[str]) -> tuple[list[str], list[str]]:
        """把 provider 的失败分成 `(没发出去的, 发出去但失败的)`。

        为什么要分（2026-09-30 加）：`providers` 对抽不出英文关键词的题面是 fail-closed，
        抛出的 `ProviderError` 消息里逐字带第三态名。若把它与"网络抖动"混成一档，
        `run_once` 就按可重试处理 —— 试满 `max_attempts`、每次留退避租约，
        最后落 `search_failed`。而"这一问没发出去"是确定性的：重试一万次也不会变。
        混档的代价有两个：① 白烧三次上游配额与三次等待；② 读数上"没问"与"问了失败"
        长得一样（三态被折平）。这一分割不动 `run_once` 对网络抖动的重试语义 ——
        它只把"不可能靠重试变好的那一类"提前终结。
        """
        states = self._not_sent_states()
        not_sent = [e for e in errors if any(s in e for s in states)]
        sent_but_failed = [e for e in errors if e not in not_sent]
        return not_sent, sent_but_failed
    def _wired_provider_names(self) -> list[str]:
        """角色级接线上有哪些源名（按接线次序，同名只算一次）。

        它是两处共用的那一份可用名单：入队之前的核名
        （`AgentA.search_literature` 的第三态）与领取时的选源
        （`_pick_named_providers`）。两处各自去点一遍名必然漂，
        而漂的表现是"报错里给的可用名单不全"—— 照着它改参数还是错。
        """
        out: list[str] = []
        for p in self.providers:
            name = str(getattr(p, "name", type(p).__name__))
            if name and name not in out:
                out.append(name)
        return out

    def _pick_named_providers(self, named: Iterable[str]) -> tuple[list[Any], list[str]]:
        """按名字从角色级接线里挑实例 ⇒ `(挑到的, 接线里没有的名字)`。

        返回两个值而不是一个：把"没接线的名字"与"挑到的实例"折进同一个列表，
        调用方就再也分不出"这个源没交货"与"这个源根本没接线"（三态纪律）。
        次序保留请求行点名的次序 —— 合并时先到者优先，次序是口径的一部分。
        """
        pool: dict[str, Any] = {}
        for p in self.providers:
            pool.setdefault(str(getattr(p, "name", type(p).__name__)), p)
        picked: list[Any] = []
        missing: list[str] = []
        for name in named:
            p = pool.get(name)
            if p is None:
                missing.append(name)
            elif p not in picked:
                picked.append(p)
        return picked, missing

    @staticmethod
    def _source_rows(stats: Any) -> list[dict]:
        """逐源读数行（形态照工具面 `search.literature` 的 `sources[]`）。

        只做格式搬运，不重新判一遍：三态（上游 `failed` / 这一问没发出去
        `refused` / 交货了 `delivered`）由 `providers.ProviderStat` 自己的三个属性
        回答，在这里再判一次就是第二份口径（FC-03）。次序保留问出去的次序，
        它与请求行点名的次序一致。
        """
        rows: list[dict] = []
        for name, st in (stats or {}).items():
            rows.append({
                "name": str(name),
                "status": str(getattr(st, "status", "") or ""),
                "count": int(getattr(st, "count", 0) or 0),
                "error_kind": str(getattr(st, "error_kind", "") or ""),
                "error": str(getattr(st, "error", "") or ""),
                "delivered": bool(getattr(st, "delivered", False)),
                "refused": bool(getattr(st, "refused", False)),
            })
        return rows

    def _search(self, req: dict) -> tuple[list[Any], list[str], dict]:
        """按这一行请求检索，并把"这一次问得怎么样"的读数一起交回。

        `providers` 这一格是唯一的开关（三态）：行上没点名源（空数组）⇒ 走 `_search_along_wiring`，
        按角色级接线查，与加这一格之前逐字相同；点名了源 ⇒ 只问点名的那些，跨源去重与逐源三态
        全部交给 `providers.MultiProvider`（与工具面 `search.literature` 的多源分支是同一份实现）；
        点名了接线里没有的源 ⇒ 如实进 `errors`（并列出可用名单），不静默丢掉那个名字。
        第三个返回值是读数（`providers_requested` / `role_providers` / `sources` / `cost`），键名与形状
        照工具面的同名读数。领取侧还再核一遍名的理由：队列里的行还可以由别的手写路径建出来
        （CLI `submit`、别的角色的 gap 分支），也可能在"换了接线重启"之后才被领到。
        """
        mode = req["mode"]
        limit = int(self.limits.get(mode, 10))
        # 查询串里只用"含 ASCII 关键词"的那一份描述（理由见 `_query_description`）。
        # 请求行上的 `content_description` 一字不动 —— 那是审计留痕，不是查询串。
        query_desc = self._query_description(req.get("topic") or "", req.get("content_description") or "")
        named = [str(x) for x in (req.get("providers") or [])]
        t0 = time.monotonic()
        if not named:
            out, errors = self._search_along_wiring(req["topic"], mode, query_desc, limit)
            return out, errors, {
                # 第一态：`providers_requested=None` 才是"没点名"的读数。
                # 写成空数组会与"点名了、但一个都没接上"同形。
                "providers_requested": None,
                "role_providers": self._wired_provider_names(),
                "sources": [],
                "cost": {"provider_calls": len(self.providers),
                         "elapsed_s": round(time.monotonic() - t0, 3)},
            }

        picked, missing = self._pick_named_providers(named)
        errors = [
            f"{name}: unknown_provider: 这一行点名的源不在当前接线上"
            f"（可用：{self._wired_provider_names()}）"
            for name in missing
        ]
        if not picked:
            return [], errors, {
                "providers_requested": list(named),
                "role_providers": self._wired_provider_names(),
                "sources": [],
                "cost": {"provider_calls": 0, "elapsed_s": round(time.monotonic() - t0, 3)},
            }

        # 惰取：不在导入期去碰 provider 层，免得凭空多一条导入边（同 `_not_sent_states`）。
        from .. import providers as P

        # 并发度仍是 1：`MultiProvider` 也是逐个问（源之间串行），
        # 与 `_search_along_wiring` 一样不会同时打多个 API。
        multi = P.MultiProvider(picked, name="a.request")
        out: list[Any] = []
        try:
            out = list(multi.search(req["topic"], mode, query_desc, limit) or [])
        except Exception as e:  # noqa: BLE001
            # `MultiProvider` 默认 fail_fast=False ⇒ 单个源炸不会走到这里。
            # 走到这里说明是它自己的合并环节炸了（例如候选不是它认的形状）——
            # 那与"某个源失败"不是一回事，必须单独如实报出来。
            errors.append(f"multi: {type(e).__name__}: {e}")
        sources = self._source_rows(multi.last_stats)
        for row in sources:
            if row["status"] == "failed" or row["refused"]:
                errors.append(f"{row['name']}: {row['error']}")
        return out, errors, {
            "providers_requested": list(named),
            "role_providers": self._wired_provider_names(),
            "sources": sources,
            "cost": {"provider_calls": len(picked),
                     "elapsed_s": round(time.monotonic() - t0, 3)},
        }

    def _search_along_wiring(self, topic: str, mode: str, query_desc: str,
                             limit: int) -> tuple[list[Any], list[str]]:
        """第一态（请求行没点名源）：串行问角色级接线上每一个源。

        并发度故意为 1（串行 provider）——避免同时打多个 API 触发限流。
        候选只做拼接、不在这里跨源去重：判重在提交阶段统一做
        （`dedup.find_existing_literature` + 锁内重判），这里是加 `providers`
        这一格之前逐字相同的那条路。
        """
        out: list[Any] = []
        errors: list[str] = []
        for p in self.providers:
            try:
                got = p.search(topic, mode, query_desc, limit)
                out.extend(got or [])
            except Exception as e:  # provider 失败不应让整个请求失败
                errors.append(f"{getattr(p, 'name', type(p).__name__)}: {type(e).__name__}: {e}")
        return out, errors
    def _stage_download(self, cand: Any, staging: Path) -> dict:
        """把候选的 PDF 下到 staging 目录（无锁，慢操作）。

        返回 DownloadResult 形状的 dict；不抛异常 —— 下载失败是预期内的常态。
        """
        base = {"status": "skipped", "http_status": None, "bytes": 0, "sha256": None, "error": None}
        if not self.do_download:
            base["error"] = "download_disabled"
            return base
        url = getattr(cand, "pdf_url", None)
        # ---- `R-45`（`draft/28` §154）：把试过哪个 URL记进下载记录。
        # 审计时撞到的真问题：6 条"ok 其实是 HTML"的行，台账里查不到它们下载的是哪个 URL
        # （URL 只活在当次 provider 候选里），于是"为什么拿到 HTML"只能靠猜。
        # 记 URL 与来源（`pdf_url_source`，OpenAlex 侧还会带 `|landing_same_as_pdf` 标记）之后，
        # 这一格可事后复核。
        base["url"] = url or None
        src = getattr(cand, "pdf_url_source", None)
        if src:
            base["url_source"] = str(src)
        if not url:
            base["error"] = "no_pdf_url"
            return base
        if self.downloader is None:
            base["error"] = "no_downloader"
            return base
        hint = f"{T.slugify(getattr(cand, 'title', '') or 'untitled', 60)}"
        try:
            res = self.downloader.download(url, staging, hint)
        except Exception as e:
            base["status"] = "failed"
            base["error"] = f"{type(e).__name__}: {e}"
            return base
        # "下载成功"不等于"拿到的是要的东西"。真实环境下 URL 以 .pdf 结尾却返回
        # text/html 是常见的（落地页、cookie 同意页、代理/反爬拦截页）—— 实测就碰到
        # 一个 12.4 MB 的 HTML 被当成论文存下来。下载器已经把它标成
        # `content_type_mismatch`，但如果这里仍记 status="ok"，下游 B 会照常去抽取
        # 那个 HTML，把网页导航文字当成"概念"。所以必须在这里把状态降级，
        # 让"上层决定"这件事真的发生。
        status = "ok" if getattr(res, "ok", False) else "failed"
        err = getattr(res, "error", None)
        if status == "ok" and err and str(err).startswith("content_type_mismatch"):
            status = "content_mismatch"
        out = {
            "status": status,
            "http_status": getattr(res, "http_status", None),
            "bytes": getattr(res, "bytes", 0) or 0,
            "sha256": getattr(res, "sha256", None),
            "error": err,
            "_staged_path": getattr(res, "path", None),
        }
        # `R-45` 的字段必须也出现在这条成功分支上。它原来只在
        # `no_pdf_url`/`no_downloader`/异常那几条早退分支里（那是我第一次改的时候
        # 只补了容易看见的几处）⇒ 结果最需要它们的成功记录里反而没有 URL。
        # 实测代价：A2 重下六条之后，行上的 `download.url` 全为 `null`，
        # "这一条到底下的是哪个 URL"又变成不可查（正是 R-45 要解决的病）。
        out["url"] = url
        if base.get("url_source"):
            out["url_source"] = base["url_source"]
        return out
    def _attach_staged(self, lit_id: str, dl: dict) -> tuple[str | None, dict]:
        """把 staging 里的字节搬进 `<library>/<lit_id>/`，返回 `(相对路径, 清洗过的 download)`。

        一处实现、两处使用（新建行与补下载共用）：搬文件的判据只有一个 ——
        `status ∈ ("ok", "content_mismatch")` 且有 staged 字节。`content_mismatch`
        的字节照样落盘：它是证据（能看到对方返回了什么），只是下游不许拿它当文献抽取；
        丢掉证据会让"为什么下载不到"变成不可查的问题。

        搬失败（例如目录不可写）⇒ `status="failed"`、`rel_path=None` ——
        绝不让"没搬成"被下游读成"下到了"。
        """
        staged = dl.pop("_staged_path", None)
        out = {k: v for k, v in dl.items() if not k.startswith("_")}
        st = dl.get("status")
        if not (staged and Path(staged).exists() and st in ("ok", "content_mismatch")):
            return None, out
        try:
            rel_dir = self.store.library / lit_id
            rel_dir.mkdir(parents=True, exist_ok=True)
            target = rel_dir / Path(staged).name
            # 同盘 os.replace 原子；跨盘回退到 move
            shutil.move(str(staged), str(target))
        except Exception as e:  # 建目录/搬文件失败 => 降级为"未下载"，但不丢元数据
            # 两个动作放在同一个 try 里是判据逼出来的：只包 move 时，
            # "`<library>/<lit_id>` 位置上是个文件"会让 `mkdir` 抛出并把整轮 A 带崩 ——
            # 而正确的语义是"这一篇没拿到"，不是"整个检索挂了"。
            out["status"] = "failed"
            out["error"] = f"move_failed: {type(e).__name__}: {e}"
            return None, out
        return f"{lit_id}/{target.name}", out


class AgentA(_RunOnce, _Run, _SearchLiterature, _IngestLocal, _ShelfSearch, _WalkCitations, _Core):
    """文献搜索智能体。providers/downloader 由外部注入，便于离线测试。"""



def _selftest() -> int:
    """`python -m agentflow.agent_a` 的自检：跑通主路径并断言关键不变量。

    为什么必须存在（它修的是一个静默空成功）：`scripts/release_check.py` 第 2 项逐个
    `python -m agentflow.agent_<role>` 并看退出码，而 `agent_a` 曾没有 `__main__` 块 ⇒ 那条命令输出
    0 行、退出码 0，旧判据把它记成"自检通过"，其实什么都没检查（`DEVELOPMENT.md` §10-D5 与附录 C
    第 4 条都记着这件事；现在 `release_check.item_selftests` 用 `has_selftest` 判据把它报成 `unknown`）。
    自检覆盖主路径与三条降级路径，全部离线、确定性：I7 优先级、落库（含下载证据）、判重幂等、
    队列空/全被租/全在退避/全被放弃四态、搜索失败不置 done 且退避租约被遵守（"写了"必须升级成
    "写了且被读"）、下载失败仍然登记。退出码：`0` = 全部通过；`1` = 有失败项。
    """
    import hashlib
    import shutil
    import tempfile
    from types import SimpleNamespace

    from ..fetch import FetchResult

    checks: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        checks.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    class _StubProvider:
        """确定性替身：不联网。`error` 非空时模拟 provider 抛异常。"""

        name = "selftest-stub"

        def __init__(self, candidates=(), error: BaseException | None = None):
            self.candidates = list(candidates)
            self.error = error

        def search(self, topic, mode, description, limit):
            if self.error is not None:
                raise self.error
            return list(self.candidates)

    class _Downloader:
        """落一个真实文件并给出真实 sha256（不联网）——让"下载证据"这条断言有意义。"""

        def download(self, url, dest_dir, hint):
            p = Path(dest_dir) / f"{hint or 'file'}.txt"
            p.write_text("selftest payload", encoding="utf-8")
            data = p.read_bytes()
            return FetchResult(ok=True, path=str(p), http_status=200, bytes=len(data),
                               sha256=hashlib.sha256(data).hexdigest(), error=None)

    class _FailDownloader:
        def download(self, url, dest_dir, hint):
            # `kind` 是 `FetchResult` 的受控失败档（`F-6`）：失败的下载必须
            # 说得出"为什么"是受控词表里的一档，否则失败原因无法按轴统计。
            return FetchResult(ok=False, kind="http_500", path=None, http_status=500,
                               bytes=0, sha256=None, error="selftest boom")

    def _cand(**kw) -> SimpleNamespace:
        """鸭子类型的候选。刻意不 import `providers.Candidate`：这里要验证的是
        `AgentA` 对候选的用法（全是 `getattr` + 默认值），不该被 provider 层的
        字段增删牵着走；用最窄的对象反而把那份契约钉得更死。"""
        base = dict(title="Selftest literature", doi="10.9999/selftest", year=2026,
                    pdf_url="http://example.invalid/selftest.pdf")
        base.update(kw)
        return SimpleNamespace(**base)

    def _add_request(st: Store, rid: str, *, topic: str, priority: str, attempts: int = 0,
                     claimed_by: str | None = None, lease_until: str | None = None) -> None:
        with st.tx("search_requests", actor="selftest") as tx:
            row = S.SearchRequest(request_id=rid, timestamp=S.now_iso(), topic=topic, mode="broad",
                                  content_description="", done=False, submitted_by="selftest",
                                  priority=priority, attempts=attempts,
                                  claimed_by=claimed_by, lease_until=lease_until)
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="selftest")

    def _drain(st: Store) -> None:
        """把队列清空（每段断言都在一个已知的队列上做，避免段落之间互相干扰）。"""
        with st.tx("search_requests", actor="selftest") as tx:
            for r in tx.rows("search_requests"):
                if not r.get("done"):
                    r["done"] = True
                    r["outcome"] = "no_results"
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("search_requests", r, note="selftest_drain")

    def _req(st: Store, rid: str) -> dict:
        return next(r for r in st.rows("search_requests") if r.get("request_id") == rid)

    try:
        root = Path(tempfile.mkdtemp(prefix="agentflow_agent_a_selftest_"))
    except OSError:  # pragma: no cover - 沙箱拒绝系统临时目录时退到仓库内
        root = Path(__file__).resolve().parents[2] / "demo" / "agent_a_selftest"
        shutil.rmtree(root, ignore_errors=True)
    try:
        print("[agent_a 自检] 离线、确定性；工作区：", root)
        st = Store(root)
        st.init(force=True)
        cfg = {"download": True, "lease_seconds": 900, "max_attempts": 3, "retry_backoff_seconds": 60}

        # ---- 1) I7：取任务只看 interactions 的排序，high 先于更早提交的 low
        _add_request(st, "r-0001", topic="low topic", priority="low")
        _add_request(st, "r-0002", topic="high topic", priority="high")
        a = AgentA(st, providers=[_StubProvider([_cand()])], downloader=_Downloader(), config=cfg)
        first = a.run_once()
        check("I7：先取 high（r-0002）而不是先提交的 low（r-0001）",
              first.request_id == "r-0002", f"got={first.request_id}")
        check("I7：优先级与序号被如实暴露（判定'为什么它先被取走'靠次序而非字符串）",
              first.priority == "high" and first.priority_rank == X.priority_rank("high"))
        check("主路径：注册 1 条、请求终局 ok", first.registered == 1 and first.outcome == "ok")
        check("下载计数：downloaded=1 / download_failed=0", first.downloaded == 1 and first.download_failed == 0)
        lits = st.rows("literature")
        check("文献行带本地路径且 processed=False（置 true 是 B 的职责）",
              len(lits) == 1 and bool(lits[0].get("path")) and lits[0].get("processed") is False)
        check("下载证据（sha256）随行落库，不是只报一个计数",
              bool((lits[0].get("download") or {}).get("sha256")))
        check("请求终局带 result_lit_ids 且释放租约",
              _req(st, "r-0002")["result_lit_ids"] == [lits[0]["lit_id"]]
              and _req(st, "r-0002")["claimed_by"] is None)
        check("候选键挂在行内供判重诊断（literature_keys 的第一级）",
              bool(lits[0].get("_keys")) and any(str(k).startswith("doi:") for k in lits[0]["_keys"]))

        # ---- 2) 幂等：同一篇再来一次只累积来源，不新建行
        second = a.run_once()
        check("幂等：重跑同一候选 ⇒ duplicated=1、registered=0、文献仍只有 1 行",
              second.duplicated == 1 and second.registered == 0 and len(st.rows("literature")) == 1)
        check("幂等：来源请求代号累积到同一行上",
              sorted(st.rows("literature")[0]["source_request_ids"]) == ["r-0001", "r-0002"])

        # ---- 3) 队列空 = 三态里的"没做"，理由必须明确
        third = a.run_once()
        check("队列空：skipped_reason=no_pending_request（不是静默的成功）",
              third.request_id is None and third.skipped_reason == "no_pending_request")

        # ---- 4) 三态可区分：'被别人持着' ≠ '队列空了' ≠ '全被放弃'
        _drain(st)
        _add_request(st, "r-0004", topic="exhausted", priority="low", attempts=3)
        _add_request(st, "r-0007", topic="held by another A", priority="high",
                     claimed_by="agent-A-other", lease_until=make_lease(900))
        c = AgentA(st, providers=[_StubProvider([_cand(title="never used")])], downloader=_Downloader(), config=cfg)
        fourth = c.run_once()
        check("超过 max_attempts ⇒ 显式放弃并计入 gave_up（不是静默什么都不做）",
              fourth.gave_up == 1 and fourth.request_id is None and fourth.skipped_reason == "no_claimable_request")
        check("放弃是可读的终局：done=true + outcome=gave_up",
              _req(st, "r-0004")["done"] is True and _req(st, "r-0004")["outcome"] == "gave_up")
        check("'被有效租约占着'单独计数，且与'队列空了'是不同的 skipped_reason",
              fourth.skipped_lease_active == 1 and fourth.skipped_reason != "no_pending_request")
        check("被有效租约占着的行不会被抢走（claimed_by 原样保留）",
              _req(st, "r-0007")["claimed_by"] == "agent-A-other" and _req(st, "r-0007")["done"] is False)

        # ---- 5) 下载失败不阻塞：文献行照常登记（path=null），并单独计数
        _add_request(st, "r-0005", topic="download fails", priority="medium")
        d = AgentA(st, providers=[_StubProvider([_cand(title="Unreachable paper", doi="10.9999/unreachable")])],
                   downloader=_FailDownloader(), config=cfg)
        dl_fail = d.run_once()
        check("下载失败：仍然注册文献行、请求以 ok 收尾（'知道有这篇但拿不到'本身是结果）",
              dl_fail.registered == 1 and dl_fail.download_failed == 1 and dl_fail.outcome == "ok")
        row5 = next(r for r in st.rows("literature") if r["title"] == "Unreachable paper")
        check("下载失败：path=null 且 download.status=failed（证据不丢）",
              row5["path"] is None and (row5.get("download") or {}).get("status") == "failed")

        # ---- 6) 下载被关闭时不得伪装成"下载成功"
        _add_request(st, "r-0006", topic="download disabled", priority="medium")
        e = AgentA(st, providers=[_StubProvider([_cand(title="Disabled download", doi="10.9999/disabled")])],
                   downloader=_Downloader(), config={**cfg, "download": False})
        off = e.run_once()
        row6 = next(r for r in st.rows("literature") if r["title"] == "Disabled download")
        check("download=False：downloaded 计数为 0 且行内 error=download_disabled",
              off.downloaded == 0 and (row6.get("download") or {}).get("error") == "download_disabled")

        # ---- 7) 只剩"被别人占着"的行时，run() 既不停摆也不谎报"队列空"
        summary = e.run(max_requests=None)
        check("run()：只剩被租约占用的行 ⇒ skipped_reason=pending_requests_all_leased",
              summary["skipped_reason"] == "pending_requests_all_leased",
              f"got={summary['skipped_reason']}")

        # ---- 8) 搜索失败：不置 done，留给租约重试（一次网络抖动不该判死请求）
        _drain(st)
        _add_request(st, "r-0003", topic="network down", priority="high")
        b = AgentA(st, providers=[_StubProvider(error=RuntimeError("selftest network down"))],
                   downloader=_Downloader(), config=cfg)
        failed = b.run_once()
        r3 = _req(st, "r-0003")
        check("搜索失败：请求没有被置 done，且 last_error 留下了原因",
              failed.outcome is None and r3["done"] is False and "network down" in str(r3["last_error"]))
        check("搜索失败：写了退避租约并把 claimed_by 置空（可重试，且在排序里靠后）",
              bool(r3["lease_until"]) and r3["claimed_by"] is None)

        # ---- 8b) "写了"不等于"被遵守"：再领一次必须领不到它。
        # 这是本次修复真正的验收判据。旧自检只断言了"租约被写入"
        # （`bool(r3["lease_until"])`），而一个断言"写入了"的测试无法发现
        # "没有任何地方读它"：`_claim` 的跳过判据曾经额外要求 `claimed_by` 非空，
        # 而失败分支恰好把 `claimed_by` 置成了 None ⇒ 那条租约永远不会被读到，
        # 同一个 A 实例下一轮立刻再领同一条、连打同一个 API。所以这里必须再跑一次
        # `_claim()` 并且断言它没领到（attempts 不增，是最硬的那条证据 ——
        # attempts 只在 `_claim` 里 +1）。
        re_claim = b._claim()
        r3_after = _req(st, "r-0003")
        check("搜索失败后的退避租约被遵守：再领一次领不到它，attempts 不增",
              re_claim.request is None and r3_after["attempts"] == 1,
              f"claimed={re_claim.request and re_claim.request.get('request_id')} "
              f"attempts={r3_after['attempts']}")
        check("退避中与'被别人持着'分开：reason=pending_requests_all_in_backoff 且计数进 backoff",
              re_claim.skipped_reason == "pending_requests_all_in_backoff"
              and re_claim.skipped_lease_backoff == 1 and re_claim.skipped_lease_active == 0,
              f"reason={re_claim.skipped_reason} backoff={re_claim.skipped_lease_backoff} "
              f"active={re_claim.skipped_lease_active}")

        # ---- 9) 空库：run() 立刻停下
        st_empty = Store(Path(root) / "empty")
        st_empty.init()
        none_agent = AgentA(st_empty, providers=[], downloader=None, config=cfg)
        empty_summary = none_agent.run(max_requests=None)
        check("空库 run()：skipped_reason=no_pending_request 且 processed 为 0",
              empty_summary["skipped_reason"] == "no_pending_request" and empty_summary["processed"] == 0)
    except Exception as e:  # noqa: BLE001
        # 自检自己炸了也必须报 FAIL，不许把 traceback 当成结论往外抛：
        # 检查器的"没跑成"与"跑成了、发现缺陷"是两件事，但两者都不是"通过"。
        # 没有这一层，一处异常会让退出码变成 1（看起来是失败）却既没有失败项清单、
        # 也看不出是哪一条挂的 —— 与"release_check 把 traceback 记成 unknown"同族。
        checks.append((f"自检执行中断：{type(e).__name__}: {e}", False))
        print(f"    [FAIL] 自检执行中断：{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    bad = [label for label, ok in checks if not ok]
    print(f"[agent_a 自检] {len(checks) - len(bad)}/{len(checks)} 项通过")
    if bad:
        print("[agent_a 自检] 失败项：")
        for label in bad:
            print(f"  - {label}")
        return 1
    return 0
