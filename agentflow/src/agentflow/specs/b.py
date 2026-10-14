"""角色 B 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_b.py` 只是把它再导出一次。
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
        "B", "run_once",
        "抽取一篇待处理文献的概念与关系（含引文逐字回验）",
        _obj({}), "BRunResult",
        side_effect="write_local", handler_name="run_once",
    ),

    ActionSpec(
        "B", "reprocess_once",
        "处理一条定向重抽取请求（I4）",
        _obj({}), "dict（status/result/touched_relation_ids）",
        side_effect="write_local", handler_name="reprocess_once",
    ),

    ActionSpec(
        "B", "run_reprocess",
        "连续处理重抽取请求（有界：max_requests）",
        _obj({"max_requests": {**_I, "minimum": 1}}),
        "汇总 dict", side_effect="write_local", handler_name="run_reprocess",
    ),

    ActionSpec(
        "B", "decide_structural_duplicate",
        "判定一组结构重复候选该不该合并（I5，纯判定，不写库）",
        _obj({"candidate": _OBJ, "concepts": {"type": "array", "items": _OBJ},
              "relations": {"type": "array", "items": _OBJ}},
             ("candidate",)),
        "判定 dict（merge / survivor / reason）",
        side_effect="read", handler_name="decide_structural_duplicate",
    ),

    ActionSpec(
        "B", "resolve_structural_duplicate",
        "执行合并判定（写 statements 的 status=superseded + relations 的 status；"
        "S1r 并表前那一格是 concepts 的 merged_into）",
        _obj({"candidate": _OBJ}, ("candidate",)),
        "合并结果 dict", side_effect="write_local", handler_name="resolve_structural_duplicate",
    ),

    ActionSpec(
        "B", "run",
        "连续抽取（有界：max_docs）",
        _obj({"max_docs": {**_I, "minimum": 1}}),
        "汇总 dict", side_effect="write_local", handler_name="run",
        # 外部轴 = egress：`AgentB.run` 会经由 OCR 读 PDF，而 `ocr.run` 首次构造
        # easyocr Reader 要下约 100MB 模型 ⇒ 这条链路真的触到我们不拥有的事。
        # 这是两层对账判据（`declaration_divergences`）逼出来的一格：
        # `ocr.run` 在 B3 收官时从遗留取值迁到 `declared_external="egress"`，
        # 而能力层这一格若留着默认的 `none`，第 [7] 条会在导入期报
        # "能力层低估了风险轴"（B.run <-> ocr.run）。
        # 效果轴保持 `write_local`（它写 literature/concepts/relations）。
        external="egress",
    ),

    # ---- `register_statement`（2026-10-02 加；本文件是 FC-27 禁改区，本次改动已登记基线待 2 名人审）
    #
    # 为什么必须有它（`draft/37` §44.4 的真机读数）：主控只能 `conductor.summon` 动作，
    # 而"把论文里的定理登记成 `statements` 行"原先只有工具（`table.create`）——
    # 于是即使文献登记好了，命题台账仍然建不起来（`agent_b/` 里 `statements` 一个字都没有），
    # G 就没有可引的依据、H 也没有可审的对象。B 的边界里本来就写着"命题台账三件套
    # 缺一不可"（完整假设的正文 / 逐字证明摘录 / 出处），这个动作就是那句话的执行面。
    #
    # 两根轴逐条读出（不是照抄工具层）：
    #   - 效果轴 `write_local`：实现（`AgentB.register_statement`）在一个事务里写 `statements`
    #     一行，并在写库前核 `literature`（坏引用不许进库）⇒ 写集里必须有这两张表，
    #     而 `statements` 原先不在 `WRITE_SETS["B"]` 里（本轮一并补上 ——
    #     这个动作让那句声明第一次有了实现）。
    #   - 外部轴 `none`：纯本地写库，不发 HTTP、不起子进程；`quote_verified` 的逐字比对
    #     由调用方（或 H 的复核）负责，本动作只登记与预检。
    # 2026-10-07（题 9/B，所有者授权、主控代改）：本条摘要按「留下这个动作干什么 + 关键约束、
    # 删掉参数语义的复述与设计缘由」的口径缩短（401 -> 258 字）。删掉的三类逐条记账：
    #   ① 逐参数的语义复述（「完整假设 + 逐字证明摘录 + 出处」「真实存在的 lit_id」
    #      「start 或 label」「start/label 至少一个」「如 "0000"」那半句）—— 这些细节在
    #      各格 params 的 description 里已经各写了一遍，被拒时 `agent_loop._param_table`
    #      会把整张表原样回给调用方（`render_params` 就是为这一档写的）；
    #   ② 设计缘由（`P-06` 编号，以及「如实登记一条猜想，好过把它挡在门外」这句立意）；
    #   ③ 内部机制（「第 2 位空 ⇒ 现算等级是「猜想」」）—— 那是 `evidencebits` 里
    #      等级怎么算出来的实现细节；调用方要的是结果（缺则落最低等级并进待办）。
    # 保留的是调用方在同行那句「必填 statement_full」里看不到、却会当场撞上的硬约束：
    # `origin` 的条件阶梯（external_lit / own_result 各要哪些键）、`doc_id` 的取值形态、
    # `quote_verified` 不是 true 时必须给理由。D56 那条红线由首句承担：它仍然说清这个
    # 动作是把一条命题登记进命题台账（不是只留一个动作名）。
    ActionSpec(
        "B", "register_statement",
        "把一条命题登记进命题台账（`statement_full` 是含完整假设的正文；写库前逐条硬校验，"
        "出处不在库里就整笔不写）。`origin` 决定其余必填项 —— external_lit 要 `source_lit_id`"
        "+ `page_range`；own_result 要 `doc_id`（4 位十进制）或 `line_range`。"
        "`proof_text` 可缺（缺则落最低等级并进待办）；`quote_verified` 是三态（不传 = 还没查），"
        "不是 true 时必须给 `quote_reason`；是 true 时用 `quote_mode` 说清**怎么**通过的"
        "（逐字命中 / 语义相同 —— 后者是 H 判的，B 唤起 H）",
        _obj(
            {
                "statement_full": {**_S, "minLength": 1},
                # `draft/37` §87：这几格的条件性必需此前完全没被广告，而实现在写库前逐条硬校验
                # —— T1 第 2 趟实测：`origin='own_result'` 先撞 `doc_id`/`line_range`（8 次），
                # 改对之后再撞 `proof_text`（6 次），14 次召唤全废、`statements` 始终 0 行。
                # 与 §85 的 certificate 同一条纪律：要求必须写进模型看得见的形状。
                "source_lit_id": {**_S, "description":
                                  "origin='external_lit' 必需：论文那一行的 lit_id"
                                  "（必须是 literature 表里真实存在的行，写库前会核）"},
                "proof_text": {**_S, "description":
                               "origin='own_result' 的逐字证明摘录。**可以不给**（P-06）："
                               "缺它 ⇒ 第 2 位空 ⇒ 现算等级降到「猜想」并进待办，"
                               "**不拒收** —— 那条硬要求实测一条真猜想都没挡住，"
                               "只挡住了如实登记"},
                "kind": _S,
                "label": _S,
                "statement_text": _S,
                "origin": {"type": "string", "enum": list(S.STATEMENT_ORIGINS),
                           "description":
                           "来源。**它决定还要给哪些字段**（写库前逐条硬校验）："
                           "external_lit（论文里的）⇒ 必须给 source_lit_id + page_range；"
                           "own_result（我们自己的）⇒ 必须给 doc_id 或 line_range 之一，"
                           "**并且**给 proof_text"},
                "page_range": {**_OBJ, "description":
                               "origin='external_lit' 必需：出处页码（start，或 label —— "
                               "如「全文未分页」；只给空的 start/end 等于没给）"},
                "evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS)},
                # 三态那一栏：`true`/`false` 直接给；"还没查"（None）靠不传这个参数表达
                # —— 工具层的极简 schema 子集不支持联合类型（`["boolean","null"]`
                # 会在校验期抛 `unhashable type: 'list'`，实测撞过）。不传 = None = 还没查，
                # 而那时 `quote_reason` 必填（动作里预检）。
                "quote_verified": {**_B, "description":
                                   "引文回验是否通过；不传 = 还没查（None）。2026-10-14 起"
                                   "“通过”分两档，方式写进 quote_mode：逐字命中 / 语义相同"},
                "quote_mode": {"type": "string", "enum": list(S.QUOTE_MODES),
                               "description":
                               "这条引文是**怎么**通过的（业主 2026-10-14：「回验不应该"
                               "是十分呆板的逐字验证，而是保持语义相同即可」）："
                               "verbatim＝逐字命中（`quoteverify.check_quote` 那一档，"
                               "不花模型钱，先走它）；semantic＝语义相同（交 H 判："
                               "引文与来源说同一件事即通过，允许改写/换记号/跨语言；"
                               "「结论强于引文」仍判不通过）。quote_verified=true 时应当给"},
                "quote_reason": {**_S, "description":
                                 "quote_verified 不是 true 时必需：写清哪里不一致、或者为什么还没查"},
                "derived_from": _ARR_S,
                "doc_id": {**_S, "description":
                           "origin='own_result' 时与 line_range **二者必居其一**：我方稿件那一行的 id。"
                           "**格式：4 位十进制字符串（如 \"0000\"）** —— 写成 \"doc:0000\" 会被拒"},
                "line_range": {**_OBJ, "description":
                               "origin='own_result' 时与 doc_id **二者必居其一**："
                               "start 或 label 至少一个"},
            },
            required=("statement_full",),
        ),
        "dict（stmt_id / source_lit_id / quote_verified / origin / evidence_kind / row）",
        side_effect="write_local", handler_name="register_statement",
        external="none",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 B（逐字搬自 `host._Builder.agent_b`；B 的签名里没有 `llm`、没有 `actor`）。

    extract_text 是模块级函数（抽取的唯一实现），直接传下去，不经接线层。
    """
    from ..agent_b import AgentB
    from ..extract import extract_text

    return AgentB(d.store, extractor=d.extractor, extract_text=extract_text,
                  config=dict(d.config))


#: 本角色的声明。
SPEC = AgentSpec(
    role='B',
    brief=    AgentBrief(
        duty="文献整理：把新到的文献变成概念行与关系行，每条关系都带可回验的引文",
        boundary=(
            "没有逐字引文支撑的关系不许产出。",
            "缺模型、缺正文、抽取失败都不许假装整理过。",
            "同一篇文献不要重复抽取；已有关系的重复判定交给判重口径，不要自己另立标准。",
            "命题台账（statements）三件套缺一不可：含完整假设的命题正文（statement_full）、逐字的证明摘录（proof_text）、出处（source_lit_id + page_range）。省掉假设的命题会被下游当成无条件成立 —— 那是 FC-23 在命题级的同一种病。",
            "quote_verified 是三态：true 逐字通过 / false 比对不一致 / null 还没查。不是 true 就必须写 quote_reason（哪里不一致、或者为什么还没查）。",
        ),
        policy=(
            "一次抽取的产出有上限（概念与关系各不超过提示词约定的条数）：超过上限时优先保留证据更硬的那几条，并在结论里说明被截掉了什么。",
            "把命题交给 D 之前先自己定位页与逐字摘录：你摘的那一段就是「原文长什么样」的唯一可比对文本 —— D 的初步审阅与 H 的采信都靠它。",
            "**你是审校这条链的第一环**：你写下的逐字 `quote` / `quote_verified` / `proof_text` 是下游唯一能「拿原文比一比」的东西 —— H 的采信、V 的逐行走查、以及收工门那几档（`quote_verified_rows` / `reviewed_proof_rows`）都读它；所以出处指错、`quote_verified` 把「还没查」写成 false，坏的都不是这一行，而是整条链。",
            "改写要显式标注：把文献里的证明重写成我们的形式时，另起一行并标 origin=own_result（我们的重构），不许让改写看起来像原文。",
        ),
        signature_error="把规则抽取器的产出当成模型抽取的产出。",
        deliverable="`statements` 里的概念行（`kind=\"concept\"` —— 并表之后概念不再单独一张表）与 `relations` 行；每条关系带 quote / page_range / quote_verified。",
        stance=(
            "读到与已有概念冲突的表述时，先追到原文那一句，再判是同一个概念的两种说法，还是两个概念 —— 这是你的高观点：概念行的结构比条数重要。",
            "抽取是给下游用的：你写下的定义要能让 D 直接拿去推理，而不是一句只能看着像定义的句子。",
            "发现正文里的论证本身有漏洞时，写进草稿本并公开说出去，不要悄悄按你的理解补全。",
        ),
    ),
    emphasis={
        '眼睛': 'core',
        '耳朵': 'minor',
        '脑子': 'core',
        '手': 'core',
        '能讨论': 'minor',
        '高观点': 'core',
        '能互动': 'minor',
        '能思辨': 'core',
        '敢创新': 'minor',
        '有品味': 'core',
    },
    local_notes={
        '眼睛': '读正文要读到逐字那一句：你的产出全部挂在可回验的引文上。',
        '高观点': '概念行（`statements` 里 `kind="concept"`）的结构比条数重要：别名归位、上下位分清、同一概念两种说法要合并。',
        '能思辨': '原文自身论证有漏洞时，记下来并公开说出去，不要悄悄按你的理解补全。',
        '有品味': '定义要能被下游直接拿去推理，而不是一句看着像定义的句子。',
        '脑子': '把一段正文变成可被推理的概念与关系：定义要准，边界要清。',
        '手': '写概念行与关系行；写不下（缺正文/缺模型）时如实标记，不假装整理过。',
    },
    read_only=False,
    summonable=True,
    #: 业主 2026-10-13：「允许 B 唤起 V」—— 理由是「B 需要初步检验收录的证明」。
    #: 你是审校链（B / H / V）的第一环：把外部文献里的证明**收录**进 `statements`
    #: （`origin=external_lit` + 逐字 `proof_text`）之后，那份证明要 **V 逐行走查签「审过」**
    #: 才谈得上下游采信（H 的采信规则里"E 的 proof 或 V 的签名"那一条）。
    #: 在这条边之前 B 够不着 V（只能经 D/C 或 M 转达两次），链断在哪里在台账上看不出来。
    #: 加这一条不动任何动作的权限面，只把"B 可以直接请 V 签字"说成真的。
    edges=('C', 'V'),
    write_set=frozenset((
                     # S1r 并表（2026-10-10）：`concepts` 从 `TABLES` 退役 ⇒ 从写集里摘掉。
                     # 概念行现在住 `statements`（`kind="concept"`，已经在这一格里），
                     # 留着老表名等于声明"B 可以写一张不存在的表"——权限面上的假声明。
                     'literature',
                     'relations',
                     'reprocess_requests',
                     # `draft/37` §46：`register_statement` 让"B 登记命题台账"第一次有了实现
                     # —— 而写集原先没有这张表（声明落后于边界里那句"三件套缺一不可"）。
                     'statements',
                 )),
    class_path='agentflow.agent_b:AgentB',
    actions=ACTIONS,
    needs=('extractor',),
    build=_build,
)
