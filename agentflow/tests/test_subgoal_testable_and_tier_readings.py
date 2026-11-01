# -*- coding: utf-8 -*-
"""两处「说的与实现差一格」：F 的子目标必填集、B 的档位读数（审计 171 F-02 / 172 R10）。

## t1：F.create_plan 的子目标是「四格必填」，不是三格

`agent_f/create_plan.py` 的判据（`subgoal_without_testable`）把 `testable` 与 `sid` /
`text` / `owner` 并列成硬条件，缺了整笔拒（`created=False`、一行都不写）；而 F 的手册
写着「每一项三格必填：`sid` / `text` / `owner`」，并说「少一格就被拒」—— 它列的是
不完整的必填集。按手册写，模型会漏掉 `testable`，然后撞一条它从没被告知的门。

## t2：档位只有 T0 会在工具结果里带读数

`agent_loop` 只对「T0（力气小）」回 `tier=T0` + `downgraded=true`；T1–T4 回 `None`，
没查成时回 `unjudged`。B 的 policy 原写「工具结果里带 `tier=T0`…`tier=T4`」⇒ B 会
在 T1–T4 的返回里找一个永远不存在的读数。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_skills as AL        # noqa: E402
from agentflow.agent_prompts import system_prompt  # noqa: E402
from agentflow.tools import build_registry       # noqa: E402

_REG = build_registry().registry


def _f_manual() -> str:
    """F 的手册全文（slug / 标题 / 索引两格 / 正文）。"""
    parts: list[str] = []
    for skill in AL.CATALOG["F"]:
        parts.append(f"### {skill.slug}")
        for field in ("title", "summary", "when", "body"):
            parts.append(str(getattr(skill, field)))
    return "\n".join(parts)


def test_f_manual_teaches_the_four_required_subgoal_fields() -> None:
    body = _f_manual()
    # 反真空：这一段真的在（否则"没有三格"可能只是没有这一节）。
    assert "`sid`" in body and "`owner`" in body, "F 手册里读不到子目标字段那一节"
    assert "三格必填" not in body, (
        "F 的手册还写「三格必填」—— 实现是四格（缺 `testable` 整笔拒 subgoal_without_testable）")
    assert "`testable`" in body, "F 的手册没把 `testable` 列成必填"
    assert "subgoal_without_testable" in body, (
        "F 的手册没点名那条受控码 —— 它对不上号就不知道这是硬条件")


def test_b_is_taught_that_only_t0_returns_a_reading() -> None:
    text = system_prompt("B", registry=_REG)
    # 反真空：这一格真的在。
    assert "收录要有审美" in text, "B 的提示词里没有判档位那一段 ⇒ 判据没有对象"
    assert "`tier=T0`…`tier=T4`" not in text, (
        "B 的提示词还说工具结果里带 tier=T0…tier=T4 —— 实现只有 T0 会回读数")
    assert "只有 T0" in text or "T0 会带读数" in text, (
        "B 的提示词没说清「只有 T0 会在工具结果里带读数」")
