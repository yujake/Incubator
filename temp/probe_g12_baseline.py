# -*- coding: utf-8 -*-
"""G-12 取证探针：15 门的 `criterion_revision` 与声明表逐字比对（两条返回路径各自看）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow import gates as G  # noqa: E402

TS = "2025-01-01T00:00:00Z"


def claim(**over):
    base = {
        "claim_id": "claim-1", "kind": "定理", "statement": "谱落在区间内。", "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {"script": "code/p1.py", "range": "d<=33", "n_cases": 256,
                             "n_counterexamples": 0},
        "counterexamples": [], "frozen": False, "freeze_reason": "", "allowed_use": "主结果",
        "scope_caveat": "", "revision_hash": "deadbeefdeadbeef", "errata_ids": [],
        "evidence_kind": "proof", "citations": ["rel:0000"], "is_negative": False,
        "negation_kind": None, "disclaimer": "", "section": "主要结果",
    }
    base.update(over)
    return base


def doc(**over):
    base = {
        "doc_id": "0000", "kind": "paper", "title": "门测试稿件",
        "markdown_path": "documents/0000.md", "claims": [claim()], "open_problems": [],
        "status": "draft", "review_rounds": 0, "created_at": TS, "updated_at": TS,
    }
    base.update(over)
    return base


root = Path(tempfile.mkdtemp()) / "ws"
(root / "code").mkdir(parents=True)
(root / "documents").mkdir(parents=True)
(root / "code" / "p1.py").write_text("print('ok')\n", encoding="utf-8")
(root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")

FULL_FINDING = {
    "finding_id": "0000", "kind": "overclaim", "level": "warning", "target": "claim-1",
    "message": "m", "evidence": "e", "line": 12, "verbatim_quote": "已证明",
    "minimal_fix": "改成『交叉验证』", "maths": "yes", "axis": G.AXES[0],
}
SCHEMA_ONLY_FINDING = {
    "finding_id": "0000", "kind": "overclaim", "level": "error", "target": "claim-1",
    "message": "m", "evidence": "e", "status": "open", "round": 1, "resolution_note": "",
}


def full_ctx(**over):
    kw = {
        "dependencies": [], "files": ["code/p1.py"], "workspace_root": root,
        "run_evidence": {"checked": True, "commands": [
            {"claim_id": "claim-1", "command": "python code/p1.py", "output_tail": "PASS"}]},
        "findings": [], "claim_counts": {"declared_claim_count": 1,
                                         "declared_counterexample_count": 0,
                                         "declared_script_count": 1},
        "banned_words": [], "literals": {}, "observed_hash": None, "own_errors": [],
    }
    kw.update(over)
    ctx = G.GateContext.build(doc(), **kw)
    ctx.observed_hash = ctx.revision_hash
    return ctx


print("=" * 100)
print("A) 全输入上下文：GateResult.criterion_revision  vs  GATE_CRITERIA_REVISION[gid]")
print("=" * 100)
ctx = full_ctx()
bad_full = []
for gid in G.GATE_IDS:
    r = G.run_gate(gid, ctx)
    declared = G.GATE_CRITERIA_REVISION[gid]
    same = r.criterion_revision == declared
    if not same:
        bad_full.append(gid)
    print(f"{gid:>4} {'SAME' if same else 'DIFF'} verdict={r.verdict:<15}")
    if not same:
        print(f"      声明表: {declared}")
        print(f"      报告里: {r.criterion_revision}")
print(f"→ 不一致 {len(bad_full)} / {len(G.GATE_IDS)}：{bad_full}")

print()
print("=" * 100)
print("B) doc=None 上下文（`_no_doc` 那条返回路径）：GateResult.criterion_revision  vs  声明表")
print("=" * 100)
ctx_nodoc = G.GateContext.build(None)
bad_nodoc = []
for gid in G.GATE_IDS:
    r = G.run_gate(gid, ctx_nodoc)
    declared = G.GATE_CRITERIA_REVISION[gid]
    same = r.criterion_revision == declared
    if not same:
        bad_nodoc.append(gid)
    print(f"{gid:>4} {'SAME' if same else 'DIFF'} verdict={r.verdict:<15} 报告里={r.criterion_revision!r}")
print(f"→ 不一致 {len(bad_nodoc)} / {len(G.GATE_IDS)}：{bad_nodoc}")

print()
print("=" * 100)
print("C) G10 两条返回路径各自的 criterion_revision（事实判定）")
print("=" * 100)
r_unknown = G.gate_g10(full_ctx(findings=[SCHEMA_ONLY_FINDING]))
r_pass = G.gate_g10(full_ctx(findings=[FULL_FINDING]))
print(f"字段缺（schema-only findings）→ verdict={r_unknown.verdict!r}  revision={r_unknown.criterion_revision!r}")
print(f"字段齐（六字段 findings）    → verdict={r_pass.verdict!r}  revision={r_pass.criterion_revision!r}")
print(f"声明表 G10                    → {G.GATE_CRITERIA_REVISION['G10']!r}")
print(f"两条路径文本是否相同：{r_unknown.criterion_revision == r_pass.criterion_revision}")

print()
print("=" * 100)
print("D) 同一个门是否有多条返回路径打印不同 revision 文本（除 G10 外）")
print("=" * 100)
variants = {}
for gid in G.GATE_IDS:
    seen = set()
    seen.add(G.run_gate(gid, full_ctx()).criterion_revision)
    seen.add(G.run_gate(gid, ctx_nodoc).criterion_revision)
    try:
        seen.add(G.run_gate(gid, full_ctx(findings=[SCHEMA_ONLY_FINDING])).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(findings=[FULL_FINDING])).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(own_errors=None)).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(banned_words=None)).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(claim_counts=None)).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(run_evidence=None)).criterion_revision)
        seen.add(G.run_gate(gid, full_ctx(observed_hash=None)).criterion_revision)
    except Exception as e:  # noqa: BLE001
        print(f"{gid} 探针路径抛异常：{type(e).__name__}: {e}")
    variants[gid] = seen
for gid, seen in variants.items():
    flag = "MULTI" if len(seen) > 1 else "single"
    print(f"{gid:>4} {flag} 不同文本数={len(seen)}")
    if len(seen) > 1:
        for t in sorted(seen):
            print(f"        - {t!r}")

print()
print("=" * 100)
print("E) 声明表在运行期是否被读到（值位置 vs 键检查位置）")
print("=" * 100)
src = Path(r"D:\Incubator\agentflow\src\agentflow\gates.py").read_text(encoding="utf-8")
for i, line in enumerate(src.splitlines(), 1):
    if "GATE_CRITERIA_REVISION" in line:
        print(f"{i:>5}: {line.strip()}")
print("→ 若只出现在 `not in` 键检查里，则声明表是死的。")
