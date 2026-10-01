"""角色 C 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_c/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import AnalysisReport, Any, D, DEFAULT_SCORE_WEIGHTS, DEFAULT_THRESHOLD_HIGH, DEFAULT_THRESHOLD_MEDIUM, Iterable, Mapping, RelationGraph, S, SERVICE_MAX_DEPTH, SUBMITTER, Sequence, Store, T, ToolRegistry, _cfg_float, _cfg_get, _cfg_int, check_conflict, interactions, json, re, tool
from .hottest import _Hottest
from .paths import _Paths
from .cold import _Cold
from .gaps import _Gaps
from .neighbors import _Neighbors
from .relations_between import _RelationsBetween
from .contradictions import _Contradictions
from .structural_duplicates import _StructuralDuplicates
from .handle import _Handle


class _Core:
    def __init__(
        self,
        store: Store,
        config: Mapping[str, Any] | None = None,
        actor: str = "agent-C",
        llm: Any = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        #: LLM 钩子。只需两个可选方法（都是鸭子类型，缺任何一个都自动回退）：
        #:   `rank_paths(payload) -> list[int]`   路径顺序（§3.3(2) 第 4 步的语义部分）
        #:   `judge_gaps(payload)  -> dict`       候选缺口是否值得研究（§3.3(4) 第 2 步）
        #: 也可以只提供 `complete(prompt) -> str`，由本模块解析 JSON 结果。
        self.llm = llm
        self._graph: RelationGraph | None = None
        self.weights: dict[str, float] = dict(DEFAULT_SCORE_WEIGHTS)
        override = self.cfg.get("score_weights")
        if isinstance(override, Mapping):
            for k, v in override.items():
                if k in self.weights:
                    try:
                        self.weights[k] = float(v)
                    except (TypeError, ValueError) as e:
                        # 原先这里是 `pass`：写错一个权重（`hop: "high"`）会静默
                        # 保留默认值 —— 报告照常产出、评分照常打印，只是口径与配置不一致，
                        # 而"口径被人改过"这件事没有任何地方会暴露。评分权重是结论的判据
                        # 本身，读不懂就必须当场炸（fail-closed），不许退回默认值。
                        raise ValueError(
                            f"score_weights[{k}]={v!r} 不是数字。权重是评分判据，"
                            "静默退回默认值会让报告口径与配置不一致而无人知道"
                        ) from e
        self.threshold_high = _cfg_float(
            self.cfg, "threshold_high", DEFAULT_THRESHOLD_HIGH, aliases=("high", "high_threshold", "score_high")
        )
        self.threshold_medium = _cfg_float(
            self.cfg, "threshold_medium", DEFAULT_THRESHOLD_MEDIUM, aliases=("medium", "medium_threshold", "score_medium")
        )
    def build_graph(self) -> RelationGraph:
        """重建并缓存关系图索引（一次构建、多次查询）。"""
        self._graph = RelationGraph.from_store(self.store)
        return self._graph
    def _g(self) -> RelationGraph:
        """取缓存的图；没有就建一次。四个分析器共享同一张图。"""
        if self._graph is None:
            return self.build_graph()
        return self._graph
    def _hot_ids(self, top_n: int | None = None) -> list[str]:
        """热门概念集合（`hottest` 的口径），用于评分里的"绕开最常见节点"项。"""
        g = self._g()
        n = top_n if top_n is not None else _cfg_int(self.cfg, "hot_top_n", 5)
        counts = g.counts()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        return [cid for cid, _ in ranked[: max(0, n)]]
    def _report(
        self,
        kind: str,
        request: str,
        params: Mapping[str, Any],
        *,
        summary: str,
        payload: Mapping[str, Any],
        markdown: str = "",
        warnings: Iterable[str] = (),
        truncated: bool = False,
        ok_: bool = True,
        error: str | None = None,
    ) -> AnalysisReport:
        rep = AnalysisReport(
            kind=kind,
            request=request,
            params=dict(params),
            summary=summary,
            payload=dict(payload),
            markdown=markdown,
            warnings=list(warnings),
            truncated=bool(truncated),
            ok=ok_,
            error=error,
            created_by=self.actor,
        )
        rep._store = self.store  # type: ignore[attr-defined]  让 report.persist() 免参数可用
        return rep
    def _md_head(self, kind: str, summary: str, warnings: Sequence[str]) -> list[str]:
        lines = [
            f"# C 分析报告：{kind}",
            "",
            f"- 生成者：`{self.actor}`",
            f"- 标题摘要：{summary}",
        ]
        if warnings:
            lines.append("- 警告：")
            lines += [f"    - {w}" for w in warnings]
        lines.append("")
        return lines
    def _relation_brief_for_report(self, g: RelationGraph, rel: Mapping[str, Any], focus: str | None = None) -> dict:
        """报告里展示关系时统一用它，避免每处各写一套字段名。"""
        cids = [str(c) for c in (rel.get("concept_ids") or [])]
        return {
            "relation_id": rel.get("relation_id"),
            "concept_ids": cids,
            "concept_names": [g.name_of(c) for c in cids],
            "other_concepts": [
                {"concept_id": c, "name": g.name_of(c)} for c in cids if focus is None or c != focus
            ],
            "description": rel.get("description") or "",
            "statement": rel.get("statement") or "",
            "quoted": bool(rel.get("quote")),
            "quote_verified": rel.get("quote_verified"),
            "status": rel.get("status"),
            "lit_id": rel.get("lit_id"),
            "page_range": rel.get("page_range") or {},
        }
    def _score_chain(
        self,
        path_nodes: Sequence[str],
        chain_ids: Sequence[str],
        rels: Sequence[Mapping[str, Any]],
        hot_ids: Iterable[str],
    ) -> dict:
        """§3.4 的信息量评分，返回可逐项打印的明细。

        为什么非要"可逐项打印"：D 拿到一条 high 路径后要判断"该不该信它"。
        如果只给一个 3.47，D 唯一能做的就是相信这个数字 —— 而数字本身没有
        说服力。给出 `ratio_true=1.00 → +2.00`、`跳数=2 → +1.20` 之后，D 可以
        自己看出"这条链之所以高，是因为两跳的引文都过了校验"，也可以反驳
        "只有两跳，推理链太短"。可解释性在这里是功能，不是装饰。
        """
        w = self.weights
        hops = len(chain_ids)
        n = max(1, len(rels))
        verified = [r.get("quote_verified") for r in rels]
        ratio_true = sum(1 for v in verified if v is True) / n
        ratio_false = sum(1 for v in verified if v is False) / n
        ratio_suspect = sum(1 for r in rels if str(r.get("status") or "") == "suspect") / n
        n_true = sum(1 for v in verified if v is True)
        n_false = sum(1 for v in verified if v is False)
        n_none = sum(1 for v in verified if v is None)
        n_suspect = sum(1 for r in rels if str(r.get("status") or "") == "suspect")
        lits = {str(r.get("lit_id") or "") for r in rels}
        n_lits = len(lits)
        desc_lens = [len(str(r.get("description") or "").strip()) for r in rels]
        avg_desc = (sum(desc_lens) / len(desc_lens)) if desc_lens else 0.0
        hot = set(hot_ids)
        off_hot = [cid for cid in path_nodes if cid not in hot]
        avoids_top = 1.0 if off_hot else 0.0

        terms = [
            {
                "name": "引文已校验比例",
                "detail": f"quote_verified=True 的跳数 {n_true}/{hops} = {ratio_true:.2f}",
                "weight": w["quote_true"],
                "contribution": w["quote_true"] * ratio_true,
            },
            {
                "name": "引文校验失败比例",
                "detail": f"quote_verified=False 的跳数 {n_false}/{hops} = {ratio_false:.2f}",
                "weight": w["quote_false"],
                "contribution": w["quote_false"] * ratio_false,
            },
            {
                "name": "suspect 比例",
                "detail": f"status=suspect 的跳数 {n_suspect}/{hops} = {ratio_suspect:.2f}",
                "weight": w["suspect"],
                "contribution": w["suspect"] * ratio_suspect,
            },
            {
                "name": "跳数",
                "detail": f"min(跳数 {hops}, 3) = {min(hops, 3)}（边际递减）",
                "weight": w["hop"],
                "contribution": w["hop"] * min(hops, 3),
            },
            {
                "name": "跨文献多样性",
                "detail": f"不同文献 {n_lits} 篇 / 跳数 {hops} = {(n_lits / hops if hops else 0):.2f}",
                "weight": w["lit_diversity"],
                "contribution": w["lit_diversity"] * ((n_lits / hops) if hops else 0.0),
            },
            {
                "name": "描述过短",
                "detail": f"平均描述长度 {avg_desc:.1f} 字符 → {'计入' if avg_desc < 12 else '不计入'}",
                "weight": w["short_desc"],
                "contribution": w["short_desc"] * (1.0 if avg_desc < 12 else 0.0),
            },
            {
                "name": "绕开最常见节点",
                "detail": (
                    f"不在热门集里的概念 {off_hot or '无'} → {'计入' if avoids_top else '不计入'}"
                ),
                "weight": w["avoid_hot"],
                "contribution": w["avoid_hot"] * avoids_top,
            },
        ]
        total = sum(t["contribution"] for t in terms)
        level = "high" if total >= self.threshold_high else ("medium" if total >= self.threshold_medium else "low")
        for t in terms:
            t["contribution"] = round(t["contribution"], 4)
        return {
            "score": round(total, 4),
            "level": level,
            "score_breakdown": {
                "inputs": {
                    "hops": hops,
                    "quote_verified_true": n_true,
                    "quote_verified_false": n_false,
                    "quote_verified_unknown": n_none,
                    "suspect": n_suspect,
                    "distinct_literature": n_lits,
                    "average_description_length": round(avg_desc, 2),
                    "concepts_outside_hot_set": off_hot,
                    "hot_set_size": len(hot),
                },
                "terms": terms,
                "total": round(total, 4),
                "thresholds": {"high": self.threshold_high, "medium": self.threshold_medium},
                "level": level,
            },
        }
    def _md_path(self, idx: int, it: Mapping[str, Any], g: RelationGraph, tag: str) -> list[str]:
        """单条路径的 markdown（含逐项评分明细 —— 见 `_score_chain` 的说明）。"""
        sb = it["score_breakdown"]
        lines = [
            f"### 路径 {idx}（{tag}信息量，score={it['score']:.2f}，{it['hops']} 跳）",
            "",
            f"- 概念链：{' → '.join(f'{n}({c})' for n, c in zip(it['concept_names'], it['concept_path']))}",
            f"- **关系代号链**：{' → '.join(it['relation_chain'])}",
            f"- 涉及文献：{', '.join(it['chain_literature_ids'])}",
        ]
        for h in it["hop_details"]:
            lines.append(
                f"    - 第 {h['hop']} 跳 {h.get('from_name', h['from'])}({h['from']}) → "
                f"{h.get('to_name', h['to'])}({h['to']})：候选 {h['candidate_count']} 条 "
                f"{h['candidate_ids']}，选中 `{h['chosen']}`"
                + ("（来自已用过的文献，但可信度/信息量更优）" if h.get("chosen_lit_already_used") else "")
            )
        lines += ["", "评分明细（为什么是这个等级）：", ""]
        for t in sb["terms"]:
            sign = "+" if t["contribution"] >= 0 else ""
            lines.append(f"- {t['name']}：{t['detail']} → {sign}{t['contribution']}")
        lines += [
            "",
            f"    合计 {sb['total']}（阈值 high>={sb['thresholds']['high']} / "
            f"medium>={sb['thresholds']['medium']}）⇒ **{sb['level']}**",
            "",
        ]
        return lines
    def _weak_assessment(
        self,
        g: RelationGraph,
        cid: str,
        rel: Mapping[str, Any],
        others: Sequence[str],
        hot_ids: set[str],
        cold_ids: set[str],
    ) -> dict:
        """§3.3(3) 的弱连接判据（全部可核实，没有一条靠语感）。

        四条判据各计 1 分（`weak_score = 得分 / 4`）：
        1. `quote_verified is not True`（含 False 与 None）：引文没被证实；
        2. `status == "suspect"`：判重存疑；
        3. 它是该概念唯一的连接：断了这个概念就彻底孤立；
        4. 另一端也很冷门：借不到力。

        为什么用"等权计数"而不是拍一个加权分：这四个信号没有客观的强弱次序，
        随便定权重会变成一个无法辩护的数字。等权 + 逐条理由字符串，读者可以
        自己决定"哪条理由在这个学科里更要紧"。

        刻意不把 `status == "rejected"` 计进来：§3.3(3) 列的四条是"弱连接"
        信号，而 rejected 的关系语义上是"已被否决"，它不是"弱"而是"不该存在"。
        把它混进弱分会让"唯一连接是 rejected"这种极端情况被稀释成一个 0.25；
        所以单独用 `has_rejected` 标出来，交给人/D 直接处理。
        """
        points = 0
        reasons: list[str] = []
        qv = rel.get("quote_verified")
        if qv is not True:
            points += 1
            reasons.append(f"引文未获证实（quote_verified={qv}）")
        if str(rel.get("status") or "") == "suspect":
            points += 1
            reasons.append("状态为 suspect（判重存疑）")
        if g.degree(cid) <= 1:
            points += 1
            reasons.append("它是该概念唯一的连接（一旦失效该概念即完全孤立）")
        peer_degree = _cfg_int(self.cfg, "cold_weak_peer_degree", 1)
        cold_peers = sorted(
            o for o in others if o in cold_ids or g.degree(o) <= peer_degree
        )
        if cold_peers:
            points += 1
            reasons.append(
                "另一端也很冷门（无法借力）："
                + "、".join(f"{g.name_of(o)}(degree={g.degree(o)})" for o in cold_peers)
            )
        return {
            "weak_points": points,
            "weak_score": round(points / 4.0, 4),
            "weak_reasons": reasons or ["四条弱判据都不成立：引文已证实、状态正常、存在多条连接、另一端是热门概念"],
            "has_rejected": str(rel.get("status") or "") == "rejected",
        }
    def _looks_like_non_concept(self, g: RelationGraph, cid: str) -> str | None:
        """"概念名明显不是概念"的可核实判据，返回理由或 None。

        只用能一眼复核的规则，不做语言模型式的判断：
        - 过长（> 24 字符且不含空格）：典型症状是整句话被当成了概念名；
        - 过短（纯 ASCII 单字母）：多半是公式符号碎片；
        - 含句读/停用词（"这个""因此""由此可见"）：抽取器的典型缺陷。
        """
        name = str((g.concept_by_id.get(cid) or {}).get("name") or "").strip()
        if not name:
            return f"{cid} 在概念表里没有名称"
        if len(name) > 24 and " " not in name:
            return f"概念名过长且无空格（{len(name)} 字符），像是整句话：{name[:24]}…"
        if len(name) == 1 and name.isascii():
            return f"概念名只有一个 ASCII 字符（{name}），像是符号碎片"
        for token in ("这个", "因此", "由此可见", "综上", "我们", "本文", "如表", "见图"):
            if token in name:
                return f"概念名含非术语成分 {token!r}：{name}"
        if re.search(r"[，。；：、,.;:!?]", name):
            return f"概念名含句读标点：{name}"
        return None
    def _concepts_relations(self, g: RelationGraph, cids: Sequence[str]) -> list[dict]:
        out: list[dict] = []
        for cid in cids:
            for rid in g.concept_relations.get(cid, []):
                rel = g.relation_by_id.get(rid)
                if rel is not None and rel not in out:
                    out.append(rel)
        return out
    def _evaluate_gap(
        self,
        g: RelationGraph,
        concepts: Sequence[str],
        *,
        kind: str,
        base_reason: str,
        common_neighbors: Sequence[str] = (),
        hot_ids: Iterable[str] = (),
    ) -> dict:
        """对一个候选缺口评估"是否确实可能有值得研究的关系"（§3.3(4) 第 2 步）。

        信号分两档，这个区分是需求"若确实有，则报告"能否成立的关键：

        - 否决项（veto）：相关关系的 `quote_verified` 全部为 False、
          概念名明显不是概念、两者已被判重（`duplicate_of` 非空）。
          这三条中的任何一条都意味着"这条候选拿不出可核实的依据"。
          它们不参与净分，而是直接把候选剔除出 `candidate_gaps`。
          为什么不能当扣分项：扣除 -0.5 之后，共同邻居、热门度、文献数这些
          正向分足以把净分抬回 medium —— 于是报告会声称"找到了值得研究的缺口"，
          而它其实一条能在原文里找到的引文都没有。这正是必须避免的
          "把没找到包装成找到了"。
        - 扣分项（仍参与净分）：引文校验部分失败、`status=suspect` 占比、
          存在 rejected、候选端仅有单一连接。这些是"证据偏弱"而非"没有证据"，
          所以扣分但不剔除。

        正向与负向信号都留下 `signals` 文本，使"为什么被否决/为什么置信度低"
        在报告里可以被反驳，而不是一句黑箱结论。
        """
        hot = set(hot_ids)
        pos = 0.0
        neg = 0.0
        pos_signals: list[str] = []
        neg_signals: list[str] = []
        veto_reasons: list[str] = []

        cn = list(common_neighbors)
        if cn:
            add = min(len(cn), 3) * 0.5
            pos += add
            pos_signals.append(
                f"结构洞信号：有 {len(cn)} 个共同邻居（{'、'.join(g.name_of(c) for c in cn)}）却无直接关系"
            )
        hot_in = [c for c in concepts if c in hot]
        if hot_in:
            add = 0.5 * len(hot_in)
            pos += add
            pos_signals.append(f"热门概念参与：{'、'.join(g.name_of(c) for c in hot_in)} 在热门集里")
        rels = self._concepts_relations(g, concepts)
        lits = {str(r.get("lit_id") or "") for r in rels}
        if len(lits) >= 2:
            pos += 0.5
            pos_signals.append(f"文献充足：相关关系分布在 {len(lits)} 篇文献里")

        # ---------------- 否决项（veto）：直接剔除，不进 candidate_gaps
        for cid in concepts:
            why = self._looks_like_non_concept(g, cid)
            if why:
                veto_reasons.append(f"概念名明显不是概念：{why}")
        if any(r.get("duplicate_of") for r in rels):
            veto_reasons.append("相关关系里有已被判重（duplicate_of 非空）的条目：这两个概念已被判定为同一个/重复关系")
        qvs = [r.get("quote_verified") for r in rels]
        if rels and all(v is False for v in qvs):
            veto_reasons.append(
                f"相关关系的引文校验**全部**失败（{len(qvs)}/{len(qvs)} 条 quote_verified=False）："
                "这条候选没有任何能在原文里逐字核实的依据"
            )

        # ---------------- 扣分项（仍参与净分）
        n_rel = len(rels)
        n_false = sum(1 for v in qvs if v is False)
        if n_rel and 0 < n_false < n_rel:
            neg += 0.5
            neg_signals.append(f"引文校验部分失败（{n_false}/{n_rel} 条）")
        n_sus = sum(1 for r in rels if str(r.get("status") or "") == "suspect")
        if n_rel and n_sus:
            neg += 0.5 * (n_sus / n_rel)
            neg_signals.append(f"status=suspect 占 {n_sus}/{n_rel}")
        if any(str(r.get("status") or "") == "rejected" for r in rels):
            neg += 0.5
            neg_signals.append("相关关系里有 status=rejected 的条目")
        peer_degree = _cfg_int(self.cfg, "cold_weak_peer_degree", 1)
        thin = [c for c in concepts if g.degree(c) <= peer_degree]
        if thin:
            neg += 0.25 * (len(thin) / max(1, len(concepts)))
            neg_signals.append(
                "候选端连接薄弱：" + "、".join(f"{g.name_of(c)}(degree={g.degree(c)})" for c in thin)
            )

        net = pos - neg
        confidence = "high" if net >= 2.0 else ("medium" if net >= 1.0 else "low")
        key = "|".join(concepts)
        return {
            "key": key,
            "kind": kind,
            "concept_ids": list(concepts),
            "concept_names": [g.name_of(c) for c in concepts],
            "common_neighbors": [{"concept_id": c, "name": g.name_of(c)} for c in cn],
            "reason": base_reason + ("；" + "；".join(pos_signals) if pos_signals else ""),
            "positive_score": round(pos, 4),
            "negative_score": round(neg, 4),
            "net_score": round(net, 4),
            "confidence": confidence,
            "confidence_deterministic": confidence,
            #: 是否通过否决门。False ⇒ 不算候选，无论净分多高（见 docstring）。
            "passed_veto": not veto_reasons,
            "vetoed": bool(veto_reasons),
            "veto_reasons": veto_reasons,
            "positive_signals": pos_signals,
            "negative_signals": neg_signals,
            "related_relation_ids": [str(r.get("relation_id")) for r in rels],
        }
    @staticmethod
    def _service_checkable(g: RelationGraph) -> tuple[bool, str]:
        """服务面能否检查：返回 `(checked, reason)`。

        `checked=False` 只留给"根本无法检查"这一种情况。在知识表为空时，
        "没有这个概念"与"概念表是空的"会被下游压成同一个结论
        （"图里没有它"），而后者其实是"知识还没有进来，问也问不出"。
        这两种情况需要 D 采取完全不同的动作（改查询 vs 等 A/B 先跑），
        所以必须用 `checked` 分开，而不是靠 reason 里的一句话。
        """
        if not g.concept_by_id:
            return False, (
                "概念表为空 ⇒ **没查**（不是'查了没有'）。"
                "此刻任何'图里没有这个概念'的结论都是假的：知识还没进来，"
                "请先让 A/B 把概念写进表里"
            )
        return True, ""
    def _relation_brief(self, g: RelationGraph, rel: Mapping[str, Any]) -> dict:
        """服务面返回关系时统一用它（字段清单是契约，不能各处各写一套）。

        `quote_verified` 原样透传（`True`/`False`/`None` 三态）—— 这里一旦"顺手"
        把 None 归一成 False，D 就无法区分"引文没校验过"与"校验失败了"，
        而这两种情况对研究决策的含义完全相反。
        """
        cids = [str(c) for c in (rel.get("concept_ids") or [])]
        return {
            "relation_id": rel.get("relation_id"),
            "concept_ids": cids,
            "concept_names": [g.name_of(c) for c in cids],
            "description": rel.get("description") or "",
            "statement": rel.get("statement") or "",
            "lit_id": rel.get("lit_id"),
            "page_range": rel.get("page_range") or {},
            "quote_verified": rel.get("quote_verified"),
            "status": rel.get("status"),
        }
    def _structural_pairs(self, g: RelationGraph) -> list[dict]:
        """`interactions.structural_duplicate_pairs` 的唯一调用口（含枚举上限配置）。

        为什么把枚举上限做成可配置：`interactions` 的上限（默认 200 对）是防 O(n²) 爆炸的，
        而"触及上限"这件事必须能测——否则"截断通知被单列"这条约束永远只有正向用例，
        而负控（通知混进 candidates）就没人拦得住。测试里把上限调到 1 即可覆盖。
        """
        mp = _cfg_get(self.cfg, "structural_duplicate_max_pairs", None)
        try:
            cap: int | None = None if mp is None else int(mp)
        except (TypeError, ValueError):
            cap = None
        return interactions.structural_duplicate_pairs(g.concepts, g.relations, max_pairs=cap)
    def _structural_duplicate_summary(self, g: RelationGraph) -> dict:
        """`gaps` payload 里的结构重复摘要（I5 检测侧，纯读、不写表）。

        为什么把检测放在 `gaps` 里也带一份：`gaps` 的候选是"应该有边却缺失"，
        而结构重复正是它的对偶问题 —— 已经有两条边（两个代号）其实是同一个东西。
        两者一起看，D 才不会一边给"缺边"的靶子、一边对重复节点视而不见。
        摘要只给计数与少量样本：完整候选走 `structural_duplicates()`，
        免得 `gaps` 的 payload 被一份可以随时再查的清单撑大（报告要可读、可存）。
        """
        pairs = self._structural_pairs(g)
        cands = [p for p in pairs if not p.get("is_truncation_notice")]
        notices = [p for p in pairs if p.get("is_truncation_notice")]
        return {
            "checked": bool(g.concept_by_id),
            "candidate_count": len(cands),
            "merge_proposals": sum(1 for p in cands if p.get("proposal") == "merge"),
            "review_proposals": sum(1 for p in cands if p.get("proposal") == "review"),
            "truncated": bool(notices),
            "sample": [
                {
                    "concept_ids": p.get("concept_ids"),
                    "concept_names": p.get("concept_names"),
                    "proposal": p.get("proposal"),
                    "name_evidence": p.get("name_evidence"),
                }
                for p in cands[:5]
            ],
            "method_note": "结构等价 ≠ 同义：只有结构证据时 proposal=review，合并决定权在 B",
            "detail_tool": "graph.structural_duplicates（按需取完整候选）",
        }
    def _submit_gap_requests(self, candidates: Sequence[Mapping[str, Any]], *, enabled: bool) -> dict:
        """把 `gaps` 的候选直接变成 A 的检索请求（I3，唯一的确定性写入路径）。

        ## 这是 `WRITE_SETS["C"]` 的受控例外（可判定的一段，不是"先这样"）

        C 是只读角色：它的写入面只有两处，且这两处的性质完全不同 ——

        | 表 | 性质 | 依据 |
        |---|---|---|
        | `analysis_reports` | C 自己的产出（登记行），合法写入 | `AnalysisReport.persist()` |
        | `search_requests` | 本条：受控例外（不是知识） | 本方法，`submit_requests=True` 才开启 |

        为什么它不构成越界（三条判据，逐条可查）：

        1. 工具面仍然全量只读。`graph.gaps` 刻意不暴露 `submit_requests`
           （见 `register_tools` 里那段注释），所以"C 的推理链不能写任何东西"
           这一条没有被破 —— 权限面（工具）与这条确定性代码路径是两件事。
        2. 写的是过程记录，不是知识。`search_requests` 是"请 A 去查一查"的请求；
           `literature` / `concepts` / `relations` 三张知识表在 C 里零写入点
           （`tests/test_agent_c_service.py::test_the_four_service_methods_do_not_touch_a_single_byte`
           与本文件的 `test_agent_c_writes_only_analysis_reports_and_never_the_knowledge_tables`
           都断言了这一点）。"绕过 B 引文逐字回验"的风险来自写知识，不来自"请求检索"。
        3. 默认关闭（`submit_requests=False`），且只能由编排层显式开启。
           默认路径上 C 的写入面就只有 `analysis_reports`。

        `capabilities.WRITE_SETS["C"]` 需要登记这条例外（登记动作在 conductor
        一侧，不在本模块）。在登记落地之前，静态写集与这里的实际行为是不一致的 ——
        而那种不一致正是本项目最恨的形态：`assert_capabilities()` 查不出来，
        只有某天有人对着表问"C 凭什么能写 search_requests"时才会暴露。

        默认关闭。开启时的全部动作都在一个 `store.tx("search_requests")` 里完成
        —— 不是"图省事"，而是因为配额判定（`admit_search_request`）与写入必须看到
        同一份在途清单：分成两个事务的话，两次判定之间另一个提交方可能已经占满配额，
        于是"闸门说可以"与"实际写进去"不再对应，配额形同虚设。

        三条闸门（缺一条都会把 A 的队列淹掉）：
        1. 只收通过 veto 且 confidence >= medium 的候选 —— 它们就是 `gaps` 里
           已经算好的 `candidate_gaps`。不达标却硬提，等于把"证据不足"洗成"去查一查"；
        2. 单次最多 `interactions.DEFAULTS["max_gap_requests_per_run"]` 条，按净分降序；
        3. 全局在途上限由 `interactions.admit_search_request` 判定，超限就拒绝
           并把理由留在 `rejected_requests` 里 —— 拒绝会把压力传导回提交方，
           而"无限排队"只会让所有请求（包括最关键的那条矛盾）一起变慢。

        主题去重与已有未完成请求比对（复用 `textutil.normalize`，不另写规范化）。
        去重放在配额闸门之前：一个重复主题的正确标签是"跳过重复"，
        而不是"因配额被拒" —— 后者会让报告把"本来就不该提交"说成"资源不够"。
        """
        max_per_run = int(interactions.DEFAULTS["max_gap_requests_per_run"])
        out: dict = {
            "enabled": bool(enabled),
            "attempted": 0,
            "max_per_run": max_per_run,
            "inflight_limit": int(interactions.DEFAULTS["max_inflight_requests"]),
            "submitted_request_ids": [],
            "rejected_requests": [],
            "skipped_duplicate_topics": [],
            "reason": "",
        }
        if not enabled:
            out["reason"] = (
                "submit_requests=False（默认）：C 不写 search_requests。"
                "C 的工具面保持**全量只读**，写入只可能来自编排层显式开启这条确定性代码路径"
            )
            return out

        eligible = [
            c
            for c in candidates
            if c.get("passed_veto") and str(c.get("confidence") or "") in ("high", "medium")
        ]
        ordered = sorted(
            eligible, key=lambda c: (-float(c.get("net_score") or 0.0), str(c.get("key") or ""))
        )
        out["attempted"] = len(ordered)
        if not ordered:
            out["reason"] = (
                "本次 gaps 没有'通过 veto 且 confidence >= medium'的候选 ⇒ 没有可提交的请求"
                "（这是'查了、没有'，不是'没查'）"
            )
            return out

        prio, prio_why = interactions.resolve_priority(SUBMITTER, None)
        with self.store.tx(
            "search_requests", actor=SUBMITTER, note=f"gaps:submit_requests(run_by={self.actor})"
        ) as tx:
            rows = tx.rows("search_requests")
            open_topics = {
                T.normalize(str(r.get("topic") or ""))
                for r in interactions.inflight_requests(rows)
            }
            open_topics.discard("")
            for cand in ordered:
                topic = "、".join(str(n) for n in (cand.get("concept_names") or []) if str(n))
                key = str(cand.get("key") or "")
                if not topic.strip():
                    out["rejected_requests"].append(
                        {"key": key, "topic": topic, "reason": "候选没有概念名，构造不出 topic；空 topic 会让 A 无从查询"}
                    )
                    continue
                tnorm = T.normalize(topic)
                if tnorm and tnorm in open_topics:
                    out["skipped_duplicate_topics"].append(
                        {
                            "key": key,
                            "topic": topic,
                            "reason": "已存在同主题的未完成请求（主题规范化后相同）⇒ 跳过，不重复排进 A 的队列",
                        }
                    )
                    continue
                if len(out["submitted_request_ids"]) >= max_per_run:
                    out["rejected_requests"].append(
                        {
                            "key": key,
                            "topic": topic,
                            "reason": (
                                f"本次 gaps 已达每轮上限 max_gap_requests_per_run={max_per_run} ⇒ 未提交。"
                                "显式拒绝而不是无限排队：无上限的队列会让最关键的那条请求也一起变慢"
                            ),
                        }
                    )
                    continue
                admit = interactions.admit_search_request(
                    rows, submitted_by=SUBMITTER, explicit_priority=prio, for_question_id=None
                )
                if not admit.get("admitted"):
                    out["rejected_requests"].append(
                        {"key": key, "topic": topic, "priority": admit.get("priority"), "reason": admit.get("reason")}
                    )
                    continue
                rid = interactions.next_prefixed_id(rows, "request_id", "r")
                row = S.SearchRequest(
                    request_id=rid,
                    timestamp=S.now_iso(),
                    topic=topic,
                    mode="topical",
                    content_description=str(cand.get("reason") or ""),
                    done=False,
                    submitted_by=SUBMITTER,
                    priority=str(admit.get("priority") or prio),
                    for_question_id=None,
                    submit_note=(
                        f"由 C.gaps 直连 A（I3）：候选 kind={cand.get('kind')}、key={key}、"
                        f"net_score={cand.get('net_score')}、confidence={cand.get('confidence')}；"
                        f"优先级理由：{prio_why}"
                    ),
                )
                row.validate()  # 早炸：schema 就在手边，别等落盘时才在 store 里炸
                tx.upsert("search_requests", row.to_dict(), note="gaps:submit_gap_request")
                out["submitted_request_ids"].append(rid)
                if tnorm:
                    open_topics.add(tnorm)

        out["reason"] = (
            f"提交 {len(out['submitted_request_ids'])} 条（上限 {max_per_run}，优先级 {prio}：{prio_why}）；"
            f"跳过重复主题 {len(out['skipped_duplicate_topics'])} 条；"
            f"拒绝 {len(out['rejected_requests'])} 条（理由逐条留在 rejected_requests 里）"
        )
        return out
    def _llm_rank_paths(self, a: str, b: str, items: Sequence[Mapping[str, Any]]) -> list[int] | None:
        """① 路径排序钩子。失败一律回退到确定性顺序，绝不因钩子而丢掉结果。

        钩子只被允许做一件事：给一个排列。它不能改分数、不能删路径 ——
        那样"可解释的确定性评分"就会被一个不可复现的模型输出悄悄替换掉。
        """
        compact = [
            {
                "index": i,
                "concepts": list(it["concept_names"]),
                "relations": list(it["relation_chain"]),
                "score": it["score"],
                "level": it["level"],
                "descriptions": [h.get("chosen_description", "") for h in it["hop_details"]],
            }
            for i, it in enumerate(items)
        ]
        try:
            fn = getattr(self.llm, "rank_paths", None)
            if callable(fn):
                out = fn({"a": a, "b": b, "paths": compact})
            elif hasattr(self.llm, "complete"):
                prompt = (
                    "下面是同一对概念之间的若干条路径。请只输出一个 JSON 数组，"
                    "按'关系链最合理'从高到低给出路径的 index，不要输出任何解释。\n"
                    + json.dumps(compact, ensure_ascii=False)
                )
                out = json.loads(str(self.llm.complete(prompt)).strip())
            else:
                return None
            if isinstance(out, Mapping):
                out = out.get("order") or out.get("indices")
            if isinstance(out, (list, tuple)):
                idx = [int(x) for x in out]
                if sorted(idx) == list(range(len(items))):
                    return idx
            return None
        except Exception:  # noqa: BLE001 - 钩子的任何异常都不该影响主流程
            return None
    def _llm_judge_gaps(self, candidates: Sequence[Mapping[str, Any]]) -> dict | None:
        """② "是否值得研究"钩子。同样只叠加、不替换确定性结论。"""
        compact = [
            {
                "key": c["key"],
                "kind": c["kind"],
                "concepts": list(c["concept_names"]),
                "reason": c["reason"],
                "confidence_deterministic": c["confidence_deterministic"],
                "net_score": c["net_score"],
            }
            for c in candidates
        ]
        try:
            fn = getattr(self.llm, "judge_gaps", None)
            if callable(fn):
                out = fn({"candidates": compact})
            elif hasattr(self.llm, "complete"):
                prompt = (
                    "下面是从关系图里找出的候选研究缺口。请只输出一个 JSON 对象，"
                    "形如 {\"<key>\": {\"worth\": true/false, \"confidence\": \"high|medium|low\", \"reason\": \"...\"}}，"
                    "不要输出任何解释文字。\n" + json.dumps(compact, ensure_ascii=False)
                )
                out = json.loads(str(self.llm.complete(prompt)).strip())
            else:
                return None
            if isinstance(out, Mapping):
                return {str(k): v for k, v in out.items()}
            return None
        except Exception:  # noqa: BLE001
            return None
    _PATH_HINTS = ("之间", "关系链", "的关系", "路径", "联系", "关联")
    _HOT_HINTS = ("最热门", "热门", "统计", "频次", "排行", "排名")
    _COLD_HINTS = ("冷门", "孤立", "被忽视", "没人研究")
    _GAP_HINTS = ("完善", "缺口", "结构洞", "补全", "缺失", "遗漏")
    @staticmethod
    def _parse_int(text: str, default: int, low: int, high: int) -> int:
        """从需求文本里取一个数字参数（如"最热门的 5 个"），取不到就用默认值。

        只在 [low, high] 内采信：需求里出现的数字多半是概念名的一部分
        （"查询 0000 与 0001"），越界就说明它不可能是 top_n。
        """
        m = re.search(r"(\d{1,4})", text)
        if not m:
            return default
        try:
            n = int(m.group(1))
        except ValueError:
            return default
        return n if low <= n <= high else default
    def _handle_paths(self, text: str) -> AnalysisReport:
        """paths 分支：从需求里抽两个概念名 → 解析成代号；解析不到就失败并列出候选。"""
        g = self._g()
        rows = list(g.concepts)
        pairs = self._extract_pair_candidates(text)
        attempts: list[dict] = []
        for raw_a, raw_b in pairs:
            ra = self._resolve_concept(rows, raw_a) if raw_a else None
            rb = self._resolve_concept(rows, raw_b) if raw_b else None
            attempts.append(
                {
                    "raw": [raw_a, raw_b],
                    "resolved": [
                        {"query": raw_a, "concept_id": ra[0] if ra else None, "name": ra[1] if ra else None},
                        {"query": raw_b, "concept_id": rb[0] if rb else None, "name": rb[1] if rb else None},
                    ],
                }
            )
            if ra and rb and ra[0] != rb[0]:
                return self.paths(
                    ra[0],
                    rb[0],
                    max_paths=_cfg_int(self.cfg, "max_paths", 5),
                    max_len=_cfg_int(self.cfg, "max_len", 4),
                    max_overlap=_cfg_float(self.cfg, "max_overlap", 0.5),
                    request=text,
                )
        # ---- 解析失败：fail 并列出候选概念名（需求明确要求）
        candidates = self._concept_candidates(g)
        parsed = [p for a in attempts for p in (a["raw"][0], a["raw"][1]) if p]
        summary = (
            "无法解析出两个已有的概念代号，因此没有执行路径查询。"
            f"从需求里抽到的候选名：{parsed or '（没抽到）'}；"
            f"现有概念候选：{'、'.join(c['name'] for c in candidates[:20])}"
            + ("…" if len(candidates) > 20 else "")
        )
        return self._report(
            "paths",
            text,
            {},
            summary=summary,
            payload={
                "parsed_candidates": parsed,
                "attempts": attempts,
                "candidate_concepts": candidates,
                "hint": "概念名必须与概念表里的名称/别名一致（只做规范化精确匹配，不做相似度归并）。",
            },
            markdown="\n".join(
                self._md_head("paths", summary, ["概念名解析失败"])
                + ["## 现有概念候选", ""]
                + [f"- {c['concept_id']} {c['name']}" for c in candidates[:50]]
            )
            + "\n",
            warnings=["概念名解析失败"],
            ok_=False,
            error="无法解析出两个概念代号",
        )
    @staticmethod
    def _extract_pair_candidates(text: str) -> list[tuple[str, str]]:
        """从需求文本里抽"两个概念名"的候选对（按可信度降序）。

        刻意抽多组而不是抽一组：中文里"A 与 B 之间的关系"和"A 和 B 之间"的
        连接词不同，英文概念名里又可能自带空格。多抽几组、逐个尝试解析，
        比写一个"完美正则"更可靠，也更符合"解析不到就如实失败"的要求 ——
        反正失败的兜底是列出候选概念，不会误导。
        """
        body = re.sub(r"[?？。！!]+$", "", (text or "").strip())
        body = re.sub(r"(?:之间|间)?\s*的?\s*(?:关系链|关系|路径|联系|关联)\s*$", "", body).strip()
        body = re.sub(
            r"^(?:请|帮我|帮忙|麻烦|我想|我要|请你)?\s*(?:查询|查一下|查|分析|查找|寻找|看看|给出|列出|看|统计|梳理|探究|研究|整理)+",
            "",
            body,
        ).strip()
        body = body.strip(" ：:，,的")
        pairs: list[tuple[str, str]] = []
        for sep in ("以及", " vs ", " VS ", " vs.", "与", "和", "跟", "同", "及", "、", ",", "vs"):
            if sep in body:
                a, _, b = body.partition(sep)
                a, b = a.strip(" 　的"), b.strip(" 　的")
                if a and b:
                    pairs.append((a, b))
        if not pairs and body:
            pairs.append((body, ""))
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out
    @staticmethod
    def _resolve_concept(rows: Sequence[dict], query: str) -> tuple[str, str] | None:
        """概念名 → `(concept_id, name)`。

        解析规则（与 `dedup.find_concept` 同一口径，不另写一套匹配）：
        1. 先走 `D.find_concept`（规范化名字 + 别名，精确匹配）；
        2. 都不中时退一步做唯一子串匹配（"群" 命中 "阿贝尔群" 的场合），
           但只有恰好一个候选命中时才采信 —— 有歧义就返回 None，
           让上层如实报告"解析不到"并列出候选，而不是替 D 猜一个。
        """
        q = (query or "").strip().strip("“”\"'《》")
        if not q:
            return None
        row = D.find_concept(list(rows), q)
        if row is None and q:
            nq = T.normalize(q)
            hits = [
                r
                for r in rows
                if nq
                and (
                    nq in (r.get("normalized_name") or T.normalize(r.get("name", "")))
                    or (r.get("normalized_name") or T.normalize(r.get("name", ""))) in nq
                )
            ]
            if len(hits) == 1:
                row = hits[0]
        if row is None:
            return None
        return str(row.get("concept_id")), str(row.get("name") or "")
    def _concept_candidates(self, g: RelationGraph) -> list[dict]:
        """现有概念清单（按 occurrences 降序，同分按代号升序）。失败报告要用它。"""
        counts = g.counts()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        return [
            {"concept_id": cid, "name": g.name_of(cid), "occurrences": v["occurrences"]}
            for cid, v in ranked
        ]
    def register_tools(self, registry: ToolRegistry) -> list[str]:
        """把四个分析器 + I1 服务面注册成工具（`graph.*`，全部 `side_effect="read"`）。

        DESIGN-TOOLS.md §1.1 把 `graph.hottest/paths/cold/gaps` 列为 C 的工具。
        它们与 `tools/graph_tools.py` 里那四个低层图查询工具共用 `graph.` 前缀：
        低层工具回答"图长什么样"，这里回答"结论是什么"；I1 新增的五个服务工具
        （neighbors / relations_between / contradictions / structural_duplicates /
        check_conflict）回答"就我现在追问的这一点，图上具体是什么情况"。

        C 的工具面必须全量只读（DESIGN-INTERACTIONS.md §2 的硬规则）：一旦 C 能写，
        它就成了绕过 B 引文逐字回验的写入路径，而那是全系统唯一能自动发现幻觉引文的地方。
        所以：
        - 这里注册的每一个工具都是 `side_effect="read"`；
        - `graph.gaps` 刻意不暴露 `submit_requests`（I3 的写入口只能由编排层直接调方法，
          见该处的注释）。

        ## 命名冲突（已解决：服务版改名 `graph.svc_*`）

        这段原先写的是"已知的命名冲突……本次不改，仍是未决项"，而下方 I1 的注册块
        已经把它解决了 —— 同一份 docstring 里两段互相矛盾（INVENTORY 4.5 第 11 条点的
        就是这处）。以实现为准（代码已经落地 `graph.svc_neighbors` /
        `graph.svc_relations_between`），这里改写成对现状的准确描述：

        - `graph.neighbors` / `graph.relations_between` 这两个名字已被低层图工具占用
          （`tools/graph_tools.py`），它们是另一套返回契约（低层给"图长什么样"）。
        - C 的服务版（三态 + 有界）因此注册为 `graph.svc_neighbors` /
          `graph.svc_relations_between`，`svc` 一眼表明"三态的服务接口（D 点菜用）"。
        - 不改低层工具（它们各有既有测试与调用方）；方法层
          `AgentC.neighbors()` / `AgentC.relations_between()` 名字不变 ——
          D 的 `_c_digest` 就是按方法层读的。
        - 为什么必须改名而不是"按注册顺序决定谁生效"：同名挂两种契约时，D 拿到的形状
          取决于注册顺序，而注册顺序是一个没人会去读的细节 —— 这正是"同名不同义"
          最典型的隐患（详见下方 I1 注册块的注释与测试
          `test_service_tool_names_do_not_collide_with_low_level_tools`）。
        """
        added: list[str] = []

        def _register(name: str, summary: str, params: dict, fn: Any, returns: str) -> None:
            if name in registry:
                return
            wrapped = tool(name, summary, params, side_effect="read", roles=("C", "D"), returns=returns)(fn)
            registry.register_function(wrapped)
            added.append(name)

        _register(
            "graph.hottest",
            "统计最热门的 top_n 个概念（出现次数口径，含代表关系与概念名翻译）。",
            {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda top_n=5: self.hottest(int(top_n)).to_dict(),
            # `ok` / `error` 必须写进返回契约：`ok=False` 表示"这次没能给出结论"
            # （概念解析不到、关系表为空…），而原因在 `error` 里 —— 契约里漏掉
            # `error`，调用方看到 ok=False 也不知道该去读哪个字段。
            "{kind, summary, payload, markdown, warnings, truncated, ok, error}",
        )
        _register(
            "graph.paths",
            "查询两个概念之间的多条低重合度路径，给出关系代号链与逐项信息量评分。",
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "minLength": 4, "maxLength": 4},
                    "b": {"type": "string", "minLength": 4, "maxLength": 4},
                    "max_paths": {"type": "integer", "minimum": 1, "maximum": 50},
                    "max_len": {"type": "integer", "minimum": 1, "maximum": 8},
                    "max_overlap": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            lambda a, b, max_paths=5, max_len=4, max_overlap=0.5: self.paths(
                a, b, max_paths=int(max_paths), max_len=int(max_len), max_overlap=float(max_overlap)
            ).to_dict(),
            "{kind, summary, payload.paths[...score_breakdown...], markdown, warnings, truncated, ok, error}",
        )
        _register(
            "graph.cold",
            "研究冷门概念：degree 升序列出，标出与热门概念的连接强度，单独给出'冷门但连接强'。",
            {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda top_n=5: self.cold(int(top_n)).to_dict(),
            "{kind, summary, payload.entries/undervalued_ids/isolated, markdown, warnings, truncated, ok, error}",
        )
        _register(
            "graph.gaps",
            "完善关系图：找低频概念组与结构洞，给出'确实有/证据不足'的二元结论与候选缺口。",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda limit=10: self.gaps(int(limit)).to_dict(),
            "{kind, summary, payload.verdict/candidate_gaps, markdown, warnings, truncated, ok, error}",
        )
        # `graph.gaps` 刻意不暴露 `submit_requests`（I3 的写入口）：
        # 本工具声明的是 `side_effect="read"`，而 `submit_requests=True` 会往
        # `search_requests` 写行。一个声明"只读"却可能写盘的工具，会让整张权限表
        # 变成一句空话 —— 而权限表是"哪种副作用需要审批"的唯一依据。
        # I3 只由编排层直接调 `AgentC.gaps(submit_requests=True)` 开启。

        # ---- I1 服务面工具（同步、只读、有界、三态）。让 D 能"点菜"：
        # 低层 graph.* 回答"图长什么样"，分析器回答"结论是什么"，这一组回答
        # "就我现在追问的这一点，图上具体是什么情况"。
        # 命名冲突（已处理）：服务版不能叫 `graph.neighbors` /
        # `graph.relations_between` —— 这两个名字已被 `tools/graph_tools.py` 的
        # 低层工具占用，而它们的返回形状不同
        # （低层给 `{degree, neighbors[]}`，服务版给 `{checked, nodes[], truncated}`）。
        # 同一个名字挂两种契约，结果取决于注册顺序 —— 而注册顺序
        # 是一个没人会去读的细节。这正是本项目最恨的"同名不同义"。
        # 服务版因此改名为 `graph.svc_*`：`svc` 一眼表明它是
        # 三态的服务接口（D 点菜用），而不是“图长什么样”的低层查询。
        # 方法层 `AgentC.neighbors()` / `AgentC.relations_between()` 名字不变 ——
        # D 的 `_c_digest` 就是按方法层读的。
        _register(
            "graph.svc_neighbors",
            "某概念的 depth 跳邻域（有界 BFS；超 max_nodes 返回 truncated=True 而不是静默截断）。"
            "查不到该代号时 checked=True 且 reason 说明'不在概念表里'，checked=False 只表示'根本没查'。",
            {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "minLength": 4, "maxLength": 4},
                    "depth": {"type": "integer", "minimum": 1, "maximum": max(1, SERVICE_MAX_DEPTH)},
                    "max_nodes": {"type": "integer", "minimum": 1},
                },
                "required": ["concept_id"],
                "additionalProperties": False,
            },
            lambda concept_id, depth=1, max_nodes=None: self.neighbors(
                concept_id, depth=int(depth), max_nodes=(None if max_nodes is None else int(max_nodes))
            ),
            "{checked, concept_id, depth, nodes[], edges[], truncated, empty, reason}",
        )
        _register(
            "graph.svc_relations_between",
            "两个概念之间的全部关系（三态：checked=False 表示没查，relation_ids=[] 且 empty=True "
            "表示查了没有）；include_inactive=False 只保留 status=active 的关系。",
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "minLength": 4, "maxLength": 4},
                    "b": {"type": "string", "minLength": 4, "maxLength": 4},
                    "include_inactive": {"type": "boolean"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            lambda a, b, include_inactive=True: self.relations_between(
                a, b, include_inactive=bool(include_inactive)
            ),
            "{checked, a, b, relation_ids[], relations[], empty, filtered_out, reason}",
        )
        _register(
            "graph.contradictions",
            "矛盾检查（判据全部来自 interactions.detect_contradictions）。给了 relation_ids 就只扫这些 "
            "（I2 的'只复核这两个具体的关系'），否则扫全部关系。method=literal，只做字面判据；"
            "结果按 strength 分档（strong 才可作为研究线索，weak 假阳性极高，仅供参考），"
            "并给出 strong_count / weak_count。",
            {
                "type": "object",
                "properties": {
                    "relation_ids": {"type": "array"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": [],
                "additionalProperties": False,
            },
            lambda relation_ids=None, limit=None: self.contradictions(
                relation_ids=relation_ids, limit=(None if limit is None else int(limit))
            ),
            "{checked, scope, scanned, contradictions[], strong_count, weak_count, truncated, method, method_note, reason}",
        )
        _register(
            "graph.structural_duplicates",
            "结构重复概念候选（I5 检测侧）：邻域完全相同且彼此无直接关系。只有结构证据时 "
            "proposal=review（**不得据此合并**），合并决定权在 B。截断通知单独放在 truncation_notice。",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1}},
                "required": [],
                "additionalProperties": False,
            },
            lambda limit=None: self.structural_duplicates(limit=(None if limit is None else int(limit))),
            "{checked, candidates[], truncation_notice, truncated, scanned_concepts, method, reason}",
        )
        _register(
            "graph.check_conflict",
            "I6 写入期一致性闸门（**纯函数**，全项目唯一实现 interactions.check_conflict）："
            "判断一条草稿关系与给定已有关系是否矛盾。签名里没有 store —— B 在自己的事务内调用它，"
            "若它去查 store 就是锁重入/死锁。**省略 existing_relations 表示'没能力检查'（checked=False），"
            "绝不等于'检查过、不冲突'**。",
            {
                "type": "object",
                "properties": {
                    "draft_relation": {"type": "object"},
                    "existing_relations": {"type": "array"},
                },
                "required": ["draft_relation"],
                "additionalProperties": False,
            },
            lambda draft_relation, existing_relations=None: check_conflict(
                draft_relation, existing_relations=existing_relations
            ),
            "{checked, conflict, conflicts_with[], reason, method, scope, compared}",
        )
        return added


class AgentC(_Hottest, _Paths, _Cold, _Gaps, _Neighbors, _RelationsBetween, _Contradictions, _StructuralDuplicates, _Handle, _Core):
    """关系分析智能体。构造时 `llm=None` 即完全确定性（默认，也是可测试的路径）。"""



if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_c`（或设 PYTHONPATH=src 后在任意目录执行）
    # 说明：本仓库的 tools/ 目录没有 __init__.py（那是别人的交付物边界），
    # 靠 Python 3 的命名空间包机制导入。若在某些工具链下 `python -m` 不成立，
    # 用：python -c "import sys; sys.path.insert(0,'.'); from agentflow import agent_c; agent_c._selftest()"
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        # 控制台编码重配失败无所谓：它只影响打印中文时的字形，不影响任何一条自检结论
        # （重定向到文件/管道时就会走到这里）。这是"有理由地忽略"，不是静默吞掉 ——
        # R001 要求的正是把这两件事区分开。
        pass

    from ..tools.base import ToolRegistry
    from ..tools.graph_tools import register as register_graph_tools
    from ..tools.trace_tools import register as register_trace_tools

    CHECKS: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        CHECKS.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    def make_store(tag: str) -> Store:
        """临时工作区。优先系统临时目录；被沙箱拒绝时退到仓库内的 demo/ 目录。"""
        try:
            root = Path(tempfile.mkdtemp(prefix=f"agentflow_agentc_{tag}_"))
        except OSError:
            root = Path(__file__).resolve().parents[2] / "demo" / f"agentc_selftest_{tag}"
        st = Store(root)
        st.init(force=True)
        return st

    # ============================================================ 数据集
    # 至少 6 个概念、8 条关系；0000(群) 与 0002(域) 之间有 2 跳与 3 跳两条以上
    # 不同长度的路径；含一条 quote_verified=False（0002 号关系）与一条
    # status=suspect（0006/0011 号关系），用来验证评分确实会降级。
    def build_dataset(st: Store) -> None:
        concepts = [
            ("0000", "群", "带二元运算且满足结合律的集合"),
            ("0001", "阿贝尔群", "交换的群"),
            ("0002", "域", "乘法可交换的除环"),
            ("0003", "交换环", "乘法可交换的环"),
            ("0004", "模", "环在阿贝尔群上的作用"),
            ("0005", "理想", "环的加法子群且对乘法封闭"),
            ("0006", "孤立概念", "与任何概念都没有关系的概念"),
            ("0007", "子群", "群的非空子集且在运算下封闭"),
            ("0008", "环同态", "保持加法与乘法运算的映射"),
            ("0009", "素理想", "商环为整环的理想"),
        ]
        def rel(rid, cids, desc, lit, qv, status="active", page=None):
            return {
                "relation_id": rid,
                "concept_ids": sorted(cids),
                "description": desc,
                "lit_id": lit,
                "page_range": page or {"start": 1, "end": 1, "label": "p. 1"},
                "quote": f"原文引文 {rid}",
                "quote_normalized": f"原文引文 {rid}",
                "quote_verified": qv,
                "statement": desc,
                "status": status,
                "concept_group_key": "|".join(sorted(cids)),
            }

        relations = [
            rel("0000", ["0000", "0001"], "阿贝尔群是一种交换的群", "0000", True),
            rel("0001", ["0001", "0002"], "每个域都是阿贝尔群", "0001", True),
            # ↓ 引文校验失败：评分必须因此降级
            rel("0002", ["0000", "0003"], "交换环的加法群是阿贝尔群", "0002", False),
            rel("0003", ["0002", "0003"], "域是交换环", "0003", True),
            rel("0004", ["0000", "0004"], "模是群在环上的作用", "0004", True),
            rel("0005", ["0004", "0005"], "理想使模的构造成为可能", "0005", None),
            # ↓ status=suspect 且引文无法校验：评分必须因此降级
            rel("0006", ["0002", "0005"], "理想与商环的对应关系", "0006", None, status="suspect"),
            rel("0007", ["0000", "0005"], "群作用下的不变量", "0006", True),
            rel("0008", ["0001", "0004"], "阿贝尔群上的模结构", "0001", True),
            # 一条涉及 3 个概念的关系：产生 3 对边，共享同一个 relation_id
            rel("0009", ["0002", "0004", "0005"], "域上模与理想的三元关系", "0007", True),
            # 冷门概念 0007（子群）与两个热门概念之间的弱连接（低信息量路径的素材）
            rel("0010", ["0000", "0007"], "子群判定", "0002", False, status="suspect"),
            rel("0011", ["0007", "0002"], "待查", "0002", None, status="suspect"),
            # 一条3 跳且与前面几条 2 跳路径重合度低（Jaccard 0.4）的链：
            # 群 -环同态- 素理想- 域。用来验证"不同长度的路径"与"多跳=更多推理链"。
            rel("0012", ["0000", "0008"], "环同态保持群的加法运算结构", "0008", True),
            rel("0013", ["0008", "0009"], "素理想在环同态下的原像性质", "0009", True),
            rel("0014", ["0009", "0002"], "域中的素理想只有零理想这一个", "0010", None),
        ]
        literatures = [
            {"lit_id": "0000", "title": "代数结构导论", "type": "M", "summary": "教材", "path": "l0.txt", "processed": True, "year": 2001},
            {"lit_id": "0001", "title": "群论讲义", "type": "M", "summary": "讲义", "path": "l1.txt", "processed": True, "year": 1998},
            {"lit_id": "0002", "title": "环与模", "type": "M", "summary": "专著", "path": "l2.txt", "processed": True, "year": 2010},
            {"lit_id": "0003", "title": "域论初步", "type": "J", "summary": "论文", "path": "l3.txt", "processed": True, "year": 2015},
            {"lit_id": "0004", "title": "模论", "type": "M", "summary": "专著", "path": "l4.txt", "processed": True, "year": 2005},
            {"lit_id": "0005", "title": "理想与商环", "type": "J", "summary": "论文", "path": "l5.txt", "processed": True, "year": 2012},
            {"lit_id": "0006", "title": "群作用", "type": "J", "summary": "论文", "path": "l6.txt", "processed": True, "year": 2018},
            {"lit_id": "0007", "title": "三元关系研究", "type": "J", "summary": "论文", "path": "l7.txt", "processed": True, "year": 2020},
            {"lit_id": "0008", "title": "环同态", "type": "M", "summary": "专著", "path": "l8.txt", "processed": True, "year": 2003},
            {"lit_id": "0009", "title": "素理想与局部化", "type": "J", "summary": "论文", "path": "l9.txt", "processed": True, "year": 2016},
            {"lit_id": "0010", "title": "域论续", "type": "J", "summary": "论文", "path": "l10.txt", "processed": True, "year": 2019},
        ]
        (st.library).mkdir(parents=True, exist_ok=True)
        (st.library / "l0.txt").write_text(
            "An abelian group is a group in which the commutative law holds.\n", encoding="utf-8"
        )
        concept_rows = []
        for cid, name, definition in concepts:
            concept_rows.append(
                {
                    "concept_id": cid,
                    "name": name,
                    "definition": definition,
                    "normalized_name": T.normalize(name),
                    "related_concepts": D.derive_related_concepts(cid, relations),
                    "created_at": S.now_iso(),
                }
            )
        with st.tx("concepts", "relations", "literature", actor="selftest", note="fixture") as tx:
            for r in concept_rows:
                tx.upsert("concepts", r)
            for r in relations:
                tx.upsert("relations", r)
            for r in literatures:
                tx.upsert("literature", r)

    print("=" * 72)
    st = make_store("main")
    build_dataset(st)
    print(f"[1] 临时工作区 {st.root}")
    print(f"    概念 {len(st.rows('concepts'))} 关系 {len(st.rows('relations'))} 文献 {len(st.rows('literature'))}")

    c = AgentC(st, config={"high": 3.0, "medium": 1.5}, actor="agent-C-selftest")
    g = c.build_graph()
    s = g.summary()
    print(f"[2] build_graph：节点={s['concept_count']} 关系={s['relation_count']} 两两边={s['pair_count']} "
          f"孤立={s['isolated_concepts']} 校验分布={s['quote_verified_counts']}")

    print("[3] 工具注册（低层图工具 + 溯源工具 + C 分析工具），并确认全是 read")
    reg = ToolRegistry(name="agentc-selftest")
    # 绑定角色（`P-14`）：本自检只调 `graph.*` / `trace.*`，那些工具的 `roles` 是 `("C","D")`，
    # 而这张注册表代表的是 C（只读）。不绑的话下面每一处 `reg.call` 都会以
    # "调用方没有声明角色"失败 —— 只读约束的刀不许靠"没写"来拿。
    reg.bound_role = "C"
    low = register_graph_tools(reg, store=st)
    tr = register_trace_tools(reg, store=st)
    ana = c.register_tools(reg)
    print(f"    graph 低层={low}")
    print(f"    trace   ={tr}")
    print(f"    分析器  ={ana}")
    print(f"    全部只读={all(reg.get(n).side_effect == 'read' for n in reg.names())}（共 {len(reg.names())} 个工具）")
    print(f"    graph.build -> {reg.call('graph.build').data['concept_count']} 个概念")

    print("[4] hottest(top_n=3)：出现次数 + 关系条数 + 概念组次数 + 代表关系")
    hr = c.hottest(top_n=3, request="统计最热门的 3 个概念")
    print(f"    summary: {hr.summary}")
    for e in hr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: occ={e['occurrences']} rel={e['relation_count']} grp={e['group_count']}")
        for r in e["representative_relations"]:
            print(f"        代表关系 {r['relation_id']} qv={r['quote_verified']} {r['status']} {r['description']!r}")
    check("hottest 命中概念名翻译", all(e["name"] and "(" not in e["name"] for e in hr.payload["entries"]))
    check("hottest 排序稳定（同分按 concept_id 升序）",
          hr.payload["hot_ids"] == sorted(hr.payload["hot_ids"], key=lambda x: (-g.counts()[x]["occurrences"], x)))

    print("[5] paths('0000','0002')：图搜索 → Jaccard 去重 → 逐跳重选关系 → 评分 → 分流")
    # 这里刻意用 max_paths=8（默认是 5）：按"长度升序"筛完后，2 跳路径恰好有 5 条，
    # 默认值会把 3 跳的那条挤到 dropped_by_max_paths 里，看不到"不同长度的路径"。
    # 这也顺带说明了 max_paths 是一个真实的展开上限，而不是装饰参数。
    P_MAX = 8
    pr = c.paths("0000", "0002", max_paths=P_MAX, max_len=4, max_overlap=0.5, request="查询 群 与 域 之间的关系")
    sh = pr.payload["search"]
    dd = pr.payload["dedup"]
    print(f"    summary: {pr.summary}")
    print(f"    图搜索：raw={sh['raw_path_count']} 截断={sh['truncated']} reasons={sh['truncation_reasons']} 预算={sh['budget_used']}/{sh['node_budget']}")
    print(f"    **未筛选前**的原始路径集合（按跳数分布 {sh['raw_paths_by_hops']}）：")
    for p in sh["raw_paths"]:
        print(f"      {'→'.join(p)}（{len(p) - 1} 跳）")
    print(f"    去重：保留={dd['kept_after_overlap_filter']} 展开={dd['selected_for_report']} 因重合丢弃={len(dd['dropped_by_overlap'])} 因max_paths丢弃={len(dd['dropped_by_max_paths'])}")
    for d in dd["dropped_by_overlap"]:
        print(f"      丢弃 {'→'.join(d['path'])}（Jaccard={d['max_jaccard']} vs {'→'.join(d['against'])}）")
    print(f"    判决：high={pr.payload['levels']['high']} medium={pr.payload['levels']['medium']} low={pr.payload['levels']['low']}")
    for it in pr.payload["paths"]:
        print(f"    - {'→'.join(it['concept_path'])} 链={'→'.join(it['relation_chain'])} 跳={it['hops']} score={it['score']} => {it['level']}")
        for h in it["hop_details"]:
            print(f"        跳{h['hop']} {h['from']}-{h['to']} 候选{h['candidate_count']}条{h['candidate_ids']} 选中{h['chosen']}")
        for t in it["score_breakdown"]["terms"]:
            print(f"        {t['name']}: {t['detail']} -> {t['contribution']:+}")
    check("存在多条不同长度的路径（2 跳与 3 跳都有）",
          any(it["hops"] == 2 for it in pr.payload["paths"]) and any(it["hops"] == 3 for it in pr.payload["paths"]))
    print(f"    定性证据：未筛选前 3 跳路径 {sh['raw_paths_by_hops'].get('3', 0)} 条（图搜索确实找到了它们），"
          f"其中 {sum(1 for d in dd['dropped_by_overlap'] if len(d['path']) - 1 == 3)} 条因高重合被丢弃；"
          f"筛选后仍有 3 跳路径={any(it['hops'] == 3 for it in pr.payload['paths'])}")
    check("Jaccard 去重确实丢掉了高重合路径", len(dd["dropped_by_overlap"]) >= 1)
    check("三个等级都被真实触发（high/medium/low 均 > 0）",
          pr.payload["levels"]["high"] > 0 and pr.payload["levels"]["medium"] > 0 and pr.payload["levels"]["low"] > 0)
    check("引文校验失败的那条路径被降级（不是 high）",
          all(it["level"] != "high" for it in pr.payload["paths"] if "0002" in it["relation_chain"]))
    check("每条路径都有可逐项打印的 score_breakdown",
          all(len(it["score_breakdown"]["terms"]) == 7 for it in pr.payload["paths"]))
    # ---- 正文/附录/统计的分流必须按小节内容核对，而不是靠字符串计数
    # （早先这里用 "'→'.join(concept_path) in md_body" 去查，而正文渲染的是带概念名的
    #   "群(0000) → 阿贝尔群(0001)"，那个紧凑串只出现在统计段 —— 断言恒假，
    #   却"看起来"在检查正文。现在改成解析小节：正文段里不允许出现任何非 high 的路径标题。）
    def _section(md: str, start_marker: str, end_marker: str | None) -> str:
        seg = md.split(start_marker, 1)[1] if start_marker in md else ""
        if end_marker and end_marker in seg:
            seg = seg.split(end_marker, 1)[0]
        return seg

    body = _section(pr.markdown, "## 正文（仅高信息量路径）", "## 附录")
    appendix = _section(pr.markdown, "## 附录", "## 统计")
    stats_sec = _section(pr.markdown, "## 统计", "## 被重合度筛掉")
    body_high = body.count("（高信息量，score=")
    body_other = body.count("（中信息量，score=") + body.count("（低信息量，score=")
    md_high = pr.markdown.count("（高信息量，score=")
    print(f"    分流核对：正文段 high 标题 {body_high} 个 / 非 high 标题 {body_other} 个；"
          f"附录段 medium 标题 {appendix.count('（中信息量，score=')} 个；统计段低信息量行 {stats_sec.count('score=')} 个")
    check("正文只含 high 路径（段落级核对，不是字符串计数）",
          body_high == pr.payload["levels"]["high"] and body_other == 0 and appendix.count("（中信息量，score=") == pr.payload["levels"]["medium"]
          and md_high == pr.payload["levels"]["high"])
    check("附录明确标注'未达正文标准'", "未达正文标准" in pr.markdown)

    print("[6] 预算截断如实回报：node_budget=3 的 AgentC 必须给出 truncated=True 与警告")
    tiny = AgentC(st, config={"node_budget": 3}, actor="agent-C-tiny")
    tr_rep = tiny.paths("0000", "0002", request="截断自检")
    print(f"    truncated={tr_rep.truncated} reasons={tr_rep.payload['search']['truncation_reasons']} "
          f"raw={tr_rep.payload['search']['raw_path_count']} 预算={tr_rep.payload['search']['budget_used']}/3")
    print(f"    summary: {tr_rep.summary[:80]}…")
    for w in tr_rep.warnings:
        print(f"    warning: {w[:90]}…")
    check("预算截断被如实标出", tr_rep.truncated and tr_rep.payload["search"]["truncation_reasons"] == ["node_budget"])

    print("[7] '没有找到高信息量路径'必须明说：把阈值抬到 99，所有 high 都该消失")
    strict = AgentC(st, config={"high": 99.0, "medium": 1.5}, actor="agent-C-strict")
    sr = strict.paths("0000", "0002", max_paths=5, request="阈值自检")
    print(f"    summary: {sr.summary}")
    print(f"    has_high={sr.payload['has_high']} 正文里是否明说={'没有找到高信息量路径' in sr.markdown}")
    check("无 high 时明说'没有找到高信息量路径'",
          (not sr.payload["has_high"]) and ("没有找到高信息量路径" in sr.markdown) and ("没有找到高信息量路径" in sr.summary))

    print("[8] LLM 钩子（构造时传入假模型）：只重排顺序，评分与内容不变")
    class _FakeLLM:
        def rank_paths(self, payload):
            # 故意给一个逆序排列，验证"顺序被采纳、内容与分数没变"
            return list(reversed([p["index"] for p in payload["paths"]]))

        def judge_gaps(self, payload):
            return {c["key"]: {"worth": True, "confidence": "medium", "reason": "假模型复核通过"} for c in payload["candidates"]}

    hooked = AgentC(st, config={}, actor="agent-C-llm", llm=_FakeLLM())
    hr2 = hooked.paths("0000", "0002", max_paths=P_MAX, request="钩子自检")
    print(f"    used_for_ordering={hr2.payload['hook']['used_for_ordering']} note={hr2.payload['hook']['note']}")
    print(f"    第一跳链={hr2.payload['paths'][0]['relation_chain']} score={hr2.payload['paths'][0]['score']} llm_ranked={hr2.payload['paths'][0]['llm_ranked']}")
    same_scores = sorted(p["score"] for p in hr2.payload["paths"]) == sorted(p["score"] for p in pr.payload["paths"])
    check("LLM 钩子只改顺序、不改评分", hr2.payload["hook"]["used_for_ordering"] and same_scores)
    hr3 = hooked.hottest(top_n=3)
    check("无钩子的分析器（hottest）不受 LLM 影响", hr3.payload["entries"] == hr.payload["entries"])
    # 钩子抛异常时必须回退
    class _BrokenLLM:
        def rank_paths(self, payload):
            raise RuntimeError("模型挂了")

        def judge_gaps(self, payload):
            raise RuntimeError("模型挂了")
    broken = AgentC(st, config={}, llm=_BrokenLLM())
    br = broken.paths("0000", "0002", max_paths=P_MAX)
    print(f"    钩子抛异常后：used={br.payload['hook']['used_for_ordering']} warnings={[w[:40] for w in br.warnings]}")
    check("钩子失败时回退到确定性顺序且不丢结果",
          (not br.payload["hook"]["used_for_ordering"]) and len(br.payload["paths"]) == len(pr.payload["paths"]))

    print("[9] cold(top_n=2)：冷门榜、完全孤立、弱连接判据、'冷门但连接强'")
    cr = c.cold(top_n=2, request="研究冷门概念")
    print(f"    summary: {cr.summary}")
    for e in cr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: degree={e['degree']} 与热门概念的关系={len(e['relations_to_hot'])} 弱关系={len(e['weak_relations'])} undervalued={e['undervalued']}")
        for r in e["relations_to_hot"]:
            print(f"        [{r['relation_id']}] 与 {'/'.join(o['name'] for o in r['other_concepts'])} weak_score={r['weak_score']} 理由={r['weak_reasons']}")
    print(f"    完全孤立：{[x['concept_id'] + ':' + x['name'] for x in cr.payload['isolated']]}")
    print(f"    冷门但连接强：{cr.payload['undervalued_ids']}")
    check("孤立概念（degree=0）被单独归类、不进冷门榜",
          "0006" in [x["concept_id"] for x in cr.payload["isolated"]] and all(e["degree"] > 0 for e in cr.payload["entries"]))
    check("弱判据给到了理由字符串",
          all(r["weak_reasons"] for e in cr.payload["entries"] for r in e["weak_relations"]))
    check("'冷门但连接强'单独列出（0003 与热门概念 0002 的连接引文已证实）",
          "0003" in cr.payload["undervalued_ids"])

    print("[10] gaps(limit=5)：低频概念组 + 结构洞 + 二元结论")
    gr = c.gaps(limit=5, request="完善关系图，找结构洞")
    print(f"    verdict={gr.payload['verdict']} has_candidates={gr.payload['has_candidates']}")
    print(f"    conclusion: {gr.payload['conclusion']}")
    print(f"    检索范围={gr.payload['searched']} truncated={gr.truncated}")
    for cg in gr.payload["candidate_gaps"][:5]:
        print(f"    候选[{cg['kind']}] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 置信度={cg['confidence']}")
        print(f"        理由={cg['reason']}")
    print(f"    被否决（low）{len(gr.payload['low_confidence_candidates'])} 条，示例理由：")
    for cg in gr.payload["low_confidence_candidates"][:3]:
        print(f"      - {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("gaps 给出明确二元结论", gr.payload["verdict"] in ("有", "无"))
    check("candidate_gaps 只收 medium 以上置信度",
          all(x["confidence"] in ("high", "medium") for x in gr.payload["candidate_gaps"]))

    print("[11] gaps 的'证据不足'路径：候选只有'引文全失败'这类依据时，否决项必须直接剔除，不许包装成'找到了'")
    st2 = make_store("nogap")
    with st2.tx("concepts", "relations", "literature", actor="selftest", note="nogap") as tx:
        for cid, name in [
            ("0000", "这是一整句话并不是概念因为它确实太长了甲"),
            ("0001", "这是一整句话并不是概念因为它确实太长了乙"),
            ("0002", "桥"),
        ]:
            tx.upsert("concepts", {"concept_id": cid, "name": name, "definition": "", "normalized_name": T.normalize(name), "related_concepts": []})
        for rid, cids in [("0000", ["0000", "0002"]), ("0001", ["0001", "0002"])]:
            tx.upsert(
                "relations",
                {
                    "relation_id": rid,
                    "concept_ids": sorted(cids),
                    "description": "可疑关系",
                    "lit_id": "0000",
                    "page_range": {"start": 1, "end": 1, "label": "p. 1"},
                    "quote": "",
                    "quote_verified": False,
                    "status": "active",
                    "concept_group_key": "|".join(sorted(cids)),
                },
            )
        tx.upsert("literature", {"lit_id": "0000", "title": "样例", "type": "M", "summary": "", "path": None, "processed": True})
    c2 = AgentC(st2, config={}, actor="agent-C-nogap")
    g2 = c2.gaps(limit=5, request="完善关系图")
    print(f"    verdict={g2.payload['verdict']}")
    print(f"    conclusion: {g2.payload['conclusion']}")
    print(f"    候选={len(g2.payload['candidate_gaps'])} 否决={len(g2.payload['vetoed_candidates'])} "
          f"净分不足={len(g2.payload['low_confidence_candidates'])} "
          f"结构洞={g2.payload['searched']['structural_holes']} 低频组={g2.payload['searched']['rare_group_candidates']}")
    for cg in g2.payload["vetoed_candidates"][:4]:
        print(f"      - [veto] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} "
              f"（本可判 {cg['confidence_deterministic']}）理由={'；'.join(cg['veto_reasons'])}")
    for cg in g2.payload["low_confidence_candidates"][:3]:
        print(f"      - [low ] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("证据不足时 verdict='无' 且候选为空",
          g2.payload["verdict"] == "无" and g2.payload["candidate_gaps"] == [] and "证据不足" in g2.payload["conclusion"])
    check("否决项生效：'引文全部失败/名字不是概念'的候选被 veto 而不是靠扣分压低",
          len(g2.payload["vetoed_candidates"]) > 0 and all(c["veto_reasons"] for c in g2.payload["vetoed_candidates"]))
    check("veto 候选仍在报告里逐条留理由（不是静默丢弃）",
          "被否决项（veto）剔除的候选" in g2.markdown and all(c["veto_reasons"][0] in g2.markdown for c in g2.payload["vetoed_candidates"][:1]))

    print("[12] trace 工具与报告联动：关系代号链 → L1 表述 → L3 正文（按需）")
    chain = pr.payload["paths"][0]["relation_chain"]
    tch = reg.call("trace.chain", relation_ids=list(chain))
    print(f"    trace.chain({chain}) ok={tch.ok}")
    for line in tch.data["chain_text"].splitlines():
        print(f"      {line}")
    l1 = reg.call("trace.relation", relation_id=chain[0])
    print(f"    trace.relation({chain[0]}) 概念名={l1.data['concept_names']} 页码={l1.data['page_range']} 三态={l1.data['quote_verified_label']}")
    l3 = reg.call("trace.literature", lit_id=l1.data["lit_id"], max_chars=200)
    print(f"    trace.literature({l1.data['lit_id']}) status={l3.data['status']} 正文={l3.data['text'][:48]!r}")
    l3b = reg.call("trace.literature", lit_id="0003")
    print(f"    trace.literature(0003，只登记了路径没落文件) status={l3b.data['status']}")
    check("链条溯源可用且下钻 L3 如实报告状态", tch.ok and l3.data["status"] == "ok" and l3b.data["status"] == "file_missing")

    print("[13] persist()：reports/<id>-<kind>.md + analysis_reports 登记行")
    info = pr.persist()
    print(f"    {info}")
    row = st.rows("analysis_reports")[0]
    print(f"    登记行：id={row['report_id']} kind={row['kind']} request={row['request']!r} path={row['markdown_path']}")
    print(f"    summary={row['summary'][:60]}…")
    md_file = st.root / info["markdown_path"]
    print(f"    文件存在={md_file.exists()} 大小={md_file.stat().st_size} 字节；payload 键={sorted(row['payload'].keys())[:6]}…")
    check("persist 落盘且登记行一致",
          row["report_id"] == info["report_id"] and row["markdown_path"] == info["markdown_path"] and md_file.exists())
    no_persist = c.handle("随便说点什么不相干的话")
    try:
        no_persist.persist()
        check("kind='unknown' 被拒绝登记", False)
    except ValueError as exc:
        print(f"    拒绝登记 unknown：{exc}")
        check("kind='unknown' 被拒绝登记", True)
    csv = c.hottest(top_n=2).persist()
    print(f"    第二份报告：{csv}")

    print("[14] handle() 关键词分派（确定性）")
    cases = [
        ("统计最热门的 5 个概念", "hottest"),
        ("查询 群 与 域 之间的关系", "paths"),
        ("研究冷门概念", "cold"),
        ("完善关系图，找缺失的结构洞", "gaps"),
    ]
    for text, want in cases:
        rep = c.handle(text)
        print(f"    {text!r} -> kind={rep.kind} ok={rep.ok} summary={rep.summary[:56]}…")
        check(f"handle 分派 {text!r} → {want}", rep.kind == want and rep.ok)
    bad = c.handle("查询 群 与 不存在的概念 之间的关系")
    print(f"    解析失败示例：ok={bad.ok} error={bad.error}")
    print(f"    summary={bad.summary}")
    print(f"    候选概念（前3）={[x['name'] for x in bad.payload['candidate_concepts'][:3]]}")
    check("概念解析不到时 fail 并列出候选概念",
          (not bad.ok) and bad.error and len(bad.payload["candidate_concepts"]) == len(g.concept_by_id))
    unk = c.handle("帮我看看这个怎么样")
    check("未命中关键词时如实说无法分派", (not unk.ok) and "无法分派" in unk.summary)

    # ============================================================ I1 服务面
    print("[15] I1 服务面：neighbors / relations_between / contradictions / structural_duplicates")
    kn_before = {n: (st.data / f"{n}.json").read_bytes() for n in ("concepts", "relations", "literature")}
    nb1 = c.neighbors("0000", depth=1)
    nb2 = c.neighbors("0000", depth=2)
    nbt = c.neighbors("0000", depth=1, max_nodes=2)
    nbx = c.neighbors("9999")
    rb1 = c.relations_between("0000", "0001")
    rb0 = c.relations_between("0000", "0006")  # 0006 是孤立概念
    kn_after = {n: (st.data / f"{n}.json").read_bytes() for n in ("concepts", "relations", "literature")}
    print(f"    neighbors(0000,depth=1)：{[(n['concept_id'], n['distance']) for n in nb1['nodes']]}")
    print(f"    neighbors(0000,depth=2) 的 2 跳节点："
          f"{[n['concept_id'] for n in nb2['nodes'] if n['distance'] == 2]}")
    print(f"    neighbors(max_nodes=2)：truncated={nbt['truncated']} 节点数={len(nbt['nodes'])} 理由={nbt['reason'][-40:]!r}")
    print(f"    neighbors(9999)：checked={nbx['checked']} empty={nbx['empty']} reason={nbx['reason'][:36]!r}…")
    print(f"    relations_between(0000,0001)：{rb1['relation_ids']}；"
          f"relations_between(0000,0006)：ids={rb0['relation_ids']} empty={rb0['empty']} checked={rb0['checked']}")
    check("neighbors 的 1 跳恰好是图索引里的直接邻居",
          {n["concept_id"] for n in nb1["nodes"] if n["distance"] == 1} == set(g.neighbors("0000"))
          and any(n["distance"] == 0 for n in nb1["nodes"]))
    check("neighbors 的 2 跳把 2 跳新节点并进来且带上 distance",
          any(n["distance"] == 2 for n in nb2["nodes"])
          and "0006" not in {n["concept_id"] for n in nb2["nodes"]})
    check("neighbors 超 max_nodes ⇒ truncated=True（不静默截断）",
          nbt["truncated"] is True and len(nbt["nodes"]) == 2 and "max_nodes" in nbt["reason"])
    check("neighbors 查不到代号 ⇒ checked=True 且说明'该代号不在概念表里'",
          nbx["checked"] is True and nbx["nodes"] == [] and "不在概念表里" in nbx["reason"])
    check("relations_between 三态：有边给 relation_ids；无边 checked=True+empty=True",
          rb1["relation_ids"] == ["0000"] and rb0["relation_ids"] == [] and rb0["empty"] is True
          and rb0["checked"] is True and "没有关系" in rb0["reason"])
    check("I1 服务面只读：三张知识表逐字节不变", kn_before == kn_after)

    # ---- 矛盾 / 结构重复：另起一个小工作区，人造"矛盾对 + 重复对"
    st4 = make_store("service")

    def _svc_rel(rid, cids, desc, lit, qv=True):
        return {
            "relation_id": rid, "concept_ids": sorted(cids), "description": desc, "lit_id": lit,
            "page_range": {"start": 1, "end": 1, "label": "p. 1"}, "quote": f"引文 {rid}",
            "quote_normalized": f"引文 {rid}", "quote_verified": qv, "statement": desc,
            "status": "active", "concept_group_key": "|".join(sorted(cids)),
        }

    with st4.tx("concepts", "relations", "literature", actor="selftest", note="service") as tx:
        for cid, name in [("0000", "群"), ("0001", "阿贝尔群"), ("0002", "环"),
                          ("0003", "环"), ("0004", "桥甲"), ("0005", "桥乙"),
                          ("0006", "孤儿甲"), ("0007", "孤儿乙")]:
            tx.upsert("concepts", {"concept_id": cid, "name": name, "definition": "d",
                                   "normalized_name": T.normalize(name), "related_concepts": []})
        for r in [
            # 人造矛盾对：同概念组，一句明确肯定、一句明确否定（才够格 strong）
            _svc_rel("0000", ["0000", "0001"], "群是阿贝尔群", "0000"),
            _svc_rel("0001", ["0000", "0001"], "群不是阿贝尔群", "0001"),
            # 结构重复对：0002/0003 邻域完全相同且名字规范化后相同 ⇒ merge
            _svc_rel("0002", ["0002", "0004"], "环与桥甲", "0000"),
            _svc_rel("0003", ["0002", "0005"], "环与桥乙", "0000"),
            _svc_rel("0004", ["0003", "0004"], "环与桥甲（另一代号）", "0000"),
            _svc_rel("0005", ["0003", "0005"], "环与桥乙（另一代号）", "0000"),
        ]:
            tx.upsert("relations", r)
    c4 = AgentC(st4, actor="agent-C-service")
    con = c4.contradictions()
    con_scoped = c4.contradictions(relation_ids=["0000", "0001"])
    sd = c4.structural_duplicates()
    # 单独用"枚举上限=1"跑一次：验证"截断通知被单列"这条约束（正向/负控都要能测）
    sd_trunc = AgentC(st4, config={"structural_duplicate_max_pairs": 1}).structural_duplicates()
    print(f"    contradictions()：checked={con['checked']} scanned={con['scanned']} "
          f"命中={[x['relation_ids'] for x in con['contradictions']]} "
          f"strong={con['strong_count']} weak={con['weak_count']} method={con['method']}")
    print(f"    contradictions(relation_ids=[0000,0001])：scanned={con_scoped['scanned']} "
          f"命中={len(con_scoped['contradictions'])}")
    print(f"    structural_duplicates()：候选={[(x['concept_ids'], x['proposal']) for x in sd['candidates']]} "
          f"truncation_notice={'有' if sd['truncation_notice'] else '无'}")
    print(f"    枚举上限=1 时：候选={len(sd_trunc['candidates'])} 条，"
          f"truncation_notice={'有' if sd_trunc['truncation_notice'] else '无'}")
    check("contradictions 命中人造矛盾对且标为 strong；method_note 声明分档与假阳性",
          con["checked"] is True and len(con["contradictions"]) == 1
          and con["contradictions"][0]["strength"] == "strong"
          and con["strong_count"] == 1 and con["weak_count"] == 0
          and con["method"] == "literal"
          and "只做字面判据，不声称能判定一般语义矛盾" in con["method_note"]
          and "strong" in con["method_note"] and "假阳性" in con["method_note"])
    check("contradictions 给了 relation_ids 就只扫这些（scanned 等于给定条数）",
          con_scoped["scope"] == "given_relation_ids" and con_scoped["scanned"] == 2
          and len(con_scoped["contradictions"]) == 1)
    check("structural_duplicates 正向：邻域相同 + 同名 ⇒ proposal=merge",
          any(x["proposal"] == "merge" and set(x["concept_ids"]) == {"0002", "0003"} for x in sd["candidates"]))
    check("structural_duplicates 负控：邻域相同但名字不同 ⇒ proposal=review 且写明'不得据此合并'",
          any(x["proposal"] == "review" and set(x["concept_ids"]) == {"0004", "0005"}
              and "不得据此合并" in x["reason"] for x in sd["candidates"]))
    check("structural_duplicates 负控：孤立概念不参与枚举",
          all("0006" not in x["concept_ids"] and "0007" not in x["concept_ids"] for x in sd["candidates"]))
    check("structural_duplicates 的截断通知与候选分开（下游不会把它当成一对概念）",
          sd_trunc["truncation_notice"] is not None
          and sd_trunc["truncation_notice"]["is_truncation_notice"] is True
          and all(not x.get("is_truncation_notice") for x in sd_trunc["candidates"]))

    # ============================================================ I3 缺口直连 A
    print("[16] I3 缺口直连 A：gaps(submit_requests=True) 的闸门与三态")
    st5 = make_store("i3")

    def _i3_fixture(target: Store) -> None:
        with target.tx("concepts", "relations", "literature", actor="selftest", note="i3") as tx:
            for i in range(4):
                tx.upsert("concepts", {"concept_id": f"{i:04d}", "name": f"概念{i}", "definition": "d",
                                       "normalized_name": T.normalize(f"概念{i}"), "related_concepts": []})
            for r in [
                _svc_rel("0000", ["0000", "0001"], "一条足够长的关系描述用于评分", "0000"),
                _svc_rel("0001", ["0000", "0002"], "一条足够长的关系描述用于评分", "0001"),
                _svc_rel("0002", ["0001", "0003"], "一条足够长的关系描述用于评分", "0000"),
            ]:
                tx.upsert("relations", r)

    _i3_fixture(st5)
    c5 = AgentC(st5, actor="agent-C-i3")
    req_before = (st5.data / "search_requests.json").read_bytes()
    rep_off = c5.gaps(submit_requests=False)
    req_after_off = (st5.data / "search_requests.json").read_bytes()
    rep_on = c5.gaps(submit_requests=True)
    rows5 = st5.rows("search_requests")
    topics5 = {"、".join(x["concept_names"]) for x in rep_on.payload["candidate_gaps"]}
    print(f"    候选={len(rep_on.payload['candidate_gaps'])} 条；"
          f"关闭时新增={len(rep_off.payload['submitted_request_ids'])} 条"
          f"（enabled={rep_off.payload['request_submission']['enabled']}）")
    print(f"    开启后新增={len(rows5)} 条："
          f"{[(r['request_id'], r['topic'], r['submitted_by'], r['priority'], r['mode']) for r in rows5]}")
    print(f"    被拒={len(rep_on.payload['rejected_requests'])} 条，"
          f"示例理由={rep_on.payload['rejected_requests'][0]['reason'][:48] if rep_on.payload['rejected_requests'] else '（无）'}…")
    check("I3 默认关闭：submit_requests=False 时一条 search_requests 都不写（逐字节不变）",
          req_before == req_after_off
          and rep_off.payload["submitted_request_ids"] == [] and rep_off.payload["request_submission"]["enabled"] is False)
    check("I3 正向：新增 ≤3 条，且 submitted_by/priority/mode/topic 全部合规",
          0 < len(rows5) <= 3
          and all(r["submitted_by"] == "agent-C" and r["priority"] == "medium"
                  and r["mode"] == "topical" and r["topic"] in topics5 and not r["done"] for r in rows5))

    st6 = make_store("i3gate")
    _i3_fixture(st6)
    with st6.tx("search_requests", actor="selftest", note="i3gate") as tx:
        for i in range(20):
            row = S.SearchRequest(
                request_id=f"r-{i + 1:04d}", timestamp=S.now_iso(), topic=f"占位主题{i}",
                mode="topical", submitted_by="agent-D",
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict())
    gate_before = (st6.data / "search_requests.json").read_bytes()
    rep_gate = AgentC(st6, actor="agent-C-i3gate").gaps(submit_requests=True)
    print(f"    在途 20/20（上限）时：新增={len(rep_gate.payload['submitted_request_ids'])} 条，"
          f"被拒={len(rep_gate.payload['rejected_requests'])} 条")
    check("I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由",
          rep_gate.payload["candidate_gaps"]
          and rep_gate.payload["submitted_request_ids"] == []
          and gate_before == (st6.data / "search_requests.json").read_bytes()
          and len(rep_gate.payload["rejected_requests"]) == len(rep_gate.payload["candidate_gaps"])
          and all("已达上限" in r["reason"] for r in rep_gate.payload["rejected_requests"]))

    print("=" * 72)
    failed = [lbl for lbl, okk in CHECKS if not okk]
    print(f"自检断言：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    if failed:
        for lbl in failed:
            print(f"  FAILED: {lbl}")
    print("SELF-CHECK " + ("DONE" if not failed else "FAILED"))
