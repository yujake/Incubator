# -*- coding: utf-8 -*-
"""`origin=own_result` 的命题必须写清来路（业主 2026-11-17 真机缺陷 ②）。

## 现场（`projects/lp-ball-3`，2026-11-17，exit 1）

收工门 `acceptance` 红（`blocker=acceptance_unmet`），原话：

```
「造」那一环没有我方派生的命题：`statements` 33 行里 `origin=own_result` 的 3 行，
其中没有任何一行写清它派生于什么（`derived_from` 与 `source_lit_id` 都是空的）
```

三条命题（`stmt:000000` / `000001` / `000002`）已经躺在台账里，而"它由什么推出来"
再也补不回原样 —— 只有当时的 B 知道。所以判据必须在登记那一刻说话，不能等到收工门。

## 这一份钉住的四条

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_an_own_result_without_any_basis_is_refused_at_the_write_port` | `origin=own_result` + 两格皆空 ⇒ 受控拒（`kind=missing_own_result_basis`），`statements` 一行都不落 | 改前这一笔照收（真机那 3 行就是这么进去的） |
| b) `test_b_either_cell_alone_lets_it_through` | 任一非空（`derived_from` 或 `source_lit_id`）⇒ 照旧放行，且来路真的落进那一行 | 不适用（正控：闸不许把正常登记堵死） |
| c) `test_c_the_other_origins_are_untouched` | `external_lit` 与概念行不受这一闸影响（各有各的来路口径） | 不适用（正控：范围不许蔓延） |
| d) `test_d_stubbing_the_judgment_off_lets_the_row_land` | 反真空：把判据打桩成"永远齐了" ⇒ a 必红（同一份 payload 落进台账） | 不适用（它守的是 a 不是真空） |

拒信还要逐条点名缺哪一格（业主逐字：「不许只说『缺凭据』」）—— a 里断言两个格子名
都在 `error` 里，且 `missing` 格格都是字段名（机器读得到）。
"""
from __future__ import annotations

import pathlib

import pytest

from conftest import add_literature, sign_before_registration
from _proof_manuscript_fixture import write_proof_manuscript
from _same_statement_stub import wire_for_secretary

from agentflow import schema as S
from agentflow import statementledger as SL
from agentflow.store import Store

#: 一条"除了来路之外都齐"的自产命题（与 `test_action_surface_matches_acceptance` 同一形）。
BASE = dict(
    statement_full="本文的引理：对周期图 K(m)，稳定范数取整数值",
    statement_text="稳定范数取整数值",
    origin="own_result", kind="conjecture", evidence_kind="heuristic",
    doc_id="000000",
    proof_text="证明：由定义直接得到。",
    quote_reason="本轮还没做逐字比对（引文那一栏待核）",
)


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


# ---------------------------------------------------------------- a) 两格皆空 ⇒ 拒
def test_a_an_own_result_without_any_basis_is_refused_at_the_write_port(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：`own_result` + `derived_from`/`source_lit_id` 皆空 ⇒ 受控拒、不进 statements。"""
    wire_for_secretary(monkeypatch)
    st, b = _b_instance(tmp_path)
    got = _register(b, st, n=0)
    assert got.get("ok") is False, got
    assert got.get("kind") == "missing_own_result_basis", got
    err = str(got.get("error") or "")
    # 逐条点名：两个格子名都要在，且拒信要说清下一步（"给它哪几条已登记命题 / 哪篇文献"）
    for cell in ("derived_from", "source_lit_id"):
        assert f"`{cell}`" in err, f"拒信没点名 {cell}：{err}"
    assert "stmt_id" in err and "lit_id" in err, f"拒信没给可执行的下一步：{err}"
    # 机器读数：缺的格格就是字段名本身（不是一句"缺凭据"）
    assert list(got.get("missing") or []) == ["derived_from", "source_lit_id"], got
    assert st.rows("statements") == [], "被拒的这一笔居然进了台账"


# ---------------------------------------------------------------- b) 任一非空 ⇒ 放行
def test_b_either_cell_alone_lets_it_through(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：给 `derived_from` 或给 `source_lit_id`，两种都给得通，且来路真的落进那一行。

    次序上先落"文献支"那一笔（它不许引自己），再拿它的号当"承重链支"的那一格 ——
    这样两条路各自都是真的来路，不是拿一个占位符顶过去。
    """
    wire_for_secretary(monkeypatch)
    st, b = _b_instance(tmp_path)
    add_literature(st, "000000")
    by_lit = _register(b, st, n=1, source_lit_id="000000")
    assert by_lit.get("ok") is True, by_lit
    row_lit = next(r for r in st.rows("statements") if r["stmt_id"] == by_lit["stmt_id"])
    assert str(row_lit.get("source_lit_id") or "") == "000000", row_lit

    base_id = str(by_lit["stmt_id"])
    by_chain = _register(b, st, n=2, statement_full=BASE["statement_full"] + "（承重链支）",
                         derived_from=[base_id])
    assert by_chain.get("ok") is True, by_chain
    row_chain = next(r for r in st.rows("statements") if r["stmt_id"] == by_chain["stmt_id"])
    assert list(row_chain.get("derived_from") or []) == [base_id], row_chain


# ---------------------------------------------------------------- c) 其他 origin 不受影响
def test_c_the_other_origins_are_untouched(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：`external_lit` 走它自己的出处口径（`source_lit_id` + `page_range`），不被这一闸缠住。"""
    wire_for_secretary(monkeypatch)
    st, b = _b_instance(tmp_path)
    add_literature(st, "000000")
    got = _register(b, st, n=3, origin="external_lit", source_lit_id="000000",
                    page_range={"label": "全文未分页"},
                    proof_text="原文那一段逐字摘录。",
                    quote_verified=True, quote_reason="")
    assert got.get("ok") is True, got
    assert got.get("kind") != "missing_own_result_basis", got

    # 概念行：它的"来路"就是它自己的定义（`conceptrows` 的口径），这一闸对它不适用。
    assert SL.own_result_basis_missing(origin="own_result", kind="concept",
                                       derived_from=[], source_lit_id="") == []
    # 判据对"别的 origin"整体不适用（不只看 concept）
    for origin in ("external_lit", "", "borrowed"):
        assert SL.own_result_basis_missing(origin=origin, derived_from=[],
                                           source_lit_id="") == [], origin


# ---------------------------------------------------------------- d) 反真空
def test_d_stubbing_the_judgment_off_lets_the_row_land(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把判据打桩成"永远齐了" ⇒ a 的同一个 payload 落进台账 ⇒ a 必红。

    这就是"闸真的是它在拦"的反真空：摘掉它之后，真机那 3 行的同形 payload 会照旧进库。
    """
    wire_for_secretary(monkeypatch)
    monkeypatch.setattr(SL, "own_result_basis_missing", lambda **_kw: [])
    st, b = _b_instance(tmp_path)
    got = _register(b, st, n=4)
    assert got.get("ok") is True, got
    assert len(st.rows("statements")) == 1, st.rows("statements")
