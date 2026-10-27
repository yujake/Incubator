"""`Store._load` 的读路径缓存（`R-BE4`，2026-10-27 业主批准）—— 三个方向各一条判据。

为什么要有这个文件：`store.py` 是 FC-27 禁 AI 区，而那一次改动（把"每次调用都读盘 +
`json.loads`"换成"按盘上读数命中的进程内缓存"）恰好动了所有读路径。缓存这类东西的
失效形态是静默的：命中了旧值不会报错、只会让读的人拿到一份"看起来合法"的旧表。
所以三件事必须由机器盯着，缺一条都会留下一个静默方向：

1. `test_the_cache_parses_once_per_unchanged_file` —— 盘上没变时只解析一次。
   它守的是收益：这条判据红了说明缓存根本没生效（那就等于改前，白改）。
2. `test_an_external_write_is_visible_immediately` —— 别的进程一写，下一次读立刻
   看见新值。它守的是正确性：缓存键是 `(路径, st_mtime_ns, st_size)`，mtime 变了
   就必须重读。这一条不许用本进程的 `tx` 去写（本进程写完会显式清缓存，那样
   就测不到 mtime 那条路），所以它直接改盘上的表文件 —— 模拟"另一个进程"。
3. `test_mutating_what_rows_returns_does_not_poison_the_cache` —— 就地改交回的行
   （顶层字段）不许污染缓存。顶层副本是 `rows()` / `read()` 的契约；深一层
   （行里嵌套的 list/dict）刻意共享，那是 `_load` docstring 写明的已知边界，本条
   不替它背书（要改嵌套值请整格赋新对象）。

另有一条三态判据：表文件不在盘上（`_stat_key` 返回 `None`）与"空表"是两件事，
前者仍按 `S.empty_table()` 的既有形态返回，不许因为缓存而变成 `StoreError`。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> Store:
    store = Store(tmp_path / "ws")
    store.init()
    return store


def _a_task(task_id: str) -> dict:
    """一行合法的 `tasks`（必填只有 `task_id` / `role` / `action` / `artifacts` / `inputs`）。"""
    return {"task_id": task_id, "role": "D", "action": "probe",
            "artifacts": [], "inputs": []}


def test_the_cache_parses_once_per_unchanged_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """盘上没变 ⇒ 连续 N 次 `rows()` 只解析一次（改前是 N 次）。

    计数打在 `json.loads` 上（`store.py` 的模块级名字），而不打在 `_load` 上：后者
    命中缓存时也会被调用，数它区分不出"命中"与"重解析"。
    """
    store = _ws(tmp_path)
    with store.tx("tasks", actor="probe") as tx:
        tx.upsert("tasks", _a_task("t-000001"))

    calls = {"n": 0}
    real = json.loads

    def counting(text, *a, **kw):
        calls["n"] += 1
        return real(text, *a, **kw)

    monkeypatch.setattr("agentflow.store.json.loads", counting)

    first = store.rows("tasks")
    assert [r["task_id"] for r in first] == ["t-000001"]
    after_first = calls["n"]
    assert after_first >= 1, "第一次读必须真的解析过（否则读数没有对象）"

    for _ in range(5):
        assert store.rows("tasks")[0]["task_id"] == "t-000001"
    assert calls["n"] == after_first, (
        f"盘上没变，5 次读却又解析了 {calls['n'] - after_first} 次 —— 缓存没生效"
        "（改前这里是每次都解析，改后必须只解析一次）")


def test_an_external_write_is_visible_immediately(tmp_path: pathlib.Path) -> None:
    """别的进程写盘（本进程不走 `tx`）⇒ 下一次读立刻看见。

    这一条只走 mtime/size 那条路：本进程 `tx` 写完会显式清缓存，那样测不到键。
    """
    store = _ws(tmp_path)
    with store.tx("tasks", actor="probe") as tx:
        tx.upsert("tasks", _a_task("t-000001"))
    assert [r["task_id"] for r in store.rows("tasks")] == ["t-000001"]

    path = store.data / S.TABLES["tasks"]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"].append(_a_task("t-000002"))
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert [r["task_id"] for r in store.rows("tasks")] == ["t-000001", "t-000002"], (
        "别的进程写完之后仍然读到旧行 —— 缓存键（mtime_ns/size）没有让缓存失效")


def test_the_commit_block_still_reads_a_fresh_snapshot(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tx` 提交块里那次 `before_rows` 必须读新鲜盘（写入期闸的输入）。

    形态：先读一遍把缓存填上，再从外部改盘，然后在同进程开一笔事务写这张表 ——
    提交块的 `before_rows` 读到的是外部那一版（不是缓存里那一版）。
    """
    store = _ws(tmp_path)
    with store.tx("tasks", actor="probe") as tx:
        tx.upsert("tasks", _a_task("t-000001"))
    store.rows("tasks")  # 填缓存

    path = store.data / S.TABLES["tasks"]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"].append({**_a_task("t-000002"), "detail": "外部写入的行"})
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    seen: dict[str, int] = {}
    from agentflow import store as ST

    real = ST._refuse_fake_proof_review

    def spy(root, table, doc_, *, before_rows):
        seen["before"] = len(before_rows or [])
        return real(root, table, doc_, before_rows=before_rows)

    monkeypatch.setattr(ST, "_refuse_fake_proof_review", spy)
    with store.tx("tasks", actor="probe") as tx:
        tx.upsert("tasks", _a_task("t-000003"))
    assert seen.get("before") == 2, (
        f"提交块的 before_rows 读到 {seen.get('before')} 行，而盘上有 2 行 ⇒ "
        "它读到了缓存里的旧快照（写入期闸会因此漏判）")


def test_mutating_what_rows_returns_does_not_poison_the_cache(tmp_path: pathlib.Path) -> None:
    """就地改交回的行（顶层字段）不许影响下一次读。

    深一层（行里嵌套的 list/dict）刻意共享 —— 那是 `_load` docstring 写明的已知边界，
    本条只钉顶层；要改嵌套值请整格赋新对象。
    """
    store = _ws(tmp_path)
    with store.tx("tasks", actor="probe") as tx:
        tx.upsert("tasks", _a_task("t-000001"))

    got = store.rows("tasks")
    got[0]["role"] = "ZZZ"
    got.append(_a_task("t-000009"))
    assert store.rows("tasks")[0]["role"] == "D", "就地改顶层字段污染了缓存"
    assert len(store.rows("tasks")) == 1, "往交回的列表里 append 污染了缓存"

    doc = store.read("tasks")
    doc["rows"][0]["role"] = "YYY"
    assert store.rows("tasks")[0]["role"] == "D", "就地改 read() 交回的 doc 污染了缓存"


def test_a_missing_table_file_is_an_empty_table_not_an_error(tmp_path: pathlib.Path) -> None:
    """表文件不在盘上 ⇒ `S.empty_table()`（三态：不是"读坏了"，也不是缓存命中）。"""
    store = Store(tmp_path / "ws")
    store.init()
    (store.data / S.TABLES["tasks"]["file"]).unlink()
    assert store.rows("tasks") == []
    assert store.read("counters")["counters"] == {}
