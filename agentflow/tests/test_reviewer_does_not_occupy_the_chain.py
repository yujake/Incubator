# -*- coding: utf-8 -*-
"""审稿人不占链（业主 2026-11-02 裁定，取"乙"）。

## 业主口径

    「F不是直接能派V吗」 + V 是审稿人不是下级

⇒ V 不该吃被审者那条链的最后一层。83 的真机现场（`projects/paper-rewrite-83`）：
`t-000252` 是 F 在 depth 4 上派 V，被 `depth_exceeded` 拒（逐字「已经到第 5 个代理」），
于是「证明要拿 V 签」这条硬要求在深链上变成不可能 —— 而签是业主定的交差条件。

## 2026-11-05 之后这一条还管不管用？（管，但换了个位置）

业主当天把深度锁从 4 抬到 6（逐字：「将深度锁调到6，不然 M->D->F->A->B->V 是做不到的
（F派A补文献，A派B录入，B派V拿V签）」）⇒ `M→D→F→A→B→V` 里 V 落在台账 depth 5，
深度本身就放行它。所以那条链不靠本文件的豁免：它的判据
（`tests/test_depth_lock_is_six_and_fanout_is_not_depth.py` 的判据 1）同时断言
"摘掉豁免也放行"。本文件的豁免从此只管"比 7 个代理更深的链"。

它免的仍然只是"把审稿人算进被审者那条链"这一步 —— 管的是目标，不管召唤方。
所以本文件的 depth 一律读"深度上限再深一跳"（`_over_the_limit()` 现算，不写死 5 或 7）。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| ① | F 在"深度上限再深一跳"上派 V（本次 depth = `max_chain_depth + 1`） | 放行（不再 `depth_exceeded`） |
| ② | 同一 depth 上派 E（非审稿人） | 仍按旧口径拒（`depth_exceeded`） |
| ③ | 反真空：把豁免摘掉（`Policy(reviewer_roles=frozenset())`） | V 也必须回到 `depth_exceeded` |
| ④ | 边界：同一次召唤方、同一条 depth 上，目标换成非审稿人 | 拒（豁免只免目标）；V 作为召唤方照旧被拒 |

判据落在 `policy.check` 的第 [3] 步；豁免集合的唯一来源是
`Policy.reviewer_roles`（不散在判据里，也不在测试里另抄一份角色名单）。
"""
from __future__ import annotations

from agentflow import policy as P
from agentflow import schema as S


def _over_the_limit() -> int:
    """「深度上限再深一跳」的台账跳数（现算：不写死 5，也不写死 7）。"""
    return P.Policy().max_chain_depth + 1


def _decision(to: str, *, depth: int | None = None, frm: str = "F") -> P.Decision:
    return P.Decision(frm=frm, to=to, role=to, action="",
                      depth=_over_the_limit() if depth is None else depth,
                      direct_children=0, key=None, ancestry=())


# ============================================================ ① 放行
def test_a_a_reviewer_at_the_depth_limit_is_allowed():
    """① F 在"深度上限再深一跳"上派 V ⇒ 放行（审稿人不占链）。"""
    assert "V" in {str(r) for r in P.Policy().reviewer_roles}, (
        "豁免集合里没有 V ⇒ 这一组判据没有对象")
    deeper = _decision("V")
    assert deeper.depth > P.Policy().max_chain_depth, (
        f"这一条必须站在上限之外（depth={deeper.depth}，"
        f"max_chain_depth={P.Policy().max_chain_depth}）—— 否则它量的不是豁免，是深度")
    assert P.check(P.Policy(), deeper) is None


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


# ============================================================ ④ 边界
def test_d_the_exemption_covers_the_target_not_the_summoner():
    """④ 边界：豁免只免"目标"这一步；同一次召唤方、同一条 depth 上换成非审稿人照拒。

    为什么这样写（2026-11-05 之后）：旧版拿 `V → F`（V 作为召唤方）当"照旧按同一张表判"
    的例子，而业主当天裁掉了 V 的全部出边（「V 不应该有出边」）⇒ 那条边今天连边闸都
    过不去（`forbidden_edge`），拿它举例会把"边不是深度"误读成"深度没放开"。
    改成同一次召唤方（B）、同一条 depth 的双目标对照：这一条不依赖 V 的出边，
    而且比旧版更强 —— 它证明的是"豁免认的是目标角色，不是这条召唤的深度"。
    """
    policy = P.Policy()
    # 同一个召唤方 B、同一条 depth：目标 V（审稿人）放行
    assert P.check(policy, _decision("V", frm="B")) is None
    # 目标 D（非审稿人，且 `B → D` 是允许的边）：同一格 depth 上照拒，拒因是深度而不是边
    refusal = P.check(policy, _decision("D", frm="B"))
    assert refusal is not None and refusal.reason == "depth_exceeded", refusal
    # V 作为召唤方不在豁免里：它必须被拒（今天没有出边 ⇒ 边闸先拒；哪天出边回来
    # ⇒ 深度闸拒）。两种拒都说明"豁免只管目标，不管召唤方"。
    as_summoner = P.check(policy, _decision("F", frm="V"))
    assert as_summoner is not None, "V 作为召唤方被放行了 ⇒ 豁免被读成了「审稿人整条链都不占」"
    assert as_summoner.reason in ("forbidden_edge", "depth_exceeded"), as_summoner
    # 对外口径不改：理由码仍是 schema 里登记的那一个
    assert "depth_exceeded" in S.REFUSAL_REASONS
