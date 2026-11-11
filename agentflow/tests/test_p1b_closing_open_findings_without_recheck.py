# -*- coding: utf-8 -*-
"""乙（2026-11-11）：收工门要认出「有 open findings 却没收过复审」（d / e / f）。

## 现场

`projects/dct-min4-20261111`：`documents/000000` 是 `status=draft`、`review_rounds=0`，
而 H 的 7 条 findings 全是 `open`。旧判据的两条（`status ∈ {accepted,revised}` 或
`review_rounds >= 1`）都不满足 ⇒ `reviewed_current_rows` 这一档 0/0 空转，
7 条 open 没人管也照样收工。

## 修法

`claimed` 多认一档：该稿件有 `status=open` 的 findings。于是这一档的分母 ≥ 1，
而 `pinned=0` ⇒ 收工门红；读数里逐条列「哪几条 open、谁该处理」
（手工判词只有 H 能复核掉；机械发现由 G 改稿后 H 重跑）。验收表没写这一档时，
门也替它说话（自动分支与 `stale_signoffs` 同形）。

- d 正控：7 条 open + 0 轮复审 ⇒ 收工门点名；
- e 反向：7 条全 fixed ⇒ 不点名；
- f 反真空：把这一档的读数摘掉 ⇒ d 红（门不再点名）。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from test_closing_gate import _acceptance_checks, _gate, _good


def _seed_manual_findings(store: Store, doc_id: str, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        got = RV.record_finding(
            store, doc_id=doc_id, kind="overclaim", target=f"claim-{i + 1}",
            message=f"手工判词 {i + 1}：正文把交叉验证说成了证明",
            evidence=f"正文第 {i + 10} 行逐字：'we have proved it'",
            level="error", round_no=1,
        )
        ids.append(str(got["finding_id"]))
    return ids


def _mark_all_fixed(store: Store, ids: list[str]) -> None:
    with store.tx("review_findings", actor="test", note="夹具：全修好") as tx:
        for fid in ids:
            row = dict(tx.find("review_findings", finding_id=fid))
            row["status"] = "fixed"
            row["resolution_note"] = "[round 2] H 显式复核 ⇒ fixed（夹具）"
            tx.upsert("review_findings", row)


def _benign_acceptance(tmp_path: pathlib.Path, st: Store) -> None:
    """只写一行不会因"有没有复审"而红的档（让 `reviewed_current_rows` 走自动分支）。"""
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件在盘上", "kind": "document_rows", "min": 1},
    ], st=st)


def _blocker_text(rep) -> str:
    return "；".join(f.detail for f in rep.blockers if f.check == "acceptance")


# ============================================================ d 正控


def test_d_open_findings_without_recheck_turn_the_gate_red(tmp_path: pathlib.Path):
    """7 条 open + 0 轮复审 ⇒ 收工门点名（逐条：哪几条、谁处理）。"""
    st, report = _good(tmp_path)
    doc = next(dict(r) for r in st.rows("documents"))
    ids = _seed_manual_findings(st, str(doc["doc_id"]), 7)
    _benign_acceptance(tmp_path, st)
    _g0, _cur0 = CL._leg_reading(st, "reviewed_current_rows", st.root)
    assert _cur0["open_findings_total"] == 7, _cur0
    assert _cur0["open_findings_unreviewed"], _cur0

    rep = _gate(st, report)
    detail = _blocker_text(rep)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert "open findings" in detail, detail
    for fid in ids:
        assert fid in detail, (fid, detail)
    # "谁该处理"必须逐条写出来：手工判词只有 H 能显式复核掉
    assert "H（`review.record_finding` 的显式复核通道" in detail, detail
    # 读数本身（不只是 blocker 文字）
    _got, cur = CL._leg_reading(st, "reviewed_current_rows", st.root)
    assert cur["open_findings_total"] == 7, cur
    assert cur["open_findings_unreviewed_docs"] == [str(doc["doc_id"])], cur
    owners = {f["owner"] for o in cur["open_findings_unreviewed"] for f in o["findings"]}
    assert len(owners) == 1 and "显式复核通道" in next(iter(owners)), owners
    assert "H.verify_fixes" in cur["next_step"], cur["next_step"]


# ============================================================ e 反向


def test_e_all_fixed_findings_are_not_named(tmp_path: pathlib.Path):
    """反向：7 条全 fixed ⇒ 这一档不点名（收工门不再红在这一条上）。"""
    st, report = _good(tmp_path)
    doc = next(dict(r) for r in st.rows("documents"))
    ids = _seed_manual_findings(st, str(doc["doc_id"]), 7)
    _mark_all_fixed(st, ids)
    _benign_acceptance(tmp_path, st)

    _got, cur = CL._leg_reading(st, "reviewed_current_rows", st.root)
    assert cur["open_findings_total"] == 0, cur
    assert cur["open_findings_unreviewed"] == [], cur
    rep = _gate(st, report)
    detail = _blocker_text(rep)
    assert "open findings" not in detail, detail
    assert rep.status["acceptance"] != "fail" or "open findings" not in detail


# ============================================================ f 反真空


def test_f_removing_the_branch_makes_d_red(tmp_path: pathlib.Path, monkeypatch):
    """反真空：把 `open_findings_unreviewed` 这一档的读数摘掉 ⇒ 门不再点名（d 红）。"""
    st, report = _good(tmp_path)
    doc = next(dict(r) for r in st.rows("documents"))
    _seed_manual_findings(st, str(doc["doc_id"]), 7)
    _benign_acceptance(tmp_path, st)

    real = CL._leg_reading

    def _stripped(store, kind, project_root):
        got, detail = real(store, kind, project_root)
        if kind == "reviewed_current_rows" and isinstance(detail, dict):
            detail = dict(detail)
            detail.pop("open_findings_unreviewed", None)
            detail.pop("open_findings_total", None)
        return got, detail

    monkeypatch.setattr(CL, "_leg_reading", _stripped)
    rep = _gate(st, report)
    detail = _blocker_text(rep)
    # 摘掉之后：7 条 open 没人点名 —— 这正是 d 要抓的形态（d 的断言会红）
    assert "open findings" not in detail, detail
