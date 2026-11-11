"""角色 F 的动作 `step`（`goal-7f5116c1` M6：从 `agent_f.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import AT, Any, Mapping, NO_PROGRESS_NOTE, PlanError, S, TERMINAL_STATUSES, _budget_left, _step_outcome

#: 收工读数里要原样带出去的那几格（键名与 `agent_f/delivery.py` 的 `summary` 同一份）。
#:
#: 最后三格是 2026-11-11（业主裁定 ①「F侧报告收工时自动提交其名下未提交的V签稿」）：
#: 它们只在收工那一趟有读数（`_close_reading` 现读写进 `tasks.artifacts`），推进轮次
#: 里 `None` / `[]` —— 那一趟不读这一格，不许读成「没有可提交的」。
_CLOSE_KEYS: tuple[str, ...] = (
    "total", "signed_count", "pending_count", "unsigned_count",
    "proof_count", "proof_statements", "draft_count",
    "abandoned_count", "abandoned_statements",
    "unfinished", "unfinished_count", "trail", "trail_required",
    "legal_exits", "exits_note", "legal_stop", "is_failure", "close_problems",
    "coverage", "coverage_reading", "coverage_ratio", "coverage_why",
    "auto_submitted", "auto_submitted_count", "still_unsubmitted",
)


class _Step:
    def _close_reading(self, out: dict, row) -> dict:
        """收工那一趟的逐条读数（业主 2026-11-02：「不许静默收工」）。

        收工的四条出口（终态 / 连续无进展 / 轮数用尽 / 没有可推进的子目标）都走这里：
        把「还有哪些成果没签」逐条点名、把出路（举例）与它自己的留痕一并带出去，
        未签且没有处置时把这一句写进 `reason` —— 收工这件事不能只剩一句"停"。
        """
        from . import delivery as _DL

        try:
            got = self._delivery_reading(row)
        except Exception as exc:  # noqa: BLE001 - 收工读数坏了不许把"停"也带走
            got = _DL.empty_reading(
                f"收工读数没跑成（{type(exc).__name__}: {exc}）⇒ 未签的那些没查成")
        # ---- 收工自动提交（业主 2026-11-11 裁定 ①）-----------------------------
        #
        # 位置在交差读数之后、逐格复制之前：三格进 `_CLOSE_KEYS` 的同一排，
        # 而完整的候选级读数另挂一份在 `out["auto_submit"]`（`still_unsubmitted`
        # 里每条都带 `state` / `why` / 两个 sha）。
        try:
            auto = self._auto_submit_signed(row)
        except Exception as exc:  # noqa: BLE001 - 自动提交坏了不许把"停"也带走
            auto = {"checked": False, "auto_submitted": [], "auto_submitted_count": 0,
                    "still_unsubmitted": [], "why": (
                        f"收工自动提交没跑成（{type(exc).__name__}: {exc}）"
                        " ⇒ 这一趟没有提交（不是「没有要提交的」）")}
        got["auto_submitted"] = [dict(x) for x in (auto.get("auto_submitted") or [])]
        got["auto_submitted_count"] = int(auto.get("auto_submitted_count") or 0)
        got["still_unsubmitted"] = [dict(x) for x in (auto.get("still_unsubmitted") or [])]
        got["auto_submit_checked"] = bool(auto.get("checked"))
        got["auto_submit_why"] = str(auto.get("why") or "")
        out["auto_submit"] = dict(auto)
        if got["auto_submitted_count"]:
            out["reason"] = (str(out.get("reason") or "").rstrip()
                             + "；收工自动提交：这一趟真写进 `tasks.artifacts` 的拿签稿 "
                             + "、".join(
                                 f"mss:{x.get('manuscript_id')}"
                                 f"（正文 sha {str(x.get('body_sha') or '')[:12]}…）"
                                 for x in got["auto_submitted"][:8])
                             + f" 共 {got['auto_submitted_count']} 份")
        blocked = [x for x in got["still_unsubmitted"]
                   if str(x.get("state") or "") in
                   ("body_changed_after_sign", "ambiguous_path", "write_failed",
                    "sign_unbacked")]
        if blocked:
            out["reason"] = (str(out.get("reason") or "").rstrip()
                             + "；有拿签稿没提交（逐条）："
                             + "；".join(str(x.get("why") or x.get("state") or "")
                                        for x in blocked[:5])
                             + (f" 等 {len(blocked)} 条" if len(blocked) > 5 else ""))
        out["delivery"] = got
        out["delivered"] = bool(got.get("delivered"))
        for key in _CLOSE_KEYS:
            out[key] = got.get(key)
        out["delivery_state_plan"] = str(got.get("state") or "")
        out["delivery_label_plan"] = str(got.get("state_label") or "")
        out["self_assessment"] = dict(got.get("self_assessment") or {})
        problems = [str(x) for x in (got.get("close_problems") or [])]
        if problems:
            out["reason"] = (str(out.get("reason") or "").rstrip()
                             + "；收工读数（逐条）：" + "；".join(problems))
        # 未签成果逐条点名（收工说明里也要点得到，不只在结构化读数里）
        open_rows = [dict(x) for x in (got.get("unfinished") or [])]
        if open_rows:
            out["reason"] = (str(out.get("reason") or "").rstrip()
                             + "；未签成果（逐条）："
                             + "、".join(
                                 f"stmt:{o.get('statement_id')}"
                                 + (f"（手稿 {o.get('manuscript')}）" if o.get("manuscript") else "")
                                 + f"[{o.get('claim_label')}]" for o in open_rows[:8])
                             + f" 共 {len(open_rows)} 条")
        return out

    def _auto_submit_signed(self, plan: Mapping[str, Any]) -> dict:
        """收工那一趟：把「已拿签、尚未提交」的稿写进 F 自己那一行的 `tasks.artifacts`。

        方法体 2026-11-11 搬进 `agent_f/autosubmit.py::auto_submit_signed`（体量软基线
        不抬：`step.py` 556 → 813 行、这个方法 215 行）。这里只留一个薄壳 —— 调用点、
        返回形状与 `_close_reading` 那三格的复制一个字都没变；`self.store` / `self.cfg` /
        `self._stamp()` 作为参数递给模块级实现。
        """
        from . import autosubmit as _AS

        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        return _AS.auto_submit_signed(
            store=self.store, root=root,
            plan_id=str((plan or {}).get("plan_id") or ""),
            stamp=str(self._stamp() or ""))

    def step(self, plan_id: str, product: Any = None) -> dict:
        """推进一轮。
        返回 ``{"plan_id","round","sid","action","outcome","status","budget_left","reason","budget_known","budget_reading"}``。

        ## `product` 这一格（2026-11-11，真机第三轮的通道断）

        可选。F 已经写好的那一份（`proof` / `reduction`）可以直接放进来：走
        `_handed_product_round` —— 既有的产物校验一条都不放宽，过了就照现有路径落成
        `reports/f-proof-<稿号>.md`（`## 依赖` 由 `cites` 渲染，F 不必手抄），
        返回值里给 `manuscript_path` / `manuscript_id`。校验不过 ⇒ 受控拒，逐条点名。

        不给（`None`）⇒ 与加这一格之前逐字同形：`_deploy` 按 owner 分派，
        F 那一支照旧问推理缝。老路没有被替代，只是多了一个"把写好的交进来"的入口。
        `outcome` 取本模块的 :data:`STEP_OUTCOMES`（``no_change`` / ``progress`` / ``blocked``）：它说的是
        这一轮推进的结果，与 `schema.TASK_OUTCOMES`（一次任务的终局）是两套命名空间，不许互相赋值—— 裁定依据与后果写在 `STEP_OUTCOMES` 的
        注释里。写入前会过一次:func:`_step_outcome` 的收口，词表外的取值当场炸。
        流程（每一步的理由都写在旁边的注释里）：
        1. 读计划 → 终结状态不再推进（不自动重入）；轮数用尽 ⇒ `stalled` + `best_partial`； 2. `pick_next_subgoal` 选目标
        （复用工具层的排序，不另写一套）； 3. 按 owner 分派（见模块 docstring 的表格）； 4. 追加一条 history，`rounds += 1`； 5. 
        判定计划状态； 6. 一个事务写回。
        """
        row = self._plan_row(plan_id)
        if row is None:
            # 拒信要可行动（`draft/39` §6.41 的 D51）：真机读数（T5 第 1 趟
            # `p8-fermat-shorter-proof`）里主控把 `problem_key`（`flt-conj-1`）当 `plan_id`
            # 传了三次，每次都只收到一句"攻坚计划 flt-conj-1 不存在" —— 而台账里明明有一行
            # （`plan_id=0000`）。只说"没有"、不说"有哪些"，调用方只能硬猜（与 §6.21 修的
            # D 侧 qid 那条同一族）。这里把在册的 plan_id 与它的 problem_key 一并给出。
            try:
                rows = [dict(r) for r in self.store.rows("attack_plans")]
            except Exception:  # noqa: BLE001 —— 读不到就退化成原来的那句话，不编内容
                rows = []
            if rows:
                listed = "；".join(
                    f"{r.get('plan_id')}（problem_key={r.get('problem_key')}，"
                    f"status={r.get('status')}）" for r in rows[:12])
                raise PlanError(
                    f"攻坚计划 {plan_id!r} 不在册 ⇒ 这一步没做。在册的攻坚计划有 "
                    f"{len(rows)} 条：{listed}。"
                    "step 要的是 plan_id（create_plan 返回的那个），不是 problem_key —— "
                    "同一个 problem_key 重复立项会命中既有计划，所以号只有 create_plan 的返回里有"
                )
            raise PlanError(
                f"攻坚计划 {plan_id!r} 不存在，而且台账里一条攻坚计划都没有 ⇒ "
                "先派 F.create_plan（它返回 plan_id）再回来推进，别对着空表反复试号")

        status = str(row.get("status") or "open")
        budget = dict(row.get("budget") or {})
        rounds = int(row.get("rounds") or 0)
        budget_left = _budget_left(budget, rounds)
        # 预算读数（P-09）：注入点给的读数原样随返回值出去（读不到也如实出去）。
        # 为什么每个返回路径都带它：调用方（M/D）与台账读的是这一次 `step` 的返回，
        # 只在某一条路上给会让"有没有读数"取决于这一轮走了哪条分支。
        reading = self.budget_of_round()

        # ---- 终结状态：不再推进（终态先到先得，不许被重入改写）
        if status in TERMINAL_STATUSES:
            return self._close_reading({
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": status,
                "budget_left": budget_left,
                "budget_known": reading["status"] == "known",
                "budget_reading": reading,
                "reason": (
                    f"计划已是终结状态 {status!r} ⇒ 不再推进。"
                    "「不再推进」不是「推进了但没有进展」：终态先到先得，"
                    "自动重入会把它当活计划重新拾起，于是终止条件形同虚设"
                ),
            }, row)

        subgoals: list[dict] = [dict(s) for s in (row.get("subgoals") or [])]
        history: list[dict] = [dict(h) for h in (row.get("history") or [])]

        # ---- [1] 轮数用尽 ⇒ stalled + best_partial（必须非空，且必须如实）
        #
        # 在它之前先判一次连续无进展（来自对 dsh 数学模式的观摩）：
        # 那种模式要求"连续 N 轮无进展就提前终止"。我们此前只按 `max_rounds` 停，
        # 而 `history[i]["outcome"] == "no_change"` 这个信号已经被生产出来却无人消费 ——
        # 这正是本项目自己总结过的 P4（"检测到了却没有消费"）的又一处实例。
        # 后果：一个"卡在未接线子目标上"的攻坚计划会把预算完整烧完才停，
        # 而它从第一轮起就不可能再有任何进展。
        stall_after = int(self.cfg.get("stall_after_no_progress_rounds", 3))
        recent = [str(h.get("outcome") or "") for h in (row.get("history") or [])][-stall_after:]
        if stall_after > 0 and len(recent) == stall_after and all(o == "no_change" for o in recent):
            row["status"] = "stalled"
            row["best_partial"] = (
                f"[提前停止] 连续 {stall_after} 轮无进展（全部 outcome=no_change）⇒ 不再烧预算。\n"
                + self._compose_best_partial(subgoals, rounds)
            )
            row["updated_at"] = self._stamp()
            self._write_plan(row, note=f"f.step:stall_after_{stall_after}_no_progress")
            self._log(f"plan {row.get('plan_id')} stalled after {stall_after} no-progress rounds")
            out = self._close_reading({
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stall_detected",
                "outcome": "no_change",
                "status": "stalled",
                "budget_left": _budget_left(budget, rounds),
                "budget_known": reading["status"] == "known",
                "budget_reading": reading,
                "reason": (
                    f"连续 {stall_after} 轮 outcome=no_change ⇒ 提前判 stalled。"
                    "不是失败，也不是成功：当前最好的部分结果已写入 best_partial。"
                    "（这个信号此前被生产出来却无人消费 —— 见 LESSONS 的 P4）"
                ),
            }, row)
            self.last_step = out
            return out
        #
        # 这里显式传 depth=0：`can_round` 会同时检查轮数与深度，而"深度到顶"
        # 的后果是"不能再分子问题"，不是"这个计划该停了"。把后者也当成终止判据，
        # 会让一个深度恰好到顶的计划连第一轮都跑不了 —— 那是把"不能再分子问题"
        # 读成了"这个问题不能做"（见 attack_tools 模块 docstring 的同一段说明）。
        if not AT.can_round(budget, rounds_done=rounds, depth=0)["allowed"]:
            row["status"] = "stalled"
            row["best_partial"] = self._compose_best_partial(subgoals, rounds)
            detail = (
                f"轮数已用尽（{rounds}/{budget.get('max_rounds')}）⇒ 停止并交出 best_partial。"
                "stalled 既不是失败也不是成功：它表示'预算内没做出来'"
            )
            # 只有还有位子时才追加 history：`AttackPlan.validate` 要求
            # `len(history) <= max_rounds × 子目标数`（"有轮次没被预算约束"的守卫）。
            # 轮数用尽时正好顶到那个上限 —— 再追加一条"停止"记录会违反 schema，
            # 于是这条计划永远写不回去（"说停"本身被 schema 挡住了）。
            # 所以把停止理由记进计划级的 best_partial（它是计划级的交接记录），
            # 而不是挤进已经被预算占满的 history。
            if len(history) < int(budget.get("max_rounds", 0)) * max(1, len(subgoals)):
                history.append(
                    {
                        "round": rounds + 1,
                        "sid": None,
                        "action": "stop",
                        "outcome": "no_change",
                        "detail": detail,
                        "evidence": [],
                        "at": self._stamp(),
                    }
                )
            row["best_partial"] = f"[停止] {detail}\n{row['best_partial']}"
            row["history"] = history
            row["updated_at"] = self._stamp()
            self._write_plan(row, note="f.step:stalled")
            self._log(f"plan {row.get('plan_id')} stalled")
            return self._close_reading({
                "plan_id": row.get("plan_id"),
                "round": rounds,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": "stalled",
                "budget_left": _budget_left(budget, rounds),
                "budget_known": reading["status"] == "known",
                "budget_reading": reading,
                "best_partial": row["best_partial"],
                "reason": detail,
            }, row)

        # ---- [2] 选子目标（复用 attack_tools.pick_next_subgoal）
        #
        # 先摘掉 `in_flight` 的子目标：它们这一轮已经"交出去等回填"了
        # （A/B 的请求在别人手里，C/D/F 的推理本框架还没接）。
        # 不过滤的话，`pick_next_subgoal` 会一轮又一轮地选中同一个子目标，
        # 于是 history 被同一条事实灌满，而真正待办的子目标永远轮不到。
        # 过滤只影响"这一轮选谁"，不改子目标的状态：它们在表里仍然是 blocked，
        # 卡点仍然对人可见（`blocked_reason` 非空）。
        pickable = [s for s in subgoals if not s.get("in_flight")]
        picked = AT.pick_next_subgoal(pickable)
        if not picked["picked"]:
            # 无可推进的子目标：这在两种情况下发生 —— 全 closed（成功收口）、
            # 或全是 dropped/blocked（需要人来解开卡点）。两者都不该静默变成"没轮次"。
            history.append(
                {
                    "round": rounds + 1,
                    "sid": None,
                    "action": "stop",
                    "outcome": "no_change",
                    "detail": f"没有可推进的子目标：{picked['reason']}",
                    "evidence": [],
                    "at": self._stamp(),
                }
            )
            row["subgoals"] = subgoals
            row["history"] = history
            row["rounds"] = rounds + 1
            row["status"] = self._derive_status(subgoals, row)
            row["updated_at"] = self._stamp()
            row["best_partial"] = self._compose_best_partial(subgoals, rounds + 1)
            self._write_plan(row, note="f.step:no_pickable")
            return self._close_reading({
                "plan_id": row.get("plan_id"),
                "round": rounds + 1,
                "sid": None,
                "action": "stop",
                "outcome": "no_change",
                "status": row["status"],
                "budget_left": _budget_left(budget, rounds + 1),
                "budget_known": reading["status"] == "known",
                "budget_reading": reading,
                "reason": picked["reason"],
            }, row)

        sg = picked["subgoal"]
        sid = str(sg.get("sid"))

        # ---- [3] 分派
        #
        # 2026-11-11：`product` 给了 ⇒ 这一轮用 F 交进来的那一份（既有的产物校验
        # 与落稿路径都在 `_handed_product_round` 里），不问推理缝、也不按 owner 派活。
        # 形式化那条子目标例外：形式化归 L、F 没有那条边 —— 这是一条权限面事实，
        # 不是"这一份产物过不过闸"，所以它照旧走 `_formal_not_in_f_round`（受控拒
        # + 上报），并且把"你交的那一份没有被采用"写进读数。
        # 不给 `product` 则一个字节都不走新路（`_deploy` 原样）。
        if product is not None:
            from .core import _is_formal_subgoal

            if _is_formal_subgoal(sg):
                deploy = self._formal_not_in_f_round(sg, plan=row)
                deploy["detail"] = (
                    str(deploy.get("detail") or "")
                    + "；⚠️ 这一轮你通过 `attack.step(product=…)` 交了产物，"
                    "但这条子目标不在 F 的权限面上（形式化归 L）⇒ 没有采用它")
            else:
                deploy = self._handed_product_round(
                    product, sg, plan=row, owner=str(sg.get("owner") or ""))
        else:
            deploy = self._deploy(sg, plan=row)

        # ---- 把分派结果写回子目标
        if deploy.get("experiment_ids"):
            sg["experiment_ids"] = sorted(set(list(sg.get("experiment_ids") or []) + list(deploy["experiment_ids"])))
        if deploy.get("proof_experiment_ids"):
            sg["proof_experiment_ids"] = sorted(
                set(list(sg.get("proof_experiment_ids") or []) + list(deploy["proof_experiment_ids"]))
            )
        if deploy.get("evidence_ids"):
            sg["evidence_ids"] = sorted(set(list(sg.get("evidence_ids") or []) + list(deploy["evidence_ids"])))
        if deploy.get("negation_kind") is not None:
            sg["negation_kind"] = deploy["negation_kind"]
        if deploy.get("status"):
            sg["status"] = deploy["status"]
        if deploy.get("blocked_reason"):
            sg["blocked_reason"] = deploy["blocked_reason"]
        if deploy.get("script_path"):
            # S-10(a)：脚本落点写回子目标。为什么必须在这里写：`step` 在分派前把
            # `subgoals` 拷成了本地列表，分派后要用这份本地副本整体写回 ——
            # 在 `_deploy_e` 里直接改 `plan["subgoals"]` 会被这一步静默覆盖
            # （下面那段 `new_subgoals` 的注释记的就是同一条）。
            sg["script_path"] = str(deploy["script_path"])
        if deploy.get("script_spec"):
            # P4-8：判据是这一轮才由 F 从 `testable` 推出来的 ⇒ 写回子目标，
            # 下一轮直接用（不必每轮花一次模型调用重新推）。
            sg["script_spec"] = dict(deploy["script_spec"])
        if deploy.get("in_flight") is not None:
            sg["in_flight"] = bool(deploy["in_flight"])
        sg["attempts"] = int(sg.get("attempts") or 0) + (1 if deploy.get("count_attempt") else 0)

        # ---- P4-8（`draft/44`）：`tried_strategies` 写回
        #
        # 改前 `tried_strategies` 「只读不写」（`core.py` 的 `_reason_self` 里那一处是
        # 全仓唯一出现点）⇒ 它是一个永远为空的读数：`pre_spend_gate` 的
        # `strategies_tried`（"九招里试过几招、还剩几招"）每一轮都读到 0，
        # 提示词里的"已试过的招"永远是"（无）"—— 于是模型每一轮都可以合法地重挑同一招。
        # 这一招真的用过了（产物里有 `strategy`）就记下来，去重后写回子目标。
        tried_now = str(dict(deploy.get("product") or {}).get("strategy") or "")
        if tried_now:
            sg["tried_strategies"] = sorted(
                set(list(sg.get("tried_strategies") or []) + [tried_now]))

        # ---- P4-7（`draft/44`）：父目标让位给刚派出去的子目标
        #
        # `counterexample_request` / `reduction` 造出新子目标之后，父目标原先仍是
        # `in_progress`，而 `pick_next_subgoal` 的次序是 `in_progress` 最先 ⇒ 「每一轮都
        # 重新选中父目标」，新子目标永远停在 `todo`（真机：`s1/s5/s6` 一直 `todo`）。
        # `waiting_on` 是这一件事的显式读数（"我在等这几条"），由
        # `attack_tools.pick_next_subgoal` 消费 —— 不靠改状态来暗示。
        if deploy.get("waiting_on"):
            sg["waiting_on"] = sorted(
                set(list(sg.get("waiting_on") or []) + [str(x) for x in deploy["waiting_on"]]))

        # ---- 归约产生的新子目标挂进计划（`draft/39` §6.31 的 D42）
        #
        # 为什么由这里挂、而不是在 `_deploy` 里直接改 `plan["subgoals"]`：`step` 在
        # 分派之前就把 `subgoals` 拷成了本地列表（`[dict(s) for s in …]`），
        # 分派完还要用本地那份写回 —— 在 `_deploy` 里往 plan 里塞的东西会被这一步
        # 覆盖掉（静默丢失，没有任何异常）。号由框架发（见 `_next_sid`），
        # 于是同一批归约不会出现两个 `s1`（schema 对重复 sid 是硬拒）。
        for raw_new in (deploy.get("new_subgoals") or []):
            subgoals.append(self._normalize_subgoal(dict(raw_new), len(subgoals)))

        history_row = {
            "round": rounds + 1,
            "sid": sid,
            "action": deploy["action"],
            # 收口到 `STEP_OUTCOMES`（`G-24②`）：词表外的取值在写入前就炸，
            # 而不是原样落进 history（那里它会让停滞检测静默失效）。
            "outcome": _step_outcome(deploy["outcome"]),
            "detail": deploy["detail"],
            "evidence": list(deploy.get("evidence") or []),
            "at": self._stamp(),
        }
        # `draft/39` §3.16/§6.14：这一轮交了什么产物（四种之一）要进 history。
        # 为什么必须在 history 里（而不是只进 detail 那句话）：活着的那条读数是
        # "`attack_plans.history` 的产物不再是 `no_change`"（真机卡点③）——
        # 它要能机械地读出来，而不是靠人去读一段散文。
        if deploy.get("product"):
            product = dict(deploy["product"])
            # 整份产物进 history（D42）：上面那四个扁平键是"给人扫一眼"的，
            # 而论证的 `steps` / 实验请求的 `script_spec` / 归约的 `new_subgoals`
            # 是这一轮真正的产出 —— 不落它们，模型这一轮想的就白想了
            # （审计时只剩一句"它说它推了一步"）。
            history_row["product_detail"] = product
            history_row["product"] = str(product.get("product") or "")
            history_row["strategy"] = str(product.get("strategy") or "")
            history_row["best_partial"] = list(product.get("best_partial") or [])
            # `dead_end_reason` 只属于 `dead_end` 那一档（CS-6）：`attackround.parse_round`
            # 给 `reduction` 与 `dead_end` 两档都写了 `product["reason"]`，而这里从前
            # "见 reason 就写 `dead_end_reason`" ⇒ 归约轮的"为什么这样归约"落进了一个
            # 名叫"死路理由"的字段（2026-10-11 现算：两个根 22 条 reduction 行全部误名，
            # 且全部落在受控 7 值之外）。归约的理由一个字都没丢 —— 它在
            # `product_detail["reason"]` 里（整份产物照旧进 history）。
            if str(product.get("product") or "") == "dead_end" and product.get("reason"):
                history_row["dead_end_reason"] = str(product["reason"])
        # ---- P3-6（`draft/44`）：产物的「落点」进 history（M 读 `attack.status` 就看得见）
        #
        # 改前 `product_detail` 只写不读（本文件的那一行是全仓唯一出现点）⇒ F 交出的论证
        # 在盘上与台账上都没有第二个读者。现在：`statement_id`（可复核的那一份）与
        # `report_path`（给人读的推进台账）都会落进 history，也都在 `step` 的返回值里。
        if deploy.get("statement_id"):
            history_row["statement_id"] = str(deploy["statement_id"])
        # ---- 送审与 V 签（业主 2026-11-02：「拿到V签F才能交差」）。
        # 这一格必须进 history 与返回值两处：它是这一轮「交没交差」的唯一机器读数，
        # 只写在 detail 那句散文里，读的人与下游都只能靠读中文来判。
        # 四档：已签 / 待签 / 未通过 / 没查成（`agent_f/vsign.py`）。
        if deploy.get("v_sign"):
            _vs = dict(deploy["v_sign"])
            _reading = dict(_vs.get("reading") or {})
            history_row["v_sign"] = {
                "state": str(_reading.get("state") or ""),
                "label": str(_reading.get("label") or ""),
                "delivered": bool(_reading.get("delivered")),
                "channel": str(_reading.get("channel") or ""),
                "ledger": str(_reading.get("ledger") or ""),
                "submitted": bool(_vs.get("submitted")),
                "skipped": bool(_vs.get("skipped")),
                "why": str(_reading.get("why") or _vs.get("why") or ""),
            }
        # ---- 逐条交差读数（业主 2026-11-02：「一个F可以产出多条成果」）-------------
        # 历史行里那一格 `delivered` 自本批起是「整个任务」的读数（有成果、且每条都已签），
        # 不是这一轮那一份 —— 后者在 `v_sign` 里。读不到计划的旧行没有这一格，照旧能读。
        if deploy.get("delivery"):
            _dl = dict(deploy["delivery"] or {})
            history_row["delivery"] = {
                "checked": bool(_dl.get("checked")),
                "total": _dl.get("total"),
                "signed_count": _dl.get("signed_count"),
                "pending_count": _dl.get("pending_count"),
                "unsigned_count": _dl.get("unsigned_count"),
                "proof_count": _dl.get("proof_count"),
                "abandoned_count": _dl.get("abandoned_count"),
                "unfinished_count": _dl.get("unfinished_count"),
                "coverage": str(_dl.get("coverage") or ""),
                "state": str(_dl.get("state") or ""),
                "legal_stop": bool(_dl.get("legal_stop")),
                "delivered": bool(_dl.get("delivered")),
            }
            history_row["delivered"] = bool(_dl.get("delivered"))
            # F 自己写的自评原样留痕（下一轮/`status` 读签时还要用它；推出来的不落盘，
            # 否则下次会冒充成"F 自己的自评"）。
            if deploy.get("self_assessment_raw") is not None:
                history_row["self_assessment"] = deploy.get("self_assessment_raw")
        if deploy.get("report_path"):
            history_row["report_path"] = str(deploy["report_path"])
        # 打回重写那一档的逐条说明要进 history：下一轮提示词的"前几轮发生过什么"
        # 读的就是 history（`_history_digest`）—— 只写进日志等于没告诉 F 怎么改。
        if deploy.get("deps_refused_findings"):
            history_row["deps_refused_findings"] = [
                dict(x) for x in (deploy["deps_refused_findings"] or [])]
        if deploy.get("deps_refused"):
            history_row["deps_refused"] = str(deploy["deps_refused"])
        # 2026-11-05（缺陷乙）：受控拒绝的机器读数进 history —— `kind` / `streak` /
        # `next_step` 三格。为什么必须落盘：下一轮（与 `attack.status` 的 `history_tail`）
        # 靠它判断"这是不是同一种形状的第 N 次"，否则重试永远是静默的。
        if deploy.get("refusal"):
            history_row["refusal"] = dict(deploy["refusal"])
        if deploy.get("deps_washing"):
            history_row["deps_washing"] = [dict(x) for x in (deploy["deps_washing"] or [])]
        # ---- 2026-11-07（业主裁定）：手稿登记条目的身份进 history --------------------
        #
        # "登记一次、证明改 N 次"这件事必须在计划台账上读得出来（`proof_revisions`
        # 读数与下一轮提示词的 history 摘要都读它），否则只能靠数盘上有几份稿。
        for _key in ("proof_mode", "proof_registered", "proof_rewritten", "proof_no",
                     "proof_sha256", "proof_label", "proof_section_hashes",
                     "manuscript_migrated", "manuscript_path", "manuscript_id",
                     "manuscript_id_source"):
            if deploy.get(_key) not in (None, "", {}, []):
                history_row[_key] = deploy[_key]
        history.append(history_row)
        row["subgoals"] = subgoals
        row["history"] = history
        row["rounds"] = rounds + 1
        row["status"] = self._derive_status(subgoals, row)
        row["updated_at"] = self._stamp()
        row["best_partial"] = self._compose_best_partial(subgoals, rounds + 1)
        if row["status"] == "stalled" and not str(row["best_partial"]).strip():
            row["best_partial"] = NO_PROGRESS_NOTE
        self._write_plan(row, note=f"f.step:{deploy['action']}")

        out = {
            "plan_id": row.get("plan_id"),
            "round": rounds + 1,
            "sid": sid,
            "action": deploy["action"],
            "outcome": _step_outcome(deploy["outcome"]),
            "status": row["status"],
            "budget_left": _budget_left(budget, rounds + 1),
            "budget_known": reading["status"] == "known",
            "budget_reading": reading,
            "reason": deploy["detail"],
        }
        # P3-6：产物落点也进返回值（调用方不必再读一遍 history 才知道去哪看）。
        if deploy.get("statement_id"):
            out["statement_id"] = str(deploy["statement_id"])
        # ---- 送审与 V 签（业主 2026-11-02）：两件读数分开给。
        # `v_sign` / `delivery_state` / `delivery_label` 是「这一轮这一份」的四档；
        # `delivered` 自本批起是「逐条」的读数（有成果、且每一条都已签）——
        # 语义唯一来源 `agent_f/delivery.py::DELIVERED_MEANS`。
        if deploy.get("v_sign"):
            out["v_sign"] = dict(deploy["v_sign"])
            out["delivery_state"] = str(deploy.get("delivery_state") or "")
            out["delivery_label"] = str(deploy.get("delivery_label") or "")
        _delivery = dict(deploy.get("delivery") or {})
        if not _delivery:
            # 非 F 自己推理的那几档（E/A/B 的分派）不经过 `_apply_round`：读数照给。
            _delivery = self._delivery_reading(row)
        out["delivery"] = _delivery
        out["delivered"] = bool(_delivery.get("delivered"))
        for _key in _CLOSE_KEYS:
            out[_key] = _delivery.get(_key)
        out["delivery_state_plan"] = str(_delivery.get("state") or "")
        out["delivery_label_plan"] = str(_delivery.get("state_label") or "")
        out["state"] = str(_delivery.get("state") or "")
        if deploy.get("report_path"):
            out["report_path"] = str(deploy["report_path"])
        # ---- 证明手稿（业主 2026-10-24 最终形态：作者只写内容、B 读稿登记）：
        # `proof` 那一档的读数随返回值出去。为什么必须进返回值而不是只写在 `detail` 那句
        # 散文里：`deps_preview` 里带着依赖段解析结果与三态读数（present / missing /
        # not_applicable），调用方要能机械地读"这份手稿交给 B 会不会落成依赖边"。
        # 手稿全文不进返回值（它是盘上那一份，路径就是 `manuscript_path`）—— 模型的上下文
        # 里塞一整篇手稿不划算，而 D/B 需要时按路径读。
        if deploy.get("manuscript_path"):
            out["manuscript_path"] = str(deploy["manuscript_path"])
        # 2026-11-10：稿号也进返回值（改同一份稿时把它给回来，不靠猜名字）。
        if deploy.get("manuscript_id"):
            out["manuscript_id"] = str(deploy["manuscript_id"])
        if deploy.get("manuscript_id_source"):
            out["manuscript_id_source"] = str(deploy["manuscript_id_source"])
        # ---- 2026-11-07（业主裁定）：手稿登记条目的身份也进返回值 ----------
        for _key in ("proof_mode", "proof_registered", "proof_rewritten", "proof_no",
                     "proof_sha256", "proof_label", "proof_section_hashes",
                     "manuscript_migrated"):
            if deploy.get(_key) not in (None, "", {}, []):
                out[_key] = deploy[_key]
        # 2026-11-04（改名与签拆开）：改名到哪一步、签块搬没搬，必须进返回值。
        # 只给 `manuscript_path` 的话，"改名了但标题没重写"与"完整改名"在调用方
        # 眼里长得一样（两者都是按号的名字）。
        for _key in ("manuscript_published", "manuscript_renamed_from",
                     "manuscript_retitled", "manuscript_sign_moved",
                     "manuscript_publish_problem", "manuscript_sign_step"):
            if _key in deploy:
                out[_key] = deploy[_key]
        if deploy.get("deps_preview"):
            out["deps_preview"] = dict(deploy.get("deps_preview") or {})
        # ---- 登记那一刻手上的稿是从哪来的（`param` / `none`）：这一格要能被机械读出来，
        # 否则"F 这一轮根本没把稿递给登记"与"递了、只是收方没读"在读数上长得一样
        # （2026-10-26，死结 1 的读数面）。
        if deploy.get("manuscript_source"):
            out["manuscript_source"] = str(deploy["manuscript_source"])
        # ---- 秘书洗稿的读数（业主 2026-10-26 晚：「洗稿结果进 F.step 的返回值与 detail」）。
        # 打回那一档走的是同一条路（`outcome=no_change` + `deps_refused*`），于是
        # "打回重写"与"已提交"在返回值上分得开 —— 而不是都叫"这一轮没推进"。
        for key in ("manuscript_washed", "deps_section_filled", "deps_washing",
                    "deps_refused", "deps_refused_findings", "wash_checked",
                    "wash_reason", "wash_actor", "missing_seam"):
            if key in deploy:
                out[key] = deploy[key]
        # ---- 形式化子目标派不出去那一档的读数（受控码 `formal_edge_missing`）。
        # 为什么必须进返回值：那一档的结论是"这条子目标该由谁派"，而"该由谁派"是一个
        # 机械可读的事实（`dispatchable_by` / `edge_exists`），不该只活在这轮的 detail 散文里
        # —— 调用方（D / M / 人）要能直接读到"这条边不存在，需要 B 派 L"。
        if deploy.get("formal_dispatch"):
            out["formal_dispatch"] = dict(deploy["formal_dispatch"])
        self.last_step = out
        return out
