"""文献检索 provider 层：统一的 ``SearchProvider`` 协议与多个数据源实现。

设计约束（见 ``DESIGN.md`` §4.1 / §5.1）：

* 本模块顶层不 import 任何兄弟模块（``schema`` / ``store`` / ``textutil`` 等），
  以便在其余模块尚未落地时也能独立导入与离线测试；确有需要时走惰性 import。
* 所有网络调用都必须带礼貌 ``User-Agent``、做最小间隔限速、对 429/5xx 指数退避重试。
* 本机 hosts 把 ``github.com`` 系域名劫持到 127.0.0.1，因此不提供任何依赖
  GitHub 的数据源；``export.arxiv.org`` 实测返回 406、``api.semanticscholar.org``
  实测 429，均不纳入实现。

线程安全：限速状态是进程级全局的。原因是"礼貌访问"针对的是上游服务，
而不是某个 provider 实例；同一进程里新建多个 provider（如 MultiProvider 内）
不应各自突破限速。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

__all__ = [
    "Candidate",
    "SearchProvider",
    "ProviderError",
    "RateLimiter",
    "HttpError",
    "reconstruct_abstract",
    "map_type_code",
    "normalize_doi",
    "dedup_key_of",
    "DEDUP_KEY_UNIDENTIFIED",
    "keyword_hit",
    "query_applicability",
    "QUERY_APPLICABILITY_STATES",
    "QUERY_NOT_APPLICABLE_CJK",
    "QUERY_EMPTY",
    "QueryApplicability",
    "TopicalityVerdict",
    "TopicalityReport",
    "OpenAlexProvider",
    "CrossrefProvider",
    "DoajProvider",
    "EuropePmcProvider",
    "FixtureProvider",
    "MultiProvider",
    "ProviderStat",
    "PROVIDER_STAT_STATUSES",
    "provider_error_kind",
    "default_user_agent",
    "DEFAULT_FIXTURE_PATH",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# 常量与默认值
# --------------------------------------------------------------------------------------

#: 默认礼貌标识。OpenAlex/Crossref 都建议带上可联系的邮箱，缺省时用 local 占位。
DEFAULT_USER_AGENT = "agentflow/0.1 (research prototype; contact: local)"

#: 默认最小请求间隔（秒）。>= 1 req/s 是对公共 API 的基本礼貌。
DEFAULT_MIN_INTERVAL = 1.0

#: 默认重试次数（不含首次尝试）。
DEFAULT_RETRIES = 3

#: 摘要截断长度。摘要只用于人工/AI 快速判断相关性，不能挤占存储与 prompt 预算。
SUMMARY_MAX_CHARS = 1200

#: 离线 fixture 候选文件的默认位置（相对本文件推算，避免依赖 cwd）。
#: 路径链：src/agentflow/providers.py -> src/agentflow -> src -> test1 -> demo/fixtures/candidates.json
DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "demo" / "fixtures" / "candidates.json"
)

#: 需要重试的 HTTP 状态码：限流与瞬时服务端故障。
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: precise 模式下判定"标题命中 topic"所需的相似度下限（见 §5.1）。
PRECISE_TITLE_SIM_THRESHOLD = 0.2

#: 英文虚词表：用于从英文标题中抽取关键词时跳过无区分度的词。
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "on", "in", "and", "or", "for", "to", "with",
        "at", "by", "from", "as", "is", "are", "be", "into", "via", "using",
        "about", "some", "its", "it", "that", "this", "these", "those", "over",
    }
)

#: 关键词辅助扫描时，单个标题对同一个关键词最多贡献的字符片段数。
_KEYWORD_TITLE_HITS_PER_KEY = 6

#: 解析端把"这一条判过没有、判成什么"写进 `Candidate.raw` 的键名。
#:
#: 为什么让解析端写、而不是让记台账的那一处重算：判据只能有一份。
#: 重算看着独立，实则是第二份口径 —— 两处的输入一旦不同（将来有人按 channel
#: 分别判、或改了某一处的入参），产物里的三档数就会与真实发生的取舍分家，
#: 而且没有任何东西会报错。取值是三态：`True` / `False` / `None`（弃权）。
_TOPICALITY_VERDICT_FIELD = "topicality_verdict"

#: "这一次检索对上游库不适用"的第三态名（`X-NEW-1` 的 D 选项）。
#:
#: 语义逐字写清（名字可以改，含义不许含糊）：题面里抽不出任何英文关键词
#: （纯中文题面是常态），于是"拿这段查询去打 OpenAlex/Crossref 这类以英文文献
#: 为主的库"这件事根本不成立 —— 不是"查了没命中"（`ok` + `count == 0`），
#: 也不是"查失败了"（`failed`），而是这一问对这条通道不适用。
#:
#: 为什么需要一个显式的取值而不是让调用方自己看查询串：
#: 改前这条路上两个读数把三种意思折成了两个 —— 查询串照样是中文原串，
#: 上游照样返回（噪音）结果，而 `last_filter_notes` 里只有一句内部记号
#: `no_ascii_keywords`。下游（含报告）读到的是 `status=ok` / `count>0`，
#: 于是"这条通道其实没接线"看起来与"检索成功"一模一样。
QUERY_NOT_APPLICABLE_CJK = "query_not_applicable_cjk"

#: 没有查询串（topic 与 description 都是空）时的第三态名。
#:
#: 与 `QUERY_NOT_APPLICABLE_CJK` 分开是因为两者的原因不同：
#: 一个是"这条通道处理不了这个语言"，一个是"这次根本没有查询"；
#: 折成同一个取值就等于让"没问"与"问了但不适用"重新变得不可分。
QUERY_EMPTY = "query_empty"

#: `QueryApplicability.state` 的受控取值。
#:
#: 与 `keyword_hit` 的返回值刻意不同轴：`keyword_hit` 的三态说的是
#: "一条候选的标题命中不命中"（`True` / `False` / `None`），这里说的是
#: "整个查询对这条通道适用不适用"。两件事折成一个词会让下一个人
#: 又把"这条通道没接线"读成"这条候选没问题"。
QUERY_APPLICABILITY_STATES = (
    "applicable_as_is",
    QUERY_NOT_APPLICABLE_CJK,
    QUERY_EMPTY,
)

#: `PROVIDER_STAT_STATUSES` 里那两个"这一问根本没发出去"的取值（`Y-1`）。
#:
#: 为什么不另立拼写：它们与 `evidence.SOURCE_STATUSES` 里新增的取值、与
#: `QueryApplicability.state` 必须是同一串字符 —— 三个出口说的是同一件事，
#: 各自抄一份拼写就是三个会漂移的口径。取值直接取上面两个常量。
_PROVIDER_STAT_REFUSAL_STATUSES = (QUERY_NOT_APPLICABLE_CJK, QUERY_EMPTY)

#: `MultiProvider.last_stats[name].status` 的受控词表（`F-6` + `Y-1`）。
#:
#: `"not_run"` 不是装饰：它让"这个方法没跑过这个源"与"跑过了但零命中"
#: （`"ok"` + `count == 0`）分得开。三态而不是两个数字，是因为
#: "没查成"与"查了没有"折成同一个值时，下游只能靠猜。
#:
#: `Y-1` 把第三态加了进来（`_PROVIDER_STAT_REFUSAL_STATUSES`）：这一问
#: 根本没发给上游，一个请求都没发出去。它既不是"查了没命中"（`ok`），
#: 也不是"上游坏了"（`failed`）。改前这两个取值在统计面上被折成 `failed`，
#: 而同一件事在 `evidence` 侧早就是第三态名（`R12-R3-3` 加进 `SOURCE_STATUSES`
#: 的那两个取值）—— 同一件事在两个出口上给出不同答案，正是 `Y-1` 登记的那条
#: 跨面不一致。前三个取值一个字都没改，`failed` 的语义也没有放宽。
PROVIDER_STAT_STATUSES = ("not_run", "ok", "failed") + _PROVIDER_STAT_REFUSAL_STATUSES


@dataclass(frozen=True)
class QueryApplicability:
    """一次调用"要不要把这段查询发给上游"的判定结果（第三态的载体）。

    ``state`` 的取值为 :data:`QUERY_APPLICABILITY_STATES` 之一，语义逐条：

    * ``applicable_as_is`` —— 题面里有英文关键词，查询原样可发（旧行为，逐字不变）；
    * ``query_not_applicable_cjk`` —— 题面抽不出任何英文关键词，**这一问不发给
      以英文文献为主的上游库**（fail-closed：宁可这一问落"未接线"，也不把
      中文原串打给英文库换回噪音）；
    * ``query_empty`` —— 根本没有查询串。

    为什么把"抽出的英文关键词"也带出来：它是判据自己用的那个读数。
    没有它，"为什么判成不适用"就只能靠再调一次 `_ascii_keywords` 去猜，
    而两次调用之间的输入一旦不同（例如中间有人改了规范化），
    判定与解释就会分家且不会报错。
    """

    state: str
    query_text: str
    ascii_keywords: tuple[str, ...] = ()
    note: str = ""

    @property
    def applicable(self) -> bool:
        """这段查询能不能原样发给上游（只有 ``applicable_as_is`` 是能）。"""
        return self.state == "applicable_as_is"

    @property
    def refusal_reason(self) -> str:
        """第三态的可读理由；适用时是空串（"没有理由"就是"不需要理由"）。"""
        if self.applicable:
            return ""
        if not self.note:
            return self.state
        return f"{self.state}：{self.note}"

    def to_dict(self) -> dict:
        """判定结果的产物形态（`state` / 查询串 / 抽到的关键词 / 理由）。"""
        return {
            "state": self.state,
            "applicable": self.applicable,
            "query_text": self.query_text,
            "ascii_keywords": list(self.ascii_keywords),
            "refusal_reason": self.refusal_reason,
        }


@dataclass(frozen=True)
class TopicalityVerdict:
    """一条候选的逐条判决（改前它算完就被丢掉了）。

    ``verdict`` 的三态与产物里的三档逐字对应：

    * ``True``  ⇒ ``judged_relevant``；
    * ``False`` ⇒ ``rejected``；
    * ``None``  ⇒ ``unjudged_no_ascii_keywords``（弃权：无法判定 ⇒ 放行）。

    为什么把 ``filter_note`` 一起带上：改前它只以计数的形式留在
    `last_filter_notes`（`{"no_ascii_keywords;not_filtered": 23}`），
    逐条的那句话在 `_precise_keep` 之后就被丢了。产物里只剩 `rejected: 0`，
    任何读者都会把它读成"精筛跑过了、没有需要剔除的"，而事实是"精筛 100% 弃权"。
    """

    title: str
    filter_note: str
    verdict: bool | None

    @property
    def bucket(self) -> str:
        """这一条落在三档里的哪一档（产物里的列名逐字取自这里）。"""
        if self.verdict is True:
            return "judged_relevant"
        if self.verdict is False:
            return "rejected"
        return "unjudged_no_ascii_keywords"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "filter_note": self.filter_note,
            "verdict": self.verdict,
            "bucket": self.bucket,
        }


@dataclass(frozen=True)
class TopicalityReport:
    """一次 `search` 的相关性判决台账（逐条 + 三档分列的数）。

    `X-NEW-1` 的 D 选项要的正是这个读数面：``judged_relevant`` /
    ``rejected`` / ``unjudged_no_ascii_keywords`` 三档分列，
    而不是"没剔除任何东西"这一个数字。``state`` 说的是这次调用整体怎么落的：

    * ``judged`` —— 逐条判决过（`precise` 模式的正常路径）；
    * ``query_not_applicable_cjk`` / ``query_empty`` —— 这一问没有发给上游
      （查询对这条通道不适用），所以条目数是 0：这里不许出现
      "0 条被剔除"，因为一条候选都还没取回来；
    * ``not_precise`` —— 这个 provider 这次不做标题精筛（非 `precise` 模式）。

    ``detail`` 里 ``verdict is None`` 的条目就是弃权。它们今天仍然放行
    （`keyword_hit` 的"宁可不过滤也不能误杀"是刻意取舍，D 选项不许改它），
    但从此可见：分母是 `total`，三档相加必须等于它，`complete` 就是这条断言。

    ``query_notes`` 是查询级的几句话（`C-4`）：这一跑有没有因为整串短语
    零召回而退到词项检索、有没有哪一路抛了异常。它与 `detail` 刻意不同轴 ——
    `detail` 说的是"每一条候选怎么判的"，这里说的是"这一问是怎么发出去的"；
    折进同一个字段就等于让"没查成 / 换了个串才查到"重新变得不可分。
    """

    provider: str
    mode: str
    state: str
    detail: tuple[TopicalityVerdict, ...] = ()
    refusal_reason: str = ""
    query_notes: tuple[str, ...] = ()

    @property
    def judged_relevant(self) -> int:
        return sum(1 for v in self.detail if v.verdict is True)

    @property
    def rejected(self) -> int:
        return sum(1 for v in self.detail if v.verdict is False)

    @property
    def unjudged_no_ascii_keywords(self) -> int:
        return sum(1 for v in self.detail if v.verdict is None)

    @property
    def total(self) -> int:
        """候选总数（三档的分母）。"""
        return len(self.detail)

    @property
    def complete(self) -> bool:
        """三档相加是否等于候选总数（"弃权"不许落在三档之外）。"""
        return self.judged_relevant + self.rejected + self.unjudged_no_ascii_keywords == self.total

    def counts(self) -> dict:
        """三档分列的数（产物里那一节的形状）。"""
        return {
            "judged_relevant": self.judged_relevant,
            "rejected": self.rejected,
            "unjudged_no_ascii_keywords": self.unjudged_no_ascii_keywords,
        }

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "state": self.state,
            "refusal_reason": self.refusal_reason,
            "counts": self.counts(),
            "total": self.total,
            "detail": [v.to_dict() for v in self.detail],
            "query_notes": list(self.query_notes),
        }


def _topic_verdicts(
    topic: str, candidates: Sequence[Candidate], *, mode: str, description: str = "",
    judged: bool = False,
) -> tuple[TopicalityVerdict, ...]:
    """把一批候选变成逐条判决（口径复用解析端算好的那一份，不另立一套）。

    为什么读 `raw` 而不是在这里重算一遍 `keyword_hit`：判据必须只有一处。
    重算看着更"独立"，实际是第二份口径 —— 解析端与这里的输入一旦不同
    （例如将来有人在 `_parse_work` 里按 channel 分别判），产物里的三档数
    就会与真实发生的取舍分家，且没有任何东西会报错。所以这里只做一件事：
    把 `_parse_work` 当时算出的判决与 `filter_note` 捞出来。

    `judged=False`（这个 provider 这个模式不做标题精筛，例如 Crossref 或
    OpenAlex 的 `topical` 模式）时，逐条的 `verdict` 一律是 `None`
    —— 它不是"弃权"，而是"这一跑没有逐条判决"；两者都落在
    `unjudged_no_ascii_keywords` 这一档里，所以 `TopicalityReport.state`
    必须一起读（`judged` / `not_precise`），单看那一档的数会认错。

    为什么 `topicality_verdict` 缺失时降级成 `None` 而不是抛：`Candidate`
    也由 fixture 或调用方手工构造，那些路径没有解析端的判决。
    降级成"未判定"是保守的（三档里它进弃权档，不会被算成"没有弃权"），
    而抛异常会让一条本来能读的台账整个消失。
    """
    out: list[TopicalityVerdict] = []
    for candidate in candidates:
        raw = candidate.raw if isinstance(candidate.raw, Mapping) else {}
        present = "topicality_verdict" in raw and mode == "precise" and judged
        verdict: bool | None = None
        if present:
            stored = raw.get("topicality_verdict")
            verdict = bool(stored) if isinstance(stored, bool) else None
        out.append(TopicalityVerdict(
            title=candidate.title,
            filter_note=_stringify(raw.get("filter_note")),
            verdict=verdict,
        ))
    return tuple(out)


def _refusal_report(provider: str, mode: str, decision: QueryApplicability) -> TopicalityReport:
    """造一份"这一问没有发给上游"的台账（第三态的产物形态）。

    为什么要有它：`search` 在拒绝之后不再有任何条目可以逐条记录，
    于是"这一问到底怎么落的"只剩异常消息里那一句话。把判定本身
    （状态 + 逐字理由 + 查询串）落成一个可读对象，调用方与测试
    就不必去解析异常字符串。
    """
    return TopicalityReport(
        provider=provider, mode=mode, state=decision.state,
        detail=(), refusal_reason=decision.refusal_reason,
    )


def _record_topicality(
    provider: str, mode: str, topic: str, candidates: Sequence[Candidate],
    *, description: str = "", judged: bool = False,
    query_notes: tuple[str, ...] = (),
) -> TopicalityReport:
    """把一批候选的逐条判决打包成台账（`search` 返回前挂到实例上）。

    `judged=True` 表示这个调用跑过标题精筛（OpenAlex 的 `precise` 模式）；
    其余情形台账的 `state` 是 `not_precise`，逐条 `verdict` 一律 `None`。

    `query_notes` 是查询级的那几句话（`C-4`：短语零召回降级 / 某一路抛异常），
    由调用方算好传进来 —— 这里只负责原样挂上去，不重算。
    """
    detail = _topic_verdicts(
        topic, candidates, mode=mode, description=description, judged=judged,
    )
    return TopicalityReport(
        provider=provider, mode=mode,
        state="judged" if judged else "not_precise", detail=detail,
        query_notes=tuple(query_notes),
    )


#: 台账 `state` 的第四个取值（`FINAL-R3-04`）：每一路都没查成 ⇒ 没有做过任何
#: 逐条判决。它与 `judged`（判过、候选可能为 0）和两个拒绝态（这一问没发出去）
#: 都不同轴，折进任何一个都会让"没查成"重新变得不可见。
TOPICALITY_STATE_CHANNEL_ERROR = "channel_error"


def _channel_error_report(
    provider: str, mode: str, channel_errors: Mapping[str, str], *, judged: bool = False,
) -> TopicalityReport:
    """每一路都抛异常时挂的台账（`FINAL-R3-04`）：`state="channel_error"` + 逐路理由。

    为什么不能沿用 `_record_topicality(judged=...)`：那样三档会写成一排 0 且
    `complete=true`，于是"一条候选都没取回来（因为每一路都失败了）"与
    "取回来了、判过、一条都没留下"在产物里同形 —— 而两者的处置完全不同
    （前者要重试/换源，后者要换检索词）。理由串进 `query_notes`。
    """
    return TopicalityReport(
        provider=provider, mode=mode,
        state=TOPICALITY_STATE_CHANNEL_ERROR,
        detail=(),
        query_notes=tuple(
            f"channel_error[{ch}]：{err}" for ch, err in sorted(channel_errors.items())
        ) + (("本条 mode 在正常路径上会做标题精筛" if judged else "本条 mode 不做标题精筛"),),
    )


def query_applicability(topic: str, description: str = "") -> QueryApplicability:
    """判定"这段查询要不要原样发给以英文文献为主的上游库"（`X-NEW-1` 的 D）。

    判据只用一处：`_ascii_keywords(查询串)`。抽不出任何英文关键词 ⇒
    `query_not_applicable_cjk`。它与 `keyword_hit` 用同一个抽取函数，
    所以"精筛弃权"与"查询不适用"这两件事由构造保证同进同退
    （`providers._ascii_keywords` 抽不到词，就是 `keyword_hit` 返回 `None` 的原因）。

    为什么判据落在查询串（而不是只看 topic）：一次调用的两条检索词里，
    只要有一条能被英文库理解，这一问就成立（例如 topic 是中文、
    description 是英文的 `precise` 调用）；把 topic 与 description 拼起来判，
    判的就是"实际发出去的东西"。

    为什么不是"topic 里有中文就拒绝"：中英混排的题面（"阿贝尔群 abelian group"）
    是可检索的，按关键词判而不是按字符集判，才不会误杀这一类。
    """
    text = " ".join(x for x in ((topic or "").strip(), (description or "").strip()) if x).strip()
    keys = _ascii_keywords(text)
    if not text:
        return QueryApplicability(
            state=QUERY_EMPTY, query_text="", ascii_keywords=(),
            note="topic 与 description 都是空的 ⇒ 没有查询串可发",
        )
    if not keys:
        shown = text[:60] + ("…" if len(text) > 60 else "")
        return QueryApplicability(
            state=QUERY_NOT_APPLICABLE_CJK, query_text=text, ascii_keywords=(),
            note=("查询串 " + shown + " 里抽不出任何英文关键词 ⇒ 这一问不发给"
                  "以英文文献为主的上游库；不是'查了没命中'，也不是'查失败了'，"
                  "而是这条通道处理不了这个查询（未接线）"),
        )
    return QueryApplicability(
        state="applicable_as_is", query_text=text, ascii_keywords=tuple(keys),
    )


def _require_applicable_query(provider: str, topic: str, description: str) -> QueryApplicability:
    """上游调用前的守卫：不适用就不发查询，并抛带第三态名的 `ProviderError`。

    为什么是异常而不是"返回空列表"：空列表在调用方（`evidence`）那里
    与"查过了、上游确实没有这条主题的文献"是同一个读数（`no_results`），
    而它照样算"查过了"⇒ 报告里照样出现"检索 ok"。拒绝必须让这一次查询
    落进"没查成"那一支 —— 那才是 fail-closed。

    抛出的消息里逐字包含 `query_not_applicable_cjk`：调用方（例如
    `evidence`）把它写进逐源 `sources_detail[].reason`，于是产物里能读出
    "这一问是未接线，不是没文献"。第三态的这些字段由 `last_topicality` 承载。
    """
    decision = query_applicability(topic, description)
    if decision.applicable:
        return decision
    raise ProviderError(f"{provider}: {decision.refusal_reason}")


class ProviderError(RuntimeError):
    """provider 层统一异常：调用方只需捕获这一种即可处理全部检索失败。"""


# --------------------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """一条候选文献。

    字段与 ``DESIGN.md`` §4.1 完全一致。全部带默认值是为了允许
    ``Candidate(title="...")`` 这种渐进式构造（单测与 fixture 解析都方便）；
    真实的 provider 一律用关键字实参构造，保持可读与可扩展。
    """

    title: str = ""
    year: int | None = None
    doi: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    type_code: str = "Z"          # GB/T 7714 码，见 §1.5
    summary: str = ""
    pdf_url: str | None = None
    landing_url: str | None = None
    language: str | None = None
    provider: str = ""
    raw: dict = field(default_factory=dict)


class SearchProvider(Protocol):
    """检索源协议。实现方只需保证 ``name`` 与 ``search`` 可用。"""

    name: str

    def search(
        self, topic: str, mode: str, description: str, limit: int
    ) -> list[Candidate]:  # pragma: no cover - 协议声明
        ...


# --------------------------------------------------------------------------------------
# 文本/归一化工具
# --------------------------------------------------------------------------------------
# 说明：DESIGN.md 把这些函数规划在 textutil.py，但本模块被要求"可独立导入"，
# 因此这里放一份最小实现。它们都是纯函数、语义与 §3.1/§3.2 一致。


def _fold_text(text: str) -> str:
    """Unicode NFC → 小写 → 全角转半角。不做分词，供关键词匹配使用。"""
    text = unicodedata.normalize("NFC", text or "").lower()
    # NFKC 会把全角字母/数字归一为半角，同时保留 CJK 汉字（它们无兼容分解）。
    return unicodedata.normalize("NFKC", text)


def _normalize_basic(text: str) -> str:
    """NFC + 小写 + NFKC + 去标点 + 折叠空白。用于标题比对与 dedup 键。"""
    folded = _fold_text(text)
    # 保留字母数字与空白（含 CJK），其余一律当标点丢弃。
    kept = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in folded)
    return re.sub(r"\s+", " ", kept).strip()


def _token_set(text: str) -> set[str]:
    """英文按词、中文按字符 bigram 切 token（对应 §3.2 的可解释做法）。"""
    t = _normalize_basic(text)
    if not t:
        return set()
    tokens = set(re.findall(r"[a-z0-9]+", t))
    cjk = "".join(ch for ch in t if not ch.isascii() and not ch.isspace())
    if len(cjk) >= 2:
        tokens.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    elif cjk:
        tokens.add(cjk)
    return tokens


def _similarity(a: str, b: str) -> float:
    """token 集合 Jaccard 相似度；两侧皆空时视为 0（不能凭空说"相同"）。"""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _ascii_keywords(text: str) -> list[str]:
    """抽取英文关键词；中文词会被自然丢弃——这正是 precise 降级策略的前提。

    中文 topic（如"阿贝尔群的基本性质"）与英文标题无法直接做字符串比较，
    抽取不到关键词时调用方必须放弃过滤，而不是把所有结果都判为不命中。
    """
    words = re.findall(r"[a-z][a-z0-9\-]{1,}", _normalize_basic(text))
    out: list[str] = []
    for w in words:
        if w in _STOPWORDS or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
    return out


def _stringify(value: Any) -> str:
    """把 OpenAlex 可返回 str/list/dict 的字段安全地压成字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        # 常见形态：{"@value": "..."} 或 {"value": "..."}
        for key in ("@value", "value", "text", "name"):
            if isinstance(value.get(key), str):
                return value[key].strip()
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(filter(None, (_stringify(v) for v in value)))
    return str(value).strip()


def _coerce_year(value: Any) -> int | None:
    """尽最大努力取出 4 位年份；取不到就返回 None（绝不猜）。"""
    if isinstance(value, dict):
        for key in ("year", "date-parts", "value", "@value", "date"):
            if key in value:
                got = _coerce_year(value[key])
                if got is not None:
                    return got
        return None
    if isinstance(value, (list, tuple)):
        return _coerce_year(value[0]) if value else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2999 else None
    if isinstance(value, str):
        m = re.search(r"(1[0-9]{3}|2[0-9]{3})", value)
        return int(m.group(1)) if m else None
    return None


def _first_url(value: Any) -> str | None:
    """从 ``[{...url...}]`` 形态里取第一个可用 URL。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            got = _first_url(item)
            if got:
                return got
    if isinstance(value, Mapping):
        for key in ("url", "URL", "pdf_url", "landing_page_url", "@id", "href"):
            got = _first_url(value.get(key))
            if got:
                return got
    return None


# --------------------------------------------------------------------------------------
# 摘要还原 / DOI / 类型码 / 关键词命中 / 去重键
# --------------------------------------------------------------------------------------


def reconstruct_abstract(inv_index: dict | None, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """把 OpenAlex 的 ``abstract_inverted_index`` 还原成正常文本。

    该结构是 ``{词: [位置...]}``。还原算法：把所有 (位置, 词) 对按位置升序排列后拼接。
    这里必须防御脏数据：OpenAlex 偶尔出现位置是非整数、或同一位置被两个词占用，
    此时排序会抛 TypeError / 丢失词元；因此逐项校验并按 (位置, 词) 二级排序保证确定性。

    还原失败（结构完全不是预期形态）时降级为压缩 JSON 片段，宁可给出原始线索，
    也不要静默返回空串让上层以为"这篇文章没有摘要"。
    """
    if not inv_index:
        return ""
    if not isinstance(inv_index, Mapping):
        return _stringify(inv_index)[:max_chars]

    pairs: list[tuple[int, str]] = []
    for word, positions in inv_index.items():
        if not isinstance(word, str):
            word = _stringify(word)
        if not word:
            continue
        if isinstance(positions, int) and not isinstance(positions, bool):
            positions = [positions]
        if not isinstance(positions, (list, tuple, set)):
            continue
        for pos in positions:
            if isinstance(pos, bool):
                continue
            if isinstance(pos, int):
                pairs.append((pos, word))
            elif isinstance(pos, str) and pos.strip().lstrip("-").isdigit():
                pairs.append((int(pos.strip()), word))

    if not pairs:
        try:
            return json.dumps(inv_index, ensure_ascii=False)[:max_chars]
        except (TypeError, ValueError):
            return ""

    pairs.sort(key=lambda p: (p[0], p[1]))
    text = re.sub(r"\s+", " ", " ".join(w for _, w in pairs)).strip()
    if len(text) > max_chars:
        # 截断处可能切断单词，回退到最后一个空白，读起来更像摘要。
        cut = text[:max_chars]
        if " " in cut[max_chars // 2 :]:
            cut = cut[: cut.rfind(" ")]
        text = cut.rstrip() + "…"
    return text


def normalize_doi(doi: str | None) -> str | None:
    """DOI 归一化 —— 转发到唯一实现 :func:`agentflow.dedup.normalize_doi`。

    本函数曾经是第二份独立实现（``INVENTORY.md`` §4.7③ 实测：``http://dx.doi.org/…``、
    尾随 ``.``、全角数字三组输入给出与 ``dedup`` 不同的结果）。

    为什么唯一实现放在 ``dedup``：DOI 是判重键的来源（§3.5 第一级）。
    ``providers.dedup_key_of`` 用它给候选的 ``dedup_key`` 赋值，而
    ``dedup.find_existing_literature`` / ``dedup._row_keys`` 用同一族键去判"是否已存在"。
    两份实现分歧 ⇒ 候选自带的键与判重检查算出的键不是同一个字符串 ⇒
    同一个 DOI 被当成两篇文献（重复登记、重复下载），且没有任何报错。

    为什么用惰性 import：``dedup`` 依赖 ``textutil``/``schema``，而本模块被要求
    可独立导入。顶层 import ``dedup`` 会把"能不能 import providers"绑到整条链条上；
    惰性 import 只在真正调用时才建立依赖，代价是一次模块查找（已在 ``sys.modules`` 里）。
    """
    from . import dedup as _D  # 惰性 import：见 docstring 末节
    return _D.normalize_doi(doi)


# OpenAlex 的 ``type`` 是受控词表；把非文章类但确实是"论文"的类型也并入 J。
_OPENALEX_TYPE_MAP: dict[str, str] = {
    "article": "J",
    "review": "J",
    "paratext": "J",
    "editorial": "J",
    "letter": "J",
    "erratum": "J",
    "libguides": "EB",
    "book": "M",
    "monograph": "M",
    "reference-book": "M",
    "book-chapter": "M",
    "book-review": "J",
    "proceedings-article": "C",
    "proceedings": "C",
    "conference-paper": "C",
    "dissertation": "D",
    "report": "R",
    "preprint": "EB",
    "posted-content": "EB",
    "standard": "S",
    "patent": "P",
    "newspaper-article": "N",
    "dataset": "Z",
    "other": "Z",
    "peer-review": "Z",
    "retraction": "Z",
    "grant": "Z",
    "software": "Z",
}

_CROSSREF_TYPE_MAP: dict[str, str] = {
    "journal-article": "J",
    "journal-issue": "J",
    "journal-volume": "J",
    "journal": "J",
    "article": "J",
    "book": "M",
    "book-chapter": "M",
    "book-section": "M",
    "book-part": "M",
    "monograph": "M",
    "edited-book": "M",
    "reference-book": "M",
    "proceedings-article": "C",
    "proceedings": "C",
    "proceedings-series": "C",
    "posted-content": "EB",
    "preprint": "EB",
    "dissertation": "D",
    "report": "R",
    "report-series": "R",
    "standard": "S",
    "standard-series": "S",
    "peer-review": "Z",
    "dataset": "Z",
    "component": "Z",
    "other": "Z",
}

#: provider 专用映射表 + 兜底码。DOAJ 只有期刊文章，EuropePMC 的类型词表差异较大。
_PROVIDER_TYPE_MAPS: dict[str, tuple[dict[str, str], str]] = {
    "openalex": (_OPENALEX_TYPE_MAP, "Z"),
    "crossref": (_CROSSREF_TYPE_MAP, "Z"),
    "doaj": ({}, "J"),
    "europepmc": ({}, "J"),
}


def map_type_code(provider: str, raw_type: str | None) -> str:
    """把各 provider 的原始类型映射为 GB/T 7714 类型码（DESIGN.md §1.5）。

    未识别的类型一律落到该 provider 的兜底码（OpenAlex/Crossref 为 ``Z``，
    DOAJ/EuropePMC 为 ``J``）。不做模糊猜测：把一篇报告猜成期刊论文
    会污染后续的引用格式与类型统计，不如显式落到"其他"。
    """
    key = (provider or "").strip().lower()
    raw = (raw_type or "").strip().lower()
    if not raw:
        return _PROVIDER_TYPE_MAPS.get(key, ({}, "Z"))[1]

    if key == "europepmc":
        # EuropePMC 的 pubType 是自由文本列表，需要按子串识别而非全等。
        return _europepmc_type(raw)

    table, fallback = _PROVIDER_TYPE_MAPS.get(key, (_OPENALEX_TYPE_MAP, "Z"))
    if raw in table:
        return table[raw]

    # 交叉兜底：Crossref 的 "journal-article" 之类可能在 OpenAlex 词表里出现，反之亦然。
    for other, _fb in _PROVIDER_TYPE_MAPS.values():
        if raw in other:
            return other[raw]
    return fallback


def _europepmc_type(raw: str) -> str:
    """EuropePMC ``pubType`` 判定：按优先级子串匹配，默认 ``J``。"""
    text = raw.lower()
    rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (("preprint", "pre-print"), "EB"),
        (("dissertation", "thesis"), "D"),
        (("patent",), "P"),
        (("standard",), "S"),
        (("newspaper",), "N"),
        (("technical report", "report"), "R"),
        (("book", "chapter", "monograph"), "M"),
        (("congress", "conference", "proceedings", "meeting abstract", "symposium"), "C"),
    )
    for needles, code in rules:
        if any(n in text for n in needles):
            return code
    return "J"


def keyword_hit(topic: str, title: str) -> bool | None:
    """判断英文标题是否命中 topic 的关键词。

    返回值是三态，这是本函数的关键设计：

    * ``True``  —— 至少一个 topic 英文关键词出现在标题中；
    * ``False`` —— 能判定且全部关键词都没出现（可据此过滤）；
    * ``None``  —— 无法判定，调用方必须放行。

    ``None`` 出现在两种情形：topic 里抽不出英文关键词（中文 topic 的常态），
    或关键词辅助扫描在标题里根本没找到（说明标题不是英文，字符串比较无意义）。
    宁可不过滤也不能误杀——漏掉一篇好文献比多留几篇噪音代价更大。
    """
    keys = _ascii_keywords(topic)
    if not keys:
        return None
    title_ascii_words = set(re.findall(r"[a-z][a-z0-9\-]{1,}", _normalize_basic(title)))
    if not title_ascii_words:
        return None
    if any(k in title_ascii_words for k in keys):
        return True
    return False


#: "这个候选的行内键无法判定"的显式取值（`F-8`）。
#:
#: 它不是键，也不参与合并：调用方见到它必须走"不能判重"那一支，
#: 而不是拿它去查 `index`。为什么需要一个显式取值而不是 `None`：
#: `None` 在这条链上还表示"这个函数没返回值"，两种意思混在一个哨兵里，
#: 下一个人就会写出 `if not key: skip` 把"无法判定"与"没有键"折叠成同一件事。
DEDUP_KEY_UNIDENTIFIED = "unidentified"


def _merge_identity_key(candidate: Candidate) -> str | None:
    """跨源合并用的键；`None` = 无法判定（`F-8`）。

    为什么键函数返回一个"不是键的哨兵"、而这里再折成 `None`：
    `dedup_key_of` 是公开函数，它的返回值必须能被打印与比对（哨兵串可读）；
    而调用点要的是"有没有键"这个二值判断。两件事分开写，
    比让 `dedup_key_of` 返回 `None` 再由每个调用方各自解释要好 ——
    后者会让"无法判定"在每一处重新被解释一遍（本项目最忌的形态）。
    """
    key = dedup_key_of(candidate)
    return None if key == DEDUP_KEY_UNIDENTIFIED else key


def dedup_key_of(candidate: Candidate) -> str:
    """候选在同一次搜索内的跨源合并键 —— 委托给 `dedup` 的键族。

    ## 契约（`F-8` 之后）

    * DOI 在场时返回 `doi:<归一化 DOI>`；
    * 否则返回 `dedup.literature_keys(...)` 里的标题键 ——
      有年份是 `title:<norm>|<year>`，没年份是 `title:<norm>|*`；
    * 两者都没有（既无 DOI、标题又规范化成空串）时返回
      :data:`DEDUP_KEY_UNIDENTIFIED`，这是一个显式的"无法判定"。

    ## 改前是什么，为什么必须改（2026-09-26 全面体检 · 子代理 F 实测）

    改前这是一条自己一套的键（`F-8`）：

    - 无年份时给 `title:<norm>|na`；而 `dedup.literature_keys` 给 `title:<norm>|*`。
      两者不是同一个字符串，于是"同一次搜索里一个源带年份、另一个不带"
      （跨库的常态）合并失败，而事后跨库判重又会把它们合上 ——
      两个判重口径互相矛盾，且没有任何报错；
    - 标题为空时给 `unknown:{abs(hash(title)):x}`。`hash()` 对 `str` 是
      每进程随机加盐的（实测两个新进程给出 `fe05bf94c9fe44e` 与
      `564d0c0c94914967`）—— 一个"每个进程一个新值"的键不是键，
      只是把"无法判定"伪装成了一个稳定标识。

    现在标题键直接取 `literature_keys` 的产物，所以
    `dedup_key_of(c) in literature_keys(c.title, c.year, c.doi)` 这条交叉断言
    在任何输入上都成立（它是本条目的验收判据）。
    """
    from . import dedup as _D  # 惰性 import：理由同本模块 normalize_doi 的说明

    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"
    keys = _D.literature_keys(candidate.title, candidate.year, None)
    if not keys:
        return DEDUP_KEY_UNIDENTIFIED
    # `literature_keys` 的标题键是 `title:<norm>|<year>` 与 `title:<norm>|*`，
    # 年份在场的那个排在前面 —— 取第一个即可（没有 DOI 时它必是标题键）。
    return keys[0]


# --------------------------------------------------------------------------------------
# HTTP：限速 + 重试
# --------------------------------------------------------------------------------------


class HttpError(ProviderError):
    """HTTP 层失败，携带状态码以便上层区分"限流"与"没这条记录"。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RateLimiter:
    """按 bucket（通常是主机名）串行化的最小间隔限速器。

    ``acquire`` 在同一把锁内完成"睡眠 + 记录时间戳"，因此多线程并发时
    请求会被真正排队，不会出现两个线程同时看到"距上次已过 1 秒"而一起发出。
    """

    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def acquire(self, bucket: str) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(bucket)
            if last is not None:
                wait = self.min_interval - (now - last)
                if wait > 0:
                    time.sleep(wait)
                    now = time.monotonic()
            self._last[bucket] = now


#: 全局限速器：礼貌访问针对上游服务，而非某个实例，故不放实例属性。
_RATE_LIMITER = RateLimiter()


def default_user_agent(mailto: str | None = None) -> str:
    """构造礼貌 User-Agent；有邮箱时带上（OpenAlex/Crossref 的 polite pool 要求）。"""
    if mailto:
        return f"agentflow/0.1 (research prototype; mailto:{mailto})"
    return DEFAULT_USER_AGENT


def _retry_after_seconds(headers: Any) -> float | None:
    """解析 ``Retry-After``；上游让我们等多久就等多久（上限截断防挂死）。"""
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:  # pragma: no cover - headers 形态由 urllib 保证
        return None
    if not raw:
        return None
    try:
        return min(float(str(raw).strip()), 60.0)
    except ValueError:
        return None


def http_get_json(
    url: str,
    params: Mapping[str, Any] | None = None,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 30.0,
    retries: int = DEFAULT_RETRIES,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    limiter: RateLimiter | None = None,
    headers: Mapping[str, str] | None = None,
    accept: str = "application/json",
) -> Any:
    """GET 一个 JSON 接口，带限速与指数退避重试。

    重试条件：网络异常，或状态码属于 ``RETRYABLE_STATUS``（429/5xx 等）。
    4xx（除 408/425/429）不重试——那是请求本身有问题，重试只会浪费配额。
    """
    if params:
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, doseq=True
        )
        sep = "&" if urllib.parse.urlparse(url).query else "?"
        full = f"{url}{sep}{query}" if query else url
    else:
        full = url

    bucket = urllib.parse.urlparse(full).netloc or "unknown"
    limiter = limiter or _RATE_LIMITER
    request_headers = {
        "User-Agent": user_agent,
        "Accept": accept,
        "Accept-Language": "en,zh-CN;q=0.8",
    }
    if headers:
        request_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        limiter.acquire(bucket)
        request = urllib.request.Request(full, headers=request_headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                body = response.read().decode("utf-8", errors="replace")
            if status is None or status >= 400:
                raise HttpError(f"unexpected status {status}", status)
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            last_error = HttpError(f"HTTP {status} for {full}", status)
            if status not in RETRYABLE_STATUS or attempt >= retries:
                raise last_error from exc
            delay = _retry_after_seconds(getattr(exc, "headers", None))
            if delay is None:
                delay = min(2.0**attempt, 20.0) * (0.8 + 0.4 * random.random())
            logger.warning("检索受限/失败（HTTP %s），%.1fs 后重试第 %d 次", status, delay, attempt + 1)
            time.sleep(delay)
        except urllib.error.URLError as exc:
            last_error = HttpError(f"network error for {full}: {exc.reason}", None)
            if attempt >= retries:
                raise last_error from exc
            delay = min(2.0**attempt, 20.0) * (0.8 + 0.4 * random.random())
            logger.warning("网络异常（%s），%.1fs 后重试第 %d 次", exc.reason, delay, attempt + 1)
            time.sleep(delay)
        except (TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = HttpError(f"bad response for {full}: {exc}", None)
            # JSON 解析失败通常不是瞬时故障 —— 更可能是被限流页/网关错误页顶替了
            # 正常响应，再重试同一路径大概率还是拿到 HTML 而不是 JSON。所以给
            # 一次重试机会（应对偶发的截断），之后立刻放弃以省配额。
            if attempt >= retries or (isinstance(exc, json.JSONDecodeError) and attempt >= 1):
                raise last_error from exc
            delay = min(2.0**attempt, 20.0) * (0.8 + 0.4 * random.random())
            time.sleep(delay)

    raise last_error or HttpError(f"failed to fetch {full}", None)


# --------------------------------------------------------------------------------------
# OpenAlex（主力 provider）
# --------------------------------------------------------------------------------------


def _openalex_pdf_url(work: Mapping[str, Any]) -> tuple[str | None, str]:
    """按"可获取性"从高到低挑 PDF 链接，并返回来源说明（便于事后审计）。

    ## `R-51`（`draft/28` §154）：`pdf_url` 与落地页**逐字相同**时要标出来

    OpenAlex 有时把**落地页/仓库页/handle 解析器**填进 `pdf_url`
    （实测：`hdl.handle.net/1773/25218`、`ul.qucosa.de/id/qucosa%3A11139`
    这两条的 `best_oa_location.pdf_url` 与 `landing_page_url` 逐字相同）。
    那种 URL 下回来的是 HTML，"下载成功"会被读成"拿到全文"。

    这里**不改** `pdf_url` 的取值（字节仍然值得当证据留下，`fetch`/`agent_a`
    会把它标成 `content_mismatch`），只在来源串上打一个 `|landing_same_as_pdf` 标记 ——
    于是事后审计能在候选记录里一眼看出"这条根本没有直链"。
    """
    landing = _openalex_landing_url(work) or ""

    def mark(url: str, source: str, loc: Any = None) -> tuple[str, str]:
        """`pdf_url` 与落地页逐字相同 ⇒ 在来源串上打标记（R-51）。

        要比**两处**落地页：work 级 `_openalex_landing_url`（优先 DOI）与该 location
        自己的 `landing_page_url`。只比前者会漏掉实测那两条（它们的 work 级落地页是
        DOI，而 location 级落地页与 `pdf_url` 逐字相同）。
        """
        loc_landing = _stringify((loc or {}).get("landing_page_url")) if isinstance(loc, Mapping) else ""
        if url and ((landing and url == landing) or (loc_landing and url == loc_landing)):
            return url, f"{source}|landing_same_as_pdf"
        return url, source

    best = work.get("best_oa_location") or {}
    if isinstance(best, Mapping):
        url = _stringify(best.get("pdf_url"))
        if url:
            return mark(url, "best_oa_location", best)
    primary = work.get("primary_location") or {}
    if isinstance(primary, Mapping):
        url = _stringify(primary.get("pdf_url"))
        if url:
            return mark(url, "primary_location", primary)
    locations = work.get("locations") or []
    if isinstance(locations, (list, tuple)):
        for loc in locations:
            if isinstance(loc, Mapping):
                url = _stringify(loc.get("pdf_url"))
                if url:
                    return mark(url, "locations", loc)
    oa = work.get("open_access") or {}
    if isinstance(oa, Mapping):
        url = _stringify(oa.get("oa_url"))
        if url:
            return mark(url, "open_access.oa_url", oa)
    return None, ""


def _openalex_landing_url(work: Mapping[str, Any]) -> str | None:
    """落地页优先用 DOI，其次 primary_location，最后 OpenAlex 自身页面。"""
    doi = normalize_doi(_stringify(work.get("doi")))
    if doi:
        return f"https://doi.org/{doi}"
    primary = work.get("primary_location") or {}
    if isinstance(primary, Mapping):
        url = _stringify(primary.get("landing_page_url"))
        if url:
            return url
    return _stringify(work.get("id")) or None


class OpenAlexProvider:
    """OpenAlex 检索源。返回 ``type``/被引数/年份/DOI/摘要倒排索引/语言等元数据。

    ``mailto`` 的取值顺序：构造参数 → 环境变量 ``ABFLOW_OPENALEX_MAILTO`` → 省略。
    进入 polite pool 能显著降低被限流的概率，但不能因此硬编码一个假邮箱。
    """

    name = "openalex"
    BASE_URL = "https://api.openalex.org/works"

    #: OpenAlex 建议显式声明 select 以减少响应体积；缺字段时解析端全部做了兜底。
    SELECT_FIELDS = (
        "id,doi,title,display_name,type,type_crossref,publication_year,publication_date,"
        "language,authorships,primary_location,best_oa_location,locations,open_access,"
        "cited_by_count,referenced_works_count,abstract_inverted_index,ids"
    )

    DEFAULT_PER_PAGE = 50
    MAX_PER_PAGE = 200

    def __init__(
        self,
        *,
        mailto: str | None = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        timeout: float = 30.0,
        per_page: int = DEFAULT_PER_PAGE,
        max_pages: int = 1,
        user_agent: str | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        env_mailto = os.environ.get("ABFLOW_OPENALEX_MAILTO", "").strip()
        self.mailto = (mailto or env_mailto) or None
        self.min_interval = max(0.0, float(min_interval))
        self.retries = max(0, int(retries))
        self.timeout = float(timeout)
        self.per_page = max(1, min(int(per_page), self.MAX_PER_PAGE))
        self.max_pages = max(1, int(max_pages))
        self.user_agent = user_agent or default_user_agent(self.mailto)
        self._limiter = limiter or _RATE_LIMITER
        #: 累积"请求次数 / 解析失败次数 / 被标题过滤掉条数"，自检与排障可直接打印。
        #: `phrase_fallbacks` 与 `channel_errors` 是 `C-4` 的两个计数：前者是
        #: "整串短语零召回、退了词项形态重抓"的条数，后者是"这一路抛了异常"的路数。
        self.stats: dict[str, int] = {
            "requests": 0,
            "items": 0,
            "parse_errors": 0,
            "filtered_out": 0,
            "phrase_fallbacks": 0,
            # `FINAL-R3-01`：因为"这一跑里同一条短语已经零召回"而省掉的那次主查询计数。
            # 它把"实际发出的请求数"与"路数 × 2"的差额解释清楚（topical 两路共享同一条短语）。
            "phrase_fallbacks_deduped": 0,
            "channel_errors": 0,
        }
        #: 上一次 search 实际发出的检索串（按 channel）与过滤原因计数，供诊断用。
        self.last_query_text: dict[str, str] = {}
        self.last_filter_notes: dict[str, int] = {}
        self.last_filtered_out: int = 0
        #: 上一次 search 里"短语零召回 ⇒ 退词项形态重抓"的逐路记录（`C-4a`）。
        #: 空 dict 与"降级过但两条都空"是两件事：后者有一条 `{channel: {..., count: 0}}`。
        self.last_phrase_fallbacks: dict[str, dict] = {}
        #: 上一次 search 里抛了异常的那些路（`C-4b`）：`{channel: 异常原文}`。
        #: 为什么必须留：改前单路异常被吞成零候选，逐源状态于是写成 `no_results`
        #: （"查过了、没有可用条目"）—— 把上游 429 读成"这个主题没有文献"。
        self.last_channel_errors: dict[str, str] = {}
        #: 上一次 search 的查询去向：每一条是"发出去了"还是"拒绝了"（`X-NEW-1`）。
        #:
        #: 为什么必须留这个：拒绝的那一跑一个条目都没有，于是
        #: `last_filter_notes` 是空的、`last_query_text` 也是空的 ——
        #: "我没发这一问"与"这个方法根本没被调用"在旧字段上完全同形。
        self.last_query_provenance: list[dict] = []
        #: 上一次 search 的相关性判决台账（逐条 + 三档分列的数）。
        self.last_topicality: TopicalityReport | None = None

    # -- 对外接口 -----------------------------------------------------------------

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """按 §5.1 的模式策略检索。

        ``limit`` 是最终返回条数上限（0 表示用该模式的默认值）；单条查询的
        抓取量由 ``_plan`` 决定，因此 topical 的"奠基 + 前沿"两路各取各的配额，
        不会互相挤占。

        ## fail-closed（`X-NEW-1` 的 D 选项）

        题面里抽不出任何英文关键词时（纯中文题面的常态），**不拿中文原串去打
        这个以英文文献为主的库**：抛 `ProviderError`，落第三态
        `query_not_applicable_cjk`。理由与"为什么是异常"逐字见
        `_require_applicable_query`。中英混排的题面照旧发出去。
        """
        topic = (topic or "").strip()
        description = (description or "").strip()
        mode = (mode or "topical").strip().lower()
        # 拒绝路径必须留下"我没问"的痕迹，所以先把这几个字段一起清空：
        # 上一跑的读数留在里面会让"这一跑什么都没发"看起来像"发了旧那几条"。
        # 为什么不止清 provenance：`tools/search_tools._provider_diagnostics` 读的是
        # `last_query_text` / `last_filter_notes` / `last_filtered_out`，而
        # `tools/search_tools._resolve_provider` 把实例缓存在 `ctx.providers` 里
        # （同一个 provider 对象会被反复读）—— 只清 provenance 会让同一个对象上
        # 出现两个互相矛盾的读数：`dispatched: false`（这一跑一个请求都没发）
        # 配着上一跑的检索串与过滤计数。复位放在下面那个提前 return 之前，
        # 所以"空 topic+description"那条分支走的是同一条复位（`R12-R3-1`）。
        self.last_query_provenance = []
        self.last_query_text = {}
        self.last_filter_notes = {}
        self.last_filtered_out = 0
        self.last_phrase_fallbacks = {}
        self.last_channel_errors = {}
        #: 这一跑里已经确认"短语零召回"的检索串（`FINAL-R3-01`）：topical 的两条路
        #: 主查询串完全相同 ⇒ 第二条路不再重发一次注定零召回的主查询。
        self._zero_recall_phrases = set()
        if not topic and not description:
            self.last_topicality = _refusal_report(
                self.name, mode, query_applicability(topic, description)
            )
            return []
        decision = self._require_applicable_query(topic, description, mode)
        self.last_query_provenance.append({
            "provider": self.name, "mode": mode, "query_text": decision.query_text,
            "state": decision.state, "dispatched": True, "reason": "",
        })

        plans = _plan_mode(mode, topic, description, limit)
        total_limit = _default_limit(mode) if limit and limit > 0 else sum(p.limit for p in plans)

        out: list[Candidate] = []
        seen: dict[str, Candidate] = {}
        filter_notes: dict[str, int] = {}
        judged: list[Candidate] = []
        filtered_out = 0
        channel_errors: dict[str, str] = {}
        for plan in plans:
            try:
                works, plan = self._fetch_with_fallback(plan)
            except ProviderError as exc:
                # 单路失败不应让整个请求失败：另一路（如"前沿"）仍可能产出有效结果。
                # 但"这一路失败了"本身必须留下读数（见循环后面那道全路失败的判据）：
                # 改前它只留一句 warning，产物上表现为 `no_results`。
                channel_errors[plan.channel] = str(exc)
                logger.warning("OpenAlex 查询路失败（sort=%s）：%s", plan.sort or "relevance", exc)
                continue
            self.last_query_text[plan.channel] = _stringify(plan.template.get("search"))
            for work in works:
                candidate = self._parse_work(work, plan, mode, topic, description)
                if candidate is None:
                    continue
                # 逐条判决先记下来再决定去留：被筛掉的那一条也是判过的一条，
                # 改前它连同它的 `filter_note` 一起消失，于是"弃权"与"筛掉了"
                # 在产物里都只剩下一个 0。
                judged.append(candidate)
                if candidate.raw.get("filtered_out"):
                    continue
                note = _stringify(candidate.raw.get("filter_note")) or "no_note"
                filter_notes[note] = filter_notes.get(note, 0) + 1
                key = _merge_identity_key(candidate)
                if key is not None and key in seen:
                    continue
                if key is not None:
                    seen[key] = candidate
                out.append(candidate)

        # 记录本轮过滤统计：precise 召回归零时必须能一眼看出是"查询本身没结果"
        # 还是"结果被标题过滤筛干净"，否则只能靠猜（配合 self.last_query_text 与
        # self.stats['filtered_out'] / stats['parse_errors'] 一起看）。
        self.last_filter_notes = filter_notes
        self.last_filtered_out = int(self.stats.get("filtered_out", 0))
        self.last_channel_errors = channel_errors
        if channel_errors:
            self.stats["channel_errors"] = self.stats.get("channel_errors", 0) + len(channel_errors)
        self.last_topicality = _record_topicality(
            self.name, mode, topic, judged, description=description,
            judged=(mode == "precise"), query_notes=self._query_notes(channel_errors),
        )
        if channel_errors and not out and len(channel_errors) == len(plans):
            # 每一路都抛了、一条都没回来 ⇒ 这是"没查成"，不是"查了没有"。
            # 折平这两件事是本模块反复踩的那类坑：调用方只能看到一个 0 候选，
            # 于是 429/网络错被读成"上游没有这个主题的文献"（`C-4b`）。
            # `FINAL-R3-04`：台账的 `state` 也必须改口 —— 改前它跟正常路径一样是
            # `judged`（配三档全 0 + `complete=true`），于是"一条候选都没有（因为没查成）"
            # 与"查过 0 条候选"在产物上同形。现在落一个显式的 `channel_error` 档；
            # 它不在 `_PROVIDER_STAT_REFUSAL_STATUSES` 里，所以下游 `_provider_refusal`
            # 不会把"没查成"误判成"这一问根本没发出去"（那是另一件事）。
            self.last_topicality = _channel_error_report(
                self.name, mode, channel_errors, judged=judged,
            )
            raise ProviderError(
                "OpenAlex 每一路都失败（"
                + "；".join(f"{ch}: {err}" for ch, err in sorted(channel_errors.items()))
                + "）⇒ 这一次没有查成（不是「没有结果」）"
            )

        if mode == "broad":
            out.sort(key=_broad_sort_key)
        return out[:total_limit] if total_limit > 0 else out

    def _query_notes(self, channel_errors: Mapping[str, str]) -> tuple[str, ...]:
        """把这一跑的两件查询事实收成台账上的几句话（`C-4`）。

        为什么要进台账而不是只留 `logger.warning`：`sources_detail` 是逐源
        状态的落点，而"这条通道查了没有"与"这条通道没查成 / 换了个串才查到"
        都必须在产物里读得到 —— 只留在日志里等于没有读数。
        """
        notes: list[str] = []
        for channel, record in sorted(self.last_phrase_fallbacks.items()):
            got = record.get("count")
            notes.append(
                f"phrase_zero_recall_fallback[{channel}]：整串短语零召回 ⇒ 改词项检索"
                f"（{got} 条）"
            )
        for channel, err in sorted(channel_errors.items()):
            notes.append(f"channel_error[{channel}]：{err}")
        return tuple(notes)

    def _require_applicable_query(self, topic: str, description: str, mode: str) -> QueryApplicability:
        """这个 provider 的守卫入口；拒绝时先把去向记进 `last_query_provenance`。

        为什么记在抛之前：异常一旦抛出去，调用方只会看到一句消息；
        而这一跑"拒绝了哪一条查询、为什么"必须能从 provider 对象上读到
        （否则排查时只能靠猜调用方有没有处理那句消息）。
        """
        try:
            return _require_applicable_query(self.name, topic, description)
        except ProviderError as exc:
            self.last_query_provenance.append({
                "provider": self.name, "mode": mode,
                "query_text": f"{topic} {description}".strip(),
                "state": QUERY_NOT_APPLICABLE_CJK, "dispatched": False,
                "reason": str(exc),
            })
            self.last_topicality = _refusal_report(
                self.name, mode, query_applicability(topic, description)
            )
            raise

    # -- 内部实现 -----------------------------------------------------------------

    def _fetch_with_fallback(self, plan: _QueryPlan) -> tuple[list[dict], _QueryPlan]:
        """抓一路；主查询零召回且这条路有词项形态时，用词项形态再抓一次（`C-4a`）。

        ## 为什么必须有这个降级

        `_phrase_query` 把整段 ASCII 题面包进一对引号，而 OpenAlex 的引号是
        字面短语匹配。实测同一条题面：加引号
        `"spectral sequence of a filtered complex and its convergence"` 的
        `meta.count` 是 0，去掉引号是 92549（`temp/_oa_probe.py`，2026-09-28）。
        生产检索路径（`evidence._default_sources`）恰好传
        `mode="precise", description=""`，于是整条链上召回恒为 0：材料为空
        （`T3` 的 `tokens_in` 恒 272）⇒ 模型如实回答"材料里没有可据以陈述的
        实质结论"⇒ O6 回验率 0/120。函数自己的 docstring 早就写了"只适用于
        短的 topic"，但没有实现这个前提。

        ## 口径（为什么不是"按词数阈值决定加不加引号"）

        阈值是凭空的魔数；"短语零召回就退词项"自适应、无常数，且顺带覆盖
        其它零召回原因（例如短题面恰好没有这条字面短语）。短语命中非零时
        行为逐字不变 —— 短题面（实测 "abelian group"）的精度收益不受影响。

        两次请求都留在读数里：`last_phrase_fallbacks[channel]` 记下原短语、
        词项串与词项串的条数，所以"发出去过哪两条"不会被读成"只发了那一条"。
        返回的 `plan` 是最后发出的那一条（`FINAL-R3-03` 的措辞更正）：
        `last_query_text` 的语义逐字是"实际发出的检索串"，而"两次都 0 条"这一支上
        它记的是降级串（那是最后发出去的那一条），条数在
        `last_phrase_fallbacks[channel]["count"]` 里 —— 想读"这一路到底拿回来几条"
        就一起读那个数，不要只看检索串。

        ## 同一次调用里不重复发同一条零召回的短语（`FINAL-R3-01`）

        `topical` 有两条路（奠基 / 前沿），两条路的主查询串完全相同（只差 `sort`）。
        改前它们各自先发一次短语、再各自降级 ⇒ 一条题面 2 次变 4 次请求，
        而这个翻倍恰好发生在限流场景附近（零召回的常见成因就是上游给空载荷/限流）。
        现在把"这一跑里已经确认零召回的短语串"记在 `_zero_recall_phrases` 里：
        第二条路直接用词项形态开局（`last_phrase_fallbacks` 里仍然记着这条路降过级），
        于是请求数从 4 降到 3。
        """
        primary = _stringify(plan.template.get("search"))
        alt = _stringify(plan.fallback)
        if primary and primary in self._zero_recall_phrases and alt and alt != primary:
            # 这一跑已经证明这条短语零召回 ⇒ 不再为第二条路重发它。
            fallback_plan = _QueryPlan(
                channel=plan.channel,
                template={**plan.template, "search": alt},
                limit=plan.limit,
                sort=plan.sort,
            )
            works = self._fetch_works(fallback_plan.template, fallback_plan.limit,
                                      sort=fallback_plan.sort)
            self.stats["phrase_fallbacks"] = self.stats.get("phrase_fallbacks", 0) + 1
            self.stats["phrase_fallbacks_deduped"] = self.stats.get("phrase_fallbacks_deduped", 0) + 1
            self.last_phrase_fallbacks[plan.channel] = {
                "phrase": primary, "terms": alt, "count": len(works),
                "deduped": True,
            }
            return works, fallback_plan

        works = self._fetch_works(plan.template, plan.limit, sort=plan.sort)
        if works or not alt or alt == primary:
            return works, plan
        if primary:
            self._zero_recall_phrases.add(primary)

        fallback_plan = _QueryPlan(
            channel=plan.channel,
            template={**plan.template, "search": alt},
            limit=plan.limit,
            sort=plan.sort,
        )
        works = self._fetch_works(fallback_plan.template, fallback_plan.limit,
                                  sort=fallback_plan.sort)
        self.stats["phrase_fallbacks"] = self.stats.get("phrase_fallbacks", 0) + 1
        self.last_phrase_fallbacks[plan.channel] = {
            "phrase": primary, "terms": alt, "count": len(works),
        }
        return works, fallback_plan

    def _fetch_works(
        self, template: Mapping[str, Any], want: int, *, sort: str | None
    ) -> list[dict]:
        """按分页抓取，最多 ``max_pages`` 页；返回原始 ``results`` 列表。"""
        remaining = max(1, int(want))
        per_page = max(1, min(self.per_page, self.MAX_PER_PAGE, remaining))
        collected: list[dict] = []

        for page in range(1, self.max_pages + 1):
            params: dict[str, Any] = dict(template)
            params["per-page"] = per_page
            params["page"] = page
            if sort:
                params["sort"] = sort
            params["select"] = self.SELECT_FIELDS
            if self.mailto:
                params["mailto"] = self.mailto

            payload = http_get_json(
                self.BASE_URL,
                params,
                user_agent=self.user_agent,
                timeout=self.timeout,
                retries=self.retries,
                min_interval=self.min_interval,
                limiter=self._limiter,
            )
            self.stats["requests"] += 1
            if not isinstance(payload, Mapping):
                logger.warning("OpenAlex 返回非对象载荷：%s", type(payload).__name__)
                break
            results = payload.get("results") or []
            if not isinstance(results, list):
                break
            for item in results:
                if isinstance(item, Mapping):
                    collected.append(dict(item))
            self.stats["items"] = self.stats.get("items", 0) + len(results)

            remaining = max(0, int(want) - len(collected))
            if remaining <= 0 or len(results) < per_page:
                break
            per_page = max(1, min(self.per_page, self.MAX_PER_PAGE, remaining))

        return collected

    def _parse_work(
        self,
        work: Mapping[str, Any],
        plan: "_QueryPlan",
        mode: str,
        topic: str,
        description: str,
    ) -> Candidate | None:
        """把 OpenAlex work 对象转成 ``Candidate``；结构性缺失则返回 None。

        ## 为什么被精筛剔除的条目也要返回（`X-NEW-1`）

        改前这里 `return candidate if keep else None`：被剔除的那一条连同它的
        `filter_note` 一起消失，调用方只能看到一个"少了几篇"的结果。
        于是"筛掉了 N 条"与"精筛压根没跑"在产物上长得一样。

        现在被剔除的条目照样返回，但 `raw["filtered_out"]` 置位 ——
        `search` 用它做两件事：① 逐条判决记账（三档里它是 `rejected` 档）；
        ② 把它挡在返回值之外（对外行为逐字不变：`search` 仍然不返回它）。
        唯一的调用方是 `OpenAlexProvider.search`，它按位判这个标记，
        所以"有没有提前 return"在外部读数上不可分辨。
        """
        title = _stringify(work.get("title")) or _stringify(work.get("display_name"))
        if not title:
            # 没有标题的条目无法进入文献表（title 是必填），直接从候选中剔除。
            self.stats["parse_errors"] = self.stats.get("parse_errors", 0) + 1
            return None

        raw_type = (_stringify(work.get("type")) or _stringify(work.get("type_crossref"))).lower()
        pdf_url, pdf_source = _openalex_pdf_url(work)
        authors = _openalex_authors(work)
        venue = _openalex_venue(work)
        summary = reconstruct_abstract(
            work.get("abstract_inverted_index") if isinstance(work.get("abstract_inverted_index"), dict) else None
        )
        language = _stringify(work.get("language")) or None

        filter_note = ""
        keep = True
        #: 这一条的判决三态（`True` / `False` / `None` = 弃权），与 `keep` 不是
        #: 同一个东西：`_precise_keep` 在"无法判定"时返回 `keep=True` 而判决是 `None`。
        #: 折成 `keep` 就会把"弃权"读成"判过且切题"，于是那一档永远是 0 —— 正是
        #: `X-NEW-1` 要修的那个形状（"没查成"被读成"查过了没问题"）。
        verdict: bool | None = None
        if mode == "precise":
            verdict = keyword_hit(topic, title)
            keep, filter_note = _precise_keep(topic, title, description)

        oa = work.get("open_access") if isinstance(work.get("open_access"), Mapping) else {}
        raw: dict[str, Any] = {
            "filter_note": filter_note,
            # 逐条判决在这里就落进 `raw`：改前它算完即丢，于是"精筛弃权"
            # 与"精筛没跑"在产物里都是同一个 0（`X-NEW-1` 要修的形态）。
            _TOPICALITY_VERDICT_FIELD: verdict,
            "channel": plan.channel,
            "sort": plan.sort or "relevance",
            "search": plan.template.get("search"),
            "filter": plan.template.get("filter"),
            "type": raw_type,
            "cited_by_count": work.get("cited_by_count"),
            "referenced_works_count": work.get("referenced_works_count"),
            "is_oa": (oa or {}).get("is_oa") if isinstance(oa, Mapping) else None,
            "pdf_url_source": pdf_source,
            "openalex_id": _stringify(work.get("id")) or None,
            # 保留原始条目：标题比对、复现查询与将来补字段都需要它。
            "openalex": dict(work),
        }
        if not keep:
            # 过滤掉的条目也要留痕，否则"为什么少了几篇"无法排查。
            raw["filtered_out"] = True
            self.stats["filtered_out"] = self.stats.get("filtered_out", 0) + 1
            logger.debug("precise 过滤掉：%s（%s）", title[:60], filter_note)

        return Candidate(
            title=title,
            year=_coerce_year(work.get("publication_year")),
            doi=normalize_doi(_stringify(work.get("doi"))),
            authors=authors,
            venue=venue,
            type_code=map_type_code("openalex", raw_type),
            summary=summary,
            pdf_url=pdf_url,
            landing_url=_openalex_landing_url(work),
            language=language,
            provider=self.name,
            raw=raw,
        )


@dataclass(frozen=True)
class _QueryPlan:
    """一条具体的检索路（OpenAlex 一次查询 = 一条路）。"""

    channel: str                       # foundational | frontier | review | popular | precise
    template: dict                     # search / filter 参数模板
    limit: int                         # 该路期望条数
    sort: str | None = None            # OpenAlex sort 表达式；None 表示按相关性
    #: 同一条路的"词项形态"检索串；空串 = 这条路没有降级形态（`C-4a`）。
    #: 整串短语在长题面上会零召回（字面匹配），主查询空手而归时由
    #: `OpenAlexProvider._fetch_with_fallback` 拿它再抓一次。
    fallback: str = ""


def _phrase_query(text: str) -> str:
    """把检索词收成"短语优先"的查询串。

    裸词检索会被 OpenAlex 的 OR 式相关性打分拉开：实测 ``search=abelian group``
    的按被引降序结果里混进了石墨烯、希格斯玻色子等无关高被引论文。给 ASCII
    词加上引号做短语匹配能显著提高 topic 的约束力；中文词加引号无益（分析器
    不同），故只对 ASCII 词生效。

    只适用于短的 topic：OpenAlex 的引号是字面短语匹配，实测
    ``"definition of abelian group and its relation to group"`` 命中数为 0
    （没有任何文章的连续文本包含这一整串），因此长 description 绝不能用本函数。

    ## 这个前提由谁兑现（`C-4a`）

    本函数不自己判断长短 —— 它只负责"短语优先"这一件事；长题面的召回兜底
    由调用方给的那条降级串承担：`_plan_mode` 在 `topical`/`precise` 两路上同时
    给出词项形态（`_term_query`），`OpenAlexProvider._fetch_with_fallback`
    在主查询零召回时用它再抓一次。实测（2026-09-28）这道兜底是必需的：
    生产检索路径传 ``description=""``，整条链上唯一的查询串就是这里的整串短语。
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if cleaned.isascii():
        return f'"{cleaned}"'
    tokens = cleaned.split(" ")
    shaped = [f'"{t}"' if t.isascii() and len(t) > 1 else t for t in tokens]
    return " ".join(shaped)


def _term_query(text: str) -> str:
    """把长文本收成"词项 + 去停用词"的查询串（不加引号）。

    用于 precise 的 description：它是自然语言描述而非检索短语，加引号会让
    OpenAlex 按字面短语匹配从而召回归零（见 ``_phrase_query`` 的实测）。
    去掉 ``of/the/and`` 这类虚词能提高词项的区分度，也避免它们主导相关性打分。
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if not cleaned.isascii():
        # 中文描述无法做英文停用词过滤，原样保留（OpenAlex 对中文亦有基础支持）。
        return cleaned
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", cleaned)
    kept = [t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 1]
    return " ".join(kept) if kept else " ".join(tokens)


def _default_limit(mode: str) -> int:
    """§5.1 的默认 limit。"""
    return {"broad": 20, "topical": 15, "precise": 10}.get(mode, 15)


def _plan_mode(mode: str, topic: str, description: str, limit: int) -> list[_QueryPlan]:
    """把模式落成可执行的查询路集合（§5.1）。

    ``topic`` 为空但 ``description`` 非空时（precise 的边界情形）自动降级为
    只用 description 检索，避免构造出 ``search=""`` 这种无意义查询。
    """
    if mode == "broad":
        review_terms = " OR ".join(
            ['"survey"', '"review"', '"introduction"', '"textbook"', '"overview"']
        )
        base_limit = limit if limit > 0 else _default_limit("broad")
        review_limit = max(5, base_limit // 2)
        popular_limit = max(5, base_limit - review_limit)
        return [
            _QueryPlan(
                channel="review",
                template={"search": f"{topic} {review_terms}".strip()},
                limit=review_limit,
                sort=None,
            ),
            _QueryPlan(
                channel="popular",
                template={"search": topic},
                limit=popular_limit,
                sort="cited_by_count:desc",
            ),
        ]

    if mode == "precise":
        precise_limit = limit if limit > 0 else _default_limit("precise")
        # description 是主检索词、topic 是约束（§5.1）：
        # - description 走词项检索（自然语言，不能加引号，否则召回为 0）；
        # - topic 走短语检索（短检索词，加引号才收得紧）。
        # 两者之间用 OR：否则"描述里的词 + topic 短语"必须同时出现在同一篇里，
        # 实测会把召回压到 0；topic 约束改由标题关键词过滤承担（见 _precise_keep）。
        parts = [p for p in (_term_query(description), _phrase_query(topic) or topic) if p]
        search = " OR ".join(parts)
        # 降级串（`C-4a`）：同一批检索词的全词项形态。短语那一段是字面匹配，
        # 长题面上它单独命中 0 条是常态（实测见 `_fetch_with_fallback`），
        # 主查询空手而归时用它再抓一次。
        fallback_parts = [p for p in (_term_query(description), _term_query(topic) or topic) if p]
        return [
            _QueryPlan(
                channel="precise",
                template={"search": search},
                limit=precise_limit,
                sort=None,
                fallback=" OR ".join(fallback_parts),
            )
        ]

    # topical（默认）：奠基（被引降序）+ 前沿（年份降序）
    topical_limit = limit if limit > 0 else _default_limit("topical")
    phrase = _phrase_query(topic) or topic
    # 同上：整串短语是字面匹配，长题面（"spectral sequence of a filtered complex
    # and its convergence" 这类）会零召回，词项形态是这条路的降级串（`C-4a`）。
    terms = _term_query(topic) or topic
    return [
        _QueryPlan(
            channel="foundational",
            template={"search": phrase},
            limit=topical_limit,
            sort="cited_by_count:desc",
            fallback=terms,
        ),
        _QueryPlan(
            channel="frontier",
            template={"search": phrase},
            limit=topical_limit,
            sort="publication_year:desc",
            fallback=terms,
        ),
    ]


def _precise_keep(topic: str, title: str, description: str) -> tuple[bool, str]:
    """precise 模式的标题命中判定，返回 ``(是否保留, filter_note)``。

    降级链（§5.1 要求"keyword 全命中"，但中文 topic 无法与英文标题比字符串）：

    1. topic 抽不出英文关键词 → 无法判定 → 不过滤，记 ``no_ascii_keywords``；
    2. 关键词有部分/全部命中 → 保留，记命中情况；
    3. 关键词一个都没命中且标题是英文（能抽出英文词）→ 剔除，记 ``keyword_miss``；
    4. 关键词一个都没命中但标题抽不出英文词（疑似非英文标题）→ 无法判定 → 不过滤；
    5. 若上述都不成立但 ``similarity(topic, title) >= 0.2``（§5.1 的并列条件）→ 保留。
    """
    hit = keyword_hit(topic, title)
    if hit is None:
        sim = _similarity(topic, title)
        if sim >= PRECISE_TITLE_SIM_THRESHOLD:
            return True, f"no_ascii_keywords;similarity={sim:.2f}>=0.2"
        return True, "no_ascii_keywords;not_filtered"
    if hit:
        return True, "keyword_hit"

    title_words = re.findall(r"[a-z][a-z0-9\-]{1,}", _normalize_basic(title))
    if not title_words:
        return True, "keyword_miss_but_title_not_ascii;not_filtered"
    sim = _similarity(topic, title)
    if sim >= PRECISE_TITLE_SIM_THRESHOLD:
        return True, f"keyword_miss;similarity={sim:.2f}>=0.2"
    note = f"keyword_miss;similarity={sim:.2f}"
    if description:
        # description 命中是更强的相关性信号；这里只记录，过滤仍以 topic 为准（§5.1）。
        note += ";description_used_as_primary_query"
    return False, note


def _broad_sort_key(candidate: Candidate) -> tuple[int, int, str]:
    """broad 模式类型偏好：``M``/``J``（综述/教材）优先，``EB`` 次之，其余最后。

    同档内按被引数降序，让高影响力的综述先进入下载队列。
    """
    code = candidate.type_code
    preference = 0 if code in ("M", "J") else (1 if code == "EB" else 2)
    cited = candidate.raw.get("cited_by_count")
    cited_num = -int(cited) if isinstance(cited, int) else 0
    return (preference, cited_num, candidate.title)


def _openalex_authors(work: Mapping[str, Any]) -> list[str]:
    """取作者显示名，保持 OpenAlex 给出的署名顺序（顺序本身是信息）。"""
    authorships = work.get("authorships") or []
    out: list[str] = []
    if isinstance(authorships, (list, tuple)):
        for entry in authorships:
            if not isinstance(entry, Mapping):
                continue
            author = entry.get("author")
            name = _stringify(author.get("display_name")) if isinstance(author, Mapping) else ""
            name = name or _stringify(entry.get("raw_author_name"))
            if name and name not in out:
                out.append(name)
    return out


def _openalex_venue(work: Mapping[str, Any]) -> str | None:
    """venue 取 primary_location.source 的 display_name，退回 host_organization_name。"""
    primary = work.get("primary_location") or {}
    if isinstance(primary, Mapping):
        source = primary.get("source")
        if isinstance(source, Mapping):
            name = _stringify(source.get("display_name"))
            if name:
                return name
        host = _stringify(primary.get("host_organization_name"))
        if host:
            return host
    best = work.get("best_oa_location") or {}
    if isinstance(best, Mapping):
        source = best.get("source")
        if isinstance(source, Mapping):
            name = _stringify(source.get("display_name"))
            if name:
                return name
    return None


# --------------------------------------------------------------------------------------
# Crossref（补 page / container-title 等元数据）
# --------------------------------------------------------------------------------------


class CrossrefProvider:
    """Crossref 检索源。

    主力价值不在检索而在元数据补齐（页码范围、container-title、issued），
    因此这里把 ``page`` 原始字符串与 ``type`` 一起放进 ``raw`` 供上层使用。
    """

    name = "crossref"
    BASE_URL = "https://api.crossref.org/works"

    #: Crossref 的 ``select`` 白名单字段。警告：Crossref 对 select 里的任一
    #: 非法字段名返回整请求 400（不是忽略该字段），一次误写会让三种模式全部 400。
    #: 逐个实测（``?select=<字段>`` 单字段探测）后确认：``language`` 属于
    #: "合法字段但不可 select"（返回 ``select-not-available``），因此必须排除；
    #: ``abstract`` 反而是可 select 的。任何新增字段上线前都必须这样实测一遍。
    #: 代价是 Crossref 侧 ``language`` 恒为 None——这是有意的取舍，胜过整个 provider 400。
    SELECT_FIELDS = (
        "DOI,title,author,type,container-title,issued,page,"
        "URL,link,is-referenced-by-count,publisher,volume,issue"
    )

    def __init__(
        self,
        *,
        mailto: str | None = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        timeout: float = 30.0,
        rows: int = 50,
        user_agent: str | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        env_mailto = os.environ.get("ABFLOW_CROSSREF_MAILTO", "").strip()
        self.mailto = (mailto or env_mailto) or None
        self.min_interval = max(0.0, float(min_interval))
        self.retries = max(0, int(retries))
        self.timeout = float(timeout)
        self.rows = max(1, min(int(rows), 1000))
        self.user_agent = user_agent or default_user_agent(self.mailto)
        self._limiter = limiter or _RATE_LIMITER
        #: 查询去向（发出去 / 被拒绝）与相关性台账；语义同 `OpenAlexProvider` 的两处。
        self.last_query_provenance: list[dict] = []
        self.last_topicality: TopicalityReport | None = None

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """按相关度检索。Crossref 无"按被引排序"，因此三种模式共用同一查询构造。

        fail-closed（`X-NEW-1` 的 D 选项）与 `OpenAlexProvider.search` 同一口径：
        查询串里抽不出英文关键词（纯中文题面）时不发这一问，抛
        `ProviderError` 落第三态 `query_not_applicable_cjk`。
        """
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        self.last_query_provenance = []
        # 去停用词后送检索：Crossref 的 bibliographic 查询同样被 of/the/and 稀释。
        query = " ".join(x for x in (_term_query(description), _term_query(topic)) if x).strip()
        decision = query_applicability(topic, description)
        if not decision.applicable:
            self.last_query_provenance.append({
                "provider": self.name, "mode": mode, "query_text": decision.query_text,
                "state": decision.state, "dispatched": False,
                "reason": f"{self.name}: {decision.refusal_reason}",
            })
            self.last_topicality = _refusal_report(self.name, mode, decision)
            raise ProviderError(f"{self.name}: {decision.refusal_reason}")
        self.last_query_provenance.append({
            "provider": self.name, "mode": mode, "query_text": decision.query_text,
            "state": decision.state, "dispatched": True, "reason": "",
        })
        if not query:
            return []

        params: dict[str, Any] = {
            "query.bibliographic": query,
            "rows": max(1, min(self.rows, want)),
            "select": self.SELECT_FIELDS,
        }
        if self.mailto:
            params["mailto"] = self.mailto

        payload = http_get_json(
            self.BASE_URL,
            params,
            user_agent=self.user_agent,
            timeout=self.timeout,
            retries=self.retries,
            min_interval=self.min_interval,
            limiter=self._limiter,
        )
        items = []
        if isinstance(payload, Mapping):
            message = payload.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("items"), list):
                items = [i for i in message["items"] if isinstance(i, Mapping)]

        out: list[Candidate] = []
        for item in items[:want]:
            candidate = self._parse_item(item)
            if candidate is not None:
                out.append(candidate)
        # Crossref 不做标题精筛（`_precise_keep` 只在 OpenAlex 的解析路径上跑），
        # 所以这里如实登记"这次没有逐条判决"，而不是伪造一个"全判过"的读数。
        self.last_topicality = _record_topicality(
            self.name, mode, topic, out, description=description,
        )
        return out

    def _parse_item(self, item: Mapping[str, Any]) -> Candidate | None:
        title = _stringify(item.get("title"))
        if not title:
            return None
        raw_type = _stringify(item.get("type")).lower()
        authors = _crossref_authors(item)
        issued = item.get("issued")
        year = _coerce_year(issued.get("date-parts") if isinstance(issued, Mapping) else issued)
        page = _stringify(item.get("page")) or None
        container = _stringify(item.get("container-title")) or None
        doi = normalize_doi(_stringify(item.get("DOI")))
        pdf_url = _crossref_pdf_url(item)

        raw: dict[str, Any] = {
            "filter_note": "",
            "channel": "relevance",
            "type": raw_type,
            "container_title": container,
            "page": page,
            "volume": _stringify(item.get("volume")) or None,
            "issue": _stringify(item.get("issue")) or None,
            "publisher": _stringify(item.get("publisher")) or None,
            "is_referenced_by_count": item.get("is-referenced-by-count"),
            "crossref": dict(item),
        }
        return Candidate(
            title=title,
            year=year,
            doi=doi,
            authors=authors,
            venue=container,
            type_code=map_type_code("crossref", raw_type),
            summary=reconstruct_abstract(_strip_markup(_stringify(item.get("abstract")))),
            pdf_url=pdf_url,
            landing_url=f"https://doi.org/{doi}" if doi else (_stringify(item.get("URL")) or None),
            language=_stringify(item.get("language")) or None,
            provider=self.name,
            raw=raw,
        )


def _crossref_authors(item: Mapping[str, Any]) -> list[str]:
    """Crossref 作者是 {given, family} 结构；拼接失败时退回 ``name`` 字段。"""
    out: list[str] = []
    authors = item.get("author") or []
    if isinstance(authors, (list, tuple)):
        for entry in authors:
            if not isinstance(entry, Mapping):
                continue
            name = _stringify(entry.get("name"))
            if not name:
                given = _stringify(entry.get("given"))
                family = _stringify(entry.get("family"))
                name = " ".join(x for x in (given, family) if x).strip()
            if name and name not in out:
                out.append(name)
    return out


def _crossref_pdf_url(item: Mapping[str, Any]) -> str | None:
    """优先 ``link`` 中 content-type 为 PDF 的条目；Crossref 链接常需订阅，仅作线索。"""
    links = item.get("link") or []
    if isinstance(links, (list, tuple)):
        for link in links:
            if isinstance(link, Mapping) and "pdf" in _stringify(link.get("content-type")).lower():
                url = _stringify(link.get("URL"))
                if url:
                    return url
    return None


def _strip_markup(text: str) -> str:
    """Crossref 的 abstract 常带 JATS 标签（``<jats:p>`` 等），去掉后才是可读文本。"""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text)


# --------------------------------------------------------------------------------------
# DOAJ / Europe PMC（可用但非主力）
# --------------------------------------------------------------------------------------


class DoajProvider:
    """DOAJ 检索源：只覆盖开放获取期刊文章，因此类型固定为 ``J``。"""

    name = "doaj"
    BASE_URL = "https://doaj.org/api/search/articles/"

    def __init__(
        self,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        timeout: float = 30.0,
        page_size: int = 50,
        user_agent: str | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.retries = max(0, int(retries))
        self.timeout = float(timeout)
        self.page_size = max(1, min(int(page_size), 100))
        self.user_agent = user_agent or default_user_agent()
        self._limiter = limiter or _RATE_LIMITER
        #: 查询去向与相关性台账；语义同 `OpenAlexProvider` 的两处。
        self.last_query_provenance: list[dict] = []
        self.last_topicality: TopicalityReport | None = None

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """DOAJ 检索（只有期刊文章）。

        fail-closed（`X-NEW-1` 的 D 选项）与 `OpenAlexProvider.search` 同一口径：
        查询串里抽不出英文关键词时不发这一问，抛 `ProviderError` 落第三态
        `query_not_applicable_cjk`。
        """
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        terms = " ".join(x for x in (description, topic) if x).strip()
        self.last_query_provenance = []
        decision = query_applicability(topic, description)
        if not decision.applicable:
            self.last_query_provenance.append({
                "provider": self.name, "mode": mode, "query_text": decision.query_text,
                "state": decision.state, "dispatched": False,
                "reason": f"{self.name}: {decision.refusal_reason}",
            })
            self.last_topicality = _refusal_report(self.name, mode, decision)
            raise ProviderError(f"{self.name}: {decision.refusal_reason}")
        self.last_query_provenance.append({
            "provider": self.name, "mode": mode, "query_text": decision.query_text,
            "state": decision.state, "dispatched": True, "reason": "",
        })
        if not terms:
            return []

        # DOAJ 的查询语法是 Elasticsearch 风格，裸词必须加引号，否则含空格/中文会报错。
        query = urllib.parse.quote(f'bibjson.title:("{terms}") OR bibjson.abstract:("{terms}")')
        url = f"{self.BASE_URL}{query}"
        payload = http_get_json(
            url,
            {"pageSize": min(self.page_size, want), "page": 1},
            user_agent=self.user_agent,
            timeout=self.timeout,
            retries=self.retries,
            min_interval=self.min_interval,
            limiter=self._limiter,
        )

        results = payload.get("results") if isinstance(payload, Mapping) else None
        out: list[Candidate] = []
        if isinstance(results, list):
            for entry in results[:want]:
                if not isinstance(entry, Mapping):
                    continue
                candidate = self._parse_entry(entry)
                if candidate is not None:
                    out.append(candidate)
        # DOAJ 不做标题精筛 ⇒ 如实登记"这次没有逐条判决"。
        self.last_topicality = _record_topicality(
            self.name, mode, topic, out, description=description,
        )
        return out

    def _parse_entry(self, entry: Mapping[str, Any]) -> Candidate | None:
        bib = entry.get("bibjson")
        if not isinstance(bib, Mapping):
            return None
        title = _stringify(bib.get("title"))
        if not title:
            return None
        year = _coerce_year(bib.get("year"))
        journal = bib.get("journal") if isinstance(bib.get("journal"), Mapping) else {}
        venue = _stringify((journal or {}).get("title")) or None

        authors: list[str] = []
        for author in bib.get("author") or []:
            if isinstance(author, Mapping):
                name = _stringify(author.get("name"))
                if name and name not in authors:
                    authors.append(name)

        doi: str | None = None
        for ident in bib.get("identifier") or []:
            if isinstance(ident, Mapping) and _stringify(ident.get("type")).lower() == "doi":
                doi = normalize_doi(_stringify(ident.get("id")))
                break

        links = bib.get("link") or []
        pdf_url: str | None = None
        landing: str | None = None
        for link in links:
            if not isinstance(link, Mapping):
                continue
            url = _stringify(link.get("url"))
            if not url:
                continue
            if "pdf" in _stringify(link.get("type")).lower() and not pdf_url:
                pdf_url = url
            if not landing:
                landing = url
        if not landing and doi:
            landing = f"https://doi.org/{doi}"

        raw: dict[str, Any] = {
            "filter_note": "",
            "channel": "doaj",
            "type": "journal-article",
            "journal": venue,
            "doaj": dict(entry),
        }
        return Candidate(
            title=title,
            year=year,
            doi=doi,
            authors=authors,
            venue=venue,
            type_code=map_type_code("doaj", "journal-article"),
            summary=reconstruct_abstract(_stringify(bib.get("abstract"))),
            pdf_url=pdf_url,
            landing_url=landing,
            language=_stringify(bib.get("language")) or None,
            provider=self.name,
            raw=raw,
        )


class EuropePmcProvider:
    """Europe PMC 检索源：生命科学领域覆盖好，其余领域仅作补充。"""

    name = "europepmc"
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(
        self,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        timeout: float = 30.0,
        page_size: int = 25,
        user_agent: str | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.retries = max(0, int(retries))
        self.timeout = float(timeout)
        self.page_size = max(1, min(int(page_size), 1000))
        self.user_agent = user_agent or default_user_agent()
        self._limiter = limiter or _RATE_LIMITER
        #: 查询去向与相关性台账；语义同 `OpenAlexProvider` 的两处。
        self.last_query_provenance: list[dict] = []
        self.last_topicality: TopicalityReport | None = None

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """Europe PMC 检索（生命科学覆盖好，其余领域仅作补充）。

        fail-closed（`X-NEW-1` 的 D 选项）与 `OpenAlexProvider.search` 同一口径：
        查询串里抽不出英文关键词时不发这一问，抛 `ProviderError` 落第三态
        `query_not_applicable_cjk`。
        """
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        terms = " ".join(x for x in (description, topic) if x).strip()
        self.last_query_provenance = []
        decision = query_applicability(topic, description)
        if not decision.applicable:
            self.last_query_provenance.append({
                "provider": self.name, "mode": mode, "query_text": decision.query_text,
                "state": decision.state, "dispatched": False,
                "reason": f"{self.name}: {decision.refusal_reason}",
            })
            self.last_topicality = _refusal_report(self.name, mode, decision)
            raise ProviderError(f"{self.name}: {decision.refusal_reason}")
        self.last_query_provenance.append({
            "provider": self.name, "mode": mode, "query_text": decision.query_text,
            "state": decision.state, "dispatched": True, "reason": "",
        })
        if not terms:
            return []

        params = {
            "query": terms,
            "format": "json",
            "pageSize": min(self.page_size, want),
            "resultType": "core",   # core 才带 abstractText / journalInfo / fullTextUrlList
        }
        payload = http_get_json(
            self.BASE_URL,
            params,
            user_agent=self.user_agent,
            timeout=self.timeout,
            retries=self.retries,
            min_interval=self.min_interval,
            limiter=self._limiter,
        )
        result_list = payload.get("resultList") if isinstance(payload, Mapping) else None
        results = (result_list or {}).get("result") if isinstance(result_list, Mapping) else None

        out: list[Candidate] = []
        if isinstance(results, list):
            for entry in results[:want]:
                if not isinstance(entry, Mapping):
                    continue
                candidate = self._parse_entry(entry)
                if candidate is not None:
                    out.append(candidate)
        # Europe PMC 不做标题精筛 ⇒ 如实登记"这次没有逐条判决"。
        self.last_topicality = _record_topicality(
            self.name, mode, topic, out, description=description,
        )
        return out

    def _parse_entry(self, entry: Mapping[str, Any]) -> Candidate | None:
        title = _stringify(entry.get("title"))
        if not title:
            return None
        pub_type = _stringify(entry.get("pubTypeList", {}).get("pubType") if isinstance(entry.get("pubTypeList"), Mapping) else entry.get("pubType"))
        year = _coerce_year(entry.get("pubYear"))
        journal = entry.get("journalInfo") if isinstance(entry.get("journalInfo"), Mapping) else {}
        journal = journal or {}
        venue = _stringify((journal.get("journal") or {}).get("title")) if isinstance(journal.get("journal"), Mapping) else ""
        venue = venue or _stringify(entry.get("journalTitle")) or None

        authors = _stringify(entry.get("authorString")).rstrip(".").split(",") if _stringify(entry.get("authorString")) else []
        authors = [a.strip() for a in authors if a.strip()]

        doi = normalize_doi(_stringify(entry.get("doi")))
        pdf_url, landing = _europepmc_urls(entry, doi)

        raw: dict[str, Any] = {
            "filter_note": "",
            "channel": "europepmc",
            "type": pub_type.lower(),
            "pmid": _stringify(entry.get("pmid")) or None,
            "pmcid": _stringify(entry.get("pmcid")) or None,
            "is_open_access": _stringify(entry.get("isOpenAccess")) or None,
            "europepmc": dict(entry),
        }
        return Candidate(
            title=title,
            year=year,
            doi=doi,
            authors=authors,
            venue=venue,
            type_code=map_type_code("europepmc", pub_type),
            summary=reconstruct_abstract(_strip_markup(_stringify(entry.get("abstractText")))),
            pdf_url=pdf_url,
            landing_url=landing,
            language=_stringify(entry.get("language")) or None,
            provider=self.name,
            raw=raw,
        )


def _europepmc_urls(entry: Mapping[str, Any], doi: str | None) -> tuple[str | None, str | None]:
    """从 ``fullTextUrlList`` 找 PDF 与落地页；Europe PMC 的 OA 文件路径可推导。"""
    pdf_url: str | None = None
    landing: str | None = None
    url_list = entry.get("fullTextUrlList")
    urls = url_list.get("fullTextUrl") if isinstance(url_list, Mapping) else None
    if isinstance(urls, list):
        for item in urls:
            if not isinstance(item, Mapping):
                continue
            url = _stringify(item.get("url"))
            if not url:
                continue
            doc_style = _stringify(item.get("documentStyle")).lower()
            site = _stringify(item.get("site")).lower()
            if not landing:
                landing = url
            if doc_style == "pdf" and (site == "pmc" or "pdf" in url.lower()):
                pdf_url = pdf_url or url
    if not pdf_url:
        pmcid = _stringify(entry.get("pmcid"))
        if pmcid:
            pdf_url = f"https://europepmc.org/api/fulltextRepo?pprId={pmcid}&type=FILE&fileName={pmcid}.pdf"
    if not landing and doi:
        landing = f"https://doi.org/{doi}"
    return pdf_url, landing


# --------------------------------------------------------------------------------------
# 离线 fixture provider
# --------------------------------------------------------------------------------------


class FixtureProvider:
    """离线确定性 provider：从 JSON 文件读候选，供离线端到端测试使用。

    设计取舍：不把缺失的 fixture 当作错误抛出。离线演示/CI 可能先跑
    fixture 之外的路径，一个缺失的素材文件不应该让整条流水线崩掉；因此这里
    只记 warning 并返回空列表，让上层按"本次无结果"处理（§2.4 的幂等语义）。
    """

    name = "fixture"

    def __init__(
        self,
        path: str | os.PathLike | None = None,
        *,
        name: str = "fixture",
        strict: bool = False,
    ) -> None:
        self.name = name
        self.path = Path(path) if path is not None else DEFAULT_FIXTURE_PATH
        self.strict = strict
        self._cache: list[dict] | None = None

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """按 topic 子串做确定性过滤（不联网、无随机、无时间依赖）。

        英文 topic 用规范化后的子串；中文 topic 与英文标题无法直接比，
        故中文 topic 视为"命中全部"（与 precise 的降级策略一致）。
        """
        records = self._load()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        folded_topic = _fold_text(topic).strip()
        is_ascii_topic = bool(re.fullmatch(r"[\x00-\x7f]+", folded_topic))

        out: list[Candidate] = []
        for record in records:
            if is_ascii_topic and folded_topic:
                blob = _fold_text(f"{record.get('title', '')} {record.get('summary', '')}")
                if folded_topic not in blob:
                    continue
            candidate = self._to_candidate(record, mode)
            if candidate is not None:
                out.append(candidate)
            if len(out) >= want:
                break
        return out

    def _load(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            logger.warning("fixture 文件不存在，返回空候选：%s", self.path)
            self._cache = []
            return self._cache
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("fixture 文件无法解析（%s）：%s", exc, self.path)
            self._cache = []
            return self._cache

        if isinstance(payload, Mapping):
            rows = payload.get("candidates") or payload.get("rows") or []
        else:
            rows = payload
        records = [dict(r) for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []
        self._cache = records
        return records

    def _to_candidate(self, record: Mapping[str, Any], mode: str) -> Candidate | None:
        title = _stringify(record.get("title"))
        if not title:
            return None
        raw = record.get("raw") if isinstance(record.get("raw"), Mapping) else {}
        raw = dict(raw)
        raw["filter_note"] = _stringify(raw.get("filter_note")) or "fixture"
        raw["channel"] = "fixture"
        raw["fixture_mode"] = mode
        raw["fixture"] = dict(record)
        pdf_url = _stringify(record.get("pdf_url")) or None
        if pdf_url and "path" in record:
            # 允许 fixture 用相对路径指向 demo 素材，便于完全离线地跑通"下载"这一步。
            raw["fixture_local_path"] = _stringify(record.get("path"))
        return Candidate(
            title=title,
            year=_coerce_year(record.get("year")),
            doi=normalize_doi(_stringify(record.get("doi"))) or None,
            authors=[str(a) for a in record.get("authors") or [] if str(a).strip()],
            venue=_stringify(record.get("venue")) or None,
            type_code=_stringify(record.get("type_code")) or map_type_code("openalex", _stringify(record.get("type"))),
            summary=_stringify(record.get("summary")),
            pdf_url=pdf_url,
            landing_url=_stringify(record.get("landing_url")) or None,
            language=_stringify(record.get("language")) or None,
            provider=_stringify(record.get("provider")) or self.name,
            raw=raw,
        )


# --------------------------------------------------------------------------------------
# 多源合并
# --------------------------------------------------------------------------------------


class ProviderStat:
    """一个源这一次检索的读数（`F-6` 的三态 + `Y-1` 的第三态）。

    取值一律是 :data:`PROVIDER_STAT_STATUSES` 之一，语义逐条：

    * `"ok"` —— 检索跑成了，`count` 可能是 0（真没命中）；
    * `"failed"` —— 检索抛了异常，`count` 一定是 0，`error_kind` 非空；
    * `"not_run"` —— 这个方法没跑过它；
    * `query_not_applicable_cjk` / `query_empty` —— 这一问根本没发给上游
      （`Y-1` 的第三态：一个请求都没发出去，`count` 一定是 0，`error` 带着理由，
      `error_kind` 是空串 —— 拒绝不属于"限流/被墙/解析失败/网络失败"那条轴）。

    为什么第三态落在 `status` 而不是另开一个字段：同一件事在 `evidence` 侧
    已经落在 `sources_detail[*].status` 上（`R12-R3-3` 把这两个取值加进了
    `SOURCE_STATUSES`）。统计面另开一个字段，等于让"这一问没发出去"在两个
    出口上各有各的读法 —— 而 `Y-1` 要修的正是这条跨面不一致。

    为什么 `failed` 一个字都不改：`failed` 说的是"上游坏了"。第三态不是它的
    子集，也不是它的同义词。要问"这个源到底交没交货"的读者用 `delivered` /
    `refused` 两个属性（或直接看 `status`），不要用 `failed` 当一个含括的
    "没结果"判据 —— 那会把第三态静默漏掉。

    为什么要有 `status`：改前失败与"零命中"都写进 `last_stats[name] = 0`，
    两者同值，唯一的分开手段是 `on_error` 回调 —— 而全仓没有任何调用点
    提供过它。也就是说"某源被墙/限流"会以"该源没命中"的形式静默进入统计。
    """

    __slots__ = ("status", "count", "error_kind", "error")

    def __init__(self, status: str = "not_run", count: int = 0,
                 error_kind: str = "", error: str = "") -> None:
        if status not in PROVIDER_STAT_STATUSES:
            raise ValueError(
                f"provider 状态必须是 {PROVIDER_STAT_STATUSES} 之一，收到 {status!r} —— "
                "把'没跑'与'跑成了但零命中'折成同一个值正是 F-6 要修的缺陷"
            )
        if status == "failed" and not error_kind:
            raise ValueError("失败的源必须给出 error_kind：只说'失败'答不出'为什么'")
        if status == "failed" and count:
            raise ValueError("失败的源不能同时报出条数（失败 ⇒ 没有结果）")
        if status in _PROVIDER_STAT_REFUSAL_STATUSES:
            if count:
                raise ValueError(
                    f"{status} 不能同时报出条数：这一问根本没发出去 ⇒ 没有结果"
                )
            if not error:
                raise ValueError(
                    f"{status} 必须给出理由：'没发出去'与'发出去零命中'只能靠理由分开"
                )
        self.status = status
        self.count = int(count)
        self.error_kind = error_kind
        self.error = error

    @property
    def failed(self) -> bool:
        """上游坏了（`"failed"`）。第三态不在这里：它由 `refused` 回答。"""
        return self.status == "failed"

    @property
    def refused(self) -> bool:
        """这一问根本没发给上游（`Y-1` 的第三态：不适用 / 没有查询串）。"""
        return self.status in _PROVIDER_STAT_REFUSAL_STATUSES

    @property
    def delivered(self) -> bool:
        """上游真的被问过并正常返回（`"ok"`；`count` 可能是 0）。"""
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "count": self.count,
            "error_kind": self.error_kind,
            "error": self.error,
        }

    def __repr__(self) -> str:  # pragma: no cover - 排障用
        return f"ProviderStat({self.to_dict()!r})"


def provider_error_kind(exc: BaseException) -> str:
    """把 provider 的异常归一到一个受控的原因档（`F-6`）。

    `HTTPError` 按状态码分档（429 = 限流、401/403 = 鉴权、404 = 越权/找不到），
    其余按异常类型分档。归一的意义就是条目的判据说的那件事：
    "按『限流/被墙/解析失败/网络失败』这条轴答得出来"。
    """
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "code", None)
    if isinstance(status, int) and status > 0:
        if status == 429 or status == 503:
            return "rate_limited"
        if status in (401, 403):
            return "auth_failed"
        if status == 404:
            return "not_found"
        if status >= 500:
            return "server_error"
        return f"http_{status}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "network_error"
    if isinstance(exc, json.JSONDecodeError):
        return "parse_failed"
    if isinstance(exc, UnicodeDecodeError):
        return "decode_failed"
    return "unknown"


def _refusal_state_of_message(text: str) -> str:
    """从一句话里认出 `Y-1` 的第三态名；认不出就返回空串。

    判据只有一处：状态名逐字出现在那句话里（`ProviderError` 的消息由
    `decision.refusal_reason` 拼出，逐字含状态名）。为什么不让 provider 抛一个
    带 `state` 属性的异常：`ProviderError` 是调用方唯一需要捕获的类型，给它加
    一个只在第三态有意义的字段，等于给"这一次是不是第三态"添第二个判定点
    （异常类型 / 属性），两处一旦漂移，统计面与产物面会重新分家 ——
    状态名只有一份，就是消息里那一个。
    """
    for state in _PROVIDER_STAT_REFUSAL_STATUSES:
        if state in text:
            return state
    return ""


def _provider_refusal(provider: object, results: Sequence[Candidate]) -> tuple[str, str]:
    """provider 自己台账上的"这一问没发出去"：返回 `(状态名, 理由)`，没有就是两个空串。

    为什么需要这一条：`OpenAlexProvider.search` 的空题面分支刻意不抛
    （提前 `return []`，`R12-R3-1` 钉住的既有行为），统计面只看异常的话会把
    "这一问根本没发出去"读成 `ok` 配 `count == 0` —— 那正是 `Y-1` 那条跨面
    不一致的另一种形态。判据不靠猜，读的是 provider 自己的两处读数：台账
    `last_topicality.state` 是第三态名，且这一跑没有记下任何去向条目
    （真发出去过的那一跑一定有一条去向条目）。带回了结果就一律不算 ——
    "没发出去"与"拿回来几条"不可能同时为真。
    """
    if results:
        return ("", "")
    report = getattr(provider, "last_topicality", None)
    if isinstance(report, Mapping):
        state = _stringify(report.get("state"))
        reason = _stringify(report.get("refusal_reason"))
    else:
        state = _stringify(getattr(report, "state", ""))
        reason = _stringify(getattr(report, "refusal_reason", ""))
    if state not in _PROVIDER_STAT_REFUSAL_STATUSES:
        return ("", "")
    if getattr(provider, "last_query_provenance", None):
        return ("", "")
    return (state, reason)


class MultiProvider:
    """把多个 provider 的结果合并去重，并保留"这条来自哪些源"的信息。

    ``raw.providers`` 是按出现顺序去重的来源名列表。之所以把来源合并进 ``raw``
    而不是丢弃后者，是因为同一篇文献在不同源里的元数据互补（OpenAlex 有被引数、
    Crossref 有页码），后续若需要"用 Crossref 补页码"仍能追溯到另一条原始记录
    （见 ``raw.sources``）。

    ## 统计按 `ProviderStat` 的受控词表分档（`F-6` + `Y-1`）

    `last_stats[name]` 是一个 :class:`ProviderStat`，`status` 区分三件事：
    "跑成了（`count` 可能是 0）"、"抛了异常（`count` 恒 0、`error_kind` 非空）"、
    以及"这一问根本没发给上游"（`Y-1` 的第三态 `query_not_applicable_cjk` /
    `query_empty`：一个请求都没发出去）。第三态从哪两处认出来，见 `search` 里
    异常分支与 `_provider_refusal` 的注释。
    `on_error` 回调不再是唯一能分开这几件事的手段 —— 它仍然会被调用
    （有回调就回调，没回调就记 `logger.warning`），但统计里自己带着原因。
    """

    def __init__(
        self,
        providers: Sequence[SearchProvider],
        *,
        name: str = "multi",
        fail_fast: bool = False,
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self.providers = list(providers)
        self.name = name
        self.fail_fast = fail_fast
        self.on_error = on_error
        #: 每次 search 后记录各源的读数（`F-6` 的三态 + `Y-1` 的第三态）。
        self.last_stats: dict[str, ProviderStat] = {}
        #: 每次 search 后记录逐条相关性判决（`X-NEW-1`）。空 tuple 的台账
        #: ≠ "没有弃权"：`state` 说明这次到底判没判（见 `TopicalityReport`）。
        self.last_topicality: TopicalityReport | None = None
        #: 被拒绝（第三态）的源名与理由。`Y-1` 之后 `last_stats[*].status` 自己
        #: 就是第三态名，这里留的是那句可读的"为什么"（异常原文，或 provider
        #: 台账里的理由）—— "这一问对这条通道不适用"与"上游坏了"不是一件事。
        self.last_refusals: dict[str, str] = {}

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        merged: list[Candidate] = []
        index: dict[str, int] = {}
        self.last_stats = {
            getattr(p, "name", type(p).__name__): ProviderStat() for p in self.providers
        }
        self.last_refusals = {}

        for provider in self.providers:
            provider_name = getattr(provider, "name", type(provider).__name__)
            try:
                results = provider.search(topic, mode, description, want)
            except Exception as exc:  # provider 各异，异常类型无法统一归一
                # 失败就是失败：`count` 记 0 且 `status` 是 `"failed"`，
                # 所以"这个源被限流了"与"这个源没命中"不再同值。
                # `Y-1`：第三态（这一问根本没发出去）从 `failed` 里分出来 ——
                # 状态位本身就是 `evidence` 侧那个第三态名，不再只藏在 `error`
                # 的自由文本里。`error_kind` 留空：拒绝不属于"限流/被墙/解析失败/
                # 网络失败"那条轴，把分类器的 `unknown` 留在那里，说的是
                # "出错了但不知道怎么归类"，而事实是"根本没发出去"。
                refusal_state = _refusal_state_of_message(str(exc))
                self.last_stats[provider_name] = ProviderStat(
                    status=refusal_state or "failed", count=0,
                    error_kind="" if refusal_state else provider_error_kind(exc),
                    error=str(exc),
                )
                # 第三态是"这一问对这条通道不适用"，它的理由与"上游坏了"不同一档，
                # 所以单独留一份可按源读到的记录。
                if refusal_state:
                    self.last_refusals[provider_name] = str(exc)
                if self.on_error is not None:
                    self.on_error(provider_name, exc)
                if self.fail_fast:
                    raise
                # 有 `on_error` 时不再重复打日志：调用方已经拿到这条信息，
                # 再打一遍会让同一件事在日志里出现两次。没有回调时必须打 ——
                # 否则"我没提供 on_error"就等于"这件事不可观测"。
                if self.on_error is None:
                    logger.warning("provider %s 检索失败：%s", provider_name, exc)
                continue

            # `Y-1`：有的 provider 对这一问"没发出去"刻意不抛（见
            # `_provider_refusal` 的 docstring），统计面只能从它自己的台账上读。
            # 读到了就不再看结果 —— 那种情形下 `results` 一定是空的。
            undispatched, why = _provider_refusal(provider, results)
            if undispatched:
                self.last_stats[provider_name] = ProviderStat(
                    status=undispatched, count=0, error_kind="",
                    error=why or undispatched,
                )
                self.last_refusals[provider_name] = why or undispatched
                continue

            self.last_stats[provider_name] = ProviderStat(status="ok", count=len(results))
            for candidate in results:
                key = _merge_identity_key(candidate)
                if key is None:
                    # 无法判定的候选（`F-8`）：既无 DOI、标题也规范化成空串。
                    # 不放进 `index` —— 放进任何桶都会让两条不同的记录合并成一条，
                    # 那正是"缺值被折成正常值"的形态。保留在结果里，
                    # 由下游按 `dedup.find_existing_literature` 的正常路径处理。
                    merged.append(_with_source(candidate, provider_name))
                    continue
                existing_pos = index.get(key)
                if existing_pos is None:
                    index[key] = len(merged)
                    merged.append(_with_source(candidate, provider_name))
                else:
                    merged[existing_pos] = _merge_candidates(
                        merged[existing_pos], candidate, provider_name
                    )
        # 合并后的逐条台账。各子 provider 自己那一份留在它们各自的实例上
        # （`last_topicality`），这里给的是"这一跑合并结果里每一条的判决"。
        self.last_topicality = _record_topicality(
            self.name, mode, topic, merged, description=description,
        )
        return merged[:want]


def _with_source(candidate: Candidate, source: str) -> Candidate:
    """把来源写进 ``raw.providers`` / ``raw.sources``。``raw`` 是可变 dict，就地更新即可。"""
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    providers = list(raw.get("providers") or [])
    if source not in providers:
        providers.append(source)
    raw["providers"] = providers
    sources = list(raw.get("sources") or [])
    sources.append({"provider": source, "raw": raw.get(candidate.provider) or raw.get("openalex")})
    raw["sources"] = sources
    return candidate


def _merge_candidates(base: Candidate, other: Candidate, source: str) -> Candidate:
    """字段级合并：只填补空缺，不覆盖已有值。

    原因是先到的源（如 OpenAlex）通常字段更全，后到的源只在缺字段时补位；
    若反过来覆盖，Crossref 的空 venue 会抹掉 OpenAlex 的有效值。
    """
    _with_source(base, source)
    raw = base.raw

    def pick(a: Any, b: Any) -> Any:
        if a in (None, "", [], {}):
            return b
        return a

    merged = Candidate(
        title=base.title or other.title,
        year=pick(base.year, other.year),
        doi=pick(base.doi, other.doi),
        authors=base.authors or list(other.authors),
        venue=pick(base.venue, other.venue),
        type_code=base.type_code if base.type_code not in ("", "Z") else other.type_code,
        summary=pick(base.summary, other.summary),
        pdf_url=pick(base.pdf_url, other.pdf_url),
        landing_url=pick(base.landing_url, other.landing_url),
        language=pick(base.language, other.language),
        provider=base.provider or other.provider,
        raw=raw,
    )
    return merged


def build_providers(
    names: Iterable[str],
    *,
    config: Mapping[str, Any] | None = None,
    fixture_path: str | os.PathLike | None = None,
) -> list[SearchProvider]:
    """按名字构造 provider 列表（供 CLI 的 ``--provider`` 参数使用）。

    ``MultiProvider`` 的构造交给调用方，这里只负责把名字翻译成实例，
    以便未来新增 provider 时不必改 CLI。
    """
    cfg = dict(config or {})
    out: list[SearchProvider] = []
    for raw_name in names:
        key = (raw_name or "").strip().lower()
        if not key:
            continue
        if key == "openalex":
            out.append(OpenAlexProvider(**_filter_kwargs(OpenAlexProvider.__init__, cfg)))
        elif key == "crossref":
            out.append(CrossrefProvider(**_filter_kwargs(CrossrefProvider.__init__, cfg)))
        elif key == "doaj":
            out.append(DoajProvider(**_filter_kwargs(DoajProvider.__init__, cfg)))
        elif key == "europepmc":
            out.append(EuropePmcProvider(**_filter_kwargs(EuropePmcProvider.__init__, cfg)))
        elif key == "fixture":
            path = cfg.get("fixture_path", fixture_path)
            out.append(FixtureProvider(path))
        else:
            logger.warning("未知 provider：%s（已跳过）", raw_name)
    return out


def _filter_kwargs(func: Callable[..., Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """只透传目标 ``__init__`` 真正接受的参数，避免配置文件里多一个键就崩。"""
    import inspect  # 惰性 import：仅诊断路径需要

    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - 内建对象才可能失败
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(config)
    return {k: v for k, v in config.items() if k in params}


# --------------------------------------------------------------------------------------
# 自检：真实联网跑一次 OpenAlex 检索 + 一次 PDF 下载
# --------------------------------------------------------------------------------------


def _selftest() -> int:
    """自检块：打印真实检索与下载结果（失败如实报告，不伪造成功）。"""
    import sys
    import tempfile

    try:  # Windows 控制台默认 GBK，中文日志会花屏或抛 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("=" * 78)
    print("agentflow.providers 自检：OpenAlex topic='abelian group' mode='topical' limit=3")
    print("=" * 78)

    provider = OpenAlexProvider(min_interval=1.0, retries=3)
    print(f"mailto={provider.mailto!r}  user_agent={provider.user_agent!r}")

    try:
        candidates = provider.search("abelian group", "topical", "", 3)
    except ProviderError as exc:
        print(f"[失败] 检索异常：{exc}")
        return 1

    print(f"命中数：{len(candidates)}  请求数：{provider.stats['requests']}")
    print(f"检索串：{provider.last_query_text}")
    print(
        f"统计：{provider.stats}  过滤原因={provider.last_filter_notes} "
        f"被过滤={provider.last_filtered_out}"
    )
    for i, item in enumerate(candidates, 1):
        print(
            f"  [{i}] {item.title[:80]}\n"
            f"      year={item.year} type={item.type_code} cited={item.raw.get('cited_by_count')} "
            f"channel={item.raw.get('channel')}\n"
            f"      doi={item.doi} pdf={item.pdf_url}\n"
            f"      venue={item.venue} authors={item.authors[:2]} summary_len={len(item.summary)}"
        )

    if not candidates:
        print("[失败] 未命中任何候选，无法继续下载自检。")
        return 1

    targets = [(c.pdf_url, c.title) for c in candidates if c.pdf_url][:5]
    if not targets:
        print("[跳过] 本次命中均无 pdf_url（OpenAlex 只标开放获取链接），下载自检未执行。")
        return 0

    try:
        from .fetch import default_downloader  # 惰性 import：避免模块级循环依赖
    except ImportError:  # 支持 `python providers.py` 直接运行
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from agentflow.fetch import default_downloader  # type: ignore[no-redef]

    # read_timeout 给得比较宽松，但必须有限：实测 AMSNet 会用 200 返回一个
    # 12MB 的 HTML 落地页并以约 25KB/s 的速度吐，无限等待会让自检看起来像挂死。
    downloader = default_downloader({"read_timeout": 60, "retries": 1})
    # 真实世界里 pdf_url 经常撒谎：出版商落地页会用 HTML 顶替直链（实测 AMSNet
    # 就是如此，URL 以 .pdf 结尾却返回 text/html）。因此自检逐个候选尝试，
    # 直到拿到"ok 且无 content_type_mismatch 警告"的结果。
    result = None
    winner = None
    with tempfile.TemporaryDirectory(prefix="agentflow-selftest-") as tmp:
        for pdf_url, title in targets:
            print("-" * 78)
            print(f"下载自检：{pdf_url}")
            attempt = downloader.download(pdf_url, Path(tmp), title)
            print(
                f"  ok={attempt.ok} http_status={attempt.http_status} bytes={attempt.bytes} "
                f"sha256={(attempt.sha256 or '')[:16]}..."
            )
            print(f"  path={attempt.path}")
            print(f"  error={attempt.error}")
            if attempt.path and Path(attempt.path).exists():
                size = Path(attempt.path).stat().st_size
                head = Path(attempt.path).read_bytes()[:5]
                print(f"  落盘大小复核：{size} 字节，文件头={head!r}")
            result = attempt
            if attempt.ok and attempt.error is None:
                winner = attempt
                break
            print("  [不满意] 该链接内容可疑或失败，尝试下一个候选。")

        print(f"downloader.stats={downloader.stats}")
    print("=" * 78)
    if winner is None:
        print("[结果] 未取得内容可信的下载（见上方 error/字节数）。")
        return 1
    print(f"[结果] 下载成功且内容类型一致：{winner.bytes} 字节，sha256={(winner.sha256 or '')[:16]}…")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手动自检入口
    raise SystemExit(_selftest())
