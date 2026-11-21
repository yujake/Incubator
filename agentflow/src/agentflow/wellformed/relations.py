# -*- coding: utf-8 -*-
"""
relations 那一类：`data/relations.json` 的号、引文区间、来源指向与去重键。
"""

from __future__ import annotations

from typing import Mapping

from .. import schema as S
from .predicates import _ID6_OR_4, _shown
from .registry import _Ctx, _local_finding, _rule, _table_rows
from .states import Finding


# ---- relations：`data/relations.json`

_REL_STATUS_VOCAB: tuple[str, ...] = tuple(S.RELATION_STATUS)


@_rule("relations", "id_shape")
def _rule_rel_id(ctx: _Ctx) -> list[Finding]:
    """`relation_id` 的号形与唯一性。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        rid = str(row.get("relation_id") or "")
        if not _ID6_OR_4.match(rid):
            out.append(_local_finding(
                ctx, "relation_id_shape",
                f"`relation_id` 读到 {_shown(row.get('relation_id'))}，不是六位号",
                row_no=n, field_name="relation_id"))
        if rid in seen:
            out.append(_local_finding(
                ctx, "relation_duplicate_id",
                f"`relation_id`={rid} 与第 {seen[rid]} 条重复", row_no=n,
                field_name="relation_id"))
        else:
            seen[rid] = n
    return out


@_rule("relations", "quote_span")
def _rule_rel_quote_span(ctx: _Ctx) -> list[Finding]:
    """说 `quote_verified=true` 就必须给出 `quote_span`（真机 lp-ball-10 的 27 条形态）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        if row.get("quote_verified") is not True:
            continue
        span = str(row.get("quote_span") or "").strip()
        if span:
            continue
        out.append(_local_finding(
            ctx, "relation_quote_span_empty",
            "`quote_verified=true` 而 `quote_span` 是空的 ⇒ 说「逐字回验通过」却指不出"
            "核的是哪一段；补回 span（形如 `p2:norm[15:93]`），或把 quote_verified 改回 "
            "null/未查", row_no=n, field_name="quote_span"))
    return out


@_rule("relations", "quote_mode")
def _rule_rel_quote_mode(ctx: _Ctx) -> list[Finding]:
    """回验方式必须落在 `schema.QUOTE_MODES` 里（否则"通过"没有口径）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        if row.get("quote_verified") is not True:
            continue
        mode = str(row.get("quote_mode") or "")
        if mode and mode not in S.QUOTE_MODES:
            out.append(_local_finding(
                ctx, "relation_quote_mode",
                f"`quote_mode` 读到 {_shown(row.get('quote_mode'))}，不在 {S.QUOTE_MODES} 里",
                row_no=n, field_name="quote_mode", severity="warning"))
    return out


@_rule("relations", "lit_ref")
def _rule_rel_lit_ref(ctx: _Ctx) -> list[Finding]:
    """`lit_id` 必须指向 literature 里真实存在的一行。"""
    out: list[Finding] = []
    rows = _table_rows(ctx.root, "literature")
    known = {str(r.get("lit_id") or "") for r in rows}
    for n, row in ctx.rows:
        lid = str(row.get("lit_id") or "")
        if lid and lid not in known:
            out.append(_local_finding(
                ctx, "relation_lit_missing",
                f"`lit_id`={lid!r} 在 literature 里没有这一行 ⇒ 这条关系的来源不存在",
                row_no=n, field_name="lit_id"))
    return out


@_rule("relations", "status")
def _rule_rel_status(ctx: _Ctx) -> list[Finding]:
    """`status` 走 `schema.RELATION_STATUS`。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        got = row.get("status")
        if got is not None and str(got) not in _REL_STATUS_VOCAB:
            out.append(_local_finding(
                ctx, "relation_status",
                f"`status` 读到 {_shown(got)}，不在 {_REL_STATUS_VOCAB} 里",
                row_no=n, field_name="status", severity="warning"))
    return out


@_rule("relations", "content")
def _rule_rel_content(ctx: _Ctx) -> list[Finding]:
    """一条关系要说得清它是什么：`description` 与 `statement` 不许同时为空。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        desc = str(row.get("description") or "").strip()
        stmt = str(row.get("statement") or "").strip()
        if not desc and not stmt:
            out.append(_local_finding(
                ctx, "relation_content_empty",
                "`description` 与 `statement` 都是空的 ⇒ 这条关系没有可读的内容（关系类型空）",
                row_no=n, field_name="description", severity="warning"))
    return out


@_rule("relations", "concept_ids")
def _rule_rel_concepts(ctx: _Ctx) -> list[Finding]:
    """`concept_ids` 必须是两个以上非空号（一条关系至少连两个概念）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        got = row.get("concept_ids")
        if not isinstance(got, list) or len(got) < 2:
            out.append(_local_finding(
                ctx, "relation_concept_ids",
                f"`concept_ids` 读到 {_shown(got)}，应为至少两个号的数组",
                row_no=n, field_name="concept_ids", severity="warning"))
            continue
        if any(not str(c or "").strip() for c in got):
            out.append(_local_finding(
                ctx, "relation_concept_ids",
                f"`concept_ids` 里有空号：{_shown(got)}", row_no=n,
                field_name="concept_ids", severity="warning"))
    return out


@_rule("relations", "dedup_key")
def _rule_rel_dedup(ctx: _Ctx) -> list[Finding]:
    """同一对概念 + 同一段引文不该落两条 active 关系。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        if str(row.get("status") or "") not in ("", "active"):
            continue
        key = str(row.get("dedup_key") or "")
        if not key:
            out.append(_local_finding(
                ctx, "relation_dedup_key_absent",
                "`dedup_key` 是空的 ⇒ 这条关系没有去重键（重复识别时认不出它）",
                row_no=n, field_name="dedup_key", severity="warning"))
            continue
        if key in seen:
            out.append(_local_finding(
                ctx, "relation_duplicate_dedup_key",
                f"`dedup_key`={key!r} 与第 {seen[key]} 条重复（两条都是 active 档）⇒ "
                "同一段引文落了两条关系", row_no=n, field_name="dedup_key"))
        else:
            seen[key] = n
    return out
