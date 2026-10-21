# -*- coding: utf-8 -*-
"""已登记但没立项的猜想，必须在主控看得见的看板上（T5 第 2 趟真机读数驱动）。

## 现场

第 2 趟 T5：`conjectures` 有 1 行（D 登记，`status=proposed`），`attack_plans` 0 行。
查轨迹：D 那趟 7 步只调了 `attack.list_plans`，从没开计划；而 D 的手册已经逐字写着
"登记完猜想请接着把这一腿开出去"（还自己记着上一趟也是 0）⇒ "再补说明"这条路的无效已被证伪。

## 修法

`Conductor.board_view` 把"`status=proposed` 且没有对应计划"的猜想亮成板项
（`kind='pending_attack'`，`pending_attack_count`），只亮出来、不点名动作 ——
要不要开由派活的那一层决定（守"主控只派活"）。

这一组钉两态：有 ⇒ 亮；已立项 ⇒ 消失（不许长期挂着假待办）。
"""

from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor
from agentflow.store import Store

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "000000", "statement": "探针猜想",
                                  "question": "q", "form": "universal",
                                  "status": "proposed", "origin": "gap",
                                  "testable": True, "notes": "", "experiment_ids": []})
    return st


def test_a_conjecture_without_a_plan_shows_up(tmp_path: pathlib.Path) -> None:
    """正控：登记了、没立项 ⇒ 板上有这一项。"""
    st = _store(tmp_path)
    view = Conductor(store=st).board_view(limit=20)
    assert view.get("pending_attack_count") == 1, view
    kinds = [str(r.get("kind") or "") for r in (view.get("open_items") or [])]
    assert "pending_attack" in kinds, kinds


def test_the_item_disappears_once_a_plan_exists(tmp_path: pathlib.Path) -> None:
    """负控：已经有计划 ⇒ 待办消失（不许长期挂着假待办）。"""
    st = _store(tmp_path)
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", {"plan_id": "000000", "problem_key": "000000",
                                   "problem": "p", "conjecture_id": "000000",
                                   "status": "attacking", "budget": BUDGET,
                                   "subgoals": []})
    view = Conductor(store=st).board_view(limit=20)
    assert view.get("pending_attack_count") is None, view
