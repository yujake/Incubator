"""把 6 个文件里 R009 点名的成对 `**` 去掉（只去成对的那一种，`**kwargs` 不受影响）。

为什么写成脚本：21 处手工改容易漏；而且 R009 是这个项目里我反复踩的规则（已第 5 次），
留一个可重算的小工具比"这次小心一点"可靠。跑完会打印每一行的改前/改后。
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(r"D:\Incubator\agentflow")
PAIR = re.compile(r"\*\*([^*\n]+?)\*\*")
TARGETS = [
    "src/agentflow/webui/server.py",
    "src/agentflow/webui/routes.py",
    "src/agentflow/webui/readers.py",
    "src/agentflow/webui/sse.py",
    "tests/test_webui_contracts.py",
    "tests/test_webui_static.py",
    "tests/test_r5_orchestration_cost.py",
]


def main() -> int:
    total = 0
    for rel in TARGETS:
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if not PAIR.search(line):
                continue
            new = PAIR.sub(lambda m: m.group(1), line)
            if new == line:
                continue
            print(f"{rel}:{i + 1}")
            print(f"  - {line.rstrip()}")
            print(f"  + {new.rstrip()}")
            lines[i] = new
            changed = True
            total += len(PAIR.findall(line))
        if changed:
            path.write_text("".join(lines), encoding="utf-8", newline="")
    print(f"\n共去掉 {total} 处成对标记")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
