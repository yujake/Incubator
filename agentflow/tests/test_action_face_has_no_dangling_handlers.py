"""动作面复核（能力面第二片）：每个声明过的动作都有实现落点，零悬空。

## 这一条守的是什么

业主的经验文档要求定期复核"动作面多余项"。动作面的权威读数是 F15 那份冻结基线
（`tests/golden/agent_surface_snapshot.json`，改它要人审）：本文件与它现读对拍，不手抄总数。

那个总数曾经手抄在这里（"总数 = 62"），而它是一种会腐烂的字面量：2026-10-23 晚的裁定
逐字是「E 侧与 Lean 相关的工具和动作都该清干净」，`specs/e.py` 顶部记着 `check_formal`
整条动作被摘掉，于是总数 62 → 61，判据在代码完全正确的情况下红着 —— 而没有人回来管它。
数字是从这张表读出来的读数，不是规格；规格在冻结基线里。

`M` 的 0 个不是缺陷：主控的工具面是 `conductor.*`（编排面），召唤别的角色靠 `conductor.summon`，不需要自己声明"动作"——这条判据把"M 没有动作"与"某人漏了实现"分开。

## 判据（含负控）

① 每个动作都在实现类上有落点（`handler_name` 的最后一段能在 `spec.cls()` 上 `hasattr`）——"声明了却没人实现"的机器读数；
② 每个动作的 `summary` 非空（提示词里那一行就靠它，空 summary 会让模型看到一行光头）；
③ `M` 的动作面必须是 0（编排面不许混进研究侧动作；反过来，若哪天给 M 加了动作，这条会提醒先想清楚）；
④ 负控：给某个角色临时塞一个 `handler_name="…nonexistent"` 的动作 ⇒ ① 必须红；
⑤ 反真空：其余九个角色的动作面都非空，且每个面与冻结基线逐条一致（不是手抄一个总数）。"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

import pytest

from agentflow import specs
from agentflow import agentspec as AS

ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")

#: 动作面的权威基线（F15 入册）：`tests/golden/agent_surface_snapshot.json`。
#:
#: 为什么判据读它而不是手抄一个总数：那个数（曾经是 62）是这张表的读数，而它会腐烂 ——
#: 2026-10-23 晚摘掉 E 的 `check_formal` 之后它变成 61，判据就红着了，而代码完全正确。
#: 要加减一个动作，该动的是这份基线（人审面），不是这条判据里的字面量。
SNAPSHOT = pathlib.Path(__file__).resolve().parent / "golden" / "agent_surface_snapshot.json"

#: 动作面的下界（防真空）：低于它说明扫描面根本没读到东西，"零悬空"只是"什么都没扫到"。
ACTION_FLOOR = 40


def _rows() -> dict[str, Any]:
    return dict(specs.builtin_specs())


def _frozen_faces() -> dict[str, list[str]]:
    """基线里每个角色的动作名（快照那一列是按名排序的 dict，这里只取 `action` 那格）。"""
    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for role, row in (doc.get("roles") or {}).items():
        names: list[str] = []
        for item in (row.get("actions") or ()):
            names.append(str(item.get("action") if isinstance(item, dict) else item))
        out[str(role)] = names
    return out


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
    """① 声明与实现对齐：一个悬空的都不许有。"""
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


def _baseline_drift() -> tuple[list[str], dict[str, list[str]]]:
    """现读 vs 冻结基线（⑤ 的判据本体）：返回（漂移行, 逐角色现读的动作名）。

    单独抽出来是因为⑤的负控要复用它：负控摘掉一条动作之后，同一个读法必须点出那一格。
    """
    built = _rows()
    frozen = _frozen_faces()
    live = {r: sorted(str(a.action) for a in (getattr(built[r], "actions", ()) or ()))
            for r in ROLES}
    drift = [f"{role}：现读 {live[role]} vs 基线 {sorted(frozen.get(role) or ())}"
             for role in ROLES if live[role] != sorted(frozen.get(role) or ())]
    return drift, live


def test_no_role_face_is_empty_and_every_face_matches_the_frozen_baseline() -> None:
    """⑤ 反真空：除 M 之外的九个角色都有动作；且每个动作面与 F15 基线逐条一致。

    为什么不再写"总数 = 62"：那个数字是从这张表读出来的读数，不是规格 —— 2026-10-23 晚
    把 E 的 `check_formal` 整条动作摘掉之后它变成 61，于是判据在代码完全正确时红着。
    精确面本来就有一份人审的落点（`tests/golden/agent_surface_snapshot.json`，F15），
    这里与它现读对拍：加/减动作要动的是那份基线，而不是这条判据里的一个字面量。
    """
    built = _rows()
    empty = [r for r in ROLES if r != "M" and not list(getattr(built[r], "actions", ()) or ())]
    assert not empty, f"这些角色的动作面是空的：{empty}"

    frozen = _frozen_faces()
    assert frozen.get("E"), (
        "基线里读不到 E 的动作面 ⇒ 对拍那一格没接上（不是'动作面没问题'）")
    drift, live = _baseline_drift()
    assert not drift, (
        "动作面与 F15 冻结基线不符（这一改动了动作面 ⇒ 该重冻基线并由人逐格看过）：\n"
        + "\n".join(drift))

    # 名录之外还有谁声明了动作？今天只有 L（形式化三件）。ROLES 不含 L 是刻意的
    # （这一面问的是 A–H + V + M），但"漏了谁"必须被读出来，而不是靠人记得。
    outside = sorted(r for r in built
                     if r not in ROLES and list(getattr(built[r], "actions", ()) or ()))
    assert outside == ["L"], (
        f"名录之外另有角色声明了动作：{outside} ⇒ 若这是新角色，先想清楚 ROLES 要不要收它")

    total = sum(len(v) for v in live.values())
    assert total >= ACTION_FLOOR, (
        f"动作面只读到 {total} 个（下界 {ACTION_FLOOR}）⇒ 扫描面没接上，"
        f"'零悬空'可能只是'什么都没扫到'；逐角色读数：{live}")


def test_the_negative_control_a_dropped_action_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⑤ 负控：从 E 的 `SPEC` 里摘掉一条动作 ⇒ 与基线的对拍必须当场点出 E 那一格。

    没有这一条，"与基线一致"可能只是"两边读的是同一份东西"：摘掉动作之后现读少一条，
    基线没动，判据必须红在"这一改动了动作面"上。
    """
    mod = __import__("agentflow.specs.e", fromlist=["SPEC"])
    spec = mod.SPEC
    kept = tuple(a for a in spec.actions if str(a.action) != "list_experiments")
    assert kept and len(kept) == len(spec.actions) - 1, (
        "夹具写错了：E 的动作面里没有 list_experiments 这一条可摘")
    monkeypatch.setattr(mod, "SPEC", dataclasses.replace(spec, actions=kept), raising=True)
    drift, _live = _baseline_drift()
    assert any(line.startswith("E：") for line in drift), (
        f"从 E 的动作面里摘掉一条，基线对拍却没点出 E：{drift}")
    assert "list_experiments" in " ".join(drift), drift
