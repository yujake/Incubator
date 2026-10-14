# -*- coding: utf-8 -*-
"""skills 三条硬约束的判据（业主 2026-10-14）。

业主原话：「将面对不同类型任务应唤起的协作方式写成各智能体的 skills，以防止前置大量
提示词，**现做现读**……至少为每种智能体特地去找至少 5 个 skill 来综合考量……
定制 skill 时需保证**描述无歧义、准确适配角色、动作都可实现**……
**不能虚构我们系统不存在的动作**」。

## 这一组守四件事

1. **不虚构**：每条 skill 用到的 `角色.动作` 必须在 `capabilities` 里存在，
   且从"拥有这条 skill 的角色"出发**够得到**（自己的动作，或它出边上的角色能做）；
   用到的工具必须在工具面上（`agent_skills.validate()` 逐条查）。
2. **描述无歧义**：`summary` / `when` / `body` 三格都不许空；索引里必须有
   "什么时候读它"这一格（没有它，索引就退化成又一份长文档）。
3. **现做现读**：前置提示词里**只有索引**——正文一个字都不许出现在提示词里
   （这条是本组的反负控：把某条 skill 的正文塞进 `CATALOG` 的 `summary`，
   它必须当场红）。
4. **调研过**：`SURVEY` 每格 ≥5 条、名字都在来源清单（38 个）里 ——
   "每种智能体至少找 5 个来综合考量"这句话唯一能被机器核的形态。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_skills as AS
from agentflow import agent_prompts as AP
from agentflow.tools import build_registry


def test_every_action_and_tool_in_the_catalog_really_exists():
    """正控：整本目录逐条过 `validate()` —— 动作存在、可达，工具在面上。"""
    problems = AS.validate()
    assert problems == [], "skills 里出现了做不到的指令：\n  - " + "\n  - ".join(problems)


def test_the_negative_control_catches_a_fabricated_action(monkeypatch):
    """反负控：塞一条**不存在的动作**进去 ⇒ 判据必须当场红。

    没有这一条，上面那条"全绿"说明不了任何事（它可能只是没查）。
    """
    bad = AS.Skill(slug="假的", title="假的", summary="一句话", when="任何时候",
                   body="正文", actions=("Z.fly_to_moon",))
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("Z.fly_to_moon" in p for p in problems), problems


def test_the_negative_control_catches_an_unreachable_action(monkeypatch):
    """反负控之二：动作**真实存在**但那个角色不在本角色的出边里 ⇒ 也必须红。

    这一条挡的是"把别人的活写进我的操作手册"：M 派不动 F/V 的动作（那两条边不存在），
    写进 M 的 skill 就是一句做不到的指令。
    """
    bad = AS.Skill(slug="越权", title="越权", summary="一句话", when="任何时候",
                   body="正文", actions=("F.step",))
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("F.step" in p and "出边" in p for p in problems), problems


def test_the_index_lists_every_skill_with_a_when_and_no_body():
    """索引：每条 skill 一行（路径 + 一句话 + 什么时候读它），且**不含正文**。"""
    for role in ("M", "B", "V"):
        block = AS.index_block(role)
        assert block, role
        for s in AS.skills_for(role):
            assert s.slug in block, (role, s.slug)
            assert s.when in block, (role, s.slug)
        # 反真空：索引里不许出现正文的第一句（那就是"前置全塞"又回来了）
        for s in AS.skills_for(role):
            first = next((ln.strip() for ln in s.body.splitlines()
                          if ln.strip() and not ln.strip().startswith("#")), "")
            if first:
                assert first not in block, (role, s.slug, first)


def test_the_prompt_carries_the_index_and_not_the_manual():
    """端到端：提示词里有索引那一段，而 skill 正文一个字都不在提示词里。"""
    reg = build_registry().registry
    text = AP.system_prompt("M", registry=reg)
    assert "你这一岗的 skills" in text, "提示词里没有 skills 索引那一段"
    for s in AS.skills_for("M"):
        assert s.slug in text, s.slug
        for line in s.body.splitlines():
            line = line.strip()
            if len(line) > 30 and not line.startswith("#"):
                assert line not in text, f"{s.slug} 的正文被塞进了前置提示词：{line[:40]}"


def test_the_skills_land_on_disk_so_they_can_be_read_on_demand(tmp_path):
    """`materialize` 真的把正文写到工作区里（角色才读得到），且幂等。"""
    written = AS.materialize(tmp_path)
    assert written, "一份都没写"
    for s in AS.skills_for("M"):
        owner = AS.SHARED if s in AS.CATALOG.get(AS.SHARED, ()) else "M"
        path = tmp_path / AS.SKILLS_DIR / owner / f"{s.slug}.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert s.title in text and s.body.strip()[:40] in text, path
    assert AS.materialize(tmp_path) == [], "第二次跑还是重写了一遍（不幂等）"


def test_every_role_has_at_least_five_builtin_skills_surveyed():
    """业主那句"每种智能体至少找 5 个 skill 来综合考量"的机器形态。"""
    names = set(AS.builtin_sources())
    assert len(names) == 38, f"来源清单应当是那 38 个：{len(names)}"
    assert set(AS.SURVEY) >= {"shared", "M", "A", "B", "C", "D", "E", "F", "G", "H", "V"}, \
        sorted(AS.SURVEY)
    for role, rows in AS.SURVEY.items():
        assert len(rows) >= 5, (role, rows)
        assert len(set(rows)) == len(rows), (role, rows)
        unknown = [r for r in rows if r not in names]
        assert not unknown, f"{role} 的调研记录里有来源目录里不存在的名字：{unknown}"


def test_the_negative_control_catches_an_empty_when(monkeypatch):
    """反负控之三：`when` 空 ⇒ 红（描述无歧义那一条的最低门槛）。"""
    bad = AS.Skill(slug="没时候", title="没时候", summary="一句话", when="",
                   body="正文")
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("when" in p for p in problems), problems
