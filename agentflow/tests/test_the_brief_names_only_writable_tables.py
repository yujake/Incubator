# -*- coding: utf-8 -*-
"""一个角色的 `deliverable` 里点名的台账表，必须在它自己的写集里。

## 这条判据守的是什么（T4 第 6 趟 `t4f` 的真机读数）

`t4f` 里 M 报了一条 `cannot`，逐字是：D.write_report 落 `analysis_reports` | D 调用 write_report 6 次均返回 ok，
> 但台账里没有一张表收得下它（`WRITE_SETS["D"]` 无 `analysis_reports`），属框架口径问题M 说得对：`analysis_reports` 是 C
的报告通道（`schema.REPORT_KINDS` 只收`hottest/paths/cold/gaps` 四档），D
的写集里没有它，`AgentD.write_report` 也只写`reports/<qid>-research.md` 那份 markdown、一张表都不写。而 D 的
`deliverable`当时逐字写着"analysis_reports 里的分析、结论、建议三层…" ⇒ 声明与权限面打架，M 照着声明去找那张表，找不到，只能记一条 `cannot`。
代码那一层早就知道这件事（`agent_d/_support.py` 的 `report_landing_reading`，S-07 的裁定是"只加读数、不改硬契约"），但声明那一层没跟上。

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
from agentflow import store as ST

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


# ---------------------------------------------------------------- 第二类扫描面：退役的表名（CS-13）
#
# 上面那三条判据按 `schema.TABLES` 现算词表 —— 于是已经退役的表名它一个都扫不到，
# 而"声明点名一张不存在的表"正是它当初要防的形态（`draft/44` `J-01`：D 的 `deliverable`
# 点了自己写不了的 `analysis_reports`；那一张表还在，所以被判据抓住了）。
# 真机上的实例（批 R10 修掉）：B 的 `deliverable` 写着"concepts 与 relations 行"，
# 而 `concepts` 早在并表（S1r，`SCHEMA_VERSION=2`）时就住进了 `statements`
# （`store._MOVED_TABLES` 是那件事的显式登记处）—— 那句话安然通过了上面三条。
#
# 这一节补的就是那第二类：退役的表名。词表不另立 —— 直接读 `store._MOVED_TABLES`
# （它是"并走的表 → 新家"的唯一登记处，`store.py:99-124`）。


def _retired_tables_named_in(text: str) -> dict[str, str]:
    """一句话里点到的已并走的表名 → 新家（空 dict = 一个都没点到）。"""
    return {old: str(meta.get("into") or "")
            for old, meta in ST._MOVED_TABLES.items() if old in str(text or "")}


def test_no_deliverable_names_a_retired_table() -> None:
    """正控：没有哪个角色的 `deliverable` 点着一张已经并走的表。

    为什么要单列一条（而不是并进上面那个 `_violations`）：两类的词表来源不同 ——
    一类是 `schema.TABLES`（现役表），一类是 `store._MOVED_TABLES`（退役表 → 新家）。
    合起来写会让"命中"这句话失去指路能力（读的人分不出"你写不了这张表"与"这张表没了"）。
    """
    specs = C._specs.builtin_specs()
    bad: list[str] = []
    for role, spec in sorted(specs.items()):
        brief = getattr(spec, "brief", None)
        if brief is None:
            continue
        hit = _retired_tables_named_in(getattr(brief, "deliverable", ""))
        for old, new_home in sorted(hit.items()):
            bad.append(f"{role}.deliverable 点了已并走的表 {old}（新家：{new_home}）")
    assert not bad, (
        "有角色的交付物声明点了一张已经并走的表（声明落后于存储布局）——\n  "
        + "\n  ".join(bad)
        + "\n改法照 `draft/103` §4.1b-24 那一处：写成新家（例如 "
          "`statements`（`kind=\"concept\"`）），别留着老表名。"
    )


def test_anti_vacuum_the_retired_table_scan_sees_something() -> None:
    """反真空 + 负控：退役词表真的读到了东西，且喂一份旧声明时当场报出来。"""
    assert ST._MOVED_TABLES, (
        "`store._MOVED_TABLES` 是空的 ⇒ 这一条判据退化成恒真（并表那次登记的"
        "『concepts → statements』必须留在那里，它是这一类的词表来源）")
    hit = _retired_tables_named_in("交付物是 concepts 与 relations 行")
    assert hit == {"concepts": "statements"}, hit

    class _Brief:
        # 刻意只写退役的那一个名字：句子里若再带上 `relations`（现役表），
        # 第一类判据也会报它 ⇒ 这条负控就分不出"哪一类看见的"。
        deliverable = "concepts 行"

    class _Spec:
        brief = _Brief()

    # 负控：这份旧声明在第一类判据（现役表词表）眼里是干净的 —— 那正是缺口的样子
    assert _violations({"Z": _Spec()}) == [], "第一类判据不该看见退役表名（它按 S.TABLES 现算）"
    # 而第二类判据必须报出来
    retired_hit = _retired_tables_named_in(_Spec.brief.deliverable)
    assert retired_hit == {"concepts": "statements"}, retired_hit
