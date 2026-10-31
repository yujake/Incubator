# -*- coding: utf-8 -*-
"""判据：机器说不行时，退出码不许是 0（2026-11-03，153-U-03；业主 2026-11-03 的裁决 ②）。

## 背景

`closing.tri_state_exit_code`（`closing.py:5990-6004`）改前只看 M 那一句：

```python
if rep.can_close: return 0          # can_close = m_verdict.met
if not rep.m_verdict: return 2
return 1
```

而 `machine_pass`（八格全 pass 且没有 blocker）与 `blockers`（J21 引文无区间 / J22 对应表
缺失 / J23 回执无背书）**一个都不参与**退出码。于是"八格 fail 或 unknown、M 却说达成"的
那一趟：`can_close=true` ⇒ 退出码 **0**（= 可交付），而机器读数明明说不行。

## 业主 2026-11-03 的裁决 ②

退出码要读 `machine_pass` / `blockers`：机器说不行 ⇒ 退出码非 0。

## 这条判据钉住什么

1. `met=True` 而有一格 `unknown`/`fail` ⇒ 退出码 **1**（改前是 0）；
2. `met=True` 而有一条 `blocker` ⇒ 退出码 **1**（改前是 0）；
3. 两边都说行（`met=True` + 八格全 pass + 无 blocker）⇒ **0**（反真空：不许改成"永远非 0"）；
4. 没人判过（`m_verdict=None`）⇒ **2**（"没查成"不许折成 1 也不许折成 0）；
5. `met=False` + 八格全 pass ⇒ **1**（M 说没做到，机器说没事 ⇒ 仍不收工）；
6. `tri_state_exit_code` 的 docstring 必须点名它读了 `machine_pass` / `blockers`
   —— 口径说明与代码同一个地方，不许只改代码。
"""
from __future__ import annotations

from agentflow import closing as CL


def _finding(level: str = "blocker", check: str = "J21") -> CL.Finding:
    return CL.Finding(check=check, code="cite_without_span", level=level, detail="夹具")


def _rep(**kw):
    return CL.ClosingReport(**kw)


def test_a_machine_failure_makes_the_exit_code_nonzero() -> None:
    """① 机器有一格不是 pass，而 M 说达成 ⇒ 退出码不是 0（改前是 0）。"""
    rep = _rep(status={"a": "pass", "b": "unknown"}, m_verdict={"met": True, "basis": "夹具"})
    assert rep.can_close is True, "夹具的前提：M 说达成"
    assert rep.machine_pass is False, "夹具的前提：机器那一格是 unknown"
    assert CL.tri_state_exit_code(rep) == 1, (
        f"机器读数说不行（unknown / 不是 pass），退出码却是 {CL.tri_state_exit_code(rep)} "
        "—— 业主 2026-11-03 的裁决 ②：机器说不行时退出码不许是 0")


def test_a_blocker_alone_makes_the_exit_code_nonzero() -> None:
    """② 八格全 pass、但有一条 blocker ⇒ 退出码不是 0（blockers 也参与）。"""
    rep = _rep(status={"a": "pass"}, findings=[_finding("blocker")],
               m_verdict={"met": True, "basis": "夹具"})
    assert rep.machine_pass is False
    assert CL.tri_state_exit_code(rep) == 1, CL.tri_state_exit_code(rep)


def test_both_sides_saying_yes_is_still_zero() -> None:
    """③ 反真空：两边都说行 ⇒ 0（不许把这一档改成"永远非 0"）。"""
    rep = _rep(status={"a": "pass", "b": "pass"},
               findings=[_finding("warning")],  # warning 只报不拦
               m_verdict={"met": True, "basis": "夹具"})
    assert rep.can_close and rep.machine_pass
    assert CL.tri_state_exit_code(rep) == 0


def test_nobody_judged_is_still_two() -> None:
    """④ 没人判过 ⇒ 2（"没查成"不许折成 1，也不许折成 0）。"""
    rep = _rep(status={"a": "pass", "b": "pass"}, m_verdict=None)
    assert CL.tri_state_exit_code(rep) == 2


def test_m_says_not_done_is_one_even_when_the_machine_passes() -> None:
    """⑤ M 说没做到、机器说没事 ⇒ 1（M 的判据仍然压过机器读数）。"""
    rep = _rep(status={"a": "pass"}, m_verdict={"met": False, "basis": "夹具"})
    assert rep.machine_pass is True
    assert CL.tri_state_exit_code(rep) == 1


def test_the_docstring_names_the_machine_readings() -> None:
    """⑥ 口径说明与代码同一处：docstring 必须点名 machine_pass / blockers。"""
    doc = CL.tri_state_exit_code.__doc__ or ""
    assert "machine_pass" in doc and "blockers" in doc, (
        "`tri_state_exit_code` 的 docstring 没说它读了 `machine_pass` / `blockers` ⇒ "
        f"读者会以为 0 只由 M 那一句决定：{doc[:200]}")
