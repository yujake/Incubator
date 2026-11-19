# -*- coding: utf-8 -*-
"""判据：机器说不行时，退出码不许是 0（2026-11-03 裁决 ②；2026-11-19 ROOTGATE-①）。

## 改前 / 改后

2026-11-03 之前 `tri_state_exit_code` 只看 M 那一句；裁决 ② 之后它读
`machine_pass` / `blockers`。但"能不能交"仍被拆成两条互不相干的轴：

```text
can_close  = m_says_done ∧ retire.complete ∧ programs_ok   # 不读八格
machine_pass = 八格全 pass ∧ 没有 blocker                  # 不读机器读数
```

于是八格 6/8、`can_close=true` 的那一趟仍然退出 0（真机 `projects/lp-ball-11`）。

2026-11-19（业主「要修根因」）之后只有一份权威结论（`closing.closing_verdict`），
退出码只从它取：`pass ⇒ 0` / `fail ⇒ 1` / `unknown ⇒ 2`。

## 这条判据钉住什么

1. `met=True` 而有一格 `unknown` ⇒ 2（没查成，不是"被拦住"）；
2. `met=True` 而有一条 `blocker` ⇒ 1（查过了、结论是坏）；
3. 两边都说行（八格全 pass + 机器读数真 + 无 blocker）⇒ 0（反真空：不许"永远非 0"）；
4. 没人判过（`m_verdict=None`）⇒ 2；
5. `met=False` + 八格全 pass ⇒ 1（M 说没做到，机器说没事 ⇒ 仍不收工）；
6. `tri_state_exit_code` 的 docstring 必须点名它读了 `machine_pass` / `blockers`
   —— 口径说明与代码同一个地方，不许只改代码。
"""
from __future__ import annotations

from agentflow import closing as CL


def _finding(level: str = "blocker", check: str = "J21") -> CL.Finding:
    return CL.Finding(check=check, code="cite_without_span", level=level, detail="夹具")


def _rep(*, status: str = "pass", met: bool | None = True,
         cell_overrides: dict[str, str] | None = None,
         findings: list[CL.Finding] | None = None,
         wired: bool = True) -> CL.ClosingReport:
    cells = {name: status for name in CL.DEFAULT_CHECKS}
    cells.update(cell_overrides or {})
    caliber = CL.machine_caliber(
        m_says_done=bool(met),
        retire={"checked": True, "complete": True} if wired else None,
        programs={"checked": True, "running_count": 0} if wired else None)
    return CL.ClosingReport(
        status=cells, findings=list(findings or []), full_gate=True,
        m_verdict=None if met is None else {"met": bool(met)},
        readings={"machine_caliber": caliber})


def test_a_machine_failure_makes_the_exit_code_nonzero() -> None:
    """① 机器有一格不是 pass，而 M 说达成 ⇒ 2（没查成；改前是 0，裁决 ② 后是 1）。"""
    rep = _rep(cell_overrides={"user_pending": "unknown"})
    assert rep.m_says_done is True, "夹具的前提：M 说达成"
    assert rep.machine_pass is False, "夹具的前提：机器那一格是 unknown"
    assert rep.can_close is None, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 2, (
        f"机器读数说没查成，退出码却是 {CL.tri_state_exit_code(rep)} —— "
        "三态纪律：unknown 是 2，不许折成 1（查过了坏）也不许折成 0")


def test_a_blocker_alone_makes_the_exit_code_nonzero() -> None:
    """② 八格全 pass、但有一条 blocker ⇒ 1（查过了、结论是坏）。"""
    rep = _rep(findings=[_finding("blocker")])
    assert rep.machine_pass is False
    assert rep.can_close is False, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 1, CL.tri_state_exit_code(rep)


def test_both_sides_saying_yes_is_still_zero() -> None:
    """③ 反真空：八格全 pass + 机器读数真 + M 说达成 ⇒ 0。"""
    rep = _rep(findings=[_finding("warning")])  # warning 只报不拦
    assert rep.machine_pass is True
    assert rep.can_close is True, rep.can_close_reason
    assert rep.closable is True
    assert CL.tri_state_exit_code(rep) == 0


def test_nobody_judged_is_still_two() -> None:
    """④ 没人判过 ⇒ 2（"没查成"不许折成 1，也不许折成 0）。"""
    rep = _rep(met=None)
    assert CL.tri_state_exit_code(rep) == 2


def test_m_says_not_done_is_one_even_when_the_machine_passes() -> None:
    """⑤ M 说没做到、机器说没事 ⇒ 1（M 的判据仍然压过机器读数）。"""
    rep = _rep(met=False)
    assert rep.machine_pass is True
    assert rep.can_close is False, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 1


def test_the_docstring_names_the_machine_readings() -> None:
    """⑥ 口径说明与代码同一处：docstring 必须点名 machine_pass / blockers。"""
    doc = CL.tri_state_exit_code.__doc__ or ""
    assert "machine_pass" in doc and "blockers" in doc, (
        "`tri_state_exit_code` 的 docstring 没说它读了 `machine_pass` / `blockers` ⇒ "
        f"读者会以为 0 只由 M 那一句决定：{doc[:200]}")
