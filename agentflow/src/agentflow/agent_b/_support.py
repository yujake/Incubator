"""B 智能体：文献整理。

职责（需求原文）：处理 A 新搜到的文献 → 维护概念表与关系表 → 处理完一篇就把文献表的
处理情况置 1；每条关系录入前检查是否已有相同或几乎相同的表述。

四个刻意的设计选择：

1. 概念名 → 概念代号 的解析在锁内做。否则两个 B 实例可能各自为"群"新建一个概念，
   产生两个概念代号指向同一概念。这与"判重"是两回事：判重是业务规则，解析唯一性是
   数据结构约束，必须靠锁。
2. `related_concepts` 由关系表整体派生，不做增量 append（DESIGN.md §6.2）。
   需求说"每次 append 时保持升序"—— 整体重算的结果与"append+排序+去重"一致，
   但多了一个性质：漏更新会自愈，不需要靠人记得同步。
3. 引文校验失败的条目仍然落库，但置 `status="suspect"`。丢掉它等于隐藏证据；
   落库并标黄，才能让人看到"模型在哪些地方引不出原文"。
4. 抽取失败不置 `processed`。`processed` 的语义是"B 处理完了"，
   处理抛异常就不是处理完了；靠租约到期重试，超过次数才显式记错。

DESIGN-INTERACTIONS.md §1 新增的三件事（I6 / I4 / I5 的决定侧）：

5. 写入期一致性闸门（I6）：关系落库前问一句"这条与图里已有的矛盾吗"。
   这个闸门必须是纯函数（`interactions.check_conflict`，签名里没有 store）：
   B 在自己的事务内调用它，若它去查 store 就是同一进程内 `filelock` 重入
   （轻则抛错、重则死锁）。已有关系由 B 用 `tx.rows("relations")` 读好传进去，
   唯一入口是 :meth:`AgentB._conflict_scope`。
   闸门是三态的：`True` 矛盾 / `False` 不矛盾 / `None`+`checked=False` 没检查；
   "没检查"绝不允许被压成"不冲突"（见 `_conflict_check` 字段与两个计数器）。
6. 定向重抽取（I4）：处理 `reprocess_requests` 里 `status="pending"` 的行，
   只动目标关系。重抽取事务里刻意不声明 `literature` 表 ——
   把 `processed` 置回 `False` 会触发全量重抽，这是 I4 明写的幂等陷阱，
   不声明该表就是"结构上不可能犯这个错"。
7. 结构重复的合并决定权（I5）：C 只提候选，B 复核两路独立证据
   （结构等价 + 名字侧）才合并，且合并必须留下可被人反驳的理由。
   宁可漏合并（少省一点空间）也不错误合并（把两条知识并成一条，不可逆）。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from .. import dedup as D
from .. import interactions as I
from .. import quoteverify
from .. import schema as S
from .. import textutil as T
from ..quoteverify import check_quote
from ..store import Store, StoreError, lease_expired, make_lease
from ..agentspec import AgentBrief, AgentSpec
REPROCESS_RESULTS = ("found", "not_found", "improved", "unchanged", "rejected_target")
NOTE_LIMIT = 2000
QUOTE_OUT_OF_DECLARED_RANGE = "substring_match_outside_declared_range"
assert QUOTE_OUT_OF_DECLARED_RANGE in Path(quoteverify.__file__).read_text(
    encoding="utf-8"
), (
    f"quoteverify 里找不到 {QUOTE_OUT_OF_DECLARED_RANGE!r} 这个 reason ⇒ "
    "B 的 quotes_out_of_declared_range 会静默地永远是 0（`E-11` 的那一档又变成了看不见）"
)
_PASSAGE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?", re.UNICODE)
def _passages(page_text: str) -> list[str]:
    """把一页切成候选片段，每一段都是原页文本的连续切片。

    为什么强调"连续切片"：`quote` 的唯一义务是"逐字出现在原文里"。
    片段若被重新拼接（或 strip 掉中间空白），它就可能过不了既有的引文回验 ——
    那会让"找到了等价表述"变成一句空话。因此这里只做切分，不做任何改写。

    切句口径与 `llm.py` 的抽取器不逐字相同是可以接受的：它只影响召回率
    （能不能找到），正确性由随后的 `check_quote` 兜底 —— 不通过就不算找到。
    """
    out: list[str] = []
    for m in _PASSAGE_RE.finditer(page_text or ""):
        seg = m.group(0)
        if seg.strip():
            out.append(seg)
    return out
@dataclass
class BRunResult:
    processed: int = 0
    concepts_created: int = 0
    concepts_reused: int = 0
    relations_added: int = 0
    relations_duplicate: int = 0
    relations_suspect: int = 0
    suspect_by_quote: int = 0
    quotes_verified: int = 0
    quotes_failed: int = 0
    quotes_unknown: int = 0
    #: `E-11`：引文逐字存在、但不在关系声明的页码范围内（落在 ±widen 的扩展窗口里）。
    #:
    #: 为什么要单独一档：这一档在 `quoteverify.check_quote` 里是
    #: `verified=True + reason='substring_match_outside_declared_range'` —— 于是
    #: 它既被计进 `quotes_verified`（"逐字可达"是真的），又不会把关系降为
    #: `suspect`（`quote_failed` 判的是 `verified is not True`）。结果是
    #: "全部引文逐字可达"这条判据在所有页码都记错时照样通过，而聚合计数器里
    #: 也看不出"页码不符"有几条 —— 这个信号原先只留在每行的 `_quote_check` 字典里，
    #: 全仓库没有任何检查器消费它。
    #:
    #: 这一档不改 `verified`（逐字存在是事实，把它抹成 False 会让"真引文被记成
    #: 幻觉"，那是 FC-02 最贵的一档），也不改 suspect 口径（那需要人裁，
    #: `draft/28` 的 `E-11` 修法里写明了）。它做的是把这一档从"折进 verified"
    #: 变成"可判定的独立档"：这里单独计数，`verify --deep` 另有一条
    #: `page_range_mismatch` 的 warning（见 `verify.verify_all`）。
    quotes_out_of_declared_range: int = 0
    unreadable: int = 0
    #: `R-56`：有文件但没有够格的抽取器（框架的规则回退）⇒ 拒抽，不置 `processed`。
    #: 单列一格而不并进 `unreadable`：文件读得到，缺的是"谁来读懂它"。
    skipped_no_extractor: int = 0
    failed: int = 0
    # ---- 取文献侧的审计信息（与 `AgentA.ARunResult` 同口径）。
    #: 因"`claimed_by` 非空且租约未过期"而被跳过的条数。
    #: 它是"有活却没干"的唯一合法解释，必须能被外部看见 —— 否则运维只能看到
    #: `skipped_reason="no_unprocessed_literature"`，会把"全被别人占着"读成"队列空了"。
    skipped_lease_active: int = 0
    #: 本轮当场放弃（`mine_attempts` 用尽）的条数。
    gave_up: int = 0
    # ---- I6 写入期闸门的三态计数（必须从外部可观察）
    #:
    #: 没有这三个数，I6 就是"看起来接上了但没生效"：闸门返回 `checked=False`
    #: 时行会被照常写成 active，而单看数据完全看不出来"这次没检查"。
    conflict_checks_run: int = 0  # checked=True（检查过，无论是否矛盾）
    conflicts_detected: int = 0  # conflict=True（写入并标 suspect）
    conflict_checks_skipped: int = 0  # checked=False（没检查）
    skipped_reason: str | None = None
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "details"}
        d["details"] = self.details[:20]
        return d
@dataclass
class BClaimOutcome:
    """`_claim()` 的结果：取文献这件事本身的结果，而不只是"取到的那一行"。

    为什么不让 `_claim()` 只返回 `dict | None`：一个 `None` 会把三件处置完全不同的事
    压成同一个值，而它们的下一步动作完全相反 ——

    - ``pending == 0``                 —— 队列里确实没有未处理文献（可以停）
    - ``skipped_lease_active > 0``     —— 有活，但都在别人手里（该等，或换实例跑）
    - ``gave_up > 0``                  —— 有活，但都超了重试上限（终局，别再等）

    压成一个 `None` 的后果不是"少一点信息"而是误导运维：`run_once()` 原先无论
    哪种情况都写 `skipped_reason="no_unprocessed_literature"`，于是"全都被人持着有效
    租约"被报成"队列空了"—— 看到的人会以为没事可做，而事实是有活压着。
    `agent_a.ClaimOutcome` 的 docstring 已经把这条纪律写透，这里只是把它原样搬到 B
    （不另立判据：字段名、含义、三态划分与 A 保持一致，唯一区别是被领的东西叫
    literature 而不是 request）。

    另外注意"放弃"与"被租"的顺序：先判租约、再判 attempts。一条正被别人跑着的
    文献不该由我们来"放弃" —— 两个人各有各的 `mine_attempts` 计数，单方面判死会
    把别人手上的活一起毁掉。
    """

    #: 取到的文献行（已置 claimed_by / lease_until / mine_attempts+=1）；没取到时为 `None`。
    literature: dict | None = None
    #: 定序时未处理文献的条数（不含已 processed 的）。
    pending: int = 0
    #: 因租约未过期而被跳过的条数（"别人正在做"）。
    skipped_lease_active: int = 0
    #: 本轮当场放弃（attempts 用尽）的条数。
    gave_up: int = 0
    #: 没取到文献时的原因；取到时为 `None`。
    skipped_reason: str | None = None

    @property
    def claimed(self) -> bool:
        """是否取到了文献。不要用 `bool(self.literature)` 代替：那会在别处再造一个判据。"""
        return self.literature is not None
from ..specs.b import SPEC  # noqa: E402,F401

