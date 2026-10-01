"""角色 C 的动作 `gaps`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import AnalysisReport, LEVELS, Mapping, _cfg_int

class _Gaps:
    def gaps(self, limit: int = 10, request: str = "", *, submit_requests: bool = False) -> AnalysisReport:
        """完善关系图（§3.3(4)）：找频次少的概念组 + 结构洞，并给出二元结论。

        需求原文是"若确实有，则报告"。这句话把责任压在了实现上：
        - 必须能明确说出"确实有"或"证据不足"；
        - 不允许把"没找到"包装成"找到了"（例如把一堆 low 置信度候选
          列在 `candidate_gaps` 里，让下游误以为发现了缺口）。

        所以 `candidate_gaps` 只收 `confidence >= medium` 的候选，其余进
        `low_confidence_candidates` 并逐条带上被否决的理由；
        `verdict` 字段给出"有"/"无"的二元答案，`conclusion` 给出人话结论。

        I3（缺口直连 A）：`submit_requests=True` 时，把 `candidate_gaps` 里
        通过 veto 且 confidence >= medium 的候选直接变成 A 的检索请求
        （`submitted_by="agent-C"`、`priority` 按 `SUBMITTER_DEFAULT_PRIORITY`、
        `mode="topical"`），单次最多 `max_gap_requests_per_run` 条、按净分降序、
        与已有未完成请求主题去重、超在途上限则拒绝而不是排队。
        默认 False（见下方那段为什么必须默认关闭）。

        I5（检测侧）：payload 里另附 `structural_duplicates` 摘要
        （结构重复概念的候选计数与少量样本；完整候选按 `graph.structural_duplicates` 取）。

        ── 为什么 I3 的写入不构成"绕过 B 引文回验"（必须写清楚，否则下一个维护者会
        以为这里有个权限漏洞，然后"顺手"把整条服务面也开成可写）──

            C 的工具面（`register_tools`）保持全量只读 —— C 的推理链不能写任何东西。
            I3 的 `search_requests` 写入是 `gaps()` 里的确定性代码路径，不经过 C 的
            工具与推理，且它写的不是知识（不是概念/关系/引文），而是"请 A 去查一查"
            的请求。因此它不构成"绕过 B 引文回验"的风险。这也是为什么它默认关闭、
            由编排层显式开启。
        """
        g = self._g()
        limit = max(0, int(limit))
        min_group = _cfg_int(self.cfg, "gap_group_min_count", 2)
        pair_budget = _cfg_int(self.cfg, "gap_pair_budget", 5000)
        hot_ids = self._hot_ids(_cfg_int(self.cfg, "hot_top_n", 5))
        warnings: list[str] = []
        truncated = False

        # ---- 候选 A：频次较少的概念组
        rare_groups: list[dict] = []
        for gk, cnt in sorted(g.group_counts.items()):
            if cnt >= min_group:
                continue
            cids = [c for c in gk.split("|") if c]
            if len(cids) < 2:
                continue
            rare_groups.append(
                self._evaluate_gap(
                    g,
                    cids,
                    kind="rare_group",
                    base_reason=f"概念组频次 {cnt} < 阈值 {min_group}（该组合只被研究过 {cnt} 次）",
                    common_neighbors=sorted(set(g.neighbors(cids[0])) & set(g.neighbors(cids[1]))) if len(cids) >= 2 else [],
                    hot_ids=hot_ids,
                )
            )

        # ---- 候选 B：结构洞（有共同邻居但彼此无直接关系）
        holes: dict[str, dict] = {}
        used_pairs = 0
        stop = False
        for u in sorted(g.adjacency):
            nbrs = g.neighbors(u)
            for i in range(len(nbrs)):
                if stop:
                    break
                for j in range(i + 1, len(nbrs)):
                    used_pairs += 1
                    if used_pairs > pair_budget:
                        truncated = True
                        stop = True
                        break
                    x, y = nbrs[i], nbrs[j]
                    if y in g.adjacency.get(x, {}):
                        continue  # 已有直接关系 ⇒ 不是结构洞
                    key = "|".join(sorted((x, y)))
                    holes.setdefault(key, {"concepts": sorted((x, y)), "common": []})["common"].append(u)
        if truncated:
            warnings.append(
                f"结构洞枚举触及 pair_budget={pair_budget} 被截断：只覆盖了部分三元组，"
                "**不能据此断言'没有更多结构洞'**。"
            )
        hole_candidates = [
            self._evaluate_gap(
                g,
                h["concepts"],
                kind="structural_hole",
                base_reason="结构洞：两个概念有共同邻居但彼此之间没有直接关系（'应该有边却缺失'的经典信号）",
                common_neighbors=sorted(set(h["common"])),
                hot_ids=hot_ids,
            )
            for _k, h in sorted(holes.items())
        ]

        all_cands = sorted(rare_groups + hole_candidates, key=lambda c: (-c["net_score"], c["key"]))
        # 三分法：否决项剔除 / 净分不足 / 真正的候选。
        # 只有 passed_veto 且净分 >= medium 的才进 candidate_gaps ——
        # 这是 verdict 语义干净的前提（见 _evaluate_gap 的 docstring）。
        vetoed = [c for c in all_cands if not c["passed_veto"]]
        survivors = [c for c in all_cands if c["passed_veto"]]
        candidates = [c for c in survivors if c["confidence"] in ("high", "medium")]
        low_conf = [c for c in survivors if c["confidence"] == "low"]
        reported = candidates[:limit]
        overflow = candidates[limit:]
        if overflow:
            warnings.append(f"另有 {len(overflow)} 条中等以上置信度候选超出 limit={limit} 未展开（已在统计中计数）。")

        # ---- LLM 钩子（可选）：只加一层语义复核，确定性结论始终保留
        hook_note = "未启用 LLM 钩子：'是否值得研究'完全由确定性信号决定。"
        if self.llm is not None and reported:
            judged = self._llm_judge_gaps(reported)
            if judged is None:
                hook_note = "LLM 钩子存在但未给出可用判断，已回退到确定性结论。"
            else:
                hook_note = "已叠加 LLM 语义复核；确定性结论保留在 confidence_deterministic 字段里以便对照。"
                for c in reported:
                    v = judged.get(c["key"])
                    if not isinstance(v, Mapping):
                        continue
                    c["llm_judgement"] = dict(v)
                    conf = str(v.get("confidence") or "")
                    if conf in LEVELS:
                        c["confidence"] = conf
                    if v.get("worth") is False:
                        c["llm_worth"] = False
                        c["reason"] = c["reason"] + "；LLM 复核认为不值得研究：" + str(v.get("reason") or "")

        worth = [c for c in reported if c.get("llm_worth", True) is not False]

        # ---- I3：把候选缺口直接变成 A 的检索请求（默认关闭；见 docstring）
        # 放在这里（而不是函数开头）：I3 只允许用"已经算好的候选"，也就是说它
        # 不能引入自己的判据。若把提交提前到候选确定之前，就不得不复制一份
        # veto / 置信度逻辑 —— 那正是"同一判据两处实现"的开端。
        submission = self._submit_gap_requests(worth, enabled=bool(submit_requests))
        # ---- I5 检测侧摘要（纯读；完整候选走 structural_duplicates()）
        structural = self._structural_duplicate_summary(g)

        # ---- 二元结论（需求："若确实有，则报告"）
        if worth:
            verdict = "有"
            conclusion = (
                f"确实有：发现 {len(worth)} 条值得研究的关系候选"
                f"（最高置信度 {worth[0]['confidence']}）。"
                f"检查范围：{len(g.group_counts)} 个概念组、{len(holes)} 个结构洞；"
                f"被否决项剔除 {len(vetoed)} 条、净分不足 {len(low_conf)} 条。"
            )
        else:
            verdict = "无"
            reasons: list[str] = []
            if vetoed:
                reasons.append(
                    f"{len(vetoed)} 条候选被**否决项**直接剔除"
                    "（引文全部无法核实 / 概念名不是概念 / 已被判重）—— 它们没有可核实的依据，"
                    "扣分再多也不能算'确实有'"
                )
            if low_conf:
                reasons.append(f"{len(low_conf)} 条候选净分未达 medium（正向信号被扣分项抵消）")
            if not rare_groups and not hole_candidates:
                reasons.append("既没有低频概念组，也没有结构洞")
            if not g.relations:
                # 关系表为空时，"无"这个 verdict 的含义完全不同：不是"查过了、确实没有"，
                # 而是"没有任何可查的关系"。原先这里与"查过没有"共享同一个 ok=True +
                # verdict="无"，于是下游（尤其是不看 payload 只看 verdict 的调用方）
                # 会把"数据还没进来"读成"确认不存在缺口"。理由要与温度计读数分开写。
                reasons.append(
                    "关系表为空（rows=0）⇒ **本次没有可评估的关系**，"
                    "这个'无'不是'查过了、确实没有缺口'"
                )
            if reported and not worth:
                reasons.append("LLM 复核否决了全部候选")
            conclusion = (
                "证据不足：本次没有发现确实可能存在的研究关系。"
                + ("原因：" + "；".join(reasons) if reasons else "候选的信号强度不足以支持'确实有'的判断。")
            )

        summary = (
            f"{conclusion}（结构洞 {len(holes)} 个、低频概念组 {len(rare_groups)} 个、"
            f"否决 {len(vetoed)} 条、净分不足 {len(low_conf)} 条，截断={truncated}）"
        )
        payload = {
            "verdict": verdict,
            "has_candidates": bool(worth),
            "conclusion": conclusion,
            "candidate_gaps": worth,
            "rejected_by_llm": [c for c in reported if c.get("llm_worth") is False],
            #: 被否决项剔除的候选：不算"有"，但逐条留理由供复核。
            "vetoed_candidates": vetoed,
            "low_confidence_candidates": low_conf,
            "overflow_candidates": overflow,
            "veto_rules": [
                "相关关系的 quote_verified 全部为 False（没有任何可核实的原文依据）",
                "概念名明显不是概念（过长/纯符号/含停用词/含句读）",
                "两者已被判重（相关关系的 duplicate_of 非空）",
            ],
            "deduction_rules": [
                "引文校验部分失败（-0.5）",
                "status=suspect 占比（-0.5 × 占比）",
                "存在 status=rejected（-0.5）",
                "候选端连接薄弱（degree <= cold_weak_peer_degree，-0.25 × 占比）",
            ],
            "searched": {
                "group_count": len(g.group_counts),
                "rare_group_candidates": len(rare_groups),
                "structural_holes": len(holes),
                "triples_examined": used_pairs,
                "pair_budget": pair_budget,
                "vetoed": len(vetoed),
            },
            "thresholds": {"gap_group_min_count": min_group, "limit": limit,
                           "confidence_high_net": 2.0, "confidence_medium_net": 1.0},
            "hot_ids": hot_ids,
            "hook": {"llm_available": self.llm is not None, "note": hook_note},
            # ---- I3：直连 A 的结果（始终存在，关闭时是空列表 + enabled=False；
            # 用"空列表"而不是"缺键"是为了让 D 的读取端不必区分两种形状，
            # 用 enabled 位来区分"没做"与"做了没结果"—— 三态纪律见 §3.4）
            "submitted_request_ids": list(submission["submitted_request_ids"]),
            "rejected_requests": list(submission["rejected_requests"]),
            "skipped_duplicate_topics": list(submission["skipped_duplicate_topics"]),
            "request_submission": submission,
            # ---- I5 检测侧摘要
            "structural_duplicates": structural,
        }
        md = self._md_head("gaps", summary, warnings)
        md += [
            f"- **二元结论：{verdict}** —— {conclusion}",
            "",
            f"- 检索范围：概念组 {len(g.group_counts)} 个（其中低频 {len(rare_groups)} 个）、"
            f"结构洞 {len(holes)} 个（检查三元组 {used_pairs} 个，预算 {pair_budget}，截断={truncated}）",
            f"- 否决项剔除 {len(vetoed)} 条；净分不足（low）{len(low_conf)} 条",
            f"- LLM 钩子：{hook_note}",
            "",
        ]
        # ---- I3/I5 的结论也进人读的 markdown：payload 只有 D 看，而"要不要把请求
        # 排进 A 的队列"是人也需要一眼确认的事（尤其是被拒的那几条）。
        md += [
            "## I3 缺口直连 A（search_requests 写入）",
            "",
            f"- 开关：**{'开启' if submit_requests else '关闭（默认）'}** —— {submission['reason']}",
            f"- 提交：{submission['submitted_request_ids'] or '（无）'}"
            f"（单次上限 {submission['max_per_run']}，全局在途上限 {submission['inflight_limit']}）",
        ]
        for r in submission["skipped_duplicate_topics"]:
            md.append(f"- 跳过重复主题：{r['topic']} —— {r['reason']}")
        for r in submission["rejected_requests"]:
            md.append(f"- 拒绝：{r.get('topic') or r.get('key')} —— {r['reason']}")
        md += [
            "",
            "## I5 结构重复概念（检测侧摘要）",
            "",
            f"- 候选 {structural['candidate_count']} 对（merge 建议 {structural['merge_proposals']} 对 / "
            f"review {structural['review_proposals']} 对，截断={structural['truncated']}）",
            f"- {structural['method_note']}",
            f"- 完整候选按需查询：`{structural['detail_tool']}`",
            "",
            "## 候选缺口（通过了否决门，且 confidence 至少 medium）",
            "",
        ]
        if not worth:
            md.append("**没有候选达到'确实有'的标准。**（这不是'找到了但没写'，而是证据不足。）")
            md.append("")
        for c in worth:
            md += [
                f"### {c['kind']}：{' ↔ '.join(c['concept_names'])}（{c['key']}，置信度 {c['confidence']}）",
                f"- 理由：{c['reason']}",
                f"- 正向信号（{c['positive_score']}）：" + ("；".join(c["positive_signals"]) or "无"),
                f"- 负向信号（-{c['negative_score']}）：" + ("；".join(c["negative_signals"]) or "无"),
                f"- 净分 {c['net_score']}；涉及关系：{', '.join(c['related_relation_ids']) or '（无）'}",
                "",
            ]
        md += ["## 被否决项（veto）剔除的候选 —— 它们**不算**“有”", ""]
        md.append(
            "否决项的语义：候选**拿不出可核实的依据**，因此无论正向分多高都不进候选。"
            "逐条列出理由，便于独立复核“证据不足”这个结论。"
        )
        md.append("")
        if not vetoed:
            md.append("（无）")
        for c in vetoed[:20]:
            md.append(
                f"- {c['kind']} {' ↔ '.join(c['concept_names'])}（净分 {c['net_score']}，"
                f"本可判 {c['confidence_deterministic']}）：被否决 —— " + "；".join(c["veto_reasons"])
            )
        md += ["", "## 净分不足（low）的候选 —— 有依据但证据偏弱", ""]
        if not low_conf:
            md.append("（无）")
        for c in low_conf[:20]:
            md.append(
                f"- {c['kind']} {' ↔ '.join(c['concept_names'])}：净分 {c['net_score']}（正 {c['positive_score']} / 负 {c['negative_score']}）"
                + ("；" + "；".join(c["negative_signals"]) if c["negative_signals"] else "")
            )
        return self._report(
            "gaps",
            request,
            {"limit": limit},
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
            truncated=truncated,
            # 关系表为空 ⇒ verdict="无" 的含义是"没得查"，不是"查过了没有"。
            # `ok` 必须如实反映这件事（与 `hottest` / `cold` 的空表分支同一口径）。
            ok_=bool(g.relations),
            error=None if g.relations else "关系表为空：没有可评估的关系，本次'无'不是'查过了没有'",
        )
