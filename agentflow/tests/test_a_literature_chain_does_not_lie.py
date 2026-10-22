"""角色 A 文献入库链路的八条判据（审计 A 的读数；每条都验证过"改前红"）。

这一份守的是"读数不许说谎"，不是"功能多一点"。八条对应审计报出的八处缺陷，
每一条的输入都走真实写侧（`AgentA.run_once` / `lit.admit_all` / `ingest_directory`），
检索源与抽取器是注入的替身：不联网、不跑模型、只写 `tmp_path`。

八条与落点（改前读数见各用例 docstring）：

1. 检索到 N 条、全被本地重叠闸拒 ⇒ `no_results` 之外还要有命中数/入库数/理由分布（`run_once`）；
2. 一键迁移的行必须有定位栏（候选 url）且标明"本次无全文"，B 读得出它在哪（`search_tools`）；
3. 报告"已入库 N 篇"按去重后的 `lit_id` 计数（`litstage.report_markdown`）；
4. 同一委托重跑不把 `lit_candidates` 的 pending 行翻倍（`run_once`）；
5. 已入库条目的 relevance 全空 ⇒ 报告判据记一条读数（只记读数，不拦门）（`litstage`）；
6. 默认检索态逐源报状态：限流 / 0 命中 / 失败三档分得开（`agent_a.core`）；
7. 有源失败但有命中 ⇒ `last_error` 非空且点名失败的源（`run_once`）；
8. `ingest_local` 落的行按 `dedup.literature_keys` 同一口径带键，判重读侧看得见（`locallib`）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import dedup as D
from agentflow import litstage as L
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.agent_b import AgentB
from agentflow.locallib import ingest_directory
from agentflow.providers import Candidate
from agentflow.tools import build_for_role

from conftest import add_literature, add_request

RID = "r-000001"


# --------------------------------------------------------------------------- 替身与夹具


class _StubProvider:
    """确定性检索源替身：不联网；可以按名抛一个指定的异常。"""

    def __init__(self, name: str, candidates=(), error: BaseException | None = None) -> None:
        self.name = name
        self.candidates = list(candidates)
        self.error = error
        self.calls = 0

    def search(self, topic, mode, description="", limit=10):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.candidates)


class _RateLimited(Exception):
    """带 HTTP 429 的异常：`providers.provider_error_kind` 据此归到 rate_limited 那一档。"""

    status = 429


class _StubExtractor:
    """B 的抽取器替身：本文件不测抽取，只测读侧写下的原因。"""

    def extract(self, doc, lit_id, meta):
        return [], []


class _FakeDoc:
    """locallib 的抽取结果替身（只有 ingest 用到的两格）。"""

    pages = ["A group is a set with an operation."]
    has_text_layer = True


def _cand(title: str, doi: str | None, *, provider: str = "stub",
          pdf_url: str | None = None, year: int = 2001) -> Candidate:
    return Candidate(
        title=title, year=year, doi=doi, authors=["A. Author"], venue="V",
        type_code="J", summary="摘要", pdf_url=pdf_url, landing_url=None,
        language="en", provider=provider, raw={"provider": provider},
    )


def _agent(store, *providers, **cfg) -> AgentA:
    config = {"download": False, "lease_seconds": 900, "max_attempts": 3,
              "retry_backoff_seconds": 0}
    config.update(cfg)
    return AgentA(store, providers=list(providers), downloader=None, config=config)


def _request(store, request_id: str = RID) -> dict:
    return next(r for r in store.rows("search_requests") if r["request_id"] == request_id)


@pytest.fixture
def reg(store):
    """A 的工具面：判据打在工具层（`lit.admit_all` 的处理器），不是内部函数上。"""
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


# ---------------------------------------------------------------- 1. 命中但全被拒


def test_hits_that_are_all_rejected_do_not_read_as_a_bare_no_results(store):
    """1. 三条候选全被重叠闸拒 ⇒ 读数里要有命中 3 / 入库 0 / 理由码分布。

    改前读数：请求行 `outcome="no_results"`、`last_error=null`，而同一次
    `lit_candidates` 的三行全是 `rejected` + `overlap_without_new_content`
    —— 与"一条都没检索到"在盘上完全同形。
    """
    add_literature(store, "000000", title="Floquet theory for periodic differential equations",
                   doi="10.9999/floquet", processed=True)
    add_request(store, RID, topic="floquet theory")
    cands = [_cand(f"Floquet theory for periodic differential equations vol {i}",
                   f"10.7777/v{i}") for i in (1, 2, 3)]
    agent = _agent(store, _StubProvider("stub", cands))

    res = agent.run_once()

    assert res.processed == 1 and res.registered == 0 and res.outcome == "no_results"
    row = _request(store)
    assert row["done"] is True
    last_error = str(row["last_error"] or "")
    assert last_error, "命中 3 条、全被重叠闸拒，却只留下 outcome=no_results 与 last_error=null"
    assert "命中 3 条" in last_error, last_error
    assert "入库 0 条" in last_error, last_error
    assert "overlap_without_new_content=3" in last_error, last_error
    # 反真空：候选行上的真相还在（这条判据读的确实是同一次的三条）
    rows = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(rows) == 3 and all(r["status"] == "rejected" for r in rows), rows
    assert all(r["reason_code"] == "overlap_without_new_content" for r in rows)


# ---------------------------------------------------------------- 2. 一键迁移的定位栏


def test_one_click_migration_leaves_a_locator_so_b_can_tell_where_it_is(store, reg):
    """2. 一键迁移的行必须有定位栏（候选 url）并标"本次无全文"；B 读得出它在哪。

    改前读数：literature 行 `path=null`、`download={"status":"skipped",
    "error":"no_local_path"}`；B 领取后只能写 `no_local_file`，说不出这篇从哪来。
    """
    url = "https://example.invalid/locate-me.pdf"
    staged = reg.call("lit.stage_add", request_id=RID, entries=[{
        "title": "Migration with a locator", "doi": "10.55/locate", "provider": "stub",
        "year": 2011, "type_code": "J", "url": url, "relevance": "与本次检索相关",
    }])
    assert staged.ok, staged.error

    got = reg.call("lit.admit_all", request_id=RID)
    assert got.ok, got.error
    lit_id = got.unwrap()["admitted"][0]["lit_id"]

    row = next(r for r in store.rows("literature") if r["lit_id"] == lit_id)
    dl = dict(row.get("download") or {})
    assert row["path"] is None, row
    assert dl.get("url") == url, dl
    assert dl.get("fulltext") == "no_fulltext_this_time", dl

    # B 的读侧实跑：原因必须点到那个定位符（不是一条说不出位置的 unreadable）
    b = AgentB(store, extractor=_StubExtractor(), extract_text=None,
               config={"lease_seconds": 900, "max_attempts": 3},
               auto_secretary=False)
    res = b.run_once()
    assert res.processed == 1 and res.unreadable == 1, res.to_dict()
    reason = str(res.details[0].get("skipped") or "")
    assert reason == f"no_fulltext_this_time: {url}", reason
    assert "unreadable" not in reason
    assert str(next(r for r in store.rows("literature")
                    if r["lit_id"] == lit_id)["last_mine_error"]) == reason


# ---------------------------------------------------------------- 3. 报告按 lit_id 计数


def test_the_admitted_count_in_the_report_counts_distinct_lit_ids(store):
    """3. 两条候选命中同一个 literature 行 ⇒ 报告写"已入库 1 篇"，不是 2 篇。

    改前读数：`## 已入库（2 篇）`，而库里的 `lit_id` 只有一个。
    """
    rows = [
        S.LitCandidate(slot="000000", request_id=RID, batch=1, status="admitted",
                       title="Same paper seen by source A", lit_id="000001",
                       relevance="与本次检索相关", added_at=S.now_iso()).to_dict(),
        S.LitCandidate(slot="000001", request_id=RID, batch=1, status="admitted",
                       title="Same paper seen by source B", lit_id="000001",
                       relevance="与本次检索相关", added_at=S.now_iso()).to_dict(),
    ]
    text = L.report_markdown(RID, rows)
    assert "## 已入库（1 篇）" in text, text
    assert "## 已入库（2 篇）" not in text, text
    written = L.write_report(store, RID, rows=rows)
    assert written["admitted"] == 1, written


# ---------------------------------------------------------------- 4. 同一委托重跑不堆行


def test_rerunning_the_same_delegation_does_not_double_the_pending_rows(store):
    """4. 同一委托再跑一次 ⇒ 候选行不再堆一份（pending 不翻倍、总数也不翻倍）。

    改前读数：同一委托的 `lit_candidates` 从 2 行变成 4 行（审计里那次是 4 变 8），
    新追加的两行与已暂存的两行 title+doi 逐字相同。
    两个计数都要看：追加的行在这一轮被结算成 admitted/rejected 之后就不再是
    pending，所以只数 pending 会漏掉"堆了一份又当场迁走"那种形态。
    """
    add_request(store, RID, topic="spectral sequences")
    cands = [_cand("Spectral sequences of filtered complexes", "10.1000/SPEC"),
             _cand("A paper without any pdf link", "10.1000/NOPDF")]
    first = L.stage_entries(
        store,
        [{"title": c.title, "doi": c.doi, "provider": "stub", "year": c.year}
         for c in cands],
        request_id=RID, actor="agent-A", note="fixture:already_staged",
    )
    assert len(first["staged"]) == 2

    before = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(before) == 2 and all(r["status"] == "pending" for r in before)

    res = _agent(store, _StubProvider("stub", cands)).run_once()

    assert res.request_id == RID and res.processed == 1
    after = [r for r in store.rows("lit_candidates") if r["request_id"] == RID]
    assert len(after) == len(before), (
        f"同一委托重跑把候选行从 {len(before)} 堆成了 {len(after)}；"
        "同 title+doi 的候选又追加了一次")
    pending_after = [r for r in after if r["status"] == "pending"]
    assert len(pending_after) == len(before), pending_after


# ---------------------------------------------------------------- 5. relevance 全空


def test_an_all_empty_relevance_is_recorded_as_a_reading_and_does_not_block(store, reg):
    """5. 已入库条目 relevance 全空 ⇒ `report_violations` 记一条；入库不受影响。

    改前读数：`report_violations(report) == []`，报告里只有一句
    "（A 未写相关性说明）"，看不出缺的是哪几条、也没有任何机器读数。
    """
    staged = reg.call("lit.stage_add", request_id=RID, entries=[
        {"title": "No relevance one", "doi": "10.60/one", "provider": "stub",
         "year": 2001, "type_code": "J"},
        {"title": "No relevance two", "doi": "10.60/two", "provider": "stub",
         "year": 2002, "type_code": "J"},
    ])
    assert staged.ok, staged.error

    got = reg.call("lit.admit_all", request_id=RID)
    assert got.ok, got.error
    data = got.unwrap()
    # 只记读数、不拦门：入库照常完成
    assert data["registered"] == 2, data

    text = Path(data["report_path"]).read_text(encoding="utf-8")
    violations = L.report_violations(text)
    assert len(violations) == 1, violations
    assert "relevance" in violations[0], violations
    assert "不拦门" in violations[0], violations
    # 点名缺哪几条，而不是一句谁都对得上的兜底
    assert "A 未写相关性说明" not in text
    tail = text.split("- 缺相关性说明的条目", 1)
    assert len(tail) == 2, text
    for row in store.rows("lit_candidates"):
        assert f"`lit:{row['lit_id']}`" in tail[1], text


# ---------------------------------------------------------------- 6. 默认检索态逐源三态


def test_the_default_search_state_reports_every_source_status(store):
    """6. 没点名源的第一态也逐源报状态：限流 / 0 命中 / 失败三档分得开。

    改前读数：`sources=[]`，于是"两个源被限流"与"接线上的源全都 0 命中"
    在动作读数上同形（都只剩 `outcome=no_results`）。
    """
    add_request(store, RID, topic="spectral sequences")
    hit = _StubProvider("alpha", [_cand("Spectral sequences of filtered complexes",
                                        "10.1002/alpha")])
    empty = _StubProvider("beta", [])
    limited = _StubProvider("gamma", error=_RateLimited("429 Too Many Requests"))
    broken = _StubProvider("delta", error=RuntimeError("boom"))

    res = _agent(store, hit, empty, limited, broken).run_once()

    assert res.registered == 1, res.to_dict()
    assert res.providers_requested == [], "第一态是'没点名'，不是'点名了没人接上'"
    by_name = {str(s["name"]): s for s in res.sources}
    assert set(by_name) == {"alpha", "beta", "gamma", "delta"}, by_name
    assert by_name["alpha"]["status"] == "ok" and by_name["alpha"]["count"] == 1, by_name
    assert by_name["beta"]["status"] == "ok" and by_name["beta"]["count"] == 0, by_name
    assert by_name["gamma"]["status"] == "failed", by_name
    assert by_name["gamma"]["error_kind"] == "rate_limited", by_name
    assert by_name["delta"]["status"] == "failed", by_name
    assert by_name["delta"]["error_kind"] != "rate_limited", by_name


# ---------------------------------------------------------------- 7. 有源失败但有命中


def test_a_failed_source_with_hits_is_not_written_as_a_clean_success(store):
    """7. 一个源失败、另一个源有命中 ⇒ `last_error` 非空且点名失败的源。

    改前读数：`outcome="ok"` + `last_error=null`，失败只进 `tx.info` 的事件流。
    """
    add_request(store, RID, topic="spectral sequences")
    good = _StubProvider("alpha", [_cand("Spectral sequences of filtered complexes",
                                         "10.1003/good")])
    bad = _StubProvider("beta", error=_RateLimited("429 Too Many Requests"))

    res = _agent(store, good, bad).run_once()

    assert res.registered == 1, res.to_dict()
    row = _request(store)
    assert row["outcome"] == "ok"
    last_error = str(row["last_error"] or "")
    assert last_error, "有源失败却有命中，last_error 却是 null"
    assert "1 个源失败" in last_error, last_error
    assert "beta" in last_error, last_error


# ---------------------------------------------------------------- 8. ingest_local 的键


def _books_dir(tmp_path: Path) -> Path:
    books = tmp_path / "books"
    books.mkdir()
    (books / "Linear_Algebra_Notes.pdf").write_bytes(b"%PDF-1.4 fixture bytes")
    return books


def test_the_row_ingest_local_lands_is_visible_to_the_dedup_key_readers(
        store, tmp_path, monkeypatch):
    """8. `ingest_local` 落的行带 `dedup_key`/`_keys`，判重读侧函数看得见。

    改前读数：行的 `dedup_key=""`、没有 `_keys` ⇒ `dedup._row_keys(row)` 是空集，
    键读侧（`_row_doi` / `_row_year` / 第 2 轮 `title:<n>|<year>`）都看不见它。
    本地藏书没有 DOI，所以这里用同一个生成器验两件事：标题键被写上，
    以及带 DOI 的同族行拿到的是同一族的 `doi:` 主键（不是另一份口径）。
    """
    monkeypatch.setattr("agentflow.locallib.extract_text", lambda path: _FakeDoc())
    rep = ingest_directory(store, _books_dir(tmp_path), note="判据夹具")
    assert rep.counts()["ingested"] == 1, rep.counts()

    row = store.rows("literature")[0]
    keys = D.literature_keys(row["title"], None, None)
    assert keys and keys[0].startswith("title:"), keys
    assert row["dedup_key"] == keys[0], row.get("dedup_key")
    assert row["_keys"] == keys, row.get("_keys")
    assert D._row_keys(row) == set(keys), D._row_keys(row)

    # 读侧函数实跑：用 dedup 自己的三级匹配去找这一行
    hit, key = D.find_existing_literature(store.rows("literature"), row["title"], None, None)
    assert hit is not None and hit["lit_id"] == row["lit_id"], hit
    assert key in D._row_keys(hit), (key, D._row_keys(hit))

    # DOI 那一档：同一个生成器产出的主键就是 `doi:` 形态，`_row_doi` 认它
    doi_keys = D.literature_keys("A paper", 2020, "https://doi.org/10.1234/AB")
    assert doi_keys[0] == "doi:10.1234/ab", doi_keys
    assert D._row_doi({"doi": None, "_keys": doi_keys}) == "10.1234/ab"


def test_locallib_builds_its_keys_with_the_shared_function(store, tmp_path, monkeypatch):
    """8' 负控：键必须来自 `dedup.literature_keys`，不是 locallib 里抄的第二份。

    把共用函数换成哨兵值 ⇒ 落库的键必须跟着换成哨兵；照抄一份实现的话，
    这个替换对它无效，键仍然是 `title:...|*` ⇒ 立刻红。
    """
    monkeypatch.setattr("agentflow.locallib.extract_text", lambda path: _FakeDoc())
    monkeypatch.setattr(D, "literature_keys", lambda *a, **k: ["title:sentinel|*"])
    ingest_directory(store, _books_dir(tmp_path), note="判据夹具")

    row = store.rows("literature")[0]
    assert row["dedup_key"] == "title:sentinel|*", row.get("dedup_key")
    assert row["_keys"] == ["title:sentinel|*"], row.get("_keys")
