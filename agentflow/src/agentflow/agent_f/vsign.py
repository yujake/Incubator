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
    """这一份证明此刻的「V 签」读数（纯读，四档；D268 批 2 起判据只有 `sign_reading`）。

    改前这一格按"块 / 侧文件 / pending 行"三条路各认一次签，三条都只看"在不在"
    或"最后一行签不签得住"，不数票。批 2 起统一走 `vsigns.sign_reading`：

    - `signed` ⇒ 有可复算的凭据（签文件里的 need 行在台账上点得出来）；
    - `rejected` ⇒ 停因 math/contract（改稿再送）；`retry_report`（程序性/文风）
      也落 `rejected` 这一档，但 `out["retry_report"]=True`，下一步说"原样再送"；
    - `waiting` ⇒ `holding` / `stale` / `unissued` / `unbacked` / `borrowed` /
      `unsigned`：还没有一份能算数的签；
    - `unknown` ⇒ `unreadable` / 读数没查成。

    手稿块仍然读出来放在 `out["manuscript"]` —— 它只是给人看的视图，不参与判定。
    """
    from pathlib import Path

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
    paths = [str(p or "").strip().replace("\\", "/") for p in (manuscript_paths or ())
             if str(p or "").strip()]
    rel = next((p for p in paths if (Path(str(root or "")) / p).is_file()),
               paths[0] if paths else "")
    block = _manuscript_block(root, paths, sha=sha) if paths else {}
    if block:
        out["manuscript"] = dict(block)   # 视图，不参与判定
    got = dict(VS.sign_reading(root, statement_id=sid, proof_text=text, proof_no=no,
                               manuscript_path=rel) or {})
    out["standing"] = got
    out["checked"] = bool(got.get("checked"))
    out["sha"] = str(got.get("sha") or sha)
    ev = dict(got.get("evidence") or {})
    cred = dict(got.get("credential") or {})
    out["verdict"] = str(ev.get("verdict") or "")
    out["verification_id"] = str(cred.get("verification_id")
                                 or (ev.get("last_row") or {}).get("verification_id") or "")
    out["ledger"] = str(cred.get("path") or "")
    state = str(got.get("state") or "unsigned")
    out["judged"] = state in ("signed", "holding", "rejected", "retry_report", "stale")
    if not out["checked"]:
        return _finish(out, STATE_UNKNOWN,
                       f"签的读数没查成（{got.get('why') or '没有理由'}）"
                       "—— 不许当成「待签」")
    if state == "signed":
        out["channel"] = CHANNEL_ON_SHELF if sid else CHANNEL_PENDING
        return _finish(out, STATE_SIGNED,
                       f"{out['ledger'] or '签文件'} 复算通过：{got.get('why')}")
    if state in ("rejected", "retry_report"):
        out["retry_report"] = state == "retry_report"
        return _finish(out, STATE_REJECTED,
                       f"{out['ledger'] or '台账'}：{got.get('why')}")
    if state in ("holding", "stale", "unissued", "unbacked", "borrowed", "unsigned"):
        return _finish(out, STATE_WAITING,
                       f"这一份正文还没有一份能算数的签（state={state}）："
                       f"{got.get('why')} ⇒ 派 V 审这一份、拿到签才算交差")
    return _finish(out, STATE_UNKNOWN,
                   f"签的读数是 {state!r}（不认识的档）⇒ 这一格没查成，不许当成「待签」")


def next_step_hint(reading: Mapping[str, Any], *,
                   manuscript_paths: Sequence[str] = ()) -> str:
    """这一份证明下一步该干什么（给 `F.step` 的 `detail` 用）。

    已签 ⇒ 别再送（同一份正文重送只会拿到同一条结论）；其余三档各给一条可执行的话。
    送审的口径只有一个：F 自己派 V（`framework_summon`，边在）——
    要审的是**哪一份稿**，所以这一句点的是手稿路径。

    ## 签名里没有 `statement_id`（2026-11-10 第二刀，业主裁定）

    裁定逐字：「撤去所有有关对某个给定命题号进行攻坚或写证明的逻辑。」
    改前这一句在"有号"时把任务写成「`stmt:<号>`」，没号才点稿路径 —— 于是同一趟活
    在 F 眼里有两个身份，而命题号那一半是**收方**（B）在收录时才发的号：F 拿着它
    去指认"要审哪一份"，等于把收录的产物当成自己的攻坚目标。
    现在只认稿路径：F 交出去的永远是 `reports/f-proof-<稿号>.md`（另一份证明是 `-p<N>`），
    正文 sha 由签那一侧现算。判据：`tests/test_f_does_not_work_for_a_statement_number.py`。
    """
    state = str(reading.get("state") or "")
    target = (manuscript_paths[0] if manuscript_paths else "这一份手稿")
    if state == STATE_SIGNED:
        return f"已签（{reading.get('ledger') or ''}）⇒ 这一份不用再送，换下一个子目标"
    if state == STATE_REJECTED:
        if reading.get("retry_report"):
            return ("V 判过这一份，但停因是程序性/文风（不是正文缺陷）⇒ 同一份正文"
                    "原样再送，不用改稿；要补的是 V 的报告记录")
        return ("V 判过这一份、没过 ⇒ 按 findings 指到的步号改稿，改完再派 V 重签"
                "（同一份正文不重复判，改过字才重判）")
    if state == STATE_UNKNOWN:
        return ("签这一格没查成 ⇒ 先查为什么（签块 / 台账 / pending 读不出来），"
                "别把它读成「没毛病」")
    return (f"派 V 审这一份（`framework_summon` 形状：`role=\"V\"`，`task` 写清"
            f"「审这一份证明稿 {target}」与要审什么）—— 拿到 V 签才算交差；"
            "派不出去（深度 / 边）就照实写进回报")


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
