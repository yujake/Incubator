#!/usr/bin/env python
"""逐格走查这一批重冻的三份快照（只报变了的那一格，不打印整篇）。"""
from __future__ import annotations

import json
import subprocess

HEAD = "2371d6f"
REL = ["agentflow/tests/golden/agent_surface_snapshot.json",
       "agentflow/tests/golden/run_topic_snapshot.json",
       "agentflow/tests/golden/verify_all_snapshot.json"]


def walk(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            yield from walk(old.get(k), new.get(k), f"{path}.{k}" if path else str(k))
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            yield path, f"list 长度 {len(old)} → {len(new)}"
        else:
            for i, (a, b) in enumerate(zip(old, new)):
                yield from walk(a, b, f"{path}[{i}]")
    elif old != new:
        yield path, (old, new)


def main() -> int:
    for rel in REL:
        old = json.loads(subprocess.run(["git", "-C", "D:/Incubator", "show", f"{HEAD}:{rel}"],
                                        capture_output=True, check=True).stdout.decode())
        new = json.loads(open(f"D:/Incubator/{rel}", encoding="utf-8").read())
        if old == new:
            print(f"== {rel}: 逐字未动")
            continue
        diffs = list(walk(old, new))
        print(f"== {rel}：差异 {len(diffs)} 条")
        for path, val in diffs[:40]:
            if isinstance(val, tuple) and isinstance(val[0], str) and len(val[0]) > 120:
                a, b = val
                # 只打印差异所在的那一小段
                i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), 0)
                print(f"   {path}: …{a[max(0, i-60):i+80]!r} → …{b[max(0, i-60):i+80]!r}")
            else:
                print(f"   {path}: {str(val)[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
