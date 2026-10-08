# -*- coding: utf-8 -*-
"""W5 负控插件（临时，不入库）：把 `WebHandler.handle_one_request` 的覆写换回基类那一份。

做法刻意不改盘上任何一个字节：只在测试进程里把那个方法重新绑定到
`http.server.BaseHTTPRequestHandler.handle_one_request`（也就是"覆写去掉"的语义）。
`serve()` 造出来的绑定类是 `type("BoundWebHandler", (WebHandler,), {...})`，
它按 MRO 取这个方法，于是拿到的就是基类那一份 —— 与"删掉覆写"逐字等价。

用法：
    $env:PYTHONPATH="<repo>\\agentflow\\src;<repo>\\temp"
    python -B -m pytest -q -p no:cacheprovider -p no:randomly -p w5_negctl_abort \
        tests/test_webui.py -k hangs_up
"""
from __future__ import annotations

import http.server


def pytest_configure(config) -> None:  # noqa: ANN001 - pytest 钩子签名
    """收集之前先把覆写摘掉。"""
    from agentflow.webui.server import WebHandler

    WebHandler.handle_one_request = (
        http.server.BaseHTTPRequestHandler.handle_one_request)
