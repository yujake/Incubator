# -*- coding: utf-8 -*-
"""F 侧的「V 签」读数：交差要拿签（业主 2026-11-02 裁定）。

口径逐字（这一笔的唯一目标）：

    重点是要F侧拿V签，拿到V签F才能交差

## 改前的缺口

`F -> V` 那条边一直在（`capabilities.ALLOWED_EDGES["F"]` 含 `"V"`，
声明真身是 `specs/f.py::SPEC.edges`），`agent_skills` 也一直教 F「你产出的证明由你派
V 签」；而 `agent_f` 的实现交完 B 的登记就结束了 —— 没有任何一处回读签，
`F.step` 的返回值里也就没有一格说「这一份证明签了没有」。83 的定格读数就是现场：
F 写的五份证明一份都没签（`out/vsigns/` 只有 000005 一份），而每一趟都照样回
`outcome=progress`。

## 这一格只做一件事：读签（不送审、不代派）

业主 2026-11-02 的第二句把送审的路定死了：「F 不是直接能派 V 吗」——
派 V 是 F 自己的动作（`framework_summon` 形状，边在，83 真机派过 17 次），
所以这一层不调 `AgentV`、也不替 F 派活：它只回答「这一份证明现在有没有 V 签」。
F 在写证明的那一趟里派 V，之后读到的就是这里给的读数。

## 四档（与 `verifications.REVIEW_STATES` 同一把尺，不另立口径）

- `signed` 已签：有一份签盖住现行正文 —— 手稿里的签块（业主指定的落点，
  `vsigns.manuscript_sign_standing`）、`out/vsigns/<正文 sha>.json`、或
  `verifications/pending/<正文 sha>.jsonl` 里那一签，三处任一成立即可；
- `rejected` 未通过：V 判过这一份、结论不是「成立」（含"判词写成立、秘书读出缺陷"）；
- `waiting` 待签：没有签、也没有打回（含「还没送审」与「审过、连续次数没到」）；
- `unknown` 没查成：台账 / 签块 / pending 读不出来（不许折成「待签」）。

`delivered` 只在 `signed` 时为真 —— 拿不到 V 签，这一趟就读成「没交差」。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from .. import proofregistry as _PR

#: 已签：现行正文有一份盖得住的签（手稿签块 / 侧文件 / pending 三处任一）。
STATE_SIGNED = "signed"
#: 待签：没有签、也没有打回 —— 含「还没送审」与「审过、连续次数没到」。
STATE_WAITING = "waiting"
#: 未通过：V 判过这一份、结论不是「成立」（或秘书读出了缺陷）。
STATE_REJECTED = "rejected"
#: 没查成：台账 / 签块 / pending 读不出来。它不是「待签」，也不是「未通过」。
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
CHANNEL_MANUSCRIPT = "manuscript"
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
        "manuscript": {},
    }


def _finish(out: dict[str, Any], state: str, why: str) -> dict[str, Any]:
    """收口：把档位与标签一起写回（`delivered` 只由档位派生，不许另算一处）。"""
    out["state"] = state
    out["label"] = DELIVERY_LABELS.get(state, "没查成")
    out["delivered"] = state == STATE_SIGNED
    out["why"] = why
    return out


def _manuscript_block(root: Any, paths: Sequence[str], *, sha: str) -> dict[str, Any]:
    """从候选手稿路径里读第一份存在的稿上的签块（读不到 ⇒ 空读数，不猜）。"""
    from pathlib import Path

    from .. import vsigns as VS

    for rel in paths or ():
        rel = str(rel or "").strip().replace("\\", "/")
        if not rel:
            continue
        try:
            text = (Path(str(root or "")) / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        got = VS.manuscript_sign_standing(text, proof_sha=sha, manuscript_path=rel)
        got["path"] = rel
        return got
    return {}


def delivery_reading(root: Any, *, statement_id: str = "", proof_text: str = "",
                     proof_no: Any = 1,
                     manuscript_paths: Sequence[str] = ()) -> dict[str, Any]:
    """这一份证明此刻的「V 签」读数（纯读，四档；判据全部借既有那一层）。

    次序（先认签、再认打回、最后才是待签）：

    0. 手稿签块：`manuscript_paths` 里第一份存在的稿上的签块
       （`vsigns.manuscript_sign_standing`）—— 这是业主 2026-11-01 指定的落点：
       「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题收录时读到」。
       块里 sha 与这一份正文相符且 `连续>=need` ⇒ 已签；`已签=false` ⇒ 未通过；
       块是旧版的 ⇒ 继续往下问（台账里可能有更新的签）。
    1. 在册签：`vsigns.sign_of(root, 正文 sha)` 有、且签上的命题号就是这一条、
       且 `streak >= need` ⇒ 已签。命题号对不上不算（同一段正文被别的命题复用
       不许借光，与 `vsigns.bits_after_sign` 同一句）。
    2. pending 签：`verifications.pending_sign` 按正文 sha 认到一行，且
       `verifications.row_signable(row)` 为真 ⇒ 已签。
    3. 打回：手稿块说没过 / pending 那一行签不住 / 在册台账那一侧
       `verifications.review_standing` 的 `rejected`（或 `holding` 而
       `secretary_fault`）⇒ 未通过。
    4. 其余：`holding` / `stale` / `unsigned` ⇒ 待签；`unreadable` 或读数本身
       没查成 ⇒ 没查成。

    `judged` 说「V 到底有没有对现在这一份正文出过结论」（不管结论是哪一档）。
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
    sha = _PR.proof_sha(text)
    out["sha"] = sha
    try:
        no = int(VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1

    # ---- 0. 手稿里的签块（业主指定的落点）
    block = _manuscript_block(root, manuscript_paths, sha=sha)
    if block:
        out["manuscript"] = dict(block)
        state = str(block.get("state") or "")
        if state == "signed":
            out.update(checked=True, channel=CHANNEL_MANUSCRIPT,
                       ledger=str(block.get("path") or ""),
                       verdict=str(block.get("verdict") or ""), judged=True)
            return _finish(out, STATE_SIGNED,
                           f"手稿 `{out['ledger']}` 里的 V 签块：{block.get('why')}")
        if state == "rejected":
            out.update(checked=True, judged=True,
                       ledger=str(block.get("path") or ""),
                       verdict=str(block.get("verdict") or ""))
            return _finish(out, STATE_REJECTED,
                           f"手稿 `{out['ledger']}` 里的 V 签块是「"
                           f"{block.get('verdict') or '（空）'}」⇒ 按缺陷改稿后再送")
        # stale / unsigned / 读不成形：继续往下问（台账里可能有更新的签）。

    # ---- 1. 在册签（out/vsigns/<正文 sha>.json）
    sign = dict(VS.sign_of(root, sha) or {})
    if sign.get("found"):
        doc = dict(sign.get("sign") or {})
        same_stmt = str(doc.get("statement_id") or "") == sid
        enough = int(doc.get("streak") or 0) >= int(doc.get("need") or 0)
        # 2026-11-03 件一：未在册（`sid == ""`）的签不按侧文件认 —— 业主 2026-11-02 指定的
        # 落点是手稿块（步骤 0）。侧文件只是 V 那一半的档；块没落（收方秘书没拿到 /
        # 父角色读不到）时它不能冒充"已签"，否则「把 land 摘掉 ⇒ F 回落待签」量不出来。
        if sid and same_stmt and enough:
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

    # ---- 2. pending 签（verifications/pending/<正文 sha>.jsonl）
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
            return _finish(
                out, STATE_WAITING,
                f"{out['ledger']} 这一签已经认给 stmt:{bound} ⇒ 不是 stmt:{sid} 的签"
                "（同一份正文只认领一次）；这一条要重签")
        if VR.row_signable(row):
            out["channel"] = CHANNEL_PENDING
            return _finish(
                out, STATE_SIGNED,
                f"{out['ledger']} 是命题还没在册时 V 审的那一签"
                f"（verdict={out['verdict']!r}）⇒ 按正文 sha 认领得到")
        return _finish(
            out, STATE_REJECTED,
            f"{out['ledger']} 里那一签签不住（verdict={out['verdict']!r}、"
            f"未解决 error {int(row.get('unresolved_errors') or 0)} 条）："
            "V 审过这一份、结论不是能签的那一档 ⇒ 按缺陷改稿后再送")

    # ---- 3. 在册台账的六态读数（判据只有 `review_standing` 一处）
    if not sid:
        return _finish(
            out, STATE_WAITING,
            "还没有命题号（B 的登记没成）⇒ 在册台账查不到，pending 里也没有"
            "这一份的签；这一份还没签，交不了差")
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
                       "⇒ 派 V 审这一份、拿到签才算交差")
    out["checked"] = False
    return _finish(out, STATE_UNKNOWN,
                   f"{out['ledger']} 的读数没查成（state={state or '空'}）："
                   f"{standing.get('why') or '没有理由'} —— 不许当成「待签」")


def next_step_hint(reading: Mapping[str, Any], *, statement_id: str = "",
                   manuscript_paths: Sequence[str] = ()) -> str:
    """这一份证明下一步该干什么（给 `F.step` 的 `detail` 用）。

    已签 ⇒ 别再送（同一份正文重送只会拿到同一条结论）；其余三档各给一条可执行的话。
    送审的口径只有一个：F 自己派 V（`framework_summon`，边在）——
    `statement_id` 有号就在 `task` 里点号，没号就点手稿路径。
    """
    state = str(reading.get("state") or "")
    target = (f"stmt:{statement_id}" if statement_id
              else (manuscript_paths[0] if manuscript_paths else "这一份手稿"))
    if state == STATE_SIGNED:
        return f"已签（{reading.get('ledger') or ''}）⇒ 这一份不用再送，换下一个子目标"
    if state == STATE_REJECTED:
        return ("V 判过这一份、没过 ⇒ 按 findings 指到的步号改稿，改完再派 V 重签"
                "（同一份正文不重复判，改过字才重判）")
    if state == STATE_UNKNOWN:
        return ("签这一格没查成 ⇒ 先查为什么（签块 / 台账 / pending 读不出来），"
                "别把它读成「没毛病」")
    return (f"派 V 审这一份（`framework_summon` 形状：`role=\"V\"`，`task` 写清 {target} "
            "与要审什么）—— 拿到 V 签才算交差；派不出去（深度 / 边）就照实写进回报")


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
