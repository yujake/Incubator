"""只读探针：抽查 experiments 行的 method × evidence_kind × negation_kind 组合。"""
from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(r"D:\Incubator\agentflow\projects")
combo = collections.Counter()
neg_by_result = collections.Counter()
proof_no_verifier = []
bad = []
for p in sorted(ROOT.glob("*/data/experiments.json")):
    doc = json.loads(p.read_text(encoding="utf-8"))
    for r in doc.get("rows") or []:
        combo[(r.get("method"), r.get("evidence_kind"))] += 1
        neg_by_result[(r.get("result"), r.get("negation_kind"))] += 1
        if r.get("evidence_kind") == "proof":
            if not str(r.get("verifier_output") or "").strip():
                proof_no_verifier.append((str(p.parent.parent.name), r.get("experiment_id")))
            if r.get("method") != "formal":
                bad.append((str(p.parent.parent.name), r.get("experiment_id"), r.get("method")))
print("method x evidence_kind:")
for k, v in sorted(combo.items(), key=lambda kv: -kv[1]):
    print(f"   {k} = {v}")
print("result x negation_kind:")
for k, v in sorted(neg_by_result.items(), key=lambda kv: -kv[1]):
    print(f"   {k} = {v}")
print("proof rows without verifier_output:", len(proof_no_verifier), proof_no_verifier[:5])
print("non-formal rows claiming proof:", len(bad), bad[:5])
