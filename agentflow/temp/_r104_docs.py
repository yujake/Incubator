#!/usr/bin/env python
"""把 `docs/ROLE-SPECS.md` / `ROLE-SPECS-DRAFT-V.md` 里"4 位编号"的**活口径**改成六位。

只改"活口径"（现在是什么样）：历史提案档（`PROPOSALS.md`）逐字不动 —— 那是历史记录，
改它等于伪造历史。改法与理由写进提交信息。
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(r"D:\Incubator\agentflow\docs")

EDITS: list[tuple[str, str, str]] = [
    ("ROLE-SPECS.md",
     "| `id_gap` | warning | 4 位 ID 出现空洞 | 全体 |",
     "| `id_gap` | warning | 编号出现空洞（六位；旧四位数据按数值判） | 全体 |"),
    ("ROLE-SPECS.md",
     "| `counter_behind` / `counter_overflow` | error | counters 落后（会撞号）/ 超出 4 位空间 | 全体 |",
     "| `counter_behind` / `counter_overflow` | error | counters 落后（会撞号）/ 超出编号空间上限（六位 = 999999） | 全体 |"),
    ("ROLE-SPECS.md",
     "| `for_question_id` | 4 位代号 | 必须存在（`verify.dangling_question_ref`，error） |",
     "| `for_question_id` | 编号（六位，旧四位仍可读） | 必须存在（`verify.dangling_question_ref`，error） |"),
    ("ROLE-SPECS.md",
     "| 命题号 | 必须 **4 位十进制** |",
     "| 命题号 | 必须 **六位十进制**（旧数据里的四位仍可读） |"),
    ("ROLE-SPECS.md",
     "| 命题号不是 4 位十进制 |",
     "| 命题号不是六位十进制（四位旧号除外） |"),
    ("ROLE-SPECS.md",
     "| **命题号必须 4 位十进制** |",
     "| **命题号必须是六位十进制（旧四位可读）** |"),
    ("ROLE-SPECS.md",
     "[PASS] 命题号必须 4 位",
     "[PASS] 命题号必须是六位十进制（旧四位可读）"),
    ("ROLE-SPECS-DRAFT-V.md",
     "写 `verifications/<4 位命题号>.jsonl`",
     "写 `verifications/<命题号>.jsonl`（六位编号，旧四位仍可读）"),
    ("ROLE-SPECS-DRAFT-V.md",
     "命题号不是 4 位十进制 ⇒ `reason=\"bad_statement_id\"`",
     "命题号不是编号形态（六位，或旧四位）⇒ `reason=\"bad_statement_id\"`"),
    ("ROLE-SPECS-DRAFT-V.md",
     "文件是 `verifications/<4 位命题号>.jsonl`",
     "文件是 `verifications/<命题号>.jsonl`（六位编号）"),
    ("ROLE-SPECS-DRAFT-V.md",
     "- 输入：`statement_id`（4 位）",
     "- 输入：`statement_id`（六位编号，旧四位仍可读）"),
]


def main() -> int:
    misses: list[str] = []
    for name, old, new in EDITS:
        p = ROOT / name
        text = p.read_text(encoding="utf-8")
        if old not in text:
            misses.append(f"{name}: 找不到 {old[:50]!r}")
            continue
        p.write_text(text.replace(old, new), encoding="utf-8", newline="")
        print(f"[ok] {name}: {old[:40]}…")
    for m in misses:
        print("[miss]", m)
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
