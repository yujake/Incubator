"""文本工具：normalize / similarity / slugify / parse_page_range（DESIGN.md §3.1-3.2）。"""

from __future__ import annotations

import pytest

from agentflow import textutil as T
from agentflow.schema import PageRange


# ------------------------------------------------------------------ normalize


def test_normalize_fullwidth_case_punct_whitespace():
    """全角、大小写、标点、空白必须被统一折叠（中英同一条路径）。"""
    assert T.normalize("  Hello,　World！ ") == "hello world"
    assert T.normalize("ＡＢＣ１２３") == "abc123"
    assert T.normalize("群、是《集合》") == "群 是 集合"
    assert T.normalize(None) == ""
    assert T.normalize("   ") == ""


def test_normalize_is_idempotent():
    """规范化必须幂等（否则判重键不稳定）。"""
    once = T.normalize("Let X be a Group.  ")
    assert T.normalize(once) == once


def test_normalize_for_quote_keeps_punctuation():
    """引文校验用的保守规范化不删标点，否则 'no, X' 与 'no X' 会被当成同一句。"""
    assert T.normalize_for_quote("No, X.") != T.normalize_for_quote("No X.")
    assert T.normalize_for_quote("A\u2014B") == "a-b"          # 破折号归一
    assert T.normalize_for_quote("  A   B\u00a0C ") == "a b c"  # 空白折叠


# ------------------------------------------------------------------ similarity


def test_similarity_english_jaccard():
    """英文按词做集合 Jaccard：3 个共享词 / 5 个并集词 = 0.6。"""
    assert T.similarity("The quick brown fox.", "the quick brown dog") == pytest.approx(0.6)


def test_similarity_chinese_bigram_jaccard():
    """中文按字符 bigram 做 Jaccard："群是集合" vs "环是集合" = 2/4。"""
    assert T.similarity("群是集合", "环是集合") == pytest.approx(0.5)
    assert T.similarity("阿贝尔群满足交换律", "阿贝尔群满足交换律") == pytest.approx(1.0)


def test_similarity_empty_is_zero_not_one():
    """两侧皆空返回 0.0（两个空串不构成"相同表述"，不能互相判重）。"""
    assert T.similarity("", "") == 0.0
    assert T.similarity("群", "") == 0.0


# ------------------------------------------------------------------ slugify


@pytest.mark.parametrize(
    "text",
    ["群论基础", "A Survey of Ring Theory", "///", "..", "", "a/b\\c:d*e?f"],
)
def test_slugify_never_empty_and_no_path_separators(text):
    """slugify 绝不返回空串，且结果不含路径分隔符（否则会生成目录路径）。"""
    slug = T.slugify(text)
    assert slug != ""
    assert "/" not in slug and "\\" not in slug
    assert not slug.startswith(".")


def test_slugify_keeps_cjk_and_respects_limit():
    """中文标题不必音译（保留 CJK），超长时按 limit 截断。"""
    assert T.slugify("群论基础") == "群论基础"
    assert T.slugify("a" * 200, limit=10) == "a" * 10


# ------------------------------------------------------------------ parse_page_range


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("pp. 45-67", 45, 67),
        ("pp.45–67", 45, 67),   # en dash
        ("p. 45", 45, 45),
        ("45-67", 45, 67),
        ("see pp. 45", 45, 45),
    ],
)
def test_parse_page_range_known_forms(text, start, end):
    """常见页码书写形态都要解析成结构化区间，并保留原书写形态作为 label。"""
    pr = T.parse_page_range(text)
    assert (pr.start, pr.end) == (start, end)
    assert pr.label == text.strip()
    assert pr.known is True


def test_parse_page_range_unknown_is_explicit():
    """解析不出来时显式返回未知（None,None），而不是编一个 1-1（§6.3 依赖这点）。"""
    pr = T.parse_page_range("no pages")
    assert isinstance(pr, PageRange)
    assert pr.start is None and pr.end is None
    assert pr.known is False
    assert pr.label == "no pages"
    empty = T.parse_page_range(None)
    assert empty.known is False and empty.label == ""


# ------------------------------------------------------------------ concept_group_key


def test_concept_group_key_sorted_and_deduped():
    """概念组键必须升序去重，保证"同一概念组"判定稳定。"""
    assert T.concept_group_key(["0002", "0001", "0002"]) == "0001|0002"
    assert T.concept_group_key(["0001", "0002"]) == T.concept_group_key(["0002", "0001"])
