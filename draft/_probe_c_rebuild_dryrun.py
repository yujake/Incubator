"""只读探针：对每个 projects/* 跑一次"重建模拟"（不落盘），看会被静默丢多少行。

复用 `store.Store.read_events` 与 `schema.row_from_dict`，逐条按 `rebuild` 的折叠规则走，
但不调用 `_atomic_write` —— 不改任何文件。
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(r"D:\Incubator\agentflow\src")))

from agentflow import schema as S  # noqa: E402
from agentflow import store as ST  # noqa: E402

ROOT = pathlib.Path(r"D:\Incubator\agentflow\projects")

tot = collections.Counter()
per_project: list[str] = []


def snap_keys(data: pathlib.Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table, spec in S.TABLES.items():
        p = data / spec["file"]
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rows = doc.get("rows")
        if not isinstance(rows, list):
            continue
        idf = spec["id_field"]
        out[table] = {str(r.get(idf)) for r in rows
                      if isinstance(r, dict) and r.get(idf) is not None}
    return out


for proj in sorted(ROOT.iterdir()):
    data = proj / "data"
    if not (data / "events.jsonl").exists():
        continue
    st = ST.Store(proj)
    events = st.read_events()
    committed = {str(e["batch"]) for e in events
                 if e.get("op") == "commit" and e.get("batch")}
    replay = []
    incomplete = set()
    for e in events:
        b = e.get("batch")
        if b is None:
            replay.append(e)
            continue
        b = str(b)
        if b in committed:
            replay.append(e)
        else:
            incomplete.add(b)

    state: dict[str, dict] = {t: {} for t in S.TABLES}
    order: dict[str, list[str]] = {t: [] for t in S.TABLES}
    skipped = collections.Counter()
    unknown: set[str] = set()
    for e in replay:
        op = e.get("op")
        if op == "delete":
            t = e.get("table")
            if t in S.TABLES:
                k = e.get("key")
                if k is not None:
                    state[t].pop(str(k), None)
            continue
        if op != "upsert":
            if op not in ST._KNOWN_NON_REPLAY_OPS:
                unknown.add(str(op))
            continue
        t = e.get("table")
        row = e.get("row") or {}
        if t == "counters" or t not in S.TABLES:
            continue
        try:
            obj = S.row_from_dict(t, row)
            obj.validate()
        except Exception:  # noqa: BLE001
            skipped[t] += 1
            continue
        k = getattr(obj, S.TABLES[t]["id_field"])
        if k not in state[t]:
            order[t].append(k)
        state[t][k] = 1

    before = snap_keys(data)
    ahead = {t: sorted(keys - set(state[t])) for t, keys in before.items()
             if keys - set(state[t])}
    n_ahead = sum(len(v) for v in ahead.values())
    tot["projects"] += 1
    tot["skipped_rows"] += sum(skipped.values())
    tot["snapshot_ahead"] += n_ahead
    tot["incomplete_batches"] += len(incomplete)
    tot["corrupt"] += sum(1 for e in events if e.get("op") == "corrupt")
    tot["unknown_ops"] += len(unknown)
    if skipped or n_ahead or incomplete or unknown:
        per_project.append(
            f"{proj.name}: skipped={dict(skipped)} snapshot_ahead={n_ahead}"
            f" ({ {k: v[:3] for k, v in list(ahead.items())[:3]} })"
            f" incomplete_batches={len(incomplete)} unknown_ops={sorted(unknown)[:3]}"
        )

print("合计：", dict(tot))
for line in per_project:
    print("  ", line)
