"""临时探针（G-7 报告用）：逐门比对 criterion 与 criterion_revision 的"声明 vs 实现"。

不修改任何文件，只读 `gates.py` 并跑 15 道门，把两组文本打出来。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\Incubator\agentflow\src")

from agentflow import gates as G  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"


def claim(**over):
    base = {
        "claim_id": "claim-1", "kind": "定理", "statement": "谱落在区间内。", "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {"script": "code/p1.py", "range": "d<=33",
                             "n_cases": 256, "n_counterexamples": 0},
        "counterexamples": [], "frozen": False, "freeze_reason": "", "allowed_use": "主结果",
        "scope_caveat": "", "revision_hash": "h", "errata_ids": [], "evidence_kind": "proof",
        "citations": ["rel:0000"], "is_negative": False, "negation_kind": None,
        "disclaimer": "", "section": "主要结果",
    }
    base.update(over)
    return base


def doc():
    return {"doc_id": "0000", "kind": "paper", "title": "t", "markdown_path": "documents/0000.md",
            "claims": [claim()], "open_problems": [], "status": "draft", "review_rounds": 0,
            "created_at": TS, "updated_at": TS}


root = Path(r"D:\Incubator\temp\g7ws")
(root / "code").mkdir(parents=True, exist_ok=True)
(root / "documents").mkdir(parents=True, exist_ok=True)
(root / "code" / "p1.py").write_text("print(1)\n", encoding="utf-8")
(root / "documents" / "0000.md").write_text("# 稿\n", encoding="utf-8")

ctx = G.GateContext.build(
    doc(),
    dependencies=[],
    files=["code/p1.py"],
    workspace_root=root,
    run_evidence={"checked": True,
                  "commands": [{"claim_id": "claim-1", "command": "python code/p1.py",
                                "output_tail": "ALL CHECKS PASS"}]},
    findings=[],
    claim_counts={"declared_claim_count": 1, "declared_counterexample_count": 0,
                  "declared_script_count": 1},
    banned_words=[],
    literals={},
    own_errors=[],
)
ctx.observed_hash = ctx.revision_hash

print("=" * 78)
print("criterion 逐门比对（修后应全部一致）")
print("=" * 78)
bad = 0
for gid in G.GATE_IDS:
    r = G.run_gate(gid, ctx)
    d = G.GATES[gid]["criterion"]
    ok = r.criterion == d
    bad += 0 if ok else 1
    print(f"{gid:4} {'OK ' if ok else 'DRIFT'}  {r.criterion[:70]}")
print(f"--> criterion 不一致门数 = {bad}")

print()
print("=" * 78)
print("criterion_revision 逐门比对（声明表 GATE_CRITERIA_REVISION vs GateResult）")
print("=" * 78)
bad2 = 0
for gid in G.GATE_IDS:
    r = G.run_gate(gid, ctx)
    d = G.GATE_CRITERIA_REVISION[gid]
    if r.criterion_revision == d:
        print(f"{gid:4} OK")
    else:
        bad2 += 1
        print(f"{gid:4} DRIFT")
        print(f"      声明表: {d}")
        print(f"      实现  : {r.criterion_revision}")
print(f"--> criterion_revision 不一致门数 = {bad2}")
