"""角色 D 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_d.py` 只是把它再导出一次。
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
        "D", "probe_c",
        "按问题向 C 点菜并记录问答（只读 C + 写回本问题行）",
        _obj({"qid": _S, "qrow": _OBJ}, ("qid",)),
        "list[dict]（本轮问到的条目）", side_effect="write_local", handler_name="probe_c",
    ),

    ActionSpec(
        "D", "ingest",
        "把一份 C 报告消化成研究问题",
        _obj({"report": _OBJ, "c_contradictions": _OBJ}, ("report",)),
        "新建的 question_id 列表", side_effect="write_local", handler_name="ingest",
    ),

    ActionSpec(
        "D", "ingest_detailed",
        "同 ingest，但返回逐条明细（含被跳过者及原因）",
        _obj({"report": _OBJ, "c_contradictions": _OBJ}, ("report",)),
        "dict", side_effect="write_local", handler_name="ingest_detailed",
    ),

    ActionSpec(
        "D", "trace_question",
        "把一个研究问题溯源到它依赖的 L1/L2/L3 证据（只读）",
        _obj({"qid": _S}, ("qid",)),
        "dict", side_effect="read", handler_name="trace_question",
    ),

    ActionSpec(
        "D", "trace_l3",
        "L3 下钻：读文献正文里该关系所在段落",
        _obj({"evidence": _OBJ, "lit_ids": _ARR_S}, ("evidence",)),
        "dict", side_effect="read", handler_name="trace_l3",
    ),

    ActionSpec(
        "D", "assess",
        "判定证据是否就绪（决定要不要向 A 要检索）",
        _obj({"qid": _S, "evidence": _OBJ}, ("qid",)),
        "verdict dict", side_effect="read", handler_name="assess",
    ),

    ActionSpec(
        "D", "submit_gaps",
        "把缺口提交为检索请求（受配额与已提交集约束）",
        _obj({"qid": _S}, ("qid",)),
        "新建的 request_id 列表", side_effect="write_local", handler_name="submit_gaps",
    ),

    ActionSpec(
        "D", "consider",
        "重新考虑一个问题（可能提到 researching）",
        _obj({"qid": _S}, ("qid",)),
        "dict", side_effect="write_local", handler_name="consider",
    ),

    ActionSpec(
        "D", "poll",
        "看新到的文献是否答上了在等的问题",
        _obj({"relations": _OBJ}),
        "dict", side_effect="write_local", handler_name="poll",
    ),

    ActionSpec(
        "D", "adjudicate",
        "裁决一条矛盾问题（I2 的闭环）",
        _obj({"qid": _S}, ("qid",)),
        "裁决 dict", side_effect="write_local", handler_name="adjudicate",
    ),

    ActionSpec(
        "D", "research",
        "回答一个证据就绪的问题",
        _obj({"qid": _S}, ("qid",)),
        "dict（含结论与证据代号）", side_effect="write_local", handler_name="research",
    ),

    ActionSpec(
        "D", "run_round",
        "把 ingest ->…-> research 串成一轮（有界：limit）",
        _obj({"report": _OBJ, "submit": _B, "limit": _I}, ("report",)),
        "本轮汇总 dict", side_effect="write_local", handler_name="run_round",
    ),

    ActionSpec(
        "D", "write_report",
        "把研究结果渲染成 markdown 报告",
        _obj({"out_path": _S}),
        "写出文件的路径", side_effect="write_local", handler_name="write_report",
    ),

    ActionSpec(
        "D", "register_conjecture",
        "登记或更新一条猜想（省略 conjecture_id ⇒ 新建）；状态机由 schema 判，"
        "被引用的实验/文献必须在库里",
        _obj({"statement": _S, "origin": _S, "conjecture_id": _S, "testable": _OBJ,
              "form": {"type": "string", "enum": list(S.CONJECTURE_FORMS)},
              "negation_statement": _S,
              "status": {"type": "string", "enum": list(S.CONJECTURE_STATUSES)},
              "experiment_ids": _ARR_S, "proof_experiment_id": _S,
              "counterexample_experiment_id": _S, "promoted_to": _OBJ,
              "known_lit_id": _S, "withdraw_reason": _S, "notes": _S},
             ("statement", "origin")),
        "dict（落库后的 conjectures 行）", side_effect="write_local",
        handler_name="register_conjecture",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 D（构造期拿到同一个 C 实例：`peers["C"]`，由接线层的单例保证）。"""
    from ..agent_d import AgentD

    return AgentD(d.store, config=dict(d.config), llm=d.llm, c=d.peers["C"], actor=d.actor)


#: 本角色的声明。
SPEC = AgentSpec(
    role='D',
    brief=    AgentBrief(
        duty='研究循环：把一个研究方向收敛成一个有证据支撑的结论，或如实说证据不足',
        boundary=(
            '只许使用证据包里出现过的关系 id 与引文，不许引入包外的事实。',
            '置信度只能等于或低于确定性口径算出的那一档。',
            '证据不足时正确结论是低置信度与缺口清单，不是把话写圆。',
            '缺口要变成具体的检索请求（交给 A）或实验请求（交给 E），不要只写在报告里。',
        ),
        policy=(
            '进入下一层验证的门槛由确定性判据给（度数、通过回验的关系条数、是否成对矛盾）：门槛没到就不下钻，先补证据。',
            '你的结论里如果有下游（E 做实验、G 写稿、H 审校）必须遵守的约束，用 message 把它发给对方，而不是只写在报告里 —— 报告不会自己走到他们手上。',
            '对 B 的文字版证明做初步数学审阅（§16 P2）：逐条读出「这条证明用了哪些假设、哪一步是它真正承重的那一步」，给三态结论（成立 / 有毛病 / 看不出来）并写明依据（引哪一行、缺哪一步）。',
            '报「有毛病」时必须附可挽救性评估：差什么（缺一个引理 / 少一个条件 / 换一个定义）、要多少预算（大概几步、要不要形式化）、救不回来的话会连累哪些结论。只报「有问题」而不说「要什么才能修」，等于把问题原样丢回去。',
        ),
        signature_error='把没有证据写成没有争议。',
        deliverable='analysis_reports 里的分析、结论、建议三层，以及它可以交出去的缺口清单。',
        stance=(
            "研究的标志不是把话写圆，而是把'卡在哪'定位到具体的一步：缺哪条证据、缺哪个反例、缺哪个定义。",
            '遇到互相矛盾的文献时，先读原始证明的那一步，再判断是结论错、条件被漏、还是口径不同 —— 不盲从权威，也不盲从你自己上一轮的判断。',
            '证不出来时正确做法是把猜想明确写下来（并给出可判定它真假的路径），而不是换成模糊表述。',
            '每一轮的判断都要能解释上一轮为什么改主意：草稿本就是那条线索。',
            '你的审阅是「初步」的：数学对错的最终背书在形式化（E）或人。你要做的是把「这里站不站得住」变成一条可判定的读数（依据 + 三态），而不是替人下最终结论。',
        ),
    ),
    emphasis={
        '眼睛': 'core',
        '耳朵': 'core',
        '脑子': 'core',
        '手': 'core',
        '能讨论': 'core',
        '高观点': 'core',
        '能互动': 'core',
        '能思辨': 'core',
        '敢创新': 'core',
        '有品味': 'core',
    },
    local_notes={
        '耳朵': 'E 的反例、C 的结构读数、A 的新文献都可能推翻你上一轮的判断：听到就改做法。',
        '能互动': '低置信度要如实说：结论强度与证据相称，不替用户把话说满；真要用户定的取舍就用 ask_user 问，等不到就按最保守的做法并写进结论。',
        '敢创新': '证不出来时把猜想明确写下来，并给出可判定它真假的路径。',
        '有品味': '删掉说不清的段落、把特例归到一般命题下：取舍要能说出口。',
        '眼睛': '读证据包与原文：每条结论都要能指回具体的关系 id 与引文。',
        '脑子': "把'这个方向有没有东西'推到'卡在哪一步'：缺证据、缺定义、还是缺反例。",
        '手': '写分析报告、写研究笔记、把缺口变成具体请求交给 A 或 E。',
        '能讨论': '证据变了就改结论：与 C/E/A 来回对齐，而不是固守上一轮的判断。',
        '高观点': '把局部结论挂到结构上：哪些是一般命题的特例，哪些其实互相冲突。',
        '能思辨': '矛盾出现时读原始证明那一步：是结论错、条件被漏，还是口径不同。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'A',
        'B',
        'C',
        'E',
        'F',
    ),
    write_set=frozenset((
                     'research_questions',
                     'search_requests',
                 )),
    class_path='agentflow.agent_d:AgentD',
    actions=ACTIONS,
    peers=('C',),
    build=_build,
)
