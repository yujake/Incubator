"""角色 F 的动作 `status`。"""
from __future__ import annotations

from ._support import S, _budget_left, re

class _Status:
    def status(self, plan_id: str) -> dict:
        """一个计划的完整可读视图：子目标状态计数、预算余量、history 尾部。

        ## 归属（K3）
        F 的实例只查看自己名下的计划：不是自己的 ⇒ 受控拒（细码 `plan_not_yours`）。
        归属读数写进 `reason`（`created_by` + 那一句 why），不新增顶层键 —— 那要动工具
        声明 `returns=` 与两份冻结快照（提示词版本面），不在本批的范围里。D/G/H 的只读
        视图不受影响（`specs/d.py:254-267`）。
        """
        row = self._plan_row(plan_id)
        if row is None:
            return {
                "checked": False,
                "plan_id": plan_id,
                "reason": f"计划 {plan_id} 不存在 ⇒ **没查**（不是'查了、没有内容'）",
            }
        # ---- 归属（K3）：F 的实例只查看自己名下的计划（D/G/H 那个读口不受影响）
        #
        # 受控拒走 `_require_own_plan` 的同一份判据；`kind` 落在 `plan_error`，细码
        # `plan_not_yours` 在正文里。读口的返回值键集合因此一个字都没变 —— 归属读数
        # 写进 `reason`（见下面那一句），不新增顶层键（那要动工具声明与冻结快照）。
        owner = self._require_own_plan(row, action="查看")
        created_by = str(row.get("created_by") or "")
        subgoals = [dict(s) for s in (row.get("subgoals") or [])]
        counts: dict[str, int] = {}
        for s in subgoals:
            st = str(s.get("status") or "")
            counts[st] = counts.get(st, 0) + 1
        budget = dict(row.get("budget") or {})
        rounds = int(row.get("rounds") or 0)
        tail_n = int(self.cfg.get("history_tail", 5))
        # ---- `R-53`（`draft/28` §158）：查出陈话卡点。F 的推进是拉取式的：子目标在 A 的回答落地后
        # 要再派一次 `F.step` 才推进 ⇒ M 一停手，子目标永久停在 `in_flight`，而 `blocked_reason` 还写着
        # "等 A 完成检索请求 r-0019"（实测那两个请求早已 `done/ok`，§154 的 A5）。这里在只读视图里对当前
        # 状态重算一次：请求已终结 ⇒ 把这句"等"标成已过期并逐条列进 `stale_blocked`（不改写盘上那一行）。
        # ---- `R-61`（`draft/28` §163）：陈话还得分新旧 —— 只读地从 `history` 反推。`stale_blocked` 原来
        # 只答"是不是陈话"、不答"陈了多久"，而拉取式推进下"停了多久"恰恰是唯一能用来排队的量。前置查证
        # （`temp/_r61_recon.py`）：`history` 条目里记了 `sid` ⇒ 不必加 `last_pushed_at`（schema 变更属禁改
        # 区）；取"该 sid 最后一次触碰"按 `at` 最大，`at` 缺省退回最大 `round`，一条都没有 ⇒ 如实留空。
        last_touch: dict[str, dict] = {}
        for entry in (row.get("history") or []):
            sid = str(entry.get("sid") or "")
            if not sid:
                continue
            at = str(entry.get("at") or "")
            try:
                rnd = int(entry.get("round") or 0)
            except (TypeError, ValueError):
                rnd = 0
            prev = last_touch.get(sid)
            if prev is None or (at, rnd) >= (str(prev.get("at") or ""), int(prev.get("round") or 0)):
                last_touch[sid] = {"at": at, "round": rnd}
        req_state = {str(x.get("request_id")): str(x.get("outcome") or "")
                     for x in self.store.rows("search_requests")}
        stale_blocked: list[dict] = []
        for s in subgoals:
            reason = str(s.get("blocked_reason") or "")
            ids = sorted(set(re.findall(rf"\br-{S.ID_OR_LEGACY_PATTERN}\b", reason)))
            if not ids:
                continue
            # 判据是"已终结"，不是"成功了"：`search_failed` / `gave_up` 同样意味着
            # "等 A 完成"这句话已经过期（A 完成了，只是失败）—— 那更该露出来。
            # 取值域直接读 `S.SEARCH_OUTCOMES`，不另抄一份（抄一份就会与 schema 漂移）。
            ended = [i for i in ids if req_state.get(i, "") in S.SEARCH_OUTCOMES]
            if ended and len(ended) == len(ids):
                s["blocked_stale"] = True
                touch = last_touch.get(str(s.get("sid") or ""))
                # 同两个值要进三处（子目标两格 + stale_blocked 一行）：各算一次。
                touch_at = str((touch or {}).get("at") or "")
                touch_round = (touch or {}).get("round")
                # `R-61`：把"最后一次被触碰"也放进只读视图（不改盘上那一行）
                s["last_touched_at"] = touch_at
                s["last_touched_round"] = touch_round
                hint = (
                    f"；该子目标最后一次被触碰是第 {touch_round} 轮（{touch_at}）"
                    "⇒ 从那以后没有人再推进" if touch else
                    "；`history` 里查不到这个子目标的触碰记录 ⇒ **它从立项起就没动过**"
                )
                s["blocked_reason"] = (
                    f"{reason}（**已过期**：{ended} 已经结束 —— 现在的卡点是"
                    f"『没有人再推进一步』，不是『还在等』{hint}）"
                )
                stale_blocked.append({"sid": s.get("sid"), "requests": ended,
                                      "last_touched_at": touch_at,
                                      "last_touched_round": touch_round})
        return {
            "checked": True,
            "plan_id": row.get("plan_id"),
            # 交差读数（逐条）：`F.status` 是只读视图，但"还有哪些没签"必须是可读的 ——
            # 收工门 / M / 人看的是同一格（判据在 `agent_f/delivery.py`）。
            "delivery": self._delivery_reading(row),
            "problem": row.get("problem"),
            "problem_key": row.get("problem_key"),
            "for_question_id": row.get("for_question_id"),
            "status": row.get("status"),
            "rounds": rounds,
            "budget": budget,
            "budget_left": _budget_left(budget, rounds),
            "depth": row.get("depth"),
            "parent_plan_id": row.get("parent_plan_id"),
            "subgoals": subgoals,
            "subgoal_counts": counts,
            "stale_blocked": stale_blocked,
            "best_partial": row.get("best_partial") or "",
            "history_len": len(row.get("history") or []),
            "history_tail": list(row.get("history") or [])[-max(0, tail_n) :],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "reason": (f"计划 {row.get('plan_id')} 当前 status={row.get('status')}，已 {rounds} 轮"
                       f"（归属 created_by={created_by or '（无归属读数）'}；"
                       f"{owner.get('why') or ''}）"),
        }
