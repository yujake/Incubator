# -*- coding: utf-8 -*-
"""FIX429B：`last_error` 的"最近一次失败"要在两条成功路径上同源。

## 现场（`temp/fix429/FIX429-REPORT.md` §7 残留洞 1）

FIX429 修好了工具层那条：`search_tools._link_request` 成功登记时不再无条件写
`last_error=None`。但 A 的自动链路还有另一条成功路径 ——
`agent_a/run_once.py` 的 `new_ids` 分支：这一轮取回并登记了东西、且本轮没有源失败时，
它照样写 `last_error = _source_failure_reading(...) or None`。

于是同一格在两条路径上语义分家：

* 工具层（`search.register`）：成功不动历史 ⇒ `last_error` = 最近一次失败；
* 自动链路（`run_once`）：成功且本轮无源失败 ⇒ 一律清 `None`。

真机可量：`r-000004` seq1724 的 429 被 seq2346 的 `search.register` 擦掉之后，
那一行是 `done=False, outcome=ok` —— 它还能被 A 再领走，再成功一次就把
`last_error` 又清成 `None`。所以"一处保留、一处擦"不是理论问题：后一条路径会把
前一条刚留住的原文抹掉。

## 这四条判据

* a：上一轮 429 → 本轮成功且无源失败 ⇒ 429 原文逐字留着（改前：被清成 `None`）。
* b 正控：从无失败史的行 ⇒ 成功之后 `last_error is None`，且行键集不变
  （为了留住历史往行上多塞字段会被它抓住）。
* b2：本轮有源失败 ⇒ 写的是本轮的读数（上一轮的原文让位给"最近一次失败"）。
* c 反真空：把 ① 的判定打桩回"一律清" ⇒ a 必红（而且打桩必须真的被调用到）。
"""
from __future__ import annotations

from agentflow import dedup as D
from agentflow import providers as P
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.store import Store
from agentflow.tools import search_tools as ST

from conftest import TS, add_request

#: 真机 r-000004 seq1724 上那一段 429 原文的形状（摘自 events.jsonl）。
FAIL_429 = (
    "OpenAlex 每一路都失败（popular: HTTP 429 for "
    "https://api.openalex.org/works?search=central+hyperplane+sections）"
    "⇒ 这一次没有查成（不是「没有结果」）"
)
#: A 把它写进行上的形状：`<源名>: <异常类型>: <原文>`（`core._search_along_wiring`）。
STORED_429 = f"openalex: ProviderError: {FAIL_429}"

TITLE = "Central hyperplane sections of l_p balls"
YEAR = 1986
DOI = "10.1000/demo.lpball"

#: 用来把退避租约变成"已到期"（模拟"上一轮的 429 已经退避到点"）。
PAST_LEASE = "2020-01-01T00:00:00+00:00"


class _Provider:
    """确定性 provider 替身：`error` 非空就抛，否则交回固定候选。"""

    def __init__(self, candidates=(), error: Exception | None = None):
        self.name = "openalex"
        self.candidates = list(candidates)
        self.error = error
        self.calls: list[str] = []

    def search(self, topic, mode, description, limit):
        self.calls.append(topic)
        if self.error is not None:
            raise self.error
        return list(self.candidates)


def _cand() -> P.Candidate:
    return P.Candidate(
        title=TITLE, year=YEAR, doi=DOI, authors=["A. Author"],
        venue="Demo Journal", type_code="J", summary="lp 球的中心截面。",
        pdf_url=None, landing_url=None, language="en", provider="openalex",
        raw={"provider": "openalex"},
    )


def _seed_literature(store: Store) -> None:
    """库里先有一篇：下一轮的候选命中它就走进"判重命中"那一支（`new_ids` 非空）。

    为什么用判重分支造"成功"：Q16 之后自动链路一条都不入库（`require_judged=True`），
    要让 `run_once` 走到 `new_ids` 那一支，最真实也最短的路就是"这一篇已经在库里"。
    """
    keys = D.literature_keys(TITLE, YEAR, DOI)
    row = S.Literature(
        lit_id="000001", title=TITLE, type="J", summary="", path=None,
        processed=False, source_request_ids=[], dedup_key=keys[0], doi=DOI,
        year=YEAR, added_at=TS,
    )
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="seed")


def _row(store: Store) -> dict:
    return next(dict(r) for r in store.rows("search_requests")
                if str(r.get("request_id")) == "r-0001")


def _expire_lease(store: Store) -> None:
    """把上一轮失败留下的退避租约改成已到期（`_claim` 的唯一判据是 `lease_expired`）。"""
    with store.tx("search_requests", actor="test") as tx:
        row = tx.find("search_requests", request_id="r-0001")
        assert row is not None
        row["lease_until"] = PAST_LEASE
        tx.upsert("search_requests", row, note="test_expire_lease")


def _agent(store: Store, provider: _Provider) -> AgentA:
    return AgentA(store, providers=[provider], downloader=None,
                  config={"download": False, "lease_seconds": 900, "max_attempts": 3})


def _fail_then_succeed(store: Store) -> tuple[AgentA, dict]:
    """造真机那一串：上一轮 429（退避）→ 租约到点 → 本轮成功（判重命中）。

    返回 `(agent, 本轮结束后的请求行)`。两条 429 都落在 `last_error` 里逐字可读。
    """
    _seed_literature(store)
    add_request(store, "r-0001", topic="central hyperplane sections of l_p balls")
    provider = _Provider()
    agent = _agent(store, provider)

    provider.error = P.ProviderError(FAIL_429)
    first = agent.run_once()
    assert first.request_id == "r-0001", first.to_dict()
    failed = _row(store)
    assert (failed["done"], failed["outcome"]) == (False, None), (
        f"夹具前提：429 那一轮是退避行（done=False / outcome=None），实得 {failed}")
    assert str(failed["last_error"] or "") == STORED_429, failed

    _expire_lease(store)
    provider.error = None
    provider.candidates = [_cand()]
    second = agent.run_once()
    assert (second.duplicated, second.registered) == (1, 0), (
        f"夹具前提：本轮必须走到判重命中那一支，实得 {second.to_dict()}")
    return agent, _row(store)


# ---------------------------------------------------------------- a：另一条成功路径
def test_a_second_round_success_keeps_the_previous_429_history(store):
    """改前红：`run_once` 的 `new_ids` 分支把 429 原文写成了 `None`。"""
    _, row = _fail_then_succeed(store)

    assert row["outcome"] == "ok", row
    assert row["result_lit_ids"] == ["000001"], row
    last_error = str(row["last_error"] or "")
    assert "429" in last_error, f"第二条成功路径把 429 史擦掉了：{row}"
    assert last_error == STORED_429, "失败原文必须逐字留着，不是改写成别的句子"


# ---------------------------------------------------------------- b：正控不脏
def test_b_a_row_without_failure_history_stays_clean_and_gains_no_field(store):
    """没有失败史的行：成功之后 `last_error` 仍是 None，行键集逐键相同。"""
    _seed_literature(store)
    before = add_request(store, "r-0001", topic="central hyperplane sections of l_p balls")
    provider = _Provider([_cand()])
    agent = _agent(store, provider)

    res = agent.run_once()
    assert (res.duplicated, res.registered) == (1, 0), res.to_dict()
    row = _row(store)

    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, row
    assert set(row) == set(before), (
        "为了留住历史往行上多塞字段了：", sorted(set(row) - set(before)))


# ---------------------------------------------------------------- b2：本轮失败优先
def test_b2_this_rounds_source_failure_wins_over_the_old_text(store):
    """本轮有源失败 ⇒ 写本轮的读数（"最近一次失败"是这一轮那句，不是上一轮那句）。"""
    _seed_literature(store)
    add_request(store, "r-0001", topic="central hyperplane sections of l_p balls")
    good = _Provider([_cand()])
    broken = _Provider()
    broken.name = "broken"
    agent = AgentA(store, providers=[good, broken], downloader=None,
                   config={"download": False, "lease_seconds": 900, "max_attempts": 3})

    broken.error = P.ProviderError("HTTP 503 Service Unavailable")
    res = agent.run_once()
    assert (res.duplicated, res.registered) == (1, 0), (
        f"夹具前提：一个源交回、另一个源失败，仍应走到判重命中那一支，实得 {res.to_dict()}")
    row = _row(store)

    last_error = str(row["last_error"] or "")
    assert "本次检索有 1 个源失败：broken" in last_error, last_error
    assert "429" not in last_error, "本轮没有 429，读数里不许出现上一轮那句"


# ---------------------------------------------------------------- c：反真空
def test_c_anti_vacuum_forcing_the_old_clear_makes_a_red(store, monkeypatch):
    """把 ① 的判定打桩回"一律清" ⇒ 第一条判据（429 仍在）必红。

    `seen` 那一格是打桩生效的物证：判定若没被调用（例如有人把判据又内联回
    `run_once`），这条判据就不是在说"清空会让 a 红"，而是在说"打桩没生效"。
    """
    seen: list[dict] = []

    def always_clear(req: dict) -> bool:
        seen.append(dict(req))
        return False

    monkeypatch.setattr(ST, "_keeps_failure_history", always_clear)

    _, row = _fail_then_succeed(store)

    assert seen, "① 的判定没有调用共判别据 `search_tools._keeps_failure_history`"
    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, "打桩没生效：a 读的可能不是这条判据"
