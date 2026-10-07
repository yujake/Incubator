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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from .. import dedup as D
from .. import interactions as X
from .. import schema as S
from .. import textutil as T
from ..store import Store, StoreError, lease_expired, make_lease
from ..agentspec import AgentBrief, AgentSpec
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

    # ---- 这一次问了谁、问得怎么样（`providers` 那一格的读数）
    #
    # 为什么放在 `ARunResult` 而不是只活在 `search_literature` 的返回值里：
    # 真正去检索的是 `run_once` 这一轮，读数只有它拿得到；动作层再把它汇总
    # （队列里有更早的请求时，一次动作会跑好几轮，逐轮读数各不相同）。
    #: 这一轮真正去问的源名（取自请求行 `providers`）。空 = 第一态（按角色配置）。
    #: 用空列表而不是 `None` 表示"没点名"：这一格是"这一轮问了哪些源"的清单，
    #: "点名了但一个都没接上"由 `sources` 为空加上 `search_errors` 里的理由回答。
    providers_requested: list[str] = field(default_factory=list)
    #: 角色级接线上有哪些源（第一态用它说明"这一次用的是哪些源"）。
    role_providers: list[str] = field(default_factory=list)
    #: 逐源读数（形态照工具面 `search.literature` 的 `sources[]`）。
    #: 只在请求行点名了源的那一态非空 —— 第一态按角色配置查，跨源合并归提交阶段，
    #: 那里没有"逐源三态"这件事，编一份出来就是假读数。
    sources: list[dict] = field(default_factory=list)
    #: 成本读数（形态照工具面的 `cost`）：`provider_calls` 是这一轮向上游发了几次。
    cost: dict = field(default_factory=dict)

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
            "providers_requested": list(self.providers_requested),
            "role_providers": list(self.role_providers),
            "sources": [dict(s) for s in self.sources],
            "cost": dict(self.cost),
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
from ..specs.a import SPEC  # noqa: E402,F401

