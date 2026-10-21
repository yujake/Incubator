"""`X-NEW-1`（题 1 的 D 选项）的判据：检索相关性的 fail-closed 止血。
## 这条缺陷在说什么（`draft/28` §100.2 / §102.3 的第一手读数）
中文题面走产品默认路径（`evidence.retrieve(topic, search_fn=None)`）时：
* `providers._ascii_keywords` 只抓英文词 ⇒ 纯中文题面抽出 0 个关键词；* 于是 `keyword_hit` 返回 `None`（"无法判定"）⇒
`_precise_keep` 逐条弃权（`filter_note = no_ascii_keywords;not_filtered`、`keep` 全 `True`）；*
而中文原串照样被打给英文库（`provenance.query_by_source` 记的就是它）；* 结果：23 条来源里 7 条与题面一个二字片段都不重合，报告里却写着"检索 ok"。
D 选项只做止血，不动判据口径：`keyword_hit` 的"宁可不过滤也不能误杀"是刻意取舍（docstring 逐字），所以这里既不许把"弃权"改判成 `reject`，也不许引入阈值过滤（那是被否掉的 C 选项）。改动只有两条：
1. 抽不出任何英文关键词 ⇒这一问不发给以英文文献为主的上游库，落第三态 `query_not_applicable_cjk`（抛 `ProviderError` ⇒ 调用方`evidence` 把它记进逐源
`sources_detail[].reason`，不再算"检索成功"）；2. 改前算完就丢的逐条判决（连同 `filter_note`）落成台账（`TopicalityReport`：三档分列的数 + 每条一句话），"弃权"从此可见。
## 这一份用例的读法
名字前缀就是读数分类：`test_positive_*` = 正控（行为照旧的那些），`test_negative_control_*` = 负控（证明判据有牙、注入真的生效）。
全部离线：`http_get_json` 一律换成替身，零 API 花费，不打 OpenAlex/Crossref。`_provider(stub)` 会把模块级 `http_get_json` 真的绑成它收到的那个替身（`R12-R3-2`），
所以这条保证由每条用例自己的夹具兑现，不靠 fixture 顺带做的monkeypatch —— 后者会让"零上游调用"的断言守的其实是另一个名字。
## `Y-1` 的追加判据（本文件的第二组正控）
`MultiProvider.last_stats[*].status` 与 `PROVIDER_STAT_STATUSES` 改前仍是`('not_run','ok','failed')`，于是同一件"这一问根本没发出去"在
`evidence` 侧是第三态名（`query_not_applicable_cjk` / `query_empty`，见 `R12-R3-3`），在 providers 统计面上却是 `failed`（"上游坏了"）。下面"正控：统计面与
`evidence` 侧的第三态对齐"那一节把两个出口钉在同一个取值上，并同时钉住"另外两档没有跟着被吞掉"。
"""

from __future__ import annotations

import pytest

from agentflow import providers as P

# ============================================================ 替身与夹具（不联网）

EN_TOPIC = "long exact sequence of derived functors in homological algebra"
CJK_TOPIC = "素数分布中的筛法"
MIXED_TOPIC = "素数分布中的筛法 sieve methods"


class _HttpStub:
    """`http_get_json` 的替身：记录每一次"真的发出去了"的调用，返回预置载荷。

    记录 `params` 而不是只记调用次数：判据要问的是"中文原串有没有被打出去"，
    而"发出去了"与"发出去了什么"是两件事（前者能被一次无关请求满足）。
    """

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload if payload is not None else {"results": []}
        self.calls: list[dict] = []

    def __call__(self, url, params=None, **kwargs):  # noqa: ANN001, ANN003 - 替身签名随被替者
        self.calls.append({"url": url, "params": dict(params or {}), "kwargs": dict(kwargs)})
        return self.payload

    @property
    def calls_count(self) -> int:
        return len(self.calls)

    @property
    def search_texts(self) -> list[str]:
        """每一次调用真正送出去的检索串（OpenAlex 的 `search` 参数）。"""
        return [str(c["params"].get("search", "")) for c in self.calls]


def _work(title: str, *, doi: str = "", year: int = 2020, cited: int = 5) -> dict:
    """一条 OpenAlex work（只填解析端真正读的字段）。"""
    return {
        "id": f"https://openalex.org/W{abs(hash(title)) % 10**8}",
        "title": title,
        "doi": doi or None,
        "type": "article",
        "publication_year": year,
        "cited_by_count": cited,
        "language": "en",
        "open_access": {"is_oa": True, "oa_url": None},
        "primary_location": {"source": {"display_name": "J. Test"}, "pdf_url": None},
    }


#: 英文精筛的三条：两条命中、一条不命中（用来证明 `rejected` 这一档真的会出现，
#: 而不是"三档里永远只有第一档有数"）。
EN_WORKS = [
    _work("A spectral sequence for the homotopy of nice spaces", doi="10.1000/a"),
    _work("The Wang sequence for half-exact functors", doi="10.1000/b"),
    _work("Review on motion control of autonomous vehicles", doi="10.1000/c"),
]


def _provider(stub: _HttpStub) -> P.OpenAlexProvider:
    """构造一个不会真的连网、也不会因限速睡着的 OpenAlex provider。

    形参 ``stub`` 真的被接上：provider 内部按模块级名字查 ``http_get_json``，
    所以这里显式把这个名字绑成收到的那个记录型替身。为什么不靠 `stub` fixture
    顺带做的 monkeypatch：那会让"零上游调用"的断言守的其实是模块级那个名字，
    而这个函数的形参从头到尾没被读过（`R12-R3-2` 的 `STUB_PARAM_UNUSED`）——
    将来那处 fixture 守卫一旦回归，用它的用例就会真的去打 `api.openalex.org`。
    """
    P.http_get_json = stub
    return P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))


@pytest.fixture()
def stub(monkeypatch: pytest.MonkeyPatch) -> _HttpStub:
    """把 `http_get_json` 换成替身（模块级名字，provider 内部按名查）。"""
    s = _HttpStub({"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}})
    monkeypatch.setattr(P, "http_get_json", s)
    return s


# ============================================================ 夹具自身的正控


def test_positive_provider_helper_binds_the_stub_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：`_provider(stub)` 收到的那个替身必须真的接上（`R12-R3-2`）。

    这一条刻意不用 `stub` fixture：fixture 会顺带 monkeypatch 模块级
    `http_get_json`，于是"零上游调用"那几条断言由 fixture 兜住，而"`_provider`
    有没有读它自己的形参"这件事在读数上不可分辨。这里只把一个替身交给 `_provider`。

    装置上的第二道替身（`tripwire`）：绑定若没发生，检索就会落到它头上 ——
    于是"删掉绑定那一行"让判据红在 `local.calls_count == 1` 上，
    而不会真的去打 `api.openalex.org`（守卫回归的代价是一次真实请求，
    正是本 finding 的 impact，所以负控装置本身也不许联网）。
    反过来说，正控下 `tripwire.calls_count == 0` 就是"绑定真的发生了"的证据。
    """
    local = _HttpStub({"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}})
    tripwire = _HttpStub({"results": []})
    monkeypatch.setattr(P, "http_get_json", tripwire)

    provider = _provider(local)
    got = provider.search(EN_TOPIC, "precise", "", 5)

    assert local.calls_count == 1, (
        "`_provider` 必须把它收到的替身绑成模块级 `http_get_json`；"
        f"实收 calls={local.calls_count}（0 = 形参又没被读，`R12-R3-2` 的原形态）"
    )
    assert tripwire.calls_count == 0, "绑定没有发生的证据：第二道替身接到了请求"
    assert local.search_texts and EN_TOPIC in local.search_texts[0], local.search_texts
    assert [c.title for c in got] == [EN_WORKS[0]["title"], EN_WORKS[1]["title"]]
    assert P.http_get_json is local, "绑定必须落在模块级名字上（provider 内部按名查）"


# ============================================================ 正控①：英文题面照旧


def test_positive_english_topic_still_dispatches_and_judges(stub: _HttpStub) -> None:
    """英文题面：查询原样发出、逐条判决照旧、三档分列有数。

    这一条是"没有改变检索行为"的正控：它断言的是改前就成立的那部分
    （查询串 = 短语化后的英文题面、命中即保留）。
    """
    provider = _provider(stub)
    got = provider.search(EN_TOPIC, "precise", "", 5)

    assert stub.calls_count >= 1, "英文题面必须照旧发出查询"
    assert all(EN_TOPIC in text for text in stub.search_texts), stub.search_texts
    assert [c.title for c in got] == [EN_WORKS[0]["title"], EN_WORKS[1]["title"]]

    report = provider.last_topicality
    assert report is not None and report.state == "judged"
    assert report.counts() == {
        "judged_relevant": 2, "rejected": 1, "unjudged_no_ascii_keywords": 0,
    }
    assert report.complete and report.total == 3
    assert provider.last_query_provenance[0]["dispatched"] is True


def test_positive_precise_filter_keeps_its_old_verdicts(stub: _HttpStub) -> None:
    """逐条判决与 `_precise_keep` 的取舍逐条一致（判决不许被重算成第二套口径）。

    `rejected` 的那一条必须真的被判成"不命中"，而不是被记成"无法判定"：
    这两档在产物里是不同的列，折在一起就等于把弃权重新藏起来。
    `None`（弃权）与 `True`（切题）也必须分得开 —— `_precise_keep` 对两者
    都返回 `keep=True`，只有三态判决能把它们分开。
    """
    provider = _provider(stub)
    provider.search(EN_TOPIC, "precise", "", 5)
    report = provider.last_topicality
    assert report is not None

    by_title = {v.title: v for v in report.detail}
    assert by_title[EN_WORKS[0]["title"]].verdict is True
    assert by_title[EN_WORKS[1]["title"]].verdict is True
    assert by_title[EN_WORKS[2]["title"]].verdict is False
    assert by_title[EN_WORKS[2]["title"]].filter_note.startswith("keyword_miss")

    # 同一个输入上 `keyword_hit` 与台账里的判决逐条相同（口径只有一处）。
    for verdict in report.detail:
        assert P.keyword_hit(EN_TOPIC, verdict.title) is verdict.verdict, verdict


# ============================================================ 正控②：中文题面落第三态


def test_positive_cjk_topic_lands_in_third_state_and_never_dispatches(stub: _HttpStub) -> None:
    """中文题面：落 `query_not_applicable_cjk`，且一次上游调用都没有发出去。

    "没发出去"是本条的核心：改前的形态是"发了，而且发的就是中文原串"。
    """
    provider = _provider(stub)
    with pytest.raises(P.ProviderError) as excinfo:
        provider.search(CJK_TOPIC, "precise", "", 5)

    assert P.QUERY_NOT_APPLICABLE_CJK in str(excinfo.value)
    assert stub.calls_count == 0, "第三态下不许有任何上游请求"
    assert stub.search_texts == []

    report = provider.last_topicality
    assert report is not None
    assert report.state == P.QUERY_NOT_APPLICABLE_CJK
    assert report.counts() == {
        "judged_relevant": 0, "rejected": 0, "unjudged_no_ascii_keywords": 0,
    }, "拒绝路径一条候选都没取回来 ⇒ 三档必须全是 0（不是'0 条被剔除'）"
    assert report.total == 0 and report.complete

    provenance = provider.last_query_provenance
    assert len(provenance) == 1
    assert provenance[0]["dispatched"] is False
    assert provenance[0]["state"] == P.QUERY_NOT_APPLICABLE_CJK
    assert CJK_TOPIC in provenance[0]["query_text"]
    assert provider.last_query_text == {}, "没有发出去的查询不许出现在'已发出'里"


def test_positive_third_state_shows_up_in_evidence_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    """第三态必须能被调用方读到（`evidence` 逐源 reason 里逐字出现状态名）。

    这里用真 provider 配替身 HTTP 走一遍 `evidence.retrieve` 的多源路径：
    两个源都不适用 ⇒ 检索落"没查成"，`sources_detail` 的 reason 里带着状态名，
    而不是 `status=ok` + `count>0` 的那种"检索成功"。
    """
    from agentflow import evidence as E

    stub = _HttpStub({"results": EN_WORKS})
    monkeypatch.setattr(P, "http_get_json", stub)

    built = P.build_providers(["openalex", "crossref"], config={"min_interval": 0.0, "retries": 0})

    def _search(topic: str, *, limit: int, timeout_sec: float, _p=None):  # noqa: ANN001, ANN202
        return _p.search(topic, "precise", "", int(limit))

    fns = {p.name: (lambda topic, *, limit, timeout_sec, _p=p: _search(
        topic, limit=limit, timeout_sec=timeout_sec, _p=_p)) for p in built}
    got = E.retrieve(CJK_TOPIC, limit=3, search_fn=fns, now="T")

    assert stub.calls_count == 0, "两个源都不该发请求"
    assert got["status"] != "ok", "不许再把'这一问不适用'报成检索成功"
    assert got["checked"] is False
    detail = {d["source"]: d for d in got["sources_detail"]}
    assert detail, got
    for entry in detail.values():
        assert P.QUERY_NOT_APPLICABLE_CJK in entry["reason"], entry
    assert got["sources"] == []


def test_positive_mixed_language_topic_is_still_dispatched(stub: _HttpStub) -> None:
    """中英混排题面照旧发出（按关键词判，不按字符集判 ⇒ 不误杀这一类）。"""
    provider = _provider(stub)
    provider.search(MIXED_TOPIC, "topical", "", 3)
    assert stub.calls_count >= 1
    assert provider.last_query_provenance[0]["dispatched"] is True
    assert "sieve" in provider.last_query_provenance[0]["query_text"]


def test_positive_empty_query_is_its_own_state(stub: _HttpStub) -> None:
    """空查询是第三种落法（`query_empty`），不与"语言不适用"折成同一个取值。"""
    provider = _provider(stub)
    assert provider.search("", "topical", "", 3) == []
    assert stub.calls_count == 0
    report = provider.last_topicality
    assert report is not None and report.state == P.QUERY_EMPTY
    assert P.query_applicability("", "").state == P.QUERY_EMPTY


# ============================================================ 正控③：拒绝不留上一跑的读数


def test_positive_refusal_resets_stale_query_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：拒绝那一跑之后，诊断面读的三个字段必须与"我没问"一致（`R12-R3-1`）。

    `tools/search_tools._provider_diagnostics` 读的是 `last_query_text` /
    `last_filter_notes` / `last_filtered_out`（"为什么只回来 2 条"的唯一可查证据），
    而 `_resolve_provider` 把 provider 实例缓存在 `ctx.providers` 里 ⇒ 同一个对象
    会被反复读。改前只清 `last_query_provenance`，于是同一个对象上出现两个互相
    矛盾的读数：`dispatched: false`（这一跑一个请求都没发）配着上一跑的检索串
    与过滤计数。这条判据先把"上一跑真的留下了读数"钉住，再问它有没有被清掉。

    夹具自己 monkeypatch（不用 `_provider` 的绑定）：这条判据问的是拒绝路径的复位，
    与"夹具怎么接上替身"是两件事，两者混在一起会让负控互相牵连。
    """
    from agentflow.tools import search_tools as ST

    local = _HttpStub({"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}})
    monkeypatch.setattr(P, "http_get_json", local)
    provider = P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))

    provider.search(EN_TOPIC, "precise", "", 5)
    # 先证明这条判据不是守着一个恒空的对象：英文那一跑必须留下三种读数。
    assert provider.last_query_text, "英文那一跑必须留下检索串"
    assert provider.last_filter_notes, "英文那一跑必须留下过滤原因计数"
    assert provider.last_filtered_out > 0, "英文那一跑必须留下被剔除的条数"
    assert local.calls_count == 1

    with pytest.raises(P.ProviderError) as excinfo:
        provider.search(CJK_TOPIC, "topical", "", 3)
    assert P.QUERY_NOT_APPLICABLE_CJK in str(excinfo.value)

    assert provider.last_query_text == {}, provider.last_query_text
    assert provider.last_filter_notes == {}, provider.last_filter_notes
    assert provider.last_filtered_out == 0, provider.last_filtered_out
    # 读数面（下游真正看的那个函数）与上面三条同源，必须一起翻面。
    diagnostics = ST._provider_diagnostics(provider)
    assert diagnostics["last_query_text"] == {}
    assert diagnostics["last_filter_notes"] == {}
    assert diagnostics["last_filtered_out"] == 0
    # `stats` 是累积量（docstring 逐字："累积请求次数 / 解析失败次数 / 被过滤条数"），
    # 不在复位范围：拒绝那一跑没有加过任何一项，所以这里仍是英文那一跑的 1。
    assert diagnostics["stats"]["requests"] == 1, diagnostics["stats"]
    assert local.calls_count == 1, "拒绝路径不许发请求（只该有英文那一跑的 1 次）"

    provenance = provider.last_query_provenance
    assert len(provenance) == 1, provenance
    assert provenance[0]["dispatched"] is False
    assert provenance[0]["state"] == P.QUERY_NOT_APPLICABLE_CJK


def test_positive_empty_topic_early_return_goes_through_the_same_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：空 topic+description 的提前 return 分支走同一条复位。

    这条分支在守卫之前就返回了，所以复位必须放在它上面；否则它同样会把上一跑的
    检索串留着，而它也是"这一跑什么都没发"（`query_empty`）。
    """
    local = _HttpStub({"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}})
    monkeypatch.setattr(P, "http_get_json", local)
    provider = P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))

    provider.search(EN_TOPIC, "precise", "", 5)
    assert provider.last_query_text and provider.last_filter_notes
    assert provider.last_filtered_out > 0

    assert provider.search("", "topical", "", 3) == []
    assert provider.last_query_text == {}, provider.last_query_text
    assert provider.last_filter_notes == {}, provider.last_filter_notes
    assert provider.last_filtered_out == 0, provider.last_filtered_out
    assert provider.last_query_provenance == [], "提前 return 的那一跑连去向条目都没有"
    report = provider.last_topicality
    assert report is not None and report.state == P.QUERY_EMPTY
    assert local.calls_count == 1, "空题面一个请求都不发（只该有英文那一跑的 1 次）"


# ============================================================ 正控④：弃权可见（三档分列）


def test_positive_unjudged_column_is_visible_with_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """弃权必须可见：三档相加 = 候选总数，且逐条 `filter_note` 不再被丢掉。

    这一条对应 `draft/28` §100.3 的读数：改前 `rejected` 恒 0、
    逐条的判决"算完即丢"。现在三列分列、每列都带得出逐条的理由。
    """
    # topic 是中文（抽不出英文关键词）但 description 是英文 ⇒ 这一问合法发出，
    # 而逐条判决全部走"无法判定 ⇒ 放行"那一支（`keyword_hit` 返回 `None`）。
    stub = _HttpStub({"results": EN_WORKS})
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))

    got = provider.search(CJK_TOPIC, "precise", "sieve methods in prime distribution", 5)

    report = provider.last_topicality
    assert report is not None
    assert report.total == len(got) == 3
    assert report.judged_relevant + report.rejected + report.unjudged_no_ascii_keywords == report.total
    assert report.complete
    assert report.unjudged_no_ascii_keywords == 3, "纯中文 topic ⇒ 精筛逐条弃权"
    assert report.rejected == 0, "弃权不许被改判成 reject（D 只让判据说实话）"

    notes = {v.bucket for v in report.detail}
    assert notes == {"unjudged_no_ascii_keywords"}
    for verdict in report.detail:
        assert verdict.filter_note, "逐条的 filter_note 必须跟着判决一起进产物"
        assert "no_ascii_keywords" in verdict.filter_note


def test_positive_rejected_rows_carry_their_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """被剔除的条目也要在台账里（改前它们连人带理由一起消失）。"""
    stub = _HttpStub({"results": EN_WORKS})
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0))

    got = provider.search(EN_TOPIC, "precise", "", 5)
    report = provider.last_topicality
    assert report is not None

    rejected = [v for v in report.detail if v.verdict is False]
    assert len(rejected) == 1
    assert rejected[0].title == EN_WORKS[2]["title"]
    assert "keyword_miss" in rejected[0].filter_note
    assert rejected[0].title not in [c.title for c in got], "台账里有它，返回值里不许有它"
    assert report.total == 3 > len(got) == 2


def test_positive_keyword_hit_still_abstains_for_cjk() -> None:
    """口径未变：`keyword_hit` 对中文题面仍然返回 `None`（不许改成 `False`）。

    这是"不许把弃权改判成 reject"的机器判据。`query_applicability` 与它
    用的是同一个抽取函数，所以两件事同进同退。
    """
    assert P.keyword_hit(CJK_TOPIC, "Prime number sieves") is None
    assert P.keyword_hit(CJK_TOPIC, "素数分布中的筛法") is None
    assert P.query_applicability(CJK_TOPIC).state == P.QUERY_NOT_APPLICABLE_CJK
    assert P.keyword_hit(EN_TOPIC, "A spectral sequence") is True
    assert P.query_applicability(EN_TOPIC).applicable is True


# ============================================================ 负控：注入必须让判据变红


def test_negative_control_disabling_the_guard_rediscovers_the_cjk_dispatch(
    stub: _HttpStub, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控（装置）：把守卫改成"恒适用" ⇒ 中文原串必须重新被打给上游。

    这是"判据有牙"的唯一证明：同一个输入，只有这一处判定不同，读数就翻面。
    """
    monkeypatch.setattr(
        P, "_require_applicable_query",
        lambda provider, topic, description: P.QueryApplicability(
            state="applicable_as_is", query_text=f"{topic} {description}".strip(),
        ),
    )
    monkeypatch.setattr(
        P, "query_applicability",
        lambda topic, description="": P.QueryApplicability(
            state="applicable_as_is", query_text=f"{topic} {description}".strip(),
        ),
    )
    provider = _provider(stub)
    provider.search(CJK_TOPIC, "precise", "", 5)

    assert stub.calls_count >= 1, "注入之后必须真的发出去（否则负控没有咬到东西）"
    assert any(CJK_TOPIC in text for text in stub.search_texts), stub.search_texts
    assert provider.last_query_provenance[0]["dispatched"] is True
    # 判据自己的锚点仍然完整：中文原串逐字出现在发出去的检索串里。
    assert all(CJK_TOPIC in text for text in stub.search_texts), stub.search_texts


def test_negative_control_multi_provider_records_the_refusal(stub: _HttpStub) -> None:
    """负控（读数面）：`MultiProvider` 必须把第三态记成第三态名并留下理由。

    折成 `ok`（"跑成了、零命中"）就等于让"未接线"重新混进"检索成功"，
    而下游所有以回验率为分母的指标都建立在这个读数上。
    `Y-1` 之后这一档也不再折成 `failed`（"上游坏了"）：状态位逐字就是那个
    第三态名（与 `evidence.sources_detail[*].status` 同一个取值）。
    """
    providers = [
        P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
        P.CrossrefProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
    ]
    multi = P.MultiProvider(providers)
    got = multi.search(CJK_TOPIC, "precise", "", 3)

    assert got == []
    assert stub.calls_count == 0
    assert set(multi.last_refusals) == {"openalex", "crossref"}
    for name, stat in multi.last_stats.items():
        # `Y-1`：这一问根本没发出去 ⇒ 状态位是第三态名，不再折成 `failed`。
        assert stat.status == P.QUERY_NOT_APPLICABLE_CJK, (name, stat.to_dict())
        assert stat.count == 0
        # 第二处：理由那句仍带状态名（`error` 是异常原文），于是两个出口同源 ——
        # 但读法变了：不再是"名字出现在某段自由文本里"，而是逐字就在句首那个位置
        # （`{源名}: {状态名}：{理由}`），状态位与理由不许只剩其一。
        assert stat.error.startswith(f"{name}: {P.QUERY_NOT_APPLICABLE_CJK}"), stat.to_dict()
        assert stat.refused is True and stat.failed is False, (name, stat.to_dict())
    report = multi.last_topicality
    assert report is not None and report.total == 0 and report.complete


# ============================================================ 正控：统计面与 evidence 侧的第三态对齐（Y-1）


def test_positive_stats_face_carries_the_third_state_name_verbatim(stub: _HttpStub) -> None:
    """正控（`Y-1`）：`last_stats[*].status` 逐字给出第三态名。

    同一件"这一问根本没发出去"，在 `evidence` 侧是 `sources_detail[*].status`
    里的 `query_not_applicable_cjk`（`R12-R3-3`），在 providers 统计面上改前却是
    `failed`（"上游坏了"）。这条判据把两个出口钉在同一个取值上，并把状态名以外
    的三个属性各归各位：`failed` 答"上游坏了"、`refused` 答"没发出去"、
    `delivered` 答"问过了"。
    """
    providers = [
        P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
        P.CrossrefProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
    ]
    multi = P.MultiProvider(providers)
    got = multi.search(CJK_TOPIC, "precise", "", 3)

    assert got == []
    assert stub.calls_count == 0, "第三态一个请求都不发"
    # 词表：原有三个取值逐字还在（加第三态不许动它们），第三态按名加进来。
    assert P.PROVIDER_STAT_STATUSES[:3] == ("not_run", "ok", "failed")
    assert P.QUERY_NOT_APPLICABLE_CJK in P.PROVIDER_STAT_STATUSES
    assert P.QUERY_EMPTY in P.PROVIDER_STAT_STATUSES
    # 与 evidence 侧那份词表用的是同一串字符：两个出口不许各写一份拼写。
    assert set(P.PROVIDER_STAT_STATUSES) & {P.QUERY_NOT_APPLICABLE_CJK, P.QUERY_EMPTY} == {
        P.QUERY_NOT_APPLICABLE_CJK, P.QUERY_EMPTY,
    }

    assert set(multi.last_stats) == {"openalex", "crossref"}
    for name, stat in multi.last_stats.items():
        assert stat.status == P.QUERY_NOT_APPLICABLE_CJK, (name, stat.to_dict())
        assert stat.to_dict()["status"] == P.QUERY_NOT_APPLICABLE_CJK, name
        assert stat.count == 0
        assert stat.error_kind == "", (name, stat.to_dict())
        assert stat.refused is True and stat.failed is False, (name, stat.to_dict())
        assert stat.delivered is False, name
        assert P.QUERY_NOT_APPLICABLE_CJK in stat.error, stat.to_dict()


def test_positive_empty_query_row_is_query_empty_not_ok(stub: _HttpStub) -> None:
    """正控（`Y-1`）：空题面那条"不抛异常"的路径也落第三态名。

    `OpenAlexProvider.search` 的空题面分支是提前 `return []`（`R12-R3-1` 钉住的
    既有行为），所以只看异常的话这一行会变成 `ok` 配 `count == 0`
    （"查了没命中"）—— 与第三态 `query_empty`（"根本没问"）是两件事。
    两个源的理由各来自一处：`openalex` 走 provider 台账，`crossref` 走异常。
    """
    providers = [
        P.OpenAlexProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
        P.CrossrefProvider(min_interval=0.0, retries=0, limiter=P.RateLimiter(0.0)),
    ]
    multi = P.MultiProvider(providers)
    got = multi.search("", "topical", "", 3)

    assert got == []
    assert stub.calls_count == 0, "空题面一个请求都不发"
    assert set(multi.last_stats) == {"openalex", "crossref"}
    for name, stat in multi.last_stats.items():
        assert stat.status == P.QUERY_EMPTY, (name, stat.to_dict())
        assert stat.count == 0 and stat.refused is True, (name, stat.to_dict())
        assert stat.delivered is False and stat.failed is False, (name, stat.to_dict())
    assert set(multi.last_refusals) == {"openalex", "crossref"}
    assert all(reason for reason in multi.last_refusals.values()), multi.last_refusals


class _BoomProvider:
    """永远抛错的替身源：用来钉"上游坏了"那一档（不出网）。"""

    name = "boom"

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0):
        raise P.ProviderError("upstream exploded")


class _QuietProvider:
    """跑成了但零命中的替身源：用来钉"查了没命中"那一档（不出网）。"""

    name = "quiet"

    def search(self, topic: str, mode: str, description: str = "", limit: int = 0):
        return []


def test_positive_failed_and_zero_hit_are_not_folded_into_the_third_state() -> None:
    """正控（`Y-1` 的反面）：扩词表不许把另外两档一起吞掉。

    加第三态最危险的形态是顺手把 `failed` 也归进第三态、或反过来把第三态
    归进 `failed`（那会让"上游坏了"与"没发出去"重新同值，只是换了方向）。
    这条判据用两个替身源把三档钉开：抛错 ⇒ `failed` 且 `error_kind` 非空；
    跑成了零命中 ⇒ `ok` 配 `count == 0`；两者都不是第三态。
    """
    multi = P.MultiProvider([_BoomProvider(), _QuietProvider()])
    got = multi.search(EN_TOPIC, "topical", "", 3)

    assert got == []
    boom = multi.last_stats["boom"]
    assert boom.status == "failed", boom.to_dict()
    assert boom.failed is True and boom.refused is False and boom.delivered is False
    assert boom.error_kind, "失败必须给出 error_kind（既有判据不许放宽）"
    assert "boom" not in multi.last_refusals, "上游坏了不是第三态"
    quiet = multi.last_stats["quiet"]
    assert quiet.status == "ok" and quiet.count == 0, quiet.to_dict()
    assert quiet.delivered is True and quiet.refused is False and quiet.failed is False
    assert "quiet" not in multi.last_refusals, "零命中不是第三态"


def test_positive_third_state_guards_are_wired() -> None:
    """正控：第三态的构造期守卫（没理由 / 带条数 / 未登记取值 ⇒ 抛）。

    守卫本身是判据的一部分：没有它，"第三态"可以带上一批结果或一句空理由
    静默构造出来，产物里就再也分不出"没发出去"与"发出去零命中"。
    """
    with pytest.raises(ValueError):
        P.ProviderStat(status=P.QUERY_EMPTY, count=0)
    with pytest.raises(ValueError):
        P.ProviderStat(status=P.QUERY_NOT_APPLICABLE_CJK, count=2, error="x")
    # 既有守卫一个字没动：错误档缺 `error_kind` / 带条数仍然抛。
    with pytest.raises(ValueError):
        P.ProviderStat(status="failed", count=0)
    with pytest.raises(ValueError):
        P.ProviderStat(status="failed", count=1, error_kind="timeout")
    # 词表没有变宽成"任何字符串"：未登记的取值仍然拒收。
    with pytest.raises(ValueError):
        P.ProviderStat(status="not_applicable")

    row = P.ProviderStat(status=P.QUERY_EMPTY, count=0, error="query_empty：没有查询串")
    assert row.refused is True and row.failed is False and row.delivered is False
    assert row.to_dict()["status"] == P.QUERY_EMPTY


# ============================================================ 读取面自身的三态纪律


def test_positive_report_counts_always_add_up(stub: _HttpStub) -> None:
    """台账自检：任何一次调用之后，三档之和恒等于候选总数。"""
    provider = _provider(stub)
    for mode in ("precise", "topical", "broad"):
        provider.search(EN_TOPIC, mode, "", 3)
        report = provider.last_topicality
        assert report is not None
        counts = report.counts()
        assert sum(counts.values()) == report.total == len(report.detail)
        assert set(counts) == {"judged_relevant", "rejected", "unjudged_no_ascii_keywords"}
        assert report.state == ("judged" if mode == "precise" else "not_precise")


# ============================================================ `C-4a`：短语零召回的降级
#
# 这一节的读数来自 2026-09-28 的第一手定位（`temp/FIX16-PLAN.md`）：
# `_phrase_query` 把整段 ASCII 题面包进引号，而 OpenAlex 的引号是字面短语匹配 ——
# 同一题面加引号的 `meta.count` 是 0、不加引号是 92549。生产检索路径
# （`evidence._default_sources`）传 `mode="precise", description=""`，
# 于是整条链上召回恒为 0：材料为空（`T3` 的 `tokens_in` 恒 272）⇒ O6 回验率 0/120。

LONG_TOPIC = "spectral sequence of a filtered complex and its convergence"


class _RoutingStub:
    """按 `(search, sort)` 分派的替身：能造出"短语 0 条、词项 3 条"这种真实形态。

    为什么不能只用 `_HttpStub`：它的载荷与请求无关，于是"降级真的发生了"与
    "第一次查询本来就有结果"在读数上不可分辨 —— 而那正是这条判据要问的事。
    `raise_when` 让某一路抛 `HttpError`（429 的形态），用来测 `C-4b`。
    """

    def __init__(self, routes: dict | None = None, *, default: dict | None = None,
                 raise_when=None) -> None:  # noqa: ANN001 - 替身签名随被替者
        self.routes = dict(routes or {})
        self.default = default if default is not None else {"results": [], "meta": {"count": 0}}
        self.raise_when = raise_when
        self.calls: list[dict] = []

    def __call__(self, url, params=None, **kwargs):  # noqa: ANN001, ANN003 - 替身签名随被替者
        got = dict(params or {})
        self.calls.append({"url": url, "params": got, "kwargs": dict(kwargs)})
        if self.raise_when is not None:
            message = self.raise_when(got)
            if message:
                raise P.HttpError(message, 429)
        return self.routes.get(str(got.get("search", "")), self.default)

    @property
    def calls_count(self) -> int:
        return len(self.calls)

    @property
    def search_texts(self) -> list[str]:
        return [str(c["params"].get("search", "")) for c in self.calls]

    @property
    def sorts(self) -> list[str]:
        return [str(c["params"].get("sort", "")) for c in self.calls]


def test_positive_plan_gives_long_topics_a_term_fallback() -> None:
    """正控：长英文题面在 `topical`/`precise` 两路上都带词项形态的降级串。

    断言的是降级串的形状而不是某个数字：它必须非空、与主串不同、且不含引号
    （含引号就还是字面短语，退化了等于没退）。
    """
    for mode in ("topical", "precise"):
        plans = P._plan_mode(mode, LONG_TOPIC, "", 5)
        assert plans, mode
        for plan in plans:
            assert plan.fallback, (mode, plan.channel, plan.template)
            assert plan.fallback != plan.template["search"], (mode, plan.channel)
            assert '"' not in plan.fallback, (mode, plan.channel, plan.fallback)
    # 中文题面两串本来就同形（`_term_query` 对非 ASCII 原样保留、`_phrase_query`
    # 只对 ASCII 词加引号），此时不产生第二次请求 —— 由下一条负控钉住。
    cjk_plans = P._plan_mode("topical", CJK_TOPIC, "", 5)
    assert all(p.fallback == p.template["search"] for p in cjk_plans), cjk_plans


def test_positive_phrase_zero_recall_falls_back_to_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：整串短语零召回时，用词项形态重抓一次，并且两条都留在读数里。

    这是 `O6 = 0` 那条链的第一环：没有这次重抓，OpenAlex 对这一问就是 0 条，
    模型拿到的材料为空，任何断言都无据可依。
    """
    phrase = f'"{EN_TOPIC}"'
    terms = P._term_query(EN_TOPIC)
    assert phrase != terms, "这条判据要求主串与降级串真的不同"
    stub = _RoutingStub({
        phrase: {"results": [], "meta": {"count": 0}},
        terms: {"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}},
    })
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(EN_TOPIC, "precise", "", 5)

    # 材料真的回来了：精筛口径照旧（两条命中、一条 keyword_miss）。
    assert [c.title for c in got] == [EN_WORKS[0]["title"], EN_WORKS[1]["title"]]
    assert stub.search_texts == [phrase, terms], "两次请求都要发出去，顺序是主串在前"
    assert provider.stats["phrase_fallbacks"] == 1
    record = provider.last_phrase_fallbacks["precise"]
    assert record["phrase"] == phrase and record["terms"] == terms
    assert record["count"] == len(EN_WORKS)
    # `last_query_text` 的语义是"实际发出的检索串"：产出结果的那一条。
    assert provider.last_query_text == {"precise": terms}
    # 台账把这件事说出来（`sources_detail[].topicality_query_notes` 的上游）。
    assert provider.last_topicality is not None
    notes = provider.last_topicality.query_notes
    assert any("phrase_zero_recall_fallback[precise]" in n for n in notes), notes


def test_negative_control_phrase_with_results_never_falls_back(stub: _HttpStub) -> None:
    """负控：主查询有结果时一次都不许重抓（降级不许变成"每次都发两遍"）。

    这是"短题面的精度收益逐字不变"的机器判据：`abelian group` 这类短题面
    命中非零，行为必须与改前完全相同。
    """
    provider = _provider(stub)

    got = provider.search(EN_TOPIC, "precise", "", 5)

    assert [c.title for c in got] == [EN_WORKS[0]["title"], EN_WORKS[1]["title"]]
    assert stub.calls_count == 1, stub.search_texts
    assert provider.stats["phrase_fallbacks"] == 0
    assert provider.last_phrase_fallbacks == {}
    assert provider.last_topicality is not None
    assert provider.last_topicality.query_notes == ()


# ============================================================ `C-4b`：没查成 ≠ 没有结果


def test_positive_all_channels_failing_raises_instead_of_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控：每一路都抛异常 ⇒ 抛 `ProviderError`，而不是"零候选"。

    改前这两件事折成同一个"0 条"，于是 429 在产物里写成 `no_results`
    （"查过了、没有可用条目"）。这里同时钉住：这不是第三态（"这一问没发出去"），
    下游必须把它记成 `failed`。
    """
    stub = _RoutingStub(raise_when=lambda params: "HTTP 429 限流")
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    with pytest.raises(P.ProviderError) as excinfo:
        provider.search(EN_TOPIC, "topical", "", 5)

    assert "每一路都失败" in str(excinfo.value)
    assert set(provider.last_channel_errors) == {"foundational", "frontier"}
    assert provider.stats["channel_errors"] == 2
    assert provider.last_query_text == {}, "一条都没回来 ⇒ 没有'实际发出的检索串'"
    assert provider.stats["phrase_fallbacks"] == 0, "没查成与零召回是两件事"
    # 三态纪律：这不是"这一问没发给上游"，所以不许被下游读成拒绝态。
    assert P._provider_refusal(provider, []) == ("", "")


def test_negative_control_one_channel_failing_keeps_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：只有一路抛时不抛，另一路的结果照常返回（既有口径不许加严）。

    "单源失败不许让整体失败"是 `evidence.retrieve` 的硬规则；这道降级不许
    把"一路坏了"升级成"整次没查成"。
    """
    stub = _RoutingStub(
        default={"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}},
        raise_when=lambda params: "HTTP 429 限流"
        if params.get("sort") == "cited_by_count:desc" else "",
    )
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(EN_TOPIC, "topical", "", 5)

    assert got, "前沿那一路的结果必须照常返回"
    assert set(provider.last_channel_errors) == {"foundational"}
    assert provider.last_query_text == {"frontier": f'"{EN_TOPIC}"'}
    assert provider.stats["channel_errors"] == 1


# ============================================================ `FINAL-R3-01`：请求数不许翻倍


def test_positive_the_same_zero_recall_phrase_is_not_reissued_in_one_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控（`FINAL-R3-01`）：topical 的两条路共用同一条主查询串，
    第一条路已经证明它零召回之后，第二条路不许再发一次同一条注定零召回的主查询。

    请求数因此是 3（1 条短语 + 2 条词项），而不是 4 —— 这个差额恰好出现在
    限流场景附近（零召回的常见成因就是上游给空载荷/限流），所以它不只是配额问题。
    """
    phrase = f'"{EN_TOPIC}"'
    terms = P._term_query(EN_TOPIC)
    stub = _RoutingStub({
        phrase: {"results": [], "meta": {"count": 0}},
        terms: {"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}},
    })
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    got = provider.search(EN_TOPIC, "topical", "", 5)

    assert got, "两条路都必须拿回候选"
    assert stub.calls_count == 3, f"应为 3 次（短语 1 + 词项 2），实际 {stub.search_texts}"
    assert stub.search_texts.count(phrase) == 1, stub.search_texts
    assert provider.stats["phrase_fallbacks"] == 2
    assert provider.stats["phrase_fallbacks_deduped"] == 1, provider.stats
    assert provider.last_phrase_fallbacks["frontier"]["deduped"] is True


def test_negative_control_a_fresh_provider_does_reissue_the_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：去重只限同一次 search 调用之内 —— 换一个 provider 实例（= 新的一跑）
    必须重新发那条短语，否则"上一跑零召回"会被错误地继承到下一跑。"""
    phrase = f'"{EN_TOPIC}"'
    terms = P._term_query(EN_TOPIC)
    stub = _RoutingStub({
        phrase: {"results": [], "meta": {"count": 0}},
        terms: {"results": EN_WORKS, "meta": {"count": len(EN_WORKS)}},
    })
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    provider.search(EN_TOPIC, "topical", "", 5)
    first_round = stub.calls_count
    provider.search(EN_TOPIC, "topical", "", 5)

    assert first_round == 3 and stub.calls_count == 6, (first_round, stub.search_texts)
    assert stub.search_texts[:3].count(phrase) == 1, stub.search_texts[:3]
    assert stub.search_texts[3:].count(phrase) == 1, "新的一跑必须重新发那条短语"


# ============================================================ `FINAL-R3-04`：没查成有自己的一档


def test_positive_all_channels_failing_gets_its_own_topicality_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正控（`FINAL-R3-04`）：每一路都失败时，台账的 `state` 必须是
    `channel_error`，而不是与正常路径同形的 `judged` + 三档全 0 + `complete=true`。

    改前那一形态让"一条候选都没取回来（因为每一路都失败）"与
    "取回来判过、一条都没留下"在产物上不可分。
    """
    stub = _RoutingStub(raise_when=lambda params: "HTTP 429 限流")
    monkeypatch.setattr(P, "http_get_json", stub)
    provider = _provider(stub)

    with pytest.raises(P.ProviderError):
        provider.search(EN_TOPIC, "topical", "", 5)

    report = provider.last_topicality
    assert report is not None
    assert report.state == P.TOPICALITY_STATE_CHANNEL_ERROR, report.state
    assert report.total == 0 and report.counts() == {
        "judged_relevant": 0, "rejected": 0, "unjudged_no_ascii_keywords": 0}
    assert any("channel_error[" in n for n in report.query_notes), report.query_notes
    # 它与"这一问根本没发出去"（两个拒绝态）不同轴：下游不许读成拒绝态。
    assert P._provider_refusal(provider, []) == ("", "")



# ============================================================ E-10：三态接进生产入口


def test_e10_the_production_diagnostics_carry_the_third_state(stub: _HttpStub) -> None:
    """E-10（draft/44）：生产读数里"没问出去"必须与"问了、零命中"分得开。

    现场：search.literature 的 diagnostics（_provider_diagnostics）只捞
    stats/last_query_text/last_filter_notes/…，不捞 last_topicality ——
    而后者是第三态的唯一载体（QueryApplicability：query_empty /
    query_not_applicable_cjk）。于是空 topic 那次 
eturn [] 在生产读数上与
    "问了、零命中"长得一模一样（三态在入口处被折平）。
    两条一起钉：① 没问出去 ⇒ 那一屏里带第三态名；② 问了零命中 ⇒ 不带。
    """
    from agentflow.tools import search_tools as ST

    refused = _provider(stub)
    assert refused.search("", "topical") == [], "空 topic 这一问不该发给上游"
    got = ST._provider_diagnostics(refused)
    assert got.get("last_topicality"), (
        "生产读数里没有 last_topicality ⇒ '没问出去'与'零命中'又折平了：" + repr(sorted(got)))
    text = repr(got["last_topicality"])
    assert P.QUERY_EMPTY in text, text

    empty = _provider(_HttpStub({"results": [], "meta": {"count": 0}}))
    assert empty.search(EN_TOPIC, "topical") == [], "问了、零命中"
    got2 = ST._provider_diagnostics(empty)
    # 两态的分界在 `refusal_reason`（第三态名）上，不在"有没有这份读数"上 ——
    # 问了零命中的那一跑同样会留下 `last_topicality`，只是 `refusal_reason` 为空。
    asked_reason = str(getattr(got["last_topicality"], "refusal_reason", "") or "")
    zero_reason = str(getattr(got2["last_topicality"], "refusal_reason", "") or "")
    assert P.QUERY_EMPTY in asked_reason, asked_reason
    assert zero_reason == "", (
        "问了零命中的那一跑不该带第三态理由（否则两种情形又同形了）：" + zero_reason)
