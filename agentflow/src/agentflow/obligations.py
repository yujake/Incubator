# -*- coding: utf-8 -*-
"""板项义务：重送（`v-resubmit@`）与收录（`b-register@`）。

## 这一层治的是什么

V 判「有毛病」之后，除了"这一条判词要送到送审者"，还有一条必须交付的活：
把这一份正文改好、重新送 V，直到拿到干净的「成立」；或者明确放弃原命题。
同样，一份稿上落了成立的 V 签之后，B 必须把它收录进 `statements`。

这两件事都不是"读到了"就算办完（ack 只表示看到了），它们的收口条件是盘上的事实：
更新的干净「成立」行 / `statements` 里出现正文且 `reviewed=true`。所以它们各开一条
`expects="work"` 的板项，凭证据收口（`conductor.close_item_by_evidence`），
不新造第二套板项。

## 投递层已退场（2026-11-16 业主裁定「vreceipts 退场」）

本模块的前身 `vreceipts.py` 还管着另一半：把 V 的判词投给送审者（outbox 意图 →
开板项 → 收工前补投）。那一半整层删除，因为它的存在理由是一条错误诊断：

- 旧诊断逐字：「投递发生在收件人下一次起跑那一刻 ⇒ 收件人不醒，回执就不存在」；
- 核实（业主逐字：「怎么可能收件人不醒，难道不是任何一条消息或计时器返回都会唤醒吗
  （来消息就是兜底计时器返回）？」）：收件人不是"不醒"——任何一条板项 / 消息落进它
  名下，都会经 `agent_loop._deliver_mailbox` 唤醒它；计时器返回同样是一条消息。
  判据 `tests/test_a_message_wakes_the_silent_agent.py` /
  `tests/test_mailbox_delivers_mid_run_and_wakes_the_parent.py` /
  `tests/test_a_silent_agent_is_wakeable_unless_retired.py`。
- AH5 里"70% 判词没送到"的真因是 `v-wash@<sha[:16]>@<parent>` 这个幂等键
  （`agent_v/core.py` 的 `_relay_unregistered_wash`）：同一份正文对同一收件人只送第一次，
  不是收件人没醒。

于是投递只剩既有的那几条路（都不在本模块）：
`vreviews.deliver_review`（判出有毛病那一刻的 V 稿 notice）、
`agent_loop.deliver_v_verdicts`（收件人下一次起跑时按台账递送）、
以及本模块开的 `v-resubmit@` 工作项 —— 三条都落在收件人名下的板项上，都会唤醒它。

## 两族义务

- `v-resubmit@<命题号>@<proof_sha256>`：不带收件人后缀（带后缀会为每一次起跑各开
  一条）；负责人 = 那一次送审的送审者；关闭条件 = 同一份证明出现更新的干净「成立」
  行，不是 ack；放弃原命题时 `close="expired"` 作废。
- `b-register@<命题号>@<被签正文的 sha>`：负责人是角色 B（认不出唯一在飞的 B 也照样
  开项，父为空 ⇒ 不挂在任何人的销号闸上）；关闭条件 = 那一行出现正文且
  `reviewed=true`，或命题被明确放弃（可解析的放弃标记）。

## 三态

"读不成"永远不是"没有义务"：`checked=False` + `reason` 逐处写明，调用方照它记读数。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import manuscriptfamily as _MFAM
from . import statementledger as SL



# ------------------------------------------------------------------ 重送义务（I2）
#
# 业主裁定把"打回"变成了两种东西：一条判词（已送到），以及一条必须重送的义务。
# 判词送到 ≠ 命题有了 V 签：回执可以全部读到、甚至 acked/done，而命题至今没有签。
# "知道了"（ack）与"改完了"（新的成立行）是两件事，而只有后者能关掉一条重送义务。
#
# 所以这一档单独立一条板项（复用 `conductor.open_item` / `set_item_detail`，
# 不新造第二套板项）：
#   · 幂等键 `v-resubmit@<命题号>@<proof_sha256>`：不带收件人后缀。带后缀的键会
#     为每一次 F 起跑各开一条，同一份正文因此长出多条重复项；
#   · 负责人 = 那一次送审的送审者（`conductor.current_parent()`，这一趟召唤的父）。
#     取不到就记 `owner="unknown"`，由收工读数 `statements_unsigned` 的 `owner_known`
#     说清楚（"记 unknown 并进收工读数"），不拿"谁醒着"当负责人；
#   · 关闭条件 = 同一命题出现更新的干净「成立」行（`settle_resubmitted`），不是 ack：
#     `expects="work"` ⇒ 收口只能是 `completed` / `expired`（`schema.Task.validate`
#     的交叉校验），拿到"知道了"什么也关不掉；
#   · 放弃原命题时这一项同时作废（`close_resubmits_for`，`close="expired"`）——
#     否则"放弃"这条出口会被"名下还有未消的板项"反锁住（`retire_integrity`）。

#: 重送义务板项的幂等键前缀（I2）。与 `v-verdict@` 分开：后者是回执，前者是义务。
RESUBMIT_PREFIX = "v-resubmit@"


def resubmit_key(label: str, proof_sha: str) -> str:
    """重送义务的幂等键：`v-resubmit@<命题号>@<proof_sha256>`。

    为什么键里是 sha 而不是 proof 编号：sha 是"哪一份正文"的指纹；一个稿号 = 一份
    文件 = 一份证明，换了 sha 就是另一份正文（另一个稿号），该开新的义务。
    刻意不带收件人后缀（见上面那一段）。
    """
    sid = str(label or "").split("#", 1)[0]
    return f"{RESUBMIT_PREFIX}{sid}@{str(proof_sha or '').strip()}"


def resubmit_sha_of(key: str) -> str:
    """从重送义务的键里取回 `proof_sha256`（认不出 ⇒ 空串，不猜）。"""
    raw = str(key or "")
    if not raw.startswith(RESUBMIT_PREFIX):
        return ""
    rest = raw[len(RESUBMIT_PREFIX):]
    _sid, sep, sha = rest.partition("@")
    return sha if sep else ""


def _resubmit_items(conductor: Any, statement_id: str) -> list[dict[str, Any]]:
    """这一条命题名下未消的重送项（读不成 ⇒ 空列表，由调用方的话说清）。"""
    if conductor is None:  # 未接板 ⇒ 没有可读的板项；这是「没接上」，
        # 由调用方判 None 后写 `skipped` + reason 说清（不折成「查过、没有」）
        return []
    want = f"{RESUBMIT_PREFIX}{str(statement_id or '')}@"
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001 —— 读不成不是"没有义务"
        return []
    return [r for r in rows
            if str(r.get("input_key") or "").startswith(want)
            and str(r.get("item_state") or "") != "done"]


def _resubmit_item_by_key(conductor: Any, key: str) -> dict[str, Any]:
    """板上有没有这一条（精确键：不认收件人后缀，那是回执那一侧的兼容口径）。"""
    if conductor is None:  # 未接板 ⇒ 没有可读的板项；这是「没接上」，
        # 由调用方判 None 后写 `skipped` + reason 说清（不折成「查过、没有」）
        return {}
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001
        return {}
    for row in rows:
        if str(row.get("input_key") or "") == str(key or ""):
            return row
    return {}


def _ledger_rows(*, root: str | Path, statement_id: str
                 ) -> tuple[list[dict[str, Any]], list[str]]:
    """这条命题的台账（原样读，坏行进 problems；不折成"没有签"）。"""
    from . import verifications as VR

    try:
        rows, problems = VR.list_verifications(root, statement_id=statement_id, limit=None)
    except Exception as exc:  # noqa: BLE001
        return [], [f"台账读不成（{type(exc).__name__}: {exc}）"]
    return [dict(r) for r in rows], [str(p) for p in problems]


def _proof_no_of_sha(rows: Sequence[Mapping[str, Any]], sha: str) -> int | None:
    """这个 sha 在老台账行里的证明号（从行反查；认不出 ⇒ `None`）。

    为什么不从 statements 行现算：F 改过稿之后，旧 sha 已经不在现行正文里了。
    台账是追加式的，它记得那份旧正文属于哪个证明号 —— 那正是"关闭条件按证明号
    匹配"要的东西。
    """
    from . import verifications as VR

    want = str(sha or "")
    if not want:
        return None
    for row in rows:
        if str(row.get("proof_sha256") or "") != want:
            continue
        return int(VR.as_proof_no(row.get("proof_no")) or 1)
    return None


def resubmit_cleared(*, root: str | Path, label: str, proof_sha: str) -> dict[str, Any]:
    """这一份正文（sha）的"重送义务"是否已经被一条更新的干净「成立」行清掉。

    判据（三态）：台账读不成 ⇒ `checked=False`（不是"没清掉"，也不是"清掉了"）；
    查成了 ⇒ `cleared` 说结论，`later_at` / `later_verification_id` 是那条成立的签。
    """
    from . import verifications as VR
    from . import vsigns as VSP

    out: dict[str, Any] = {"checked": False, "cleared": False, "proof_no": None,
                           "later_at": "", "later_verification_id": "", "why": ""}
    sid = str(label or "").split("#", 1)[0]
    rows, problems = _ledger_rows(root=root, statement_id=sid)
    if problems:
        out["why"] = "；".join(problems[:2])
        return out
    out["checked"] = True
    sha = str(proof_sha or "")
    no = _proof_no_of_sha(rows, sha)
    out["proof_no"] = no
    if no is None:
        out["why"] = (f"台账里没有任何一行盖着 sha={sha[:12]}… ⇒ 认不出这是第几份证明"
                      "（那就不猜它有没有被清掉）")
        return out
    # ---- 作废行不许清义务 ---------------------------------------------------
    #
    # 现场见 `verifications._hold_runs` 的 docstring（同一份正文重开一趟 ⇒ 那三行作废）：
    # 作废行不是"打回之后更干净的「成立」"。尺与连续计数同一处（`void_after_rejection`
    # → `_hold_runs`）—— 两边各判一套，就会"不算票、却算义务已清"。
    try:
        void = VR.void_after_rejection([dict(r) for r in rows])
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有作废行"
        out.update(checked=False,
                   why=(f"作废行读不出来（{type(exc).__name__}: {exc}）"
                        " ⇒ 判不了这条义务清没清（不许当成「已清」）"))
        return out
    last_fault = -1
    for i, row in enumerate(rows):
        if int(VR.as_proof_no(row.get("proof_no")) or 1) != no:
            continue
        if str(row.get("proof_sha256") or "") == sha:
            last_fault = i
    for i in range(last_fault + 1, len(rows)):
        row = rows[i]
        if int(VR.as_proof_no(row.get("proof_no")) or 1) != no:
            continue
        if i < len(void) and void[i]:
            # 打回之后又起转的那一行：不作数（不许拿它把义务清掉）。
            continue
        if VR.read_verdict(row) != "成立":
            continue
        if VSP.verdict_axis(row):
            continue
        out.update(cleared=True, later_at=str(row.get("at") or ""),
                   later_verification_id=str(row.get("verification_id") or ""),
                   why=(f"{label} 在那次打回之后又有一次干净的「成立」"
                        f"（{row.get('verification_id')}，{row.get('at')}）⇒ 义务已清"))
        return out
    out["why"] = "这一次打回之后还没有更新的干净「成立」⇒ 义务还在"
    return out


def _resubmit_body(*, label: str, detail: Mapping[str, Any], at: str) -> tuple[str, str]:
    """重送项的一句话摘要 + 正文（上限 = `agent_loop.BOARD_DETAIL_CHARS`，480 字）。

    与 `_register_body` 同一个上限：这两条义务的正文都带"两条出路"，写者与渲染层
    各拍一个数就是 ② 被切的那条缝（全文 306 字，480 之下一个字都不切）。
    """
    from .agent_loop import BOARD_DETAIL_CHARS

    step = (f"第 {detail.get('defect_step')} 步" if detail.get("defect_step")
            else "步号没读到")
    sha = str(detail.get("proof_sha256") or "")
    summary = f"待重送：{label}（打回于 {at or '时刻没读到'}，错在{step}）"
    body = (
        f"这是一条必须重送的义务，不是通知：{label} 被 V 判过缺陷"
        f"（最近一签 {detail.get('verification_id') or '（没读到编号）'}，错在{step}，"
        f"这一签盖的是 sha {sha[:12]}…）。\n"
        "收口条件只有一条：同一条命题（同一份证明）出现更新的、干净的「成立」行 ——"
        "届时这一项由框架自动收口（completed），不靠 ack；"
        "退回一句「知道了」不会让它消失。\n"
        "两条出路：① 补齐之后把这一份重新送 V（`verify.verify_proof`）重签；"
        "② 确实做不下去就明确放弃原命题（B 侧：`table.update` 该命题 "
        "`status=abandoned` + 放弃标记，理由与时间缺一不可）——放弃时这一项同时作废。"
    )
    return summary, body[:int(BOARD_DETAIL_CHARS)]


def ensure_resubmit(*, store: Any, root: str | Path, label: str,
                    verification_id: str, detail: Mapping[str, Any], recipient: str,
                    role: str, depth: int, at: str = "") -> dict[str, Any]:
    """开一条「待重送」板项（幂等；已清掉的不开）。

    返回 `{"checked","state","key","item_id","owner","reason","problems"}`，`state ∈
    {opened, existing, cleared, closed, unowned, skipped, error}`：

    - `opened`：新开了一条；
    - `existing`：同键的项已经在板上（不重开 —— 这是幂等的落点）；
    - `cleared`：这次打回之后已经有一条更新的干净「成立」⇒ 义务本来就没了，不开
      （历史补投会走到这一支：旧判决不该在收工时凭空长出一条待办）；
    - `closed`：板上那条已经 done（不重开，读数说"已经收口"）；
    - `unowned`：读不到送审者 ⇒ 不猜负责人、不开项，负责人记 `unknown`（收工读数里
      `statements_unsigned.rows[].owner_known=False` 会把它说清楚）；
    - `skipped`：这一行没有 sha / 没有命题号 ⇒ 做不出幂等键（不猜）；
    - `error`：开项抛了（`problems` 里带原话），不带走这一签。
    """
    from . import vsigns as VSP

    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "owner": str(recipient or ""), "reason": "", "problems": []}
    sid = str(label or "").split("#", 1)[0]
    sha = str(detail.get("proof_sha256") or "")
    if not sid or not sha:
        out.update(state="skipped",
                   reason="这一行没有命题号 / 没有 proof_sha256 ⇒ 做不出幂等键（不猜）")
        return out
    key = resubmit_key(label, sha)
    out["key"] = key
    cleared = resubmit_cleared(root=root, label=label, proof_sha=sha)
    if not cleared.get("checked"):
        out.update(state="skipped",
                   reason=(f"台账读不成 ⇒ 判不了这条义务清没清（{cleared.get('why')}）"
                           "；不拿'读不出来'当'还没清'去开一条待办"))
        out["problems"].append(str(cleared.get("why") or "台账读不成"))
        return out
    conductor = _conductor(store)
    if cleared.get("cleared"):
        # 已经清了：板上若还开着那一条（历史遗留），顺手收口；没有就什么都不开。
        row = _resubmit_item_by_key(conductor, key)
        if row and conductor is not None:
            _state, why = conductor.close_item_by_evidence(
                str(row.get("task_id") or ""), close="completed",
                why=f"义务已清：{cleared.get('why')}")
            if why:
                out["problems"].append(why)
        out.update(checked=True, state="cleared", item_id=str(row.get("task_id") or ""),
                   reason=str(cleared.get("why") or "义务已清"))
        return out
    if not str(recipient or ""):
        out.update(state="unowned", owner="unknown",
                   reason=("读不到送审者 ⇒ 不猜负责人、不开项；负责人记 unknown，"
                           "由收工读数 statements_unsigned 的 owner_known 说清楚"))
        return out
    row = _resubmit_item_by_key(conductor, key)
    if row:
        task_id = str(row.get("task_id") or "")
        state = str(row.get("item_state") or "")
        out.update(checked=True, item_id=task_id,
                   state=("closed" if state == "done" else "existing"),
                   reason=(f"同键的板项已存在（{task_id}，item_state={state}）⇒ 不重开"))
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason="这一趟没有 conductor ⇒ 板项开不了（不拿意图当交付）")
        return out
    summary, body = _resubmit_body(label=label, detail=detail, at=at)
    try:
        item_id = conductor.open_item(
            kind="notice", role=str(role or ""), expects="work", action="notice",
            summary=summary, called_by="V", parent_task_id=str(recipient),
            depth=int(depth or 1) + 1, input_key=key)
        conductor.set_item_detail(item_id, body)
    except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走这一签
        out.update(state="error",
                   reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
        return out
    out.update(checked=True, state="opened", item_id=item_id,
               reason=f"新开重送项 {item_id}（负责人 {recipient}）")
    return out


def settle_resubmitted(*, store: Any, root: str | Path,
                       row: Mapping[str, Any]) -> dict[str, Any]:
    """一条干净的「成立」签落下之后：把同一份证明名下开着的重送项收口。

    判据（缺一不可）：这一行的结论词是「成立」，且秘书没有判 fault（判 fault 的
    "成立"仍然是一次打回）。收口方式
    `close="completed"`（"做完了"，不是"知道了"），由 `conductor.close_item_by_evidence`
    落盘：那是唯一一条不是收件人 ack 的收口语义。

    返回 `{"checked","closed","skipped","problems","reason"}`；台账读不成 ⇒
    `checked=False`（不是"没有要收口的"）。
    """
    from . import verifications as VR
    from . import vsigns as VSP

    out: dict[str, Any] = {"checked": False, "closed": [], "skipped": [],
                           "problems": [], "reason": ""}
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    if not sid:
        out["reason"] = "这一行没有命题号 ⇒ 判不了要收口哪一条"
        return out
    if VR.read_verdict(row) != "成立" or VSP.verdict_axis(row):
        out.update(checked=True, reason="这一签不是干净的「成立」⇒ 没有义务要收口")
        return out
    no = int(VR.as_proof_no(row.get("proof_no")) or 1)
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "这一趟没有 conductor ⇒ 板项收不了口（不是「没有要收口的」）"
        return out
    rows, problems = _ledger_rows(root=root, statement_id=sid)
    out["checked"] = True
    out["problems"].extend(problems)
    for item in _resubmit_items(conductor, sid):
        key = str(item.get("input_key") or "")
        sha = resubmit_sha_of(key)
        item_no = _proof_no_of_sha(rows, sha)
        if item_no is None:
            # 认不出属于第几份证明 ⇒ 不猜；只在 sha 完全相同时收口。
            if sha and sha == str(row.get("proof_sha256") or ""):
                item_no = no
            else:
                out["skipped"].append({"key": key,
                                       "why": "认不出这条义务是第几份证明的（台账里没有那个 sha）"})
                continue
        if item_no != no:
            continue
        task_id = str(item.get("task_id") or "")
        _state, why = conductor.close_item_by_evidence(
            task_id, close="completed",
            why=(f"同一份证明（#p{no}）出现了干净的「成立」："
                 f"{row.get('verification_id') or '（没读到编号）'}"))
        if why:
            out["problems"].append(f"{task_id}：{why}")
            continue
        out["closed"].append(task_id)
    out["reason"] = (f"收口 {len(out['closed'])} 条重送项"
                     + (f"；{len(out['skipped'])} 条认不出是哪一份证明" if out["skipped"] else "")
                     + (f"；{len(out['problems'])} 条没收成" if out["problems"] else ""))
    return out


def close_resubmits_for(store: Any, *, statement_id: str, why: str) -> dict[str, Any]:
    """把一条命题名下全部开着的重送项作废（`close="expired"`）。

    谁调它：放弃原命题那一步（`Secretary` 的 abandoned 分支）。为什么必须调：
    `retire_integrity` 把"名下还有未消的板项"算成不干净，而放弃之后的义务不该再
    压着任何人 —— 不在这里收口，"放弃"这条出口会被销号闸反锁住。
    """
    out: dict[str, Any] = {"checked": False, "closed": [], "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "这一趟没有 conductor ⇒ 重送项收不了口（不是「没有要收口的」）"
        return out
    out["checked"] = True
    for item in _resubmit_items(conductor, statement_id):
        task_id = str(item.get("task_id") or "")
        _state, problem = conductor.close_item_by_evidence(
            task_id, close="expired", why=str(why or "命题被明确放弃"))
        if problem:
            out["problems"].append(f"{task_id}：{problem}")
            continue
        out["closed"].append(task_id)
    out["reason"] = (f"作废 {len(out['closed'])} 条重送项"
                     + (f"；{len(out['problems'])} 条没收成" if out["problems"] else ""))
    return out


def resubmit_digest(root: str | Path, store: Any = None) -> dict[str, Any]:
    """重送义务的读数：开着的 / 认不出负责人的 / 逐条明细（收工与判据共用）。"""
    out: dict[str, Any] = {"checked": False, "open": 0, "unowned": 0, "rows": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有重送义务」）"
        return out
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"板项读不出来（{type(exc).__name__}: {exc}）"
        return out
    out["checked"] = True
    for row in rows:
        key = str(row.get("input_key") or "")
        if not key.startswith(RESUBMIT_PREFIX):
            continue
        state = str(row.get("item_state") or "")
        if state == "done":
            continue
        owner = str(row.get("parent_task_id") or "")
        out["open"] += 1
        if not owner:
            out["unowned"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""), "key": key,
                            "owner": owner or "unknown", "item_state": state,
                            "role": str(row.get("role") or ""),
                            "detail": str(row.get("detail") or "")[:200]})
    out["reason"] = f"板上开着 {out['open']} 条重送义务"
    return out

# ------------------------------------------------------------------ 「签了但没人收录」（B 侧，I2 的同形）
#
# 现场：一份 `reports/f-proof-<号>.md` 上有 `secretary:F` 的成立签块，`b-proof-<号>.md`
# 也已落盘；而 `statements:<号>` 仍是 ek=heuristic / 正文=0 / reviewed=false —— 没人登记。
#
# 根因：B 只被派去收过文献，D 把签发当成终点、没派 B 收录。教学里其实有那条
# （`specs/d.py`：「② 那一行写进你的报告之后派 B 入库」）—— 缺的不是"教"，是义务：
# 签发之后没有任何东西把"这一份还没入库"摆到 B 面前。
#
# 所以这一档与 `v-resubmit@` 同形（同一个 `conductor.open_item`、同一种"凭证据收口"，
# 不靠 ack）：
#
# - 幂等键 `b-register@<命题号>@<被签正文的 sha>`：不带收件人后缀（同一命题的同一份
#   正文只该有一条义务；重判只刷签块，不重开这条）；
# - 触发：一份 `reports/{f,b}-proof-<号>.md` 上有成立的签块，而 `statements` 对应行
#   拿不出"正文 + reviewed=true"（签发那一刻由 `_vsigns_write_after_flip` 开；收工前
#   由 :func:`sweep_registrations` 补开 —— 漏开不许靠"下一次有人想起来"补）；
# - 收口只有一条：那一行出现正文 且 `reviewed=true`（逐份口径，一份证明不借另一份的
#   光）；另一条明确出口是"明确不收录并给理由"—— 它落在既有载体上：命题被标成
#   `abandoned` 且 `quote_reason` 是一条可解析的放弃标记（`statementabandon.parse_abandon`
#   的同一份判据，理由与时间缺一不可），届时这一项作废 `expired`；
# - 负责人：这一条只有"角色"（B），没有"事实上的收件人"。所以不猜：调用方给了台账号
#   就用；没给就认那一刻唯一在飞的 B 台账号（0 或 ≥2 ⇒ 不认）；一个都认不出时
#   `owner=""` 而照样开项（与 `v-resubmit` 的 `unowned` 不开项不同：那一条的负责人是
#   事实"谁送审"，猜不得；这一条的责任是角色 B，项本身必须存在 —— 它由 `board_view`
#   亮给主控去派，且父为空的项不挂在任何人的销号闸上）。

#: 「签了但没人收录」义务的幂等键前缀（缺陷 B）。与 `v-resubmit@` 分开。
REGISTER_PREFIX = "b-register@"

#: 这一条义务认的载体（`reports/f-proof-<号>.md` 或 `b-proof-<号>.md`）。
#: E 的穷举证据稿不在这一档（它走 `bits.proof` 那条通道）。
#: 从表派生（f-proof / b-proof 两族）。
REGISTRATION_CARRIERS: tuple[str, ...] = tuple(
    f"{_MFAM.MANUSCRIPT_DIR}/{_MFAM.prefix_of(name)}"
    for name in ("f-proof", "b-proof"))

#: 这一条义务的负责人角色（收口是 B 的动作）。
REGISTER_ROLE = "B"


def register_key(label: str, proof_sha: str) -> str:
    """「必须收录」义务的幂等键：`b-register@<命题号>@<被签正文的 sha>`。

    为什么键里是 sha：同一命题的两份证明各自独立（`#p2` 不许借 `#p1` 的光），而"这一份
    正文还没有被收录"是按正文说的 —— 换了 sha 就是另一份正文，该开新的义务。
    刻意不带收件人后缀（与 `resubmit_key` 同一条理由：带后缀会为每一次起跑各开一条）。
    """
    sid = str(label or "").split("#", 1)[0]
    return f"{REGISTER_PREFIX}{sid}@{str(proof_sha or '').strip()}"


def register_sha_of(key: str) -> str:
    """从这条义务的键里取回 `proof_sha256`（认不出 ⇒ 空串，不猜）。"""
    raw = str(key or "")
    if not raw.startswith(REGISTER_PREFIX):
        return ""
    rest = raw[len(REGISTER_PREFIX):]
    _sid, sep, sha = rest.partition("@")
    return sha if sep else ""


#: 「签落地 ⇒ 招呼 B」那一次召唤的幂等键前缀（SGN1，2026-11-17 真机 lp-ball-5）。
#:
#: 为什么要与板项的键分开（`b-register@` 只能有一个含义）：那条键回答"这一份签有没有
#: 一条待收编的义务"，这一条回答"为这一份签叫过谁"。两个问题分开之后，
#: 重放/重复投递落在召唤这一侧是"同键已有一行 ⇒ 不再召"（`_wake_registrar` 的第一档），
#: 而板项那一侧照旧"同键不重开"——两条幂等各自成立，不互相冒充。
REGISTER_WAKE_PREFIX = "b-awake@"


def register_wake_key(label: str, proof_sha: str) -> str:
    """召唤的幂等键：`b-awake@<命题号>@<被签正文的 sha>`（`<命题号>` 可带 `#pN` 时只取号）。"""
    sid = str(label or "").split("#", 1)[0]
    return f"{REGISTER_WAKE_PREFIX}{sid}@{str(proof_sha or '').strip()}"


def _register_items(conductor: Any) -> list[dict[str, Any]]:
    """板上所有「必须收录」义务（读不成 ⇒ 空列表，由调用方的话说清）。

    没有 conductor 时回空列表不是把"没做"折成"没有结果"：这一格是"板上有没有
    这一条"的纯读口，没有 conductor 就是"读不到板"。调用方（`ensure_registration` /
    `reconcile_registrations` / `registration_digest`）在调它之前已经单独判过
    `_conductor()` 是否为 None，并把那一档记成 `skipped` / `checked=False` + `reason`
    —— 那一句话落在那里，不在这里。
    """
    if conductor is None:  # 未接板 ⇒ 没有可读的板项；这是「没接上」，由调用方写 skipped + reason
        return []
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001 —— 读不成不是"没有义务"
        return []
    return [r for r in rows if str(r.get("input_key") or "").startswith(REGISTER_PREFIX)]


def _register_item_by_key(conductor: Any, key: str) -> dict[str, Any]:
    """板上有没有这一条（精确键：不带收件人后缀）。

    空字典的两档与 `_register_items` 同一条纪律：没有 conductor / 读不成都是"读不到板"，
    由调用方记 `skipped` + 原因；这一格不冒充"板上没有这一条"这个结论。
    """
    if conductor is None:  # 未接板 ⇒ 空字典是「读不到板」，调用方记 skipped + reason（不是"板上没有"）
        return {}
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001
        return {}
    for row in rows:
        if str(row.get("input_key") or "") == str(key or ""):
            return row
    return {}


def _label_parts(label: str) -> tuple[str, int]:
    """`<命题号>#p<号>` ⇒ `(命题号, 证明号)`；没有 `#p` 后缀 ⇒ 证明号 1。"""
    sid = str(label or "").split("#", 1)[0]
    tail = str(label or "").partition("#")[2]
    if tail.startswith("p") and tail[1:].isdigit() and int(tail[1:]) >= 1:
        return sid, int(tail[1:])
    return sid, 1


def _proof_body_present(row: Mapping[str, Any], proof_no: int) -> bool:
    """那一行里第 `proof_no` 份证明有没有正文（`proof_text` 与 `proofs[]` 两处都认）。"""
    if int(proof_no or 1) == 1 and str(row.get("proof_text") or "").strip():
        return True
    for one in (row.get("proofs") or ()):
        if not isinstance(one, Mapping):
            continue
        try:
            no = int(one.get("proof_no") or 1)
        except (TypeError, ValueError):
            no = 1
        if no != int(proof_no or 1):
            continue
        if str(one.get("proof_text") or "").strip():
            return True
    return False


def _proof_reviewed(row: Mapping[str, Any], proof_no: int) -> bool:
    """那一行的第 `proof_no` 份证明有没有被 reviewed（逐份表优先，`#p2` 不借 `#p1` 的光）。"""
    from . import evidencebits as _EB

    bits = dict(row.get("bits") or {})
    per = dict(_EB.reviewed_by_proof(bits) or {})
    if per:
        # `reviewed_by_proof` 把证明号归一成 int 键（`{1: True}`），而盘上是 JSON：
        # 两个键形都认一遍（手写行 / 别的写者的 `"1"` 不许读成"没签"）。
        want = int(proof_no or 1)
        if want in per:
            return bool(per[want])
        return bool(per.get(str(want)))
    return bool(bits.get("reviewed"))


def _manuscript_owner_row(*, store: Any, rel: str = "",
                          manuscript_id: str = "") -> dict[str, Any]:
    """按稿认这一份签该收到哪一行（「两个号段」里稿那一半的唯一落点）。

    为什么义务必须有这一半：SGN1（`a30844ef`）给"未在册的签"开的义务键是
    `b-register@<稿号>@<sha>` —— 写下的是稿号；而 2026-11-13 的裁定让稿号与命题号
    分家（`reports/f-proof-000002.md` ⇒ 稿号 000002，B 收录出来的行是 `stmt_id=000000`）。
    读侧若只按命题号 `by_id(stmt_id=稿号)` 找，那一行永远不存在 ⇒ 义务永远收不了口
    （RED11 §1③：同一行同一 sha，`000002#p1` 读成"没入库"、`000000#p1` 读成"已入库"）。

    判据只认收录记录那两处（`statements.manuscript_id` 与 `statements.manuscripts`），
    不走签行那一源（见 `manuscriptretire.statement_of_manuscript` 的 `sign_rows`）：
    这里问的是"这一份稿收进了哪一行"，而签行回答的是"谁签过它"。

    返回 `{"checked","found","stmt_id","why"}`；反查的唯一实现在
    `manuscriptretire.statement_of_manuscript`，本函数只收窄它的源、不另写一份扫描。
    """
    text = str(rel or "").strip().replace("\\", "/")
    mid = str(manuscript_id or "").strip()
    out: dict[str, Any] = {"checked": True, "found": False, "stmt_id": "", "why": ""}
    if not text and not mid:
        out["why"] = "没有稿路径 / 稿号 ⇒ 按稿认不了（不是「没有这一行」）"
        return out
    try:
        from . import manuscriptretire as _MR

        got = _MR.statement_of_manuscript(store, rel=text, manuscript_id=mid,
                                          sign_rows=False)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"，不折成"没有这一行"
        out.update(checked=False, why=f"按稿反查抛了（{type(exc).__name__}: {exc}）")
        return out
    out.update(checked=bool(got.get("checked")), found=bool(got.get("found")),
               stmt_id=str(got.get("stmt_id") or ""), why=str(got.get("why") or ""))
    return out


def registration_gap(*, store: Any, label: str, proof_sha: str = "",
                     manuscript: str = "") -> dict[str, Any]:
    """这一份签过的正文入库了没有（收口判据的唯一实现；纯读、不写任何东西）。

    判据（缺一不可）：`statements` 那一行拿得出这一份证明的正文，且那一份被
    `reviewed=true`（`bits.evidence.reviewed_by_proof` 的逐份表优先）。两条都齐 ⇒
    `gap=False`（义务已清）；否则 `gap=True`（义务还在）。

    ## 两个号段（2026-11-13 裁定之后必须分开对）

    `label` 里那个号可能是命题号（在册那两条签路开的键），也可能是稿号
    （未在册那一支与收工扫盘开的键：号从稿名读）。两个号段在真机上是分家的
    （稿 000002 ⇒ 命题 000000）⇒ 只按命题号找永远找不到那一行。这一格按三档对：

    ① 给了稿路径 ⇒ 按稿认（`_manuscript_owner_row`，收录记录那两源，最确定）；
    ② 没给路径 ⇒ 先按命题号 `by_id`（口径一），miss 再按稿号认稿；
    ③ 两档都命中而指向不同的行 ⇒ `matched_by="ambiguous"` + `gap=True`：
       判不了就不猜（拿别人的行判成"已收录"会把一条没办完的义务静默关掉）。

    读数里 `matched_by`（`statement_id` / `manuscript_id` / `ambiguous`）与
    `resolved_statement_id` 让"这一问走的是哪个号段"看得见。

    「明确不收录并给理由」那一档：`status="abandoned"` 且 `quote_reason` 是一条可解析的
    放弃标记（理由与时间都在）⇒ `abandoned=True, gap=False`（义务作废，不是"收录了"）。
    只写 `status=abandoned` 而没有可解析标记 ⇒ 不算明确不收录，`gap` 仍为真
    （与 `closing.statements_unsigned` 的 `abandoned_without_reason` 同一把尺）。

    三态：`checked=False` 只在 `statements` 读不出来 / 没给 store 时出现 ——
    它说的是"这一格没查成"，不许折成"已经收录了"。

    返回键：`checked` / `gap` / `abandoned` / `body` / `reviewed` / `status` /
    `statement_id` / `resolved_statement_id` / `matched_by` / `proof_no` /
    `manuscript` / `reviewed_why` / `reason`。
    """
    from . import statementabandon as _SA

    sid, no = _label_parts(label)
    out: dict[str, Any] = {"checked": False, "gap": None, "abandoned": False,
                           "body": False, "reviewed": False, "status": "",
                           "statement_id": sid, "resolved_statement_id": sid,
                           "matched_by": "",
                           "proof_no": no,
                           "manuscript": str(manuscript or ""),
                           "reviewed_why": "", "reason": ""}
    if store is None:
        out["reason"] = "没有 store ⇒ 收录状态查不了（不是「已经收录了」）"
        return out
    if not sid:
        out["reason"] = "这一条没有命题号 ⇒ 判不了要查哪一行（不猜）"
        return out
    # 按号定位走查口（口径一）：读不到 ≠ 没收录（三态在这一层才分得开）。
    by_id = SL.by_id(store, stmt_id=sid)
    if not by_id["checked"]:
        err = by_id.get("error") or {}
        out["reason"] = (f"`statements` 读不出来（{err.get('type', '?')}: "
                         f"{err.get('message', '?')}）⇒ 这一格没查成")
        return out
    rel = str(manuscript or "").strip().replace("\\", "/")
    claim = _manuscript_owner_row(store=store, rel=rel,
                                  manuscript_id="" if rel else sid)
    if not claim.get("checked"):
        out["reason"] = f"{claim.get('why') or '按稿认领没查成'} ⇒ 这一格没查成"
        return out
    row = by_id["row"] if by_id["found"] else {}
    matched = "statement_id" if by_id["found"] else ""
    if claim.get("found"):
        claimed = str(claim.get("stmt_id") or "")
        # 只有"只给了一个裸号"时才存在二义：号既可能是命题号、也可能是稿号。给了稿路径
        # 就没有二义（稿属于哪一行由收录记录回答，1:1）；那一档按稿认，不拿号去猜。
        if by_id["found"] and claimed and claimed != sid and not rel:
            out.update(checked=True, gap=True, matched_by="ambiguous",
                       resolved_statement_id="",
                       reason=(f"两个号段都命中：命题 {sid} 在册有一行，而"
                               f"{(f'稿 {rel}' if rel else f'稿号 {sid}')} 归命题 {claimed}"
                               " ⇒ 这一条义务该去哪一行收口判不了（不猜）：把义务键改成"
                               "命题号，或让这一份稿只归一条命题"))
            return out
        if claimed and claimed != sid:
            got = SL.by_id(store, stmt_id=claimed)
            if not got["checked"]:
                err = got.get("error") or {}
                out["reason"] = (f"`statements` 读不出来（{err.get('type', '?')}: "
                                 f"{err.get('message', '?')}）⇒ 这一格没查成")
                return out
            row = got["row"] if got["found"] else {}
        matched = "manuscript_id"
    elif not by_id["found"]:
        out.update(checked=True, gap=True, matched_by="", resolved_statement_id="",
                   reason=(f"`statements` 里没有命题 {sid} 那一行（按命题号查），"
                           f"{(f'稿 {rel}' if rel else f'稿号 {sid}')} 也没有收进任何一行"
                           " ⇒ 这一份签还没有被收录（先要 B 把它登记进册）"))
        return out
    out["checked"] = True
    out["matched_by"] = matched
    resolved = str(row.get("stmt_id") or "") or sid
    out["resolved_statement_id"] = resolved
    out["status"] = str(row.get("status") or "")
    if out["status"] == "abandoned":
        parsed = _SA.parse_abandon(row.get("quote_reason"))
        if parsed.get("checked"):
            out.update(gap=False, abandoned=True,
                       reason=(f"命题 {resolved} 已被明确放弃（{parsed.get('at')}："
                               f"{parsed.get('reason')}）⇒ 明确不收录，义务作废"))
            return out
        out.update(gap=True,
                   reason=(f"命题 {resolved} 写着 status=abandoned，而放弃标记读不出来"
                           f"（{parsed.get('why')}）⇒ 不算明确不收录（义务仍在）"))
        return out
    out["body"] = _proof_body_present(row, no)
    out["reviewed"] = _proof_reviewed(row, no)
    if out["body"] and out["reviewed"]:
        out.update(gap=False,
                   reason=(f"{resolved}#p{no} 已经入库（有正文、reviewed=true）⇒ 义务已清"
                           + (f"（按稿 {out['manuscript']} 认的）" if matched == "manuscript_id"
                              else "")))
        return out
    out["gap"] = True
    out["reviewed_why"] = ("正文在" if out["body"] else "正文是空的")
    out["reviewed_why"] += ("、reviewed=true" if out["reviewed"] else "、reviewed 不是 true")
    out["reason"] = (f"{resolved}#p{no} 还没入库（{out['reviewed_why']}）"
                     f"⇒ 这一份稿的签没有任何人登记过")
    return out


def _register_body(*, label: str, detail: Mapping[str, Any], manuscript: str,
                   at: str = "") -> tuple[str, str]:
    """这一条义务的一句话摘要 + 正文（上限 = `agent_loop.BOARD_DETAIL_CHARS`，480 字）。

    为什么上限不在这里另拍一个数：写入侧若自己截断（例如 `body[:400]`），完整正文里
    靠后的「明确放弃 + 理由与时间」会在进板之前被切掉。渲染层再怎么调都读不回来 ——
    写入侧定"存多少"，渲染侧定"念多少"，念的那个不许小于存的；两层共用一个常量，
    这条缝才在结构上不存在。
    """
    from .agent_loop import BOARD_DETAIL_CHARS

    sid = str(detail.get("statement_id") or label.split("#", 1)[0])
    # `proof_no` 在 V 签侧退役：这一段只用 `label` 里老行可能带的 `#pN` 做措辞兼容
    # （新行没有这一格 ⇒ `_label_parts` 按 canonical 1），明细字典里不再单独带一格。
    _, no = _label_parts(label)
    sha = str(detail.get("proof_sha256") or "")
    path = str(manuscript or detail.get("manuscript") or "")
    summary = f"待收录：{sid}#p{no}（稿上已有成立的 V 签，`statements` 里还没入库）"
    body = (
        f"这是一条必须收录的义务，不是通知：`{path or '（稿路径没读到）'}` 上有成立的 V 签"
        f"（命题 {sid}#p{no}，被签正文 sha {sha or '（没读到）'}，签于 {at or '（时刻没读到）'}），"
        f"而 `statements` 那一行仍然{detail.get('reviewed_why') or '没有正文 / 未 reviewed'}。\n"
        "收口条件只有一条：那一行出现正文 且 reviewed=true（逐份口径，`#p2` 不借 `#p1` 的光）"
        " —— 届时这一项由框架自动收口（completed），不靠 ack；退回一句「知道了」不会让它消失。\n"
        "两条路：① 从稿上把正文收进 `statements`（B 的 `own.register_statement`；稿上的签块会被"
        "认成第 3 位）；② 确实不收录就明确放弃原命题（`status=abandoned` + 可解析的放弃标记，"
        "理由与时间缺一不可）—— 放弃时这一项同时作废。"
    )
    return summary, body[:int(BOARD_DETAIL_CHARS)]


def _live_role_task(store: Any, role: str) -> dict[str, Any]:
    """那一刻唯一在飞的该角色台账号（0 或 ≥2 ⇒ 不认，不猜）。

    与 `resolve_recipient` 的"唯一才认"同一条纪律：这里问的是"现在有没有一个确定的 B
    可以接这条义务"，两趟以上在飞时"哪一趟接"不可判 —— 那时宁可记 `owner=""`，也不拿
    "谁醒着"当负责人。
    """
    out: dict[str, Any] = {"checked": False, "task_id": "", "candidates": [], "why": ""}
    if store is None:
        out["why"] = "没有 store ⇒ 读不到台账号"
        return out
    try:
        from .conductor import UNFINISHED_STATUSES

        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
        return out
    alive = [r for r in rows
             if str(r.get("role") or "") == str(role)
             and not str(r.get("kind") or "")
             and str(r.get("status") or "") in UNFINISHED_STATUSES]
    out["checked"] = True
    out["candidates"] = [str(r.get("task_id") or "") for r in alive]
    if len(alive) == 1:
        out["task_id"] = str(alive[0].get("task_id") or "")
        out["why"] = f"那一刻只有一趟 {role} 在飞（{out['task_id']}）"
        return out
    out["why"] = (f"那一刻有 {len(alive)} 趟 {role} 在飞（{out['candidates']}）"
                  "⇒ 负责人不可判（不猜）" if alive else
                  f"那一刻没有 {role} 在飞 ⇒ 负责人不可判（不猜）")
    return out


def _registrar_now(store: Any, role: str = REGISTER_ROLE) -> dict[str, Any]:
    """这一刻这条义务该送到哪一趟台账号（"送信地址"，不是"负责人归属"）。

    与 :func:`_live_role_task` 的差别只有一条，而那条就是 SGN1 的真机现场：
    0 趟在飞时它还要往前找一步 —— 找那一趟终态但未销号的该角色台账号（"静默"）。
    真机 `projects/lp-ball-5` 的读数（2026-11-17 17:11）：157 行 tasks、
    `role="B"` 的台账号 0 趟、`b-register@` 板项 0 条、`statements` 0 行，
    而 `reports/f-proof-000002/3.md` 上两枚签已经落地 —— 义务既没开、也没人去干。

    为什么"静默"这一档必须找：`conductor.open_item` 的唤醒判定（`_ensure_consumer`）
    对"终态且未销号"的收件人正是同号继续（业主 2026-10-29「静默的唤醒就是接到
    消息被唤醒」）。改前这一格只认"在飞"⇒ 静默的 B 被读成"没有负责人"⇒ 板项开成
    无主的（`parent_task_id=None`）⇒ 唯一叫得醒的那一趟反而没被叫
    （"只写台账、不叫醒"的同族）。

    ≥2 趟在飞时取最近开始的那一趟，而不是像 `_live_role_task` 那样判"不可判"：
    那一条判的是归属（写进回执给人看的"谁接的"），宁可 unknown；这一格判的是
    送信地址（一条 notice 落进谁名下）—— 落进哪一趟都不改变义务的内容与收口
    条件，而"不挑"的代价是这条义务永远没人叫醒。

    返回 `{"checked","task_id","candidates","running","why"}`；`task_id=""` = 这一刻
    确实没有一个可接的 B（由调用方决定要不要新召一趟）。
    """
    out: dict[str, Any] = {"checked": False, "task_id": "", "candidates": [],
                           "running": False, "why": ""}
    if store is None:
        out["why"] = "没有 store ⇒ 读不到台账号"
        return out
    try:
        from .conductor import UNFINISHED_STATUSES

        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不成不折成"没有人可叫"
        out["why"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
        return out
    out["checked"] = True
    mine = [r for r in rows
            if str(r.get("role") or "") == str(role) and not str(r.get("kind") or "")]
    alive = [r for r in mine if str(r.get("status") or "") in UNFINISHED_STATUSES]
    quiet = [r for r in mine if str(r.get("status") or "") not in UNFINISHED_STATUSES]
    out["candidates"] = [str(r.get("task_id") or "") for r in mine]
    cond = _conductor(store)
    if cond is None:
        out["why"] = "这一趟没有接主控（`cached_conductor` 是空）⇒ 叫不了人"
        return out
    for running, pool in ((True, alive), (False, quiet)):
        # 从最近开始的那一趟往前找：销号名单读不全 / 已销号 ⇒ 不拿它当收件人
        # （fail-closed：`_ensure_consumer` 对这两种也会拒绝唤醒，先在这里筛掉，
        # 免得板项挂到一个叫不醒的号上）。
        for row in sorted(pool, key=lambda r: str(r.get("started_at") or ""), reverse=True):
            tid = str(row.get("task_id") or "")
            try:
                verdict = cond.retired_verdict(tid, parent=str(row.get("parent_task_id") or ""))
            except Exception:  # noqa: BLE001 —— 读不出来就不认它（fail-closed）
                verdict = "unknown"
            if verdict != "live":
                out["why"] = (f"{tid} 的销号名单读的是 {verdict} ⇒ 不拿它当收件人"
                              "（已销号彻底没有了；读不全就交人看）")
                continue
            out.update(task_id=tid, running=running,
                       why=(f"那一刻有 {len(alive)} 趟 {role} 在飞 ⇒ 送最近开始的那一趟"
                            f"（{tid}）" if running else
                            f"没有 {role} 在飞，但有 {len(quiet)} 趟静默未销号 ⇒ "
                            f"送最近开始的那一趟（{tid}，同号继续）"))
            return out
    out["why"] = (f"那一刻有 {len(alive)} 趟 {role} 在飞、{len(quiet)} 趟静默，"
                  "但一个都不可叫（已销号 / 销号名单读不全）" if mine else
                  f"那一刻没有 {role} 的台账号（一趟都没起过）⇒ 只能新召一趟")
    return out


def _wake_row(store: Any, key: str) -> dict[str, Any]:
    """板上有没有这个键的召唤行（纯读；读不成 ⇒ 空字典，由调用方说"没读到"）。"""
    if store is None:  # 空输入得空输出：这一格是"有没有那一行"的纯读口，没有 store 就是
        # "读不到台账"；调用方（`_wake_registrar` / `registration_digest`）把那一档记成
        # `skipped` 或 `problems` + 原因，不在这里冒充"没有这一行"这个结论。
        return {}
    try:
        for row in store.rows("tasks"):
            if str(row.get("input_key") or "") == str(key or ""):
                return dict(row)
    except Exception:  # noqa: BLE001 —— 读不成不是"没有那一行"
        return {}
    return {}


def _executor_can_run(conductor: Any, role: str) -> tuple[bool, str]:
    """这一趟的执行侧跑得了"只派活"（空动作）的召唤吗。

    判据是一条既有事实，不是猜测：空动作的召唤走模型驱动那一层
    （`agent_loop.LlmBackend.call`：`loops` 里没登记 `(角色, "")` 也会现造一个循环，
    见它的 docstring「空动作为什么走循环」）；而确定性后端（`LocalBackend`）按
    `(角色, 动作)` 找 handler，空动作没有 handler ⇒ 它连跑都跑不起来。

    为什么要这一格：召了也跑不起来的角色，唯一的下场是台账里多一行 `failed`
    —— 那正是"看起来做了"的假动作。这一档如实记 `skipped` + 原因，板项照旧开在板上。
    """
    backend = getattr(conductor, "backend", None)
    if backend is None:
        return False, "这一趟没有执行侧（`conductor.backend` 是空）"
    if getattr(backend, "loops", None) is not None:
        return True, ""
    return False, ("这一趟的执行侧按 (角色,动作) 分派（`LocalBackend`），空动作没有 handler "
                   "⇒ 召唤跑不起来")


def _registrar_task_text(*, key: str, label: str, manuscript: str, sha: str,
                         at: str = "") -> str:
    """召唤 B 时那句话（派活不点动作 ⇒ 这句就是它这一趟知道的一切）。"""
    sid = str(label or "").split("#", 1)[0]
    return (
        f"收编这一签（义务 {REGISTER_PREFIX}{sid}@{sha}）：`{manuscript or '（没读到稿路径）'}` "
        f"上已经有成立的 V 签（{label}，正文 sha {sha[:12]}…，签于 {at or '（时刻没读到）'}），"
        f"而 `statements` 里 {sid} 那一行还没有正文 / 未 reviewed。"
        "请把它收进 `statements`（B 的 `own.register_statement`；稿名里的号就是命题号），"
        "并按正文 sha 认领 V 签（逐份口径，`#p2` 不借 `#p1` 的光）；"
        "收口条件是那一行出现正文且 reviewed=true —— 届时板项自动收口，不需要 ack。"
    )


def _wake_registrar(*, store: Any, conductor: Any, key: str, label: str,
                    manuscript: str = "", sha: str = "", at: str = "",
                    opened_under: str = "") -> dict[str, Any]:
    """「签落地 ⇒ 招呼 B」这一步落成盘上的事实（幂等，永不抛）。

    业主 2026-11-17（SGN1，真机 `projects/lp-ball-5`）：签落地那一刻必须有一条
    真能把 B 叫醒的动作。改前只有一条板项，而板项在"没有 B 台账号"时是无主的
    （`parent_task_id=None`）—— 无主的项不落进任何人的收件箱，`_ensure_consumer`
    的判定是"没有收件人（公共频道/广播）⇒ 没有要跑的人" ⇒ 义务写在板上，B 一次也没醒。
    真机读数：3 枚签落地、`b-register@` 0 条、B 台账号 0 趟。

    四档（每档都是读数，不折平）：

    - `already`：这个键已经有召唤行 ⇒ 不重复召唤（重放 / 重复投递落在这一档）；
    - `running`：那一刻 B 在飞 ⇒ 板项落进它名下，它下一拍自己读到（不新召）；
    - `woken` / `attached`：那一刻 B 静默未销号 ⇒ 同号继续（`wake_on_lifeline`：
      那是既有唯一带"已销号 / 在飞"双闸的唤醒口）；没接执行侧时停在 `attached`；
    - `summoned`：一个 B 都没有 ⇒ 新召一趟（`summon_begin` + `start_summon`：
      与 `tools/conductor_tools.py::conductor_summon` 同一形态，`by="M"` 是那一条
      边（`ALLOWED_EDGES["M"]` 含 B），父为空（这是框架为主控补的一趟，不挂在哪个
      在飞的父上）；`task_id` 与 `at` 就是报告里那句"已召唤 B（任务 id 与时刻）"；
    - `skipped` / `refused` / `error`：叫不动，逐档说清为什么（板项仍在板上）。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "task_id": "", "at": "",
                           "key": str(key or ""), "reason": ""}
    if conductor is None:
        out.update(state="skipped",
                   reason="这一趟没有 conductor ⇒ 叫不了人（板项照旧开在板上）")
        return out
    out["checked"] = True
    # ---- ① 这个键已经叫过一次 ⇒ 不重复召唤（幂等的落点） -------------------
    seen = _wake_row(store, key)
    if seen:
        out.update(state="already", task_id=str(seen.get("task_id") or ""),
                   at=str(seen.get("started_at") or ""),
                   reason=(f"同键（{key}）的召唤行已在台账上（{seen.get('task_id')}，"
                           f"{seen.get('started_at')}）⇒ 不重复召唤"))
        return out
    # ---- ② 有可接的 B ⇒ 不新召（在飞 / 静默同号继续） -----------------------
    who = _registrar_now(store, REGISTER_ROLE)
    tid = str(who.get("task_id") or "")
    if tid:
        if tid == str(opened_under or ""):
            # 板项刚刚就开在它名下 ⇒ `open_item` 的 `_ensure_consumer` 已经走过一遍
            # 唤醒判定（信先在收件箱里、再叫它 —— 顺序反了它会读不到这一条）。
            # 这里只把那一句原话接上；"叫没叫"与"叫得成不成"必须分得开。
            consumer = dict(getattr(conductor, "last_consumer_reading", {}) or {})
            started = bool(consumer.get("started"))
            out.update(state=("woken" if started
                              else ("running" if who.get("running") else "attached")),
                       task_id=tid, at=str(at or ""),
                       reason=(f"板项开在 {tid} 名下（{who.get('why')}）；"
                               f"唤醒判定：{consumer.get('reason') or '（没有读数）'}"))
            return out
        woke: dict[str, Any] = {}
        if not who.get("running"):
            try:
                woke = dict(conductor.wake_on_lifeline(tid) or {})
            except Exception as exc:  # noqa: BLE001 —— 叫醒失败要如实回
                woke = {"started": False,
                        "reason": f"叫醒那一笔抛了（{type(exc).__name__}: {exc}）"}
        out.update(state=("woken" if woke.get("started")
                          else ("running" if who.get("running") else "attached")),
                   task_id=tid, at=str(at or ""),
                   reason=(str(woke.get("reason") or "")
                           or str(who.get("why") or "")))
        return out
    # ---- ③ 一个 B 都没有 ⇒ 新召一趟（这一条就是"SGN1 的修法"） -------------
    can, why_not = _executor_can_run(conductor, REGISTER_ROLE)
    if not can:
        out.update(state="skipped",
                   reason=(f"{why_not} ⇒ 这一键没有召唤（板项仍在板上，由主控/收工读数看见）；"
                           f"现场：{who.get('why')}"))
        return out
    text = _registrar_task_text(key=key, label=label, manuscript=manuscript,
                                sha=sha, at=at)
    try:
        from . import schema as _S

        started = conductor.summon_begin(
            REGISTER_ROLE, "", {"task": text}, by=_S.CONDUCTOR_ROLE,
            # 父为空：这一趟不挂在任何在飞的父上（`capabilities.audit_task_ledger`
            # 要求无父行 depth=1，`_depth_of(None)` 给的正是 1）。
            parent_task_id=None, input_key=str(key), roster={"task": text})
    except Exception as exc:  # noqa: BLE001 —— 召唤抛了不许带走这一签
        out.update(state="error",
                   reason=f"召唤那一笔抛了（{type(exc).__name__}: {exc}）")
        return out
    refusal = getattr(started, "refusal", None)
    if refusal is not None:
        out.update(state="refused", task_id="",
                   reason=(f"召唤被拒（{getattr(refusal, 'status', '')}/"
                           f"{getattr(refusal, 'refusal_reason', '')}）："
                           f"{getattr(refusal, 'detail', '') or '没有理由'}"))
        return out
    try:
        conductor.start_summon(started)      # 非阻塞：不占 V 这一拍
    except Exception as exc:  # noqa: BLE001 —— 前半已经在台账上了，照实报
        out.update(state="summoned", task_id=str(getattr(started, "task_id", "") or ""),
                   at=str(_wake_row(store, key).get("started_at") or ""),
                   reason=(f"台账那一行已经派出去了（{getattr(started, 'task_id', '')}），"
                           f"但执行侧没起来（{type(exc).__name__}: {exc}）"))
        return out
    row = _wake_row(store, key)
    out.update(state="summoned", task_id=str(getattr(started, "task_id", "") or ""),
               at=str(row.get("started_at") or ""),
               reason=(f"已召唤 B {getattr(started, 'task_id', '')}"
                       f"（{row.get('started_at') or '时刻没读到'}；键 {key}）"))
    return out


def ensure_registration(*, store: Any, root: str | Path, label: str, proof_sha: str,
                        manuscript: str = "", owner: str = "", called_by: str = "V",
                        depth: int = 1, at: str = "", skip_gap: bool = False,
                        wake: bool = False) -> dict[str, Any]:
    """开一条「必须收录」义务项（幂等；已清掉的不开，已收口的收口）。

    返回 `{"checked","state","key","item_id","owner","owner_known","reason","problems",
    "wake"}`，`state` 取：`opened` / `existing` / `closed`（板上那条已经 done）/ `cleared`
    （盘上已经入库 ⇒ 义务本来就没了，顺手把板上那条按证据收口）/ `expired`（命题已被明确
    放弃）/ `skipped`（没有 conductor / 查不成 / 做不出幂等键）/ `error`（开项抛了）。

    `owner`：给了就用；没给就认那一刻的 B 台账号；一个都认不出 ⇒ `owner=""` 而照样开项
    （`owner_known=False`，由 `registration_digest` 的 `unowned` 数出来，
    `board_view` 把这一条亮给主控去派）。

    `wake=True`（签落地那一刻，SGN1）：除了开项，还要有一条真能把 B 叫醒的动作
    （`:func:`_wake_registrar` 的四档读数落在 `out["wake"]`）。为什么必须：改前只有一个
    板项，而"没有 B 台账号"时它是无主的 —— 无主的项不进任何人的收件箱，
    `_ensure_consumer` 判"没有收件人 ⇒ 没有要跑的人"，于是 3 枚签落地、B 一次没醒
    （真机 `projects/lp-ball-5`，2026-11-17）。这一档在"一个 B 都没有"时新召一趟
    （`summon_begin` + `start_summon`），并把召唤任务 id 与时刻记进读数。

    `skip_gap=True`（V 的签后义务）：不读 `statements` 判断"是不是已经收录"。
    义务的存在与它是否已满足是两件事：V 只对手稿负责 ⇒ 签落成后无条件开；"满足了没有"
    由 B 收录时消账、收工时 `sweep_registrations` 收口。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "owner": str(owner or ""), "owner_known": False,
                           "owner_why": "", "reason": "", "problems": [], "wake": {}}
    sid = _label_parts(label)[0]
    sha = str(proof_sha or "").strip()
    if not sid or not sha:
        out.update(state="skipped",
                   reason="这一条没有命题号 / 没有被签正文的 sha ⇒ 做不出幂等键（不猜）")
        return out
    key = register_key(label, sha)
    out["key"] = key
    if skip_gap:
        # V 只对手稿负责：开义务不看册。三态照旧（`checked=True` + `gap=True`），
        # 但理由逐字说清"这是一条无条件义务，是否已满足不在这里判"。
        gap = {"checked": True, "gap": True, "abandoned": False,
               "reason": ("签后无条件开义务（V 不读 statements）；"
                          "是否已经收录由 B 收录时消账 / 收工扫盘判")}
    else:
        gap = registration_gap(store=store, label=label, proof_sha=sha,
                               manuscript=manuscript)
    if not gap.get("checked"):
        out.update(state="skipped",
                   reason=(f"{gap.get('reason')}；不拿'读不出来'当'还没收录'去开一条待办"))
        out["problems"].append(str(gap.get("reason") or "收录状态读不成"))
        return out
    conductor = _conductor(store)
    if not gap.get("gap"):
        row = _register_item_by_key(conductor, key)
        if row and conductor is not None and str(row.get("item_state") or "") != "done":
            close = "expired" if gap.get("abandoned") else "completed"
            _state, why = conductor.close_item_by_evidence(
                str(row.get("task_id") or ""), close=close,
                why=f"义务已清：{gap.get('reason')}")
            if why:
                out["problems"].append(why)
            out.update(checked=True, item_id=str(row.get("task_id") or ""),
                       state=("expired" if gap.get("abandoned") else "cleared"),
                       reason=str(gap.get("reason") or "义务已清"))
            return out
        out.update(checked=True, item_id=str((row or {}).get("task_id") or ""),
                   state="cleared", reason=str(gap.get("reason") or "义务已清"))
        return out
    row = _register_item_by_key(conductor, key)
    if row:
        state = str(row.get("item_state") or "")
        out.update(checked=True, item_id=str(row.get("task_id") or ""),
                   owner=str(row.get("parent_task_id") or ""),
                   owner_known=bool(row.get("parent_task_id")),
                   state=("closed" if state == "done" else "existing"),
                   reason=(f"同键的板项已存在（{row.get('task_id')}，item_state={state}）"
                           "⇒ 不重开"))
        if wake:
            # 重放 / 重复投递落在这里：板项不重开；召唤那一侧按 `b-awake@` 键判
            # （`_wake_registrar` 的第一档：同键已有召唤行 ⇒ 不再召）。
            out["wake"] = _wake_registrar(
                store=store, conductor=conductor, key=register_wake_key(label, sha),
                label=label, manuscript=str(manuscript or ""), sha=sha, at=at)
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason=("这一趟没有 conductor ⇒ 板项开不了（义务不落盘 = 没人会看到；"
                           "不是「已经收录了」）"))
        return out
    if not str(out["owner"] or "").strip():
        # 两把尺：`wake=True` 用"送信地址"那一把（在飞 → 最近一趟；否则静默那一趟），
        # 否则用原来那一条（唯一在飞才认）。见 `_registrar_now` 与 `_live_role_task`。
        who = _registrar_now(store, REGISTER_ROLE) if wake else _live_role_task(store, REGISTER_ROLE)
        out["owner"] = str(who.get("task_id") or "")
        out["owner_known"] = bool(out["owner"])
        # 「负责人记 unknown」是读数、不是失败：它不进 `problems`（那会让收工读数把
        # "没人在飞"报成"这一条没办成"），由 `registration_digest` 的 `unowned` 数出来。
        out["owner_why"] = str(who.get("why") or "")
    else:
        out["owner_known"] = True
        out["owner_why"] = "调用方点名了负责人"
    if wake and not str(out["owner"] or "").strip():
        # 一个可接的 B 都没有 ⇒ 新召一趟（这一趟的 `task_id` 就是它的负责人）。
        # 有 B 可接时不在这里叫：顺序必须是"信先进收件箱、再叫它" —— 板项落进
        # 它名下那一刻由 `open_item` 的 `_ensure_consumer` 叫（静默 ⇒ 同号继续）。
        wake_now = _wake_registrar(
            store=store, conductor=conductor, key=register_wake_key(label, sha),
            label=label, manuscript=str(manuscript or ""), sha=sha, at=at)
        out["wake"] = wake_now
        if wake_now.get("state") == "summoned" and wake_now.get("task_id"):
            out["owner"] = str(wake_now["task_id"])
            out["owner_known"] = True
            out["owner_why"] = "为这一签新召了一趟 B（`b-awake@` 那一行）"
    # 深度：有负责人 ⇒ 它那一行 depth + 1（`capabilities.audit_task_ledger` 的
    # `task_depth_discontinuous` 按这条链核）；没有负责人 ⇒ 无父的项必须是 1。
    if out["owner"]:
        item_depth = max(1, int(_task_row(store, out["owner"]).get("depth") or 1)) + 1
    else:
        item_depth = 1
    summary, body = _register_body(
        label=label,
        detail={"statement_id": sid, "proof_sha256": sha,
                "manuscript": str(manuscript or ""),
                "reviewed_why": str(gap.get("reviewed_why") or "")},
        manuscript=manuscript, at=at)
    try:
        item_id = conductor.open_item(
            kind="notice", role=REGISTER_ROLE, expects="work", action="notice",
            summary=summary, called_by=str(called_by or "V"),
            parent_task_id=(str(out["owner"]) or None),
            depth=item_depth, input_key=key)
        conductor.set_item_detail(item_id, body)
    except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走这一签
        out.update(state="error", reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
        return out
    out.update(checked=True, state="opened", item_id=item_id,
               reason=(f"新开「必须收录」义务 {item_id}"
                       + (f"（负责人 {out['owner']}）" if out["owner"]
                          else "（负责人记 unknown，由主控派人）")))
    if wake and not out["wake"]:
        # 板项刚刚开在有一趟 B 的名下 ⇒ 那一下就是既有唤醒口
        # （`open_item` → `_ensure_consumer`：静默 ⇒ 同号继续；在跑 ⇒ 下一拍自己读）。
        out["wake"] = _wake_registrar(
            store=store, conductor=conductor, key=register_wake_key(label, sha),
            label=label, manuscript=str(manuscript or ""), sha=sha, at=at,
            opened_under=str(out["owner"] or ""))
    return out


def sweep_registrations(*, store: Any, root: str | Path, limit: int = 50,
                        at: str = "") -> dict[str, Any]:
    """扫一遍 `reports/{f,b}-proof-*.md`：带成立的签而没入库 ⇒ 逐份开义务（幂等）。

    为什么还要扫盘（签发那一刻已经会开一条）：义务不能只依赖"签发那一路跑到了"——
    病根正是"没有任何东西把这件事摆到 B 面前"。这一趟是收工前的看门：谁漏开、
    谁在签发之后才改的稿，都在这里被数一遍。判据只认手上这份稿：`manuscript_sign_standing`
    说 signed 才算（负判 / stale / 没块 ⇒ 不是这一档的事）。
    """
    out: dict[str, Any] = {"checked": False, "scanned": 0, "signed": 0,
                           "opened": [], "existing": [], "closed": [],
                           "cleared": [], "expired": [], "skipped": [],
                           "problems": [], "reason": ""}
    from . import verifications as _VR
    from . import vsigns as _VS

    if store is None:
        out["reason"] = "没有 store ⇒ 这一格没查成（不是「没有欠收录的稿」）"
        return out
    reports = Path(str(root or "")) / "reports"
    files: list[Path] = []
    for prefix in REGISTRATION_CARRIERS:
        name = prefix.rsplit("/", 1)[-1]
        if not reports.is_dir():
            continue
        files.extend(sorted(reports.glob(f"{name}*.md")))
    out["checked"] = True
    for path in files:
        if len(out["opened"]) + len(out["existing"]) >= max(1, int(limit)):
            out["skipped"].append({"path": _VS.rel(path, root),
                                   "why": f"到了一次扫盘的上限 {int(limit)} 条"})
            break
        rel = _VS.rel(path, root)
        out["scanned"] += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out["problems"].append(f"{rel}：读不出来（{type(exc).__name__}: {exc}）")
            continue
        block = _VS.manuscript_sign_standing(text, manuscript_path=rel)
        if str(block.get("state") or "") != "signed":
            out["skipped"].append({"path": rel,
                                   "why": f"这一份稿不是「签着」那一档（{block.get('why')}）"})
            continue
        sid = _VS.manuscript_id_of(rel)
        if not sid:
            out["skipped"].append({"path": rel, "why": "稿名认不出裸稿号 ⇒ 不猜命题号"})
            continue
        # `-v2` 一类历史档：`manuscript_id_of` 仍读得出号（设计 3.3.2 的兼容读法），
        # 但它不可收录（`tier=legacy`）⇒ 不许给它开「签了但没人收录」的义务。
        if _MFAM.classify_manuscript(rel).get("tier") != _MFAM.TIER_FAMILY:
            out["skipped"].append({"path": rel, "why": "历史档（legacy）⇒ 不可收录"})
            continue
        out["signed"] += 1
        sha = str(block.get("proof_sha256") or "")
        label = f"{sid}#p{_VR.as_proof_no(_VS.manuscript_proof_no_of(rel)) or 1}"
        got = ensure_registration(store=store, root=root, label=label, proof_sha=sha,
                                  manuscript=rel, called_by="obligations.sweep",
                                  at=str(block.get("at") or at or ""))
        out["problems"].extend(str(x) for x in (got.get("problems") or []))
        state = str(got.get("state") or "")
        if state == "opened":
            out["opened"].append(str(got.get("item_id") or ""))
        elif state == "existing":
            out["existing"].append(str(got.get("item_id") or ""))
        elif state in ("closed", "cleared"):
            out[state].append(str(got.get("item_id") or ""))
        elif state == "expired":
            out["expired"].append(str(got.get("item_id") or ""))
        else:
            out["skipped"].append({"path": rel,
                                  "why": str(got.get("reason") or "这一份没开成")})
    out["reason"] = (f"扫到 {out['scanned']} 份证明稿（签着的 {out['signed']} 份）："
                     f"新开 {len(out['opened'])} 条、已在板上 {len(out['existing'])} 条、"
                     f"顺手收口 {len(out['closed']) + len(out['cleared'])} 条、"
                     f"作废 {len(out['expired'])} 条、跳过 {len(out['skipped'])} 条"
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out


def settle_registration(*, store: Any, root: str | Path, stmt_id: str,
                        manuscript: str = "", at: str = "") -> dict[str, Any]:
    """B 收录落成那一刻把「必须收录」义务消账（永不抛；键从稿号认到命题号）。

    ## 为什么需要这一格：`ensure_registration` 的 docstring 许了半句没实现的承诺

    那一段逐字写着「满足了没有」由 B 收录时消账、收工时 `sweep_registrations` 收口。
    后半句有落点，前半句此前没有：`close_item_by_evidence` 只在 `obligations` 内被调
    （`ensure_registration` / `reconcile_registrations` / `reconcile_resubmits`），
    而 `reconcile` 的唯一调用点是 `conductor.closing` 那一个工具。RED11 的彩排里 M 的脚本
    是「派 B → 销 B1 → final」，没有收工对账那一笔 ⇒ 义务停在 `seen` ⇒ `retire_child`
    受控拒（"名下还有 1 条未消的板项"）⇒ final 连拒 3 拍（`final_refused`）⇒ CLI rc=5、
    多打 3 次真调用（16 → 19）。收口必须发生在收录那一刻，不能等谁想起来做对账。

    ## 键的迁移落在读数上（不是改写板项的身份列）

    未在册那一支的键带稿号；收录之后这一行有了命题号。这一格按"这一份稿归哪一行"
    （`_manuscript_owner_row` / `by_id`）认出那条义务、收口成 `completed`，并把
    `b-register@<稿号>@<sha>` → `b-register@<命题号>@<sha>` 逐字写进收口读数
    （`adopted_key`）与事件 note。板项的 `input_key` 不就地改写：它是"这一条义务被谁、
    在什么时候开出来的"的证据，而写侧每次重放都会按稿名重算同一个键 —— 改了它，
    「同键不重开」就破了（下一次签发会为同一份稿再开一条）。读侧
    （`registration_gap`）两个号段认出的是同一条义务，所以下游读哪一边都是同一个结论。

    ## 只认这一份稿 / 这一条命题的义务（不拿"板上任何一条"去试）

    一行的键是 `<号>@<sha>`，那个号可能是命题号（在册那两路）也可能是稿号（未在册 / 扫盘）。
    这一格只碰两种：`号 == 这一笔拿到的命题号`，或 `号 == 这一份稿的稿号`。别的义务
    （别的稿 / 别的命题）原样留在板上 —— 那是 `left` 之外的事，不在这里判。

    三态：`checked=False` 只在"没有 conductor / 没给命题号"时出现（不是"没有要收口的"）。
    """
    out: dict[str, Any] = {"checked": False, "settled": [], "left": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有要收口的义务」）"
        return out
    sid = str(stmt_id or "").strip()
    if not sid:
        out["reason"] = "这一笔没有命题号 ⇒ 收不了口（不是「没有义务」）"
        return out
    out["checked"] = True
    rel = str(manuscript or "").strip().replace("\\", "/")
    mid = ""
    if rel:
        from . import vsigns as _VS

        mid = str(_VS.manuscript_id_of(rel) or "")
    for row in _register_items(conductor):
        key = str(row.get("input_key") or "")
        if str(row.get("item_state") or "") == "done":
            continue
        num = key[len(REGISTER_PREFIX):].partition("@")[0]
        sha = register_sha_of(key)
        if num == sid:
            gap = registration_gap(store=store, label=f"{sid}#p1", proof_sha=sha)
        elif mid and num == mid:
            gap = registration_gap(store=store, label=f"{mid}#p1", proof_sha=sha,
                                   manuscript=rel)
        else:
            continue  # 不是这一份稿 / 这一条命题的义务：原样留在板上
        if not gap.get("checked") or gap.get("gap") or \
                str(gap.get("resolved_statement_id") or "") != sid:
            out["left"].append({"key": key, "item_id": str(row.get("task_id") or ""),
                                "why": str(gap.get("reason") or "义务还在")})
            continue
        close = "expired" if gap.get("abandoned") else "completed"
        adopted = register_key(f"{sid}#p1", sha)
        _state, problem = conductor.close_item_by_evidence(
            str(row.get("task_id") or ""), close=close,
            why=(f"收录落成：{gap.get('reason')}"
                 + (f"；键 {key} → {adopted}（迁到收录后的命题号）"
                    if key != adopted else "")))
        if problem:
            out["problems"].append(f"{row.get('task_id')}：{problem}")
            continue
        out["settled"].append({"item_id": str(row.get("task_id") or ""), "key": key,
                               "adopted_key": adopted, "close": close,
                               "matched_by": str(gap.get("matched_by") or ""),
                               "why": str(gap.get("reason") or "")})
    out["reason"] = (f"收录落成：收口 {len(out['settled'])} 条"
                     + (f"、仍开着 {len(out['left'])} 条" if out["left"] else "")
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out


def reconcile_registrations(*, store: Any, root: str | Path) -> dict[str, Any]:
    """板上开着的「必须收录」义务与盘上的事实对一次账（收工前的收敛点）。

    两条来源要知道它：签发那一刻（`_vsigns_write_after_flip`）与收工对账
    （`reconcile` → `sweep_registrations`）。而"收录完了"这件事发生在 B 的写口里 ——
    那一层不认识板项。所以这里按盘上的事实收口：`statements` 那一行已经有正文 +
    reviewed ⇒ `completed`；命题被明确放弃 ⇒ `expired`。都不靠 ack。

    幂等：已经收口的项不在 `_register_items` 的未终态里，重跑是零写入。三态：板项读不出来
    / `statements` 读不出来 ⇒ `checked=False`（不是"没有要收口的"）。
    """
    out: dict[str, Any] = {"checked": False, "closed": [], "expired": [], "left": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有收录义务」）"
        return out
    out["checked"] = True
    for row in _register_items(conductor):
        key = str(row.get("input_key") or "")
        if str(row.get("item_state") or "") == "done":
            continue
        task_id = str(row.get("task_id") or "")
        label = key[len(REGISTER_PREFIX):].partition("@")[0]
        if "#p" not in label:
            label = f"{label}#p1"
        gap = registration_gap(store=store, label=label,
                              proof_sha=register_sha_of(key))
        if not gap.get("checked"):
            out["left"].append({"key": key, "why": str(gap.get("reason") or "查不成")})
            continue
        if gap.get("gap"):
            out["left"].append({"key": key,
                                "why": f"义务还在（{gap.get('reason')}）"})
            continue
        close = "expired" if gap.get("abandoned") else "completed"
        _state, problem = conductor.close_item_by_evidence(
            task_id, close=close, why=f"义务已清：{gap.get('reason')}")
        if problem:
            out["problems"].append(f"{task_id}：{problem}")
            continue
        out["closed"].append(task_id)
        if close == "expired":
            out["expired"].append(task_id)
    out["reason"] = (f"对账：收口 {len(out['closed'])} 条"
                     f"（其中明确不收录作废 {len(out['expired'])} 条），"
                     f"仍开着 {len(out['left'])} 条"
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out


def registration_digest(root: str | Path, store: Any = None) -> dict[str, Any]:
    """「必须收录」义务的一眼读数：开着的 / 认不出负责人的 / 已召唤 B 的 / 逐条明细。

    `summoned` 与每行的 `wake` 是 SGN1（2026-11-17）加的：义务"开在板上"与
    "有人被叫醒"是两件事，读数必须分得开 —— 改前这一格只数开项，于是
    "3 枚签 / 0 条义务 / B 一次没醒"在收工读数里长得像"没有欠收录"。
    """
    out: dict[str, Any] = {"checked": False, "open": 0, "unowned": 0, "summoned": 0,
                           "rows": [], "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有收录义务」）"
        return out
    out["checked"] = True
    wakes: dict[str, dict[str, Any]] = {}
    try:
        for row in (store.rows("tasks") if store is not None else ()):
            key = str(row.get("input_key") or "")
            if key.startswith(REGISTER_WAKE_PREFIX):
                wakes[key] = dict(row)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没读到"，不折成"没召过"
        out["problems"].append(f"召唤行读不出来（{type(exc).__name__}: {exc}）")
    for row in _register_items(conductor):
        if str(row.get("item_state") or "") == "done":
            continue
        owner = str(row.get("parent_task_id") or "")
        key = str(row.get("input_key") or "")
        sid = key[len(REGISTER_PREFIX):].partition("@")[0]
        sha = register_sha_of(key)
        wake = wakes.get(register_wake_key(f"{sid}#p1", sha)) or {}
        out["open"] += 1
        if not owner:
            out["unowned"] += 1
        if wake.get("task_id"):
            out["summoned"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""),
                            "key": key,
                            "owner": owner or "unknown",
                            "item_state": str(row.get("item_state") or ""),
                            "role": str(row.get("role") or ""),
                            "wake": str(wake.get("task_id") or ""),
                            "wake_at": str(wake.get("started_at") or ""),
                            "detail": str(row.get("detail") or "")[:200]})
    out["reason"] = (f"板上开着 {out['open']} 条收录义务"
                     + (f"（其中 {out['unowned']} 条负责人 unknown，等主控派人）"
                        if out["unowned"] else "")
                     + (f"；其中 {out['summoned']} 条已经召唤过 B" if out["summoned"] else ""))
    return out


def _prefix() -> str:
    from .agent_loop import V_VERDICT_ITEM_PREFIX

    return V_VERDICT_ITEM_PREFIX


def _root_of(store: Any, fallback: Any = "") -> str:
    got = getattr(store, "root", None) or fallback
    return str(got or "")


# ------------------------------------------------------------------ 键与明细

def key_of(label: str, verification_id: str, recipient: str) -> str:
    """判词板项的键：`v-verdict@<label>@<vid>@<recipient>`（只用于读旧盘）。

    写它的不是本模块：`agent_loop.deliver_v_verdicts` 只在收件人下一次起跑时按台账
    递送。本模块只在 [:func:`reconcile`] 里读它认"这一条判词当时投给了谁"。
    带收件人的理由是历史键（无后缀）认不出收件人；这里不改写、不重开。
    """
    return f"{_prefix()}{label}@{verification_id}@{recipient}"


def legacy_key_of(label: str, verification_id: str) -> str:
    """没有收件人后缀的旧键：只用于读旧盘，不许用它写新项。"""
    return f"{_prefix()}{label}@{verification_id}"


def _label_of(row: Mapping[str, Any]) -> tuple[str, str]:
    """台账行 ⇒ `(label, verification_id)`；`label = <stmt>#p<proof_no>`。"""
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    no = row.get("proof_no")
    vid = str(row.get("verification_id") or "")
    if not sid or not vid:
        return "", ""
    try:
        no_int = int(no) if no is not None else 1
    except (TypeError, ValueError):
        no_int = 1
    return f"{sid}#p{no_int}", vid

# ------------------------------------------------------------------ 收件人

def _conductor(store: Any) -> Any:
    """这个工作区已经存在的主控（绝不顺手建一个：建歪了会让判据读到空壳）。"""
    if store is None:
        return None
    try:
        from .tools.conductor_tools import cached_conductor

        return cached_conductor(store)
    except Exception:  # noqa: BLE001 —— 读不到主控是"投不了"，不是崩溃
        return None


def _task_row(store: Any, task_id: str) -> dict[str, Any]:
    """台账里的一行（读不到 ⇒ `{}`）。"""
    if store is None or not str(task_id or ""):
        return {}
    try:
        for row in store.rows("tasks"):
            if str(row.get("task_id") or "") == str(task_id):
                return dict(row)
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _recipient_now(store: Any) -> dict[str, Any]:
    """这一条义务的负责人：这一次工具调用所属召唤的父（`current_parent` = 送审者）。

    读不到 ⇒ `recipient=""` + `reason`（`ensure_resubmit` 记 `unowned`，不猜）。
    """
    out: dict[str, Any] = {"recipient": "", "role": "", "depth": 0, "reason": ""}
    try:
        from . import conductor as CND

        pid, prole = CND.current_parent()
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"读不到调用上下文（{type(exc).__name__}: {exc}）"
        return out
    if not str(pid or ""):
        out["reason"] = ("这一趟调用不在任何召唤里（`current_parent` 是空）⇒ "
                         "读不到送审者；不拿「谁醒着」当收件人")
        return out
    rec = _task_row(store, pid)
    if not rec:
        out["reason"] = f"送审者 {pid} 在台账里没有那一行 ⇒ 板项没处挂（不猜）"
        return out
    out["recipient"] = str(pid)
    out["role"] = str(prole or rec.get("role") or "")
    out["depth"] = max(1, int(rec.get("depth") or 1))
    return out

def resolve_recipient(store: Any, at: str) -> dict[str, Any]:
    """历史判定的收件人：按 V 台账号的时间窗解析，唯一才认。

    口径（不猜）：

    - 那一拍恰好只有一趟 V 在跑 ⇒ 收件人 = 它的 `parent_task_id`（送审者）；
    - 0 趟或 2 趟以上 ⇒ `checked=False` + 原因（不是"没有收件人"）。

    为什么可以这么读：V 台账号的 `started_at` / `ended_at` 在 `tasks` 上逐秒可读，
    而一条判定只能由一趟 V 产出。两趟并发时不可判 ——
    那时"哪一趟审的"只能靠 run 工件与会话对时，那不是运行期该做的事（也不是"讲证据"，
    是"讲推断"）。
    """
    out: dict[str, Any] = {"checked": False, "recipient": "", "role": "",
                           "depth": 0, "candidates": [], "reason": ""}
    if not str(at or ""):
        out["reason"] = "这一条判定没有 `at` ⇒ 时间窗无从读（不是「没有送审者」）"
        return out
    try:
        t = datetime.fromisoformat(str(at))
    except ValueError:
        out["reason"] = f"`at` 不是 ISO 时间：{at!r}"
        return out
    alive: list[dict[str, Any]] = []
    try:
        raw_rows = list(store.rows("tasks"))
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）⇒ 收件人没解析"
        return out
    # 一趟同时做"只留 V 台账号"与"时间窗覆盖 at"（原先先把 V 行抄一份、再扫一遍）。
    for row in raw_rows:
        if str(row.get("role") or "") != "V" or str(row.get("kind") or ""):
            continue
        try:
            started = datetime.fromisoformat(str(row.get("started_at") or ""))
        except ValueError:
            continue
        ended_text = str(row.get("ended_at") or "")
        try:
            ended = datetime.fromisoformat(ended_text) if ended_text else None
        except ValueError:
            ended = None
        if started <= t and (ended is None or t <= ended):
            alive.append(dict(row))
    out["candidates"] = [str(r.get("task_id") or "") for r in alive]
    if len(alive) != 1:
        out["reason"] = (f"那一拍有 {len(alive)} 趟 V 在跑（{out['candidates']}）⇒ "
                         "送审者不可判（不猜）" if alive else
                         "那一拍没有 V 在跑 ⇒ 送审者不可判（不猜）")
        return out
    who = alive[0]
    pid = str(who.get("parent_task_id") or "")
    if not pid:
        out["reason"] = f"V 台账号 {who.get('task_id')} 没有父（顶层发起）⇒ 没有送审者"
        return out
    rec = _task_row(store, pid)
    if not rec:
        out["reason"] = f"送审者 {pid} 在台账里没有那一行 ⇒ 板项没处挂"
        return out
    out.update(checked=True, recipient=pid, role=str(rec.get("role") or ""),
               depth=max(1, int(rec.get("depth") or 1)),
               reason=f"由 V 台账号 {who.get('task_id')} 的时间窗唯一确定")
    return out

# ------------------------------------------------------------------ 板项读口

def _board_item(conductor: Any, label: str, verification_id: str) -> dict[str, Any]:
    """板上有没有这一条（新键、旧键、任意收件人后缀都算）⇒ 那一行。

    这是"这一条判词的板项在哪"的纯读口：历史盘上那一项可能是 `v-verdict@` 的老键
    （无收件人后缀）或新键（带后缀），两种都认。没有 conductor / 读不成 ⇒ 空字典
    （"读不到板"），调用方（`reconcile`）把那一档记 `left` + 原因，不在这里冒充
    "板上没有这一条"。
    """
    base = legacy_key_of(label, verification_id)
    if conductor is None:
        # 空输入得空输出：这一格是"板上有没有这一条"的纯读口，没 conductor 就是"读不到板"；
        # 调用方（`reconcile`）把那一档记 `left` + 原因，不在这里折成"板上没有"。
        return {}
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001
        return {}
    for row in rows:
        key = str(row.get("input_key") or "")
        if key == base or key.startswith(base + "@"):
            return row
    return {}

def _resubmit_or_skip(*, requires_rewrite: bool, store: Any, root: str,
                      label: str, verification_id: str,
                      detail: Mapping[str, Any], recipient: str, role: str,
                      depth: int, at: str) -> dict[str, Any]:
    """按这一条判定的类别开不开"改稿"义务（D3 批 2 的唯一分叉点）。

    - `requires_rewrite=True`（math / contract / 历史行）⇒ 照旧 `ensure_resubmit`；
    - `False`（程序性 / 文风）⇒ 不开义务，回一个 `state="skipped"` 的读数：
      待改的是 V 的报告，不是这份正文；同一份正文可以原样再送。

    为什么不返回空 dict：`record_verdict` 的调用方/判据读 `resubmit.state`；"没开义务"
    必须是一条有内容的读数（reason 说明为什么），不能与"没读到"折平。
    """
    if requires_rewrite:
        return ensure_resubmit(
            store=store, root=root, label=label, verification_id=verification_id,
            detail=detail, recipient=recipient, role=role, depth=depth, at=at)
    sha = str(detail.get("proof_sha256") or "")
    return {"checked": True, "state": "skipped",
            "key": (resubmit_key(label, sha) if sha else ""),
            "item_id": "", "owner": str(recipient or ""),
            "reason": ("程序性/文风：这一份正文没有被指出数学缺陷 ⇒ 不开改稿义务"
                       "（同一份正文可以原样再送，不必改稿换 sha）"),
            "problems": []}



# ------------------------------------------------------------------ 一条判定 ⇒ 一条义务

def _verdict_detail(store: Any, root: str, label: str,
                    verification_id: str) -> dict[str, Any] | None:
    """从台账把一条判定读成重送项要的明细（收工对账补开历史行时走这一支）。

    只取开义务真正要用的四格：`verification_id` / `proof_sha256` / `defect_step` /
    `requires_rewrite`。正文里的措辞由 :func:`_resubmit_body` 现拼，不从别处抄一份。
    读不出来 ⇒ `None`（调用方记"跳过"，不拿空明细开一条没有 sha 的项）。
    """
    from . import verifications as VR

    sid = str(label or "").split("#", 1)[0]
    try:
        rows, _problems = VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception:  # noqa: BLE001 —— 读不成不是"这一条没有义务"
        return None
    sign = next((dict(r) for r in rows
                 if str(r.get("verification_id") or "") == str(verification_id or "")), None)
    if sign is None:
        return None
    kind = VR.fault_kind_of(sign)
    report = (str(kind.get("source") or "") == "row"
              and str(kind.get("kind") or "") in ("procedural", "style"))
    step = sign.get("defect_step")
    return {"verification_id": str(verification_id or ""),
            "proof_sha256": str(sign.get("proof_sha256") or ""),
            "defect_step": step if isinstance(step, int) else None,
            "requires_rewrite": not report}


def record_verdict(store: Any, row: Mapping[str, Any], *, at: str = "",
                   source: str = "verify_proof") -> dict[str, Any]:
    """一条台账行落下之后：干净「成立」⇒ 收口重送项；「有毛病」⇒ 开/续重送义务。

    投递不在这里（见模块 docstring）：这一格只维护义务。判词送达由
    `vreviews.deliver_review`（判定那一刻）与 `agent_loop.deliver_v_verdicts`
    （收件人下一次起跑）负责，两条都走既有板项 / 信箱唤醒。

    返回 `{"checked","state","reason","problems","resubmit"}`；`state` 取
    `settled` / `skipped` / `opened` / `existing` / `cleared` / `closed` / `unowned` /
    `error`（后几档由 `ensure_resubmit` 的读数原样带出）。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "reason": "",
                           "problems": [], "resubmit": {}}
    if store is None:
        out["reason"] = "没有 store ⇒ 义务没处落（不是「没有义务」）"
        return out
    label, vid = _label_of(row)
    if not label or not vid:
        out["reason"] = "这一行没有 label / 编号 ⇒ 做不出幂等键（不猜）"
        return out
    root = _root_of(store)
    from . import vsigns as VSP

    if not VSP.verdict_axis(row):
        # 干净的「成立」是关闭重送义务的那一道门（不是"什么都不做"）。
        try:
            settled = settle_resubmitted(store=store, root=root, row=row)
        except Exception as exc:  # noqa: BLE001 —— 收口失败不许带走这一签
            settled = {"checked": False, "closed": [], "skipped": [], "problems": [],
                       "reason": f"重送项收口没跑成（{type(exc).__name__}: {exc}）"}
        out["resubmit"] = settled
        out["problems"].extend(str(x) for x in (settled.get("problems") or []))
        if settled.get("closed"):
            out.update(checked=bool(settled.get("checked")), state="settled",
                       reason=str(settled.get("reason") or "义务已清"))
        else:
            out.update(checked=bool(settled.get("checked")), state="skipped",
                       reason=(str(settled.get("reason") or "")
                               or "这一签不是「有毛病」那一档 ⇒ 没有要收口的重送项"))
        return out
    detail = _verdict_detail(store, root, label, vid)
    if detail is None:
        out["reason"] = "台账里读不出这一行的明细 ⇒ 这一条义务没开（不是「没有义务」）"
        out["problems"].append(out["reason"])
        return out
    who = _recipient_now(store)
    got = _resubmit_or_skip(
        requires_rewrite=bool(detail.get("requires_rewrite", True)),
        store=store, root=root, label=label, verification_id=vid, detail=detail,
        recipient=str(who["recipient"]), role=str(who["role"]),
        depth=int(who["depth"]), at=str(at or row.get("at") or ""))
    out["resubmit"] = got
    out["problems"].extend(str(x) for x in (got.get("problems") or []))
    out.update(checked=bool(got.get("checked")), state=str(got.get("state") or ""),
               reason=str(got.get("reason") or ""))
    return out



def reconcile_resubmits(*, store: Any, root: str | Path) -> dict[str, Any]:
    """把板上开着的重送义务与"盘上的事实"对一次账（收工前那一趟的收敛点）。

    为什么要对账（而不是只在写入时收口）：义务的关闭有两个来源，而它们不都经过
    `record_verdict` ——

    - 干净的「成立」签落下时由 `record_verdict` 收口（`settle_resubmitted`）；
    - 命题被明确放弃时，可能走 `statementabandon.apply_abandonment`（它自己会作废），
      也可能走 `table.update(status=abandoned)` 那条就地写口
      （`Secretary.amend_statement_meta`）—— 后者不认识板项，义务会留在板上，
      反过来把销号闸（`retire_integrity` 的"名下还有未消的板项"）锁死。

    所以补一条对账：逐条看板上开着的 `v-resubmit@<命题>@<sha>`，按盘上的事实决定
    收口方式 —— 命题已是可解析的 `abandoned` ⇒ 作废（`expired`）；否则同一份证明
    已有更新的干净「成立」⇒ 收口（`completed`）。两个判据都复用既有唯一实现
    （`statementabandon.parse_abandon` / `resubmit_cleared`），这里不新立一份。

    幂等：已经收口的项不在 `_resubmit_items` 里，重跑是零写入。三态：板项读不出来 /
    台账读不出来 ⇒ `checked=False`（不是"没有要收口的"）。
    """
    from . import statementabandon as _SA

    out: dict[str, Any] = {"checked": False, "closed": [], "expired": [], "left": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有重送义务」）"
        return out
    try:
        board = [dict(r) for r in conductor._board_rows()]
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"板项读不出来（{type(exc).__name__}: {exc}）"
        return out
    # 取数走查口的唯一取数口（三态：读不成不是 0 行）；索引的构造只有一处。
    stmt_rows, problem, error = SL.rows_of(store)
    if problem:
        out["reason"] = (f"`statements` 读不出来（{error.get('type') or '?'}: "
                         f"{error.get('message') or problem}）")
        return out
    statements = SL.index_by_id(stmt_rows)
    out["checked"] = True
    for row in board:
        key = str(row.get("input_key") or "")
        if not key.startswith(RESUBMIT_PREFIX):
            continue
        if str(row.get("item_state") or "") == "done":
            continue
        task_id = str(row.get("task_id") or "")
        sid = key[len(RESUBMIT_PREFIX):].partition("@")[0]
        sha = resubmit_sha_of(key)
        stmt = statements.get(sid) or {}
        if not stmt:
            out["left"].append({"key": key, "why": f"命题 {sid} 不在册 ⇒ 不猜它放没放弃"})
            continue
        if str(stmt.get("status") or "") == "abandoned":
            parsed = _SA.parse_abandon(stmt.get("quote_reason"))
            if not parsed.get("checked"):
                out["problems"].append(
                    f"{sid}：status=abandoned 而放弃标记读不出来（{parsed.get('why')}）"
                    " ⇒ 义务不按放弃处理（它仍然是未签）")
                out["left"].append({"key": key, "why": "放弃标记读不出来"})
                continue
            _state, problem = conductor.close_item_by_evidence(
                task_id, close="expired",
                why=f"命题 {sid} 已被明确放弃（{parsed.get('at')}）")
            if problem:
                out["problems"].append(f"{task_id}：{problem}")
                continue
            out["expired"].append(task_id)
            out["closed"].append(task_id)
            continue
        cleared = resubmit_cleared(root=root, label=f"{sid}#p1", proof_sha=sha)
        if not cleared.get("checked"):
            out["left"].append({"key": key, "why": str(cleared.get("why") or "台账读不成")})
            continue
        if not cleared.get("cleared"):
            out["left"].append({"key": key, "why": "义务还在（还没有更新的干净成立）"})
            continue
        _state, problem = conductor.close_item_by_evidence(
            task_id, close="completed",
            why=f"义务已清：{cleared.get('why')}")
        if problem:
            out["problems"].append(f"{task_id}：{problem}")
            continue
        out["closed"].append(task_id)
    out["reason"] = (f"对账：收口 {len(out['closed'])} 条"
                     f"（其中放弃作废 {len(out['expired'])} 条），"
                     f"仍开着 {len(out['left'])} 条"
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out



# ------------------------------------------------------------------ 收工前的补开与对账

def reconcile(*, store: Any, root: str | Path = "", caller: str = "conductor.closing"
              ) -> dict[str, Any]:
    """收工前把两族义务与盘上的事实对一次账（只维护义务，不投任何回执）。

    三件事，顺序固定：

    ① 漏开的补开：逐条「有毛病」判定，板上没有对应 `v-resubmit@<命题>@<sha>` 的，
       先按当时那一项判决的板项认送审者，认不出再按"那一拍唯一一趟 V"的时间窗解析
       （`resolve_recipient`，唯一才认），然后开项；
    ② 重送义务对账（`reconcile_resubmits`）：命题被明确放弃 ⇒ `expired`，
       出现更新的干净「成立」⇒ `completed`；
    ③ 收录义务：先扫盘补开（`sweep_registrations`），再与盘上事实对账
       （`reconcile_registrations`）。

    三态：台账 / 板项 / statements 读不出来 ⇒ `checked=False` + `reason`，
    不许折成"没有要补的"。补开是幂等的：同键只一条，重跑零写入。
    """
    out: dict[str, Any] = {"checked": False, "caller": caller, "receipts": 0,
                           "opened": [], "left": [], "resubmit": [],
                           "resubmit_reconcile": {}, "registration": {},
                           "registration_reconcile": {}, "problems": [], "reason": ""}
    if store is None:
        out["reason"] = "没有 store ⇒ 这一格没查成（不是「没有漏开的义务」）"
        return out
    root = _root_of(store, root)
    try:
        from . import vsigns as VSP

        got = VSP.receipt_digest(root, store, limit=10_000)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"打回读数读不出来（{type(exc).__name__}: {exc}）⇒ 补开没跑"
        out["problems"].append(out["reason"])
        return out
    out["problems"].extend(str(x) for x in (got.get("problems") or []))
    if not got.get("checked"):
        out["reason"] = (f"台账读不成（{got.get('reason') or '原因没读到'}）⇒ "
                         "这一格没查成（不是「没有漏开的义务」）")
        return out
    out["checked"] = True
    out["receipts"] = int(got.get("receipts") or 0)
    conductor = _conductor(store)
    for one in got.get("rows") or []:
        label = str(one.get("label") or "")
        vid = str(one.get("verification_id") or "")
        at = str(one.get("at") or "")
        if not label or not vid:
            out["problems"].append("有一行没有 label / 编号 ⇒ 补开跳过（不猜）")
            continue
        detail = _verdict_detail(store, root, label, vid)
        if detail is None:
            out["problems"].append(f"{label}@{vid}：台账里读不出这一行的明细 ⇒ 补开跳过")
            continue
        if not bool(detail.get("requires_rewrite", True)):
            # 程序性 / 文风不是打回：不发回执，也不开"改稿"义务（D3 批 2）。
            continue
        sha = str(detail.get("proof_sha256") or "")
        key = resubmit_key(label, sha) if sha else ""
        row = _resubmit_item_by_key(conductor, key) if key else {}
        if row:
            # 已经开过（不论开没开成终态）：不重开，读数里记一条。
            out["left"].append({"key": key, "why": "板上已有这一条义务"})
            continue
        item = _board_item(conductor, label, vid)
        recipient = str(item.get("parent_task_id") or "")
        role = str(item.get("role") or "")
        depth = max(1, int(_task_row(store, recipient).get("depth") or 1)) if recipient else 0
        why = "板上那一项判决的收件人" if recipient else ""
        if not recipient:
            who = resolve_recipient(store, at)
            if who.get("checked"):
                recipient, role = str(who["recipient"]), str(who["role"])
                depth = int(who["depth"])
                why = str(who.get("reason") or "")
            else:
                out["left"].append({"label": label, "verification_id": vid,
                                    "why": str(who.get("reason") or "送审者不可判")})
                continue
        rs = ensure_resubmit(store=store, root=root, label=label, verification_id=vid,
                             detail=detail, recipient=recipient, role=role,
                             depth=depth, at=at)
        out["resubmit"].append({"label": label, "verification_id": vid, "why": why, **rs})
        out["problems"].extend(str(x) for x in (rs.get("problems") or []))
        if rs.get("state") == "opened":
            out["opened"].append(str(rs.get("item_id") or ""))
    try:
        out["resubmit_reconcile"] = reconcile_resubmits(store=store, root=root)
    except Exception as exc:  # noqa: BLE001 —— 对账没跑成不许带走收工读数
        out["resubmit_reconcile"] = {"checked": False, "closed": [], "expired": [],
                                     "left": [], "problems": [],
                                     "reason": f"对账没跑成（{type(exc).__name__}: {exc}）"}
    try:
        out["registration"] = sweep_registrations(store=store, root=root)
    except Exception as exc:  # noqa: BLE001 —— 扫盘没跑成不许带走收工读数
        out["registration"] = {"checked": False, "scanned": 0, "signed": 0,
                               "opened": [], "existing": [], "closed": [], "cleared": [],
                               "expired": [], "skipped": [], "problems": [],
                               "reason": f"扫盘没跑成（{type(exc).__name__}: {exc}）"}
    try:
        out["registration_reconcile"] = reconcile_registrations(store=store, root=root)
    except Exception as exc:  # noqa: BLE001
        out["registration_reconcile"] = {
            "checked": False, "closed": [], "expired": [], "left": [], "problems": [],
            "reason": f"对账没跑成（{type(exc).__name__}: {exc}）"}
    out["reason"] = (f"打回 {out['receipts']} 条；补开重送项 {len(out['opened'])} 条、"
                     f"认不出送审者 {len(out['left'])} 条；"
                     f"{str(out['resubmit_reconcile'].get('reason') or '')}；"
                     f"{str(out['registration'].get('reason') or '')}；"
                     f"{str(out['registration_reconcile'].get('reason') or '')}")
    return out
