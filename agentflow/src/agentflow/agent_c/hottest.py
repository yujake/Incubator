"""角色 C 的动作 `hottest`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import AnalysisReport, relation_sort_key

class _Hottest:
    def hottest(self, top_n: int = 5, request: str = "") -> AnalysisReport:
        """统计最热门的几个概念（§3.3(1)）。

        §3.3(1) 第 1 步的"出现次数"口径很关键：对每条关系的 `concept_ids` 里
        每个概念 +1 次出现，一条关系涉及 3 个概念就算 3 次。这不是"关系条数"：
        把"关系数"当热度，会让一个只跟"集合"发生关系的高频概念排到前面，
        而它其实只是被反复提及，并没有形成多少知识联系。
        这里由 `RelationGraph.counts()` 统一提供两种口径（occurrences 与
        relation_count），报告里两个都给，D 可以自己交叉验证。

        代表关系按 §3.3(4) 的确定性序取前 3（引文已校验优先、其次状态、
        再次信息量），不是随机取 3 条 —— 需求要的是"便于人工核对热度是否
        名副其实"，那就必须给最能代表这个概念的关系。
        """
        g = self._g()
        top_n = max(0, int(top_n))
        counts = g.counts()
        counts_all = dict(counts)
        warnings: list[str] = []
        if not g.relations:
            # 这两种"空"必须分清：没有关系表数据 ≠ 没有热门概念。
            #
            # `ok_=False`：`AnalysisReport.ok` 的 docstring 明说 "False 表示'这次
            # 没能给出结论'（概念解析不到、关系表为空等）"，而这里原先返回的是默认的
            # `ok=True` —— docstring 与实现直接矛盾。后果不是"少一个字段"：工具层
            # `graph.hottest` 返回的就是 `.to_dict()`，调用方 `if res["ok"]` 会把
            # "数据还没进来"当成"统计做完了，结果为空"，进而得出一个口吻确定的错结论。
            return self._report(
                "hottest",
                request,
                {"top_n": top_n},
                summary="关系表为空：还没有任何关系数据可供统计（这不是'没有热门概念'，而是'数据还没进来'）。",
                payload={"entries": [], "hot_ids": [], "relation_total": 0, "concept_total": len(g.concept_by_id)},
                markdown="\n".join(
                    self._md_head("hottest", "关系表为空，无法统计热度。", ["关系表 rows 为 0"])
                    + ["## 结论", "", "关系表为空，没有可统计的对象。请先让 B 抽取关系。"]
                ),
                warnings=["关系表为空"],
                ok_=False,
                error="关系表为空：数据还没进来，无法给出结论",
            )

        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        top = ranked[:top_n]
        hot_ids = [cid for cid, _ in top]
        entries: list[dict] = []
        for cid, vals in top:
            rels = [g.relation_by_id[r] for r in g.concept_relations.get(cid, []) if r in g.relation_by_id]
            reps = sorted(rels, key=relation_sort_key)[:3]
            entries.append(
                {
                    "concept_id": cid,
                    "name": g.name_of(cid),
                    "occurrences": vals["occurrences"],
                    "relation_count": vals["relation_count"],
                    "group_count": vals["group_count"],
                    "degree": g.degree(cid),
                    "representative_relations": [self._relation_brief_for_report(g, r, focus=cid) for r in reps],
                }
            )
        isolated = sorted(cid for cid, v in counts.items() if v["relation_count"] == 0)
        if len(ranked) > top_n and ranked[top_n - 1][1]["occurrences"] == ranked[top_n][1]["occurrences"]:
            warnings.append(
                "第 %d 名与第 %d 名的 occurrences 相同（都是 %d）：同分按 concept_id 升序取舍，"
                "截断线附近的名次没有语义差别。" % (top_n, top_n + 1, ranked[top_n][1]["occurrences"])
            )
        payload = {
            "top_n": top_n,
            "relation_total": len(g.relations),
            "concept_total": len(counts),
            "occurrence_basis": "对每条关系的 concept_ids 里每个概念 +1 次出现（3 个概念的关系算 3 次）",
            "entries": entries,
            "hot_ids": hot_ids,
            "isolated_ids": isolated,
            "all_counts_tail": [
                {"concept_id": cid, **vals} for cid, vals in ranked[top_n : top_n + 10]
            ],
            "sort_rule": "occurrences 降序，同分按 concept_id 升序（稳定，保证可复现）",
        }
        md = self._md_head("hottest", f"最热门的 {len(entries)} 个概念（按出现次数）。", warnings)
        md += ["| 概念代号 | 概念名 | 出现次数 | 关系条数 | 概念组次数 |", "|---|---|---|---|---|"]
        md += [
            f"| {e['concept_id']} | {e['name']} | {e['occurrences']} | {e['relation_count']} | {e['group_count']} |"
            for e in entries
        ]
        md += ["", "## 代表关系（按引文校验与信息量的确定性序取前 3）", ""]
        for e in entries:
            md.append(f"### {e['name']}（{e['concept_id']}）")
            if not e["representative_relations"]:
                md.append("- （没有任何关系）")
                continue
            for r in e["representative_relations"]:
                md.append(
                    f"- `{r['relation_id']}` {r['description']}（{r['status']}，"
                    f"引文校验={r['quote_verified']}，文献 {r['lit_id']}）"
                )
        if isolated:
            md += ["", f"## 完全孤立的概念（degree=0，共 {len(isolated)} 个）：{', '.join(isolated)}", ""]
        return self._report(
            "hottest",
            request,
            {"top_n": top_n},
            summary=f"最热门的 {len(entries)} 个概念：" + "、".join(f"{e['name']}({e['occurrences']}次)" for e in entries),
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
        )
