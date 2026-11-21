# -*- coding: utf-8 -*-
"""
statements 那一类：`data/statements.json` 的号、命题类型、等级与证明号。
"""

from __future__ import annotations

from typing import Mapping

from .. import evidencebits as EB
from .. import manuscriptkind as MK
from .. import schema as S
from .predicates import _ID6_OR_4, _is_int, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- statements：`data/statements.json`

_STMT_KIND_VOCAB: tuple[str, ...] = tuple(MK.KIND_RANK) + tuple(EB.DEFINITION_KINDS)
_STMT_GRADE_VOCAB: tuple[str, ...] = (tuple(EB.GRADE_ORDER) + (EB.GRADE_NOT_APPLICABLE,
                                                              EB.GRADE_UNJUDGED))


@_rule("statements", "id_shape")
def _rule_stmt_id(ctx: _Ctx) -> list[Finding]:
    """`stmt_id` 的号形与唯一性。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        sid = str(row.get("stmt_id") or "")
        if not _ID6_OR_4.match(sid):
            out.append(_local_finding(
                ctx, "statement_id_shape",
                f"`stmt_id` 读到 {_shown(row.get('stmt_id'))}，不是六位号",
                row_no=n, field_name="stmt_id"))
        if sid in seen:
            out.append(_local_finding(
                ctx, "statement_duplicate_id",
                f"`stmt_id`={sid} 与第 {seen[sid]} 条重复", row_no=n, field_name="stmt_id"))
        else:
            seen[sid] = n
    return out


@_rule("statements", "kind_vocab")
def _rule_stmt_kind(ctx: _Ctx) -> list[Finding]:
    """`kind` 走 `manuscriptkind.KIND_RANK` 加概念两档。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        got = str(row.get("kind") or "")
        if got and got not in _STMT_KIND_VOCAB:
            out.append(_local_finding(
                ctx, "statement_kind",
                f"`kind` 读到 {_shown(row.get('kind'))}，不在 {_STMT_KIND_VOCAB} 里",
                row_no=n, field_name="kind"))
    return out


@_rule("statements", "grade_vocab")
def _rule_stmt_grade(ctx: _Ctx) -> list[Finding]:
    """`bits.grade` 走 `evidencebits` 的等级词表（含 not_applicable / unjudged）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        bits = row.get("bits")
        if not isinstance(bits, Mapping):
            out.append(_local_finding(
                ctx, "statement_bits_shape",
                f"`bits` 读到 {_shown(bits)}，应为对象（五元位那一格必须是结构，不是标量）",
                row_no=n, field_name="bits"))
            continue
        grade = bits.get("grade")
        if grade is not None and str(grade) not in _STMT_GRADE_VOCAB:
            out.append(_local_finding(
                ctx, "statement_grade",
                f"`bits.grade` 读到 {_shown(grade)}，不在 {_STMT_GRADE_VOCAB} 里",
                row_no=n, field_name="bits.grade"))
    return out


@_rule("statements", "vocab")
def _rule_stmt_vocab(ctx: _Ctx) -> list[Finding]:
    """`origin` / `status` 走 `schema` 的两张词表。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        origin = row.get("origin")
        if origin is not None and str(origin) not in S.STATEMENT_ORIGINS:
            out.append(_local_finding(
                ctx, "statement_origin",
                f"`origin` 读到 {_shown(origin)}，不在 {S.STATEMENT_ORIGINS} 里",
                row_no=n, field_name="origin", severity="warning"))
        status = row.get("status")
        if status is not None and str(status) not in S.STATEMENT_STATUSES:
            out.append(_local_finding(
                ctx, "statement_status",
                f"`status` 读到 {_shown(status)}，不在 {S.STATEMENT_STATUSES} 里",
                row_no=n, field_name="status", severity="warning"))
    return out


@_rule("statements", "proof_no")
def _rule_stmt_proof_no(ctx: _Ctx) -> list[Finding]:
    """有证明正文就要有证明号，没有正文就不该带号。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        text = str(row.get("proof_text") or "")
        no = row.get("proof_no")
        if text.strip() and not (_is_int(no) and no >= 1):
            out.append(_local_finding(
                ctx, "statement_proof_text_without_no",
                f"`proof_text` 非空，而 `proof_no` 读到 {_shown(no)} ⇒ 有正文没有证明号",
                row_no=n, field_name="proof_no", severity="warning"))
        if not text.strip() and _is_int(no) and no >= 1:
            out.append(_local_finding(
                ctx, "statement_proof_no_without_text",
                f"`proof_no`={no}，而 `proof_text` 是空的 ⇒ 有证明号没有正文",
                row_no=n, field_name="proof_no", severity="warning"))
    return out


@_rule("statements", "quote_span")
def _rule_stmt_quote_span(ctx: _Ctx) -> list[Finding]:
    """与关系行同一条：说回验通过就要给出区间。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        if row.get("quote_verified") is not True:
            continue
        if str(row.get("quote_span") or "").strip():
            continue
        out.append(_local_finding(
            ctx, "statement_quote_span_empty",
            "`quote_verified=true` 而 `quote_span` 是空的 ⇒ 通过没有可复核的区间",
            row_no=n, field_name="quote_span"))
    return out
