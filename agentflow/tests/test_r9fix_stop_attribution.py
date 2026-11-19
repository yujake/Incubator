# -*- coding: utf-8 -*-
"""R9FIX · D6/D7：叫停那一句必须写清「谁按的、为什么、是哪一趟」。

## 改前红（真机 lp-ball-9，10:01:39，L3003）

末行 `agent_run_end.final` 写「**用户**叫停（开关文件 .agentflow-stop）：第 64 步
之后收工」，而 `runs/stop-history.jsonl` 是 `by=M` / `reason=budget` —— 那是主控
自己按 $1.00 保留线叫停（框架预算还剩 $0.98）。`stopctl.stop_reason_of` 对所有
开关一律返回 `stop_file`，负载里的 `by` / `reason` 只进了 stop-history，没进
`agent_loop._stop_note` 的模板。

同一句还会被子代理的终态回报带到父的板上（`t-000211` 是 D 的这句话挂在 M 名下），
所以开头必须写清"是哪一趟"：否则「第 0 步」会被读成 M 的步数（M 实际 64 步）。

## 这一条判据守什么

1. `stop_attribution_of` 把负载翻成"谁/为什么"（不改停止理由码）；
2. `_stop_note` / `_stop_headline` 用这份归属，不写死「用户」；
3. 反真空：用户真的按停时仍写「用户叫停」，不许把两档折平。
"""
from __future__ import annotations

from agentflow import stopctl
from agentflow.agent_loop import AgentLoop


class _Loop:
    """只够 `_stop_note` / `_stop_headline` 用的壳（不跑循环）。"""

    role = "M"
    session_root = r"D:\ws"
    sid = "s1"
    stop_file = ".agentflow-stop"
    _stop_payload: dict = {}


def _note(payload: dict, *, role: str = "M", stop_reason: str = "stop_file",
          step: int = 64) -> str:
    loop = _Loop()
    loop.role = role
    loop._stop_payload = payload
    return AgentLoop._stop_note(loop, stop_reason, step)


def test_attribution_reads_the_switch_payload_without_changing_the_reason_code():
    got = stopctl.stop_attribution_of({"reason": "budget", "by": "M", "force": False})

    assert got["checked"] is True, got
    assert got["by"] == "M" and got["reason"] == "budget", got
    assert "主控" in got["label"] and "预算" in got["label"], got
    assert "用户" not in got["label"], got
    # 反向：理由码一个字不动（退出码 4 与 `USER_STOP_REASONS` 的分类都靠它）。
    assert stopctl.stop_reason_of({"reason": "budget", "by": "M"}) == "stop_file"


def test_a_self_stop_is_not_rendered_as_a_user_stop():
    """改前：`_stop_note` 对任何 `stop_file` 都写「用户叫停」。"""
    text = _note({"reason": "budget", "by": "M", "force": False})

    assert "用户叫停" not in text, text
    assert "主控 M 自己" in text and "预算保留线" in text, text
    assert "M 这一趟" in text, text


def test_a_childs_stop_note_names_the_child_not_the_parent():
    """`t-000211` 的形态：D 的这句话挂在 M 的板上 ⇒ 必须写明是 D 这一趟。"""
    text = _note({"reason": "budget", "by": "M"}, role="D", step=0)

    assert text.startswith("D 这一趟："), text
    assert "第 0 步之后收工" in text, text
    # 反真空：0 是 D 的步数，不是 M 的 64 —— 两趟各自写自己的。
    assert "第 64 步" not in text, text


def test_a_real_user_stop_still_says_user():
    """反真空：用户按的停不许被新逻辑改写成「主控自己」。"""
    text = _note({"reason": "user", "by": "user", "force": False})

    assert "用户叫停" in text, text
    assert "主控" not in text, text
