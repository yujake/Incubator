# -*- coding: utf-8 -*-
"""引文回验的两档（业主 2026-10-14）：「回验不应该是十分呆板的逐字验证，
而是保持语义相同即可」；落点是 **B 唤起 H**。

这一组守三件事：

1. **两栏的分工**：`quote_verified` 是三态结论，`quote_mode` 是**通过的方式**
   （`verbatim` 逐字命中 / `semantic` 语义相同）。两栏互相冒充的行不许拿到学分。
2. **历史行不许被追溯性降级**：`quote_mode` 这一栏是今天才有的，在那之前
   `quote_verified=True` 只可能来自 `quoteverify.check_quote`（逐字那一档）⇒
   空方式按 `verbatim` 读（判据 `test_a_legacy_external_lit_row_keeps_its_citation_credit`
   也钉着这条）。
3. **语义档不许被逐字档顶替**：H 判的"语义相同"与"结论强于引文"是两件事，
   后者仍必须落 `mismatch`（判据见 `quote_state` 的表）。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S


# ============================================================ 1 四态表
@pytest.mark.parametrize("row, want", [
    # 还没查
    ({"quote_verified": None}, "unchecked"),
    ({}, "unchecked"),
    # 查过了、不一致（语义档也救不了它：H 的判据是"说同一件事"）
    ({"quote_verified": False}, "mismatch"),
    ({"quote_verified": False, "quote_mode": "semantic"}, "mismatch"),
    # 通过的两档
    ({"quote_verified": True, "quote_mode": "verbatim"}, "verbatim"),
    ({"quote_verified": True, "quote_mode": "semantic"}, "semantic"),
    # 历史行：方式那一栏还没有的时代，True 只可能来自逐字那一档
    ({"quote_verified": True}, "verbatim"),
    ({"quote_verified": True, "quote_mode": ""}, "verbatim"),
    # 说不出方式的通过 ⇒ 按没查算（词表外的值就是"说不清"）
    ({"quote_verified": True, "quote_mode": "fuzzy"}, "unchecked"),
    ({"quote_verified": True, "quote_mode": "看起来一样"}, "unchecked"),
])
def test_the_quote_state_table(row: dict, want: str) -> None:
    """四态表（唯一读口径）：`unchecked` / `mismatch` / `verbatim` / `semantic`。"""
    assert EB.quote_state(row) == want, row
    assert EB.quote_explains_itself(row) == (want in S.QUOTE_MODES), row


# ============================================================ 2 写侧归一
def _stmt(**kw) -> S.Statement:
    base = dict(stmt_id="0001", origin="external_lit", statement_full="若 A 则 B",
                source_lit_id="0000", quote_reason="核对过")
    base.update(kw)
    return S.Statement(**base)


def test_a_bare_true_is_recorded_as_verbatim_not_left_empty() -> None:
    """只说了"通过"、没说方式的行**记实成 verbatim**（历史事实），不许留白。"""
    row = _stmt(quote_verified=True)
    row.validate()
    assert row.quote_mode == "verbatim", row.to_dict()
    assert row.to_dict()["quote_mode"] == "verbatim"


def test_the_semantic_verdict_is_kept_verbatim() -> None:
    """H 判的语义档原样留着 —— 不许被逐字档"顺手改写成" verbatim。"""
    row = _stmt(quote_verified=True, quote_mode="semantic")
    row.validate()
    assert row.quote_mode == "semantic", row.to_dict()


def test_a_mode_outside_the_vocabulary_is_refused() -> None:
    """词表外的值直接拒（两栏不许互相冒充这条靠它兜住）。"""
    with pytest.raises(ValueError) as got:
        _stmt(quote_verified=True, quote_mode="fuzzy").validate()
    assert "quote_mode" in str(got.value) and "verbatim" in str(got.value)


def test_a_row_that_did_not_pass_has_no_mode() -> None:
    """没通过/还没查的行，方式归空串 —— 留着会让人读成"用某种方式查过了"。"""
    for kw in ({"quote_verified": False, "quote_mode": "verbatim"},
               {"quote_verified": None, "quote_mode": "semantic"}):
        row = _stmt(**kw)
        row.validate()
        assert row.quote_mode == "", (kw, row.to_dict())


def test_the_relation_carries_the_same_two_columns() -> None:
    """关系行与命题行走同一对口径（引文挂在关系行上，那一栏才是主战场）。"""
    rel = S.Relation(relation_id="0001", concept_ids=["0001", "0002"],
                     description="d", lit_id="0000",
                     page_range=S.PageRange(1, 2, "p.1-2"),
                     quote_verified=True, quote_mode="semantic")
    rel.validate()
    assert rel.quote_mode == "semantic"
    assert rel.to_dict()["quote_mode"] == "semantic"
    with pytest.raises(ValueError):
        S.Relation(relation_id="0002", concept_ids=["0001", "0002"], description="d",
                   lit_id="0000", page_range=S.PageRange(1, 2, "p.1-2"),
                   quote_verified=True, quote_mode="maybe").validate()


# ============================================================ 3 学分
def test_the_citation_credit_needs_a_usable_mode() -> None:
    """引用命题的学分：两档都给（逐字 / 语义），说不清方式的不给。"""
    ok_v = {"stmt_id": "0001", "origin": "external_lit", "source_lit_id": "0001",
            "quote_verified": True, "quote_mode": "verbatim", "status": "active"}
    ok_s = {**ok_v, "stmt_id": "0002", "quote_mode": "semantic"}
    bad = {**ok_v, "stmt_id": "0003", "quote_mode": "fuzzy"}
    assert EB.bits_from_row(ok_v)["grade"] == EB.bits_from_row(ok_s)["grade"] != "conjecture"
    assert EB.bits_from_row(bad)["grade"] == "conjecture", EB.bits_from_row(bad)


def test_the_credit_reason_says_which_mode_it_was() -> None:
    """理由那一栏要把两档说开（读的人不该去猜"核过"是哪种核过）。"""
    rows = [{"stmt_id": "0001", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "verbatim"},
            {"stmt_id": "0002", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "semantic"}]
    from agentflow import evidencebits

    got = evidencebits.clean_statement_ids(rows)
    assert got["clean"] == ["0001", "0002"], got
    assert "逐字" in got["reasons"]["0001"], got
    assert "语义" in got["reasons"]["0002"], got
