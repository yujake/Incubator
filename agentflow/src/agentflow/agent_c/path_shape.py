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
- `walked_nodes` / `walked_edges`：这一行真的走通的那一段。走到根时它就是承重脊
  （与 `spine_nodes` / `support_edges` 逐条相同）；因深度用尽而停时它是"起点 →
  停下的前一站"那一段；停在别的原因上（依赖没写 / 悬空边 / 环）时是空的。
  有了这两格，两批读数才拼得起来（见 `join_segments`）。
- `frontier`：这一行因深度用尽而停下的那些节点（每条路径一列，可能一个都没有）。
  每条给 `{node, from, via_dep_id, proof_no, path_group, depth_reached, why, next_hint}`，
  口径见下面的「前沿那一列」。
- `frontier_note`：这一批没有前沿时的说明。"" 只表示两种情况之一：全都到根了，
  或者停下的原因不是深度（后者会点名"有几条没走到根、但不是深度"）——
  与 `checked=False`（没算成）合起来才是三态。

## 前沿那一列（`max_depth` 是一批能搜多深，不是"这条路有多长"）

业主 2026-10-22：

> 「这里 max 的意思是一批分析能搜到多深，不妨碍如果有个证明有几十个大步骤，
>  可以一批一批往回搜，再拼起来。」

所以"这一批没到根"必须被读成两种截然不同的事：还没搜完（深度用尽，前面还有）
与链在这儿断了（依赖没写 / 悬空边 / 环）。`frontier` 就是前者的读数：

- `node`：这一批停下的那个节点（下一批的起点候选）；
- `from`：它上一站（已经走通的最后一个节点）；
- `via_dep_id`：接缝那条边的 `dep_id`（这条边在台账里存在，但这一批没有真的走过它）；
- `depth_reached`：从本批起点到 `from` 的跳数（= 这一批走通的深度上限，通常就是
  `max_depth`）。`node` 的深度是它加一 —— 正是这一跳越界了；
- `why`：只有 `depth_limit` 一个取值（别的停法不叫前沿）；
- `next_hint`：下一批怎么接着搜的一句话（把 `target` 换成 `node`、路径号照本行）。

一条候选路径可以有好几个前沿节点（组内 AND 的几条分支各自被截断）：它们都在
`frontier` 里，模型自己挑先搜哪一条 —— 本模块不做"接着搜"，也不替模型决定。

## `join_segments`：给 C 核对自己拼的那条链的材料，不是"自动拼链器"

两批读数（各是 `proof_chain` 的 payload，或 `path_shapes` 的返回值）交给
`join_segments`，它按"前沿节点 → 下一批的起点"把各段接起来，产出合并后的形状读数
（`hops` / `steps` / `gaps` / `detour_nodes` 按拼后的边与节点重算，不是把两批的数字相加）
以及 `segments`（每段的起点 / 终点 / 跳数）与 `seams`（接缝节点）。

它的定位是核对材料：接缝对不对、有没有环、哪一段缺失，由它摆出来给模型看；
"要不要接着搜、拼起来之后这条链自不自然"仍然是模型的判断（技能文本里写着那个循环）。
框架不会替模型自动一批一批搜下去 —— 那会把"由谁决定搜多深"这件事从模型手里拿走。
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

#: 前沿条目里 `why` 的唯一取值：因深度用尽而停。
#:
#: 为什么钉成常量而不写字面量：`why` 是判据要对着核的那一格，也是模型读到的那一格；
#: 两处各写一份字面量，等哪天停下的原因换了名字，两侧会各自漂移而没有任何东西会报。
FRONTIER_DEPTH_LIMIT = "depth_limit"


def path_shapes(graph: Any, target: str, groups: Sequence[Mapping[str, Any]], *,
                max_depth: int = 4) -> dict[str, Any]:
    """候选路径的形状读数（每条 `(证明号, 组)` 一行）。

    参数：`graph` 是 `proof_chain._DepGraph` 的只读快照（只用它的
    `is_root` / `groups_of` / `target_of` / `stmts` 四处）；`target` 是目标的裸命题号
    （带 `stmt:` 前缀也认）；`groups` 是 `proof_chain` 已经算出来的那串候选路径；
    `max_depth` 是这一批能往回搜多深（不是"这条路最多几跳"）。

    返回 `{"start": str, "checked": bool, "rows": [...], "total": int, "note": str,
    "frontier": [...], "frontier_note": str}`：

    - `checked=True` + `rows=[]`：这个目标没有候选路径（没有依赖边）；
    - `checked=True` + `rows=[...]`：每一行就是一条候选路径的形状；
    - `checked=False`：这一趟没算完（分支超上限），`note` 写清为什么。
      "没算完"与"没有候选路径"必须分得开 —— 前者不许被读成后者。
    - `frontier`：因深度用尽而停下的节点（`start` 是这一批的起点）。三种状态分得开：
      `checked=True` + `frontier=[]`（没有前沿）、`checked=True` + 非空（有前沿）、
      `checked=False`（没算成）。空列表不许被读成"这条路不存在"。
    """
    rows: list[dict[str, Any]] = []
    if isinstance(target, str) and target:
        target_node = target if ":" in target else f"stmt:{target}"
    else:
        return {"start": "", "checked": False, "rows": [], "total": 0,
                "frontier": [], "frontier_note": "目标号是空的 ⇒ 没算形状，也没有前沿",
                "note": "目标号是空的 ⇒ 没算形状"}
    budget: dict[str, Any] = {"n": 0, "max": int(MAX_BRANCH_EVALS), "exceeded": False}
    total = len(groups)
    for row in groups:
        rows.append(_shape_of(graph, target_node, row, alternatives=max(0, total - 1),
                              max_depth=max_depth, budget=budget))
        if budget["exceeded"]:
            break
    if budget["exceeded"]:
        return {"start": target_node, "checked": False, "rows": rows, "total": total,
                "frontier": _frontier_of(rows),
                "frontier_note": (f"分支评估超过上限 {budget['max']} 次 ⇒ 前沿只算到前 "
                                  f"{len(rows)} 条候选路径（这一趟没算完：没算到的不等于没有）"),
                "note": (f"分支评估超过上限 {budget['max']} 次 ⇒ 形状只算到第 "
                         f"{len(rows)} 条（这一趟没算完，不是『就这几条』）")}
    if not groups:
        # 目标没有依赖边：只有一种候选路径 —— "它自己就是根"（无依赖直达那一档）。
        rows.append(_self_row(graph, target_node))
    frontier = _frontier_of(rows)
    return {"start": target_node, "checked": True, "rows": rows, "total": total,
            "frontier": frontier, "frontier_note": _frontier_note(rows, frontier),
            "note": ""}


def _frontier_of(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把各行自己的前沿条目并成一列（按 `(节点, 上一站, 路径号)` 去重）。

    去重不是为了好看：同一条 `(证明号, 组)` 的同一处截断可能在几个分支里各记一次，
    重复摆在读数里会让"这一批停在三处"这句话变成假的读数。
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        for item in row.get("frontier") or []:
            key = (str(item.get("node") or ""), str(item.get("from") or ""),
                   str(item.get("proof_no")), str(item.get("path_group")))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(item))
    return out


def _frontier_note(rows: Sequence[Mapping[str, Any]],
                   frontier: Sequence[Mapping[str, Any]]) -> str:
    """没有前沿时那一格该说什么（有两种"没有"，不能混）。

    有前沿 ⇒ 空串（那几条自己带着 `why` 与 `next_hint`）。
    没有前沿、而且每一行都到根了 ⇒ 空串（"这一批就到根了"）。
    没有前沿、却有行没到根 ⇒ 必须说清"停下的原因不是深度" —— 那种行
    在读数里长得像"没搜完"，实际上是链在那儿断了（依赖没写 / 悬空边 / 环）。
    """
    if frontier:
        return ""
    stopped = [r for r in rows if not r.get("reached")]
    if not stopped:
        return ""
    return (f"有 {len(stopped)} 条候选路径没走到根，但停下不是因为深度用尽 ⇒ 这一批"
            "没有前沿（该看每一行的 `why`：依赖没写 / 悬空边 / 环都在那儿）")


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
        # 走通的那一段：只有起点自己（它没有下一站）。前沿是空的 —— 这一行不是
        # 因深度停下的（到根了，或者依赖没写）。
        "walked_nodes": [target_node], "walked_edges": [], "frontier": [],
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
    trace: dict[str, Any] = {"cuts": []}
    spine = _group_spine(graph, target_node, edges, max_depth=max_depth,
                         budget=budget, path=(target_node,), chain=[], trace=trace)
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
        "spine_nodes": [], "walked_nodes": [], "walked_edges": [], "frontier": [],
        "why": "" if row.get("reached") else str(row.get("why") or ""),
    }
    if not spine["ok"]:
        out["hops"] = int(row.get("length") or 0)
        out["off_path_ratio"] = None
        # 因深度用尽而停：把"停在哪"如实交出来（前沿 + 走通的那一段）。
        # 停在别的原因上（依赖没写 / 悬空边 / 环）时没有前沿 —— 那两种"停"必须分得开。
        out["frontier"] = [_frontier_entry(cut, max_depth=max_depth,
                                           proof_no=proof_no, path_group=group)
                           for cut in trace["cuts"]]
        out["walked_nodes"], out["walked_edges"] = _deepest_walk(trace["cuts"])
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
        # 走通的那一段就是承重脊（含起点）。前沿是空的：这一行到根了，
        # 即使有备选分支被深度截断，也不算"这一批停在那儿"（那些分支逐条在
        # `proof_chain` 的 `failures` 里，不在这一格）。
        "walked_nodes": [target_node] + spine_nodes,
        "walked_edges": list(spine["edges"]),
        "frontier": [],
    })
    return out


def _frontier_entry(cut: Mapping[str, Any], *, max_depth: int, proof_no: int,
                    path_group: int) -> dict[str, Any]:
    """一条前沿条目（`{node, from, via_dep_id, proof_no, path_group, depth_reached,
    why, next_hint}`）。

    `depth_reached` 记的是"这一批从起点走通的深度"（= 到 `from` 的跳数），不是
    `node` 自己的深度：`node` 的深度是它加一，正是那一跳越界了。这样记的理由是
    下一批 `target` 换成 `node` 之后，"两批拼起来到 `node` 是第几跳"要能用
    `depth_reached + 1` 复核；把两个数字中的一个换成另一种口径，接缝处就会差一跳，
    而差一跳的链看起来照样像一条链。
    """
    node = str(cut.get("node") or "")
    return {
        "node": node,
        "from": str(cut.get("from") or ""),
        "via_dep_id": str(cut.get("via_dep_id") or ""),
        "proof_no": int(proof_no),
        "path_group": int(path_group),
        "depth_reached": int(cut.get("depth_reached") or 0),
        "why": FRONTIER_DEPTH_LIMIT,
        "next_hint": (f"下一批把 target 换成 {node}（同一条候选路径：proof_no={proof_no}、"
                      f"path_group={path_group}），max_depth 仍用 {max_depth} 再搜一批；"
                      "两批的形状交给 path_shape.join_segments 核对接缝"),
    }


def _deepest_walk(cuts: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    """几条截断里取最深的那一段（"这一批走通到哪儿"）。

    为什么取最深而不拼所有分支：`walked_nodes` 回答的是"这一段走到哪"，一条路径只有
    一个终点；别的前沿节点自己在 `frontier` 里各占一条，不会丢。
    """
    if not cuts:
        return [], []
    best = max(cuts, key=lambda c: (int(c.get("depth_reached") or 0),
                                    len(c.get("walked_edges") or [])))
    return ([str(n) for n in best.get("walked_nodes") or []],
            [dict(e) for e in best.get("walked_edges") or []])


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
                 path: tuple[str, ...], chain: list[dict[str, str]],
                 trace: dict[str, Any]) -> dict[str, Any]:
    """同一个 `(证明号, 组)` 内的多条边取 AND：每条都要走通，脊把它们并起来。

    长度口径与 `proof_chain._and_length` 逐字相同（组里最长的那条边决定长度）：
    本模块不另立一份口径，否则两处会各自漂移，而"两条链长不一致"没人会报。

    深度口径也与 `proof_chain._grow` 对齐：`path` 装着"从这一行的起点到 `node`"
    的节点序列（含 `node`），`node` 的深度是 `len(path) - 1`，与 `_grow` 的
    `depth` 同一个意思 —— 超了 `max_depth` 就停，并把这处截断记进 `trace`。

    `chain` 是与 `path` 逐跳对应的边（`{dep_id, from, to}`）：有它，截断处才说得出
    "接缝那条边是哪一条"，两批读数也就拼得起来。
    """
    if len(path) - 1 > max_depth:
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
        step = {"dep_id": str(dep.get("dep_id") or ""), "from": node, "to": tgt}
        sub = _descend(graph, tgt, max_depth=max_depth, budget=budget,
                       path=path + (tgt,), chain=chain + [step], trace=trace)
        if not sub["ok"]:
            return _no_spine()
        nodes.extend(sub["nodes"])
        spine_edges.append(step)
        spine_edges.extend(sub["edges"])
        length = max(length, 1 + int(sub["length"]))
    return {"ok": True, "nodes": nodes, "edges": spine_edges, "length": length}


def _descend(graph: Any, node: str, *, max_depth: int, budget: dict[str, Any],
             path: tuple[str, ...], chain: list[dict[str, str]],
             trace: dict[str, Any]) -> dict[str, Any]:
    """某一节点自己的承重脊：在它的 `(证明号, 组)` 分支里取可行且最短的那一条。

    与 `proof_chain._grow` 的组合规则同一条（分支之间 OR、组内 AND），只是这里
    问的不是"到不到得了根"，而是"到了根的那条脊长什么样"。并列时取
    `(证明号, 组号)` 小的那一条 —— 与 `proof_chain` 排 `ranked` 的次序键一致，
    于是同一条路径在两边指到的是同一个分支。

    深度用尽不是"没有脊"的同义词：这里把截断处（`node`、上一站、接缝那条边、
    走通的那一段）记进 `trace["cuts"]`，调用方据此交出 `frontier`。
    """
    depth = len(path) - 1
    if depth > max_depth:
        trace["cuts"].append({
            "node": node,
            "from": (path[-2] if len(path) >= 2 else ""),
            "via_dep_id": (str(chain[-1].get("dep_id") or "") if chain else ""),
            "depth_reached": depth - 1,
            "walked_nodes": list(path[:-1]),
            "walked_edges": [dict(e) for e in chain[:-1]],
        })
        return _no_spine()
    ok, _why = graph.is_root(node)
    if ok:
        return {"ok": True, "nodes": [node], "edges": [], "length": 0}
    if node in path[:-1]:
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
                               path=path, chain=chain, trace=trace)
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


# --------------------------------------------------------------- 两批读数拼起来


def join_segments(segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把两批（或多批）读数按"前沿节点 → 下一批的起点"接起来，给 C 核对用。

    ## 定位：核对材料，不是"自动拼链器"

    要不要接着搜、挑哪一条前沿、拼起来之后这条链自不自然 —— 都是模型的判断
    （技能文本里那个循环写的才是做法）。本函数只做一件机械的事：把各批已经交出来的
    读数按接缝对一遍，把"拼起来长什么样、接缝在哪、哪一段缺"摆成能复核的读数。
    框架不会替模型一批一批搜下去 —— 那会把"搜多深"的决定权从模型手里拿走。

    ## 输入

    每一批一项，三种写法都认：`C.proof_chain` 的 payload（`path_shapes` / `frontier` /
    `node.stmt_id` 都在里面）、`path_shapes` 的返回值（`rows` / `frontier` / `start`）、
    或者自己攒的一个小 dict（`{"start": ..., "rows": [...], "frontier": [...],
    "checked": bool}`）。顺序就是批次顺序。

    ## 三种状态（不许折平）

    - `checked=False`：拼不起来（接缝对不上 / 成环 / 某批没交出行 / 有一批没算成），
      `note` 点名断在第几批、缺的是哪一段，`rows` 是空的 —— 绝不给出一个
      "看起来完整"的链；已经接上的 `segments` / `seams` 照旧交出，好让人看见断在哪儿。
    - `checked=True` + `complete=True`：拼成一条到根的链。
    - `checked=True` + `complete=False`：拼起来了，但链还没到根（最后一批停在前沿上），
      `note` 说清还需要第几批、起点是哪几个节点。"没搜完"是这一档，不是 `checked=False`。

    ## 每格口径

    - `hops`：拼起来之后承重边的条数（各段的边 + 每条接缝那一跳）。不是各段跳数相加：
      前一批报的 `hops` 里含着"越界那一跳"（它没走通），相加会多算一跳。
    - `steps`：拼起来的承重脊上不同节点的个数（不含最初那个起点）。
    - `gaps` / `gap_nodes`：各段报的跳变节点取并集，再与拼后的脊求交（同一处跳变
      被两批各报一次时不重复计）。
    - `detour_nodes` / `off_path_ratio`：各段旁挂节点取并集，减去拼后的脊 ——
      一段里看着像旁挂的节点，可能正是另一段的承重脊。
    - `segments`：`[{start, end, hops, batch}]`，每段是那一批实际走通的那一段
      （它的起点、终点、跳数）；
    - `seams`：`[{at_node, from_batch, to_batch, via_dep_id}]`，`at_node` 是前一批
      停下的节点（= 后一批的起点），`via_dep_id` 是接缝那条边的台账 id
      （它没有被任何一批真的走过，所以它不进任何一段的 `hops`，只算在合并后的）。
    """
    parts = [_segment_parts(seg, i) for i, seg in enumerate(segments or ())]
    if not parts:
        return {"checked": False, "complete": False, "rows": [], "segments": [], "seams": [],
                "note": ("没有给任何一批读数 ⇒ 拼不起来（这不是『拼成了一条空链』："
                         "空列表是没东西可拼，不是拼出来是空的）")}

    chosen: list[tuple[dict[str, Any], dict[str, Any]]] = []
    segments_out: list[dict[str, Any]] = []
    seams: list[dict[str, Any]] = []
    nodes: list[str] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    problems: list[str] = []
    first_start = ""
    pending_seam: dict[str, Any] | None = None

    for idx, part in enumerate(parts):
        if not part["checked"]:
            problems.append(f"第 {part['batch']} 批这一趟没算成（`checked=False`）⇒ "
                            "那一批的读数不可信，拼不起来")
            break
        if not part["rows"]:
            problems.append(f"第 {part['batch']} 批没有交出行读数（`path_shapes` 是空的）⇒ "
                            "那一段的形状无从核对")
            break
        seam_from_prev, pending_seam = pending_seam, None
        row: dict[str, Any] | None
        if idx + 1 < len(parts):
            # 这一批必须交出一个"前沿正好停在下一批起点"的行 —— 接缝就是这么定的。
            want = parts[idx + 1]["start"]
            row = _row_by_frontier(part["rows"], want)
            if row is None:
                where = "、".join(str(f.get("node") or "")
                                  for f in part["frontier"]) or "（前沿是空的）"
                problems.append(
                    f"第 {part['batch']} 批的前沿是 {where}，而第 {part['batch'] + 1} 批的起点是 "
                    f"{want} ⇒ 接缝对不上：拼不起来（缺的是 {want} 之后那一段，"
                    "先拿回那一批的读数再拼）")
                break
            pending_seam = _frontier_entry_of(part["frontier"], want)
        else:
            row = _pick_row(part["rows"])
        if seam_from_prev is not None and idx > 0:
            if _node_ref(part["start"]) != _node_ref(seam_from_prev.get("node")):
                problems.append(
                    f"第 {part['batch']} 批的起点是 {part['start']}，而第 {parts[idx - 1]['batch']} "
                    f"批的前沿节点是 {seam_from_prev.get('node')} ⇒ 接缝对不上：拼不起来")
                break

        w_nodes = [str(n) for n in (row.get("walked_nodes") or [])]
        w_edges = [dict(e) for e in (row.get("walked_edges") or [])]
        seg_start = part["start"] or (w_nodes[0] if w_nodes else "")
        if w_nodes and seg_start and _node_ref(w_nodes[0]) != _node_ref(seg_start):
            problems.append(
                f"第 {part['batch']} 批的起点是 {seg_start}，而它交出来的那一段从 "
                f"{w_nodes[0]} 开始 ⇒ 这一批的读数不是从起点量的，拼不起来")
            break
        seg_end = w_nodes[-1] if w_nodes else seg_start
        segments_out.append({"start": seg_start, "end": seg_end,
                             "hops": len(w_edges), "batch": int(part["batch"])})
        if idx == 0:
            first_start = seg_start
            add_nodes, add_edges = list(w_nodes), list(w_edges)
        else:
            if seam_from_prev is None:
                problems.append(f"第 {part['batch']} 批前面没有接缝读数 ⇒ 拼不起来")
                break
            prev_end = nodes[-1] if nodes else first_start
            if _node_ref(prev_end) != _node_ref(seam_from_prev.get("from")):
                problems.append(
                    f"第 {part['batch'] - 1} 批的那一段走到 {prev_end}，而前沿条目记的接缝上一站是 "
                    f"{seam_from_prev.get('from')} ⇒ 接缝对不上（缺的是 {seam_from_prev.get('from')} "
                    f"到 {seam_from_prev.get('node')} 之间那一段）")
                break
            seams.append({"at_node": str(seam_from_prev.get("node") or ""),
                          "from_batch": int(parts[idx - 1]["batch"]),
                          "to_batch": int(part["batch"]),
                          "via_dep_id": str(seam_from_prev.get("via_dep_id") or "")})
            add_edges = [{"dep_id": str(seam_from_prev.get("via_dep_id") or ""),
                          "from": str(seam_from_prev.get("from") or ""),
                          "to": str(seam_from_prev.get("node") or ""),
                          "seam": True}] + list(w_edges)
            add_nodes = list(w_nodes)
        duplicate = [n for n in add_nodes if n in seen]
        if duplicate:
            problems.append(f"有环：{duplicate[0]} 在同一份拼接里出现了两次"
                            f"（第 {part['batch']} 批又走回它）⇒ 拼不起来")
            break
        seen.update(add_nodes)
        nodes.extend(add_nodes[1:] if idx == 0 else add_nodes)
        edges.extend(add_edges)
        chosen.append((part, row))

    if not problems and not chosen:
        problems.append("没有任何一批被接上 ⇒ 拼不起来")
    complete = bool(chosen) and bool(chosen[-1][1].get("reached"))
    note = ""
    if not problems and not complete:
        last_part, last_row = chosen[-1]
        last_frontier = [dict(f) for f in (last_row.get("frontier") or [])]
        if not last_frontier:
            problems.append(
                f"第 {last_part['batch']} 批没走到根，而它没有前沿（停下的原因不是深度："
                f"{last_row.get('why') or '见那一行的 why'}）⇒ 这是一处断点，接不下去")
        else:
            where = "、".join(str(f.get("node") or "") for f in last_frontier)
            note = (f"拼起来了，但链还没到根：第 {last_part['batch']} 批停在 {where}"
                    f"（why={FRONTIER_DEPTH_LIMIT}）⇒ 还需要第 {len(parts) + 1} 批，"
                    "起点从这几个前沿节点里挑。这不是『没有这条路』，是还没搜完")
    if problems:
        return {"checked": False, "complete": False, "rows": [],
                "segments": segments_out, "seams": seams,
                "note": "；".join(problems)}
    if not note:
        note = (f"拼成一条到根的链：{len(segments_out)} 段、{len(seams)} 处接缝。"
                "接缝那几条边按前一批前沿记的 `via_dep_id` 计 —— 它们没有被任何一批真的走过，"
                "所以要复核就回到台账看那几条依赖。这是核对读数，不是判决："
                "这么拼对不对、拼起来自不自然，由你自己判")
    spine = list(dict.fromkeys(nodes))
    gap_nodes = sorted({str(g) for _p, r in chosen for g in (r.get("gap_nodes") or [])}
                       & set(spine))
    detour = sorted({str(d) for _p, r in chosen for d in (r.get("detour_nodes") or [])}
                    - set(spine) - {_node_ref(first_start)})
    seen_all = set(spine) | set(detour)
    head = chosen[0][1]
    row_out = {
        "path_id": "join-" + "-".join(str(int(p["batch"])) for p, _r in chosen),
        "proof_no": int(head.get("proof_no") or 0),
        "path_group": int(head.get("path_group") or 0),
        "hops": len(edges),
        "steps": len(spine),
        "gaps": len(gap_nodes), "gap_nodes": gap_nodes,
        "detour_nodes": detour,
        "off_path_ratio": (round(len(detour) / len(seen_all), 3) if seen_all else 0.0),
        "support_edges": edges,
        "alternatives": int(head.get("alternatives") or 0),
        "reached": bool(complete), "spine_found": bool(complete),
        "spine_nodes": spine,
        "walked_nodes": [first_start] + spine,
        "walked_edges": edges,
        # 拼到根了这一格就是空的（没有"停"）；没到根则把最后一批的前沿照抄过来。
        "frontier": [dict(f) for f in (chosen[-1][1].get("frontier") or [])] if not complete else [],
        "batches": [int(p["batch"]) for p, _r in chosen],
        "why": "" if complete else note,
    }
    return {"checked": True, "complete": bool(complete), "rows": [row_out],
            "segments": segments_out, "seams": seams, "note": note}


def _node_ref(value: Any) -> str:
    """节点号写到同一种写法上（`0008` 与 `stmt:0008` 指的是同一个节点）。

    拼链要比"前一批的终点等于后一批的起点"，两种写法混着来会让一条接得上的链
    被判成接不上 —— 而那时读数看起来只是"拼不起来"，没人会想到是写法。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return text if ":" in text else f"stmt:{text}"


def _segment_parts(seg: Mapping[str, Any], index: int) -> dict[str, Any]:
    """一批读数归一成 `{batch, start, frontier, rows, checked}`（三种写法都认）。"""
    rows = seg.get("path_shapes")
    if not isinstance(rows, list):
        rows = seg.get("rows") if isinstance(seg.get("rows"), list) else []
    start = str(seg.get("start") or "")
    if not start:
        node = seg.get("node")
        if isinstance(node, Mapping) and str(node.get("stmt_id") or ""):
            start = f"stmt:{node['stmt_id']}"
    if not start:
        start = str(seg.get("target") or "")
    if not start:
        for row in rows:
            walked = [str(n) for n in (row.get("walked_nodes") or [])] if isinstance(row, Mapping) else []
            if walked:
                start = walked[0]
                break
    checked = seg.get("checked", seg.get("path_shapes_checked", True))
    return {"batch": int(seg.get("batch") or (index + 1)),
            "start": _node_ref(start),
            "frontier": [dict(f) for f in (seg.get("frontier") or [])
                         if isinstance(f, Mapping)],
            "rows": [dict(r) for r in rows if isinstance(r, Mapping)],
            "checked": bool(checked)}


def _row_by_frontier(rows: Sequence[Mapping[str, Any]], want: Any) -> dict[str, Any] | None:
    """找出"前沿正好停在 `want`"的那一行（下一批的起点就接在它的前沿上）。"""
    target = _node_ref(want)
    for row in rows:
        for item in row.get("frontier") or []:
            if _node_ref(item.get("node")) == target:
                return dict(row)
    return None


def _frontier_entry_of(frontier: Sequence[Mapping[str, Any]],
                       want: Any) -> dict[str, Any] | None:
    """那一列前沿里指向 `want` 的那一条。"""
    target = _node_ref(want)
    for item in frontier:
        if _node_ref(item.get("node")) == target:
            return dict(item)
    return None


def _pick_row(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """没有接缝要求时挑哪一行：先取走到根的，再取跳数少的（与 `proof_chain` 同序）。"""
    reached = [r for r in rows if r.get("reached")]
    pool = reached or list(rows)
    return dict(min(pool, key=lambda r: (int(r.get("hops") or 0),
                                         int(r.get("proof_no") or 0),
                                         int(r.get("path_group") or 0))))
