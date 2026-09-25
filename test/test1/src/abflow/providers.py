"""文献检索 provider 层：统一的 ``SearchProvider`` 协议与多个数据源实现。

设计约束（见 ``DESIGN.md`` §4.1 / §5.1）：

* 本模块**顶层不 import 任何兄弟模块**（``schema`` / ``store`` / ``textutil`` 等），
  以便在其余模块尚未落地时也能独立导入与离线测试；确有需要时走惰性 import。
* 所有网络调用都必须带礼貌 ``User-Agent``、做最小间隔限速、对 429/5xx 指数退避重试。
* 本机 hosts 把 ``github.com`` 系域名劫持到 127.0.0.1，因此**不提供**任何依赖
  GitHub 的数据源；``export.arxiv.org`` 实测返回 406、``api.semanticscholar.org``
  实测 429，均不纳入实现。

线程安全：限速状态是**进程级全局**的。原因是"礼貌访问"针对的是上游服务，
而不是某个 provider 实例；同一进程里新建多个 provider（如 MultiProvider 内）
不应各自突破限速。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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
    "keyword_hit",
    "OpenAlexProvider",
    "CrossrefProvider",
    "DoajProvider",
    "EuropePmcProvider",
    "FixtureProvider",
    "MultiProvider",
    "default_user_agent",
    "DEFAULT_FIXTURE_PATH",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# 常量与默认值
# --------------------------------------------------------------------------------------

#: 默认礼貌标识。OpenAlex/Crossref 都建议带上可联系的邮箱，缺省时用 local 占位。
DEFAULT_USER_AGENT = "abflow/0.1 (research prototype; contact: local)"

#: 默认最小请求间隔（秒）。>= 1 req/s 是对公共 API 的基本礼貌。
DEFAULT_MIN_INTERVAL = 1.0

#: 默认重试次数（不含首次尝试）。
DEFAULT_RETRIES = 3

#: 摘要截断长度。摘要只用于人工/AI 快速判断相关性，不能挤占存储与 prompt 预算。
SUMMARY_MAX_CHARS = 1200

#: 离线 fixture 候选文件的默认位置（相对本文件推算，避免依赖 cwd）。
#: 路径链：src/abflow/providers.py -> src/abflow -> src -> test1 -> demo/fixtures/candidates.json
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
# 因此这里放一份**最小实现**。它们都是纯函数、语义与 §3.1/§3.2 一致。


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
    这里**必须防御脏数据**：OpenAlex 偶尔出现位置是非整数、或同一位置被两个词占用，
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
    """归一化 DOI：去 URL 前缀、去 ``doi:`` 前缀、小写。

    去重的第一级键（§3.5）依赖它，所以必须把 ``https://doi.org/10.X`` 与
    ``10.X`` 视为同一篇。
    """
    if not doi:
        return None
    text = _fold_text(str(doi)).strip()
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    text = text.strip().strip(".")
    return text or None


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
    DOAJ/EuropePMC 为 ``J``）。**不做模糊猜测**：把一篇报告猜成期刊论文
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
    * ``False`` —— 能判定且**全部**关键词都没出现（可据此过滤）；
    * ``None``  —— **无法判定**，调用方必须放行。

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


def dedup_key_of(candidate: Candidate) -> str:
    """§3.5 的三级去重键：DOI → 标题+年份 → 无则退化为标题哈希。

    第三级不用 sha256（下载哈希由 fetch 层产生），这里用标题的规范化形态兜底，
    保证键始终非空且稳定。
    """
    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"
    title = _normalize_basic(candidate.title)
    if title:
        year = candidate.year if candidate.year is not None else "na"
        return f"title:{title}|{year}"
    return f"unknown:{abs(hash(candidate.title)):x}"


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

    ``acquire`` 在**同一把锁内**完成"睡眠 + 记录时间戳"，因此多线程并发时
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
        return f"abflow/0.1 (research prototype; mailto:{mailto})"
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
    4xx（除 408/425/429）**不重试**——那是请求本身有问题，重试只会浪费配额。
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
            # **一次**重试机会（应对偶发的截断），之后立刻放弃以省配额。
            if attempt >= retries or (isinstance(exc, json.JSONDecodeError) and attempt >= 1):
                raise last_error from exc
            delay = min(2.0**attempt, 20.0) * (0.8 + 0.4 * random.random())
            time.sleep(delay)

    raise last_error or HttpError(f"failed to fetch {full}", None)


# --------------------------------------------------------------------------------------
# OpenAlex（主力 provider）
# --------------------------------------------------------------------------------------


def _openalex_pdf_url(work: Mapping[str, Any]) -> tuple[str | None, str]:
    """按"可获取性"从高到低挑 PDF 链接，并返回来源说明（便于事后审计）。"""
    best = work.get("best_oa_location") or {}
    if isinstance(best, Mapping):
        url = _stringify(best.get("pdf_url"))
        if url:
            return url, "best_oa_location"
    primary = work.get("primary_location") or {}
    if isinstance(primary, Mapping):
        url = _stringify(primary.get("pdf_url"))
        if url:
            return url, "primary_location"
    locations = work.get("locations") or []
    if isinstance(locations, (list, tuple)):
        for loc in locations:
            if isinstance(loc, Mapping):
                url = _stringify(loc.get("pdf_url"))
                if url:
                    return url, "locations"
    oa = work.get("open_access") or {}
    if isinstance(oa, Mapping):
        url = _stringify(oa.get("oa_url"))
        if url:
            return url, "open_access.oa_url"
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
        self.stats: dict[str, int] = {
            "requests": 0,
            "items": 0,
            "parse_errors": 0,
            "filtered_out": 0,
        }
        #: 上一次 search 实际发出的检索串（按 channel）与过滤原因计数，供诊断用。
        self.last_query_text: dict[str, str] = {}
        self.last_filter_notes: dict[str, int] = {}
        self.last_filtered_out: int = 0

    # -- 对外接口 -----------------------------------------------------------------

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """按 §5.1 的模式策略检索。

        ``limit`` 是**最终返回条数上限**（0 表示用该模式的默认值）；单条查询的
        抓取量由 ``_plan`` 决定，因此 topical 的"奠基 + 前沿"两路各取各的配额，
        不会互相挤占。
        """
        topic = (topic or "").strip()
        description = (description or "").strip()
        mode = (mode or "topical").strip().lower()
        if not topic and not description:
            return []

        plans = _plan_mode(mode, topic, description, limit)
        total_limit = _default_limit(mode) if limit and limit > 0 else sum(p.limit for p in plans)

        out: list[Candidate] = []
        seen: dict[str, Candidate] = {}
        filter_notes: dict[str, int] = {}
        filtered_out = 0
        for plan in plans:
            try:
                works = self._fetch_works(plan.template, plan.limit, sort=plan.sort)
            except ProviderError as exc:
                # 单路失败不应让整个请求失败：另一路（如"前沿"）仍可能产出有效结果。
                logger.warning("OpenAlex 查询路失败（sort=%s）：%s", plan.sort or "relevance", exc)
                continue
            self.last_query_text[plan.channel] = _stringify(plan.template.get("search"))
            for work in works:
                candidate = self._parse_work(work, plan, mode, topic, description)
                if candidate is None:
                    continue
                if candidate.raw.get("filtered_out"):
                    continue
                note = _stringify(candidate.raw.get("filter_note")) or "no_note"
                filter_notes[note] = filter_notes.get(note, 0) + 1
                key = dedup_key_of(candidate)
                if key in seen:
                    continue
                seen[key] = candidate
                out.append(candidate)

        # 记录本轮过滤统计：precise 召回归零时必须能一眼看出是"查询本身没结果"
        # 还是"结果被标题过滤筛干净"，否则只能靠猜（配合 self.last_query_text 与
        # self.stats['filtered_out'] / stats['parse_errors'] 一起看）。
        self.last_filter_notes = filter_notes
        self.last_filtered_out = int(self.stats.get("filtered_out", 0))

        if mode == "broad":
            out.sort(key=_broad_sort_key)
        return out[:total_limit] if total_limit > 0 else out

    # -- 内部实现 -----------------------------------------------------------------

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
        """把 OpenAlex work 对象转成 ``Candidate``；结构性缺失则返回 None。"""
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
        if mode == "precise":
            keep, filter_note = _precise_keep(topic, title, description)

        oa = work.get("open_access") if isinstance(work.get("open_access"), Mapping) else {}
        raw: dict[str, Any] = {
            "filter_note": filter_note,
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

        candidate = Candidate(
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
        return candidate if keep else None


@dataclass(frozen=True)
class _QueryPlan:
    """一条具体的检索路（OpenAlex 一次查询 = 一条路）。"""

    channel: str                       # foundational | frontier | review | popular | precise
    template: dict                     # search / filter 参数模板
    limit: int                         # 该路期望条数
    sort: str | None = None            # OpenAlex sort 表达式；None 表示按相关性


def _phrase_query(text: str) -> str:
    """把检索词收成"短语优先"的查询串。

    裸词检索会被 OpenAlex 的 OR 式相关性打分拉开：实测 ``search=abelian group``
    的按被引降序结果里混进了石墨烯、希格斯玻色子等无关高被引论文。给 ASCII
    词加上引号做短语匹配能显著提高 topic 的约束力；中文词加引号无益（分析器
    不同），故只对 ASCII 词生效。

    **只适用于短的 topic**：OpenAlex 的引号是**字面短语**匹配，实测
    ``"definition of abelian group and its relation to group"`` 命中数为 0
    （没有任何文章的连续文本包含这一整串），因此长 description 绝不能用本函数。
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
    """把长文本收成"词项 + 去停用词"的查询串（**不加引号**）。

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
        # - description 走**词项**检索（自然语言，不能加引号，否则召回为 0）；
        # - topic 走**短语**检索（短检索词，加引号才收得紧）。
        # 两者之间用 OR：否则"描述里的词 + topic 短语"必须同时出现在同一篇里，
        # 实测会把召回压到 0；topic 约束改由标题关键词过滤承担（见 _precise_keep）。
        parts = [p for p in (_term_query(description), _phrase_query(topic) or topic) if p]
        search = " OR ".join(parts)
        return [
            _QueryPlan(
                channel="precise",
                template={"search": search},
                limit=precise_limit,
                sort=None,
            )
        ]

    # topical（默认）：奠基（被引降序）+ 前沿（年份降序）
    topical_limit = limit if limit > 0 else _default_limit("topical")
    phrase = _phrase_query(topic) or topic
    return [
        _QueryPlan(
            channel="foundational",
            template={"search": phrase},
            limit=topical_limit,
            sort="cited_by_count:desc",
        ),
        _QueryPlan(
            channel="frontier",
            template={"search": phrase},
            limit=topical_limit,
            sort="publication_year:desc",
        ),
    ]


def _precise_keep(topic: str, title: str, description: str) -> tuple[bool, str]:
    """precise 模式的标题命中判定，返回 ``(是否保留, filter_note)``。

    降级链（§5.1 要求"keyword 全命中"，但中文 topic 无法与英文标题比字符串）：

    1. topic 抽不出英文关键词 → 无法判定 → **不过滤**，记 ``no_ascii_keywords``；
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

    主力价值不在检索而在**元数据补齐**（页码范围、container-title、issued），
    因此这里把 ``page`` 原始字符串与 ``type`` 一起放进 ``raw`` 供上层使用。
    """

    name = "crossref"
    BASE_URL = "https://api.crossref.org/works"

    #: Crossref 的 ``select`` 白名单字段。**警告**：Crossref 对 select 里的**任一**
    #: 非法字段名返回整请求 400（不是忽略该字段），一次误写会让三种模式全部 400。
    #: 逐个实测（``?select=<字段>`` 单字段探测）后确认：``language`` 属于
    #: "合法字段但不可 select"（返回 ``select-not-available``），因此**必须排除**；
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

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        """按相关度检索。Crossref 无"按被引排序"，因此三种模式共用同一查询构造。"""
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        # 去停用词后送检索：Crossref 的 bibliographic 查询同样被 of/the/and 稀释。
        query = " ".join(x for x in (_term_query(description), _term_query(topic)) if x).strip()
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

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        terms = " ".join(x for x in (description, topic) if x).strip()
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

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        topic = (topic or "").strip()
        description = (description or "").strip()
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        terms = " ".join(x for x in (description, topic) if x).strip()
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

    设计取舍：**不**把缺失的 fixture 当作错误抛出。离线演示/CI 可能先跑
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
        """按 topic 子串做**确定性**过滤（不联网、无随机、无时间依赖）。

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


class MultiProvider:
    """把多个 provider 的结果合并去重，并保留"这条来自哪些源"的信息。

    ``raw.providers`` 是按出现顺序去重的来源名列表。之所以把来源合并进 ``raw``
    而不是丢弃后者，是因为同一篇文献在不同源里的元数据互补（OpenAlex 有被引数、
    Crossref 有页码），后续若需要"用 Crossref 补页码"仍能追溯到另一条原始记录
    （见 ``raw.sources``）。
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
        #: 每次 search 后记录各源贡献条数，便于诊断"某个源静默失效"。
        self.last_stats: dict[str, int] = {}

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0) -> list[Candidate]:
        want = int(limit) if limit and limit > 0 else _default_limit(mode)
        merged: list[Candidate] = []
        index: dict[str, int] = {}
        self.last_stats = {}

        for provider in self.providers:
            provider_name = getattr(provider, "name", type(provider).__name__)
            try:
                results = provider.search(topic, mode, description, want)
            except Exception as exc:  # provider 各异，异常类型无法统一归一
                self.last_stats[provider_name] = 0
                if self.on_error is not None:
                    self.on_error(provider_name, exc)
                if self.fail_fast:
                    raise
                logger.warning("provider %s 检索失败：%s", provider_name, exc)
                continue

            self.last_stats[provider_name] = len(results)
            for candidate in results:
                key = dedup_key_of(candidate)
                existing_pos = index.get(key)
                if existing_pos is None:
                    index[key] = len(merged)
                    merged.append(_with_source(candidate, provider_name))
                else:
                    merged[existing_pos] = _merge_candidates(
                        merged[existing_pos], candidate, provider_name
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
    """字段级合并：**只填补空缺**，不覆盖已有值。

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
    print("abflow.providers 自检：OpenAlex topic='abelian group' mode='topical' limit=3")
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
        from abflow.fetch import default_downloader  # type: ignore[no-redef]

    # read_timeout 给得比较宽松，但**必须有限**：实测 AMSNet 会用 200 返回一个
    # 12MB 的 HTML 落地页并以约 25KB/s 的速度吐，无限等待会让自检看起来像挂死。
    downloader = default_downloader({"read_timeout": 60, "retries": 1})
    # 真实世界里 pdf_url 经常撒谎：出版商落地页会用 HTML 顶替直链（实测 AMSNet
    # 就是如此，URL 以 .pdf 结尾却返回 text/html）。因此自检逐个候选尝试，
    # 直到拿到"ok 且无 content_type_mismatch 警告"的结果。
    result = None
    winner = None
    with tempfile.TemporaryDirectory(prefix="abflow-selftest-") as tmp:
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
