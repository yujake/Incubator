# -*- coding: utf-8 -*-
"""证伪通道（库层）：把一份 V 签过的「证伪论证」翻译成被证伪命题的「证伪签」。

## 业主 2026-11-13 裁定（逐字，三段）

> 「关于标记命题台账内命题错误，需将 proof 栏替换成证伪论证，且你要看谁能负责这块。
> V 签需是对该证伪论证的签。等级打成错误。」
> 「F 可写，如果是 E 反例，让 F 拿着这个反例写理论论证。」
> 「证伪论证通常由 B 侧发起……B 应下派 D 再下派 F 负责。……请 B 将这些稿先正常录入，
> 然后写证伪稿依赖面写它们……并专门通过证伪通道（锁定命题号）提交（不通过秘书……），
> 证伪通道系统自动将 V 签翻译成证伪签，且 error 等级根据证伪签算，证伪签在则否决其它等级
> 且 error 绝对是最低等级。」

## 这条通道的两个"锁"（输入只有两样）

1. `statement_id`：被证伪的那条命题 「P」 的号 —— 全程不改它（不重定向、不按正文猜）；
2. `manuscript`：B 的证伪论证稿（Q 的 b-稿）的路径 —— 必须正是 V 签盖住的那一份。

「不通过秘书」在这里是结构上的：本模块不调 `Secretary.extract_manuscript`、
不读签块、不认"稿上自称已签"，只读两样机器凭据（`## 证明` 的正文 sha + `out/vsigns/`
里那一份签的复算/背书）。入口也不经 ActionSpec —— 那是声明面（p282/FC-27）。
判据走本模块的 `refute_by_sign`。

## 它「不」做的事（每一条都是刻意的）

- 不写 `out/vsigns/<sha>.json`：签文件是「一稿一签」，而证伪签的对象是「另一条命题」 P。
  写进去就是一稿两签（同一份正文挂两个结论）。翻译结果只落 P 那一行的口袋
  （`bits.evidence.refutation_sign`）与作废载荷（`bits.voided_by`）。
- 不动 Q：Q 是一条正常的命题（它证的是"P 不成立"），它照常走 B 的登记 + V 的签。
- 不判"P 到底错没错"：那是 V 对那份论证的结论（`state="signed"` 才有资格往下走）。
- 不要求依赖面「有行」：业主对 B 侧稿的要求是「形式要有，可为空」⇒ 只要求
  `## 依赖` 那一节在（`present=True`）且读得懂（`refused` 为空）。
- 不做级联：`cascade_void` 的读数由 `statementrefute.refute_statement` 那条路给；
  本模块只落"根"这一条，`closing` 的 `pollution` 那一栏会按依赖倒排扫出来。

## 三态（与 `statementrefute` 同一条纪律）

- `checked=True`：写成了（`wrote=True`），或本来就是这一档（`already=True`，幂等）；
- `checked=True, wrote=False, refused=<码>`：受控拒绝，「一个字节都不写」；
- `checked=False`：没查成（台账 / 稿 / 签 / 台账账本读不出来）⇒ 不许折成"没有错"。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import errorstate as _ES
from . import evidencebits as _EB
from . import schema as _S
from .errorstate import conjecture_refuted, statement_refuted  # noqa: F401 —— 读口在这里转出

#: 受控拒绝码（一个码一件事；调用方按码分句，不许折成"系统故障"）。
MISSING_ID = "refutation_missing_id"
NO_STORE = "no_store"
MISSING_MANUSCRIPT = "refutation_missing_manuscript"
BAD_MANUSCRIPT = "refutation_bad_manuscript"
UNKNOWN_STATEMENT = "refutation_unknown_statement"
ON_RETIRED = "refutation_on_retired"
#: 这一行现在读不出状态（`status` 不在词表 / 作废载荷在而状态没跟上 / 证伪签口袋坏）
#: ⇒ 不许覆盖：覆盖等于拿一笔新历史盖住"这一行本来就读不出来"。
STATE_UNREADABLE = "refutation_state_unreadable"
NOT_A_PROPOSITION = "refutation_not_a_proposition"
DRAFT_UNREADABLE = "refutation_draft_unreadable"
PROOF_ABSENT = "refutation_proof_absent"
DEPS_MISSING = "refutation_dependency_section_missing"
DEPS_UNREADABLE = "refutation_dependency_section_unreadable"
SIGN_UNREADABLE = "refutation_sign_unreadable"
NOT_SIGNED = "refutation_not_signed"
SIGN_MISSING = "refutation_sign_missing"
UNKNOWN_PROOF_PATH = "refutation_unknown_proof_path"

#: 证伪论证稿的族：B 写的证伪稿（`manuscripts/B/b-proof-<B稿号>.md`）。
#: 别的族一律拒：F 的稿是"P 不成立"的「证明」，B 的稿才是「证伪论证」（引前者）。
DRAFT_FAMILY = "b-proof"

_HEX = frozenset("0123456789abcdef")


def sign_payload(*, artifact_sha: Any, ledger: Any, at: Any, manuscript: Any = "",
                 statement_id: Any = "", proof_no: Any = 1) -> dict[str, Any]:
    """把「V 对 Q 那份证伪论证的签」翻译成 P 的证伪签（「唯一翻译点」）。

    只做翻译与形状校验，不读盘、不判该不该签（那是 `refute_by_sign` 的事）。
    返回空字典 = 这一份签说不出"签的是哪一份正文 / 哪一行台账 / 几时" ⇒ 调用方
    必须受控拒（`SIGN_MISSING`）：翻译不出来就是没有证伪签，宁可整笔不写。

    ## 为什么键集合是这几格
    `artifact_sha` + `ledger` 是"这一签盖的是那一份正文、在那本台账里"的「唯一」凭据
    （与 `ARTIFACT_SHA_RULE` 同一把尺）；`at` 让读数回答"几时判它错的"；
    `manuscript` 是锁进来的那条路径（读的人不必再去别处查"哪一份稿"）；
    `signed_statement_id` 是 Q（「被签的那条命题」），P 是「被否决的那条」 —— 两个号
    必须都能读出来，否则"这一格证伪签是谁的"就分不清。
    """
    sha = str(artifact_sha or "").strip().lower()
    led = str(ledger or "").strip()
    stamp = str(at or "").strip()
    if len(sha) != 64 or any(ch not in _HEX for ch in sha) or not led or not stamp:
        return {}
    return {
        "kind": _EB.REFUTATION_SIGN_KIND,
        "artifact_sha": sha,
        "ledger": led,
        "at": stamp,
        "manuscript": str(manuscript or "").strip().replace("\\", "/"),
        "signed_statement_id": str(statement_id or "").strip(),
        "proof_no": int(proof_no or 1),
    }


def _fail(out: dict[str, Any], code: str, why: str, **extra: Any) -> dict[str, Any]:
    """受控拒绝（`checked=True` + `refused`，一个字节都不写）。"""
    out.update(checked=True, refused=str(code), why=str(why), **extra)
    return out


def _by_id(store: Any, statement_id: str) -> tuple[dict[str, Any] | None, str, bool]:
    """按号取 P 那一行：`(行, 原因, 查没查成)`（口径一，走 `statementledger.by_id`）。"""
    from . import statementledger as _SL

    got = _SL.by_id(store, stmt_id=statement_id)
    if not got.get("checked"):
        err = got.get("error") or {}
        return (None,
                f"`statements` 读不出来（{err.get('type', '?')}: "
                f"{err.get('message', '?')}）⇒ 没查成", False)
    return (dict(got["row"]) if got.get("found") else None), "", True


def _manuscript_reading(rel: str) -> dict[str, Any]:
    """这一条路径能不能当证伪论证稿：过族表、族是 `b-proof`、且在该族的角色目录下。

    只判形态（族 / 目录 / 真文件名），不判内容 —— 内容是下面 `_draft_reading` 的事。
    """
    from . import manuscriptfamily as _MFAM

    out: dict[str, Any] = {"checked": True, "ok": False, "family": "",
                           "tier": "", "why": ""}
    got = _MFAM.classify_manuscript(rel)
    out["family"] = str(got.get("family") or "")
    out["tier"] = str(got.get("tier") or "")
    if out["tier"] == _MFAM.TIER_LEGACY:
        out["why"] = (f"`{rel}` 是历史档（`notes/` 或 `-vN`）⇒ 不签、不收录 ⇒ "
                      "不能当证伪通道的输入")
        return out
    if out["tier"] != _MFAM.TIER_FAMILY:
        out["why"] = (f"`{rel}` 不是框架手稿（族={out['family'] or '—'}，"
                      f"档={out['tier'] or '—'}）⇒ 证伪通道只收 "
                      f"`{_MFAM.relpath(DRAFT_FAMILY, '<稿号>')}`")
        return out
    if out["family"] != DRAFT_FAMILY:
        out["why"] = (f"`{rel}` 是 `{out['family']}` 族 ⇒ 证伪论证稿必须是 "
                      f"`{DRAFT_FAMILY}`（B 写、B 的稿号）。F 的稿是「P 不成立」的"
                      "证明，由 B 正常录入后「被引」，不是这条通道的输入")
        return out
    out["ok"] = True
    return out


def _draft_reading(root: Any, rel: str) -> dict[str, Any]:
    """读那份稿：`## 证明` 正文 + `## 依赖` 那一节的形态（三态，不折平）。

    ## 正文为什么要按 `manuscript_proof_body` 归一
    `depsection.proof_body` 取出来的那一节首尾各带一个换行，而签的 sha 是按
    "登记时那一份正文"（逐行 join、无首尾空行）算的（`ARTIFACT_SHA_RULE`）。
    不归一到同一串，签文件里的 sha 与这里算的 sha 会差一个换行 ⇒ 每一处都
    "看起来成功了"、而签永远认不上。归一口径只有一处：`vsigns.manuscript_proof_body`。
    """
    from . import depsection as _DS
    from . import vsigns as _VS

    got = _DS.read_proof_body(root, rel)
    out: dict[str, Any] = {
        "checked": bool(got.get("checked")), "state": str(got.get("state") or ""),
        "body": "", "why": str(got.get("why") or ""),
        "deps": {"present": False, "refused": "", "rows": 0, "why": ""},
    }
    if not out["checked"]:
        return out
    text = str(got.get("text") or "")
    out["body"] = _VS.manuscript_proof_body(text)
    section = _DS.parse_dependency_section(text)
    out["deps"] = {
        "present": bool(section.get("present")),
        "refused": str(section.get("refused") or ""),
        "rows": len(section.get("rows") or ()),
        "why": str(section.get("reason") or ""),
    }
    return out


def _sign_reading(root: Any, store: Any, *, rel: str, body: str,
                  ) -> dict[str, Any]:
    """V 的签是不是盖在这份证伪论证上（唯一判据：`vsigns.sign_reading`）。

    返回 `{checked, state, signed, sha, sign, ledger, at, q_statement_id, why}`。
    `checked=False` = 没查成（读不出来）—— 与"没签"分开。
    """
    from . import proofregistry as _PR
    from . import vsigns as _VS

    out: dict[str, Any] = {"checked": False, "state": "", "signed": False,
                           "sha": "", "sign": {}, "ledger": "", "at": "",
                           "q_statement_id": "", "why": ""}
    sha = _PR.proof_sha(body)
    out["sha"] = sha
    found = _VS.sign_of(root, sha)
    if not found.get("checked"):
        out["why"] = f"签文件这一格没查成：{found.get('why') or ''}"
        return out
    sign = dict(found.get("sign") or {})
    out["sign"] = sign
    out["q_statement_id"] = str(sign.get("statement_id") or "").strip()
    reading = _VS.sign_reading(
        root, statement_id=out["q_statement_id"], proof_text=body, proof_no=1,
        manuscript_path=rel, store=store)
    out.update(checked=bool(reading.get("checked")),
               state=str(reading.get("state") or ""),
               signed=(str(reading.get("state") or "") == "signed"),
               why=str(reading.get("why") or ""))
    if out["signed"]:
        out["ledger"] = str(sign.get("ledger") or "")
        out["at"] = str(sign.get("at") or "")
    return out


def _history_entry(old_text: str, new_text: str, *, proof_no: int) -> dict[str, Any]:
    """旧正文留痕那一条（形状与 `register_statement._canonical_history_entry` 同一份）。

    为什么转调而不是另写一份：那条形状是"旧正文 / 旧 sha / 几时 / 被谁换掉"的唯一
    定义，第二份实现会让 `proof_history` 里出现两种元素（读的人要按形状分叉）。
    """
    from .agent_b.register_statement import _canonical_history_entry

    entry = _canonical_history_entry(old_text, new_text)
    if int(proof_no) >= 1:
        entry["proof_no"] = int(proof_no)
    return entry


def _replace_body(row: Mapping[str, Any], *, proof_no: int,
                  body: str) -> tuple[dict[str, Any] | None, str]:
    """把证伪论证写进第 `proof_no` 份正文，返回 `(改后的行, 旧正文)`。

    `proof_no=1` ⇒ canonical 那一格（`proof_text`）；`>1` ⇒ `proofs[]` 里对应的那条。
    找不到那一条 ⇒ `(None, "")`（调用方受控拒 `UNKNOWN_PROOF_PATH`）。
    """
    from . import verifications as _VR

    merged = dict(row)
    if int(proof_no) == 1:
        return merged, str(row.get("proof_text") or "")
    listed = [dict(one) if isinstance(one, Mapping) else one
              for one in (row.get(_VR.PROOFS_KEY) or [])]
    for index, one in enumerate(listed):
        if not isinstance(one, Mapping) or int(one.get("proof_no") or 0) != int(proof_no):
            continue
        old = str(one.get("text") or "")
        listed[index] = {**dict(one), "text": body,
                         "proof_sha256": _VR.text_sha(body)}
        merged[_VR.PROOFS_KEY] = listed
        return merged, old
    return None, ""


def refute_by_sign(store: Any, *, statement_id: Any, manuscript: Any,
                   proof_no: Any = 1, at: Any = "", actor: str = "B",
                   reason: Any = "") -> dict[str, Any]:
    """证伪通道的唯一入口：锁 P + 锁稿 ⇒ 把 V 的签翻译成证伪签并落终态。

    ## 九步（每一步失败都受控拒、一个字节都不写）
    ① 参数：命题号 / 稿路径 / store；
    ② 稿的形态（`b-proof` 族）；
    ③ P 在册（口径一按号取；不在册 ⇒ 拒，「不新建行」）；
    ④ 终态纪律：已 `refuted` ⇒ `already=True`（幂等，不写）；`abandoned` / `superseded`
       ⇒ 拒（两个终态不许换档）；概念行 ⇒ 拒（不是命题）；
    ⑤ 读稿：`## 证明` 正文（缺节 ⇒ 拒）+ `## 依赖`（缺节 / 读不懂 ⇒ 拒；「空表放行」）；
    ⑥ 签：`sign_reading == "signed"` 且签文件点名的那份正文就是这一份（sha 同一把尺）；
    ⑦ 翻译：`sign_payload(...)`（空 ⇒ 拒，fail-closed）；
    ⑧ 写：`proof_text|proofs[n]` ← 证伪论证（旧正文按号进 `proof_history`）、
       `status=refuted`、`bits.voided_by` / `bits.evidence.refutation_sign`，
       「同一笔事务」（`schema.py:2516-2520`：`voided_by` 非空时 status 不许是 active）；
    ⑨ 读数：`grade` 由 `evidencebits.derive_grade` 现算 ⇒ 「错误」（否决其它等级）。

    返回键：`checked` / `wrote` / `already` / `refused` / `why` / `statement_id` /
    `manuscript` / `proof_no` / `sha` / `ledger` / `at` / `sign` / `grade` /
    `old_sha` / `changes` / `deps` / `reason`。
    """
    out: dict[str, Any] = {
        "checked": False, "wrote": False, "already": False, "refused": "",
        "why": "", "statement_id": str(statement_id or "").strip(),
        "manuscript": str(manuscript or "").strip().replace("\\", "/"),
        "proof_no": 1, "sha": "", "ledger": "", "at": "", "sign": {},
        "grade": "", "old_sha": "", "changes": [], "deps": {}, "reason": "",
    }
    sid = out["statement_id"]
    rel = out["manuscript"]
    if not sid:
        return _fail(out, MISSING_ID, "没给命题号 ⇒ 不知道证伪哪一条（不猜）")
    if store is None:
        return _fail(out, NO_STORE, "这一层没有 store ⇒ 写不了")
    if not rel:
        return _fail(out, MISSING_MANUSCRIPT,
                     "没给证伪论证稿的路径 ⇒ 不知道 V 签的是哪一份（不猜）")
    try:
        no = int(proof_no or 1)
    except (TypeError, ValueError):
        return _fail(out, UNKNOWN_PROOF_PATH, f"证明号认不出（收到 {proof_no!r}）")
    if no < 1:
        return _fail(out, UNKNOWN_PROOF_PATH, f"证明号必须是正整数（收到 {proof_no!r}）")
    out["proof_no"] = no
    form = _manuscript_reading(rel)
    if not form.get("ok"):
        return _fail(out, BAD_MANUSCRIPT, str(form.get("why") or ""),
                     family=str(form.get("family") or ""))
    row, why, checked = _by_id(store, sid)
    if not checked:
        return _fail(out, UNKNOWN_STATEMENT, why)
    if row is None:
        return _fail(out, UNKNOWN_STATEMENT,
                     f"命题 {sid} 不在册 ⇒ 证伪一条不存在的命题（不新建行）")
    if str(row.get("kind") or "") == "concept":
        return _fail(out, NOT_A_PROPOSITION,
                     f"命题 {sid} 的 kind 是 concept（概念行不参与等级链，也没有真值）"
                     " ⇒ 它不能被证伪")
    status_now = str(row.get("status") or "")
    reading = _ES.statement_refuted(row=row)
    if reading["state"] == _ES.STATE_ERROR:
        # 幂等：同一笔重放不写第二遍；但也只认"确实挂着证伪签"那一档 ——
        # 一条凭反例实验作废（没有证伪签）的行被这条通道"认领"，等于把
        # 另一种作废读成证伪（两种作废凭据不同，读数里 `by_sign` 分得开）。
        already = bool(reading["error_by_sign"])
        out.update(checked=True, already=already, statement_id=sid,
                   grade=reading["grade"],
                   why=(f"这一条早就是错误那一档（{_ES.ERROR_WORD}）、且挂着证伪签 ⇒ "
                        "一个字节都没写（幂等）" if already else
                        f"这一条已经是错误那一档，但不是凭证伪签（没有证伪签口袋）⇒ "
                        "不接管：它当初凭什么作废的，读数里已有一份载荷"))
        if not already:
            out["refused"] = ON_RETIRED
        return out
    if reading["state"] == _ES.STATE_UNKNOWN:
        # 读不出来的一行（载荷在而状态没跟上 / 签口袋坏 / 状态词不在词表）不许覆盖。
        return _fail(out, STATE_UNREADABLE,
                     f"这一行现在读不出状态（{reading['conflict'] or '未知'}："
                     f"{reading['why']}）⇒ 整笔不写：先把它读出来，再判它错")
    if status_now in ("abandoned", "superseded"):
        return _fail(out, ON_RETIRED,
                     f"命题 {sid} 已经是 {status_now}（终态 / 墓碑）⇒ 不能在同一条上再标"
                     "「错误」：换了档就读不出'当初是放弃、被取代还是被证伪'")
    draft = _draft_reading(str(getattr(store, "root", "") or ""), rel)
    out["deps"] = dict(draft.get("deps") or {})
    if not draft.get("checked"):
        return _fail(out, DRAFT_UNREADABLE, str(draft.get("why") or ""))
    body = str(draft.get("body") or "")
    if not body.strip():
        return _fail(out, PROOF_ABSENT,
                     f"`{rel}` 的 `## 证明` 是空的（或没有这一节）⇒ 没有可翻译的证伪论证")
    if not out["deps"].get("present"):
        return _fail(out, DEPS_MISSING,
                     f"`{rel}` 没有 `## 依赖` 那一节。业主对 B 侧稿的要求是"
                     "「形式要有，可为空」⇒ 空表可以，缺节不行（缺节与'自足'读起来一样）")
    if str(out["deps"].get("refused") or ""):
        return _fail(out, DEPS_UNREADABLE,
                     f"`{rel}` 的 `## 依赖` 读不懂：{out['deps'].get('why') or ''}")
    signed = _sign_reading(str(getattr(store, "root", "") or ""), store,
                           rel=rel, body=body)
    out["sha"] = str(signed.get("sha") or "")
    if not signed.get("checked"):
        return _fail(out, SIGN_UNREADABLE, str(signed.get("why") or ""))
    if not signed.get("signed"):
        return _fail(out, NOT_SIGNED,
                     f"V 没有签这一份证伪论证（`sign_reading.state={signed.get('state')!r}`）："
                     f"{signed.get('why') or ''} —— 证伪签必须是对这份论证的签",
                     state=str(signed.get("state") or ""))
    payload = sign_payload(artifact_sha=signed.get("sha"), ledger=signed.get("ledger"),
                           at=signed.get("at"), manuscript=rel,
                           statement_id=signed.get("q_statement_id"), proof_no=no)
    if not payload:
        return _fail(out, SIGN_MISSING, (
            "这一份签翻译不出来（签字里缺 正文 sha / 台账 / 时刻 任一格）⇒ 没有证伪签，"
            "整笔不写：宁可读成「没有证伪」，也不写一格说不出凭据的「错误」"))
    out["ledger"] = payload["ledger"]
    out["at"] = payload["at"]
    out["sign"] = dict(payload)
    return _write(store, row=row, sid=sid, rel=rel, body=body, no=no,
                  payload=payload, at=str(at or "").strip(), actor=actor,
                  reason=str(reason or "").strip(), out=out)


def _write(store: Any, *, row: Mapping[str, Any], sid: str, rel: str, body: str,
           no: int, payload: Mapping[str, Any], at: str, actor: str,
           reason: str, out: dict[str, Any]) -> dict[str, Any]:
    """⑧ 那一笔：正文替换 + 终态 + 两个口袋，「同一个事务」。

    事务本身走 `statementrefute._write_row`（今晚刚落的那一笔：整行重建 → 过
    `schema.Statement.validate` → `store.tx` 里再按号核一次 → `tx.upsert`）。
    为什么转调而不是另写一份：`voided_by` 非空时 status 不许是 active 这条约束
    （`schema.py` 的 `Statement.validate`）就落在那一步的 validate 上，第二份实现
    会让"状态与口袋同时落盘"这件事有两个说法。
    """
    from . import statementrefute as _SR

    merged, old = _replace_body(row, proof_no=no, body=body)
    if merged is None:
        return _fail(out, UNKNOWN_PROOF_PATH,
                     f"命题 {sid} 的证明清单里没有 #{no} 这一份 ⇒ 不知道换哪一条")
    stamp = at or _S.now_iso()
    history = [dict(h) for h in (row.get("proof_history") or [])
               if isinstance(h, Mapping)]
    entry = _history_entry(old, body, proof_no=no)
    history.append(entry)
    merged["proof_history"] = history
    if no == 1:
        merged["proof_text"] = body
    bits = dict(row.get("bits") or {})
    evidence = dict(bits.get("evidence") or {})
    evidence[_EB.REFUTATION_SIGN_KEY] = dict(payload)
    bits["evidence"] = evidence
    kind = str(row.get("kind") or "")
    merged["bits"] = _EB.normalize_raw(bits,
                                       origin=str(row.get("origin") or "own_result"),
                                       kind=kind)
    #: status（错误那一档）/ `voided_by` / 等级三件事由 `_write_row` 一处 settle：
    #: 它写完会在同一个事务里读回校验"状态=错误 ∧ 等级=错误"，否则整笔回滚。
    data, code, why = _SR._write_row(
        store, before=row, merged=merged,
        note=f"statement:refutation_sign:{stamp}", actor=f"refutation:{actor}",
        payload=dict(payload))
    if code:
        # `statements_unreadable` 是"没查成"；其余是受控拒（校验不过 / 写不进去）。
        out.update(checked=(code != "statements_unreadable"),
                   refused=code, why=why)
        return out
    out.update(checked=True, wrote=True, statement_id=sid, manuscript=rel,
               at=stamp, old_sha=entry.get("sha", ""),
               grade=_EB.derive_grade(dict(data.get("bits") or {}), kind=kind),
               changes=[f"status: {str(row.get('status') or '')} → {_ES.ERROR_WORD}",
                        f"proof_text#{no} ← 证伪论证（旧正文进 proof_history）",
                        "bits.evidence.refutation_sign",
                        "bits.voided_by: refutation_sign"],
               reason=(reason or
                       (f"命题 {sid} 已标记为错误（{stamp}）：凭据是 V 对 "
                        f"`{rel}` 那份证伪论证的签（台账 `{payload.get('ledger')}`）")))
    return out


#: 读口的旧名（`refutation_of`）已并入 `errorstate.statement_refuted`：
#: 一个概念只留一个口。下面这行只是把老名字指过去，防止外部手工调用报 AttributeError；
#: 新代码一律用 `statement_refuted`（模块顶部已转出）。
refutation_of = statement_refuted


__all__ = [
    "BAD_MANUSCRIPT",
    "DEPS_MISSING",
    "DEPS_UNREADABLE",
    "DRAFT_FAMILY",
    "DRAFT_UNREADABLE",
    "MISSING_ID",
    "MISSING_MANUSCRIPT",
    "NOT_A_PROPOSITION",
    "NOT_SIGNED",
    "NO_STORE",
    "ON_RETIRED",
    "PROOF_ABSENT",
    "SIGN_MISSING",
    "SIGN_UNREADABLE",
    "STATE_UNREADABLE",
    "UNKNOWN_PROOF_PATH",
    "UNKNOWN_STATEMENT",
    "sign_payload",
    "statement_refuted",
]
