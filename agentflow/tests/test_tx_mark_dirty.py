"""`Tx.mark_dirty` 的语义：就地改列表必须显式标脏，否则改动静默丢失。

这是一个真实的静默失败路径：`tx.rows(t)` 返回的是可变列表，调用方可以直接改里面的
dict。这种改动不会经过 `upsert`，所以没有任何东西把表标成脏 —— 提交时该表被跳过，
改动凭空消失，而且不报任何错。

原先 `Tx` 的 docstring 提到过 `mark_dirty`，但方法并不存在，调用方只能去摸 `tx._dirty`
这个私有属性 —— 文档与实现对不上。本文件把这个契约固定下来。

§176 更正一处过期表述：本节原文说"`table_tools` 的删除就是这么做的"，
而 §176 之后产品路径上的删除走 `Tx.delete`（`op="delete"` 进事件流、可被重放，
见 `tests/test_store_delete_events.py`）—— 就地改列表仍然是被允许的写法，
但它不再是删除的产品用法，只是这个契约本身覆盖的形态之一。
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
    """标脏 ⇒ 改动落盘。就地改列表（改字段值）时这是必须显式写上的那一步。"""
    _seed(store)
    with store.tx("concepts", actor="test") as tx:
        tx.rows("concepts")[0]["name"] = "标了脏"
        tx.mark_dirty("concepts")

    assert store.rows("concepts")[0]["name"] == "标了脏"


def test_inplace_delete_rows_then_mark_dirty(store):
    """就地 `del` 一行 + 标脏 ⇒ 快照确实变了。

    这一条恰好是 `R-57` 的反面教材：快照变了、但事件流里没有痕迹 ⇒
    `store.rebuild()` 之后这一行会复活（§176 的注入负控实测过这条路径）。
    它留在这里是作为 `mark_dirty` 的语义判据（"就地改 + 标脏 ⇒ 落盘"），
    不是"删除应当这么写"的示范 —— 产品路径上的删除必须用 `Tx.delete`。
    """
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
