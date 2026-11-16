# -*- coding: utf-8 -*-
"""渲染后的 system prompt ↔ 该角色的工具面：判据的共用扫描器与豁免登记表。

## 这一层守什么

`tests/test_policy_never_names_a_tool_the_role_lacks.py` 守的是 policy 那一格；
`tests/test_tool_summaries_only_name_tools_the_role_has.py` 守的是 工具摘要；
`tests/test_prompt_action_names_exist.py` 守的是 动作名存不存在。它们都不守
「渲染出来的那一份完整 system prompt 里点名的工具，是不是这个角色拿得到的」——
而模型读到的正是这一份。审计 AU1 ③ 的缺口一句话就是它。

## 判据形状

1. 对每个角色渲染完整 system prompt（`agent_prompts.system_prompt`，与生产同一条
   入口、同一张带 `fs.*` / `research.*` 的注册表 —— 裸 `build_registry()` 少 13 件，
   不能拿它当"面"）；
2. 扫形如 `组.动作` 的工具名 token；凡命中注册工具名、而不在该角色工具面上 ⇒ 红；
3. 唯一的出路是逐条登记（`EXEMPT`）：每条给出类目、原文锚点、两档下的出现次数。
   未登记、登记过期、次数对不上、锚点不在 —— 全部红。

## 豁免类目（受控词表，逐条给理由）

- `partner_quote`：伙伴表把同伴的 boundary 原话逐字抄进提示词（`partners_lines`
  的机制）。句子主语是"它"，读者读到的是"别人的边界"。判据现算 `partners_lines`
  核对：这个 token 的每一处出现都必须落在伙伴表里，多一处就红。
  审计 AU1 表一 C1 的五份（B/D/F/G/M；Lean 开档还有 L —— L 读 C 的 boundary）。
- `owner_annotation`：同一句写明施事是别人（"主控用 `conductor.board`" / "由 G 用
  `doc.build_document`" / "V 的 `verify.verify_proof`" / "登记走 A"）。这不是教本角色。
- `negation_note`：同一句自带否定（"主控 M 没有这两件工具 —— 它的读面是 `fs.*`"）。
- `namespace_note`：同一实现的两种命名空间（工具名 vs 动作名）。例如名册那一段把
  `conductor.retire_child(child_name=…)` 的调用形抄给只读角色，但同一句写明
  "能调工具的父走 `retire_child`，只读那一档只有 `retire` 形"；`conductor.summon`
  对 G/H 是同一件事：他们走动作 `summon`，句中说"派活的结果"。
- `not_a_tool`：命中注册名，但句中是返回值字段路径 —— M 的 `attack.status` 是
  `F.status` 拿回来的那个字段，不是一次工具调用（审计 AU1 表一的假阳性记录）。

## 为什么锚点与次数是判据的一部分

只登记 `(角色, token)` 会把这张表变成橡皮图章：句子删了、理由没了，表还绿着。
所以每条还要给一句原文锚点（这句话还在，才说明"这是转述/否定/命名空间"的理由还
成立）和两档出现次数（多一处 = 新的提法没有走登记，少一处 = 表过期）。
`partner_quote` 不需要锚点：它的理由由 `partners_lines` 现算。

维护规则：提示词里新增/删除一处跨角色工具名 ⇒ 同一笔里改这张表；改动理由写在
`WHY` 那一行的类目里，不要新开类目（新类目 = 新口径，要先说服人）。
"""
from __future__ import annotations

import dataclasses
import re
from typing import Mapping

from agentflow import agent_prompts as AP

#: `组.动作` 的工具名 token（大小写敏感：`V.verify_proof` 是动作，不在射程）。
TOOL_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)(?![A-Za-z0-9_])")

#: 豁免类目与它们的理由（受控词表：`EXEMPT` 里的类目必须在这里）。
WHY: dict[str, str] = {
    "partner_quote": "伙伴表逐字抄同伴的 boundary 原话（机制如此；主语是「它」）",
    "owner_annotation": "同一句写明施事是别人（主控 / 别的角色 / V 的）",
    "negation_note": "同一句自带否定（拿不到、没有这一件 / 读面是 fs.*）",
    "namespace_note": "同一实现的两种命名空间（工具名 vs 动作名；句子已写明读者走哪一档）",
    "not_a_tool": "命中注册名，但句中是返回值字段路径（不是一次工具调用）",
}

#: 伙伴表机制涉及的工具名（`partner_quote` 只许出现在这几个 token 上）。
PARTNER_TOKENS: frozenset[str] = frozenset({
    "analysis.register_report",
    "review.record_finding",
    "review.report",
    "review.review_document",
    "review.verify_fixes",
})


@dataclasses.dataclass(frozen=True)
class Exemption:
    """一条登记：类目 + 原文锚点 + 两档出现次数（`None` = 该档里这个角色不渲染）。"""

    klass: str
    anchor: str
    count_on: int | None
    count_off: int | None

    def count_in(self, mode: str) -> int | None:
        return self.count_on if mode == "on" else self.count_off


#: 逐条登记。键 `(角色, token)`；出现次数是"当前这一版提示词"的读数，不是规格。
#: 生成方式：`temp/cl2/build_table.py --emit`（两档各起一次进程，见那个脚本的 docstring）。
#: 2026-11-16（p286，FC-27 三份补丁）：H 的 G8 段多点名一次 `conductor.closing`（收工门的
#: `readings.run_evidence`）、M 的 G8 段多点名一次 `verify.run_experiment`（台账行带
#: `code_hash` / `exit_code`）⇒ 两条 owner_annotation 的次数各 +1；锚点未动，类目未动
#: （仍是同一类"写明施事是别人"的转述）。
EXEMPT: dict[tuple[str, str], Exemption] = {
    ("A", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("A", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("A", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("B", "analysis.register_report"): Exemption("partner_quote", "", 1, 1),
    ("B", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("B", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("B", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("B", "review.record_finding"): Exemption("partner_quote", "", 1, 1),
    ("B", "review.report"): Exemption("partner_quote", "", 1, 1),
    ("B", "review.review_document"): Exemption("partner_quote", "", 1, 1),
    ("B", "review.verify_fixes"): Exemption("partner_quote", "", 1, 1),
    ("C", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("C", "conductor.retire_child"): Exemption("namespace_note", "销号两个入口同一落点", 2, 2),
    ("C", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 1, 1),
    ("D", "analysis.register_report"): Exemption("partner_quote", "", 1, 1),
    ("D", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("D", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("D", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("E", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("E", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("E", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("F", "analysis.register_report"): Exemption("partner_quote", "", 1, 1),
    ("F", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("F", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("F", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("G", "analysis.register_report"): Exemption("partner_quote", "", 1, 1),
    ("G", "conductor.acceptance"): Exemption("owner_annotation", "主控用 `conductor.acceptance` 读它", 1, 1),
    ("G", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, 1),
    ("G", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 5, 5),
    ("G", "conductor.summon"): Exemption("namespace_note", "被拒的派活与没登记的条目不许写成已登记", 1, 1),
    ("G", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, 3),
    ("G", "review.record_finding"): Exemption("partner_quote", "", 1, 1),
    ("G", "review.report"): Exemption("partner_quote", "", 1, 1),
    ("G", "review.review_document"): Exemption("partner_quote", "", 1, 1),
    ("G", "review.verify_fixes"): Exemption("partner_quote", "", 1, 1),
    ("G", "search.ingest_local"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("G", "search.register"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("G", "verify.verify_proof"): Exemption("owner_annotation", "由 V 的 `verify.verify_proof`", 1, 1),
    ("H", "conductor.acceptance"): Exemption("owner_annotation", "主控用 `conductor.acceptance` 读它", 1, 1),
    ("H", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 6, 6),
    ("H", "conductor.retire_child"): Exemption("namespace_note", "销号两个入口同一落点", 3, 3),
    ("H", "conductor.summon"): Exemption("namespace_note", "被拒的派活与没登记的条目不许写成已登记", 1, 1),
    ("H", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 1, 1),
    ("H", "doc.build_document"): Exemption("owner_annotation", "由 G 用 `doc.build_document`", 1, 1),
    ("H", "doc.paper_compile"): Exemption("owner_annotation", "只有 G 拿得到", 5, 5),
    ("H", "fs.write"): Exemption("owner_annotation", "由 G 用 `fs.write`", 2, 2),
    ("H", "search.ingest_local"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("H", "search.register"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("H", "verify.verify_proof"): Exemption("owner_annotation", "由 V 的 `verify.verify_proof`", 1, 1),
    ("V", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, 1),
    ("V", "conductor.retire_child"): Exemption("namespace_note", "销号两个入口同一落点", 2, 2),
    ("V", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 1, 1),
    ("L", "analysis.register_report"): Exemption("partner_quote", "", 1, None),
    ("L", "conductor.board"): Exemption("owner_annotation", "**主控**用 `conductor.board` 看它们", 1, None),
    ("L", "conductor.closing"): Exemption("owner_annotation", "主控收工前调 `conductor.closing`", 1, None),
    ("L", "conductor.wake_blocked"): Exemption("owner_annotation", "要等主控 `conductor.wake_blocked`", 3, None),
    ("M", "analysis.register_report"): Exemption("partner_quote", "", 1, 1),
    ("M", "attack.status"): Exemption("not_a_tool", "你派 `F.status` 拿回来的 `attack.status`", 1, 1),
    ("M", "doc.build_document"): Exemption("owner_annotation", "由 G 用 `doc.build_document`", 1, 1),
    ("M", "doc.paper_compile"): Exemption("owner_annotation", "只有 G 拿得到", 6, 6),
    ("M", "doc.write_mapping"): Exemption("owner_annotation", "G 调 `doc.write_mapping`", 1, 1),
    ("M", "manuscripts.list"): Exemption("negation_note", "主控 M 没有这两件工具", 1, 1),
    ("M", "manuscripts.read"): Exemption("negation_note", "主控 M 没有这两件工具", 2, 2),
    ("M", "review.record_finding"): Exemption("partner_quote", "", 1, 1),
    ("M", "review.report"): Exemption("partner_quote", "", 1, 1),
    ("M", "review.review_document"): Exemption("partner_quote", "", 1, 1),
    ("M", "review.verify_fixes"): Exemption("partner_quote", "", 1, 1),
    ("M", "search.ingest_local"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("M", "search.register"): Exemption("owner_annotation", "登记走 A（`literature`", 1, 1),
    ("M", "verify.run_experiment"): Exemption("owner_annotation", "派 E 用 `verify.run_experiment", 2, 2),
    ("M", "verify.verify_proof"): Exemption("owner_annotation", "由 V 的 `verify.verify_proof`", 1, 1),
}


def surface(registry: object, role: str) -> set[str]:
    """该角色的工具面（`for_role` 是工具面的唯一读法）。"""
    return {str(spec.name) for spec in registry.for_role(role)}  # type: ignore[attr-defined]


def partner_text(role: str) -> str:
    """这一格渲染出来的伙伴表（与提示词里那几行逐字同源）。"""
    return "\n".join(AP.partners_lines(role))


def foreign_tokens(text: str, registry: object, role: str) -> list[str]:
    """提示词里点名了、而该角色面上没有的注册工具名（排序去重）。"""
    names = {str(n) for n in registry.names()}  # type: ignore[attr-defined]
    have = surface(registry, role)
    return sorted({tok for tok in TOOL_TOKEN.findall(text) if tok in names and tok not in have})


def scan(role: str, text: str, registry: object, *, mode: str,
         exempt: Mapping[tuple[str, str], Exemption] | None = None,
         partner_check: bool = True) -> list[str]:
    """扫一份渲染后的提示词，返回"别家工具名"的逐条问题（空列表 = 全在登记里）。

    `exempt=None` 用 `EXEMPT`；传空 dict 是反真空（"清空豁免清单"那一档）。
    """
    table = EXEMPT if exempt is None else exempt
    partner = partner_text(role)
    out: list[str] = []
    for token in foreign_tokens(text, registry, role):
        entry = table.get((role, token))
        if entry is None:
            out.append(f"{role}: {token}（未登记：提示词点名了该角色拿不到的工具）")
            continue
        if entry.klass not in WHY:
            out.append(f"{role}: {token}（登记的类目 {entry.klass!r} 不在受控表里）")
            continue
        want = entry.count_in(mode)
        if want is None:
            out.append(f"{role}: {token}（{mode} 档里这个角色不渲染，但登记说它有次数）")
            continue
        got = text.count(token)
        if got != want:
            out.append(f"{role}: {token}（{mode} 档出现 {got} 次，登记是 {want} 次 ⇒ "
                       "要么登记过期，要么新提法没走登记）")
            continue
        if entry.klass == "partner_quote":
            if token not in PARTNER_TOKENS:
                out.append(f"{role}: {token}（partner_quote 只许用在伙伴表那五件上）")
            elif not partner_check or partner.count(token) != got:
                out.append(f"{role}: {token}（登记成伙伴表引用，但全文 {got} 次里只有 "
                           f"{partner.count(token)} 次在伙伴表里）")
            continue
        if not entry.anchor or entry.anchor not in text:
            out.append(f"{role}: {token}（豁免理由的原文锚点不在了：{entry.anchor!r} ⇒ "
                       "这条登记过期，请重判它还是不是转述/否定）")
    return out


def registered_pairs() -> set[tuple[str, str]]:
    return set(EXEMPT)


def pair_count(role: str) -> int:
    return sum(1 for r, _ in EXEMPT if r == role)
