# -*- coding: utf-8 -*-
"""F 侧的送审与「交差要有 V 签」的读数（业主 2026-11-02 裁定）。

口径逐字（这一笔的唯一目标）：

    重点是要F侧拿V签，拿到V签F才能交差

## 为什么要有这一格（改前的缺口）

`F -> V` 那条边一直在（`capabilities.ALLOWED_EDGES["F"]` 含 `"V"`，
声明真身是 `specs/f.py::SPEC.edges`），`agent_skills` 也一直教 F
「你产出的证明由你派 V 签」；而 `agent_f/core.py` 的实现交完 B 的登记就结束了 ——
没有任何一处真的把证明递出去，也没有任何一处回读签。`F.step` 的返回值里
于是没有一格说「这一份证明签了没有」，`outcome=progress` 与「交差」之间
没有闸。83 的定格读数就是这条缺口的现场：F 写的五份证明一份都没签
（`out/vsigns/` 只有 000005 一份），而 F 的每一趟都照样回 progress。

## 这一格做两件事（判据都不在这里重写）

1. :func:`submit_proof` —— 把这一份证明递给 V。走的是进程内调用
   `AgentV.verify_proof`，与 F 把内容交给 `B.register_statement` 同一种做法：
   边在，就走得通；V 那边自己连判 `verifications.SIGN_STREAK_NEED` 轮、
   由 V 的秘书发签。两个落点都由 V 决定，这里一个字节都不写：
   - 命题在册 ⇒ `verifications/<命题号>.jsonl`（签落 `out/vsigns/<正文 sha>.json`）；
   - 命题不在册 ⇒ `verifications/pending/<正文 sha>.jsonl`（`record_pending_sign`，
     按正文 sha 可认领；B 登记时由 `vsigns.bits_after_sign` 认领，那一半已经存在）。

2. :func:`delivery_reading` —— 纯读的回读，四档（与 `verifications.REVIEW_STATES`
   同一把尺，不另立口径）：
   - `signed` 已签：有一份签盖住现行正文（在册签 / pending 签都算）；
   - `rejected` 未通过：V 判过这一份、结论不是「成立」（或判了「成立」而秘书读出了缺陷）；
   - `waiting` 待签：没有签、也没有打回（含「还没送审」与「审过、连续次数没到」）；
   - `unknown` 没查成：台账 / pending 读不出来（不许折成「待签」）。
   F 的 `step` 把这一格带回去；`delivered` 只在 `signed` 时为真 ——
   拿不到 V 签那一趟就读成「没交差」。
"""
from __future__ import annotations

from typing import Any, Mapping

#: 已签：现行正文有一份盖得住的签（在册或 pending 都算）。
STATE_SIGNED = "signed"
#: 待签：没有签、也没有打回 —— 含「还没送审」与「审过、连续次数没到」。
STATE_WAITING = "waiting"
#: 未通过：V 判过这一份、结论不是「成立」（或秘书读出了缺陷）。
STATE_REJECTED = "rejected"
#: 没查成：台账 / pending 读不出来。它不是「待签」，也不是「未通过」。
STATE_UNKNOWN = "unknown"

#: 四档的固定顺序（从查清了到没查成），与外层读数的词表逐字一致。
DELIVERY_STATES: tuple[str, ...] = (STATE_SIGNED, STATE_WAITING,
                                   STATE_REJECTED, STATE_UNKNOWN)

#: 档 -> 给人看的标签（F 的返回值与 `detail` 都用这几个词，别处不再各写一份）。
DELIVERY_LABELS: dict[str, str] = {
    STATE_SIGNED: "已签",
    STATE_WAITING: "待签",
    STATE_REJECTED: "未通过",
    STATE_UNKNOWN: "没查成",
}

#: 签是从哪一条通道读到的（读数格 `channel` 的取值）。
CHANNEL_ON_SHELF = "on_shelf"
CHANNEL_PENDING = "pending"
CHANNEL_LEDGER = "ledger"


def _empty(state: str = STATE_UNKNOWN, why: str = "") -> dict[str, Any]:
    """一格的初值：键无条件存在（三态纪律：不许靠少给键表达「没有读数」）。"""
    return {
        "checked": False,
        "state": state,
        "label": DELIVERY_LABELS.get(state, "没查成"),
        "delivered": state == STATE_SIGNED,
        "why": why,
        "channel": "",
        "ledger": "",
        "verification_id": "",
        "verdict": "",
        "sha": "",
        "judged": False,
        "standing": {},
        "pending": {},
    }


def _finish(out: dict[str, Any], state: str, why: str) -> dict[str, Any]:
    """收口：把档位与标签一起写回（`delivered` 只由档位派生，不许另算一处）。"""
    out["state"] = state
    out["label"] = DELIVERY_LABELS.get(state, "没查成")
    out["delivered"] = state == STATE_SIGNED
    out["why"] = why
    return out


def delivery_reading(root: Any, *, statement_id: str = "", proof_text: str = "",
                     proof_no: Any = 1) -> dict[str, Any]:
    """这一份证明此刻的「V 签」读数（纯读，四档；判据全部借既有那一层）。

    次序（先认签、再认打回、最后才是待签）：

    1. 在册签：`vsigns.sign_of(root, 正文 sha)` 有、且签上的命题号就是这一条、
       且 `streak >= need` ⇒ 已签。命题号对不上不算（同一段正文被别的命题复用
       不许借光，与 `vsigns.bits_after_sign` 同一句）。
    2. pending 签：`verifications.pending_sign` 按正文 sha 认到一行，且
       `verifications.row_signable(row)` 为真（结论「成立」、没有未解决的 error）
       ⇒ 已签。这一档就是「先签后登记」的那一半：B 登记时按同一把尺认领。
    3. 打回：pending 那一行签不住（结论不是「成立」）⇒ 未通过；
       在册台账那一侧用 `verifications.review_standing` 的六态读数 ——
       `rejected`、或 `holding` 而 `secretary_fault` 为真（判词写「成立」、
       秘书读出了缺陷）⇒ 未通过。
    4. 其余：`holding`（次数没到）/ `stale`（签的是旧版）/ `unsigned`（一次都没签）
       ⇒ 待签；`unreadable` 或读数本身没查成 ⇒ 没查成。

    `judged` 说「V 到底有没有对现在这一份正文出过结论」（不管结论是哪一档）：
    送审那一步靠它决定要不要真的再花一次 V 的调用（同一份正文不重复送审）。
    """
    from .. import verifications as VR
    from .. import vsigns as VS

    out = _empty(STATE_UNKNOWN)
    text = str(proof_text or "")
    sid = str(statement_id or "").strip()
    if not text.strip():
        out["checked"] = False
        return _finish(out, STATE_UNKNOWN,
                       "没有证明正文 ⇒ 没有可签的对象，这一格没查成"
                       "（不是「待签」：待签说的是有正文、还没签）")
    sha = VR.proof_sha(text)
    out["sha"] = sha
    try:
        no = int(VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1

    # ---- ① 在册签（out/vsigns/<正文 sha>.json）
    sign = dict(VS.sign_of(root, sha) or {})
    if sign.get("found"):
        doc = dict(sign.get("sign") or {})
        same_stmt = str(doc.get("statement_id") or "") == sid
        enough = int(doc.get("streak") or 0) >= int(doc.get("need") or 0)
        if same_stmt and enough:
            out.update(checked=True, channel=CHANNEL_ON_SHELF,
                       ledger=str(sign.get("path") or ""),
                       verification_id=str((doc.get("passes") or [{}])[-1].get(
                           "verification_id") or ""),
                       verdict=str(doc.get("verdict") or ""), judged=True)
            return _finish(
                out, STATE_SIGNED,
                f"`{out['ledger']}` 有签：连续 {doc.get('streak')}/{doc.get('need')}"
                f" 次成立，签的就是 stmt:{sid}（命题号与正文 sha 都对得上）")
    elif not sign.get("checked"):
        out["checked"] = False
        return _finish(out, STATE_UNKNOWN,
                       str(sign.get("why") or "签文件读不出来 ⇒ 这一格没查成"))

    # ---- ② pending 签（verifications/pending/<正文 sha>.jsonl）
    try:
        got = VR.pending_sign(root, proof_shas=(sha,))
    except VR.VerificationError as exc:
        out["checked"] = False
        return _finish(out, STATE_UNKNOWN,
                       f"`verifications/{VR.PENDING_DIR_NAME}/` 读不出来"
                       f"（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
    out["checked"] = True
    if got.get("found"):
        row = dict(got.get("row") or {})
        out.update(pending=row, ledger=str(got.get("ledger") or ""),
                   verdict=str(got.get("verdict") or ""), judged=True,
                   verification_id=str(row.get("verification_id") or ""))
        bound = str(row.get("stmt_id") or row.get("statement_id") or "")
        if bound and sid and bound != sid:
            out["pending"] = row
            return _finish(
                out, STATE_WAITING,
                f"{out['ledger']} 这一签已经认给 stmt:{bound} ⇒ 不是 stmt:{sid} 的签"
                "（同一份正文只认领一次）；这一条要重签")
        if VR.row_signable(row):
            out["channel"] = CHANNEL_PENDING
            return _finish(
                out, STATE_SIGNED,
                f"{out['ledger']} 是命题还没在册时 V 审的那一签"
                f"（verdict={out['verdict']!r}）⇒ 按正文 sha 认领得到，"
                "B 登记时由同一把尺认领（先签后登记与先登记后签是同一件事）")
        return _finish(
            out, STATE_REJECTED,
            f"{out['ledger']} 里那一签签不住（verdict={out['verdict']!r}、"
            f"未解决 error {int(row.get('unresolved_errors') or 0)} 条）："
            "V 审过这一份、结论不是能签的那一档 ⇒ 按缺陷改稿后再送")

    # ---- ③ 在册台账的六态读数（判据只有 `review_standing` 一处）
    if not sid:
        return _finish(
            out, STATE_WAITING,
            "还没有命题号（B 的登记没成）⇒ 在册台账查不到，pending 里也没有"
            "这一份的签；这一份还没送审，交不了差")
    standing = dict(VR.review_standing(root, statement_id=sid, proof_text=text,
                                       proof_no=no) or {})
    out["standing"] = standing
    state = str(standing.get("state") or "")
    out["judged"] = state in ("signed", "holding", "rejected", "stale")
    out["verdict"] = str(standing.get("verdict") or out["verdict"])
    out["verification_id"] = str(standing.get("verification_id") or "")
    out["ledger"] = str(standing.get("ledger") or "")
    if state == "signed":
        out["checked"] = True
        out["channel"] = CHANNEL_LEDGER
        return _finish(out, STATE_SIGNED,
                       f"{out['ledger']} 的现行正文有签（{standing.get('why')}）")
    if state == "rejected":
        out["checked"] = True
        return _finish(out, STATE_REJECTED,
                       f"{out['ledger']}：V 判过这一份、最近一签是 "
                       f"{out['verification_id'] or '（没有号）'}（verdict="
                       f"{out['verdict'] or '（空）'}）⇒ 复核过、结论不是能签的那一档，"
                       "按缺陷改稿后再送")
    if state == "holding" and standing.get("secretary_fault"):
        # 判词写「成立」、秘书读出了缺陷（业主 2026-10-30 第三次裁定：只要不是完全没毛病
        # 都叫有毛病）。这一档不许读成「还差几次」—— 那是把一条已点名的缺陷当成次数不够。
        out["checked"] = True
        return _finish(out, STATE_REJECTED,
                       f"{out['ledger']}：V 的判词是「成立」，但 V 的秘书读出了缺陷"
                       f"（secretary_fault，最近一签 {out['verification_id'] or '（没有号）'}）"
                       "⇒ 按缺陷改稿后再送（不是「还差几次」）")
    if state in ("holding", "stale", "unsigned"):
        out["checked"] = True
        return _finish(out, STATE_WAITING,
                       f"{out['ledger']}：这一份正文还没有签（{standing.get('why')}）"
                       "⇒ 送 V 审、拿到签才算交差")
    out["checked"] = False
    return _finish(out, STATE_UNKNOWN,
                   f"{out['ledger']} 的读数没查成（state={state or '空'}）："
                   f"{standing.get('why') or '没有理由'} —— 不许当成「待签」")


def _verification_summary(got: Mapping[str, Any]) -> dict[str, Any]:
    """V 那一次调用的读数摘要（不把整份 bits / citations 塞进计划台账）。"""
    passes = [dict(p) for p in (got.get("review_passes") or []) if isinstance(p, Mapping)]
    return {
        "checked": bool(got.get("checked")),
        "kind": str(got.get("kind") or ""),
        "verdict": str(got.get("verdict") or ""),
        "verification_id": str(got.get("verification_id") or ""),
        "ledger": str(got.get("ledger") or ""),
        "signed_bit3": bool(got.get("signed_bit3")),
        "reason": str(got.get("reason") or ""),
        "detail": str(got.get("detail") or "")[:600],
        "passes": [{k: p.get(k) for k in ("pass", "axis", "decision", "streak",
                                          "need", "streak_ok", "issue", "issued",
                                          "verdict", "verification_id", "terminal")}
                   for p in passes],
        "sign_issuance": dict(got.get("sign_issuance") or {}),
        "asked": len(passes),
    }


def submit_proof(*, store: Any, root: Any, statement_id: str = "", proof_text: str = "",
                 proof_no: Any = 1, verifier: Any = None) -> dict[str, Any]:
    """把这一份证明递给 V，再回读签（两步的读数都交出去）。

    ## 什么时候真的送（同一份正文不重复花钱）

    先读一次 `delivery_reading`：

    - 已经签了 ⇒ 不送（V 那边也有 `already_signed` 的短接，这里不再花一次调用）；
    - 这一份正文 V 已经判过（`judged` 为真、档位不是已签）⇒ 不重复送：
      打回之后要改稿，改完正文 sha 就变了，那时才该重送
      （业主 2026-11-01：「『知道了』与『改完了』是两件事」—— 同一份正文重送
      只会拿到同一条结论，而它要花三次模型调用）；
    - 还没审过（待签 / 没查到打回）⇒ 送。

    ## 没有命题号那一档

    `verify.verify_proof` 的 `statement_id` 是必填（工具面 `required`，实现里
    `S.is_valid_id` 不过就 `bad_statement_id`）⇒ 没有号就送不了。这一档如实报
    「没送」，回读照旧（`waiting`：pending 里也没有这一份的签）。不给两件东西
    编一个号，也不假装送过。

    返回键：`submitted` / `skipped` / `why` / `statement_id` / `reading`（回读）/
    `verification`（V 那一次的摘要；没送时是空对象）。
    """
    from .. import verifications as VR

    out: dict[str, Any] = {
        "submitted": False,
        "skipped": False,
        "checked": False,
        "why": "",
        "statement_id": str(statement_id or ""),
        "reading": {},
        "verification": {},
    }
    text = str(proof_text or "")
    before = delivery_reading(root, statement_id=statement_id, proof_text=text,
                             proof_no=proof_no)
    out["reading"] = before
    if before.get("delivered"):
        out.update(skipped=True, checked=True,
                   why="这一份正文已经有 V 签（在册或 pending）⇒ 不再送审")
        return out
    if not str(statement_id or "").strip():
        out.update(why=("没有命题号 ⇒ 送不了审：`verify.verify_proof` 的 `statement_id` "
                        "是必填（命题还没在册那条路今天只对穷举型证据开放）。"
                        "先把这一条登记成在册命题（B 的 register_statement）再送"))
        return out
    if before.get("judged"):
        out.update(skipped=True, checked=True,
                   why=(f"这一份正文 V 已经判过（{before.get('verdict') or '见台账'}）"
                        "⇒ 同一份不重复送审；按缺陷改稿之后正文 sha 变了再送"))
        return out
    if verifier is None:
        try:
            from ..agent_v import AgentV

            verifier = AgentV(store, workspace_root=root)
        except Exception as exc:  # noqa: BLE001 —— 造不出 V 就是「没送成」，不许静默
            out["why"] = f"V 造不出来（{type(exc).__name__}: {exc}）⇒ 这一份没送审"
            return out
    try:
        got = verifier.verify_proof(statement_id=str(statement_id),
                                   proof_text=text, proof_no=proof_no)
    except Exception as exc:  # noqa: BLE001 —— 送审失败是「没查成」，不是「没毛病」
        out["why"] = f"送审那一步失败（{type(exc).__name__}: {exc}）⇒ 这一份没审成"
        out["reading"] = delivery_reading(root, statement_id=statement_id,
                                         proof_text=text, proof_no=proof_no)
        return out
    if not isinstance(got, Mapping):
        out["why"] = f"V 的返回值不成形（{type(got).__name__}）⇒ 这一份没审成"
        return out
    out["submitted"] = True
    out["checked"] = bool(got.get("checked"))
    out["verification"] = _verification_summary(got)
    out["why"] = (str(got.get("reason") or got.get("detail") or "")
                  or ("V 收了这一份" if got.get("checked") else "V 没给出结论"))
    out["reading"] = delivery_reading(root, statement_id=statement_id,
                                     proof_text=text, proof_no=proof_no)
    return out


def selftest() -> int:
    """自检：四档词表与标签一一对上（不碰盘、不调模型）。"""
    problems: list[str] = []
    if set(DELIVERY_LABELS) != set(DELIVERY_STATES):
        problems.append("标签表与档位词表不是同一组")
    for state in DELIVERY_STATES:
        if not str(DELIVERY_LABELS.get(state) or "").strip():
            problems.append(f"档 {state!r} 没有标签")
    if (delivery_reading(".", proof_text="", statement_id="")["state"]
            != STATE_UNKNOWN):
        problems.append("空正文那一档不是「没查成」")
    for line in problems:
        print(f"FAIL {line}")
    print(f"vsign selftest: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
