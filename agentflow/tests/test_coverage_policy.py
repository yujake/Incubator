"""`policy.check_action` 的判据测试（等级 2：角色/动作存在性的判定）。

## 为什么这条判据值得单独补

`policy.check_action` 是唯一的角色/动作存在性判据，而 `check` / `check_edge`
都先调它。它的 docstring 逐字给出本文件的核心判据：

> 两种失败必须分开：`unknown_role`（名单里没这个人）与
> `unknown_action`（人存在，但没这个本事）。合并成一句"不支持"会让
> "我把角色名拼错了"与"我调了一个该角色真的没有的动作"无法区分。

所以断言必须打在 `Refusal.reason` 上（`unknown_role` vs `unknown_action`；
受控词表见 `schema.REFUSAL_REASONS`），而不是"返回了非 None"。
`Refusal` 的字段是 `reason` / `detail` / `limit` —— 第二、三个字段分别给出
人话细节与"是哪一类上限判的"，所以断言也顺便核了 `limit`。

## 夹具不写死名单（§5.3）

角色从 `schema.ROLES` 取，动作从 `capabilities.actions_for(role)` 取 ——
不在这里另写一份"谁有什么动作"的表（那正是本模块要避免的第二份判据）。
"""

from __future__ import annotations

import pytest

from agentflow import capabilities as C
from agentflow import policy as P
from agentflow import schema as S


def _a_role_with_an_action() -> tuple[str, str]:
    """找一个"既有角色身份、又至少有一个动作"的 (role, action)。

    从 `capabilities` 反查，不写死。找不到就是本文件的前提崩了，应当红。
    """
    for role in S.ROLES:
        acts = [a.action for a in C.actions_for(role)]
        if acts:
            return role, acts[0]
    pytest.fail("schema.ROLES 里没有任何角色带动作 ⇒ 本文件的判据失去对象")


# ============================================================ 正向


def test_check_action_accepts_a_real_role_and_its_own_action():
    """正向：真实角色 + 它自己声明的动作 ⇒ 放行（`None`）。

    为什么必须有：一个"永远返回 Refusal"的实现能通过全部负控 ——
    正向断言是它的反面（§5.1）。
    """
    role, action = _a_role_with_an_action()
    assert P.check_action(role, action) is None


def test_check_action_accepts_every_declared_action_of_every_role():
    """正向（全量）：`capabilities` 声明的每一个 (角色, 动作) 都必须放行。

    为什么全量：单点正向只能证明"那一个动作没被误拦"。存在性判据的价值在于
    不许漏放，而漏放的形态是"某个角色的某个动作突然调不动了" ——
    那只有全量断言才抓得到。
    """
    bad: list[str] = []
    for role in S.ROLES:
        for spec in C.actions_for(role):
            r = P.check_action(role, spec.action)
            if r is not None:
                bad.append(f"{role}/{spec.action} 被拒：{r.code}")
    assert bad == [], bad


def test_check_action_accepts_the_conductor_role_presence_but_never_an_action():
    """正向 + 负控（同一个角色的两半）：主控 `M` 被承认存在，但没有动作。

    `check_action` 对 `M` 走一条独立分支（`role == S.CONDUCTOR_ROLE`）。
    它必须报 `unknown_action` 而不是 `unknown_role` ——
    把 `M` 报成"名单里没这个人"会让日志说"角色不存在"，而它明明是主控。
    """
    ref = P.check_action(S.CONDUCTOR_ROLE, "summon")
    assert ref is not None, "主控不该被当成一个能 summon 的普通角色"
    assert ref.reason == "unknown_action", ref
    assert ref.limit == "action", ref


# ============================================================ 负控


def test_check_action_rejects_unknown_role_with_its_own_code():
    """负控：不存在的角色 ⇒ `unknown_role`，且 reason 里带上合法名单。

    断言 reason 里要有名单：这句 reason 的唯一用途就是让人发现"我把角色名拼错了"，
    所以它必须给出正确的取值集合。只断言 code 会放过一个只说"不支持"的实现。
    """
    bogus = S.ROLES[0] + "-NOT-A-ROLE"
    ref = P.check_action(bogus, "run")
    assert ref is not None and ref.reason == "unknown_role", ref
    assert ref.limit == "role", ref
    assert bogus in ref.detail, ref.detail
    assert all(r in ref.detail for r in S.ROLES), f"detail 没给出全部合法角色：{ref.detail}"


def test_check_action_rejects_unknown_action_for_a_real_role_with_its_own_code():
    """负控（本文件的核心）：真实角色 + 它没有的动作 ⇒ `unknown_action`。

    这条断言就是 docstring 说的"两种失败必须分开"的钉子：
    它与上一条的输入只差"角色是否真实"，而 `code` 必须不同。
    把两条合成一条"返回了 Refusal"的断言，会让"合并成一句不支持"的实现通过。
    """
    role, own = _a_role_with_an_action()
    bogus = own + "-NOT-AN-ACTION"
    ref = P.check_action(role, bogus)
    assert ref is not None and ref.reason == "unknown_action", ref
    assert ref.limit == "action", ref
    assert role in ref.detail and bogus in ref.detail, ref.detail
    # 反向负控：换个真实角色，它自己的动作不许被判成 unknown_action。
    other = P.check_action(role, own)
    assert other is None, other


def test_check_action_unknown_role_takes_precedence_over_unknown_action():
    """负控（判定顺序）：角色与动作都不存在时，报的是 `unknown_role`。

    为什么顺序是判据的一部分（`check_edge` 的 docstring 逐字："一个不存在的角色
    谈不上'边'"）：若先报 `unknown_action`，调用方会去查"这个人为什么没这个动作"，
    而真正的问题是"根本没有这个人"。
    """
    bogus_role = S.ROLES[0] + "-X"
    ref = P.check_action(bogus_role, "whatever-action")
    assert ref is not None and ref.reason == "unknown_role", ref


def test_check_action_does_not_consult_other_roles_actions():
    """负控（防越权误放）：角色 A 的某个动作，别的角色若未声明就必须被拒。

    这是"矩阵错则『不该能调的工具』变成『能调』"（`AGENTS.md` 的 auth-audit 一类）
    在纯函数层的钉子。做法：从 `capabilities` 里找一对"X 有动作 a、Y 没有动作 a"
    的真实组合，断言 Y/a 被拒 —— 不写死角色名与动作名。
    """
    pairs: list[tuple[str, str, str]] = []
    for r1 in S.ROLES:
        for spec in C.actions_for(r1):
            for r2 in S.ROLES:
                if r2 == r1 or r2 == S.CONDUCTOR_ROLE:
                    continue
                if C.find_action(r2, spec.action) is None:
                    pairs.append((r2, spec.action, r1))
    if not pairs:
        pytest.skip("所有角色的动作集合都相同 ⇒ 没有可构造的跨角色反例")
    for role, action, owner in pairs[:5]:
        ref = P.check_action(role, action)
        assert ref is not None and ref.reason == "unknown_action", (role, action, owner, ref)
