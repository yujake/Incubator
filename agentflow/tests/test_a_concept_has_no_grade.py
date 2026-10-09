# -*- coding: utf-8 -*-
"""概念行不参与等级（`draft/97` §14.5）——并表之后的第一条读数纪律。

并表之后 `concepts` 与 `statements` 住同一张表，等级由 `evidencebits.derive_grade` 现算。
概念没有证据位（`bits={}`）⇒ 照常派生就会得到最弱那一档"猜想"。而"猜想"是一句关于
真值的话（"还没证出来"），概念根本没有真值可言（它只有"良定义没良定义"）
⇒ 于是每条概念都会被读成"还没证的猜想"，这个读数在报告里是错的。

口径：`derive_grade(bits, kind="concept")` 短路成 `GRADE_NOT_APPLICABLE`（"不适用"），
它不在 `GRADES` 里 —— 不参与排序、不算进"定理有几条"。

## 这一组守什么

- 正控：概念行的现算等级是"不适用"（改前是"猜想" ⇒ 改前必红）、带这一档的 `bits` 能被写进去；
- 负控：命题行的等级一个字不变（空 bits ⇒ 猜想；第 2+4 位 ⇒ 正式定理）；
- 反真空：这一档不在 `GRADES` 里（进了链就会被排序、被算进定理计数）、
  `audited_badge` 对概念不成立、`clean_statement_ids` 给概念的理由说的是
  "它不是一条有真值的断言"（不是"等级太低"）。
"""

from __future__ import annotations

from agentflow import evidencebits as EB
from agentflow import schema as S


def test_a_concept_row_has_no_grade():
    """概念行的现算等级是「不适用」（改前它会被读成"猜想"）。"""
    bits = EB.bits_from_row({"stmt_id": "0001", "kind": "concept", "bits": {}})
    assert bits["grade"] == EB.GRADE_NOT_APPLICABLE, bits["grade"]
    assert bits["grade"] != "conjecture", "概念不是'猜想'：那句话在说真值，概念没有真值"
    assert EB.GRADE_LABELS[EB.GRADE_NOT_APPLICABLE] == "不适用（概念行不参与等级）"
    # 走写入口也一样（`bits_of` 的 kind 形参）
    assert EB.bits_of(kind="concept")["grade"] == EB.GRADE_NOT_APPLICABLE


def test_a_theorem_row_is_graded_exactly_as_before():
    """负控：命题行的等级一个字不变（这一改不许动到那条链）。"""
    empty = EB.bits_from_row({"stmt_id": "0002", "kind": "theorem", "bits": {}})
    assert empty["grade"] == "conjecture"
    strong = EB.bits_from_row({"stmt_id": "0003", "kind": "lemma", "bits": {
        "numeric": "verified", "evidence": {"numeric": {"experiment_id": "0001"}}}})
    assert strong["grade"] == "strong_conjecture"
    theorem = EB.bits_of(proof=True, proof_process="逐步论证……", formal="verified",
                         formal_evidence={"checker": "lean4"})
    assert theorem["grade"] == "theorem"


def test_the_not_applicable_value_is_not_in_the_grade_chain():
    """反真空：这一档不在 `GRADES` 里 —— 进了链就会被排序、被算进定理计数。"""
    assert EB.GRADE_NOT_APPLICABLE not in EB.GRADES, EB.GRADES
    assert set(EB.GRADES) == {"conjecture", "strong_conjecture", "pre_theorem", "theorem"}
    # 概念即便五位里有'审过'也不该挂"已过正式审查"的徽章
    bits = EB.bits_of(reviewed=True, reviewed_by={"round": 1}, audited=True,
                      audited_by={"round": 1}, kind="concept")
    assert bits["grade"] == EB.GRADE_NOT_APPLICABLE and bits["audited_badge"] is False


def test_a_concept_row_can_be_written_with_that_grade():
    """写入口：概念行带这一档 `bits` 时 `Statement.validate` 照过（自报等级那一比也按 kind 算）。"""
    row = S.Statement(stmt_id="0001", origin="own_result", kind="concept", label="谱",
                      statement_full="矩阵的谱", proof_text="concept:primitive",
                      quote_reason="原始概念：良定义性义务为空", status="active",
                      bits=EB.bits_of(kind="concept"))
    row.validate()
    assert row.bits["grade"] == EB.GRADE_NOT_APPLICABLE
    # 负控：把命题行的等级塞成"不适用" ⇒ 拒（等级不许自报错）
    bad = S.Statement(stmt_id="0002", origin="own_result", kind="theorem", label="定理",
                      statement_full="设 G 连通……", proof_text="Proof. ……",
                      quote_reason="自产", status="active",
                      bits={"grade": EB.GRADE_NOT_APPLICABLE})
    try:
        bad.validate()
    except ValueError as exc:
        assert "等级不许自报" in str(exc) or "现算" in str(exc), str(exc)
    else:
        raise AssertionError("命题行自报 grade=not_applicable 必须被拒（改前必红的那一格）")


def test_the_clean_set_says_why_a_concept_is_not_a_basis():
    """概念不在"干净引用对象"里，但理由要说对（不是"等级太低"）。"""
    out = EB.clean_statement_ids([{"stmt_id": "0001", "kind": "concept", "bits": {}}])
    assert out["clean"] == []
    why = out["reasons"]["0001"]
    assert "不参与等级" in why and "定义" in why, why
    assert "等级只有" not in why, "概念的问题不是'等级太低'（它根本没有等级这一说）"
