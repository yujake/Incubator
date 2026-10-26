"""角色 F 的动作 `create_plan`（`goal-7f5116c1` M6：从 `agent_f.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import AT, Any, Mapping, PlanError, S, Sequence, TERMINAL_STATUSES
from ..refusals import refuse

#: 形式化那一档在 F 这一侧不许立项的受控码（`refuse` 的 `kind`）。
#:
#: 为什么单独一个码、而不是沿用 `subgoal_without_testable` 那一个：两条拒信要调用方做的
#: 事相反 —— 那一条是"把怎么算做成补上再来"，这一条是"别在 F 这里立它，把命题交 B"。
#: 折成一个码，模型只会去补 `testable`，然后照样立一条不该存在的子目标。
#:
#: 与 `agent_f/core.py::FORMAL_EDGE_MISSING_REASON`（`formal_edge_missing`）的分工：
#: 那一个是"台账里已经有一行形式化子目标，而 F 派不出去"（人手改盘 / 旧计划）；
#: 这一个是在立项那一刻就说"别写它"。两个码说的是两件事，都不许折进对方。
FORMAL_IS_NOT_F_TODO = "formal_is_not_f_todo"

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
        
        1. 预算必须完整（`check_budget`），不完整就拒绝创建 ——`budget=None` 表示"没给"，此时用本次运行的默认预算（`DEFAULT_BUDGET`，
        可用构造 config 按维度覆盖，见 `_default_budget`）；显式给了一个缺键的 dict 则是"给了但不完整"，拒绝（返回 `created=False`，
        不写库）。这两种情况必须分开，否则"我们忘了配预算"会被默认值掩盖。 2. 同一 `problem_key` 已有未终结的计划 ⇒ 不新建，返回已存在的`plan_id`。
        理由：攻坚是多轮的，而"再立一个项"这个动作看起来无害，实际会让同一个难题被并行地攻两遍，两边的 history 各自长，谁也看不到对方已经证否的路径。 3. 子目标必须能
        被 `AttackPlan.validate` 接受 —— 所以在事务外先建行并`validate()`，非法就当场抛，绝不把非法行交给事务。
        """
        default_budget = self._default_budget()
        chk = AT.check_budget(dict(budget) if budget is not None else dict(default_budget))
        if not chk["complete"]:
            # 走「统一的拒绝形态」（`refusals.refuse`）：这一支是拒绝，而它此前只给
            # `created: false` + `reason` —— 调用方（主控）看到的 `outcome` 于是是 `ok`
            # （「执行完成（handler 未声明 outcome，按有产出处理）」），真机里它连着 6 次
            # 以为自己立了项，而 `attack_plans` 一行都没有（`draft/37` §127）。
            # `conductor._end_from_payload` 据此落 `refused`（参数不完整 ⇒ `invalid_params`）。
            return refuse(
                "budget_incomplete",
                f"拒绝创建：{chk['reason']}。"
                "（预算不完整时不立项，而不是先用默认值把洞补上再跑）",
                # `reason` 这一键既有调用方与既有判据在读：统一形态不许把它们的读数弄丢
                # （`refuse` 的 `**extra` 就是为这件事留的）。
                reason=(f"拒绝创建：{chk['reason']}。"
                        "（预算不完整时不立项，而不是先用默认值把洞补上再跑）"),
                created=False, plan_id=None, duplicate=False,
                # 五条分支（成功 / 判重命中 / 预算被拒 / 缺 testable / 立了形式化子目标）
                # 的键集合逐字相同（2026-10-27）：`returns=` 只有一套键，而两套键之间必然有一格是"声明了
                # 却永远不出现"或"出现了却没声明"。没有计划可读数的那几格给空读数
                # （`""` / `0` / `[]`），而不是缺键 —— 「这一格没有读数」与「这一格是空」
                # 由键的存在区分开（与 `verify.verify_proof` 三条返回路径同一条纪律）。
                status="", subgoals=0, subgoal_id="",
                missing=chk["missing"], budget=dict(budget or {}),
            )

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
                # 判重命中也把"那个已有计划长什么样"一并给读数（键集合与成功支逐字相同）。
                "budget": dict(existing.get("budget") or {}),
                "subgoals": len(list(existing.get("subgoals") or [])),
                "subgoal_id": "",
                "missing": [],
                "kind": "",
                "error": "",
                "refusal_reason": "",
                "reason": (
                    f"problem_key={problem_key!r} 已有未终结的计划 {existing.get('plan_id')}"
                    f"（status={existing.get('status')}）⇒ 不新建。"
                    "重复立项会让同一个难题被并行攻两遍，两边的 history 互相看不见"
                ),
            }

        goal_rows = [self._normalize_subgoal(s, i) for i, s in enumerate(subgoals or [])]
        # ---- 形式化那一档在 F 这里不许立项（业主 2026-10-27：「我们现在不准边研究边 lean，
        #      我在 L 侧已经描述很清楚了什么时候能派 L」） ----
        #
        # 为什么判据要前移到写侧：改前的形态是"立得出来、然后每一轮死一次" ——
        # formal 子目标照建不误，直到 `step` 派活那一步才落 `dead_end(formal_edge_missing)`。
        # 那等于把"这个形状根本不该在 F 这里"这句话推到花钱之后才说：预算照花、history
        # 堆一串同一个死路，而模型从来没被告知"别立它"。
        #
        # 判据只有一处：`core._is_formal_subgoal`（`method="formal"` 或 `owner="L"`）——
        # 这里不另写一份"算不算形式化"。惰性 import：`core` 在 import 期会拉起本模块
        # （它要把动作 mixin 装起来），模块级 import 会成环。
        #
        # 为什么走 `refuse` 而不是 `PlanError`：这一档不是"参数写错了、改改再来"，
        # 而是"这个形状不属于这里" —— 前者要模型改参数重试，后者要它换一条路（把命题交 B）。
        # 处置方向相反，所以给受控码（终态落 `refused / invalid_params`，与
        # `subgoal_without_testable` 同族），而不是抛异常。
        from .core import FORMAL_OWNER, _is_formal_subgoal  # 惰性：见上

        for row in goal_rows:
            if not _is_formal_subgoal(row):
                continue
            sid = str(row.get("sid") or "")
            seen = "、".join(f"{key}={row.get(key)!r}" for key in ("method", "owner")
                            if str(row.get(key) or "").strip())
            msg = (
                f"子目标 {sid} 是形式化那一档（它写着 {seen}）—— 形式化不是流水线的一步，"
                "也不是 F 的活：只有 B 能派 L，而派不派由登记那条证明的人判断"
                "（`specs/l.py` 的裁定逐字：「只有 B 可以派 L」—— 理由「B 是 statements 的"
                "唯一登记方，所以『只让 B 派 L』结构上等于『L 形式化的东西一定出自 B 的库』，"
                "而形式化的成本由那个登记证明的人来判断」；「F → L」那条边「本批曾开又撤回："
                "F 的攻坚是流水线的一环，挂在它下面就是把形式化变成流水线的一步，"
                "而业主的裁定把这件事留给 B」）。"
                "⇒ 这一笔不立（一条都不写库）：把这条命题交给 B"
                "（`B.register_statement` 登记，之后要不要、什么时候形式化由 B 判断），"
                "F 的攻坚走它自己那一格。"
            )
            return refuse(
                FORMAL_IS_NOT_F_TODO, msg,
                # `reason` 这一键既有调用方与既有判据在读：统一形态不许把它们的读数弄丢。
                reason=msg,
                created=False, plan_id=None, duplicate=False,
                status="", subgoal_id=sid, subgoals=len(goal_rows),
                missing=[], budget=dict(budget or {}),
            )

        # ---- 可检验形式是立项的硬条件（2026-10-27，真机 `PLAN 000000 round1 action=dead_end`） --
        #
        # 改前的形态：子目标没有 `testable` 也照样落库，于是"这一笔立不成立"要到
        # `step` 里 `attackround.pre_spend_gate` 那一道才被挡 —— 真机读数逐字是
        # `round1 action=dead_end product=dead_end detail="子目标 a（owner=F）：花钱之前的
        # 闸门没过：子目标没有可检验形式（testable 空）"`：计划建成了、F 一次推理都没发、
        # 预算烧在"每条子目标各死一轮"上，而模型从头到尾没被问过一句"怎么算做成了"。
        #
        # 所以判据前移到写侧：立项那一次就把"没有可检验形式"这件事拒掉，整笔不写库
        # （`refuse` 的受控码 `subgoal_without_testable` ⇒ 终态落 `refused/invalid_params`，
        # 不是"执行完成"）。这里读的是 `_normalize_subgoal` 归一之后的那一格 ——
        # `testable` / `check` / `criterion` / `acceptance` 四种写法都算写了
        # （模型真用过 `check`），所以这不是"要求模型猜键名"，而是"要求它真的写过一次"。
        #
        # 不许在这里替研究定标准（凭空造一个 `testable`）：那会把"不知道该判什么"
        # 伪装成"已经能判" —— 与 `_spec_from_testable` 那段拒绝凭空造 `params` 同一条理由。
        for row in goal_rows:
            sid = str(row.get("sid") or "")
            if str(row.get("testable") or "").strip():
                continue
            msg = (
                f"子目标 {sid} 没有可检验形式（testable）—— 计划里每一条都要写"
                "\"怎么算做成了\"，否则花钱闸会在推理之前把它挡掉，F 一次都跑不起来"
            )
            return refuse(
                "subgoal_without_testable", msg,
                # `reason` 这一键既有调用方与既有判据在读：统一形态不许把它们的读数弄丢。
                reason=msg,
                created=False, plan_id=None, duplicate=False,
                status="", subgoal_id=sid, subgoals=len(goal_rows),
                missing=[], budget=dict(budget or {}),
            )

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
            # 四条分支键集合逐字相同（见预算被拒那一支的注释）：没有拒绝的那几格给空读数。
            "subgoal_id": "",
            "missing": [],
            "kind": "",
            "error": "",
            "refusal_reason": "",
            "reason": f"已立项 {pid}（深度 {depth}，子目标 {len(row.subgoals)} 个，预算 {row.budget}）",
        }
        self._log(f"plan {pid} created", problem_key=problem_key)
        return out
