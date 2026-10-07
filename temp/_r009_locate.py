"""把 R009 报出来的每一处（注释/文档串里的成对 `**`）逐行打印出来，供人工逐条消掉。

为什么不用内联 python：PowerShell 会把反引号/反斜杠/引号吃掉（我这轮栽过三次）。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(r"D:\Incubator\agentflow")
PAIR = re.compile(r"\*\*[^*\n]+\*\*")
#: 本轮新写的文件（R009 报的就是这几个；`lint --json` 这个仓不支持，所以自己扫）
TARGETS = [
    "src/agentflow/webui/server.py",
    "src/agentflow/webui/routes.py",
    "src/agentflow/webui/readers.py",
    "src/agentflow/webui/sse.py",
    "src/agentflow/webui/writes.py",
    "src/agentflow/web/emit_types.py",
    "src/agentflow/web/emit_theme.py",
    "tests/test_webui.py",
    "tests/test_webui_contracts.py",
    "tests/test_webui_static.py",
]


def main() -> int:
    total = 0
    for rel in TARGETS:
        path = REPO / rel
        if not path.is_file():
            print(f"  ?? {rel} 不在盘上")
            continue
        hits = [(n, line.rstrip()) for n, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1) if PAIR.search(line)]
        if not hits:
            continue
        total += sum(len(PAIR.findall(line)) for _n, line in hits)
        print(f"\n== {rel}（{len(hits)} 行）")
        for n, line in hits:
            print(f"  {n}: {line.strip()[:150]}")
            print(f"      -> {PAIR.findall(line)}")
    print(f"\n合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
