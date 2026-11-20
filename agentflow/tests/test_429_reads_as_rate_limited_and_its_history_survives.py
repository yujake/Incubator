# -*- coding: utf-8 -*-
"""FIX429：429 在逐源读数上要读得出是限流，且成功登记不许把这段历史擦掉。

## 现场（真机 lp-ball-13，`agentflow/temp/minelit/MINE-LIT-REPORT.md` §D2/D3）

改前两处读数同形：429 与"出错了但不知道怎么归类"都写 `error_kind="unknown"`。

1. 逐源：`OpenAlexProvider.search` 每一路都失败时抛的是裸 `ProviderError`，
   不带 `status`/`kind` ⇒ `provider_error_kind` 落到最后一行 `return "unknown"`。
   `runs/A-…124522-001.json` step2/4/44 的 `sources[]` 就是
   `name=openalex, status=failed, error_kind=unknown`，正文才写着 429/冷却。
2. 台账：`_link_request` 在成功登记时无条件写 `last_error=None` ——
   r-000002 seq162（429）被 seq960/966 擦成 None；r-000004 seq1724 被 seq2346 擦成
   None。只有 r-000003 的 429 史活下来，因为 seq807 有一次人手 `table.update`。

## 这七条判据

* a：模拟 429（每一路都 429）⇒ 逐源 `error_kind=rate_limited`，且不是 `unknown`；
  聚合的那一句仍归 `external_unavailable`（既有的"外部不可用"语义不许被换掉）。
* a2：处在限流冷却期的源（真机 step2/4/44 的另一支）同样要读成 `rate_limited`。
* a3：403 / 超时 / 连不上各有自己的档（`forbidden` / `timeout` / `unreachable`）。
* b：429 之后一次成功登记 ⇒ 429 的原文仍在（两种真实行形状各一条）。
* c：第一次就成功的行 ⇒ 读数不变脏（`last_error` 仍是 None，行上不多一格）。
* d1：把分类打桩回 `unknown` ⇒ a 必红（证明 a 咬的是分类真身，不是常量）。
* d2：把"保留失败史"打桩回"清空" ⇒ b 必红。
"""
from __future__ import annotations

import pathlib
import urllib.error

import pytest

from agentflow import errorstats as ES
from agentflow import providers as P
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_for_role
from agentflow.tools import search_tools as ST

from conftest import TS, add_request

#: 真机 r-000002 seq162 / r-000004 seq1724 上那一段失败原文的形状（摘自台账）。
FAIL_429 = (
    "openalex: ProviderError: OpenAlex 每一路都失败（popular: HTTP 429 for "
    "https://api.openalex.org/works?search=isodiametric+inequality+plane）"
    "⇒ 这一次没有查成（不是「没有结果」）"
)


def _all_channels_429(self, plan):
    raise P.HttpError("HTTP 429 for https://api.openalex.org/works?search=cube", 429)


def _all_channels_403(self, plan):
    raise P.HttpError("HTTP 403 for https://api.openalex.org/works?search=cube", 403)


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    """冷却表是进程级的；每条判据前后清空，免得"上一条的 429"变成这一条的输入。"""
    P.clear_provider_cooldowns()
    yield
    P.clear_provider_cooldowns()


def _a_registry(store: Store, root: pathlib.Path):
    reg = build_for_role("A", store=store, workspace_root=root).registry
    reg.bound_role = "A"
    return reg


def _register(reg, **kw):
    args = {"role": "A", "title": "Cube slicing in R^n", "type_code": "J",
            "summary": "Ball 1986", "year": 1986}
    args.update(kw)
    res = reg.call("search.register", **args)
    assert res.ok, res.error
    return res.unwrap()


def _request(store: Store, request_id: str = "r-0001") -> dict:
    return next(dict(r) for r in store.rows("search_requests")
                if str(r.get("request_id")) == request_id)


def _seed(store: Store, *, done: bool, outcome: str | None, last_error: str | None) -> dict:
    """按真机那一行的形状插一条请求（`add_request` 不暴露 outcome，这里补上）。"""
    row = S.SearchRequest(
        request_id="r-0001", timestamp=TS, topic="cube slicing", mode="broad",
        done=done, outcome=outcome, last_error=last_error,
    )
    row.validate()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", row.to_dict())
    return row.to_dict()


# ---------------------------------------------------------------- a：429 的逐源读数


def test_a_429_on_every_channel_reads_as_rate_limited_not_unknown(monkeypatch):
    """改前：逐源 `error_kind="unknown"`（真机 A-124522 step2/4/44）。"""
    monkeypatch.setattr(P.OpenAlexProvider, "_fetch_with_fallback", _all_channels_429)
    oa = P.OpenAlexProvider(min_interval=0.0, retries=0)

    with pytest.raises(P.ProviderError) as caught:
        oa.search("cube slicing", "topical")

    kind = P.provider_error_kind(caught.value)
    assert kind == "rate_limited", (kind, caught.value)
    assert kind != "unknown", "429 又被折成'不知道怎么归类'了"

    # 逐源读数走真路径：MultiProvider 捕获聚合异常并写 last_stats。
    P.clear_provider_cooldowns()
    multi = P.MultiProvider([oa])
    multi.search("cube slicing", "topical")
    stat = multi.last_stats["openalex"]
    assert (stat.status, stat.count, stat.error_kind) == ("failed", 0, "rate_limited"), stat.to_dict()

    # 聚合面的既有语义没被换掉：A 写进 errors 的那一行仍归 external_unavailable。
    reading = f"openalex: {type(caught.value).__name__}: {caught.value}"
    assert ES._tool_refusal_family({"error": reading}) == ("ProviderError", "external_unavailable")


def test_a_source_cooling_down_after_a_429_is_still_rate_limited():
    """真机 step2/4/44 的另一支：源正在冷却，逐源读数也是 unknown —— 同一处修。"""
    P.start_provider_cooldown("openalex", 60)
    multi = P.MultiProvider([P.OpenAlexProvider(min_interval=0.0)])
    multi.search("cube slicing", "topical")

    stat = multi.last_stats["openalex"]
    assert stat.status == "failed", stat.to_dict()
    assert stat.error_kind == "rate_limited", stat.to_dict()


def test_403_timeout_and_connection_failure_have_their_own_kinds(monkeypatch):
    """403 是"这条通道不许进"、401 是"凭证不对"、超时/连不上各自一档。"""
    assert P.provider_error_kind(P.HttpError("HTTP 403 for x", 403)) == "forbidden"
    assert P.provider_error_kind(P.HttpError("HTTP 401 for x", 401)) == "auth_failed"
    assert P.provider_error_kind(TimeoutError("read timed out")) == "timeout"
    refused = urllib.error.URLError(ConnectionRefusedError("connection refused"))
    assert P.provider_error_kind(refused) == "unreachable"

    # 聚合面同一口径：每一路 403 ⇒ 逐源读数 forbidden（不是 unknown）。
    monkeypatch.setattr(P.OpenAlexProvider, "_fetch_with_fallback", _all_channels_403)
    with pytest.raises(P.ProviderError) as caught:
        P.OpenAlexProvider(min_interval=0.0).search("cube slicing", "topical")
    assert P.provider_error_kind(caught.value) == "forbidden"


# ---------------------------------------------------------------- b：成功登记不清历史


@pytest.mark.parametrize("done, outcome", [(False, None), (True, "search_failed")])
def test_a_successful_registration_keeps_the_429_history(tmp_path, done, outcome):
    """改前：`_link_request` 无条件写 `last_error=None` ⇒ 429 史被擦。

    两种行形状都是真机读到的：r-000004 seq1724（`done=False, outcome=None`，
    退避中）与 r-000002 seq162（`done=True, outcome=search_failed`）。
    """
    store = Store(tmp_path)
    store.init()
    _seed(store, done=done, outcome=outcome, last_error=FAIL_429)
    reg = _a_registry(store, tmp_path)

    _register(reg, request_id="r-0001")
    row = _request(store)

    assert row["outcome"] == "ok", row
    assert row["result_lit_ids"] == ["000000"], row
    last_error = str(row["last_error"] or "")
    assert "429" in last_error, f"成功登记把 429 史擦掉了：{row}"
    assert last_error == FAIL_429, "失败原文必须逐字留着，不是改写成别的句子"


def test_repeat_registrations_do_not_erase_what_the_first_one_kept(tmp_path):
    """同一请求连续登记三次（真机 seq2346/2350/2354）⇒ 429 史仍要在。"""
    store = Store(tmp_path)
    store.init()
    _seed(store, done=False, outcome=None, last_error=FAIL_429)
    reg = _a_registry(store, tmp_path)

    _register(reg, request_id="r-0001", title="Cube slicing in R^n")
    _register(reg, request_id="r-0001", title="Another slicing paper")
    _register(reg, request_id="r-0001", title="Third slicing paper")
    row = _request(store)

    assert len(row["result_lit_ids"]) == 3, row
    assert str(row["last_error"] or "") == FAIL_429, row


# ---------------------------------------------------------------- c：正控不脏


def test_a_first_time_success_stays_clean_and_gains_no_field(tmp_path):
    """没有失败史的行：`last_error` 仍是 None，行上也不许多出任何一格。"""
    store = Store(tmp_path)
    store.init()
    before = add_request(store, "r-0001", done=False)
    reg = _a_registry(store, tmp_path)

    _register(reg, request_id="r-0001")
    row = _request(store)

    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, row
    assert set(row) == set(before), (
        "为了留住历史往行上多塞字段了：", sorted(set(row) - set(before)))


def test_a_no_results_reading_is_still_replaced_by_the_success(tmp_path):
    """`no_results` 那一格的"命中 N 条、入库 0 条"不是失败读数，仍要随成功作废。

    这是 R9FIX 钉过的那一格：`outcome` 翻成 ok 之后，那句过期且相反的读数
    不能继续挂在行上。它与 429 的区别由 `outcome` 回答，不靠猜文本。
    """
    store = Store(tmp_path)
    store.init()
    add_request(store, "r-0001", done=True,
                last_error="命中 1 条、入库 0 条（待裁）")
    reg = _a_registry(store, tmp_path)

    _register(reg, request_id="r-0001")
    row = _request(store)

    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, row


# ---------------------------------------------------------------- d：反真空


def test_anti_vacuum_stubbing_the_classifier_back_to_unknown_makes_a_red(monkeypatch):
    """把分类打桩回 `unknown` ⇒ 第一条判据（`== "rate_limited"`）必红。"""
    monkeypatch.setattr(P, "provider_error_kind", lambda exc: "unknown")
    monkeypatch.setattr(P.OpenAlexProvider, "_fetch_with_fallback", _all_channels_429)

    with pytest.raises(P.ProviderError) as caught:
        P.OpenAlexProvider(min_interval=0.0).search("cube slicing", "topical")

    assert P.provider_error_kind(caught.value) == "unknown", (
        "打桩没生效：第一条判据读的可能不是分类真身")
    assert P.provider_error_kind(caught.value) != "rate_limited"


def test_anti_vacuum_forcing_the_old_clear_makes_b_red(tmp_path, monkeypatch):
    """把"保留失败史"打桩成"一律清空" ⇒ 第二条判据（429 仍在）必红。"""
    monkeypatch.setattr(ST, "_keeps_failure_history", lambda req: False)

    store = Store(tmp_path)
    store.init()
    _seed(store, done=True, outcome="search_failed", last_error=FAIL_429)
    reg = _a_registry(store, tmp_path)

    _register(reg, request_id="r-0001")
    row = _request(store)

    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, "打桩没生效：第二条判据读的可能不是这条判据"
