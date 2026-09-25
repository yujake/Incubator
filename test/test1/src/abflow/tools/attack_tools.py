"""F 的工具：**多轮难题攻坚**。

## 为什么"攻坚"需要独立的预算模型

D 的问题生命周期是"缺口 → 补证据 → 研究 → 回答"：它**有终点**，因为
"证据够了"是一个可判定的条件。而难题攻坚没有这个性质 —— "还没做出来"
永远成立，所以一个没有预算的攻坚循环会**一直跑下去**，而且它跑得越久，
看起来越像在工作。

因此本模块把三维预算（FC-18）做成**可机械检查**的东西：

- `max_rounds` —— **生命周期总量**：这个难题总共允许几轮；
- `max_parallel_subgoals` —— **瞬时并发**：一轮里允许同时推进几个子目标；
- `max_persist_attempts` —— **单点重试**：同一个子目标最多重试几次；
- `max_depth` —— **嵌套深度**：攻坚中派生出的新难题最多嵌套几层。

只有总量没有并发 ⇒ 一轮可以无限扇出（瞬时打爆配额）；
只有并发没有总量 ⇒ 扇出可以无限持续（永不停止）。
**两类必须同时存在**，缺一类就等于没有上限。

## `can_round` 的两个维度**不能混为一谈**（读代码前先看这一段）

`can_round(budget, rounds_done=..., depth=...)` 同时检查两件事，但它们的
**后果完全不同**：

- 轮数用尽 ⇒ **这个计划该停了**（交出 `best_partial`，标 `stalled`）；
- 深度到顶 ⇒ **不能再派生新的子计划**，但这个计划本身的轮次照常推进。

把后者也当成"该停了"，会让一个深度恰好到顶的计划**连第一轮都跑不了** ——
那是把"不能再分子问题"误读成了"这个问题不能做"。所以 `AgentF.step` 只在
**轮数**维度用 `can_round` 做终止判据（见 `agent_f.py` 的说明），
深度维度由 `can_derive` 单独暴露给"要不要派生"这个决策。

## 工具与智能体的分工

`attack.create_plan` / `attack.step` / `attack.status` / `attack.list_plans`
是对 `abflow.agent_f.AgentF` 的**薄封装**（惰性导入避免成环）：写入逻辑只有一份。
`attack.check_budget` / `attack.pick_next_subgoal` 是纯函数，直接在这里实现，
`AgentF` 转发过来 —— 与此前一样，"不要发明第二套判据"。
"""

from __future__ import annotations

from typing import Any, Sequence

from .base import ParamError, ToolRegistry, ToolSpec, fail, ok

#: **读**计划的角色：F 做攻坚；D 会把"多轮未收敛的问题"升级给 F，所以要能读；
#: G 需要读攻关结论来写稿；H 需要核对"stalled 有没有谎报成 resolved"。
_READ_ROLES = ("F", "D", "G", "H")

#: **写**计划的角色：只有 F。
#:
#: ⚠️ 为什么把 `create_plan` / `step` 收窄到 F 一个人（而读侧仍是四个角色）：
#: "谁需要**看见**这件事"与"谁有权**决定**这件事"是两个不同的问题。
#: 让 D/G/H 也能立项或推进，就等于把 F 的终止条件暴露给三个不受其预算约束的
#: 调用方 —— 而"多轮攻坚必须有唯一的主人"正是 FC-18 那套预算能成立的前提。
#: 收窄的成本只是 D 想立项时要显式调用 `AgentF`（一次有意的决定），
#: 收益是"谁会推进这个计划"这个问题有唯一答案。
_WRITE_ROLES = ("F",)

#: 默认预算。数字本身可以调，**但四类键必须都在**（见 `check_budget`）。
DEFAULT_BUDGET: dict[str, int] = {
    "max_rounds": 6,
    "max_parallel_subgoals": 2,
    "max_persist_attempts": 2,
    "max_depth": 2,
}

_REQUIRED_BUDGET_KEYS = ("max_rounds", "max_parallel_subgoals", "max_persist_attempts", "max_depth")

#: 终结状态（**不能自动重入**）。`stalled` 也在其中：它表示"预算用尽仍未解决"，
#: 不是"暂时停下等一会儿"。把它排除在外，循环下一轮就会把它当活计划重新拾起，
#: 于是"预算用尽"这个终止条件形同虚设。
TERMINAL_STATUSES = ("resolved", "abandoned", "stalled")


def check_budget(budget: dict | None) -> dict:
    """检查预算是否完整、是否还允许再开一轮。**纯函数，不碰存储。**

    返回 ``{"checked", "complete", "missing", "allowed", "reason"}``。

    ⚠️ 三态在这里的具体形态：`checked=False` 表示"没检查"（没给预算），
    而 `allowed=False` 表示"检查了、不许"（预算用尽）。把这两者折叠成同一个
    `False`，就会让"我们忘了配预算"看起来像"预算用完了"。
    """
    if budget is None:
        return {
            "checked": False,
            "complete": False,
            "missing": list(_REQUIRED_BUDGET_KEYS),
            "allowed": None,
            "reason": "没有提供预算 ⇒ **没检查**。注意这与'预算用尽'是两件事",
        }
    missing = [k for k in _REQUIRED_BUDGET_KEYS if k not in budget]
    if missing:
        return {
            "checked": True,
            "complete": False,
            "missing": missing,
            "allowed": False,
            "reason": (
                f"预算缺少 {missing}。三维预算缺一不可（FC-18）："
                "只有轮数上限则单轮可无限扇出，只有并发上限则可无限轮"
            ),
        }
    return {
        "checked": True,
        "complete": True,
        "missing": [],
        "allowed": True,
        "reason": f"预算完整：{ {k: budget[k] for k in _REQUIRED_BUDGET_KEYS} }",
    }


def can_round(budget: dict | None, *, rounds_done: int, depth: int = 0) -> dict:
    """在给定预算与已做轮数下，能否再开一轮。

    ⚠️ 返回里的 `allowed=False` 可能来自**两个不同维度**（轮数 / 深度），
    调用方必须看 `blocked_by` 再决定处置（见模块 docstring）。
    """
    chk = check_budget(budget)
    if not chk["checked"]:
        return {**chk, "allowed": None, "blocked_by": "not_checked"}
    if not chk["complete"]:
        return {**chk, "blocked_by": "incomplete"}
    assert budget is not None
    mr = int(budget["max_rounds"])
    md = int(budget["max_depth"])
    if rounds_done >= mr:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "rounds",
            "reason": f"轮数已用尽 {rounds_done}/{mr} ⇒ 停止（此时必须交出 best_partial，而不是谎报成功）",
        }
    if depth >= md:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "depth",
            "reason": f"嵌套深度已到上限 {depth}/{md} ⇒ 不再派生新的攻坚计划",
        }
    return {
        **chk,
        "allowed": True,
        "blocked_by": None,
        "reason": f"允许第 {rounds_done + 1} 轮（上限 {mr}）",
    }


def can_derive(budget: dict | None, *, depth: int) -> dict:
    """能否从当前深度**派生一个子计划**（`depth+1`）。

    与 `can_round` 分开是有意的：一个计划"自己还能跑"与"还能再分子问题"
    是两个独立的问题，共用一个布尔会让深度到顶的计划被误判成"该停了"。
    """
    chk = check_budget(budget)
    if not chk["checked"] or not chk["complete"]:
        return {**chk, "allowed": None if not chk["checked"] else False, "blocked_by": "incomplete"}
    assert budget is not None
    md = int(budget["max_depth"])
    if depth + 1 > md:
        return {
            **chk,
            "allowed": False,
            "blocked_by": "depth",
            "reason": f"当前深度 {depth}，派生后为 {depth + 1} > max_depth={md} ⇒ 不许再分子问题",
        }
    return {
        **chk,
        "allowed": True,
        "blocked_by": None,
        "reason": f"当前深度 {depth}，派生后为 {depth + 1} <= max_depth={md}",
    }


def pick_next_subgoal(subgoals: Sequence[dict]) -> dict:
    """选下一个要推进的子目标。**确定性排序，不看运气。**

    次序（每一步都是"为什么它更该先做"）：

    1. `in_progress` —— 已经开始的最先接着做（避免半途而废的子目标永远烂在那里）；
    2. `todo` 且 `owner` 有明确归属 —— 可执行的优先；
    3. `blocked` —— 排在最后（它需要先解决卡点，而不是重试）。

    `closed` / `dropped` / `supported_not_proved` 一律不选：前两者是终态，
    第三者表示"数值支持但没有证明" —— 它已经被推进到本框架能推进的尽头了，
    再选它只会把资源从真正待办的子目标上挪走（FC-22）。

    全部不可选时返回 ``{"picked": False, "reason": ...}`` ——
    **不能返回 None 让调用方自己猜**。
    """
    def rank(sg: dict) -> tuple:
        st = str(sg.get("status") or "")
        order = {"in_progress": 0, "todo": 1, "blocked": 2}
        return (order.get(st, 9), str(sg.get("sid") or ""))

    pool = [s for s in subgoals if str(s.get("status") or "") in ("in_progress", "todo", "blocked")]
    if not pool:
        return {
            "picked": False,
            "subgoal": None,
            "reason": "没有可推进的子目标（全部 closed/dropped/supported_not_proved 或列表为空）",
        }
    pool.sort(key=rank)
    return {"picked": True, "subgoal": pool[0], "reason": f"按确定性次序选中 {pool[0].get('sid')}"}


def _root_for(root: Any, store: Any) -> Any:
    return root if root is not None else getattr(store, "root", None)


def _agent_for(store: Any):
    """构造一个 AgentF。**惰性导入**：agent_f 反向引用本模块，模块级导入会成环。"""
    from ..agent_f import AgentF  # 惰性：避免 tools ↔ agent 的循环导入

    return AgentF(store)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    root: Any = None,
    **_: Any,
) -> None:
    """装配 F 可见的攻坚工具。

    ⚠️ ``store`` 为 None 时三个**需要存储**的工具照样注册，调用时返回
    ``ok=False, kind="not_wired"``（FC-08）。不这样做的话，"没接线"会以
    "计划不存在"的形式出现在调用方眼里 —— 那是把"我们没接上"说成了
    "这个东西不存在"。
    """
    root = _root_for(root, store)

    def _need_store(tool: str):
        if store is None:
            return fail(
                f"{tool} 未接线：装配时没有提供 store。"
                "**未接线不等于'没有计划'**",
                kind="not_wired",
            )
        return None

    registry.register(
        ToolSpec(
            name="attack.check_budget",
            summary="检查攻坚预算是否完整、是否还允许再开一轮（四类键缺一不可）",
            params={
                "type": "object",
                "properties": {
                    "budget": {"type": "object"},
                    "rounds_done": {"type": "integer", "minimum": 0},
                    "depth": {"type": "integer", "minimum": 0},
                },
                "required": ["budget"],
                "additionalProperties": False,
            },
            handler=lambda budget, rounds_done=0, depth=0: ok(
                can_round(budget, rounds_done=rounds_done, depth=depth)
            ),
            side_effect="none",
            roles=_READ_ROLES,
            returns="{'checked','complete','missing','allowed','reason'}",
            tags=("attack", "budget"),
        )
    )

    registry.register(
        ToolSpec(
            name="attack.pick_next_subgoal",
            summary="按确定性次序选出下一个要推进的子目标（开始过的优先，卡住的最后）",
            params={
                "type": "object",
                "properties": {"subgoals": {"type": "array", "items": {"type": "object"}}},
                "required": ["subgoals"],
                "additionalProperties": False,
            },
            handler=lambda subgoals: ok(pick_next_subgoal(subgoals)),
            side_effect="none",
            roles=_READ_ROLES,
            returns="{'picked', 'subgoal', 'reason'}",
            tags=("attack",),
        )
    )

    registry.register(
        ToolSpec(
            name="attack.create_plan",
            summary=(
                "为一个难题立项（预算四类键缺一不可，不完整就拒绝创建）。"
                "同一 problem_key 已有未终结的计划时不新建，返回已有 plan_id"
            ),
            params={
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "problem_key": {"type": "string"},
                    "for_question_id": {"type": "string"},
                    "subgoals": {"type": "array", "items": {"type": "object"}},
                    "budget": {"type": "object"},
                    "depth": {"type": "integer", "minimum": 0},
                    "parent_plan_id": {"type": "string"},
                },
                "required": ["problem", "problem_key"],
                "additionalProperties": False,
            },
            handler=lambda problem, problem_key, for_question_id=None, subgoals=None, budget=None,
            depth=0, parent_plan_id=None: (
                _need_store("attack.create_plan")
                or ok(
                    _agent_for(store).create_plan(
                        problem,
                        problem_key,
                        for_question_id=for_question_id,
                        subgoals=subgoals,
                        budget=budget,
                        depth=depth,
                        parent_plan_id=parent_plan_id,
                    )
                )
            ),
            side_effect="write_local",
            roles=_WRITE_ROLES,
            returns="{created, plan_id, reason, plan?}",
            tags=("attack", "plan"),
        )
    )

    registry.register(
        ToolSpec(
            name="attack.step",
            summary=(
                "推进攻坚计划的一轮：按 owner 分派（E 做实验 / A 提检索 / B 提重抽取），"
                "C/D/F 的推理未接线则如实记 no_change，绝不假装做了"
            ),
            params={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
                "additionalProperties": False,
            },
            handler=lambda plan_id: (
                _need_store("attack.step") or ok(_agent_for(store).step(plan_id))
            ),
            side_effect="write_local",
            roles=_WRITE_ROLES,
            returns="{plan_id, round, sid, action, outcome, status, budget_left, reason}",
            tags=("attack", "loop"),
        )
    )

    registry.register(
        ToolSpec(
            name="attack.status",
            summary="读一个攻坚计划的完整可读视图（子目标状态计数、预算余量、history 尾部）",
            params={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
                "additionalProperties": False,
            },
            handler=lambda plan_id: (
                _need_store("attack.status") or ok(_agent_for(store).status(plan_id))
            ),
            side_effect="read",
            roles=_READ_ROLES,
            returns="{checked, plan_id, status, rounds, subgoal_counts, history_tail, ...}",
            tags=("attack",),
        )
    )

    registry.register(
        ToolSpec(
            name="attack.list_plans",
            summary="列出全部攻坚计划（可按 problem_key 过滤）。没有它就无法回答'这个难题立过项没有'",
            params={
                "type": "object",
                "properties": {
                    "problem_key": {"type": "string"},
                    "include_terminal": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            handler=lambda problem_key=None, include_terminal=True: (
                _need_store("attack.list_plans")
                or ok(_agent_for(store).list_plans(problem_key=problem_key, include_terminal=include_terminal))
            ),
            side_effect="read",
            roles=_READ_ROLES,
            returns="{checked, total, plans}",
            tags=("attack",),
        )
    )
