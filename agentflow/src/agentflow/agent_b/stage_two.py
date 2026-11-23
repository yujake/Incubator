"""B 的二阶段自驱（`stage_two`）：从 `run_once` 拆出的那一块。

## 为什么单独成文件

`agent_b/run_once.py` 在 p310 那一笔之后越过了「`src/` 下 >800 行的文件数」那条软基线
（业主口径：不许抬基线，拆函数或拆文件）。这里搬的是"二阶段自驱"这一个语义单元 ——
它与 `run_once` 的抽取主流程没有调用边，只由 `_finish` 在出口处调一次；不是按行数切。
`AgentB` 的组装面在 `core.py`（多继承里加 `_StageTwoSelfDrive`）。

## 为什么要有它

业主裁定（2026-11-21，逐字）：「B 应该自动做，而不是 M 派。」真机 `projects/lp-ball-15`
的现场是 B 的 `own.run_once` 19 次、`own.register_statement` 19 次、`own.open_polish_copy`
0 次 —— 它把「本委托只做快录」当成了停下理由，而写「主职是第二阶段」的那一句只是
描述，不是动作。所以这一格把入口做成动作与读数：每一拍的 `run_once` 回执里都带
`stage_two.unwashed`（逐条 `stmt_id` + 证明号 + 有没有开过稿），非空就意味着这一岗的活
没做完；同时把「有原稿、还没开过稿」的那几条当场开出来（`open_optimization_drafts`，
一轮有上限、幂等），B 的下一步就只剩洗与送签。

它不替模型洗稿（洗稿是文本判断，只有 B 自己做）、不替 V 签（签归 V）、也不写
`statements`：写盘只沿用既有的开稿实现（`open_polish_copy` 的四步），洗与替换仍走
B 自己的动作。
"""
from __future__ import annotations


class _StageTwoSelfDrive:
    @staticmethod
    def _stage_two_self_drive_enabled() -> bool:
        """二阶段自驱开不开（反真空的打桩点；默认开）。

        与 `agent_b/open_polish_copy._optimization_round_enabled` /
        `register_statement._optimization_replace_enabled` 同形：这一格只回答
        "这一拍自驱做不做"，不回答"洗哪一条"。反真空把它打成 False ⇒
        `run_once` 不再自己开优化稿（`stage_two.debt` 照常点名）——
        证明"自己开了稿"不是一句恒真读数。
        """
        return True

    def _finish(self, res):
        """`run_once` 的每个出口都从这里交结果：先算二阶段自驱读数，再返回。

        为什么所有出口都要走它（而不是只在"队列空"那一支）：第二阶段的自驱不能
        等"这一批文献恰好全部消化完"—— 那一批的证明可能在文献队列还很长的中途
        才登记进来（真机 lp-ball-15：命题 15:00 就在册，而文献队列还有 19 篇没消化）。
        每一拍都算一次，才是"这一批不洗完不算这一岗做完"；它幂等（开过的稿由
        `tasks.artifacts` 的来源记录认出来，不重复开）。
        """
        res.stage_two = self._stage_two_self_drive()
        return res

    def _stage_two_self_drive(self) -> dict:
        """二阶段（逐个优化）的自驱：这一拍自己看"还有几条没洗"，并把该开的稿开掉。

        ## 读数形状（键固定）

        `{checked, enabled, in_task, candidates, debt_count, debt, unwashed_count,
          unwashed, opened, skipped_open, skipped_no_draft, refused, next_action, why}`：

        - `candidates`：`closing.statements_optimization_candidates` 的条数（含"还没原稿"的）；
        - `unwashed`：有正文、且至少一份没洗的命题逐条（`stmt_id` / `unoptimized_proofs` /
          `optimization_open` / `draft_available` / `next_step`）—— 这就是"还有几条没洗"；
        - `washed_count` / `proofs_total`：回执里回答「洗了几份」的那两格读数
          （全表有正文的证明份数 / 其中 `optimized=true` 的份数；不含已放弃与已退休的命题）。
          它们是"累计洗过多少"，不是"这一拍洗了几份" —— 后者只有 `opened` 那一格回答
          （这一拍开了几份稿），洗稿本身是文本判断，框架不替你做、也不拿它拦门；
        - `debt`：`unwashed` 里还没开过优化稿、且有原稿可开的那几条（这一拍要开的就是它）；
        - `opened` / `skipped_open` / `skipped_no_draft` / `refused`：沿用开稿那一笔的读数；
        - `next_action`：非空时是一句可执行的下一步（洗 → 送 V → 精准替换）。

        三态：`checked=False` 是"没查成"（`statements` 读不出来 / 没有 store），不是
        "一条都不欠洗"；`enabled=False` 是反真空打桩，`debt` 照常点名。
        """
        out: dict = {
            "checked": False, "enabled": False, "in_task": False,
            "candidates": 0, "debt_count": 0, "debt": [],
            "unwashed_count": 0, "unwashed": [],
            "proofs_total": 0, "washed_count": 0,
            "opened": [], "skipped_open": [], "skipped_no_draft": [], "refused": [],
            "next_action": "", "why": "",
        }
        store = getattr(self, "store", None)
        if store is None:
            out["why"] = "没有 store ⇒ 读不到「未优化清单」（没查成，不是「一条都不欠洗」）"
            return out
        from .. import closing as _CL

        cand = _CL.statements_optimization_candidates(store)
        if not cand.get("checked"):
            out["why"] = str(cand.get("reason") or "「未优化清单」没查成")
            return out
        out["checked"] = True
        out["candidates"] = int(cand.get("count") or 0)
        # DANGLE ③：回执里"洗了几份 / 还剩几份"两格读数（口径在
        # `closing.statements_optimization_candidates`，全表累计，不是只数候选）。
        out["proofs_total"] = int(cand.get("proofs_total") or 0)
        out["washed_count"] = int(cand.get("washed_count") or 0)
        out["enabled"] = bool(self._stage_two_self_drive_enabled())
        # ---- 只把"有正文、还没洗"的命题算进这一格（候选面里"还没原稿"的那些不是等洗）
        unwashed: list[dict] = []
        debt: list[dict] = []
        for row in (cand.get("rows") or []):
            unoptimized = [int(n) for n in (row.get("unoptimized_proofs") or [])]
            if not unoptimized:
                continue
            draft = dict(row.get("draft") or {})
            open_state = dict(row.get("optimization_open") or {})
            one = {
                "stmt_id": str(row.get("stmt_id") or ""),
                "kind": str(row.get("kind") or ""),
                "prompt_class": str(row.get("prompt_class") or ""),
                "unoptimized_proofs": unoptimized,
                "draft_available": bool(draft.get("available")),
                "optimization_open": open_state,
                "opened": bool(open_state.get("found")),
                "next_step": str(row.get("next_step") or ""),
            }
            unwashed.append(one)
            if not one["opened"] and one["draft_available"]:
                debt.append(one)
        out["unwashed"] = unwashed
        out["unwashed_count"] = len(unwashed)
        out["debt"] = debt
        out["debt_count"] = len(debt)
        # ---- 不在任务上下文 ⇒ 不写盘（没有"自己那一行"记来源，重复开稿无法幂等）
        try:
            from ..conductor import current_task_id

            out["in_task"] = bool(str(current_task_id() or ""))
        except Exception:  # noqa: BLE001 —— 读不到召唤号 = 不在任务上下文（不是崩溃）
            out["in_task"] = False
        if not out["enabled"]:
            out["why"] = "二阶段自驱被关掉（反真空打桩）⇒ 这一拍只点名欠账、不自己开稿"
            out["next_action"] = self._stage_two_next_action(unwashed)
            return out
        if debt:
            if not out["in_task"]:
                out["why"] = ("查过了：这一拍有 %d 条该开优化稿，但不在任务上下文 ⇒ "
                              "不自己开（没有来源记录可写，重复开无法幂等）；"
                              "由带召唤号的那一拍接着开" % len(debt))
                out["next_action"] = self._stage_two_next_action(unwashed)
                return out
            got = self.open_optimization_drafts()
            for key in ("opened", "skipped_open", "skipped_no_draft", "refused"):
                out[key] = list(got.get(key) or [])
            if not got.get("checked"):
                # 开稿那一笔没查成：不回退成"一条都没开"，如实标三态。
                out["checked"] = False
                out["why"] = str(got.get("why") or "「未优化清单」没查成（开稿那一笔）")
                out["next_action"] = self._stage_two_next_action(unwashed)
                return out
            opened_ids = {str(x.get("stmt_id") or "")
                          for x in (out["opened"] or []) if x.get("ok")}
            for one in unwashed:
                if one["stmt_id"] in opened_ids:
                    one["opened"] = True
            out["debt"] = [one for one in debt if one["stmt_id"] not in opened_ids]
            out["debt_count"] = len(out["debt"])
        out["why"] = (
            "这一拍查过：%d 条候选里 %d 条有正文还没洗（全表已洗 %d/%d 份；逐条见 "
            "`unwashed`）；"
            "%s" % (out["candidates"], out["unwashed_count"],
                    out["washed_count"], out["proofs_total"],
                    ("自己开了 %d 份优化稿、跳过 %d 条已开的、拒绝 %d 条；"
                     % (len(out["opened"]), len(out["skipped_open"]), len(out["refused"]))
                     if out["opened"] or out["skipped_open"] or out["refused"] else
                     "这一拍没有新开的稿；")) +
            ("照 `next_action` 接着洗。" if out["unwashed_count"] else "没有欠洗的证明。"))
        out["next_action"] = self._stage_two_next_action(unwashed)
        return out

    @staticmethod
    def _stage_two_next_action(unwashed: list[dict]) -> str:
        """欠洗清单的下一步（逐条点名；空清单给空串）。"""
        todo = [one for one in unwashed if one.get("unoptimized_proofs")]
        if not todo:
            return ""
        head = todo[0]
        sid = str(head.get("stmt_id") or "")
        nos = ",".join(str(n) for n in (head.get("unoptimized_proofs") or []))
        return (
            f"这一批还有 {len(todo)} 条没洗（stmt_id: "
            + "、".join(str(one.get("stmt_id") or "") for one in todo)
            + f"）。从 stmt:{sid} 的 #p{nos} 起逐份做：在 `manuscripts/B/b-proof-*.md` 副本上"
            "把证明正文洗清楚（`fs.edit`）→ 派 V（`V.verify_proof` 带 `statement_id` + "
            "`proof_manuscript`）重拿签 → 签到位用 `own.register_statement` 交带稿的正文"
            "（或 `own.ingest_manuscript(mode=\"apply\", path_group≥1)`）精准替换："
            "旧正文进 `proof_history`、`optimized_by_proof[证明号]=true`。"
            "不必等 M 派 —— 快录交回那一刻，二阶段就归你。")
