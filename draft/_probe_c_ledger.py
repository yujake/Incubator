"""只读探针：统计 projects/*/data/*.json 里的真实取值分布（调查 C 用）。

不改任何仓库文件；输出到 stdout，由调用方重定向。
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(r"D:\Incubator\agentflow\projects")

FIELDS = {
    "literature.json": ["matched", "type", "processed", ("download", "status")],
    "relations.json": ["status", ("quote_verified",)],
    "statements.json": ["origin", "status", "evidence_kind", "quote_verified", "kind"],
    "conjectures.json": ["status", "form"],
    "documents.json": ["status", "kind"],
    "experiments.json": ["method", "evidence_kind", "result", "negation_kind"],
    "search_requests.json": ["mode", "done", "outcome", "priority", "submitted_by"],
    "reprocess_requests.json": ["status", "result", "reason"],
    "dependencies.json": ["status", "kind"],
    "research_questions.json": ["status", "kind", "contradiction_verdict"],
    "review_findings.json": ["kind", "level", "status", "axis", "maths"],
    "tasks.json": ["status", "outcome", "refusal_reason", "role"],
    "usage_ledger.json": ["scope"],
    "concepts.json": ["merged_into"],
    "attack_plans.json": ["status"],
    "analysis_reports.json": ["kind"],
    "eval_results.json": ["k"],
}

counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
files_seen = 0
rows_seen = 0
parse_fail: list[str] = []


def value_of(row: dict, field):
    if isinstance(field, tuple):
        cur = row
        for part in field:
            if not isinstance(cur, dict):
                return "<missing>"
            cur = cur.get(part)
        return cur
    return row.get(field, "<missing>")


for fname, fields in FIELDS.items():
    for p in sorted(ROOT.glob(f"*/data/{fname}")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            parse_fail.append(f"{p}: {exc}")
            continue
        files_seen += 1
        for row in doc.get("rows") or []:
            rows_seen += 1
            for f in fields:
                key = f if isinstance(f, str) else ".".join(f)
                v = value_of(row, f)
                counts[f"{fname.split('.')[0]}.{key}"][repr(v)] += 1

print(f"files={files_seen} rows={rows_seen} parse_fail={len(parse_fail)}")
for k in sorted(counts):
    c = counts[k]
    top = ", ".join(f"{v}×{n}" for v, n in c.most_common(12))
    print(f"{k}: {top}")
for f in parse_fail:
    print("PARSE_FAIL", f)
sys.exit(0)
