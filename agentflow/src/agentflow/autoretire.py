# -*- coding: utf-8 -*-
"""收工前自动收尾的只读判据：哪些静默且无未消项的节点会被销掉。

## 为什么单独一个模块（ROOTGATE-③，2026-11-19）

同一份判据有两个读者，而它们一个写盘、一个不许写盘：

- ``agent_loop._auto_retire_ready``：``final`` 闸真的调 ``Secretary.retire`` 把它们销掉；
- ``closing.machine_feeders``：收工门只读（``check_closing`` 不写任何东西），
  但它要回答"收尾前自动收尾会销哪些、销完之后这一支干不干净"。

改前只有第一个读者有这份判据：``closing`` 的 retire 格读的是销号前的快照，
所以最后一次 closing 必写"retire 不干净"，而 38 秒后 final 闸自己把它清干净
（真机 ``projects/lp-ball-11``：18:20:40–43 销了 20 个）—— 读数与事实错位。
把"静默且无未消项"这一条判据放在这里，两处读同一份，错位就没有了。

## 判据一个字都不放宽

只认 ``retire_ready`` 的 ``branch == "waiting_no_children"`` 且 ``items_open == 0``
（与 ``_auto_retire_ready`` 的循环逐字同源）。有未消项 / 还在飞 / 待机 / 有活跃子 /
读不到 —— 一律不碰。``plan_retire`` 额外做一步只读的闭包：一个
``waiting_with_children`` 的父，在它那些活跃子都在候选里时，子销完之后它也会就绪
（``_auto_retire_ready`` 是靠"销一轮、再读一轮"发现这件事的；这里不写盘，只能用闭包
把同一件事算出来，轮数上限与 ``_auto_retire_ready`` 同为 ``MAX_ROUNDS``）。
"""
from __future__ import annotations

from typing import Any, Mapping

#: 与 ``_auto_retire_ready`` 的循环上限同一档（防病态树 / 防闭包不收敛）。
MAX_ROUNDS = 6


def ready_now(cond: Any, root: str, order: list[str]) -> dict[str, Any]:
    """当前这一拍真的可销的节点（逐父读 ``retire_ready``，只读）。

    返回 ``{"checked", "ready": {task_id: {task_id, owner, role}}, "info": {...},
    "problems": []}``。``info`` 是每个被读过就绪读数的节点（不只候选）——
    ``plan_retire`` 的闭包要用它的 ``branch`` / ``items_open``。
    """
    out: dict[str, Any] = {"checked": True, "ready": {}, "info": {},
                           "problems": []}
    parents = [str(root)] + [str(t) for t in order if str(t) and str(t) != str(root)]
    for pid in parents:
        try:
            got = cond.retire_ready(pid)
        except Exception as exc:  # noqa: BLE001 —— 一层读不成不许带走其余
            out["problems"].append(f"{pid} 的就绪读数没查成（{type(exc).__name__}: {exc}）")
            continue
        if not got.get("checked"):
            out["problems"].append(f"{pid} 的就绪读数没查成（{got.get('reason')}）")
            continue
        for item in got.get("ready") or []:
            tid = str(item.get("task_id") or "")
            if not tid:
                continue
            reading = dict(item.get("reading") or {})
            info = {"branch": str(item.get("branch") or ""),
                    "items_open": int(reading.get("items_open") or 0),
                    "owner": str(pid), "role": str(item.get("role") or "")}
            # 同一节点只应出现在它父的那一次读数里；重复时保留第一次（确定性）。
            out["info"].setdefault(tid, info)
            if info["branch"] == "waiting_no_children" and info["items_open"] == 0:
                out["ready"][tid] = {"task_id": tid, "owner": info["owner"],
                                     "role": info["role"]}
    return out


def _children_map(order: list[str], parent_of: Mapping[str, str]) -> dict[str, list[str]]:
    kids: dict[str, list[str]] = {}
    for tid in order:
        pid = str(parent_of.get(tid) or "")
        if pid:
            kids.setdefault(pid, []).append(tid)
    return kids


def _kept_why(info: Mapping[str, Any]) -> str:
    branch = str(info.get("branch") or "")
    if int(info.get("items_open") or 0) > 0:
        return f"名下还有 {int(info['items_open'])} 条未消项"
    if branch == "active":
        return "它自己还在跑"
    if branch == "waiting_with_children":
        return "名下还有没销的子代理"
    if not branch:
        return "就绪读数里没有这一项"
    return f"branch={branch}（不是静默且无未消项）"


def plan_retire(cond: Any, root: str, retire: Mapping[str, Any] | None = None
                ) -> dict[str, Any]:
    """只读投影：收尾前自动收尾会销哪些、留哪些、销完这一支干不干净。

    ``retire`` 是 ``retire_integrity`` 的读数（用来知道"还在册的节点"是哪些）。
    返回 ``{"checked", "would_retire": [task_id…], "kept": [{task_id, why}…],
    "problems": [], "reason": "", "projected_complete": bool}``。
    """
    out: dict[str, Any] = {"checked": False, "would_retire": [], "kept": [],
                           "problems": [], "reason": "", "projected_complete": False}
    snapshot = dict(retire) if isinstance(retire, Mapping) else {}
    if not snapshot.get("checked"):
        out["reason"] = ("retire_integrity 自己没查成 ⇒ 收尾前自动收尾会销哪些也算不出来"
                         "（不是「没有可销的」）")
        return out
    try:
        got_order = cond.subtree_postorder(root)
    except Exception as exc:  # noqa: BLE001 —— 读不到就留给 M，不猜
        out["reason"] = f"子树次序读不成（{type(exc).__name__}: {exc}）"
        return out
    if not got_order.get("checked"):
        out["reason"] = f"子树次序没查成（{got_order.get('reason')}）"
        return out
    order = [str(t) for t in (got_order.get("order") or []) if str(t)]
    parent_of = dict(got_order.get("parent_of") or {})
    roster = [str(n.get("task_id") or "") for n in (snapshot.get("nodes") or [])
              if str(n.get("task_id") or "")]
    now = ready_now(cond, root, order)
    out["problems"] = list(now["problems"])
    info = dict(now["info"])
    kids = _children_map(order, parent_of)
    # 闭包：先叶子、后父。``waiting_with_children`` 的父只有在它那些还在册的子
    # 全都在候选里时才会在子销完之后就绪。
    cand: set[str] = {tid for tid, one in info.items()
                      if one["branch"] == "waiting_no_children" and one["items_open"] == 0}
    for _round in range(MAX_ROUNDS):
        added = False
        for tid in roster:
            if tid in cand:
                continue
            one = info.get(tid)
            if not one or one["items_open"] != 0:
                continue
            if one["branch"] == "waiting_no_children":
                cand.add(tid)
                added = True
            elif one["branch"] == "waiting_with_children":
                left = [c for c in kids.get(tid, ()) if c in roster and c not in cand]
                if not left:
                    cand.add(tid)
                    added = True
        if not added:
            break
    index = {tid: i for i, tid in enumerate(order)}
    out["would_retire"] = sorted(cand, key=lambda t: (index.get(t, 10 ** 6), t))
    out["kept"] = [{"task_id": tid, "why": _kept_why(info.get(tid) or {})}
                   for tid in roster if tid not in cand]
    out["checked"] = not out["problems"]
    out["projected_complete"] = bool(
        out["checked"] and not out["kept"] and not (snapshot.get("dirty") or []))
    if not out["checked"]:
        out["reason"] = "；".join(out["problems"][:3])
    elif not out["projected_complete"]:
        out["reason"] = ("收尾前自动收尾之后 retire 仍不干净："
                         + "、".join(f"{k['task_id']}（{k['why']}）"
                                    for k in out["kept"][:6])
                         + (f" 等 {len(out['kept'])} 个" if len(out["kept"]) > 6 else ""))
    return out


def project_retire(cond: Any, root: str,
                   retire: Mapping[str, Any] | None) -> dict[str, Any]:
    """把 ``retire_integrity`` 的读数换成"收尾前自动收尾之后"的那一份（只读）。

    - 已经干净 ⇒ 原样返回，``projected=False``（不需要投影）；
    - 不干净但所有还在册的节点都是候选、且没有 ``dirty`` ⇒ ``complete=True`` +
      ``projected=True``，并逐条写明"会销哪些"；
    - 有未消项 / 还在飞 / 读不成 ⇒ ``complete=False`` + 逐条点名（反真空：不许把
      "还有未消项"投影成干净）。
    """
    base = dict(retire) if isinstance(retire, Mapping) else {}
    if not base.get("checked"):
        base.setdefault("projected", False)
        return base
    if base.get("complete"):
        base.update(projected=False, complete_before_auto_retire=True,
                    auto_retire={"checked": True, "would_retire": [], "kept": [],
                                 "problems": [], "reason": "这一支已经干净，无需自动收尾"})
        return base
    plan = plan_retire(cond, root, base)
    auto = {"checked": bool(plan.get("checked")),
            "would_retire": list(plan.get("would_retire") or []),
            "kept": list(plan.get("kept") or []),
            "problems": list(plan.get("problems") or []),
            "reason": str(plan.get("reason") or "")}
    base["complete_before_auto_retire"] = False
    base["projected"] = bool(plan.get("projected_complete"))
    base["auto_retire"] = auto
    if base["projected"]:
        base["complete"] = True
        base["reason"] = (
            "收尾前自动收尾会销掉这些静默且无未消项的节点："
            + "、".join(auto["would_retire"][:8])
            + (f" 等 {len(auto['would_retire'])} 个" if len(auto["would_retire"]) > 8 else "")
            + " ⇒ 销完之后这一支就干净了（这是只读投影，真正销号在 final 闸）")
    else:
        base["complete"] = False
        base["reason"] = ("retire 不干净：" + str(plan.get("reason") or "还有节点没销"))
    return base
