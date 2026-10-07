"""角色 C 的动作 `neighbors`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import SERVICE_MAX_DEPTH, SERVICE_MAX_NODES, _cfg_int, _service_int

class _Neighbors:
    def neighbors(self, concept_id: str, *, depth: int = 1, max_nodes: int | None = None) -> dict:
        """某概念的 `depth` 跳邻域（同步、只读、有界）。

        返回
        ----
        ``{"checked", "concept_id", "depth", "nodes": [{concept_id, name, distance}],
           "edges": [...], "truncated", "reason", "empty", ...}``

        - `nodes` 含起点本身（`distance=0`）。不含起点的话，"查不到这个概念"
          与"它是个孤立节点"在返回值上长得一模一样，而那两件事要求 D 做不同的事：
          前者要改查询，后者才是"这个方向确实没人研究"。
        - `empty` 的口径：这次查询没有找到起点之外的任何节点（孤立概念、或
          depth 内无邻居）。它与 `checked` 正交 —— `checked=True & empty=True`
          才是"查了、确实没有邻居"。
        - `depth` 与 `max_nodes` 都会被夹进服务上限（`truncated=True` + `reason` 明说）；
          触及 `max_nodes` 时只展开到边界为止并如实标截断。静默截断会让 D 以为
          "就这些邻居"，进而得出一个口吻确定的错误结论。
        - 概念不存在 ⇒ `checked=True`、`nodes=[]`、`reason` 说清"该代号不在概念表里"。
          `checked=False` 只留给"概念表为空 / 图上没有任何可查代号"。
        """
        g = self._g()
        cid = str(concept_id or "")
        checked, why = self._service_checkable(g)

        depth_ceiling = max(1, _cfg_int(self.cfg, "service_max_depth", SERVICE_MAX_DEPTH))
        node_ceiling = max(1, _cfg_int(self.cfg, "service_max_nodes", SERVICE_MAX_NODES))
        want_depth = _service_int(depth, name="depth", default=1)
        want_nodes = node_ceiling if max_nodes is None else _service_int(max_nodes, name="max_nodes",
                                                                       default=node_ceiling)
        eff_depth = max(1, min(want_depth, depth_ceiling))
        eff_nodes = max(1, min(want_nodes, node_ceiling))

        clamped: list[str] = []
        if want_depth > depth_ceiling:
            clamped.append(
                f"请求 depth={want_depth} 超过服务上限 {depth_ceiling} ⇒ 按 {depth_ceiling} 跳计算"
            )
        if max_nodes is not None and want_nodes > node_ceiling:
            clamped.append(
                f"请求 max_nodes={want_nodes} 超过服务上限 {node_ceiling} ⇒ 按 {node_ceiling} 个节点计算"
            )

        if not checked:
            return {
                "checked": False,
                "concept_id": cid,
                "depth": eff_depth,
                "max_nodes": eff_nodes,
                "nodes": [],
                "edges": [],
                "truncated": False,
                "empty": True,
                "reason": why,
                "budget_notes": list(clamped),
            }

        if cid not in g.concept_by_id:
            return {
                "checked": True,
                "concept_id": cid,
                "depth": eff_depth,
                "max_nodes": eff_nodes,
                "nodes": [],
                "edges": [],
                "truncated": False,
                "empty": True,
                "reason": (
                    f"该代号不在概念表里：{cid}（概念表现有 {len(g.concept_by_id)} 个代号）⇒ "
                    "查过了、**没有这个概念**。这不是 checked=False —— checked=False 是'根本没查'，"
                    "请勿把两者压成同一个结论"
                ),
                "budget_notes": list(clamped),
            }

        nb = g.neighborhood(cid, depth=eff_depth, max_nodes=eff_nodes)
        nodes = list(nb["nodes"])
        edges = list(nb["edges"])
        notes = list(clamped)
        if nb["truncated"]:
            notes.append(
                f"已展开 {nb['node_count']} 个节点即触及 max_nodes={eff_nodes}"
                f"（触发原因：{'、'.join(nb['reasons'])}）"
            )
        truncated = bool(nb["truncated"]) or bool(clamped)
        empty = len(nodes) <= 1
        if empty:
            reason = (
                f"{g.name_of(cid)}（{cid}）在概念表里，但 {eff_depth} 跳内**没有任何邻居**"
                "（它是孤立概念）⇒ 查过了、确实没有邻居"
            )
        else:
            reason = (
                f"{g.name_of(cid)}（{cid}）在 {eff_depth} 跳内命中 {len(nodes) - 1} 个邻居"
                f"（含起点共 {len(nodes)} 个节点、{len(edges)} 条边）"
            )
        if truncated:
            reason += (
                "；⚠️ **结果不完整**：" + "；".join(notes)
                + "。不能据此断言'邻居就这些'——那正是静默截断最坏的形态"
            )
        return {
            "checked": True,
            "concept_id": cid,
            "name": g.name_of(cid),
            "depth": eff_depth,
            "max_nodes": eff_nodes,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "empty": empty,
            "reason": reason,
            "budget_notes": notes,
        }
