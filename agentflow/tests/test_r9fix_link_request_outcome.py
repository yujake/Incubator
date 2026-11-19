# -*- coding: utf-8 -*-
"""R9FIX · D2：`lit` 回填了 `result_lit_ids`，终局也必须跟着变成 `ok`。

## 改前红（真机 lp-ball-9，`search_requests` r-000001/2/5/7）

四行的 `result_lit_ids` 都非空（`lit.admit_all` 收完 4 条），但 `outcome` 仍是
`no_results`、`last_error` 还留着「命中 N 条、入库 0 条（待裁）」的过期句子。
收工门 R2（检索真的取回）只数 `outcome=ok` 的行 ⇒ 1 条 < 3 条，`acceptance` 红。
根因：`tools/search_tools.py` 的 `_link_request` 只写 ids，不碰 `outcome` /
`last_error`；demo 路径（`demo.py:366-380`）有正确写法，生产路径没有。

## 反真空

把"有文献落库"与"没有文献落库"两条路都钉住：只有真的挂上了一篇的请求才被
翻成 `ok`；别的请求（`request_id=None` / 没挂上）不许被顺手改绿。
"""
from __future__ import annotations

import pathlib

from agentflow.store import Store
from agentflow.tools import build_for_role
from conftest import add_request


def _a_registry(store: Store, root: pathlib.Path):
    reg = build_for_role("A", store=store, workspace_root=root).registry
    reg.bound_role = "A"
    return reg


def _register(reg, **kw):
    args = {"role": "A", "title": "Cube slicing in R^n", "type_code": "J",
            "summary": "Ball 1986", "year": 1986}
    args.update(kw)
    res = reg.call("search.register", **args)
    assert res.ok, res.error
    return res.unwrap()


def _request(store: Store, request_id: str = "r-0001") -> dict:
    return next(dict(r) for r in store.rows("search_requests")
                if str(r.get("request_id")) == request_id)


def test_a_linked_literature_flips_the_request_outcome_to_ok(tmp_path: pathlib.Path):
    """改前：`result_lit_ids=['000000']` 而 `outcome='no_results'`（R2 数不到它）。"""
    root = tmp_path
    store = Store(root)
    store.init()
    add_request(store, "r-0001", done=True,
                last_error="命中 1 条、入库 0 条（待裁）")
    reg = _a_registry(store, root)

    _register(reg, request_id="r-0001")
    row = _request(store)

    assert row["result_lit_ids"] == ["000000"], row
    assert row["outcome"] == "ok", row
    assert row["last_error"] is None, row


def test_duplicate_branch_also_flips_the_requests_outcome(tmp_path: pathlib.Path):
    """判重命中支走的是 `_link_request` 的另一个调用点 —— 同一格必须一起翻。"""
    root = tmp_path
    store = Store(root)
    store.init()
    add_request(store, "r-0001", done=True, last_error="命中 1 条、入库 0 条（待裁）")
    reg = _a_registry(store, root)

    first = _register(reg)                       # 新建（不带 request_id）
    assert first["created"] is True, first
    second = _register(reg, request_id="r-0001")  # 判重命中
    row = _request(store)

    assert second["created"] is False and second["reason"] == "duplicate", second
    assert row["result_lit_ids"] == [first["lit_id"]], row
    assert row["outcome"] == "ok" and row["last_error"] is None, row


def test_a_request_without_linked_literature_keeps_its_no_results(tmp_path: pathlib.Path):
    """反真空：没有文献挂上来的请求不许被"顺手改绿"。"""
    root = tmp_path
    store = Store(root)
    store.init()
    add_request(store, "r-0001", done=True, last_error="真的零命中")
    reg = _a_registry(store, root)

    _register(reg, request_id=None)
    row = _request(store)

    assert row["result_lit_ids"] == [], row
    assert row["outcome"] is None, row
    assert row["last_error"] == "真的零命中", row
