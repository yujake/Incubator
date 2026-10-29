# -*- coding: utf-8 -*-
"""判据：B 的审美技能要写清"判档的是秘书（模型），力气读数只作参考"。

业主 2026-10-29：「全交给模型判，5 个等级的自然语言描述应该还在吧」「判档的还是 B 秘书」。

改前这份技能教的是机械口径（「五项合成一个分数，分数落格」「档位由机器按上面五项读数算，
不能靠多写两句自我评价改变」），与新的题面自相矛盾。改后必须：

1. 五档的自然语言定义仍在（业主原话）；
2. 明写判档的是自己（B 的秘书面），`effort` 只是参考读数；
3. 反真空：正文里不再出现 `EFFORT_TIER_BANDS` 或"档位由机器按…算"这类旧口径。
"""
from __future__ import annotations

from agentflow import agent_skills as AS


def _body() -> str:
    for _role, items in AS.CATALOG.items():
        for item in items:
            got = item if isinstance(item, dict) else getattr(item, "__dict__", {})
            if str(got.get("slug")) == "审美-太平凡的不收":
                return str(got.get("body") or "")
    raise AssertionError("技能表里没有 B 的审美技能 ⇒ 判据失去对象")


def test_the_five_definitions_are_still_there():
    """正题①：五档定义（业主原话）一处没丢。"""
    body = _body()
    assert "天才般的洞察力" in body, body[:400]
    # 技能正文按行宽折行，"有一定价值的非平凡结论"会被断成两行 ⇒ 分段断言
    assert "有一定价值的" in body and "非平凡结论" in body, body[:400]
    assert "基础定理或初步结论" in body, body[:400]


def test_the_body_says_the_secretary_judges_and_effort_is_only_a_reading():
    """正题②：判档的是秘书（模型），力气读数只作参考。"""
    body = _body()
    assert "参考读数" in body, body[:600]
    assert "判档的是你自己" in body, body[:600]
    assert "写得长不等于难" in body, body[:900]


def test_the_old_mechanical_claim_is_gone():
    """反真空：旧口径（按五项读数算档、不能靠自我评价改变）必须消失。"""
    body = _body()
    assert "EFFORT_TIER_BANDS" not in body, body[:600]
    assert "档位由机器按上面五项读数算" not in body, body[:600]
