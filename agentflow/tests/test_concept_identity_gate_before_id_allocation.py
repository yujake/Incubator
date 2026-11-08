# -*- coding: utf-8 -*-
"""判据：概念直写口（`conceptrows.upsert` / `agent_b.run_once`）在发号之前过同一性闸。

## 后门是什么（2026-11-08，D2）

`Secretary.write_concept_row` 会算概念同一性，但它的调用方在调用它之前就
`tx.alloc_id(...)` 发号了。于是"判不了就拒"落在那一层只有两种坏形态：
- 不写 ⇒ 号已发、行没建 ⇒ `verify` 的 `id_gap`（空洞）；
- 放过 ⇒ 概念轴有个后门（同一个概念照样落第二行）。

修法：`secretary.concept_identity_gate(tx, *, label, full)` 在发号之前判（纯读：
`same_concept` 的唯一调用点，零模型调用）。判不了 ⇒ `checked=False`、一个号都不发。

## 钉什么

| 条 | 它要证明的事 |
|---|---|
| a | 闸本体：在册 0 条可比行 ⇒ different；有"抽不出定义项"的行 ⇒ `checked=False` |
| b | `CR.upsert` 判不了 ⇒ `checked=False`、0 新行、counters 不动（无 id_gap） |
| c | 正控：判得了 different（含第一条）⇒ 照常发号建行；第一条概念能登记进来 |
| d | `agent_b/run_once.resolve_concept` 的闸在 `alloc_id("stmt")` 之前（源码顺序） |
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import conceptrows as CR
from agentflow import secretary as SEC
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _counter(st: Store, kind: str = "stmt") -> int:
    path = pathlib.Path(st.root) / "data" / "counters.json"
    return int(((json.loads(path.read_text(encoding="utf-8")).get("counters") or {})
                .get(kind, 0)))


def test_a_gate_judges_without_writing(tmp_path: pathlib.Path) -> None:
    """a：闸本体只回判词（same / different / 没判成），不写盘、不发号。"""
    st = _ws(tmp_path)
    # 在册 0 条 ⇒ "没有同一个概念"判得出来。
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        empty = SEC.concept_identity_gate(tx, label="有限维李代数",
                                          full="概念（有限维李代数）：dim < ∞。")
    assert empty["checked"] is True and empty["state"] == "different", empty
    first = CR.upsert(st, label="概念", definition="设 X 是一个集合。")
    assert first.get("checked") is True, first
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        unjudged = SEC.concept_identity_gate(tx, label="概念",
                                             full="设 Y 是一个拓扑空间。")
    assert unjudged["checked"] is False and unjudged["state"] == "", unjudged
    assert "没判成" in str(unjudged.get("reason") or ""), unjudged
    # 闸本身一个字节都没写：行数与 counters 都没动。
    assert len(_rows(st)) == 1, _rows(st)
    assert _counter(st) == 1, _counter(st)


def test_b_upsert_refuses_before_id_allocation(tmp_path: pathlib.Path) -> None:
    """b（负控）：`CR.upsert` 判不了 ⇒ checked=False、0 新行、counters 不动。"""
    st = _ws(tmp_path)
    first = CR.upsert(st, label="概念", definition="设 X 是一个集合。")
    assert first.get("checked") is True, first
    before_rows, before_count = len(_rows(st)), _counter(st)
    refused = CR.upsert(st, label="概念", definition="设 Y 是一个拓扑空间。")
    assert refused.get("checked") is False, refused
    assert refused.get("stmt_id") == "", refused
    assert "没判成" in str(refused.get("reason") or ""), refused
    # 改法必须可读（主笔 2026-11-08）。
    assert "改法" in str(refused.get("reason") or "") or "定义项" in str(refused.get("reason") or ""), refused
    assert len(_rows(st)) == before_rows, _rows(st)
    assert _counter(st) == before_count, (_counter(st), before_count)


def test_c_different_concepts_still_get_their_rows(tmp_path: pathlib.Path) -> None:
    """c（正控）：判得了 different（含在册 0 条）⇒ 照常发号建行，不是一律拒。"""
    st = _ws(tmp_path)
    first = CR.upsert(st, label="有限维李代数",
                      definition="概念（有限维李代数）：dim_K g < ∞。")
    assert first.get("checked") is True and first.get("stmt_id"), first
    second = CR.upsert(st, label="幂零李代数",
                       definition="概念（幂零李代数）：降中心列在有限步终止。")
    assert second.get("checked") is True and second.get("stmt_id"), second
    assert str(second["stmt_id"]) != str(first["stmt_id"]), (first, second)
    assert len(_rows(st)) == 2, [r.get("stmt_id") for r in _rows(st)]


def test_d_run_once_gates_before_allocating() -> None:
    """d：`agent_b/run_once.resolve_concept` 的闸在 `tx.alloc_id("stmt")` 之前。

    这一条是源码顺序判据（那个函数是闭包内定义的，单测拿不到它的对象）：谁把闸
    挪到发号之后（后门就回来了），这一条当场红。
    """
    text = (REPO / "src" / "agentflow" / "agent_b" / "run_once.py").read_text(encoding="utf-8")
    gate_at = text.find("concept_identity_gate")
    alloc_at = text.find('cid = tx.alloc_id("stmt")')
    assert gate_at >= 0, "run_once 里找不到 concept_identity_gate 调用 ⇒ 后门回来了"
    assert alloc_at >= 0, "run_once 里找不到 cid = tx.alloc_id(\"stmt\")"
    assert gate_at < alloc_at, (
        "run_once 的同一性闸在发号之后（会留 id_gap 或放过）⇒ 先判后分号被破坏")
    assert '"stage": "concept_identity"' in text, "闸拒绝时没有落逐条读数"
