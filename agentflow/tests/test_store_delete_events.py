"""`R-57` 的判据：删除必须进事件流，否则 `rebuild()` 会让删掉的行复活。

## 改前是什么样（`draft/28` §173 的 R-57）

"删一行"只有一条路：把 `tx.rows(table)` 那个列表就地改掉再 `mark_dirty`
（`tools/table_tools.py::table_delete` 就是那样写的）。快照变了，
但 `events.jsonl` 里没有任何痕迹 —— 而重建的唯一输入是事件日志
⇒ 删掉的行在 `rebuild()` 之后回来，而那次重建的每一个计数都"正常"：
`batches_incomplete=0`、`snapshot_rows_not_in_log=0`。
也就是说没有一个读数会告诉读的人"你刚恢复出来的数据比删之前多"。

## 这一组判据守什么

1. 删除留下 `op="delete"` 事件，带被删的整行（审计需要：否则事后只能看到"少了一行"，
   查不出少的是什么）；
2. 重建重放删除 ⇒ 那一行不复活，且 `deletes_replayed` 把它数出来；
3. 同一事务里 upsert/delete 混用 ⇒ 按调用顺序折叠（upsert 后 delete ⇒ 没了；反之 ⇒ 在）；
4. `tool` 层那条路（`table.delete`）也走事件（否则产品路径上 R-57 照旧）；
5. 认不出的 `op` 进 `unknown_ops`（不给"日志里有读不懂的东西"留静默）；
6. 没有删除事件的日志 ⇒ `deletes_replayed=0`、`unknown_ops=[]`（不许误报）。

## S1r 并表（`SCHEMA_VERSION=2`）之后的改动

本文件守的是存储层判据（删除事件 / 重放 / 顺序折叠），而被删的那一行只是
标本。并表把 `concepts` 表真删（概念行住进 `statements`）⇒ 标本换成
`statements` 的一行（`kind="stmt"` / 主键 `stmt_id`），断言一个字都没松：
事件里依旧必须带被删的整行（这里改判 `label` 与 `origin`，与原先判 `name`
同一条不变量 —— 事件里留下的是"被删的那一行长什么样"）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


def _st(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path)
    st.init()
    return st


def _put_stmt(st: Store, label: str) -> str:
    """插一条合法的 `statements` 行（并表之后本文件用的标本）。

    形状刻意与 `schema.Statement.validate` 对齐：`origin` 在受控词表内、
    `statement_full` 非空、`quote_verified` 不是 `True` 时 `quote_reason` 非空。
    """
    with st.tx("statements", actor="test") as tx:
        sid = tx.alloc_id("stmt")
        tx.upsert("statements", {"stmt_id": sid, "origin": "own_result", "kind": "theorem",
                                 "label": label, "statement_full": f"{label} 的命题正文（夹具）",
                                 "quote_verified": None,
                                 "quote_reason": "自产结果（测试夹具）",
                                 "created_at": TS})
    return sid


def _events(st: Store) -> list[dict]:
    return [json.loads(line) for line in st.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _ids(st: Store) -> list[str]:
    return sorted(str(r.get("stmt_id")) for r in st.rows("statements"))


def test_delete_writes_an_event_with_the_whole_row(tmp_path: pathlib.Path):
    """正控①：删除留事件，且事件里带被删的整行与主键（审计面）。

    并表之后标本是 `statements` 的一行；"整行"这条不变量照旧逐字判：
    事件里必须能读出被删那行的字段值（这里取 `label`），而不只是"少了一行"。
    """
    st = _st(tmp_path)
    sid = _put_stmt(st, "谱")
    with st.tx("statements", actor="test") as tx:
        removed = tx.delete("statements", sid)
    assert removed is not None and removed["label"] == "谱"
    deletes = [e for e in _events(st) if e.get("op") == "delete"]
    assert len(deletes) == 1, deletes
    assert deletes[0]["table"] == "statements"
    assert deletes[0]["key"] == sid
    assert (deletes[0].get("row") or {}).get("label") == "谱", "被删的整行必须留在日志里"
    assert _ids(st) == []


def test_rebuild_does_not_resurrect_a_deleted_row(tmp_path: pathlib.Path):
    """正控②（R-57 的本体）：删掉的行在 `rebuild()` 之后不复活，并被计数。"""
    st = _st(tmp_path)
    keep = _put_stmt(st, "区间")
    gone = _put_stmt(st, "谱")
    with st.tx("statements", actor="test") as tx:
        tx.delete("statements", gone)
    assert _ids(st) == [keep]

    res = st.rebuild()
    assert _ids(st) == [keep], f"删掉的行复活了：rebuild ⇒ {_ids(st)}"
    assert res["deletes_replayed"] == 1, res
    assert res["batches_incomplete"] == 0 and res["snapshot_rows_not_in_log"] == 0, res


def test_order_inside_one_transaction_is_the_call_order(tmp_path: pathlib.Path):
    """负控（顺序语义）：同一事务里 upsert 后 delete ⇒ 没了；delete 后 upsert ⇒ 在。"""
    st = _st(tmp_path)
    sid = _put_stmt(st, "谱")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": sid, "origin": "own_result", "kind": "theorem",
                                 "label": "谱（改）", "statement_full": "改后的正文（夹具）",
                                 "quote_verified": None, "quote_reason": "自产结果（测试夹具）",
                                 "created_at": TS})
        tx.delete("statements", sid)
    assert _ids(st) == []
    st.rebuild()
    assert _ids(st) == [], "upsert 之后 delete ⇒ 重建也必须没有它"

    st2 = _st(tmp_path / "b")
    sid2 = _put_stmt(st2, "区间")
    with st2.tx("statements", actor="test") as tx:
        tx.delete("statements", sid2)
        tx.upsert("statements", {"stmt_id": sid2, "origin": "own_result", "kind": "theorem",
                                 "label": "区间（回）", "statement_full": "回填的正文（夹具）",
                                 "quote_verified": None, "quote_reason": "自产结果（测试夹具）",
                                 "created_at": TS})
    st2.rebuild()
    rows = {str(r["stmt_id"]): r for r in st2.rows("statements")}
    assert sid2 in rows and rows[sid2]["label"] == "区间（回）", "delete 之后 upsert ⇒ 重建后必须在"


def test_deleting_a_missing_key_writes_nothing(tmp_path: pathlib.Path):
    """负控（不许无中生有）：删一个不存在的键 ⇒ `None`，且日志里不多一条事件。"""
    st = _st(tmp_path)
    _put_stmt(st, "谱")
    n_before = len(_events(st))
    with st.tx("statements", actor="test") as tx:
        assert tx.delete("statements", "9999") is None
    assert len(_events(st)) == n_before, "没删到东西就不该留下事件"


def test_the_table_delete_tool_also_goes_through_the_event_log(tmp_path: pathlib.Path):
    """正控③（产品路径）：`table.delete` 工具删掉的行在 rebuild 之后不许复活。

    这一格才是 R-57 的真实形态 —— 改之前是它把 `tx.rows()` 就地改掉的。
    """
    from agentflow.tools.base import ToolRegistry
    from agentflow.tools import table_tools

    st = _st(tmp_path)
    sid = _put_stmt(st, "谱")
    reg = ToolRegistry()
    # `store` 与 `actor` 在注册期绑进 handler（工具参数表里只剩数据，见 `register` 的 docstring），
    # 所以调用侧只给 `role` 与数据参数。
    table_tools.register(reg, store=st, actor="test")
    res = reg.call("table.delete", role="A", table="statements", id=sid)
    assert res.ok is True and res.data is True, res.error
    assert _ids(st) == []
    assert any(e.get("op") == "delete" for e in _events(st)), "工具路径也必须留删除事件"
    st.rebuild()
    assert _ids(st) == [], "工具删掉的行在重建之后复活了 ⇒ R-57 没修干净"


def test_an_unknown_op_is_reported_not_silently_ignored(tmp_path: pathlib.Path):
    """负控（三态）：日志里出现一个读不懂的 `op` ⇒ 它必须出现在返回值里。"""
    st = _st(tmp_path)
    _put_stmt(st, "谱")
    with st.events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"seq": 99, "ts": TS, "batch": "probe-batch",
                             "op": "frobnicate", "table": "statements"}, ensure_ascii=False) + "\n")
        fh.write(json.dumps({"seq": 100, "ts": TS, "batch": "probe-batch",
                             "op": "commit", "rows": 1}, ensure_ascii=False) + "\n")
    res = st.rebuild()
    assert res["unknown_ops"] == ["frobnicate"], res


def test_a_log_without_deletes_reports_zero_and_no_false_alarms(tmp_path: pathlib.Path):
    """负控（不许误报）：没有删除事件的日志 ⇒ `deletes_replayed=0` 且 `unknown_ops=[]`。"""
    st = _st(tmp_path)
    _put_stmt(st, "谱")
    _put_stmt(st, "区间")
    res = st.rebuild()
    assert res["deletes_replayed"] == 0 and res["unknown_ops"] == [], res
    assert len(_ids(st)) == 2
