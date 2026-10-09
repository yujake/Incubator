# -*- coding: utf-8 -*-
"""`precise` 的第三档降级：主串与词项串都零召回时，退到"只用 topic"（脱开 description）。

## 这条判据守的是什么（真机读数）

T2 第 23 趟（`t2r`，2026-10-10）的 `projects/p6t-research-from-zero/data/search_requests.json`
里，`r-0002` / `r-0004` / `r-0006` 三次 topic=`edge-girth-regular graphs`、`mode=precise`、
带一段 ~30 词的 `content_description` ⇒ 三次全 `no_results`（`attempts=1`、`last_error=null`），
而同一天放宽成 `girth-regular graphs` 的 `r-0005` 一次取回 5 篇。本机现算（`temp/_probe_retrieval2.py`）
把这两条参数逐字打一遍：`r-0002` 的主串与降级串都是 0 条（上游 `meta.count=0`，不是被
标题过滤掉），而同一个 topic 只要脱开那段 description 就是 10 条 —— 含标题逐字是
《Edge-girth-regular graphs》的那一篇。也就是说"查不到"的真原因是查询串太长，
而既有的两档降级都带着 description 的词项，两档一起归零。

## 判据的形状（红/绿成对 + 反真空）

* 正控：两档都 0、第三档有 ⇒ 真的换到第三档、结果回得来、台账两句话都写出来；
* 负控①（"降级不许变成每次都发三遍"）：第一档就有结果 ⇒ 只发 1 次，第三档一次都不发；
* 负控②（"换了也没查到"与"换到了"分得开）：三档全 0 ⇒ 结果仍是 0，但读数里
  `last_resort_count == 0`，且台账确实记着"退到第三档"这件事；
* 反真空①：description 为空时 `last_resort` 必须是空串（第一档已经是"只用 topic"，
  第三档会是一条一模一样的请求）；
* 反真空②：第三档串真的不含 description 里的词、且含 topic。
"""
from __future__ import annotations

import pytest

from agentflow import providers as P

TOPIC = "edge-girth-regular graphs"
DESCRIPTION = (
    "Search for literature on edge-girth-regular graphs (graphs where every edge lies "
    "in the same number of girth cycles), girth-regular graphs, and cages."
)


def _work(title: str) -> dict:
    return {
        "id": f"https://openalex.org/W{abs(hash(title)) % 10**8}",
        "title": title,
        "doi": None,
        "type": "article",
        "publication_year": 2020,
        "cited_by_count": 5,
        "language": "en",
        "open_access": {"is_oa": True, "oa_url": None},
        "primary_location": {"source": {"display_name": "J. Test"}, "pdf_url": None},
    }


TOPIC_ONLY_WORKS = [
    _work("Edge-girth-regular graphs"),
    _work("Extremal edge-girth-regular graphs"),
]


class _RoutingStub:
    """按检索串分派的替身（记录每一次真的发出去的串）。"""

    def __init__(self, routes: dict | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[dict] = []

    def __call__(self, url, params=None, **kwargs):  # noqa: ANN001, ANN003 - 替身签名随被替者
        got = dict(params or {})
        self.calls.append({"url": url, "params": got, "kwargs": dict(kwargs)})
        return self.routes.get(str(got.get("search", "")), {"results": [], "meta": {"count": 0}})

    @property
    def search_texts(self) -> list[str]:
        return [str(c["params"].get("search", "")) for c in self.calls]


def _provider(stub: _RoutingStub) -> P.OpenAlexProvider:
    P.http_get_json = stub
    return P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))


def _plans(description: str = DESCRIPTION) -> list[P._QueryPlan]:
    return P._plan_mode("precise", TOPIC, description, 5)


def test_anti_vacuum_1_empty_description_has_no_third_tier() -> None:
    """反真空①：description 为空时第三档必须是空串（否则就是一条重复请求）。"""
    plan = _plans("")[0]
    assert plan.template["search"] == f'"{TOPIC}"'
    assert plan.fallback == P._term_query(TOPIC)
    assert plan.last_resort == "", plan.last_resort


def test_anti_vacuum_2_third_tier_drops_the_description_and_keeps_the_topic() -> None:
    """反真空②：第三档串脱开 description、保留 topic，且与前两串都不同。"""
    plan = _plans()[0]
    assert plan.last_resort, "带 description 时必须有第三档"
    assert plan.last_resort == P._term_query(TOPIC)
    for word in ("literature", "cycles", "cages", "Search"):
        assert word.lower() not in plan.last_resort.lower(), (word, plan.last_resort)
    assert "girth-regular" in plan.last_resort
    assert plan.last_resort not in (plan.template["search"], plan.fallback)


def test_positive_two_zero_tiers_fall_back_to_the_topic_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：前两档都 0 条 ⇒ 第三档真的发出去，结果回得来，台账两句话都写出来。"""
    plan = _plans()[0]
    stub = _RoutingStub({plan.last_resort: {"results": TOPIC_ONLY_WORKS,
                                            "meta": {"count": len(TOPIC_ONLY_WORKS)}}})
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(TOPIC, "precise", DESCRIPTION, 5)

    assert [c.title for c in got] == [w["title"] for w in TOPIC_ONLY_WORKS]
    assert stub.search_texts == [plan.template["search"], plan.fallback, plan.last_resort]
    assert provider.stats["phrase_fallbacks"] == 1
    assert provider.stats["last_resort_fetches"] == 1
    record = provider.last_phrase_fallbacks["precise"]
    assert record["count"] == 0
    assert record["last_resort"] == plan.last_resort
    assert record["last_resort_count"] == len(TOPIC_ONLY_WORKS)
    # "实际发出的检索串"是产出结果的那一条（`FINAL-R3-03` 的同一口径）。
    assert provider.last_query_text == {"precise": plan.last_resort}
    assert provider.last_topicality is not None
    notes = provider.last_topicality.query_notes
    assert any("last_resort_used[precise]" in n for n in notes), notes
    assert any("phrase_zero_recall_fallback[precise]" in n for n in notes), notes


def test_negative_control_1_results_on_the_first_query_send_exactly_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控①：第一档就有结果 ⇒ 只发 1 次；第三档一次都不许发。

    没有这一条，"降级"会退化成"每条查询都发三遍"，而那正好发生在限流附近。
    """
    plan = _plans()[0]
    stub = _RoutingStub({plan.template["search"]: {"results": TOPIC_ONLY_WORKS,
                                                   "meta": {"count": len(TOPIC_ONLY_WORKS)}}})
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(TOPIC, "precise", DESCRIPTION, 5)

    assert [c.title for c in got] == [w["title"] for w in TOPIC_ONLY_WORKS]
    assert len(stub.search_texts) == 1, stub.search_texts
    assert provider.stats["phrase_fallbacks"] == 0
    assert provider.stats["last_resort_fetches"] == 0
    assert provider.last_phrase_fallbacks == {}


def test_negative_control_2_all_three_tiers_empty_is_still_zero_but_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控②：三档全 0 ⇒ 结果仍是 0 条，但读数里"退到第三档也 0"与"没退"分得开。

    这一条防的是"用一次更宽的查询把 `no_results` 洗掉"：第三档没有结果时，
    台账上必须留下 `last_resort_count=0` 这条如实读数，而不是不留痕迹。
    """
    plan = _plans()[0]
    stub = _RoutingStub({})
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(TOPIC, "precise", DESCRIPTION, 5)

    assert got == []
    assert stub.search_texts == [plan.template["search"], plan.fallback, plan.last_resort]
    assert provider.stats["last_resort_fetches"] == 1
    record = provider.last_phrase_fallbacks["precise"]
    assert record["count"] == 0 and record["last_resort_count"] == 0
    assert provider.last_topicality is not None
    assert any("last_resort_used[precise]" in n for n in provider.last_topicality.query_notes)
