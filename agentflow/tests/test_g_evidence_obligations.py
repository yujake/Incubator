"""G 的两条"无机械闸"义务：反向引用 / 一证据两用（2026-10-21）。

`specs/g.py` 的 policy[7] 与 policy[9] 此前只有提示词、没有任何判据。本文件钉住补上的两条判据本体
（`verifications.opposite_direction_evidence` / `verifications.one_evidence_used_twice`）与它们在审计面
（`verify._check_7`）上的接线。每条都配四件套：① 正控：刻意造出违规 ⇒ 报，且点名（稿件行 id + 证据
行 id / 断言 id）；② 反真空：合规形态 ⇒ 不报（判据不许"永远报一条"）；③ 负控：把判据本体换成恒
`None` / 恒 `[]` ⇒ 正控必须消失；④ 边界：一证据两用的作用域只在一份稿件内（跨稿件复用是正常的）。

两条义务的机械可判性（诊断结论，判据的界写在判据本体里）：反向引用可判的那一半是
`experiments.result="refutes"` 被一条没有登记成 `is_negative=True` + `negation_kind="disproved"` 的
断言当支撑引用 —— 两个字段都在 schema 里；另一半（否定型断言引 `result="supports"`）判不了：
`supports` 是相对实验行自己的 `claim` 说的，一条否定命题完全可能被一条 supports 实验支持。一证据
两用可判：身份 = 同一条实验行，或同脚本（`code_hash`）+ 同 `observations.data`（这正是 `agent_e`
写入期 `[同一份证据]` note 用的口径，两边读同一个 `evidence_identity`）；同一份稿件里 ≥ 2 条不同
`claim_id` 引用同一身份 ⇒ warning（正当复用存在，硬拦会红掉合规稿件）。"""

from __future__ import annotations

from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import verify as VY
from agentflow.store import Store
from agentflow.tools import doc_tools as DT
from agentflow.verify import verify_all

from conftest import sync_counters

TS = "2026-01-01T00:00:00+00:00"

#: 六位编号（宽度只从 `schema.ID_DIGITS` 取，不写死字面量）。
EID1 = S.format_id(1)
EID2 = S.format_id(2)
DID = S.format_id(0)
DID2 = S.format_id(3)


# ============================================================ 夹具


def _put_experiment(
    store: Store,
    eid: str,
    *,
    result: str = "supports",
    code_hash: str = "",
    data: dict | None = None,
    claim_key: str = "",
) -> dict:
    """落一条合法实验行（`result` 的三种取值都能造）。"""
    kw: dict = {
        "experiment_id": eid,
        "claim": "被检验的命题",
        "claim_key": claim_key or f"claim-key-{eid}",
        "method": "numeric",
        "evidence_kind": "cross_check",
        "result": result,
        "code_path": "code/exp.py",
        "code_hash": code_hash or f"hash-{eid}",
        "exit_code": 0,
        "created_at": TS,
        "observations": ({"data": dict(data)} if data else {}),
    }
    if result == "refutes":
        # `schema.Experiment.validate` 的两条硬条件：证否必须可复核、必须与否定型一致。
        kw["negation_kind"] = "disproved"
        kw["counterexample"] = {"detail": "n=3 处的反例"}
    else:
        kw["negation_kind"] = "not_proved"
    row = S.Experiment(**kw)
    row.validate()
    with store.tx("experiments", actor="test", note="fixture") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _claim(cid: str, cites: list[str], *, negative: bool = False,
           negation_kind: str = "disproved") -> dict:
    """一条合法的正文断言（`cross_check` 自带 disclaimer）。"""
    claim = {
        "claim_id": cid,
        "text": f"断言 {cid} 的正文。",
        "citations": list(cites),
        "evidence_kind": "cross_check",
        "section": "§1",
        "disclaimer": DT.CROSS_CHECK_DISCLAIMER,
    }
    if negative:
        claim["is_negative"] = True
        claim["negation_kind"] = negation_kind
    return claim


def _put_doc(store: Store, claims: list[dict], *, doc_id: str = DID) -> dict:
    """落一份合法稿件（走 `Document.validate`，不手搓字段）。"""
    row = S.Document(doc_id=doc_id, kind="note", title="稿件", claims=claims,
                     status="draft", created_at=TS)
    row.validate()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _hits(report, code: str):
    return [i for i in report.issues if i.code == code]


# ============================================================ 一、反向引用


def test_a_claim_may_not_cite_an_experiment_that_refutes_it(clean_store: Store):
    """① 正向断言引一条 `result="refutes"` 的实验 ⇒ error，且点名稿件行 + 证据行 + 断言。"""
    exp = _put_experiment(clean_store, EID1, result="refutes")
    claim = _claim("c1", [f"exp:{EID1}"])
    _put_doc(clean_store, [claim])

    rep = verify_all(clean_store)
    hits = _hits(rep, VY.OPPOSITE_DIRECTION_EVIDENCE_CODE)
    assert len(hits) == 1, [i.to_dict() for i in rep.issues]
    issue = hits[0]
    assert issue.level == "error", issue.to_dict()
    assert issue.table == "documents"
    assert issue.row_id == DID, issue.to_dict()
    assert "c1" in issue.message and f"exp:{EID1}" in issue.message, issue.message
    assert rep.ok is False

    # 判据本体单独可调：返回的是"判定"，不是报文字符串（写入期与审计期共用）。
    hit = VR.opposite_direction_evidence(claim, exp)
    assert hit is not None and hit["experiment_id"] == EID1
    assert hit["result"] == "refutes"


def test_direction_matching_citations_are_not_flagged(clean_store: Store):
    """② 反真空：方向一致的引用 ⇒ 不报（supports↔正面断言 / refutes↔已证否断言）。"""
    exp_ok = _put_experiment(clean_store, EID1, result="supports")
    exp_ref = _put_experiment(clean_store, EID2, result="refutes")
    positive = _claim("c1", [f"exp:{EID1}"])
    disproved = _claim("c2", [f"exp:{EID2}"], negative=True,
                       negation_kind="disproved")
    _put_doc(clean_store, [positive, disproved])

    rep = verify_all(clean_store)
    assert _hits(rep, VY.OPPOSITE_DIRECTION_EVIDENCE_CODE) == [], \
        [i.to_dict() for i in rep.issues]
    assert VR.opposite_direction_evidence(positive, exp_ok) is None
    assert VR.opposite_direction_evidence(disproved, exp_ref) is None


def test_removing_the_direction_rule_makes_the_criterion_red(
        clean_store: Store, monkeypatch):
    """③ 负控：把判据本体换成恒 `None` ⇒ ① 必须消失（证明 ① 不是碰巧读到了别处）。"""
    _put_experiment(clean_store, EID1, result="refutes")
    _put_doc(clean_store, [_claim("c1", [f"exp:{EID1}"])])
    assert len(_hits(verify_all(clean_store), VY.OPPOSITE_DIRECTION_EVIDENCE_CODE)) == 1

    monkeypatch.setattr(VR, "opposite_direction_evidence", lambda *a, **k: None)
    assert _hits(verify_all(clean_store), VY.OPPOSITE_DIRECTION_EVIDENCE_CODE) == [], (
        "把判据本体摘掉之后还报得出来 ⇒ ① 不是这条判据给的（那条断言是真空的）")


# ============================================================ 二、一证据两用


def test_the_same_experiment_cannot_support_two_claims(clean_store: Store):
    """④ 同一 `experiment_id` 支持两条不同断言 ⇒ warning，且点名三条 id。"""
    _put_experiment(clean_store, EID1, result="supports")
    _put_doc(clean_store, [
        _claim("c1", [f"exp:{EID1}"]),
        _claim("c2", [f"exp:{EID1}"]),
    ])

    rep = verify_all(clean_store)
    hits = _hits(rep, VY.ONE_EVIDENCE_USED_TWICE_CODE)
    assert len(hits) == 1, [i.to_dict() for i in rep.issues]
    issue = hits[0]
    # 为什么是 warning 不是 error：同一份证据被两条断言引用可以是正当的
    # （定理+推论、复现），硬拦会红掉合规稿件；它必须是看得见的读数。
    assert issue.level == "warning", issue.to_dict()
    assert issue.row_id == DID, issue.to_dict()
    for needle in ("c1", "c2", f"exp:{EID1}"):
        assert needle in issue.message, (needle, issue.message)

    direct = VR.one_evidence_used_twice(clean_store.rows("documents"),
                                        clean_store.rows("experiments"))
    assert len(direct) == 1, direct
    assert direct[0]["claim_ids"] == ["c1", "c2"], direct
    assert direct[0]["experiment_ids"] == [EID1], direct


def test_two_claims_with_different_evidence_are_not_flagged(clean_store: Store):
    """反真空：两条断言各引各的证据 ⇒ 不报；跨稿件复用同一条证据也不报。"""
    _put_experiment(clean_store, EID1, result="supports")
    _put_experiment(clean_store, EID2, result="supports")
    _put_doc(clean_store, [
        _claim("c1", [f"exp:{EID1}"]),
        _claim("c2", [f"exp:{EID2}"]),
    ])
    _put_doc(clean_store, [_claim("c3", [f"exp:{EID1}"])], doc_id=DID2)

    rep = verify_all(clean_store)
    assert _hits(rep, VY.ONE_EVIDENCE_USED_TWICE_CODE) == [], \
        [i.to_dict() for i in rep.issues]
    assert VR.one_evidence_used_twice(clean_store.rows("documents"),
                                      clean_store.rows("experiments")) == []


def test_two_runs_of_the_same_script_and_data_are_one_evidence(clean_store: Store):
    """D39 的真机形态：两次运行、两个 `exp:`、同脚本 + 同 `data` ⇒ 仍是同一份证据。

    真机读数（T2 第 9 趟 `p6k`）：一个脚本被派了 9 次、每次打印逐字相同的 `data`，
    台账上 9 条 `supports`，手稿当 9 份独立证据引。按 `experiment_id` 判重看不见它
    —— 所以身份必须是 `code_hash` + `observations.data`（与 E 的 `[同一份证据]`
    note 同一处定义）。
    """
    same = {"n_vertices": 30, "degrees": [3], "girth": 8}
    _put_experiment(clean_store, EID1, result="supports",
                    code_hash="deadbeefdeadbeef", data=same, claim_key="W(2)")
    _put_experiment(clean_store, EID2, result="supports",
                    code_hash="deadbeefdeadbeef", data=same, claim_key="W(3)")
    _put_doc(clean_store, [
        _claim("c1", [f"exp:{EID1}"]),
        _claim("c2", [f"exp:{EID2}"]),
    ])

    assert VR.evidence_identity(clean_store.rows("experiments")[0]) == \
        VR.evidence_identity(clean_store.rows("experiments")[1])

    rep = verify_all(clean_store)
    hits = _hits(rep, VY.ONE_EVIDENCE_USED_TWICE_CODE)
    assert len(hits) == 1, [i.to_dict() for i in rep.issues]
    for needle in ("c1", "c2", f"exp:{EID1}", f"exp:{EID2}"):
        assert needle in hits[0].message, (needle, hits[0].message)


def test_removing_the_reuse_rule_makes_the_criterion_red(
        clean_store: Store, monkeypatch):
    """④ 的负控：把判据本体换成恒 `[]` ⇒ ④ 必须消失。"""
    _put_experiment(clean_store, EID1, result="supports")
    _put_doc(clean_store, [
        _claim("c1", [f"exp:{EID1}"]),
        _claim("c2", [f"exp:{EID1}"]),
    ])
    assert len(_hits(verify_all(clean_store), VY.ONE_EVIDENCE_USED_TWICE_CODE)) == 1

    monkeypatch.setattr(VR, "one_evidence_used_twice", lambda *a, **k: [])
    assert _hits(verify_all(clean_store), VY.ONE_EVIDENCE_USED_TWICE_CODE) == [], (
        "把判据本体摘掉之后还报得出来 ⇒ ④ 不是这条判据给的（那条断言是真空的）")
