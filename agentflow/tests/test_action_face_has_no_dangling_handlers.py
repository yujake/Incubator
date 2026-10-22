"""动作面复核（能力面第二片）：62 个动作，62 个实现落点，零悬空。

## 这一条守的是什么

业主的经验文档要求定期复核"动作面多余项"。2026-10-22 现读 `specs.builtin_specs()`：动作总数 62（每角色 A 6 / B 7 / C 10 / D 15 / E 5 / F 4 /
G 7 / H 5 / V 3 / M 0），悬空动作（`handler_name` 在实现类上不存在）0 个。

`M` 的 0 个不是缺陷：主控的工具面是 `conductor.*`（编排面），召唤别的角色靠 `conductor.summon`，不需要自己声明"动作"——这条判据把"M 没有动作"与"某人漏了实现"分开。

## 判据（含负控）

① 每个动作都在实现类上有落点（`handler_name` 的最后一段能在 `spec.cls()` 上 `hasattr`）——"声明了却没人实现"的机器读数；
② 每个动作的 `summary` 非空（提示词里那一行就靠它，空 summary 会让模型看到一行光头）；
③ `M` 的动作面必须是 0（编排面不许混进研究侧动作；反过来，若哪天给 M 加了动作，这条会提醒先想清楚）；
④ 负控：给某个角色临时塞一个 `handler_name="…nonexistent"` 的动作 ⇒ ① 必须红；
⑤ 反真空：其余九个角色的动作面都非空，且总数 = 62。"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from agentflow import specs
from agentflow import agentspec as AS

ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")
EXPECTED_TOTAL = 62


def _rows() -> dict[str, Any]:
    return dict(specs.builtin_specs())


def _dangling(built: dict[str, Any]) -> list[str]:
    """判据本体：返回"声明了但实现类上没有落点"的动作（空 = 绿）。"""
    out: list[str] = []
    for role, spec in built.items():
        cls = spec.cls()
        for act in (getattr(spec, "actions", ()) or ()):
            handler = str(getattr(act, "handler_name", "") or "")
            method = handler.split(".")[-1] if handler else ""
            name = str(getattr(act, "action", "") or "")
            if not method:
                out.append(f"{role}.{name}：没有 handler_name")
            elif not hasattr(cls, method):
                out.append(f"{role}.{name}：handler `{handler}` 在 {type(cls).__name__} 上不存在")
    return out


def test_every_declared_action_has_an_implementation() -> None:
    """① 声明与实现对齐：62 个动作一个悬空的都不许有。"""
    problems = _dangling(_rows())
    assert not problems, "；".join(problems)


def test_every_action_carries_a_summary() -> None:
    """② 每个动作都要有一句 summary（提示词里那一行靠它）。"""
    bald = [f"{role}.{getattr(a, 'action', '')}"
            for role, spec in _rows().items()
            for a in (getattr(spec, "actions", ()) or ())
            if not str(getattr(a, "summary", "") or "").strip()]
    assert not bald, f"这些动作没有 summary：{bald}"


def test_the_conductor_declares_no_actions_of_its_own() -> None:
    """③ M 的动作面必须是 0：它的活在 `conductor.*` 编排面上。"""
    built = _rows()
    assert not list(getattr(built["M"], "actions", ()) or ()), (
        "M 现在有动作了 —— 若这是有意的，请先想清楚「编排面 vs 研究侧」的界线，再更新这条判据")


def test_the_negative_control_a_dangling_handler_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """④ 负控：临时给 A 塞一个指向不存在方法的动作 ⇒ ① 必须红。

        负控打 `SPEC`（不是模块级 `ACTIONS`）：`builtin_specs()` 每次现取 `mod.SPEC`，
        只改 `ACTIONS` 的负控会假绿。"""
    mod = __import__("agentflow.specs.a", fromlist=["SPEC"])
    spec = mod.SPEC
    ghost = AS.ActionSpec(
        role="A", action="ghost_action", summary="（负控：实现不存在）",
        params={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        returns="ARunResult", handler_name="A.definitely_not_implemented",
    )
    monkeypatch.setattr(mod, "SPEC", dataclasses.replace(spec, actions=tuple(spec.actions) + (ghost,)),
                        raising=True)
    problems = _dangling(_rows())
    assert problems, "负控失败：塞了一个没有实现的动作，判据仍然绿 ⇒ 它读的不是真身"
    assert "ghost_action" in " ".join(problems)


def test_no_role_face_is_empty_and_the_total_is_62() -> None:
    """⑤ 反真空：除 M 之外的九个角色都有动作，总数 62。"""
    built = _rows()
    empty = [r for r in ROLES if r != "M" and not list(getattr(built[r], "actions", ()) or ())]
    assert not empty, f"这些角色的动作面是空的：{empty}"
    total = sum(len(list(getattr(built[r], "actions", ()) or ())) for r in ROLES)
    assert total == EXPECTED_TOTAL, f"动作总数 {total} != {EXPECTED_TOTAL}"
