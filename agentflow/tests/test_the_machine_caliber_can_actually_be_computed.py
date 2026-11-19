# -*- coding: utf-8 -*-
"""判据：机器读数那一格要真的算得出来，并进一份权威结论（2026-11-03 / 2026-11-19）。

## 背景

2026-11-03 的裁决 ①=乙把"能不能交"拆成两条轴：`can_close = m_says_done ∧
retire.complete ∧ programs_ok`（不读八格），`machine_pass` 读八格（不读机器读数）。
真机 `projects/lp-ball-11` 因此八格 6/8 仍 `exit 0`。

2026-11-19（ROOTGATE-①，业主「要修根因」）之后只剩一份结论
（`closing.closing_verdict`）：机器读数那一格仍是它的半边，但 `can_close` 不再
单独成立 —— 八格有 fail 时它必须是 `False`。

## 这条判据钉住什么

1. 喂齐且三者全真 ⇒ `machine_caliber.value is True`，八格全 pass 的完整门
   `can_close is True` / `closable is True`；
2. 任一个假 ⇒ `value is False`，`can_close is False`，且 `can_close_reason` 点名是哪一个假
   （retire 不干净 / programs 没停 / M 说没达成）；
3. 没喂 ⇒ `checked=False`、`value=None` + `reason` 里是 `not_wired`（不许退化成 False ——
   False 会被读成"机器说不通过"），完整门 `can_close is None`、退出码 2；
4. 喂了、但某一格自己 `checked=False` ⇒ 仍 `None` + 说清是哪一格没查成
   （三态纪律：没查成 ≠ 不通过）。
"""
from __future__ import annotations

from typing import Any

from agentflow import closing as CL

_CLEAN_RETIRE = {"checked": True, "complete": True, "count": 0, "total": 0}
_DIRTY_RETIRE = {"checked": True, "complete": False, "count": 1, "total": 1,
                 "reason": "还在册 1 个"}
_CLEAN_PROGRAMS = {"checked": True, "running_count": 0, "running": []}
_BUSY_PROGRAMS = {"checked": True, "running_count": 2, "running": [{"program": "x"}]}


def _full(*, met: bool = True, wired: bool = True,
          retire: Any = None, programs: Any = None) -> CL.ClosingReport:
    """一份完整的八格门：八格全 pass + 机器读数（`wired=False` 时不喂）。"""
    caliber = CL.machine_caliber(
        m_says_done=met,
        retire=(retire if retire is not None else _CLEAN_RETIRE) if wired else None,
        programs=(programs if programs is not None else _CLEAN_PROGRAMS) if wired else None)
    return CL.ClosingReport(status={name: "pass" for name in CL.DEFAULT_CHECKS},
                            full_gate=True, m_verdict={"met": met},
                            readings={"machine_caliber": caliber})


def test_all_three_true_makes_the_machine_caliber_and_the_verdict_true() -> None:
    """① 喂齐且三者全真 ⇒ 机器读数真，完整门的 `can_close is True`。"""
    rep = _full()
    caliber = rep.readings["machine_caliber"]
    assert caliber["value"] is True, caliber
    assert rep.m_says_done is True, rep.to_dict()
    assert rep.can_close is True, (rep.can_close, rep.can_close_reason)
    assert rep.closable is True, rep.closable
    assert "not_wired" not in rep.can_close_reason, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 0


def test_any_false_makes_it_false_and_names_which_one() -> None:
    """② 任一个假 ⇒ False，且 reason 点名是哪一个。"""
    assert _full().can_close is True
    dirty = _full(retire=_DIRTY_RETIRE)
    assert dirty.can_close is False, (dirty.can_close, dirty.can_close_reason)
    assert "retire" in dirty.can_close_reason, dirty.can_close_reason
    busy = _full(programs=_BUSY_PROGRAMS)
    assert busy.can_close is False, (busy.can_close, busy.can_close_reason)
    assert "programs" in busy.can_close_reason, busy.can_close_reason
    m_no = _full(met=False)
    assert m_no.can_close is False, (m_no.can_close, m_no.can_close_reason)
    assert "m_says_done" in m_no.can_close_reason or "M 说" in m_no.can_close_reason, \
        m_no.can_close_reason


def test_not_fed_stays_none() -> None:
    """③ 没喂 ⇒ None + `not_wired`（不许退化成 False），退出码 2（不是 0）。"""
    rep = _full(wired=False)
    caliber = rep.readings["machine_caliber"]
    assert caliber["value"] is None, caliber
    assert rep.can_close is None, (rep.can_close, rep.can_close_reason)
    assert "not_wired" in rep.can_close_reason, rep.can_close_reason
    assert rep.closable is False
    assert CL.tri_state_exit_code(rep) == 2


def test_a_fed_but_unreadable_cell_is_none_not_false() -> None:
    """④ 喂了、但那一格自己没查成 ⇒ 仍 None，并说清是哪一格。"""
    rep = _full(retire={"checked": False, "reason": "台账读不成"})
    assert rep.can_close is None, (rep.can_close, rep.can_close_reason)
    assert "retire" in rep.can_close_reason and "没查成" in rep.can_close_reason, \
        rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 2
