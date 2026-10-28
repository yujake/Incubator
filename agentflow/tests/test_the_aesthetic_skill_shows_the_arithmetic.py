# -*- coding: utf-8 -*-
"""判据：B 的审美技能必须把"太平凡"的算术摆出来，说清它不评数学价值。

## 现场（2026-10-28，业主：「平凡怎么能这么判」）

页面上五条命题全判"太平凡"，理由都写着"分数 0（体量 1425 字、步骤 0、引理 0、工具簇 1、
绕路 0）"。查下来它不是模型读出来的判断，是算术：

```
score = 体量字 // 2000 + 编号步骤 // 6 + 不同引理 // 2 + max(0, 簇-1) + 绕路
T0 = 0-1 分
```

`chars // 2000` 在 0-1999 字之间恒为 0 ⇒ 1400 字的短证明与 5 个字的空话在这一项上完全
一样；五条（1425/1527/1592/1815/1692 字）分全为 0 ⇒ 全落 T0。而"太平凡"这个词读起来像在
评数学价值。

## 这一组守什么

1. 技能正文里有那条公式（`// 2000` 与档位边界）与"不是在评数学价值"那句话；
2. 五条真机读数写进正文（读的人知道这是算术，不是个案）；
3. 词表不动：`statement_aesthetic` 的判定词仍是 合格/太平凡/判不了 —— 改词是一次
   受控词表变更（下游的 `_is_trivial_verdict`、收工门 notes、页面都读它），
   要动得单独一次、带理由，不在这一条里偷偷改。
"""
from __future__ import annotations

from agentflow import agent_skills as AS
from agentflow import secretary as SEC


def _body() -> str:
    for _role, items in AS.CATALOG.items():
        for item in items:
            got = item if isinstance(item, dict) else getattr(item, "__dict__", {})
            if str(got.get("slug")) == "审美-太平凡的不收":
                return str(got.get("body") or "")
    raise AssertionError("技能表里没有 B 的审美技能 ⇒ 判据失去对象")


def test_the_skill_shows_the_arithmetic():
    """正题：公式与档位边界在技能正文里（可离线复算）。"""
    body = _body()
    assert "// 2000" in body or "//2000" in body, body[:600]
    assert "T0" in body and "0-1 分" in body, body[:600]


def test_the_skill_says_it_is_not_a_judgement_of_the_mathematics():
    """正题：说清"太平凡"只等于"力气读数落 0-1 分"，不评数学价值。"""
    body = _body()
    assert "不是在评数学价值" in body, body[:600]
    # 真机那五条要写进正文（读的人一眼看出这是台阶，不是个案）
    assert "1425" in body and "1692" in body, body[:800]


def test_the_verdict_vocabulary_is_unchanged():
    """反真空：词表没有被我偷偷改（改词是一次受控词表变更，要单独做）。"""
    assert SEC.STATEMENT_VERDICTS == ("合格", "太平凡", "判不了"), SEC.STATEMENT_VERDICTS
    assert SEC.EFFORT_TIER_BANDS[0] == (0, 1, "T0"), SEC.EFFORT_TIER_BANDS
