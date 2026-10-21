# -*- coding: utf-8 -*-
"""`created_by` 必须记真实作者，不能落成 schema 的 per-table 默认值（缺陷 ⑩）。

## 现场（真机 `projects/t5f`，T5 那趟）

`data/conjectures.json` 里那条猜想的 `created_by` 是 `agent-F`，
而它其实是 D 写的（`runs/D-*.json` 里有那一步 `table.create`）。
`created_by: "agent-F"` 是 `schema.Conjecture` 的字段默认值，不是作者证据。

## 现在的口径（`store.Tx.upsert`）

行里 `created_by` 缺省/空白 ⇒ 用本次事务的 `actor` 盖章；
显式给了就保留（调用方的声明不许被覆盖）。
"""
from __future__ import annotations

import pytest

from agentflow.store import Store


@pytest.fixture()
def st(tmp_path):
    store = Store(tmp_path / "ws")
    store.init()
    return store


def _write(st: Store, cid: str, actor: str, created_by: str | None = None) -> None:
    row = {"conjecture_id": cid, "statement": f"断言 {cid}",
           # 判据自己要求的两格（错误消息里逐字点名过）：来源必须可追 ＋ 必须可检验
           "origin": "gap", "testable": "枚举 n<=6 检查是否存在反例"}
    if created_by is not None:
        row["created_by"] = created_by
    with st.tx("conjectures", actor=actor) as tx:
        tx.upsert("conjectures", row)


def _author(st: Store, cid: str) -> str:
    return str(next(r for r in st.rows("conjectures")
                    if str(r.get("conjecture_id")) == cid).get("created_by"))


def test_created_by_defaults_to_the_real_actor(st: Store):
    """正控：不传 `created_by` ⇒ 记成写它的那个 actor（不是 `agent-F`）。"""
    _write(st, "000000", "agent-D")
    assert _author(st, "000000") == "agent-D"


def test_an_explicit_created_by_is_preserved(st: Store):
    """负控：显式给了 `created_by` ⇒ 原样保留，不许被 actor 覆盖。"""
    _write(st, "000001", "agent-A", created_by="agent-F")
    assert _author(st, "000001") == "agent-F"


def test_a_blank_created_by_counts_as_missing(st: Store):
    """边界：空白串等同缺省 ⇒ 按 actor 盖章。"""
    _write(st, "000002", "agent-C", created_by="   ")
    assert _author(st, "000002") == "agent-C"
