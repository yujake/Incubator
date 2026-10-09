# -*- coding: utf-8 -*-
"""S1o：`C.proof_chain` —— 一条成果的最短证明依赖链（业主 2026-10-09 两句）。

> 「想想C怎么找最短依赖链？总归得在记录定理和证明时同样把依赖写清，直到找到最根上的
>  依赖（某文献或某无前提依赖的自证定理）为止」
> 「B走乙。由于B这边出了多依赖写法，C的分析需要做适配」

判据（正控 3 / 负控 3 / 反真空 2 + 别名 1）：

- 正控①：两组可选路径（长 2 / 长 1）⇒ `best_group` 取短那组、`groups_total=2`；
- 正控②：无前提自证定理作根（没有边 + `evidence_kind="proof"`）⇒ 那一组 `reached`；
- 正控③：原始概念作根（`kind="concept"` + `proof_text="concept:primitive"`）；
- 负控①：环 ⇒ 只那一组 `cycle`（别的组照给）；
- 负控②："没有边又没有 proof 证据"不许当根 ⇒ 进 `unwritten`（那是"依赖没写"）；
- 负控③：`status="dangling"` 的边 ⇒ 那一组不完整（`reached=False`）；
- 反真空①：`statements`/`dependencies` 读不成 ⇒ `checked=False`（不是"没有依赖"）；
- 反真空②：跨组汇总按节点去重（同一条边写进两组不许把规模读数吹大）；
- 别名：`target` 给别名 ⇒ `matched_by="alias"`。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agentflow import schema as S          # noqa: E402
from agentflow.agent_c import AgentC       # noqa: E402
from agentflow.store import Store          # noqa: E402

TS = "2026-10-09T00:00:00+08:00"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _stmt(st: Store, sid: str, *, label: str = "", kind: str = "theorem",
          evidence: str = "cross_check", proof_text: str = "", aliases=()) -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind=kind,
                      label=label or f"{kind} {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text=proof_text, source_lit_id=None,
                      quote_verified=None, quote_reason="夹具（还没核）",
                      evidence_kind=evidence, aliases=list(aliases),
                      status="active", created_at=TS)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict(), note="stmt")


def _lit(st: Store, lid: str) -> None:
    row = S.Literature(lit_id=lid, title=f"文献 {lid}", type="J", summary="s",
                       path=None, added_at=TS)
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="lit")


def _dep(st: Store, did: str, used_by: str, *, stmt: str = "", exp: str = "",
         lit: str = "", kind: str = "theorem", group: int = 1,
         status: str = "closed", reason: str = "") -> None:
    row = S.Dependency(dep_id=did, used_by=used_by, kind=kind, label="前提",
                       status=status, status_reason=reason,
                       source_stmt_id=stmt or None, source_experiment_id=exp or None,
                       source_lit_id=lit or None, path_group=group, created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")


# ------------------------------------------------------------------ 正控


def test_the_shortest_of_several_paths_wins(tmp_path: pathlib.Path):
    """正控①：两组可选路径（长 2 / 长 1）⇒ `best_group` 取短的那组、`groups_total=2`。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _lit(st, "0009")
    # 路径 2（短）：0001 → lit:0009
    _dep(st, "0001", "stmt:0001", lit="0009", kind="prior_art", group=2)
    # 路径 1（长）：0001 → 0002 → lit:0009
    _dep(st, "0002", "stmt:0001", stmt="0002", group=1)
    _dep(st, "0003", "stmt:0002", lit="0009", kind="prior_art", group=1)
    rep = AgentC(st).proof_chain("0001", k=2)
    assert rep.ok, rep.error
    p = rep.payload
    assert p["groups_total"] == 2 and p["best_group"] == 2, p
    by_group = {g["group"]: g for g in p["groups"]}
    assert by_group[2]["length"] == 1, by_group[2]          # 路径 2：一跳（直达文献）
    assert by_group[1]["length"] == 2, by_group[1]          # 路径 1：两跳（经中间定理）
    assert by_group[1]["reached"] and by_group[2]["reached"], by_group


def test_a_premise_free_proved_theorem_is_a_root(tmp_path: pathlib.Path):
    """正控②：无前提自证定理（没有边 + `evidence_kind="proof"`）⇒ 那一组走到根。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _stmt(st, "0002", evidence="proof", proof_text="Proof. 检查器核过……")
    _dep(st, "0001", "stmt:0001", stmt="0002")
    rep = AgentC(st).proof_chain("0001")
    assert rep.ok and rep.payload["best_group"] == 1, rep.payload
    assert rep.payload["groups"][0]["reached"] is True, rep.payload["groups"]


def test_a_primitive_concept_is_a_root(tmp_path: pathlib.Path):
    """正控③：原始概念（`kind="concept"` + `proof_text="concept:primitive"`）也是根。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _stmt(st, "0002", kind="concept", proof_text="concept:primitive")
    _dep(st, "0001", "stmt:0001", stmt="0002", kind="definition")
    rep = AgentC(st).proof_chain("0001")
    assert rep.payload["groups"][0]["reached"] is True, rep.payload


# ------------------------------------------------------------------ 负控


def test_a_cycle_marks_only_that_group(tmp_path: pathlib.Path):
    """负控①：环 ⇒ 只那一组 `cycle`；另一组（到文献）照给。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _stmt(st, "0002")
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", stmt="0002", group=1)
    _dep(st, "0002", "stmt:0002", stmt="0001", group=1)      # 环
    _dep(st, "0003", "stmt:0001", lit="0009", kind="prior_art", group=2)
    rep = AgentC(st).proof_chain("0001")
    groups = {g["group"]: g for g in rep.payload["groups"]}
    assert groups[1]["cycle"] is True and groups[1]["reached"] is False, groups[1]
    assert groups[2]["reached"] is True, groups[2]
    assert rep.payload["best_group"] == 2, rep.payload


def test_a_missing_dependency_is_not_a_root(tmp_path: pathlib.Path):
    """负控②：没有边、也没有 proof 证据 ⇒ 不许当根（那是"依赖没写"）。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _stmt(st, "0002", evidence="cross_check")               # 无边 + 非 proof
    _dep(st, "0001", "stmt:0001", stmt="0002")
    rep = AgentC(st).proof_chain("0001")
    g = rep.payload["groups"][0]
    assert g["reached"] is False and "stmt:0002" in g["unwritten"], g
    assert any("没有边" in h["why"] for h in g["hops"] if h["status"] == "unwritten"), g
    assert rep.payload["best_group"] is None, rep.payload


def test_a_dangling_edge_makes_that_group_incomplete(tmp_path: pathlib.Path):
    """负控③：`dangling` 边 ⇒ 那一组不完整（不算到根）。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _dep(st, "0001", "stmt:0001", status="dangling", reason="来源还没定")
    rep = AgentC(st).proof_chain("0001")
    assert rep.payload["groups"][0]["reached"] is False, rep.payload


# ------------------------------------------------------------------ 反真空


def test_an_unreadable_ledger_is_not_an_empty_graph(tmp_path: pathlib.Path):
    """反真空①：表读不成 ⇒ `checked=False`（不是"这条成果没有依赖"）。"""
    class _Boom:
        def rows(self, table):
            raise RuntimeError("盘读不成")

    rep = AgentC(_Boom()).proof_chain("0001")
    assert rep.ok is False, rep.to_dict()
    assert rep.payload["checked"] is False, rep.payload
    assert "读不成" in rep.summary, rep.summary


def test_cross_group_totals_deduplicate_nodes(tmp_path: pathlib.Path):
    """反真空②：跨组汇总按节点去重 —— 同一条边写进两组不许把规模读数吹大。"""
    st = _store(tmp_path)
    _stmt(st, "0001")
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", lit="0009", kind="prior_art", group=1)
    _dep(st, "0002", "stmt:0001", lit="0009", kind="prior_art", group=2)   # 同一个叶子
    rep = AgentC(st).proof_chain("0001")
    p = rep.payload
    assert p["groups_total"] == 2, p
    # 两组的 hops 加起来是 2 条，但去重之后的节点只有一个（`lit:0009`）
    assert sum(len(g["hops"]) for g in p["groups"]) == 2, p["groups"]
    assert p["unique_nodes"] == 1, p


def test_an_alias_hits_the_same_row_and_says_so(tmp_path: pathlib.Path):
    """别名（D10′ 的乙档）：`target` 给别名也能命中，读数里写明 `matched_by`。"""
    st = _store(tmp_path)
    _stmt(st, "0001", label="Moore bound M(k, g)", aliases=["M(k,g)"])
    _lit(st, "0009")
    _dep(st, "0001", "stmt:0001", lit="0009", kind="prior_art")
    rep = AgentC(st).proof_chain("M(k,g)")
    assert rep.payload["matched_by"] == "alias", rep.payload
    assert rep.payload["node"]["stmt_id"] == "0001", rep.payload
