# -*- coding: utf-8 -*-
"""判据：放弃命题的四档在提示词里被教全了（业主 2026-11-07 第二刀）。

## 这条判据守的是什么

`statementabandon.ABANDON_KINDS` 上一笔已经从两档扩成四档（F 侧 `math_error` /
`difficulty`，E 侧 `counterexample` / `space_too_large`），判定口也已经是同一个
`check_abandon_reason`。但模型看得见的那一面当时还写着「两档之一」——
于是模型照提示词只学会两种理由，第三种（发现反例）与第四种（枚举空间过大）在
`abandon_kind` 的 enum 里可选、却没有任何一句教它该给什么证据。

这一条判据把它钉在「模型实际读到的那份 system prompt」上，而不是钉在源码注释里：
每一条档名与它要的那一格（`experiment_id` / `space`）都必须真的渲染进
「教放弃这件事的那几个角色」的提示词。

## 为什么按 `ABANDON_KINDS` 派生，而不是写死四个名字

写死一份清单，下一轮再加一档时这张表不会红 —— 测试会继续对着旧的四档亮绿。
派生之后，词表加一档 ⇒ 提示词没跟 ⇒ 这里必红（方向：实现 → 提示词）。
另一头（提示词 → 实现）由 `SA.ABANDON_KINDS` / `ABANDON_PARAM_KEYS` 那一份真身守着：
这里只教这些名字，不发明新名字。

## 判据

| # | 判据 | 用例 |
|---|---|---|
| a | 教放弃的那几个角色（B/D/F/M）的提示词里，四档与两格一个不少 | `test_a_*` |
| b | 反真空：从渲染好的提示词里删掉 `counterexample` ⇒ 同一判据必红 | `test_b_*` |
| c | E 手册写着数值证明路线写盘前会过同一个形态闸（判据 `proposition_form_refused`） | `test_c_*` |
"""
from __future__ import annotations

import pytest

from agentflow import statementabandon as SA
from agentflow.agent_prompts import system_prompt
from agentflow.store import Store
from agentflow.tools import ROLES, build_registry

#: 提示词里教「放弃理由该写什么」的那几个角色：D 是研究侧主导、F 是被打回后可能
#: 放弃的那一侧、M 决定「这条不做了」。B 是执行口 —— 它的那一份教法来自
#: `table.update` 的 summary（工具面），由工具声明那一侧的判据钉着
#: （`tests/test_tool_surface_snapshot.py` 与 `test_tool_descriptions_are_compressed`）。
TEACHING_ROLES: tuple[str, ...] = ("D", "F", "M")

#: E 侧那两档各自多要的那一格。名字取自 `ABANDON_PARAM_KEYS` 的真身，不另写一份。
E_SIDE_CELLS: tuple[str, ...] = ("experiment_id", "space")


@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    """一张带工作区的完整注册表（`table.update` 的 summary 才会渲染进提示词）。"""
    ws = tmp_path_factory.mktemp("abandon-four-tiers") / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws, roles=tuple(ROLES),
                          strict=True).registry


def missing_teachings(text: str) -> list[str]:
    """这一段提示词缺了哪几档 / 哪两格（空列表 = 四档两格都在）。"""
    gaps = [kind for kind in SA.ABANDON_KINDS if kind not in str(text or "")]
    gaps += [cell for cell in E_SIDE_CELLS if cell not in str(text or "")]
    return gaps


# ---------------------------------------------------------------- a 四档两格都在

def test_a_every_teaching_role_names_all_four_tiers_and_the_two_cells(registry) -> None:
    """a：B / D / F / M 的提示词里，`ABANDON_KINDS` 四档与 `experiment_id` / `space` 全在。"""
    # 反真空：词表本身不能是空的，否则「全在」在空集上成立。
    assert len(SA.ABANDON_KINDS) == 4, SA.ABANDON_KINDS
    for cell in E_SIDE_CELLS:
        assert cell in SA.ABANDON_PARAM_KEYS, (cell, SA.ABANDON_PARAM_KEYS)

    gaps = {role: missing_teachings(system_prompt(role, registry=registry))
            for role in TEACHING_ROLES}
    assert not any(gaps.values()), (
        "这些角色的提示词没把放弃理由的四档教全（词表里有一档、提示词里没有 ⇒ "
        "模型只学会它读过的那几档）：\n  "
        + "\n  - ".join(f"[{role}] 缺 {missing}" for role, missing in gaps.items() if missing))


# ---------------------------------------------------------------- b 反真空

def test_b_dropping_the_counterexample_tier_turns_the_criterion_red(registry) -> None:
    """b：把 `counterexample` 那一档从提示词里删掉 ⇒ 判据必红（不是「永远绿」）。"""
    text = system_prompt("M", registry=registry)
    assert missing_teachings(text) == [], "基线就不绿 ⇒ 下面的反真空没有意义"

    doctored = text.replace("counterexample", "")
    assert doctored != text, "提示词里根本没有 counterexample ⇒ 这一档本来就没被教"
    assert "counterexample" in missing_teachings(doctored), (
        "删掉 `counterexample` 之后判据仍然说「齐」⇒ 这条判据没在量这一档")


# ---------------------------------------------------------------- c E 手册同一道闸

def test_c_the_e_handbook_says_the_numeric_proof_route_passes_the_same_form_gate() -> None:
    """c：E 手册里，数值证明路线在写盘之前过同一个形态闸（条件 → 结论）。"""
    from agentflow.agent_skills import _e_skills

    bodies = {skill.slug: skill.body for skill in _e_skills()}
    body, _why = _the_numeric_proof_handbook(bodies)
    for needle in ("同一个", "形态闸", "proposition_form_refused", "条件", "结论"):
        assert needle in body, (
            f"E 的数值证明手册没写 {needle!r} ⇒ 模型不知道这条路写盘前也要过形态闸"
            "（业主 2026-11-07：「F侧的注册+放弃闸需同步到E侧的数值证明路线」）")


def _the_numeric_proof_handbook(bodies: dict[str, str]) -> tuple[str, str]:
    """取 E 的「穷举证明」那一本（它是数值证明路线的唯一手册）。"""
    for slug, body in bodies.items():
        if "穷举证明" in slug:
            return body, slug
    raise AssertionError(f"E 的手册里没有「穷举证明」那一本：{sorted(bodies)}")
