"""F 收工自动提交：把「已拿签、尚未提交」的稿写进 F 自己那一行的 `tasks.artifacts`。

（2026-11-11 从 `agent_f/step.py::_Step._auto_submit_signed` 的方法体搬出；业主裁定 ①
「F侧报告收工时自动提交其名下未提交的V签稿」。拆出的理由：同一批把 `step.py` 556 → 813
行、把那个方法推到 215 行 —— 业主口径是基线不许抬，所以按「读 / 写」拆：记号与
扫描住在 `agent_f/submission.py`，本模块只回答「这一趟选谁、怎么落进 artifacts」。）

## 为什么由框架写、不读模型给的清单（业主 2026-11-11 裁定 ①）

模型只说「收工」这件事；提交哪几份是盘上的事实（V 的颁发表 × 现行文件），
由框架现读现写 —— 于是"提交单"不可能被模型漏报或虚报。

## 三态（不许把「没提交」写成「提交了」）

- `auto_submitted`：这一趟真写进 artifacts 的那几份（稿号 + 正文 sha +
  签 sha + 文件字节 sha + 时刻）；并发下别人先写的那一份不算这一趟的；
- `still_unsubmitted`：有文件、这一趟没提交的，逐条给理由
  （`unsigned` / `body_changed_after_sign` / `sign_unbacked` /
  `already_submitted` / `no_task_row` / `write_failed` / `ambiguous_path`）；
- `checked=False`：这一格没查成（颁发表读不出来 / 写不进去）——
  不是「没有要提交的」。

## 幂等

`artifacts` 里已有该稿号的 `mss:` 记号 ⇒ 一个字节都不再写（判据是稿号，
与版本无关 —— 业主 2026-11-11 追加裁定）。

## 为什么写 `tasks` 而不新建表

`tasks.artifacts` 是既有的「这次召唤产出了哪些引用」那一格（`conductor.finish`
本来就 append-only 合并它），F 的提交单落在那里，D 才有一处可读的「已提交」。

公开入口只有 :func:`auto_submit_signed`；`_still` / `_select` / `_write_fresh` 是它的
三段（选谁 / 事务里落 artifacts），拆开只为不把一件事写成两百行。
"""
from __future__ import annotations

from typing import Any, Mapping

from .. import conductor as CX
from . import delivery as _DL
from ._support import S, TERMINAL_STATUSES


def _still(cand: Mapping[str, Any], state: str, why: str) -> dict[str, Any]:
    """`still_unsubmitted` 的一行（两个 sha 与「配不配」一起给）。

    2026-11-11 业主裁定：`proof_no` 在手稿产出侧 / 呈递侧退役 ⇒ 这一格不带它。
    """
    return {
        "manuscript_id": str(cand.get("manuscript_id") or ""),
        "manuscript": str(cand.get("manuscript") or ""),
        "signed": bool(cand.get("signed")),
        "signed_sha": str(cand.get("signed_sha") or ""),
        "current_sha": str(cand.get("current_sha") or ""),
        "sha_matches": bool(cand.get("signed_sha")
                            and cand.get("signed_sha") == cand.get("current_sha")),
        "state": str(state or ""), "why": str(why or ""),
    }


def _select(candidates: list[dict[str, Any]], *, submitted: Mapping[str, Any],
            row: Mapping[str, Any] | None, row_why: str, stamp: str,
            out: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """选谁：已签、sha 与现行正文一致、artifacts 里还没有这个稿号 ⇒ `(候选, 记号)`。

    没选上的逐条进 `out["still_unsubmitted"]`（并发下别人先写的那一份也在这里，
    由调用方在事务之后补）；`out` 是同一个读数容器，本函数不改别的两格。
    """
    pending: list[tuple[dict[str, Any], str]] = []
    for cand in candidates:
        mid = str(cand.get("manuscript_id") or "")
        if not mid:
            continue
        if mid in submitted:
            out["still_unsubmitted"].append(_still(
                cand, "already_submitted",
                f"`tasks.artifacts` 里已经有稿号 {mid} 的提交记号 ⇒ "
                "幂等：不重复写"))
            continue
        if not cand.get("signed"):
            out["still_unsubmitted"].append(_still(
                cand, str(cand.get("state") or "unsigned"),
                str(cand.get("why") or "没有可提交的签 ⇒ 不入提交单")))
            continue
        if row is None:
            out["still_unsubmitted"].append(_still(
                cand, "no_task_row",
                row_why or "没有可写的 F 台账行 ⇒ 这一份拿签稿没提交"))
            continue
        try:
            token = _DL.submission_token(
                manuscript_id=mid,
                path=str(cand.get("manuscript") or ""),
                body_sha=str(cand.get("signed_sha") or ""),
                sign_sha=str(cand.get("sign_sha") or ""),
                file_sha=str(cand.get("file_sha") or ""),
                statement_id=str(cand.get("statement_id") or ""),
                # 签时刻（签文件里的 `at`）；老签 / 夹具没有这一格 ⇒ 退到提交时刻，
                # 但两格在记号里分开写，读的人不会把"提交"读成"签发"。
                at=str(cand.get("at") or stamp), submitted_at=stamp,
                # 收工这一条路写 `via=closing_auto_submit`：签触发那一条写
                # `sign_issued`（2026-11-11 甲），读侧靠这一格分清谁置的。
                via=_DL.VIA_CLOSING)
        except ValueError as exc:  # 稿号为空已在上面挡掉；这里只兜底
            out["still_unsubmitted"].append(_still(cand, "bad_token", str(exc)))
            continue
        pending.append((cand, token))
    return pending


def _write_fresh(store: Any, *, task_id: str,
                 pending: list[tuple[dict[str, Any], str]],
                 out: dict[str, Any]) -> tuple[list[str], str]:
    """一个事务、读-判-写（`artifacts` 是 append-only）⇒ `(真写进去的记号, 写失败理由)`。

    锁内重算「已提交」：并发下另一个收工可能刚写过；范围仍是所有 F 的行。
    既有项一个不动（`S.sorted_unique` 只去重排序），只把这一趟选出来的追加上去。
    """
    fresh: list[str] = []
    write_error = ""
    try:
        with store.tx("tasks", actor="F", note="f.step:auto_submit") as tx:
            cur = tx.find("tasks", task_id=task_id)
            if cur is None:
                write_error = f"事务里找不到 {task_id!r} 那一行"
            else:
                existing: dict[str, dict[str, Any]] = {}
                for one in tx.rows("tasks"):
                    if str(one.get("role") or "") != "F":
                        continue
                    got, problems = _DL.submissions_of(
                        one.get("artifacts") or ())
                    out["problems"] += problems
                    for mid, rec in got.items():
                        existing.setdefault(mid, rec)
                fresh = [
                    token for _cand, token in pending
                    if str((_DL.parse_submission(token) or {}).get(
                        "manuscript_id") or "") not in existing]
                if fresh:
                    # 合并而不是覆盖：既有项一个不动（`S.sorted_unique` 只去重排序）。
                    cur["artifacts"] = S.sorted_unique(
                        list(cur.get("artifacts") or ()) + fresh)
                    tx.upsert("tasks", cur, note="f.step:auto_submit")
    except Exception as exc:  # noqa: BLE001 —— 写不进去必须如实说
        write_error = f"{type(exc).__name__}: {exc}"
    return fresh, write_error


def auto_submit_signed(*, store: Any, root: Any, plan_id: str, stamp: str) -> dict:
    """收工那一趟的自动提交（读盘 → 选 → 事务写 → 逐条读数）。

    参数是 `_Step` 那个薄壳递过来的三样运行期事实：`store`（台账）、`root`（工作区根，
    盘上稿与 V 的颁发表都在它下面）、`stamp`（这一趟的提交时刻）。返回形状与
    `agent_f/step.py` 的 `_close_reading` 读的那三格逐字一致。
    """
    out: dict[str, Any] = {
        "checked": False, "auto_submitted": [], "auto_submitted_count": 0,
        "still_unsubmitted": [], "problems": [],
        "task_id": "", "plan_id": str(plan_id or ""),
        "why": "",
    }
    try:
        scan = _DL.submission_candidates(root)
    except Exception as exc:  # noqa: BLE001 —— 收工读数坏了不能把"停"带走
        out["why"] = (f"拿签稿扫描没跑成（{type(exc).__name__}: {exc}）"
                      " ⇒ 这一趟没有自动提交（不是「没有要提交的」）")
        return out
    out["checked"] = bool(scan.get("checked"))
    out["problems"] = [str(x) for x in (scan.get("problems") or [])]
    candidates = [dict(c) for c in (scan.get("candidates") or [])
                  if isinstance(c, Mapping)]

    # ---- 找「F 自己那一行」（召唤号由运行期上下文挂上；直调时没有）---------
    task_id = str(CX.current_task_id() or "")
    out["task_id"] = task_id
    row: dict[str, Any] | None = None
    row_why = ""
    tasks: list[dict[str, Any]] = []
    try:
        tasks = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没有可写的那一行
        row_why = f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
    #: 「已提交」按稿号（与版本无关）判；范围是所有 F 的 task 行，不只本趟：
    #: 一份稿交过一次就是交过了，换个 task 再收工也不该再写一遍。
    submitted: dict[str, dict[str, Any]] = {}
    for one in tasks:
        if str(one.get("role") or "") != "F":
            continue
        got, problems = _DL.submissions_of(one.get("artifacts") or ())
        out["problems"] += problems
        for mid in got:
            submitted.setdefault(mid, dict(got[mid]))
    if not task_id:
        row_why = ("这一趟没有召唤号（`conductor.current_task_id()` 是空的："
                   "直调 `F.step` 的那条路）⇒ 没有「F 自己那一行」可写")
    else:
        found = next((r for r in tasks
                      if str(r.get("task_id") or "") == task_id), None)
        if found is None:
            row_why = (f"召唤号 {task_id!r} 不在 `tasks` 表里 ⇒ "
                       "没有「F 自己那一行」可写")
        elif str(found.get("role") or "") != "F":
            row_why = (f"召唤号 {task_id!r} 那一行的角色是 "
                       f"{found.get('role')!r}，不是 F")
        elif str(found.get("status") or "") in TERMINAL_STATUSES:
            row_why = (f"召唤号 {task_id!r} 那一行已经是终态 "
                       f"{found.get('status')!r} ⇒ 不再往终态行写产物"
                       "（终态先到先得）")
        else:
            row = found

    pending = _select(candidates, submitted=submitted, row=row, row_why=row_why,
                      stamp=stamp, out=out)
    if not pending:
        out["why"] = (
            "没有「已拿签、尚未提交」的稿 ⇒ 这一趟不写 artifacts"
            if not out["still_unsubmitted"] else
            "有稿文件，但这一趟没有一份可提交 ⇒ 逐条理由见 still_unsubmitted")
        return out

    fresh, write_error = _write_fresh(store, task_id=task_id, pending=pending, out=out)
    if write_error:
        out["checked"] = False
        out["why"] = f"自动提交没写成（{write_error}）⇒ 这一趟一份都没提交"
        for cand, _token in pending:
            out["still_unsubmitted"].append(
                _still(cand, "write_failed", out["why"]))
        return out
    fresh_set = set(fresh)
    for token in fresh:
        rec = dict(_DL.parse_submission(token) or {})
        out["auto_submitted"].append({
            "manuscript_id": str(rec.get("manuscript_id") or ""),
            "manuscript": str(rec.get("path") or ""),
            "body_sha": str(rec.get("body_sha") or ""),
            "signed_sha": str(rec.get("body_sha") or ""),
            "sign_sha": str(rec.get("sign_sha") or ""),
            "file_sha": str(rec.get("file_sha") or ""),
            "at": str(rec.get("at") or ""),
            "submitted_at": str(rec.get("submitted_at") or ""),
            "token": token,
        })
    for cand, token in pending:
        if token in fresh_set:
            continue
        out["still_unsubmitted"].append(_still(
            cand, "already_submitted",
            "写这一趟之前，同一稿号的提交记号已经被另一次收工写进 "
            "`artifacts`（并发幂等）"))
    out["auto_submitted_count"] = len(out["auto_submitted"])
    out["why"] = (
        f"这一趟自动提交 {out['auto_submitted_count']} 份拿签稿"
        + (f"；另有 {len(out['still_unsubmitted'])} 份没提交"
           "（逐条理由见 still_unsubmitted）"
           if out["still_unsubmitted"] else ""))
    return out
