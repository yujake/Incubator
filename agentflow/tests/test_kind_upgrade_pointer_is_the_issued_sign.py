# -*- coding: utf-8 -*-
"""判据：`_kind_upgrade` 的指针以「正式颁发的那一签」为准，不取台账最后一条 pending。

## 缺陷（2026-11-14 真机 lp-ball 的 `stmt 000041`）

`f-proof-000001`（正文 sha `0ac4b14c…`）上并发跑了两趟 V：

| 时刻 | pass | 有没有发签 | 签文件/台账指针 |
|---|---|---|---|
| 20:55:26 | u-000001..u-000003 | 发了（`out/vsigns/0ac4b14c….json`） | `verifications/pending/0ac4….jsonl#u-000003` |
| 20:57:25 | u-000004..u-000006 | 没发（`landed=pending`、`charged=false`） | 台账里还有这 3 行 |

`proof_review_gap` 走"最后一条 pending" ⇒ 指针取 `u-000006`，于是
`_kind_upgrade.basis` 写成 `out/vsigns/0ac4….json#u-000006 · 台账 …#u-000006` ——
同一行两个指针打架（签是自己 `#u-000003` 那一签，台账最后一条是 `u-000006`）。

## 判据（红 → 绿）

| # | 判据 | 改前 |
|---|---|---|
| a | 六条 pending、签发在 `u-000003` ⇒ `gap.verification_id == "u-000003"`、`basis` 两处都是 `#u-000003` | `#u-000006` |
| b | 正控 000040（三条 pending、签就是 `u-000003`）⇒ `basis` 与改前逐字相同 | 相同（不许被顺手改动） |

## 反真空

把 `_issued_verification_pointer` 打桩成"没有颁发记录"（即退回"最后一条 pending"）
⇒ a 当场红（`u-000006` 回来），b 仍绿（干净链本来就不受这条修影响）。

全部 tmp 工作区，不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

import conftest

SID_BUG = "000041"
SID_CTRL = "000040"
REL_F = "reports/f-proof-000001.md"
BODY_BUG = "夹具：并发两趟审读的那一份证明正文。"
BODY_CTRL = "夹具：干净链（只有一条 pending 审读）的证明正文。"
AT_SIGN = "2026-11-14T20:55:26+08:00"
AT_LATE = "2026-11-14T20:57:25+08:00"


def _pending_row(no: int, *, sha: str, sid: str, at: str) -> dict:
    return {
        "verification_id": f"u-{no:06d}",
        "statement_id": sid, "stmt_id": sid, "verifier": "agent-V",
        "verdict": "成立", "defect_step": None, "quote": "", "why": "夹具：成立",
        "findings": [], "unresolved_errors": 0, "citation_checks": [],
        "proof_sha256": sha, "proof_chars": 30,
        "object_sha256": "", "object_path": REL_F,
        "proof_no": 1, "round": no, "used_faces": [], "submission_id": "",
        "landed": "pending", "at": at,
        "secretary_judge": {"answer": "没问题", "axis": "clean", "checked": True,
                            "basis": ["夹具：逐条核过"]},
        "path_group": 1, "claimed_at": at,
    }


def _workspace(tmp_path: pathlib.Path, *, body: str, sid: str,
               late_pending: bool) -> tuple[Store, str, dict]:
    """pending 台账（3 或 6 行）+ 一份发在 `#u-000003` 的签；返回 store / sha / 命题行。"""
    st = Store(tmp_path / "ws")
    st.init()
    sha = VS._sign_sha(body)
    rows = [_pending_row(i, sha=sha, sid=sid,
                         at=(AT_SIGN if i <= 3 else AT_LATE))
            for i in range(1, 7 if late_pending else 4)]
    led = pathlib.Path(st.root) / "verifications" / "pending" / f"{sha}.jsonl"
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": sha, "review_call": "call-1", "review_pass": r["round"]}
              for r in rows[:3]]
    got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                   ledger=f"verifications/pending/{sha}.jsonl#u-000003",
                   statement_id="", proof_no=1, passes=passes, at=AT_SIGN,
                   artifact_path=REL_F, by="secretary:F")
    assert got.get("written") is True, got
    conftest.seed_statement_row(
        st, stmt_id=sid, statement_full="夹具命题。", kind="theorem",
        proof_text=body, manuscript_id="000001", proof_no=1)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id") or "") == sid)
    return st, sha, row


def _basis(sha: str) -> str:
    return (f"out/vsigns/{sha}.json#u-000003 · "
            f"台账 verifications/pending/{sha}.jsonl#u-000003")


# ------------------------------------------------------------------ a 绿

def test_a_the_basis_names_the_issued_sign_not_the_last_pending(tmp_path) -> None:
    """a：六条 pending、签发在 u-000003 ⇒ gap 与 basis 都指 u-000003，不指 u-000006。"""
    st, sha, row = _workspace(tmp_path, body=BODY_BUG, sid=SID_BUG, late_pending=True)
    gap = VR.proof_review_gap(st.root, row)
    assert gap.get("ok") is True and gap.get("state") == "signed", gap
    assert gap.get("verification_id") == "u-000003", gap
    assert str(gap.get("ledger") or "").endswith(f"{sha}.jsonl#u-000003"), gap
    basis = VR.kind_upgrade_witness(st.root, row)
    assert basis == _basis(sha), basis
    assert "u-000006" not in basis, basis


# ------------------------------------------------------------------ b 正控

def test_b_the_clean_chain_000040_is_byte_for_byte_unchanged(tmp_path) -> None:
    """b：正控 000040（三条 pending、签就是 u-000003）逐字不变 —— 修 a 不许动它。"""
    st, sha, row = _workspace(tmp_path, body=BODY_CTRL, sid=SID_CTRL,
                              late_pending=False)
    gap = VR.proof_review_gap(st.root, row)
    assert gap.get("ok") is True and gap.get("verification_id") == "u-000003", gap
    assert VR.kind_upgrade_witness(st.root, row) == _basis(sha)


# ------------------------------------------------------------------ 反真空

def test_c_anti_vacuum_last_pending_pointer_turns_it_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把"以颁发签为准"摘掉（退回最后一条 pending）⇒ a 红、b 仍绿。"""
    st_bug, sha_bug, row_bug = _workspace(
        tmp_path / "bug", body=BODY_BUG, sid=SID_BUG, late_pending=True)
    st_ctrl, sha_ctrl, row_ctrl = _workspace(
        tmp_path / "ctrl", body=BODY_CTRL, sid=SID_CTRL, late_pending=False)
    real = VR._issued_verification_pointer

    monkeypatch.setattr(
        VR, "_issued_verification_pointer",
        lambda root, sha: {"checked": True, "found": False, "ledger": "",
                           "verification_id": "", "why": "反真空桩：退回最后一条 pending"})
    gap = VR.proof_review_gap(st_bug.root, row_bug)
    assert gap.get("verification_id") == "u-000006", gap       # a 红：打架重现
    basis = VR.kind_upgrade_witness(st_bug.root, row_bug)
    assert "u-000006" in basis, basis
    # b 仍绿：干净链的最后一条 pending 本来就是 u-000003
    assert VR.kind_upgrade_witness(st_ctrl.root, row_ctrl) == _basis(sha_ctrl)
    assert real is not None
