# -*- coding: utf-8 -*-
"""判据：四条写路径的会话基线必须在测试模块导入之前拍下（conftest 导入期）。

## 真因（2026-11-01 逐条可核）

`tests/test_agent_prompts.py:1533` 在模块导入期执行

```python
REGISTRY = build_registry().registry
```

而 `src/agentflow/tools/__init__.py:726` 的 `build_registry()` 会经
`clock_tools._install_append_hook()` 把时钟观测器 `_observe_session_event` 挂到
`sessions._APPEND_HOOK` 上。pytest 在收集阶段导入测试模块，于是这条副作用发生在
「第一条判据 setup」之前、但在 `tests/conftest.py` 导入之后。

会话基线若交给 session 级夹具在「第一条判据 setup」时拍（改前的实现），拍到的就是
这条别的测试模块的导入期副作用；而每条判据收尾又按这份基线把钩子装回槽里 ⇒
紧接着的 `sse.attach()` 如实报 `replaced=('append',)` ⇒
`tests/test_webui_sse.py::test_attach_wires_all_four_write_paths` 单跑绿、宽邻域红
（2026-11-01 实测：`pytest tests/test_agent_prompts.py tests/test_webui_sse.py -q`
= 1 failed / 85 passed）。

## 这一份守什么

本文件在自己的导入期再放一次同源副作用（`build_registry()`，与上面那行同一机制），
于是：

- 拍摄在导入期（现实现）⇒ 基线里 `append` 是 `None` ⇒ 绿；
- 有人把拍摄挪回 session 夹具 ⇒ 基线里 `append` 是 `clock_tools._observe_session_event`
  ⇒ 本用例当场红，而且不依赖 `test_agent_prompts.py` 在不在这趟运行里。

这条判据守的是"装置"，不是产品：它红的时候，被怀疑的应当是
`tests/conftest.py` 里那道基线的拍摄时点，而不是任何产品代码。
"""
from __future__ import annotations

from agentflow.tools import build_registry
from agentflow.tools import clock_tools as CT

#: 导入期就跑一次装配 —— 与 `tests/test_agent_prompts.py:1533` 同一机制（那一行是真出处）：
#: `build_registry()` 把时钟观测器挂到 `sessions._APPEND_HOOK`。pytest 收集阶段导入本模块，
#: 所以这个副作用一定发生在「第一条判据 setup」之前；基线若拍在那之后就会把它吃进去。
POLLUTER = build_registry()


def test_the_session_baseline_was_captured_before_this_module_was_imported(
        write_path_hook_baseline: dict) -> None:
    """基线里不许含时钟观测器（含了 = 基线是在测试模块导入之后拍的）。"""
    baseline = write_path_hook_baseline
    assert baseline["append"] is not CT._observe_session_event, (
        "会话基线里含时钟观测器 `clock_tools._observe_session_event` ⇒ 基线是在测试模块"
        "导入之后拍的（别的模块的导入期副作用被当成了会话起点）。拍点必须挪回 "
        "`tests/conftest.py` 的导入期（见 `_WRITE_PATH_HOOK_BASELINE` 上方那段），"
        "否则 `sse.attach()` 会把这条外来钩子如实报成 `replaced=('append',)`。")
    assert baseline["append"] is None, (
        f"会话基线里 append 槽不是空的：{baseline['append']!r} ⇒ 基线不干净")
    assert baseline["installed"] is False, (
        f"会话基线里时钟装配闩锁是 {baseline['installed']!r} ⇒ 基线带着导入期的装配读数")
    # 反真空：本文件的那条导入期副作用真的发生过（否则上面两句可能只是"没人装过"）。
    assert POLLUTER is not None, "`build_registry()` 没跑（这条判据的前提不成立）"
