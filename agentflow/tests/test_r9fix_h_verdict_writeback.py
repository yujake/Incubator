# -*- coding: utf-8 -*-
"""R9FIX · D9：H 这一趟最后一份审校报告的裁决回写 `documents` 审核轴。

## 现场（真机 lp-ball-9）

H 的 round-3（09:39:11）只调 `review.report`，裁决 `revise_again` 只留在报告与
final 里，`documents.reviewed_at` 停在上一轮 09:27:27 —— 「判词」与「它判的那一版」
在盘上分家。

## 为什么由框架在 H 收尾时写，而不是 `review.report` 里写

`review.report` 的契约是「只写一个报告文件、不碰任何数据表」
（`tests/test_review_report_writes_back_verdict.py`）；它一旦写 `documents`，
`capabilities.assert_capabilities` 的只读例外写集就对不上（那条登记在禁改区）。
所以这里测的是框架侧的回写：H 的工具面仍然没有写工具。

## 反真空

1. 报告钉的版本与现行版不同 ⇒ 不写（判词不盖到新版上）；
2. 这一行已经有 `review_verdict`（这一趟 `verify_fixes` 刚写过）⇒ 不覆盖；
3. 裁决不是 accepted/rejected（`unverified`）⇒ 不写。
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

from agentflow import claimanatomy as CA
from agentflow.agent_loop import AgentLoop
from agentflow.store import Store
from test_agent_h import clean_claim, seed_document


class _Loop:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.role = "H"


class _Run:
    def __init__(self, steps) -> None:
        self.steps = list(steps)


def _step(*, doc_id: str, verdict: str, revision_hash: str, ok: bool = True):
    return SimpleNamespace(
        shape="tool",
        payload={"name": "review.report", "args": {"doc_id": doc_id}},
        result={"tool": "review.report", "ok": ok,
                "data": {"doc_id": doc_id, "verdict": verdict,
                         "revision_hash": revision_hash}},
    )


def _doc(store: Store, doc_id: str = "0000") -> dict:
    return next(dict(r) for r in store.rows("documents")
                if str(r.get("doc_id")) == doc_id)


def _stamp(store: Store, run) -> str:
    return AgentLoop._stamp_h_review_axis(_Loop(store), run)


def test_a_rejected_report_stamps_the_review_axis(tmp_path: pathlib.Path):
    """改前：`review.report` 落盘，documents 行一个字节不变。"""
    store = Store(tmp_path / "ws")
    store.init()
    seed_document(store, "0000", [clean_claim()])
    row = _doc(store)
    assert row["review_verdict"] == "", row

    note = _stamp(store, _Run([_step(doc_id="0000", verdict="rejected",
                                     revision_hash=CA.revision_hash(row))]))

    row = _doc(store)
    assert row["review_verdict"] == "有毛病", row
    assert row["reviewed_by"] == "agent-H" and row["reviewed_at"], row
    assert "已回写" in note, note


def test_an_accepted_report_stamps_成立(tmp_path: pathlib.Path):
    store = Store(tmp_path / "ws")
    store.init()
    seed_document(store, "0000", [clean_claim()])
    row = _doc(store)
    _stamp(store, _Run([_step(doc_id="0000", verdict="accepted",
                              revision_hash=CA.revision_hash(row))]))
    assert _doc(store)["review_verdict"] == "成立", _doc(store)


def test_a_report_for_a_newer_revision_is_not_written(tmp_path: pathlib.Path):
    """反真空：报告钉的是旧版（盘上又改过）⇒ 判词不许盖到新版上。"""
    store = Store(tmp_path / "ws")
    store.init()
    seed_document(store, "0000", [clean_claim()])
    row = _doc(store)
    note = _stamp(store, _Run([_step(doc_id="0000", verdict="rejected",
                                     revision_hash="0" * 16)]))
    assert _doc(store)["review_verdict"] == "", _doc(store)
    assert "只挂读到的那一版" in note, note


def test_an_existing_verdict_is_not_overwritten(tmp_path: pathlib.Path):
    """反真空：这一趟 `verify_fixes` 已经写过审核轴 ⇒ 不覆盖。"""
    store = Store(tmp_path / "ws")
    store.init()
    seed_document(store, "0000", [clean_claim()])
    with store.tx("documents", actor="agent-H") as tx:
        row = tx.find("documents", doc_id="0000")
        row["review_verdict"] = "有毛病"
        row["reviewed_at"] = "2026-11-19T09:27:27+08:00"
        row["reviewed_by"] = "agent-H"
        tx.upsert("documents", row)
    current = _doc(store)
    _stamp(store, _Run([_step(doc_id="0000", verdict="accepted",
                              revision_hash=CA.revision_hash(current))]))
    row = _doc(store)
    assert row["review_verdict"] == "有毛病", row
    assert row["reviewed_at"] == "2026-11-19T09:27:27+08:00", row


def test_an_unverified_report_does_not_stamp(tmp_path: pathlib.Path):
    store = Store(tmp_path / "ws")
    store.init()
    seed_document(store, "0000", [clean_claim()])
    row = _doc(store)
    _stamp(store, _Run([_step(doc_id="0000", verdict="unverified",
                              revision_hash=CA.revision_hash(row))]))
    assert _doc(store)["review_verdict"] == "", _doc(store)
