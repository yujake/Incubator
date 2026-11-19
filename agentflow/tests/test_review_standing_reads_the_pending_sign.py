# -*- coding: utf-8 -*-
"""判据：`review_standing` 必须读到「先签后收录」那一签（FIX186-D1）。

## 现场（lp-ball-11，`draft/186` §5bis）

```text
out/vsigns/80061a57….json 3/3 成立、verifications/pending/30af0d0b….jsonl 第 2–5 行
statement_id="000005"，但 verifications/000005.jsonl 不存在
⇒ review_standing 只读后者 ⇒ statement_review_reading 读成 unsigned/grade=conjecture、
  final_gaps 的 unsigned +1、acceptance 的 construct_leg.linked.where 指向不存在的文件
```

`proof_review_gap` 有 pending 回退（`:5960-5988`），`review_standing` 没有 —— 同一族缺陷：
同一件事两个读口两个答案。

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 已认领的 pending 3/3「成立」⇒ `statement_review_reading` 读成 `signed`、`reviewed=True`、`streak=3/3`、`review_source="pending"` | 改前读成 unsigned |
| b | 同一现场 `grading` 抬到 `pre_theorem`（不再被读成 conjecture） | 改前 `grade=conjecture` |
| c | 反真空：把 pending 回退打桩掉 ⇒ 回到 unsigned（证明 a 的绿来自那一叠签） | —— |
| d | 认领给别的命题的那一签不算（不许借光） | —— |
| e | 在册台账有行时以正本为准（pending 不盖过已收录的行） | —— |

## 边界

`tmp_path` 工作区；不读写 `projects/`。真实副本上的复算见 `temp/fix186/judge_d1_lp11.py`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest                                     # noqa: E402
from agentflow import verifications as VR           # noqa: E402
from test_load_bearing_reads_the_claimed_pending_sign import (  # noqa: E402
    PROOF, _register, _row, _signed_rows, _store,
)

SID_OTHER = "000042"


def _claimed_pending(tmp_path: pathlib.Path) -> tuple[object, str, dict]:
    """造 lp-ball-11 那一种现场：pending 里 3/3 已签 + 在册、在册台账文件不存在。"""
    st = _store(tmp_path)
    _signed_rows(st)                      # 3 转「成立」，同一份正文
    sid = _register_min(st)
    row = _row(st, sid)
    assert not (pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl").is_file(), (
        "夹具前提：在册台账不能存在（先签后收录的现场）")
    return st, sid, row


def _register_min(st: object) -> str:
    """收录那份稿（登记拿到号、pending 那一签被认领）；夹具与 R10FIX-D4 的同形。"""
    from test_load_bearing_reads_the_claimed_pending_sign import _manuscript, _put

    rel, text = _manuscript()
    _put(st, rel, text)
    return _register(st, rel)


# ============================================================ a + b：读成 signed
def test_a_the_pending_sign_is_the_current_v_sign(tmp_path: pathlib.Path) -> None:
    """a：pending 3/3「成立」⇒ 命题级 signed / reviewed / streak 3/3。"""
    st, sid, row = _claimed_pending(tmp_path)
    reading = VR.statement_review_reading(st.root, row)
    assert reading["state"] == "signed", reading
    assert reading["reviewed"] is True, reading
    assert reading["proofs"][0]["state"] == "signed", reading["proofs"]
    assert reading["proofs"][0]["streak"] == VR.SIGN_STREAK_NEED, reading["proofs"]
    assert reading["proofs"][0]["need"] == VR.SIGN_STREAK_NEED, reading["proofs"]
    assert reading["proofs"][0]["verification_id"] == "u-000003", reading["proofs"]


def test_b_the_grade_lifts_because_the_sign_is_found(tmp_path: pathlib.Path) -> None:
    """b：同一现场等级抬到 `pre_theorem`（改前被读成 conjecture）。"""
    st, sid, row = _claimed_pending(tmp_path)
    reading = VR.statement_review_reading(st.root, row)
    assert reading["grade"] == "pre_theorem", reading


# ============================================================ c：反真空
def test_c_without_the_pending_fallback_it_is_unsigned_again(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：把 pending 回退打桩掉 ⇒ 回到 unsigned（a 的绿由那一叠签决定）。"""
    st, sid, row = _claimed_pending(tmp_path)
    monkeypatch.setattr(VR, "_pending_standing_rows",
                        lambda *a, **k: None)   # noqa: ARG005
    reading = VR.statement_review_reading(st.root, row)
    assert reading["state"] == "unsigned", reading
    assert reading["reviewed"] is False, reading


# ============================================================ d：不许借光
def test_d_a_sign_claimed_to_another_statement_does_not_count(
        tmp_path: pathlib.Path) -> None:
    """d：pending 那一签认给 000001，问 000042 ⇒ 不借光（unsigned）。"""
    st, sid, row = _claimed_pending(tmp_path)
    other = conftest.seed_statement_row(
        st, stmt_id=SID_OTHER, statement_full="另一条夹具命题（同一份正文）。",
        proof_text=PROOF, kind="conjecture", status="active",
        quote_reason="夹具：还没放弃")
    standing = VR.review_standing(st.root, statement_id=SID_OTHER,
                                  proof_text=PROOF, proof_no=1)
    assert standing["state"] == "unsigned", standing
    assert str(standing.get("verification_id") or "") == "", standing
    assert other["stmt_id"] == SID_OTHER


# ============================================================ e：在册台账优先
def test_e_the_register_ledger_wins_over_pending(tmp_path: pathlib.Path) -> None:
    """e：在册台账有一行「有毛病」⇒ 仍按正本读（pending 那 3/3 不许把它盖掉）。"""
    st, sid, row = _claimed_pending(tmp_path)
    ledger = pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(ledger).write_text("", encoding="utf-8")   # 先放一个空文件
    assert VR.review_standing(st.root, statement_id=sid,
                              proof_text=PROOF, proof_no=1)["state"] == "signed"
    # 有行时以正本为准：写一行「成立」但 axis=fault ⇒ rejected，pending 不参与。
    VR.record_verification(
        str(st.root), statement_id=sid, proof_text=PROOF, proof_no=1,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        manuscript="reports/f-proof-000001.md",
        secretary_judge={"checked": True, "axis": "fault", "decision": "有问题",
                         "reason": "夹具：秘书读出缺陷"})
    assert VR.review_standing(st.root, statement_id=sid,
                              proof_text=PROOF, proof_no=1)["state"] == "rejected"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
