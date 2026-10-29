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
   也就是说第 1 条真的在守这件事。
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
