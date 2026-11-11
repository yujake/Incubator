# -*- coding: utf-8 -*-
"""丙（2026-11-11，业主裁定「丙修」）：有 open findings 就不许 `accepted`。

## 真机现场（`projects/dct-min5r-20261111`，只读）

```
documents/000000: status=accepted / review_verdict=成立 / reviewed_by=agent-H
review_findings:  3 条全 open（2 error + 1 warning）
```

次序（H 的 run 记录）：21:42:12 `review.record_finding` 落 3 条手工判词 ⇒ 21:42:19
`review.review_document(round_no=4)`；那一趟只按新扫的 `error_count=0` 就把
`documents.status` 写成 `accepted`、`review_verdict` 写成「成立」—— 它没看盘上那 3 条
open findings，也不收口它们。`verify_all` 的 `accepted_with_open_error` 一直能抓到这个
矛盾，但那是"事后审计"，不是"不许写"。

## 修的是产生矛盾的那一侧

闸加在 `review_document` 的 `target_status` 判定（写 `documents.status` 的那一处），
不加在事后纠正；`review_findings` 的状态一个字节都不改。判据两条：
① 这一版没有 open findings；② 本轮复审收过（`round_no` / `documents.review_rounds`
一起进读数）—— 旧轮次的 open 项还挂着时，本轮没有收过那一版的全部发现。

## 这一组守什么

| # | 造什么 | 期望 |
|---|---|---|
| h | 先落 3 条 open（2 error + 1 warning），再 `review_document(error=0)` | `status != accepted`（停在 `in_review`）；不写「成立」；`open_findings` 读数点名 3 条 |
| i | 3 条全 fixed 之后再审一次 | `accepted` 放行（不是永远拒） |
| j | 反真空：把这条闸摘掉 | h 的断言红（`status` 又变回 `accepted`） |

零模型调用：正文 / 断言 / 发现都用夹具直接造。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import sync_counters, write_paper

CLAIM_TEXT = "谱落在区间内。"


def _claim() -> dict:
    return {
        "claim_id": "claim-1", "section": "主要结果", "text": CLAIM_TEXT,
        "evidence_kind": "cross_check", "citations": ["lit:0000"],
        "is_negative": False, "negation_kind": None,
        "disclaimer": "数值交叉验证，不构成证明",
    }


def _document_row(doc_id: str = "000000") -> dict:
    from agentflow import signatures as SIG

    row = S.Document(
        doc_id=doc_id, kind="paper", title="稿件", markdown_path=None,
        claims=[_claim()], status="in_review", review_rounds=0,
        created_at="2026-11-11T21:39:09+08:00",
        updated_at="2026-11-11T21:39:09+08:00").to_dict()
    row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def _seed(store: Store, doc_id: str = "000000") -> None:
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n"
                       f"{CLAIM_TEXT}\n\\end{{document}}\n")
    with store.tx("documents", actor="fixture") as tx:
        tx.upsert("documents", _document_row(doc_id))
    sync_counters(store)


def _record_three(store: Store, doc_id: str = "000000") -> list[str]:
    """复刻真机那 3 条（2 error + 1 warning，全部手工判词、全部 open）。"""
    ids: list[str] = []
    for i, level in enumerate(("error", "error", "warning")):
        got = RV.record_finding(
            store, doc_id=doc_id, kind="overclaim", target=f"claim-{i + 1}",
            level=level, round_no=i + 1,
            message=f"手工判词 {i + 1}：正文用词超过台账凭据",
            evidence=f"正文第 {i + 10} 行逐字：'we have proved it'（夹具）",
            axis="证据")
        ids.append(str(got["finding_id"]))
    return ids


def _mark_all_fixed(store: Store, ids: list[str]) -> None:
    with store.tx("review_findings", actor="test", note="夹具：全修好") as tx:
        for fid in ids:
            row = dict(tx.find("review_findings", finding_id=fid))
            row["status"] = "fixed"
            row["resolution_note"] = "[round 4] H 显式复核 ⇒ fixed（夹具）"
            tx.upsert("review_findings", row)


def _doc(store: Store) -> dict:
    return next(dict(r) for r in store.rows("documents"))


# ============================================================ h：真机次序
def test_h_open_findings_block_accepted(store: Store) -> None:
    _seed(store)
    ids = _record_three(store)
    res = RV.review_document(store, "000000", dependencies=[], round_no=4)
    # 机械扫描这一趟没找到缺陷 —— 但盘上还有 3 条 open：不许 accepted
    assert res["error_count"] == 0, res
    assert res["verdict"] == "accepted", res      # 机械判据的结论，允许留着
    assert res["status"] != "accepted", res
    assert res["status"] == "in_review", res
    doc = _doc(store)
    assert doc["status"] == "in_review", doc
    # 不写「成立」：这一版没有被本轮复审收口，写「成立」就是那个矛盾
    assert str(doc.get("review_verdict") or "") == "", doc
    # 读数点名 3 条，且分得清 error / warning
    reading = dict(res.get("open_findings") or {})
    assert reading.get("total") == 3, reading
    assert reading.get("error") == 2 and reading.get("warning") == 1, reading
    assert sorted(reading.get("finding_ids") or []) == sorted(ids), reading
    assert reading.get("blocks_accept") is True, reading
    assert "open findings" in str(res.get("reason") or ""), res.get("reason")
    assert "review.verify_fixes" in str(res.get("reason") or ""), res.get("reason")


# ============================================================ i：修好了就放行
def test_i_all_fixed_then_accepted_is_allowed(store: Store) -> None:
    _seed(store)
    ids = _record_three(store)
    blocked = RV.review_document(store, "000000", dependencies=[], round_no=4)
    assert blocked["status"] == "in_review", blocked
    _mark_all_fixed(store, ids)
    res = RV.review_document(store, "000000", dependencies=[], round_no=5)
    assert res["status"] == "accepted", res
    doc = _doc(store)
    assert doc["status"] == "accepted", doc
    assert str(doc.get("review_verdict") or "") == "成立", doc
    assert (res.get("open_findings") or {}).get("total") == 0, res


# ============================================================ j：反真空
def test_j_removing_the_gate_turns_h_red(store: Store, monkeypatch) -> None:
    """把「有 open findings 就不许 accepted」那一条摘掉 ⇒ 真机次序必须变回 accepted。"""
    _seed(store)
    _record_three(store)

    def _no_gate(**__):
        return [], {"checked": True, "total": 0, "error": 0, "warning": 0,
                    "finding_ids": [], "review_round": 4, "review_rounds": 0,
                    "blocks_accept": False, "why": "打桩：这条闸摘掉了"}

    monkeypatch.setattr(RV, "_open_findings_gate", _no_gate)
    res = RV.review_document(store, "000000", dependencies=[], round_no=4)
    assert res["status"] == "accepted", res
    assert _doc(store)["status"] == "accepted", _doc(store)
