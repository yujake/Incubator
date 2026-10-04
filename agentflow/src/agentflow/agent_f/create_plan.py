"""角色 F 的动作 `create_plan`（`goal-7f5116c1` M6：从 `agent_f.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import AT, Any, Mapping, PlanError, S, Sequence, TERMINAL_STATUSES

class _CreatePlan:
    def create_plan(
        self,
        problem: str,
        problem_key: str,
        *,
        for_question_id: str | None = None,
        subgoals: Sequence[Mapping[str, Any]] | None = None,
        budget: Mapping[str, Any] | None = None,
        depth: int = 0,
        parent_plan_id: str | None = None,
    ) -> dict:
        """为一个难题立项。

        返回 ``{"created", "plan_id", "reason", "duplicate", "status", "budget"}``。

        三条硬规矩：

        1. 预算必须完整（`check_budget`），不完整就拒绝创建 ——
           `budget=None` 表示"没给"，此时用本次运行的默认预算
           （`DEFAULT_BUDGET`，可用构造 config 按维度覆盖，见 `_default_budget`）；
           显式给了一个缺键的 dict 则是"给了但不完整"，拒绝
           （返回 `created=False`，不写库）。这两种情况必须分开，
           否则"我们忘了配预算"会被默认值掩盖。
        2. 同一 `problem_key` 已有未终结的计划 ⇒ 不新建，返回已存在的
           `plan_id`。理由：攻坚是多轮的，而"再立一个项"这个动作看起来
           无害，实际会让同一个难题被并行地攻两遍，两边的 history 各自长，
           谁也看不到对方已经证否的路径。
        3. 子目标必须能被 `AttackPlan.validate` 接受 —— 所以在事务外先建行并
           `validate()`，非法就当场抛，绝不把非法行交给事务。
        """
        default_budget = self._default_budget()
        chk = AT.check_budget(dict(budget) if budget is not None else dict(default_budget))
        if not chk["complete"]:
            return {
                # `ok: False`（`draft/37` §127 的真机读数）：这一支是「拒绝」，
                # 而它此前只给 `created: false` + `reason` —— 调用方（主控）看到的
                # `outcome` 于是是 `ok`（"执行完成（handler 未声明 outcome，按有产出处理）"），
                # 真机里它连着 6 次以为自己立了项，而 `attack_plans` 一行都没有。
                # 判据在 `conductor._end_from_payload`：payload 里 `ok=False` ⇒ refused。
                # 分档规则是"声明了受控的 `refusal_reason` ⇒ refused；只说 ok=False ⇒ failed"，
                # 而这一支是「调用方参数不完整」（改参数就能过）⇒ `invalid_params`。
                "ok": False,
                "refusal_reason": "invalid_params",
                "kind": "budget_incomplete",
                "created": False,
                "plan_id": None,
                "duplicate": False,
                "reason": (
                    f"拒绝创建：{chk['reason']}。"
                    "（预算不完整时不立项，而不是先用默认值把洞补上再跑）"
                ),
                "missing": chk["missing"],
                "budget": dict(budget or {}),
            }

        if not str(problem).strip():
            raise PlanError("problem 不能为空")
        if not str(problem_key).strip():
            raise PlanError("problem_key 不能为空（没有它就无法判重）")

        existing = None
        for r in self.store.rows("attack_plans"):
            if str(r.get("problem_key")) == str(problem_key) and str(r.get("status")) not in TERMINAL_STATUSES:
                existing = r
                break
        if existing is not None:
            return {
                # `ok: True`（幂等成功，不是拒绝）：同一 `problem_key` 已经有未终结的计划
                # ⇒ "这件事已经立过项了"，那是一个「正常结局」（返回已有 plan_id）。
                # 显式写出来，是为了与上面那一支的 `ok: False` 分开 ——
                # 三态纪律：`没有可做的` 与 `被拒了` 不许长得一样。
                "ok": True,
                "created": False,
                "plan_id": str(existing.get("plan_id")),
                "duplicate": True,
                "status": existing.get("status"),
                "reason": (
                    f"problem_key={problem_key!r} 已有未终结的计划 {existing.get('plan_id')}"
                    f"（status={existing.get('status')}）⇒ 不新建。"
                    "重复立项会让同一个难题被并行攻两遍，两边的 history 互相看不见"
                ),
            }

        goal_rows = [self._normalize_subgoal(s, i) for i, s in enumerate(subgoals or [])]
        with self.store.tx("attack_plans", actor=self.actor, note="f.create_plan") as tx:
            pid = tx.alloc_id("plan")
            try:
                row = S.AttackPlan(
                    plan_id=pid,
                    problem=str(problem),
                    problem_key=str(problem_key),
                    for_question_id=for_question_id,
                    status="open",
                    rounds=0,
                    budget={k: int(v) for k, v in dict(budget or default_budget).items()},
                    subgoals=goal_rows,
                    history=[],
                    depth=int(depth),
                    parent_plan_id=parent_plan_id,
                    best_partial="",
                    created_at=self._stamp(),
                    updated_at=self._stamp(),
                    created_by=self.actor,
                )
                # 早炸：非法子目标/深度/预算在写入前就会被拒，事务里什么都留不下。
                row.validate()
            except ValueError as e:
                # 不吞异常：这里只是把 `schema` 的 `ValueError` 换成语义正确的
                # `PlanError`（`ToolError` 子类），好让工具层给出
                # `kind="tool_error"` + 具体原因，而不是无声的 `kind="unexpected"`。
                # 失败本身照旧发生、事务照旧回滚 —— 这正是"炸得要响、还要说清为什么"。
                raise PlanError(
                    f"计划参数不合 schema 硬约束（plan 未创建）：{e}。"
                    f"problem_key={problem_key!r}，深度 {depth}，子目标 {len(goal_rows)} 个。"
                    "非法计划不许落库：落进去之后每一轮 step 都会在同一个坏行上再炸一次"
                ) from e
            tx.upsert("attack_plans", row.to_dict(), note=f"create_plan:{problem_key}")

        out = {
            "ok": True,
            "created": True,
            "plan_id": pid,
            "duplicate": False,
            "status": row.status,
            "budget": dict(row.budget),
            "subgoals": len(row.subgoals),
            "reason": f"已立项 {pid}（深度 {depth}，子目标 {len(row.subgoals)} 个，预算 {row.budget}）",
        }
        self._log(f"plan {pid} created", problem_key=problem_key)
        return out
