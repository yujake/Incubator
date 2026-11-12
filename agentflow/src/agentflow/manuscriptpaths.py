# -*- coding: utf-8 -*-
"""多证明的路径号（B 收录时分配）。

一条命题已有 N 条路径 ⇒ 新正文排第 N+1；同一份稿（同正文 sha / 同路径）重复
收录 ⇒ 沿用原号。依赖行与 `verifications` 行都用这个号。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .manuscriptproducers import _manuscript_id_of


# --------------------------------------------------------------------- 路径号（多证明）
def path_reading(store: Any, root: Any, *, statement_id: str) -> dict[str, Any]:
    """一条命题现在有几条「证明路径」、每条是哪份稿（稿号 + 正文 sha）。

    两条来源 join：
    - `dependencies` 行的 `path_group`（B 收录时写的那个号；老盘只有 1）；
    - `verifications` 行的 `path_group`（V 落行时可能还没有，B 收录后由
      :func:`stamp_verification_path_group` 补齐；老行没有这一格 ⇒ 只按 sha 读，
      不硬填一个号）。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {"checked": False, "statement_id": sid, "paths": [],
                           "count": 0, "why": ""}
    if not sid:
        out["why"] = "没有命题号 ⇒ 路径数判不了"
        return out
    by_group: dict[int, dict[str, Any]] = {}
    problems: list[str] = []
    try:
        deps = [dict(r) for r in store.rows("dependencies")] if store is not None else []
    except Exception as exc:  # noqa: BLE001
        return {"checked": False, "statement_id": sid, "paths": [], "count": 0,
                "why": f"`dependencies` 读不出来（{type(exc).__name__}: {exc}）"}
    for row in deps:
        used = str(row.get("used_by") or "")
        if used.split("#", 1)[0] != f"stmt:{sid}":
            continue
        try:
            group = int(row.get("path_group") or 1)
        except (TypeError, ValueError):
            group = 1
        one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                          "body_sha": "", "manuscript": "",
                                          "sources": []})
        one["sources"].append(str(row.get("source_stmt_id")
                                  or row.get("source_lit_id")
                                  or row.get("source_experiment_id")
                                  or row.get("label") or ""))
    try:
        from . import verifications as _VR

        rows, _vbad = _VR.list_verifications(root, statement_id=sid, limit=None)
        if _vbad:
            problems.extend(f"verifications: {x}" for x in _vbad)
    except Exception as exc:  # noqa: BLE001
        rows = []
        problems.append(f"`verifications` 读不出来（{type(exc).__name__}: {exc}）")
    for row in rows or ():
        doc = dict(row or {})
        sha = str(doc.get("proof_sha256") or "").strip().lower()
        rel = str(doc.get("manuscript") or doc.get("object_path") or "").strip()
        raw_group = doc.get("path_group")
        group: int | None
        try:
            group = int(raw_group) if raw_group not in (None, "") else None
        except (TypeError, ValueError):
            group = None
        if group is None:
            # 老行没有这一格：只按 sha 记一条读数，不替它编组号。
            if not sha and not rel:
                continue
            group = 0
        one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                          "body_sha": "", "manuscript": "",
                                          "sources": []})
        if not one["body_sha"]:
            one["body_sha"] = sha
        if not one["manuscript"] and rel:
            one["manuscript"] = rel
            one["manuscript_id"] = _manuscript_id_of(rel)
        if not one["manuscript_id"] and rel:
            one["manuscript_id"] = _manuscript_id_of(rel)
    paths = [by_group[g] for g in sorted(by_group) if int(g) >= 1]
    out.update(checked=True, paths=paths, count=len(paths),
               why=(f"`stmt:{sid}` 有 {len(paths)} 条路径"
                    + (f"；{len(problems)} 条读数问题" if problems else "")))
    if problems:
        out["problems"] = problems
    return out


def assign_path_group(*, store: Any, root: Any, statement_id: str,
                      manuscript: str, body_sha: str = "") -> dict[str, Any]:
    """B 收录时给这一份证明分配「第几条路径」。

    规则：这条命题已经有 N 条路径 ⇒ 新正文排第 N+1 条；同一份稿（同正文 sha / 同
    路径）重复收录 ⇒ 沿用原来的号，不新增路径。老盘没有 `path_group` 的行不猜号
    （只贡献它有的组号；一条都没有 ⇒ 第 1 条）。
    """
    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    sha = str(body_sha or "").strip().lower()
    got = path_reading(store, root, statement_id=sid)
    out: dict[str, Any] = {"checked": bool(got.get("checked")), "path_group": 1,
                           "existing": False, "count": int(got.get("count") or 0),
                           "statement_id": sid, "manuscript": rel, "body_sha": sha,
                           "paths": list(got.get("paths") or []), "why": "",
                           "problems": list(got.get("problems") or [])}
    if not sid:
        out.update(checked=False, why="没有命题号 ⇒ 路径号分不了（不是「第 1 条」）")
        return out
    if not got.get("checked"):
        out.update(checked=False, why=f"路径数没读成：{got.get('why') or '未知原因'}")
        return out
    for one in got.get("paths") or []:
        same_sha = sha and str(one.get("body_sha") or "").lower() == sha
        same_path = rel and str(one.get("manuscript") or "") == rel
        if same_sha or same_path:
            if int(one.get("path_group") or 0) >= 1:
                out.update(path_group=int(one["path_group"]), existing=True,
                           why=(f"这一份正文（sha {sha[:12]}…）已经是第 "
                                f"{one['path_group']} 条路径 ⇒ 沿用，不新增"))
                return out
    groups = [int(p.get("path_group") or 0) for p in (got.get("paths") or [])]
    group = max([g for g in groups if g >= 1] or [0]) + 1
    out.update(path_group=group, existing=False,
               why=(f"这条命题已有 {out['count']} 条路径 ⇒ 新收的这一份排第 {group} 条"))
    return out


def stamp_verification_path_group(*, root: Any, statement_id: str, body_sha: str,
                                  manuscript: str, path_group: int) -> dict[str, Any]:
    """把 B 分配的路径号回写到覆盖同一份正文的 `verifications` 行（老行补格）。

    为什么必须回写：V 落行时 B 还没收录（路径号还没分配），而同一份证明的依赖行与
    verification 行必须用同一个号。写法是"只读-判-重写"：已有同一个号 ⇒ 一个字节不动；
    已有别的号 ⇒ 不覆盖、如实报（`bound_elsewhere`）；其余行逐字节原样。
    """
    sid = str(statement_id or "").strip()
    sha = str(body_sha or "").strip().lower()
    rel = str(manuscript or "").strip().replace("\\", "/")
    group = int(path_group or 0)
    out: dict[str, Any] = {"checked": False, "stamped": 0, "files": [],
                           "problems": [], "why": ""}
    if not sid:
        out["why"] = "没有命题号 ⇒ 路径号回写不了（不是「已经写过」）"
        return out
    if group < 1:
        out["why"] = f"路径号必须是正整数（收到 {path_group!r}）"
        return out
    try:
        from . import verifications as _VR

        files = [_VR.verification_ledger_path(root, sid)]
        pending = _VR.pending_dir(root)
        if pending.is_dir():
            files.extend(sorted(pending.glob("*.jsonl")))
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"verifications 目录读不出来（{type(exc).__name__}: {exc}）"
        return out
    bad_any = False
    for path in files:
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            out["problems"].append(f"{path.name} 读不出来（{type(exc).__name__}: {exc}）")
            continue
        import json

        lines = raw.splitlines(keepends=True)
        changed = 0
        bad = False
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            row_sid = str(row.get("stmt_id") or row.get("statement_id") or "")
            row_sha = str(row.get("proof_sha256") or "").strip().lower()
            row_rel = str(row.get("manuscript") or row.get("object_path") or "").strip()
            if not ((sha and row_sha == sha) or (rel and row_rel == rel)):
                continue
            if row_sid and row_sid != sid:
                out["problems"].append(
                    f"{path.name} 有一行属于 stmt:{row_sid}（不是 stmt:{sid}）⇒ 不回写")
                bad = True
                continue
            if not row_sid and path.name != f"{sid}.jsonl":
                # 未认领的 pending 行不替它绑号（认领是 `vsigns.claim_pending` 的事）。
                continue
            current = row.get("path_group")
            try:
                current_no = int(current) if current not in (None, "") else 0
            except (TypeError, ValueError):
                current_no = 0
            if current_no == group:
                continue
            if current_no >= 1:
                out["problems"].append(
                    f"{path.name} 的 {row.get('verification_id') or '一行'} 已有路径号 "
                    f"{current_no}（不是 {group}）⇒ 不覆盖")
                bad = True
                continue
            row["path_group"] = group
            lines[i] = json.dumps(row, ensure_ascii=False, default=str) + (
                "\n" if line.endswith("\n") else "")
            changed += 1
        if changed and not bad:
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.write_text("".join(lines), encoding="utf-8")
                tmp.replace(path)
            except OSError as exc:
                out["problems"].append(f"{path.name} 写不进去（{type(exc).__name__}: {exc}）")
                try:
                    tmp.unlink()
                except OSError:  # noqa: R001 —— 临时文件删不掉不改变"这笔没写成"的结论
                    pass
                continue
            out["stamped"] += changed
            out["files"].append(str(path))
        bad_any = bad_any or bad
    out["checked"] = not bad_any
    out["why"] = (f"回写了 {out['stamped']} 条 verification 行（路径号 {group}）"
                  if not bad_any else "有行已有别的路径号 / 属于别的命题 ⇒ 没有覆盖")
    return out



