# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：机器口径那一格要真的算得出来（2026-11-03，153-U-01/U-02 第 2 笔）。

## 背景

第 1 笔（`1449d314`）把 `can_close` 拆成两个名字：`m_says_done`（M 的判断）与
`can_close: bool | None`（机器口径）。那一笔里 `can_close` 恒 `None`（reason 写着
`not_wired: 这一格还没接线（retire_integrity / programs 没喂进来）`）—— 因为
`ClosingReport` 里没有任何 `retire_integrity` 格（`grep retire_integrity closing.py` = 0 命中），
`programs_ok` 也只活在 `agent_loop._final_gate_reading` 里。

这一笔把两个喂参接上：`check_closing(..., retire=…, programs=…)`，由
`conductor.closing`（运行内）与 `agentflow closing`（运行外）各自喂。

## 这条判据钉住什么

1. 喂齐且三者全真 ⇒ `can_close is True`，`closable` 跟着真；
2. 任一个假 ⇒ `can_close is False`，且 `can_close_reason` 说清是哪一个假
   （retire 不干净 / programs 没停 / M 说没达成）；
3. 没喂 ⇒ `can_close is None` + `reason` 里是 `not_wired`（不许退化成 False ——
   False 会被读成"机器说不通过"）；
4. 喂了、但某一格自己 `checked=False` ⇒ 仍 `None` + 说清是哪一格没查成
   （三态纪律：没查成 ≠ 不通过）。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> Store:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    return st


def _rep(st, **kw):
    return CL.check_closing(st, checks=("substance",), project_dir="", report_path="",
                            goal_met=True, **kw)


_CLEAN_RETIRE = {"checked": True, "complete": True, "count": 0, "total": 0}
_DIRTY_RETIRE = {"checked": True, "complete": False, "count": 1, "total": 1,
                 "reason": "还在册 1 个"}
_CLEAN_PROGRAMS = {"checked": True, "running_count": 0, "running": []}
_BUSY_PROGRAMS = {"checked": True, "running_count": 2, "running": [{"program": "x"}]}


def test_all_three_true_makes_the_machine_caliber_true(tmp_path: pathlib.Path) -> None:
    """① 喂齐且三者全真 ⇒ `can_close is True`（今天红：恒 None）。"""
    rep = _rep(_ws(tmp_path), retire=_CLEAN_RETIRE, programs=_CLEAN_PROGRAMS)
    assert rep.m_says_done is True, rep.to_dict()
    assert rep.can_close is True, (rep.can_close, rep.can_close_reason)
    assert rep.closable is True, rep.closable
    assert "not_wired" not in rep.can_close_reason, rep.can_close_reason


def test_any_false_makes_it_false_and_names_which_one(tmp_path: pathlib.Path) -> None:
    """② 任一个假 ⇒ False，且 reason 点名是哪一个。"""
    tiny = _rep(_ws(tmp_path / "a"), retire=_CLEAN_RETIRE, programs=_CLEAN_PROGRAMS)
    assert tiny.can_close is True
    dirty = _rep(_ws(tmp_path / "b"), retire=_DIRTY_RETIRE, programs=_CLEAN_PROGRAMS)
    assert dirty.can_close is False, (dirty.can_close, dirty.can_close_reason)
    assert "retire" in dirty.can_close_reason, dirty.can_close_reason
    busy = _rep(_ws(tmp_path / "c"), retire=_CLEAN_RETIRE, programs=_BUSY_PROGRAMS)
    assert busy.can_close is False, (busy.can_close, busy.can_close_reason)
    assert "programs" in busy.can_close_reason, busy.can_close_reason
    m_no = CL.check_closing(_ws(tmp_path / "d"), checks=("substance",), project_dir="",
                            report_path="", goal_met=False,
                            retire=_CLEAN_RETIRE, programs=_CLEAN_PROGRAMS)
    assert m_no.can_close is False, (m_no.can_close, m_no.can_close_reason)
    assert "m_says_done" in m_no.can_close_reason or "M 说" in m_no.can_close_reason, \
        m_no.can_close_reason


def test_not_fed_stays_none(tmp_path: pathlib.Path) -> None:
    """③ 没喂 ⇒ None + `not_wired`（不许退化成 False）。"""
    rep = _rep(_ws(tmp_path))
    assert rep.can_close is None, (rep.can_close, rep.can_close_reason)
    assert "not_wired" in rep.can_close_reason, rep.can_close_reason


def test_a_fed_but_unreadable_cell_is_none_not_false(tmp_path: pathlib.Path) -> None:
    """④ 喂了、但某一格自己没查成 ⇒ 仍 None，并说清是哪一格。"""
    rep = _rep(_ws(tmp_path), retire={"checked": False, "reason": "台账读不成"},
               programs=_CLEAN_PROGRAMS)
    assert rep.can_close is None, (rep.can_close, rep.can_close_reason)
    assert "retire" in rep.can_close_reason and "没查成" in rep.can_close_reason, \
        rep.can_close_reason
