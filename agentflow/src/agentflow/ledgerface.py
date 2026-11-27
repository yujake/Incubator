# -*- coding: utf-8 -*-
"""台账索引的"面"：依赖面 / 被引面 / 局部树展开（`ledgerindex.py` 的另一半）。

## 为什么拆开

`ledgerindex.py` 做的是两件不同的事：建索引（把两条表读成节点表 + 双向邻接，只读、
一次）与按面读（依赖面 / 被引面 / `expand` 的局部树）。前者是数据的家，后者是"从索引
里看出去"的几种读法 —— 拆成两个模块，各自只回答一件事；索引对象仍是
`ledgerindex.LedgerIndex`（本模块不定义第二个索引、也不建第二份邻接）。

## 口径不变

所有函数都是 `index` 的第一人称读法：入参是一个已建好的 `LedgerIndex`，行为、返回
形状、有界（深度 / 节点 / 字符）与增量账逐字保持原样。
`LedgerIndex.dependency_face` / `cited_face` / `expand` 仍存在，转发到本模块。
"""
from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from . import evidencebits as EB
from .ledgerindex import (
    DEFAULT_PROOF_NO,
    MAX_CHARS,
    MAX_FACE_CHAINS,
    MAX_FACE_DEPTH,
    MAX_NODES,
    _delivered_add,
    _delivered_get,
    _group_label,
)


# ---------------------------------------------------------------- 依赖面（全路径 + 分组）

def dependency_face(index: Any, stmt_id: Any, *,
                    max_chains: int = MAX_FACE_CHAINS,
                    max_depth: int = MAX_FACE_DEPTH) -> dict[str, Any]:
    """一条命题的依赖面：向上到根的全路径，按 `(path_no, path_group)` 分组。

    组内每条链回答三件事：路上经过哪几条命题（`chain`）、每一跳引在哪一步
    （`steps[i].used_at`）、终点是不是根（`root`）；走不到根 ⇒ `status="broken"`
    + `break_at`（断在哪条边、为什么）。不许静默少给几层。
    """
    sid = index.normalize_stmt_id(stmt_id)
    out: dict[str, Any] = {
        "checked": True, "groups": [], "root_kind": "", "root": {},
        "truncated": False, "reasons": [], "why": "",
    }
    node = index.nodes.get(sid)
    if node is None:
        out.update(checked=False,
                   why="台账里没有这一条 ⇒ 依赖面没查成（不是「它没有依赖」）")
        return out
    edges = index.up_edges(sid)
    if not edges:
        is_concept = str(node.get("kind") or "") == "concept"
        root_kind = "primitive_concept" if is_concept else "no_premise"
        out.update(root_kind=root_kind,
                   root={"kind": root_kind, "id": f"stmt:{sid}",
                         "label": node.get("label", "")},
                   why=("台账里没有一条依赖边指向它（概念行）⇒ 按原始概念读；"
                        "「没有边」不等于「它没有关系」—— 命题不引概念时这一面就是空的。"
                        if is_concept else
                        "台账里没有一条依赖边指向它 ⇒ 按无前提（自足）读；"
                        "但「没有依赖边」不等于「证明没用别人」—— 依赖面是录入时写下的。"))
        return out
    grouped: dict[tuple[int, int], list[dict]] = {}
    for edge in edges:
        grouped.setdefault((int(edge["path_no"]), int(edge["path_group"])),
                           []).append(edge)
    for key in sorted(grouped):
        group = {
            "group": _group_label(key), "proof_no": key[0], "path_group": key[1],
            "edges": [_edge_view(e) for e in grouped[key]],
            "chains": [], "broken": False, "truncated": False, "reasons": [],
            "why": "",
        }
        for edge in grouped[key]:
            _walk_up(index, edge, path=[f"stmt:{sid}"], steps=[], group=group,
                     max_chains=max_chains, max_depth=max_depth, depth=0,
                     seen={sid})
        group["broken"] = any(c["status"] != "ok" for c in group["chains"])
        group["truncated"] = bool(group["reasons"])
        if group["broken"]:
            group["why"] = "这一组里至少有一条链走不到根（见 chains 里的 break_at）"
        else:
            group["why"] = f"这一组 {len(group['chains'])} 条链都走到了根"
        if group["truncated"]:
            out["truncated"] = True
            out["reasons"].extend(f"{group['group']}:{r}" for r in group["reasons"])
        out["groups"].append(group)
    broken_groups = [g["group"] for g in out["groups"] if g["broken"]]
    out["why"] = (f"按证明路径分 {len(out['groups'])} 组"
                  + (f"；走不到根的组：{'、'.join(broken_groups)}" if broken_groups else
                     "；每组都到了根"))
    return out


def _walk_up(index: Any, edge: Mapping[str, Any], *, path: list[str],
             steps: list[dict], group: dict[str, Any], max_chains: int,
             max_depth: int, depth: int, seen: set[str]) -> None:
    """从一条"向上"的边继续走到根（深度优先；每个终点记一条链）。"""
    step = {
        "from": path[-1], "to": (f"stmt:{edge['source_stmt_id']}"
                                 if edge["source_stmt_id"] else
                                 str(edge["source_root"].get("id") or "")),
        "dep_id": edge["dep_id"], "path_no": edge["path_no"],
        "path_group": edge["path_group"], "used_at": edge["used_at"],
        "used_at_known": edge["used_at_known"], "status": edge["status"],
    }
    chain_steps = [*steps, step]
    if len(group["chains"]) >= max_chains:
        if "chain_budget" not in group["reasons"]:
            group["reasons"].append("chain_budget")
        return
    target = str(edge["source_stmt_id"] or "")
    if not target:
        root = dict(edge["source_root"])
        if root:
            group["chains"].append(_chain(path, chain_steps, root=root,
                                          status="ok", break_at={}))
        else:
            group["chains"].append(_chain(
                path, chain_steps, root={}, status="broken",
                break_at={"node": path[-1], "dep_id": edge["dep_id"],
                          "status": edge["status"],
                          "why": (f"这条依赖没有闭合（status={edge['status'] or '?'}）"
                                  f"，四选一来源一个都没给 ⇒ 走不到根"
                                  + (f"；理由：{edge['status_reason']}"
                                     if edge["status_reason"] else ""))}))
        return
    if target in seen:
        group["chains"].append(_chain(
            path, chain_steps, root={}, status="broken",
            break_at={"node": path[-1], "dep_id": edge["dep_id"],
                      "why": f"依赖链成环：stmt:{target} 已经在来路上 ⇒ 走不到根"}))
        return
    if depth + 1 > max_depth:
        if "depth_budget" not in group["reasons"]:
            group["reasons"].append("depth_budget")
        group["chains"].append(_chain(
            path, chain_steps, root={}, status="broken",
            break_at={"node": path[-1], "dep_id": edge["dep_id"],
                      "why": f"向上超过 {max_depth} 层还没到根 ⇒ 判不了终点"}))
        return
    target_node = index.nodes.get(target)
    if target_node is None:
        group["chains"].append(_chain(
            path, chain_steps, root={}, status="broken",
            break_at={"node": path[-1], "dep_id": edge["dep_id"],
                      "why": (f"依赖指向 stmt:{target}，但台账里没有这一行 "
                              "⇒ 断在不在册的那一端")}))
        return
    next_edges = index.up_edges(target)
    if not next_edges:
        is_concept = str(target_node.get("kind") or "") == "concept"
        root_kind = "primitive_concept" if is_concept else "no_premise"
        group["chains"].append(_chain(
            path + [f"stmt:{target}"], chain_steps,
            root={"kind": root_kind, "id": f"stmt:{target}",
                  "label": target_node.get("label", "")},
            status="ok", break_at={}))
        return
    for nxt in next_edges:
        _walk_up(index, nxt, path=path + [f"stmt:{target}"], steps=chain_steps,
                 group=group, max_chains=max_chains, max_depth=max_depth,
                 depth=depth + 1, seen=seen | {target})


def _chain(path: list[str], steps: list[dict], *, root: Mapping[str, Any],
           status: str, break_at: Mapping[str, Any]) -> dict[str, Any]:
    return {"chain": list(path), "steps": [dict(s) for s in steps],
            "root": dict(root), "status": status, "break_at": dict(break_at)}


def _edge_view(edge: Mapping[str, Any]) -> dict[str, Any]:
    """依赖面 / 被引面里每条边的读数（键恒定）。"""
    return {
        "dep_id": edge["dep_id"], "used_by": edge["used_by"],
        "used_by_head": edge["used_by_head"],
        "citer_stmt_id": edge["citer_stmt_id"],
        "citer_kind": edge["citer_kind"],
        "external_citer": bool(edge["external_citer"]),
        "proof_no": int(edge["path_no"]), "path_group": edge["path_group"],
        "kind": edge["kind"], "label": edge["label"],
        "source_stmt_id": edge["source_stmt_id"],
        "source_root": dict(edge["source_root"]),
        "used_at": edge["used_at"], "used_at_known": bool(edge["used_at_known"]),
        "status": edge["status"],
    }


# ---------------------------------------------------------------- 被引面（一层）

def cited_face(index: Any, stmt_id: Any) -> dict[str, Any]:
    """谁引用它 —— 只给一层（直接引用者），含每条边的路径号 / 用在哪一步。"""
    sid = index.normalize_stmt_id(stmt_id)
    out: dict[str, Any] = {
        "checked": True, "citations": [], "count": 0, "external": 0,
        "by_status": {}, "truncated": False, "reasons": [], "why": "",
    }
    if sid not in index.nodes:
        out.update(checked=False,
                   why="台账里没有这一条 ⇒ 被引面没查成（不是「没人引它」）")
        return out
    citations = [_edge_view(e) for e in index.by_source.get(sid, ())]
    out["citations"] = citations
    out["count"] = len(citations)
    out["external"] = sum(1 for c in citations if c["external_citer"])
    by_status: dict[str, int] = {}
    for one in citations:
        by_status[str(one["status"])] = by_status.get(str(one["status"]), 0) + 1
    out["by_status"] = by_status
    out["why"] = (f"直接引用它（一层）的有 {len(citations)} 条依赖边"
                  if citations else
                  "台账里没有一条依赖边以它为被引方 ⇒ 0 条被引"
                  "（这是「查过、没人引」，不是「没查成」；"
                  "「台账里没有命题依赖它」不等于「它没有关系」）")
    return out


# ---------------------------------------------------------------- expand（局部树）

def expand(index: Any, node: Any, depth: int, direction: str = "both", *,
           max_nodes: int = MAX_NODES,
           max_chars: int = MAX_CHARS) -> dict[str, Any]:
    """从 `node` 起按 `depth` 层上下展开 ⇒ 局部树（层数由调用方决定、必填）。

    返回形状：

        {nodes, edges, frontier, truncated, reasons, budget_used,
         added_nodes, already_known, ...}

    每个节点带七样：相对选定节点的关系（方向 / 距离 / 经由的链）、命题号、
    命题类别（`kind` 原文）、命题内容（`statement_full`，不含证明）、等级、
    依赖面（全路径 + 按证明路径分组）、被引面（一层）。

    无句柄、但增量：同一个 `(根, node, depth, direction)` 的第二次调用只交
    新增节点（`nodes` 里不再出现上一趟给过的），并在 `added_nodes` /
    `already_known` 里把两批分开；同一问反复调不会把同一批字段再塞一遍上下文。
    """
    sid = index.normalize_stmt_id(node)
    root_node = index.nodes.get(sid)
    base: dict[str, Any] = {
        "checked": False, "node": sid, "depth": int(depth), "direction": direction,
        "nodes": [], "edges": [], "frontier": [],
        "truncated": False, "reasons": [],
        "budget_used": {"nodes": 0, "added": 0, "edges": 0, "chars": 0,
                        "node_budget": int(max_nodes),
                        "char_budget": int(max_chars), "depth_max": int(depth)},
        "added_nodes": [], "already_known": [], "why": "",
    }
    if root_node is None:
        base["why"] = (f"台账里没有 {sid or '（空号）'} 这一条 ⇒ 展不开"
                       "（不是「它没有关系」）；先用 `ledger.resolve` 选一个真存在的根")
        base["reasons"] = ["node_not_found"]
        return base
    direction = str(direction or "both")
    max_depth = max(0, int(depth))
    max_nodes = max(1, int(max_nodes))
    max_chars = max(1, int(max_chars))

    # ---- BFS（按层推进；方向决定取哪一侧的邻接）
    relations: dict[str, dict[str, Any]] = {
        sid: {"direction": "root", "distance": 0, "via": [], "via_text": "（选定节点）"}}
    visited: list[str] = [sid]
    expanded: set[str] = set()
    edges_out: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    chars = 0
    reasons: list[str] = []
    truncated = False

    queue: deque[tuple[str, int]] = deque([(sid, 0)])
    while queue:
        current, distance = queue.popleft()
        expanded.add(current)
        for nxt, edge, kind in _neighbors(index, current, direction):
            edge_view = _tree_edge(current, nxt, edge, kind)
            edge_key = (edge_view["dep_id"], edge_view["dir"], edge_view["from"])
            if edge_key not in edge_keys:
                edge_keys.add(edge_key)
                edges_out.append(edge_view)
            if not edge_view["to_is_statement"]:
                continue                     # 外部根：只作为边的读数
            target = str(edge_view["to_id"])
            if target in relations:
                continue
            if distance + 1 > max_depth:
                continue
            if len(visited) >= max_nodes:
                if "node_budget" not in reasons:
                    reasons.append("node_budget")
                truncated = True
                continue
            relations[target] = {
                "direction": "up" if kind == "up" else "down",
                "distance": distance + 1,
                "via": [*relations[current]["via"], _tree_step(edge_view)],
                "via_text": _via_text(relations[current], edge_view),
            }
            visited.append(target)
            queue.append((target, distance + 1))

    # ---- 逐节点装配读数（字符预算在装配时逐条核）
    nodes_out: list[dict[str, Any]] = []
    for sid_i in visited:
        reading = index._read_node(sid_i, relations[sid_i])
        size = len(json.dumps(reading, ensure_ascii=False, default=str))
        if chars + size > max_chars and nodes_out:
            if "char_budget" not in reasons:
                reasons.append("char_budget")
            truncated = True
            break
        chars += size
        nodes_out.append(reading)

    # 边只连交回的那批节点（外部根例外：它们没有节点、本身就是边的读数）。
    # 预算/深度截到边界上的那些目标不进 `nodes`，只由 `frontier` 交接。
    delivered = {r["stmt_id"] for r in nodes_out}
    edges_out = [e for e in edges_out
                 if (not e["to_is_statement"]) or e["to_id"] in delivered]

    known = _delivered_get(index.root, sid, max_depth, direction)
    added = [r["stmt_id"] for r in nodes_out if r["stmt_id"] not in known]
    already = [{"stmt_id": r["stmt_id"], "kind": r["kind"],
                "status": r["status"], "label": r["label"]}
               for r in nodes_out if r["stmt_id"] in known]
    if known:
        # 增量：上一趟给过的节点不再重复交字段（身份 / 类别 / 状态 / 标签四格足够接上），
        # 边也只留与新增节点相连的那些（到旧节点的接缝保留，免得"接不上"）。
        added_set = set(added)
        nodes_out = [r for r in nodes_out if r["stmt_id"] in added_set]
        # 边跟着"新交付的节点"走：外部根没有节点，它挂在哪条边上就由那条边的
        # 展开方带出来；展开方没新增 ⇒ 这条外部读数也不该再塞一遍。
        edges_out = [e for e in edges_out
                     if e["to_id"] in added_set
                     or e["from"].split(":")[-1] in added_set]
    _delivered_add(index.root, sid, max_depth, direction, set(visited))

    frontier = _frontier(index, visited, expanded, relations, direction, max_depth)
    base.update(
        checked=True, nodes=nodes_out, edges=edges_out,
        frontier=frontier, truncated=truncated, reasons=reasons,
        budget_used={"nodes": len(visited), "added": len(added),
                     "edges": len(edges_out), "chars": chars,
                     "node_budget": max_nodes, "char_budget": max_chars,
                     "depth_max": max_depth},
        added_nodes=added, already_known=already,
        why=(f"从 stmt:{sid} 起按 {direction} 展开 {max_depth} 层："
             f"这一趟新增 {len(added)} 个节点"
             + (f"，另有 {len(already)} 个上一趟已经给过（不重复塞）"
                if already else "")),
    )
    return base


def _neighbors(index: Any, sid: str, direction: str) -> list[tuple[str, dict, str]]:
    """`(目标, 边, 方向)` 列表；外部根也给（`目标` 为空串）。"""
    out: list[tuple[str, dict, str]] = []
    if direction in ("up", "both"):
        for edge in index.up_edges(sid):
            out.append((str(edge["source_stmt_id"] or ""), edge, "up"))
    if direction in ("down", "both"):
        for edge in index.down_edges(sid):
            out.append((str(edge["citer_stmt_id"] or ""), edge, "down"))
    return out


def _tree_edge(current: str, nxt: str, edge: Mapping[str, Any],
               kind: str) -> dict[str, Any]:
    """局部树的一条边（`from` = 展开的那一方，`to` = 走到的那一方）。

    外部根（`doc:` / `relation:` / `experiment:` 那一族，或 `source_lit_id` 那三种来源）
    没有目标节点：`to` 给它的外部号、`to_is_statement=False`，节点表里不建它。
    """
    external = not nxt
    if not external:
        target = f"stmt:{nxt}"
    elif kind == "down":
        target = str(edge["used_by_head"])
    else:
        target = str(edge["source_root"].get("id") or "")
    if kind == "up" and external:
        external_root = dict(edge["source_root"])
    elif external:
        external_root = {"kind": "external_usage", "id": target, "field": "used_by"}
    else:
        external_root = {}
    return {
        "from": f"stmt:{current}", "to": target, "to_id": (nxt if not external else target),
        "dir": "up" if kind == "up" else "down",
        "dep_id": edge["dep_id"], "path_no": edge["path_no"],
        "path_group": edge["path_group"], "used_at": edge["used_at"],
        "used_at_known": bool(edge["used_at_known"]),
        "status": edge["status"],
        "to_is_statement": not external,
        "external_root": external_root,
    }


def _via_text(previous: Mapping[str, Any], edge: Mapping[str, Any]) -> str:
    """`relation.via_text` 的一行：从选定节点到这一条，逐跳写明方向与用在哪一步。"""
    arrow = "↑" if edge["dir"] == "up" else "↓"
    where = f"，用在哪一步：{edge['used_at']}" if edge["used_at"] else ""
    return (f"{previous['via_text']} {arrow} {edge['to']} "
            f"（{edge['dir']} · #p{edge['path_no']}{where}）")


def _read_node(index: Any, sid: str, relation: Mapping[str, Any]) -> dict[str, Any]:
    """一个节点的完整读数（八样）。"""
    node = index.nodes.get(sid) or {}
    return {
        "stmt_id": sid,
        "kind": str(node.get("kind") or ""),
        "status": str(node.get("status") or ""),
        "grade": str(node.get("grade") or EB.GRADE_NOT_APPLICABLE),
        "label": str(node.get("label") or ""),
        "statement_full": str(node.get("statement_full") or ""),
        "proof_no": int(node.get("proof_no") or DEFAULT_PROOF_NO),
        "proof_nos": list(node.get("proof_nos") or []),
        #: 4) 非平凡度档位（逐证明路径，键 = `path_group`；读不到 ⇒ `checked=False`）。
        #: 这一格是"这条证明有多难"的唯一读数来源（`secretary_tier_ledger.nontriviality_paths`
        #: 折叠，本层只搬运）。C 写"为什么接受这一处高难度证明"时要引它。
        "nontriviality": dict(node.get("nontriviality")
                              or {"checked": False, "paths": {},
                                  "why": "这个节点没有档位读数"}),
        #: 1) 相对选定节点的关系：方向 / 相距几层 / 经由哪条边（链）
        "relation": {"direction": str(relation.get("direction") or ""),
                     "distance": int(relation.get("distance") or 0),
                     "via": [dict(one) for one in (relation.get("via") or [])],
                     "via_text": str(relation.get("via_text") or "")},
        #: 5) 依赖面：全路径 + 按证明路径分组
        "dependency_face": index.dependency_face(sid),
        #: 6) 被引面：只给一层（直接引用者）
        "cited_face": index.cited_face(sid),
    }


def _frontier(index: Any, visited: Sequence[str], expanded: set[str],
              relations: Mapping[str, Mapping[str, Any]], direction: str,
              max_depth: int) -> list[dict[str, Any]]:
    """边界节点 =「还能再展开」的接口（C 对其中任何一个再 expand 一次就接上）。

    两档都算：① 走到 `depth` 层、还有下一层的；② 因节点 / 字符预算没来得及展开的。
    """
    out: list[dict[str, Any]] = []
    for sid in visited:
        rel = relations.get(sid) or {}
        beyond = int(rel.get("distance") or 0) >= max_depth
        if sid in expanded and not beyond:
            continue
        can: list[str] = []
        if direction in ("up", "both"):
            if any(str(e["source_stmt_id"] or "") and
                   str(e["source_stmt_id"]) not in relations
                   for e in index.up_edges(sid)):
                can.append("up")
        if direction in ("down", "both"):
            if any(str(e["citer_stmt_id"] or "") and
                   str(e["citer_stmt_id"]) not in relations
                   for e in index.down_edges(sid)):
                can.append("down")
        if not can:
            continue
        node = index.nodes.get(sid) or {}
        out.append({"stmt_id": sid, "kind": str(node.get("kind") or ""),
                    "label": str(node.get("label") or ""),
                    "distance": int(rel.get("distance") or 0),
                    "directions": can})
    return out


def _tree_step(edge: Mapping[str, Any]) -> dict[str, Any]:
    """`relation.via` 里的一跳（从哪到哪、经由哪条边、用在哪一步）。"""
    return {"dir": str(edge["dir"]), "from": str(edge["from"]), "to": str(edge["to"]),
            "dep_id": str(edge["dep_id"]), "path_no": int(edge["path_no"]),
            "path_group": int(edge["path_group"]),
            "used_at": str(edge["used_at"])}
