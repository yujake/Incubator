# -*- coding: utf-8 -*-
"""证明的"路子"必须回到读者眼前：写侧落 `secretary.PROOF_ROUTES_KEY`，读侧必须有人把它翻出来。

## 这一份补的是哪一根线（`docs/WIRING-AUDIT-2026-10-27.md` 第四节第一行）

审计实测：`secretary.proof_route_of` / `proof_routes_of` 是孤儿 —— 全仓 0 个非测试
调用点。路子由 `Secretary.record_statement` 写进 statements 那一行的 `secretary.PROOF_ROUTES_KEY`
（业主 2026-10-24：「路线写在证明这一层」），写完就再没有人读回来。于是：

    写侧有那句话，读侧没有那一格；模型读得到行，读不到"这份证明走的是哪条路"。

现在接在读侧：`table.get` / `table.list` 的 statements 行各带两格 —— `route`
（第 1 份证明那一句）与 `proof_routes`（`{证明号: 一句话}` 全量），两只都由
`secretary.proof_routes_of` / `proof_route_of` 现算（同一只派生函数，
`table_tools._with_proof_routes`）。

## 三条判据（含反真空）

1. `test_table_get_carries_the_proof_route`：写侧落了路子 ⇒ `table.get` 的那一行里
   读得到（`route` 与 `proof_routes` 都有值）。改前红：这一格根本不存在。
2. `test_table_list_carries_the_proof_route`：`table.list` 的每一行同样带着（两条读侧
   工具共用同一只派生函数 —— 只接一处会让"按 id 取"与"列表取"各说一半）。
3. `test_the_route_cell_is_empty_when_the_writer_writes_nothing`（反真空）：把写侧打桩
   成不写 `secretary.PROOF_ROUTES_KEY` ⇒ 读侧那两格为空。这一条钉的是"那两格真的是从写入的东西
   算出来的"，而不是某个恒真的常量。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import conductor as COND
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary, for_role_wired
from agentflow.store import Store
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

#: 命题正文（判定与登记都要它）；路线由打桩的缝给，判据不依赖真实模型。
FULL = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在且两两共轭。"
LABEL = "Sylow I（存在性）"
PROOF = "证明：由类方程直接得。"
#: 这条路子（写侧会把它洗进 `secretary.PROOF_ROUTES_KEY` 的 `"1"` 那一格）。
ROUTE = "路线二：由类方程直接数，不经过群作用"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


class _Call:
    ok = True
    problem = ""
    detail = ""


class _RouteSeam:
    """打桩的秘书缝：只回一条判定（`route` 那格就是写侧的输入）。"""

    wired = True

    def __init__(self, route: str = ROUTE) -> None:
        self.route = route

    def ask_json(self, prompt: Any, **kw: Any) -> tuple[dict[str, Any], Any]:
        return ({"decision": "different", "same_as": "", "canonical_name": "Sylow I",
                 "route": self.route, "condition": "打桩：条件未读",
                 "conclusion": "打桩：结论未读", "reason": "打桩：恒判 different",
                 "basis": ["打桩：不同"]}, _Call())


def _own() -> dict[str, Any]:
    return {"statement_full": FULL, "statement_text": FULL[:24], "label": LABEL,
            "origin": "own_result", "kind": "conjecture", "proof_text": PROOF,
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _record(st: Store) -> str:
    """走生产写路：`record_statement` 落一行 statements（带 `secretary.PROOF_ROUTES_KEY`）。"""
    sec = for_role_wired("B", root=st.root, store=st, seam=_RouteSeam())
    got = sec.record_statement(_own(), role="B")
    assert got.get("created") is True, got
    assert got.get("proof_route") == ROUTE, got
    return str(got.get("stmt_id") or "")


def _registry(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg


def _as(stmt_id: str, call):
    with COND.calling_as(S.format_id(0), "B"):
        return call()


# ------------------------------------------------------------------ 1 / 2 读侧

def test_table_get_carries_the_proof_route(tmp_path: pathlib.Path) -> None:
    """`table.get(table="statements")` 的那一行带 `route` 与 `proof_routes`。

    改前红：两个键都不存在 —— 路子只活在写侧那个下划线键里，读侧没人翻它。
    """
    st = _ws(tmp_path)
    sid = _record(st)
    reg = _registry(st)
    got = _as(sid, lambda: reg.call("table.get", table="statements", id=sid))
    assert got.ok, (got.error, got.meta)
    data = dict(got.data or {})
    assert data.get("route") == ROUTE, data
    assert data.get("proof_routes") == {"1": ROUTE}, data
    # 写侧那个内部键仍然在（读侧不删它，只是额外给两格）。
    assert data.get(SEC.PROOF_ROUTES_KEY) == {"1": ROUTE}, data


def test_table_list_carries_the_proof_route(tmp_path: pathlib.Path) -> None:
    """`table.list(table="statements")` 的每一行同样带着那两格。"""
    st = _ws(tmp_path)
    sid = _record(st)
    reg = _registry(st)
    got = _as(sid, lambda: reg.call("table.list", table="statements"))
    assert got.ok, (got.error, got.meta)
    rows = [dict(r) for r in (got.data or {}).get("rows") or ()]
    assert len(rows) == 1, rows
    assert rows[0].get("route") == ROUTE, rows[0]
    assert rows[0].get("proof_routes") == {"1": ROUTE}, rows[0]
    # 非 statements 的表不许被这两格污染（派生只挂在那一条表上）。
    other = _as(sid, lambda: reg.call("table.list", table="documents"))
    assert other.ok, other.error
    for row in (other.data or {}).get("rows") or ():
        assert "route" not in row and "proof_routes" not in row, row


# ------------------------------------------------------------------ 3 反真空

def test_the_route_cell_is_empty_when_the_writer_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把写侧打桩成不写 `secretary.PROOF_ROUTES_KEY` ⇒ 读侧那两格为空。

    这一条钉的是"那两格真的是从写入的东西算出来的"：如果它们来自某个恒真的常量
    （或来自行上别的东西），打桩之后仍然会有值 —— 那判据 1 就什么都没在量。
    """
    st = _ws(tmp_path / "nowrite")
    real = Secretary._annotate_proposition

    def without_route(row: dict[str, Any], adj: Any, *, proof_no: int = 1,
                      route: str = "") -> dict[str, Any]:
        """打桩：故意把路线丢掉（写侧"不写"的那一档）。"""
        return real(row, adj, proof_no=proof_no, route="")

    monkeypatch.setattr(Secretary, "_annotate_proposition", staticmethod(without_route))
    sid = _record(st)
    row = next(r for r in st.rows("statements") if str(r.get("stmt_id")) == sid)
    assert not row.get(SEC.PROOF_ROUTES_KEY), ("打桩没生效：写侧仍然落了路线", row)

    reg = _registry(st)
    got = _as(sid, lambda: reg.call("table.get", table="statements", id=sid))
    assert got.ok, got.error
    data = dict(got.data or {})
    assert data.get("route") == "", data
    assert data.get("proof_routes") == {}, data
