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

from typing import Any, Mapping

#: 第 1/4 位的四态（顺序就是"从没做到做到了"的强弱）。
BIT_STATES: tuple[str, ...] = ("pending", "na", "failed", "verified")
#: 派生等级（由弱到强；`audited` 是并列的追加档，不进这个序列）。
GRADES: tuple[str, ...] = ("conjecture", "strong_conjecture", "pre_theorem", "theorem")
GRADE_LABELS: dict[str, str] = {
    "conjecture": "猜想",
    "strong_conjecture": "强猜想",
    "pre_theorem": "预备定理级",
    "theorem": "正式定理",
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
            voided_by: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    bits["grade"] = derive_grade(bits)
    bits["audited_badge"] = bool(bits["audited"]) and bits["grade"] != "conjecture"
    return bits


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
    if not raw:
        return bits_of(origin=origin, source_lit_id=str(row.get("source_lit_id") or ""),
                       quote_verified=row.get("quote_verified"))
    ev = dict(raw.get("evidence") or {})
    bits: dict[str, Any] = {
        "numeric": _state(raw.get("numeric")),
        "proof": bool(raw.get("proof")),
        "reviewed": bool(raw.get("reviewed")),
        "formal": _state(raw.get("formal")),
        "audited": bool(raw.get("audited")),
        "origin": origin,
        "evidence": ev,
        "voided_by": dict(raw.get("voided_by") or row.get("refuted_by") or {}),
    }
    bits["grade"] = derive_grade(bits)
    bits["audited_badge"] = bool(bits["audited"]) and bits["grade"] != "conjecture"
    return bits


def derive_grade(bits: Mapping[str, Any]) -> str:
    """五元位 ⇒ 等级（唯一的等级来源；任何角色自报的等级都不认）。

    第 1 位只做一件事：把"猜想"抬成"强猜想"——封顶就在这一条：
    数值验证再多、再强，也到不了"定理"（用户口径：数值验证不构成证明）。
    """
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
    `verified` 必须带凭据（脚本 + sha 或检查器输出）。
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
    if (bits.get("proof") and not str(ev.get("proof_process") or "").strip()
            and ev.get("proof_source") != "citation"):
        problems.append("proof=true 必须带证明过程（逐步论证）")
    if bits.get("reviewed") and not ev.get("reviewed_by"):
        problems.append("reviewed=true 必须带凭据（自己产出 ⇒ V 的三态结论；引用 ⇒ 文献代号）")
    if bits.get("audited") and not ev.get("audited_by"):
        problems.append("audited=true 必须带 H 的审校轮次与结论")
    return problems


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
