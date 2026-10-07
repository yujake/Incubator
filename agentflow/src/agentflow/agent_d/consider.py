"""角色 D 的动作 `consider`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations


class _Consider:
    def consider(self, qid: str) -> dict:
        """§4.1 状态机的 [3] 评估 → 分支 这一步，独立成可复用的方法。

        - 证据足够 ⇒ 把问题推进到 ``researching``（下一步就该写结论了）；
        - 证据不足 ⇒ 交给 :meth:`submit_gaps` 提问（它会查重与看预算）。

        为什么必须单独有这个方法：早先"足够"这一支什么都不做，问题就永远停在
        ``open`` —— 而 ``research()`` 只处理 ``researching``，于是证据充足的问题
        永远不会被研究、也永远不会出现在报告的"现有证据"一节里，表现为
        "D 溯源为空"。那不是工具没接上，是状态机少了一条边（§4.1 明写"足够 → [5]
        写研究报告"）。把这一支显式实现出来，问题就再也不会卡在 open。

        返回 ``{"question_id","sufficient","criteria","priority","confidence",
        "promoted","submitted"}``，供编排层记账。
        """
        ev = self.trace_question(qid)
        verdict = self.assess(qid, ev)
        result = {
            "question_id": qid,
            "sufficient": bool(verdict["sufficient"]),
            "criteria": [c["id"] for c in verdict["criteria"]],
            "priority": verdict["priority"],
            "confidence": verdict["confidence"],
            "promoted": False,
            "submitted": [],
        }
        if verdict["sufficient"]:
            # open/needs_evidence -> researching 都是合法迁移（见 research_tools.LEGAL_TRANSITIONS）
            data = self._call("research.set_status", question_id=qid, status="researching",
                              notes="[consider] 证据足够（无判据触发）=> 进入 researching，准备写结论")
            result["promoted"] = bool(data)
            if not data:
                # 工具不可用时也要让状态前进，否则问题会永远卡在 open：
                # 直接经 store 写（同一把锁，同样过 schema 校验）。
                self._promote_to_researching(qid, reason="[consider] 工具层不可用，直接推进状态")
                result["promoted"] = True
            return result
        result["submitted"] = self.submit_gaps(qid)
        return result
