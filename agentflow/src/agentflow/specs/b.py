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
    # 为什么必须有它（`draft/37` §44.4 的真机读数）：主控只能 `conductor.summon` 动作，而"把论文里的
    # 定理登记成 `statements` 行"原先只有工具（`table.create`）⇒ 命题台账建不起来，G 没有可引的依据、
    # H 也没有可审的对象；B 的边界里写的"命题台账三件套缺一不可"就是这个动作的执行面。
    # 两根轴：效果轴 `write_local`（一个事务写 `statements` 一行，写库前核 `literature` ⇒ 写集必须含
    # 这两张表，`statements` 原先不在 `WRITE_SETS["B"]` 里，本轮补上）；外部轴 `none`（纯本地写库）。
    # 2026-10-07（题 9/B）摘要缩短 401 → 258 字，删掉三类：逐参数语义复述（各格 params 已各写一遍）、
    # 设计缘由（`P-06` 编号与"如实登记一条猜想好过挡在门外"）、内部机制（第 2 位空 ⇒ 等级是「猜想」）；
    # 保留调用方会当场撞上的硬约束：`origin` 条件阶梯、`doc_id` 形态、`quote_verified` 非 true 要理由。
    ActionSpec(
        "B", "register_statement",
        "把一条命题登记进命题台账（`statement_full` 是含完整假设的正文；写库前逐条硬校验，"
        "出处不在库里就整笔不写）。`origin` 决定其余必填项 —— external_lit 要 `source_lit_id`"
        "+ `page_range`；own_result 要 `doc_id`（六位十进制编号）或 `line_range`。"
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
                "proofs": {"type": "array", "items": {"type": "object"}},
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
                "evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS),
                                  "description":
                                  "证据强度。**有 `proof_text` 且 V 在 "
                                  "`verifications/<命题号>.jsonl` 里签了「成立」（且签的就是现行"
                                  "这一版正文）⇒ 就该写 `proof_review`** —— 定义只在 "
                                  "`schema.EVIDENCE_KINDS`，写入期按它核，不多要别的字段；"
                                  "只有**真没有那一签**时才退 `heuristic` / `cross_check`。"
                                  "两条出口：① 先请 V 走查（`V.verify_proof`）签完再写 "
                                  "`proof_review`；② 如实写弱档，并在 `quote_reason` 里写清"
                                  "「还没有 V 的签名」"},
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
                # D1（2026-10-22）：这两格是"证据"的入口。此前动作面没有它们，而
                # `additionalProperties=false` ⇒ H 判出来的 span 与调用指纹连传都传不进来
                # （模型猜参数名会被判 invalid_params），语义档因此结构性不可达；
                # 逐字档则只能自报"通过"而说不出核的是哪一段。
                "quote_span": {**_S, "description":
                               "引文在来源里命中哪一段。逐字档的口径是 `p{页}:norm[起:止]`："
                               "页号从 1 起，起止是该页经 `textutil.normalize_for_quote` "
                               "归一化之后的字符偏移（含头不含尾）；语义档这一栏是 H 判时"
                               "对着的那一段来源原文。给了 `source_lit_id` 且那一篇的全文在库时，"
                               "B 会拿它去真比对并把算出来的区间写实（交接来的区间只是线索，"
                               "落盘的是重算出来的那个）；**说 `quote_verified=true` 而这一次"
                               "核不出区间 ⇒ 这一笔降成 unknown**（说不出核了哪一段就不算通过）"},
                "quote_call_sha256": {**_S, "description":
                                      "**只有 `quote_mode=semantic` 这一档填**：H 的 "
                                      "`judge_quote_semantics` 回执里 `call.prompt_sha256`"
                                      "（那次语义判定的调用指纹）。逐字档不填 —— 它是纯文本"
                                      "比对，没有模型调用（不是忘了记）；语义档缺它 ⇒ 写库前"
                                      "当场拒（说不出是哪一次判的，就不算语义通过）"},
                "derived_from": _ARR_S,
                "doc_id": {**_S, "description":
                           "origin='own_result' 时与 line_range **二者必居其一**：我方稿件那一行的 id。"
                           f"**格式：{S.ID_DIGITS} 位十进制字符串（如 \"{S.format_id(0)}\"；旧数据里的 4 位号仍可读）** —— 写成 \"doc:0000\" 会被拒"},
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


#: 形式化那条通道的完整口径（六步，正向写成一条有入口的流程）。
#:
#: 为什么单独拎成常量：关掉 Lean 时要用同一份字符串做改写表的左边（见本文件末尾的
#: `NO_LEAN_REPLACEMENTS`）。手抄两份必然漂移，而漂移的表现是"关档那一档还点着一个
#: 不存在的角色"——那正是 `tests/test_l_is_isolated_when_lean_is_off.py` 会红的那一格。
#:
#: 六步与各自的落点（业主 2026-10-24 口径：是否形式化由用户指定，需有许可再做）：
#: ① 许可 = 用户指定某一条需要形式化验证；② M 把这件要求交给 B；③ B 逐条派 L
#: （`B → L` 是唯一入边，一条才做一条），给命题 + 证明链 + 库里已被核过的条目；
#: ④ 要回检查器原话 + 真实退出码 + 三态；⑤ `unknown` 是没查成 ⇒ 补齐材料再派一次；
#: ⑥ 困难回到 B ⇒ B 改证明 ⇒ 重新拿 V 签；缺陷严重 ⇒ B 通知 D 开展研究。
PROOF_CHANNEL = (
    "**形式化那条通道的六步，每一步的落点都在你手上**："
    "① 许可只有一个来源 —— 用户指定「这一条需要形式化验证」；没人指定就不做这件事"
    "（在台账上照样写「未核到」，不排进流水线）。"
    "② 许可之后 M 会把这件要求交给你。"
    "③ 你的动作是逐条派 L（`B → L` 是唯一的入边，一条才做一条），派它时给三样："
    "命题目录里那一行（`stmt_id`，它自带 `statement_full` 与 `proof_text`）、要验的证明链"
    "（`proof_text` 逐字；同一条有好几份证明时给 `proof_no`）、以及库里那条已被核过的依赖"
    "（`statements` 里同一声明名的那几行）。"
    "④ 要回三样：检查器原话（`verifier_output`）、真实退出码（`exit_code`）、三态结论"
    "（`verified` / `failed` / `unknown`）—— 只写「通过」而没这三样的不算数。"
    "⑤ 三态是 `unknown` 时那是**没查成**（缺材料 / 超时 / 自检不过）：补齐它点名缺的那一段"
    "（一条假设、那一步的依据、那一行 import）再派一次，同一份材料不要连撞两次。"
    "⑥ L 把「失败或对不上」报回来时按三步处置：先改证明（同一份内容再交一次 "
    "`own.register_statement`，覆盖 canonical、旧正文进 `proof_history`）⇒ 再请 V 重签"
    "（`V.verify_proof`，签的是新正文）⇒ 若判断缺陷在证明路线本身（不是补一块就够），"
    "用 `escalate_proof_research(severity=\"research\")` 把这条难点交给 D 开展研究；"
    "普通缺陷不进 D 的收件箱。汇报里点名命题号、失败类型（漏一步 / 缺假设 / 只能 sorry / "
    "与台账对不上）、第几步、建议补什么 —— 这三步与这一格靠的就是它。"
)

#: 关掉 Lean 时，上面那一段换成这一份（这一档做不出形式化）。
#:
#: 左边与右边都是常量：左边逐字出现在开档的渲染里（`tests/test_lean_switch.py` 的反真空
#: 守着这一点），右边一个字都不许提 Lean（同一条判据的第二半）。
PROOF_CHANNEL_NO_LEAN = (
    "**形式化那一档本会话产不出来（系统做不了）**：证明的判读走逐行审阅 —— 证明过程逐字进 "
    "`statements` 的 `proof_text`（含假设、每一步的依据、你接不上的那一步），再请 V 用 "
    "`verify.verify_proof` 逐行走查，结论进 `verifications` 表（签发新的那一档要 V 的「成立」）。"
    "用户指定「这一条需要形式化验证」时，如实回「本会话形式化已关闭」这一读数，"
    "并把这条要求连同缺的那几样记进交付。"
)


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
            "一次抽取的产出有上限（概念与关系各不超过提示词约定的条数）：超过上限时优先保留证据更硬的那几条，并在结论里说明被截掉了"
            "什么。关系的价值在信息量：每条要能回答「这两个概念是什么关系、凭哪一句原文（`quote`）」，`kind` 要是说得出的关系名；"
            "「相关」这类空边不许产出；归并同义说法要说清凭什么判它们同义。",
            "把命题交给 D 之前先自己定位页与逐字摘录：你摘的那一段就是「原文长什么样」的唯一可比对文本 —— D 的初步审阅与 H 的采信"
            "都靠它。",
            "**你是审校这条链的第一环**：你写下的逐字 `quote` / `quote_verified` / `proof_text` 是下游唯一能「拿原文比一比」的东西 "
            "—— H 的采信、V 的逐行走查、以及收工门那几档（`quote_verified_rows` / `reviewed_proof_rows`）都读它；所以出处指错、"
            "`quote_verified` 把「还没查」写成 false，坏的都不是这一行，而是整条链。",
            "**证据档按「有什么凭据」定，不按「怕不怕」定**（2026-10-19 晚）：一条命题的 `proof_text` 非空、且 V 在 "
            "`verifications/<命题号>.jsonl` 里**最近那一签**是「成立」（`proof_sha256` 与现行正文相符）⇒ 它的 "
            "`evidence_kind` **就是** `proof_review`（定义逐字在 `schema.EVIDENCE_KINDS`，写入期按它当场核）。"
            "**只有真没有那一签时**才退到 `heuristic` / `cross_check` —— 退档不是错，但它是安全方向的偷懒：一条够格的强结果"
            "写成弱档，论文的强度声明会长期虚低，而 `verify` 会报 `weaker_than_evidence`（warning）把它点出来。两条出口写清："
            "① 请 V 走查（`V.verify_proof`，产物就是 `verifications/<命题号>.jsonl` 那一行）签完再写 `proof_review`；"
            "② 如实降档，并在 `quote_reason` 里写「还没有 V 的签名」—— 别把'拿不准'写成默认值。"
            "改命题的档位或正文：把同一份内容**再交一次** `own.register_statement`；`table.update` 那类通用写口对 "
            "statements 已被封，撞了只会白跑一趟。",
            # 2026-10-20 业主裁定（逐字："B 负责定理及证明入库时可让 V 审核签字，这是对文献侧引入的内容
            # 需要看的，因为我们自己经 F 产出的证明天生带 V 签字"）：V 的签字有两个入口，B 只管文献那一侧。
            "**入库的是文献侧引入的定理/证明（不是 F 产的）⇒ 派 V 审核签字，签了才写 `proof_review`**；"
            "F 产的证明天生带 V 签字，不要重复要求签。",
            # 2026-10-22 晚（业主的最终协作面裁定）：「可向 B 汇报形式化过程中遇到的困难、
            # 要求 B 完善证明并重新得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点。」
            # 2026-10-24（业主口径：是否形式化由用户指定，需有许可再做，一条才做一条）：
            # 这一段此前刻意不写出 L 那个字母（那时 `specs/b.py` 没有关档改写表，写死一个
            # 角色名会让"关着时非 L 角色 0 处 L"那条判据当场红）。现在这一段是整条通道的
            # 唯一真身（许可 → 派 L → 给什么 → 要回什么 → unknown 怎么办 → 困难与升级），
            # 只写"形式化那一岗"读的人不知道派谁 ⇒ 名字必须写出来，关档那一档由本文件末尾
            # 那张 `NO_LEAN_REPLACEMENTS` 把整段换成"这一档做不了"。
            PROOF_CHANNEL,
            "改写要显式标注：把文献里的证明重写成我们的形式时，另起一行并标 origin=own_result（我们的重构），不许让改写看起来像原文。",
            # 2026-10-23 业主裁定（逐字要点）：「秘书不再因"太平凡"拦收录，只是加一个档位叫 T0
            # （和 T1 到 T4 是一个性质），T0 叫基础定理或初步结论」。于是这一格的两句话换掉：
            # 「不收」改成「落 T0」、「当场拦下」改成「降为 T0，照旧收下」。
            # 2026-10-24 业主裁定（逐字：「B侧收录为什么还是有"是否太平凡"这栏？不是已经被 T0 到 T4
            # 取代了吗？」）：措辞收口 —— 这一格只用「非平凡性档位 T0–T4」＋「未判」两套说法，
            # 不再出现那种像"收不收"的措辞（它已经改成"判哪一档"）。对账锚点「入库前你的秘书」
            # 保留（`tests/test_secretary_prompt_alignment.py` 认它），第三处随工具结果的形态一起换
            # （`statement_too_trivial` 这个拒绝码不再产生，工具结果里现在挂的是 `tier=T0`…`tier=T4`
            # 或「未判」）。
            "**收录要有审美，也要判档位**：判到最低那一档就是 T0（基础定理或初步结论）——"
            "**这不是拒绝，是分档**。判不了的写「未判」并给出理由；"
            "档位只有 T0–T4 这五档 ＋「未判」，没有第六种说法。"
            "**判档位要用的素材**：判据是「后面哪一步会用到它」与「它比已知的那一条强在哪」——"
            "两条都答不上来就是最低那一档（T0），不是拒收。"
            "**入库前你的秘书会替你把这一关**：它给出档位（工具结果里带 `tier=T0`…`tier=T4`，"
            "或「未判」+ 理由），照旧收录、不再拒收 —— 但它给的「缺哪一条判据」就是你升档的路："
            "补齐之后重交，档位才往上走。"
            "它判`判不了`/`没查成`时这一格没有档位（那是「这一格没查成」，不是「合格」）。",
            # 2026-10-24 业主裁定（D-54，逐字要点）：「Sylow 第一定理，会有几种证明语言，
            # 会有不同的依赖面，然后后续让 C 从不同的依赖面起点追依赖链就能完整显示不同证明路径」
            # +「B 侧应该已经做过对同一定理收录多种证明和所对依赖面了」。机制早就在
            # （`proofs` / `used_by="stmt:<号>#pN"` / `path_group` / `reviewed_by_proof` /
            # 对应表的 `proof_no`），缺的是"用户要几种证明时该落成什么形状"的口径，
            # 所以这一条是正向政策：写清形状，也写一句反向判据（别拆成几条命题）。
            "**同一条定理的多种证明只占一条 stmt，不占多条命题**：用户要「几种证明语言 / 几条独立"
            "路径」时，目标是同一条命题的 `proof_no` 1..N，不是 N 条独立命题。登记时一次交清："
            "`own.register_statement` 的 `proofs=[{proof_no: 1..N, text: …}]`（`#p1` 落行上的 "
            "`proof_text`，`#p2` 起落同一行的 `proofs` 清单）。**每条证明各自要 V 的签**："
            "`bits.evidence.reviewed_by_proof` 按 `proof_no` 逐份记（`{\"1\": true, \"2\": false}`），"
            "一份签了不代表另一份签了，也不许拿一份的签替另一份背书。每条证明用到的依赖按 "
            "`used_by=\"stmt:<命题号>#pN\"` ＋ `path_group` 标明它属于第几条证明（`deps` 两维："
            "外层 = 可选路径、内层 = 一条路径上的步骤），C 才能按不同的依赖面追出不同的证明路径。"
            "论文对应表里同一条命题占多行、每行各带 `proof_no`。"
            "**反向判据：不要把同一条定理拆成多条命题** —— 表述不同（极大 p-子群版 / |G|=p^a·m 版 / "
            "归纳版）不等于不同命题；拆开之后 `proof_no` 恒为 1、`path_group` 只剩一组，"
            "多证明机制一次都不会被触发。判重先问「这是不是同一条」，再问「这是它的第几份证明」。",
            "**这张收录表就是我们版的「综述」**：所以不产出「综述」这一件产物、不给 `documents` 另开一类；A 交来的文献由你把定理与"
            "证明收进 `statements`（`proof_text` + 逐字出处），**收录比转述强**：综述里的一句话查不到行，收录表里每一行都能。",
            # 2026-10-22 业主裁定 B-1（逐字：「若出现被指认无可信度的文献，或待审核的文献，
            # 则不可当引文入库，只可当研究参考」）：只在提示词里提醒。
            # 不做 stage 强制、不做出处闸、不改 schema —— 这一格是提示词，不是判据；
            # 落库路径（lit_candidates / literature）一个字都没动。
            "被指认无可信度、或还在待审核的文献：不可当引文入库，只可当研究参考 —— 不拿它的原话当 "
            "`quote` / `quote_reason` 的凭据，也不凭它登记关系行；它只能落在「研究参考 / 待核」那一栏，"
            "要引用就先换一篇可核的来源。",
            # 2026-10-24 业主裁定（逐字：「注意不只是M侧改，其它所有智能体都要知道有监控一层
            # 子代理的能力」）：只写这一实现里真有的两件 —— `trace.children` 与
            # `conductor.escalate` 都在本角色的工具面上。判据：
            # tests/test_every_role_knows_it_can_watch_its_children.py。
            "**你能监控自己的直接下级，但只看得见一层**：`trace.children`（不传参数就是看你这一趟名下）"
            "逐个给子任务的状态、被拒次数与类目（`refusals`）、最近几步（`recent_steps`）、产出是否真落盘"
            "（`products`）、最近一次交接（`last_handoff`）；传 `depth` 大于 1 也只给一层。要看更深（例如你想看"
            "「下级的下级的下级」）就用 `conductor.escalate` 向 M 请求 —— M 会把对你的指导连同各级父的通知一起"
            "发下来：你看到的是指导，不是原始全树数据。",
        ),
        signature_error="把规则抽取器的产出当成模型抽取的产出。",
        deliverable="`statements` 里的概念行（`kind=\"concept\"` —— 并表之后概念不再单独一张表）与 `relations` 行；每条关系带 quote / page_range / quote_verified。",
        stance=(
            "读到与已有概念冲突的表述时，先追到原文那一句，再判是同一个概念的两种说法，还是两个概念 —— 这是你的高观点：概念行的结构比条数重要。",
            "抽取是给下游用的：你写下的定义要能让 D 直接拿去推理，而不是一句只能看着像定义的句子。",
            "发现正文里的论证本身有漏洞时，写进草稿本并公开说出去，不要悄悄按你的理解补全。",
            "提交命题入库时要写清**判档位要用的素材**（后面哪一步会用到它、它比已知的那条强在哪、"
            "它的证明是体量大还是用了跨领域工具）：这是入库前你的秘书判非平凡性档位"
            "（T0–T4；T0 = 基础定理或初步结论）时的输入 —— 素材答不上来时它只能落最低那一档（T0）"
            "或写「未判」＋理由；你只给素材，不下档位结论，档位判错了由秘书那一趟的 basis 负责。",
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
    #: 你是审校链（B / H / V）的第一环：把外部文献里的证明「收录」进 `statements`
    #: （`origin=external_lit` + 逐字 `proof_text`）之后，那份证明要 「V 逐行走查签「审过」」
    #: 才谈得上下游采信（H 的采信规则里"E 的 proof 或 V 的签名"那一条）。
    #: 在这条边之前 B 够不着 V（只能经 D/C 或 M 转达两次），链断在哪里在台账上看不出来。
    #: 加这一条不动任何动作的权限面，只把"B 可以直接请 V 签字"说成真的。
    #: 业主 2026-10-14：「允许 B 和 H 协作，B 唤起 H」—— 理由是那条引文回验的口径改了：
    #: 「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」。
    #: 分工：逐字那一档 B 自己走（`quoteverify.check_quote`，不花模型钱，先走它）；
    #: 逐字不中而「语义相同」的（作者自己改写、换记号、跨语言的引文）由 「H 判」，
    #: B 拿 H 的判定回填 `quote_verified` + `quote_mode="semantic"`
    #: （H 只读、且它的落库代理被钉死在 review_findings/documents 上 ⇒ "判"与"落"分居两处）。
    #: 在这条边之前 B 够不着 H，于是那些语义相同的引文只能一直挂着 `quote_verified=null`。
    #:
    #: 2026-10-22 晚（业主的最终协作面裁定，逐字）：「L 的协作面特别简单：只有 B 可以派 L，
    #: L 允许派 C 来梳理证明链，消费 B 的定理证明库，可向 B 汇报形式化过程中遇到的困难、
    #: 要求 B 完善证明并重新得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点。」
    #: 这一格按那句话加两条边，各自只承担那一句里的一件事：
    #: - `L`：唯一入口。B 派 L 去做形式化（`L.formalize` / `L.check_formal` / `L.record`），
    #:   L 消费的就是 B 登记的 `statements` 那一行（`statement_full` + `proof_text`）。
    #:   B 是 `statements` 的唯一登记方，所以"只有 B 可以派 L"在结构上等于
    #:   "L 形式化的东西一定出自 B 的库"。别的角色一律不许有到 L 的边
    #:   （判据：`tests/test_l_collab_surface_is_exactly_this.py` 逐角色断言）；
    #: - `D`：缺陷严重时的升级出口。B 收到 L 的汇报后自己改证明（覆盖 canonical，
    #:   旧正文进 `proof_history`），再请 V 重签（`B → V` 这条既有边）—— 若 B 判断缺陷
    #:   在证明路线本身（`severity="research"`），这一条边是唯一能把"这个证明难点该做
    #:   研究了"交给 D 的路（实现在 `agent_b/proof_research.py`，落点是 D 的收件箱，
    #:   标题前缀 `研究请求`）。
    #: 这两条之外没有放宽任何别的边：B 不会因此够得到 A / E / F / G，
    #: 也不替 D 做研究判断（它只交一条带读数的问题，研究怎么做归 D）。
    edges=('C', 'D', 'H', 'L', 'V'),
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


#: 关掉 Lean 之后，B 那一段「形式化那条通道」改写成另一份（这一档做不出形式化）。
#:
#: 为什么 B 也要有一张表：`PROOF_CHANNEL` 是整条通道的唯一真身，它必须写出派谁
#: （只写"形式化那一岗"读的人不知道派谁）；而关掉那一档 L 不是这一档的角色，
#: 非 L 角色的渲染里不许出现这个角色名（`tests/test_l_is_isolated_when_lean_is_off.py`）。
#: 左边与右边都取自本文件的常量（`PROOF_CHANNEL` / `PROOF_CHANNEL_NO_LEAN`）——
#: 不手抄，于是"改了声明忘了改改写表"这类静默失效在结构上不会发生。
NO_LEAN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (PROOF_CHANNEL, PROOF_CHANNEL_NO_LEAN),
)
