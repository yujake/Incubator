# -*- coding: utf-8 -*-
"""甲（2026-11-11 业主裁定）：轮次账要跟着「复审」走。

真机读数（`projects/dct-min6-20261111`，只读）：`documents.review_rounds` 恒 2，
而 H 事实上复审过很多趟、findings 摊出 12 个"轮次"。根因是两套轮次互不相认：

* 只有 `G.revise` 会 +1，而真机上 G 常用 `fs.edit` 改稿（不经过 `revise`）；
* `review_document` / `verify_fixes` 一次都不涨；
* `record_finding` 自己 `max(round)+1` 造轮次 —— 于是 24 条发现摊出 1..12。

本文件钉的口径（判决逐条对应施工单 a–d）：

| 判据 | 现场 | 期望 |
|---|---|---|
| a | G 改一次 + H 复审一次 | `review_rounds == 2`，这一轮的 finding `round == 2` |
| b | H 复审两次（G 各改一次） | `review_rounds == 3`，这一轮记的 finding `round == 3` |
| c | 只复审不改稿（有 open findings） | 每复审一次仍 +1；不许因此把 status 写成 accepted |
| d | 反真空：把 "+1" 摘掉 | a 必须变回"改前的读数"（1） |

"轮次只从 `documents.review_rounds` 来"这件事在 b 里同时钉 findings 那一侧：
不传 `round_no` 的 `record_finding` 盖的是当前复审轮次，不是 `max(round)+1`。
"""
from __future__ import annotations

import json

import pytest

from conftest import TS, add_literature, sync_counters, write_paper

from agentflow import schema as S
import agentflow.tools.review_tools as RV
from agentflow.agent_g import AgentG
from agentflow.store import Store

DOC = "000000"


def _claim() -> dict:
    return {
        "claim_id": "claim-1", "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "heuristic", "citations": ["lit:0000"],
        "is_negative": False, "negation_kind": None, "disclaimer": "",
    }


def _document_row(*, review_rounds: int = 0, claims: list[dict] | None = None) -> dict:
    row = S.Document(
        doc_id=DOC, kind="paper", title="轮次探针稿", markdown_path=None,
        claims=list(claims if claims is not None else [_claim()]),
        status="in_review", review_rounds=review_rounds,
        created_at=TS, updated_at=TS,
    ).to_dict()
    from agentflow import signatures as SIG
    row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def _seed(store: Store) -> None:
    """一份有正文、`review_rounds=0` 的稿件（0 = 还没进过任何一轮）。"""
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n最小正文。\n\\end{document}\n")
    add_literature(store, "0000", title="探针文献", processed=True)
    with store.tx("documents", actor="fixture") as tx:
        tx.upsert("documents", _document_row())
    sync_counters(store)


def _doc(store: Store) -> dict:
    return next(dict(r) for r in store.rows("documents"))


def _rounds(store: Store) -> int:
    return int(_doc(store).get("review_rounds") or 0)


def _finding(store: Store, finding_id: str) -> dict:
    return next(dict(r) for r in store.rows("review_findings")
                if str(r.get("finding_id")) == str(finding_id))


# ============================================================ a：G 改一次 + H 复审一次 ⇒ 2

def test_a_one_revision_then_one_review_makes_two_rounds(store: Store) -> None:
    """G 改一次（它只把轮次托到 1）+ H 复审一次 ⇒ 轮次 = 2。"""
    _seed(store)
    g = AgentG(store, config={"docs_subdir": "documents"})
    g.revise(DOC, note="按 H 的意见改")
    assert _rounds(store) == 1, "改一次之后的读数（真机上这里恒为 2；现在它是 1）"

    res = RV.review_document(store, DOC, dependencies=[])
    assert res["checked"] is True, res
    assert res["round"] == 2, res
    assert _rounds(store) == 2, "复审一次必须让 documents.review_rounds = 2"

    # 同一轮取证：这一轮记的判词 round 必须等于当时的 review_rounds。
    got = RV.record_finding(
        store, doc_id=DOC, kind="overclaim", target="claim-1",
        message="这一句把交叉验证说成了证明",
        evidence="正文第 3 行逐字：'we have proved it'",
    )
    assert got["round"] == 2, got
    assert _finding(store, got["finding_id"])["round"] == 2


# ============================================================ b：H 复审两次（G 各改一次）⇒ 3

def test_b_two_reviews_with_a_revision_each_make_three_rounds(store: Store) -> None:
    """第二次改稿不再推进轮次；第二次复审把它推到 3，且这一轮的判词 round=3。"""
    _seed(store)
    g = AgentG(store, config={"docs_subdir": "documents"})
    g.revise(DOC, note="第 1 次改")
    first = RV.review_document(store, DOC, dependencies=[])
    assert first["round"] == 2 and _rounds(store) == 2

    g.revise(DOC, note="第 2 次改")
    assert _rounds(store) == 2, "改稿不推进轮次（轮次账跟着复审走）"

    second = RV.review_document(store, DOC, dependencies=[])
    assert second["round"] == 3, second
    assert _rounds(store) == 3

    got = RV.record_finding(
        store, doc_id=DOC, kind="garbled", target="section:2",
        message="这一段的记号与上一节不一致",
        evidence="main.tex:12 的符号与 main.tex:31 的声明不同",
    )
    assert got["round"] == 3, got
    assert _finding(store, got["finding_id"])["round"] == 3


# ============================================================ c：只复审不改稿也 +1，但不许 accepted

def test_c_review_without_revision_still_advances_but_never_accepts(store: Store) -> None:
    """只复审、不改稿：每复审一次 +1；有 open findings 时 status 不许被写成 accepted。"""
    _seed(store)
    # 一条 open 的 error 级判词（第 1 轮记的）—— 它就是"这一版还不许通过"的那一条。
    RV.record_finding(
        store, doc_id=DOC, kind="overclaim", target="claim-1", level="error",
        message="正文声称已证明，但凭据只到交叉验证",
        evidence="正文逐字：'we have proved it'；台账 evidence_kind=cross_check",
    )
    # 未复审之前轮次是 0；判词记在第 1 轮（即将进行的那一轮）。
    assert _rounds(store) == 0

    first = RV.review_document(store, DOC, dependencies=[])
    assert _rounds(store) == 1, "只复审不改稿也必须 +1（复审本身就推进轮次）"
    assert first["status"] != "accepted", first
    assert _doc(store)["status"] != "accepted"

    second = RV.review_document(store, DOC, dependencies=[])
    assert _rounds(store) == 2, "复审第二次再 +1"
    assert second["status"] != "accepted", second
    assert str(_doc(store).get("review_verdict") or "") == "", _doc(store)


# ============================================================ d：反真空（摘掉 +1 ⇒ a 红）

def test_d_removing_the_plus_one_turns_a_red(store: Store, monkeypatch) -> None:
    """反真空：把轮次推进摘掉 ⇒ a 的读数退回"改前"（1）。

    这条不是在测一个理想行为，而是在测 a 的那条断言真的靠这段实现活着：
    若将来有人把 `_advance_review_round` 改成"什么都不做"，这里会看到 1 而不是 2。
    """
    _seed(store)
    g = AgentG(store, config={"docs_subdir": "documents"})
    g.revise(DOC, note="按 H 的意见改")

    def _no_advance(store, doc_id, *, explicit=None, actor="agent-H"):
        # 打桩：只算读数、不写盘、也不 +1（"把 +1 摘掉"的等价形态）。
        cur = int(_doc(store).get("review_rounds") or 0)
        return (max(cur, int(explicit)) if explicit is not None else cur), None

    monkeypatch.setattr(RV, "_advance_review_round", _no_advance)
    res = RV.review_document(store, DOC, dependencies=[])
    assert res["round"] == 1, res
    assert _rounds(store) == 1, "摘掉 +1 之后复审不再推进轮次 —— a 的 == 2 因此会红"
