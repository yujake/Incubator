"""角色 D 的动作 `probe_c`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Any, Mapping

class _ProbeC:
    def probe_c(self, qid: str, qrow: Mapping[str, Any] | None = None) -> list[dict]:
        """I1：为某个研究问题现场推导参数并向 C 点菜（而不是吃套餐）。
        ## 参数从哪来
        全部由该问题自己的 ``related_concept_ids`` / ``related_relation_ids``推导，绝不照抄报告里已有的结果：
        - ``neighbors(concept_id)``：焦点是该问题的概念（最多``max_c_neighbor_queries`` 个）；- 
        ``relations_between(a, b)``：该问题概念的两两组合（最多``max_c_pair_queries`` 对）；- 
        ``contradictions(relation_ids=...)``：范围是该问题引用的关系。没有关系代号时传 ``relation_ids=None``（= C 的全
        图范围，参数里显式为 None，不假装"我限定过范围"）。
        报告是上一次分析的快照，而这个问题的当下需要可能与那次分析的 kind 完全不同 —— 这正是"让 D 能点菜，把 C 从批处理变成服务"的意义（§1 I1）。
        查询次数有界：C 是服务，不等于可以无限点单；每个问题最多几次，否则 D 的循环会被自己的查询拖住（§1 I1 的终止条件）。
        """
        if qrow is None:
            qrow = next(
                (r for r in self.store.rows("research_questions") if str(r.get("question_id")) == str(qid)), None
            ) or {}
        cids = [str(x) for x in (qrow.get("related_concept_ids") or []) if x]
        rids = sorted({str(x) for x in (qrow.get("related_relation_ids") or []) if x})
        out: list[dict] = []

        for cid in cids[: self.max_c_neighbor_queries]:
            params = {"concept_id": cid, "depth": 1}
            out.append(self._c_record("neighbors", params, self._c_call("neighbors", **params)))

        pairs: list[tuple[str, str]] = []
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                pairs.append((cids[i], cids[j]))
                if len(pairs) >= self.max_c_pair_queries:
                    break
            if len(pairs) >= self.max_c_pair_queries:
                break
        for a, b in pairs:
            params = {"a": a, "b": b, "include_inactive": True}
            out.append(self._c_record("relations_between", params, self._c_call("relations_between", **params)))

        cparams = {"relation_ids": rids or None, "limit": self.max_c_contradictions}
        out.append(self._c_record("contradictions", cparams, self._c_call("contradictions", **cparams)))
        return out
