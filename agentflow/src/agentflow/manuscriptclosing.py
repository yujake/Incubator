# -*- coding: utf-8 -*-
"""E 的收工自动提交。

与 F 那套同形：选 E 名下（`e-proof` / `e-num` 两族）已签、尚未提交的稿，把
`mss:` 记号写进 E 自己那一行 `tasks.artifacts`。记号格式与解析复用
`agent_f/submission.py`，不在本模块新造字符串。

本模块与 `manuscriptsubmission`（统一读口 + B 收录）拆开，只为体量基线：
两边共用同一批 `mss:` 记号函数，不各写一份。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import manuscriptfamily as _MFAM
from . import schema as S
from .manuscriptsubmission import (
    TERMINAL_TASK_STATUSES, VIA_CLOSING, _proof_sha, _read_tasks, _task_tokens,
    parse_submission, resolve_submission, submission_token, submissions_of,
)


# --------------------------------------------------------------------- E：收工自动提交
def _still(cand: Mapping[str, Any], state: str, why: str) -> dict[str, Any]:
    return {
        "manuscript_id": str(cand.get("manuscript_id") or ""),
        "manuscript": str(cand.get("manuscript") or ""),
        "proof_no": int(cand.get("proof_no") or 0) or 1,
        "signed": bool(cand.get("signed")),
        "signed_sha": str(cand.get("signed_sha") or ""),
        "current_sha": str(cand.get("current_sha") or ""),
        "sha_matches": bool(cand.get("signed_sha")
                            and cand.get("signed_sha") == cand.get("current_sha")),
        "state": str(state or ""), "why": str(why or ""),
    }


def signed_candidates(root: Any, *, families: Sequence[str],
                      role: str = "") -> dict[str, Any]:
    """本工作区里 `families` 各族的稿 × V 的颁发表 ⇒ 每个稿「该不该提交」。

    稿的身份是 `(family, manuscript_id)`，不是单号：E 的两族各走自己的号段
    （`e-proof` / `e-num` 都从 `000000` 起），F 的 `f-proof-000040` 与 B 的
    `b-proof-000040` 是同一条命题的两条路径 —— 三类都是不同的稿。
    只有「同族 + 同号 + 指到多份不同的文件」才是真的 `ambiguous_path`。

    纯读（不碰 store、不写盘）。读数形状与 `agent_f.submission.submission_candidates`
    同一套（`{checked, candidates, problems, why}`）—— 那一份只认 F 族，E 的两族
    要在这里按同一个判据读，不另造一套"签算不算签"的口径。每个候选带 `family`。
    """
    from . import vsigns as _VS

    wanted = tuple(str(f) for f in families if str(f))
    out: dict[str, Any] = {"checked": True, "candidates": [], "problems": [], "why": ""}
    root_p = Path(str(root or "."))
    d = _VS.signs_dir(root)
    try:
        files = (sorted(p for p in d.glob("*.json") if p.name != _VS.INDEX_NAME)
                 if d.is_dir() else [])
    except OSError as exc:  # noqa: BLE001
        out.update(checked=False, why=(
            f"`{_VS.SIGNS_DIR}/` 列不出来（{type(exc).__name__}: {exc}）⇒ "
            "拿签稿这一格没查成（不是「一份都没签」）"))
        return out
    #: 稿的身份 = `(族, 稿号)`，不是单号：E 的 `e-proof` / `e-num` 各有独立号段、
    #: 都从 `000000` 起；F 的 `f-proof-000040` 与 B 的 `b-proof-000040` 是同一条命题的
    #: 两条路径。单号分桶会把它们折成「一个号指到多份文件」⇒ 假 ambiguity。
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []

    def _bucket(family: str, mid: str) -> dict[str, Any]:
        key = (family, mid)
        one = by_key.get(key)
        if one is None:
            one = {"family": family, "manuscript_id": mid, "paths": [], "signs": [],
                   "statement_id": "", "proof_no": 0, "at": ""}
            by_key[key] = one
            order.append(key)
        return one

    for path in files:
        cred = _VS.credential_reading(root, path.stem)
        doc = dict(cred.get("sign") or {})
        if not doc:
            out["problems"].append(
                f"{path.name}：签读不出来（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
            continue
        if not cred.get("checked"):
            out["problems"].append(
                f"{path.name}：签的复算没查成（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
        rel = str(doc.get("artifact_path") or "").strip().replace("\\", "/")
        parsed = _MFAM.classify_manuscript(rel)
        family = str(parsed.get("family") or "")
        if family not in wanted:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            out["problems"].append(
                f"{path.name}：签的载体 {rel!r} 认不出稿号 ⇒ 不提交（不猜一个号）")
            continue
        sign_sha = ""
        try:
            sign_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:  # noqa: BLE001
            out["problems"].append(
                f"{path.name}：签文件读不出来（{type(exc).__name__}: {exc}）")
        one = _bucket(family, mid)
        if rel and rel not in one["paths"]:
            one["paths"].append(rel)
        one["signs"].append({
            "signed_sha": str(cred.get("artifact_sha") or path.stem).strip().lower(),
            "at": str(doc.get("at") or ""), "sign_sha": sign_sha,
            "recomputable": bool(cred.get("recomputable")),
            "code": str(cred.get("problem") or ""), "why": str(cred.get("why") or ""),
        })
        if not one["statement_id"]:
            one["statement_id"] = str(doc.get("statement_id") or "").strip()
        if not one["proof_no"]:
            one["proof_no"] = int(doc.get("proof_no") or 1)
        if str(doc.get("at") or "") > str(one["at"] or ""):
            one["at"] = str(doc.get("at") or "")
    report_paths: list[Path] = []
    reports = root_p / _MFAM.MANUSCRIPT_DIR
    for family in wanted:
        try:
            got = sorted(reports.glob(f"{_MFAM.prefix_of(family)}*.md"))
        except OSError as exc:  # noqa: BLE001
            got = []
            out["problems"].append(
                f"`reports/` 列不出 {family} 的稿（{type(exc).__name__}: {exc}）"
                " ⇒ 未签的那一半没查成")
        report_paths.extend(got)
    for path in sorted(set(report_paths)):
        rel = str(path.relative_to(root_p)).replace("\\", "/")
        parsed = _MFAM.classify_manuscript(rel)
        family = str(parsed.get("family") or "")
        if family not in wanted:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            continue
        one = _bucket(family, mid)
        if rel not in one["paths"]:
            one["paths"].append(rel)
        if not one["proof_no"]:
            one["proof_no"] = int(parsed.get("proof_no") or 1)
    for key in order:
        one = by_key[key]
        family, mid = key
        paths = [str(x) for x in (one.get("paths") or []) if str(x)]
        signs = [dict(x) for x in (one.get("signs") or [])]
        cand: dict[str, Any] = {
            "family": family,
            "manuscript_id": mid, "manuscript": paths[0] if paths else "",
            "proof_no": int(one.get("proof_no") or 0) or 1,
            "statement_id": str(one.get("statement_id") or ""),
            "signed_sha": "", "sign_sha": "", "at": str(one.get("at") or ""),
            "current_sha": "", "file_sha": "", "signed": False,
            "state": "", "why": "",
        }
        if len(paths) > 1:
            cand.update(state="ambiguous_path", why=(
                f"{family} 族同一个稿号指到多份不同的文件（"
                + "、".join(paths) + "）⇒ "
                "一稿号一文件，这一份不提交 —— 这里不替它挑「哪一版」"))
            out["candidates"].append(cand)
            continue
        rel = cand["manuscript"]
        if not rel:
            cand.update(state="manuscript_missing",
                        why="颁发表里这一份签没有 `artifact_path` ⇒ 没有地址可提交")
            out["candidates"].append(cand)
            continue
        try:
            blob = (root_p / rel).read_bytes()
        except OSError as exc:
            cand.update(state="manuscript_missing", why=(
                f"签的载体 `{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 不提交"))
            out["candidates"].append(cand)
            continue
        cand["file_sha"] = hashlib.sha256(blob).hexdigest()
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            cand.update(state="manuscript_unreadable",
                        why=f"签的载体 `{rel}` 不是 UTF-8 文本（{exc}）⇒ 不提交")
            out["candidates"].append(cand)
            continue
        cand["current_sha"] = _proof_sha(text)
        matching = [s for s in signs if s["signed_sha"] == cand["current_sha"]]
        if matching:
            hit = matching[0]
            cand.update(signed_sha=hit["signed_sha"], sign_sha=hit["sign_sha"],
                        at=str(hit["at"] or cand["at"]))
            if hit["recomputable"]:
                cand.update(signed=True, state="signed", why=(
                    f"已拿签（签 sha={hit['signed_sha']}，与现行正文一致）⇒ 可提交"))
            else:
                cand.update(state="sign_unbacked", why=(
                    f"签文件在、sha 也与现行正文一致（{hit['signed_sha']}），但复算不上"
                    f"（{hit['code'] or '?'}）：{hit['why']} ⇒ 不提交"))
        elif signs:
            latest = max(signs, key=lambda s: str(s.get("at") or ""))
            cand.update(signed_sha=latest["signed_sha"], sign_sha=latest["sign_sha"],
                        at=str(latest["at"] or ""), state="body_changed_after_sign",
                        why=(f"这一份签过之后正文又变了（签 sha={latest['signed_sha']} / "
                             f"现在 sha={cand['current_sha']}）⇒ 不提交"))
        else:
            cand.update(state="unsigned",
                        why="未签 ⇒ 不入提交单（V 的颁发表里没有这一份现行的签）")
        out["candidates"].append(cand)
    out["why"] = (f"颁发表里 {len(files)} 份签、盘上 {len(set(report_paths))} 份 "
                  f"{'/'.join(wanted)} 的稿 ⇒ {len(out['candidates'])} 份稿（族+号）"
                  + (f"；{len(out['problems'])} 条读数问题" if out["problems"] else ""))
    return out


def _select(candidates: list[dict[str, Any]], *, submitted: Mapping[str, Any],
            families_by_mid: Mapping[str, Any],
            row: Mapping[str, Any] | None, row_why: str, stamp: str,
            out: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """选谁：已签、sha 与现行正文一致、这一族的这一号在 artifacts 里还没有 ⇒ `(候选, 记号)`。

    幂等键是 (族, 稿号)：`e-proof-000000` 已提交不意味着 `e-num-000000` 已提交。
    老记号（没写族的）只在"这一号唯一地属于这一族"时才算数（`resolve_submission`
    的三态）；跨族同号却族定不下来 ⇒ 不拿它当已提交，并把「跨族同号、无法唯一定位」
    写进 `out["problems"]`（不静默地替两族猜一份）。
    """
    pending: list[tuple[dict[str, Any], str]] = []
    for cand in candidates:
        mid = str(cand.get("manuscript_id") or "")
        if not mid:
            continue
        fam = str(cand.get("family") or "")
        hit, reading = resolve_submission(submitted, family=fam, manuscript_id=mid,
                                          families=families_by_mid.get(mid, ()))
        if str(reading.get("state") or "") == "ambiguous":
            why = str(reading.get("why") or "")
            if why and why not in out["problems"]:
                out["problems"].append(why)
        if hit is not None:
            out["still_unsubmitted"].append(_still(
                cand, "already_submitted",
                f"`tasks.artifacts` 里已经有 {fam} 稿号 {mid} 的提交记号 ⇒ 幂等：不重复写"))
            continue
        if not cand.get("signed"):
            out["still_unsubmitted"].append(_still(
                cand, str(cand.get("state") or "unsigned"),
                str(cand.get("why") or "没有可提交的签 ⇒ 不入提交单")))
            continue
        if row is None:
            out["still_unsubmitted"].append(_still(
                cand, "no_task_row",
                row_why or "没有可写的台账行 ⇒ 这一份拿签稿没提交"))
            continue
        try:
            token = submission_token(
                manuscript_id=mid, family=fam,
                path=str(cand.get("manuscript") or ""),
                body_sha=str(cand.get("signed_sha") or ""),
                sign_sha=str(cand.get("sign_sha") or ""),
                file_sha=str(cand.get("file_sha") or ""),
                proof_no=int(cand.get("proof_no") or 1),
                statement_id=str(cand.get("statement_id") or ""),
                at=str(cand.get("at") or stamp), submitted_at=stamp,
                # 收工这一条路（E）：签触发那一条写 `sign_issued`。
                via=VIA_CLOSING)
        except ValueError as exc:
            out["still_unsubmitted"].append(_still(cand, "bad_token", str(exc)))
            continue
        pending.append((cand, token))
    return pending


def auto_submit_for(*, store: Any, root: Any, role: str,
                    families: Sequence[str], task_id: str = "",
                    stamp: str = "") -> dict[str, Any]:
    """收工自动提交（E 用；F 自己那份在 `agent_f/autosubmit.py`）。

    选谁：`families` 里已签（签 sha == 当前正文 sha）、尚未提交的稿；记号写到
    「`role` 自己那一行 task」的 `artifacts`（同一套 `mss:` 格式）。幂等按 (族, 稿号)：
    `e-proof-000000` 已提交不意味着 `e-num-000000` 已提交（E 的两族各走自己的号段，
    同号是常态）。未签不提交、签后改正文不提交两条与 F 一致；没有 task 行时逐条落
    `no_task_row`，且不静默。
    """
    out: dict[str, Any] = {
        "checked": False, "auto_submitted": [], "auto_submitted_count": 0,
        "still_unsubmitted": [], "problems": [], "task_id": str(task_id or ""),
        "role": str(role or ""), "families": list(families), "why": "",
    }
    try:
        scan = signed_candidates(root, families=families, role=role)
    except Exception as exc:  # noqa: BLE001 —— 收工读数坏了不能把「停」带走
        out["why"] = (f"拿签稿扫描没跑成（{type(exc).__name__}: {exc}）"
                      " ⇒ 这一趟没有自动提交（不是「没有要提交的」）")
        return out
    out["checked"] = bool(scan.get("checked"))
    out["problems"] = [str(x) for x in (scan.get("problems") or [])]
    candidates = [dict(c) for c in (scan.get("candidates") or [])
                  if isinstance(c, Mapping)]
    #: 这一趟的候选里，每个号出现在哪几族（老记号没写族时"唯一确定"要靠它）。
    families_by_mid: dict[str, list[str]] = {}
    for cand in candidates:
        cand_mid = str(cand.get("manuscript_id") or "")
        cand_fam = str(cand.get("family") or "")
        if cand_mid and cand_fam:
            families_by_mid.setdefault(cand_mid, [])
            if cand_fam not in families_by_mid[cand_mid]:
                families_by_mid[cand_mid].append(cand_fam)
    tasks, tasks_why = _read_tasks(store)
    submitted, _, token_problems = _task_tokens(
        [r for r in tasks if str(r.get("role") or "") == str(role)])
    out["problems"] += token_problems
    row: dict[str, Any] | None = None
    row_why = ""
    tid = str(task_id or "")
    if not tid:
        row_why = ("没有召唤号（`task_id` 是空的）⇒ 没有「自己那一行」可写")
    else:
        found = next((r for r in tasks if str(r.get("task_id") or "") == tid), None)
        if found is None:
            row_why = f"召唤号 {tid!r} 不在 `tasks` 表里 ⇒ 没有「自己那一行」可写"
        elif str(found.get("role") or "") != str(role):
            row_why = (f"召唤号 {tid!r} 那一行的角色是 {found.get('role')!r}，"
                       f"不是 {role}")
        elif str(found.get("status") or "") in TERMINAL_TASK_STATUSES:
            row_why = (f"召唤号 {tid!r} 那一行已经是终态 {found.get('status')!r} ⇒ "
                       "不再往终态行写产物")
        else:
            row = found
    if not tasks and tasks_why:
        out["problems"].append(tasks_why)
    pending = _select(candidates, submitted=submitted,
                      families_by_mid=families_by_mid,
                      row=row, row_why=row_why,
                      stamp=str(stamp or ""), out=out)
    if not pending:
        out["why"] = ("没有「已拿签、尚未提交」的稿 ⇒ 这一趟不写 artifacts"
                      if not out["still_unsubmitted"] else
                      "有稿文件，但这一趟没有一份可提交 ⇒ 逐条理由见 still_unsubmitted")
        return out
    fresh: list[str] = []
    write_error = ""
    try:
        with store.tx("tasks", actor=str(role), note=f"{str(role).lower()}.close:auto_submit") as tx:
            cur = tx.find("tasks", task_id=tid)
            if cur is None:
                write_error = f"事务里找不到 {tid!r} 那一行"
            else:
                existing: dict[str, dict[str, Any]] = {}
                for one in tx.rows("tasks"):
                    if str(one.get("role") or "") != str(role):
                        continue
                    got, bad = submissions_of(one.get("artifacts") or ())
                    out["problems"] += bad
                    for key, rec in got.items():
                        existing.setdefault(str(key), dict(rec))
                for cand, token in pending:
                    cand_mid = str(cand.get("manuscript_id") or "")
                    cand_fam = str(cand.get("family") or "")
                    hit, _reading = resolve_submission(
                        existing, family=cand_fam, manuscript_id=cand_mid,
                        families=families_by_mid.get(cand_mid, ()))
                    if hit is None:
                        fresh.append(token)
                if fresh:
                    cur["artifacts"] = S.sorted_unique(
                        list(cur.get("artifacts") or ()) + fresh)
                    tx.upsert("tasks", cur,
                              note=f"{str(role).lower()}.close:auto_submit")
    except Exception as exc:  # noqa: BLE001 —— 写不进去必须如实说
        write_error = f"{type(exc).__name__}: {exc}"
    if write_error:
        out["checked"] = False
        out["why"] = f"自动提交没写成（{write_error}）⇒ 这一趟一份都没提交"
        for cand, _token in pending:
            out["still_unsubmitted"].append(_still(cand, "write_failed", out["why"]))
        return out
    fresh_set = set(fresh)
    for token in fresh:
        rec = dict(parse_submission(token) or {})
        out["auto_submitted"].append({
            "manuscript_id": str(rec.get("manuscript_id") or ""),
            "family": str(rec.get("family") or ""),
            "manuscript": str(rec.get("path") or ""),
            "proof_no": int(rec.get("proof_no") or 0) or 1,
            "body_sha": str(rec.get("body_sha") or ""),
            "signed_sha": str(rec.get("body_sha") or ""),
            "sign_sha": str(rec.get("sign_sha") or ""),
            "file_sha": str(rec.get("file_sha") or ""),
            "at": str(rec.get("at") or ""),
            "submitted_at": str(rec.get("submitted_at") or ""),
            "via": VIA_CLOSING, "token": token,
        })
    for cand, token in pending:
        if token in fresh_set:
            continue
        out["still_unsubmitted"].append(_still(
            cand, "already_submitted",
            "写这一趟之前，同一 (族, 稿号) 的提交记号已经被另一次收工写进 "
            "`artifacts`（并发幂等）"))
    out["auto_submitted_count"] = len(out["auto_submitted"])
    out["why"] = (f"这一趟自动提交 {out['auto_submitted_count']} 份拿签稿"
                  + (f"；另有 {len(out['still_unsubmitted'])} 份没提交"
                     "（逐条理由见 still_unsubmitted）"
                     if out["still_unsubmitted"] else ""))
    return out


