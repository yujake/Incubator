# -*- coding: utf-8 -*-
"""角色 V（验证者）的声明（F-02）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_v` 只是把它实现出来。所以它进了 `.noai-paths`（改它等于改权限面
⇒ 需要 2 名人审），判据见 `tests/test_agent_spec_reconciliation.py` 与
`tests/test_capabilities_two_layer.py`。

## V 是什么（`draft/39` §3.21 一/五/六 的用户定案）

H 是稿件级正式审查（五元位第 5 位）；V 是证明级验证（五元位第 3 位）。
把"证明级"塞进 H 会把 H 的语义撑宽（一个人的两个判断面混在一起，读数也就分不开了），
所以它是独立角色。它做三件事（用户点名的 I12/I10/I17）：

1. I12 冷启动：每次审校开新会话，只给对象（证明全文）+ 只读查询面的读数 ——
   不给 F 的叙述、不给 store 句柄。独立性是结构性质，不是"约定只读"。
2. I10 硬禁令 + 同段依据：逐条查（无条件前提 / 无依据的步骤 / "易证、显然"这类缝 /
   引用的命题是否干净），每条问题指到那一步。
3. I17 整篇重读：把证明按写成后的样子当一次输入整体读，不只逐单元核对。

## 权限面：只读 + 自己的台账

`read_only=True`、`write_set=frozenset()`：V 不写任何表。它唯一的产物是
`verifications/<命题号>.jsonl` 这个文件（追加式，与手稿同一形态，不新增表）——
`capabilities.WRITE_SETS` 描述的是"会写哪几张表"，所以那里是空集，
而这一点由 `tools.READ_ONLY_ROLES` 里的 `"V"` 与 `for_role` 的结构性剥离一起守住。

## 边：只有 `F`（用户 2026-10-05 第七轮裁定）

V 只与 F 交互：F 提交、V 退回；不给 D、不给 E 当对话对象。
（`draft/39 §3.21 五`那张草表里还写着 `V → D` / `V → E`，那是被后续裁定覆盖的旧稿；
`draft/54 §1.1` 逐字记着"不要 `V→D`/`V→E`"。）
"""

from __future__ import annotations

from typing import Any

from ..agentspec import (
    ActionSpec,
    AgentBrief,
    AgentSpec,
    BuilderDeps,
    _I,
    _S,
    _obj,
)

#: 本角色的动作表。
#:
#: 三条动作全部声明 `side_effect="read"`（用户裁定）：V 在"会写哪几张表"这根轴上是
#: 只读的 —— 它的台账是一个文件，不是表。若把 `verify_proof` 写成 `write_local`，
#: `for_role("V")` 会把它从 V 自己看得见的工具面上剥掉（只读角色的结构性剥离）
#: ⇒ "动作登记了却永远调不到"，而判据只看名单、看不见这件事。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "V", "verify_proof",
        "把一份证明按写成后的样子整体重读：三态结论 + 每条问题指到步号，"
        "并写 verifications/<命题号>.jsonl",
        _obj(
            {
                "statement_id": {**_S, "minLength": 4, "maxLength": 4},
                "proof_text": _S,
                # 只读读数（命题现状 / 文献与实验台账摘要）由调用方取好传进来：
                # 传字符串而不是传 store，是为了让"它能碰什么"在接口上就固定下来
                # （I12 的结构形态，见 `verifications.cold_start_prompt`）。
                "readonly_facts": _S,
            },
            required=("statement_id", "proof_text"),
        ),
        "一行验证台账（含 v-NNNN / verdict / findings / proof_sha256）",
        side_effect="read", handler_name="verify_proof",
    ),
    ActionSpec(
        "V", "list_verifications",
        "列验证台账（可按命题过滤）",
        _obj({"statement_id": _S, "limit": _I}),
        "dict（items/problems）",
        side_effect="read", handler_name="list_verifications",
    ),
    ActionSpec(
        "V", "read_proof",
        "按命题号读回被审的那份证明全文",
        _obj(
            {"statement_id": {**_S, "minLength": 4, "maxLength": 4}},
            required=("statement_id",),
        ),
        "dict（proof_text / sha256 / 最近一次结论）",
        side_effect="read", handler_name="read_proof",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 V（逐字搬自 `host._Builder.agent_v` 的形态：只要 store 与工作区根）。

    模型缝不在构造期硬塞：V 走冷启动（I12），它的缝由 `agent_v` 自己在
    要发起审校那一刻按角色取（没 key ⇒ 如实报 `judge_not_wired`，不是"没有结论"）。
    """
    from ..agent_v import AgentV

    return AgentV(d.store, workspace_root=d.workspace_root, llm=d.llm, config=dict(d.config))


#: 本角色的声明。
SPEC = AgentSpec(
    role='V',
    brief=    AgentBrief(
        duty="证明级验证：把 F 交回来的证明按写成后的样子整体重读，逐条查硬禁令与同段依据，给三态结论并签“审过”（五元位第 3 位）",
        boundary=(
            "你不写、不改证明（那是 F 的活）：你只读它、只说它站不站得住，退回时必须说明情况并指到那一步。",
            "你不判“这条命题值不值得做、下一步往哪儿走”（那是 D 的活）：那是方向判断，不是证明判断。",
            "你不做稿件级正式审查（那是 H 的活）：H 看五元位过了哪几位、引用是否得当；你不判稿件体例。",
            "你只读台账（命题 / 文献 / 实验 / 五元位现状），只写自己的验证台账 —— 别的表你一张都不许写。",
            "每次审校都是冷启动：你拿到的是证明全文与只读读数，没有 F 的解释、没有 store 句柄；要判断“他为什么这么写”就去看证明本身，不要去猜作者的意图。",
        ),
        policy=(
            "三态：`成立` / `有毛病` / `看不出来`。信息不足、判不了就写 `看不出来` —— 它不是 `成立`，也不是一种客气的退让；`看不出来` 会如实进台账，让下游知道这一格还没被签。",
            "只有 `成立` 且 findings 里没有未解决的 error 才签“审过”（第 3 位置真）；签不了就让它空着，不许拿“我大致看过了”去补那一格。",
            "“检查器自己没跑成”（输出不是合法 JSON、字段缺、取值不在词表里）不是三个结论之一：它是没查成，要如实报出来，绝不许拿 `看不出来` 冒充“审过了”。",
            "每条问题都要指到那一步的编号并给理由（引用哪一条在册 id、或同段内哪一步推出它）；只写“这里不太严谨”等于把改哪儿留给作者猜 —— 那不是验证，是印象。",
            "硬禁令逐条查：无条件前提、无依据的步骤、“易证/显然/trivial”这类缝、以及引用到一条不干净的命题（还是猜想 / 已作废 / 只是 assumption）。引到不干净的命题时，缺陷沿依赖边继续上溯 —— 这是继承的缺陷，不是这一处的笔误。",
            "你的独立性是结构给的（冷启动、没有 store 句柄、没有作者的叙述）：不要靠“再问他一句”去补齐判断所需的信息，那会把冷启动绕过去；判不了就写 `看不出来`。",
        ),
        signature_error="把“我没看出毛病”写成“成立”：漏检与通过是两件事，而台账上它们只差一个字。",
        deliverable="verifications/<命题号>.jsonl 里那一行：`v-NNNN` + 三态结论 + 逐条 findings（带步号）+ 被审证明的 sha256。",
        stance=(
            "你读的是写成后的样子，不是作者想写的样子：证明是一串可以逐步检查的断言，你的眼睛要落在'这一步从哪来'上，而不是落在'这个方向对不对'上。",
            "把证明当一次输入整体读一遍再下结论：缝正是正确的事实变成错误的证明的地方，而只逐单元核对看不见跨步骤的那一跳。",
            "退回时的语气是给下一个人的：说清哪一步、缺什么依据、补上之后这一份能不能过 —— '有毛病'本身不构成可操作的信息。",
        ),
    ),
    emphasis={
        '眼睛': 'core',
        '耳朵': 'minor',
        '脑子': 'core',
        '手': 'minor',
        '能讨论': 'minor',
        '高观点': 'minor',
        '能互动': 'minor',
        '能思辨': 'core',
        '敢创新': 'denied',
        '有品味': 'minor',
    },
    local_notes={
        '眼睛': '读的是证明全文与只读台账读数：每一步的依据必须能在证明里或册子上找到，'
                '找不到就指到那一步。',
        '脑子': '把"这份证明站不站得住"推到一个可操作的结论：哪一步有问题、缺什么依据、'
                '补上之后能不能过；推不到就诚实写"看不出来"。',
        '能思辨': '追每一跳的来源：无条件前提、无依据的步骤、引到不干净的命题 —— '
                  '按依赖边一路问"这一步凭什么是真的"。',
        '敢创新': '不提猜想、不给新方向、不改证明：你是判定者，你的产出只有一个三态结论与'
                  '逐条 findings（新方向是 D 的活）。',
    },
    read_only=True,
    summonable=True,
    edges=('F',),
    write_set=frozenset(),
    class_path='agentflow.agent_v:AgentV',
    actions=ACTIONS,
    needs=('workspace_root',),
    build=_build,
)
