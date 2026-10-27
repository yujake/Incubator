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
            out, errors, stats = self._search_along_wiring(
                req["topic"], mode, query_desc, limit)
            return out, errors, {
                # 第一态：`providers_requested=None` 才是"没点名"的读数。
                # 写成空数组会与"点名了、但一个都没接上"同形。
                "providers_requested": None,
                "role_providers": self._wired_provider_names(),
                # 第一态也逐源报状态：改前这里是空数组，于是"两个源被限流"
                # 与"接线上的源全都 0 命中"在读数上完全同形（都只剩
                # `outcome=no_results`）。逐源读数由 `_search_along_wiring`
                # 产生，形状与点名那一态、与工具面 `search.literature` 的
                # `sources[]` 逐键相同。
                "sources": self._source_rows(stats),
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
                             limit: int) -> tuple[list[Any], list[str], dict]:
        """第一态（请求行没点名源）：串行问角色级接线上每一个源，并留下逐源读数。

        并发度故意为 1（串行 provider）——避免同时打多个 API 触发限流。
        候选只做拼接、不在这里跨源去重：判重在提交阶段统一做
        （`dedup.find_existing_literature` + 锁内重判），这里是加 `providers`
        这一格之前逐字相同的那条路。

        ## 第三个返回值为什么必须有（逐源三态）

        改前这一态不产出 `sources`，于是"两个源被限流"与"接线上的源全都 0 命中"
        在动作读数上同形：两者都只剩 `outcome=no_results` 与一个空的 errors。
        区分它们靠的是 `providers.ProviderStat` 那一套受控状态，本方法只负责
        按源把事实填进去 —— 分类的真身仍在 `providers`（`provider_error_kind` /
        `_refusal_state_of_message` / `_provider_refusal`），这里不另写一份
        "限流还是被墙"的判据，否则两处一漂，"限流"就会在动作面上重新变成一个
        普通失败（FC-03 的老形态）。

        三档在读数上如何分开：跑成了（`status="ok"`，`count` 可能是 0）、
        上游抛了（`status="failed"` + `error_kind`，其中 `error_kind=rate_limited`
        就是限流那一档）、这一问根本没发出去（第三态状态名，`error_kind` 留空）。
        """
        from .. import providers as P

        out: list[Any] = []
        errors: list[str] = []
        stats: dict[str, Any] = {}
        for p in self.providers:
            name = str(getattr(p, "name", type(p).__name__))
            try:
                got = list(p.search(topic, mode, query_desc, limit) or [])
            except Exception as e:  # provider 失败不应让整个请求失败
                errors.append(f"{name}: {type(e).__name__}: {e}")
                refusal_state = P._refusal_state_of_message(str(e))
                stats[name] = P.ProviderStat(
                    status=refusal_state or "failed", count=0,
                    error_kind="" if refusal_state else P.provider_error_kind(e),
                    error=str(e),
                )
                continue
            # 有的 provider 对"这一问不适用"刻意不抛（`Y-1`）：统计面只能从它
            # 自己的台账上读。读法与 `MultiProvider` 是同一处实现。
            undispatched, why = P._provider_refusal(p, got)
            if undispatched:
                stats[name] = P.ProviderStat(
                    status=undispatched, count=0, error_kind="",
                    error=why or undispatched,
                )
                continue
            out.extend(got)
            stats[name] = P.ProviderStat(status="ok", count=len(got))
        return out, errors, stats
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
