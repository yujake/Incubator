"""证据层：先检索、再逐字回验 —— 让报告里的每条结论都落在某段真实原文上。

## [为什么] 为什么要有这一层

本轮之前，`run_topic` 把模型答复直接当成结论落进 `claims.json` 与报告：
模型说"某定理在 1930 年被证明"，产物里就写着这句话，没有任何外部依据。
"看起来有据"与"真有据"是两件事，而它们之间的缺口恰恰不在任何一段代码里 ——
所以缺口不会报错，只会让报告变得不可复核。

这一层把那句话变成两道可判定的门：

1. 模型只能在 `retrieve` 拿回来的材料里作答（材料为空时不许给结论）；
2. 每条结论必须附一条从材料里逐字复制的引文，且该引文要被 `verify_claims`
   在来源文本里逐字找到 —— 找不到就是 `not_found`（编造的引文必须落到这里）。

## [契约] 检索的三态（本模块的第一条纪律）

`retrieve` 的结局有四种，`checked` 只对前两种为真：

- `ok`：查到了至少一条带 provenance 的来源；
- `no_results`：查过了，但一条可用来源都没有（含"查到条目却全部缺来源信息而被拒收"）；
- `retrieval_failed`：查了，但检索器报错/返回了无法解析的东西 —— 这是"没查成"；
- `not_configured`：压根没有发起检索（没有检索器可造、主题为空、或上游决定不查）。

把 `retrieval_failed` 折叠成 `no_results`，会让"网络断了"看起来像"这个主题没有文献"；
反过来折叠，会让"确实没有文献"看起来像故障。两种读法都会让产物撒谎。

### 多源：逐源记状态，单源失败不许让整体失败

一次检索可以同时问多个库（生产缺省 OpenAlex + Crossref）。逐源状态写进
`sources_status` / `sources_detail[*].status`，取值见 `SOURCE_STATUSES`：

- `ok`：这个源返回了至少一条可归一成来源的条目；
- `no_results`：这个源查过了、但一条可用条目都没有；
- `failed`：这个源查不成（异常、不可构造、返回了无法解析的东西）；
- `query_not_applicable_cjk` / `query_empty`：这一问压根没有发给这个源
  （查询里抽不出英文关键词 / 查询为空，见禁改区 `providers` 的
  `query_applicability`）。它与上面三态不许折平：`failed` 说的是"发了、没查成"，
  第三态说的是"没发 —— 这条通道处理不了这个查询"，把它记成 `ok` 会让
  "未接线"重新混进"检索成功"，记成 `failed` 则丢掉"到底为什么没发"。

### 逐源的判决面：三档分列 + 逐条 `filter_note`（产物面接线）

`sources_detail[*]` 不只记"查到几条"，还把 provider 侧算过、改前算完即丢的
相关性判决折进来（数据源是 `providers.TopicalityReport`）：

- `topicality_buckets`：`judged_relevant` / `rejected` / `unjudged_no_ascii_keywords`
  三档分列 + `total` + `complete`，形状与 `TopicalityReport.counts()` 逐字一致；
- `topicality_notes`：逐条 `filter_note`（`{filter_note: 条数}`），
  `judged_relevant` 也一并收 —— 改前 `last_filter_notes` 里只有内部记号与计数，
  逐条那句话在精筛之后就被丢掉了；
- `topicality_state`：这一跑的整体落法（`judged` / `not_precise` / 第三态名）。

为什么必须是列表而不是一个 `rejected` 总数：`rejected=0` 有两种互不相同的
来源（"精筛跑过了、一条都不该剔"与"精筛 100% 弃权"），下游照报告面取数时
把两者读成同一件事，`draft/28` §100.3 记的正是这个形态。

三档之和恒等于该源的候选总数（`topicality_buckets.total`，也就是台账
`detail` 的长度），`complete` 就是这条断言 —— 它允许大于 `count`（返回值里
被精筛剔除的条目不占 `count`，但它们照样要出现在三档里）。

整体状态由逐源状态推出，判据只有一处（`_status_of_sources`）：
有任一源 `ok` ⇒ `ok`；一个 `ok` 都没有但有源 `no_results` ⇒ `no_results`；
全部 `failed` ⇒ `retrieval_failed`。为什么必须这样推而不是"取最坏的一个"：
把某个库的一次 429 当成整次检索失败，会把手上已有的材料一并丢掉 ——
而材料是这一层唯一的产出，丢掉它等于让报告退化成模型自说自话。

跨源同一篇文献按 DOI 归一化去重（调用禁改区 `dedup.normalize_doi`，不另写第二份规则），
合并后的条目写明它来自哪些源（`providers`）。为什么必须写下来：一条来源被两个库
同时证实时，它与"只有一个库说过"在可信度上不是一回事，而两者在旧结构里长得一样。

## [契约] 逐字回验的四种判决（第二条纪律）

- `verified`：引文在某个来源的原文里逐字存在（唯一能当证据的判决）；
- `not_found`：材料在手上、逐字比对过、没找到 —— 编造的引文落在这一档；
- `known_unverifiable`：这条断言按设计无法用逐字引文回验（例如模型压根没给引文）；
- `unknown`：没查成（手上没有任何来源文本、引文规范化后为空、回验函数抛异常）。

`unknown` 与 `not_found` 的区别就是"没查成"与"查了没有"的区别，绝不许混。

### 判决必须带级别：`abstract` 与 `fulltext`

每条 `verified` 都带 `level ∈ {"abstract", "fulltext"}` 与 `locator`（页或字符偏移）。
这不是装饰：手上只有摘要时，"逐字通过"说的是"这句话在摘要里"，
而读者很容易把它读成"这句话在论文正文里"—— 后者是本层根本没有检查过的事。
所以有全文时优先用全文（`doc.pages` 逐页），只有摘要时才落 `abstract` 级；
一条只存在于摘要、正文里没有的引文，永远只能是 `abstract` 级。

## [契约] 拆分与判决分处两层（本层只做判决）

"把一段答复拆成原子断言"的判据在 `claims` 模块里（`split_claims`），
本模块只做判决（`verify_claims`）与二者的合成入口（`claims.ledger_rows`）。
为什么拆开放：拆分要在没有来源文本时也能跑（它判的是"这段话里有几条断言"），
而判决必须有来源才能跑（它判的是"这条断言的引文在不在"）。
两者合在一个函数里，会让"没有材料"顺带把拆分也一起停掉 ——
而"我们拆出了 12 条，只是没有材料可回验"与"我们没拆"是两句不同的话。

`parse_claims` 因此变成对 `claims.parse_claims` 的转发（同名入口保留是为了
既有调用方的签名不变），本模块不再持有第二套切分容错。

## [契约] 测试接缝只有三个（每个动作一个）

`retrieve(search_fn=...)`、`acquire_fulltext(fetch_fn=..., extract_fn=...)`
与 `verify_claims(quote_fn=...)`：生产为 `None`（此时调用禁改区里的
`providers` / `fetch` / `extract` / `quoteverify` 真实实现），测试注入假函数。
刻意不加 `AGENTFLOW_RETRIEVAL_FAKE` 之类的环境变量后门：那种开关一旦存在，
生产上就会有人误设它，而产物里每一行看起来都仍然可信。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import schema as S
from . import claims as _claims
from . import fulltextstore as _fts

__all__ = [
    "ACQUIRE_STATUSES",
    "CHECKED_STATUSES",
    "EVIDENCE_LEVELS",
    "RETRIEVAL_STATUSES",
    "SOURCE_STATUSES",
    "TOPICALITY_ATTR",
    "VERDICTS",
    "RetrievalNotConfigured",
    "acquire_fulltext",
    "materials_block",
    "not_attempted",
    "parse_claims",
    "retrieve",
    "selftest",
    "verify_claims",
]

#: 检索结局的受控词表（唯一来源；下游只许判这些值）。
RETRIEVAL_STATUSES: tuple[str, ...] = (
    "ok",
    "no_results",
    "retrieval_failed",
    "not_configured",
)

#: 逐源状态：某个库这一次到底查成什么样。
#:
#: 第三态（`query_not_applicable_cjk` / `query_empty`）与 `providers` 侧的
#: 名字逐字相同，不另立一套：改前状态名只出现在 `reason` 的自由文本里，
#: 于是"这一问没发出去"必须靠读字符串才知道 —— 而字符串是给人读的，机器判不了。
#:
#: 为什么加值而不是另开一个字段：`sources_status` / `sources_detail[*].status`
#: 是同一件事的两个出口（`_result` 里只有一处 assert 守着它们），
#: 让第三态只落在其中一个出口上，等于让两个出口对"这一跑怎么落的"给出不同答案。
SOURCE_STATUSES: tuple[str, ...] = (
    "ok",
    "no_results",
    "failed",
    "query_not_applicable_cjk",
    "query_empty",
)

#: 读 provider 逐条判决台账的属性名（`providers.TopicalityReport`）。
#:
#: 为什么按名读而不是 import 那个类：`evidence` 与 `providers` 之间不许有
#: 循环依赖，而且测试接缝注入的是裸函数（没有这个属性）——
#: 读不到就降级成"这一次没有逐条判决"，不许冒泡，也不许编一个空台账充数。
TOPICALITY_ATTR = "last_topicality"

#: 全文获取的逐条状态。六种都要有理由字段 —— 没有理由的失败与"没做"无法分辨。
ACQUIRE_STATUSES: tuple[str, ...] = (
    "ok",
    "no_pdf",
    "download_failed",
    "no_text_layer",
    "extract_failed",
    "not_configured",
)

#: 回验到达的级别。抽象级与全文级不许混：读者必须能看出这次到底查到了哪一层。
EVIDENCE_LEVELS: tuple[str, ...] = ("abstract", "fulltext")

#: 只有这两个状态算"查过了"。为什么单独成常量：退出码、未接线清单、
#: 报告证据段三处都要判同一件事，而写在三处的判据早晚会漂移。
CHECKED_STATUSES: frozenset[str] = frozenset({"ok", "no_results"})

#: 断言判决的受控词表。
VERDICTS: tuple[str, ...] = ("verified", "not_found", "known_unverifiable", "unknown")

#: 检索函数签名：`(topic, *, limit, timeout_sec) -> 条目序列`。
SearchFn = Callable[..., Sequence[Any]]

#: 回验函数签名：与禁改区 `quoteverify.check_quote` 完全一致。
QuoteFn = Callable[..., Any]


class RetrievalNotConfigured(RuntimeError):
    """没有可用的检索器（模块读不到、客户端造不出来、上层决定不查）。

    为什么要单独一个异常类型：它对应"没查成"里的"没配置"，
    而不是"查了失败"。两者在产物里必须能分辨（`not_configured` vs
    `retrieval_failed`），靠异常字符串去猜是不可靠的。
    """


@dataclass(frozen=True)
class _PagesDoc:
    """交给禁改区 `quoteverify.check_quote` 的最小文档视图：只需要 `pages`。

    为什么不用 `extract.DocumentText`：那个类的 `source_kind` 语义是
    pdf/txt/md/html，而这里的"页"是检索回来的摘要文本块。套用它会在产物里
    写下一个假的来源种类（"这段文字来自 PDF"是编的），而本层的全部意义就是
    不许有编出来的来源。

    `pages` 只有一项：手上关于这篇文献的原文就是摘要那一段。
    页码恒为 1 说的不是论文的第 1 页，而是"我们自己持有的那段文本"。
    """

    pages: list[str]


def _result(status: str, sources: Sequence[Mapping[str, Any]], reason: str, *,
            query: str, retrieved_at: str, rejected: Sequence[Mapping[str, Any]] = (),
            limit: int = 0, sources_status: Mapping[str, str] | None = None,
            sources_detail: Sequence[Mapping[str, Any]] | None = None) -> dict:
    """组装检索结果（唯一构造点：`status` 与 `checked` 必须一致，不许各写各的）。

    `sources_status` 逐源记这一源的状态；`sources_detail` 带上条数与失败原因。
    两者都写进产物：只留一个汇总状态的话，"到底问了哪几个库、各自怎么样"
    就只剩在一句话里，而那句话是给人读的，机器判不了。
    """
    assert status in RETRIEVAL_STATUSES, f"未登记的检索状态：{status!r}"
    status_map = {str(k): str(v) for k, v in dict(sources_status or {}).items()}
    for name, value in status_map.items():
        assert value in SOURCE_STATUSES, f"未登记的逐源状态：{name}={value!r}"
    return {
        "status": status,
        "sources": [dict(s) for s in sources],
        "reason": reason,
        "checked": status in CHECKED_STATUSES,
        "query": query,
        "retrieved_at": retrieved_at,
        "rejected": [dict(r) for r in rejected],
        "limit": int(limit),
        # 逐源台账：哪几个源被问过、各自什么结局。空 dict 表示这次没有逐源信息
        # （单函数注入的老路径），与"问了零个源"是两件事，所以用 detail 区分。
        "sources_status": status_map,
        "sources_detail": [dict(d) for d in (sources_detail or [])],
    }


def not_attempted(reason: str, *, query: str = "", now: str | None = None) -> dict:
    """造一份"本次没有发起检索"的结果（没 key、主题为空时由调用方使用）。

    为什么单独成一个函数而不是让调用方手搓 dict：`evidence.json` 的结构
    必须只有一个构造点。第二处手写的 dict 会在加字段时静默漂移，
    而漂移的表现是"某次运行的 evidence.json 少一个字段"，没有任何测试会红。
    """
    return _result("not_configured", [], reason, query=query,
                   retrieved_at=now or S.now_iso())


def _coerce_year(value: Any) -> int | None:
    """尽最大努力取 4 位年份；取不到就 None（绝不猜一个年份填进去）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2999 else None
    if isinstance(value, str):
        m = re.search(r"(1[0-9]{3}|2[0-9]{3})", value)
        return int(m.group(1)) if m else None
    return None


def _text_of(value: Any) -> str:
    """把任意字段压成去首尾空白的字符串（None -> 空串，不写 "None"）。"""
    return "" if value is None else str(value).strip()


def _source_from_item(item: Any, *, index: int, provider: str, query: str,
                      retrieved_at: str) -> tuple[dict | None, str]:
    """把一个检索条目归一成 source；返回 `(source, 拒收原因)`。

    为什么拒收而不是"标一下就算了"：`sources` 是证据列表，
    证据必须能回答"这条来自哪个库、用什么查询、什么时候拿到的"。
    一条来源不明的条目留在列表里，就等于让后续的逐字回验把
    "某段文本"当成"某篇文献的原文"，而引文级的可追溯性正是这一层的全部价值。
    拒收的条目不会消失：它们连同原因写进结果的 `rejected` 字段。

    这里只归一，不合并：跨源去重由 `_merge_into` 负责。两件事分开写，
    是为了让"这条来自哪几个源"由合并那一处统一决定 —— 写在这里会出现
    "先到的源覆盖后到的源"这种依赖顺序的行为，而它不会报错。
    """
    if isinstance(item, Mapping):
        title = _text_of(item.get("title"))
        doi = _text_of(item.get("doi")) or None
        year = _coerce_year(item.get("year"))
        url = _text_of(item.get("url") or item.get("landing_url")) or None
        abstract = _text_of(item.get("abstract") or item.get("summary"))
        src = _text_of(item.get("source") or item.get("provider")) or provider
        pdf_url = _text_of(item.get("pdf_url")) or None
    else:
        title = _text_of(getattr(item, "title", ""))
        doi = _text_of(getattr(item, "doi", "")) or None
        year = _coerce_year(getattr(item, "year", None))
        url = _text_of(getattr(item, "landing_url", "")) or None
        abstract = _text_of(getattr(item, "summary", ""))
        src = _text_of(getattr(item, "provider", "")) or provider
        pdf_url = _text_of(getattr(item, "pdf_url", "")) or None

    if not title:
        return None, "无标题：不能把它当来源引用（标题是引用的最小标识）"
    if not src:
        return None, "来源不明：既没有库名（provider/source），也没有可追溯的出处"
    if not (doi or url):
        return None, f"缺可解析标识：{src} 这条既没有 DOI 也没有 URL，无法复核它真的存在"
    if not url and doi:
        url = f"https://doi.org/{doi}"
    return {
        "source_id": f"S{index}",
        "source": src,
        "providers": [src],
        "doi": doi,
        "title": title,
        "year": year,
        "url": url,
        "abstract": abstract,
        # 开放全文的下载线索。抽取结果（`fulltext`）由 acquire_fulltext 挂上；
        # 这里恒为 None 表示"没有查过全文"，与"查过但没有全文"分得开。
        "pdf_url": pdf_url,
        "fulltext": None,
        # provenance 三件套：哪个库、用什么查询、什么时候。
        # `providers` 是"这条来自哪几个源"：合并时会被补全，单源时就是它自己。
        # 放进 provenance 而不是只放在顶层，是为了让下游只需看 provenance 一处。
        "provenance": {"provider": src, "query": query, "retrieved_at": retrieved_at,
                       "providers": [src], "query_by_source": {src: query}},
    }, ""


def _dedup_keys_of(source: Mapping[str, Any]) -> list[str]:
    """一条来源的全部去重键（DOI 优先、其次标题+年）。

    为什么必须走禁改区 `dedup.literature_keys` 而不是自己拿 DOI 做小写比较：
    DOI 归一化（全角折半角、去 `doi.org/` 前缀、去尾随点）是一条「不可逆」的判据 ——
    第二份规则一旦与 `dedup.normalize_doi` 有一处分歧，同一篇文献就会以两个身份
    同时出现在产物里，而两处各自都自洽、都不会报错。所以这里只取键，不造规则。
    """
    from . import dedup as D  # 惰性 import：见 `_default_search` 的同类说明

    doi = _text_of(source.get("doi")) or None
    title = _text_of(source.get("title"))
    year = source.get("year") if isinstance(source.get("year"), int) else None
    keys = D.literature_keys(title, year, doi)
    # 没有 DOI 时 `literature_keys` 只给标题键；同一标题不同年会被合并成一条，
    # 这是刻意的（预印本与正式版常常同题不同年，§3.5 第三级就是为此存在）。
    return keys or []


def _merge_keys(source: Mapping[str, Any]) -> list[str]:
    """取"可以用来判同一条"的键；返回空列表表示这条没有可判重的键。

    没有键的条目「不许」与别的条目合并：把它们塞进同一个兜底桶里，
    等于凭"都没有标识"这个事实去断言"它们是同一篇"，那不是判重，是猜。
    """
    keys = _dedup_keys_of(source)
    doi_keys = [k for k in keys if k.startswith("doi:")]
    if doi_keys:
        # DOI 是判重键的第一级：有它就不用标题键，避免标题拼写差异把同一篇拆开。
        return doi_keys[:1]
    title_keys = [k for k in keys if k.startswith("title:") and not k.endswith("|*")]
    return title_keys[:1]


def _merge_into(primary: dict, other: Mapping[str, Any]) -> None:
    """把 `other` 合并进 `primary`（就地）。只记来源、只补空缺，不覆盖。

    两个刻意的取舍：

    1. 「先到的为准」：不覆盖已有字段。理由是后到的源（如 Crossref）字段常常更少，
       让它覆盖 OpenAlex 的有效值会让"合并"变成"降级"，而产物上看不出来。
    2. 「两处原始记录的出处差是信息」：`other` 的具体来源记进 `provenance.query_by_source`，
       这样"这条是真的被两个库同时查到"与"两个库里只有一个有它"分得开。
    """
    name = _text_of(other.get("source"))
    providers = list(primary.get("providers") or [])
    if name and name not in providers:
        providers.append(name)
    primary["providers"] = providers

    prov = dict(primary.get("provenance") or {})
    by_source = dict(prov.get("query_by_source") or {})
    other_prov = other.get("provenance") if isinstance(other.get("provenance"), Mapping) else {}
    if name and name not in by_source:
        by_source[name] = _text_of((other_prov or {}).get("query"))
    prov["query_by_source"] = by_source
    primary["provenance"] = prov

    for field in ("doi", "year", "abstract", "pdf_url"):
        if not primary.get(field) and other.get(field):
            primary[field] = other[field]


def _status_of_sources(sources_status: Mapping[str, str]) -> str:
    """把逐源状态推成整体状态（唯一判据）。

    判据的次序是刻意的：`ok` 优先。一个源失败不该让整次检索失败 ——
    手上已有的材料是这一层唯一的产出，因为另一个库限流就把它丢掉，
    等于让报告退化成模型自说自话（而它看起来与"检索了、没找到"一模一样）。
    """
    values = list(sources_status.values())
    if not values:
        return "no_results"
    if "ok" in values:
        return "ok"
    if "no_results" in values:
        return "no_results"
    return "retrieval_failed"


def _default_search(topic: str, *, limit: int, timeout_sec: float) -> Sequence[Any]:
    """生产检索：调用禁改区里的 `providers` 真实客户端（OpenAlex）。

    为什么惰性 import 且把失败翻成 `RetrievalNotConfigured`：
    `providers` 依赖 `dedup`/`schema` 一长串模块，把"能不能 import `evidence`"
    绑到整条链上没有意义；更重要的是导入失败必须落进三态里的"没配置"，
    而不是让 `run_topic` 崩出一个 traceback —— 崩溃会让"没查成"看起来像"程序坏了"。
    """
    try:
        from . import providers as P
    except Exception as exc:  # 导入失败的原因在别处，这里只负责如实归成"没配置"
        raise RetrievalNotConfigured(
            f"读不到 providers 模块（{type(exc).__name__}: {exc}）⇒ 本次没有可用的检索器"
        ) from exc

    try:
        client = P.OpenAlexProvider(
            timeout=float(timeout_sec),
            retries=1,
            per_page=max(1, min(int(limit), int(P.OpenAlexProvider.MAX_PER_PAGE))),
        )
    except Exception as exc:  # 构造参数/环境问题都归成"没配置"（还没发出任何请求）
        raise RetrievalNotConfigured(
            f"检索客户端造不出来（{type(exc).__name__}: {exc}）⇒ 本次没有发起检索"
        ) from exc

    # [踩过] 用 `precise` 而不是 `topical`：实测（2026-09，本机联网）`topical` 的两路查询
    # 按被引/年份排序，主题 "abelian group" 的前几条是石墨烯、希格斯玻色子、
    # 椭圆曲线密码 —— 材料一旦跑偏，"只能用给定材料作答"就变成了
    # "只能引用不相干的材料"。`precise` 走短语检索 + 标题关键词过滤，
    # 同一主题返回的是 Infinite Abelian groups / Abelian groups 这类真对得上的条目；
    # 中文主题（"阿贝尔群"）也返回了标题里带"阿贝尔群"的文献。
    # description 传空：本层的输入只有一个 topic，没有第二段描述可用。
    return client.search(topic, "precise", "", int(limit))


def _per_source_limit(limit: int, n_sources: int) -> int:
    """多源时每个源各要几条。

    为什么不让每个源各要 `limit` 条：条目是按源逐个归一再去重的，
    多问一个源不等于多拿到材料，却要多花一次配额。这里按源数摊分、至少 1 条 ——
    "至少 1"是为了不让 `limit=1, n=3` 这种输入变成"每个源 0 条"（那等于没问）。
    """
    return max(1, int(int(limit) // max(1, int(n_sources))))


def _sources_from_items(raw_items: Sequence[Any], *, source_name: str, query: str,
                        retrieved_at: str, start_index: int = 1) -> tuple[list[dict], list[dict]]:
    """把一个源的原始条目归一成来源列表 + 拒收列表（单源内先按自己的键去重）。"""
    out: list[dict] = []
    rejected: list[dict] = []
    index: dict[str, int] = {}
    for raw in list(raw_items):
        source, why = _source_from_item(
            raw, index=start_index + len(out) - 1, provider=source_name,
            query=query, retrieved_at=retrieved_at,
        )
        if source is None:
            rejected.append({"source": source_name, "reason": why})
            continue
        # `_source_from_item` 的 index 语义是"第几条归一成功的来源"，这里按 `out`
        # 的当前长度算，保证编号连续（中间被拒收的条目不占号）。
        source["source_id"] = f"S{start_index + len(out)}"
        keys = _merge_keys(source)
        pos = next((index[k] for k in keys if k in index), None)
        if pos is None:
            for k in keys:
                index[k] = len(out)
            out.append(source)
        else:
            _merge_into(out[pos], source)
    return out, rejected


def _merge_across_sources(groups: Sequence[tuple[str, Sequence[dict]]],
                          *, query: str, retrieved_at: str) -> tuple[list[dict], list[dict]]:
    """把各源的来源列表跨源合并，返回 `(合并后的来源, 冲突留痕)`。

    合并判据：DOI 归一化后相同（走禁改区 `dedup`），没有 DOI 时退到"标题+年"。
    没有可判重键的条目各自成条，不许塞进同一个兜底桶 —— 那不是判重，是猜。

    冲突留痕回答的是"这篇到底在哪个库里出现过"：两个源给出的标题/年份不一致时，
    合并保留先到的那一份（先到的通常字段更全），但把差异写进 `conflicts` ——
    悄悄挑一个读起来像是"两个源说法一致"，而它们并不一致。
    """
    merged: list[dict] = []
    index: dict[str, int] = {}
    conflicts: list[dict] = []
    for name, items in groups:
        for source in items:
            keys = _merge_keys(source)
            pos = next((index[k] for k in keys if k in index), None)
            if pos is None:
                for k in keys:
                    index[k] = len(merged)
                merged.append(source)
                continue
            current = merged[pos]
            for field in ("title", "year"):
                kept, dropped = current.get(field), source.get(field)
                if kept and dropped and kept != dropped:
                    conflicts.append({"slot": pos, "field": field, "kept": kept,
                                      "dropped": dropped, "from": name,
                                      "reason": "跨源同一篇文献的该字段不一致，保留先到的那一份"})
            _merge_into(current, source)

    for position, source in enumerate(merged, start=1):
        source["source_id"] = f"S{position}"
        prov = dict(source.get("provenance") or {})
        prov["query"] = query
        prov["retrieved_at"] = retrieved_at
        # 这一条来自哪几个库：合并后的条目必须看得出它是被两个库同时证实的。
        prov["providers"] = list(source.get("providers") or [])
        source["provenance"] = prov
        source["duplicate_of"] = [
            {k: v for k, v in c.items() if k != "slot"}
            for c in conflicts if c["slot"] == position - 1
        ]
    return merged, conflicts


#: 三档分列的档名（与 `providers.TopicalityReport.counts()` 的键逐字相同）。
#:
#: 为什么在这里再写一遍而不是 import：本模块要能在没有 `providers` 的
#: 依赖链条时被 import（见 `_default_search` 的同类说明）。这份常量不是
#: 第二套口径 —— 它在 `_normalize_buckets` 里只用来取值，
#: 数由 provider 侧算好传进来；键名漂移会让三档相加对不上 `total`，
#: 而那正是 `complete` 要守的断言。
_TOPICALITY_BUCKETS: tuple[str, ...] = (
    "judged_relevant",
    "rejected",
    "unjudged_no_ascii_keywords",
)

#: 逐条 `filter_note` 的条数上限。为什么要有上限：一条坏 provider 可能对
#: 一万条候选各给一个不同的 `filter_note`（例如把标题拼进理由里），
#: 台账会跟着产物一起膨胀。超限如实记进 `topicality_notes_truncated`，
#: 绝不静默截断。
_MAX_TOPICALITY_NOTES = 200

#: 单源路径（注入一个检索函数）在产物里用的源名。空名会让报告里的
#: `=ok` 读不出"这是哪个源"，而"没有名字"与"名字是空串"不一样。
_SINGLE_SOURCE_NAME = "search_fn"


def _topicality_of(fn: Any) -> Any:
    """取检索函数的最近一次逐条判决台账（没有就 `None`）。

    为什么读函数对象上的属性：`retrieve` 的接缝是一个可调用对象。生产实现
    （`_default_sources` 造的那个闭包）把 provider 实例挂在 `provider` 属性上，
    所以这里取的是 `fn.provider.last_topicality`；测试注入的裸函数没有这些
    属性 ⇒ 返回 `None`（"这一次没有逐条判决"，不是"三档都是 0"）。

    两种形态都收（`fn.last_topicality` / `fn.provider.last_topicality`）是刻意的：
    下游可以包一层自己的函数而不必继承 provider，但读不到就要说读不到，
    不许在这里编一个空台账 —— 那会把"没接线"重新变成"零剔除"。

    不许在这里 import `providers`：那会把"能不能 import evidence"绑到
    整条 provider 依赖链上，而且测试替身会被迫实现一个它不关心的协议。
    """
    direct = _attr_or_none(fn, TOPICALITY_ATTR)
    if direct is not None:
        return direct
    return _attr_or_none(_attr_or_none(fn, "provider"), TOPICALITY_ATTR)


def _attr_or_none(obj: Any, name: str) -> Any:
    """取字段：`Mapping` 按键取、其余对象按属性取；读不到就 `None`（绝不冒泡）。

    为什么两种形态都要收：台账在产物里是 dict（`to_dict()` / JSON 回读），
    在内存里是 `TopicalityReport` 这样的冻结 dataclass —— 两条路径读同一批
    读数，只认一种形态会让另一种静默变成"没有这条读数"
    （实测踩过：只写 `getattr` ⇒ dict 形态恒返回 `None`）。

    为什么把异常也吃掉：`getattr` 在自造属性的测试替身上可能抛异常，
    而一次"读台账失败"绝不该让整次检索从"没查成"变成一次崩溃
    （`retrieve` 的契约是从不抛异常）。
    """
    try:
        if isinstance(obj, Mapping):
            return obj.get(name)
        return getattr(obj, name, None)
    except Exception:  # noqa: BLE001 - 见 docstring：读台账失败只降级，不冒泡
        return None


def _normalize_buckets(report: Any) -> dict | None:
    """把台账的三档数压成产物形态；读不出三档就返回 `None`（"没有这条读数"）。

    接受两种来源：`TopicalityReport.counts()`（对象方法）与同形 dict
    （替身/产物回读）。不补零：把"读不出"写成 0 会让三档相加等于 0、
    看起来与"一条候选都没有"一模一样，而那正是"弃权不可见"的原形态。
    """
    counts = _attr_or_none(report, "counts")
    if callable(counts):
        try:
            counts = counts()
        except Exception:  # noqa: BLE001 - 见 `_attr_or_none` 的同类说明
            return None
    if not isinstance(counts, Mapping):
        return None
    out: dict[str, int] = {}
    for name in _TOPICALITY_BUCKETS:
        value = counts.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        out[name] = value
    total = _attr_or_none(report, "total")
    if isinstance(total, bool) or not isinstance(total, int):
        total = sum(out.values())
    out["total"] = total
    out["complete"] = sum(out[name] for name in _TOPICALITY_BUCKETS) == total
    return out


def _notes_of(report: Any) -> dict[str, int]:
    """逐条 `filter_note` 的分列（`{filter_note: 条数}`，含被剔除的那些条）。

    读数来自台账 `detail`：每一条候选都带一句改前会被丢掉的话。
    `filter_note` 为空的条目归到 `"no_filter_note"` —— 这条记号本身是信息
    （"这一条没有理由"），不许让它与"理由恰好是空串"两件事长得一样。
    """
    detail = _attr_or_none(report, "detail")
    if not isinstance(detail, (list, tuple)):
        return {}
    notes: dict[str, int] = {}
    for verdict in detail:
        raw = verdict.get("filter_note") if isinstance(verdict, Mapping) else \
            _attr_or_none(verdict, "filter_note")
        note = _text_of(raw) or "no_filter_note"
        notes[note] = notes.get(note, 0) + 1
    return notes


def _query_notes_of(report: Any) -> tuple[str, ...]:
    """台账上查询级（不是逐条候选级）的那几句话（`C-4`：短语零召回退词项 / 某一路抛了异常）。

    与 `_notes_of` 刻意不同轴：那个数的是"每一条候选的 `filter_note`"，
    这个收的是"这一问是怎么发出去的"。两条都要出现在产物里，但混进同一个
    字段就再也分不开 —— "这一路没查成"会被读成"这一路的候选都被筛掉了"。
    """
    raw = _attr_or_none(report, "query_notes")
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    for item in raw:
        text = _text_of(item)
        if text:
            out.append(text)
    return tuple(out)


def _report_fields(report: Any) -> dict:
    """台账 → 产物字段；读不出三档时返回空 dict（"这一次没有逐条判决"）。

    空 dict 与"三档都是 0"是两件事：前者是"没有这条读数"，后者是
    "确实一条候选都没有"。折平它们，等于把"没接线"重新藏进"零"里面。
    """
    buckets = _normalize_buckets(report)
    if buckets is None:
        # 这里不是把"没做"折叠成"没有结果"：读不到台账 ⇒ 这几列不出现（缺席）在产物里，
        # 而"三档都是 0"另有其形（台账读得到、候选数为 0）。空 dict 只用于 update，
        # 所以它不会在产物里留下一个看起来像"零剔除"的键 —— 理由见本函数 docstring。
        return {}
    out: dict[str, Any] = {"topicality_buckets": buckets}
    state = _text_of(_attr_or_none(report, "state"))
    if state:
        out["topicality_state"] = state
    notes = _notes_of(report)
    if notes:
        ordered = dict(sorted(notes.items(), key=lambda kv: (-kv[1], kv[0])))
        out["topicality_notes"] = dict(list(ordered.items())[:_MAX_TOPICALITY_NOTES])
        out["topicality_notes_truncated"] = max(0, len(ordered) - _MAX_TOPICALITY_NOTES)
    query_notes = _query_notes_of(report)
    if query_notes:
        # 与 `topicality_notes` 不同：这几句是查询级事实（不是逐条候选的），
        # 条数天然很少（每路最多两条），所以不截断 —— 截断会把"哪一路降级过"藏起来。
        out["topicality_query_notes"] = list(query_notes)
    return out


def _third_state_in(text: str) -> str:
    """从一段自由文本里认出第三态名（认得两个就返回空串，不猜）。

    为什么要认：单源路径（注入一个函数）没有台账可读，唯一带着"这一问
    没发出去"的地方就是失败原因里的状态名 —— 而它今天只以文本形式存在，
    逐源 `status` 于是只能记成 `failed`（"发了、没查成"）。
    两个名字同时出现说明这段文本不是我们写的那种形态，那时不猜。
    """
    hits = [name for name in SOURCE_STATUSES[3:] if name in text]
    return hits[0] if len(hits) == 1 else ""


def _source_detail(source_name: str, *, status: str, count: int, rejected: int,
                   reason: str, conflicts: int = 0, report: Any = None) -> dict:
    """一条逐源台账行：状态 / 条数 / 拒收 / 理由 / 冲突 + 相关性判决面。

    唯一构造点：多源路径与单源路径都走这里。第二处手写的 dict 会在加字段时
    静默漂移，而漂移的表现是"某个入口的 `sources_detail` 少一列"，
    没有任何测试会红（与 `_result` 是同一个理由）。
    """
    row = {
        "source": source_name,
        "status": status,
        "count": int(count),
        "rejected": int(rejected),
        "reason": reason,
        "conflicts": int(conflicts),
    }
    row.update(_report_fields(report))
    return row


def _retrieve_one(name: str, fn: SearchFn, *, row_name: str = "", query: str, limit: int,
                  timeout_sec: float, retrieved_at: str,
                  ) -> tuple[str, list[dict], list[dict], str, dict, str]:
    """问一个源，返回 `(源名, 来源, 拒收, 失败原因, 逐源台账, 逐源状态)`。

    失败原因非空 ⇒ 这个源这一次没有可用条目。这里刻意把"源报错/没发出去"
    与"源没结果"分成两个返回值，而不是靠 `len(items) == 0` 去猜：
    一个源在异常之后也可能返回空列表，而"它坏了"与"它说没有"必须是两句话。

    `逐源状态` 取 `SOURCE_STATUSES` 之一：读得到台账时用台账自己的 `state`
    （第三态名逐字进产物），否则退回 `failed`。

    `name` 与 `row_name` 刻意分开：`name` 是条目缺来源时的兜底库名
    （单源注入路径给空串 —— 那时条目自己没写库名就应当被拒收，而不是被
    贴上一个我们编的库名），`row_name` 只用于逐源台账那一行的 `source` 字段。
    把两者合成一个会让"缺来源的条目"凭空获得一个来源，而那条判据
    （`test_source_without_provenance_is_rejected_and_listed`）正是靠它拒收的。
    """
    row_name = row_name or name
    report = None
    try:
        items = fn(query, limit=int(limit), timeout_sec=float(timeout_sec))
    except RetrievalNotConfigured as exc:
        failure = f"没配置（{exc}）"
        return name, [], [], failure, _source_detail(
            row_name, status="failed", count=0, rejected=0, reason=failure), "failed"
    except Exception as exc:  # 跨库异常无法统一归一，这里必须翻成三态而不是冒泡
        failure = f"{type(exc).__name__}: {exc}"
        # 拒绝路径上 provider 已经把"这一问没发出去"挂进台账；
        # 这里读一次，让第三态名逐字落进逐源 status，而不是只留在 reason 文本里。
        report = _topicality_of(fn)
        detail = _source_detail(row_name, status="", count=0, rejected=0,
                                reason=failure, report=report)
        third = _text_of(_attr_or_none(report, "state"))
        if third not in SOURCE_STATUSES[3:]:
            third = _third_state_in(failure)
        status = third or "failed"
        detail["status"] = status
        return name, [], [], failure, detail, status

    if items is None or isinstance(items, (str, bytes, Mapping)):
        failure = (f"返回了 {type(items).__name__} 而不是条目列表 ⇒ "
                   "无法判断是没查到还是坏掉了")
        detail = _source_detail(row_name, status="failed", count=0, rejected=0, reason=failure)
        return name, [], [], failure, detail, "failed"

    # 2026-10-17（IO #6）：注入的 `search_fn` 可能返回非可迭代值（int/None）——
    # `list(5)` 会抛 TypeError，而 `retrieve` 的 docstring 明写"本函数从不抛异常"。
    if not isinstance(items, (list, tuple)):
        items = []
    sources, rejected = _sources_from_items(
        list(items)[: max(1, int(limit))], source_name=name,
        query=query, retrieved_at=retrieved_at,
    )
    report = _topicality_of(fn)
    status = "ok" if sources else "no_results"
    detail = _source_detail(row_name, status=status, count=len(sources),
                            rejected=len(rejected),
                            reason="查到条目" if sources else "查过了、没有可用条目",
                            report=report)
    return name, sources, rejected, "", detail, status

def retrieve(topic: str, *, limit: int = 5, search_fn: SearchFn | Mapping[str, SearchFn] | None = None,
             timeout_sec: float = 30.0, now: str | None = None) -> dict:
    """按主题检索文献，返回三态化结果（支持多源）。

    `search_fn` 是唯一的测试接缝，两种形态都接受：

    * 一个函数 `(topic, *, limit, timeout_sec) -> 条目序列`（单源，原有形态）；
    * 一个 `{源名: 函数}` 映射（多源）。生产为 `None` ⇒ 走禁改区里的
      `providers`（缺省 OpenAlex + Crossref）。

    多源时的硬规则（每一条都有对应的负控用例）：

    * 「单源失败不让整体失败」：只要有一个源 `ok`，整体就是 `ok`；
    * 两个源都 `no_results` 才是 `no_results`；全都 `failed` 才是 `retrieval_failed`；
    * 跨源按 DOI 归一化去重（走禁改区 `dedup`），合并后的条目带 `providers`，
      看得出它来自哪几个源。

    返回 ``{"status", "sources", "reason", "checked", "query", "retrieved_at",
    "rejected", "limit", "sources_status", "sources_detail"}``；`sources` 里每一条都带
    provenance（库名/查询/时间），缺来源的条目会被拒收并列进 `rejected`
    （"宁可少一条，也不留一条说不清出处的"）。

    `sources_detail` 每条 = `{source, status, count, rejected, reason, conflicts}`
    加上 provider 侧的相关性判决面（`topicality_buckets` 三档分列 /
    `topicality_notes` 逐条 `filter_note` / `topicality_state`）。读不到台账时
    这几个键不出现 —— 不补零，见 `_report_fields`。单源与多源两个入口
    都走 `_source_detail` 这一个构造点（多一个手写 dict 就会静默漂移）。

    本函数从不抛异常：检索客户端的异常类型跨库不统一（`ProviderError`、
    `URLError`、解析错……），让它们冒泡会把"没查成"变成一次崩溃，
    而崩溃在退出码上与"程序有 bug"无法区分。
    """
    query = _text_of(topic)
    retrieved_at = now or S.now_iso()
    if not query:
        return not_attempted(
            "主题为空 ⇒ 本次没有发起检索（空查询打出去只会浪费上游配额）", now=retrieved_at
        )

    wanted = max(1, int(limit))
    if search_fn is None:
        # 生产路径：多源。缺省不落回单源 —— 否则"生产支持多源"就只是一句注释。
        fns = _default_sources(timeout_sec=float(timeout_sec), limit=wanted)
        return _retrieve_many(fns, query=query, limit=wanted,
                              timeout_sec=float(timeout_sec), retrieved_at=retrieved_at)
    if isinstance(search_fn, Mapping):
        return _retrieve_many(dict(search_fn), query=query, limit=wanted,
                              timeout_sec=float(timeout_sec), retrieved_at=retrieved_at)

    fn = search_fn
    # 单源路径的条目一样要逐源台账：报告渲染读 `sources_status`、判据读
    # `sources_detail`，两个出口对"这一跑怎么落的"必须同一答案。
    # 返回的兜底库名显式丢掉（`_`）：注入的条目自己没写库名时应当被拒收，
    # 而不是被贴上一个我们编出来的库名；`row_name` 只管台账那一行怎么署名。
    _, sources, rejected, failure, detail, source_status = _retrieve_one(
        "", fn, row_name=_SINGLE_SOURCE_NAME, query=query, limit=wanted,
        timeout_sec=float(timeout_sec), retrieved_at=retrieved_at,
    )
    if failure:
        status = "not_configured" if failure.startswith("没配置") else "retrieval_failed"
        return _result(status, [], f"检索失败（{failure}）" if status == "retrieval_failed"
                       else failure, query=query, retrieved_at=retrieved_at, limit=limit,
                       sources_status={_SINGLE_SOURCE_NAME: source_status},
                       sources_detail=[detail])
    if not sources:
        why = ("查过了，但这个主题一条文献都没有返回"
               if not rejected
               else f"查到 {len(rejected)} 条，但全部缺来源信息（无一可追溯到具体库与查询）⇒ 全部拒收")
        return _result("no_results", [], why, query=query, retrieved_at=retrieved_at,
                       rejected=rejected, limit=limit,
                       sources_status={_SINGLE_SOURCE_NAME: source_status},
                       sources_detail=[detail])

    return _result("ok", sources, f"查到 {len(sources)} 条可用来源", query=query,
                   retrieved_at=retrieved_at, rejected=rejected, limit=limit,
                   sources_status={_SINGLE_SOURCE_NAME: source_status},
                   sources_detail=[detail])


def _retrieve_many(fns: Mapping[str, SearchFn], *, query: str, limit: int,
                   timeout_sec: float, retrieved_at: str) -> dict:
    """多源检索：逐源问、逐源记状态、跨源合并，最后按逐源状态推整体状态。

    源名的顺序就是 `fns` 的插入顺序（调用方给的那个顺序），不许在内部重排 ——
    "先问哪个库"决定了同一条冲突字段保留哪一份，重排会让产物随字典实现变化，
    而那种变化没有任何测试会红。
    """
    per_source = _per_source_limit(limit, len(fns))
    groups: list[tuple[str, Sequence[dict]]] = []
    sources_status: dict[str, str] = {}
    detail: list[dict] = []
    rejected: list[dict] = []

    for name in fns:
        source_name = _text_of(name) or "unknown"
        got_name, sources, dropped, failure, row, source_status = _retrieve_one(
            source_name, fns[name], row_name=source_name, query=query, limit=per_source,
            timeout_sec=timeout_sec, retrieved_at=retrieved_at,
        )
        sources_status[source_name] = source_status
        detail.append(row)
        rejected.extend(dropped)
        groups.append((got_name, sources))

    merged, conflicts = _merge_across_sources(groups, query=query, retrieved_at=retrieved_at)
    overall = _status_of_sources(sources_status)
    if overall == "ok":
        reason = f"查到 {len(merged)} 条可用来源（去重后；咨询 {len(fns)} 个源）"
    elif overall == "no_results":
        reason = f"咨询了 {len(fns)} 个源，全部没有可用条目（含被拒收的）"
    else:
        # 全失败那一支逐条列出"为什么没查成"，并带上逐源状态名：第三态的那些源
        # 与"上游坏了"在这一句里从此读得出来（改前只有源名与自由文本，
        # `query_not_applicable_cjk` 只是文本里的一串字）。
        why = "；".join(f"{d['source']}={d['status']}: {d['reason']}" for d in detail
                        if d["status"] == "failed" or d["status"] in SOURCE_STATUSES[3:])
        reason = f"{len(fns)} 个源全部失败 ⇒ 本次没有查到任何东西（不是'没有文献'）：{why}"

    return _result(overall, merged, reason, query=query, retrieved_at=retrieved_at,
                   rejected=rejected, limit=limit, sources_status=sources_status,
                   sources_detail=[{**d, "conflicts": len(conflicts)} for d in detail])


def _default_sources(*, timeout_sec: float, limit: int) -> dict[str, SearchFn]:
    """生产多源：禁改区 `providers` 里的 OpenAlex 与 Crossref 各一个检索函数。

    为什么复用 `providers.build_providers` 而不是自己发 HTTP：Crossref 的查询构造、
    `select` 字段白名单（写错一个字段整个请求 400）、JATS 摘要去标签都已在那边
    调校过；在这里照着重写一份，等于让"检索口径"有两个来源，而两者漂移时
    产物上只会表现为"结果不太一样"。

    两个源都在这里构造：任意一个造不出来（版本差异、环境问题）只是让那个源
    落 `failed`，其余源照样跑 —— 这正是"单源失败不许让整体失败"的落地形态。
    """
    try:
        from . import providers as P
    except Exception as exc:  # 导入失败的原因在别处，这里只负责如实归成"没配置"
        raise RetrievalNotConfigured(
            f"读不到 providers 模块（{type(exc).__name__}: {exc}）⇒ 本次没有可用的检索器"
        ) from exc

    per_source = max(1, int(limit))
    wanted = ("openalex", "crossref")
    try:
        built = P.build_providers(wanted, config={
            "timeout": float(timeout_sec),
            "retries": 1,
            "per_page": per_source,
            "rows": per_source,
            "min_interval": 1.0,
        })
    except Exception as exc:  # 构造参数/环境问题都归成"没配置"（还没发出任何请求）
        raise RetrievalNotConfigured(
            f"检索客户端造不出来（{type(exc).__name__}: {exc}）⇒ 本次没有发起检索"
        ) from exc

    out: dict[str, SearchFn] = {}
    for provider in built:
        name = _text_of(getattr(provider, "name", "")) or "unknown"

        def _search(topic: str, *, limit: int, timeout_sec: float,
                    _p=provider) -> Sequence[Any]:
            # 与单源路径同一套模式选择：见 `_default_search` 里对 `precise` 的实测说明。
            return _p.search(topic, "precise", "", int(limit))

        # 把 provider 实例挂在这个检索函数上：`_retrieve_one` 因此能读到它
        # 刚刚写下的 `last_topicality`（三档分列 + 逐条 filter_note）。
        # 为什么挂在函数上而不是另开一个返回值：`SearchFn` 的签名是公开接缝
        # （`tests/test_evidence.py::test_search_fn_receives_topic_limit_and_timeout`
        # 对称地钉着它），加一个返回值要动全部调用方与全部替身；
        # 挂实例则对替身零要求（读不到就降级成"这一次没有逐条判决"）。
        _search.provider = provider  # type: ignore[attr-defined]
        out[name] = _search
    if not out:
        raise RetrievalNotConfigured("providers.build_providers 没有造出任何检索源 ⇒ 本次没有发起检索")
    return out


# ---------------------------------------------------------------------- 全文获取

#: 认得出是 PDF 的后缀。判据取自 URL 路径而不是 Content-Type：直链常被落地说谎，
#: 而"能不能抽文本"的最后判据是抽取器，不是我们猜的类型。
_PDF_SUFFIXES = (".pdf",)


def _pdf_url_of(source: Mapping[str, Any]) -> str:
    """挑这条来源的开放全文 URL；没有就空串。"""
    direct = _text_of(source.get("pdf_url"))
    if direct:
        return direct
    url = _text_of(source.get("url"))
    path = url.split("?", 1)[0].lower()
    if url.lower().startswith(("http://", "https://")) and path.endswith(_PDF_SUFFIXES):
        return url
    return ""


def _field(result: Any, name: str, default: Any = None) -> Any:
    """从 `FetchResult` / `DocumentText` 同类对象或同形 dict 里取字段。"""
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _sha256_file(path: str) -> str:
    """算落盘文件的 sha256（按块读，文件多大都不吃内存）。

    为什么必须自己算而不能只信下载器给的哈希：抽取失败/被截断的文件也要能定位，
    而"文件在盘上"与"下载器说它哈希是多少"是两件事（文件可能已被别处改写）。
    算不出来就返回空串并写明原因，绝不编一个哈希填进去。
    """
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        # 读不到文件时返回空串：哈希算不出来是"没算成"，调用方会据此看出缺哈希，
        # 而不是拿到一个看起来正常的假值。
        return ""


def _default_fetch_fn(url: str, dest_dir: Path, filename_hint: str) -> Any:
    """生产下载：禁改区 `fetch.default_downloader`（唯一权威实现）。

    惰性 import：本模块要在没有 `fetch`/`extract` 链条的环境里也能被 import
    （`retrieve` 与 `verify_claims` 都不依赖它们）。
    """
    from . import fetch as F

    return F.default_downloader().download(url, dest_dir, filename_hint)


def _default_extract_fn(path: str) -> Any:
    """生产抽取：禁改区 `extract.extract_text`（唯一权威实现）。"""
    from .extract import extract_text

    return extract_text(path)


def _acquire_one(source: dict, fetch_fn: Callable[..., Any], extract_fn: Callable[..., Any], *,
                 dest_dir: Path, max_bytes: int,
                 text_store_dir: str | Path | None = None) -> None:
    """给一条来源做全文获取，就地把结论写进它的 `fulltext` 字段（六态 + 理由）。

    写进来源本身而不是另起一张表：回验要用 `fulltext.pages`，报告要报"哪几条到了
    全文级"，两处必须看同一份数据。另存一份会让它们有机会不一致。
    """
    url = _pdf_url_of(source)
    if not url:
        source["fulltext"] = {"status": "no_pdf", "reason": "没有可下载的开放全文链接（只拿到摘要）",
                              "url": ""}
        return
    try:
        fetched = fetch_fn(url, dest_dir, _text_of(source.get("title")) or "paper")
    except Exception as exc:  # 下载器抛异常也算下载失败，不许冒泡出去毁掉整条来源
        source["fulltext"] = {"status": "download_failed", "url": url,
                              "reason": f"下载抛异常（{type(exc).__name__}: {exc}）"}
        return

    ok = bool(_field(fetched, "ok", False))
    path = _text_of(_field(fetched, "path")) or ""
    error = _text_of(_field(fetched, "error")) or ""
    if not ok:
        source["fulltext"] = {"status": "download_failed", "url": url,
                              "reason": error or "下载失败（下载器没有给出原因）",
                              "http_status": _field(fetched, "http_status")}
        return
    if not path:
        # 声称成功却没有落盘路径：这是"下载器说了谎"，绝不许当成 ok 往下抽。
        source["fulltext"] = {"status": "download_failed", "url": url,
                              "reason": "下载器报 ok 但没有给出落盘路径 ⇒ 无可抽取的文件"}
        return

    bytes_on_disk = 0
    try:
        bytes_on_disk = Path(path).stat().st_size
    except OSError:
        # 落盘路径读不到：下面的抽取会如实失败，这里不编字节数。
        bytes_on_disk = 0
    if bytes_on_disk > int(max_bytes):
        source["fulltext"] = {"status": "download_failed", "url": url, "path": path,
                              "bytes": bytes_on_disk, "sha256": _sha256_file(path),
                              "reason": f"落盘文件 {bytes_on_disk} 字节，超过上限 {max_bytes} 字节"}
        return

    try:
        doc = extract_fn(path)
    except Exception as exc:  # 抽取器的异常类型跨后端不统一，这里统一翻成 extract_failed
        source["fulltext"] = {
            "status": "extract_failed", "url": url, "path": path,
            "bytes": bytes_on_disk, "sha256": _sha256_file(path),
            "reason": f"抽取失败（{type(exc).__name__}: {exc}）",
        }
        return

    pages = [str(p) for p in (_field(doc, "pages", []) or [])]
    if not pages:
        # 扫描件：能被打开、页数正常，但一页文本都没有。它不是抽取失败，
        # 差别在于"要 OCR"与"要换抽取器"，而这两件事该做的动作完全不同。
        source["fulltext"] = {
            "status": "no_text_layer", "url": url, "path": path,
            "bytes": bytes_on_disk, "sha256": _sha256_file(path),
            "reason": "抽出来没有任何文本层（疑似扫描件，需要 OCR 才能逐字回验）",
        }
        return

    base = {
        "status": "ok",
        "url": url,
        "path": path,
        "sha256": _text_of(_field(fetched, "sha256")) or _sha256_file(path),
        "bytes": bytes_on_disk,
        "pages": len(pages),
        "backend": _text_of(_field(doc, "source_kind")) or "unknown",
        "encoding": _field(doc, "encoding"),
        "download_warning": error,
        "reason": f"抽到 {len(pages)} 页文本（后端 {_text_of(_field(doc, 'source_kind')) or 'unknown'}）",
    }
    # 抽取出来的逐页文本就是证据本体（回验要拿它逐字比对），但它有两种存法：
    #
    # - 给了 `text_store_dir`：按内容寻址存进项目的 `.fulltext/`，产物里只留 `text_ref`
    #   （同一本书的同一份正文只存一份；依据 `draft/30` §T0-2 与 `draft/29` §7.4）。
    # - 没给：逐页文本内联在产物里（形态与改前一致）。这里不再写 `text` ——
    #   它是 `"\n".join(pages)` 的重复，全仓实测没有任何读者（`draft/29` §1 的读数）。
    #
    # 注意：写侧与读侧是同一条链 —— 只写 `text_ref` 而不让读侧认它，会让"全文级回验"
    # 静默降级。所以本处改动必须与 `_fulltext_pages`（§T0-3）同批落地。
    if text_store_dir is None:
        base["text_pages"] = pages
        base["text_store"] = "inline"
    else:
        ref = _fts.put(pages, store_dir=text_store_dir,
                       pdf_sha256=_text_of(base["sha256"]), pdf_path=str(path),
                       pdf_bytes=bytes_on_disk, backend=str(base["backend"]),
                       encoding=base["encoding"] if isinstance(base["encoding"], str) else None)
        base["text_ref"] = ref
        base["chars"] = int(ref.get("chars") or 0)
        base["text_store"] = "ref"
    source["fulltext"] = base


def _acquire_impls(fetch_fn: Callable[..., Any] | None,
                   extract_fn: Callable[..., Any] | None) -> tuple[Any, Any, str]:
    """确定这一次实际用哪个下载器与抽取器；返回 `(下载, 抽取, 没配置的原因)`。

    `None` 走进生产实现意味着"我要去拿禁改区里的 `fetch` / `extract`"，
    而「拿不到」与"拿到了、这次没查成"必须分开：所以这里主动 import 一次，
    失败就带着原因回来，调用方把它写成 `not_configured`，而不是逐条报下载失败 ——
    后者会让所有来源看起来"都下载失败了"，那是把基础设施缺失记成文献的属性。
    """
    fetch_impl, extract_impl = fetch_fn, extract_fn
    problem = ""
    if fetch_impl is None:
        try:
            fetch_impl = _default_fetch_fn
        except Exception as exc:  # 读不到 fetch 模块：本次没有下载器，不是"没有全文"
            problem = f"读不到下载器（{type(exc).__name__}: {exc}）"
    if extract_impl is None:
        try:
            extract_impl = _default_extract_fn
        except Exception as exc:  # 读不到 extract 模块：同上，归"没配置"
            problem = problem or f"读不到抽取器（{type(exc).__name__}: {exc}）"
    return fetch_impl, extract_impl, problem


def acquire_fulltext(sources: Sequence[Any], *, fetch_fn: Callable[..., Any] | None = None,
                     extract_fn: Callable[..., Any] | None = None,
                     dest_dir: str | Path | None = None, limit: int = 5,
                     max_bytes: int = 50 * 1024 * 1024,
                     only_source_ids: Sequence[str] | None = None,
                     text_store_dir: str | Path | None = None) -> dict:
    """给检索到的来源逐条拿全文，六态化写回每条的 `fulltext` 字段。

    六态与各自的理由字段是这一层的全部内容：`ok` / `no_pdf`（没有可下载的开放全文）/
    `download_failed` / `no_text_layer`（是扫描件）/ `extract_failed` / `not_configured`。
    为什么"没有 PDF"与"下载失败"必须是两句话：前者是这篇文献的客观属性（要换文献），
    后者是基础设施问题（要重试），而把两者折叠成一个"失败"会让人对整批来源做一个
    错误的动作。 `not_configured` 覆盖两种"没做"：压根没有下载器/抽取器可造，
    以及超出本次 `limit` 而「没有发起」下载 —— 后者绝不许写成 `no_pdf`。

    `fetch_fn` / `extract_fn` 是唯一的生产接线点，两者都为 `None` 时走禁改区里的
    `fetch.default_downloader` 与 `extract.extract_text`；测试注入假函数。

    `text_store_dir` 决定"逐页正文存哪"（`draft/30` §T0-2）：给了它就按内容寻址存进
    该目录（产物里只留 `text_ref`，同一本书的同一份正文只存一份）；不给就内联在产物里
    （形态与改前一致，只是不再写那个没人读的 `text` 字段）。两种形态由 `text_store`
    键自报，读者不必猜。

    本函数不抛异常（构造下载器失败除外，那归 `not_configured`）：一条来源的
    下载/抽取失败只影响它自己。返回
    ``{"configured", "checked", "limit", "statuses", "counts", "results", "reason"}``。
    """
    wanted = max(1, int(limit))
    only = {_text_of(x) for x in (only_source_ids or [])}
    selected = [s for s in sources
                if isinstance(s, dict) and (not only or _text_of(s.get("source_id")) in only)]
    out_dir = Path(dest_dir) if dest_dir is not None else Path(".")

    fetch_impl, extract_impl, setup_error = _acquire_impls(fetch_fn, extract_fn)
    results: list[dict] = []
    for index, source in enumerate(selected):
        sid = _text_of(source.get("source_id")) or "?"
        existing = source.get("fulltext")
        if isinstance(existing, Mapping) and _text_of(existing.get("status")) == "ok":
            # 已经有全文的来源不重复下载：再下一次只会覆盖同一份证据，
            # 却要再花一次配额，而且会让这一次的哈希替掉上一次那一份。
            results.append({"source_id": sid, "status": "ok",
                            "reason": "已有全文（本次未重复下载）", "pages": 0,
                            "sha256": _text_of(existing.get("sha256")), "bytes": 0,
                            "backend": _text_of(existing.get("backend"))})
            continue
        if setup_error:
            source["fulltext"] = {"status": "not_configured", "reason": setup_error}
        elif index >= wanted:
            source["fulltext"] = {
                "status": "not_configured",
                "reason": f"超出本次 limit={wanted} ⇒ 没有发起下载（不是'没有开放全文'）",
            }
        else:
            _acquire_one(source, fetch_impl, extract_impl, dest_dir=out_dir, max_bytes=max_bytes,
                         text_store_dir=text_store_dir)
        doc = source.get("fulltext") or {}
        results.append({
            "source_id": sid,
            "status": _text_of(doc.get("status")) or "not_configured",
            "reason": _text_of(doc.get("reason")),
            "pages": int(doc.get("pages") or 0),
            "sha256": _text_of(doc.get("sha256")),
            "bytes": int(doc.get("bytes") or 0),
            "backend": _text_of(doc.get("backend")),
        })

    statuses = [r["status"] for r in results]
    counts = {name: statuses.count(name) for name in ACQUIRE_STATUSES}
    ok_sources = [s for s in selected
                  if (_text_of((s.get("fulltext") or {}).get("status")) == "ok")]
    checked = bool(selected) and not setup_error
    if setup_error:
        reason = f"没有可用的下载/抽取实现 ⇒ 本次没有做全文获取（{setup_error}）"
    elif not selected:
        reason = "本次没有可获取全文的来源（检索没查成或来源为空）⇒ 没有发起任何下载"
    else:
        reason = (f"{len(ok_sources)}/{len(selected)} 条来源拿到了可逐字回验的全文；"
                  f"其余各态见 counts（每一种都带理由）")
    return {
        "configured": not setup_error,
        "checked": checked,
        "limit": wanted,
        "statuses": statuses,
        "counts": counts,
        "results": results,
        "ok_sources": len(ok_sources),
        "reason": reason,
    }


# ---------------------------------------------------------------------- 引文逐字回验


_DEFAULT_PARSE_MAX = 200
"""`parse_claims` 在调用方没有指定上限时实际用的条数上限。

为什么要写成这个模块里的一处常量：包装层的参数默认值必须是不可变对象，
所以这里只能把数字写死一次（不能写 `claims.DEFAULT_MAX_CLAIMS`）。
于是"上限"这件事在两个模块各出现一次，靠
`tests/test_evidence.py::test_evidence_parse_claims_is_a_pure_forwarder`
断言两边相等 —— 上限漂移会让两条路径拆出不同的条数，而两者各自都自洽。
"""


def parse_claims(text: str, *, max_claims: int = _DEFAULT_PARSE_MAX,
                 parse_fn: Any = None) -> list[dict]:
    """把模型答复切成断言（每条含 `text` 与 `quote`）—— 纯转发到 `claims.parse_claims`。

    判据（哪些算一条断言、依据是什么、超上限怎么办）只有一份实现，
    在 `claims` 模块里（FC-03：同一判据只许一处实现）。这里保留同名入口是为了
    既有调用方与既有测试的签名不变；实现是纯转发，本模块不补第二套容错 ——
    两份容错一旦漂移，同一段答复会拆出两个条数，而两者各自都自洽。

    与旧实现的行为差别（这是本工作包要解决的问题之一）：旧实现只认
    `- 结论 || 引文` 与 `断言：X | 引文：Y` 两种写法，没有引文的行会被直接丢弃；
    现在没有引文的断言同样进台账（判决 `known_unverifiable`），
    切不出的行由 `claims.split_claims` 归成三态并带理由。

    `max_claims` 的缺省不再是旧的 8：8 条会把一段论文级的答复截到 8 条，
    而旧实现不记录截掉了多少条（截断诚实由 `claims.split_claims` 负责）。
    """
    return _claims.parse_claims(text, max_claims=max_claims, parse_fn=parse_fn)


def materials_block(sources: Sequence[Mapping[str, Any]], *, max_chars: int = 1200,
                    limit: int = 8) -> str:
    """把来源渲染成 prompt 里的"可用材料"段。

    为什么要单独成函数：这一段是"模型只能用这些材料作答"这条约束的唯一载体，
    而它同时也是产物可解释性的一部分（同一份材料 + 同一份 prompt 才谈得上复现）。
    材料为空时它必须明说"没有材料、不许给结论" —— 静默给一个空段会让模型
    凭记忆作答，而产物上看起来与有材料时一模一样。
    """
    head = [
        "",
        "## 可用材料（唯一允许作为依据的内容）",
        "",
    ]
    usable = [s for s in list(sources)[: max(1, int(limit))] if _text_of(s.get("title"))]
    if not usable:
        head += [
            "（本次没有检索到任何可用材料。）",
            "",
            "## 作答要求",
            "",
            "- 材料为空 ⇒ 不许给出任何实质结论；直接回答“材料中没有可依据的内容”。",
            "- 不许引用材料之外的任何文献、数据或记忆。",
            "",
        ]
        return "\n".join(head)

    for s in usable:
        title = _text_of(s.get("title"))
        year = s.get("year")
        bits = [f"[{_text_of(s.get('source_id')) or 'S?'}] {title}"]
        tail = "，".join(x for x in (
            f"年份 {year}" if year else "",
            f"来源 {_text_of(s.get('source'))}",
            f"DOI {_text_of(s.get('doi'))}" if s.get("doi") else "",
        ) if x)
        if tail:
            bits.append(f"（{tail}）")
        abstract = _text_of(s.get("abstract"))
        if abstract:
            if len(abstract) > max_chars:
                abstract = abstract[:max_chars].rstrip() + "…"
            bits.append(f"\n摘要：{abstract}")
        else:
            bits.append("\n摘要：（这条来源没有摘要文本，无法据它引用原文）")
        head.append("".join(bits))
        head.append("")

    head += [
        "## 作答要求",
        "",
        "- 只能用上面材料里的内容作答；材料里没有的，写“材料中没有”。",
        "- 每条结论一行，格式严格为：`- <结论> || <从上面摘要里逐字复制的引文>`。",
        "- 引文必须逐字复制（不许改写、不许拼接、不许把两条摘要合并）。",
        "- 没有材料支持的结论不要写：编造的引文会被逐字回验判为未通过。",
        "",
    ]
    return "\n".join(head)


def _check_one(doc: _PagesDoc, quote: str, fn: QuoteFn, *, window_kind: str) -> Any:
    """对单条来源调用一次回验函数（唯一调用点，签名与禁改区实现一致）。

    声明的页码范围恒为"手上这段文本的全部页"：`pages` 有什么就声明什么。
    为什么必须一致：`check_quote` 先按声明窗口查，窗口之外的页「不看」 ——
    摘要是单页文本，声明 `(1, 1)` 正好；全文可能几十页，还声明 `(1, 1)` 就会让
    正文第 2 页上逐字存在的引文被判 `not_found`，而"逐字存在"是硬事实，
    把它判成编造是最坏的一类错判。

    `window_kind` 只写进页码标签（`PageRange.source_kind`），不参与判定：
    它让产物里能看出"这次是在摘要上比对的还是在全文上比对的"。
    """
    total = max(1, len(doc.pages))
    return fn(doc, quote, S.PageRange(1, total, window_kind), widen=0,
              allow_fulltext_fallback=False)


def _read_verdict(result: Any) -> tuple[bool | None, str]:
    """从回验结果里读出三态与原因（同时接受 `QuoteCheck` 与同形 dict）。

    ## `verified is None`（回验器拒绝判定）的第二项在这里就近补默认值

    此前它默认成 `"unknown"`，于是调用方那句
    `verdict_reason or "verifier_refused_to_judge"` 永远走不到 ——
    一个更具体的字面量成了死词汇（`R2-AN-6`：`draft/28` §40.5）。
    默认值搬到这里之后，"拒绝判定"写下的理由就是那个更具体的字面量，
    调用方不再需要（也不许再）加一层同义兜底：同一个事实只许有一个定义。

    为什么 `verified=False` 时不在这一层补默认值：那种情况下回验器没给理由
    是可达的（`{"verified": False, "reason": ""}`，探针 `D2`），
    而"没命中"的兜底（`not_found`）属于调用方的语境（它知道候选来源有几个）。
    两档的理由不是同一件事，在这里合并会把"回验器拒绝判定"与
    "回验器说没命中、但没给理由"折叠成一个词。
    """
    if isinstance(result, Mapping):
        verified = result.get("verified")
        reason = _text_of(result.get("reason"))
    else:
        verified = getattr(result, "verified", None)
        reason = _text_of(getattr(result, "reason", ""))
    if verified is None:
        return None, reason or "verifier_refused_to_judge"
    return bool(verified), reason


def _fulltext_pages(source: Mapping[str, Any],
                    cache: dict[str, tuple[list[str], str]] | None = None,
                    ) -> tuple[list[str], str]:
    """这条来源的逐页正文从哪来：返回 `(逐页文本, 问题)`，问题为空串才算读成。

    两种存法都必须能读（`draft/30` §T0-3）：产物里带 `text_ref` 时按引用去 store 读，
    否则读内联的 `text_pages`。为什么要有这一层：此前 `text_pages` 在两处被直接读
    （`_pages_of` 与 `_check_quote_levels`），两处直读就是两份口径。

    `cache` 的作用域是一次 `verify_claims` 调用内的局部字典（键 = `text_ref.path`）：
    同一份 4.6 MB 的 store 文件不该在一次回验里被解析七遍。刻意不做模块级缓存 ——
    那会跨调用掩盖"文件被改"，而这一层的全部价值就在于当场发现文件被改。

    坏引用绝不许折成"这篇没有全文"：调用方拿到非空的问题串时，必须把它写进理由
    （`store_file_missing` 与"没有开放全文"是两件事）。
    """
    full = source.get("fulltext")
    if not (isinstance(full, Mapping) and _text_of(full.get("status")) == "ok"):
        return [], "fulltext_not_ok"
    ref = full.get("text_ref")
    if isinstance(ref, Mapping) and ref.get("path"):
        key = str(ref.get("path"))
        if cache is not None and key in cache:
            return cache[key]
        pages, problem = _fts.load(ref)
        if cache is not None:
            cache[key] = (pages, problem)
        return pages, problem
    inline = [str(p) for p in (full.get("text_pages") or [])]
    if inline:
        return inline, ""
    return [], "fulltext_no_text"


def _pages_of(source: Mapping[str, Any],
              cache: dict[str, tuple[list[str], str]] | None = None) -> tuple[list[str], str, str]:
    """这条来源能拿来做逐字比对的文本：返回 `(逐页文本, 级别, 为什么是这个级别)`。

    优先全文：全文逐字存在是比摘要更强的证据，而"有全文时还只查摘要"会让
    报告里的 `fulltext` 级永远为空，读者据此以为全文没有一句话对得上。

    降级到摘要时，理由必须说清是哪一种降级：引用坏了（`text_ref` 取不到）与
    "这篇没有全文"是两句话 —— 把前者写成后者就是不实陈述（`draft/30` §T0-3）。
    """
    pages, problem = _fulltext_pages(source, cache)
    if pages:
        return pages, "fulltext", "用的是已获取的全文逐页文本"
    abstract = _text_of(source.get("abstract"))
    if abstract:
        if problem in ("", "fulltext_not_ok", "fulltext_no_text"):
            return [abstract], "abstract", "只拿到摘要（这篇没有可用的全文文本）"
        return [abstract], "abstract", f"全文逐页文本取不到（{problem}）⇒ 只到摘要级"
    if problem in ("", "fulltext_not_ok", "fulltext_no_text"):
        return [], "abstract", "这条来源没有任何可比的文本"
    return [], "abstract", f"全文逐页文本取不到（{problem}）且这条来源没有摘要"


def _to_int(value: Any) -> int | None:
    """把值收成 int；收不了就 None（绝不猜一个页码填进去）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _locate(source: Mapping[str, Any], level: str, quote: str, matched_page: Any) -> dict:
    """算出这条引文实际命中的位置（页码或字符偏移）。

    为什么要有它：`verified` 只回答"在不在"，而"在哪"是它能不能被复核的全部内容。
    全文级给页号（第几页）；摘要级给页号 1 与字符偏移 —— 摘要只有一个文本块，
    偏移才是能被人核对的位置。取不到就如实返回 `{kind: "unknown"}`：编一个页码
    比不给更坏，因为它看起来像查过。
    """
    page = _to_int(matched_page) or 1
    if level == "fulltext":
        return {"kind": "page", "page": page}
    text = _text_of(source.get("abstract"))
    offset = text.find(quote) if text and quote else -1
    locator: dict = {"kind": "char_offset", "page": page}
    if offset >= 0:
        locator["start"] = offset
        locator["end"] = offset + len(quote)
    else:
        # 命中在规范化后的文本上、原始摘要里找不到（大小写/空白被规整过）：
        # 这就是"位置没算成"，不许写一个 0 当偏移。
        locator["kind"] = "unknown"
        locator["why"] = "规范化后命中，无法在原始摘要里算出字符偏移"
    return locator


def _check_quote_against(pages: Sequence[str], quote: str, fn: QuoteFn,
                         *, window_kind: str) -> tuple[Any, str]:
    """对一段文本跑一次回验，返回 `(回验结果, 异常描述)`；异常不冒泡。"""
    try:
        return _check_one(_PagesDoc(pages=list(pages)), quote, fn,
                          window_kind=window_kind), ""
    except Exception as exc:  # 回验实现抛异常 = 没查成，绝不许折成 not_found
        return None, f"{type(exc).__name__}: {exc}"


def _check_quote_levels(source: Mapping[str, Any], quote: str,
                        fn: QuoteFn, *,
                        cache: dict[str, tuple[list[str], str]] | None = None,
                        ) -> tuple[Any, str, dict, str, bool]:
    """对一条来源按"全文优先"回验，返回 `(结果, 异常, locator, 级别, 有可比文本吗)`。

    两级各查一次是刻意的：全文命中就给 `fulltext`，全文没命中而摘要命中就给
    `abstract`。「只存在于摘要、正文里没有的引文必须落到 `abstract`」 ——
    把它标成 `fulltext` 就是让读者以为正文里有这句话，而正文我们其实查过、没有。

    ## 第五个返回值为什么必须存在（`E-12`）

    此前"这条来源根本没有可比文本"与"回验器拒绝判定"都折成 `(None, "", {}, level)` 同一个形态，
    于是 `verify_claims` 在"声明的来源没有文本"时直接落 `unknown` 并 `break` ——
    其余"有文本"的来源根本没被查过。方向是 fail-closed（不会假通过），
    但"能查成的"被写成"没查成"，台账还退化成字面量 `reason='unknown'`。
    所以这里显式区分：`False` = 这条来源没有可比文本（调用方应继续查别的来源），
    `True` = 真的比对过（结果可能是 verified / not_found / 拒绝判定）。

    ## `False` 只剩一条路（`R2-AN-5`）

    上面那个区分曾经漏了一半："有全文、没摘要、全文比过了但没命中"
    这一形态（`:1155` 那一支）也被返回成 `False`，于是调用方写下
    "一条来源都没比对过 / `no_comparable_text_in_any_source`" ——
    判决与理由都是不实陈述（全文真的比过，结论是"没找到"，
    方向虽然保守，但硬事实被丢掉了，一个假理由进了真库）。
    现在那一支返回那次全文比对的结果（`comparable=True`、级别 `fulltext`），
    `False` 因此恢复本条 docstring 的语义：它是 `:1139` 那条真"没有可比文本"。
    """
    text_pages, level, _why = _pages_of(source, cache)
    if not text_pages:
        return None, "", {}, level, False

    # 全文那次比对的结果（没跑过全文就是 `None`）。下面"这条来源没有摘要"
    # 那一支要如实返回这一次的读数，而不是把它折成"没有可比文本"。
    full_outcome: Any = None
    # 全文文本只从这一处取：内联的 `text_pages` 与引用式的 `text_ref` 都由
    # `_fulltext_pages` 解析（引用坏了就返回空 + 问题串，于是这里自然跳过全文那次比对，
    # 落到摘要级，并把问题串留给 `verify_claims` 去计数与写理由）。
    full_pages, _ft_problem = _fulltext_pages(source, cache)
    if full_pages:
        outcome, failure = _check_quote_against(full_pages, quote, fn, window_kind="fulltext")
        if failure:
            return None, failure, {}, "fulltext", True
        verified, reason = _read_verdict(outcome)
        if verified is True:
            return outcome, "", _locate(source, "fulltext", quote,
                                        _field(outcome, "matched_page", 1)), "fulltext", True
        if verified is None:
            return outcome, "", {}, "fulltext", True
        # 只剩 `verified is False` 一种出路：全文比过了、逐字没找到。
        # 留一份读数，供下面"没有摘要"那一支如实返回（`R2-AN-5`）。
        full_outcome = outcome

    abstract = _text_of(source.get("abstract"))
    if not abstract:
        if full_outcome is None:
            # 不可达（如实登记，不是"在守某个形态"）：`text_pages` 非空而摘要为空
            # ⇒ 那些文本只可能来自全文那次比对（`_pages_of` 只从全文或摘要取文本），
            # 而那条路上的三种出路都已经在上面 return 了。
            # 留着这一支是为了"以后改了 `_pages_of`"时不会静默地把一次真比对
            # 说成"没有可比文本"：它退回 fail-closed 的 `unknown`。
            return None, "", {}, level, False
        # `R2-AN-5`：全文比过了、逐字没找到、而这条来源没有摘要。
        # 判决与理由必须是那次比对的读数（`not_found` + 回验器给的真理由），
        # 不许折成 `comparable=False` —— 调用方会把它读成"这条来源没有可比文本"，
        # 于是台账写下"一条来源都没比对过 / 没查成"，而事实是比过了、没找到。
        # 这样 `comparable=False` 也恢复它 docstring 里的语义：只有上面
        # `:1139`（以及这个不可达分支）那条真"没有可比文本"的路。
        return full_outcome, "", {}, "fulltext", True
    outcome, failure = _check_quote_against([abstract], quote, fn, window_kind="abstract")
    if failure:
        return None, failure, {}, "abstract", True
    verified, _reason = _read_verdict(outcome)
    if verified is True:
        return outcome, "", _locate(source, "abstract", quote,
                                    _field(outcome, "matched_page", 1)), "abstract", True
    return outcome, "", {}, "abstract", True


def _normalize_claim(claim: Any) -> dict:
    """把一条断言归一成 `{"text", "quote", "evidence_source"}`。"""
    if isinstance(claim, Mapping):
        text = _text_of(claim.get("text") or claim.get("claim"))
        quote = _text_of(claim.get("quote"))
        declared = _text_of(claim.get("evidence_source"))
    else:
        text, quote, declared = _text_of(claim), "", ""
    return {"text": text, "quote": quote, "evidence_source": declared}


def verify_claims(claims: Sequence[Any], sources: Sequence[Mapping[str, Any]], *,
                  quote_fn: QuoteFn | None = None) -> dict:
    """把每条断言与来源原文逐字比对，返回带判决的台账。

    `quote_fn` 是唯一的测试接缝：生产为 `None`（调用禁改区里的
    `quoteverify.check_quote`，签名与它逐字一致），测试注入假函数。

    顺序上有一条硬规则：先判「有没有可比的原文」，再判「引文在不在」。
    手上没有任何来源文本时一律 `unknown`（没查成），绝不落 `not_found` ——
    否则"没查成"会被读成"模型编了引文"，而那是把一次基础设施故障
    记成一次学术不端。反过来，材料在手上、逐字比对过、没找到，才是 `not_found`。

    声明了 `evidence_source` 的断言先查它声明的来源；没命中时继续查其余来源，
    并把真正命中的那一条写回 `evidence_source`（引文逐字存在是硬事实，
    模型把出处记错是另一件事，不该由"记错出处"来决定引文算不算存在）。

    每条 `verified` 都带 `level`（`abstract` / `fulltext`）与 `locator`：
    有全文时优先用全文逐页文本，只有摘要可用时才落 `abstract`。
    只存在于摘要、正文里没有的引文「永远只能是 `abstract` 级」 ——
    把它标成全文级，就是让读者以为正文里有这句话。
    """
    ordered = [_normalize_claim(c) for c in claims]
    # 2026-10-17（IO #7）：`evidence.json` 可能被写坏（`sources: [null, {...}]`）——
    # 原来假定每条都是 Mapping，一条 null 就让整次回验抛 AttributeError。
    sources = [s for s in sources if isinstance(s, Mapping)]
    index = {_text_of(s.get("source_id")): s for s in sources if _text_of(s.get("source_id"))}
    # 一次回验内的局部缓存（键 = `text_ref.path`）：同一份 store 文件不该被解析七遍。
    # 刻意不做模块级缓存 —— 那会跨调用掩盖"文件被改"（`draft/30` §T0-3）。
    cache: dict[str, tuple[list[str], str]] = {}
    # "有可比文本"包含两种：摘要，或已获取到的全文。只数摘要会让"有全文的来源"
    # 被误判成没有可比原文，把一次明明能查的回验报成 unknown。
    with_text = [s for s in sources if _pages_of(s, cache)[0]]
    with_fulltext = [s for s in sources if _pages_of(s, cache)[1] == "fulltext"]

    fn = quote_fn if quote_fn is not None else _default_quote_fn()
    ledger: list[dict] = []
    failure = ""

    for claim in ordered:
        row = {
            "text": claim["text"],
            "quote": claim["quote"],
            "verdict": "unknown",
            "evidence_source": "",
            "verified": False,
            "reason": "",
            "checked": False,
            # 判决到达的级别与命中位置。没有 verified 就没有级别：
            # 给一条没通过的判决标"全文级"会让人以为正文里有这句话。
            "level": "",
            "locator": {},
        }
        if not claim["quote"]:
            row.update(verdict="known_unverifiable", reason="no_quote",
                       checked=False)
            ledger.append(row)
            continue
        if not with_text:
            row.update(verdict="unknown", reason="no_source_text",
                       checked=False)
            ledger.append(row)
            continue

        declared = claim["evidence_source"]
        candidates = ([index[declared]] if declared in index else []) + \
            [s for s in with_text if s is not index.get(declared)]
        not_found_reason = ""
        any_comparable = False
        for source in candidates:
            outcome, why, locator, level, comparable = _check_quote_levels(
                source, claim["quote"], fn, cache=cache)
            if why:
                failure = why
                row.update(verdict="unknown", reason=f"quote_fn_failed:{failure}",
                           checked=False)
                break
            if not comparable:
                # 这条来源没有任何可比的文本 ⇒ 继续查其余来源（`E-12`）。
                # 不 break 的理由：docstring 承诺"没命中时继续查其余来源"，
                # 而"这条来源没文本"正是"没命中"的一种；break 会把明明能查成的
                # 引文写成"没查成"，并把真原因丢掉。
                continue
            any_comparable = True
            verified, verdict_reason = _read_verdict(outcome)
            if verified is True:
                row.update(verdict="verified", verified=True,
                           evidence_source=_text_of(source.get("source_id")),
                           reason=verdict_reason or "substring_match", checked=True,
                           level=level, locator=locator)
                break
            if verified is None:
                # 第二项在这里一定非空：`_read_verdict` 对 `verified is None`
                # 已经补了 `"verifier_refused_to_judge"`（`R2-AN-6`）。
                # 这里不再写 `or "verifier_refused_to_judge"` —— 那会是第二份
                # 同义定义，而且永远走不到（判据见 `_read_verdict` 的 docstring）。
                row.update(verdict="unknown", reason=verdict_reason,
                           evidence_source=_text_of(source.get("source_id")),
                           checked=False)
                break
            not_found_reason = not_found_reason or verdict_reason or "not_found"
        if row["verdict"] == "unknown" and row["reason"] == "":
            if any_comparable:
                # 至少有一条来源真的比对过、逐字都没找到 ⇒ 这才是 not_found（编造的引文落这里）。
                row.update(verdict="not_found", reason=not_found_reason or "not_found",
                           evidence_source=declared, checked=True)
            else:
                # 防御性收口（`R2-AN-5` 之后这里不可达）：`candidates` 全部取自
                # `with_text`（`_pages_of` 拿得到文本的来源），而 `_check_quote_levels`
                # 现在只在真"没有可比文本"时返回 `comparable=False` ⇒ 走到这里时
                # `any_comparable` 必为真。留着它不是为了守某个已知形态，
                # 而是因为"没查成"绝不能落 `not_found`：万一将来判据漂了，
                # 也必须 fail-closed 地记成 `unknown`，而不是把基础设施故障
                # 读成学术不端（`E-12`）。
                row.update(verdict="unknown", reason="no_comparable_text_in_any_source",
                           evidence_source=declared, checked=False)
        ledger.append(row)

    counts = {"total": len(ledger)}
    for v in VERDICTS:
        counts[v] = sum(1 for r in ledger if r["verdict"] == v)
    counts["unverified"] = counts["total"] - counts["verified"]
    # 两级的通过条数分开数：合成一个"通过"数字正是本层最要防的那种读法 ——
    # 读者会把它当成"全文都对得上"，而其中可能有几条只对上了摘要。
    for level in EVIDENCE_LEVELS:
        counts[f"verified_{level}"] = sum(
            1 for r in ledger if r["verdict"] == "verified" and r["level"] == level
        )

    levels_reached = sorted({r["level"] for r in ledger if r["verdict"] == "verified"})

    # 坏引用（`draft/30` §T0-4）：全文逐页文本取不到的那些来源必须被点名计数。
    # 否则"降级到摘要级"会被读成"这篇没有全文"—— 那是不实陈述，而且它会把
    # 一次可修的存储缺陷伪装成文献的属性。
    broken_refs = sorted({p for (_pages, p) in cache.values()
                          if p not in ("", "fulltext_not_ok", "fulltext_no_text")})
    if broken_refs:
        counts["fulltext_text_unavailable"] = len(broken_refs)

    if failure:
        checked, reason = False, f"回验函数抛异常 ⇒ 本次部分断言没查成（{failure}）"
    elif not sources:
        checked, reason = False, "没有任何来源 ⇒ 本次没有可回验的原文（不是'引文都不存在'）"
    elif not with_text:
        checked, reason = False, "来源都没有任何可比文本（既没有摘要也没有全文）⇒ 本次没有可逐字比对的原文"
    else:
        reached = "／".join(levels_reached) if levels_reached else "无（没有一条通过）"
        # 这两句话就是"不许让读者以为全文验过而实际只验了摘要"的载体，
        # 所以按"手上到底有没有全文"分三种说法，而不是笼统一句"已回验"。
        if counts.get("verified_fulltext"):
            scope = "有断言在全文逐页文本里命中"
        elif broken_refs:
            scope = (f"其中 {len(broken_refs)} 条来源声称拿到了全文，但逐页文本引用取不到 ⇒ "
                     "这几条只按摘要级核过（不是'这篇没有全文'）")
        elif with_fulltext:
            scope = ("有全文文本，但没有任何一条通过全文比对；"
                     "本次通过的那些只到摘要级")
        else:
            scope = "本次来源里没有可用的全文文本，回验只到达摘要级"
        checked = True
        reason = (f"对 {counts['total']} 条断言在 {len(with_text)} 条来源文本上做了逐字比对；"
                  f"本次回验到达的级别：{reached}（{scope}）")
        if broken_refs:
            reason += "；取不到的理由逐字如下：" + "；".join(broken_refs)

    return {
        "claims": ledger,
        "counts": counts,
        "check": {
            "checked": checked,
            "reason": reason,
            #: 写进产物里的实现名：换掉回验实现必须能从台账里看出来。
            "quote_fn": "injected" if quote_fn is not None else "quoteverify.check_quote",
            "sources_with_text": len(with_text),
            "sources_with_fulltext": len(with_fulltext),
            #: 读者必须能一眼看到"这次到底验到了哪一层"，而不用逐条读台账。
            "levels_reached": levels_reached,
            #: 全文引用取不到的那些来源（`draft/30` §T0-4）：键只在真出问题时出现 ——
            #: 一个常驻的空列表会让读者以为"这一栏永远是空的、所以没问题"。
            **({"fulltext_text_unavailable": broken_refs} if broken_refs else {}),
        },
        "checked": checked,
        "reason": reason,
    }


def _default_quote_fn() -> QuoteFn:
    """生产回验：禁改区里的 `quoteverify.check_quote`（唯一权威实现）。

    为什么惰性 import：本模块要在没有 `dedup`/`extract` 链条的环境里
    也能被 import（`retrieve` 的部分不依赖它）；缺了它必须报成"没查成"，
    所以这里让 ImportError 自然冒泡到调用方 —— `verify_claims` 会把它
    翻成 `unknown` 而不是 `not_found`。
    """
    from .quoteverify import check_quote

    return check_quote


# ---------------------------------------------------------------------- 自检


def _fake_search(items: Sequence[Any]) -> SearchFn:
    """造一个固定条目的检索接缝（自检与测试共用同一种造法）。"""

    def _s(topic: str, *, limit: int, timeout_sec: float) -> Sequence[Any]:
        return list(items)[: max(1, int(limit))]

    return _s


def selftest() -> int:
    """离线自检：四态检索、正控与负控、`unknown` 与 `not_found` 不混。

    为什么要有它：本模块的两条判据（"没查成"不许折叠、"编造的引文必须 not_found"）
    都是负向的 —— 它们的存在只能靠"故意造一个坏输入看它会不会被放过"来证明。
    自检把这两条负控放在模块自己身上，改坏任何一条都会在 `python -m agentflow.evidence`
    上立刻现形，而不必等端到端用例。
    """
    problems: list[str] = []
    quote = "the commutative law holds"
    item = {"source": "fake", "title": "Commutative laws", "doi": "10.1000/x",
            "year": 1930, "abstract": f"An abelian group is a group in which {quote}."}

    got = retrieve("阿贝尔群", search_fn=_fake_search([item]), now="T")
    if got["status"] != "ok" or got["checked"] is not True or len(got["sources"]) != 1:
        problems.append(f"ok 路径不对：{got['status']} / {len(got['sources'])}")
    if not got["sources"][0]["provenance"].get("query"):
        problems.append("来源缺 provenance（查询串为空）")

    empty = retrieve("阿贝尔群", search_fn=_fake_search([]), now="T")
    if empty["status"] != "no_results" or empty["checked"] is not True:
        problems.append(f"no_results 路径不对：{empty}")

    def _boom(topic: str, *, limit: int, timeout_sec: float):
        raise RuntimeError("network down")

    failed = retrieve("阿贝尔群", search_fn=_boom, now="T")
    if failed["status"] != "retrieval_failed" or failed["checked"] is not False:
        problems.append(f"retrieval_failed 必须 checked=False：{failed}")

    def _unconfigured(topic: str, *, limit: int, timeout_sec: float):
        raise RetrievalNotConfigured("没有检索器")

    nc = retrieve("阿贝尔群", search_fn=_unconfigured, now="T")
    if nc["status"] != "not_configured" or nc["checked"] is not False:
        problems.append(f"not_configured 路径不对：{nc}")

    no_source = retrieve("阿贝尔群", search_fn=_fake_search([{"title": "无出处"}]), now="T")
    if no_source["status"] != "no_results" or not no_source["rejected"]:
        problems.append(f"缺来源的条目必须被拒收并留痕：{no_source}")

    v = verify_claims([{"text": "它是交换群", "quote": quote}], got["sources"])
    if v["claims"][0]["verdict"] != "verified" or v["claims"][0]["evidence_source"] != "S1":
        problems.append(f"正控失败：{v['claims'][0]}")

    bad = verify_claims([{"text": "它是交换群", "quote": "这句话在材料里不存在"}], got["sources"])
    if bad["claims"][0]["verdict"] != "not_found" or bad["claims"][0]["verified"]:
        problems.append(f"负控失败（编造的引文必须 not_found）：{bad['claims'][0]}")

    blind = verify_claims([{"text": "它是交换群", "quote": quote}], [])
    if blind["claims"][0]["verdict"] != "unknown":
        problems.append(f"没有来源时必须 unknown 而不是 not_found：{blind['claims'][0]}")

    noquote = verify_claims([{"text": "综述性结论", "quote": ""}], got["sources"])
    if noquote["claims"][0]["verdict"] != "known_unverifiable":
        problems.append(f"没有引文时必须 known_unverifiable：{noquote['claims'][0]}")

    # 多源：一源失败一源成功 ⇒ 整体必须仍是 ok（单源失败不许让整体失败）。
    one_bad = retrieve("阿贝尔群", now="T", search_fn={
        "bad": _boom, "good": _fake_search([{**item, "source": "good"}])})
    if one_bad["status"] != "ok" or one_bad["sources_status"] != {"bad": "failed", "good": "ok"}:
        problems.append(f"单源失败不许让整体失败：{one_bad['status']} / {one_bad['sources_status']}")

    all_bad = retrieve("阿贝尔群", now="T", search_fn={"a": _boom, "b": _boom})
    if all_bad["status"] != "retrieval_failed":
        problems.append(f"全失败才 retrieval_failed：{all_bad['status']}")

    # 全文级的负控：只在摘要里存在的引文，只许标 abstract，绝不许标 fulltext。
    ft_source = {**got["sources"][0], "fulltext": {
        "status": "ok", "text": "Something else entirely.", "text_pages": ["Something else entirely."]}}
    only_abs = verify_claims([{"text": "它是交换群", "quote": quote}], [ft_source])
    if only_abs["claims"][0]["level"] != "abstract":
        problems.append(f"只存在于摘要的引文必须标 abstract：{only_abs['claims'][0]}")

    shadow = {**ft_source, "fulltext": {
        "status": "ok", "text": f"Text on page one. {quote}",
        "text_pages": ["Text on page one.", f"In the body, {quote}."]}}
    in_body = verify_claims([{"text": "它是交换群", "quote": quote}], [shadow])
    if in_body["claims"][0]["level"] != "fulltext" or \
            in_body["claims"][0]["locator"].get("page") != 2:
        problems.append(f"正文里有的引文必须标 fulltext 并给页号：{in_body['claims'][0]}")

    for p in problems:
        print(f"  [FAIL] {p}")
    print(f"[evidence] 自检：检索={got['status']}/{empty['status']}/{failed['status']}/"
          f"{nc['status']} / 多源={one_bad['status']}({one_bad['sources_status']})/"
          f"{all_bad['status']} / 回验={v['claims'][0]['verdict']}/{bad['claims'][0]['verdict']}/"
          f"{blind['claims'][0]['verdict']} / 级别="
          f"{only_abs['claims'][0]['level']}/{in_body['claims'][0]['level']}")
    if problems:
        return 1
    print("[evidence] 四态检索、多源合并、正控、负控、级别（abstract/fulltext）的分界都对")
    return 0


def evidence_main(argv: Any = None) -> int:
    """入口：目前只有自检。刻意不叫 `main`（`cli.main` 才是对外的唯一命令入口）。"""
    return selftest()


if __name__ == "__main__":
    raise SystemExit(evidence_main())
