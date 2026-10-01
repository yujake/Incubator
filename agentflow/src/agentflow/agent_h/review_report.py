"""角色 H 的动作 `review_report`（`goal-7f5116c1` M6：从 `agent_h.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, Mapping, _UNSPECIFIED

class _ReviewReport:
    def review_report(
        self,
        doc_id: str,
        *,
        own_errors: Any = None,
        round_no: int = 1,
        dependencies: Any = _UNSPECIFIED,
        run_evidence: Mapping[str, Any] | None = None,
        banned_words: Any = None,
        claim_counts: Mapping[str, Any] | None = None,
    ) -> dict:
        """产出 G1–G15 的完整审校报告（markdown 落盘，转发 `review.report`）。

        ## 这份报告必须以三样东西为骨架（`draft/17` §8.4）

        1. 被审版本的内容 hash（G11）：报告头写 `revision_hash`。没有它，
           报告里的"第几行/第几条"在稿件被改过之后全部失效。
        2. 零发现自证（G13）：每道报"零发现"的门都必须带"我用了什么过程、
           数出了什么数字"。只写"无问题"不合规 —— 参考体例的实测范例
           （`p6_..._REFEREE.md:48-56`）逐字写出了它扫了什么、数出了什么。
        3. 『我这一轮犯的错』一节（G15）：在报告头里，缺失则退回。

        ## `own_errors` 的三态（这是本方法最要紧的一处）

        ==================  ==========================================================
        传什么                行为
        ==================  ==========================================================
        `None`（默认/不传）  不替调用方编造：传空列表让报告生成，但在日志与返回值里
                             显式登记"本轮没有登记自身错误"（`own_errors_registered=False`）
        `[]`                 合法：显式声明"本轮零自身错误"
        非空列表              逐条写进报告头
        ==================  ==========================================================

        为什么不把 `None` 直接当成 `[]`：那会让"我没写"与"我写了『没有』"
        在报告里长得一模一样 —— 而 G15 的全部意义就是让前者不可接受。
        这里选择"生成报告 + 显式留痕"而不是抛异常，是因为 H 的审校流程
        （`review` / `verify_fixes`）不该因为报告元数据没填就整个跑不动；
        但报告里与返回值里必须看得见这件事没填。
        """
        registered = own_errors is not None
        errs = [str(x) for x in (own_errors or [])]
        params: dict[str, Any] = {
            "doc_id": str(doc_id),
            "own_errors": errs,
            "round_no": int(round_no),
        }
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        if run_evidence is not None:
            params["run_evidence"] = dict(run_evidence)
        if claim_counts is not None:
            params["claim_counts"] = dict(claim_counts)
        if banned_words is not None:
            params["banned_words"] = [str(x) for x in banned_words]
        data = self._writer("review.report", **params)
        data["own_errors_registered"] = registered
        self._emit(
            f"审校报告 doc:{doc_id} → {data.get('report_path')}："
            f"verdict={data.get('verdict')}（pass={data.get('pass_count')}、fail={data.get('fail_count')}、"
            f"unknown={data.get('unknown_count')}、not_applicable={data.get('not_applicable_count')}），"
            f"被审版本 hash={data.get('revision_hash')}，"
            + (f"自身错误已登记 {len(errs)} 条" if registered else "自身错误未登记（own_errors 缺失）")
            + f"；没查成的门={data.get('unknown_gates')}"
        )
        return data
