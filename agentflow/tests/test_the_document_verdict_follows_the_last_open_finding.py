# -*- coding: utf-8 -*-
"""文档级判词不许落后于最后一条 open finding（R10FIX-D6 / 与 D9 同族）。

## 现场（R10 真机 lp-ball-10，2026-11-19，只读对账 `temp/r10check`）

| 时刻 | 事件 |
|---|---|
| 13:51:31 | H 最后一次 `review.report` → rejected |
| 13:54:11 | round-5 `review.verify_fixes` 落 `review_verdict` / `reviewed_at` |
| 14:03:36 | H 落 finding 000010（`open`，`inconsistent_number` @claim-12） |
| 14:04:06 | H 最后一趟 `t-000189` 收工（0 次 `review.report`） |

于是 `documents.reviewed_at` 比最后一条 open finding 早 9 分 25 秒，收工门读的正是
这个差（「有 open findings 而这一版没有复审记录」）。根因不是"回写坏了"，而是只有
`review.report` 那一条路会回写：H 完全可以最后一趟只补一条手工 finding。

## 判据

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 没有 `review.report`、但落了更晚的 open finding ⇒ 判词时间跟到 finding 那一刻 | 真机那一趟的形状 |
| a-反真空 | 把这一格摘掉（打桩返回空串）⇒ 时间一动不动 | 证明 a 的绿灯压在这一格上 |
| b | 幂等：再调一次不再写（读数空串） | 同一趟收尾只写一次 |
| c | finding 比判词旧 ⇒ 不回填（判词不退） | "最近的判词"不许被旧缺陷拖回去 |

"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import review_tools as RT

DOC = "000000"
BEFORE = "2026-11-19T13:54:11+08:00"
FINDING_AT = "2026-11-19T14:03:36+08:00"


# ---------------------------------------------------------------- 夹具


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _doc(st: Store, *, reviewed_at: str = BEFORE) -> dict:
    row = S.Document(doc_id=DOC, kind="paper", title="手稿", status="in_review",
                     claims=[{"claim_id": "claim-12", "text": "一条断言",
                              "citations": ["lit:000000"], "evidence_kind": "heuristic",
                              "section": "§3"}],
                     review_verdict="有毛病", reviewed_at=reviewed_at,
                     reviewed_by="agent-H", review_rounds=5,
                     created_at="2026-11-19T13:29:36+08:00")
    row.validate()
    with st.tx("documents", actor="agent-H") as tx:
        tx.upsert("documents", row.to_dict())
    return row.to_dict()


def _finding(st: Store, *, at: str) -> dict:
    """真写口落一条手工 finding（`review.record_finding`）。"""
    import agentflow.schema as _S

    real = _S.now_iso
    _S.now_iso = lambda: at                     # type: ignore[assignment]
    try:
        return RT.record_finding(
            st, doc_id=DOC, kind="inconsistent_number", target="claim-12",
            message="§3 的数值与 exp:000002 对不上", evidence="逐条核过：差 0.4",
            level="warning", actor="agent-H")
    finally:
        _S.now_iso = real                       # type: ignore[assignment]


def _loop(st: Store, tmp_path: pathlib.Path) -> AL.AgentLoop:
    return AL.AgentLoop(role="H", session_root=tmp_path / "ws", registry=None,
                        seam=None, store=st)


def _doc_now(st: Store) -> dict:
    return [dict(r) for r in st.rows("documents") if str(r.get("doc_id")) == DOC][0]


# ============================================================ a 正控


def test_a_a_newer_open_finding_moves_the_document_verdict_time(
        tmp_path: pathlib.Path) -> None:
    """a：没有 `review.report` 时，判词时间跟到最后一条 open finding 那一刻。"""
    st = _store(tmp_path)
    _doc(st)
    _finding(st, at=FINDING_AT)
    note = _loop(st, tmp_path)._stamp_h_review_axis(AL.LoopRun(role="H", task=""))
    assert "open finding" in note and DOC in note, note

    row = _doc_now(st)
    assert row["review_verdict"] == "有毛病", row
    assert row["reviewed_at"] == FINDING_AT, row
    assert row["reviewed_by"] == "agent-H", row


def test_a2_without_the_open_finding_rule_the_time_does_not_move(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a-反真空：把「按 open finding 更新」摘掉 ⇒ 同一现场时间一动不动。"""
    monkeypatch.setattr(AL, "_stamp_open_finding_axis", lambda loop: "")
    st = _store(tmp_path)
    _doc(st)
    _finding(st, at=FINDING_AT)
    note = _loop(st, tmp_path)._stamp_h_review_axis(AL.LoopRun(role="H", task=""))
    assert note == "", note
    assert _doc_now(st)["reviewed_at"] == BEFORE, _doc_now(st)


# ============================================================ b 幂等


def test_b_the_stamp_is_idempotent(tmp_path: pathlib.Path) -> None:
    """b：同一趟收尾再调一次 ⇒ 读数空串、时间与判词不动。"""
    st = _store(tmp_path)
    _doc(st)
    _finding(st, at=FINDING_AT)
    loop = _loop(st, tmp_path)
    first = loop._stamp_h_review_axis(AL.LoopRun(role="H", task=""))
    assert first, first
    again = loop._stamp_h_review_axis(AL.LoopRun(role="H", task=""))
    assert again == "", again
    assert _doc_now(st)["reviewed_at"] == FINDING_AT, _doc_now(st)


# ============================================================ c 不回填


def test_c_a_finding_older_than_the_verdict_does_not_drag_it_back(
        tmp_path: pathlib.Path) -> None:
    """c：finding 比判词旧 ⇒ 不回填（"最近的判词"不许被旧缺陷拖回去）。"""
    st = _store(tmp_path)
    _doc(st, reviewed_at="2026-11-19T14:10:00+08:00")
    _finding(st, at=FINDING_AT)                 # 14:03:36 < 14:10:00
    note = _loop(st, tmp_path)._stamp_h_review_axis(AL.LoopRun(role="H", task=""))
    assert note == "", note
    assert _doc_now(st)["reviewed_at"] == "2026-11-19T14:10:00+08:00", _doc_now(st)
