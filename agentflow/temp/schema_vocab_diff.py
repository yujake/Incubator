#!/usr/bin/env python
"""差分探针：把 `claimanatomy.validate_claim` 在**一批覆盖各校验分支的 claim** 上的
逐格结论 dump 成一份确定性的 JSON（题 2/B「行为逐字不变」的差分证据）。

用法（工作目录 `agentflow/`）：

    python -B temp/schema_vocab_diff.py out.json

为什么是"逐格"而不是"跑一遍测试"：本探针只读 `validate_claim` 的返回，
把每一格的 `checked / decided / verdict / status_axis / error_count /
warning_count / issues[(code, field_name, level, message)]` 逐字写下来。
改前改后各跑一次，两份 JSON 逐字节比对 —— 结论相同才算"行为逐字不变"。

本文件不是判据、也不进 `tests/`：它是一次性的差分工具。
"""

from __future__ import annotations

import json
import sys

from agentflow import claimanatomy as CA


def _base(**over: object) -> dict:
    """一条合法的最小断言；`over` 用来按需破坏某一格。"""
    claim = {
        "claim_id": "c-1",
        "statement": "谱落在区间内。",
        "citations": ["rel:0000"],
        "evidence_kind": "heuristic",
        "section": "主要结果",
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
    }
    claim.update(over)
    return claim


def _full(**over: object) -> dict:
    """12 字段齐全 + 台账四列的一条断言（走 strict 模式的"全过"那一档）。"""
    claim = _base(
        statement="存在无穷多个素数。",
        citations=["stmt:0004", "lit:0000#p.12-13"],
        evidence_kind="proof",
        kind="定理",
        status="证",
        proof_location="self_ref",
        numeric_evidence={"script": "s.py", "range": "n<=100",
                          "n_cases": 100, "n_counterexamples": 0},
        counterexamples=[],
        frozen=False,
        freeze_reason="",
        allowed_use="主结果",
        scope_caveat="",
        revision_hash="",
        errata_ids=[],
        source_kind="自证",
        our_check="证明",
        our_check_note="逐步推导走通。",
        falsifiable=True,
        falsifiable_note="反例搜索 n<=100 无。",
        paper_ref="",
        paper_excerpt="",
    )
    claim.update(over)
    return claim


#: 一组 claim，逐条点名它打的是哪一支判据（类别名只用于读表，不参与判据）。
FIXTURES: list[tuple[str, dict]] = [
    ("min-ok-heuristic", _base()),
    ("min-ok-proof", _base(evidence_kind="proof")),
    ("min-ok-cross_check-with-disclaimer",
     _base(evidence_kind="cross_check", disclaimer="数值交叉验证，不构成证明")),
    ("min-ok-negative-not_proved",
     _base(is_negative=True, negation_kind="not_proved")),
    ("full-12-fields", _full()),
    ("full-12-fields-abandoned-status",
     _full(status="作废", errata_ids=["E-01"], evidence_kind="heuristic")),
    ("kind-legal-定义", _full(kind="定义")),
    ("kind-legal-反例", _full(kind="反例")),
    ("kind-illegal", _base(kind="猜想")),
    ("status-legal-待精化", _full(status="待精化")),
    ("status-illegal-已证", _base(status="已证")),
    ("status-证-with-cross_check", _base(status="证", evidence_kind="cross_check",
                                         disclaimer="数值交叉验证，不构成证明")),
    ("status-验-with-proof", _base(status="验", evidence_kind="proof")),
    ("status-作废-without-reason", _base(status="作废")),
    ("status-作废-with-freeze_reason", _base(status="作废", freeze_reason="E-02 重编号")),
    ("allowed_use-legal", _full(allowed_use="Remark only")),
    ("allowed_use-illegal", _base(allowed_use="主结论")),
    ("numeric_evidence-complete", _full()),
    ("numeric_evidence-missing-keys",
     _base(numeric_evidence={"script": "s.py"})),
    ("numeric_evidence-not-object", _base(numeric_evidence=["script"])),
    ("source_kind-legal", _base(source_kind="文献")),
    ("source_kind-illegal", _base(source_kind="文献来源")),
    ("source_kind-trailing-space", _base(source_kind="文献 ")),
    ("our_check-legal", _base(our_check="只读了陈述")),
    ("our_check-illegal", _base(our_check="数值验证")),
    ("falsifiable-not-bool", _base(falsifiable="是")),
    ("falsifiable-note-not-str", _base(falsifiable_note=["反例搜索"])),
    ("paper_ref-not-str", _base(paper_ref=211)),
    ("undeclared-key", _base(source_kind_typo="文献")),
    ("citations-empty", _base(citations=[])),
    ("citations-missing-key", {k: v for k, v in _base().items() if k != "citations"}),
    ("citations-with-empty-element", _base(citations=["rel:0000", "  "])),
    ("citations-with-non-str", _base(citations=["rel:0000", 7])),
    ("citations-bare-number", _base(citations=["0004"])),
    ("citations-unknown-prefix", _base(citations=["zzz:0004"])),
    ("citations-stmt", _base(citations=["stmt:0004"])),
    ("citations-stmt-empty-ref", _base(citations=["stmt:"])),
    ("citations-no-colon", _base(citations=["0004abc"])),
    ("statement-vs-text-conflict", _base(text="另一句", statement="这一句")),
    ("text-alias-only", {"claim_id": "c-1", "text": "谱落在区间内。",
                         "citations": ["rel:0000"], "evidence_kind": "heuristic",
                         "section": "主要结果"}),
    ("no-claim_id", {k: v for k, v in _base().items() if k != "claim_id"}),
    ("empty-claim_id", _base(claim_id="  ")),
    ("empty-statement", _base(statement="   ")),
    ("missing-required-evidence_kind",
     {k: v for k, v in _base().items() if k != "evidence_kind"}),
    ("evidence_kind-illegal", _base(evidence_kind="prooof")),
    ("cross_check-without-disclaimer", _base(evidence_kind="cross_check")),
    ("heuristic-overclaim-wording", _base(statement="我们证明了该结论。")),
    ("negative-without-kind", _base(is_negative=True)),
    ("negation_kind-illegal", _base(is_negative=True, negation_kind="没查过")),
    ("negation_kind-without-negative", _base(negation_kind="not_proved")),
    ("frozen-true-without-reason", _base(frozen=True)),
    ("frozen-true-with-reason", _base(frozen=True, freeze_reason="已定稿")),
    ("whole-claim-is-a-list", ["not", "a", "mapping"]),
]


def _issues(spec: CA.ClaimSpec) -> list[dict]:
    return [
        {"code": i.code, "field": i.field_name, "level": i.level, "message": i.message}
        for i in spec.issues
    ]


def _row(name: str, strict: bool, claim: object) -> dict:
    spec = CA.validate_claim(claim, strict=strict)  # type: ignore[arg-type]
    return {
        "fixture": name,
        "strict": strict,
        "claim_id": spec.claim_id,
        "checked": spec.checked,
        "decided": spec.decided,
        "verdict": spec.verdict,
        "status_axis": spec.status_axis,
        "undecided_reason": spec.undecided_reason,
        "error_count": spec.error_count,
        "warning_count": spec.warning_count,
        "issues": _issues(spec),
    }


def main(argv: list[str]) -> int:
    out_path = argv[1] if len(argv) > 1 else "schema_vocab_diff.json"
    rows = [_row(name, strict, claim)
            for name, claim in FIXTURES
            for strict in (False, True)]
    # 同时把六张词表当前读到的值与身份写下来（"同一份"那一格的证据）。
    vocabs = {n: list(getattr(CA, n)) for n in (
        "CLAIM_KINDS", "CLAIM_STATUSES", "ALLOWED_USE_KINDS",
        "NUMERIC_EVIDENCE_KEYS", "CLAIM_SOURCE_KINDS", "CLAIM_CHECK_KINDS")}
    payload = {"rows": rows, "vocabs": vocabs}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"[probe] {len(rows)} 格 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
