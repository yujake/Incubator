# -*- coding: utf-8 -*-
"""C1 / C2（2026-11-05 走查）：能看几层的主体是调用方，不是被看的那一行。

## 这一份守的是什么

| 判据 | 守的那件事 | 改前形态 |
|---|---|---|
| 01 | 非 M 调用方看一行 M 的 task + `depth=5` ⇒ 只回 1 层 | 旧实现 `role = _role_of(task_row)` ⇒ 拿到 5 层 |
| 02 | 脚本/直调路径（没有 `calling_as`）同样只拿 1 层 | 工具层守卫要求 `current_task_id()` 非空，脚本里是空的 |
| 03 | M 调用方照旧按请求的层数 | 不回归 |
| 04 | 生产路径（带 `calling_as`）行为不变 | 不回归 |
| 05 | 反真空：把主体打桩回"被看的行"⇒ 01 当场红 | 同 01 |
| 06 | 没有调用方身份时 fail-closed 成非 M | 旧实现回落到被看那一行 |
| 07 | C2：M 传 `None` = 1 层；"全树"归 `subtree_rows(depth=None)` | docstring 原说"不限/大数"，实现是 1 |

夹具直接复用 `test_parent_can_trace_children._fixture` 的那条 5 层链
（`M(top) -> D(d1) -> D(d2) -> B(b3) -> E(e4)`），不另造一份台账。
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import agenttrace as AT

import test_parent_can_trace_children as TRACE


def _rows(fx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("task_id") or ""): dict(r) for r in fx["st"].rows("tasks")}


def _ids(data: dict[str, Any]) -> set[str]:
    return {str(c.get("task_id") or "") for c in data["children"]}


def _top_row(fx: dict[str, Any]) -> dict[str, Any]:
    return _rows(fx)[fx["top"]]


# ============================================================ 01 主体 = 调用方

def test_01_a_non_conductor_caller_sees_one_layer_whatever_row_it_views(
        tmp_path: pathlib.Path):
    """非 M 调用方看一行 M 的 task + `depth=5` ⇒ 只回 1 层。

    改前红：`clamp_depth` 的 role 取 `_role_of(task_row)`，被看的行是 M ⇒ 放行 5 层
    （d1/d2/b3/e4 全在里面）。
    """
    fx = TRACE._fixture(tmp_path)
    top_row = _top_row(fx)
    assert AT._role_of(top_row) == "M", "夹具前提：被看的那一行真的是 M"

    data = AT.children_with_facts(fx["st"], fx["ws"], top_row,
                                  depth=5, caller_role="D")
    assert _ids(data) == {fx["d1"]}, ("非 M 调用方只许看一层：", _ids(data))
    assert data["depth_requested"] == 5, data["depth_requested"]
    assert data["depth_granted"] == 1, data["depth_granted"]
    assert data["one_layer_only"] is True, data
    assert data["me"]["role"] == "M", "被看的是 M 的行，这一点不许被改写"


# ============================================================ 02 脚本/直调

def test_02_a_script_without_identity_gets_one_layer_from_the_tool(
        tmp_path: pathlib.Path):
    """脚本里 `reg.call(..., task_id=<M 的行>)`（没有 `calling_as`）也只拿 1 层。

    这正是审查报告点名的绕法：工具层 582-589 的守卫只在
    `current_task_id()` 非空时才拒，而脚本里那个号是空的。
    """
    fx = TRACE._fixture(tmp_path)
    res = fx["reg"].call("trace.children", role="D", task_id=fx["top"], depth=5)
    assert res.ok, res.to_dict()
    assert _ids(res.data) == {fx["d1"]}, ("脚本路径只许看一层：", _ids(res.data))
    assert res.data["depth_granted"] == 1, res.data["depth_granted"]
    assert res.data["one_layer_only"] is True, res.data


# ============================================================ 03 M 照旧

def test_03_a_conductor_caller_still_gets_the_depth_it_asked_for(
        tmp_path: pathlib.Path):
    """M 调用方看同一行 + `depth=5` ⇒ 照旧拿到 5 层（d1/d2/b3/e4）。"""
    fx = TRACE._fixture(tmp_path)
    data = AT.children_with_facts(fx["st"], fx["ws"], _top_row(fx),
                                  depth=5, caller_role="M")
    assert _ids(data) == {fx["d1"], fx["d2"], fx["b3"], fx["e4"]}, _ids(data)
    assert data["depth_granted"] == 5, data["depth_granted"]
    assert data["one_layer_only"] is False, data


# ============================================================ 04 生产路径

def test_04_the_production_path_with_calling_as_is_unchanged(
        tmp_path: pathlib.Path):
    """带 `calling_as` 的生产路径：非 M 仍只一层（`depth_requested` 如实保留）。

    注：`trace.children` 的 `roles` 是 `S.ROLES`，M 本来就不在它的工具面上
    （M 看全树用 `conductor.watch`）⇒ 这里只钉非 M 的生产路径；M 的限深语义
    由 03 / 07 的直调判据覆盖。
    """
    fx = TRACE._fixture(tmp_path)
    with TRACE._as(fx["ws"], fx["d2"], "D", fx["d1"], "D"):
        res = fx["reg"].call("trace.children", role="D", depth=3, window=5)
    TRACE._assert_one_layer(res, only_child=fx["b3"], must_not=fx["e4"])
    assert res.data["depth_requested"] == 3, res.data["depth_requested"]


# ============================================================ 05 反真空

def test_05_reverting_the_subject_to_the_viewed_row_makes_01_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """反真空：把主体打桩回"被看的行"⇒ 01 的两条断言当场红。

    打桩点就是 `_depth_subject` —— 它正常路径不读 `task_row`；换成
    `lambda _c, row: _role_of(row)` 就复现旧实现。
    """
    fx = TRACE._fixture(tmp_path)
    top_row = _top_row(fx)
    monkeypatch.setattr(AT, "_depth_subject",
                        lambda _caller, row: AT._role_of(row))
    data = AT.children_with_facts(fx["st"], fx["ws"], top_row,
                                  depth=5, caller_role="D")
    assert data["depth_granted"] == 5, data["depth_granted"]
    assert fx["e4"] in _ids(data), _ids(data)
    with pytest.raises(AssertionError):
        assert _ids(data) == {fx["d1"]} and data["depth_granted"] == 1


# ============================================================ 06 fail-closed

def test_06_no_caller_identity_fails_closed_to_non_conductor(
        tmp_path: pathlib.Path):
    """没有 `caller_role`、也没有 `calling_as` ⇒ 按非 M 处理，不回落到被看的行。"""
    fx = TRACE._fixture(tmp_path)
    data = AT.children_with_facts(fx["st"], fx["ws"], _top_row(fx), depth=5)
    assert data["depth_granted"] == 1, data["depth_granted"]
    assert _ids(data) == {fx["d1"]}, _ids(data)


# ============================================================ 07 C2 语义

def test_07_m_none_is_one_layer_and_full_tree_belongs_to_subtree_rows(
        tmp_path: pathlib.Path):
    """C2：M 传 `None` = 1 层；"不额外截断"的全树由 `subtree_rows(depth=None)` 承担。"""
    fx = TRACE._fixture(tmp_path)
    # 判定的语义：M 的 None 与显式 1 同义（一层视图的缺省），不是"不限"。
    assert AT.clamp_depth("M", None) == 1
    assert AT.clamp_depth("M", None) == AT.clamp_depth("M", 1) == 1
    assert AT.clamp_depth("M", 4) == 4
    assert AT.clamp_depth("D", None) == 1
    # 一层视图里 M 传 None：只给直接下级。
    data = AT.children_with_facts(fx["st"], fx["ws"], _top_row(fx),
                                  depth=None, caller_role="M")
    assert _ids(data) == {fx["d1"]}, _ids(data)
    assert data["depth_granted"] == 1, data["depth_granted"]
    # 全树在 `subtree_rows(depth=None)`（`conductor.watch` 走的那一条）。
    every = AT.subtree_rows(fx["st"].rows("tasks"), fx["top"], depth=None)
    assert {str(r.get("task_id") or "") for r in every} == {
        fx["top"], fx["d1"], fx["d2"], fx["b3"], fx["e4"]}


def test_08_the_clamp_docstring_claims_match_the_implementation():
    """C2-b：docstring 里每条断言都能在实现里找到对应行为（这里钉关键几条）。"""
    doc = AT.clamp_depth.__doc__ or ""
    assert "调用方" in doc, "主体必须写明是调用方"
    assert "None" in doc and "同义" in doc, "M 传 None 的口径必须写明"
    assert "subtree_rows" in doc, "全树归哪里必须写明"
    assert "大数" not in doc, "旧 docstring 的「大数接住」必须消失"
    # 与实现逐条对上：
    assert AT.clamp_depth("M", None) == 1
    assert AT.clamp_depth("D", 9) == 1
    assert AT.clamp_depth("M", 9) == 9
