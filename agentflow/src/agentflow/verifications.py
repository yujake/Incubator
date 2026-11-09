# -*- coding: utf-8 -*-
"""验证者（V）的证明级审校台账（`draft/39` §3.21 五，用户 2026-10-05 定案）。

## 先分清三个"档"（2026-10-27，R-EVID 审查的 ③；零行为改动，只是点明词）

同一个"档"字在这一族里指三根不同的轴，谁都不许拿一根去顶另一根：

* `evidence_kind`（本模块最常说的"档位"）—— 真身 `schema.EVIDENCE_KINDS`
  （`proof` / `proof_review` / `cross_check` / `heuristic`，从强到弱）。它回答
  "这条断言的证据是哪一类"。本模块只用它判一件事：够不够格被引
  （`CITATION_EVIDENCE_FLOOR`，现算前缀，不抄字面量）。
* `GRADES`（本模块说的"定理档"）—— 真身 `evidencebits.GRADES`
  （`conjecture` / `strong_conjecture` / `pre_theorem` / `theorem`）。它由五元位
  派生（`evidencebits.derive_grade`），本模块的 `statement_grade` /
  `_highest_grade` 只是在多证明模型里"取最高"。
* `T0`–`T4`（非平凡性档）—— 不归本模块：真身在 `secretary.py`
  （`nontriviality_label` 与它那张 band 表）。本模块一个字都不定义它。

五元证据位（§3.14）的第 3 位（"审过"）的 owner 是 V：一个 F 配一个验证者，它把 F 交回来的
证明按写成后的样子整体重读，做三件事（用户点名的 I12/I10/I17）：① I12 冷启动 —— 每次审校开
新会话，只给对象（证明全文）+ 只读查询面的读数，不给 F 的叙述、不给 store 句柄 ⇒ "独立性"
是结构性质而不是一句约定；② I10 硬禁令 + 同段依据 —— 逐条查（无条件前提 / 无依据的步骤 /
"易证、显然、trivial"这类缝 / 引用的命题是否干净），每条问题指到那一步并给理由；③ I17 整篇
重读 —— 把证明当一次输入整体读（"这些缝正是正确的事实变成错误证明的地方"），而不是只逐单元
核对。
## 落点与形态（与手稿同一形态：追加式 JSONL，不新增台账表）
`<工作区>/verifications/<命题号>.jsonl`：一行 = 一次审校，至少要有输入证明的 `sha256`、两态
结论、逐条 findings（每条带步号）、用了哪个只读面、验证者实例名；编号 `v-0001…` 按文件内顺序
发（与手稿编号、台账 id 同一套做法）。
## V 的判词只是陈述；轴只有两态，且只由秘书的语义分析给出（2026-11-06 p247）
`VERDICTS` 只有 `有毛病` / `成立` 两格，但它们现在是轴（clean / fault）的两个名字，
不是 `parse_verdict` 的词表。台账行上的 `verdict` 是 V 写下的陈述：它原样落盘、
原样读出（:func:`read_verdict`），框架不从它推任何状态 —— 业主 2026-11-06 第三次收紧的
原话：「V 的判词只是陈述」「不做折档」「不许按词面把判不了 / 看不出来 / 拿不准 /
我无法判断折成任何一态」。每一转的轴由 V 的秘书读这段回复后语义判定
（`secretary_judge.axis`，唯一读口 :func:`secretary_axis`，`clean` / `fault`），
连续次数与签发只看那个轴。秘书判 fault 而 V 没给 `defect_step` 时，由秘书定出那一步
（`Secretary.judge_v_reply` 的 `defect_step` 读数）。

"检查器自己没跑成"（模型输出不是合法 JSON、缺 `verdict` 字段、findings 形状坏）不是轴 ——
`record()` 在没有可解析的陈述时抛 `VerificationError`，绝不写一行"没查成"来冒充"审过了"。
历史值「看不出来」（:data:`LEGACY_VERDICTS`，2026-11-01 之前写下的行）仍读得出，
但它不折成任何一态、不算票、也不签。

### 2026-11-06 p247：连"历史值按成立读并计票"也取消了
改前（2026-11-02 到 p246）读侧给老行上的 `看不出来` 留了一条"按成立读并计票"的兼容支。
p247 的口径是"判词只是陈述" ⇒ 那条兼容支也删了：老行的陈述原样读出，轴为空
（:func:`secretary_axis` 读成空串）⇒ :func:`_hold_run_lengths` 对它按"这一行的轴读不出来"
处理（不算票、也不清零），:func:`row_signable` 为假。这是收紧方向：老工作区的连续数会回到
"只数得出真有秘书轴的行"，不会再把一个已经不存在的档当成通过。
* 台账文件不改写（追加式，迁移要重写历史行 ⇒ 不做）：盘上那四个字仍是原始读数。
签"审过"（§3.21 五）：轴是 `clean` 且 findings 里没有未解决的 `error` ⇒ `signs_bit3()`，
`bit3_payload()` 给出五元位第 3 位那份读数（`reviewed=True` + 凭据）。
## 「复核过的是哪一份」怎么记（业主 2026-10-22 口径，治那处结构性断链）
签名行记 `(stmt_id, proof_no, proof_sha256)`。`proof_no` 是证明号：`1` = canonical
（缺省，老数据不带它就等价于 `#p1`），`2, 3, …` 是同一条命题的其它证明（见 :data:`PROOFS_KEY`）。
每条证明各自有第 3 位（`reviewed`）：签的是"这一份的每一步站得住"，别的证明不许借光。
判定永远看那条证明现在这一份正文：它的现行 sha 有「成立」那一签 ⇒ `signed`；
签的是旧版 ⇒ `stale`（待复核，第 3 位不计）；被签过、结论不是「成立」⇒ `rejected`；
一次都没签 ⇒ `unsigned`。命题级的定理档 = 在 in-sync 的证明里取最高
（:func:`statement_grade`），一条 in-sync 都没有 ⇒ 猜想。
哈希只回答"这份稿在你签完之后有没有被改过"，它是读数，不是授权凭证：任何写入路径都不因
sha 不符而拒收（`proof_review_gaps` 明确把 `stale` 当成"待复核"这个读数，而不是"没有凭据"）。
签名落盘之后「同一次写」把那条证明的 `reviewed` 翻上去（:func:`sign_statement`）：
先追加台账那一行、再在 `statements` 的事务里改那一行；事务没成就把刚追加的那一行撤回。
逐条证明的第 3 位落在命题行的 `bits.evidence.reviewed_by_proof`（`{"1": true, "2": false}`），
而 `bits.reviewed` 仍是"任一份成立即为 True"的汇总位（老读者只认它）。汇总位要按"任一份
仍 in-sync"读，就必须知道每一签盖住的是哪一份正文 ⇒ 同一次写还落一张 `bits.evidence.
reviewed_sha_by_proof`（`{"1": "<sha256>", "2": ""}`，见 `evidencebits.REVIEWED_SHA_BY_PROOF_KEY`）。
## 老键与老行（兼容，不迁移）
签名行记的三格是 `stmt_id` / `proof_no` / `proof_sha256`。更早的真机行只有
`statement_id`（没有 `stmt_id`），更早的写法还可能把证明号写成 `rev`。读侧认这三对写法：
`stmt_id` 缺 ⇒ 读 `statement_id`；`proof_no` 缺 ⇒ 读 `rev`（见 :func:`proof_no_of`）；
两个都没有 ⇒ `#p1`（缺省证明号，见 `proofloc`）。写侧只写正名 —— 迁移要重写历史台账，
而兼容只需要一行读法，且不会把"谁在什么时候签的"改成"我们改写过它"。
## 引用核实（业主 2026-10-26：V 要核 F 的引用，而 F 的引用不是逐字引文）
F 在 `dependencies` 上登记"这一份证明用到哪条在册命题"（`used_by` / `path_group` /
`source_stmt_id` / 那一行的人话）。那是自然语言描述（"由引理 2"、"由 Sylow I 可知"），
不是逐字引文 ⇒ 只把编号交给 V 没有用，V 必须看到两样东西：F 是怎么说的、被引命题真正
说的是什么（`agent_v.core._citation_material` 把两边一起取出来，正文摘要一起进提示词）。
V 逐条给一档结论（:data:`CITATION_VERDICTS`：`consistent` / `weaker` / `stronger` /
`unrelated` / `inadmissible` / `unknown`），读数是 `citation_checks` 那五格
（:data:`CITATION_CHECK_KEYS`；第 5 格 `in_material` 说明这一条是不是这一份证明登记的引用），
随台账那一行落盘。签字前置（:func:`signs_bit3`）：
只要有一条 `stronger` / `unrelated` / `inadmissible` / `unknown`，这一签就不许落地
（:func:`citation_gate` 点名是哪一条、差在哪）；`weaker` 可以签，但读数里点名"只用到了
弱形式"；档位不够格（低于 `proof_review`，业主逐字「proof_review级及以上才可引用」）
是事实而不是判断，由 :func:`evidence_kind_admissible` 从 `schema.EVIDENCE_KINDS` 现算。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import depsection as _DS  # 可引门槛的唯一定义（`CITATION_MIN_LEVEL`）
from . import evidencebits as EB  # 等级的唯一派生口（`derive_grade` / 反算表）
from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from . import statementbody as _SB  # 命题正文的唯一读口（被引命题的正文从这里取）
from . import statementledger as SL  # 命题台账的查口（按号 / 按关键词，只读、零模型）
from . import textutil as T  # 引用解析的唯一实现（`citation_ref_parts`，`P-5`）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）

#: 验证台账目录（工作区根下）。
VERIFICATIONS_DIR = "verifications"
#: V 的结论（轴）—— 只有两态（业主 2026-11-01 裁定，逐字：「不应该有『看不出来』，
#: 『看不出来错』就是没毛病，没有『看不出来对』」）。顺序就是从"找到了缺陷"到"没找到缺陷"；
#: 最后一格永远是 `成立`（`numericproof.THIRD_PARTY_VERDICT_OK` 按 `[-1]` 引用它）。
#:
#: p247（业主第三次收紧）：这两格是轴（clean / fault）的名字，不是 `parse_verdict` 的词表。
#: 台账行上的 `verdict` 是 V 的陈述，不是判据；轴只由 :func:`secretary_axis` 给。
#: `parse_verdict` 因此不再按 `verdict` 的字面折档（判不了 / 看不出来 / 拿不准
#: 一个都不折；连"有毛病"也不由它定轴）。"看不出对"这回事不存在：V 永远拿不出
#: "它一定正确"的证据，那一档从来就不是它的一项结论。
#:
#: 与秘书那一条是同一条口径：秘书读 V 的回复后语义判定 `clean` / `fault`，
#: 连续次数与签发只看那个轴，不看 V 自己写的那两个字。
VERDICTS: tuple[str, ...] = ("有毛病", "成立")
#: 已经取消的那一档的历史值（业主 2026-11-02 追加裁定：「这一档连历史兼容读也不留」）。
#:
#: 业主 2026-11-01 裁定逐字：「不应该有『看不出来』，『看不出来错』就是没毛病，没有
#: 『看不出来对』」。于是这一档不再是 V 的一种结论。p247 起它连"读侧折成成立"也不做：
#: :func:`read_verdict` 原样返回台账上的陈述，轴由秘书给。这个常量现在只剩两个用处：
#: - 对拍点：`schema.REVIEW_VERDICTS`（另一根轴，FC-27 禁改区）与
#:   `exhaustionreport.VERDICT_UNKNOWN`（会审的机械读数）里还写着同一个词，读侧要对得上
#:   （`tests/test_the_four_verdict_word_lists_agree.py`）；
#: - 给老台账一个可读的陈述值（读得出、不崩），但它不产生任何轴、不算票、不签。
#: 台账不改写（追加式文件，迁移要重写历史行 ⇒ 不做）。
LEGACY_VERDICTS: tuple[str, ...] = ("看不出来",)
#: 业主 2026-11-01 逐字要求写进 V 可见面的那两句：两态的定义，与"看不出错就是成立"。
#:
#: 为什么它们是常量而不是散在提示词里的字面量：`verifications.cold_start_prompt` 是 V
#: 每次审阅真正读到的入口，`specs/v.py` 的 `policy` 是渲染进 system prompt 的那一份
#: （那一处不能 import 本模块 —— 本模块 import 它，反过来会成环）。两处必须逐字相同，
#: 而"逐字相同"只能由渲染面判据钉住：`tests/test_v_verdict_is_two_states.py` 的 s4
#: 在渲染之后的提示词上核这两句（不是核源码里的常量）。
TWO_STATE_LINE = (
    "成立（没找到缺陷 —— 不要求你证明它正确）"
    "/ 有毛病（找到了缺陷，必须指到步号与原句）")
NO_THIRD_STATES = (
    "『看不出错』就是成立；不存在『看不出来』这一档，也不存在『看不出对』这回事")
#: findings 的级别 —— 别名，不抄第二份：词表真身是 `schema.FINDING_LEVELS`
#: （`parse_verdict` 与 `schema.ReviewFinding` 判的是同一件事，两处各写一份字面量
#: 就会在加一档时一处认、一处拒）。
FINDING_LEVELS: tuple[str, ...] = S.FINDING_LEVELS
#: 硬禁令的清单（I10 的最小形态）：命中这些短语的步骤必须被指出来。
#: 用户 2026-10-05 口径："F 禁止写'易证/显然/trivial/clearly/it is easy to see'"。
HARD_BAN_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)
#: 一次审校至少要交代的四件事（缺一就不是"审过了"）。
REQUIRED_FIELDS: tuple[str, ...] = ("verdict", "statement_id", "proof_sha256")

#: 引用核实的档位结论（业主 2026-10-26 裁定，两批）。
#:
#: 口径逐字：「正常写证明就是不会逐字的」、「proof_review级及以上才可引用」。所以判据不是
#: "字面像不像"，而是"F 对这一条被引命题的用法成不成立、以及这一条够不够格被引" ——
#: 改写、压缩、换符号都合法，只要条件与结论没被换掉：
#:
#: - `consistent`：F 的用法与这条命题真正说的条件/结论一致（措辞当然可以不同）；
#: - `weaker`：F 只用到了它的弱形式（不等于错，是情报；可以签，但读数里点名）；
#: - `stronger`：F 用到的结论比命题本身更强（引用被夸大，或悄悄去掉了它要的假设）；
#: - `unrelated`：这条命题与这一步无关（引错了）；
#: - `inadmissible`：被引命题的档位低于 `proof_review`（`cross_check` / `heuristic` / 空）
#:   ⇒ 它不够格被当作依据引（不管用法一致不一致）；
#: - `unknown`：V 判不了（材料不足 / 被引命题不在册）；它不是 `consistent`。
CITATION_VERDICTS: tuple[str, ...] = (
    "consistent", "weaker", "stronger", "unrelated", "inadmissible", "unknown",
)
#: 能签「成立」的两档：弱形式不是错。`weaker` 会被点名，但它不挡签字。
CITATION_SIGNABLE: frozenset[str] = frozenset(("consistent", "weaker"))
#: 挡住「成立」的四档（逐条点名是哪一条、差在哪）。`unknown` 也在里面：判不了不是一致；
#: `inadmissible` 也在里面：档位不够不是"用法对不对"能救的。
CITATION_BLOCKING: frozenset[str] = frozenset(
    ("stronger", "unrelated", "inadmissible", "unknown"))
#: 一条核实读数落盘时的五格。`quote_verbatim` 只是信息（F 那句话是不是逐字抄的），
#: 它不参与判定 —— 业主裁定"逐字"不能当标准，写证明不会逐字引。
#:
#: `in_material`（2026-10-27 补）是这一格为什么挡住签字的语境，必须随读数落盘：
#: `reconcile_citation_checks` 会给"V 多给的、材料里没有的那几条"标 `False`，
#: 而签字前置（`citation_gate`）明确不拿它们挡签（它们不是这一份证明登记的引用）。
#: 改前这一格只在内存里：落盘时被洗掉 ⇒ `signs_bit3` 读 `citation_blocks` 时
#: 把材料外的那条也算成挡签，于是"V 判成立、闸也说 ok"的一签落盘后读回
#: `rejected`，理由是"verdict='成立' ⇒ 结论不是成立"（自相矛盾，且写的人无从修）。
#: 老行没有这一格 ⇒ 按"材料内"读（它们本来就是按材料内判定写下的）。
CITATION_CHECK_KEYS: tuple[str, ...] = (
    "stmt_id", "verdict", "quote_verbatim", "note", "in_material")
#: 进 V 的审查材料的"被引命题正文摘要"长度上界（正文本身留在 `citations` 的全文格里）。
CITATION_DIGEST_CHARS = 600

#: 被引命题的等级下限 —— 直接引用 `depsection.CITATION_MIN_LEVEL`（唯一门槛定义）。
#:
#: 2026-11-05 改口径前这里是档位字面量 `"proof_review"`，与 `depsection` 各写一份；
#: 真机反例 `mp3-r3/000000`（档位 `proof_review`、等级 `conjecture`）上两处给相反答案：
#: B 拒、V 放行。业主裁定「判定面一律读等级」之后，这里不再写第二份字面量：
#: 阈值与允许集合都从 `depsection` 那一个定义取。
CITATION_EVIDENCE_FLOOR = _DS.CITATION_MIN_LEVEL


def admissible_evidence_kinds() -> tuple[str, ...]:
    """够格被引的等级（按由强到弱的顺序；唯一来源是 `depsection.CITATION_LEVELS`）。

    返回空元组 = 判不了（门槛定义读不到）：空集会让每一条引用都判 `inadmissible`，
    那是可见的失败；反过来在门槛坏掉时放行，就是"没查成"折成"通过"。
    """
    try:
        levels = tuple(_DS.CITATION_LEVELS)
    except Exception:  # noqa: BLE001 —— 读不到门槛 ⇒ 空集（fail-closed）
        return ()
    return tuple(g for g in reversed(EB.GRADES) if g in levels)


def citation_grade_admissible(grade: Any) -> bool:
    """这一级够不够格被引（空串 / 认不出的等级 ⇒ 不够格；判据只有一处）。"""
    return _DS.citation_level_allowed(str(grade or "").strip())


def evidence_kind_admissible(kind: Any) -> bool:
    """历史档位入参的兼容口：先按 `GRADE_TO_KIND` 反算成等级，再走等级门槛。

    为什么保留这个名字：`agent_v` 的缝与 V 的审查材料仍按历史档位字段取值（那是存量行的
    形状）。但它不另有门槛 —— 档位在这里只是"等级的反算名"的逆读，两步都不离开
    `depsection.CITATION_MIN_LEVEL` 那一个定义。判定面请直接用 `citation_grade_admissible`。
    """
    grade = EB.KIND_TO_GRADE.get(str(kind or "").strip(), "")
    return citation_grade_admissible(grade)


def _citation_checks_raw(raw: Any) -> list[dict[str, Any]]:
    """把 V 输出里的 `citation_checks` 洗成规整的五格；形状不对 ⇒ 抛 `VerificationError`。

    它是"没查成"那一档：`verdict` 不在词表里 / `stmt_id` 不是命题号形态，
    都不是"这一条判成什么"，而是这一次输出不可解析 —— 不许折成 `unknown`
    （`unknown` 是一条诚实的结论，而坏输出不是）。

    `in_material` 的缺省是 `True`（不是 `False`）：V 自己给的那几条默认就是"这一份
    证明登记过的引用"；只有 `reconcile_citation_checks` 会显式标 `False`（V 多给的）。
    缺键读成 `False` 会把"V 说的"当成"材料外的"，那是往放行的方向走。
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise VerificationError("citation_checks 必须是数组（每条被引命题一项）")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            raise VerificationError(f"citation_checks 第 {i} 项必须是对象")
        sid = str(item.get("stmt_id") or "").strip()
        if not S.is_valid_id(sid):
            raise VerificationError(
                f"citation_checks 第 {i} 项的 stmt_id 不是命题号形态（收到 {sid!r}）"
                f"：它必须是被引命题的 {S.ID_DIGITS} 位号（旧四位号仍可读）")
        verdict = str(item.get("verdict") or "").strip()
        if verdict not in CITATION_VERDICTS:
            raise VerificationError(
                f"citation_checks 第 {i} 项的 verdict 必须是 {CITATION_VERDICTS} 之一，"
                f"收到 {verdict!r}")
        flagged = item.get("quote_verbatim")
        if isinstance(flagged, str):
            verbatim = flagged.strip().lower() in ("1", "true", "yes", "y", "是", "逐字")
        else:
            verbatim = bool(flagged)
        in_material = item.get("in_material")
        out.append({
            "stmt_id": sid, "verdict": verdict, "quote_verbatim": verbatim,
            "note": str(item.get("note") or "").strip(),
            "in_material": True if in_material is None else bool(in_material),
        })
    return out


def reconcile_citation_checks(checks: Sequence[Mapping[str, Any]],
                             material: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把 V 给的那几条结论与"材料里有哪几条被引命题"对齐（缺一条就按 `unknown` 算）。

    四条规矩，都是三态纪律在这一格上的落法：
    - 材料里每一条被引命题都必须有一条结论；V 没给 ⇒ 补一条 `unknown`
      （note 写明"没有给出结论"）。判不了与没判是两件事，但两者都不能签「成立」；
    - 被引命题的档位不够格（`evidence_kind` 低于 `proof_review`，含空串）⇒ 一律改判
      `inadmissible`，不管 V 判的是"用法一致"还是别的。这一档是事实而不是判断：
      业主口径逐字「proof_review级及以上才可引用」，所以它不交给模型自由裁量（模型说
      `consistent` 也照样改判，原文附在 note 里）。判据本体是
      :func:`evidence_kind_admissible`（禁止词表从 `schema.EVIDENCE_KINDS` 现算）；
    - 被引命题不在册（`statement_missing`）⇒ 若 V 写了 `consistent` / `weaker`，
      改判 `unknown`（它读不到的那条命题，判不了"一致"；这一格不许凭印象签字）；
    - V 多给的（材料里没有那条被引命题）仍然交回去，但标 `in_material=False`：
      它不是这一份证明登记的引用，不计入挡不挡签字（挡签字只认材料里的那几条）。
    """
    by_id: dict[str, dict[str, Any]] = {}
    for chk in checks:
        row = {key: chk.get(key) for key in CITATION_CHECK_KEYS}
        row["stmt_id"] = str(row.get("stmt_id") or "").strip()
        row["verdict"] = str(row.get("verdict") or "unknown").strip()
        row["quote_verbatim"] = bool(row.get("quote_verbatim"))
        row["note"] = str(row.get("note") or "").strip()
        # 缺键 ⇒ 材料内（`in_material` 的缺省不许往放行方向走，见
        # `_citation_checks_raw` 的同一条说明）。
        row["in_material"] = row.get("in_material") is not False
        by_id.setdefault(row["stmt_id"], row)
    out: list[dict[str, Any]] = []
    for item in material:
        sid = str(item.get("stmt_id") or "")
        got = by_id.pop(sid, None)
        if got is None:
            got = {"stmt_id": sid, "verdict": "unknown", "quote_verbatim": False,
                   "note": "V 没有对这条被引命题给出结论（材料里有它）",
                   "in_material": True}
        grade = str(item.get("grade") or "")
        # 先判"这一条在不在册"（它比等级更根本：不在册的命题连等级都没有），
        # 再判等级 —— 两档都是挡签的，但点名要说清是哪一种。
        if bool(item.get("statement_missing")) and got["verdict"] in CITATION_SIGNABLE:
            got = dict(got, verdict="unknown",
                       note=(f"被引命题 {sid} 不在册 ⇒ 判不了「一致」"
                             f"（V 原文：{got['note'] or '（无）'}）"))
        admitted = item.get("admissible")
        if admitted is None:
            # 兼容旧材料的形状：没有 `grade` 那一格时，先把历史档位反算成等级
            # （`evidence_kind_admissible` 只做这一步换算，门槛仍是同一个）。新材料
            # （`agent_v.core._citation_material` 的返回）一定带 `grade`，走的是上面那条正路。
            admitted = (citation_grade_admissible(grade) if "grade" in item
                        else evidence_kind_admissible(item.get("evidence_kind")))
        if not bool(item.get("statement_missing")) and not admitted:
            tail = f"（V 原文：{got['note']}）" if got["note"] else ""
            got = dict(got, verdict="inadmissible",
                       note=(f"被引命题 {sid} 现在只是 {grade or '（空：等级算不出来）'}，"
                             f"够不上 {CITATION_EVIDENCE_FLOOR} 级 ⇒ 不够格被引{tail}"))
        out.append(dict(got, in_material=True))
    for sid, got in by_id.items():
        out.append(dict(got, in_material=False))
    return out


def citation_gate(checks: Sequence[Mapping[str, Any]], *, problem: str = "") -> dict[str, Any]:
    """引用核实的签字前置读数（纯函数）：能不能签「成立」，被哪一条挡住。

    返回 `ok` / `blocking` / `weaker` / `problem` / `why`。`blocking` 与 `weaker` 里每项
    是 `{stmt_id, verdict, note}`（点名用）。`problem` 非空是"这一档没查成"（依赖台账
    读不出来）—— 它与"核过、没有引用"必须分开，所以它也挡住签字。
    """
    blocking: list[dict[str, Any]] = []
    weaker: list[dict[str, Any]] = []
    for chk in checks:
        # 材料之外的那几条（V 多给的）不计入签字前置：它们不是这一份证明登记的引用。
        if chk.get("in_material") is False:
            continue
        verdict = str(chk.get("verdict") or "")
        entry = {"stmt_id": str(chk.get("stmt_id") or ""), "verdict": verdict,
                 "note": str(chk.get("note") or "")}
        if verdict in CITATION_BLOCKING:
            blocking.append(entry)
        elif verdict in CITATION_SIGNABLE and verdict != "consistent":
            weaker.append(entry)
    why = ""
    if problem:
        why = (f"引用核实没查成（{problem}）⇒ 这一份不能判「成立」"
               "（没查成不是「核过、一致」）")
    elif blocking:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'} 判 {e['verdict']}"
            + (f"（{e['note']}）" if e["note"] else "")
            for e in blocking)
        why = (f"引用核实挡下了「成立」：{shown} —— "
               "stronger 是引用被夸大、unrelated 是引错了、"
               f"inadmissible 是被引命题的档位低于 {CITATION_EVIDENCE_FLOOR}（不够格被引）、"
               "unknown 是判不了，四档都不许签")
    elif weaker:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'}" + (f"（{e['note']}）" if e["note"] else "")
            for e in weaker)
        why = (f"引用核实通过，但有 {len(weaker)} 条只用到了弱形式：{shown} —— "
               "弱形式不是错，记下来给读的人一句情报")
    return {"ok": not blocking and not problem, "blocking": blocking, "weaker": weaker,
            "problem": str(problem or ""), "why": why}


def citation_blocks(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """这一签里挡住「成立」的引用核实条目（空列表 = 没有被挡）。

    `signs_bit3` 用它：台账那一行写着 `成立`、而引用核实里有一条 `stronger` /
    `unrelated` / `unknown` ⇒ 这一签不许落地。硬闸放在这里（而不是只放在写路径上），
    因为"手写一条成立行"与"V 自己判了成立"在读者眼里没有区别。

    材料之外的那几条（`in_material=False`，V 多给的）不算挡签 —— 与
    :func:`citation_gate` 逐字同一条规则（2026-10-27 收口）：它们不是这一份证明
    登记的引用，挡不挡只看材料里的那几条。改前这里没有这一句，而
    `in_material` 又不落盘 ⇒ 落盘再读回来时两个判定口给出相反结论。
    老行没有这一格 ⇒ 按材料内读（`!= False`，不是 `is True`）。
    """
    checks = row.get("citation_checks")
    if not isinstance(checks, (list, tuple)):
        return []
    return [{"stmt_id": str(c.get("stmt_id") or ""), "verdict": str(c.get("verdict") or ""),
             "note": str(c.get("note") or "")}
            for c in checks if isinstance(c, Mapping)
            and c.get("in_material") is not False
            and str(c.get("verdict") or "") in CITATION_BLOCKING]


def apply_citation_gate(verdict: Mapping[str, Any],
                        gate: Mapping[str, Any]) -> dict[str, Any]:
    """把引用核实的结论并进 V 的结论（纯函数：`parse_verdict` 的形态进、同一形态出）。

    三档处置（业主 2026-10-26 的签字前置；2026-11-01 按两态结论改口径）：
    - 有 `stronger` / `unrelated` / `inadmissible` ⇒ 不许判「成立」：结论改判「有毛病」，
      逐条 error 落进 findings（点明哪一条被引命题、差在哪）。这就是受控拒绝：这一签
      签不成，而"为什么签不成"在台账里逐字可读；
    - 只有 `unknown` ⇒ 这一档是「没查成」，不是「没问题」：结论标签不动（V 没找到缺陷），
      但这一签不签发，理由写「引用核不了」—— `blocking` 里那条 `unknown` 同时是
      `findings` 里一条 error（⇒ `unresolved_errors > 0`）且进 :func:`citation_blocks`
      ⇒ :func:`row_signable` 为假 ⇒ 既不翻位、也不投"连续成立"那一票。
      改前这里把结论改判成第三态 `看不出来`；业主 2026-11-01 裁定那一档不存在，
      而"判不了挡签"这件事本来就有自己的落点（引用闸），不需要借一个假结论来说；
    - 只有 `weaker` ⇒ 结论不动（可签），但加一条 info 把"这一步只用到弱形式"记下来；
    - `gate["problem"]` 非空（依赖台账读不出来 ⇒ 这一档没查成）⇒ 与 `unknown` 同一档：
      结论不动、`citation_gate.problem` 随行落盘 ⇒ `signing_gate_problem` 挡住这一签。
      改前它也把结论改判成第三态；那是把"没查成"折成一个假结论，同一批改掉。

    改判时 `defect_step` 保留模型给的那一步（它可能仍是承重步）；模型没给就留 `None` ——
    这一档的缺陷是按"被引命题"定位的，不是按步号定位的（`parse_verdict` 因此允许
    "有毛病 + 有挡签的引用核实 + 没有步号"这一种组合）。
    """
    out = {
        "verdict": str(verdict.get("verdict") or ""),
        "defect_step": verdict.get("defect_step"),
        "quote": str(verdict.get("quote") or ""),
        "why": str(verdict.get("why") or ""),
        "findings": [dict(f) for f in (verdict.get("findings") or [])],
        "unresolved_errors": 0,
        "citation_checks": [dict(c) for c in (verdict.get("citation_checks") or [])],
        #: 折过档的那一行把模型原话带下去（`apply_citation_gate` 是纯函数，不许吃掉它）。
        "verdict_raw": str(verdict.get("verdict_raw") or ""),
    }
    blocking = list(gate.get("blocking") or [])
    defect = [e for e in blocking if str(e.get("verdict") or "") != "unknown"]
    for entry in blocking:
        kind = f"citation_{entry.get('verdict') or 'unknown'}"
        tail = f"：{entry['note']}" if entry.get("note") else ""
        sid = entry.get("stmt_id") or "（没有号）"
        verdict_text = str(entry.get("verdict") or "")
        if verdict_text == "unknown":
            detail = (f"引用核实：被引命题 {sid} 判不了（unknown）{tail}"
                      "；引用核不了 ⇒ 这一档没查成、这一份不签发（不是「没问题」）")
        elif verdict_text == "inadmissible":
            detail = (f"引用核实：被引命题 {sid} 的档位够不上 {CITATION_EVIDENCE_FLOOR}{tail}"
                      "；档位不够格是事实，与原文一致不一致无关 ⇒ 这一份不能判「成立」")
        else:
            detail = (f"引用核实：被引命题 {sid} 判 {verdict_text}"
                      f"{tail or '：V 没有写理由'}"
                      "；这一条使这一份不能判「成立」")
        out["findings"].append({"level": "error", "step": None, "kind": kind,
                                "detail": detail})
    for entry in (gate.get("weaker") or []):
        tail = f"（{entry['note']}）" if entry.get("note") else ""
        out["findings"].append({
            "level": "info", "step": None, "kind": "citation_weaker",
            "detail": (f"引用核实：这一步只用到了被引命题 "
                       f"{entry.get('stmt_id') or '（没有号）'} 的弱形式{tail}"
                       "；不等于错，但读的人要知道它没有被用满"),
        })
    if defect and out["verdict"] == "成立":
        # 引用被夸大 / 引错 / 档位不够 ⇒ 这是找到了缺陷（缺陷按被引命题定位）。
        out["verdict"] = "有毛病"
    # 只有 `unknown` / 依赖台账读不出来 ⇒ 结论不动（它没找到缺陷）：这一签由引用闸挡住
    # （那几条 error 让 `unresolved_errors > 0`，且 `citation_blocks` / `signing_gate_problem`
    # 也挡）⇒ 不翻位、不投连续成立那一票。这里刻意不造第三态（业主 2026-11-01）。
    if blocking or gate.get("problem"):
        gate_why = str(gate.get("why") or "")
        if gate_why:
            out["why"] = (out["why"] + "；" + gate_why) if out["why"] else gate_why
    out["unresolved_errors"] = sum(1 for f in out["findings"] if f.get("level") == "error")
    return out


class VerificationError(ValueError):
    """这次审校没查成（不是"有毛病"）：输出不合法、字段缺、取值不在词表里。"""


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def verifications_dir(root: str | Path) -> Path:
    """验证台账目录（工作区根下的 `verifications/`；只算路径，不建目录）。"""
    return Path(root) / VERIFICATIONS_DIR


def verification_ledger_path(root: str | Path, statement_id: str) -> Path:
    """一个命题一份台账：`verifications/<命题号>.jsonl`。

    命题号的形态判据只有一处：`schema.is_valid_id`（当前宽度六位，旧数据四位读侧兼容）——
    2026-10-14 之前这里自己写死了"恰好 4 位"，宽度一改就会把新号当场拒掉。
    """
    sid = str(statement_id or "").strip()
    if not S.is_valid_id(sid):
        raise VerificationError(
            f"命题号必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），"
            f"收到 {statement_id!r}")
    return verifications_dir(root) / f"{sid}.jsonl"


#: 「命题还没在册时审的那一签」落在哪：`verifications/pending/<sha>.jsonl`（D-34）。
#:
#: 为什么单独一个子目录（而不是塞进 `verifications/` 顶层）：顶层那一层是"每个命题一份台账"，
#: `list_verifications` 与收工门 R10 都按顶层 `*.jsonl` 逐个命题读 —— 混进一份没有命题号的
#: 台账会让那些读法把一行"还不属于任何命题"的签算到某个命题头上。子目录不进那条 glob，
#: 而认领它的入口只有一个：:func:`pending_sign`（按对象内容的 sha）。
PENDING_DIR_NAME = "pending"
#: pending 台账里那一行的编号前缀（`u-NNNNNN`：u = 未登记）。
PENDING_PREFIX = "u-"


def pending_dir(root: str | Path) -> Path:
    """pending 台账的目录（只算路径，不建目录）。"""
    return verifications_dir(root) / PENDING_DIR_NAME


def pending_ledger_path(root: str | Path, key: str) -> Path:
    """一份 pending 台账：`verifications/pending/<内容 sha>.jsonl`（按对象内容分文件）。"""
    text = str(key or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise VerificationError(
            "pending 台账的文件名必须是 64 位十六进制的 sha256（按对象内容分文件），"
            f"收到 {key!r}")
    return pending_dir(root) / f"{text}.jsonl"


def record_pending_sign(root: str | Path, *, proof_text: str, verdict: Mapping[str, Any],
                        verifier: str = "V", object_sha256: Any = "",
                        object_path: Any = "",
                        secretary_judge: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """把"命题还没在册时"的一次审校落进 pending 台账，返回那一行。

    为什么要这一格（D-34，r34b 的真机现场）：V 审完判「成立」，而 `statements` 是 0 行 ——
    `record_verification` 要一个合法命题号才写得出 `verifications/<号>.jsonl`，于是那一签
    没有落点，结论只能 escalation 掉。结论丢了不是"没审"，是"审了没处记"。

    落点按对象内容的 sha 分文件：`object_sha256`（那份报告 / 证明文件的字节 sha256）给了
    就用它，没给就退到证明正文的 sha（`proof_sha256`）。两个 sha 都写进行里，所以 B 后来
    认领时按哪一个都找得到（"顺序不再重要"）。

    结论一样要过 `parse_verdict`（结构解析；p247 起它不判定、不折档）。
    `secretary_judge`（p247）随同一行落盘 —— axis 是这一行唯一的轴来源；不给 ⇒ 这一行
    没有轴，`row_signable` 为假（fail-closed，不会按 `verdict` 字面签）。
    引用核实那一格（`citation_checks`）随同一行落盘，形状与 `record_verification` 逐格相同。
    """
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        # 老调用方带的原话照旧带下去（审计用）。
                                        "verdict_raw": verdict.get("verdict_raw", ""),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    text = str(proof_text or "")
    sha = proof_sha(text)
    obj = str(object_sha256 or "").strip().lower()
    key = obj or sha
    path = pending_ledger_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"pending 台账有读不出来的行：{problems[:3]}")
    row = {
        "verification_id": f"{PENDING_PREFIX}{S.format_id(len(rows) + 1)}",
        # 没有命题号是这一档的定义（命题还没在册）：两个键都留空串而不是缺键 ——
        # 读的人要能分辨"这一行不属于任何命题"与"这一行是旧格式、没有这个键"。
        "statement_id": "", "stmt_id": "",
        "proof_no": int(DEFAULT_PROOF_NO),
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        "citation_checks": list(checked.get("citation_checks") or []),
        "proof_sha256": sha, "proof_chars": len(text),
        #: 对象（盘上那一份报告 / 证明文件）的字节 sha256 与相对路径：认领时按它。
        "object_sha256": obj, "object_path": str(object_path or "").strip().replace("\\", "/"),
        "round": len(rows) + 1, "used_faces": [], "submission_id": "",
        "landed": "pending", "at": _now_iso(),
    }
    if str(checked.get("verdict_raw") or "").strip():
        #: 老调用方带过来的原话（只在真带了时写）。
        row["verdict_raw"] = str(checked["verdict_raw"]).strip()
    #: p247：轴是这一行唯一的判定来源（由 V 的秘书读回复后语义判定）。
    #: 无条件写（业主裁定 2）：改前是"给了才写"，于是没给的那一行落进
    #: `historical_axis` 的历史兼容支、按 `verdict` 字面拿到 clean —— 三行不经秘书的
    #: 「成立」就能凑满连续次数并签住第 3 位。现在没给就写 :data:`NO_SECRETARY_JUDGE`
    #: （未判成：`checked=False` + 空轴），`row_signable` 为假、连续计数不算票。
    row[SECRETARY_JUDGE_KEY] = secretary_judge_cell(secretary_judge)
    #: 同 `record_verification`：I10 硬禁令的机械命中只作读数（条件写入、不参与判定）。
    _pending_banned = banned_markers_in(text)
    if _pending_banned:
        row["hard_ban_markers"] = list(_pending_banned)
    _append_verification(path, row)
    return row


def pending_rows(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """pending 台账的全部行（按落盘顺序；坏行照实报出，不静默跳过）。"""
    base = pending_dir(root)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    if not base.is_dir():
        return out, problems
    for file in sorted(base.glob("*.jsonl")):
        rows, bad = JF.read_jsonl(file)
        problems.extend(f"{PENDING_DIR_NAME}/{file.name}: {b}" for b in bad)
        out.extend(rows)
    return out, problems


def pending_sign(root: str | Path, *, object_sha256: Any = "",
                 proof_shas: Sequence[str] = ()) -> dict[str, Any]:
    """按对象内容的 sha 认领 pending 台账里的那一签（最近一次审校说了算）。

    返回 `{"found","verdict","proof_sha256","object_sha256","ledger","row","why"}`。
    `found=False` 只表示"pending 里没有盖住这一份的签"，不是"没查成"；
    读不出来时才抛 `VerificationError`（三态：没查成不许折成没有签）。

    `row` 是认到的那一整行（`found=True` 时非空）：判据在调用方那一侧，而它们要的
    `unresolved_errors` / `citation_checks` / `citation_gate` 三格只在行上 ——
    交半行出去等于逼调用方退回"只看 verdict 那个词"。
    """
    out: dict[str, Any] = {"found": False, "verdict": "", "proof_sha256": "",
                           "object_sha256": "", "ledger": "", "row": {}, "why": ""}
    obj = str(object_sha256 or "").strip().lower()
    wants = {str(s or "").strip().lower() for s in (proof_shas or ()) if str(s or "").strip()}
    rows, problems = pending_rows(root)
    if problems:
        raise VerificationError("；".join(problems[:3]))
    hit: dict[str, Any] | None = None
    for row in rows:
        got_obj = str(row.get("object_sha256") or "").strip().lower()
        got_proof = str(row.get("proof_sha256") or "").strip().lower()
        if obj:
            if got_obj != obj:
                continue
        elif wants:
            if got_proof not in wants:
                continue
        else:
            continue
        hit = row
    if hit is None:
        where = (f"对象 sha256 {obj[:12]}…" if obj else f"证明正文 sha {sorted(wants)[:1]}")
        out["why"] = (f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里没有盖住这一份"
                      f"（{where}）的签 —— 命题还没在册时 V 也没审过它")
        return out
    out.update(found=True, verdict=str(hit.get("verdict") or ""),
               proof_sha256=str(hit.get("proof_sha256") or ""),
               object_sha256=str(hit.get("object_sha256") or ""),
               #: 认到的那一整行（2026-10-27 补）。为什么要交出去：`signs_bit3` 要读
               #: `unresolved_errors` / `citation_checks` / `citation_gate` 三格，而它们
               #: 改前在这一格里被丢掉了 ⇒ 调用方只能退回"看 verdict 那个词"，
               #: 于是同一行内容在 pending 与命题台账两处被两套判据读。
               row=dict(hit),
               ledger=(f"{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/"
                       f"{str(hit.get('object_sha256') or hit.get('proof_sha256') or '')[:64]}"
                       f".jsonl#{hit.get('verification_id') or '?'}"))
    out["why"] = (f"{out['ledger']} 是按对象内容 sha 认领到的那一签，"
                  f"verdict={out['verdict']!r}")
    return out


def citations_block(citations: Sequence[Mapping[str, Any]],
                    problem: str = "") -> str:
    """引用核实那一节怎么印进提示词（纯字符串拼装，只有材料、没有句柄）。

    业主 2026-10-26：F 的"引用"是自然语言描述，不是逐字引文 ⇒ 光给编号没有用，
    V 要看到"F 是怎么说的"与"被引命题真正说的"两样东西才能判它成不成立。
    所以每一条都印三样：F 那句话（含它出自依赖行哪个键）、被引命题正文摘要、
    被引命题现在的档位（够不够格被引）。
    """
    lines: list[str] = ["## 引用核实（F 在依赖面登记的引用；逐条核 F 是不是这么用的）"]
    if problem:
        lines.append(f"- 依赖台账读不出来（{problem}）⇒ 这一档没查成：没有材料就不能判"
                     "「一致」，判不了就写 unknown（它挡住「成立」）。")
    if not citations:
        if not problem:
            lines.append("- 这一份证明没有登记任何被引命题（`dependencies` 里没有指向本条命题"
                         "这一份证明的 `stmt:` 依赖）⇒ `citation_checks` 给空数组。")
        else:
            lines.append("- 材料读不到时不许说「这一份证明没有引用」：那是把「没查成」说成"
                         "「核过、没有引用」。")
        return "\n".join(lines)
    lines.append(f"- 登记了 {len(citations)} 条被引命题。每一条都要给一档结论："
                 "少给一条就按 unknown 算，而 unknown 挡住「成立」。")
    for i, item in enumerate(citations, 1):
        sid = str(item.get("stmt_id") or "")
        groups = "、".join(str(g) for g in (item.get("path_groups") or [])) or "1"
        lines.append("")
        lines.append(f"### {i}. {sid}（路径组 {groups}）")
        if item.get("statement_missing"):
            lines.append("- 册子里没有这条命题（不在册）⇒ 只能判 unknown，不许判一致。")
        else:
            kind = str(item.get("evidence_kind") or "")
            if item.get("admissible"):
                lines.append(f"- 它现在的档位：`{kind}`（够格被引）")
            else:
                lines.append(
                    f"- 它现在的档位：`{kind or '（空：没有档位）'}`，"
                    f"够不上 `{CITATION_EVIDENCE_FLOOR}` 级 ⇒ 不够格被引："
                    "这一条要判 inadmissible（不管原文一致不一致）。")
            lines.append(f"- 被引命题正文：{item.get('statement_digest') or '（正文为空）'}")
        for path in (item.get("paths") or []):
            note = str(path.get("note") or "")
            where = str(path.get("note_source") or "")
            lines.append(
                f"- F 的说法（路径组 {path.get('path_group')}，依赖行 "
                f"{path.get('dep_id') or '?'} 的 `{where or '（没有话）'}`）："
                f"{note or '（F 没有写为什么引它）'}")
            quote = str(path.get("quote") or "")
            # 引文原话单独印一次，但若 F 那句话里已经含着它（写侧常把 quote 拼进 label，
            # 例如"手稿依赖段（第 4 行）：由引理 2"）就不再重复一遍。
            if quote and quote not in note:
                lines.append(f"- 依赖行上的引文原话：{quote}")
            status = str(path.get("status") or "")
            if status:
                lines.append(f"- 这条依赖的状态：{status}")
    return "\n".join(lines)


def _cold_start_review_checklist() -> str:
    """`cold_start_prompt` 的「审阅清单（这是嘱托，不是门）」那一节。

    2026-11-06 从 `cold_start_prompt` 里原样搬出来（纯机械抽取：字面、顺序、空行一个
    字节都没动）。为什么抽它：它自成一节、且只吃常量字面（不读任何入参），而
    `cold_start_prompt` 已经越过 200 行那条软线 —— 抽成函数之后调用处只剩一行转调。
    改这里的文案等于改提示词（要抬 `PROMPT_VERSION`、重冻十一格摘要），属人审范围。
    """
    return (
        # ---- 审阅清单（draft/122 按 F 的交付面重剪；S5 的提示词落点）----
        #
        # 为什么清单在提示词里、而它又明说"不是门"：`docs/DEVELOPMENT-SPEC.md` §13 的分工
        # —— 提示词管"想让它这么做"，判据管"不许它不这么做"。下面每一条都是"怎么读"的
        # 方法（判不了），所以只能是嘱托；而"V 是不是逐行验证过"本来也不可机器判
        # （draft/126 §三 的同一句）。完整版在 V 的技能手册里
        # （`skills/V/产出-只产意见-签分两档.md`），这里给压缩版 —— 它每次审阅都要带，
        # 而手册是按需读的。
        "\n## 审阅清单（这是嘱托，不是门）\n"
        "`docs/DEVELOPMENT-SPEC.md` §13：提示词管「想让它这么做」，判据管「不许它不这么做」。"
        "下面这一份属于前者 —— 没有任何一格会因为「你没按清单逐条走」而变红；"
        "你不按它走时，你写「成立」的那句话就只是一句印象。\n"
        "清单按 F 在本框架里实际交付的那种证明重剪（带显式假设清单的条件性证明 = 假设清单"
        "＋ 定理链＋ 由构造给出的中间对象 ＋ 条件性结论 ＋ 指数/常数记账），每关只问 F 能回答的问题：\n"
        "- 假设关：H-1 每条假设里的符号有没有公式级定义（只有描述 ⇒ 它不是数学命题）；"
        "H-2 这条假设的构造有没有用到结论本身（循环）；H-3 它给的界够不够支撑用到它的那一步；"
        "H-4 假设只在某个区域给控制、而证明用在区域之外；H-5 每条假设是不是真在某一步被用到。\n"
        "- 定理链关：T-1 每一步的「由…得」有没有真推导（引理名与适用范围；只写"
        "「由上式可得」而无中间代数的按空洞处理）；T-2 依赖有没有断在某条没证完的 Lemma 上；"
        "T-3 常数是否依赖于正在取极限的参数（把「对每个固定 X 存在 Y」当成一致界）；"
        "T-4 逐项取极限/求和/积分的依据是哪一条（一致收敛 / 绝对收敛 / 控制收敛 / 有限性）；"
        "T-5 用恒等定理时两边是否都是确定的亚纯函数（陈述带 1 + O(·) 的，先改成显式因子）；"
        "T-6 Lemma 的陈述与证明给的结论是否同一件事；T-7 例外情形（小素数 / 整除判别式 /"
        "边界指数 / 退化）有没有单独处理；T-8 主定理的结论逐字对回假设 —— 多出来的部分靠什么。\n"
        "- 记号关（这一关必须真的算）：N-1 变量替换有没有改回去（定义了 C(s)=s+c 之后，"
        "全篇还有几处把 C(s) 写成 s）；N-2 反函数回代时实部/虚部各移了多少、结论里说清没有；"
        "N-3 指数账 —— 把全篇的指数与常数（3/16、1/4、δ1、δ2、ε(q,t)…）列成一张表逐个代入核对，"
        "同一常数在两节取不同值就报出来；N-4 文中说「更强/更弱」时与真正需要的条件并列比较。\n"
        "- 条件性措辞关：C-1「在 (H1)–(Hn) 下」是否精确（每条假设良定义吗）；"
        "C-2 有没有把「猜想」当「定理」用；C-3 有没有把「未核实的外部结果」当标准事实"
        "（写「标准/众所周知/经典结果」的，要求它给出本情形的确切陈述；"
        "你只判「说没说清」，不去查文献）；C-4 正文的自我定位与标题/摘要是否一致。\n"
        "- 明确不归 F 的（不许拿这些凑数）：文献真伪与页码级核对（归 B；C-3 只判说清没说清）、"
        "实验数值 / 复现结果（归 E）、稿件排版 / 术语统一 / 写作风格（归 G / C）、"
        "「这篇论文有没有价值 / 想法好不好」（那是 M 的）。"
        "回复里若主要以这些作为「发现问题」的依据 ⇒ 它们不是这份证明的缺陷，"
        "但这也不是「成立」：判 `有毛病`，把「理由面错位」写成一条 finding"
        "（`kind` 写明「理由面错位」，`step` 与 `defect_step` 指到你拿来质疑的那一步）——"
        "秘书只看 `findings` 与 `defect_step`，写进 `why` 不算数。\n"
        "- 结论语法：有毛病 ⇒ 逐条三段式（位置（步号）/ 原文逐字 / 类型编号 / 为何不成立 / "
        "需补什么）；成立 ⇒ 说清走过哪几关、每关的核对记录，以及你尝试过的反驳"
        "（在哪一处试着构造反例、为什么失败）；只写「整体框架没问题 / 思路上没问题」"
        "而不带这些记录 ⇒ 那就是没逐行验证（你至少有一处没核）⇒ 判 `有毛病`、"
        "把「核到哪一步、从哪一步起没核」写进 `findings`（带步号）并在 `defect_step` 指到"
        "那一步；秘书按题面判「有缺陷要指出」，这一签不签发 —— 不许写成「成立 + 一条备注」。\n"
    )


def _cold_start_proof_strength(*, lean_on: bool) -> str:
    """`cold_start_prompt` 的「成立是什么强度」那一节（两类 proof 并列 + 穷举会审）。

    与 `_cold_start_review_checklist` 同一笔抽出，同样逐字节未动。唯一的入参是
    `lean_on`（原 `cold_start_prompt` 里那个 `_lean_on` 开关读数）：它只决定
    「本会话 Lean 形式化：已开启 / 已关闭」那一句。
    改这里的文案等于改提示词（要抬 `PROMPT_VERSION`、重冻十一格摘要），属人审范围。
    """
    return (
        # 2026-10-17（Lean 审计 S3）：这是 V 的真实入口（`agent_v/core.py` 用它，
        # 而 `system_prompt("V")` 全仓没有生产路径渲染）⇒ 开关与"成立≠proof"必须写在这里，
        # 否则 V 在 Lean 开着/关着时行为完全一样，而 H 会把它签的第 3 位当凭据。
        #
        # 2026-10-23 晚（业主：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」）：
        # 这里此前写的是「evidence_kind=proof 只由 verify.check_formal 的检查器输出产生；
        # 要 proof 就请 M 派 E 走 formal 那条路」—— 那句话现在是假话（穷举证据也能拿 proof，
        # 而签字的人正是 V），它会让 V 把 E 交来的穷举证明读成"不归我审"，或者反过来去要
        # 一份自然语言证明。所以改成两类 proof 并列，并把穷举那一档的入口写在这里。
        # 2026-11-01（业主 P0-2）：这两句此前是「签字的人是你」与「七项全过才签」——
        # 两处都把签说成 V 自己发的，与同一份提示词第 8 行那句互斥（p248 起那一句分成
        # 在册 / 未在册两档：在册「发不发签由你的秘书判定并落盘」，未在册「由你颁发签信封、
        # 由收方秘书落块」）。现在统一：在册档 V 给判定、发签在秘书；未在册档 V 颁发信封、
        # 收方秘书落块（业主 2026-11-04 的明文例外，见 `specs/v.py` 与 `agent_v/core.py`）。
        "\n## 你这个「成立」是什么强度：两类 proof 并列\n"
        f"- 本会话 Lean 形式化：{'已开启' if lean_on else '已关闭'}；\n"
        "- `proof` 级证据有两类，并列、不分高低：\n"
        "  ① Lean 形式化 —— 凭据是 `formal.check_formal` 的检查器原话；\n"
        "  ② 穷举 —— 凭据是 E 写的那份程序 + ②③；发签分两档：在册档由你的秘书判定并落盘，"
        "未在册档不问秘书（机械会审全过即由你颁发签信封、收方秘书落块）；你只给结论，"
        "见下面那一档；\n"
        # 2026-10-24：判据 long 期望这一句「不构成 `proof`」—— 它的意思是"
        # 你这一次逐行走查的「成立」本身不是 proof 级凭据：proof 档要那两类里的某一份"
        # （检查器原话 / 穷举那份程序），你这一签是给它们背书的，不是替代它们。
        "- 要说清强度：你这一次的「成立」本身不构成 `proof` —— 它是对上面两类里某一份的背书；"
        "`proof` 级证据仍然要那一份凭据（检查器原话，或穷举那份程序 + ②③）。\n"
        # 2026-11-04（审 C 区）：这一句此前一个字都没有 —— 而档位回填
        # （`_grade_recomputed_from_signature`）正是由这一签触发的：在册那一行在签落位那一刻
        # 按现行签把 `evidence_kind` 重算一遍，目标档按通道给。V 不知道这件事，就会把
        # "穷举那一篇"读成"我审过了、所以是 proof_review"（那是错的终态，`draft/178`）。
        "- 等级不归你算：B 收录这份稿、认出这一签时，按现行签**现算等级**（只升不降，"
        "`_grade_recomputed_from_signature`）—— 通道是穷举程序"
        "（三段式证明栏 + 实验台账里那条由你签下的穷举证明）⇒ `theorem`；通道是文字证明 ⇒ "
        "`pre_theorem`。`evidence_kind`（`proof` / `proof_review`）只是由等级反算的历史列名。"
        "判据只有一处（`numericproof.find_signed_exhaustion_for_column`）："
        "穷举那一篇停在 `pre_theorem` 是错的终态，因为 V 不能逐行走查一份程序。\n"
        "- 所以别在理由里写「已形式化验证」（那是第 ① 类的说法）；穷举那一类你要写的是"
        "「穷尽性与会审七项已核」。\n"
        "\n## 穷举型证据会审（证明栏第 ① 段是程序、且不是 `.lean` 时走这一档）\n"
        "- 你的入口是七项机械会审，一条一项、逐条给读数：① 程序地址在不在盘上、读不读得出来；"
        "② 报告落盘且三块齐（`out/experiments/<实验号>/exhaustion.md`）；"
        "③ 搜索空间的数字与代码里的循环/参数一致；④ 对称性/剪枝的理由成不成立；"
        "⑤ 边界覆盖写没写、数字对不对得上；⑥ 结论是穷尽而不是抽样；"
        "⑦ 形式化那一格填的类别对不对（数值定理填数值程序、理论定理填 `.lean`）。\n"
        "- 结论落在三格：`exhaustion_review`（整份会审读数）/ `checks`（七项逐项 ok）/ "
        "`missing`（缺哪一块材料）。\n"
        "- 缺材料（报告没落地、实验行没有、②③ 缺一块）⇒ 这一格没查成：点名缺哪一块，"
        "既不判 `成立`、也不判 `有毛病`，台账里也不留那一行（留一行会把「没查成」"
        "冒充成「审过了」）；材料补齐之后重新送审。\n"
        "- 七项全过才判 `成立`；会不会发签分两档：在册档由你的秘书按连续次数判，未在册档按机械"
        "会审的连续次数判（`source=exhaustion_report`，不经秘书）—— 这一签是「对数值证据的背书」，"
        "不是「你逐行读过一份自然语言证明」。\n"
    )


def cold_start_prompt(statement_full: str, proof_text: str,
                      *, readonly_facts: str = "",
                      citations: Sequence[Mapping[str, Any]] = (),
                      citations_problem: str = "") -> str:
    """V 的冷启动提示词（纯函数：只有对象 + 只读读数，没有 F 的叙述、没有 store 句柄）。

    为什么把"提示词怎么拼"做成纯函数而不是塞进角色循环里：I12 是一个结构性质 ——
    "给它的上下文里有没有 F 的叙述 / 有没有 store 句柄"必须能被判据直接断言
    （`tests/test_verifier_role.py` 就是这么判的）。塞进循环里之后，它只能靠"读代码相信"。

    `readonly_facts` 是已经渲染好的只读读数（命题/文献/实验台账的摘要，由调用方
    从只读查询面取好传进来）—— 传字符串而不是传 store，是为了让"它能碰什么"在接口上
    就固定下来。

    `citations` 是引用核实的材料（`agent_v.core._citation_material` 的返回）：F 对每条被引命题的说法
    与被引命题的正文摘要一起进来。它仍然只是一串字符串（没有 store 句柄），
    但它是 F 的叙述 —— 所以接口上多这一格是刻意的：V 要核 F 的引用，就必须看到 F 的
    说法，这是 `draft/39` 里"不给作者叙述"那条纪律的一处有边界的例外（只给被引命题的
    依赖行，不给整份证明的作者解释）。
    """
    # 开关读数（读不懂按"关"算：与 settings 的 fail-closed 同向）
    try:
        from .settings import lean_enabled as _le

        _lean_on = bool(_le()[0])
    except Exception:  # noqa: BLE001
        _lean_on = False
    return (
        "你是验证者（V）。你这一次只做一件事：把下面这份证明按写成后的样子整体重读一遍，"
        "判断它站不站得住。\n\n"
        "你不写、不改证明；不判这命题值不值得做；不做稿件级正式审查。\n\n"
        # ---- 业主 2026-11-01：V 的结论只有两态（逐字见下）----
        #
        # 这一段是结论词那一根轴，与秘书那一条（它判的是回复的措辞）是两张词表。
        # 判据：`tests/test_v_verdict_is_two_states.py` 的 s4（这一份与 system prompt
        # 都要有两态那两句，且 `看不出来` 只许出现在那句否定式里）。
        "## 结论只有两态\n"
        "- " + TWO_STATE_LINE + "。\n"
        "- " + NO_THIRD_STATES + "。\n"
        "- 你判「成立」时不需要证明它正确，只需要说明你沿下面那几条角度都没找到缺陷。"
        "你的 `verdict` 只是陈述，不是判据：框架不会按这两个字机械定轴 —— 每一转的"
        "clean / fault 由你的秘书读这段回复后语义判定（它会写清依据）。所以拿不准、信息不足、"
        "某个记号没定义时，别用一句话糊过去：把「卡在哪一步」写进 `findings`（带步号）与"
        "`defect_step`，让秘书判得出 fault；不许写成「成立 + 一条备注」。「成立」= 零 finding："
        "`findings` 必须为空；只要有一处要改的（哪怕只是措辞建议、`level=info`），就是 `有毛病`，要指到那一步。\n\n"
        # ---- 业主 2026-10-29 追加口径：V 只产意见；发签的判定与写盘都不在 V 手上
        # （在册档由秘书判定、框架侧落盘；未在册档由 V 颁发信封、收方秘书落块 ‖
        # S5 的提示词落点；两档的边界见 `specs/v.py` 的「发签权的边界」）----
        #
        # 这一段的判据是 v9（`tests/test_v_sign_gate_streak.py` 的 c4）：V 的可见文本里
        # 不出现「签在我」「我已经签过了」这类说法，而「签由秘书」（在册档那半句）
        # 必须写出来。
        "## 你产出什么、不由你决定什么\n"
        "- 你只审手稿：命题正文读稿的 `## 命题`，证明全文读 `## 证明`，依赖面读 `## 依赖`；"
        "你产出一份审稿意见（下面那个 JSON），它进 `verifications/<命题号>.jsonl` 那一行。\n"
        "- 签落在稿上（`- V 签：` 那一行签块）；侧文件在 `out/vsigns/<被审正文的 sha>.json`"
        "（一稿一签：正文改一个字，那一签就作废），落块由收方秘书做。"
        "在册档发不发签由你的秘书判定并落盘；未在册档由你颁发签信封、由收方秘书落块。"
        "你写「成立」不等于签上了：到位没有看稿上的签块与那一个侧文件，不是你的判词；"
        "轮数与门槛由框架按这一趟送审自己数，你不需要推断它。所以别在回复里写「我已经签过了」"
        "「这一条签住了」。\n"
        # ---- 2026-11-08（业主「V 只对手稿负责」）：签落在稿上，命题位 / 等级 / 第几份归 B ----
        #
        # 改前这一格写着「看签文件与五元位第 3 位」、并把台账那一行叫「签的正本」——
        # 那两句在 V 不看 statements 之后都成了假话（`specs/v.py` 的写集为空，
        # `agent_v.core` 的命题正文只从稿的 `## 命题` 读）。判据：
        # `tests/test_v_prompt_owns_the_manuscript_only.py`。
        "- 命题位（第 3 位）、等级、这是第几份证明，都由 B 收录这份稿时决定，不在你这一侧："
        "你只负责这一份手稿站不站得住。\n"
        # ---- 2026-11-08（业主「V 只对手稿负责」）：签完之后那两格读数要读得懂 ----
        "\n## 你这一签之后：两格读数与六档\n"
        "- 稿上已签、已入台账是两格分开的读数：稿上已签看稿里的 `- V 签：` 签块"
        "（`已签` / `连续` / `正文sha`），已入台账看 `statements` 里这一份正文的 sha 与第 3 位。\n"
        "- `signed_pending_filing`：稿上已签、册里还没有证明行（或第 3 位没翻）⇒ 等 B 收录；"
        "这不是「签丢了」。\n"
        "- `signed_stale_in_ledger`：稿上已签、册里是旧版 ⇒ 签还在，等 B 收录这一版；"
        "册里现行那一版的号与 sha 会在读数里点名。\n"
        "- 另外四档：`filed`（两格都对上）/ `unsigned`（都没签）/ `abandoned`（明确放弃）/ "
        "`unreadable`（没查成）。\n"
        "- 你看不到审阅之外的任何东西：你只看见下面这份命题、证明与只读读数；"
        "谁读你的意见、之后怎么处理，都不进你的输入，也不该出现在你的输出里。\n\n"
        "## 硬禁令（命中哪一条就指到那一步）\n"
        "- 无条件前提（结论要的前提没写出来）；\n"
        "- 无依据的步骤（既没引到在册的 id，也没有同段内的推导）；\n"
        f"- 缝：{'、'.join(HARD_BAN_MARKERS)} 这类「跳过去」的措辞；\n"
        "- 引用到一条不干净的命题（还是猜想 / 已作废 / 只是 assumption）。\n\n"
        "## 只读读数（你只能看这些；没有 store 句柄，也不给你作者的任何解释）\n"
        f"{readonly_facts.strip() or '（调用方没有附只读读数）'}\n\n"
        "## 命题（含完整假设）\n"
        f"{str(statement_full or '').strip() or '（空）'}\n\n"
        "## 证明全文\n"
        f"{str(proof_text or '').strip() or '（空）'}\n\n"
        f"{citations_block(citations, citations_problem)}\n\n"
        "## 只输出一个 JSON 对象（不要解释文字、不要代码围栏）\n"
        '{"verdict": "成立|有毛病", "defect_step": <整数或 null>, '
        '"quote": "<命中的原话，逐字>", "why": "<一句话理由>", '
        '"findings": [{"level": "error|warning|info", "step": <整数或 null>, '
        '"kind": "<短语>", "detail": "<指到那一步的说明>"}], '
        '"citation_checks": [{"stmt_id": "<被引命题号>", '
        '"verdict": "consistent|weaker|stronger|unrelated|inadmissible|unknown", '
        '"quote_verbatim": <true 或 false>, "note": "<一句话依据：一致在哪 / 差在哪>"}]}\n'
        "- `defect_step`：有毛病时必须给出那一步的编号（从 1 起数，按证明里的步骤顺序）；\n"
        "- `成立` = `findings` 为空（零 finding）；有一条要改的就是 `有毛病`，"
        "在 `defect_step` 指到那一步、把那一条写进 `findings`。\n"
        "- 没有第三个词：写成「判不了 / 我无法判断」不是一种结论 —— 那是没做完审；"
        "框架不折档（不把它算成成立、也不算成有毛病），由秘书读这段回复后语义判成"
        "clean / fault，并在 `findings`（带步号）与 `defect_step` 里对得上卡在哪一步；"
        "秘书按题面判「有缺陷要指出」时，这一签不签发。如果你确实找不出缺陷，就把核对记录"
        "写出来（" + NO_THIRD_STATES + "），不是让你写一句「判不了」当答案。\n"
        + _cold_start_review_checklist()
        # ---- 引用核实那一档的口径（业主 2026-10-26 两批裁定，逐字见 CITATION_VERDICTS）
        + "\n## 引用核实怎么判（正常写证明就是不会逐字的；判据不是字面像不像）\n"
        "- `consistent`：F 的用法与这条命题真正说的条件/结论一致（改写、压缩、换符号都行）；\n"
        "- `weaker`：F 只用到了它的弱形式 —— 不等于错，是情报；这一档可以判成立，"
        "但 note 要写清只用到哪一部分；\n"
        "- `stronger`：F 用到的结论比命题本身更强（把结论说强了、或悄悄去掉了它要的假设）；\n"
        "- `unrelated`：这条命题与这一步无关（引错了）；\n"
        f"- `inadmissible`：被引命题的**等级**低于 `{CITATION_EVIDENCE_FLOOR}`（"
        "`conjecture` / `strong_conjecture` / 空）⇒ 不够格被当作依据引，不管用法一致不一致；\n"
        "- `unknown`：材料不足判不了（不在册 / 正文读不到）—— 它不是 `consistent`。\n"
        "- `quote_verbatim` 只当信息记（F 那句话是不是逐字抄的），它不影响结论、也不影响签字。\n"
        "- 有一条 `stronger` / `unrelated` / `inadmissible` / `unknown` ⇒ 这一份不许判 `成立`"
        "（你写成成立也会被改判）；只有全部 `consistent` / `weaker` 才签得成。\n"
        + _cold_start_proof_strength(lean_on=_lean_on)
    )


def proof_sha(proof_text: str) -> str:
    """被审证明的 sha256（钉住"审的是哪一份"；与台账 id 的指纹口径同一套）。

    ## 单一实现（2026-11-09 T2 收口）

    真身只有一个：:func:`proofregistry.proof_sha` —— 它认识两种入参（一份手稿 ⇒
    `## 证明` 那一节；一段证明正文 ⇒ 逐字节）。本函数只转发，不再自带第二把尺。

    为什么必须转发：改前这里是一行裸 `hashlib.sha256(str(proof_text))`，而 V 签盖的是
    手稿 `## 证明` 那一节的 sha ⇒ 同一个"手稿"经这两个入口会得到两个不同的 sha，
    跨入口对拍时表现为"签不上"或"签错了也能过"。转发之后两个入口对任何输入同值；
    对"一段证明正文"这个既有调用面，结果逐字节不变（见 T2 收口报告的逐调用点清单）。

    签名保持 `(proof_text: str) -> str`：既有调用点逐字不改（本批只换实现）。
    """
    from . import proofregistry as _PR

    return _PR.proof_sha(proof_text)


#: 一条证明（或一条命题）相对「它现在这一份正文」的六种读数（唯一口径在
#: :func:`review_standing` / :func:`statement_review_reading`）。
#:
#: 顺序是"从查清了到没查成"：`signed`（现行版有「成立」那一签，且连续次数够了）/
#: `holding`（签过、判成立，但连续次数还没到 `SIGN_STREAK_NEED`）/ `stale`（签的是旧版，
#: 待复核）/ `rejected`（现行版被签过，结论不是「成立」）/ `unsigned`（一次都没签）/
#: `unreadable`（台账读不出来 / 证明号认不出 —— 没查成，不是通过、也不是没签过）。
#:
#: 为什么 stale 与 rejected 必须分开（三态纪律）：前者是"签过、但签的不是现在这一份"，
#: 后者是"签的就是这一份、结论是没过"。把两者折成同一个"不算"会让"改完稿还没送审"
#: 与"审过了、没过"在读数上长得一样，而处置完全不同（前者重派 V，后者改证明）。
#:
#: 为什么 `holding` 必须单列（业主 2026-10-29「连续 3 次」）：第 1、2 次「成立」只落台账、
#: 不翻位（`:func:`sign_statement``）。若把它们折进 `unsigned`，那一档的措辞是"一次都没签"——
#: 而台账上明明有 1、2 行签，读的人会拿到一句假话；折进 `rejected` 更坏（"复核过、结论不是
#: 成立"同样是假话）。三档的处置也不同：holding = 再派两次审阅；unsigned = 派一次；rejected = 改证明。
REVIEW_STATES: tuple[str, ...] = ("signed", "holding", "stale", "rejected",
                                  "unsigned", "unreadable")

#: 「一次送审内部连续几次成立才发签」（业主 2026-11-02 定稿）。
#:
#: 语义写死在这里，后来人不许再把它读成"跨送审累计"：
#: - 一次 `verify_proof` 调用 = V 连判 `SIGN_STREAK_NEED` 轮（`agent_v.core.review_pass_bound`
#:   现读这个数）；三轮里任一轮「有毛病」⇒ 立刻停、打回、不签；三轮都干净 ⇒ 发签。
#: - 跨两次送审绝不累计：每份正文的签只由"某一次送审内部的那几轮"决定
#:   （业主逐字：「不允许跨两次送审累计成功数」）。旧台账里那些没有 `review_call` /
#:   `review_pass` 的行是历史形态（`legacy_rows`），读得出、但不参与新签判断。
#: - 名字里的 "STREAK" 只指"同一趟调用内连着几轮 clean"，不是"台账尾部连续几行"。
#:
#: 为什么是一个常量而不是散在各处的 `3`：判据（`review_standing` / `signs_bit3` /
#: `sign_statement`）与读数（`proof_review_gap` 的 checklist、`review_standing` 的
#: `streak/need/streak_ok`）必须说同一个数。抄成三份之后，调一次口径就会留下两处
#: 还按旧数算的暗门 —— 而那种暗门没有任何一条判据会报。
SIGN_STREAK_NEED: int = 3

#: 台账行上「秘书语义判定」那一格的键（业主 2026-10-29 的 B 段）。
#:
#: 它是行上的一格而不是 statements 的新列：连续计数从台账派生（`draft/125` §二 A），
#: 于是 `schema.py` / `store.py` 这两个 FC-27 一个字节都不用动。历史行没有这一格
#: ⇒ 读侧按「没判过」处理（空轴既不攒票也不清零；2026-11-02 起 `historical_axis` 恒空）；
#: 「计入连续」是这条口径上线之前的行为，已经不是今天的读法。
SECRETARY_JUDGE_KEY = "secretary_judge"

#: 台账行上「秘书语义判定」那一格的写侧轴（业主 2026-10-29 的 B 段；
#: 2026-10-30 第三次裁定收成两档）：`clean` = 没问题（计入连续）/
#: `fault` = 有缺陷要指出（清零）。
#:
#: 为什么没有第三格：业主逐字「不可能有判不了…只要不是完全没毛病都叫有毛病」。写侧
#: （`record_verification`）只收这两格 —— 传别的值一律落成空轴（"这一行没有轴" =
#: 这一趟没查成），于是"新判定产生第三档"在结构上不可能发生。
#:
#: 2026-11-02（追加裁定：那一档连历史兼容读也不留）：改前这里还有第二个常量
#: `SECRETARY_JUDGE_HISTORICAL_AXES = ("unsure",)` —— 老台账行上那个轴名"读得出、
#: 不计票、也不清零"。那个常量、:func:`secretary_axis` 的兼容支与
#: :func:`_hold_run_lengths` 里对应的一支一起删了：老行上的那个轴名现在读出来是
#: 空轴（"这一行没有轴"），不再有任何一格替它留位置。
SECRETARY_JUDGE_AXES: tuple[str, ...] = ("clean", "fault")

#: 写口拿不到秘书判定时，往 `SECRETARY_JUDGE_KEY` 那一格里写的东西（"未判成"）。
#:
#: ## 它挡的是哪一条（业主裁定 2：「看究竟谁登记的成立，绕过秘书登记才是缺陷」）
#: 改前两个台账写口都把这一格写成条件写入：调用方不给 `secretary_judge` ⇒ 这一格
#: 根本不落盘。而读侧的 :func:`historical_axis` 只对"没有这一格"的行生效，那一支是按
#: `verdict` 的字面给轴的（成立 ⇒ clean）。于是"省掉这一格"不是"没判"，
#: 而是把轴让给了一个字符串：
#:
#:     三次 `record_verification(verdict={"verdict": "成立"})`（一次秘书都不问）
#:     ⇒ 每行 `historical_axis` = clean ⇒ `row_signable` = True
#:     ⇒ `consecutive_holds.streak` = 3 ⇒ `bit3_payload(...)["reviewed"]` = True
#:
#: 那就是"绕过秘书登记成立"，而且是能签住第 3 位的那一条（现场读数见
#: `tests/test_v_axis_comes_from_the_secretary.py::test_l_*`）。所以写口现在无条件
#: 写这一格：给了判定就写调用方给的（轴仍然是唯一来源），没给就写这一格 ——
#: `checked=False` + 空轴 ⇒ `row_signable` 为假、连续计数既不算票也不清零
#: （fail-closed，与"问过、没判成"同一档）。
#:
#: 为什么不是"干脆写 `verdict=未判成`"：`verdict` 是 V 的陈述（p247），
#: 写盘时改它等于改历史；"未判成"是这一行有没有判过的性质，落在这一格上。
NO_SECRETARY_JUDGE: dict[str, Any] = {
    "axis": "",
    "checked": False,
    "decision": "",
    "reason": ("这一行没有秘书判定 ⇒ 未判成（轴只能由 V 的秘书给；"
               "写口 fail-closed，不按 verdict 的字面补轴）"),
}


def secretary_judge_cell(secretary_judge: Mapping[str, Any] | None) -> dict[str, Any]:
    """把调用方给的判定归一成台账那一格；没给 ⇒ :data:`NO_SECRETARY_JUDGE`（不是省掉）。

    两个写口（:func:`record_verification` / :func:`record_pending_sign`）共用这一处：

    - 没给 / 给了空 Mapping ⇒ "未判成"那一格（无条件落盘，读侧因此分不出
      "新行没问过秘书"与"老行没有这一格"—— 前者被读成未判成，后者才走历史兼容）；
    - 给了 ⇒ 轴照写，但只有 `checked` 为真时轴才写得进去：`axis=clean` 与
      `checked=False` 同时出现是"问过、没判成"，那一档必须落成空轴 ——
      否则一行"没判成"会带着一条干净的轴过 `row_signable`。

    `record_verification` 另把 `decision` / `reason` 截短（老口径），本函数只归一轴与
    `checked`，其余键由调用方照原样带着（`basis` / `source` / `defect_step` 都在里头）。
    """
    if not isinstance(secretary_judge, Mapping) or not secretary_judge:
        return dict(NO_SECRETARY_JUDGE)
    out = dict(secretary_judge)
    checked = bool(out.get("checked"))
    axis = str(out.get("axis") or "").strip()
    out["axis"] = axis if (checked and axis in SECRETARY_JUDGE_AXES) else ""
    out["checked"] = checked
    return out

#: 多证明模型的落点（业主 2026-10-22：不加 schema 字段）。
#:
#: 一条命题可以有几份证明：canonical 是 `#p1`，它的正文就是行上既有的 `proof_text`
#: （老写者只会写那一格，所以它必须继续是 `#p1` 的权威正文）；其余证明落在行 JSON
#: 里一个额外的键 `proofs`：`[{"proof_no": 2, "proof_text": "..."}, ...]`。
#: `schema.row_from_dict` 只取它认识的键（"未知字段会被忽略"），所以盘上多这一个键
#: 不需要动 `schema` —— 而"证明清单"本身是数据，不是磁盘格式契约的新字段。
PROOFS_KEY = "proofs"


def as_proof_no(value: Any) -> int:
    """把一个证明号归一成正整数（`2` / `"2"` / `"p2"` / `"#p2"` / `"stmt:000004#p2"` 都认）；认不出 ⇒ 0。

    0 表示"这不是一个证明号"。写入口用它把调用方给的 `proof_no` 归一，读侧用它判
    "这一格有没有写证明号"；两处用同一个函数，免得一边认 `p2` 一边不认。
    带 `#pN` 尾巴的写法交给 `proofloc`（全仓拆这个尾巴的唯一解析点，业主 2026-10-22）：
    两份解析意味着"台账上是第 2 条、读出来是第 1 条"这种错没有任何东西会报。
    """
    text = str(value or "").strip()
    # 只带前缀的写法（`"#p2"`）先去掉那颗 `#`：`proofloc` 把"没有命题号的 `#p2`"判成坏尾巴
    # （它是在 `used_by` 上判的，那里确实没有命题号），而本函数的入参允许这种简写。
    if text.startswith("#") and "#" not in text[1:]:
        text = text[1:]
    if "#p" in text:
        from . import proofloc as _PL   # 惰性：`proofloc` 只被这一处与依赖读侧用到

        _head, no, problem = _PL.parse_used_by_checked(text)
        # 坏尾巴（`#p0` / `#p` / `#pabc` / 多段 …）不是"第 1 条证明"：`parse_used_by` 会把它们
        # 静默折成 canonical（它是给"读侧照读"用的），而这里的返回值是给调用方判
        # "这一格到底有没有写证明号"用的 —— 折成 1 会让"这不是一个证明号"读成"这就是 #p1"。
        # 0 是本函数唯一的"不是证明号"取值（调用方一律按 `or 1` 兜底 canonical）。
        return 0 if problem else no
    text = text.lstrip("#").lstrip("pP")
    try:
        got = int(text)
    except (TypeError, ValueError):
        return 0
    return got if got >= 1 else 0


def proof_no_strict(value: Any) -> int:
    """写侧收调用方给的证明号：认不出就抛 `VerificationError`（不静默折成 `#p1`）。

    与 :func:`proof_no_of` 的分界（2026-10-22 审计第 3 条）：`proof_no_of` 是读侧的
    "这一行属于哪一份证明"，拿不到答案就按 canonical 读（读侧折平只会让读数粗，
    不会让某一份证明凭空多一签）；本函数是写侧的"调用方说要签哪一份"，拿不到答案
    必须拒绝 —— 改前两处写口都写 `as_proof_no(x) or 1`，于是 `proof_no=0`
    （"这不是一个证明号"的哨兵）被静默折成 `#p1`：调用方说"签 #p2"，台账上记的是
    `proof_no=1`，而 `verdict=成立` 一个字节不少，两份证明的第 3 位读出来是反的。

    `None` 不是"认不出"，是"没给"（缺省 canonical，见 `proofloc`）。
    调用方要区分"没给参数"与"给了但认不出"，靠的就是传 `None` 与传一个坏值的差别。
    """
    if value is None:
        return DEFAULT_PROOF_NO
    got = as_proof_no(value)
    if got >= 1:
        return got
    raise VerificationError(
        f"证明号认不出：收到 {value!r}（合法写法是 1、2、3 … 或 '2' / 'p2' / '#p2'）"
        "⇒ 拒绝：不落台账、不改任何一位（按 #p1 记会让这一签挂到别的证明头上）")


#: 证明号在行上的键名。`proof_no` 是正名；`rev` 是更早的写法。
#:
#: 为什么读侧认两个名字、而不是做一次迁移：台账是追加式文件（`verifications/*.jsonl`），
#: 改键名只能重写历史行 —— 那会把"谁在什么时候签的"改成"我们改写过它"。兼容的代价是
#: 一行读法，迁移的代价是不可逆的审计记录。`no` 是清单项里更短的那个旧别名。
PROOF_NO_KEYS: tuple[str, ...] = ("proof_no", "rev", "no")


def proof_no_of(row: Mapping[str, Any]) -> int:
    """这一行（签名行 / 证明清单项 / 任何带证明号的 dict）记的证明号；没写 ⇒ canonical（1）。

    0（"这不是一个证明号"）不出现在返回值里：调用方问的是"这一行属于哪一份证明"，
    而答案永远有一个 —— 没写就是 `#p1`（老数据的读法，业主 2026-10-22 口径：
    不带 `#pN` / 不带 `proof_no` 的老数据，读数与行为逐字不变，证明号缺省 1）。
    认不出的值同样按 1 读：读侧拿不到答案，比读成 canonical 更坏（`as_proof_no` 的
    0 留给"判这一格有没有写号"那一档用）。
    """
    for key in PROOF_NO_KEYS:
        value = row.get(key)
        if str(value or "").strip():
            got = as_proof_no(value)
            if got >= 1:
                return got
    return DEFAULT_PROOF_NO


def _read_proof_no(value: Any) -> int:
    """读侧收一个"要看哪一份证明"的号：没给 ⇒ canonical（1）；给了但认不出 ⇒ 0。

    ## 三档不许折平（业主 2026-10-22 裁定）
    - :func:`proof_no_of` 问的是"这一行属于哪一份证明"—— 答案永远有一个（老行没写就是
      `#p1`），所以它把认不出的值也读成 1；
    - :func:`proof_no_strict` 是写侧"调用方说要签哪一份"—— 认不出就抛错，一个字节都不写；
    - 本函数是读侧的"调用方点名要看哪一份"—— 它必须能回答"没有这一份"：字段/参数缺失
      才是 canonical，给了但认不出就是 0，不许折成 `#p1`。

    改前三处读口都写 `as_proof_no(x) or 1`：于是 `'abc'` / `0` / `2.0` 这类"这不是一个
    证明号"的值被静默读成 canonical —— 读数里看不出"号给错了"，而 `proof_text_of` 还会
    把 `#p1` 的正文端出来当作"你要的那一份"。折平在这里不是"读数粗一点"，是张冠李戴。

    空串与 `None` 同一档（都算"没写"）：老行可能把这一格写成空串，它与"键不存在"在读侧
    没有区别（`proof_no_of` 也是这么读的，见那里的 `if str(value or "").strip()`）。
    """
    if value is None or not str(value).strip():
        return DEFAULT_PROOF_NO
    return as_proof_no(value)


def proof_list(row: Mapping[str, Any]) -> list[tuple[int, str]]:
    """这条命题的证明清单 `[(proof_no, 正文), ...]`，`#p1` 恒在且排第一。

    两处来源（与 `PROOFS_KEY` 的注释同一口径）：
    - `#p1`（canonical）：行上的 `proof_text` —— 老写者（B / F / 秘书）只会写那一格，
      所以它必须继续是 canonical 的权威正文；
    - `#p2` 及以上：行 JSON 的 `proofs` 清单里，每项 `{"proof_no": n, "proof_text": …}`。
      清单里若也写了 1 号，读侧以 `proof_text` 为准（同一格不许有两个权威）。
    没有清单的旧行 ⇒ 只有一条 `(1, proof_text)`，读数与改前逐字相同。
    """
    out: list[tuple[int, str]] = [(1, str(row.get("proof_text") or ""))]
    raw = row.get(PROOFS_KEY)
    if not isinstance(raw, (list, tuple)):
        return out
    seen = {1}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        no = proof_no_of(entry)
        if no <= 1 or no in seen:
            continue
        seen.add(no)
        out.append((no, str(entry.get("proof_text") or entry.get("text") or "")))
    return sorted(out, key=lambda item: item[0])


def proof_text_of(row: Mapping[str, Any], proof_no: int = 1) -> str:
    """这条命题的某一份证明现在长什么样（找不到那一份 ⇒ 空串）。

    证明号走 :func:`_read_proof_no`：没给 ⇒ `#p1`；给了但认不出（`'abc'` / `0` …）⇒
    空串，不端出 `#p1` 的正文。改前是 `as_proof_no(proof_no) or 1`，于是
    `proof_text_of(row, 'abc')` 读到的就是 canonical 那一份 —— 一个坏号得到的答案与
    "我要 #p1"逐字相同，而调用方无从分辨。
    """
    want = _read_proof_no(proof_no)
    if want < 1:
        return ""
    for no, text in proof_list(row):
        if no == want:
            return text
    return ""


def proof_label(statement_id: str, proof_no: int = 1) -> str:
    """读数里的写法：`000004#p2`（不带 `#pN` 的老写法等价于 `#p1`）。

    证明号认不出时写法里点名（`000004#p？（证明号认不出：'abc'）`），不折成 `#p1`：
    这个串会进 `why` / `detail` / 逐条计数项（`proofs_unreviewed` 等），折平会让一条
    坏号以 canonical 的身份出现在读数里，读的人只会看到"#p1 怎么样"，看不到"号给错了"。
    """
    sid = str(statement_id or "")
    no = _read_proof_no(proof_no)
    if no < 1:
        return f"{sid}#p？（证明号认不出：{proof_no!r}）"
    return f"{sid}#p{no}"


def parse_verdict(text: str) -> dict[str, Any]:
    """把 V 的那一句输出拆成字段；它不判定任何东西（p247：判词只是陈述）。

    "没查成"与"对证明的结论"必须分开：前者是检查器的问题（重试 / 修提示词），
    后者是对证明的判断。把两者折平，会让一次模型抽风在台账上留下"V 看过这份证明"
    ——那是一条假证据。

    ## 这里只做结构解析，不做任何词面折档（业主 2026-11-06 第三次收紧）
    业主逐字：「V 的判词只是陈述」；「不做折档」；「不许按词面把判不了 / 看不出来 /
    拿不准 / 我无法判断折成任何一态」。所以本函数：
    ① 只拆 JSON、取字段、洗 `findings` / `citation_checks`，把 `verdict` 原样留住；
    ② 不检查 `verdict` 是不是两态之一，也不因它写了什么就决定 clean / fault ——
       每一转的轴由 V 的秘书读这段回复后语义判定（`secretary_judge.axis`，
       见 :func:`secretary_axis`）；
    ③ `defect_step` 允许缺：秘书判 fault 而 V 没给步号时，由秘书定出那一步
       （`Secretary.judge_v_reply` 的 `defect_step` 读数），再写回这一行。

    只有结构本身不合法（不是 JSON / 缺 `verdict` 字段 / `findings` 形状坏 /
    `citation_checks` 形状坏）才是"没查成"：抛 `VerificationError`，不落行。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start:end + 1] if (start >= 0 and end > start) else raw
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise VerificationError(f"V 的输出不是合法 JSON（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(got, Mapping):
        raise VerificationError("V 的输出必须是对象")
    said = str(got.get("verdict") or "").strip()
    if not said:
        raise VerificationError("V 的输出缺 `verdict` 字段 ⇒ 没有可判的陈述（没查成）")
    #: 折档时代留下的原话（老调用方仍会带过来）；p247 起 `verdict` 自己就是原话。
    verdict_raw = str(got.get("verdict_raw") or "").strip()

    findings: list[dict[str, Any]] = []
    for item in (got.get("findings") or []):
        if not isinstance(item, Mapping):
            raise VerificationError("findings 的每一项都必须是对象")
        level = str(item.get("level") or "").strip()
        if level not in FINDING_LEVELS:
            raise VerificationError(f"finding.level 必须是 {FINDING_LEVELS} 之一，收到 {level!r}")
        findings.append({"level": level, "step": item.get("step"),
                         "kind": str(item.get("kind") or "").strip(),
                         "detail": str(item.get("detail") or "").strip()})
    defect_step = got.get("defect_step")
    if defect_step is not None and not isinstance(defect_step, int):
        raise VerificationError("defect_step 必须是整数或 null")
    checks = _citation_checks_raw(got.get("citation_checks"))
    return {"verdict": said, "verdict_raw": verdict_raw,
            "defect_step": defect_step,
            "quote": str(got.get("quote") or "").strip(),
            "why": str(got.get("why") or "").strip(),
            "findings": findings,
            "citation_checks": checks,
            "unresolved_errors": sum(1 for f in findings if f["level"] == "error")}


def next_verification_id(root: str | Path, statement_id: str) -> str:
    """这个命题的验证台账里的下一个编号（`v-` + 当前宽度；宽度见 `schema.format_id`）。

    为什么从 `record_verification` 里抽出来一处具名函数（2026-10-14 改宽度那一笔）：
    它是发号点，而"每个发号点都发当前宽度"这条判据要能逐个真发一次 ——
    发号逻辑埋在写函数中间时，判据只能靠"读一遍代码"来假装检查过。
    """
    path = verification_ledger_path(root, statement_id)
    rows, _problems = JF.read_jsonl(path) if path.is_file() else ([], [])
    return f"v-{S.format_id(len(rows) + 1)}"


def record_verification(root: str | Path, *, statement_id: str, proof_text: str, verdict: Mapping[str, Any],
           verifier: str = "V", round_no: int | None = None,
           used_faces: Iterable[str] = (), submission_id: str = "",
           store: Any = None, proof_no: Any = None,
           object_sha256: Any = "", object_path: Any = "",
           manuscript: str = "",
           citation_gate: Mapping[str, Any] | None = None,
           secretary_judge: Mapping[str, Any] | None = None,
           sign_issuance: Mapping[str, Any] | None = None,
           washed_relay: Mapping[str, Any] | None = None,
           review_pass: int | None = None, review_call: str = "",
           flip: bool = True) -> dict[str, Any]:
    """把一次审校写进这个命题的台账（追加一行），返回那一行。

    编号 `v-NNNN` 由脚本按文件内顺序发（`draft/39` §3.21 五：与手稿编号、台账 id 同一套）。
    写之前把结论再规范化一遍（`parse_verdict` 的同一套校验）—— 调用方绕开解析直接
    构造一个 dict 时，坏结论会在写入期被挡住，而不是等到下游读它的时候。

    ## 这一行记什么（2026-10-22 补上右边的三格）
    `(stmt_id, proof_no, proof_sha256)`：`stmt_id` 是被审的那条命题（与 `statement_id`
    同值，两个键都写是为了不让读的人去猜哪个才是号）；`proof_no` 是被审的那一份证明
    （缺省 1 = canonical，见 :data:`PROOFS_KEY`）；`proof_sha256` 是这一份正文的指纹。
    三者合起来回答"复核过的是哪一份"。

    ## 证明号的两种来路必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给参数 ⇒ canonical（`#p1`）；给了但 :func:`as_proof_no` 认不出
    （`0` / `'abc'` / `2.0` / `'#p0'` …）⇒ :func:`proof_no_strict` 抛
    `VerificationError`，一个字节都不写。改前这里写 `as_proof_no(proof_no) or 1`：
    调用方说"签 #p2"、号给成了 0，台账上记成 `proof_no=1` 且 `verdict=成立` —— 签错
    一份证明，而盘上没有任何一格会报。

    ## `store` 给了就顺手把那条证明的第 3 位翻上去（业主 2026-10-22：同一次写）
    给了 `store` 且这一签签得住第 3 位（`signs_bit3`）⇒ 追加台账之后立刻调
    :func:`sign_statement`，在同一个 `statements` 事务里把那条证明的 `reviewed` 置真并把
    `reviewed_by` 换成这一签的凭据（含 `proof_no` 与 `proof_sha256`）。返回值里多一格
    `statement_writeback`（写没写成、为什么、回滚了没有、追加落在哪一态）—— 台账那一行
    是权威记录，位是它的缓存；写位失败不回滚签名（签名确实发生过），但必须如实报出来。
    不给 `store` ⇒ 只追加台账（老行为，夹具与自检走这条）。

    ## `manuscript`：这一签的载体（2026-11-04，业主裁定 甲）

    工作区相对路径。给了它就把这一格写进台账行（条件写入 ⇒ 老行逐字节不变）；
    :func:`sign_statement` 翻位时从行上读它、交给 :func:`_vsigns_write_after_flip`，
    于是 `vsigns.land` 把签块盖回送审方点名的那一份稿，而不是按约定路径扫盘猜一份。
    未在册那一支不走这里（它落 `verifications/pending/<sha>.jsonl`，手稿由
    `Secretary.land_unregistered_sign` 落）。

    ## 返回行上的三格：这一签到底有没有落地（2026-10-22 审计第 1 条）
    `checked` / `re_sign_required` / `reason`：撤回（`_rollback_append`）发生在
    :func:`sign_statement` 内部，调用方只看返回值。改前撤回之后返回行仍然是那一份
    `verdict=成立` 的记录 ⇒ V 的 `verify_proof` 照报"签住了第 3 位"，而台账是 0 字节。
    现在撤回或追加失败 ⇒ `checked=False`、`re_sign_required=True`、`reason` 逐字写明
    "台账那一行被撤回 / 没写成"。

    ## `citation_gate`：只在"这一档没查成"时写（2026-10-27）
    `problem` 非空（依赖台账读不出来）⇒ 行上多一格 `citation_gate`
    （`ok` / `problem` / `why` 三个读数）。为什么必须落盘：那时 `citation_checks` 常常
    是空数组，而空数组什么都不挡 —— 读侧的硬闸（:func:`signs_bit3`）要能分开
    "没查成"与"核过、没有引用"。查成了的行不写这一格（老行因此逐字节不变）。

    ## `secretary_judge` / `sign_issuance`：业主 2026-10-29 的 B 段与 A 段
    `secretary_judge` 是秘书对这段回复的两档语义判定（`clean` / `fault`），原样落到台账
    那一行的 `SECRETARY_JUDGE_KEY` 那一格 —— 连续计数读它（`fault` 清零、`clean` 计入；
    没查成的那一行两样都不做）。写侧只收这两格（`:data:`SECRETARY_JUDGE_AXES``）：词表外的
    轴（包括 2026-10-30 之前那个已取消的轴名）一律落成空轴，写不进来。
    不给就一个字节都不写（历史行与"没问过秘书"的那一批因此逐字节不变，
    读侧按"没判过"处理，也就是计入）。
    `sign_issuance` 是秘书"发不发这一签"的决定，原样交给 :func:`sign_statement` 当闸：
    `checked=False`（没缝 / 超时 / 台账读不成 / 没装配）⇒ 不翻位。
    两个参数都只影响"位翻不翻"，不改台账那一行的 `verdict`（那是 `parse_verdict` 的正本）。

    ## `flip=False`：这一签只落台账，翻位交给秘书（业主 2026-10-29 追加口径）
    原话：「V 不再自己发签。V 只产出审稿意见；由 V 的秘书判定并落盘」。所以 V 的写入口
    取 `flip=False`：台账那一行照落（正本），`statement_writeback.deferred_to="secretary"`，
    第 3 位由 `Secretary.decide_sign_issuance` 判完再调
    :func:`sign_statement`（`append_ledger=False`）翻。默认 `True` 是兼容门（夹具 / 直调本函数
    的那一批），生产 V 那两条路都传 `False`。

    ## `review_pass` / `review_call`：这一行是"哪一趟送审的第几轮"（2026-11-02 定稿）
    一次 `verify_proof` = V 连判 `SIGN_STREAK_NEED` 轮；`review_call` 是那一趟调用的 id
    （每趟一个，同一趟的三行逐字相同），`review_pass` 是这趟里的第几轮（1..need）。
    新签只认同一 `review_call` 内 `review_pass=1..need` 的那几行；跨调用绝不累计。
    `round` 保持原样（全局台账行号，老读数仍在用），不要拿它当趟内轮次。
    不给这两个参数（老调用点 / 夹具 / 直调本函数）⇒ `review_call=""`、
    `review_pass=None` ⇒ 读侧按历史形态计（`legacy_rows`），不参与新签判断。
    """
    # 证明号先判：坏号在写任何东西之前就拒（不落台账、不改位）。
    no = proof_no_strict(proof_no)
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        # 折过档的那一行要把模型原话带下去（审计用）：
                                        # 不带的话，`parse_verdict` 只能看到已折好的
                                        # 「成立」，盘上就再也查不到"它其实没判"。
                                        "verdict_raw": verdict.get("verdict_raw", ""),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        # 引用核实那一格也要过同一套校验：调用方绕开
                                        # `parse_verdict` 直接构造 dict 时，坏档位同样被挡在
                                        # 写入期（否则它会以"没有这一格"的样子落盘）。
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    path = verification_ledger_path(root, statement_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"这个命题的验证台账有读不出来的行：{problems[:3]}")
    vid = next_verification_id(root, statement_id)
    sha = proof_sha(proof_text)
    row = {
        "verification_id": vid,
        # 两个键同值：`statement_id` 是历史名（老行只有它），`stmt_id` 是"被审的命题"的
        # 那一个名字（业主 2026-10-22 点名要它）。只写一个会让按另一个键读的人读到 None，
        # 而"读到 None"与"这一签不属于任何命题"在读数上长得一样。
        "statement_id": str(statement_id), "stmt_id": str(statement_id),
        #: 被审的是哪一份证明（1 = canonical，#p1）。老行没有这一格 ⇒ 读侧按 1 算。
        "proof_no": no,
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        #: 引用核实（业主 2026-10-26）：`[{stmt_id, verdict, quote_verbatim, note}]`。
        #: 每一行都写这一个键（空列表 = "这一签核过、没有被引命题要核"，与历史行
        #: "没有这一格"在读侧分得开：老行没有它，新行有它、可以是空的）。
        "citation_checks": list(checked.get("citation_checks") or []),
        "proof_sha256": sha,
        "proof_chars": len(str(proof_text or "")),
        "round": int(round_no) if round_no is not None else len(rows) + 1,
        #: 这一行是"哪一趟送审的第几轮"（2026-11-02 定稿）：`review_call` 同一趟相同，
        #: `review_pass` 是 1..need。老行没有这两个键 ⇒ 读侧按历史形态（`legacy_rows`）计，
        #: 不参与新签判断。`round` 仍是全局台账行号，不是趟内轮次。
        "review_pass": int(review_pass) if review_pass is not None else None,
        "review_call": str(review_call or ""),
        "used_faces": [str(x) for x in used_faces],
        "submission_id": str(submission_id or ""),
        "at": _now_iso(),
    }
    if str(checked.get("verdict_raw") or "").strip():
        #: 折档那一行留住的模型原话（"它其实没判、只是没找到缺陷"这件事的唯一读数）。
        #: 只在真折过时写 ⇒ "模型自己就答了两态"的行与历史行逐字节不变。
        row["verdict_raw"] = str(checked["verdict_raw"]).strip()
    #: I10 硬禁令的机械命中（2026-10-27，业主裁定：先接成读数、不许直接挡签）。
    #: 命中就写一格 `hard_ban_markers`（"易证/显然/trivial/…"逐条），落盘可见；
    #: 只在命中时写（条件写入，老行与"没命中"的行逐字节不变）。它不参与任何判定：
    #: `signs_bit3` 不读它、`parse_verdict` 不因它改结论 —— 理由是"存量里有多少条
    #: 会被挡"还没量过，一次接上挡签会把一批历史证明打掉（业主 2026-10-27 的裁定）。
    _banned = banned_markers_in(proof_text)
    if _banned:
        row["hard_ban_markers"] = list(_banned)
    #: D-34：这一签审的对象（盘上那份报告 / 证明文件）的字节 sha256 与相对路径。
    #: 只在调用方真的知道时写（条件写入，老行因此逐字节不变），读侧按它认领
    #: "命题登记之前审的那一签"（`numericproof.latest_third_party_sign` 的第二路）。
    if str(object_sha256 or "").strip():
        row["object_sha256"] = str(object_sha256).strip().lower()
        row["object_path"] = str(object_path or "").strip().replace("\\", "/")
    #: 2026-11-04（业主裁定 甲）：这一签的载体（工作区相对路径）。在册命题也必须
    #: 有一份手稿：签块要盖回它，`sign_statement` 翻位时从这一格读到它、交给
    #: `vsigns.land`（`_vsign_payload` 不再靠"按约定路径扫盘"猜一份）。只在给了稿时
    #: 写（条件写入 ⇒ 老行逐字节不变；未在册那一支走的是 pending 台账，不经这里）。
    if str(manuscript or "").strip():
        row["manuscript"] = str(manuscript).strip().replace("\\", "/")
    #: 引用核实那一档的判据本行（`citation_gate` 的五格）。只在"这一档没查成"
    #: （`problem` 非空）时写：那时 `citation_checks` 往往是空数组（没有条目可核），
    #: 而空数组什么都不挡 —— 没有这一格，读侧（`signs_bit3`）就分不开"没查成"与
    #: "核过、没有引用"。查成了的行一个字都不多写（老行因此逐字节不变）。
    gate_problem = ""
    if isinstance(citation_gate, Mapping):
        gate_problem = str(citation_gate.get("problem") or "").strip()
    if gate_problem:
        row["citation_gate"] = {"ok": False, "problem": gate_problem,
                                "why": str(citation_gate.get("why") or "")}
    #: 秘书语义判定的两档轴（业主 2026-10-29 的 B 段；2026-10-30 第三次裁定收成两档）：
    #: `{axis, checked, decision, reason}`。
    #: 无条件写（业主裁定 2）：调用方给了判定就写它，没给就写"未判成"那一格
    #: （:data:`NO_SECRETARY_JUDGE`）。改前是条件写入 —— 不给就一个字节都不写，于是
    #: 那一行落进 `historical_axis` 的历史兼容支、按 `verdict` 字面拿到 clean。
    #: 为什么落在这一行而不是 `statements` 的新列：连续计数从台账派生（`draft/125` §二 A），
    #: 而"这一签当年算不算一票"是这一行的性质（`_hold_run_lengths` 读它）。
    _judge = secretary_judge_cell(secretary_judge)
    row[SECRETARY_JUDGE_KEY] = {
        "axis": _judge["axis"],
        "checked": bool(_judge["checked"]),
        "decision": str(_judge.get("decision") or ""),
        "reason": str(_judge.get("reason") or "")[:300],
    }
    #: 洗过的那一份转达文本（业主 2026-10-29 的 C 段）：`{text, findings, dropped, refused}`。
    #: 只在秘书真的洗出来时写（`washed=True`）—— 洗不出来的那一档不写这一格：
    #: 台账上"没有这一格"必须是"没洗过/洗不出来"，而不许写一份空文本冒充洗过。
    #: 它是 C 段交付面的唯一来源（`agent_loop.v_rejections_digest` 读这一格），
    #: 于是"递给 F 的那段话"与"台账上留痕的那段话"是同一份字节。
    if isinstance(washed_relay, Mapping) and washed_relay.get("washed"):
        row["washed_relay"] = {
            "text": str(washed_relay.get("text") or ""),
            "findings": [dict(f) for f in (washed_relay.get("findings") or [])
                         if isinstance(f, Mapping)],
            "dropped": [dict(f) for f in (washed_relay.get("dropped") or [])
                        if isinstance(f, Mapping)],
        }
    if store is None:
        _append_verification(path, row)
        # 缺陷 A（2026-11-05）：重判之后把签块那两格刷到台账最新那一行。
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return row
    if flip is False:
        # ---- 业主 2026-10-29 追加口径：V 不再自己发签 ----
        #
        # V 只产审稿意见；"翻不翻第 3 位"由 V 的秘书判（`Secretary.decide_sign_issuance`），
        # 落地那一步也由它调 `sign_statement(append_ledger=False)`。所以这一支只落台账
        # （正本先落，签这个事实不依赖任何人的决定），把翻位留给秘书：
        # `statement_writeback.deferred_to == "secretary"` 是"这一支没翻位"的可读读数，
        # 它不是失败（`checked` 仍为真：台账那一行确实落了）。
        append_state = "not_attempted"
        append_problem = ""
        try:
            _append_verification(path, row)
            append_state = "appended"
        except OSError as exc:
            append_state = "failed"
            append_problem = f"{type(exc).__name__}: {exc}"
        writeback: dict[str, Any] = {
            "written": False, "rolled_back": False, "append_state": append_state,
            "re_sign_required": append_state != "appended", "grade": "",
            "statement_id": str(statement_id), "proof_no": no,
            "proof_sha256": sha, "kind_upgrade": {}, "upgrade_note": "",
            "grade_recomputed": {},
            "streak": 0, "need": SIGN_STREAK_NEED, "streak_ok": False,
            "deferred_to": "secretary",
            "reason": (f"发签这一步不在这一支：在册档由 V 的秘书判定并发（业主 2026-10-29），"
                       f"未在册档由 V 自己颁发签信封。台账那一行已落（{vid}）"
                       + (f"；但签名那一行没写成（{append_problem}）" if append_problem else "")),
        }
        row["statement_writeback"] = writeback
        _mark_landed(row, writeback)
        # 缺陷 A（2026-11-05）：台账那一行落下之后刷签块（`vsigns.refresh_manuscript_sign`）。
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return row
    if not row_signable(row):
        # 签不住的结论也要落台账（它是"看过、结论是没过"的证据），但它不翻任何位。
        # 追加由本函数做（`sign_statement` 在这一支只回一句理由、不碰台账）⇒ 由本函数
        # 把追加落在哪一态写回 `statement_writeback`（2026-10-22 审计第 5 条：那一格
        # 此前只有"-written 前的 -1"一个哨兵兼任两义，"签名确实发生过"可能是在说谎）。
        #
        # 判据是行局部那一半（`row_signable`），不是 `signs_bit3`：后者还要连续次数，
        # 而"连续次数不够"与"这一签签不住"是两件事 —— 前者仍要走 `sign_statement`
        # （它负责把台账追加在事务里、并在次数够了的时候翻位），后者连事务都不该开。
        # 改前这里写的是 `signs_bit3(row)`（那时它只有行局部那一半）；业主 2026-10-29
        # 给 `signs_bit3` 加了连续闸之后，若不同步改这一行，"成立但还差次数"那一支会
        # 被当成本支处理 ⇒ 台账会被追加两次（一次在这里、一次在 `sign_statement` 里）。
        append_state = "not_attempted"
        append_problem = ""
        try:
            _append_verification(path, row)
            append_state = "appended"
        except OSError as exc:
            append_state = "failed"
            append_problem = f"{type(exc).__name__}: {exc}"
        writeback = sign_statement(store, row=row, proof_text=proof_text,
                                   path=path, proof_no=no)
        writeback["append_state"] = append_state
        if append_state == "failed":
            writeback.update(
                written=False, re_sign_required=True,
                reason=(f"签名那一行没写成（{append_problem}）⇒ 这一签没有落地（必须重签）；"
                        + str(writeback.get("reason") or "")))
        row["statement_writeback"] = writeback
        _mark_landed(row, writeback)
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return row
    writeback = sign_statement(store, row=row, proof_text=proof_text,
                               path=path, proof_no=no, sign_issuance=sign_issuance)
    row["statement_writeback"] = writeback
    _mark_landed(row, writeback)
    row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                   manuscript=manuscript)
    return row


def _retrack_sign_block(root: str | Path, *, row: Mapping[str, Any],
                        manuscript: str = "") -> dict[str, Any]:
    """台账那一行落下之后：把这一份正文的签块刷到台账最新那一行（缺陷 A；永不抛）。

    为什么挂在这里（2026-11-05，真机 87 的读数）：签块上 `台账=` / `时间=` 两格此前
    只有 :func:`sign_statement` -> `vsigns.land` 一个写者，而它只在发签那一刻跑。
    同一份正文之后的每一次重判（同 sha 的新台账行）只追加台账、没人碰块 ⇒ 块永远停在
    第一次发签那一行（87：块说 v-000008，账上最新 v-000011；而且 v-000009 判了「有毛病」
    之后块还挂着旧签）。

    判据一个字都不在这里（唯一实现是 :func:`vsigns.refresh_manuscript_sign`）：这一格只
    负责"行落了就叫它一声"，并把它那一笔的三态读数带进返回值 —— 刷块失败不许带走这一签
    （台账那一行已经落了，它是正本）。读数的键是 `sign_block_refresh`（不落盘：
    它在追加之后才写进返回行，与 `statement_writeback` 同一条纪律）。
    """
    from . import vsigns as _VS

    try:
        return dict(_VS.refresh_manuscript_sign(
            root, artifact_sha=str(row.get("proof_sha256") or ""),
            statement_id=str(row.get("stmt_id") or row.get("statement_id") or ""),
            proof_no=row.get("proof_no"), manuscript=str(manuscript or "")))
    except Exception as exc:  # noqa: BLE001 —— 刷块失败不许带走这一签（台账已落）
        return {"checked": False, "state": "error",
                "why": (f"签块刷新没跑成（{type(exc).__name__}: {exc}）"
                        "⇒ 块可能停在旧那一签上（这一格没查成）")}


def _mark_landed(row: dict[str, Any], writeback: Mapping[str, Any]) -> None:
    """把"这一签有没有真的落地"写进返回行（`checked` / `re_sign_required` / `reason`）。

    判据只认 `writeback` 自己报的两格：`append_state == "appended"`（台账那一行真追加了）
    且没有 `rolled_back`（它没被撤回）。只看 `verdict` 会把"被撤回的那一签"读成"签住了"，
    而台账盘上是 0 字节 —— 这正是本批审计第 1 条的读数（`checked=True verdict='成立'
    signed_bit3=True` 而台账字节数 0）。
    """
    landed = (str(writeback.get("append_state") or "") == "appended"
              and not writeback.get("rolled_back"))
    row["checked"] = bool(landed)
    row["re_sign_required"] = bool(writeback.get("re_sign_required"))
    if landed:
        row["reason"] = ""
        return
    head = "台账那一行被撤回" if writeback.get("rolled_back") else "台账那一行没写成"
    row["reason"] = (f"{head}：这一签没有落地（必须重签）；位没有改成 reviewed="
                     f"{bool(writeback.get('written'))}；写回原话："
                     f"{str(writeback.get('reason') or '')}")


def list_verifications(root: str | Path, *, statement_id: str = "",
             limit: int | None = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """列验证台账（可按命题过滤）；返回 `(行, 坏行说明)` —— 坏行照实报出，不静默跳过。

    ## `limit=None` 与 `limit=0` 必须分开（V1，`draft/44` J-14）

    实现此前写的是 `out[-limit:]`，而 `-0 == 0` ⇒ `limit=0` 恰好等于全量。
    那是一个靠运算符巧合成立的语义：调用方写 `limit=0`（"不要行"）会拿到全部行，
    而没有任何报错。三态纪律在分页上同样成立 —— "要零条"与"要全部"是两件事。

      - `limit=None` ⇒ 全量（"我要看完整本台账"）；
      - `limit=0`   ⇒ 零条（空表）；
      - `limit=n>0` ⇒ 末尾 n 条（按 (命题号, 编号) 排序后取尾部）。
    """
    base = verifications_dir(root)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    files = ([verification_ledger_path(root, statement_id)] if statement_id
             else sorted(base.glob("*.jsonl")) if base.is_dir() else [])
    for p in files:
        rows, bad = JF.read_jsonl(p)
        problems.extend(f"{p.name}: {b}" for b in bad)
        out.extend(rows)
    out.sort(key=lambda r: (str(r.get("statement_id") or ""), str(r.get("verification_id") or "")))
    if limit is None:
        return out, problems
    return out[-max(0, int(limit)):] if int(limit) > 0 else [], problems


def ledger_reading(root: str | Path, *, store: Any = None) -> dict[str, Any]:
    """验证台账的"真身"读数：文件是正本，同名的数据表从来不存在（一处真身）。

    ## 为什么需要这一格（真机 sylow3，2026-10-24 的缺口二）
    V 的产物是工作区里 `verifications/<命题号>.jsonl` 的那些行（`schema.TABLES` 里
    没有 `verifications` 这张表：`store.rows("verifications")` 直接抛「未知表」）。
    于是一次运行结束时盘上有 `verifications/000000.jsonl` ... `000006.jsonl` 七份、
    十四行签，而按"数据表"那一面看（`data/` 目录里没有 `verifications.json`）是 0 行。
    两处口径从来没有被任何一格对起来过：文件面是 7 份、表面是 0 行，收工门、对应表、
    证据面各读各的一边 ⇒ 读的人只会看到"没有签"。

    这一格把这件事写成一次可机器读的读数，三态（不猜）：
    - `source`：这一档的正本永远是 `verifications/*.jsonl`（文件）。同名数据表
      `is_store_table=False`，`rows=None`（不是 0 —— "这张表不存在"与"表是空的"是两件事）。
    - `mirror`：如果盘上真有 `data/verifications.json`（派生副本 / 别人拷进去的），
      就逐条按 `verification_id` 对账；`agrees` 只有 `True` / `False` / `None` 三档，
      `None` = 没有副本可对（"没查"不是"对上了"）。
    - `problems` 非空 ⇒ 两面分家，`why` 说清差在哪几条。

    返回（键集合固定，读的人不必猜）：
    `checked` / `source` / `files` / `file_names` / `rows` / `signed` /
    `signed_statements` / `table` / `mirror` / `agrees` / `problems` / `why` / `next_step`。
    """
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "checked": False,
        "source": f"{VERIFICATIONS_DIR}/*.jsonl",
        "files": 0,
        "file_names": [],
        "rows": 0,
        "signed": 0,
        "signed_statements": [],
        "table": {"name": VERIFICATIONS_DIR, "is_store_table": False, "rows": None,
                  "why": ""},
        "mirror": {"path": f"data/{VERIFICATIONS_DIR}.json", "present": False,
                   "rows": None, "agrees": None},
        "agrees": None,
        "problems": [],
        "why": "",
        "next_step": "",
    }
    # ---- 文件面（正本）
    base = verifications_dir(root_p)
    if not base.is_dir():
        out["why"] = (f"`{VERIFICATIONS_DIR}/` 不在盘上 ⇒ 这个工作区还没有一次签过"
                      "（这是「零签」，不是「读不到」：目录在不在与行读不读得出来是两件事）")
        out["next_step"] = "派 V 走 `verify.verify_proof`（产物就是那个目录下的一行）"
        _ledger_table_state(out, store)
        return out
    rows, bad = list_verifications(root_p, limit=None)
    out["checked"] = True
    out["file_names"] = sorted(p.name for p in base.glob("*.jsonl"))
    out["files"] = len(out["file_names"])
    out["rows"] = len(rows)
    signed = signed_rows(rows)
    out["signed"] = len(signed)
    out["signed_statements"] = sorted({_statement_id_of(r) for r in signed if _statement_id_of(r)})
    out["problems"] = list(bad)
    # ---- 表面：同名 store 表存不存在（"不存在"不许折成"0 行"）
    _ledger_table_state(out, store)
    # ---- 派生副本（如果有）
    mirror = dict(out["mirror"])
    mirror["rows"], mirror["present"] = _ledger_mirror_rows(root_p)
    if mirror["present"] and isinstance(mirror["rows"], list):
        want = {str(r.get("verification_id") or "") for r in rows}
        have = {str(r.get("verification_id") or "") for r in mirror["rows"]}
        mirror["count"] = len(mirror["rows"])
        if want == have:
            mirror["agrees"] = True
        else:
            mirror["agrees"] = False
            mirror["missing_ids"] = sorted(want - have)
            mirror["extra_ids"] = sorted(have - want)
            out["problems"].append(
                f"`data/{VERIFICATIONS_DIR}.json` 与文件台账分家：文件 {len(want)} 条、"
                f"表 {len(have)} 条（文件有表没有的是 {mirror['missing_ids'][:6]}、"
                f"表有文件没有的是 {mirror['extra_ids'][:6]}）")
        out["agrees"] = mirror["agrees"]
    elif mirror["present"]:
        mirror["agrees"] = None
        out["problems"].append(
            f"`data/{VERIFICATIONS_DIR}.json` 在盘上但读不出来 ⇒ 这一面没查成"
            f"（{mirror.get('why') or '格式不认'}）")
    out["mirror"] = mirror
    if out["files"] and out["signed"] == 0:
        out["problems"].append(
            f"`{VERIFICATIONS_DIR}/` 有 {out['files']} 份台账、{out['rows']} 行，"
            "而没有一行签「成立」⇒ 审过但一次都没签住（这是读数，不是读不到）")
    if not out["problems"]:
        out["why"] = (f"文件台账 {out['files']} 份、{out['rows']} 行，"
                      f"其中签「成立」且无未解决 error 的 {out['signed']} 行"
                      f"（覆盖 {len(out['signed_statements'])} 条命题）")
        if not out["table"]["is_store_table"]:
            # 表面那一格不是「0 行」，而是「这张表不存在」：读的人要能从这一格直接知道
            # 该去读文件（改前这一步没有任何落点，于是「表 0 行」被当成了「没有签」）。
            out["why"] += "；" + str(out["table"]["why"])
    out["next_step"] = (
        "读验证台账只走这一个口（`verifications.list_verifications` / 本函数）："
        f"正本是 `{VERIFICATIONS_DIR}/<命题号>.jsonl`；要找「表」的那个人应当读"
        "`rows` / `signed` 这两格，而不是去找一张不存在的 `verifications` 表")
    return out


def _statement_id_of(row: Mapping[str, Any]) -> str:
    """一行签名属于哪条命题（正名 `stmt_id`，老行读 `statement_id`）。"""
    return str(row.get("stmt_id") or row.get("statement_id") or "")


def _ledger_table_state(out: dict[str, Any], store: Any) -> None:
    """同名数据表那一面的三态：它不是 store 表（`rows=None`），不是「0 行」。"""
    table = dict(out.get("table") or {})
    in_schema = False
    try:  # 只在拿得到 schema 时判；拿不到就如实说没查成
        in_schema = VERIFICATIONS_DIR in S.TABLES
    except Exception:  # noqa: BLE001 - 读不到 schema 时按"不在表里"继续，理由写在 why 里
        in_schema = False
    table["is_store_table"] = bool(in_schema)
    if in_schema:
        table["why"] = f"`{VERIFICATIONS_DIR}` 是 store 表 ⇒ 读表即可（与文件对账）"
        if store is not None:
            try:
                table["rows"] = len(list(store.rows(VERIFICATIONS_DIR)))
            except Exception as exc:  # noqa: BLE001 - 读不到表就是"没查成"
                table["why"] += f"；但这一次没读出来（{type(exc).__name__}: {exc}）"
        out["table"] = table
        return
    table["rows"] = None
    table["why"] = (
        f"`{VERIFICATIONS_DIR}` 不是一张 store 表（`schema.TABLES` 里没有它）⇒ "
        f"`store.rows(\"{VERIFICATIONS_DIR}\")` 只会抛「未知表」，"
        f"按表读的那一面永远读到 0 行；正本是工作区里的 `{VERIFICATIONS_DIR}/"
        "<命题号>.jsonl`。这一格给的就是「表不存在」（`rows=None`），"
        "而不是「表是空的」（那会是 0）")
    out["table"] = table


def _ledger_mirror_rows(root_p: Path) -> tuple[Any, bool]:
    """盘上有没有 `data/verifications.json`（派生副本）；有就把它读成行列表。"""
    path = root_p / "data" / f"{VERIFICATIONS_DIR}.json"
    if not path.is_file():
        return None, False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 读不出来如实交给调用方
        return {"why": f"{type(exc).__name__}: {exc}"}, True
    rows = doc.get("rows") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        return {"why": "文件里没有 rows 数组"}, True
    return [dict(r) for r in rows if isinstance(r, Mapping)], True


def signing_gate_problem(row: Mapping[str, Any]) -> str:
    """台账那一行记下的"引用核实没查成"那一档（空串 = 没记，或记的是查成了）。

    为什么单独一格：`problem`（依赖台账读不出来）不是 `citation_checks` 里的任何一档
    —— 它是"这一档没查成"，而空数组只说明"没有条目可核"。两者折平之后，"没查成"就
    长成了"没有引用"（那一版 `signs_bit3` 只读 `citation_checks`，于是这种行照样签）。
    历史行没有 `citation_gate` 这一格 ⇒ 空串，读数逐字不变。
    """
    gate = row.get("citation_gate")
    if not isinstance(gate, Mapping):
        return ""
    return str(gate.get("problem") or "").strip()


def read_verdict(row: Mapping[str, Any]) -> str:
    """这一行上 V 写下的结论陈述（原样；p247 起不做任何折档）。

    ## 它只做一件事：取字段
    业主 2026-11-06 第三次收紧逐字：「V 的判词只是陈述」「不做折档」。所以这里
    原样返回台账上的 `verdict` 字符串（包括历史值 `看不出来`），不把它折成
    `成立` 或 `有毛病`、也不据此产生轴。轴只有一处：:func:`secretary_axis`。

    ## 历史行（不改写、也不折）
    老行上那四个字仍是原始读数（`list_verifications` 原样返回）。`read_verdict`
    把它们读出来是给人复核"它当年写的到底是什么"的；它们不参与计票、不参与签发
    （见 :func:`_hold_run_lengths` 与 :func:`row_signable`）。

    ## 为什么还留这个函数
    读数的展示面（`review_standing` / `bit3_payload` / 回执）要能逐字回放 V 写的那句话。
    判断面不再经过它 —— 判断面问 :func:`secretary_axis`。
    """
    return str(row.get("verdict") or "")


def row_signable(row: Mapping[str, Any]) -> bool:
    """行局部那一半：这一行自己够不够格签五元位第 3 位。

    ## 轴只认秘书给的（业主 2026-11-06 第三次收紧 · p247）
    第一句是 `secretary_axis(row) == "clean"`。这是轴（clean / fault）的唯一真源：
    由 V 的秘书读 V 的回复后语义判定并写清依据（`secretary_judge.axis`）。
    本函数不读 `verdict` 的字面 —— 按业主原话，「V 的判词只是陈述」，
    「不许按字面直接定轴」。没有轴的行（老行 / 没判成 / 秘书不在场）一律 False：
    fail-closed，不是"没问题"。

    再加三条机械闸（它们不是轴，也不改变轴）：
    - 未解决的 error：引用核实 / 依赖面审计落进来的 error；
    - `citation_gate.problem`（`:func:`signing_gate_problem`）：依赖台账读不出来，
      "没查成"与"核过、没有引用"必须分开；
    - 引用核实里挡签的档（`stronger` / `unrelated` / `inadmissible` / `unknown`）。

    ## 为什么它与 :func:`signs_bit3` 是两个名字而不是一个（业主 2026-10-29）
    「连续 3 次」这一条读不到：它要数台账尾部那几行（:func:`consecutive_holds`）。
    行局部谓词自己读台账就会造出"位上说签了、台账只签一次"的第二份账（`draft/124` §一②），
    所以两条轴在这里分开：本函数 = 这一行自己的资格；:func:`signs_bit3` =
    本函数 且 调用方递进来的连续读数。函数名刻意不同，免得读的人以为
    `signs_bit3(row)` 少了什么参数只是"默认值不同"。
    """
    if ledger_axis(row) != "clean":
        return False
    if int(row.get("unresolved_errors") or 0) != 0:
        return False
    if signing_gate_problem(row):
        return False
    return not citation_blocks(row)


def historical_axis(row: Mapping[str, Any]) -> str:
    """已废：历史兼容轴 —— 2026-11-06 裁定 2 起不再给轴，一律空串。

    ## 改前它做什么（这条缺陷的后半截）
    p247 到裁定 2 之间，这一格对"没有 `secretary_judge` 这一格"的行按 `verdict` 的
    字面给轴：`成立` ⇒ `clean`、`有毛病` ⇒ `fault`、其余（含历史值 `看不出来`）⇒ 空。
    本意是"让老台账读得出"，但它的判据是 `verdict` 这个字符串，而写口当时是
    条件写入（不给判定就根本不落这一格）—— 于是它同时成了第二条写路的第二半：

        `record_verification(verdict={"verdict": "成立"})`（一次秘书都不问）
        ⇒ 这一格不落盘 ⇒ 本函数按字面给 clean
        ⇒ `row_signable` = True、`_hold_run_lengths` 计一票
        ⇒ 三次这样的写 ⇒ `consecutive_holds.streak = 3` ⇒ 第 3 位被签住

    那就是业主说的"绕过秘书登记才是缺陷"，而且绕过去之后能签（现场读数见
    `temp/probe-secretary-census/probe_bypass_sign.py` 与
    `tests/test_v_axis_comes_from_the_secretary.py::test_l_*`）。

    ## 现在
    与 :func:`secretary_axis` 合流：没有那一格 ⇒ 空轴 = unjudged
    （由 :func:`ledger_axis` 的调用方按"不计票、不清零、不签发"处置）。函数名与这一格
    保留下来，是因为它是"这条按字面定轴的规则曾经存在"的唯一落点，也是这条裁定
    在代码里的墓碑：下一个想在读侧给老行补一条字面轴的人，改的就是这里。
    要看"这一行为什么没有轴"，读 :func:`axis_reading`。
    """
    return ""


def axis_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一行的轴从哪来（纯读数，不参与判定；裁定 2 要的那句"这行没有秘书判定"）。

    `source` 三档：
    - `secretary`：这一行有 `secretary_judge` 这一格、且轴是词表里的两档之一；
    - `secretary_unjudged`：有那一格、但 `checked` 为假 / 轴读不出来
      （"问过、没判成"，框架失败，等判定接上之后重签）；
    - `none`：连那一格都没有 —— 老台账行，或者一次没有经过秘书的写入。
      这一档从前会被按 `verdict` 字面读成 clean，现在不算轴。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    axis = secretary_axis(row)
    if axis:
        return {"axis": axis, "source": "secretary", "why": f"轴由秘书给：{axis}"}
    if isinstance(got, Mapping):
        return {"axis": "", "source": "secretary_unjudged",
                "why": ("这一行的秘书判定没查成（checked=False 或轴读不出来）"
                        "⇒ 不计票、不清零、不签发")}
    return {"axis": "", "source": "none",
            "why": ("这一行没有 `secretary_judge` 这一格 ⇒ 没有秘书判定"
                    "（V 的判词只是陈述，不是轴）⇒ 不计票、不清零、不签发")}


def ledger_axis(row: Mapping[str, Any]) -> str:
    """这一行的轴：只认 `secretary_judge.axis`（裁定 2 起不再有字面回退）。

    没有这一格 / 轴读不出来 ⇒ 空串 = unjudged。见 :func:`historical_axis`（墓碑）与
    :func:`axis_reading`（读数）。
    """
    return secretary_axis(row)


def secretary_axis(row: Mapping[str, Any]) -> str:
    """这一行台账上的秘书判定轴（写侧 `SECRETARY_JUDGE_AXES`；没有这一格 ⇒ 空串）。

    只有写侧那两格（`clean` / `fault`）；其余一律空串。
    空串 = "这一行没有轴"（老行没有这一格 / 这一趟没查成 / 秘书不在场 / 老行上那个
    已取消的轴名）。读侧怎么处置它，由调用方那一条纪律决定：:func:`_hold_run_lengths`
    对"有这一格、但轴读不出来"的行是既不算票、也不清零（与"没有这一格"刻意分开 ——
    读不出轴 ≠ 判过 clean，`tests/test_v_sign_gate_streak.py` 的 z2(c) 钉着这条 fail-closed）。

    2026-11-02（追加裁定：那一档连历史兼容读也不留）：改前这里还认一个历史轴名
    （`SECRETARY_JUDGE_HISTORICAL_AXES = ("unsure",)`，2026-10-30 之前写下的行里有它）。
    那个常量与这一支一起删了 —— 老行上的那个值现在读出来是空轴，"那一档"在读侧不再有
    任何自己的位置：`_hold_run_lengths` 里也没有它的分支了（改前那条分支的结果与
    "轴读不出来"那条通用纪律逐字相同，删掉它等于删掉"承认那一档存在"的最后一行字）。

    取了词表外的值也归空串。那条保护落在写侧：`Secretary.judge` 对词表外的答法判
    `checked=False`（没查成），于是读侧看到的是"问过、没判成"那一档（既不算票也不清零），
    而不是"轴读不出来但算过了"。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return ""
    axis = str(got.get("axis") or "").strip()
    return axis if axis in SECRETARY_JUDGE_AXES else ""


def secretary_judged(row: Mapping[str, Any]) -> bool:
    """这一行的秘书判定是"判过了"还是"没判成"（`checked` 那一格；没有 ⇒ False）。

    为什么要单独一个读口（业主 2026-10-30）：没有这一格的老行与"判了、但没查成"的行
    长得不一样。p247 起两者的处置相同（都没有轴 ⇒ 不算票、也不清零），但读数仍必须分得开：
    "从没问过秘书"（老行）与"问过、没判成"（框架失败）是两件事。
    读侧只认这一格，不许自己再写一遍 `secretary_judge.checked` 的取值路径。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return False
    return bool(got.get("checked"))


def secretary_unjudged(row: Mapping[str, Any]) -> bool:
    """这一行写着"问过秘书、没判成"（有那一格、但 `checked` 为假）。

    与"没有那一格"（从没问过 / 老行）刻意分开：前者是这一趟的框架失败（业主
    2026-10-30 第三次裁定：没查成不是一种判定），它在连续计数里既不算票、也不清零；
    后者按"没判过"计入连续（:func:`_hold_run_lengths`）。两者必须分得开 —— 否则
    "这一趟没查成"会被读成"这一份还没判过"，而处置完全不同（前者等判定接上之后重签，
    后者就是正常的第几票）。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return False
    return not bool(got.get("checked"))


def _streak_number(streak: Any) -> int | None:
    """把"连续读数"归一成一个整数；`None` = 这一档没有可用的读数。

    接受三种来路（都是同一件事的不同载体，不另立判据）：
    - `consecutive_holds` 的返回值（dict）：`checked` 为假 ⇒ `None`（没查成不是 0 次）；
    - 一个整数（已经数过的连续次数）；
    - `None` / 其它任何东西 ⇒ `None`（没有读数，与"读到 0"不同）。
    """
    if isinstance(streak, Mapping):
        if not bool(streak.get("checked")):
            return None
        try:
            return int(streak.get("streak") or 0)
        except (TypeError, ValueError):
            return None
    if isinstance(streak, bool) or streak is None:
        return None
    try:
        return int(streak)
    except (TypeError, ValueError):
        return None


def streak_ok(streak: Any, need: int | None = None) -> bool:
    """连续读数够不够发签（没读数 ⇒ 不够：fail-closed）。

    为什么 `None` 不许当"够"：`signs_bit3` 是本仓唯一的签字硬闸，而"调用方忘了传连续
    读数"与"连续次数够了"必须分得开。默认放行的话，任何一处漏传都会静默退回
    "一次成立就发签"—— 那正是这一条口径要取消的东西，而盘上不会有任何读数报它。

    `need=None` = 门槛现读 `SIGN_STREAK_NEED`（2026-10-30 改）。改前这里是
    `need: int = SIGN_STREAK_NEED` —— 默认参数在导入期求值，等于把门槛的第二个副本
    钉进了签字闸：门槛一旦不是 3（`agent_v.core.review_pass_bound` 的负控就把门槛
    临时打成 1 与 5），秘书那一端按新值判"够"，这一端按旧值判"没到门槛" —— 同一个门槛
    给出两个数，而"发签没落成"这句理由会把它说成"还差次数"。默认参数不是配置，它是一次
    快照；门槛要现读。
    """
    got = _streak_number(streak)
    if got is None:
        return False
    limit = int(SIGN_STREAK_NEED) if need is None else int(need)
    return got >= limit


def signs_bit3(row: Mapping[str, Any], *, streak: Any = None) -> bool:
    """这一行能不能签五元位第 3 位：行局部资格 且 连续次数够。

    `streak`（业主 2026-10-29）是台账派生的连续成立次数，三种载体见
    :func:`_streak_number`；不给就不签（fail-closed，理由见 :func:`streak_ok`）。

    为什么连续次数是入参而不是在这里现读台账：本函数是行局部谓词（被一批
    "手里只有一行"的地方调用，`numericproof` / `_gap_from_pending` / 各处读数），
    拿不到可靠的行序。硬塞一次读盘会让"这一行"与"它的位置"两件事在每个调用点各算一遍
    ——`draft/124` §一② 点名的那种第二份账就是这么长出来的。

    历史行（没有 `secretary_judge` 这一格）不受影响：连续计数把它们当"没判过"（计入），
    与这条口径上线之前的读数逐字相同。
    """
    if not row_signable(row):
        return False
    return streak_ok(streak)


def bit3_payload(row: Mapping[str, Any], *, streak: Any = None) -> dict[str, Any]:
    """把一行审校翻成五元位第 3 位那份读数（交给 `evidencebits.bits_of`）。

    签不了（`有毛病` / 有未解决 error / 引用核实挡签 / 连续次数不够）⇒ 返回 `{}`
    （第 3 位保持空）—— 这不是"忘了写"，是"没签"。`streak` 与 :func:`signs_bit3` 同义。
    老行上的 `看不出来`（:data:`LEGACY_VERDICTS`）不在这张"签不了"的清单里：它按
    :func:`read_verdict` 读成 `成立` ⇒ 只要连续次数够，它签得住（2026-11-02 追加裁定）。

    凭据里带 `proof_no` 与 `proof_sha256`（2026-10-22）：读侧要拿它们回答"位上说审过的
    那一份，还是不是现在这一份"（`evidencebits.bits_from_row` 与收工门的 R10 都读这两格）。
    """
    if not signs_bit3(row, streak=streak):
        return {}
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    return {
        "reviewed": True,
        "reviewed_by": {
            "verifier": str(row.get("verifier") or "V"),
            "verification_id": str(row.get("verification_id") or ""),
            "round": row.get("round"),
            #: 凭据上记的是 V 写下的那句陈述（:func:`read_verdict` 原样取字段，不折档）；
            #: 轴的读数在下一格（p247：`reviewed_by.axis` 才是判定凭据，`verdict` 只是原话）。
            "verdict": read_verdict(row),
            "axis": ledger_axis(row),
            "evidence": f"verifications/{sid}.jsonl#"
                        f"{row.get('verification_id')}",
            "findings": list(row.get("findings") or []),
            "proof_no": proof_no_of(row),
            "proof_sha256": str(row.get("proof_sha256") or ""),
        },
    }


def _already_signed_locator(reviewed_by: Mapping[str, Any],
                            per: Mapping[int, bool],
                            sha_by: Mapping[int, str], no: int) -> str:
    """「这一位签过」能不能定位到一次具体签名（空串 = 判不了）。

    ## 为什么裸布尔不够（业主 2026-11-04 裁定 · 乙-11）

    `bits.reviewed=True` 是写侧留下的一个布尔。有台账的行由台账现算
    （`review_standing`）；而 `bit3_already_signed` 是 V 的短接判据 —— 它若拿一个
    没有任何定位凭据的裸布尔说"已经签过"，V 就不会再读一眼、直接返回
    `signed_bit3=True`。可定位 = `reviewed_by` 里有 `verification_id` 或
    `proof_sha256`，或逐条表（`reviewed_by_proof` / `reviewed_sha_by_proof`）里
    至少一条「为真且有 sha」。四者都没有 ⇒ 判不了、按没签过处理（照常送审）。
    这与 `closing._review_locator` 是同一把尺（那边早就是这么判的），只是这一格
    不 import closing（会成环）。
    """
    by = dict(reviewed_by or {})
    vid = str(by.get("verification_id") or "").strip()
    if vid:
        return f"verification_id={vid}"
    sha = str(by.get("proof_sha256") or "").strip()
    if sha:
        return f"proof_sha256={sha[:12]}"
    own = str((sha_by or {}).get(no) or "").strip()
    if own:
        return f"proof_sha256={own[:12]}"
    for n, ok in (per or {}).items():
        if not ok:
            continue
        got = str((sha_by or {}).get(n) or "").strip()
        if got:
            return f"proof_sha256={got[:12]}"
    return ""


def bit3_already_signed(row: Mapping[str, Any], *, proof_no: Any = DEFAULT_PROOF_NO,
                        proof_text: str = "") -> dict[str, Any]:
    """命题行上这一份证明的第 3 位是不是已经为真（纯读；2026-10-31）。

    ## 为什么要有这一格
    一条已经签过的命题不该再被送审。真机冒烟（工作区 `projects/abelian-smoke-20261030c`）
    的 `verifications/000001.jsonl` 有 12 行、全是同一份正文（同一个 `proof_sha256`）：
    v6–v8 三转 clean 之后第 3 位已经翻真，v9–v12 却还在被送审，其中 v10 被判成 fault
    —— 读侧（`agent_loop.v_rejections_digest` → `deliver_v_verdicts`）把那一转当成
    「有毛病要打回」，F 于是被叫去改一份已经签过的证明。判据落在写侧这一格：
    位已经为真 ⇒ 这一趟没有可做的审校（调用方据此短接，见 `AgentV.verify_proof`）。

    ## 它读什么、不读什么
    只读命题行（`statements` 那一行）上的五元位，并且现算
    （`evidencebits.bits_from_row`）：于是「签的是旧版正文」那一档在这里已经读成没签
    —— 改稿之后仍然会重审，那正是要的。不读台账、不读模型、不写任何东西：
    台账回答"这一签是怎么来的"，而"这一位现在是不是真的"只有命题行能回答。

    ## 逐条证明（`#p2` 不许借 `#p1` 的光）
    有逐条表（`bits.evidence.reviewed_by_proof`）时按证明号读：`#p2` 那条是假 ⇒ 不短接
    （哪怕汇总位 `bits.reviewed` 因为 `#p1` 为真）。没有逐条表（历史行 / 只翻汇总位的
    写者）⇒ 汇总位与 `reviewed_by` 是唯一凭据，此时按 `reviewed_by.proof_no` 判
    「签的是哪一份」；那一格也没有 ⇒ 按 canonical 读（老数据不带证明号）。

    ## 无可定位的凭据 ⇒ 不短接（业主 2026-11-04 裁定 · 乙-11）
    位写着真、而 `reviewed_by` 里既没有 `verification_id` 也没有 `proof_sha256`、
    逐条表里也没有任一条「为真且有 sha」⇒ 判不了，`signed=False`，照常送审。
    旧行 / repair / 手改行里可能只剩一个裸布尔；不拿它当"已经签过"。

    ## 返回（键集合固定；判不了也照样给全）
    `signed` / `proof_no` / `proof_sha256` / `reviewed_by` / `bits` / `why`。
    `signed=False` 的 `why` 写清是哪一档（位没翻 / 签过但正文改过 / 签的是别的证明 /
    没有命题行 / 证明号认不出 / 位没有可定位的凭据），读的人不必从几个假值里反推。
    """
    from . import evidencebits as _EB   # 惰性：与 `_reviewed_statement_row` 同一条纪律

    out: dict[str, Any] = {
        "signed": False, "proof_no": DEFAULT_PROOF_NO, "proof_sha256": "",
        "reviewed_by": {}, "bits": {}, "why": "",
    }
    if not isinstance(row, Mapping) or not row:
        out["why"] = "没有命题行 ⇒ 判不了「这一位签过没有」"
        return out
    no = as_proof_no(proof_no)
    if no < 1:
        out["why"] = f"证明号认不出：{proof_no!r}"
        return out
    out["proof_no"] = no
    bits = _EB.bits_from_row(row)
    out["bits"] = bits
    out["reviewed_by"] = dict((bits.get("evidence") or {}).get("reviewed_by") or {})
    sha_now = proof_sha(proof_text) if str(proof_text or "").strip() else ""
    out["proof_sha256"] = sha_now
    if not bits.get("reviewed"):
        raw = row.get("bits") if isinstance(row.get("bits"), Mapping) else {}
        if raw.get("reviewed"):
            # 位在盘上写着真、读侧却现算成假：那是「签过、但签的不是现在这一份正文」
            # （`evidencebits._stale_review_cleared`）。它必须照常重审，不许短接。
            out["why"] = ("命题行上那一位写的是真，但那一签盖住的不是现在这一份正文"
                          "（读侧按过期现算成假）⇒ 改稿之后要重审")
        else:
            out["why"] = "命题行的第 3 位没翻（这一份证明没被签过）"
        return out
    per = _EB.reviewed_by_proof(bits)
    sha_by = _EB.reviewed_sha_by_proof(bits)
    if per:
        if not per.get(no):
            out["why"] = (f"第 3 位签的证明不是 #{no}（逐条表里 #{no} 为假）"
                          "⇒ 这一份不许借别的证明的光")
            return out
    else:
        signed_no = as_proof_no(out["reviewed_by"].get("proof_no")) \
            if out["reviewed_by"] else 0
        if signed_no and signed_no != no:
            out["why"] = f"第 3 位签的是 #{signed_no}，不是 #{no}"
            return out
    want = str(sha_by.get(no) or "")
    if want and sha_now and want != sha_now:
        out["why"] = (f"#{no} 那一签盖住的正文不是现在这一份"
                      f"（签的 sha {want[:12]}…，现在 {sha_now[:12]}…）")
        return out
    if not _already_signed_locator(out["reviewed_by"], per, sha_by, no):
        # 位写着真、而凭据里没有任何可定位的签名 ⇒ 判不了，按没签过处理。
        # 这一支必须排在 `signed=True` 之前：短接是"省掉一次审校"，不能拿裸布尔换。
        out["why"] = ("第 3 位写着审过，但凭据里没有可定位的签名（`reviewed_by` 无 "
                      "`verification_id` / `proof_sha256`，逐条表也没有任一为真且有 sha）"
                      " ⇒ 判不了，按没签过处理：照常送审，不拿一个裸布尔短接")
        return out
    out["signed"] = True
    return out


def _is_legacy_row(row: Mapping[str, Any]) -> bool:
    """这一行是不是「历史形态」——没有单次送审的轮次标记。

    2026-11-02 起新写的台账行都带 `review_call`（同一趟 `verify_proof` 的调用 id）与
    `review_pass`（这趟里的第几轮）；老行没有这两个键。这两种行在判据上必须分开：

    - 新行：只有同一 `review_call` 内的 `review_pass=1..need` 才算一次送审的三轮；
    - 老行：读得出（`legacy_rows` 计数）、但不参与新签判断，也不按新规则重算成签。

    判据取"两个标记缺任一"而不是只看 `review_call`：半截写入（有 call id、没有轮次）
    同样说不清"这是第几轮"，按历史形态收是最保守的那一侧。
    """
    if not str(row.get("review_call") or "").strip():
        return True
    return row.get("review_pass") in (None, "")


def _hold_runs(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[bool]]:
    """逐行给出 `(到这一行为止连续几次成立, 这一行是否作废)`（行序 = 台账追加序）。

    这是台账历史读数的唯一计数实现：:func:`consecutive_holds`（从尾部取一格）、
    :func:`review_standing`（它已经读过同一批行，不重复读盘）、:func:`signed_rows`
    （一批台账里哪几行签住了）三处都调它；:func:`_hold_run_lengths` 是它的只取计数那一半。

    ## 2026-11-06（业主裁定 3 的准确含义）：打回站住，同一份正文不重复判

    业主逐字：「一次判有毛病时应该立即打回，不再起转，等下一次提交时重新从 0 转计数」。
    于是「打回」不只是一次清零，而是这份正文的下一次送审不再攒票：

    - 带 `review_call` 的行（2026-11-02 起的新形态 = 一次 `verify_proof` 的一转）：
      这一份正文上第一次出现 `axis=fault` 之后，后续那些新送审的 clean 行一律作废
      （`void=True`，计数停在 0）—— 它们不再算"另一次送审的三转"（真机
      `R-mk-infinite-94` 的 000034：v1 clean / v2 fault / v3–v5 clean 曾经凑成 3/3 签）;
    - 不带 `review_call` 的老行（2026-11-02 之前"一次调用只判一轮、靠台账尾部凑次数"
      的形态）：按旧口径读（fault 清零之后还能再攒）—— 这是历史兼容，不是新签的路
      （`tests/test_v_sign_gate_streak.py::test_a2` 钉着它）。

    为什么用 `review_call` 当判据而不是"一律作废"：老行没法归到某一次送审上，把旧读数
    按新规矩重算会把历史工作区的读数整体翻掉（那不是这次修正要动的东西）。
    """
    runs: list[int] = []
    void: list[bool] = []
    sha = ""
    run = 0
    #: 这一份证明里被判过打回的那些正文 sha（带 `review_call` 的那一行判了 fault）。
    #:
    #: 按 sha 记、不随"换了一份正文"清掉：台账里两份正文的行可以交错出现（改稿 → 回退 →
    #: 再改稿），而"这一份 sha 打回过"是这份正文的性质，不是相邻两行的性质。
    #: 改前它是单值、遇到 sha 变化就重置 ⇒ 交错出现时后一次的同 sha 行会漏掉作废。
    rejected: set[str] = set()
    for row in rows:
        one = str(row.get("proof_sha256") or "")
        if not runs or one != sha:
            run = 0
            sha = one
        axis = ledger_axis(row)
        call = str(row.get("review_call") or "").strip()
        is_void = bool(one and one in rejected and call)
        if axis == "fault":
            run = 0
            if call:
                rejected.add(one)
        elif not axis:
            # 没有轴：老行 / 没判成 / 轴名读不出来。那不是一种判定 ⇒ 既不攒票也不作废。
            pass
        elif is_void:
            # 打回之后又起转的那一趟：不算"同一次送审内的票"，也不给自己清零的理由。
            run = 0
        elif not row_signable(row):
            run = 0
        else:
            run += 1
        runs.append(run)
        void.append(is_void)
    return runs, void


def _hold_run_lengths(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """逐行给出「到这一行为止，连续几次成立」（行序就是台账的追加序）。

    计数规则（含 2026-11-06「打回站住」那一档）见 :func:`_hold_runs`：本函数只取它的
    计数那一半，读数对外的形状逐字未变。

    它不再充当"新签发不发"的判据（2026-11-02 业主定稿：「不允许跨两次送审累计
    成功数」）。一次 `verify_proof` 的签发只看同一次调用内的轮数
    （`sign_issuance.within_call`）；这个函数数的是跨全部历史行的连续数，只用来回答
    "台账上以前发生过什么"，旧工作区的读数（`holding` / `signed` 等）仍照它读。
    三个调用点都是读侧；写侧 `sign_statement` 在拿到 `within_call` 时不调它。

    三处各写一遍合计，只会让三处对同一批行给出三个数 —— 而"位上说签了、台账只签一次"
    正是这种分家的形态。

    ## 什么会清零、什么被读成"这一票算上了"（2026-10-29 的 A 段 + 2026-10-30 第三次裁定
    ## + 2026-11-01 的两态结论 + 2026-11-02 的追加裁定）
    - `proof_sha256` 变了 ⇒ 清零（F 改稿之后，之前那几次审的不是这一份）；
    - 行局部签不住（`有毛病` / 未解决 error / 引用挡签）⇒ 清零；
    - 轴是 `clean` ⇒ 投一票；
    - 轴是 `fault`（有缺陷要指出）⇒ 清零；
    - 没有轴（老行没有 `secretary_judge` / 问过没判成 / 轴名读不出来）⇒ 不清零、也不计入。
      这是 p247 的核心：轴只由秘书的语义分析给，`verdict` 的字面不是证据。
      "这一行的轴读不出来"与"这一趟判过了 clean"必须分得开，否则一次读侧故障就会把一条
      未判的行静默算成一票（`tests/test_v_sign_gate_streak.py` 的 z2(c) 钉着这件事）。
    - 轴是 `clean` 但行局部机械闸没过（未解决 error / 引用挡签 / 依赖台账读不成）⇒ 清零；
    - 同一份正文已经被打回过（带 `review_call` 的那一次送审里判了 fault）⇒ 之后的
      新送审行一律作废、不攒票（2026-11-06 业主裁定 3；判据在 :func:`_hold_runs`）。

    调用方负责先把行分组（同一命题 + 同一证明号）：一条命题的两份证明各自数各自的，
    `#p1` 的三票不许替 `#p2` 数（不许借光）。
    """
    return _hold_runs(rows)[0]


def void_after_rejection(rows: Sequence[Mapping[str, Any]]) -> list[bool]:
    """逐行给出「这一行属于『同一份正文被打回之后又起转』的那一趟」（读侧共用的一把尺）。

    判据只有一处实现（:func:`_hold_runs`），本函数是它对外的那一半：读侧有两处必须
    同尺 —— 台账的连续计数（:func:`_hold_run_lengths`）与"重送义务清没清"
    （:func:`vreceipts.resubmit_cleared`）。两处各判一套的后果很具体：作废行一边不算
    票、一边却还能把"要你重送"的义务清掉 —— 于是一份被打回、没改稿、重掷签上的正文，
    既不欠票、也不再有人要求它重送（"打回即站住"只站住了一半）。

    调用方负责先把行分组（同一命题 + 同一证明号），与 :func:`_hold_run_lengths` 同一条。
    """
    return _hold_runs(rows)[1]


def _rows_of_proof(rows: Sequence[Mapping[str, Any]], proof_no: int) -> list[Mapping[str, Any]]:
    """这一批台账行里属于 `#proof_no` 的那些（按台账行序，别的证明的行一条都不带）。"""
    return [r for r in rows if proof_no_of(r) == int(proof_no)]


def consecutive_holds(root: str | Path, statement_id: str, proof_no: Any = 1,
                      need: int | None = None) -> dict[str, Any]:
    """台账尾部连续几次「成立」且是同一份正文（纯读；业主 2026-10-29 的 A 段）。

    `need=None` = 门槛现读 `SIGN_STREAK_NEED`（2026-10-30 改，理由与 :func:`streak_ok`
    同一句：默认参数是导入期的快照，不是门槛本身 —— 而 `sign_statement` 的签字闸读的
    就是这个函数的返回值，两处门槛漂了之后"够不够"会给出两个数）。

    这就是「连续 3 次没问题」那个计数：从 `verifications/<命题号>.jsonl` 的尾部按台账
    行序往回数，同一 `proof_sha256`、连续判「成立」的行数；任何一行判「有毛病」、或者
    sha 换了、或者秘书判了 `fault` ⇒ 从那里断开（尾行自己就断 ⇒ 0 次）。
    秘书没查成的那一行不清零也不计入；老行上的 `看不出来`（:data:`LEGACY_VERDICTS`）
    按成立读、并且算一票（2026-11-02：那一档连历史兼容读也不留，见
    :func:`_hold_run_lengths` 与本模块 :func:`read_verdict`）。

    ## 三态（"没查成"不是"0 次"）
    | 结局 | `checked` | `streak` |
    |---|---|---|
    | 数出来了（含"一次都没签"） | True | 数出来的次数（可以是 0） |
    | 台账在盘上但读不出坏行 / 证明号认不出 / 命题号不是编号形态 | False | 0 |

    `checked=False` 时 `streak=0` 只是占位（返回值必须有一个整数），调用方要读的是
    `checked`：`signs_bit3(row, streak=<这一份>)` 会因为它 `checked` 为假而不签
    （见 :func:`_streak_number`），所以"没查成"在签字那一端是 fail-closed 的。

    ## `legacy_rows`：历史形态的显式读数（2026-11-02）

    `legacy_rows` = 这一份证明的台账行里没有 `review_call` / `review_pass` 的行数。
    这些行是旧版跨送审累计形态留下的（当时一次调用只判一轮、靠台账尾部凑次数），
    读得出、也仍参与 `streak` 这个历史读数；但它们不参与新签判断 ——
    新签只看同一趟 `verify_proof` 内 `review_pass=1..need` 的那几行
    （`sign_issuance.within_call`）。"多少行是历史形态"必须能一眼读出来，否则
    "旧台账的 2 行 clean 被当成这一次的 2 轮"会静静地发生。

    返回键：`checked` / `statement_id` / `proof_no` / `need` / `streak` / `streak_ok` /
    `sha`（尾部那一签盖住的正文 sha256）/ `rows`（这一个证明号的行数）/
    `legacy_rows` / `ledger` / `reason`。
    """
    out: dict[str, Any] = {
        "checked": False, "statement_id": str(statement_id or "").strip(),
        "proof_no": 0, "need": int(SIGN_STREAK_NEED) if need is None else int(need),
        "streak": 0, "streak_ok": False,
        "sha": "", "rows": 0, "legacy_rows": 0, "ledger": "", "reason": "",
    }
    no = _read_proof_no(proof_no)
    if no < 1:
        out["reason"] = (f"证明号认不出：收到 {proof_no!r} ⇒ 不知道数的是哪一份证明，"
                         "这一格没查成（不是「一次都没签」）")
        return out
    out["proof_no"] = no
    sid = out["statement_id"]
    if not S.is_valid_id(sid):
        out["reason"] = (f"命题号 {sid!r} 不是编号形态 ⇒ 查不到台账，这一格没查成"
                         "（不是「一次都没签」）")
        return out
    try:
        path = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out["reason"] = f"命题号 {sid!r} 查不到台账（{exc}）⇒ 这一格没查成"
        return out
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        out.update(checked=True,
                   reason=(f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有"
                           "（查过了：连续次数是 0，不是「没查成」）"))
        return out
    rows, problems = JF.read_jsonl(path)
    if problems:
        out["reason"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                         "连续次数没查成（不是「0 次」）")
        return out
    mine = _rows_of_proof(rows, no)
    out["rows"] = len(mine)
    out["legacy_rows"] = sum(1 for r in mine if _is_legacy_row(r))
    out["checked"] = True
    if not mine:
        out["reason"] = (f"`{out['ledger']}` 里没有 #{no} 这一份证明的签 ⇒ 连续次数 0"
                         "（别的证明签过也不借光）")
        return out
    runs = _hold_run_lengths(mine)
    tail = mine[-1]
    run = runs[-1]
    out.update(streak=int(run), streak_ok=bool(run >= out["need"]),
               sha=str(tail.get("proof_sha256") or ""))
    if out["streak_ok"]:
        out["reason"] = (f"#{no} 的尾部连续 {run} 次「成立」且盖着同一份正文"
                         f"（sha {out['sha'][:12]}…，门槛 {out['need']} 次）⇒ 够发签")
    else:
        out["reason"] = (f"#{no} 的尾部连续 {run} 次「成立」（门槛 {out['need']} 次，"
                         f"最新一签 {str(tail.get('verification_id') or '') or '（没有编号）'}、"
                         f"verdict={tail.get('verdict')!r}）⇒ 不发签：连续次数没到门槛"
                         "（这一签只落台账、不翻位）")
    return out


def signed_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """这一批台账行里签住了第 3 位的那些（按 (命题号, 证明号) 分组各自数连续次数）。

    `ledger_reading` / `unverified_statement_refs` 要从一批跨命题的行里数"有几行签住了"，
    而连续次数只能在同一份证明的同一批行里数 ⇒ 分组这一步必须只有一处实现
    （否则两个读数会对同一批行给出不同的行数）。
    """
    groups: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((_statement_id_of(row), proof_no_of(row)), []).append(row)
    out: list[Mapping[str, Any]] = []
    for key in sorted(groups):
        one = groups[key]
        for row, run in zip(one, _hold_run_lengths(one)):
            if signs_bit3(row, streak=run):
                out.append(row)
    return out


def _verification_line(row: Mapping[str, Any]) -> str:
    """台账的一行怎么落盘（唯一实现：追加与撤回都拿它算字节）。"""
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"


def _append_verification(path: Path, row: Mapping[str, Any]) -> int:
    """追加一行，返回追加前的文件字节数（撤回时按它截断）。"""
    line = _verification_line(row).encode("utf-8")
    before = path.stat().st_size if path.exists() else 0
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line.decode("utf-8"))
    return before


def _rollback_append(path: Path, before: int, row: Mapping[str, Any]) -> bool:
    """把刚追加的那一行撤掉（只撤我们自己的那一行）；撤不动 ⇒ False。

    判据是"文件尾逐字等于我们写的那一行"：文件尾若已经变成别人的行，截断会
    删掉别人的记录 —— 那种情况下宁可留着我们这一行（它确实发生过），也不动别人的。
    """
    want = _verification_line(row).encode("utf-8")
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if data[before:] != want:
        return False
    try:
        with path.open("r+b") as fh:
            fh.truncate(before)
        return True
    except OSError:
        return False


def _reviewed_statement_row(found: Mapping[str, Any], verification_row: Mapping[str, Any],
                           *, proof_text: str, proof_no: int = 1,
                           streak: Any = None) -> dict[str, Any]:
    """命题那一行改成"那一份证明的第 3 位已签"的样子。

    只动四处：那一份证明的 `reviewed`（#p1 = `bits.reviewed` 的汇总位；#p2+ 另外把
    `proofs` 清单里对应项标上）、逐条证明的那张表
    （`bits.evidence.reviewed_by_proof = {"1": true, "2": false, ...}`）、逐条证明的
    "那一签盖住哪一份正文"那张表（`bits.evidence.reviewed_sha_by_proof`）与凭据
    `reviewed_by`；别的一格不碰。等级必须现算
    （`evidencebits.normalize_raw` 的唯一入口）：盘上那份 `grade` 只是缓存，写下去的
    必须与现算逐字相同，否则提交期 `bits_shape_problems` 会拒收这一笔。

    ## 逐条表为什么必须整表写，而不是只写被签的那一格
    业主的负控是"签了 #p1、#p2 读成 False"。只写 `{"1": true}` 的话，`#p2` 是"表里
    没有这一格"——而"没有"与"有、值为 False"在读侧长得不一样：前者要靠调用方记得
    缺省是 False，后者是直接读出来的结论。所以这里把 `proof_list` 里每一份都列出来，
    被签的那一份为 True，其余按原来的值（没有再按 False）。汇总位
    `bits.reviewed` 的语义不变：任一份为 True 即 True。

    ## 第二张表为什么也整表写（sha 那一格）
    汇总位要回答"还有没有一份证明仍盖着现在这一份正文"。`reviewed_by` 只留最近那一签，
    只核它会让"签过 #p1、之后改了 #p2"读成没审过。所以逐条记下每一签的 sha：被签的
    那一份换成这一签的 `proof_sha256`，其余保留原值（没有就写空串 = 这一份判不了）。
    """
    from . import evidencebits as _EB   # 惰性：只在真写这一行时需要（不新增模块级依赖边）

    new = dict(found)
    # 证明号已经在 `sign_statement` 判过（`proof_no_strict`：没给 ⇒ canonical，给了坏值 ⇒
    # 拒）；这里再走一遍同一个函数是防"将来有人直接调本函数"时把 0 静默折成 #p1。
    no = proof_no_strict(proof_no)
    payload = bit3_payload(verification_row, streak=streak)
    reviewed_by = dict(payload.get("reviewed_by") or {})
    bits = dict(new.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    # 逐条表整表写（含未签的那几份为 False）：`#p2` 不许借 `#p1` 的光。
    per = {str(n): bool(v) for n, v in
           (_EB.reviewed_by_proof(new) or {}).items()}
    per = {str(n): bool(per.get(str(n), False)) for n, _ in proof_list(new)}
    per[str(no)] = True
    ev[_EB.REVIEWED_BY_PROOF_KEY] = per
    # 逐条证明的"那一签盖住的是哪一份正文"：`{证明号: sha256}`（没签过 / 判不了的写空串）。
    # 汇总位按"任一条仍 in-sync ⇒ True"读，靠的就是这一格（见 `_stale_review_cleared`）。
    sha_by_proof = {str(n): str(v) for n, v in
                    (_EB.reviewed_sha_by_proof(new) or {}).items()}
    sha_by_proof = {str(n): str(sha_by_proof.get(str(n), "")) for n, _ in proof_list(new)}
    sha_by_proof[str(no)] = str(verification_row.get("proof_sha256") or "")
    ev[_EB.REVIEWED_SHA_BY_PROOF_KEY] = sha_by_proof
    # 命题那一行的 `bits.reviewed` 是"这条命题至少有一份证明被审过"的汇总位（老读者
    # 只认它）；真正的凭据按证明记：`reviewed_by` 里带 `proof_no` 与 `proof_sha256`，
    # 于是"这一位说的是哪一份"不再靠猜。
    ev["reviewed_by"] = reviewed_by
    bits["reviewed"] = any(per.values())
    bits["evidence"] = ev
    new["bits"] = _EB.normalize_raw(bits, origin=str(new.get("origin") or "own_result"),
                                    kind=str(new.get("kind") or ""))
    if no > 1:
        entries = [dict(p) if isinstance(p, Mapping) else p
                   for p in (new.get(PROOFS_KEY) or [])]
        for p in entries:
            if isinstance(p, dict) and proof_no_of(p) == no:
                p["reviewed"] = True
                p["reviewed_by"] = dict(reviewed_by)
        new[PROOFS_KEY] = entries
    return new


def _kind_upgrade_from_signature(row: Mapping[str, Any], *, root: str | Path,
                                 verifier: str) -> dict[str, Any]:
    """V 判「成立」之后，按证据位把这一行的 `kind` 现算一遍（D-69）。

    ## 为什么它在签名这一笔里（断链在哪）
    D-37 已经有"kind 该不该跟着证据升"的唯一判据（`evidencebits.kind_following_grade`，
    纯读），但它的写侧落点都不在"V 签字"这条路上：
    `agent_b.register_statement` 的那一格只在第 4 位（形式化）同步出变化时才跑。
    于是真机 sylow3 那种形态 —— V 的台账里判「成立」、`bits.evidence.reviewed_by_proof`
    是 `{"1": true}`，而 `statements` 那一行的 `kind` 仍是 `conjecture` —— 没有任何一步会
    去改它：读的人（G 写稿 / H 审校 / 收工门）读 `kind`，于是"这是定理"这句话在盘上
    不存在，论文却已经把它排成 lemma / theorem。

    这一格就是那条断链的补口：台账那一行刚追加进 `verifications/<命题号>.jsonl`
    （同一个事务里），`kind_following_grade` 现在读得到那一签，于是把它放在
    `_reviewed_statement_row` 之后、`tx.upsert` 之前 —— 位与档位同一笔事务落盘。

    ## 只抬 `kind`，不碰 `evidence_kind`
    `evidence_kind` 的抬档已经有一条正路（秘书那一支，凭据是同一个
    `verifications.proof_review_gap`），而 `kind` 那一格没有任何一条正路会在签字之后
    到达。两件事各修一处，不再造第二份 `evidence_kind` 口径。

    ## 三态（判不了就不抬）
    只有 `kind_following_grade` 说 `state="upgraded"` 时才改那一格：`held`（凭据不够）
    与 `unreadable`（五元位算不出来）都原样返回 —— "没判成"绝不折成"已经升了"。
    这一笔也绝不降档：起点只认 `conjecture`（`KIND_UPGRADABLE_FROM`），别的 kind 一个字不动。

    返回 `{"row", "kind_upgrade", "note"}`：`row` 是（可能）改过 `kind` 的那一行，
    `kind_upgrade` 是与秘书那一支同形的留痕（`from` / `to` / `basis` / `grade` /
    `by` / `at`），`note` 是给返回读数看的那一句「因 V 判成立而抬档：…（依据 …）」。
    """
    from . import evidencebits as _EB   # 惰性：与 `_reviewed_statement_row` 同一条纪律

    out: dict[str, Any] = {"row": dict(row), "kind_upgrade": {}, "note": ""}
    read = _EB.kind_following_grade(out["row"], root=root)
    if str(read.get("state") or "") != "upgraded":
        return out
    target = str(read.get("kind") or "")
    before = str(out["row"].get("kind") or "")
    if target not in _EB.KIND_UPGRADE_TARGETS or target == before:
        return out
    basis = str(read.get("basis") or "")
    out["row"]["kind"] = target
    out["row"]["_kind_upgrade"] = {
        "from": before, "to": target, "basis": basis,
        "grade": str(read.get("grade") or ""),
        "by": str(verifier or "verifier-V"), "at": S.now_iso(),
    }
    out["kind_upgrade"] = dict(out["row"]["_kind_upgrade"])
    out["note"] = (f"因 V 判成立而抬档：{before or '（空）'}→{target}"
                   f"（依据 {basis or '台账里那一签'}）")
    return out


#: 机器核过的那一档（`schema.EVIDENCE_KINDS` 的最强端）。回填只认它"比 proof_review 强"。
PROOF_KIND = str(S.EVIDENCE_KINDS[0])

#: V 落签之后"按现行签把档位重算一遍"那一格的读数键（业主 2026-11-04）。
#:
#: 与秘书那一支的 `_evidence_kind_upgrade` 刻意分成两格：那一格记的是"同一份内容再交
#: 一次、这一回来的声明更强"（提交方声明的来路）；这一格记的是"签刚落位、按盘上那一签
#: 重算"（盘上凭据的来路）。两件事的来路不同，读的人要能分开看 —— 否则"这一格是谁改的"
#: 永远查不出来。
GRADE_RECOMPUTED_KEY = "_grade_recomputed"


def _exhaustion_proof_channel(row: Mapping[str, Any], *,
                              root: str | Path) -> dict[str, Any]:
    """这一行的证明走的是不是「E 的穷举程序 + V 签」那条通道 —— 纯读，不写任何东西。

    ## 为什么回填必须分通道（业主 2026-11-04 的裁定，写死在 `schema.EVIDENCE_KINDS`）
    穷举数值证明 + 针对该穷举的 V 签 ⇒ 直接 `proof`；`proof_review` 的定义是
    "V 逐行审过文字证明"，而 V 不能逐行走查一份程序 ⇒ 穷举题停在 `proof_review`
    本身就是错的终态。所以"V 落签之后按签重算档位"这一格不能一律给 `proof_review`：
    它得先问一句"这一份证明是哪条通道的"。

    ## 判据只有一处（不另立第二套穷举口径）
    这一格只问 `numericproof.find_signed_exhaustion_for_column` —— 它内部读
    `is_signed_exhaustion`（方法属于计算类、`evidence_kind="proof"`、签名主体 V、
    ②③ 作者含 E、`proof_reason="exhaustion"`），正是 `verify` 审计
    （`proof_stmt_without_formal_backing` 的第二条合法背书）与 B 的入库闸用的那一个函数。
    于是"回填给的档"与"审计认的背书"结构上是同一件事，不会分家。

    ## 三态（判不了就不按穷举给档）
    - `checked=False`：实验台账读不出来（没给根 / 表坏了）⇒ "没查成"，调用方按文字
      证明通道处理（`proof_review`）—— 不许把"没查成"读成"是穷举"；
    - `checked=True, found=False`：查过了，台账里没有这份证明栏对应的穷举证明
      ⇒ 文字证明通道；
    - `found=True`：`experiment_id` / `script` 指向那一条 E 签的穷举证明。

    返回 `{checked, found, experiment_id, script, why}`。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "experiment_id": "",
                           "script": "", "why": ""}
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        out["why"] = "这一行没有证明正文 ⇒ 通道判不了（也就没有任何一档可升）"
        return out
    if not str(root or "").strip():
        out["why"] = "没给工作区根 ⇒ 实验台账读不出来（这一格没查成）"
        return out
    try:
        from . import numericproof as _NP   # 惰性：穷举判据的单一口径
        from .store import Store           # 惰性：只读一份表，不参与本模块的写事务

        experiments = Store(root).rows("experiments")
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许猜成"是穷举"
        out["why"] = (f"实验台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                      "（按文字证明通道处理，不按穷举给 proof）")
        return out
    out["checked"] = True
    hit = _NP.find_signed_exhaustion_for_column(experiments, text)
    if hit is None:
        out["why"] = ("台账里没有与这份证明栏对应的、V 签下的穷举证明 "
                      "⇒ 这一行走文字证明通道（`proof_review`）")
        return out
    out["found"] = True
    out["experiment_id"] = str(hit.get("experiment_id") or hit.get("id") or "")
    out["script"] = _NP.proof_column_script(text)
    out["why"] = (f"证明栏是穷举证明的三段式（① 程序 {out['script'] or '（空）'} + ②③），"
                  f"台账里 exp:{out['experiment_id'] or '?'} 是 V 签下的穷举证明")
    return out


def _grade_recomputed_from_signature(row: Mapping[str, Any], *, root: str | Path,
                                     proof_no: Any = None) -> dict[str, Any]:
    """V 的签刚落位 ⇒ 按现行签现算等级（只算等级，不再写档位）。

    ## 业主 2026-11-05 的裁定（为什么这一格从"写档"改成"只算等级"）
    「档位不再是一套词表：`evidence_kind` 只作历史列保留，判定面一律读等级」。
    于是这一格不再回答"该把 `evidence_kind` 写成哪一档"，只回答"按五元位现算，
    这一行现在是哪一级"。签落位之后 `bits.reviewed` 已被 `_reviewed_statement_row`
    翻真 ⇒ 等级自然升到 `pre_theorem`（或第 1/4 位本就 verified 时到 `theorem`）；
    这一格不复制那份真值，它只是把"凭什么"（哪一份台账的哪一签）与档位的历史反算名
    （`kind_from_grade`）写进读数，供回执与审计用。

    ## 三态（不折平）
    - 凭据读不出来 ⇒ `checked=False`（"没查成"既不是"不够格"也不是"没变"）；
    - 凭据不够（没签 / 签的是旧版 / 判的不是成立）⇒ `reading={}`（negative：
      没签的命题不许被这一格说成"升了"）；
    - 算出来了 ⇒ `to` 是等级、`to_kind` 是它的历史反算名。

    ## 只读
    本函数一个字节都不写：`out["row"]` 是入参的副本、`evidence_kind` 不动。
    写档位的地方（若还有）必须走 `EB.kind_from_grade` 反算，不许拿这一格的
    `to` 直接当档位（那是把等级又译回第二套真值）。`_apply_grade_backfill`
    是那唯一一处写者，写的是反算名，不是"这一格给的目标档"。

    返回 `{"row", "reading"}`：`reading` 是
    `{checked, from, to, from_kind, to_kind, why, basis, proof_no, at}`；
    没动过就是 `{}` —— 键的存在本身说明"这一签改变了等级读数"。
    """
    out: dict[str, Any] = {"row": dict(row), "reading": {}}
    if str(out["row"].get("kind") or "") == "concept":
        # 概念不参与等级链：既不是"升了"也不是"不够格"，这一格没有它的事。
        return out
    try:
        gap = proof_review_gap(root, out["row"], proof_no=proof_no)
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许当成"不够格"
        out["reading"] = {
            "checked": False, "from": "", "to": "",
            "why": (f"凭据读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                    "等级与档位一个字节不动")}
        return out
    if not gap.get("ok"):
        return out
    ledger = str(gap.get("ledger") or "")
    vid = str(gap.get("verification_id") or "")
    # 两支的 `ledger` 形状不同：台账支是路径（`verifications/<号>.jsonl`），pending 支
    # 已经带着号（`verifications/pending/<sha>.jsonl#u-000001`，见 `pending_sign` 的
    # `ledger`）。这里只在"还没带号"时补一次 —— 否则 pending 支会拼成
    # `…jsonl#u-000001#u-000001`：同一个锚点写两遍，读的人会以为那是两层定位。
    basis = (f"{ledger}#{vid}" if ledger and vid and not ledger.endswith(f"#{vid}")
             else (ledger or vid))
    try:
        bits = EB.bits_from_row(out["row"])
    except Exception as exc:  # noqa: BLE001 —— 同上：算不出来就是没查成
        out["reading"] = {
            "checked": False, "from": "", "to": "",
            "why": (f"五元位算不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                    "等级与档位一个字节不动")}
        return out
    # ---- 穷举通道：签住的是 E 的穷举程序 ⇒ 第 1 位落 verified ---------------
    #
    # 2026-11-05 业主裁定「穷举证书相当于 Lean 形式化，表示绝对正确」，于是
    # `derive_grade` 的 `theorem` 有两条同级入口：第 2 位 + 第 4 位（formal verified）
    # 或第 2 位 + 第 1 位（numeric verified）。但"V 签住这一份穷举证明"这件事此前
    # 没有任何写者把它落到第 1 位：`_exhaustion_proof_channel` 还在，却没人调用
    # ⇒ 穷举题签完停在 `pre_theorem`，永远到不了 `theorem`。
    #
    # 位置与 `_reviewed_statement_row` 的 reviewed 同一步：签已经落位（gap.ok），
    # 这一格只把"签住的那份证明是哪条通道"翻译成第 1 位。通道判据只有一处
    # （`numericproof.find_signed_exhaustion_for_column`），这里不另写一份。
    channel = "text"
    try:
        _exhaustion = _exhaustion_proof_channel(out["row"], root=root)
    except Exception:  # noqa: BLE001 —— 通道判不了就按文字证明（不猜成穷举）
        _exhaustion = {"checked": False, "found": False, "why": ""}
    if _exhaustion.get("found"):
        evidence = dict(bits.get("evidence") or {})
        evidence["numeric"] = {
            "experiment_id": str(_exhaustion.get("experiment_id") or ""),
            "script": str(_exhaustion.get("script") or ""),
            "why": str(_exhaustion.get("why") or ""),
        }
        bits = dict(bits, numeric="verified", evidence=evidence)
        kind_now = str(out["row"].get("kind") or "")
        out["row"]["bits"] = EB.normalize_raw(
            bits, origin=str(out["row"].get("origin") or "own_result"),
            voided_by=dict(bits.get("voided_by") or {}), kind=kind_now)
        bits = out["row"]["bits"]
        channel = "exhaustion"
    target = EB.derive_grade(bits, kind=str(out["row"].get("kind") or ""))
    from_kind = str(out["row"].get("evidence_kind") or "").strip()
    from_grade = EB.KIND_TO_GRADE.get(from_kind, "")
    # ---- 幂等（不写第二个时间戳）：两件都算"这一签没有新消息" ----------------
    # ① 历史列反算出来的等级与现算等级相同（例如位没翻 ⇒ 两边都是 conjecture）；
    # ② 行上已经有一条 `to` 相同的回执（同一份签再签一次）。
    # 只读行上的回执，不读 `evidence_kind` 当第二套真值 —— 后者只是 `from` 的读数。
    prior = out["row"].get(GRADE_RECOMPUTED_KEY)
    if from_grade and from_grade == target:
        return out
    if isinstance(prior, Mapping) and str(prior.get("to") or "") == target:
        return out
    out["reading"] = {
        "checked": True,
        "from": from_grade, "to": target,
        "from_kind": from_kind, "to_kind": EB.kind_from_grade(target),
        "channel": channel,
        "why": ("V 的签刚落位：这一行有证明正文，且台账里那一签盖住的就是现行这一版 "
                "⇒ 按五元位现算等级（只算等级，不写档位）；"
                f"历史列 `evidence_kind`={from_kind or '（空）'} 只是读数，判定面读 `{target}`"),
        "basis": basis, "proof_no": int(gap.get("proof_no") or 0) or None,
        "at": _now_iso(),
    }
    return out


def _vsign_payload(*, root: Any, ledger: Path, statement_id: str, proof_no: int,
                   sha: str, need: int, holds: Mapping[str, Any],
                   manuscript: str = "") -> dict[str, Any]:
    """组一份签的内容（纯读：台账 + 手稿路径；不写任何东西）。

    业主 2026-11-01（逐字）：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题
    收录时读到。」于是签要落成「按被签正文 sha 命名」的一份侧文件（`out/vsigns/<sha>.json`），
    它的内容全部从台账现读，不复制全文：

    - `passes`：这一份正文尾部连续 `need` 转的 `{verification_id, at, proof_sha256, why}`
      （`why` 是 V 那一转自己写的理由，逐字；「全文在台账」，见 `vsigns.PASSES_SOURCE_NOTE`）；
    - `objections`：「同一份 sha」 上的「有毛病」记录（两档都算：V 自己判的、秘书判 fault 的）。
      为什么要它：同一段正文可能先被判有毛病、后来连续三次成立拿到签（V 改判 / 秘书在
      「V 写成立」的回复上读出缺陷那一档）—— 那段痕迹必须留在签上，否则"先有毛病、后有签"
      这件事在签这一份文件里看不见（跨 sha 的改版链不在这里，那是台账 `superseded` 的事）；
    - `artifact_path`：这一签的载体。给了 `manuscript` 就用它（在册那一支从台账行带来，
      2026-11-04 甲：手稿是签的唯一载体）；没给才退回 `depsection.manuscript_relpaths`
      扫"按号命名的 f-proof 稿"（旧行为）。两者都找不到就留空 —— `ledger` 那一格永远有，
      所以定位不会丢。

    `written_by` 不在这里定（本函数只组内容）：它由调用方那一格
    :func:`_vsigns_write_after_flip` 按 `append_ledger` 分两档 —— 秘书落地那条路
    （V 先落台账、秘书只翻位）是 `secretary`，直调写入口（夹具 /
    `record_verification(flip=True)`）是 `sign_statement(direct)`。两者都真实发生过，
    把后者也写成 secretary 会让"这张签是谁发的"变成假话。
    """
    from . import vsigns as _VS

    out: dict[str, Any] = {"passes": [], "objections": [], "artifact_path": "",
                           "ledger": f"{VERIFICATIONS_DIR}/{statement_id}.jsonl#"
                                     f"{str(holds.get('verification_id') or '')}",
                           "at": S.now_iso()}
    try:
        rows, _problems = JF.read_jsonl(ledger)
    except OSError:
        rows = []
    mine = _rows_of_proof([dict(r) for r in rows], proof_no)
    runs = _hold_run_lengths(mine)
    want = max(1, int(need or 1))
    passes: list[dict[str, Any]] = []
    # ---- 2026-11-02：签的 `passes` 只许来自同一趟送审（业主：「不允许跨两次送审
    # 累计成功数」）。持有 `review_call` 时按它取行，绝不按台账尾部的连续票数回捞 ——
    # 后者会把旧台账里的 clean 行拼进本次的签（实测：2 行历史 + 本次第 1 轮，tail=3
    # 会捞到 runs=3/2/1 的三行，其中两行是历史行）。
    call_id = str(holds.get("review_call") or "")
    if call_id:
        picked = [r for r in mine
                  if str(r.get("review_call") or "") == call_id
                  and int(r.get("review_pass") or 0) >= 1]
        picked.sort(key=lambda r: int(r.get("review_pass") or 0))
        picked = picked[:want]
        for r in picked:
            passes.append({
                "verification_id": str(r.get("verification_id") or ""),
                "at": str(r.get("at") or ""),
                "proof_sha256": str(r.get("proof_sha256") or ""),
                "why": str(r.get("why") or ""),
                # 这两格让"三票同源"在签文件里可直接读（vsigns.write_sign 原样复制）。
                "review_call": call_id,
                "review_pass": int(r.get("review_pass") or 0),
            })
    else:
        # 历史 / 直调路径：按台账尾部连续票数回捞（旧行为，逐字不变）。
        # 尾部那一串连续成立的票：`runs[i]` 就是"到这一行为止连续几次"，
        # 所以从尾部往回收 `streak, streak-1, …` 恰好收齐那一串。
        # 为什么不用 `signs_bit3(row, streak=runs[i])` 过滤：那个谓词问的是"这一行能不能翻位"
        # （要够门槛），而这里要的是"哪几行是这一签的票"—— 前两票本来就不够门槛，
        # 用翻位谓词会把它们全滤掉（实测：passes 只剩 1 条）。
        tail = int(holds.get("streak") or (runs[-1] if runs else 0))
        for i in range(len(mine) - 1, -1, -1):
            if len(passes) >= want:
                break
            if str(mine[i].get("proof_sha256") or "") != sha:
                continue
            if runs[i] != tail - len(passes):
                continue
            one = {"verification_id": str(mine[i].get("verification_id") or ""),
                   "at": str(mine[i].get("at") or ""),
                   "proof_sha256": str(mine[i].get("proof_sha256") or ""),
                   "why": str(mine[i].get("why") or "")}
            if (str(mine[i].get("review_call") or "")
                    or mine[i].get("review_pass") is not None):
                one["review_call"] = str(mine[i].get("review_call") or "")
                one["review_pass"] = mine[i].get("review_pass")
            passes.append(one)
        passes.reverse()
    if passes:
        # 最后的那一签就是这一份签的落点（台账行序 = 追加序，不存在第二种"最近"）。
        out["ledger"] = f"{VERIFICATIONS_DIR}/{statement_id}.jsonl#" \
                        f"{passes[-1]['verification_id']}"
    out["passes"] = passes
    objections: list[dict[str, Any]] = []
    for row in mine:
        if str(row.get("proof_sha256") or "") != sha:
            continue
        axis = _VS.verdict_axis(row)
        if not axis:
            continue
        objections.append({"verification_id": str(row.get("verification_id") or ""),
                           "at": str(row.get("at") or ""),
                           "axis": axis,
                           "defect_steps": _VS.defect_steps(row)})
    out["objections"] = objections
    # ---- 载体：点名的那一份优先（2026-11-04 甲）---------------------------------
    #
    # 改前只按 `depsection.manuscript_relpaths` 扫"按号命名的 f-proof 稿"：真机里稿
    # 叫 `notes/...` 或 B 的 `b-proof-<号>.md` 时就扫不到，签只落进台账、稿上没有签块。
    # 现在在册那一支把 `proof_manuscript` 随台账行带进来（`record_verification` 的
    # `manuscript` 参数）⇒ 就盖回送审方点名的那一份；没点名时才退回扫盘（旧行为）。
    named = str(manuscript or "").strip().replace("\\", "/")
    try:
        if named:
            if (Path(str(root)) / named).is_file():
                out["artifact_path"] = named
            # 点名了而盘上没有 ⇒ 不退回扫盘：签会盖到另一份稿上，那比"没有落点"更坏。
            # 这一档由 `_registered_manuscript_body` 在更早处拒掉，到这里只作兜底。
        else:
            from . import depsection as _DS

            for rel in _DS.manuscript_relpaths(statement_ids=[statement_id]):
                if (Path(str(root)) / rel).is_file():
                    out["artifact_path"] = str(rel)
                    break
    except Exception:  # noqa: BLE001 —— 定位那一格读不成不算失败（它不参与判据）
        out["artifact_path"] = ""
    return out


def _registration_after_vsign(*, store: Any, root: Any, vsign: Mapping[str, Any],
                              statement_id: str, proof_no: int,
                              sha: str, skip_gap: bool = False) -> dict[str, Any]:
    """`sign_statement` 那一笔事务之外：签块落成了就给 B 开一条「必须收录」义务。

    为什么必须在事务之外（2026-11-05 实测）：`_vsigns_write_after_flip` 跑在
    `store.tx("statements")` 里面，而开板项要拿 `tasks` / `counters` 的锁 ⇒ 在里面开项
    直接撞 `StoreError: 获取 counters 的锁超时（30.0s）`（同一进程已经持有那把锁）。
    所以这一格落在事务落定之后（`sign_statement` 的返回之前）。

    为什么以"块真的落成"为闸：义务的凭据是稿上那一块成立的签。没落成（未在册 / 秘书
    不在场 / 正文不符那几档）不是"签了没人收录"，那一档由收工扫盘
    （`vreceipts.sweep_registrations`）按盘上的事实兜底 —— 这里不编一条。
    """
    land = dict(vsign.get("land") or {}) if isinstance(vsign, Mapping) else {}
    if not land.get("landed"):
        return {"checked": True, "state": "skipped", "code": "sign_not_landed",
                "reason": ("签块没落成 ⇒ 这一档不是「签了没人收录」（收工扫盘按盘上的"
                           "事实兜底），不在这里开义务")}
    sign = dict(vsign.get("sign") or {}) if isinstance(vsign, Mapping) else {}
    mw = dict(land.get("manuscript_write") or {})
    rel = str(mw.get("path") or sign.get("artifact_path") or "")
    return _registration_after_sign(store=store, root=root,
                                    statement_id=str(statement_id or ""),
                                    proof_no=int(proof_no or 1), sha=str(sha or ""),
                                    manuscript=rel, at=str(sign.get("at") or ""),
                                    skip_gap=skip_gap)


def _registration_after_sign(*, store: Any, root: Any, statement_id: str, proof_no: int,
                             sha: str, manuscript: str, at: str = "",
                             skip_gap: bool = False) -> dict[str, Any]:
    """签发（签块落成）之后：给 B 开一条「必须收录」义务（缺陷 B；永不抛）。

    为什么在这里（业主 2026-11-05）：87 的现场是"签了但没人收录"——
    `reports/f-proof-000000.md` 上有 `secretary:F` 的成立签，而 `statements:000000`
    仍是 `正文=0 / reviewed=false`；盘上的根因是 D 从头没派 B 收录（B 在 87 里只被派过
    1 次，还是文献侧的 `t-000027`）。教学里那句话（`specs/d.py`「那一行写进你的报告之后
    派 B 入库」）在，但"教"不是"义务"：签发之后必须有东西把"这一份还没入库"摆到 B 面前。

    判据一个字都不在这里（唯一实现是 `vreceipts.registration_gap` /
    `vreceipts.ensure_registration` 与它们的幂等键 `b-register@<命题号>@<sha>`）。
    这一格只做两件事：认出"这一签的载体是不是 `reports/{f,b}-proof-…`"（不是就不开：
    那一档不在这一条义务的射程内），然后把读数带进返回值。失败不许带走这一签。

    三态：`checked` / `state`（`opened` / `existing` / `closed` / `cleared` / `expired` /
    `skipped` / `error`）/ `reason`；`skipped` 里 `code=not_a_proof_carrier` 说的是
    "这一签的稿不在这一条义务的射程内"，不是"已经收录了"。

    `skip_gap=True`（2026-11-08，V 的签后义务）：不读 `statements` 去判断"是不是已经收录了"。
    义务的存在与它是否已满足是两件事 —— V 只对手稿负责，签落成后就无条件开义务；
    "满足了没有"由 B 收录时消账、收工时 `sweep_registrations` 按盘上事实收口。

    默认 `False` 只服务历史直调（`sign_statement` 末尾那一支：兼容门，仍按 `statements`
    判"已收录"）；生产签后义务在 `land_sign_without_ledger` 里显式传 `skip_gap=True`。
    判据 `test_production_landing_does_not_rely_on_write_defaults` 逐条核这一格。
    """
    from . import vreceipts as _VRC

    out: dict[str, Any] = {"checked": False, "state": "skipped", "key": "", "item_id": "",
                           "owner": "", "owner_known": False, "code": "", "reason": ""}
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not rel:
        out.update(code="no_manuscript",
                   reason="这一签没有手稿载体 ⇒ 这一条义务不知道要收录哪一份（不是「已收录」）")
        return out
    if not any(rel.startswith(prefix) for prefix in _VRC.REGISTRATION_CARRIERS):
        out.update(code="not_a_proof_carrier",
                   reason=(f"`{rel}` 不是 `reports/{{f,b}}-proof-…` 那一类载体 "
                           f"{list(_VRC.REGISTRATION_CARRIERS)} ⇒ 不在这一条义务的射程内"))
        return out
    label = f"{str(statement_id or '')}#p{int(proof_no or 1)}"
    try:
        got = _VRC.ensure_registration(store=store, root=root, label=label,
                                       proof_sha=str(sha or ""), manuscript=rel,
                                       called_by="V", at=str(at or ""),
                                       skip_gap=bool(skip_gap))
    except Exception as exc:  # noqa: BLE001 —— 开义务失败不许带走这一签
        out.update(code="registration_raised",
                   reason=(f"开「必须收录」义务那一笔抛了（{type(exc).__name__}: {exc}）"
                           "⇒ 这一格没查成（收工扫盘会再试一次）"))
        return out
    out.update(dict(got))
    return out


def _vsigns_write_after_flip(store: Any, *, row: Mapping[str, Any], ledger: Path,
                             statement_id: str, proof_no: int, sha: str,
                             holds: Mapping[str, Any],
                             append_ledger: bool, by: str = "",
                             manuscript: str = "") -> dict[str, Any]:
    """翻位之后把签落成侧文件（「永不抛」：这一格的三态由调用方读）。

    为什么与落签拆成两步（2026-11-02 业主口径）：V 只颁发（`vsigns.issue`），
    手稿块与台账位由收方秘书落（`vsigns.land`，`by=` 只认 `secretary:F|B`）。
    本函数是 V 侧那一半的接线：颁发成功之后按 `by` 去落签；`by` 为空（直调 / 夹具 /
    V 的父角色读不到）⇒ 颁发照做（`written_by=sign_statement(direct)`），但落签会被
    受控拒绝 `not_a_secretary`，块不盖 —— 读数留在 `land` 那一格，不冒充"落成了"。

    返回 `issue` 的三态（`written` / `idempotent` / `conflict` / `archive_error` /
    `reason` / `path` / `sign` / `envelope`），外加 `land`（落签那一笔的读数）与
    `payload_problem`（组内容那一步的问题，空串 = 组得成）。
    """
    out: dict[str, Any] = {"written": False, "idempotent": False, "conflict": False,
                           "path": "", "archive_error": "", "reason": "",
                           "sign": {}, "payload_problem": "", "envelope": {},
                           "land": {}, "manuscript_write": {},
                           "refused_below_need": False}
    from . import vsigns as _VS

    root = getattr(store, "root", "")
    if isinstance(store, (str, Path)):
        root = str(store)
    need = int(holds.get("need") or SIGN_STREAK_NEED)
    # ---- 收方秘书是谁：调用方给了就用；没给就按这一趟的父角色现读（权威来源）----
    #
    # 为什么是 `current_parent()` 而不是"猜一个 F / B"：V 的 parent 就是"谁送审"，
    # 而收方秘书只能是那一位的秘书（业主 2026-11-02：父代理 = V 的 parent）。
    # 读不到（直调 / 夹具 / 没有挂点）⇒ 空串 = 没有收方秘书 ⇒ 能颁发、不能落块。
    who = str(by or "").strip()
    if not who:
        try:
            from . import conductor as _CND

            _pid, prole = _CND.current_parent()
            who = _VS.secretary_id(prole)
        except Exception:  # noqa: BLE001 —— 读不到父角色不是失败：就是"没有收方秘书"
            who = ""
    try:
        payload = _vsign_payload(root=root, ledger=ledger, statement_id=statement_id,
                                 proof_no=proof_no, sha=sha, need=need, holds=holds,
                                 manuscript=manuscript)
    except Exception as exc:  # noqa: BLE001 —— 组内容失败要留读数，但不许带走翻位
        out["payload_problem"] = f"{type(exc).__name__}: {exc}"
        payload = {"passes": [], "objections": [], "artifact_path": "", "ledger": "",
                   "at": S.now_iso()}
    try:
        got = _VS.issue(
            root, artifact_sha=sha,
            streak=int(holds.get("streak") or 0), need=need,
            artifact_path=str(payload.get("artifact_path") or ""),
            ledger=str(payload.get("ledger") or ""),
            statement_id=str(statement_id or ""), proof_no=int(proof_no),
            passes=list(payload.get("passes") or []),
            objections=list(payload.get("objections") or []),
            at=str(payload.get("at") or ""),
            by=who)
    except Exception as exc:  # noqa: BLE001 —— 写文件那一笔抛了也要如实报
        out["reason"] = f"颁发那一笔抛了（{type(exc).__name__}: {exc}）"
        return out
    out.update({k: got.get(k) for k in ("written", "idempotent", "conflict", "path",
                                        "archive_error", "reason", "sign", "envelope",
                                        "code", "refused_below_need")})
    if got.get("written") or got.get("idempotent"):
        try:
            landed = _VS.land(
                root, artifact_sha=sha, by=who,
                manuscript_path=str(payload.get("artifact_path") or ""),
                store=None, statement_id=str(statement_id or ""),
                proof_no=int(proof_no),
                # 台账位由外层事务（`sign_statement` 的 `store.tx`）落 —— 这里再落一次
                # 就是同一格两个写者（而且会重入同一把表锁）。
                ledger_bit=False)
        except Exception as exc:  # noqa: BLE001 —— 落签抛了也要如实报（签已经颁发了）
            landed = {"landed": False, "state": "refused", "reason": (
                f"落签那一笔抛了（{type(exc).__name__}: {exc}）"), "code": "land_raised"}
        out["land"] = dict(landed or {})
        out["manuscript_write"] = dict((landed or {}).get("manuscript_write") or {})
        if not (landed or {}).get("landed"):
            out["reason"] = (f"{out['reason']}；落签没成："
                             f"{str((landed or {}).get('reason') or '没有理由')}")
    if out["payload_problem"]:
        out["reason"] = (f"{out['reason']}；组签内容时有一格没读成"
                         f"（{out['payload_problem']}）")
    return out


def land_sign_without_ledger(store: Any, *, row: Mapping[str, Any],
                             within_call: int | None = None,
                             need: Any = None, review_call: str = "",
                             by: str = "", manuscript: str = "") -> dict[str, Any]:
    """颁签 + 落块，不碰 `statements`（2026-11-08，业主「V 只对手稿负责」）。

    这是 V 的在册送审在"三转 clean + 秘书判发"之后的落地那一步：
    - 写签的侧文件（`out/vsigns/<正文 sha>.json`，`vsigns.issue`）；
    - 让收方秘书把 `- V 签：` 九格块落回手稿（`vsigns.land`，`ledger_bit=False`）；
    - 给 B 开一条「必须收录」义务（`_registration_after_vsign`，签块落成才开）。

    不开 `store.tx("statements")`：不翻第 3 位、不写 `kind` / `grade` /
    `reviewed_by_proof`。那些是 B 收录时的活（业主：「第几份证明、什么等级都是 B 秘书
    录入时关心且需负责的」）。于是 `writeback["written"]` 恒为 False —— 它回答的是
    "命题位有没有被这一趟翻"，答案是没有；签有没有落地由 `sign_issued` /
    `manuscript_write` 两格回答（三态不许折平）。

    返回键：`written`（恒 False，命题位）/ `deferred_to="filing:B"` /
    `sign_issued` / `vsign` / `land` / `manuscript_write` / `registration` / `reason`。
    `written=False` 与 `sign_issued=False` 同时出现才是"这一签没落地"。
    """
    out: dict[str, Any] = {
        "written": False, "rolled_back": False, "deferred_to": "filing:B",
        "sign_issued": False, "append_state": "appended_by_caller",
        "vsign": {}, "land": {}, "manuscript_write": {}, "registration": {},
        "statement_id": str(row.get("stmt_id") or row.get("statement_id") or ""),
        "proof_no": 0, "proof_sha256": str(row.get("proof_sha256") or ""),
        "grade": "", "kind_upgrade": {}, "upgrade_note": "",
        "grade_recomputed": {}, "streak": 0, "need": int(SIGN_STREAK_NEED),
        "streak_ok": False, "reason": "",
    }
    row = dict(row or {})
    sid = str(out["statement_id"])
    if not sid:
        out["reason"] = ("没有命题号 ⇒ 这一签没有可写的台账锚点（不是「签上了」）")
        return out
    if not row_signable(row):
        out["reason"] = ("这一签签不住（verdict 不是「成立」，或有未解决的 error）"
                         "⇒ 不颁发、不落块")
        return out
    root = getattr(store, "root", "")
    if isinstance(store, (str, Path)):
        root = str(store)
    try:
        no = proof_no_of(row)
    except VerificationError:
        no = DEFAULT_PROOF_NO
    out["proof_no"] = int(no)
    n = int(need or SIGN_STREAK_NEED)
    if within_call is not None:
        holds: dict[str, Any] = {
            "checked": True, "streak": max(0, int(within_call)), "need": n,
            "streak_ok": bool(int(within_call) >= n),
            "sha": str(row.get("proof_sha256") or ""),
            "review_call": str(review_call or row.get("review_call") or ""),
            "legacy_rows": 0,
        }
    else:
        holds = consecutive_holds(root, sid, proof_no=no)
    out["streak"] = int(holds.get("streak") or 0)
    out["need"] = int(holds.get("need") or n)
    out["streak_ok"] = bool(holds.get("streak_ok"))
    try:
        ledger = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out["reason"] = f"{exc}；这一签没有可写的台账锚点"
        return out
    vsign = _vsigns_write_after_flip(
        root, row=row, ledger=ledger, statement_id=sid, proof_no=int(no),
        sha=str(row.get("proof_sha256") or ""), holds=holds,
        append_ledger=False, by=str(by or ""),
        manuscript=str(manuscript or row.get("manuscript") or ""))
    out["vsign"] = dict(vsign)
    out["sign_issued"] = bool(vsign.get("written") or vsign.get("idempotent"))
    out["manuscript_write"] = dict(vsign.get("manuscript_write") or {})
    out["land"] = dict(vsign.get("land") or {})
    if out["sign_issued"] and out["manuscript_write"].get("written"):
        out["reason"] = ("签已颁发并落回手稿；命题行的第 3 位与等级由 B 收录时"
                         "按正文 sha 认领/现算（V 不写 statements）")
    elif out["sign_issued"]:
        out["reason"] = (f"签已颁发（`{vsign.get('path') or '签文件'}`），但块没落："
                         f"{str(out['land'].get('reason') or vsign.get('reason') or '没有理由')}")
    else:
        out["reason"] = (f"颁发没成（`{vsign.get('path') or '签文件'}`）："
                         f"{str(vsign.get('reason') or '没有理由')}")
    out["registration"] = _registration_after_vsign(
        store=store, root=root, vsign=dict(vsign), statement_id=sid,
        proof_no=int(no), sha=str(row.get("proof_sha256") or ""), skip_gap=True)
    return out


def sign_statement(store: Any, *, row: Mapping[str, Any], proof_text: str,
                   path: Path | None = None, proof_no: Any = None,
                   sign_issuance: Mapping[str, Any] | None = None,
                   append_ledger: bool = True, by: str = "") -> dict[str, Any]:
    """把一签写回 `statements` 那一行里那一条证明的第 3 位（与台账同一次写）。

    ## 这一格为什么原来永远是 False
    第 3 位的唯一写者是 B 的 `register_statement`，而它按设计不替 V 签字（`BIT_OWNERS`：
    第 3 位的 owner 是 V）；V 自己的写口（本模块的 `record_verification`）当时只写台账
    那个文件，从来不碰 `statements`。于是"V 真的签了、台账上写着成立"与"命题那一行
    的 `reviewed` 位"之间没有连接：收工门的 R10 读位 ⇒ 恒 0。这一格就是那条断链的补口。

    ## 不借光（多证明模型）
    签名只翻被签的那一份（`proof_no`）的 `reviewed`；别的证明一个字不动。
    `proof_no > 1` 而命题行的证明清单里没有那一份 ⇒ 只落台账、不翻位（没有可翻的
    那一条证明），理由串写清 —— 不许把凭据记到 #p1 头上。

    ## 证明号：没给与给了坏值必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给 ⇒ 按这一行自己记的那一格（老行只有 `rev` 时由
    :func:`proof_no_of` 按正名读，兼容、不迁移）；给了但 :func:`proof_no_strict` 认不出
    ⇒ 不追加台账、不改位，`reason` 点名"证明号认不出"。改前写的是
    `as_proof_no(proof_no) or proof_no_of(row)`：0 被折成这一行自己的号，
    于是"号给错了"与"号没给"在台账上长得一模一样。

    ## 顺序与回滚（为什么不是纯原子事务）
    台账是追加式文件、`statements` 是快照 JSON，两者不可能进同一个事务。所以取这个顺序：
    ① 在 `statements` 的事务里（事务已持有该表锁 ⇒ 并发签同一行时"读-改-写"是原子的）
       先追加台账那一行；② 改内存里那一行（那条证明的 `reviewed=True` + 凭据换成本签）；
    ③ 提交。提交失败 ⇒ 把刚追加的那一行撤回（只撤我们自己的那一行），整笔"没发生"；
    撤回不了 ⇒ 留着台账行并如实报"位没写成"—— 签名确实发生过，抹掉它比留一条
    "位没跟上"更坏；而读侧（`review_standing`）按台账现算，所以断链不会因此复现。

    ## `before = -1` 不再兼任两义（2026-10-22 审计第 5 条）
    改前 `before` 既是"追加前的字节数"又是"到底试没试过追加"：追加本身失败时它还是 -1，
    于是理由串照样写"台账那一行留着（签名确实发生过）"—— 而盘上一个字节都没有。
    现在追加落在哪一态由 `append_state` 单独记（`not_attempted` / `appended` / `failed`），
    理由串据此分三句；`re_sign_required` 说清调用方是不是必须重签（只有"没落地"才要）。

    返回键：`written` / `reason` / `rolled_back` / `grade` / `statement_id` / `proof_no` /
    `proof_sha256` / `append_state` / `re_sign_required` / `kind_upgrade` / `upgrade_note` /
    `grade_recomputed` /
    `streak` / `need` / `streak_ok`（业主 2026-10-29 的连续读数；键集合固定 ——
    "这一格没有读数"与"这一格是 0"必须由键的存在区分开）。
    `written=False` 的四种来路各有
    理由串：签不住第 3 位（不改位）、连续次数不够（不改位）、秘书没发签（不改位）、
    命题不在册或那一份证明不在（没有可写的行）、
    追加失败（连台账那一行都没写）、事务失败（附回滚结果）。

    ## D-69：同一笔事务里把 `kind` 跟着这一签抬上去
    见 :func:`_kind_upgrade_from_signature`。它只改 `kind` 那一格（起点只认 `conjecture`），
    判不了就一个字节都不动；抬了的时候 `kind_upgrade` / `upgrade_note` 两格把依据
    （`verifications/<命题号>.jsonl#v-…`）写出来，读的人不用去翻台账才知道凭什么。

    ## 第 1、2 次只落台账、不翻位（业主 2026-10-29 的 A 段）
    这一签先追加进台账（那是正本），然后从台账现数尾部连续成立次数
    （:func:`consecutive_holds`，含刚追加的这一行）：数到 `SIGN_STREAK_NEED` 次才翻位，
    否则 `written=False` + 理由串点名"还差几次" —— 台账那一行照样在，
    `append_state="appended"`、`re_sign_required=False`（"次数不够"不是"没落地"）。
    计数放在追加之后、且只有这一处：`draft/124` §一② 点名的那种第二份账
    （"位上说签了、台账只签一次"）就是"行局部谓词自己数次数"长出来的。

    ## `sign_issuance`：秘书持有"发不发签"的决定（业主 2026-10-29）
    调用方问过秘书 ⇒ 把那份三态读数递进来（:meth:`Secretary.decide_sign_issuance` 的返回）。
    `checked` 为假（没缝 / 超时 / 台账读不成 / 没装配）或 `issue` 为假 ⇒ 不翻位，
    理由串逐字写出秘书那一句：`checked=False` 绝不被读成"没问题"
    （`draft/125` §三：装配没接上时秘书判定必须报 `checked=False`，且不放签）。
    `None` = 调用方没有问过秘书（老调用点 / 夹具 / 直接调本函数那一档）⇒ 只按连续闸判，
    这一档是兼容门，不是第二套判据。

    ## `sign_issuance.within_call`：单次送审内部的轮数（2026-11-02 定稿）
    这个键一旦给出（`AgentV` 的连判循环每一轮都会给"这一趟的第几轮"），本函数
    只看它：`>= need` 才翻位；台账尾部的历史连续数不参与判定（不现数、不二次确认）。
    这正是业主「不允许跨两次送审累计成功数」的落点 —— 旧后门是"台账已有 2 行 clean，
    本次第 1 轮 clean ⇒ 3 票凑够"。`streak` / `need` / `streak_ok` 三格与签文件里的
    `streak` 都取这个趟内数；签的 `passes` 按同一 `review_call` 取，绝不跨趟拼接。
    不给 `within_call` ⇒ 走历史兼容门（台账读数），那一档不是送审路径。

    ## `append_ledger=False`：台账那一行已经由调用方落了（业主 2026-10-29 追加口径）
    V 不再自己发签：`AgentV.verify_proof` 只落台账（`record_verification(flip=False)`），
    然后由 V 的秘书判定并调本函数翻位（`Secretary.decide_sign_issuance` 的落地那一步）。
    那时台账那一行已经在盘上（它是正本、先落），本函数只做"翻位"这一半 ⇒ `append_ledger=False`：
    不再追加（否则同一签在台账上出现两次），`append_state="appended_by_caller"`，
    异常分支也不撤回（不是我们追加的，没有可撤的）。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    # 证明号：调用方给的那个（`proof_no`）；没给就按这一行自己记的那一格 —— 老行只有
    # `rev` 时由 `proof_no_of` 按正名读（兼容，不迁移）。
    out: dict[str, Any] = {
        "written": False, "reason": "", "rolled_back": False, "grade": "",
        "statement_id": sid, "proof_no": None,
        "proof_sha256": str(row.get("proof_sha256") or ""),
        #: 台账那一行落在哪一态（三态，不许折平）：
        #: `not_attempted` = 这一支根本不追加（签不住第 3 位 / 号认不出）；
        #: `appended` = 真追加了一行（撤回与否另看 `rolled_back`）；`failed` = 追加本身失败；
        #: `appended_by_caller` = 调用方先落了那一行（`append_ledger=False`：V 的秘书那条路），
        #: 本函数只翻位、不撤回。
        "append_state": "not_attempted",
        #: 调用方是不是必须重签：只有"这一签没有落在台账上"（追加失败 / 已撤回）才为真。
        "re_sign_required": False,
        #: D-69：这一签有没有把 `kind` 抬上去（形状与秘书那一支的升档痕迹相同）：
        #: `{}` = 没抬（起点不是 conjecture / 凭据不够 / 位算不出来），那三档都不改盘。
        "kind_upgrade": {},
        #: 抬档的读数原话（「因 V 判成立而抬档：conjecture→theorem（依据 …）」）；
        #: 没抬时是空串。它不写进 `reason`：`reason` 只留"这一签没落成"的那几档。
        "upgrade_note": "",
        #: 档位回填（业主 2026-11-04）：这一签有没有把 `evidence_kind` 按现行签重算上去。
        #: `{}` = 没动（已经是那一档 / 凭据不够 / 那一刻不适用），那几档都不改盘；
        #: 非空时形状见 `_grade_recomputed_from_signature` 的 `reading`。
        "grade_recomputed": {},
        #: 连续读数（见 :func:`consecutive_holds`）：给了 `sign_issuance.within_call`
        #: 时是这一趟送审内的轮数（2026-11-02 定稿）；不给时是台账尾部连续成立次数
        #: （历史兼容门）。三个键无条件存在。
        "streak": 0, "need": SIGN_STREAK_NEED, "streak_ok": False,
        #: 业主 2026-11-01：这一签的侧文件（`out/vsigns/<artifact_sha>.json`）落成了没有。
        #: 三态与 `vsigns.write_sign` 同形：`written` / `idempotent` / `conflict` /
        #: `archive_error`（归档失败不回滚）/ `reason` / `path`。签文件写不成时本函数
        #: 整笔失败（位也不会翻），所以"`written=True` 而 `vsign.written=False`"只可能
        #: 是"这一份签早就在盘上、逐字相同"（`idempotent`）这一档。
        "vsign": {},
        #: 2026-11-03（件二）：翻位前那道正文闸的读数 —— `matched` / `missing_body` /
        #: `sha_mismatch`。空串 = 还没走到那道闸（前面的分支已经返回）。
        "body_gate": "",
    }
    try:
        no = proof_no_of(row) if proof_no is None else proof_no_strict(proof_no)
    except VerificationError as exc:
        out.update(re_sign_required=True,
                   reason=(f"{exc}；第 3 位一个字没动，台账里也没有这一签"))
        return out
    out["proof_no"] = no
    if not row_signable(row):
        out["reason"] = ("这一签签不住第 3 位（verdict 不是「成立」，或有未解决的 error）"
                         "⇒ 位不动：没签住的字不该改任何读数")
        return out
    ledger = path or verification_ledger_path(store.root, sid)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    append_state = "not_attempted"
    #: 追加前的字节数（只有 `append_state == "appended"` 时才有意义，撤回按它截断）。
    before = -1
    try:
        with store.tx("statements", actor=f"verifier-{row.get('verifier') or 'V'}",
                      note=f"verify.sign:{sid}#p{no}") as tx:
            # 按号定位走查口（口径一）；快照传 `tx`（同一个 `rows(table)` 协议）。
            # 锁内读失败仍照旧抛出（查口把异常收成 checked=False → 这里翻回一次抛出，
            # 否则「读不到」会被下面读成「没有这一行」）。
            by_id = SL.by_id(tx, stmt_id=sid)
            if not by_id["checked"]:
                err = by_id.get("error") or {}
                raise RuntimeError(f"`statements` 读不出来（{err.get('type') or '?'}: "
                                   f"{err.get('message') or by_id.get('reason') or '?'}）")
            found = by_id["row"] if by_id["found"] else None
            if not append_ledger:
                # 台账那一行是调用方先落的（V 的秘书那条路）：这里一个字都不追加。
                append_state = "appended_by_caller"
                out["append_state"] = append_state
            else:
                try:
                    before = _append_verification(ledger, row)
                except OSError:
                    # 追加本身失败：记下这一态再往外抛（理由串要据此说"整笔没发生"，
                    # 不许说"签名确实发生过"）。
                    append_state = "failed"
                    raise
                append_state = "appended"
                out["append_state"] = append_state
            if found is None:
                out["reason"] = (f"`statements` 里没有命题 {sid} ⇒ 只落了台账（签名）那一行，"
                                 "第 3 位没有可写的行")
                return out
            if no > 1 and no not in {n for n, _ in proof_list(found)}:
                out["reason"] = (f"命题 {sid} 的证明清单里没有 #{no}（`{PROOFS_KEY}` 那一条）"
                                 "⇒ 只落了台账那一行；第 3 位不翻（不许把这一签记到 #p1 头上）")
                return out
            # ---- 业主 2026-10-29：连续 N 次成立才翻位（第 1、2 次只落台账）----
            #
            # 2026-11-02 定稿：`sign_issuance.within_call` 一旦给出，只看这一趟送审
            # 内部的轮数，台账尾部历史连续数一个字节都不参与"发不发签"的判断
            # （业主：「不允许跨两次送审累计成功数」；后门是"2 行历史 clean + 本次第 1 轮"）。
            # `within_call` 是 `Secretary.decide_sign_issuance` 从 `AgentV` 那趟循环
            # 拿到的、已经按趟数过的数；这里不再现数台账，也不拿台账做二次确认。
            # 不给它（旧直调路径 / 夹具 / `record_verification(flip=True)`）⇒ 仍按台账
            # 读数走，那是历史兼容门，不是送审路径。
            within_call: int | None = None
            if sign_issuance is not None and sign_issuance.get("within_call") is not None:
                try:
                    within_call = int(sign_issuance.get("within_call"))
                except (TypeError, ValueError):
                    within_call = None
            if within_call is not None:
                need = int(sign_issuance.get("need") or SIGN_STREAK_NEED)
                holds = {
                    "checked": True,
                    "streak": within_call, "need": need,
                    "streak_ok": bool(within_call >= need),
                    "sha": str(row.get("proof_sha256") or ""),
                    # 让 `_vsign_payload` 按同一趟送审取 `passes`（不按台账尾部回捞）。
                    "review_call": str(sign_issuance.get("review_call")
                                       or row.get("review_call") or ""),
                    "legacy_rows": 0,
                }
            else:
                # 历史 / 直调路径：现读台账（含刚追加的这一行）——这是旧"连续次数"的
                # 唯一来路；不在这里另存一份计数、也不许把一个整数从调用方传进来：
                # 位是台账的缓存，缓存只能从正本现算。
                holds = consecutive_holds(getattr(store, "root", ""), sid, proof_no=no)
            out["streak"] = int(holds.get("streak") or 0)
            out["need"] = int(holds.get("need") or SIGN_STREAK_NEED)
            out["streak_ok"] = bool(holds.get("streak_ok"))
            if sign_issuance is not None and not (
                    bool(sign_issuance.get("checked")) and bool(sign_issuance.get("issue"))):
                # 秘书没有发签（没缝 / 超时 / 台账读不成 / 它自己判了不发）。
                # 这一档与"次数不够"必须分开说：前者是"没有人发这一签"，后者是"还差几次"。
                out["reason"] = ("秘书没有发这一签（"
                                 + ("checked=False："
                                    if not bool(sign_issuance.get("checked")) else "")
                                 + f"{str(sign_issuance.get('reason') or '没有给理由')}）"
                                 "⇒ 只落了台账那一行，第 3 位不翻")
                return out
            if not signs_bit3(row, streak=holds):
                out["reason"] = (f"连续「成立」{out['streak']}/{out['need']} 次"
                                 f"（同一份正文 sha {str(row.get('proof_sha256') or '')[:12]}…）"
                                 "⇒ 还差次数：只落了台账那一行，第 3 位不翻"
                                 "（连续 3 次没问题才发签）")
                return out
            # ---- 2026-11-03（件二）：翻位前必须核"这一份正文存在，且就是签覆盖的那一份" ----
            #
            # 86 的现场：`stmt:000013` 的 `proof_text` 是空串（B 先按"不带正文"拿号，
            # 正文等 V 签完再登记），而 V 的秘书按 `row.proof_sha256=ed35…` 调本函数 ⇒
            # 改前这里不看命题行有没有正文，直接把 `reviewed_by_proof["1"]` 写成 true。
            # 于是"没有正文（也就没有正文 sha）"被读成"第 1 份已签"。
            #
            # 判据（业主 2026-11-03）：第 3 位翻真要求"该份正文存在，且它的 sha 与这一签
            # 覆盖的 sha 相同"。两条缺一 ⇒ 位不翻，理由串点名缺哪一条 —— 不静默跳过，
            # 也不拿"签过了"冒充"命题行里有这一份"。
            #
            # 但"位不翻"不等于"签不颁"：两阶段录入是 B 先拿号、V 先签、B 再把正文写进
            # 命题行（2026-11-02 口径），B 靠 `out/vsigns/<正文 sha>.json` 按 sha 认领。
            # 所以下面仍调 `_vsigns_write_after_flip`（写签文件 + 落手稿块），只是跳过
            # `_reviewed_statement_row`/`tx.upsert` 那一半。
            body_in_row = proof_text_of(found, no)
            signed_sha = str(row.get("proof_sha256") or "")
            body_gate = "matched"
            if not str(body_in_row or "").strip():
                body_gate = "missing_body"
                out["reason"] = (
                    f"命题 {sid} 的第 {no} 份证明没有正文（`proof_text` / `{PROOFS_KEY}` 都读不到）"
                    " ⇒ 这一签没有可盖的正文：第 3 位不翻（`reviewed_by_proof` 不写这一份），"
                    "签照旧颁发，等 B 把正文写进命题行之后按正文 sha 认领")
            else:
                body_sha = proof_sha(str(body_in_row))
                if not signed_sha or body_sha != signed_sha:
                    body_gate = "sha_mismatch"
                    out["reason"] = (
                        f"命题 {sid} 的第 {no} 份证明正文 sha {body_sha[:12]}… 与这一签覆盖的 "
                        f"sha {signed_sha[:12] or '（空）'}… 不符 ⇒ 第 3 位不翻"
                        "（签的不是现在这一份正文）；签照旧颁发，等正文换过来之后按 sha 认领")
            out["body_gate"] = body_gate
            if body_gate == "matched":
                new = _reviewed_statement_row(found, row, proof_text=proof_text, proof_no=no,
                                              streak=holds)
                # ---- D-69：V 判「成立」⇒ 同一笔事务里按证据位把 `kind` 现算一遍。
                #
                # 位置在"位已经翻上去"之后、`tx.upsert` 之前：台账那一行刚追加进
                # `verifications/<号>.jsonl`，`kind_following_grade` 现在读得到那一签；
                # 判不了（`held` / `unreadable`）就原样不动（三态：不抬，也不降）。
                upgraded = _kind_upgrade_from_signature(
                    new, root=getattr(store, "root", ""), verifier=f"verifier-{no}")
                new = upgraded["row"]
                # ---- 等级现算（2026-11-05 改口径）：只算等级、不再写档位 --------------
                #
                # 位置与 D-69 那一格并列、`tx.upsert` 之前：台账那一行刚追加进
                # `verifications/<号>.jsonl`，`proof_review_gap` 现在读得到它。
                # 这一格只把"按现行签现算的等级 + 凭什么"写进回执（`GRADE_RECOMPUTED_KEY`）；
                # `evidence_kind` 一个字不动 —— 它只是历史列，判定面读等级。
                recomputed = _grade_recomputed_from_signature(
                    new, root=getattr(store, "root", ""), proof_no=no)
                if recomputed["reading"]:
                    # 2026-11-06：这一格不只算等级，还会按穷举通道落第 1 位
                    # （`numeric=verified`）—— 那一份 `row` 必须一起落盘，否则
                    # "算过 theorem"只活在返回值里，盘上仍是 pre_theorem。
                    new = dict(recomputed.get("row") or new)
                    new[GRADE_RECOMPUTED_KEY] = dict(recomputed["reading"])
                tx.upsert("statements", new, note=f"verify.sign:{sid}#p{no}")
                out.update(written=True, grade=str((new.get("bits") or {}).get("grade") or ""),
                           kind_upgrade=dict(upgraded["kind_upgrade"]),
                           upgrade_note=str(upgraded["note"]),
                           grade_recomputed=dict(recomputed["reading"]))
            # ---- 业主 2026-11-01：签落成一份按正文 sha 命名的侧文件 -------------------
            #
            # 位置在这里（upsert 之后、事务里）的三个理由：
            # ① 位与签同生共死：`<sha>.json` 写不成 ⇒ 抛出去让整个事务回滚（连同台账那
            #    一行一起撤回）——"签没落地"与"签落了但没档"是两件事，前者要能重试；
            # ② 归档（`issued.json`）失败「不许」回滚：位已经翻在 `statements` 里，
            #    删掉刚写好的签文件是抹掉发生过的事（`vsigns` 的模块 docstring 那一节）；
            # ③ 内容全部从台账现读（`_vsign_payload`），不复制全文、不吃调用方状态。
            sign_out = _vsigns_write_after_flip(
                store, row=dict(row), ledger=ledger, statement_id=sid, proof_no=no,
                sha=str(row.get("proof_sha256") or ""), holds=holds,
                append_ledger=bool(append_ledger), by=str(by or ""),
                # 2026-11-04（甲）：载体随台账行来（`record_verification(manuscript=…)`）。
                manuscript=str(row.get("manuscript") or ""))
            out["vsign"] = dict(sign_out)
            if not (sign_out.get("written") or sign_out.get("idempotent")):
                if sign_out.get("refused_below_need"):
                    # 两道守卫不一致（`signs_bit3` 说够、`write_sign` 说不够）：位照它自己的
                    # 判据翻，「不写签」，并把这件事留在 `vsign.reason` 里。
                    #
                    # 为什么这一档不许把整笔弄失败：`signs_bit3` 是第 3 位的「唯一」硬闸
                    # （`tests/test_v_sign_gate_streak.py::z1` 用"把 `streak_ok` 打成恒真"
                    # 做反真空负控）。若这里改成抛异常回滚，那道闸就再也量不出来了 ——
                    # 一条"签没写"的读数是可见的，而一条"闸拆了也看不出来"的判据是不可修的。
                    out["vsign"]["reason"] = str(sign_out.get("reason") or "")
                else:
                    # 签文件没落地（写不成 / 冲突）⇒ 整笔失败（位不许在"没有任何档"的情况下翻上去）。
                    raise VerificationError(
                        "签文件没写成：" + str(sign_out.get("reason") or "没有理由"))
    except Exception as exc:  # noqa: BLE001 - 写位失败要如实报（签名那一行可能已经在盘上了）
        rolled = (_rollback_append(ledger, before, row)
                  if append_state == "appended" and before >= 0 else False)
        if append_state == "failed":
            reason = (f"台账那一行也没写成（{type(exc).__name__}: {exc}）⇒ 第 3 位没写成，"
                      "整笔没发生（可以重试；必须重签）")
        elif rolled:
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行已撤回（整笔没发生，可以重试）⇒ 必须重签")
        elif append_state in ("appended", "appended_by_caller"):
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行留着（签名确实发生过）；读侧按台账现算，不按这一位")
        else:
            # 连追加都没走到（例如事务加锁失败）：台账里没有这一签，整笔没发生。
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行没有追加（整笔没发生）⇒ 必须重签")
        out.update(
            written=False, rolled_back=bool(rolled), append_state=append_state,
            re_sign_required=(not rolled
                              and append_state not in ("appended", "appended_by_caller")),
            reason=reason)
    # ---- 缺陷 B（2026-11-05）：签发落成之后，给 B 开一条「必须收录」义务 ----
    #
    # 位置在事务之外（理由见 `_registration_after_vsign`：事务里开板项会撞锁）。
    # 87 的现场：`reports/f-proof-000000.md` 上有成立的签，而 `statements:000000` 仍是
    # 「正文=0 / reviewed=false」—— 签发之后没有任何东西把"这一份还没入库"摆到 B 面前
    # （D 从头没派 B 收录；B 在 87 里只被派过 1 次，还是文献侧的 `t-000027`）。
    out["registration"] = _registration_after_vsign(
        store=store, root=getattr(store, "root", ""), vsign=dict(out.get("vsign") or {}),
        statement_id=sid, proof_no=int(no),
        sha=str(row.get("proof_sha256") or ""))
    return out


def _superseded_reading(row: Mapping[str, Any], *, streak: Any = None) -> dict[str, Any]:
    """一条被更近的签盖过去的旧签（`review_standing` 的 `superseded` 元素）。

    它回答"这一份正文以前还被谁签过、签的是哪一版、结论是什么"：旧签仍然可见，
    但判定只看最近那一签（:func:`review_standing`）。字段刻意只留定位用的几格，
    正文与 findings 不回放 —— 那些在台账文件里逐字可查，读数层不复制历史。

    `verdict` 按两态读（:func:`read_verdict`）：老行上的 `看不出来` 在这里报 `成立`
    （2026-11-02：那一档连历史兼容读也不留）；逐字原话仍去台账文件里读。

    `signed_bit3` 是那一签当年的读数：`streak` 由调用方按"到这一行为止的连续次数"
    递进来（:func:`_hold_run_lengths` 的分组读数）——旧签也要过同一道连续闸，
    否则"当年签住了"会把一条只有 1 票的旧签说成签过。
    """
    return {
        "verification_id": str(row.get("verification_id") or ""),
        "verdict": read_verdict(row),
        "round": row.get("round"),
        "at": str(row.get("at") or ""),
        "proof_no": proof_no_of(row),
        "proof_sha256": str(row.get("proof_sha256") or ""),
        "signed_bit3": signs_bit3(row, streak=streak),
        "unresolved_errors": int(row.get("unresolved_errors") or 0),
        "why": str(row.get("why") or "")[:200],
    }


def review_standing(root: str | Path, *, statement_id: str, proof_text: str,
                    proof_no: int = 1) -> dict[str, Any]:
    """一条证明的第 3 位相对「它现在这一份正文」的读数（唯一判定口，纯读）。

    ## 判据（业主 2026-10-22 多证明模型）
    只看 `proof_no` 这一份证明的现行正文的 sha：同一份正文上按台账行序取最近那一签，
    它签住了 ⇒ `signed`；最近那一签的结论不是「成立」⇒ `rejected`；签的是旧版 ⇒
    `stale`（R10 不计，单列 `proofs_stale`）；这一份一次都没签 ⇒ `unsigned`（哪怕同一条
    命题的别的证明签过 —— 不许借光）；台账读不出来 ⇒ `unreadable`（没查成，不是通过）。
    更早的签不改判定，只进 `superseded`（仍可见：id / verdict / 那一签盖住的 sha）。

    ## 最近一签为什么必须能否决（2026-10-22 审计的第 3 条）
    改前先挑出有「成立」的那几签再取最后一条，于是"先成立、后改判有毛病"永远读回
    `signed`：后一次否决投不出去，旧的那一签被当成了免死金牌。改后同一份正文的覆盖集里
    只有最后那一签说了算；更早的签降为历史读数。
    "旧签名是历史，不是否决票"仍然成立，但它的方向被限定为：旧版上的结论（包括
    「有毛病」）不否决现行这一份上的「成立」那一签（哈希只回答"这份稿在你签完之后有没有
    被改过"）；反过来，同一份正文上更新的否决必须盖过更早的成立。

    ## 哈希在这里的角色：读数，不是授权
    `stale` 与 `rejected` 都不拦任何写入（见 :func:`proof_review_gaps`），它们只让第 3 位
    不计入、并各自有一个可读的理由。返回键：`checked` / `state` / `ok` / `in_sync` /
    `ledger_present` / `statement_id` / `proof_no` / `sha` / `verification_id` / `verdict` /
    `round` / `unresolved_errors` / `rows`（这条命题的台账总行数）/ `proof_rows`（本份
    证明的行数）/ `superseded` / `superseded_total` / `problems` / `ledger` / `why` /
    `streak` / `need` / `streak_ok`（业主 2026-10-29 的连续读数）/ `legacy_rows`
    （历史形态的行数，2026-11-02：只作历史台账读数，不参与新签判断）。

    ## 「连续 3 次」在这一格怎么读（业主 2026-10-29 的 A 段）
    `state="signed"` 的条件从"最近一签是成立"改成"尾部连续 `SIGN_STREAK_NEED` 签成立
    且同一份正文"：`streak` / `need` / `streak_ok` 三格把这件事逐字报出来。签过、判成立、
    但次数还没到 ⇒ `state="holding"`（不是 `signed`，也不是"一次都没签"）。计数只调
    :func:`_hold_run_lengths`（不重复读盘：这里的 `mine` 就是它要的那批行），
    行长与"哪一签算第几票"因此与 :func:`consecutive_holds` 逐字一致。

    ## 历史形态与"新签"分开（2026-11-02，业主定稿）
    上面这段说的是台账历史读数：它回答"以前发生过什么"，旧工作区的 `state` 仍照它读。
    但"新签发不发"不再看它 —— 新签只看同一趟 `verify_proof` 内 `review_pass=1..need`
    的那几行（`sign_issuance.within_call`）。没有 `review_call` / `review_pass` 的行
    由 `legacy_rows` 显式数出来，不参与新签判断，也不按新规则重算成签。

    ## 历史行 `verdict="看不出来"` 怎么读（2026-11-02：这一档连历史兼容读也不留）
    按 :func:`read_verdict` 读成 `成立` ⇒ 它走上面同一条路（同一份正文 ⇒ `signed` /
    `holding`，并投"连续成立"那一票），没有"历史行"那一条支了。改前它读成 `rejected`
    并附一句"只作兼容读：既不算票、也不清零"（宽容方向：老行既不算通过、也不算失败），
    那条历史支已整段删掉（连函数一起）。

    ## 证明号认不出 ⇒ `unreadable`，不折成 `#p1`（2026-10-22 收尾）
    `proof_no` 问的是"要看哪一份证明"，所以没给（`None` / 空串）才是 canonical；给了但
    :func:`as_proof_no` 认不出（`0` / `'abc'` / `2.0`）⇒ 返回 `checked=False`、
    `state="unreadable"`、`proof_no=0`，`why` 逐字点名"证明号认不出"。改前是
    `as_proof_no(proof_no) or 1`：一个坏号拿到的是 `#p1` 的读数，而读的人看不出号给错了
    （同样的折平还在 :func:`proof_text_of` / :func:`proof_label` 里，三处一起改的）。
    这一档是"没查成"（问的是哪一份都没有答案），不是"查过了、没签过"。
    """
    sid = str(statement_id or "").strip()
    no = _read_proof_no(proof_no)
    sha = proof_sha(proof_text)
    out: dict[str, Any] = {
        "checked": False, "state": "unsigned", "ok": False, "in_sync": None,
        "ledger_present": False, "statement_id": sid, "proof_no": no, "sha": sha,
        "verification_id": "", "verdict": "", "round": None,
        "unresolved_errors": 0, "rows": 0, "proof_rows": 0, "problems": [],
        "superseded": [], "superseded_total": 0,
        #: 连续读数（业主 2026-10-29）：三个键无条件存在（"这一格是 0"与"没有这一格"
        #: 必须靠键的存在分开）。读不成 / 没有那一行时它们是 0 / 3 / False。
        "streak": 0, "need": int(SIGN_STREAK_NEED), "streak_ok": False,
        #: 历史形态的行数（2026-11-02）：没有 `review_call` / `review_pass` 的行。
        #: 它们只作历史台账读数，不参与新签判断；见 :func:`_is_legacy_row`。
        "legacy_rows": 0,
        "ledger": "", "why": "",
    }
    if no < 1:
        # 证明号认不出 ⇒ "问的是哪一份"没有答案。这是"没查成"，不是"没签过"（三态纪律），
        # 也不许悄悄按 canonical 读：改前 `as_proof_no(proof_no) or 1` 会把它读成 `#p1`，
        # 于是"号给错了"的读数与"我要 #p1"逐字相同。
        out.update(
            checked=False, state="unreadable",
            why=(f"证明号认不出：收到 {proof_no!r}（合法写法是 1、2、3 … 或 "
                 "'2' / 'p2' / '#p2'）⇒ 不知道问的是哪一份证明，这一格没查成"
                 "（不是「没签过」，也不是「签过过期」）；读侧不把它折成 canonical（#p1）"))
        return out
    if not sid:
        out.update(checked=True, why="没有命题号 ⇒ 查不到台账（不是没签过）")
        return out
    try:
        path = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out.update(checked=True, why=f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到台账")
        return out
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    out["ledger_present"] = path.is_file()
    if not out["ledger_present"]:
        out.update(checked=True,
                   why=f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有（不是签过过期）")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        out.update(state="unreadable",
                   why=(f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                        "第 3 位没查成（不是「没签过」，也不是「签过过期」）"))
        return out
    out["checked"] = True
    if not str(proof_text or "").strip():
        # 空正文不是"签过过期"：没有被审的对象，「签没签过」这件事无从谈起。
        out.update(why=(f"{proof_label(sid, no)} 的正文是空的 ⇒ 没有被审的那一份，"
                        "这一格既不是「签过」也不是「签过过期」"))
        return out
    mine = [r for r in rows if proof_no_of(r) == no]
    out["proof_rows"] = len(mine)
    out["legacy_rows"] = sum(1 for r in mine if _is_legacy_row(r))
    if not mine:
        out.update(why=(f"`{out['ledger']}` 里没有 #{no} 这一份证明的签"
                        "（别的证明签过也不算 —— 不许借光）"))
        return out
    covering = [r for r in mine if str(r.get("proof_sha256") or "") == sha]
    # ---- 最近一签的判据（2026-10-22 审计后）：同一份正文上按台账行序取最后那一签。
    #
    # 改前这里先挑 `signed`（有「成立」的签）再取它的最后一条，于是"先成立、后改判有毛病"
    # 永远读成 signed —— 后一次否决投不出去，旧的那一签被当成了免死金牌。改后：在同一份
    # 正文的覆盖集里，最后那一签说了算；更早的签只留在 `superseded` 里可见，不参与判定。
    # 签名行本身是追加式的（台账不改历史），所以"最近"就是读出来的行序（`at` / `round`
    # 只做展示；时钟回拨不会把判定翻回去）。
    chosen = covering[-1] if covering else mine[-1]
    cut = next((i for i, r in enumerate(mine) if r is chosen), len(mine) - 1)
    superseded = mine[:cut]
    # ---- 连续读数（业主 2026-10-29）：逐行的"到这一行为止连续几次成立"。
    #
    # `runs[-1]` 是本份证明现在的连续次数（尾部那一签数到几），`runs[cut]` 是
    # "被选中那一签当年算第几票"—— 判定用的是后者：`chosen` 未必是尾行
    # （F 改了正文、而更早的几签盖着现行 sha 时就是那种情形），拿尾行的票数去判
    # 一个更早的签会把它说成它没达到过的次数。
    runs, runs_void = _hold_runs(mine)
    chosen_run = runs[cut] if 0 <= cut < len(runs) else 0
    out.update({
        "streak": int(runs[-1] if runs else 0),
        "need": int(SIGN_STREAK_NEED),
        "streak_ok": bool(runs and runs[-1] >= SIGN_STREAK_NEED),
        "verification_id": str(chosen.get("verification_id") or ""),
        #: 结论按两态读（:func:`read_verdict`）：老行上的 `看不出来` 在这里就是 `成立`。
        "verdict": read_verdict(chosen),
        "round": chosen.get("round"),
        "unresolved_errors": int(chosen.get("unresolved_errors") or 0),
        #: 被这一签盖过去的旧签（仍可见、不参与判定）：按台账行序，逐条给 id / verdict /
        #: 那一签盖住的 sha。它是"旧签降为历史"的唯一读数格。
        "superseded": [_superseded_reading(r, streak=runs[i])
                       for i, r in enumerate(superseded)],
        "superseded_total": len(superseded),
        #: I10 硬禁令在这一签上的机械命中（2026-10-27，只报不判）：这一格不参与
        #: `state` / `ok` / `in_sync` 中的任何一个 —— 它只是让"这一签盖过的正文里有
        #: 「易证/显然」"这件事可见。老行没有这一格 ⇒ 空列表。
        "hard_ban_markers": [str(m) for m in (chosen.get("hard_ban_markers") or [])],
        #: 秘书对这段回复的语义判定（业主 2026-10-29 第 5 轮）：`fault` 是"V 的结论词写
        #: 成立、但秘书读出来它其实指出了缺陷"那一档。它不改六态词表（`state` 仍 `holding`，
        #: 因为 R10 与收工门共读那个词表），只让这件事在读数里说得出来 ——
        #: 否则读的人会把 `holding` 的"还差 3 次"当成"还没评够"，而实际是"被读出了缺陷"。
        #: 2026-11-02 起这里是 :func:`secretary_axis` 的读法（只有 clean / fault 两格）：
        #: 老行上那个已取消的轴名读出来是空串（"这一行没有轴"），不再在读数里冒充一格。
        "secretary_axis": ledger_axis(chosen),
        "secretary_fault": (ledger_axis(chosen) == "fault"),
        #: 这一转的秘书判定是"判过了"还是"没判成"（业主 2026-10-30）：读侧要拿它把
        #: "没查成"与"判过了"分开（见 :func:`secretary_judged` / :func:`secretary_unjudged`）。
        "secretary_judged": secretary_judged(chosen),
        "secretary_unjudged": secretary_unjudged(chosen),
    })
    if covering and 0 <= cut < len(runs_void) and runs_void[cut]:
        # ---- 2026-11-06（业主裁定 3 的准确含义）：这一签落在"打回之后又起转"的那一趟上 --
        #
        # 真机 `R-mk-infinite-94` 的 000034：v2 判 fault（打回），同一次送审本该到此为止；
        # 而 v3–v5 是同一份正文（同一个 sha）重开的一趟，三转 clean 之后签了、签块写
        # "连续=3/3"。业主逐字：「第 2 转判 fault 时就该打回，根本不该有第 3、4、5 转」。
        # 所以读侧按新口径把那些行判成作废（:func:`_hold_runs` 的 `void`），这一份正文
        # 仍是打回状态、连续数 0：不许把"打回之后又起转"读成"另一次送审攒够了"。
        objection = ""
        obj_i = -1
        for i in range(min(cut, len(mine)) - 1, -1, -1):
            if (str(mine[i].get("proof_sha256") or "") == sha
                    and ledger_axis(mine[i]) == "fault"):
                objection = str(mine[i].get("verification_id") or "")
                obj_i = i
                break
        out.update(
            state="rejected", in_sync=False,
            #: 定位那几格指回打回那一行（不是指回那一条作废的 clean 行）：
            #: 读 `verification_id` 的人要能找到"凭什么打回"，而不是一条不作数的签。
            verification_id=(objection or str(chosen.get("verification_id") or "")),
            round=(mine[obj_i].get("round") if obj_i >= 0 else chosen.get("round")),
            verdict=(read_verdict(mine[obj_i]) if obj_i >= 0 else read_verdict(chosen)),
            unresolved_errors=int((mine[obj_i].get("unresolved_errors") or 0)
                                  if obj_i >= 0 else 0),
            secretary_axis="fault" if obj_i >= 0 else ledger_axis(chosen),
            secretary_fault=True if obj_i >= 0 else bool(out.get("secretary_fault")),
            why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                 f"{str(chosen.get('verification_id') or '（没有号）')}，它落在「被打回之后"
                 f"又起转」的那一趟送审上 ⇒ 这一签不作数（同一份正文不重复判、跨送审不累计）；"
                 f"这一份仍是打回状态"
                 + (f"（打回在 {objection}）" if objection else "")
                 + "：按缺陷改稿之后再送，下一次送审从 0 起数"))
        return out
    if covering and signs_bit3(chosen, streak=chosen_run):
        out.update(state="signed", ok=True, in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）连续 "
                        f"{chosen_run}/{SIGN_STREAK_NEED} 签「成立」，最近一签是"
                        f"{out['verification_id']}（{out['ledger']}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史"
                           "（见 superseded，不参与判定）" if superseded else "")))
        return out
    if covering and row_signable(chosen) and not signs_bit3(chosen, streak=chosen_run):
        # 签过、判成立、签的也是现行这一份 —— 就是次数没到（业主 2026-10-29）。
        out.update(state="holding", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）已连续 "
                        f"{chosen_run}/{SIGN_STREAK_NEED} 签「成立」（最近一签 "
                        f"{out['verification_id']}，{out['ledger']}）⇒ 还差 "
                        f"{SIGN_STREAK_NEED - chosen_run} 次才发签：台账有行、第 3 位没翻"
                        + ("；但秘书读出了缺陷（它判 fault：V 的结论词虽写「成立」，"
                           "回复里其实指出了问题）—— 这一份要按缺陷处理，"
                           "别把「还差几次」当成「还没评够」"
                           if out.get("secretary_fault") else "")
                        + ("；而这一转秘书没判成（checked=False：没查成，不是有毛病）"
                           "—— 这一签不发，等判定接上之后重签"
                           if out.get("secretary_unjudged") else "")))
        return out
    if covering and ledger_axis(chosen) == "fault":
        out.update(state="rejected", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                        f"{out['verification_id']}：秘书语义判定轴=fault ⇒ 这一份要打回，"
                        f"按缺陷处理（V 写下的陈述：{out['verdict']!r}；"
                        f"unresolved_errors={out['unresolved_errors']}；"
                        f"why：{str(chosen.get('why') or '')[:120]}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史（见 superseded），"
                           "不能把它翻回「成立」" if superseded else "")))
        return out
    if covering:
        # 轴不是 fault、但这一行也没签成：clean 但次数没到 / 机械闸挡签 / 这一问没判成
        # （checked=False）/ 没有轴（老行）。p247 起这里不再按 `verdict` 的字面判"打回"：
        # 只有秘书判 fault 才是打回（上一支），其余一律是"这一签不发"。
        out.update(state="holding", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                        f"{out['verification_id']}（V 写下的陈述：{out['verdict']!r} —— "
                        "复核过、这一签不发）"
                        + ("；秘书没判成（checked=False：没查成，不是有毛病）"
                           if out.get("secretary_unjudged") else "")
                        + ("；这一行没有秘书轴（老行 / 没判过）⇒ 不算票、不签发"
                           if not out.get("secretary_axis") else "")))
        return out
    out.update(state="stale", in_sync=False,
               why=(f"`{out['ledger']}` 里 {proof_label(sid, no)} 有 {len(mine)} 签，"
                    f"但没有一签盖住它现在这一份：最近一签 {out['verification_id']} 签的是"
                    f"另一版（台账 sha256={str(chosen.get('proof_sha256') or '')[:12]}…，"
                    f"现行这一份={sha[:12]}…）⇒ 待复核（stale）：第 3 位不计，"
                    "等 V 对现在这一份重签"))
    return out


def statement_review_reading(root: str | Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """一条命题在「多证明」模型下的第 3 位读数（纯读，逐条证明分开）。

    ## 为什么命题级读数不能只有一个布尔
    多证明模型（业主 2026-10-22）里，每条证明各自有第 3 位：`#p1` 签过不等于 `#p2`
    签过（不许借光），`#p2` 签过也不等于 `#p1` 签过。命题级要回答的是"这条定理有没有
    一份被审过的证明"，所以它是逐条读数的汇总，而逐条读数各自独立。

    返回键：
    - `proofs`: `[{proof_no, state, ok, in_sync, reviewed, grade, formal,
      proof_sha256, verification_id, streak, need, streak_ok, why}]`
      （每条证明一条，按 `proof_no` 升序）；
      其中 `formal` 是这一条证明自己的第 4 位（`{证明号: 状态}` 里的那一格，
      四态 + 读侧产生的 `stale`）：`#p1` 形式化通过不等于 `#p2` 形式化通过，
      所以它必须逐条给，并且与 `grade` 成对读；
      `streak` / `need` / `streak_ok` 是这一份证明自己的连续读数（业主 2026-10-29，
      `#p1` 的票数不替 `#p2` 数）；
    - `reviewed`: 命题级 —— 至少一条证明 `signed`（定理档取"最高"就落在这一格）；
    - `grade`: 逐条证明各自的档里最高的那一档（`_highest_grade`）：一条 in-sync 都没有
      ⇒ `conjecture`；两条各缺一半（一条有形式化、另一条有签名）⇒ 不许凑出定理
      （借光由逐条派生挡掉，见 `proofs[*]["grade"]`）；
    - `state`: 命题级六态（有 signed 就 `signed`；否则有 stale 就 `stale`；否则有
      rejected 就 `rejected`；否则有 holding 就 `holding`；否则有 unreadable 且没别的
      ⇒ `unreadable`；否则 `unsigned`）；
    - `proofs_unreviewed` / `proofs_stale` / `proofs_rejected` / `proofs_holding`:
      逐条证明的编号写法
      （`000004#p2`），不许折进"没有证明"：它们是两条独立读数；
    - `proofs_superseded`: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）；
      它们仍可见，但不参与判定（最近一签说了算）；
    - 概念行：`reviewed=False` / `grade=not_applicable` 短路，不产出上面那些计数项；
    - `checked` / `ledger_present` / `problems` / `why`。
    """
    from . import evidencebits as _EB   # 惰性：等级的唯一入口
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    kind = str(row.get("kind") or "")
    bits = _EB.bits_from_row(row)
    if kind == "concept":
        # ---- 概念行短路（2026-10-22 审计的第 5 条） -----------------------------
        #
        # 改前这里照样去读台账，然后把每条的 state 写成 unsigned、grade 写成
        # not_applicable，却没有把 `ok` 一起压掉：只要概念行的 proof_text 撞上一次
        # 「成立」的签，`reviewed = any(e["ok"])` 就把它抬成 `reviewed=True`、
        # `state='signed'`，而同一条读数的 `proofs[0]` 写着 `unsigned`、
        # `grade='not_applicable'` —— 一条读数自己跟自己矛盾，R10 也跟着把它算进去。
        # 概念不参与等级链（`derive_grade` 对 concept 短路），所以这一格整份是
        # "不适用"：reviewed 恒 False、grade 恒 not_applicable，也不产出
        # `proofs_unreviewed` / `proofs_stale` / `proofs_rejected` 这些计数项
        # （它们会让"概念"被当成"没签过的证明"灌进读数）。
        entries = [{
            "proof_no": no, "label": proof_label(sid, no),
            "state": "unsigned", "ok": False, "in_sync": None,
            "reviewed": False, "grade": _EB.GRADE_NOT_APPLICABLE,
            "proof_sha256": proof_sha(text), "verification_id": "",
            "superseded": [],
            "why": ("概念行不参与等级链（`evidencebits.derive_grade` 对 "
                    "kind='concept' 短路成 not_applicable）⇒ 这一格对它不适用，"
                    "既不算审过，也不算没审过"),
        } for no, text in proof_list(row)]
        return {
            "checked": True,
            "ledger_present": False,
            "statement_id": sid,
            "proofs": entries,
            "state": "unsigned",
            "reviewed": False,
            "grade": _EB.GRADE_NOT_APPLICABLE,
            "proofs_unreviewed": [],
            "proofs_stale": [],
            "proofs_rejected": [],
            "proofs_holding": [],
            "proofs_superseded": [],
            "superseded_total": 0,
            "problems": [],
            "why": (f"{sid or '（没有编号）'} 是概念行（kind='concept'）：概念不参与"
                    "等级链，没有「审过的证明」这一档 ⇒ reviewed=False、"
                    "grade=not_applicable，也不计入 R10"),
        }
    entries: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    stale: list[str] = []
    rejected: list[str] = []
    holding: list[str] = []
    superseded_labels: list[str] = []
    problems: list[str] = []
    ledger_present = False
    #: 第 4 位（形式化）在逐条证明上的读数：`{证明号: 状态}`。汇总那一层是 OR
    #: （业主 2026-10-22：「但凡任意一个路径通过核验，它就是对的」），而逐条这一层是
    #: "哪一条路径验过" —— 两条都要：只读汇总会让 `#p2` 借 `#p1` 的光。
    formal_states = _EB.formal_by_proof(bits)
    for no, text in proof_list(row):
        st = review_standing(root, statement_id=sid, proof_text=text, proof_no=no)
        ledger_present = ledger_present or bool(st.get("ledger_present"))
        problems.extend(str(p) for p in (st.get("problems") or []))
        per = dict(bits)
        per["reviewed"] = bool(st.get("ok"))
        # 逐条证明的第 4 位：只有这一条自己被验过才算（不许拿别条的顶）。
        per[_EB.FORMAL_BIT] = formal_states.get(no, "pending")
        grade = _EB.derive_grade(per, kind=kind)
        state = str(st.get("state") or "unsigned")
        old = [dict(x) for x in (st.get("superseded") or [])]
        for item in old:
            superseded_labels.append(
                f"{proof_label(sid, no)}:{str(item.get('verification_id') or '?')}")
        entries.append({
            "proof_no": no, "label": proof_label(sid, no), "state": state,
            "ok": bool(st.get("ok")), "in_sync": st.get("in_sync"),
            "reviewed": bool(st.get("ok")), "grade": grade,
            #: 这一条证明自己的第 4 位（`evidencebits.FORMAL_PATH_STATES` 的取值：
            #: 四态 + 读侧产生的 `stale`）。它与 `grade` 成对："这条证明到什么档"
            #: 只有这两格合起来才说得清（#p1 形式化通过、#p2 没验 ⇒ 两条各自的档不同）。
            "formal": per[_EB.FORMAL_BIT],
            "proof_sha256": str(st.get("sha") or ""),
            "verification_id": str(st.get("verification_id") or ""),
            #: 被最近那一签盖过去的旧签（仍可见、不参与判定）。`review_standing`
            #: 的同一格原样下传，逐条证明分开。
            "superseded": old,
            #: 连续读数（业主 2026-10-29）：这一份证明自己的 `streak` / `need` /
            #: `streak_ok`，逐条证明分开（#p1 的票数不替 #p2 数）。
            "streak": int(st.get("streak") or 0),
            "need": int(st.get("need") or SIGN_STREAK_NEED),
            "streak_ok": bool(st.get("streak_ok")),
            #: 秘书对最近那一签的判定（业主 2026-10-30）：轴只有 clean / fault 两档，
            #: `judged` 区分"判过了"与"没判成"，`unjudged` 是"问过、没查成"那一格。
            "secretary_axis": str(st.get("secretary_axis") or ""),
            "secretary_judged": bool(st.get("secretary_judged")),
            "secretary_unjudged": bool(st.get("secretary_unjudged")),
            "why": str(st.get("why") or ""),
        })
        if state == "unsigned":
            unreviewed.append(proof_label(sid, no))
        elif state == "stale":
            stale.append(proof_label(sid, no))
        elif state == "rejected":
            rejected.append(proof_label(sid, no))
        elif state == "holding":
            holding.append(proof_label(sid, no))
    reviewed = any(e["ok"] for e in entries)
    states = [e["state"] for e in entries]
    if reviewed:
        state = "signed"
    elif "stale" in states:
        state = "stale"
    elif "rejected" in states:
        state = "rejected"
    elif "holding" in states:
        # 签过、判成立、只是次数没到（业主 2026-10-29）。它必须排在 `unsigned` 之前：
        # "有行、还差两次"与"一次都没签"是两种处置（前者再派两次，后者派一次）。
        state = "holding"
    elif "unreadable" in states:
        state = "unreadable"
    else:
        state = "unsigned"
    out_bits = dict(bits)
    out_bits["reviewed"] = reviewed
    #: 命题级的档 = 逐条证明里最高的那一档（`draft/39` §3.14 的"在 in-sync 的证明里取最高"）。
    #:
    #: 改前这里先把第 3 位取 OR、第 4 位取 OR，再派生一次：多证明模型下那会让
    #: `#p1` 的形式化通过 + `#p2` 的 V 签名凑出一档 —— 两条各缺一半，凑出来的档
    #: 谁也没有（借光）。现在每一档都由一条证明自己撑起来，命题级只是取最高的那条。
    grade = _highest_grade([str(e.get("grade") or "") for e in entries])
    if not grade:
        grade = _EB.derive_grade(out_bits, kind=kind)
    why = _statement_reading_why(sid=sid, state=state, reviewed=reviewed, entries=entries,
                                 unreviewed=unreviewed, stale=stale, rejected=rejected,
                                 holding=holding)
    return {
        "checked": not problems,
        "ledger_present": ledger_present,
        "statement_id": sid,
        "proofs": entries,
        "state": state,
        "reviewed": reviewed,
        "grade": grade,
        "proofs_unreviewed": unreviewed,
        "proofs_stale": stale,
        "proofs_rejected": rejected,
        #: 签过、判成立、但连续次数还没到的那些（写法与上面三格同形）。
        #: 单列的理由：它们是"再派两次审阅"的待办，不是"派一次"，也不是"改证明"。
        "proofs_holding": holding,
        #: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）：它们仍在台账里、
        #: 仍读得出来，但不参与命题级判定（最近一签说了算，见 `review_standing`）。
        "proofs_superseded": superseded_labels,
        "superseded_total": len(superseded_labels),
        "problems": problems,
        "why": why,
    }


def _statement_reading_why(*, sid: str, state: str, reviewed: bool,
                           entries: Sequence[Mapping[str, Any]],
                           unreviewed: Sequence[str], stale: Sequence[str],
                           rejected: Sequence[str], holding: Sequence[str]) -> str:
    """命题级那句 `why`（六态各一句；`holding` 里再把两种处置分开）。

    为什么要单独一个函数：这条`why`有六个分支、每支都是一句人话，而它住在
    :func:`statement_review_reading` 里会把那个函数压过 200 行（`scripts/repo_survey.py`
    的长函数基线是逐条登记的，长大要人裁）。判据不变，只是换了个落点。
    """
    if reviewed:
        return ""
    if state == "stale":
        return (f"{sid} 的证明都签过旧版（或签过但没盖住现在这一份）"
                f"（stale：{'、'.join(stale)}）⇒ 一条 in-sync 的签名都没有")
    if state == "rejected":
        return (f"{sid} 的证明现在这一份被签过、结论不是「成立」"
                f"（rejected：{'、'.join(rejected)}）")
    if state == "holding":
        # 2026-10-30（第三次裁定）：holding 里混着两种来路 —— "次数没到"（再送 V 判几转）
        # 与"这一转秘书没判成"（框架失败：没查成）。读数必须把它们分开，否则后者会被
        # 读成前者（"再判几次就好"）。
        #
        # 2026-11-02 删掉了第三种来路：改前这里还单列"历史行里的 unsure（只作历史兼容读：
        # 既不算票、也不清零）"。那一档连历史兼容读也不留之后，老行上那个轴名读出来是
        # 空轴（:func:`secretary_axis`），它在连续计数里落进"轴读不出来"那条通用纪律
        # （不计票、也不清零）—— 与"这一转秘书没判成"同一条处置，于是不再需要第三句。
        unjudged = [str(e.get("label") or "") for e in entries
                    if str(e.get("state") or "") == "holding"
                    and e.get("secretary_unjudged")]
        return (f"{sid} 的证明签过、也判了「成立」，但连续次数还没到 "
                f"{SIGN_STREAK_NEED} 次（holding：{'、'.join(holding)}）"
                "⇒ 第 3 位不发签：再送 V 审够次数（第 1、2 次只落台账、不翻位）"
                + (f"；其中 {'、'.join(unjudged)} 是这一转秘书没判成（checked=False："
                   "没查成，不是有毛病）—— 那一档不发签，等判定接上之后重签"
                   if unjudged else ""))
    if state == "unreadable":
        return f"{sid} 的验证台账读不出来 ⇒ 第 3 位没查成（不是「没签过」）"
    return (f"{sid} 的证明一次都没签（{'、'.join(unreviewed) or '没有证明'}）"
            "⇒ 第 3 位是没签过，不是签过过期")


def _highest_grade(grades: Sequence[str]) -> str:
    """几条证明各自的档 ⇒ 命题级那一档（`GRADES` 里最靠后的那个）。

    空清单 / 只有认不出的取值 ⇒ 空串（调用方退回"按汇总位现算"那一条路，不猜）。
    `not_applicable`（概念行）不在 `GRADES` 里，所以它到不了这里：概念行在
    `statement_review_reading` 里是短路的一支。
    """
    from . import evidencebits as _EB   # 惰性：与 `statement_review_reading` 同一处依赖

    known = [str(g) for g in grades if str(g) in _EB.GRADES]
    if not known:
        return ""
    return max(known, key=_EB.GRADES.index)


def statement_grade(root: str | Path, row: Mapping[str, Any]) -> str:
    """一条命题的等级 —— 转发（唯一实现在 `depsection.statement_grade`）。

    这一格原先自带一份实现（`statement_review_reading(root, row)["grade"]`：逐条证明
    现读台账、在 in-sync 的证明里取最高），与 `depsection.statement_grade`（`bits` 现算）
    是两个落点 —— `R003` 报的正是"同一判据两份实现"。2026-11-05 收成一处：等级由
    `evidencebits.derive_grade` 从五元位现算（`depsection` 那一份），这里只转发。

    `root` 保留在签名里只为老调用方（`test_multi_proof_end_to_end` 等）不必改；
    等级不从台账现读 —— 台账的签只写第 3 位（`bits.reviewed`），读侧按同一条
    `bits_from_row` 现算。逐条证明各自的读数仍归
    :func:`statement_review_reading`（那是另一个函数、回答另一个问题：每条证明自己
    到什么档），不要从这一格取。
    """
    return _DS.statement_grade(row)


def banned_markers_in(proof_text: str) -> list[str]:
    """这份证明里命中了哪些硬禁令短语（I10 的机械那一半，可离线复算）。"""
    text = str(proof_text or "")
    return [m for m in HARD_BAN_MARKERS if m in text]


#: `proof_review` 这一档的凭据判据码（2026-10-19，堵「假 proof_review」）。
#:
#: 两个码各有落点，不许合成一个（一个是写入期拒收，一个是审计期点名 ——
#: 同一句话在两个出口上的读者不同：写者要"改哪里"，审计要"存量有多少"）：
#:
#: - `CODE_WRITE`：写入期闸（`store.tx` 提交时）—— 当场拒收，一行都不写；
#: - `CODE_AUDIT`：审计期档（`verify._check_13`）—— error 级点名，存量照读。
CODE_WRITE = "proof_review_without_evidence"
CODE_AUDIT = "proof_review_without_verification"

#: `proof_review` 这一档在 `statements.evidence_kind` 里的取值（口径见 `schema.EVIDENCE_KINDS`）。
PROOF_REVIEW_KIND = "proof_review"


def _pending_signed(root: str | Path, proof_text: Any) -> dict[str, Any] | None:
    """命题还没在册时 V 审的那一签（按这一份正文的 sha 认领）；没有 ⇒ `None`。

    D-34：`verifications/pending/<sha>.jsonl` 里的那一行是真的审过（七项机械会审），
    只是当时没有命题号可挂。它是"先签后登记"那一半的证据面，所以在
    :func:`proof_review_gap` 里与"这一条命题台账里的那一签"同等看待 —— 判据仍然只有
    这一处（`signs_bit3`：成立且没有未解决 error）。
    """
    text = str(proof_text or "")
    if not text.strip():
        return None
    try:
        got = pending_sign(root, proof_shas=(proof_sha(text),))
    except VerificationError:
        return None
    if not got.get("found"):
        return None
    return got


def _gap_from_pending(out: dict[str, Any], checks: list[dict[str, Any]],
                      got: Mapping[str, Any], *, statement_id: str) -> dict[str, Any]:
    """:func:`_pending_signed` 认到那一签之后，把 `proof_review_gap` 的读数摊开。

    判据与"台账那一路"同一条（`signs_bit3`）：`成立` 且没有未解决 error、且引用核实
    没有挡住的那一条，才算签住（2026-10-27 收口）。

    改前这一行是 `row_ok = (verdict == "成立")` —— 与它上面这句话相反：`pending_sign`
    只回四格，`unresolved_errors` / `citation_checks` / `citation_gate` 全被丢掉，
    于是"成立 + 有未解决 error"与"成立 + 引用核实判不了"在这一路上都读成签住了，
    而同一行内容放进 `verifications/<命题号>.jsonl` 会被 `signs_bit3` 拒。同一份证据、
    两个落点、两套判定 —— 这就是要收掉的那条缝。
    """
    row = dict(got.get("row") or {})
    row.setdefault("verdict", str(got.get("verdict") or ""))
    # pending 那一签按对象 sha 认领，没有命题台账可数连续次数（它审的时候命题还没
    # 登记，那条台账还不存在）⇒ 连续闸在这一档不适用，判据只走行局部那一半
    # （`row_signable`：成立 + 无未解决 error + 引用不挡）。这不是放宽：连续闸要读的
    # 东西在 pending 这条路上根本不存在，硬套只会把"先签后登记"这条合法路整条堵死。
    row_ok = row_signable(row)
    verdict_word = str(got.get("verdict") or "")
    out["ledger"] = str(got.get("ledger") or "")
    out["verification_id"] = str(out["ledger"]).split("#")[-1]
    #: 这一签挂的是第几条证明（多证明模型，业主 2026-10-22）：pending 行自己记着号
    #: （`record_pending_sign` 写 `proof_no`），与台账那一支取 `chosen_no` 同一个口径
    #: （见 `proof_review_gap` 末尾 `chosen_no` 那一行）。
    #:
    #: 改前这一格没有任何一支写：`proof_review_gap` 走 pending 支时返回的 `proof_no`
    #: 恒是初始值 `None`。为什么这不是"少一格装饰"：`_grade_recomputed_from_signature`
    #: 把 gap 的这一格原样抄进 `_grade_recomputed.proof_no`（那条读数的形状写死在它的
    #: docstring 里，含 `proof_no`），而 `register_statement` 自 2026-11-05 起在"正文落行
    #: 之后、tx.upsert 之前"就调回填 —— 那一笔的签通常还只在 pending 台账里 ⇒ 改前
    #: 行上的 `_grade_recomputed.proof_no` 写成 `None`。`_read_proof_no` 对"没写号"的
    #: 约定仍是 canonical（缺省 ⇒ 1；给了坏值 ⇒ 0），所以那条读数丢的不是"号怎么读"，
    #: 而是"这一签挂的是哪一份"：读的人只能按 canonical 猜，分不出"真的是 #p1"与
    #: "写的人没填"（3640a508 起由本函数末尾那一行 `proof_no_of(row)` 补上）。
    out["proof_no"] = proof_no_of(row)
    out["verdict"] = verdict_word
    out["rows"] = 1
    out["sha_matches"] = True
    out["checked"] = True
    # 签不住有两种来路，拒信必须分开说：结论压根不是「成立」，还是判了「成立」却
    # 被 `signs_bit3` 的三条（未解决 error / 引用核实 / 没查成）之一挡住。
    if verdict_word != "成立":
        blocked = f"结论是 {verdict_word!r}（要「成立」）"
    else:
        blocked = ("结论写了「成立」但签不住（" + _bit3_blockers(row) + "）")
    checks[1].update(ok=bool(row_ok),
                     detail=(f"{out['ledger']}（命题还没在册时审的那一签）"
                             if row_ok else f"{out['ledger']}：{blocked}"))
    checks[2].update(ok=bool(row_ok),
                     detail=("按这一份正文的 sha 认领到（待登记的那一签）"
                             if row_ok else "签的不是这一份"))
    if not row_ok:
        out["state"] = "rejected"
        out["why"] = (f"命题 {statement_id} 的证明在 pending 台账里那一签：{blocked}"
                      "⇒ 复核过、签不住")
        return out
    out["state"] = "signed"
    out["ok"] = True
    out["why"] = (f"命题 {statement_id} 的凭据在 `{out['ledger']}`：V 在命题还没在册时"
                  "审过这一份并判「成立」，按这一份正文的 sha 认领到"
                  "（「先签后登记」与「先登记后签」是同一件事）")
    return out


def _bit3_blockers(row: Mapping[str, Any], *, streak: Any = None) -> str:
    """`signs_bit3` 为假时，逐条说清是哪一条挡住（拒信与读数的唯一措辞处）。

    `streak` 与 :func:`signs_bit3` 同义：行局部都过了、只有连续次数不够时，这一格
    必须把那句话写出来 —— 否则拒信会落进 `"判据判不了（读数不全）"` 那条兜底，
    读的人以为"有一格没读出来"，而实际只是"还差两次审阅"。
    """
    why: list[str] = []
    if int(row.get("unresolved_errors") or 0) != 0:
        why.append(f"未解决的 error {int(row.get('unresolved_errors') or 0)} 条")
    problem = signing_gate_problem(row)
    if problem:
        why.append(f"引用核实没查成（{problem}）")
    blocked = citation_blocks(row)
    if blocked:
        why.append("引用核实挡住：" + "、".join(
            f"{e['stmt_id'] or '（没有号）'} 判 {e['verdict']}" for e in blocked))
    if row_signable(row) and not streak_ok(streak):
        got = _streak_number(streak)
        why.append(("连续「成立」的次数没读出来（这一格没查成 ⇒ 不发签）"
                    if got is None else
                    f"连续「成立」{got}/{SIGN_STREAK_NEED} 次（还差 "
                    f"{SIGN_STREAK_NEED - got} 次）"))
    return "；".join(why) or "判据判不了（读数不全）"


def proof_review_gap(root: str | Path, row: Mapping[str, Any],
                     proof_no: Any = None) -> dict[str, Any]:
    """一条 `evidence_kind="proof_review"` 的命题有没有凭据 —— 纯读，不写任何东西。

    判据逐字来自 `schema.EVIDENCE_KINDS` 上面那段定义（2026-10-19 之前它只是注释，没有代码
    强制）：`proof_review` —— 证明经逐行审阅（`statements` 表的 `proof_text` 非空 + V 的
    `verifications` 里那一条签「成立」）。三条都要成立（缺哪条就报哪条，`why` 里说清）：
    1. `proof_text` 非空 —— 没有被审的那份证明，"审过"无从谈起；
    2. `verifications/<命题号>.jsonl` 里有一条盖住现行这一份正文的签（判定只走
       `review_standing`：那一份证明现在的 sha 有 `signs_bit3` 的签）；
    3. 那一签带着这一份正文的 `proof_sha256` —— 哈希回答"这份稿在你签完之后有没有被改过"。
    2026-10-22 口径（业主）：第 3 条是读数，不是授权凭证。所以 `ok=False` 有两种完全
    不同的来路，`state` 把它们分开：`stale`（签的是旧版 ⇒ 待复核）与 `rejected`
    （签的就是这一份、结论不是「成立」）。写入期闸只拒后者与"一次都没签"，见
    :func:`proof_review_gaps` —— "正文改过了"不许成为拒收理由。
    三态：读不到台账 / 坏行 ⇒ `ok=False` 且 `checked=False`（没查成，不是"通过"）；台账
    读得出、只是`一次都没签` ⇒ `checked=True`（查过了，结论是没凭据）。

    ## 任一份证明签住即放行（2026-10-22 审计最危险的一批，第 1 条）
    `evidence_kind` 是命题级的声明，而多证明模型里每一条证明各自有第 3 位
    （见 :func:`statement_review_reading`）⇒ 命题级凭据的判据是"至少一份证明 signed"。
    改前这里写死 `review_standing(..., proof_no=1)`：只认 canonical 那一份，于是
    `#p1` 未签、`#p2` 已成立的存量 `proof_review` 行既写不进去（闸整笔拒收），
    拒收之后撤回又抹掉台账那一行（同一批审计的两半）。
    逐条那一侧仍然分开：`state` / `proof_no` / `verification_id` / `sha_matches` / `why`
    说的是"当前这一份"（`proof_no` 参数；没给就按这一行自己记的号、没有就 canonical），
    于是拒信仍指得出是哪一份证明缺凭据，而不是一句"这一行不行"。

    返回键：`ok` / `checked` / `why` / `state` / `proof_no` / `statement_id` /
    `verification_id` / `verdict` / `round` / `unresolved_errors` / `sha_matches` /
    `ledger` / `rows` / `problems` / `checklist`；`checklist` 是逐项过关读数
    （`[{"item", "ok", "detail"}]`，三条与上面一一对应），只为拒信存在（业主 2026-10-19 的口径：
    "拒收消息要让人/模型一眼看出该补哪一项"），不参与判据 —— 写错只改可读性。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    out: dict[str, Any] = {
        "ok": False, "checked": False, "why": "", "statement_id": sid,
        "verification_id": "", "verdict": "", "round": None,
        "sha_matches": None, "ledger": "", "rows": 0, "problems": [],
        #: 现行这一份的读数（`REVIEW_STATES`）与证明号：`ok` 只在 `signed` 时为真。
        #: `state="stale"` 是"签过、但签的是旧版"—— 它是待复核这个读数，不是"没签过"；
        #: `state="holding"` 是"签过、判成立、连续次数还没到"（业主 2026-10-29）。
        "state": "", "proof_no": None,
    }
    checks: list[dict[str, Any]] = [
        {"item": "proof_text 非空（有被审的那份证明）", "ok": False, "detail": "还没判到"},
        {"item": f"`verifications/<命题号>.jsonl` 里有签「成立」的那一行"
                 f"（verdict=成立 且 unresolved_errors=0）", "ok": False, "detail": "还没判到"},
        {"item": "那一行的 `proof_sha256` 等于现在这一版 `proof_text` 的 sha256",
         "ok": False, "detail": "还没判到"},
    ]
    out["checklist"] = checks
    # ---- 概念行：永远不算"有证明"（2026-10-21，本批缺陷一的读侧）
    #
    # 真机读数（`projects/mp3/data/statements.json`）：1143 条概念行每一条
    # 都带 `proof_text`（值是一个哨兵 `concept:primitive`）。于是"这一行有没有证明"
    # 的读数被顶高：`prose_reviewed_statements` 数的是"`proof_text` 非空且 V 签了
    # 成立"，一条概念行只要撞上一次签名就能进那一格；而 `proof_review_gap` 也只问
    # `proof_text` 非空 —— 它会把概念行当成"有一条被审过的证明"的候选。
    #
    # 判据只有一句：概念不参与等级链（`draft/97` §14.5，
    # `evidencebits.derive_grade` 对 `kind="concept"` 短路成 `not_applicable`），
    # 所以它既没有"证明"这一档，也不可能"有证明"。两档要分开说：
    # 带 `proof_text` 是写入侧的污染（要点名，让存量看得见），
    # 不带是正常（这一格对它不适用 —— 不是"缺证明"）。
    if str(row.get("kind") or "") == "concept":
        out["checked"] = True
        text_concept = str(row.get("proof_text") or "")
        if text_concept.strip():
            checks[0].update(ok=False, detail=f"{len(text_concept)} 字（概念行不该有）")
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"概念行不该带证明文本：命题 {sid or '（没有编号）'} 是 "
                          f"kind='concept'，而它的 `proof_text` 非空"
                          f"（{text_concept[:40]!r}）⇒ 概念不参与等级链，"
                          "`proof_text` 对它不是证明，而是一个哨兵；"
                          "任何'有没有证明'的读数都会被它顶高。"
                          "写入侧已经堵住（`conceptrows.concept_statement` 不写这一格），"
                          "这一条是存量行的点名：把这一格清空（定义/待补标记都在别的字段里）")
        else:
            checks[0]["detail"] = "概念行没有 proof_text（正常：概念不参与等级链）"
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"命题 {sid or '（没有编号）'} 是概念行（kind='concept'）："
                          "概念没有'证明'这一档（不参与等级链）⇒ 这一格对它不适用，"
                          "不许读成'有证明'，也不许读成'缺证明'")
        return out
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        checks[0]["detail"] = "空"
        checks[1]["detail"] = "没有被审的对象，不适用"
        checks[2]["detail"] = "没有被审的对象，不适用"
        out["why"] = (f"命题 {sid or '（没有编号）'} 的 evidence_kind="
                      f"{PROOF_REVIEW_KIND!r}，而 `proof_text` 是空的 ⇒ "
                      "没有被审的那份证明，「逐行审阅过」这句话就没有对象。"
                      "要么把证明过程写进 proof_text，要么把这一档降成 heuristic")
        return out
    checks[0].update(ok=True, detail=f"{len(text)} 字")
    if not S.is_valid_id(sid):
        checks[1]["detail"] = "命题号不是编号形态，查不到台账"
        checks[2]["detail"] = "同上"
        out["why"] = (f"命题号 {sid!r} 不是编号形态（{S.ID_DIGITS} 位，旧四位仍可读）⇒ "
                      f"`verifications/` 里查不到它，凭据无从核起")
        return out
    path = verification_ledger_path(root, sid)
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        pending = _pending_signed(root, text)
        if pending is not None:
            return _gap_from_pending(out, checks, pending, statement_id=sid)
        out["checked"] = True
        checks[1]["detail"] = f"`{out['ledger']}` 不在盘上（一次审校都没有）"
        checks[2]["detail"] = "没有那一行，无从比"
        out["why"] = (f"命题 {sid} 声称 evidence_kind={PROOF_REVIEW_KIND!r}，而 "
                      f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有。"
                      "这一档要求 V 的 `verifications` 里那一条签「成立」（且审的是现在"
                      "这一版）—— 没有它，这一行就只是「自称被审过」。"
                      f"建议：① 派 V 去 `verify_proof(statement_id=\"{sid}\")`（不传 "
                      "proof_text，签的就是现行正文）；② 把 evidence_kind 降成 heuristic")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        checks[1]["detail"] = f"台账有读不出来的行：{problems[:3]}（没查成）"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                      "凭据没查成（不是「查过、没问题」）")
        return out
    if not rows:
        pending = _pending_signed(root, text)
        if pending is not None:
            return _gap_from_pending(out, checks, pending, statement_id=sid)
        out["checked"] = True
        checks[1]["detail"] = "台账是空文件"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 是空文件 ⇒ 一次审校都没落过"
                      "（「有这个文件」不等于「审过」）")
        return out

    # ---- 判定分两个口（2026-10-22 审计第 1 条 + 多证明模型收口）
    #
    # 命题级（`ok`）：`evidence_kind` 是命题级的声明，而每一条证明各自有第 3 位 ⇒
    # "任一份证明 signed 即放行"（`statement_review_reading` 的 `reviewed`）。
    # 逐条级（`state` / `proof_no` / `verification_id` / `sha_matches` / `why`）：
    # 说的是"当前这一份"（`proof_no`，缺省按这一行自己记的号，再缺省 canonical）。
    #
    # 为什么不能只留一个口：只留命题级，拒信就说不清是哪一份缺凭据（读的人只能猜）；
    # 只留逐条级（改前就是 `review_standing(..., proof_no=1)`），"#p1 未签、#p2 已签"
    # 的存量行会被写入期闸整笔拒收，而拒收之后撤回把台账那一行也抹掉 —— 同一批审计
    # 的第 1 条正是这个形态：`checked=True verdict='成立' signed_bit3=True` 而台账 0 字节。
    reading = statement_review_reading(root, row)
    no = proof_no_of(row) if proof_no is None else as_proof_no(proof_no)
    if no < 1:
        no = DEFAULT_PROOF_NO
    entries = [p for p in (reading.get("proofs") or []) if isinstance(p, Mapping)]
    by_no = {as_proof_no(p.get("proof_no")): p for p in entries}
    current = by_no.get(no) or by_no.get(DEFAULT_PROOF_NO) or {}
    signed_entry = next((p for p in entries if p.get("ok")), {})
    stale_entry = next((p for p in entries if str(p.get("state") or "") == "stale"), {})
    checked = bool(reading.get("checked"))
    if checked and signed_entry:
        chosen, state = signed_entry, "signed"
    elif checked and stale_entry:
        chosen, state = stale_entry, "stale"
    else:
        chosen, state = current, str(current.get("state") or "unsigned")
    chosen_no = as_proof_no(chosen.get("proof_no")) or no
    # 台账那一签的细节（verdict / round / unresolved_errors）只有 `review_standing` 的
    # 返回里有，逐条读数只带定位用的几格 ⇒ 对"被选中的那一份"再读一次（纯读，不写）。
    span = (review_standing(root, statement_id=sid,
                            proof_text=proof_text_of(row, chosen_no), proof_no=chosen_no)
            if checked else {})
    out.update({
        "checked": checked,
        "state": state,
        "proof_no": chosen_no,
        "sha_matches": chosen.get("in_sync"),
        "verification_id": str(chosen.get("verification_id") or ""),
        "verdict": str(span.get("verdict") or ""),
        "round": span.get("round"),
        # 给拒收消息用（"这一签是 verdict=X、unresolved_errors=N"）：读数，
        # 不参与判据 —— 判据只看 `signs_bit3`（一处口径）。
        "unresolved_errors": int(span.get("unresolved_errors") or 0),
        # I10 硬禁令的机械命中（只报不判，见 `review_standing` 的同一格）。
        "hard_ban_markers": [str(m) for m in (span.get("hard_ban_markers") or [])],
    })
    if state == "signed" and checked:
        checks[1].update(ok=True, detail=f"{out['verification_id']}：{out['verdict'] or '成立'}")
        checks[2].update(ok=True, detail=(
            f"{proof_label(sid, chosen_no)} 的现行正文 sha "
            f"{str(chosen.get('proof_sha256') or '')[:12]}… 与台账那一行相符"))
        out["ok"] = True
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r} 有凭据（每份证明各自有第 3 位，"
            f"任一份 signed 即算）：{str(chosen.get('why') or '')}")
        return out
    if state == "rejected":
        checks[1]["detail"] = (f"现行这一版被签过：{out['verification_id']} "
                               f"verdict={out['verdict']!r}、"
                               f"unresolved_errors={out['unresolved_errors']}")
        checks[2]["detail"] = "签的就是现行这一版，但结论不是「成立」"
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r}，而 `{out['ledger']}` 里"
            f"{proof_label(sid, chosen_no)} 现在这一份上那一签是 {out['verification_id']}："
            f"verdict={out['verdict']!r}、unresolved_errors={out['unresolved_errors']}"
            f"（why：{str(chosen.get('why') or '')[:120]}）⇒ 复核过、结论不是「成立」。"
            "建议：按 findings 改好证明再派 V 走一遍，或者如实降档 —— "
            "改完再把同一份内容交一次（改稿是正常动作，不是越权）。")
        return out
    if state == "stale":
        checks[1]["detail"] = (f"{proof_label(sid, chosen_no)} 签过，但没有一签盖住现在这一份"
                               f"（最近一签 {out['verification_id']}）")
        checks[2]["detail"] = "签的是另一版，无从比"
        out["why"] = (str(chosen.get("why") or "")
                      + "；改稿是正确动作，建议：请重新拿 V 签 —— 派 V 用 "
                      f"`verify_proof(statement_id=\"{sid}\", proof_no={chosen_no})` "
                      "审现行正文（签还没到位：这一版正文上还没有签块）")
        return out
    if state == "holding":
        # 签过、判成立、签的也是现行这一版 —— 就是连续次数没到（业主 2026-10-29）。
        # 它与 `unsigned`（一次都没签）必须分开说：前者的下一步是"再送 V 两次"，
        # 后者是"送 V 一次"。折成同一个读数会让"已经在路上"看起来像"还没出发"。
        entry = next((p for p in entries
                      if as_proof_no(p.get("proof_no")) == chosen_no), {})
        got = int(entry.get("streak") or 0)
        need = int(entry.get("need") or SIGN_STREAK_NEED)
        checks[1]["detail"] = (f"{proof_label(sid, chosen_no)} 已连续 {got}/{need} 次「成立」"
                               f"（最近一签 {out['verification_id']}）")
        checks[2]["detail"] = "签的就是现行这一版（不是过期），只是连续次数还没到"
        out["checked"] = checked
        out["why"] = (f"命题 {sid} 的证明签过、也判了「成立」，但连续次数只到 {got}/{need}"
                      "⇒ 签还没到位（V 判过「成立」，但这一版正文上还没有签块），"
                      "不能当「审过」。建议：再送 V 审，直到签到位；"
                      "不许把这几票当成一次签")
        return out
    if state == "unsigned":
        # 台账读得出、只是这一份（以及别的证明）一次都没签 ⇒ 查过了，结论是"没凭据"。
        # 改前这一支掉进最后那段，被报成 checked=False「台账读不出来（没查成）」——
        # 把"查过了、没签过"与"没查成"折成同一个读数（审计第 4 条）。
        checks[1]["detail"] = (f"`{out['ledger']}` 里没有 {proof_label(sid, chosen_no)} 这一份"
                               "证明的签（一次都没签）")
        checks[2]["detail"] = "没有那一行，无从比"
        out["checked"] = checked
        out["why"] = str(chosen.get("why") or
                         f"`{out['ledger']}` 里没有这一份证明的签 ⇒ 一次都没签")
        out["why"] += ("；建议：请拿 V 签 —— 派 V 用 "
                       f"`verify_proof(statement_id=\"{sid}\", proof_no={chosen_no})` 审这一份"
                       "（签还没到位：这一版正文上还没有签块）")
        return out
    checks[1]["detail"] = "台账读不出来（没查成）"
    checks[2]["detail"] = "同上"
    out["checked"] = False
    out["why"] = str(chosen.get("why") or "台账没查成（不是「没签过」）")
    return out


#: 比 `pre_theorem` 更弱的等级（降档告警用；2026-11-05 起读等级，不读档位）。
WEAKER_THAN_PRE_THEOREM_GRADES: tuple[str, ...] = ("conjecture", "strong_conjecture")

#: 历史档位名（保留导出只因 `secretary.py` 仍读它；那条 lane 的"声明档位退场"后延）。
#: 判定面不再用它：`weaker_than_evidence_gaps` 读的是 :data:`WEAKER_THAN_PRE_THEOREM_GRADES`。
WEAKER_THAN_PROOF_REVIEW: tuple[str, ...] = ("heuristic", "cross_check")


def weaker_than_evidence_gaps(root: str | Path,
                              rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里够格 `pre_theorem` 却现算成更弱等级的那些 —— 纯读。

    ## 2026-11-05：这条读数改读等级
    改前它读 `evidence_kind` 在 :data:`WEAKER_THAN_PROOF_REVIEW` 里（`heuristic` /
    `cross_check`）；业主动裁「判定面一律读等级」之后，判据换成"现算等级低于
    `pre_theorem`、而凭据已经够 `pre_theorem`"。这两件事在旧口径下几乎等价
    （档位弱 ⇔ 等级弱），但新口径能看见旧口径看不见的那一类：档位写着 `proof`、
    现算等级却只有 `strong_conjecture` 的行（真机 169 条不一致里有一批正是它）。

    ## 这条读数在说什么（2026-10-19，接 `proof_review_gap` 的反方向）
    `proof_review_gap` 管"自称审过、其实没签"（虚报）；这里是它的镜像：凭据齐全、
    等级却现算得低。真机形态（`projects/mp2` 的 `stmt:000003`）：`proof_text` 1909 字、
    `verifications/000003.jsonl` 里 `v-000001` 签「成立」、`proof_sha256` 与现行正文
    相符 ⇒ 按五元位现算就是 `pre_theorem`，而盘上落的是 `heuristic`。
    它不是虚报，所以不是 error：降档是安全方向，可以是有意的选择；但它必须是看得见的
    选择，不是默认值 —— 长期把强结果写成弱档，论文的强度声明会系统性偏低。

    判据只三条：
    1. 现算等级在 :data:`WEAKER_THAN_PRE_THEOREM_GRADES` 里；
    2. `proof_text` 非空（没有证明就谈不上"这份证明被审过"）；
    3. `proof_review_gap(...)` 判 `ok=True`（V 最近一签是「成立」且 `proof_sha256`
       等于现行正文）。
    概念行（`kind="concept"`）跳过：概念不参与等级链（`evidencebits.derive_grade` 的
    `not_applicable`）。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        try:
            bits = EB.bits_from_row(dict(row))
            grade = EB.derive_grade(bits, kind=str(row.get("kind") or ""))
        except Exception:  # noqa: BLE001 —— 算不出来不是"档位写低了"（三态：判不了就不判）
            continue
        if grade not in WEAKER_THAN_PRE_THEOREM_GRADES:
            continue
        if not str(row.get("proof_text") or "").strip():
            continue
        gap = proof_review_gap(root, row)
        if not gap.get("ok"):
            continue
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        out.append({
            "statement_id": sid,
            "grade": grade,
            "evidence_kind": str(row.get("evidence_kind") or ""),
            "verification_id": gap.get("verification_id") or "",
            "ledger": gap.get("ledger") or "",
            "why": (f"命题 {sid} 现算等级是 `{grade}`（低于 `pre_theorem`），而它的凭据"
                    f"已经够 `pre_theorem`：`proof_text` 非空、`{gap.get('ledger') or ''}` 里 "
                    f"{gap.get('verification_id')} 签「成立」、`proof_sha256` 与现行正文相符"
                    "（判据与 `proof_review` 写入期那道闸同一处）。"
                    "降档是安全方向，所以这是 warning、不是 error；但它必须是有意的："
                    "要么让这一行的五元位如实反映那一签，要么在报告里写清为什么故意留弱档。"),
        })
    return out


def proof_review_gaps(root: str | Path, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里凭据不够的那些 `proof_review`（空列表 = 都够）。

    只挑 `evidence_kind == "proof_review"` 的行去核（其它档不归这条判据管：
    `proof` 由 `evidencebits.bit_evidence_gaps` 核，`cross_check`/`heuristic` 只需声明）。

    ## 哪些算"凭据不够"（业主 2026-10-22 口径改了半边）
    这一份的调用者是写入期闸（`store._refuse_fake_proof_review`）与审计期档
    （`verify._check_13`），所以"不够"的判据就是"该不该拒收/点名"：
    - `unsigned`（一次「成立」都没有）/ `unreadable`（台账读不出来）⇒ 不够，照旧；
    - `rejected`（现行这一版被签过、结论不是「成立」）⇒ 不够，照旧；
    - `stale`（签过、但签的是旧版）⇒ 不再算"没有凭据"。哈希是读数不是授权凭证：
      "正文改过了"是正常动作，任何写入路径都不许因为它被拒收。这一档现在是待复核
      这个读数（收工门 R10 的 `stale_ids`），不是"没签过"。
    - 任一证明 `signed` ⇒ 够（`proof_review_gap` 的命题级判据）：多证明模型里每份证明
      各自有第 3 位，"#p1 未签、#p2 已成立"这一形态不许整笔拒收 —— 它是本批审计
      第 1 条的存量形态（真机 mp1 的 10 条 `proof_review`）。逐条的不合格仍由
      `proof_review_gap` 的 `state` / `why` 读出来，只是不升级成"整笔不写"。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("evidence_kind") or "") != PROOF_REVIEW_KIND:
            continue
        gap = proof_review_gap(root, row)
        if gap["ok"] or gap.get("state") == "stale":
            continue
        out.append(gap)
    return out


#: `recompute_grades` 的四栏（顺序 = CLI 的打印顺序；2026-11-05 改口径后第二栏
#: 从"已是最高"改成"已经一致"—— 重刷不只往上升，也纠 105 条虚报）。
#:
#: 名字是字符串而不是枚举，是因为它们直接进 `--json` 与四栏表：读的人拿到的就是
#: 这四个键。`not_enough` 里的 `state` 逐字取自 :func:`proof_review_gap`（不在本命令
#: 里另造一套词表），`unchecked` 只收 `checked=False` 的那一档。
GRADE_BACKFILL_COLUMNS: tuple[str, ...] = ("will_upgrade", "already_consistent",
                                           "not_enough", "unchecked")


def recompute_grades(root: str | Path, store: Any, *, apply: bool = False) -> dict[str, Any]:
    """按现行 V 的签重算每一行的等级（四栏读数；`apply` 才把历史列反算回去）。

    ## 2026-11-05 改口径：这一格从"补档位"变成"算等级"
    业主动裁：「等级是唯一的轴……`evidence_kind` 只作历史列保留，判定面一律读等级」。
    于是本命令的主读数从"该把 `evidence_kind` 写成哪一档"变成"按五元位现算，这一行
    现在哪一级"：等级是 :func:`evidencebits.derive_grade` 的现算值，不是本命令造的目标。

    ## 判据只有一处
    每一行都调 :func:`_grade_recomputed_from_signature`（它只算等级、不写档位）；
    本函数一个字都不重写"够不够 `pre_theorem`"的判据。四栏里"凭据不够"那一栏的
    `state` 是 :func:`proof_review_gap` 的原值（`signed` / `holding` / `stale` /
    `rejected` / `unsigned` / `unreadable`），不是本命令自造的枚举。

    ## 四栏（顺序不变，语义改成等级）
    - `will_upgrade`：现算等级与"历史档位反算出来的等级"不一致 —— 两个方向都收，
      `direction` 逐条写 `up`/`down`。存量里 106 条 `cross_check→heuristic` 会降、
      30 条 `cross_check→proof_review` 会升（分布见 `temp/grade_audit.py`）。
    - `already_consistent`：现算等级与历史列的反算名已经一致（重刷不会动它）；
    - `not_enough`：现算等级算不出来、而凭据闸有话说 —— `state` 逐字是
      `proof_review_gap().state`；
    - `unchecked`：`checked=False`（台账读不出来 / 坏行 / 这一行根本查不了）＋ `why`。
    概念行（`kind="concept"`）不进四栏：概念不参与等级链（`evidencebits.derive_grade` 对
    它 `not_applicable`），把它折进任何一栏都是错读数。它们逐条记在 `concepts` 里，
    并在 `--json` / CLI 摘要里报出条数。

    ## `apply`
    `apply=True` 时逐条落盘（一行一笔 `store.tx("statements")`）：事务内重新读这一行、
    再调一次 `_grade_recomputed_from_signature`（盘在两次读之间可能变过），只有仍然
    "等级与历史档位不一致"才 `tx.upsert`。写的是反算名
    （`evidencebits.kind_from_grade(等级)`）—— 档位若还出现，只能由等级反算
    （业主原话），不是"本命令选了一个目标档"。读不出来的行一个字不写；写入失败记
    `failed`、继续下一条。写完逐条再读一次盘，只有盘上现算等级与 `_grade_recomputed.to`
    都对上才记 `written`，否则记 `unmoved`（"已写 / 未动"是两条不同的读数）。

    幂等：等级与反算名已经一致的行在 `_grade_recomputed_from_signature` 之后不会再动
    ⇒ 第二次 `apply` 全部落 `already_top` 或 `not_enough`。

    返回键：`checked`（整张表读出来了吗）/ `apply` / `root` / `rows`（总行数）/
    `columns`（上面四栏）/ `concepts` / `written` / `unmoved` / `failed` / `why`。
    `not_enough` 每条还带 `ledger` / `ledger_present` / `rows`：`proof_review_gap` 在
    "台账文件不在盘上 / 空文件 / 没有证明正文"这几支会给出空的 `state`，这几格用 gap
    自己的读数说清"空"是哪一种 —— 不在这里补一个枚举。
    """
    root_p = Path(root) if str(root or "").strip() else Path(getattr(store, "root", "") or "")
    out: dict[str, Any] = {
        "checked": False, "apply": bool(apply), "root": str(root_p),
        "rows": 0, "columns": {name: [] for name in GRADE_BACKFILL_COLUMNS},
        "concepts": [], "written": [], "unmoved": [], "failed": [], "why": "",
    }
    if not str(root_p).strip():
        out["why"] = "没给工作区根 ⇒ 台账读不出来（四栏都没查成）"
        return out
    if not (root_p / "data" / str(S.TABLES["statements"]["file"])).is_file():
        out["why"] = (f"`{root_p / 'data' / str(S.TABLES['statements']['file'])}` 不在盘上"
                      " ⇒ 这不像一个工作区（四栏都没查成）")
        return out
    rows, problem, error = SL.rows_of(store)
    if problem:
        out["why"] = (f"`statements` 读不出来（{error.get('type') or '?'}: "
                      f"{error.get('message') or problem}）⇒ 四栏都没查成")
        return out
    out["checked"] = True
    out["rows"] = len(rows)
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    order = {g: i for i, g in enumerate(EB.GRADES)}

    def _rank(grade: str) -> int:
        return order.get(str(grade or ""), -1)

    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        cur = str(row.get("evidence_kind") or "").strip()
        if str(row.get("kind") or "") == "concept":
            # 概念不参与等级链：它既不该被升档，也不是"凭据不够"。单列出来是为了
            # 不让"四栏加起来比行数少"变成一条看不见的缺口。
            out["concepts"].append({
                "statement_id": sid, "evidence_kind": cur,
                "why": "概念行不参与等级链（`evidencebits.derive_grade` 对它是 "
                       "`not_applicable`）⇒ 不归本命令管",
            })
            continue
        got = _grade_recomputed_from_signature(row, root=root_p)
        reading = dict(got.get("reading") or {})
        if reading.get("checked") is False:
            # 判据自己报"没查成"（异常那一支）。先按 `checked=False` 分出去。
            out["columns"]["unchecked"].append({
                "statement_id": sid, "evidence_kind": cur, "state": "",
                "why": str(reading.get("why") or "凭据没查成（读不出来）"),
            })
            continue
        # 现算等级直接读五元位（唯一入口 `derive_grade`）；`reading` 只提供
        # "凭什么"（basis）与幂等判据，不提供等级 —— 后者由 `bits_from_row` 现算，
        # 这样"没签 / 凭据不够"的行也能被如实判成"该降档"（纠虚报那 105+ 条）。
        doc_kind = str(row.get("kind") or "")
        try:
            live_grade = EB.derive_grade(EB.bits_from_row(dict(row)), kind=doc_kind)
        except Exception:  # noqa: BLE001 —— 算不出来按"没查成"记，不折成"一致"
            out["columns"]["unchecked"].append({
                "statement_id": sid, "evidence_kind": cur, "state": "",
                "why": "五元位算不出来 ⇒ 这一行没查成（不是「一致」）",
            })
            continue
        cur_grade = EB.KIND_TO_GRADE.get(cur, "")
        if live_grade != cur_grade:
            direction = "up" if _rank(live_grade) > _rank(cur_grade) else "down"
            out["columns"]["will_upgrade"].append({
                "statement_id": sid,
                # `from` / `to` 是等级；档位两列并列给出，读的人不必自己换算。
                "from": cur_grade or "（空）", "to": live_grade,
                "from_kind": cur or "（空）",
                "to_kind": EB.kind_from_grade(live_grade),
                "direction": direction,
                "basis": str(reading.get("basis") or ""),
                "why": str(reading.get("why") or (
                    "历史档位与现算等级不一致：判定面读等级，重刷会按反算名改这一列"
                    "（两个方向都改；降档是纠虚报）")),
            })
            pending.append((out["columns"]["will_upgrade"][-1], dict(got["row"])))
            continue
        out["columns"]["already_consistent"].append(
            {"statement_id": sid, "grade": live_grade, "evidence_kind": cur})
        continue
    if apply and pending:
        _apply_grade_backfill(root_p, store, pending, out)
    return out


def _apply_grade_backfill(root: Path, store: Any,
                          pending: list[tuple[dict[str, Any], dict[str, Any]]],
                          out: dict[str, Any]) -> None:
    """`recompute_grades(apply=True)` 的写盘半：一行一笔事务 + 写后逐条读盘。

    ## 写的是什么（2026-11-05）
    写的是反算名：`evidencebits.kind_from_grade(等级)`。`_grade_recomputed_from_signature`
    只算等级、不写档位；这一格是"档位若还出现，只能由等级反算"那条纪律的唯一写者。
    事务内重新读这一行、再跑一次 `_grade_recomputed_from_signature`：调用方手上那份
    `pending` 是几毫秒前算的，而盘可能已经变过（另一个进程刚补过签 / 刚改过正文）。
    判据仍然只有那一处；这里只决定"还写不写"。
    """
    attempted: list[tuple[dict[str, Any], str]] = []
    for entry, _planned in pending:
        sid = str(entry.get("statement_id") or "")
        try:
            with store.tx("statements", actor="repair",
                          note=f"repair.backfill_grades:{sid}") as tx:
                # 按号定位走查口（口径一）。改前这里还认 `statement_id` 这个历史别名：
                # `statements` 的主键只有 `stmt_id`（`schema` 里没有那一列，`row_from_dict`
                # 也会丢掉未知键）⇒ 那一档是死别名，收口时按主键口径统一。
                current_got = SL.by_id(tx, stmt_id=sid)
                if not current_got["checked"]:
                    err = current_got.get("error") or {}
                    raise RuntimeError(
                        f"`statements` 读不出来（{err.get('type') or '?'}: "
                        f"{err.get('message') or current_got.get('reason') or '?'}）")
                current = current_got["row"] or None
                if current is None:
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": "事务里找不到这一行（两次读之间盘变过）⇒ 没动",
                    })
                    continue
                fresh = _grade_recomputed_from_signature(current, root=root)
                trace = dict(fresh.get("reading") or {})
                try:
                    live = EB.derive_grade(EB.bits_from_row(dict(current)),
                                           kind=str(current.get("kind") or ""))
                except Exception:  # noqa: BLE001 —— 算不出来 ⇒ 没查成，不动
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": "事务内重算五元位失败 ⇒ 没查成，不动",
                    })
                    continue
                target_kind = EB.kind_from_grade(live)
                cur_now = str(current.get("evidence_kind") or "").strip()
                if not target_kind or target_kind == cur_now:
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": str(trace.get("why")
                                   or "重算结果与历史列已经一致（盘在两次读之间变过）⇒ 没动"),
                    })
                    continue
                if not trace:
                    # 凭据那一支没给出回执（没签 / 凭据不够），而等级与历史列确实不一致
                    # ⇒ 写盘仍要留痕。痕里的 `from`/`to` 是等级，`basis` 留空（没有签可指）。
                    trace = {
                        "checked": True, "from": EB.KIND_TO_GRADE.get(cur_now, ""),
                        "to": live, "from_kind": cur_now, "to_kind": target_kind,
                        "why": ("重刷：历史档位与现算等级不一致 ⇒ 按 `kind_from_grade` "
                                "反算改写这一列（没有签可指，basis 为空）"),
                        "basis": "", "proof_no": None, "at": _now_iso(),
                    }
                current["evidence_kind"] = target_kind
                current[GRADE_RECOMPUTED_KEY] = dict(trace)
                tx.upsert("statements", current,
                          note=f"repair.backfill_grades:{sid}")
            attempted.append((entry, live))
        except Exception as exc:  # noqa: BLE001 —— 一条写失败不许拖住其余行
            out["failed"].append({
                "statement_id": sid,
                "why": f"{type(exc).__name__}: {exc}",
            })
    if not attempted:
        return
    # ---- 写后逐条再读一次盘（业主 2026-11-04）：事务返回 ≠ 盘上是那个样子。
    try:
        from .store import Store as _Store   # 惰性：只为一个"全新的读"开一个新句柄

        # 取数走查口的唯一取数口（三态：读不成不是 0 行）。
        disk_got, disk_problem, disk_error = SL.rows_of(_Store(root))
    except Exception as exc:  # noqa: BLE001 —— 读不回来就逐条记"没查成"
        disk_got, disk_problem = None, f"{type(exc).__name__}: {exc}"
        disk_error = {"type": type(exc).__name__, "message": str(exc)}
    if disk_problem:
        for entry, _target in attempted:
            out["unmoved"].append({
                "statement_id": str(entry.get("statement_id") or ""),
                "why": ("写完之后再读盘失败（"
                        f"{disk_error.get('type') or '?'}: "
                        f"{disk_error.get('message') or disk_problem}）"
                        "⇒ 这一条是「没查成」，不是「没动」"),
            })
        return
    # 索引的构造只有一处（查口 `index_by_id`）。改前这里还认 `statement_id`
    # 这个历史别名：`statements` 的主键只有 `stmt_id`（schema 里没有那一列，
    # `row_from_dict` 也会丢掉未知键）⇒ 那一档是死别名，按主键口径统一。
    disk_rows = SL.index_by_id(disk_got)
    for entry, target in attempted:
        sid = str(entry.get("statement_id") or "")
        disk = disk_rows.get(sid) or {}
        trace = dict(disk.get(GRADE_RECOMPUTED_KEY) or {})
        try:
            live_grade = EB.derive_grade(EB.bits_from_row(disk),
                                         kind=str(disk.get("kind") or ""))
        except Exception:  # noqa: BLE001 —— 读不回来按"没落到"记
            live_grade = ""
        if (live_grade == target
                and str(disk.get("evidence_kind") or "").strip() == EB.kind_from_grade(target)
                and str(trace.get("to") or "") == target):
            out["written"].append({
                "statement_id": sid, "from": str(entry.get("from") or ""),
                "to": target, "to_kind": EB.kind_from_grade(target),
                "at": str(trace.get("at") or ""),
                "basis": str(trace.get("basis") or ""),
            })
        else:
            out["unmoved"].append({
                "statement_id": sid,
                "why": (f"写完之后再读盘：现算等级={live_grade!r}、"
                        f"evidence_kind={disk.get('evidence_kind')!r}、"
                        f"{GRADE_RECOMPUTED_KEY}.to="
                        f"{str(trace.get('to') or '（没有痕）')!r} ⇒ 这一条没落到目标等级"),
            })


def unverified_statement_refs(root: str | Path,
                              plans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """攻坚计划的 `history` 里点名了哪些 `statement_id`、而 `verifications` 里没有对应行。

    ## 为什么这一条落在「攻」那一格（2026-10-19，接 V 的回路的收工侧）
    F 的论证由 B 登记成 `statements` 一行、拿到 `statement_id` 之后，那一号进 `attack_plans.history`（`agent_f/step.py`
    的 P3-6 落点），M 在 `attack.status` 里看得见；但看得见不等于有人审 —— 那一栏可以一直是
    "F 交了、没人签"而收工门照样绿（「攻」只问计划推进了没有）。这一条把两件事接上：history 里
    有 `statement_id` ⇒ `verifications` 里必须有它的一行（`verify_proof` 的产物）；没有 ⇒
    `closing._check_acceptance` 记 `unknown`（不是 `pass`）——"没签"与"签了"必须分得开。
    三态：`checked=False` ⇒ 没查成（读不到 `verifications/` 目录或坏行），不是"一条都没缺"；
    `missing` 逐条给 `plan_id` / `round` / `statement_id` / `why`。`signed` 是"那一行签住了第 3 位"
    （`signs_bit3`），不决定红绿（由 `missing` 定），留着是因为"有行但没签"与"有行且签了"是两种不同状态（`有毛病` 也是一条"有对应行"）。
    """
    refs: list[dict[str, Any]] = []
    problems: list[str] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        for entry in (plan.get("history") or []):
            if not isinstance(entry, Mapping):
                continue
            sid = str(entry.get("statement_id") or "").strip()
            if not sid:
                continue
            ref: dict[str, Any] = {
                "plan_id": str(plan.get("plan_id") or ""),
                "round": entry.get("round"),
                "statement_id": sid, "rows": None, "signed": None, "why": "",
            }
            try:
                path = verification_ledger_path(root, sid)
            except VerificationError as exc:
                ref["why"] = f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到它那一份台账"
                refs.append(ref)
                continue
            if not path.is_file():
                ref["rows"] = 0
                ref["signed"] = False
                ref["why"] = (f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上 ⇒ "
                              "这一条命题一次审校都没落过")
                refs.append(ref)
                continue
            rows, bad = JF.read_jsonl(path)
            if bad:
                problems.extend(f"{VERIFICATIONS_DIR}/{sid}.jsonl: {b}" for b in bad)
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行：{bad[:3]}"
                refs.append(ref)
                continue
            ref["rows"] = len(rows)
            ref["signed"] = bool(signed_rows(rows))
            if not rows:
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 是空文件 ⇒ 一次审校都没落过"
            refs.append(ref)
    missing = [r for r in refs if not r.get("rows")]
    return {
        "checked": not problems,
        "problems": problems,
        "refs": refs,
        "missing": missing,
        "total": len(refs),
        "note": ("plan 的 `history` 里有 `statement_id` ⇒ `verifications/<命题号>.jsonl` 里"
                 "必须有它的一行（派 V 的 `verify.verify_proof` 就会落）。`missing` 非空 ⇒ "
                 "「攻（攻坚推进）」那一格记 `unknown`（不是 `pass`）；`signed` 只是读数："
                 "「有行但没签」由审计期那一档（`proof_review_without_verification`）点名"),
    }


# ============================================================ 断言与所引证据：方向 / 同一份证据复用
#
# 这一节是 `specs/g.py` policy[7]（「引用一个与断言相反的证据行，比没有引用更坏」）
# 与 policy[9]（「同一份证据不能当第二份用」）两条义务的机械判据本体。
#
# 为什么落在 `verifications`（而不是在 `verify._check_7` 里直接写一份）：
# 同一条口径在写入期（`doc_tools.check_proofs`，2026-10-13 起就有一条"引否证当支撑"）
# 与审计期（`verify._check_7`）各读一次 —— 两处各写一份判据必然漂移，而漂移的形态是
# "写入期拦下的，审计期照样说没问题"（FC-03 禁止的形态）。落法与
# `weaker_than_evidence_gaps` 同源：判据本体只此一份，两个出口都调它。

#: `experiments.result` 里"方向"只有两档有值；`inconclusive` 没有方向。
#: 真身是 `schema.EXPERIMENT_RESULTS`，这里只把"相反"那一个取值点名。
REFUTES = "refutes"
#: `negation_kind` 里"已证否"那一档（受控词表真身是 `schema.NEGATION_KINDS`）。
DISPROVED = "disproved"


def opposite_direction_evidence(claim: Mapping[str, Any],
                                experiment: Mapping[str, Any]) -> dict[str, Any] | None:
    """这条断言引用这条实验时，方向是不是反的 —— 判据本体（纯读，`None` = 不反）。

    ## 判的是什么（可机械化的那一半）
    一条实验行自己的结论是 `result="refutes"`（连同 `negation_kind="disproved"`，这是
    `schema.Experiment.validate` 强制的），意思是"它检验的那条命题被证否了"。一条正文断言
    把它列进 `citations` 当支撑时，台账上必须能读出"这条断言正是在说「我们证否了它」"——
    机械读法就是 `is_negative=True` 且 `negation_kind="disproved"`（`doc_tools.check_proofs`
    2026-10-13 的口径，真机现场：`projects/p6t2-research-20261012b` 的 claim-2 把 `exp:0002`
    （`result="refutes"`）列进 `citations` 当支撑，一路写库）。判据只需要两个字段：证据行的
    `result` / `negation_kind`，断言的 `is_negative` / `negation_kind` —— 都在 schema 里。
    ## 哪一半判不了（如实登记，不硬造）
    反方向的那一支 —— 断言登记成"已证否"、却引一条 `result="supports"` 的实验 —— 不归本判据管：
    `supports` 是相对于实验行自己的 `claim` 说的，而一条否定型断言（例如「不存在这样的图」）完全
    可能由一条 `supports` 的实验支持；更常见的是 `supports` 只是 `cross_check`（数值支持）。要判
    它，必须让实验行声明"它检验的命题相对于这条正文断言的正负极性"（例如 `tests_claim_id` +
    `direction` 两格），那是 schema 改动，不是审计侧能单方面补的。同理，`result="refutes"` 引一条
    正面断言也只有在"实验检验的就是这条断言所说的命题"时才是真相反 —— 本判据把"引用关系"当成
    那个链接（与写入期、收工门同一口径）。
    ## 返回值：不反 ⇒ `None`；反 ⇒ 一个 dict（`experiment_id` / `result` / 断言侧字段 / `why`），写入期与审计期各自决定怎么呈现（`problem` / `Issue`），判定本身不重复。
    """
    if str(experiment.get("result") or "") != REFUTES:
        return None
    if bool(claim.get("is_negative")) and str(claim.get("negation_kind") or "") == DISPROVED:
        return None
    eid = str(experiment.get("experiment_id") or "")
    return {
        "experiment_id": eid,
        "result": REFUTES,
        "claim_is_negative": bool(claim.get("is_negative")),
        "claim_negation_kind": str(claim.get("negation_kind") or ""),
        "why": (
            f"它引了 {('exp:' + eid) if eid else '这条实验'} 当支撑，而那条实验自己的结论是 "
            f"`result={REFUTES!r}`（否证）⇒ 一条否证被当成支撑用了。"
            "要么把这条断言改成否定型并写 `is_negative=True` + "
            f"`negation_kind={DISPROVED!r}`（「我们证否了它」），"
            "要么换一条真正支持它的证据；只在正文里解释「那只是脚本内部判据的问题」不算数 —— "
            "台账上它仍然是 refutes。"
        ),
    }


def _freeze(value: Any) -> Any:
    """把 `observations.data` 变成可比较的规范形（dict 的键序不参与同一性）。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def evidence_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """一条实验行的"证据身份"：同一份读数只该算一份证据。

    ## 为什么身份不能只是 `experiment_id`
    真机读数（`draft/39` §6.27 的 D39，T2 第 9 趟 `p6k`）：一个脚本被派了 9 次，claim 分别是
    W(2)/W(3)/W(4)…，每次都打印逐字相同的 `data`（30 顶点 / 度 3）—— 始终是同一个图。台账上于是
    有 9 条 `result="supports"`，手稿把它们当 9 份独立证据引：同一份读数被当成了九份。这 9 条的
    `experiment_id` 各不相同，所以"按 `experiment_id` 判重"看不见它。
    ## 身份的定义（与 E 写入期那条 note 同一处）：有 `observations.data`（非空）⇒ 同脚本
    （`code_hash`）+ 同 `data` 即同一份证据（`code_hash` 为空也照比：历史行没有哈希时，"同 data" 仍是唯一可比的读数）；没有 `data` ⇒ 退回
    `experiment_id`（同一行被引两次是同一份证据；两行都没有 data 时不合并 —— 那会靠猜）。
    此前它只在 `agent_e.run_experiment._reused_evidence_note` 里，现在两边都读这一个函数（FC-03：同一件事不许有两份定义）。
    """
    obs = row.get("observations")
    data = dict(obs.get("data") or {}) if isinstance(obs, Mapping) else {}
    if data:
        return ("data", str(row.get("code_hash") or ""), _freeze(data))
    return ("row", str(row.get("experiment_id") or ""))


def one_evidence_used_twice(documents: Iterable[Mapping[str, Any]],
                            experiments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """同一份证据被同一份稿件里的两条不同断言当独立证据用 —— 纯读。

    ## 判据（一条）：把每份稿件的 `claims[].citations` 里的 `exp:` 引用按 :func:
    `evidence_identity` 归组；同一组里出现 ≥ 2 个不同的 `claim_id` ⇒ 报一条。
    为什么 warning 不是 error（与 `opposite_direction_evidence` 的 error 不同）：同一份证据被两条
    断言引用可以是正当的（定理与推论、综述复述同一条读数、两条表述压在同一次计算上）。台账分不出
    "两条独立支撑"与"一份支撑被数了两遍"，所以它必须是看得见的读数，不是硬拦（会红掉合规稿件），
    而完全不说又正是 D39 的形态。处置写进 `why`：是复现就在正文与实验行 `notes` 里说清。
    ## 范围只在一份稿件内：跨稿件复用同一份证据是正常的（综述与论文引同一条实验）；判据只在
    同一份 `documents` 行内部比较 —— 返回值 `[{doc_id, claim_ids, experiment_ids, why}]`；
    空列表 = 不报（正常形态）。
    """
    exp_by_id: dict[str, Mapping[str, Any]] = {}
    for row in experiments:
        if not isinstance(row, Mapping):
            continue
        eid = str(row.get("experiment_id") or "")
        if eid:
            exp_by_id[eid] = row
    out: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            continue
        doc_id = str(doc.get("doc_id") or "")
        groups: dict[tuple[Any, ...], dict[str, list[str]]] = {}
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            cid = str(claim.get("claim_id") or "")
            if not cid:
                continue
            for cite in claim.get("citations") or []:
                kind, ref = T.citation_ref_parts(cite)
                if kind != "exp":
                    continue
                row = exp_by_id.get(ref)
                if row is None:
                    continue          # 悬空引用由 `dangling_citation` 报，不在这里重复
                group = groups.setdefault(evidence_identity(row),
                                          {"claim_ids": [], "experiment_ids": []})
                if cid not in group["claim_ids"]:
                    group["claim_ids"].append(cid)
                if ref not in group["experiment_ids"]:
                    group["experiment_ids"].append(ref)
        for group in groups.values():
            claim_ids = sorted(group["claim_ids"])
            if len(claim_ids) < 2:
                continue
            experiment_ids = sorted(group["experiment_ids"])
            evidence = " / ".join(f"exp:{eid}" for eid in experiment_ids)
            if len(experiment_ids) == 1:
                same = f"同一条实验行（{evidence}）"
            else:
                same = (f"{evidence} 是同脚本 + 同 `data` 的两次运行"
                        "（`observations.data` 逐字相同）")
            out.append({
                "doc_id": doc_id,
                "claim_ids": claim_ids,
                "experiment_ids": experiment_ids,
                "why": (
                    f"稿件 {doc_id} 的断言 {'、'.join(claim_ids)} 都把 {evidence} 当独立证据用，"
                    f"而它是同一份证据（{same}）⇒ 一条证据被算成了两份。"
                    "若这是复现（同一个对象被核了两次），请在正文与实验行的 `notes` 里"
                    "说清「这不是第二份独立证据」；否则换一条真正独立的证据。"
                ),
            })
    return out


def selftest() -> int:
    """最小自检：冷启动提示词只有对象、两态可判、签位条件、追加式编号。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="verifications_selftest_"))
    checks: list[tuple[str, bool]] = []
    prompt = cold_start_prompt("设 G 是群，则 c(G) ≤ 1。", "1. 由定义直接得到。",
                               readonly_facts="- stmt:0007 现状：猜想（第 2 位空）")
    checks.append(("提示词带命题与证明", "c(G) ≤ 1" in prompt and "由定义直接得到" in prompt))
    checks.append(("提示词带硬禁令", "易证" in prompt and "无依据的步骤" in prompt))
    # I12（冷启动）在这一层的判据是接口：拼提示词的函数只收字符串，
    # 没有任何 store / conductor / registry / session_root 参数 —— 于是"不给句柄"
    # 是结构性质，而不是"约定只读"（提示词里出现"没有 store 句柄"这几个字是说明，
    # 不是句柄本身；按子串判会把说明误判成句柄）。
    import inspect as _inspect

    params = set(_inspect.signature(cold_start_prompt).parameters)
    checks.append(("接口上没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    bad = parse_verdict('{"verdict": "有毛病", "defect_step": 2, "findings": '
                        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步"}]}')
    checks.append(("两态解析", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=bad)
    # 编号宽度不许写死（2026-10-14 业主裁定：4 位 → 6 位）：发号点是
    # `next_verification_id` 的 `f"v-{S.format_id(...)}"`，所以断言也从
    # `schema` 取形态。旧写法写死 `"v-0001"`，宽度一改这条自检就红 ——
    # 那是断言过期（`v-0001` 这一格属于旧四位号），不是发号器坏了。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   row["verification_id"] == f"v-{S.format_id(1)}"))
    checks.append(("有毛病不签第 3 位", bit3_payload(row) == {}))
    good = parse_verdict('{"verdict": "成立", "findings": []}')
    first = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    checks.append(("第 1 次成立只落台账、不翻位（业主 2026-10-29）",
                   bit3_payload(first, streak=consecutive_holds(root, "0007")).get("reviewed")
                   is not True))
    record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    ok_row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    holds = consecutive_holds(root, "0007")
    checks.append((f"连续 {SIGN_STREAK_NEED} 次成立才签第 3 位",
                   holds["streak"] >= SIGN_STREAK_NEED
                   and bit3_payload(ok_row, streak=holds).get("reviewed") is True))
    checks.append(("追加式（四行）", len(list_verifications(root, limit=None)[0]) == 4))
    checks.append(("limit=0 是零条、limit=None 才是全量",
                   list_verifications(root, limit=0)[0] == []
                   and len(list_verifications(root, limit=None)[0]) == 4))
    try:
        parse_verdict("我不确定")
        unparsable = False
    except VerificationError:
        unparsable = True
    checks.append(("没查成抛错（不冒充审过了）", unparsable))
    # 2026-11-02（业主：这一档连历史兼容读也不留）：老行上的那一格按 `成立` 读、能签、
    # 而且算一票。三条一起判 —— 只判"读成成立"会漏掉"它在连续计数里仍被跳过"。
    legacy = {"verdict": LEGACY_VERDICTS[0], "unresolved_errors": 0, "citation_checks": []}
    checks.append(("老行上的已取消档：按成立读、且能签第 3 位",
                   read_verdict(legacy) == "成立" and row_signable(legacy)))
    checks.append(("连续计数：成立, 已取消档, 成立 是 3 票（改前是 2）",
                   _hold_run_lengths([
                       {"verdict": "成立", "proof_sha256": "x", "unresolved_errors": 0},
                       dict(legacy, proof_sha256="x"),
                       {"verdict": "成立", "proof_sha256": "x", "unresolved_errors": 0},
                   ]) == [1, 2, 3]))
    for name, good_ in checks:
        print(f"  [{'PASS' if good_ else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
