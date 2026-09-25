"""`Tx.mark_dirty` 的语义：就地改列表必须显式标脏，否则改动静默丢失。

这是一个真实的静默失败路径：`tx.rows(t)` 返回的是可变列表，调用方可以直接改里面的
dict（`table_tools` 的删除就是这么做的）。这种改动不会经过 `upsert`，
所以没有任何东西把表标成脏 —— 提交时该表被跳过，改动凭空消失，而且不报任何错。

原先 `Tx` 的 docstring 提到过 `mark_dirty`，但方法并不存在，调用方只能去摸 `tx._dirty`
这个私有属性 —— 文档与实现对不上。本文件把这个契约固定下来。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.store import Store, StoreError


def _seed(store: Store, n: int = 2) -> None:
    with store.tx("concepts", actor="test") as tx:
        for i in range(n):
            tx.upsert(
                "concepts",
                S.Concept(
                    concept_id=f"{i:04d}", name=f"c{i}", definition="",
                    created_at=S.now_iso(), updated_at=S.now_iso(),
                ).to_dict(),
            )


def test_inplace_edit_without_mark_dirty_is_lost(store):
    """不标脏 ⇒ 改动丢失。这个用例断言的是当前（危险的）行为，用来证明
    `mark_dirty` 的必要性 —— 一旦将来有人让"就地改列表"自动标脏，本用例会失败，
    那时应当把它改成正面断言（并在 store 里写明语义变更）。"""
    _seed(store)
    with store.tx("concepts", actor="test") as tx:
        tx.rows("concepts")[0]["name"] = "改了但没标脏"

    assert store.rows("concepts")[0]["name"] == "c0", "未标脏的改动不该落盘（当前语义）"


def test_inplace_edit_with_mark_dirty_persists(store):
    """标脏 ⇒ 改动落盘。这是调用方（如 table_tools 的删除）应当使用的路径。"""
    _seed(store)
    with store.tx("concepts", actor="test") as tx:
        tx.rows("concepts")[0]["name"] = "标了脏"
        tx.mark_dirty("concepts")

    assert store.rows("concepts")[0]["name"] == "标了脏"


def test_inplace_delete_rows_then_mark_dirty(store):
    """就地 `del` 一行 + 标脏 ⇒ 真正落盘（删除路径的实际用法）。"""
    _seed(store, 3)
    with store.tx("concepts", actor="test") as tx:
        rows = tx.rows("concepts")
        rows[:] = [r for r in rows if r["concept_id"] != "0001"]
        tx.mark_dirty("concepts")

    assert [r["concept_id"] for r in store.rows("concepts")] == ["0000", "0002"]


def test_mark_dirty_rejects_undeclared_table(store):
    """对事务未声明的表标脏必须报错 —— 否则会"标记成功但实际没锁"，并发下写坏数据。"""
    with pytest.raises(StoreError, match="未声明表"):
        with store.tx("concepts", actor="test") as tx:
            tx.mark_dirty("relations")
