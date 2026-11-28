# -*- coding: utf-8 -*-
"""角色 V（验证者）的声明（F-02）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_v` 只是把它实现出来。所以它进了 `.noai-paths`（改它等于改权限面
⇒ 需要 2 名人审），判据见 `tests/test_agent_spec_reconciliation.py` 与
`tests/test_capabilities_two_layer.py`。

## V 是什么

H 是稿件级正式审查（五元位第 5 位）；V 是证明级验证（五元位第 3 位）。
把"证明级"塞进 H 会把 H 的语义撑宽（一个人的两个判断面混在一起，读数也就分不开了），
所以它是独立角色。它做三件事（用户点名的 I12/I10/I17）：

1. I12 冷启动：每次审校开新会话，只给对象（证明全文）+ 只读查询面的读数 ——
   不给 F 的叙述、不给 store 句柄。独立性是结构性质，不是"约定只读"。
2. I10 硬禁令 + 同段依据：逐条查（无条件前提 / 无依据的步骤 / "易证、显然"这类缝 /
   引用的命题是否干净），每条问题指到那一步。
3. I17 整篇重读：把证明按写成后的样子当一次输入整体读，不只逐单元核对。

## 权限面：只读 + 自己维护的那张台账

`read_only=True`、`write_set=frozenset()`：V 不写任何**数据表**。它写的是**自己维护的那张表**
`verifications/<命题号>.jsonl`（追加式，与手稿同一形态，不新增 `schema.TABLES`）与它颁的签
（`out/vsigns/<正文 sha>.json`、收方秘书落回送审手稿的签块）—— 三者都是工作区写，所以
`verify_proof` 这个动作**据实**声明 `side_effect="write_local"`。
`capabilities.WRITE_SETS` 描述的是"会写哪几张**数据表**"，所以那里是空集；V 拿得到那件写工具走的是
`tools/base.py::READONLY_CALL_EXCEPTIONS["V"]` 的逐条例外，而 `tools.READ_ONLY_ROLES` 里的 `"V"`
与 `for_role` 的结构性剥离继续保证**别人的**写工具一件都进不了它的面 —— 只读约束的是
"不能改别人的东西"，不是"不能有副作用"。

## 边：入边 `B` / `E` / `F`，出边为空

V 只被这三方唤起：F 交证明、E 交穷举证据、B 交文献侧引入的证明；它自己不派任何人
（`edges=()`，出边为空）。签完的回执沿「谁送审、回给谁」走，收录那一跳由 D（或 F）
派 B，不是 V 派 B。

## 引用核实（一句政策）

V 侧审查也要核实 F 报告的引用（F 的引用可能非逐字，需要 V 自行判断）。判据不是字面
像不像（正常写证明就不会逐字），而是「proof_review 级及以上才可引用」—— 按**等级是
唯一的轴**，它的口径就是等级 `pre_theorem` 及以上。落法（实现只有一处）：

- V 的审查材料里必须同时有 F 对每条被引命题的说法（`dependencies` 那一行）
  与被引命题的正文摘要 —— 只给编号，V 核不出"F 是不是这么用的"；
- 逐条一档结论 `consistent` / `weaker` / `stronger` / `unrelated` / `inadmissible` /
  `unknown`，读数是台账里的 `citation_checks`（`{stmt_id, verdict, quote_verbatim, note,
  in_material}`：`quote_verbatim` 只作信息、不参与判定，`in_material` 说这一条引用在不在材料内）；
- `stronger` / `unrelated` / `inadmissible` 三档 ⇒ 这一份改判 `有毛病`、不签发；
  `unknown` 是「没查成」⇒ 同样不签发（两者理由不同，都点名哪一条、差在哪）；
  `weaker` 可以签，但读数里点名"只用到了弱形式"；
- 等级闸是事实、不是判断：被引命题的等级低于 `pre_theorem`（含空档）一律 `inadmissible`，
  允许集合从 `evidencebits.GRADES` 现算（`verifications.citation_grade_admissible`）；
  `evidence_kind` 只是历史列，判定面不读它。

为什么这段写在模块 docstring 而不是 `policy` 元组里：`policy` 会渲染进 V 的提示词、
挂进 `tests/test_agent_prompts.py` 的冻结摘要与 `PROMPT_VERSION` 那一轴；本文件这一格
留声明侧的同一条政策，渲染面那一句落在 V 的真实入口 `verifications.cold_start_prompt`
（它才是 V 每次审校读到的提示词），两处说的是同一条口径。

## 发签权的边界（明文例外）

「V 只产审稿意见；发签的计数与门槛由框架从台账现数（`sign_counting`），秘书只执行落签」
只约束在册档；这条例外约束的是
**发签判定**（`decide_sign_issuance` 的 `issue` 那一路：它不再自己数次数、也不再问模型），
**不是「要不要轴」**。

未在册档（`reports/f-proof-*.md` / `reports/e-proof-*.md` / `reports/b-proof-*.md`
那一支，`agent_v/core.py::_review_unregistered_prose` 与
`_review_unregistered_exhaustion`）常常没有「收方秘书在场」这个前提：F / E 的稿在被
收方接手之前就要签，强行要求秘书判「发不发」会把这一档变成死路。所以：

- **发签**：未在册散文支按 `need` 转 clean（F / B 是 3）、穷举档按
  `EXHAUSTION_SIGN_STREAK_NEED` 次机械会审 clean（2026-11-17 起是 1：实验侧报告不承重、
  承重的是程序）即由 V 颁发 —— `vsigns.issue`
  写 `out/vsigns/<正文 sha>.json`、把信封交给收方；两支都不许有 `issue` 那一路
  （都不调 `decide_sign_issuance`，那正是这条例外约束的东西）；
- **轴（clean / fault）该谁给**：散文支每一转由 V 的秘书做语义判定
  （`_judge_v_reply` → `Secretary.judge_v_reply`，`source=secretary:v_reply_defect`）；
  穷举支没有 V 的散文回复，轴由机械会审自己的两态读数给（`exhaustionreport.review`，
  `source=exhaustion_report`），不问秘书。V 的判词只是陈述，轴不看它的字面；
- 手稿签块仍只由收方秘书落（`Secretary.land_unregistered_sign`），V 在这个档里
  一处签写口都没有 —— 一句话：未在册档「V 颁发、落块仍由收方秘书做」；
- 这是明文例外，不是暗中放宽：判据
  `tests/test_unregistered_issuance_is_an_explicit_exception.py` 同时钉住
  「这一段在」与「未在册两支不调发签判定」，并用正控钉住「散文支必须问秘书要轴、
  穷举支必须不问」。谁把发签判定插进未在册档，或把散文支的轴改回 V 自己给，
  那一条判据会红。
"""

from __future__ import annotations

from typing import Any

from .. import schema as S
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
#: 三件动作里两件是 `read`，`verify_proof` 据实是 `write_local`：
#: 它写 V **自己维护的那张台账** `verifications/<命题号>.jsonl`、未在册档的签信封
#: `out/vsigns/<正文 sha>.json`，并让收方秘书把签块盖回送审的那份手稿。
#: 不能声明 `read` 的理由：那是把"写不写数据表"与"写不写工作区"折成了同一件事；
#: `side_effect` 的轴定义是"数据表 / 工作区"（`tools/base.py::EFFECT`），所以真值就是
#: `write_local`。
#: 它仍留在 V 的工具面上，走的是 `tools/base.py::READONLY_CALL_EXCEPTIONS["V"]`
#: 那条逐条例外（不是靠把副作用写成 `read` 换可达性）。这条两层声明必须同名同值：
#: `capabilities.assert_capabilities` 第 [7] 条把"工具说写、能力说读"判成 error。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "V", "verify_proof",
        "把一份证明按写成后的样子整体重读：两态结论 + 每条问题指到步号，"
        "并写 verifications/<命题号>.jsonl（在册命题必须带证明稿 `proof_manuscript`（proof manuscript），"
        "签落在稿上）",
        _obj(
            {
                # 长度上界从「唯一那处宽度」取（`schema.ID_DIGITS`）；下界 4 是
                # 「旧数据的宽度」（`LEGACY_ID_PATTERN`），因为盘上的老命题号仍然可读。
                # 硬编码成 `minLength=4, maxLength=4` 会在真机上直接现形：
                # `V.verify_proof 的参数不合法：statement_id. 长度最多 4`（送审被拒、
                # 一次真跑白等一轮）。
                "statement_id": {**_S, "minLength": 4, "maxLength": S.ID_DIGITS},
                # `proof_text` 不是必填 —— 三处口径不能互相矛盾
                # （本行 required、工具面 description、实现）。真身在工具层
                # （`tools/verify_tools.py`，`validate_params` 读的那一份），这里跟着它
                # 说同一句话：只给命题号即可，正文从 statements 里取。两层根级 required
                # 必须逐字相同，判据是 `assert_capabilities()` 第 [9] 条与第 [9c] 条
                # （`_PARAMS_DERIVED_FROM_TOOL` 里登记了 ("V", "verify_proof")）。
                #
                # 在册那一档必须给 `proof_manuscript`（内联正文不能单独过审）。
                # 它仍是**条件**必填（有 statement_id 才要），根级 required 放不下"如果"，
                # 所以这里仍不是必填项；拒绝由实现（`_manuscript_gate`）出，
                # 码 `proof_text_needs_a_manuscript`。
                "proof_text": _S,
                # 这一格是**历史坐标（只读兼容）**：签的身份是正文 sha + 稿路径
                # （`proof_manuscript`），不是"第几条证明"；老盘按 `-pN` 寻址的那一档
                # 仍可传它，新送审不必传。
                # 下界 1 的真身在工具层（`verify.verify_proof` 的 `proof_no.minimum=1`，
                # 它是 `validate_params` 真正读的那一份）；只写 `_I` ⇒ 派活面放行
                # `proof_no=0`，而工具层必然拒收。判据：
                # `capabilities.assert_capabilities()` 第 [9c] 条（`_PARAMS_DERIVED_FROM_TOOL`）。
                "proof_no": {**_I, "minimum": 1,
                             "description": "历史坐标（只读兼容）：老盘按 `-pN` 寻址时用；"
                                            "新签的身份是正文 sha + 稿路径，不靠这个号"},
                # 只读读数（命题现状 / 文献与实验台账摘要）由调用方取好传进来：
                # 传字符串而不是传 store，是为了让"它能碰什么"在接口上就固定下来
                # （I12 的结构形态，见 `verifications.cold_start_prompt`）。
                "readonly_facts": _S,
                # 给一条"还没在册"的入口 —— 传 F 那一份证明手稿的
                # 工作区相对路径（`reports/f-proof-*.md`），V 就读稿审、三转干净就把签块
                # 盖回**那一份手稿**（`vsigns.write_manuscript_sign`）。此时 `statement_id`
                # 不给（空串 = 还没在册），落点不是 `verifications/<号>.jsonl`。
                # 为什么不是新动作：V 做的还是同一件事（重读一份证明、给两态结论），
                # 变的只是对象从"在册命题的正文"扩到"手稿里的那一段正文"。
                #
                # 在册那一档**必须**给这一格 —— 签块 / `## 依赖` 段 / 按号寻址这三样
                # 只在文件上；只给内联正文的在册送审由实现受控拒绝
                # （`proof_text_needs_a_manuscript`）。
                "proof_manuscript": _S,
            },
            # `statement_id` 不是唯一的入口键 —— 未在册那一档不给号，
            # 给 `proof_manuscript`。两键至少给一个，缺哪个由实现按 `checked=False`
            # 如实拒（`no_proof_text` / `statement_missing`），不在这里做二选一约束
            # （`_obj` 的 required 是"根级必填"，没有"二选一"的位置）。
            required=(),
        ),
        "一行验证台账（含 v-NNNN / verdict / findings / proof_sha256）",
        side_effect="write_local", handler_name="verify_proof",
    ),
    ActionSpec(
        "V", "list_verifications",
        "列验证台账（可按命题过滤）",
        # `limit` 的下界 0 与工具层（`verify.list_verifications`）同界：负数没有语义，
        # 工具层会拒收 ⇒ 动作面必须说同一句话（判据同上）。
        _obj({"statement_id": _S, "limit": {**_I, "minimum": 0}}),
        "dict（items/problems）",
        side_effect="read", handler_name="list_verifications",
    ),
    ActionSpec(
        "V", "read_proof",
        "按命题号读回被审的那份证明全文",
        _obj(
            # 同 `verify_proof`：上界取自 `S.ID_DIGITS`（不是硬编码 4）。
            {"statement_id": {**_S, "minLength": 4, "maxLength": S.ID_DIGITS}},
            required=("statement_id",),
        ),
        "dict（proof_text / sha256 / 最近一次结论）",
        side_effect="read", handler_name="read_proof",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 V（只要 store 与工作区根）。

    模型缝不在构造期硬塞：V 走冷启动（I12），它的缝由 `agent_v` 自己在
    要发起审校那一刻按角色取（没 key ⇒ 如实报 `judge_not_wired`，不是"没有结论"）。
    """
    from ..agent_v import AgentV

    return AgentV(d.store, workspace_root=d.workspace_root, llm=d.llm, config=dict(d.config))


#: 本角色的声明。
SPEC = AgentSpec(
    role='V',
    brief=    AgentBrief(
        duty="证明级验证：把交进来的证明按写成后的样子整体重读，逐条查硬禁令与同段依据，给两态结论；**发签的判定与写盘是两件事**：**签只由你（V 这一侧）颁发**（未在册档写 `out/vsigns/<被审正文的 sha>.json`，把信封交给收方秘书）；**在册档够不够门槛由框架按这一趟的台账现数，落签由收方秘书**（手稿签块与五元位第 3 位都不在你手上）",
        boundary=(
            "你由 F / E / B 唤起：F 把写成的证明交给你复核；E 把穷举证据（程序 + ②③ 报告）交给你会审；B 在把一条自产结果登记成 proof 之前要你这一签。你不写、不改证明（那是 F 的活）：你只读它、只说它站不站得住，退回时必须说明情况并指到那一步（F 按你给的那一条补步骤，而不是重写整篇）。",
            "你不判“这条命题值不值得做、下一步往哪儿走”（那是 D 的活）：那是方向判断，不是证明判断。",
            "你不做稿件级正式审查（那是 H 的活）：H 看五元位过了哪几位、引用是否得当；你不判稿件体例。",
            # V 面有 write_local（`clock.*` / `conductor.ack` / `conductor.post_task`），
            # 按「工具面全量只读」说就不成立。只读的意思是「对其它智能体的产出只读」——
            # 别人的台账一张都不写，自己侧的产物照写。
            "你**对其它智能体的产出只读**：别人的命题 / 文献 / 实验 / 五元位台账，你一张表都不写、一个字节都不改。"
            "**你自己侧的产物**是：`verifications/<命题号>.jsonl` 那一行（一行一次审校；三件动作里 "
            "`verify_proof` 声明 `write_local`，`list_verifications` / `read_proof` 声明 `read`）"
            "与签的侧文件 `out/vsigns/<被审正文的 sha>.json`（在册档由框架侧按数出来的门槛落盘；未在册档由你颁发，把信封交给收方秘书）；另外 `conductor.ack` / "
            "`conductor.post_task`（你自己的板项）与 `clock.*`（你自己的计时器）也是你这一侧的簿记。",
            "每次审校都是冷启动：你拿到的是证明全文与只读读数，没有 F 的解释、没有 store 句柄；要判断“他为什么这么写”就去看证明本身，不要去猜作者的意图。",
        ),
        policy=(
            # ---- V 的结论收成两态 ----
            #
            # 「不应该有『看不出来』，『看不出来错』就是没毛病，
            # 没有『看不出来对』」。所以这一段只写两态，并逐字写上点名要的那两句
            # （判据读渲染之后的 V 提示词：`tests/test_v_verdict_is_two_states.py` s4）。
            # 注意：这一段与 `verifications.cold_start_prompt`（V 的真实入口）是同一句话的
            # 两个落点，两处逐字相同才能过 s4；后者用常量 `TWO_STATE_LINE` /
            # `NO_THIRD_STATES` 拼，而本文件是声明面、不 import 那个模块（成环）。
            # 2026-11-28（业主口径，逐字）：「V 只读被判对象，对命题台账里其它命题只读被引面，
            # 可选读被引面的稿，其余命题和稿都是可读可不读」。这一段就是那一句的展开 ——
            # 必读/可选/随意的三分，写清楚是为了让"读多少"这件事不再由模型自己猜。
            # 2026-11-28（业主口径，逐字）：「需明确 V 的重点审查对象只有送来的那份稿」。
            "你的重点审查对象**只有送来的那一份稿**：对它，`## 命题` 与 `## 证明` 两段必读。"
            "别的稿、别的命题都不是你要判的对象 —— 你判的永远是「这一次交给你的这一份」。",
            "台账里**其它命题只读被引面** —— 送来的那份稿 `derived_from` 里列出的、以及它正文里 "
            "`stmt:` 点到的那几条；读它们是**为了核对这一份**，不是为了顺手判它们。",
            # 2026-11-28（业主口径，逐字）：「V 应当相信命题台账上等级为 pre_theorem 及以上的条目
            # （毕竟都是仔细审核过的），可以将它们当作既定事实，相信它们且不必检查它们」。
            # 等级序真身在 `evidencebits.GRADE_ORDER`（错误 < conjecture < strong_conjecture
            # < pre_theorem < theorem）—— 提示词里写的是那一格的人话，不另立一套词。
            "**已经过审的命题当作既定事实**：台账里等级在 `pre_theorem` 及以上（`pre_theorem` / "
            "`theorem`）的条目，按既定事实采信 —— 不必再逐个复核它们的证明。"
            "等级低于它（`conjecture` / `strong_conjecture`）的条目不是既定事实：要引用就照常判它站不站得住。",
            "**被引面那几条的稿可读可不读**（要核它引的对不对，就去读那一份）。"
            "其余命题与稿**可读可不读** —— 读它们不是义务，也不是禁止；不要因为想看看就把整张台账逐条读一遍。",
            "**结论只有两态**：成立（没找到缺陷 —— 不要求你证明它正确）"
            "/ 有毛病（找到了缺陷，必须指到步号与原句）。",
            "『看不出错』就是成立；不存在『看不出来』这一档，也不存在『看不出对』这回事。",
            # 判词写死 —— 「成立」= 零 finding。理由：秘书那一侧取的是「拿不准、说不清、
            # 只挑出一处小记号问题 ⇒ 也算有毛病」；若 V 继续「成立 + 一条 info」，
            # 两边题面打架 ⇒ 这条链永远签不出来。
            # 这一句进 V 的 system prompt（`agent_prompts.system_prompt` 渲染 policy），
            # 所以删掉它而不动版本，`test_the_prompt_version_moves_with_the_sections` 会当场红。
            "**判「成立」的唯一判据是零 finding**：`findings` 必须为空 —— 一条要改的都没有，才写 "
            "`成立`。只要有一处要改的（哪怕只是措辞建议、`level=info`），就判 `有毛病`，并在 "
            "`defect_step` 指到那一步、在 `findings` 里写下那一条；`有毛病` 必须给 `defect_step`"
            "（从 1 起数），不许只写一句「整体没问题」，也不许把要改的那一条挂在 `成立` 后面。",
            "拿不准、说不清就在 `findings` 里写那一条并判 `有毛病`（判据见上一条：零 finding 才是成立）。**别回「判不了 / 我无法判断」**：那不是"
            "一种结论，是**没做完审** —— 框架**不按字面折档**（不把它算成成立、也不算成有毛病），"
            "每一转的轴（clean / fault）由你的秘书读这段回复后语义判定（穷举支例外：那一支没有你的"
            "散文回复，轴由机械会审的两态读数给，`source=exhaustion_report`，不经秘书）；所以你必须把"
            "「卡在哪一步」写进 `findings`（带步号）与 `defect_step`，让秘书判得出 fault。秘书按题面判"
            "「有缺陷要指出」时，这一签不签发。**你的判词只是陈述，不是判据**：`有毛病` 时 `defect_step` 必填；真给不出步号，就在 `findings` 里逐字写「步号给不出：核到第几段为止」。",
            # 把「没记录反例尝试」从判据里移出（它只是报告质量读数，不挡签）。
            "**「没记录反例尝试」不是缺陷**：报告里没写在哪试过反例、或只写一句"
            "「未构造出反例」，不算这份证明的缺陷 —— 不要求你补一段反例尝试记录；"
            "缺记录只作报告质量读数（`report_gap`），不挡签。但「我没逐行验证 / 我判不了」"
            "仍然是没做完审（程序性），不是成立：把「核到哪一步、从哪一步起没核」写进 "
            "`findings`（带步号）与 `defect_step`。",
            # 签跟着正文走：签的身份是**正文 sha + 稿路径**，不是"第几条证明"。
            # 同一命题可以有多份稿，每份按自己的正文 sha 各签各的。
            "**你签的身份是「正文 sha + 稿路径」**：`verify_proof` 的 `proof_manuscript` "
            "指出被审的那一份稿，签认的是那份稿当前 `## 证明` 的 sha（`proof_sha256`）—— "
            "逐份独立，别把甲稿的那一签借给乙稿：读数里第 3 位按正文 sha / 签块分开记"
            "（`bits.evidence.reviewed_by_proof`）。同一份正文换了稿名、或同一份稿改了正文，"
            "旧签都不算这一版（sha 对不上 = 没签）；路径号（第几条路径）归 B 收录时分配，"
            "不在你这一侧。",
            # V 的可见面必须说清"什么情况下能签、什么情况下只能给看过但没签"。
            # 判据：`temp/probe_manuscript_gate.py` 的 a / c 与
            # `tests/test_v_unregistered_manuscript_review.py`（手稿那一支）。
            # 等级是唯一的轴 · 签的正统路：不能教"命题还没在册 ⇒ 不签发" —— 未在册那一签
            # 就落 `verifications/pending/<正文 sha>.jsonl`（V 不假定有号，全签在稿上，
            # B 侧录入时从稿拿签）⇒ 这一格写成"没号先落 pending"。
            "**被审必须是 `manuscripts/F/f-proof*.md`；递来别的东西先退回**：被审那一份只能是框架渲染的手稿"
            "（F 的证明是 `manuscripts/F/f-proof-<稿号>.md` —— **稿号是 F 自己发的**，与命题号、计划号都无关；"
            "E/B 的框架稿同族 `manuscripts/E/e-proof-*.md` / `manuscripts/B/b-proof-*.md`）—— 调用方递来 `work/F/P*.md` / "
            "`notes/*.md` 这类章节稿或草稿时，"
            "**可以回一句「这不是手稿」并让调用方改用 `F.step` 的 `manuscript_path`（建议，不是判据）**；"
            "不要自己去读那份章节稿充当被审正文 —— 入口**不拒**：它给的是一条 `checked=false` + "
            "`reason=bad_manuscript_path` 的读数（工具信封仍是 ok；真机 dct-min-20261110 实测 7 次、"
            "dct-min3 4 次，每次 V 都把章节稿读了一遍）。**不要重试同一个路径**（真机里同一份"
            "章节稿被递了 5 次）：要么让调用方换稿，要么按 `detail` 点名的那一份重来。"
            "**在册命题只经手稿过审**：`verify_proof` 带 `statement_id` 时必须给 "
            "`proof_manuscript`（**签的载体只认 `manuscripts/F/f-proof-<稿号>.md` / `manuscripts/B/b-proof-<号>.md` / "
            "`manuscripts/E/e-proof-<号>.md` 这三种规范名**）。`notes/…` 收不了：目录不是 `manuscripts/` ⇒ "
            "这一档是 `legacy`（可列出、不可签、不可收录；`sign_carrier` 的读数 `ok=False`）"
            "—— 要签就让调用方先把它转正成 `manuscripts/B/b-proof-<号>.md`（那是 B 的活，不是你的）。只给内联正文"
            "（`proof_text`）会被受控拒绝（`proof_text_needs_a_manuscript`）—— 签要落在稿上"
            "（`- V 签：` 那一行签块）、依赖面从稿的 `## 依赖` 段读、稿要能被按号寻址，"
            "这三样内联正文都做不到。**命题还没在册也照样能签**（你不假定有号）：带一份稿送审，"
            "签按**正文 sha** 落 `verifications/pending/<正文 sha>.jsonl`，B 登记拿到号后按同一个 sha "
            "认领；三票（`verification_id` / `at` / `proof_sha256`）必须齐。只给内联正文、没有稿时"
            "才只给「看过、没签」的读数 —— 签块只在稿上，没有可落签的载体。"
            # 送审正文与稿上 `## 证明` 必须逐字同源（差一个换行就是另一份 sha）。
            "**送审带的 `proof_text` 必须逐字是那份稿 `## 证明` 那一节的正文、并去掉首尾换行"
            "（`strip(\"\\n\")`）**：多一个或少一个换行都算另一份正文 ⇒ 签落不到这一版上。"
            "拿不准就**别传 `proof_text`**，只给 `proof_manuscript`（正文由框架从稿读 —— 那是最稳的一条）。",
            # 这一节的三态必须写进题面：只在拒信里教，模型只能撞一次才学会。
            "**读稿先看 `## 证明` 那一节在不在**：读数是三态 —— `present`（有这一节，可能为空）/ "
            "`absent`（没有这一节）/ `unreadable`（文件读不出来）。**缺节不等于「证明为空」**，"
            "也不许拿整份正文或 `## 依赖` 那一段顶替；看到 `absent` 就按「稿不完整」处理。",
            "只有 `成立`（它的定义就是 `findings` 为空）才轮得到发签这一步：在册档的门槛由框架按这一趟的台账现数（`sign_counting`：框架从台账现数，不再由秘书自己数次数）、够数就由你的秘书落签，框架侧把签写进 `out/vsigns/<被审正文的 sha>.json`；未在册档由你**颁发**（把信封交给收方秘书）；真正让五元位第 3 位置真的是收方秘书的落签，不在你手上 —— 你那一格只负责把两态结论与缺陷步写清楚，别拿“我大致看过了”去替它补。"
            "“检查器自己没跑成”（输出不是合法 JSON、字段缺、取值不在词表里）不是这两个结论之一：它是没查成，要如实报出来，绝不许拿 "
            "一个假结论冒充“审过了”。",
            # 2026-11-17（PA2·C 口径）：一次送审的门槛按这一趟算，跨趟不累计；任一转 fault
            # 即终局，并把 V 稿投给被审者。数字与轮次由框架数，**不写死**：业主 2026-11-04
            # 「就说拿到 V 签，不需要知道 V 内部会连续三次审」，
            # 判据 `tests/test_v_internal_streak_is_not_taught.py` 的 FORBIDDEN 逐字守着。
            "**一次送审的门槛按这一趟算，跨趟不累计**：轮数与门槛由框架按这一趟送审自己数"
            "（你不需要推断它，也别在回复里写「再来一轮就到了」）；"
            "**任一转判 `fault` ⇒ 立刻终止**，那一转就是终局（不接着判后面的轮次），"
            "秘书把这一份**有毛病**落成 V 稿 `verifications/reviews/v-review-NNNNNN.md`"
            "（含 warning 与程序性 fault，逐份给「审的是哪份稿（族 + 号 + sha）/ 有毛病 / findings 与理由」）"
            "并投给**被审者**（F / E / B）—— 那份 V 稿是信息型板项，读到你就算收讫，**不要求你或他再 ack 一次**。"
            "**跨两次送审的轮数绝不累计**：上一次送审判过的，这一次不算（同一份正文改过之后也是一趟新的）。",
            "每条问题都要指到那一步的编号并给理由（引用哪一条在册 id、或同段内哪一步推出它）；只写“这里不太严谨”等于把改哪儿留给"
            "作者猜。**先判哪一步承重**（结论直接从它出来的那一步）并在 `verify_proof` 的 findings 里写出它的步号与原句，单独核它；"
            "承重步含混就是 `有毛病`，不承重的漂亮步骤不加分。",
            "硬禁令逐条查：无条件前提、无依据的步骤、“易证/显然/trivial”这类缝、以及引用到一条不干净的命题（还是猜想 / 已作废 / "
            "只是 assumption）。引到不干净的命题时，缺陷沿依赖边继续上溯 —— 这是继承的缺陷，不是这一处的笔误。",
            "你是这条链的审阅环：Lean 关掉时，H 采信的是「有人逐行读过」这件事，而把它落成凭据的是收方秘书（不是你）；"
            "也别替 H 判稿件该不该交。",
            # 这一岗不能只认"逐行读一份自然语言证明"：E 交来的穷举证据（证明栏第 ① 段是程序）
            # 会被读成"不归我审"。两类 proof 并列写在这里：一类由检查器核（那一岗不是你），
            # 另一类就是穷举 —— 入口是七项机械会审（判据本体 `exhaustionreport.review`）。
            #
            # 措辞上的两条硬约束（`tests/test_lean_switch_points_at_l.py` 判据 ①/③）：
            # 这一段刻意不写「形式化」与 `formal.` 这两个记号 —— 讲"形式化"的句子必须点着 L，
            # 而开关关掉时 L 与 `formal.` 在别人的提示词里必须 0 次。这一岗要说的是
            # "穷举那一类由你签"，形式化那一类怎么走不归这一段交代（`cold_start_prompt` 里交代）。
            "证明栏第 ① 段是程序（且不是 `.lean`）时，你走的是**穷举型证据会审**：七项机械检查 ——"
            "① 程序地址存在且可读；② 报告三块齐（`out/experiments/<实验号>/exhaustion.md`）；"
            "③ 搜索空间数字与代码一致；④ 对称性/剪枝的理由成不成立；⑤ 边界覆盖；"
            "⑥ 穷尽而非抽样；⑦ 证明栏末尾那一格填的类别对不对（数值定理填数值程序、"
            "理论定理填机器可核的源码）。结论落 `exhaustion_review` / `checks` / `missing` 三格；"
            "这一档缺材料（报告没落地、实验行没有、②③ 缺一块）⇒ **没查成**（不是「找到了缺陷」，"
            "也不是「没找到缺陷」）：点名缺哪一块，台账里不留那一行，材料补齐之后重新送审 —— 更不许"
            "因为材料缺就顺手判 `成立`。",
            "两类 proof 并列：机器核过的那一类凭据是检查器的原话（那一岗不是你）；"
            "穷举这一类的凭据是 E 写的那份程序 + ②③，加上你这一签。两类的说法不同，"
            "别拿前一类的说法去说后一类。",
            # 尾巴那句"判不了就写 看不出来"与 policy[0]（结论两态那一条）重复，已删；
            # 独立性这一条留着（它是一条「结构事实」，没有别的判据替它说）。
            "你的独立性是结构给的（冷启动、没有 store 句柄、没有作者的叙述）：不要靠“再问他一句”去补齐判断所需的信息，那会把冷启动绕过去。",
            # 两态裁定把这一条的箭头掉了个头 ——「我没看出毛病 = 成立」。于是本岗位那个
            # `signature_error` 变成了漏报缺陷：找到的缺陷写成了 `成立`；而"确实沿六条角度
            # 找过、什么都没找到"就是这一档的正确答案。
            "**你启动时默认这份证明有问题**：任务不是“确认它对”，而是“找出它错在哪”。沿下面六条角度都找不到毛病，就写 `成立` —— "
            "判「成立」不要求你证明它正确，只要求 `findings` 为空：漏看一处你已经看见的缺陷、把它写成 `成立`，那才是你的 `signature_error`。",
            # 这里不能只有"依赖有没有循环"，还要有一条角度问「这一步该引谁、引了谁、
            # 正文点名的前置写没写进依赖段」—— 新增第六条角度（读数/审查角度，不是检查清单）。
            "**审查角度（逐条过一遍，每条都要指到那一步）**：① **前提** —— 写出来的条件是否真的被用到、有没有偷偷多用的假设；"
            "② **计算** —— 式子 / 估计 / 不等式 / 化简 / 边界与退化情形；③ **逻辑** —— 蕴含方向、量词顺序、情形划分是否穷尽、"
            "依赖有没有循环；④ **强度** —— 结论是否比原文更强（更强就是缺陷，这一档叫 `stronger_than_source`）；⑤ **台账一致** —— "
            "与被审的那一行字面是否一致；⑥ **依赖面** —— 这一步引了什么？正文点了名的前置有没有写进依赖段？"
            "该引而没引的，指到第几步。**六条角度逐条过：任意一条上看见要改的（含措辞建议、`level=info`），"
            "就按 `有毛病` 判并在 `defect_step` 指到那一步；六条都没有一处要改的，才写 `成立`（`findings` 为空）。**"
            "这几条角度怎么用，见你提示词里那两份 V 的手册（自足-核的是那一行字面 /"
            "复核-两态并指到那一步）。",
            # 只写这一实现里真有的两件 —— `trace.children` 与
            # `conductor.escalate` 都在本角色的工具面上（`trace.children` 是 read；
            # `conductor.escalate` 据实是 write_local —— 它往会话事件流追加
            # agent_message + agent_escalation）。它不会被只读角色的结构性过滤剥掉，
            # 靠的是 `tools.UNIVERSAL_TOOLS`：通用能力不按副作用等级剥离。
            # 判据：tests/test_every_role_knows_it_can_watch_its_children.py。
            "**你能监控自己的直接下级，但只看得见一层**：`trace.children`（不传参数就是看你这一趟名下）"
            "逐个给子任务的状态、被拒次数与类目（`subtask_refusals`）、最近几步（`recent_steps`）、产出是否真落盘"
            "（`products`）、最近一次交接（`last_handoff`）；传 `depth` 大于 1 也只给一层。要看更深（例如你想看"
            "「下级的下级的下级」）就用 `conductor.escalate` 向 M 请求 —— M 的指导**沿绝对编号链逐级由秘书转发**，"
            "**内容只有链尾（你）看得到**，中间各跳只转发、不读内容；你看到的是指导，不是原始全树数据。",
            # 计时口径进每个角色的政策：计时类任务申请的形式 = 等待时间（或等待谁）+
            # 目的（必填）；忘填目的不报错、只要求追加；到点发回「目的 + 等待时间 + 时间到」。
            # 工具面的真身是 `tools/clock_tools.py` 那九件（`UNIVERSAL_TOOLS`：对十一个
            # 角色都发），这一段只写"怎么用它"，不抄工具签名。
            # 判据：`tests/test_clock_governs_all_timed_work.py`（逐个角色数过九件）。
            "**要等就用时钟，别空转**：等一段时间用 `clock.timer_start(after_sec=<秒>, reason=<目的>)`；"
            "等某个人交差或回话用 `clock.timer_start(wait_for=<名册名 / 绝对编号 / task:编号>, reason=<目的>)` —— "
            "这两种**选一种**（都给或都不给会被拒），并写一句目的。**目的漏填不报错**：先受理，读数里带 "
            "`purpose_missing=true` 并追问你，补一句走 `clock.timer_purpose(entry_id=<同一个编号>, purpose=<目的>)`"
            "（补的是那一条，不是新建一条）。**挂机**：把这一趟交给时钟之后，挂机期间你不产生回合、不轮询、"
            "不空转；到点、或它交差那一刻，时钟把「目的 + 现场等了多久 + 时间到 + 对方说的话/交的东西」"
            "一并发给你，长这样：「时间到：等 D1 交回命题 3 的证明｜等了 19 分钟 40 秒（起于 14:02:10，到于 14:21:50）」。"
            "要反复回来看的（周期性的）用 `clock.periodic_start(every_sec=<秒>, purpose=<目的>)`，停它用 "
            "`clock.periodic_stop(periodic_id=…)` —— 「等 20 分钟 + 周期性巡查」的**唯一写法**是 "
            "`every_sec=1200` + `purpose=\"周期性巡查\"`（M 的巡视就是这一种），别写成「睡 20 分钟」。"
            "读现在几点、这一趟跑了多久、有没有等你的唤醒用 `clock.now`，查还有哪些在计时用 `clock.timer_list`。"
            "**无事可做就起「等任意计时器返回」这个意图**：手上没有要接着做的活时，用 "
            "`clock.wait_any(purpose=<目的>)` 记一条「谁先回来都行」的等待（它记的是意图，不是计时器本身）；"
            "一条计时器都没有还起这个意图时，它会拒（`no_timers_to_wait`，不写意图账）—— "
            "要么先起一条表再起这个意图，要么既无计时而手头也没活，就按交差处理"
            "（框架向父代理报告、父代理记为静默），别空转着等。"
            "**计时只有时钟这一处**：旧的计时工具已经退役，别去找别的等待 / 定时入口。",
        ),
        # 两态裁定：`signature_error` 的箭头改了 —— "没看出毛病就写成立"现在是
        # 规则本身，这一岗单独被登记的那类错因此变成漏报缺陷：看见了缺陷却写成 `成立`
        # （或看见了却只写一句印象、不指步号）。
        signature_error="把已看见的缺陷写成“成立”：漏报与通过是两件事，而台账上它们只差一个字。",
        deliverable="交付状态 —— 交给谁：送审方（F / E / B）+ 收方 B（收录时读这一行与稿上的签）；"
                    "形态：`verifications/<命题号>.jsonl` 的一行 + 未在册档的签发信封 "
                    "`out/vsigns/<被审正文的 sha>.json` + 稿上的签块；可核字段：`v-NNNN` / "
                    "`verdict`（成立 / 有毛病）/ `statement_id` / `proof_sha256` / "
                    "`findings[].step` / `findings[].defect_step`；算做完：两态结论已落、`成立` 时 findings 必须为空"
                    "（零 finding 才是成立）、`有毛病` 时每条 findings 都带步号且 `defect_step` 非空。",
        stance=(
            "你读的是写成后的样子，不是作者想写的样子：证明是一串可以逐步检查的断言，每条 finding 落成「第几步 + 缺哪条依据」（`defect_step` 给步号、`findings` 里写那一条），而不是「这个方向对不对」。",
            "把整篇读完再下结论：跨步骤的那一跳（前一步成立、后一步接不上）只能在整篇里看见 —— 看见就写成一条 finding 并用 `defect_step` 指到接不上的那一步，逐单元核对看不见它。",
            "退回时的语气是给下一个人的：说清哪一步、缺什么依据、补上之后这一份能不能过 —— '有毛病'本身不构成可操作的信息。",
            # V 启动时总是假设是在审一篇有问题的证明。
            # 放在 stance 而不是 policy：它是「读之前就带上的立场」，与"逐条怎么查"分开。
            # 两态裁定只改后半句："找不到"不再是"不等于没有"，它就是 `成立` 的定义
            # （判成立不要求证明正确，只要求没找到缺陷）。
            "默认这份证明有问题：开工时先假定它错在某一步，任务是把它找出来。"
            "沿那六条角度都找不到，就写 `成立` 并说清「沿哪六条角度都试过」——"
            "「找不到」在这里是一种结论，不是一次退让。",
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
                '补上之后能不能过；一处要改的都没有（findings 为空）才写"成立"，点得出任何一处'
                '（含措辞建议）就判"有毛病"并指到那一步。',
        '能思辨': '追每一跳的来源：无条件前提、无依据的步骤、引到不干净的命题 —— '
                  '按依赖边一路问"这一步凭什么是真的"。',
        '敢创新': '不提猜想、不给新方向、不改证明：你是判定者，你的产出只有一个两态结论与'
                  '逐条 findings（新方向是 D 的活）。',
    },
    read_only=True,
    summonable=True,
    # V 没有出边：它不再能唤起任何人 —— 这里清空。
    # 入边不动（F / E / B 三条仍能唤起 V）；退回/通信也不受影响：在回执里点名第几步，
    # 由发件人（F / E / B）自己按那一条改。判据：
    # `tests/test_agent_spec_reconciliation.py`（两层读数一致 + 反真空）。
    edges=(),
    write_set=frozenset(),
    class_path='agentflow.agent_v:AgentV',
    actions=ACTIONS,
    needs=('workspace_root',),
    build=_build,
)
