# -*- coding: utf-8 -*-
"""手稿族的产出方读数。

事实来源只有手稿路径的族前缀；父名单从 `capabilities.ALLOWED_EDGES` 现算
（形状是 `dict[str, frozenset[str]]`，不是 `list[tuple]`）。本模块不做写盘、
不读台账 —— 写行那一侧是 `verifications._producer_cells`。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import manuscriptfamily as _MFAM

#: 稿族 ⇒ 产出方角色（唯一一张映射表；事实来源仍是路径族，不是调用方自报）。
PRODUCER_OF_FAMILY: dict[str, str] = {
    "f-proof": "F",
    "b-proof": "B",
    "e-proof": "E",
    "e-num": "E",
    # 2026-11-27（MSOWN）：A 的汇报稿与 C 的分析稿各有产出角色（保留表的族名矩阵要用它们）。
    "a-report": "A",
    "c-analysis": "C",
    "d-research": "D",
}

UNKNOWN = "unknown"


# --------------------------------------------------------------------- 产出方
def parents_of(child_role: str) -> dict[str, Any]:
    """`child_role` 的父名单：从 `capabilities.ALLOWED_EDGES` 现算（不写死字面量）。

    返回 `{checked, parents, source, why}`。`checked=False` = edges 读不出来
    （那一档不许当成「没有父」）。值容器逐项 `in` 判，`frozenset` / `list` / `tuple`
    都吃 —— 形状本身由 capabilities 决定，本函数不抄一份类型断言。
    """
    out: dict[str, Any] = {"checked": False, "parents": [], "source": "",
                           "why": ""}
    try:
        from . import capabilities as _CAP

        edges = getattr(_CAP, "ALLOWED_EDGES", None)
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实说
        out["why"] = f"`capabilities.ALLOWED_EDGES` 读不出来（{type(exc).__name__}: {exc}）"
        return out
    if not isinstance(edges, Mapping):
        out["why"] = ("`capabilities.ALLOWED_EDGES` 不是映射（"
                      f"{type(edges).__name__}）⇒ 父名单判不了")
        return out
    role = str(child_role or "").strip()
    parents = sorted(str(frm) for frm, tos in edges.items()
                     if role and _contains(tos, role))
    out.update(checked=True, parents=parents,
               source="capabilities.ALLOWED_EDGES",
               why=("" if parents else f"`{role}` 没有任何入边（不是「父名单读不成」）"))
    return out


def _contains(container: Any, value: str) -> bool:
    try:
        return value in container
    except TypeError:  # 坏形状：当成不包含（调用方另有 checked 读数）
        return False


def producer_of(rel: Any, *, roster_role: str = "", child_role: str = "") -> dict[str, Any]:
    """手稿路径 ⇒ 产出方读数（事实来源只有路径的族前缀）。

    `roster_role` 只作对账（V 的秘书从名册读到的父角色）：它与路径族不一致时
    记 `roster_mismatch=True`，但 `producer_role` 永远取路径那一份 —— 调用方 /
    模型自报不能改写事实。

    返回键：`producer_role` / `producer_code` / `family` / `tier` / `manuscript_id` /
    `checked` / `roster_role` / `roster_mismatch` / `in_parent_roster` / `parents` /
    `why` / `problem`。
    """
    raw = str(rel or "").strip().replace("\\", "/")
    out: dict[str, Any] = {
        "producer_role": UNKNOWN, "producer_code": "", "family": "", "tier": "",
        "manuscript_id": "", "checked": False, "roster_role": str(roster_role or ""),
        "roster_mismatch": False, "in_parent_roster": False, "parents": [],
        "why": "", "problem": "",
    }
    if not raw:
        out["why"] = "没有手稿路径 ⇒ 产出方判不了（不是「产出方是 F」）"
        out["problem"] = "no_manuscript_path"
        return _with_parent_check(out, child_role)
    reading = _MFAM.classify_manuscript(raw)
    tier = str(reading.get("tier") or "")
    family = str(reading.get("family") or "")
    out.update(family=family, tier=tier,
               manuscript_id=str(reading.get("manuscript_id") or ""))
    if tier == _MFAM.TIER_FAMILY and family in PRODUCER_OF_FAMILY:
        out.update(producer_role=PRODUCER_OF_FAMILY[family], checked=True,
                   why=f"`{raw}` 的族是 {family} ⇒ 产出方 {PRODUCER_OF_FAMILY[family]}")
    else:
        out.update(producer_role=UNKNOWN, checked=False, problem=str(
            reading.get("code") or "family_unrecognized"),
            why=(f"`{raw}` 认不出生产族（tier={tier or '?'}，family={family or '?'}）⇒ "
                 "产出方记 unknown，不猜一个角色"))
    hint = str(roster_role or "").strip()
    if hint and out["producer_role"] != UNKNOWN and hint != out["producer_role"]:
        out["roster_mismatch"] = True
        out["why"] += (f"；名册里的父角色是 {hint}，与路径族不一致 ⇒ "
                       "以路径族为准（自报不改写事实）")
    return _with_parent_check(out, child_role)


def _with_parent_check(out: dict[str, Any], child_role: str) -> dict[str, Any]:
    role = str(child_role or "").strip()
    if not role:
        return out
    got = parents_of(role)
    out["parents"] = list(got.get("parents") or [])
    out["parent_check_checked"] = bool(got.get("checked"))
    producer = str(out.get("producer_role") or "")
    out["in_parent_roster"] = bool(
        got.get("checked") and producer and producer != UNKNOWN
        and producer in (got.get("parents") or []))
    if not got.get("checked"):
        out["why"] += "；父名单没读成（这一格不是「不在名单里」）"
    elif producer and producer != UNKNOWN and not out["in_parent_roster"]:
        out["problem"] = out.get("problem") or "producer_not_a_parent"
        out["why"] += (f"；产出方 {producer} 不在 `{role}` 的父名单 "
                       f"{out['parents']} 里 ⇒ 这一格对不上")
    return out


def verification_producer_reading(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """读一条验证行的产出方格（老行没有这一格 ⇒ 三态的第一态 `unknown`）。"""
    doc = dict(row or {})
    role = str(doc.get("producer_role") or "").strip()
    code = str(doc.get("producer_code") or "").strip()
    if not role:
        return {"checked": False, "producer_role": UNKNOWN, "producer_code": "",
                "why": ("老行没有 `producer_role` 这一格 ⇒ 产出方 unknown"
                        "（不是「产出方是 F / B / E」，也不硬填一个）")}
    if role == UNKNOWN:
        return {"checked": False, "producer_role": UNKNOWN, "producer_code": code,
                "why": str(doc.get("producer_problem") or doc.get("producer_why")
                           or "这一行写了 unknown：路径族认不出 ⇒ 不猜")}
    return {"checked": True, "producer_role": role, "producer_code": code,
            "why": str(doc.get("producer_problem") or "")}




def _manuscript_id_of(rel: str) -> str:
    return str(_MFAM.classify_manuscript(rel).get("manuscript_id") or "")



