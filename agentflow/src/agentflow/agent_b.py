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

from . import dedup as D
from . import interactions as I
from . import quoteverify
from . import schema as S
from . import textutil as T
from .quoteverify import check_quote
from .store import Store, StoreError, lease_expired, make_lease

#: I4：B 对一次定向重抽取给出的终局结果词表。
#:
#: 为什么落在 B 而不在 schema：`ReprocessRequest.result` 目前是自由文本
#: （本轮不改 schema —— 它不在 B 的所有权范围内）。词表必须包含
#: `rejected_target`："连目标都不合法"与"做了但没找到"是两回事，
#: 混成一个词会让"重抽取失败率"这类统计失去意义。
REPROCESS_RESULTS = ("found", "not_found", "improved", "unchanged", "rejected_target")

#: `result_note` 的字符上限。它是给人看的证据（`need_context` 时就是原文片段），
#: 必须有上限，否则一次请求就能把 json 撑到无法阅读。
NOTE_LIMIT = 2000

#: `E-11`：`quoteverify.check_quote` 给出的"逐字存在、但不在声明的页码范围内"那一档。
#:
#: 为什么在 B 这一层要认识这个字面量：B 是那个"把 `verified` 读成结论"的地方
#: （`chk.verified is True` ⇒ 计 `quotes_verified`），而这一档的 `verified` 也是
#: `True` —— 只有 `reason` 能把它与"页码正确"分开。判据必须是一个受控常量而不是
#: 散在 `if` 里的一句字面量：`quoteverify.py` 在 FC-27 禁改区，它的 reason 一旦改名，
#: 这里会静默地一条都不再计。下面那条导入期断言就是为了让这种改名立刻炸出来。
QUOTE_OUT_OF_DECLARED_RANGE = "substring_match_outside_declared_range"
#: 上游（`quoteverify`）真的会产出上面那个字面量吗 —— 导入期核一次。
#: 这一条与 `agent_e` 的 `set(formalgw.STATUSES) <= set(映射表)` 是同一形态：
#: 隐式契约放在导入期，不留给"跑起来才发现"。
assert QUOTE_OUT_OF_DECLARED_RANGE in Path(quoteverify.__file__).read_text(
    encoding="utf-8"
), (
    f"quoteverify 里找不到 {QUOTE_OUT_OF_DECLARED_RANGE!r} 这个 reason ⇒ "
    "B 的 quotes_out_of_declared_range 会静默地永远是 0（`E-11` 的那一档又变成了看不见）"
)

#: 切"候选片段"用的句末标点（含换行）。中文与英文都要切，否则整页会被当成一个片段，
#: 相似度会被无关句子的 token 稀释到阈值以下（表现为"明明有等价表述却找不到"）。
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


class AgentB:
    """文献整理智能体。extractor / extract_text 由外部注入，便于离线测试。"""

    def __init__(
        self,
        store: Store,
        *,
        extractor: Any,
        extract_text: Any,
        config: dict | None = None,
        actor: str = "agent-B",
    ):
        self.store = store
        self.extractor = extractor
        self.extract_text = extract_text
        self.cfg = config or {}
        self.actor = actor
        self.lease_seconds = int(self.cfg.get("lease_seconds", 900))
        self.max_attempts = int(self.cfg.get("max_attempts", 3))
        self.dup_strong = float(self.cfg.get("dup_strong", 0.92))
        self.dup_review = float(self.cfg.get("dup_review", 0.72))
        self.widen_pages = int(self.cfg.get("quote_widen_pages", 1))
        self.allow_fulltext_fallback = bool(self.cfg.get("allow_fulltext_quote_fallback", False))
        # ---- I4 定向重抽取
        #: "等价表述"的相似度下限。低于它就不认（宁可报 not_found 也不猜）：
        #: 转写与原文的 token Jaccard 在阈值以下时，"找没找到"就变成了掷骰子，
        #: 而 I4 的全部价值在于"它说的话可以被核实"。
        self.reprocess_min_similarity = float(self.cfg.get("reprocess_min_similarity", 0.5))
        #: 在声明页码两侧多看几页（页码常常只错一页；与引文回验的 ±widen 同思路）。
        self.reprocess_context_pages = int(self.cfg.get("reprocess_context_pages", 1))
        #: 一次 `run()` 里最多处理多少条重抽取请求（有界：不许无限循环）。
        self.max_reprocess_per_run = int(self.cfg.get("max_reprocess_per_run", 10))

    # ------------------------------------------------------------------ I6 闸门的输入
    def _conflict_scope(self, tx) -> list[dict] | None:
        """把"图里已有的关系"交给 I6 闸门 —— 从当前事务里读，不新开事务。

        为什么单独一个方法：`interactions.check_conflict` 的硬约束是"调用方在
        自己的事务内把已有关系读好传进去，闸门自己绝不拿锁"。
        把"从哪读"收敛到唯一一处，这条约束才有落点（评审时只看这一个方法即可）。

        返回 `None` 的语义是"本次没有能力检查"（`check_conflict` 会返回
        `checked=False`），它与空列表（"读了，图里确实没有可比的关系"）完全是两回事。
        生产路径永远返回 `tx.rows("relations")`；测试与将来的降级路径可以显式返回
        `None`，让"没检查"这条分支可被触发、可被观察，而不是停留在纸面上。
        """
        return tx.rows("relations")

    # ------------------------------------------------------------------ 取任务
    def _claim(self) -> BClaimOutcome:
        """在锁内领一条未处理文献：置 `claimed_by` / `lease_until` / `mine_attempts+=1`。

        返回 :class:`BClaimOutcome` 而不是 `dict | None` —— 理由见那个类的 docstring：
        "队列空了" / "全被别人持着" / "全被放弃" 必须能被区分，`skipped_reason` 逐个命名
        （``no_unprocessed_literature`` / ``pending_literature_all_leased`` /
        ``no_claimable_literature``）。

        顺序即优先级：先判租约、再判 attempts。一条正被别人跑着的文献不该由我们来
        "放弃"（各有各的 `mine_attempts` 计数），否则会把别人手上的活单方面判死。
        """
        with self.store.tx("literature", actor=self.actor, note="claim") as tx:
            rows = tx.rows("literature")
            cands = sorted(
                (r for r in rows if not r.get("processed")),
                key=lambda r: (r.get("added_at") or "", r.get("lit_id") or ""),
            )
            pending = len(cands)
            skipped_lease_active = 0
            gave_up = 0
            for r in cands:
                if r.get("claimed_by") and not lease_expired(r.get("lease_until")):
                    skipped_lease_active += 1
                    continue  # 别人正拿着有效租约
                n = int(r.get("mine_attempts") or 0)
                if n >= self.max_attempts:
                    r["processed"] = True
                    r["last_mine_error"] = (
                        f"超过最大抽取尝试次数 {self.max_attempts}，已放弃。上一次错误：{r.get('last_mine_error')}"
                    )
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("literature", r, note="give_up")
                    gave_up += 1
                    continue
                r["claimed_by"] = self.actor
                r["lease_until"] = make_lease(self.lease_seconds)
                r["mine_attempts"] = n + 1
                tx.upsert("literature", r, note="claimed")
                return BClaimOutcome(
                    literature=dict(r),
                    pending=pending,
                    skipped_lease_active=skipped_lease_active,
                    gave_up=gave_up,
                )
            if pending == 0:
                reason = "no_unprocessed_literature"
            elif skipped_lease_active == pending:
                reason = "pending_literature_all_leased"
            else:
                reason = "no_claimable_literature"
            return BClaimOutcome(
                pending=pending,
                skipped_lease_active=skipped_lease_active,
                gave_up=gave_up,
                skipped_reason=reason,
            )

    # ------------------------------------------------------------------ 主流程
    def _extraction_meta(self, lit: dict) -> dict:
        """构造传给抽取器的元数据。

        为什么要塞 `seed_concepts`：规则抽取器（以及多数 LLM 提示词）判断
        "这句话还提到了哪些概念"时，需要一个"已知概念"的参照集合。最自然的参照集合
        就是概念表当前的内容 —— 因为 B 的目标恰恰是把新文献接到已有概念网络上。
        不传它，定义句就只会产出一个概念名，关系因 `len(concept_ids) < 2` 被全部丢弃，
        表现为"抽取器什么都抽不到"，而真正的原因在调用方没给上下文。

        种子是提示而非权威：这里允许读无锁快照，因为种子只影响召回率，
        不影响正确性（概念的唯一性仍由提交事务内的锁保证）。

        但"读不到概念表"是另一回事，必须显式传给抽取器（`seed_concepts_error`）：
        读不到 ⇒ 种子退化成"只有配置里那几个" ⇒ 定义句只产出一个概念名 ⇒
        所有关系因 `len(concept_ids) < 2` 被丢弃，而症状是"文献处理完了、
        却一条关系都没新增"，没有任何报错。静默失败比崩溃更危险，所以这里不吞。
        """
        meta = {
            "title": lit.get("title"),
            "venue": lit.get("venue"),
            "year": lit.get("year"),
            "authors": lit.get("authors") or [],
            "lit_id": lit.get("lit_id"),
        }
        seeds: list[dict] = list(self.cfg.get("seed_concepts") or [])
        limit = int(self.cfg.get("seed_concept_limit", 300))
        seeds_error: str | None = None
        try:
            known = self.store.rows("concepts")
        except Exception as e:  # noqa: BLE001
            # 这里不许静默吞掉。概念表读不出来时，种子会退化成"只有配置里那几个"，
            # 而本函数的 docstring 自己说了：没有种子的后果是"定义句只产出一个概念名，
            # 关系因 len(concept_ids) < 2 被全部丢弃，表现为'抽取器什么都抽不到'"。
            # 也就是说：一次读取失败会让召回率静默塌掉，而正确性判据（唯一性靠锁）
            # 照样成立 —— 症状是"文献处理完了、但一条关系都没有"，没人能看出为什么。
            # 种子的内容确实只是提示（无锁快照可以接受），但"读不到"这件事本身
            # 是一个必须被看见的事实，所以把它作为显式字段传下去，而不是吞掉。
            known = []
            seeds_error = f"{type(e).__name__}: {e}"
        for c in known[-limit:]:
            seeds.append(
                {
                    "name": c.get("name"),
                    "definition": c.get("definition") or "",
                    "aliases": list(c.get("aliases") or []),
                }
            )
        if seeds:
            meta["seed_concepts"] = seeds
        if seeds_error is not None:
            # 只在读不到时才出现这个键：它的存在本身就是一个告警信号，
            # 消费方不需要区分"None 表示没问题"还是"None 表示没查"。
            meta["seed_concepts_error"] = (
                f"概念表读不出来（{seeds_error}）⇒ 本次只用了配置里的种子，"
                "召回率会下降（**不是**'没有已有概念'）"
            )
        return meta

    def run_once(self) -> BRunResult:
        """处理至多一篇未处理文献，返回本轮的完整审计结果。

        三态纪律在这里有两个落点：

        1. 取不到文献不等于"队列空了"：`skipped_reason` 由 `_claim()` 的三态给出
           （`no_unprocessed_literature` / `pending_literature_all_leased` /
           `no_claimable_literature`），并同时暴露 `skipped_lease_active` / `gave_up`
           两个计数。原先无论哪种情况都写"no_unprocessed_literature"，是误导运维。
        2. 抽取失败不等于处理完了：不置 `processed`，只留 `last_mine_error`，
           由租约到期重试（模块 docstring 第 4 条）。
        """
        res = BRunResult()
        claim = self._claim()
        # 取文献侧的审计信息先落进结果，再决定要不要早退 —— 否则"有活但全被别人
        # 占着"这类信息会随着 skipped_reason 一起丢掉，外部只剩一个"什么都没做"。
        res.skipped_lease_active = claim.skipped_lease_active
        res.gave_up = claim.gave_up
        lit = claim.literature
        if lit is None:
            res.skipped_reason = claim.skipped_reason
            return res

        lit_id = lit["lit_id"]
        dl_status = (lit.get("download") or {}).get("status")
        path = self.store.library_path(lit.get("path"))
        # 三种"没有可抽取内容"的情况都要标为已处理并记明原因，否则它们会永远
        # 堵在队首（每次 run 都重新领取同一行）。注意 content_mismatch 单独列出来：
        # 文件其实存在（是证据），只是它按内容类型判定不是论文 —— 实测碰到过
        # 12.4 MB 的 HTML 被当成 PDF 存下来，若照常抽取会把网页导航文字当概念。
        unreadable_reason = None
        if dl_status == "content_mismatch":
            unreadable_reason = f"content_type_mismatch: {path.name if path else '?'}"
        elif path is None:
            unreadable_reason = "no_local_file"
        elif not path.exists():
            unreadable_reason = f"file_missing:{path}"

        if unreadable_reason is not None:
            with self.store.tx("literature", actor=self.actor, note="unreadable") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["processed"] = True
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = unreadable_reason
                tx.upsert("literature", row, note="skipped_unreadable")
            res.unreadable += 1
            res.processed = 1
            res.details.append({"lit_id": lit_id, "stage": "acquire", "skipped": unreadable_reason})
            return res

        try:
            doc = self.extract_text(path)
            concepts, relations = self.extractor.extract(
                doc, lit_id, self._extraction_meta(lit)
            )
        except Exception as e:
            # 抽取失败：不置 processed，让租约过期后重试
            with self.store.tx("literature", actor=self.actor, note="extract_failed") as tx:
                row = tx.find("literature", lit_id=lit_id) or lit
                row["claimed_by"] = None
                row["lease_until"] = None
                row["last_mine_error"] = f"{type(e).__name__}: {e}"
                tx.upsert("literature", row, note="extract_failed")
            res.failed += 1
            res.details.append({"lit_id": lit_id, "stage": "extract", "error": f"{type(e).__name__}: {e}"})
            return res

        # ---- 引文校验（无锁；只依赖文档）
        verified_rels: list[dict] = []
        for rel in relations:
            chk = check_quote(
                doc,
                getattr(rel, "quote", "") or "",
                getattr(rel, "page_range", None),
                widen=self.widen_pages,
                allow_fulltext_fallback=self.allow_fulltext_fallback,
            )
            if chk.verified is True:
                res.quotes_verified += 1
                # `E-11`：引文逐字存在、但落在声明的页码之外。判据取 `reason`
                # 而不是 `window` 前缀（`check_quote` 里只有这一条分支会给出这个
                # reason，见 `quoteverify.check_quote` 的 widen 分支）。
                if chk.reason == QUOTE_OUT_OF_DECLARED_RANGE:
                    res.quotes_out_of_declared_range += 1
            elif chk.verified is False:
                res.quotes_failed += 1
            else:
                res.quotes_unknown += 1
            verified_rels.append({"rel": rel, "check": chk})

        # ---- 提交（锁内，短）
        with self.store.tx("literature", "concepts", "relations", actor=self.actor, note="commit") as tx:
            concept_rows = tx.rows("concepts")
            relation_rows = tx.rows("relations")
            touched: set[str] = set()

            def resolve_concept(name: str, definition: str = "", aliases: Iterable[str] | None = None) -> str:
                nonlocal concept_rows
                existing = D.find_concept(concept_rows, name, list(aliases or []))
                if existing is not None:
                    # 合并别名（需求未要求，但别名不合并会导致后续同义名重复建概念）
                    merged = S.sorted_unique(list(existing.get("aliases") or []) + [name] + list(aliases or []))
                    merged = [a for a in merged if T.normalize(a) != (existing.get("normalized_name") or "")]
                    if merged != (existing.get("aliases") or []):
                        existing["aliases"] = merged
                        existing["updated_at"] = S.now_iso()
                        tx.upsert("concepts", existing, note="alias_merge")
                    res.concepts_reused += 1
                    return existing["concept_id"]
                cid = tx.alloc_id("concept")
                row = S.Concept(
                    concept_id=cid,
                    name=name,
                    definition=definition,
                    related_concepts=[],
                    normalized_name=T.normalize(name),
                    aliases=[a for a in S.sorted_unique(list(aliases or [])) if T.normalize(a) != T.normalize(name)],
                    definition_source_lit_id=lit_id if definition else None,
                    created_at=S.now_iso(),
                    updated_at=S.now_iso(),
                )
                row.validate()
                d = row.to_dict()
                concept_rows.append(d)
                tx.upsert("concepts", d, note="created")
                res.concepts_created += 1
                return cid

            # 1) 显式概念草稿先建（它们带定义，是概念的权威来源）
            for cd in concepts:
                resolve_concept(cd.name, cd.definition, cd.aliases)

            # 2) 关系：解析概念 → 判重 → 写入
            written: list[str] = []
            for item in verified_rels:
                rel = item["rel"]
                chk = item["check"]
                names = [n for n in (getattr(rel, "concept_names", []) or []) if n and n.strip()]
                if len(names) < 2:
                    res.details.append(
                        {"lit_id": lit_id, "stage": "relation", "skipped": "fewer_than_two_concepts", "names": names}
                    )
                    continue
                cids = S.sorted_unique(resolve_concept(n) for n in names)
                if len(cids) < 2:
                    res.details.append(
                        {"lit_id": lit_id, "stage": "relation", "skipped": "concepts_collapsed", "names": names}
                    )
                    continue

                quote = getattr(rel, "quote", "") or ""
                description = getattr(rel, "description", "") or ""
                group_key = T.concept_group_key(cids)
                decision = D.decide_relation(
                    relation_rows,
                    concept_group_key=group_key,
                    quote=quote,
                    description=description,
                    dup_strong=self.dup_strong,
                    dup_review=self.dup_review,
                )
                if decision.kind == "duplicate":
                    res.relations_duplicate += 1
                    res.details.append(
                        {
                            "lit_id": lit_id,
                            "stage": "relation",
                            "skipped": "duplicate",
                            "duplicate_of": decision.existing_id,
                            "score": round(decision.score, 4),
                        }
                    )
                    continue

                rid = tx.alloc_id("relation")
                # 引文校验失败/无法校验 → 降级为 suspect（不丢弃，保留证据）
                quote_failed = chk.verified is not True
                status = decision.status
                if quote_failed:
                    status = "suspect"
                pr = getattr(rel, "page_range", None)
                if not isinstance(pr, S.PageRange):
                    pr = S.PageRange.from_dict(pr if isinstance(pr, dict) else None)

                # ---- I6 写入期一致性闸门 ----
                # 已有关系必须在同一个 tx 内读（`_conflict_scope`），再交给纯函数：
                # 闸门里没有 store，因此不可能在这里重入 filelock（见模块 docstring 第 5 条）。
                # 代价是它只能看见"本事务已经读到的图"—— 这正是我们想要的语义：
                # 检查的是"按我即将提交的视图，这条矛盾吗"。
                draft = {
                    "relation_id": rid,
                    "concept_ids": list(cids),
                    "concept_group_key": group_key,
                    "statement": description,
                    "description": description,
                    "quote": quote,
                    "lit_id": lit_id,
                }
                cinfo = I.check_conflict(draft, existing_relations=self._conflict_scope(tx))
                if cinfo.get("checked"):
                    res.conflict_checks_run += 1
                else:
                    # 三态纪律：`checked=False` 不是"不冲突"。
                    # 行里会留下 `_conflict_check.checked=False` 作为证据，
                    # 同时计数器 +1，让"没检查"在统计里也看得见。
                    res.conflict_checks_skipped += 1
                    res.details.append(
                        {
                            "lit_id": lit_id,
                            "stage": "conflict_gate",
                            "skipped": "conflict_check_unavailable",
                            "reason": cinfo.get("reason"),
                        }
                    )
                conflicts_with = list(cinfo.get("conflicts_with") or []) if cinfo.get("conflict") else []
                if cinfo.get("conflict") is True:
                    # 矛盾比"引文可疑"更强，但落库动作相同：照写 + 标黄。
                    # 丢掉它等于隐藏最值钱的信号（文献之间的真实分歧）。
                    res.conflicts_detected += 1
                    status = "suspect"

                row = S.Relation(
                    relation_id=rid,
                    concept_ids=cids,
                    description=description,
                    lit_id=lit_id,
                    page_range=pr,
                    quote=quote,
                    quote_normalized=T.normalize_for_quote(quote),
                    quote_verified=chk.verified,
                    statement=description,
                    concept_group_key=group_key,
                    dedup_key=D.relation_dedup_key(group_key, quote),
                    status=status,
                    duplicate_of=decision.existing_id if decision.kind == "suspect" else None,
                    created_at=S.now_iso(),
                )
                row.validate()
                d = row.to_dict()
                d["_quote_check"] = chk.to_dict()
                # 诊断字段一律带上：即使"检查过、不冲突"也留痕，否则无法区分
                # "闸门说没问题"与"闸门根本没跑"。
                d["_conflict_check"] = cinfo
                if conflicts_with:
                    d["conflicts_with"] = conflicts_with
                relation_rows.append(d)
                tx.upsert("relations", d, note=f"status:{status},quote:{chk.reason},conflict:{cinfo.get('conflict')}")
                written.append(rid)
                touched.update(cids)
                # 按最终落库状态计数，而不是按判重结论计数：
                # 引文校验失败、以及 I6 闸门发现矛盾，都会把 status 降级为 suspect，
                # 只统计判重那条路径会让报告的 suspect 数与表里的实际条数对不上。
                if status == "suspect":
                    res.relations_suspect += 1
                    if quote_failed and decision.kind != "suspect":
                        res.suspect_by_quote += 1
                else:
                    res.relations_added += 1

            # 3) 概念自身涉及的旧关系也要重算 related_concepts（例如新建的概念与既有概念相连）
            for d in relation_rows:
                if d.get("lit_id") == lit_id or set(d.get("concept_ids") or []) & touched:
                    touched.update(d.get("concept_ids") or [])

            # 4) 由关系表整体派生 related_concepts
            for cid in sorted(touched):
                target = next((c for c in concept_rows if c["concept_id"] == cid), None)
                if target is None:
                    continue
                want = D.derive_related_concepts(cid, relation_rows, include_suspect=True)
                if target.get("related_concepts") != want:
                    target["related_concepts"] = want
                    target["updated_at"] = S.now_iso()
                    tx.upsert("concepts", target, note="related_recomputed")

            # 5) 标记文献处理完成（与实体写入同一事务 —— 见 DESIGN.md §2.4）
            lit_row = tx.find("literature", lit_id=lit_id) or lit
            lit_row["processed"] = True
            lit_row["claimed_by"] = None
            lit_row["lease_until"] = None
            lit_row["last_mine_error"] = None
            tx.upsert("literature", lit_row, note="processed")
            res.processed = 1

        return res

    # ------------------------------------------------------------------ I4 定向重抽取
    def reprocess_once(self) -> dict:
        """处理一条 pending 的重抽取请求（I4）。返回一份可审计的摘要。

        `handled=False` 有两种完全不同的含义，必须能分开（三态纪律）：

        - ``skipped_reason="no_pending_reprocess"`` —— 表里确实没有待办（没做）；
        - ``skipped_reason=None`` 且 ``error`` 非空 —— 领到了但处理失败：请求仍是
          `pending`（留给租约过期后重试），绝不标 done。

        ``rejected`` 列出本次被准入闸门拒掉的请求：它们不是"没做"，
        而是"明确判定不该做"，理由写进了 `result_note`。
        """
        claimed, rejected = self._claim_reprocess()
        if claimed is None:
            return {
                "handled": False,
                "reprocess_id": None,
                "rejected": rejected,
                "skipped_reason": "no_pending_reprocess" if not rejected else None,
            }
        rid = str(claimed.get("reprocess_id") or "")
        try:
            outcome = self._perform_reprocess(claimed)
        except Exception as e:
            # 读文件/抽取可能因为缺依赖、文件损坏而失败。不标 done：
            # "我压根没看成"和"我看过了、原文里没有"是两回事（I4 的三态纪律）。
            self._record_reprocess_failure(claimed, f"{type(e).__name__}: {e}")
            return {
                "handled": False,
                "reprocess_id": rid,
                "rejected": rejected,
                "skipped_reason": None,
                "error": f"{type(e).__name__}: {e}",
            }
        out = self._finish_reprocess(claimed, outcome)
        out["rejected"] = rejected
        return out

    def run_reprocess(self, max_requests: int | None = None) -> dict:
        """把 pending 的重抽取请求处理干净（有界，不会无限循环）。

        两道刹车，都很必要：

        - ``max_reprocess_per_run``：单次调用最多处理多少条（默认 10）；
        - ``seen``：同一条请求在一次调用里只处理一次。失败路径会释放租约让请求
          立刻可被再领，若没有这道刹车，"失败 → 释放 → 再领 → 再失败"就是一个
          不会停的循环 —— 而且是静默的：它不报错，只是把时间烧完。
        """
        cap = self.max_reprocess_per_run if max_requests is None else int(max_requests)
        summary: dict = {
            "handled": 0,
            "by_result": {},
            "rejected": [],
            "errors": [],
            "notes": [],
            "skipped_reason": None,
            "stopped": None,
        }
        seen: set[str] = set()
        n = 0
        while n < cap:
            out = self.reprocess_once()
            n += 1
            summary["rejected"].extend(out.get("rejected") or [])
            rid = str(out.get("reprocess_id") or "")
            if rid and rid in seen:
                summary["stopped"] = "same_request_repeated"
                break
            if rid:
                seen.add(rid)
            if out.get("error"):
                summary["errors"].append({"reprocess_id": rid, "error": out["error"]})
                continue
            if not out.get("handled"):
                summary["skipped_reason"] = out.get("skipped_reason")
                break
            summary["handled"] += 1
            word = str(out.get("result") or "")
            summary["by_result"][word] = summary["by_result"].get(word, 0) + 1
            summary["notes"].append(
                {
                    "reprocess_id": rid,
                    "result": word,
                    "touched_relation_ids": out.get("touched_relation_ids") or [],
                }
            )
        if summary["stopped"] is None and cap > 0 and n >= cap:
            summary["stopped"] = "max_requests_reached"
        return summary

    @staticmethod
    def _quota_rows(rows: Sequence[Mapping[str, Any]], current_id: str) -> list[dict]:
        """配额统计用的行集合：排除正在被受理的这一条。

        `interactions.reprocess_counts` 的口径是"pending + done 都算已受理"。
        提交方（C/D）是在插入请求之前调用 `admit_reprocess_request` 的，
        那时新请求还没进表；而 B 是在"请求已经在表里"的前提下复核。
        若把这一条 pending 也算进去，同一次受理会被数两次，
        `max_reprocess_per_relation=2` 实际只允许 1 次 —— 闸门比设计更严，
        而且是静默变严。排除自身后语义回到"同一关系最多被受理 max 次"。
        """
        return [dict(r) for r in rows if str(r.get("reprocess_id") or "") != str(current_id)]

    def _reject_reprocess(self, row: dict, why: str, tx) -> None:
        """标 `rejected`（不是 done）并写清理由。

        为什么与 `done` 分开：`done` = "B 处理过了，结论是 result"；
        `rejected` = "B 判定根本不该处理它"。混成一个状态后，配额统计
        （`reprocess_counts` 只数 pending+done）会把"我拒绝过"当成"我做过了"，
        于是一个从未被处理过的关系被拒两次就再也进不来。
        """
        row["status"] = "rejected"
        row["result"] = "rejected_target"
        row["result_note"] = T.clip(why, NOTE_LIMIT)
        row["claimed_by"] = None
        row["lease_until"] = None
        tx.upsert("reprocess_requests", row, note="reprocess_rejected")

    def _claim_reprocess(self) -> tuple[dict | None, list[dict]]:
        """认领一条 pending 的重抽取请求（与 literature 同样的租约模式）。

        准入的四条判据在这里一次做完（顺序即优先级）：

        1. 尝试次数 —— 超限就放弃（标 rejected，而不是永远挂着）；
        2. 目标非空 —— 无目标的重抽取会退化成全量重抽（I4 明写的幂等陷阱）；
        3. 目标存在 —— 关系可能已被删除、或已被 I5 合并（此时候选应转到 survivor）；
        4. 配额（`interactions.admit_reprocess_request`）—— 同一关系最多被受理
           `DEFAULTS["max_reprocess_per_relation"]` 次，被拒的不计入。

        为什么在"认领"这一步做完而不是在收尾时做：被拒的请求根本不该进入重活阶段
        （读全文、重新抽取可能几十秒）。四条判据用的都是同一个事务里读到的行，
        因此不存在"A 看到还有额度、B 看到没有了"的窗口。
        """
        rejected: list[dict] = []
        with self.store.tx("reprocess_requests", "relations", actor=self.actor, note="reprocess_claim") as tx:
            rows = tx.rows("reprocess_requests")
            known_relations = {str(r.get("relation_id")) for r in tx.rows("relations")}
            cands = sorted(
                (r for r in rows if str(r.get("status") or "") == "pending"),
                key=lambda r: (r.get("timestamp") or "", r.get("reprocess_id") or ""),
            )
            for row in cands:
                if row.get("claimed_by") and not lease_expired(row.get("lease_until")):
                    continue  # 别人正拿着有效租约
                rid = str(row.get("reprocess_id") or "")
                n = int(row.get("attempts") or 0)
                if n >= self.max_attempts:
                    self._reject_reprocess(
                        row,
                        f"超过最大处理尝试次数 {self.max_attempts}，已放弃。"
                        f"上一次错误：{row.get('last_error')}（失败是环境问题，不是结论，所以标 rejected 而不是 done）",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                targets = [str(x) for x in (row.get("relation_ids") or []) if x]
                if not targets:
                    self._reject_reprocess(
                        row, "目标关系为空 ⇒ **无目标的重抽取会退化成全量重抽**，拒绝", tx
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                missing = [t for t in targets if t not in known_relations]
                if missing:
                    self._reject_reprocess(
                        row,
                        f"目标关系不存在：{'、'.join(missing)}（可能已被删除或被 I5 合并到 survivor 上）"
                        "⇒ 不做任何猜测性重抽",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                reason = str(row.get("reason") or "")
                if reason == "structural_duplicate":
                    # I5 的合并决定需要"C 的候选"（概念对 + 名字证据 + 邻域），
                    # 仅凭 relation_ids 无法判定两个概念是否同义。猜一个合并就是绕过
                    # "两路独立证据"这条规则，所以拒绝，并把请求交回候选路径。
                    self._reject_reprocess(
                        row,
                        "reason=structural_duplicate 无法用 relation_ids 判定：合并必须走 "
                        "decide_structural_duplicate(candidate)（候选里有概念对与名字证据）"
                        "⇒ 拒绝，不做猜测性合并",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                adm = I.admit_reprocess_request(
                    self._quota_rows(rows, rid), relation_ids=targets, reason=reason
                )
                if not adm.get("admitted"):
                    self._reject_reprocess(row, f"准入闸门拒绝：{adm.get('reason')}", tx)
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                row["claimed_by"] = self.actor
                row["lease_until"] = make_lease(self.lease_seconds)
                row["attempts"] = n + 1
                tx.upsert("reprocess_requests", row, note="reprocess_claimed")
                return dict(row), rejected
        return None, rejected

    def _load_doc_for(self, lit: Mapping[str, Any] | None) -> tuple[Any, str]:
        """重新打开目标文献，返回 `(doc, 不可用原因)`；原因非空时 doc 为 `None`。

        为什么把"原因"作为返回值而不是抛异常：I4 的每一次"没做到"都必须落成
        一行可读的证据（`result_note`）。抛异常会把它变成一次失败重试，最后变成
        `rejected` —— 看起来像 B 做错了事，而事实是"这份文献本来就无法逐字定位"
        （扫描件、没下载到 PDF）。静默失败比崩溃更危险，所以这里要的是"说出来"。
        """
        if lit is None:
            return None, "文献不在文献表里（关系指向了一个不存在的 lit_id）"
        lid = str(lit.get("lit_id") or "")
        try:
            path = self.store.library_path(lit.get("path"))
        except Exception as e:
            return None, f"文献路径非法：{e}"
        if path is None:
            return None, f"文献 {lid} 没有本地文件（path=null，通常是没有下载到 PDF）"
        if not path.exists():
            return None, f"文献 {lid} 的本地文件不存在：{path.name}"
        try:
            doc = self.extract_text(path)
        except Exception as e:
            return None, f"文献 {lid} 重新抽取失败：{type(e).__name__}: {e}"
        if not list(getattr(doc, "pages", None) or []):
            return None, f"文献 {lid} 无文本层（扫描版？）⇒ 无从逐字定位"
        return doc, ""

    def _candidate_passages(self, doc, pr, *, fulltext: bool) -> list[tuple[int, str]]:
        """候选片段 `(页号, 片段)`。先看声明页附近，需要时再看全文。"""
        pages = list(getattr(doc, "pages", None) or [])
        if not pages:
            return []
        if fulltext or pr is None or not getattr(pr, "known", False):
            rng = list(range(1, len(pages) + 1))
        else:
            lo = max(1, int(pr.start) - self.reprocess_context_pages)
            hi = min(len(pages), int(pr.end) + self.reprocess_context_pages)
            rng = list(range(lo, hi + 1))
        out: list[tuple[int, str]] = []
        for p in rng:
            for seg in _passages(pages[p - 1]):
                out.append((p, seg))
        return out

    def _context_passage(self, doc, pr) -> tuple[str, str]:
        """`need_context` 用的原文片段（只读）：返回 `(取自哪里, 片段)`。

        优先用 `extract.py` 已经提供的 `DocumentText.text_at`（1-based 闭区间）：
        B 不该自己再拼一遍页码语义 —— 拼错了会给出错误页的"上下文"，
        而 D 会把它当成 L3 溯源的证据（那正是最不该出错的地方）。
        """
        pages = list(getattr(doc, "pages", None) or [])
        if pr is not None and getattr(pr, "known", False):
            lo = max(1, int(pr.start) - self.reprocess_context_pages)
            hi = min(len(pages), int(pr.end) + self.reprocess_context_pages)
            where = f"声明页码 {pr.label or f'{pr.start}-{pr.end}'}（实际取第 {lo}-{hi} 页）"
        else:
            lo, hi = 1, len(pages)
            where = f"页码未知（实际取全文第 {lo}-{hi} 页）"
        at = getattr(doc, "text_at", None)
        text = at(lo, hi) if callable(at) else "\n".join(pages[lo - 1 : hi])
        return where, text

    def _find_equivalent_quote(self, doc, rel: Mapping[str, Any], pr) -> tuple[str, str, dict | None]:
        """`quote_unverifiable`：回原文找该陈述的等价表述，并重跑既有回验。

        两道闸门，缺一不可：

        1. 相似度闸门 —— 候选片段必须与关系的 `statement`/`description` 足够像
           （token Jaccard ≥ `reprocess_min_similarity`）。低于阈值就报 `not_found`：
           宁可不改，也不把"随便一句像的话"塞进 `quote`。
        2. 既有回验闸门 —— 选中的片段必须再走一遍 `check_quote`（复用
           quoteverify 的同一份实现，不另写判据）。它是原页的连续切片，正常必然通过；
           若不通过，就说明"看着像"并不等于"逐字在原文里"，此时不算找到。
        """
        statement = str(rel.get("statement") or rel.get("description") or "") or str(rel.get("quote") or "")
        if not statement.strip():
            return "not_found", "关系既无 statement 也无 description，无法判断何为'等价表述'，未改动", None
        best_score, best = 0.0, None
        scope_text = ""
        for scope_text, fulltext in (("声明页附近", False), ("全文", True)):
            for page, seg in self._candidate_passages(doc, pr, fulltext=fulltext):
                score = T.similarity(seg, statement)
                if score > best_score:
                    best_score, best = score, (page, seg)
            if best is not None and best_score >= self.reprocess_min_similarity:
                break
        if best is None or best_score < self.reprocess_min_similarity:
            return (
                "not_found",
                f"在{scope_text or '原文'}的候选片段里，与陈述最相似的片段相似度仅 {best_score:.2f}"
                f"（阈值 {self.reprocess_min_similarity:.2f}）⇒ 不认定存在等价表述，**未改动引文**",
                None,
            )
        page, seg = best
        chk = check_quote(
            doc,
            seg,
            S.PageRange(page, page, f"p. {page}"),
            widen=self.widen_pages,
            allow_fulltext_fallback=self.allow_fulltext_fallback,
        )
        if chk.verified is not True:
            return (
                "not_found",
                f"找到候选片段（第 {page} 页，相似度 {best_score:.2f}），但**既有的引文回验**未通过"
                f"（{chk.reason}）⇒ 不写入：'看起来像'不等于'逐字在原文里'",
                None,
            )
        return (
            "found",
            f"在第 {page} 页找到与陈述相似度 {best_score:.2f} 的等价表述，已更新 "
            f"quote/quote_normalized/page_range，并通过既有引文回验（{chk.reason}；窗口 {chk.window}）",
            {
                "quote": seg,
                "quote_normalized": T.normalize_for_quote(seg),
                "page_range": S.PageRange(page, page, f"p. {page}").to_dict(),
                "quote_verified": True,
                "_quote_check": chk.to_dict(),
            },
        )

    def _expand_statement(self, doc, rel: Mapping[str, Any], pr) -> tuple[str, str, dict | None]:
        """`low_information`：回到文献该页附近，把陈述换成包含它的更长片段。

        判据是"字面锚点 + 严格更长"，不用相似度：这里是扩展而不是检索，
        扩展的合法性来自"新片段确实包含旧陈述"—— 那是一个可逐字核实的事实。
        找不到锚点就报 `unchanged`：不臆造一个"更完整的陈述"
        （那正是"把没做到写成做成了"的经典形态）。
        """
        cur = str(rel.get("statement") or rel.get("description") or "")
        anchor = cur.strip() or str(rel.get("quote") or "").strip()
        if not anchor:
            return "unchanged", "关系没有 statement/description/quote 可作锚点，无法定位到原文段落，未改动", None
        na = T.normalize_for_quote(anchor)
        best: tuple[int, str] | None = None
        for page, seg in self._candidate_passages(doc, pr, fulltext=True):
            if na and na in T.normalize_for_quote(seg):
                if best is None or len(seg) > len(best[1]):
                    best = (page, seg)
        if best is None:
            return (
                "unchanged",
                f"在文献原文里找不到当前陈述的字面锚点（{T.clip(anchor, 80)!r}）"
                "⇒ 不臆造'更完整的陈述'，未改动",
                None,
            )
        page, seg = best
        if len(seg.strip()) <= len(cur.strip()):
            return (
                "unchanged",
                f"第 {page} 页所在片段并不比当前陈述更完整（{len(seg.strip())} ≤ {len(cur.strip())} 字符），未改动",
                None,
            )
        return (
            "improved",
            f"在第 {page} 页找到包含当前陈述的更长片段（{len(cur.strip())} → {len(seg.strip())} 字符），"
            "已更新 statement/description",
            {"statement": seg, "description": seg},
        )

    def _perform_reprocess(self, req: Mapping[str, Any]) -> dict:
        """重活（回原文重新定位/抽取）—— 在事务外做。

        为什么不放在事务里：抽取一篇 PDF 可能几秒到几十秒，而事务要持有
        relations / reprocess_requests 的锁；把重活放进去等于推翻 store 的"锁内短"
        （见 store.py 的模块 docstring）。代价是必须在收尾时再核对一次
        "A 阶段读到的那一行有没有被别人改过" —— 见 `_finish_reprocess`。

        返回的 `result` 一定是 :data:`REPROCESS_RESULTS` 里的词；
        "做不到"必须显式落成 `not_found` / `unchanged` + 理由。
        """
        reason = str(req.get("reason") or "")
        targets = [str(x) for x in (req.get("relation_ids") or []) if x]
        rel_index = {str(r.get("relation_id")): r for r in self.store.rows("relations")}
        lit_index = {str(l.get("lit_id")): l for l in self.store.rows("literature")}

        docs: dict[str, tuple[Any, str]] = {}

        def doc_for(lit_id: str) -> tuple[Any, str]:
            # 同一篇文献在一次请求里只抽一次（一次请求可以针对多条关系）。
            if lit_id not in docs:
                docs[lit_id] = self._load_doc_for(lit_index.get(lit_id))
            return docs[lit_id]

        lines: list[str] = []
        words: list[str] = []
        updates: dict[str, dict] = {}
        fingerprints: dict[str, dict] = {}
        for rid in targets:
            rel = rel_index.get(rid)
            if rel is None:
                words.append("not_found")
                lines.append(f"[{rid}] not_found：目标关系已不存在（可能刚被删除或被 I5 合并），未改动任何数据")
                continue
            lit_id = str(rel.get("lit_id") or "")
            doc, why = doc_for(lit_id)
            if doc is None:
                # "无法真正重抽"的唯一合法表达：结果 + 明确的原因。
                word = "unchanged" if reason == "low_information" else "not_found"
                words.append(word)
                lines.append(f"[{rid}] {word}：无法真正重抽 —— {why}；关系保持原样（不假装成功）")
                continue
            pr = S.PageRange.from_dict(rel.get("page_range"))
            if reason == "need_context":
                where, passage = self._context_passage(doc, pr)
                words.append("found")
                lines.append(
                    f"[{rid}] found：{where}原文片段（逐字，供 D 做 L3 溯源；**只读**，未改动关系）：\n{passage}"
                )
                continue
            if reason == "quote_unverifiable":
                word, note, upd = self._find_equivalent_quote(doc, rel, pr)
            else:  # low_information（其余取值已在认领阶段被拒）
                word, note, upd = self._expand_statement(doc, rel, pr)
            words.append(word)
            lines.append(f"[{rid}] {note}")
            if upd:
                updates[rid] = upd
                fingerprints[rid] = {
                    "quote": rel.get("quote"),
                    "statement": rel.get("statement"),
                    "description": rel.get("description"),
                }
        if reason in ("need_context", "quote_unverifiable"):
            result = "found" if "found" in words else "not_found"
        else:
            result = "improved" if "improved" in words else "unchanged"
        return {
            "result": result,
            "note": f"reason={reason}；目标 {len(targets)} 条\n" + "\n".join(lines),
            "touched": sorted(updates),
            "updates": updates,
            "fingerprints": fingerprints,
        }

    def _record_reprocess_failure(self, req: Mapping[str, Any], error: str) -> None:
        """处理失败：记 `last_error` 并释放租约，状态仍为 `pending`。

        为什么不标 `done` + `result="not_found"`：`not_found` 的含义是
        "我看过了，原文里没有" —— 那是一个结论；这里发生的是"我压根没看成"。
        把后者写成前者，正是 DESIGN-INTERACTIONS.md §3.4 点名禁止的形态。
        """
        with self.store.tx("reprocess_requests", actor=self.actor, note="reprocess_failed") as tx:
            row = tx.find("reprocess_requests", reprocess_id=req.get("reprocess_id")) or dict(req)
            row["last_error"] = T.clip(error, 500)
            row["claimed_by"] = None
            row["lease_until"] = None
            tx.upsert("reprocess_requests", row, note="reprocess_failed")

    def _finish_reprocess(self, req: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict:
        """收尾（短事务）：写入目标关系的新字段 + 请求的终局结果。

        这里刻意不声明 `literature` 表：重抽取是"重新看已有的"，不是
        "当作没看过"。把 `processed` 置回 `False` 会触发全量重抽（I4 的幂等陷阱），
        而不声明该表 = 结构上不可能犯这个错（提交只会写 `t._dirty` 里的表）。

        目标行在写入前会核对指纹：A 阶段（锁外）读到的 quote/statement/description
        若已被别人改过，就放弃写入并如实记下来 —— 宁可少改一次，也不要覆盖另一个
        B 实例刚写下的结果（那会是一次静默的丢失更新，store 的模块 docstring
        说的正是这件事）。
        """
        result_word = str(outcome.get("result") or "")
        if result_word not in REPROCESS_RESULTS:
            # 程序错误就该炸：写一个词表外的 result 会让下游统计静默失准。
            raise ValueError(f"I4 的结果必须是 {REPROCESS_RESULTS} 之一，收到 {result_word!r}")
        touched: list[str] = []
        stale: list[str] = []
        with self.store.tx("relations", "reprocess_requests", actor=self.actor, note="reprocess") as tx:
            live = {str(r.get("relation_id")): r for r in tx.rows("relations")}
            for rid, upd in (outcome.get("updates") or {}).items():
                row = live.get(str(rid))
                if row is None:
                    stale.append(f"{rid}（已不存在）")
                    continue
                fp = (outcome.get("fingerprints") or {}).get(rid) or {}
                if any(row.get(k) != v for k, v in fp.items()):
                    stale.append(f"{rid}（处理期间被改动）")
                    continue
                upd = dict(upd)
                if "quote" in upd:
                    # dedup_key 是"概念组 + 引文哈希"的派生字段：改了 quote 必须重算，
                    # 否则索引键与内容漂移，后续判重会按旧键比较（静默失效）。
                    upd["dedup_key"] = D.relation_dedup_key(
                        str(row.get("concept_group_key") or ""), str(upd["quote"])
                    )
                upd["_reprocess"] = {
                    "reason": req.get("reason"),
                    "reprocess_id": req.get("reprocess_id"),
                    "result": result_word,
                    "at": S.now_iso(),
                }
                row.update(upd)
                tx.upsert("relations", row, note=f"reprocess:{req.get('reason')}")
                touched.append(str(rid))
            note = str(outcome.get("note") or "")
            if stale:
                note += f"\n未写入（目标已变，避免覆盖别人的写入）：{'、'.join(stale)}"
            row = tx.find("reprocess_requests", reprocess_id=req.get("reprocess_id")) or dict(req)
            row["status"] = "done"
            row["result"] = result_word
            row["result_note"] = T.clip(note, NOTE_LIMIT)
            row["touched_relation_ids"] = sorted(touched)
            row["claimed_by"] = None
            row["lease_until"] = None
            row["last_error"] = None
            tx.upsert("reprocess_requests", row, note=f"reprocess_done:{result_word}")
        return {
            "handled": True,
            "reprocess_id": str(req.get("reprocess_id") or ""),
            "result": result_word,
            "touched_relation_ids": sorted(touched),
            "stale_targets": stale,
            "note": row["result_note"],
        }

    # ------------------------------------------------------------------ I5 结构重复的合并决定
    @staticmethod
    def _id_order(cid: str) -> int:
        """`concept_id` 的可比较次序。非法 ID 排到最后 —— 它不该在 tie-break 里胜出。"""
        return int(cid) if str(cid).isdigit() else 10**9

    @staticmethod
    def _dedup_match(
        rows: Sequence[Mapping[str, Any]],
        *,
        exclude_id: str,
        name: str,
        aliases: Sequence[str],
    ) -> dict | None:
        """在去掉某一行的概念表上跑一次 `dedup.find_concept`（同一套规范化）。

        为什么要去掉自己：`find_concept` 会把行自己的名字算进候选，于是"查自己"
        必然命中自己 —— 复核就退化成恒真。去掉自己之后，"A 的名字解析到 B"
        才真的是"判重索引认为 A 与 B 是同一个概念"。
        """
        rest = [r for r in rows if str(r.get("concept_id")) != str(exclude_id)]
        return D.find_concept(rest, name, list(aliases or []))

    def decide_structural_duplicate(
        self,
        candidate: Mapping[str, Any] | None,
        *,
        concepts: Sequence[Mapping[str, Any]] | None = None,
        relations: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict:
        """I5：对 C 提出的"结构重复候选"给出合并或否决的决定（决定权在 B）。

        决策规则（保守；两路证据必须独立成立）
        ----------------------------------------
        1. 结构侧（由 B 自己复算，不采信候选里的结论）：候选必须恰是两个概念、
           两者都还是活节点（`merged_into` 为空），且两者之间没有直接关系 ——
           有直接关系说明它们已经被声明为两个不同的东西，"邻域相同"在这里是
           自然现象，合并会抹掉一条真实知识。
        2. 名字侧（第二路，独立于结构）：先要求 C 给的名字证据不是 `"none"`，
           再用 `dedup.find_concept` 的同一套规范化独立复核：去掉 A 之后，
           用 A 的名字/别名查判重索引，必须恰好查回 B；反向亦然。
           "恰好"很重要：若查回的是第三个概念，说明名字有歧义 ⇒ 不合并。

        两条都成立才 `merge`；否则 `reject`，并且必须给出能被反驳的理由
        （例如"邻域相同但规范化名字不同且无别名交集 ⇒ 结构等价 ≠ 同义"）。

        为什么这么保守：结构等价 ≠ 同义。"所有子群都同构的两个概念"完全可能
        连着同一批邻居。错误合并不可逆（度数、路径、问题溯源全被污染），
        而漏合并只是少省一点空间。

        survivor 的选取规则（确定性，不随机）
        -----------------------------------
        定义更长的一方存活；定义长度相同（含都为空）时取 `concept_id` 较小者。
        理由：survivor 的定义会留在图上，丢掉更完整的定义等于静默删知识；
        `concept_id` 是唯一稳定的全序，用它兜底保证"同一候选永远得到同一结论"
        （可复现、可审计，且不依赖表的物理顺序）。

        返回 ``{"verdict", "reason", "survivor_id", "merged_id", "evidence"}``。
        本方法只决定不落盘；执行合并用 :meth:`resolve_structural_duplicate`。
        """
        rows_c = list(concepts) if concepts is not None else self.store.rows("concepts")
        rows_r = list(relations) if relations is not None else self.store.rows("relations")
        cids = [str(x) for x in ((candidate or {}).get("concept_ids") or [])]

        def reject(why: str) -> dict:
            return {
                "verdict": "reject",
                "reason": why,
                "survivor_id": None,
                "merged_id": None,
                "evidence": {"concept_ids": cids, "candidate_proposal": (candidate or {}).get("proposal")},
            }

        if len(cids) != 2:
            return reject(f"候选必须**恰好两个**概念（I5 的结构重复是成对的），收到 {cids!r}")
        a_id, b_id = sorted(cids)
        if a_id == b_id:
            return reject(f"候选的两个概念代号相同（{a_id}）⇒ 这不是一对，拒绝")
        by_id = {str(c.get("concept_id")): c for c in rows_c}
        a, b = by_id.get(a_id), by_id.get(b_id)
        if a is None or b is None:
            return reject(f"候选里有概念不存在于概念表（{a_id if a is None else b_id}）⇒ 无法复核，拒绝")
        if a.get("merged_into") or b.get("merged_into"):
            return reject(
                f"{a_id}/{b_id} 中有一方已经是墓碑（merged_into 非空）⇒ 应把候选转到 survivor 上，不得二次合并"
            )
        for r in rows_r:
            rc = {str(x) for x in (r.get("concept_ids") or [])}
            if a_id in rc and b_id in rc:
                return reject(
                    f"{a_id} 与 {b_id} 之间存在直接关系 {r.get('relation_id')} ⇒ 它们**已被声明为"
                    "两个不同的东西**，此时'邻域相同'是自然的，**不得合并**"
                )
        name_ev = str((candidate or {}).get("name_evidence") or "none")
        if name_ev == "none":
            return reject(
                "邻域相同但规范化名字不同、也无别名交集 ⇒ **结构等价 ≠ 同义**"
                "（两个不同的概念完全可能连着同一批邻居）；只有一路证据，不得合并"
            )
        fwd = self._dedup_match(rows_c, exclude_id=a_id, name=str(a.get("name") or ""), aliases=a.get("aliases") or [])
        rev = self._dedup_match(rows_c, exclude_id=b_id, name=str(b.get("name") or ""), aliases=b.get("aliases") or [])
        got_fwd = str(fwd.get("concept_id")) if fwd else None
        got_rev = str(rev.get("concept_id")) if rev else None
        if got_fwd != b_id or got_rev != a_id:
            return reject(
                "名字侧独立复核未通过：用 dedup.find_concept（同一套规范化）在**去掉自身**的表上查，"
                f"{a_id} 的名字解析到 {got_fwd or '无命中'}（期望 {b_id}）、"
                f"{b_id} 的名字解析到 {got_rev or '无命中'}（期望 {a_id}）"
                "⇒ 名字证据不足或存在歧义（可能别名指向第三个概念），不得合并"
            )
        len_a = len(str(a.get("definition") or "").strip())
        len_b = len(str(b.get("definition") or "").strip())
        survivor, merged = (
            (a, b) if (len_a, -self._id_order(a_id)) >= (len_b, -self._id_order(b_id)) else (b, a)
        )
        survivor_id, merged_id = str(survivor["concept_id"]), str(merged["concept_id"])
        neigh = [str(x) for x in ((candidate or {}).get("neighbors") or [])]
        # `_NAME_EVIDENCE_TEXT` 是 C 侧同一份证据的人话说明：复用它，避免
        # "C 说这是别名证据、B 的报告却写成别的词"这种同一事实两种措辞。
        # 取不到时回退到代码本身（宁可少一句人话，也不许因为措辞表改名就炸）。
        why_name = getattr(I, "_NAME_EVIDENCE_TEXT", {}).get(name_ev, name_ev)
        reason = (
            "两路独立证据同时成立：① 结构等价（邻域完全相同"
            + (f"：{'、'.join(neigh)}" if neigh else "")
            + "，且两者之间无直接关系 —— 由 B 从关系表复算确认）；"
            f"② 名字侧证据「{why_name}」，且 B 用 dedup.find_concept 的同一套规范化独立复核双向命中。"
            f"按确定性规则（定义更长者存活，同长取 concept_id 较小者：{len_a} vs {len_b} 字符）"
            f"⇒ {survivor_id} 存活、{merged_id} 被吸收"
        )
        return {
            "verdict": "merge",
            "reason": reason,
            "survivor_id": survivor_id,
            "merged_id": merged_id,
            "evidence": {
                "concept_ids": [a_id, b_id],
                "name_evidence": name_ev,
                "candidate_proposal": (candidate or {}).get("proposal"),
                "detected_by": (candidate or {}).get("detected_by"),
                "definition_lengths": {a_id: len_a, b_id: len_b},
            },
        }

    def resolve_structural_duplicate(self, candidate: Mapping[str, Any] | None) -> dict:
        """决定 + 执行合并（I5）。返回决定字段加执行摘要。

        为什么在一个事务里"先复核再执行"：候选是 C 用无锁快照算出来的，
        等 B 拿到它时图可能已经变了（另一个 B 实例刚写了新关系、或刚合并了别的对）。
        因此决定必须基于本事务读到的行重算一遍，而不是采信候选里的结论。
        判成 `reject` 时一行数据都不写（只返回理由）。

        关系改写的后果是想清楚的
        ------------------------
        把被合并方换成 survivor 之后，可能产生重复关系（两条关系变成同一概念组、
        同一引文）。这里不自己造一套判据，而是把改写后的行喂给既有的
        `dedup.decide_relation`：判成 `duplicate` 的行标 `status="rejected"` +
        `duplicate_of` 指向幸存关系（保留行，删了就无从审计）；判成 `suspect`
        的行降级为 `suspect`；其余保持原状态。
        改写还会影响 `related_concepts`，因此所有受影响的概念都用
        `dedup.derive_related_concepts` 整体重算（派生而非增量，DESIGN.md §6.2）。
        """
        with self.store.tx("concepts", "relations", actor=self.actor, note="structural_merge") as tx:
            decision = self.decide_structural_duplicate(
                candidate, concepts=tx.rows("concepts"), relations=tx.rows("relations")
            )
            if decision["verdict"] != "merge":
                return {
                    **decision,
                    "applied": False,
                    "rewritten_relation_ids": [],
                    "rejected_relation_ids": [],
                    "skipped_relation_ids": [],
                }
            summary = self._apply_merge(tx, decision)
        return {**decision, **summary}

    def _apply_merge(self, tx, decision: Mapping[str, Any]) -> dict:
        """在给定事务内执行合并（调用方已完成复核）。见 :meth:`resolve_structural_duplicate`。"""
        survivor_id = str(decision["survivor_id"])
        merged_id = str(decision["merged_id"])
        rel_rows = tx.rows("relations")

        def contains_merged(r: Mapping[str, Any]) -> bool:
            return merged_id in {str(x) for x in (r.get("concept_ids") or [])}

        rewritten: list[str] = []
        rejected: list[str] = []
        skipped: list[str] = []
        # 未被改写的行随时可作判重的对照集（按 relation_id 升序改写，保证结论稳定）
        untouched = [dict(r) for r in rel_rows if not contains_merged(r)]
        accepted: list[dict] = []
        for r in sorted((r for r in rel_rows if contains_merged(r)), key=lambda r: str(r.get("relation_id"))):
            rid = str(r.get("relation_id"))
            new_cids = S.sorted_unique(
                [survivor_id if str(c) == merged_id else str(c) for c in (r.get("concept_ids") or [])]
            )
            if len(new_cids) < 2:
                # 防御分支：候选要求"两者之间无直接关系"（decide 里已复算过），
                # 正常不可达。真到了这里就只标记不改写，绝不静默丢行。
                row = dict(r)
                row["_merge_note"] = (
                    f"I5 合并**未改写**本行：概念组改写后会塌缩成 {new_cids!r}（少于 2 个概念），"
                    "交人工/下一轮处理"
                )
                tx.upsert("relations", row, note="structural_merge_skipped")
                skipped.append(rid)
                continue
            new_key = T.concept_group_key(new_cids)
            d = D.decide_relation(
                untouched + accepted,
                concept_group_key=new_key,
                quote=str(r.get("quote") or ""),
                description=str(r.get("description") or ""),
                dup_strong=self.dup_strong,
                dup_review=self.dup_review,
            )
            row = dict(r)
            row["concept_ids"] = new_cids
            row["concept_group_key"] = new_key
            row["dedup_key"] = D.relation_dedup_key(new_key, str(r.get("quote") or ""))
            if d.kind == "duplicate":
                row["status"] = "rejected"
                row["duplicate_of"] = d.existing_id
                row["_merge_note"] = (
                    f"I5 合并改写后与 {d.existing_id} 同概念组且引文重复（分数 {d.score:.3f}）"
                    "⇒ 交既有判重逻辑处理：本行标 rejected 并保留为证据，指向幸存关系"
                )
                rejected.append(rid)
            elif d.kind == "suspect":
                row["status"] = "suspect"
                row["duplicate_of"] = d.existing_id
                row["_merge_note"] = (
                    f"I5 合并改写后与 {d.existing_id} 高度相似（{d.score:.3f}）⇒ 按既有判重降级为 suspect"
                )
                accepted.append(row)
                rewritten.append(rid)
            else:
                row["_merge_note"] = f"I5 合并改写：概念 {merged_id} → {survivor_id}（关系内容未改动）"
                accepted.append(row)
                rewritten.append(rid)
            tx.upsert("relations", row, note=f"structural_merge:{merged_id}->{survivor_id}")

        # ---- 受影响概念的 related_concepts 整体重算（派生而非增量，漏更新会自愈）
        final_rels = tx.rows("relations")
        changed = set(rewritten) | set(rejected)
        affected = {survivor_id, merged_id}
        for r in final_rels:
            if str(r.get("relation_id")) in changed:
                affected.update(str(x) for x in (r.get("concept_ids") or []))
        for cid in sorted(affected):
            row = next((c for c in tx.rows("concepts") if str(c.get("concept_id")) == cid), None)
            if row is None:
                continue
            want = D.derive_related_concepts(cid, final_rels, include_suspect=True)
            if row.get("related_concepts") != want:
                row["related_concepts"] = want
                row["updated_at"] = S.now_iso()
                tx.upsert("concepts", row, note="related_recomputed")

        # ---- 概念行：survivor 收别名（含被合并方的名字），被合并方立墓碑
        survivor = next(c for c in tx.rows("concepts") if str(c.get("concept_id")) == survivor_id)
        merged = next(c for c in tx.rows("concepts") if str(c.get("concept_id")) == merged_id)
        own = survivor.get("normalized_name") or T.normalize(str(survivor.get("name") or ""))
        aliases = S.sorted_unique(
            list(survivor.get("aliases") or []) + [str(merged.get("name") or "")] + list(merged.get("aliases") or [])
        )
        aliases = [x for x in aliases if x and T.normalize(x) != own]
        if aliases != (survivor.get("aliases") or []):
            survivor["aliases"] = aliases
        survivor["updated_at"] = S.now_iso()
        tx.upsert("concepts", survivor, note="alias_merge")

        reason = str(decision.get("reason") or "")
        reason += (
            f"；关系改写：{len(rewritten)} 条改指 {survivor_id}"
            + (
                f"，其中 {len(rejected)} 条改写后与既有关系同组同引文 ⇒ 按既有判重逻辑标 "
                "rejected（保留为证据，未删除）"
                if rejected
                else ""
            )
            + (f"；{len(skipped)} 条因概念组塌缩**未改写**，待人工/下一轮处理" if skipped else "")
        )
        merged["merged_into"] = survivor_id
        merged["merge_reason"] = reason
        merged["merged_at"] = S.now_iso()
        merged["_merge"] = {
            "survivor_id": survivor_id,
            "rewritten_relation_ids": sorted(rewritten),
            "rejected_relation_ids": sorted(rejected),
            "skipped_relation_ids": sorted(skipped),
            "evidence": dict(decision.get("evidence") or {}),
        }
        tx.upsert("concepts", merged, note="merged")
        return {
            "applied": True,
            "survivor_id": survivor_id,
            "merged_id": merged_id,
            "merge_reason": reason,
            "rewritten_relation_ids": sorted(rewritten),
            "rejected_relation_ids": sorted(rejected),
            "skipped_relation_ids": sorted(skipped),
        }

    def run(self, max_docs: int | None = None) -> dict:
        """处理若干篇文献（`max_docs=None` = 处理到没有可领的为止），最后处理定向重抽取。

        退出/停止条件只有一条：`run_once()` 给出 `skipped_reason`（队列空 / 全被别人
        占着 / 全被放弃）。返回累加后的 `BRunResult.to_dict()` + `reprocess` 摘要。
        """
        total = BRunResult()
        n = 0
        while max_docs is None or n < max_docs:
            r = self.run_once()
            total.skipped_lease_active += r.skipped_lease_active
            total.gave_up += r.gave_up
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
                break
            for f in (
                "processed",
                "concepts_created",
                "concepts_reused",
                "relations_added",
                "relations_duplicate",
                "relations_suspect",
                "suspect_by_quote",
                "quotes_verified",
                "quotes_failed",
                "quotes_unknown",
                "quotes_out_of_declared_range",
                "unreadable",
                "failed",
                "conflict_checks_run",
                "conflicts_detected",
                "conflict_checks_skipped",
            ):
                setattr(total, f, getattr(total, f) + getattr(r, f))
            total.details.extend(r.details)
            n += 1
        out = total.to_dict()
        # 文献消化完之后再处理定向重抽取：先把新知识落库，再回头修已有的。
        # 反过来做，刚修好的关系会立刻被新文献的判重/I6 闸门重算一遍，白做一次功。
        out["reprocess"] = self.run_reprocess()
        return out


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    """`python -m agentflow.agent_b` 的自检：跑通主路径并断言关键不变量。

    ## 为什么这个函数必须存在（它修的是一个静默空成功）

    `scripts/release_check.py` 第 2 项会逐个 `python -m agentflow.agent_<role>` 并看退出码。
    在本次修复之前，`agent_b` 没有 `__main__` 块，于是那条命令输出 0 行、退出码 0
    —— 旧判据会把它记成"自检通过"，而它其实什么都没检查。这正是本项目最忌讳的形态：
    "没做"被读成"通过"（`DEVELOPMENT.md` §10-D5 / 附录 C 第 4 条；
    `release_check.item_selftests` 现在专门用 `has_selftest` 把这种情况报成 `unknown`）。

    自检只覆盖离线、确定性的路径：概念复用与别名合并、引文回验失败的降级
    （suspect 而不是丢弃）、`processed` 的语义（抽取失败不置）、I6 闸门的三态计数、
    结构重复的保守否决、以及取文献侧的三态（队列空 / 全被别人占着 / 全被放弃）。

    退出码：`0` = 全部通过；`1` = 有失败项。
    """
    import shutil
    import tempfile
    from pathlib import Path

    checks: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        checks.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    class _Concept:
        def __init__(self, name, definition="", aliases=()):
            self.name, self.definition, self.aliases = name, definition, list(aliases)

    class _Relation:
        def __init__(self, concept_names, quote, description="", page_range=None):
            self.concept_names, self.quote = list(concept_names), quote
            self.description = description or quote
            # 引文回验只有在声明了页码（或显式开启 fulltext 兜底）时才会去扫原文；
            # 默认给已知页码，好让"逐字核实通过"这条主路径真的被走到。
            self.page_range = page_range or S.PageRange(1, 1, "p. 1")

    class _Extractor:
        """确定性抽取器替身：返回预先给好的概念/关系（不联网、不过模型）。"""

        def __init__(self, concepts=(), relations=()):
            self.concepts, self.relations = list(concepts), list(relations)
            self.seen_meta: list[dict] = []

        def extract(self, doc, lit_id, meta):
            self.seen_meta.append(dict(meta))
            return list(self.concepts), list(self.relations)

    class _FailingExtractor:
        def extract(self, doc, lit_id, meta):
            raise RuntimeError("selftest extractor boom")

    TEXT = "An abelian group is a group in which the commutative law holds. 群论里的交换律。"

    class _Doc:
        """最小文档替身：刻意不 import `extract.DocumentText`。

        契约是鸭子类型的，而且只有两条：`pages`（逐页文本）与 `text_at`（1-based 闭区间）。
        用最窄的替身把这两条钉死，比依赖 `extract.py` 的字段增删更稳
        （它也确实是 `quoteverify.check_quote` 实际读的全部）。
        """

        def __init__(self, text: str = TEXT, extra_pages: tuple[str, ...] = ()):
            #: `pages[0]` 是第 1 页。`extra_pages` 是给"页码写错"那一段用的：
            #: 引文落在第 2 页，而关系声明的是第 1 页（`E-11` 那一档）。
            self.pages = [text, *extra_pages]

        def text_at(self, lo: int, hi: int) -> str:
            return "\n".join(self.pages[lo - 1: hi])

    def _extract(_path) -> _Doc:
        return _Doc()

    def _write_lit(st: Store, lit_id: str, name: str) -> None:
        d = st.library / lit_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.txt").write_text(TEXT, encoding="utf-8")

    def _add_lit(st: Store, lit_id: str, *, path: str | None, processed: bool = False,
                 claimed_by: str | None = None, lease_until: str | None = None,
                 mine_attempts: int = 0) -> None:
        with st.tx("literature", actor="selftest") as tx:
            row = S.Literature(lit_id=lit_id, title=f"Selftest {lit_id}", type="J", summary="",
                               path=path, processed=processed, source_request_ids=[],
                               dedup_key=f"title:selftest {lit_id}|*", added_at=S.now_iso(),
                               claimed_by=claimed_by, lease_until=lease_until,
                               mine_attempts=mine_attempts)
            row.validate()
            tx.upsert("literature", row.to_dict(), note="selftest")

    def _lit(st: Store, lit_id: str) -> dict:
        return next(r for r in st.rows("literature") if r.get("lit_id") == lit_id)

    def _drain(st: Store) -> None:
        """把文献队列清空（每段断言都在一个已知的队列上做，段落之间不互相干扰）。"""
        with st.tx("literature", actor="selftest") as tx:
            for r in tx.rows("literature"):
                if not r.get("processed"):
                    r["processed"] = True
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("literature", r, note="selftest_drain")

    def _mk(root: Path, *, extractor=None, config=None) -> AgentB:
        cfg = {"lease_seconds": 900, "max_attempts": 3}
        cfg.update(config or {})
        return AgentB(Store(root), extractor=extractor or _Extractor(), extract_text=_extract, config=cfg)

    try:
        root = Path(tempfile.mkdtemp(prefix="agentflow_agent_b_selftest_"))
    except OSError:  # pragma: no cover - 沙箱拒绝系统临时目录时退到仓库内
        root = Path(__file__).resolve().parents[2] / "demo" / "agent_b_selftest"
        shutil.rmtree(root, ignore_errors=True)
    try:
        print("[agent_b 自检] 离线、确定性；工作区：", root)

        # ---- 1) 主路径：概念复用 + 引文逐字核实 + related_concepts 由关系表派生
        st = Store(root)
        st.init(force=True)
        _write_lit(st, "0000", "selftest")
        _add_lit(st, "0000", path="0000/selftest.txt")
        quote = "An abelian group is a group in which the commutative law holds."
        ext = _Extractor(
            concepts=[_Concept("group", "群"), _Concept("abelian group", "交换群")],
            relations=[_Relation(["group", "abelian group"], quote, "交换群是群")],
        )
        b = AgentB(st, extractor=ext, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res = b.run_once()
        check("主路径：处理 1 篇、建 2 个概念、写 1 条关系",
              res.processed == 1 and res.concepts_created == 2 and res.relations_added == 1)
        check("引文逐字核实通过（quotes_verified=1）且行内 quote_verified=True",
              res.quotes_verified == 1
              and st.rows("relations")[0].get("quote_verified") is True)
        check("processed 语义：处理完成后置 True 并释放租约",
              _lit(st, "0000")["processed"] is True and _lit(st, "0000")["claimed_by"] is None)
        check("related_concepts 由关系表**派生**（各自指向对方，不留空）",
              all(sorted(c["related_concepts"]) == sorted(
                  x["concept_id"] for x in st.rows("concepts") if x["concept_id"] != c["concept_id"])
                  for c in st.rows("concepts")))

        # ---- 2) 概念复用而不是重复建：同名概念走 find_concept，只在歧义时建新的
        _write_lit(st, "0001", "selftest")
        _add_lit(st, "0001", path="0001/selftest.txt")
        ext2 = _Extractor(concepts=[_Concept("group", ""), _Concept("交换群", "", ["abelian group"])], relations=[])
        b2 = AgentB(st, extractor=ext2, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res2 = b2.run_once()
        check("概念名复用：'group' 走既有代号、'交换群' 以别名并入 'abelian group'，都不新建概念",
              res2.concepts_created == 0 and res2.concepts_reused == 2 and len(st.rows("concepts")) == 2,
              f"created={res2.concepts_created} reused={res2.concepts_reused}")
        check("别名合并写回概念行（否则后续同义名会各自建一份概念）",
              any("交换群" in (c.get("aliases") or []) for c in st.rows("concepts")))
        check("抽取器拿到了概念表种子，且没有 seed_concepts_error（种子只影响召回率，不是权威）",
              bool(ext2.seen_meta[0].get("seed_concepts")) and "seed_concepts_error" not in ext2.seen_meta[0])

        # ---- 3) 引文回验失败 ⇒ 落库但降级 suspect（不丢弃证据）
        _write_lit(st, "0002", "selftest")
        _add_lit(st, "0002", path="0002/selftest.txt")
        ext3 = _Extractor(relations=[_Relation(["group", "abelian group"], "这句话原文里根本没有。", "幻觉引文")])
        b3 = AgentB(st, extractor=ext3, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res3 = b3.run_once()
        check("引文找不到：仍然落库（不丢证据）但 status=suspect，且 quote_verified=False",
              res3.relations_suspect == 1 and res3.suspect_by_quote == 1
              and any(r.get("status") == "suspect" and r.get("quote_verified") is False
                      for r in st.rows("relations")))
        check("I6 闸门计数可观察：跑了就计 conflict_checks_run，没跑就计 skipped（三态不折叠）",
              res3.conflict_checks_run + res3.conflict_checks_skipped >= 1)

        # ---- 3b) `E-11`：引文逐字存在、但页码写错 ⇒ 单独可数（不折进 verified）
        _drain(st)
        _write_lit(st, "0005", "selftest")
        _add_lit(st, "0005", path="0005/selftest.txt")
        ext3b = _Extractor(relations=[
            _Relation(["group", "abelian group"], TEXT, "页码写错",
                      page_range=S.PageRange(1, 1, "p. 1")),
        ])
        # 引文在第 2 页，而上面声明的页码是第 1 页；widen=1 ⇒ 落在扩展窗口里命中。
        # 第 1 页刻意给一段不含引文的文本：`_Doc` 的默认页就是 TEXT，直接用默认
        # 会让声明窗口内直接命中（`substring_match`），根本走不到"页码写错"那一档。
        b3b = AgentB(st, extractor=ext3b,
                     extract_text=lambda _p: _Doc(text="第一页：这里没有那句话。",
                                                  extra_pages=(TEXT,)),
                     config={"lease_seconds": 900, "max_attempts": 3, "quote_widen_pages": 1})
        res3b = b3b.run_once()
        check("页码写错：引文仍计 quotes_verified（逐字可达是真的），"
              "但必须**另计** quotes_out_of_declared_range=1（`E-11`）",
              res3b.quotes_verified == 1 and res3b.quotes_out_of_declared_range == 1,
              f"verified={res3b.quotes_verified} out_of_range={res3b.quotes_out_of_declared_range}")

        # ---- 4) 抽取失败 ⇒ 不置 processed（留给租约到期重试）
        _write_lit(st, "0003", "selftest")
        _add_lit(st, "0003", path="0003/selftest.txt")
        b4 = AgentB(st, extractor=_FailingExtractor(), extract_text=_extract,
                    config={"lease_seconds": 900, "max_attempts": 3})
        res4 = b4.run_once()
        check("抽取抛异常：failed=1 且文献**没有**被置 processed、last_mine_error 留下原因",
              res4.failed == 1 and _lit(st, "0003")["processed"] is False
              and "boom" in str(_lit(st, "0003")["last_mine_error"]))

        # ---- 5) 无本地文件 ⇒ 标为已处理并记明原因（否则永远堵在队首）
        # 先把上一段留下的"仍在队列里"的行清掉，让这一段的队列是已知的。
        _drain(st)
        _add_lit(st, "0004", path=None)
        b5 = AgentB(st, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res5 = b5.run_once()
        check("没有本地文件：unreadable=1、置 processed=True 并写明 no_local_file",
              res5.unreadable == 1 and _lit(st, "0004")["processed"] is True
              and "no_local_file" in str(_lit(st, "0004")["last_mine_error"]))

        # ---- 6) 取文献侧的三态：'队列空了' / '全被别人占着' / '全被放弃'
        st6 = Store(Path(root) / "claim")
        st6.init()
        b6 = AgentB(st6, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        empty = b6.run_once()
        check("队列空：skipped_reason=no_unprocessed_literature（不是静默的成功）",
              empty.skipped_reason == "no_unprocessed_literature")
        _add_lit(st6, "0000", path=None, claimed_by="agent-B-other", lease_until=make_lease(900))
        leased = b6.run_once()
        check("全都被人持着有效租约 ⇒ **不是**'队列空了'，而是 pending_literature_all_leased",
              leased.skipped_reason == "pending_literature_all_leased" and leased.skipped_lease_active == 1)
        check("被有效租约占着的行不会被抢走（claimed_by 原样保留）",
              _lit(st6, "0000")["claimed_by"] == "agent-B-other" and _lit(st6, "0000")["processed"] is False)
        _add_lit(st6, "0001", path=None, mine_attempts=3)
        gave = b6.run_once()
        check("超过 max_attempts ⇒ 显式放弃（gave_up=1）且 reason 与'全被租'可区分",
              gave.gave_up == 1 and gave.skipped_reason == "no_claimable_literature"
              and _lit(st6, "0001")["processed"] is True)
        check("三种 skipped_reason 互不相同（三态不许压成一个）",
              len({empty.skipped_reason, leased.skipped_reason, gave.skipped_reason}) == 3)

        # ---- 7) I5：结构重复必须有两路独立证据才合并，否则否决并给理由
        st7 = Store(Path(root) / "i5")
        st7.init()
        with st7.tx("concepts", actor="selftest") as tx:
            for cid, name, definition in (("0000", "群", "群的定义"), ("0001", "group", "")):
                row = S.Concept(concept_id=cid, name=name, definition=definition, related_concepts=[],
                                normalized_name=T.normalize(name), aliases=[],
                                created_at=S.now_iso(), updated_at=S.now_iso())
                row.validate()
                tx.upsert("concepts", row.to_dict(), note="selftest")
        b7 = AgentB(st7, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        no_ev = b7.decide_structural_duplicate(
            {"concept_ids": ["0000", "0001"], "name_evidence": "none", "neighbors": []}
        )
        check("名字侧无证据 ⇒ reject（'结构等价 ≠ 同义'，只有一路证据不得合并）",
              no_ev["verdict"] == "reject" and no_ev["survivor_id"] is None)
        row = b7.resolve_structural_duplicate({"concept_ids": ["0000", "0001"], "name_evidence": "none"})
        check("reject 时**一行数据都不写**（applied=False，两张表逐字节不变）",
              row["applied"] is False and all(c.get("merged_into") is None for c in st7.rows("concepts")))
    except Exception as e:  # noqa: BLE001
        # 自检自己炸了也必须报 FAIL（理由同 `agent_a._selftest`）：检查器"没跑成"
        # 不是"通过"，而 traceback 会让失败项清单为空、看不出挂在哪一条。
        checks.append((f"自检执行中断：{type(e).__name__}: {e}", False))
        print(f"    [FAIL] 自检执行中断：{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    bad = [label for label, ok in checks if not ok]
    print(f"[agent_b 自检] {len(checks) - len(bad)}/{len(checks)} 项通过")
    if bad:
        print("[agent_b 自检] 失败项：")
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
