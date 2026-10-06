"""只读：报告是否引用了真实存在的行号/符号（抽样核对）。"""
from __future__ import annotations

import pathlib
import re
import sys

REPORT = pathlib.Path(r"D:\Incubator\draft\41-调查报告-C-数据与证据链.md")
SRC = pathlib.Path(r"D:\Incubator\agentflow\src\agentflow")
text = REPORT.read_text(encoding="utf-8")

# 抽取 `file.py:NNN` 形式（同一行里可能多次出现，且 `:NNN` 可能省略文件名沿用上一个）
pairs = re.findall(r"`([a-z_]+\.py):(\d+)", text)
bad = []
for name, lineno in pairs:
    p = SRC / name
    if not p.exists():
        bad.append((name, lineno, "file-missing"))
        continue
    body = p.read_text(encoding="utf-8").splitlines()
    n = int(lineno)
    if n < 1 or n > len(body):
        bad.append((name, lineno, f"out-of-range(len={len(body)})"))

print(f"带文件名的行号引用：{len(pairs)} 处；越界/文件缺失：{len(bad)}")
for b in bad:
    print("   ", b)
