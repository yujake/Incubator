# -*- coding: utf-8 -*-
"""V 回执的投递：先落意图，再开板项（业主 2026-11-01 裁定 · 167 的丙案）。

## 这一层治的是什么（81 的真机读数）

V 判「有毛病」的 8 条回执里只有 4 条到了收件人手上。根因不在"投递函数写错了"，而在
投递发生在收件人下一次起跑那一刻（`agent_loop.deliver_v_verdicts` 的唯一调用点是
`AgentLoop.run` 的 F 分支）：F 03:54 之后再没起跑，后 4 条（04:05–04:14）连板项都没开。
于是"送到"成了"收件人醒着"的副产品 —— 收件人不醒，回执就不存在。

## 两层，两件事（别把它们折平）

| 层 | 回答的问题 | 落点 |
|---|---|---|
| 甲：判定即投 | 这一条判定投出去了没有 | 本模块（outbox + 板项），由 V 在 `record_verification` 之后调 |
| 乙：收工前补投 | 有没有漏投的判定 | 本模块 `backfill`，由 `conductor.closing` 在门读数算完之后调 |

`dispatched`（有板项）与 `delivered`（收件人真的读过：`item_close=="acked"` +
`agent_mailbox` 的 `seen_by`/`seen_step`）是两个数，读数分别给。把它们折成一个
"未送达"会让"没人投"与"投了没人读"同形 —— 那正是 81 之前那一版读数的毛病。

## 收件人 = 送审者（业主裁定，不是"谁先醒来"）

`deliver_v_verdicts` 原来把判决投给"下一次起跑的 F"。81 的取证把这条打掉了：8 条判定
全部由 B 召唤的 V 跑产出，却被投给了两次与它们无关的 F 跑 —— 收件人是按"谁先
醒来"算的，不是按"谁送的审"算的。

现在的收件人只有一个来源：`conductor.current_parent()` —— 这一趟工具调用所属的那次
召唤的父（`AgentLoop._resolve_parent` 在 `calling_as` 里挂上来的，与 `escalate` 读的是
同一格）。读不到就记 `undelivered`，不猜（"谁醒着"不是收件人的证据）。

## 顺序：意图先落盘，再开板项（崩溃不丢）

```text
① 追加 outbox 意图（pending，含 label / vid / recipient / at）
② 开板项（走既有 `deliver_v_verdicts`，幂等键 = v-verdict@<label>@<vid>@<recipient>）
③ 追加 dispatched（记 item_id）或 undelivered（记原因）
```

崩在 ① 与 ② 之间 ⇒ 盘上留着一条 `pending` 意图，`backfill` 会把它补上；崩在 ② 与 ③
之间 ⇒ 板项已经在（`deliver_v_verdicts` 读板去重），补投只会走"已在板上"那一支，
不会多开。两种崩溃都不丢，也不会重复开项。

## 并发（两个负控钉住的正是这里）

幂等原来靠"先读板、再开项"，两个投递者同时拿到一份"还没有这一条"的板快照就会各开
一项（实测：同键 2 行）。本模块把整段 ①→③ 放进同一把跨进程锁（`filelock`）里，
于是第二个投递者看到的是第一个已写下的 `dispatched`，直接返回 `existing`。
`tasks.input_key` 仍然没有唯一约束（那要动 `schema.py`，是禁改区）—— 所以这条锁是
唯一的并发保证，改动本模块时不许把 `deliver_v_verdicts` 的调用挪到锁外面。

## 三态（"没查成"不是"没送到"）

- 有 conductor、开了项 ⇒ `dispatched`；
- 没有 conductor / 开项抛异常 / 明细造不出来 ⇒ `pending`（留给 `backfill` 重试），
  不是 `undelivered` —— 它还能成；
- 读不到送审者（`current_parent` 空 / 台账里没有那一行）⇒ `undelivered`（终态：不猜），
  但 `backfill` 仍会用"台账号时间窗唯一"重解析一次（见 :func:`resolve_recipient`）。

## 历史判定（本笔之前的 8 条）

81 那 8 条是在本笔之前判的：盘上没有 outbox 意图，也就没有"送审者"这一格。
`backfill` 对它们走 :func:`resolve_recipient`：只有那一拍恰好只有一趟 V 在跑时才认
（时间窗来自 `tasks` 的 `started_at`/`ended_at`）；两趟以上在跑 = 不可判 = `undelivered`。
81 的后 4 条恰好满足（04:05–04:14 只有 t-000206 / t-000213 在跑）⇒ 补投能落地；前 4 条
本来就已经送达，不需要解析。
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from filelock import FileLock, Timeout

from . import schema as _S
from . import statementledger as SL   # 命题台账的查口（按号 / 按关键词，只读、零模型）

#: 落点目录（`out/` 下，与 `out/vsigns/` 平级）：这是"回执投递"的账，不是签的账。
OUTBOX_DIR = "vreceipts"

#: 意图账的文件名。
OUTBOX_NAME = "outbox.jsonl"

#: 跨进程锁（与 `filelock` 的 OS 锁配合；进程内再加一把线程锁，见 `_lock`）。
LOCK_NAME = ".lock"

#: 行的 `kind`（append-only 的每一行都带它，读的人据此过滤）。
KIND = "v-receipt-intent"

PENDING = "pending"
DISPATCHED = "dispatched"
UNDELIVERED = "undelivered"

# ------------------------------------------------------------------ 重送义务（I2）
#
# 业主 2026-11-01 的裁定把"打回"变成了两种东西：一条回执（已送到），以及一条
# 必须重送的义务。改前只有前者 —— 82 的真机读数说得很直白：8 条 V 判决回执全部
# dispatched，其中 t-000022(000001) 与 t-000027(000002) 甚至已经 acked/done，而这两条
# 命题至今没有 V 签；同一批判决还被重复投给后来的 F 台账号（t-000082/083/089/090
# 全 seen）。"知道了"（ack）与"改完了"（新的成立行）是两件事，而只有后者能关掉
# 一条重送义务。
#
# 所以这一档单独立一条板项（复用 `conductor.open_item` / `set_item_detail`，
# 不新造第二套板项）：
#   · 幂等键 `v-resubmit@<命题号>@<proof_sha256>`：不带收件人后缀。带后缀的键会
#     为每一次 F 起跑各开一条 —— 82 那四条重复项（t-000082/089/090 + 原项）就是
#     后缀的后果；
#   · 负责人 = 那一次送审的送审者（`outbox` 里的 recipient/submitter）。取不到就记
#     `owner="unknown"`，由收工读数 `statements_unsigned` 的 `owner_known` 说清楚
#     （"记 unknown 并进收工读数"），不拿"谁醒着"当负责人；
#   · 关闭条件 = 同一命题出现更新的干净「成立」行（`settle_resubmitted`），不是 ack：
#     `expects="work"` ⇒ 收口只能是 `completed` / `expired`（`schema.Task.validate`
#     的交叉校验），拿到"知道了"什么也关不掉；
#   · 放弃原命题时这一项同时作废（`close_resubmits_for`，`close="expired"`）——
#     否则"放弃"这条出口会被"名下还有未消的板项"反锁住（`retire_integrity`）。

#: 重送义务板项的幂等键前缀（I2）。与 `v-verdict@` 分开：后者是回执，前者是义务。
RESUBMIT_PREFIX = "v-resubmit@"


def resubmit_key(label: str, proof_sha: str) -> str:
    """重送义务的幂等键：`v-resubmit@<命题号>@<proof_sha256>`。

    为什么键里是 sha 而不是 proof 编号：sha 是"哪一份正文"的指纹（业主 2026-10-22
    的多证明模型里，同一命题下 #p1/#p2 各自独立）；换了 sha 就是另一份正文，
    该开新的义务。刻意不带收件人后缀（见上面那一段）。
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
    """这个 sha 属于第几份证明（从台账行反查；认不出 ⇒ `None`）。

    为什么不从 statements 行现算：F 改过稿之后，旧 sha 已经不在现行正文里了
    （真机 000006：20:42 打回的是 f6e…，20:50 重送的是 2203…）。台账是追加式的，
    它记得那份旧正文属于哪个证明号 —— 那正是"关闭条件按证明号匹配"要的东西。
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
    # ---- 2026-11-06（业主裁定 3）：作废行不许清义务 ---------------------------
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
      （历史补投会走到这一支：81/82 的旧判决不该在收工时凭空长出一条待办）；
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
    "成立"仍然是一次打回 —— 82 的 000001/000006 就是这一档）。收口方式
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
# 真机 `projects/paper-rewrite-87` 2026-11-05 现场：
#
# ```text
# reports/f-proof-000000.md 有 `secretary:F` 的成立签块；b-proof-000000/2/3 也已落盘。
# 而 statements:000000 仍是 ek=heuristic / 正文=0 / reviewed=false —— 没人登记。
# ```
#
# 盘上核过的根因：87 里 B 只被派过 1 次（`t-000027`，called_by=A，文献侧），D 从头没派 B
# 收录。教学里其实有那条（`specs/d.py`：「② 那一行写进你的报告之后派 B 入库」），
# D 没走到 ⇒ 缺的不是"教"，是义务：签发之后没有任何东西把"这一份还没入库"摆到 B 面前。
#
# 所以这一档与 `v-resubmit@` 同形（同一个 `conductor.open_item`、同一种"凭证据收口"，
# 不靠 ack）：
#
# - 幂等键 `b-register@<命题号>@<被签正文的 sha>`：不带收件人后缀（同一命题的同一份
#   正文只该有一条义务；重判只刷签块，不重开这条）；
# - 触发：一份 `reports/{f,b}-proof-<号>.md` 上有成立的签块，而 `statements` 对应行
#   拿不出"正文 + reviewed=true"（签发那一刻由 `_vsigns_write_after_flip` 开；收工前
#   由 :func:`sweep_registrations` 补开 —— 漏开不许靠"下一次有人想起来"补）；
# - 收口只有一条：那一行出现正文 且 `reviewed=true`（逐份口径，`#p2` 不借 `#p1` 的
#   光）；另一条明确出口是"明确不收录并给理由"—— 它落在既有载体上：命题被标成
#   `abandoned` 且 `quote_reason` 是一条可解析的放弃标记（`statementabandon.parse_abandon`
#   的同一份判据，理由与时间缺一不可），届时这一项作废 `expired`；
# - 负责人：这一条只有"角色"（B），没有"事实上的收件人"。所以不猜：调用方给了台账号
#   就用；没给就认那一刻唯一在飞的 B 台账号（0 或 ≥2 ⇒ 不认）；一个都认不出时
#   `owner=""` 而照样开项（与 `v-resubmit` 的 `unowned` 不开项不同：那一条的负责人是
#   事实"谁送审"，猜不得；这一条的责任是角色 B，项本身必须存在 —— 它由 `board_view`
#   亮给主控去派，且父为空的项不挂在任何人的销号闸上）。

#: 「签了但没人收录」义务的幂等键前缀（缺陷 B，2026-11-05）。与 `v-resubmit@` 分开。
REGISTER_PREFIX = "b-register@"

#: 这一条义务认的载体（业主 2026-11-05 逐字：`reports/f-proof-<号>.md` 或
#: `b-proof-<号>.md`）。E 的穷举证据稿不在这一档（它走 `bits.proof` 那条通道）。
REGISTRATION_CARRIERS: tuple[str, ...] = ("reports/f-proof-", "reports/b-proof-")

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


def registration_gap(*, store: Any, label: str, proof_sha: str = "",
                     manuscript: str = "") -> dict[str, Any]:
    """这一份签过的正文入库了没有（收口判据的唯一实现；纯读、不写任何东西）。

    判据（缺一不可）：`statements` 那一行拿得出这一份证明的正文，且那一份被
    `reviewed=true`（`bits.evidence.reviewed_by_proof` 的逐份表优先）。两条都齐 ⇒
    `gap=False`（义务已清）；否则 `gap=True`（义务还在）。

    「明确不收录并给理由」那一档：`status="abandoned"` 且 `quote_reason` 是一条可解析的
    放弃标记（理由与时间都在）⇒ `abandoned=True, gap=False`（义务作废，不是"收录了"）。
    只写 `status=abandoned` 而没有可解析标记 ⇒ 不算明确不收录，`gap` 仍为真
    （与 `closing.statements_unsigned` 的 `abandoned_without_reason` 同一把尺）。

    三态：`checked=False` 只在 `statements` 读不出来 / 没给 store 时出现 ——
    它说的是"这一格没查成"，不许折成"已经收录了"。

    返回键：`checked` / `gap` / `abandoned` / `body` / `reviewed` / `status` /
    `statement_id` / `proof_no` / `manuscript` / `reviewed_why` / `reason`。
    """
    from . import statementabandon as _SA

    sid, no = _label_parts(label)
    out: dict[str, Any] = {"checked": False, "gap": None, "abandoned": False,
                           "body": False, "reviewed": False, "status": "",
                           "statement_id": sid, "proof_no": no,
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
    row = by_id["row"] if by_id["found"] else None
    out["checked"] = True
    if row is None:
        out.update(gap=True,
                   reason=(f"`statements` 里没有命题 {sid} 那一行 ⇒ 这一份签还没有被收录"
                           "（先要 B 把它登记进册）"))
        return out
    out["status"] = str(row.get("status") or "")
    if out["status"] == "abandoned":
        parsed = _SA.parse_abandon(row.get("quote_reason"))
        if parsed.get("checked"):
            out.update(gap=False, abandoned=True,
                       reason=(f"命题 {sid} 已被明确放弃（{parsed.get('at')}："
                               f"{parsed.get('reason')}）⇒ 明确不收录，义务作废"))
            return out
        out.update(gap=True,
                   reason=(f"命题 {sid} 写着 status=abandoned，而放弃标记读不出来"
                           f"（{parsed.get('why')}）⇒ 不算明确不收录（义务仍在）"))
        return out
    out["body"] = _proof_body_present(row, no)
    out["reviewed"] = _proof_reviewed(row, no)
    if out["body"] and out["reviewed"]:
        out.update(gap=False,
                   reason=(f"{sid}#p{no} 已经入库（有正文、reviewed=true）⇒ 义务已清"))
        return out
    out["gap"] = True
    out["reviewed_why"] = ("正文在" if out["body"] else "正文是空的")
    out["reviewed_why"] += ("、reviewed=true" if out["reviewed"] else "、reviewed 不是 true")
    out["reason"] = (f"{sid}#p{no} 还没入库（{out['reviewed_why']}）"
                     f"⇒ 这一份稿的签没有任何人登记过")
    return out


def _register_body(*, label: str, detail: Mapping[str, Any], manuscript: str,
                   at: str = "") -> tuple[str, str]:
    """这一条义务的一句话摘要 + 正文（上限 = `agent_loop.BOARD_DETAIL_CHARS`，480 字）。

    为什么上限不在这里另拍一个数（2026-11-05，业主裁定「同一笔做」）：改前这里是
    `body[:400]`，而完整正文 462 字 ⇒ 第 ② 条「明确放弃 + 理由与时间」在进板之前
    就被切掉了（存进 `tasks.detail` 的结尾是"…；② 确"）。渲染层再怎么调都读不回来 ——
    写入侧定"存多少"，渲染侧定"念多少"，念的那个不许小于存的；两层共用一个常量，
    这条缝才在结构上不存在（`agent_loop.BOARD_DETAIL_CHARS` 的注释里写着 480 的实测依据）。
    """
    from .agent_loop import BOARD_DETAIL_CHARS

    sid = str(detail.get("statement_id") or label.split("#", 1)[0])
    no = int(detail.get("proof_no") or 1)
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


def ensure_registration(*, store: Any, root: str | Path, label: str, proof_sha: str,
                        manuscript: str = "", owner: str = "", called_by: str = "V",
                        depth: int = 1, at: str = "", skip_gap: bool = False) -> dict[str, Any]:
    """开一条「必须收录」义务项（幂等；已清掉的不开，已收口的收口）。

    返回 `{"checked","state","key","item_id","owner","owner_known","reason","problems"}`，
    `state` 取：`opened` / `existing` / `closed`（板上那条已经 done）/ `cleared`（盘上
    已经入库 ⇒ 义务本来就没了，顺手把板上那条按证据收口）/ `expired`（命题已被明确放弃）/
    `skipped`（没有 conductor / 查不成 / 做不出幂等键）/ `error`（开项抛了）。

    `owner`：给了就用；没给就认那一刻唯一的 B 台账号；一个都认不出 ⇒ `owner=""` 而
    照样开项（`owner_known=False`，由 `registration_digest` 的 `unowned` 数出来，
    `board_view` 把这一条亮给主控去派）。

    `skip_gap=True`（2026-11-08，V 的签后义务）：不读 `statements` 判断"是不是已经收录"。
    义务的存在与它是否已满足是两件事：V 只对手稿负责 ⇒ 签落成后无条件开；"满足了没有"
    由 B 收录时消账、收工时 `sweep_registrations` 收口。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "owner": str(owner or ""), "owner_known": False,
                           "owner_why": "", "reason": "", "problems": []}
    sid, no = _label_parts(label)
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
        return out
    if conductor is None:
        out.update(state="skipped",
                   reason=("这一趟没有 conductor ⇒ 板项开不了（义务不落盘 = 没人会看到；"
                           "不是「已经收录了」）"))
        return out
    if not str(out["owner"] or "").strip():
        who = _live_role_task(store, REGISTER_ROLE)
        out["owner"] = str(who.get("task_id") or "")
        out["owner_known"] = bool(out["owner"])
        # 「负责人记 unknown」是读数、不是失败：它不进 `problems`（那会让收工读数把
        # "没人在飞"报成"这一条没办成"），由 `registration_digest` 的 `unowned` 数出来。
        out["owner_why"] = str(who.get("why") or "")
    else:
        out["owner_known"] = True
        out["owner_why"] = "调用方点名了负责人"
    # 深度：有负责人 ⇒ 它那一行 depth + 1（`capabilities.audit_task_ledger` 的
    # `task_depth_discontinuous` 按这条链核）；没有负责人 ⇒ 无父的项必须是 1。
    if out["owner"]:
        item_depth = max(1, int(_task_row(store, out["owner"]).get("depth") or 1)) + 1
    else:
        item_depth = 1
    summary, body = _register_body(
        label=label,
        detail={"statement_id": sid, "proof_no": no, "proof_sha256": sha,
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
    return out


def sweep_registrations(*, store: Any, root: str | Path, limit: int = 50,
                        at: str = "") -> dict[str, Any]:
    """扫一遍 `reports/{f,b}-proof-*.md`：带成立的签而没入库 ⇒ 逐份开义务（幂等）。

    为什么还要扫盘（签发那一刻已经会开一条）：义务不能只依赖"签发那一路跑到了"——
    87 的病根正是"没有任何东西把这件事摆到 B 面前"。这一趟是收工前的看门：谁漏开、
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
        out["signed"] += 1
        sha = str(block.get("proof_sha256") or "")
        label = f"{sid}#p{_VR.as_proof_no(_VS.manuscript_proof_no_of(rel)) or 1}"
        got = ensure_registration(store=store, root=root, label=label, proof_sha=sha,
                                  manuscript=rel, called_by="vreceipts.sweep",
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


def reconcile_registrations(*, store: Any, root: str | Path) -> dict[str, Any]:
    """板上开着的「必须收录」义务与盘上的事实对一次账（收工前的收敛点）。

    两条来源要知道它：签发那一刻（`_vsigns_write_after_flip`）与收工扫盘
    （`backfill` → `sweep_registrations`）。而"收录完了"这件事发生在 B 的写口里 ——
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
    """「必须收录」义务的一眼读数：开着的 / 认不出负责人的 / 逐条明细。"""
    out: dict[str, Any] = {"checked": False, "open": 0, "unowned": 0, "rows": [],
                           "problems": [], "reason": ""}
    conductor = _conductor(store)
    if conductor is None:
        out["reason"] = "没有 conductor ⇒ 板项读不出来（不是「没有收录义务」）"
        return out
    out["checked"] = True
    for row in _register_items(conductor):
        if str(row.get("item_state") or "") == "done":
            continue
        owner = str(row.get("parent_task_id") or "")
        out["open"] += 1
        if not owner:
            out["unowned"] += 1
        out["rows"].append({"task_id": str(row.get("task_id") or ""),
                            "key": str(row.get("input_key") or ""),
                            "owner": owner or "unknown",
                            "item_state": str(row.get("item_state") or ""),
                            "role": str(row.get("role") or ""),
                            "detail": str(row.get("detail") or "")[:200]})
    out["reason"] = (f"板上开着 {out['open']} 条收录义务"
                     + (f"（其中 {out['unowned']} 条负责人 unknown，等主控派人）"
                        if out["unowned"] else ""))
    return out


def _prefix() -> str:
    from .agent_loop import V_VERDICT_ITEM_PREFIX

    return V_VERDICT_ITEM_PREFIX


#: 进程内互斥：`filelock` 的 OS 锁在 Windows 上按句柄，两个线程各开一个 FileLock
#: 也能互斥；这一把是"同一进程里先排好队"的兜底（避免两把 OS 锁在同一进程内
#: 争抢时的平台差异）。键是 outbox 的绝对路径。
_PROC_LOCK = threading.Lock()
_PROC_LOCKS: dict[str, threading.Lock] = {}


# ------------------------------------------------------------------ 路径与读写

def outbox_path(root: str | Path) -> Path:
    """`<root>/out/vreceipts/outbox.jsonl`（本模块唯一的写点）。"""
    return Path(str(root)) / "out" / OUTBOX_DIR / OUTBOX_NAME


def _root_of(store: Any, fallback: Any = "") -> str:
    got = getattr(store, "root", None) or fallback
    return str(got or "")


def _read(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读全部意图行（坏行进 `problems`，不静默跳过）。"""
    path = outbox_path(root)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return rows, problems
    try:
        with path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError as exc:
                    problems.append(f"outbox 第 {i} 行读不出来（{exc}）")
                    continue
                if isinstance(rec, Mapping) and str(rec.get("kind") or "") == KIND:
                    rows.append(dict(rec))
    except OSError as exc:
        problems.append(f"outbox 读不出来（{type(exc).__name__}: {exc}）")
    return rows, problems


def _latest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """每一把键的当前状态 = 最后一行（append-only 的"最后一行胜"）。"""
    out: dict[str, dict[str, Any]] = {}
    for rec in rows:
        key = str(rec.get("key") or "")
        if key:
            out[key] = dict(rec)
    return out


def _append(root: str | Path, rec: Mapping[str, Any]) -> None:
    """追加一行并落盘（`fsync`：崩在返回之后的那一行也真的在盘上）。"""
    path = outbox_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"kind": KIND, **dict(rec)}, ensure_ascii=False, sort_keys=True,
                      default=str)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


@contextlib.contextmanager
def _lock(root: str | Path) -> Iterator[None]:
    """outbox 的写者锁（跨进程 + 进程内）。

    为什么整段 ①→③ 都要在锁里：`tasks.input_key` 没有唯一约束（`schema.py` 是禁改区），
    "先读板再开项"在并发下会各开一项。锁里第二个投递者读到的是 `dispatched`，
    于是它只会返回"已在板上"。
    """
    path = outbox_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    with _PROC_LOCK:
        lock = _PROC_LOCKS.setdefault(key, threading.Lock())
    lock.acquire()
    fl = FileLock(str(path.parent / LOCK_NAME), timeout=30.0)
    try:
        try:
            fl.acquire()
        except Timeout:
            # 拿不到锁 = 没查成（不是"投过了"）：调用方会把这一条记 pending。
            raise TimeoutError("outbox 锁在 30 秒内没拿到") from None
        yield
    finally:
        try:
            fl.release()
        except Exception:  # noqa: BLE001 —— 释放失败不许带走已经写下的行
            pass
        lock.release()


# ------------------------------------------------------------------ 键与明细

def key_of(label: str, verification_id: str, recipient: str) -> str:
    """幂等键的唯一实现：`v-verdict@<label>@<vid>@<recipient>`。

    为什么要带收件人（业主 2026-11-01 裁定）：同一 vid 可能先落 outbox 后被补投，
    而"两者都收"这一档被否 —— 带上收件人之后，键回答的是"这一条投给这个收件人
    了没有"，不是"这一条投过没有"。
    """
    return f"{_prefix()}{label}@{verification_id}@{recipient}"


def legacy_key_of(label: str, verification_id: str) -> str:
    """改前那一版的键（没有收件人后缀）：只用于读旧盘，不许用它写新项。"""
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


def _detail_of_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """一条台账行 ⇒ `deliver_v_verdicts` 要的明细（用生产那一支，不另拼一份）。"""
    from . import agent_loop as AL
    from . import vsigns as VSP

    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    label, vid = _label_of(row)
    try:
        no = int(row.get("proof_no") or 1)
    except (TypeError, ValueError):
        no = 1
    entry = {"label": label, "proof_no": no, "verification_id": vid,
             # `in_sync` 只影响板上的措辞（"这一签盖的就是现在这一份"），
             # 读不到就按 False 写 —— 那是最保守的那一句，不是一句假话。
             "unresolved_errors": int(row.get("unresolved_errors") or 0),
             "in_sync": bool(row.get("in_sync")) if "in_sync" in row else None,
             "proof_sha256": str(row.get("proof_sha256") or "")}
    detail = AL._v_rejection_detail(sid, entry, row, VSP.verdict_axis(row) or "verdict")
    if entry["in_sync"] is None and detail.get("in_sync") is None:
        detail["in_sync"] = False
    return detail


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
    """甲 的收件人：这一次工具调用所属召唤的父（`current_parent`）。

    读不到 ⇒ `recipient=""` + `reason`（调用方记 `undelivered`，不猜）。
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

    口径（业主裁定：不猜）：

    - 那一拍恰好只有一趟 V 在跑 ⇒ 收件人 = 它的 `parent_task_id`（送审者）；
    - 0 趟或 2 趟以上 ⇒ `checked=False` + 原因（不是"没有收件人"）。

    为什么可以这么读：V 台账号的 `started_at` / `ended_at` 在 `tasks` 上逐秒可读，
    而一条判定只能由一趟 V 产出。两趟并发的现场（81 的 03:35 那一拍就是）不可判 ——
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
    rows: list[dict[str, Any]] = []
    try:
        for row in store.rows("tasks"):
            one = dict(row)
            if str(one.get("role") or "") != "V" or str(one.get("kind") or ""):
                continue
            rows.append(one)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）⇒ 收件人没解析"
        return out
    alive: list[dict[str, Any]] = []
    for row in rows:
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
            alive.append(row)
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


# ------------------------------------------------------------------ 写：意图 → 板项 → 状态

def _board_item(conductor: Any, label: str, verification_id: str) -> dict[str, Any]:
    """板上有没有这一条（新键、旧键、任意收件人后缀都算）⇒ 那一行。"""
    base = legacy_key_of(label, verification_id)
    if conductor is None:
        # 空输入得空输出：这一格是"板上有没有这一条"的纯读口，没有 conductor 就是
        # "读不到板"。调用方（`_publish` / `backfill`）在调它之前已经单独判过
        # `_conductor()` 是否为 None，并把那一档记成 pending / undelivered ——
        # checked=False + reason 落在那里，不在这里。返回空字典不是把"没查"折成"没有"。
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


#: 角色名（写证明的那个人/那一类）。唯一来源是 `schema.ROLES`（R005：不抄第二份）。
_ROLES = tuple(_S.ROLES)


def _role_of(text: Any) -> str:
    """`agent-F` / `F` / `secretary-B` ⇒ 角色字母；认不出 ⇒ 空串。"""
    got = str(text or "").strip()
    if not got:
        return ""
    for prefix in ("agent-", "agent_", "secretary-", "secretary_"):
        if got.lower().startswith(prefix):
            got = got[len(prefix):]
            break
    got = got.strip().upper()
    return got if got in _ROLES else ""


def _author_of(store: Any, label: str) -> dict[str, Any]:
    """这份证明的登记作者（只认两种可信来源；都没有 ⇒ `checked=False`）。

    为什么只认两种：

    - `statements.proof_authors`：显式登记的作者（穷举型证据那一档早就在写，
      普通证明今天还没有人写）；
    - `statements.created_by` 且它点名的是角色（`agent-F`）：那是"谁创建了这一行"。

    `created_by="secretary-B"` 不算作者：B 的秘书写这一行 = B 把证明收录进册，
    那是登记动作，不是写作（业主 2026-11-01：「F 写的证明，F 送审……B 侧收录」）。
    认成作者会让"替人送审"这一档永远看不见 —— 而那正是本笔要它可见的东西。

    读不到作者时返回 `checked=False` + 原因；调用方记 `author_not_recorded`，
    不许默认成"作者就是送审者"（那是猜）。
    """
    out: dict[str, Any] = {"checked": False, "author": "", "source": "", "reason": ""}
    sid = str(label or "").split("#", 1)[0]
    if store is None or not sid:
        out["reason"] = "没有 store / 没有命题号 ⇒ 作者读不到"
        return out
    # 按号定位走查口（口径一）；`row={}` 与改前同一个默认值（falsy ⇒ 「不在册」那一支）。
    by_id = SL.by_id(store, stmt_id=sid)
    if not by_id["checked"]:
        err = by_id.get("error") or {}
        out["reason"] = (f"statements 读不出来（{err.get('type', '?')}: "
                         f"{err.get('message', '?')}）")
        return out
    row = by_id["row"]
    if not row:
        out["reason"] = f"命题 {sid} 不在册 ⇒ 作者读不到"
        return out
    authors = row.get("proof_authors")
    if isinstance(authors, (list, tuple)):
        for one in authors:
            role = _role_of(one)
            if role:
                out.update(checked=True, author=role, source="proof_authors",
                           reason=f"proof_authors 登记为 {role}")
                return out
    created = str(row.get("created_by") or "")
    if not created.lower().startswith(("secretary-", "secretary_")):
        role = _role_of(created)
        if role:
            out.update(checked=True, author=role, source="created_by",
                       reason=f"created_by={created} 点名了角色 {role}")
            return out
    out["reason"] = (f"作者没有登记（created_by={created or '（空）'} 是登记口，不是作者）"
                     "⇒ 这一格记作者未记录，不猜")
    return out


def statement_author_of(store: Any, label: str) -> dict[str, Any]:
    """公开读口：`_author_of` 的同一份实现（读侧与判据都从这里问作者）。"""
    return _author_of(store, label)


def _publish(*, store: Any, root: str, label: str, verification_id: str,
             recipient: str, role: str, depth: int, detail: Mapping[str, Any],
             at: str, by_task: str = "", called_by: str = "V",
             source: str = "verify_proof", unknown_reason: str = "",
             author: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """① 意图 → ② 板项 → ③ dispatched/undelivered。整段在锁里（并发只开一项）。"""
    from . import agent_loop as AL

    who = dict(author or {})
    author_role = str(who.get("author") or "")
    author_known = bool(who.get("checked"))
    # 替人送审：送审者（收件人）与登记作者不是同一个角色 ⇒ 缺陷（业主 2026-11-01），
    # 但不许因此改投给作者（那是把定义读成路由）；只把它记下来、让它可见。
    violation = bool(author_known and author_role and role
                     and author_role != _role_of(role))
    note = ""
    if violation:
        note = (f"（替人送审：送审者是 {role or '（角色没读到）'}，而这份证明的登记作者是 "
                f"{author_role}。按业主 2026-11-01 的口径这是缺陷，不是转交 —— 回执仍投送审者。）")
    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "opened": False, "reason": "", "problems": [],
                           "resubmit": {},
                           "submitter": recipient, "submitter_role": role,
                           "author": author_role,
                           "author_source": str(who.get("source") or ""),
                           "submitter_is_not_author": (violation if author_known else None),
                           "author_not_recorded": (not author_known)}
    if not recipient:
        # 收件人读不到 ⇒ 意图照落（可见），状态 undelivered（不猜）。
        # `unknown_reason` 必须原样带过来：把"那一拍有 2 趟 V 在跑"折成"没有收件人"，
        # 读的人就没法判断这是"这一条没有送审者"还是"这一条暂时不可判"。
        out.update(state=UNDELIVERED,
                   reason=(unknown_reason or "没有收件人 ⇒ 不开项（不猜）"))
        key = key_of(label, verification_id, "")
        out["key"] = key
        try:
            with _lock(root):
                if _latest(_read(root)[0]).get(key, {}).get("state") != UNDELIVERED:
                    _append(root, {"key": key, "label": label,
                                   "verification_id": verification_id, "recipient": "",
                                   "role": "", "at": at, "by_task": by_task,
                                   "state": UNDELIVERED, "item_id": "",
                                   "reason": out["reason"], "source": source})
        except Exception as exc:  # noqa: BLE001
            out["problems"].append(f"outbox 写不进去（{type(exc).__name__}: {exc}）")
        return out
    key = key_of(label, verification_id, recipient)
    out["key"] = key
    # outbox 的每一行都带这四格：替人送审/作者未记录必须在账上可查，不只在返回值里。
    extra = {"submitter": recipient, "submitter_role": role, "author": author_role,
             "author_source": str(who.get("source") or ""),
             "submitter_is_not_author": (violation if author_known else None),
             "author_not_recorded": (not author_known),
             "severity": ("error" if violation else "")}
    try:
        with _lock(root):
            latest = _latest(_read(root)[0])
            cur = latest.get(key) or {}
            if str(cur.get("state") or "") == DISPATCHED:
                # outbox 说"投过了" —— 但板项才是交付物。板项不在（台账被重建 /
                # 被删 / 上一版把它撤了）⇒ 这一条其实没投出去，照常重开；
                # 拿 intent 当交付是"看起来成功"，正是本仓最忌的那一档。
                if _board_item(_conductor(store), label, verification_id):
                    out.update(checked=True, state=DISPATCHED,
                               item_id=str(cur.get("item_id") or ""),
                               reason="outbox 已记：这一条投给这个收件人过了（不重开）")
                    # 回执那一条已经在板上，但"必须重送"的义务是另一条板项：
                    # 旧盘（本笔之前投过的判决）在这里补开，幂等键没有收件人后缀，
                    # 于是同一个收件人跑十趟也只有一条。
                    out["resubmit"] = ensure_resubmit(
                        store=store, root=root, label=label,
                        verification_id=verification_id, detail=detail,
                        recipient=recipient, role=role, depth=depth, at=at)
                    return out
            if not cur:
                _append(root, {"key": key, "label": label,
                               "verification_id": verification_id,
                               "recipient": recipient, "role": role, "at": at,
                               "by_task": by_task, "state": PENDING, "item_id": "",
                               "reason": "", "source": source, **extra})
            conductor = _conductor(store)
            if conductor is None:
                out.update(checked=False, state=PENDING,
                           reason="这一趟没有 conductor ⇒ 板项开不了（意图已在盘上，"
                                  "收工前的补投会再试）")
                _append(root, {"key": key, "label": label,
                               "verification_id": verification_id,
                               "recipient": recipient, "role": role, "at": at,
                               "by_task": by_task, "state": PENDING, "item_id": "",
                               "reason": out["reason"], "source": source, **extra})
                return out
            got = AL.deliver_v_verdicts(conductor, task_id=recipient, depth=depth,
                                        role=role, details=[dict(detail)],
                                        called_by=called_by, note=note)
            out["problems"].extend(str(x) for x in (got.get("problems") or []))
            item_id = ""
            if got.get("opened"):
                item_id = str(got["opened"][0])
                out.update(checked=True, opened=True)
            else:
                row = _board_item(conductor, label, verification_id)
                item_id = str(row.get("task_id") or "")
            if item_id:
                out.update(state=DISPATCHED, item_id=item_id,
                           reason=(f"新开板项 {item_id}" if got.get("opened")
                                   else f"已在板上 {item_id}（不重开）"))
            else:
                out.update(state=UNDELIVERED,
                           reason=str(got.get("reason") or "板项没开成（原因没读到）"))
            # ---- I2（业主 2026-11-01）：「打回」不只是一条回执，还是一条必须重送的
            # 义务。义务单独一条板项（`v-resubmit@<命题>@<sha>`，无收件人后缀），
            # 关闭条件是"同一份证明出现更新的干净成立行"，不是 ack。
            out["resubmit"] = ensure_resubmit(
                store=store, root=root, label=label, verification_id=verification_id,
                detail=detail, recipient=recipient, role=role, depth=depth, at=at)
            _append(root, {"key": key, "label": label,
                           "verification_id": verification_id, "recipient": recipient,
                           "role": role, "at": at, "by_task": by_task,
                           "state": out["state"], "item_id": out["item_id"],
                           "reason": out["reason"], "source": source, **extra})
    except Exception as exc:  # noqa: BLE001 —— 投递失败不许带走这一签
        out.update(checked=False, state=PENDING,
                   reason=f"投递没跑成（{type(exc).__name__}: {exc}）")
        out["problems"].append(out["reason"])
    return out


def publish_row(store: Any, row: Mapping[str, Any], *, at: str = "",
                source: str = "verify_proof") -> dict[str, Any]:
    """甲 的入口：`record_verification` 之后立刻调（一条台账行 → 一次投递）。

    收件人 = `current_parent()`（召唤这一趟 V 的那个任务）。不是"有毛病"那一档就
    不投回执（`state="skipped"`）—— 但"干净的成立"那一档要做另一件事：把同一份
    证明名下开着的重送义务收口（`settle_resubmitted`，`state="settled"`）。
    这就是业主 2026-11-01 裁定的关闭条件：不是 ack，而是"更新的成立行"。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "key": "", "item_id": "",
                           "opened": False, "reason": "", "problems": [],
                           "resubmit": {}}
    if store is None:
        out["reason"] = "没有 store ⇒ 回执没处落（不是「投过了」）"
        return out
    label, vid = _label_of(row)
    if not label or not vid:
        out["reason"] = "这一行没有 label / 编号 ⇒ 做不出幂等键"
        return out
    try:
        from . import vsigns as VSP

        if not VSP.verdict_axis(row):
            # 干净的「成立」是关闭重送义务的那一道门（不是"什么都不做"）。
            try:
                settled = settle_resubmitted(store=store, root=_root_of(store), row=row)
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
                           reason="这一签不是「有毛病」那一档 ⇒ 不投回执"
                                  "（回执只给要改的人）；也没有要收口的重送项")
            return out
        detail = _detail_of_row(row)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"明细造不出来（{type(exc).__name__}: {exc}）"
        return out
    who = _recipient_now(store)
    root = _root_of(store)
    return _publish(store=store, root=root, label=label, verification_id=vid,
                    recipient=str(who["recipient"]), role=str(who["role"]),
                    depth=int(who["depth"]), detail=detail,
                    at=str(at or row.get("at") or ""),
                    by_task=_current_task(), source=source,
                    unknown_reason=str(who.get("reason") or ""),
                    author=_author_of(store, label))


def _current_task() -> str:
    """这一趟 V 的台账号（读不到就是空串 —— 它不是收件人，只是留给审计的"谁判的"）。"""
    try:
        from . import conductor as CND

        return str(CND.current_task_id() or "")
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ 乙：收工前补投

def reconcile_resubmits(*, store: Any, root: str | Path) -> dict[str, Any]:
    """把板上开着的重送义务与"盘上的事实"对一次账（收工前那一趟的收敛点）。

    为什么要对账（而不是只在写入时收口）：义务的关闭有两个来源，而它们不都经过
    `vreceipts` ——

    - 干净的「成立」签落下时由 `publish_row` 收口（`settle_resubmitted`）；
    - 命题被明确放弃时，可能走 `statementabandon.apply_abandonment`（它自己会作废），
      也可能走 `table.update(status=abandoned)` 那条就地写口（业主 2026-11-01 加的
      `Secretary.amend_statement_meta`）—— 后者不认识板项，义务会留在板上，
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
    try:
        statements = {str(r.get("stmt_id") or ""): dict(r)
                      for r in store.rows("statements")}
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"`statements` 读不出来（{type(exc).__name__}: {exc}）"
        return out
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


def _detail_from_ledger(store: Any, root: str, label: str,
                        verification_id: str) -> dict[str, Any] | None:
    """从台账文件把某一条判定读成投递明细（历史行没有 outbox 意图时走这一支）。"""
    from . import verifications as VR

    sid = label.split("#", 1)[0]
    try:
        rows, _problems = VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception:  # noqa: BLE001
        return None
    sign = next((dict(r) for r in rows
                 if str(r.get("verification_id") or "") == verification_id), None)
    if sign is None:
        return None
    # `in_sync`：这一签盖的正文与命题现文是不是同一份（与读侧同一口径：
    # `statement_review_reading` 的 proofs[*].in_sync）。
    try:
        # 按号定位走查口（口径一）；读不到与不在册在这条读数上同形（都是 `in_sync=False`），
        # 因为这一格只是回执明细里的一句话，不是「六档」的判据。
        by_id = SL.by_id(store, stmt_id=sid)
        stmt = by_id["row"] if by_id["found"] else {}
        reading = VR.statement_review_reading(root, stmt) if stmt else {}
        entry = next((e for e in (reading.get("proofs") or [])
                      if str(e.get("verification_id") or "") == verification_id), {})
        sign["in_sync"] = bool(entry.get("in_sync"))
    except Exception:  # noqa: BLE001
        sign["in_sync"] = False
    try:
        return _detail_of_row(sign)
    except Exception:  # noqa: BLE001
        return None


def backfill(*, store: Any, caller: str = "conductor.closing") -> dict[str, Any]:
    """乙 的入口：把 `receipt_digest` 的全部「有毛病」行扫一遍，补投漏的。

    为什么补投源是 `receipt_digest`（`_fault_rows`）而不是 `v_rejections_digest`：
    后者只给"每份证明最近那一签"。81 上它给 7 条，而真值 8 条 —— `000000#p1`
    的 `v-000001` 被后来的 `v-000002` 顶掉了。拿它当补投源，那一条永远补不回来。

    幂等：板上已有（任意收件人后缀 / 旧键）⇒ 只记一条 `dispatched`（adopted），不开项；
    同一个 key 再扫一遍 ⇒ 只读不写（见 `_publish` 的 `latest` 判断）。
    """
    out: dict[str, Any] = {"checked": False, "caller": caller, "receipts": 0,
                           "dispatched": 0, "not_dispatched": 0, "opened": [],
                           "adopted": [], "existing": [], "undelivered": [],
                           "submitter_is_not_author": [], "author_not_recorded": [],
                           "problems": [], "reason": ""}
    if store is None:
        out["reason"] = "没有 store ⇒ 这一格没查成（不是「没有漏投」）"
        return out
    root = _root_of(store)
    try:
        from . import vsigns as VSP

        got = VSP.receipt_digest(root, store, limit=10_000)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"回执读数读不出来（{type(exc).__name__}: {exc}）⇒ 补投没跑"
        out["problems"].append(out["reason"])
        return out
    out["problems"].extend(str(x) for x in (got.get("problems") or []))
    if not got.get("checked"):
        out["reason"] = (f"台账读不成（{got.get('reason') or '原因没读到'}）⇒ "
                         "这一格没查成（不是「没有漏投」）")
        return out
    out["checked"] = True
    rows = list(got.get("rows") or [])
    out["receipts"] = int(got.get("receipts") or 0)
    conductor = _conductor(store)
    for row in rows:
        label = str(row.get("label") or "")
        vid = str(row.get("verification_id") or "")
        if not label or not vid:
            out["problems"].append("有一行没有 label / 编号 ⇒ 补投跳过（不猜）")
            continue
        item = _board_item(conductor, label, vid)
        author = _author_of(store, label)
        if item:
            out["adopted"].append(str(item.get("task_id") or ""))
            if author.get("checked") and author.get("author") != _role_of(item.get("role")):
                out["submitter_is_not_author"].append(
                    f"{label}@{vid}：送审者 {item.get('role')}，作者 {author.get('author')}")
            elif not author.get("checked"):
                out["author_not_recorded"].append(f"{label}@{vid}")
            # 板上已有：把 outbox 补成 dispatched（幂等；已记过则不写第二行）。
            key = key_of(label, vid, str(item.get("parent_task_id") or ""))
            try:
                with _lock(root):
                    latest = _latest(_read(root)[0])
                    if key not in latest:
                        _append(root, {"key": key, "label": label,
                                       "verification_id": vid,
                                       "recipient": str(item.get("parent_task_id") or ""),
                                       "role": str(item.get("role") or ""),
                                       "at": str(row.get("at") or ""), "by_task": "",
                                       "state": DISPATCHED,
                                       "item_id": str(item.get("task_id") or ""),
                                       "reason": "板上已有（补投时认领，不重开）",
                                       "source": caller,
                                       "submitter": str(item.get("parent_task_id") or ""),
                                       "submitter_role": str(item.get("role") or ""),
                                       "author": str(author.get("author") or ""),
                                       "author_source": str(author.get("source") or ""),
                                       "submitter_is_not_author": (
                                           (author.get("author") != _role_of(item.get("role")))
                                           if author.get("checked") else None),
                                       "author_not_recorded": (not author.get("checked")),
                                       "severity": ("error" if (
                                           author.get("checked")
                                           and author.get("author") != _role_of(item.get("role")))
                                           else "")})
            except Exception as exc:  # noqa: BLE001
                out["problems"].append(f"{label}@{vid}：outbox 认领没写成"
                                       f"（{type(exc).__name__}: {exc}）")
            # 回执项在板上 ≠ 重送义务在板上：旧盘（本笔之前投过的判决）要走这一支
            # 把义务补开。幂等键没有收件人后缀，所以补投十趟也只多一条。
            _detail = _detail_from_ledger(store, root, label, vid)
            if _detail is not None:
                _holder = str(item.get("parent_task_id") or "")
                _rs = ensure_resubmit(
                    store=store, root=root, label=label, verification_id=vid,
                    detail=_detail, recipient=_holder,
                    role=str(item.get("role") or ""),
                    depth=max(1, int(_task_row(store, _holder).get("depth") or 1)),
                    at=str(row.get("at") or ""))
                out.setdefault("resubmit", []).append(
                    {"label": label, "verification_id": vid, **_rs})
                out["problems"].extend(str(x) for x in (_rs.get("problems") or []))
            continue
        # 板上没有 ⇒ 定收件人：先看 outbox 意图，再看时间窗（唯一才认）。
        recipient, role, depth, why = "", "", 0, ""
        try:
            latest = _latest(_read(root)[0])
        except Exception:  # noqa: BLE001
            latest = {}
        known = [rec for key, rec in latest.items()
                 if str(rec.get("label") or "") == label
                 and str(rec.get("verification_id") or "") == vid
                 and str(rec.get("recipient") or "")]
        if known:
            rec = known[-1]
            recipient = str(rec.get("recipient") or "")
            role = str(rec.get("role") or "")
            depth = int(rec.get("depth") or 0) or 0
            if not depth:
                holder = _task_row(store, recipient)
                depth = max(1, int(holder.get("depth") or 1))
            why = "outbox 里已有这一条意图（收件人就是它）"
        else:
            got_who = resolve_recipient(store, str(row.get("at") or ""))
            if got_who.get("checked"):
                recipient = str(got_who["recipient"])
                role = str(got_who["role"])
                depth = int(got_who["depth"])
                why = str(got_who["reason"])
            else:
                why = str(got_who.get("reason") or "收件人不可判")
        detail = _detail_from_ledger(store, root, label, vid)
        if detail is None:
            out["problems"].append(f"{label}@{vid}：台账里读不出这一行的明细 ⇒ 补投跳过")
            continue
        res = _publish(store=store, root=root, label=label, verification_id=vid,
                       recipient=recipient, role=role, depth=depth, detail=detail,
                       at=str(row.get("at") or ""), by_task="", called_by="V",
                       source=caller, unknown_reason=why, author=author)
        if res.get("submitter_is_not_author"):
            out["submitter_is_not_author"].append(
                f"{label}@{vid}：送审者 {role}，作者 {author.get('author')}")
        elif res.get("author_not_recorded"):
            out["author_not_recorded"].append(f"{label}@{vid}")
        if res.get("state") == DISPATCHED:
            if res.get("opened"):
                out["opened"].append(str(res.get("item_id") or ""))
            else:
                out["existing"].append(str(res.get("item_id") or ""))
        elif res.get("state") == UNDELIVERED:
            out["undelivered"].append(f"{label}@{vid}：{res.get('reason') or why}")
        out["problems"].extend(str(x) for x in (res.get("problems") or []))
    # 三个数分开报（业主 2026-11-01：投出去与送到了不是一个数）。
    try:
        again = VSP.receipt_digest(root, store, limit=10_000)
        out["dispatched"] = int(again.get("dispatched") or 0)
        out["not_dispatched"] = int(again.get("not_dispatched") or 0)
    except Exception as exc:  # noqa: BLE001
        out["problems"].append(f"补投后的三态没读成（{type(exc).__name__}: {exc}）")
    # 收工前的最后一件事：板上开着的重送义务与盘上的事实对一次账（命题已被明确放弃的
    # 作废、已有更新干净成立的收口）。两条来源（`statementabandon` 与
    # `Secretary.amend_statement_meta`）都不认识板项，这一格是它们的收敛点。
    try:
        out["resubmit_reconcile"] = reconcile_resubmits(store=store, root=root)
    except Exception as exc:  # noqa: BLE001 —— 对账没跑成不许带走收工读数
        out["resubmit_reconcile"] = {"checked": False, "closed": [], "expired": [],
                                     "left": [], "problems": [],
                                     "reason": f"对账没跑成（{type(exc).__name__}: {exc}）"}
    # ---- 缺陷 B（2026-11-05）：收工前再把"签了但没人收录"扫一遍（看门的那一半）----
    #
    # 签发那一刻已经会开一条（`_vsigns_write_after_flip`），但义务不能只依赖"那一路跑到了"
    # —— 87 的病根正是"没有任何东西把这件事摆到 B 面前"。这一趟做两件事，顺序固定：
    # ① 扫盘补开漏的（`sweep_registrations`，幂等：同键只一条）；
    # ② 与盘上的事实对账收口（`reconcile_registrations`：入库了就 completed、明确放弃就
    #    expired，都不靠 ack）。
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
    out["reason"] = (f"回执 {out['receipts']} 条；补投新开 {len(out['opened'])} 条、"
                     f"认领 {len(out['adopted'])} 条、已在板上 {len(out['existing'])} 条、"
                     f"收件人不可判 {len(out['undelivered'])} 条；"
                     f"替人送审 {len(out['submitter_is_not_author'])} 条（error）、"
                     f"作者未记录 {len(out['author_not_recorded'])} 条 ⇒ "
                     f"已投出 {out['dispatched']} 条、未投出 {out['not_dispatched']} 条"
                     "（投出去 ≠ 送到：送到看收件人 acked）")
    return out


# ------------------------------------------------------------------ 读口

def outbox_index(root: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    """`(label, verification_id) -> 最后一条意图`（读侧要它把作者/送审者并进读数）。"""
    rows, _problems = _read(root)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in rows:
        out[(str(rec.get("label") or ""), str(rec.get("verification_id") or ""))] = rec
    return out


def outbox_digest(root: str | Path) -> dict[str, Any]:
    """outbox 的一眼读数（`pending` / `dispatched` / `undelivered` 三条分开数）。

    三态：文件不在 ⇒ `checked=True, rows=0`（查过了、没有意图）；读不成就
    `checked=False`（不是"没有意图"）。
    """
    rows, problems = _read(root)
    latest = _latest(rows)
    out: dict[str, Any] = {"checked": not problems, "rows": len(rows),
                           "keys": len(latest), "pending": 0, "dispatched": 0,
                           "undelivered": 0, "problems": list(problems), "reason": ""}
    for rec in latest.values():
        state = str(rec.get("state") or "")
        if state in out:
            out[state] = int(out[state]) + 1
    out["reason"] = (f"outbox {out['keys']} 条意图：已投出 {out['dispatched']}、"
                     f"待补投 {out['pending']}、收件人不可判 {out['undelivered']}")
    return out
