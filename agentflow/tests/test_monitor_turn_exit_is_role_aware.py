# -*- coding: utf-8 -*-
"""判据 S2：监控回合的出口按角色渲染（watch / guide 是 M 专属，不许写给所有人）。

## 守的是什么

`agent_loop._monitor_block` 是每个角色在"被唤醒开起来的监控回合"里读到的那一段。
改前它给所有角色都写「只许 `conductor.watch` / `conductor.guide` / 补派 / 收口」——
而 `conductor.watch` 与 `conductor.guide` 只在主控的工具面上。非 M 角色读到两件它没有的
工具，照做只会拿 `unknown_tool` / 越权拒绝，而真正的出口（补派 / 收口 / `note`）不在话里。

## 判据（正控 2 / 负控 1）

1. 非 M（D/E/F/G/H/V 抽样）的监控段：不出现 `conductor.watch` / `conductor.guide`，
   且读得到三类出口（补派 / 收口 / note）；
2. M 的监控段：仍然点名 watch / guide（它真有这两件）；
3. 反真空：把出口句改回"所有角色都写 watch / guide" ⇒ 1 必红。

## 零模型

`_monitor_block` 是纯字符串渲染（树形读数用桩替掉），不调模型、不读盘。
"""
from __future__ import annotations

import pytest

from agentflow import agent_loop as AL
from agentflow import schema as S

#: 改前那一句（所有角色都读到的四类出口）。
_OLD_EXIT = ("这一回合的出口只许这四类：`conductor.watch`（看全树）/ "
             "`conductor.guide`（给指导）/ 补派（`summon` 一个或 `summon_many` 一批）/ "
             "收口（`final`）。")

_NON_M = ("D", "E", "F", "G", "H", "V", S.CONDUCTOR_ROLE)


class _FakeLoop:
    """`_monitor_block` 只用到这几个属性（树形读数用桩，不读台账）。"""

    def __init__(self, role: str) -> None:
        self.role = role
        self.monitor_of = ""
        self._monitor_turn_step = -1
        self._monitor_refusals = 0

    def _tree_reading(self) -> str:
        return "- [t-1] D·running（判据夹具）"


_WAKES = {"consumed": [{"wake_id": "w-1", "reason": "时钟到点", "due_at": "2026-10-25T00:00",
                        "mailbox_item_id": "t-9"}]}


def _monitor_text(role: str) -> str:
    return AL.AgentLoop._monitor_block(_FakeLoop(role), wakes=_WAKES, step=0)


def _exit_problems(text: str, role: str) -> list[str]:
    """这段监控回合的出口与这个角色的工具面对不上 = 一条问题。"""
    out: list[str] = []
    for tool in ("conductor.watch", "conductor.guide"):
        if tool in text and str(role) != S.CONDUCTOR_ROLE:
            out.append(f"{role} 的监控回合点名了 {tool}（它没有这一件；watch/guide 只有 M 有）")
    if str(role) == S.CONDUCTOR_ROLE:
        for tool in ("conductor.watch", "conductor.guide"):
            if tool not in text:
                out.append(f"M 的监控回合没有点名 {tool}（它真有这一件，出口少了入口）")
    else:
        for needle in ("补派", "收口", "`note`"):
            if needle not in text:
                out.append(f"{role} 的监控回合读不到「{needle}」这一类出口")
    return out


# ============================================================ 1 非 M 按角色渲染
@pytest.mark.parametrize("role", [r for r in _NON_M if r != S.CONDUCTOR_ROLE])
def test_01_non_m_monitor_turn_never_names_watch_or_guide(role: str) -> None:
    """01：非 M 的监控回合只写它真有的出口，不写 watch / guide。"""
    text = _monitor_text(role)
    assert "【监控回合】" in text, f"{role} 的判据夹具不再产生监控回合：{text[:200]}"
    problems = _exit_problems(text, role)
    assert problems == [], "\n".join(problems)


def test_02_the_conductor_still_gets_the_tree_tools() -> None:
    """02（正控）：M 的监控回合仍然点名 watch / guide（这两件真的在它工具面上）。"""
    text = _monitor_text(S.CONDUCTOR_ROLE)
    assert "conductor.watch" in text and "conductor.guide" in text, text[-500:]
    assert _exit_problems(text, S.CONDUCTOR_ROLE) == []


# ============================================================ 3 反真空
def test_03_reverting_to_the_all_roles_wording_turns_the_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """03：把出口句改回"所有角色都写 watch / guide" ⇒ 01 必红。"""
    monkeypatch.setattr(AL, "monitor_exit_text", lambda role: _OLD_EXIT)
    text = _monitor_text("D")
    problems = _exit_problems(text, "D")
    assert problems, (
        "把出口句改回「所有角色都写 watch / guide」之后，判据仍然绿 ⇒ 它没有在看这一段")
    assert any("conductor.watch" in one for one in problems), problems
