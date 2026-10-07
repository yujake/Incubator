# -*- coding: utf-8 -*-
"""审计 `draft/72|73|74` 里的**事实性引用**（只报对不上的，不打印通过项）。

三类检查：
  ① `路径.py:行号` —— 行号存在吗？那一行的内容与引用处的上下文有共同标识符吗？
  ② `tests/x.py` / `x.py::ye_shi` —— 判据文件与用例名真的在盘上吗？
  ③ 可复算的事实声明（手工登记几条：六件产物样本、verifications 目录、受理标记计数）——
     重新算一遍，把读数打出来（不评判，交给人看）。
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
)]
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
CITE = re.compile(r"`?([A-Za-z0-9_./\\-]+\.py):(\d+)")
TESTFILE = re.compile(r"(tests[/\\][A-Za-z0-9_]+\.py)")
TESTNODE = re.compile(r"([A-Za-z0-9_]+\.py)::([A-Za-z0-9_]+)")
sys.stdout.reconfigure(encoding="utf-8")


def find_file(rel: str) -> pathlib.Path | None:
    rel = rel.replace("\\", "/")
    for cand in (REPO / rel, REPO / "src" / "agentflow" / rel,
                 REPO / "src" / "agentflow" / "tools" / rel, REPO / rel.split("/")[-1]):
        if cand.is_file():
            return cand
    # 只给裸文件名的：在 src/agentflow 与 tools 下按名找
    name = rel.split("/")[-1]
    for base in (REPO / "src" / "agentflow", REPO / "src" / "agentflow" / "tools",
                 REPO / "tools", REPO / "scripts", REPO / "tests"):
        p = base / name
        if p.is_file():
            return p
    return None


def main() -> int:
    bad = 0
    for doc in DRAFTS:
        if not doc.is_file():
            print(f"!! 文档不在：{doc}")
            continue
        text = doc.read_text(encoding="utf-8")
        print("=" * 78)
        print(f"# {doc.name}")
        # ① 行号引用
        for m in CITE.finditer(text):
            rel, lineno = m.group(1), int(m.group(2))
            p = find_file(rel)
            if p is None:
                print(f"  [文件不存在] {rel}:{lineno}")
                bad += 1
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if lineno < 1 or lineno > len(lines):
                print(f"  [行号越界] {rel}:{lineno}（该文件共 {len(lines)} 行）")
                bad += 1
                continue
            actual = lines[lineno - 1]
            ctx = text[max(0, m.start() - 90): m.end() + 60]
            ctx_ids = {t for t in IDENT.findall(ctx)}
            if not (ctx_ids & set(IDENT.findall(actual))):
                print(f"  [行内容对不上] {rel}:{lineno}")
                print(f"      引用处上下文：…{ctx.strip()[:120]}…")
                print(f"      盘上那一行  ：{actual.strip()[:120]}")
                bad += 1
        # ② 判据文件与用例名
        for m in sorted({x.group(1).replace('\\', '/') for x in TESTFILE.finditer(text)}):
            p = REPO / m
            if not p.is_file():
                print(f"  [判据文件不存在] {m}")
                bad += 1
        for m in TESTNODE.finditer(text):
            fname, node = m.group(1), m.group(2)
            p = REPO / "tests" / fname
            if not p.is_file():
                continue  # 文件那条已经报过
            body = p.read_text(encoding="utf-8", errors="replace")
            if f"def {node}(" not in body:
                print(f"  [用例名不存在] tests/{fname}::{node}")
                bad += 1
    print("=" * 78)
    print(f"不一致条目：{bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
