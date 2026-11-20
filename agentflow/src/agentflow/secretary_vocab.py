# -*- coding: utf-8 -*-
"""秘书的受控词表：一个词只有一个定义（从 secretary.py 的 U15/U17/U18/U25/U26 等单元的常量逐字搬出）。

我保证哪条不变式：判断、决定、派活、签、规则、行轴、依赖面这些轴的每个取值只在这里定义
一次。判据面与提示词面都从这里 import 同一个常量 —— 同一个词写两遍，两份就会在没人改错的
情况下慢慢分叉，而两边各自的测试都是绿的。

为什么先切它：词表被 20 多个单元引用（`JUDGE_VERDICTS` 被判断内核与提示词同时读，
`SIGN_*` 还被 `agent_v/core.py` 读）。先落地它，后面每一刀的 import 面就定了；晚切则每一刀
都要顺手改一次词表 import，五刀就是五次重复碰同一面。

对外名字：本模块导出的全部常量（`KIND_*` / `DECISIONS` / `JUDGE_*` / `SIGN_*` /
`DISPATCH_*` / `ROW_AXIS_*` / `DEPS_MISSING_*` / `NONTRIVIALITY_*` / `BRIEF_MAX` …），
它们都还在 secretary.py 里再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from typing import Any


#: 发件/收件的单次模型调用上限（`draft/55` §5.2：1 次调用、≤3 秒，超时放行）。
DEFAULT_DEADLINE_SEC = 3.0

#: 秘书 ⇄ 秘书协商的轮数上限（`draft/55` §5.2：最多 2 轮，之后上报本体）。
MAX_NEGOTIATION_ROUNDS = 2

#: 一次最多几条闭环提醒（`draft/55` §5.2：默认 5，避免刷屏）。
MAX_REMINDERS = 5

#: 六种事件名（`draft/55` §5.1）—— 常量在这里是为了让"冒充本体"这件事结构上不可能：
#: 秘书发出的每一条都带 `secretary/` 前缀。
KIND_OPTIMIZED = "secretary_optimized"

KIND_HANDOFF = "secretary_handoff"

KIND_NOTICE = "secretary_notice"

KIND_PROPOSAL = "secretary_proposal"

KIND_NEGOTIATION = "secretary_negotiation"

KIND_DECISION = "secretary_decision"

#: 秘书的判断结论词表（`draft/55` §2 的 B 类）——派活那一轴的结论。
DECISIONS = ("可派", "建议重排", "建议改派", "建议不派", "已优化", "已提醒", "已执笔")

# ---------------------------------------------------------------- 两段式：洗 → 请示 → 确认
#
# 业主裁定（2026-10-21）：派活时的"委托秘书洗一遍格式"是两段，不是一段：
#
# | 段 | 谁做 | 产物 |
# |---|---|---|
# | ① 洗 + 请示 | 发件方秘书 | `washed == original` ⇒ 无事发生（直接执行，不多花一轮）；有差异 ⇒ 不执行，出一份受控的请示读数（`outcome=wash_proposed` + `proposal_id` + 逐字段 diff） |
# | ② 确认 | 发起方（父） | `accept_proposal=<id>` ⇒ 用 `washed` 执行；`reject_proposal=<id>` ⇒ 用 `original` 执行并留痕 |
#
# 为什么不是"直接应用"（S1g 的旧形态）：那等于秘书替本体表态（`draft/53` §2 的两条红线），
# 而与它相对的那一版（"永远只建议"）又把洗格式变成摆设（`draft/90` E5 的差）。
# 两段式把"洗"与"要不要按洗过的派"分开：洗是格式面的确定性命中，要不要是父的事。
#
# 受控词：确认/拒绝的字段名、请示的 `outcome` 取值 —— 三者都只有这一份定义。
ACCEPT_PROPOSAL = "accept_proposal"

REJECT_PROPOSAL = "reject_proposal"

PROPOSAL_KEYS: tuple[str, ...] = (ACCEPT_PROPOSAL, REJECT_PROPOSAL)

#: 第一段的受控 `outcome` 值（步骤结果里就这一个词说"这一步没有派活"）。
OUTCOME_WASH_PROPOSED = "wash_proposed"

#: 执行那一趟台账 `decision` 那一格的受控取值（请示 / 接受 / 拒绝，只有这三个词）。
#: 三个都只在 :meth:`Secretary.optimize_outbound` 那一处产生，且与步骤结果的
#: `outcome` / `accepted` 一一对应（读台账的人不必再去猜"这一行是请示还是确认"）。
DECISION_PROPOSED = "洗出格式差异 ⇒ 请示"

DECISION_ACCEPTED = "接受了秘书的格式洗"

DECISION_REJECTED = "拒绝了秘书的格式洗"

#: 非平凡性的五档（T0–T4）：它回答"多不平凡"，同时是判档那一问的词表
#: （`STATEMENT_VERDICTS` 从它派生）—— 一根轴，不是两根。
#:
#: T0 不是"次品档"、不是"未评级"，它是同一根轴上的第一档：
#: 平凡但真的那些（`a+b=b+a` 那一类，以及由数值实验直接穷举出来的基础事实）落在 T0，
#: 而它们"能进表"这件事由 T0 这一档保证。
#:
#: | 档 | 语义 |
#: |---|---|
#: | 0 | 基础定理或初步结论（平凡但真；含由数值实验直接穷举得出的那些） |
#: | 1 | 有一定价值的非平凡结论 |
#: | 2 | 证明方法都是平凡的，但工作量较大 |
#: | 3 | 需要用较多的技巧或跨领域工具 |
#: | 4 | 需要天才般的洞察力，或思维链极长，或是偏离主流研究方向的神奇构造 |
#:
#: "判不了"不再用 0 表示（0 从这一天起是一档真的档位）：见 :data:`NONTRIVIALITY_UNJUDGED`。
NONTRIVIALITY_LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4)


def _nontriviality_level(value: Any) -> int | None:
    """把模型给的档位收敛到 `0|1|2|3|4`；别的（含缺省）一律 `None` = 判不了。

    2026-10-23 起 `0` 是一档真的档位（T0 基础定理或初步结论），所以"判不了"必须
    换一个值：`None`。这里刻意不把坏输入折成 0 —— 那会把"模型给了 `1.9`"读成
    "这是一条基础定理"，正是"静默降级"的形态。同理也不许折成 1。

    只认整数（或纯数字字符串）：`1.9` 不是"第 1 档"，它是坏输入。

    2026-11-01：`nontriviality_label` 与 `STATEMENT_VERDICTS` 在 import 期就要用它
    （词表从档位轴派生），所以它住在档位常量旁边、必须定义在它们之前。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        got: Any = value
    elif isinstance(value, str):
        raw = value.strip()
        upper = raw.upper()
        if upper.startswith("T") and upper[1:].isdigit():
            # 2026-10-29：判档那一问的 decision 词表就是 T0..T4，这里原先只认数字
            # ⇒ 模型答 "T3" 永远解析成 None（"交给模型判"在结构上走不通）。
            got = int(upper[1:])
        elif raw.isdigit():
            got = int(raw)
        else:
            return None
    else:
        return None
    return got if got in NONTRIVIALITY_LEVELS else None


#: 档位的显示名（`0 -> "T0"`）。读侧一律调 :func:`nontriviality_label`，不各写一份。
_NONTRIVIALITY_LABELS: dict[int, str] = {level: f"T{level}" for level in NONTRIVIALITY_LEVELS}


def nontriviality_label(level: Any) -> str:
    """档位号 → 显示名（`0 -> "T0"` … `4 -> "T4"`；判不了 ⇒ 空串）。"""
    got = _nontriviality_level(level)
    return _NONTRIVIALITY_LABELS.get(got, "") if got is not None else ""


#: 判档那一问的结论词表（业主 2026-11-01 裁定：审美轴三格退场，直接只用 T0 到 T4）。
#:
#: 2026-11-01 之前这里是 `("合格", "太平凡", "判不了")`：一根"收不收"的审美轴，与
#: `NONTRIVIALITY_LEVELS`（"多不平凡"）并排。裁定之后这一问只剩一根轴 —— `decision`
#: 就是档位，三个旧词退场。从档位轴派生（不写第二份字面量）：两张表漂了，就会出现
#: "词表里有 T5、档位轴没有"这种只在提示词里成立的档位。
#:
#: ## 两态（2026-11-01 第二刀：判不了退场为"没查成"）
#: | 结局 | 盘上那一格 |
#: |---|---|
#: | 有档 | `decision` = `"T0"`…`"T4"`（决定台账同值；档位台账 `nontriviality` 0..4 + `label`） |
#: | 没查成 | `judge.checked=false`；决定台账 `decision="没查成"`；没有档位行 |
#:
#: "判不了"不是一种判定结果，是"我们没拿到判定"（模型给 null / 旧词 / 坏 JSON，
#: 调用失败，正文被截断，一项力气读数都取不到）—— 它的处置是"重试 / 重交 / 人看"，
#: 所以它必须长成"没查成"，而不是第四档，也不是一条 `nontriviality: null` 的行。
#:
#: 概念 / 定义行另有一态 `not_applicable`（见 :meth:`Secretary.not_applicable_nontriviality`）：
#: 那是"这一问对它不成立"，不是"没查成"，两回事，不许折平。
#:
#: ## 旧行怎么读（只影响读旧台账；写侧与新行一个字都不产生这三个词）
#: | 老 `decision` | 折算出的档位 | 判据 |
#: |---|---|---|
#: | `T0`…`T4` | 同名档位 | 老台账里的同名档位 |
#: | `太平凡` | T0 | 这个结论只剩"力气小 ⇒ 落 T0"这一层意思 |
#: | `合格` | 读 `judge.nontriviality`（或同号 `nontriviality.jsonl` 那一行）；都没有 ⇒ 未判 | 它当年只表示"收"，从不携带档位 |
#: | `判不了` | 未判（`None`） | 它是"该判而没判"，不是一档 |
#:
#: 唯一实现是 :func:`_tier_from_legacy_decision`（读旧行的唯一折算口）。判据
#: `tests/test_the_statement_vocabulary_is_only_the_five_tiers.py` 钉着"旧词只许出现在它里面"。
STATEMENT_VERDICTS: tuple[str, ...] = tuple(
    nontriviality_label(level) for level in NONTRIVIALITY_LEVELS)


#: 「这一条与在册的哪一条是同一条命题」的结论词表（两档）。
#:
#: 准绳：「定理描述一致（什么条件推出什么结论），就是一个定理」。这一问不许有第三种
#: 结论 —— 读不清就是没判成，不是一种判词。
#:
#: 所以这一问只有两个结论：同一组条件推出同一组结论（same）/ 不是（different）。
#: 「没有第三种结论词」：读不清（缺条件 / 结论写不清 / same 点不出候选号 / 词表外结论 /
#: 超时 / 坏 JSON / 没缝）不是一种判定，而是「没判成」 —— `checked=False`，上层按 fail-closed
#: 处置（不新建、不合并、受控拒）。"没判成"与"判过了、不同"必须在盘上分得开：
#: 前者是 `checked=False`，后者是 `checked=True` + `verdict="different"`。
PROPOSITION_VERDICTS: tuple[str, ...] = ("same", "different")


#: V 的回复有没有指出缺陷（两档）。
#:
#: 为什么另立一张表而不复用 `STATEMENT_VERDICTS`（`合格` / `太平凡` / `判不了`）：
#: 那是 B 的审美轴（这条命题够不够格入库），这里是 V 的结论轴（这段审阅回复
#: 到底有没有指出缺陷）。两根轴共用一张词表之后，"太平凡"会被当成一种"有缺陷"——
#: 而它们在台账上是两件事（前者不改任何签，后者清零连续次数）。
#:
#: 这一根轴的词表只有两格：「不可能有判不了。只要不是完全没毛病都叫有毛病」。
#: 拿不准、只挑出一处小记号问题、说"我没逐行验证"——统统算「有缺陷要指出」。
#: 模型若答词表外的值，`judge()` 判它"不在词表里 ⇒ 不采信" ⇒ `checked=False`
#: （"没查成"，见 :meth:`Secretary.judge_v_reply`），不会被当成第三种结论，也不会在
#: 台账上留下一个 `判不了` 的判词。
#: 老台账行上那个轴名也不再是一格：`verifications.SECRETARY_JUDGE_HISTORICAL_AXES` 与
#: `secretary_axis` 的兼容支都没有了，老行上那个值读出来是空轴（"这一行没有轴"）。
V_REPLY_CLEAN = "没问题"

V_REPLY_FAULT = "有缺陷要指出"

#: `v_reply_defect` 那一类的词表（两格，顺序 = 由"没问题"到"有缺陷要指出"）。
V_REPLY_VERDICTS: tuple[str, ...] = (V_REPLY_CLEAN, V_REPLY_FAULT)

#: 词表取值 ⇒ 台账上那条轴的两档（与 `verifications.SECRETARY_JUDGE_AXES` 逐字同一套）。
#: 为什么要有这一张映射而不是直接把中文写进台账：台账那一格是给代码读的
#: （`verifications._hold_run_lengths` 按 `fault` 分流），中文词表是给模型读的。
#: 两者之间只有这一处翻译，改词不改轴；这张映射里没有第三条出路 ——
#: "拿不准"落在 `V_REPLY_FAULT` 那一格（业主逐字：只要不是完全没毛病都叫有毛病）。
V_REPLY_AXIS: dict[str, str] = {V_REPLY_CLEAN: "clean", V_REPLY_FAULT: "fault"}


#: V 的秘书「发不发这一签」（2026-11-16 裁定 ③：不再问模型，只留两个读数词）。
#:
#: 地板（同一趟送审内连续 clean 达到门槛）过了即发；没过就是 `不签发`。
#: 这两个词现在只是读数标签，不是一张要模型逐字取自的词表 ——
#: `SIGN_ISSUANCE_VERDICTS` 与 `_judge_system` 的 `sign_issuance` 那一问都已删除。
SIGN_ISSUE = "签发"

SIGN_WITHHOLD = "不签发"

#: 判定"没查成"时，台账那一行的 `decision` 该写什么。
#:
#: 「没查成」不是一种判定 ⇒ 台账上也不许写成一个结论词。这一格因此用
#: `没查成` 这个专用词：它不在任何一张 `JUDGE_VERDICTS` 里，读的人一眼看得出"这一趟没有
#: 结论"，不会把它当成某一档（也不给"判不了"留位置）。
JUDGE_UNCHECKED = "没查成"

#: 判断类别 → 它允许的结论词表（唯一一处把"哪类判断有哪些结论"写下来的地方）。
#:
#: 加一类判断时只加一行：`Secretary.JUDGE_KINDS` 与 `judge()` 的校验都从这张表派生，
#: 于是"新类别悄悄用了别的轴的词"这件事在结构上就发生不了。
#: 同种证明的判定词表（二态、语义；判不了走 `checked=False`，不设第三档）。
#: 定义必须早于 `JUDGE_VERDICTS`（那张表在模块加载期就取它）。
PROOF_KIND_VERDICTS: tuple[str, ...] = ("same", "different")

#: 「这一条派给 F 的活，是不是一个研究方向」那一轴的词表（两态、语义）。
#:
#: 业主 2026-11-13 的裁定（本批 R1/R2）：「plan由F自己决定，所以D不可能做出按plan个数派F，
#: 于是D只能按研究方向开多个F而非把一堆方向委托给一个F」——D 的秘书要审这一件事，
#: 不合适时给提醒（不是拒收）。两档：
#:   `是一个方向`   —— 这一条交给 F 的是一件事（要弄清什么、可试哪条路），一个 F 接得住；
#:   `不是一个方向` —— 一条派活里捆了多个互不相干的研究方向（该按方向拆成多个 F），
#:                    或者它其实是一张"计划列表 / 进度督办"（plan 由 F 自己决定，
#:                    派活不该点名它们）。
#: 判不了 ⇒ `checked=False`（不设第三档：第三档会被读成一个结论词）。
#:
#: 为什么不用「合适 / 不合适」：`_judge_system` 的泄漏判据是子串判的
#: （`test_the_head_is_the_one_of_that_kind_not_a_placeholder`：别的轴的词不许整张混进
#: 这一类的题面），而「合适」是「更合适」的子串（派活轴 rearrange 那一问里就有
#: "换一个收件方更合适"）⇒ 一加就会把那一问判红。这两个词是这一问自己的说法，
#: 不与任何别的轴共用字串。
DISPATCH_FIT_OK = "是一个方向"

DISPATCH_FIT_UNSUITABLE = "不是一个方向"

DISPATCH_FIT_VERDICTS: tuple[str, ...] = (DISPATCH_FIT_OK, DISPATCH_FIT_UNSUITABLE)

JUDGE_VERDICTS: dict[str, tuple[str, ...]] = {
    "duplicate_retry": DECISIONS,
    "tool_name": DECISIONS,
    "rearrange": DECISIONS,
    "statement_aesthetic": STATEMENT_VERDICTS,
    # 命题同一性：结论词表就是二态。
    "proposition_identity": PROPOSITION_VERDICTS,
    # V 的回复有没有指出缺陷。独立一张表，不复用审美轴。
    "v_reply_defect": V_REPLY_VERDICTS,
    # 2026-11-16 裁定 ③：这里没有 `sign_issuance` —— 发签不再是一问，
    # 地板过了即由秘书自动发（见 `decide_sign_issuance`）。
    # 这一份证明与在册各路径是不是同一套证法（二态、语义：对比证明方法，不做任何机械闸）。
    # 不加第三档：判不了走 `checked=False`（fail-closed，调用方不收录）。
    "proof_kind": PROOF_KIND_VERDICTS,
    # 这一条 D 派给 F 的活是不是一个研究方向（二态：合适 / 不合适）。
    # 独立一张表：它不复用派活轴的 `DECISIONS`（"建议重排"是处置，不是"合不合适"）。
    "dispatch_fit": DISPATCH_FIT_VERDICTS,
}

#: `dispatch_fit` 那一问的题面（模块级常量，`_judge_system` 只引用它）。
#:
#: 为什么不住在 `_judge_system` 的函数体里：那一格是软基线
#: `src_functions_gt200_lines` 盯着的函数（业主口径 92 不许抬），二十来行题面塞进函数体
#: 会把它顶过 200 行。题面本身只取决于 `kind`、与材料无关，抽成常量不改变缓存纪律
#: （它照样进 `system` 那一段）。
DISPATCH_FIT_QUESTION: str = (
    "问题：下面这一条是 D 派给 F 的活（材料里的 `task` 是派活原文，"
    "`action` / `params` 是随附的调用面，可能为空）。它是不是**一个研究方向**？\n"
    "判据只有一条：这条派活交给 F 的是**一件事**（要弄清什么、可以试哪条路），"
    "而不是**几件互不相干的事**。\n"
    "几件事（判「不是一个方向」）：\n"
    "- 一条派活里捆了几个不同的研究方向，要一个 F 同时攻几条线；\n"
    "- 它其实是一张**计划列表 / 进度督办**（点名多条计划、多个要证的命题、要求逐个推进），"
    "而 plan 由 F 自己决定 —— D 派活该按研究方向派，不该按计划个数派；\n"
    "- 它把「汇报 / 盯进度」写成了一次攻坚方向（那不是方向，是流程要求）。\n"
    "一件事（判「是一个方向」）：只写方向、约束、可试的路，没有把几个方向捆在一起，"
    "也没有替 F 决定它要开几条计划、先推哪一条。\n"
    "不参与判定的东西：这条方向难不难、值不值得做、F 能不能证出来 —— 那些是研究判断，"
    "不是这一问。\n"
    "读不清（原文被截断、只有编号、没有可读的方向文字）时不要猜：把 decision 留成空串，"
    "框架把它当「没判成」处理（这一条只提醒、不拦派活）。\n"
    "decision 取「是一个方向」/「不是一个方向」之一；reason 一句话；"
    "basis 引派活原文里的字句。"
    "判「不是一个方向」时 reason 必须写清**该拆成几件事、每件事各派一个 F 的话该怎么写**"
    "（这是给 D 的提醒，不是拒收）。"
)

#: 判断"没查成"时，台账那一行的 `decision` 该写什么（按类别）。
#:
#: 为什么需要这张小表：`_record_judge` 的缺省是 `"建议重排"`（派活那一轴的词）——
#: 对这几种判断，`checked=False` 时写"建议重排"是一句假话。这里给它们一个专用词
#: （`没查成`，不是任何一档结论），其余类别原样保留旧缺省：改它们的词会改历史读数。
#: 每一类都得在表里：漏一类，它在没查成时写的就是派活轴的"建议重排"（错轴）。
_JUDGE_UNDECIDED: dict[str, str] = {
    "v_reply_defect": JUDGE_UNCHECKED,
    "statement_aesthetic": JUDGE_UNCHECKED, "proof_kind": JUDGE_UNCHECKED,
    "dispatch_fit": JUDGE_UNCHECKED,
}


#: 「真跑过」的终态（`tasks.status` 那一格）。为什么不用 `tokens > 0` 当判据：81 趟实测
#: `t-000073` 真跑了 18 分钟也 `tokens=0`（记账在 `usage_ledger` 那一侧，`tasks.tokens`
#: 回答的是"这一行抄回来多少"，不是"它跑没跑"）。`draft/160` §三-6 的丁案把它列成前提假设之一。
RAN_STATUSES: tuple[str, ...] = ("done", "failed", "cancelled")


#: 名册简介的字数上限 —— 与内容闸是同一个数（`roster_add` 里 `len(text) > 60` 那一档）。
#: 代写那一支必须自己截到这个长度以内：否则秘书写出来的那句话会被秘书自己的闸拒，
#: "没给简介"就变成"永远登记不上"（死角）。
BRIEF_MAX = 60

#: 句末标点（取"第一句"时截到它为止，含它）。刻意不收 `.`：小数（`1.5`）、
#: 文献号、相对路径（`../x`）里的点会把一句话切碎，而任务原文的句末几乎总是这几个。
_SENTENCE_END: tuple[str, ...] = ("。", "！", "？", "!", "?", "；", ";")


#: 名册里保存的任务原文上限（业主 2026-10-27：「自动以 task 填充目的」+「截断到 200 字」）。
TASK_TEXT_MAX: int = 200


#: `state` 的五档（不许增删：`roster_view` 的对外取值域，前端与读侧都按它显示）。
#: "判不了"不是第六档 —— 它是旁边那一格 `state_checked=False`（2026-10-27）。
STATE_LABELS: tuple[str, ...] = ("活跃", "待命", "已停", "已退役", "未登记")


# ---------------------------------------------------------------- 台账行分轴（Q18，2026-10-26）
#
# 一条 `tasks` 行到底是"在跑的子代理"、"板项"还是"顶趟行"，这个判断只许有一处。
# 散在多处时各写一遍（扇出轴 / 未消项轴 / 闭环轴），而闭环轴那一份没读 `kind`：
# 30 条板项行（`status` 恒为 `pending`）会被数成"running 5 条"（`MAX_REMINDERS` 截断），
# 而那一刻 18 条代理行全部 done、台账里一个在跑的子都没有。
#
# 落点为什么在秘书而不在 conductor：收件箱一族归秘书。
#
# 上面那一处判据同时回答了两个问题 —— "这一行是什么"（轴）与
# "它还活不活"。要"所有代理行（含终态）"的读点拿不到它（终态代理行被折进 `other`），
# 要"活着的代理"的读点又得自己再写一遍 `status ∈ {pending, running}`。所以拆成两件：
# `row_axis(row)` 只回答轴（五档），
# `is_live_agent(row)` 只回答"是不是一个活着的代理"（= 轴是 agent）。判据仍然只有这一处，
# 读点调哪一个由它问的问题决定，不许再内联 `kind` / `status`。
#: 代理行：`kind` 为空、不是顶趟行、`status` 还没终态。
ROW_AXIS_AGENT = "agent"

#: 板项行：`kind` 非空且 `item_state != "done"`（还没收口）。
ROW_AXIS_ITEM_OPEN = "item_open"

#: 板项行：`kind` 非空且已经收口（`item_state == "done"`）。
ROW_AXIS_ITEM_CLOSED = "item_closed"

#: 顶趟行：`open_top_level_run` 开的那一行（`action="run"`、没有父）。
ROW_AXIS_ROOT = "root"

#: 其余（代理行的历史终态行等）：两根轴都不进。
ROW_AXIS_OTHER = "other"

#: 顶趟行的动作哨兵（`conductor.open_top_level_run` 与 `_open_consume_root` 写的）。
TOP_LEVEL_ACTION = "run"

#: "还没终态"的两档（`schema.TASK_STATUSES` 里的活档；与 conductor 的扇出判据同一批）。
#:
#: 这一行是全仓唯一的真身：conductor 的 `UNFINISHED_STATUSES` 是它对
#: 这一行的转发（`tuple(SEC.LIVE_TASK_STATUSES)`），不再是第二份字面量。方向是这样选的，
#: 不是反过来：`conductor` 顶层 import `secretary`（那一行要读 `MAX_REMINDERS`），
#: 而 `secretary` 顶层不 import `conductor` —— 这样两种导入顺序都无环。
#: 判据：`tests/test_live_statuses_single_source.py`（两个名字取到的必须是同一个元组，
#: 且这两个文件里除本行之外不再有 `("pending", "running")` 字面量）。
LIVE_TASK_STATUSES = ("pending", "running")


#: `deps_missing` 的三档（三态：不把「不适用」折成「缺」，也不把「缺」折成「零依赖」）。
DEPS_MISSING_PRESENT = "present"

DEPS_MISSING_ABSENT = "missing"

DEPS_MISSING_NOT_APPLICABLE = "not_applicable"

DEPS_MISSING_STATES: tuple[str, ...] = (DEPS_MISSING_PRESENT, DEPS_MISSING_ABSENT,
                                        DEPS_MISSING_NOT_APPLICABLE)


#: 概念同一性"没判成"的受控码（同上）。
#:
#: 概念这一档是确定性判据（`same_concept`，零模型调用），但"两侧都抽不出定义项"仍是
#: 判不了：折成 different 就会照旧新建第二行（同一个概念两行，正是这一档要治的形态），
#: 所以调用方受控拒，不是"照常新建"。
CONCEPT_IDENTITY_UNJUDGED = "concept_identity_unjudged"


#: `same_as` 归一化时要剥掉的外壳字符：模型把候选号写成了 Python/JSON 列表字面量
#: （`"['000003']"`）或加了引号 / 空白（`'"000003"'` / `" 000003 "`）。
#:
#: 为什么集中成一个常量：真机 82 的 52 处坏值只出现三种外形（见
#: `temp/probe_82_errors/same_as_hits.txt`），而"外壳有哪些字符"是这件事的唯一判据；
#: 散在分支里写两遍，下一次多一种外形就会有半处漏掉。
SAME_AS_WRAPPER_CHARS = "[]'\"` \t\r\n"


#: 同一性按"定义项相同"判的那几档 kind（概念行没有条件 → 结论，命题那一套判据对它失效）。
#:
#: 为什么只有 `concept` 一档、不顺手带上 `definition`：这一档的判据是"标签（或正文里
#: 被定义的那个术语）规范化后相同"，而 `definition` 行在真机台账里常常把标签留着空
#: （命题本体写在 `statement_full` 里），拿它当键会把一堆不相关的定义并到同一行 ——
#: 并错一条的代价比漏并大（与 `PROPOSITION_KINDS` 的取舍同一条理由）。
CONCEPT_IDENTITY_KINDS: tuple[str, ...] = ("concept",)


#: 洗名洗掉的那两类（`label_washed["class"]` 的取值）—— 读的人要能分辨"哪一类触发了"。
LABEL_WASH_ROUTE = "路线/自证草稿/待审签"

LABEL_WASH_WORKING = "内部工作名"

#: 从正文里抽标签时最多留多少字（超出就截断：名字是用来念的，不是第二份正文）。
LABEL_FROM_STATEMENT_CHARS = 60

#: 内部工作名词表：`(这一类的名字, 正则)`。命中的那一段从标签里删掉，并在
#: `label_washed["class"]` 里点名这一类的名字。
#:
#: 真机读数（`projects/mp3-r2/data/statements.json` 的 000000 / 000001）：两行的 label
#: 逐字都是「F 攻坚 000000 子目标 S2」—— 派活台账里的内部工作名成了定理名，于是
#: 同一条定理的两份证明看起来是两条不同的定理。改前的洗名只洗"路线 / 自证草稿 /
#: 要 V 审签"那一类（见 `_judge_system("proposition_identity")` 里 canonical_name 那
#: 一句），工作名不在那一类里，原样落了盘。
#:
#: 为什么是一张可清空的表而不是几条 if：判据要能被反真空验证（把这张表清空 ⇒
#: 真机那两个 label 必须原样保留），而 if 链清不空，那条反真空用例就会打空炮。
LABEL_WORKING_NAME_RULES: tuple[tuple[str, str], ...] = (
    # 「<角色> 攻坚 <编号>」：角色是一两个字母（F / B2），编号可能省略。
    # 末尾那个否定前瞻是"词尾"判据：`攻坚计划` 里的"攻坚"不是工作名（后面还接着汉字）。
    ("攻坚子目标", r"[A-Za-zＡ-Ｚａ-ｚ]{1,2}\s*攻坚\s*[0-9０-９]*"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「子目标 S<n>」（编号可能省略）
    ("子目标编号", r"子目标\s*[SＳs]?\s*[0-9０-９]*"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「第 n 步」/「第 n 轮」：派活台账里的步号
    ("第几步", r"第\s*[0-9０-９一二三四五六七八九十百]+\s*(?:步|轮)"
              r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「待推进」这一档状态词（贴在首尾时算修饰；整条都是它 ⇒ 那不是名字）
    ("待推进", r"(?:待推进|待办|待下一步)\s*[:：,，·—\-]?"
              r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
    # 「草稿」这一档（「自证草稿」「待 V 审签」是它的两种写法）
    ("草稿/待审签", r"(?:自证草稿|草稿|待\s*V\s*审签|待审签)\s*[:：,，·—\-]?"
                  r"(?![\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"),
)


#: 「这一条在讲派活」的机械线索词（受控词表，只有一个取值）。
DISPATCH_VERB = "派活"


#: :func:`dispatch_targets` 认的两条线索名（进读数：判据要能回答"凭什么说它是派活对象"）。
CLUE_VERB = "紧跟派活动词"

CLUE_NOTE = "名字后跟一句括注"

#: 内容与收件面不符时那一行台账的结论。沿用 `DECISIONS` 里既有的两档，不新造词：
#: 一份稿子里装了多件派活 ⇒ 建议按收件人重排；公告里点名并下指令 ⇒ 建议改派成私聊。
DECISION_REARRANGE = "建议重排"

DECISION_READDRESS = "建议改派"


#: 这一闸的受控码（模型读得到的那一个）。
PROPOSITION_FORM_REFUSED = "proposition_form_refused"
