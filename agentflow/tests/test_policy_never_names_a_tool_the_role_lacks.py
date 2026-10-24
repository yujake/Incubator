# -*- coding: utf-8 -*-
"""判据：一个角色的 policy 里点名的 `组.动作` 必须真的在它自己的工具面上。

## 为什么要有这一条（根因）

旧护栏只逐条核四件（`trace.children` / `conductor.escalate` / `conductor.watch` /
`conductor.guide`，见 `tests/test_every_role_knows_it_can_watch_its_children.py` 判据 02）。
于是 policy 里别的工具名一路带着病：D 的 policy 教它 `conductor.summon`（那是 M 的
工具）、F 的 policy 教它 `verify.read_proof`（那是 V 的工具）、E 的 policy 教它
`verify.verify_proof`（同样是 V 的）。模型读到就照着调，框架只能回 `unknown_tool` /
越权拒绝 —— 一次真钱。

这一条把"四件"换成通用判据：从注册表现算全集，逐角色扫 policy 里的
`组.动作` 记号，凡是注册过的工具都必须在该角色的工具面上；不认识的 `组.动作` 记号
（拼错的工具名）同样算红。失败信息点名缺哪几件。

## 范围

扫 `schema.ROLES`（十个可召唤角色）。M 不在这一条里：它的 policy 刻意点名"派给谁、
让对方用哪件工具"（`doc.paper_compile` 等），那不是 M 自己要调的；M 自己的工具名
另由 `test_every_role_knows_it_can_watch_its_children.py` 判据 03 守着。

## 判据（正控 / 反真空 / 负控）

1. 逐角色：policy 里出现的注册工具名 ⊆ 这个角色的工具面（缺哪件点名）；
2. 逐角色：带工具组前缀、但不是注册工具的记号 ⇒ 也算红（拼错的名字同样是幻觉）；
3. 反真空：每个角色的 policy 至少点得出一个工具名（否则"没有缺件"是废话）；
4. 负控：往 D 的 policy 里塞 `conductor.summon` ⇒ 必红，且失败信息点名这一件。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.tools import build_registry

#: 本判据扫的角色（M 不在内，理由见模块 docstring）。
POLICY_ROLES: tuple[str, ...] = tuple(S.ROLES)

#: `组.动作` 的记号（与全仓工具命名同一形态：小写 snake，点分两段）。
_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)(?![A-Za-z0-9_])")


@pytest.fixture(scope="module")
def registry():
    return build_registry().registry


def _policy_text(role: str) -> str:
    return "\n".join(str(item) for item in AP.ROLE_BRIEFS[role].policy)


def _tokens(role: str) -> set[str]:
    return set(_TOKEN.findall(_policy_text(role)))


def _surface(registry, role: str) -> set[str]:
    return {str(spec.name) for spec in registry.for_role(role)}


def _missing(role: str, registry) -> list[str]:
    """这个角色的 policy 点名了、但它工具面上没有的工具（含拼错的记号）。"""
    tools = {str(name) for name in registry.names()}
    groups = {name.split(".")[0] for name in tools}
    surface = _surface(registry, role)
    out: list[str] = []
    for token in sorted(_tokens(role)):
        if token in tools:
            if token not in surface:
                out.append(f"{token}（它不在 {role} 的工具面上）")
        elif token.split(".")[0] in groups:
            out.append(f"{token}（这不是注册过的工具 —— 名字拼错了）")
    return out


# ============================================================ 1 通用判据（逐角色）
@pytest.mark.parametrize("role", POLICY_ROLES)
def test_01_every_tool_in_the_policy_is_on_that_roles_surface(role: str, registry) -> None:
    """01：policy 里每一个注册工具名都在这个角色的工具面上（缺哪几件点名）。"""
    problems = _missing(role, registry)
    assert problems == [], (
        f"{role} 的 policy 点名了 {len(problems)} 件它没有的工具：\n  - "
        + "\n  - ".join(problems))


# ============================================================ 2 反真空
@pytest.mark.parametrize("role", POLICY_ROLES)
def test_02_each_policy_names_at_least_one_real_tool(role: str, registry) -> None:
    """02（反真空）：policy 里至少读得到一个 `组.动作` 记号 —— 否则 01 是空集。"""
    tools = {str(name) for name in registry.names()}
    named = {t for t in _tokens(role) if t in tools}
    assert named, (
        f"{role} 的 policy 里一个工具名都扫不到 ⇒ 01 对这一格是橡皮图章"
        "（正则或 registry 有一处坏了）")


# ============================================================ 3 负控
def test_03_injecting_conductor_summon_into_d_turns_the_scan_red(
        registry, monkeypatch: pytest.MonkeyPatch) -> None:
    """03：往 D 的 policy 里塞 `conductor.summon` ⇒ 必红，且点名这一件。"""
    assert _missing("D", registry) == [], "夹具前提：D 的 policy 改前是干净的"

    brief = AP.ROLE_BRIEFS["D"]
    injected = dataclasses.replace(
        brief, policy=tuple(brief.policy) + ("下一步用 `conductor.summon` 派 B 入库。",))
    monkeypatch.setitem(AP.ROLE_BRIEFS, "D", injected)
    problems = _missing("D", registry)
    assert problems, "往 D 的 policy 里塞了 conductor.summon，判据却一声不吭"
    assert any("conductor.summon" in one for one in problems), problems


def test_04_a_misspelled_tool_name_is_also_red(registry, monkeypatch: pytest.MonkeyPatch) -> None:
    """04（负控之二）：带工具组前缀、但不是注册工具的名字同样必红（拼错也教不会）。"""
    brief = AP.ROLE_BRIEFS["E"]
    injected = dataclasses.replace(
        brief, policy=tuple(brief.policy) + ("跑之前先看 `verify.does_not_exist`。",))
    monkeypatch.setitem(AP.ROLE_BRIEFS, "E", injected)
    problems = _missing("E", registry)
    assert any("verify.does_not_exist" in one for one in problems), problems
