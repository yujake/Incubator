# -*- coding: utf-8 -*-
"""
acceptance 那一类：`out/paper/ACCEPTANCE-CHECKS.json` 的行形状与不适用理由。
"""

from __future__ import annotations

from typing import Mapping

from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- acceptance：`out/paper/ACCEPTANCE-CHECKS.json`


@_rule("acceptance", "shape")
def _rule_acc_shape(ctx: _Ctx) -> list[Finding]:
    """每一行的形状走 `closing._acceptance_row_problem`（那一处的唯一实现）。

    没有 `min` / `max` / `na` 的行不算畸形：收工门按档位的缺省阈值判它（`closing`
    的 `implicit_min`），"没写阈值"是合法写法。这里只把它记进 notes，让读的人知道
    那几行没有显式达标线。
    """
    from .. import closing as CL

    out: list[Finding] = []
    seen: set[str] = set()
    implicit = 0
    for n, row in ctx.rows:
        cid = str(row.get("id") or "")
        problem = CL._acceptance_row_problem(cid, row, seen)
        if problem:
            out.append(_local_finding(ctx, "acceptance_row_shape", problem, row_no=n))
            if cid:
                seen.add(cid)
            continue
        seen.add(cid)
        if row.get("na") is True and not str(row.get("note") or "").strip():
            out.append(_local_finding(
                ctx, "acceptance_na_without_reason",
                f"验收行 {cid} 标了 `na=true` 却没写 `note` ⇒ 不适用也要说清为什么不适用",
                row_no=n, field_name="note", severity="warning"))
        if row.get("na") is not True and "min" not in row and "max" not in row:
            implicit += 1
    if implicit:
        ctx.notes.append(
            f"其中 {implicit} 行没有显式 `min`/`max`（按档位缺省阈值判，合法写法）")
    return out
