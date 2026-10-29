# -*- coding: utf-8 -*-
"""判据：真实装配的那一趟把执行侧接上（"接到消息就继续"在真机上可用）。

业主 2026-10-29：「静默的唤醒就是接到消息被唤醒」。机制的判定在
`Conductor._ensure_consumer`，执行侧是 `Conductor.resume_dispatched`；
两者要接在一起 —— 但只在真实装配（`host.wired_conductor`）里接，
替身构造的 conductor 保持"未接线"的读数，这样两件事在盘上分得开。

这一组守什么：
1. 正题：`host.wired_conductor(...)` 返回的主控上，`resume_runner` 已接上；
2. 反真空：裸构造（`Conductor(store, backend=LocalBackend({}))`，判据里到处是它）
   不自动接 —— 否则"给静默子开一条 queued notice 就把它叫成 active"会静默改掉
   一批既有判据的口径。
"""
from __future__ import annotations

import pathlib

from agentflow import host
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def test_the_real_wiring_connects_the_execution_side(tmp_path: pathlib.Path) -> None:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = host.wired_conductor(st)
    assert cond is not None, "装配没给出主控"
    runner = getattr(cond, "resume_runner", None)
    assert callable(runner), "真实装配没有把执行侧接上（静默就永远叫不起来）"
    assert getattr(runner, "__name__", "") == "resume_dispatched", runner


def test_a_bare_conductor_does_not_auto_resume(tmp_path: pathlib.Path) -> None:
    """反真空：判据里到处是裸构造，它们不许被自动接上。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    assert getattr(cond, "resume_runner", None) is None
