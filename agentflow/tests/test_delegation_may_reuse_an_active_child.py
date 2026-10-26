# -*- coding: utf-8 -*-
"""S1j：复用的分支 —— "派活不一定是增"在台账层的判据（业主 2026-10-08 深夜订正）。

> 「派活不一定是增（可能是给已有活跃子代理派活），但增一定是派活。」

⇒ 增 ⊆ 派活、派活 ⊋ 增。本批落台账层那一半：父名下此刻有哪些子代理可以再接一件活
（行标签「活跃」= 在跑；「待命」= 已停但声明过 `keep_alive`）。

口径订正（2026-10-26 三态裁定之后）：「活跃子代理」的定义是"非静默"，于是待命那一档也
算活跃（在飞 / 待机 / 静默三态与活跃的关系见 `tests/test_three_states_flying_standby_silent.py`）。
本文件判的那两行标签仍是名册面的四态词（活跃 / 待命 / 已停 / 已退役），与那条定义不是同一个轴；
文件里的断言一条都没按旧口径写，所以那一批裁定没有让它们变红。

## 这一批不做哪一半（如实写在这里，免得读的人以为漏了）

- 名字面（`reuse:"D1"` 与译码）在 S1k：名字、名册、对照表都还不存在（`draft/90` E16/E17），
  本方法因此只给候选清单，不挑"最合适的那个" —— 复用必须父点名（业主 B2）。
- 资源级复用（真有进程在等）不是本批：按 `draft/92` §7-②，今天的复用只能是
  用同一个名字再跑一次（语义复用）；资源复用属 A2=甲 的后半，另立一批。

## 判据

正控 2（活跃 + 待命各一条、角色过滤）；负控 2（已停且没声明待命 ⇒ 不在候选里；
工作项永远不是候选）；反真空 1（台账读不成 ⇒ `checked=False`，不许折成"没有可复用的"）。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({}))


def _child(cond: Conductor, parent: str, *, role: str = "A", status: str = "done",
           key: str = "s1j@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")


def _standby(cond: Conductor, child: str, *, key: str) -> str:
    return cond.open_item(kind="delegation", role="A", expects="work", action="run_once",
                          summary="派给 A 的活", called_by="M", parent_task_id=child,
                          depth=3, input_key=key, keep_alive=True)


def test_a_running_child_is_reusable_and_a_standby_one_too(tmp_path: pathlib.Path):
    """正控：活跃（在跑）与待命（已停 + 声明过 keep_alive）都进候选，各带自己的 state。"""
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    running = _child(cond, parent, role="A", status="running", key="s1j@run")
    standby = _child(cond, parent, role="D", status="done", key="s1j@sb")
    _standby(cond, standby, key="s1j@sb-item")

    got = cond.reusable_children_of(parent)
    assert got["checked"] is True and got["reason"] == "", got
    table = {r["task_id"]: r for r in got["rows"]}
    assert set(table) == {running, standby}, got["rows"]
    assert table[running]["state"] == "活跃", table[running]
    assert table[standby]["state"] == "待命", table[standby]


def test_a_stopped_child_without_standby_is_not_reusable(tmp_path: pathlib.Path):
    """负控：已停、又没声明待命 ⇒ 不在候选里（要派活就新起）。

    没有这一条，"复用"会被用到一条已经收工的记录上 —— 那条记录不会再跑，
    于是那次派活永远不会有结果（而盘上看起来"派出去了"）。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    stopped = _child(cond, parent, role="A", status="done", key="s1j@stopped")
    got = cond.reusable_children_of(parent)
    assert got["checked"] is True, got
    assert stopped not in {r["task_id"] for r in got["rows"]}, got["rows"]


def test_role_filter_and_work_items_are_excluded(tmp_path: pathlib.Path):
    """负控（两轴 + 角色）：工作项永远不是候选；`role` 给了就只看那个角色。"""
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    a = _child(cond, parent, role="A", status="running", key="s1j@a")
    d = _child(cond, parent, role="D", status="running", key="s1j@d")
    cond.open_item(kind="delegation", role="G", expects="work", action="run_once",
                   summary="派给 G 的活", called_by="M", parent_task_id=parent,
                   depth=2, input_key="s1j@item")

    all_rows = {r["task_id"] for r in cond.reusable_children_of(parent)["rows"]}
    assert all_rows == {a, d}, ("工作项不许进候选", all_rows)
    only_d = cond.reusable_children_of(parent, role="D")
    assert {r["task_id"] for r in only_d["rows"]} == {d}, only_d["rows"]


def test_reusable_children_of_is_three_state(tmp_path: pathlib.Path, monkeypatch):
    """反真空：台账读不成 ⇒ `checked=False`（不许折成"没有可复用的"）。

    折平的后果：复用静默变成新起 —— 多建一个代理、多烧一次钱，而盘上读不出"这是被迫的"。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")

    def boom() -> Any:
        raise RuntimeError("注入的台账故障")

    monkeypatch.setattr(cond, "_tasks", boom)
    got = cond.reusable_children_of(parent)
    assert got["checked"] is False and "RuntimeError" in got["reason"], got
    assert got["rows"] == [], got


def test_a_standby_declaration_that_cannot_be_read_is_not_treated_as_no(tmp_path: pathlib.Path,
                                                                       monkeypatch):
    """反真空（第二处）：某一行待命声明读不成 ⇒ 整体 `checked=False`。

    这一条防的是"半个读数"：前面几行读得到、后面一行读不到时，不许把结果当成
    "这个人不可复用"（那是拿"没查成"当"没有"）。做法：只让 `keep_alive_of` 抛。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    stopped = _child(cond, parent, role="A", status="done", key="s1j@gone")

    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("注入的待命读数故障")

    monkeypatch.setattr(cond, "keep_alive_of", boom)
    got = cond.reusable_children_of(parent)
    assert got["checked"] is False, got
    assert stopped not in {r["task_id"] for r in got["rows"]}, got["rows"]
