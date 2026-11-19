# -*- coding: utf-8 -*-
"""`load_bearing` 的「现行版有 V 签」要认得住"先签后收录"那一签（R10FIX-D4）。

## 现场（R10 真机 lp-ball-10，2026-11-19，只读对账 `temp/r10check`）

最后一次收工的 `readings.load_bearing` 是 `claims=[]`、`claims_with_proof=0`、
`prose_reviewed_ids=[]`、`v_sign_backed_claims=0`，而同一份读数里 `verification_rows=13`
—— 也就是说这一格"什么都没看见"，然后以 `state=not_applicable` pass。

两条原因分开：

1. `_statement_reviewed` 读的是在册台账那一路（`statement_review_reading` →
   `review_standing` → `verifications/<命题号>.jsonl`）。而"先签后收录"是主路：V 在
   命题还没在册时审、B 收录时才拿到号 ⇒ 那一签住在
   `verifications/pending/<载体 sha>.jsonl`，在册台账里根本没有这一行 ⇒ 这一格对
   000013 / 000017（`proof_review_gap` 都是 `claimed=True, streak=3/3, ok=True`）
   都回 False。于是 Lean 关时的替代口径（"引用的命题现行版有 V 签"）在这条主路上
   从来没生效过。
2. 手稿写的是 `proof_review`（pre_theorem），而承重集合按 §10.2 ① 只认
   `theorem` 档 —— 这不是口径错（Lean 关时 `claimanatomy` 的用词上限就是
   `proof_review`，写 `proof` 才是超过证据），但"零承重"与"稿里一条带证据的结论都
   没有"在读数上长得一样。所以 `claims_below_theorem` 把那一档列出来。

## 判据

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 已认领的 pending 3/3 签 ⇒ `_statement_reviewed=True`、`prose_reviewed_ids` 非空、断言 `backed_by=v_sign` | 先签后收录的主路 |
| a-反真空 | 把 pending 回退打桩掉 ⇒ 旧读口回到 False（FIX186-D1 之后两把尺同一个答案） | 证明 a 的绿来自那一签本身 |
| b | 未认领的 pending 签不算（`proof` 断言仍 fail） | 旧射程：pending 只够过准入闸 |
| c | `proof_review` 断言不算承重，但进 `claims_below_theorem`（读数，不改判定） | 真机手稿 claim-4 |

"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow import schema as S
from agentflow import settings as SET
from agentflow import sign_counting as SC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.tools.doc_tools import PROOF_REVIEW_DISCLAIMER

from conftest import seed_statement_row
from test_the_first_sign_before_registration_still_lifts_the_kind import (
    FULL, LABEL, PROOF, _b, _manuscript, _pending_rows, _put, _row, _store,
)

CARRIER = "a" * 64
REL = "reports/f-proof-000007.md"
CLEAN = {"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具"}


# ---------------------------------------------------------------- 夹具


def _signed_rows(st: object, *, issue: bool = True) -> list[dict]:
    rows = [VR.record_pending_sign(
        str(getattr(st, "root")), proof_text=PROOF, object_sha256=CARRIER,
        object_path=REL, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", secretary_judge=CLEAN,
        review_call="c1", review_pass=i, at=f"2026-11-19T13:42:1{i}+08:00")
        for i in (1, 2, 3)]
    if issue:
        VS.issue(str(getattr(st, "root")), artifact_sha=rows[0]["proof_sha256"],
                 artifact_path=REL, streak=3, need=3,
                 ledger=f"verifications/pending/{CARRIER}.jsonl#u-000003",
                 proof_no=1, passes=[SC.ticket(r) for r in rows],
                 at="2026-11-19T13:42:16+08:00", by="secretary:F")
    return rows


def _register(st: object, rel: str) -> str:
    filed = _b(st).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", derived_from=["999999"], kind="conjecture",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=rel)
    assert filed.get("ok") is True, filed
    return str(filed.get("stmt_id") or "")


def _claim_doc(st: object, *, sid: str, evidence_kind: str) -> dict:
    claim = {"claim_id": "c1", "text": "已获 V 签「成立」的结果",
             "citations": [f"stmt:{sid}"], "evidence_kind": evidence_kind,
             "section": "§2"}
    if evidence_kind == "proof_review":
        claim["disclaimer"] = PROOF_REVIEW_DISCLAIMER
    row = S.Document(doc_id="0001", kind="paper", title="未发表的论文",
                     status="in_review", claims=[claim],
                     created_at="2026-01-01T00:00:00+08:00")
    row.validate()
    with getattr(st, "tx")("documents", actor="test") as tx:
        tx.upsert("documents", row.to_dict())
    return row.to_dict()


def _load_bearing(st: object) -> dict:
    rep = CL.check_closing(st, project_dir=str(getattr(st, "root")), report_path="")
    return {"rep": rep, **dict(rep.readings.get("load_bearing") or {})}


# ============================================================ a 正控


def test_a_the_claimed_pending_sign_counts_as_the_current_v_sign(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：已认领的 pending 3/3 签 ⇒ 承重门的替代口径真的生效。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    _signed_rows(st)
    sid = _register(st, rel)
    row = _row(st, sid)
    assert row["kind"] == "theorem", row
    assert CL._statement_reviewed(st.root, row) is True

    _claim_doc(st, sid=sid, evidence_kind="proof")
    got = _load_bearing(st)
    claims = list(got.get("claims") or [])
    assert claims and claims[0]["backed_by"] == "v_sign", got
    assert claims[0]["v_signed"] == [sid], claims
    assert got.get("v_sign_backed_claims") == 1, got
    assert sid in list(got.get("prose_reviewed_ids") or []), got
    assert got["rep"].status["load_bearing"] == "pass", got["rep"].status


def test_a2_the_old_reader_is_still_false_on_the_same_workspace(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a-反真空（FIX186-D1 之后）：旧读口也有 pending 回退，所以要打桩它才回 False。

    改前 `statement_review_reading` 只读在册台账 ⇒ 同一现场回 False（那一笔"换读口"
    的理由）。D1 把 pending 回退补进 `review_standing` 之后，两把尺对同一件事给同一个
    答案；这一条把回退打桩掉 ⇒ 旧读口回到 `unsigned` —— 证明它的 `True` 确实来自
    "先签后收录"那一叠，而不是来自它本来就不看台账。
    """
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    _signed_rows(st)
    sid = _register(st, rel)
    row = _row(st, sid)
    assert VR.proof_review_gap(st.root, row).get("ok") is True, VR.proof_review_gap(st.root, row)
    assert VR.statement_review_reading(st.root, row).get("reviewed") is True, (
        "D1 之后旧读口必须与 proof_review_gap 同一个答案")
    monkeypatch.setattr(VR, "_pending_standing_rows",
                        lambda *a, **k: None)  # noqa: ARG005 —— 打桩签名与实现同形
    assert VR.statement_review_reading(st.root, row).get("reviewed") is False, (
        "打桩掉 pending 回退之后旧读口仍回 True ⇒ 它看的不是那一叠签")


# ============================================================ b 未认领不算


def test_b_an_unclaimed_pending_sign_still_does_not_back_the_claim(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：未认领的 pending 签不算凭据（旧射程不变：`proof` 断言仍 fail）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _store(tmp_path)
    seeded = seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text=LABEL,
        kind="conjecture", label=LABEL, origin="own_result",
        evidence_kind="heuristic", manuscript_id="000007")
    sid = str(seeded["stmt_id"])
    _signed_rows(st, issue=False)
    assert all(not str(r.get("statement_id") or "") for r in _pending_rows(st)), _pending_rows(st)
    row = _row(st, sid)
    assert CL._statement_reviewed(st.root, row) is False

    _claim_doc(st, sid=sid, evidence_kind="proof")
    got = _load_bearing(st)
    assert got["rep"].status["load_bearing"] == "fail", got["rep"].to_dict()
    assert [c["backed_by"] for c in got.get("claims") or []] == [""], got.get("claims")


# ============================================================ c 门槛以下那一档


def test_c_a_proof_review_claim_is_below_the_theorem_threshold_but_visible(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：`proof_review` 断言不算承重，但进 `claims_below_theorem`（不是真空）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    _signed_rows(st)
    sid = _register(st, rel)
    _claim_doc(st, sid=sid, evidence_kind="proof_review")

    got = _load_bearing(st)
    lb = got
    assert lb.get("claims") == [], lb.get("claims")
    assert lb.get("claims_with_proof") == 0, lb
    assert lb.get("state") == "not_applicable", lb
    assert lb.get("claims_below_theorem") == 1, lb
    below = list(lb.get("claims_below_theorem_rows") or [])
    assert below and below[0]["claim_id"] == "c1", below
    assert below[0]["grade"] == "pre_theorem" and below[0]["evidence_kind"] == "proof_review", below
    # 判定面没放宽：§10.2 ① 的机械形态仍只认 `evidence_kind == "proof"`。
    first = CL.MUST_T3_CONDITIONS[0]
    assert first[2] == "enforced" and 'evidence_kind == "proof"' in first[1], first
    # pass 的理由必须读得出来"有门槛以下的断言"，不许与"一条都没有"同形。
    info = [f.detail for f in got["rep"].findings if f.code == "lean_disabled"]
    assert info and "proof_review" in info[0], info
