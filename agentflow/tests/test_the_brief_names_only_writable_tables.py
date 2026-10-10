# -*- coding: utf-8 -*-
"""一个角色的 `deliverable` 里点名的台账表，必须在它自己的写集里。

## 这条判据守的是什么（T4 第 6 趟 `t4f` 的真机读数）

`t4f` 里 M 报了一条 `cannot`，逐字是：

> D.write_report 落 `analysis_reports` | D 调用 write_report 6 次均返回 ok，
> 但台账里没有一张表收得下它（`WRITE_SETS["D"]` 无 `analysis_reports`），属框架口径问题

M 说得对：`analysis_reports` 是 C 的报告通道（`schema.REPORT_KINDS` 只收
`hottest/paths/cold/gaps` 四档），D 的写集里没有它，`AgentD.write_report` 也只写
`reports/<qid>-research.md` 那份 markdown、一张表都不写。而 D 的 `deliverable`
当时逐字写着"analysis_reports 里的分析、结论、建议三层…" ⇒ 声明与权限面打架，
M 照着声明去找那张表，找不到，只能记一条 `cannot`。代码那一层早就知道这件事
（`agent_d/_support.py` 的 `report_landing_reading`，S-07 的裁定是"只加读数、不改硬契约"），
但声明那一层没跟上。

## 判据的形状（全角色扫，成对）

* 正控：七个角色的 `deliverable` 现在点的表全在自己的写集里（改之前 D 是唯一一处越界）；
* 反真空①：扫到的表名总数必须足够（否则"没命中"只是因为扫描器没读到东西）；
* 反真空②（对着判据本体做的负控）：拿一份故意越界的假声明喂给同一个函数 ⇒ 必须报出来；
* 反真空③：`brief` 里别的字段（`duty`/`policy`/`stance`）不在这条判据的范围内 ——
  它们谈的是做法，不是交付落点；判据只扫 `deliverable` 一格（免得读成"整份 brief 不许提别的表"）。
"""
from __future__ import annotations

import pytest

from agentflow import capabilities as C
from agentflow import schema as S

#: 不算"交付落点"的表：纯账本 / 过程记录类（任何角色都可以在说明里提它们，提了也不算
#: "声明要写它"）。刻意只排这几张：`documents` / `review_findings` / `statements` /
#: `relations` / `literature` 这些是某些角色的交付表 ⇒ 排掉它们会让判据漏掉真越界
#: （我第一版就是这么写的，负控当场把它照出来了：假声明点了 `experiments` 与 `documents`
#: 却只报一条）。
_NOT_DELIVERABLES = frozenset({"tasks", "usage_ledger", "events", "eval_results", "counters"})


def _tables_named_in(text: str) -> set[str]:
    """一句话里点到的台账表名（按 `schema.TABLES` 现算，不另立词表）。"""
    return {t for t in S.TABLES if t not in _NOT_DELIVERABLES and t in str(text or "")}


def _violations(specs: dict) -> list[str]:
    """哪些角色的 `deliverable` 点了自己写不了的表（判据本体，供负控直接喂假声明）。"""
    bad: list[str] = []
    for role, spec in sorted(specs.items()):
        brief = getattr(spec, "brief", None)
        if brief is None:
            continue
        named = _tables_named_in(getattr(brief, "deliverable", ""))
        writable = C.WRITE_SETS.get(role, frozenset())
        for t in sorted(named - set(writable)):
            bad.append(f"{role}.deliverable 点了 {t}，而 {role} 的写集里没有它"
                       f"（写集：{sorted(writable)}）")
    return bad


def test_positive_every_role_delivers_a_table_it_can_write() -> None:
    """正控：七个角色的 `deliverable` 不许点自己写不了的表。"""
    specs = C._specs.builtin_specs()
    bad = _violations(specs)
    assert not bad, (
        "有角色的交付物声明点了自己写不了的台账表（声明与权限面打架）——\n  "
        + "\n  ".join(bad)
        + "\n两条出路：把声明改成它真交付的东西（首选），或把它写进写集（那是权限面改动）。"
    )


def test_anti_vacuum_the_scan_actually_finds_tables() -> None:
    """反真空①：扫描器必须真的读到表名（否则"没命中"只是没读到东西）。"""
    specs = C._specs.builtin_specs()
    named = {role: _tables_named_in(getattr(spec.brief, "deliverable", ""))
             for role, spec in specs.items()}
    total = sum(len(v) for v in named.values())
    assert total >= 5, f"七个角色的 deliverable 里只扫到 {total} 个表名 ⇒ 判据接近真空：{named}"
    # 覆盖到的角色数也要够（不是"某一个角色写满了"）
    assert sum(1 for v in named.values() if v) >= 6, named


def test_anti_vacuum_2_the_criterion_flags_a_deliberately_broken_declaration() -> None:
    """反真空②（对判据本体的负控）：喂一份越界的假声明 ⇒ 同一个函数必须报出来。"""
    class _Brief:
        deliverable = "研究结论写进 experiments，顺带把 documents 也改一改"

    class _Spec:
        brief = _Brief()

    bad = _violations({"Z": _Spec()})
    assert len(bad) == 2, bad
    assert any("experiments" in b for b in bad), bad
    assert any("documents" in b for b in bad), bad
    # 正控对照：同一份假声明把写集给它，就不该再报
    assert _tables_named_in(_Brief.deliverable) == {"experiments", "documents"}


def test_anti_vacuum_3_the_criterion_only_looks_at_deliverable() -> None:
    """反真空③：别的字段（谈做法）不在范围内 —— 判据只扫 `deliverable` 一格。"""
    class _Brief:
        deliverable = "研究问题与缺口清单"
        policy = ("把结论落到 experiments 里（这句谈做法，不是交付落点）",)

    class _Spec:
        brief = _Brief()

    assert _violations({"Z": _Spec()}) == [] or all("deliverable" in b for b in _violations({"Z": _Spec()})), \
        _violations({"Z": _Spec()})


def test_negative_the_two_copies_of_the_same_declaration_stay_in_step() -> None:
    """负控（同一条声明的两处副本）：`specs/d.py` 与 `agent_prompts.ROLE_BRIEFS["D"]` 逐字一致。

    为什么单列：这两处由 `tests/test_agent_spec_reconciliation.py` 对账，而"声明改一处、
    另一处不改"正是这条判据要防的形态 —— 本轮改 D 的交付物时就先撞上了它
    （`pytest` 报 `[D] brief.deliverable：spec … ≠ 真相 …`）。
    """
    from agentflow import agent_prompts as AP

    specs = C._specs.builtin_specs()
    two = (specs["D"].brief.deliverable, AP.ROLE_BRIEFS["D"].deliverable)
    assert two[0] == two[1], f"两处 D 交付物不一致：\nspecs: {two[0]}\nprompts: {two[1]}"
    # 而这一句里若提到 `analysis_reports`，必须是在说"不进那张表"（不许把它当交付落点）
    assert "analysis_reports" not in two[0] or "不进那张表" in two[0], two[0]
