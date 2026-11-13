# -*- coding: utf-8 -*-
"""台账命题「错误」与等级「错误」的唯一读口，外加双读过渡的两个常量。

## 一个概念、两处读法、必须恒等（业主 2026-11-13 的裁定）

台账命题被证伪是一件事，它在两个地方各有一个读法：

- 状态轴：`statements.status`（今天叫 `refuted`，词表补丁落地后叫 `error`）；
- 等级轴：`evidencebits.derive_grade` 算出来的 `GRADE_ERROR`（「错误」）。

两处读法必须恒等：`status=错误 ⇔ 等级=错误`。本模块是把这句话变成机器判据的唯一地方：

- :func:`statement_refuted` —— 台账命题的三态读口（是 / 不是 / 读不出来）；
- :func:`conjecture_refuted` —— 临时命题（F 侧计划中命题 / E 侧命题 / B 侧命题）的三态读口。

不许再在别处直比 `status == "refuted"` 或 `grade == "错误"`：那正是"两处读法各自
说话"的形态，现场一旦出现一行只有一边成立，就没有任何读数会响（本仓最忌的
"看起来在检查、实际什么都没检查"）。

## 双读过渡（业主选的甲方案：代码先跑通、词表等人审）

`schema.STATEMENT_STATUSES` 现在是 `… "refuted" …`，补丁落地后变 `… "error" …`。
本模块的常量从词表现取：

- :data:`ERROR_WORD` —— 写侧唯一落点：词表里有 `error` 就写 `error`，否则写 `refuted`；
- :data:`ERROR_WORDS` —— 读侧认的词：`error` 与 `refuted` 里词表声明了的那些。

于是补丁一落地，写口自动改落 `error`、读口自动只认 `error`（另一词变成"不认识的状态"
⇒ 读不出来，而不是静默读成"不是错"）。判据
`tests/test_one_concept_two_readings.py::test_the_word_follows_the_vocabulary` 钉住这一跳。

## 三态与三个冲突码

`state` 只有三档：`error`（是）/ `not_error`（不是）/ `unknown`（读不出来）。

`unknown` 里能归因的三种恒等被破坏形态各有一个受控码（`conflict`）：

= ========================== ============================================================
`status_without_payload`     `status=错误` 而 `bits.voided_by` 没有（或自称证伪签却读不出来）
                             ⇒ 说不出凭什么判它错（等级只能读成「猜想」）
`payload_without_status`     作废载荷在、等级也读成「错误」，而 `status` 不是错误那一档
                             ⇒ 状态那一半没跟上（例如 `superseded` 行挂着证伪载荷）
`status_grade_disagree`      `status=错误` 且载荷也在，但等级现算不是「错误」
                             ⇒ 两处读法真的分家了（例如证伪签口袋坏掉、否决没生效）
= ========================== ============================================================

没有冲突码的 `unknown` 是"这一行根本没查到"（不在册 / 台账读不出来 / 状态词不在词表里）。

## 边界：临时命题不参与这条恒等

临时命题没有五元位、没有等级，所以 `refuted` 在它那一侧不是"等级错误"的反面。
它判的是另一件事：这条还没进台账的命题已经被判错、拒收了。证据两选一：

- `counterexample_experiment_id`（被一次反例实验否证）；
- `refusal_ref`（注册期被判错、拒收记录的引用；FC-27 补丁给 `Conjecture` 加的那一格）。

两件都没有 ⇒ 读不出来（`status_without_payload`）——不许为了凑过 `validate` 假造实验号。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import evidencebits as _EB
from . import schema as _S

# ---------------------------------------------------------------- 状态三态

#: 这条命题就是错的。
STATE_ERROR = "error"
#: 这条命题不是错的（读得出、两边一致）。
STATE_NOT_ERROR = "not_error"
#: 读不出来（没查到 / 词表外的状态 / 两处读法分家）。与"不是错的"分得开。
STATE_UNKNOWN = "unknown"

#: 冲突码：`status=错误` 但拿不出作废载荷（说不出凭什么错）。
CONFLICT_STATUS_WITHOUT_PAYLOAD = "status_without_payload"
#: 冲突码：作废载荷在、等级也读成「错误」，而 `status` 不是错误那一档。
CONFLICT_PAYLOAD_WITHOUT_STATUS = "payload_without_status"
#: 冲突码：`status=错误` 且载荷在，但等级现算不是「错误」。
CONFLICT_STATUS_GRADE_DISAGREE = "status_grade_disagree"

# ---------------------------------------------------------------- 双读过渡

#: 写侧唯一落点：词表里活着的是哪个词就写哪个（补丁落地后自动变 `error`）。
ERROR_WORD: str = "error" if "error" in _S.STATEMENT_STATUSES else "refuted"

#: 读侧认的词：`error` / `refuted` 里词表声明了的那些。
#: 为什么按词表过滤而不是两个都认：补丁落地后 `refuted` 不在词表里了，盘上若还有
#: 这种行，它必须读成"不认识的状态"（`unknown`），不许继续冒充错误或悄悄变成"不是错"。
ERROR_WORDS: tuple[str, ...] = tuple(
    w for w in ("error", "refuted") if w in _S.STATEMENT_STATUSES
)
if not ERROR_WORDS:  # pragma: no cover - 词表被改坏时导入期就炸（不留静默降级）
    raise RuntimeError(
        "schema.STATEMENT_STATUSES 里既没有 'error' 也没有 'refuted' ⇒ "
        "「错误」这一档没有落点（两处读法无处恒等）"
    )

# ---------------------------------------------------------------- 临时命题三态

#: 临时命题被判错、拒收（`conjectures.status`）。
CONJ_STATE_REFUTED = "refuted"
#: 临时命题不是被拒的那一档。
CONJ_STATE_NOT_REFUTED = "not_refuted"
#: 临时命题读不出来（不在册 / 状态词不在词表 / `refuted` 拿不出两件凭据之一）。
CONJ_STATE_UNKNOWN = "unknown"


def _blank(*, why: str = "") -> dict[str, Any]:
    """一份"读不出来"的读数骨架（三态里的第三态，绝不折成 `not_error`）。"""
    return {"checked": False, "found": False, "state": STATE_UNKNOWN,
            "why": str(why or "没查到"), "conflict": "", "status": "",
            "word": "", "grade": "", "error_by_sign": False, "error_by_evidence": False,
            "voided_by": {}}


def _statement_error_reading(row: Any) -> dict[str, Any]:
    """私有判据（唯一一份）：一行台账命题 ⇒ `error` / `not_error` / `unknown`。

    读两处：`status`（状态轴）与 `evidencebits.bits_from_row` 现算的等级（等级轴），
    再拿 `bits.voided_by` 判"凭什么"。三处任何一处对不上都落在 `unknown` + 冲突码上，
    而不是挑一边信。

    为什么等级要现算而不是读 `bits.grade`：那一格只是缓存（`bits_from_row` 会现算并
    覆盖），判据读缓存就等于让写的那一刻说了算 —— 而"两处读法恒等"要的正是"现在读出来
    是什么"。
    """
    out = _blank()
    if not isinstance(row, Mapping) or not row:
        out["why"] = "没有行 ⇒ 读不出来（不猜成'不是错'）"
        return out
    status = str(row.get("status") or "")
    out.update(checked=True, found=True, status=status, word=status)
    out["why"] = ""
    if status and status not in _S.STATEMENT_STATUSES:
        out["why"] = (f"status={status!r} 不在 STATEMENT_STATUSES 里 ⇒ 这一行读不出状态"
                      f"（认识的词是 {_S.STATEMENT_STATUSES}）")
        return out
    try:
        bits = _EB.bits_from_row(dict(row))
        grade = _EB.derive_grade(bits, kind=str(row.get("kind") or ""))
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"不是错"
        out["why"] = f"五元位 / 等级读不出来（{type(exc).__name__}: {exc}）"
        return out
    payload = dict(bits.get("voided_by") or {})
    sign_reading = _EB.refutation_reading(bits)
    claims_sign = str(payload.get("kind") or "") == _EB.REFUTATION_SIGN_KIND
    sign_ok = bool(sign_reading.get("checked") and sign_reading.get("sign"))
    out.update(grade=grade, voided_by=payload, error_by_sign=bool(claims_sign and sign_ok),
               error_by_evidence=bool(payload) and not (claims_sign and sign_ok))
    is_error_word = status in ERROR_WORDS
    grade_is_error = grade == _EB.GRADE_ERROR
    if claims_sign and not sign_ok:
        # 自称证伪签却读不出那三格：这不是"没有证伪"，是"说不出凭什么"。
        out.update(conflict=CONFLICT_STATUS_WITHOUT_PAYLOAD,
                   why=("`bits.voided_by.kind=refutation_sign` 而证伪签读不出来"
                        f"（{sign_reading.get('why') or '签口袋不在 / 缺格'}）⇒ 不许当证伪"))
        return out
    if not payload and is_error_word:
        out.update(conflict=CONFLICT_STATUS_WITHOUT_PAYLOAD,
                   why=("status=错误 而 `bits.voided_by` 是空的 ⇒ 说不出凭什么判它错"
                        "（等级只能读成「猜想」）"))
        return out
    if is_error_word:
        if not grade_is_error:
            out.update(conflict=CONFLICT_STATUS_GRADE_DISAGREE,
                       why=(f"status=错误 且作废载荷在，但等级现算是 {grade!r} 而不是"
                            f"「{_EB.GRADE_ERROR}」⇒ 两处读法分家了"))
            return out
        out.update(state=STATE_ERROR)
        return out
    if grade_is_error:
        out.update(conflict=CONFLICT_PAYLOAD_WITHOUT_STATUS,
                   why=(f"等级现算是「{_EB.GRADE_ERROR}」（作废载荷在），而 status={status!r}"
                        " 不是错误那一档 ⇒ 状态那一半没跟上"))
        return out
    out.update(state=STATE_NOT_ERROR)
    return out


def _conjecture_reading(row: Any) -> dict[str, Any]:
    """私有判据：一行临时命题 ⇒ `refuted` / `not_refuted` / `unknown`。

    与台账那一档的恒等无关（临时命题没有等级）；这里判的是"这条还没进台账的命题
    是不是已经被判错、拒收了"，凭据两选一：反例实验号 / 拒收记录引用。
    """
    out = {"checked": False, "found": False, "state": CONJ_STATE_UNKNOWN, "why": "",
           "conflict": "", "status": "", "by_experiment": False, "by_refusal": False,
           "counterexample_experiment_id": "", "refusal_ref": "", "conjecture_id": ""}
    if not isinstance(row, Mapping) or not row:
        out["why"] = "没有行 ⇒ 读不出来（不猜成'没被拒'）"
        return out
    status = str(row.get("status") or "")
    exp = str(row.get("counterexample_experiment_id") or "").strip()
    refusal = str(row.get("refusal_ref") or "").strip()
    out.update(checked=True, found=True, status=status, conjecture_id=str(
        row.get("conjecture_id") or ""), counterexample_experiment_id=exp, refusal_ref=refusal)
    if status not in _S.CONJECTURE_STATUSES:
        out["why"] = (f"status={status!r} 不在 CONJECTURE_STATUSES 里 ⇒ 这一行读不出状态"
                      f"（认识的词是 {_S.CONJECTURE_STATUSES}）")
        return out
    if status != CONJ_STATE_REFUTED:
        out["state"] = CONJ_STATE_NOT_REFUTED
        return out
    out.update(by_experiment=bool(exp), by_refusal=bool(refusal))
    if not exp and not refusal:
        out.update(conflict=CONFLICT_STATUS_WITHOUT_PAYLOAD,
                   why=("status=refuted 而反例实验号与拒收记录引用都没有 ⇒ "
                        "说不出凭什么判它错（不许假造一个实验号凑过 validate）"))
        return out
    out["state"] = CONJ_STATE_REFUTED
    return out


def statement_refuted(store: Any = None, *, stmt_id: Any = "", row: Any = None,
                      ) -> dict[str, Any]:
    """台账命题的唯一读口：这条命题是不是「错误」？三态。

    两种定位方式、同一份判据：

    - 手上已经有行（`closing` / `agent_loop` / `manuscriptretire` 本来就在遍历）⇒ `row=行`，
      不额外读盘；
    - 只有号 ⇒ `stmt_id=` + `store`（走 `statementledger.by_id`，口径一）。

    返回键：`checked` / `found` / `state` / `why` / `conflict` / `status` / `word` /
    `grade` / `error_by_sign` / `error_by_evidence` / `voided_by`。

    - `state == "error"`：两边都读得出、且都说"错"（`status` 是错误那一档、等级是「错误」、
      载荷说得出凭什么）；
    - `state == "not_error"`：两边都读得出、且都说"不是错"；
    - `state == "unknown"`：读不出来。`conflict` 非空时是"恒等被破坏"（三个码见模块
      docstring），空时是"根本没查到"。

    调用方不许把它折成一个布尔：`unknown` 折成 `not_error` 就是"没查成被读成查过了"。
    """
    if row is not None:
        return _statement_error_reading(row)
    if store is None:
        return _blank(why="这一层没有 store ⇒ 读不了")
    sid = str(stmt_id or "").strip()
    if not sid:
        return _blank(why="没给命题号 ⇒ 不猜")
    try:
        from . import statementledger as _SL

        got = _SL.by_id(store, stmt_id=sid)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return _blank(why=f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成")
    if not got.get("checked"):
        err = got.get("error") or {}
        return _blank(why=(f"`statements` 读不出来（{err.get('type', '?')}: "
                           f"{err.get('message', '?')}）⇒ 没查成"))
    if not got.get("found"):
        out = _blank(why=f"命题 {sid} 不在册 ⇒ 读不出来（不是'不是错'）")
        out["checked"] = True
        return out
    return _statement_error_reading(dict(got["row"]))


def conjecture_refuted(store: Any = None, *, conjecture_id: Any = "", row: Any = None,
                       ) -> dict[str, Any]:
    """临时命题的唯一读口：这条还没进台账的命题是不是「被拒」？三态。

    临时命题只有三个来源：F 侧计划中的命题、E 侧命题、B 侧命题（业主 2026-11-13）。
    D 侧没有临时命题 ⇒ 本模块不提供写入口，也不认 `created_by=agent-D` 的行是
    "D 的临时命题"（那只是历史行的作者字段）。

    `state`：`refuted` / `not_refuted` / `unknown`；`unknown` 时 `conflict` 非空表示
    "说它被拒却拿不出凭据"（与台账那一档的 `status_without_payload` 同一个码、同一句理由）。
    """
    if row is not None:
        return _conjecture_reading(row)
    if store is None:
        out = _blank(why="这一层没有 store ⇒ 读不了")
        out["state"] = CONJ_STATE_UNKNOWN
        return out
    cid = str(conjecture_id or "").strip()
    if not cid:
        out = _blank(why="没给猜想号 ⇒ 不猜")
        out["state"] = CONJ_STATE_UNKNOWN
        return out
    try:
        rows = [dict(r) for r in store.rows("conjectures")]
    except Exception as exc:  # noqa: BLE001
        out = _blank(why=f"`conjectures` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成")
        out["state"] = CONJ_STATE_UNKNOWN
        return out
    hit = next((r for r in rows if str(r.get("conjecture_id") or "") == cid), None)
    if hit is None:
        out = _blank(why=f"猜想 {cid} 不在册 ⇒ 读不出来（不是'没被拒'）")
        out.update(checked=True, state=CONJ_STATE_UNKNOWN)
        return out
    return _conjecture_reading(hit)


__all__ = [
    "CONFLICT_PAYLOAD_WITHOUT_STATUS",
    "CONFLICT_STATUS_GRADE_DISAGREE",
    "CONFLICT_STATUS_WITHOUT_PAYLOAD",
    "CONJ_STATE_NOT_REFUTED",
    "CONJ_STATE_REFUTED",
    "CONJ_STATE_UNKNOWN",
    "ERROR_WORDS",
    "ERROR_WORD",
    "STATE_ERROR",
    "STATE_NOT_ERROR",
    "STATE_UNKNOWN",
    "conjecture_refuted",
    "statement_refuted",
]
