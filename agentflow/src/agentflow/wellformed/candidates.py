# -*- coding: utf-8 -*-
"""
lit_candidates 那一类：`data/lit_candidates.json` 的槽位、六态与理由码。
"""

from __future__ import annotations

from typing import Mapping

from .. import schema as S
from .predicates import _ID6_OR_4, _shown
from .registry import _Ctx, _local_finding, _rule, _table_rows
from .states import Finding


# ---- lit_candidates：`data/lit_candidates.json`


@_rule("lit_candidates", "slot")
def _rule_lc_slot(ctx: _Ctx) -> list[Finding]:
    """槽位号的号形与唯一性（槽位不复用，重复即同一槽两条读数）。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        slot = str(row.get("slot") or "")
        if not _ID6_OR_4.match(slot):
            out.append(_local_finding(
                ctx, "candidate_slot_shape",
                f"`slot` 读到 {_shown(row.get('slot'))}，不是六位号",
                row_no=n, field_name="slot"))
        if slot in seen:
            out.append(_local_finding(
                ctx, "candidate_duplicate_slot",
                f"`slot`={slot} 与第 {seen[slot]} 条重复 ⇒ 同一槽两条读数",
                row_no=n, field_name="slot"))
        else:
            seen[slot] = n
    return out


@_rule("lit_candidates", "status_vocab")
def _rule_lc_status(ctx: _Ctx) -> list[Finding]:
    """`status` 走 `schema.CANDIDATE_STATUSES` 的六态。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        got = str(row.get("status") or "")
        if got not in S.CANDIDATE_STATUSES:
            out.append(_local_finding(
                ctx, "candidate_status",
                f"`status` 读到 {_shown(row.get('status'))}，不在 {S.CANDIDATE_STATUSES} 里",
                row_no=n, field_name="status"))
    return out


@_rule("lit_candidates", "state_fields")
def _rule_lc_state_fields(ctx: _Ctx) -> list[Finding]:
    """六态各自的必填格（口径逐字取自 `schema.CANDIDATE_STATUSES` 的注释）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        st = str(row.get("status") or "")
        cleared_at = str(row.get("cleared_at") or "").strip()
        lit_id = str(row.get("lit_id") or "").strip()
        if st == "admitted":
            if not lit_id:
                out.append(_local_finding(
                    ctx, "candidate_admitted_without_lit_id",
                    "`status=admitted` 而 `lit_id` 是空的 ⇒ 说已入库却指不出 literature 里哪一行",
                    row_no=n, field_name="lit_id"))
            if not cleared_at:
                out.append(_local_finding(
                    ctx, "candidate_admitted_without_cleared_at",
                    "`status=admitted` 而 `cleared_at` 是空的 ⇒ 说已结算却没有结算时刻"
                    "（清表迁移之前登记的老行没有这一格；老盘上这是历史形状）",
                    row_no=n, field_name="cleared_at", severity="warning"))
        elif st == "cleared":
            if not cleared_at:
                out.append(_local_finding(
                    ctx, "candidate_cleared_without_at",
                    "`status=cleared` 而 `cleared_at` 是空的", row_no=n,
                    field_name="cleared_at"))
            if not str(row.get("clear_reason") or "").strip():
                out.append(_local_finding(
                    ctx, "candidate_cleared_without_reason",
                    "`status=cleared` 而 `clear_reason` 是空的", row_no=n,
                    field_name="clear_reason"))
        elif st == "withdrawn":
            if not str(row.get("withdrawn_reason") or "").strip():
                out.append(_local_finding(
                    ctx, "candidate_withdrawn_without_reason",
                    "`status=withdrawn` 而 `withdrawn_reason` 是空的", row_no=n,
                    field_name="withdrawn_reason"))
        elif st == "rejected":
            if not str(row.get("reject_reason") or "").strip():
                out.append(_local_finding(
                    ctx, "candidate_rejected_without_reason",
                    "`status=rejected` 而 `reject_reason` 是空的 ⇒ 拒了却不说为什么",
                    row_no=n, field_name="reject_reason", severity="warning"))
        elif st == "qualified":
            if lit_id:
                out.append(_local_finding(
                    ctx, "candidate_qualified_with_lit_id",
                    f"`status=qualified` 而 `lit_id`={lit_id!r} ⇒ 判收阶段还不许发号",
                    row_no=n, field_name="lit_id"))
            if not str(row.get("relevance") or "").strip():
                out.append(_local_finding(
                    ctx, "candidate_qualified_without_relevance",
                    "`status=qualified` 而 `relevance` 是空的", row_no=n,
                    field_name="relevance"))
    return out


@_rule("lit_candidates", "reason_code")
def _rule_lc_reason_code(ctx: _Ctx) -> list[Finding]:
    """理由码是受控词表（自由发挥的理由码没法按类统计）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        code = str(row.get("reason_code") or "")
        if code and code not in S.CANDIDATE_REASON_CODES:
            out.append(_local_finding(
                ctx, "candidate_reason_code",
                f"`reason_code` 读到 {_shown(row.get('reason_code'))}，"
                f"不在 {S.CANDIDATE_REASON_CODES} 里", row_no=n,
                field_name="reason_code", severity="warning"))
    return out


@_rule("lit_candidates", "admitted_ref")
def _rule_lc_admitted_ref(ctx: _Ctx) -> list[Finding]:
    """`admitted` 的 `lit_id` 必须在 literature 里存在；同 DOI 不许两条 admitted。"""
    out: list[Finding] = []
    rows = _table_rows(ctx.root, "literature")
    known = {str(r.get("lit_id") or "") for r in rows}
    by_doi: dict[str, int] = {}
    for n, row in ctx.rows:
        if str(row.get("status") or "") != "admitted":
            continue
        lit_id = str(row.get("lit_id") or "")
        if lit_id and lit_id not in known:
            out.append(_local_finding(
                ctx, "candidate_admitted_ref_missing",
                f"`lit_id`={lit_id!r} 在 literature 里没有这一行 ⇒ 说入库了但没有那一行",
                row_no=n, field_name="lit_id"))
        doi = str(row.get("doi") or "").strip().lower()
        if not doi:
            continue
        if doi in by_doi:
            out.append(_local_finding(
                ctx, "candidate_duplicate_doi",
                f"DOI {doi!r} 已由第 {by_doi[doi]} 条 admitted ⇒ 同一篇文献两条已入库",
                row_no=n, field_name="doi", severity="warning"))
        else:
            by_doi[doi] = n
    return out
