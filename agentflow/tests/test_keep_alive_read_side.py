# -*- coding: utf-8 -*-
"""S2'：`keep_alive` 的读侧（A6=丙）—— 声明在派活项上，读代理行时看它名下最新那条。

## 一处订正（`draft/92` §15.6）

主控先前把业主 T22 的"无活跃子代理且自身完全停止"读成了对父的要求，于是写下
"待命的父不许消边"。业主 §1.9 的三分支说明那两条都是对要退役的那个子代理自己说的：
"在等待"（待命）恰恰是可以退役的那一支（只要它自己名下没有活跃子代理）。
所以本批只留两件事：① 这一格有一个三态读侧；② "活跃"与"在等待"的分界是
它在不在跑（`active_children` 说），而"待命"只是一格的声明（这里说）——
两者正交：在等待 + keep_alive = 待命；在等待 + 没 keep_alive = 已停。

## 判据

正控 2（派活项自己的那一格 / 代理行名下最新那条）；负控 2（只有派活项能带 `keep_alive`
—— schema 当场拒；更新的一条派活项会覆盖旧声明）；反真空 1（没有那一行 / 读不成 ⇒ 三态）。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({}))


def _child(cond: Conductor, parent: str, *, key: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": "A", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": "2026-10-08T22:05:00+08:00", "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="start:A.run_once")


def _delegate(cond: Conductor, child: str, *, keep_alive: bool, key: str,
              at: str = "2026-10-08T22:01:00+08:00") -> str:
    item = cond.open_item(kind="delegation", role="A", expects="work", action="run_once",
                          summary="派给 A 的活", called_by="M", parent_task_id=child,
                          depth=3, input_key=key, keep_alive=keep_alive)
    # 排序键用 `started_at`：显式钉一下，免得两条派活项同秒（判据要问"最新那条"）
    with cond.store.tx("tasks", actor="test", note="at") as tx:
        row = tx.find("tasks", task_id=item)
        row["started_at"] = at
        tx.upsert("tasks", row, note="at")
    return item


def test_the_delegation_item_carries_its_own_flag(tmp_path: pathlib.Path):
    """正控（第一半）：派活项自己的那一格读得回来。"""
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, key="s2@a")
    hot = _delegate(cond, child, keep_alive=True, key="s2@ka1")
    cold = _delegate(cond, child, keep_alive=False, key="s2@ka0", at="2026-10-08T22:02:00+08:00")
    assert cond.keep_alive_of(hot) == {"checked": True, "keep_alive": True, "reason": ""}
    assert cond.keep_alive_of(cold) == {"checked": True, "keep_alive": False, "reason": ""}


def test_an_agent_row_reads_its_newest_delegation_item(tmp_path: pathlib.Path):
    """正控（第二半）：问代理行时，读的是它名下最新那条派活项的声明。

    这条是 A6=丙 的实际语义："父声明'这个实例做完一件还待命'" —— 声明跟着一次派活走，
    所以后来的一次派活可以改掉先前的声明（下面那张表就是"覆盖"这件事本身）。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, key="s2@b")
    _delegate(cond, child, keep_alive=True, key="s2@old", at="2026-10-08T22:01:00+08:00")
    assert cond.keep_alive_of(child)["keep_alive"] is True, cond.keep_alive_of(child)

    _delegate(cond, child, keep_alive=False, key="s2@new", at="2026-10-08T22:09:00+08:00")
    got = cond.keep_alive_of(child)
    assert got["checked"] is True and got["keep_alive"] is False, (
        "最新那条派活项说了算（旧声明被覆盖）", got)


def test_only_a_delegation_item_may_carry_keep_alive(tmp_path: pathlib.Path):
    """负控（边界）：只有派活项能带 `keep_alive` —— 别的 kind 会被 schema 当场拒。

    没有这一条，"待命"这个概念会溢到通报/留言上，于是"谁在待命"变成不可判的。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    with pytest.raises(ValueError) as ei:
        cond.open_item(kind="notice", role="A", expects="ack", summary="子代理已收工",
                       called_by="A", parent_task_id=parent, depth=2, input_key="s2@bad",
                       keep_alive=True)
    assert "keep_alive" in str(ei.value), ei.value


def test_no_delegation_item_means_not_standby(tmp_path: pathlib.Path):
    """边界：名下一条派活项都没有 ⇒ `keep_alive=False`，但 `checked=True`（"确实没有"）。"""
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, parent, key="s2@c")
    assert cond.keep_alive_of(child) == {"checked": True, "keep_alive": False, "reason": ""}


def test_keep_alive_of_is_three_state(tmp_path: pathlib.Path, monkeypatch):
    """反真空：没有那一行 / 读不成 ⇒ `checked=False`（不许折成"没声明过待命"）。

    折平的后果很具体：退役判定会把"我读不到台账"当成"它不是待命" ⇒ 一个真的在待命的
    实例被划掉（而它名下的活还没完）。
    """
    _st, cond = _cond(tmp_path)
    missing = cond.keep_alive_of("t-9999")
    assert missing["checked"] is False and "没有" in missing["reason"], missing

    parent = cond.open_top_level_run("M", "父那一趟")

    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("注入的台账故障")

    # 注入点跟着实现走：2026-10-27 起 `keep_alive_of` 一拍只读一次台账（`_tasks()`），
    # 不再是 `_task(task_id)` 再扫第二遍 —— 打在旧口上等于没打（判据会假绿）。
    monkeypatch.setattr(cond, "_tasks", boom)
    bad = cond.keep_alive_of(parent)
    assert bad["checked"] is False and "RuntimeError" in bad["reason"], bad


def test_standby_and_running_are_orthogonal_reads(tmp_path: pathlib.Path):
    """口径（正交）：`active_children` 说"在不在跑"，`keep_alive_of` 说"是不是待命"。

    两个读侧合起来才是四态折叠（`draft/92` §2）：
    活跃 / 待命（在等待 + keep_alive）/ 已停（在等待 + 没 keep_alive）/ 已退役（S1k 说）。
    这一条把"折平"这件事钉在调用方（S1k），而不是让两个读侧互相猜。
    """
    _st, cond = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    standby = _child(cond, parent, key="s2@standby")
    _delegate(cond, standby, keep_alive=True, key="s2@sb")
    stopped = _child(cond, parent, key="s2@stopped")

    states = {r["task_id"]: r["state"] for r in cond.active_children(parent)["rows"]}
    assert states[standby] == "在等待" and states[stopped] == "在等待", states
    assert cond.keep_alive_of(standby)["keep_alive"] is True
    assert cond.keep_alive_of(stopped)["keep_alive"] is False
