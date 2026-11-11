# -*- coding: utf-8 -*-
"""P2-4：手工判词不许被 `verify_fixes` 的自动复跑判掉（j / k / l）。

## 现场（`projects/dct-min4-20261111` 真机读数）

H 的 7 条发现全部是 `review.record_finding` 落的手工判词（散文 key：
`(kind, target, message)`），而 `verify_fixes` 的 resolved 判据是
「上一轮的 key 不在本轮 `scan_document` 结果里」——

    散文 key 永远不在 scan 结果里 ⇒ 只要 H 跑一次 `verify_fixes`，
    那 7 条会被全部标成 `fixed`（"重跑对应检查不再复现"），而一条检查都没重跑。

这正是 `R-04-b`（"没查 ≠ 修好"）在手工判词这一支上的同形缺口：改前它只保护了
语义判据产的那一支（`_is_semantic_finding`），手工判词没有任何标记，结构上分不开。

## 本文件的判据

- j 正控：7 条手工 findings（G 已用 `revise` 把它们标成 fixed）+ 跑一次
  `verify_fixes` ⇒ 仍是 open，绝不变成 fixed；读数逐条说清
  「手工判词不能被自动复跑判掉」。
- k 反向：H 显式复核过的手工判词（同一个去重键、`evidence` 以
  `复核 fixed：` / `复核 wontfix：` 开头）能离场，且 `resolution_note` 指到
  复核那一次（`[H 复核] [round N]`）；之后的 `verify_fixes` 不许把它改回去。
- l 反真空：把这道判据摘掉（`_is_manual_finding` 恒 False）⇒ j 立刻红（7 条全 fixed）。

## 为什么来源标记写在 `resolution_note`、复核走 `evidence`

`schema.ReviewFinding` 在 FC-27 禁改区（本批不许加列）；工具声明面被两份冻结
快照钉住（加参数要重冻 golden，本批未获授权）。所以：

- 来源标记 = 既有自由文本 `resolution_note` 的受控前缀 `[manual] `；
- 显式复核 = 既有参数 `evidence` 的两个受控前缀。

这两处都是同一张表的既有字段，不新造第二份账。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import add_literature, write_paper

TS = "2026-01-01T00:00:00+00:00"


def _claim() -> dict:
    return {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "heuristic",
        "citations": ["lit:0000"],
        "is_negative": False,
        "negation_kind": None,
    }


def _workspace(store: Store) -> Store:
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n谱落在区间内。\n\\end{document}\n")
    add_literature(store, "0000", title="探针文献", processed=True)
    row = S.Document(
        doc_id="0000", kind="paper", title="P2-4 探针稿", markdown_path=None,
        claims=[_claim()], status="draft", review_rounds=0,
        created_at=TS, updated_at=TS,
    ).to_dict()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    return store


def _record(agent: AgentH, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        res = agent.writers.call(
            "review.record_finding", role="H", doc_id="0000",
            kind="overclaim",
            target=f"claim-{i + 1}",
            message=f"手工判词 {i + 1}：这句把交叉验证说成了证明",
            evidence=f"正文第 {i + 10} 行逐字：'we have proved it'",
            level="error",
            # 一轮审校里落的 7 条属于同一轮（`record_finding` 不给时按"已有最大轮次+1"
            # 逐条递增，那是它的旧口径；这里显式给同一轮，才复现真机"一轮 7 条"的形态）。
            round_no=1,
        )
        assert res.ok is True, res.error
        ids.append(res.data["finding_id"])
    return ids


def _status(store: Store) -> dict[str, str]:
    return {str(r["finding_id"]): str(r["status"]) for r in store.rows("review_findings")}


# ============================================================ j 正控


def test_j_manual_findings_stay_open_after_a_verify_fixes_run(store: Store):
    """7 条手工判词 + 跑一次 `verify_fixes` ⇒ 仍是 open；读数点名它们。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 3})
    ids = _record(agent, 7)
    rows = {str(r["finding_id"]): r for r in store.rows("review_findings")}
    assert all(str(rows[i]["resolution_note"]).startswith(RV.MANUAL_FINDING_NOTE_PREFIX)
               for i in ids), rows

    # 真机的形态：G 先用 revise 把它们标成 fixed（"改完了"），然后 H 跑 verify_fixes。
    AgentG(store).revise("0000", fixed_findings=ids, note="按 H 的发现改了正文")
    assert set(_status(store).values()) == {"fixed"}

    res = agent.verify_fixes("0000", round_no=2)

    after = _status(store)
    assert [after[i] for i in ids] == ["open"] * 7, after
    assert res["resolved"] == [], res["resolved"]
    sources = {f["finding_id"]: f.get("source") for f in res["still_open"]}
    assert [sources[i] for i in ids] == ["manual_not_rechecked"] * 7, sources
    assert len(res["not_rechecked"]) == 7, res["not_rechecked"]
    assert all(f.get("note") for f in res["not_rechecked"])
    assert "手工判词" in res["reason"], res["reason"]
    assert "不能被自动复跑判掉" in res["reason"], res["reason"]
    # 一条机械 checks 都没重跑这件事必须写在 reason 里（不是把它说成"重跑过"）
    assert "显式复核" in res["reason"], res["reason"]


# ============================================================ k 反向：H 显式复核能离场


def test_k_an_explicit_h_recheck_lets_a_manual_finding_leave(store: Store):
    """H 显式复核 ⇒ fixed / wontfix 能离场，读数指到复核那一次。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 5})
    fid = _record(agent, 1)[0]

    # k-1：H 重新判过、这一条已经不再成立 ⇒ fixed
    got = agent.writers.call(
        "review.record_finding", role="H", doc_id="0000",
        kind="overclaim", target="claim-1",
        message="手工判词 1：这句把交叉验证说成了证明",
        evidence=f"{RV.RECHECK_FIXED_PREFIX}第 10 行已改成 'numerically supported'，不再声称已证明",
        round_no=2,
    )
    assert got.ok is True, got.error
    assert got.data["created"] is False and got.data["status"] == "fixed", got.data
    row = next(r for r in store.rows("review_findings") if r["finding_id"] == fid)
    assert row["status"] == "fixed"
    assert RV.MANUAL_RECHECK_MARK in row["resolution_note"], row["resolution_note"]
    assert "[round 2]" in row["resolution_note"], row["resolution_note"]

    # k-2：之后跑 verify_fixes（round 3）不许把它改回去
    res = agent.verify_fixes("0000", round_no=3)
    row2 = next(r for r in store.rows("review_findings") if r["finding_id"] == fid)
    assert row2["status"] == "fixed", row2
    assert [f for f in res["still_open"] if f["finding_id"] == fid] == [], res["still_open"]
    assert [f for f in res["resolved"] if f["finding_id"] == fid][0]["source"] == "manual_rechecked"
    assert "显式复核" in res["reason"], res["reason"]

    # k-3：wontfix 也必须能离场，但理由必填
    fid2 = _record(agent, 2)[1]
    bad = agent.writers.call(
        "review.record_finding", role="H", doc_id="0000",
        kind="overclaim", target="claim-2",
        message="手工判词 2：这句把交叉验证说成了证明",
        evidence=RV.RECHECK_WONTFIX_PREFIX,
    )
    assert bad.ok is False and "理由" in str(bad.error), bad
    good = agent.writers.call(
        "review.record_finding", role="H", doc_id="0000",
        kind="overclaim", target="claim-2",
        message="手工判词 2：这句把交叉验证说成了证明",
        evidence=f"{RV.RECHECK_WONTFIX_PREFIX}这是文献原句的逐字翻译，标题已给出出处",
    )
    assert good.ok is True and good.data["status"] == "wontfix", good.data
    assert next(r for r in store.rows("review_findings")
                if r["finding_id"] == fid2)["status"] == "wontfix"


def test_k2_an_explicit_recheck_cannot_be_used_as_a_stamp(store: Store):
    """负控：复核前缀只能用在已登记的手工判词上（不许当盖章工具）。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 3})
    missing = agent.writers.call(
        "review.record_finding", role="H", doc_id="0000",
        kind="overclaim", target="claim-9", message="不存在的一条",
        evidence=f"{RV.RECHECK_FIXED_PREFIX}我说它好了",
    )
    assert missing.ok is False and "不存在" in str(missing.error), missing

    # 机械扫描产的发现（review_document 落的）不许用这句话离场：
    # 它必须由 verify_fixes 重跑对应检查判定。
    S.ReviewFinding(finding_id="999999", doc_id="0000", kind="overclaim",
                    level="error", target="claim-1", evidence="citations=[]",
                    message="机械发现", status="open", created_at=TS,
                    created_by="agent-H").validate()
    with store.tx("review_findings", actor="test", note="机械发现") as tx:
        tx.upsert("review_findings", {
            "finding_id": "999999", "doc_id": "0000", "kind": "overclaim",
            "level": "error", "target": "claim-1", "evidence": "citations=[]",
            "message": "机械发现", "round": 1, "suggestion": "", "status": "open",
            "resolution_note": "", "created_at": TS, "created_by": "agent-H",
            "axis": "", "line": None, "line_unavailable_reason": "",
            "verbatim_quote": "", "maths": "",
        })
    scanned = agent.writers.call(
        "review.record_finding", role="H", doc_id="0000",
        kind="overclaim", target="claim-1", message="机械发现",
        evidence=f"{RV.RECHECK_FIXED_PREFIX}我说它好了",
    )
    assert scanned.ok is False and "机械扫描" in str(scanned.error), scanned


# ============================================================ l 反真空


def test_l_removing_the_gate_makes_the_positive_control_red(store: Store, monkeypatch):
    """反真空：把「手工判词」这道判据摘掉 ⇒ j 的 7 条会被全部标成 fixed。"""
    _workspace(store)
    agent = AgentH(store, config={"max_review_rounds": 3})
    ids = _record(agent, 7)
    AgentG(store).revise("0000", fixed_findings=ids, note="按 H 的发现改了正文")
    assert set(_status(store).values()) == {"fixed"}

    monkeypatch.setattr(RV, "_is_manual_finding", lambda row: False)
    agent.verify_fixes("0000", round_no=2)
    # 摘掉之后：7 条全 fixed —— 这正是要堵的形态（j 会红）
    assert [ _status(store)[i] for i in ids ] == ["fixed"] * 7, _status(store)
