"""角色 D 的动作 `submit_gaps`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import EvidenceError

class _SubmitGaps:
    def submit_gaps(self, qid: str) -> list[str]:
        """不足则提交查询请求（调 ``research.submit_gap``）。返回新提交的 request_id 列表。

        这个方法的全部价值集中在"不重复提交"上：
        1. 先看该问题的等待集里有没有未完成的请求 —— 有就直接返回空列表
           （工具内部还会再查一次重，两道关卡不冲突：方法是"省一次调用"，
           工具是"结构上不可能重复"）；
        2. 再看预算（每问题 2 轮 / 全局 20 个，§8 待决问题 3）。
             预算用完时不提交，但把原因写进 gap_reason —— 静默地少提一个请求
        会让报告里的"已提交查询"一节与事实不符。

        Raises
        ------
        EvidenceError
            研究问题 ``qid`` 不存在（先经 :meth:`trace_question`，同一个判据）。
            与"预算用完"必须分开：前者是调用方给错了号（该停），
            后者是正常业务状态（返回空列表 + 留痕）。
        """
        ev = self.trace_question(qid)
        verdict = self.assess(qid, ev)
        if not verdict["insufficient"]:
            return []

        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None)
        if qrow is None:
            raise EvidenceError(f"研究问题 {qid} 不存在")

        still_open = self._pending_of(qrow)
        if still_open:
            self.last_submit_skip = {
                "question_id": qid,
                "reason": "已有未完成的查询请求，未重复提交",
                "open_requests": [r.get("request_id") for r in still_open],
            }
            return []

        budget = self._budget()
        used = int(budget["per_question"].get(qid, 0))
        if used >= self.max_requests_per_question:
            self._note(qid, f"[budget] 该问题已提交 {used} 次查询，达到每问题上限 "
                           f"{self.max_requests_per_question}，本轮不再提问（§8 待决问题 3）")
            return []
        if budget["remaining"] <= 0:
            self._note(qid, f"[budget] 全局查询预算已用尽（上限 {self.max_total_requests}），本轮不再提问")
            return []

        topic, desc = self._search_topic_and_desc(qrow, ev)
        criteria = "；".join(f"{c['id']}: {c['detail']}" for c in verdict["criteria"])
        data = self._call(
            "research.submit_gap",
            question_id=qid,
            topic=topic,
            mode="topical",
            description=f"{desc}；触发的可核实判据：{criteria}",
        )
        if not data:
            return []
        if data.get("duplicated"):
            self.last_submit_skip = {"question_id": qid, "reason": data.get("reason")}
            return []
        rid = data.get("request_id")
        if not rid:
            # 查重没挡下、却没有请求号 ⇒ 只剩一种可能：I7 的在途配额挡下了
            # （工具层从批 R19 起过闸门）。这一支必须留痕：静默少提一个请求会让报告里的
            # "已提交查询"一节与事实不符，而这里的"少提"是外部原因，不是 D 没判断出来。
            # 从前这里直接往下走 ⇒ 写下一条"已向 A 提交查询请求 None"的笔记（CS-1）。
            reason = str(data.get("reason") or "")
            self.last_submit_skip = {"question_id": qid, "reason": reason}
            self._note(qid, f"[inflight] 在途配额挡下了这次提问（{reason}）")
            return []
        self._note(
            qid,
            f"[submit_gap] 证据不足（触发判据 {'/'.join(c['id'] for c in verdict['criteria'])}），"
            f"已向 A 提交查询请求 {rid}（topic={topic}，mode=topical）",
        )
        return [str(rid)] if rid else []
