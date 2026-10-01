"""角色 B 的动作 `run`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import BRunResult

class _Run:
    def run(self, max_docs: int | None = None) -> dict:
        """处理若干篇文献（`max_docs=None` = 处理到没有可领的为止），最后处理定向重抽取。

        退出/停止条件只有一条：`run_once()` 给出 `skipped_reason`（队列空 / 全被别人
        占着 / 全被放弃）。返回累加后的 `BRunResult.to_dict()` + `reprocess` 摘要。
        """
        total = BRunResult()
        n = 0
        while max_docs is None or n < max_docs:
            r = self.run_once()
            total.skipped_lease_active += r.skipped_lease_active
            total.gave_up += r.gave_up
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
                break
            for f in (
                "processed",
                "concepts_created",
                "concepts_reused",
                "relations_added",
                "relations_duplicate",
                "relations_suspect",
                "suspect_by_quote",
                "quotes_verified",
                "quotes_failed",
                "quotes_unknown",
                "quotes_out_of_declared_range",
                "unreadable",
                "failed",
                "conflict_checks_run",
                "conflicts_detected",
                "conflict_checks_skipped",
            ):
                setattr(total, f, getattr(total, f) + getattr(r, f))
            total.details.extend(r.details)
            n += 1
        out = total.to_dict()
        # 文献消化完之后再处理定向重抽取：先把新知识落库，再回头修已有的。
        # 反过来做，刚修好的关系会立刻被新文献的判重/I6 闸门重算一遍，白做一次功。
        out["reprocess"] = self.run_reprocess()
        return out
