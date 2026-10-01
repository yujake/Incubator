"""角色 A 的动作 `run`（`goal-7f5116c1` M6：从 `agent_a.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import ARunResult

class _Run:
    def run(self, max_requests: int | None = None) -> dict:
        """处理若干条请求。`max_requests=None` 表示处理到没有待办为止。

        返回的是累加后的 `ARunResult.to_dict()`。三态纪律：`skipped_reason`
        非空表示"这一轮没取到活的原因"（不是错误），此时循环立即停下 ——
        继续空转只会把同一句"队列空了"重复无数遍。
        """
        total = ARunResult()
        n = 0
        while max_requests is None or n < max_requests:
            r = self.run_once()
            # 取任务侧的审计信息先汇总，再判断要不要早退：早退的那一轮
            # （队列空 / 全被别人占着）恰恰是"为什么没干活"最需要被看见的一轮。
            total.queue_pending = r.queue_pending
            total.skipped_lease_active += r.skipped_lease_active
            total.skipped_lease_backoff += r.skipped_lease_backoff
            total.gave_up += r.gave_up
            if r.request_id:
                total.request_id = r.request_id
                total.priority = r.priority
                total.priority_rank = r.priority_rank
                total.submitted_by = r.submitted_by
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
                break
            total.processed += r.processed
            total.registered += r.registered
            total.duplicated += r.duplicated
            total.downloaded += r.downloaded
            total.download_failed += r.download_failed
            total.download_suspect += r.download_suspect
            total.outcome = r.outcome
            n += 1
        return total.to_dict()
