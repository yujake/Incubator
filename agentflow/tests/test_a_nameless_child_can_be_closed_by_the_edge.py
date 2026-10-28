# -*- coding: utf-8 -*-
"""判据：`retire_child(task_id=…)` 的目标没有名册名时，改走认边收口（不再硬拒）。

## 真机（`projects/paper-rewrite-79`，2026-10-29 01:23 `final_refused`）

那 11 个在册节点里 8 个是 M 自己的直接子（父 = t-000001），另 3 个在 t-000036 / t-000029 名下；
它们全都没有名册名。M 逐个 `conductor.retire_child(child_name="t-000016")` 去销，每次都被
「名册里没有这个名字」拦住 ⇒ 收工闸「整棵树都已销号」永远差 11 个。

连锁销号在这里也救不了：级联是"对一个有名册名的子从最深往上销"，而这 8 个是 M 的
直接子、本身没有名字 —— 没有可以起头的那一层。所以必须让"按 task_id 直接销一个无名册名
的已静默节点"这条路走得通：不写销号名单，只写父行的认边落痕（`edge-released:`），
而 `retire_integrity` 读的正是那一格。

## 这一组守什么

1. 正题：无名册名的已静默直接子 ⇒ `retired` + `edge_released`，且 `retire_integrity` 不再把它算在册；
2. 有名册名的照旧走秘书（销号名单里留痕，不许退化成"只认边"）；
3. 还在跑的 ⇒ 照旧拒（这条路不是"什么都能销"）。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "data").mkdir(exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.roster_sink = Secretary("M", root=ws, store=st)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reg.bound_role = "M"
    return st, cond, reg


def _agent(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    ended = None if status in ("pending", "running") else "2026-10-29T01:00:00+08:00"
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"u@{role}",
        "status": status, "outcome": ("ok" if ended else None), "refusal_reason": None,
        "instance": "", "detail": "干完了", "error": None,
        "started_at": "2026-10-29T00:50:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}")


def test_a_nameless_finished_child_is_closed_by_the_edge(tmp_path: pathlib.Path):
    """正题：无名册名的已收口直接子 ⇒ 认边收口，收工闸不再差它。"""
    st, cond, reg = _env(tmp_path)
    top = cond.open_top_level_run("M", "按 task_id 销无名册名的子")
    child = _agent(cond, top)
    with calling_as(top):
        got = dict(reg.call("conductor.retire_child", task_id=child,
                            reason="收工：它没有名册名").data or {})
    assert got.get("retired") is True, got
    assert got.get("edge_released") is True, got
    integrity = cond.retire_integrity(top)
    assert [n["task_id"] for n in (integrity.get("nodes") or [])] == [], integrity.get("nodes")


def test_a_running_nameless_child_is_still_refused(tmp_path: pathlib.Path):
    """反真空：还在跑 ⇒ 照旧拒（这条路不是"什么都能销"）。"""
    st, cond, reg = _env(tmp_path)
    top = cond.open_top_level_run("M", "跑到一半就不许销")
    child = _agent(cond, top, status="running")
    with calling_as(top):
        got = dict(reg.call("conductor.retire_child", task_id=child,
                            reason="试试").data or {})
    assert got.get("retired") is not True, got
