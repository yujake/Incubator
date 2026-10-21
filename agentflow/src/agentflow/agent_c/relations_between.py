"""角色 C 的动作 `relations_between`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations


class _RelationsBetween:
    def relations_between(self, a: str, b: str, *, include_inactive: bool = True) -> dict:
        """两个概念之间的全部关系（同步、只读、有界）。
        返回----``{"checked", "a", "b", "relation_ids", "relations": [精简行...],"empty", "reason", ...}``
        三态在这里的分工（DESIGN §3.4 明写的一条）：
        - ``relation_ids == []`` + ``empty=True`` + ``checked=True`` —— 查了，没有；- 
        ``checked=False`` —— 没查（概念表为空，图上没有任何可查代号）。
        把前者压成后者（或反过来）会让 D 分不清"这两点确实没有关系"与"我根本没查到"，而前者是一条可以写进研究结论的确定性判断，后者只是一个待办。
        `include_inactive=False` 只过滤 `status != "active"` 的关系（判重存疑/已否决）。被过滤掉多少条会写进 `reason` 与 
        `filtered_out` —— 否则"过滤后为空"与"本来就没有"又是同一个形状。
        """
        g = self._g()
        aid, bid = str(a or ""), str(b or "")
        checked, why = self._service_checkable(g)
        unknown = sorted({x for x in (aid, bid) if x and x not in g.concept_by_id})
        base = {
            "a": aid,
            "b": bid,
            "a_name": g.name_of(aid) if g.concept_by_id else "",
            "b_name": g.name_of(bid) if g.concept_by_id else "",
            "include_inactive": bool(include_inactive),
            "unknown_concepts": unknown,
        }
        if not checked:
            return {**base, "checked": False, "relation_ids": [], "relations": [], "empty": True,
                    "filtered_out": 0, "reason": why}

        all_rels = g.relations_between(aid, bid)
        rels = (
            list(all_rels)
            if include_inactive
            else [r for r in all_rels if str(r.get("status") or "") == "active"]
        )
        filtered_out = len(all_rels) - len(rels)
        briefs = [self._relation_brief(g, r) for r in rels]
        empty = not briefs
        if aid == bid:
            reason = f"a 与 b 是同一个概念（{aid}）：自己与自己之间不存在关系 ⇒ 查过了、没有"
        elif empty:
            reason = f"查过了：{aid} 与 {bid} 之间没有关系（关系表这一对上是空的）"
        else:
            reason = (
                f"查到了 {len(briefs)} 条关系："
                + "、".join(str(x["relation_id"]) for x in briefs)
            )
        if filtered_out:
            reason += (
                f"；另有 {filtered_out} 条非 active 的关系被 include_inactive=False 过滤掉了"
                "（**它们确实存在**，只是本次查询不要它们）"
            )
        if unknown:
            reason += (
                f"；注意 {'、'.join(unknown)} 不在概念表里（可能只出现在关系的 concept_ids 上），"
                "因此这个名字来自图索引而非概念表"
            )
        return {
            **base,
            "checked": True,
            "relation_ids": [str(x["relation_id"]) for x in briefs],
            "relations": briefs,
            "empty": empty,
            "filtered_out": filtered_out,
            "reason": reason,
        }
