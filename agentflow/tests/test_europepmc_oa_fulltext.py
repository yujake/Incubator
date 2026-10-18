# -*- coding: utf-8 -*-
"""Europe PMC 的 OA 全文取法与 JATS XML 抽取 —— 2026-10-15 那两处改动的钉子。

## 钉的是哪两件事（同一条链的两半，缺一条就白改）

`providers._europepmc_urls` 此前把 Europe PMC **自己在 `fullTextUrlList` 里报的**
`https://europepmc.org/articles/PMC…?pdf=render` 当下载直链 —— 实测**永远 403**
（且与 User-Agent 无关：它是网站页，不是 API）。真机代价（T5 第 8 趟 `p8h`）：
41 条文献里 17 条 `http_403`，其中 **12 条是 europepmc**。

而**唯一取得到全文的那条路**（EBI 的 `/rest/{PMCID}/fullTextXML`）返回的是 **JATS XML**
—— 所以只修端点等于把 403 换成 `UnsupportedFormat`。两半必须一起改：

| 半 | 落点 | 这一份钉什么 |
|---|---|---|
| 端点 | `providers._europepmc_urls` | 报来的网站页**永不被选**；PMC 号走 EBI；PPR 号才走预印本参数 |
| 格式 | `extract.py` 的 `_XML_SUFFIXES` | `.xml` 剥标签取正文，且**词与词之间要有分隔** |

## 为什么这两件事值得两条判据（而不是"改完就算"）

- `_europepmc_urls` 此前**一条判据都没有**（全仓 tests 无一提到 europepmc）——
  而它决定整家 provider 的下载目标；这次踩到的两个错（`site` 的真值是
  `Europe_PMC` 而不是 `pmc`；`pprId` 收 PPR 号不收 PMC 号）都在这条"没人看"的路径上。
- `.xml` 那一半最容易出的错不是"读不到"而是**读到粘在一起的词**
  （实测首版剥出来是 `'…SocietyR Soc Open Sci…'`，会污染逐字引文回验）——
  所以判据断言的是**词边界**，不是"非空"。

两条都不联网：`entry` 按真机观测到的形状手写，XML 写进 `tmp_path`。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import extract as EX
from agentflow import providers as P

#: 真机观测到的 Europe PMC 记录形状（`resultType=core`，2026-10-15 实测 `PMC6502358`）。
#: ⚠️ 注意 `site` 的真值是 **`Europe_PMC`**（下划线），不是 `pmc` —— 这正是旧代码
#: `site == "pmc"` 那半句从来没生效的原因。
def _entry(*, pmcid: str = "PMC6502358", extra_pdf: str | None = None,
           is_oa: str = "Y") -> dict:
    urls = [
        {"site": "DOI", "documentStyle": "doi", "availability": "Subscription required",
         "url": "https://doi.org/10.1098/rsos.181055"},
        {"site": "Europe_PMC", "documentStyle": "html", "availability": "Open access",
         "url": f"https://europepmc.org/articles/{pmcid}"},
        {"site": "Europe_PMC", "documentStyle": "pdf", "availability": "Open access",
         "url": f"https://europepmc.org/articles/{pmcid}?pdf=render"},
    ]
    if extra_pdf:
        urls.append({"site": "Other", "documentStyle": "pdf", "availability": "Open access",
                     "url": extra_pdf})
    # `isOpenAccess` 是 **10-A** 的判据（实测：5 条返 200 的全是 `Y`、6 条返 500 的全是 `N`，
    # 而 `inEPMC`/`hasPDF` 两组全是 Y —— 分不开）。夹具必须带上它，否则测的不是真形态。
    return {"pmcid": pmcid, "doi": "10.1098/rsos.181055", "isOpenAccess": is_oa,
            "fullTextUrlList": {"fullTextUrl": urls}}


# ==================================================== 一、端点：网站页永不被选


def test_the_europepmc_website_page_is_never_the_download_target() -> None:
    """正控：PMC 号 ⇒ 走 EBI 的 OA 全文路由，报来的 `?pdf=render` **不许**被选。"""
    url, landing = P._europepmc_urls(_entry(), "10.1098/rsos.181055")
    assert url == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6502358/fullTextXML", url
    assert "?pdf=render" not in str(url), url
    # 落地页仍如实给（它是个真的落地页，只是取不到文件）
    assert landing == "https://doi.org/10.1098/rsos.181055", landing


def test_a_real_pdf_link_from_another_site_is_still_used() -> None:
    """反真空：别的站点给的**真** PDF 直链仍然要用 —— 别把过滤写成"一概不用报来的链接"。

    没有这一条，"永远返回 EBI 路由"也能满足上面那条正控，而那会把
    （真的能下的）第三方直链一起丢掉。
    """
    other = "https://example.org/paper.pdf"
    url, _ = P._europepmc_urls(_entry(extra_pdf=other), None)
    assert url == other, url


def test_a_preprint_id_uses_the_preprint_parameter() -> None:
    """`pprId` 收的是**预印本号（PPR…）**：只有真的是 PPR 号时才准走那一支。

    旧代码无条件把 `PMC…` 塞进 `pprId=` ⇒ 结构上永远不会成（这是同一条路径上的第二个错）。
    """
    url, _ = P._europepmc_urls(_entry(pmcid="PPR123456"), None)
    assert url is not None and "pprId=PPR123456" in url, url
    assert "fullTextXML" not in url, url


# ==================================================== 一之二、10-A：非 OA 不给 URL


def test_a_non_oa_article_gets_no_url_at_all() -> None:
    """**10-A**：`isOpenAccess != "Y"` ⇒ **一条 URL 都不给**（而不是给一条注定 500 的）。

    为什么这不是"少做一件事"：下载层对 5xx 会**重试 3 次**，而 EBI 那条路由对非 OA
    文章**确定性地**返 500（实测 6/6）。T5 第 9 趟的盘上读数：18 条 `http_status=500`
    ⇒ 约 **54 次白跑** ＋ 满屏噪音。
    不给 URL ⇒ 那一行如实落成"没有开放全文"（`skipped`/`no_pdf_url`）——
    三态纪律：那**不是失败**，是"这一篇没有我们取得到的全文"。
    """
    url, landing = P._europepmc_urls(_entry(is_oa="N"), "10.1098/rsos.181055")
    assert url is None, url
    # 落地页照给（它是个真的落地页，指得到那一篇）
    assert landing == "https://doi.org/10.1098/rsos.181055", landing


def test_an_oa_article_still_gets_the_ebi_route() -> None:
    """反真空：`isOpenAccess == "Y"` 仍然要给 URL —— 否则"永远返回 None"也能满足上一条。"""
    url, _ = P._europepmc_urls(_entry(is_oa="Y"), None)
    assert url is not None and "fullTextXML" in str(url), url


# ==================================================== 一之三、10-B：合并别丢好链接


def test_a_constructed_url_does_not_beat_an_oa_location() -> None:
    """**10-B**：合并时"构造出来的"URL 不该盖过别家报来的 **OA 位置**。

    真机形态：`--provider` 的顺序是 `crossref,doaj,europepmc,openalex` ——
    **OpenAlex 排在最后**，而它是唯一会报 `best_oa_location` 的那一家；
    于是先到的 EuropePMC（**由我们构造的** EBI 路由）把 OpenAlex 手里
    **能打开的** OA 位置盖掉了（实测同一 DOI：OpenAlex 给的是可用的 OA 位置，
    而盘上那些行的 `download.url` 是 EBI 那条）。
    """
    base = P.Candidate(title="t", doi="10.1/x", provider="europepmc",
                       pdf_url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
                       raw={"pdf_url_derived": True})
    other = P.Candidate(title="t", doi="10.1/x", provider="openalex",
                        pdf_url="https://example.org/oa.pdf",
                        raw={"pdf_url_source": "best_oa_location.pdf_url"})
    merged = P._merge_candidates(base, other, "openalex")
    assert merged.pdf_url == "https://example.org/oa.pdf", merged.pdf_url
    # 来源读数要跟着走：否则合并后的行会写着"来自 base"而 URL 是对方的（读数与事实不符）
    assert merged.raw.get("pdf_url_source") == "best_oa_location.pdf_url", merged.raw
    # 不许污染被合并的那一方
    assert base.raw.get("pdf_url_source") is None, base.raw


def test_a_missing_url_on_the_other_side_does_not_erase_the_one_we_have() -> None:
    """反真空：对方**没有** pdf_url ⇒ 必须保留 base 那一条（别把"他没有"读成"换成没有"）。"""
    base = P.Candidate(title="t", doi="10.1/x", provider="europepmc",
                       pdf_url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
                       raw={"pdf_url_derived": True})
    other = P.Candidate(title="t", doi="10.1/x", provider="crossref", raw={})
    assert P._merge_candidates(base, other, "crossref").pdf_url == base.pdf_url


# ==================================================== 二、格式：JATS XML 要读得出词


#: 真机形态：JATS 全文常以这条 DOCTYPE 开头 ⇒ 魔数嗅探会把它判成 HTML。
_JATS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.2 20190208//EN" "JATS-archivearticle1.dtd">
<article><front><journal-meta><journal-title-group>
<journal-title>Royal Society Open Science</journal-title>
<abbrev-journal-title>R Soc Open Sci</abbrev-journal-title>
</journal-title-group></journal-meta>
<article-meta><article-id pub-id-type="pmc">PMC6502358</article-id>
<title-group><article-title>A theory and methodology to quantify knowledge</article-title>
</title-group></article-meta></front>
<body><sec><p>We <italic>show</italic> that knowledge can be quantified.</p></sec></body>
</article>
"""


def test_the_jats_full_text_is_extracted_with_word_boundaries(tmp_path: Path) -> None:
    """正控：`.xml` 要读出正文，且**相邻字段之间不能粘**（粘了会污染逐字引文回验）。

    两件事一起断言：
    ① `source_kind == "xml"`（读报告的人能分清"从网页剥的"还是"从 XML 剥的"）；
    ② `Royal Society Open Science` 与 `R Soc Open Sci` 之间**有分隔** ——
       首版剥出来是 `'…SocietyR Soc Open Sci…'`，所以这一格判的是词边界而不是"非空"。
    """
    p = tmp_path / "paper.xml"
    p.write_text(_JATS, encoding="utf-8")
    dt = EX.extract_text(str(p))
    assert dt.source_kind == "xml", dt.source_kind
    assert "Royal Society Open Science" in dt.text, dt.text[:200]
    assert "SocietyR Soc" not in dt.text, "相邻字段被粘在一起（词边界丢了）"
    # 行内标签不该把句子切断（插空格的用意）
    assert "We show that knowledge can be quantified." in dt.text, dt.text[:300]
    assert dt.has_text_layer is True


def test_a_jats_file_stored_as_bin_is_still_rejected(tmp_path: Path) -> None:
    """负控（守住边界）：**扩展名**才是 `.xml` 那条路的入口。

    一个内容相同、但存成 `.bin` 的文件仍然要按老规矩被拒 ——
    否则"嗅探"就变成了"什么都收"，而 `_sniff` 刻意只救 HTML 那一种
    "内容与文件名不符"（理由逐字在它的 docstring 里）。
    """
    p = tmp_path / "paper.bin"
    p.write_text(_JATS, encoding="utf-8")
    with pytest.raises(EX.ExtractError):
        EX.extract_text(str(p))
