# -*- coding: utf-8 -*-
"""`agentflow sign-audit`：D268 批 1 的只读读数口（零模型、零写盘）。

它回答一个问题：按"必须可复算"的新口径，每个工区里的签到底有几份是真的。

七张表（对应设计 §5.3 的五张表 + 本批要求的 `borrowed` 与"不可复算签文件"清单）：

1. `signed`：凭据在、且复算通过（签文件里的 `passes` 能在台账上逐条点出 `need` 行）。
2. `unissued`：够票（`votes >= need`）却没有签文件 —— 事故档，今天是按 `signed` 读的。
3. `unbacked`：签文件在、复算不上（自指签 / 锚点那几行没有秘书轴 / passes 不齐 …）。
4. `borrowed`：凭据能复算，但它是别条命题（或别的证明号）的签。
5. `view_conflict`：手稿块自称 `n/n` 而凭据不在 / 复算不上 / 与现行正文不是一版。
6. `legacy_clean_only`：有 clean 行（1..need-1 票）、没有凭据 —— 严格化后从"当签读"
   翻成"欠签"的那批。
7. `unverifiable_sign_files`：不可复算的签文件逐条（工区 / 文件 sha / 理由码 /
   那格台账）—— 只列，不写盘、不补签、不标记（业主 2026-11-09 裁定 ⑦）。

读什么：`<root>/data/statements.json`、`verifications/**/*.jsonl`、`out/vsigns/*.json`、
`reports|notes|out` 下的 `*proof*.md`。写什么：一个字节都不写（不建目录、不加锁、
不写报告、不碰台账、不碰签文件）。

退出码：`0` 查过了（含"0 签"）/ `2` 没查成（根不在盘上 / 一条台账都读不出来）。
`2` 不是"没有问题"：它是"这一格没查成"，与 `0` 必须分开（三态纪律）。

跑法：

    python scripts/sign_audit.py --root projects/paper-rewrite-98b
    python scripts/sign_audit.py --root .                 # 扫 <root>/projects/* 或 <root>/agentflow/projects/*
    python scripts/sign_audit.py --root projects/paper-rewrite-84 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import vsigns as VS  # noqa: E402

EXIT_OK = 0
EXIT_UNKNOWN = 2


def _workspaces(root: Path) -> list[Path]:
    """`--root` 指一个工区 / 一个 projects 目录 / 仓库根 ⇒ 工区列表（只读）。

    一个空的工作区（`data/statements.json` 是空表）与"这是仓库根"长得一样：
    `agentflow/` 自己就有一套空表。所以：
    ① 根自己就是一个有命题的工区 ⇒ 只看它；
    ② 否则先看 `agentflow/projects/`、再看 `projects/`（本仓的数据面在
       `agentflow/projects/`；`D:\Incubator\projects\` 是另一套历史目录）；
    ③ 都没有时才把根下「有命题」的子目录当工区（空表子目录不算 ——
       否则 `--root .` 会把 `agentflow/` 那套空表当成一个工区）。
    """
    if (root / "data" / "statements.json").is_file():
        if _statements(root):
            return [root]
        for base in (root / "agentflow" / "projects", root / "projects"):
            if base.is_dir():
                found = sorted(p for p in base.iterdir()
                               if (p / "data" / "statements.json").is_file())
                if found:
                    return found
        return [root]
    for base in (root / "agentflow" / "projects", root / "projects"):
        if not base.is_dir():
            continue
        found = sorted(p for p in base.iterdir()
                       if (p / "data" / "statements.json").is_file())
        if found:
            return found
    if root.is_dir():
        found = sorted(p for p in root.iterdir()
                       if (p / "data" / "statements.json").is_file() and _statements(p))
        if found:
            return found
    return []


def _statements(ws: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads((ws / "data" / "statements.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [dict(r) for r in (doc.get("rows") or []) if isinstance(r, Mapping)]


def _ledger_rows(ws: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读这个工区全部台账行（`verifications/*.jsonl` + `pending/*`），只读。"""
    from agentflow import jsonlfile as JF

    out: list[dict[str, Any]] = []
    problems: list[str] = []
    base = ws / "verifications"
    if not base.is_dir():
        return out, problems
    files = sorted(base.glob("*.jsonl")) + sorted((base / "pending").glob("*.jsonl"))
    for path in files:
        rows, bad, state = JF.read_jsonl_state(path)
        if state == "unreadable" or bad:
            problems.append(f"{path.relative_to(ws)}: {bad[:2] or state}")
            continue
        out.extend(dict(r) for r in rows if isinstance(r, Mapping))
    return out, problems


def _manuscript_for(ws: Path, sid: str, no: int,
                    rows: Sequence[Mapping[str, Any]]) -> str:
    """这一份证明的正文载体（只读；次序：台账点名的稿 > 内容 sha 对得上的稿 > 同名稿）。

    98b 的 000000 是 `reports/b-proof-000000.md`（不是 `f-proof-*`）⇒ 只按
    `depsection.manuscript_relpaths` 那一条扫不到，必须先用台账行的 `manuscript`。
    """
    mine = [r for r in rows if int(r.get("proof_no") or 1) == int(no)]
    named = ""
    if mine:
        named = str(mine[-1].get("manuscript") or "").strip().replace("\\", "/")
    if named and (ws / named).is_file():
        return named
    known = {str(r.get("proof_sha256") or "") for r in mine}
    cands: list[str] = []
    if sid and all(ch.isalnum() or ch in "_-" for ch in sid):
        for pattern in (f"reports/*proof*{sid}*.md", f"notes/*proof*{sid}*.md",
                        f"out/*proof*{sid}*.md"):
            cands.extend(str(p.relative_to(ws)).replace("\\", "/")
                         for p in sorted(ws.glob(pattern)))
    cands = list(dict.fromkeys(cands))
    for rel in cands:
        try:
            text = (ws / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        body = VS.manuscript_proof_body(text) if "## 证明" in text else text
        if VS._sign_sha(body) in known:
            return rel
    for rel in cands:
        name = Path(rel).name
        if name.endswith(f"-p{no}.md") or f"proof-{sid}.md" in name:
            return rel
    return cands[0] if cands else ""


def _block_files(ws: Path) -> Iterable[Path]:
    for sub in ("reports", "notes", "out"):
        base = ws / sub
        if base.is_dir():
            for path in sorted(base.rglob("*proof*.md")):
                if path.is_file():
                    yield path


def _audit_workspace(ws: Path) -> dict[str, Any]:
    """一个工区的七张表（纯读）。"""
    out: dict[str, Any] = {
        "workspace": ws.name, "root": str(ws), "checked": True,
        "statements": 0, "rows": 0, "problems": [], "readings": [],
        "signed": [], "unissued": [], "unbacked": [], "borrowed": [],
        "view_conflict": [], "legacy_clean_only": [],
        "unverifiable_sign_files": [],
    }
    stmts = _statements(ws)
    rows, problems = _ledger_rows(ws)
    out["statements"] = len(stmts)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        out["checked"] = False
    by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        no = int(row.get("proof_no") or 1)
        by_key.setdefault((sid, no), []).append(row)
    keys = set(by_key)
    for row in stmts:
        sid = str(row.get("stmt_id") or "")
        no = int(row.get("proof_no") or 1)
        if sid:
            keys.add((sid, no))
    readings: dict[tuple[str, int], dict[str, Any]] = {}
    out["readings"] = []
    for sid, no in sorted(keys):
        mine = by_key.get((sid, no), [])
        rel = _manuscript_for(ws, sid, no, mine)
        got = VS.sign_reading(ws, statement_id=sid, proof_no=no, manuscript_path=rel)
        readings[(sid, no)] = got
        if not got.get("checked"):
            out["checked"] = False
        state = str(got.get("state") or "")
        base = {
            "workspace": ws.name, "statement_id": sid, "proof_no": no,
            "sha": str(got.get("sha") or ""), "state": state,
            "body_state": str(got.get("body_state") or ""),
            "votes": int(got.get("votes") or 0), "need": int(got.get("need") or 0),
            "votes_source": str(got.get("votes_source") or ""),
            "credential_path": str(got["credential"].get("path") or ""),
            "credential_code": str(got["credential"].get("problem") or ""),
            "manifest": rel, "why": str(got.get("why") or ""),
        }
        out["readings"].append(dict(base))
        if state == "unissued":
            out["unissued"].append(dict(base))
        elif state == "borrowed":
            out["borrowed"].append(dict(base))
        if (not got["credential"].get("found")
                and 0 < int(got.get("votes") or 0) < int(got.get("need") or 0)):
            out["legacy_clean_only"].append(dict(base))
    # ---- 签文件：逐份复算（文件在不算签）
    signs_dir = ws / "out" / "vsigns"
    if signs_dir.is_dir():
        for path in sorted(signs_dir.glob("*.json")):
            if path.name == VS.INDEX_NAME:
                continue
            cred = VS.credential_reading(ws, path.stem)
            if not cred.get("checked"):
                out["checked"] = False
            if not cred.get("found"):
                out["unverifiable_sign_files"].append({
                    "workspace": ws.name, "file_sha": path.stem,
                    "artifact_sha": path.stem, "code": "sign_file_unreadable",
                    "ledger": "", "why": cred.get("why") or ""})
                continue
            if not cred.get("recomputable"):
                entry = {
                    "workspace": ws.name, "file_sha": path.stem,
                    "artifact_sha": str(cred.get("artifact_sha") or path.stem),
                    "code": str(cred.get("problem") or "unbacked"),
                    "ledger": str(cred.get("where") or ""),
                    "statement_id": str((cred.get("sign") or {}).get("statement_id") or ""),
                    "proof_no": (cred.get("sign") or {}).get("proof_no"),
                    "why": str(cred.get("why") or ""),
                }
                out["unbacked"].append(dict(entry))
                out["unverifiable_sign_files"].append(dict(entry))
                continue
            sign = cred.get("sign") or {}
            out["signed"].append({
                "workspace": ws.name,
                "statement_id": str(sign.get("statement_id") or ""),
                "proof_no": sign.get("proof_no"),
                "sha": str(cred.get("artifact_sha") or ""),
                "credential_path": str(cred.get("path") or ""),
                "tier": str(cred.get("tier") or ""),
                "ledger_kind": str(cred.get("ledger_kind") or ""),
                "got": int(cred.get("got") or 0),
                "need": int(cred.get("need") or 0),
            })
    # ---- 手稿块：自称 n/n 而凭据不在 / 复算不上 ⇒ view_conflict（块只是视图）
    seen: set[tuple[str, str]] = set()
    for path in _block_files(ws):
        rel = str(path.relative_to(ws)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        block = VS.manuscript_sign_reading(text, manuscript_path=rel)
        if not block.get("found") or not block.get("signed"):
            continue
        streak = int(block.get("streak") or 0)
        need = int(block.get("need") or 0)
        if need < 1 or streak < need:
            continue
        block_sha = str(block.get("proof_sha256") or "")
        sid = str(block.get("statement_id") or "")
        if not sid.isdigit():
            mid = str(block.get("manuscript_id") or "")
            if not mid.isdigit():
                mid = VS.manuscript_id_of(rel)
            sid = mid if mid.isdigit() else ""
        key = (rel, block_sha)
        if key in seen:
            continue
        seen.add(key)
        # 块自称 3/3 的那一版有没有一份复算通过的凭据？
        # 注意：不能拿"现行正文"的 `sign_reading` 判 —— 块盖的是旧版、而旧版真签过时，
        # 按现行正文读会把它误报成冲突（84 的 f-proof-000000 就是这一档）。
        cred = VS.credential_reading(ws, block_sha) if block_sha else {
            "found": False, "recomputable": False, "problem": "no_block_sha",
            "path": "", "why": "签块没写正文sha"}
        if cred.get("recomputable"):
            continue
        reading = readings.get((sid, 1))
        if reading is None:
            reading = VS.sign_reading(ws, statement_id=sid, proof_no=1,
                                      manuscript_path=rel)
        out["view_conflict"].append({
            "workspace": ws.name, "statement_id": sid, "manifest": rel,
            "block_streak": streak, "block_need": need,
            "block_sha": block_sha, "block_ledger": str(block.get("ledger") or ""),
            "reading_state": str(reading.get("state") or ""),
            "body_sha": str(reading.get("sha") or ""),
            "credential_path": str(cred.get("path") or ""),
            "why": (f"手稿块自称 {streak}/{need}，而这一版（{block_sha[:12]}…）"
                    f"没有一份复算通过的凭据（{cred.get('problem') or '凭据不在'}）⇒ "
                    f"块只是一句话；按现行正文读是 `{reading.get('state') or '?'}`"),
        })
    out["unbacked"].sort(key=lambda one: (one["workspace"], one["file_sha"]))
    out["unverifiable_sign_files"].sort(
        key=lambda one: (one["workspace"], one["file_sha"]))
    return out


def audit(root: str | Path) -> dict[str, Any]:
    """把七张表算成一份可 JSON 化的全库读数（纯读；不写任何工作区）。"""
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "checked": False, "root": str(root_p), "workspaces": [], "readings": [],
        "signed": [], "unissued": [], "unbacked": [], "borrowed": [],
        "view_conflict": [], "legacy_clean_only": [],
        "unverifiable_sign_files": [],
        "summary": {"workspaces": 0, "statements": 0, "rows": 0, "signed": 0,
                    "unissued": 0, "unbacked": 0, "borrowed": 0,
                    "view_conflict": 0, "legacy_clean_only": 0,
                    "unverifiable_sign_files": 0},
        "problems": [], "why": "",
    }
    spaces = _workspaces(root_p)
    if not spaces:
        out["why"] = "根下没有工区（找不到 data/statements.json）⇒ 没查成（不是「0 签」）"
        return out
    for ws in spaces:
        got = _audit_workspace(ws)
        out["workspaces"].append(got["workspace"])
        out["problems"].extend(got["problems"])
        out["readings"].extend(got.get("readings") or [])
        for key in ("signed", "unissued", "unbacked", "borrowed", "view_conflict",
                    "legacy_clean_only", "unverifiable_sign_files"):
            out[key].extend(got[key])
        out["summary"]["statements"] += int(got["statements"])
        out["summary"]["rows"] += int(got["rows"])
    out["checked"] = not out["problems"]
    out["summary"]["workspaces"] = len(out["workspaces"])
    for key in ("signed", "unissued", "unbacked", "borrowed", "view_conflict",
                "legacy_clean_only", "unverifiable_sign_files"):
        out["summary"][key] = len(out[key])
    if out["checked"]:
        out["why"] = (
            f"扫了 {out['summary']['workspaces']} 个工区、{out['summary']['rows']} 行台账："
            f"signed {out['summary']['signed']} · unissued {out['summary']['unissued']} · "
            f"unbacked {out['summary']['unbacked']} · borrowed {out['summary']['borrowed']} · "
            f"view_conflict {out['summary']['view_conflict']} · "
            f"legacy_clean_only {out['summary']['legacy_clean_only']}；"
            "本次没有写任何工作区")
    else:
        out["why"] = (f"扫了 {out['summary']['workspaces']} 个工区，但有 "
                      f"{len(out['problems'])} 本台账读不出来 ⇒ 这一格没查成"
                      "（不是「没有问题」）")
    return out


def _table(lines: list[str], title: str, rows: Sequence[Mapping[str, Any]],
           cols: Sequence[tuple[str, str]]) -> None:
    lines.append(title)
    if not rows:
        lines.append("  （没有）")
        return
    for one in rows:
        cells = []
        for key, fmt in cols:
            value = one.get(key, "")
            if fmt == "sha":
                value = f"{str(value)[:12]}…" if value else "-"
            cells.append(f"{key}={value if value not in (None, '') else '-'}")
        lines.append("  " + "  ".join(cells))
    lines.append("")


def render(reading: Mapping[str, Any]) -> list[str]:
    """七张表的人读渲染（不改变任何判定，只排版）。"""
    lines: list[str] = []
    lines.append(f"sign-audit  root={reading.get('root')}")
    lines.append(f"  {reading.get('why')}")
    if reading.get("problems"):
        lines.append("  ⚠️ 有台账读不出来（这一格没查成，不是「没有问题」）：")
        for problem in reading["problems"][:8]:
            lines.append(f"    - {problem}")
    lines.append("")
    _table(lines, "== 1. signed（凭据复算通过）==", reading.get("signed") or (),
           (("workspace", ""), ("statement_id", ""), ("proof_no", ""),
            ("sha", "sha"), ("tier", ""), ("got", ""), ("need", "")))
    _table(lines, "== 2. unissued（够票没发签）==", reading.get("unissued") or (),
           (("workspace", ""), ("statement_id", ""), ("proof_no", ""),
            ("sha", "sha"), ("votes", ""), ("need", ""), ("votes_source", "")))
    _table(lines, "== 3. unbacked（文件在、复算不上）==", reading.get("unbacked") or (),
           (("workspace", ""), ("file_sha", "sha"), ("code", ""), ("ledger", "")))
    _table(lines, "== 4. borrowed（借光）==", reading.get("borrowed") or (),
           (("workspace", ""), ("statement_id", ""), ("proof_no", ""),
            ("sha", "sha"), ("credential_path", ""), ("why", "")))
    _table(lines, "== 5. view_conflict（块自称 n/n，票不够）==",
           reading.get("view_conflict") or (),
           (("workspace", ""), ("statement_id", ""), ("manifest", ""),
            ("block_streak", ""), ("block_need", ""), ("block_sha", "sha"),
            ("reading_state", "")))
    _table(lines, "== 6. legacy_clean_only（有 clean 行、无凭据）==",
           reading.get("legacy_clean_only") or (),
           (("workspace", ""), ("statement_id", ""), ("proof_no", ""),
            ("sha", "sha"), ("votes", ""), ("need", ""), ("state", "")))
    _table(lines, "== 7. unverifiable_sign_files（不可复算的签文件逐条）==",
           reading.get("unverifiable_sign_files") or (),
           (("workspace", ""), ("file_sha", "sha"), ("code", ""), ("ledger", ""),
            ("why", "")))
    counts = reading.get("summary") or {}
    lines.append("== 计数 ==")
    lines.append("  " + "  ".join(f"{key}={counts.get(key, 0)}" for key in (
        "workspaces", "statements", "rows", "signed", "unissued", "unbacked",
        "borrowed", "view_conflict", "legacy_clean_only",
        "unverifiable_sign_files")))
    lines.append("  （这一条命令只读：不写 out/vsigns/、不写台账、不补签、不标记任何签文件）")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：只读、零写盘；`0` 查过了 / `2` 没查成。"""
    parser = argparse.ArgumentParser(
        prog="agentflow sign-audit",
        description="D268 批 1 的只读读数：signed / unissued / unbacked / borrowed / "
                    "view_conflict / legacy_clean_only + 不可复算签文件清单")
    parser.add_argument("--root", default=".", help="工作区 / projects 目录 / 仓库根（默认当前目录）")
    parser.add_argument("--json", action="store_true", help="打成 JSON（同一份读数）")
    args = parser.parse_args(argv)

    reading = audit(args.root)
    if args.json:
        print(json.dumps(reading, ensure_ascii=False, indent=2))
    else:
        for line in render(reading):
            print(line)
    if not reading.get("checked"):
        print(f"[unknown] 没查成：{reading.get('why')}"
              "（这里的 0 不是「没有」，是「没查成」）", file=sys.stderr)
        return EXIT_UNKNOWN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
