# -*- coding: utf-8 -*-
"""VF 路探针：把 CLI 彩排这一趟的 llm_call 事件与 usage_ledger 逐笔摊开。

用法（在 `agentflow/` 下）::

    $env:PYTHONPATH='src;tests'; python -B temp/vf/probe_reading.py

只读：跑一趟彩排（只换出网层，与 `tests/test_rehearsal_cli_proof_main_chain.py`
同一份 `_run`），把读数写到 `temp/vf/reading.json` 并打一张表。
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PROJ = HERE.parents[1]
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "tests"))

import pytest  # noqa: E402

from test_rehearsal_cli_proof_main_chain import _run  # noqa: E402

(tmp := pathlib.Path(tempfile.mkdtemp(prefix="vf-probe-")))


def main() -> int:
    lean = sys.argv[1] if len(sys.argv) > 1 else "0"
    mp = pytest.MonkeyPatch()
    try:
        got = _run(tmp, mp, lean=lean)
    finally:
        mp.undo()
    ws, st = got["ws"], got["store"]
    calls = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") != "llm_call":
                continue
            ledger = dict(event.get("ledger") or {})
            calls.append({
                "session": path.stem,
                "role": str(event.get("role") or ""),
                "task_id": str(event.get("task_id") or ""),
                "note": str(event.get("note") or ""),
                "reason": str(ledger.get("reason") or ""),
                "usage_id": str(ledger.get("usage_id") or ""),
                "idem_key": str(ledger.get("idem_key") or ""),
            })
    rows = [dict(r) for r in st.rows("usage_ledger")]
    by_id = {str(r.get("usage_id") or ""): r for r in rows}
    for call in calls:
        row = by_id.get(call["usage_id"]) or {}
        note = str(row.get("note") or "")
        idx = ""
        for part in note.split(";"):
            if part.startswith("call_index="):
                idx = part.split("=", 1)[1]
        call["call_index"] = idx
    out = {"rc": got["rc"], "ws": str(ws), "calls": calls, "rows": rows}
    (HERE / "reading.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    print(f"rc={got['rc']} calls={len(calls)} rows={len(rows)}")
    print("| # | session | role | task | call_index | reason | usage_id |")
    print("|---|---|---|---|---|---|---|")
    for i, c in enumerate(calls):
        print(f"| {i} | {c['session']} | {c['role']} | {c['task_id']} | {c['call_index']} | "
              f"{c['reason']} | {c['usage_id']} |")
    print("\nusage_ledger:")
    for r in rows:
        print(f"  {r.get('usage_id')} role={r.get('role')} task={r.get('task_id')} "
              f"usd={r.get('usd')} note={str(r.get('note') or '')[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
