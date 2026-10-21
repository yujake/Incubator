# -*- coding: utf-8 -*-
"""命题的五元证据位与派生等级（`draft/39` §3.14，用户 2026-10-05 定）。

## 五个位（每一位都有明确的 owner，owner 是判据的一部分）

| # | 位 | owner | 成立时至少要写什么 |
|---|---|---|---|
| 1 | 数值验证 `numeric` | E | 四态：`verified` / `failed` / `na`（不适用，必须写理由）/ `pending`（还没做）；`verified`/`failed` 要记被哪个脚本测的（script + sha + 实验号） |
| 2 | 有证明 `proof` | F | 证明过程（逐步论证，每步引到的 id 在册） |
| 3 | 审过 `reviewed` | V（自己产出的命题）／引用（引用命题：凭据是文献代号） | 自己产出 ⇒ V 的三态结论；引用 ⇒ `lit:`/`known_lit_id` + 逐字核验 |
| 4 | 形式化通过 `formal` | E | 四态，同第 1 位；`verified` 才算过 |
| 5 | 正式审查 `audited` | H（G 申请） | H 的审校轮次与结论（H 只看证据是否确凿 + 引用是否得当，不读证明判数学） |

## 位与台账的映射（业主 2026-10-09：五元状态是哪张表在维护，要做好映射）

上面的表说的是"这一位属于谁"，`BIT_LEDGERS` 说的是"这一位去哪张表里查"：
`proof` 去 `statements.proof_text`（B 维护的那张表）、`numeric`/`formal` 去
`experiments`（`method` 要对得上）、`reviewed`/`audited` 去稿件上的 V/H 结论。
判据（`bit_evidence_gaps`）只做一件业主点名的事：位上说有，表里要查得到。

## 等级机械派生（不许任何角色自报等级）

- 全空/false ⇒ 猜想；
- 第 1 位 `verified` ⇒ 强猜想（封顶：数值堆再多也不能变成定理 —— 用户口径"数值验证不构成证明"）；
- 第 2 位 + 第 3 位 ⇒ 预备定理级；
- 第 2 位 + 第 4 位 ⇒ 正式定理；
- 第 5 位 ⇒ 追加"已过正式审查"（并列，不覆盖）。

## 作废（`draft/39` §3.15/§3.18）

只有两种能作废：① 数值实验出真反例（四条判据同时成立）；② 理论构造出反例。
作废后五位读数全部作废（保留历史 + `refuted_by`），条目保留。
"审不出来 / 没人做 / 预算用尽 / 脚本报错"一律不许作废。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

#: 引文"通过"的两档（`schema.QUOTE_MODES` 的唯一来源就是它，这里只转发一次引用）。
from .schema import QUOTE_MODES

#: 第 1/4 位的四态（顺序就是"从没做到做到了"的强弱）。
BIT_STATES: tuple[str, ...] = ("pending", "na", "failed", "verified")
#: 派生等级（由弱到强；`audited` 是并列的追加档，不进这个序列）。
GRADES: tuple[str, ...] = ("conjecture", "strong_conjecture", "pre_theorem", "theorem")
#: 「不适用」那一档（`draft/97` §14.5）：概念行不参与等级链。
#: 刻意不在 `GRADES` 里：进了那条序列就会被排序、被算进"定理有几条"的计数，
#: 而"这个概念是猜想"这句话本身是错的（概念没有真值，只有良定义没良定义）。
GRADE_NOT_APPLICABLE = "not_applicable"
GRADE_LABELS: dict[str, str] = {
    "conjecture": "猜想",
    "strong_conjecture": "强猜想",
    "pre_theorem": "预备定理级",
    "theorem": "正式定理",
    GRADE_NOT_APPLICABLE: "不适用（概念行不参与等级）",
}
#: 五位的名字（对外读数、台账字段都用这一套）。
BIT_NAMES: tuple[str, ...] = ("numeric", "proof", "reviewed", "formal", "audited")
#: 每一位的 owner（引用命题的第 3 位 owner 是"引用"，不是 V）。
BIT_OWNERS: dict[str, str] = {
    "numeric": "E", "proof": "F", "reviewed": "V", "formal": "E", "audited": "H",
}


def _state(value: Any) -> str:
    """把一个位的取值规范化成四态之一；`None`/空 ⇒ `pending`（还没做）。"""
    text = str(value or "").strip().lower()
    if text in ("", "none", "null", "pending", "todo"):
        return "pending"
    if text in ("na", "n/a", "not_applicable"):
        return "na"
    if text in ("failed", "false", "no", "refuted", "refutes", "refute"):
        return "failed"
    if text in ("verified", "true", "yes", "passed", "supports"):
        return "verified"
    return "pending"


def bits_of(*, numeric: Any = None, numeric_evidence: Mapping[str, Any] | None = None,
            numeric_reason: str = "", proof: Any = None, proof_process: str = "",
            reviewed: Any = None, reviewed_by: Mapping[str, Any] | None = None,
            formal: Any = None, formal_evidence: Mapping[str, Any] | None = None,
            formal_reason: str = "", audited: Any = None,
            audited_by: Mapping[str, Any] | None = None, origin: str = "own_result",
            source_lit_id: str = "", quote_verified: Any = None,
            voided_by: Mapping[str, Any] | None = None,
            kind: str = "") -> dict[str, Any]:
    """把各方标下的读数组装成五元位（纯函数：不读盘、不写盘）。

    ## 引用命题那一条（`draft/39` §3.15 三）

    `origin=external_lit` 且引到一条逐字核过的来源（`quote_verified is True`）⇒
    第 2 位（有证明）与第 3 位（审过）直接为真，凭据是文献代号（不是 V 的走查）。
    引用来的命题因此最多到"预备定理级"（第 4 位要形式化，第 5 位要 G 申请 H 审）。
    """
    cited = bool(source_lit_id) and origin == "external_lit" and quote_verified is True
    bits: dict[str, Any] = {
        "numeric": _state(numeric),
        "proof": bool(proof) or cited or bool(proof_process.strip()),
        "reviewed": bool(reviewed) or cited,
        "formal": _state(formal),
        "audited": bool(audited),
        "origin": str(origin or "own_result"),
        "evidence": {
            "numeric": dict(numeric_evidence or {}),
            "numeric_reason": str(numeric_reason or ""),
            "proof_process": str(proof_process or ""),
            # 第 2 位是怎么来的：`citation`（引用命题，凭据是文献代号）还是 `own`（我方证明过程）。
            # 这一栏必须显式落 —— 否则"引用命题的第 2 位"会被 `bit_problems` 当成
            # "自己写了证明却没写过程"而报缺陷（判据分不出两者等于两者被压成一件事）。
            "proof_source": "citation" if cited else ("own" if proof else ""),
            "reviewed_by": dict(reviewed_by or ({"evidence": f"lit:{source_lit_id}"} if cited else {})),
            "formal": dict(formal_evidence or {}),
            "formal_reason": str(formal_reason or ""),
            "audited_by": dict(audited_by or {}),
        },
        "voided_by": dict(voided_by or {}),
    }
    bits["grade"] = derive_grade(bits, kind=kind)
    bits["audited_badge"] = (bool(bits["audited"])
                             and bits["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return bits


def quote_state(row: Mapping[str, Any]) -> str:
    """一条引文现在的状态（引文回验的唯一读口径，2026-10-14 业主裁定之后）。

    业主那句话：「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」。
    于是"通过"这件事分两档，四态字面量：

    - `"verbatim"`：逐字命中（`quoteverify.check_quote` 那一档，不花模型钱）；
    - `"semantic"`：语义相同（H 判的；允许改写、换记号、跨语言）；
    - `"mismatch"`：查过了、不一致（`quote_verified is False`）——语义档也救不了它：
      H 的判据是"引文与来源说同一件事"，"结论强于引文"照样落这一档；
    - `"unchecked"`：还没查（`None`），或者方式那一栏是认不出的词
      （词表外的值 ⇒ 说不出怎么通过的 ⇒ 按没查算）。

    空 `quote_mode` 按 `verbatim` 读（历史事实，不是默认值）：这一栏是 2026-10-14
    才有的，在那之前 `quote_verified=True` 只可能来自 `quoteverify.check_quote`
    （逐字那一档）—— 判据 `test_a_legacy_external_lit_row_keeps_its_citation_credit`
    钉着这条读法。新的写入方必须说明方式：`schema` 拒绝词表外的值，B 的语义档要
    显式写 `semantic`（那条链的判据在 `tests/test_quote_semantics.py`）。

    为什么读侧还要再判一次（写侧 `schema._normalize_quote_mode` 已经归一过）：盘上是
    JSON —— 手改的行、旧版本写的行、别的工具写的行都可能绕过构造器。这一条是"读的人
    永远看到自洽的一对"的兜底，`bits_from_row` 与收工门都走它。
    """
    verified = row.get("quote_verified")
    if verified is None:
        return "unchecked"
    if verified is not True:
        return "mismatch"
    mode = str(row.get("quote_mode") or "")
    if mode == "":
        return "verbatim"          # 历史行：唯一可能的来路（见上面那段）
    return mode if mode in QUOTE_MODES else "unchecked"


def quote_explains_itself(row: Mapping[str, Any]) -> bool:
    """这一行的"通过"有没有说出方式（`True` 且方式在两档词表里）。"""
    return quote_state(row) in QUOTE_MODES


def bits_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """台账里的一行 ⇒ 五元位（唯一的读入口：判据、门、状态报告都走这里）。

    两条路：

    - 行里有 `bits` 记录（新写的行）⇒ 按四态/布尔重新规范化一遍再派生等级
      （等级永远现算，不信盘上存的等级 —— 存的那份只当缓存，判据不读它）；
    - 行里没有位记录（旧行）⇒ 一律按"五位全空"算，只有引用命题那一条例外
      （`origin=external_lit` + `quote_verified` ⇒ 第 2+3 位为真，凭据是文献代号）。

    为什么旧行要按全空算：`statements.status='proved'`、`evidence_kind='proof'` 这些
    都是自报的。五元位这套东西存在的理由就是"自报不算凭据"——若这里给旧行补一个
    尊重的读法，那套纪律当场破功（而且历史上正是那些自报字段把"数值支持"读成了"已证明"）。
    """
    raw = dict(row.get("bits") or {})
    origin = str(row.get("origin") or "own_result")
    kind = str(row.get("kind") or "")
    if not raw:
        return bits_of(origin=origin, source_lit_id=str(row.get("source_lit_id") or ""),
                       quote_verified=quote_explains_itself(row), kind=kind)
    bits = normalize_raw(raw, origin=origin, kind=kind,
                         voided_by=dict(raw.get("voided_by") or row.get("refuted_by") or {}))
    return _stale_review_cleared(bits, row, kind=kind)


def _stale_review_cleared(bits: dict[str, Any], row: Mapping[str, Any], *,
                          kind: str = "") -> dict[str, Any]:
    """第 3 位写的时候记了「签的是哪一份」而现行正文不是那一份 ⇒ 这一位读成没审过。

    ## 为什么读侧要判这一条（业主 2026-10-22 口径：哈希是读数，不是授权凭证）
    写侧把 `reviewed` 翻真时会把这一签盖住的那一份正文的 `proof_sha256` 连同证明号
    `proof_no` 记进 `evidence.reviewed_by`。此后正文可能又被改过（改稿是正常动作，
    不许因此拒写），而位还停在 `True` 上 —— 于是"审过"这个读数会过期。读侧的判据
    就一句：记下来的那份 sha 与它现在这一份不同 ⇒ 这一位现在不是"审过"，而是
    "签过、过期了"。
    ## 边界（三态：判不了就不判）
    - 位是假 ⇒ 什么都不做（没签过不是 stale）；
    - `reviewed_by` 里没有 `proof_sha256`（历史行 / 引用命题那条凭据是 `lit:` 代号）
      ⇒ 判不了，原样返回（不许把判不了的读成"过期"）；
    - 那一份证明的正文取不到（行里没有 `proof_text`，也没有对应证明号的清单项）
      ⇒ 判不了，原样返回。
    """
    if not bits.get("reviewed"):
        return bits
    ev = dict(bits.get("evidence") or {})
    reviewed_by = dict(ev.get("reviewed_by") or {})
    want = str(reviewed_by.get("proof_sha256") or "")
    if not want:
        return bits
    from . import verifications as _VR   # 惰性：证明号与 sha 的口径各只有一处

    proof_no = _VR.as_proof_no(reviewed_by.get("proof_no")) or 1
    text = _VR.proof_text_of(row, proof_no)
    if proof_no == 1 and "proof_text" not in row:
        return bits          # 部分调用方只喂 `bits`：没有正文可判
    got = _VR.proof_sha(text)
    if got == want:
        return bits
    out = dict(bits)
    out["reviewed"] = False
    out["grade"] = derive_grade(out, kind=kind)
    out["audited_badge"] = (bool(out.get("audited"))
                            and out["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return out


#: `bits` 这一栏里位本身之外允许出现的键（写台账时要经过 `bits_shape_problems`）。
BIT_META_KEYS: tuple[str, ...] = ("evidence", "voided_by", "origin", "grade", "audited_badge")


def normalize_raw(raw: Mapping[str, Any], *, origin: str = "own_result",
                  voided_by: Mapping[str, Any] | None = None,
                  kind: str = "") -> dict[str, Any]:
    """盘上那一栏 `bits` ⇒ 规范化的五位（布尔/四态都归一，等级现算）。

    读与写共用这一份：`bits_from_row`（读）与 `bits_shape_problems`（写之前把形状关）
    若各归一一次，就会出现"写进去判合规、读出来是另一个意思"的分家。
    """
    bits: dict[str, Any] = {
        "numeric": _state(raw.get("numeric")),
        "proof": bool(raw.get("proof")),
        "reviewed": bool(raw.get("reviewed")),
        "formal": _state(raw.get("formal")),
        "audited": bool(raw.get("audited")),
        "origin": origin,
        "evidence": dict(raw.get("evidence") or {}),
        "voided_by": dict(voided_by if voided_by is not None else (raw.get("voided_by") or {})),
    }
    bits["grade"] = derive_grade(bits, kind=kind)
    bits["audited_badge"] = (bool(bits["audited"])
                             and bits["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return bits


def bits_shape_problems(raw: Mapping[str, Any] | None, *,
                        kind: str = "") -> list[str]:
    """写台账之前把 `bits` 那一栏的形状关（未知键 / 自报等级与现算不一致 / 位自身不合规）。

    为什么连"自报的等级"也要管：判据从不读盘上那个等级（`bits_from_row` 永远现算），
    于是存一个与现算不符的等级不会改变任何结论 —— 它只会让读盘的人（包括模型自己）
    看到两个数。这种"看起来是读数、其实谁都不读"的字段正是本仓最忌的形态，所以在写入期
    直接拒掉：等级可以留着当缓存，但必须与现算逐字相同。
    """
    if not raw:
        return []
    if not isinstance(raw, Mapping):
        return ["bits 必须是对象（五位：numeric/proof/reviewed/formal/audited）"]
    problems: list[str] = []
    unknown = sorted(set(raw) - set(BIT_NAMES) - set(BIT_META_KEYS))
    if unknown:
        problems.append(
            f"bits 里有不认识的键 {unknown}：位的名字只有 {list(BIT_NAMES)}"
            f"（另加 {'/'.join(BIT_META_KEYS)}）—— 拼错的键会被静默忽略，"
            "于是它与「这一位还没填」长得一模一样")
    bits = normalize_raw(raw, origin=str(raw.get("origin") or "own_result"), kind=kind)
    claimed = raw.get("grade")
    if claimed is not None and str(claimed) != bits["grade"]:
        problems.append(
            f"bits.grade 写的是 {claimed!r}，按五位现算是 {bits['grade']!r} —— "
            "等级不许自报（判据永远现算）：要么删掉这个键，要么让它等于现算值")
    problems.extend(bit_problems(bits))
    return problems


def derive_grade(bits: Mapping[str, Any], *, kind: str = "") -> str:
    """五元位 ⇒ 等级（唯一的等级来源；任何角色自报的等级都不认）。

    第 1 位只做一件事：把"猜想"抬成"强猜想"——封顶就在这一条：
    数值验证再多、再强，也到不了"定理"（用户口径：数值验证不构成证明）。

    `kind="concept"` 短路（`draft/97` §14.5，业主 2026-10-09「concept 表真并进
    statements……proof 里就证这个概念为什么是良定义的」）：概念不参与这条链。
    它没有证据位（`bits={}`），若照常派生，现算结果是最弱那一档 ——
    于是并表之后每条概念都会被读成"猜想"，而"猜想"在报告里是一句关于真值的话，
    概念根本没有真值可言（它只有"良定义没良定义"）。所以这一档单独给一个值
    （`GRADE_NOT_APPLICABLE`），它不在 `GRADES` 里 —— 不参与排序、不算进定理计数。
    """
    if str(kind or "") == "concept":
        return GRADE_NOT_APPLICABLE
    if bits.get("voided_by"):
        return "conjecture"          # 作废之后等级清零（历史留在 voided_by 里）
    has_proof = bool(bits.get("proof"))
    reviewed = bool(bits.get("reviewed"))
    formal = _state(bits.get("formal")) == "verified"
    if has_proof and formal:
        return "theorem"
    if has_proof and reviewed:
        return "pre_theorem"
    if _state(bits.get("numeric")) == "verified":
        return "strong_conjecture"
    return "conjecture"


def bit_problems(bits: Mapping[str, Any]) -> list[str]:
    """五元位自身的完备性问题（空列表 = 合规）。

    三态纪律：`na`（不适用）与 `failed`（做了没通过）都必须写理由/原文；
    `verified` 必须带能复跑的凭据，而且凭据要指名道姓：

    - 第 1 位（数值验证）⇒ 要写清是哪条实验/哪个脚本测的（`experiments` 或 `script`）；
    - 第 4 位（形式化通过）⇒ 要写清是哪个检查器（`checker`）。

    为什么凭据要写到这么细（E3 迁移重放挖出来的，`draft/39` §6.2 五）：p6e 那一趟真的跑过
    两条 `method=formal` 实验，而没有任何命题指向它们 ⇒ "形式化做过"在位上是不可见的。
    位的凭据里若不写"是哪一次实验/哪一个检查器"，同一件事会以"看起来做过"与"查不出来"
    两种形态并存，而这两种在报告里长得一样。
    """
    problems: list[str] = []
    ev = dict(bits.get("evidence") or {})
    for name, key in (("numeric", "numeric"), ("formal", "formal")):
        state = _state(bits.get(name))
        if state == "na" and not str(ev.get(f"{key}_reason") or "").strip():
            problems.append(f"{name}=na 必须写理由（为什么这条命题不适合{'数值验证' if name == 'numeric' else '形式化'}）")
        if state == "failed" and not (str(ev.get(f"{key}_reason") or "").strip()
                                      or ev.get(key)):
            problems.append(f"{name}=failed 必须带原文（脚本/检查器输出）")
        if state == "verified" and not ev.get(key):
            problems.append(f"{name}=verified 必须带凭据（脚本 + sha，或检查器输出）")
    if _state(bits.get("numeric")) == "verified":
        num = dict(ev.get("numeric") or {})
        # 只在"有凭据但凭据没指针"时报这一条：凭据为空时上面那条已经点过名了，
        # 同一件事报两次会让"改哪里"变得不清楚（一条缺陷只留一条可行动的话）。
        if num and not (num.get("experiments") or num.get("experiment_id")
                        or num.get("script") or num.get("scripts")):
            problems.append("numeric=verified 必须写明是哪条实验/哪个脚本测的"
                            "（experiments / experiment_id / script）—— 没有指针的凭据复跑不了")
    if _state(bits.get("formal")) == "verified":
        formal = dict(ev.get("formal") or {})
        if formal and not str(formal.get("checker") or "").strip():
            problems.append("formal=verified 必须写明是哪个检查器（checker：lean4 / coq / isabelle…）")
    if (bits.get("proof") and not str(ev.get("proof_process") or "").strip()
            and ev.get("proof_source") != "citation"):
        problems.append("proof=true 必须带证明过程（逐步论证）")
    if bits.get("reviewed") and not ev.get("reviewed_by"):
        problems.append("reviewed=true 必须带凭据（自己产出 ⇒ V 的三态结论；引用 ⇒ 文献代号）")
    if bits.get("audited") and not ev.get("audited_by"):
        problems.append("audited=true 必须带 H 的审校轮次与结论")
    return problems


#: 五元位 ⇒ 哪张表在维护它（业主 2026-10-09：「再确认一条命题的五元状态是哪张表在维护，
#: 要做好映射（如果五元状态里说有证明，证明应该在 B 维护的表里可查）」）。
#:
#: 每一格四件事：`owner`（谁签的字）/ `ledger`（去哪张表的哪个字段查）/ `pointer`
#: （位里写的那个可追查凭据字段）/ `criteria`（位说 `verified` 时，台账里必须查得到什么）。
#:
#: 为什么要有这张表：位是读数，表是凭据。只说"这一位是 verified"而不说
#: "去哪张表里能查到它"，五元状态就会退化成自报 —— 而"自报不算凭据"正是这套位存在的理由
#: （见 `bits_from_row` 的 docstring）。映射写在这里而不是散在判据里，是为了让
#: "哪一位归哪张表"只有一个出处：`verify.py` 的第 13 段按这张表派判据。
#:
#: 第五位（正式审查）与第三位（审过）的凭据是按稿件钉的（V/H 的审校结论落在稿件上），
#: 所以它们的 `ledger` 是 `documents` 而非命题表：命题这一级只看得见 `doc_id`，
#: "doc_id 存不存在"由 `verify` 的 `dangling_doc_ref` 守。这一格刻意不产生命题级判据 ——
#: 命题没有 `doc_id` 时那一档判不了，报一条假的 error 比不报更糟（会训练人忽略告警）。
BIT_LEDGERS: dict[str, dict[str, str]] = {
    "numeric": {
        "owner": "E",
        "ledger": "experiments（method='numeric'）",
        "pointer": "bits.evidence.numeric 里的 experiment_id / experiments / script",
        "criteria": "位说 verified ⇒ 指针指的那条实验行必须在 experiments 表里，且 method='numeric'",
    },
    "proof": {
        "owner": "F",
        "ledger": "statements.proof_text（B 维护的那张表）",
        "pointer": "命题自己那一行（同表内查，不需要跨表指针）",
        "criteria": "位说 true ⇒ 同行的 proof_text 非空（证明过程逐步可读）；"
                    "引用命题例外（凭据是文献代号 + 逐字核验）",
    },
    "reviewed": {
        "owner": "V",
        "ledger": "documents（V 的审校结论，按稿件钉）",
        "pointer": "doc_id",
        "criteria": "位说 true ⇒ V 的结论挂在稿件上 ⇒ 命题级只查 doc_id 在不在册"
                    "（由 dangling_doc_ref 守）；没有 doc_id ⇒ 判不了，不报",
    },
    "formal": {
        "owner": "E",
        "ledger": "experiments（method='formal'）",
        "pointer": "bits.evidence.formal 里的 experiment_id / checker",
        "criteria": "位说 verified ⇒ 指针指的那条实验行必须在 experiments 表里，且 method='formal'",
    },
    "audited": {
        "owner": "H",
        "ledger": "documents（H 的审校轮次与结论，按稿件钉；G 申请）",
        "pointer": "doc_id",
        "criteria": "同第 3 位：命题级判不了，只查稿件在不在册",
    },
}


def bit_ledger(bit: str) -> dict[str, str]:
    """取某一位的台账映射（未知位 ⇒ 空 dict，调用方按"没查成"处理，不按"查过了没问题"）。"""
    return dict(BIT_LEDGERS.get(str(bit), {}))


def bit_evidence_gaps(row: Mapping[str, Any], *,
                      experiments: Iterable[Mapping[str, Any]] = (),
                      ) -> list[dict[str, str]]:
    """五元位与它们各自的台账对不对得上（空列表 = 位说的都能在表里查到）。

    只判跨表的那一半（"位说有证明 ⇒ 证明在 B 的表里可查"）：位自身的形状
    （`na` 要理由、`verified` 要凭据）由 `bit_problems` 判，这里不重复。

    三条判据，各守一种病：

    1. `proof` 位为真而 `statements.proof_text` 空（`bits_proof_without_evidence`，error）：
       位上说"有证明"，去 B 维护的那张表里却查不到证明过程 —— 这正是业主点名的形态。
       引用命题（`evidence.proof_source == 'citation'`）不在此列：它的凭据是文献代号
       ＋逐字核验，证明过程在别人的文献里，不在我们的台账里。
    2. 指针指的实验行不存在（`bits_evidence_pointer_dangling`，error）：位里的凭据
       指名道姓写了 `experiment_id`，而 experiments 表里没有这一行 ⇒ 这条凭据复跑不了，
       且"复跑不了"与"跑过"在报告里长得一样。
    3. 指针指的实验行存在但 `method` 不是这一位该有的（`bits_evidence_method_mismatch`，
       warning）：拿一条数值实验当形式化凭据（或反之）—— 三态纪律里这是"查了别的东西"
       而不是"没查"，所以看得见但不拦门。

    边界（三态）：没有指针时不报（`bit_problems` 已经报过"凭据要指名道姓"，
    同一件事报两次会让"改哪里"变得不清楚）；experiments 表读不到时由调用方给空序列，
    此时指针行必然"不存在" —— 所以调用方必须先确认表读到了再判第 2/3 条。
    """
    bits = bits_from_row(row)
    ev = dict(bits.get("evidence") or {})
    by_exp = {str(e.get("experiment_id") or ""): e for e in experiments}
    gaps: list[dict[str, str]] = []

    if bits.get("proof"):
        text = str(row.get("proof_text") or "").strip()
        cited = str(ev.get("proof_source") or "") == "citation"
        if not text and not cited:
            gaps.append({
                "bit": "proof", "level": "error", "code": "bits_proof_without_evidence",
                "reason": ("第 2 位（有证明）为真，而 statements.proof_text 是空的 ⇒ "
                           "去 B 维护的那张表里查不到证明过程（位上说有、表里没有）；"
                           "要么把证明过程写进 proof_text，要么把这一位降下来"),
            })

    for bit, method, key in (("numeric", "numeric", "numeric"), ("formal", "formal", "formal")):
        if _state(bits.get(bit)) != "verified":
            continue
        payload = dict(ev.get(key) or {})
        # 指针可能写成单个号（`experiment_id`）或一列号（`experiments`）—— 两种都要认，
        # 而且列要摊平：把整列 `str()` 成一个号，报出来的就是一条查不到的假指针
        # （"0001,0002" 这种号永远不会在表里，负控会以"表里没有"的形态假绿）。
        raw: list[Any] = []
        for cand in (payload.get("experiment_id"), payload.get("experiments"),
                     payload.get("experiment_ids")):
            if isinstance(cand, (list, tuple, set)):
                raw.extend(cand)
            elif str(cand or "").strip():
                raw.append(cand)
        ids = [x for x in dict.fromkeys(str(v) for v in raw) if x]
        for eid in ids:
            hit = by_exp.get(eid)
            if hit is None:
                gaps.append({
                    "bit": bit, "level": "error", "code": "bits_evidence_pointer_dangling",
                    "reason": (f"第 {'1' if bit == 'numeric' else '4'} 位为 verified，凭据指向实验 "
                               f"{eid!r}，而 experiments 表里没有这一行 ⇒ 这条凭据复跑不了"
                               "（台账映射：" + BIT_LEDGERS[bit]["ledger"] + "）"),
                })
                continue
            got = str(hit.get("method") or "")
            if got and got != method:
                gaps.append({
                    "bit": bit, "level": "warning", "code": "bits_evidence_method_mismatch",
                    "reason": (f"第 {'1' if bit == 'numeric' else '4'} 位为 verified，凭据指的实验 "
                               f"{eid!r} 的 method={got!r}（这一位要 method={method!r}）⇒ "
                               "等于拿另一类证据当这一位的凭据"),
                })
    return gaps


def clean_statement_ids(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """I4（`draft/39` §3.21 二）：哪些命题算"干净"的引用对象（引用它不必重验）。

    两类进干净集合，各有明确凭据：

    1. 我方命题：五位派生出「预备定理级」或「正式定理」（第 2 位 + 第 3/4 位）——
       它的证明过程与被审记录都在册，引用它只需如实呈现，不重验；
    2. 引用命题（`origin=external_lit` 且 `quote_verified is True`）：凭据是文献代号 +
       逐字核过的那一份原文 —— 这正是 I4 说的"来源已验证过的，如实呈现、不重验"。

    返回 `{"clean": [...], "reasons": {id: 理由}}`：理由逐条留下（"为什么它能被信"可复核），
    而不在集合里的就是"引用它要小心"的（还在猜想 / 已作废 / 没逐字核过）。
    """
    clean: list[str] = []
    reasons: dict[str, str] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("id") or "")
        if not sid:
            continue
        bits = bits_from_row(row)
        if bits.get("voided_by"):
            reasons[sid] = "已作废（不能作为依据）"
            continue
        if str(bits.get("origin") or "") == "external_lit":
            state = quote_state(row)
            if state in QUOTE_MODES:
                clean.append(sid)
                how = "逐字核过" if state == "verbatim" else "语义核过（H 判：与来源说同一件事）"
                reasons[sid] = f"引用命题：{how}（凭据 lit:{row.get('source_lit_id')}）"
            else:
                reasons[sid] = ("引用命题但没核过（逐字与语义两档都没有）"
                                "⇒ 不许当依据（I4 的边界）")
            continue
        if str(row.get("kind") or "") == "concept":
            # 概念行不参与等级（`draft/97` §14.5）⇒ 它当然不在"干净引用对象"里，
            # 但理由必须说对：不是"等级太低"，而是"它不是一条有真值的断言"。
            reasons[sid] = ("概念行（不参与等级）：引用概念要引它的定义，"
                            "而不是把它当定理用")
            continue
        if str(bits.get("grade") or "") in ("pre_theorem", "theorem"):
            clean.append(sid)
            reasons[sid] = (f"我方命题：{GRADE_LABELS.get(str(bits.get('grade')))}"
                            "（第 2 位 + 第 3/4 位）")
        else:
            reasons[sid] = (f"等级只有「{GRADE_LABELS.get(str(bits.get('grade')))}」"
                            "⇒ 引用它要小心")
    return {"clean": clean, "reasons": reasons}


def cascade_void(rows: Iterable[Mapping[str, Any]], *, root: str,
                 reason: str = "") -> dict[str, Any]:
    """I1（级联作废）：一条命题作废 ⇒ 依赖它的那些证明的五位读数一并失效。

    依赖边取自 `derived_from`（本表内的 `stmt_id` 列表：这条命题用到了哪些别的命题）。
    闭包按"谁引用了作废者"逐层扩（A 作废 ⇒ 引 A 的 B 作废 ⇒ 引 B 的 C 作废…），
    每一行的 `voided_by` 里记着 `kind="cascade"` 与根（是谁引起的），
    于是"这一条为什么作废"永远能追到那个数值反例或构造。

    三态与边界：

    - 环（A 引 B、B 引 A）不许把判据卡死：已访问集合挡住，环本身记进 `cycles` 读数；
    - 找不到的引用（引了一条不在册的 id）记进 `missing`，不影响闭包继续
      （悬空引用是另一个缺陷，由别处报）；
    - 根自己那条由调用方按 §3.18 的四条判据先作废（这里不重复判）。

    返回 `{"dependents": [...], "voided_by": {id: 载荷}, "cycles": [...], "missing": [...]}`。
    """
    root_id = str(root or "").strip()
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("id") or "")
        if sid:
            by_id[sid] = row
    if root_id not in by_id:
        return {"dependents": [], "voided_by": {}, "cycles": [], "missing": [root_id],
                "note": "根命题不在这一批行里 ⇒ 级联判不了（没查成，不是「没有依赖」）"}
    importers: dict[str, list[str]] = {}
    missing: list[str] = []
    for sid, row in by_id.items():
        for dep in (row.get("derived_from") or []):
            dep_id = str(dep)
            if dep_id not in by_id:
                missing.append(f"{sid}→{dep_id}")
                continue
            importers.setdefault(dep_id, []).append(sid)
    dependents: list[str] = []
    voided_by: dict[str, Any] = {}
    cycles: list[str] = []
    seen = {root_id}

    def walk(node: str, path: tuple[str, ...], *, depth: int) -> None:
        """按"谁引用了它"往下走；只有回到当前路径上的祖先才算环。

        为什么用路径而不是"已访问"判环（第一版就错在这里）：菱形依赖
        （A←B、A←C、B←D、C←D）里 D 会被访问两次，而它不是环 ——
        用"已访问"会把菱形误报成环。真环的判据是"这条边指回当前这条路径上的某个节点"。
        """
        if depth > 200:                                    # pragma: no cover - 防御性上限
            return
        for imp in importers.get(node, []):
            if imp in path:
                cycles.append(f"{imp}↔{node}")
                continue
            if imp in seen:
                continue
            seen.add(imp)
            dependents.append(imp)
            voided_by[imp] = {"kind": "cascade", "root": root_id, "via": node,
                              "reason": str(reason or
                                            f"依赖的 {node} 已作废 ⇒ 五位一并失效")}
            walk(imp, path + (imp,), depth=depth + 1)

    walk(root_id, (root_id,), depth=0)
    return {"dependents": dependents, "voided_by": voided_by,
            "cycles": sorted(set(cycles)), "missing": sorted(set(missing))}


def apply_cascade(rows: Iterable[Mapping[str, Any]], *, root: str,
                  reason: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按 `cascade_void` 的结果把行改好（返回 `(改后的行, 读数)`）—— 调用方负责落库。

    只改 `bits.voided_by`（等级由 `derive_grade` 现算 ⇒ 自动回到"猜想"），
    其余字段一个字不动：作废是"读数失效"，不是"把条目删掉或改写内容"。
    """
    got = cascade_void(rows, root=root, reason=reason)
    out: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        sid = str(row.get("stmt_id") or row.get("id") or "")
        mark = got["voided_by"].get(sid)
        if mark:
            bits = dict(row.get("bits") or {})
            bits["voided_by"] = mark
            row["bits"] = bits
        out.append(row)
    return out, got


#: 作废需要的四条（`draft/39` §3.18）：缺一条都不许作废。
VOID_CONDITIONS: tuple[str, ...] = (
    "script_exit_ok", "structured_verdict", "counterexample_present", "counterexample_valid",
)


def void_refusal(experiment: Mapping[str, Any] | None, *,
                 verdict: str = "", counterexample_valid: Any = None) -> str:
    """能不能用这条实验作废命题？返回拒绝理由（空串 = 允许作废）。

    四条同时成立才允许：① 脚本正常退出；② 脚本自己给出结构化结论；
    ③ 反例非空且可复现（脚本 + sha + 参数齐全）；④ 反例确实是这条命题的反例。
    """
    e = dict(experiment or {})
    if e.get("exit_code") not in (0, "0"):
        return "脚本没有正常退出（超时/崩溃 ⇒ inconclusive，不许作废）"
    # 结论要来自脚本自己：台账行里记了 `result` 就以它为准（调用方转述的 `verdict`
    # 只在这一行没记结论时才用）—— 否则"人说 refutes、行说 inconclusive"会被放行。
    stated = _state(e.get("result")) if e.get("result") else _state(verdict)
    if stated != "failed":
        return "脚本没有给出 refutes 的结构化结论（不是它说的，不算）"
    if not e.get("counterexample"):
        return "反例为空 ⇒ 不许作废（脚本报错与命题为假必须分得开）"
    if not (e.get("code_path") and e.get("code_hash")):
        return "反例不可复现（缺 code_path / code_hash）"
    if counterexample_valid is not True:
        return "反例是否成立没有结论（要 D 给'成立/有毛病/看不出来'里的一个）"
    return ""


def void(experiment: Mapping[str, Any], *, verdict: str = "", counterexample_valid: Any = None,
         construction: str = "") -> dict[str, Any]:
    """作废一个命题：返回 `voided_by` 载荷（调用方把它写进台账；五位读数一并作废、条目保留）。"""
    if construction.strip():
        return {"kind": "construction", "construction": construction.strip()}
    reason = void_refusal(experiment, verdict=verdict, counterexample_valid=counterexample_valid)
    if reason:
        raise ValueError(f"不许作废：{reason}")
    e = dict(experiment)
    return {"kind": "numeric_counterexample", "experiment_id": e.get("experiment_id"),
            "script": e.get("code_path"), "sha": e.get("code_hash"),
            "counterexample": e.get("counterexample")}
