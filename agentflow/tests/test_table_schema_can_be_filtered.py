# -*- coding: utf-8 -*-
"""`table.schema` 必须能只取一张表（缺陷 ⑤）。

## 现场（真机 T4/T5）

`table.schema` 无参调用返回全部 17 张表 = 47070 字节，被上下文预算截断；
于是模型改用"故意写错一个字段名、从 validation 错误里读字段清单"那种笨办法
（33 次失败调用里 15 次是 `table.create`，白烧步数与钱）。

## 现在的口径

* 无参 ⇒ 行为逐字节不变（16 张表，47070 B）；
* `table="statements"` ⇒ 只回那一张（8045 B，1/6 体积）；
* `table="nope"` ⇒ 可读拒信 `unknown_table` ＋ 在册表名（不是"这张表没有字段"）。
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry


@pytest.fixture()
def reg():
    ws = pathlib.Path(tempfile.mkdtemp())
    return build_registry(store=Store(ws), workspace_root=ws).registry


def test_without_argument_every_table_is_still_listed(reg):
    """负控（行为不许变）：无参调用仍是全部在册表。"""
    from agentflow import schema as S

    r = reg.call("table.schema", role="B")
    assert r.ok, r.error
    assert set(r.data["tables"]) == set(S.TABLES), "无参调用的表清单变了"


def test_one_table_can_be_asked_for_alone(reg):
    """正控：`table="statements"` 只回一张，且体积显著小于全量。"""
    full = reg.call("table.schema", role="B")
    one = reg.call("table.schema", role="B", table="statements")
    assert one.ok, one.error
    assert list(one.data["tables"]) == ["statements"]
    size_full = len(json.dumps(full.data, ensure_ascii=False))
    size_one = len(json.dumps(one.data, ensure_ascii=False))
    assert size_one < size_full / 3, (
        f"过滤没起作用：全量 {size_full}B，单表 {size_one}B")


def test_an_unknown_table_is_a_readable_refusal(reg):
    """三态：未知表 ⇒ `unknown_table` ＋ 在册表名（不是空字段表）。"""
    r = reg.call("table.schema", role="B", table="nope")
    assert not r.ok
    # `fail(error, **meta)` ⇒ `ToolResult(False, None, error, meta)`：失败时 `data` 恒为
    # None，`kind` 在 `meta` 里（我在第一次写这条判据时按 `data` 找，找不到 —— 判据
    # 自己暴露了真实返回形状）。
    meta = getattr(r, "meta", None) or {}
    assert str(meta.get("kind")) == "unknown_table", meta
    assert "statements" in str(r.error), "拒信里必须带在册表名，否则调用方没法自纠"
    assert "nope" in str(r.error)
