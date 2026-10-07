"""角色 C 的动作 `paths`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import AnalysisReport, PathSearchResult, _cfg_int, relation_sort_key

class _Paths:
    def paths(
        self,
        a: str,
        b: str,
        *,
        max_paths: int = 5,
        max_len: int = 4,
        max_overlap: float = 0.5,
        request: str = "",
    ) -> AnalysisReport:
        """查询两个概念间的关系（§3.3(2) 的 6 步，逐条落地）。"""
        g = self._g()
        params = {"a": a, "b": b, "max_paths": max_paths, "max_len": max_len, "max_overlap": max_overlap}
        warnings: list[str] = []
        unknown = [x for x in (a, b) if x not in g.adjacency]
        if unknown:
            return self._report(
                "paths",
                request,
                params,
                summary=f"无法查询：图里没有概念 {', '.join(unknown)}。",
                payload={"unknown": unknown, "known_concepts": self._concept_candidates(g)},
                warnings=["起点或终点不存在"],
                ok_=False,
                error=f"未知概念：{unknown}",
            )
        if a == b:
            return self._report(
                "paths",
                request,
                params,
                summary="无法查询：起点与终点是同一个概念（路径长度为 0，没有意义）。",
                payload={"a": a, "b": b},
                warnings=["a == b"],
                ok_=False,
                error="a 与 b 相同",
            )

        hot_top_n = _cfg_int(self.cfg, "hot_top_n", 5)
        hot_ids = self._hot_ids(hot_top_n)
        node_budget = _cfg_int(self.cfg, "node_budget", 20000)
        search_max = _cfg_int(self.cfg, "search_max_paths", max(50, int(max_paths) * 10))

        # ---- 第 1 步：有界图搜索
        raw: PathSearchResult = g.paths(a, b, max_len=int(max_len), max_paths=search_max, node_budget=node_budget)
        # 把"未筛选前"的原始集合按跳数统计并留在 payload 里：这是回答
        # "3 跳路径到底是没有，还是被去重丢掉了"的唯一证据。没有它，
        # 读报告的人只能相信"筛选后剩几条"这个二手结论。
        raw_by_hops: dict[str, int] = {}
        for _p in raw:
            k = str(len(_p) - 1)
            raw_by_hops[k] = raw_by_hops.get(k, 0) + 1
        if raw.truncated:
            warnings.append(
                "图搜索被截断（" + "、".join(raw.reasons) + f"）；已展开 {raw.budget_used} 个节点 / "
                f"预算 {raw.node_budget}。以下结论**只覆盖已搜到的部分**，不代表'两点之间只有这些路径'。"
            )

        # ---- 第 2 步：低重合度筛选（Jaccard）
        ordered = sorted(raw, key=lambda p: (len(p), list(p)))
        kept: list[list[str]] = []
        dropped_by_overlap: list[dict] = []
        for p in ordered:
            worst: tuple[float, list[str]] | None = None
            for q in kept:
                j = g.jaccard_nodes(p, q)
                if worst is None or j > worst[0]:
                    worst = (j, q)
            if worst is not None and worst[0] > float(max_overlap):
                dropped_by_overlap.append(
                    {
                        "path": list(p),
                        "concept_names": [g.name_of(c) for c in p],
                        "max_jaccard": round(worst[0], 4),
                        "against": list(worst[1]),
                        "reason": f"与已选路径节点重合度 {worst[0]:.2f} > max_overlap={max_overlap}（本质上同一条路径）",
                    }
                )
                continue
            kept.append(p)
        selected = kept[: max(0, int(max_paths))]
        dropped_by_limit = [
            {"path": list(p), "reason": f"超过 max_paths={max_paths}，仅在统计中计数"} for p in kept[max(0, int(max_paths)) :]
        ]
        if dropped_by_limit:
            warnings.append(f"另有 {len(dropped_by_limit)} 条低重合度路径因 max_paths={max_paths} 未展开（仅在统计里计数）。")

        # ---- 第 3/4 步：每一跳读全部候选关系，再选最合理的关系
        path_items: list[dict] = []
        incomplete: list[dict] = []
        for p in selected:
            hop_details: list[dict] = []
            chain_ids: list[str] = []
            used_lits: set[str] = set()
            broken = False
            for i in range(len(p) - 1):
                cands = g.relations_between(p[i], p[i + 1])
                if not cands:
                    broken = True
                    hop_details.append(
                        {
                            "hop": i + 1,
                            "from": p[i],
                            "to": p[i + 1],
                            "candidate_count": 0,
                            "candidate_ids": [],
                            "chosen": "",
                            "note": "这一跳在图上成立但关系表里找不到对应关系（数据不一致）",
                        }
                    )
                    chain_ids.append("")
                    continue
                # `relations_between` 内部已经按 `relation_sort_key` 排过一遍，`best_relation`
                # 内部还会再排一遍，这里是第三次。这不是"第二份判据"（INVENTORY 4.7⑨
                # 的措辞容易被读成判据分叉）：三次用的都是同一个 `graph_tools.relation_sort_key`
                # （import 进来的唯一实现），所以不存在"两套判据漂移"的风险。
                # 保留它是因为 `candidate_ids` 要按确定性序打印给审计者看，而这份顺序
                # 不该悄悄依赖被调用方内部实现（它若哪天改成不排序，报告的顺序就变了）。
                ranked_cands = sorted(cands, key=relation_sort_key)
                best = g.best_relation(cands, used_lits)
                assert best is not None
                lit = str(best.get("lit_id") or "")
                hop_details.append(
                    {
                        "hop": i + 1,
                        "from": p[i],
                        "from_name": g.name_of(p[i]),
                        "to": p[i + 1],
                        "to_name": g.name_of(p[i + 1]),
                        "candidate_count": len(cands),
                        "candidate_ids": [str(c.get("relation_id")) for c in ranked_cands],
                        "chosen": str(best.get("relation_id")),
                        "chosen_description": best.get("description") or "",
                        "chosen_status": best.get("status"),
                        "chosen_quote_verified": best.get("quote_verified"),
                        "chosen_lit_id": lit,
                        "chosen_lit_already_used": lit in used_lits,
                        "note": f"共 {len(cands)} 条候选，按 quote_verified→status→信息量 的确定性序取最优",
                    }
                )
                chain_ids.append(str(best.get("relation_id")))
                used_lits.add(lit)
            rels = [g.relation_by_id[r] for r in chain_ids if r in g.relation_by_id]
            if broken or len(rels) != len(chain_ids):
                incomplete.append({"concept_path": list(p), "relation_chain": chain_ids})
                warnings.append(f"路径 {p} 存在无法解析的跳，已排除出正文（数据不一致，请先 verify）。")
                continue
            scored = self._score_chain(p, chain_ids, rels, hot_ids)
            path_items.append(
                {
                    "concept_path": list(p),
                    "concept_names": [g.name_of(c) for c in p],
                    "relation_chain": chain_ids,
                    "hops": len(chain_ids),
                    "hop_details": hop_details,
                    "chain_literature_ids": sorted({str(r.get("lit_id") or "") for r in rels}),
                    "llm_ranked": False,
                    **scored,
                }
            )

        # ---- 第 4 步的 LLM 钩子（可选）：只重排顺序，不改内容
        hook_used = False
        hook_note = "未启用 LLM 钩子：路径顺序完全由确定性评分决定。"
        if self.llm is not None and path_items:
            order = self._llm_rank_paths(a, b, path_items)
            if order:
                try:
                    reordered = [path_items[i] for i in order]
                    if sorted(order) == list(range(len(path_items))):
                        for it in reordered:
                            it["llm_ranked"] = True
                        path_items = reordered
                        hook_used = True
                        hook_note = "已按 LLM 返回的顺序重排路径（内容与评分仍为确定性结果）。"
                    else:
                        warnings.append("LLM 排序钩子返回的不是一个合法排列，已回退到确定性顺序。")
                except (IndexError, TypeError) as exc:
                    warnings.append(f"LLM 排序钩子结果无法应用（{exc}），已回退到确定性顺序。")
            else:
                hook_note = "LLM 钩子存在但未给出可用排序，已回退到确定性顺序。"

        # ---- 第 5/6 步：按等级分流
        high = [it for it in path_items if it["level"] == "high"]
        medium = [it for it in path_items if it["level"] == "medium"]
        low = [it for it in path_items if it["level"] == "low"]

        if not path_items:
            if raw.truncated:
                summary = (
                    "没有找到任何完整路径，且**搜索被截断**：不能据此判断两点不连通，"
                    "请提高 node_budget/max_len 或降低 max_overlap 后重试。"
                )
            else:
                summary = "没有找到任何路径：这两点之间在给定跳数内确实不连通（这是确定性结论，搜索未被截断）。"
        elif not high:
            # 需求："若全部为 low，报告要明说'没有找到高信息量路径'，而不是硬凑。"
            summary = (
                f"**没有找到高信息量路径**（候选 {len(selected)} 条：medium {len(medium)} 条、low {len(low)} 条）。"
                f"最高分 {max((it['score'] for it in path_items), default=0):.2f}，"
                f"未达 high 阈值 {self.threshold_high}；不把 medium 当作 high 上报。"
            )
        else:
            summary = (
                f"找到 {len(high)} 条高信息量路径"
                f"（另有 medium {len(medium)} 条、low {len(low)} 条）："
                + "；".join(
                    f"{'→'.join(it['concept_names'])}（{'→'.join(it['relation_chain'])}，score={it['score']:.2f}）"
                    for it in high[:3]
                )
            )

        payload = {
            "a": {"concept_id": a, "name": g.name_of(a)},
            "b": {"concept_id": b, "name": g.name_of(b)},
            "search": {
                "raw_path_count": len(raw),
                "raw_paths": [list(p) for p in raw],
                "raw_paths_by_hops": raw_by_hops,
                "truncated": raw.truncated,
                "truncation_reasons": list(raw.reasons),
                "budget_used": raw.budget_used,
                "node_budget": raw.node_budget,
                "max_len": int(max_len),
                "search_max_paths": search_max,
            },
            "dedup": {
                "kept_after_overlap_filter": len(kept),
                "selected_for_report": len(selected),
                "max_overlap": float(max_overlap),
                "dropped_by_overlap": dropped_by_overlap,
                "dropped_by_max_paths": dropped_by_limit,
                "rule": "节点集合 Jaccard 相似度 > max_overlap 即丢弃（严格大于，等于阈值时保留）",
            },
            "levels": {"high": len(high), "medium": len(medium), "low": len(low)},
            "has_high": bool(high),
            "incomplete_paths": incomplete,
            "paths": path_items,
            "hot_ids": hot_ids,
            "hot_basis": f"occurrences 前 {hot_top_n}",
            "score_thresholds": {"high": self.threshold_high, "medium": self.threshold_medium},
            "score_weights": dict(self.weights),
            "hook": {"llm_available": self.llm is not None, "used_for_ordering": hook_used, "note": hook_note},
        }
        md = self._md_head("paths", summary, warnings)
        md += [
            f"查询：**{g.name_of(a)}（{a}）** ↔ **{g.name_of(b)}（{b}）**",
            "",
            f"- 图搜索到 {len(raw)} 条简单路径（截断={raw.truncated}，原因={raw.reasons or '无'}，"
            f"预算 {raw.budget_used}/{raw.node_budget}；按跳数分布 {raw_by_hops}）",
            f"- 低重合度筛选后保留 {len(kept)} 条，报告展开 {len(selected)} 条，"
            f"因重合度丢弃 {len(dropped_by_overlap)} 条，因 max_paths 丢弃 {len(dropped_by_limit)} 条",
            f"- 信息量判决：high {len(high)} / medium {len(medium)} / low {len(low)}",
            f"- LLM 钩子：{hook_note}",
            "",
            "## 正文（仅高信息量路径）",
            "",
        ]
        if not high:
            md.append("**没有找到高信息量路径。**（medium 见附录，low 只在统计里计数、不展开。）")
            md.append("")
        for idx, it in enumerate(high, 1):
            md += self._md_path(idx, it, g, "高")
        md += ["", "## 附录（中等信息量路径，仅供参考，**未达正文标准、不作为证据**）", ""]
        if not medium:
            md.append("（无）")
        for idx, it in enumerate(medium, 1):
            md += self._md_path(idx, it, g, "中")
        md += ["", "## 统计（低信息量路径不展开，仅计数）", ""]
        md.append(f"- 低信息量路径：{len(low)} 条；分数区间：" + (
            f"{min((it['score'] for it in low), default=0):.2f} ~ {max((it['score'] for it in low), default=0):.2f}"
            if low
            else "（无）"
        ))
        for it in low:
            md.append(
                f"    - {'→'.join(it['concept_names'])}（{'→'.join(it['relation_chain'])}，score={it['score']:.2f}，"
                f"未达 medium 阈值 {self.threshold_medium}）"
            )
        if dropped_by_overlap:
            md += ["", "## 被重合度筛掉的路径（说明去重确实起了作用）", ""]
            for d in dropped_by_overlap:
                md.append(f"- {'→'.join(d['concept_names'])}：{d['reason']}（与 {'→'.join(d['against'])} 比）")
        return self._report(
            "paths",
            request,
            params,
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
            truncated=bool(raw.truncated) or bool(dropped_by_limit),
        )
