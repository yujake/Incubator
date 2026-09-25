"""数据模型与校验。

设计要点：
- 需求给定的字段一律保留原名与语义；本模块只做"结构化 + 约束"。
- 所有 ID 是 **4 位十进制字符串**（"0000"…"9999"），不用 int，避免前导零在序列化时丢失。
- 数组字段（related_concepts / concept_ids / source_request_ids）在**写入前**统一走
  `sorted_unique()`，把"保持升序、去重"从"调用方记得做"变成"结构上不可能做错"。
- 时间戳统一 ISO-8601 带时区，由 `now_iso()` 产生，保证同库内可比。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

SCHEMA_VERSION = 1

# ---------------------------------------------------------------- 枚举 / 受控词表

#: 搜索模式。对应需求里的 广泛 / 专题 / 精确。
SEARCH_MODES = ("broad", "topical", "precise")

#: 任务优先级（I7）。A 的检索产能是稀缺资源，必须能排序；
#: 只做**排队**，不做抢占（抢占会打断正在跑的 A，代价大于收益）。
PRIORITIES = ("high", "medium", "low")

#: 优先级的可比较次序。数字越小越先被取走。
#: 之所以集中定义在这里而不是散落在各智能体里：一旦 A 的取任务顺序与
#: D 的派发顺序用了两套口径，"high 优先"就会静默失效 —— 而它不会报错。
PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

#: 各提交方的默认优先级（DESIGN-INTERACTIONS.md §1 I7 的表）。
#: 未登记的提交方一律落到 "low" —— 宁可让陌生来源排在后面，也不要让它插队。
#:
#: ⚠️ **本框架自己的角色必须显式登记**，不能靠"未登记 ⇒ low"这条兜底。
#: 兜底的语义是"**我不认识这个来源**，所以不让它插队"；而 E/F/G/H 我们是认识的。
#: 把两者混为一谈会造成一个静默的错觉：F 提交的攻坚检索需求读到 `low`，
#: 看上去像"框架决定它不重要"，实际是"框架没登记它"。
SUBMITTER_DEFAULT_PRIORITY: dict[str, str] = {
    "agent-D:contradiction": "high",
    "human": "high",
    "agent-D": "medium",
    "agent-C": "medium",
    # F 的检索需求来自"多轮攻坚"。**登记为 low 是一个刻意的决定，不是兜底**：
    # 设计基线（DESIGN-INTERACTIONS.md §1 I7 的表）只为"矛盾"(high)、
    # "D/C 的缺口"(medium)、"B 的补定义"(low)、"人"(high) 给过依据；
    # 对 F 没有任何证据说明它的需求比 C 的缺口更急。在没有依据时**保守**：
    # 排在后面比让它插队安全，而且这个"low"是**写下来的**，不是"没登记所以碰巧低"。
    "agent-F": "low",
    # B 的补定义可以在空闲时做。
    "agent-B": "low",
    # E 做实验、G 写稿、H 审校 —— 它们**本来就不该**直接提交检索请求。
    # 登记成 low 而不是靠兜底，是为了让"它们提交了"这件事是一个**显式**事实：
    # 真出现了，就是有人越界或有人手动代提交，值得看一眼。
    "agent-E": "low",
    "agent-G": "low",
    "agent-H": "low",
    "unknown": "low",
}

#: GB/T 7714 文献类型标识码（参考论文参考文献的标注方法）。
LIT_TYPES = ("J", "M", "C", "D", "R", "S", "P", "N", "EB", "Z")

#: 关系/概念的复核状态。suspect 是"几乎相同"判定的中间态，保留可审计性。
RELATION_STATUS = ("active", "suspect", "rejected")

#: 一次搜索请求的终局类型。它回答的是"这一行是**怎么结束**的"，
#: 而不是"有没有出错" —— 二者必须分开，否则"搜索了但没有结果"会被当成故障，
#: 而"所有 provider 都失败"又会被当成正常完成。
#:   ok            —— 至少登记了一篇文献
#:   no_results    —— 搜索正常执行但确实没有命中（这是一个**有效结论**）
#:   search_failed —— 所有 provider 都失败，且已用尽重试
#:   gave_up       —— 超过最大尝试次数被放弃
SEARCH_OUTCOMES = ("ok", "no_results", "search_failed", "gave_up")

#: `literature.download.status` 的受控词表。
#:
#: 为什么必须做成受控词表而不是随手写字符串：AgentB 是靠
#: `status == "content_mismatch"` 来决定"**不要**抽取这个文件"的。一旦有人把
#: 它拼成 `content-mismatch` / `contentMismatch`，比较就会静默失败 —— B 会照常
#: 去抽取一个 HTML 落地页，把网页文字当成"概念"。**这正是缺陷 #8 的复发路径**，
#: 而它不会报任何错。把它纳入 schema 校验，就让拼错在写入时立刻炸出来。
#:   ok                —— 下全了，且内容类型与预期相符
#:   content_mismatch  —— 下全了，但内容类型不是想要的（如 .pdf 链接返回 HTML）
#:   failed            —— 下载失败（网络/HTTP/搬文件失败）
#:   skipped           —— 未尝试下载（无 pdf_url / 关闭下载 / 达到单请求上限）
DOWNLOAD_STATUSES = ("ok", "content_mismatch", "failed", "skipped")

_ID_RE = re.compile(r"^\d{4}$")


def now_iso() -> str:
    """返回带本地时区偏移的 ISO-8601 时间戳（秒级）。"""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def is_valid_id(value: Any) -> bool:
    """ID 必须是 4 位十进制字符串。"""
    return isinstance(value, str) and bool(_ID_RE.match(value))


def require_id(value: Any, what: str = "id") -> str:
    if not is_valid_id(value):
        raise ValueError(f"{what} 必须是 4 位十进制字符串，收到 {value!r}")
    return value


def sorted_unique(values: Iterable[Any]) -> list:
    """升序去重。用于所有"要求升序"的数组字段。

    注意：元素可能是 str（ID）或 int，故用 `sorted(set(...))`；
    set 会丢失顺序但也顺带保证去重，随后 sorted 恢复升序。
    """
    return sorted(set(values))


# ---------------------------------------------------------------- 页码范围


@dataclass(frozen=True)
class PageRange:
    """页码范围。

    `start`/`end` 是 1-based 闭区间整数，供程序比较与定位；
    `label` 保留原始书写形态（如 "pp. 45-46"），供人阅读与引用。
    未知页码时用 start=end=None —— 显式表达"不知道"，而不是编一个 0。
    """

    start: int | None = None
    end: int | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.start is not None and self.start < 1:
            raise ValueError(f"页码必须 >= 1，收到 start={self.start}")
        if self.end is not None and self.end < 1:
            raise ValueError(f"页码必须 >= 1，收到 end={self.end}")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(f"start({self.start}) 不能大于 end({self.end})")

    @property
    def known(self) -> bool:
        return self.start is not None and self.end is not None

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict | None) -> "PageRange":
        d = d or {}
        return cls(start=d.get("start"), end=d.get("end"), label=d.get("label", "") or "")


# ---------------------------------------------------------------- 各表行对象


@dataclass
class SearchRequest:
    """文献搜索请求清单的一行。

    需求字段：timestamp / topic / mode / content_description / done
    扩展字段见 DESIGN.md §0.2 —— 没有它们就无法安全并发、也无法验证"完成"是否真产出。
    """

    request_id: str
    timestamp: str
    topic: str
    mode: Literal["broad", "topical", "precise"]
    content_description: str = ""
    done: bool = False
    # --- 扩展
    submitted_by: str = "unknown"
    claimed_by: str | None = None
    lease_until: str | None = None
    attempts: int = 0
    result_lit_ids: list[str] = field(default_factory=list)
    last_error: str | None = None
    #: 终局类型；见 `SEARCH_OUTCOMES`。未结束时为 None。
    outcome: str | None = None
    #: 优先级（I7）。A 按 `PRIORITY_RANK` 升序取任务，同级 FIFO。
    priority: str = "medium"
    #: 该请求是**为哪个研究问题**服务的（I2 矛盾闭环 / 3.2 证据就绪判据都要它）。
    #: 空串表示"不是由某个问题驱动的"（例如人在 CLI 上手敲的）。
    for_question_id: str | None = None
    #: 提交来源的自由文本说明（人可读；机器判定只看 `submitted_by`）。
    submit_note: str = ""

    def validate(self) -> None:
        if not self.request_id:
            raise ValueError("request_id 不能为空")
        if self.mode not in SEARCH_MODES:
            raise ValueError(f"mode 必须是 {SEARCH_MODES} 之一，收到 {self.mode!r}")
        if not self.topic.strip():
            raise ValueError("topic 不能为空")
        if self.priority not in PRIORITIES:
            raise ValueError(
                f"priority 必须是 {PRIORITIES} 之一，收到 {self.priority!r}。"
                "A 靠它排序取任务，拼错会让高优先级请求静默沉底。"
            )
        if self.for_question_id is not None:
            require_id(self.for_question_id, "for_question_id")
        # 精确模式必须给出内容描述，否则无法构造有效查询（DESIGN.md §1.1）
        if self.mode == "precise" and not self.content_description.strip():
            raise ValueError("precise 模式必须提供 content_description")
        if not isinstance(self.done, bool):
            raise ValueError("done 必须是 bool")
        for i in self.result_lit_ids:
            require_id(i, "result_lit_ids[]")
        if self.outcome is not None and self.outcome not in SEARCH_OUTCOMES:
            raise ValueError(f"outcome 必须是 {SEARCH_OUTCOMES} 之一或 None，收到 {self.outcome!r}")
        # done 的语义：必须能说清"是怎么结束的"。
        # 这里**不强制** outcome 必填（历史数据与测试夹具可能只有 result_lit_ids /
        # last_error），但明确拒绝"三样都没有"的情况 —— 那正是曾经的 bug：
        # 搜索正常返回空结果时既不写 lit_ids 也不写 error，于是无法与"没跑过"区分。
        if self.done:
            if self.outcome is None and not (self.result_lit_ids or self.last_error):
                raise ValueError(
                    "done=true 时必须给出 outcome（ok/no_results/search_failed/gave_up），"
                    "或至少给出 result_lit_ids / last_error"
                )
            if self.outcome == "ok" and not self.result_lit_ids:
                raise ValueError("outcome=ok 时 result_lit_ids 不能为空")
            if self.outcome in ("search_failed", "gave_up") and not self.last_error:
                raise ValueError(f"outcome={self.outcome} 时必须记录 last_error")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Literature:
    """文献表的一行。需求字段：文献代号/名称/类型/简述/地址/处理情况。"""

    lit_id: str
    title: str
    type: str
    summary: str
    path: str | None
    processed: bool = False
    # --- 扩展
    source_request_ids: list[str] = field(default_factory=list)
    dedup_key: str = ""
    doi: str | None = None
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    language: str | None = None
    added_at: str = ""
    download: dict = field(default_factory=dict)
    # --- 扩展：B 的并发控制（与 requests 表同样的租约思路）
    claimed_by: str | None = None
    lease_until: str | None = None
    mine_attempts: int = 0
    last_mine_error: str | None = None

    def validate(self) -> None:
        require_id(self.lit_id, "lit_id")
        if not self.title.strip():
            raise ValueError("title 不能为空")
        if self.type not in LIT_TYPES:
            raise ValueError(f"type 必须是 {LIT_TYPES} 之一，收到 {self.type!r}")
        if not isinstance(self.processed, bool):
            raise ValueError("processed 必须是 bool")
        # path 允许为 None（下载失败），但不能是绝对路径或越出 library/ 的相对路径
        if self.path is not None:
            p = self.path.replace("\\", "/")
            if p.startswith("/") or ":" in p or ".." in p.split("/"):
                raise ValueError(f"path 必须是 library/ 下的相对路径，收到 {self.path!r}")
        for i in self.source_request_ids:
            if not i:
                raise ValueError("source_request_ids 含空值")
        # download.status 必须在受控词表内 —— 见 DOWNLOAD_STATUSES 的说明：
        # 下游 B 靠这个字符串决定是否跳过，拼错会静默放行非论文内容。
        if self.download:
            status = self.download.get("status")
            if status is not None and status not in DOWNLOAD_STATUSES:
                raise ValueError(
                    f"download.status 必须是 {DOWNLOAD_STATUSES} 之一，收到 {status!r}。"
                    "注意：agent_b 依赖 'content_mismatch' 这个精确字符串来跳过非论文内容，"
                    "拼错会让缺陷 #8 静默复发。"
                )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Concept:
    """概念表的一行。需求字段：概念代号/名称/定义/相关概念代号。"""

    concept_id: str
    name: str
    definition: str
    related_concepts: list[str] = field(default_factory=list)
    # --- 扩展
    normalized_name: str = ""
    aliases: list[str] = field(default_factory=list)
    definition_source_lit_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    #: 被合并到哪个概念（I5）。非空表示"这一行是冗余节点，已被 survivor 吸收"。
    #:
    #: 为什么不直接删行：删掉就**无法审计**"当初为什么认为它们是同一个"。
    #: 保留 + 指向 survivor，既让下游能过滤（`merged_into is None` 才是活节点），
    #: 又留下了合并决策的完整轨迹。
    merged_into: str | None = None
    #: 合并理由（由 B 给出，人可读）。`merged_into` 非空时它**必须**非空 ——
    #: "合并了但说不出为什么"是不可审计的，与"静默丢弃"同类。
    merge_reason: str = ""
    merged_at: str = ""

    def validate(self) -> None:
        require_id(self.concept_id, "concept_id")
        if not self.name.strip():
            raise ValueError("name 不能为空")
        if self.merged_into is not None:
            require_id(self.merged_into, "merged_into")
            if self.merged_into == self.concept_id:
                raise ValueError("merged_into 不能指向自身")
            if not self.merge_reason.strip():
                raise ValueError(
                    f"concept {self.concept_id} 标了 merged_into={self.merged_into} 却没有 merge_reason："
                    "合并决定必须留下理由（合并决定权在 B，且必须可审计）"
                )
        # 需求明确：升序、且不含自身
        if self.related_concepts != sorted(set(self.related_concepts)):
            raise ValueError(f"related_concepts 必须升序去重：{self.related_concepts}")
        if self.concept_id in self.related_concepts:
            raise ValueError("related_concepts 不能包含自身")
        for r in self.related_concepts:
            require_id(r, "related_concepts[]")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Relation:
    """关系表的一行。需求字段：概念代号组/关系描述/文献代号/页码范围。"""

    relation_id: str
    concept_ids: list[str]
    description: str
    lit_id: str
    page_range: PageRange
    # --- 扩展
    quote: str = ""
    quote_normalized: str = ""
    quote_verified: bool | None = None
    statement: str = ""
    concept_group_key: str = ""
    dedup_key: str = ""
    status: str = "active"
    duplicate_of: str | None = None
    created_at: str = ""
    #: **本条关系还引用了哪些文献**（除主引文 `lit_id` 之外）。
    #:
    #: 为什么必须补这个字段：上一版"一条关系只能引一篇文献"是明确记录的缺口
    #: （`10-...md` §13.1 P0-4 标 ⚠️ 未完成）。数学上一条关系常常由两篇文献
    #: 共同支持（例如"K(m) 与 S̃_m 同谱"需要一篇给 K(m) 的谱、另一篇给 S̃_m 的谱）。
    #: 只有 `lit_id` 时，第二篇支持文献**无处可写**，于是依赖集无法闭合 ——
    #: 而依赖集不闭合正是"把引用的定理当成自己的定理"的技术根源（FC-23）。
    supporting_lit_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        require_id(self.relation_id, "relation_id")
        require_id(self.lit_id, "lit_id")
        if len(self.concept_ids) < 2:
            raise ValueError("概念代号组至少要有 2 个概念")
        if self.concept_ids != sorted(set(self.concept_ids)):
            raise ValueError(f"concept_ids 必须升序去重：{self.concept_ids}")
        for c in self.concept_ids:
            require_id(c, "concept_ids[]")
        for lid in self.supporting_lit_ids:
            require_id(lid, "supporting_lit_ids[]")
        if self.lit_id in self.supporting_lit_ids:
            raise ValueError("supporting_lit_ids 不应包含主引文 lit_id（重复登记会让依赖计数虚高）")
        if not self.description.strip():
            raise ValueError("description 不能为空")
        if self.status not in RELATION_STATUS:
            raise ValueError(f"status 必须是 {RELATION_STATUS} 之一，收到 {self.status!r}")
        if self.quote_verified is not None and not isinstance(self.quote_verified, bool):
            raise ValueError("quote_verified 必须是 bool 或 None")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_range"] = self.page_range.to_dict()
        return d


# ---------------------------------------------------------------- C/D 新增：受控词表

#: C 的分析报告类型。与需求里的四类需求一一对应。
REPORT_KINDS = ("hottest", "paths", "cold", "gaps")

#: D 的研究问题状态机（DESIGN-TOOLS.md §4.1）：
#:   open            —— 刚提取出来，尚未评估证据
#:   needs_evidence  —— 已判定证据不足，且已向 A 提交查询请求（在等）
#:   researching     —— 证据就绪，正在研究
#:   answered        —— 已给出结论
#:   dropped         —— 评估后判定不值得研究（要写理由，不许静默丢弃）
QUESTION_STATUSES = ("open", "needs_evidence", "researching", "answered", "dropped")

#: 矛盾闭环（I2）的裁决词表。**四态而非三态**，因为 "persistent" 与
#: "unresolved" 的下游动作完全不同：前者要人来看并停止追问，后者还要再来一轮。
#: 把它们合并成一个词，就等于把"该停了"和"继续"混为一谈。
CONTRADICTION_VERDICTS = ("resolved", "unresolved", "new_contradiction", "persistent")

#: 研究问题的驱动类型（I2）。见 `ResearchQuestion.kind`。
QUESTION_KINDS = ("gap", "contradiction")

#: 定向重抽取（I4）的原因词表。受控词表而非自由文本，理由同 DOWNLOAD_STATUSES：
#: B 靠这个字符串决定**该怎么重做**，拼错会静默走错分支。
REPROCESS_REASONS = (
    "quote_unverifiable",  # 引文逐字校验失败 → 回全文找等价表述
    "low_information",  # 描述过短/信息量低 → 回该页附近抽更完整的陈述
    "need_context",  # D 要该关系所在段落的完整语境
    "structural_duplicate",  # I5：C 提出结构重复，请 B 复核是否合并
)

#: 重抽取请求的生命周期。
#:   pending    —— 已提交，B 还没处理
#:   done       —— B 处理完（**结果写进 result，可能仍是"没找到"**）
#:   rejected   —— 被闸门拒绝（超限 / 目标不存在 / 原因非法）
REPROCESS_STATUSES = ("pending", "done", "rejected")


@dataclass
class ReprocessRequest:
    """定向重抽取请求（DESIGN-INTERACTIONS.md §1 I4）。

    为什么不复用 `search_requests`：语义根本不同 —— 搜索请求是"去外面找新东西"，
    重抽取是"把已有的东西重新看一遍"。混在一张表里会让"A 的产能统计"
    把不消耗网络的本地工作也算进去，配额就失去意义。

    ⚠️ 它**不是**"把 `processed` 置回 false"。那会触发全量重抽，是幂等陷阱。
    必须带**目标**（`relation_ids`），B 只在该目标上工作。
    """

    reprocess_id: str  # "p-NNNN"
    timestamp: str
    reason: str
    submitted_by: str = "unknown"
    #: 目标关系。至少一条 —— 空目标的"重抽取"会退化成全量重抽。
    relation_ids: list[str] = field(default_factory=list)
    #: 目标文献（可选；`reason="need_context"` 时由 D 指定更精确的落点）。
    lit_id: str | None = None
    #: 提交方的补充说明（人可读）。
    detail: str = ""
    status: str = "pending"
    #: 处理结果。三态纪律：`status="done"` 但 `result="not_found"` 是**有效结论**，
    #: 与"没处理"（`status="pending"`）必须能区分。
    result: str | None = None
    result_note: str = ""
    #: B 处理时被改动的关系（用于 I4 的"只改动目标关系"验收）。
    touched_relation_ids: list[str] = field(default_factory=list)
    claimed_by: str | None = None
    lease_until: str | None = None
    attempts: int = 0
    last_error: str | None = None

    def validate(self) -> None:
        if not self.reprocess_id:
            raise ValueError("reprocess_id 不能为空")
        if self.reason not in REPROCESS_REASONS:
            raise ValueError(f"reason 必须是 {REPROCESS_REASONS} 之一，收到 {self.reason!r}")
        if self.status not in REPROCESS_STATUSES:
            raise ValueError(f"status 必须是 {REPROCESS_STATUSES} 之一，收到 {self.status!r}")
        if not self.relation_ids:
            raise ValueError(
                "relation_ids 不能为空 —— 无目标的重抽取会退化为全量重抽（I4 的幂等陷阱）"
            )
        if self.relation_ids != sorted(set(self.relation_ids)):
            raise ValueError(f"relation_ids 必须升序去重：{self.relation_ids}")
        for rid in self.relation_ids:
            require_id(rid, "relation_ids[]")
        if self.lit_id is not None:
            require_id(self.lit_id, "lit_id")
        if self.status == "done" and self.result is None:
            raise ValueError(
                "status=done 时必须给出 result（如 found / not_found / improved / unchanged），"
                "否则无法与'没做'区分"
            )
        if self.result_note is None:
            raise ValueError("result_note 不能是 None（用空串表示没写说明）")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchQuestion:
    """D 的工作台一行（DESIGN-TOOLS.md §2.1）。"""

    question_id: str
    question: str
    origin: str = ""  # 溯源："C:paths:0000->0003"
    related_concept_ids: list[str] = field(default_factory=list)
    related_relation_ids: list[str] = field(default_factory=list)
    status: str = "open"
    priority: str = "medium"
    evidence_lit_ids: list[str] = field(default_factory=list)
    #: 已提交给 A 的查询请求。**这是"D 继续思考"能自动接上的唯一依据**：
    #: 没有它就无法判断"新来的文献是不是我等的那个"。
    waiting_request_ids: list[str] = field(default_factory=list)
    gap_reason: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    #: 问题类型（I2）。`"gap"` = 缺口驱动；`"contradiction"` = 矛盾驱动。
    #:
    #: 为什么必须显式区分而不是靠 origin 字符串前缀：两者的**收敛条件不同**
    #: （缺口靠"证据相关即为就绪"，矛盾靠"裁决 resolved/persistent"），
    #: 且矛盾有**轮数上限**。靠解析 origin 的字符串格式来决定生命周期，
    #: 会在 origin 格式一变时静默失效。
    kind: str = "gap"
    #: 矛盾闭环专用字段（kind="contradiction" 时有意义）。
    contradiction_relation_ids: list[str] = field(default_factory=list)
    contradiction_rounds: int = 0
    #: 最近一次裁决（见 `CONTRADICTION_VERDICTS`）。None = 还没裁决过。
    contradiction_verdict: str | None = None
    #: 本轮矛盾闭环为该问题提交过的检索请求（与 waiting_request_ids 分开记，
    #: 因为 `max_contradiction_requests` 的全局配额需要按"矛盾驱动"来统计）。
    contradiction_request_ids: list[str] = field(default_factory=list)
    #: **保序**的关系代号链（FC-05）。与 `related_relation_ids` 是一对：
    #: 后者是**集合**（引用了哪些知识，升序去重、可比较、可判重），
    #: 本字段是**序列**（按什么顺序走的 —— 推理路径本身）。
    #:
    #: 为什么必须成对存在：上一版只有集合字段，于是"跳序"（A→C→B 与 A→B→C 的区别）
    #: 被 `sorted(set(...))` 静默吃掉，只能从 `origin` 字符串反解。
    #: **顺序是数学论证的一部分**，它不是"同一集合的另一种写法"。
    relation_chain: list[str] = field(default_factory=list)

    def validate(self) -> None:
        require_id(self.question_id, "question_id")
        if not self.question.strip():
            raise ValueError("question 不能为空")
        if self.status not in QUESTION_STATUSES:
            raise ValueError(f"status 必须是 {QUESTION_STATUSES} 之一，收到 {self.status!r}")
        if self.priority not in PRIORITIES:
            raise ValueError(f"priority 必须是 {PRIORITIES} 之一，收到 {self.priority!r}")
        if self.kind not in QUESTION_KINDS:
            raise ValueError(f"kind 必须是 {QUESTION_KINDS} 之一，收到 {self.kind!r}")
        if self.contradiction_verdict is not None and self.contradiction_verdict not in CONTRADICTION_VERDICTS:
            raise ValueError(
                f"contradiction_verdict 必须是 {CONTRADICTION_VERDICTS} 之一或 None，"
                f"收到 {self.contradiction_verdict!r}"
            )
        if self.kind == "contradiction":
            if len(self.contradiction_relation_ids) != 2:
                raise ValueError(
                    "kind=contradiction 时 contradiction_relation_ids 必须恰有 2 条"
                    f"（矛盾只可能发生在谈同一件事的两句话之间），收到 {self.contradiction_relation_ids!r}"
                )
            if self.contradiction_relation_ids != sorted(set(self.contradiction_relation_ids)):
                raise ValueError("contradiction_relation_ids 必须升序去重")
        if self.contradiction_rounds < 0:
            raise ValueError("contradiction_rounds 不能为负")
        #: 状态与轮数的一致性：说"已裁决为 persistent"就不能还停在开着的状态里等下一轮
        if self.contradiction_verdict == "persistent" and self.status in ("open", "researching"):
            raise ValueError(
                "contradiction_verdict=persistent 表示**已停止自动追问**，status 不能还是"
                f"{self.status!r}（那会让循环继续把它当活任务）"
            )
        for f in ("related_concept_ids", "related_relation_ids", "evidence_lit_ids"):
            vals = getattr(self, f)
            if vals != sorted(set(vals)):
                raise ValueError(f"{f} 必须升序去重：{vals}")
        for cid in self.related_concept_ids:
            require_id(cid, "related_concept_ids[]")
        for rid in self.related_relation_ids:
            require_id(rid, "related_relation_ids[]")
        # `relation_chain` 是**序列**：只校验元素合法，**不许**排序去重
        # （排序会把推理路径改成另一条路径）。它的"保序"由 round-trip 测试守。
        for rid in self.relation_chain:
            require_id(rid, "relation_chain[]")
        if self.relation_chain and set(self.relation_chain) - set(self.related_relation_ids):
            raise ValueError(
                "relation_chain 含 related_relation_ids 里没有的代号 "
                f"{sorted(set(self.relation_chain) - set(self.related_relation_ids))} —— "
                "链条必须由本问题引用的关系构成（否则链与集合会各自漂移）"
            )
        for lid in self.evidence_lit_ids:
            require_id(lid, "evidence_lit_ids[]")
        # 状态与等待集的一致性：说"在等证据"就必须真的记了在等谁
        if self.status == "needs_evidence" and not self.waiting_request_ids:
            raise ValueError(
                "status=needs_evidence 时必须记录 waiting_request_ids，否则无法判断"
                "「新到的文献是不是我正在等的那批」，D 的循环就接不上"
            )
        if self.status == "dropped" and not self.notes.strip():
            raise ValueError("status=dropped 时必须写 notes 说明为什么放弃（不许静默丢弃）")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisReport:
    """C 的报告登记行（DESIGN-TOOLS.md §2.2）。"""

    report_id: str
    kind: str
    request: str = ""  # 原始需求原文，保留以便审计"报告是否答非所问"
    params: dict = field(default_factory=dict)
    summary: str = ""
    #: 结构化结果。D 靠它溯源到代号链 —— 只存 markdown 的话 D 得解析自然语言。
    payload: dict = field(default_factory=dict)
    markdown_path: str | None = None
    created_at: str = ""
    created_by: str = "agent-C"

    def validate(self) -> None:
        require_id(self.report_id, "report_id")
        if self.kind not in REPORT_KINDS:
            raise ValueError(f"kind 必须是 {REPORT_KINDS} 之一，收到 {self.kind!r}")
        if not self.summary.strip():
            raise ValueError("summary 不能为空（D 的第一入口就是它）")
        if not isinstance(self.payload, dict):
            raise ValueError("payload 必须是对象")
        if self.markdown_path is not None:
            p = self.markdown_path.replace("\\", "/")
            if p.startswith("/") or ":" in p or ".." in p.split("/"):
                raise ValueError(f"markdown_path 必须是相对路径，收到 {self.markdown_path!r}")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- E/F/G/H 新增：受控词表

#: 实验方法（E）。
#:   numeric            —— 浮点数值计算（采样、BFS、特征值）
#:   symbolic           —— 符号计算（精确代数）
#:   exhaustive_search  —— 在有限范围内穷举
#:   formal             —— 交给证明检查器（Lean/Coq/…）核验
EXPERIMENT_METHODS = ("numeric", "symbolic", "exhaustive_search", "formal")

#: **证据等级**（FC-22 的落地核心）。
#:
#:   proof       —— 由形式化检查器核验过的证明（**只有 `method="formal"` 才可能拿到**）
#:   cross_check —— 数值/穷举的交叉验证。**它不是证明**，且在任何报告里都必须
#:                  自动附加"不构成证明"的字样。
#:   heuristic   —— 启发式观察（例如"看起来像"），证据力最弱。
#:
#: 为什么把它做成 schema 字段而不是靠人记得标注：数学里"数值对了"与"证完了"
#: 是天壤之别，而**人一定会忘**。把它变成字段，并让 schema 拒绝
#: "method=numeric 却声称 evidence_kind=proof"，这条错误就在**写入时**炸掉。
EVIDENCE_KINDS = ("proof", "cross_check", "heuristic")

#: 一次实验对被检验命题的结论。
EXPERIMENT_RESULTS = ("supports", "refutes", "inconclusive")

#: **三种否定必须分开**（FC-25）。
#:
#:   disproved           —— 已证否（有可复现的反例）
#:   not_proved          —— 数值/穷举支持，但**没有证明**
#:   not_searched_here   —— 这个实验根本没做
#:   no_local_evidence   —— 做了，但本地拿不到能判定的证据
#:
#: 把"未证明"与"已证否"混起来在数学上是灾难；把"没搜索"与"搜了没有"混起来
#: 在本项目里已经踩过（`cold` 的"完全孤立"就是为此单独归一类）。
NEGATION_KINDS = ("disproved", "not_proved", "not_searched_here", "no_local_evidence")

#: F 的攻坚计划状态。
#:   open / attacking / progress —— 在推进
#:   supported_not_proved       —— 子目标都有数值支持，但没有任何形式化证明
#:   stalled                    —— 预算用尽仍未解决（**不是失败，也不是成功**）
#:   resolved / abandoned       —— 终局
ATTACK_STATUSES = ("open", "attacking", "progress", "supported_not_proved", "stalled", "resolved", "abandoned")

#: 攻坚计划的**终态**：一旦到达就不再推进。
#:
#: ⚠️ 这份名单曾经**有两处实现且已经漂移**：
#: `attack_tools.TERMINAL_STATUSES` 写的是 `("resolved","abandoned","stalled")`，
#: **漏了 `supported_not_proved`** —— 而 `agent_f` 会真的写这个状态（"子目标都有数值支持，
#: 但没有任何形式化证明"）。后果：一个已达该状态的计划被 `pick_next_subgoal` 当成**活计划**
#: 重新拾起，于是终止条件形同虚设（正是 `attack_tools` 那段注释自己警告的形态，
#: 只是它漏列了那个状态）。
#:
#: 现在它是**唯一来源**：`attack_tools.TERMINAL_STATUSES` 就是这个名字的 import。
#: 之所以放进 `schema` 而不是工具层：这是**领域状态**的分类，数据层必须权威。
ATTACK_TERMINAL_STATUSES = ("resolved", "abandoned", "stalled", "supported_not_proved")

#: 攻坚子目标的状态。`supported_not_proved` 单独存在是 FC-22 的直接后果：
#: "有数值支持"绝不能被写成 `closed`。
SUBGOAL_STATUSES = ("todo", "in_progress", "supported_not_proved", "closed", "blocked", "dropped")

#: 子目标可以派给谁。**角色即权限面**，所以这是一个受控词表。
SUBGOAL_OWNERS = ("F", "A", "B", "C", "D", "E", "G")

#: G 的文档类型与状态。
DOC_KINDS = ("reproduction_report", "survey", "paper", "note")
DOC_STATUSES = ("draft", "in_review", "revised", "accepted", "rejected", "unresolved_review")

#: 依赖类型（FC-23）。`external_unavailable` 是**必须存在**的一档：
#: 引用了但拿不到的来源（例如论文里"companion book [6, Thm 6.5]"）
#: 既不是 closed，也不该被含糊地写成 dangling。
DEP_KINDS = ("theorem", "definition", "lemma", "proposition", "dataset", "experiment", "prior_art")
DEP_STATUSES = ("closed", "dangling", "external_unavailable")

#: H 的审校发现类型。**每一类都必须能机械判定**，否则审校会退化成"我感觉"。
#:   unsupported_claim       —— 断言没有引用（可判定：citations 为空）
#:   dangling_dep            —— 依赖悬空 / 外部不可得（可判定：dependencies 表）
#:   quote_mismatch          —— 引文与原文不符（可判定：回到原文比对）
#:   overclaim               —— 把 cross_check 写成 proved（可判定：evidence_kind）
#:   missing_negation_kind   —— 否定型结论没分类（可判定：is_negative + negation_kind）
#:   scope_drift             —— 把假设当公理、结论范围被放大
#:   garbled                 —— 表述错误 / 自相矛盾
#:   inconsistent_number     —— 同一个数字在不同处不一致
FINDING_KINDS = (
    "unsupported_claim", "dangling_dep", "quote_mismatch", "overclaim",
    "missing_negation_kind", "scope_drift", "garbled", "inconsistent_number",
)

#: 告警分级（FC-13）。
#:
#: 分级规则（**两句话，必须记牢**）：
#:   - "表里已记录的缺陷被重算确认" ⇒ `warning`
#:   - "表里记录与重算事实矛盾（谎报）" ⇒ `error`
#: 若不这样分，红灯会被训练成背景噪音，于是真正的 error 也会被忽略。
FINDING_LEVELS = ("error", "warning", "info")

#: 审校发现的状态。`wontfix` / `disputed` 必须写理由（同 `dropped` 必须写 notes）。
FINDING_STATUSES = ("open", "fixed", "wontfix", "disputed")


@dataclass
class Experiment:
    """E 的一次实验记录（DESIGN-ROLES.md §2.1）。

    ⚠️ **本表最重要的一条规矩**：`method` 是"计算类"（numeric / symbolic /
    exhaustive_search）时，`evidence_kind` **不得**为 `"proof"`。
    这条由 :meth:`validate` 机械执行，不靠人记得。

    为什么必须机械执行：数学里数值实验**不构成证明**（`09-...md` §6.2(1)
    "验证通过 ≠ 数学正确"）。而"我算了几千个点都对"写成"已证明"是本领域
    最自然也最危险的过度声称。把它变成 schema 约束，就让这句谎话
    **在写入的那一刻**炸掉，而不是等到审校（或读者）发现。
    """

    experiment_id: str
    claim: str  # 被检验的命题（人话，给人读）
    claim_key: str  # 命题的机器可读键（用于去重与引用，如 "SpecK(m)=[-m,m]"）
    method: str
    #: 证据等级。默认 `cross_check` —— **默认值本身就在表达"这不是证明"**。
    evidence_kind: str = "cross_check"
    result: str = "inconclusive"
    #: 三种否定（FC-25）。`result="refutes"` 时必须是 `"disproved"`。
    negation_kind: str | None = None
    #: 实验脚本。**必须落在工作区内**（相对路径），且与 `code_hash` 成对出现 ——
    #: 没有哈希的"可复现"只是口号。
    code_path: str | None = None
    code_hash: str = ""
    params: dict = field(default_factory=dict)
    #: 结构化观测（极值、命中数、网格分辨率……）。给机器判读用。
    observations: dict = field(default_factory=dict)
    exit_code: int | None = None
    runtime_sec: float | None = None
    artifact_paths: list[str] = field(default_factory=list)
    #: 反例。`result="refutes"` 时**必须**给出（否则"证否"是不可复核的）。
    counterexample: dict | None = None
    #: 形式化检查器的原始输出。`evidence_kind="proof"` 时**必须**非空。
    verifier_output: str = ""
    #: **检查器输出管的是哪个命题**（来自对本地先例 DeepMath 的观摩）。
    #:
    #: DeepMath 的做法是"验证工具与上下文绑定"：越界调用直接 raise。
    #: 我们此前 `verifier_output` 是一个**自由字符串** —— 于是把"命题 A 的检查器输出"
    #: 粘到"命题 B 的记录行"上，结构上完全允许，而且**没有任何地方会报错**。
    #: 有了这个字段，`validate()` 就能要求"输出管的就是本行声称的命题"。
    verifier_subject_key: str = ""
    #: **搜索类结果必须携带证书**（来自对本地先例 dsh 数学模式的观摩）。
    #:
    #: 形态：`{"kind": "witness"|"unsat"|"enumeration_bound"|"counterexample",
    #:        "detail": {...}}`。
    #: *穷举/可满足性* 这类结论的说服力**全部**来自"证书"：
    #: "在 B 内没有反例"若不说清 B 是什么，就只是一句无法复核的话。
    certificate: dict | None = None
    #: 搜索边界（证书的适用范围）。`certificate` 非空时**必须**给出。
    search_bound: dict = field(default_factory=dict)
    for_question_id: str | None = None
    notes: str = ""
    created_at: str = ""
    created_by: str = "agent-E"

    def validate(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        if not self.claim.strip():
            raise ValueError("claim 不能为空")
        if not self.claim_key.strip():
            raise ValueError("claim_key 不能为空（没有它就无法回答'这条实验检验的是哪个命题'）")
        if self.method not in EXPERIMENT_METHODS:
            raise ValueError(f"method 必须是 {EXPERIMENT_METHODS} 之一，收到 {self.method!r}")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"evidence_kind 必须是 {EVIDENCE_KINDS} 之一，收到 {self.evidence_kind!r}")
        if self.result not in EXPERIMENT_RESULTS:
            raise ValueError(f"result 必须是 {EXPERIMENT_RESULTS} 之一，收到 {self.result!r}")
        if self.negation_kind is not None and self.negation_kind not in NEGATION_KINDS:
            raise ValueError(f"negation_kind 必须是 {NEGATION_KINDS} 之一或 None，收到 {self.negation_kind!r}")

        # ---- 硬约束 1：计算类方法**永远**拿不到 proof 等级（FC-22 的机械落地）
        if self.method != "formal" and self.evidence_kind == "proof":
            raise ValueError(
                f"method={self.method!r} 的实验不得声称 evidence_kind='proof'。"
                "数值/符号/穷举都只是**交叉验证**：数学里数值实验不构成证明。"
                "若确实要主张已证明，必须走 method='formal' 并给出 verifier_output。"
            )
        # ---- 硬约束 2：声称 proof 必须有检查器输出
        if self.evidence_kind == "proof" and not self.verifier_output.strip():
            raise ValueError(
                "evidence_kind='proof' 时必须给出 verifier_output（证明检查器的原始输出）。"
                "没有它的'已证明'与 'cross_check' 在证据上是同一件事，不应享受 proof 的待遇"
            )
        # ---- 硬约束 2b：检查器输出必须**管的就是本行声称的命题**
        #
        # 来自对本地先例 DeepMath 的观摩（它的做法是"验证工具与上下文绑定，越界即 raise"）。
        # 没有这一条时，`verifier_output` 是一个自由字符串 —— 你可以把命题 A 的
        # 检查器输出粘到命题 B 的行上，而**结构上完全合法**。
        # 这不是理论风险：任何"批量跑了一堆检查、再批量写记录"的实现都会踩到它。
        if self.evidence_kind == "proof" and not self.verifier_subject_key.strip():
            raise ValueError(
                "evidence_kind='proof' 时必须给出 verifier_subject_key（检查器输出管的是哪个命题）。"
                "否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'"
            )
        if self.verifier_subject_key.strip() and self.verifier_subject_key.strip() != self.claim_key.strip():
            raise ValueError(
                f"verifier_subject_key={self.verifier_subject_key!r} 与本行的 claim_key="
                f"{self.claim_key!r} 不一致 ⇒ 检查器输出管的不是这条命题。"
                "**验证工具必须与上下文绑定**（越界即拒绝），否则证据等级就成了可随手搬运的标签"
            )
        # ---- 硬约束 2c：搜索类结论必须携带证书
        #
        # 来自对 dsh 数学模式的观摩：*穷举 / SAT / UNSAT* 这类结论的说服力**全部**来自证书。
        # "在 B 内没有反例"若不说清 B 是什么、用什么算法搜的，就只是一句无法复核的话 ——
        # 它看起来是结论，实际上是一个**没有定义域的断言**。
        search_like = self.method in ("exhaustive_search",)
        if search_like and not self.certificate:
            raise ValueError(
                f"method={self.method!r}（穷举/枚举类）必须给出 certificate ——"
                "'在 B 内没有反例'的说服力全部来自'B 是什么、怎么搜的'。"
                "没有证书时它只是一句无法复核的话"
            )
        if self.certificate is not None:
            if not isinstance(self.certificate, dict) or not str(self.certificate.get("kind") or "").strip():
                raise ValueError("certificate 必须是对象且含 kind（witness/unsat/enumeration_bound/counterexample）")
            if not self.search_bound:
                raise ValueError(
                    "给了 certificate 就必须给 search_bound（证书的适用范围）——"
                    "证书脱离边界就没有意义"
                )
        # ---- 硬约束 3：崩溃不得被写成正面结论
        if self.exit_code is not None and self.exit_code != 0 and self.result != "inconclusive":
            raise ValueError(
                f"exit_code={self.exit_code} 表示实验**没有正常跑完**，result 必须是 'inconclusive'，"
                f"收到 {self.result!r}。把崩溃当成'支持'是本项目最忌讳的静默失败"
            )
        # ---- 硬约束 4：证否必须给出反例，且反例本身不能自称是证明
        if self.result == "refutes":
            if not self.counterexample:
                raise ValueError("result='refutes' 时必须给出 counterexample（否则'证否'不可复核）")
            if self.evidence_kind == "proof":
                raise ValueError(
                    "result='refutes' 时 evidence_kind 不得为 'proof'："
                    "反例**推翻**命题，不是对命题的证明；把它标成 proof 会让下游误读"
                )
            if self.negation_kind != "disproved":
                raise ValueError("result='refutes' 时 negation_kind 必须是 'disproved'")
        # ---- 硬约束 5：三种否定必须分类（FC-25）
        if self.result != "refutes":
            if self.negation_kind not in ("not_proved", "not_searched_here", "no_local_evidence"):
                raise ValueError(
                    f"result={self.result!r} 时必须给出 negation_kind ∈ "
                    "('not_proved','not_searched_here','no_local_evidence')。"
                    "'未证明'、'没搜过'、'搜了但没有本地证据'是三件不同的事，不许合并"
                )
        # ---- 硬约束 6：可复现性 —— 有脚本就必须有哈希
        if self.code_path is not None:
            p = self.code_path.replace("\\", "/")
            if p.startswith("/") or ":" in p or ".." in p.split("/"):
                raise ValueError(f"code_path 必须是工作区内的相对路径，收到 {self.code_path!r}")
            if not self.code_hash.strip():
                raise ValueError(
                    "给了 code_path 就必须给 code_hash —— 没有哈希的'可复现'只是口号"
                    "（脚本一改，记录就指向了另一段代码）"
                )
        if self.for_question_id is not None:
            require_id(self.for_question_id, "for_question_id")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AttackPlan:
    """F 的难题攻坚计划（DESIGN-ROLES.md §2.2）。

    **为什么"多轮"必须独立成表，而不是塞进 `research_questions`**：
    D 的 `research_questions` 的生命周期是"缺口→补证据→研究→回答"，是一棵**树**
    （一个问题一个答案）。而难题攻坚是**一个目标 + 多轮尝试**，每轮可能要
    （a）向 A 要检索、（b）让 B 重抽取、（c）让 E 做实验、（d）自己推理 —— 四种
    完全不同的动作，且要能**中途停下并把当前最好结果交出去**（FC-21）。
    把它硬塞进问题表，就会出现"一个 question 有四种互相打架的状态语义"。

    轮次历史存在 `history` 里（而不是单独一张表）：F 的审计需求是
    "把这个难题的每一轮按顺序读一遍"，一次 upsert 写整行正好服务这个需求，
    而拆表会带来额外的锁与一致性成本（本框架的 `LOCK_ORDER` 已经很长了）。
    """

    plan_id: str
    problem: str  # 难题原文（人话）
    problem_key: str  # 机器可读的难题键（去重/引用）
    for_question_id: str | None = None
    status: str = "open"
    rounds: int = 0
    #: 三维预算（FC-18）。四类键都必须在，缺一类就退化：
    #: 只有轮数上限 → 单轮可以无限扇出；只有并发上限 → 可以无限轮。
    budget: dict = field(default_factory=dict)
    #: 子目标列表。每个元素：
    #: ``{"sid","text","owner","status","evidence_ids","experiment_ids",
    #:    "blocked_reason","attempts","negation_kind"}``
    subgoals: list[dict] = field(default_factory=list)
    #: 轮次历史（append-only）。每个元素：
    #: ``{"round","sid","action","outcome","detail","evidence","at"}``
    history: list[dict] = field(default_factory=list)
    #: 深度（嵌套攻坚）。**单调不减**，用于 `max_depth`（FC-18 ③）。
    depth: int = 0
    parent_plan_id: str | None = None
    #: **未能解决时的当前最好部分结果**（FC-21：整体绝不谎报成功，
    #: 但也不该把所有中间成果丢掉）。`status="stalled"` 时必须非空。
    best_partial: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "agent-F"

    def validate(self) -> None:
        require_id(self.plan_id, "plan_id")
        if not self.problem.strip():
            raise ValueError("problem 不能为空")
        if not self.problem_key.strip():
            raise ValueError("problem_key 不能为空")
        if self.status not in ATTACK_STATUSES:
            raise ValueError(f"status 必须是 {ATTACK_STATUSES} 之一，收到 {self.status!r}")
        if self.rounds < 0:
            raise ValueError("rounds 不能为负")
        if self.depth < 0:
            raise ValueError("depth 不能为负")
        # ---- 三维预算必须完整（FC-18）
        need = ("max_rounds", "max_parallel_subgoals", "max_persist_attempts", "max_depth")
        missing = [k for k in need if k not in (self.budget or {})]
        if missing:
            raise ValueError(
                f"budget 缺少 {missing}。三个维度的预算缺一不可（FC-18）："
                "只有轮数上限则单轮可以无限扇出，只有并发上限则可以无限轮"
            )
        if self.rounds > int(self.budget.get("max_rounds", 0)):
            raise ValueError(
                f"rounds={self.rounds} 已超过 budget.max_rounds={self.budget.get('max_rounds')}"
                "（轮数上限是硬约束，超了就不该继续写）"
            )
        # ---- 子目标
        seen: set[str] = set()
        for i, sg in enumerate(self.subgoals):
            if not isinstance(sg, dict):
                raise ValueError(f"subgoals[{i}] 必须是对象")
            sid = str(sg.get("sid") or "")
            if not sid:
                raise ValueError(f"subgoals[{i}] 缺少 sid")
            if sid in seen:
                raise ValueError(f"subgoals 出现重复 sid：{sid}")
            seen.add(sid)
            st = sg.get("status")
            if st not in SUBGOAL_STATUSES:
                raise ValueError(f"subgoals[{i}].status 必须是 {SUBGOAL_STATUSES} 之一，收到 {st!r}")
            ow = sg.get("owner")
            if ow not in SUBGOAL_OWNERS:
                raise ValueError(
                    f"subgoals[{i}].owner 必须是 {SUBGOAL_OWNERS} 之一，收到 {ow!r}。"
                    "owner 是权限面的一部分，拼错会让子目标派给不存在的人"
                )
            if st == "blocked" and not str(sg.get("blocked_reason") or "").strip():
                raise ValueError(f"subgoals[{i}] 状态为 blocked 却没说被什么卡住（不许静默卡住）")
            # FC-22：子目标只能"有数值支持"，不能凭数值就被关闭
            if st == "closed" and not sg.get("proof_experiment_ids"):
                raise ValueError(
                    f"subgoals[{i}] 被标为 closed，但没有给出 proof 级证据"
                    "（proof_experiment_ids 为空）。数值/穷举支持只能标 supported_not_proved —— "
                    "把 cross_check 当证明关闭子目标，正是 FC-22 要防的事"
                )
        # ---- 轮次历史上限 & 单调性
        #
        # ⚠️ 上限是 `max_rounds × 子目标数 + 1`，**那个 +1 是必要的**。
        #
        # 曾经的判据恰好等于"每轮每子目标一条"，于是**轮数用尽的那一轮无法追加
        # 一条 `action="stop"` 的如实记录** —— "说停"这件事本身被 schema 挡住
        # （实测 `ValueError: history 长度超出预算允许的轮数 × 子目标数`），
        # 实现方只能把停止理由塞进 `best_partial` 绕过去。
        # 一条记录"我停下了"的审计行必须被允许存在，否则"为什么停"就只能靠猜。
        hist = self.history or []
        cap = int(self.budget.get("max_rounds", 0)) * max(1, len(self.subgoals) or 1) + 1
        if len(hist) > cap:
            raise ValueError(
                f"history 长度 {len(hist)} 超出预算允许的 {cap}（= max_rounds × 子目标数 + 1）"
                "：说明有轮次没有被预算约束"
            )
        last = 0
        for i, h in enumerate(hist):
            r = int(h.get("round", 0))
            if r < last:
                raise ValueError(f"history[{i}].round={r} 小于前一轮 {last}：轮次必须单调不减")
            last = r
        if self.status == "stalled" and not self.best_partial.strip():
            raise ValueError(
                "status='stalled' 时必须写 best_partial（当前最好的部分结果）。"
                "攻坚停下来了却什么都不交出去，等于把已经得到的中间成果丢掉 —— "
                "而'绝不谎报成功'不等于'什么都不报'"
            )
        if self.parent_plan_id is not None:
            require_id(self.parent_plan_id, "parent_plan_id")
        if self.for_question_id is not None:
            require_id(self.for_question_id, "for_question_id")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    """G 的稿件（DESIGN-ROLES.md §2.3）。"""

    doc_id: str
    kind: str
    title: str
    markdown_path: str | None = None
    #: 结构化章节：``[{"heading","body"}]``。存结构化是为了让 H 能**定位**到
    #: 具体章节去审，而不是对一整块 markdown 做事后正则。
    sections: list[dict] = field(default_factory=list)
    #: 断言列表。每个元素：
    #: ``{"claim_id","section","text","evidence_kind","citations":[...],
    #:    "is_negative","negation_kind","disclaimer"}``
    #: 其中 `citations` 的元素形如 ``"rel:0007"`` / ``"lit:0003#p.4"`` / ``"exp:0002"``。
    claims: list[dict] = field(default_factory=list)
    open_problems: list[str] = field(default_factory=list)
    status: str = "draft"
    review_rounds: int = 0
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "agent-G"

    def validate(self) -> None:
        require_id(self.doc_id, "doc_id")
        if self.kind not in DOC_KINDS:
            raise ValueError(f"kind 必须是 {DOC_KINDS} 之一，收到 {self.kind!r}")
        if not self.title.strip():
            raise ValueError("title 不能为空")
        if self.status not in DOC_STATUSES:
            raise ValueError(f"status 必须是 {DOC_STATUSES} 之一，收到 {self.status!r}")
        if self.markdown_path is not None:
            p = self.markdown_path.replace("\\", "/")
            if p.startswith("/") or ":" in p or ".." in p.split("/"):
                raise ValueError(f"markdown_path 必须是工作区内的相对路径，收到 {self.markdown_path!r}")
        if not self.claims:
            raise ValueError("claims 不能为空 —— 一份没有任何断言的稿件不是稿件")
        seen: set[str] = set()
        for i, c in enumerate(self.claims):
            if not isinstance(c, dict):
                raise ValueError(f"claims[{i}] 必须是对象")
            cid = str(c.get("claim_id") or "")
            if not cid:
                raise ValueError(f"claims[{i}] 缺少 claim_id")
            if cid in seen:
                raise ValueError(f"claims 出现重复 claim_id：{cid}")
            seen.add(cid)
            if not str(c.get("text") or "").strip():
                raise ValueError(f"claims[{i}] 的 text 不能为空")
            # ---- 硬约束 1：没有引用的断言不许存在（FC-02）
            cites = c.get("citations") or []
            if not cites:
                raise ValueError(
                    f"claims[{cid}] 没有 citations。**没有引用的断言不允许进入稿件**："
                    "数学断言的价值完全取决于它来自哪里（FC-02）"
                )
            for x in cites:
                if not isinstance(x, str) or not x.strip():
                    raise ValueError(f"claims[{cid}] 的 citations 含空/非字符串元素")
            ek = c.get("evidence_kind")
            if ek not in EVIDENCE_KINDS:
                raise ValueError(f"claims[{cid}].evidence_kind 必须是 {EVIDENCE_KINDS} 之一，收到 {ek!r}")
            # ---- 硬约束 2：cross_check 的断言**必须**自带"不构成证明"声明（FC-22）
            if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
                raise ValueError(
                    f"claims[{cid}] 的 evidence_kind='cross_check'，必须给 disclaimer"
                    "（如'数值交叉验证，不构成证明'）。**这句话由结构强制，不靠人记得写**"
                )
            # ---- 硬约束 3：否定型断言必须分类（FC-25）
            if c.get("is_negative") is True and not c.get("negation_kind"):
                raise ValueError(
                    f"claims[{cid}] 是否定型断言，必须给 negation_kind ∈ {NEGATION_KINDS}。"
                    "'未证明'与'已证否'在数学上是两件事"
                )
            if c.get("is_negative") is not True and c.get("negation_kind") is not None:
                raise ValueError(
                    f"claims[{cid}] 不是否定型断言却带了 negation_kind={c.get('negation_kind')!r}"
                    "（会让'否定'的计数虚高）"
                )
        if self.review_rounds < 0:
            raise ValueError("review_rounds 不能为负")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dependency:
    """G 登记的**外部依赖**（DESIGN-ROLES.md §2.3，FC-23 的落地）。

    数学上把引用的定理当成自己的定理，会**静默放大结论的适用范围**。
    论文 `test/main.pdf` 正好提供了一个真实案例：Theorem 1.5 依赖
    "companion book [6, Thm. 6.5]" 给出的 Spec S̃_m = [−m, m]，
    而那本书**不在本项目可得范围内**（Remark 1.6 自己也这么说）。
    本框架把它登记成 `status="external_unavailable"`，
    于是"我们没有独立验证这个前提"变成一条**可查询的事实**，
    而不是藏在引文角标里。
    """

    dep_id: str
    used_by: str  # "doc:0001#claim-3" / "relation:0007" / "experiment:0002"
    kind: str
    label: str  # 人话标签，如 "companion book [6] Thm. 6.5"
    status: str = "dangling"
    source_lit_id: str | None = None
    source_experiment_id: str | None = None
    page_range: PageRange = field(default_factory=PageRange)
    quote: str = ""
    #: 为什么是这个状态。**`dangling` / `external_unavailable` 时必须非空** ——
    #: "依赖没闭合"这个结论本身也要有依据。
    status_reason: str = ""
    created_at: str = ""
    created_by: str = "agent-G"

    def validate(self) -> None:
        require_id(self.dep_id, "dep_id")
        if not self.used_by.strip():
            raise ValueError("used_by 不能为空（依赖必须挂到某个具体的使用点）")
        if self.kind not in DEP_KINDS:
            raise ValueError(f"kind 必须是 {DEP_KINDS} 之一，收到 {self.kind!r}")
        if self.status not in DEP_STATUSES:
            raise ValueError(f"status 必须是 {DEP_STATUSES} 之一，收到 {self.status!r}")
        if not self.label.strip():
            raise ValueError("label 不能为空")
        if self.source_lit_id is not None:
            require_id(self.source_lit_id, "source_lit_id")
        if self.source_experiment_id is not None:
            require_id(self.source_experiment_id, "source_experiment_id")
        if self.status == "closed" and not (self.source_lit_id or self.source_experiment_id):
            raise ValueError(
                "status='closed' 必须指向一个已入库的来源（source_lit_id 或 source_experiment_id）。"
                "否则'闭合'只是声称，verify 的依赖闭合检查会立刻发现这是空头支票"
            )
        if self.status in ("dangling", "external_unavailable") and not self.status_reason.strip():
            raise ValueError(
                f"status={self.status!r} 时必须写 status_reason（依赖为什么没闭合 / 为什么不可得）。"
                "只标一个状态而不说原因，等于把问题记了一笔却没人能接手"
            )
        if self.kind == "experiment" and self.source_experiment_id is None:
            raise ValueError("kind='experiment' 的依赖必须给 source_experiment_id")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_range"] = self.page_range.to_dict()
        return d


@dataclass
class ReviewFinding:
    """H 的一条审校发现（DESIGN-ROLES.md §2.4）。

    ⚠️ **`evidence` 必填非空**，这是本表的设计核心。

    本项目最刺痛的一条教训是：**审校者的判断也需要证据**。
    上一阶段评审里，评审方（我）提出的"medium 泄漏进正文"是**错的**，
    是实现方拿证据顶回来才纠正的。若审校记录可以只写"这里有问题"而
    不给依据，那么审校就会变成**另一种幻觉的来源**，而且因为审校者的
    位置更高，它更难被纠正。
    """

    finding_id: str
    doc_id: str
    kind: str
    level: str
    target: str  # "claim-3" / "section:2" / "dep:0004" / "rel:0007"
    evidence: str  # **必填**：H 凭什么这么判
    message: str
    round: int = 1
    suggestion: str = ""
    status: str = "open"
    resolution_note: str = ""
    created_at: str = ""
    created_by: str = "agent-H"

    def validate(self) -> None:
        require_id(self.finding_id, "finding_id")
        require_id(self.doc_id, "doc_id")
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"kind 必须是 {FINDING_KINDS} 之一，收到 {self.kind!r}")
        if self.level not in FINDING_LEVELS:
            raise ValueError(f"level 必须是 {FINDING_LEVELS} 之一，收到 {self.level!r}")
        if self.status not in FINDING_STATUSES:
            raise ValueError(f"status 必须是 {FINDING_STATUSES} 之一，收到 {self.status!r}")
        if not self.target.strip():
            raise ValueError("target 不能为空（发现必须能定位到具体位置，否则无法处置）")
        if not self.evidence.strip():
            raise ValueError(
                "evidence 不能为空。**审校者的判断也需要证据** —— "
                "只写'这里有问题'的发现是另一种幻觉来源，而且更难被纠正"
            )
        if not self.message.strip():
            raise ValueError("message 不能为空")
        if self.round < 1:
            raise ValueError("round 从 1 开始")
        if self.status in ("wontfix", "disputed") and not self.resolution_note.strip():
            raise ValueError(
                f"status={self.status!r} 时必须写 resolution_note"
                "（不接受修但不说明为什么，与 'dropped 必须写 notes' 同一条纪律）"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 主控编队（Conductor）

#: **全项目唯一的角色名单**（FC-03 单一来源）。
#:
#: 此前它只活在 `tools/__init__.py` 里，而 `schema` 需要一个"role 是不是合法"
#: 的判据时只能自己再写一份 —— 那就是"跨模块字符串约定有两处定义"。
#: 现在 `tools.ROLES` **就是**这一个对象（它 import 这里），
#: 所以改角色名单只需要改一行，也不可能不一致。
ROLES = ("A", "B", "C", "D", "E", "F", "G", "H")

#: 主控（编排者）的角色标识。
#:
#: 为什么把主控也放进角色空间：本框架的入口是**用户对主控说话**，主控按需召唤角色。
#: 若主控不在这套名单里，它就成了"谁能召唤谁"策略之外的特权路径 ——
#: 而**特权路径正是权限模型最容易漏的地方**。
CONDUCTOR_ROLE = "M"

#: 一次**召唤**（summon）的任务状态。
#:
#:   pending     —— 已立项，尚未开始
#:   running     —— 正在跑
#:   done        —— 正常结束（**结果可能是"没做成"**，那看 outcome）
#:   cancelled   —— 被取消（含超时 / 预算耗尽导致的取消）
#:   failed      —— 异常终止（错误写进 error）
#:
#: ⚠️ `done` 与 `failed`/`cancelled` 必须分开：前者的语义是"这个任务**跑完了**"，
#: 后者的语义是"它**没跑完**"。三者合并成"结束"之后，就无法回答
#: "这条结论是在一次成功完成的召唤里产出的、还是在一次崩溃里被顺手写下的"。
TASK_STATUSES = ("pending", "running", "done", "cancelled", "failed")

#: 召唤的**终局类型**（回答"这次召唤到底给出了什么"）。
#:
#:   ok             —— 完成并产出了预期产出
#:   no_result      —— **完成但确实没有结果**（这是一个有效结论，如"检索无命中"）
#:   not_applicable —— 完成，但该动作在当前状态下不适用（如"没有待办"）
#:   refused        —— **框架拒绝执行**（越权 / 超预算 / 超深度 / 检测到循环）
#:   failed         —— 执行中异常
#:   cancelled      —— 被取消
#:
#: `refused` 单列是刻意的：**"我们没做"与"做了没成"是最容易被混为一谈的一对**
#: （本项目在引文校验、OCR、D 溯源、C 预算截断四处都踩过）。拒绝是**策略**的决定，
#: 失败是**执行**的结果，二者需要完全不同的处置。
TASK_OUTCOMES = ("ok", "no_result", "not_applicable", "refused", "failed", "cancelled")

#: 框架拒绝执行的具体理由（受控词表）。`outcome="refused"` 必须带其中之一。
REFUSAL_REASONS = (
    "unknown_role",  # 角色不存在
    "unknown_action",  # 该角色没有这个动作
    "forbidden_edge",  # 策略不允许这条召唤边（如 C→B）
    "depth_exceeded",  # 超过最大召唤深度
    "fanout_exceeded",  # 超过单点最大扇出
    "concurrency_exceeded",  # 超过全局并发上限
    "budget_exceeded",  # token / 花销预算耗尽
    "deadline_exceeded",  # 墙钟截止已过
    "cycle_detected",  # 同一条 (role, action, input_key) 已在祖先链上出现过
    "not_wired",  # 该角色的该动作尚未接线
)


@dataclass
class Task:
    """一次**召唤**的台账行（主控编队的核心表）。

    ## 为什么不复用已有的表

    `attack_plans` / `research_questions` 描述的是**领域对象**（一个难题、一个研究问题）；
    本表描述的是**运行记录**（谁在什么时候召唤了谁、为了什么、结果如何）。
    把它们混在一起，就会出现"一个研究问题有四种互相打架的状态语义"那种局面
    —— `AttackPlan` 的 docstring 已经为此警告过一次。

    ## 它同时承担 FC-20（取消语义）的三条要求

    1. **每个 start 有且仅有一个 end**：`started_at` / `ended_at` 成对，
       且 `status ∈ {done, cancelled, failed}` ⇒ `ended_at` 必填。
    2. **终态先到先得**：`ended_at` 一旦写下就不许再被改写 ——
       由 :meth:`validate` 的 "pending/running 却已有 ended_at ⇒ 拒" 保证。
    3. **dispose 幂等**：重复结束同一个任务时，第二次必须**什么都不做**
       （由 `Conductor` 实现；schema 在这里提供"改了就违规"的判据）。
    """

    task_id: str  # "t-NNNN"（过程记录，不占 4 位编号空间）
    role: str  # 被召唤的角色（A–H），或 "M"（主控自己）
    action: str  # 该角色暴露的动作名
    #: 谁召唤的：`"M"`（主控）、`"A"`（角色 → 角色）、`"user"`（人直接指派）。
    called_by: str = "M"
    #: 父任务 id。主控发起的为 None。
    #: **这条链是"深度"的唯一权威来源** —— 不靠调用栈，因为跨进程/跨会话之后调用栈就没了。
    parent_task_id: str | None = None
    #: 召唤链的深度（主控发起 = 1）。**单调不减**，resume 后不重置（FC-18 ③）。
    depth: int = 1
    #: 判重用的输入指纹。`(role, action, input_key)` 在**祖先链**上重复出现即判循环。
    input_key: str = ""
    status: str = "pending"
    outcome: str | None = None
    #: `outcome == "refused"` 时的受控理由（见 `REFUSAL_REASONS`）。
    refusal_reason: str | None = None
    #: 人可读的说明。**"为什么是这个结果"必须能读**，否则台账就只是个计数器。
    detail: str = ""
    error: str | None = None
    started_at: str = ""
    ended_at: str | None = None
    #: 该次召唤消耗的 token / 估算美元。由调用方在结束时回填（FC-19）。
    tokens: int = 0
    usd: float = 0.0
    #: 该次召唤登记的**产出引用**（形如 `"experiments:0003"`、`"documents:0001"`）。
    artifacts: list[str] = field(default_factory=list)
    #: 该次召唤**读过**的行（审计用；也让"这条结论的依据是哪次召唤"可回答）。
    inputs: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not str(self.task_id or "").strip():
            raise ValueError("task_id 不能为空")
        if self.role not in (*ROLES, CONDUCTOR_ROLE):
            raise ValueError(f"role 必须是 {(*ROLES, CONDUCTOR_ROLE)} 之一，收到 {self.role!r}")
        if not str(self.action or "").strip():
            raise ValueError("action 不能为空（没有动作的召唤是一句空话）")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"status 必须是 {TASK_STATUSES} 之一，收到 {self.status!r}")
        if self.outcome is not None and self.outcome not in TASK_OUTCOMES:
            raise ValueError(f"outcome 必须是 {TASK_OUTCOMES} 之一或 None，收到 {self.outcome!r}")
        if self.depth < 1:
            raise ValueError("depth 从 1 开始（主控发起 = 1）")
        if self.tokens < 0 or self.usd < 0:
            raise ValueError("tokens/usd 不能为负")

        # ---- 状态机：终态一旦写下就不许再改写（FC-20 的 first-wins）
        if self.status == "running" and not self.started_at:
            raise ValueError("status=running 必须记录 started_at（否则无法回答'跑了多久'）")
        if self.status in ("pending", "running") and self.ended_at is not None:
            raise ValueError(
                f"status={self.status!r} 却已有 ended_at —— 终态先到先得，"
                "结束时间一旦写下就不许再被改写（否则取消与完成会互相覆盖）"
            )
        if self.status in ("done", "cancelled", "failed") and not self.ended_at:
            raise ValueError(f"status={self.status!r} 必须记录 ended_at（每个 start 有且仅有一个 end）")

        # ---- 三态与一致性：`done` 必须说清"给出了什么"
        if self.status == "done" and self.outcome is None:
            raise ValueError(
                "status=done 时必须给出 outcome（ok/no_result/not_applicable/refused）—— "
                "'跑完了'与'跑完了有没有结果'是两件事"
            )
        if self.status == "done" and not str(self.detail or "").strip():
            raise ValueError("status=done 时必须写 detail（这次召唤到底做了什么）")
        if self.outcome == "refused":
            if self.status != "done":
                raise ValueError(
                    "outcome=refused 的召唤 status 必须是 'done' —— "
                    "**拒绝是一次成功执行**（框架正确地说'不'），不是失败"
                )
            if self.refusal_reason not in REFUSAL_REASONS:
                raise ValueError(
                    f"outcome=refused 时必须给 refusal_reason ∈ {REFUSAL_REASONS}，"
                    f"收到 {self.refusal_reason!r}（拒绝的理由必须是受控词表，不许自由文本）"
                )
        if self.refusal_reason is not None and self.outcome != "refused":
            raise ValueError("refusal_reason 只在 outcome='refused' 时有意义")
        if self.status == "failed" and not str(self.error or "").strip():
            raise ValueError("status=failed 时必须写 error（失败的原因不能是空白）")
        if self.status == "failed" and self.outcome != "failed":
            raise ValueError("status=failed 时 outcome 必须是 'failed'")
        if self.status == "cancelled" and self.outcome not in ("cancelled", "refused"):
            raise ValueError(
                "status=cancelled 时 outcome 必须是 'cancelled'（被取消）"
                "或 'refused'（因超预算/超截止被拒）—— 二者语义不同，但都属于'没做完'"
            )
        if self.parent_task_id is not None:
            if not str(self.parent_task_id).strip():
                raise ValueError("parent_task_id 给了就必须非空（用 None 表示主控发起）")
            if str(self.parent_task_id) == str(self.task_id):
                raise ValueError("parent_task_id 不能指向自身")
        for a in self.artifacts:
            if not str(a).strip():
                raise ValueError("artifacts 不能含空元素")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 成本与评测口径（FC-19 / FC-24）

#: 花销台账的**归口**。为什么必须有受控词表：没有它，"这次花了多少"就没有可比口径
#: （"搜索"与"审校"的 token 花在一个池子里，等于什么也没说）。
USAGE_SCOPES = ("summon", "experiment", "search", "extract", "review", "reason", "other")


@dataclass
class UsageEntry:
    """一笔花销（FC-19：token 预算是**硬约束**，且**重试也计入**）。

    ## 三条刻意的设计

    1. **零值也记**。一次"跑了但没花 token"（例如纯本地计算）必须留下一条零值记录 ——
       否则"没记账"与"花了零"无法区分，而"预算还剩多少"这个问题就永远答不准。
    2. **`attempts` 单独记**。它是"这笔钱花了几次才花出去"的直接证据：
       `04-…md` §B6 的原话是 "Each retry is another billed provider request"。
       只记总量不记次数，就无法发现"某条路径一直在重试"。
    3. **`usd` 允许为 0**（没有单价表时），但 `tokens_total` 与 `usd` **不能同时为 0
       且 `note` 为空** —— 那样这条记录不携带任何信息。
    """

    usage_id: str
    scope: str
    role: str = "unknown"
    task_id: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    #: 显式总量。留空则由 `tokens_in + tokens_out` 推得（写入方负责填一个）。
    tokens_total: int = 0
    usd: float = 0.0
    attempts: int = 1
    at: str = ""
    note: str = ""
    #: 幂等键：**同一个非空值在整张表里只能出现一次**。
    #: 空串 = "这一行没有幂等身份"（历史行、以及直接调 `TokenMeter.charge` 的行），
    #: **不受唯一性约束** —— 把它也算进唯一性会让所有历史行互相冲突、整表提交炸掉。
    #: 为什么是字段而不是 `note` 里的文本标记：见本提案 §1、§3.3。
    idem_key: str = ""

    def validate(self) -> None:
        require_id(self.usage_id, "usage_id")
        if self.scope not in USAGE_SCOPES:
            raise ValueError(f"scope 必须是 {USAGE_SCOPES} 之一，收到 {self.scope!r}")
        if self.tokens_in < 0 or self.tokens_out < 0 or self.tokens_total < 0:
            raise ValueError("token 数不能为负")
        if self.usd < 0:
            raise ValueError("usd 不能为负")
        if self.attempts < 1:
            raise ValueError(
                f"attempts 从 1 开始（收到 {self.attempts}）—— 0 次尝试却记了一笔花销是不自洽的"
            )
        if self.tokens_total and self.tokens_total < self.tokens_in + self.tokens_out:
            raise ValueError(
                f"tokens_total={self.tokens_total} 小于 tokens_in+tokens_out="
                f"{self.tokens_in + self.tokens_out}（总量口径必须覆盖分项）"
            )
        if not str(self.at or "").strip():
            raise ValueError("at 不能为空（没有时间戳的账目无法按时间对账）")
        if self.tokens_total == 0 and self.usd == 0 and not str(self.note or "").strip():
            raise ValueError(
                "零值记录必须写 note —— **零值也要记**（否则'没记账'与'花了零'无法区分），"
                "但一条不带任何信息的零值行只会污染台账"
            )
        if self.task_id is not None:
            if not str(self.task_id).strip():
                raise ValueError("task_id 给了就必须非空")
        if self.idem_key != self.idem_key.strip():
            raise ValueError(
                "idem_key 不许有首尾空白 —— 否则 '  k' 与 'k' 是两个不同的键，"
                "唯一性就形同虚设（同一笔账会被记两次，且不变量不会响）"
            )

    def to_dict(self) -> dict:
        return asdict(self)


#: FC-24 要求的**必填口径字段**。缺任一字段的评测数字**不得进入对外报告**。
#:
#: 为什么把这件事做成字段而不是"写文档时记得写"：
#: 同一个 miniF2F 数字可以是四件完全不同的事（**97% = LLM judge 分**、
#: **69% = 论文引用的文献 SOTA**、**34.8% = 端到端且与原始非形式题面比对后的精确值**、
#: **40% = 同口径在原始 miniF2F 上的成绩**），同对模型在两个口径下差 **−13.5 ~ −29.5 点**
#: （`08-…md` §A.5.5）。**口径不是补充说明，口径就是那个数字的一部分。**
EVAL_REQUIRED_FIELDS = (
    "benchmark",
    "benchmark_version",
    "split",
    "k",
    "decontamination",
    "date",
    "source",
)


@dataclass
class EvalResult:
    """一条**带完整口径**的评测结果（FC-24）。

    渲染层 gate：任何引用它的断言，其 citation 必须能解析到一条字段齐全的记录；
    缺字段的数字**不许进入对外报告**。
    """

    eval_id: str
    claim_key: str
    benchmark: str
    benchmark_version: str
    split: str
    #: pass@k 的 k。`k == 1` 表示 pass@1。
    k: int
    value: float
    #: 去污染声明。**必须显式写**（哪怕是 "none"）—— "我们没做去污染"本身是必须披露的信息。
    decontamination: str
    date: str
    source: str
    samples: int | None = None
    uses_retrieval: bool | None = None
    allows_sorry: bool | None = None
    notes: str = ""
    created_at: str = ""
    created_by: str = "agent-E"

    def validate(self) -> None:
        require_id(self.eval_id, "eval_id")
        if not str(self.claim_key or "").strip():
            raise ValueError("claim_key 不能为空（这条数字检验的是哪个命题）")
        missing = [
            f for f in EVAL_REQUIRED_FIELDS
            if not str(getattr(self, f) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"评测结果缺少必填口径字段 {missing}。"
                "**口径不是补充说明，口径就是那个数字的一部分**（FC-24）："
                "同一个基准的同一个数字在不同口径下能差 13–30 个百分点。"
                "缺任一字段的数字不得进入对外报告。"
            )
        if self.k < 1:
            raise ValueError(f"k 从 1 开始（pass@k 的 k），收到 {self.k}")
        if not (0.0 <= float(self.value) <= 1.0):
            raise ValueError(
                f"value 是**比率**（0..1），收到 {self.value}。"
                "用百分数会让'97 与 0.97'在同一条记录里共存，口径立刻失准"
            )
        if self.samples is not None and self.samples < 1:
            raise ValueError("samples 给了就必须 >= 1")
        if not str(self.created_at or "").strip():
            raise ValueError("created_at 不能为空")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- FC-05 顺序与集合分离

#: **每一个数组字段都必须在这里声明它是"集合"还是"序列"。**
#:
#: FC-05 的由来（`test/test2/LESSONS.md` §6.1）：
#: 本项目为满足"升序"不变量，**丢掉了关系链的跳序**，只能从 `origin` 字符串反解
#: （`11-…md` §6.3、§13 第 6 条）。根因是**数组字段的语义没有被显式声明** ——
#: 于是所有数组都被默认当成集合（升序去重），而"顺序本身携带信息"的那些
#: 就被静默破坏了。
#:
#: ## 三种取值
#:
#: - ``"set"`` —— **集合**：必须升序且去重。`validate_table` 会**集中**检查这一点，
#:   所以新增一个集合字段时**不需要**（也不应该）在自己的 `validate()` 里再手写一遍
#:   `if x != sorted(set(x))` —— 那种手写就是"同一判据有两处实现"。
#: - ``"seq"`` —— **序列**：保序，**不许**排序去重。必须有 **round-trip 测试**
#:   （写→读→逐元素相等），否则"保序"只是一句声明。
#: - 未声明 —— **不允许**：`verify` 会报 `undeclared_array_field`。
#:
#: 为什么用"未声明即报错"而不是"默认按集合处理"：
#: 默认值会**静默**把序列当集合。而"静默破坏顺序"正是 FC-05 要修的那个缺陷。
ARRAY_FIELD_KINDS: dict[str, dict[str, str]] = {
    "search_requests": {"result_lit_ids": "set"},
    # 作者顺序是有意义的（第一作者 ≠ 末位作者），所以是 seq。
    "literature": {"source_request_ids": "set", "authors": "seq"},
    # 别名顺序影响展示与"主名"判断；`related_concepts` 是纯集合。
    "concepts": {"related_concepts": "set", "aliases": "seq"},
    "relations": {"concept_ids": "set", "supporting_lit_ids": "set"},
    "reprocess_requests": {"relation_ids": "set", "touched_relation_ids": "set"},
    "research_questions": {
        "related_concept_ids": "set",
        "related_relation_ids": "set",
        "evidence_lit_ids": "set",
        "waiting_request_ids": "set",
        "contradiction_relation_ids": "set",
        "contradiction_request_ids": "set",
        # ⚠️ 这一对就是 FC-05 的正面范例：**同一个链条，两个字段**。
        # `related_relation_ids` 是集合（"引用了哪些知识"，升序、可比较、可查重）；
        # `relation_chain` 是序列（"按什么顺序走的"，保序、就是推理路径本身）。
        # 合成一个字段就必然丢掉一半信息 —— 这正是上一版踩过的坑。
        "relation_chain": "seq",
    },
    "analysis_reports": {},
    # 产物列表的顺序有意义（生成顺序）；重复的产物引用没有意义，但"顺序"更重要，
    # 所以是 seq 而不是 set。
    "experiments": {"artifact_paths": "seq"},
    # 子目标与轮次历史的顺序**就是**攻坚过程本身，绝不能排序。
    "attack_plans": {"subgoals": "seq", "history": "seq"},
    # 章节顺序、断言顺序、开放问题顺序都是有意义的。
    "documents": {"sections": "seq", "claims": "seq", "open_problems": "seq"},
    "dependencies": {},
    "review_findings": {},
    "tasks": {"artifacts": "set", "inputs": "set"},
    "usage_ledger": {},
    "eval_results": {},
}


def array_kinds(table: str) -> dict[str, str]:
    """某张表的数组字段声明。未登记的表返回空 dict（不是 None —— 空是"没有数组字段"）。"""
    return dict(ARRAY_FIELD_KINDS.get(table, {}))


def check_array_invariants(table: str, obj: Any) -> list[str]:
    """集中检查某行的所有**已声明为集合**的数组字段是否升序去重。

    返回违规描述列表（空 = 通过）。**由 :func:`validate_table` 调用** ——
    这就是"集合字段的升序去重"这件事的**唯一**权威检查点。

    为什么集中在表级而不是每行的 `validate()` 里：
    - 每行手写一遍是"同一判据多处实现"，漏写一处就静默失效（新增 `supporting_lit_ids`
      时就差点漏了）；
    - 而"哪些字段是集合"这件事必须显式声明（见 `ARRAY_FIELD_KINDS` 的说明）。
    """
    bad: list[str] = []
    for fname, kind in array_kinds(table).items():
        if kind != "set":
            continue
        val = getattr(obj, fname, None)
        if val is None:
            continue
        if not isinstance(val, (list, tuple)):
            bad.append(f"{fname} 声明为集合但值不是数组：{type(val).__name__}")
            continue
        if list(val) != sorted(set(val), key=lambda v: (str(type(v)), v) if False else v):
            # 上面的 key 参数是为了让混合类型也能比较；实际值域只有 str/int。
            bad.append(f"{fname} 声明为集合但未升序去重：{list(val)}")
    return bad

# ---------------------------------------------------------------- 表级容器
#: 表名 -> (文件名, 行类, ID 前缀规则)
TABLES: dict[str, dict] = {
    "search_requests": {"file": "search_requests.json", "row": SearchRequest, "id_field": "request_id", "id_kind": "request"},
    "literature": {"file": "literature.json", "row": Literature, "id_field": "lit_id", "id_kind": "lit"},
    "concepts": {"file": "concepts.json", "row": Concept, "id_field": "concept_id", "id_kind": "concept"},
    "relations": {"file": "relations.json", "row": Relation, "id_field": "relation_id", "id_kind": "relation"},
    "research_questions": {"file": "research_questions.json", "row": ResearchQuestion, "id_field": "question_id", "id_kind": "question"},
    "analysis_reports": {"file": "analysis_reports.json", "row": AnalysisReport, "id_field": "report_id", "id_kind": "report"},
    "reprocess_requests": {"file": "reprocess_requests.json", "row": ReprocessRequest, "id_field": "reprocess_id", "id_kind": "reprocess"},
    "experiments": {"file": "experiments.json", "row": Experiment, "id_field": "experiment_id", "id_kind": "experiment"},
    "attack_plans": {"file": "attack_plans.json", "row": AttackPlan, "id_field": "plan_id", "id_kind": "plan"},
    "documents": {"file": "documents.json", "row": Document, "id_field": "doc_id", "id_kind": "doc"},
    "dependencies": {"file": "dependencies.json", "row": Dependency, "id_field": "dep_id", "id_kind": "dep"},
    "review_findings": {"file": "review_findings.json", "row": ReviewFinding, "id_field": "finding_id", "id_kind": "finding"},
    "tasks": {"file": "tasks.json", "row": Task, "id_field": "task_id", "id_kind": "task"},
    "usage_ledger": {"file": "usage_ledger.json", "row": UsageEntry, "id_field": "usage_id", "id_kind": "usage"},
    "eval_results": {"file": "eval_results.json", "row": EvalResult, "id_field": "eval_id", "id_kind": "eval"},
}

#: 4 位 ID 分配器覆盖的表（search_requests 用 r-NNNN，reprocess_requests 用 p-NNNN，
#: 都不占用 4 位编号空间 —— 它们是**过程记录**，而 4 位空间留给**知识实体**）。
ID_COUNTERS = {
    "lit": "lit_id",
    "concept": "concept_id",
    "relation": "relation_id",
    "question": "question_id",
    "report": "report_id",
    "experiment": "experiment_id",
    "plan": "plan_id",
    "doc": "doc_id",
    "dep": "dep_id",
    "finding": "finding_id",
    "usage": "usage_id",
    "eval": "eval_id",
}


def empty_table() -> dict:
    return {"schema_version": SCHEMA_VERSION, "rows": []}


def validate_table(table: str, doc: dict) -> None:
    """校验一张表的整体结构。抛 ValueError，不返回布尔值 —— 让错误尽早炸出来。"""
    if table not in TABLES:
        raise ValueError(f"未知表名：{table}")
    if not isinstance(doc, dict):
        raise ValueError(f"{table} 快照必须是对象")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{table} schema_version 应为 {SCHEMA_VERSION}，收到 {doc.get('schema_version')!r}")
    rows = doc.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{table}.rows 必须是数组")

    spec = TABLES[table]
    id_field = spec["id_field"]
    seen_ids: set[str] = set()
    # ---- 幂等键的唯一性（"被索引的唯一键"在本栈里的落点）
    #
    # 判据是**通用的**：任何行只要带一个**非空**的 `idem_key`，它在整张表里就必须唯一。
    # 没有把 `idem_key` 特判成"只有 usage_ledger 才有"：那样每新增一张需要幂等的表
    # 都要改这里一次，而漏改的表现是"静默没有唯一性"（没有任何检查会响）。
    seen_idem: dict[str, str] = {}
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"{table}.rows[{i}] 必须是对象")
        try:
            obj = row_from_dict(table, raw)
            obj.validate()
            # FC-05：集合字段的升序去重在这里**集中**检查（唯一权威点）。
            problems = check_array_invariants(table, obj)
            if problems:
                raise ValueError("；".join(problems))
        except ValueError as e:
            raise ValueError(f"{table}.rows[{i}] 校验失败：{e}") from e
        rid = getattr(obj, id_field)
        if rid in seen_ids:
            raise ValueError(f"{table} 出现重复 ID：{rid}")
        seen_ids.add(rid)
        key_val = str(getattr(obj, "idem_key", "") or "")
        if key_val:
            if key_val in seen_idem:
                raise ValueError(
                    f"{table} 出现重复的幂等键 {key_val!r}"
                    f"（{id_field}={seen_idem[key_val]} 与 {rid}）—— "
                    "同一笔账被记了两次，花销与预算都会翻倍。"
                    "这在本项目的既有判据下**完全不可见**（两行的 usage_id 不同，"
                    "duplicate_id 不响），所以这条断言是它唯一的自动防线。"
                )
            seen_idem[key_val] = str(rid)


def row_from_dict(table: str, raw: dict):
    """把快照里的 dict 还原成行对象。未知字段会被忽略（向前兼容）。"""
    if table == "search_requests":
        return SearchRequest(**{k: raw[k] for k in raw if k in SearchRequest.__dataclass_fields__})
    if table == "literature":
        return Literature(**{k: raw[k] for k in raw if k in Literature.__dataclass_fields__})
    if table == "concepts":
        return Concept(**{k: raw[k] for k in raw if k in Concept.__dataclass_fields__})
    if table == "relations":
        d = {k: raw[k] for k in raw if k in Relation.__dataclass_fields__}
        d["page_range"] = PageRange.from_dict(raw.get("page_range"))
        return Relation(**d)
    if table == "research_questions":
        return ResearchQuestion(**{k: raw[k] for k in raw if k in ResearchQuestion.__dataclass_fields__})
    if table == "analysis_reports":
        return AnalysisReport(**{k: raw[k] for k in raw if k in AnalysisReport.__dataclass_fields__})
    if table == "reprocess_requests":
        return ReprocessRequest(**{k: raw[k] for k in raw if k in ReprocessRequest.__dataclass_fields__})
    if table == "experiments":
        return Experiment(**{k: raw[k] for k in raw if k in Experiment.__dataclass_fields__})
    if table == "attack_plans":
        return AttackPlan(**{k: raw[k] for k in raw if k in AttackPlan.__dataclass_fields__})
    if table == "documents":
        return Document(**{k: raw[k] for k in raw if k in Document.__dataclass_fields__})
    if table == "dependencies":
        d = {k: raw[k] for k in raw if k in Dependency.__dataclass_fields__}
        d["page_range"] = PageRange.from_dict(raw.get("page_range"))
        return Dependency(**d)
    if table == "review_findings":
        return ReviewFinding(**{k: raw[k] for k in raw if k in ReviewFinding.__dataclass_fields__})
    if table == "tasks":
        return Task(**{k: raw[k] for k in raw if k in Task.__dataclass_fields__})
    if table == "usage_ledger":
        return UsageEntry(**{k: raw[k] for k in raw if k in UsageEntry.__dataclass_fields__})
    if table == "eval_results":
        return EvalResult(**{k: raw[k] for k in raw if k in EvalResult.__dataclass_fields__})
    raise ValueError(f"未知表名：{table}")
