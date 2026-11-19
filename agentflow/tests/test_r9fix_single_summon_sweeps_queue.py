# -*- coding: utf-8 -*-
"""R9FIX · D3：主控改走单件 `conductor.summon` 时，待认领队列也要被扫到。

## 改前红（真机 lp-ball-9，08:53:39，`r-000009`）

D 提交了一条检索请求（`submitted_by=agent-D`、`attempts=0`、`claimed_by=None`）。
M 在初始批次之后一直用单件 `conductor.summon` 派活（09:11 / 09:14 / 09:19 三次），
而扫队只挂在 `run_plan` / `summon_many` 与顶趟收尾上 ⇒ 这一条到收工都没人认领，
收工门 R11（请求闭环）红。

## 判据

1. M 的单件派活之前要扫一次队列：待认领请求 ⇒ 出现 `consume:<rid>` 的 A 行；
2. 反真空（角色）：子角色（F）的单件派活不替 M 收研究链的队列；
3. 反真空（空队）：没有待认领请求时不多派一趟 A。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, calling_as
from agentflow.store import Store
from conftest import add_request


class _FakeA:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_once(self) -> dict:
        self.calls.append("run_once")
        return {"outcome": "ok"}


class _FakeE:
    def list_experiments(self) -> dict:
        return {"experiments": [], "count": 0}


def _wired(tmp_path: pathlib.Path):
    store = Store(tmp_path)
    store.init()
    a = _FakeA()
    c = Conductor(store, registry={"A": ("object", a), "E": ("object", _FakeE())})
    root = c.open_top_level_run("M", "r9fix-d3")
    return store, c, a, str(root)


def _consume_rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("tasks")
            if str(r.get("input_key") or "").startswith("consume:")]


def test_a_single_m_summon_sweeps_the_pending_search_queue(tmp_path: pathlib.Path):
    """改前：`r-0001` 一直 `attempts=0`，`tasks` 里没有 `consume:r-0001`。"""
    store, c, a, root = _wired(tmp_path)
    add_request(store, "r-0001")

    with calling_as(root, "M"):
        got = c.summon("E", "list_experiments", {})

    assert got.status == "done", got.to_dict()
    assert a.calls == ["run_once"], a.calls
    rows = _consume_rows(store)
    assert [r["input_key"] for r in rows] == ["consume:r-0001"], rows
    assert rows[0]["role"] == "A" and rows[0]["status"] == "done", rows


def test_a_childs_single_summon_does_not_sweep_the_conductors_queue(tmp_path: pathlib.Path):
    """反真空：F 派 V 的单件召唤不替 M 收研究链队列。"""
    store, c, a, _root = _wired(tmp_path)
    add_request(store, "r-0001")

    with calling_as("t-000099", "F"):
        c.summon("E", "list_experiments", {})

    assert a.calls == [], a.calls
    assert _consume_rows(store) == [], _consume_rows(store)


def test_an_empty_queue_does_not_add_a_spurious_a_run(tmp_path: pathlib.Path):
    """反真空：没有待认领请求 ⇒ 不多派一趟 A（省一次真机模型调用）。"""
    store, c, a, root = _wired(tmp_path)

    with calling_as(root, "M"):
        c.summon("E", "list_experiments", {})

    assert a.calls == [], a.calls
    assert _consume_rows(store) == [], _consume_rows(store)
