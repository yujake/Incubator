# -*- coding: utf-8 -*-
"""R9FIX 追补：门槛够了、签却没发 ⇒ 盘上要有一条「该发签却没发」的记录。

## 改前（真机 lp-ball-9，08:30:09，正文 sha e863773…）

第 4 个 3/3 clean 组（`review_call=aa5bac98f15b`，passes 1/2/3）没有签文件，也没有
任何失败记录：拒签理由只是 `verify.verify_proof` 返回值里的一句话
（`proof_changed_since_dispatch`：读到 e863，盘上已改成 a724）。返回值读过就没了，
事后只能靠"签文件不在"倒推 —— 「没发」与「没查」在盘上同形。

## 这条判据守什么

1. `streak_ok=True` 且签没落地 ⇒ `out/vsigns/.issuance-missed.jsonl` 有一条，逐字带
   理由码、门槛与两把读数；
2. 幂等：同一 `(sha, code, reason)` 重复调用只追加一次；
3. 反真空：门槛没到（`streak_ok=False`）⇒ 一条都不写（不是"每次没签都记"）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import verifications as VR
from agentflow import vsigns
from agentflow.store import Store


def _workspace(tmp_path: pathlib.Path, *, body: str = "1. a\n") -> Store:
    store = Store(tmp_path)
    store.init()
    p = tmp_path / "reports" / "f-proof-000000.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# x\n\n## 证明\n\n{body}", encoding="utf-8")
    return store


def _try_issue(store: Store, *, streak_ok: bool = True) -> dict:
    return VR._vsigns_write_after_flip(
        store, row={"verifier": "V1"},
        ledger=pathlib.Path(store.root) / "verifications" / "pending" / "x.jsonl",
        statement_id="", proof_no=1, sha="e" * 64,
        holds={"streak": 3 if streak_ok else 2, "need": 3, "streak_ok": streak_ok},
        append_ledger=False, manuscript="reports/f-proof-000000.md")


def _rows(store: Store) -> list[dict]:
    p = vsigns.missed_issue_path(store.root)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]


def test_a_threshold_met_but_unissued_sign_is_recorded(tmp_path: pathlib.Path):
    """改前：签文件不在、盘上 0 条记录（理由只活在返回值里）。"""
    store = _workspace(tmp_path)
    out = _try_issue(store)

    assert out["code"] == "proof_changed_since_dispatch", out
    rows = _rows(store)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["should_issue"] is True and row["written"] is False, row
    assert row["artifact_sha"] == "e" * 64, row
    assert row["streak"] == 3 and row["need"] == 3, row
    assert row["code"] == "proof_changed_since_dispatch", row
    assert "判词 / V 稿 / 台账行只挂读到的那一版" in row["reason"], row


def test_the_same_missed_issue_is_recorded_once(tmp_path: pathlib.Path):
    """幂等：同一 (sha, code, reason) 重复走同一条路只追加一次。"""
    store = _workspace(tmp_path)
    _try_issue(store)
    _try_issue(store)

    assert len(_rows(store)) == 1, _rows(store)


def test_a_short_streak_is_not_recorded(tmp_path: pathlib.Path):
    """反真空：门槛没到（2/3）不是「该发签却没发」，一条都不写。"""
    store = _workspace(tmp_path)
    out = _try_issue(store, streak_ok=False)
    assert out["code"] == "proof_changed_since_dispatch", out
    assert _rows(store) == [], _rows(store)
