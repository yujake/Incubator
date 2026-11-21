"""角色 A 的动作 `run`：把 `run_once` 循环到"没有待办"或到达上限。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（拆分只动 import 面）。
"""
from __future__ import annotations

from ._support import ARunResult

class _Run:
    def run(self, max_requests: int | None = None) -> dict:
        """处理若干条请求。`max_requests=None` 表示处理到没有待办为止。

        返回的是累加后的 `ARunResult.to_dict()`。三态纪律：`skipped_reason`
        非空表示"这一轮没取到检索请求的原因"（不是错误），此时循环立即停下 ——
        继续空转只会把同一句"队列空了"重复无数遍。队列空而候选表里还有待裁行时，
        `run_once` 会把那些委托认领下来（`claimed_delegations` / `claim_note`）并同样
        停下：判与提交是 A 的模型动作，自动链路不替它做。
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
            # 待裁读数跟着最后一轮走（越新的那一轮越接近盘上的现状）：它不累加 ——
            # "还剩几条"是状态量，不是这一趟做了几件事的累计量。
            total.pending_total = r.pending_total
            total.pending_by_delegation = list(r.pending_by_delegation)
            total.pending_note = r.pending_note
            if r.request_id:
                total.request_id = r.request_id
                total.priority = r.priority
                total.priority_rank = r.priority_rank
                total.submitted_by = r.submitted_by
            if r.claimed_delegations:
                # 队列空时那一档"认领还有待裁行的委托"：它不产生检索活，下一轮
                # 不该再走同样的路（会一直重复认领同一批委托）。所以也当成
                # "这一轮没有可继续自动做的事"停下 —— 判与提交是 A 的模型动作。
                total.claimed_delegations = list(r.claimed_delegations)
                total.claim_note = r.claim_note
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
            if r.claimed_delegations or r.skipped_reason:
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
