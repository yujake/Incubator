"""A 智能体：文献搜索。

职责（需求原文）：接收文献搜索请求清单 → 搜索 → 把文献**下载到本地** → 维护文献表 → 把请求标记完成。

四个刻意的设计选择：

1. **锁只覆盖簿记，不覆盖网络**。搜索与下载可能耗时数十秒；若持锁做这些事，
   B 智能体会被整段时间阻塞。因此流程切成"短事务声明租约 → 无锁做 I/O → 短事务提交"。
   代价是**提交时必须在锁内重做一次判重**（另一个 A 实例可能已抢先登记同一篇），
   这一步不能省。
2. **先落文献行，再置请求完成**（DESIGN.md §2.4）。崩溃时请求仍是未完成，
   重跑靠 `dedup_key` 幂等，不会重复登记。
3. **下载失败不算请求失败**。文献行照常登记（`path=null`），
   因为"我知道有这篇论文但拿不到全文"本身就是有价值的结果；B 会跳过它并计数。
4. **取任务只做排队，不做抢占**（I7）。A 按 `interactions.order_pending_requests`
   给出的顺序取任务，排序键是"优先级 → 租约是否过期 → 提交时间 → request_id"。
   这里有两条**硬约束**：

   - **排序键只有那一份实现**，本模块不另写一套（哪怕只是 `sort(key=...)`）。
     一旦 A 的取任务顺序与提交方（C/D）的派发顺序各持一套判据，
     "high 优先"就会**静默失效** —— 不报错，只是最关键的矛盾永远排在后面。
     这正是 `RuleExtractor` docstring 警告过的"两个模块各持一套判据"。
   - **不抢占**：正在跑的 A 已经付掉了检索与下载的成本，被高优先级请求打断只会让
     两条请求都变慢，还在 staging 里留下一堆半成品；收益小于代价。
     高优先级请求在**下一次** `_claim()` 时自然排到队首。
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
    # 没有这几个字段，I7 的效果**无法从外部观察**：外部只能看到"处理了 1 条"，
    # 看不到它是不是优先级最高的那条，也看不到高优先级的那条为什么没被取走。

    #: 本轮取到的请求代号；`None` 表示本轮没取到任何请求（原因见 `skipped_reason`）。
    request_id: str | None = None
    #: 该请求的优先级，**原样取自行**。这里不做任何"修正"：A 的职责是按优先级取任务，
    #: 不是替提交方决定优先级（那会让"谁提的"这件事在链路上丢失）。
    priority: str | None = None
    #: `interactions.priority_rank(priority)`。单独给出是因为判定"为什么它先被取走"
    #: 靠的是**次序**而不是字符串 —— 直接比较字符串会得到 `"high" < "low"` 这种错结论。
    priority_rank: int | None = None
    #: 提交方（审计线索：这件事是谁提的）。
    submitted_by: str | None = None
    #: 定序时队列里的待办条数。
    queue_pending: int = 0
    #: 因"`claimed_by` 非空且租约**未**过期"而被跳过的条数。
    #: 这是"高优先级就在队里却没被取走"的唯一合法解释，必须能被外部看见 ——
    #: 否则运维只能看到"什么都没做"，无从判断是队列空了还是全被别人占着。
    skipped_lease_active: int = 0

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
        }


@dataclass
class ClaimOutcome:
    """`_claim()` 的结果：取任务这件事**本身**的结果，而不只是"取到的那一行"。

    为什么不让 `_claim()` 只返回 `dict | None`：一个 `None` 会同时表示三件完全不同的
    事，而它们对应的处置完全不同（这正是"三态纪律"要防的形态）：

    - ``pending == 0``                    —— 队列是空的（可以停）
    - ``skipped_lease_active > 0``        —— 有活，但都在别人手里（该等，或换个 A 实例跑）
    - ``gave_up > 0``                     —— 有活，但都超了重试上限（**终局**，别再等）

    压成一个 `None` 的后果不是"少一点信息"，而是**误导运维**：看到
    `skipped_reason="no_pending_request"` 会以为队列空了，而实际上队列里躺着一条
    high 优先级请求在等租约被修好。所以三者必须能被区分，`skipped_reason` 逐个命名。
    """

    #: 取到的请求（已置 claimed_by / lease_until / attempts+=1）；没取到时为 `None`。
    request: dict | None = None
    #: 定序时队列里的待办条数。
    pending: int = 0
    #: 因租约**未**过期而被跳过的条数（"别人正在做"）。
    skipped_lease_active: int = 0
    #: 本轮当场放弃（attempts 用尽）的条数。
    gave_up: int = 0
    #: 没取到请求时的原因，取值见 `_claim` 的 docstring；取到时为 `None`。
    skipped_reason: str | None = None

    @property
    def claimed(self) -> bool:
        """是否取到了请求。**不要**用 `bool(self.request)` 代替：那会在别处再造一个判据。"""
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
        # 搜索失败后的退避租约：既允许重试，又避免在同一进程里立刻重打同一个 API
        self.retry_backoff_seconds = int(self.cfg.get("retry_backoff_seconds", 60))

    # ------------------------------------------------------------------ 取任务
    def _claim(self) -> ClaimOutcome:
        """在锁内按 **I7 优先级**领取一条待办请求：置 claimed_by / lease_until / attempts+=1。

        排序键**全权**由 `interactions.order_pending_requests` 决定
        （优先级 → 租约是否过期 → 提交时间 → request_id）。这里**不另写排序**：
        见模块 docstring 第 4 条 —— 两套判据必然漂移，而漂移的表现是
        "高优先级静默沉底"，不会报错。

        **A 只排队，不抢占。** 已经有一条请求在跑时，即使此刻来了更高的优先级，
        也要等它跑完 —— 正在跑的那条已经付掉了检索与下载的成本，打断它会让
        **两条**都变慢，还会在 staging 里留下半成品。高优先级请求在下一轮
        `_claim()` 时自然排到队首，这一点由 `order_pending_requests` 保证。

        保留的租约语义：`claimed_by` 非空**且**租约未过期的请求不得被取走
        （哪怕它是 high）；租约**已过期**的可以抢（那是之前有人拿到却没做完的活，
        收回沉没成本比重新开一条更便宜）。租约判据用 `store.lease_expired`，
        与 `order_pending_requests` 内部用的是同一个函数，不在这里自己比较时间字符串。

        实测提醒（别被"过期优先"的措辞误导）：`order_pending_requests` 把
        "租约为空（无人持有）"与"租约已过期"放进**同一个排序桶**，两者都排在
        "租约仍在走"的前面。因此过期租约**不会**插全新请求的队，但也不会被饿死
        （同桶内按 FIFO 轮到）。若有人按"过期优先"去改判据，会把 A 自己的
        退避租约（`retry_backoff_seconds`）一起改坏 —— 那条租约正是靠这个分桶生效的。

        没取到请求时给出的 `skipped_reason`（**三态，不许压成一个 None**）：

        - ``"no_pending_request"``         —— 队列里没有未完成的请求（真没事可做）
        - ``"pending_requests_all_leased"`` —— 有未完成的，但全被别人持着有效租约
        - ``"no_claimable_request"``        —— 有未完成的，但剩下的全在本次被放弃
          （attempts 用尽 ⇒ done=true），或既非空又非"全被租"的其它情况
        """
        with self.store.tx("search_requests", actor=self.actor, note="claim") as tx:
            rows = tx.rows("search_requests")
            # ⚠️ 只拿 order_pending_requests 的输出，不自己再造一份顺序。
            ordered = X.order_pending_requests(rows)
            pending = len(ordered)
            skipped_lease_active = 0
            gave_up = 0
            for r in ordered:
                # 先判租约，再判 attempts：一条正被别人跑着的请求不该由我们来"放弃"，
                # 否则会把别人手上的活单方面判死（两个人各有各的 attempts 计数）。
                if r.get("claimed_by") and not lease_expired(r.get("lease_until")):
                    skipped_lease_active += 1
                    continue  # 别人正在做，且租约未过期
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
                    order=[x.get("request_id") for x in ordered],
                )
                return ClaimOutcome(
                    request=dict(r),
                    pending=pending,
                    skipped_lease_active=skipped_lease_active,
                    gave_up=gave_up,
                )
            if pending == 0:
                reason = "no_pending_request"
            elif skipped_lease_active == pending:
                reason = "pending_requests_all_leased"
            else:
                reason = "no_claimable_request"
            return ClaimOutcome(
                pending=pending,
                skipped_lease_active=skipped_lease_active,
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

        返回 DownloadResult 形状的 dict；不抛异常 —— 下载失败是**预期内的常态**。
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
        # ⚠️ "下载成功"不等于"拿到的是要的东西"。真实环境下 URL 以 .pdf 结尾却返回
        # text/html 是常见的（落地页、cookie 同意页、代理/反爬拦截页）—— 实测就碰到
        # 一个 12.4 MB 的 HTML 被当成论文存下来。下载器已经把它标成
        # `content_type_mismatch`，但如果这里仍记 status="ok"，下游 B 会照常去抽取
        # 那个 HTML，把网页导航文字当成"概念"。所以必须在这里把状态**降级**，
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
        result = ARunResult()
        claim = self._claim()
        # 取任务侧的审计信息**先落进结果**，再决定要不要早退 —— 否则
        # "有 high 在队里但全被租约占着"这类信息会随着 skipped_reason 一起丢掉，
        # 外部就只剩一个"什么都没做"。
        result.queue_pending = claim.pending
        result.skipped_lease_active = claim.skipped_lease_active
        result.gave_up = claim.gave_up
        req = claim.request
        if req is None:
            result.skipped_reason = claim.skipped_reason
            return result
        # I7：把"本轮取了哪条、它是什么优先级"暴露出来 —— 这是从外部**唯一**能
        # 观察到优先级真的生效的地方（文献表里看不出来）。
        result.request_id = req.get("request_id")
        result.priority = req.get("priority")
        result.priority_rank = X.priority_rank(req.get("priority"))
        result.submitted_by = req.get("submitted_by")

        candidates, search_errors = self._search(req)

        staging = Path(tempfile.mkdtemp(prefix="abflow-stage-", dir=str(self.store.library)))
        try:
            # ---- 阶段 1（无锁）：先把候选规范化 + 下载到 staging。
            # 这里**不**分配 ID、不写表，因此失败/崩溃都不会留下半成品。
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
                    # content_mismatch 的字节**照样落盘**：它是证据（能看到对方返回了
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
                    # upsert 已经把行放进去了；这里**不能**再 append，否则会出现重复 ID。
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
                    # DESIGN.md §5.3：**搜索失败不等于这条请求结束**。
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
                    # 搜索正常执行但零命中 —— 这是一个**有效结论**，不是错误
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
                # 注意：这里**不**再碰 `result.gave_up`。放弃（gave_up）只发生在
                # `_claim()` 里 —— 请求被放弃后根本不会被取出来跑，所以"跑到提交阶段
                # 才发现 outcome=gave_up"是一个不可能发生的分支。原来那行
                # `result.gave_up = 1 if fresh.get("outcome") == "gave_up" else 0`
                # 因此恒为 0，把 `_claim()` 里真正数到的放弃条数**覆盖成 0**：
                # 字段存在、名字合理、永远是 0 —— 典型的"看起来在统计、实际恒为假"。
        finally:
            # staging 目录里的残留下载一并清掉（成功搬走的已经不在里面了）
            shutil.rmtree(staging, ignore_errors=True)

        return result

    def run(self, max_requests: int | None = None) -> dict:
        """处理若干条请求。`max_requests=None` 表示处理到没有待办为止。"""
        total = ARunResult()
        n = 0
        while max_requests is None or n < max_requests:
            r = self.run_once()
            # 取任务侧的审计信息先汇总，**再**判断要不要早退：早退的那一轮
            # （队列空 / 全被别人占着）恰恰是"为什么没干活"最需要被看见的一轮。
            total.queue_pending = r.queue_pending
            total.skipped_lease_active += r.skipped_lease_active
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
