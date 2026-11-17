# -*- coding: utf-8 -*-
"""`origin` 只是状态：自产（`own_result`）/ 引用（`external_lit`）—— 不再欠"来路"。

## 业主 2026-11-17 逐字（被测语义）

```
「own_result 还有什么来路？"来路"这种陈述是过时的，以前设计这种语义就是为了指到证明手稿，
 现在已经在台账里体现了。所以只是一个状态：自产/引用」
```

## 推论（本文件钉住的那一半）

`derived_from` / `source_lit_id` 保留为可选信息：有就记，没有不算错。它们当初是
"指到那份证明手稿"的手段，而手稿关联现在由台账体现（`verifications/` / `out/vsigns/` /
`reports/*-proof-*.md` 的签块 / `documents`）。所以两道写口都不许再因为这两格为空而拒收 ——
"自产"的证据是台账里那份签过的稿（收工门「造」那一环，判据在
`tests/test_closing_gate.py::test_the_construct_stage_needs_a_signed_manuscript_in_the_ledger`），
不是调用方在载荷里写了一个 `derived_from`。

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_an_own_result_without_basis_lands_on_both_write_ports` | 两道写口（B 的登记路 / 秘书写口）交不带 `derived_from`/`source_lit_id` 的自产命题 ⇒ 都能入库，且那两格仍然是空的 | 改前受控拒 `missing_own_result_basis`、整笔不写 |
| d) `test_d_concepts_and_cited_statements_are_untouched` | 概念行 / 引用命题两档不受影响（各有各的出处口径） | 不适用（正控：范围不许蔓延） |

为什么两条写口都要测：来路拒当初是两处（B 的登记路 `register_statement` 与秘书写口
`Secretary.record_statement`，后者承接 `table.create("statements")` 的路由）。只删一处
会让另一处继续拒 —— 而"哪一处还在拒"在盘上看起来像"这一笔本来就不合法"。
"""
from __future__ import annotations

import pathlib

import pytest

from _proof_manuscript_fixture import write_proof_manuscript
from _same_statement_stub import wire_for_secretary
from conftest import add_literature, sign_before_registration

from agentflow import schema as S
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools as TT

#: 一条"除了来路之外都齐"的自产命题（与 `test_action_surface_matches_acceptance` 同一形）。
BASE = dict(
    statement_full="本文的引理：对周期图 K(m)，稳定范数取整数值",
    statement_text="稳定范数取整数值",
    origin="own_result", kind="conjecture", evidence_kind="heuristic",
    doc_id="000000",
    proof_text="证明：由定义直接得到。",
    quote_reason="本轮还没做逐字比对（引文那一栏待核）",
)

#: 表创建那条路不带证明正文（`table.create` 的可路由键里没有 `bits`；带正文的新行
#: 本来就过不了正文闸 —— 那是既有的一档，不由这一份引入）。这一形是"没有正文的猜想"。
BASE_TABLE = dict(BASE, proof_text="")


def _world(root: pathlib.Path) -> Store:
    st = Store(root)
    st.init()
    return st


def _b_instance(tmp_path: pathlib.Path):
    """按装配路径造一个 B（真装配：`host.build_role_registry` 的 B 那一条）。"""
    from agentflow import host as host_mod

    ws = tmp_path / "bws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = host_mod.build_role_registry(st, providers=[object()], config={},
                                       workspace_root=str(ws))
    return st, reg["B"][1](store=st)


def _register(b, st, *, n: int, **over):
    """按生产形状登记一笔：稿先落盘、签先落位（与既有夹具同一条路）。"""
    payload = {**BASE, **over}
    payload["proof_manuscript"] = write_proof_manuscript(
        st.root, S.format_id(n), str(payload.get("proof_text") or ""),
        statement_full=payload["statement_full"])
    sign_before_registration(st.root, proof_text=str(payload.get("proof_text") or ""))
    out = b.register_statement(**payload)
    return out if isinstance(out, dict) else out.to_dict()


def _create(st: Store, row: dict, role: str = "B"):
    """按现场的身份调 `table.create(table="statements")`（走真实的路由，不绕它）。"""
    with calling_as("t-000001", role):
        return TT.table_create(TT.TableContext(store=st), table="statements",
                               row=dict(row))


# ---------------------------------------------------------------- a) 两格皆空 ⇒ 能入库
def test_a_an_own_result_without_basis_lands_on_both_write_ports(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：`derived_from` / `source_lit_id` 都空的自产命题，两道写口都能正常入库。

    这不是"放宽"：业主 2026-11-17 的语义是「只是一个状态」—— 自产/引用由 `origin`
    回答；那两格是可选的补充信息。所以判据要钉的是"它们为空时不再被拒"，并且
    落盘那一行里它们确实是空的（不许悄悄替调用方编一个号来满足旧闸）。
    """
    wire_for_secretary(monkeypatch)

    # ① B 的登记路（带稿 + 先签后登记的生产形状）：不带两格来路 ⇒ 照常落库。
    st_b, b = _b_instance(tmp_path / "b")
    got = _register(b, st_b, n=0)
    assert got.get("ok") is True, got
    assert got.get("kind") != "missing_own_result_basis", got
    rows = [dict(r) for r in st_b.rows("statements")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert list(row.get("derived_from") or []) == [], row
    assert not str(row.get("source_lit_id") or "").strip(), row
    assert str(row.get("origin") or "") == "own_result", row
    assert str(row.get("stmt_id") or "") == str(got.get("stmt_id") or ""), (row, got)

    # ② 秘书写口（`table.create` 被路由过来那一条）：同一份"两格皆空"的载荷 ⇒ 照常建行。
    st_t = _world(tmp_path / "t")
    res = _create(st_t, BASE_TABLE)
    assert res.ok is True, (res.data, res.meta, res.error)
    made = [dict(r) for r in st_t.rows("statements")]
    assert len(made) == 1, made
    assert list(made[0].get("derived_from") or []) == [], made[0]
    assert not str(made[0].get("source_lit_id") or "").strip(), made[0]


# ---------------------------------------------------------------- d) 概念 / 引用两档
def test_d_concepts_and_cited_statements_are_untouched(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：概念行与引用命题走各自的口径，不受这一改影响（范围不许蔓延）。

    - 概念行：它的"来路"就是它自己的定义（`conceptrows` 的口径），本来就不带
      `derived_from` / `source_lit_id` —— 概念行的表创建路照旧落库；
    - 引用命题：出处是 `source_lit_id` + `page_range` + 逐字回验（`external_lit`
      那一档），与"自产有没有派生链"是两件事。
    """
    wire_for_secretary(monkeypatch)

    # ① 概念行（表创建路径）
    st = _world(tmp_path / "concept")
    concept = dict(BASE_TABLE, kind="concept", label="稳定范数", self_authored=True,
                   statement_full="概念：图 K(m) 上的稳定范数",
                   quote_reason="概念行：来路是它自己的定义")
    res = _create(st, concept)
    assert res.ok is True, (res.data, res.meta, res.error)
    rows = [dict(r) for r in st.rows("statements")]
    assert [str(r.get("kind") or "") for r in rows] == ["concept"], rows
    assert list(rows[0].get("derived_from") or []) == [], rows[0]

    # ② 引用命题（B 的登记路）：出处那三样齐 ⇒ 照常落库。
    st_b, b = _b_instance(tmp_path / "cited")
    add_literature(st_b, "000000")
    got = _register(b, st_b, n=3, origin="external_lit", source_lit_id="000000",
                    page_range={"label": "全文未分页"},
                    proof_text="原文那一段逐字摘录。",
                    quote_verified=True, quote_reason="")
    assert got.get("ok") is True, got
    assert got.get("kind") != "missing_own_result_basis", got
    cited = next(dict(r) for r in st_b.rows("statements")
                 if str(r.get("stmt_id") or "") == str(got.get("stmt_id") or ""))
    assert str(cited.get("source_lit_id") or "") == "000000", cited
