# -*- coding: utf-8 -*-
"""F 的「已登记、还没送 V」的稿：两处读数共用的唯一扫描（INV7）。

## 这一格修的是什么（`agentflow/temp/inv7/INV7-REPORT.md`，`projects/lp-ball-7`）

F 在 10:02:18 已经把 `reports/f-proof-000001.md` 登记进盘（稿头有正文 sha /
命题指纹 / 版本行 ⇒ `proofregistry.parse_entry` 认它是登记条目），`v_sign` 那一格
也如实读成 `unsigned`（「这一份正文还没有一份能算数的签」）。可同一拍的
`delivery` 却读成 `total=0` / `proof_count=0` / `still_unsubmitted=[]` /
`researched_no_output` —— 于是 10:07:19 与 10:12:20 两次 `agent_park` 都判
`pending_work=false`，F 没有拿到任何模型回合去执行「下一步：派 V」。

根因不是两个读数各自算错，而是「成果的身份只认 `statements` 行」：B 的收录在
V 签之后，所以一份「已登记、等签」的稿在 `history` 里没有 `statement_id`，
`delivery.outputs_of` 数不到它；而 `v_sign` 读的是手稿 × 签的颁发表，两处口径
分家。本模块把「盘上已登记的 F 稿」收成一份可复用的扫描，`delivery` 与挂机判据
都从它取数 —— 一处分家就两处一起红（判据
`tests/test_f_registered_unsigned_is_pending.py` 的 e 条）。

## 判据

- 已登记：`proofregistry.parse_entry(text)["checked"]`（稿头有正文 sha /
  命题指纹 / 版本行之一）。没有登记元信息的草稿（真机 `f-proof-000000.md`）
  不算 —— 它不是「等签」，是「还没登记」；
- 未签：`vsign.delivery_reading` 的四档里不是 `signed`。`waiting` 是「等签」
  （含真的还没送审）；`rejected` 是 V 判过没过；`unknown` 是签那一格没查成 ——
  三档都需要 F 的动作，所以都进待办（三态纪律：不把「没查成」折成「没事」）；
- 纯读：只列 `reports/`、只算 sha、只读签；一个字节都不写盘。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

#: 本模块只服务 F 的证明稿（B 的 `b-proof-*` 有它自己的送审路径）。
FAMILY = "F"

#: 交付/待办读数里一条「稿」的身份前缀（命题号的身份前缀是 `stmt:`；两者不混）。
MANUSCRIPT_OUTPUT_PREFIX = "mss:"


def _empty(why: str = "") -> dict[str, Any]:
    return {"checked": True, "count": 0, "items": [], "rows": [],
            "problems": [], "why": why}


def scan_registered(root: Any, *, family: str = FAMILY) -> dict[str, Any]:
    """扫 `reports/` 下这一族的稿，只留「已登记」的那些（纯读）。

    返回 `{checked, rows, problems, why}`。`rows` 每项：
    `{manuscript_id, manuscript, text, entry, label}`。
    `checked=False` 只表示目录列不出来（「没查成」）；单份稿读不出来进 `problems`，
    不冒充「这一份不存在」。
    """
    from .. import manuscriptform as _MF
    from .. import proofregistry as _PR
    from .. import vsigns as _VS

    out = _empty()
    base = Path(str(root or "")) / _MF.MANUSCRIPT_DIR
    if not str(root or "").strip():
        out.update(checked=False, why="没有工作区根 ⇒ 已登记稿这一格没查成（不是「没有稿」）")
        return out
    prefix = str(_MF.PREFIX.get(str(family or ""), ""))
    if not prefix:
        out.update(checked=False, why=f"稿族 {family!r} 没有前缀 ⇒ 这一格没查成")
        return out
    try:
        paths = sorted(base.glob(f"{prefix}*.md")) if base.is_dir() else []
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 没查成
        out.update(checked=False,
                   why=(f"`{_MF.MANUSCRIPT_DIR}/` 列不出来（{type(exc).__name__}: {exc}）"
                        " ⇒ 已登记稿这一格没查成（不是「一份都没有」）"))
        return out
    rows: list[dict[str, Any]] = []
    for path in paths:
        rel = f"{_MF.MANUSCRIPT_DIR}/{path.name}"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out["problems"].append(
                f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一份这次没查成")
            continue
        entry = dict(_PR.parse_entry(text) or {})
        if not bool(entry.get("checked")):
            continue          # 草稿（无登记元信息）：不是「等签」，是「还没登记」
        parsed = dict(_VS.parse_manuscript_name(rel) or {})
        mid = str(parsed.get("manuscript_id") or entry.get("manuscript_id") or "")
        rows.append({"manuscript_id": mid, "manuscript": rel, "text": text,
                     "entry": entry, "label": str(entry.get("label") or "")})
    out["rows"] = rows
    out["why"] = (f"`{_MF.MANUSCRIPT_DIR}/` 下 {len(paths)} 份 {prefix}*.md 里有 "
                  f"{len(rows)} 份带登记元信息")
    return out


def summon_action(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一份稿「下一步」的可执行动作（summon 形状：`role="V"` + 要审的稿路径）。

    真机 step 8 的 tool result 里只有一句「下一步：派 V 审这一份」；F 想在
    `self_assessment` 里写同一件事又被封闭参数表拒掉。这一格把「下一步」变成
    结构化的动作读数（不是替它派，派活仍是 F 自己的动作）。
    """
    rel = str(row.get("manuscript") or "")
    mid = str(row.get("manuscript_id") or "")
    sha = str(row.get("sha") or row.get("sha256") or "")
    tail = (f"（稿号 {mid}，正文 sha {sha[:12]}…）" if mid else "")
    return {
        "tool": "framework_summon",
        "shape": "summon",
        "role": "V",
        "task": (f"审这一份证明稿 {rel}{tail}：判它成立/不成立，"
                 "给出逐条 findings 与结论；拿到签才算 F 这一趟交差"),
        "manuscript": rel,
        "manuscript_id": mid,
    }


def manuscript_reading(root: Any, row: Mapping[str, Any], *,
                       reading: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """一份已登记稿的 V 签读数（四档；`reading` 给了就复用，不重复读盘）。"""
    from .. import proofregistry as _PR
    from . import vsign as _VS

    got = dict(reading or {})
    rel = str(row.get("manuscript") or "")
    if not got:
        try:
            got = dict(_VS.delivery_reading(
                root, statement_id="", proof_text=str(row.get("text") or ""),
                manuscript_paths=(rel,) if rel else ()))
        except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」，不是「没签」
            got = {"state": _VS.STATE_UNKNOWN, "label": "没查成",
                   "delivered": False, "checked": False,
                   "why": f"读签这一格没跑成（{type(exc).__name__}: {exc}）"}
    state = str(got.get("state") or _VS.STATE_UNKNOWN)
    entry = dict(row.get("entry") or {})
    sha = str(got.get("sha") or entry.get("sha256") or "")
    if not sha:
        try:
            sha = _PR.proof_sha(str(row.get("text") or ""))
        except Exception:  # noqa: BLE001 —— sha 只是读数，算不出来不带走结论
            sha = ""
    out = {
        "manuscript_id": str(row.get("manuscript_id") or ""),
        "manuscript": rel,
        "label": str(row.get("label") or ""),
        "sha": sha,
        "state": state,
        "state_label": str(got.get("label") or ""),
        "signed": bool(got.get("delivered")),
        "checked": bool(got.get("checked", True)),
        "why": str(got.get("why") or ""),
    }
    out["next_action"] = summon_action(out)
    return out


def unsubmitted_reading(root: Any) -> dict[str, Any]:
    """已登记、V 签还没到的稿（`count` > 0 ⇒ 这一拍有活）。

    返回 `{checked, count, items, rows, problems, why}`；`items` 每项是
    :func:`manuscript_reading` 的那一格（带 `next_action`）。
    """
    scan = scan_registered(root)
    out = {"checked": bool(scan.get("checked")), "count": 0, "items": [],
           "rows": list(scan.get("rows") or []),
           "problems": list(scan.get("problems") or []), "why": ""}
    items: list[dict[str, Any]] = []
    for row in out["rows"]:
        got = manuscript_reading(root, row)
        if got.get("signed"):
            continue
        items.append(got)
    out["items"] = items
    out["count"] = len(items)
    if not out["checked"]:
        out["why"] = str(scan.get("why") or "已登记稿这一格没查成（不是「没有稿」）")
    elif items:
        out["why"] = (f"名下 {len(items)} 份已登记、V 签还没到的稿："
                      + "、".join(f"{x['manuscript']}（{x['state_label'] or x['state']}）"
                                 for x in items[:6]))
    else:
        out["why"] = str(scan.get("why") or "名下没有「已登记、V 签还没到」的稿")
    return out
