# -*- coding: utf-8 -*-
"""`review.scan` 这一件工具本身的判据（块 1：工具面 / 形状 / 三条路径）。

## 这一份守什么

块 0（`tests/test_texaudit.py`）守的是"数得对不对"；这一份守"这件工具装得对不对"：
它是 H 的唯一统一入口，所以有两条独立的事实要钉住 ——

1. 它在 H 的默认只读面上（`side_effect="read"`、`roles=("H",)`），且只有 H 拿得到；
2. 它返回的八个键在任何一条路径上都相同（扫成 / 路径被拒 / 一类都没接线）——
   否则调用方得先判 `ok` 才知道能不能读 `counts`，那正是三态纪律要避免的形态。

## 为什么还要钉"它没有写入口"

H 是只读角色，而这一件是新加的：任何人以后想给它加一个"顺手落库"的分支，
这一条会先红。落库通道本批刻意没开（`review.record_finding` 的 kind 词表里没有
这七类，实测 7/7 被参数门拒）—— 所以"只读"在这里不是口号，是这一批的边界。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import texaudit as TEX
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import review_tools as RV


@pytest.fixture()
def registry(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws).registry


def _call(reg, **args):
    return reg.call("review.scan", role="H", **args)


def test_only_h_gets_the_unified_entry(registry) -> None:
    """它只在 H 的面上（统一入口不该顺手发给别的角色）。"""
    owners = [role for role in ("A", "B", "C", "D", "E", "F", "G", "H", "V")
              if "review.scan" in {s.name for s in registry.for_role(role)}]
    assert owners == ["H"], owners
    spec = registry.get("review.scan")
    assert spec.roles == ("H",), spec.roles
    assert spec.side_effect == "read", spec.side_effect


def test_it_is_on_the_default_read_only_surface(registry) -> None:
    """默认注册面（`include_writers` 为假）里就有它，且整张面仍然只有 none/read。"""
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="review-default")
    RV.register(reg, store=None)
    assert "review.scan" in reg.names()
    assert all(s.side_effect in ("none", "read") for s in reg.for_role("H"))


def test_the_kinds_enum_is_the_contract(registry) -> None:
    """`kinds` 的枚举 == `texaudit.SCAN_KINDS`（唯一来源，不在这里抄第二份）。"""
    spec = registry.get("review.scan")
    prop = spec.params["properties"]["kinds"]
    assert list(prop["items"]["enum"]) == list(TEX.SCAN_KINDS), prop["items"]["enum"]
    assert spec.params["required"] == ["kinds"], spec.params["required"]


def test_the_eight_keys_come_back_on_a_real_scan(registry) -> None:
    """正控：真扫一次，八键齐全，且 `findings[]` 的元素是九键。"""
    res = _call(registry, kinds=["text_integrity"], paths=["."])
    assert res.ok, res.error
    assert tuple(sorted(res.data)) == tuple(sorted(TEX.RETURN_KEYS)), sorted(res.data)
    assert set(res.data["counts"]) == {"files", "findings", "by_kind", "by_severity", "facts"}
    for item in res.data["findings"]:
        assert tuple(item) == TEX.FINDING_KEYS, sorted(item)


def test_a_rejected_path_is_not_checked_and_says_why(registry) -> None:
    """三态：越界路径 ⇒ `checked=False` + 理由（不是"零命中"）。"""
    res = _call(registry, kinds=["text_integrity"], paths=["../escape"])
    assert res.ok, res.error
    assert res.data["checked"] is False
    assert any("越出工作区" in str(b["reason"]) for b in res.data["bad"]), res.data["bad"]


def test_a_kind_that_is_not_wired_yet_is_honest(registry) -> None:
    """块 1 的接线面：除 `text_integrity` 外的类如实报"还没接线"，不静默跳过。

    这一条在块 2（把 `_WIRED_KINDS` 扩到七类）之后会自动变成"能跑了" —— 那时
    它守的是另一半：`_WIRED_KINDS` 里那一类的读数必须与 `SCAN_KINDS` 对齐。
    """
    res = _call(registry, kinds=list(TEX.SCAN_KINDS), paths=["out/paper"])
    assert res.ok, res.error
    wired = set(RV._WIRED_KINDS)  # noqa: SLF001 —— 这一条就是钉那个常量的
    unwired = set(TEX.SCAN_KINDS) - wired
    by_kind = {b["kind"] for b in res.data["bad"]}
    for kind in unwired:
        assert kind in by_kind, (kind, res.data["bad"])
        assert "还没接线" in next(b["reason"] for b in res.data["bad"] if b["kind"] == kind)
    for kind in wired:
        assert kind not in {b["kind"] for b in res.data["bad"] if "还没接线" in b["reason"]}, kind


def test_a_missing_project_makes_ledger_match_unchecked(registry) -> None:
    """三态：不给 project ⇒ `ledger_match` 没查成（不是"对得上"），其余类照查。"""
    res = _call(registry, kinds=["ledger_match", "text_integrity"], paths=["."])
    assert res.ok, res.error
    bad_kinds = {b["kind"] for b in res.data["bad"]}
    assert "ledger_match" in bad_kinds, res.data["bad"]


def test_the_summary_points_at_the_seven_kinds(registry) -> None:
    """摘要要让 H 一眼看出"一个入口七类读数"（这是"方便 H 使用"的落点）。"""
    summary = registry.get("review.scan").summary
    assert "机械读数" in summary, summary
    for token in ("kinds", "detail", "bad"):
        assert token in registry.get("review.scan").returns, token
