"""证据层：先检索、再逐字回验 —— 让报告里的每条结论都落在某段真实原文上。

## 为什么要有这一层

本轮之前，`run_topic` 把模型答复直接当成结论落进 `claims.json` 与报告：
模型说"某定理在 1930 年被证明"，产物里就写着这句话，没有任何外部依据。
"看起来有据"与"真有据"是两件事，而它们之间的缺口恰恰不在任何一段代码里 ——
所以缺口不会报错，只会让报告变得不可复核。

这一层把那句话变成两道可判定的门：

1. 模型只能在 `retrieve` 拿回来的材料里作答（材料为空时不许给结论）；
2. 每条结论必须附一条从材料里逐字复制的引文，且该引文要被 `verify_claims`
   在来源文本里逐字找到 —— 找不到就是 `not_found`（编造的引文必须落到这里）。

## 检索的三态（本模块的第一条纪律）

`retrieve` 的结局有四种，`checked` 只对前两种为真：

- `ok`：查到了至少一条带 provenance 的来源；
- `no_results`：查过了，但一条可用来源都没有（含"查到条目却全部缺来源信息而被拒收"）；
- `retrieval_failed`：查了，但检索器报错/返回了无法解析的东西 —— 这是"没查成"；
- `not_configured`：压根没有发起检索（没有检索器可造、主题为空、或上游决定不查）。

把 `retrieval_failed` 折叠成 `no_results`，会让"网络断了"看起来像"这个主题没有文献"；
反过来折叠，会让"确实没有文献"看起来像故障。两种读法都会让产物撒谎。

### 多源：逐源记状态，单源失败不许让整体失败

一次检索可以同时问多个库（生产缺省 OpenAlex + Crossref）。逐源状态写进
`sources_status`，取值只有三种：

- `ok`：这个源返回了至少一条可归一成来源的条目；
- `no_results`：这个源查过了、但一条可用条目都没有；
- `failed`：这个源查不成（异常、不可构造、返回了无法解析的东西）。

整体状态由逐源状态推出，判据只有一处（`_status_of_sources`）：
有任一源 `ok` ⇒ `ok`；一个 `ok` 都没有但有源 `no_results` ⇒ `no_results`；
全部 `failed` ⇒ `retrieval_failed`。为什么必须这样推而不是"取最坏的一个"：
把某个库的一次 429 当成整次检索失败，会把手上已有的材料一并丢掉 ——
而材料是这一层唯一的产出，丢掉它等于让报告退化成模型自说自话。

跨源同一篇文献按 DOI 归一化去重（调用禁改区 `dedup.normalize_doi`，不另写第二份规则），
合并后的条目写明它来自哪些源（`providers`）。为什么必须写下来：一条来源被两个库
同时证实时，它与"只有一个库说过"在可信度上不是一回事，而两者在旧结构里长得一样。

## 逐字回验的四种判决（第二条纪律）

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

## 拆分与判决分处两层（本层只做判决）

"把一段答复拆成原子断言"的判据在 `claims` 模块里（`split_claims`），
本模块只做判决（`verify_claims`）与二者的合成入口（`claims.ledger_rows`）。
为什么拆开放：拆分要在没有来源文本时也能跑（它判的是"这段话里有几条断言"），
而判决必须有来源才能跑（它判的是"这条断言的引文在不在"）。
两者合在一个函数里，会让"没有材料"顺带把拆分也一起停掉 ——
而"我们拆出了 12 条，只是没有材料可回验"与"我们没拆"是两句不同的话。

`parse_claims` 因此变成对 `claims.parse_claims` 的转发（同名入口保留是为了
既有调用方的签名不变），本模块不再持有第二套切分容错。

## 测试接缝只有三个（每个动作一个）

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

__all__ = [
    "ACQUIRE_STATUSES",
    "CHECKED_STATUSES",
    "EVIDENCE_LEVELS",
    "RETRIEVAL_STATUSES",
    "SOURCE_STATUSES",
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
SOURCE_STATUSES: tuple[str, ...] = ("ok", "no_results", "failed")

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

    # 用 `precise` 而不是 `topical`：实测（2026-09，本机联网）`topical` 的两路查询
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


def _retrieve_one(name: str, fn: SearchFn, *, query: str, limit: int,
                  timeout_sec: float, retrieved_at: str) -> tuple[str, list[dict], list[dict], str]:
    """问一个源，返回 `(源名, 归一后的来源, 拒收, 失败原因)`。

    失败原因非空 ⇒ 这个源算 `failed`。这里刻意把"源报错"与"源没结果"分成两个
    返回值，而不是靠 `len(items) == 0` 去猜：一个源在异常之后也可能返回空列表，
    而"它坏了"与"它说没有"在产物里必须是两句话。
    """
    try:
        items = fn(query, limit=int(limit), timeout_sec=float(timeout_sec))
    except RetrievalNotConfigured as exc:
        return name, [], [], f"没配置（{exc}）"
    except Exception as exc:  # 跨库异常无法统一归一，这里必须翻成三态而不是冒泡
        return name, [], [], f"{type(exc).__name__}: {exc}"

    if items is None or isinstance(items, (str, bytes, Mapping)):
        return name, [], [], (f"返回了 {type(items).__name__} 而不是条目列表 ⇒ "
                              "无法判断是没查到还是坏掉了")

    sources, rejected = _sources_from_items(
        list(items)[: max(1, int(limit))], source_name=name,
        query=query, retrieved_at=retrieved_at,
    )
    return name, sources, rejected, ""

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
    _name, sources, rejected, failure = _retrieve_one(
        "", fn, query=query, limit=wanted, timeout_sec=float(timeout_sec),
        retrieved_at=retrieved_at,
    )
    if failure:
        status = "not_configured" if failure.startswith("没配置") else "retrieval_failed"
        return _result(status, [], f"检索失败（{failure}）" if status == "retrieval_failed"
                       else failure, query=query, retrieved_at=retrieved_at, limit=limit)
    if not sources:
        why = ("查过了，但这个主题一条文献都没有返回"
               if not rejected
               else f"查到 {len(rejected)} 条，但全部缺来源信息（无一可追溯到具体库与查询）⇒ 全部拒收")
        return _result("no_results", [], why, query=query, retrieved_at=retrieved_at,
                       rejected=rejected, limit=limit)

    return _result("ok", sources, f"查到 {len(sources)} 条可用来源", query=query,
                   retrieved_at=retrieved_at, rejected=rejected, limit=limit)


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
        got_name, sources, dropped, failure = _retrieve_one(
            source_name, fns[name], query=query, limit=per_source,
            timeout_sec=timeout_sec, retrieved_at=retrieved_at,
        )
        if failure:
            sources_status[source_name] = "failed"
        else:
            sources_status[source_name] = "ok" if sources else "no_results"
        detail.append({
            "source": source_name,
            "status": sources_status[source_name],
            "count": len(sources),
            "rejected": len(dropped),
            "reason": failure or ("查到条目" if sources else "查过了、没有可用条目"),
        })
        rejected.extend(dropped)
        groups.append((got_name, sources))

    merged, conflicts = _merge_across_sources(groups, query=query, retrieved_at=retrieved_at)
    overall = _status_of_sources(sources_status)
    if overall == "ok":
        reason = f"查到 {len(merged)} 条可用来源（去重后；咨询 {len(fns)} 个源）"
    elif overall == "no_results":
        reason = f"咨询了 {len(fns)} 个源，全部没有可用条目（含被拒收的）"
    else:
        why = "；".join(f"{d['source']}: {d['reason']}" for d in detail if d["status"] == "failed")
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
                 dest_dir: Path, max_bytes: int) -> None:
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

    source["fulltext"] = {
        "status": "ok",
        "url": url,
        "path": path,
        "sha256": _text_of(_field(fetched, "sha256")) or _sha256_file(path),
        "bytes": bytes_on_disk,
        "pages": len(pages),
        "backend": _text_of(_field(doc, "source_kind")) or "unknown",
        "encoding": _field(doc, "encoding"),
        # 抽取出来的逐页文本：回验要拿它逐字比对，所以它就是证据本体，不是缓存。
        "text": "\n".join(pages),
        "text_pages": pages,
        "download_warning": error,
        "reason": f"抽到 {len(pages)} 页文本（后端 {_text_of(_field(doc, 'source_kind')) or 'unknown'}）",
    }


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
                     only_source_ids: Sequence[str] | None = None) -> dict:
    """给检索到的来源逐条拿全文，六态化写回每条的 `fulltext` 字段。

    六态与各自的理由字段是这一层的全部内容：`ok` / `no_pdf`（没有可下载的开放全文）/
    `download_failed` / `no_text_layer`（是扫描件）/ `extract_failed` / `not_configured`。
    为什么"没有 PDF"与"下载失败"必须是两句话：前者是这篇文献的客观属性（要换文献），
    后者是基础设施问题（要重试），而把两者折叠成一个"失败"会让人对整批来源做一个
    错误的动作。 `not_configured` 覆盖两种"没做"：压根没有下载器/抽取器可造，
    以及超出本次 `limit` 而「没有发起」下载 —— 后者绝不许写成 `no_pdf`。

    `fetch_fn` / `extract_fn` 是唯一的生产接线点，两者都为 `None` 时走禁改区里的
    `fetch.default_downloader` 与 `extract.extract_text`；测试注入假函数。

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
            _acquire_one(source, fetch_impl, extract_impl, dest_dir=out_dir, max_bytes=max_bytes)
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
    """从回验结果里读出三态与原因（同时接受 `QuoteCheck` 与同形 dict）。"""
    if isinstance(result, Mapping):
        verified = result.get("verified")
        reason = _text_of(result.get("reason"))
    else:
        verified = getattr(result, "verified", None)
        reason = _text_of(getattr(result, "reason", ""))
    if verified is None:
        return None, reason or "unknown"
    return bool(verified), reason


def _pages_of(source: Mapping[str, Any]) -> tuple[list[str], str, str]:
    """这条来源能拿来做逐字比对的文本：返回 `(逐页文本, 级别, 为什么是这个级别)`。

    优先全文：全文逐字存在是比摘要更强的证据，而"有全文时还只查摘要"会让
    报告里的 `fulltext` 级永远为空，读者据此以为全文没有一句话对得上。
    """
    full = source.get("fulltext")
    if isinstance(full, Mapping) and _text_of(full.get("status")) == "ok":
        text_pages = [str(p) for p in (full.get("text_pages") or [])]
        if text_pages:
            return text_pages, "fulltext", "用的是已获取的全文逐页文本"
    abstract = _text_of(source.get("abstract"))
    if abstract:
        return [abstract], "abstract", "只拿到摘要（这篇没有可用的全文文本）"
    return [], "abstract", "这条来源没有任何可比的文本"


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
                        fn: QuoteFn) -> tuple[Any, str, dict, str]:
    """对一条来源按"全文优先"回验，返回 `(结果, 异常, locator, 级别)`。

    两级各查一次是刻意的：全文命中就给 `fulltext`，全文没命中而摘要命中就给
    `abstract`。「只存在于摘要、正文里没有的引文必须落到 `abstract`」 ——
    把它标成 `fulltext` 就是让读者以为正文里有这句话，而正文我们其实查过、没有。
    """
    text_pages, level, _why = _pages_of(source)
    if not text_pages:
        return None, "", {}, level

    full = source.get("fulltext")
    if isinstance(full, Mapping) and _text_of(full.get("status")) == "ok":
        full_pages = [str(p) for p in (full.get("text_pages") or [])]
        outcome, failure = _check_quote_against(full_pages, quote, fn, window_kind="fulltext")
        if failure:
            return None, failure, {}, "fulltext"
        verified, reason = _read_verdict(outcome)
        if verified is True:
            return outcome, "", _locate(source, "fulltext", quote,
                                        _field(outcome, "matched_page", 1)), "fulltext"
        if verified is None:
            return outcome, "", {}, "fulltext"

    abstract = _text_of(source.get("abstract"))
    if not abstract:
        return None, "", {}, "abstract"
    outcome, failure = _check_quote_against([abstract], quote, fn, window_kind="abstract")
    if failure:
        return None, failure, {}, "abstract"
    verified, _reason = _read_verdict(outcome)
    if verified is True:
        return outcome, "", _locate(source, "abstract", quote,
                                    _field(outcome, "matched_page", 1)), "abstract"
    return outcome, "", {}, "abstract"


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
    index = {_text_of(s.get("source_id")): s for s in sources if _text_of(s.get("source_id"))}
    # "有可比文本"包含两种：摘要，或已获取到的全文。只数摘要会让"有全文的来源"
    # 被误判成没有可比原文，把一次明明能查的回验报成 unknown。
    with_text = [s for s in sources if _pages_of(s)[0]]
    with_fulltext = [s for s in sources if _pages_of(s)[1] == "fulltext"]

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
        for source in candidates:
            outcome, why, locator, level = _check_quote_levels(source, claim["quote"], fn)
            if why:
                failure = why
                row.update(verdict="unknown", reason=f"quote_fn_failed:{failure}",
                           checked=False)
                break
            verified, verdict_reason = _read_verdict(outcome)
            if verified is True:
                row.update(verdict="verified", verified=True,
                           evidence_source=_text_of(source.get("source_id")),
                           reason=verdict_reason or "substring_match", checked=True,
                           level=level, locator=locator)
                break
            if verified is None:
                row.update(verdict="unknown",
                           reason=verdict_reason or "verifier_refused_to_judge",
                           evidence_source=_text_of(source.get("source_id")),
                           checked=False)
                break
            not_found_reason = not_found_reason or verdict_reason or "not_found"
        if row["verdict"] == "unknown" and row["reason"] == "":
            # 所有来源都比对过、逐字都没找到 ⇒ 这才是 not_found（编造的引文落在这里）。
            row.update(verdict="not_found", reason=not_found_reason or "not_found",
                       evidence_source=declared, checked=True)
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
        elif with_fulltext:
            scope = ("有全文文本，但没有任何一条通过全文比对；"
                     "本次通过的那些只到摘要级")
        else:
            scope = "本次来源里没有可用的全文文本，回验只到达摘要级"
        checked = True
        reason = (f"对 {counts['total']} 条断言在 {len(with_text)} 条来源文本上做了逐字比对；"
                  f"本次回验到达的级别：{reached}（{scope}）")

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
