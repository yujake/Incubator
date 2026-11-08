# -*- coding: utf-8 -*-
"""判据⑤：`verify_proof` 早退时 `sign_issuance` 必须是完整的 fail-closed 键。

## 崩点（2026-11-08）

工具声明（`tools/verify_tools.py` 的 `returns=`）写着 `sign_issuance` 键无条件存在；
而改前 `verify_proof` 的初值是 `sign_issuance: {}`，多条早退路径直接 `return out` ⇒
按 `sign_issuance["checked"]` 读的调用方当场 `KeyError`（V 自检就是这么读的：
`clean["sign_issuance"]["checked"]`）。

修法只在初值（`agent_v/core.py` 的 `fail_closed_sign_issuance`），不改声明那句话。

## 这一份钉的三条

| 条 | 造什么 | 期望 |
|---|---|---|
| a | `bad_statement_id` 早退 | `sign_issuance` 键集合完整、`checked=False`、`issue=False`、`reason` 非空；直接下标读不炸 |
| b | `bad_proof_no` / 载体闸早退 | 同上（两条早退各一次，证明不是"只修了某一条路径"） |
| c | 反真空：把初值改回 `{}` | `got["sign_issuance"]["checked"]` 立刻 `KeyError`（a/b 的绿来自这次修复） |

零网络、零模型：这三条路径都在问模型之前返回。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_v as AVPKG  # noqa: F401  —— 确保包已导入
from agentflow.agent_v import core as AV

#: 完整的 fail-closed 键集合（与 `fail_closed_sign_issuance` 逐字一致；改它要一起改）。
EXPECTED_KEYS = {
    "checked", "issue", "issued", "landed", "decision", "writeback", "streak",
    "need", "streak_ok", "projected", "same_sha", "state", "reason",
    "within_call", "review_call", "ledger_streak", "basis", "reading", "cost",
    "material", "statement_id", "proof_no",
}


def _agent(tmp_path: pathlib.Path) -> AV.AgentV:
    return AV.AgentV(None, workspace_root=tmp_path)


def _assert_fail_closed(got: dict) -> dict:
    iss = got.get("sign_issuance")
    assert isinstance(iss, dict), got
    assert set(iss) == EXPECTED_KEYS, sorted(set(iss) ^ EXPECTED_KEYS)
    # 直接下标读（调用方的读法）不许炸 —— 这就是这条判据的意义。
    assert iss["checked"] is False, iss
    assert iss["issue"] is False, iss
    assert iss["issued"] is False, iss
    assert iss["landed"] is False, iss
    assert str(iss["reason"] or ""), iss
    assert int(iss["need"]) >= 1, iss
    return iss


# ============================================================ a：坏命题号早退

def test_a_bad_statement_id_still_has_the_full_issuance_shape(
        tmp_path: pathlib.Path) -> None:
    got = _agent(tmp_path).verify_proof("7", proof_text="x")
    assert got.get("checked") is False, got
    assert got.get("reason") == "bad_statement_id", got
    iss = _assert_fail_closed(got)
    assert iss["statement_id"] == "7", iss


# ============================================================ b：坏证明号 / 载体闸早退

def test_b_bad_proof_no_still_has_the_full_issuance_shape(
        tmp_path: pathlib.Path) -> None:
    got = _agent(tmp_path).verify_proof("000007", proof_text="1. 显然。", proof_no=0)
    assert got.get("checked") is False, got
    assert got.get("reason") == "bad_proof_no", got
    _assert_fail_closed(got)


def test_c_missing_manuscript_still_has_the_full_issuance_shape(
        tmp_path: pathlib.Path) -> None:
    got = _agent(tmp_path).verify_proof("000007", proof_text="")
    assert got.get("checked") is False, got
    assert got.get("reason") == "proof_text_needs_a_manuscript", got
    iss = _assert_fail_closed(got)
    assert iss["statement_id"] == "000007", iss
    assert int(iss["proof_no"]) == 1, iss   # 缺省 = canonical


# ============================================================ d：反真空

def test_d_restoring_the_empty_initial_value_makes_the_reading_crash(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把初值退回 `{}` ⇒ 直接下标读当场 KeyError（a/b 的绿来自这次修复）。"""
    monkeypatch.setattr(AV, "fail_closed_sign_issuance",
                        lambda **kw: {}, raising=True)
    got = _agent(tmp_path).verify_proof("7", proof_text="x")
    assert got.get("reason") == "bad_statement_id", got
    assert got.get("sign_issuance") == {}, got
    with pytest.raises(KeyError):
        _ = got["sign_issuance"]["checked"]
