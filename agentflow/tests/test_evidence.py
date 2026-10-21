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
from agentflow import providers as P
from agentflow.tools import search_tools as ST

#: 固定时间戳：产物里的时间戳可复现，断言才稳得住。
TS = "2026-01-01T00:00:00+00:00"
#: 一段会被逐字引用的原文。
ABSTRACT = "An abelian group is a group in which the commutative law holds."
#: 材料里确实存在的那句话（正控用的引文）。
VERBATIM = "the commutative law holds"
#: 中文题面（抽不出英文关键词）：改前它照样被打给英文库，报告里却写着"检索 ok"。
CJK_TOPIC = "素数分布中的筛法"


def _fake_search(items, *, seen: list | None = None, report: dict | None = None,
                 raises: Exception | None = None):
    """造一个检索接缝：返回固定条目，并把调用参数记进 `seen`（验契约用）。

    `report` / `raises` 给"逐条判决面"那一组用：生产实现的闭包把 provider
    实例挂在 `provider` 属性上，这里用同一种形态模拟 —— 台账是 `report`
    底下那个 `last_topicality`（裸函数没有它 ⇒ 产物里就没有那几列，
    见 `evidence._report_fields`）。
    """
    holder: dict = {}

    def _s(topic: str, *, limit: int, timeout_sec: float):
        if seen is not None:
            seen.append({"topic": topic, "limit": limit, "timeout_sec": timeout_sec})
        if raises is not None:
            raise raises
        return list(items)

    if report is not None:
        holder["last_topicality"] = dict(report)
        # 只实现"读台账"所需的属性（不是真 provider）：第三态下 provider
        # 已经拒绝发查询，条目一条都没有，所以这里也不需要 http 替身。
        _s.provider = type("_ReportHolder", (), holder)()  # type: ignore[attr-defined]
    return _s


def _report(*, state: str, counts: dict, detail: tuple = (), total: int | None = None,
            query_notes: tuple | None = None) -> dict:
    """一份台账替身（形状与 `providers.TopicalityReport.to_dict()` 相同）。

    `query_notes` 是 `C-4` 之后台账上的查询级字段。刻意用 `None` 表示"这份台账
    没有这条读数"（字段缺席），与"有这条读数但是空的"（空 tuple）分开 ——
    折平它们正是本仓反复踩的那类坑。
    """
    out = {"state": state, "counts": dict(counts), "detail": tuple(detail),
           "total": sum(counts.values()) if total is None else int(total)}
    if query_notes is not None:
        out["query_notes"] = tuple(query_notes)
    return out


def _verdict(title: str, note: str, verdict) -> dict:
    """台账里的一条逐条判决（形状与 `providers.TopicalityVerdict.to_dict()` 相同）。"""
    return {"title": title, "filter_note": note, "verdict": verdict}


#: 替身 HTTP（判据里读真 provider 的逐条判决面时才需要；默认载荷 = 零条目）。
class _HttpStub:
    """`providers.http_get_json` 的替身：记录"真的发出去了"的调用（第三态下应为 0 次）。

    `routes` 让载荷随检索串变化（`C-4a` 的接线判据要造出"整串短语 0 条、
    词项形态 3 条"这一形态）；不给 `routes` 时行为与改前逐字相同。
    """

    def __init__(self, payload: dict | None = None, routes: dict | None = None) -> None:
        self.payload = payload if payload is not None else {"results": []}
        self.routes = dict(routes or {})
        self.calls: list[dict] = []

    def __call__(self, url, params=None, **kwargs):  # noqa: ANN001, ANN003 - 签名随被替者
        got = dict(params or {})
        self.calls.append({"url": url, "params": got})
        return self.routes.get(str(got.get("search", "")), self.payload)


def _real_provider_fns(stub: _HttpStub) -> dict:
    """真 provider + 替身 HTTP：两个源各一个检索函数（形状与生产同形）。"""
    built = P.build_providers(["openalex", "crossref"],
                              config={"min_interval": 0.0, "retries": 0})
    out: dict = {}
    for provider in built:
        def _bound(topic: str, *, limit: int, timeout_sec: float, _p=provider):  # noqa: ANN202
            return _p.search(topic, "precise", "", int(limit))

        # 与生产同形（`evidence._default_sources` 把 provider 挂在这个属性上）。
        _bound.provider = provider  # type: ignore[attr-defined]
        out[provider.name] = _bound
    return out


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


# =================================================== 逐源判决面：三档分列 + filter_note
# 这一组是 `R12-R3-3` 的验收（产物面接线）。改前 `sources_detail` 每条只有
# `{source,status,count,rejected,reason,conflicts}`：三档只挂在 provider 的
# `last_topicality` 上，逐条的 `filter_note` 算完即丢 ⇒ 下游照报告面取数时
# `rejected` 恒 0、弃权不可见（`draft/28` §100.3 的形态）。
# 判据两条：① 三档相加 == 该源候选总数、逐条带 `filter_note`；
# ② 第三态下 `sources_detail[*].status` 逐字是第三态名（不是原因文本里的字）。


def test_sources_detail_has_the_three_columns_and_per_row_notes():
    """正控（`R12-R3-3`）：三档分列相加 == 候选总数，且逐条 `filter_note` 进产物。

    台账里 3 条候选：2 条判过且切题、1 条被剔除。返回值只有 2 条（被剔除的不返回），
    所以 `count(2) != total(3)` 是对的 —— 三档加起来才是候选总数，
    而 `count + rejected` 永远不等于它（`rejected` 那一列说的是"缺来源被拒收"）。
    """
    report = _report(
        state="judged",
        counts={"judged_relevant": 2, "rejected": 1, "unjudged_no_ascii_keywords": 0},
        detail=(
            _verdict("A spectral sequence", "keyword_hit", True),
            _verdict("The Wang sequence", "keyword_hit", True),
            _verdict("Review on motion control", "keyword_miss;similarity=0.07", False),
        ),
    )
    got = E.retrieve(
        "long exact sequence of derived functors", now=TS, limit=5,
        search_fn={"openalex": _fake_search(
            [_source(title="A spectral sequence", doi="10.1000/a"),
             _source(title="The Wang sequence", doi="10.1000/b")],
            report=report)},
    )
    assert got["status"] == "ok", got
    entry = got["sources_detail"][0]
    buckets = entry["topicality_buckets"]
    assert {k: buckets[k] for k in ("judged_relevant", "rejected",
                                    "unjudged_no_ascii_keywords")} == {
        "judged_relevant": 2, "rejected": 1, "unjudged_no_ascii_keywords": 0}
    assert sum(buckets[k] for k in ("judged_relevant", "rejected",
                                    "unjudged_no_ascii_keywords")) == buckets["total"] == 3
    assert buckets["complete"] is True
    assert entry["topicality_state"] == "judged"
    # 逐条 filter_note：三条候选各一句，含被剔除的那一条（改前它连理由一起消失）。
    assert entry["topicality_notes"] == {"keyword_hit": 2,
                                         "keyword_miss;similarity=0.07": 1}
    assert entry["count"] == 2 and entry["rejected"] == 0, \
        "count 是返回值条数、rejected 是缺来源被拒收的条数 —— 都不等于三档之和"


def test_unjudged_column_is_visible_through_the_evidence_layer():
    """正控的同族：弃权（无法判定 ⇒ 放行）必须在产物里可见，且不许被改判成 reject。

    中文 topic + 英文 description 是合法发出的（查询里有英文关键词），
    而逐条判决全部走"弃权"那一支。改前这一跑在 `sources_detail` 里长得
    与"精筛跑过了、一条都不该剔"一模一样。
    """
    report = _report(
        state="judged",
        counts={"judged_relevant": 0, "rejected": 0, "unjudged_no_ascii_keywords": 3},
        detail=tuple(_verdict(f"W{i}", "no_ascii_keywords;not_filtered", None)
                     for i in range(3)),
    )
    got = E.retrieve(
        CJK_TOPIC, now=TS, limit=5,
        search_fn={"openalex": _fake_search(
            [_source(title="W0", doi="10.1000/a"), _source(title="W1", doi="10.1000/b"),
             _source(title="W2", doi="10.1000/c")], report=report)},
    )
    entry = got["sources_detail"][0]
    assert entry["topicality_buckets"]["unjudged_no_ascii_keywords"] == 3
    assert entry["topicality_buckets"]["rejected"] == 0, "弃权不许被改判成 reject"
    assert entry["topicality_notes"] == {"no_ascii_keywords;not_filtered": 3}
    assert entry["topicality_state"] == "judged"
    assert "no_ascii_keywords" in "".join(entry["topicality_notes"]), \
        "逐条理由必须带得出，否则弃权仍然只以一个数字存在"


# ============================================================ `C-4`：查询级事实进产物
#
# 为什么这几句必须进 `sources_detail` 而不是只留日志：`O6 = 0` 那条链的起点就是
# "整串短语零召回 ⇒ 一个源 0 条 ⇒ 材料为空"。只看得见 `count = 0` 时，
# "这一路换了词项串才查到"与"上游本来就没有这个主题"在产物上完全同形。

EN_LONG_TOPIC = "long exact sequence of derived functors in homological algebra"


def test_positive_query_notes_reach_the_sources_detail():
    """正控：台账上的查询级几句话逐字进 `sources_detail`。"""
    report = _report(
        state="judged",
        counts={"judged_relevant": 1, "rejected": 0, "unjudged_no_ascii_keywords": 0},
        detail=(_verdict("A spectral sequence", "keyword_hit", True),),
        query_notes=("phrase_zero_recall_fallback[precise]：整串短语零召回 ⇒ 改词项检索（3 条）",),
    )
    got = E.retrieve(
        EN_LONG_TOPIC, now=TS, limit=5,
        search_fn={"openalex": _fake_search(
            [_source(title="A spectral sequence", doi="10.1000/a")], report=report)},
    )
    entry = got["sources_detail"][0]
    assert entry["topicality_query_notes"] == [
        "phrase_zero_recall_fallback[precise]：整串短语零召回 ⇒ 改词项检索（3 条）"]
    # 与逐条 `filter_note` 分列：两件事不许混进同一个字段。
    assert entry["topicality_notes"] == {"keyword_hit": 1}


def test_negative_control_without_query_notes_the_column_is_absent():
    """负控：台账上没有这条读数 ⇒ 那一列不出现（不是空列表）。

    "三档都是 0"与"没有这条读数"是两件事，这一列照同一条纪律办：
    补一个 `[]` 会让"这次没有降级、也没有哪一路失败"与"查询级事实没接线"
    长得一模一样。
    """
    report = _report(
        state="judged",
        counts={"judged_relevant": 1, "rejected": 0, "unjudged_no_ascii_keywords": 0},
        detail=(_verdict("A spectral sequence", "keyword_hit", True),),
    )
    got = E.retrieve(
        EN_LONG_TOPIC, now=TS, limit=5,
        search_fn={"openalex": _fake_search(
            [_source(title="A spectral sequence", doi="10.1000/a")], report=report)},
    )
    entry = got["sources_detail"][0]
    assert "topicality_query_notes" not in entry, entry
    assert entry["topicality_notes"] == {"keyword_hit": 1}, "逐条那一列照旧"


def test_positive_real_provider_fallback_lands_in_the_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控（端到端）：真 provider + 替身 HTTP ⇒ 降级那件事出现在产物里。

    这一条是"接线真的通了"的证据：上一条正控用的是手造的台账替身，
    只能证明折算函数对；这一条从 `_phrase_query` 的整串短语出发，
    经过真 `OpenAlexProvider.search` 的降级、`_record_topicality` 的台账，
    一路走到 `sources_detail` 的那一列。
    """
    phrase = f'"{EN_LONG_TOPIC}"'
    terms = P._term_query(EN_LONG_TOPIC)
    assert phrase != terms
    stub = _HttpStub(routes={
        phrase: {"results": [], "meta": {"count": 0}},
        terms: {"results": [{"id": "https://openalex.org/W1", "title": "A spectral sequence",
                             "type": "article", "publication_year": 2020,
                             "cited_by_count": 5, "language": "en",
                             "abstract_inverted_index": {"Spectral": [0], "sequences": [1]}}],
                  "meta": {"count": 1}},
    })
    monkeypatch.setattr(P, "http_get_json", stub)
    fns = _real_provider_fns(stub)

    got = E.retrieve(EN_LONG_TOPIC, now=TS, limit=5,
                     search_fn={"openalex": fns["openalex"]})

    entry = got["sources_detail"][0]
    assert entry["status"] == "ok" and entry["count"] == 1, entry
    notes = entry["topicality_query_notes"]
    assert any("phrase_zero_recall_fallback[precise]" in n for n in notes), notes
    assert [c["params"]["search"] for c in stub.calls] == [phrase, terms], \
        "产物说发生了降级，替身必须真的收到过这两条检索串"


def test_negative_control_without_the_report_the_three_columns_are_missing():
    """负控（无台账）：读不到台账 ⇒ 那几列不出现，不补零。

    这一条是"接线真的在起作用"的证明：同一个检索函数，只有当它的
    `last_topicality` 读得到时，正控那两条断言才成立。今天（改前）的形态
    就是这里断言的样子 —— `topicality_buckets` 不在产物里，
    所以"三档分列相加 == 候选总数"这条断言在改前必然红。
    顺带钉住另一半纪律：读不到 ≠ 三档都是 0（补零会把"没接线"重新藏起来）。
    """
    got = E.retrieve(
        "long exact sequence of derived functors", now=TS, limit=5,
        search_fn={"openalex": _fake_search(
            [_source(title="A spectral sequence", doi="10.1000/a"),
             _source(title="The Wang sequence", doi="10.1000/b")])},
    )
    entry = got["sources_detail"][0]
    assert "topicality_buckets" not in entry, "读不到台账时不许编一个三档都是 0 的台账"
    assert "topicality_notes" not in entry
    assert entry["status"] == "ok" and entry["count"] == 2


def test_a_bare_single_search_fn_still_reports_its_source_row():
    """单源路径也要有逐源台账（改前它只有 `sources_status`，没有 detail）。

    报告渲染读的是 `sources_status`，判据读的是 `sources_detail` ——
    两个出口对"这一跑怎么落的"必须给出同一个答案。
    """
    got = E.retrieve(CJK_TOPIC, now=TS, search_fn=_fake_search([_source(title="W0")]))
    assert got["sources_status"] == {"search_fn": "ok"}
    assert [d["source"] for d in got["sources_detail"]] == ["search_fn"]
    assert got["sources_detail"][0]["status"] == "ok"
    assert got["sources_detail"][0]["count"] == 1
    assert got["sources_detail"][0]["conflicts"] == 0


def test_third_state_name_lands_in_sources_detail_status_verbatim(monkeypatch):
    """正控（`R12-R3-3` 的核心）：中文题面 ⇒ 逐源 `status` 逐字是第三态名。

    走真 provider（`build_providers`）+ 替身 HTTP，两个源都不适用 ⇒
    一次上游调用都没有（这是止血那一半，已在 `R12-R3-2` 验证）；
    这里断言的是产物那一半：`sources_detail[*].status` 逐字是
    `query_not_applicable_cjk`，不是闭集里的 `failed` 加上一句自由文本。
    """
    stub = _HttpStub()
    monkeypatch.setattr(P, "http_get_json", stub)
    got = E.retrieve(CJK_TOPIC, limit=3, now=TS, search_fn=_real_provider_fns(stub))
    assert stub.calls == [], "第三态下不许有任何上游请求"
    assert got["status"] == "retrieval_failed" and got["checked"] is False
    assert got["sources"] == [] and got["rejected"] == []
    for source in ("openalex", "crossref"):
        assert got["sources_status"][source] == P.QUERY_NOT_APPLICABLE_CJK
    assert len(got["sources_detail"]) == 2, got["sources_detail"]
    for entry in got["sources_detail"]:
        assert entry["status"] == P.QUERY_NOT_APPLICABLE_CJK, entry
        assert P.QUERY_NOT_APPLICABLE_CJK in entry["reason"]
        assert entry["topicality_state"] == P.QUERY_NOT_APPLICABLE_CJK
        assert entry["topicality_buckets"]["total"] == 0
        assert entry["topicality_buckets"]["complete"] is True
        assert entry["count"] == 0 and entry["rejected"] == 0


def test_source_detail_row_has_exactly_one_construction_point():
    """判据面自证：`sources_detail` 的键集只有 `_source_detail` 一处决定。

    为什么值得一条机器判据：产物新增列的漂移形态是"某个入口少一列"，
    而两个入口（单源 / 多源）各自都自洽、都不会报错。这里把
    "多源行的键 == 单源行的键 == 构造点的键"钉住。
    """
    plain = E._source_detail("x", status="ok", count=0, rejected=0, reason="r")
    multi = E.retrieve("阿贝尔群", now=TS, search_fn={"a": _fake_search([_source()])})
    single = E.retrieve("阿贝尔群", now=TS, search_fn=_fake_search([_source()]))
    assert set(multi["sources_detail"][0]) == set(plain) | {"conflicts"}
    assert set(single["sources_detail"][0]) == set(plain)


def test_negative_control_without_the_summary_the_third_state_is_failed(monkeypatch):
    """负控（拆装置）：把"折进产物"的那三处拆掉 ⇒ 读数退回改前的形态。

    注入的是改前那三处定义（`SOURCE_STATUSES` 的第三态取值、读台账的
    `_topicality_of`、写台账列的 `_report_fields`），所以这一跑的产物
    逐字等于改前：逐源 `status` 退回闭集里的 `failed`、`sources_detail`
    里没有三档、第三态名只剩在 `reason` 自由文本里。正控那两条断言
    （"逐源 status 逐字是第三态名"、"三档分列相加 == 候选总数"）
    在这个注入下必然红 —— 这就是"今天的形态就是红的"那句读数的机器形态。
    """
    stub = _HttpStub()
    monkeypatch.setattr(P, "http_get_json", stub)
    got = E.retrieve(CJK_TOPIC, limit=3, now=TS, search_fn=_real_provider_fns(stub))
    assert got["sources_status"] == {"openalex": P.QUERY_NOT_APPLICABLE_CJK,
                                     "crossref": P.QUERY_NOT_APPLICABLE_CJK}

    monkeypatch.setattr(E, "SOURCE_STATUSES", ("ok", "no_results", "failed"))
    monkeypatch.setattr(E, "_topicality_of", lambda fn: None)
    monkeypatch.setattr(E, "_report_fields", lambda report: {})
    flipped = E.retrieve(CJK_TOPIC, limit=3, now=TS, search_fn=_real_provider_fns(stub))
    assert flipped["sources_status"] == {"openalex": "failed", "crossref": "failed"}, \
        "闭集里没有第三态时，这一跑只能退回 failed（这就是改前的形态）"
    for entry in flipped["sources_detail"]:
        assert entry["status"] == "failed"
        assert "topicality_buckets" not in entry, "拆掉之后台账那一行不许留着三档"
        assert P.QUERY_NOT_APPLICABLE_CJK in entry["reason"], \
            "改前的形态正是：状态名只留在 reason 文本里，机器判不了"


def test_default_production_wiring_folds_the_report(monkeypatch):
    """正控（生产接线）：`search_fn=None`（真 provider）也带得出逐源台账。

    这是"接线真的在生产路径上"的证明：`evidence._default_sources` 造的闭包
    必须把 provider 实例挂出来，否则 `last_topicality` 读不到 ——
    手写的替身读得到不算数，这条走真实现（替身只替换 HTTP）。
    """
    stub = _HttpStub()
    monkeypatch.setattr(P, "http_get_json", stub)
    got = E.retrieve(CJK_TOPIC, limit=3, now=TS)  # search_fn=None ⇒ 生产实现
    assert stub.calls == [], "第三态下不许有任何上游请求"
    assert got["status"] == "retrieval_failed" and got["checked"] is False
    assert got["sources_status"] == {"openalex": P.QUERY_NOT_APPLICABLE_CJK,
                                     "crossref": P.QUERY_NOT_APPLICABLE_CJK}
    assert len(got["sources_detail"]) == 2, got["sources_detail"]
    for entry in got["sources_detail"]:
        assert entry["status"] == P.QUERY_NOT_APPLICABLE_CJK
        assert entry["topicality_state"] == P.QUERY_NOT_APPLICABLE_CJK
        assert entry["topicality_buckets"] == {
            "judged_relevant": 0, "rejected": 0, "unjudged_no_ascii_keywords": 0,
            "total": 0, "complete": True,
        }


def test_default_production_wiring_folds_the_three_columns(monkeypatch):
    """正控（生产接线②）：英文题面的生产路径把三档与逐条 `filter_note` 带进产物。

    三条候选走真 `OpenAlexProvider.search`（替身 HTTP）：两条判过且切题、
    一条被剔除 ⇒ 产物里的三档相加 == 候选总数，且三条的 `filter_note` 都在。
    `CrossrefProvider`（这个替身载荷下解析不出条目）与它各占一行，互不干扰。
    """
    works = [
        {"id": "W1", "title": "A spectral sequence for the homotopy of nice spaces",
         "doi": "10.1000/a", "type": "article", "publication_year": 2020,
         "cited_by_count": 5, "language": "en",
         "open_access": {"is_oa": True, "oa_url": None},
         "primary_location": {"source": {"display_name": "J. Test"}, "pdf_url": None}},
        {"id": "W2", "title": "The Wang sequence for half-exact functors",
         "doi": "10.1000/b", "type": "article", "publication_year": 2020,
         "cited_by_count": 5, "language": "en",
         "open_access": {"is_oa": True, "oa_url": None},
         "primary_location": {"source": {"display_name": "J. Test"}, "pdf_url": None}},
        {"id": "W3", "title": "Review on motion control of autonomous vehicles",
         "doi": "10.1000/c", "type": "article", "publication_year": 2020,
         "cited_by_count": 5, "language": "en",
         "open_access": {"is_oa": True, "oa_url": None},
         "primary_location": {"source": {"display_name": "J. Test"}, "pdf_url": None}},
    ]
    stub = _HttpStub({"results": works, "meta": {"count": len(works)}})
    monkeypatch.setattr(P, "http_get_json", stub)
    got = E.retrieve("long exact sequence of derived functors in homological algebra",
                     limit=5, now=TS)  # 生产实现（多源）
    assert stub.calls, "英文题面必须照旧发出查询"
    entry = {d["source"]: d for d in got["sources_detail"]}["openalex"]
    buckets = entry["topicality_buckets"]
    assert (buckets["judged_relevant"], buckets["rejected"],
            buckets["unjudged_no_ascii_keywords"]) == (2, 1, 0)
    assert buckets["total"] == 3 and buckets["complete"] is True
    assert entry["topicality_state"] == "judged"
    assert entry["topicality_notes"] == {"keyword_hit": 2,
                                         "keyword_miss;similarity=0.07": 1}
    assert entry["count"] == 2, "被剔除的那一条不返回，但它照样要在三档里"
    assert entry["rejected"] == 0, "`rejected` 那一列说的是缺来源被拒收的条数，不是精筛剔除数"


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


def test_acquire_fulltext_ok_records_provenance(tmp_path: Path):
    """③ ok：落盘哈希、页数、抽取后端名、字节数四件 provenance 都要有。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a", "b"]),
                             dest_dir=tmp_path)
    ft = sources[0]["fulltext"]
    assert ft["status"] == "ok" and got["counts"]["ok"] == 1
    assert ft["pages"] == 2 and ft["backend"] == "pdf"
    assert ft["sha256"] == "deadbeef", "下载器给了哈希就用它（同一份文件只算一次）"
    assert ft["bytes"] > 0 and ft["reason"]


def test_acquire_fulltext_writes_only_under_the_given_dest_dir(tmp_path: Path):
    """回归钉子：本文件历史上 8 处写成 `dest_dir="."`，把 `paper.pdf` 写进了仓库根。

    那是实测发生过的事故：`pytest` 的 cwd 是仓库根，假下载器把夹具 PDF 落在 `.`
    就等于「每跑一次测试，仓库根就覆写一次 paper.pdf」——审计期实测仓库根里原有的
    `paper.pdf` 被它从 351623 字节覆盖成 26 字节的夹具文本，而且"同一棵树跑两次
    得到同样的仓库根"这件事从此不成立。

    判据刻意不是"根目录条目集合没变"：旧行为是覆写一个已存在的同名文件，
    条目集合根本不会变，那种写法抓不住这条缺陷。这里盯的是那个具体路径的
    (存在性, 大小, mtime)，它才是这条缺陷的指纹；正向的一半是"夹具必须真的落在
    传进来的 dest_dir 里"（否则这条用例可以靠"什么都没写"骗过去）。
    """
    root = Path(__file__).resolve().parents[1]
    target = root / "paper.pdf"

    def fingerprint(p: Path) -> tuple[bool, int, int]:
        if not p.exists():
            return (False, -1, -1)
        st = p.stat()
        return (True, st.st_size, st.st_mtime_ns)

    before = fingerprint(target)
    sources = [_src_for_fulltext()]
    E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a"]),
                       dest_dir=tmp_path)
    assert fingerprint(target) == before, (
        f"仓库根的 paper.pdf 被这次调用动过：{before} -> {fingerprint(target)}"
    )
    assert (tmp_path / "paper.pdf").is_file(), "夹具 PDF 应该落在传进来的 dest_dir 里"


def test_acquire_fulltext_no_pdf_has_a_reason(tmp_path: Path):
    """③ no_pdf：没有可下载的开放全文 ⇒ 与"下载失败"分处两态。"""
    sources = [_src_for_fulltext(pdf_url=None, url="https://doi.org/10.1000/abelian")]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a"]),
                             dest_dir=tmp_path)
    assert sources[0]["fulltext"]["status"] == "no_pdf"
    assert got["counts"]["no_pdf"] == 1
    assert "没有可下载" in sources[0]["fulltext"]["reason"]


def test_acquire_fulltext_download_failed_has_a_reason(tmp_path: Path):
    """③ download_failed：下载器报失败 ⇒ 理由必须来自它，且不许继续去抽取。"""
    called: list[str] = []

    def _bad(url: str, dest_dir, filename_hint: str):
        return {"ok": False, "path": None, "bytes": 0, "error": "http_403", "http_status": 403}

    def _never(path: str):
        called.append(path)
        raise AssertionError("下载失败后不该去抽取")

    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_bad, extract_fn=_never, dest_dir=tmp_path)
    assert sources[0]["fulltext"]["status"] == "download_failed"
    assert sources[0]["fulltext"]["reason"] == "http_403"
    assert called == [] and got["counts"]["download_failed"] == 1


def test_acquire_fulltext_no_text_layer_means_scanned(tmp_path: Path):
    """③ no_text_layer：能打开、但一页文本都没有（扫描件）⇒ 不是 extract_failed。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(),
                             extract_fn=_extract_pages([]), dest_dir=tmp_path)
    assert sources[0]["fulltext"]["status"] == "no_text_layer"
    assert got["counts"]["no_text_layer"] == 1
    assert "OCR" in sources[0]["fulltext"]["reason"]


def test_acquire_fulltext_extract_failed_keeps_the_exception_type(tmp_path: Path):
    """③ extract_failed：抽取器抛异常 ⇒ 理由里必须带异常类型（不许只说"失败"）。"""
    def _boom(path: str):
        raise RuntimeError("no pdf backend installed")

    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_boom, dest_dir=tmp_path)
    assert sources[0]["fulltext"]["status"] == "extract_failed"
    assert "RuntimeError" in sources[0]["fulltext"]["reason"]
    assert got["counts"]["extract_failed"] == 1


def test_acquire_fulltext_over_limit_is_not_configured_not_no_pdf(tmp_path: Path):
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
                             dest_dir=tmp_path, limit=1)
    assert sources[1]["fulltext"]["status"] == "not_configured"
    assert "没有发起下载" in sources[1]["fulltext"]["reason"]
    assert len(calls) == 1, "超限的来源不许真的去打网络"
    assert got["counts"]["not_configured"] == 1 and got["counts"]["download_failed"] == 1


def test_acquire_fulltext_without_impls_is_not_configured(tmp_path: Path):
    """③ not_configured（第一种含义）：压根没有下载器/抽取器可造。"""
    sources = [_src_for_fulltext()]
    got = E.acquire_fulltext(sources, fetch_fn=None, extract_fn=None, dest_dir=tmp_path)
    # 生产实现是能被 import 的（本仓库里 fetch/extract 都在），所以这里要的是
    # "没有 setup 失败"这一半；真正的"读不到模块"由 `_acquire_impls` 的返回值表达。
    assert got["configured"] is True and got["checked"] is True
    assert isinstance(sources[0]["fulltext"], dict)


# =================================================== 回验分级：level 与 locator
# 这一组是任务 3 的验收，也是整个工作包最关键的两条负控。


def _source_with_fulltext(text_pages: list[str], **kw) -> dict:
    """一条既有摘要又有全文的来源（回验分级的输入形态）。

    形态与生产写侧的内联路径一致：只有 `text_pages`，没有 `text`
    （`text` 是 `"\\n".join(pages)` 的重复，实测无读者；见 `draft/30` §T0-2）。
    """
    src = _src_for_fulltext(**kw)
    src["fulltext"] = {"status": "ok",
                       "text_pages": list(text_pages), "pages": len(text_pages),
                       "text_store": "inline",
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


def test_download_failure_still_verifies_against_the_abstract(tmp_path: Path):
    """⑥ 下载失败 ⇒ download_failed，但整体仍能在有摘要时继续（回验落到摘要级）。

    这一条把"全文没拿到"与"没查成"分开：摘要在手上就是查过了，
    退出码不该因此变成 2，级别如实停在摘要级。
    """
    sources = [_src_for_fulltext()]

    def _bad(url: str, dest_dir, filename_hint: str):
        return {"ok": False, "error": "network_error: timed out"}

    got = E.acquire_fulltext(sources, fetch_fn=_bad, extract_fn=_extract_pages(["x"]),
                             dest_dir=tmp_path)
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


# ================== `R2-AN-5` / `R2-AN-6`：比过了没找到 ≠ 没有可比文本；拒绝判定要有名字 两条缺陷都在"`_check_quote_levels` 的第五个返回值 / `_read_verdict` 的默认值"这一小段里：
# - `R2-AN-5`：「有全文、没有摘要、全文逐字比过但没命中」从前返回 `comparable=False`，调用方把它读成"这条
#   来源没有可比文本" ⇒ 台账落 `unknown` + `no_comparable_text_in_any_source`。判决与理由都是不实陈述：全文
#   真的比过、结论是"没找到"（方向是 fail-closed，但硬事实被丢掉，而且假理由会真的写进库，`draft/28` §40.4）。
# - `R2-AN-6`：`_read_verdict` 在 `verified is None` 时默认给 `"unknown"`，于是调用方那句
#   `or "verifier_refused_to_judge"` 永远走不到 —— 一个更具体的字面量成了死词汇；默认值因此搬进
#   `_read_verdict`（唯一一处定义）。同一条修法里不许顺手删掉 `or "not_found"`：`verified=False` 时第二项可以是
#   空串（与 `verified is None` 不同），那条兜底是可达的 —— 下面最后一条用例守它。


def _verdict_fn(verified, reason=""):
    """回验器的桩：逐字比对本身是 `quoteverify` 的事，本组只测"判决怎么被记下来"。"""
    def _f(doc, quote, page_range, widen=0, allow_fulltext_fallback=False):
        return {"verified": verified, "reason": reason}
    return _f


#: 一条只有全文、没有摘要的来源（`R2-AN-5` 的形态）。
_FULL_ONLY_SRC = {"source_id": "S1", "fulltext": {"status": "ok", "text_pages": ["alpha beta"]}}
_MISS_CLAIM = {"text": "断言", "quote": "zzz-not-here", "evidence_source": "S1"}


def test_a_fulltext_compared_and_missed_is_not_found_not_unchecked():
    """正控（`R2-AN-5`）：全文比过了、逐字没找到、这条来源没有摘要 ⇒ `not_found` + 真理由。"""
    res = E.verify_claims([_MISS_CLAIM], [_FULL_ONLY_SRC], quote_fn=_verdict_fn(False, "quote_absent"))
    row = res["claims"][0]
    assert (row["verdict"], row["reason"]) == ("not_found", "quote_absent")
    assert row["reason"] != "no_comparable_text_in_any_source", (
        "全文真的比过 ⇒ 不许写成'一条来源都没比对过'"
    )
    assert row["checked"] is True, "这是查过了（比过了、没找到），不是没查成"


def test_a_fulltext_hit_without_an_abstract_is_still_verified_at_fulltext_level():
    """防误伤（`R2-AN-5`）：同一条来源命中 ⇒ 仍是 `verified` / `fulltext` 级。"""
    res = E.verify_claims([_MISS_CLAIM], [_FULL_ONLY_SRC], quote_fn=_verdict_fn(True, "substring_match"))
    row = res["claims"][0]
    assert (row["verdict"], row["level"], row["checked"]) == ("verified", "fulltext", True)


def test_a_refusing_verifier_is_recorded_under_its_own_name():
    """正控（`R2-AN-6`）：回验器拒绝判定 ⇒ 理由写 `verifier_refused_to_judge`。

    两处都读：读法（`_read_verdict`）与结果（`verify_claims` 落的那一行）。
    只读前者会漏掉"调用方又加了一层同义兜底"这种改法，只读后者会漏掉
    "默认值放错层"。
    """
    assert E._read_verdict({"verified": None, "reason": ""}) == (None, "verifier_refused_to_judge")
    assert E._read_verdict({"verified": None}) == (None, "verifier_refused_to_judge")
    res = E.verify_claims([_MISS_CLAIM], [_FULL_ONLY_SRC], quote_fn=_verdict_fn(None, ""))
    row = res["claims"][0]
    assert row["verdict"] == "unknown", "拒绝判定仍是 unknown 判决（不许折成 not_found）"
    assert row["reason"] == "verifier_refused_to_judge"
    assert row["checked"] is False


def test_a_not_found_verdict_without_a_reason_keeps_the_not_found_fallback():
    """负控（`R2-AN-6` 的边界）：`verified=False` 且回验器没给理由 ⇒ 兜底仍是 `not_found`。

    这一条守的是"别把 `or "not_found"` 一起删掉"：`verified=False` 时第二项可以是
    空串（探针 `D2`），所以那条兜底可达。删掉它会写出 `reason=''` 的台账行 ——
    一条没有理由的判决。
    """
    assert E._read_verdict({"verified": False, "reason": ""}) == (False, "")
    src = {"source_id": "S2", "abstract": "gamma delta"}
    res = E.verify_claims([{"text": "断言", "quote": "zzz", "evidence_source": "S2"}], [src],
                          quote_fn=_verdict_fn(False, ""))
    row = res["claims"][0]
    assert (row["verdict"], row["reason"], row["checked"]) == ("not_found", "not_found", True)


def test_acquire_statuses_are_a_controlled_vocabulary():
    """③ 的同族：六态词表是判据，改坏它要让用例红（写在两处的判据早晚会漂移）。

    `SOURCE_STATUSES` 同样不许含糊：第三态（这一问压根没发给这个源）与
    `ok` / `no_results` / `failed` 是四件不同的事，把它折回 `failed`
    会让"未接线"重新与"上游坏了"同形（`R12-R3-3` 的产物面缺口）。
    """
    assert E.ACQUIRE_STATUSES == ("ok", "no_pdf", "download_failed", "no_text_layer",
                                  "extract_failed", "not_configured")
    assert E.EVIDENCE_LEVELS == ("abstract", "fulltext")
    assert E.SOURCE_STATUSES == ("ok", "no_results", "failed",
                                 "query_not_applicable_cjk", "query_empty")
    # 第三态名与禁改区 `providers` 侧逐字相同（不许另立一套拼写）。
    P = pytest.importorskip("agentflow.providers")
    assert E.SOURCE_STATUSES[3] == P.QUERY_NOT_APPLICABLE_CJK
    assert E.SOURCE_STATUSES[4] == P.QUERY_EMPTY

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


# ======================================================================
# 正文存哪：内联 vs 内容寻址引用（依据 `draft/30` §T0-2 / §T0-3 / §T0-4）
#
# 这一组守的是"整本书的正文只存一份"这件事的两个方向：
# 写侧两种形态都自报家门（`text_store`），读侧两种形态都必须能核，
# 而引用坏了必须被点名计数 —— 不许折成"这篇没有全文"。
# ======================================================================


def test_inline_fulltext_keeps_pages_and_drops_the_dead_text_field(tmp_path: Path):
    """不给 store 目录 ⇒ 逐页文本内联，且不再写那个没人读的 `text` 字段。"""
    sources = [_src_for_fulltext()]
    E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a", "b"]),
                       dest_dir=tmp_path)
    ft = sources[0]["fulltext"]
    assert ft["text_store"] == "inline"
    assert ft["text_pages"] == ["a", "b"]
    assert "text_ref" not in ft
    assert "text" not in ft, "`text` 是 join(pages) 的重复，全仓实测无读者"


def test_ref_fulltext_stores_once_and_records_the_reference(tmp_path: Path):
    """给 store 目录 ⇒ 正文存进 `.fulltext`，产物里只留引用（且不带 text_pages）。"""
    store = tmp_path / ".fulltext"
    sources = [_src_for_fulltext()]
    E.acquire_fulltext(sources, fetch_fn=_fetch_ok(), extract_fn=_extract_pages(["a", "b"]),
                       dest_dir=tmp_path, text_store_dir=store)
    ft = sources[0]["fulltext"]
    assert ft["text_store"] == "ref"
    assert "text_pages" not in ft and "text" not in ft
    ref = ft["text_ref"]
    assert Path(ref["path"]).parent == store and Path(ref["path"]).is_file()
    assert ref["pages"] == 2 and ft["chars"] == 2

    # 幂等：同一份正文再存一次，不新增文件（内容寻址的意义就在这里）
    E.acquire_fulltext([_src_for_fulltext()], fetch_fn=_fetch_ok(),
                       extract_fn=_extract_pages(["a", "b"]),
                       dest_dir=tmp_path, text_store_dir=store)
    assert len(list(store.glob("*.json"))) == 1


def test_ref_and_inline_give_the_same_verdict_level_and_locator(tmp_path: Path):
    """两种存法对同一条引文必须给出同一判决、同一级别、同一页号。"""
    pages = ["Page one is about something else.", f"Page two states that {_FT_QUOTE}."]
    inline = _source_with_fulltext(pages)
    ref_src = _src_for_fulltext()
    E.acquire_fulltext([ref_src], fetch_fn=_fetch_ok(), extract_fn=_extract_pages(pages),
                       dest_dir=tmp_path, text_store_dir=tmp_path / ".fulltext")
    claims = [{"text": "单位元唯一", "quote": _FT_QUOTE}]
    a = E.verify_claims(claims, [inline])["claims"][0]
    b = E.verify_claims(claims, [ref_src])["claims"][0]
    assert (a["verdict"], a["level"], a["locator"]) == (b["verdict"], b["level"], b["locator"])
    assert a["level"] == "fulltext" and a["locator"] == {"kind": "page", "page": 2}


def test_broken_ref_is_counted_and_never_read_as_no_fulltext(tmp_path: Path):
    """坏引用（store 文件被删）⇒ 降级 + 点名计数 + 理由不说是"这篇没有全文"。"""
    store = tmp_path / ".fulltext"
    src = _src_for_fulltext()
    E.acquire_fulltext([src], fetch_fn=_fetch_ok(),
                       extract_fn=_extract_pages([f"x {_FT_QUOTE}"]),
                       dest_dir=tmp_path, text_store_dir=store)
    Path(src["fulltext"]["text_ref"]["path"]).unlink()

    res = E.verify_claims([{"text": "单位元唯一", "quote": _FT_QUOTE}], [src])
    row = res["claims"][0]
    assert row["level"] != "fulltext", "引用取不到时绝不许报全文级"
    assert res["counts"]["fulltext_text_unavailable"] == 1
    assert "store_file_missing" in " ".join(res["check"]["fulltext_text_unavailable"])
    assert "store_file_missing" in res["reason"]
    assert "不是'这篇没有全文'" in res["reason"]


def test_unavailable_key_is_absent_when_nothing_is_broken():
    """键只在真出问题时出现：常驻的空列表会让读者以为"这一栏永远是空的、所以没问题"。"""
    src = _source_with_fulltext([f"body text with {_FT_QUOTE}"])
    res = E.verify_claims([{"text": "单位元唯一", "quote": _FT_QUOTE}], [src])
    assert "fulltext_text_unavailable" not in res["check"]
    assert "fulltext_text_unavailable" not in res["counts"]
