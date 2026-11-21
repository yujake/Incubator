# -*- coding: utf-8 -*-
"""判据（ASEARCH，2026-11-21）：A 的检索纪律与收尾义务必须长在它自己读得到的地方。

## 改前为什么红（真机 `projects/lp-ball-14` 坐实）

- 14 条 `search_requests` 里 13 条 `no_results`；`no_result_topics` 8 条全是题面式说法
  （`Ball cube slicing` / `Meyer Pajor sections` / `Koenig Koldobsky sections of the cube` /
  `Koldobsky Fourier transform sections` / `central hyperplane sections of the l_p ball` /
  `Brunn concavity sections centrally symmetric body` / `sectional isoperimetric inequality` /
  `Fourier transform sections of the cube`）。收工门 R2 的原话：「一条 `no_results` 是合法
  终局，但按纪律它要用规范术语再查一次（题面式说法查不到不等于这个方向没有文献）」——
  而 A 的职责面（`specs/a.py` 的 policy）一个字都没写这件事，手册正文里也只有五条代换里的一条。
- 4 个委托共 24 条候选留成 `pending`（`r-000011` 15 / `r-000012` 2 / `r-000013` 4 /
  `r-000014` 3）：没有逐条 `lit.admit` / `lit.stage_reject`，也没有逐委托
  `lit.admit_all` 提交清表，而交给召唤方的回执里没写还剩几条。

## 判据（断言渲染产物，不数词频）

| # | 判据 | 反真空 |
|---|---|---|
| a | A 的 `system_prompt` 里有两条纪律原话 + 收尾三步 | 从 `ROLE_BRIEFS["A"]` 拿掉那两条 ⇒ a 必红 |
| b | A 的手册（`skills/A/…md` 渲染文本）里同样有这两条纪律与收尾三步 | 把手册正文/summary 换成探针 ⇒ b 必红 |
| c | A 的 SKILLS_INDEX 那一行（前置提示词里唯一的手册入口）也点名这两条 | 把 summary/when 清空 ⇒ c 必红 |

反真空打在判据函数上（`_missing_query` / `_missing_closing` 逐条点名缺哪一句），不是只断言
"某段文字比另一段长"。
"""
from __future__ import annotations

import dataclasses

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow.tools import build_registry

#: 渲染提示词用的固定任务与工作区（与 `tests/test_agent_prompts.py` 同一组缺省值）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 纪律 ① 的两个锚（题面句不是查询词 / no_results 之后换什么）。
_QUERY_ANCHORS: tuple[str, ...] = (
    "题面式说法不是查询词",
    "换规范术语再查一次",
    "规范术语",
    "关键词组合",
)

#: 纪律 ② 的锚（逐条判收判拒 / 逐委托提交清表 / 回执报还剩几条）。
_CLOSING_ANCHORS: tuple[str, ...] = (
    "逐条",
    "判收",
    "判拒",
    "逐委托",
    "lit.admit_all",
    "pending_total",
    "还剩几条待裁",
)


def _a_prompt() -> str:
    """A 这一次真的会读到的 system prompt。"""
    return AP.system_prompt("A", registry=build_registry().registry,
                            task=TASK, workspace_root=ROOT)


def _a_skill() -> AS.Skill:
    """A 目录里那条检索方法手册（slug 是稳定标识，判据按它取）。"""
    for skill in AS.skills_for("A"):
        if skill.slug == "找文献-换招法而不是换说法":
            return skill
    raise AssertionError("A 的 skills 里没有 `找文献-换招法而不是换说法`（判据失去对象）")


def _a_manual() -> str:
    """A 用 `fs.read` 读到的那些字节（头部 summary/when + 正文）。"""
    return AS._render("A", _a_skill())


def _missing(text: str, anchors: tuple[str, ...]) -> list[str]:
    """哪些锚没出现在这段渲染产物里（空 = 两条纪律都长在这一面）。"""
    return [f"缺「{needle}」" for needle in anchors if needle not in text]


def _missing_query(text: str) -> list[str]:
    return [f"纪律①：{x}" for x in _missing(text, _QUERY_ANCHORS)]


def _missing_closing(text: str) -> list[str]:
    return [f"纪律②：{x}" for x in _missing(text, _CLOSING_ANCHORS)]


def _all_missing(text: str) -> list[str]:
    return _missing_query(text) + _missing_closing(text)


# ---------------------------------------------------------------- a 职责面


def test_a_prompt_carries_both_disciplines_and_the_closing_steps() -> None:
    """a. A 的 system prompt 里两条纪律与收尾三步逐条可读。"""
    prompt = _a_prompt()
    assert _all_missing(prompt) == [], (
        "A 的职责面里缺检索纪律/收尾义务 ⇒ 模型只按工具默认行为做："
        + "；".join(_all_missing(prompt)))


def test_a_anti_vacuum_removing_the_clauses_makes_the_prompt_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的反真空：把两句从声明里拿掉 ⇒ 同一个检查必须点名报缺。"""
    brief = AP.ROLE_BRIEFS["A"]
    assert _all_missing(_a_prompt()) == [], "夹具前提：改后这一面应当先绿"

    stripped = dataclasses.replace(
        brief,
        policy=tuple(x for x in brief.policy if "题面式说法不是查询词" not in str(x)),
        boundary=tuple(x for x in brief.boundary if "每一趟的收尾" not in str(x)),
    )
    assert stripped.policy != brief.policy and stripped.boundary != brief.boundary, (
        "夹具前提：那两条纪律确实长在 policy / boundary 上（否则这条负控在打空气）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "A", stripped)
    assert _missing_query(_a_prompt()) != [], "拿掉纪律①之后判据仍读得到它 —— a 是橡皮图章"
    assert _missing_closing(_a_prompt()) != [], "拿掉收尾义务之后判据仍读得到它 —— a 是橡皮图章"


# ---------------------------------------------------------------- b 手册正文


def test_a_manual_carries_both_disciplines_and_the_closing_steps() -> None:
    """b. A 现读的那份手册里两条纪律与收尾三步逐条可读（它真的会 `fs.read` 它）。"""
    manual = _a_manual()
    assert _all_missing(manual) == [], (
        "A 的手册里缺检索纪律/收尾义务 ⇒ 前置提示词说了、现读的手册没说，"
        "两处一漂模型只会照一处做：" + "；".join(_all_missing(manual)))


def test_b_anti_vacuum_removing_the_manual_body_makes_the_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """b 的反真空：把手册正文与 summary 换成探针 ⇒ 同一检查必须点名报缺。"""
    skills = AS.CATALOG["A"]
    victim = _a_skill()
    assert _all_missing(_a_manual()) == [], "夹具前提：改后这一面应当先绿"

    probe = dataclasses.replace(victim, body="（探针：正文被清空）",
                                summary="（探针：一句话被清空）",
                                when="（探针：什么时候读被清空）")
    monkeypatch.setitem(
        AS.CATALOG, "A",
        tuple(probe if s.slug == victim.slug else s for s in skills))
    assert _all_missing(_a_manual()) != [], "把手册正文换掉之后判据仍绿 —— b 是橡皮图章"


# ---------------------------------------------------------------- c 索引行


def test_c_the_index_row_also_names_both_disciplines() -> None:
    """c. 前置提示词里唯一的手册入口（SKILLS_INDEX 那一行）也点名这两条。"""
    index = AS.index_block("A")
    assert "题面式说法不是查询词" in index, (
        "索引里没有纪律① ⇒ 模型看不到「手册为什么值得现在读」")
    assert "换规范术语重查一次" in index, "索引里没有「no_results 之后换什么」"
    assert "逐委托" in index and "lit.admit_all" in index, (
        "索引里没有收尾义务 ⇒ 手册能被跳过，skip 掉之后模型不知道还要清表")


def test_c_anti_vacuum_the_index_negative_control_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的反真空：把那条 skill 的 summary/when 清空 ⇒ 索引判据必红。"""
    skills = AS.CATALOG["A"]
    victim = _a_skill()
    assert "题面式说法不是查询词" in AS.index_block("A")

    probe = dataclasses.replace(victim, summary="（探针）", when="（探针）")
    monkeypatch.setitem(
        AS.CATALOG, "A",
        tuple(probe if s.slug == victim.slug else s for s in skills))
    index = AS.index_block("A")
    assert "题面式说法不是查询词" not in index, "清空 summary 之后索引仍带着纪律① —— c 是橡皮图章"
    assert "lit.admit_all" not in index, "清空 summary 之后索引仍带着收尾义务 —— c 是橡皮图章"
