# -*- coding: utf-8 -*-
"""`attackround` 的读数：把「前提步」与「推导步被声明成前提」分开（不改判据强度）。

调查报告：`temp/dep_probe/REPORT-dependency-surface.md`。机械后果那一格：可引池为空时
`assumption: true` 是唯一合法出口（`_clean_step` 只要求「有 `cites` 或 `assumption`」），
于是 83/84/85/87 的 262 个编号步骤里 244 个标成「（前提）」—— 而它们逐字都是
「由…得到…」「因此…」。本文件钉的是读数（`problems`）：真前提步不报，推导步被声明成
前提报一条并点名第几步；这一轮照旧被收下（拒收面一个字不动）。
"""
from __future__ import annotations

import json

from agentflow import attackround as AR


def _proof(steps: list[dict]) -> dict:
    """造一份成形的一轮（`parse_round` 的返回就是"返回读数"）。"""
    return AR.parse_round(json.dumps({
        "product": "proof", "strategy": "反证", "why_strategy": "反设结论不成立",
        "steps": steps,
    }, ensure_ascii=False))


# ============================================================ b：推导步被声明成前提

def test_b_a_derivation_step_declared_as_a_premise_is_reported_with_its_step_number() -> None:
    """第 3 步是推导步却标了 `assumption: true` ⇒ 一条 `problem`，点名第 3 步。"""
    got = _proof([
        # 第 1 步：真前提（先接受一个条件）—— 合法，不该报。
        {"text": "假设 G 是 3-正则、围长 6 的图", "assumption": True},
        # 第 2 步：引到在册命题的推导步 —— 合法，不该报。
        {"text": "取一条边 e，它的两个端点各有 2 个邻居", "cites": ["stmt:0001"]},
        # 第 3 步：正文在推导（「由…」「因此」），却被声明成前提。
        {"text": "由上面的假设与 stmt:0001 的计数，n=14 时边数为 21，因此结论成立",
         "assumption": True},
    ])

    assert got["product"] == "proof", "读数不许把这一轮改成拒收（判据强度不动）"
    problems = got["problems"]
    assert len(problems) == 1, f"应当恰好一条 problem（第 1、2 步都合法）：{problems}"
    problem = problems[0]
    assert "第 3 步" in problem, f"problem 没有点名第几步：{problem!r}"
    assert "这一步被声明成前提，但它是推导步" in problem, (
        f"problem 的措辞没有把「前提步」与「推导步被声明成前提」分开：{problem!r}")

    assert [s["role"] for s in got["steps"]] == ["前提步", "推导步", "推导步（被声明成前提）"], (
        got["steps"])


def test_b_a_real_premise_step_is_not_reported() -> None:
    """第 1 步是真前提步（假设）⇒ 不许报 problem；前提挂在在册命题上照旧合法。"""
    got = _proof([{"text": "假设 G 是 3-正则、围长 6 的图", "assumption": True}])
    assert got["problems"] == [], got["problems"]
    assert got["steps"][0]["role"] == "前提步", got["steps"][0]

    # I11 边界的合法形态：先接受一条在册命题（`tests/test_attack_round.py` 有一条同形夹具）。
    got2 = _proof([{"text": "设 stmt:0007 成立（本轮前提）", "cites": ["stmt:0007"],
                    "assumption": True}])
    assert got2["problems"] == [], (
        f"「前提挂在一条在册命题上」被误读成推导步了：{got2['problems']}")
    assert got2["steps"][0]["role"] == "前提步", got2["steps"][0]


def test_b_removing_the_problem_generation_turns_the_same_criterion_red(monkeypatch) -> None:
    """反真空：把 problem 的生成摘掉（这里用替身函数模拟）⇒ 同一个尺子必须红。

    正控那条（`..._is_reported_with_its_step_number`）读的就是 `problems`；生成一旦
    不被调用，它就必然红 —— 这一条把"红的原因"单独钉出来。
    """
    monkeypatch.setattr(AR, "_read_step_role",
                        lambda n, text, is_assumption: ("推导步", ""))

    got = _proof([
        {"text": "假设 G 是 3-正则、围长 6 的图", "assumption": True},
        {"text": "取一条边 e，它的两个端点各有 2 个邻居", "cites": ["stmt:0001"]},
        {"text": "由上面的假设与 stmt:0001 的计数，因此结论成立", "assumption": True},
    ])
    assert got["problems"] == [], (
        f"替身摘掉生成之后仍然有 problem ⇒ 反真空没有牙：{got['problems']}")
