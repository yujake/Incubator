"""schema 层：行级与表级不变量（DESIGN.md §1）。"""

from __future__ import annotations

import pytest

from agentflow import schema as S


# ------------------------------------------------------------------ PageRange


def test_page_range_start_greater_than_end_rejected():
    """start > end 的页码范围必须被拒绝（§1.4 不变量）。"""
    with pytest.raises(ValueError):
        S.PageRange(start=46, end=45)


def test_page_range_non_positive_start_or_end_rejected():
    """页码是 1-based 闭区间，0 或负数必须被拒绝。"""
    with pytest.raises(ValueError):
        S.PageRange(start=0, end=3)
    with pytest.raises(ValueError):
        S.PageRange(start=1, end=0)


def test_page_range_unknown_is_allowed_and_marked_unknown():
    """页码未知用 (None, None) 显式表达，且 known 为 False（不能编一个 0）。"""
    pr = S.PageRange(None, None, "no pages")
    assert pr.known is False
    assert pr.start is None and pr.end is None
    assert S.PageRange(45, 67, "pp. 45-67").known is True


# ------------------------------------------------------------------ Concept


def test_concept_related_concepts_must_be_sorted_unique():
    """related_concepts 未升序必须抛错（需求明确要求升序）。"""
    c = S.Concept(concept_id="0000", name="群", definition="", related_concepts=["0002", "0001"])
    with pytest.raises(ValueError):
        c.validate()
    dup = S.Concept(concept_id="0000", name="群", definition="", related_concepts=["0001", "0001"])
    with pytest.raises(ValueError):
        dup.validate()


def test_concept_related_concepts_must_not_contain_self():
    """related_concepts 含自身必须抛错（§1.3 不变量）。"""
    c = S.Concept(concept_id="0000", name="群", definition="", related_concepts=["0000"])
    with pytest.raises(ValueError):
        c.validate()


def test_concept_related_concepts_elements_must_be_ids():
    """related_concepts 的元素必须是 4 位 ID 形态。"""
    c = S.Concept(concept_id="0000", name="群", definition="", related_concepts=["7"])
    with pytest.raises(ValueError):
        c.validate()


# ------------------------------------------------------------------ SearchRequest


def test_precise_mode_requires_content_description():
    """precise 模式没有 content_description 时必须抛错（§1.1 不变量）。"""
    req = S.SearchRequest(
        request_id="r-0001",
        timestamp="2026-01-01T00:00:00+00:00",
        topic="域的定义",
        mode="precise",
        content_description="",
    )
    with pytest.raises(ValueError):
        req.validate()


def test_done_requires_result_or_explicit_error():
    """done=true 却既无 result_lit_ids 也无 last_error 必须抛错（"完成"必须可验证）。"""
    req = S.SearchRequest(
        request_id="r-0001",
        timestamp="2026-01-01T00:00:00+00:00",
        topic="群论",
        mode="broad",
        done=True,
    )
    with pytest.raises(ValueError):
        req.validate()


def test_done_with_last_error_is_valid():
    """done=true + last_error（显式"确认无结果/已放弃"）是合法组合。"""
    req = S.SearchRequest(
        request_id="r-0001",
        timestamp="2026-01-01T00:00:00+00:00",
        topic="群论",
        mode="broad",
        done=True,
        last_error="超过最大尝试次数 3，已放弃",
    )
    req.validate()


def test_unknown_mode_rejected():
    """mode 必须在受控词表内。"""
    req = S.SearchRequest(
        request_id="r-0001",
        timestamp="2026-01-01T00:00:00+00:00",
        topic="群论",
        mode="deep",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError):
        req.validate()


# ------------------------------------------------------------------ Literature


@pytest.mark.parametrize("bad_path", ["../secret.pdf", "a/../../b.pdf", "/abs/x.pdf", "C:/x.pdf"])
def test_literature_path_must_stay_inside_library(bad_path):
    """path 含 .. 或绝对路径必须抛错（防路径穿越，§1.2）。"""
    lit = S.Literature(lit_id="0000", title="T", type="J", summary="", path=bad_path)
    with pytest.raises(ValueError):
        lit.validate()


def test_literature_path_none_is_allowed_for_failed_download():
    """下载失败时 path 允许为 None（§1.2 不变量）。"""
    S.Literature(lit_id="0000", title="T", type="J", summary="", path=None).validate()


def test_literature_type_must_be_in_controlled_vocabulary():
    """type 不在 GB/T 7714 词表内必须抛错（§1.5）。"""
    lit = S.Literature(lit_id="0000", title="T", type="XX", summary="", path=None)
    with pytest.raises(ValueError):
        lit.validate()


# ------------------------------------------------------------------ Relation / 表级


def test_relation_needs_at_least_two_concepts():
    """概念代号组长度必须 ≥ 2（§1.4）。"""
    rel = S.Relation(
        relation_id="0000",
        concept_ids=["0000"],
        description="d",
        lit_id="0000",
        page_range=S.PageRange(1, 1, "p. 1"),
    )
    with pytest.raises(ValueError):
        rel.validate()


def test_relation_status_must_be_in_controlled_vocabulary():
    """status 只能是 active / suspect / rejected。"""
    rel = S.Relation(
        relation_id="0000",
        concept_ids=["0000", "0001"],
        description="d",
        lit_id="0000",
        page_range=S.PageRange(1, 1, "p. 1"),
        status="maybe",
    )
    with pytest.raises(ValueError):
        rel.validate()


def test_validate_table_rejects_duplicate_ids():
    """同一张表里出现重复主键必须抛错（否则 upsert 会静默互相覆盖）。"""
    good = S.Concept(concept_id="0000", name="群", definition="").to_dict()
    doc = {"schema_version": S.SCHEMA_VERSION, "rows": [good, dict(good)]}
    with pytest.raises(ValueError):
        S.validate_table("concepts", doc)


def test_validate_table_rejects_wrong_schema_version():
    """schema_version 不匹配必须抛错，避免把旧格式当新格式解析。"""
    with pytest.raises(ValueError):
        S.validate_table("concepts", {"schema_version": 999, "rows": []})
