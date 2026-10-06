"""只读探针：拿**当前** schema 去校验 projects/*/data 下的每一份历史快照。

回答"validate_table 会不会因为某条判据把历史快照判死"这个问题。
"""
from __future__ import annotations

import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(r"D:\Incubator\agentflow\src")))

from agentflow import schema as S  # noqa: E402

ROOT = pathlib.Path(r"D:\Incubator\agentflow\projects")
by_table: dict[str, dict] = {spec["file"]: t for t, spec in S.TABLES.items()}
ok = collections.Counter()
bad: dict[str, list[str]] = collections.defaultdict(list)

for p in sorted(ROOT.glob("*/data/*.json")):
    table = by_table.get(p.name)
    if table is None:
        continue
    import json
    doc = json.loads(p.read_text(encoding="utf-8"))
    try:
        S.validate_table(table, doc)
        ok[table] += 1
    except Exception as exc:  # noqa: BLE001
        bad[table].append(f"{p.parent.parent.name}/{p.name}: {type(exc).__name__}: {str(exc)[:200]}")

print("通过：", dict(ok))
print("失败：", {k: len(v) for k, v in bad.items()})
for table, items in sorted(bad.items()):
    for line in items[:6]:
        print(f"  [{table}] {line}")
