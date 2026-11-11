# -*- coding: utf-8 -*-
"""乙（2026-11-11 业主裁定）：同一处的旧判词要被新判覆盖（`superseded`）。

真机读数（`projects/dct-min6-20261111`，只读）：findings 跨轮累积，同一处的旧条不会被
覆盖 —— 24 条里有多条是同一处的不同表述，`open` 数只增不减（在 2–11 之间摆动）。
业主裁定：同一 `(kind, target)` 在更晚的轮次又记了一条 ⇒ 更早那条推成
`superseded`，并用 `superseded_by` 指到新那条。

本文件钉的判据（施工单 e–h）：

| 判据 | 现场 | 期望 |
|---|---|---|
| e | 同一 (kind,target) 记两次（r1、r3） | open=1（新那条）；r1 那条 superseded 且 superseded_by 指得到 r3 |
| f | target 不同 | 两条都 open（不许误覆盖） |
| g | 已 fixed 的条 + 后来的同处新判 | 旧条仍 fixed（不改成 superseded） |
| h | 反真空：把覆盖摘掉 | e 变回 open=2（红） |

语义边界：只在 kind 与 target 逐字完全相同时覆盖；`fixed`/`wontfix`（以及
`disputed`）是已了结的判词，不被覆盖；覆盖不是删除 —— 原文、轮次、证据都留着。
`open` 的判定仍只看 `status == "open"` ⇒ 覆盖之后 open 数下降。
"""
from __future__ import annotations

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


def _seed(store: Store, *, status: str = "in_review") -> None:
    write_paper(store, "\\documentclass{article}\n\\begin{document}\n最小正文。\n\\end{document}\n")
    add_literature(store, "0000", title="探针文献", processed=True)
    row = S.Document(
        doc_id=DOC, kind="paper", title="覆盖探针稿", markdown_path=None,
        claims=[_claim()], status=status, review_rounds=1,
        created_at=TS, updated_at=TS,
    ).to_dict()
    from agentflow import signatures as SIG
    row["content_sha256"] = SIG.content_sha256_of(row)
    with store.tx("documents", actor="fixture") as tx:
        tx.upsert("documents", row)
    sync_counters(store)


def _record(store: Store, *, target: str, message: str, round_no: int,
            level: str = "warning") -> dict:
    return RV.record_finding(
        store, doc_id=DOC, kind="overclaim", target=target, message=message,
        evidence=f"正文逐字：'{message}'（夹具）", level=level, round_no=round_no,
    )


def _rows(store: Store) -> dict[str, dict]:
    return {str(r["finding_id"]): dict(r) for r in store.rows("review_findings")}


def _open_count(store: Store) -> int:
    return sum(1 for r in store.rows("review_findings")
               if str(r.get("status")) == "open")


# ============================================================ e：同处 r1 → r3 ⇒ open=1

def test_e_a_later_judgement_supersedes_the_earlier_one(store: Store) -> None:
    _seed(store)
    old = _record(store, target="claim-1", message="旧表述：这一处说得太满", round_no=1)
    assert _open_count(store) == 1

    new = _record(store, target="claim-1", message="第 3 轮重判：同一处仍然太满", round_no=3)
    rows = _rows(store)
    assert rows[old["finding_id"]]["status"] == "superseded", rows[old["finding_id"]]
    assert rows[old["finding_id"]]["superseded_by"] == new["finding_id"]
    assert rows[new["finding_id"]]["status"] == "open"
    assert _open_count(store) == 1, "覆盖之后 open 数必须下降（e）"
    # 不是删除：原文、轮次、证据都留着（可追溯）
    assert rows[old["finding_id"]]["round"] == 1
    assert rows[old["finding_id"]]["message"] == "旧表述：这一处说得太满"
    assert rows[old["finding_id"]]["evidence"]
    # 读数面上指得到覆盖它的那一条
    listed = RV.list_findings(store, doc_id=DOC)["findings"]
    picked = next(f for f in listed if f["finding_id"] == old["finding_id"])
    assert picked["superseded_by"] == new["finding_id"], picked
    # 新判词自己的 superseded_by 是空（它没有被覆盖）
    assert rows[new["finding_id"]]["superseded_by"] == ""


# ============================================================ f：target 不同 ⇒ 两条都 open

def test_f_a_different_target_is_not_the_same_place(store: Store) -> None:
    _seed(store)
    a = _record(store, target="claim-1", message="这一处太满", round_no=1)
    b = _record(store, target="claim-2", message="那一处也太满", round_no=3)
    rows = _rows(store)
    assert rows[a["finding_id"]]["status"] == "open"
    assert rows[b["finding_id"]]["status"] == "open"
    assert rows[a["finding_id"]]["superseded_by"] == ""
    assert _open_count(store) == 2, "target 差一个字都不算同一处（f）"


# ============================================================ g：fixed 不被覆盖

def test_g_a_settled_finding_is_not_superseded(store: Store) -> None:
    _seed(store)
    old = _record(store, target="claim-1", message="已修好的那一条", round_no=1,
                  level="error")
    # G 用真写口把它标成 fixed（只改 status/resolution_note，内容一个字不改）
    AgentG(store, config={"docs_subdir": "documents"}).revise(
        DOC, fixed_findings=[old["finding_id"]], note="已按意见改")
    assert _rows(store)[old["finding_id"]]["status"] == "fixed"

    new = _record(store, target="claim-1", message="后来同一处的新判词", round_no=3)
    rows = _rows(store)
    assert rows[old["finding_id"]]["status"] == "fixed", "已了结的不动（g）"
    assert rows[old["finding_id"]]["superseded_by"] == ""
    assert rows[new["finding_id"]]["status"] == "open"
    assert _open_count(store) == 1


# ============================================================ h：反真空（摘掉覆盖 ⇒ e 红）

def test_h_removing_the_supersede_turns_e_red(store: Store, monkeypatch) -> None:
    """反真空：把覆盖摘掉 ⇒ 同一处两条都还是 open（e 的 open=1 因此会红）。"""
    _seed(store)
    monkeypatch.setattr(RV, "_supersede_prior_open",
                        lambda *a, **k: [])
    old = _record(store, target="claim-1", message="旧表述：这一处说得太满", round_no=1)
    new = _record(store, target="claim-1", message="第 3 轮重判：同一处仍然太满", round_no=3)
    rows = _rows(store)
    assert rows[old["finding_id"]]["status"] == "open"
    assert rows[new["finding_id"]]["status"] == "open"
    assert _open_count(store) == 2, "摘掉覆盖之后 open=2 —— e 的 == 1 因此会红"


# ============================================================ 机械扫描那条路也覆盖

def _fake_scan(findings: list[dict]) -> dict:
    """只喂 `review_document` 真正读的那几格（扫描器本体不在本用例的靶子上）。"""
    return {
        "findings": findings,
        "error_count": sum(1 for f in findings if f["level"] == "error"),
        "warning_count": sum(1 for f in findings if f["level"] == "warning"),
        "info_count": sum(1 for f in findings if f["level"] == "info"),
        "dep_check": {"checked": True, "reason": "夹具：依赖闭合查过", "open": []},
        "coverage": {"claims_total": 1, "claims_reviewed": 1, "claims_decided": 1,
                     "claims_semantically_judged": 0, "note": "夹具"},
        "semantic_check": {"checked": False, "judge": "", "reason": "夹具：没接线",
                           "claims_judged": 0, "claims_unknown": 0,
                           "checker_errors": 0, "stronger_than_evidence": 0},
    }


def test_the_scan_path_supersedes_too(store: Store, monkeypatch) -> None:
    """`review_document` 落的机械判词走同一条覆盖规则（不只是 `record_finding`）。"""
    _seed(store)

    def _scan_round_one(doc, **__):
        return _fake_scan([{
            "kind": "overclaim", "level": "error", "target": "claim-1",
            "evidence": "第 1 轮：cross_check 且 disclaimer 为空",
            "message": "这一档必须显式声明「数值交叉验证，不构成证明」",
        }])

    monkeypatch.setattr(RV, "scan_document", _scan_round_one)
    first = RV.review_document(store, DOC, dependencies=[])
    old = [f for f in first["new_findings"] if f["kind"] == "overclaim"]
    assert len(old) == 1, first["new_findings"]

    # 第 2 轮：同一处、同一个 kind，但判词换了表述（去重键因此不同）
    def _scan_round_three(doc, **__):
        return _fake_scan([{
            "kind": "overclaim", "level": "error", "target": "claim-1",
            "evidence": "第 3 轮：正文含「已证明」而证据档位是 heuristic",
            "message": "把交叉验证写成了证明",
        }])

    monkeypatch.setattr(RV, "scan_document", _scan_round_three)
    second = RV.review_document(store, DOC, dependencies=[])
    new = [f for f in second["new_findings"] if f["kind"] == "overclaim"]
    assert len(new) == 1, second["new_findings"]

    rows = _rows(store)
    assert rows[old[0]["finding_id"]]["status"] == "superseded"
    assert rows[old[0]["finding_id"]]["superseded_by"] == new[0]["finding_id"]
    listed = {f["finding_id"]: f for f in RV.list_findings(store, doc_id=DOC)["findings"]}
    assert listed[old[0]["finding_id"]]["superseded_by"] == new[0]["finding_id"]


# ============================================================ 老行的"递增轮次"

def test_a_legacy_inflated_round_is_still_superseded(store: Store) -> None:
    """真机拷贝上的形态：老判词 round 是旧 `max+1` 口径（1..12），比新的复审轮次还大。

    老行不可能是"将来某一轮"记的 ⇒ 它仍然比"这一次写入"更早。所以判据写成
    "round 不同 = 更早一次写入；round 相同 = 同一轮并存"，而不是数值 `>=`。
    （`temp/_min6_repro.py` 在 `projects/dct-min6-20261111` 的只读拷贝上量到：
    新复审轮次 3、老判词 round=12，旧条仍被覆盖。）
    """
    _seed(store)
    old = _record(store, target="claim-1", message="旧口径下第 12 轮的那条", round_no=12)
    new = _record(store, target="claim-1", message="统一口径后的复审轮次那一条", round_no=3)
    rows = _rows(store)
    assert rows[old["finding_id"]]["status"] == "superseded"
    assert rows[old["finding_id"]]["superseded_by"] == new["finding_id"]
    assert rows[new["finding_id"]]["status"] == "open"


# ============================================================ schema 三态 + verify 不再报红

def test_old_rows_without_the_new_field_read_as_not_superseded() -> None:
    """老行三态：没有 `superseded_by` 这一格 ⇒ 读成"未覆盖"（空串），不是坏行。"""
    legacy = {
        "finding_id": "000001", "doc_id": "000000", "kind": "overclaim",
        "level": "warning", "target": "claim-1", "evidence": "旧证据",
        "message": "旧行（这一格当年不存在）", "round": 1, "status": "open",
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    row = S.row_from_dict("review_findings", legacy)
    assert row.superseded_by == ""
    row.validate()          # 老行照旧合法（不因缺这一格被 store.rebuild 丢掉）


def test_superseded_requires_a_pointer() -> None:
    """`status='superseded'` 必须指得到"被哪一条覆盖"（指针是这一状态唯一的落点）。"""
    with pytest.raises(ValueError, match="superseded_by"):
        S.ReviewFinding(
            finding_id="000001", doc_id="000000", kind="overclaim", level="error",
            target="claim-1", evidence="证据", message="被覆盖的那一条",
            status="superseded", superseded_by="",
        ).validate()


def test_verify_does_not_call_a_superseded_error_unresolved(store: Store) -> None:
    """覆盖之后 open 数下降，`verify_all` 也不许再把旧 error 读成"未处置"。"""
    from agentflow import verify as V

    _seed(store, status="accepted")
    old = _record(store, target="claim-1", message="旧判词（error）", round_no=1,
                  level="error")
    with store.tx("review_findings", actor="fixture") as tx:
        row = tx.find("review_findings", finding_id=old["finding_id"])
        row["status"] = "superseded"
        row["superseded_by"] = "000999"
        tx.upsert("review_findings", row)

    issues = V.verify_all(store).issues
    assert not [i for i in issues if i.code == "accepted_with_open_error"], [
        i.to_dict() for i in issues if i.code == "accepted_with_open_error"]

    # 负控：把状态退回 open ⇒ 同一条审计必须报红（证明它真的在看这一格）
    with store.tx("review_findings", actor="fixture") as tx:
        row = tx.find("review_findings", finding_id=old["finding_id"])
        row["status"] = "open"
        row["superseded_by"] = ""
        tx.upsert("review_findings", row)
    again = V.verify_all(store).issues
    assert [i for i in again if i.code == "accepted_with_open_error"], (
        "状态退回 open 之后必需报红 —— 否则上面那条断言是真空的")
