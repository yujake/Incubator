# -*- coding: utf-8 -*-
"""依赖的第四种来源（我们自己的一条命题）与"多组证明路径"。

业主 2026-10-09 两句：「B走乙。由于B这边出了多依赖写法，C的分析需要做适配」、
「如果证明路径不唯一，可增另一组依赖，实现用二维列表」。

`draft/97` §15.0 的 E2 记着现场事实：`Dependency` 的字段表里此前没有 `source_stmt_id`
（也没有 `path_group`），于是"定理 A 用到定理 B / 用到某个概念"那条边无处安放 ——
承重链在命题之间断掉，而那正是 C 的"最短依赖链"要走的那些边。

## 这一组守什么

1. 正控：一条指着我方命题的边写得进去，且 `path_group` 按外层下标落；
   二维列表 ⇄ 字段的往返可复算（三行 ⇒ 两组：组内 AND、组间 OR）；
2. 负控：指一条不在册的命题 ⇒ 拒且零写入（"依赖闭合"必须核到已入库的行）；
   同时给两个来源 / 组号 0 或负数 / `closed` 却没给来源 ⇒ 各自拒；
3. 反真空：两层声明（`specs/g.py` 的动作参数与工具面 `@tool` 的 schema）都列了这两格
   且类型一致 —— 只有一层列了，参数门与真交下去的值就会分家；
   以及"加了这两格"没有放宽既有规则（`dangling` 仍必须写 `status_reason`）。
"""

from __future__ import annotations

import pathlib

import pytest
from conftest import TS, add_literature, sync_counters
from agentflow import schema as S
from agentflow.tools.doc_tools import register_dependency


def _stmt(store, sid: str, label: str) -> dict:
    row = S.Statement(stmt_id=sid, origin="own_result", kind="theorem", label=label,
                      statement_full=f"设 G 是有限连通图；则 {label} 成立。",
                      proof_text="Proof. ……", quote_reason="自产结果（单测夹具）",
                      status="active", created_at=TS)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _deps(store) -> list[dict]:
    return list(store.rows("dependencies"))


def _groups(store, used_by: str) -> list[list[str]]:
    """按 `path_group` 把边还原成二维列表（`draft/97` §12.1 的读法）。"""
    out: dict[int, list[str]] = {}
    for d in _deps(store):
        if str(d["used_by"]) != used_by:
            continue
        out.setdefault(int(d["path_group"]), []).append(str(d["source_stmt_id"]))
    return [sorted(out[g]) for g in sorted(out)]


# ==================================================== 一、正控

def test_a_dependency_may_point_at_our_own_statement(store):
    """`source_stmt_id` 指的是一条在册命题 ⇒ 边写得进去，组号跟着落。"""
    _stmt(store, "0000", "引理 A")
    row = register_dependency(store, "doc:0001#claim-1", "theorem", "引理 A",
                              source_stmt_id="0000", status="closed", path_group=2)
    assert row["source_stmt_id"] == "0000" and row["path_group"] == 2
    assert row["status"] == "closed" and row["source_lit_id"] is None
    assert row["used_by"] == "doc:0001#claim-1"
    assert len(_deps(store)) == 1


def test_two_path_groups_round_trip_to_a_two_dimensional_list(store):
    """三行 ⇒ 两组（组内 AND、组间 OR），按字段读回来就是那个二维列表。"""
    _stmt(store, "0000", "引理 A")
    _stmt(store, "0001", "引理 B")
    _stmt(store, "0002", "引理 C")
    used_by = "doc:0002#claim-7"
    register_dependency(store, used_by, "theorem", "路径 1 第一步",
                        source_stmt_id="0000", status="closed", path_group=1)
    register_dependency(store, used_by, "theorem", "路径 1 第二步",
                        source_stmt_id="0001", status="closed", path_group=1)
    register_dependency(store, used_by, "theorem", "路径 2（更短）",
                        source_stmt_id="0002", status="closed", path_group=2)
    assert _groups(store, used_by) == [["0000", "0001"], ["0002"]], _deps(store)
    assert len(_deps(store)) == 3, "一行一条边（二维列表落成字段，不是一行两列）"


# ==================================================== 二、负控

def test_a_statement_edge_must_point_at_a_row_in_the_ledger(store):
    """指一条不在册的命题 ⇒ 拒，且零写入（"闭合"必须核到已入库的行）。"""
    with pytest.raises(ValueError) as e:
        register_dependency(store, "doc:0001#claim-1", "theorem", "不存在的引理",
                            source_stmt_id="9999", status="closed")
    assert "statements" in str(e.value) and "9999" in str(e.value), str(e.value)
    assert _deps(store) == [], "被拒的依赖不许留下半行"


def test_only_one_source_end_is_allowed(store):
    """被依赖的那一端最多给一个（给两个就说不清这条边依赖谁）。"""
    add_literature(store, "0000")
    _stmt(store, "0000", "引理 A")
    with pytest.raises(ValueError) as e:
        register_dependency(store, "doc:0001#claim-1", "theorem", "两个来源",
                            source_lit_id="0000", source_stmt_id="0000", status="closed")
    assert "最多给一个" in str(e.value), str(e.value)
    assert _deps(store) == []


def test_the_group_number_must_be_a_positive_integer(store):
    """组号 0 / 负数 ⇒ 拒（"第几组"失去意义）。"""
    for bad in (0, -1, "零"):
        with pytest.raises(ValueError) as e:
            register_dependency(store, "doc:0001#claim-1", "theorem", "组号不对",
                                status="dangling", status_reason="先记一笔", path_group=bad)
        assert "path_group" in str(e.value), (bad, str(e.value))
    assert _deps(store) == []


def test_adding_these_two_fields_did_not_loosen_the_old_rules(store):
    """反真空：`closed` 仍必须给来源；`dangling` 仍必须写 `status_reason`。"""
    with pytest.raises(ValueError) as e:
        register_dependency(store, "doc:0001#claim-1", "theorem", "空头闭合",
                            status="closed", path_group=3)
    assert "必须指向一个已入库来源" in str(e.value), str(e.value)
    with pytest.raises(ValueError) as e:
        register_dependency(store, "doc:0001#claim-1", "theorem", "没写原因",
                            status="dangling", path_group=1)
    assert "status_reason" in str(e.value), str(e.value)
    assert _deps(store) == []


# ==================================================== 三、两层声明都对上（反真空）

def test_both_declaration_layers_name_the_two_new_fields():
    """工具面 schema 与动作声明都列了这两格、类型一致（只列一层 ⇒ 参数门与值分家）。"""
    from agentflow import specs as SPECS
    from agentflow.specs.g import ACTIONS

    spec = next(a for a in ACTIONS if a.action == "register_dependency")
    props = spec.params["properties"]
    assert props["source_stmt_id"] == {"type": "string"}, props["source_stmt_id"]
    assert props["path_group"] == {"type": "integer"}, props["path_group"]

    text = pathlib.Path("src/agentflow/tools/doc_tools.py").read_text(encoding="utf-8")
    assert '"source_stmt_id": {"type": "string"}' in text, "工具面没声明 source_stmt_id"
    assert '"path_group": {"type": "integer"' in text, "工具面没声明 path_group"
    # 反真空：`specs` 包的收表入口确实拿到了这一条（不是读了一个没人用的局部表）
    assert any(a.action == "register_dependency" for a in SPECS.action_table()["G"])
