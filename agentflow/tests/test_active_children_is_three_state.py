# -*- coding: utf-8 -*-
"""S1h：两态快照的三态返回 + 消边标记的幂等（`draft/95` 排期第三批，`draft/92` §3.1/§3.3）。

## 这一批补的是"判据要的两种量"里缺的那一半

业主 T22 的退役算法（`draft/90` §1.9）要问两件事：这个子还在不在跑、
这条边父认过没有。前者的读侧今天只有 `_in_flight_children_of`（只给"活跃"那一档，
没有三态、也没有"在等待"），后者根本不存在（没有任何"消边已经记过"的落痕）。

## 本文件钉住五件事

1. 正控（两态快照）：`active_children` 给"活跃 / 在等待"两档，且只数代理行；
2. 负控（两轴）：工作项（板项）不进这张快照 —— 它们是 `open_items_of` 的事；
3. 反真空（三态）：读不成 ⇒ `checked=False` + `reason`，不许折成空表
   （那会让"没查成"被读成"名下没有子代理"从而误退役，`draft/90` E9）；
4. 正控（幂等）：同一 `(子代号, 第几次)` 只落一笔；不同"第几次"各落各的；
5. 负控（三条结构判据）：还在跑的子不许被记消边；工作项不许被记；不是这个父的
   子不许被记 —— 三条都必须零写入（判据不过时盘上不许出现半份落痕）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({}))


def _child(cond: Conductor, parent: str, *, role: str = "A", status: str = "running",
           key: str = "s1h@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")


def _inputs(st: Store, tid: str) -> list[str]:
    row = next(r for r in st.rows("tasks") if str(r.get("task_id")) == tid)
    return [str(x) for x in (row.get("inputs") or [])]


def test_active_children_gives_the_two_states_and_only_agents(tmp_path: pathlib.Path):
    """正控：两档状态 + 只数代理行（工作项不进这张快照）。

    改前必红：`active_children` 不存在（当时只有 `_in_flight_children_of`，
    它只给"活跃"那一档，且没有三态）。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    running = _child(cond, parent, role="A", status="running", key="s1h@a")
    waiting = _child(cond, parent, role="D", status="done", key="s1h@d")
    item = cond.open_item(kind="delegation", role="A", expects="work", action="run_once",
                          summary="派给 A 的活", called_by="M", parent_task_id=parent,
                          depth=2, input_key="s1h@item")

    got = cond.active_children(parent)
    assert got["checked"] is True and got["reason"] == "", got
    rows = {r["task_id"]: r for r in got["rows"]}
    assert set(rows) == {running, waiting}, ("只数代理行（工作项不许进）", got["rows"])
    assert item not in rows, got["rows"]
    assert rows[running]["state"] == "活跃", rows[running]
    assert rows[running]["role"] == "A", rows[running]
    assert rows[waiting]["state"] == "在等待", rows[waiting]
    assert rows[waiting]["role"] == "D", rows[waiting]


def test_active_children_is_three_state_on_read_failure(tmp_path: pathlib.Path, monkeypatch):
    """反真空：读不成 ⇒ `checked=False` + `reason`（不许返回空表冒充"名下没有子代理"）。

    为什么这条必须有：调用方（退役那一路）拿 `rows == []` 会判"名下没有活 ⇒ 可以退役"，
    而真相是"我没读到台账" —— 那会把一个正在带三个子的父退役掉。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")

    def boom() -> Any:
        raise RuntimeError("注入的台账故障")

    monkeypatch.setattr(cond, "_tasks", boom)
    got = cond.active_children(parent)
    assert got["checked"] is False, got
    assert "RuntimeError" in got["reason"] and "注入" in got["reason"], got
    assert got["rows"] == [], got


def test_note_edge_release_is_idempotent_per_attempt(tmp_path: pathlib.Path):
    """正控（幂等）：同一 `(子, 第几次)` 只一笔；换一档"第几次"各落各的。"""
    st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, status="done", key="s1h@done")

    mark, why = cond.note_edge_release(parent, child_task_id=child, attempt=1)
    assert mark == f"edge-released:{child}#1" and why == "", (mark, why)
    assert mark in _inputs(st, parent), _inputs(st, parent)

    again, why2 = cond.note_edge_release(parent, child_task_id=child, attempt=1)
    assert again == "" and "已经记过" in why2, (again, why2)
    assert _inputs(st, parent).count(mark) == 1, ("不许写第二份", _inputs(st, parent))

    second, why3 = cond.note_edge_release(parent, child_task_id=child, attempt=2)
    assert second == f"edge-released:{child}#2" and why3 == "", (second, why3)
    got = cond.released_edges(parent)
    assert got["checked"] is True, got
    assert got["edges"] == [{"child_task_id": child, "attempt": 1},
                            {"child_task_id": child, "attempt": 2}], got["edges"]


def test_a_running_child_cannot_be_marked_released(tmp_path: pathlib.Path):
    """负控（结构判据一）：还在跑的子不许被记消边，且零写入。

    与业主 §1.9 第①支对齐：A1 活跃 ⇒ 先把它的最近报告端给父，不退役。
    """
    st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, status="running", key="s1h@run")
    before = list(_inputs(st, parent))

    mark, why = cond.note_edge_release(parent, child_task_id=child, attempt=1)
    assert mark == "" and "还在跑" in why, (mark, why)
    assert _inputs(st, parent) == before, ("判据不过 ⇒ 零写入", _inputs(st, parent))


def test_a_work_item_cannot_be_marked_released(tmp_path: pathlib.Path):
    """负控（结构判据二）：工作项不是代理 ⇒ 不许被记消边（两轴分开）。"""
    st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    item = cond.open_item(kind="notice", role="A", expects="ack", summary="子代理已收工",
                          called_by="A", parent_task_id=parent, depth=2, input_key="s1h@n")
    before = list(_inputs(st, parent))

    mark, why = cond.note_edge_release(parent, child_task_id=item, attempt=1)
    assert mark == "" and "工作项" in why, (mark, why)
    assert _inputs(st, parent) == before, _inputs(st, parent)


def test_a_stranger_cannot_be_marked_released(tmp_path: pathlib.Path):
    """负控（结构判据三）：不是这个父的子 ⇒ 拒绝（防止"记到别人账上"）。"""
    st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    other_parent = cond.open_top_level_run("D", "另一个父")
    stranger = _child(cond, other_parent, status="done", key="s1h@stranger")
    before = list(_inputs(st, parent))

    mark, why = cond.note_edge_release(parent, child_task_id=stranger, attempt=1)
    assert mark == "" and "不是" in why and "的子" in why, (mark, why)
    assert _inputs(st, parent) == before, _inputs(st, parent)


def test_released_edges_is_three_state_and_ignores_other_marks(tmp_path: pathlib.Path):
    """反真空（读侧）：读不着那一行 ⇒ `checked=False`；别的 `inputs` 标记不许被误读成边。"""
    st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, status="done", key="s1h@d2")
    # 掺两个同族的既有标记（受理 / 结算）—— 它们不是边
    with st.tx("tasks", actor="test", note="mix") as tx:
        row = tx.find("tasks", task_id=parent)
        row["inputs"] = [str(x) for x in (row.get("inputs") or [])] + [
            "conductor:admitted", "tokenmeter:settled"]
        tx.upsert("tasks", row, note="mix")
    cond.note_edge_release(parent, child_task_id=child, attempt=1)

    got = cond.released_edges(parent)
    assert got["edges"] == [{"child_task_id": child, "attempt": 1}], got["edges"]
    missing = cond.released_edges("t-9999")
    assert missing["checked"] is False and "没有" in missing["reason"], missing
    assert json.dumps(got, ensure_ascii=False)      # 读侧的结果是 JSON 友好的（会进工具面）
