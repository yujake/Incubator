# -*- coding: utf-8 -*-
"""D 代递 E 的 `exp:` 携带行（业主 2026-11-04 裁定 B）。

## 业主裁定（逐字）

    B 甲 —— E 的 exp: 行也由 D 代递（与 F 行同形）

## 改前是什么形态

`_deliver_carried_to_b` 对 `exp:` 行只记一条 `addressed`（"命题还没有号 ⇒ D 不代它登记"），
于是 E 的穷举证明稿虽然写在携带单上，**B 从未被 D 直接调用过**：`statements` 里那一行
只能等下一次 B 自己（或 D 派 B 的模型 args）去补。A 的裁定把这一环定成"与 F 行同形"：
D 在代码里调 `B.register_statement`，参数从 experiment 行 + 稿拼：
`statement_full`（experiment.claim）/ 证明栏（稿的 `## 证明`）/ `doc_id` / `line_range`。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 已签的 `exp:` 行 ⇒ D 的 `write_report` 真的把它递给 B；B 收下（`ok=True`）、`statements` 多一行、`reviewed=True` | 改前 `addressed`，B 一次都没被调用，`statements` 0 行 |
| b | 没签的 `exp:` 行不代递（`kind=exp_proof_unsigned`）、`statements` 仍是 0 行 | 沿用既有判据（携带单只收已签），代递最后一道也再核一次 |
| c | 反真空：把代递那一笔摘掉 ⇒ B 侧收不到、`statements` 里没有那一行 | 证明 a 的绿来自 D 的代码调用，不是来自 B 恰好自己跑过 |

零模型调用：E 的穷举会审是机械七项；B 的登记不发模型请求。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import depsection as DS  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402

from test_e_proof_is_carried_by_d import CLAIM, CLAIM_KEY, _env  # noqa: E402


def _d(env: dict) -> AgentD:
    """按真机装配的形状造 D：构造期拿到同一个 B 实例（`specs/d.py` 的 `peers["B"]`）。"""
    return AgentD(env["store"], config={"workspace_root": env["store"].root},
                  b=env["b"])


def _exp_rec(delivery: dict, eid: str) -> dict | None:
    return next((dict(r) for r in (delivery.get("results") or [])
                 if str(r.get("experiment_id") or "") == eid), None)


# ============================================================ a 代递并入库
def test_a_the_signed_exp_row_is_delivered_and_lands_a_statement(
        tmp_path: pathlib.Path) -> None:
    """a：已签 exp 行 ⇒ D 交货给 B、B 收下、statements 一行且 reviewed=True。"""
    env = _env(tmp_path)
    eid = str(env["out"]["experiment_id"])
    assert not list(env["store"].rows("statements")), "前提：命题还没进台账"

    d = _d(env)
    d.write_report()
    delivery = d.last_delivery
    rec = _exp_rec(delivery, eid)
    assert rec is not None, delivery
    assert rec.get("ok") is True, rec
    assert str(rec.get("manuscript_source") or "") == DS.SOURCE_CARRIED, rec
    assert str(rec.get("stmt_id") or ""), rec
    assert int(rec.get("deps_written") or 0) >= 0, rec
    # 不再是"没被问"的 addressed 读数：这一趟真的调用了 B。
    assert [x for x in (delivery.get("addressed") or [])
            if str(x.get("experiment_id") or "") == eid] == [], delivery

    rows = [dict(r) for r in env["store"].rows("statements")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("stmt_id") or "") == rec["stmt_id"], row
    assert str(row.get("statement_full") or "") == CLAIM, row
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, bits
    # 证明栏来自稿的 `## 证明` 节（与 E 给的证明栏逐字同源）。
    assert str(row.get("proof_text") or "") == str(env["column"]), row
    # 出处指回 experiment 行（E 的账），不是编出来的文献页。
    assert "exp:" in str((row.get("line_range") or {}).get("label") or ""), row


# ============================================================ b 没签不代递
def test_b_an_unsigned_exp_row_is_not_delivered(tmp_path: pathlib.Path) -> None:
    """b：没签的 exp 稿 ⇒ D 不代递、B 侧收不到、statements 0 行。"""
    env = _env(tmp_path, sign=False)
    eid = str(env["out"]["experiment_id"])
    rel = str(env["out"]["proof_manuscript"])
    d = _d(env)

    # ① 走 `write_report`：携带单本来就筛掉没签的稿 ⇒ 连行都没有。
    d.write_report()
    assert _exp_rec(d.last_delivery, eid) is None, d.last_delivery
    assert not list(env["store"].rows("statements"))

    # ② 直接把那一行递进代递口（清单漂移 / 直调那一档）：最后一道判据仍不递。
    rec = d._deliver_exp_row({"experiment_id": eid, "path": rel})
    assert rec is not None and rec.get("ok") is False, rec
    assert rec.get("kind") == "exp_proof_unsigned", rec
    assert not list(env["store"].rows("statements")), "没签的稿被登记进了 statements"


# ============================================================ c 反真空
def test_c_removing_the_delivery_leaves_b_without_the_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：把 D 代递 exp 的那一笔摘掉 ⇒ B 侧收不到、statements 里没有那一行。"""
    env = _env(tmp_path)
    eid = str(env["out"]["experiment_id"])

    monkeypatch.setattr(AgentD, "_deliver_exp_row", lambda self, row: None)
    d = _d(env)
    d.write_report()
    assert _exp_rec(d.last_delivery, eid) is None, d.last_delivery
    assert int(d.last_delivery.get("delivered") or 0) == 0, d.last_delivery
    assert not list(env["store"].rows("statements")), (
        "摘掉代递之后 statements 里仍有一行 ⇒ a 的绿不是 D 那一笔带来的")
