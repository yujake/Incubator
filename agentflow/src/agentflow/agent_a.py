"""A 智能体：文献搜索。

职责（需求原文）：接收文献搜索请求清单 → 搜索 → 把文献下载到本地 → 维护文献表 → 把请求标记完成。

四个刻意的设计选择：

1. 锁只覆盖簿记，不覆盖网络。搜索与下载可能耗时数十秒；若持锁做这些事，
   B 智能体会被整段时间阻塞。因此流程切成"短事务声明租约 → 无锁做 I/O → 短事务提交"。
   代价是提交时必须在锁内重做一次判重（另一个 A 实例可能已抢先登记同一篇），
   这一步不能省。
2. 先落文献行，再置请求完成（DESIGN.md §2.4）。崩溃时请求仍是未完成，
   重跑靠 `dedup_key` 幂等，不会重复登记。
3. 下载失败不算请求失败。文献行照常登记（`path=null`），
   因为"我知道有这篇论文但拿不到全文"本身就是有价值的结果；B 会跳过它并计数。
4. 取任务只做排队，不做抢占（I7）。A 按 `interactions.order_pending_requests`
   给出的顺序取任务，排序键是"优先级 → 租约是否过期 → 提交时间 → request_id"。
   这里有两条硬约束：

   - 排序键只有那一份实现，本模块不另写一套（哪怕只是 `sort(key=...)`）。
     一旦 A 的取任务顺序与提交方（C/D）的派发顺序各持一套判据，
     "high 优先"就会静默失效 —— 不报错，只是最关键的矛盾永远排在后面。
     这正是 `RuleExtractor` docstring 警告过的"两个模块各持一套判据"。
   - 不抢占：正在跑的 A 已经付掉了检索与下载的成本，被高优先级请求打断只会让
     两条请求都变慢，还在 staging 里留下一堆半成品；收益小于代价。
     高优先级请求在下一次 `_claim()` 时自然排到队首。
     见 `DESIGN-INTERACTIONS.md` §5 待决问题 3。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import dedup as D
from . import interactions as X
from . import schema as S
from . import textutil as T
from .store import Store, StoreError, lease_expired, make_lease


@dataclass
class ARunResult:
    processed: int = 0
    registered: int = 0
    duplicated: int = 0
    downloaded: int = 0
    download_failed: int = 0
    download_suspect: int = 0
    gave_up: int = 0
    skipped_reason: str | None = None
    outcome: str | None = None
    # ---- I7：本轮"取了哪条、为什么是它、有什么被跳过"的审计信息。
    # 没有这几个字段，I7 的效果无法从外部观察：外部只能看到"处理了 1 条"，
    # 看不到它是不是优先级最高的那条，也看不到高优先级的那条为什么没被取走。

    #: 本轮取到的请求代号；`None` 表示本轮没取到任何请求（原因见 `skipped_reason`）。
    request_id: str | None = None
    #: 该请求的优先级，原样取自行。这里不做任何"修正"：A 的职责是按优先级取任务，
    #: 不是替提交方决定优先级（那会让"谁提的"这件事在链路上丢失）。
    priority: str | None = None
    #: `interactions.priority_rank(priority)`。单独给出是因为判定"为什么它先被取走"
    #: 靠的是次序而不是字符串 —— 直接比较字符串会得到 `"high" < "low"` 这种错结论。
    priority_rank: int | None = None
    #: 提交方（审计线索：这件事是谁提的）。
    submitted_by: str | None = None
    #: 定序时队列里的待办条数。
    queue_pending: int = 0
    #: 因"租约未过期且 `claimed_by` 非空"而被跳过的条数（别人正在做）。
    #: 这是"高优先级就在队里却没被取走"的合法解释之一，必须能被外部看见 ——
    #: 否则运维只能看到"什么都没做"，无从判断是队列空了还是全被别人占着。
    skipped_lease_active: int = 0
    #: 因"租约未过期且 `claimed_by` 为空"而被跳过的条数（我们自己上次搜索
    #: 失败留下的退避租约，`retry_backoff_seconds`）。
    #: 与 `skipped_lease_active` 分开数：两者要等的对象不同（等别人 / 等自己），
    #: 处置也不同（换个 A 实例跑 / 什么都别做，到点自然重试）。压在一起会让运维
    #: 去找一个不存在的"另一个 A 实例"。
    skipped_lease_backoff: int = 0

    def to_dict(self) -> dict:
        return {
            "processed": self.processed,
            "registered": self.registered,
            "duplicated": self.duplicated,
            "downloaded": self.downloaded,
            "download_failed": self.download_failed,
            "download_suspect": self.download_suspect,
            "gave_up": self.gave_up,
            "outcome": self.outcome,
            "skipped_reason": self.skipped_reason,
            "request_id": self.request_id,
            "priority": self.priority,
            "priority_rank": self.priority_rank,
            "submitted_by": self.submitted_by,
            "queue_pending": self.queue_pending,
            "skipped_lease_active": self.skipped_lease_active,
            "skipped_lease_backoff": self.skipped_lease_backoff,
        }


@dataclass
class ClaimOutcome:
    """`_claim()` 的结果：取任务这件事本身的结果，而不只是"取到的那一行"。

    为什么不让 `_claim()` 只返回 `dict | None`：一个 `None` 会同时表示几件完全不同的
    事，而它们对应的处置完全不同（这正是"三态纪律"要防的形态）：

    - ``pending == 0``                      —— 队列是空的（可以停）
    - ``skipped_lease_active > 0``          —— 有活，但都在别人手里（该等，或换个 A 实例跑）
    - ``skipped_lease_backoff > 0``         —— 有活，但都在我们自己的退避租约里
      （`claimed_by` 为空 + 未来的 `lease_until`）—— 处置是"什么都别做，到点自然重试"，
      与"换个实例跑"恰好相反（换实例也领不到：租约就写在行上，不认人）
    - ``gave_up > 0``                       —— 有活，但都超了重试上限（终局，别再等）

    压成一个 `None` 的后果不是"少一点信息"，而是误导运维：看到
    `skipped_reason="no_pending_request"` 会以为队列空了，而实际上队列里躺着一条
    high 优先级请求在等租约被修好。所以它们必须能被区分，`skipped_reason` 逐个命名。
    """

    #: 取到的请求（已置 claimed_by / lease_until / attempts+=1）；没取到时为 `None`。
    request: dict | None = None
    #: 定序时队列里的待办条数。
    pending: int = 0
    #: 租约未过期且 `claimed_by` 非空 ⇒ 跳过的条数（"别人正在做"）。
    skipped_lease_active: int = 0
    #: 租约未过期且 `claimed_by` 为空 ⇒ 跳过的条数（"我们自己上次失败的退避"）。
    skipped_lease_backoff: int = 0
    #: 本轮当场放弃（attempts 用尽）的条数。
    gave_up: int = 0
    #: 没取到请求时的原因，取值见 `_claim` 的 docstring；取到时为 `None`。
    skipped_reason: str | None = None

    @property
    def claimed(self) -> bool:
        """是否取到了请求。不要用 `bool(self.request)` 代替：那会在别处再造一个判据。"""
        return self.request is not None


# ---------------------------------------------------------------------- 智能体


class AgentA:
    """文献搜索智能体。providers/downloader 由外部注入，便于离线测试。"""

    def __init__(
        self,
        store: Store,
        *,
        providers: Iterable[Any],
        downloader: Any | None = None,
        config: dict | None = None,
        actor: str = "agent-A",
    ):
        self.store = store
        self.providers = list(providers)
        self.downloader = downloader
        self.cfg = config or {}
        self.actor = actor
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

    # ------------------------------------------------------------------ 取任务
    def _claim(self) -> ClaimOutcome:
        """在锁内按 I7 优先级领取一条待办请求：置 claimed_by / lease_until / attempts+=1。

        排序键全权由 `interactions.order_pending_requests` 决定
        （优先级 → 租约是否过期 → 提交时间 → request_id）。这里不另写排序：
        见模块 docstring 第 4 条 —— 两套判据必然漂移，而漂移的表现是
        "高优先级静默沉底"，不会报错。

        A 只排队，不抢占。 已经有一条请求在跑时，即使此刻来了更高的优先级，
        也要等它跑完 —— 正在跑的那条已经付掉了检索与下载的成本，打断它会让
        两条都变慢，还会在 staging 里留下半成品。高优先级请求在下一轮
        `_claim()` 时自然排到队首，这一点由 `order_pending_requests` 保证。

        保留的租约语义（唯一判据是"租约是否仍在有效期内"）：`lease_until` 在未来
        ⇒ 不得被取走（哪怕它是 high）；`lease_until` 为空或已过期 ⇒ 可以抢
        （空 = 无人持有；已过期 = 之前有人拿到却没做完，收回沉没成本比重新开一条更便宜）。
        `claimed_by` 不参与"要不要跳过"的判断，它只用来解释为什么被跳过
        （落进 `skipped_lease_active` 还是 `skipped_lease_backoff`）。
        租约判据用 `store.lease_expired`，与 `order_pending_requests` 内部用的是同一个
        函数，不在这里自己比较时间字符串。

        为什么判据必须是这样（它曾经少读了一半）：搜索失败时 `run_once` 写下的退避租约
        是 ``claimed_by=None`` + 未来的 `lease_until`；若这里额外要求 `claimed_by` 非空，
        那条租约就永远不会被读到 —— 同一个 A 实例下一轮立刻再领同一条，连打同一个
        API（最多到 `max_attempts` 才 `gave_up`）。写进存储的约束不等于被执行的约束，
        所以自检里既断言"租约被写了"，也断言"再领一次领不到"。

        两个计数分开数，因为它们对应两件不同的事（处置也不同）：

        - ``skipped_lease_active``  —— 租约有效 且 `claimed_by` 非空（别人正在做）
        - ``skipped_lease_backoff`` —— 租约有效 且 `claimed_by` 为空（我们自己上次失败
          留下的退避，要等到期才允许重试）

        实测提醒（别被"过期优先"的措辞误导）：`order_pending_requests` 把
        "租约为空（无人持有）"与"租约已过期"放进同一个排序桶，两者都排在
        "租约仍在走"的前面。因此过期租约不会插全新请求的队，但也不会被饿死
        （同桶内按 FIFO 轮到）。排序与跳过是两件事，不要混在一句话里：
        退避租约是靠本条跳过判据生效的；`order_pending_requests` 的分桶只负责
        让它在排序上不抢占（不排到全新请求前面）。按"过期优先"去改分桶，改坏的是排序；
        把跳过判据收紧回 ``claimed_by`` 非空，改坏的才是退避本身。

        没取到请求时给出的 `skipped_reason`（不许压成一个 None）：

        - ``"no_pending_request"``              —— 队列里没有未完成的请求（真没事可做）
        - ``"pending_requests_all_leased"``     —— 有未完成的，但全部被别人持着有效租约
        - ``"pending_requests_all_in_backoff"`` —— 有未完成的，但全部在自己的退避租约里
          （`claimed_by` 为空 + `lease_until` 在未来）。它与上一条必须分开：那句诊断
          说的是"别人持着"，而这里的活其实是我们自己上次失败留下的 —— 读成"别人在跑"
          会让运维去找一个不存在的另一个 A 实例（而换个实例照样领不到：租约写在行上，不认人）。
        - ``"no_claimable_request"``            —— 有未完成的，但剩下的全在本次被放弃
          （attempts 用尽 ⇒ done=true），或既有被别人持着的、又有在退避中的
          （"有活但都领不到"—— 最诚实的说法，不替调用方猜该等别人还是等自己），
          或其它任何未能归入上面某一类的情形

        优先级（判据只有这一处，顺序即优先级）：队列空 → 全被别人持着 → 全在退避中 →
        其余一律 ``no_claimable_request``。中间两类各自要求整队都是这一种情形
        （该计数 == `pending`），所以"一部分被别人持着、一部分在退避"这种混合情形
        自然落进最后一个，不会被谎报成其中任何一类。
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

    # ------------------------------------------------------------------ 搜索
    def _search(self, req: dict) -> tuple[list[Any], list[str]]:
        """并发度故意为 1（串行 provider）——避免同时打多个 API 触发限流。"""
        mode = req["mode"]
        limit = int(self.limits.get(mode, 10))
        out: list[Any] = []
        errors: list[str] = []
        for p in self.providers:
            try:
                got = p.search(req["topic"], mode, req.get("content_description") or "", limit)
                out.extend(got or [])
            except Exception as e:  # provider 失败不应让整个请求失败
                errors.append(f"{getattr(p, 'name', type(p).__name__)}: {type(e).__name__}: {e}")
        return out, errors

    # ------------------------------------------------------------------ 下载
    def _stage_download(self, cand: Any, staging: Path) -> dict:
        """把候选的 PDF 下到 staging 目录（无锁，慢操作）。

        返回 DownloadResult 形状的 dict；不抛异常 —— 下载失败是预期内的常态。
        """
        base = {"status": "skipped", "http_status": None, "bytes": 0, "sha256": None, "error": None}
        if not self.do_download:
            base["error"] = "download_disabled"
            return base
        url = getattr(cand, "pdf_url", None)
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
        return {
            "status": status,
            "http_status": getattr(res, "http_status", None),
            "bytes": getattr(res, "bytes", 0) or 0,
            "sha256": getattr(res, "sha256", None),
            "error": err,
            "_staged_path": getattr(res, "path", None),
        }

    # ------------------------------------------------------------------ 主流程
    def run_once(self) -> ARunResult:
        """处理至多一条待办请求，返回本轮的完整审计结果。

        三态纪律在这里的落点：取不到请求时不返回一个"看起来正常的空结果"，
        而是把"没做"的原因原样带出来（`skipped_reason` 四选一，取值与优先级见 `_claim`）。
        `processed/registered/...` 全是计数（"做了多少"），`skipped_reason` 是
        "为什么没做" —— 两者正交，调用方必须分别看。
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

        candidates, search_errors = self._search(req)

        staging = Path(tempfile.mkdtemp(prefix="agentflow-stage-", dir=str(self.store.library)))
        try:
            # ---- 阶段 1（无锁）：先把候选规范化 + 下载到 staging。
            # 这里不分配 ID、不写表，因此失败/崩溃都不会留下半成品。
            prepared: list[dict] = []
            downloads = 0
            for cand in candidates:
                title = getattr(cand, "title", "") or ""
                if not title.strip():
                    continue
                entry = {
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
                }
                if downloads < self.max_downloads:
                    dl = self._stage_download(cand, staging)
                    downloads += 1 if dl.get("status") != "skipped" else 0
                    entry["download"] = dl
                else:
                    entry["download"] = {"status": "skipped", "error": "max_downloads_reached",
                                         "http_status": None, "bytes": 0, "sha256": None}
                prepared.append(entry)

            # ---- 阶段 2（锁内，短）：重新判重 → 分配 ID → 落行 → 搬文件 → 标记请求完成。
            with self.store.tx("search_requests", "literature", actor=self.actor, note="register") as tx:
                lit_rows = tx.rows("literature")
                new_ids: list[str] = []
                for entry in prepared:
                    existing, hit_key = D.find_existing_literature(
                        lit_rows, entry["title"], entry["year"], entry["doi"]
                    )
                    if existing is not None:
                        # 同一篇被另一个请求（或另一个 A 实例）先登记了：只追加来源，不新建行
                        src = set(existing.get("source_request_ids") or [])
                        src.add(req["request_id"])
                        existing["source_request_ids"] = sorted(src)
                        tx.upsert("literature", existing, note=f"dup_by:{hit_key}")
                        result.duplicated += 1
                        new_ids.append(existing["lit_id"])
                        continue

                    lit_id = tx.alloc_id("lit")
                    rel_dir = self.store.library / lit_id
                    rel_dir.mkdir(parents=True, exist_ok=True)

                    dl = entry.get("download") or {}
                    staged = dl.pop("_staged_path", None)
                    rel_path: str | None = None
                    st = dl.get("status")
                    # content_mismatch 的字节照样落盘：它是证据（能看到对方返回了
                    # 什么），只是不允许下游把它当文献抽取。丢掉证据会让"为什么下载不到"
                    # 变成不可查的问题。
                    if staged and Path(staged).exists() and st in ("ok", "content_mismatch"):
                        target = rel_dir / Path(staged).name
                        # 同盘 os.replace 原子；跨盘回退到 move
                        try:
                            shutil.move(str(staged), str(target))
                        except Exception as e:  # 搬文件失败 => 降级为"未下载"，但不丢元数据
                            dl["status"] = "failed"
                            dl["error"] = f"move_failed: {type(e).__name__}: {e}"
                        else:
                            rel_path = f"{lit_id}/{target.name}"
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
                    result.registered += 1

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
                    exhausted = int(fresh.get("attempts") or 0) >= self.max_attempts
                    fresh["last_error"] = "; ".join(search_errors)
                    if exhausted:
                        fresh["done"] = True
                        fresh["outcome"] = "search_failed"
                        fresh["lease_until"] = None
                    else:
                        fresh["done"] = False
                        fresh["outcome"] = None
                        # 退避租约：既让重试可行，又不会在本进程里立刻重打同一个 API
                        fresh["lease_until"] = make_lease(self.retry_backoff_seconds)
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
        finally:
            # staging 目录里的残留下载一并清掉（成功搬走的已经不在里面了）
            shutil.rmtree(staging, ignore_errors=True)

        return result

    def run(self, max_requests: int | None = None) -> dict:
        """处理若干条请求。`max_requests=None` 表示处理到没有待办为止。

        返回的是累加后的 `ARunResult.to_dict()`。三态纪律：`skipped_reason`
        非空表示"这一轮没取到活的原因"（不是错误），此时循环立即停下 ——
        继续空转只会把同一句"队列空了"重复无数遍。
        """
        total = ARunResult()
        n = 0
        while max_requests is None or n < max_requests:
            r = self.run_once()
            # 取任务侧的审计信息先汇总，再判断要不要早退：早退的那一轮
            # （队列空 / 全被别人占着）恰恰是"为什么没干活"最需要被看见的一轮。
            total.queue_pending = r.queue_pending
            total.skipped_lease_active += r.skipped_lease_active
            total.skipped_lease_backoff += r.skipped_lease_backoff
            total.gave_up += r.gave_up
            if r.request_id:
                total.request_id = r.request_id
                total.priority = r.priority
                total.priority_rank = r.priority_rank
                total.submitted_by = r.submitted_by
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
                break
            total.processed += r.processed
            total.registered += r.registered
            total.duplicated += r.duplicated
            total.downloaded += r.downloaded
            total.download_failed += r.download_failed
            total.download_suspect += r.download_suspect
            total.outcome = r.outcome
            n += 1
        return total.to_dict()


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    """`python -m agentflow.agent_a` 的自检：跑通主路径并断言关键不变量。

    ## 为什么这个函数必须存在（它修的是一个静默空成功）

    `scripts/release_check.py` 第 2 项会逐个 `python -m agentflow.agent_<role>` 并看退出码。
    在本次修复之前，`agent_a` 没有 `__main__` 块，于是那条命令输出 0 行、退出码 0
    —— 旧判据会把它记成"自检通过"，而它其实什么都没检查。这正是本项目最忌讳的形态：
    "没做"被读成"通过"（`DEVELOPMENT.md` §10-D5 与附录 C 第 4 条都记着这件事；
    现在 `release_check.item_selftests` 也专门加了 `has_selftest` 判据把它报成 `unknown`）。

    自检覆盖的是主路径与三条降级路径，全部离线、确定性：
    取任务的 I7 优先级、落库（含下载证据）、判重幂等、队列空/全被租/全在退避/全被放弃的
    四态、搜索失败不置 done 且退避租约被遵守（"写了"必须升级成"写了且被读"）、
    下载失败仍然登记。

    退出码：`0` = 全部通过；`1` = 有失败项（退出码是这份自检唯一的机器可读结论）。
    """
    import hashlib
    import shutil
    import tempfile
    from types import SimpleNamespace

    from .fetch import FetchResult

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
            return FetchResult(ok=False, path=None, http_status=500, bytes=0, sha256=None, error="selftest boom")

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
        check("被有效租约占着的行**不会**被抢走（claimed_by 原样保留）",
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
        check("搜索失败：请求**没有**被置 done，且 last_error 留下了原因",
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
        check("搜索失败后的退避租约**被遵守**：再领一次领不到它，attempts 不增",
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


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块（release_check 第 2 项会跑它）
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 控制台编码重配失败无所谓（重定向到文件时就是这种情况），不影响自检结论
        pass
    raise SystemExit(_selftest())
