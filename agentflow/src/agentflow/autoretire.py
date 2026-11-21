# -*- coding: utf-8 -*-
"""收工前自动收尾的只读判据：哪些静默的节点会被销掉。

## 为什么单独一个模块（ROOTGATE-③，2026-11-19）

同一份判据有两个读者，而它们一个写盘、一个不许写盘：

- ``agent_loop._auto_retire_ready``：``final`` 闸真的调 ``Secretary.retire`` 把它们销掉；
- ``closing.machine_feeders``：收工门只读（``check_closing`` 不写任何东西），
  但它要回答"收尾前自动收尾会销哪些、销完之后这一支干不干净"。

改前只有第一个读者有这份判据：``closing`` 的 retire 格读的是销号前的快照，
所以最后一次 closing 必写"retire 不干净"，而 38 秒后 final 闸自己把它清干净
（真机 ``projects/lp-ball-11``：18:20:40–43 销了 20 个）—— 读数与事实错位。
把"静默"这一条判据放在这里，两处读同一份，错位就没有了。

## 判据一个字都不放宽（RETIREFIX，2026-11-21）

只认 ``retire_ready`` 的 ``branch == "waiting_no_children"``。有一档例外，它把
"无未消项"拆成两种情形（``items_open == 0`` 或"名下只剩 ``expects="ack"`` 的通知"）：

- 真机 ``projects/lp-ball-15``：``t-000047`` / ``t-000122`` 都是静默、无活跃子，
  名下各挂 1 / 2 条 ``expects="ack"`` 的到点通知（收件人就是它们自己），而优雅停止
  已经把那三条翻成 ``block``（``stopctl.block_remaining_tasks``）—— ``block -> done``
  是状态机倒退，收件人自己都 ack 不动，那几条永远不会被收口。改前这条链互锁：
  自动收尾不碰它（``items_open != 0``），于是 final 闸永远报"retire 不干净"。
- 出口不是"把 ack 替它做掉"（父代 ack 被 ``conductor.ack`` 的 ``not_yours`` 拒），
  而是 ``conductor.void_items`` 那条既有的作废口：先把节点销掉，再把它名下那几条
  「只剩 ack、且已被框架自己翻成 block」的通知按"收件人已销号 ⇒ 叫不醒"作废
  （``void_items(revoke=False)`` 的 deaf 判据本来就要求"已销号 / 兜底表被永久抑制"）。
  作废留六格痕，可复核。
- 不放宽的四格：``expects=work`` 的交付项（``b-register@`` / ``v-resubmit@``）一条都
  不作废；``queued`` / ``seen`` 的通知（收件人还来得及 ack）一条都不作废 —— 业主
  「就做手，不兜底」说的正是这一档；根（M）自己名下的项不碰（``_item_authority``
  也不许 M 改 M 的项）；逐条读数缺一项就整节点不碰（fail-closed）。"整棵树干净"的
  定义一个字没动（``retire_integrity.complete`` 仍要求 ``nodes`` 与 ``dirty`` 都空）。

``plan_retire`` 额外做一步只读的闭包：一个 ``waiting_with_children`` 的父，在它那些
活跃子都在候选里时，子销完之后它也会就绪（``_auto_retire_ready`` 是靠"销一轮、再读
一轮"发现这件事的；这里不写盘，只能用闭包把同一件事算出来，轮数上限与
``_auto_retire_ready`` 同为 ``MAX_ROUNDS``）。
"""
from __future__ import annotations

from typing import Any, Mapping

#: 与 ``_auto_retire_ready`` 的循环上限同一档（防病态树 / 防闭包不收敛）。
MAX_ROUNDS = 6

#: 自动收尾唯一允许作废的未消项类型（要交付的活 ``work`` 一条都不许）。
VOIDABLE_EXPECTS = "ack"

#: 自动收尾唯一允许作废的 ``item_state``：``block`` 是「框架自己」在优雅停止时翻的那一档
#: （唯一写入点是 ``stopctl.block_remaining_tasks``）。为什么只认这一档：``block`` 之后
#: 连收件人都 ack 不动（``block -> done`` 是状态机倒退，``conductor.ack`` 报 ``state_error``）
#: ⇒ 这几条已经没有人能收口，是框架自己把路堵死的，收尾时当然由框架自己收拾。
#: 反过来，``queued`` / ``seen`` 的通知是"收件人还来得及 ack"的那一档（d68 的
#: ``conductor.ack`` 就是那只手）—— 那一档框架一个字节都不许替它收（业主「就做手，不兜底」）。
VOIDABLE_STATES: tuple[str, ...] = ("block",)


def voidable_items(info: Mapping[str, Any]) -> list[str]:
    """这一节点"销号之后可以作废"的未消项编号（不满足 ⇒ 空表）。

    四条 fail-closed（缺一条就整节点不碰 —— 只作废已知的那几条会把未知的留在板上，
    "清干净"就成了假读数）：

    1. ``branch == "waiting_no_children"``：它自己静默、名下没有活跃子（还在飞的不碰）；
    2. ``items_open_ids`` 的条数与 ``items_open`` 对得上（读不出逐条 = 不碰）；
    3. 逐条 ``expects == "ack"``（有一条是 ``work`` 就整节点不碰）；
    4. 逐条 ``item_state`` 都在 ``VOIDABLE_STATES``（框架在优雅停止时翻的 ``block``）——
       ``queued`` / ``seen`` 那一档是收件人还来得及 ack 的，不许框架替它收。
    """
    if str(info.get("branch") or "") != "waiting_no_children":
        return []
    open_n = int(info.get("items_open") or 0)
    ids = [str(x) for x in (info.get("items_open_ids") or []) if str(x)]
    expects = dict(info.get("items_open_expects") or {})
    states = dict(info.get("items_open_states") or {})
    if open_n <= 0 or len(ids) != open_n:
        return []
    if any(str(expects.get(i) or "") != VOIDABLE_EXPECTS for i in ids):
        return []
    if any(str(states.get(i) or "") not in VOIDABLE_STATES for i in ids):
        return []
    return ids


def dirty_voidables(cell: Mapping[str, Any]) -> list[str]:
    """已经销号、可名下还有未消项的节点（``retire_integrity.dirty`` 那一档）里能只作废的那几条。

    为什么需要它（RETIREFIX 复算，真机 lp-ball-15）：一个名册名可以绑多个台账号
    （复用），按其中一个号销号就同时销掉全部绑过的号 —— 那几笔的 ack 通知不会经过
    "逐个节点"那一轮，于是它们是"已销号 + 名下还有 block 通知"（``dirty``）。这一档
    不需要再销号，只需要把作废口走一遍，否则 ``retire_integrity`` 永远算 dirty。

    判据与 :func:`voidable_items` 同源：``open_items`` 与 ``open_item_ids`` 对得上、
    逐条 ``expects == "ack"``、逐条 ``item_state`` 都在 ``VOIDABLE_STATES``。
    """
    open_n = int(cell.get("open_items") or 0)
    ids = [str(x) for x in (cell.get("open_item_ids") or []) if str(x)]
    expects = dict(cell.get("open_item_expects") or {})
    states = dict(cell.get("open_item_states") or {})
    if open_n <= 0 or len(ids) != open_n:
        return []
    if any(str(expects.get(i) or "") != VOIDABLE_EXPECTS for i in ids):
        return []
    if any(str(states.get(i) or "") not in VOIDABLE_STATES for i in ids):
        return []
    return ids


def ready_now(cond: Any, root: str, order: list[str]) -> dict[str, Any]:
    """当前这一拍真的可销的节点（逐父读 ``retire_ready``，只读）。

    返回 ``{"checked", "ready": {task_id: {task_id, owner, role}}, "info": {...},
    "problems": []}``。``info`` 是每个被读过就绪读数的节点（不只候选）——
    ``plan_retire`` 的闭包要用它的 ``branch`` / ``items_open`` / 逐条 ``expects``。
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
                    "items_open_ids": [str(x) for x in (reading.get("items_open_ids") or [])],
                    "items_open_expects": {str(k): str(v) for k, v in
                                           dict(reading.get("items_open_expects") or {}).items()},
                    "items_open_states": {str(k): str(v) for k, v in
                                          dict(reading.get("items_open_states") or {}).items()},
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
    """只读投影：收尾前自动收尾会销哪些、作废哪些、留哪些、销完这一支干不干净。

    ``retire`` 是 ``retire_integrity`` 的读数（用来知道"还在册的节点"是哪些）。
    返回 ``{"checked", "would_retire": [task_id…], "would_void": [{task_id, item_ids}…],
    "kept": [{task_id, why}…], "problems": [], "reason": "", "projected_complete": bool}``。
    """
    out: dict[str, Any] = {"checked": False, "would_retire": [], "would_void": [],
                           "kept": [], "problems": [], "reason": "",
                           "projected_complete": False}
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
    # 没有作废口 ⇒ "只剩 ack" 那一档投影不出来（留给 M 自己按拒信处置；不折成
    # "没有可销的"，也不把它写成"没查成" —— 这一档是"这一版 conductor 没接那一口"）。
    can_void = callable(getattr(cond, "void_items", None))
    kids = _children_map(order, parent_of)
    # 候选 = 无未消项的静默节点 ＋ 名下只剩 ack 通知的静默节点（销号后作废那几条）。
    cand: set[str] = {tid for tid, one in info.items()
                      if one["branch"] == "waiting_no_children" and one["items_open"] == 0}
    void_plan: dict[str, list[str]] = {}
    for tid in roster:
        one = info.get(tid)
        if not one or one["branch"] != "waiting_no_children" or one["items_open"] == 0:
            continue
        ids = voidable_items(one) if can_void else []
        if ids:
            cand.add(tid)
            void_plan[tid] = ids
    for _round in range(MAX_ROUNDS):
        added = False
        for tid in roster:
            if tid in cand:
                continue
            one = info.get(tid)
            if not one:
                continue
            ids = voidable_items(one) if can_void else []
            if one["items_open"] != 0 and not ids:
                continue
            if one["branch"] == "waiting_no_children":
                cand.add(tid)
                if ids:
                    void_plan[tid] = ids
                added = True
            elif one["branch"] == "waiting_with_children":
                left = [c for c in kids.get(tid, ()) if c in roster and c not in cand]
                if not left:
                    cand.add(tid)
                    if ids:
                        void_plan[tid] = ids
                    added = True
        if not added:
            break
    index = {tid: i for i, tid in enumerate(order)}
    out["would_retire"] = sorted(cand, key=lambda t: (index.get(t, 10 ** 6), t))
    # 已销号但名下还有未消项的（`retire_integrity.dirty`）：那一档不用再销号，只用作废。
    dirty_plan: dict[str, list[str]] = {}
    dirty_left: list[dict[str, str]] = []
    for cell in (snapshot.get("dirty") or []):
        tid = str(cell.get("task_id") or "")
        ids = dirty_voidables(cell) if can_void else []
        if ids:
            dirty_plan[tid] = ids
        elif tid:
            dirty_left.append({"task_id": tid, "why": (
                f"已经销号，可名下还有 {int(cell.get('open_items') or 0)} 条未消项"
                "（不是「已被停止翻成 block 的 ack 通知」⇒ 不许自动作废）")})
    out["would_void"] = [{"task_id": tid, "item_ids": list(void_plan[tid])}
                         for tid in out["would_retire"] if tid in void_plan]
    out["would_void"].extend({"task_id": tid, "item_ids": list(ids), "retired": True}
                             for tid, ids in dirty_plan.items())
    out["kept"] = [{"task_id": tid, "why": _kept_why(info.get(tid) or {})}
                   for tid in roster if tid not in cand] + dirty_left
    out["checked"] = not out["problems"]
    out["projected_complete"] = bool(
        out["checked"] and not out["kept"] and not dirty_left)
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
    - 不干净但所有还在册的节点都是候选（含"销号后作废 ack 通知"那一档）、且没有
      ``dirty`` ⇒ ``complete=True`` + ``projected=True``，并逐条写明"会销哪些、
      会作废哪几条"；
    - 有未消项（且不是只剩 ack 通知）/ 还在飞 / 读不成 ⇒ ``complete=False`` + 逐条
      点名（反真空：不许把"还有未消项"投影成干净）。
    """
    base = dict(retire) if isinstance(retire, Mapping) else {}
    if not base.get("checked"):
        base.setdefault("projected", False)
        return base
    if base.get("complete"):
        base.update(projected=False, complete_before_auto_retire=True,
                    auto_retire={"checked": True, "would_retire": [], "would_void": [],
                                 "kept": [],
                                 "problems": [], "reason": "这一支已经干净，无需自动收尾"})
        return base
    plan = plan_retire(cond, root, base)
    auto = {"checked": bool(plan.get("checked")),
            "would_retire": list(plan.get("would_retire") or []),
            "would_void": list(plan.get("would_void") or []),
            "kept": list(plan.get("kept") or []),
            "problems": list(plan.get("problems") or []),
            "reason": str(plan.get("reason") or "")}
    base["complete_before_auto_retire"] = False
    base["projected"] = bool(plan.get("projected_complete"))
    base["auto_retire"] = auto
    void_n = sum(len(x.get("item_ids") or []) for x in auto["would_void"])
    void_text = ("，并把 "
                 + "、".join(f"{x['task_id']} 名下的 {len(x['item_ids'])} 条 ack 通知"
                            for x in auto["would_void"][:6])
                 + " 作废（收件人已销号 ⇒ 叫不醒）") if auto["would_void"] else ""
    if base["projected"]:
        base["complete"] = True
        base["reason"] = (
            "收尾前自动收尾会销掉这些静默的节点："
            + "、".join(auto["would_retire"][:8])
            + (f" 等 {len(auto['would_retire'])} 个" if len(auto["would_retire"]) > 8 else "")
            + void_text + (f"（共 {void_n} 条）" if void_n else "")
            + " ⇒ 销完之后这一支就干净了（这是只读投影，真正销号在 final 闸）")
    else:
        base["complete"] = False
        base["reason"] = ("retire 不干净：" + str(plan.get("reason") or "还有节点没销"))
    return base
