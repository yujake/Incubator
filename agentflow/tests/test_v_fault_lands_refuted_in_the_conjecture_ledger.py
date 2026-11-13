# -*- coding: utf-8 -*-
"""判据 ③(b2)：V 判「有毛病」⇒ 猜想台账那一行落 `refuted`（业主 2026-11-13 裁定 ②）。

## 这一格补的是哪半边

裁定 ②：「被拒 ⇒ `refuted`，办法是给 `Conjecture` 的证据加第二条 `refusal_ref`」。被拒有
两条真实的来路，都落同一个函数（`conjectureledger.mark_refuted`）：

- E 跑出反例（`result=refutes`）⇒ `refuted` + `counterexample_experiment_id`（E 那一笔，见
  `test_conjecture_ledger_has_one_write_point.py`）；
- V 判「有毛病」或 B 拒收 ⇒ `refuted` + `refusal_ref`。B 那一侧接在 `register_statement`
  的拒收路上；V 这一侧接在 `verifications.record_verification`（V 的判词落台账的唯一入口）。

## 判据

| # | 判据 |
|---|---|
| a | V 判「有毛病」⇒ 猜想行 `refuted`，`refusal_ref` 指向 `verifications/<命题号>.jsonl#v-…`，且那一行带读数 `conjecture_refutation.checked=True` |
| b | V 判「成立」⇒ 猜想行一个字节都不动（`refused` 不是"每次审校都改台账"） |
| c | 反真空：把 `conjectureledger.mark_refuted` 打桩成不写 ⇒ a 必须红 |
| d | 三态：命题正文读不到（`statements` 里没有这一条）⇒ 读数是 `checked=False` + 理由，不是"没被拒" |
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import conjectureledger as CL  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.store import Store  # noqa: E402

SID = "000001"
PROOF = ("取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n"
         "反例满足题设，故原命题不成立。\n")
STATEMENT = "对每个 n ≥ 3，正则图的围长都不小于 n。"
TS = "2026-11-13T00:00:00+08:00"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed_rows(st: Store) -> str:
    """铺一条猜想行（产出侧落的）+ 一条正文相同的命题行（V 审的是它）。"""
    conj = CL.register(store=st, statement=STATEMENT, origin="experiment:000009",
                       testable={"criterion": "逐 n 验围长"}, status="proposed",
                       actor="agent-E")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": SID, "statement_full": STATEMENT,
                                 "kind": "theorem", "status": "active",
                                 "origin": "own_result",
                                 "quote_reason": "夹具：还没查（不是没通过）",
                                 "created_at": TS, "updated_at": TS})
    return str(conj["conjecture_id"])


def _fault() -> dict:
    return VR.parse_verdict(json.dumps({
        "verdict": "有毛病", "defect_step": 1, "quote": "它是 2-正则",
        "why": "第 1 步无条件把 C_n 当成反例，而原命题是对正则图的一般断言",
        "findings": [{"level": "error", "step": 1, "kind": "反例不成立",
                      "detail": "C_n 的围长是 n，正好满足命题结论"}],
    }, ensure_ascii=False))


def _clean() -> dict:
    return VR.parse_verdict(json.dumps({
        "verdict": "成立", "quote": "", "why": "", "findings": [],
    }, ensure_ascii=False))


def _row_of(st: Store, cid: str) -> dict:
    return next(dict(r) for r in st.rows("conjectures")
                if str(r.get("conjecture_id")) == cid)


# ============================================================ a 正控

def test_a_a_fault_verdict_lands_refuted_with_the_ledger_ref(tmp_path):
    """a：V 判「有毛病」⇒ 猜想行 `refuted` + `refusal_ref` 指到那一签。"""
    st = _store(tmp_path)
    cid = _seed_rows(st)
    row = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                                 verdict=_fault(), flip=False)
    reading = dict(row.get("conjecture_refutation") or {})
    assert reading.get("checked") is True, reading
    assert reading.get("refuted") is True, reading
    assert reading.get("conjecture_id") == cid, reading
    want = f"verifications/{SID}.jsonl#{row['verification_id']}"
    assert reading.get("refusal_ref") == want, reading
    got = _row_of(st, cid)
    assert got["status"] == "refuted", got
    assert got["refusal_ref"] == want, got


# ============================================================ b 反方向：成立不动它

def test_b_a_clean_verdict_does_not_touch_the_conjecture_row(tmp_path):
    """b：「成立」⇒ 猜想行一个字节都不动，返回行上也不加那一格。"""
    st = _store(tmp_path)
    cid = _seed_rows(st)
    before = _row_of(st, cid)
    row = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                                 verdict=_clean(), flip=False)
    assert row["verdict"] == "成立", row
    assert "conjecture_refutation" not in row, row.get("conjecture_refutation")
    after = _row_of(st, cid)
    assert after["status"] == before["status"] and after == before, (before, after)


# ============================================================ c 反真空

def test_c_stub_out_mark_refuted_and_the_refutation_disappears(tmp_path, monkeypatch):
    """c（反真空）：把唯一写点打桩成不写 ⇒ 猜想行必须仍不是 `refuted`。"""
    st = _store(tmp_path)
    cid = _seed_rows(st)
    before = _row_of(st, cid)

    def _no_write(**_kw):
        return {"ok": False, "kind": "stubbed", "reason": "夹具：不写"}

    monkeypatch.setattr(CL, "mark_refuted", _no_write)
    row = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                                 verdict=_fault(), flip=False)
    after = _row_of(st, cid)
    assert after["status"] == before["status"], f"写点被打桩成不写，行却变了：{after}"
    reading = dict(row.get("conjecture_refutation") or {})
    assert reading.get("refuted") is False, reading


# ============================================================ d 三态：对不上那一行

def test_d_a_fault_without_a_matching_statement_says_not_checked(tmp_path):
    """d：命题正文读不到 ⇒ `checked=False` + 理由（"对不上"不是"没被拒"）。"""
    st = _store(tmp_path)
    _seed_rows(st)
    # 把 statements 那一行删掉：V 的判词在，但正文对不上猜想行
    with st.tx("statements", actor="test") as tx:
        tx.delete("statements", SID)
    row = VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                                 verdict=_fault(), flip=False)
    reading = dict(row.get("conjecture_refutation") or {})
    assert reading.get("checked") is False, reading
    assert "读不到正文" in str(reading.get("reason") or ""), reading
