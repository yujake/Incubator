"""角色 D 的动作 `trace_question`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import EvidenceError, Mapping

class _TraceQuestion:
    def trace_question(self, qid: str) -> dict:
        """L1→L2（按需 L3）溯源，返回证据包（§4.3）。

        - L1：``relation_id`` → ``quote`` / ``description`` / ``page_range``；
        - L2：``concept_id`` → 概念定义 + 它参与的全部关系的表述；
        - L3：``lit_id`` → 文献元数据 + 本地文件 + 正文片段。

        L3 是按需的（贵）：只有当"证据互相矛盾"或"要写结论却没有一条
        ``quote_verified=True`` 的关系"时才下钻。这两个条件都是可核实的，
        不做"感觉需要更多细节"这种判断。

        工具调用一律走 ``self.tools.call``：如果 ``trace_tools`` 还没写好，
        本方法用的是内置降级替身（``trace_mode="fallback"``），返回的证据形状
        与真身一致，因此 D 的后续步骤不需要分支。

        Raises
        ------
        EvidenceError
            研究问题 ``qid`` 不在 ``research_questions`` 表里。显式列出
            而不是让它隐式逃逸：调用方（``pipeline``/``cli``）要能区分
            "问题号写错了"（调用方 bug，应立刻停）与"证据不足"（业务状态）。
        """
        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None)
        if qrow is None:
            raise EvidenceError(f"研究问题 {qid} 不存在")
        # 注：`last_tool_errors` 已在 `__init__` 里初始化（见那里的注释）。
        # 这里原先还有一行 `getattr(self, "last_tool_errors", [])` 的惰性兜底 ——
        # 它既是死代码，又会掩盖"有人在别处绕过 `__init__` 造对象"这种真实错误
        # （兜底之后错误消失，只留下一个莫名其妙的空列表）。故删除。

        rel_index = self._relations_by_id()
        #: 链条自身的步子（L1 的本体），按跳序排列。见 :meth:`_chain_order`。
        chain_ids = self._chain_order(qrow)
        #: 链条的概念走向（群→环同态→素理想→域），来自 C 报告的 payload；
        #: 用来给每一跳标出方向（见 :meth:`_chain_concept_path`）。
        chain_cpath = self._chain_concept_path(qrow, chain_ids) if chain_ids else []
        wanted_rids = [r for r in (qrow.get("related_relation_ids") or []) if r]
        # 概念度数不够时，把"概念当前参与的全部关系"并进候选：
        # 否则一个刚提取出来的问题（只带 0~1 条关系）会永远判成"证据不足"，
        # 而库里其实已经有相关表述了。
        #
        # 这些是 L2 上下文，不是链条本身。两者在报告里必须分开呈现：
        # 混在一个列表里，读者无法分辨"哪几条是这条链的步子、哪些只是顺带捞到的"，
        # 而"按代号溯源"的要求恰恰是让人顺着链读。判据计算仍然用全部 claims
        # （广度是判断证据够不够的依据），受限的只是呈现。
        for cid in qrow.get("related_concept_ids") or []:
            for r in rel_index.values():
                if cid in (r.get("concept_ids") or []):
                    wanted_rids.append(str(r.get("relation_id")))
        # 排序：链条自身在前且按跳序，其余按代号升序（稳定、可复现）
        ordered: list[str] = list(chain_ids) + sorted(set(wanted_rids) - set(chain_ids))
        wanted_rids = list(dict.fromkeys(ordered))

        claims: list[dict] = []
        traces: list[dict] = []
        trace_mode = "external"
        for rid in wanted_rids:
            data = self._trace_one("trace.relation", relation_id=rid)
            if data is None:
                # 工具缺失/失败 => 用本地关系行兜底（只用事实，不做推断）
                data = self._local_relation_claim(rid)
                trace_mode = "fallback"
            if data and str(data.get("source")) == "fallback":
                trace_mode = "fallback"
            if not data or data.get("found") is False:
                traces.append({"level": "L1", "tool": "trace.relation", "relation_id": rid, "found": False})
                continue
            traces.append({"level": "L1", "tool": "trace.relation", "relation_id": rid, "found": True})
            row = rel_index.get(rid) or {}
            # 概念代号：外部返回 `concepts: [{concept_id,...}]`，降级替身返回 `concept_ids: [...]`。
            # 两者都认 —— 否则 `concept_pair_key` 恒为空，§4.4 判据 3（矛盾）永远不会触发。
            cids = data.get("concept_ids")
            if not cids:
                cids = [c.get("concept_id") for c in (data.get("concepts") or []) if isinstance(c, Mapping)]
            cids = [str(c) for c in (cids or row.get("concept_ids") or []) if c]
            claims.append(
                {
                    "relation_id": rid,
                    "lit_id": data.get("lit_id") or row.get("lit_id"),
                    "concept_ids": cids,
                    "concept_names": list(data.get("concept_names") or []),
                    "quote": str(data.get("quote") or ""),
                    "description": str(data.get("description") or ""),
                    "statement": str(data.get("statement") or row.get("statement") or ""),
                    "page_range": data.get("page_range") or row.get("page_range") or {},
                    "status": data.get("status") or row.get("status"),
                    "quote_verified": data.get("quote_verified", row.get("quote_verified")),
                    "concept_pair_key": row.get("concept_pair_key"),
                    "on_path": rid in set(qrow.get("related_relation_ids") or []),
                    "in_chain": rid in chain_ids,
                    "hop": (chain_ids.index(rid) + 1) if rid in chain_ids else None,
                    # 这一跳的两个端点（按 C 的走向）；拿不到就是 None，绝不猜。
                    "hop_from": self._concept_name(chain_cpath[chain_ids.index(rid)])
                    if rid in chain_ids and len(chain_cpath) == len(chain_ids) + 1 else None,
                    "hop_to": self._concept_name(chain_cpath[chain_ids.index(rid) + 1])
                    if rid in chain_ids and len(chain_cpath) == len(chain_ids) + 1 else None,
                }
            )

        # ---- L1+：关系链（`trace.chain`）。问题若来自 C 的 paths 报告，它的
        # `related_relation_ids` 正是一条链；把整条链的表述串起来引用，是需求
        # "按代号溯源到相关表述"在链条维度上的直接体现（报告里可直接引用 chain_text）。
        #
        # 按跳序（hop order）传：`related_relation_ids` 是 schema 要求升序去重的
        # 字段，跳序在那里已经丢了；链子的真实顺序只能从 `origin`
        # （``C:paths:0000:0009->0010->0005``）里读回来。用升序的号去调 trace.chain，
        # 会得到一条"编号递增但语义断裂"的链 —— 而读者要的是能顺着读的推导过程。
        path_chains: list[dict] = []
        if len(chain_ids) >= 2 and "trace.chain" in self.tools:
            chain = self._trace_one("trace.chain", relation_ids=list(chain_ids))
            if isinstance(chain, Mapping):
                if str(chain.get("source")) == "fallback":
                    trace_mode = "fallback"
                traces.append({"level": "chain", "tool": "trace.chain", "found": True,
                               "steps": chain.get("step_count")})
                path_chains.append(
                    {
                        "relation_ids": list(chain.get("relation_ids") or []),
                        "chain_text": chain.get("chain_text") or "",
                        "missing": list(chain.get("missing") or []),
                    }
                )

        # ---- L2：概念定义 + 参与的全部关系
        l2: list[dict] = []
        all_cids: set[str] = set(qrow.get("related_concept_ids") or [])
        for c in claims:
            all_cids.update(c["concept_ids"])
        for cid in sorted(all_cids):
            # `with_relations=True`：L2 的语义就是"概念定义 + 它参与的全部关系的表述"。
            # 不显式打开的话，外部 trace_tools 默认只回定义与度数，D 就拿不到邻居的表述。
            data = self._trace_one("trace.concept", concept_id=cid, with_relations=True)
            if data is None:
                data = self._local_concept(cid)
                trace_mode = "fallback"
            elif str(data.get("source")) == "fallback":
                trace_mode = "fallback"
            if not data or data.get("found") is False:
                traces.append({"level": "L2", "tool": "trace.concept", "concept_id": cid, "found": False})
                continue
            traces.append({"level": "L2", "tool": "trace.concept", "concept_id": cid, "found": True})
            # 两种返回形状必须都认：
            #   - 外部 trace_tools：`{level:'L2', concept:{...}, counts:{relation_count:N}, relations:[...]}`
            #   - 内置降级替身：`{concept_id, name, definition, degree, relations:[...]}`
            # 早先只读扁平形状，结果外部的 degree/name/definition 全被读成空 ——
            # 判据 (b) 于是永远成立，D 会对着有充分证据的问题一直提问。
            inner = data.get("concept") if isinstance(data.get("concept"), Mapping) else {}
            counts = data.get("counts") if isinstance(data.get("counts"), Mapping) else {}
            rels = list(data.get("relations") or [])
            degree = data.get("degree")
            if degree is None:
                degree = counts.get("relation_count")
            if degree is None:
                degree = data.get("relation_count")
            if degree is None:
                degree = len(rels)
            l2.append(
                {
                    "concept_id": cid,
                    "name": data.get("name") or inner.get("name") or "",
                    "definition": data.get("definition") or inner.get("definition") or "",
                    "aliases": list(data.get("aliases") or inner.get("aliases") or []),
                    "related_concepts": list(
                        data.get("related_concepts")
                        or [n.get("concept_id") for n in (data.get("neighbors") or []) if isinstance(n, Mapping)]
                    ),
                    "degree": int(degree or 0),
                    "occurrences": counts.get("occurrences"),
                    "relations": rels,
                }
            )

        return {
            "question_id": qid,
            "question": qrow.get("question") or "",
            "origin": qrow.get("origin") or "",
            "status": qrow.get("status"),
            "priority": qrow.get("priority"),
            "related_concept_ids": list(qrow.get("related_concept_ids") or []),
            "related_relation_ids": list(qrow.get("related_relation_ids") or []),
            "chain_ids": list(chain_ids),
            "chain_concept_path": list(chain_cpath),
            "claims": claims,
            "l2": l2,
            "l3": [],
            "path_chains": path_chains,
            "traces": traces,
            "trace_mode": trace_mode,
            "warnings": list(self.last_tool_errors),
        }
