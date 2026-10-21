"""角色 C 的动作 `cold`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import AnalysisReport, _cfg_int

class _Cold:
    def cold(self, top_n: int = 5, request: str = "") -> AnalysisReport:
        """研究冷门概念（§3.3(3)）。
        
        两个刻意的分类决定：
        
        1. degree==0 的"完全孤立"单独归一类，不进冷门榜。"没人研究"（有关系但少）与"没人连接"（一条关系都没有）需要完全不同的动作：前者可能因为冷门而被低估，后者
        更可能是抽取遗漏或概念本身不该存在。混在一起会让 top_n 被孤立概念占满，而它们根本列不出"与热门概念的关系"（§3.3(3) 第 2 步）。 2. "冷门但连接强"单
        独列出：这是本分析器给 D 的核心输入。一个度数很低、但它与热门概念之间的连接引文已证实、状态正常、且不是唯一连接的概念，最可能是"被低估的研究点"；反过来，连接全是
        suspect 的冷门概念，更可能是抽取噪声，不该占用 D 的循环。
        """
        g = self._g()
        top_n = max(0, int(top_n))
        counts = g.counts()
        warnings: list[str] = []
        if not g.relations:
            # 与 `hottest` 同一条理由：`ok` 的 docstring 把"关系表为空"明确列为
            # "这次没能给出结论"，实现必须与它一致（否则调用方会把"没数据"读成"查完了"）。
            return self._report(
                "cold",
                request,
                {"top_n": top_n},
                summary="关系表为空：无法判断冷门（这不是'没有冷门概念'，而是'还没有关系数据'）。",
                payload={"entries": [], "isolated": [], "relation_total": 0},
                markdown="\n".join(
                    self._md_head("cold", "关系表为空，无法评估冷门概念。", ["关系表 rows 为 0"])
                    + ["## 结论", "", "关系表为空，没有可评估的对象。"]
                ),
                warnings=["关系表为空"],
                ok_=False,
                error="关系表为空：还没有关系数据，无法给出结论",
            )

        isolated = sorted(cid for cid, v in counts.items() if v["relation_count"] == 0)
        candidates = sorted(
            ((cid, v) for cid, v in counts.items() if v["relation_count"] > 0),
            key=lambda kv: (kv[1]["relation_count"], kv[0]),
        )
        coldest = candidates[:top_n]
        cold_ids = {cid for cid, _ in coldest}
        hot_ids = set(self._hot_ids(max(top_n, _cfg_int(self.cfg, "hot_top_n", 5))))

        entries: list[dict] = []
        for cid, vals in coldest:
            rels = [g.relation_by_id[r] for r in g.concept_relations.get(cid, []) if r in g.relation_by_id]
            to_hot: list[dict] = []
            weak: list[dict] = []
            for rel in rels:
                others = [str(c) for c in (rel.get("concept_ids") or []) if str(c) != cid]
                wa = self._weak_assessment(g, cid, rel, others, hot_ids, cold_ids)
                brief = self._relation_brief_for_report(g, rel, focus=cid)
                item = {**brief, **wa}
                if any(o in hot_ids for o in others):
                    to_hot.append(item)
                if wa["weak_points"] > 0:
                    weak.append(item)
            strong_to_hot = [x for x in to_hot if x["weak_points"] == 0]
            entries.append(
                {
                    "concept_id": cid,
                    "name": g.name_of(cid),
                    "definition": (g.concept_by_id.get(cid) or {}).get("definition") or "",
                    "degree": g.degree(cid),
                    "occurrences": vals["occurrences"],
                    "group_count": vals["group_count"],
                    # 需求："报告冷门概念和一些热门概念间的关系"
                    "relations_to_hot": to_hot,
                    "weak_relations": weak,
                    "all_relation_count": len(rels),
                    "strong_connections_to_hot": strong_to_hot,
                    # 核心输入：是否属于"冷门但连接强"
                    "undervalued": bool(strong_to_hot),
                    "undervalued_reason": (
                        "与热门概念的连接中至少有一条不满足任何弱判据（引文已证实/状态正常/非唯一连接/另一端热门）"
                        if strong_to_hot
                        else "与热门概念的连接全部至少满足一条弱判据，或根本没有与热门概念的连接"
                    ),
                }
            )
        undervalued = [e for e in entries if e["undervalued"]]
        if not hot_ids:
            warnings.append("热门集为空（关系表没有可排名的概念），因此'与热门概念的关系'一栏为空。")

        summary = (
            f"最冷门的 {len(entries)} 个概念（degree 升序）："
            + "、".join(f"{e['name']}(degree={e['degree']})" for e in entries)
            + f"；其中'冷门但连接强'（最可能被低估）{len(undervalued)} 个："
            + ("、".join(e["name"] for e in undervalued) if undervalued else "无")
            + f"；完全孤立（degree=0）{len(isolated)} 个，单独归类。"
        )
        payload = {
            "top_n": top_n,
            "cold_ids": [e["concept_id"] for e in entries],
            "entries": entries,
            "undervalued_ids": [e["concept_id"] for e in undervalued],
            "isolated": [{"concept_id": cid, "name": g.name_of(cid)} for cid in isolated],
            "hot_ids": sorted(hot_ids),
            "weak_criteria": [
                "quote_verified is not True（引文未获证实）",
                "status == 'suspect'（判重存疑）",
                "它是该概念唯一的连接",
                "另一端概念本身也很冷门（degree <= cold_weak_peer_degree）",
            ],
            "weak_score_rule": "四条判据各计 1 分，weak_score = 得分 / 4；全部理由都写进 weak_reasons",
            "relation_total": len(g.relations),
        }
        md = self._md_head("cold", summary, warnings)
        md += [
            f"- 冷门 top{top_n}（已排除 degree=0）：{', '.join(e['name'] for e in entries)}",
            f"- 完全孤立（degree=0，单列）：{', '.join(cid for cid in isolated) if isolated else '（无）'}",
            f"- 热门集合（用于比对）：{', '.join(g.name_of(c) for c in sorted(hot_ids)) if hot_ids else '（无）'}",
            "",
        ]
        for e in entries:
            md += [f"## {e['name']}（{e['concept_id']}，degree={e['degree']}）", ""]
            if e["definition"]:
                md.append(f"定义：{e['definition']}")
            if not e["relations_to_hot"]:
                md.append("- 与热门概念之间没有任何关系（它的连接都在冷门概念之间）。")
            for r in e["relations_to_hot"]:
                mark = "**连接强**" if r["weak_points"] == 0 else f"弱（weak_score={r['weak_score']}）"
                md.append(
                    f"- `{r['relation_id']}` 与 {', '.join(o['name'] for o in r['other_concepts'])}："
                    f"{r['description']}（{r['status']}，引文校验={r['quote_verified']}）→ {mark}"
                )
                if r["weak_points"] > 0:
                    for reason in r["weak_reasons"]:
                        md.append(f"    - 弱判据：{reason}")
            md.append("")
        md += ["## 冷门但连接强（最可能被低估的研究点，给 D 的核心输入）", ""]
        if not undervalued:
            md.append("（无：所有冷门概念与热门概念的连接都至少满足一条弱判据。）")
        for e in undervalued:
            md.append(
                f"- **{e['name']}**（{e['concept_id']}，degree={e['degree']}）："
                + "；".join(
                    f"`{r['relation_id']}` 与 {'/'.join(o['name'] for o in r['other_concepts'])} 的连接"
                    f"（引文校验={r['quote_verified']}，{r['status']}）"
                    for r in e["strong_connections_to_hot"]
                )
            )
        return self._report(
            "cold",
            request,
            {"top_n": top_n},
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
        )
