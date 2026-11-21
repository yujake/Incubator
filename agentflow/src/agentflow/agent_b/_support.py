"""B 包内部件共用的小工具（口径与包入口同一份）。

职责与几条设计选择（锁内解析 / 派生而非增量 / suspect 落库 / 不置 processed / I6、I4、
I5）见 `agent_b/__init__.py` 的模块 docstring —— 这里不复制一份会漂的副本。本文件只放
dataclass、常量与纯函数小工具。
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
#: "这台机器没有够格的抽取器"这一档的落点（`R-56` 的拒抽）：`run_once` 把它写进
#: `last_mine_error`。单立一个常量、而不是在两处各写一遍字面量，是因为 `_claim` 的
#: 放弃分支要靠它分辨「真抽过、失败 N 次」与「从未真抽」（`D-2` 的第四档，2026-10-02）
#: —— 那两档的结论文字必须完全不同，而字面量写两遍就是漂移的开始。
NO_EXTRACTOR_ERROR = "no_llm_extractor"
QUOTE_OUT_OF_DECLARED_RANGE = "substring_match_outside_declared_range"
assert QUOTE_OUT_OF_DECLARED_RANGE in Path(quoteverify.__file__).read_text(
    encoding="utf-8"
), (
    f"quoteverify 里找不到 {QUOTE_OUT_OF_DECLARED_RANGE!r} 这个 reason ⇒ "
    "B 的 quotes_out_of_declared_range 会静默地永远是 0（`E-11` 的那一档又变成了看不见）"
)
#: `proof_manuscript` 收"路径"时允许的两个根（与 `agent_f.manuscript.PROMOTE_SOURCE_ROOTS`
#: 同一个口径：`notes/` 是草稿本、`reports/` 是正式落点）。别的根一律当"正文"处理，
#: 不按路径读盘 —— 这一格不许变成"从任意路径读一个文件当证明"。
_MANUSCRIPT_PATH_ROOTS: tuple[str, ...] = ("notes", "reports")


def _norm_manuscript_rel(value: Any) -> str:
    """`proof_manuscript` 的形状归一（只换分隔符；不猜、不补前缀）。"""
    return str(value or "").strip().replace("\\", "/")


def _is_manuscript_rel(rel: str) -> bool:
    """这一格看起来是不是一个工作区相对路径（而不是一份正文）。

    判据只认形状：单行（正文必然带换行）、带 `/`、以 `.md` 结尾、落在
    `notes/` 或 `reports/` 下、没有盘符 / 不以 `/` 开头 / 不含 `..`。
    """
    text = _norm_manuscript_rel(rel)
    if not text or "\n" in text or "\r" in text:
        return False
    if not text.casefold().endswith(".md") or "/" not in text:
        return False
    if text.startswith("/") or ":" in text:
        return False
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if len(parts) < 2 or any(p == ".." for p in parts):
        return False
    return parts[0] in set(_MANUSCRIPT_PATH_ROOTS)


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
    #: 为什么要单独一档：这一档在 `quoteverify.check_quote` 里是 `verified=True` +
    #: `reason='substring_match_outside_declared_range'` ⇒ 既被计进 `quotes_verified`（"逐字可达"是真的），
    #: 又不会把关系降为 `suspect`（`quote_failed` 判的是 `verified is not True`）⇒ "全部引文逐字可达"这条
    #: 判据在所有页码都记错时照样通过；这个信号原先只留在每行的 `_quote_check` 字典里，全仓没有消费者。
    #: 它不改 `verified`（抹成 False 会让"真引文被记成幻觉"，那是 FC-02 最贵的一档），也不改 suspect 口径
    #: （需人裁，`draft/28` 的 `E-11` 修法里写明了）：把这一档变成可判定的独立档 —— 这里单独计数，
    #: `verify --deep` 另有一条 `page_range_mismatch` 的 warning。
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
    #: 因"租约未过期而 `claimed_by` 为空"被跳过的条数：那是我们自己上次失败留下的退避。
    #: 与上一格分开数（`A.ARunResult` 同口径）：两者要等的对象不同 —— 等别人 / 等自己。
    #: 单列这一格的理由（`D-2`，与 A 同口径）：`_claim` 若只在 `claimed_by` 非空时
    #: 才认租约，B 自己写的退避租约就写了等于没写 —— 失败的那一行当轮就被重领，
    #: `mine_attempts` 在一次调用里烧到上限并被判死。
    skipped_lease_backoff: int = 0
    #: 本轮当场放弃（`mine_attempts` 用尽）的条数。
    gave_up: int = 0
    # ---- I6 写入期闸门的三态计数（必须从外部可观察）
    #:
    #: 没有这三个数，I6 就是"看起来接上了但没生效"：闸门返回 `checked=False`
    #: 时行会被照常写成 active，而单看数据完全看不出来"这次没检查"。
    conflict_checks_run: int = 0  # checked=True（检查过，无论是否矛盾）
    conflicts_detected: int = 0  # conflict=True（写入并标 suspect）
    conflict_checks_skipped: int = 0  # checked=False（没检查）
    # ---- 概念配额
    #:
    #: `concepts_refused`：这一趟因"配额用完"被「受控拒绝」的新概念条数；
    #: `relations_deferred`：因为要用的概念被拒、这一趟写不了的关系条数。
    #: 两个数都必须从外部可观察 —— 否则"少写了 N 条"与"本来就只有这么多"在台账上
    #: 长得一样（静默丢弃那一档要堵的就是它）。
    concepts_refused: int = 0
    relations_deferred: int = 0
    #: 配额的读数（`conceptrows.ConceptQuota.reading()`：`limit` / `written` /
    #: `refused` / `refused_count` / `why`）。空 dict = 这一趟没走到建概念那一步。
    concept_quota: dict = field(default_factory=dict)
    skipped_reason: str | None = None
    #: 这一趟领到的那篇文献，`literature.path` 是按哪个基准解析出来的
    #: （`library` / `workspace`；没领到或没解析出来 = 空串）。
    #:
    #: 为什么这一格要进读数：`literature.path` 的写入侧有两个坐标系（`search_tools._adopt_file`
    #: 先 `library/` 后 workspace），而抽取入口改前只认 `library/` ⇒ 一条按工作区相对写下的
    #: `library/000001/…` 被解析成 `library/library/…`、判 `file_missing`，而读数上
    #: "文件真的不在"与"在另一个基准下"同形。把基准记下来，这两种才分得开。
    #: `run` 汇总时保留第一条非空的（逐篇的来路在 `details[*stage=resolve]`）。
    path_base: str = ""
    #: 二阶段的自驱读数：`run_once` 每一拍都自己算一次「这一批还有哪几条证明没洗」，
    #: 并自己把该开的优化稿开出来（`open_optimization_drafts`）。它不等人派 ——
    #: 第一阶段（快录）与第二阶段（逐个优化）之间没有"等回执"这一跳。
    #:
    #: 形状由 `agent_b/run_once.py::_stage_two_self_drive` 一处给：
    #: `{checked, enabled, in_task, candidates, debt_count, debt, unwashed_count,
    #:   unwashed, opened, skipped_open, skipped_no_draft, refused, next_action, why}`。
    #: 空 dict = 这一拍没算（旧调用方拿到的返回形状因此逐字不变）。
    stage_two: dict = field(default_factory=dict)
    details: list[dict] = field(default_factory=list)

    #: 「真消化」过几篇 = `processed` − `unreadable`。
    #:
    #: 为什么这一格非有不可：`run_once` 在"没有本地全文 / 内容类型不符"那两支里「也」把
    #: `processed` 置 True（那两支本身是对的 —— 不置 True，那些行会永远堵在队首、
    #: 每一轮都被重领）。于是 `processed` 这一个布尔同时装着两件「处置相反」的事：
    #: 「我读过并抽了」与「我连文件都没有、跳过了」。下游读的全是 `processed`，
    #: 于是台账上写着"34 条已消化"，而真相是"10 条有全文、24 条只是被标了一下"。
    #: T5 那一趟的后果：M 连着派了 11 次同一种活（每次都拿到 `ok`），`relations` 始终 0 行，
    #: 一整轮预算花在"读不到的东西"上。「这就是"三态被折成一个布尔"的代价。」
    #:
    #: 它只数「真的调过抽取器」的那些，所以 `unreadable` / `skipped_no_extractor` 都不进
    #: （后者本来就不置 `processed`，列出来只为把话说完）。
    @property
    def digested(self) -> int:
        return max(0, int(self.processed) - int(self.unreadable))

    #: 这一趟的「任务级终局」（`TASK_OUTCOMES` 里的一个）。由 :func:`task_outcome` 一处算。
    @property
    def outcome(self) -> str:
        return task_outcome(self)[0]

    @property
    def detail(self) -> str:
        return task_outcome(self)[1]

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "details"}
        d["details"] = self.details[:20]
        # 三格一起进返回值（`digested` / `outcome` / `detail`）：主控读的是这份 dict，
        # 而"这一趟到底有没有产出"必须「在这一层就说实话」 —— 不能留给下游去猜
        # （下发现在 `processed` 上猜错过一次，见 `digested` 的说明）。
        d["digested"] = self.digested
        d["outcome"], d["detail"] = task_outcome(self)
        return d


def task_outcome(res: "BRunResult") -> tuple[str, str]:
    """B 的抽取这一趟「该报什么终局」 —— 唯一一处判据（动作自己声明，不由框架猜）。

    为什么必须由动作声明：框架那边只看得见"handler 返回了一个 dict 而没写 `outcome`"，
    于是按"有产出"记 `ok`（`conductor._end_from_payload`）。那一形态下，新建概念 0、
    新增关系 0 的一趟也会被记成 `outcome=ok`，主控据此以为"文献消化过了"、继续派同一种
    活 —— "什么都没做成"被报成了成功。

    规则（三态，与 `TASK_OUTCOMES` 同口径）：真消化过 ≥1 篇（`digested > 0`）⇒ `ok`；
    一篇都没真动（全是"没全文 / 缺抽取器 / 放弃 / 队列空"）⇒ `no_result`；有失败、且
    一篇都没真消化 ⇒ `failed`。`no_result` 是「有效结论」（"跑完了，确实没有产出"），
    不是错误 —— 它存在的意义正是让主控「看得见」"这一趟白跑了"，从而不再原样重派。
    """
    digested = res.digested  # 这一格是计算属性（processed − unreadable）：下面两处读的是同一个值
    worked = digested > 0
    produced = bool(res.concepts_created or res.concepts_reused or res.relations_added
                    or res.relations_duplicate or res.quotes_verified
                    or res.quotes_failed or res.quotes_unknown)
    stuck = bool(res.failed) and not worked and not produced
    detail = (f"真消化 {digested} 篇（新建概念 {res.concepts_created} / 复用 "
              f"{res.concepts_reused} / 新增关系 {res.relations_added} / 引文判定 "
              f"{res.quotes_verified + res.quotes_failed + res.quotes_unknown}）；"
              f"没有本地全文 {res.unreadable} 篇、缺抽取器 {res.skipped_no_extractor} 篇、"
              f"放弃 {res.gave_up} 篇、失败 {res.failed} 篇"
              + (f"；队列：{res.skipped_reason}" if res.skipped_reason else ""))
    if worked or produced:
        return "ok", detail
    if stuck:
        return "failed", detail + " ⇒ 这一趟没有任何产出"
    return "no_result", detail + " ⇒ 这一趟**没有任何产出**（不是成功，别按成功读）"
@dataclass
class BClaimOutcome:
    """`_claim()` 的结果：取文献这件事本身的结果，而不只是"取到的那一行"。
    为什么不让 `_claim()` 只返回 `dict | None`：一个 `None` 会把三件处置完全不同的事压成同一个值，而它们的下一步动作完全相反 ——
    - ``pending == 0``                 —— 队列里确实没有未处理文献（可以停）- ``skipped_lease_active > 0``
    —— 有活，但都在别人手里（该等，或换实例跑）- ``skipped_lease_backoff > 0``    —— 有活，但都在我们自己的退避租约里（到点自然重试）
    - ``gave_up > 0``                  —— 有活，但都超了重试上限（终局，别再等）
    压成一个 `None` 的后果不是"少一点信息"而是误导运维：`run_once()` 原先无论哪种情况都写 
    `skipped_reason="no_unprocessed_literature"`，于是"全都被人持着有效租约"被报成"队列空了"—— 看到的人会以为没事可做，而事实
    是有活压着。`agent_a.ClaimOutcome` 的 docstring 已经把这条纪律写透，这里只是把它原样搬到 B （不另立判据：字段名、含义、三态划分与 A 
    保持一致，唯一区别是被领的东西叫 literature 而不是 request）。
    另外注意"放弃"与"被租"的顺序：先判租约、再判 attempts。一条正被别人跑着的文献不该由我们来"放弃" —— 两个人各有各的 `mine_attempts` 计数，
    单方面判死会把别人手上的活一起毁掉。
    """

    #: 取到的文献行（已置 claimed_by / lease_until）；没取到时为 `None`。
    #: `R3-⑩` 起 `mine_attempts` 不在这里加：它只在真正调用抽取器的那一刻 +1
    #: （`run_once` 的成功提交与 `extract_failed` 两处）—— 领取不等于抽取，
    #: 否则"从未真抽"的那一档会因为排队次数用尽而被判死。
    literature: dict | None = None
    #: 定序时未处理文献的条数（不含已 processed 的）。
    pending: int = 0
    #: 因租约未过期而被跳过的条数（"别人正在做"）。
    skipped_lease_active: int = 0
    #: 因租约未过期而被跳过的条数（"我们自己上次失败留下的退避"）。
    #: 与上一格同源不同义：`claimed_by` 为空只说明持有者不是别人，不说明没人等。
    skipped_lease_backoff: int = 0
    #: 本轮当场放弃（attempts 用尽）的条数。
    gave_up: int = 0
    #: 没取到文献时的原因；取到时为 `None`。
    skipped_reason: str | None = None
    #: 领取前归一化掉的存量 `library/` 前缀行（这一趟改了哪几行；空列表 = 一行都没改）。
    #: 读数形状：`{"lit_id", "before", "after"}` —— "我改过你的盘"这件事必须可查，不是静默修。
    path_normalizations: list[dict] = field(default_factory=list)
    #: 被领到那一行的"归一化前"读数：`{"before", "after", "resolution"}`，其中
    #: `resolution` 是 `litread.ResolvedLiteraturePath`（在归一化之前解原串得到的，
    #: 所以 `path_base` 保留的是存量写法真正落在哪个基准上）。`None` = 这一行本来就规范。
    #:
    #: 为什么读数要在归一化之前取：`litread` 的 workspace 回退只对带 `library/` 前缀的串
    #: 启用 —— 归一化之后再解，`path_base=workspace` 这一档就永远读不出来了（缺陷 1 的
    #: 另一半）。归一化只改盘，不改"这一行当时按哪个基准读得到"的事实。
    legacy_path_reading: dict | None = None

    @property
    def claimed(self) -> bool:
        """是否取到了文献。不要用 `bool(self.literature)` 代替：那会在别处再造一个判据。"""
        return self.literature is not None
from ..specs.b import SPEC  # noqa: E402,F401

