# -*- coding: utf-8 -*-
"""S-09 的判据（非 LLM 半）：D 的 `conclusion` 措辞与 `confidence` 数字一致吗。

裁定（主控）：S-09 的 LLM 接线那一半属残余集 R1（E5 给 D 接 LLM，裁决 6 = B），
本轮不动；非 LLM 的那半（`conclusion` 一致性判据）现在做。

真机缺陷形态（`44 S-09`）：`_llm_refine` 只夹数字、文本原样采用 ⇒ 数字 0.3
而措辞写"证明了"。读报告的人（与下游引用者）看的是措辞，不是那个小数 ——
所以这是报告层面的夸大，必须有一条不依赖模型的判据盯住它。
"""
from __future__ import annotations

from agentflow.agent_d._support import conclusion_consistency_reading


def test_s09_low_confidence_with_an_overclaim_is_flagged():
    """判据（改前红：`conclusion_consistency_reading` 不存在 ⇒ AttributeError）。"""
    got = conclusion_consistency_reading(conclusion="我们证明了这条命题。", confidence=0.3)
    assert got["checked"] is True, got
    assert got["verdict"] == "overstated", got
    assert got["overclaim"] and got["confidence"] == 0.3, got
    assert "confidence=0.3" in got["reason"], got["reason"]


def test_s09_high_confidence_with_a_hedge_is_flagged():
    """另一半方向：数字很高而措辞留了很大余地（那会让读者低估我们的结论）。"""
    got = conclusion_consistency_reading(conclusion="这也许成立，有待进一步确认。", confidence=0.9)
    assert got["verdict"] == "understated", got
    assert got["hedge"], got


def test_s09_matching_directions_are_consistent():
    """正控：两个方向都对得上 ⇒ `consistent`（低数字 + 软措辞 / 高数字 + 硬措辞）。"""
    soft = conclusion_consistency_reading(conclusion="这也许成立。", confidence=0.2)
    hard = conclusion_consistency_reading(conclusion="我们证明了这条命题。", confidence=0.9)
    assert soft["verdict"] == "consistent" and hard["verdict"] == "consistent", (soft, hard)
    assert soft["reason"] == "" and hard["reason"] == "", (soft, hard)


def test_s09_a_plain_conclusion_is_not_flagged():
    """反负控（防"什么都判夸大"）：没有任何措辞标记 ⇒ 一律 `consistent`。"""
    got = conclusion_consistency_reading(conclusion="抽样与该结论一致。", confidence=0.1)
    assert got["verdict"] == "consistent" and got["overclaim"] == [], got


def test_s09_without_a_number_the_grid_is_not_checked():
    """三态：`confidence=None`（或不是数字）⇒ `checked=False` —— 不许折成"一致"。"""
    miss = conclusion_consistency_reading(conclusion="我们证明了它。", confidence=None)
    assert miss["checked"] is False and miss["verdict"] == "", miss
    assert "没查成" in miss["reason"], miss
    bad = conclusion_consistency_reading(conclusion="x", confidence="很高")
    assert bad["checked"] is False and "不是数字" in bad["reason"], bad
