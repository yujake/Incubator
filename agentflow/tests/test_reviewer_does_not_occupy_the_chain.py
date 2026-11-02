# -*- coding: utf-8 -*-
"""审稿人不占链（业主 2026-11-02 裁定，取"乙"）。

## 业主口径

    「F不是直接能派V吗」 + V 是审稿人不是下级

⇒ V 不该吃 M→G→D→F 那条链的第 5 层。83 的真机现场（`projects/paper-rewrite-83`）：
`t-000252` 是 F 在 depth 4 上派 V，被 `depth_exceeded` 拒（逐字「已经到第 5 个代理」），
于是「证明要拿 V 签」这条硬要求在深链上变成不可能 —— 而签是业主定的交差条件。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| ① | F 在 depth 4 上派 V（本次 depth=5） | 放行（不再 `depth_exceeded`） |
| ② | 同一 depth 上派 E（非审稿人） | 仍按旧口径拒（`depth_exceeded`） |
| ③ | 反真空：把豁免摘掉（`Policy(reviewer_roles=frozenset())`） | V 也必须回到 `depth_exceeded` |

判据落在 `policy.check` 的第 [3] 步；豁免集合的唯一来源是
`Policy.reviewer_roles`（不散在判据里，也不在测试里另抄一份角色名单）。
"""
from __future__ import annotations

import pytest
from agentflow import policy as P
from agentflow import schema as S


def _decision(to: str, *, depth: int = 5, frm: str = "F") -> P.Decision:
    return P.Decision(frm=frm, to=to, role=to, action="", depth=depth,
                      direct_children=0, key=None, ancestry=())


# ============================================================ ① 放行
def test_a_a_reviewer_at_the_depth_limit_is_allowed():
    """① F 在 depth 4 上派 V ⇒ 放行（审稿人不占链）。"""
    assert "V" in {str(r) for r in P.Policy().reviewer_roles}, (
        "豁免集合里没有 V ⇒ 这一组判据没有对象")
    assert P.check(P.Policy(), _decision("V")) is None


# ============================================================ ② 非审稿人照旧
def test_b_a_worker_at_the_depth_limit_is_still_refused():
    """② 同一 depth 上派 E ⇒ 仍按旧口径拒（豁免只给审稿人）。"""
    refusal = P.check(P.Policy(), _decision("E"))
    assert refusal is not None, "派 E 也被放行了 ⇒ 豁免被放宽成了「谁都不占链」"
    assert refusal.reason == "depth_exceeded", refusal


# ============================================================ ③ 反真空
def test_c_removing_the_exemption_restores_the_refusal():
    """③ 反真空：把豁免摘掉 ⇒ V 必须回到 `depth_exceeded`。"""
    stripped = P.Policy(reviewer_roles=frozenset())
    refusal = P.check(stripped, _decision("V"))
    assert refusal is not None, "摘掉豁免之后 V 仍然放行 ⇒ 这条判据不是靠豁免在放行"
    assert refusal.reason == "depth_exceeded", refusal


# ============================================================ 深一层的边界
def test_d_the_boundary_is_documented_not_unbounded():
    """边界：豁免只免"目标"这一步；depth 再深一层仍然按同一张表判。"""
    policy = P.Policy()
    assert P.check(policy, _decision("V", depth=policy.max_chain_depth + 1)) is None
    # 但 V 自己的出边（V→F 退回）不在这条豁免里：F 不是审稿人 ⇒ 照旧按链长拒。
    deeper = P.Decision(frm="V", to="F", role="F", action="", depth=20,
                        direct_children=0, key=None, ancestry=())
    refusal = P.check(policy, deeper)
    assert refusal is not None and refusal.reason == "depth_exceeded", refusal
