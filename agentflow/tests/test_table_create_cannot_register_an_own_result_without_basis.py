# -*- coding: utf-8 -*-
"""表创建路径也不能落「没有来路」的 `own_result`（业主 2026-11-17 真机缺陷 ② 的尾巴）。

## 现场（FX2 逐字）

FX2 已经把判据接进 B 的登记那一步（`agent_b/register_statement.py` 调
`statementledger.own_result_basis_missing` ⇒ 受控拒 `missing_own_result_basis`），
但秘书写口 `Secretary.record_statement` 还没有这道闸：
`table.create("statements")` 被 `store.direct_write_refusal` 转给秘书
（`tools/table_tools.py::_route_to_secretary`），仍能写入无来路的 `own_result` 行
⇒ 收工门仍会红（真机 `projects/lp-ball-3`：33 条命题里 3 条 `own_result` 全空）。

## 这一份钉住的五条

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_table_create_of_an_own_result_without_basis_is_refused_and_lands_nothing` | 表创建路径交无来路的 `own_result` ⇒ 受控拒（`missing_own_result_basis`）+ `statements` 0 行 | 改前这一笔照收（真机那 3 行就是这么进去的） |
| b) `test_b_the_two_write_roads_give_the_same_code_and_the_same_wording` | B 的登记路与秘书写口逐字同码、同拒信（reason 相等） | 改前秘书这一侧根本没有这句拒信 |
| c) `test_c_a_basis_lets_the_table_route_through` | 有来路（`derived_from` 或 `source_lit_id` 非空）⇒ 照旧落库，且来路真的落进那一行 | 不适用（正控：闸不许把正常登记堵死） |
| d) `test_d_concepts_and_the_numeric_green_channel_are_untouched` | 概念行 / 普通数值绿通不受影响（各有各的来路口径） | 不适用（正控：范围不许蔓延） |
| e) `test_e_stubbing_the_secretary_gate_off_lets_the_same_payload_land` | 反真空：把秘书写口这道闸打桩关掉 ⇒ a 必红（同一份载荷落进台账） | 不适用（它守的是 a 不是真空） |

判据 b 的比法不是"两边都拒"，而是两边吐出同一个受控码、同一句点名两格的拒信：
两处各写一遍"有没有来路"，改一处就会让"B 拒的"与"表创建被拒的"漂开 —— 那正是
这次要收掉的形态。拒信还要逐条点名缺哪一格（`derived_from` / `source_lit_id`）。

夹具形状说明：表创建这条路不带证明正文。`bits` 是 `table_tools._NOT_ROUTABLE_KEYS`
里的一格（带着它连路由都进不去），而秘书的正文闸对"没有 bits 的新行"不 defer ⇒
带正文的新行本来就过不去（那是既有的一档，不由这一闸引入）。这一份要量的是
"来路"，所以夹具用"没有正文的猜想"这一形：来路闸之外，它是真能落库的。
"""
from __future__ import annotations

import pathlib

import pytest

from _same_statement_stub import wire_for_secretary

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import statementledger as SL
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools as TT

#: 一条"除了来路之外都齐"的自产命题（与 `test_own_result_must_say_where_it_comes_from`
#: 的 BASE 同一形；没有证明正文 —— 见模块 docstring 最后一段）。
BASE = dict(
    statement_full="本文的引理：对周期图 K(m)，稳定范数取整数值",
    statement_text="稳定范数取整数值",
    origin="own_result", kind="conjecture", evidence_kind="heuristic",
    doc_id="000000",
    proof_text="",
    quote_verified=None,
    quote_reason="本轮还没做逐字比对（引文那一栏待核）",
)


def _world(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _ctx(st: Store) -> TT.TableContext:
    return TT.TableContext(store=st)


def _create(st: Store, row: dict, role: str = "B"):
    """按现场的身份调 `table.create(table="statements")`（走真实的路由，不绕它）。"""
    with calling_as("t-000001", role):
        return TT.table_create(_ctx(st), table="statements", row=dict(row))


def _route_detail(res) -> dict:
    """兜底方（秘书）自己那份读数：`meta.detail` 里带着它的 `refused` / `reason` / `missing`。"""
    meta = dict(res.meta or {})
    return dict(meta.get("detail") or {})


# ---------------------------------------------------------------- a) 无来路 ⇒ 拒
def test_a_table_create_of_an_own_result_without_basis_is_refused_and_lands_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：`table.create("statements")` 交无来路的 `own_result` ⇒ 受控拒 + 0 行。

    断言四样：处置是"兜底方拒"、码是 `missing_own_result_basis`、拒信点名两格、
    `statements` 一行都不落。
    """
    wire_for_secretary(monkeypatch)
    st = _world(tmp_path)
    res = _create(st, BASE)
    assert res.ok is False, (res.data, res.meta)
    detail = _route_detail(res)
    assert str(detail.get("refused") or "") == "missing_own_result_basis", detail
    err = str(detail.get("reason") or "")
    for cell in ("derived_from", "source_lit_id"):
        assert f"`{cell}`" in err, f"拒信没点名 {cell}：{err}"
    assert "stmt_id" in err and "lit_id" in err, f"拒信没给可执行的下一步：{err}"
    assert list(detail.get("missing") or []) == ["derived_from", "source_lit_id"], detail
    assert st.rows("statements") == [], "被拒的这一笔居然进了台账"

    # ② 这条受控拒必须在拒信台账留一行原文（AL2 那条壳；六格逐格点名）。
    from agentflow import refusals as R

    lines = R.refusal_records(st.root)
    assert len(lines) == 1, f"拒了一次，台账却是 {len(lines)} 行：{lines}"
    line = lines[0]
    for key in ("kind", "why", "at", "role", "task_id", "where"):
        assert key in line, f"台账那一行缺 {key!r}：{sorted(line)}"
    assert line["kind"] == "missing_own_result_basis", line
    assert line["why"] == err, ("台账里的 why 与返回值里的 reason 不是同一句", line, err)
    assert line["where"] == "secretary.record_statement", line
    assert line["role"] == "B", line
    assert line["task_id"] == "t-000001", line
    assert str(line["at"]).strip(), "台账那一行没有时刻"
    assert R.refusal_ledger_path(st.root).parent == pathlib.Path(st.root) / "out" / "secretary"


# ---------------------------------------------------------------- b) 两路同码同措辞
def _b_instance(tmp_path: pathlib.Path):
    """按装配路径造一个 B（与 FX2 判据同一个造法）。"""
    from agentflow import host as host_mod

    ws = tmp_path / "bws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = host_mod.build_role_registry(st, providers=[object()], config={},
                                       workspace_root=str(ws))
    return st, reg["B"][1](store=st)


def test_b_the_two_write_roads_give_the_same_code_and_the_same_wording(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：B 的登记路与秘书写口（表创建路由）⇒ 同一个码、同一句拒信（逐字相等）。

    只比"两边都拒"是不够的：拒信是模型真正读到的那一格，两处各写一遍就会漂开。
    所以这里断言 `detail["reason"] == B 的 error`、`detail["refused"] == B 的 kind`、
    `missing` 两格也相等 —— 判据与措辞都只有 `statementledger` 那一处。
    """
    wire_for_secretary(monkeypatch)
    st_b, b = _b_instance(tmp_path / "b")
    by_b = b.register_statement(**BASE)
    by_b = by_b if isinstance(by_b, dict) else by_b.to_dict()
    assert by_b.get("ok") is False, by_b
    assert by_b.get("kind") == "missing_own_result_basis", by_b
    assert not st_b.rows("statements"), st_b.rows("statements")

    st_table = _world(tmp_path / "table")
    res = _create(st_table, BASE)
    detail = _route_detail(res)
    assert res.ok is False, (res.data, res.meta)
    assert str(detail.get("refused") or "") == str(by_b.get("kind") or ""), detail
    assert str(detail.get("reason") or "") == str(by_b.get("error") or ""), (
        "两条写路给出的拒信不一样：",
        {"B": by_b.get("error"), "table.create": detail.get("reason")})
    assert list(detail.get("missing") or []) == list(by_b.get("missing") or []), detail
    assert st_table.rows("statements") == [], "被拒的这一笔居然进了台账"


# ---------------------------------------------------------------- c) 有来路 ⇒ 放行
def test_c_a_basis_lets_the_table_route_through(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：给 `derived_from`（或 `source_lit_id`）⇒ 表创建这条路照旧落库。

    两条支路各走一遍：承重链支给一个形状合法的 `stmt_id`；文献支先落一条
    literature 行、再把号写进 `source_lit_id`。断言不只是"没被拒"——来路要真的
    出现在盘上那一行里，否则"放行"是空的。
    """
    from conftest import add_literature

    wire_for_secretary(monkeypatch)
    st = _world(tmp_path)
    add_literature(st, S.format_id(0))

    by_lit = _create(st, dict(BASE, source_lit_id=S.format_id(0)))
    assert by_lit.ok is True, (by_lit.data, by_lit.error)
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert str(rows[0].get("source_lit_id") or "") == S.format_id(0), rows[0]

    base_id = str(rows[0]["stmt_id"])
    by_chain = _create(st, dict(BASE, statement_full=BASE["statement_full"] + "（承重链支）",
                                derived_from=[base_id]))
    assert by_chain.ok is True, (by_chain.data, by_chain.error)
    row_chain = next(r for r in st.rows("statements")
                     if str(r.get("stmt_id") or "") != base_id)
    assert list(row_chain.get("derived_from") or []) == [base_id], row_chain


# ---------------------------------------------------------------- d) 两个例外
def test_d_concepts_and_the_numeric_green_channel_are_untouched(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：概念行与普通数值绿通不受这一闸影响（各有各的来路，判据自己短路）。

    - 概念行：来路就是它自己的定义（`OWN_RESULT_BASIS_EXEMPT_KINDS`）；
    - 普通数值绿通：来路是 E 的那一条实验行 —— 载荷里它落成第 1 位
      `numeric="verified"` + 凭据里的实验指针（`bits` 不在 `table.create` 的可路由键
      里，所以这一格只可能由产出侧现算交来）。
    概念行走表创建路径真落库；绿通那一档用秘书写口验证"两格来路都空而第 1 位有
    实验凭据 ⇒ 放行"。
    """
    wire_for_secretary(monkeypatch)
    st = _world(tmp_path)

    # ① 概念行：`kind` 自己就是来路（不要求在载荷里给 derived_from / source_lit_id）。
    concept = dict(BASE, kind="concept", label="稳定范数", self_authored=True,
                   statement_full="概念：图 K(m) 上的稳定范数",
                   quote_reason="概念行：来路是它自己的定义")
    res = _create(st, concept)
    assert res.ok is True, (res.data, res.error)
    rows = st.rows("statements")
    assert [str(r.get("kind") or "") for r in rows] == ["concept"], rows
    assert list(rows[0].get("derived_from") or []) == [], rows[0]
    assert SL.own_result_basis_missing(origin="own_result", kind="concept",
                                       derived_from=[], source_lit_id="") == []

    # ② 普通数值绿通：`origin=own_result`、两格来路都空，而第 1 位有实验凭据。
    bits = EB.bits_of(
        origin="own_result", quote_verified=None, proof=False, kind="conjecture",
        numeric="verified",
        numeric_evidence={"experiment_id": S.format_id(0),
                          "experiments": [S.format_id(0)],
                          "script": "code/exp.py",
                          "entries": [{"script": "code/exp.py", "range": "m<=6",
                                       "n_cases": 12, "n_counterexamples": 0}],
                          "certificate": False})
    sec = SEC.Secretary("B", root=st.root, store=st)
    got = sec.record_statement(
        dict(BASE, statement_full="数值绿通：K(m) 的稳定范数在 m<=6 上取整数值",
             statement_text="稳定范数取整数值",
             quote_reason="E 的普通数值手稿：来路是那一条实验行",
             bits=bits), role="B")
    assert got.get("refused") in ("", None), got
    assert got.get("created") is True, got
    row = next(r for r in st.rows("statements")
               if str(r.get("stmt_id") or "") == str(got["stmt_id"]))
    assert str((row.get("bits") or {}).get("numeric") or "") == "verified", row.get("bits")


# ---------------------------------------------------------------- e) 反真空
def test_e_stubbing_the_secretary_gate_off_lets_the_same_payload_land(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把秘书写口这道闸打桩关掉 ⇒ a 必红（同一份载荷落进台账）。

    打桩打在 a 读的那一格上（`secretary._own_result_basis_refusal`）：关掉之后，
    a 的同一个 payload 会真的建出一行 —— 于是 a 的"码"与"0 行"两条断言都会红。
    这不证明"这一笔本来合法"，只证明 a 的绿确实由这道闸带来，不是"表创建路径
    本来就写不进 statements"。
    """
    wire_for_secretary(monkeypatch)
    assert hasattr(SEC, "_own_result_basis_refusal"), "秘书写口这道闸不在它该在的地方"
    monkeypatch.setattr(SEC, "_own_result_basis_refusal", lambda _body: {}, raising=True)
    st = _world(tmp_path)
    res = _create(st, BASE)
    assert res.ok is True, (res.data, res.error)
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert list(rows[0].get("derived_from") or []) == [], rows[0]
    assert str(rows[0].get("source_lit_id") or "") == "", rows[0]
