# -*- coding: utf-8 -*-
"""判据：同一条命题再交一次、证明换了 ⇒ 就地覆盖 canonical 正文（不再被判重挡下）。

## 真机（2026-10-28，`projects/paper-rewrite-78c`，B 的"两扇门"死结）

```
17:19:36  B 用 table.update 改 stmt:000005 的 proof_text
          → 拒：「这一格只有一条正路：再交一次 own.register_statement
                 （statement_full 与在册那一行相同 + 新的 proof_text）⇒ 就地覆盖
                 canonical 正文，旧正文整段进 proof_history」          ← direct_write
17:01:20 / 17:32:33 / 17:38:07   B 照那句话再交一次
          → 拒：「同一条 statement_full 已在册 ⇒ 重复读数，不新建行」  ← backstop
```

那句话承诺的路在实现里不存在：`record_statement` 在同文那一支只认"证据档升强"
（`_upgrade_evidence_kind`），其余一律 `duplicate`。于是 B 左右撞门，`000006` 的第 3 稿
证明落不下去（D 17:53 的回报逐字："statement_text 这一格没能就地改…如实报为缺口"）。

## 这一组守什么

1. 正题：同 `statement_full` + 新 `proof_text` ⇒ `created=False` / `duplicate=False` /
   `updated_proof=True`；行上的 `proof_text` 换掉，旧正文进 `proof_history`（带 `sha` /
   `replaced_by` / `proof_no`）；返回值明说"要重签"；
2. 反真空：同文 + 同证明 ⇒ 仍 `duplicate=True`（真重复不许被当成更新）；
3. 不同 `statement_full` ⇒ 走原路新建一条（这次改动不碰它）；
4. 概念行 / 没有 proof_text 的重复登记 ⇒ 一行一个字都不改。
"""
from __future__ import annotations

import pathlib

from agentflow.secretary import Secretary
from agentflow.store import Store

STATEMENT = "若 H(σ0) 成立（存在绝对常数 σ0<1 使所有 Dirichlet L 在 Re s>σ0 非零），则无 Siegel 零点。"


def _secretary(tmp_path: pathlib.Path) -> tuple[Secretary, Store]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return Secretary("B", root=ws, store=st, enable_model=False), st


def _payload(proof: str) -> dict:
    return {"statement_full": STATEMENT, "statement_text": STATEMENT,
            "kind": "conjecture", "origin": "own_result", "label": "B1 归约命题",
            "proof_text": proof, "evidence_kind": "cross_check",
            "quote_reason": "自产命题，无需逐字引文"}


def _row(st: Store) -> dict:
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    return rows[0]


def test_the_same_proposition_with_a_new_proof_updates_the_canonical_text(tmp_path: pathlib.Path):
    """正题：同文 + 新证明 ⇒ 就地覆盖，旧稿进 proof_history，并要求重签。"""
    sec, st = _secretary(tmp_path)
    first = sec.record_statement(_payload("Proof. 第一稿。"), role="B")
    assert first.get("created") is True, first
    again = sec.record_statement(_payload("Proof. 第二稿（按 V 的 S4/S6 意见改）。"), role="B")
    assert again.get("created") is False, again
    assert again.get("duplicate") is False, again
    assert again.get("updated_proof") is True, again
    assert again.get("resign_required") is True, again
    row = _row(st)
    assert "第二稿" in str(row.get("proof_text")), row.get("proof_text")
    history = row.get("proof_history") or []
    assert history, row
    assert "第一稿" in str(history[-1].get("text")), history[-1]
    assert history[-1].get("sha") and history[-1].get("replaced_by"), history[-1]
    assert int(history[-1].get("proof_no") or 0) == 1, history[-1]


def test_the_same_proposition_with_the_same_proof_is_still_a_duplicate(tmp_path: pathlib.Path):
    """反真空：同文 + 同证明 ⇒ 仍判重复（不许把"真的重复"读成更新）。"""
    sec, st = _secretary(tmp_path)
    sec.record_statement(_payload("Proof. 同一稿。"), role="B")
    again = sec.record_statement(_payload("Proof. 同一稿。"), role="B")
    assert again.get("duplicate") is True, again
    assert again.get("created") is False, again
    assert again.get("updated_proof") is not True, again
    assert (st.rows("statements")[0].get("proof_history") or []) == []


def test_a_different_statement_still_creates_a_new_row(tmp_path: pathlib.Path):
    """正控：不同 statement_full ⇒ 照旧新建一条（这次改动不碰那一支）。"""
    other_statement = ("对任意 ε>0，存在常数 C(ε)>0，使 ζ(1+it) ≠ 0 且 |ζ'(1+it)| ≤ C(ε)log|t| 对一切 |t|≥2 成立。")
    sec, st = _secretary(tmp_path)
    sec.record_statement(_payload("Proof. 甲。"), role="B")
    other = {**_payload("Proof. 乙。"),
             "statement_full": other_statement, "statement_text": other_statement,
             "label": "另一条完全不同的命题"}
    got = sec.record_statement(other, role="B")
    assert got.get("created") is True, got
    assert len(st.rows("statements")) == 2, st.rows("statements")


def test_a_duplicate_without_a_proof_touches_nothing(tmp_path: pathlib.Path):
    """没有 proof_text 的重复登记 ⇒ 一行一个字都不改（还是判重）。"""
    sec, st = _secretary(tmp_path)
    sec.record_statement(_payload("Proof. 有稿。"), role="B")
    bare = {k: v for k, v in _payload("").items() if k != "proof_text"}
    again = sec.record_statement(bare, role="B")
    assert again.get("duplicate") is True, again
    row = _row(st)
    assert "有稿" in str(row.get("proof_text")), row
    assert (row.get("proof_history") or []) == []
