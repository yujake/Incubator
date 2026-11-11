# -*- coding: utf-8 -*-
"""统一读口：给定稿号 / 路径 ⇒ 产出方 + 提交状态 + 时刻 + via（三块共用）。

判据汇总 c 的三条读数：
- F 的稿走收工 ⇒ `via=closing_auto_submit`、`state=submitted`；
- B 的稿走收录 ⇒ `via=ingested_to_ledger`、`state=submitted`；
- 老验证行没有 `producer_role` ⇒ `unknown`（不是硬填 F）。

另：三处 join（路径族 / V 的颁发表 / `tasks.artifacts` 的 `mss:` 记号）在
`manuscriptsubmission.submission_reading` 一处实现，F / E / B 不各写一份。
"""
from __future__ import annotations

import pathlib

import conftest
import test_b_ingest_marks_submitted as TB
import test_f_auto_submits_signed_manuscripts as TF
from agentflow import manuscriptsubmission as MS
from agentflow import verifications as VR
from agentflow.store import Store


# ============================================================ F：收工自动提交
def _f_submitted(tmp_path: pathlib.Path) -> tuple[Store, str]:
    st = TF._ws(tmp_path)
    f = TF._f(st)
    TF._task(st)
    mid = "000000"
    TF._signed_manuscript(st, mid)
    out = TF._close(f, TF._plan_used_up(f))
    assert out.get("auto_submitted_count") == 1, out
    return st, mid


def test_f_manuscript_reads_submitted_via_closing_auto_submit(tmp_path):
    st, mid = _f_submitted(tmp_path)
    read = MS.submission_reading(st, st.root, manuscript_id=mid)
    assert read["state"] == "submitted", read
    assert read["via"] == MS.VIA_CLOSING, read
    assert read["producer_role"] == "F", read
    assert read["submitted_at"], read
    assert read["signed"] is True, read
    assert read["token"].startswith(f"mss:{mid}"), read
    # 路径入参也读得出同一份
    by_path = MS.submission_reading(st, st.root,
                                    manuscript=f"reports/f-proof-{mid}.md")
    assert by_path["manuscript_id"] == mid and by_path["state"] == "submitted", by_path


# ============================================================ B：收录即提交
def test_b_manuscript_reads_submitted_via_ingested_to_ledger(tmp_path):
    st, b = TB._ws(tmp_path)
    TB._task(st)
    conftest.seed_statement_row(st, stmt_id=TB.SID,
                                statement_full=TB.PROPOSITION, kind="theorem")
    rel = "reports/b-proof-000001.md"
    TB._write(st, rel, TB._manuscript())
    TB._signed_proof(st, rel, TB.PROOF1)
    got = TB._ingest(b, rel, cells=["proof_text"])
    assert got.get("b_submission", {}).get("written") is True, got
    read = MS.submission_reading(st, st.root, manuscript_id="000001")
    assert read["state"] == "submitted", read
    assert read["via"] == MS.VIA_INGEST, read
    assert read["producer_role"] == "B", read
    assert read["submitted_at"], read
    assert read["signed"] is True, read


# ============================================================ 老行：unknown
def test_an_old_verification_row_reads_unknown():
    old = {"verification_id": "v-0001", "stmt_id": "000001",
           "proof_sha256": "a" * 64, "verdict": "成立"}
    assert MS.verification_producer_reading(old)["producer_role"] == "unknown"
    assert VR.producer_reading(old)["checked"] is False


# ============================================================ 未提交
def test_an_unsigned_manuscript_reads_unsubmitted(tmp_path):
    st = TF._ws(tmp_path)
    mid = "000009"
    TF._unsigned_manuscript(st, mid)
    read = MS.submission_reading(st, st.root, manuscript_id=mid)
    assert read["state"] == "unsubmitted", read
    assert read["via"] == "", read
    assert read["producer_role"] == "F", read
