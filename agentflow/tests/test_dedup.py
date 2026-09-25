"""判重：文献三级键 / 概念精确合并 / 关系三档（DESIGN.md §3）。"""

from __future__ import annotations

import pytest

from agentflow import dedup as D
from agentflow import textutil as T


def _seq(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def _quote(words: list[str]) -> str:
    return " ".join(words) + "."


# ------------------------------------------------------------------ 文献三级键


@pytest.mark.parametrize(
    "raw",
    ["https://doi.org/10.1/x", "http://doi.org/10.1/x", "doi:10.1/X", "10.1/X", "  10.1/x  "],
)
def test_normalize_doi_equivalence(raw):
    """DOI 归一化：URL 前缀/doi: 前缀/大小写/首尾空白都应等价（§3.5 第一级键）。"""
    assert D.normalize_doi(raw) == "10.1/x"


def test_literature_dedup_doi_priority_over_title():
    """DOI 命中即认定同一篇，即使标题与年份完全不同（DOI 是最高优先级的硬键）。"""
    rows = [
        {"lit_id": "0000", "title": "Completely different title", "dedup_key": "doi:10.1/x"},
    ]
    hit, key = D.find_existing_literature(rows, "另一个标题", 2000, "https://doi.org/10.1/X")
    assert hit is not None and hit["lit_id"] == "0000"
    assert key == "doi:10.1/x"


def test_literature_dedup_by_title_and_year():
    """没有 DOI 时退到"标题规范化 + 年份"这一级。"""
    rows = [{"lit_id": "0000", "title": "A Survey of Ring Theory", "dedup_key": "title:a survey of ring theory|1940"}]
    hit, key = D.find_existing_literature(rows, "a survey of RING theory!", 1940, None)
    assert hit is not None and hit["lit_id"] == "0000"
    assert key.startswith("title:")


def test_literature_dedup_same_title_different_year_is_new():
    """同名不同年（如两本不同版本的书）不得合并。"""
    rows = [{"lit_id": "0000", "title": "Group Theory", "dedup_key": "title:group theory|1960"}]
    hit, _key = D.find_existing_literature(rows, "Group Theory", 2020, None)
    assert hit is None


def test_literature_dedup_uses_secondary_keys_stored_on_row():
    """agent_a 会把全部候选键挂在 `_keys` 上；即使 dedup_key 不匹配也要用 `_keys` 兜住。"""
    rows = [
        {
            "lit_id": "0000",
            "title": "Commutativity",
            "dedup_key": "title:commutativity|1930",
            "_keys": ["doi:10.1/x", "title:commutativity|1930"],
        }
    ]
    hit, key = D.find_existing_literature(rows, "另一个标题", 2000, "https://doi.org/10.1/X")
    assert hit is not None and hit["lit_id"] == "0000"
    assert key == "doi:10.1/x"


# ------------------------------------------------------------------ 概念判重


def test_find_concept_matches_normalized_name_and_aliases():
    """概念只按规范化名字/别名精确合并（不做相似度自动归并，§3.4）。"""
    rows = [{"concept_id": "0000", "name": "群", "normalized_name": "群", "aliases": ["group"]}]
    assert D.find_concept(rows, "群")["concept_id"] == "0000"
    assert D.find_concept(rows, "GROUP")["concept_id"] == "0000"
    # 相似但不同名不得合并
    assert D.find_concept(rows, "环") is None
    assert D.find_concept(rows, "群论") is None


# ------------------------------------------------------------------ 关系三档


def _rel(rid: str, group: str, quote: str, status: str = "active") -> dict:
    return {
        "relation_id": rid,
        "concept_group_key": group,
        "quote": quote,
        "quote_normalized": T.normalize_for_quote(quote),
        "status": status,
    }


def test_relation_exact_same_quote_is_duplicate():
    """概念组相同且引文规范化后完全相等 → duplicate（§3.3 第 1 档）。"""
    q = _quote(_seq("c", 10))
    d = D.decide_relation([_rel("0000", "0000|0001", q)], concept_group_key="0000|0001", quote=q)
    assert d.kind == "duplicate"
    assert d.existing_id == "0000"
    assert d.should_write is False
    assert d.status == "rejected"
    assert d.detail["reason"] == "exact_quote_match"


def test_relation_high_similarity_is_duplicate():
    """Jaccard ≥ dup_strong(0.92) 但文本不同 → 仍判 duplicate（拒绝写入）。"""
    common = _seq("c", 49)
    old = _quote(common + ["oldtail0"])
    new = _quote(common + ["newtail0"])
    assert 0.92 <= T.similarity(old, new) < 1.0
    d = D.decide_relation([_rel("0000", "0000|0001", old)], concept_group_key="0000|0001", quote=new)
    assert d.kind == "duplicate"
    assert d.score >= 0.92
    assert d.existing_id == "0000"


def test_relation_mid_similarity_is_suspect():
    """0.72 ≤ Jaccard < 0.92 → 写入但置 suspect，并记 duplicate_of（可审计的中间态）。"""
    common = _seq("c", 36)
    old = _quote(common + _seq("old", 4))
    new = _quote(common + _seq("new", 4))
    assert 0.72 <= T.similarity(old, new) < 0.92
    d = D.decide_relation([_rel("0007", "0000|0001", old)], concept_group_key="0000|0001", quote=new)
    assert d.kind == "suspect"
    assert d.should_write is True
    assert d.status == "suspect"
    assert d.existing_id == "0007"


def test_relation_low_similarity_is_new():
    """Jaccard < dup_review(0.72) → 正常写入 active。"""
    old = _quote(_seq("c", 10) + _seq("old", 10))
    new = _quote(_seq("c", 10) + _seq("new", 10))
    d = D.decide_relation([_rel("0000", "0000|0001", old)], concept_group_key="0000|0001", quote=new)
    assert d.kind == "new"
    assert d.status == "active"
    assert d.should_write is True


def test_relation_different_concept_group_is_new_even_if_text_identical():
    """不同概念组即使引文逐字相同也判 new（§3.3 的关键规则：不同知识点）。"""
    q = _quote(_seq("c", 10))
    d = D.decide_relation([_rel("0000", "0000|0001", q)], concept_group_key="0002|0003", quote=q)
    assert d.kind == "new"
    assert d.existing_id is None


def test_relation_dedup_ignores_rejected_rows():
    """status=rejected 的关系不参与判重比较（否则被拒过的引文永远写不进来）。"""
    q = _quote(_seq("c", 10))
    d = D.decide_relation(
        [_rel("0000", "0000|0001", q, status="rejected")],
        concept_group_key="0000|0001",
        quote=q,
    )
    assert d.kind == "new"


def test_relation_dedup_counts_suspect_rows():
    """suspect 关系参与判重（它是已落库的行，重复提交同一引文应被判重）。"""
    q = _quote(_seq("c", 10))
    d = D.decide_relation(
        [_rel("0000", "0000|0001", q, status="suspect")],
        concept_group_key="0000|0001",
        quote=q,
    )
    assert d.kind == "duplicate"


def test_relation_empty_quote_is_suspect_not_active():
    """同一概念组内引文为空（历史数据/无文本层）→ 无法判重，保守地标 suspect 交复核。"""
    existing = [_rel("0000", "0000|0001", _quote(_seq("c", 10)))]
    d = D.decide_relation(existing, concept_group_key="0000|0001", quote="")
    assert d.kind == "suspect"
    assert d.should_write is True
    assert d.detail["reason"] == "empty_quote"


def test_relation_dedup_key_is_stable_and_group_scoped():
    """关系 dedup_key 必须稳定（同输入同输出）且含概念组，保证幂等重跑不产生重复行。"""
    q = "A group is a set."
    k1 = D.relation_dedup_key("0000|0001", q)
    k2 = D.relation_dedup_key("0000|0001", "A  Group is a SET.")
    assert k1 == k2
    assert k1 != D.relation_dedup_key("0000|0002", q)
    assert k1.startswith("0000|0001::")


# ------------------------------------------------------------------ related_concepts 派生


def test_derive_related_concepts_excludes_self_sorted_unique():
    """由关系派生：排除自身、升序去重（§6.2）。"""
    relations = [
        {"relation_id": "0000", "concept_ids": ["0001", "0002"], "status": "active"},
        {"relation_id": "0001", "concept_ids": ["0000", "0001"], "status": "active"},
    ]
    assert D.derive_related_concepts("0001", relations) == ["0000", "0002"]


def test_derive_related_concepts_ignores_rejected_but_counts_suspect():
    """rejected 不计入；suspect 计入（保守：宁可多连，等复核）。"""
    relations = [
        {"relation_id": "0000", "concept_ids": ["0000", "0002"], "status": "rejected"},
        {"relation_id": "0001", "concept_ids": ["0000", "0003"], "status": "suspect"},
        {"relation_id": "0002", "concept_ids": ["0000", "0004"], "status": "active"},
    ]
    assert D.derive_related_concepts("0000", relations) == ["0003", "0004"]


def test_derive_related_concepts_include_suspect_flag():
    """include_suspect=False 时 suspect 关系被排除（供"严格模式"复用同一函数）。"""
    relations = [{"relation_id": "0001", "concept_ids": ["0000", "0003"], "status": "suspect"}]
    assert D.derive_related_concepts("0000", relations, include_suspect=False) == []
