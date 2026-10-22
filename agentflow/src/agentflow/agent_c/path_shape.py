# -*- coding: utf-8 -*-
"""角色 C 的候选路径形状读数：把每条候选路径的"形状"摆出来（业主 2026-10-22）。

业主 2026-10-22 的原话（这是本模块唯一的需求真身）：

> 「分析最自然，最直接的关系路径（不只是看最短依赖链）。比如一个 T4 级的东西
>  无依赖地生生证出来了，还有一条路线是循序渐进花五六个大步骤自然推出，我们肯定
>  不希望用前者。但是如果在那一顿绕弯子，有许多不直接支撑证明的引理或定理在依赖链
>  上，C 应该不选它。如果曲折的路径是已收录的唯一路径，则应该上报让父代理找 D 组织
>  研究，并提出自己的构想。总之这是 LLM 驱动。」

分工（不做死判据）：

- 这一层只算形状，不打分。每条候选路径一行：跳数、大步骤数、无依赖跳变几处、
  旁挂节点、承重边、同目标还有几条别的路径；
- 判"哪一条更自然"是模型的活（口径写在 `agent_skills.py` 里 C 那一岗的
  「最自然路径」那一节）。这里若塞一个"自然度分数"，模型就只能相信那个数字，
  而数字本身没有说服力 —— `core._score_chain` 之所以要把评分逐项打印出来，
  是同一条理由的另一面：让人能反驳它。形状本身就是证据，所以这里连分数都不给。

与 `proof_chain` 的分工：`proof_chain` 负责"哪条路径到得了根、最短是哪条"
（组内 AND / 组间 OR 的语义在那一份里，本模块一个字都不改它），
本模块只在它已经算出来的候选路径（`groups_out`，每个 `(证明号, 组)` 一行）之上
补一层形状。两者共用同一张只读快照 `_DepGraph`，不重读台账。

各格的口径（每一格都能被别人照着复核）：

- `path_id`：`p<证明号>g<组号>`；目标自身就是根的那一行是 `target-is-root`
  （证明号 / 组号都记 0，它们是哨兵不是读数）。
- `hops`：这一行的承重脊上有几条边（见下行 `support_edges`）。与 `proof_chain`
  报的 `length` 同源：脊就是"可行分支里最短的那一条"。
- `steps`：承重脊上的不同节点数（不含目标自身；末端的根也算一步 —— 它就是你
  落到的那个依据）。它数的是"要经过几个不同的命题段"，所以同一个命题在脊上出现
  两次只算一段，而两个前提汇聚时 `steps` 会小于 `hops`。
- `gaps`：脊上"无依赖直达"的跳变处数。判据：该节点是 `stmt:` 行、没有任何依赖边、
  而且 `_DepGraph.is_root` 判它是根、且它不是概念（概念的定义算根不算跳变）。
  这正是"T4 级的东西无依赖地生生证出来"的形状：链在这里断掉，中间没有一步可查。
  `lit:` 是外部依据、`concept` 是定义，两者都不计。
- `detour_nodes`：挂在这条路径上、但不被这条路径的结论用到的节点。判据
  （比"只被中间节点引用"更稳的那一版，理由见 `_shape_of`）：它在这一行
  `proof_chain` 走过的地方出现过（`hops`），却不在承重脊上 —— 也就是说这条路径
  的结论并不经过它。线性链上不会有旁挂节点（每个非根节点都只被一个中间节点引用，
  按字面判据会把整条链都标成旁挂 —— 那种口径只会产出噪音）。
- `off_path_ratio`：`len(detour_nodes)` 除以"这一行出现过的不同节点数（不含目标）"。
  它是形状读数，不是判决：0.5 也可以是一条好路径（只要旁挂的那一半不承重）。
- `support_edges`：承重脊上的边，逐条给 `dep_id` / `from` / `to`
  （"哪些边真的支撑结论"就是它）。
- `alternatives`：同一个目标还有几条别的候选路径（`groups_total - 1`）。
- `spine_nodes`：这条路的承重脊（不含目标自身）—— `detour_nodes` 就是"走过、
  却不在脊上"的那些，`support_edges` 是这条脊上的边。三格读的是同一件事的三个面。
- `spine_found`：这一行有没有算出承重脊。没走到根的路径没有脊，
  此时 `steps` / `gaps` / `detour_nodes` 都是空的，`off_path_ratio` 记 `None` ——
  "没有脊"是未知，不是 0（三态纪律）。
"""
from __future__ import annotations

from ._support import Any, Mapping, Sequence

#: 一次形状计算最多评估多少个 `(节点, 证明号, 组)` 分支。
#:
#: 为什么要有上限：依赖图里同一层可以有很多条分支（每个 `path_group` 一条），
#: 而本模块要沿脊往下走，最坏情况与 `proof_chain` 的递归同阶。超了就如实报
#: "没算完"（`checked=False`），绝不给一份被静默截断的形状 —— 一份少了行的读数
#: 会被下游读成"就这么几条"。
MAX_BRANCH_EVALS = 20000


def path_shapes(graph: Any, target: str, groups: Sequence[Mapping[str, Any]], *,
                max_depth: int = 4) -> dict[str, Any]:
    """候选路径的形状读数（每条 `(证明号, 组)` 一行）。

    参数：`graph` 是 `proof_chain._DepGraph` 的只读快照（只用它的
    `is_root` / `groups_of` / `target_of` / `stmts` 四处）；`target` 是目标的裸命题号
    （带 `stmt:` 前缀也认）；`groups` 是 `proof_chain` 已经算出来的那串候选路径。

    返回 `{"checked": bool, "rows": [...], "total": int, "note": str}`：

    - `checked=True` + `rows=[]`：这个目标没有候选路径（没有依赖边）；
    - `checked=True` + `rows=[...]`：每一行就是一条候选路径的形状；
    - `checked=False`：这一趟没算完（分支超上限），`note` 写清为什么。
      "没算完"与"没有候选路径"必须分得开 —— 前者不许被读成后者。
    """
    rows: list[dict[str, Any]] = []
    if isinstance(target, str) and target:
        target_node = target if ":" in target else f"stmt:{target}"
    else:
        return {"checked": False, "rows": [], "total": 0,
                "note": "目标号是空的 ⇒ 没算形状"}
    budget: dict[str, Any] = {"n": 0, "max": int(MAX_BRANCH_EVALS), "exceeded": False}
    total = len(groups)
    for row in groups:
        rows.append(_shape_of(graph, target_node, row, alternatives=max(0, total - 1),
                              max_depth=max_depth, budget=budget))
        if budget["exceeded"]:
            break
    if budget["exceeded"]:
        return {"checked": False, "rows": rows, "total": total,
                "note": (f"分支评估超过上限 {budget['max']} 次 ⇒ 形状只算到第 "
                         f"{len(rows)} 条（这一趟没算完，不是『就这几条』）")}
    if not groups:
        # 目标没有依赖边：只有一种候选路径 —— "它自己就是根"（无依赖直达那一档）。
        rows.append(_self_row(graph, target_node))
    return {"checked": True, "rows": rows, "total": total, "note": ""}


def _self_row(graph: Any, target_node: str) -> dict[str, Any]:
    """目标自己没有任何依赖边时的那一行（"无依赖地生生证出来"的最小形状）。

    它是不是根要由 `is_root` 判（读不成 / 不是根 ⇒ `reached=False`）：
    一条没有边、也没有证明证据的命题是"依赖没写"，不许被这一层读成"已经是根"。
    """
    ok, why = graph.is_root(target_node)
    gap_nodes = [target_node] if (ok and _is_bare_root(graph, target_node)) else []
    return {
        "path_id": "target-is-root", "proof_no": 0, "path_group": 0,
        "hops": 0, "steps": 0,
        "gaps": len(gap_nodes), "gap_nodes": gap_nodes,
        "detour_nodes": [], "off_path_ratio": 0.0,
        "support_edges": [], "alternatives": 0,
        "reached": bool(ok), "spine_found": bool(ok),
        # 脊不含目标自身（与其它行同一口径）：这一行的脊是空的，因为
        # 结论就是它自己 —— 没有任何一跳支撑它（跳变那一格 `gaps` 记的就是这件事）。
        "spine_nodes": [],
        "why": "" if ok else why,
    }


def _shape_of(graph: Any, target_node: str, row: Mapping[str, Any], *,
              alternatives: int, max_depth: int, budget: dict[str, Any]) -> dict[str, Any]:
    """一条候选路径一行（脊、跳变、旁挂、承重边，逐格给读数）。

    `detour_nodes` 为什么按"在 `hops` 里、却不在脊上"判，而不是按字面的
    "只被链上的中间节点引用、不被目标或其直接前提引用"：

    字面判据在一条正常的线性链（目标 → A → B → 文献）上会把 A 与 B 都标成旁挂 ——
    因为 B 确实只被 A 引用、A 也确实只被目标引用。那种口径产出的每一行都是噪音，
    而噪音判据等于没有判据。旁挂要抓的是"结论并不经过它"：脊是这条路径真正赖以
    走到根的那一串节点，落在脊外的（同一条路径里被走过、但没被用到的分支）才是
    业主说的"挂在链上但不直接支撑证明的引理或定理"。两者在"绕弯子"的那些图上
    给出同一批节点（中间节点的另一条分支正是被中间节点引用、又不被目标用到的东西），
    而在正常链上只后者不报。
    """
    proof_no = int(row.get("proof_no") or 1)
    group = int(row.get("group") or 1)
    subs = graph.groups_of(target_node)
    edges = (subs.get(proof_no) or {}).get(group) or []
    spine = _group_spine(graph, target_node, edges, max_depth=max_depth,
                         budget=budget, path=(target_node,))
    walked = [str(h.get("node") or "") for h in (row.get("hops") or [])]
    walked = [n for n in walked if n and n != target_node]
    out: dict[str, Any] = {
        "path_id": f"p{proof_no}g{group}", "proof_no": proof_no, "path_group": group,
        # 没有脊时跳数只能引 `proof_chain` 报的那一个（那是这一组走到的最深处），
        # 并如实标 `spine_found=False`。
        "hops": 0, "steps": 0, "gaps": 0, "gap_nodes": [],
        "detour_nodes": [], "off_path_ratio": None,
        "support_edges": [], "alternatives": int(alternatives),
        "reached": bool(row.get("reached")), "spine_found": bool(spine["ok"]),
        "spine_nodes": [], "why": "" if row.get("reached") else str(row.get("why") or ""),
    }
    if not spine["ok"]:
        out["hops"] = int(row.get("length") or 0)
        out["off_path_ratio"] = None
        return out
    spine_nodes = [n for n in dict.fromkeys(spine["nodes"]) if n != target_node]
    gap_nodes = [n for n in spine_nodes if _is_bare_root(graph, n)]
    seen = set(spine["nodes"]) | set(walked) | {target_node}
    seen.discard(target_node)
    detour = sorted({n for n in walked} - set(spine["nodes"]))
    out.update({
        "hops": len(spine["edges"]),
        "steps": len(spine_nodes),
        "gaps": len(gap_nodes),
        "gap_nodes": gap_nodes,
        "detour_nodes": detour,
        "off_path_ratio": (round(len(detour) / len(seen), 3) if seen else 0.0),
        "support_edges": list(spine["edges"]),
        "spine_nodes": spine_nodes,
    })
    return out


def _is_bare_root(graph: Any, node: str) -> bool:
    """这个节点是不是"无依赖直达"的那种根（业主说的 T4 跳变）。

    三条同时成立才算：① 它是一条 `stmt:` 命题（文献是外部依据、概念是定义，
    两者都不算跳变）；② 它一条依赖边都没有；③ `_DepGraph.is_root` 判它是根
    （没有边却"不是根"的那一档叫"依赖没写"，不许算成跳变，更不许算成到根）。
    """
    kind, _, bare = str(node).partition(":")
    if kind != "stmt":
        return False
    row = (getattr(graph, "stmts", None) or {}).get(bare) or {}
    if str(row.get("kind") or "") == "concept":
        return False
    if graph.groups_of(bare):
        return False
    ok, _why = graph.is_root(node)
    return bool(ok)


def _group_spine(graph: Any, node: str, edges: Sequence[Mapping[str, Any]], *,
                 max_depth: int, budget: dict[str, Any],
                 path: tuple[str, ...]) -> dict[str, Any]:
    """同一个 `(证明号, 组)` 内的多条边取 AND：每条都要走通，脊把它们并起来。

    长度口径与 `proof_chain._and_length` 逐字相同（组里最长的那条边决定长度）：
    本模块不另立一份口径，否则两处会各自漂移，而"两条链长不一致"没人会报。
    """
    if len(path) > max_depth:
        return _no_spine()
    nodes: list[str] = [node]
    spine_edges: list[dict[str, str]] = []
    length = 0
    for dep in edges:
        budget["n"] = int(budget["n"]) + 1
        if int(budget["n"]) > int(budget["max"]):
            budget["exceeded"] = True
            return _no_spine()
        if str(dep.get("status") or "") == "dangling":
            return _no_spine()
        tgt, _kind = graph.target_of(dep)
        if not tgt:
            return _no_spine()
        sub = _descend(graph, tgt, max_depth=max_depth, budget=budget, path=path)
        if not sub["ok"]:
            return _no_spine()
        nodes.extend(sub["nodes"])
        spine_edges.append({"dep_id": str(dep.get("dep_id") or ""),
                            "from": node, "to": tgt})
        spine_edges.extend(sub["edges"])
        length = max(length, 1 + int(sub["length"]))
    return {"ok": True, "nodes": nodes, "edges": spine_edges, "length": length}


def _descend(graph: Any, node: str, *, max_depth: int, budget: dict[str, Any],
             path: tuple[str, ...]) -> dict[str, Any]:
    """某一节点自己的承重脊：在它的 `(证明号, 组)` 分支里取可行且最短的那一条。

    与 `proof_chain._grow` 的组合规则同一条（分支之间 OR、组内 AND），只是这里
    问的不是"到不到得了根"，而是"到了根的那条脊长什么样"。并列时取
    `(证明号, 组号)` 小的那一条 —— 与 `proof_chain` 排 `ranked` 的次序键一致，
    于是同一条路径在两边指到的是同一个分支。
    """
    if len(path) > max_depth:
        return _no_spine()
    ok, _why = graph.is_root(node)
    if ok:
        return {"ok": True, "nodes": [node], "edges": [], "length": 0}
    if node in path:
        return _no_spine()
    subs = graph.groups_of(node)
    if not subs:
        return _no_spine()
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, int] | None = None
    for sub_no in sorted(subs):
        for sub_group in sorted(subs[sub_no]):
            got = _group_spine(graph, node, subs[sub_no][sub_group],
                               max_depth=max_depth, budget=budget,
                               path=path + (node,))
            if not got["ok"]:
                if budget["exceeded"]:
                    return _no_spine()
                continue
            key = (int(got["length"]), int(sub_no), int(sub_group))
            if best_key is None or key < best_key:
                best, best_key = got, key
    return best or _no_spine()


def _no_spine() -> dict[str, Any]:
    """没有承重脊（没走到根 / 环 / 超深度 / 分支超上限）。"""
    return {"ok": False, "nodes": [], "edges": [], "length": 0}
