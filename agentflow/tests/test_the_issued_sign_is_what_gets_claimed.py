# -*- coding: utf-8 -*-
"""「签了 3/3 的命题仍记 conjecture」：认哪一行，由已经发出去的那一签说了算。

## 现场（R10 真机 lp-ball-10，2026-11-19，只读对账 `temp/r10check`）

`reports/f-proof-000001.md` 的 3/3 签在 13:42:16 由 `sign_counting` 数出来并颁发了
（`out/vsigns/4e418348….json`，`ledger=verifications/pending/ef286c92….jsonl#u-000024`）。
11 秒后 V 又对同一份稿跑了一趟，那一趟第 2 轮落成 `u-000025`，秘书判 没查成
（`axis=""`、`checked=false`）。而 `pending_sign` 的口径是「最后扫到的那一行说了算」：

- B 收录那一笔（`register_statement(proof_manuscript=reports/f-proof-000001.md)`）
  拿到的是 `u-000025` ⇒ `row_signable` 为假 ⇒ `ledger_not_signable` ⇒ 不认领、
  不回写 `statement_id`；
- `stmt:000015` 因此停在 `conjecture`（`grade=pre_theorem`、3/3 票）；
- 同一条断链让验收表 R7 读成 `unknown`（「plan 000003 第 4 轮点名了 stmt:000015，
  而 `verifications` 里没有对应的行」）；
- 认领之后"抬 kind"那一格读的是同一个 `pending_sign` ⇒ 它也数不到那 3 票。

断点在读侧选行，不在写侧：`bind_pending_claim` 能写（整份 pending 文件一起绑）、
`_kind_upgrade_from_evidence` 能抬，坏的是"这一份正文的那一签是哪一行"。

## 判据（每条都能造红，也有反真空）

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 3/3 签 + 之后一笔没判成的行 ⇒ 收录后 `kind=theorem`、pending 行回写 `statement_id`、`proof_review_gap.ok` | 真机同形（`review_call` / `review_pass` / 一条没判成的尾行） |
| a-反真空 | 把 `_issued_anchor_of_pending` 打桩成恒 `None` ⇒ a 当场红（kind 回 conjecture） | 证明 a 的绿灯压在这一格上 |
| b | 尾行判 `fault` ⇒ 不翻旧账（认领仍受控拒） | 尾行是「有毛病」 |
| c | 没有签文件（只是 pending 行）⇒ 认领仍受控拒（旧射程不变） | 未发签的三行 |

"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import sign_counting as SC
from agentflow import verifications as VR
from agentflow import vsigns as VS

from test_the_first_sign_before_registration_still_lifts_the_kind import (
    FULL, LABEL, PROOF, _b, _manuscript, _pending_rows, _put, _row, _store,
)

CARRIER = "a" * 64
REL_TAIL = "reports/f-proof-000007.md"

#: 夹具的印迹（a 的现场：3 票 clean + 之后一笔没判成）
CLEAN_JUDGE = {"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"}
UNJUDGED = {"checked": False, "axis": "", "answer": "没查成"}


def _pending(st: object, *, i: int, call: str, judge: dict, at: str) -> dict:
    return VR.record_pending_sign(
        str(getattr(st, "root")), proof_text=PROOF, object_sha256=CARRIER,
        object_path=REL_TAIL, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", secretary_judge=judge,
        review_call=call, review_pass=i, at=at)


def _issue(st: object, rows: list[dict]) -> dict:
    """按真机那一签的形状颁发（锚点 = 第 3 轮那一行）。"""
    return VS.issue(
        str(getattr(st, "root")), artifact_sha=rows[0]["proof_sha256"],
        artifact_path=REL_TAIL, streak=3, need=3,
        ledger=f"verifications/pending/{CARRIER}.jsonl#u-000003",
        proof_no=1, passes=[SC.ticket(r) for r in rows],
        at="2026-11-19T13:42:16+08:00", by="secretary:F")


def _tail_is_unjagged(st: object) -> None:
    """真机的那一行：签发出 11 秒后、另一趟送审的第 2 轮、秘书没判成。"""
    _pending(st, i=2, call="c2", judge=UNJUDGED, at="2026-11-19T13:42:52+08:00")


def _register(st: object, rel: str) -> dict:
    return _b(st).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", derived_from=["999999"], kind="conjecture",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=rel)


# ============================================================ a 正控


def test_a_the_issued_sign_is_what_gets_claimed_and_lifts_the_kind(
        tmp_path: pathlib.Path) -> None:
    """a：3/3 签之后又来一笔没判成的行 ⇒ 收录仍认那一签、kind 抬到 theorem。"""
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    rows = [_pending(st, i=i, call="c1", judge=CLEAN_JUDGE,
                     at=f"2026-11-19T13:42:1{i}+08:00") for i in (1, 2, 3)]
    issued = _issue(st, rows)
    assert issued.get("written") is True, issued
    _tail_is_unjagged(st)

    # 认哪一行：读口自己要说清（不是调用方猜）。
    got = VR.pending_sign(str(st.root), proof_shas=(rows[0]["proof_sha256"],))
    assert got["row"]["verification_id"] == "u-000003", got["row"]
    assert got.get("anchored_at_issued_sign"), got

    filed = _register(st, rel)
    assert filed.get("ok") is True, filed
    sid = str(filed.get("stmt_id") or "")
    row = _row(st, sid)
    assert row["kind"] == "theorem", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("from") == "conjecture" and trace.get("to") == "theorem", trace
    assert "pending" in str(trace.get("basis") or ""), trace
    assert VR.proof_review_gap(st.root, row).get("ok") is True, VR.proof_review_gap(st.root, row)

    # 回填：整份 pending 文件一起绑（含那一笔没判成的行 —— 它是同一份签的几转）。
    claimed = [r for r in _pending_rows(st) if str(r.get("statement_id") or "")]
    assert len(claimed) == 4, [(r.get("verification_id"), r.get("statement_id")) for r in claimed]
    assert {str(r.get("statement_id")) for r in claimed} == {sid}, claimed


def test_a2_without_the_anchor_rule_the_kind_stays_a_conjecture(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a-反真空：把「认已发签锚点」那一格摘掉 ⇒ 同一现场回 conjecture。"""
    monkeypatch.setattr(VR, "_issued_anchor_of_pending", lambda *a, **k: None)
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    rows = [_pending(st, i=i, call="c1", judge=CLEAN_JUDGE,
                     at=f"2026-11-19T13:42:1{i}+08:00") for i in (1, 2, 3)]
    _issue(st, rows)
    _tail_is_unjagged(st)
    filed = _register(st, rel)
    # 收录本身照旧成功（这一笔不是靠拒收来表达的）——变的是它认不到那一签。
    assert filed.get("ok") is True, filed
    row = _row(st, str(filed.get("stmt_id") or ""))
    assert row["kind"] == "conjecture", (
        "摘掉锚点那一格之后 3/3 签仍然抬成了 theorem ⇒ a 的绿灯不是由这一格撑着的", row)
    assert "_kind_upgrade" not in row, row


# ============================================================ b 尾行是 fault


def test_b_a_later_fault_is_not_overruled_by_the_earlier_sign(
        tmp_path: pathlib.Path) -> None:
    """b：尾行判 `fault` ⇒ 不翻旧账（认领仍受控拒，三态不折平）。"""
    st = _store(tmp_path)
    rows = [_pending(st, i=i, call="c1", judge=CLEAN_JUDGE,
                     at=f"2026-11-19T13:42:1{i}+08:00") for i in (1, 2, 3)]
    _issue(st, rows)
    _pending(st, i=1, call="c3",
             judge={"checked": True, "axis": "fault", "decision": "有毛病", "reason": "夹具"},
             at="2026-11-19T13:50:00+08:00")
    got = VR.pending_sign(str(st.root), proof_shas=(rows[0]["proof_sha256"],))
    assert got["row"]["verification_id"] == "u-000004", got["row"]
    assert not got.get("anchored_at_issued_sign"), got

    bits, out = VS.bits_after_sign({}, root=str(st.root), proof_text=PROOF,
                                   statement_id="", proof_no=1, kind="conjecture")
    assert out.get("applied") is False, out
    assert out.get("code") == "ledger_not_signable", out
    assert not (dict(bits).get("reviewed")), bits


# ============================================================ c 没有签文件


def test_c_without_an_issued_sign_the_tail_row_still_decides(
        tmp_path: pathlib.Path) -> None:
    """c：没有签文件（只是 pending 行）⇒ 旧射程不变：尾行不是结论就不认领。"""
    st = _store(tmp_path)
    rows = [_pending(st, i=i, call="c1", judge=CLEAN_JUDGE,
                     at=f"2026-11-19T13:42:1{i}+08:00") for i in (1, 2, 3)]
    _tail_is_unjagged(st)                     # 没有 `VS.issue`：这一份正文没有签文件
    got = VR.pending_sign(str(st.root), proof_shas=(rows[0]["proof_sha256"],))
    assert got["row"]["verification_id"] == "u-000004", got["row"]
    assert not got.get("anchored_at_issued_sign"), got
    _bits, out = VS.bits_after_sign({}, root=str(st.root), proof_text=PROOF,
                                    statement_id="", proof_no=1, kind="conjecture")
    assert out.get("applied") is False and out.get("code") == "ledger_not_signable", out
