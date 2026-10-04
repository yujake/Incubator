"""角色 F 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_f.py` 只是把它再导出一次。
所以本文件在 `.noai-paths` 里受保护（改它等于改权限面 ⇒ 需要 2 名人审）；
动作表的每一行都从 `capabilities.py` 逐字搬来（含注释），判据见
`tests/test_agent_spec_reconciliation.py` 与 `tests/test_capabilities_two_layer.py`。
"""
from __future__ import annotations

from .. import schema as S
from ..agentspec import (
    _ARR_I,
    _ARR_OBJ,
    _ARR_S,
    _B,
    _I,
    _N,
    _OBJ,
    _S,
    ActionSpec,
    AgentBrief,
    AgentSpec,
    BuilderDeps,
    _obj,
)

#: 本角色的动作表（从 `capabilities.py` 逐字搬来）。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "F", "create_plan",
        "立项（预算不完整即拒绝，不写库）",
        _obj({"problem": _S, "problem_key": _S, "for_question_id": _S,
              "subgoals": {"type": "array", "items": _OBJ}, "budget": _OBJ,
              "depth": _I, "parent_plan_id": _S},
             ("problem", "problem_key")),
        "dict（plan_id）", side_effect="write_local", handler_name="create_plan",
    ),

    ActionSpec(
        "F", "step",
        "推进一轮（唯一会改计划的方法）",
        _obj({"plan_id": _S}, ("plan_id",)),
        "dict（本轮做了什么 / 新状态）", side_effect="write_local", handler_name="step",
    ),

    ActionSpec(
        "F", "status",
        "只读看一个攻坚计划的当前状态",
        _obj({"plan_id": _S}, ("plan_id",)),
        "dict", side_effect="read", handler_name="status",
    ),

    ActionSpec(
        "F", "list_plans",
        "只读列举攻坚计划",
        _obj({"problem_key": _S, "include_terminal": _B}),
        "dict", side_effect="read", handler_name="list_plans",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 F（构造期拿到同一个 E 实例：`peers["E"]`）。"""
    from ..agent_f import AgentF

    return AgentF(d.store, config=dict(d.config), llm=d.llm, e=d.peers["E"], actor=d.actor)


#: 本角色的声明。
SPEC = AgentSpec(
    role='F',
    brief=AgentBrief(
        duty='多轮难题攻坚：在预算内一轮一轮逼近平息或反例，并如实报告进展',
        boundary=(
            '终止条件是预算与轮次，不是感觉：预算耗尽必须停手并如实写未推进。',
            '不许把没推进写成已完成；台账里的每一步都要能看出这一轮做了什么、为什么停。',
            '不许自己改结论或证据：你的产出是攻击计划与进展，结论由 D 或人收口。',
            '需要 C/D/E 的推理而框架没接线时，如实写未接线，不许编一个中间结果顶上。',
        ),
        policy=(
            "每一轮先挑一个可判定的子目标，做完就落台账；子目标不可判定时先把它拆小。",
            "**立项不等于攻坚：`create_plan` 只是把难题摆上台面，推进它是 `attack.step`**"
            "（一轮一份 `history`；下一个子目标用 `attack.pick_next_subgoal` 的确定性次序取）—— "
            "`draft/37` §138 的 T2 四趟实测：`create_plan` 12 次而 `step` **0 次**，"
            "12 份计划的 `history` 全是空的。立项之后**同一轮里**就推进一步，再决定要不要继续。",
            "每一轮推进之后把**成果或困难**回报给发起人（`message` 给 D）：这一轮证了什么 / "
            "否了什么 / 卡在哪 / 下一步换哪个子目标。回报不是形式 —— D 用它决定继续攻坚还是改猜想；"
            "T2 里 F 与 D 之间的留言是 0 条，于是 D 永远不知道攻坚走到哪一步。",
            "连续两轮没有实质进展就换子目标，或者把计划落 `stalled` 并把卡点写进回报"
            "（`attack.status` 读得到它）。不许用'再建一份计划'代替推进：同一个 `problem_key` "
            "的重复 `create_plan` 会命中既有计划并把它原样返回 —— 那不是进展，是一次原地打转"
            "（`draft/37` §136 的活性判据会把它读出来）。",
        ),
        signature_error='把无变化写成有进展。',
        deliverable='attack_plans 行的子目标进展与终止原因。',
        stance=(
            "攻坚的产物是'离解决还差什么'，不是'我们做了很多轮'：每一轮都要让卡点更具体一点。",
            '允许提猜想：把猜想写成可判定的形式（谁、在什么条件下、能不能被一个反例推翻），然后交给 E 或 D 去验。',
            "被预算逼停时，把'停在哪里、下一步该从哪继续'写清楚 —— 那是下一轮能接着干的唯一理由。",
        ),
    ),
    emphasis={
        '眼睛': 'minor',
        '耳朵': 'core',
        '脑子': 'core',
        '手': 'minor',
        '能讨论': 'core',
        '高观点': 'minor',
        '能互动': 'core',
        '能思辨': 'core',
        '敢创新': 'core',
        '有品味': 'minor',
    },
    local_notes={
        '耳朵': "D/E/C 的回信决定下一轮往哪打；预算耗尽时把'停在哪、下一步从哪继续'说清楚。",
        '能互动': '阶段性汇报是交付的一部分：每一轮都要让卡点比上一轮更具体；要被放手跑多轮时，把「下一轮从哪继续」写清楚。',
        '敢创新': '猜想要写成可判定的形式（谁、什么条件下、能不能被一个反例推翻）。',
        '脑子': "每一轮都要让卡点更具体：从'不会做'到'缺这一条引理'。",
        '能讨论': '把进展与卡点摊给 D/E/C 看，让他们决定要不要换角度。',
        '能思辨': '此路不通时换一条独立的路，而不是把同一招做得更用力。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'A',
        'B',
        'C',
        'D',
        'E',
    ),
    write_set=frozenset((
                     'attack_plans',
                     'reprocess_requests',
                     'search_requests',
                 )),
    class_path='agentflow.agent_f:AgentF',
    actions=ACTIONS,
    peers=('E',),
    build=_build,
)
