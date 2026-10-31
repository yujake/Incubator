# -*- coding: utf-8 -*-
"""判据：`sse.detach()` 必须还原来宾钩子（clock 的事件旁路就挂在 `sessions.append` 上）。

## 真因（2026-10-29，由失败断言定位）

```
test_h: assert [f["timer_id"] for f in fires] == [timer_id], fires
        AssertionError: [] == ['tm-000001']
```

子发了消息、父挂机的计时器没被唤醒 —— 那条唤醒走 `sessions.append` → clock 的事件旁路。
而旧 `sse.detach()` 把这四个槽一律设成 `None`，把 clock 装的旁路永久抹掉：
于是任何"起过网页服务再关掉"的判据，都会在它之后的所有用例里掐断这条链。
这解释了全部现象：单跑绿、跑过服务那批文件之后必红、且"两半都能引爆"（任一支服务文件都够）。

## 这一组守什么

1. 正题：装一个来宾 append 钩子 → `sse.attach()` → `sse.detach()` ⇒ 那个钩子必须回来；
2. 反真空：`detach()` 之前先清掉 `_PREV`（模拟旧实现"一律设 None"）⇒ 来宾钩子必须消失，
   也就是说第 1 条真的在守这件事；
3. 另一半（2026-11-03 补）：钩子被清成 `None` 之后，下一次 `build_registry` 必须把它装回来
   —— `clock_tools._HOOK_INSTALLED` 是"只装一次"的闩锁，信它就会让观测链永久消失。
"""
from __future__ import annotations

import pathlib

from agentflow import sessions as SS
from agentflow.webui import sse


def test_detach_restores_the_foreign_append_hook(tmp_path: pathlib.Path):
    """正题：attach/detach 之后，来宾挂上的 append 钩子必须还在。"""
    calls: list = []

    def guest(root, event):  # noqa: ANN001
        calls.append((root, event))

    SS.set_append_hook(guest)
    try:
        sse.begin_serving(heartbeat_sec=0)
        sse.attach()
        sse.detach()
        SS.append(tmp_path, {"kind": "probe", "role": "M"}, sid="s-probe")
        assert calls, "detach 之后来宾钩子不再被调用 ⇒ 它被抹掉了（clock 的旁路就是这样丢的）"
    finally:
        SS.set_append_hook(None)


def test_the_old_behaviour_would_drop_it(tmp_path: pathlib.Path):
    """反真空：把 `_PREV` 清空再 detach（= 旧实现）⇒ 来宾钩子消失。"""
    calls: list = []

    def guest(root, event):  # noqa: ANN001
        calls.append((root, event))

    SS.set_append_hook(guest)
    try:
        sse.begin_serving(heartbeat_sec=0)
        sse.attach()
        sse._PREV.clear()          # 模拟"没有记账 ⇒ 一律设 None"
        sse.detach()
        SS.append(tmp_path, {"kind": "probe", "role": "M"}, sid="s-probe-2")
        assert not calls, "这次应当被抹掉 —— 否则第 1 条是恒真的假绿"
    finally:
        SS.set_append_hook(None)


def test_build_registry_reinstalls_the_clock_hook_after_it_was_cleared(tmp_path):
    """负控：钩子被清成 None 之后，下一次 `build_registry` 必须重新装上（不是报 "already"）。

    为什么这条必须存在：`sessions._APPEND_HOOK` 是进程级单槽，`clock_tools` 的观测器
    （`_observe_session_event`）挂在上面，而清除者不止一个文件（本文件、`test_webui*`）。
    旧实现信 `_HOOK_INSTALLED` 这个布尔闩锁 ⇒ 槽被清掉之后再装配直接返回 `already`，
    `observe_work` / `observe_message` 再也不跑（`parked_steps` / `delivery` 恒 0）。
    """
    from agentflow.store import Store
    from agentflow.tools import build_registry
    from agentflow.tools import clock_tools as CT

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    build_registry(store=st, workspace_root=ws)
    assert SS._APPEND_HOOK is CT._observe_session_event, "前提：装配该把时钟观测器装上"
    SS.set_append_hook(None)          # 模拟网页端判据的清除
    build_registry(store=st, workspace_root=ws)
    assert SS._APPEND_HOOK is CT._observe_session_event, (
        "_HOOK_INSTALLED 让装配报了 already、钩子没装回来 ⇒ 时钟观测链永久消失")
