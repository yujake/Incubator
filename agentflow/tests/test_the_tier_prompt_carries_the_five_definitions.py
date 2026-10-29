# -*- coding: utf-8 -*-
"""判据：判档那一问的题面给的是五档自然语言定义，不是分数表。

业主 2026-10-29：「全交给模型判，5 个等级的自然语言描述应该还在吧」。

改前那一支要求模型回 `nontriviality_basis` = 「分数 7 = 体量 5164 字/2 + 步骤 8/1 + …」，
等于让模型复述机器算好的分数 —— 档位实际由分数落格决定。改后题面必须是五句定义，
并且明写 effort 只作参考。

## 这一组守什么

1. 正题：题面里五档定义（T0..T4 各一句）逐条在场，并写清"参考读数"；
2. 反真空：题面不再要求复述分数（"把分数"这种指令必须消失）。
"""
from __future__ import annotations

from agentflow.secretary import _judge_system

FIVE = ("T0 基础定理或初步结论", "T1 有一定价值的非平凡结论",
        "T2 证明方法都是平凡的", "T3 需要用较多的技巧或跨领域工具",
        "T4 需要天才般的洞察力")


def test_the_prompt_carries_the_five_owner_definitions():
    """正题：T0..T4 五句原话都在题面里。"""
    text = _judge_system("statement_aesthetic")
    for line in FIVE:
        assert line in text, (line, text[:600])


def test_the_prompt_says_the_effort_numbers_are_only_a_reference():
    """正题：明写 effort 只作参考（写得长不等于难）。"""
    text = _judge_system("statement_aesthetic")
    assert "参考读数" in text, text[:600]
    assert "不等于难" in text, text[:600]


def test_the_prompt_no_longer_asks_to_recite_the_score():
    """反真空：不再要求"把分数写出来"。"""
    text = _judge_system("statement_aesthetic")
    assert "把分数" not in text, text[:600]
