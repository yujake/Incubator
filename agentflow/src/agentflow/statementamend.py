# -*- coding: utf-8 -*-
"""由 V 的 finding 触发的「命题表述改动」（MST1；业主 2026-11-16 裁定 6，受控写口）。

## 业主裁定（逐字，这就是本模块的全部职责）

> 「我之前以为你要对着V的finding追踪改证明内容，现在我理解了你是要根据finding改命题表述，
>   这是有道理的，但需要再过命题表述闸且不申请新稿号而是沿用稿号和稿并自动修改稿中命题描述
>   为过闸的描述，然后继续edit。若命题有大问题，建议走math_error放弃命题」

四条，逐条落在下面四段上：

1. 只放行"由 finding 触发"的表述改动（:func:`trigger_reading`）；
2. 新表述必须再过命题表述闸 —— 判据本体只有一处
   （`Secretary.judge_proposition_form`，`src/agentflow/secretary.py:3804`），本模块经
   `proofoutcomes.form_gate_reading` 跑同一道闸（三态解释也是同一份）；
3. 不申请新稿号：本模块不碰 `manuscriptids`、不换路径、不新落文件 ——
   稿号与稿路径由调用方（`proofregistry.register_or_rewrite`）逐字沿用；
4. 闸通过后框架自动改写稿里 `## 命题` 那一节（:func:`apply_amendment`，唯一写口仍是
   `proofregistry.replace_section` 与 `proofregistry.rewrite_proposition_head`）。

## 改前是什么形态（AH5 现场，本模块要消灭的那一类缺陷）

`proofregistry.register_or_rewrite` 只要发现 `## 命题` 的规范化指纹变了就整笔受控拒
（`proposition_text_changed`）。AH5 那一笔：F 为修第 12 步顺手把 `[1,∞)` 改成 `[1,∞]`
一个字符 ⇒ 整笔拒、盘上一个字节没写 ⇒ 下一版把改对的那一步退回原样。
"改证明"与"改命题表述"是两根轴，用同一把整笔拒的刀去挡，代价是把改对的那一步也退掉。

## 触发的判据（机器可读，不是调用方自称）

「由 finding 触发」= V 对这一份稿的当前正文落过一行、且那一行的秘书轴是 `fault`
（`verifications.ledger_axis`，轴的唯一来源是 `secretary_judge.axis`；V 的判词只是陈述）。
两本台账都读（在册 `verifications/<号>.jsonl` 与未在册 `verifications/pending/<sha>.jsonl`），
按 `(at, 来源, 追加序)` 取最新那一行 —— 先「有毛病」后「成立」的同一份正文，最新那一行说了算。

为什么不用"调用方传一个 `from_finding=True`"这种自称：那不是证据，是口令。改成读台账之后，
"改表述"这条路只在 V 真的对这一份正文说过话、且说的是有毛病时才开 —— 而那种场合
签本来就没有（这一份正文没过 V），所以本写口不开冻结面的洞。

## 不放行的三种情形（全部受控拒，盘上一个字节不动）

- 没有 finding（或最新一行不是 fault）⇒ `proposition_text_changed`：这是另一条新命题
  （走登记 / 换号），或者走「放弃 + 换号」；要按 finding 改表述，先让 V 对这一份正文说话。
- 有 finding 而新表述过不了形态闸 ⇒ `proposition_form_refused`（逐条点名缺什么）。
- 台账读不出来 / 闸没接上 ⇒ 没查成，同样受控拒（"没查成"不许折成"没问题"）。

## 命题有大问题（不是表述问题）⇒ 走 `math_error` 放弃命题

本模块不碰那条路：放弃是 `statementabandon` / `math_error` 的事（换一条命题就是另一条命题，
不是"表述"）。读数里的 `next_when_not_expressional` 把出口指过去。
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from . import proofoutcomes as _PO

#: 触发的那一档轴（`verifications.SECRETARY_JUDGE_AXES` 里的两档之一；这里只读不写）。
_TRIGGER_AXIS = "fault"

#: 受控码（只增不改；`proposition_text_changed` / `proposition_form_refused` 两组沿用
#: `proofoutcomes` 的既有名字，不另起第二套词）。
REFUSED_LEDGER_UNREADABLE = "verification_ledger_unreadable"
REFUSED_GATE_MISSING = "proposition_form_gate_unavailable"


def _touches(row: Mapping[str, Any], *, sha: str, rel: str) -> bool:
    """这一行台账是不是针对这一份正文（sha 优先；只有缺 sha 的老行才按稿路径认）。

    为什么不按路径认到底：路径是"哪一份稿"，sha 是"稿里的哪一段正文"。改表述的 finding
    必须落在盘上现在这一段正文上 —— 只按路径认，一份稿的历史缺陷会永远给它开门。
    """
    row_sha = str(row.get("proof_sha256") or "").strip().lower()
    if sha and row_sha:
        return row_sha == sha
    path = str(row.get("object_path") or "").strip().replace("\\", "/")
    if not path:
        path = str(row.get("manuscript") or "").strip().replace("\\", "/")
    return bool(rel and path) and path == rel


def trigger_reading(root: Any, *, rel: Any = "", body_sha256: Any = "") -> dict[str, Any]:
    """V 对这一份正文最新的那一行是不是「有毛病」（两本台账合读；纯读）。

    返回键固定：
    `checked`（这一问有没有真的判成）/ `triggered` / `axis` / `rows`（命中几行）/
    `verification_id` / `defect_step` / `at` / `source`（`pending` | `ledger`）/
    `findings`（那一行上的逐条缺陷）/ `problems` / `why`。

    三态：台账读不出来 ⇒ `checked=False` + `why`（"没查成"不是"没有 finding"）。
    `triggered` 只在 `checked=True` 且最新那一行的轴是 `fault` 时为真。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {
        "checked": False, "triggered": False, "axis": "", "rows": 0,
        "verification_id": "", "defect_step": None, "at": "", "source": "",
        "findings": [], "problems": [], "why": "", "body_sha256": str(body_sha256 or ""),
    }
    if not str(root or ""):
        out["why"] = "没有工作区根 ⇒ V 的台账读不出来（没查成 ≠ 没有 finding）"
        return out
    sha = str(body_sha256 or "").strip().lower()
    want_rel = str(rel or "").strip().replace("\\", "/")
    try:
        ledger, bad = _VR.list_verifications(root, limit=None)
        pending, pending_bad = _VR.pending_rows(root)
    except Exception as exc:  # noqa: BLE001 —— 读不成 = 判不了（不是"没有 finding"）
        out["why"] = f"V 的台账读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    out["problems"] = [str(b) for b in (list(bad) + list(pending_bad))]
    #: (at, 来源序, 追加序, 行)：来源序 0 = 未在册那一本（AH5 现场就是它），1 = 在册。
    #: 已认领的 pending 行会同时出现在两本里（`list_verifications` 会把它并进在册那一口）
    #: ⇒ 按 `verification_id` 去重：同一条签不该被读成"两本台账各说了一句"。
    cand: list[tuple[str, int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for rank, rows in ((0, pending), (1, ledger)):
        for i, row in enumerate(rows or []):
            if not isinstance(row, Mapping) or not _touches(row, sha=sha, rel=want_rel):
                continue
            vid = str(row.get("verification_id") or "")
            if vid and vid in seen:
                continue
            seen.add(vid)
            cand.append((str(row.get("at") or ""), rank, i, dict(row)))
    if not cand:
        out.update(checked=True,
                   why="V 的台账里没有针对这一份正文的行 ⇒ 不是 finding 触发")
        return out
    cand.sort(key=lambda t: (t[0], t[1], t[2]))
    latest = cand[-1]
    tie = [t for t in cand if t[0] == latest[0]]
    axes = [str(_VR.ledger_axis(t[3]) or "") for t in tie]
    if len({t[1] for t in tie}) > 1 and any(one != _TRIGGER_AXIS for one in axes):
        # 同一秒里两本台账给了不同结论 ⇒ "最新那一行"判不了。fail-closed：不算触发。
        out.update(checked=True, rows=len(cand),
                   why=("同一秒里在册与未在册两本台账都命中，而它们的轴不同 ⇒ "
                        "判不了最新那一行是哪一条（没判成不许折成 finding 触发）"))
        return out
    axis = str(_VR.ledger_axis(latest[3]) or "")
    row = latest[3]
    vid = str(row.get("verification_id") or "")
    out.update(checked=True, triggered=axis == _TRIGGER_AXIS, axis=axis,
               rows=len(cand), at=latest[0],
               source="pending" if latest[1] == 0 else "ledger",
               verification_id=vid, defect_step=row.get("defect_step"),
               findings=[dict(f) for f in (row.get("findings") or [])
                         if isinstance(f, Mapping)])
    if axis == _TRIGGER_AXIS:
        out["why"] = f"V 对这一份正文最新那一行（{vid or '?'}）的轴是 fault ⇒ 触发"
    elif axis:
        out["why"] = (f"V 对这一份正文最新那一行（{vid or '?'}）的轴是 {axis}"
                      "（不是 fault）⇒ 不算 finding 触发")
    else:
        out["why"] = (f"V 对这一份正文最新那一行（{vid or '?'}）没有轴"
                      "⇒ 不计票、也不当 finding 触发")
    return out


def _proposition_of(text: Any) -> str:
    """稿里 `## 命题` 那一节的正文（切节口径只有一处：`proofregistry.split_sections`）。"""
    from . import proofregistry as _PR

    _head, sections = _PR.split_sections(text)
    return next((str(body) for name, body in sections if name == "命题"), "").strip()


def amend_reading(
    root: Any, *, out: dict[str, Any], entry: Mapping[str, Any], rel: Any,
    old_text: Any, proposition: Any, gate: Callable[..., Mapping[str, Any]] | None,
    kind: Any = "", label: Any = "", proof_text: Any = "",
) -> dict[str, Any]:
    """这一笔"改命题表述"能不能放行：`(触发 + 过闸 + 自动改写)` 三段合一。

    `out` 是 `register_or_rewrite` 的读数（本函数把两格写进去：`proposition_amend` 与
    `gate`）；返回值只有三格：`{"ok": bool, "text": <改写后的整份稿>, "refusal": <受控拒那几格>}`。

    为什么改写的产物从这里带出去、而不留在读数里：读数会被日志与提示词读走，整份手稿
    （几 KB 正文）不该搭在它上面。`text` 只在 `ok=True` 时有意义。
    """
    from . import proofregistry as _PR

    old_prop = _proposition_of(old_text)
    new_prop = str(proposition or "").strip()
    before_sha = _PR.proof_sha(old_text)
    reading: dict[str, Any] = {
        "checked": False, "ok": False, "triggered": False, "trigger_axis": "",
        "trigger_verification_id": "", "trigger_defect_step": None, "trigger_at": "",
        "trigger_rows": 0, "trigger": {}, "gate": {},
        "proposition_before": old_prop, "proposition_after": new_prop,
        "fingerprint_before": _PR.proposition_fingerprint(old_prop),
        "fingerprint_after": _PR.proposition_fingerprint(new_prop),
        "proof_sha256_before": before_sha, "proof_sha256_after": "",
        "problems": [], "why": "",
        "next_when_not_expressional": ("命题有大问题（不是表述问题）⇒ 走 `math_error` 放弃"
                                       "这条命题；改表述这条路不换号、也不换命题"),
    }
    out["proposition_amend"] = reading

    def _refuse(code: str, why: str, *, problems: list[str] | None = None,
                checked: bool = True) -> dict[str, Any]:
        """这一笔到此为止：把受控拒那几格交给调用方 `out.update(...)`，盘上不动。"""
        reading.update(checked=bool(checked), ok=False, why=why,
                       problems=list((reading.get("problems") or []) + list(problems or [])))
        return {"ok": False, "text": "",
                "refusal": {"refused": code, "why": why,
                            "problems": list(reading["problems"]),
                            "entry": dict(entry or {})}}

    # ---- ① 触发：V 对这一份正文说过"有毛病"（不是调用方自称） ------------------
    trigger = trigger_reading(root, rel=rel, body_sha256=before_sha)
    reading.update(trigger=trigger, triggered=bool(trigger.get("triggered")),
                   trigger_axis=str(trigger.get("axis") or ""),
                   trigger_verification_id=str(trigger.get("verification_id") or ""),
                   trigger_defect_step=trigger.get("defect_step"),
                   trigger_at=str(trigger.get("at") or ""),
                   trigger_rows=int(trigger.get("rows") or 0))
    if not trigger.get("checked"):
        return _refuse(REFUSED_LEDGER_UNREADABLE, str(trigger.get("why") or ""),
                       problems=["verification_ledger_unreadable"], checked=False)
    if not trigger.get("triggered"):
        return _refuse(
            _PO.REFUSED_TEXT_CHANGED,
            ("命题正文与登记条目里那一条不一致（指纹 "
             f"{reading['fingerprint_before'][:12]}… → "
             f"{reading['fingerprint_after'][:12]}…）⇒ 受控拒。"
             "这一笔不是由 V 的 finding 触发的（"
             f"{trigger.get('why') or '台账里没有那一行'}）—— 改表述只有一条路：等 V 对"
             "这一份正文说话，再过命题表述闸；而它是另一条新命题时走登记（换号），或者走"
             "「放弃 + 换号」+ `math_error`。不要用挂证明改命题正文"),
            problems=["proposition_text_changed"])
    # ---- ② 过闸：判据本体只有一处（`Secretary.judge_proposition_form`） -------------
    if gate is None:
        return _refuse(REFUSED_GATE_MISSING,
                       "命题表述闸没有接上（gate=None）⇒ 没判成 ⇒ 受控拒："
                       "'没判成'不许折成'表述合规'；改表述这一笔一个字节都不写",
                       problems=["proposition_form_gate_unavailable"])
    gate_reading, gate_refusal = _PO.form_gate_reading(
        gate, proposition=new_prop, kind=kind, proof_text=proof_text, label=label,
        entry=entry or {})
    out["gate"] = gate_reading
    reading["gate"] = gate_reading
    if gate_refusal is not None:
        return _refuse(_PO.REFUSED_GATE, str(gate_refusal.get("why") or ""),
                       problems=list(gate_refusal.get("problems") or []),
                       checked=bool(gate_refusal.get("checked", False)))
    # ---- ③ 自动改写 `## 命题`（唯一写口转发；先干跑一次，核不过就一个字节不写） ----
    new_text, replaced = _PR.replace_section(old_text, "命题", new_prop)
    if not replaced:
        return _refuse(_PO.REFUSED_SHAPE,
                       "稿里没有 `## 命题` 那一节（或切节口径认不出它）⇒ 没有可原位改写的"
                       "板块（缺节不等于「要新建一节」：那会改稿的形状，这一档不做）",
                       problems=["manuscript_shape_refused"])
    after_sha = _PR.proof_sha(new_text)
    reading["proof_sha256_after"] = after_sha
    if after_sha != before_sha:
        return _refuse(_PO.REFUSED_SHAPE,
                       "改写 `## 命题` 之后 `## 证明` 的正文 sha 变了 ⇒ 这一笔会动到签盖的"
                       "那段字节，整笔不写（冻结面不开洞）",
                       problems=["proof_body_would_move"])
    text_after = _PR.rewrite_proposition_head(
        new_text, new_fp=str(reading["fingerprint_after"]))
    detail = (f"V 的 finding（{reading['trigger_verification_id'] or '?'}，轴 "
              f"{reading['trigger_axis']}"
              + (f"，缺陷在第 {reading['trigger_defect_step']} 步"
                 if reading["trigger_defect_step"] is not None else "")
              + "）触发 + 新表述过了命题表述闸 ⇒ 沿用原稿号原位改写 `## 命题`（指纹 "
              f"{reading['fingerprint_before'][:12]}… → "
              f"{reading['fingerprint_after'][:12]}…）")
    reading.update(checked=True, ok=True, why=(
        detail + "；`## 证明` 的正文 sha 逐字未变 ⇒ 签若存在仍然对得上"))
    return {"ok": True, "text": text_after, "refusal": {}}


def apply_amendment(text: Any, amend: Any) -> tuple[str, bool]:
    """把 `## 命题` 那一节换成过闸的那一版（没放行 ⇒ 原样返回，一个字节不动）。

    这是裁定 6 的第 ④ 条落点：改写的不是"调用方手里那段"，是闸看到并放行的那段
    （`amend["proposition_after"]`）—— 两段分家时，盘上写的就不是过闸的那一版。
    """
    got = dict(amend) if isinstance(amend, Mapping) else {}
    if not got.get("ok"):
        return str(text or ""), False
    from . import proofregistry as _PR

    new_text, replaced = _PR.replace_section(
        str(text or ""), "命题", str(got.get("proposition_after") or ""))
    if not replaced:
        return str(text or ""), False
    return _PR.rewrite_proposition_head(
        new_text, new_fp=str(got.get("fingerprint_after") or "")), True
