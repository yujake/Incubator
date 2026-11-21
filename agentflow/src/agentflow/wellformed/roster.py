# -*- coding: utf-8 -*-
"""
roster_retired 那一类：`out/roster/*-retired.jsonl` 的销号行与它指的活对象。
"""

from __future__ import annotations

from typing import Mapping

from .. import schema as S
from .predicates import _is_int, _shown
from .registry import _Ctx, _local_finding, _rule, _table_rows
from .states import Finding


# ---- roster_retired：`out/roster/*-retired.jsonl`

_RET_ROLES: tuple[str, ...] = (S.CONDUCTOR_ROLE,) + tuple(S.ROLES)


@_rule("roster_retired", "lines")
def _rule_ret_lines(ctx: _Ctx) -> list[Finding]:
    """坏行逐条报出来。"""
    return [_local_finding(ctx, "retired_bad_line", f"坏行：{why}")
            for why in ctx.line_problems]


@_rule("roster_retired", "fields")
def _rule_ret_fields(ctx: _Ctx) -> list[Finding]:
    """销号行的每一格：名字、角色、理由、序号。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        if not str(row.get("name") or "").strip():
            out.append(_local_finding(
                ctx, "retired_name_absent", "这一条没有 `name` ⇒ 销的是谁说不清",
                row_no=n, field_name="name"))
        role = str(row.get("role") or "")
        if role not in _RET_ROLES:
            out.append(_local_finding(
                ctx, "retired_role",
                f"`role` 读到 {_shown(row.get('role'))}，不在名册 {_RET_ROLES} 里",
                row_no=n, field_name="role", severity="warning"))
        if not str(row.get("reason") or "").strip():
            out.append(_local_finding(
                ctx, "retired_reason_absent",
                "`reason` 是空的 ⇒ 销号没有理由（普查里 36 条、跨 15 个工作区；"
                "例如 lp-ball-14 的 t-000081、lp-ball-12 的 t-000001、"
                "lp-ball-10 的 t-000010）",
                row_no=n, field_name="reason", severity="warning"))
        if not _is_int(row.get("seq")):
            out.append(_local_finding(
                ctx, "retired_seq",
                f"`seq` 读到 {_shown(row.get('seq'))}，应为整数",
                row_no=n, field_name="seq", severity="warning"))
    return out


@_rule("roster_retired", "refs")
def _rule_ret_refs(ctx: _Ctx) -> list[Finding]:
    """销号对象必须真实存在：`task_id` / `owner` 都要在 tasks 里有那一行。"""
    out: list[Finding] = []
    rows = _table_rows(ctx.root, "tasks")
    known = {str(r.get("task_id") or "") for r in rows}
    for n, row in ctx.rows:
        for field_name in ("task_id", "owner"):
            got = str(row.get(field_name) or "")
            if got and got not in known:
                out.append(_local_finding(
                    ctx, "retired_ref_missing",
                    f"`{field_name}`={got!r} 在 tasks 里没有这一行 ⇒ 销的是不存在的对象",
                    row_no=n, field_name=field_name))
    return out
