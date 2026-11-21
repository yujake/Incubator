"""角色 B 的动作 `run`。"""
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
        # ---- 优化轮（业主 2026-11-14 的「优化侧一般性规定」）------------------------
        #
        # 「系统取未优化的命题号及相关信息、命题类型、原证明稿，自动注册 B 侧稿号并给出
        # 初始稿」⇒ 这一趟先按未优化清单把该开的优化稿开出来，不等人点。写盘只发生在
        # `open_polish_copy` 的四步里（收工读数纯读，一个字节都不写）；一轮有上限
        # （`OPTIMIZATION_ROUND_MAX`），下一轮接着开。没有原稿的概念不开，只进读数。
        drafts = self.open_optimization_drafts()
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
            # `path_base` 是逐篇的读数（`run_once` 那一趟领到的那一篇是按哪个基准解析的）；
            # 一轮可能两种基准都有，所以汇总只保留第一条非空的，逐篇来路在
            # `details[*stage=resolve]` 里一条不少。
            if not total.path_base:
                total.path_base = r.path_base
            # 二阶段自驱的读数取最后一拍（每一拍都现算：`unwashed` 是"这一轮末尾
            # 还剩哪几条没洗"的最新现场；开稿的逐条记录在最后一拍里已经包含前几拍
            # 开过的 —— `skipped_open` 会点名它们）。
            if r.stage_two and r.stage_two.get("checked"):
                total.stage_two = dict(r.stage_two)
            n += 1
        out = total.to_dict()
        # 这一轮配额的「总」读数：`concepts_created` 只说得清"写了多少"，
        # 说不清"被挡了多少、挡的是谁"—— 后者才是"不许静默丢弃"要的那一半。
        out["concept_quota"] = quota.reading()
        # 文献消化完之后再处理定向重抽取：先把新知识落库，再回头修已有的。
        # 反过来做，刚修好的关系会立刻被新文献的判重/I6 闸门重算一遍，白做一次功。
        out["reprocess"] = self.run_reprocess()
        # 优化轮那一笔的读数（开了几份 / 跳过几条 / 受控拒几条）：与 `concept_quota`
        # 同档的"这一轮干了什么"读数，不是判据。
        out["optimization_drafts"] = drafts
        return out
