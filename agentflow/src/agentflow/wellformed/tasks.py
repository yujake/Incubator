# -*- coding: utf-8 -*-
"""
tasks 那一类：`data/tasks.json` 的号、角色、状态词表与父行指向。
"""

from __future__ import annotations

from typing import Mapping

from .. import schema as S
from .predicates import _TASK_ID, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- tasks：`data/tasks.json`

_TASK_ROLES: tuple[str, ...] = (S.CONDUCTOR_ROLE,) + tuple(S.ROLES)


@_rule("tasks", "id_shape")
def _rule_task_id(ctx: _Ctx) -> list[Finding]:
    """`task_id` 的号形与唯一性。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        tid = str(row.get("task_id") or "")
        if not _TASK_ID.match(tid):
            out.append(_local_finding(
                ctx, "task_id_shape",
                f"`task_id` 读到 {_shown(row.get('task_id'))}，应形如 t-000000",
                row_no=n, field_name="task_id"))
        if tid in seen:
            out.append(_local_finding(
                ctx, "task_duplicate_id",
                f"`task_id`={tid} 与第 {seen[tid]} 条重复", row_no=n, field_name="task_id"))
        else:
            seen[tid] = n
    return out


@_rule("tasks", "role")
def _rule_task_role(ctx: _Ctx) -> list[Finding]:
    """`role` 必须在名册里（M 加 A-V-L）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        role = str(row.get("role") or "")
        if role not in _TASK_ROLES:
            out.append(_local_finding(
                ctx, "task_role",
                f"`role` 读到 {_shown(row.get('role'))}，不在名册 {_TASK_ROLES} 里",
                row_no=n, field_name="role"))
    return out


@_rule("tasks", "vocab")
def _rule_task_vocab(ctx: _Ctx) -> list[Finding]:
    """`status` / `outcome` / `item_state` 各走自己的词表。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        status = row.get("status")
        if status is not None and str(status) not in S.TASK_STATUSES:
            out.append(_local_finding(
                ctx, "task_status",
                f"`status` 读到 {_shown(status)}，不在 {S.TASK_STATUSES} 里",
                row_no=n, field_name="status"))
        outcome = row.get("outcome")
        if outcome is not None and str(outcome) not in S.TASK_OUTCOMES:
            out.append(_local_finding(
                ctx, "task_outcome",
                f"`outcome` 读到 {_shown(outcome)}，不在 {S.TASK_OUTCOMES} 里",
                row_no=n, field_name="outcome", severity="warning"))
        item_state = str(row.get("item_state") or "")
        if item_state and item_state not in S.ITEM_STATES:
            out.append(_local_finding(
                ctx, "task_item_state",
                f"`item_state` 读到 {_shown(row.get('item_state'))}，不在 {S.ITEM_STATES} 里",
                row_no=n, field_name="item_state", severity="warning"))
    return out


@_rule("tasks", "dispatch_only")
def _rule_task_action(ctx: _Ctx) -> list[Finding]:
    """空 `action` 是 S2 的生产形态，不是畸形（只记读数，不落 Finding）。

    口径出处：`policy.py` 写明「`action=""` 是生产路径上唯一的派活形态（口径 S2）」。
    2026-11-21 普查先在真机上数到 `tasks.action=""`（lp-ball-15 有 38 条），本以为是
    畸形；读到这条口径之后判定它不是 —— 把它记成 Finding 会把主路径读成 38 条假读数，
    正是"机械判据压人"的形态。所以这里只把条数记进 notes。
    """
    empty = sum(1 for _, row in ctx.rows
                if not str(row.get("action") or "").strip()
                and not str(row.get("kind") or "").strip())
    if empty:
        ctx.notes.append(
            f"其中 {empty} 条是只派活、不点动作（`action=\"\"`，口径 S2 的生产形态，"
            "不是畸形）")
    return []


@_rule("tasks", "parent")
def _rule_task_parent(ctx: _Ctx) -> list[Finding]:
    """`parent_task_id` 要么为空，要么指向本表里真实存在的一行。"""
    out: list[Finding] = []
    known = {str(r.get("task_id") or "") for _, r in ctx.rows}
    for n, row in ctx.rows:
        parent = row.get("parent_task_id")
        if parent in (None, ""):
            continue
        if str(parent) in known:
            continue
        out.append(_local_finding(
            ctx, "task_parent_missing",
            f"`parent_task_id`={_shown(parent)} 在 tasks 里没有这一行 ⇒ 父行不存在",
            row_no=n, field_name="parent_task_id", severity="warning"))
    return out
