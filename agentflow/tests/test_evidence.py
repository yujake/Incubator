"""证据层的验收：检索四态、provenance、逐字回验的正控与负控。

## 为什么负控比正控多

"引文逐字存在 ⇒ verified"是这套机制想要的行为；"引文是编的 ⇒ 必须 not_found"
才是它能防住的东西。前者错了会让人不信任报告，后者错了会让编造的引文进报告 ——
所以这里两条都有，且负控（编造、缺来源、没查成）刻意写得更细。

## 为什么全部离线

`retrieve(search_fn=...)` 与 `verify_claims(quote_fn=...)` 是两个动作各自的接缝。
不注入 `quote_fn` 时走的是禁改区里的 `quoteverify.check_quote` —— 那是纯字符串比对，
本来就不碰网络，所以正控与负控都用真实实现验，只有需要模拟"回验函数坏了"
的那一条才注入假的。检索则一律注入假函数：这一层不该在单测里去连 OpenAlex。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentflow import claims as C
from agentflow import evidence as E

#: 固定时间戳：产物里的时间戳可复现，断言才稳得住。
TS = "2026-01-01T00:00:00+00:00"
#: 一段会被逐字引用的原文。
ABSTRACT = "An abelian group is a group in which the commutative law holds."
#: 材料里确实存在的那句话（正控用的引文）。
VERBATIM = "the commutative law holds"


def _fake_search(items, *, seen: list | None = None):
    """造一个检索接缝：返回固定条目，并把调用参数记进 `seen`（验契约用）。"""

    def _s(topic: str, *, limit: int, timeout_sec: float):
        if seen is not None:
            seen.append({"topic": topic, "limit": limit, "timeout_sec": timeout_sec})
        return list(items)

    return _s


def _source(**kw) -> dict:
    """一条合法的检索条目（默认带全 provenance 所需的字段）。"""
    base = {"source": "openalex", "title": "Abelian groups", "year": 1930,
            "doi": "10.1000/abelian", "abstract": ABSTRACT}
    base.update(kw)
    return base


# --------------------------------------------------------------- ① 检索四态


def test_retrieve_ok_returns_sources_with_provenance():
    """① ok：查到条目 ⇒ status=ok、checked=True，且每条都带完整 provenance。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    assert got["status"] == "ok" and got["checked"] is True
    assert got["query"] == "阿贝尔群" and got["retrieved_at"] == TS
    assert len(got["sources"]) == 1
    prov = got["sources"][0]["provenance"]
    assert prov["provider"] == "openalex", "来源必须记下是哪个库"
    assert prov["query"] == "阿贝尔群", "来源必须记下是用什么查询拿到的"
    assert prov["retrieved_at"] == TS, "来源必须记下是什么时候拿到的"


def test_retrieve_no_results_is_checked_and_distinct_from_failure():
    """① no_results：查过了、没有结果 ⇒ checked=True（它不是"没查成"）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([]), now=TS)
    assert got["status"] == "no_results" and got["checked"] is True
    assert got["sources"] == [] and got["rejected"] == []


def test_retrieve_failure_is_not_checked_and_keeps_the_reason():
    """① retrieval_failed：检索器报错 ⇒ checked=False，且原因里带上异常类型。"""
    def _boom(topic: str, *, limit: int, timeout_sec: float):
        raise ConnectionError("getaddrinfo failed")

    got = E.retrieve("阿贝尔群", search_fn=_boom, now=TS)
    assert got["status"] == "retrieval_failed" and got["checked"] is False
    assert "ConnectionError" in got["reason"] and "getaddrinfo" in got["reason"]


def test_retrieve_not_configured_is_distinct_from_failed():
    """① not_configured：压根没有检索器 ⇒ 与"查了失败"分处两态。"""
    def _none(topic: str, *, limit: int, timeout_sec: float):
        raise E.RetrievalNotConfigured("没有可用的检索器")

    got = E.retrieve("阿贝尔群", search_fn=_none, now=TS)
    assert got["status"] == "not_configured" and got["checked"] is False
    assert "没有可用的检索器" in got["reason"]


def test_empty_topic_is_not_attempted_rather_than_no_results():
    """① 的边界：空主题 ⇒ 没发起检索（not_configured），不是"查了没有结果"。"""
    got = E.retrieve("   ", search_fn=_fake_search([_source()]), now=TS)
    assert got["status"] == "not_configured" and got["checked"] is False
    assert E.not_attempted("没 key", now=TS)["checked"] is False


def test_retrieve_never_raises_on_weird_payloads():
    """① 的同族：检索器返回不可解析的东西 ⇒ 归成三态，不许把异常冒泡出去。"""
    def _weird(topic: str, *, limit: int, timeout_sec: float):
        return "不是列表"

    got = E.retrieve("阿贝尔群", search_fn=_weird, now=TS)
    assert got["status"] == "retrieval_failed" and got["checked"] is False
    assert "不是条目列表" in got["reason"]


def test_search_fn_receives_topic_limit_and_timeout():
    """① 的契约：假检索与生产检索拿到的参数必须是同一组（接缝不能靠猜）。"""
    seen: list[dict] = []
    E.retrieve("阿贝尔群", limit=3, timeout_sec=7.5,
               search_fn=_fake_search([_source()], seen=seen), now=TS)
    assert seen == [{"topic": "阿贝尔群", "limit": 3, "timeout_sec": 7.5}]


# --------------------------------------------------------------- ② provenance


def test_source_without_provenance_is_rejected_and_listed():
    """② 缺来源的条目被拒收，并留下原因（"宁可少一条，也不留一条说不清出处的"）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([{"title": "无出处的一篇"}]), now=TS)
    assert got["sources"] == []
    assert got["status"] == "no_results", "查到了但全部拒收，不是 ok 也不是 retrieval_failed"
    assert got["rejected"] and "来源不明" in got["rejected"][0]["reason"]


def test_item_with_provider_but_no_identifier_is_rejected():
    """② 的同族：有库名但既没有 DOI 也没有 URL ⇒ 无法复核它真的存在，拒收。"""
    got = E.retrieve("阿贝尔群",
                     search_fn=_fake_search([{"source": "openalex", "title": "T"}]), now=TS)
    assert got["sources"] == [] and "缺可解析标识" in got["rejected"][0]["reason"]


def test_url_is_derived_from_doi_but_still_traceable():
    """② 的正控：给了 DOI 就能推出可复核的 URL，条目被接受。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    assert got["sources"][0]["url"] == "https://doi.org/10.1000/abelian"


def test_no_source_may_lack_provenance():
    """② 的全局断言：ok 结果里每一条来源都必须三件套齐全（这是一条不变量）。

    多源之后这条不变量多了一项：`providers` 必须写出"这条来自哪几个源" ——
    没有它就分不出"被两个库同时证实"与"只有一个库有它"。
    第二条刻意用「另一个 DOI」：同一个 DOI 的两条按判重键是同一条，
    那条路径由 `test_same_paper_from_two_sources_merges` 负责。
    """
    got = E.retrieve("阿贝尔群",
                     search_fn=_fake_search([_source(),
                                             _source(title="T2", doi="10.1000/other")]),
                     now=TS)
    assert got["status"] == "ok" and len(got["sources"]) == 2
    for s in got["sources"]:
        prov = s["provenance"]
        assert prov["provider"] and prov["query"] and prov["retrieved_at"]
        assert prov["providers"] == [prov["provider"]], "每条来源必须写明它来自哪些源"
        assert s["title"] and (s["doi"] or s["url"])


# --------------------------------------------------------- ③④ 负控与正控（真实回验）


def test_negative_control_fabricated_quote_is_not_found():
    """③ 负控：材料在手上、比对过、那句话不存在 ⇒ 必须 not_found（不许放过）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims(
        [{"text": "阿贝尔群是有限群", "quote": "every abelian group is finite"}],
        got["sources"],
    )
    row = res["claims"][0]
    assert row["verdict"] == "not_found" and row["verified"] is False
    assert row["evidence_source"] == "", "not_found 的断言不许指向任何来源"


def test_positive_control_verbatim_quote_is_verified():
    """④ 正控：逐字存在的引文 ⇒ verified，且指向真正命中的那条来源。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims([{"text": "它是交换群", "quote": VERBATIM}], got["sources"])
    row = res["claims"][0]
    assert row["verdict"] == "verified" and row["verified"] is True
    assert row["evidence_source"] == "S1"
    assert res["counts"]["verified"] == 1 and res["counts"]["unverified"] == 0
    assert res["checked"] is True


def test_punctuation_change_is_not_forgiven():
    """④ 的边界：改标点就不算逐字（保守规范化是刻意的，不许放水）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims(
        [{"text": "它是交换群", "quote": "the commutative law holds, for every pair."}],
        got["sources"],
    )
    assert res["claims"][0]["verdict"] == "not_found"


# ------------------------------------------------- ⑤ unknown 与 not_found 不许混


def test_unknown_when_there_is_no_source_text_at_all():
    """⑤ 手上没有任何来源 ⇒ unknown（没查成），绝不落 not_found。"""
    res = E.verify_claims([{"text": "T", "quote": VERBATIM}], [])
    row = res["claims"][0]
    assert row["verdict"] == "unknown" and row["checked"] is False
    assert res["checked"] is False and "没有任何来源" in res["reason"]


def test_unknown_when_the_source_has_no_abstract_text():
    """⑤ 来源在、但它没有摘要文本 ⇒ 无从比对 ⇒ unknown（不是"引文不存在"）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source(abstract="")]), now=TS)
    assert got["status"] == "ok"
    res = E.verify_claims([{"text": "T", "quote": VERBATIM}], got["sources"])
    assert res["claims"][0]["verdict"] == "unknown"
    assert res["claims"][0]["reason"] == "no_source_text"


def test_unknown_when_the_verifier_itself_fails():
    """⑤ 回验函数抛异常 ⇒ unknown（把基础设施故障记成学术不端是最坏的读法）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)

    def _boom(doc, quote, page_range, *, widen=1, allow_fulltext_fallback=False):
        raise RuntimeError("verifier crashed")

    res = E.verify_claims([{"text": "T", "quote": VERBATIM}], got["sources"],
                          quote_fn=_boom)
    assert res["claims"][0]["verdict"] == "unknown"
    assert "quote_fn_failed" in res["claims"][0]["reason"]
    assert res["checked"] is False


def test_claim_without_a_quote_is_known_unverifiable():
    """⑤ 同族：没给引文的结论按设计无法逐字回验 ⇒ known_unverifiable，不是 not_found。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims([{"text": "综述性结论", "quote": ""}], got["sources"])
    row = res["claims"][0]
    assert row["verdict"] == "known_unverifiable" and row["reason"] == "no_quote"
    assert res["counts"]["not_found"] == 0


def test_verdicts_are_a_controlled_vocabulary():
    """⑤ 的同族：判决只许取受控词表里的值（写错一个词就是一次静默的读错）。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims(
        [{"text": "A", "quote": VERBATIM}, {"text": "B", "quote": "不存在的一句"},
         {"text": "C", "quote": ""}], got["sources"])
    assert all(r["verdict"] in E.VERDICTS for r in res["claims"])
    assert res["counts"]["total"] == 3 and res["counts"]["verified"] == 1
    assert res["counts"]["unverified"] == 2


# ------------------------------------------------------------ 断言解析与材料段


def test_parse_claims_reads_the_agreed_format_and_ignores_the_rest():
    """断言解析：约定格式切得出，杂散行会被拆成断言，没引文的断言也登记。

    改名留痕：本用例原名以 `_and_ignores_the_rest` 结尾，断言的是
    "切不出引文的行直接丢弃"。接线之后那条判据本身成了要防的缺陷 ——
    丢弃会让"我们没验这一条"看起来像"这条断言不存在"，所以判据换成：
    带引文的保留引文、不带引文的保留断言且 `quote` 为空、重复的仍然去重。
    真正被"忽略"的只剩结构行（标题、代码围栏），理由写在
    `claims._heuristic_claims` 里。
    """
    text = (
        "结论如下：\n"
        f"- 阿贝尔群是交换群 || {VERBATIM}\n"
        "- 这句没有引文\n"
        f"断言：第二个结论 ｜ 引文：{VERBATIM}\n"
        "随便一句没有格式的话\n"
        f"- 阿贝尔群是交换群 || {VERBATIM}\n"
    )
    claims = E.parse_claims(text)
    assert claims == [
        {"text": "结论如下：", "quote": ""},
        {"text": "阿贝尔群是交换群", "quote": VERBATIM},
        {"text": "这句没有引文", "quote": ""},
        {"text": "第二个结论", "quote": VERBATIM},
        {"text": "随便一句没有格式的话", "quote": ""},
    ], "重复的断言必须去重；没引文的断言必须留下（quote 为空）"


def test_parse_claims_stops_at_max_claims():
    """断言解析的上限是硬约束：模型回一大段时不许把台账撑爆。

    上限是硬约束，但不许静默：截掉多少条由 `claims.split_claims` 的
    `truncated` / `total_found` 记下来（见
    `test_split_truncation_is_recorded_and_the_numbers_add_up`）。
    """
    text = "\n".join(f"- 断言{i} || 引文{i}" for i in range(20))
    assert len(E.parse_claims(text, max_claims=3)) == 3
    assert len(E.parse_claims(text)) == 20, "缺省上限之下一条都不许少"


def test_materials_block_says_there_is_no_material_when_there_is_none():
    """材料段：没有材料时必须明说"不许给结论"，静默空段会让模型凭记忆作答。"""
    block = E.materials_block([])
    assert "没有检索到任何可用材料" in block and "不许给出任何实质结论" in block
    filled = E.materials_block([{"source_id": "S1", "source": "openalex",
                                 "title": "Abelian groups", "abstract": ABSTRACT}])
    assert "[S1] Abelian groups" in filled and VERBATIM in filled
    assert "逐字复制" in filled


def test_verify_claims_with_no_claims_is_not_a_failure():
    """空台账：没有断言要查 ⇒ 不是失败，但 checked 取决于手上有没有可比原文。"""
    with_src = E.verify_claims([], [{"source_id": "S1", "abstract": ABSTRACT}])
    assert with_src["claims"] == [] and with_src["checked"] is True
    empty = E.verify_claims([], [])
    assert empty["checked"] is False and empty["counts"]["total"] == 0


@pytest.mark.parametrize("status", list(E.RETRIEVAL_STATUSES))
def test_checked_only_for_the_two_checked_statuses(status: str):
    """三态纪律的机器可读形式：`checked` 与 status 的对应关系只有一种。"""
    assert (status in E.CHECKED_STATUSES) == (status in ("ok", "no_results"))


def test_evidence_selftest_passes_offline():
    """模块自检要能在没有网络、没有 key 的环境里通过。"""
    assert E.evidence_main([]) == 0


# =================================================== 多源检索：逐源状态与合并
# 这一组是任务 1 的验收。判据的核心只有一条：「单源失败不许让整体失败」 ——
# 材料是这一层唯一的产出，因为另一个库限流就把它丢掉，等于让报告退化成
# 模型自说自话，而它看起来与"检索了、没找到"一模一样。


def _boom(topic: str, *, limit: int, timeout_sec: float):
    """一个失败的源（网络故障）。"""
    raise ConnectionError("network down")


def _empty(topic: str, *, limit: int, timeout_sec: float):
    """一个"查过了、没有"的源。"""
    return []


def test_one_source_failing_does_not_fail_the_whole_retrieval():
    """① 一源失败 + 一源成功 ⇒ 整体必须 ok，且逐源状态如实记录。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn={
        "broken": _boom, "good": _fake_search([_source(source="good")]),
    })
    assert got["status"] == "ok" and got["checked"] is True
    assert got["sources_status"] == {"broken": "failed", "good": "ok"}
    assert len(got["sources"]) == 1, "坏掉的那个源不许把好源的结果带走"
    detail = {d["source"]: d for d in got["sources_detail"]}
    assert "ConnectionError" in detail["broken"]["reason"], "失败源必须留下原因"
    assert detail["good"]["count"] == 1


def test_all_sources_failed_is_retrieval_failed_not_no_results():
    """① 全部源都失败 ⇒ retrieval_failed（不是"这个主题没有文献"）。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn={"a": _boom, "b": _boom})
    assert got["status"] == "retrieval_failed" and got["checked"] is False
    assert got["sources_status"] == {"a": "failed", "b": "failed"}
    assert "全部失败" in got["reason"]


def test_all_sources_empty_is_no_results_and_counts_as_checked():
    """① 全部源都"查过了、没有" ⇒ no_results，且这是「查过了」（checked=True）。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn={"a": _empty, "b": _empty})
    assert got["status"] == "no_results" and got["checked"] is True
    assert got["sources_status"] == {"a": "no_results", "b": "no_results"}


def test_no_results_plus_failed_is_no_results_not_failure():
    """① 的边界：一源没结果、一源失败 ⇒ no_results（有一个源确实查过了）。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn={"a": _empty, "b": _boom})
    assert got["status"] == "no_results" and got["checked"] is True
    assert got["sources_status"] == {"a": "no_results", "b": "failed"}


def test_same_paper_from_two_sources_merges_and_names_both():
    """② 同一篇（DOI 不同写法）来自两个源 ⇒ 合并成一条，且标明两个源。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn={
        # 第二个源给的 DOI 带 URL 前缀与尾随点：归一化必须把它与第一个认成同一篇
        # （归一化规则只有禁改区 `dedup.normalize_doi` 一份，这里不另写判据）。
        "openalex": _fake_search([_source(source="openalex", doi="10.1000/abelian")]),
        "crossref": _fake_search([_source(source="crossref",
                                          doi="https://doi.org/10.1000/abelian.",
                                          abstract="")]),
    })
    assert got["status"] == "ok"
    assert len(got["sources"]) == 1, "同一篇文献不许在产物里出现两次"
    merged = got["sources"][0]
    assert merged["providers"] == ["openalex", "crossref"], "必须看得出它来自两个源"
    assert merged["provenance"]["query_by_source"]["crossref"] == "阿贝尔群"
    assert merged["source_id"] == "S1"
    assert got["sources_status"] == {"openalex": "ok", "crossref": "ok"}


def test_two_different_dois_stay_two_sources():
    """② 的负控：DOI 不同就是两篇，不许因为标题像就合并。"""
    got = E.retrieve("阿贝尔群", now=TS, search_fn=_fake_search([
        _source(doi="10.1000/a"), _source(doi="10.1000/b"),
    ]))
    assert len(got["sources"]) == 2


# =================================================== 全文获取：六态各一例
# 六种状态每一种都要有理由字段 —— 没有理由的失败与"没做"在产物里长得一样。

_FT_QUOTE = "the identity element is unique"


def _src_for_fulltext(**kw) -> dict:
    """一条带 PDF 线索的来源（全文获取的输入形态）。"""
    base = {"source_id": "S1", "source": "openalex", "title": "Abelian groups",
            "doi": "10.1000/abelian", "year": 1930, "abstract": ABSTRACT,
            "pdf_url": "https://example.invalid/paper.pdf", "fulltext": None}
    base.update(kw)
    return base


def _fetch_ok(text: str = "page one text\nsecond page"):
    """假下载器：真落一个文件（哈希要能算出来），返回 FetchResult 同形 dict。"""
    def _f(url: str, dest_dir, filename_hint: str):
        p = Path(dest_dir) / "paper.pdf"
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(p), "bytes": len(text), "error": None,
                "sha256": "deadbeef"}
    return _f


def _extract_pages(pages: list[str]):
    def _e(path: str):
        return {"text": "\n".join(pages), "pages": list(pages),
                "source_kind": "pdf", "encoding": None}
    return _e


def test_acquire_fulltext_ok_records_provenance():
    """③ ok：落盘哈希、页数、抽取后端名、字节数四件 provenance 都要有。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a", "b"]),
                             dest_dir=".")
    ft = sources[0]["fulltext"]
    assert ft["status"] == "ok" and got["counts"]["ok"] == 1
    assert ft["pages"] == 2 and ft["backend"] == "pdf"
    assert ft["sha256"] == "deadbeef", "下载器给了哈希就用它（同一份文件只算一次）"
    assert ft["bytes"] > 0 and ft["reason"]


def test_acquire_fulltext_no_pdf_has_a_reason():
    """③ no_pdf：没有可下载的开放全文 ⇒ 与"下载失败"分处两态。"""
    sources = [_src_for_fulltext(pdf_url=None, url="https://doi.org/10.1000/abelian")]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a"]),
                             dest_dir=".")
    assert sources[0]["fulltext"]["status"] == "no_pdf"
    assert got["counts"]["no_pdf"] == 1
    assert "没有可下载" in sources[0]["fulltext"]["reason"]


def test_acquire_fulltext_download_failed_has_a_reason():
    """③ download_failed：下载器报失败 ⇒ 理由必须来自它，且不许继续去抽取。"""
    called: list[str] = []

    def _bad(url: str, dest_dir, filename_hint: str):
        return {"ok": False, "path": None, "bytes": 0, "error": "http_403", "http_status": 403}

    def _never(path: str):
        called.append(path)
        raise AssertionError("下载失败后不该去抽取")

    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_bad, extract_fn=_never, dest_dir=".")
    assert sources[0]["fulltext"]["status"] == "download_failed"
    assert sources[0]["fulltext"]["reason"] == "http_403"
    assert called == [] and got["counts"]["download_failed"] == 1


def test_acquire_fulltext_no_text_layer_means_scanned():
    """③ no_text_layer：能打开、但一页文本都没有（扫描件）⇒ 不是 extract_failed。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(),
                             extract_fn=_extract_pages([]), dest_dir=".")
    assert sources[0]["fulltext"]["status"] == "no_text_layer"
    assert got["counts"]["no_text_layer"] == 1
    assert "OCR" in sources[0]["fulltext"]["reason"]


def test_acquire_fulltext_extract_failed_keeps_the_exception_type():
    """③ extract_failed：抽取器抛异常 ⇒ 理由里必须带异常类型（不许只说"失败"）。"""
    def _boom(path: str):
        raise RuntimeError("no pdf backend installed")

    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_boom, dest_dir=".")
    assert sources[0]["fulltext"]["status"] == "extract_failed"
    assert "RuntimeError" in sources[0]["fulltext"]["reason"]
    assert got["counts"]["extract_failed"] == 1


def test_acquire_fulltext_over_limit_is_not_configured_not_no_pdf():
    """③ not_configured（第二种含义）：超 limit 而「没有发起」下载。

    这一条是"没做"与"做了没成"的分界：超限的来源绝不许写成 no_pdf，
    那会让"我们没去拿"看起来像"这篇没有开放全文"。
    """
    sources = [_src_for_fulltext(source_id="S1"), _src_for_fulltext(source_id="S2")]
    calls: list[str] = []

    def _count(url: str, dest_dir, filename_hint: str):
        calls.append(url)
        return {"ok": False, "error": "should_not_be_called"}

    got = E.acquire_fulltext(sources, fetch_fn=_count, extract_fn=_extract_pages(["a"]),
                             dest_dir=".", limit=1)
    assert sources[1]["fulltext"]["status"] == "not_configured"
    assert "没有发起下载" in sources[1]["fulltext"]["reason"]
    assert len(calls) == 1, "超限的来源不许真的去打网络"
    assert got["counts"]["not_configured"] == 1 and got["counts"]["download_failed"] == 1


def test_acquire_fulltext_without_impls_is_not_configured():
    """③ not_configured（第一种含义）：压根没有下载器/抽取器可造。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=None, extract_fn=None, dest_dir=".")
    # 生产实现是能被 import 的（本仓库里 fetch/extract 都在），所以这里要的是
    # "没有 setup 失败"这一半；真正的"读不到模块"由 `_acquire_impls` 的返回值表达。
    assert got["configured"] is True and got["checked"] is True
    assert isinstance(sources[0]["fulltext"], dict)


# =================================================== 回验分级：level 与 locator
# 这一组是任务 3 的验收，也是整个工作包最关键的两条负控。


def _source_with_fulltext(text_pages: list[str], **kw) -> dict:
    """一条既有摘要又有全文的来源（回验分级的输入形态）。"""
    src = _src_for_fulltext(**kw)
    src["fulltext"] = {"status": "ok", "text": "\n".join(text_pages),
                       "text_pages": list(text_pages), "pages": len(text_pages),
                       "backend": "pdf", "sha256": "x", "bytes": 1}
    return src


def test_key_negative_control_abstract_only_quote_is_never_called_fulltext():
    """⑤ 关键负控：只存在于摘要、正文里没有的引文 ⇒ 必须标 abstract。

    若它被标成 fulltext，读者会以为正文里有这句话 —— 而正文我们其实查过、
    里面没有。这是本工作包最贵的一种错标。
    """
    src = _source_with_fulltext([f"Body text of page one mentions {_FT_QUOTE}.",
                                "Page two is about something else entirely."])
    # 摘要里逐字有 VERBATIM，正文两页里都没有。
    res = E.verify_claims([{"text": "它是交换群", "quote": VERBATIM}], [src])
    row = res["claims"][0]
    assert row["verdict"] == "verified"
    assert row["level"] == "abstract", f"只验到摘要的引文绝不许标全文级：{row}"
    assert row["locator"]["kind"] == "char_offset" and row["locator"]["start"] >= 0
    assert res["counts"]["verified_abstract"] == 1
    assert res["counts"]["verified_fulltext"] == 0
    assert res["check"]["levels_reached"] == ["abstract"]


def test_quote_in_fulltext_is_verified_at_fulltext_level_with_page():
    """⑤ 的正控：正文里逐字存在的引文 ⇒ level=fulltext，且 locator 给出页号。"""
    src = _source_with_fulltext(["Page one has no such sentence.",
                                f"On page two we recall that {_FT_QUOTE}."])
    res = E.verify_claims([{"text": "单位元唯一", "quote": _FT_QUOTE}], [src])
    row = res["claims"][0]
    assert row["verdict"] == "verified" and row["level"] == "fulltext"
    assert row["locator"] == {"kind": "page", "page": 2}, "命中位置必须能被人核对"
    assert res["counts"]["verified_fulltext"] == 1 and res["counts"]["verified_abstract"] == 0
    assert res["check"]["levels_reached"] == ["fulltext"]


def test_both_levels_are_counted_separately():
    """⑤ 的同族：同一次回验里两级各有命中 ⇒ 两个数字分别给，不许合并成一个。"""
    src = _source_with_fulltext(["Page one.", f"Page two says {_FT_QUOTE}."])
    res = E.verify_claims([
        {"text": "摘要里的话", "quote": VERBATIM},
        {"text": "正文里的话", "quote": _FT_QUOTE},
    ], [src])
    assert [c["level"] for c in res["claims"]] == ["abstract", "fulltext"]
    assert res["counts"]["verified_abstract"] == 1
    assert res["counts"]["verified_fulltext"] == 1
    assert res["counts"]["verified"] == 2
    assert res["check"]["levels_reached"] == ["abstract", "fulltext"]


def test_no_fulltext_means_level_is_abstract_and_says_so():
    """⑤ 的边界：手上只有摘要 ⇒ 台账里每一条通过都只能是 abstract。"""
    got = E.retrieve("阿贝尔群", search_fn=_fake_search([_source()]), now=TS)
    res = E.verify_claims([{"text": "它是交换群", "quote": VERBATIM}], got["sources"])
    assert res["claims"][0]["level"] == "abstract"
    assert res["counts"]["verified_fulltext"] == 0
    assert "只到达摘要级" in res["reason"], "理由里必须写明这次没能到达全文级"


def test_negative_control_fabricated_quote_against_fulltext_is_not_found():
    """④ 负控：编造的引文对全文 ⇒ not_found（全文在手时更不许放过编造）。"""
    src = _source_with_fulltext(["Page one is about groups.", "Page two is about rings."])
    res = E.verify_claims([{"text": "编造的结论", "quote": "abelian groups are always finite"}],
                          [src])
    row = res["claims"][0]
    assert row["verdict"] == "not_found" and row["verified"] is False
    assert row["level"] == "" and row["locator"] == {}, "未通过的判决不许标级别或位置"
    assert res["counts"]["not_found"] == 1


def test_download_failure_still_verifies_against_the_abstract():
    """⑥ 下载失败 ⇒ download_failed，但整体仍能在有摘要时继续（回验落到摘要级）。

    这一条把"全文没拿到"与"没查成"分开：摘要在手上就是查过了，
    退出码不该因此变成 2，级别如实停在摘要级。
    """
    sources = [_src_for_fulltext()]

    def _bad(url: str, dest_dir, filename_hint: str):
        return {"ok": False, "error": "network_error: timed out"}

    got = E.acquire_fulltext(sources, fetch_fn=_bad, extract_fn=_extract_pages(["x"]),
                             dest_dir=".")
    assert sources[0]["fulltext"]["status"] == "download_failed"
    assert got["counts"]["download_failed"] == 1
    res = E.verify_claims([{"text": "它是交换群", "quote": VERBATIM}], sources)
    assert res["claims"][0]["verdict"] == "verified"
    assert res["claims"][0]["level"] == "abstract"
    assert res["checked"] is True, "有摘要可查 ⇒ 这是查过了，不是没查成"
    assert "只到达摘要级" in res["reason"]


def test_no_comparable_text_at_all_is_the_only_case_that_is_not_checked():
    """⑥ 的边界：完全没有可比文本（摘要与全文都没有）⇒ 才落 unknown / checked=False。"""
    src = _src_for_fulltext(abstract="")
    src["fulltext"] = {"status": "no_text_layer", "reason": "扫描件"}
    res = E.verify_claims([{"text": "T", "quote": VERBATIM}], [src])
    assert res["claims"][0]["verdict"] == "unknown"
    assert res["claims"][0]["reason"] == "no_source_text"
    assert res["checked"] is False


def test_acquire_statuses_are_a_controlled_vocabulary():
    """③ 的同族：六态词表是判据，改坏它要让用例红（写在两处的判据早晚会漂移）。"""
    assert E.ACQUIRE_STATUSES == ("ok", "no_pdf", "download_failed", "no_text_layer",
                                  "extract_failed", "not_configured")
    assert E.EVIDENCE_LEVELS == ("abstract", "fulltext")
    assert E.SOURCE_STATUSES == ("ok", "no_results", "failed")


# ================================================= 原子断言拆分：三态 / 不丢弃 / 截断
# 这一组是本工作包的验收。四条判据：
#   1. 三态各一例（parsed / no_claims / unparsable），空集绝不许当成功；
#   2. 没有引文的断言落 known_unverifiable，不许消失；
#   3. 截断诚实：被截断的条数必须写在产物里，且数字对得上；
#   4. 负控：一段完全没有可断言内容的答复必须 no_claims 且带理由
#      （不许当成"零问题通过"）。
# 全部离线：拆分层是纯函数，判决层注入假 `quote_fn`。


def test_split_parsed_splits_prose_into_atomic_claims():
    """① parsed：散文式答复按句切，每条断言都带"拆分依据"。"""
    got = C.split_claims("阿贝尔群是交换群。它有唯一的单位元。有限群的阶是整数。")
    assert got.status == "parsed" and len(got.claims) == 3
    assert [c.text for c in got.claims] == ["阿贝尔群是交换群。", "它有唯一的单位元。",
                                            "有限群的阶是整数。"]
    assert {c.basis for c in got.claims} == {"sentence_end"}
    assert all(c.quote == "" for c in got.claims)
    assert got.truncated == 0 and got.total_found == 3
    assert got.fingerprint, "拆分指纹必须落产物：换一次口径要看得出来"


def test_split_uses_the_models_own_markers_first():
    """① parsed 的同族：模型写了 `||` 就按它切，引文原样保留。"""
    got = C.split_claims(f"- 阿贝尔群是交换群 || {VERBATIM}\n- 单位元唯一\n")
    assert got.status == "parsed"
    assert [(c.text, c.quote, c.basis) for c in got.claims] == [
        ("阿贝尔群是交换群", VERBATIM, "quote_marker"),
        ("单位元唯一", "", "bullet"),
    ]


def test_split_no_claims_when_the_reply_refuses():
    """④ 负控（关键）：一段完全没有可断言内容的答复必须 no_claims 且带理由。

    这一条挡的是"把空台账当成零问题通过"：一句"我无法给出结论"按句子会被
    切出一条断言，而它恰恰是"这次没有结论"的那句话。判据必须让它落
    `no_claims`，理由里逐字写出命中的拒绝措辞（可被反驳、可被审计）。
    """
    got = C.split_claims("材料中没有可依据的内容，我无法给出结论。")
    assert got.status == "no_claims" and got.claims == []
    assert got.truncated == 0 and got.total_found == 0
    assert "拒绝措辞" in got.reason and "无法给出结论" in got.reason
    assert got.status != "parsed", "空集绝不许当成功"


def test_split_unparsable_when_there_is_nothing_to_process():
    """① unparsable：空串与"全是符号"都读不动 ⇒ 与 no_claims 分得开。"""
    empty = C.split_claims("   ")
    assert empty.status == "unparsable" and empty.claims == []
    assert "空串" in empty.reason and empty.reason
    symbols = C.split_claims("????????????")
    assert symbols.status == "unparsable" and symbols.claims == []
    assert "字母或数字" in symbols.reason


def test_split_is_deterministic_and_the_injected_parser_is_not_a_black_box():
    """② 的纪律：同一输入 + 同一 parse_fn 必须同结果，且指纹把注入这件事记下来。"""
    text = "\n".join(f"- 断言{i} || 引文{i}" for i in range(5))
    first = C.split_claims(text)
    second = C.split_claims(text)
    assert [c.to_dict() for c in first.claims] == [c.to_dict() for c in second.claims]
    assert first.fingerprint == second.fingerprint

    calls: list[str] = []

    def _fn(raw: str, *, max_claims: int):
        calls.append(raw)
        return [{"text": "模型补的一条", "quote": VERBATIM}]

    injected = C.split_claims(text, parse_fn=_fn)
    assert calls == [text], "注入的 parse_fn 只该被调用一次"
    assert injected.parse_fn_used is True
    assert injected.claims[0].basis == "parsed_fn"
    assert injected.fingerprint != first.fingerprint, \
        "用没用 parse_fn 必须改变指纹（否则口径漂移看不出来）"
    assert injected.status == "parsed" and len(injected.claims) == 6


def test_split_with_a_broken_parse_fn_falls_back_and_says_so():
    """② 的同族：注入的 parse_fn 坏了只是退回启发式，不许把整次拆分化成"没拆成"。"""
    def _boom(raw: str, *, max_claims: int):
        raise RuntimeError("辅助拆分挂了")

    got = C.split_claims("- 一条断言\n", parse_fn=_boom)
    assert got.status == "parsed" and len(got.claims) == 1
    assert C.PARSE_FN_ERROR in got.parse_fn_error
    assert any(C.PARSE_FN_ERROR in e for e in got.errors)


def test_claim_without_a_quote_stays_in_the_ledger_as_known_unverifiable():
    """②（关键）：没有引文的断言必须留在台账里，判决 known_unverifiable。

    这是本工作包最贵的一条：丢掉它会让"我们没验这一条"读成"这条断言不存在"。
    """
    split = C.split_claims(f"- 有引文 || {VERBATIM}\n- 没有引文\n- 编造的 || 材料里没有")
    assert split.status == "parsed" and len(split.claims) == 3
    verdicts = E.verify_claims([c.to_dict() for c in split.claims],
                               [{"source_id": "S1", "abstract": ABSTRACT}])
    rows = C.ledger_rows(split, verdicts["claims"])
    assert [r["verdict"] for r in rows] == ["verified", "known_unverifiable", "not_found"]
    assert rows[1]["quote"] == "" and rows[1]["verdict"] == "known_unverifiable"
    assert rows[1]["claim_id"] == "C2"
    assert all(set(r) == set(C.LEDGER_ROW_KEYS) for r in rows), \
        "台账每一行的键必须齐（少一个键就是下游读不到的一件事）"
    assert [r["claim_id"] for r in rows] == ["C1", "C2", "C3"]


def test_split_truncation_is_recorded_and_the_numbers_add_up():
    """③ 截断诚实：被截断的条数必须写明，且 `登记 + 截断 == 共拆出`。"""
    text = "\n".join(f"- 断言{i} || 引文{i}" for i in range(250))
    got = C.split_claims(text, max_claims=200)
    assert got.status == "parsed" and len(got.claims) == 200
    assert got.total_found == 250 and got.truncated == 50
    assert len(got.claims) + got.truncated == got.total_found
    assert any("已截断 50 条" in e for e in got.errors), \
        "截断必须留下可读的痕迹，不许静默"
    assert "截断后登记 200 条" in got.reason

    tiny = C.split_claims(text, max_claims=7)
    assert len(tiny.claims) == 7 and tiny.truncated == 243
    assert len(tiny.claims) + tiny.truncated == tiny.total_found == 250


def test_merge_splits_dedupes_across_replies_and_keeps_truncation_honest():
    """③ 的同族：两次调用的答复合并后去重，截断数字来自全局口径。

    合并后的 `truncated` 口径是"共拆出多少条减去登记多少条"，所以跨次调用的
    重复也会落进这个差额（它对读者就是"少掉的那几条"，理由是重复还是超限
    都写在 `reason` / `errors` 里）。恒等式 `登记 + 截断 == 共拆出` 必须成立 ——
    这是"截断诚实"唯一可判定的形态。
    """
    first = C.split_claims("- 同一条 || q\n- 第二条 || q2")
    second = C.split_claims("- 同一条 || q\n- 第三条 || q3")
    merged = C.merge_splits([first, second])
    assert merged.status == "parsed"
    assert [c.text for c in merged.claims] == ["同一条", "第二条", "第三条"]
    assert merged.total_found == 4, "共拆出多少条要把两段都算进来（去重前）"
    assert merged.truncated == 1, "跨次调用重复的那一条要落进差额"
    assert len(merged.claims) + merged.truncated == merged.total_found

    capped = C.merge_splits([first, second], max_claims=2)
    assert len(capped.claims) == 2 and capped.total_found == 4 and capped.truncated == 2
    assert len(capped.claims) + capped.truncated == capped.total_found

    # 每一段自己先被截断时，合并后的"共拆出"要把那些也算进来（不许变小）。
    part = C.split_claims("\n".join(f"- 断言{i} || 引文{i}" for i in range(50)),
                          max_claims=10)
    both = C.merge_splits([part, part], max_claims=10)
    assert both.total_found == 100, "共拆出多少条必须来自逐段的总数，不是逐段登记数"
    assert len(both.claims) + both.truncated == both.total_found == 100


def test_ledger_rows_never_invents_a_pass_for_a_quote_less_claim():
    """② 的负控：判决行与断言对错位时，不许把没引文的断言写成"验过了"。"""
    split = C.split_claims("- 没有引文的断言")
    rows = C.ledger_rows(split, [{"text": "没有引文的断言", "quote": "",
                                 "verdict": "verified", "level": "fulltext",
                                 "checked": True}])
    assert rows[0]["verdict"] == "known_unverifiable"
    assert rows[0]["checked"] is False and rows[0]["level"] == ""


def test_ledger_rows_marks_claims_the_verifier_never_saw():
    """② 的同族：判决行没覆盖到的断言落 known_unverifiable，不许当成通过。"""
    split = C.split_claims(f"- A || q-a\n- B || q-b")
    rows = C.ledger_rows(split, [{"text": "A", "quote": "q-a", "verdict": "verified",
                                  "level": "abstract", "checked": True}])
    assert rows[0]["verdict"] == "verified"
    assert rows[1]["verdict"] == "known_unverifiable"
    assert "没有这一条的判决行" in rows[1]["reason"]


def test_verdict_vocabulary_has_exactly_one_authority():
    """② 的同族：判决词表只有一份（`evidence.VERDICTS`），`claims` 里那份被钉住。"""
    assert C.VERDICTS == E.VERDICTS
    assert C.SPLIT_STATUSES == ("parsed", "no_claims", "unparsable")
    assert C.LEDGER_ROW_KEYS[0] == "claim_id" and "verdict" in C.LEDGER_ROW_KEYS
    assert callable(C.refusal_reason) and C.refusal_reason("我无法给出结论。")


def test_evidence_parse_claims_is_a_pure_forwarder():
    """② 的同族：`evidence.parse_claims` 与 `claims.parse_claims` 不许有第二个上限。

    包装层必须给一个不可变的默认值，于是"上限"这件事在两个模块各出现一次；
    这条用例把两边钉成同一个数字 —— 否则两条路径会拆出不同的条数，
    而两者各自都自洽（FC-03 的典型形态）。
    """
    assert E._DEFAULT_PARSE_MAX == C.DEFAULT_MAX_CLAIMS
    text = "\n".join(f"- 断言{i} || 引文{i}" for i in range(C.DEFAULT_MAX_CLAIMS + 5))
    assert E.parse_claims(text) == C.parse_claims(text)
    assert len(E.parse_claims(text)) == C.DEFAULT_MAX_CLAIMS


#: 形如密钥的字面量。判据取"前缀 + 足够长的随机体"，而不是裸前缀：
#: 裸前缀在真实代码里会命中 `tags=("research", "gap", "ask-A")` 这类无关串，
#: 也会命中断言"产物里不许有它"的那一行本身 —— 那是假阳性，
#: 而假阳性会让这条门在第一次运行时就失去可信度（本项目 R001/R006 的教训）。
_SECRET_LIKE = re.compile(r"['\"](?:sk|rk|pk)-[A-Za-z0-9_\-]{12,}['\"]")
#: 明确写着"这不是真 key"的夹具串（白名单）。
#:
#: 白名单是刻意的、也必须短：`test_modelgw.py` 需要一条「看起来像 key」 的串来验
#: 脱敏，而"看起来像"与"是真的"在字面上无法区分。所以这里逐个登记，
#: 新增一条就要多登记一条 —— 一个新出现的、不在白名单里的长串会让这条用例红，
#: 这正是它存在的意义（反过来，"凡是 sk- 开头就放过"等于没有这条门）。
_KNOWN_FAKE_KEYS: frozenset[str] = frozenset({
    "sk-super-secret-value", "fixture-key-not-a-secret", "selftest-key",
})


def test_no_source_or_test_file_contains_a_real_looking_key():
    """⑧ 安全：源码与测试里都不许出现形如真实密钥的字面量（除已登记的假串）。

    为什么这条要扫全仓而不能只看产物：夹具串一旦照抄成真 key，
    它就会随产物、日志与抄本扩散，而单元测试不会因为"串长得像 key"而变红。
    为什么判据带长度下界、白名单逐个登记：见 `_SECRET_LIKE` 与 `_KNOWN_FAKE_KEYS`。
    """
    root = Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for folder in (root / "src", root / "tests"):
        for path in folder.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                found = _SECRET_LIKE.search(line)
                if found and found.group(0).strip("'\"") not in _KNOWN_FAKE_KEYS:
                    hits.append(f"{path.relative_to(root)}:{lineno}: {found.group(0)[:20]}...")
    assert hits == [], f"出现形如密钥的字面量：{hits}"
