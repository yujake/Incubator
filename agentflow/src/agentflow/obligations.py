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


def _manuscript_of_proof(store: Any, root: Any, sid: str, sha: str) -> dict[str, Any]:
    """这份被签正文属于哪一份稿（`manuscriptpaths.path_reading` 是唯一读口）。

    返回 `{checked, manuscript, why}`。认不出（台账里没有那个 sha / 没有稿）⇒
    空稿路径 —— 调用方退回"送审者"那一条旧地址，不猜一个稿。
    """
    out: dict[str, Any] = {"checked": False, "manuscript": "", "why": ""}
    if store is None or not str(sid or "") or not str(sha or ""):
        out["why"] = "没有 store / 命题号 / 正文 sha ⇒ 认不出稿"
        return out
    try:
        from . import manuscriptpaths as _MP

        got = dict(_MP.path_reading(store, root, statement_id=str(sid)))
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["why"] = f"路径面读不出来（{type(exc).__name__}: {exc}）"
        return out
    out["checked"] = bool(got.get("checked"))
    want = str(sha or "").strip().lower()
    for one in got.get("paths") or ():
        if str(one.get("body_sha") or "").strip().lower() != want:
            continue
        rel = str(one.get("manuscript") or "").strip().replace("\\", "/")
        if rel:
            out.update(manuscript=rel,
                       why=f"正文 sha {want[:12]}… 属于 `{rel}`")
            return out
    out["why"] = (f"`{sid}` 的路径面里没有 sha={want[:12]}… 那一份稿"
                  "（认不出是哪一份 ⇒ 不猜）")
    return out


def _manuscript_owner(store: Any, root: Any, sid: str, sha: str,
                      manuscript: str = "") -> dict[str, Any]:
    """这份稿的产出实例（K9 的收件人来源：产物台账说谁写的，就是谁）。

    稿路径优先取调用方给的那一份（判词行自己记着"我审的是哪份稿"，见
    `_verdict_detail`）；没给才按"命题号 + 正文 sha"从路径面反查。
    实现只有一处：`agent_f.pending.manuscript_producer`（台账 `producer`/`instance`
    > 实例级 actor）。
    返回 `{checked, manuscript, role, instance, why}`；认不出实例 ⇒ `instance=""`
    （调用方按角色地址处置，不挑一趟）。
    """
    out: dict[str, Any] = {"checked": False, "manuscript": str(manuscript or ""),
                           "role": "", "instance": "", "why": ""}
    if out["manuscript"]:
        out.update(checked=True, why="稿路径来自判词行")
    else:
        got = _manuscript_of_proof(store, root, sid, sha)
        out["manuscript"] = str(got.get("manuscript") or "")
        if not out["manuscript"]:
            out.update(checked=bool(got.get("checked")), why=str(got.get("why") or ""))
            return out
    try:
        from .agent_f import pending as _FP

        prod = dict(_FP.manuscript_producer(str(root or ""), out["manuscript"]))
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["why"] = f"产物归属读不出来（{type(exc).__name__}: {exc}）"
        return out
    out.update(checked=True, role=str(prod.get("producer_role") or ""),
               instance=str(prod.get("producer_instance") or ""),
               why=(f"`{out['manuscript']}` 的产出实例是 "
                    + (str(prod.get("producer_instance")) if prod.get("producer_instance")
                       else "（没有实例归属）")))
    return out


def _addressed_task(store: Any, role: str, instance: str) -> dict[str, Any]:
    """那个实例此刻在飞的台账号；不在飞 ⇒ 空（不拿终态行当地址）。"""
    if not str(instance or ""):
        return {}
    return _live_task_of(store, str(role or ""), str(instance))


def ensure_resubmit(*, store: Any, root: str | Path, label: str,
                    verification_id: str, detail: Mapping[str, Any], recipient: str,
                    role: str, depth: int, at: str = "") -> dict[str, Any]:
    """开一条「待重送」板项（幂等；已清掉的不开）。

    返回 `{"checked","state","key","item_id","owner","owner_instance","owner_known",
    "owner_why","reason","problems"}`，`state ∈ {opened, existing, cleared, closed,
    unowned, skipped, error}`：

    - `opened`：新开了一条；
    - `existing`：同键的项已经在板上（不重开 —— 这是幂等的落点）；
    - `cleared`：这次打回之后已经有一条更新的干净「成立」⇒ 义务本来就没了，不开
      （历史补投会走到这一支：旧判决不该在收工时凭空长出一条待办）；
    - `closed`：板上那条已经 done（不重开，读数说"已经收口"）；
    - `unowned`：既读不到送审者、又认不出这份稿的产出实例 ⇒ 不猜负责人、不开项；
    - `skipped`：这一行没有 sha / 没有命题号 ⇒ 做不出幂等键（不猜）；
    - `error`：开项抛了（`problems` 里带原话），不带走这一签。

    ## 收件人 = 该稿的产出实例（K9 / SH-40）

    改前收件人是"送审者"（`conductor.current_parent()`，即发起那一趟的台账号）。
    那一趟一结束，板项就挂在一个 `done` 的号上：`open_items_of` 只看自己名下的行，
    新起的同角色台账号看不见它（真机 lp-ball-8 的 `v-resubmit@` 挂在已 done 的
    t-000049 上）。现在收件人是这份稿的产出实例（产物台账的 `producer`/`instance`），
    地址写进板项行（`Task.instance`），父只在该实例此刻在飞时填 —— 终态行不再是地址，
    义务等那个实例下一次起跑时由 `Conductor.open_items_for` 交给它。
    """

    from . import vsigns as VSP

    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "owner": str(recipient or ""), "owner_instance": "",
                           "owner_known": False, "owner_why": "",
                           "reason": "", "problems": []}
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
    # ---- 收件实例：这份稿的产出实例（K9） ---------------------------------
    owner = _manuscript_owner(store, root, sid, sha,
                              manuscript=str(detail.get("manuscript") or ""))
    target_role = str(owner.get("role") or role or "")
    target_instance = str(owner.get("instance") or "")
    live: dict[str, Any] = {}
    if target_instance:
        live = _addressed_task(store, target_role, target_instance)
        out["owner_instance"] = target_instance
        out["owner_known"] = True
        out["owner"] = str(live.get("task_id") or "")
        out["owner_why"] = (f"这份稿的产出实例是 {target_instance}"
                            + (f"，此刻在飞 {live.get('task_id')}" if live else
                               "，此刻没有在飞的台账号 ⇒ 义务按实例地址等它下一次起跑"))
    else:
        # 认不出产出实例：退回送审者那一条旧地址 —— 但绝不挂在已终态的号上。
        caller = str(recipient or "")
        # 显式置空再判：`out["owner"]` 的初值是调用方给的那一趟，而"它已终态"
        # 这一档必须真的把这个地址清掉（不是留着继续说"挂在它名下"）。
        out["owner"] = caller if (caller and _task_running(store, caller)) else ""
        out["owner_known"] = bool(out["owner"])
        out["owner_why"] = (str(owner.get("why") or "认不出产出实例")
                            + ("；送审者那一刻在飞，按它投递" if out["owner"]
                               else "；送审者不在飞 ⇒ 按角色地址落在板上"))
        if not out["owner"] and not target_instance and not caller:
            out.update(state="unowned", owner="unknown",
                       reason=("读不到送审者、也认不出这份稿的产出实例 ⇒ 不猜负责人、"
                               "不开项；owner_known=False 会出现在收工读数里"))
            return out
    row = _resubmit_item_by_key(conductor, key)
    if row:
        task_id = str(row.get("task_id") or "")
        state = str(row.get("item_state") or "")
        out.update(checked=True, item_id=task_id,
                   owner=str(row.get("parent_task_id") or ""),
                   owner_instance=str(row.get("instance") or out["owner_instance"]),
                   owner_known=bool(row.get("instance") or row.get("parent_task_id")),
                   state=("closed" if state == "done" else "existing"),
                   reason=(f"同键的板项已存在（{task_id}，item_state={state}）⇒ 不重开"))
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason="这一趟没有 conductor ⇒ 板项开不了（不拿意图当交付）")
        return out
    summary, body = _resubmit_body(label=label, detail=detail, at=at)
    parent = str(out["owner"] or "")
    if parent:
        item_depth = max(1, int(_task_row(store, parent).get("depth") or 1)) + 1
    else:
        item_depth = 1
    try:
        item_id = conductor.open_item(
            kind="notice", role=target_role, expects="work", action="notice",
            summary=summary, called_by="V", parent_task_id=(parent or None),
            depth=item_depth, input_key=key,
            recipient_instance=str(out["owner_instance"] or ""))
        conductor.set_item_detail(item_id, body)
    except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走这一签
        out.update(state="error",
                   reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
        return out
    out.update(checked=True, state="opened", item_id=item_id,
               reason=(f"新开重送项 {item_id}"
                       + (f"（收件实例 {out['owner_instance']}"
                          + (f"，在飞台账号 {out['owner']}" if out["owner"] else "，此刻不在飞")
                          + "）" if out["owner_instance"]
                          else "（按角色地址，由该角色的实例领取）")))
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
        instance = str(row.get("instance") or "")
        out["open"] += 1
        # 收件地址两格（K9）：实例地址在行上，台账号只在那个实例此刻在飞时才有。
        # 两格都空才是「没有收件人」；只有台账号空、实例地址在 ⇒ 义务等它下一次起跑。
        if not owner and not instance:
            out["unowned"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""), "key": key,
                            "owner": owner or "unknown", "owner_instance": instance,
                            "item_state": state,
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
    f"{_MFAM.dir_of(name)}/{_MFAM.prefix_of(name)}"
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


def wake_state_of(row: Mapping[str, Any],
                  wake_row: Mapping[str, Any] | None = None) -> str:
    """这一条 `b-register@` 义务的"叫醒落在哪一支"（只读，三档）。

    ## 为什么要这一格（RETIREFIX，2026-11-21，真机 `projects/lp-ball-15`）

    三族义务的旧读法把「`b-register` 4 条而 `b-awake` 0 条」读成"叫醒那一侧缺读数"
    —— 读错了。`b-awake@` 是「召唤」的幂等键（`_wake_registrar` 第 ④ 档：一个 B
    都没有 ⇒ 新召一趟才落行），其余五档（`already` / `running` / `woken` /
    `attached` / `addressed` / `role_addressed`）按设计不落 `b-awake@` 行。所以
    "0 条 b-awake"的正确读法是"这一趟没有新召过 B"，不是"没叫醒"。那一趟的四个
    签落地时刻，B 要么在飞（`t-000091` 的收件实例 `b-batch4-1` = `t-000014`，
    14:46:31–16:14:54 在飞）、要么按实例地址投递（`t-000113` → `B1`）、要么按角色
    地址留在板上（`t-000148` / `t-000170`，`instance` 空）—— 一条都不该有新召行。

    这一格只回答"落在哪一支"，不回答"叫得醒还是叫不醒"（后者是当场的 `wake.state`，
    在 V 的工具回执里，不落后台）：

    - ``summoned``：有同键的 `b-awake@` 召唤行（新召了一趟，行上带任务号与时刻）；
    - ``instance_addressed``：板上那条带收件实例（`instance` 非空）⇒ 按实例地址投递，
      不新召（`_wake_registrar` ②）；
    - ``role_addressed``：既无召唤行、也无实例地址 ⇒ 按角色地址留在板上
      （③ 那一档，该角色任一实例起跑时领得到）。

    判据只有这一处：`registration_digest` 的逐行读数与三族对账（`temp/reconB`）
    都读它。它不写盘、不新开义务行 —— "叫醒"不欠动作，不许拿它冒充一条待办。
    """
    if str((wake_row or {}).get("task_id") or "").strip():
        return "summoned"
    if str(row.get("instance") or "").strip():
        return "instance_addressed"
    return "role_addressed"


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


def _role_rows(store: Any, role: str) -> tuple[list[dict[str, Any]], str]:
    """该角色的台账号行（实例行；`kind` 非空的行不算）。读不成 ⇒ `([], 理由)`。"""
    if store is None:
        return [], "没有 store ⇒ 读不到台账号"
    try:
        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有人"
        return [], f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
    return [r for r in rows
            if str(r.get("role") or "") == str(role)
            and not str(r.get("kind") or "")], ""


def _row_instance(store: Any, role: str, task_id: str) -> str:
    """一个台账号那一趟的实例标签（`identity.resolve_identity` 是唯一来源）。

    台账号兜底（`source == "task_id"`）不算实例标签：那是"这一笔没有实例身份"的
    兼容读数，拿它当地址会让同一个实例换个号就收不到自己的义务。
    """
    if store is None or not str(task_id or ""):
        return ""
    try:
        from . import identity as _ID

        got = dict(_ID.resolve_identity(store, role, task_id=str(task_id)))
    except Exception:  # noqa: BLE001 —— 读不成 ⇒ 这一行没有实例标签
        return ""
    if str(got.get("source") or "") == "task_id":
        return ""
    return str(got.get("instance") or "")


def _live_task_of(store: Any, role: str, instance: str) -> dict[str, Any]:
    """那个实例此刻在飞的台账号行（没有 ⇒ 空字典）。

    只在飞的行当收件地址的父：一条终态行已经没有人读了，把义务挂上去就是
    "永远没人收"（`SH-40` 的现场）。实例地址本身仍留在板项行上，所以这一刻不在飞
    不等于这条义务丢了 —— 它等这个实例下一次起跑。
    """
    from .conductor import UNFINISHED_STATUSES

    if not str(instance or ""):
        return {}
    rows, _why = _role_rows(store, role)
    alive = [r for r in rows
             if str(r.get("status") or "") in UNFINISHED_STATUSES
             and _row_instance(store, role, str(r.get("task_id") or "")) == instance]
    if not alive:
        return {}
    alive.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
    return dict(alive[-1])


def _statement_registrar(store: Any, statement_id: str) -> dict[str, Any]:
    """这条命题是谁登记的：`statements.created_by` 上的实例标签。

    「谁登记了这条命题，谁把它收录完整」是一个可复算的事实（`created_by` 是 B 的
    写口落的），不是"谁醒着"那种推断。读不到实例标签（老行写的是 `secretary-B`
    这种角色级值）⇒ 空串，由调用方退回角色地址。
    """
    out: dict[str, Any] = {"checked": False, "instance": "", "created_by": "", "why": ""}
    sid = str(statement_id or "").strip()
    if store is None or not sid:
        out["why"] = "没有 store / 没有命题号 ⇒ 读不到登记实例"
        return out
    try:
        rows, problem, error = SL.rows_of(store)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["why"] = f"`statements` 读不出来（{type(exc).__name__}: {exc}）"
        return out
    if problem:
        out["why"] = (str(problem) + "（" + str((error or {}).get("type") or "?") + "）")
        return out
    row = dict(SL.index_by_id(rows).get(sid) or {})
    out["checked"] = True
    created_by = str(row.get("created_by") or "").strip()
    out["created_by"] = created_by
    if not created_by:
        out["why"] = f"命题 {sid} 的 `created_by` 是空的 ⇒ 登记实例读不到"
        return out
    from . import identity as _ID

    got = _ID.split_actor(REGISTER_ROLE, created_by)
    if not got.get("instance"):
        out["why"] = (f"命题 {sid} 的登记者是 {created_by!r}（角色级）⇒ 没有实例标签"
                      "（不拿角色桶当收件实例）")
        return out
    out["instance"] = str(got["instance"])
    out["why"] = f"命题 {sid} 由 {created_by} 登记 ⇒ 收件实例 {out['instance']}"
    return out


def recipient_reading(store: Any, role: str, *, statement_id: str = "",
                      owner: str = "", owner_instance: str = "") -> dict[str, Any]:
    """这条义务的收件实例与它的在飞台账号（K9 的唯一判据；不挑）。

    地址只从三处读，按优先级：

    1. 调用方点名的 `owner_instance` / `owner`（`owner` 的实例标签按 `identity` 读）；
    2. 收录义务：这条命题的登记实例（`statements.created_by`，见
       :func:`_statement_registrar`）—— "谁登记，谁收录完整"；
    3. 都没有 ⇒ 空串 = 角色地址（该角色的任一实例都能领，见
       `Conductor.open_items_for`）。

    改前这里的两段（`_live_role_task` 的"唯一才认"、`_registrar_now` 的"≥2 取最近
    开始"）都是在猜"哪一趟"，现在整段删除：查不出收件实例就记角色地址，由板项行
    自己带着这个事实（`Task.instance`）等它该等的人。

    返回 `{checked, role, instance, task_id, source, why}`；`task_id` 只在那个实例
    此刻在飞时非空（终态行不当地址）。
    """
    out: dict[str, Any] = {"checked": False, "role": str(role or ""), "instance": "",
                           "task_id": "", "source": "", "why": ""}
    instance = str(owner_instance or "").strip()
    source = "caller_instance" if instance else ""
    tid = str(owner or "").strip()
    if not instance and tid:
        instance = _row_instance(store, str(role or ""), tid)
        if instance:
            source = "caller_task"
        else:
            out["why"] = (f"调用方给的负责人 {tid} 读不出实例标签"
                          "（台账号不是实例地址；不拿它当收件实例）")
    if not instance and str(role or "") == REGISTER_ROLE and str(statement_id or ""):
        got = _statement_registrar(store, str(statement_id))
        if not got.get("checked"):
            out["why"] = str(got.get("why") or "登记实例没查成")
        instance = str(got.get("instance") or "")
        if instance:
            source = "statements.created_by"
    out["checked"] = True
    if not instance:
        out["source"] = "role"
        out["why"] = (out["why"] + "；" if out["why"] else "") + (
            "没有可判定的收件实例 ⇒ 这一条按角色地址落在板上"
            "（不按「唯一在飞 / 最近开始」挑一趟）")
        return out
    live = _live_task_of(store, str(role or ""), instance)
    out.update(instance=instance, task_id=str(live.get("task_id") or ""),
               source=source or "explicit",
               why=(f"收件实例 {instance}（来源 {source or 'explicit'}）"
                    + (f"，此刻在飞 {live.get('task_id')}" if live else
                       "，此刻没有在飞的台账号（义务等它下一次起跑）")))
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
                    owner: str = "", owner_instance: str = "",
                    opened_under: str = "", item_id: str = "") -> dict[str, Any]:
    """「签落地 ⇒ 把义务投给它的收件实例」这一步落成盘上的事实（幂等，永不抛）。

    改前这一格按角色找工作地址：`_registrar_now` 在 ≥2 趟 B 在飞时取"最近开始的那一趟"，
    0 趟时找"终态未销号"的那一趟。两处都是在猜"哪一趟"，也正是 K9 记的病：
    两条 `b-register@` 至今 `parent_task_id=None` 没人收 / lp-ball-4 两趟 B 同秒起跑
    只有最近开始的那个能收到。现在地址是显式的：`owner_instance` 由调用方
    （`recipient_reading`）给出，这一格只做投递，不做选择。

    六档（每档都是读数，不折平）：

    - `already`：这个键已经有召唤行 ⇒ 不重复召唤（重放 / 重复投递落在这一档）；
    - `running`：收件实例那一刻在飞 ⇒ 板项落在它名下，它下一拍自己读到；
    - `woken` / `attached`：收件实例静默未销号 ⇒ 同号继续（`wake_on_lifeline`：
      既有唯一带"已销号 / 在飞"双闸的唤醒口）；没接执行侧时停在 `attached`；
    - `addressed`：实例地址已知、而它这一刻没有在飞的台账号 ⇒ 不新召、也不拿别的
      B 顶；义务按实例地址留在板上，等它下一次起跑（`Conductor.open_items_for` 读得到）；
    - `role_addressed`：地址只到角色（没有任何可判定的收件实例）⇒ 有 B 的台账号时
      不挑一趟：板项按角色地址留在板上，该角色任一实例都能领；
    - `summoned`：一个 B 都没有过 ⇒ 新召一趟（`summon_begin` + `start_summon`，
      `by="M"` 是那一条边、父为空）；`task_id` 与 `at` 就是报告里那句"已召唤 B"；
    - `skipped` / `refused` / `error`：叫不动，逐档说清为什么（板项仍在板上）。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "task_id": "", "at": "",
                           "key": str(key or ""), "instance": str(owner_instance or ""),
                           "reason": ""}
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
    # ---- ② 地址是实例 ⇒ 定向投递（不查别的实例） ---------------------------
    if str(owner_instance or ""):
        tid = str(owner or "").strip() or str(
            _live_task_of(store, REGISTER_ROLE, str(owner_instance)).get("task_id") or "")
        if not tid:
            out.update(state="addressed",
                       reason=(f"收件实例 {owner_instance} 此刻没有在飞的台账号 ⇒ 不新召、"
                               "也不拿别的 B 顶：义务按实例地址留在板上，它下一次起跑时收到"))
            return out
        if tid == str(opened_under or ""):
            # 板项刚刚就开在它名下 ⇒ `open_item` 的 `_ensure_consumer` 已经走过一遍
            # 唤醒判定（信先在收件箱里、再叫它 —— 顺序反了它会读不到这一条）。
            consumer = dict(getattr(conductor, "last_consumer_reading", {}) or {})
            started = bool(consumer.get("started"))
            out.update(state=("woken" if started else "running"),
                       task_id=tid, at=str(at or ""),
                       reason=(f"板项开在 {tid} 名下（收件实例 {owner_instance}）；"
                               f"唤醒判定：{consumer.get('reason') or '（没有读数）'}"))
            return out
        running = _task_running(store, tid)
        woke: dict[str, Any] = {}
        if not running:
            try:
                woke = dict(conductor.wake_on_lifeline(tid) or {})
            except Exception as exc:  # noqa: BLE001 —— 叫醒失败要如实回
                woke = {"started": False,
                        "reason": f"叫醒那一笔抛了（{type(exc).__name__}: {exc}）"}
        out.update(state=("woken" if woke.get("started")
                          else ("running" if running else "attached")),
                   task_id=tid, at=str(at or ""),
                   reason=(str(woke.get("reason") or "")
                           or f"收件实例 {owner_instance} 的台账号 {tid}"))
        return out
    # ---- ③ 地址只到角色：有 B 的台账号就不挑一趟 ---------------------------
    rows, why = _role_rows(store, REGISTER_ROLE)
    if rows:
        out.update(state="role_addressed",
                   reason=(f"这一条按角色地址落在板上（{key}）：盘上有 {len(rows)} 趟 B 的"
                           "台账号，而没有点名收件实例 ⇒ 不按「唯一在飞 / 最近开始」挑一趟"
                           "（该角色任一实例都能领，见 `Conductor.open_items_for`）"))
        return out
    # ---- ④ 一个 B 都没有 ⇒ 新召一趟（这一条就是"SGN1 的修法"） -------------
    can, why_not = _executor_can_run(conductor, REGISTER_ROLE)
    if not can:
        out.update(state="skipped",
                   reason=(f"{why_not} ⇒ 这一键没有召唤（板项仍在板上，由主控/收工读数看见）；"
                           f"现场：{why or '没有 B 的台账号'}"))
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
        new_id = str(getattr(started, "task_id", "") or "")
        _re_address_wake_item(conductor, item_id=item_id, task_id=new_id, out=out)
        out.update(state="summoned", task_id=new_id,
                   at=str(_wake_row(store, key).get("started_at") or ""),
                   reason=(f"台账那一行已经派出去了（{new_id}），"
                           f"但执行侧没起来（{type(exc).__name__}: {exc}）"))
        return out
    row = _wake_row(store, key)
    new_id = str(getattr(started, "task_id", "") or "")
    _re_address_wake_item(conductor, item_id=item_id, task_id=new_id, out=out)
    out.update(state="summoned", task_id=new_id,
               at=str(row.get("started_at") or ""),
               reason=(f"已召唤 B {new_id}"
                       f"（{row.get('started_at') or '时刻没读到'}；键 {key}）"))
    return out


def _re_address_wake_item(conductor: Any, *, item_id: Any, task_id: Any,
                          out: dict[str, Any]) -> None:
    """新召来的那一趟 ⇒ 把板项改投到它名下（SGN1 的「板项开在它名下」那一格）。

    为什么这一步在召唤之后：未在册那一支先开板项是刻意的（信先落、再叫它 ——
    顺序反了，被叫醒的 B 读不到自己为什么起来），而"召到哪个台账号"只有
    `summon_begin` 之后才知道。不补这一格，召来的 B 名下什么都没有。
    永不抛：改投失败只落读数（板项仍在板上，按角色地址由该角色任一实例领）。
    """
    tid, item = str(task_id or ""), str(item_id or "")
    if not tid or not item:
        return
    try:
        said, why = conductor.re_address_item(item, parent_task_id=tid)
    except Exception as exc:  # noqa: BLE001 —— 改投失败不许带走这一签
        out["re_addressed_to"] = ""
        out["re_address_why"] = f"板项改投抛了（{type(exc).__name__}: {exc}）"
        return
    out["re_addressed_to"] = "" if why else tid
    out["re_address_why"] = why or said


def _task_running(store: Any, task_id: str) -> bool:
    """这个台账号那一刻还在跑吗（读不到 ⇒ 按不在跑处置，唤醒判定会再判一次）。"""
    from .conductor import UNFINISHED_STATUSES

    row = _task_row(store, task_id)
    return str(row.get("status") or "") in UNFINISHED_STATUSES


def ensure_registration(*, store: Any, root: str | Path, label: str, proof_sha: str,
                        manuscript: str = "", owner: str = "",
                        owner_instance: str = "", called_by: str = "V",
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
                           "owner": str(owner or ""), "owner_instance": str(owner_instance or ""),
                           "owner_known": False, "owner_source": "",
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
                   owner_instance=str(row.get("instance") or ""),
                   owner_known=bool(row.get("instance")),
                   owner_source="board_row",
                   state=("closed" if state == "done" else "existing"),
                   reason=(f"同键的板项已存在（{row.get('task_id')}，item_state={state}）"
                           "⇒ 不重开"))
        if wake:
            # 重放 / 重复投递落在这里：板项不重开；召唤那一侧按 `b-awake@` 键判
            # （`_wake_registrar` 的第一档：同键已有召唤行 ⇒ 不再召）。
            out["wake"] = _wake_registrar(
                store=store, conductor=conductor, key=register_wake_key(label, sha),
                label=label, manuscript=str(manuscript or ""), sha=sha, at=at,
                owner=str(out["owner"] or ""),
                owner_instance=str(out["owner_instance"] or ""))
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason=("这一趟没有 conductor ⇒ 板项开不了（义务不落盘 = 没人会看到；"
                           "不是「已经收录了」）"))
        return out
    # ---- 收件实例（K9）：显式地址，不挑 -------------------------------------
    #
    # 地址来源见 `recipient_reading`：调用方点名 > 这条命题的登记实例
    # （`statements.created_by`）> 角色地址。改前那两段（"唯一在飞才认" /
    # "≥2 取最近开始"）整段删除 —— 查不出收件实例就按角色地址落在板上，
    # 由该角色的实例领取，不在多趟里挑一个。
    rec = recipient_reading(store, REGISTER_ROLE, statement_id=sid,
                            owner=str(out["owner"] or ""),
                            owner_instance=owner_instance)
    out["owner"] = str(rec.get("task_id") or "")
    out["owner_instance"] = str(rec.get("instance") or "")
    out["owner_known"] = bool(out["owner_instance"])
    out["owner_source"] = str(rec.get("source") or "")
    # 「负责人记 unknown」是读数、不是失败：它不进 `problems`（那会让收工读数把
    # "没有收件实例"报成"这一条没办成"），由 `registration_digest` 的 `unowned` 数出来。
    out["owner_why"] = str(rec.get("why") or "")
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
            depth=item_depth, input_key=key,
            recipient_instance=str(out["owner_instance"] or ""))
        conductor.set_item_detail(item_id, body)
    except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走这一签
        out.update(state="error", reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
        return out
    out.update(checked=True, state="opened", item_id=item_id,
               reason=(f"新开「必须收录」义务 {item_id}"
                       + (f"（收件实例 {out['owner_instance']}"
                          + (f"，在飞台账号 {out['owner']}" if out["owner"] else "，此刻不在飞")
                          + "）" if out["owner_instance"]
                          else "（没有可判定的收件实例 ⇒ 按角色地址，由该角色的实例领取）")))
    if wake and not out["wake"]:
        # 板项刚刚开在有一趟 B 的名下 ⇒ 那一下就是既有唤醒口
        # （`open_item` → `_ensure_consumer`：静默 ⇒ 同号继续；在跑 ⇒ 下一拍自己读）。
        out["wake"] = _wake_registrar(
            store=store, conductor=conductor, key=register_wake_key(label, sha),
            label=label, manuscript=str(manuscript or ""), sha=sha, at=at,
            owner=str(out["owner"] or ""),
            owner_instance=str(out["owner_instance"] or ""),
            opened_under=str(out["owner"] or ""), item_id=str(item_id))
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
    base = Path(str(root or ""))
    files: list[Path] = []
    for prefix in REGISTRATION_CARRIERS:
        # `REGISTRATION_CARRIERS` 的每一项是「角色目录 + 族前缀」
        # （`manuscripts/F/f-proof-`）：目录与前缀一起决定扫哪里，不许丢目录
        # 再去 `reports/` 下 glob（旧布局已退役，2026-11-22）。
        rel_dir, _sep, name = prefix.rpartition("/")
        directory = base / rel_dir
        if not directory.is_dir():
            continue
        files.extend(sorted(directory.glob(f"{name}*.md")))
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

    RETIREFIX（2026-11-21）再加一格 `wake_state`（逐行）与两个合计
    （`instance_addressed` / `role_addressed`）：`summoned` 只数"新召了一趟"，
    而"按实例地址投递"/"按角色地址留在板上"这两档不落 `b-awake@` 行 —— 只给
    `summoned` 时，真机 lp-ball-15 的"4 条义务 / 0 条召唤"会被读成"叫醒缺读数"。
    判据在 :func:`wake_state_of`（唯一一处）。
    """
    out: dict[str, Any] = {"checked": False, "open": 0, "unowned": 0, "summoned": 0,
                           "instance_addressed": 0, "role_addressed": 0,
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
        instance = str(row.get("instance") or "")
        key = str(row.get("input_key") or "")
        sid = key[len(REGISTER_PREFIX):].partition("@")[0]
        sha = register_sha_of(key)
        wake = wakes.get(register_wake_key(f"{sid}#p1", sha)) or {}
        wake_state = wake_state_of(row, wake)
        out["open"] += 1
        if not owner and not instance:
            out["unowned"] += 1
        if wake_state == "summoned":
            out["summoned"] += 1
        elif wake_state == "instance_addressed":
            out["instance_addressed"] += 1
        else:
            out["role_addressed"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""),
                            "key": key,
                            "owner": owner or "unknown",
                            "owner_instance": instance,
                            "item_state": str(row.get("item_state") or ""),
                            "role": str(row.get("role") or ""),
                            "wake": str(wake.get("task_id") or ""),
                            "wake_at": str(wake.get("started_at") or ""),
                            "wake_state": wake_state,
                            "detail": str(row.get("detail") or "")[:200]})
    out["reason"] = (f"板上开着 {out['open']} 条收录义务"
                     + (f"（其中 {out['unowned']} 条负责人 unknown，等主控派人）"
                        if out["unowned"] else "")
                     + (f"；其中 {out['summoned']} 条已经召唤过 B" if out["summoned"] else "")
                     + (f"；{out['instance_addressed'] + out['role_addressed']} 条按地址"
                        "留在板上（不落召唤行，不是没叫醒）"
                        if (out["instance_addressed"] or out["role_addressed"]) else ""))
    return out


# ------------------------------------------------------------------ D 的递交义务（d-handoff@）
#
# 现场（真机 lp-ball-21，2026-11-24）：E 落了 19 条 conjecture（refuted 6 /
# supported_not_proved 6 / testing 7），D 的两次任务只做了 fs.list / table.list /
# research.list_gaps / propose_question / assess / submit_gaps —— 一次都没有把猜想递给 B。
# 结果 `statements` 60 条全是 concept（文献来源）、theorem 0 条 ⇒ B 无命题可证
# ⇒ `documents` 0。缺的不是"教"（`specs/d.py` 逐字写着"把这条猜想写清交给产出侧"
# 与"向 B 登记只递指针"），而是义务：猜想落成之后没有任何东西把"这一条还没递"
# 摆到 D 面前。
#
# 所以这一档与 `v-resubmit@` / `b-register@` 同形（同一个 `conductor.open_item`、
# 同一种"凭证据收口"，不靠 ack；不新造第二套板项）：
#
# - 幂等键 `d-handoff@<猜想号>`：不带收件人后缀、不带 sha（一条猜想只有一个"递交"动作，
#   同一条重复落行只该有一条义务）；
# - 触发：E 的 `run_experiment` 把猜想行落成 `status=supported_not_proved`（台账唯一
#   写点 `conjectureledger.register` 之后、事务之外那一刻，见
#   `agent_e.run_experiment` 的 [6]）；收工对账 `reconcile` 再扫一遍补开
#   （`sweep_handoffs` —— 漏开不许靠"下一次有人想起来"补）；
# - 收口三条（全是盘上的事实，不是回执）：
#   ① B 收录成功 —— `statements` 出现同文命题（规范化正文相同），`kind` 是
#      `theorem` / `conjecture` 且证据是数值那一档（第 1 位 `numeric=verified`，或
#      老行 `evidence_kind=cross_check`）；`b-register@` 那一项被消账也算；
#   ② 该猜想被 `refuted` / `withdrawn`（不再值得递交）⇒ `close="expired"`；
#   ③ 命题被明确放弃（`statementabandon.parse_abandon` 认得出的放弃标记）⇒ `expired`；
# - 负责人：角色是 D，地址取"这条猜想的产出来源的父"（产出那一趟 E 的
#   `parent_task_id`，只有它是 D 才认）；认不出就取那一刻唯一在飞的 D；再认不出
#   ⇒ `owner=""`、读数记 `unknown`（按角色地址落在板上）—— 不拿"谁醒着"当负责人。
# - 唤醒：开项走 `Conductor.open_item` 的同一条投递路（板项 + `_ensure_consumer`），
#   不在这里另造 clock / lifeline 逻辑。

#: 「把这条猜想递给 B」义务的幂等键前缀。与 `b-register@` / `v-resubmit@` 分开。
HANDOFF_PREFIX = "d-handoff@"

#: 这一条义务的负责人角色（递交是 D 的动作；收口是 B 的动作）。
HANDOFF_ROLE = "D"


def handoff_key(conjecture_id: Any) -> str:
    """「必须递交」义务的幂等键：`d-handoff@<猜想号>`。

    为什么键里只有猜想号：一条猜想的递交只有一个动作（"这一条有没有递给 B"），
    与 `b-register@` 的"哪一份正文"、`v-resubmit@` 的"哪一份被审正文"不同 ——
    猜想行本身没有 sha。同一条猜想重复落行（E 重跑支持性实验）落在同一个键上
    ⇒ 板上只有一条义务。
    """
    return f"{HANDOFF_PREFIX}{str(conjecture_id or '').strip()}"


def handoff_conjecture_of(key: Any) -> str:
    """从义务键里取回猜想号（认不出 ⇒ 空串，不猜）。"""
    raw = str(key or "")
    if not raw.startswith(HANDOFF_PREFIX):
        return ""
    return raw[len(HANDOFF_PREFIX):].split("@", 1)[0]


def _handoff_items(conductor: Any) -> list[dict[str, Any]]:
    """板上所有「必须递交」义务（读不成 ⇒ 空列表，由调用方的话说清）。

    与 `_register_items` 同一条纪律：没有 conductor / 读不成都是"读不到板"，
    由调用方记 `skipped` + 原因；这一格不冒充"板上没有这一条"这个结论。
    """
    if conductor is None:  # 未接板 ⇒ 没有可读的板项；由调用方写 skipped + reason
        return []
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001 —— 读不成不是"没有义务"
        return []
    return [r for r in rows if str(r.get("input_key") or "").startswith(HANDOFF_PREFIX)]


def _handoff_item_by_key(conductor: Any, key: str) -> dict[str, Any]:
    """板上有没有这一条（精确键；未接板 / 读不成 ⇒ 空字典，由调用方说清三态）。"""
    if conductor is None:  # 未接板 ⇒ 空字典是「读不到板」，由调用方记 skipped + reason
        return {}
    try:
        rows = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001
        return {}
    for row in rows:
        if str(row.get("input_key") or "") == str(key or ""):
            return row
    return {}


def _conjecture_row(store: Any, conjecture_id: str) -> dict[str, Any]:
    """按号取回猜想行（读不出来 / 没有 ⇒ 空字典，由调用方按三态处置）。"""
    if store is None or not str(conjecture_id or ""):
        return {}
    try:
        for row in store.rows("conjectures"):
            if str(row.get("conjecture_id") or "") == str(conjecture_id):
                return dict(row)
    except Exception:  # noqa: BLE001 —— 读不成不是"没有这一条"
        return {}
    return {}


def _norm_text(value: Any) -> str:
    """判重用的规范化正文：唯一实现是 `conjectureledger.norm_statement`，不抄第二份。

    为什么同一把尺：B 收录时写 `registered_stmt_id` 用的就是它；这里若另写一份
    去空白 / 标点的规则，"同一条命题"在两个号段上就会有两个答案。
    """
    from . import conjectureledger as _CL

    return _CL.norm_statement(value)


def _statements_reading(store: Any) -> tuple[list[dict[str, Any]], bool, str]:
    """一次读全 `statements` 表：`(rows, checked, why)`。

    三态纪律：读不出来 ⇒ `checked=False`，由调用方写成"这一格没查成"，
    不许折成"还没有这一行"（那会把一条还该开着的义务静默关掉）。
    """
    if store is None:
        return [], False, "没有 store ⇒ `statements` 读不出来（不是「还没有这一行」）"
    try:
        rows, problem, _error = SL.rows_of(store)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return [], False, f"`statements` 读不出来（{type(exc).__name__}: {exc}）"
    if problem:
        return [], False, str(problem)
    return [dict(r) for r in (rows or ())], True, ""


def _numeric_evidence_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一条 `statements` 行算不算"B 收录成功"（形状 + 数值证据）。

    判据（缺一不可）：`kind ∈ {theorem, conjecture}`，且证据是数值那一档 ——
    第 1 位 `numeric=verified`（`evidencebits` 的读口），或者老行没有 bits 时
    `evidence_kind=cross_check`（`numericproof.SUPPORTED_ONLY_KIND` 的口径）。
    纯文献来源的 `concept` 行不在此列：它不证明"这条猜想被收进了命题台账"。
    """
    from . import evidencebits as _EB

    out: dict[str, Any] = {"ok": False, "why": ""}
    kind = str(row.get("kind") or "")
    if kind not in ("theorem", "conjecture"):
        out["why"] = f"kind={kind!r} 不是 theorem / conjecture"
        return out
    try:
        bits = dict(_EB.bits_from_row(row) or {})
    except Exception:  # noqa: BLE001 —— bits 读不出来退回历史列，不在这里抛
        bits = {}
    if str(bits.get("numeric") or "") == "verified":
        out.update(ok=True, why="第 1 位 numeric=verified")
        return out
    if str(row.get("evidence_kind") or "") == "cross_check":
        out.update(ok=True, why="evidence_kind=cross_check（老行没有 bits 的读法）")
        return out
    out["why"] = (f"证据不是数值那一档（bits.numeric={bits.get('numeric')!r}，"
                  f"evidence_kind={row.get('evidence_kind')!r}）")
    return out


def _statement_abandoned(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一条 `statements` 行是不是"明确放弃"（可解析的放弃标记）。

    `status=abandoned` 且 `quote_reason` 是一条可解析的标记（理由与时间都在）
    才算；只写状态的行不算（与 `closing.statements_unsigned` 的
    `abandoned_without_reason` 同一把尺）。
    """
    from . import statementabandon as _SA

    out: dict[str, Any] = {"abandoned": False, "why": ""}
    if str(row.get("status") or "") != "abandoned":
        return out
    got = _SA.parse_abandon(row.get("quote_reason"))
    if not got.get("checked"):
        out["why"] = f"状态是 abandoned，但放弃标记读不出来（{got.get('why')}）"
        return out
    out.update(abandoned=True,
               why=f"已明确放弃（{got.get('at')}：{str(got.get('reason'))[:40]}）")
    return out


def _conjecture_producer_task(store: Any, row: Mapping[str, Any]) -> str:
    """这条猜想是哪一趟 E 产出的（`origin=experiment:<号>` ⇒ 实验行的 `owner_task`）。

    只认 E 的落点（`experiment:` 开头的 origin）：F 的稿命题 / B 的收录行不在这
    一档 —— 它们是"猜想台账的另外两个时刻"，没有"递给 B"这回事。
    """
    origin = str(row.get("origin") or "")
    if not origin.startswith("experiment:"):
        return ""
    eid = origin.split(":", 1)[1].strip()
    if not eid or store is None:
        return ""
    try:
        for one in store.rows("experiments"):
            if str(one.get("experiment_id") or "") == eid:
                return str(one.get("owner_task") or "")
    except Exception:  # noqa: BLE001 —— 读不成 ⇒ 认不出产出来源，由调用方记 unknown
        return ""
    return ""


def _conjecture_manuscript(store: Any, row: Mapping[str, Any]) -> str:
    """这条猜想可引用的 E 手稿路径（普通数值档优先，其次穷举证明稿）。

    为什么义务正文里要带它：`specs/d.py` 要求 D 递指针时"`proof_manuscript` 给这个
    路径 + `kind=conjecture`"—— 义务正文不点名那份稿，D 还得自己再找一遍。
    """
    origin = str(row.get("origin") or "")
    if not origin.startswith("experiment:"):
        return ""
    eid = origin.split(":", 1)[1].strip()
    if not eid or store is None:
        return ""
    try:
        rows = [dict(r) for r in store.rows("experiments")]
    except Exception:  # noqa: BLE001 —— 读不成 ⇒ 正文写"路径没读到"，不猜
        return ""
    for one in rows:
        if str(one.get("experiment_id") or "") != eid:
            continue
        obs = dict(one.get("observations") or {})
        for name in ("numeric_manuscript", "proof_manuscript"):
            raw = obs.get(name)
            if isinstance(raw, Mapping):
                path = str(raw.get("path") or "").strip()
            else:
                path = str(raw or "").strip()
            if path:
                return path
    return ""


def _row_instance_of(store: Any, role: str, row: Mapping[str, Any]) -> str:
    """这一行台账自己的实例地址（`tasks.instance` 那一格本身，不读调用上下文）。

    为什么不用 `_row_instance`：那一格走 `identity.resolve_identity`，而
    `resolve_identity` 会把当前调用上下文的实例标签当成候选（explicit 优先于
    `tasks.instance`）。递交义务是在 E 那一趟里开的 —— 那一刻上下文是 E 的实例，
    拿它去读"那个 D 是谁"，读回来的是 E 自己的标签（探针实测：owner_instance=E1）。
    板项地址必须来自被读的那一行，不许来自"谁正在说话"。
    """
    instance = str(row.get("instance") or "").strip()
    if instance:
        return instance
    return _row_instance(store, role, str(row.get("task_id") or ""))


def _live_row_of_instance(store: Any, role: str, instance: str) -> dict[str, Any]:
    """那个实例此刻在飞的台账号行（按 `tasks.instance` 本身比；没有 ⇒ 空字典）。"""
    from .conductor import UNFINISHED_STATUSES

    want = str(instance or "")
    if not want:
        return {}
    rows, _why = _role_rows(store, role)
    alive = [r for r in rows
             if str(r.get("status") or "") in UNFINISHED_STATUSES
             and str(r.get("instance") or "") == want]
    if not alive:
        return {}
    alive.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
    return dict(alive[-1])


def handoff_owner(*, store: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """这条递交义务该挂在哪个 D 名下（三档，不拿"谁醒着"当负责人）。

    次序（与模块那段注释逐字对应）：

    1. `producer_parent`：产出这条猜想的那一趟 E，它的 `parent_task_id` 是 D ⇒
       用那个 D 的实例地址（它在飞就同时给台账号；不在飞就按实例地址等它下一次起跑）；
    2. `in_flight_d`：父不是 D（例如 M 直接派了 E）⇒ 取那一刻唯一在飞的 D；
    3. `role`：一个 D 都认不出 / 有好几个在飞 ⇒ `owner=""`、`owner_known=False`，
       按角色地址落在板上（`d_handoff_reading` 的 `unowned` 数出来）。
    """
    from .conductor import UNFINISHED_STATUSES

    out: dict[str, Any] = {"owner": "", "owner_instance": "", "owner_known": False,
                           "owner_source": "", "owner_why": ""}
    producer = _conjecture_producer_task(store, row)
    parent_id = str(_task_row(store, producer).get("parent_task_id") or "") if producer else ""
    parent_row = _task_row(store, parent_id)
    if str(parent_row.get("role") or "") == HANDOFF_ROLE:
        instance = _row_instance_of(store, HANDOFF_ROLE, parent_row)
        live = _live_row_of_instance(store, HANDOFF_ROLE, instance)
        out.update(owner=str(live.get("task_id") or ""), owner_instance=instance,
                   owner_known=bool(instance), owner_source="producer_parent",
                   owner_why=(f"猜想由 {producer} 产出，它的父是 D 台账号 {parent_id}"
                              + (f"（实例 {instance}"
                                 + (f"，此刻在飞 {live.get('task_id')}" if live
                                    else "，此刻没有在飞的台账号 ⇒ 按实例地址等它")
                                 + "）" if instance
                                 else "（读不出实例标签 ⇒ 按角色地址）")))
        return out
    rows, why = _role_rows(store, HANDOFF_ROLE)
    live_rows = [r for r in rows if str(r.get("status") or "") in UNFINISHED_STATUSES]
    if len(live_rows) == 1:
        one = live_rows[0]
        tid = str(one.get("task_id") or "")
        instance = _row_instance_of(store, HANDOFF_ROLE, one)
        out.update(owner=tid, owner_instance=instance, owner_known=bool(instance),
                   owner_source="in_flight_d",
                   owner_why=(f"产出来源的父不是 D（{parent_id or '没有父'}）"
                              f"⇒ 那一刻唯一在飞的 D 是 {tid}"
                              + (f"（实例 {instance}）" if instance else "")))
        return out
    out.update(owner_source="role",
               owner_why=(f"产出来源的父不是 D（{parent_id or '没有父'}）"
                          + (f"，{why}" if why else "")
                          + f"，此刻在飞的 D 有 {len(live_rows)} 个 ⇒ 不挑"
                          "；这一条按角色地址落在板上，读数记 owner=unknown"))
    return out


def handoff_gap(*, store: Any, conjecture_id: str) -> dict[str, Any]:
    """这条递交义务还欠不欠（收口判据的唯一实现；纯读、不写任何东西）。

    返回 `{checked, gap, eligible, refuted, abandoned, statement_id, matched_by,
    manuscript, conjecture_status, reason}`：

    - `gap=False` + `refuted=True`：猜想被 `refuted` / `withdrawn` ⇒ 义务作废；
    - `gap=False` + `abandoned=True`：命题被明确放弃（可解析标记）⇒ 义务作废；
    - `gap=False` + `statement_id` 非空：B 收录成功（同文 + 数值证据；或 b-register 已消账）；
    - `gap=True` + `eligible=True`：还欠着，该有一条 `d-handoff@`；
    - `gap=True` + `eligible=False`：状态不是 `supported_not_proved`（例如 `testing`）——
      不新开，但也不凭空关掉已经开着的那一条（收口条件只有三条，见模块注释）；
    - `checked=False`：`conjectures` / `statements` 读不出来 ⇒ "没查成"，不折成"不欠"。
    """
    out: dict[str, Any] = {"checked": False, "gap": None, "eligible": False,
                           "refuted": False, "abandoned": False, "statement_id": "",
                           "matched_by": "", "manuscript": "",
                           "conjecture_status": "", "reason": ""}
    cid = str(conjecture_id or "").strip()
    if store is None:
        out["reason"] = "没有 store ⇒ 判不了这条义务还欠不欠（不是「不欠」）"
        return out
    row = _conjecture_row(store, cid)
    if not row:
        out["reason"] = (f"`conjectures` 里没有 {cid!r} 那一行 ⇒ 判不了"
                         "（不是「不欠」；这一格没查成）")
        return out
    out["checked"] = True
    status = str(row.get("status") or "")
    out["conjecture_status"] = status
    out["manuscript"] = _conjecture_manuscript(store, row)
    if status in ("refuted", "withdrawn"):
        out.update(gap=False, refuted=True,
                   reason=f"猜想 {cid} 已是 {status}（不再值得递交）")
        return out
    rows, checked, why = _statements_reading(store)
    if not checked:
        out.update(checked=False, reason=why + " ⇒ 这一格没查成")
        return out
    want = _norm_text(row.get("statement"))
    hit: dict[str, Any] = {}
    for one in rows:
        if not str(one.get("stmt_id") or ""):
            continue
        if _norm_text(one.get("statement_full")) == want:
            hit = dict(one)
            break
    if hit:
        sid = str(hit.get("stmt_id") or "")
        out["statement_id"] = sid
        abandoned = _statement_abandoned(hit)
        if abandoned.get("abandoned"):
            out.update(gap=False, abandoned=True, matched_by="statement",
                       reason=f"`statements` 的 {sid} {abandoned.get('why')} ⇒ 义务作废")
            return out
        evidence = _numeric_evidence_reading(hit)
        if evidence.get("ok"):
            out.update(gap=False, matched_by="statement",
                       reason=(f"`statements` 已有同文命题 {sid}"
                               f"（{evidence.get('why')}）⇒ B 收录成功"))
            return out
        out.update(gap=True, eligible=(status == "supported_not_proved"),
                   matched_by="statement",
                   reason=(f"`statements` 有同文命题 {sid}，但{evidence.get('why')}"
                           " ⇒ 不算收录成功"))
        return out
    # 同文命题一行都没有：再看 `b-register@` 那一侧有没有已经消账的（同一份正文）。
    settled = _settled_register_statement_ids(store, want=want, rows=rows)
    if settled:
        out.update(gap=False, matched_by="b-register", statement_id=settled[0],
                   reason=(f"`b-register@` 那一项已经凭证据消账（{settled[0]}）"
                           "⇒ 收录已经落成"))
        return out
    out.update(gap=True, eligible=(status == "supported_not_proved"),
               reason=(f"`statements` 里没有与猜想 {cid} 同文的命题"
                       + ("" if status == "supported_not_proved"
                          else f"（猜想状态是 {status}，不新开）")))
    return out


def _settled_register_statement_ids(store: Any, *, want: str,
                                    rows: Sequence[Mapping[str, Any]]
                                    ) -> list[str]:
    """已经凭证据消账的 `b-register@` 项里，正文与这条猜想相同的命题号。

    为什么还要对一遍正文：`b-register@` 的键里只有命题号与 sha，板上可能有一条
    别人的收录义务刚刚消账 —— 拿"板上有任何一条消账的 b-register"当"这一条被收录了"，
    会把一条还欠着的递交义务静默关掉。纯读；未接板 / 读不成 ⇒ 空列表（调用方
    按"没有这一条证据"处置，不会因此关项）。
    """
    conductor = _conductor(store)
    if conductor is None:  # 未接板 ⇒ 这一档读不到；空列表由调用方在 reason 里说清
        return []
    by_id = {str(row.get("stmt_id") or ""): dict(row) for row in rows}
    out: list[str] = []
    for item in _register_items(conductor):
        if str(item.get("item_state") or "") != "done":
            continue
        num = str(item.get("input_key") or "")[len(REGISTER_PREFIX):].partition("@")[0]
        hit = by_id.get(num) or {}
        if hit and _norm_text(hit.get("statement_full")) == want:
            out.append(num)
    return out


def _handoff_body(*, row: Mapping[str, Any], manuscript: str, at: str = ""
                  ) -> tuple[str, str]:
    """这一条义务的一句话摘要 + 正文（上限 = `agent_loop.BOARD_DETAIL_CHARS`，480 字）。

    正文要把 D 该做的那一笔写全（递给谁、怎么递、引哪一份稿）—— 与 `specs/d.py`
    的"向 B 登记只递指针"同一口径；收口条件两条都写出来，否则 D 只看见"要交"，
    看不见"交完之后它自己会消失"。
    """
    from .agent_loop import BOARD_DETAIL_CHARS

    cid = str(row.get("conjecture_id") or "")
    origin = str(row.get("origin") or "")
    eid = origin.split(":", 1)[1].strip() if origin.startswith("experiment:") else ""
    summary = f"待递交：猜想 {cid}（E 有数值支持、还没有递给 B）"
    body = (
        f"这是一条必须递交的义务，不是通知：E 的实验 exp:{eid or '（没读到）'}"
        f" 已经把猜想 {cid} 落成「有支持但未证明」（supported_not_proved，"
        f"落于 {at or '时刻没读到'}），而 `statements` 里还没有它。\n"
        "要交的那一笔：把这条猜想递给 B —— `register_statement` 只递指针："
        f"`proof_manuscript` 给 {manuscript or 'E 的数值手稿（路径没读到，按实验号找）'}"
        "、`kind=conjecture`、出处给 `exp:<实验号>`；命题正文 / 证明正文都由 B 从那份稿里读。\n"
        "收口条件（任一即由框架自动收口，不靠 ack）：① B 收录成功（`statements` 出现同文命题，"
        "kind=theorem|conjecture 且证据是数值那一档）；② 这条猜想被 refuted / withdrawn"
        "（届时这一项作废）。退回一句「知道了」不会让它消失。"
    )
    return summary, body[:int(BOARD_DETAIL_CHARS)]


def ensure_handoff(*, store: Any, row: Mapping[str, Any], at: str = "") -> dict[str, Any]:
    """E 落一条猜想那一刻：该开就开一条 `d-handoff@<号>`（幂等；已清了就收口）。

    返回 `{checked,state,key,item_id,owner,owner_instance,owner_known,owner_source,
    owner_why,reason,problems}`，`state` 取：

    - `opened`：新开了一条；
    - `existing`：同键的项已经在板上（不重开 —— 幂等的落点）；
    - `closed` / `expired`：板上那条原本开着，但盘上的事实已经让义务没了
      （B 收录成功 / 猜想被 refuted / 命题被放弃）⇒ 按证据收口；
    - `cleared`：盘上已经清了、板上也没有开着的（历史补投走这一支）；
    - `ineligible`：状态不是 `supported_not_proved` ⇒ 不新开（也不关已开的）；
    - `skipped`：没有 conductor / 台账读不成；
    - `error`：开项抛了（`problems` 里带原话），不带走这一趟实验。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "owner": "", "owner_instance": "", "owner_known": False,
                           "owner_source": "", "owner_why": "", "reason": "",
                           "problems": []}
    cid = str((row or {}).get("conjecture_id") or "").strip()
    if not cid:
        out.update(state="skipped",
                   reason="这一行没有猜想号 ⇒ 做不出幂等键（不猜）")
        return out
    key = handoff_key(cid)
    out["key"] = key
    conductor = _conductor(store)
    item = _handoff_item_by_key(conductor, key)
    gap = handoff_gap(store=store, conjecture_id=cid)
    if not gap.get("checked"):
        out.update(state="skipped",
                   reason=(f"{gap.get('reason')}；不拿'读不出来'当'已经递过了'"
                           "去开一条待办"))
        out["problems"].append(str(gap.get("reason") or "递交状态读不成"))
        return out
    if not gap.get("gap"):
        if item and conductor is not None and str(item.get("item_state") or "") != "done":
            close = "expired" if (gap.get("refuted") or gap.get("abandoned")) else "completed"
            _state, why = conductor.close_item_by_evidence(
                str(item.get("task_id") or ""), close=close,
                why=f"义务已清：{gap.get('reason')}")
            if why:
                out["problems"].append(why)
            out.update(checked=True, item_id=str(item.get("task_id") or ""),
                       state=("expired" if close == "expired" else "closed"),
                       reason=str(gap.get("reason") or "义务已清"))
            return out
        out.update(checked=True, item_id=str((item or {}).get("task_id") or ""),
                   state="cleared", reason=str(gap.get("reason") or "义务已清"))
        return out
    if not gap.get("eligible"):
        out.update(checked=True,
                   item_id=str((item or {}).get("task_id") or ""),
                   state=("existing" if item else "ineligible"),
                   reason=str(gap.get("reason") or "状态不是 supported_not_proved ⇒ 不新开"))
        return out
    if item:
        out.update(checked=True, item_id=str(item.get("task_id") or ""),
                   owner=str(item.get("parent_task_id") or ""),
                   owner_instance=str(item.get("instance") or ""),
                   owner_known=bool(item.get("instance") or item.get("parent_task_id")),
                   owner_source="board_row",
                   state=("closed" if str(item.get("item_state") or "") == "done"
                          else "existing"),
                   reason=(f"同键的板项已存在（{item.get('task_id')}，"
                           f"item_state={item.get('item_state')}）⇒ 不重开"))
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason=("这一趟没有 conductor ⇒ 板项开不了（义务不落盘 = 没人会看到；"
                           "不是「已经递过了」）"))
        return out
    owner = handoff_owner(store=store, row=row)
    out.update(owner=str(owner.get("owner") or ""),
               owner_instance=str(owner.get("owner_instance") or ""),
               owner_known=bool(owner.get("owner_known")),
               owner_source=str(owner.get("owner_source") or ""),
               owner_why=str(owner.get("owner_why") or ""))
    if out["owner"]:
        item_depth = max(1, int(_task_row(store, out["owner"]).get("depth") or 1)) + 1
    else:
        item_depth = 1
    summary, body = _handoff_body(row=row,
                                  manuscript=str(gap.get("manuscript") or ""), at=at)
    try:
        item_id = conductor.open_item(
            kind="notice", role=HANDOFF_ROLE, expects="work", action="notice",
            summary=summary, called_by="E", parent_task_id=(out["owner"] or None),
            depth=item_depth, input_key=key,
            recipient_instance=str(out["owner_instance"] or ""))
        conductor.set_item_detail(item_id, body)
    except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走这一趟实验
        out.update(state="error", reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
        return out
    out.update(checked=True, state="opened", item_id=item_id,
               reason=(f"新开「待递交」义务 {item_id}"
                       + (f"（收件实例 {out['owner_instance']}"
                          + (f"，在飞台账号 {out['owner']}" if out["owner"] else "，此刻不在飞")
                          + "）" if out["owner_instance"]
                          else "（没有可判定的负责人 ⇒ 按角色地址，由 D 的实例领取）")))
    return out


def settle_handoff(*, store: Any, stmt_id: str = "") -> dict[str, Any]:
    """把板上开着的 `d-handoff@` 按盘上的事实收口（B 收录那一刻 / 收工对账共用）。

    为什么需要这一格：收录成功发生在 B 的写口里，而那一层不认识板项；收工对账
    在本链里不一定跑（真机 RED11 的现场）。所以 B 收录落成那一刻也调它一次
    （`agent_b.ingest_manuscript._settle_registration_duty` 的两个出口都过那里），
    收工时 `reconcile` 再调一次 —— 两处同一份判据，idempotent。

    `stmt_id` 只进读数（"这一笔收录是哪一个号"），收口判据不依赖它：同文命题
    在 `statements` 里出现这件事本身就是证据。

    三态：没有 conductor / 台账读不成 ⇒ `checked=False`（不是"没有要收口的"）。
    """
    out: dict[str, Any] = {"checked": False, "stmt_id": str(stmt_id or ""),
                           "closed": [], "expired": [], "left": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有要收口的义务」）"
        return out
    out["checked"] = True
    for item in _handoff_items(conductor):
        if str(item.get("item_state") or "") == "done":
            continue
        key = str(item.get("input_key") or "")
        cid = handoff_conjecture_of(key)
        gap = handoff_gap(store=store, conjecture_id=cid)
        if not gap.get("checked"):
            out["left"].append({"key": key, "why": str(gap.get("reason") or "查不成")})
            continue
        if gap.get("gap"):
            out["left"].append({"key": key,
                                "why": f"义务还在（{gap.get('reason')}）"})
            continue
        close = "expired" if (gap.get("refuted") or gap.get("abandoned")) else "completed"
        _state, problem = conductor.close_item_by_evidence(
            str(item.get("task_id") or ""), close=close,
            why=f"义务已清：{gap.get('reason')}")
        if problem:
            out["problems"].append(f"{item.get('task_id')}：{problem}")
            continue
        if close == "expired":
            out["expired"].append(str(item.get("task_id") or ""))
        else:
            out["closed"].append(str(item.get("task_id") or ""))
    out["reason"] = (f"收口 {len(out['closed'])} 条、作废 {len(out['expired'])} 条，"
                     f"仍开着 {len(out['left'])} 条"
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out


def sweep_handoffs(*, store: Any, limit: int = 50) -> dict[str, Any]:
    """扫一遍 `conjectures`：`supported_not_proved` 且还没有义务的 ⇒ 逐条补开（幂等）。

    为什么还要扫盘（E 落账那一刻已经会开一条）：义务不能只依赖"落账那一路跑到了"——
    病根正是"没有任何东西把这件事摆到 D 面前"。这一趟是收工前的看门：谁漏开
    （例如那一趟没有 conductor）都在这里被数一遍、补一条。

    范围只认 E 的落点（`origin=experiment:`）：F 的稿命题 / B 的收录行没有
    "递给 B"这回事，纯文献来源的 concept 行也不在此列。
    """
    out: dict[str, Any] = {"checked": False, "scanned": 0, "opened": [], "existing": [],
                           "closed": [], "expired": [], "cleared": [], "skipped": [],
                           "problems": [], "reason": ""}
    if store is None:
        out["reason"] = "没有 store ⇒ 这一格没查成（不是「没有漏开的义务」）"
        return out
    try:
        rows = [dict(r) for r in store.rows("conjectures")]
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        out["reason"] = (f"`conjectures` 读不出来（{type(exc).__name__}: {exc}）"
                         "⇒ 这一格没查成")
        return out
    out["checked"] = True
    for row in rows:
        if not str(row.get("origin") or "").startswith("experiment:"):
            continue
        if str(row.get("status") or "") != "supported_not_proved":
            continue
        if len(out["opened"]) + len(out["existing"]) >= max(1, int(limit)):
            out["skipped"].append({"conjecture_id": str(row.get("conjecture_id") or ""),
                                   "why": f"到了一次扫盘的上限 {int(limit)} 条"})
            break
        out["scanned"] += 1
        got = ensure_handoff(store=store, row=row)
        out["problems"].extend(str(x) for x in (got.get("problems") or []))
        state = str(got.get("state") or "")
        if state in ("opened", "existing", "closed", "expired", "cleared"):
            out[state].append(str(got.get("item_id") or ""))
        else:
            out["skipped"].append({"conjecture_id": str(row.get("conjecture_id") or ""),
                                   "why": str(got.get("reason") or "这一条没开成")})
    out["reason"] = (f"扫到 {out['scanned']} 条有数值支持的猜想："
                     f"新开 {len(out['opened'])} 条、已在板上 {len(out['existing'])} 条、"
                     f"顺手收口 {len(out['closed']) + len(out['cleared'])} 条、"
                     f"作废 {len(out['expired'])} 条、跳过 {len(out['skipped'])} 条"
                     + (f"；{len(out['problems'])} 条没办成" if out["problems"] else ""))
    return out


def d_handoff_reading(store: Any = None) -> dict[str, Any]:
    """「待递交」义务的一眼读数：开着的 / 负责人认不出的 / 逐条明细。

    读者是主控（挂在收工门的 `readings.v_obligations.d_handoff_reading` 上），
    它不要求主控多做一步：这一格只回答"还有几条没递、每一条挂在谁名下、卡在哪"。

    三态：没有 conductor / 板项读不出来 ⇒ `checked=False` + 理由
    （"没查成"不是"没有待递交"）。
    """
    out: dict[str, Any] = {"checked": False, "open": 0, "unowned": 0, "rows": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有待递交义务」）"
        return out
    out["checked"] = True
    for row in _handoff_items(conductor):
        if str(row.get("item_state") or "") == "done":
            continue
        key = str(row.get("input_key") or "")
        cid = handoff_conjecture_of(key)
        owner = str(row.get("parent_task_id") or "")
        instance = str(row.get("instance") or "")
        gap = handoff_gap(store=store, conjecture_id=cid)
        out["open"] += 1
        if not owner and not instance:
            out["unowned"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""), "key": key,
                            "conjecture_id": cid,
                            "owner": owner or "unknown", "owner_instance": instance,
                            "item_state": str(row.get("item_state") or ""),
                            "role": str(row.get("role") or ""),
                            "gap": gap.get("gap"),
                            "eligible": bool(gap.get("eligible")),
                            "statement_id": str(gap.get("statement_id") or ""),
                            "why": str(gap.get("reason") or ""),
                            "detail": str(row.get("detail") or "")[:200]})
    out["reason"] = (f"板上开着 {out['open']} 条待递交义务"
                     + (f"（其中 {out['unowned']} 条 owner=unknown，等主控派人）"
                        if out["unowned"] else ""))
    return out


def _prefix() -> str:
    from .agent_loop import V_VERDICT_ITEM_PREFIX

    return V_VERDICT_ITEM_PREFIX


def _root_of(store: Any, fallback: Any = "") -> str:
    got = getattr(store, "root", None) or fallback
    return str(got or "")


# ------------------------------------------------------------------ 键与明细


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

    取开义务要用的格：`verification_id` / `proof_sha256` / `defect_step` /
    `requires_rewrite`，以及这一签盖在哪份稿上（`manuscript`，K9：收件人 = 该稿的
    产出实例，而这一格就是那个事实的第一手来源 —— 判词行记着它审的是哪份稿）。
    正文里的措辞由 :func:`_resubmit_body` 现拼，不从别处抄一份。
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
    manuscript = str(sign.get("manuscript") or sign.get("object_path") or "").strip()
    return {"verification_id": str(verification_id or ""),
            "proof_sha256": str(sign.get("proof_sha256") or ""),
            "defect_step": step if isinstance(step, int) else None,
            "requires_rewrite": not report,
            "manuscript": manuscript.replace("\\", "/")}


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
                           "registration_reconcile": {}, "d_handoff": {},
                           "d_handoff_settle": {}, "d_handoff_reading": {},
                           "problems": [], "reason": ""}
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
                # 送审者不可判不再等于「这条义务开不了」：收件人首先是这份稿的产出
                # 实例（`ensure_resubmit` 自己会读）。这里只把那一格记成读数。
                why = str(who.get("reason") or "送审者不可判")
        rs = ensure_resubmit(store=store, root=root, label=label, verification_id=vid,
                             detail=detail, recipient=recipient, role=role,
                             depth=depth, at=at)
        out["resubmit"].append({"label": label, "verification_id": vid, "why": why, **rs})
        out["problems"].extend(str(x) for x in (rs.get("problems") or []))
        if rs.get("state") == "opened":
            out["opened"].append(str(rs.get("item_id") or ""))
        elif rs.get("state") in ("unowned", "skipped", "error"):
            out["left"].append({"label": label, "verification_id": vid,
                                "why": str(rs.get("reason") or "这一条没开成")})
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
    # ④ 递交义务（D 侧）：先扫盘补开（`sweep_handoffs`），再按盘上的事实收口
    #    （`settle_handoff`），最后给一眼读数。读数挂在这里 ⇒ 它随
    #    `conductor.closing` 的 `readings.v_obligations` 出现在主控眼前，不需要主控
    #    多做一步（也不新增工具、不动工具面 golden）。
    try:
        out["d_handoff"] = sweep_handoffs(store=store)
    except Exception as exc:  # noqa: BLE001 —— 扫盘没跑成不许带走收工读数
        out["d_handoff"] = {"checked": False, "scanned": 0, "opened": [], "existing": [],
                            "closed": [], "expired": [], "cleared": [], "skipped": [],
                            "problems": [],
                            "reason": f"扫盘没跑成（{type(exc).__name__}: {exc}）"}
    try:
        out["d_handoff_settle"] = settle_handoff(store=store)
    except Exception as exc:  # noqa: BLE001
        out["d_handoff_settle"] = {
            "checked": False, "closed": [], "expired": [], "left": [], "problems": [],
            "reason": f"对账没跑成（{type(exc).__name__}: {exc}）"}
    try:
        out["d_handoff_reading"] = d_handoff_reading(store)
    except Exception as exc:  # noqa: BLE001
        out["d_handoff_reading"] = {
            "checked": False, "open": 0, "unowned": 0, "rows": [], "problems": [],
            "reason": f"读数没跑成（{type(exc).__name__}: {exc}）"}
    out["reason"] = (f"打回 {out['receipts']} 条；补开重送项 {len(out['opened'])} 条、"
                     f"认不出送审者 {len(out['left'])} 条；"
                     f"{str(out['resubmit_reconcile'].get('reason') or '')}；"
                     f"{str(out['registration'].get('reason') or '')}；"
                     f"{str(out['registration_reconcile'].get('reason') or '')}；"
                     f"{str(out['d_handoff'].get('reason') or '')}；"
                     f"{str(out['d_handoff_settle'].get('reason') or '')}")
    return out
