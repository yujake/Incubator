# -*- coding: utf-8 -*-
"""判据：起服务的人要负责撤钩子 —— `server_close()` 之后 `sse` 的四个写路径钩子必须没了。

## 真因（2026-10-29 二分定位，逐条可核）

`test_clock_governs_all_timed_work` 的 test_h / test_h3 / test_j「单跑绿、全量红」。
按 pytest 默认收集顺序二分到 4 个文件的窗口，触发器是
`tests/test_cache_warm_button_is_honest.py`（它直接调 `serve()` 起真服务器）：

```
[102,106) + clock  ⇒ 3 failed（复现）
其中也只有 test_cache_warm_button_is_honest 单独和 clock 一起跑是绿的
   ⇒ 它是"把污染推过去"的那一个，不是唯一的污染源
```

机制：`serve()` 会 `sse.begin_serving()` + `sse.attach()`，把 `sessions.append` 换成一个
"顺便发 SSE 事件"的闭包；而撤钩子原先只在 `run()` 的 finally 里做。**直接调 `serve()` 的
判据**（本仓库有好几处）于是把钩子留在进程里 —— 之后所有用例的 `sessions.append` 都走
那条路，`observed_events()` 的计数不再增长，于是 clock 那三条读到"没有事件"。

## 这一组守什么

1. 正题：`serve()` 之后钩子是装上的；`server_close()` 之后一个都不剩；
2. 反真空：重新 `attach()` 再断言"钩子又有了" —— 也就是说上面那条真的在守这件事
   （把 `server_close` 里那次 `detach` 拿掉，第 1 条立刻红）。
"""
from __future__ import annotations

import pathlib

from agentflow.webui import server as S
from agentflow.webui import sse


def _attached() -> set:
    return set(getattr(sse, "_ATTACHED", set()) or set())


def test_closing_the_server_releases_the_sse_hooks(tmp_path: pathlib.Path):
    """正题：起服务装钩子，`server_close()` 之后钩子必须撤干净。"""
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    srv = S.serve(root, port=0)
    try:
        assert _attached(), "起服务时四个写路径钩子应当是装上的（否则这条判据没有对象）"
    finally:
        srv.server_close()
    assert _attached() == set(), f"关服务之后还留着钩子：{sorted(_attached())}"
    assert sse.serving() is False, "关服务之后这一代应当是结束的"


def test_the_reading_would_catch_a_missing_detach(tmp_path: pathlib.Path):
    """反真空：重新装上钩子 ⇒ `_attached()` 又非空（说明第 1 条不是恒真）。"""
    sse.begin_serving(heartbeat_sec=0)
    sse.attach()
    try:
        assert _attached(), "装回去之后应当读得到钩子 —— 否则第 1 条是恒真的假绿"
    finally:
        sse.detach()
    assert _attached() == set()
