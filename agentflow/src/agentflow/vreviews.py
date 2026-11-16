# -*- coding: utf-8 -*-
"""V 稿：V 的秘书判出「有毛病」时，给被审者（F / E / B）的审阅报告。

业主 2026-11-16 的裁定（原文见 SG1 施工单）：

- ⑤ 有毛病 ⇒ 落 V 稿：审的是哪份稿（族 + 号 + sha）/ 有毛病 / findings 与理由
  （含 warning 与程序性 fault）；
- ⑥ 落盘 `verifications/reviews/v-review-NNNNNN.md` + `index.jsonl`；
  号源 = 索引 max + 1（不用 `store.alloc_id` / counters）；
  幂等键 = 台账锚点（台账路径, verification_id）—— 因为未在册 pending 行没有
  `review_call`；
- ⑦ 交付 = `conductor.open_item` 的 notice，不要求 ack（`expects=""`）。

## 为什么号源读索引而不是 `store.alloc_id`

V 稿不是 `tasks` / `statements` 那种 store 表里的行：它住在 `verifications/reviews/`
这一层文件里，索引就是它的台账。拿 `store.alloc_id` 会造出一个与索引无关的号源，
两份号一旦漂开，"v-review-000007" 就可能对应两份不同的报告。索引是唯一真身，
号源也只能从它现读。

## 幂等键为什么是（台账路径, verification_id）

在册那一签的锚点是 `verifications/<命题号>.jsonl#v-…`；未在册那一签的锚点是
`verifications/pending/<正文 sha>.jsonl#u-…`（没有 `review_call`）。两条路的共同
可定位事实只有这两格，所以幂等键取它们。同一行判定被重复投递时只回旧那一份，
不追加第二个编号、也不覆盖盘上那一份。

## 三态

`record_review` 的 `checked` 是"这一格查成了没有"：索引读不出来 / 写盘失败 ⇒
`checked=False`，`written=False`，理由点名。`idempotent=True` 是"查成了、盘上已有
同一锚点的那一份"——它不是失败，也不是"又写了一份"。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Mapping

#: V 稿目录（工作区根相对；索引也在这里）。
REVIEWS_DIR = "verifications/reviews"
#: 索引名（一份报告一行；号源从它现读）。
INDEX_NAME = "index.jsonl"
#: 报告文件名前缀（`v-review-NNNNNN.md`）。
PREFIX = "v-review-"
#: 板项 `input_key` 前缀：V 稿（不是 ack 项，见 `conductor.ACK_REQUIRED_ITEM_PREFIXES`）。
REVIEW_PREFIX = "v-review@"
#: 板项 `input_key` 前缀：签好的稿（同一份稿的一次送审一条）。
SIGNED_PREFIX = "v-signed@"

_ID_RE = re.compile(r"^v-review-(\d{6,})$")
_LOCKS: dict[str, Any] = {}
_LOCKS_GUARD = threading.Lock()


def reviews_dir(root: str | Path) -> Path:
    """V 稿目录（只算路径，不建目录）。"""
    return Path(str(root)).joinpath(*REVIEWS_DIR.split("/"))


def reviews_index_path(root: str | Path) -> Path:
    """V 稿索引 `verifications/reviews/index.jsonl`。"""
    return reviews_dir(root) / INDEX_NAME


def review_path(root: str | Path, review_id: str) -> Path:
    """一份 V 稿的路径（只算路径）。"""
    return reviews_dir(root) / f"{str(review_id)}.md"


def _lock_for(path: Path):
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _read_index(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读索引：返回 `(行, 坏行说明)`；文件不存在 = 还没有报告（不是坏）。"""
    path = reviews_index_path(root)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return rows, problems
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"索引读不出来（{type(exc).__name__}: {exc}）"]
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            got = json.loads(line)
        except ValueError as exc:
            problems.append(f"索引第 {i} 行不是合法 JSON（{exc}）")
            continue
        if not isinstance(got, dict):
            problems.append(f"索引第 {i} 行不是对象")
            continue
        rows.append(got)
    return rows, problems


def next_review_id(rows: list[Mapping[str, Any]]) -> str:
    """索引的 max + 1（宽度 6；解析不出的行不参与发号，但不许把它们当 0）。"""
    top = 0
    for row in rows:
        got = _ID_RE.match(str(row.get("review_id") or ""))
        if got:
            top = max(top, int(got.group(1)))
    return f"{PREFIX}{top + 1:06d}"


def _anchor(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("ledger") or ""), str(row.get("verification_id") or ""))


def find_review(root: str | Path, *, ledger: str,
                verification_id: str) -> dict[str, Any] | None:
    """按台账锚点找已经落过的那一份（找不到 ⇒ `None`）。"""
    rows, _problems = _read_index(root)
    want = (str(ledger or ""), str(verification_id or ""))
    if not want[1]:
        return None
    return next((dict(r) for r in rows if _anchor(r) == want), None)


def _rel(root: str | Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(str(root)).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _atomic_write(path: Path, text: str) -> None:
    """LF 落盘 + 原子替换（临时文件与目标同目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _append_index(path: Path, row: Mapping[str, Any]) -> None:
    """追加一行（一次 write；追加式文件不改历史行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line)


def _finding_lines(findings: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in findings:
        level = str(item.get("level") or "info")
        step = item.get("step")
        where = f"第 {step} 步" if isinstance(step, int) and not isinstance(step, bool) else "未指步"
        kind = str(item.get("kind") or "").strip()
        detail = str(item.get("detail") or "").strip()
        head = f"- [{level}] {where}"
        if kind:
            head += f" · {kind}"
        out.append(head + (f"：{detail}" if detail else ""))
    return out


def _render(*, review_id: str, at: str, statement_id: str, manuscript: str,
            manuscript_family: str, manuscript_id: str, proof_sha256: str,
            verdict: str, defect_step: Any, findings: list[Mapping[str, Any]],
            reason: str, fault_kind: str, fault_cause: str, ledger: str,
            verification_id: str) -> str:
    """把一份判定摊成给人读的 V 稿（内容只有事实与理由，不写价值判断）。"""
    lines: list[str] = [
        f"# V 审阅报告 {review_id}",
        "",
        f"- 生成时间：{at}",
        f"- 被审稿：`{manuscript or '（没有手稿路径）'}`",
        f"- 稿族 / 稿号：`{manuscript_family or '（读不出）'}` / `{manuscript_id or '（读不出）'}`",
        f"- 被审正文 sha256：`{proof_sha256 or '（读不出）'}`",
        f"- 结论：有毛病（V 的秘书语义判定：fault）",
        f"- 判词原文：{verdict or '（没有原文）'}",
        f"- 缺陷步：{('第 %s 步' % defect_step) if isinstance(defect_step, int) else '未指步'}",
        f"- 缺陷类别：{fault_kind or '（没给）'}"
        + (f"（{fault_cause}）" if fault_cause else ""),
        f"- 台账锚点：`{ledger}#{verification_id}`",
    ]
    if statement_id:
        lines.append(f"- 命题号（若在册）：`{statement_id}`")
    lines.extend(["", "## findings（含 warning）", ""])
    body = _finding_lines(findings)
    lines.extend(body or ["- （这一转没有逐条 finding；理由见下一节）"])
    lines.extend(["", "## 理由", "", reason.strip() or "（没有给理由）", ""])
    lines.extend([
        "## 判据（写报告的人与读报告的人都按这一条读）",
        "",
        "- 只要不是完全没毛病就叫有毛病；`warning` 也算有毛病。",
        "- 程序性 / 文风 fault 同样落这份报告（它不是对数学缺陷的认定，但它是"
        "「这一份没有通过」的读数）。",
        "",
    ])
    return "\n".join(lines)


def record_review(root: str | Path, *, statement_id: str, manuscript: str,
                  manuscript_family: str, manuscript_id: str,
                  proof_sha256: str, verdict: str, defect_step: Any,
                  findings: list[Mapping[str, Any]] | None, reason: str,
                  ledger: str, verification_id: str, fault_kind: str = "",
                  fault_cause: str = "", review_call: str = "", at: str = "",
                  actor: str = "agent-V") -> dict[str, Any]:
    """落一份 V 稿（幂等；号源 = 索引 max + 1）。

    返回 `checked` / `written` / `idempotent` / `review_id` / `path` / `rel` /
    `index_path` / `sha256` / `at` / `reason` / `entry`。
    """
    at = str(at or "").strip()
    gate = reviews_dir(root)
    out: dict[str, Any] = {
        "checked": False, "written": False, "idempotent": False,
        "review_id": "", "path": "", "rel": "", "index_path": str(reviews_index_path(root)),
        "sha256": "", "at": at, "reason": "", "entry": {},
        "statement_id": str(statement_id or ""), "ledger": str(ledger or ""),
        "verification_id": str(verification_id or ""),
    }
    if not str(verification_id or "").strip() or not str(ledger or "").strip():
        out["reason"] = ("没有台账锚点（台账路径 / verification_id）⇒ 这一份 V 稿"
                         "没有幂等键，不落盘（不许靠猜一个编号写第二份）")
        return out
    lock = _lock_for(gate)
    with lock:
        rows, problems = _read_index(root)
        if problems:
            out["reason"] = ("V 稿索引读不出来 ⇒ 不发新号、不落盘："
                             + "；".join(problems[:3]))
            return out
        existing = next((dict(r) for r in rows
                         if _anchor(r) == (str(ledger), str(verification_id))), None)
        if existing is not None:
            out.update(checked=True, idempotent=True, written=False,
                       review_id=str(existing.get("review_id") or ""),
                       path=str(review_path(root, str(existing.get("review_id") or ""))),
                       rel=str(existing.get("path") or ""),
                       sha256=str(existing.get("sha256") or ""),
                       at=str(existing.get("at") or at),
                       reason="同一台账锚点已经落过一份 V 稿 ⇒ 回旧的，不写第二份",
                       entry=existing)
            return out
        review_id = next_review_id(rows)
        path = review_path(root, review_id)
        rel = _rel(root, path)
        items = [dict(f) for f in (findings or []) if isinstance(f, Mapping)]
        text = _render(
            review_id=review_id, at=at, statement_id=str(statement_id or ""),
            manuscript=str(manuscript or ""),
            manuscript_family=str(manuscript_family or ""),
            manuscript_id=str(manuscript_id or ""),
            proof_sha256=str(proof_sha256 or ""), verdict=str(verdict or ""),
            defect_step=defect_step, findings=items, reason=str(reason or ""),
            fault_kind=str(fault_kind or ""), fault_cause=str(fault_cause or ""),
            ledger=str(ledger), verification_id=str(verification_id))
        try:
            _atomic_write(path, text)
        except OSError as exc:
            out["reason"] = f"V 稿写不进去（{type(exc).__name__}: {exc}）"
            return out
        entry = {
            "review_id": review_id, "at": at, "path": rel,
            "statement_id": str(statement_id or ""),
            "manuscript": str(manuscript or ""),
            "manuscript_family": str(manuscript_family or ""),
            "manuscript_id": str(manuscript_id or ""),
            "proof_sha256": str(proof_sha256 or ""),
            "verdict": str(verdict or ""), "axis": "fault",
            "defect_step": defect_step, "fault_kind": str(fault_kind or ""),
            "fault_cause": str(fault_cause or ""),
            "findings": len(items), "ledger": str(ledger),
            "verification_id": str(verification_id),
            "review_call": str(review_call or ""),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "actor": str(actor or ""),
        }
        try:
            _append_index(reviews_index_path(root), entry)
        except OSError as exc:
            out["reason"] = (f"V 稿索引写不进去（{type(exc).__name__}: {exc}）"
                             f"；正文已落 `{rel}`，但索引缺这一行，必须重落")
            return out
        out.update(checked=True, written=True, review_id=review_id,
                   path=str(path), rel=rel, entry=entry,
                   sha256=entry["sha256"],
                   reason=f"V 稿已落盘：{rel}")
        return out


def _conductor_for(store: Any) -> Any:
    """取这个工作区已经存在的主控；没有 ⇒ `None`（不顺手建一个）。"""
    from .tools.conductor_tools import cached_conductor

    return cached_conductor(store)


def _deliver(store: Any, root: str | Path, *, key: str, summary: str,
             detail: str, role_hint: str = "", actor: str = "agent-V",
             depth: int = 1) -> dict[str, Any]:
    """开一条不要求 ack 的 notice 板项 + 写 detail（V 稿 / 签好的稿共用）。"""
    out: dict[str, Any] = {
        "checked": False, "state": "", "item_id": "", "key": key,
        "role": "", "parent_task_id": "", "reason": "",
        "detail_path": "", "existing": False,
    }
    conductor = _conductor_for(store)
    if conductor is None:
        out.update(state="pending", reason="这一趟没有已装配的主控 ⇒ 板项开不了"
                                            "（不是「已经送到」）")
        return out
    from . import conductor as _CND

    parent_id, parent_role = _CND.current_parent()
    if not str(parent_id or ""):
        out.update(state="undelivered",
                   reason="这一趟调用不在任何召唤里（`current_parent` 是空）⇒ "
                          "读不到被审者；不拿「谁醒着」当收件人")
        return out
    role = str(parent_role or role_hint or "")
    out.update(role=role, parent_task_id=str(parent_id))
    try:
        board = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001 —— 读不成就不去重（宁多一条，不静默丢）
        board = []
    have = next((r for r in board if str(r.get("input_key") or "") == key), None)
    if have is not None:
        out.update(checked=True, state="dispatched", existing=True,
                   item_id=str(have.get("task_id") or ""),
                   reason=f"这一条已经在板上（{have.get('task_id') or '没读到编号'}）⇒ 不重开")
        return out
    try:
        item_id = conductor.open_item(
            kind="notice", role=role or "F", expects="", action="notice",
            summary=summary, called_by=actor, parent_task_id=str(parent_id),
            depth=max(1, int(depth or 1)), input_key=key)
        got, problem = conductor.set_item_detail(item_id, detail)
    except Exception as exc:  # noqa: BLE001 —— 投递失败是框架失败，不许带走判定
        out.update(state="error",
                   reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        return out
    out.update(checked=bool(got), state=("dispatched" if got else "pending"),
               item_id=str(item_id), detail_path=str(detail or ""),
               reason=(str(problem) if problem else
                       f"已投给 {parent_id} 的板项 {item_id}"))
    return out


def deliver_review(store: Any, *, root: str | Path, review: Mapping[str, Any],
                   statement_id: str = "", actor: str = "agent-V",
                   depth: int = 1) -> dict[str, Any]:
    """把一份 V 稿作为 notice 交给被审者（不要求 ack）。"""
    got = dict(review or {})
    review_id = str(got.get("review_id") or "")
    if not review_id:
        return {"checked": False, "state": "not_written", "item_id": "", "key": "",
                "role": "", "parent_task_id": "", "reason": "没有 V 稿编号 ⇒ 不投",
                "detail_path": "", "existing": False}
    rel = str(got.get("rel") or got.get("path") or "")
    detail = (
        f"V 的审阅报告：`{rel}`\n"
        f"- 被审稿：`{got.get('entry', {}).get('manuscript') or ''}`\n"
        f"- 结论：有毛病（V 的秘书语义判定：fault）\n"
        f"- 台账锚点：`{got.get('entry', {}).get('ledger') or ''}"
        f"#{got.get('entry', {}).get('verification_id') or ''}`\n"
        "V 的原文不转达；这份报告就是给你的审阅意见。改完把同一份稿重新送 V。\n"
    )
    return _deliver(store, root, key=f"{REVIEW_PREFIX}{review_id}",
                    summary=f"V 的审阅报告（有毛病）：{review_id}",
                    detail=detail, role_hint="", actor=actor, depth=depth)


def deliver_signed(store: Any, *, root: str | Path, manuscript: str,
                   proof_sha256: str, sign_rel: str, ledger: str,
                   verification_id: str, streak: int, need: int,
                   by: str = "", review_call: str = "",
                   actor: str = "agent-V", depth: int = 1) -> dict[str, Any]:
    """把签好的稿作为 notice 交给送审者（不要求 ack）。"""
    key = f"{SIGNED_PREFIX}{review_call or str(proof_sha256)[:16] or 'unknown'}"
    detail = (
        f"V 已经把签签进稿里：`{manuscript}`\n"
        f"- 正文 sha256：`{proof_sha256}`\n"
        f"- 签文件：`{sign_rel or '（没读到）'}`\n"
        f"- 连续 clean：{int(streak)}/{int(need)}\n"
        f"- 落签者：{by or '（没读到）'}\n"
        f"- 台账：`{ledger}#{verification_id}`\n"
        "这一份稿已经签好，可以直接交给 B 收录（按正文 sha 认领）。\n"
    )
    return _deliver(store, root, key=key, summary="V 签好的稿",
                    detail=detail, role_hint="", actor=actor, depth=depth)
