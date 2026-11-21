# -*- coding: utf-8 -*-
"""
usage_ledger 那一类：`data/usage_ledger.json` 的钱、词表、幂等键与调用序号。
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .. import modelcost as MC
from .. import schema as S
from .predicates import _ID6_OR_4, _is_int, _is_number, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding
from .tasks import _TASK_ROLES


# ---- usage_ledger：`data/usage_ledger.json`

_UL_SCOPES: tuple[str, ...] = tuple(S.USAGE_SCOPES) + (S.SCOPE_UNCLASSIFIED,)


@_rule("usage_ledger", "id_shape")
def _rule_ul_id(ctx: _Ctx) -> list[Finding]:
    """`usage_id` 的号形与唯一性。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        uid = str(row.get("usage_id") or "")
        if not _ID6_OR_4.match(uid):
            out.append(_local_finding(
                ctx, "usage_id_shape",
                f"`usage_id` 读到 {_shown(row.get('usage_id'))}，不是六位号",
                row_no=n, field_name="usage_id"))
        if uid in seen:
            out.append(_local_finding(
                ctx, "usage_duplicate_id",
                f"`usage_id`={uid} 与第 {seen[uid]} 条重复", row_no=n, field_name="usage_id"))
        else:
            seen[uid] = n
    return out


@_rule("usage_ledger", "money")
def _rule_ul_money(ctx: _Ctx) -> list[Finding]:
    """`usd` 必须是有限非负数；`tokens_total` 必须等于进出之和。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        usd = row.get("usd")
        if not _is_number(usd) or float(usd) < 0:
            out.append(_local_finding(
                ctx, "usage_usd",
                f"`usd` 读到 {_shown(usd)} ⇒ 不是有限非负数（负数/NaN/inf 都会把合计算错）",
                row_no=n, field_name="usd"))
        tin, tout, ttotal = row.get("tokens_in"), row.get("tokens_out"), row.get("tokens_total")
        if not (_is_int(tin) and _is_int(tout) and _is_int(ttotal)):
            out.append(_local_finding(
                ctx, "usage_tokens_shape",
                f"`tokens_in`/`tokens_out`/`tokens_total` 读到 "
                f"{_shown(tin)}/{_shown(tout)}/{_shown(ttotal)}，都应为整数",
                row_no=n, field_name="tokens_total"))
        elif ttotal != tin + tout:
            out.append(_local_finding(
                ctx, "usage_tokens_total",
                f"`tokens_total`={ttotal} 而 `tokens_in`+`tokens_out`={tin + tout} ⇒ 合计对不上",
                row_no=n, field_name="tokens_total"))
    return out


def _is_known_role(value: Any) -> bool:
    """角色名在不在名册里；秘书地址（`secretary:<角色>`）照认。

    为什么把秘书地址算进来：用量账上的 `role` 是"谁花的钱"，秘书花的那几笔记成
    `secretary:B`（`vsigns.secretary_id` 的写法），不是名册外的角色。
    """
    role = str(value or "")
    if role.startswith("secretary:"):
        role = role.split(":", 1)[1]
    if role == MC.DEFAULT_ROLE:
        # `modelgw` 是 `modelcost.DEFAULT_ROLE`：不经任何角色的直呼（CLI / 网关）记在它名下，
        # 不是名册外的角色。
        return True
    return role in _TASK_ROLES


@_rule("usage_ledger", "vocab")
def _rule_ul_vocab(ctx: _Ctx) -> list[Finding]:
    """`scope` 与 `role` 走各自的词表。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        scope = str(row.get("scope") or "")
        if scope not in _UL_SCOPES:
            out.append(_local_finding(
                ctx, "usage_scope",
                f"`scope` 读到 {_shown(row.get('scope'))}，不在 {_UL_SCOPES} 里",
                row_no=n, field_name="scope"))
        if not _is_known_role(row.get("role")):
            out.append(_local_finding(
                ctx, "usage_role",
                f"`role` 读到 {_shown(row.get('role'))}，不在名册 {_TASK_ROLES} 里"
                "（秘书地址 `secretary:<角色>` 照认）",
                row_no=n, field_name="role", severity="warning"))
    return out


@_rule("usage_ledger", "idem")
def _rule_ul_idem(ctx: _Ctx) -> list[Finding]:
    """同一个幂等键不许两条（重复结算）。

    口径与 `scripts/usage_ledger_audit.py` 一致：键是 `idem-<12位十六进制>` 或
    `settle-<12位十六进制>`。那份脚本负责清洗存量，这里只报"有重复"。
    """
    out: list[Finding] = []
    pattern = re.compile(r"^(?:idem|settle)-[0-9a-f]{12}$")
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        key = str(row.get("idem_key") or "").strip()
        if not key:
            continue
        if not pattern.match(key):
            out.append(_local_finding(
                ctx, "usage_idem_key_shape",
                f"`idem_key` 读到 {_shown(key)}，既不是 idem- 也不是 settle- 加 12 位十六进制",
                row_no=n, field_name="idem_key", severity="warning"))
            continue
        if key in seen:
            out.append(_local_finding(
                ctx, "usage_duplicate_idem",
                f"`idem_key`={key!r} 与第 {seen[key]} 条重复 ⇒ 同一次调用结算了两笔",
                row_no=n, field_name="idem_key"))
        else:
            seen[key] = n
    return out


@_rule("usage_ledger", "call_index")
def _rule_ul_call_index(ctx: _Ctx) -> list[Finding]:
    """同一 (角色, 任务, 档) 的 `call_index` 必须是一段无洞、无重的连号。

    `call_index` 只在 `note` 里（`...call_index=<n>...`）。起点可以是 0 或 1
    （各档的计数器起点不同），所以判据是"从最小号码连续、不重复"，不是"必须从 0 起"。
    """
    out: list[Finding] = []
    pattern = re.compile(r"call_index=(\d+)")
    groups: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for n, row in ctx.rows:
        note = str(row.get("note") or "")
        matched = pattern.search(note)
        if not matched:
            continue
        key = (str(row.get("role") or ""), str(row.get("task_id") or ""),
               str(row.get("scope") or ""))
        groups.setdefault(key, []).append((int(matched.group(1)), n))
    for key, pairs in groups.items():
        nums = sorted(i for i, _ in pairs)
        want = list(range(nums[0], nums[0] + len(nums)))
        if nums == want:
            continue
        seen_at: dict[int, int] = {}
        for i, n in pairs:
            if i in seen_at:
                out.append(_local_finding(
                    ctx, "usage_call_index_duplicate",
                    f"{key} 的 `call_index`={i} 出现两次（第 {seen_at[i]} 行与第 {n} 行）",
                    row_no=n, field_name="note"))
            else:
                seen_at[i] = n
        missing = sorted(set(want) - set(nums))
        if missing:
            out.append(_local_finding(
                ctx, "usage_call_index_gap",
                f"{key} 的 `call_index` 缺号 {missing[:8]}（共 {len(nums)} 行，"
                f"最小 {nums[0]}、最大 {nums[-1]}）⇒ 要么漏记了一笔，要么记重了",
                severity="warning"))
    return out
