# -*- coding: utf-8 -*-
"""引文回验接在 relations 写口 ＋ 正文闸接在 `search.register`（真机 lp-ball-14 的 P0-3 / P1-9）。

## 现场（只读取证，`temp/mine14/MINE14-REPORT.md` §3.2 / P0-3 / P1-9）

- 6 条关系（`rel:000003`–`000008`）是经 `table.create` / `table.update` 写的：
  `runs/B-20261121-013045-001.json` 的 step 14/22/24/25/28/29 建行、step 20/27/30 把
  `{"quote_verified": true, "quote_mode": "verbatim", "quote_span": ""}` 一起写下去；
  写路照收（`data/events.jsonl` seq 1864 的 `note="tool:table.create"`、`actor="tool"`）。
- 代码侧：`quoteevidence.enforce_quote_evidence`（D1 的写侧断言）在 `src/` 里只被
  `agent_b/run_once.py`（抽取那条路）与 `agent_b/register_statement.py` 调过；
  通用 relations 写口一次都没调（`git show HEAD:…/table_tools.py` 里 `quote_span`
  命中 0 次）⇒ "说逐字通过"与"算得出区间"在盘上是两件互不相干的事。
- 另一处同族缺口：`search.register`（`tools/search_tools.py:_h_register`）只校验
  `type_code` / `title` / 判重，不调 `litstage` 那道 ALITCONTENT 闸
  （`content_assertion_without_content`）⇒ A2 用它在 01:41–01:42 建了 5 条
  `content_read=false` 的 literature 行，summary 里带着内容性断言。

## 这一条判据钉什么

1. 关系写口的 `quote_verified=true` 必须在这一次写里由 `enforce_quote_evidence`
   当场算出可复算的 `quote_span`；算不出（没有全文 / 没有要比对的那一段）⇒ 降成
   `None` 并写清 reason（读数进 `meta.quote_evidence`，不许静默），语义档缺证据 / 无来源
   无背书 ⇒ 整笔受控拒。判据本体只有一份，本文件不重写"true 需要 span"。
2. `search.register` 的 `summary` 走同一条正文闸（`litavail.content_assertion` 判
   "算不算内容性断言"，`litavail.content_read` 判"读没读到正文"，受控码与
   `litstage` 共用）。候选链（`lit.admit` → `_registrar_from_candidate`）把现算的
   `read_ok` 交进来，读过的那一条照常写。

## 反真空（没有它，这条判据是橡皮图章）

把两处接线各自打桩掉（`table_tools._quote_evidence_on_relations_write` 恒放行、
`search_tools._content_claim_refusal` 恒放行）⇒ a / c 必须变红：同一笔会重新写出
`quote_verified=true`／内容断言照旧进库。见 `test_d_*`。
"""
from __future__ import annotations

import json
import re

import pytest

from agentflow import quoteevidence as QE
from agentflow import schema as S
from agentflow.extract import extract_text
from agentflow.store import Store
from agentflow.textutil import normalize_for_quote
from agentflow.tools import build_for_role
from agentflow.tools import search_tools
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

from conftest import add_concept, add_literature

A, B = "000002", "000004"
LIT = "000000"

#: 库里的那份全文（`.txt` ⇒ `pages=[全文]`，页码恒 1）。
FULLTEXT = (
    "Cube slicing in R^n.\n"
    "2. The lower bound. The lower bound will be an immediate consequence of the\n"
    "following simple probabilistic inequality, which compares a random variable with a\n"
    "uniformly distributed random variable of the same L^p-norm.\n"
)
QUOTE = "The lower bound will be an immediate consequence"
SPAN_RE = re.compile(r"^p\d+:norm\[\d+:\d+\]$")


def _concepts(store: Store) -> None:
    add_concept(store, A, "群")
    add_concept(store, B, "阿贝尔群")


def _lit_with_fulltext(store: Store) -> None:
    """一条有本地全文的文献行（写口要真去盘上取它）。"""
    target = store.library / LIT / "paper.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FULLTEXT, encoding="utf-8")
    add_literature(store, LIT, path=f"{LIT}/paper.txt",
                   download={"status": "ok", "fulltext": "ok", "bytes": len(FULLTEXT)})


def _lit_metadata_only(store: Store) -> None:
    add_literature(store, LIT, path=None, download={
        "status": "failed", "error": "no_local_path", "bytes": 0,
        "fulltext": "metadata_only"})


def _tables(store: Store) -> ToolRegistry:
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


def _relation_row(**over) -> dict:
    row = {"concept_ids": [A, B], "description": "描述", "lit_id": LIT, "quote": QUOTE}
    row.update(over)
    return row


def _disk(store: Store, relation_id: str) -> dict:
    return next(dict(r) for r in store.rows("relations")
                if str(r.get("relation_id")) == relation_id)


# ===================================================================== a：无全文 ⇒ 降档
def test_a_verified_without_a_fulltext_is_downgraded_with_a_reason(store: Store):
    """a：`quote_verified=true` 而这一条没有可比的全文 ⇒ 落 None + reason（改前：静默写 true）。

    "没有全文"是这一格最常见的样子（仅题录文献，真机那 5 条 metadata_only）：不是
    `False`（我们没证明原文里没有），也不是 `True`（没人核过）。
    """
    _concepts(store)
    _lit_metadata_only(store)
    reg = _tables(store)

    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote_verified=True, quote_mode="verbatim"))
    assert res.ok is True, res.error
    row = _disk(store, res.data)
    assert row["quote_verified"] is None, row
    assert row["quote_mode"] == "", row
    assert row["quote_span"] == "", row
    assert row["quote_reason"].strip(), "降档必须写清为什么（不许静默）"
    assert "unknown" in row["quote_reason"], row["quote_reason"]
    reading = res.meta.get("quote_evidence") or {}
    assert reading.get("action") == "downgrade", reading
    assert reading.get("why"), reading


def test_a2_update_cannot_assert_verified_true_without_evidence(store: Store):
    """a（第二个写口）：`table.update` 把 None 改成 true 也走同一道回验。"""
    _concepts(store)
    _lit_metadata_only(store)
    reg = _tables(store)
    made = reg.call("table.create", table="relations",
                    row=_relation_row(quote_verified=None, quote_reason="还没查"))
    assert made.ok is True, made.error

    res = reg.call("table.update", table="relations", id=made.data,
                   patch={"quote_verified": True, "quote_mode": "verbatim"})
    assert res.ok is True, res.error
    row = _disk(store, made.data)
    assert row["quote_verified"] is None, row
    assert "unknown" in row["quote_reason"], row["quote_reason"]
    assert (res.meta.get("quote_evidence") or {}).get("action") == "downgrade"


# ===================================================================== b：有全文 ⇒ 真回验
def test_b_a_locatable_quote_lands_true_with_a_recomputable_span(store: Store):
    """b（正控）：quote 在全文里逐字存在 ⇒ true ＋ 区间由这一次写算出来，可复算。"""
    _concepts(store)
    _lit_with_fulltext(store)
    reg = _tables(store)

    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote_verified=True, quote_mode="verbatim"))
    assert res.ok is True, res.error
    row = _disk(store, res.data)
    assert row["quote_verified"] is True, row
    assert row["quote_mode"] == "verbatim", row
    span = row["quote_span"]
    assert SPAN_RE.match(span), span

    # 复算：拿同一个区间在原文上切一刀，归一化后应当逐字等于归一化后的引文。
    doc = extract_text(store.library / LIT / "paper.txt")
    piece, page = QE.span_slice(doc, span)
    assert page == 1, page
    assert piece == normalize_for_quote(QUOTE), (piece, normalize_for_quote(QUOTE))
    assert QE.locate_span(doc, QUOTE) == span, (span, QE.locate_span(doc, QUOTE))
    assert (res.meta.get("quote_evidence") or {}).get("action") == "keep"


def test_b2_the_span_is_recomputed_not_trusted(store: Store):
    """b2：自报的 `quote_span` 只是线索 —— 落盘的是重算出来的那个（`p9:norm[0:1]` 不被采信）。"""
    _concepts(store)
    _lit_with_fulltext(store)
    reg = _tables(store)
    made = reg.call("table.create", table="relations",
                    row=_relation_row(quote_verified=None, quote_reason="还没查"))
    assert made.ok is True, made.error

    res = reg.call("table.update", table="relations", id=made.data,
                   patch={"quote_verified": True, "quote_mode": "verbatim",
                          "quote_span": "p9:norm[0:1]"})
    assert res.ok is True, res.error
    row = _disk(store, made.data)
    assert row["quote_verified"] is True, row
    assert row["quote_span"] != "p9:norm[0:1]", row
    assert row["quote_span"].startswith("p1:norm["), row["quote_span"]


def test_a3_a_quote_absent_from_the_fulltext_is_false_not_true(store: Store):
    """a3：有全文、整份里都没有这一段 ⇒ `False`（查过了、不一致），不是 true，也不是 unknown。"""
    _concepts(store)
    _lit_with_fulltext(store)
    reg = _tables(store)

    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote="this sentence is not in the paper at all",
                                     quote_verified=True, quote_mode="verbatim"))
    assert res.ok is True, res.error
    row = _disk(store, res.data)
    assert row["quote_verified"] is False, row
    assert "not_found" in row["quote_reason"], row["quote_reason"]
    assert (res.meta.get("quote_evidence") or {}).get("action") == "mismatch"


def test_a4_semantic_without_its_two_evidences_is_refused_whole(store: Store):
    """a4：`quote_mode="semantic"` 缺区间/调用指纹 ⇒ 整笔受控拒（判据的 refuse 档）。"""
    _concepts(store)
    _lit_with_fulltext(store)
    reg = _tables(store)

    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote_verified=True, quote_mode="semantic"))
    assert res.ok is False, ("没有证据的 semantic 竟然写进去了", res.meta)
    assert res.meta.get("kind") == "quote_evidence_refused", res.meta
    assert store.rows("relations") == [], "被拒的行不许有半个字节落盘"


# ============================================================ c：search.register 正文闸
def _a_registry(store: Store):
    reg = build_for_role("A", store=store, workspace_root=store.root).registry
    reg.bound_role = "A"
    return reg


def _register(reg, **kw):
    args = {"role": "A", "title": "Cube slicing in R^n", "type_code": "J",
            "summary": "题录：一篇讨论立方体截面的论文", "year": 1986}
    args.update(kw)
    return reg.call("search.register", **args)


def test_c_a_content_claim_without_reading_is_refused(store: Store):
    """c：`content_read=false`（直写路没有读过正文的证据）而 summary 写了内容性断言 ⇒ 受控拒。

    改前这一笔会进库（真机 A2 的 5 条 metadata_only 就是这么来的）。
    """
    reg = _a_registry(store)
    res = _register(reg, title="Gamma, beta, zeta",
                    summary="该文用 Bohr-Mollerup 定理给出 log Γ 的精确值，并证明了不等式")
    assert res.ok is False, ("内容性断言竟然进了库", res.data)
    assert res.meta.get("kind") == "content_assertion_without_content", res.meta
    assert res.meta.get("claim"), res.meta
    assert store.rows("literature") == [], "被拒的行不许有半个字节落盘"


def test_c2_a_metadata_only_summary_still_passes(store: Store):
    """c2（正控）：只写题录性说明 ⇒ 照常登记（这一闸不是"把登记一刀切封掉"）。"""
    reg = _a_registry(store)
    res = _register(reg, summary="题录：Ball 1986，AMS 期刊，立方体截面方向")
    assert res.ok is True, res.error
    assert res.data["created"] is True, res.data
    assert len(store.rows("literature")) == 1


def test_c3_a_proven_read_lets_the_same_claim_through(store: Store):
    """c3（正控）：候选链现算出"读过"（`read_ok=True`）⇒ 同一句内容性断言照常写。

    这一条钉的是"闸判的是读数不是措辞"：同一段 summary，读数不同，结论不同。
    """
    claim = "该文用 Bohr-Mollerup 定理给出 log Γ 的精确值，并证明了不等式"
    ctx = search_tools._Ctx(workspace=store.root, store=store)
    assert search_tools._content_claim_refusal(
        claim, read_ok=False) is not None, "没读过却放行 ⇒ 闸是空的"
    res = search_tools._h_register(ctx, "Gamma, beta, zeta", "J", claim, read_ok=True)
    assert res.ok is True, res.error
    assert len(store.rows("literature")) == 1


# ================================================================== d：反真空
def test_d_disabling_the_relations_wiring_brings_back_the_silent_true(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """d（a 的反真空）：把 relations 那一处接线打桩掉 ⇒ 同一笔重新写出 `true`（无区间）。

    打桩掉之后仍能写进去，说明 a 的降档是这道接线给的，不是别处顺手挡的。
    """
    _concepts(store)
    _lit_metadata_only(store)
    monkeypatch.setattr(table_tools, "_quote_evidence_on_relations_write",
                        lambda *a, **k: (None, {}))
    reg = _tables(store)
    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote_verified=True, quote_mode="verbatim"))
    assert res.ok is True, res.error
    row = _disk(store, res.data)
    assert row["quote_verified"] is True and row["quote_span"] == "", row
    assert not (res.meta.get("quote_evidence") or {}), res.meta


def test_d2_disabling_the_register_gate_lets_the_claim_land(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """d（c 的反真空）：把正文闸打桩掉 ⇒ 同一条内容性断言照旧进库。"""
    monkeypatch.setattr(search_tools, "_content_claim_refusal", lambda *a, **k: None)
    reg = _a_registry(store)
    res = _register(reg, title="Gamma, beta, zeta",
                    summary="该文证明了不等式，并给出 log Γ 的精确值")
    assert res.ok is True, res.error
    assert len(store.rows("literature")) == 1
    assert "不等式" in store.rows("literature")[0]["summary"]


# ======================================================= 取证读数：那 6 条若走新写口
def test_the_real_project_rows_are_recomputable(store: Store):
    """把 lp-ball-14 那 6 条关系的 quote 真值搬进夹具 ⇒ 新写口会算出区间（不是 unknown）。

    这一条是"真机复算"在测试里的锚：这 6 段引文逐字取自同一份全文（B 当时拿
    `out/texts/cand-000105.txt` 自核过），所以新写口给的是 `true + p:norm[...]`，
    而不是"只能降档"。
    """
    _concepts(store)
    _lit_with_fulltext(store)
    reg = _tables(store)
    quotes = [
        "The lower bound will be an immediate consequence",
        "which compares a random variable with a",
    ]
    spans = []
    for quote in quotes:
        res = reg.call("table.create", table="relations",
                       row=_relation_row(quote=quote, quote_verified=True,
                                         quote_mode="verbatim"))
        assert res.ok is True, res.error
        row = _disk(store, res.data)
        assert row["quote_verified"] is True, row
        assert SPAN_RE.match(row["quote_span"]), row
        spans.append(row["quote_span"])
    assert len(set(spans)) == len(spans), "不同的引文必须落在不同的区间"


def test_the_quote_fields_are_declared_where_the_table_is() -> None:
    """结构读数：`relations` 表确实有这四栏（闸接的是真字段，不是拼出来的名字）。"""
    names = {f.name for f in S.TABLES["relations"]["row"].__dataclass_fields__.values()}
    for key in table_tools._QUOTE_FIELDS:
        assert key in names, key


def test_the_written_reading_is_json_serialisable(store: Store):
    """`meta.quote_evidence` 要能进 run record（读数不许是看不懂的 Python 对象）。"""
    _concepts(store)
    _lit_metadata_only(store)
    reg = _tables(store)
    res = reg.call("table.create", table="relations",
                   row=_relation_row(quote_verified=True, quote_mode="verbatim"))
    assert res.ok is True, res.error
    json.dumps(res.meta["quote_evidence"], ensure_ascii=False)
