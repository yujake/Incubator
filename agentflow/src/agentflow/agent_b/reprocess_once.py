"""角色 B 的动作 `reprocess_once`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations


class _ReprocessOnce:
    def reprocess_once(self) -> dict:
        """处理一条 pending 的重抽取请求（I4）。返回一份可审计的摘要。

        `handled=False` 有两种完全不同的含义，必须能分开（三态纪律）：

        - ``skipped_reason="no_pending_reprocess"`` —— 表里确实没有待办（没做）；
        - ``skipped_reason=None`` 且 ``error`` 非空 —— 领到了但处理失败：请求仍是
          `pending`（留给租约过期后重试），绝不标 done。

        ``rejected`` 列出本次被准入闸门拒掉的请求：它们不是"没做"，
        而是"明确判定不该做"，理由写进了 `result_note`。
        """
        claimed, rejected = self._claim_reprocess()
        if claimed is None:
            return {
                "handled": False,
                "reprocess_id": None,
                "rejected": rejected,
                "skipped_reason": "no_pending_reprocess" if not rejected else None,
            }
        rid = str(claimed.get("reprocess_id") or "")
        try:
            outcome = self._perform_reprocess(claimed)
        except Exception as e:
            # 读文件/抽取可能因为缺依赖、文件损坏而失败。不标 done：
            # "我压根没看成"和"我看过了、原文里没有"是两回事（I4 的三态纪律）。
            self._record_reprocess_failure(claimed, f"{type(e).__name__}: {e}")
            return {
                "handled": False,
                "reprocess_id": rid,
                "rejected": rejected,
                "skipped_reason": None,
                "error": f"{type(e).__name__}: {e}",
            }
        out = self._finish_reprocess(claimed, outcome)
        out["rejected"] = rejected
        return out
