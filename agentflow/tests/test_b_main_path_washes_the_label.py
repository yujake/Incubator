# -*- coding: utf-8 -*-
"""缺陷 ④②：B 主路要把判定那一趟的 `canonical_name` / `route` 带回来 ——
脏标签必须经 B 主路也会被洗掉。

## 审计探针 D（改前红）

`agent_b/register_statement.py` 的 `_same_statement_adjudication` 把
`canonical_name` / `route` 写死成空串 ⇒ `secretary._record_statement_tx` 的洗名条件
（`adj.checked ∧ adj.canonical_name`）永假 ⇒ 脏标签原样落盘。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | B 主路（按手稿路径收录）判成 different、判定那一趟给出 `canonical_name="Sylow 三定理"` / `route="路线一：类方程"` ⇒ 盘上 label 洗成定理名，`label_washed` 给出原标签 → 洗过的名字，`proof_route` 带回路线 | `canonical_name` 恒空 ⇒ 洗名条件永假，脏标签原样落盘 |
| b | 负控：同一笔把 `canonical_name` 留空（即改前的形状）⇒ 脏标签原样落盘 | 这正是改前 B 主路的读数（洗名没有发生） |

零模型调用：判定打桩在 `Secretary.adjudicate_proposition`（唯一判定入口）；
签是 `conftest.sign_before_registration` 落的真 pending 台账。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import (b_form_gate_ok, seed_statement_row,  # noqa: E402
                      sign_before_registration)
from agentflow import depsection as DS  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

MANUSCRIPT = "reports/f-proof-000009.md"
PROPOSITION = "对任意有限群 G，若 |G| = p^a·m 且 p∤m，则 G 有 p 阶元。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")
DIRTY = "Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）"
CLEAN = "Sylow 三定理"
ROUTE = "路线一：类方程/强归纳 + 共轭作用"


def _workspace(tmp_path: pathlib.Path) -> dict:
    st = Store(tmp_path / "ws")
    st.init()
    deps = DS.render_dependency_section([])
    text = (
        "# F 的证明手稿：p 阶元\n\n"
        f"- 标签：{DIRTY}\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{PROPOSITION}\n\n"
        f"## 证明\n\n{PROOF}\n\n" + deps)
    target = pathlib.Path(st.root) / MANUSCRIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    sign_before_registration(st.root, proof_text=PROOF)
    # 台账里先有一条别的命题：`_resolve_same_statement` 只有在"有可检索命题"时才
    # 走秘书那一趟（空台账是"查过 0 条"的确定性短路）。
    seed_statement_row(st, statement_full="另一条命题：设 n<=3，则 Q(n) 成立。",
                       kind="conjecture", label="Q(n)")
    return {"store": st,
            "b": b_form_gate_ok(AgentB(st, extractor=None, extract_text=None,
                                       config={}))}


def _stub(monkeypatch, *, canonical_name: str, route: str) -> None:
    def _judge(self, stmt_like, **kwargs):
        return {"checked": True, "attempted": True, "verdict": "different",
                "same_as": "", "canonical_name": canonical_name, "route": route,
                "condition": "夹具：条件", "conclusion": "夹具：结论",
                "basis": "夹具：条件与结论不同", "reason": "夹具：判 different",
                "candidates": [], "keywords": ["Sylow"], "hits_total": 0,
                "hits_named": [], "judged": False, "pages_total": 1,
                "pages_judged": 0, "candidates_total": 0, "page_exhausted": True,
                "reused": False, "cached": False, "statement_sha256": "",
                "seam_source": "fixture", "cost": {}}

    monkeypatch.setattr(SEC.Secretary, "adjudicate_proposition", _judge)


def _row_by_proposition(env: dict, proposition: str) -> dict:
    return next(dict(r) for r in env["store"].rows("statements")
                if str(r.get("statement_full") or "") == proposition)


# ============================================================ a B 主路洗名
def test_a_b_main_path_washes_the_dirty_label(tmp_path, monkeypatch) -> None:
    """a：判定那一趟的 `canonical_name` / `route` 经 B 主路带回 ⇒ 脏标签被洗。"""
    env = _workspace(tmp_path)
    _stub(monkeypatch, canonical_name=CLEAN, route=ROUTE)
    got = env["b"].register_statement(statement_full="",
                                      proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    row = _row_by_proposition(env, PROPOSITION)
    assert row["label"] == CLEAN, (
        "B 主路没把判定那一趟的 canonical_name 带回来："
        f"盘上 label={row['label']!r}（原标签 {DIRTY!r}）")
    washed = dict(got.get("label_washed") or {})
    assert washed.get("from") == DIRTY and washed.get("to") == CLEAN, washed
    assert str(got.get("proof_route") or "") == ROUTE, got.get("proof_route")
    adj = dict(row.get("_proposition_adjudication") or {})
    assert adj.get("canonical_name") == CLEAN, adj


# ============================================================ b 负控：改前形状
def test_b_without_the_carried_canonical_name_the_label_stays_dirty(
        tmp_path, monkeypatch) -> None:
    """b：`canonical_name` 留空（改前 B 主路的形状）⇒ 脏标签原样落盘。"""
    env = _workspace(tmp_path)
    _stub(monkeypatch, canonical_name="", route="")
    got = env["b"].register_statement(statement_full="",
                                      proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    row = _row_by_proposition(env, PROPOSITION)
    assert row["label"] == DIRTY, row["label"]
    assert not dict(got.get("label_washed") or {}), got.get("label_washed")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
