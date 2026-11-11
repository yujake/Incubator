# -*- coding: utf-8 -*-
"""手稿的「产出方」与「已提交」读数（2026-11-11 业主裁定 ①②③ 的共同落点）。

## 这一层回答三个问题（三块共用，别各写一份）

1. 这份稿的产出方是谁（甲）：事实来源只有手稿路径的族前缀
   （`reports/f-proof-*` ⇒ F；`reports/e-proof-*` / `e-num-*` ⇒ E；
   `reports/b-proof-*` ⇒ B）—— :func:`producer_of`。它再拿
   `capabilities.ALLOWED_EDGES` 现算「V 的父名单」做校验（不写死一张字面量表）。
2. 这份稿提交了没有、怎么提交的（乙 / 丙 / 统一读口）：
   :func:`submission_reading` 把三处 join 起来 —— 路径族、V 的颁发表
   （`out/vsigns/<正文 sha>.json`）、`tasks.artifacts` 里的 `mss:` 记号。
3. 收工（E）与收录（B）各写哪一枚记号：:func:`auto_submit_for` 与
   :func:`mark_ingested`。两个都复用 `agent_f/submission.py` 的那一套
   `mss:` 记号拼装 / 解析（本模块不新造字符串格式）。

## 三态纪律

- `checked=False` = 这一格没查成（目录列不出来 / 台账读不出来），
  不是「没有已签稿」、也不是「没有提交」；
- 老验证行没有 `producer_role` 这一格 ⇒ :func:`verification_producer_reading`
  读 `unknown`，不按族硬填一个 F；
- 族认不出（坏路径 / `notes/` / `legacy`）⇒ `producer_role="unknown"` 并带理由，
  不猜一个角色。

## 边（V 的父名单）

`ALLOWED_EDGES` 的形状是 `dict[str, frozenset[str]]`（角色 → 它能召唤的角色），
不是 `list[tuple]`。所以「谁是 V 的父」= 所有值里含 `"V"` 的那些键；见
:func:`parents_of`。这一格每次现读 capabilities，不缓存、不抄一份常量表。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import manuscriptfamily as _MFAM
from . import schema as S

#: 稿族 ⇒ 产出方角色（唯一一张映射表；事实来源仍是路径族，不是调用方自报）。
PRODUCER_OF_FAMILY: dict[str, str] = {
    "f-proof": "F",
    "b-proof": "B",
    "e-proof": "E",
    "e-num": "E",
}

#: 「已提交」记号的前缀与字段 —— 真身在 `agent_f/submission.py`，这里只做懒引用。
SUBMISSION_PREFIX = "mss:"

#: 任务的终态（`block` 不算：它能被唤醒，不是终态）。
TERMINAL_TASK_STATUSES: tuple[str, ...] = tuple(
    s for s in S.TASK_STATUSES if s not in ("pending", "running", "block"))

#: `via` 的两档（统一读口的三条读数之一）：F/E 走收工自动提交，B 走收录。
VIA_CLOSING = "closing_auto_submit"
VIA_INGEST = "ingested_to_ledger"

UNKNOWN = "unknown"


# --------------------------------------------------------------------- 记号（复用 F 那一套）
def _submission():
    """懒取 `agent_f.submission`（它那套 `mss:` 记号格式/解析器是唯一真身）。"""
    from .agent_f import submission as _SUB

    return _SUB


def submission_token(**kwargs: Any) -> str:
    """拼一枚 `mss:` 记号（薄转发，格式由 `agent_f/submission.py` 定义）。"""
    return _submission().submission_token(**kwargs)


def parse_submission(token: Any) -> dict[str, Any] | None:
    return _submission().parse_submission(token)


def submissions_of(artifacts: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    return _submission().submissions_of(artifacts)


from .manuscriptproducers import (
    PRODUCER_OF_FAMILY, UNKNOWN, _manuscript_id_of, parents_of, producer_of,
    verification_producer_reading,
)
from .manuscriptpaths import (  # 多证明路径号（B 收录时分配）
    assign_path_group, path_reading, stamp_verification_path_group,
)
# --------------------------------------------------------------------- 盘上事实
def _proof_sha(text: str) -> str:
    """`## 证明` 那一节的 sha256（全仓一把尺：`proofregistry.proof_sha`）。"""
    from . import proofregistry as _PR

    return _PR.proof_sha(text)


def _sign_reading(root: Any, body_sha: str) -> dict[str, Any]:
    """V 的颁发表里那一份签（逐份文件；`issued.json` 只是派生归档，不拿它下结论）。"""
    from . import vsigns as _VS

    sha = str(body_sha or "").strip().lower()
    if len(sha) != 64:
        return {"checked": False, "found": False, "signed": False, "sign": {},
                "sign_sha": "", "at": "", "why": "没有可查的正文 sha"}
    got = _VS.credential_reading(root, sha)
    doc = dict(got.get("sign") or {})
    sign_sha = ""
    path = str(got.get("path") or "")
    if path:
        try:
            sign_sha = hashlib.sha256((Path(str(root)) / path).read_bytes()).hexdigest()
        except OSError:
            sign_sha = ""
    return {
        "checked": bool(got.get("checked")), "found": bool(got.get("found")),
        "signed": bool(doc) and bool(got.get("recomputable")),
        "recomputable": bool(got.get("recomputable")),
        "sign": doc, "sign_sha": sign_sha, "at": str(doc.get("at") or ""),
        "artifact_sha": str(got.get("artifact_sha") or ""),
        "why": str(got.get("why") or ""),
    }


def _read_tasks(store: Any) -> tuple[list[dict[str, Any]], str]:
    if store is None:
        return [], "没有 store ⇒ `tasks.artifacts` 读不到（不是「没有提交」）"
    try:
        return [dict(r) for r in store.rows("tasks")], ""
    except Exception as exc:  # noqa: BLE001
        return [], f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"


def _task_tokens(tasks: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]],
                                                             dict[str, dict[str, Any]],
                                                             list[str]]:
    """`tasks.artifacts` ⇒ `({稿号: 记号}, {稿号: 写记号的那一行}, 问题)`。"""
    tokens: dict[str, dict[str, Any]] = {}
    owners: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for row in tasks or ():
        got, bad = submissions_of((row or {}).get("artifacts") or ())
        problems.extend(bad)
        for mid, rec in got.items():
            tokens.setdefault(str(mid), dict(rec))
            owners.setdefault(str(mid), dict(row or {}))
    return tokens, owners, problems


def _manuscript_id_of(rel: str) -> str:
    return str(_MFAM.classify_manuscript(rel).get("manuscript_id") or "")


def _find_rel_for_mid(root: Any, mid: str) -> str:
    """按稿号在 `reports/` 下找那份稿（一稿号一文件；多份 ⇒ 空串，不挑一版）。"""
    if not mid:
        return ""
    hits: list[str] = []
    base = Path(str(root))
    for family in _MFAM.FAMILY_ORDER:
        prefix = _MFAM.prefix_of(family)
        d = base / _MFAM.MANUSCRIPT_DIR
        try:
            paths = sorted(d.glob(f"{prefix}{mid}*.md")) if d.is_dir() else []
        except OSError:
            paths = []
        for path in paths:
            rel = f"{_MFAM.MANUSCRIPT_DIR}/{path.name}"
            if _manuscript_id_of(rel) == mid:
                hits.append(rel)
    uniq = sorted(set(hits))
    return uniq[0] if len(uniq) == 1 else ""


# --------------------------------------------------------------------- B：收录即提交
def _task_row_for(store: Any, *, role: str, task_id: str) -> tuple[dict[str, Any] | None,
                                                                  str]:
    tasks, why = _read_tasks(store)
    if why:
        return None, why
    tid = str(task_id or "")
    if not tid:
        return None, "这一趟没有召唤号 ⇒ 没有可写的 task 行"
    found = next((r for r in tasks if str(r.get("task_id") or "") == tid), None)
    if found is None:
        return None, f"召唤号 {tid!r} 不在 `tasks` 表里 ⇒ 没有可写的 task 行"
    if str(found.get("role") or "") != str(role):
        return None, (f"召唤号 {tid!r} 那一行的角色是 {found.get('role')!r}，"
                      f"不是 {role}")
    if str(found.get("status") or "") in TERMINAL_TASK_STATUSES:
        return None, f"召唤号 {tid!r} 那一行已经是终态 {found.get('status')!r}"
    return found, ""


def mark_ingested(*, store: Any, root: Any, manuscript: Any, out: dict[str, Any],
                  task_id: str = "", stamp: str = "") -> dict[str, Any]:
    """B 把一份 `b-proof-*` 存进台账（收录成功）时，在 B 自己那一行写提交记号。

    只在 `out["ok"] is True` 且路径族是 `b-proof` 时动手；受控拒 / 别的族 ⇒ 原样返回，
    不写一个字节。没有 task 行时把理由写进 `out["b_submission"]`（不静默）。
    幂等：所有 B 行里已有该稿号的记号 ⇒ 不再写。
    """
    rel = str(manuscript or "").strip().replace("\\", "/")
    result: dict[str, Any] = {"checked": False, "written": False, "already": False,
                              "manuscript_id": "", "token": "", "via": VIA_INGEST,
                              "path_group": int((out.get("path_group") or {}).get(
                                  "path_group") or 0),
                              "why": ""}
    out["b_submission"] = result
    if not isinstance(out, dict) or not bool(out.get("ok")):
        result["why"] = "收录没有成功（受控拒 / 未写成）⇒ 不置已提交"
        return out
    if not task_id:
        try:
            from . import conductor as _CND

            task_id = str(_CND.current_task_id() or "")
        except Exception:  # noqa: BLE001 —— 读不到就是没有 task 行
            task_id = ""
    if not stamp:
        stamp = S.now_iso()
    prod = producer_of(rel)
    if str(prod.get("producer_role") or "") != "B":
        result["why"] = (f"`{rel}` 不是 B 的稿（产出方 "
                         f"{prod.get('producer_role') or 'unknown'}）⇒ 这一笔不写 B 的提交记号")
        result["checked"] = True
        return out
    mid = str(prod.get("manuscript_id") or "")
    result["manuscript_id"] = mid
    path = Path(str(root)) / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        result["why"] = f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 提交记号写不了"
        return out
    body_sha = _proof_sha(text)
    sign = _sign_reading(root, body_sha)
    sign_rec = dict(sign.get("sign") or {})
    stmt_id = str((out.get("target") or {}).get("stmt_id")
                  or (out.get("register") or {}).get("stmt_id")
                  or out.get("stmt_id") or "")
    row, row_why = _task_row_for(store, role="B", task_id=task_id)
    if row is None:
        result.update(checked=True, why=f"没有 task 行可写：{row_why}")
        return out
    tasks, _why = _read_tasks(store)
    submitted, _owners, _bad = _task_tokens(
        [r for r in tasks if str(r.get("role") or "") == "B"])
    if mid in submitted:
        result.update(checked=True, already=True, why=(
            f"`tasks.artifacts` 里已经有稿号 {mid} 的提交记号 ⇒ 幂等：不重复写"))
        return out
    try:
        token = submission_token(
            manuscript_id=mid, path=rel, body_sha=body_sha,
            sign_sha=str(sign.get("sign_sha") or ""), file_sha=hashlib.sha256(
                path.read_bytes()).hexdigest(),
            proof_no=int(sign_rec.get("proof_no") or prod.get("proof_no") or 1),
            statement_id=stmt_id, at=str(sign.get("at") or ""),
            submitted_at=str(stamp or ""))
    except (ValueError, OSError) as exc:
        result["why"] = f"提交记号拼不出来（{type(exc).__name__}: {exc}）"
        return out
    try:
        with store.tx("tasks", actor="B", note="b.ingest:auto_submit") as tx:
            cur = tx.find("tasks", task_id=str(task_id))
            if cur is None:
                result["why"] = f"事务里找不到 {task_id!r} 那一行 ⇒ 提交记号没写"
                return out
            existing: set[str] = set()
            for one in tx.rows("tasks"):
                if str(one.get("role") or "") != "B":
                    continue
                got, _bad = submissions_of(one.get("artifacts") or ())
                existing.update(str(x) for x in got)
            if mid in existing:
                result.update(checked=True, already=True,
                              why=f"并发下另一笔已经写了 {mid} 的提交记号")
                return out
            cur["artifacts"] = S.sorted_unique(list(cur.get("artifacts") or ()) + [token])
            tx.upsert("tasks", cur, note="b.ingest:auto_submit")
    except Exception as exc:  # noqa: BLE001
        result["why"] = f"提交记号写不进 `tasks`（{type(exc).__name__}: {exc}）"
        return out
    result.update(checked=True, written=True, token=token,
                  why=f"收录成功 ⇒ 稿 {mid} 置为已提交（via={VIA_INGEST}）")
    return out


def submission_reading(store: Any, root: Any, *, manuscript: Any = "",
                       manuscript_id: Any = "", producer_code: str = "") -> dict[str, Any]:
    """统一读口：给定稿号 / 路径 ⇒ 产出方 + 提交状态 + 时刻 + via。

    三处 join：
    1. 路径族（`manuscriptfamily.classify_manuscript`）⇒ `producer_role`；
    2. V 的颁发表（`out/vsigns/<正文 sha>.json`）⇒ `signed` / `signed_sha` / `sign_sha`；
    3. `tasks.artifacts` 里的 `mss:` 记号 ⇒ `state` / `submitted_at` / `via`。

    `via`：F / E 的稿 ⇒ `closing_auto_submit`；B 的稿 ⇒ `ingested_to_ledger`。
    没有记号 ⇒ `state="unsubmitted"`、`submitted_at=""`、`via=""`（不是「没查」）。
    老验证行的产出方格由 :func:`verification_producer_reading` 读（缺格 ⇒ unknown）。
    """
    mid = str(manuscript_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    tasks, tasks_why = _read_tasks(store)
    tokens, owners, problems = _task_tokens(tasks)
    if not mid:
        mid = _manuscript_id_of(rel) if rel else ""
    if not rel and mid:
        rec = tokens.get(mid)
        if rec and rec.get("path"):
            rel = str(rec["path"])
        else:
            rel = _find_rel_for_mid(root, mid)
    if not mid and rel:
        mid = _manuscript_id_of(rel)
    prod = producer_of(rel) if rel else {
        "producer_role": UNKNOWN, "producer_code": "", "family": "", "tier": "",
        "manuscript_id": mid, "checked": False, "why": "没有稿路径 ⇒ 产出方 unknown"}
    rec = dict(tokens.get(mid) or {})
    owner = dict(owners.get(mid) or {})
    signed_sha = str(rec.get("body_sha") or "")
    if not signed_sha and rel:
        try:
            signed_sha = _proof_sha((Path(str(root)) / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            signed_sha = ""
    sign = _sign_reading(root, signed_sha) if signed_sha else {
        "checked": False, "found": False, "signed": False, "sign": {},
        "sign_sha": "", "at": "", "why": "没有正文 sha ⇒ 签查不了"}
    role = str(prod.get("producer_role") or UNKNOWN)
    if rec:
        via = VIA_INGEST if role == "B" else VIA_CLOSING
        state = "submitted"
    else:
        via, state = "", "unsubmitted"
    out: dict[str, Any] = {
        "checked": True, "manuscript": rel, "manuscript_id": mid,
        "producer_role": role,
        "producer_code": str(producer_code or prod.get("producer_code") or ""),
        "state": state, "submitted_at": str(rec.get("submitted_at") or ""),
        "via": via,
        "signed": bool(sign.get("signed")),
        "signed_sha": str(sign.get("artifact_sha") or signed_sha),
        "sign_sha": str(sign.get("sign_sha") or ""),
        "sign_at": str(sign.get("at") or ""),
        "token": str(rec.get("token") or ""),
        "task_id": str(owner.get("task_id") or ""),
        "task_role": str(owner.get("role") or ""),
        "problems": list(problems), "why": "",
    }
    if tasks_why:
        out["problems"].append(tasks_why)
    if role != UNKNOWN and owner and str(owner.get("role") or "") != role:
        out["problems"].append(
            f"写提交记号的是 {owner.get('role')}（{owner.get('task_id')}），"
            f"而路径族说产出方是 {role}")
    if not rel:
        out["checked"] = False
        out["why"] = ("没有手稿路径 / 稿号 ⇒ 这一格没查成（不是「没有提交」）")
    elif not rec:
        out["why"] = (f"`tasks.artifacts` 里没有稿号 {mid or '?'} 的 `mss:` 记号 ⇒ "
                      "未提交（via 没有来源）")
    else:
        out["why"] = (f"已提交（via={via}，submitted_at={out['submitted_at'] or '未记录'}）")
    return out
