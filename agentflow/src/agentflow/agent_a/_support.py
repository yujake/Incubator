"""A 智能体：文献搜索（`agent_a` 包内部件共用的小工具，口径与包入口同一份）。

职责（需求原文）：接收文献搜索请求清单 → 搜索 → 把文献下载到本地 → 维护文献表 → 把请求标记完成。
四个刻意的设计选择见 `agent_a/__init__.py` 的模块 docstring（此处不复制一份会漂的副本）。

本文件里唯一需要单独交代的：这里的东西都是「包内部件」——不进 import 面、不构成权限面，
所以改动它不需要动 `specs/a.py`；反过来说，任何"A 的动作"都不许写在这里（动作在
`agent_a/<动作>.py`，由 `capabilities.assert_capabilities()` 在导入期核对公开方法是否存在）。
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
    #: 两态都有：点名了源的那一态来自 `MultiProvider` 的逐源统计，没点名的
    #: 第一态来自 `_search_along_wiring` 的逐源读数 —— 第一态不报的话，
    #: "某个源被限流"与"接线上的源全都 0 命中"在动作读数上同形（2026-10-20
    #: 审计 A 的缺陷 6）。"这一次有没有点名源"仍由 `providers_requested` 回答
    #: （`None` = 没点名），不许用 `sources` 是否为空去推断。
    sources: list[dict] = field(default_factory=list)
    #: 成本读数（形态照工具面的 `cost`）：`provider_calls` 是这一轮向上游发了几次。
    cost: dict = field(default_factory=dict)

    # ---- 委托报告（业主 2026-10-20 第 3 条：报告是交付物，不是可选）
    #
    # 为什么这三格在 `ARunResult` 上而不是只写文件：调用方（主控 / D / H）读的是动作的
    # 返回，而不是去猜盘上有哪个文件。「报告在哪、里面两块各几条」必须随这次动作一起交回 ——
    # 否则"报告没写"与"报告写了但没被看到"在读数上同形。
    #: 报告落点（`reports/lit-<request_id>.md` 的绝对路径）；空串 = 没写（理由见 `report_error`）。
    report_path: str = ""
    #: 报告"已入库"那一块的条数。
    report_admitted: int = 0
    #: 报告"未入库"那一块的条数（含理由）。
    report_not_admitted: int = 0
    #: 报告写失败的原因（空串 = 没失败）。文献已经落库，报告失败不该把它判成失败。
    report_error: str = ""

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
            "report_path": self.report_path,
            "report_admitted": self.report_admitted,
            "report_not_admitted": self.report_not_admitted,
            "report_error": self.report_error,
        }
@dataclass
class ClaimOutcome:
    """`_claim()` 的结果：取任务这件事本身的结果，而不只是"取到的那一行"。

    为什么不让 `_claim()` 只返回 `dict | None`：一个 `None` 会同时表示几件处置完全不同的事
    （三态纪律要防的形态）：``pending == 0``（队列空，可以停）/ ``skipped_lease_active > 0``
    （有活但在别人手里）/ ``skipped_lease_backoff > 0``（有活但在我们自己的退避租约里，
    处置是"什么都别做，到点自然重试"）/ ``gave_up > 0``（都超了重试上限，终局）。
    压成一个 `None` 的后果是误导运维：看到 `skipped_reason="no_pending_request"` 会以为队列空了，
    而队列里其实躺着一条 high 优先级请求在等租约被修好。所以 `skipped_reason` 逐个命名。
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

