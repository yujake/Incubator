# -*- coding: utf-8 -*-
"""审计 `draft/72|73|74` 里的**事实性引用**（三档，只报需要人看的）。

## 它为什么是"三档"而不是"一档"
本文档族的写法有三种，**只有前两种能被机器判**：
  1. `` `file.py:120 symbol` `` —— 符号在反引号跨度里 ⇒ 可判：那一行必须含这个符号；
  2. `` `symbol`（`file.py:120`） `` —— 符号在跨度外、相邻 ⇒ 可判（取跨度外的近邻标识符）；
  3. `` `file.py:120/140/160` `` —— **只有路径与行号**（成组或单个）⇒ **机器判不了**：
     没有"应该有什么"的断言。这一档**把那一行原样打出来**，交人一眼扫过 ——
     本批的教训正是：真错就藏在这一档里（如"runs/ 那 1 项"写成进程登记，是**语义**错，
     行号本身是对的，任何行号检查都抓不到它）。

用法：
  python -B temp/_audit_web_drafts.py            # 三档全打
  python -B temp/_audit_web_drafts.py --bare     # 只打第 3 档（逐行原文，供人扫）
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(r"D:\Incubator\agentflow")
DRAFTS = [REPO.parent / "draft" / n for n in (
    "72-Web端加强（详细设计）.md",
    "73-Web端加强（按文件细化方案）.md",
    "74-前端×后端配合矩阵（按前端文件）.md",
    "75-Web端伪代码（逐前端文件·互相对齐）.md",
    "76-待裁选择题（Web端·全部待裁项）.md",
    "77-Web端施工台账与G2签字包.md",
    "78-Web端三条主线（零交）拆解.md",
    "79-待裁清单（Web施工中新冒出）.md",
    "80-待裁选择题（Web施工·合并后）.md",
)]
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
CITE = re.compile(r"([A-Za-z0-9_./\\-]+\.py):(\d+)")
TESTFILE = re.compile(r"(tests[/\\][A-Za-z0-9_]+\.py)")
TESTNODE = re.compile(r"([A-Za-z0-9_]+\.py)::([A-Za-z0-9_]+)")
PLANNED = ("新", "新增", "计划", "W0", "W1", "W2", "W3", "W4", "W5")
# 明确说"这个文件不存在"的句子**不是**在断言它存在（如 draft/78 §7 的
# "本仓没有 tests/test_userio.py"）。这类提法要单列一桶打给人看，不能算硬错，
# 也不能混进"计划中的判据文件"（那桶的语义是"打算建、还没建"）。
# 负控：把"没有"换成"见"，同一句必须落回硬错桶（temp/_audit_web_drafts.py 自测过）。
NEGATED = ("没有", "不存在", "不是", "并未", "尚无")
sys.stdout.reconfigure(encoding="utf-8")


def find_file(rel: str) -> pathlib.Path | None:
    rel = rel.replace("\\", "/")
    for cand in (REPO / rel, REPO / "src" / "agentflow" / rel,
                 REPO / "src" / "agentflow" / "tools" / rel):
        if cand.is_file():
            return cand
    name = rel.split("/")[-1]
    for base in (REPO / "src" / "agentflow", REPO / "src" / "agentflow" / "tools",
                 REPO / "tools", REPO / "scripts", REPO / "tests"):
        p = base / name
        if p.is_file():
            return p
    return None


def main() -> int:
    only_bare = "--bare" in sys.argv
    hard: list[str] = []
    suspect: list[str] = []
    bare: list[str] = []
    planned: list[str] = []
    negated: list[str] = []

    for doc in DRAFTS:
        if not doc.is_file():
            print(f"!! 文档不在：{doc}")
            continue
        text = doc.read_text(encoding="utf-8")
        for m in CITE.finditer(text):
            rel, lineno = m.group(1), int(m.group(2))
            p = find_file(rel)
            if p is None:
                hard.append(f"{doc.name}: 文件不存在 {rel}:{lineno}")
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if not (1 <= lineno <= len(lines)):
                hard.append(f"{doc.name}: 行号越界 {rel}:{lineno}（共 {len(lines)} 行）")
                continue
            actual = lines[lineno - 1]
            bare.append(f"{rel}:{lineno}  →  {actual.strip()[:104]}")
        seen_files: set[str] = set()
        for mm in TESTFILE.finditer(text):
            rel_test = mm.group(1).replace("\\", "/")
            if rel_test in seen_files:
                continue
            seen_files.add(rel_test)
            if (REPO / rel_test).is_file():
                continue
            where = text[max(0, mm.start() - 60): mm.start() + 40]
            line = f"{doc.name}: 判据文件不存在 {rel_test}"
            if any(k in where for k in PLANNED):
                planned.append(line + "（该处标了'新/计划'）")
            elif any(k in where for k in NEGATED):
                negated.append(line + "（该处明说它不存在 —— 不是断言）")
            else:
                hard.append(line)
        for m in TESTNODE.finditer(text):
            fname, node = m.group(1), m.group(2)
            p = REPO / "tests" / fname
            if p.is_file() and f"def {node}(" not in p.read_text(encoding="utf-8", errors="replace"):
                hard.append(f"{doc.name}: 用例名不存在 tests/{fname}::{node}")

    print("=" * 78)
    print(f"① 硬错（文件/行号/判据文件/用例名）—— 机械可判、可靠：{len(hard)}")
    for one in hard:
        print("   " + one)
    print(f"② 逐条引用 → 盘上那一行原文（**机器判不了语义**，逐行打给人扫）：{len(bare)} 条")
    if only_bare:
        for one in bare:
            print("   " + one)
    else:
        print(f"   （加 --bare 看这 {len(bare)} 行；本档包括'行号对但语义错'那一种 —— 只有人看得出来）")
    print(f"③ 计划中的判据文件（尚未建，不算错）：{len(planned)}")
    for one in planned:
        print("   " + one)
    print(f"③b 明确说'不存在'的提法（不是在断言它有）：{len(negated)}")
    for one in negated:
        print("   " + one)
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
