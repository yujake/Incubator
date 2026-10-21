"""角色 B 的动作 `run`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import BRunResult
from .. import conceptrows as _CR   # 轮配额（`CONCEPTS_PER_ROUND_MAX`）的唯一出处

class _Run:
    def run(self, max_docs: int | None = None) -> dict:
        """处理若干篇文献（`max_docs=None` = 处理到没有可领的为止），最后处理定向重抽取。
        退出/停止条件只有一条：`run_once()` 给出 `skipped_reason`（队列空 / 全被别人占着 / 全被放弃）。返回累加后的 
        `BRunResult.to_dict()` + `reprocess` 摘要。
        ## 概念配额是「轮」预算（2026-10-21，本批缺陷一的第三处）
        真机 mp3：这一层的一轮（19 篇文献）灌进 「1143 条」概念 —— 于是"每轮产出新事实"这条读数被一次水漫金山顶平，且 1143 条概念全是 
        `proof_text="concept:primitive"`的术语行。配额按"一轮"限（`conceptrows.CONCEPTS_PER_ROUND_MAX`
        = 30），并且「跨篇累加」：按篇限量挡不住"篇数多"那种水漫（19 × 30 还是 570）。超出的被受控拒绝并留读数（`concepts_refused` / 
        `relations_deferred` /`concept_quota` / `details[*stage=concept_quota]`），已经写进去的照旧保留。
        轮边界就在这一层：轮首换一个新的 `ConceptQuota`（挂在实例上，见`run_once` 的 docstring —— 动作的调用面上不许出现"配额"这个参数）。
        """
        total = BRunResult()
        quota = _CR.ConceptQuota()
        self._concept_quota = quota
        n = 0
        while max_docs is None or n < max_docs:
            r = self.run_once()
            total.skipped_lease_active += r.skipped_lease_active
            total.skipped_lease_backoff += r.skipped_lease_backoff
            total.gave_up += r.gave_up
            if r.skipped_reason:
                total.skipped_reason = r.skipped_reason
                break
            for f in (
                "processed",
                "concepts_created",
                "concepts_reused",
                "concepts_refused",
                "relations_deferred",
                "relations_added",
                "relations_duplicate",
                "relations_suspect",
                "suspect_by_quote",
                "quotes_verified",
                "quotes_failed",
                "quotes_unknown",
                "quotes_out_of_declared_range",
                "unreadable",
                "skipped_no_extractor",
                "failed",
                "conflict_checks_run",
                "conflicts_detected",
                "conflict_checks_skipped",
            ):
                setattr(total, f, getattr(total, f) + getattr(r, f))
            total.details.extend(r.details)
            n += 1
        out = total.to_dict()
        # 这一轮配额的「总」读数：`concepts_created` 只说得清"写了多少"，
        # 说不清"被挡了多少、挡的是谁"—— 后者才是"不许静默丢弃"要的那一半。
        out["concept_quota"] = quota.reading()
        # 文献消化完之后再处理定向重抽取：先把新知识落库，再回头修已有的。
        # 反过来做，刚修好的关系会立刻被新文献的判重/I6 闸门重算一遍，白做一次功。
        out["reprocess"] = self.run_reprocess()
        return out
