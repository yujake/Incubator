"""数据模型与校验。

设计要点：
- 需求给定的字段一律保留原名与语义；本模块只做"结构化 + 约束"。
- 所有 ID 是不带前导零丢失风险的十进制字符串（当前宽度六位 "000000"…"999999"；
  旧数据里的四位号按读侧兼容照样读得进来），不用 int，避免前导零在序列化时丢失。
- 数组字段（related_concepts / concept_ids / source_request_ids）在写入前统一走
  `sorted_unique()`，把"保持升序、去重"从"调用方记得做"变成"结构上不可能做错"。
  "写入前"那一步的落点是 `normalize_set_fields()`（写侧归一）：它按
  `ARRAY_FIELD_KINDS` 里声明为 `set` 的那些字段就地排序去重，并把改动过的字段名
  回给调用方；`check_array_invariants()` 仍是落盘那一侧的判据（归一化不是放宽它）。
- 时间戳统一 ISO-8601 带时区，由 `now_iso()` 产生，保证同库内可比。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping

#: 磁盘格式契约的版本号（读期 fail-closed，版本不符一律拒读）。
#:
#: `2`：`concepts` 表不存在了 —— 概念行以 `kind="concept"` 住进 `statements`
#: （号由同一个分配器重发），`TABLES` / `LOCK_ORDER` / `ARRAY_FIELD_KINDS` 里都没有它。
#: 老盘（v1）不靠读期兼容 —— 读期照旧拒，唯一的兼容点是
#: `store.rebuild`：它接受上一版的事件（`known_old`），把 `concepts` 那一段
#: 折进 `statements` 再写快照（折叠内核在 `migrate_concepts`，改号逐条落
#: `out/migrate-map.jsonl`）。
#:
#: `2` 仍然是当前版本（2026-11-22 `A-0c-2` CONTRACT-DRESEARCH 加 `DOC_KINDS=research`
#: **没有**抬它，理由要能复算）：
#:
#: 1. **方向的差别**：`F-7` 管的是"旧数据被按新语义解释"。这一笔里新代码读每一行老
#:    `documents` 行都逐字不变（`kind` 词表只加了一个新取值，老取值的语义与校验一个
#:    字节没动，也没有新增/改义字段）⇒ 新读旧不需要翻译；
#: 2. **抬的代价是立刻的、全局的**：读期 fail-closed 会让盘上每一个 v2 工作区
#:    （`projects/**` 实测 60+ 份 `data/*.json`）与 `tests/` 里 54 处硬写
#:    `"schema_version": 2` 的夹具当场拒读，而 `rebuild` 是唯一出路；
#: 3. **剩下的那一点风险照实登记**：反过来（老二进制重放含 `research` 行的新事件）会
#:    在 `store` 的重放校验里被判 `schema_rejected` 跳过一行 —— 那份 markdown 与事件
#:    都还在盘上、可人工补，而"当前代码读不了当前盘"是不可接受的。业主若要老二进制
#:    硬失败而不是静默跳过，下一笔再把版本抬到 3（那时要同时改 54 处夹具）。
SCHEMA_VERSION = 2

# ---------------------------------------------------------------- 枚举 / 受控词表

#: 搜索模式。对应需求里的 广泛 / 专题 / 精确。
SEARCH_MODES = ("broad", "topical", "precise")

#: 任务优先级（I7）。A 的检索产能是稀缺资源，必须能排序；
#: 只做排队，不做抢占（抢占会打断正在跑的 A，代价大于收益）。
PRIORITIES = ("high", "medium", "low")

#: 优先级的可比较次序。数字越小越先被取走。
#: 之所以集中定义在这里而不是散落在各智能体里：一旦 A 的取任务顺序与
#: D 的派发顺序用了两套口径，"high 优先"就会静默失效 —— 而它不会报错。
PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

#: 各提交方的默认优先级（DESIGN-INTERACTIONS.md §1 I7 的表）。
#: 未登记的提交方一律落到 "low" —— 宁可让陌生来源排在后面，也不要让它插队。
#:
#: 本框架自己的角色必须显式登记，不能靠"未登记 ⇒ low"这条兜底。
#: 兜底的语义是"我不认识这个来源，所以不让它插队"；而 E/F/G/H 我们是认识的。
#: 把两者混为一谈会造成一个静默的错觉：F 提交的攻坚检索需求读到 `low`，
#: 看上去像"框架决定它不重要"，实际是"框架没登记它"。
SUBMITTER_DEFAULT_PRIORITY: dict[str, str] = {
    "agent-D:contradiction": "high",
    "human": "high",
    "agent-D": "medium",
    "agent-C": "medium",
    # F 的检索需求来自"多轮攻坚"。登记为 low 是一个刻意的决定，不是兜底：
    # 设计基线（DESIGN-INTERACTIONS.md §1 I7 的表）只为"矛盾"(high)、
    # "D/C 的缺口"(medium)、"B 的补定义"(low)、"人"(high) 给过依据；
    # 对 F 没有任何证据说明它的需求比 C 的缺口更急。在没有依据时保守：
    # 排在后面比让它插队安全，而且这个"low"是写下来的，不是"没登记所以碰巧低"。
    "agent-F": "low",
    # B 的补定义可以在空闲时做。
    "agent-B": "low",
    # E 做实验、G 写稿、H 审校 —— 它们本来就不该直接提交检索请求。
    # 登记成 low 而不是靠兜底，是为了让"它们提交了"这件事是一个显式事实：
    # 真出现了，就是有人越界或有人手动代提交，值得看一眼。
    "agent-E": "low",
    "agent-G": "low",
    "agent-H": "low",
    # A 自己的检索需求：显式登记为 low（写下来的决定，不是靠兜底）。
    # A 实例提交的行（`agent-A-A1` / `agent-A-egr` 这类带后缀的写法）经
    # `interactions.role_key_of_submitter` 折到 `agent-A` 之后命中的就是这一行；
    # 理由串因此读作"按提交方 … 的角色 agent-A 的默认优先级"。
    "agent-A": "low",
    "unknown": "low",
}

#: GB/T 7714 文献类型标识码（参考论文参考文献的标注方法）。
LIT_TYPES = ("J", "M", "C", "D", "R", "S", "P", "N", "EB", "Z")

#: 关系/概念的复核状态。suspect 是"几乎相同"判定的中间态，保留可审计性。
RELATION_STATUS = ("active", "suspect", "rejected")

#: 一次搜索请求的终局类型：回答"这一行是怎么结束的"，不是"有没有出错" —— 二者必须分开，
#: 否则"搜索了但没有结果"会被当成故障，而"所有 provider 都失败"会被当成正常完成。
#:   ok —— 至少登记了一篇文献；no_results —— 搜索正常执行但确实没有命中（这是一个有效结论）；
#:   search_failed —— 所有 provider 都失败且已用尽重试；gave_up —— 超过最大尝试次数被放弃。
#:
#: 别与 `TASK_OUTCOMES` 串了（两套命名空间只差一个字母）：本词表（`search_requests.outcome`）
#: 用复数 `no_results`，`TASK_OUTCOMES`（`tasks.outcome`）用单数 `no_result`。错一个字母不会
#: 有任何东西变红 —— 两处 `validate` 都只说"不在词表里"，不会告诉你串了哪一套。
SEARCH_OUTCOMES = ("ok", "no_results", "search_failed", "gave_up")

#: `literature.download.status` 的受控词表。
#:
#: 为什么必须做成受控词表而不是随手写字符串：AgentB 是靠
#: `status == "content_mismatch"` 来决定"不要抽取这个文件"的。一旦有人把
#: 它拼成 `content-mismatch` / `contentMismatch`，比较就会静默失败 —— B 会照常
#: 去抽取一个 HTML 落地页，把网页文字当成"概念"。这正是缺陷 #8 的复发路径，
#: 而它不会报任何错。把它纳入 schema 校验，就让拼错在写入时立刻炸出来。
#:   ok                —— 下全了，且内容类型与预期相符
#:   content_mismatch  —— 下全了，但内容类型不是想要的（如 .pdf 链接返回 HTML）
#:   failed            —— 下载失败（网络/HTTP/搬文件失败）
#:   skipped           —— 未尝试下载（无 pdf_url / 关闭下载 / 达到单请求上限）
DOWNLOAD_STATUSES = ("ok", "content_mismatch", "failed", "skipped")

#: 「待新增文献列表」(`lit_candidates`) 的槽位状态词表：六态，不是"在/不在"两态。
#: 折成一个布尔会让四种处置在盘上同形，而它们的下一步动作相反。
#:   pending    —— 在列表里等着被审（唯一可被 stage_withdraw / stage_reject / admit 的态）
#:   withdrawn  —— 被撤掉：槽位仍在列表里（序号不复用），`withdrawn_reason` 必须非空
#:   rejected   —— 审内容后拒收：`reject_reason` 必须非空（重叠检查没通过也走这一档）
#:   qualified  —— 判收（有入库资格）但**尚未注册**：`relevance` 必须非空、`lit_id` 必须为空
#:                 （2026-11-16 Q1，业主口径「判收不注册、提交时才注册」：号是提交那一刻
#:                 由系统批量发出来的，判定期只有临时号 `cand:<槽位>`）
#:   admitted   —— 已正式入库：`lit_id` 必须非空（就是 literature 里那一行）
#:   cleared    —— 迁移结算时被清空的残留（超配额/未审完）：`cleared_at` 与 `clear_reason` 必须非空
CANDIDATE_STATUSES: tuple[str, ...] = ("pending", "withdrawn", "rejected", "qualified",
                                       "admitted", "cleared")

#: 「待新增文献列表」的筛选理由受控词表（理由用受控取值，不许自由发挥）。
#: 为什么要受控：这些理由会进委托报告的"未入库"一块，而报告交给下一次委托的 D/H 读 —— 自由
#: 文本没法按类统计（这一轮挡了几篇重复、几篇低质），也没法被机器判据检查。每一档都是一个
#: 可判定的情形：`withdrawn_by_reviewer` / `rejected_off_topic` / `rejected_low_quality` /
#: `duplicate_doi` / `overlap_without_new_content` / `overlap_ok_false` / `registration_failed`
#: （过了筛但没给出 `lit_id`，入库失败不是成功）/ `over_cap`（本次委托配额已满，≤10 篇）/
#: `not_screened`（一键迁移结算时仍未审完，随委托一并清空）。
CANDIDATE_REASON_CODES: tuple[str, ...] = (
    "withdrawn_by_reviewer",
    "rejected_off_topic",
    "rejected_low_quality",
    "duplicate_doi",
    "overlap_without_new_content",
    "overlap_ok_false",
    "registration_failed",
    "over_cap",
    "not_screened",
)

#: 理由码的中文标签（写进行上的那一栏、并进报告的括号里）。
#:
#: 与 `CANDIDATE_REASON_CODES` 同文件、同顺序的语义：加一个码必须同时加一条标签，
#: 否则报告里会出现一个只有码没有说法的条目（`assert` 在下面的导入期判据里守着）。
CANDIDATE_REASON_LABELS: dict[str, str] = {
    "withdrawn_by_reviewer": "已撤掉（审内容后自己撤的）",
    "rejected_off_topic": "拒收（与本次检索无关）",
    "rejected_low_quality": "拒收（内容质量不足）",
    "duplicate_doi": "拒收（DOI 与本地库完全相同 ⇒ 视为重复）",
    "overlap_without_new_content": "拒收（与本地库重叠度高且没给新内容）",
    "overlap_ok_false": "拒收（调用方显式标了不可收）",
    "registration_failed": "没入库（登记路径没给出 lit_id）",
    "over_cap": "未入库（本次委托的入库配额已满，≤10 篇）",
    "not_screened": "未入库（迁移结算时仍未审完）",
}

assert set(CANDIDATE_REASON_LABELS) == set(CANDIDATE_REASON_CODES), (
    "CANDIDATE_REASON_LABELS 与 CANDIDATE_REASON_CODES 的取值不一致 —— "
    "报告里会出现只有码没有说法的条目（加一个理由码必须同时加一条标签）"
)

#: `literature.matched` 的受控词表：检索回来的到底是不是这一篇。
#:   exact —— 题名/年份/DOI 都对得上派活时点名的那一篇；partial —— 同一篇但元数据有出入；
#:   mismatch —— 不是同一篇（例如要 Brown 1971，下回来 2022 年另一篇 CLT 论文，真 PDF、
#:                 登记成功，没有任何地方报出来）。
#: 空串是第四态、不是缺席："" = 还没做命中校验（三态纪律："没查"不能折成"查过了没问题"）。
#: 别与"这条定理在不在这篇里"那一栏的 `matched` 串了（同 `SEARCH_OUTCOMES` 那一族的形态）：本栏问
#: "这一篇是不是我要的那一篇"（文献身份）⇒ 第三态叫 `mismatch`；那处问"这条定理在不在这篇
#: 里"（文内定位）⇒ 第三态叫 `none`。处置方向相反（重取 vs 换关键词/如实回报），折平即同形。
LIT_MATCH_STATUSES = ("exact", "partial", "mismatch")

#: 编号宽度的唯一定义处（六位十进制，防溢出）。
#:
#: 为什么必须是一处：`store.MAX_ID`（上限）与三个形态判据（`_ID_RE` / `_PROCESS_ID_RE` /
#: 各消费方的正则）都从它派生 —— `assert_id_space_contract()` 存在的理由
#: 就是"上限与形态不许分家"：改 `ID_DIGITS` 而忘了改 `MAX_ID`，导入期当场炸。
ID_DIGITS = 6

#: 当前宽度的编号形态（新写的号必须是它）。
ID_PATTERN = rf"\d{{{ID_DIGITS}}}"

#: 旧数据（4 位）的读侧兼容形态。
#:
#: 盘上已有的 4 位号照样读得进来（`is_valid_id` 两条形态都认），
#: 但发号器只发六位（`format_id()` 一处；判据见 `tests/test_id_width.py`）。
#: 不这么做的话，`store.rebuild()` 会把所有历史行当坏行静默跳过 —— 那是数据毁灭，
#: 不是"迁移"。
LEGACY_ID_PATTERN = r"\d{4}"

#: "六位或旧四位"的合并形态：给消费方（解析别人写下的号的那些正则）用。
ID_OR_LEGACY_PATTERN = rf"(?:{ID_PATTERN}|{LEGACY_ID_PATTERN})"

_ID_RE = re.compile(rf"^{ID_PATTERN}$")
_LEGACY_ID_RE = re.compile(rf"^{LEGACY_ID_PATTERN}$")


def format_id(n: int) -> str:
    """把整数编号按当前宽度写成字符串（发号的唯一形态）。

    所有发号点（`store.alloc_id` / `interactions.next_prefixed_id` /
    `table_tools._allocate_id` / 手稿号 / 留言号 / 问题号 / 审校号）都从这里取形态，
    于是"宽度"只有一处可改，也不会有人漏掉某一个发号点。
    """
    return f"{int(n):0{ID_DIGITS}d}"


def now_iso() -> str:
    """返回带本地时区偏移的 ISO-8601 时间戳（秒级）。"""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def is_valid_id(value: Any) -> bool:
    """ID 形态判据：当前宽度（六位）或旧数据宽度（四位）。

    两个宽度都认的理由是读侧兼容：盘上已有的号是 4 位，`store.rebuild()` 与每一行
    `validate()` 都走这里 —— 只认六位会把全部历史行判成坏行静默跳过。
    "新号必须是六位"这条不在这一格判，它在发号器上判（`format_id()` 一处，
    判据见 `tests/test_id_width.py`）：读侧要宽、写侧只有一条路。
    """
    return isinstance(value, str) and bool(_ID_RE.match(value) or _LEGACY_ID_RE.match(value))


def is_legacy_id(value: Any) -> bool:
    """这个号是不是旧数据宽度（4 位）——读侧留痕用，不当写入判据。"""
    return isinstance(value, str) and bool(_LEGACY_ID_RE.match(value))


def id_width(value: Any) -> int:
    """这个号的宽度（不是字符串就是 0）——给判据与迁移读数用。"""
    if not isinstance(value, str) or not value.isdigit():
        return 0
    return len(value)


def require_id(value: Any, what: str = "id") -> str:
    if not is_valid_id(value):
        raise ValueError(
            f"{what} 必须是 {ID_DIGITS} 位十进制字符串（如 {format_id(0)}；"
            f"旧数据里的 4 位号仍可读），收到 {value!r}")
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
    #: 该请求是为哪个研究问题服务的（I2 矛盾闭环 / 3.2 证据就绪判据都要它）。
    #: 空串表示"不是由某个问题驱动的"（例如人在 CLI 上手敲的）。
    for_question_id: str | None = None
    #: 提交来源的自由文本说明（人可读；机器判定只看 `submitted_by`）。
    submit_note: str = ""
    #: 这一次检索点名要问哪几个源（一次问多源）。
    #: [契约] 空数组是「没有点名源 ⇒ 按角色级接线查」这一态，不是缺省值（所以不用 `None`/空串）；
    #: 非空数组是「只问这几个源，次序就是问的次序」。
    #: [为什么] 默认值必须是空数组：盘上已有的行没有这个键，`row_from_dict` 按 `__dataclass_fields__`
    #: 过滤后缺的键交给默认值 ⇒ 老行照样读得进来；这也是本次不抬 `SCHEMA_VERSION` 的理由。
    #: [为什么] 这里刻意不校验「源名认不认识」：可用源的真身是 `providers.build_providers` 那张名单
    #: 加调用方注入的实例，抄进 schema 就是造出第二个要同步的地方。认识的判据在动作层
    #: （`AgentA.search_literature` 入队前逐个核名），本字段只做形状校验（非空字符串、元素是字符串）。
    providers: list[str] = field(default_factory=list)
    #: 提交方那一个实例（FX-14，2026-11-19）：`submitted_by` 是冻结契约键（I7 的优先级
    #: 查表按它认「提交方是谁」；把运行标签混进去会让默认优先级静默掉到 low），所以实例
    #: 标签另存一格 —— 「这一条请求是哪一个 F 交的」答得出来，契约键不动。空串 = 老行 /
    #: 直调（读侧按「没记」处理，不编一个实例出来）。
    #:
    #: 必须追加在**尾部**（不是插在 `submitted_by` 后面）：字段顺序既是位置参数构造的顺序，
    #: 也是 `to_dict()` 落盘的键序 —— 插队会改掉既有字段的位置，判据
    #: `tests/test_agent_a_search_providers.py::test_the_dataclass_fields_are_appended_so_positional_construction_still_works`
    #: 钉的就是这一条（改前 FX-14 把它插在第 8 格，老的位置参数构造会把 `claimed_by` 的值
    #: 喂给实例标签，而 `asdict` 的键序也与盘上老行不一致）。
    submitted_instance: str = ""

    def validate(self) -> None:
        if not self.request_id:
            raise ValueError("request_id 不能为空")
        # 非空之外还必须过过程记录 ID 的完整判据（形态 + 前缀）：
        # 只查非空时 `r--0001` / `0000` / `gb-0001` 全部通过 `validate()`。
        require_process_id(self.request_id, "request")
        if self.mode not in SEARCH_MODES:
            raise ValueError(f"mode 必须是 {SEARCH_MODES} 之一，收到 {self.mode!r}")
        # `providers` 只做形状校验：是不是数组、元素是不是非空字符串。
        # 「这个源名认不认识」不在这里判 —— 那需要读检索后端注册表，
        # 而把它读进 schema 就是造出第二份名单（见字段上的注释）。
        if not isinstance(self.providers, (list, tuple)):
            raise ValueError(
                "providers 必须是数组（这一次要点名的源名列表）；没有点名源就留空数组，"
                f"不要用 None 或空串，收到 {type(self.providers).__name__} —— "
                "「没点名」与「点名了一个空名字」在盘上同形之后就再也分不开了"
            )
        for i, name in enumerate(self.providers):
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    f"providers[{i}] 必须是非空字符串（源名），收到 {name!r}："
                    "空名字既不是「按角色配置查」也不是一个可用的源"
                )
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
        # 这里不强制 outcome 必填（历史数据与测试夹具可能只有 result_lit_ids /
        # last_error），但明确拒绝"三样都没有"的情况：搜索正常返回空结果时既不写
        # lit_ids 也不写 error，于是无法与"没跑过"区分。
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


#: `literature.path` 的坐标系前缀。这一格永远不写它 —— 见 `literature_path_problem`。
LIT_PATH_PREFIX = "library/"


def literature_path_problem(path: str | None) -> str | None:
    """`literature.path` 的形状判据（唯一实现）：合法 ⇒ `None`，否则 ⇒ 拒信正文。

    ## 为什么这里专门拒 `library/` 前缀
    这一格存的是相对 `library/` 的路径（`000001/x.pdf`），库根本身不写进来。
    所以 `library/` 前缀不是"风格"，是多一层：带它会被下游按 `library` 基准再拼一次，
    解析到库里不存在的 `library/library/…` ⇒ `file_missing`。
    拒信必须说清该怎么写 —— 只说"不合法"，模型只能再猜一次。

    ## 为什么只判形状、不判盘（"文件在不在"不在这里）
    `validate()` 是字段级的，手上没有工作区根（同样的话写在 `store._refuse_fake_proof_review`
    的注释里：那条判据要读盘，所以它落在事务提交块而不是 `validate`）。而且 `validate()` 在
    `Store.rebuild()` 重放历史时也会被调用 —— 「读历史不是改历史」：存量里的坏行由审计期
    `verify.file_missing` 点名，不该让重建整个失败。写入期的"落地"判据在
    `tools/table_tools.py`（那里有 `Store`）：路径存在但不是普通文件 ⇒ 拒；文件不在 ⇒ 放行
    （可修的状态，存在性归审计期，同 `relations.dangling_concept` 的口径）。
    """
    if path is None:
        return None
    p = path.replace("\\", "/")
    if p.startswith(LIT_PATH_PREFIX):
        rest = p[len(LIT_PATH_PREFIX):]
        how = f"`{rest}`" if rest else "`000001/xxx.pdf`"
        return (
            f"path 不要带 library/ 前缀：这一格存的是相对 **library/** 的路径，"
            f"写成 {how} 这种形态（库根本身不写进这一格）。"
            f"带前缀会被下游按 library 基准再拼一层，变成 library/library/… ⇒ file_missing。"
            f"收到 {path!r}"
        )
    if p.startswith("/") or ":" in p or ".." in p.split("/"):
        return (
            f"path 必须是 library/ 下的相对路径（工程内相对、不带盘符、不含 `..` 段），"
            f"收到 {path!r}"
        )
    return None


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
    #: 期刊/文集里的页码范围（GB/T 7714 的"页码"那一栏）。
    #: 空串 = 还没记（不是"这篇没有页码"：整本专著、预印本确实可以没有）。
    #: 为什么是字符串而不是 PageRange：row_from_dict 对 literature 只按 __dataclass_fields__ 过滤、
    #: 不做 PageRange.from_dict（对照 relations 那一支），直接放 PageRange 字段会让盘上的 dict 原样贴进来。
    pages: str = ""
    #: 命中校验结论：`exact` / `partial` / `mismatch` / `""`（= 还没核）。
    #: 词表与"为什么它和文献定位那一栏的 matched 不是一回事"见 `LIT_MATCH_STATUSES`。
    matched: str = ""
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
        # path 允许为 None（下载失败），但不能是绝对路径、越出 library/ 的相对路径，
        # 也不能带多余的 `library/` 前缀。判据本体在 `literature_path_problem`（唯一实现，
        # 为什么专拒 `library/` 前缀也写在那里）：`table_tools` 的归一化
        # 与反真空都钉同一个函数名，判据不许有第二份。
        if self.path is not None:
            problem = literature_path_problem(self.path)
            if problem is not None:
                raise ValueError(problem)
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
        # 命中校验：空串是合法的第四态（= 还没核），非空必须在词表里。
        if self.matched and self.matched not in LIT_MATCH_STATUSES:
            raise ValueError(
                f"matched 必须是 {LIT_MATCH_STATUSES} 之一，或空串（= 还没做命中校验），"
                f"收到 {self.matched!r}。拼错的后果与 download.status 同族："
                "下游靠这个字符串判断'要不要信这一篇'，而错拼只会静默放行。"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LitCandidate:
    """「待新增文献列表」的一行。

    ## 它为什么必须是一张自己的表，而不是 `literature` 的一个 processed 值：它要存的两件事实在 literature 上
    无处可写 —— 塞进 `download.error` 或自由文本等于把证据藏进一句散文：谁都没法按状态查，也无法证明"12 条
    里只入了 9 条"是因为撤了 3 条而不是丢了 3 条。那两件事实是：
    1. 槽位 —— 列表内序号自动分配、不复用，撤掉之后那一位空着（"第 3 号被撤了哪一篇、为什么"必须还查得出来）；
    2. 筛选过程本身 —— 撤掉/拒收的理由、与本地库的重叠读数、以及"本次检索要的新内容"。
    ## 三处不变量（`validate()` 守的正是这几条）：`status == "withdrawn"` ⇒ `withdrawn_reason` 非空；
    `status == "rejected"` ⇒ `reject_reason` 非空；`status == "admitted"` ⇒ `lit_id` 非空；`status == "cleared"`
    ⇒ `cleared_at` 与 `clear_reason` 都非空（"清空"是一次有时间的收尾动作，不是"这一行从来没被处理过"）。
    2026-11-16（Q1）多一条：`status == "qualified"`（判收、尚未注册）⇒ `relevance` 非空且 `lit_id` 为空
    —— "有资格"与"有号"是两件事，判定期一个号都没有（临时号是 `cand:<槽位>`，由 `slot` 派生，不落字段）。
    这些不变量都写成"状态 ⇒ 证据非空"，而不是"有理由 ⇒ 改状态"：后者允许"先撤、后补理由"的两段式，而两段式
    在崩溃点上会留下一行撤了但说不出为什么的记录。
    ## 字段口径：`slot` 主键，列表内序号，由 `store.alloc_id("candidate")` 发（六位、只增不复用），批次之间
    连续编号（第 2 批从第 1 批的下一个号起，所以"12 条 + 3 条"是 1..15）；`request_id` 属于哪一次查询委托
    （`r-NNNNNN` = `search_requests` 的一行：生命周期 = 一次委托，旧委托的行不参与
    本次筛选但不删掉，审计时按 `request_id` 查得到）；`batch` 第几批；`relevance` 一句"为什么与本次检索
    相关"；`reason_code` 筛除理由的受控取值（`CANDIDATE_REASON_CODES`）；`overlap_score` / `overlap_kind` /
    `overlap_with` 与本地库的重叠读数（受控取值见 `litstage.OVERLAP_KINDS`：`doi_exact` / `title_jaccard`；
    拿不到时是 `None` / 空串 —— 三态：没查 ≠ 查了没重叠）；`new_content` 重叠度高时调用方必须给的那句话
    （"给了但没答到点上"机器判不了，所以只判非空）。
    """

    slot: str
    batch: int
    status: str
    title: str
    #: 这一次查询委托（`search_requests.request_id`）：列表按委托重置，默认视图只按它过滤。
    request_id: str = ""
    doi: str | None = None
    provider: str = ""
    year: int | None = None
    type_code: str = "J"
    summary: str = ""
    url: str = ""
    added_at: str = ""
    #: 一句"它为什么与本次检索相关"（委托报告的已入库块要用它）。
    relevance: str = ""
    #: 入库后回填的 literature 行号；未入库时是 `None`（不是空串 —— 空串是"说得出但为空"）。
    lit_id: str | None = None
    admitted_at: str = ""
    #: 筛除理由的受控取值（`CANDIDATE_REASON_CODES` 之一，或空串 = 还没筛）。
    reason_code: str = ""
    #: 撤掉的理由（`status == "withdrawn"` 时必须非空）。
    withdrawn_reason: str = ""
    #: 审内容后拒收的理由（`status == "rejected"` 时必须非空）。
    reject_reason: str = ""
    #: 迁移结算清空该槽的时刻与理由（`status == "cleared"` 时两者都必须非空）。
    cleared_at: str = ""
    clear_reason: str = ""
    #: 重叠度高时调用方给的"本次检索要的新内容"。
    new_content: str = ""
    overlap_score: float | None = None
    overlap_kind: str = ""
    overlap_with: str | None = None
    #: 调用方对"重叠也可以收"的显式声明（`None` = 没表态）。它不替代 `new_content`：
    #: 真正的放行判据在 `litstage.admit`，这里的值只如实记下"谁来电话说过可以收"。
    overlap_ok: bool | None = None
    #: ——— 委托认领（AL-11，2026-11-19）———
    #:
    #: 一次委托的待裁行由哪一个 A 实例认领着：`claimed_by` = actor（实例级，
    #: `agent-A-<名册名>`），`lease_until` = 租约到期时刻（与 `search_requests` 同一套
    #: `store.make_lease` / `store.lease_expired` 语义）。三个都空 = 没人认领
    #: （老行 / 还没认领过）—— 与 `search_requests` 的领取同形，不另造一套互斥。
    #: 为什么落在候选行上：委托级认领必须有一个**行上的**落点（只写事件的话，两个 A
    #: 同时进来时盘上没有任何互斥，二者都「认领」同一批委托）。
    claimed_by: str = ""
    lease_until: str | None = None
    claimed_at: str = ""

    def validate(self) -> None:
        require_id(self.slot, "slot")
        if not isinstance(self.batch, int) or isinstance(self.batch, bool) or self.batch < 1:
            raise ValueError(f"batch 必须是 >= 1 的整数（第几批），收到 {self.batch!r}")
        if not str(self.request_id or "").strip():
            raise ValueError(
                f"槽位 {self.slot} 没有 request_id —— 待新增列表按**委托**重置（业主 2026-10-20 "
                "第 1 条）：没有委托号的行会与下一次委托串在一起，而「串了」没有任何东西会报错"
            )
        require_process_id(self.request_id, "request")
        if self.status not in CANDIDATE_STATUSES:
            raise ValueError(
                f"status 必须是 {CANDIDATE_STATUSES} 之一，收到 {self.status!r}。"
                "拼错的后果与 download.status 同族：下游按这个字符串决定「还能不能动这一槽」，"
                "而错拼只会静默地把它当成一个不认识的态"
            )
        if not str(self.title or "").strip():
            raise ValueError(
                "title 不能为空 —— 撤掉的槽位**保留**题名，正是「记下删掉了哪一篇」的落点；"
                "空题名的空槽位等于一条查不出内容的记录"
            )
        if self.type_code and self.type_code not in LIT_TYPES:
            raise ValueError(f"type_code 必须是 {LIT_TYPES} 之一，收到 {self.type_code!r}")
        if self.reason_code and self.reason_code not in CANDIDATE_REASON_CODES:
            raise ValueError(
                f"reason_code 必须是受控取值 {CANDIDATE_REASON_CODES} 之一或空串，"
                f"收到 {self.reason_code!r} —— 报告里的理由只认受控取值（不许自由发挥）"
            )
        if self.status == "withdrawn" and not str(self.withdrawn_reason or "").strip():
            raise ValueError(
                f"槽位 {self.slot} 标了 status='withdrawn' 却没有 withdrawn_reason —— "
                "撤掉必须写清为什么（否则「空槽位」与「从来没这一条」在盘上同形）"
            )
        if self.status == "rejected" and not str(self.reject_reason or "").strip():
            raise ValueError(
                f"槽位 {self.slot} 标了 status='rejected' 却没有 reject_reason —— "
                "拒收必须写清为什么（业主口径：拒收要写理由）"
            )
        if self.status == "qualified":
            # 2026-11-16（Q1）：判收但**还没注册**。两条一起守：
            #   `relevance` 非空 —— 判过的证据就是那一句（与 `judged_state` 同一口径）；
            #   `lit_id` 空 —— 有资格 ≠ 有号；带号就说明注册已经发生了，
            #   那一行必须是 `admitted`。两个字段都留空会让"判收"与"没判"在盘上同形。
            if not str(self.relevance or "").strip():
                raise ValueError(
                    f"槽位 {self.slot} 标了 status='qualified' 却没有 relevance —— "
                    "判收必须写得出「为什么与本次检索相关」（否则与「没判过」同形）"
                )
            if str(self.lit_id or "").strip():
                raise ValueError(
                    f"槽位 {self.slot} 标了 status='qualified' 却带着 lit_id —— "
                    "判收不注册：号是提交那一刻才发的，带号的行必须是 status='admitted'"
                )
        if self.status == "admitted" and not str(self.lit_id or "").strip():
            raise ValueError(
                f"槽位 {self.slot} 标了 status='admitted' 却没有 lit_id —— "
                "入库必须指得出 literature 里的那一行（否则「入库了」是一句无法核对的话）"
            )
        if self.status == "cleared":
            if not str(self.cleared_at or "").strip():
                raise ValueError(
                    f"槽位 {self.slot} 标了 status='cleared' 却没有 cleared_at —— "
                    "「清空」是一次有时间的收尾动作，没有时刻的 cleared 与「没处理过」同形"
                )
            if not str(self.clear_reason or "").strip():
                raise ValueError(
                    f"槽位 {self.slot} 标了 status='cleared' 却没有 clear_reason —— "
                    "清空也要说清为什么（配额满了 / 没审完），否则报告里那一行说不出理由"
                )
        if self.lit_id:
            require_id(self.lit_id, "lit_id")
        if self.overlap_score is not None:
            s = float(self.overlap_score)
            if not (0.0 <= s <= 1.0):
                raise ValueError(f"overlap_score 是比率口径（0..1），收到 {self.overlap_score!r}")
        if self.overlap_ok is not None and not isinstance(self.overlap_ok, bool):
            raise ValueError("overlap_ok 必须是 bool 或 None")

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
    #: 为什么不直接删行：删掉就无法审计"当初为什么认为它们是同一个"。
    #: 保留 + 指向 survivor，既让下游能过滤（`merged_into is None` 才是活节点），
    #: 又留下了合并决策的完整轨迹。
    merged_into: str | None = None
    #: 合并理由（由 B 给出，人可读）。`merged_into` 非空时它必须非空 ——
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
        _problems = _set_problems("related_concepts", self.related_concepts)
        if _problems:
            raise ValueError("；".join(_problems))
        if self.concept_id in self.related_concepts:
            raise ValueError("related_concepts 不能包含自身")
        for r in self.related_concepts:
            require_id(r, "related_concepts[]")

    def to_dict(self) -> dict:
        return asdict(self)


#: 「这条引文是怎么回验通过的」：回验不要求呆板的逐字相同，语义相同也算通过。
#: 两栏的分工，别混成一件：
#:
#: - `quote_verified`：三态结论（`True` 通过 / `False` 不一致 / `None` 还没查）；
#: - `quote_mode`：通过的方式 ——
#:   `verbatim` = 逐字命中（`quoteverify.check_quote` 那一档，不花模型钱，先走它）；
#:   `semantic` = 语义判定（交给 H：引文与来源说同一件事即通过，允许改写、换记号、
#:   跨语言；"结论强于引文"仍判不通过）。
#:
#: 两栏不许互相冒充：`quote_verified is True` 而 `quote_mode` 说不出方式的行按没查算
#: （`evidencebits.quote_state()` 是这条口径的唯一实现）。`validate()` 会把
#: "只说了通过、没说方式"的行记实成 `verbatim`，但只在 `quote_span` 非空时；反过来，
#: 没通过/还没查的行，方式一律归空串（方式对它没有意义）。
#:
#: 为什么还要求 `quote_span` 非空：区间是"核了哪一段、在第几页"的唯一载子，没有它，
#: `verbatim` 这个字在盘上只是一句自我描述，读侧会当成逐字通过。区间为空 ⇒ 方式记空串，
#: 由读侧 `evidencebits.quote_state` 读成 `no_evidence`，由 `closing` 那一格点名。
QUOTE_MODES: tuple[str, ...] = ("verbatim", "semantic")


def _normalize_quote_mode(obj: Any, *, what: str) -> None:
    """把一行的 `quote_verified` / `quote_mode` 两栏摆成自洽的一对（就地改写）。

    三条，逐条对应 `QUOTE_MODES` 那段 docstring 的口径：

    1. `quote_verified is True` 而 `quote_mode` 空 ⇒ 有区间才记实成 `verbatim`；
       区间为空就记空串（不许盖成 `verbatim`）；
    2. 不是 `True`（`False` / `None`）⇒ 方式一律归空串：方式对"没通过/还没查"没有意义，
       留着会让人误读成"用某种方式查过了"；
    3. 认不出的词 ⇒ 抛错（词表外的值不许进库；两栏不许互相冒充这条靠它兜住）。
    """
    verified = getattr(obj, "quote_verified", None)
    mode = str(getattr(obj, "quote_mode", "") or "")
    if verified is True and mode == "":
        # 空方式只在拿得出区间时才记实成逐字档。
        # 这一格是"写侧唯一会给 mode 补值的地方"，补错了就是把一句自报升成结论：
        # 区间为空时保持空串，让读侧按 no_evidence 读（而不是读成正好在那一档的 verbatim）。
        span_now = str(getattr(obj, "quote_span", "") or "").strip()
        mode = "verbatim" if span_now else ""
    if verified is not True and mode != "":
        mode = ""
    if mode != "" and mode not in QUOTE_MODES:
        raise ValueError(f"{what} 的 quote_mode 必须是 {QUOTE_MODES} 之一或空串，"
                         f"收到 {mode!r}（引文回验只有'逐字命中'与'语义相同'两档）")
    obj.quote_mode = mode
    # 语义那一档要求证据：对着哪一段原文、哪一次调用判的，
    # 两样都要落在行上 —— 否则"语义相同"就是一句谁都能说的话。
    if mode == "semantic":
        span = str(getattr(obj, "quote_span", "") or "").strip()
        call = str(getattr(obj, "quote_call_sha256", "") or "").strip()
        if not span or not call:
            raise ValueError(
                f"{what} 标了 quote_mode='semantic'，但"
                + ("缺 quote_span（来源那一段逐字正文）" if not span else "")
                + ("；" if not span and not call else "")
                + ("缺 quote_call_sha256（那次语义判定的调用记录）" if not call else "")
                + " —— 语义那一档必须留证据：说不出对着哪一段、哪一次判的，就不算通过")


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
    #: 这条引文是怎么回验通过的（`QUOTE_MODES` 之一，或空串 = 没有方式可言）。
    quote_mode: str = ""
    #: 为什么这么判（人话；语义那一档就是 H 的判定理由）。
    quote_reason: str = ""
    #: 语义那一档的证据：
    #: `quote_span` 是来源里那一段逐字取来的正文，`quote_call_sha256` 是那次模型调用的
    #: 提示词指纹（可复查的调用记录）。两条都由 `_normalize_quote_mode` 在
    #: `quote_mode="semantic"` 时要求非空 —— 说不出"对着哪一段、哪一次判的"，
    #: 就不算语义通过（这是"两栏不许互相冒充"在内容上的那一半）。
    quote_span: str = ""
    quote_call_sha256: str = ""
    statement: str = ""
    concept_group_key: str = ""
    dedup_key: str = ""
    status: str = "active"
    duplicate_of: str | None = None
    created_at: str = ""
    #: 这条关系正式并进概念图的时刻。
    #:
    #: 与 `created_at` 的区别（这一格存在的全部理由）：`created_at` 是"这一行什么时候
    #: 建出来的"（任何行都有，包括还没并进去的 `suspect` / `rejected`），
    #: 而 `merged_at` 回答的是旧标准里那一格问的问题 —— "这条边是哪天进来的"。
    #: 两段式写路径（先起草、后并入）里两者不同；今天的主路径一趟写一行，
    #: `status == "active"` 时两者相等 —— 但读的人不必再去猜"`created_at` 是不是并表时间"。
    #:
    #: 空串那一档要按 `status` 读（三态纪律）：
    #: `status in ("suspect", "rejected")` 且空串 ⇒ 还没并进图；
    #: `status == "active"` 且空串 ⇒ 并表时间未知（旧行没有这一格），
    #: 不是"没并进去"——它已经在图里了。把这两者折成一个空串会让
    #: "老数据没有这一格"看起来像"这些边没并进图"。
    merged_at: str = ""
    #: 本条关系还引用了哪些文献（除主引文 `lit_id` 之外）。
    #:
    #: 为什么必须有这个字段：数学上一条关系常常由两篇文献共同支持
    #: （例如"K(m) 与 S̃_m 同谱"需要一篇给 K(m) 的谱、另一篇给 S̃_m 的谱）。
    #: 只有 `lit_id` 时，第二篇支持文献无处可写，于是依赖集无法闭合 ——
    #: 而依赖集不闭合正是"把引用的定理当成自己的定理"的技术根源（FC-23）。
    supporting_lit_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        require_id(self.relation_id, "relation_id")
        require_id(self.lit_id, "lit_id")
        if len(self.concept_ids) < 2:
            raise ValueError("概念代号组至少要有 2 个概念")
        _problems = _set_problems("concept_ids", self.concept_ids)
        if _problems:
            raise ValueError("；".join(_problems))
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
        _normalize_quote_mode(self, what=f"relation {self.relation_id}")
        # 并表时间与状态必须自洽（一处判据，别让读者自己去猜空串的含义）
        if self.merged_at and self.status != "active":
            raise ValueError(
                f"relation {self.relation_id} 标了 merged_at={self.merged_at!r} 而 "
                f"status={self.status!r}：只有 active 的关系才算'并进了概念图'"
                "（suspect/rejected 留着这一格会让'哪天进来的'读出一个不存在的时刻）")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_range"] = self.page_range.to_dict()
        return d


# ---------------------------------------------------------------- C/D 新增：受控词表

#: C 的分析报告类型（`analysis_reports.kind` 的受控词表）。
#: 前四档是需求里的四类分析、与需求一一对应；第五档 `proof_chain` 是证明链路径分析
#: （`agent_c/proof_chain.py` 的 `_report("proof_chain", …)`）。2026-11-20 并入：
#: 改前它产出的 kind 不在本词表里 ⇒ `_report` 的"产出即登记"分支恒不命中，同族分析器
#: 里唯一一个只活在返回值里的报告（`tests/test_wireup_residue.py` 钉住它今天登记得成）。
REPORT_KINDS = ("hottest", "paths", "cold", "gaps", "proof_chain")

#: D 的研究问题状态机（DESIGN-TOOLS.md §4.1）：
#:   open            —— 刚提取出来，尚未评估证据
#:   needs_evidence  —— 已判定证据不足，且已向 A 提交查询请求（在等）
#:   researching     —— 证据就绪，正在研究
#:   answered        —— 已给出结论
#:   dropped         —— 评估后判定不值得研究（要写理由，不许静默丢弃）
QUESTION_STATUSES = ("open", "needs_evidence", "researching", "answered", "dropped")

#: 矛盾闭环（I2）的裁决词表。四态而非三态，因为 "persistent" 与
#: "unresolved" 的下游动作完全不同：前者要人来看并停止追问，后者还要再来一轮。
#: 把它们合并成一个词，就等于把"该停了"和"继续"混为一谈。
CONTRADICTION_VERDICTS = ("resolved", "unresolved", "new_contradiction", "persistent")

#: 研究问题的驱动类型（I2）。见 `ResearchQuestion.kind`。
QUESTION_KINDS = ("gap", "contradiction")

#: 猜想的状态。
#:
#: 为什么不复用 `QUESTION_STATUSES` 的 `answered`：问题由"查明"了结，猜想由
#: "证明或否证"了结 —— 同一个词同时意味着两件事，正是本仓反复禁止的形态。
CONJECTURE_STATUSES = ("proposed", "needs_evidence", "testing", "supported_not_proved",
                       "refuted", "proved", "promoted", "known_in_literature", "withdrawn")

#: 猜想的形态受控词表（写进 `form`）。
CONJECTURE_FORMS = ("universal", "existential", "identity", "bound", "structural")

#: 猜想必须是可检验的陈述句：疑问句由下面的 `CONJECTURE_QUESTION_MARKS` +
#: `CONJECTURE_QUESTION_PATTERNS` 判（唯一入口 `looks_like_a_question()`，
#: `Conjecture.validate` 与工具层拒信都调它）。
#:
#: 旧做法是"出现 谁 / 什么 / which / what 这些词就算问题"。按子串匹配会误伤普通陈述句
#: 里的 `which`/`what`（定义句 "…in which every edge …" 会被拒，`somewhat` 含 `what` 也会），
#: 于是"猜想的可检验形式"那一步整条落不了库 —— 那张词表因此退役（零调用，已删）。

#: 疑问句的字面标记（出现在任何位置都算 —— 它们几乎只在问句里出现，
#: 且不会像 `which` 那样嵌在数学术语里）。`?`/`？` 单列在这里而不是当正则，
#: 因为它本身是正则元字符（写成 `?` 会以 `re.error` 收场）。
CONJECTURE_QUESTION_MARKS = ("?", "？", "是否", "吗")

#: 疑问句的形态（正则；只认句首的疑问词/助动词，不认"出现在任何位置"）：
#: `Which graphs …` / `What is …` / `Is there …` / `哪些 (m,k) …`。
CONJECTURE_QUESTION_PATTERNS = (
    r"^\s*(谁|什么|哪些|哪类|如何|怎么|为什么)",
    r"(?i)^\s*(which|what|whether|who|whom|whose|when|where|why|how)\b",
    r"(?i)^\s*(is|are|does|do|can|could|should|would|will|has|have)\b",
)


def looks_like_a_question(text: str) -> list[str]:
    """这句话读起来是不是一个问题？返回命中的形态（空列表 = 是陈述句）。

    判据只有一份：`Conjecture.validate` 与工具层的拒信都调它 —— 拒信里要能把
    "你为什么被拒"说清，不可操作的拒信只会让调用方反复猜。
    """
    import re as _re

    hits: list[str] = []
    body = str(text or "")
    for mark in CONJECTURE_QUESTION_MARKS:
        if mark in body:
            hits.append(mark)
    for pat in CONJECTURE_QUESTION_PATTERNS:
        # 形态表是自己写的：写坏了要当场炸，不许悄悄变成"命中"（那会拒掉所有猜想）
        # 也不许悄悄变成"没命中"（那会让问题句混进猜想台账）。
        if _re.search(pat, body):
            hits.append(pat)
    return hits

#: 定向重抽取（I4）的原因词表。受控词表而非自由文本，理由同 DOWNLOAD_STATUSES：
#: B 靠这个字符串决定该怎么重做，拼错会静默走错分支。
REPROCESS_REASONS = (
    "quote_unverifiable",  # 引文逐字校验失败 → 回全文找等价表述
    "low_information",  # 描述过短/信息量低 → 回该页附近抽更完整的陈述
    "need_context",  # D 要该关系所在段落的完整语境
    "structural_duplicate",  # I5：C 提出结构重复，请 B 复核是否合并
)

#: 重抽取请求的生命周期。
#:   pending    —— 已提交，B 还没处理
#:   done       —— B 处理完（结果写进 result，可能仍是"没找到"）
#:   rejected   —— 被闸门拒绝（超限 / 目标不存在 / 原因非法）
REPROCESS_STATUSES = ("pending", "done", "rejected")


@dataclass
class ReprocessRequest:
    """定向重抽取请求（DESIGN-INTERACTIONS.md §1 I4）。

    为什么不复用 `search_requests`：语义根本不同 —— 搜索请求是"去外面找新东西"，
    重抽取是"把已有的东西重新看一遍"。混在一张表里会让"A 的产能统计"
    把不消耗网络的本地工作也算进去，配额就失去意义。

    它不是"把 `processed` 置回 false"。那会触发全量重抽，是幂等陷阱。
    必须带目标（`relation_ids`），B 只在该目标上工作。
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
    #: 处理结果。三态纪律：`status="done"` 但 `result="not_found"` 是有效结论，
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
        # 与 `SearchRequest.validate` 同一条判据（前缀是 p-）。
        require_process_id(self.reprocess_id, "reprocess")
        if self.reason not in REPROCESS_REASONS:
            raise ValueError(f"reason 必须是 {REPROCESS_REASONS} 之一，收到 {self.reason!r}")
        if self.status not in REPROCESS_STATUSES:
            raise ValueError(f"status 必须是 {REPROCESS_STATUSES} 之一，收到 {self.status!r}")
        if not self.relation_ids:
            raise ValueError(
                "relation_ids 不能为空 —— 无目标的重抽取会退化为全量重抽（I4 的幂等陷阱）"
            )
        _problems = _set_problems("relation_ids", self.relation_ids)
        if _problems:
            raise ValueError("；".join(_problems))
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
    #: 已提交给 A 的查询请求。这是"D 继续思考"能自动接上的唯一依据：
    #: 没有它就无法判断"新来的文献是不是我等的那个"。
    waiting_request_ids: list[str] = field(default_factory=list)
    gap_reason: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    #: 问题类型（I2）。`"gap"` = 缺口驱动；`"contradiction"` = 矛盾驱动。
    #:
    #: 为什么必须显式区分而不是靠 origin 字符串前缀：两者的收敛条件不同
    #: （缺口靠"证据相关即为就绪"，矛盾靠"裁决 resolved/persistent"），
    #: 且矛盾有轮数上限。靠解析 origin 的字符串格式来决定生命周期，
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
    #: 保序的关系代号链（FC-05）。与 `related_relation_ids` 是一对：
    #: 后者是集合（引用了哪些知识，升序去重、可比较、可判重），
    #: 本字段是序列（按什么顺序走的 —— 推理路径本身）。
    #:
    #: 为什么必须成对存在：只有集合字段时，"跳序"（A→C→B 与 A→B→C 的区别）
    #: 会被 `sorted(set(...))` 静默吃掉，只能从 `origin` 字符串反解。
    #: 顺序是数学论证的一部分，它不是"同一集合的另一种写法"。
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
            _problems = _set_problems("contradiction_relation_ids",
                                      self.contradiction_relation_ids)
            if _problems:
                raise ValueError("；".join(_problems))
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
            _problems = _set_problems(f, vals)
            if _problems:
                raise ValueError("；".join(_problems))
        for cid in self.related_concept_ids:
            require_id(cid, "related_concept_ids[]")
        for rid in self.related_relation_ids:
            require_id(rid, "related_relation_ids[]")
        # `relation_chain` 是序列：只校验元素合法，不许排序去重
        # （排序会把推理路径改成另一条路径）。它的"保序"由 round-trip 测试守。
        for rid in self.relation_chain:
            require_id(rid, "relation_chain[]")
        chain_extra = set(self.relation_chain) - set(self.related_relation_ids)
        if self.relation_chain and chain_extra:
            raise ValueError(
                "relation_chain 含 related_relation_ids 里没有的代号 "
                f"{sorted(chain_extra)} —— "
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
class Conjecture:
    """一条猜想。

    ## 为什么它是独立对象，而不是 `research_questions` 的一个 kind：
    1. 会撞既有不变量 —— `ResearchQuestion` 的 `status="needs_evidence"` 必须带非空 `waiting_request_ids`
       （D 的循环靠它接上），而猜想等的是实验，没有检索请求可等；
    2. 命题不是问题 —— 问题由"查明"了结，猜想由"证明或否证"了结，共用一个 `answered` 会让同一个词意味着两件事。
    ## 状态机（`CONJECTURE_STATUSES`）：`proposed` → `testing` → （`supported_not_proved` | `refuted` |
    `proved`）→ `promoted`；另有 `needs_evidence`（提不出可检验形式）、`known_in_literature`（别人证过，
    带文献）、`withdrawn`（撤下，必须写理由）。`validate()` 只写"每条状态必须带什么"这类单行内可判的拒收
    条件；跨对象的判据（升格必须挂 proof 实验、被引用的猜想不许硬删）在 `verify.verify_all` 里 —— 两处分工的
    理由：schema 管一行，verify 管一库。
    """

    conjecture_id: str
    #: 命题本体：必须是一条可判真假的陈述句（含疑问词即拒收）。
    statement: str
    #: 否命题（可空）：给"否证"一个明确的对象。
    negation_statement: str = ""
    #: 受控词表 `CONJECTURE_FORMS`。
    form: str = "universal"
    #: 可检验形式：`{"params": {...}, "bounds": {...}, "why": "..."}`。空 ⇒ 只能落 `needs_evidence`。
    testable: dict = field(default_factory=dict)
    #: 必填：从哪来（report_id / `rel:NNNN` / gap / `lit:NNNN`）。防"凭空出现的猜想"。
    origin: str = ""
    #: 受控词表 `CONJECTURE_STATUSES`。
    status: str = "proposed"
    #: 检验过它的实验（升序去重）。
    experiment_ids: list[str] = field(default_factory=list)
    #: 仅 `method="formal"` 且 `evidence_kind="proof"` 的实验。
    proof_experiment_id: str = ""
    #: 反例所在的实验（`result="refutes"`）。
    counterexample_experiment_id: str = ""
    #: 被拒那一档的第二条证据：谁拒了它（业主 2026-11-13 裁定 ②）。
    #:
    #: 取值形态：V 的 `verifications/<命题号>.jsonl#v-00000N`，或 B 的
    #: `b-refusal:<受控码>#<手稿/命题>`。与 `counterexample_experiment_id` 并列：
    #: 一条猜想被判死有两条真实的来路 —— 跑出了反例，或被判死了（V 判「有毛病」/
    #: B 拒收）。只认前一条会让第二种在台账上永远停在"还没验"；只认后一条会让一次
    #: 没跑成的实验变成一次判决。两条都空 ⇒ `refuted` 拒收。
    #:
    #: 为什么是"多一格可选字段"而不是新状态档：`CONJECTURE_STATUSES` 是受控词表，
    #: 加一档等于放宽一整根轴（`AGENTS.md` 的 FC-27 一节）；而"被拒"本来就是 `refuted`
    #: 的一条来路，缺的只是它的证据格。加可选字段不动磁盘格式契约
    #: （`row_from_dict` 按 dataclass 字段过滤 ⇒ 老行缺这一格取空默认值，不抬
    #: `SCHEMA_VERSION`；同族先例见 `Literature.pages`）。
    refusal_ref: str = ""
    #: 升格落点：`{"kind": "document_claim", "id": "..."}`。
    promoted_to: dict = field(default_factory=dict)
    #: 别人已经证过时的文献代号（"别人证过"与"我们证过"是两件事）。
    known_lit_id: str = ""
    #: 撤下理由（`status="withdrawn"` 时必填，不许静默消失）。
    withdraw_reason: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "agent-D"
    #: 最后一个把这一行写成现在这个样子的人（SH-10，2026-11-19）。
    #:
    #: 知识实体按规范化正文归并是对的（同一条命题只有一行），但"谁把它推到 refuted"
    #: 必须答得出来：`experiment_ids` 只说得出是哪几条实验，说不出是哪一支笔。
    #: `created_by` 是创建者（会被并进来的第二笔覆盖掉才叫错），这一格每次写都更新；
    #: 空串 = 加这一格之前的老行（读侧按"没记"处理，不折成创建者）。
    updated_by: str = ""

    def validate(self) -> None:
        """单行内可判的拒收条件（跨对象判据在 `verify.verify_all`）。

        每一条对应状态机里的一句"禁止的读法"：把"没检验"与
        "检验过没结论"与"检验过有支持"与"检验过被否证"分开，不许折叠。
        """
        require_id(self.conjecture_id, "conjecture_id")
        # ---- 一次把问题说齐：先收集，再一次抛 ----
        # 逐条顺序抛会让调用方走四轮才凑齐一条猜想的字段：
        #   form 词表 → status/proposed 要 testable → testable 要对象 → needs_evidence 要 notes。
        # 真实智能体会在这里困惑并浪费 token。与 B（`register_statement`）/ F（`create_plan`）两处逐字同形：
        # 只有一条问题时原文案一字不动；多于一条时补一行整份清单。
        _probs: list[tuple[str, str]] = []          # (短标签, 原文案)
        if not self.statement.strip():
            _probs.append(("statement", "statement 不能为空：猜想必须是一条可判真假的陈述句"))
        bad = looks_like_a_question(self.statement)
        if bad:
            _probs.append(("statement(疑问句形态)", (
                f"statement 读起来是个问题（命中形态 {bad}）⇒ 它是问题而不是猜想。"
                "猜想必须是可判真假的陈述句（问题走 research_questions）：把疑问句改写成断言 —— "
                "例如「哪些 (m,k) 有无穷多例子？」改写为「对每个 m ≥ 5，k = 3 都有无穷多个 …」。"
                "注意：普通陈述里的 which / what 不算问题（从句里出现它们是正常的），"
                "判据看的是句首疑问词与问号")))
        if self.form not in CONJECTURE_FORMS:
            _probs.append(("form", f"form 必须是 {CONJECTURE_FORMS} 之一，收到 {self.form!r}"))
        if self.status not in CONJECTURE_STATUSES:
            _probs.append(("status", f"status 必须是 {CONJECTURE_STATUSES} 之一，收到 {self.status!r}"))
        if not self.origin.strip():
            _probs.append(("origin", "origin 必填：猜想的来源必须可追"
                                     "（report_id / rel:NNNN / gap / lit:NNNN）"))
        if self.status == "proposed" and not self.testable:
            _probs.append(("testable", "status=proposed 时必须给 testable（可检验形式）；"
                                       "给不出就落 needs_evidence"))
        if self.status == "needs_evidence" and not (self.notes.strip() or self.withdraw_reason.strip()):
            _probs.append(("notes", "status=needs_evidence 时必须写清为什么提不出可检验形式"
                                    "（notes 或 withdraw_reason）"))
        if self.status == "supported_not_proved" and not self.experiment_ids:
            _probs.append(("experiment_ids", "status=supported_not_proved 时必须记至少一条检验过它的实验"))
        if self.status == "refuted" and not (self.counterexample_experiment_id.strip()
                                             or self.refusal_ref.strip()):
            _probs.append(("counterexample_experiment_id", (
                "status=refuted 时必须给 counterexample_experiment_id（反例来自一次实验）"
                "或 refusal_ref（谁拒了它：V 的 `verifications/<号>.jsonl#v-…` / B 的 "
                "`b-refusal:<受控码>#…`）—— 两条并列，缺一不可；"
                "inconclusive 不得转 refuted")))
        if self.status == "proved" and not self.proof_experiment_id:
            _probs.append(("proof_experiment_id", "status=proved 时必须给 proof_experiment_id"))
        if self.status == "promoted" and not (self.proof_experiment_id
                                              and str(self.promoted_to.get("id") or "").strip()):
            _probs.append(("promoted_to.id", "status=promoted 时必须同时有 proof_experiment_id 与 promoted_to.id"
                                     "（升格要有证据与落点）"))
        if _probs:
            _head = _probs[0][1]
            if len(_probs) > 1:
                _head += ("　**这一条还差**：" + "、".join(label for label, _ in _probs)
                          + " —— 一次给齐就不用再来回问。")
            raise ValueError(_head)
        if self.status == "known_in_literature" and not self.known_lit_id.strip():
            raise ValueError(
                "status=known_in_literature 时必须给 known_lit_id：别人证过与我们证过是两件事"
            )
        if self.status == "withdrawn" and not self.withdraw_reason.strip():
            raise ValueError("status=withdrawn 时必须写 withdraw_reason（撤下不许静默消失）")
        _problems = _set_problems("experiment_ids", self.experiment_ids)
        if _problems:
            raise ValueError("；".join(_problems))
        for eid in self.experiment_ids:
            require_id(eid, "experiment_ids[]")
        for name in ("proof_experiment_id", "counterexample_experiment_id"):
            val = getattr(self, name)
            if val:
                require_id(val, name)
        if self.known_lit_id:
            require_id(self.known_lit_id, "known_lit_id")

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

#: `experiments` 的方法词表。这张表的口径是「机器核验与实验台账」，收两类账：
#:   numeric            —— 浮点数值计算（采样、BFS、特征值）；E 写
#:   symbolic           —— 符号计算（精确代数）；E 写
#:   exhaustive_search  —— 在有限范围内穷举；E 写
#:   formal             —— formal（Lean 核验），交给证明检查器核验；L 写
#:
#: L 的形式化行不新开一张表，就落在本表里 —— `method="formal"` 是口径如此，
#: 不是把 Lean 核验当成数值实验。
EXPERIMENT_METHODS = ("numeric", "symbolic", "exhaustive_search", "formal")

#: 证据等级（FC-22 落地核心）：proof（形式化检查器核验过，或穷举程序把整个命题证掉了）·
#: proof_review（`proof_text` 非空 ＋ V 签「成立」；不是机器检查 ⇒ 必须自带 disclaimer，是"没有 Lean 也要能写
#: 论文"的落点）· cross_check（数值/穷举交叉验证，不构成证明，报告必须自动附这句话）· heuristic（最弱）。
#: 穷举那一档的凭据是程序脚本 + 搜索空间 + 覆盖说明（`proof_reason="exhaustion"`，判据在
#: `numericproof.exhaustion_problems`）：纯数值实验把整个命题证掉时也拿 proof，签字由 V 签、
#: ②③ 由 E 写。计算类仍然拿不到"随手的" proof —— 没有程序脚本与覆盖说明就没有这一档。
#: 强制三处：`verifications.proof_review_gap`（判据本体：最后一签「成立」且 `proof_sha256` 对得上现在这一版）·
#: `store._refuse_fake_proof_review`（写入期当场拒收，`proof_review_without_evidence`）· `verify._check_13` 的
#: `proof_review_without_verification`（审计期 error，逐条点名存量）。
#: 反方向也是缺陷：够这一档却把 `evidence_kind` 写得更弱 ⇒ `_check_13` 报 `weaker_than_evidence`（warning，
#: 判据本体 `verifications.weaker_than_evidence_gaps`）；有 `proof_text` 且有那一签 ⇒ 就该落这一档。
EVIDENCE_KINDS = ("proof", "proof_review", "cross_check", "heuristic")

#: `experiments` 表能用的证据等级（比 `EVIDENCE_KINDS` 少 `proof_review`）。
#:
#: 为什么实验表不许用它：`proof_review` 说的是"一份证明被逐行审阅过"，
#: 而实验表登记的是一次实验（脚本 / 检查器）的结论。让一行实验去声称
#: `proof_review`，等于把"审阅"这件事从 `verifications/<命题号>.jsonl`（文件账本，不是表）
#: 搬到一个没有审阅信息的字段里 —— 于是"谁审的、审的是哪一版"就再也读不出来了。
EXPERIMENT_EVIDENCE_KINDS = ("proof", "cross_check", "heuristic")

#: 一次实验对被检验命题的结论。
EXPERIMENT_RESULTS = ("supports", "refutes", "inconclusive")

#: 实验行的状态（`Experiment.status`）。只有两档：仍有效 / 已撤销。
#:
#: 撤销不是删行：`store` 的删除会让读者连「这一条曾经算数」都看不见，而课题台账要的
#: 正是「哪一条还算数、为什么不算了」。所以撤销是两档状态加四条留痕（谁 / 何时 /
#: 为什么 / 换成哪一份脚本）。
#: 为什么复用 `active` / `voided` 这两个词：`STATEMENT_STATUSES` 与 `evidencebits`
#: 的作废载荷（`bits.voided_by`）已经在用这一族词，同一件事不许有两个说法。
EXPERIMENT_ACTIVE = "active"
EXPERIMENT_VOIDED = "voided"
EXPERIMENT_STATUSES = (EXPERIMENT_ACTIVE, EXPERIMENT_VOIDED)

#: 撤销实验行的受控理由码（`Experiment.void_reason_code`）。
#:
#: 今天只有一档：脚本改了 —— 同一个 `code_path` 上挂着 `code_hash` 不同的两行时，
#: 页面上只报「代码不一致」，两条并列挂着，读者无从判断哪一条还算数。
#: 为什么是受控词表而不是自由文本：理由是机器可判的那一半（判据逐字钉
#: `code_changed`），而「为什么撤」那句人话另有 `void_reason` 一栏。
#: 加一档 = 加一种「老登记不再算数」的合法理由，必须先有人裁定。
VOID_REASON_CODE_CHANGED = "code_changed"
VOID_REASON_CODES = (VOID_REASON_CODE_CHANGED,)


def experiment_is_voided(row: Any) -> bool:
    """这一行实验是不是已经撤销（读侧唯一判据）。

    为什么读侧也要一个函数：`tools.verify_tools.evidence_for`（读数）与
    `closing._leg_reading` 的验收档必须用同一个谓词问「这条还算不算证据」——
    两处各写一份，口径一分家就没有任何测试能看见，而读者会同时看到两个数。
    `None` / 非对象一律按「没撤销」读；`status` 缺席的行同理（缺这一列 ⇒ 按有效行读）。
    """
    if not isinstance(row, dict):
        return False
    return str(row.get("status") or "") == EXPERIMENT_VOIDED


def active_experiment_rows(rows: Iterable[Any]) -> list[Any]:
    """从一批实验行里滤掉已撤销的那些（顺序不变）。"""
    return [row for row in rows if not experiment_is_voided(row)]


def experiment_void_reason(*, code_hash_from: Any, code_hash_to: Any) -> str:
    """脚本改了那一档的撤销理由（逐字格式的唯一出处）。

    格式是「脚本 <旧 sha 前 16 位> → <新 sha 前 16 位>」：十六进制串不截成八位那种
    半截哈希（既不能核也不能读），而 16 位足够在同一台账里分清两份脚本。
    为什么要有这个函数：写侧（`agent_e.run_experiment`）与 `validate` 的判据都要
    这一句，两处各拼一次就会有一处悄悄改了格式。
    """
    old = str(code_hash_from or "").strip()[:16]
    new = str(code_hash_to or "").strip()[:16]
    return f"脚本 {old} → {new}"

#: 三种否定必须分开（FC-25）。
#:
#:   disproved           —— 已证否（有可复现的反例）
#:   not_proved          —— 数值/穷举支持，但没有证明
#:   not_searched_here   —— 这个实验根本没做
#:   no_local_evidence   —— 做了，但本地拿不到能判定的证据
#:
#: 把"未证明"与"已证否"混起来在数学上是灾难；把"没搜索"与"搜了没有"混起来
#: 在本项目里已经踩过（`cold` 的"完全孤立"就是为此单独归一类）。
NEGATION_KINDS = ("disproved", "not_proved", "not_searched_here", "no_local_evidence")

#: F 的攻坚计划状态。
#:   open / attacking           —— 在推进
#:   supported_not_proved       —— 子目标都有数值支持，但没有任何形式化证明
#:   stalled                    —— 预算用尽仍未解决（不是失败，也不是成功）
#:   resolved / abandoned       —— 终局
#:
#: 2026-11-13 按业主裁定删掉 `progress`：`agent_f._derive_status` 从不返回它
#: （推进中的计划一律记 `attacking`），72 个工作区 0 行，读点只有 `AttackPlan.validate`
#: 的成员判断 ⇒ 它是一句「词表说有、代码永远给不出」的假承诺。教法面
#: （`ROLE-SPECS` 附录 §F.5 那张表里的「本轮有推进」一行）同批删除。
ATTACK_STATUSES = ("open", "attacking", "supported_not_proved", "stalled", "resolved", "abandoned")

#: 攻坚计划的终态：一旦到达就不再推进。
#:
#: 每一档都必须在列。漏一档的后果是：一个已达该状态的计划被 `pick_next_subgoal`
#: 当成活计划重新拾起，于是终止条件形同虚设 —— 而 `agent_f` 会真的写
#: `supported_not_proved`（"子目标都有数值支持，但没有任何形式化证明"）。
#:
#: 它是唯一来源：`attack_tools.TERMINAL_STATUSES` 就是这个名字的 import。
#: 之所以放进 `schema` 而不是工具层：这是领域状态的分类，数据层必须权威。
ATTACK_TERMINAL_STATUSES = ("resolved", "abandoned", "stalled", "supported_not_proved")

#: 攻坚子目标的状态。`supported_not_proved` 单独存在是 FC-22 的直接后果：
#: "有数值支持"绝不能被写成 `closed`。
SUBGOAL_STATUSES = ("todo", "in_progress", "supported_not_proved", "closed", "blocked", "dropped")

#: 子目标可以派给谁。角色即权限面，所以这是一个受控词表。
SUBGOAL_OWNERS = ("F", "A", "B", "C", "D", "E", "G")

#: G 的文档类型与状态。
#:
#: `reproduction_report` 已于 2026-11-13 按业主裁定删除（0 行 / 无读点 / 无写入口）：
#: 「独立复现报告」若真要做，要的是一个接线条目（谁产出、谁审、落在哪张表），
#: 而不是一条永远不可能出现的词表取值。
#:
#: `research`（2026-11-22 `A-0c-2` CONTRACT-DRESEARCH，业主授权"改硬契约先斩后奏"）：
#: **D 的研究稿**（`manuscripts/D/RESEARCH.md` / `manuscripts/D/<qid>-research.md`，
#: 写侧 `agent_d.write_report`）。为什么它是 `documents` 的一种、而不是新开一张表：
#:
#: 1. 它是**交付正文**（业主 2026-11-22：G 的论文要引它；同日的 D-DIR 裁定又说
#:    "过程笔记才是 `work/D/`"）—— 而"交付正文"在盘上就是 `documents` 那一行的语义
#:    （`markdown_path` 指向真文件 + `sections` + `claims` + `content_sha256`）；
#: 2. 它天然要 `claims[].citations`（D 的结论引 `rel:` / `lit:` / `stmt:` / `exp:`），
#:    而"没有引用的断言不许存在"（FC-02）正是 `documents.claims` 已经有的机械判据；
#: 3. `refvocab` 的 `doc:<号>` / `closing.document_rows` / G 的 `doc.build_document`
#:    （`doc:` 引用）都是现成读口 —— 新开一张表等于再造一套"稿子怎么被引用"。
#:
#: 代价（照实写，别让下一个人以为这是免费的）：它是**唯一**来源 ——
#: `specs/g.py` 与 `tools/doc_tools.py` 的工具面 enum 都从本元组派生，于是 G 的
#: `doc.build_document` / `doc.list_documents` 的可选 kind 多了一档（工具面 + golden
#: 快照同笔重生成）；D 的写集（`specs/d.py::SPEC.write_set`）里还没有 `documents`，
#: 本笔把写点落在 `doc_tools.record_research_report`（`documents` 的既有写通路）。
DOC_KINDS = ("survey", "paper", "note", "research")

#: D 的研究稿在 `documents.kind` 上的取值（**唯一**来源是上面那个元组）。
#:
#: 为什么不直接写字面量 `"research"`：读侧（`manuscriptretire` 的第五源、
#: `closing` 的读数、`agent_d` 的 S-07 读数）都要问"这一行是不是 D 的报告"。
#: 字面量散在四处时，改一个字就会让某处静默读成"不是"。
RESEARCH_DOC_KIND = "research"
assert RESEARCH_DOC_KIND in DOC_KINDS, "RESEARCH_DOC_KIND 必须真的在 DOC_KINDS 里"

DOC_STATUSES = ("draft", "in_review", "revised", "accepted", "rejected", "unresolved_review")

#: 一次审核的裁决。空串 = 还没审过。
#: 为什么单列一根轴：`status` 兼表"通过"，而"审过"与"通过"是完全不同的状态。
#: `reviewed_documents` 读这根轴；`accepted_documents` 读 `成立`。
#:
#: H 这一轴没有第三种结论：「看不出错」就是没毛病，而「看不出来」的意思是"这一轮没查成"。
#: 所以这里只剩三格（空串 + 两态）。旧行里可能残留「看不出来」：
#: 读侧一律折成「没查成」（checked=False + 一条「这是旧数据」的读数），
#: 不是「成立」，也不是「有毛病」—— 那两格都是查过之后的裁决，而「没查成」恰恰不是。
#: 读侧唯一入口是下面的 `read_review_verdict`；写侧只许写这里的三格。
REVIEW_VERDICTS = ("", "成立", "有毛病")

#: 旧行里可能残留、而写侧再也写不出的那一格（「看不出来」）。
#: 它只在读侧有意义：按「没查成」读（不是第三态，也不是「成立」）。
REVIEW_LEGACY_VERDICTS = ("看不出来",)


def read_review_verdict(row: Mapping[str, Any]) -> dict[str, Any]:
    """读 `documents` 行的审核轴 —— 这一格的唯一读口。

    返回 ``{"raw", "verdict", "checked", "legacy", "reason"}``。
    三态纪律落在这里：只有真裁决才 ``checked=True``；旧值 / 空串 / 词表外的值一律
    ``checked=False``，并给一条读得懂的理由（旧值那一条会写明「这是旧数据」）。

    ## 为什么旧值「看不出来」读成「没查成」，而不是「成立」

    V 那一轴的历史值按「成立（没找到缺陷）」读；H 这一轴不同：
    H 写下「看不出来」时说的是"这一轮我没查成"（缺材料 / 没跑），不是"我查了、没找到
    缺陷"。把它读成「成立」是最贵的折平 —— 没查过的东西变成一条通过裁决。所以这里
    折成 ``checked=False``，且 ``legacy=True`` 让读的人看得见"这条读数来自旧数据"，
    不许静默当成没审过。
    """
    raw = str(row.get("review_verdict") or "")
    if raw in REVIEW_LEGACY_VERDICTS:
        return {
            "raw": raw, "verdict": "", "checked": False, "legacy": True,
            "reason": (
                "旧数据：这一行的 review_verdict 是 2026-10-30 之前写下的「看不出来」，"
                "按「没查成」读（checked=False）—— 它不是「成立」（H 没查成不等于没找到缺陷），"
                "也不是「有毛病」；不计入「审过」，也不计入「通过」"
            ),
        }
    if raw == "":
        return {"raw": raw, "verdict": "", "checked": False, "legacy": False,
                "reason": "空串 = 这一行还没有审校裁决（没审过，不是「成立」）"}
    if raw not in REVIEW_VERDICTS:
        return {"raw": raw, "verdict": "", "checked": False, "legacy": False,
                "reason": f"词表外的裁决 {raw!r} ⇒ 按「没查成」读（不许折成「成立」或「有毛病」）"}
    return {"raw": raw, "verdict": raw, "checked": True, "legacy": False, "reason": ""}

#: 依赖类型（FC-23）。`external_unavailable` 是必须存在的一档：
#: 引用了但拿不到的来源（例如论文里"companion book [6, Thm 6.5]"）
#: 既不是 closed，也不该被含糊地写成 dangling。
DEP_KINDS = ("theorem", "definition", "lemma", "proposition", "experiment", "prior_art")
#: 依赖的状态。四态而不是两态。
#:
#:   closed                —— 来源已入库、且引用本身没问题
#:   dangling              —— 引用悬空（该有的来源没登记）
#:   external_unavailable  —— 来源可得性之外的原因：我们拿不到它
#:   refuted               —— 这条被引用的东西本身被证否了（文献错了）
#:   disputed              —— 这条引用有争议、尚未裁决（可能是我们错了，也可能是文献错了）
#:
#: 为什么 `refuted` / `disputed` 不能折进 `dangling`：三者的处置方向相反。
#: `dangling` 要去做的是"把来源补齐"；`refuted` 要做的可能是"把我们的结论一起撤下来"
#: （如果错的是文献，那么压在这条引用上的结论就不能再算数）；`disputed` 要做的
#: 是"送去裁决"（矛盾闭环）。折成一档，等于把"补一个引用"与
#: "撤一条结论"合并成同一个动作 —— 而后者是不可逆的那一类。
DEP_STATUSES = ("closed", "dangling", "external_unavailable", "refuted", "disputed")

#: 一条命题台账（`statements` 表）的来源。
#:
#:   external_lit —— 从文献里摘出来的（B 的"消化"：完整假设 + 证明逐字 + 出处）
#:   own_result   —— 我们自己得到的结果（"自产定理该不该进事实库"）
#:
#: 为什么 origin 必须是独立字段、而不从 `source_lit_id` 推：自产的定理同样会引文献
#: （我们的证明用了 Brown 的定理），于是"有 source_lit_id"既可能是"抄来的"也可能是
#: "我们证的过程中引的"。这两个意思在报告里必须分栏（我们补的与原文的分栏），
#: 而"分栏"这件事靠推导是推不出来的。
STATEMENT_ORIGINS = ("external_lit", "own_result")

#: 命题台账的状态（与裁决闭环配套）：active（在册、可用作依据）·
#: disputed（有争议、尚未裁决，不许当依据用，见 verify 的不变量）· refuted（被证否）·
#: superseded（被后来的一条取代）· pending_definition（概念行：行已登记、定义还没到）·
#: abandoned（明确放弃原命题：`quote_reason` 里必须是一条可解析的放弃标记
#: `abandoned@<ISO8601>@<理由>`，唯一实现 `statementabandon`）。
#:
#: `abandoned` 为什么必须是一等状态：每个命题和证明的产出最终必须以 V 签收尾，
#: 拿不到 V 签就得一直改，或者放弃原命题 —— "一直改"与"放弃"是两条合法终点，
#: 只有它们都读得出来，收工门才敢对"既没签
#: 也没放弃"那一档判红（`closing.statements_unsigned` → blocker）。把它折进
#: `superseded`（被取代）或 `refuted`（被证否）都会说一句假话：放弃的命题既没有
#: 后来者，也没被证否。
#: 最后一档的边界：① 它不是"可用依据"（与
#: `disputed`/`refuted`/`superseded` 同列，见 `STATEMENT_UNUSABLE_STATUSES`）；② 必须带待补标记
#: （`quote_reason` 里的 `concept:pending_search` / `concept:self_authored`，唯一出处是
#: `migrate_concepts`）⇒ "为什么空着"与"谁来补"在盘上读得到（`pending_inbox` 扫的就是它）。
STATEMENT_STATUSES = ("active", "disputed", "refuted", "superseded", "pending_definition",
                      "abandoned")

#: 命题台账里不许再被当作依据的状态。`verify` 的不变量读的就是这一份名单 ——
#: 两处各写一份是"同一判据两个落位"，漂移时没有任何地方会红。
#: `pending_definition` 在列：定义还没到的概念不是依据（"待补"不是"已成立"）。
#: `abandoned` 在列：放弃的命题不再是依据（与 `superseded`"被取代"同一条纪律 ——
#: 它不是"还没签，先用着"）。
STATEMENT_UNUSABLE_STATUSES = ("disputed", "refuted", "superseded", "pending_definition",
                               "abandoned")

#: `statements.kind` 的受控词表（2026-11-22 B2d）。
#:
#: ## 两根轴，各有各的名字（不许互相冒充）
#:
#: - `kind`  = **命题的种类**：它长什么样（定理 / 引理 / 命题 / 推论 / 猜想 / 例子 /
#:   定义 / 概念）；
#: - `grade` = **证据等级**：我们凭什么信它（`conjecture` / `strong_conjecture` /
#:   `pre_theorem` / `theorem` / `error` / `not_applicable`；不落盘，由
#:   `evidencebits.derive_grade` 从五元位现算）。
#:
#: 所以 `kind="theorem"` 而 `grade="conjecture"` 不是自相矛盾：文献里引来的定理陈述
#: （`origin=external_lit` + 逐字回文）**就是**定理这个种类，而我们对它的证据只有
#: 引文回验、没有自己的证明/形式化 ⇒ 等级是猜想。反过来 `grade="theorem"` 也不许
#: 改写作者写下的种类（`evidencebits.kind_following_grade` 只把 `conjecture` 往
#: `theorem` / `lemma` 抬，且要签）。真机 lp-ball-15 实测 13 条 `kind=theorem`：
#: 10 条 `external_lit` + `grade=conjecture`（文献定理）、3 条 `own_result` +
#: `grade=pre_theorem`（我方有证明、过 V 签、未机器核验）。
#:
#: ## 为什么现在设词表
#:
#: 改前它只要求非空（"自由文本"），于是模型自造一个种类在数据面上不可见；而它早已
#: 是几处判据的输入：同一性合并只并命题性的那几档、`pending_definition` 只给 concept、
#: `derive_grade` 对 concept 短路、稿头交叉核对按词表判强弱。词表外的新写在写盘前
#: **受控拒**（`statement_kind_problem`）；历史行按 `created_at` 豁免，读侧照读
#: （`evidencebits.statement_kind_reading` 记 `legacy`）。
#:
#: 与 `secretary_decl.PROPOSITION_KINDS` / `NOT_APPLICABLE_KINDS` 是同一份名单：
#: 那两格是秘书层的历史落位，本表是数据契约的真身。`tests/test_b2d_kind_vocabularies.py`
#: 钉住两边逐字相等 —— 两处各写一份、漂移时没有任何地方会红，是本仓反复禁止的形态。
STATEMENT_PROPOSITION_KINDS: tuple[str, ...] = (
    "theorem", "lemma", "proposition", "corollary", "conjecture", "example")
#: 不做力气判档的那两档（`secretary_decl.NOT_APPLICABLE_KINDS` 的同一份名单）。
#: 注意 `derive_grade` 的短路只有 `concept` 一档（`definition` 的既有口径见该函数 docstring：
#: 它照常参与等级链，判据 `test_agent_b_concept_registration_carries_kind.py` 钉着）。
STATEMENT_NON_PROPOSITION_KINDS: tuple[str, ...] = ("concept", "definition")
STATEMENT_KINDS: tuple[str, ...] = (STATEMENT_PROPOSITION_KINDS
                                    + STATEMENT_NON_PROPOSITION_KINDS)

#: `kind` 词表生效的那一天（历史行按 `created_at` 老于它豁免）。
#:
#: 为什么界线的判据是 `created_at`：`Statement.validate()` 既在写盘前跑，也在
#: `store.rebuild()` 重放历史时跑，而 rebuild 会把 validate 抛异常的行**静默跳过**。
#: 一条历史行若写着词表外的种类，硬拒等于下一次重建时把它丢掉 —— 那是改历史，
#: 不是收紧新写。所以"新写拒、旧行读"只能按 created_at 分。
STATEMENT_KIND_VOCAB_SINCE = "2026-11-22"


def statement_kind_problem(kind: Any, *, created_at: Any = "") -> str:
    """`kind` 的受控判据（空串 = 合格）。三态，不许折平：

    | 档 | 条件 | 处置 |
    |---|---|---|
    | 词表内 | `kind ∈ STATEMENT_KINDS` | 合格 |
    | 历史行 | 词表外，且 `created_at` 早于 :data:`STATEMENT_KIND_VOCAB_SINCE` | 读侧照读（`legacy`），不拒 |
    | 新写 | 词表外，且 `created_at` 不早于生效日 | 拒（`ValueError`，一个字节都不落） |

    没有 `created_at` 的行按历史行放行：官方两个写点
    （`Secretary.record_statement` 与 `table.create`）都会补 `created_at`，
    而 rebuild 读到的老行可能没有它 —— 在这一格硬拒会变成"重建时静默丢行"。
    """
    text = str(kind or "").strip()
    if not text:
        return "kind 不能为空（受控词表：" + " / ".join(STATEMENT_KINDS) + "）"
    if text in STATEMENT_KINDS:
        return ""
    at = str(created_at or "").strip()
    if at and at[:10] >= STATEMENT_KIND_VOCAB_SINCE:
        return (f"kind={text!r} 不在受控词表 {STATEMENT_KINDS} 里 —— "
                "`kind` 是命题的种类（它长什么样），不是自由文本；"
                "证据等级是另一根轴（`bits` 现算的 grade），不要写进 kind")
    return ""

# ---------------------------------------------------------------- 断言的语义词表
#
# 下面六张是 `documents.claims[]` 各字段的受控词表。它们决定"一条断言能写成什么"，而稿件是落库
# 对象，所以按 `DEVELOPMENT.md` §2.3（跨模块受控词表定义在 `schema.py`）它们
# 与上面那些 `*_KINDS` / `*_STATUSES` 同族，真身放在这里。
#
# `claimanatomy` 从本模块 import —— 于是同一张表在两边是同一个对象
# （`CA.CLAIM_KINDS is S.CLAIM_KINDS`），不再有第二份字面量（FC-03）。
#
# 派生的东西（`CLAIM_FIELDS` / 别名表 / 家族表）仍然留在 `claimanatomy.py`：
# 搬的只是"真身词表"，不是判据表。

#: 断言的 `kind`：这是数学对象的类型，不是文稿的体裁。
#: 检查脚本靠这个前缀建索引，且编号规则是"按类型内连续" ——
#: 所以它必须来自受控词表，而不是自由文本。
CLAIM_KINDS = ("定义", "定理", "命题", "引理", "推论", "例", "注", "反例")

#: 断言的 `status`：生命周期轴（与 `evidence_kind` 正交）。
#: `作废` 是"这条断言已被撤销"——它必须能表达，否则"作废的断言仍被当作有效结论引用"
#: 这件事在数据模型里不可见。
CLAIM_STATUSES = ("证", "验", "待精化", "作废")

#: `allowed_use`：论文线的硬性降级规则（RP/00_STANDARD.md 的体例要求）。
#: 只有数值支撑的结论不得出现在摘要/主结果，必须降为 Remark。
ALLOWED_USE_KINDS = ("主结果", "Remark only", "移入 open")

#: `numeric_evidence` 四元组。键名固定，多一个少一个都不可判定。
NUMERIC_EVIDENCE_KEYS = ("script", "range", "n_cases", "n_counterexamples")

#: 断言台账「来源」列。
#:
#: 2026-11-13 按业主裁定删掉 `自证` / `未决`（0 行 / 无读点 / 无写入口）：
#: 这条轴的写入口从来没接上（305 条断言的 `source_kind` 全是空串），
#: 摆着两档只会让读表的人以为「我们自己算的」与「来源至今没查清」已经被区分开了。
#: 真要那张三态来源轴，第一步是接线（谁写、写在哪、谁读），不是先在词表里摆三档。
CLAIM_SOURCE_KINDS: tuple[str, ...] = ("文献",)

#: 「我方核到什么程度」这一列。分档判据是「我们做了什么」，
#: 不是结论有多可信：`证明`（形式化/逐步推导，我方自己走通）·
#: `数值`（复算 / 反例搜索）· `只读了陈述`（连数值核对都没做）。
#: 中间那一档刻意不叫「验证」：那会把"跑过脚本"说成"验过了"。
CLAIM_CHECK_KINDS: tuple[str, ...] = ("证明", "数值", "只读了陈述")


#: H 的审校发现类型。每一类都必须能机械判定，否则审校会退化成"我感觉"：unsupported_claim
#: （citations 为空）· dangling_dep（依赖悬空/外部不可得）· overclaim（把 cross_check 写成 proved）·
#: missing_negation_kind（否定型结论没分类）· scope_drift（把假设当公理、结论范围被放大）·
#: garbled（表述错误/自相矛盾）· inconsistent_number（同一数字在不同处不一致）。
#: 没有"找到了但不一样"这一档：`quoteverify.check_quote` 的 reason 取值里从来没有它，
#: 也没有任何生产路径能产出它 ⇒ 那句"可判定"是假承诺。
#: 系统只能判"逐字不在"，不能判"被改写/拼接"（边界写在 :func:`agentflow.quoteverify.check_quote`
#: 的 docstring 里）。
FINDING_KINDS = (
    "unsupported_claim", "dangling_dep", "overclaim",
    "missing_negation_kind", "scope_drift", "garbled", "inconsistent_number",
)

#: 告警分级（FC-13）。
#:
#: 分级规则（两句话，必须记牢）：
#:   - "表里已记录的缺陷被重算确认" ⇒ `warning`
#:   - "表里记录与重算事实矛盾（谎报）" ⇒ `error`
#: 若不这样分，红灯会被训练成背景噪音，于是真正的 error 也会被忽略。
FINDING_LEVELS = ("error", "warning", "info")

#: 审校发现的状态。`wontfix` / `disputed` 必须写理由（同 `dropped` 必须写 notes）。
#:
#: `superseded`：同一 `(kind, target)` 在更晚的轮次又记了一条判词 ⇒ 更早那条被新判覆盖。
#: 它不是删除：原文、轮次、证据都留着，只把状态推成 `superseded` 并用 `superseded_by`
#: 指到新那条。`open` 的判定仍只看 `status == "open"` ⇒ 覆盖之后 open 数应当下降。
#: `fixed` / `wontfix`（以及 `disputed`）是已了结的判词，不被覆盖 —— 已了结的不动。
FINDING_STATUSES = ("open", "fixed", "wontfix", "disputed", "superseded")

#: `maths` 的取值域（落点见 `docs/PROPOSALS.md`）。
#:
#: 名字刻意不以 `_KINDS` / `_STATUSES` / `_OUTCOMES` / `_SCOPES` 结尾：它不是一张
#: "产出方从中挑一个"的业务词表，而是 `gates.gate_g10` 那条 `maths: yes/no` 判据的
#: 取值域本身。`tools/vocab_census.py` 按后缀认定候选词表，把它命名成词表只会多出
#: 一条"死取值/无产出点"的诊断噪音（它的产出方是 H 的审校发现，不在 `src/` 里）。
FINDING_MATHS_VALUES = ("yes", "no")

#: 审校格式契约的生效日。唯一的读者是 `gates.gate_g10`。
#:
#: 语义只有一句：`created_at` 早于这一天的发现是"契约生效前落盘的历史行"，
#: G10 对它们不要求 `line` / `verbatim_quote` / `suggestion`(=`minimal_fix`) / `maths`
#: 四个键。为什么豁免面必须是一个常量而不是"看情况"：`store.rebuild()` 对重放的每一行
#: 调 `validate()`，抛异常的行被 `skipped += 1` 静默丢掉 —— 那是数据遗失，不是格式错误。
#: 历史行不许回填：`line` 只能从 `target` 猜出来，猜出来的行号是一个发明出来的数字。
REVIEW_FINDING_FORMAT_SINCE = "2026-09-27"


def experiment_preflight_problems(*, method: str, certificate: Any = None,
                                  search_bound: Any = None,
                                  for_question_id: str | None = None) -> list[str]:
    """`Experiment` 里不需要跑脚本就能判的那几条硬要求。

    为什么要有它：这几条若只在 `Experiment.validate()` 里判，而那里跑在子进程之后，
    脚本先跑完、行才被拒，钱与时间已经花了。调用方（`agent_e.run_experiment`）在起子进程
    之前调本函数，一次都不该白花。口径只有一处：`Experiment.validate()` 调的就是本函数，
    不会有两个会漂的判据。
    覆盖四条：① 穷举/枚举类必须给 `certificate`；② `certificate` 必须是对象且含 `kind`；③ 给了 `certificate`
    就必须给 `search_bound`；④ `for_question_id` 必须是合法编号。其余硬约束依赖跑完才知道的量（`exit_code` /
    `result` / `evidence_kind` / 证书内容与结论的一致性），留在 `validate()` 里 —— 本函数不假装能判它们。
    """
    problems: list[str] = []
    search_like = str(method) in ("exhaustive_search",)
    if search_like and not certificate:
        problems.append(
            f"method={method!r}（穷举/枚举类）必须给出 certificate ——"
            "'在 B 内没有反例'的说服力全部来自'B 是什么、怎么搜的'。"
            "没有证书时它只是一句无法复核的话"
        )
    if certificate is not None:
        if not isinstance(certificate, dict) or not str(certificate.get("kind") or "").strip():
            problems.append("certificate 必须是对象且含 kind"
                            "（witness/unsat/enumeration_bound/counterexample）")
        if not search_bound:
            problems.append("给了 certificate 就必须给 search_bound（证书的适用范围）——"
                            "证书脱离边界就没有意义")
    if for_question_id is not None:
        try:
            require_id(for_question_id, "for_question_id")
        except ValueError as exc:            # 编号判据在 `require_id` 里（一处）
            problems.append(str(exc))
    return problems


@dataclass
class Experiment:
    """机器核验与实验台账的一行（DESIGN-ROLES.md §2.1）。

    这张表收两类账：E 写 numeric / symbolic / exhaustive_search（数值与穷举实验），
    L 写 formal（Lean 核验）。L 的形式化行也落在本表里，所以它记的是「机器核过没有」
    与「算过什么」两种账，不是把两者混成一件事。

    本表最重要的一条规矩：`method` 是"计算类"（numeric / symbolic /
    exhaustive_search）时，`evidence_kind` 不得为 `"proof"` —— 除非整个论域
    被穷尽验证过（穷举能拿 proof：签字由 V、②③ 由 E 写，证明栏写程序脚本；
    判据本体 `numericproof.exhaustion_problems`）。
    这条由 :meth:`validate` 机械执行，不靠人记得。

    为什么必须机械执行：数学里数值实验一般不构成证明（"验证通过 ≠ 数学正确"）。
    而"我算了几千个点都对"写成"已证明"是本领域最自然也最危险的过度声称。把它变成
    schema 约束，就让这句谎话在写入的那一刻炸掉，而不是等到审校（或读者）发现。
    穷举那一档不是放宽这条：它要的是"整个论域"这三件可核的证据（搜索空间 / exhaustive /
    覆盖说明），而"算了几千个点"恰恰拿不出它们。
    """

    experiment_id: str
    claim: str  # 被检验的命题（人话，给人读）
    claim_key: str  # 命题的机器可读键（用于去重与引用，如 "SpecK(m)=[-m,m]"）
    #: 方法（受控词表 `EXPERIMENT_METHODS`）：E 写 numeric / symbolic /
    #: exhaustive_search，L 写 formal（Lean 核验）—— 两类账共用这一张机器核验台账。
    method: str
    #: 证据等级。默认 `cross_check` —— 默认值本身就在表达"这不是证明"。
    evidence_kind: str = "cross_check"
    result: str = "inconclusive"
    #: 三种否定（FC-25）。`result="refutes"` 时必须是 `"disproved"`。
    negation_kind: str | None = None
    #: 实验脚本。必须落在工作区内（相对路径），且与 `code_hash` 成对出现 ——
    #: 没有哈希的"可复现"只是口号。
    code_path: str | None = None
    code_hash: str = ""
    params: dict = field(default_factory=dict)
    #: 结构化观测（极值、命中数、网格分辨率……）。给机器判读用。
    observations: dict = field(default_factory=dict)
    exit_code: int | None = None
    runtime_sec: float | None = None
    artifact_paths: list[str] = field(default_factory=list)
    #: 反例。`result="refutes"` 时必须给出（否则"证否"是不可复核的）。
    counterexample: dict | None = None
    #: 形式化检查器的原始输出。`evidence_kind="proof"` 时必须非空。
    verifier_output: str = ""
    #: 检查器输出管的是哪个命题（来自对本地先例 DeepMath 的观摩）。
    #:
    #: DeepMath 的做法是"验证工具与上下文绑定"：越界调用直接 raise。
    #: `verifier_output` 若是自由字符串，把"命题 A 的检查器输出"粘到"命题 B 的记录行"
    #: 上，结构上完全允许，而且没有任何地方会报错。
    #: 有了这个字段，`validate()` 就能要求"输出管的就是本行声称的命题"。
    verifier_subject_key: str = ""
    #: 搜索类结果必须携带证书。
    #:
    #: 形态：`{"kind": "witness"|"unsat"|"enumeration_bound"|"counterexample",
    #:        "detail": {...}}`。
    #: *穷举/可满足性* 这类结论的说服力全部来自"证书"：
    #: "在 B 内没有反例"若不说清 B 是什么，就只是一句无法复核的话。
    certificate: dict | None = None
    #: 搜索边界（证书的适用范围）。`certificate` 非空时必须给出。
    search_bound: dict = field(default_factory=dict)
    for_question_id: str | None = None
    notes: str = ""
    #: 这一行还算不算数（受控词表 `EXPERIMENT_STATUSES`）。
    #:
    #: 两档：`active`（仍有效）/ `voided`（已撤销）。撤销不是删除 —— 手稿里引过的
    #: `exp:<号>` 必须还能打开，读者要能看见「这一条曾经算数、为什么不算了」。
    status: str = EXPERIMENT_ACTIVE
    #: 撤销留痕：谁撤的、什么时候、为什么（人话）、受控理由码。
    #: 四格只在 `status="voided"` 时非空 —— 有效行上留着半截撤销痕迹，读侧就分不清
    #: 「没撤」与「撤了一半」（`validate` 因此两档都判）。
    voided_by: str = ""
    voided_at: str = ""
    void_reason: str = ""
    void_reason_code: str = ""
    #: 撤销时那个脚本的新 sha256（整串）。老那一份就是本行的 `code_hash` ⇒ 两格合起来
    #: 是「脚本 旧 → 新」这句人话的可核依据（`void_reason` 只印两边的前 16 位）。
    voided_code_to: str = ""
    #: ——— 行级归属（K11，2026-11-19）———
    #:
    #: 这一行是**哪一趟、哪个实例**写下的：`owner_task` = 写这一行那一趟的台账号，
    #: `owner_instance` = 那一趟的实例标签（名册名 / 召唤标签，读法唯一在
    #: `identity.resolve_identity`）。两格与 `created_by` 不是一件事：
    #: `created_by` 是 actor（可能只剩角色桶 `agent-E`），而这两格是「谁那一支笔」。
    #: 读写面共用一处判据（`rowscope`）：
    #:   - 读：同角色的另一个实例看不到这一行；别的角色照旧读得到（证据要能流到 V/B/G）；
    #:   - 写（改 / 删）：只有这一行的归属实例能改；`table.create` 由调用者身份现盖这两格。
    #: 两格都空 = 加这两列之前的老行。老行不判给任何实例：读侧按 `created_by` 的
    #: 角色级归属处理，写侧仍按角色级判 —— 「判不了」不许折成「判给了某个人」。
    owner_task: str = ""
    owner_instance: str = ""
    created_at: str = ""
    created_by: str = "agent-E"

    def validate(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        claim_key = self.claim_key.strip()
        if not self.claim.strip():
            raise ValueError("claim 不能为空")
        if not claim_key:
            raise ValueError("claim_key 不能为空（没有它就无法回答'这条实验检验的是哪个命题'）")
        if self.method not in EXPERIMENT_METHODS:
            raise ValueError(f"method 必须是 {EXPERIMENT_METHODS} 之一，收到 {self.method!r}")
        if self.evidence_kind not in EXPERIMENT_EVIDENCE_KINDS:
            raise ValueError(
                f"experiments 表的 evidence_kind 必须是 {EXPERIMENT_EVIDENCE_KINDS} 之一，"
                f"收到 {self.evidence_kind!r}（`proof_review` 不在这一档：它是**审阅**的等级，"
                "凭据在 `verifications/<命题号>.jsonl`（文件账本，不是表）里，"
                "不属于台账里的任何一行（含 L 那类 formal 机器核验行）")
        if self.result not in EXPERIMENT_RESULTS:
            raise ValueError(f"result 必须是 {EXPERIMENT_RESULTS} 之一，收到 {self.result!r}")
        if self.negation_kind is not None and self.negation_kind not in NEGATION_KINDS:
            raise ValueError(f"negation_kind 必须是 {NEGATION_KINDS} 之一或 None，收到 {self.negation_kind!r}")

        # ---- 硬约束 1：计算类方法要 proof 必须拿出"整个论域被穷尽验证"的三件证据
        #
        # 计算类方法不是永远拿不到 proof：纯数值实验把整个命题证掉时也拿 proof
        # （理由是穷举，签名是对应的程序脚本）。所以这一条是"只有穷尽证据齐备才许"，
        # 判据本体只有一处：
        # `numericproof.exhaustion_problems`（搜索空间 + 布尔 true 的 exhaustive +
        # 覆盖说明 + 程序脚本的相对路径）。缺任何一条（含"说不清"那一档）⇒ 拒，
        # 且拒信逐条列出缺什么 —— 它要能让人/模型当场改对。
        # 为什么仍然不是"随你标"：`a+b=b+a` 那种数值扫描也会喊"我都算过了"，
        # 而"算了很多点"与"穷尽了整个论域"之间隔着覆盖说明这一句人话。
        _numeric_proof = (self.method != "formal" and self.evidence_kind == "proof")
        if _numeric_proof:
            from . import numericproof as _NP

            _problems = _NP.exhaustion_problems(
                method=self.method, observations=self.observations,
                certificate=self.certificate, search_bound=self.search_bound,
                code_path=self.code_path, result=self.result)
            if _problems:
                raise ValueError(
                    f"method={self.method!r} 的实验不得声称 evidence_kind='proof' —— "
                    "除非整个论域被穷尽验证过（业主 2026-10-23：穷举能拿 proof，"
                    f"签名主体是 {_NP.PROOF_SIGNER}，证明栏写「程序地址 + 程序设计 + "
                    "穷举论证」三段，后两段由 E 写）。这一行缺："
                    + "；".join(_problems)
                    + "。补齐之前它最多是 "
                    f"{_NP.SUPPORTED_ONLY_KIND}（{_NP.SUPPORTED_ONLY_LABEL}）；"
                    "要主张已证明也可以走 method='formal' 并给出 verifier_output。"
                )
            # ---- 硬约束 1b：穷举那一档的签名主体必须是 V、②③ 的作者必须含 E
            #      （签字仍然由 V 签；E 是 ②③ 的原作者，但签名主体是 V）。
            #
            # 判据本体 `numericproof.is_signed_exhaustion`：signed_by=V、proof_authors 含 E、
            # 证明理由在受控词表里。缺它 ⇒ 这一行是"手写的 proof"，没有任何人签过 ——
            # 而"谁签的、②③ 是谁写的"正是这一档与"数值实验支持"之间唯一可核的分界。
            #
            # 第三方签字那一半（V 的会审签名真落在 `verifications/<号>.jsonl` 里）不在这里判：
            # `validate` 是纯的（手上没有工作区根），而这条实验行是在 V 审之前写的
            # （E 跑完实验就要落行，V 审的是随后登记成命题的那份证明栏）⇒ 在这一层要那
            # 一签会让正控永远过不去。它落在 B 的入库闸 `numericproof.filing_problems`
            # （那一步手上既有根、又正是"命题要以 proof 进库"的那一刻）。
            if not _NP.is_signed_exhaustion({"method": self.method,
                                             "evidence_kind": self.evidence_kind,
                                             "observations": self.observations}):
                raise ValueError(
                    "计算类的 proof 行必须带签名：`observations"
                    f"[{_NP.SIGNATURE_KEY!r}]` 里要有 `signed_by={_NP.PROOF_SIGNER!r}`、"
                    f"`{_NP.PROOF_AUTHORS_KEY}` 含 `{_NP.NUMERIC_AUTHOR!r}`、"
                    f"`proof_reason={_NP.PROOF_REASON_EXHAUSTION!r}`。"
                    "没有签名者的'已证明'与 cross_check 在证据上是同一件事；"
                    "签名只由 E 的 run_experiment 在判定穷尽之后写"
                    "（`numericproof.sign_experiment`）"
                )
            # ---- 硬约束 1c：②③ 必须已经落成盘上一份可核的读数（E 写的报告要能落下来）。
            #
            # 判据本体在 `exhaustionreport.exhaustion_problems`
            # （`numericproof.report_problems` 只转发）：它读行上的落盘事实
            # （路径 / 字节数 / sha256 / 三块齐不齐）。没有这一条时，一条 proof 行
            # 可以在盘上什么都没有的情况下写进库 —— 而"②③ 写了"正是"这条证据能不能
            # 叫证明"的那一半。
            _report_problems = _NP.report_problems({
                "experiment_id": self.experiment_id, "method": self.method,
                "evidence_kind": self.evidence_kind, "observations": self.observations})
            if _report_problems:
                raise ValueError(
                    "计算类的 proof 行必须带 ②③ 的落盘读数："
                    + "；".join(_report_problems)
                    + "。补齐之前它最多是 "
                    f"{_NP.SUPPORTED_ONLY_KIND}（{_NP.SUPPORTED_ONLY_LABEL}）"
                )
        # ---- 硬约束 2：声称 proof 必须有签名者说的话
        #
        # 形式化那一档说的是"检查器的原始输出"；穷举那一档说的是"那份程序跑了什么"
        # （它的凭据是 code_path + code_hash + certificate/search_bound，硬约束 2c 与 6
        # 已经各自强制过）。两档都要有凭据，只是凭据的形态不同 —— 缺了它，
        # "已证明"与 cross_check 在证据上是同一件事，不应享受 proof 的待遇。
        if self.evidence_kind == "proof" and not _numeric_proof and not self.verifier_output.strip():
            raise ValueError(
                "evidence_kind='proof' 时必须给出 verifier_output（证明检查器的原始输出）。"
                "没有它的'已证明'与 'cross_check' 在证据上是同一件事，不应享受 proof 的待遇"
            )
        # ---- 硬约束 2b：检查器输出必须管的就是本行声称的命题
        #
        # 来自对本地先例 DeepMath 的观摩（它的做法是"验证工具与上下文绑定，越界即 raise"）。
        # 没有这一条时，`verifier_output` 是一个自由字符串 —— 你可以把命题 A 的
        # 检查器输出粘到命题 B 的行上，而结构上完全合法。
        # 这不是理论风险：任何"批量跑了一堆检查、再批量写记录"的实现都会踩到它。
        # 穷举那一档没有"检查器输出"，它的上下文绑定是 code_path + code_hash（硬约束 6）
        # 与 certificate/search_bound（硬约束 2c）—— 所以这一条只对形式化那一路强制。
        subject_key = self.verifier_subject_key.strip()
        if (self.evidence_kind == "proof" and not _numeric_proof
                and not subject_key):
            raise ValueError(
                "evidence_kind='proof' 时必须给出 verifier_subject_key（检查器输出管的是哪个命题）。"
                "否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'"
            )
        if subject_key and subject_key != claim_key:
            raise ValueError(
                f"verifier_subject_key={self.verifier_subject_key!r} 与本行的 claim_key="
                f"{self.claim_key!r} 不一致 ⇒ 检查器输出管的不是这条命题。"
                "**验证工具必须与上下文绑定**（越界即拒绝），否则证据等级就成了可随手搬运的标签"
            )
        # ---- 硬约束 2c：搜索类结论必须携带证书
        #
        # 来自对 dsh 数学模式的观摩：*穷举 / SAT / UNSAT* 这类结论的说服力全部来自证书。
        # "在 B 内没有反例"若不说清 B 是什么、用什么算法搜的，就只是一句无法复核的话 ——
        # 它看起来是结论，实际上是一个没有定义域的断言。
        #
        # 这一段与下面 `for_question_id` 那一条不需要跑脚本就能判
        # ⇒ 口径在 `experiment_preflight_problems()`，由调用方
        # （`agent_e.run_experiment`）在起子进程之前判一次；这里调同一个函数
        # ⇒ 判据仍然只有一处。
        _pre = experiment_preflight_problems(
            method=self.method, certificate=self.certificate,
            search_bound=self.search_bound, for_question_id=self.for_question_id)
        if _pre:
            raise ValueError(_pre[0])
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
        # `for_question_id` 的编号形态由上面那次 `experiment_preflight_problems()` 判过
        # —— 同一处口径，不在这里重复判。

        # ---- 硬约束 7：撤销是「两档状态 ＋ 四条留痕」，不许撤一半
        #
        # 为什么要在 schema 层判：撤销是「这一行不再是证据」的唯一开关，而读侧
        # （`experiment_is_voided`）只看 `status` 一个词 —— 一条 `status="voided"`
        # 却没有理由的行，在读数里会变成「无缘无故不算数了」，那种行比不撤更坏。
        # 反方向同样要判：有效行上挂着撤销留痕，读的人会以为它已经被撤过。
        if self.status not in EXPERIMENT_STATUSES:
            raise ValueError(f"status 必须是 {EXPERIMENT_STATUSES} 之一，收到 {self.status!r}")
        _void_trail = {"voided_by": self.voided_by, "voided_at": self.voided_at,
                       "void_reason": self.void_reason,
                       "void_reason_code": self.void_reason_code,
                       "voided_code_to": self.voided_code_to}
        if self.status == EXPERIMENT_VOIDED:
            if self.void_reason_code not in VOID_REASON_CODES:
                raise ValueError(
                    f"撤销的实验行必须给受控理由码 ∈ {VOID_REASON_CODES}，"
                    f"收到 {self.void_reason_code!r}（理由码是机器可判的那一半）")
            _missing = [name for name, value in _void_trail.items()
                        if not str(value or "").strip()]
            if _missing:
                raise ValueError(
                    f"撤销的实验行缺留痕 {_missing}：谁撤的 / 什么时候 / 为什么 / "
                    "换成哪一份脚本，缺一条都复核不了这次撤销")
            if self.void_reason_code == VOID_REASON_CODE_CHANGED:
                if not str(self.code_hash or "").strip():
                    raise ValueError(
                        "理由码 code_changed 的撤销行必须留 code_hash（被改掉的那一份脚本）")
                _want = experiment_void_reason(code_hash_from=self.code_hash,
                                               code_hash_to=self.voided_code_to)
                if self.void_reason.strip() != _want:
                    raise ValueError(
                        "理由码 code_changed 的 void_reason 必须逐字是 "
                        f"{_want!r}（两个 sha 前 16 位），收到 {self.void_reason!r}")
        else:
            _filled = [name for name, value in _void_trail.items()
                       if str(value or "").strip()]
            if _filled:
                raise ValueError(
                    f"有效（status={self.status!r}）的实验行不许带撤销留痕：{_filled} ——"
                    "撤了一半的行会让读侧分不清它到底还算不算数")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AttackPlan:
    """F 的难题攻坚计划（DESIGN-ROLES.md §2.2）。

    为什么"多轮"必须独立成表，而不是塞进 `research_questions`：D 的 `research_questions` 的生命周期是"缺口→
    补证据→研究→回答"，是一棵树（一个问题一个答案）；而难题攻坚是一个目标 + 多轮尝试，每轮可能要（a）向 A
    要检索、（b）让 B 重抽取、（c）让 E 做实验、（d）自己推理 —— 四种完全不同的动作，且要能中途停下并把当前
    最好结果交出去（FC-21）。硬塞进问题表，就会出现"一个 question 有四种互相打架的状态语义"。
    轮次历史存在 `history` 里（而不是单独一张表）：F 的审计需求是"把这个难题的每一轮按顺序读一遍"，一次
    `upsert` 写整行正好服务这个需求，而拆表会带来额外的锁与一致性成本（本框架的 `LOCK_ORDER` 已经很长了）。
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
    #: 深度（嵌套攻坚）。单调不减，用于 `max_depth`（FC-18 ③）。
    depth: int = 0
    parent_plan_id: str | None = None
    #: 未能解决时的当前最好部分结果（FC-21：整体绝不谎报成功，
    #: 但也不该把所有中间成果丢掉）。`status="stalled"` 时必须非空。
    best_partial: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "agent-F"
    #: 这条计划名下的攻坚台账（`work/F/attack-<plan_id>.md`）在盘上的工作区相对路径。
    #: 2026-11-22（A-0c-1，`draft/201`）新加：此前台账里没有这一格，F 的攻坚稿落在盘上
    #: 却回指不到（"文件在盘上、台账里没有"）。
    #:
    #: `None` 与 `""` 是两件事，不许折平：
    #: - `None` = 这一行没有记过（2026-11-22 之前写下的老行，以及刚立项、一轮都没落的行）；
    #: - `""` = 记过、结论是"没有对应稿"。
    #: 两者对读侧的效果相同（都回答"没有可回指的稿"），但落盘形态不同就是不同的审计事实：
    #: "没记"是缺信息，"记了、没有"是结论。
    #:
    #: 读侧不许按 `plan_id` 反推 `attack-<plan_id>.md`：真机上两个方向都有不匹配
    #: （`lp-ball-6` 7 行 / 8 文件；`dct-min2` 18 行 / 11 文件 —— 7 条计划一轮都没落稿）。
    #: 反推等于给台账造第二个真身。
    #:
    #: 必须追加在尾部：字段顺序既是位置参数构造的顺序，也是 `to_dict()` 落盘的键序
    #: （同族先例见 `SearchRequest.submitted_instance` 上那条注释）。
    report_path: str | None = None

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
        # ---- 攻坚台账的回指（A-0c-1，`draft/201`）：`report_path` 要么没记（None），
        # 要么就是这一条计划自己的那一份台账的工作区相对路径。
        #
        # 为什么这里要判"文件名必须是 `attack-<自己的 plan_id>.md`"：这一格的唯一用途是
        # 回指，记成别的计划那一份不会让读侧报错 —— 它只会让 `manuscriptretire` /
        # `refvocab` 把"A 计划的稿"认成"B 计划的"，而两边都自洽。回指面指错行比没有
        # 回指面更坏：没有时读侧会说"没有台账行"，指错时读侧会肯定地说出错的那一行。
        if self.report_path is not None:
            if not isinstance(self.report_path, str):
                raise ValueError(
                    "report_path 必须是字符串或 None，收到 "
                    f"{type(self.report_path).__name__}")
            rel = self.report_path.strip().replace("\\", "/")
            if rel != self.report_path:
                raise ValueError(
                    "report_path 必须是已归一的相对路径（去首尾空白、`/` 分隔），"
                    f"收到 {self.report_path!r}")
            if rel:
                if rel.startswith("/") or ".." in rel.split("/"):
                    raise ValueError(
                        "report_path 必须是工作区相对路径（不许绝对路径或含 `..`），"
                        f"收到 {rel!r}")
                if not rel.endswith(".md"):
                    raise ValueError(f"report_path 必须指向一份 `.md`，收到 {rel!r}")
                want = f"attack-{self.plan_id}.md"
                if rel.rsplit("/", 1)[-1] != want:
                    raise ValueError(
                        f"report_path 的文件名必须是 {want!r}（这条计划自己的攻坚台账），"
                        f"收到 {rel!r} —— 记成别的计划那一份会让回指指错行")
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
        # 上限是 `max_rounds × 子目标数 + 1`，那个 +1 是必要的：没有它，轮数用尽的
        # 那一轮无法追加一条 `action="stop"` 的如实记录 —— "说停"这件事本身被
        # schema 挡住，实现方只能把停止理由塞进 `best_partial` 绕过去。
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
    #: 结构化章节：``[{"heading","body"}]``。存结构化是为了让 H 能定位到
    #: 具体章节去审，而不是对一整块 markdown 做事后正则。
    sections: list[dict] = field(default_factory=list)
    #: 断言列表。每个元素：
    #: ``{"claim_id","section","text","evidence_kind","citations":[...],
    #:    "is_negative","negation_kind","disclaimer"}``
    #: 其中 `citations` 的元素形如 ``"rel:0007"`` / ``"lit:0003#p.4"`` / ``"exp:0002"``
    #: / ``"eval:0005"`` / ``"doc:0002#claim-1@<内容哈希前 16 位>"`` /
    #: ``"stmt:0004"``（引我们自己的命题：有了它，`closing` 才判得了
    #: "哪几条正文断言压在这条命题上"）。
    #: 认哪些前缀、各指向哪张表：唯一声明面是 `CITATION_PREFIXES`（见那里的说明）。
    #: 反例字段有两个来源，语义互不替代：
    #: `counterexamples` = 人 / 文献已知的清单；`numeric_evidence.n_counterexamples`
    #: = 那一次数值运行机器扫到的条数。两者不等时 `scope_caveat` 必填
    #: （判据在下面的 `validate()` 里，不在 G12 那道门上）。
    claims: list[dict] = field(default_factory=list)
    open_problems: list[str] = field(default_factory=list)
    status: str = "draft"
    review_rounds: int = 0
    #: 一次审核的裁决：`""`（未审）/ `成立` / `有毛病`（`REVIEW_VERDICTS`）。
    #: 与 `status` 分开：审过 ≠ 通过（`status` 只表生命周期与历史上的通过/驳回）。
    #: 旧行里的 `看不出来` 只作兼容读：`read_review_verdict` 把它折成「没查成」
    #: （`checked=False`），不是「成立」。
    review_verdict: str = ""
    #: 裁决写下时的时间与主（谁审的）。空串 = 没审过。
    reviewed_at: str = ""
    reviewed_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    #: 内容第几版（G 每次改内容 +1）。新建稿件是 1。
    #: 它不参与 `content_sha256`（那算的是内容本身），只作"改了几次"的可读刻度。
    revision: int = 0
    #: 这一版内容的规范哈希（`signatures.content_sha256_of`；"" = 还没算过）。
    #: 为什么必须有：审批与引用都是对某一版的 —— 没有它，"审批过的版本"与
    #: "被引用的版本"会静默变成两版。
    content_sha256: str = ""
    #: ——— 行级归属（K11，2026-11-19）——— 与 `Experiment` 同形、同一条判据
    #: （`rowscope`）：`owner_task` / `owner_instance` 是「哪一趟、哪个实例」写下的这一行。
    #: 稿件台账的写点仍然只有 `doc.build_document` / `doc.write_mapping` / H 的审校那几条
    #: 正路（DOCGATE2 不改）；这两格让**删除**与**读侧**也认得出归属：别人的稿不归我删，
    #: 同角色的另一个 G 实例不该把别人的稿当成自己那一支的。
    owner_task: str = ""
    owner_instance: str = ""
    created_by: str = "agent-G"

    def validate(self) -> None:
        require_id(self.doc_id, "doc_id")
        if self.kind not in DOC_KINDS:
            raise ValueError(f"kind 必须是 {DOC_KINDS} 之一，收到 {self.kind!r}")
        if not self.title.strip():
            raise ValueError("title 不能为空")
        if self.status not in DOC_STATUSES:
            raise ValueError(f"status 必须是 {DOC_STATUSES} 之一，收到 {self.status!r}")
        if self.review_verdict not in REVIEW_VERDICTS:
            raise ValueError(
                f"review_verdict 必须是 {REVIEW_VERDICTS} 之一，收到 {self.review_verdict!r}"
                "（空串 = 还没审过；`成立`/`有毛病` 是两态裁决，2026-10-30 业主裁定"
                "之后不再收「看不出来」—— 没查成走 checked=False + 理由，不落裁决）")
        if self.revision < 0:
            raise ValueError(f"revision 不能为负，收到 {self.revision!r}")
        if self.content_sha256:
            h = self.content_sha256.strip().lower()
            if len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
                raise ValueError(
                    f"content_sha256 必须是 64 位小写十六进制（收到 {self.content_sha256!r}）；"
                    "它由 `signatures.content_sha256_of` 产出，不该手写"
                )
        if self.status == "accepted" and not self.content_sha256.strip():
            raise ValueError(
                "status='accepted' 必须带 content_sha256：审批是**对某一版**的审批，"
                "没有内容哈希就钉不住它审的是哪一版（`draft/29` §8.5 第 2 条）"
            )
        if self.markdown_path is not None:
            p = self.markdown_path.replace("\\", "/")
            if p.startswith("/") or ":" in p or ".." in p.split("/"):
                raise ValueError(f"markdown_path 必须是工作区内的相对路径，收到 {self.markdown_path!r}")
        #: 断言为空只对 D 的研究稿开一个口（2026-11-22 `A-0c-2`）：一份报告可以是
        #: 「这一趟什么都没研究成」（真机 `lp-ball-6`：`documents 1` 而 `vsigns 0`）——
        #: 那时**不许**为了过校验编一条断言，但必须把"为什么没有断言"写进
        #: `open_problems`。空断言 + 空 open_problems 仍是拒收：那是"交了一张白纸"，
        #: 读的人分不出它和"什么都没交"。
        _blank_report = (
            self.kind == RESEARCH_DOC_KIND
            and any(str(x or "").strip() for x in (self.open_problems or ()))
        )
        if not self.claims and not _blank_report:
            raise ValueError(
                "claims 不能为空 —— 一份没有任何断言的稿件不是稿件"
                f"（唯一例外：kind={RESEARCH_DOC_KIND!r} 的研究稿，且 `open_problems`"
                " 逐条写清了这一趟为什么没有断言）")
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
            # ---- 硬约束 2：cross_check / proof_review 的断言必须自带声明（FC-22）
            #
            # 两档要的声明不同（一句话说清"这一档凭什么"）：
            # cross_check = 数值交叉验证；proof_review = 逐行审阅过的证明（非机器检查）。
            # 为什么用同一个字段：读者只看一句话，而"这一条是哪种证据"必须在正文旁边
            # 就能读到 —— 这也是 `doc.compose_claim` 自动补那句声明的落点。
            if ek in ("cross_check", "proof_review") and not str(c.get("disclaimer") or "").strip():
                what = ("数值交叉验证，不构成证明" if ek == "cross_check"
                        else "逐行审阅过的证明，未经机器检查")
                raise ValueError(
                    f"claims[{cid}] 的 evidence_kind={ek!r}，必须给 disclaimer（如'{what}'）。"
                    "**这句话由结构强制，不靠人记得写**"
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
            # ---- 硬约束 4：反例的两个来源 ----
            #
            # 两个字段各司其职，谁都不许被读成另一个（口径写清 = 本候选的全部内容）：
            #   * `counterexamples` = 人 / 文献已知的反例清单（可能来自别处）。
            #     它是空清单时只说"没有已知反例"，不说"机器没扫到反例"；
            #   * `numeric_evidence.n_counterexamples` = 那一次数值运行扫到的条数
            #     （机器产生，与 `script` / `range` / `n_cases` 同属一个四元组）。
            # 两者本来就不该相等，所以这里不判相等、也不判谁更权威；
            # 只判一件事：不相等时必须用 `scope_caveat` 把差异来源写成一句可判定的话
            # （例："文献已知反例，非本次扫描"）。
            # 这不是一致性门：G12 一行不改，它继续把两个来源并列当"搜过"的痕迹。
            ces = c.get("counterexamples")
            ne = c.get("numeric_evidence")
            n_ce = ne.get("n_counterexamples") if isinstance(ne, dict) else None
            if isinstance(ces, (list, tuple)) and len(ces) > 0 and n_ce is not None:
                if len(ces) != n_ce and not str(c.get("scope_caveat") or "").strip():
                    raise ValueError(
                        f"claims[{cid}] 的 counterexamples 有 {len(ces)} 条（人/文献已知），"
                        f"而 numeric_evidence.n_counterexamples={n_ce!r}（那一次运行机器扫到的），"
                        "两者不等却没有 scope_caveat。"
                        "两个数本来就不该相等（一个来自人/文献、一个来自机器），"
                        "但差异必须自证：不给 scope_caveat，读者无法判断哪个数在说什么（P-10）"
                    )
        if self.review_rounds < 0:
            raise ValueError("review_rounds 不能为负")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dependency:
    """G 登记的外部依赖（DESIGN-ROLES.md §2.3，FC-23 的落地）。

    数学上把引用的定理当成自己的定理，会静默放大结论的适用范围。
    论文 `test/main.pdf` 正好提供了一个真实案例：Theorem 1.5 依赖
    "companion book [6, Thm. 6.5]" 给出的 Spec S̃_m = [−m, m]，
    而那本书不在本项目可得范围内（Remark 1.6 自己也这么说）。
    本框架把它登记成 `status="external_unavailable"`，
    于是"我们没有独立验证这个前提"变成一条可查询的事实，
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
    #: 为什么是这个状态。`dangling` / `external_unavailable` 时必须非空 ——
    #: "依赖没闭合"这个结论本身也要有依据。
    status_reason: str = ""
    created_at: str = ""
    #: 内部来源：本仓的稿件。与 `source_lit_id` / `source_experiment_id`
    #: 并列的第三种来源 —— "这条断言依赖我们自己另一篇稿子的某条断言"。
    source_doc_id: str | None = None
    #: 内部来源：该稿件里的哪一条断言（`documents.*.claims[].claim_id`）。
    #: 给了它就必须给 `source_doc_id`（断言脱离稿件没有意义）。
    source_claim_id: str | None = None
    #: 这条边属于哪一条证明路径：同一 `used_by` + 同一 `path_group` 的行 =
    #: 一条路径（组内 AND：都要）；不同 `path_group` = 可选路径（组间 OR：任一）。
    #: 缺省 1 ⇒ 历史行（与"只有一条路径"的写法）语义一个字不变。
    path_group: int = 1
    #: 被依赖的那一端是本表的一条命题（"定理 A 用到定理 B / 用到某个概念"）。
    #: 与 `source_lit_id` / `source_experiment_id` / `source_doc_id` 并列的第四种来源。
    source_stmt_id: str | None = None
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
        if self.source_doc_id is not None:
            require_id(self.source_doc_id, "source_doc_id")
        if self.source_claim_id and not self.source_doc_id:
            raise ValueError(
                "给了 source_claim_id 就必须给 source_doc_id：一条断言脱离它的稿件没有意义"
                "（`draft/30` §T4-A 的内部来源）"
            )
        if self.status == "closed" and not (
                self.source_lit_id or self.source_experiment_id or self.source_doc_id
                or self.source_stmt_id):
            raise ValueError(
                "status='closed' 必须指向一个已入库的来源（source_lit_id / source_experiment_id / "
                "source_doc_id / source_stmt_id）。否则'闭合'只是声称，verify 的依赖闭合检查会"
                "立刻发现这是空头支票（`source_stmt_id` 是 2026-10-09 加的第四种来源："
                "「定理 A 用到定理 B / 用到某个概念」那条边此前无处安放）"
            )
        if self.status in ("dangling", "external_unavailable") and not self.status_reason.strip():
            raise ValueError(
                f"status={self.status!r} 时必须写 status_reason（依赖为什么没闭合 / 为什么不可得）。"
                "只标一个状态而不说原因，等于把问题记了一笔却没人能接手"
            )
        # `refuted` / `disputed`：这两档同样必须说清"为什么"，
        # 而且比上面那一档更要紧 —— 它们要触发的是"压在它上面的结论怎么办"，
        # 而不只是"去把来源补齐"。动机写成一句话，接手的人才知道该撤哪条结论。
        if self.status in ("refuted", "disputed") and not self.status_reason.strip():
            raise ValueError(
                f"status={self.status!r} 时必须写 status_reason（这条引用为什么被证否 / 争议在哪）。"
                "这一档会让压在它上面的 proof 级断言变成违规（见 verify 的 "
                "proof_claim_on_refuted_dependency），所以理由不能省"
            )
        if self.kind == "experiment" and self.source_experiment_id is None:
            raise ValueError("kind='experiment' 的依赖必须给 source_experiment_id")
        # ---- 证明路径可多组：
        if int(self.path_group) < 1:
            raise ValueError(
                f"path_group 必须是正整数（收到 {self.path_group!r}）：同一 used_by + 同一组 = "
                "一条路径（组内都要），不同组 = 可选路径（组间任一）；0 或负数会让'第几组'失去意义"
            )
        ends = [bool(self.source_lit_id), bool(self.source_experiment_id),
                bool(self.source_stmt_id), bool(self.source_doc_id)]
        if sum(ends) > 1:
            raise ValueError(
                "被依赖的那一端最多给一个（lit / experiment / stmt / doc 四选一）：给两个就说不清"
                "这条边到底依赖谁"
            )
        # 注意：不要求"非 dangling 就必须给一端" —— `external_unavailable`（引了但拿不到）
        # 恰恰是"知道有这么一个来源、而它不在我们库里"那一档，它天然没有 `source_*`；
        # `closed` 那一档由上面既有的规则管（必须指向一个已入库的来源）。
        if self.source_stmt_id is not None:
            require_id(self.source_stmt_id, "source_stmt_id")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_range"] = self.page_range.to_dict()
        return d


@dataclass
class Statement:
    """一条命题台账行：命题原文 + 完整假设 + 证明逐字摘录 + 出处。

    ## 为什么要有这张表：台账里有依赖、有发现、有报告，却没有一处放得下"定理 1.5 的假设是什么、
    它的证明原文长什么样"。于是"审这条证明对不对"在数据面上无处落脚：B 消化完只能在会话记录里
    留一段话，D 要审它得再读一遍 PDF，H 要判"正文与台账逐字一致"也没有可比的第二份文本。
    这张表就是那个落点。
    它与相邻三张表的分工：`literature`（那篇文献）、`statements`（文献里或我们手里的那条命题 —— 本表）、
    `dependencies`（某个使用点依赖了哪条命题，`used_by` → 本表的 `stmt_id` 是自然延伸）。
    ## 四个字段为什么必须分开：`statement_full`（含完整假设）vs `statement_text`（短版/人话）—— 数学里"定理
    成立"与"在什么假设下成立"是两件事，省掉假设的命题会被下游当成无条件成立（这正是 FC-23 在命题级的同一种
    病）；`proof_text`（逐字摘录）—— `quote_verified` 的比对对象就是它，没有逐字原文"引文回验"无从做起；
    `origin`（`external_lit` / `own_result`）—— 报告的"我们补的"与"原文的"要分栏，靠
    `source_lit_id` 推不出来；`kind`（theorem / lemma / …）2026-11-22 起是**受控词表**
    （:data:`STATEMENT_KINDS`）：它是"命题的种类"这一轴（它长什么样），与"我们凭什么信它"
    那一轴（`bits` 现算的 `grade`）正交。改前它刻意不是词表（"它不参与任何判据分支"），
    但那个前提已经不成立（同一性合并 / `pending_definition` / `derive_grade` / 稿头
    交叉核对都按 kind 分支）；历史行里词表外的取值照读（`evidencebits.statement_kind_reading`
    记 `legacy`），新写词表外 ⇒ 受控拒（:func:`statement_kind_problem`）。
    ## `quote_verified` 是三态，不是布尔：`True` = 逐字比对通过 / `False` = 比对过、不一致 / `None` = 没校验。
    三态纪律的老规矩：`None` 绝不是 `False`，也绝不是 `True`（`quoteverify.QuoteCheck` 的 `verified` 就是
    同一套三态）。所以只要不是 `True`，就必须在 `quote_reason` 里说清"为什么"—— 包括"还没查"。
    """

    stmt_id: str
    #: `external_lit`（从文献摘的）或 `own_result`（我们自己得的）。见 `STATEMENT_ORIGINS`。
    origin: str = ""
    #: 命题种类（theorem / lemma / …）。受控词表 `STATEMENT_KINDS`；语义见类 docstring。
    #: 词表外的新写受控拒；历史行按 `created_at` 豁免、读侧记 `legacy`。
    kind: str = "theorem"
    #: 人话标签（如 "Theorem 1.5"）。可空 —— 有些命题在原文里没有编号。
    label: str = ""
    #: 短版命题（引用时用的那一句）。可以为空（只有 `statement_full` 齐全才算数）。
    statement_text: str = ""
    #: 含完整假设的命题正文。`status="active"` 时必填 —— 这是本表的核心判据。
    statement_full: str = ""
    #: 证明的逐字摘录（`external_lit`）或我们自己的证明（`own_result`）。
    proof_text: str = ""
    #: 出处文献（`origin="external_lit"` 时必填）。
    source_lit_id: str | None = None
    page_range: PageRange = field(default_factory=PageRange)
    #: 三态：True 通过 / False 比对不一致 / None 没校验。见类 docstring。
    #: "通过"分两档（`QUOTE_MODES`）：逐字命中 / 语义相同。
    quote_verified: bool | None = None
    #: 这条引文是怎么回验通过的（`QUOTE_MODES` 之一，或空串 = 没有方式可言）。
    quote_mode: str = ""
    #: 不是 True 时必填：为什么没通过、或者为什么还没查。
    quote_reason: str = ""
    #: 语义那一档的证据（与 `Relation` 同一对）：来源那一段逐字正文 + 那次判定的调用记录。
    quote_span: str = ""
    quote_call_sha256: str = ""
    #: 证据等级（复用 `EVIDENCE_KINDS`）：proof / cross_check / heuristic。
    #: 它是派生只读视图：真正判等级的是 `bits`（五元证据位）。
    evidence_kind: str = "heuristic"
    #: 五元证据位：`numeric` / `proof` / `reviewed` / `formal` / `audited`。
    #:
    #: 空对象 = 这一行还没有任何位记录（旧行）⇒ 一律按"五位全空"读（等级 = 猜想）。
    #: 第 4 位（`formal`）的形状与另外四位不同：它是二维的 `{证明号: 四态}`
    #: （对哪个路径做了形式化验证要指明；而定理的正确性只要任意一个路径通过核验即可）。
    #: 键只能是证明号
    #: （`verifications.as_proof_no` 归一，1 = canonical），值只能是 `BIT_STATES` 的四态
    #: —— `stale` 是读侧按"记下来的 proof_sha256 与现行正文不符"现算出来的，不许写进盘上。
    #: 标量形态仍然合法（老行 / 单路径：等价 `{1: 那个四态}`），所以存量零迁移。
    #: 形状与四态纪律的唯一判据来源是 `evidencebits`（这里只转发它的 `bit_problems`，
    #: 不抄第二份口径）；等级不落盘，由 `evidencebits.derive_grade` 现算
    #: （盘上存一份缓存就等于给出"自报等级"的口子，而那正是这套位要堵的洞）。
    bits: dict = field(default_factory=dict)
    #: 见 `STATEMENT_STATUSES` / `STATEMENT_UNUSABLE_STATUSES`。
    status: str = "active"
    #: 这条命题用到了哪些别的命题（本表内的 `stmt_id`，升序去重）。
    #: 它是"承重结论"可追踪的落点：收工门问的就是"承重的那些有没有 T3 或已降档"。
    derived_from: list[str] = field(default_factory=list)
    #: 同一个东西的别的写法（定理也可能有别名）。
    #: 与 `concepts.aliases` 同一件事，并表之后住在这里 —— 任何 kind 都能有
    #: （定理/定义/引理/命题/概念），秘书查重时按 `textutil.normalize` 比它。
    #: 形状与顺序纪律由 `ARRAY_FIELD_KINDS['statements']['aliases']`（`seq`）统一守。
    aliases: list[str] = field(default_factory=list)
    #: 自产结果落在哪份稿子里（`documents.doc_id`）。
    doc_id: str | None = None
    #: 自产结果在稿子里的行范围（如 "120-148"）。可空。
    line_range: str = ""
    created_at: str = ""
    created_by: str = "agent-B"

    def validate(self) -> None:
        require_id(self.stmt_id, "stmt_id")
        if self.origin not in STATEMENT_ORIGINS:
            raise ValueError(
                f"origin 必须是 {STATEMENT_ORIGINS} 之一，收到 {self.origin!r} —— "
                "它是必填的：一条命题是抄来的还是我们自己证的，决定它在报告里进哪一栏"
            )
        _kind_problem = statement_kind_problem(self.kind, created_at=self.created_at)
        if _kind_problem:
            raise ValueError(_kind_problem)
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"evidence_kind 必须是 {EVIDENCE_KINDS} 之一，收到 {self.evidence_kind!r}")
        if self.status not in STATEMENT_STATUSES:
            raise ValueError(f"status 必须是 {STATEMENT_STATUSES} 之一，收到 {self.status!r}")
        if self.quote_verified is not None and not isinstance(self.quote_verified, bool):
            raise ValueError("quote_verified 必须是 bool 或 None（三态：通过 / 不一致 / 没校验）")
        _normalize_quote_mode(self, what=f"statement {self.stmt_id}")
        if self.quote_verified is not True and not self.quote_reason.strip():
            raise ValueError(
                f"quote_verified={self.quote_verified!r} 时必须写 quote_reason："
                "比对不一致要说清哪里不一致，没校验要说清为什么还没校验 —— "
                "只留一个空字段，等于把'没查'记成了一笔没人能接手的账"
            )
        # ---- 出处：external_lit 必须指向一篇文献（否则"逐字摘录"没有比对对象）
        if self.origin == "external_lit" and not (self.source_lit_id or "").strip():
            raise ValueError(
                "origin='external_lit' 必须给 source_lit_id：从文献里摘的命题不写清是哪一篇，"
                "逐字回验就没有第二份文本可比（这正是 B 的消化必须交出出处的原因）"
            )
        if self.source_lit_id is not None:
            require_id(self.source_lit_id, "source_lit_id")
        if self.doc_id is not None:
            require_id(self.doc_id, "doc_id")
        # ---- 自产结果缺 `proof_text`：不拒（"降级 + 待办"）。
        # 不拒不是放宽门槛：降级是现算的（缺第 2 位 ⇒ `evidencebits.derive_grade` 直接给"猜想"，
        # `bits` 与等级都不需要新字段、等级本来就不落盘）；待办有既有载体（`quote_verified`
        # 的三态 + `quote_reason`，消费端扫的就是"该有而没有"）。反过来（拒收）的代价更重：
        # `own_result` 行里带 `proof_text` 的居多而现算等级全是 `conjecture` ⇒ 拒收一条真猜想
        # 也挡不住，只挡住"如实登记"。
        # 边界（不许顺手做）：不加字段、不造新表；`STATEMENT_STATUSES` 加值只走人裁。
        # 负控：缺完整假设的行不许进 active。
        if self.status == "active" and not self.statement_full.strip():
            raise ValueError(
                "status='active' 必须有 statement_full（含完整假设）："
                "省掉假设的命题会被下游当成无条件成立 —— 这是 FC-23 在命题级的同一种病。"
                "概念行还没抽到定义时走 `pending_definition`（D12 甲：那一档不是依据，"
                "且必须带待补标记）；其余情形请补全假设或标成 disputed/refuted/superseded"
            )
        # ---- 放弃那一档：必须带理由与时间。
        #
        # 为什么这一格要在数据面拦：`status="abandoned"` 只是换了一个字面量 ——
        # 一条被标成放弃、却读不出"为什么、什么时候"的命题，与"悬着"没有区别
        # （读的人既没法复核，也没法回答"这件事是几时被放下的"）。判据本体是
        # `statementabandon.parse_abandon`（唯一实现，写读两侧共用），这里只转发。
        if self.status == "abandoned":
            from . import statementabandon as _SA

            got = _SA.parse_abandon(self.quote_reason)
            if not got.get("checked"):
                raise ValueError(
                    "status='abandoned' 必须在 quote_reason 里写一条可解析的放弃标记"
                    f"（`{_SA.ABANDON_MARKER}<ISO8601>{_SA.ABANDON_SEP}<理由>`）："
                    f"{got.get('why') or '标记读不出来'} —— 只标状态不写理由与时间，"
                    "等于把'为什么放下'记成一笔没人能接手的账（与 `quote_verified` "
                    "的三态纪律同一条）")
        # ---- 待补那一档的配套纪律：空定义必须说清"为什么空、谁来补"。
        # 只对概念行要求：别的命题若落成 pending_definition，那是把"还没做"记成一笔
        # 没人能接手的账（与 `quote_verified` 的三态纪律同一条）。
        if self.status == "pending_definition":
            if self.kind != "concept":
                raise ValueError(
                    "pending_definition 只给概念行用（'定义还没抽到'这一档）："
                    f"收到 kind={self.kind!r} —— 别的命题没有'等定义'这种中间态，"
                    "要么是证据没凑齐（走 bits 的四态），要么是有争议（走 disputed）"
                )
            if self.statement_full.strip():
                raise ValueError(
                    "pending_definition 与'定义已经有了'自相矛盾（statement_full 非空）⇒ "
                    "定义到了就把它改回 active（那一笔同时清掉待补标记）"
                )
            marker = str(self.quote_reason or "")
            from . import migrate_concepts as _MC   # 惰性：待补标记的唯一出处（不新增模块级依赖边）

            wanted = (_MC.PENDING_SEARCH, _MC.SELF_AUTHORED)
            if not any(m in marker for m in wanted):
                raise ValueError(
                    "status='pending_definition' 必须在 quote_reason 里写清待补标记"
                    f"（{wanted} 之一，唯一出处是 `migrate_concepts`）："
                    "只留一个空字段等于把'还没抽到'记成一笔没人能接手的账"
                )
        # ---- derived_from：升序去重、不含自身、每个都得是合法 id
        _problems = _set_problems("derived_from", self.derived_from)
        if _problems:
            raise ValueError("；".join(_problems))
        for dep in self.derived_from:
            require_id(dep, "derived_from[]")
        if self.stmt_id in self.derived_from:
            raise ValueError("derived_from 不能包含自身（自环会让'承重链'永远闭合）")
        # ---- 别名（定理也可能有别名）
        #
        # 只在数据面把两件明显不合规的事挡住（形状与顺序纪律由
        # `ARRAY_FIELD_KINDS['statements']['aliases'] = 'seq'` 那一处统一守，不在这里抄第二份）：
        #   ① 别名与自己的 `label` 相同 —— 那是"没有别名"，不是"有一条别名"；
        #   ② 空别名 —— 它会让查重按空白命中一切（比"漏登记"更坏）。
        for a in self.aliases or []:
            if not str(a).strip():
                raise ValueError("aliases 里不能有空串（空别名会让查重按空白命中一切）")
            from . import textutil as _T   # 惰性：与 `evidencebits` 同一处风格，不新增模块级依赖边

            if _T.normalize(str(a)) == _T.normalize(str(self.label or "")):
                raise ValueError(
                    f"aliases 里有与自身 label 相同的写法（{a!r}）⇒ 那是'没有别名'，"
                    "不是'有一条别名'（查重时会把自己当成自己的别名）"
                )
        # ---- 五元证据位：形状与"四态纪律"在这里把一次关。
        #
        # 判据本体在 `evidencebits`（唯一来源）：这里只转发，不抄第二份口径 ——
        # 两份口径一旦分家，"没做过"与"做过没通过"就会在某一处被压平，而门照样亮绿。
        # 第 4 位是二维的（`{证明号: 四态}`）：键是不是证明号、
        # 值是不是写侧那四态、逐条凭据有没有落在 `evidence.formal_by_proof` 里，
        # 都由 `bits_shape_problems` 逐条判 —— 这一格只负责"写库之前必须过它"。
        # 为什么必须在数据面把这一关：盘上写进一个形状不对的 `bits`，下游（收工门、
        # 状态报告）读到的就是一条半成品读数，而没有任何一处会响。
        if self.bits:
            from . import evidencebits as _EB

            # `kind` 必须传进去：概念行不参与等级链，
            # 而"自报等级 vs 现算等级"那一比也要按同一个 kind 算 —— 不传的话
            # 概念行存下的 `grade="not_applicable"` 会被当成"与现算不符"而拒收。
            problems = _EB.bits_shape_problems(self.bits, kind=self.kind)
            if problems:
                raise ValueError("bits 不合规：" + "；".join(problems))
            row = {"stmt_id": self.stmt_id, "origin": self.origin, "bits": self.bits,
                   "source_lit_id": self.source_lit_id, "quote_verified": self.quote_verified}
            if _EB.bits_from_row(row).get("voided_by") and self.status == "active":
                raise ValueError(
                    "作废的命题不许留 status='active'：作废要把状态推成 refuted 或 superseded "
                    "（等级清零与状态降档是两件事，只做一件会让'已作废'在别的读数里复活）"
                )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_range"] = self.page_range.to_dict()
        return d


@dataclass
class ReviewFinding:
    """H 的一条审校发现（DESIGN-ROLES.md §2.4）。

    `evidence` 必填非空，这是本表的设计核心。本项目最刺痛的一条教训是：审校者的判断也需要证据 ——
    若审校记录可以只写"这里有问题"而不给依据，审校就会变成另一种幻觉来源，而且因为审校者的位置
    更高，它更难被纠正。
    ---- G10 六键里的四键 ----
    G10 审校格式门要求"每条发现必须有：轴 + 严重度 + 行号 + ≤20 词逐字引文 + 最小修法 +
    `maths: yes/no`"。这六格里 `axis` / `line` / `verbatim_quote` / `maths` 在本表都有同名字段；
    "最小修法"概念上有、键名不同（G10 读 `minimal_fix`，本表叫 `suggestion`）。两条纪律写在这里，
    因为它们都是"看起来更严、实际更糟"的形态：
    1. 本表的 `validate()` 刻意不含"这四个字段必须非空"这类断言。理由不是宽容，是 `store.rebuild()`：
    它逐行调 `S.row_from_dict(...)` + `obj.validate()`，任何异常都被 `except Exception: skipped += 1; continue`
    吃掉 —— 加上非空断言，契约生效前落盘的历史 finding 行会在下一次重建时整行消失，而且不报错。完整性由
    `gates.gate_g10` 判，且 G10 只对 `created_at >= REVIEW_FINDING_FORMAT_SINCE` 的行要求它；历史行按
    `created_at` 豁免，不许回填。
    2. 这四个字段一律不进去重键。去重键是 `(kind, target, message)`（`tools/review_tools._dedup_key`），
    `verify_fixes` 的重开逻辑与 `test_agent_h` 的去重断言都靠它。把 `line`（行号易失）或 `verbatim_quote`
    （改一个词就变）塞进键里，会让每次微小改动都产生一批新发现，并打断"标了 fixed 但其实还在"的重开逻辑。
    """

    finding_id: str
    doc_id: str
    kind: str
    level: str
    target: str  # "claim-3" / "section:2" / "dep:0004" / "rel:0007"
    evidence: str  # 必填：H 凭什么这么判
    message: str
    round: int = 1
    suggestion: str = ""
    status: str = "open"
    resolution_note: str = ""
    #: 被哪一条更晚的判词覆盖（`superseded_by` = 新 finding 的 `finding_id`）。
    #: 三态口径：空串 = 没有被覆盖（所有老行、以及今天绝大多数行都是这一档），
    #: 非空串 = 本行 status 已推成 `superseded` 且覆盖它的是那一条。
    #: 它只在 `status == "superseded"` 时才有意义；`validate()` 对"说了被覆盖却不给指针"
    #: 当场拒（指针是这条状态唯一的可追溯落点），其余情形一个字都不判。
    superseded_by: str = ""
    created_at: str = ""
    created_by: str = "agent-H"
    #: 轴。取值域 = `gates.AXES`（数学 / 体例 / 工程 / 证据）。
    #: 不在本模块重抄一份词表（FC-03）：`validate()` 里按 `gates.AXES` 判。
    axis: str = ""
    #: 1 起的行号，指向 `doc_id` 那一行。`None` = "这一次拿不到行号"，此时必须给
    #: `line_unavailable_reason`（否则"拿不到"是一个没有结论的空白）。行号只有在版本冻结（G11）之后
    #: 才有意义 —— 未冻结时记下的行号在改稿之后就是错的，而它看起来一样精确。
    #: 接线落在 `gates` 侧（`GateContext.findings_version_pinned` + `gate_g10`）；本表不加非空断言
    #: —— `store.rebuild()` 会把任何 `validate()` 抛异常
    #: 的行静默丢掉，所以"必填"这件事由门判、不由写入期契约判。口径：版本已冻结（G11 通过）时
    #: `line_unavailable_reason` 不是合规的第三态（"行号拿不到"与"版本已冻住"互相矛盾），G10 按缺字段打回。
    line: int | None = None
    #: 逐字引文（≤20 词；中文按字、英文按空白切词）。词数口径只有一份实现：
    #: `gates._quote_word_count`，由 `validate()` 复用，不另造一套。
    verbatim_quote: str = ""
    #: `maths` 档。取值域 = `FINDING_MATHS_VALUES`（`"yes"` / `"no"`）。
    maths: str = ""
    #: `line is None` 时必须非空的理由（"为什么这一次拿不到行号"）。
    #: 这一格只在版本未冻结时才是合规的第三态；G11 通过
    #: （`observed_hash` 与被审版本 hash 逐字相等）时 `line` 必填，
    #: 此时填了本字段也会被 G10 按"缺 `行号(line)`"打回。
    line_unavailable_reason: str = ""

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
        # 被覆盖的那一条必须指得到"被谁覆盖" —— 指针是 `superseded` 这个状态唯一
        # 的可追溯落点（原文与轮次都留着，删掉的是"它还算数"这件事，不是这一行）。
        # 反方向不判：`superseded_by` 非空而状态不是 superseded 的情形不存在于写入面，
        # 但老行里多这一格不该被 `store.rebuild()` 静默丢掉（见类 docstring 第 1 条）。
        if self.status == "superseded" and not self.superseded_by.strip():
            raise ValueError(
                "status='superseded' 时必须给 superseded_by（被哪一条更晚的判词覆盖）"
            )
        # ---- 取值判据 ----
        #
        # 只判"给了值就必须给对"，刻意不判"必须给值"（见类 docstring 第 1 条：
        # 非空断言会让 store.rebuild() 静默丢历史行）。完整性由 G10 判。
        # 词表与词数口径都只有一份实现，都在 `gates` 里，这里惰性 import：
        # `gates` 顶层 import `tools.doc_tools`，而后者顶层 import 本模块 ——
        # 模块级互相 import 会成环（与 `store` 那处惰性 import 同一条理由）。
        from .gates import AXES, _quote_word_count

        if self.axis.strip() and self.axis not in AXES:
            raise ValueError(f"axis 必须是 {AXES} 之一，收到 {self.axis!r}")
        if self.maths.strip() and self.maths not in FINDING_MATHS_VALUES:
            raise ValueError(f"maths 必须是 {FINDING_MATHS_VALUES} 之一，收到 {self.maths!r}")
        if self.line is not None:
            if isinstance(self.line, bool) or not isinstance(self.line, int) or self.line < 1:
                raise ValueError(
                    f"line 必须是 1 起的行号（int）或 None（拿不到行号时给 None），收到 {self.line!r}"
                )
        if self.verbatim_quote.strip():
            words = _quote_word_count(self.verbatim_quote)
            if words > 20:
                raise ValueError(
                    f"verbatim_quote 是 {words} 词，超过参考体例的 20 词上限"
                    "（口径 = `gates._quote_word_count`：中文按字、英文按空白切词）"
                )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 主控编队（Conductor）

#: 全项目唯一的角色名单（FC-03 单一来源）。
#:
#: `tools.ROLES` 就是这一个对象（它 import 这里），
#: 所以改角色名单只需要改一行，也不可能不一致。
#:
#: `L`（Lean 形式化者）：照 E 的 Lean 面复制出来的一个可运行角色。
#: 协作面：入边恰好 `B → L`、出边恰好 `L → C`、可召唤
#: （`specs/l.py` 与 `specs/b.py` 的 `edges`/`summonable`）—— 这两件事都由声明派生，
#: 本行的加一个字不构成任何一条边。判据见
#: `tests/test_l_collab_surface_is_exactly_this.py`。
ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L")

#: 主控（编排者）的角色标识。
#:
#: 为什么把主控也放进角色空间：本框架的入口是用户对主控说话，主控按需召唤角色。
#: 若主控不在这套名单里，它就成了"谁能召唤谁"策略之外的特权路径 ——
#: 而特权路径正是权限模型最容易漏的地方。
CONDUCTOR_ROLE = "M"

#: 一次召唤（summon）的任务状态：pending（已立项，尚未开始）· running（正在跑）· done（正常结束，
#: 结果可能是"没做成"，那看 outcome）· cancelled（被取消，含超时/预算耗尽）· failed（异常终止）。
#: `done` 与 `failed`/`cancelled` 必须分开：前者的语义是"这个任务跑完了"，后者是"它没跑完"；三者合并成"结束"之后就答不出"这条结论是在一次成功完成的召唤里产出的、还是在崩溃里被顺手写下的"。
# ---- 工作项板
# 为什么这四条词表定义在 `schema.py`：`manuscripts` 就 `from . import schema as S`（它要用
# `S.TABLES` / `S.ROLES`）⇒ 反过来 import 会成环；而本仓既有规矩（判据
# `tests/test_claimanatomy.py::test_the_six_claim_vocabularies_have_exactly_one_definition_in_schema`）
# 是"受控词表的真身在 `schema.py`，工具侧只引用不内联"。

#: 板上一行的四种 `kind`。空串 = 老行 / 纯实例行（不进板）。
#: 为什么"空串"也算合法取值：盘上已有的老行没有这一列，加列之后它们必须天然被读成
#: "不是板项"，不许要求逐行迁移。
ITEM_KINDS: tuple[str, ...] = ("delegation", "message", "report", "notice")
#: 一条工作项"要什么行为"——这一格决定"什么算做完"（最小行为是"确认读过"）。
ITEM_EXPECTS: tuple[str, ...] = ("ack", "work")
#: 工作项轴的四档：`claimed` = 接手（写 `running` 行那一刻）、
#: `seen` = 渲染（被读进某一步的提示词）。它与 `status` 是两根轴，不许共用一个名字。
#: `block`（与 `TASK_STATUSES` 同一件事的另一根轴）—— 优雅停止时
#: 被停掉的委托，它在板上的那一项也不许继续写着"待办"（`stopctl.block_remaining_tasks`
#: 把两根轴一起翻）。它不进 `ITEM_CLOSES`：`block` 不是收口方式，是"停在这里"。
ITEM_STATES: tuple[str, ...] = ("queued", "claimed", "seen", "done", "block")
#: `done` 的两种收口：`acked`（知道了）与 `completed`（做完了）必须分得开 ——
#: 折平它就是把"光知道个信息"读成"交付了"。
#: 板项收口的三档。
#:
#: 为什么必须有第三档：子代理静默/退役后，它名下"只许本人 ack"的到点通知永远不会有人 ack，
#: 而销号闸要求"名下没有未消的板项"、收工闸要求"整棵树都已销号" ⇒ 四个环节互锁，
#: 那一趟连续被拒满 `max_final_refused` 拍后以 `final_refused` 收尾、final 为空。
#: 出口只能是"作废"这一档：它不是"知道了"（acked），也不是"做完了"（completed），
#: 而是"这条通知永远不会再被收件人处理"。折进前两档会让读数再也分不清这三件事 ——
#: 那正是这套系统反复禁止的折平。
ITEM_CLOSES: tuple[str, ...] = ("acked", "completed", "expired")

#: `block` 一档说的是"停了、但这件活没做完"，与 `cancelled`（被取消）和 `failed`（崩了）
#: 都不同：前者是"人不让它做了"，后者是"它做坏了"，而 `block` 是"优雅停止时它还在手上"。
#: 翻这一档的是框架（`stopctl.block_remaining_tasks`），不是模型自己声明 ——
#: 于是"停的时候手上还剩什么"在台账上有主人、有理由（`detail` 必填）、有时间（`ended_at`）。
TASK_STATUSES = ("pending", "running", "done", "cancelled", "failed", "block")

#: 召唤的终局类型（回答"这次召唤到底给出了什么"）：ok（完成并产出了预期产出）· no_result（完成
#: 但确实没有结果，如"检索无命中"，这是一个有效结论）· not_applicable（完成，但该动作在当前状态
#: 下不适用）· refused（框架拒绝执行：越权/超预算/超深度/检测到循环）· failed（执行中异常）·
#: cancelled（被取消）· cut_off_by_parent（父代理退场时它还在跑，由父的退场结算写成终态 ——
#: 结果未知，不许记成 ok）。`refused` 单列是刻意的："我们没做"与"做了没成"是最容易被混为一谈的一对
#: （引文校验、OCR、D 溯源、C 预算截断四处都踩过），拒绝是策略的决定、失败是执行的结果。
#: 别与 `SEARCH_OUTCOMES` 串了（两套命名空间只差一个字母）：本词表（`tasks.outcome`）用单数
#: `no_result`，那里（`search_requests.outcome`）用复数 `no_results`。两处必须成对读 —— "错一个
#: 字母"在两边都只会得到一句"不在词表里"，而不会告诉你串了哪一套（见 `SEARCH_OUTCOMES` 上面那段）。
TASK_OUTCOMES = ("ok", "no_result", "not_applicable", "refused", "failed", "cancelled",
                 "cut_off_by_parent")

#: 一个子代理的结局（三档，见 :func:`child_ending`）。它是"这个子到底怎么结束的"这一问的
#: 唯一答案面 —— 正常交付 / 被父代理退场掐断 / 被叫停。三档各有各的台账落点：
#: `delivered` 用子自己报的 `status`/`outcome`；`cut_off_by_parent` 落
#: `done` + `cut_off_by_parent` + `settled_at_parent_exit=True`；`stopped` 落
#: `cancelled` + `cancelled`（或 `refused`，当它是"因超预算/超截止被拒"那一档）。
CHILD_ENDINGS = ("delivered", "cut_off_by_parent", "stopped")

#: 三档的命名常量：`child_ending()` 的三个分支各返回其中一档（不是再写一遍字面量）。
#:
#: 为什么要这一层：三档若在 `child_ending()` 里各写一遍字面量，"词表说三档"与
#: "判定点给三档"只是碰巧一致 —— 词表改一个字母、加一档、删一档，判定点一个字节都不会
#: 跟着变，也没有任何判据会红。解包之后：`CHILD_ENDINGS` 被改短/改长，`schema.py` 的导入期当场抛
#: `ValueError`（不是静默漂移）；词表与分支的"一一对应"（不许有档没人产、也不许产出
#: 词表外的档）由 `tests/test_child_endings_are_a_closed_set.py` 穷举判。
CHILD_DELIVERED, CHILD_CUT_OFF_BY_PARENT, CHILD_STOPPED = CHILD_ENDINGS

#: 只有框架能写、角色自己不许声明的 outcome（在 `TASK_OUTCOMES` 里，但 handler 说
#: "我这一趟是 cut_off_by_parent" 不算数）。
#:
#: 为什么必须有这一格：那一档说的是"父代理退场时它还在跑"，只有父的退场结算那一步
#: 知道这件事。若 handler 也能声明它，就等于给了一条凭空把一行写成"被掐断"的路
#: —— 而那一行可能根本没跑过，读侧却会把它的产出当作"未并入"丢掉（与伪造终态同族）。
FRAMEWORK_ONLY_OUTCOMES = ("cut_off_by_parent",)


def child_ending(*, status: str = "", outcome: str | None = None,
                 stop_code: str = "", cut_off: bool = False) -> dict:
    """一个子代理的结局 —— 三档只在这一处判（唯一判定点）。

    为什么必须有这一处："一个子的结局"若散在四个写者手里 —— 子自己交付
    （`Conductor._end_from_payload`）、子读到取消（`summon_run` 的
    `except CancelRequested`）、`dispose()`、以及父退场那一处 —— 各自拼自己的
    `status`/`outcome` 字面量，"被父退场掐断"这一档在台账上就没有位置（父退场时
    一个字段都不写，子行留在 `running`，或在自己的线程里照常写成 `done`/`ok` ——
    两种都和"正常交付"长得一模一样）。三档从同一处判出来之后，"这个子是被谁结束的"
    只需要读一个函数。

    参数（都是事实，不是判断）：
    `cut_off`：父代理退场时它还在跑（真值 = 这一档，优先于其余两档）；
    `stop_code`：叫停的理由码（`user` / `budget` / `dispose` …）；给了非空串 = 被叫停；
    `status` / `outcome`：子自己报的那两格（`delivered` 档原样透传，一个字节都不改写）。

    返回 `{"ending", "status", "outcome", "settled_at_parent_exit", "why"}`。调用方只许
    按这四格写台账，不许在调用点另拼 `status`/`outcome` 字面量。
    `ending` 的取值只来自 :data:`CHILD_ENDINGS`（三个分支各返回其中一档；词表与分支的
    一一对应由 `tests/test_child_endings_are_a_closed_set.py` 穷举判）。
    """
    if cut_off:
        return {"ending": CHILD_CUT_OFF_BY_PARENT, "status": "done",
                "outcome": "cut_off_by_parent", "settled_at_parent_exit": True,
                "why": "父代理退场时它还在跑 ⇒ 这一行由父的退场结算写成终态：结果未知，不是 ok"}
    if str(stop_code or "") or str(status or "") == "cancelled":
        # `refused` 那一档要保住：`status=cancelled` 时 `outcome=refused` 是"因超预算/超截止
        # 被拒"，与"被取消"语义不同（`validate` 允许两者，见下面对 cancelled 的判据）。
        kept = "refused" if str(outcome or "") == "refused" else "cancelled"
        return {"ending": CHILD_STOPPED, "status": "cancelled", "outcome": kept,
                "settled_at_parent_exit": False,
                "why": f"被叫停（{str(stop_code or '') or 'cancelled'}）"}
    return {"ending": CHILD_DELIVERED, "status": str(status or "done"),
            "outcome": str(outcome or "no_result"), "settled_at_parent_exit": False,
            "why": "子代理自己交了差"}

#: 框架拒绝执行的具体理由（受控词表）。`outcome="refused"` 必须带其中之一。
#:
#: `invalid_params`：「这次调用本身不成立」这一档。没有它，参数门只好借用
#: `unknown_action`（"这个角色没这个动作"）来报"参数不合法" —— 调用方拿到
#: `refusal_reason=unknown_action` 却看到 detail 写着"dependencies. 必须是对象"，
#: 排查方向被引到"角色能力表"上去了（那是查名字的方向，而真相是改参数）。
#: 同一件事在 handler 内部发生时更糟：那里落的是 `failed / 执行中异常`
#: （"业务拒绝"与"代码崩了"同形）。有了这一档，两处都落到同一个诚实的位置。
REFUSAL_REASONS = (
    "unknown_role",  # 角色不存在
    "unknown_action",  # 该角色没有这个动作
    "forbidden_edge",  # 策略不允许这条召唤边（如 C→B），或目标是不可召唤的主控
    "invalid_params",  # 参数/前置条件不满足：这次调用本身不成立（不是"角色没这个本事"）
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
    """一次召唤的台账行（主控编队的核心表）。

    ## 为什么不复用已有的表：`attack_plans` / `research_questions` 描述的是领域对象，本表描述的是运行记录
    （谁在什么时候召唤了谁、为了什么、结果如何）。混在一起就会出现"一个研究问题有四种互相打架的状态语义"
    那种局面 —— `AttackPlan` 的 docstring 已经为此警告过一次。
    ## 它同时承担 FC-20（取消语义）的三条要求：
    1. 每个 start 有且仅有一个 end：`started_at` / `ended_at` 成对，且 `status ∈ {done, cancelled, failed}`
       ⇒ `ended_at` 必填。
    2. 终态先到先得：`ended_at` 一旦写下就不许再被改写 —— 由 :meth:`validate` 的 "pending/running 却已有 ended_at ⇒ 拒"保证。
    3. dispose 幂等：重复结束同一个任务时第二次必须什么都不做（由 `Conductor` 实现；schema 提供"改了就
       违规"的判据）。
    """

    task_id: str  # "t-NNNNNN"（过程记录，不占编号空间）
    role: str  # 被召唤的角色（A–H），或 "M"（主控自己）
    action: str  # 该角色暴露的动作名
    #: 谁召唤的：`"M"`（主控）、`"A"`（角色 → 角色）、`"user"`（人直接指派）。
    called_by: str = "M"
    #: 父任务 id。主控发起的为 None。
    #: 这条链是"深度"的唯一权威来源 —— 不靠调用栈，因为跨进程/跨会话之后调用栈就没了。
    parent_task_id: str | None = None
    #: 召唤链的深度（主控发起 = 1）。单调不减，resume 后不重置（FC-18 ③）。
    depth: int = 1
    #: 判重用的输入指纹。`(role, action, input_key)` 在祖先链上重复出现即判循环。
    input_key: str = ""
    status: str = "pending"
    outcome: str | None = None
    #: `outcome == "refused"` 时的受控理由（见 `REFUSAL_REASONS`）。
    refusal_reason: str | None = None
    #: 实例标签。空串 = 这个角色只有那一个实例。
    #:
    #: 为什么必须落到台账上：`instance` 若只存在于日志行与后端调用参数里
    #: （`conductor.summon(..., instance=…)` → `_log("… , instance=X")`），
    #: "这一轮里 N 个并行实例各自做了什么"在读台上无法归因 —— 台账里同角色同动作的
    #: 多行长得一模一样。R17 要的"同一份文献只被一个实例领走"没有这一栏根本判不了。
    instance: str = ""
    #: 人可读的说明。"为什么是这个结果"必须能读，否则台账就只是个计数器。
    detail: str = ""
    error: str | None = None
    started_at: str = ""
    ended_at: str | None = None
    #: 该次召唤消耗的 token / 估算美元。由调用方在结束时回填（FC-19）。
    tokens: int = 0
    usd: float = 0.0
    #: 该次召唤登记的产出引用（形如 `"experiments:0003"`、`"documents:0001"`）。
    artifacts: list[str] = field(default_factory=list)
    #: 该次召唤读过的行（审计用；也让"这条结论的依据是哪次召唤"可回答）。
    inputs: list[str] = field(default_factory=list)

    # ---- 工作项板（板就在这张表上）
    #
    # 七格都追加在末尾：`to_dict()` 是 `asdict`（键序 = 字段序），而 I-9 要求
    # `rebuild()` 之后 `tasks.json` 逐字节一致（判据见
    # `tests/test_task_instance.py`："加了这一栏之后 rebuild 逐字节不变"）。
    #
    # 为什么工作项轴不叫 `status`：`status` 说的是实例的生命周期
    # （pending/running/done/cancelled/failed），而"这一项被读过没有"是另一根轴
    # —— 两根轴共用一个名字，就会把"接了它"读成"读过了"（本仓反复踩的三态塌陷）。
    #: 板上的 kind（`ITEM_KINDS`）。空串 = 老行 / 纯实例行（不进板）。
    kind: str = ""
    #: 什么算做完（`ITEM_EXPECTS`）；`kind` 非空时必填。
    #:
    #: 唯一允许为空的行是撤销/作废之后的那一行（`item_state="done"` 且
    #: `item_close="expired"`）：它不再欠任何动作，原值记在 `expects_was`
    #: （判据 `tests/test_revocation_shape_improvements.py`）。
    expects: str = ""
    #: 工作项轴（`ITEM_STATES`）。
    item_state: str = ""
    #: 收口方式（`ITEM_CLOSES`）；`item_state == "done"` 时必填。
    item_close: str = ""
    #: 谁读的（`item_state` 走到 `seen` 那一刻、渲染它的那个实例的 `task_id`）。
    seen_by: str = ""
    #: 第几步读的（"跨多步未读"升级档要用）。
    seen_step: int | None = None
    #: 派活参数：父声明"这个实例做完一件还待命"。只对 `kind == "delegation"` 有意义。
    keep_alive: bool = False

    # ---- 这一行是不是"父代理退场时被结算的"
    #
    # 为什么必须是一格显式的标记（而不是让读的人去比 `detail` 的措辞）：`outcome` 里
    # 那一个 `cut_off_by_parent` 档回答"它怎么结束的"，这一格回答"是谁写的这一行"
    # ——父退场时子代理可能还活着，它会晚些时候在自己的线程里写自己的终态；两件事
    # 必须分得开，否则"被掐断"与"自己交差"在台账上又会长得一样。
    #
    # 位置在最后一位（不是美观问题）：`to_dict()` 是 `asdict`（键序 = 字段序），而
    # `_write_new_row` 与 `finish` 都把行补齐到全字段 —— 新键追加在末尾才让 `rebuild()`
    # 之后 `tasks.json` 逐字节一致（I-9 的那两条判据守这件事）。
    #: `True` = 这一行的终态是父代理退场时结算的（子当时还在跑，结果未知）。
    settled_at_parent_exit: bool = False

    # ---- 撤销：`expects` 被清空之后，原值留在哪
    #
    # 为什么必须有这一格（一个数一个名，撤销不是删除）：撤销之后那一行不再欠任何动作，
    # 于是 `expects`（"什么算做完"的唯一一格）被清空 —— 可它原来要的是 `ack` 还是
    # `work`，读的人仍然要能回答（"这一条本来只要一个回执，还是一件要交付的活"）。
    # 把它抹掉就是把撤销这件事塌成"本来就没有"。所以清空 `expects` 时必须把原值留在
    # 这一格；这一格只在 `expects == ""` 时有值（两格同时非空 ⇒ 读的人不知道以哪格为准，
    # 由 `validate` 当场拒）。
    #
    # 位置在最后一位的理由同 `settled_at_parent_exit`（`rebuild()` 逐字节一致，I-9）。
    #: `expects` 被清空前的那一档（`ITEM_EXPECTS` 之一；空串 = 没有可留的来路）。
    expects_was: str = ""

    def validate(self) -> None:
        if not str(self.task_id or "").strip():
            raise ValueError("task_id 不能为空")
        # 与 `SearchRequest.validate` 同一条判据（前缀是 t-）。
        require_process_id(self.task_id, "task")
        if self.role not in (*ROLES, CONDUCTOR_ROLE):
            raise ValueError(f"role 必须是 {(*ROLES, CONDUCTOR_ROLE)} 之一，收到 {self.role!r}")
        # 这一格放开空动作（口径「M 只派活」：不指定能力，也不该有填 action 的位置）。
        # 一次派活可以没有动作（动作由被派者自己选），此时那句"空话"是 `task`（活），
        # 而 `task` 必填由派活四个入口逐处守：`agent_loop._do_summon` / `_do_summon_many`、
        # `tools/conductor_tools.py` 的 `conductor.summon` / `conductor.summon_many`（`required` 里都有
        # `task`，处理器在不点时当场拒）。
        # 为什么必须放开：空动作的行会死在写行这一刻，连"派活被拒"的证据都留不下；
        # 判据改成"由派活入口保证带活"。
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
        if self.status == "block":
            # 「停了、没做完」必须留下为什么：翻这一档的是框架，而框架只知道停机理由
            # （预算耗尽 / 用户叫停 / 上级叫停）—— 那句理由写进 `detail`，读的人才知道
            # 这活是被谁、因为什么停下的（三态纪律：不许让"没做完"变成一行没有来路的空状态）。
            if not str(self.detail or "").strip():
                raise ValueError(
                    "status='block' 必须写 detail（为什么停下：预算耗尽 / 用户叫停 / …）—— "
                    "「停了、没做完」这一档不许没有来路")
            if self.outcome not in (None, "no_result"):
                raise ValueError(
                    f"status='block' 的 outcome 只能是 None 或 'no_result'，收到 {self.outcome!r}"
                    "（没做完就不是 ok / not_applicable）")
        if self.status == "cancelled" and self.outcome not in ("cancelled", "refused"):
            raise ValueError(
                "status=cancelled 时 outcome 必须是 'cancelled'（被取消）"
                "或 'refused'（因超预算/超截止被拒）—— 二者语义不同，但都属于'没做完'"
            )
        # ---- 父退场掐断那一档的两格必须成对（不许只有一半）
        #
        # 为什么两个方向都判：`outcome=cut_off_by_parent` 是"它怎么结束的"，`settled_at_parent_exit`
        # 是"谁写的这一行"。只判一个方向的话，会出现"写着被掐断、却没有标记"（读侧按标记筛
        # 就漏掉它）与"标了记、却写成 ok"（读侧按 outcome 筛就把它当成正常交付）两种半笔。
        if self.outcome == "cut_off_by_parent":
            if self.status != "done":
                raise ValueError(
                    "outcome=cut_off_by_parent 的 status 必须是 'done' —— 它不是"
                    "失败（代码没崩）、也不是取消（没人叫停），而是父代理退场时它还"
                    "在跑；终态该落在 done 上、由 outcome 说明结果未知"
                )
            if not self.settled_at_parent_exit:
                raise ValueError(
                    "outcome=cut_off_by_parent 必须同时置 settled_at_parent_exit=True ——"
                    "后者是'这一行由父的退场结算写成'的唯一标记"
                )
        if self.settled_at_parent_exit and self.outcome != "cut_off_by_parent":
            raise ValueError(
                f"settled_at_parent_exit=True 时 outcome 必须是 'cut_off_by_parent'，"
                f"收到 {self.outcome!r} —— 标了记却写着别的结局，读侧按哪一格筛都会漏"
            )
        if self.parent_task_id is not None:
            if not str(self.parent_task_id).strip():
                raise ValueError("parent_task_id 给了就必须非空（用 None 表示主控发起）")
            if str(self.parent_task_id) == str(self.task_id):
                raise ValueError("parent_task_id 不能指向自身")
        for a in self.artifacts:
            if not str(a).strip():
                raise ValueError("artifacts 不能含空元素")

        # ---- 工作项板的七条
        #
        # 口径：`kind == ""` ⇒ 老行 / 纯实例行，其余六格与 `keep_alive` 必须全空
        # ⇒ 加列对盘上已有的老行零影响（它们没有这几列）。
        if not self.kind:
            if (self.expects or self.item_state or self.item_close or self.seen_by
                    or self.seen_step is not None or self.keep_alive
                    or self.expects_was):
                raise ValueError(
                    "kind 为空（老行/纯实例行）时，工作项那几格与 keep_alive 必须全空 —— "
                    "否则这一行既算老行又带板状态，读它的人分不清以哪一格为准"
                )
        else:
            if self.kind not in ITEM_KINDS:
                raise ValueError(f"kind 必须是 {ITEM_KINDS} 之一或空串，收到 {self.kind!r}")
            # 空 `expects` 只开在撤销/作废之后的那一行（`done` + `expired`，见
            # `expects` / `expects_was` 两格的字段注释）；其余行仍只许 `ITEM_EXPECTS` 两档。
            empty_expects_ok = (self.expects == "" and self.item_state == "done"
                                and self.item_close == "expired")
            if self.expects not in ITEM_EXPECTS and not empty_expects_ok:
                raise ValueError(
                    f"kind 非空时 expects 必须是 {ITEM_EXPECTS} 之一"
                    f"（或撤销后 done/expired 行上的空串），收到 {self.expects!r}"
                    "（少了它就没有'什么算做完'的口径）"
                )
            if self.expects_was:
                if self.expects:
                    raise ValueError(
                        "expects_was 只在 expects 被清空时有意义 —— 两格同时非空，"
                        "读的人不知道哪一格才是现在的口径"
                    )
                if self.expects_was not in ITEM_EXPECTS:
                    raise ValueError(
                        f"expects_was 必须是 {ITEM_EXPECTS} 之一，收到 {self.expects_was!r}"
                        "（它是清空前的那一档，不许自由文本）"
                    )
            if self.item_state not in ITEM_STATES:
                raise ValueError(
                    f"kind 非空时 item_state 必须是 {ITEM_STATES} 之一，收到 {self.item_state!r}"
                )
            if self.item_state == "done":
                if self.item_close not in ITEM_CLOSES:
                    raise ValueError(
                        f"item_state='done' 必须给 item_close ∈ {ITEM_CLOSES}，收到 {self.item_close!r}"
                        "（'知道了'与'做完了'是两种收口，不许含糊）"
                    )
            elif self.item_close:
                raise ValueError("item_close 只在 item_state='done' 时有意义")
            # 交叉校验：两个字段各自为真、合起来是假话 —— 在这里拦。
            if self.item_close == "acked" and self.expects != "ack":
                raise ValueError(
                    "用 acked 收口只允许 expects='ack' 的项 —— "
                    "要交付的活不许靠'知道了'收掉（两个字段各自合法、合起来是假话）"
                )
            if self.item_close == "completed" and self.expects != "work":
                raise ValueError(
                    "用 completed 收口只允许 expects='work' 的项 —— "
                    "只要'知道了'的项不许被标成'做完了'（反方向同样拦）"
                )
            if self.item_state == "seen" and not str(self.seen_by or "").strip():
                raise ValueError(
                    "item_state='seen' 必须写 seen_by（谁读的）—— 空口 ack 的判据靠它配对（业主 A3）"
                )
            if (self.seen_step is None) != (not str(self.seen_by or "").strip()):
                raise ValueError("seen_by 与 seen_step 要么都在、要么都不在（半份读数比没有更糟）")
            if self.keep_alive and self.kind != "delegation":
                raise ValueError("keep_alive 只对 kind='delegation' 有意义（只有派活项才谈得上'待命'）")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 成本与评测口径（FC-19 / FC-24）

#: 花销台账的归口。为什么必须有受控词表：没有它，"这次花了多少"就没有可比口径
#: （"搜索"与"审校"的 token 花在一个池子里，等于什么也没说）。
#:
#: 六档，没有 `"other"`。为什么没有它：`modelgw.complete` 的 docstring 自己写着
#: "缺省也不许是「其它」：一个「其他」档会把「有人忘了写」伪装成一个正常的分类"，
#: 而 `"other"` 若在词表里，那句承诺在数据上就不成立：`Charge(scope="other")` 不拒，
#: `by_scope["other"]` 与正常档长得一模一样。一个"什么都不是"的档要么有真实产出点、
#: 要么不在词表里；今天没有任何地方会产出 `"other"`，所以按后者处置。
#: 编外的值不会被丢掉 —— `tokenmeter.by_scope` 把它们归到显式的 `SCOPE_UNCLASSIFIED`
#: 档并记下原值（那里能看出"有人写了一个编外归口"）。
USAGE_SCOPES = ("summon", "experiment", "search", "extract", "review", "reason")

#: "这一行没有可辨的归口"的显式取值。它不在 `USAGE_SCOPES` 里，理由是
#: 那六个值是调用方声明的用途，而这个值是读账方在遇到编外/空 scope 时的落位：
#: 把它塞进词表会让"有人写了一个编外归口"看起来像一个合法的分类
#: （G-20 的纪律逐字："缺省不许静默落到某个'其它'档"）。它只出现在只读汇总
#: （`tokenmeter.by_scope`）里；写入方必须给出 `USAGE_SCOPES` 里的一个值。
SCOPE_UNCLASSIFIED = "unclassified"

#: 每一档归口的产出点登记。值是一个二元组：
#: `(产出点标识, 说明)`，或 `None` 表示"本版本没有产出点"。
#:
#: 为什么需要它：`by_scope` 对每一档都给固定键，零值档也在场 ——
#: 于是"没有任何生产代码会产出这一档"与"查过、这一档没花钱"在产物里长得一模一样。
#: 把产出点写成一张可对账的表之后，"某一档归零"这件事才有确定的读法。
#:
#: 判据（`_assert_usage_scope_production_contract` 在导入期执行）：
#: `USAGE_SCOPES` 的每一档都必须在这张表里出现 —— 新增一档而不登记产出点，
#: 导入期就炸，而不是等读者从 `by_scope` 的全零里猜。
#:
#: 注意这张表是人写的声明，不是推导出来的：能推导出来的只有"源码里出现了
#: 这个字面量"，而那正是 `G-6` 要否掉的那种证据（`'other'` 在 modelgw 的自检里
#: 也出现过）。所以这里逐档写下"谁产出它"，由测试与真实产物两条判据交叉验证。
USAGE_SCOPE_PRODUCERS: dict[str, tuple[str, str] | None] = {
    "summon": ("conductor._charge_and_settle", "召唤级结算：Charge(scope='summon')"),
    "experiment": None,
    "search": None,
    # `extract` 的产出点是模型抽取那条通路（`projects.extract_with_model` 经
    # `modelclient.ModelClient` 调模型，归口 scope='extract'）：
    # 声明写着"没有代码会产出它"而实际有，就是一句假话（`G-6` 要防的正是这个）。
    "extract": ("modelclient.ModelClient.complete",
                "模型读本地文献那一步：charge_reply(scope='extract')"),
    "review": None,
    # `reason` 有两个产出点：`runflow` 的作答调用点，以及 `run-agent` 那条路的模型缝
    # （`llmseam.LlmSeam._charge_ledger`）。漏掉后者会让"谁产出这一档"这句声明
    # 变成一句半真的话（`G-6` 要防的正是"声明与产出脱节"）。
    "reason": ("runflow.SCOPE_ANSWER + llmseam.LlmSeam._charge_ledger",
               "两条路的 charge_reply/Charge 都归口 scope='reason'："
               "runflow 的作答调用点，与 run-agent 的模型缝（每次 LLM 调用一行）"),
}


def usage_scope_production() -> dict[str, str]:
    """每一档归口的产出状态（`G-6`）：`produced` / `not_produced`。

    刻意不把"没有产出点"折成 `False` 或空串：读的人要能一眼看出
    "这一档是查过没花钱"还是"根本没有代码会产出它"。两者在 `by_scope` 的全零里
    完全同形，这正是 `G-6` 登记的缺陷形态。
    """
    return {s: ("produced" if USAGE_SCOPE_PRODUCERS.get(s) else "not_produced") for s in USAGE_SCOPES}


def scopes_without_producer() -> list[str]:
    """本版本没有任何生产产出点的归口（按词表顺序）。"""
    return [s for s in USAGE_SCOPES if not USAGE_SCOPE_PRODUCERS.get(s)]


def _assert_usage_scope_production_contract() -> None:
    """导入期对账：词表的每一档都必须登记了产出状态，且不许登记词表外的档。

    与 `assert_process_id_contract()` 同一手法（声明面与派生面互相对账）：
    只比 `set(USAGE_SCOPES)` 与 `set(USAGE_SCOPE_PRODUCERS)` 是不对称的 ——
    前者多一档就漏了，后者多一档是垃圾。两条都判。
    """
    missing = [s for s in USAGE_SCOPES if s not in USAGE_SCOPE_PRODUCERS]
    if missing:
        raise AssertionError(
            f"归口 {missing} 没有在 USAGE_SCOPE_PRODUCERS 里登记产出点 —— "
            "新增一档归口时必须同时说明'谁产出它'，否则 by_scope 里的全零"
            "既可能是'没花钱'也可能是'没有产出点'，读者分不出来（G-6）"
        )
    extra = [s for s in USAGE_SCOPE_PRODUCERS if s not in USAGE_SCOPES]
    if extra:
        raise AssertionError(
            f"USAGE_SCOPE_PRODUCERS 登记了词表外的归口 {extra} ⇒ "
            "两张表已经分家，`by_scope` 的键集合不再等于词表（G-6）"
        )


_assert_usage_scope_production_contract()


@dataclass
class UsageEntry:
    """一笔花销（FC-19：token 预算是硬约束，且重试也计入）。

    ## 三条刻意的设计

    1. 零值也记。一次"跑了但没花 token"（例如纯本地计算）必须留下一条零值记录 ——
       否则"没记账"与"花了零"无法区分，而"预算还剩多少"这个问题就永远答不准。
    2. `attempts` 单独记。它是"这笔钱花了几次才花出去"的直接证据：
       每次重试都是一次新的计费请求（"Each retry is another billed provider request"）。
       只记总量不记次数，就无法发现"某条路径一直在重试"。
    3. `usd` 允许为 0（没有单价表时），但 `tokens_total` 与 `usd` 不能同时为 0
       且 `note` 为空 —— 那样这条记录不携带任何信息。
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
    #: 幂等键：同一个非空值在整张表里只能出现一次。
    #: 空串 = "这一行没有幂等身份"（历史行、以及直接调 `TokenMeter.charge` 的行），
    #: 不受唯一性约束 —— 把它也算进唯一性会让所有历史行互相冲突、整表提交炸掉。
    #: 为什么是字段而不是 `note` 里的文本标记：唯一性要由结构保证，不能靠文本约定。
    idem_key: str = ""

    def validate(self) -> None:
        require_id(self.usage_id, "usage_id")
        if self.scope not in USAGE_SCOPES:
            raise ValueError(f"scope 必须是 {USAGE_SCOPES} 之一，收到 {self.scope!r}")
        if self.tokens_in < 0 or self.tokens_out < 0 or self.tokens_total < 0:
            raise ValueError("token 数不能为负")
        if self.usd < 0:
                raise ValueError("usd 不能为负")
        if self.attempts is not None:
            if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
                raise ValueError(f"attempts 必须是整数，收到 {self.attempts!r}")
        if (self.attempts or 0) < 1:
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


#: FC-24 要求的必填口径字段。缺任一字段的评测数字不得进入对外报告。
#:
#: 为什么把这件事做成字段而不是"写文档时记得写"：
#: 同一个 miniF2F 数字可以是四件完全不同的事（97% = LLM judge 分、
#: 69% = 论文引用的文献 SOTA、34.8% = 端到端且与原始非形式题面比对后的精确值、
#: 40% = 同口径在原始 miniF2F 上的成绩），同对模型在两个口径下差 −13.5 ~ −29.5 点
#: （`08-…md` §A.5.5）。口径不是补充说明，口径就是那个数字的一部分。
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
    """一条带完整口径的评测结果（FC-24）。

    ## 2026-11-22：这张表已退役（`TABLES` 里没有 `eval_results`）

    行类型与 `EVAL_REQUIRED_FIELDS` **刻意保留**：它们是 `eval_results` 这张表
    「曾经长什么样」的声明，读侧宽容要用它 —— 历史工作区里的
    `data/eval_results.json` 仍按这一份形状校验（`store` 读侧按
    `RETIRED_TABLES` 认它、`validate_table` 走 `row_from_dict` 的同一条分支）。
    但**没有任何写点**：`TABLES` 里没有它、`store.tx` 拒它、`table.*` 拒它，
    `init()` 也不再建这份文件。理由与取证见 `RETIRED_TABLES` 那一格。

    渲染层 gate：任何引用它的断言，其 citation 必须能解析到一条字段齐全的记录；
    缺字段的数字不许进入对外报告。（这条口径本身没有失效，它跟着行类型一起
    留在只读一侧；没有产出方，所以今天没有任何一个数字能被它放行。）
    """

    eval_id: str
    claim_key: str
    benchmark: str
    benchmark_version: str
    split: str
    #: pass@k 的 k。`k == 1` 表示 pass@1。
    k: int
    value: float
    #: 去污染声明。必须显式写（哪怕是 "none"）—— "我们没做去污染"本身是必须披露的信息。
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
        # `k` 由下面 `_validate_k` 独占校验，所以它先从这条泛化判据里摘出去。
        #
        # `EVAL_REQUIRED_FIELDS` 里的 `k` 不走这条泛化判据：`str(getattr(self, f) or "")`
        # 会把 `0` 读成"空"，于是 `k=0` 报的是"缺少必填口径字段 ['k']"，把修法指错方向
        # （读者会去补字段，而真因是 `k < 1`）。
        # 剩下六个字段仍然走泛化判据 —— 它们没有第二处独立判据，不存在这个问题。
        missing = [
            f for f in EVAL_REQUIRED_FIELDS
            if f != "k" and not str(getattr(self, f) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"评测结果缺少必填口径字段 {missing}。"
                "**口径不是补充说明，口径就是那个数字的一部分**（FC-24）："
                "同一个基准的同一个数字在不同口径下能差 13–30 个百分点。"
                "缺任一字段的数字不得进入对外报告。"
            )
        self._validate_k()
        if not (0.0 <= float(self.value) <= 1.0):
            raise ValueError(
                f"value 是**比率**（0..1），收到 {self.value}。"
                "用百分数会让'97 与 0.97'在同一条记录里共存，口径立刻失准"
            )
        if self.samples is not None and self.samples < 1:
            raise ValueError("samples 给了就必须 >= 1")
        if not str(self.created_at or "").strip():
            raise ValueError("created_at 不能为空")

    def _validate_k(self) -> None:
        """`k` 的唯一判据：非空、不是布尔、是整数、从 1 开始。

        ## 为什么这四件事必须在同一处
        四件事（非空、不是布尔、是整数、从 1 开始）分散判会各自只说对一半：
        `str(k or "")` 把 `0` 当空串，于是 `k=0` 报"缺少必填口径字段 ['k']"（真因是 `k < 1`）；
        `if self.k < 1` 让 `k=True` 因为 `bool` 是 `int` 的子类而通过（`True < 1` 为假），
        于是"pass@True"这种无意义口径能进库；`k="1"` 过得了非空判据，然后在 `<` 上抛 `TypeError`
        —— 一个不是 `ValueError` 的异常从 `validate()` 里逃出去，而所有调用方都按
        "`validate()` 抛 `ValueError`"处理。合并成一处之后，"什么样的 k 合法"只有一个答案，
        且失败形态恒为 `ValueError`。
        ## 为什么拒绝 `bool` 与 `float`
        `k=True` 与 `k=1.0` 都能过宽松判据 —— 它们不是"另一种写法"，而是口径不明：读
        `eval_results` 的人无法判断 `1.0` 是"k=1"还是某处做了浮点运算漏了取整；`EvalResult.k`
        的声明类型是 `int`，留着"声明是 int、实际可以是 bool/float"这种缺口就是口径漏洞。
        `allows_sorry` / `samples` 是可选字段（口径未变）。
        """
        if self.k is None or (isinstance(self.k, str) and not self.k.strip()):
            raise ValueError("k 不能为空（pass@k 的 k 必填，见 EVAL_REQUIRED_FIELDS）")
        if isinstance(self.k, bool):
            raise ValueError(
                f"k 不能是布尔值（收到 {self.k!r}）—— bool 是 int 的子类，"
                "`True < 1` 为假，于是 k=True 会静默通过，"
                "把一个无意义的口径（pass@True）写进库"
            )
        if not isinstance(self.k, int):
            raise ValueError(
                f"k 必须是整数（收到 {self.k!r}，类型 {type(self.k).__name__}）—— "
                "浮点/字符串形态会让 k 的口径不可判定"
            )
        if self.k < 1:
            raise ValueError(f"k 从 1 开始（pass@k 的 k），收到 {self.k}")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- FC-05 顺序与集合分离

#: 每一个数组字段都必须在这里声明它是"集合"还是"序列"（FC-05）。
#: 不显式声明 ⇒ 所有数组都被默认当成集合（升序去重），而"顺序本身携带信息"
#: 的那些会被静默破坏（本项目因此丢掉了关系链的跳序，只能从 `origin` 字符串反解）。
#: - "set" —— 集合：必须升序且去重。`validate_table` 会集中检查，所以新增集合字段时不需要（也不
#:   应该）在自己的 `validate()` 里再手写一遍 `if x != sorted(set(x))` —— 那就是同一判据两处实现。
#: - "seq" —— 序列：保序、不许排序去重。必须有 round-trip 测试（写→读→逐元素相等），否则"保序"
#:   只是一句声明。- 未声明 —— 不允许：`verify` 会报 `undeclared_array_field`。
#: 为什么用"未声明即报错"而不是"默认按集合处理"：默认值会静默把序列当集合，而那正是 FC-05 要修的缺陷。
ARRAY_FIELD_KINDS: dict[str, dict[str, str]] = {
    "search_requests": {
        "result_lit_ids": "set",
        # `providers` 是 seq 而不是 set：A 按这一行给出的次序依次问各个源，
        # 而跨源合并是「先到者优先」（检索层只填空缺、不覆盖已有值）
        # ⇒ 次序变了，「同一篇文献最终采信谁的元数据」就变了。
        # 声明成 set 会让集中检查在写盘那一刻要求升序去重，于是调用方给的次序
        # 被静默重排 —— 那正是 FC-05 要防的形态（顺序本身携带信息）。
        "providers": "seq",
    },
    # 作者顺序是有意义的（第一作者 ≠ 末位作者），所以是 seq。
    "literature": {"source_request_ids": "set", "authors": "seq"},
    # 别名顺序影响展示与"主名"判断；`related_concepts` 是纯集合。
    # 概念行已并进 `statements`：概念的别名落在 `statements.aliases`（同表已声明 "seq"），
    # `related_concepts` 由 `relations` 表管。
    "relations": {"concept_ids": "set", "supporting_lit_ids": "set"},
    "reprocess_requests": {"relation_ids": "set", "touched_relation_ids": "set"},
    "research_questions": {
        "related_concept_ids": "set",
        "related_relation_ids": "set",
        "evidence_lit_ids": "set",
        "waiting_request_ids": "set",
        "contradiction_relation_ids": "set",
        "contradiction_request_ids": "set",
        # 这一对就是 FC-05 的正面范例：同一个链条，两个字段。
        # `related_relation_ids` 是集合（"引用了哪些知识"，升序、可比较、可查重）；
        # `relation_chain` 是序列（"按什么顺序走的"，保序、就是推理路径本身）。
        # 合成一个字段就必然丢掉一半信息。
        "relation_chain": "seq",
    },
    # 触点：`ARRAY_FIELD_KINDS` 是"哪些数组字段当集合/序列"的登记表，未声明即 `verify` 报
    # `undeclared_array_field`（不静默 —— 这正是 FC-05 要防的"静默把序列当集合"）。
    # `experiment_ids` 是纯集合（检验过它的实验，顺序无意义），故 "set"。
    "conjectures": {"experiment_ids": "set"},
    "analysis_reports": {},
    # 产物列表的顺序有意义（生成顺序）；重复的产物引用没有意义，但"顺序"更重要，
    # 所以是 seq 而不是 set。
    "experiments": {"artifact_paths": "seq"},
    # 子目标与轮次历史的顺序就是攻坚过程本身，绝不能排序。
    "attack_plans": {"subgoals": "seq", "history": "seq"},
    # 章节顺序、断言顺序、开放问题顺序都是有意义的。
    "documents": {"sections": "seq", "claims": "seq", "open_problems": "seq"},
    "dependencies": {},
    # 命题台账的 `derived_from` 是集合：一条命题用到哪几条别的命题，
    # 顺序没有数学含义（去重才有：重复引用会让"承重面"计数虚高）。
    "statements": {"derived_from": "set", "aliases": "seq"},
    "review_findings": {},
    "tasks": {"artifacts": "set", "inputs": "set"},
    "usage_ledger": {},
    # 待新增文献列表：没有任何数组字段 —— 空 dict 是"这张表没有
    # 数组字段"这个事实本身，不是"忘了登记"。登记它是必须的：未登录的表会让
    # `verify` 的 `undeclared_array_field` 在将来有人加一个 list 字段时失去对象。
    "lit_candidates": {},
}


def array_kinds(table: str) -> dict[str, str]:
    """某张表的数组字段声明。未登记的表返回空 dict（不是 None —— 空是"没有数组字段"）。"""
    return dict(ARRAY_FIELD_KINDS.get(table, {}))


def _set_problems(field: str, val: Any) -> list[str]:
    """一个「声明为集合」的数组字段现在的形状问题（先把元素类型判掉，再做升序去重）。

    ## R-05：为什么必须先判类型：`related_concepts=["0001", 2]` 这样的混合类型数组会让
    `list(val) != sorted(set(val))` 在比较 `str` 与 `int` 时抛 `TypeError`。那不是"库里有一条坏数据"，而是
    判据自己炸了：`validate_table` 只把 `ValueError` 当"这一行不合法"（`except ValueError`）；`store.rebuild`
    的灾难恢复链同样只接 `ValueError` ⇒ 一条混类型的行会以 `TypeError` 打断整次重建，而重建是不可逆的那条路。
    所以元素先判、异类型不比较，三档各自给一条问题描述（每一档至多一条 —— 表级调用方按"一条问题 = 一个坏
    字段"读，`tests/test_coverage_schema.py` 的 `len(bad) == 1` 就是这条口径）。
    ## 文案为什么保留"未升序去重"四个字：它与"值不是数组"/"元素不是字符串"是三件不同的事，而看这句话的人
    要去改的东西完全不同（改排序 / 改形状 / 改元素类型）；既有的判据按这四个字认它，所以这里逐字保留。
    """
    if not isinstance(val, (list, tuple)):
        return [f"{field} 声明为集合但值不是数组：{type(val).__name__}"]
    if any(not isinstance(v, str) for v in val):
        return [f"{field} 声明为集合但元素不是字符串：{[type(v).__name__ for v in val]}"]
    if list(val) != sorted(set(val)):
        return [f"{field} 声明为集合但未升序去重：{list(val)}"]
    return []


def normalize_set_fields(table: str, raw: Any) -> list[str]:
    """把「声明为集合」的数组字段在写入前排序去重（就地改 `raw`，返回被改动的字段名）。

    ## 写侧为什么是归一化而不是拒收
    模型的输入 `concept_ids=["000004","000002"]` 与 `["000002","000002"]` 表达得完全
    清楚 —— "这几个概念之间有关系"。"集合的规范形态是升序去重"是我们自己的存储
    契约，不是它对这件事的表态。写侧若只有拒收（`_set_problems` 的"未升序去重"），
    模型写错次序一次、读一次拒信、再猜一次，同一个坑会连踩好几次。
    ⇒ 写侧改成"排序去重后照收"，并把改动过的字段名回给调用方（`tools/table_tools.py`
    把这份读数落在返回值的 `normalized` 格上）。"我改过你的输入"因此可查，不是静默改。

    ## 判据只有一张表：集合字段的唯一声明面是 `ARRAY_FIELD_KINDS`（`kind == "set"`）
    这里遍历的字段与 :func:`check_array_invariants` 是同一张表、同一个 `kind`；两处各写
    一份名单必然漂，而漂的形态是"归一化了一格、检查着另一格"（本仓反复踩过的形态）。

    ## 只归一"形态已经合法"的值（不许放宽真正的类型/形态校验）
    不是数组 / 元素不是字符串 ⇒ 原样留着，让 `_set_problems` 照旧拒它。归一化只回答
    "这几个元素的次序与重复要不要动"，不回答"这个值能不能收"：`"abc"` 这种不成立的号
    在排序之后仍然要过 `require_id`（`Relation.validate` 等），于是它照旧被拒（拒信从
    "未升序去重"变成"concept_ids[] 必须是…"——后者才是真问题）。"号存不存在"更不在这一
    格的职权内：那是审计期 `verify` 的 `dangling_*`。

    ## 返回值的用法（三态纪律）
    空列表 = 这一笔一个集合字段都没动（不是"没查"：本函数每次都会遍历全部已声明的集合字段）。
    """
    changed: list[str] = []
    if not isinstance(raw, dict):
        # 载荷不是对象 ⇒ 这里没有可归一的东西；"这一行不合法"由 `row_from_dict` / `validate` 报。
        return changed
    for fname, kind in array_kinds(table).items():
        if kind != "set" or fname not in raw:
            continue
        val = raw[fname]
        if not isinstance(val, (list, tuple)):
            continue            # 交给 `_set_problems` 的"值不是数组"那一档
        if any(not isinstance(v, str) for v in val):
            continue            # 交给 `_set_problems` 的"元素不是字符串"那一档（混类型不许在这里比）
        want = sorted_unique(val)
        if isinstance(val, list) and val == want:
            continue
        # tuple 也收（Python 调用方），落盘形态统一成 list；这也算"改动过"，如实记一笔。
        raw[fname] = want
        changed.append(fname)
    return changed


def check_array_invariants(table: str, obj: Any) -> list[str]:
    """集中检查某行的所有已声明为集合的数组字段是否升序去重。

    返回违规描述列表（空 = 通过）。由 :func:`validate_table` 调用 ——
    这就是"集合字段的升序去重"这件事的唯一权威检查点。

    ## 它与写侧归一是两件事，别把这一条删掉
    `tools/table_tools.py` 的两个写口在进校验之前先调 :func:`normalize_set_fields`
    （模型给的 `["000004","000002"]` 被排好序再收），所以从那条路写进来的行不会
    撞到这里。这一条仍然必须留着：它是落盘契约（`store.tx` 的提交块与 `rebuild` 都走
    `validate_table`），管的是"绕过写口直接拼一行"的那些写者 —— 归一是"替模型改输入"，
    不是"放宽盘上的形态"。正控见 `tests/test_store_concurrency.py` 与
    `tests/test_coverage_schema.py`（它们直接写坏行，必须照旧被拒）。

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
        # R-05：三档判据（不是数组 / 元素不是字符串 / 未升序去重）只在 `_set_problems` 里，
        # 行级 `validate()` 与这里调的是同一个谓词 —— 两处各写一遍必然漂，
        # 而漂的形态正是"表级放行、行级炸"或反之。
        bad.extend(_set_problems(fname, val))
    return bad

# ---------------------------------------------------------------- 表级容器
#: 表名 -> (文件名, 行类, ID 前缀规则)
TABLES: dict[str, dict] = {
    "search_requests": {"file": "search_requests.json", "row": SearchRequest, "id_field": "request_id", "id_kind": "request"},
    "literature": {"file": "literature.json", "row": Literature, "id_field": "lit_id", "id_kind": "lit"},
    # `concepts` 表不存在（`SCHEMA_VERSION=2` 并进 `statements`）：概念行以
    # `kind="concept"` 住进下面的 `statements`。删掉之后 `store.rows("concepts")`
    # 走 `store._MOVED_TABLES` 那条受控错 + 指路，不是"未知表"这种读不出下一步的错。
    "relations": {"file": "relations.json", "row": Relation, "id_field": "relation_id", "id_kind": "relation"},
    "research_questions": {"file": "research_questions.json", "row": ResearchQuestion, "id_field": "question_id", "id_kind": "question"},
    # 猜想：独立对象，不是问题的一个 kind —— 理由见类的 docstring。
    "conjectures": {"file": "conjectures.json", "row": Conjecture, "id_field": "conjecture_id", "id_kind": "conjecture"},
    "analysis_reports": {"file": "analysis_reports.json", "row": AnalysisReport, "id_field": "report_id", "id_kind": "report"},
    "reprocess_requests": {"file": "reprocess_requests.json", "row": ReprocessRequest, "id_field": "reprocess_id", "id_kind": "reprocess"},
    "experiments": {"file": "experiments.json", "row": Experiment, "id_field": "experiment_id", "id_kind": "experiment"},
    "attack_plans": {"file": "attack_plans.json", "row": AttackPlan, "id_field": "plan_id", "id_kind": "plan"},
    "documents": {"file": "documents.json", "row": Document, "id_field": "doc_id", "id_kind": "doc"},
    "dependencies": {"file": "dependencies.json", "row": Dependency, "id_field": "dep_id", "id_kind": "dep"},
    # 命题台账：知识实体，所以吃编号空间（见 ID_COUNTERS）。
    # 放在 dependencies 之后：命题是依赖的锚点，两者相邻便于读图（`store.LOCK_ORDER` 同序）。
    "statements": {"file": "statements.json", "row": Statement, "id_field": "stmt_id", "id_kind": "stmt"},
    "review_findings": {"file": "review_findings.json", "row": ReviewFinding, "id_field": "finding_id", "id_kind": "finding"},
    "tasks": {"file": "tasks.json", "row": Task, "id_field": "task_id", "id_kind": "task"},
    "usage_ledger": {"file": "usage_ledger.json", "row": UsageEntry, "id_field": "usage_id", "id_kind": "usage"},
    # `eval_results` **不在这里**：2026-11-22 退役（见 `RETIRED_TABLES`）。
    # 它曾在这里（`id_kind="eval"`）；退役后新工作区不再生成这份文件，
    # 历史工作区里的那一份由读侧按 `RETIRED_TABLES` 认它并报"已退役"。
    # 待新增文献列表：一次检索的候选先进这里，审完才入 literature。
    # `slot` 吃的是编号空间（`ID_COUNTERS["candidate"]`）：它必须只增不复用
    # （撤掉的槽位照样占着号），而"不复用"这件事只能由发号器保证 —— 手写序号迟早会重用。
    "lit_candidates": {"file": "lit_candidates.json", "row": LitCandidate,
                       "id_field": "slot", "id_kind": "candidate"},
}


# ---------------------------------------------------------------- 退役表（只读一侧）
#
# 一张表怎么"退干净"，四件事缺一不可：
#   ① 不在 `TABLES` 里 ⇒ `init()` 不再建文件、`table.*` 不认它、`store.tx` 拒它；
#   ② 在 `RETIRED_TABLES` 里留名 ⇒ 历史工作区里那份文件**不是**"畸形/未知"，
#      读侧认得出它并报"已退役"（三态：读到旧表 ≠ unknown、≠ pass）；
#   ③ 行类型与口径字段留在只读一侧 ⇒ 历史文件仍按原形状校验，不因为表没了就变成
#      "谁也读不懂的一坨 JSON"；
#   ④ 引用面（`CITATION_PREFIXES` / `refspecs`）跟着摘 ⇒ 退役之后它不再是合法的
#      写入面 / 引用前缀（"半套"就是把前缀留着、表却没了）。
#
# 为什么不做成 `TABLES` 里的一个 `retired: True` 旗标：那样每一处 `for table in
# TABLES` 都得自己记得"跳过退役的"（`init` / `verify` / `doc_tools` / 迁移……），
# 漏一处就是一个静默的半退役形态。清单分家之后，"在表里"与"在退役名单里"互斥，
# 由 `retired_tables()` 与导入期断言对账。

#: 已退役的表：名字 → 文件 / 行类型 / 主键 / 为什么退 / 历史文件怎么读。
#:
#: `eval_results`（2026-11-22 退役，业主已批"派人做"）：
#:   · **全仓 0 个写点** —— 产品代码里没有任何 `upsert`/`insert` 指向它
#:     （AST 实扫；判据 `tests/test_eval_results_has_no_producer.py` 的正控扫的就是它）；
#:   · **51 个工作区全是 0 行**（`projects/*/data/eval_results.json` 逐个 parse，
#:     `rows` 全空；同一次普查里 `reprocess_requests` 也是 51/0）；
#:   · 它只活在"登记 + 读口"里：`verify` / `doc_tools.citation_coverage` / `refspecs`
#:     都只是读它，读到的永远是 0 行 ⇒ 那些读数从来没有信息量，却让"评测这一档"
#:     看起来被审计过（`docs/REPRO-eval-results-no-producer.md` 的既有结论）。
#:   · 为什么退役而不是补产出方：FC-24 的口径字段是真要求，但"谁来产出"这件事
#:     一直没有主；留着一张没人写的表，等于把"没有产出方"伪装成"评测 0 行"。
RETIRED_TABLES: dict[str, dict] = {
    "eval_results": {
        "file": "eval_results.json",
        "row": EvalResult,
        "id_field": "eval_id",
        "retired_at": "2026-11-22",
        "why": "全仓 0 个写点 + 51 个工作区全 0 行 ⇒ 从来没有产出方；"
               "只留读口会让『没有评测』读成『评测 0 行』",
        "how": "历史工作区里这份文件仍在盘上：读侧按 `RETIRED_TABLES` 认它、"
               "返回 `retired=true`（行照旧读得出来），不报畸形、不报未知表；"
               "`init()` 不再生成它，`table.*` / `store.tx` 一律拒写。"
               "要恢复评测这一档：先补产出方与验收判据，再把这一格搬回 `TABLES`"
               "（两处都在本文件，导入期断言会逼人同时改；`docs/REPRO-eval-results-no-producer.md` 有复算命令）",
    },
}


def retired_table(name: Any) -> dict | None:
    """这张表是不是已退役（是 ⇒ 那一格；否 ⇒ None）。

    唯一读口：`store` 的读侧宽容、`table_tools` 的拒信、判据都调它，别各自
    `S.RETIRED_TABLES.get(...)` 抄一遍（"同一判据两个落位"是本仓反复踩的形态）。
    """
    return RETIRED_TABLES.get(str(name or ""))


def retired_tables() -> frozenset[str]:
    """全部已退役的表名（判据与读数用；反真空打桩的对象就是它）。"""
    return frozenset(RETIRED_TABLES)


# ---------------------------------------------------------------- 已登记但未启用的表
#
# 与 `RETIRED_TABLES` 的分界（这一格存在的全部理由）：
#   · 退役 = **没有产出方**（写代码根本不存在）⇒ 表从 `TABLES` 摘掉；
#   · 未启用 = **产出方与消费方都在、闸也在，只是从来没有一趟真的跑过**
#     ⇒ 表留着，但把"未启用"写成机器可读的登记面，而不是靠一句注释。
#
# `reprocess_requests`（2026-11-22 判"未启用"，不是退役）：
#   · 写点：F 的 `submit_reprocess_request`（`agent_f/core.py`，I4 闸门后落一行）
#     + B 的 `reprocess_once` / `reprocess_claim` / `reprocess_failed`（认领、失败、
#     完成各一笔）—— 两侧都是人写过的代码路径，整条线是通的；
#   · 读数：51 个工作区 0 行（与 `eval_results` 同一次普查），`counters.json` 里
#     连 `p` 号段都没有 ⇒ 从来没有一条请求被提交过；
#   · 变数：2026-11-22 收口第 2 笔（`221f9ab2`）把 B 侧"重抽取"那条 skill 删了
#     （52→50 条 skill）⇒ 今天 B **不会被告知**去认领这条队列，而 F 的声明里
#     仍教它提交 ⇒ 一条真提交会永久 pending，把 `unfinished_request_rows` 顶红。
#   · 为什么判"未启用"而不是退役：退役要同时摘掉 F 的动作、B 的动作、I4 闸门与
#     两份 role spec（`specs/*` 在 p316 冻结、`interactions.py` 在 FC-27）——
#     只摘一半就是"留下半套"，比留着更坏；而那几处今天都不在本笔的允许改动面里。
#     所以本笔只做两件事：① 把"未启用"登记成下面这一格（单一落点）；
#     ② 让收工门的读数说清"这条队列未启用"，而不是把它读成"没人做"。
#   待办（需要 p316 之后的一次协调批）：要么恢复 B 的 skill，要么把 F 的
#   `submit_reprocess_request` 与 `admit_reprocess_request` 一起摘掉 —— 二选一，
#   不许让"F 教着提交、B 不再被告知"这个不对称继续存在。
NOT_ENABLED_TABLES: dict[str, dict] = {
    "reprocess_requests": {
        "since": "2026-11-22",
        #: 谁会写它（登记面，不是实现；实现指针写在下面 `producers` / `consumers`）。
        "producers": ("agent-F:submit_reprocess_request",),
        "consumers": ("agent-B:reprocess_once",),
        "evidence": "51 个工作区 0 行、`counters.json` 无 `p` 号段；"
                    "B 侧 skill 已于 2026-11-22 退役（52→50）",
        "to_enable": "恢复 B 的『重抽取』skill（或改由别的角色认领），"
                     "并跑一条真请求把 `unfinished_request_rows` 走到 0；"
                     "否则整条线一起退役（F 的动作 + I4 闸门 + 两份 role spec 同批摘）",
    },
}


def not_enabled_table(name: Any) -> dict | None:
    """这张表是不是"已登记、未启用"（是 ⇒ 那一格；否 ⇒ None）。"""
    return NOT_ENABLED_TABLES.get(str(name or ""))


#: 编号空间计数器覆盖的表（search_requests 用 r-NNNNNN，reprocess_requests 用 p-NNNNNN，
#: 都不占用编号空间 —— 它们是过程记录，而编号空间留给知识实体）。
ID_COUNTERS = {
    "lit": "lit_id",
    # `concept` 那一档随并表退役：表没了而类别还在的话，`verify` 的
    # `verify._check_1` 的计数器那一段会反查不到表，每次审计都报一条 `counter_table_missing` ——
    # 那是"已经不存在的表"，不是缺陷。`counters.json` 里那份残留值无害
    # （`verify` 只遍历这张表，未知类别根本不看）。
    "relation": "relation_id",
    "question": "question_id",
    "conjecture": "conjecture_id",
    "report": "report_id",
    "experiment": "experiment_id",
    "plan": "plan_id",
    "doc": "doc_id",
    "dep": "dep_id",
    # 命题台账吃编号空间：一条命题是知识实体，
    # 不是过程记录 —— 它会被别处引用（`dependencies.used_by`、报告的承重栏），
    # 而过程记录式的短号（`s-NNNN`）在跨会话引用时读不出"这是哪一条"。
    "stmt": "stmt_id",
    "finding": "finding_id",
    "usage": "usage_id",
    # `eval` 那一档随表退役（2026-11-22）：表没了而类别还在的话，`verify` 的
    # 计数器那一段会反查不到表、每次审计都报一条 `counter_table_missing` ——
    # 那是"已经不存在的表"，不是缺陷。`counters.json` 里不会有 `eval` 这一格
    # （实测 51 个工作区全是 0 次发号、一格都没有），残留值也无害
    # （`verify` 只遍历这张表，未知类别根本不看，如 `concept` 那 9 个工作区）。
    # 待新增文献列表的槽位号：与其余知识实体同样吃编号空间 ——
    # "序号不复用"必须由发号器保证（见 `TABLES["lit_candidates"]` 的注释）。
    "candidate": "slot",
}


# ---------------------------------------------------------------- 号段：一种角色一套号
#
# 业主口径（2026-11-19）：号**由系统统一发**（顾客排队拿号，取号是系统一个逻辑），
# 要私有的是「号之外的账」；而号本身按**角色**分格：一种角色一套号。
#
# 今天绝大多数实体类恰好只服务一个角色（plan 只由 F 发、doc 只由 G 发，
# stmt / lit / relation … 各自的写者也只有一支），「一类一格」与「一角色一格」
# 在它们身上说的是同一件事 ⇒ 不需要登记。唯一不合口径的是 `experiment`：
# E 写 numeric / symbolic / exhaustive，L 写 formal，两种角色共用一条号段
# （改前 `store.alloc_id("experiment")` 是一格，E 发 000000、L 接着发 000001）。
#
# 所以这里只登记「同一类实体确实由多个角色发号」的那几类，给每个角色一段**互不穿插**
# 的号段（号段 = 这个角色独占的那半段号；6 位空间对半分，各 50 万号，两个角色谁先
# 发都不影响对方，谁都不可能拿到别人的号）。类别没有登记 ⇒ 就是旧形态（一格、从 0 起），
# 一个字节都不变。
#
# 为什么不是「两格计数器、都从 000000 起」（手稿族那样的形状）：`experiments` 的主键
# 只有一列 `experiment_id`，两族都从 0 起会当场撞主键，而 `upsert` 按主键替换 ⇒
# 静默覆盖别人的行。手稿那边能用「都从 000000 起」是因为身份是 `(族, 号)` 两列；
# 实验行的身份只有号这一列 ⇒ 号段是对半分，不是各从 0 起。
#
# `store.alloc_id(kind, segment=…)` 是唯一的发号口（计数器的键 = `kind` 或
# `kind:<角色>`；`counter_key()` 是这层编码的唯一来源）。`verify` 的连续性 / 计数器
# 两项按号段各查一遍（见 `counter_bands()`）。
ID_SEGMENTS: dict[str, dict[str, int]] = {
    # 实验号：E 拿前半段（numeric / symbolic / exhaustive），L 拿后半段（formal）。
    # E 那一段的标签是空串 —— 它与改前的「一格、从 0 起」逐字同形，于是存量工作区的
    # `counters.experiment` 原地继续给 E 用（不需要迁移、也不会从头重发号）。
    "experiment": {"": 0, "L": 500_000},
}

#: 角色 → 号段标签（只有登记过号段的类别需要这一张）。
#:
#: 为什么不从角色名直接拼段标签：段标签是 `counters.json` 里的键的一部分（`counter_key`），
#: 它必须与 `ID_SEGMENTS` 的标签逐字一致才读得到那一段；把「E 用空串」这件事写在
#: 角色映射里，是为了让 E 的计数器键保持改前的 `experiment`（存量兼容），同时 L 拿到
#: 自己那一格。没登记这句角色的类别 / 角色 ⇒ 空串 = 唯一那一段。
ROLE_SEGMENTS: dict[str, dict[str, str]] = {
    "experiment": {"E": "", "L": "L"},
}


def counter_bands(kind: str) -> dict[str, tuple[int, int]]:
    """这个 ID 类别的号段表：`{角色标签: (起, 止)}`（闭区间）。

    没登记号段的类别 ⇒ `{"": (0, 10**ID_DIGITS - 1)}`：一格、从 0 起，与改前逐字相同。
    登记过的类别按起点排序，每段到下一段的起点前一位为止、最后一段到编号上限。
    """
    top = 10 ** ID_DIGITS - 1
    starts = ID_SEGMENTS.get(str(kind or ""))
    if not starts:
        return {"": (0, top)}
    ordered = sorted((int(base), str(label)) for label, base in starts.items())
    out: dict[str, tuple[int, int]] = {}
    for index, (base, label) in enumerate(ordered):
        end = ordered[index + 1][0] - 1 if index + 1 < len(ordered) else top
        out[label] = (base, end)
    return out


def id_counter_key(kind: str, segment: str = "") -> str:
    """计数器在 `counters.json` 里的键：一格类别是 `kind`，分号段的类别是 `kind:<角色>`。

    这是这层编码的**唯一来源**：`store.alloc_id` / `Store.set_counters` / `verify` /
    `rebuild` 都读它，谁也不自己拼字符串（拼错了会造出一个没人读的数字）。
    """
    name = str(kind or "")
    seg = str(segment or "")
    return f"{name}:{seg}" if seg else name


def segment_for_role(kind: str, role: Any) -> str:
    """这个角色发这一类号时用哪一段（没在这张表里登记 ⇒ 空串 = 唯一那一段）。"""
    mapping = ROLE_SEGMENTS.get(str(kind or ""), {})
    return str(mapping.get(str(role or "").strip(), "") or "")


def segment_of_id(kind: str, value: Any) -> str:
    """这个号落在哪一段（读不出来 / 认不出 ⇒ 空串）。

    号段只有登记过才有「认不认」这回事：没登记的类别一律空串。登记过的类别里，
    一个号必须在某一段的闭区间内 —— 落在段外（手工改过号 / 从旧库恢复）⇒ 空串，
    由 `verify` 的计数器那一段点名，而不是在这里猜一个段。
    """
    if not ID_SEGMENTS.get(str(kind or "")):
        return ""
    text = str(value or "").strip()
    if not text.isdigit():
        return ""
    number = int(text)
    for label, (base, end) in counter_bands(kind).items():
        if base <= number <= end:
            return label
    return ""


# ---------------------------------------------------------------- 过程记录 ID

#: 过程记录 ID 的形态：`<前缀>-NNNNNN`（前缀是字母数字、且不带连接号）。
#: 与编号空间的 `_ID_RE` 成对：两者互斥，而"互斥"正是
#: "过程记录不占编号空间"这句话可判定的原因。
#: 号身认"当前宽度或旧四位"（读侧兼容，口径与 `is_valid_id` 同一处）——
#: 盘上 `t-0252` 这类历史行必须照样读得进来。
_PROCESS_ID_RE = re.compile(rf"^[A-Za-z][A-Za-z0-9]*-{ID_OR_LEGACY_PATTERN}$")

#: 过程记录前缀的唯一来源就是"哪些表不在 `ID_COUNTERS` 里"。
#: 不写死前缀名单（`r` / `p` / `t`）的理由：那会是第二份实现，而两份名单一旦漂移，
#: `verify` 的 `_id_contiguity` 会对过程记录号做 `int()` 并把审计自己搞崩。
#: 这里的判据只有一条：`id_field` 不被 `ID_COUNTERS` 覆盖的表就是过程记录。
#: 于是新增一张过程记录表时它会自动被算进来，不需要谁记得改这里。


#: 过程记录类别 -> 它的 ID 前缀（声明面）。
#:
#: 为什么需要一个声明面，而不是全靠从 `ID_COUNTERS` 推：那样推出来的判据是
#: 同义反复。`process_id_kinds()` 的定义是"`id_field` 不被 `ID_COUNTERS`
#: 覆盖的那些表"，于是 `set(ID_COUNTERS) & process_id_kinds()` 恒为空 ——
#: 有人往 `ID_COUNTERS` 里塞 `"task": "task_id"` 时，`tasks` 会同时从
#: `process_id_kinds()` 里掉出去，交集照样为空，判据一声不响。
#: 所以这里把契约的另一半写下来，让两边互相对账（本项目对"同一件事两个落位"
#: 的标准做法，见 `.noai-paths` 与 `AGENTS.md` 的按位比对）：
#: 声明面（本表）与派生面（`TABLES` + `ID_COUNTERS`）一旦不一致就导入期炸。
PROCESS_ID_PREFIXES: dict[str, str] = {
    "request": "r",     # search_requests.request_id  = "r-NNNNNN"
    "reprocess": "p",   # reprocess_requests.reprocess_id = "p-NNNNNN"
    "task": "t",        # tasks.task_id = "t-NNNNNN"（见 Task.task_id 的说明）
}


# ---------------------------------------------------------------- 主键由谁分配

#: 带前缀的号：`rel-000001` / `stmt-1` / `p-1` 这一族（"模型按直觉手填"的形态）。
#:
#: 与 `_PROCESS_ID_RE` 刻意不同：那条要求"前缀 + 连接号 + 当前宽度（或旧四位）的数字"，
#: 于是 `stmt-1` / `rel-1` 会从它下面溜过去 —— 而它们正是模型写出来的形态
#: （B 会按 `rel-` 前缀的直觉填 `relation_id`）。这里问的只是形态
#: "这是不是一个带前缀的号"，不问它合不合法、位数够不够。
_PREFIXED_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-")


def looks_like_prefixed_id(value: Any) -> bool:
    """这个值是不是"带前缀的号"（`rel-000001` / `stmt-1` / `p-1`）。

    唯一用途：`tools/table_tools.py` 判"模型把一个本该由台账分配的号手填了"。
    它是那条受控拒绝的检测谓词，所以单独成一条函数：负控（"把它打桩成永假 ⇒
    那条拒绝必须变红"）才有对象可打。

    放在 `schema` 的理由：`ID_COUNTERS` / `PROCESS_ID_PREFIXES` 是"哪个前缀是人工号"
    的唯一声明面，工具层只该拿这条谓词，不另写一份正则。
    """
    return isinstance(value, str) and bool(_PREFIXED_ID_RE.match(value.strip()))


def id_allocator_kind(table: str) -> str:
    """这张表的主键由谁发号：`"counter"`（编号空间）或 `"prefix"`（过程记录）。

    空串 = 未知表。返回值是"这一格该不该手填"的唯一机器可读依据 ——
    两种都由台账分配（发号点只有 `tools/table_tools.py::_allocate_id` 一处，它再分派到
    `store.Tx.alloc_id` 或 `interactions.next_prefixed_id`），区别只在形态：
      - `"counter"`：`ID_COUNTERS` 覆盖的那几类 ⇒ 当前宽度（六位）十进制，如 `000000`；
        模型不该手填它，`rel-000001` / `stmt-1` 这种前缀号一律不认。
      - `"prefix"`：`PROCESS_ID_PREFIXES` 覆盖的那几类 ⇒ `<前缀>-号码`，如 `r-000001`；
        这一格允许手填人工号，但前缀必须是那张表自己的（`search_requests` 只认 `r`）。

    ## 为什么这条要显式写成一个函数而不是留在注释里
    "哪些编号自动分配、哪些要手填"若只散落在各表的 `id_field` 与几个 `validate()` 里，
    模型读不到 ⇒ 它会按 `rel-` 前缀编一个号。判据一旦可执行，就能被对账：
    `tests/test_hand_filled_ids_are_refused.py` 遍历 `TABLES` 断言
    "没有任何一张表的主键是外部给的"（返回值不为空串），于是将来新增一张"主键由
    调用方给"的表时，那句"所有主键都由台账分配"的文案会当场变红。
    """
    spec = TABLES.get(str(table or ""))
    if spec is None:
        return ""
    return "counter" if spec["id_kind"] in ID_COUNTERS else "prefix"


# ---------------------------------------------------------------- 引用前缀

#: 引用前缀 -> 它指向哪张表（`documents.claims[].citations` 的受控前缀表）。元素是 `前缀:代号`
#: （`lit:0003#p.4` 这种带页码/锚点的写法按同一个代号算，见 `textutil.citation_ref_parts`）。
#: "这个前缀认不认、指向哪张表"必须有一处真身：散在多个落位时，同一个字符串
#: "写入期认、审计期不认"不会有任何东西会红。对账见
#: `assert_citation_prefix_contract()`（导入期自动跑一次）。
#: `stmt` 是正文断言引命题的落点 ⇒ `closing` 的污染面从"命题之间"扩到
#: "哪几条正文断言压在这条命题上"。
#: 顺序沿用 `verify.CITATION_KINDS` 的顺序，于是"同一个集合的不同排列"在 diff 里一眼可见。
CITATION_PREFIXES: dict[str, str] = {
    "rel": "relations",
    "lit": "literature",
    "exp": "experiments",
    # `eval` **留着**（2026-11-22：表退役，引用前缀不摘）。这一格是读侧宽容的一部分：
    # ① `verify` 的 `_BRANCH_KINDS` 在导入期与 `CITATION_PREFIXES` 逐字对账
    #    （`assert set(CITATION_KINDS) == set(_BRANCH_KINDS)`），摘掉前缀会让
    #    `verify.py`（FC-27）当场导入失败 —— 而"退役一张表"不该把审计器本身炸掉；
    # ② 历史文档里若真出现过 `eval:`，它仍要能解析：命中的是 `RETIRED_TABLES` 里的
    #    那份历史文件，读到行 ⇒ 解析成功，读不到 ⇒ `missing`，**不是** `unknown`。
    # 所以 `assert_citation_prefix_contract` 接受"目标是一张退役表"（见那一格）。
    "eval": "eval_results",
    "doc": "documents",
    "stmt": "statements",
}


def citation_prefix_table(prefix: Any) -> str | None:
    """`前缀:代号` 的前缀指向哪张表（`None` = 这个前缀不认）。

    唯一实现：`tools.doc_tools._CITATION_TABLES` 与 `gates.gate_g2` 的可解析前缀
    都从本表派生（改口径只改这里）。提示词与 `docs/` 里写的用法不是判据。
    """
    return CITATION_PREFIXES.get(str(prefix))


def assert_citation_prefix_contract() -> None:
    """引用前缀声明面与 `TABLES` 的对账。导入期自动跑一次。

    判据三条：
    1. 每个前缀指向的表名真的在 `TABLES` **或 `RETIRED_TABLES`** 里 —— 否则那是个
       "谁也核不了"的前缀，症状是写入期与审计期对同一个字符串给出不同结论。
       退役表收在这里是刻意的（`eval` 那一格）：表退役了，历史文档里的引用仍要能
       解析到那份历史文件；读到行 ⇒ ok，读不到 ⇒ missing，**不是 unknown**；
    2. `stmt` 必须在表里、且指向 `statements` —— 这条写法一旦被摘掉，
       "哪几条正文断言压在这条命题上"就重新变成判不了，而 `closing` 那一格只会退回一句边界文字；
    3. 前缀形态：首字符是字母、其余是小写 ASCII 字母或数字。`citations` 按第一个冒号切前缀、代号里的 `#`
       之后按锚点处理，所以前缀里出现冒号或大写就有歧义。
    写成函数再在导入期调用，而不是把断言摊在模块级：函数可被测试再次调用，于是"往本表里塞一个指向不存在
    表的前缀 ⇒ 必须红"这条负控才是可写的。
    """
    known_targets = set(TABLES) | set(RETIRED_TABLES)
    unknown = sorted(t for t in CITATION_PREFIXES.values() if t not in known_targets)
    assert not unknown, (
        f"CITATION_PREFIXES 指向了 TABLES / RETIRED_TABLES 里都没有的表：{unknown} ⇒ "
        "这些前缀没有任何读取面能核它的存在性（写入期与审计期会分家）"
    )
    assert CITATION_PREFIXES.get("stmt") == "statements", (
        "`stmt:` 前缀没了或指错了表 ⇒ 正文断言引用命题这条写法失效，"
        "`closing` 的断言级污染面会退回『判不了』而没有任何东西会红"
        "（`draft/68` 题 1，2026-10-07 所有者裁定 A）"
    )
    for prefix in CITATION_PREFIXES:
        shaped = (bool(prefix) and prefix[:1].isalpha() and prefix.isascii()
                  and prefix == prefix.lower() and prefix.isalnum())
        assert shaped, (
            f"引用前缀 {prefix!r} 的形态不对：首字符是字母、其余是小写 ASCII 字母或数字"
        )


def process_id_kinds() -> frozenset[str]:
    """不占编号空间的 ID 类别。

    返回 `id_kind`（`search_requests` 是 `"request"`、`reprocess_requests` 是
    `"reprocess"`、`tasks` 是 `"task"`），因为 `id_kind` 才是与 `ID_COUNTERS`
    的键同层的东西。

    这张表是从 `TABLES` 与 `ID_COUNTERS` 派生的；它与声明面
    `PROCESS_ID_PREFIXES` 的键必须相等（由 `assert_process_id_contract()` 守）——
    单看它自己是同义反复，见 `PROCESS_ID_PREFIXES` 的说明。
    """
    counter_fields = set(ID_COUNTERS.values())
    return frozenset(
        spec["id_kind"] for spec in TABLES.values() if spec["id_field"] not in counter_fields
    )


def id_space_kinds() -> frozenset[str]:
    """占编号空间的那几类（= `ID_COUNTERS` 的键）。与 `process_id_kinds()` 互斥。

    名字里的"编号空间"随 `ID_DIGITS` 一起动（宽度写进名字，改宽度之后就会是一句假话）。
    """
    return frozenset(ID_COUNTERS)


def is_valid_process_id(value: Any, id_kind: str | None = None) -> bool:
    """过程记录 ID 的形态判据（如 `r-000001` / `p-000001` / `t-000001`；旧四位照样读）。

    为什么不并进 `is_valid_id`：那个是知识实体编号的判据。两者必须能互相排除 —— 合并成一个"两种都接受"
    的函数，就等于把"占不占编号空间"这个区分抹掉了，而那正是"不可判定"的成因。
    ## 第二个参数 `id_kind`：不给时这条判据只校形态（前缀-号码），它刻意是宽的 ——
    `assert_process_id_contract()` 用它证明"过程 ID 与编号 ID 互斥"。给了就同时校前缀：`id_kind='request'`
    只接受 `r-`。
    为什么前缀比对必须挂在这里而不是另写一份正则：`PROCESS_ID_PREFIXES` 是"哪张表用哪个前缀"的唯一声明面。
    另写一份 `^r-\d{4}$` 就是第二份实现，而"同一件事两个落位"正是 `normalize_doi` 那族缺陷的成因。前缀比对
    与形态比对因此共用同一个正则，只是多一个 `dict` 查找。
    """
    if not (isinstance(value, str) and bool(_PROCESS_ID_RE.match(value))):
        return False
    if id_kind is None:
        # 只校形态：这是"两半互斥"契约需要的宽口径，不许收紧 ——
        # 收紧它会连带拒绝 `assert_process_id_contract()` 里 `gb-` 那类样本，
        # 而那条负控正是靠"形态判据本身不认前缀"来证明前缀是另一条判据。
        return True
    want = PROCESS_ID_PREFIXES.get(id_kind)
    if want is None:
        return False
    return value.split("-", 1)[0] == want


def require_process_id(value: Any, id_kind: str) -> str:
    """过程记录 ID 的完整判据（形态 + 前缀），失败即抛。

    三个行校验器（`SearchRequest.validate` / `ReprocessRequest.validate` /
    `Task.validate`）都走这里：只查"非空"时 `r--0001` / `r-10000` / `0000` / `gb-0001`
    这类号可以静默落库。
    这里把"该表的 `id_kind`"显式传进来，于是两张判据（形态、前缀）
    都由调用点强制走一遍 —— 而不是靠每个调用方记得自己比一遍前缀。
    """
    if not is_valid_process_id(value, id_kind):
        want = PROCESS_ID_PREFIXES.get(id_kind)
        raise ValueError(
            f"{id_kind} 的过程记录 ID 必须是「前缀 {want!r} + 连接号 + {ID_DIGITS} 位数字」"
            f"（如 {want}-{format_id(1)}；旧数据里的 4 位号仍可读），收到 {value!r}。"
            "只查非空会让 5 位号、双连接号、越界号与错前缀号静默落库，"
            "直到某个下游按整数解析或按前缀过滤时才暴露（`c-1` / `c-2`）。"
        )
    return value


# ---- `P-17` 的断言：把这条契约变成导入期就炸的东西。
#
# 若只靠"`ID_COUNTERS` 的键里恰好没有 `task`"，那是用一个"缺失"在替一条"契约"说话：
# 有人给任务号装一个计数器（或把 `task` 塞进 `ID_COUNTERS`）时没有任何东西会红，而
# `interactions.next_prefixed_id` 越界产号的入口就多一个。
#
# 写成函数再在导入期调用，而不是把断言直接摊在模块级：函数可被测试再次调用，
# 于是"往 ID_COUNTERS 里塞一个过程前缀 ⇒ 必须红"这条负控才是可写的
# （模块级断言只在 import 时跑一次，注入之后就再也触发不了）。


def assert_process_id_contract() -> None:
    """断言"过程记录不占编号空间"。导入期自动跑一次。

    四条判据。声明面与派生面互相对账，所以它们不是同义反复：
    1. `set(ID_COUNTERS)` 与过程前缀（`r`/`p`/`t`）的交集为 空 —— 直接钉住"占号空间"这件事本身；
    2. `set(PROCESS_ID_PREFIXES)`（声明面）与 `process_id_kinds()`（派生面）相等 —— 有人给过程表装上计数器
       时，派生面会变而声明面不变，两条路都炸；
    3. 每一张过程记录表的 `id_field` 都不在 `ID_COUNTERS` 的值里；
    4. 过程 ID 与编号空间 ID 的形态判据互斥且各自可判定（`"000000"` 与旧数据 `"0000"` 都不是过程 ID，
       `"t-000001"` 与旧数据 `"t-0001"` 都不是编号 ID）。
    """
    process_kinds = process_id_kinds()
    counter_kinds = id_space_kinds()
    prefixes = set(PROCESS_ID_PREFIXES.values())

    assert not (counter_kinds & prefixes), (
        f"ID_COUNTERS 里有过程记录前缀 {sorted(counter_kinds & prefixes)}："
        "过程记录（r-/p-/t-）刻意不占编号空间。给它装计数器会让编号空间被"
        "过程记录吃掉，并且给 next_prefixed_id 的越界产号多开一个入口（P-17 / P-4）。"
        "要么把它从 ID_COUNTERS 里去掉，要么这是一次需要人裁的口径变更。"
    )
    assert set(PROCESS_ID_PREFIXES) == set(process_kinds), (
        f"声明面 PROCESS_ID_PREFIXES={sorted(PROCESS_ID_PREFIXES)} 与派生面 "
        f"process_id_kinds()={sorted(process_kinds)} 不一致："
        "过程记录不占编号空间这条契约的**两个落位分家了**。"
        "派生面变了而声明面没变（或反之）都必须有人看一眼 —— 直接改派生面"
        "（例如把 task 塞进 ID_COUNTERS）会让任务号开始吃编号空间。"
    )
    for tname, spec in TABLES.items():
        if spec["id_kind"] in process_kinds:
            assert spec["id_field"] not in counter_kinds, (
                f"表 {tname} 是过程记录，它的 {spec['id_field']} 不该出现在 ID_COUNTERS 的值里"
            )
    # 两个形态判据必须互斥、且各自可判定 —— 否则"task_id 是什么形态"仍然只是注释。
    # 两个宽度都试：新号（六位）与旧数据（四位）都必须落在"编号 ID"这一半。
    for sample in (format_id(0), "0000"):
        assert is_valid_id(sample) and not is_valid_process_id(sample), (
            f"编号 ID {sample!r} 不被过程判据接受")
    for sample in (f"t-{format_id(1)}", "t-0001"):
        assert is_valid_process_id(sample) and not is_valid_id(sample), (
            f"过程 ID {sample!r} 不被编号判据接受")
    assert is_valid_process_id(f"r-{format_id(999999)}") and is_valid_process_id("p-0001"), (
        "过程 ID 形态判据要求 前缀+连接号+号码（当前宽度或旧四位）"
    )


def assert_id_space_contract() -> None:
    """断言"编号宽度契约"只有一个定义处。导入期自动跑一次。

    为什么需要这一条：`store.MAX_ID` 是"编号上限"的唯一定义处（`interactions.py` 明确说它 import 那个常量而
    不是另抄一份），`schema._ID_RE` 是形态的唯一定义处，而两者之间若没有对账，把 `MAX_ID` 改成三位或五位数
    不会有任何东西响，而 `is_valid_id` 照样只认一种宽度 ⇒ "上限"与"形态"分家，发出来的号要么被 `require_id`
    拒掉、要么永久无法表达。判据两条：
    1. `MAX_ID` 必须是 `_ID_RE` 那种宽度的最大值（`10 的宽度次方 - 1`）—— 改窄/改宽都会红：
       "改它等于改磁盘契约"不能只写在注释里；
    2. 每一类 ID（`TABLES` 的 `id_kind`）必须恰好落在两半之一：要么进 `ID_COUNTERS` 吃编号空间，要么进
       `PROCESS_ID_PREFIXES` 不占 —— 一个 `id_kind` 两边都不在，意味着有一张表的 ID 形态没有声明面管它。
    """
    # 惰性 import：`store` 顶层 `from . import schema as S`，模块级互相 import 会成环。
    # 函数体内 import 只在本函数被调用时执行（导入期调用时 `store` 已能正常加载）。
    from .store import MAX_ID

    m = re.match(r"^\^\\d\{(\d+)\}\$$", _ID_RE.pattern)
    assert m is not None, f"_ID_RE 的形状变了（{_ID_RE.pattern!r}），这条对账判据读不懂它"
    width = int(m.group(1))
    assert MAX_ID == 10 ** width - 1, (
        f"store.MAX_ID = {MAX_ID}，而 schema._ID_RE = {_ID_RE.pattern!r} 只表达 "
        f"{width} 位（该宽度的最大值是 {10 ** width - 1}）⇒ **编号宽度契约的两个落位分家了**。"
        "MAX_ID 是上限的唯一定义处，_ID_RE 是形态的唯一定义处；改其中任何一个"
        "都等于改磁盘格式契约（DESIGN.md §0.1 C4）—— 这是需要人裁的口径变更，"
        "不许只改一边。"
    )
    covered = set(ID_COUNTERS) | set(process_id_kinds())
    declared = {spec["id_kind"] for spec in TABLES.values()}
    assert covered == declared, (
        f"这些 id_kind 不在 ID_COUNTERS 也不在过程记录前缀里：{sorted(declared - covered)}"
        "（另一侧多出来的："
        f"{sorted(covered - declared)}）⇒ 有一张表的 ID 形态没有任何声明面管它。"
        "4 位空间与过程记录空间必须**互补**，否则新增表时会出现一个"
        "既不占号、也不被 `_PROCESS_ID_RE` 接受的 ID 类别（`F-9` / `P-17`）。"
    )


def assert_table_registry_contract() -> None:
    """三份表清单互相对账。导入期自动跑一次。

    判据四条，一条对应一种"半套退役"：
    1. `TABLES` 与 `RETIRED_TABLES` 不许有交集 —— 同一张表既在写又在退役名单里，
       症状是 `init()` 建它而 `tx()` 拒它（或反之），两种读数都"看起来正常"；
    2. `NOT_ENABLED_TABLES` 的键必须都在 `TABLES` 里 —— "未启用"是"表在、线没跑过"，
       不是"表没了"；表没了就该进退役名单，否则那一格是一条谁也读不到的登记；
    3. 退役表不许同时是"未启用表" —— 两格说的是相反的事；
    4. 退役登记要能读出它自己那一份文件与行类型（`file` / `row` / `id_field`），
       且 `id_field` 真的是那个行类型上的字段 —— 否则读侧宽容拿不到形状。

    写成函数再在导入期调用（不是把断言摊在模块级）的理由与
    `assert_process_id_contract` 同一句：函数可被测试再次调用，于是"往两张清单里
    各塞一个同名表 ⇒ 必须红"这条负控才是可写的。
    """
    assert not (set(TABLES) & set(RETIRED_TABLES)), (
        f"这些表同时在 TABLES 与 RETIRED_TABLES 里：{sorted(set(TABLES) & set(RETIRED_TABLES))}"
        " ⇒ 一张表不能既「在写」又「退役」：`init()` 会建它而 `tx()` 拒它，"
        "两边的读数都会看起来正常。二选一。"
    )
    stray = sorted(set(NOT_ENABLED_TABLES) - set(TABLES))
    assert not stray, (
        f"NOT_ENABLED_TABLES 里有不在 TABLES 里的表：{stray} ⇒ "
        "“未启用”说的是“表在、整条线没跑过”，不是“表没了”；表没了请进 RETIRED_TABLES。"
    )
    assert not (set(NOT_ENABLED_TABLES) & set(RETIRED_TABLES)), (
        "同一张表不许既是“未启用”又是“已退役”：两格说的正好相反"
    )
    for name, spec in sorted(RETIRED_TABLES.items()):
        for key in ("file", "row", "id_field"):
            assert str(spec.get(key) or ""), f"退役表 {name} 的登记缺 {key!r}"
        assert spec["id_field"] in getattr(spec["row"], "__dataclass_fields__", {}), (
            f"退役表 {name} 的 id_field={spec['id_field']!r} 不是 "
            f"{spec['row'].__name__} 上的字段 ⇒ 读侧宽容拿不到形状"
        )


assert_table_registry_contract()
assert_id_space_contract()
assert_process_id_contract()
assert_citation_prefix_contract()


def empty_table() -> dict:
    return {"schema_version": SCHEMA_VERSION, "rows": []}


def validate_table(table: str, doc: dict) -> None:
    """校验一张表的整体结构。抛 ValueError，不返回布尔值 —— 让错误尽早炸出来。

    退役表（`RETIRED_TABLES`）也收：历史工作区里那份文件仍按**退役时那一份形状**
    校验（行类型在 `row_from_dict` 里同一条分支），这是"读侧宽容"的另一半 ——
    表退役不等于历史文件变成"谁也读不懂的 JSON"。写侧永远走不到这里
    （`store.tx` 与 `table.*` 在更早一层就拒了退役表）。
    """
    spec = TABLES.get(table) or RETIRED_TABLES.get(table)
    if spec is None:
        raise ValueError(f"未知表名：{table}")
    if not isinstance(doc, dict):
        raise ValueError(f"{table} 快照必须是对象")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{table} schema_version 应为 {SCHEMA_VERSION}，收到 {doc.get('schema_version')!r}")
    rows = doc.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{table}.rows 必须是数组")

    id_field = spec["id_field"]
    seen_ids: set[str] = set()
    # ---- 幂等键的唯一性（"被索引的唯一键"在本栈里的落点）
    #
    # 判据是通用的：任何行只要带一个非空的 `idem_key`，它在整张表里就必须唯一。
    # 没有把 `idem_key` 特判成"只有 usage_ledger 才有"：那样每新增一张需要幂等的表
    # 都要改这里一次，而漏改的表现是"静默没有唯一性"（没有任何检查会响）。
    seen_idem: dict[str, str] = {}
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"{table}.rows[{i}] 必须是对象")
        try:
            obj = row_from_dict(table, raw)
            obj.validate()
            # FC-05：集合字段的升序去重在这里集中检查（唯一权威点）。
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
    # 触点：
    # `row_from_dict` 是"表名 → 行类"的第二份名单，`TABLES` 里有它这里没有，
    # 症状是 `validate_table` 报"未知表名：conjectures"（写盘当场炸，不是静默）。
    if table == "conjectures":
        return Conjecture(**{k: raw[k] for k in raw if k in Conjecture.__dataclass_fields__})
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
    if table == "statements":
        d = {k: raw[k] for k in raw if k in Statement.__dataclass_fields__}
        d["page_range"] = PageRange.from_dict(raw.get("page_range"))
        return Statement(**d)
    if table == "review_findings":
        return ReviewFinding(**{k: raw[k] for k in raw if k in ReviewFinding.__dataclass_fields__})
    if table == "tasks":
        return Task(**{k: raw[k] for k in raw if k in Task.__dataclass_fields__})
    if table == "usage_ledger":
        return UsageEntry(**{k: raw[k] for k in raw if k in UsageEntry.__dataclass_fields__})
    if table == "eval_results":
        return EvalResult(**{k: raw[k] for k in raw if k in EvalResult.__dataclass_fields__})
    if table == "lit_candidates":
        return LitCandidate(**{k: raw[k] for k in raw if k in LitCandidate.__dataclass_fields__})
    raise ValueError(f"未知表名：{table}")
