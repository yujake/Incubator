# -*- coding: utf-8 -*-
"""R9FIX · D1：`conductor.closing` 的义务对账必须真的跑（不是 NameError 被吞）。

## 改前红（真机 lp-ball-9，09:21:12 L2357 / 09:46:34 L2760）

两次 `conductor.closing` 的 `readings.v_obligations` 都是：

    {"checked": false,
     "reason": "义务对账没跑成（NameError: name 'root' is not defined）
                ⇒ 不是「没有漏开的义务」"}

根因在 `tools/conductor_tools.py` 的 `conductor_closing`：它把不存在的局部名
`root` 传给了 `obligations.reconcile`，而那个 `except Exception` 又把 NameError
吞成一条 `checked=false` 读数 —— 于是「三族义务对账」这一格在这一趟里一次都没跑过，
却长得像「跑了、没查成」。

## 这一条判据守什么

1. 正常路径（有 store / 有会话）⇒ `checked=True`（对账真的跑了）；
2. 反真空：返回值里不许出现 `NameError`；把 `_OBL.reconcile` 打桩成"被调用过"，
   证明 `checked=True` 不是靠"空表默认值"蒙出来的。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import sessions as SS
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry


def _wired(tmp_path: pathlib.Path):
    store = Store(tmp_path)
    store.init()
    SS.append(tmp_path, {"kind": "agent_run_start", "role": "M",
                         "task_id": "t-000001"}, sid="s1")
    c = Conductor(store, registry={})
    reg = build_registry(store=store, conductor=c,
                         session_root=str(tmp_path), sid="s1").registry
    return store, c, reg


def _close(reg):
    res = reg.call("conductor.closing", role="M", project_dir=".",
                   goal="r9fix-d1", goal_met=True, basis="判据")
    assert res.ok, res.error
    return res.unwrap()


def test_closing_obligations_read_check_runs_instead_of_nameerror(tmp_path: pathlib.Path):
    """改前：`checked=False` + `NameError: name 'root' is not defined`。"""
    _store, _c, reg = _wired(tmp_path)

    got = _close(reg)
    reading = dict((got.get("readings") or {}).get("v_obligations") or {})

    assert "NameError" not in str(reading.get("reason") or ""), reading
    assert reading.get("checked") is True, reading
    # 反真空：这一格不是"没东西可对账"的默认值 —— 空工作区也要给出 checked=True，
    # 而且 `caller` 真的标着这次调用（reconcile 确实被走到）。
    assert reading.get("caller") == "conductor.closing", reading
    assert reading.get("left") == [] and reading.get("problems") == [], reading


def test_closing_obligations_delegates_to_the_single_reconcile(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """反真空：`checked=True` 必须来自 `obligations.reconcile` 真被调用。"""
    from agentflow import obligations as OBL

    seen: list[dict] = []

    def fake_reconcile(**kwargs):
        seen.append(dict(kwargs))
        return {"checked": True, "closed": [], "expired": [], "left": [],
                "problems": [], "reason": "stubbed"}

    monkeypatch.setattr(OBL, "reconcile", fake_reconcile)
    _store, _c, reg = _wired(tmp_path)
    got = _close(reg)
    reading = dict((got.get("readings") or {}).get("v_obligations") or {})

    assert reading.get("checked") is True, reading
    assert reading.get("reason") == "stubbed", reading
    assert len(seen) == 1, seen
    # 工作区根不是空串（空串在 reconcile 里会退回 store.root；这一条钉的是
    # 调用方真的给了根，而不是靠默认值）。
    assert str(seen[0].get("root") or "") == str(tmp_path), seen[0]
