# -*- coding: utf-8 -*-
"""智能体 V：证明级验证（只读；`draft/39` §3.21 一/五/六 的用户定案）。
## 它是谁
H 是稿件级正式审查（五元位第 5 位）；V 是证明级验证（五元位第 3 位）。 V 做三件事（用户点名的 I12/I10/I17），三条都在这里落地：
1. I12 冷启动：每次审校只把"对象（证明全文）+ 只读读数"拼进提示词 ——拼提示词的函数（`verifications.cold_start_prompt`）只收字
符串，没有任何 store / conductor / registry 句柄参数，"独立性"因此是结构性质； 2. I10 硬禁令 + 同段依据：逐条查无条件前提 / 无
依据的步骤 / "易证、显然"这类缝 /引用到不干净的命题，每条问题指到那一步（落进 findings 的 `step` 字段）； 3. I17 整篇重读：证明是整体一次交
给它的输入，不是逐单元切开的碎片。
## 它只写一个文件，不写任何表
`read_only=True`、`write_set=frozenset()`（`specs/v.py`）。它唯一的产物是
`verifications/<命题号>.jsonl`（追加式，`verifications.record_verification` 发号）。所以它拿不到任何写工具
—— 这不是"约定只读"，是 `tools.base._role_surface`的结构性剥离（`tools.READ_ONLY_ROLES` 含 `"V"`）。
## 2026-10-22 补：签字要能到命题那一行上（2026-10-29 起由秘书落地）
`verify_proof` 调 `verifications.record_verification(..., store=self.store, flip=False)`：
它只把台账那一行落盘。把被签的那一份证明（`proof_no`）的 `reviewed` 翻上去是
`verifications.sign_statement` 的事，而它的唯一调用者是 V 的秘书
（`Secretary.decide_sign_issuance` 的落地那一步）。为什么必须由签名这条路径自己写：
此前第 3 位的唯一写者是 B 的 `register_statement`，而它按
`evidencebits.BIT_OWNERS` 不替 V 签字 ⇒ "V 签了、台账上写着成立"与"命题那一行的 reviewed 位"
之间没有连接，收工门 R10 恒 0。写回的结果在返回值 `review_write` 里（写没写成、为什么、
回滚了没有），失败不静默吞掉。
业主 2026-10-29 的口径：V 只产审稿意见；在册档发不发签由 V 的秘书决定（连续 3 次 clean
才发）。未在册档是明文例外（业主 2026-11-04 乙-5）：不经秘书判，三转 clean 即由 V 颁发
签信封（`vsigns.issue`），手稿签块仍由收方秘书落。所以 `verify_proof` 的返回值里
`signed_bit3` 在在册档读的是"秘书真的把位翻上去了没有"（不是"台账里的票数够不够"）；
在未在册档它恒为 False —— 那一档没有命题行可翻，签落在 `out/vsigns/` 与 pending 台账上。
## 2026-10-30 补：「连续 3 次」是谁在数（这一条改了调用形态）
业主口径逐字：「V 所谓连续 3 次『没问题』，是 V 判没问题后连续再判，不是 F 提交 3 次
V 过 3 次。毕竟没问题的判决没必要给 F。有毛病的要给 F 知道叫它改正。这块 V 秘书要做好」。
于是 `verify_proof` 一次调用会自己问模型（同一份正文、同一个 `proof_no`）：每一问都落一行
台账、都问一次秘书发不发；clean 那一档一个字都不发给 F。

## 2026-10-30 再补：连判只有两种终局（业主第二次裁定仍有效）
业主口径逐字：「连判里面如果判出一回秘书语义分析认为是『有毛病』的，
则直接打回了，连判终止」。于是这一趟的终局只有两种，上界动态等于门槛
（:func:`review_pass_bound`，`VR.SIGN_STREAK_NEED` 现读）：

1. 连续 `VR.SIGN_STREAK_NEED` 转 clean ⇒ 秘书发签；
2. 任一转判出 `fault`（有毛病）⇒ 立刻终止，这一转就是终局：台账那一行经秘书洗稿后由
   `agent_loop.v_rejections_digest` 与 `deliver_v_verdicts` 打回给 F；V 自己的结论不是
   「成立」那一档也立刻停（它本身就是打回）。

## 2026-11-02 定稿：跨两次送审绝不累计（业主追加口径，本模块的计数边界）

业主逐字：「不允许跨两次送审累计成功数」。于是：

- 一次 `verify_proof` = 同一次调用内连判 `SIGN_STREAK_NEED` 轮，每一趟从第 1 轮重数；
- 台账每一行带 `review_pass`（这一趟的第几轮）与 `review_call`（这一趟的调用 id）；
- 秘书的发签地板（`sign_issuance.within_call`）只看这一趟的轮数；台账尾部的历史连续数
  （`consecutive_holds` / `legacy_rows`）只作历史读数，不参与新签判断；
- 旧台账没有 `review_call` / `review_pass` 的行 = 历史形态，读得出、但不按新规则重算成签。

## 2026-10-30 三次补：秘书的语义判定只有两档（第三次裁定，本次唯一口径）
业主口径逐字：「不可能有判不了。你告诉我啥叫判不了？只要不是完全没毛病都叫有毛病」。
所以秘书的判定轴只有 `clean` / `fault`：拿不准、只挑出一处小记号问题、只说"我没逐行验证"
——统统算 `fault`。词表里也只有两格（`secretary.V_REPLY_VERDICTS`）：模型若仍答历史
那一格（"判不了"）或任何词表外的写法 ⇒ `judge()` 判"不采信" ⇒ `checked=False`（没查成），
不会被折成第三种结论。2026-11-02（业主追加裁定：「这一档连历史兼容读也不留」）：老台账行
上那个轴名也不再有兼容读 —— `verifications` 删了
`SECRETARY_JUDGE_HISTORICAL_AXES` 与 `secretary_axis` 的兼容支，老行上那个值读出来是
空轴（这一行没有轴），连续计数里没有一条分支认它。

"没查成"不是判定（第 3 条）：秘书问不出来 / 模型输出不合法 / 台账写不进去 ⇒ 那是框架
失败：终止、`checked=False` + 明确 reason，不许当成 fault 打回、也不许说"次数没到"。
没有判断面（装配缺口）与"问过、没答上来"分开读：后者是框架失败（`reason` 以
`secretary_unjudged` 开头），前者是"这一趟没人能发这一签"（V 的审阅照算、台账照落）。

"循环跑完而既没签也没打回"不是一条终局：它只可能来自病态配置（门槛被改成 0 / 负数）
或秘书在次数够的那一转既不签也不判出问题 ⇒ 返回值报内部不一致（`checked=False` + 明确
`reason`），绝不写成"次数没到"。逐次读数在返回值的 `review_passes` 里（每项带
`terminal`：这一转是不是终局、是哪一种终局）。
## V 的判词只是陈述；轴只有两态（散文支由秘书给，穷举支由机械会审给）（2026-11-06 p247 · p248 补穷举支）
业主 2026-11-01 逐字：「不应该有『看不出来』，『看不出来错』就是没毛病，没有『看不出来对』」。
2026-11-06 第三次收紧又逐字定死：「V 的判词只是陈述」「不做折档」「不许按词面把判不了 /
看不出来 / 拿不准 / 我无法判断折成任何一态」；「每一转的轴（clean / fault）一律由 V 秘书
做语义分析后给出」；「判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步」。
穷举支是这条例外里唯一不经秘书的：那一支没有 V 的散文回复，轴由机械会审自己的两态读数给
（`exhaustionreport.review`，台账行的 `source=exhaustion_report`），不经秘书；在册档与未在册
散文支仍由秘书给轴（`source=secretary:v_reply_defect`）。
于是：`verdict` / `findings` / `defect_step` 只由 `parse_verdict` 做结构解析；
`成立` / `有毛病` 是轴的名字（`secretary_judge.axis`），连续次数与签发只看那个轴。
"检查器自己没跑成"（没接线 / 输出不是合法 JSON / 缺 `verdict` 字段）不是轴 —— 那种情况下
`checked=False` 且台账里不留行（绝不写一行"没查成"来冒充"审过了"）。
`verify_proof` 因此有两种失败形态，各自的读数分开：
- `checked=False, reason="judge_not_wired"`：没有模型缝，这次根本没看；
- `checked=False, reason="unparsable"`：看了、但拿回来的东西不是合法结论 ⇒ 不落台账行。
穷举型证据缺材料同理：`checked=False, reason="missing_material"`（缺哪一块进 `detail`），
台账里也不留行。秘书这一问没查成是另一档：台账照落（`secretary_judge.checked=False`），
只是那一转不算 clean、也不按 V 的判词补判。
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import schema as S   # 命题号形态的唯一来源（当前宽度 + 旧四位读侧兼容）
from .. import verifications as VR
from ..store import StoreError

#: V 在台账里的默认实例名（`bit3_payload` 的 `reviewed_by.verifier` 就是它）。
DEFAULT_VERIFIER = "agent-V"

#: V 的受控拒绝码表：`kind` 是档，`reason` 是细则。
#:
#: 为什么两个名字都留（2026-11-05 走查 D7：同一个拒绝给出
#: `kind=proof_manuscript_required` / `reason=proof_text_needs_a_manuscript`）：
#: `kind` 回答"这一笔拒的是哪一档"，它与 B 侧同一件事的码同名
#: （`agent_b/register_statement.py` 的 `proof_manuscript_required`），下游可以按它把
#: V / B 两处的拒绝并成一类；`reason` 回答"这一档里具体缺什么"，而工具声明
#: （`tools/verify_tools.py` 的 reason 词表）与既有判据读的都是它。收敛成一个词
#: 会把"档"与"细则"折平（下游再也分不出"同一档的两种细则"），也会让已登记的
#: reason 词表变成第二个口径 —— 所以两格都留，但对应关系只在这一张表里写一次：
#: :meth:`AgentV._manuscript_gate` 从它取 `reason`，判据也读它核对两处可对上
#: （改掉本表而两个码仍不同名 ⇒ 判据红，见 `temp/walk-fix-20261105/probe_d7.py`）。
#:
#: 表里那两行就是"档 ↔ 细则"的全部映射（一档一格细则；加第二格细则要在这里登记，
#: 不许在调用点各写一份字符串）::
#:
#:     kind（档）                     reason（细则）
#:     proof_manuscript_required      proof_text_needs_a_manuscript
V_REFUSAL_CODES: dict[str, dict[str, str]] = {
    "proof_manuscript_required": {
        "reason": "proof_text_needs_a_manuscript",
        "means": ("在册命题送审没带手稿（只给了内联正文，或什么都没给）：签块 / "
                  "`## 依赖` / 按号寻址都只在文件上，所以这一档一个字节都不审、不落签"),
    },
}


#: `verify.verify_proof` 会写进返回值的 `kind` 码全集（非空；空串 = 这一趟没有档）。
#:
#: 这是唯一的 kind 词表：`tools/verify_tools.py` 的 `returns` 从它拼出模型可见的
#: 词表（不再手抄一份），`temp/probe_verify_tool_face.py` 用 AST 从本文件的实现里现算
#: 同一个集合，两个方向都对账（实现多一个 / 声明多一个都红）。
#:
#: 扫法（判据见那个探针）：以 `AgentV.verify_proof` 为根、沿 `self.<方法>()` 与模块级
#: 调用求可达闭包，取其中所有 `"kind": <码>` / `out["kind"] = <码>` /
#: `out.update(kind=<码>)` 的字面量（含 `IfExp` 两支；经 `V_REFUSAL_CODES` 的除外）。
#: 2026-11-05 走查 D13：`proof_manuscript_required` 此前没进声明（`:1652-1673`）。
V_VERIFY_PROOF_KINDS: tuple[str, ...] = (
    "bad_manuscript_name",
    "bad_manuscript_path",
    "dependency_section_missing",
    "dependency_section_unreadable",
    "manuscript_has_no_proof_section",
    "manuscript_missing",
    "manuscript_unreadable",
    "numeric_evidence",
    "numeric_evidence_reviewed_not_signed",
    "proof_manuscript_required",
    "proof_manuscript_signed",
    "proof_reviewed_not_signed",
    "proof_text_mismatch",
    "proof_unregistered_rejected",
    "proof_unregistered_signed",
)

#: `verify.verify_proof` 会写进返回值的 `reason` 码全集（受控拒绝 / 终局读数）。
#:
#: 与 `V_VERIFY_PROOF_KINDS` 同一条纪律：声明与探针都读这一份。三档带冒号细则
#: 的码在 :data:`V_VERIFY_PROOF_SUFFIXED_REASONS` 里说明形状 —— 实现写的是
#: `<code>：<detail>`，声明里不许再把它印成裸码。
#:
#: `already_signed` 是 `checked=True` 的终局（已签过、这一趟零转）；其余都是
#: `checked=False` 的没查成码。`judge_not_wired` / `empty_reply` 是模型缝自己的
#: problem，经 `_review_pass` 原样透传进 `reason`，所以也在全集里。
V_VERIFY_PROOF_REASONS: tuple[str, ...] = (
    "already_signed",
    "bad_manuscript_name",
    "bad_manuscript_path",
    "bad_proof_no",
    "bad_statement_id",
    "dependency_section_missing",
    "dependency_section_unreadable",
    "empty_reply",
    "internal_inconsistency",
    "judge_not_wired",
    "ledger_row_lost",
    "ledger_unwritable",
    "manuscript_empty",
    "manuscript_has_no_proof_section",
    "manuscript_missing",
    "manuscript_unreadable",
    "missing_material",
    "no_proof_text",
    "proof_text_mismatch",
    "proof_text_needs_a_manuscript",
    "secretary_unjudged",
    "statement_id_missing",
    "unparsable",
)

#: 实现写 `<code>：<detail>` 的那几个 reason（冒号后是细则，不是码的一部分）。
#:
#: 声明按这张表把它们印成带细则的形状（D14）：`ledger_row_lost` 此前被声明成裸码，
#: 而实现写的是 `ledger_row_lost：<reason>`（`:1311` / `:2548`）。
V_VERIFY_PROOF_SUFFIXED_REASONS: dict[str, str] = {
    "internal_inconsistency": "：<detail>",
    "ledger_row_lost": "：<reason>",
    "secretary_unjudged": "：<detail>",
}
assert set(V_VERIFY_PROOF_SUFFIXED_REASONS) <= set(V_VERIFY_PROOF_REASONS), (
    f"V_VERIFY_PROOF_SUFFIXED_REASONS={sorted(V_VERIFY_PROOF_SUFFIXED_REASONS)} "
    "必须全部在 V_VERIFY_PROOF_REASONS 里 —— 带细则的码也是全集的一部分"
)

#: 未在册那一支的"命题页"占位（2026-11-02，业主：「V 签先放在 F 的手稿里，让 B 录入」）。
#:
#: `verifications.cold_start_prompt` 的 `## 命题（含完整假设）` 那一段在未在册时没有正文：
#: 不给它一句实话，提示词里会印一个「（空）」—— 模型会以为命题是空的，而不是"还没登记"。
#: 这一句同时把"签落在哪"说清楚（手稿），因为那一档的落点确实不是 `verifications/<号>.jsonl`。
UNREGISTERED_STATEMENT_PAGE = (
    "（这一条命题还没在册：命题正文读不到。你只按下面这份证明正文本身重读一遍，"
    "判它作为一份证明站不站得住；这一签会落在它所在的那一份手稿里，"
    "等 B 收录这条命题时随稿读到。）"
)


def _now_iso() -> str:
    """当前时刻（与全仓其它台账同一个写法：`S.now_iso()`）。"""
    return S.now_iso()

#: 工具层那条路要用的模型缝（与 F 的那一对是同一件事，单一来源在 `llmseam`）。
#:
#: 为什么需要它：`verify.verify_proof` 这条工具路径（M 派 `V.verify_proof` 时走的那条）
#: 拿不到 host 的装配上下文 —— 它只从 `verify_tools.register` 得到 store 与工作区根。
#: 不登记缝的话，"模型驱动那一趟"里的 V 会永远报 `judge_not_wired`，而那不是事实。
#: 默认 `None` = 没接线（环境里有 key 也不改变行为，与 `DEFAULT_LLM_LOOPS` 同一条纪律）。
#:
#: 逐角色的默认缝表在 `llmseam`（`set_role_seam` / `role_seam`）—— 那件事只实现一份，
#: 本文件只把角色 `"V"` 绑上去（下面两个下划线助手是纯绑定，没有自己的状态）。
#: 惰性 import 是必须的：`llmseam` 在 import 期会拉起 `agent_prompts` → `capabilities`
#: → 本模块，模块级 import 会成环。
def _v_role_seam() -> Any:
    from ..llmseam import role_seam

    return role_seam("V")


def _v_set_role_seam(llm: Any) -> None:
    from ..llmseam import set_role_seam

    return set_role_seam("V", llm)


#: `default_llm()` / `set_default_llm(llm)`：V 在工具层那条路上的缝。
default_llm = _v_role_seam
set_default_llm = _v_set_role_seam


class VerificationWiringError(RuntimeError):
    """这次审校没查成：没有模型缝，或拿回来的结论不合法。不是 `有毛病`。"""


#: 业主 2026-10-29：「temperature = 1.0（正常对话的数值）」——只给 V 的审阅调用。
#:
#: 为什么 V 用正常对话的温度而别的角色不动：V 的活是"读出这份证明站不站得住"，
#: 那是理解与判断，不是把同一句话复现三遍。而"可复现"这一条已经由连续 3 次
#: （`verifications.SIGN_STREAK_NEED`）＋ 秘书语义判定承担，不再靠把采样钉死。
#: 别的角色与秘书那一档仍是 `modelgw.DEFAULT_TEMPERATURE`（0.2），一个字节都没动。
REVIEW_TEMPERATURE = 1.0

#: 一次 `verify_proof` 最多替 F 连判几次：「动态等于门槛」（业主 2026-10-30 的两次裁定）。
#:
#: 改前这里是导入期定死的常量（`MAX_REVIEW_PASSES = int(VR.SIGN_STREAK_NEED)`），并按"上界
#: 与门槛是两个数"实现：门槛调高时判到上界就停、如实报"次数没到"。业主 2026-10-30 的第二次
#: 裁定逐字否掉了那个终局：「连判里面如果判出一回秘书语义分析认为是
#: 『有毛病』的，则直接打回了，连判终止」。于是上界与门槛是同一个数，而且「每趟现读」：
#: 循环跑满门槛时，clean 那一档必然已经攒够门槛票 ⇒ "要么签、要么打回"逻辑上必然命中
#: （跑完两头都没有 = 内部不一致，见 `verify_proof` 循环之后那一段）。
#:
#: 为什么不在导入期取一次就够：门槛是配置，默认参数/模块常量都是一次快照；快照与现读漂了
#: 之后，"判几次"会按旧门槛走、而"够不够发签"按新门槛判 —— 同一趟调用里两个数。
def review_pass_bound() -> int:
    """这一趟最多判几转 = 门槛现读（`verifications.SIGN_STREAK_NEED`）。

    这个上界就是一次送审内的轮数（2026-11-02 业主定稿：一次调用 = 连判三轮）。
    它不是跨两次送审累计的目标数：每一趟从第 1 轮重新数，台账历史一票都不带进来。
    """
    return int(VR.SIGN_STREAK_NEED)


#: 第 2 次起的提问末尾追加的那一句（"第几次"只加在提问的尾巴上）。
#:
#: 为什么不写进 system 前缀：`llmseam` 的跨 run 前缀缓存按 system 命中，把次数写进
#: 去等于每一趟换一个前缀 —— 三次调用三次 miss，而这一批改动恰好把调用次数乘以三。
#: 写成"追加"还有一个好处：前 `len(prompt)` 个字节三趟逐字相同，判据可以拿它量。
REVIEW_PASS_NOTE = (
    "\n\n（这是同一份证明的第 {n} 次独立重读：只按这一次读到的东西下结论，"
    "不要因为上一次怎么判就跟着判。）")


#: 穷举会审「缺材料」那一档的判据与文案，两支（在册 / 未在册）共用这一处。
#:
#: 判据只有一条：会审自己的结论是 `exhaustionreport.VERDICT_UNKNOWN`（缺材料时
#: `review()` 就这么判，`missing` 里点名缺哪一块）。为什么不是一个新常量：`review()` 是
#: 那一档的唯一产出方，在这里另立一份字面量等于给同一件事造第二个真身。
#:
#: 文案为什么必须共用：两支落的东西不同（在册支进 `verifications/<号>.jsonl` 之前就 return，
#: 未在册支进 `verifications/pending/<sha>.jsonl` 之前就 return），但读的人是同一批
#: （F 要知道补什么、B 要知道这一条没审成）。2026-11-01 的审计现场正是两支各写各的：
#: 在册支有护栏、未在册支没有 ⇒ 缺材料被折成「成立」写进 pending 台账。抄写两份文案迟早
#: 会漂，所以只留这一份。
MISSING_MATERIAL_REASON = "missing_material"


def missing_material_detail(verdict: Mapping[str, Any],
                            missing: list[str]) -> str:
    """「缺材料 ⇒ 没查成」那一句（在册 / 未在册两支逐字同一句）。

    返回空串 = 这一档不是缺材料（判据在调用方那一侧：`verdict_of(reviewed)["verdict"]`
    等不等于 `VERDICT_UNKNOWN`）—— 这样调用方只需要判一次，文案不会出现第二份。
    """
    from .. import exhaustionreport as _ER

    if str(verdict.get("verdict") or "") != _ER.VERDICT_UNKNOWN:
        return ""
    return (
        f"穷举型证据会审缺材料（{'; '.join(missing) or '没点名'}）⇒ 这一格"
        "没查成：既不判「成立」（缺材料不许判成立）、也不判「有毛病」"
        "（没有找到缺陷，不许按缺陷打回 F），台账里不留行。"
        "补上缺的那几块之后重新送审（会审的七项读数在 exhaustion_review 里）。")


def merge_dependency_audit(verdict: Mapping[str, Any],
                           audit: Mapping[str, Any] | None) -> dict[str, Any]:
    """把依赖面六项审计并进 V 的结论（纯函数；在册 / 未在册两支共用）。

    业主 2026-11-06：「引用未在册命题应该在 V 审阅时就被打回，轮不到 B」。
    这一格是那条口径的接线：`depsection.dependency_review` 逐条给出 error finding，
    这里把它们并进 `parse_verdict` 的同一形态（`verdict` / `defect_step` /
    `findings` / `unresolved_errors`），于是

    - `verdict` 改判「有毛病」⇒ 连判在第一转就停（V 自己的结论不是成立就是终局）；
    - `defect_step` 指到审计点的第一步（机械判据比模型的指针具体，覆盖它；
      模型自己的 findings 一条不丢，仍在清单里）；
    - `unresolved_errors` 重算 ⇒ `row_signable` 不放签（双重保险）。

    审计为空（`ok=True` / 没有 findings）⇒ 结论一个字不动（好稿不许被挡）。
    """
    out = dict(verdict)
    findings = [dict(f) for f in (out.get("findings") or [])]
    added = [dict(f) for f in ((audit or {}).get("findings") or [])]
    if not added:
        return out
    findings.extend(added)
    out["findings"] = findings
    out["verdict"] = "有毛病"
    out["unresolved_errors"] = sum(
        1 for f in findings if str(f.get("level")) == "error")
    step = (audit or {}).get("defect_step")
    if isinstance(step, int):
        out["defect_step"] = step
    why = str((audit or {}).get("why") or "")
    if why:
        out["why"] = (str(out.get("why") or "") + "；" + why).strip("；")
    return out


def _rejection_stands(standing: Mapping[str, Any]) -> bool:
    """这一份正文的台账读数是不是「已经被打回、还没改过字」（业主裁定 3 的准确含义）。

    业主逐字：「一次判有毛病时应该立即打回，不再起转，等下一次提交时重新从 0 转计数」。
    于是「打回」对同一份正文是终局：在 F 把正文改掉（sha 变了）之前，重送同一份
    不构成一次新的送审 —— 否则就是"再掷一次骰子"，而 `R-mk-infinite-94` 的 000034 正是
    这么签上的（v2 判 fault ⇒ 同一份正文重开一趟，v3–v5 三转 clean ⇒ 签块写 连续=3/3）。

    两档都算打回，与 F 侧 `agent_f.vsign.delivery_reading` 同一个谓词（不许两处各判一套）：

    - `rejected`：最近一签的秘书轴是 fault（含"那一趟属于打回之后又起转、已作废"那一档）；
    - `holding` + `secretary_fault`：V 的判词写「成立」、秘书读出了缺陷（老行的形态）。

    其余（`unsigned` / `stale` / `holding` / `signed` / `unreadable`）都不算打回：
    `signed` 另有 `already_signed` 那条短接先走，`unreadable` 是"没查成"。
    """
    state = str(standing.get("state") or "")
    if state == "rejected":
        return True
    return state == "holding" and bool(standing.get("secretary_fault"))


def _manuscript_digest(text: str) -> str:
    """被引命题正文的摘要（进提示词的那一份；截断规则沿用 `verifications` 那一套）。"""
    body = str(text or "").strip()
    limit = int(VR.CITATION_DIGEST_CHARS)
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + f"……（以下截断，全文共 {len(body)} 字）"


def _cited_manuscripts(root: Any, deps_rows: Sequence[Mapping[str, Any]]
                       ) -> dict[str, dict[str, Any]]:
    """被引命题的手稿（V 只读手稿之后，引用核实的正文与可引资格都从这里来）。

    每条被引 `stmt:<号>` 按两族约定命名在盘上找：`reports/f-proof-<号>.md` 先、
    `reports/b-proof-<号>.md` 后（F 的原稿 / B 的改写稿；谁在盘上用谁）。
    找不到 ⇒ `found=False`（读数里如实写"盘上没有这一条命题的手稿"），不退回台账。

    `signed` = :func:`vsigns.manuscript_sign_standing` 对这份稿现在这一份正文
    判出的 `signed`：可引门槛 `pre_theorem` 的口径就是"有 V 签"，所以这一格同时回答
    "够不够格被引"，不需要读 `statements.bits` 的等级。
    """
    from .. import depsection as _DS
    from .. import evidencebits as _EB
    from .. import vsigns as _VS

    wanted: list[str] = []
    for row in deps_rows:
        sid = str(row.get("stmt_id") or "").strip()
        if sid and sid not in wanted:
            wanted.append(sid)
    out: dict[str, dict[str, Any]] = {}
    for sid in wanted:
        tried: list[str] = []
        hit: tuple[str, str] | None = None
        for rel in (f"{_DS.MANUSCRIPT_DIR}/{_DS.MANUSCRIPT_STMT_PREFIX}{sid}.md",
                    f"{_DS.MANUSCRIPT_DIR}/b-proof-{sid}.md"):
            tried.append(rel)
            try:
                text = (Path(root) / rel).read_text(encoding="utf-8")
            except OSError:
                continue
            hit = (rel, text)
            break
        if hit is None:
            out[sid] = {
                "found": False, "manuscript": "", "statement_full": "",
                "statement_digest": "", "signed": False, "grade": "",
                "evidence_kind": "", "tried": tried,
                "why": ("盘上没有这一条命题的手稿（找过 "
                        + " / ".join(f"`{one}`" for one in tried) + "）"),
            }
            continue
        rel, text = hit
        full = _DS.statement_body(text)
        block = _VS.manuscript_sign_standing(
            text, proof_sha=VR.proof_sha(_DS.proof_body(text).strip("\n")),
            manuscript_path=rel)
        signed = str(block.get("state") or "") == "signed"
        out[sid] = {
            "found": True, "manuscript": rel, "statement_full": full,
            "statement_digest": _manuscript_digest(full),
            "signed": signed,
            "grade": ("pre_theorem" if signed else ""),
            "evidence_kind": (_EB.kind_from_grade("pre_theorem") if signed else ""),
            "why": str(block.get("why") or ""), "tried": tried,
        }
    return out


def _citation_material(*, rel: str, deps: Mapping[str, Any],
                       cited: Mapping[str, Mapping[str, Any]],
                       proof_no: int = 1) -> tuple[list[dict[str, Any]], str]:
    """V 的引用核实材料：手稿 `## 依赖` 四列表 + 每条被引命题手稿的正文 / 签。

    与改前的键集合相同（`stmt_id` / `paths` / `path_groups` / `dep_ids` /
    `statement_full` / `statement_digest` / `statement_missing` / `statement_label` /
    `evidence_kind` / `admissible` / `grade`），只多两格读数
    `manuscript` / `manuscript_missing`。判据本体仍在 `verifications.reconcile_citation_checks`
    与 `citation_gate`，这里只换材料来源。

    三态：`statement_missing` 明确保持 `False` —— V 读不到台账，"不在册"是它没查过的话；
    读不到被引手稿由 `manuscript_missing=True` + `admissible=False` 表达（机械改判
    `inadmissible`，挡住这一签），不冒充"没有引用"。
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in (deps.get("rows") or []):
        sid = str(row.get("stmt_id") or "").strip()
        if not sid:
            continue
        info = dict(cited.get(sid) or {})
        item = grouped.setdefault(sid, {
            "stmt_id": sid, "paths": [], "path_groups": [],
            "dep_ids": [], "statement_full": "", "statement_digest": "",
            "statement_missing": False, "statement_label": "", "evidence_kind": "",
            "admissible": False, "grade": "",
            #: 被引命题的手稿（V 读到的正文 / 签都在这一份上）；空串 = 盘上没有。
            "manuscript": str(info.get("manuscript") or ""),
            "manuscript_missing": not bool(info.get("found")),
        })
        line = int(row.get("line") or 0)
        group = int(row.get("path_group") or 1)
        locator = f"{rel}#L{line}" if rel and line else (rel or "手稿依赖段")
        item["paths"].append({
            "dep_id": locator,
            "used_by": f"stmt:{sid}#p{int(proof_no or 1)}",
            "path_group": group,
            "note": str(row.get("quote") or ""),
            "note_source": "## 依赖·引用",
            "status": "", "label": "",
            "quote": str(row.get("quote") or ""),
        })
        if group not in item["path_groups"]:
            item["path_groups"].append(group)
        item["dep_ids"].append(locator)
    out = list(grouped.values())
    for item in out:
        info = dict(cited.get(str(item["stmt_id"])) or {})
        item["statement_full"] = str(info.get("statement_full") or "")
        item["statement_digest"] = str(info.get("statement_digest") or "")
        item["admissible"] = bool(info.get("signed"))
        item["grade"] = str(info.get("grade") or "")
        item["evidence_kind"] = str(info.get("evidence_kind") or "")
        if item["manuscript_missing"]:
            # 读不到稿时给一句实话：不许让提示词把它读成"被引命题的正文是空的"。
            item["statement_digest"] = (
                "（V 只读手稿：盘上找不到这一条命题的手稿，读不到它的正文与签）")
        item["path_groups"] = sorted(item["path_groups"])
    out.sort(key=lambda it: (it["stmt_id"], it["path_groups"]))
    return out, ""


def _manuscript_facts(rel: str, raw: str, deps: Mapping[str, Any],
                      block: Mapping[str, Any] | None = None) -> str:
    """给 V 提示词的「只读读数」（2026-11-08：只剩手稿事实，不读命题台账）。

    I12 要求"对象 + 只读读数"；对象是一份手稿，所以读数也只说这份稿：
    哪些节读到了、依赖面几行、签块是什么状态。命题的 `kind` / `status` /
    `evidence_kind` 是 B 的登记口径（等级也是 B 现算的），V 判"这份证明对不对"
    不需要它们。
    """
    from .. import depsection as _DS

    lines: list[str] = []
    rel_text = str(rel or "").strip()
    lines.append(f"- 手稿：`{rel_text}`" if rel_text else "- 手稿：（这一趟没有给 proof_manuscript）")
    statement = _DS.statement_body(raw) if raw else ""
    lines.append("- `## 命题`：" + (f"读到（{len(statement)} 字）" if statement
                                   else "没读到（这一份稿没有命题页）"))
    body = _DS.proof_body(raw) if raw else ""
    lines.append(f"- `## 证明`：{len(body.strip())} 字")
    rows = list(deps.get("rows") or [])
    groups = sorted({int(r.get("path_group") or 1) for r in rows})
    lines.append(f"- `## 依赖`：{len(rows)} 行"
                 + (f"（路径组 {'、'.join(str(g) for g in groups)}）" if groups else ""))
    sign = dict(block or {})
    state = str(sign.get("state") or "")
    if not sign:
        lines.append("- 签块：（这一趟没有读签块）")
    elif state == "signed":
        lines.append(f"- 签块：已签（正文 sha {str(sign.get('proof_sha256') or '')[:12]}…，"
                     f"连续 {sign.get('streak')}/{sign.get('need')}）")
    else:
        lines.append(f"- 签块：{state or 'unsigned'}（{sign.get('why') or '未签'}）")
    return "\n".join(lines)


def _ledger_row_for_sha(root: Any, statement_id: str, sha: str) -> dict[str, Any]:
    """V 自己台账里盖住这一份正文 sha 的最近一行（读不到 / 没有 ⇒ 空 dict）。

    2026-11-08：V 不再读命题行，但"这一份稿已经签过"的短接仍要把那一签当初读到的
    引用结论 / findings 回放出来（返回值不许比真身更空）。来源只能是 V 自己的台账
    （`verifications/<号>.jsonl`），按正文 sha 认，不按命题行的第 3 位认。
    """
    sid = str(statement_id or "").strip()
    if not sid or not str(sha or "").strip():
        return {}
    try:
        rows, _bad = VR.list_verifications(root, statement_id=sid, limit=None)
    except (OSError, VR.VerificationError):
        return {}
    hit = [r for r in rows if str(r.get("proof_sha256") or "") == str(sha)]
    return dict(hit[-1]) if hit else {}


def _pending_ledger_ref(row: Mapping[str, Any]) -> str:
    """pending 台账行 ⇒ 锚点 `verifications/pending/<key>.jsonl#<verification_id>`。

    为什么单独一格（2026-11-05 晚）：没号先签那一档的"背书"就是这一串，签文件、签块、
    返回值三处都要指向同一行 —— 三处各拼一次，拼法迟早分家（`object_sha256` 与
    `proof_sha256` 谁在前、`u-` 前缀带不带）。全仓只在这里拼。
    """
    key = str(row.get("object_sha256") or row.get("proof_sha256") or "").strip()
    vid = str(row.get("verification_id") or "").strip()
    if not key or not vid:
        return ""
    return f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/{key}.jsonl#{vid}"


def _passes_with_tickets(passes: list[dict[str, Any]],
                         rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把每一转的读数与它刚落下的那一行 pending 台账并成一张真票。

    没号先签那一档的三票必须是 `verification_id` / `at` / `proof_sha256` 三格齐全
    （业主 2026-11-05 晚：「三票有空/不齐 ⇒ 拒」）。改前这一档的 `passes` 只有
    `pass` / `verdict` / `unresolved_errors` 三格，三格全空的占位一样的形状 ——
    `vsigns.sign_object_gate` 的 `passes_incomplete` 因此永远会拒它。
    这里按同一趟的第 i 转配第 i 行（`pending_rows` 的追加序 = 转序）。
    """
    out: list[dict[str, Any]] = []
    for i, one in enumerate(passes):
        ticket = dict(one)
        row = dict(rows[i]) if i < len(rows) and isinstance(rows[i], Mapping) else {}
        ticket["verification_id"] = str(row.get("verification_id") or "")
        ticket["at"] = str(row.get("at") or "")
        ticket["proof_sha256"] = str(row.get("proof_sha256") or "")
        out.append(ticket)
    return out


def _unregistered_secretary_judge(got: Mapping[str, Any]) -> dict[str, Any]:
    """未在册那一支的轴读数：原样带到返回值顶层（与在册支同形）。

    为什么要有这一格（2026-11-06）：这一支的 `checked` / `axis` / `source` /
    `defect_step` / `reason` 此前只躺在 `review_passes` 与 pending 台账行上，调用方
    从返回值顶层拿不到"轴是什么、谁判的" —— 业主的规矩是「读数不许丢」。在册那一支
    的顶层早就有 `secretary_judge`（`verify_proof` 的初值里也有，键无条件存在）；
    这一格让两支同形，而不是让未在册那支的读者自己去翻明细。

    源只有一处：`_review_unregistered_prose` / `_review_unregistered_exhaustion`
    返回的 `secretary_judge`（它们与写进 pending 台账行的是同一份判定）。
    `passes` 那一支只是兜底：某条"没查成"的早退路径没有 judgment 时，至少把最后一转
    的轴与步号读出来；两者都没有 ⇒ 空字典（"这一趟没有轴可报"，不是 clean）。
    """
    judge = dict(got.get("secretary_judge") or {})
    if judge:
        return judge
    passes = [p for p in (got.get("passes") or []) if isinstance(p, Mapping)]
    last = dict(passes[-1]) if passes else {}
    if not last:
        return {}
    axis = str(last.get("axis") or "")
    return {
        "checked": bool(axis),
        "axis": axis,
        "decision": str(last.get("verdict") or ""),
        "reason": str(last.get("reason") or ""),
        "source": str(last.get("source") or ""),
        "defect_step": last.get("defect_step"),
    }


def fail_closed_sign_issuance(*, statement_id: str = "", proof_no: int = 0,
                              reason: str = "") -> dict[str, Any]:
    """`verify_proof` 初值里 `sign_issuance` 那一格的 fail-closed 形状（键无条件存在）。

    ## 为什么要有它（2026-11-08，业主让核的那条）

    改前初值是 `{}`：`verify_proof` 的每一条早退路径（`bad_statement_id` /
    `bad_proof_no` / 手稿闸 / 未在册那几条闸…）都直接 `return out`，于是返回值里
    `sign_issuance` 是空字典 —— 而工具声明（`tools/verify_tools.py` 的 `returns=`）
    写着这一格的键无条件存在。按 `sign_issuance["checked"]` 读的调用方（V 自检就是
    这么读的：`clean["sign_issuance"]["checked"]`）当场 `KeyError`。

    修法只给**初值**一套完整的 fail-closed 键，不改声明那句话：键集合取两处实现的
    并集（`Secretary.decide_sign_issuance` 的初值 + `_terminal_issuance` 的返回），
    值全是"没走到签发"：`checked=False` / `issue=False` / `issued=False`，`reason`
    说清这是早退，不是"不签发"那一档。

    三态纪律：`checked=False` 不是"可以签"，也不是"判过、不签发" —— 它是"这一趟
    没走到签发那一步"。任何一条真路径仍会整格覆盖它（`out["sign_issuance"] = ...`），
    所以这里只影响早退。
    """
    return {
        "checked": False, "issue": False, "issued": False, "landed": False,
        "decision": "",
        "writeback": {}, "streak": 0, "need": int(VR.SIGN_STREAK_NEED),
        "streak_ok": False, "projected": 0, "same_sha": False, "state": "",
        "reason": (str(reason or "")
                   or "这一趟没走到签发那一步（早退）⇒ 没有发签：`checked=False` "
                      "不是「可以签」，也不是「不签发」这一档"),
        "within_call": None, "review_call": "", "ledger_streak": 0,
        "basis": [], "reading": {}, "cost": {}, "material": {},
        "statement_id": str(statement_id or ""), "proof_no": int(proof_no or 0),
    }


class AgentV:
    """验证者。三个 handler 与 `specs/v.py` 的 `handler_name` 逐字同名。

    `llm` 是一个"能回答一段提示词的模型缝"：给 `LlmSeam`（有 `.ask`）、
    给一个 client（有 `.complete`）、或给一个可调用对象都行。不给就是没接线 ——
    `verify_proof` 会如实报 `judge_not_wired`，绝不用确定性文本假装审过
    （审校是一件只有模型能做的事，没有它就没有结论）。
    """

    def __init__(self, store: Any, *, workspace_root: str | Path | None = None,
                 llm: Any = None, config: Mapping[str, Any] | None = None,
                 log: Callable[[str], None] | None = None,
                 secretary: Any = None) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        root = workspace_root or getattr(store, "root", None) or "."
        self.workspace_root = Path(root).resolve()
        self.llm = llm
        self.actor = str(self.cfg.get("actor") or DEFAULT_VERIFIER)
        self.log = log
        #: V 自己的秘书（业主 2026-10-29：发不发签由它持有）。
        #:
        #: 为什么它有一个构造形参：`agent_loop.run_role` 那条路在装配期就已经造好了一名
        #: 秘书（并按名册绑了实例）—— 那一条应当原样交进来，而不是在这里另造一个
        #: （两个对象 = 两本台账）。不给 ⇒ 由 :meth:`_secretary` 惰性装配：
        #: `draft/125` §三点名的"工具路径造不出秘书"那个缺口，落点就在这一处
        #: （工具层 `tools/verify_tools.py` 是 FC-27，不许改；`AgentV` 不是）。
        self.secretary = secretary
        #: 惰性装配只试一次（并且试过就要记住）："没缝"不是一个每签都要重试的错误，
        #: 而"没试过"与"试了没成"必须在读数上分得开。
        self._secretary_tried = secretary is not None
        #: 装配读数（懒装配失败/没缝时的那一句为什么；空串 = 没出问题或还没试）。
        self.secretary_problem = ""
        self.logs: list[str] = []

    # ------------------------------------------------------------------ 内部

    def _emit(self, message: str) -> None:
        self.logs.append(message)
        if self.log is not None:
            self.log(message)

    def _seam(self) -> Any:
        """这次审校用哪个模型缝：显式给的最优先，否则按角色现造一个。

        现造的那一个不抛：`LlmSeam.for_role` 在没有 key 时给出 `wired=False` 的缝，
        而 `ask` 会返回 `problem="judge_not_wired"` —— 三态纪律要的正是这个：
        "没接线"是一条读数，不是一次异常。
        """
        if self.llm is not None:
            return self.llm
        from ..llmseam import LlmSeam
        from ..tokenmeter import TokenMeter

        return LlmSeam.for_role("V", session_root=self.workspace_root,
                                meter=TokenMeter(self.store) if self.store is not None else None)

    def _ask(self, prompt: str) -> tuple[str, str]:
        """问一次模型。返回 `(文本, 失败原因)`；失败原因空 = 拿到了文本。"""
        seam = self._seam()
        if seam is None:
            return "", "judge_not_wired"
        try:
            if hasattr(seam, "ask"):
                # 业主 2026-10-29：V 的审阅调用按正常对话的温度问（`REVIEW_TEMPERATURE`
                # = 1.0）；别的角色没有这一格，仍是 `modelgw.DEFAULT_TEMPERATURE`（0.2）。
                call = seam.ask(prompt, task_id="", temperature=REVIEW_TEMPERATURE)
                problem = str(getattr(call, "problem", "") or "")
                text = str(getattr(call, "text", "") or "")
                if problem and not text:
                    return "", problem
                return text, ("" if text else "empty_reply")
            if hasattr(seam, "complete"):
                reply = seam.complete(prompt)
                if isinstance(reply, Mapping):
                    return str(reply.get("text") or reply.get("content") or ""), ""
                return str(reply or ""), ""
        except Exception as exc:  # noqa: BLE001 —— 缝的异常是"没查成"，不是"有毛病"
            return "", f"{type(exc).__name__}: {exc}"
        return "", "judge_not_wired"

    # ---------------------------------------------------- 秘书（业主 2026-10-29）

    def _secretary(self) -> Any:
        """这一趟的 V 秘书（没有 ⇒ `None`，理由在 `self.secretary_problem`）。

        ## 为什么装配点在这里（`draft/125` §三的那个缺口）
        V 走循环时 `agent_loop.run_role` 已经装配好秘书并交进来；V 走工具路径
        （M 派 `V.verify_proof`）时，工具层 `tools/verify_tools.py:_agent_v` 只拿得到
        store 与工作区根 —— 它造不出秘书，而它是 FC-27（禁改区），不许为了接线改它。
        所以装配落在 `AgentV` 自己这一层：它是被那一处构造的，不是禁改区。

        ## 没缝 ≠ 有问题
        `secretary.for_role_wired` 在设置里没有秘书那一档 key 时不装空缝
        （那会把"从来没有判断面"写成"试过了、没成"）⇒ 这里的秘书 `seam is None`，
        `judge` / `decide_sign_issuance` 会如实报 `checked=False`。业主口径：
        装配没接上时秘书判定必须报 `checked=False`，且不发签（`draft/125` §三）。
        """
        if self.secretary is not None:
            return self.secretary
        if self._secretary_tried:
            return None
        self._secretary_tried = True
        try:
            from .. import secretary as _SEC

            got = _SEC.for_role_wired("V", root=self.workspace_root, store=self.store)
        except Exception as exc:  # noqa: BLE001 —— 造不出来是"没有秘书"，不是"没问题"
            self.secretary_problem = (f"V 的秘书装配失败（{type(exc).__name__}: {exc}）⇒ "
                                      "这一趟没有秘书：判定与发签都按 checked=False 读")
            self._emit(f"verify_proof：{self.secretary_problem}")
            return None
        self.secretary = got
        if not str(getattr(got, "seam", "")):
            self.secretary_problem = (f"V 的秘书没有判断面（{got.model_source or '没有模型缝'}）"
                                      "⇒ 判定与发签按 checked=False 读（不是「没问题」）")
        return got

    def _judge_v_reply(self, reply: str, verdict: Mapping[str, Any],
                       no: int, *, statement_id: str = "") -> dict[str, Any]:
        """问秘书：V 这段回复有没有指出缺陷（业主 2026-10-29 的 B 段）。

        材料只给 V 的回复正文 + 这一签的 `verdict` / `defect_step`；不给 F 的证明
        （I12：V 的秘书读叙述本来就被 `may_read_narrative` 禁，这里不开那个口子）。

        轴只有两档（业主 2026-10-30 第三次裁定：「只要不是完全没毛病都叫有毛病」）：
        `clean` / `fault`。拿不准、只挑出一个小记号问题、只说"我没逐行验证"——都是 fault
        （`secretary.V_REPLY_AXIS` 只有两格：词表外的一律"不采信" ⇒ `checked=False`）。

        没有秘书 / 没判断面 ⇒ `checked=False` + `axis=""`：那是"没查成"，不是一种判定，
        更不是"没问题"（连续计数里既不算票、也不清零）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "axis": "", "unwired": True, "decision": "",
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 语义判定没查成（不是「没问题」）")}
        try:
            return sec.judge_v_reply(reply=str(reply or ""),
                                     verdict=str(verdict.get("verdict") or ""),
                                     defect_step=verdict.get("defect_step"),
                                     statement_id=str(statement_id or ""),
                                     proof_no=no,
                                     task_id=str(self.cfg.get("task_id") or ""))
        except Exception as exc:  # noqa: BLE001 —— p247：秘书抛异常不许回退成字面判
            return {"checked": False, "axis": "", "unwired": False, "decision": "",
                    "reason": (f"秘书这一问抛异常（{type(exc).__name__}: {exc}）⇒ "
                               "这一转的轴没查成（checked=False，不按 V 的判词字面补判）")}

    def _wash_v_reply(self, reply: str, verdict: Mapping[str, Any], no: int, *,
                      statement_id: str = "") -> dict[str, Any]:
        """问秘书：把这段意见洗成能转达给 F 的文本（业主 2026-10-29 的 C 段）。

        秘书不在场 ⇒ `checked=False, refused="secretary_unavailable"`，且不返回原文
        （`wash_v_reply` 的纪律：洗不出来就不输出原文）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "washed": False, "text": "", "findings": [],
                    "dropped": [], "refused": "secretary_unavailable",
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 洗不出来（不输出原文）")}
        return sec.wash_v_reply(reply=str(reply or ""),
                                verdict=str(verdict.get("verdict") or ""),
                                defect_step=verdict.get("defect_step"),
                                statement_id=str(statement_id or ""), proof_no=no,
                                task_id=str(self.cfg.get("task_id") or ""),
                                label=str(verdict.get("label") or ""))

    def _decide_sign_issuance(self, statement_id: str, proof_text: str, no: int,                              verdict: Mapping[str, Any], *,
                              row: Mapping[str, Any] | None = None,
                              within_call: int | None = None,
                              review_call: str = "") -> dict[str, Any]:
        """问秘书：这一签发不发（业主 2026-10-29 的 A 段，追加口径：落盘也由它做）。

        `row` 是 `record_verification(flip=False)` 刚落下的台账那一行：秘书据此知道
        "这一签已经在台账上了"（连续次数不用再加一票），并在判发之后由它自己调
        `sign_statement(append_ledger=False)` 翻位。

        `within_call`（2026-11-02 定稿）是这一趟送审内的第几轮：给了它，秘书那一侧
        的地板只看这个数，台账尾部的历史连续数只作读数 —— 跨两次送审绝不累计。
        `review_call` 是这一趟的调用 id，随发签读数落到签文件的 `passes` 里
        （"三票同源"可读）。

        没有秘书 ⇒ `checked=False, issue=False, issued=False`：不放签。这一句是
        fail-closed 的那一半（`draft/125` §三：「装配没接上时，秘书判定必须报
        checked=False」；追加口径之后它是主路径：发签权在秘书手上，秘书不在场就等于
        不能发签）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "issue": False, "issued": False, "streak": 0,
                    "projected": 0, "need": VR.SIGN_STREAK_NEED, "streak_ok": False,
                    "decision": "", "writeback": {}, "landed": False,
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 没有人发这一签（不放签）")}
        return sec.decide_sign_issuance(statement_id=statement_id, proof_text=proof_text,
                                        proof_no=no, verdict=verdict, row=row,
                                        within_call=within_call,
                                        review_call=review_call,
                                        task_id=str(self.cfg.get("task_id") or ""))

    # ---------------------------------------------------- 引用核实（业主 2026-10-26）

    def _citation_admissibility(self, grade: str) -> bool:
        """被引命题的等级够不够格被引（2026-11-05：门槛读等级，`pre_theorem` 及以上）。

        为什么单独一个具名方法：这一格是"可引判据"的唯一落点，而它必须能被打桩 ——
        判据里的反真空就是把它打成恒放行 / 恒拒绝，看那两条是不是跟着红。
        真身只有一处（`verifications.citation_grade_admissible` → 转发
        `depsection.citation_level_allowed`，门槛字面量只在 `depsection.CITATION_MIN_LEVEL`
        一处），这里不抄第二份词表、也不读历史档位。
        """
        return VR.citation_grade_admissible(grade)

    def _citation_checks(self, checks: list[dict[str, Any]],
                         material: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """引用核实的定稿：模型给的那几档只是原料（覆盖 / 档位 / 不在册在这里定）。

        同样是可打桩的一格：把它打成恒 `consistent`，负控（引错、引强）必须跟着红 ——
        否则那几条判据量的就不是"引用真的被核过"，而是"模型说了什么"。
        """
        return VR.reconcile_citation_checks(checks, material)

    def _dependency_audit(self, manuscript_text: str,
                          cited: Mapping[str, Mapping[str, Any]] | None = None
                          ) -> dict[str, Any]:
        """依赖面的机械审计（六项逐条核）—— V 是第一道防线（业主 2026-11-06）。

        判据本体在 `depsection.dependency_review`（与 B 的登记入口、F 的可引池同源）；
        这里只负责"读一次手稿的 `## 依赖`"与"没有稿就跳过"。

        2026-11-08（V 只对手稿负责）：可引资格换成被引命题的手稿（盘上那一份稿、
        且稿上有盖住它现行正文的 V 签）—— `admissibility=manuscript_citation_resolver`。
        ①② 不再说"未在册"（V 读不到册，说那句话就是编），改成"盘上没有这一条命题的
        手稿 / 手稿上没有签"；④⑤⑦（表与正文一致 / 步号 / 引文归属）仍用被引手稿的
        `## 命题` 合成行来核。读不到稿 ⇒ 如实说 `checked=False`，不冒充"核过、没问题"。
        """
        from .. import depsection as _DS

        if not str(manuscript_text or "").strip():
            return {"checked": False, "ok": True, "findings": [],
                    "defect_step": None, "why": "（这一趟没有手稿文本 ⇒ 依赖面不核）"}
        rows: list[dict[str, Any]] = []
        #: 被引手稿的正文行（供 ⑦ 引文归属 / ④⑤ 的集合核对用；只含读到的那些）。
        for sid, info in (cited or {}).items():
            if bool(dict(info).get("found")):
                rows.append({"stmt_id": str(sid),
                             "statement_full": str(dict(info).get("statement_full") or "")})
        #: 可引资格也走可打桩的那一格（`_citation_admissibility`）：材料那一侧与依赖面
        #: 审计必须同一个答案，否则"打桩恒放行"只会松开引用闸、松不开审计 ⇒ 判据两套。
        resolved = {str(sid): dict(info) for sid, info in (cited or {}).items()}
        for sid, info in resolved.items():
            info["signed"] = (bool(info.get("found"))
                              and bool(self._citation_admissibility(
                                  str(info.get("grade") or ""))))
        return _DS.dependency_review(
            manuscript_text, rows,
            admissibility=_DS.manuscript_citation_resolver(resolved))

    # ------------------------------------------------------------------ 三个动作

    def verify_proof(self, statement_id: str = "", proof_text: str = "",
                     readonly_facts: str = "", proof_no: Any = 1,
                     proof_manuscript: str = "",
                     **kw: Any) -> dict[str, Any]:
        """把一份证明整体重读一遍，落一行验证台账（`v-NNNN`）。

        ## 证明号与正文必须绑在一起（2026-10-22 审计第 2 条）

        `proof_no` 说"审的是第几份"，送进提示词的正文必须是那一份的正文：
        参数没给正文 ⇒ 取 `verifications.proof_text_of(该行, proof_no)`；参数给了正文 ⇒
        它必须与盘上那一份是同一份（sha 相同），否则拒（`proof_text_mismatch`）——
        记到 `#pN` 上会把 sha 与证明号错配。改前这里是 `if not text: text =
        hit["proof_text"]`：说"审 #p2"却把 #p1 的正文送进提示词，而 sha 记在 #p2 头上，
        于是"#p1 没被牵连"与"#p2 真的审过"两句话同时是假的。
        不给证明号 ⇒ canonical（`#p1`）；给了但认不出（`0` / `'abc'` / `2.0`）⇒
        `checked=False, reason="bad_proof_no"`（改前 `or 1` 静默折成 `#p1`：签错一份
        证明，台账上照样写着 `verdict=成立`）；命题的证明清单里没有 `#pN` ⇒
        `checked=False, reason="no_such_proof"`；那一份在、正文空 ⇒ `no_proof_text`。
        以上四条都不落台账行。

        ## 台账那一行有没有落地（2026-10-22 审计第 1 条）

        写位失败可能整笔回滚，而回滚（`verifications._rollback_append`）会把台账那一行
        一起抹掉。改前返回值只看 `verdict` ⇒ 台账 0 字节而返回说"签住了第 3 位"。
        现在只看 `record_verification` 返回行上的 `checked`：没落地 ⇒ 本方法
        `checked=False`、`signed_bit3=False`、`reason` 逐字写明"台账那一行被撤回 /
        没写成"，调用方据此知道必须重签（`review_write.re_sign_required`）。

        ## 键集合在三条返回路径上完全相同（与 `verify.evidence_for` 同一纪律）

        "没查成"（`checked=False`）不是工具失败（同 `verify.check_formal` 的`no_backend`：那是没查成，不是查了没过）⇒ 照样
        `ok` 返回、键一个不少，由 `checked` / `reason` 说出真相。少给键会让下游把"这一格没有读数"读成"这一格是零"。

        ## 一次调用里连判几次：只有两种终局（业主 2026-10-30 的两次裁定）

        "连续 3 次没问题"是 V 判完接着再判，不是 F 交三次。所以本方法自己问模型最多
        :func:`review_pass_bound` 次（= 门槛现读，同一份正文、同一个 `proof_no`），每一转
        各落一行台账、各问一次秘书。终局只有两种：签上了（连续 `need` 转 clean ⇒ 秘书发签）
        或打回了（任一转判出 fault / 结论不是成立 ⇒ 那一转就是终局，立刻停）。
        "跑完而两头都没有"报内部不一致（`checked=False`），不当成一条终局。
        逐次读数在返回值的 `review_passes` 里（每项给 `pass` / `axis` / `decision` /
        `streak` / `need` / `streak_ok` / `issue` / `issued` / `verdict` /
        `verification_id` / `review_call` / `terminal`），而 `secretary_judge` /
        `sign_issuance` 仍是"最后一转"那两格。

        ## 2026-11-02 定稿：这一趟的轮数只在这一趟里数（跨送审绝不累计）
        每一趟都有一个新的 `review_call`；三行台账的 `review_pass` 是 1 / 2 / 3。
        发签地板（`sign_issuance.within_call`）只看这个趟内数；台账尾部历史连续数
        （旧台账的 `legacy_rows`）只作历史读数，不参与新签判断。于是"上一趟留了 2 行
        clean、这一趟第 1 轮 clean"不再凑成一张签 —— 业主逐字：「不允许跨两次送审
        累计成功数」。

        ## 已经签过的命题不再送审（2026-10-31）

        命题行上这一份证明的第 3 位已经为真 ⇒ 这一趟不进连判循环，直接返回
        `reason="already_signed"`（台账零行、模型零问）；改稿之后 sha 变了就不再短接、
        照常重审。现场见 `draft/142` §四；返回值为什么必须回放那一签的读数、以及短接
        为什么必须落在这个位置，见下面那一段注释。
        """
        del kw  # 声明层没有别的参数；多给的键在这里不静默生效
        out: dict[str, Any] = {
            "checked": False,
        "kind": "",          # 三条返回路径键集合一致（没查成时空串）
            "statement_id": str(statement_id or "").strip(),
            "verification_id": "",
            "verdict": "",
            "defect_step": None,
            "findings": [],
            "unresolved_errors": 0,
            "proof_sha256": "",
            "proof_no": None,
            "proof_chars": 0,
            "signed_bit3": False,
            "reviewed_by": {},
            "bits": {},
            # 写回读数（`statement_writeback`）：成功支与"台账那行没落地"那一支都会给，
            # 而"没查成"那几条路径改前没有这一格 ⇒ 三条返回路径的键集合不同，
            # 声明只能二选一（要么模型看不见这一格，要么声明里多一格永远不出现的）。
            # 三态纪律取法：键在这里就存在，`{}` = 这一趟没有写回可报。
            "review_write": {},
            "ledger": "",
            "reason": "",
            "detail": "",
            # 穷举型证据会审那一档的四格（普通逐行走查路径上它们是空的，但键要在：
            # "这一格没有读数"与"这一格是空字符串"必须由键的存在区分开）。
            "exhaustion_review": {},
            "signer": "",
            "proof_authors": [],
            "report_path": "",
            "checks": [],
            "missing": [],
            # 引用核实那一档（业主 2026-10-26）：材料（被引命题 + 正文摘要）/ 逐条结论 /
            # 签字前置读数。三条返回路径键集合相同 ⇒ 它们必须在初值里就存在。
            "citations": [],
            "citation_checks": [],
            "citation_gate": VR.citation_gate([]),
            # 业主 2026-10-29 的两格：秘书语义判定（B 段，两档）与发签决定（A 段）。
            # 键无条件存在（"没判成"由 `checked=False` 说，不靠少给键来表达）。
            "secretary_judge": {},
            #: 2026-11-08：初值是一套**完整的 fail-closed 键**，不是 `{}` —— 早退路径
            #: 直接 `return out`，空字典会让按 `sign_issuance["checked"]` 读的调用方
            #: 当场 KeyError（V 自检就是这么读的）。键集见 :func:`fail_closed_sign_issuance`。
            "sign_issuance": fail_closed_sign_issuance(
                statement_id=str(statement_id or "").strip()),
            # 业主 2026-10-30：这一趟自己连判了几次、每一转的判定档与连续次数。
            # 同理无条件存在（一次都没判成时是空数组 —— "没判过"与"判了 0 转"不靠少给键分）。
            "review_passes": [],
        }
        # ---- 2026-11-02 业主定稿：一次送审 = 同一次调用内连判三轮，跨调用绝不累计 ----
        #
        # 这一趟的调用 id：这一趟落下的每一行台账都带同一个 `review_call`，行上再带
        # `review_pass`（第几轮）。新签只认同一个 `review_call` 内 `review_pass=1..need`
        # 的那几行；旧台账没有这两个标记 ⇒ 历史形态（`legacy_rows`），不参与新签判断。
        # 只在内存里发，不改任何盘上格式；`round` 仍是全局台账行号，不动。
        review_call = uuid.uuid4().hex[:12]
        sid = out["statement_id"]
        # ---- 空号是合法的一种说法：「这一条还没在册」（2026-11-02）----
        #
        # 业主 2026-11-02（逐字）：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或
        # 命题收录时读到」。改前空号一律 `bad_statement_id` ⇒ F 只能等 B 登记拿到号才
        # 送得成审 ⇒ F 的交差挂在 B 的动作上。现在空号走「未在册手稿」那一支：读
        # `proof_manuscript` 指的那一份稿、三转干净就把签块盖回稿里。
        # 非空却打不成合法号仍然是 `bad_statement_id`（调用方写错了，不许折成"未在册"）。
        if not S.is_valid_id(sid) and sid:
            out["reason"] = "bad_statement_id"
            out["detail"] = (f"命题号必须是 {S.ID_DIGITS} 位十进制（旧数据里的 4 位号仍可读），"
                             f"收到 {statement_id!r}")
            return out
        # 证明号先判：没给（`None` 或缺省）⇒ canonical；给了但认不出 ⇒ 拒。
        # 改前 `proof_no=0` 一路被 `or 1` 折成 #p1，"号给错了"没有任何读数。
        try:
            no = VR.proof_no_strict(proof_no)
        except VR.VerificationError as exc:
            out["reason"] = "bad_proof_no"
            out["detail"] = f"{exc}；这一格没查成，台账里不留行"
            self._emit(f"verify_proof({sid})：{exc} —— 没查，不落台账行")
            return out
        out["proof_no"] = no
        # `sign_issuance` 的初值在号判完之后补上这两格：早退路径（手稿闸 / 未在册那几条）
        # 交回的 fail-closed 读数也要带对号与命题号，而不是空/0。
        out["sign_issuance"]["statement_id"] = sid
        out["sign_issuance"]["proof_no"] = int(no)
        text = str(proof_text or "")
        #: 这一趟签的载体（工作区相对路径；空串 = 没有手稿）。在册那一支由参数给、
        #: 随台账行交给 `sign_statement`（签块落回同一份稿）；未在册那两支各自处理。
        manuscript_rel = ""
        #: 这一趟读到的手稿全文（六项依赖面审计要用 `## 依赖` 段；空串 = 没有稿）。
        manuscript_raw = ""
        statement_full = ""
        # ---- 2026-11-08（业主：「V 现在只对手稿负责，不该看台账了」）----------------
        #
        # 在册/未在册的分岔只看 `statement_id` 是否为空：空号走未在册四支（行为不变），
        # 非空号走手稿主路 —— 不查 `statements`。命题在不在册、第几份证明、现等级
        # 都不再是 V 的输入（业主：「第几份证明、什么等级都是 B 秘书录入时关心且需负责的」）。
        # 命题正文从稿的 `## 命题` 读，依赖面从 `## 依赖` 读，被引命题的正文与
        # 可引资格从它们各自的手稿读（`_cited_manuscripts`）。
        if not sid:
            # ---- D-34（2026-10-24）：命题还没在册时 V 的签不许丢 ------------------
            #
            # r34b 的真机现场：`statements` 0 行，V 审完判「成立」，而
            # `record_verification` 要一个合法命题号才写得出台账 ⇒ 那一签没有落点。
            # 业主的模型是"V 的签＝盖章"，盖章不该因为"那一页还没装订进册"而作废 ⇒
            # 这一档走 `verifications/pending/<sha>`，B 登记之后按同一个 sha 认领。
            # ---- 2026-11-03（业主：「E 在数值证明拿 V 签的时候流程和 F 一模一样」）----
            #
            # 未在册的穷举证明先走 E 那一支（三轮机械会审 + 收方秘书落签块），
            # 与下面 F 的散文那一支同一套（同一份手稿形状 / 同一次 `vsigns.issue` /
            # 同一个 `land_unregistered_sign`）。返回 None = 这一份不是穷举证据、
            # 或盘上没有 E 的手稿 ⇒ 退回下面两支（pending / 散文），一个字节不写。
            # 2026-11-04（业主裁定 A 甲）：B 的改写手稿若没带命题号（B 只交稿），
            # 也走「签在稿上」这一支。
            b_got = self._review_b_manuscript(
                text=text, manuscript=proof_manuscript, no=no)
            if b_got is not None:
                return self._finish_unregistered(out, no=no, got=b_got)
            exhaust = self._review_unregistered_exhaustion(
                text=text, manuscript=proof_manuscript, no=no)
            if exhaust is not None:
                return self._finish_unregistered(out, no=no, got=exhaust)
            pending = self._review_without_statement(text=text, no=no)
            if pending is not None:
                return self._finish_unsigned_review(out, statement_id=sid, no=no, got=pending)
            # ---- 2026-11-02 / 2026-11-05 晚（业主：「V 就不能假定有号，全签在稿上，
            #      B 侧录入时从稿拿签。这是已有口径」）----
            #
            # 未在册 + 给了手稿（或正文）⇒ 走「读稿审、签块盖回手稿」那一支。
            # 落点有两处、互不替代：签块在 `reports/(f|b|e)-proof-<数字>.md` 上，
            # 独立背书在 `verifications/pending/<正文 sha>.jsonl`（三转三行）。
            unregistered = self._review_unregistered_prose(
                text=text, manuscript=proof_manuscript, no=no)
            if unregistered is not None:
                return self._finish_unregistered(out, no=no, got=unregistered)
        else:
            # ---- 2026-11-04（业主裁定 甲）：命题的证明必须由一份手稿承载 ----------
            #
            # 业主逐字：「V 审在册命题时也必须给手稿（`proof_manuscript`），内联正文
            # 不再能单独过审。」签块、`## 依赖` 段、按号命名的稿这三样只在文件上有落点；
            # 内联正文是内存里的一串字，签了没有地方盖块，B 收稿时读不到依赖面。
            # 判据拆成一个具名方法 `_manuscript_gate`（反真空判据把它打桩成恒放行 ⇒
            # 老的内联那一支必须重新走通）。
            #
            # 穷举型证据（E 那一档）不走"内联正文"这条路：它的载体同样是手稿
            # （`reports/e-proof-<实验号>.md`），机械七项会审照跑，签块落回这份稿。
            manuscript_rel = str(proof_manuscript or "").strip().replace("\\", "/")
            from .. import depsection as _DS
            from .. import exhaustionreport as _ER

            _exp_rows: list = []
            try:
                if self.store is not None:
                    _exp_rows = list(self.store.rows("experiments"))
            except (StoreError, AttributeError, TypeError):
                _exp_rows = []
            if manuscript_rel:
                # 载体在手：正文以稿为准（穷举那一支的稿里 `## 证明` 就是证明栏）。
                _ms = self._registered_manuscript_body(
                    text=text, manuscript=manuscript_rel, statement_id=sid)
                if _ms.get("failed"):
                    out.update(checked=False,
                               kind=str(_ms.get("kind") or "manuscript_unreadable"),
                               reason=str(_ms.get("reason") or "manuscript_unreadable"),
                               detail=str(_ms.get("detail") or ""))
                    self._emit(f"verify_proof({sid})：手稿没读成 —— 不审")
                    return out
                if not str(text or "").strip():
                    text = str(_ms.get("body") or "")
                manuscript_raw = str(_ms.get("raw") or "")
                # 2026-11-08：命题正文只从稿的 `## 命题` 读（不再读 statements）。
                statement_full = _DS.statement_body(manuscript_raw)
            else:
                # 老路（内联）：参数给的正文。这一段只在 `_manuscript_gate` 被摘掉时
                # 才走得到（反真空判据打的就是它）：默认装配下 gate 立刻返回受控拒绝，
                # 一个字节都不落。
                _gate = self._manuscript_gate(
                    sid=sid, text=text, manuscript=manuscript_rel)
                if _gate is not None:
                    out.update(_gate)
                    self._emit(f"verify_proof({sid})：在册命题只给内联正文 —— 不审，不落签"
                               "（要先有手稿）")
                    return out
                if not text.strip():
                    out["reason"] = "no_proof_text"
                    out["detail"] = ("这一条没有可签的载体：既没有手稿（`proof_manuscript`），"
                                     "也没有可审的正文 ⇒ 先落一份稿再送")
                    return out
            # 2026-11-08：穷举判定只看稿里 `## 证明` 那一节的写法（V 不再看
            # statements 的证明栏，也不看稿名）。`reports/e-proof-*.md` 只说明这份稿
            # 是 E 那一族，不说明这一份正文已经是数值证据。
            _numeric = _ER.is_exhaustion_column({"proof_text": text}, _exp_rows)

            # ---- 2026-10-23 晚（业主：「E 写的报告要能落下来，且 V 也要会审这种东西」）
            #
            # 穷举型证据（证明栏第 ① 段是一份数值实验程序）不按"逐行读证明文本"审：
            # 要审的是那份程序与 E 写的 ②③ 对不对得上（程序在不在、搜索空间的数在代码里
            # 有没有着落、剪枝/对称性有没有解释、边界写没写、结论是不是穷尽、形式化那一格
            # 填的类别对不对）。判据本体只有一处：`exhaustionreport.review`；这里只负责
            # 把它的三格读数翻成一次审校（落台账、`成立` 才签第 3 位）。
            #
            # 三格里最要紧的一档是「缺材料」（会审自己的读数是
            # `exhaustionreport.VERDICT_UNKNOWN`）：报告没落地（E 的 ②③ 没落成盘上那份读数）
            # 时不许判成立 —— 而业主 2026-11-01 的裁定把那一档整个取消了（V 不产出它），
            # 所以缺材料落的是没查成（`checked=False` + `reason="missing_material"`）：
            # 台账里不留行，缺哪一块逐条进 `detail`。它既不是"找到了缺陷"（不许打回 F），
            # 也不是"没找到缺陷"（不许判成立）—— 材料补齐之后重新送审。
            if _numeric:
                # ---- 2026-11-04（审计缺陷 ①）：会审对象必须是稿里那一份正文 ----------
                #
                # 改前这里 `_ER.review(statement=hit, ...)`：会审读的是 statements 上的
                # 证明栏，而签块盖的是稿里 `## 证明` 那一段 —— 真机读数（Q3b）是一份
                # 「1. 显然成立。」的稿拿到了 `已签=true`，会审的七项读的却是另一份 sha。
                # 现在会审对象显式取 `{"proof_text": text}`（与 `_review_without_statement`
                # / `_review_unregistered_exhaustion` 同一写法）：审的就是要签的那一份。
                # 稿里的正文与命题行上的那一版不同是合法的（改稿 / 第二阶段优化）——
                # 不同时审稿、签稿，命题行等 B 收录新正文时再按 sha 认领，绝不拿旧版
                # 的七项读数去给新版签字。
                _reviewed = _ER.review(workspace_root=self.workspace_root,
                                       statement={"proof_text": text},
                                       experiments=_exp_rows,
                                       # 2026-11-08：程序路径不在证明栏里了，会审要钉到
                                       # 这份稿自己那条实验（稿名里那个实验号）。
                                       experiment_id=_ER.experiment_id_of(manuscript_rel))
                out["kind"] = "numeric_evidence"
                out["exhaustion_review"] = dict(_reviewed)
                out["signer"] = str(_reviewed.get("signed_by") or "")
                out["proof_authors"] = list(_reviewed.get("proof_authors") or [])
                out["report_path"] = str(_reviewed.get("report_path") or "")
                self._emit(
                    f"verify_proof({sid})：穷举型证据会审 ⇒ {_reviewed.get('verdict')}"
                    f"（{len(_reviewed.get('checks') or [])} 项检查，"
                    f"缺材料 {_reviewed.get('missing') or []}）")
                _text_for_ledger = text
                # 业主 2026-10-29：穷举型证据这一路也走同一对秘书判定（B 段 / A 段）。
                # 这一路的"回复"没有模型原文（会审是机械的七项核对）⇒ 材料给的是
                # 会审自己的结论那一句，而不是 F 的证明正文（I12 同一条纪律）。
                _n_verdict = _ER.verdict_of(_reviewed)
                _missing = [str(m) for m in (_reviewed.get("missing") or [])]
                _missing_detail = missing_material_detail(_n_verdict, _missing)
                if _missing_detail:
                    # ---- 缺材料 ⇒ 没查成（业主 2026-11-01：不存在「看不出来」这一档）----
                    #
                    # 会审本身跑完了（七项逐项有读数），但盘上缺了该有的那一块：这既不是
                    # "找到了缺陷"（不许打回 F），也不是"没找到缺陷"（不许判成立）。
                    # 诚实的那一格只有"没查成"：`checked=False` + 明确 reason，台账里不留行
                    # （留一行会把"没查成"冒充成"审过了"）。缺哪一块逐条进 detail。
                    #
                    # 判据与文案都在 `missing_material_detail` 里：未在册那一支
                    # （`_review_without_statement`）用同一处 —— 两支必须同一条，
                    # 否则其中一支漏掉时"缺材料 ⇒ 成立"就会从那一支漏出来（P0-1）。
                    out["checked"] = False
                    out["reason"] = MISSING_MATERIAL_REASON
                    out["detail"] = _missing_detail
                    self._emit(f"verify_proof({sid})：穷举会审缺材料 —— 没查成，不落台账行"
                               f"（{_missing}）")
                    return out
                # 业主 2026-10-29：穷举型证据这一路也走同一对秘书判定（B 段 / A 段）。
                # 这一路的"回复"没有模型原文（会审是机械的七项核对）⇒ 材料给的是
                # 会审自己的结论那一句，而不是 F 的证明正文（I12 同一条纪律）。
                _n_reply = (f"穷举型证据会审：结论 {_n_verdict.get('verdict')!r}"
                            f"（{len(_reviewed.get('checks') or [])} 项检查，"
                            f"缺材料 {_missing}）")
                #: p247：穷举这一档没有模型原文（会审是机械的七项核对）—— 轴由机械会审
                #: 自己的两态读数给（`VERDICT_OK` ⇒ clean / `VERDICT_BAD` ⇒ fault），
                #: 写成与秘书判定同形的 `secretary_judge`（`source=exhaustion_report`）。
                #: 这不是按 V 的判词字面定轴：这一格的 `verdict` 就是会审的机械结论本身。
                _n_word = str(_n_verdict.get("verdict") or "")
                _n_axis = ("clean" if _n_word == str(_ER.VERDICT_OK)
                           else ("fault" if _n_word == str(_ER.VERDICT_BAD) else ""))
                _n_judge = {
                    "checked": bool(_n_axis), "axis": _n_axis, "decision": _n_word,
                    "reason": str(_reviewed.get("why") or _reviewed.get("reason") or ""),
                    "basis": [f"exhaustion_report={_n_word}"],
                    "source": "exhaustion_report",
                    "defect_step": _n_verdict.get("defect_step"),
                }
                out["secretary_judge"] = dict(_n_judge)
                try:
                    _row = VR.record_verification(
                        self.workspace_root, statement_id=sid,
                        proof_text=_text_for_ledger,
                        verdict=_n_verdict, verifier=self.actor,
                        submission_id=str(self.cfg.get("submission_id") or ""),
                        store=self.store, proof_no=no,
                        # D-34：这一签审的对象是 E 那份报告（它的字节 sha256 与相对路径）。
                        # 记进台账之后，B 的入库闸就能"按对象内容找签"（B 的报告是目录，
                        # 索引里那四格写的就是这一份），于是"谁先谁后"不再重要。
                        object_sha256=str(_reviewed.get("report_sha256") or ""),
                        object_path=str(_reviewed.get("report_path") or ""),
                        # 2026-11-04（甲）：签的载体是这份 e-proof 稿；`sign_statement`
                        # 从台账行上读它，把签块落回同一份稿（`vsigns.land`）。
                        manuscript=manuscript_rel,
                        secretary_judge=_n_judge,
                        # 穷举型证据是机械七项核对（不走上文的三轮连判）：这一格按
                        # "这一趟的第 1 轮"如实记；签发仍走历史台账门（见 review_call 注释）。
                        review_pass=1, review_call=review_call,
                        # 业主 2026-10-29 追加口径：V 只落台账，翻位交给秘书。
                        flip=False)
                except Exception as exc:  # noqa: BLE001 —— 台账写口的任何异常都落成红读数
                    # 2026-11-05（D4）：改前只收 `VerificationError` / `OSError`，别的异常
                    # 会「穿透 `verify_proof`」（真跑 `ws-vacuum2` 的 `RuntimeError`）—— 调用方
                    # 拿到的是一次崩溃而不是一条读数。三态纪律：写口自己坏了也是「这一格
                    # 没查成」，异常类型与原话必须能被人读到，不许穿透。
                    out["checked"] = False
                    out["reason"] = "ledger_unwritable"
                    out["detail"] = (f"台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                                     "这一格没查成（不落台账、不改位、必须重签）")
                    self._emit(f"verify_proof({sid})：台账写不进去 —— 会审没落地")
                    return out
                _n_word = str(_n_verdict.get("verdict") or "")
                _n_axis = str(_n_judge.get("axis") or "")
                _n_judged = bool(_n_judge.get("checked"))
                if _n_word == "成立" and _n_judged and _n_axis == "clean":
                    # 只有"判过了、没问题、结论成立"这一档才问"这一签发不发"。
                    _n_issuance = self._decide_sign_issuance(sid, _text_for_ledger, no,
                                                             _n_verdict, row=_row,
                                                             review_call=review_call)
                else:
                    # 其余那一档一律不发签，读数由 `_terminal_issuance` 给（与逐行走查
                    # 那条链同一套判据：verdict 先行，其次 fault，最后才是没查成）。
                    _n_issuance = self._terminal_issuance(
                        sid, no, text=_text_for_ledger, row=_row,
                        judgment=_n_judge, verdict=_n_verdict)
                out["sign_issuance"] = dict(_n_issuance)
                if _n_word == "成立" and not _n_judged and not bool(_n_judge.get("unwired")):
                    # 秘书问不出来（这一问失败）⇒ 框架失败（业主 2026-10-30 第三次裁定
                    # 第 3 条）：终止 + checked=False + 明确 reason；不许当成 fault 打回，
                    # 也不许报"签住了"。装配缺口（unwired）不在这一支：那一档 V 的会审
                    # 确实做完了，只是没人能发这一签。
                    out["checked"] = False
                    out["reason"] = ("secretary_unjudged：会审这一转秘书问不出来"
                                     "（没查成，不是判定）")
                    out["detail"] = (
                        "穷举型证据的会审做完了、台账那一行也落了，但秘书的语义判定没查成"
                        f"（{str(_n_judge.get('reason') or '没有给理由')[:300]}）⇒ 这一签不发，"
                        "连判到此为止。处置：核对 V 的秘书装配与模型缝"
                        "（`secretary.for_role_wired(\"V\", ...)`），判定接上之后重签。"
                        "这一档不是「有毛病」——不许按缺陷打回 F。")
                    self._emit(f"verify_proof({sid})：会审这一转秘书没查成"
                               f"（{str(_n_judge.get('reason') or '没有给理由')[:120]}）")
                    return out
                return self._finish_numeric(out, statement_id=sid, no=no, row=_row,
                                            reviewed=_reviewed)
            # 走到这里：在册的散文证明。`text` 在更早处已经按载体归一（给了稿就是
            # 稿里 `## 证明` 那一节，`manuscript_rel` 非空；只有反真空判据 d 把
            # `_manuscript_gate` 摘掉时才是内联正文）。正文与稿的对 sha 也在那里做过，
            # 这里不再读第二遍、也不与 `statements` 上那一份比（手稿正是"新写/改后"
            # 的那一版，在册那一版可能还空着或不同）。
        if not text.strip():
            out["reason"] = "no_proof_text"
            out["detail"] = ("这一条没有可签的载体：既没有手稿（`proof_manuscript`），"
                             "也没有可审的正文 ⇒ 先落一份稿再送（`reports/…` 或 "
                             "`notes/…` 皆可，三节 `## 命题` / `## 证明` / `## 依赖`）")
            return out

        # ---- 2026-11-08：稿上已经签过的不再送审 ---------------------------------
        #
        # 判据只看手稿（`vsigns.manuscript_sign_standing`：签块盖住的就是这一份正文）。
        # 不再读命题行的第 3 位 —— V 不读台账之后，"已签"是稿上的事实，不是册里的缓存。
        # 三样读数照旧：`checked=True` / `review_passes=[]` / `reason="already_signed"`。
        # `signed_bit3` 在这里恒为 False：这一趟没有翻任何命题位（签在稿上，B 收录时认）。
        _sign_block: dict[str, Any] = {}
        if manuscript_raw:
            from .. import vsigns as _VS

            _sign_block = dict(_VS.manuscript_sign_standing(
                manuscript_raw, proof_sha=VR.proof_sha(text),
                manuscript_path=manuscript_rel) or {})
        if str(_sign_block.get("state") or "") == "signed":
            # 这一趟没有新判任何事，但"那一签当时读到了什么"必须照得出来：引用材料
            # 从手稿现读，逐条引用结论 / findings / 引用闸回放签住的那一行台账。
            # 为什么必须回放：读者手上的返回值不许比真身更空 —— 空 `citation_checks`
            # 会让"核过、有一条 weaker"与"没有引用"在读数上长得一样。
            # 回放不是现造：来源只有盘上那一行，找不到就照实说找不到。
            from .. import depsection as _DS

            signed_row = _ledger_row_for_sha(self.workspace_root, sid, VR.proof_sha(text))
            signed_id = str(signed_row.get("verification_id") or "")
            _deps = _DS.parse_dependency_section(manuscript_raw)
            _cited = _cited_manuscripts(self.workspace_root, _deps.get("rows") or [])
            citations, citations_problem = _citation_material(
                rel=manuscript_rel, deps=_deps, cited=_cited, proof_no=no)
            for item in citations:
                # 可引判据走可打桩的那一格（`_citation_admissibility`，与循环里同一处）。
                item["admissible"] = bool(
                    self._citation_admissibility(item.get("grade") or ""))
            # 引用闸也是纯函数（`citation_gate`）：台账只在"这一档没查成"时存那一格
            # （`problem` 非空，见 `record_verification`），其余情况按行上的逐条结论现算
            # —— 两处读法必须与循环里那一趟相同，否则回放出来的闸与那一签当时的闸不同。
            replayed_checks = list(signed_row.get("citation_checks") or [])
            stored_gate = signed_row.get("citation_gate")
            if isinstance(stored_gate, Mapping) and stored_gate:
                replayed_gate = dict(stored_gate)
            else:
                replayed_gate = VR.citation_gate(
                    replayed_checks,
                    problem=str(citations_problem if not signed_row else ""))
            out.update({
                "checked": True,
                "kind": "proof_manuscript_signed",
                "signed_bit3": False,
                # 稿上那一格是这一趟唯一可报的"签"；命题位没有翻（B 收录时认）。
                "review_write": {
                    "written": False, "rolled_back": False, "deferred_to": "filing:B",
                    "manuscript_signed": True,
                    "filed": "not_read_by_v",
                    "reason": ("这一份正文在稿上已经签过；命题行由 B 收录时按正文 sha 认领"
                               "（V 不读、也不写 statements）"),
                },
                "bits": {},
                "reviewed_by": {},
                "verification_id": signed_id,
                "verdict": (VR.read_verdict(signed_row)
                            or str(_sign_block.get("verdict") or "")),
                "defect_step": signed_row.get("defect_step"),
                "findings": list(signed_row.get("findings") or []),
                "unresolved_errors": int(signed_row.get("unresolved_errors") or 0),
                "proof_sha256": str(_sign_block.get("proof_sha256") or VR.proof_sha(text)),
                "proof_chars": int(signed_row.get("proof_chars") or len(text)),
                "citations": citations,
                "citation_checks": replayed_checks,
                "citation_gate": replayed_gate,
                "ledger": (f"{VR.VERIFICATIONS_DIR}/{sid}.jsonl#{signed_id}"
                           if signed_id else ""),
                # 这一趟一转都没判：读侧不许把它读成"判过、没问题"，也不许读成"没判过
                # 所以还要再审"—— 短接这件事由 `reason` 说。
                "review_passes": [],
                "reason": "already_signed",
                "detail": (f"命题 {sid} 的 {VR.proof_label(sid, no)} 在稿"
                           f"`{manuscript_rel}` 上已经签过（连续 "
                           f"{_sign_block.get('streak')}/{_sign_block.get('need')} 成立，"
                           f"正文 sha {str(_sign_block.get('proof_sha256') or '')[:12]}…）"
                           "⇒ 这一趟没有可做的审校：不再重复审、不落新台账行、不问模型。"
                           "上面那些引用核实与 findings 是那一签留下的读数，不是这一趟新判的"
                           f"（台账那一行：{VR.VERIFICATIONS_DIR}/{sid}.jsonl"
                           f"#{signed_id or '?'}）。"
                           "这一份签已经落在稿上；命题行的第 3 位与等级由 B 收录时"
                           "按正文 sha 认领/现算（V 不写 statements）。"
                           + ("这一趟的依赖面读不出来，引用材料这一格没取成："
                              f"{citations_problem}；" if citations_problem else "")
                           + ("台账里没找到那一签的原文 ⇒ 逐条引用结论与 findings "
                              "取不到（那不是「核过、没有引用」）。"
                              if signed_id and not signed_row else "")
                           + (f"引用核实那一档的读数：{replayed_gate.get('why')}"
                              if replayed_gate.get("why") else "")
                           + "要重新审这一份已经签过的证明，先改稿（正文 sha 变了就不短接）。"),
            })
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 这一份正文在稿上已经"
                       f"签过了（连续 {_sign_block.get('streak')}/{_sign_block.get('need')}）"
                       "—— 不再重复审，不落新台账行、不问模型")
            return out

        # ---- 2026-11-06（业主裁定 3 的准确含义）：打回站住 —— 同一份正文不再起转 ------
        #
        # 业主逐字：「一次判有毛病时应该立即打回，不再起转，等下一次提交时重新从 0 转计数」。
        # 上一格管"已经签过的"，这一格管对称的那一档：这一份正文已经被打回过。
        #
        # 现场（`R-mk-infinite-94` 的 000034：v1 clean / v2 fault / v3–v5 clean 签上）与
        # 判据见 :func:`_rejection_stands` 的 docstring。
        #
        # 所以这里与 `already_signed` 同形：不问模型、不落台账行、不签发，把"打回站住"
        # 作为这一趟的结论报回去（`checked=True`：查过了，结论是这一份仍是打回状态）。
        # 下一次真正的提交是 F 改稿之后（正文 sha 变了）—— 那一趟从 0 起数，三转
        # clean 照旧发签（`agent_v.core` 的连判循环一个字都不用改）。
        #
        # 幂等与范围：判据只读台账（`review_standing` 只看这一份正文的覆盖集），
        # 命题不在册 / 台账没有这一份 ⇒ `unsigned`，这一格不触发；`unreadable`（台账读
        # 不出来）也不触发（那是"没查成"，不许折成"打回"）。
        standing = VR.review_standing(self.workspace_root, statement_id=sid,
                                      proof_text=text, proof_no=no)
        if _rejection_stands(standing):
            _obj_id = str(standing.get("verification_id") or "")
            _obj_ref = (f"{standing.get('ledger') or VR.VERIFICATIONS_DIR}#{_obj_id}"
                        if _obj_id else str(standing.get("ledger") or ""))
            _judge = {
                "checked": True, "axis": "fault", "decision": "",
                "reason": str(standing.get("why") or ""),
                "basis": [f"台账读数：{_obj_ref or '（没有定位）'}"],
                #: 这一格不是秘书这一次判的，是台账上那一次打回的读数（读侧口径）。
                "source": "ledger:rejected",
            }
            out.update({
                "checked": True,
                "kind": "",
                "signed_bit3": False,
                "verdict": str(standing.get("verdict") or ""),
                "proof_sha256": str(standing.get("sha") or VR.proof_sha(text)),
                "proof_no": no,
                "proof_chars": len(text),
                # 这一趟零转：一条模型调用都没花、一行台账都没落。
                "review_passes": [],
                "secretary_judge": _judge,
                "sign_issuance": self._terminal_issuance(
                    sid, no, text=text, row={}, judgment=_judge, verdict={}),
                "ledger": _obj_ref,
                "reason": f"{_obj_ref or '台账'}：打回站住（同一份正文不重复判）",
                "detail": (
                    "这一份正文已经被打回过 ⇒ 这一趟不问模型、不落台账行、不签发。"
                    "业主 2026-11-06（裁定 3）逐字：「一次判有毛病时应该立即打回，不再起转，"
                    "等下一次提交时重新从 0 转计数」—— 打回之后又起转的那一趟不是"
                    "「另一次送审攒够三转」，所以同一份正文（同一个 sha）重送不会把"
                    "连续次数续上、也不会被当成新的三转。"
                    f"台账读数：{str(standing.get('why') or '（没有理由）')}。"
                    "处置：按 findings / 洗过的转达改稿；改过字（正文 sha 变了）之后重送，"
                    "那一趟从 0 起数，三转 clean 才发签。"
                    "这一条不是「没查成」，也不是「又签住了」：它是打回。" ),
            })
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 这一份正文已经被"
                       f"打回过（{_obj_ref or '台账里那一行'}）—— 不重复判、不落新行、"
                       "不问模型；改过字之后重送")
            return out

        # ---- 引用核实的材料（业主 2026-10-26：V 要核 F 的引用，而 F 的引用不是逐字引文）----
        #
        # 2026-11-08（V 只对手稿负责）：这一份材料从手稿的 `## 依赖` 与被引命题
        # 各自的手稿现读（`_cited_manuscripts`），不再读 `dependencies` / `statements`。
        # 每一条仍然给三样：F 在依赖段里写的那句原话、被引命题手稿的 `## 命题` 摘要、
        # 以及"那份稿上有没有盖住现行正文的 V 签"（可引资格；pre_theorem ⇔ 有 V 签）。
        # 不给编号了事：只给编号，V 核不出"F 是不是这么用的、这条够不够格被引"。
        #
        # 2026-10-30 起这一份材料是"三转共用"的：同一份正文 ⇒ 依赖行与被引命题摘要不会
        # 因为"第几次读"而变。每一转各自去读一遍盘只会多三次 IO，还会让三转的审阅对象
        # 有可能不同 —— 那正好把"同一份证明的连续三次判断"悄悄变成"三份不同东西的判断"。
        _deps = _DS.parse_dependency_section(manuscript_raw)
        _cited = _cited_manuscripts(self.workspace_root, _deps.get("rows") or [])
        citations, citations_problem = _citation_material(
            rel=manuscript_rel, deps=_deps, cited=_cited, proof_no=no)
        for item in citations:
            # 可引判据走可打桩的那一格（`_citation_admissibility`），材料里存的是它的答案。
            item["admissible"] = bool(self._citation_admissibility(item.get("grade") or ""))
        out["citations"] = citations
        facts = str(readonly_facts or "") or _manuscript_facts(
            manuscript_rel, manuscript_raw, _deps, block=_sign_block)
        prompt = VR.cold_start_prompt(statement_full or f"（命题 {sid} 的正文没读到）",
                                      text, readonly_facts=facts, citations=citations,
                                      citations_problem=citations_problem)

        # ---- 业主 2026-10-30 的两次裁定：一次调用里连着判，终局只有两种 ----
        #
        # 循环的每一转都是一次真的模型调用 + 一行台账 + 一次秘书判定，三件事一件都不许省：
        # 省了模型调用就成了"把同一份结论抄三遍"（那不是连续三次判断，是一次判断数三下）；
        # 省了台账行，连续次数就没有来源；省了秘书判定，就等于 V 自己发签（2026-10-29 已收回）。
        #
        # 停的两条（业主第二次裁定的逐字：「连判里面如果判出一回秘书
        # 语义分析认为是『有毛病』的，则直接打回了，连判终止」）：
        # ① 签上：秘书已经决定签发（`issue`）。"判了签发却没落盘"是装配问题，再判几转也变不
        #    出一张签 ⇒ 一并停，并让 `issued` 如实说没落地；
        # ② 打回：秘书判 fault（有毛病），或这一签的结论不是「成立」。
        #    那一转就是终局：缺陷已经点名，这一行的读数就是打回给 F 的那一条
        #    （fault 那一档随台账行带上洗过的转达）。
        #    不再多问一转 —— 多问等于"再给一次机会"，而业主的口径是"直接打回"。
        #
        # 上界动态等于门槛（`review_pass_bound()` 现读）：跑满门槛时 clean 那一档必然攒够
        # 门槛票，于是"要么签、要么打回"必然命中。跑完两头都没有 ⇒ 内部不一致（见下）。
        need = review_pass_bound()
        #: 依赖面的机械审计（业主 2026-11-06：V 是第一道）：算一次、三转共用。
        dependency_audit = self._dependency_audit(manuscript_raw, _cited)
        passes: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        #: 终局是哪一种："" = 循环跑完还没命中终局（= 内部不一致）/ signed / rejected /
        #: gate（结论成立、但这一行自己签不住：引用核实挡签或还有未解决的 error）/
        #: unjudged（秘书这一问没查成）/ ledger（台账那一行没落地）。
        #:
        #: `rejected` 是"打回"那一个终局（2026-11-06 业主裁定 3）：秘书判 fault ⇒
        #: 这一转就是终局、立刻打回，不再起转。改前这个值叫 `fault`——同一种结局在
        #: 未在册两支里叫 `rejected`，在在册这一支叫 `fault`，读的人要按分支猜名字；
        #: 现在三支同一个词（`_review_unregistered_prose` / `_review_exhaustion_rounds`）。
        #:
        #: 判的次序（2026-11-01 修，`draft/165` 取证 D）：结局（rejected）→
        #: 签不签得动（gate）→ 签上了没有（signed）→ 没查成（unjudged）；台账那一档最先判。
        #: 别把 gate 移回结局之前：`row_signable` 蕴含"结论成立"，移回去就会再把
        #: "有毛病"吞成"成立但签不住"（`tests/test_v_terminal_says_what_happened.py` 的 s3c 钉着）。
        stopped = ""
        stop_why = ""
        #: 这一趟送审内的连续 clean 次数（2026-11-06 业主裁定 3 的准确含义：真计数）。
        #:
        #: 它不是轮号：只有"这一转的秘书轴是 clean 且这一行自己签得住"才 +1，任何别的
        #: 一转一律归零。改前这里是 `pass_no if axis == "clean" else 0`（= 拿轮号当连续数）
        #: —— 那个形状只在"fault 必然 break"的巧合下才是对的；一旦哪一转没断，
        #: 它会把"清零之后的第 3 轮"直接读成 3/3（正是业主否掉的"清零后接着攒"）。
        streak = 0
        for pass_no in range(1, need + 1):
            once = self._review_pass(sid=sid, text=text, no=no, prompt=prompt,
                                     citations=citations,
                                     citations_problem=citations_problem,
                                     pass_no=pass_no, review_call=review_call,
                                     manuscript=manuscript_rel,
                                     dependency_audit=dependency_audit)
            if not once.get("ok"):
                # 这一转没查成（没接线 / 结论不合法 / 台账写不进去）。已经读到的读数
                # 照改前的顺序摊回返回值：秘书判定与引用核实在改前也是先落再写的，
                # 于是"没查成"那几条路上它们照样读得出来。
                if once.get("judgment"):
                    out["secretary_judge"] = dict(once["judgment"])
                if once.get("gate"):
                    out["citation_gate"] = dict(once["gate"])
                    out["citation_checks"] = [
                        {key: c.get(key) for key in VR.CITATION_CHECK_KEYS}
                        for c in (once.get("checks") or [])]
                if once.get("wash"):
                    out["wash_v_reply"] = dict(once["wash"])
                if str(once.get("emit") or ""):
                    self._emit(str(once["emit"]))
                out["reason"] = str(once.get("reason") or "")
                out["detail"] = str(once.get("detail") or "")
                out["review_passes"] = passes
                return out
            last = once
            axis = str(once["judgment"].get("axis") or "")
            # 这一转的 streak 是这一趟送审内连到几转 clean（2026-11-02 定稿 + 2026-11-06
            # 裁定 3）：真计数 —— 只在"轴是 clean 且这一行自己签得住"时才 +1，
            # 任何别的转（fault / 没判成 / 引用挡签）一律归零。不是台账尾部跨历史的连续数
            # （那正是"跨两次送审累计"的后门），也不是轮号（那会把"清零后接着攒"读成够了）。
            streak = (streak + 1) if (axis == "clean" and VR.row_signable(once["row"])) else 0
            passes.append({
                "pass": pass_no,
                "axis": axis,
                "decision": str(once["issuance"].get("decision") or ""),
                "streak": streak,
                "need": int(need),
                "streak_ok": bool(streak >= int(need)),
                "issue": bool(once["issuance"].get("issue")),
                "issued": bool(once["issuance"].get("issued")),
                "verdict": str(once["row"].get("verdict") or ""),
                "verification_id": str(once["row"].get("verification_id") or ""),
                #: 同一趟送审的调用 id（三转逐字相同）。签文件里的 `passes` 按它取行，
                #: 旧台账没有这一格 ⇒ 历史形态，不参与新签判断。
                "review_call": review_call,
                #: 这一转是不是终局、是哪一种（""=不是终局）。读侧不必再从"下一转还在不在"
                #: 反推"停在哪儿"，也不用把"打回"读成"次数没到"。
                "terminal": "",
            })
            out["review_passes"] = passes
            if once["row"].get("checked") is False:
                # 台账那一行没落地（追加失败 / 被撤回）⇒ 立刻停：再判几转也攒不出一票
                # （连续次数从台账派生）。收尾那一支会报 `ledger_row_lost`，不许报"签住了"。
                stopped = "ledger"
                passes[-1]["terminal"] = stopped
                stop_why = "台账那一行没落地（必须重签）"
                break
            # ---- 先判秘书给的轴，再判"这一签签不签得动"，最后判"签上了没有" ----
            #
            # p247（业主 2026-11-06 第三次收紧）：「V 的判词只是陈述」「每一转的轴
            # （clean / fault）一律由 V 秘书做语义分析后给出」「streak / 签发只看秘书
            # 给出的轴，不看 V 自己写的那两个字」。所以这里删掉了原来的
            # `read_verdict(row) != "成立"` 那一支（它会按 V 的字面直接打回，越过秘书的
            # 语义判定），也删掉了它的 `terminal="verdict"`。现在只有：
            #   ① 秘书判 fault ⇒ 打回（terminal=rejected）；
            #   ② 轴 clean 但行局部机械闸没过（引用挡签 / 未解决 error）⇒ gate；
            #   ③ 秘书判了签发 ⇒ signed；
            #   ④ 秘书这一问没查成 ⇒ unjudged（不按字面补判）。
            # 三条必须同时成立（`tests/test_v_terminal_says_what_happened.py` 的 s3c 用 AST
            # 钉住，别只信这段注释）：gate 在结局之后、gate 在 signed 之前。
            #
            # 2026-11-06（业主裁定 3）：「一次判有毛病时应该立即打回，不再起转，等下一次
            # 提交时重新从 0 转计数」。所以 fault 这一支一判出来就 break —— 这一转就是这次
            # 送审的最后一转；连续数归零（`streak` 上面已经算了），而同一次送审绝不会
            # 再起第 4、5 转。下一次送审是一条新的 `review_call`，从 0 起数。
            if axis == "fault":
                stopped = "rejected"
                passes[-1]["terminal"] = stopped
                stop_why = "秘书判 fault（有毛病）：这一转就是终局，立刻打回 F（不再起转）"
                break
            if not bool(once["judgment"].get("checked")):
                # 秘书这一问没查成（没缝 / 没答上来 / 词表外 / 抛异常）：那不是判定，
                # 更不是"有毛病"。p247：这一支排在 gate 之前 —— 没有轴就没有"签不签得动"
                # 可判（`row_signable` 也返回假），必须如实报 unjudged，不许把它读成
                # "结论成立但签不住"。立刻停，读数由收尾那一支分两档给。
                stopped = "unjudged"
                passes[-1]["terminal"] = stopped
                stop_why = ("秘书这一转没判成（checked=False）：没查成，不是有毛病，"
                            "也不是没问题")
                break
            if not VR.row_signable(once["row"]):
                # ---- 结论写「成立」，但这一行自己签不住（引用核实挡签 / 未解决的 error）----
                #
                # 2026-11-01 的两态裁定把这个终局露了出来：改前"引用判不了"被改判成第三态
                # `看不出来`，于是循环按"V 的结论不是成立"那一支停；两态之后结论仍是 `成立`
                # （它没找到缺陷），挡住这一签的是引用闸，而循环此前不读它 ⇒ 三转跑完既没签、
                # 也没打回，收尾报一条假的 `internal_inconsistency`。这一支补上那个终局：
                # 立刻停，由正常收尾路径如实报"结论成立、但这一签没落地，为什么"。
                #
                # 它只接"结论成立"的行（上面两支已经把"有毛病"接走了）⇒ 下面这句
                # "结论是「成立」"是这一支自己的前提，不是替别人写的。原来那句
                # "也不是没查成"删掉了：秘书这一问没查成与"签不住"可以同时成立，
                # 那句话会对读者撒谎；"没查成"由 `secretary_judge.checked` 自己说。
                stopped = "gate"
                passes[-1]["terminal"] = stopped
                stop_why = ("这一签的结论是「成立」，但它自己签不住"
                            f"（{VR.signing_gate_problem(once['row']) or '引用核实挡签'}"
                            f"；未解决 error {int(once['row'].get('unresolved_errors') or 0)} 条）"
                            "⇒ 不签第 3 位；连判到此为止（这不是有毛病）")
                break
            if bool(once["issuance"].get("issue")):
                stopped = "signed"
                passes[-1]["terminal"] = stopped
                stop_why = ("签上了" if once["issuance"].get("issued")
                            else "秘书判了签发，但翻位没落成（落地是秘书的事）")
                break
        # 循环之后：这一趟的读数一律取"最后那一转"（前面的每一转都在 `review_passes` 里）。
        row = dict(last.get("row") or {})
        judgment = dict(last.get("judgment") or {})
        issuance = dict(last.get("issuance") or {})
        gate = dict(last.get("gate") or VR.citation_gate([]))
        out["secretary_judge"] = judgment
        out["sign_issuance"] = issuance
        out["citation_gate"] = gate
        out["citation_checks"] = [{key: c.get(key) for key in VR.CITATION_CHECK_KEYS}
                                  for c in (last.get("checks") or [])]
        if last.get("wash"):
            out["wash_v_reply"] = dict(last["wash"])
        if stopped == "":
            # 循环跑完而既没签也没打回 ⇒ 内部不一致，不是一条终局（业主 2026-10-30 否掉的
            # 就是"次数没到"这类收尾）。`checked=False` 是"没查成"，不是"审过了"。
            out["review_passes"] = passes
            out["reason"] = "internal_inconsistency：连判跑完既没签也没打回"
            out["detail"] = (
                f"门槛 {need} 次、这一趟判了 {len(passes)} 转，却既没有秘书发签、也没有任何"
                "一转被秘书判出毛病 ⇒ 这是一处内部不一致（不是一条合法的终局，"
                "也不是「再判几次就好」）。两种来路：① 门槛被改成 0 或负数（连判一转都跑不了）；"
                "② 秘书在连续次数已经够的那一转既不发签、也没判出问题（秘书那一侧的装配或"
                "判定异常）。处置：把门槛改回正整数，并核对 V 的秘书装配"
                "（`secretary.for_role_wired(\"V\", ...)`）之后重签。")
            self._emit(f"verify_proof({sid})：连判跑完既没签也没打回 —— 内部不一致"
                       f"（门槛 {need}，判了 {len(passes)} 转）")
            return out
        if stopped == "unjudged" and not bool(judgment.get("unwired")):
            # "秘书问不出来"那一档（业主 2026-10-30 第三次裁定第 3 条）：框架失败 ⇒
            # 整笔 `checked=False` + 明确 reason；不许当成 fault 打回，也不许说"次数没到"。
            # 与"没有判断面"（装配缺口）分开：那一档台账照落、顶层 checked 仍为真
            # （V 的审阅确实做完了），这里报的是"这一问没查成"。
            out["review_passes"] = passes
            out["checked"] = False
            out["signed_bit3"] = False
            out["bits"] = {}
            out["reason"] = ("secretary_unjudged：这一转秘书问不出来（没查成，"
                             "不是判定）")
            out["detail"] = (
                "V 的审阅这一转做完了、台账那一行也落了，但秘书的语义判定没查成"
                f"（{str(judgment.get('reason') or '没有给理由')[:300]}）⇒ 这一签不发，"
                "连判到此为止。处置：核对 V 的秘书装配与模型缝（"
                "`secretary.for_role_wired(\"V\", ...)`），判定接上之后重签。"
                "这一档不是「有毛病」——不许按缺陷打回 F，也不是「再判几转就好」。")
            self._emit(f"verify_proof({sid})：秘书这一转没查成（"
                       f"{str(judgment.get('reason') or '没有给理由')[:120]}）—— 没查成")
            return out
        self._emit(f"verify_proof({sid})：这一趟自己连判 {len(passes)} 次"
                   f"（停在：{stop_why}）")
        self._emit(f"verify_proof({sid})：秘书语义判定 "
                   f"{'checked' if judgment.get('checked') else 'checked=False'}"
                   f"（{judgment.get('axis') or '没判'}）"
                   f"；发签 {'发' if issuance.get('issue') else '不发'}"
                   f"（连续 {issuance.get('projected')}/{issuance.get('need')}）"
                   + (f"；翻位 {'成' if issuance.get('issued') else '没成'}"
                      if issuance.get("issue") else ""))
        writeback = dict(issuance.get("writeback") or row.get("statement_writeback") or {})
        if row.get("checked") is False:
            # 台账那一行没落地（被撤回 / 追加失败）：不许报"签住了第 3 位"。
            # 改前这里照样 `checked=True, signed_bit3=True`，而盘上 0 字节（审计第 1 条）。
            out.update({
                "checked": False,
                "review_write": writeback,
                "reason": f"ledger_row_lost：{row.get('reason') or '台账那一行没写成'}",
                "detail": (f"V 的结论是 {row.get('verdict')!r}，但台账那一行"
                           + ("被撤回" if writeback.get("rolled_back") else "没写成")
                           + " ⇒ 这一签没有落地、命题行的第 3 位也没改；"
                             "必须重签（重新走一次 verify.verify_proof），"
                             "不许把它当成「审过了」"),
            })
            self._emit(f"verify_proof({sid})：{out['reason']} —— 台账里没有这一签")
            return out
        # 2026-11-08：V 不再翻命题位（`signed_bit3` 恒 False）。这一趟的"签"只回答
        # 两件事：签的侧文件颁发了没有（`issuance.issued`）、收方秘书把九格块落回
        # 手稿了没有（`writeback.manuscript_write.written`）。命题行的第 3 位与等级
        # 由 B 收录时按正文 sha 认领 / 现算。
        _ms_write = dict(writeback.get("manuscript_write") or {})
        _manuscript_signed = bool(_ms_write.get("written") or _ms_write.get("idempotent"))
        bits: dict[str, Any] = {}
        try:
            from .. import evidencebits as EB

            bits = EB.bits_of(proof=bool(str(text or "").strip()), proof_process=text)
        except Exception as exc:  # noqa: BLE001 —— 合成失败不影响台账那一行（它已经落盘）
            self._emit(f"verify_proof({sid})：五元位合成失败（{type(exc).__name__}: {exc}）")
        self._emit(f"verify_proof({sid})：{row['verification_id']} verdict={row['verdict']} "
                   f"signed_bit3=False（签在稿上：颁发={bool(issuance.get('issued'))}，"
                   f"落块={_manuscript_signed}）")
        if _manuscript_signed:
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 的签已由收方秘书"
                       f"落回手稿（{_ms_write.get('path') or manuscript_rel}）；"
                       "命题行等 B 收录")
        elif writeback:
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 的签没落成 —— "
                       f"{writeback.get('reason') or ''}")
        out.update({
            "checked": True,
            "verification_id": row["verification_id"],
            "verdict": row["verdict"],
            "defect_step": row["defect_step"],
            "findings": row["findings"],
            "unresolved_errors": row["unresolved_errors"],
            "proof_sha256": row["proof_sha256"],
            "proof_no": row.get("proof_no"),
            "proof_chars": row["proof_chars"],
            # 命题位没有翻（V 不写 statements）；"签在稿上"由 `review_write` 两格说。
            "signed_bit3": False,
            "reviewed_by": {},
            "bits": bits,
            "review_write": dict(writeback, manuscript_signed=_manuscript_signed,
                                 filed="not_read_by_v"),
            "ledger": f"verifications/{sid}.jsonl#{row['verification_id']}",
            # 台账那一行是这一档的正本：返回的 citation_checks 从盘上那一行读回来
            # （它已经过 `parse_verdict` 的同一套校验、只剩那几格）。
            "citation_checks": list(row.get("citation_checks") or []),
            "reason": f"{row['verification_id']}：{row['verdict']}"
                      + ("（签在稿上；命题行由 B 收录时认领）"
                         if _manuscript_signed else "（不签：签没落成）")
                      + ("；秘书判定没查成（这一趟没有判断面）⇒ 这一签不发"
                         if stopped == "unjudged" else "")
                      + (f"；引用核实挡下 {len(gate.get('blocking') or [])} 条"
                         if gate.get("blocking") else ""),
            # 引用核实那一句原话（挡签时它点名哪一条、差在哪；只有弱形式时它点名那一条）。
            "detail": str(gate.get("why") or ""),
        })
        return out

    def _review_pass(self, *, sid: str, text: str, no: int, prompt: str,
                     citations: list[dict[str, Any]], citations_problem: str,
                     pass_no: int, review_call: str = "",
                     manuscript: str = "",
                     dependency_audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """一份证明的一次独立审阅（业主 2026-10-30 的"连续再判"里的那一转）。

        一转做五件事，一件都不许省：
        ① 真的问一次模型（第 2 转起在提问的末尾追加"第几次"，稳定前缀一个字不动）；
        ② 把回复解析成两态结论（不合法 ⇒ 这一格"没查成"，不落台账行；历史值「看不出来」
         按「成立」收，而「判不了 / 我无法判断」这一族按「有毛病」收 —— 见
         `verifications.parse_verdict`）；
        ③ 引用核实的定稿与签字前置（与改前同一套判据，唯一实现在 `verifications`）；
        ④ 秘书的语义两档判定（B 段）＋ 判了 fault 时那一次洗稿（C 段）；
        ⑤ `record_verification(flip=False)` 落一行台账；clean 且结论是「成立」才问秘书
        发不发签（A 段），其余几档已经是终局 —— 由 `_terminal_issuance` 给一个 fail-closed
        的读数（见那个方法：这一签不许在"打回"的同一条路径上翻上位）。

        为什么这一转必须单独是一个方法：它要在 `verify_proof` 里被转三次，而"每一转都走
        同一套纪律"这件事只能有一个实现 —— 抄三遍必然漂（而漂的那一处正好会是
        "第 2 转忘了落台账"或"第 3 转跳过了秘书"）。

        2026-11-02 定稿：`pass_no` 是这一趟送审内的第几轮，`review_call` 是这一趟的
        调用 id。两格一起落进台账（`review_pass` / `review_call`），并作为 `within_call`
        递给秘书的发签地板 —— 台账尾部历史连续数不再参与这一趟的签发判断
        （业主：「不允许跨两次送审累计成功数」）。

        返回 `{"ok": True, "row": 台账行, "judgment": 秘书判定, "wash": 洗稿读数,
        "issuance": 发签决定, "gate": 引用闸, "checks": 逐条引用结论}`；
        `ok=False` 那一支只带"没查成"的三样东西（`reason` / `detail` / `emit`），
        与改前逐字相同，另外把已经读到的 `judgment` / `gate` / `checks` / `wash` 带回去
        （改前那几条路上它们也是先落进返回值再报错的）。
        """
        asked = prompt if int(pass_no) <= 1 else prompt + REVIEW_PASS_NOTE.format(n=pass_no)
        reply, problem = self._ask(asked)
        if problem:
            return {"ok": False, "reason": problem,
                    "detail": ("这次审校没有拿到合法结论 ⇒ 台账里不留行"
                               "（留一行会把「没查成」冒充成「审过了」）"),
                    "emit": f"verify_proof({sid})：没查成（{problem}）—— 不落台账行"}
        try:
            verdict = VR.parse_verdict(reply)
        except VR.VerificationError as exc:
            return {"ok": False, "reason": "unparsable",
                    "detail": f"模型输出不是合法结论：{exc}",
                    "emit": f"verify_proof({sid})：结论不合法（{exc}）—— 不落台账行"}

        # ---- 引用核实的定稿与签字前置（业主 2026-10-26 两批裁定）----
        #
        # 三条判据在这里合成一个结论：① 每一条被引命题都要有结论（缺的按 unknown 算）；
        # ② 被引命题低于 `proof_review` ⇒ inadmissible（事实，不交给模型裁量）；
        # ③ 有一条挡签的档 ⇒ 结论从「成立」改判（stronger/unrelated/inadmissible →
        #    有毛病；只有 unknown ⇒ 结论不动（它没找到缺陷），由引用闸挡住这一签）。改判的
        #    每一条都落进 findings 并点名，
        #    于是"签不成"这件事在台账里逐字可读，而不是只在返回值里说一句。
        checks = self._citation_checks(list(verdict.get("citation_checks") or []), citations)
        gate = VR.citation_gate(checks, problem=citations_problem)
        verdict = VR.apply_citation_gate(dict(verdict, citation_checks=checks), gate)
        #: 依赖面六项审计（业主 2026-11-06：V 是第一道）：机械判据并进结论 ——
        #: 不在册 / 等级不够 / 表与正文不一致 / 步号对不上 ⇒ 判「有毛病」、点名。
        verdict = merge_dependency_audit(verdict, dependency_audit)
        self._emit(f"verify_proof({sid})：引用核实 {len(checks)} 条，"
                   f"挡签 {len(gate.get('blocking') or [])} 条"
                   + (f"，弱形式 {len(gate.get('weaker') or [])} 条"
                      if gate.get("weaker") else "")
                   + ("；依赖台账读不到（这一档没查成）" if gate.get("problem") else ""))

        # ---- 业主 2026-10-29：V 不再自己发签 ----
        #
        # 追加口径逐字：「V 不再自己发签。V 只产出审稿意见；由 V 的秘书判定并落盘
        # （`Secretary.decide_sign_issuance` → 满足"连续 3 次 clean"才调
        # `verifications.sign_statement` 翻 `bits.evidence`）」。
        #
        # 于是这一转的顺序是三步，写盘的位置与改前不同：
        # ① 秘书判这段回复是哪一档（B 段；材料只给回复 + 这一签的 verdict/defect_step）；
        # ② `record_verification(flip=False)` 只落台账（正本先落，签这个事实不依赖任何人
        #    的决定；`statement_writeback.deferred_to == "secretary"`）；
        # ③ 秘书读连续次数 + 判"发不发"，判发就由它自己调 `sign_statement` 翻位。
        # 秘书不在场 / 没缝 / 没判成 ⇒ ②照落、③不翻 ⇒ 第 3 位保持空（fail-closed）。
        judgment = self._judge_v_reply(reply, verdict, no, statement_id=sid)
        # ---- p247：判 fault 而 V 没给步号 ⇒ 用秘书定出的那一步 ------------------
        #
        # 业主 2026-11-06 第三次收紧：「判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步」。
        # 机械解析仍然只负责取字段（V 给了就原样用）；秘书那一问给出步号时，这一行按它写。
        if (str(judgment.get("axis") or "") == "fault"
                and verdict.get("defect_step") is None):
            _sec_step = judgment.get("defect_step")
            if isinstance(_sec_step, int) and not isinstance(_sec_step, bool):
                verdict = dict(verdict, defect_step=_sec_step)
        # C 段：秘书判"有缺陷要指出"⇒ 立刻洗一遍，把洗过的文本随台账那一行落盘。
        # 为什么在落台账之前洗：台账是追加式文件，行写下去就不能改；洗过的转达文本
        # 必须与那一签一起落（`v_rejections_digest` 从那一格读给 F）。
        # 洗不出来 ⇒ 这一格不写（"没有这一格" = 没洗过，不许写空文本冒充洗过）。
        wash: dict[str, Any] = {}
        if str(judgment.get("axis") or "") == "fault":
            wash = self._wash_v_reply(reply, verdict, no, statement_id=sid)
        try:
            row = VR.record_verification(self.workspace_root, statement_id=sid, proof_text=text,
                                         verdict=verdict, verifier=self.actor,
                                         submission_id=str(self.cfg.get("submission_id") or ""),
                                         store=self.store, proof_no=no,
                                         # `problem` 非空（依赖台账读不出来）要随行落盘：
                                         # 否则读侧只看到空的 `citation_checks`，分不开
                                         # "没查成"与"核过、没有引用"。
                                         citation_gate=gate,
                                         # B 段：两档语义判定随台账那一行落盘。
                                         secretary_judge=judgment,
                                         # C 段：洗过的转达文本（只有真洗出来时才写）。
                                         washed_relay=wash,
                                         # A 段：发签权在秘书手上 ⇒ 这一次不翻位。
                                         flip=False,
                                         review_pass=pass_no,
                                         review_call=review_call,
                                         # 2026-11-04（甲）：这一签的载体。落进台账行，
                                         # 秘书翻位时 `sign_statement` 从行上读到它、
                                         # 让 `vsigns.land` 把签块盖回同一份稿。
                                         manuscript=manuscript)
        except Exception as exc:  # noqa: BLE001 —— 台账写口的任何异常都落成红读数（D4）
            # 台账写不进去（坏行 / 权限 / 磁盘 / 目录 / 写口自己抛的任何异常）⇒ 这是
            # "没查成"，不是"签住了"。不接住它会让异常穿透到工具层，而那一层读不到
            # "这一签没落地"这句话（2026-11-05 D4：改前只收 VerificationError / OSError）。
            self._emit(f"verify_proof({sid})：台账写不进去（{type(exc).__name__}: {exc}）—— 没查成")
            return {"ok": False, "checked": False, "reason": "ledger_unwritable",
                    "detail": (f"台账写不进去（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                               "（不落台账、不改位、必须重签）"),
                    "emit": "", "judgment": judgment, "wash": wash,
                    "gate": gate, "checks": checks}
        axis = str(judgment.get("axis") or "")
        # ---- 167/甲（业主 2026-11-01 裁定）：判定那一笔就投，收件人 = 送审者
        #
        # 为什么必须在这里、而不是等 F 下一次起跑（改前那一版在
        # `agent_loop.deliver_v_verdicts` 的唯一调用点 = `AgentLoop.run` 的 F 分支）：
        # 81 的 8 条判定里 4 条落在 F 最后一次起跑之后 ⇒ 连板项都没开，"送到"变成了
        # "收件人醒着"的副产品。回执是这一次判定的产物，不是下一次起跑的副作用。
        #
        # 顺序（崩溃不丢）：`vreceipts.publish_row` 先把意图落盘、再开板项、再记
        # dispatched（见那个模块的 docstring）。这里只用 `_publish_receipt` 一个口，
        # 判据（`tests/test_v_receipt_delivery_does_not_wait_for_the_recipient.py`）
        # 打桩的也是它 —— 摘掉它必须让"8 条判定 8 条有板项"变红。
        #
        # 收件人读不到（不在任何召唤里 / 台账没有那一行）⇒ 意图记 `undelivered`，
        # 不拿"谁醒着"当收件人。这一格失败不许带走这一签：`_review_pass` 的
        # 返回值一个字都不变（下面的键集合是判据钉住的）。
        receipt = self._publish_receipt(row)
        if receipt.get("state"):
            self._emit(f"verify_proof({sid})：回执 {receipt.get('state')}"
                       f"（{receipt.get('reason') or '没有读数'}）")
        if bool(judgment.get("checked")) and axis == "clean":
            # 只有"判过了、轴是 clean"这一档才问"这一签发不发"
            # （其余几档都是终局或没查成，见 `_terminal_issuance`）。
            # p247：这里不再看 `verdict == "成立"` —— 轴只由秘书给，V 的判词只是陈述。
            # 2026-11-02 定稿：把"这一趟的第几轮"作为地板递给秘书 —— 前两轮必不签，
            # 第三轮 clean 才签；台账历史行不参与（跨送审绝不累计）。
            issuance = self._decide_sign_issuance(sid, text, no, verdict, row=row,
                                                  within_call=pass_no,
                                                  review_call=review_call)
        else:
            issuance = self._terminal_issuance(sid, no, text=text, row=row,
                                               judgment=judgment, verdict=verdict)
        return {"ok": True, "row": row, "judgment": judgment, "wash": wash,
                "issuance": issuance, "gate": gate, "checks": checks,
                "verdict": verdict}

    def _publish_receipt(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """把这一签的回执投给送审者（167/甲；业主 2026-11-01 裁定）。

        ## 为什么单独一个方法

        判据要能把它打桩成空转（反真空：摘掉它 ⇒ "8 条判定 8 条有板项"必须变红），
        而 `verify_proof` 的返回值键集合是三条返回路径 / `returns=` 声明钉住的
        （`tests/test_tools_returns_declaration.py`）—— 投递读数因此不进返回值，
        只进 outbox（`out/vreceipts/outbox.jsonl`，盘上可读、崩了也在）与一条 `_emit`。

        ## 三态

        - `dispatched`：板项在（新开或已在）；`undelivered`：读不到送审者（不猜）；
        - `pending`：这一趟没有 conductor / 开项失败 ⇒ 意图已落盘，留给收工前补投；
        - 不是「有毛病」那一档 ⇒ `skipped`（"成立"的签不打扰任何人）。

        任何异常都折成 `{"state": "error"}` 返回，不许带走这一签 —— 回执投不出去
        是框架面的失败，不是"这一份证明没毛病"。
        """
        try:
            from .. import vreceipts as VRC

            return VRC.publish_row(self.store, row, at=str(row.get("at") or ""))
        except Exception as exc:  # noqa: BLE001 —— 投递失败不许带走这一签
            return {"checked": False, "state": "error",
                    "reason": f"回执投递没跑成（{type(exc).__name__}: {exc}）"}

    def _terminal_issuance(self, statement_id: str, proof_no: int, *, text: str,
                           row: Mapping[str, Any], judgment: Mapping[str, Any],
                           verdict: Mapping[str, Any]) -> dict[str, Any]:
        """这一转不是"判过了、没问题、成立"⇒ 不发签，读数逐字说清"为什么没签"。

        为什么不问 `decide_sign_issuance`：它读的是"连续次数够不够 + 是否同一份正文"。
        在这一转上那两条都可能已经满足（fault 之前攒的票还在），于是它会在"打回"的
        同一条路径上把第 3 位翻上去 —— 那一签与刚判出来的缺陷会同时成立，而业主的口径是
        这一转直接打回。所以这一格由 V 这一侧直接给一个 fail-closed 的读数：
        `issue=False`、`issued=False`（这一签没有发、也不该发）。

        `checked` 取秘书这一次判定自己的 `checked`：它判过（fault）⇒ True；
        它根本没判成（没有秘书 / 没缝 / 这一问没答上来）⇒ False ——"没查成"不许被读成
        "判过了"，更不许被读成"有毛病"。
        `streak` / `need` / `state` / `same_sha` 从台账现算（同一份读数来源，不另立判据）。
        """
        try:
            standing = VR.review_standing(self.workspace_root, statement_id=statement_id,
                                          proof_text=text, proof_no=proof_no)
        except Exception as exc:  # noqa: BLE001 —— 读不成是读数缺失，不是"发了签"
            self._emit(f"verify_proof({statement_id})：终局那一转的台账读数没读成"
                       f"（{type(exc).__name__}: {exc}）")
            standing = {}
        need = int(VR.SIGN_STREAK_NEED)
        streak = int(standing.get("streak") or 0)
        # 词表只有那一个来源（`secretary.SIGN_WITHHOLD`）：这里不抄第二份中文取值。
        from .. import secretary as _SEC

        axis = str(judgment.get("axis") or "")
        # 这一转凭什么不发签：fault（秘书判有毛病）/ unjudged（秘书这一问没查成）。
        # p247：不再有 `verdict` 那一档 —— V 的判词只是陈述，不发签的轴由秘书给。
        if axis == "fault":
            kind = "fault"
        else:
            kind = "unjudged"
        return {
            "checked": bool(judgment.get("checked")),
            "issue": False, "issued": False, "landed": False,
            "decision": _SEC.SIGN_WITHHOLD,
            "streak": streak, "need": need,
            "streak_ok": bool(streak >= need), "projected": streak,
            "same_sha": bool(str(standing.get("sha") or "")
                             and str(standing.get("sha")) == VR.proof_sha(text)),
            "state": str(standing.get("state") or ""),
            "reason": self._terminal_reason(kind=kind, judgment=judgment, verdict=verdict),
            "basis": [f"秘书判定 checked={bool(judgment.get('checked'))} "
                      f"axis={axis or '（没有轴）'}",
                      f"continuous={streak}/{need}",
                      f"row={row.get('verification_id') or '（没有编号）'}"],
            "reading": dict(standing), "cost": {}, "material": {},
            "writeback": {}, "statement_id": str(statement_id),
            "proof_no": int(proof_no),
        }

    def _terminal_reason(self, *, kind: str, judgment: Mapping[str, Any],
                         verdict: Mapping[str, Any]) -> str:
        """不发签那一转的 `sign_issuance.reason`：说清"为什么不签"，不说"次数没到"。

        两档分开写（`fault` / `unjudged` —— 读的人据此知道下一步该干什么）：fault = 有毛病
        （按缺陷改）、unjudged = 这一问没查成（框架失败：不是判定，也不许当成"有毛病"打回）。
        p247：`verdict` 那一档删了 —— V 的判词只是陈述，不能拿它当"打回"的证据；
        打回只有秘书判 fault 这一条路。
        `kind` 由调用方按与循环同一套判据算好（`fault` / `unjudged`）。
        """
        if kind == "fault":
            return ("这一转秘书语义判定说「有毛病」（fault）⇒ 不发签；这一转就是终局："
                    "已按 fault 打回 F（错在第几步见洗过的转达与 findings）")
        return ("这一转秘书没判成（checked=False）⇒ 不发签；这是框架失败（没查成），"
                "既不是「有毛病」，也不是「没问题」："
                f"{str(judgment.get('reason') or '没有给理由')[:200]}")

    def _manuscript_gate(self, *, sid: str, text: str, manuscript: str) -> dict[str, Any] | None:
        """在册命题的载体闸（业主 2026-11-04 裁定 甲）：没稿 ⇒ 受控拒绝。

        返回 `None` = 放行（这一趟有稿，或调用方是"未在册"那一档 —— 那个分支不走这里）；
        否则返回一份"没查成"的读数（键是 `verify_proof` 初始值那几格，调用方直接摊开）。

        ## 为什么单独一个方法

        反真空判据 d 要能把它打桩成恒放行，然后断言"同一笔调用回到会签"。若这条判据
        写死在 `verify_proof` 里，"a 是红的"就分不清是"闸在工作"还是"别处也恰好走不通"。
        现在老的内联那一支原样留在下面（`listed` / `on_disk` / `proof_text_mismatch`），
        只有这一道闸挡住它 —— 桩一摘，那条路就必须重新走通。

        ## 拒信要指路（不暗示"补个正文就行"）

        `proof_text` 不是缺的那一格：缺的是载体。所以 detail 说三件事 ——
        签块 / `## 依赖` / 按号寻址都只在文件上；落一份稿（只收
        `reports/{f,e,b}-proof-<号>.md`，按号命名是硬条件；`notes/…` 先走转正）；再来。
        一个字节都不审、不落。

        ## 返回里的两个码（D7，2026-11-05 走查）

        `kind` 是档、`reason` 是细则 —— 映射只在 `V_REFUSAL_CODES` 里写一次，
        这里从它取细则码（两格都留的理由见那张表）。
        """
        if str(manuscript or "").strip():
            return None
        if str(text or "").strip():
            why = "这一趟只给了内联正文（`proof_text`）"
        else:
            why = "这一趟既没有正文、也没有手稿（`proof_manuscript`）"
        _code = "proof_manuscript_required"
        return {
            "checked": False,
            "kind": _code,
            "reason": V_REFUSAL_CODES[_code]["reason"],
            "detail": (
                f"命题 {sid} 已登记，而{why} ⇒ 不审、不落签。在册命题也要手稿："
                "签要落在稿上（`- V 签：` 那一行签块）、依赖面从稿的 `## 依赖` 段读、"
                "稿要能被按号寻址（`reports/{f,e,b}-proof-<号>.md`）—— 内联正文这三样都"
                "做不到，所以它不能单独过审。处置：先落一份按号命名的稿（"
                "`reports/f-proof-<号>.md`；`notes/…` 这种认不出裸稿号的稿先走转正，"
                "落成按号命名的那一份），三节按 `## 命题` / `## 证明` / `## 依赖` 写；"
                "写完再带 `proof_manuscript=<那个路径>` 送审。这一趟的正文不必再传："
                "V 从稿里取那一段（参数里同时给 `proof_text` 只作对 sha 的核对）。"
            ),
        }

    def _registered_manuscript_body(self, *, text: str,
                                     manuscript: str, statement_id: str = "") -> dict[str, Any]:
        """在册命题点名的那一份手稿：读 `## 证明` 那一节（2026-11-04，业主裁定 甲）。

        为什么单独一个方法：在册的散文路与穷举路都要做同一件事 —— 认路径、读盘、
        取 `## 证明`、与参数给的正文对 sha。两处各写一遍必然漂，而漂的那一处正好会
        是"散文路读了稿、穷举路还在用内联正文"。

        ## 路径判据

        - 工作区相对、不含盘符 / 以 `/` 开头 / `..`；
        - 稿名必须能被 `vsigns.manuscript_id_of` 认出一个裸稿号
          （`reports/{f,e,b}-proof-<号>.md`）—— 按号命名是硬条件（业主 2026-11-04 裁定
          乙-2）：第 9 格 `手稿号` 与 B 的收录认签都按它；`notes/…` 这种认不出号的稿
          先走转正（`fd9a5e33` 的那一步），落成按号命名的那一份再来；
        - 必须是盘上那一份文件（不收目录、不收不存在的路径）；
        - 必须有一节 `## 证明` 且那一节非空 —— 没有可签的正文，签就没有对象。

        为什么"按号命名"从口味变成硬条件：认不出号的稿会写出第 9 格为空串的签块，
        而 B 的 `manuscript_sign_gate` 对 `manuscript_id_missing` 一律不认 ——
        V 签了、没人能认，等于白签。

        返回 `{"manuscript": 相对路径, "body": 正文}`；失败时
        `{"failed": True, "kind": ..., "reason": ..., "detail": ...}`（`reason` 是
        受控拒信的码，`kind` 给调用方摊进返回值）。
        """
        from .. import depsection as _DS

        rel = str(manuscript or "").strip().replace("\\", "/")
        if (not rel or rel.startswith("/") or ":" in rel
                or ".." in rel.split("/")):
            return {"failed": True, "kind": "bad_manuscript_path",
                    "reason": "bad_manuscript_path",
                    "detail": (f"`proof_manuscript` 要的是工作区相对路径（盘上那一份文件），"
                               f"收到 {manuscript!r} ⇒ 这一格没审、不落签")}
        from .. import vsigns as _VS
        _mid = _VS.manuscript_id_of(rel)
        _carrier = _VS.sign_carrier_reading(rel)
        if not _carrier.get("ok"):
            # 2026-11-05（父裁定）：计划稿是合法的落稿名，但不是签的载体。
            # 这里只判签的那一侧，`parse_manuscript_name` 一个字节都不改（F 的
            # 「先落计划名、拿到号再改名」还要用它）。
            return {"failed": True, "kind": "bad_manuscript_name",
                    "reason": "bad_manuscript_name",
                    "detail": (f"`{rel}` 不是签的载体：{_carrier.get('reason')}"
                               " ⇒ 这一格没审、不落签")}
        if not _mid:
            # 2026-11-04（业主裁定 · 乙-2）：按号命名是硬条件。认不出号的稿会写出
            # 第 9 格为空串的签块，而 B 的 `manuscript_sign_gate` 对
            # `manuscript_id_missing` 一律不认 —— V 签了、没人能认。
            return {"failed": True, "kind": "bad_manuscript_name",
                    "reason": "bad_manuscript_name",
                    "detail": (f"`{rel}` 的稿名认不出裸稿号（只收 "
                               "`reports/{f,e,b}-proof-<号>.md`：第 9 格 `手稿号` 与 B 的"
                               "收录认签都按它）⇒ 这一格没审、不落签。处置：把这份稿"
                               "转正成按号命名的那一份（`reports/f-proof-<命题号>.md`，"
                               "`notes/…` 稿走转正那一步）再来；认不出号的签块 B 不认，"
                               "签了也白签")}
        if (str(statement_id or "").strip() and _mid != str(statement_id).strip()
                # E 的数值证明稿按实验号寻址（`reports/e-proof-<实验号>.md`），
                # 命题号在登记那一行上 ⇒ 这一族的稿号与命题号本来就不同名。
                # 其余两族（F 的证明稿 / B 的改写稿）必须是同一条命题的稿。
                and not rel.startswith("reports/e-proof")):
            # 2026-11-05（业主）：稿号必须就是这一条命题。改前只要求"认得出一个号"，
            # 于是 `reports/b-proof-000016.md` 可以被当成 000014 的证明签下去（第 9 格
            # 写 000016、台账写 000014）—— 签盖错了对象，而没有任何一处会报。
            return {"failed": True, "kind": "bad_manuscript_name",
                    "reason": "bad_manuscript_name",
                    "detail": (f"`{rel}` 的稿号是 {_mid}，而这一签要给 stmt:"
                               f"{str(statement_id).strip()} ⇒ 不审、不落签：签盖的必须是"
                               "这一条命题自己的那一份稿（`reports/{f,b,e}-proof-<命题号>.md`）")}
        path = Path(self.workspace_root) / rel
        if not path.is_file():
            return {"failed": True, "kind": "manuscript_missing",
                    "reason": "manuscript_missing",
                    "detail": (f"`{rel}` 不在盘上（或不是一份文件）⇒ 这一格没审、不落签："
                               "在册命题要签，签的对象必须是盘上那一份手稿")}
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"failed": True, "kind": "manuscript_unreadable",
                    "reason": "manuscript_unreadable",
                    "detail": (f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                               "这一格没审、不落签")}
        body = _DS.proof_body(raw).strip("\n")
        if not body.strip():
            return {"failed": True, "kind": "manuscript_has_no_proof_section",
                    "reason": "manuscript_has_no_proof_section",
                    "detail": (f"`{rel}` 里没有 `## 证明` 那一节（或那一节是空的）⇒ "
                               "没有可审、可签的正文：补上 `## 证明` 再送审")}
        # ---- 2026-11-04（审计缺陷 ③）：缺 `## 依赖` 段不许签 ------------------
        #
        # 业主点名的三样（签块 / 依赖面 / 按号命名）里，依赖面只能从稿的这一节读。
        # 只读 `## 证明` 会签出一份"没有依赖面"的稿，B 收稿时读到空表声明 —— 而那与
        # "作者根本没写"在读数上分不开。空表（四列表头在、0 行）是合法形态（自足证明），
        # 缺整节不是。判据：`temp/probe_manuscript_gate.py` 的 g 组。
        try:
            section = _DS.parse_dependency_section(raw)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有依赖"
            return {"failed": True, "kind": "dependency_section_unreadable",
                    "reason": "dependency_section_unreadable",
                    "detail": (f"`{rel}` 的 `## 依赖` 段读不成（{type(exc).__name__}: {exc}）"
                               "⇒ 不审、不落签")}
        if not section.get("present"):
            return {"failed": True, "kind": "dependency_section_missing",
                    "reason": "dependency_section_missing",
                    "detail": (f"`{rel}` 里没有 `## 依赖` 那一节（四列表）⇒ 不审、不落签："
                               "依赖面只能从稿的这一节读；没有引用任何在册命题也要写一张"
                               "空表（表头在、0 行）—— 空表是声明，缺节不是")}
        if str(section.get("refused") or "").strip():
            return {"failed": True, "kind": "dependency_section_unreadable",
                    "reason": "dependency_section_unreadable",
                    "detail": (f"`{rel}` 的 `## 依赖` 段不合格（{section.get('refused')}）⇒ "
                               "不审、不落签：按四列表头重写那一节再来")}
        given = str(text or "")
        if given.strip() and VR.proof_sha(given) != VR.proof_sha(body):
            return {"failed": True, "kind": "proof_text_mismatch",
                    "reason": "proof_text_mismatch",
                    "detail": (f"参数给的正文与 `{rel}` 的 `## 证明` 不是同一份"
                               f"（参数 sha {VR.proof_sha(given)[:12]}…，盘上 "
                               f"{VR.proof_sha(body)[:12]}…）⇒ 拒绝：签会盖错一份正文；"
                               "在册这一档正文以稿为准，参数里那份只作核对 —— "
                               "要么把 `proof_text` 换成稿里那一份，要么把 `proof_no` 指对")}
        return {"manuscript": rel, "body": body, "raw": raw}

    def _review_b_manuscript(self, *, text: str, manuscript: str = "", no: int = 1,
                             statement_full: str = "") -> dict[str, Any] | None:
        """B 的改写手稿：与 F / E 同一条链（三轮成立 + 收方秘书落签块）。

        ## 业主裁定（逐字，2026-11-04）

            A 甲 —— B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）

        ## 为什么单开一个入口

        B 的稿是在在册命题上改写的：`verify_proof` 若按在册那一支走，会写
        `verifications/<号>.jsonl`、并按台账认签 —— 而这一笔要签的是"B 改写后的
        那一版正文"，它的载体是 `reports/b-proof-<号>.md` 里那一行签块。所以这里
        只做一件事：认出 B 手稿的命名，把它交给与 F/E 完全相同的未在册散文那一支
        （三转 + `vsigns.issue` + `Secretary.land_unregistered_sign`）。收方是 V 的
        parent（B）⇒ `secretary:B` 落块；V 自己一处签写口都没有。

        返回 `None` = 这一份不是 B 的改写手稿（别的路径不在这里开口子）。
        """
        from .. import bmanuscript as _BM

        rel = str(manuscript or "").strip().replace("\\", "/")
        if not _BM.is_relpath(rel):
            return None
        return self._review_unregistered_prose(
            text=text, manuscript=rel, no=no, b_manuscript=True,
            statement_full=str(statement_full or ""))

    def _review_unregistered_prose(self, *, text: str, manuscript: str = "",
                                   no: int = 1, b_manuscript: bool = False,
                                   statement_full: str = "") -> dict[str, Any] | None:
        """未在册的一份散文证明：三转判完把签块盖回它那一份手稿（2026-11-02 起）。

        业主 2026-11-05 晚逐字（这一版的口径）：
        「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签。这是已有口径」。

        所以这一支是正统主路，不是"未在册的例外"：

        - 签的载体是稿上那一行签块（`reports/(f|b|e)-proof-<数字>.md`）；
        - 独立背书的台账是 `verifications/pending/<正文 sha>.jsonl`（三转三行，
          `verification_id` / `at` / `proof_sha256` 三票齐全）；
        - 签块上的 `命题号=未在册` 是合法形态（真机 `f-proof-000019.md` 就是）；
        - B 收录时按正文 sha 从稿上拿签（`vsigns.bits_after_sign` → `sign_ledger_backing`：
          台账指得回 V 的行才算真签，指向稿自己的是假签）。

        ## 判据（与在册那一支同一把尺，判据本体都在 `verifications` / `vsigns`）

        - 三转（`review_pass_bound()` == `verifications.SIGN_STREAK_NEED`）都判「成立」、
          无未解决 error ⇒ 三转各落一行 pending 台账，再写签块（`已签=true；连续=need/need`）；
        - 任一转判出「有毛病」⇒ 立刻停；不写块（2026-11-03 甲口径：负判不是签，
          `draft/178`「V 不写手稿里的签块」），判词落
          `verifications/pending/<正文 sha>.jsonl`，F 的 `delivery_reading` 读成「未通过」；
        - 任一转拿不到合法结论（没缝 / 空回复 / 解析失败）⇒ `checked=False`、一个字节都
          不写（"没查成"不许冒充"审过了"，与 `no_proof_text` 同一条纪律）；
        - 已经签过（稿里已有 sha 相符的签块）⇒ 不重复审、不重复写（同一份正文不重复判）；
        - 计划稿（`*-proof-plan-<数字>`）是合法落稿名，但不是签的载体 ⇒ 签不落它。

        ## 为什么先判满三转再写块

        块是"第 need 转成立那一刻"的档（与 `vsigns.ARTIFACT_SHA_RULE` 同一条）。边判边写的话，
        第 2 转失败会留下第 1 转那一块"已签"——把一次没跑完的送审读成签过。

        返回 `{"block":…, "passes":…, "manuscript":…, "sha":…}`；
        没查成 / 路径不合法 / 稿不在盘上 ⇒ `{"reason","detail","passes"}`。
        """
        from .. import bmanuscript as _BM
        from .. import depsection as _DS
        from .. import vsigns as _VS

        rel = str(manuscript or "").strip().replace("\\", "/")
        body = str(text or "")
        raw_manuscript = ""
        if rel:
            # 入口只认约定命名（`reports/f-proof*.md` / `reports/e-proof-*.md`，以及
            # 2026-11-04 起的 `reports/b-proof-*.md`）：V 读什么由这里定死，
            # 不给"按任意路径读一盘"的口子。
            if b_manuscript:
                _ok_path = _BM.is_relpath(rel)
                _what = "B 的改写手稿（`reports/b-proof-*.md`）"
            else:
                _ok_path = bool(
                    rel.startswith(f"{_DS.MANUSCRIPT_DIR}/{_DS.MANUSCRIPT_STMT_PREFIX}")
                    or rel.startswith(f"{_DS.MANUSCRIPT_DIR}/f-proof"))
                _what = f"F 的证明手稿（`{_DS.MANUSCRIPT_DIR}/f-proof*.md`）"
            if not _ok_path:
                return {"failed": True, "reason": "bad_manuscript_path",
                        "detail": (f"`proof_manuscript` 只收 {_what}，收到 {rel!r}")}
            try:
                raw_manuscript = (Path(self.workspace_root) / rel).read_text(encoding="utf-8")
            except OSError as exc:
                return {"failed": True, "reason": "manuscript_missing",
                        "detail": (f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                                   "这一份没审成（未在册送审要指向盘上那一份稿）")}
            # 签名对象必须与"登记时那一份正文"逐字相同：`proof_body` 取的是小节正文，
            # 带 markdown 的空行（首尾各一个 `\n`）；而 F 交给 B 的 `proof_text` 是逐行
            # join 的那一串（没有首尾空行）。所以这里只去掉首尾换行 —— 否则签块里的 sha
            # 与 B 登记时算的 sha 永远差一个换行，签永远认不上（这条链的静默断点）。
            on_disk = _DS.proof_body(raw_manuscript).strip("\n")
            if not body.strip():
                body = on_disk
            elif on_disk.strip() and VR.proof_sha(on_disk) != VR.proof_sha(body):
                return {"failed": True, "reason": "proof_text_mismatch",
                        "detail": (f"参数给的正文与 `{rel}` 的「## 证明」不是同一份"
                                   f"（参数 sha {VR.proof_sha(body)[:12]}…，盘上 "
                                   f"{VR.proof_sha(on_disk)[:12]}…）⇒ 拒绝：签会盖错一份正文")}
            # 2026-11-04（审计缺陷 ③）：缺 `## 依赖` 段不许签（空表合法，见
            # `_registered_manuscript_body` 同一段注释）。三处读稿口同一把尺。
            _section = _DS.parse_dependency_section(raw_manuscript)
            if not _section.get("present"):
                return {"failed": True, "reason": "dependency_section_missing",
                        "detail": (f"`{rel}` 里没有 `## 依赖` 那一节（四列表）⇒ 不审、不落签："
                                   "依赖面只能从稿的这一节读；没有引用也要写一张空表"
                                   "（表头在、0 行）")}
            if str(_section.get("refused") or "").strip():
                return {"failed": True, "reason": "dependency_section_unreadable",
                        "detail": (f"`{rel}` 的 `## 依赖` 段不合格"
                                   f"（{_section.get('refused')}）⇒ 不审、不落签")}
        if not body.strip():
            return None
        #: 依赖面的机械审计（业主 2026-11-06：V 是第一道）：与在册那一支同一份判据，
        #: 2026-11-08 起可引资格也读被引命题的手稿（V 只对手稿负责）；没有稿
        #: （只有内联正文）时这一格不核。
        _deps = _DS.parse_dependency_section(raw_manuscript) if raw_manuscript else {}
        _cited = _cited_manuscripts(
            self.workspace_root, (_deps.get("rows") or [])) if _deps else {}
        dependency_audit = self._dependency_audit(raw_manuscript, _cited)
        sha = VR.proof_sha(body)
        if raw_manuscript:
            already = _VS.manuscript_sign_standing(raw_manuscript, proof_sha=sha)
            if str(already.get("state") or "") == "signed":
                return {"block": already, "passes": [], "manuscript": rel, "sha": sha,
                        "already": True,
                        "reason": (f"`{rel}` 里已经有盖住这一份正文的签块"
                                   f"（{already.get('why')}）⇒ 不重复审、不重复写")}
        if b_manuscript:
            # B 的改写手稿：命题可能已经在册（改写就是在册那一版的替身），但被签的
            # 对象始终是这份稿里「## 证明」那一节 —— 审阅口径与 F/E 同一份提示词，
            # 只把"这是谁的稿、签往哪落"如实说清。
            _facts = (
                "这一份是 B 改写后的证明手稿"
                + (f"（在册命题的完整正文：{statement_full.strip()[:400]}）"
                   if str(statement_full or "").strip() else "（命题还没在册）")
                + "：你只按下面这份证明正文本身重读；审过之后签会落回这一份手稿"
                  "（`reports/b-proof-<命题号>.md` 里的签块），B 带这份稿入库时读到它。")
        else:
            _facts = ("这一条命题还没给命题号（V 只读手稿，不查台账；命题正文读不到）："
                      "你只按下面这份证明正文本身重读；签会落进这一份手稿，"
                      "等 B 收录这条命题时随稿读到。")
        prompt = VR.cold_start_prompt(
            UNREGISTERED_STATEMENT_PAGE, body, readonly_facts=_facts)
        need = review_pass_bound()
        judged: list[dict[str, Any]] = []
        passes: list[dict[str, Any]] = []
        stopped = ""
        for n in range(1, int(need) + 1):
            asked = prompt if n <= 1 else prompt + REVIEW_PASS_NOTE.format(n=n)
            reply, problem = self._ask(asked)
            if problem:
                return {"failed": True,
                        "reason": f"judge_not_wired:{problem}" if not reply else problem,
                        "detail": (f"第 {n} 转没拿到审阅回复（{problem}）⇒ 这一份没查成："
                                   "一个字节都不写（缺材料不落签）"),
                        "passes": passes, "manuscript": rel}
            try:
                verdict = VR.parse_verdict(reply)
            except VR.VerificationError as exc:
                return {"failed": True, "reason": "unparsable",
                        "detail": (f"第 {n} 转的输出不是合法结论（{exc}）⇒ 这一份没查成："
                                   "一个字节都不写"),
                        "passes": passes, "manuscript": rel}
            #: 依赖面六项审计（业主 2026-11-06）：机械缺陷并进这一转的结论。
            verdict = merge_dependency_audit(verdict, dependency_audit)
            #: p247：轴由 V 的秘书语义判定（V 的判词只是陈述）。
            #: `source` 随这一份判定一起落账（pending 行与返回值顶层读的是同一格）：
            #: 散文支的轴来路就是这一问，不从别处推断。
            judgment = dict(self._judge_v_reply(reply, verdict, no))
            judgment.setdefault("source", "secretary:v_reply_defect")
            if (str(judgment.get("axis") or "") == "fault"
                    and verdict.get("defect_step") is None):
                _sec_step = judgment.get("defect_step")
                if isinstance(_sec_step, int) and not isinstance(_sec_step, bool):
                    verdict = dict(verdict, defect_step=_sec_step)
            axis = str(judgment.get("axis") or "")
            word = VR.read_verdict(verdict)
            unresolved = int(verdict.get("unresolved_errors") or 0)
            judged.append({"pass": n, "verdict": verdict, "judgment": judgment})
            passes.append({"pass": n, "axis": axis, "verdict": word,
                           "unresolved_errors": unresolved,
                           "defect_step": verdict.get("defect_step"),
                           "terminal": ""})
            self._emit(f"verify_proof(未在册)：第 {n} 转 {word}"
                       f"（秘书轴={axis or '没查成'}，未解决 error {unresolved} 条）")
            if not judgment.get("checked"):
                # 秘书这一问没查成 ⇒ 这一份不签（不是 fault，也不是 clean）。
                stopped = "unjudged"
                passes[-1]["terminal"] = stopped
                break
            if axis == "fault" or unresolved != 0:
                stopped = "rejected"
                passes[-1]["terminal"] = stopped
                break
        else:
            stopped = "signed"
            if passes:
                passes[-1]["terminal"] = stopped
        # ---- 2026-11-04（甲）：没有手稿 ⇒ 只能"看过"，不能签 ---------------------
        #
        # 未在册 + 没给 `proof_manuscript` + 只给内联正文：这一趟仍然可以判（"允许
        # 临时核对"），但没有可落签的载体 —— 签块、`## 依赖` 段、按号命名的稿
        # 都只在文件上。所以判完把终局改成 `reviewed_unsigned`：不颁发签、不写 pending
        # 台账（那一行会被 B 当第三方签认领），只把"看过、没签"的读数带回去。
        # 负判照旧落 pending（那是打回的凭据，不是签）；正判而无稿这一档不许留签。
        if stopped == "signed" and not rel:
            stopped = "reviewed_unsigned"
            if passes:
                passes[-1]["terminal"] = stopped
        at = _now_iso()
        last = judged[-1]["verdict"] if judged else {}
        #: p247：V 的判词只是陈述 —— 签没签不代表它写成「成立」；原样回放。
        verdict_word = str(last.get("verdict") or "")
        streak = len(judged) if stopped == "signed" else 0
        # ---- 甲（2026-11-03）：负判不是签，不写手稿块 ----------------------------
        #
        # `draft/178` 的边界逐字：「V 不写手稿里的签块（`- V 签：` 那一行）」；
        # 手稿块只由收方秘书落（`written_by=secretary:F|B`）。改前这一支在
        # 「有毛病」那一转也调 `write_manuscript_sign(signed=False)`，把
        # `已签=false；判词=有毛病；签名者=agent-V` 写进 F 的稿（86 真机的现场）。
        # 负判不是签：块一旦出现，读侧就多一个「签过一次（没成）」的落点，
        # 而业主的口径是「负判直接打回、不是签」。
        #
        # 判词改落 `verifications/pending/<正文 sha>.jsonl`（D-34 的未在册台账）：
        # 那一行是 V 自己的账（不是手稿），`pending_sign` 的「最近一次审校说了算」
        # 会把它读成 rejected，F 的 `delivery_reading` 因此仍读得到「未通过」。
        #
        # 正判且给了手稿（2026-11-03 件一）：V 不直接写块，与在册那条路同形 ——
        # `vsigns.issue()` 出信封（`out/vsigns/<正文 sha>.json`），落签只经收方秘书的
        # `Secretary.land_unregistered_sign()`（件三：V 这边 0 处签写口）。收方 = V 的
        # parent 那一侧（送审者），身份由秘书从 `conductor.current_parent()` 读；读不到就
        # "能颁发、不能落块"，不猜一个 F/B。
        pending: dict[str, Any] = {}
        issued: dict[str, Any] = {}
        landed: dict[str, Any] = {}
        block_write: dict[str, Any] = {
            "written": False, "idempotent": False, "missing": False,
            "state": "not_attempted", "path": rel, "line": 0, "reading": {},
            "code": "", "body_mismatch": False, "body_sha256": "", "signed_sha256": "",
            "why": ("负判不写手稿块（甲：V 只颁发；块只由收方秘书落）"
                    if stopped != "signed" else "没有手稿落点"),
        }
        if stopped == "signed" and rel:
            # ---- 2026-11-05 晚（业主）：计划稿是合法落稿名，但不是签的载体 --------
            #
            # 「先落计划名、拿到号再改名」是 F 的既有工作流，`parse_manuscript_name`
            # 一个字节都不改；但签只认 `reports/(f|b|e)-proof-<数字>.md`。真机
            # `f-proof-plan-000011` 上那块 3/3 就是从这里放进来的。判在写 pending 台账
            # 之前：盘上不留"永远认领不了"的行。三转读数照给（看过、没签），只是不构成签。
            _carrier = _VS.sign_carrier_reading(rel)
            if not _carrier.get("ok"):
                stopped = "reviewed_unsigned"
                block_write["code"] = str(_carrier.get("code") or "not_a_sign_carrier")
                block_write["why"] = (
                    f"`{rel}` 不是签的载体：{_carrier.get('reason') or ''}"
                    " ⇒ 看过、没签（三转读数照给，一个签字节都不落：不落 pending 台账、"
                    "不颁发签文件、稿上不写签块）")
        if stopped == "signed" and rel:
            # ---- 2026-11-05 晚（业主）：没号先签是正统主路 --------------------
            #
            # 原话：「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签。这是已有口径」。
            # 所以这一档不是「被拒的未在册」，而是主路：
            #   ① 三转各落一行 `verifications/pending/<正文 sha>.jsonl`（一行一转 ⇒
            #      `verification_id` / `at` / `proof_sha256` 三票齐全，不是三个空对象）；
            #   ② 签照旧由收方秘书落回稿上（`reports/(f|b|e)-proof-<数字>.md` 的签块）；
            #   ③ 签文件里的 `ledger` 指最后一转那一行（pending 台账 = 这一签的独立背书）。
            # 改前这一档在 `vsigns.issue` 的 "没有命题号 ⇒ 不签" 那道闸上整条死掉：
            # 三转判完一个字节都不写（探针 `before.txt` ①：盘上连 `verifications/` 都没有）。
            try:
                pending_rows = [VR.record_pending_sign(
                    self.workspace_root, proof_text=body, verdict=judged[i]["verdict"],
                    verifier=self.actor, object_path=rel,
                    secretary_judge=judged[i].get("judgment"))
                    for i in range(len(judged))]
            except Exception as exc:  # noqa: BLE001 —— D4：写口抛什么都要落成红读数
                # 2026-11-05（D4）：改前只收 `VerificationError` / `OSError`，写口抛别的
                # 异常（反真空探针 `ws-vacuum2` 的 `RuntimeError`）会穿透 `verify_proof`。
                return {"failed": True, "checked": False, "reason": "ledger_unwritable",
                        "detail": (f"pending 台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                                   "这一份没查成（签没有落点，必须重审）"),
                        "passes": passes, "manuscript": rel,
                        "secretary_judge": (dict(judged[-1].get("judgment") or {})
                                            if judged else {})}
            pending = pending_rows[-1] if pending_rows else {}
            passes = _passes_with_tickets(passes, pending_rows)
            block_write, issued, landed = self._issue_and_land_unregistered(
                rel=rel, sha=sha, streak=streak, need=need, no=no,
                passes=passes, at=at, block_write=block_write,
                ledger=_pending_ledger_ref(pending))
        elif stopped == "reviewed_unsigned":
            # 看过、没签：这一档一个字节都不写（没有稿 / 计划稿都没有签的落点）。
            # 不落 pending：那一行按正文 sha 可认领，B 会把它当"有人签过"。
            # 计划稿那一档的 `why` 已经在上面写好（`code` 非空）⇒ 不覆盖它。
            if not str(block_write.get("code") or "").strip():
                block_write["why"] = (
                    "没有手稿（`proof_manuscript`）⇒ 只能看过、不能签："
                    "签块 / `## 依赖` 段 / 按号命名这三样都只在文件上")
        else:
            # 负判：只落 pending 台账（不写块）；正判而没有手稿落点：签也只能落这里。
            try:
                pending = VR.record_pending_sign(
                    self.workspace_root, proof_text=body, verdict=last,
                    verifier=self.actor, object_path=rel,
                    secretary_judge=(judged[-1].get("judgment") if judged else None))
            except Exception as exc:  # noqa: BLE001 —— D4：写口抛什么都要落成红读数
                # 同上一支：判词没有落点也是「这一份没查成」，不许把异常抛给调用方。
                return {"failed": True, "checked": False, "reason": "ledger_unwritable",
                        "detail": (f"pending 台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                                   "这一份没查成（判词没有落点，必须重审）"),
                        "passes": passes, "manuscript": rel,
                        "secretary_judge": (dict(judged[-1].get("judgment") or {})
                                            if judged else {})}
        reading = dict(block_write.get("reading") or {})
        return {"block": reading, "passes": passes, "manuscript": rel, "sha": sha,
                "stopped": stopped, "block_write": block_write,
                "issued": issued, "landed": landed,
                "pending": pending,
                #: 2026-11-06：轴那一格带到顶层（`_finish_unregistered` 原样搬到返回值）。
                "secretary_judge": (dict(judged[-1].get("judgment") or {})
                                    if judged else {}),
                "verdict": verdict_word, "findings": list(last.get("findings") or []),
                "defect_step": last.get("defect_step"),
                "unresolved_errors": int(last.get("unresolved_errors") or 0),
                "reason": (("（未在册）" + (str(block_write.get("why") or "")
                                            or ("看过、没签：没有手稿（`proof_manuscript`）"
                                                "⇒ 这一签没有载体，签只能落在稿上")))
                           if stopped == "reviewed_unsigned"
                           else ("（未在册）"
                                 + (str(block_write.get("why") or "") if stopped == "signed"
                                    else (f"判「{verdict_word}」：负判不写手稿块，判词落 "
                                          f"`{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/`"
                                          f"（{pending.get('verification_id') or '没编号'}）"))))}

    def _review_unregistered_exhaustion(self, *, text: str, manuscript: str = "",
                                        no: int = 1) -> dict[str, Any] | None:
        """未在册的一份穷举证明：三轮会审 + 收方秘书落签块（2026-11-03）。

        ## 业主逐字（这是本方法存在的唯一理由）

        > 「E 在数值证明拿 V 签的时候流程和 F 一模一样，若未实现请先实现」

        ## 改前差在哪（三处，逐条对得上真机读数）

        1. E 没有「手稿」：穷举证据只有 `out/experiments/<实验号>/exhaustion.md`
           （②③ 的读数，没有 `## 证明` 那一节）⇒ `_review_unregistered_prose` 的入口
           守卫（只认 `reports/f-proof*.md`）把它拒成 `bad_manuscript_path`；
        2. 收方没有人：`vsigns.SECRETARY_OF` 只有 F / B ⇒ E 派 V 的那一签
           「能颁发、没人能落」（`not_a_secretary`），稿上永远没有签块；
        3. 签是自报的：`experiments.observations.e_signature.signed_by="V"` 是 E 在
           `build_experiment` 里自己写的（`numericproof.suspect_self_signed` 报的就是它）。

        改后这一支与 F 那条路同一套：同一份 `reports/*.md` 手稿形状、同一个三轮门槛
        （`review_pass_bound()` == `verifications.SIGN_STREAK_NEED`）、同一次
        `vsigns.issue()` 出信封、同一个收方秘书的落签方法（`land_unregistered_sign`，
        块的 9 格、`手稿号`、`正文sha` 全由 `vsigns` 那一侧判）。
        唯一的差别是「判词从哪来」：散文那一支问模型（冷启动逐行读），这一支走七项机械会审
        （`exhaustionreport.review`，2026-10-23 的既定口径：穷举证据不按逐行读证明文本审）。
        三轮都过才发签 —— 与 F 一样，"一次成立"不算签。

        ## 为什么正判也要落一行 pending

        B 的入库闸（`numericproof.filing_problems`）认 E 这一路的第三方签字时读的是
        `verifications/pending/<对象 sha>.jsonl`（`latest_third_party_sign` 的第二路）。
        F 那一侧 B 读的是手稿块（`manuscript_sign_standing`），E 这一侧两条都读 ——
        所以正判时"手稿块"与"台账行"都要落：少前者，E 的稿上没有签；少后者，
        B 即使看到块也过不了 `proof` 档的第三方签字闸。

        返回 `None` = 这一份不是穷举型证据 / 找不到 E 的手稿（交给散文与 pending 那两支）；
        否则返回与 :meth:`_review_unregistered_prose` 同形的 dict（`_finish_unregistered` 读）。
        """
        from .. import depsection as _DS
        from .. import exhaustionreport as _ER
        from .. import numericproof as _NP
        from .. import vsigns as _VS

        body = str(text or "")
        rel = str(manuscript or "").strip().replace("\\", "/")
        explicit = bool(rel)
        exp_rows: list = []
        try:
            if self.store is not None:
                exp_rows = list(self.store.rows("experiments"))
        except (StoreError, AttributeError, TypeError):
            exp_rows = []
        # ---- 只认参数给的那份手稿（与 F 那一支同一条入口守卫） -------------------
        #
        # 为什么不按证明栏自己去实验台账里反查一份稿：F 的落块那一路也只认
        # `proof_manuscript` 参数（`agent_v.core._review_unregistered_prose` 的入口守卫）——
        # "谁送审"由送审方点名，V 不替它去盘上猜一份（猜错就把签盖到别人那份稿上）。
        # 两条实验共用同一份程序时，"按 `code_path` 反查"还会挑到第一条（真机形态），
        # 签核的就会是别人那份报告的 sha。所以 E 要拿到手稿签块，就在送审时点名那份稿
        # （`E.run_experiment` 的返回值里 `proof_manuscript` 就是这一格）。
        if not rel or not _ER.is_manuscript_relpath(rel):
            return None
        # 这份稿属于哪条实验：稿名里那个实验号是唯一不会歧义的键（两条实验共用
        # 同一份程序时，按 `code_path` 反查会挑到第一条 —— 那样签核的是别人那份报告）。
        eid = _ER.experiment_id_of(rel)
        row = next((dict(r) for r in exp_rows
                    if str(r.get("experiment_id") or "") == eid), None)
        read = _ER.read_proof_manuscript(self.workspace_root, rel)
        if not read.get("ok"):
            if not explicit:
                # 稿是"按证明栏反查出来的"、而盘上没有 ⇒ 这一档不是"送审指错了稿"，
                # 而是"这一条还没有那份手稿"（存量工作区就是这个形态）⇒ 退回 pending
                # 那一支（老行为：结论照样落盘，只是没有稿可签）。
                return None
            return {"failed": True, "reason": "manuscript_missing",
                    "detail": (f"`{rel}` 读不出来（{read.get('state')}："
                               f"{'；'.join(str(p) for p in read.get('problems') or [])}）⇒ "
                               "这一份没审成（未在册的穷举证明要指向盘上那一份稿）"),
                    "passes": [], "manuscript": rel}
        on_disk = str(read.get("proof_body") or "").strip("\n")
        if not on_disk.strip():
            return {"failed": True, "reason": "manuscript_empty",
                    "detail": f"`{rel}` 的 `## 证明` 那一节没有正文 ⇒ 没有可审/可签的对象",
                    "passes": [], "manuscript": rel}
        if not body.strip():
            body = on_disk
        elif VR.proof_sha(on_disk) != VR.proof_sha(body):
            return {"failed": True, "reason": "proof_text_mismatch",
                    "detail": (f"参数给的正文与 `{rel}` 的「## 证明」不是同一份"
                               f"（参数 sha {VR.proof_sha(body)[:12]}…，盘上 "
                               f"{VR.proof_sha(on_disk)[:12]}…）⇒ 拒绝：签会盖错一份正文"),
                    "passes": [], "manuscript": rel}
        if not _ER.is_exhaustion_column({"proof_text": body}, exp_rows):
            return None
        # 2026-11-04（审计缺陷 ③）：缺 `## 依赖` 段不许签（空表合法）。
        _section = _DS.parse_dependency_section(read.get("text") or "")
        if not _section.get("present"):
            return {"failed": True, "reason": "dependency_section_missing",
                    "detail": (f"`{rel}` 里没有 `## 依赖` 那一节（四列表）⇒ 不审、不落签："
                               "依赖面只能从稿的这一节读；没有引用也要写一张空表"
                               "（表头在、0 行）"),
                    "passes": [], "manuscript": rel}
        if str(_section.get("refused") or "").strip():
            return {"failed": True, "reason": "dependency_section_unreadable",
                    "detail": (f"`{rel}` 的 `## 依赖` 段不合格"
                               f"（{_section.get('refused')}）⇒ 不审、不落签"),
                    "passes": [], "manuscript": rel}
        sha = VR.proof_sha(body)
        already = _VS.manuscript_sign_standing(read.get("text") or "", proof_sha=sha,
                                              manuscript_path=rel)
        if str(already.get("state") or "") == "signed":
            return {"block": already, "passes": [], "manuscript": rel, "sha": sha,
                    "already": True,
                    "reason": (f"`{rel}` 里已经有盖住这一份正文的签块"
                               f"（{already.get('why')}）⇒ 不重复审、不重复写")}
        # ---- 三轮：每一轮都重读盘上那一份报告（机械会审，不问模型） ----
        need = review_pass_bound()
        failure, judged, passes, stopped, reviewed = self._review_exhaustion_rounds(
            body=body, exp_rows=exp_rows, row=row, rel=rel, need=need)
        if failure is not None:
            # 缺材料 ⇒ 没查成的那份读数原样返回（不是负判：这一份没审下来）；
            # 已判过的几转照旧带出去（轴读数不许丢），空表 = 一转都没判到。
            failure = dict(failure)
            failure["secretary_judge"] = (dict(judged[-1].get("judgment") or {})
                                          if judged else {})
            #: 会审七项读数不能丢（detail 里承诺了它在 `exhaustion_review` 里；缺材料
            #: 那一档同样是"会审跑完了、只是盘上缺一块"）。
            if reviewed:
                failure["exhaustion_review"] = dict(reviewed)
            return failure
        at = _now_iso()
        last = judged[-1]["verdict"] if judged else {}
        verdict_word = "成立" if stopped == "signed" else VR.read_verdict(last)
        streak = len(judged) if stopped == "signed" else 0
        pending: dict[str, Any] = {}
        issued: dict[str, Any] = {}
        landed: dict[str, Any] = {}
        block_write: dict[str, Any] = {
            "written": False, "idempotent": False, "missing": False,
            "state": "not_attempted", "path": rel, "line": 0, "reading": {},
            "code": "", "body_mismatch": False, "body_sha256": "", "signed_sha256": "",
            "why": ("负判不写手稿块（V 只颁发；块只由收方秘书落）"
                    if stopped != "signed" else "没有手稿落点"),
        }
        # ---- 台账那一行：正判也要落（B 的第三方签字闸读的就是它） ----
        #
        # 2026-11-05 晚：正判那一档与散文那条路同一把尺 —— 一转一行，三转就是三张
        # 真票（`verification_id` / `at` / `proof_sha256` 齐全），签的 `passes` 直接从
        # 这三行取；负判只落判词那一行（负判不是签）。改前正判也只落一行、`passes` 三格
        # 是空的 ⇒ `sign_object_gate` 的 `passes_incomplete` 会拒它。
        try:
            if stopped == "signed":
                pending_rows = [VR.record_pending_sign(
                    self.workspace_root, proof_text=body, verdict=judged[i]["verdict"],
                    verifier=self.actor,
                    object_sha256=str(reviewed.get("report_sha256") or ""),
                    object_path=(str(reviewed.get("report_path") or "") or rel),
                    secretary_judge=judged[i].get("judgment"))
                    for i in range(len(judged))]
                pending = pending_rows[-1] if pending_rows else {}
                passes = _passes_with_tickets(passes, pending_rows)
            else:
                pending = VR.record_pending_sign(
                    self.workspace_root, proof_text=body, verdict=last,
                    verifier=self.actor,
                    object_sha256=str(reviewed.get("report_sha256") or ""),
                    object_path=(str(reviewed.get("report_path") or "") or rel),
                    secretary_judge=(judged[-1].get("judgment") if judged else None))
        except Exception as exc:  # noqa: BLE001 —— D4：写口抛什么都要落成红读数
            # 穷举那一支的 pending 写口同理：改前只收 VerificationError / OSError。
            return {"failed": True, "checked": False, "reason": "ledger_unwritable",
                    "detail": (f"pending 台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                               "这一份没查成（判词没有落点，必须重审）"),
                    "passes": passes, "manuscript": rel,
                    "secretary_judge": (dict(judged[-1].get("judgment") or {})
                                        if judged else {})}
        if stopped == "signed":
            block_write, issued, landed = self._issue_and_land_unregistered(
                rel=rel, sha=sha, streak=streak, need=need, no=no,
                passes=passes, at=at, block_write=block_write,
                ledger=_pending_ledger_ref(pending))
        reading = dict(block_write.get("reading") or {})
        return {"block": reading, "passes": passes, "manuscript": rel, "sha": sha,
                "stopped": stopped, "block_write": block_write,
                "issued": issued, "landed": landed, "pending": pending,
                #: 2026-11-06：轴那一格带到顶层（与散文那一支同形；穷举支的 source
                #: 是 `exhaustion_report`，不是秘书）。
                "secretary_judge": (dict(judged[-1].get("judgment") or {})
                                    if judged else {}),
                "verdict": verdict_word, "findings": list(last.get("findings") or []),
                "defect_step": last.get("defect_step"),
                "unresolved_errors": int(last.get("unresolved_errors") or 0),
                "reason": ("（未在册·穷举）"
                           + (str(block_write.get("why") or "") if stopped == "signed"
                              else (f"判「{verdict_word}」：负判不写手稿块，判词落 "
                                    f"`{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/`"
                                    f"（{pending.get('verification_id') or '没编号'}）")))}

    def _review_exhaustion_rounds(
        self, *, body: str, exp_rows: list, row: dict[str, Any] | None, rel: str,
        need: int,
    ) -> tuple[dict[str, Any] | None,
               list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
        """未在册穷举证明的机械会审：三轮都过才发签，返回 `(缺材料读数, judged, passes, stopped, reviewed)`。

        ## 为什么是七项机械会审而不是逐行读
        穷举证据的既定口径（`exhaustionreport.review`，2026-10-23）：它不按散文证明那样
        逐行问模型，而是每一轮都重读盘上那一份报告（`out/experiments/<实验号>/exhaustion.md`
        的 ②③ 读数）。门槛与 F 那条路同一个 `need`（`review_pass_bound()` ==
        `verifications.SIGN_STREAK_NEED`）：一轮成立不算签，三轮都成立才算。

        ## 三态（第一个返回值）
        `None` = 这一趟审下来了，`stopped` 是 `"signed"` / `"rejected"`；
        非 `None` = 某一轮缺材料 ⇒ 调用方原样返回它，那是「没查成」
        （`reason=MISSING_MATERIAL_REASON`），不是负判 —— 负判是审了、结论不是成立。

        ## `passes` 里的 `terminal`
        只有最后一转带 `terminal`（签的那一转 / 判负的那一转）；中间那几转是空串。
        `judged` 与 `passes` 一一对位（`judged[i]["verdict"]` 是第 i 转的判词整份读数）。
        """
        from .. import exhaustionreport as _ER

        judged: list[dict[str, Any]] = []
        passes: list[dict[str, Any]] = []
        stopped = ""
        reviewed: dict[str, Any] = {}
        for n in range(1, int(need) + 1):
            reviewed = _ER.review(workspace_root=self.workspace_root,
                                  statement={"proof_text": body}, experiments=exp_rows,
                                  # 钉到这份稿自己那条实验（`experiment_row` 优先于按程序反查）
                                  experiment_row=row)
            verdict = _ER.verdict_of(reviewed)
            word = str(verdict.get("verdict") or "")
            missing = [str(m) for m in (reviewed.get("missing") or [])]
            missing_detail = missing_material_detail(verdict, missing)
            if missing_detail:
                self._emit(f"verify_proof(未在册·穷举)：第 {n} 转缺材料 —— 没查成（{missing}）")
                return ({"failed": True, "reason": MISSING_MATERIAL_REASON,
                         "detail": missing_detail, "passes": passes, "manuscript": rel},
                        judged, passes, stopped, reviewed)
            #: p247：穷举这一档没有 V 的散文回复 —— 轴由机械会审自己的两态读数给
            #: （`_ER.VERDICT_OK` ⇒ clean / `_ER.VERDICT_BAD` ⇒ fault），并写成与
            #: 秘书判定同形的 `secretary_judge`（`source=exhaustion_report`）。这不是
            #: 按 V 的 `verdict` 字面定轴：这一格的 `verdict` 就是会审的机械结论本身。
            _axis = ("clean" if word == str(_ER.VERDICT_OK)
                     else ("fault" if word == str(_ER.VERDICT_BAD) else ""))
            judgment = {
                "checked": bool(_axis), "axis": _axis, "decision": word,
                "reason": str(reviewed.get("why") or reviewed.get("reason") or ""),
                "basis": [f"exhaustion_report={word}"],
                "source": "exhaustion_report",
                "defect_step": verdict.get("defect_step"),
            }
            judged.append({"pass": n, "verdict": verdict, "judgment": judgment})
            passes.append({"pass": n, "axis": _axis, "verdict": word,
                           "unresolved_errors": int(verdict.get("unresolved_errors") or 0),
                           "defect_step": verdict.get("defect_step"),
                           "terminal": ""})
            self._emit(f"verify_proof(未在册·穷举)：第 {n} 转 {word}"
                       f"（{len(reviewed.get('checks') or [])} 项检查）")
            if _axis != "clean":
                stopped = "rejected"
                passes[-1]["terminal"] = stopped
                break
        else:
            stopped = "signed"
            if passes:
                passes[-1]["terminal"] = stopped
        return None, judged, passes, stopped, reviewed

    def _issue_and_land_unregistered(self, *, rel: str, sha: str, streak: int,
                                     need: int, no: int,
                                     passes: list[dict[str, Any]], at: str,
                                     block_write: dict[str, Any],
                                     ledger: str = ""
                                     ) -> tuple[dict[str, Any], dict[str, Any],
                                                dict[str, Any]]:
        """未在册正判的那一笔：V 出信封，秘书落（2026-11-03 件三）。

        为什么单独一个方法：`_review_unregistered_prose` 已经接近 200 行（repo survey
        的软判据按函数量体量），把"颁发 + 落签"这一段抽出来，判据那一边一行不增。

        ## `ledger`：这一签的独立背书（2026-11-05 晚，业主）
        没号那一档的 `ledger` 必须是 `verifications/pending/<正文sha>.jsonl#u-<号>`
        （调用方给，:func:`_pending_ledger_ref` 是唯一的拼法）。改前这里写死
        `f"{rel}#V签"` —— 那正是「稿头自述当台账」的假签形状（真机
        `b-proof-000016` / `f-proof-plan-000011`），`vsigns.sign_object_gate` 现在会拒它。

        ## V 只做颁发这一半（结构判据，不靠约定）
        改前这里直接 `vsigns.land(by=<从 conductor 读来的角色>)` —— `by=` 只是 V 的代码
        写的一句话，"落签在秘书"是约定的。现在落签只经
        :meth:`Secretary.land_unregistered_sign`：V 把 `vsigns.issue()` 的整份返回交过去，
        块落哪一份稿、台账位翻不翻，都由秘书那一侧判（`agent_v/` 里 0 处签写口）。

        收方身份（`by=` 与信封的 `to`）也由秘书给（`Secretary.actor_label`）：它是
        "这一签该由谁落"的唯一来源；读不到 ⇒ 空串 ⇒ 能颁发、不能落块，不猜一个 F/B。

        返回 `(block_write, issued, landed)`：三格都是读数，`block_write` 是收尾
        （`_finish_unregistered`）读的那一格。
        """
        from .. import vsigns as _VS

        sec = self._secretary()
        who = ""
        if sec is not None:
            try:
                who = str(getattr(sec, "actor_label", "") or "")
            except Exception:  # noqa: BLE001 —— 读不到收方不是失败：就是"没有收方秘书"
                who = ""
        issued: dict[str, Any] = {}
        landed: dict[str, Any] = {}
        try:
            issued = _VS.issue(
                self.workspace_root, artifact_sha=sha, streak=streak, need=need,
                artifact_path=rel, ledger=ledger, statement_id="",
                proof_no=no, passes=passes, at=at, by=who)
        except Exception as exc:  # noqa: BLE001 —— 颁发抛了也要如实报
            issued = {"written": False, "reason": (
                f"颁发那一笔抛了（{type(exc).__name__}: {exc}）"), "path": ""}
        if issued.get("written") or issued.get("idempotent"):
            land_fn = getattr(sec, "land_unregistered_sign", None) if sec is not None else None
            if not callable(land_fn):
                # 反真空的那一档：方法被摘掉 / 这一趟没有秘书 ⇒ 签颁发了也没人落块。
                landed = {
                    "landed": False, "state": "refused", "code": "no_landing_method",
                    "reason": (f"{self.secretary_problem or '这一趟没有落签的秘书'}"
                               " ⇒ 签已颁发，但没有人落块：F 的读数仍是「待签」"),
                    "manuscript_write": {}, "ledger_bit": "not_attempted", "by": who}
            else:
                try:
                    landed = land_fn(issued)
                except Exception as exc:  # noqa: BLE001 —— 签已颁发，落签抛了要如实报
                    landed = {"landed": False, "state": "refused", "code": "land_raised",
                              "reason": f"落签那一笔抛了（{type(exc).__name__}: {exc}）",
                              "manuscript_write": {}, "ledger_bit": "not_attempted",
                              "by": who}
        mw = dict(landed.get("manuscript_write") or {})
        block_write.update(
            written=bool(mw.get("written")),
            idempotent=bool(mw.get("idempotent")),
            missing=bool(mw.get("missing")),
            state=str(mw.get("state") or (
                "failed" if (issued.get("written") or issued.get("idempotent"))
                else "not_attempted")),
            path=str(mw.get("path") or rel),
            line=int(mw.get("line") or 0),
            reading=dict(mw.get("reading") or {}),
            code=str(landed.get("code") or mw.get("code") or ""),
            body_mismatch=bool(landed.get("body_mismatch")),
            body_sha256=str(mw.get("body_sha256") or ""),
            signed_sha256=str(mw.get("signed_sha256") or ""),
        )
        if block_write["written"]:
            block_write["why"] = (
                f"签由收方秘书 {who or '（没有收方秘书）'} 落进 `{rel}`"
                f"（连续 {streak}/{need} 成立；V 只颁发，不写块）")
        elif issued.get("written") or issued.get("idempotent"):
            block_write["why"] = (
                f"签已颁发（`{issued.get('path') or '签文件'}`，信封→"
                f"{who or '（没有收方秘书）'}），但块没落："
                f"{landed.get('reason') or issued.get('reason') or '没有理由'}")
        elif str(issued.get("code") or "") == _VS.STATEMENT_ID_MISSING:
            # 2026-11-05（业主）：没有命题号就没有可签的对象。这一档不是"签发失败"
            # （那会让调用方去重试），是"这一份稿还不能签"：先登记拿到号，再带号送审。
            block_write.update(state="refused", why=str(issued.get("reason") or ""))
        else:
            block_write["why"] = (
                f"签发没成（`{issued.get('path') or '签文件'}`）："
                f"{issued.get('reason') or '没有理由'}；块没落")
        return block_write, issued, landed

    def _finish_unregistered(self, out: dict[str, Any], *, no: int,
                             got: Mapping[str, Any]) -> dict[str, Any]:
        """未在册手稿那一支的收尾（键集与另几条返回路径相同）。

        2026-11-06：轴那一格（`checked` / `axis` / `source` / `defect_step` / `reason`）
        由 :func:`_unregistered_secretary_judge` 带到返回值顶层 —— 与在册那一支的
        `secretary_judge` 同形。改前它只躺在 `review_passes` 与 pending 台账行上，
        调用方读返回值拿不到"轴是什么、谁判的"。
        """
        if bool(got.get("failed")):
            out.update(checked=False, reason=str(got.get("reason") or ""),
                       detail=str(got.get("detail") or ""),
                       review_passes=list(got.get("passes") or []),
                       secretary_judge=_unregistered_secretary_judge(got))
            #: 会审的七项读数照带（缺材料那一档也一样：读数是正本，不因没查成而丢）。
            if got.get("exhaustion_review"):
                out["exhaustion_review"] = dict(got["exhaustion_review"])
                out["checks"] = list(dict(got["exhaustion_review"]).get("checks") or [])
                out["missing"] = list(dict(got["exhaustion_review"]).get("missing") or [])
            self._emit(f"verify_proof(未在册)：没查成（{got.get('reason')}）")
            return out
        stopped = str(got.get("stopped") or "")
        block = dict(got.get("block") or {})
        pending = dict(got.get("pending") or {})
        # ---- 2026-11-04：同一份正文已经签过 ⇒ 不重复审、不重复写，读数按「已签」报 ----
        #
        # `_review_unregistered_prose` / `_review_unregistered_exhaustion` 的 already 支
        # 不给 `stopped`（它没判任何一转）；改前它落到下面"负判"那一支，于是返回值说
        # 「判「成立」：负判不写手稿块」—— 而盘上明明有一块盖住同一份正文的签。
        # 这一格不是一条终局判定，是"这一份已经签过"：kind 与 detail 都按已签说，
        # `review_passes=[]`（这一趟零转），一个字节都不写。
        if bool(got.get("already")):
            out.update({
                "checked": True,
                "kind": "proof_unregistered_signed",
                "verdict": str(block.get("verdict") or got.get("verdict") or ""),
                "proof_sha256": str(block.get("proof_sha256") or got.get("sha") or ""),
                "proof_no": no,
                "signed_bit3": False,
                "review_passes": [],
                "secretary_judge": _unregistered_secretary_judge(got),
                "ledger": str(got.get("manuscript") or "") or str(block.get("ledger") or ""),
                "reason": str(got.get("reason") or ""),
                "detail": (f"`{got.get('manuscript') or '（这一份稿）'}` 里已经有盖住同一份"
                           "正文的签块 ⇒ 这一趟不重复审、不重复写（签块仍是一行）。"
                           "这里 `signed_bit3=False` 是诚实的：没有命题行可翻；B 收录时"
                           "从稿上的那一块读到它。"),
            })
            self._emit(f"verify_proof(未在册)：already_signed（{out['reason']}）")
            return out
        manuscript_write = dict(got.get("block_write") or {})
        issued = dict(got.get("issued") or {})
        landed = dict(got.get("landed") or {})
        #: 负判的判词仍在 pending；正判那一档的 pending 三行就是这一签的票（没有手稿
        #: 的那一档不落签，见 `_finish_unsigned_review`）。
        pending_ledger = _pending_ledger_ref(pending) if pending else ""
        if stopped == "signed":
            if manuscript_write.get("written"):
                record = (f"签块由收方秘书落进了 `{got.get('manuscript')}`（"
                          f"连续 {block.get('streak')}/{block.get('need')} 成立；"
                          f"背书台账 `{pending_ledger or '（没有）'}`）——B 收录这条命题时"
                          "从稿上读到它、按正文 sha 认领；这里 `signed_bit3=False` 是诚实的："
                          "没有命题行可翻。没有命题号是这一档的常态（业主 2026-11-05："
                          "V 不假定有号，全签在稿上）。")
            elif issued.get("written") or issued.get("idempotent"):
                # 2026-11-03 件一：V 只颁发。颁发了而没有收方秘书（父角色读不到 / 直调）
                # ⇒ 块没落，F 的读数仍是「待签」；不许拿"签已颁发"冒充"稿上有块"。
                record = (f"签已颁发（`{issued.get('path') or '（签文件）'}`，信封→"
                          f"{issued.get('envelope', {}).get('to') or '（没有收方秘书）'}），"
                          f"但收方秘书没落块：{landed.get('reason') or '没有理由'}；"
                          f"背书台账已在 `{pending_ledger or '（没有）'}`，B 收录时按正文 sha "
                          "认领（F 的读数仍是「待签」：块没落 = 稿上没有那一行）。")
            else:
                record = (f"这一份的签落在 `{pending_ledger or '（没有落点）'}`（没有手稿落点，"
                          "签块未尝试）——B 登记之后按正文 sha 认领；这里 `signed_bit3=False` 是诚实的："
                          "没有命题行可翻。")
        elif stopped == "reviewed_unsigned":
            # 2026-11-04（甲）：没有稿 ⇒ 只能"看过"，不能签。这一档不落任何签、
            # 不落 pending 台账（按 sha 可认领的那一行会被当成第三方签）。
            # 2026-11-05 晚：计划稿（不是签的载体）也走这一档 —— 三转读数照给、不构成签，
            # 理由用 `block_write.why` 那一条（它点名"计划稿"），不冒充"没有手稿"。
            from .. import vsigns as _VS2

            if str(manuscript_write.get("code") or "") == _VS2.MANUSCRIPT_NAME_PLAN:
                record = (str(manuscript_write.get("why") or "")
                          + f"这一趟的三转判定（{got.get('verdict') or '（无结论）'}，"
                            f"{len(list(got.get('passes') or []))} 转）只作读数，不构成签。")
            else:
                record = ("看过、没签：这一趟只给了内联正文、没给 `proof_manuscript` ⇒ "
                          "没有可落签的载体 —— 签块、`## 依赖` 段、按号命名的稿这三样都只在"
                          "文件上，内联正文一样都做不到，所以这一签不签发、台账里也不留 "
                          "sign 行。要签就把这份正文落成一份稿（`reports/…` 或 `notes/…` 皆可，"
                          "三节 `## 命题` / `## 证明` / `## 依赖`），再带 `proof_manuscript` 送审。"
                          f"这一趟的判定（{got.get('verdict') or '（无结论）'}，"
                          f"{len(list(got.get('passes') or []))} 转）只作读数，不构成签。")
        else:
            record = (f"这一份判「{got.get('verdict') or ''}」：负判不写手稿块"
                      "（甲口径：`draft/178`「V 不写手稿里的签块」，块只由收方秘书落；"
                      "负判不是签）。判词已落 "
                      f"`{pending_ledger or '（pending 台账）'}`，F 的读数是「未通过」；"
                      "按缺陷改稿后再送，不签第 3 位、也不写重复块。")
        out.update({
            "checked": True,
            "kind": ("proof_reviewed_not_signed"
                     if stopped == "reviewed_unsigned"
                     else "proof_unregistered_signed" if stopped == "signed"
                     else "proof_unregistered_rejected"),
            "verification_id": str(pending.get("verification_id") or ""),
            "verdict": str(got.get("verdict") or block.get("verdict") or ""),
            "defect_step": got.get("defect_step"),
            "findings": list(got.get("findings") or []),
            "unresolved_errors": int(got.get("unresolved_errors") or 0),
            "proof_sha256": str(got.get("sha") or ""),
            "proof_no": no,
            "proof_chars": 0,
            "signed_bit3": False,
            "review_passes": list(got.get("passes") or []),
            "secretary_judge": _unregistered_secretary_judge(got),
            "ledger": pending_ledger or str(got.get("manuscript") or ""),
            "reason": str(got.get("reason") or ""),
            "detail": record,
        })
        self._emit(f"verify_proof(未在册)：{out['kind']}（{out['reason']}）")
        return out

    def _review_without_statement(self, *, text: str, no: int) -> dict[str, Any] | None:
        """命题还没在册时的一次穷举型证据会审（D-34）；不归这一档 ⇒ `None`。

        为什么只接穷举型证据：那一档的会审是机械的（七项可核的事实：
        程序在不在、报告落没落、数字对不对得上……），不需要命题正文就能判 ——
        而普通逐行走查要"按写成后的样子整体重读"，缺了命题那一页就无从审
        （那一档仍按原样报 `statement_missing`）。

        ## 2026-11-04（业主裁定 甲）：这一支不再签

        改前这里落 `verifications/pending/<对象 sha>.jsonl` —— 那一行按对象 sha
        可认领，B 登记之后就是第三方签。而它拿到签的输入只有内联的证明栏：稿上没有
        签块、`## 依赖` 段没人写、也没有按号命名的稿。甲口径把这一档收成"看过、
        没签"：机械七项照跑（读数照给），但一个签字节都不落。E 要签就走
        `proof_manuscript`（`reports/e-proof-<实验号>.md`，`_review_unregistered_exhaustion`）。

        返回 `{"reviewed": {...}, "unsigned": True}`；缺材料时返回
        `{"reason": "missing_material", "detail": ..., "reviewed": {...}}`（一行都不落）。
        """
        if not str(text or "").strip():
            return None
        from .. import exhaustionreport as _ER

        exp_rows: list = []
        try:
            if self.store is not None:
                exp_rows = list(self.store.rows("experiments"))
        except (StoreError, AttributeError, TypeError):
            exp_rows = []
        if not _ER.is_exhaustion_column({"proof_text": text}, exp_rows):
            return None
        reviewed = _ER.review(workspace_root=self.workspace_root,
                              statement={"proof_text": text}, experiments=exp_rows)
        _verdict = _ER.verdict_of(reviewed)
        _missing = [str(m) for m in (reviewed.get("missing") or [])]
        _missing_detail = missing_material_detail(_verdict, _missing)
        if _missing_detail:
            # ---- 缺材料 ⇒ 没查成（与在册那一支同一判据、同一文案）----
            #
            # 审计现场（draft/172 §三 P0-1）：改前这里直接 `record_pending_sign(verdict=
            # verdict_of(reviewed))`，而 `record_pending_sign` 过 `parse_verdict` ⇒
            # 「看不出来」折成「成立」落进 pending 台账。V 的冷启动逐字禁止这么做
            # （缺材料 ⇒ 没查成、台账里不留行）。所以护栏放在落盘之前，一行都不写。
            self._emit(f"verify_proof(未在册)：穷举会审缺材料 —— 没查成，不落 pending 行"
                       f"（{_missing}）")
            return {"reason": MISSING_MATERIAL_REASON, "detail": _missing_detail,
                    "reviewed": reviewed}
        # 2026-11-04（甲）：机械会审照跑，但不落签。没有手稿就没有签的载体：
        # 落一行 pending 等于给 B 一个"可按 sha 认领的第三方签"，而那正是要堵的口子。
        self._emit(f"verify_proof(未在册)：穷举型证据会审 ⇒ {_verdict.get('verdict')}"
                   "（看过、没签：没有手稿就没有签的载体）")
        return {"reviewed": reviewed, "unsigned": True,
                "sha": VR.proof_sha(text), "proof_chars": len(str(text or ""))}

    def _finish_unsigned_review(self, out: dict[str, Any], *, statement_id: str, no: int,
                                got: Mapping[str, Any]) -> dict[str, Any]:
        """`_review_without_statement` 的收尾：没手稿 ⇒ 只给“看过、没签”的读数。

        ## 这一格不落签（2026-11-04 业主裁定 甲）

        改前它叫 `_finish_pending`：那一支会把判定落进
        `verifications/pending/`，让 B 能把它当成第三方签。现在这一条路没有手稿
        （签的载体），所以机械会审照跑、读数照给，但
        `verification_id=""`、`ledger=""`、`signed_bit3=False` —— 一个签字节都不落。
        要签就让 E 带 `proof_manuscript=reports/e-proof-<实验号>.md` 走手稿那一支。

        缺材料那一档（`got["reason"]` 非空）仍原样摊开七项读数：那是“没查成”，
        不是“看过”。
        """
        if str(got.get("reason") or ""):
            out["reason"] = str(got.get("reason"))
            out["detail"] = str(got.get("detail") or "")
            reviewed = dict(got.get("reviewed") or {})
            if reviewed:
                # 缺材料那一档：会审跑完了、七项读数在手上，而 detail 里承诺了
                # 「会审的七项读数在 exhaustion_review 里」⇒ 不带出来那句话就是假话。
                out["exhaustion_review"] = reviewed
                out["signer"] = str(reviewed.get("signed_by") or "")
                out["proof_authors"] = list(reviewed.get("proof_authors") or [])
                out["report_path"] = str(reviewed.get("report_path") or "")
            return out
        reviewed = dict(got.get("reviewed") or {})
        from .. import exhaustionreport as _ER

        verdict = _ER.verdict_of(reviewed)
        out.update({
            "checked": True,
            "kind": "numeric_evidence_reviewed_not_signed",
            "verification_id": "",
            "verdict": str(verdict.get("verdict") or ""),
            "defect_step": verdict.get("defect_step"),
            "findings": list(verdict.get("findings") or []),
            "unresolved_errors": int(verdict.get("unresolved_errors") or 0),
            "proof_sha256": str(got.get("sha") or ""),
            "proof_no": no,
            "proof_chars": int(got.get("proof_chars") or 0),
            "signed_bit3": False,
            "exhaustion_review": reviewed,
            "signer": str(reviewed.get("signed_by") or ""),
            "proof_authors": list(reviewed.get("proof_authors") or []),
            "report_path": str(reviewed.get("report_path") or ""),
            "checks": list(reviewed.get("checks") or []),
            "missing": list(reviewed.get("missing") or []),
            "ledger": "",
            "reason": ("看过、没签：命题还没在册，而这一趟只给了内联证明栏、"
                       "没给 `proof_manuscript` ⇒ 没有可落签的载体；"
                       "机械会审的七项读数照给，但一个签字节都没落"),
            "detail": (f"命题 {statement_id or '（还没落号）'} 这一趟没有可签的载体"
                       "（V 只读手稿，不查 statements）："
                       "穷举型证据的会审跑完了（七项读数在 `exhaustion_review` / "
                       "`checks` / `missing` 里），判定只作读数、不构成签，"
                       "也不落任何 pending 台账行。要签就让 E 带 "
                       "`proof_manuscript=reports/e-proof-<实验号>.md` 送审："
                       "签块由收方秘书落回那一份稿，B 收录时从稿上读到。"),
        })
        self._emit(f"verify_proof(未在册)：{out['kind']}（{out['reason']}）")
        return out

    def _finish_numeric(self, out: dict[str, Any], *, statement_id: str, no: int,
                        row: Mapping[str, Any], reviewed: Mapping[str, Any]) -> dict[str, Any]:
        """穷举型证据会审的收尾：台账那一行落地没有、五元位、返回值。

        这一段与 `verify_proof` 的普通收尾是同一套纪律（只认 `row` 上的 `checked`）：
        台账没落地就不许报"签住了第 3 位"；`成立` 才签；`有毛病` 照样留一行
        （那是"看过、结论是没过"的证据）。结论按两态读（`VR.read_verdict`）：
        老行上那个已取消的档（2026-11-02：连历史兼容读也不留）读成 `成立`。
        """
        sid = statement_id
        # 翻位那一步在秘书那一侧（业主 2026-10-29 追加口径）：`row.statement_writeback`
        # 是 record_verification 的"deferred"读数，真正的写回在 `out["sign_issuance"]` 里。
        writeback = dict((out.get("sign_issuance") or {}).get("writeback")
                         or row.get("statement_writeback") or {})
        if row.get("checked") is False:
            out.update({
                "checked": False,
                "review_write": writeback,
                "reason": f"ledger_row_lost：{row.get('reason') or '台账那一行没写成'}",
                "detail": (f"V 的会审结论是 {row.get('verdict')!r}，但台账那一行没落地 ⇒ "
                           "这一签没有落地、命题行的第 3 位也没改；必须重签"),
            })
            self._emit(f"verify_proof({sid})：{out['reason']} —— 台账里没有这一签")
            return out
        # ---- 2026-11-08：穷举这一路也不翻命题位 --------------------------------
        #
        # 与散文那条路同一把尺：签只落在稿上（侧文件 + 九格块），命题行的第 3 位与
        # 等级由 B 收录时按正文 sha 认领 / 现算。`signed_bit3` 恒 False；"签落地了
        # 没有"由 `sign_issuance.issued` 与 `writeback.manuscript_write` 两格回答。
        _ms_write = dict(writeback.get("manuscript_write") or {})
        _manuscript_signed = bool(_ms_write.get("written") or _ms_write.get("idempotent"))
        bits: dict[str, Any] = {}
        try:
            from .. import evidencebits as EB

            bits = EB.bits_of(proof=bool(str(row.get("proof_text") or "").strip()),
                              proof_process=str(row.get("proof_text") or ""))
        except Exception as exc:  # noqa: BLE001 —— 合成失败不影响台账那一行（它已经落盘）
            self._emit(f"verify_proof({sid})：五元位合成失败（{type(exc).__name__}: {exc}）")
        self._emit(f"verify_proof({sid})：{row['verification_id']} verdict={row['verdict']} "
                   f"signed_bit3=False（穷举型证据；签在稿上：{_manuscript_signed}）")
        if _manuscript_signed:
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 的签已由收方秘书"
                       "落回手稿；命题行等 B 收录")
        out.update({
            "checked": True,
            "verification_id": row["verification_id"],
            "verdict": row["verdict"],
            "defect_step": row["defect_step"],
            "findings": row["findings"],
            "unresolved_errors": row["unresolved_errors"],
            "proof_sha256": row["proof_sha256"],
            "proof_no": row.get("proof_no"),
            "proof_chars": row["proof_chars"],
            "signed_bit3": False,
            "reviewed_by": {},
            "bits": bits,
            "review_write": dict(writeback, manuscript_signed=_manuscript_signed,
                                 filed="not_read_by_v"),
            "ledger": f"verifications/{sid}.jsonl#{row['verification_id']}",
            "reason": f"{row['verification_id']}：{row['verdict']}"
                      + ("（签在稿上；命题行由 B 收录时认领）"
                         if _manuscript_signed else "（不签：签没落成）"),
            "checks": list(reviewed.get("checks") or []),
            "missing": list(reviewed.get("missing") or []),
        })
        return out

    def list_verifications(self, statement_id: str = "", limit: Any = None, **kw: Any) -> dict[str, Any]:
        """列验证台账（可按命题过滤；`limit=None` = 全量，不是"零条"）。"""
        del kw
        lim = None if limit is None else max(0, int(limit))
        rows, problems = VR.list_verifications(self.workspace_root,
                                               statement_id=str(statement_id or "").strip(),
                                               limit=lim)
        return {
            "checked": True,
            "total": len(rows),
            "items": rows,
            "problems": list(problems),
            "truncated": bool(lim is not None and len(rows) > lim),
            "reason": f"共 {len(rows)} 行验证台账"
                      + (f"，坏行 {len(problems)} 条（照实列出，不静默跳过）" if problems else ""),
        }

    def read_proof(self, statement_id: str, **kw: Any) -> dict[str, Any]:
        """按命题号读回被审的那份证明全文 + 它的 sha256 + 最近一次结论。

        与 `verify_proof` 同一纪律：三条返回路径的键集合完全相同
        （"没读到"由 `source="none"` 与 `reason` 说，不靠少给键来表达）。
        """
        del kw
        sid = str(statement_id or "").strip()
        out: dict[str, Any] = {
            "checked": False, "statement_id": sid, "proof_text": "", "source": "none",
            "sha256": "", "proof_chars": 0, "verifications": 0,
            "last_verdict": None, "last_verification_id": None,
            "problems": [], "reason": "",
        }
        if not S.is_valid_id(sid):
            out["reason"] = (f"命题号必须是 {S.ID_DIGITS} 位十进制（旧数据里的 4 位号仍可读），"
                             f"收到 {statement_id!r}")
            return out
        text, source = "", "none"
        # 2026-11-08（V 只对手稿负责）：被审的证明全文从手稿读（不再读 statements）。
        # 按两族约定命名找：F 的原稿先、B 的改写稿后；都没有 ⇒ source="none"，
        # 不退回台账（V 不读它）。
        from .. import depsection as _DS

        _tried: list[str] = []
        for rel in (f"{_DS.MANUSCRIPT_DIR}/{_DS.MANUSCRIPT_STMT_PREFIX}{sid}.md",
                    f"{_DS.MANUSCRIPT_DIR}/b-proof-{sid}.md"):
            _tried.append(rel)
            try:
                raw = (Path(self.workspace_root) / rel).read_text(encoding="utf-8")
            except OSError:
                continue
            body = _DS.proof_body(raw).strip("\n")
            if body.strip():
                text, source = body, "manuscript"
                break
        if source == "none":
            read_problems = [f"盘上没有这一条命题的证明手稿（找过 {' / '.join(_tried)}）"]
        else:
            read_problems = []
        rows, problems = VR.list_verifications(self.workspace_root, statement_id=sid, limit=None)
        last = rows[-1] if rows else None
        out.update({
            "checked": True,
            "proof_text": text,
            "source": source,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "proof_chars": len(text),
            "verifications": len(rows),
            #: 结论按两态读（`verifications.read_verdict`）：老行上的那一档（2026-11-02 起
            #: 连历史兼容读也不留）在这里读成 `成立`，不冒充第三种结论。
            "last_verdict": VR.read_verdict(last or {}),
            "last_verification_id": (last or {}).get("verification_id"),
            "problems": read_problems + list(problems),
            "reason": ("从手稿读到了证明全文" if text else
                       "盘上没有这个命题的证明手稿（没读到 ≠ 没有毛病；V 不读 statements）"),
        })
        return out


class _ScriptedSeam:
    """自检用的替身缝：按调用次数返回事先写好的文本（只服务自检，不进产品路径）。"""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: Any) -> Any:
        """返回一个只有 `text` / `problem` 两个字段的替身结局。"""
        from types import SimpleNamespace

        self.prompts.append(prompt)
        text = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(text=text, problem="" if text else "judge_not_wired")


class _NoSecretary:
    """自检用的"没有秘书"替身：三件都如实报 `checked=False`（业主 2026-10-29）。

    为什么自检必须给它：`AgentV._secretary()` 会真的去装配一名秘书（工具路径那条缺口），
    而自检不该联网、也不该花钱。给了这个替身，"这一趟没有秘书"就是自检里的第一条读数
    —— 它同时是发签那条路径的反面（`signed_bit3` 必须为假）。
    """

    seam = ""
    model_source = "自检：这一趟没有秘书"

    def judge_v_reply(self, **_kw: Any) -> dict[str, Any]:
        """判定没查成（不是"没问题"）：没有轴（空串），不清零、也不计入。"""
        return {"checked": False, "axis": "", "unwired": True, "decision": "",
                "reason": "自检：没有秘书 ⇒ 判定没查成"}

    def decide_sign_issuance(self, **_kw: Any) -> dict[str, Any]:
        """没人发签 ⇒ 不签发。"""
        return {"checked": False, "issue": False, "issued": False, "streak": 0,
                "projected": 0, "need": VR.SIGN_STREAK_NEED, "streak_ok": False,
                "decision": "", "writeback": {}, "landed": False,
                "reason": "自检：没有秘书 ⇒ 没有人发这一签"}

    def wash_v_reply(self, **_kw: Any) -> dict[str, Any]:
        """洗不出来 ⇒ 不输出原文（自检不测洗稿，只核两态形状）。"""
        return {"checked": False, "washed": False, "text": "", "findings": [],
                "dropped": [], "refused": "secretary_unavailable",
                "reason": "自检：没有秘书"}


def selftest() -> int:
    """最小自检：冷启动的接口形态、两态、签位条件、追加式编号、没查成不落行。"""
    import tempfile

    checks: list[tuple[str, bool]] = []
    root = Path(tempfile.mkdtemp(prefix="agent_v_selftest_"))

    def _manuscript(stmt_id: str, proof: str) -> str:
        """落一份按号命名的稿，返回工作区相对路径（自检的送审载体）。

        2026-11-08 业主口径「V 只对手稿负责，不该看台账了」：签块 / `## 依赖` /
        按号寻址三样只在文件上，内联正文（`proof_text`）单独送审会被
        `proof_manuscript_required` 受控拒 —— 自检也必须走同一条正路，否则它量的
        是一条真机上不存在（也不许存在）的入口。三节 `## 命题` / `## 证明` /
        `## 依赖` 齐全；依赖段空表本身就是"这一份没有引用任何在册命题"的声明。
        """
        rel = f"reports/f-proof-{stmt_id}.md"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# F 的证明手稿（自检）\n\n"
            f"- 命题号：stmt:{stmt_id}\n\n"
            "## 命题\n\n（自检：这一份审的只是证明正文）\n\n"
            f"## 证明\n\n{proof}\n\n"
            "## 依赖\n\n"
            "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n\n"
            "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
            encoding="utf-8")
        return rel

    agent = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=_ScriptedSeam([
        '{"verdict": "成立", "findings": []}',
        '{"verdict": "有毛病", "defect_step": 2, "findings": '
        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步没有依据"}]}',
        "我不确定",
    ]))
    checks.append(("构造成功", agent.actor == DEFAULT_VERIFIER))

    clean = agent.verify_proof(
        "0007", proof_manuscript=_manuscript("0007", "1. 由定义直接得到。"))
    checks.append(("干净证明签成立", clean["checked"] and clean["verdict"] == "成立"))
    # 编号宽度「不许写死」：2026-10-14 业主裁定「所有四位编号改成六位」
    # （`schema.ID_DIGITS = 6`），发号点是 `verifications.next_verification_id`
    # 的 `f"v-{S.format_id(...)}"`；读侧仍认旧四位号（`schema.LEGACY_ID_PATTERN`）。
    # 旧断言把 `"v-0001"` 写死在两处 ⇒ 宽度一改它就红，而"红了"这件事没有任何
    # 东西看得见（自检只在手工敲命令时跑）。这是「断言过期」，不是行为退化：
    # 台账发的号是正确的六位（见下一条与 `tests/test_id_width.py`）。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   clean["verification_id"] == f"v-{S.format_id(1)}"))
    # 业主 2026-10-29：V 只产意见，签由秘书发；而且连续 3 次成立才签。
    # 自检这一趟没有秘书 ⇒ 第 1 次成立既没有票数也没有人发签 ⇒ 第 3 位必须是空的。
    checks.append(("成立但第 1 次不签第 3 位（没有秘书、也没到第 3 票）",
                   clean["signed_bit3"] is False
                   and clean["sign_issuance"]["checked"] is False
                   and clean["sign_issuance"]["issue"] is False))
    # 第 3 位（审过）的 owner 是 V —— 这一格只能核静态那一半：
    # `evidencebits.BIT_OWNERS["reviewed"] == "V"`（位表里的 owner）。
    # "签名者是 V、凭据是本次这行"那一半要真的签成才看得到，自检没有秘书 ⇒ 不在这里核
    # （那一条在 `tests/test_v_sign_gate_streak.py` 的 a6/a8 里走真路径）。
    from .. import evidencebits as _EB

    checks.append(("五元位第 3 位 owner 是 V（位表那一格）",
                   _EB.BIT_OWNERS.get("reviewed") == "V"
                   and clean["reviewed_by"] == {}))

    bad = agent.verify_proof(
        "0007", proof_manuscript=_manuscript("0007", "1. 由定义直接得到。2. 易证。"))
    checks.append(("有毛病指到那一步", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    checks.append(("有毛病不签第 3 位", bad["signed_bit3"] is False
                   and bad["bits"].get("reviewed") is False))

    unparsable = agent.verify_proof(
        "0007", proof_manuscript=_manuscript("0007", "1. 随便写。"))
    checks.append(("没查成不落行", unparsable["checked"] is False
                   and unparsable["reason"] == "unparsable"))

    rows = agent.list_verifications()
    checks.append(("追加式：两行（第三份没落）",
                   rows["checked"] and rows["total"] == 2))
    checks.append(("limit=None 是全量而不是零条", agent.list_verifications(limit=None)["total"] == 2))

    # I12 的接口形态：拼提示词的那一步只收字符串。
    import inspect as _inspect

    params = set(_inspect.signature(VR.cold_start_prompt).parameters)
    checks.append(("冷启动提示词没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    # 正控：提示词里真的有对象与硬禁令（否则上面那条"没有句柄"只是空集通过）。
    seam = _ScriptedSeam(['{"verdict": "看不出来", "findings": []}'])
    probe = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=seam)
    probe.verify_proof("0008", proof_manuscript=_manuscript("0008", "1. 显然成立。"),
                       readonly_facts="- 只读读数：0 行")
    sent = seam.prompts[0] if seam.prompts else ""
    checks.append(("提示词里带证明全文与硬禁令", "1. 显然成立。" in sent and "易证" in sent))
    checks.append(("提示词里带只读读数", "只读读数：0 行" in sent))
    # p247：历史值「看不出来」原样落成陈述（不折档），没有秘书轴 ⇒ 不签第 3 位。
    _probe_rows = probe.list_verifications("0008")["items"]
    checks.append(("回「看不出来」⇒ 原样落行（不折档）",
                   probe.list_verifications("0008")["total"] == 1
                   and bool(_probe_rows) and _probe_rows[0]["verdict"] == "看不出来"
                   and VR.read_verdict(_probe_rows[0]) == "看不出来"
                   and VR.secretary_axis(_probe_rows[0]) == ""))
    checks.append(("没有秘书轴的陈述同样不签第 3 位",
                   bool(_probe_rows) and VR.bit3_payload(_probe_rows[0]) == {}))

    noproof_seam = _ScriptedSeam([])
    noproof = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=noproof_seam)
    got = noproof.verify_proof("0007", proof_text="")
    # 2026-11-08 业主口径「V 只对手稿负责」之后，"没有可签的载体"挡在更前面那一格，
    # 拒信码从 `no_proof_text` 变成 `proof_text_needs_a_manuscript`。这条判据量的那件事
    # 一个字没变：没有载体就不问模型（`not noproof_seam.prompts`）、不落台账行。
    checks.append(("没有证明全文就不问模型", got["checked"] is False
                   and got["reason"] == "proof_text_needs_a_manuscript"
                   and not noproof_seam.prompts))
    bad_id = noproof.verify_proof("7", proof_text="x")
    # 标签写错过一次（"命题号必须 4 位"而 `schema.ID_DIGITS == 6`）：标签也是判据的
    # 一部分 —— 读者照着它去改数据，会得到"越改越不对"。所以除了 `reason` 码，
    # 这里还核一句「细节里报出的宽度」与 `schema.ID_DIGITS` 逐字一致。
    checks.append((f"命题号必须 {S.ID_DIGITS} 位（旧数据里的 4 位号仍可读）",
                   bad_id["reason"] == "bad_statement_id"
                   and f"{S.ID_DIGITS} 位" in bad_id["detail"]
                   and "4 位号仍可读" in bad_id["detail"]))
    # 反真空：上面那条只证明"坏号被拒"。若发号/收号两侧一起把六位号也拒了，
    # 它照样绿 ⇒ 这里正控地把一个「六位」命题号喂进去，必须被当成合法号：
    # 过了号闸才会走到载体闸，于是"拒信码是载体闸那个"就是"号被接受了"的读数。
    six_ok = noproof.verify_proof(S.format_id(7), proof_text="")
    checks.append((f"六位命题号被接受（{S.format_id(7)}；写侧的新形态）",
                   six_ok["reason"] == "proof_text_needs_a_manuscript"))

    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    passed = sum(1 for _, g in checks if g)
    # 汇总行与退出码同源（与 `agent_e` 的 F-4 同一纪律）：`[FAIL]` 是逐条读数，
    # 汇总行是可机械读出的那一个数；退出码只跟它走。
    print(f"  SELF-CHECK {'DONE' if passed == len(checks) else 'FAILED'}（agent_v）："
          f"{passed} 项通过 / {len(checks) - passed} 项失败")
    return 0 if passed == len(checks) else 1
