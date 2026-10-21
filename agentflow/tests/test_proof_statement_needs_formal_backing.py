# -*- coding: utf-8 -*-
"""命题自称 `proof` 必须有 formal 实验背书（缺陷 ④）。

## 为什么只能在审计侧查

`Statement` 的字段里没有任何指向实验/检查器的引用
（`stmt_id/origin/kind/label/statement_text/proof_text/source_lit_id/page_range/
quote_verified/quote_mode/quote_reason/quote_span/quote_call_sha256/evidence_kind/bits`）
⇒ 写库时无法"就地"判它有没有被检查器核过。于是这条不变量放在
`verify.py::_check_13`（命题台账那一段）里做跨表对账：

* `evidence_kind="proof"` 的命题，必须在 `experiments` 里有
  `method="formal"` ＋ `evidence_kind="proof"` 的行，且它的
  `verifier_subject_key`/`claim_key` 能撞上命题的 `label`/`proof_text`；
* 撞不上 ⇒ 一条 warning `proof_stmt_without_formal_backing`
  （不阻断写库，但报告里看得见 —— 与 `active_stmt_quote_unverified` 同档）。
"""
from __future__ import annotations

from agentflow import verify as V


class _Rep:
    def __init__(self) -> None:
        self.issues: list = []
        self.checked: dict = {}


class _Store:
    def __init__(self, rows: dict) -> None:
        self._rows = rows

    def rows(self, table: str) -> list:
        return list(self._rows.get(table, []))


def _proof_stmt(stmt_id: str, label: str) -> dict:
    return {"stmt_id": stmt_id, "evidence_kind": "proof", "label": label,
            "proof_text": "证明正文", "status": "active"}


def _codes(rep: _Rep) -> list[str]:
    return [str(getattr(i, "code", "")) for i in rep.issues]


def test_a_proof_statement_without_a_formal_experiment_is_flagged():
    """负控：自称 proof，台账里一条 formal 实验都没有 ⇒ 必须报。"""
    rep = _Rep()
    V._check_13(rep, _Store({
        "statements": [_proof_stmt("000000", "thm:stable")],
        "literature": [], "documents": [], "experiments": [],
    }))
    assert "proof_stmt_without_formal_backing" in _codes(rep), _codes(rep)


def test_a_proof_statement_backed_by_a_formal_experiment_is_clean():
    """正控：有 `method=formal` ＋ `evidence_kind=proof` 且 key 对得上 ⇒ 不许误报。"""
    rep = _Rep()
    V._check_13(rep, _Store({
        "statements": [_proof_stmt("000001", "thm:stable")],
        "literature": [], "documents": [],
        "experiments": [{"method": "formal", "evidence_kind": "proof",
                         "claim_key": "thm:stable"}],
    }))
    assert "proof_stmt_without_formal_backing" not in _codes(rep), _codes(rep)


def test_a_non_proof_statement_is_not_constrained():
    """边界：`evidence_kind` 不是 proof（`cross_check`/`heuristic`）⇒ 这条规则不管它。"""
    rep = _Rep()
    stmt = _proof_stmt("000002", "thm:stable")
    stmt["evidence_kind"] = "cross_check"
    V._check_13(rep, _Store({"statements": [stmt], "literature": [], "documents": [],
                             "experiments": []}))
    assert "proof_stmt_without_formal_backing" not in _codes(rep), _codes(rep)
