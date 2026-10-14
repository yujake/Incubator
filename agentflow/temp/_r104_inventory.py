#!/usr/bin/env python
"""六位编号（②）的施工清单：`04d` / 4 位 ID 字面量按文件点数（src / tests / docs 分开）。"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
PAT = re.compile(r":04d|zfill\(4\)|\\\\d\{4\}|\b[0-9]{4}\b|4 位|四位")


def scan(rel: str, suffix: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for p in sorted((ROOT / rel).rglob(f"*{suffix}")):
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = PAT.findall(text)
        if hits:
            # `04d` 这类"生成点"与裸 4 位数字要分开看
            gens = len(re.findall(r":04d|zfill\(4\)", text))
            out.append((str(p.relative_to(ROOT)), len(hits), gens))
    return out


for rel, suffix in (("src/agentflow", ".py"), ("tests", ".py"), ("docs", ".md")):
    rows = scan(rel, suffix)
    total = sum(r[1] for r in rows)
    print(f"== {rel}: {len(rows)} 个文件、{total} 处（其中取号点 {sum(r[2] for r in rows)}）")
    for name, n, gens in sorted(rows, key=lambda r: -r[1])[:14]:
        print(f"   {n:4d} 处（取号点 {gens}）  {name}")
