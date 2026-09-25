"""引文校验：三态判定 + 页码错误必须被显式标出（DESIGN.md §6.3）。

全部用例用**构造的 DocumentText 替身**（纯 dataclass），不依赖真实 PDF：
这样测试又快又确定，也不会因为 PDF 后端差异而飘。
"""

from __future__ import annotations

from abflow.extract import DocumentText
from abflow.quoteverify import check_quote
from abflow.schema import PageRange

P1 = "Group theory studies algebraic structures."
P2 = "An abelian group is a group in which the commutative law holds."
P3 = "The identity element is unique in every group."


def _doc(pages: list[str]) -> DocumentText:
    return DocumentText(text="\n".join(pages), pages=list(pages), source_kind="pdf")


def test_declared_page_hit_is_verified():
    """引文在声明页内命中 → verified=True 且 matched_page 指向真实页。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P2, PageRange(2, 2, "p. 2"))
    assert chk.verified is True
    assert chk.matched_page == 2
    assert chk.window == "declared:2-2"
    assert chk.reason == "substring_match"


def test_hit_outside_declared_range_is_flagged_explicitly():
    """声明页外但在 ±widen 内命中 → verified=True，但 reason 必须显式标出"页码错误"。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P2, PageRange(3, 3, "p. 3"), widen=1)
    assert chk.verified is True
    assert chk.matched_page == 2
    assert chk.reason == "substring_match_outside_declared_range"
    assert chk.window == "widened:2-3"

    backward = check_quote(doc, P3, PageRange(2, 2, "p. 2"), widen=1)
    assert backward.verified is True
    assert backward.matched_page == 3
    assert backward.reason == "substring_match_outside_declared_range"


def test_quote_not_found_is_false():
    """声明页与扩窗都找不到 → verified=False，reason=not_found。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, "This sentence appears nowhere in the document.", PageRange(1, 2, "pp. 1-2"))
    assert chk.verified is False
    assert chk.reason == "not_found"
    assert "declared:1-2" in chk.tried and "widened:1-3" in chk.tried


def test_quote_far_outside_widen_is_not_found():
    """超出 ±widen 的远处命中不算通过（页码错误不能被无限扩窗掩盖）。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P1, PageRange(3, 3, "p. 3"), widen=1)
    assert chk.verified is False
    assert chk.reason == "not_found"


def test_no_text_layer_is_none_not_false():
    """无文本层（pages=[]）→ verified is None 且 reason=no_text_layer（"没校验"≠"校验失败"）。"""
    chk = check_quote(_doc([]), P2, PageRange(1, 1, "p. 1"))
    assert chk.verified is None
    assert chk.reason == "no_text_layer"
    assert chk.matched_page is None
    assert chk.tried == ()


def test_unknown_page_without_fallback_is_false():
    """页码未知且不允许全文兜底 → verified=False 且 reason=not_found_page_unknown。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P2, PageRange(None, None, ""), allow_fulltext_fallback=False)
    assert chk.verified is False
    assert chk.reason == "not_found_page_unknown"
    assert chk.tried == ("no_window",)


def test_unknown_page_with_explicit_fallback_is_verified_but_labeled():
    """显式允许全文兜底时才算通过，并且必须如实回报用的是全文窗口。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, P2, PageRange(None, None, ""), allow_fulltext_fallback=True)
    assert chk.verified is True
    assert chk.matched_page == 2
    assert chk.window == "fulltext"
    assert chk.reason == "substring_match_fulltext"


def test_empty_quote_is_unknown_not_verified():
    """空引文无从校验 → verified is None（绝不能因为"没得比"就判通过）。"""
    chk = check_quote(_doc([P1, P2, P3]), "", PageRange(1, 1, "p. 1"))
    assert chk.verified is None
    assert chk.reason == "empty_quote"


def test_normalization_tolerates_case_and_whitespace_only():
    """允许的差异仅限大小写/空白折叠；多页范围内的引文仍可命中。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, "an ABELIAN group is a group in which the\n  commutative law holds.", PageRange(2, 3, "pp. 2-3"))
    assert chk.verified is True
    assert chk.matched_page == 2


def test_normalization_does_not_forgive_word_or_punctuation_changes():
    """不允许改词/删标点：'holds, for' 与 'holds for' 必须判为未命中（保守规范化）。"""
    doc = _doc(["Commutative law holds, for every pair."])
    chk = check_quote(doc, "Commutative law holds for every pair.", PageRange(1, 1, "p. 1"))
    assert chk.verified is False
    assert chk.reason == "not_found"


def test_unverified_relation_is_not_falsely_passed_with_wide_range():
    """整篇区间声明（1..n）也必须真的找到引文，不能因为窗口大就放行。"""
    doc = _doc([P1, P2, P3])
    chk = check_quote(doc, "No such sentence in this paper.", PageRange(1, 3, "pp. 1-3"))
    assert chk.verified is False
