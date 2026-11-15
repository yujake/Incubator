# -*- coding: utf-8 -*-
"""RE ②：record_finding 的产出必须能过 G10 的 maths 那一格（不许放宽 G10）。

## 现场（projects/lp-ball，2026-11-14；分析与原始读数见 temp/analysis/12-review-exit.md）

11 条手工判词的 `maths` 全空，G10 判 fail。根因在产出侧：`record_finding` 的工具
声明面里根本没有 `maths` 参数（加参数要动 `specs/h.py` 与两份 golden 快照，FC-27），
而 `schema.ReviewFinding.maths` 的默认值是空串 ⇒ G10 对任何 `record_finding` 产出
恒红，H 自己的格式门成了一个没有出口的格子。

## 修法

不动 G10 的判据，也不新造第二份判据：按 kind 从 `_FOUR_GATE_KEYS_OF_KIND` 读 maths
（机械那一支的 `_finding()` 用的就是这张产出侧声明表），于是"这个 kind 的发现要不要
读断言本身才能判"全仓只有一处声明。

## 判据成对（红→绿 + 反真空）

- e 正控：受控词表里每个 kind 各落一条 ⇒ 六格齐、G10 pass；
- e 反真空：同一批产出把 maths 抠掉（旧行为）⇒ G10 必须 fail；把 G10 的判据本体
  打桩成恒通过 ⇒ 上面这条必须红，也就证明正控的绿来自 maths 真的被写进去了，
  不是门被放宽了。
"""

from __future__ import annotations

import pytest

from agentflow import gates as G
from agentflow import schema as S
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import write_paper

TS = "2026-01-01T00:00:00+00:00"

#: G10 六格里由调用方给的五格（maths 是第六格，本文件判的就是它）。
_G10_CALLER_KEYS = {
    "axis": "体例",
    "suggestion": "按本发现 message 指出的那一格改正",
    "verbatim_quote": "谱落在区间内",
    "line": 12,
}


def _workspace(store: Store) -> Store:
    write_paper(store)
    row = S.Document(
        doc_id="0000", kind="paper", title="RE ② 探针稿", markdown_path=None,
        claims=[{
            "claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
            "evidence_kind": "heuristic", "citations": ["lit:0000"],
            "is_negative": False, "negation_kind": None,
        }],
        status="draft", review_rounds=0, created_at=TS, updated_at=TS,
    ).to_dict()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    return store


def _record_every_kind(store: Store) -> list[dict]:
    """受控词表里每个 kind 各落一条 record_finding，返回盘上的行。"""
    agent = AgentH(store)
    for kind in S.FINDING_KINDS:
        res = agent.writers.call(
            "review.record_finding", role="H", doc_id="0000", kind=kind,
            target=f"claim-{kind}", message=f"手工判词（{kind}）：这一格要改",
            evidence=f"正文第 12 行逐字：谱落在区间内（{kind}）",
            level="warning", round_no=1, **_G10_CALLER_KEYS,
        )
        assert res.ok is True, res.error
    rows = [dict(r) for r in store.rows("review_findings")]
    assert len(rows) == len(S.FINDING_KINDS), rows
    return rows


def _g10(rows: list[dict]):
    return G.gate_g10(G.GateContext.build(None, findings=list(rows)))


def _e_criterion(rows: list[dict]) -> list[str]:
    """e 的判据本体：产出过 G10，且同一批产出抠掉 maths 必须被 G10 拒（成对才算数）。"""
    problems: list[str] = []
    got = _g10(rows)
    if got.verdict != "pass":
        problems.append(f"record_finding 的产出过不了 G10：verdict={got.verdict} reason={got.reason}")
    stripped = [dict(r, maths="") for r in rows]
    old = _g10(stripped)
    if old.verdict == "pass":
        problems.append(
            "把 maths 抠掉（旧行为）之后 G10 仍然通过 ⇒ 这条判据是真空的："
            "G10 的 maths 那一格被放宽了，正控的绿不能证明产出侧补上了它"
        )
    return problems


# ============================================================ e 正控


def test_e_record_finding_output_passes_g10(store: Store):
    """每个 kind 的 record_finding 产出都过 G10，且 maths 取自产出侧声明表。"""
    _workspace(store)
    rows = _record_every_kind(store)
    for row in rows:
        kind = str(row["kind"])
        expected = RV._FOUR_GATE_KEYS_OF_KIND[kind][1]
        assert row["maths"] == expected, (kind, row["maths"], expected)
        assert row["maths"] in S.FINDING_MATHS_VALUES
    assert _e_criterion(rows) == [], _e_criterion(rows)


# ============================================================ e 反真空


def test_e_anti_vacuum_a_always_passing_g10_makes_the_criterion_red(store: Store, monkeypatch):
    """反真空：把 G10 的判据本体打桩成恒通过 ⇒ e 的判据必须红。"""
    _workspace(store)
    rows = _record_every_kind(store)
    assert _e_criterion(rows) == []

    # 恒通过桩：直接复用一次真 G10 的 pass 结果（判据本体不再看输入）。
    always_pass = _g10(rows)
    assert always_pass.verdict == "pass"
    monkeypatch.setattr(G, "gate_g10", lambda ctx: always_pass)

    problems = _e_criterion(rows)
    assert problems, problems
    assert any("真空" in p for p in problems), problems
