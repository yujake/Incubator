# -*- coding: utf-8 -*-
"""判据：处理器抛了也必须回 500 + 原因，不许"服务器活着、却把连接直接关掉"。

## 真机（2026-10-28）

`serve web` 把 URL 打了出来，而 `/api/state` 的请求被直接关掉（客户端看到
`RemoteDisconnected: Remote end closed connection without response`，裸 socket 首行是空的）。
原因是没有兜底：处理器一抛，`BaseHTTPRequestHandler` 只 `close_connection`，服务器活着却
什么都不说 —— `verify_serving` 自证只能报"打不通"。

## 这一组守什么

1. 处理器抛 ⇒ `_invoke` 回 500 JSON，正文点名处理器与异常；
2. 正常处理器 ⇒ 照旧把请求交给它（这次兜底没有改变成功路径）；
3. 客户端自己断开（`BrokenPipeError`）⇒ 不写成 500（那是对端的事，硬写会再造异常）。
"""
from __future__ import annotations

import pytest

from agentflow.webui import server as S


class _FakeHandler:
    """只记 `_json` / `_send` 的最小句柄（`_invoke` 要的就是这两格 + 处理器方法）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _json(self, code: int, obj: dict) -> None:
        self.calls.append(("json", int(code), dict(obj)))

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict | None = None) -> None:
        self.calls.append(("send", int(code), body.decode("utf-8", "replace")))


def test_a_crashing_handler_answers_500_with_the_reason():
    """正题：处理器抛 ⇒ 500 + 原因。"""

    def boom(params, query) -> None:
        raise RuntimeError("状态读数炸了")

    handler = _FakeHandler()
    setattr(handler, "boom", boom)
    S.WebHandler._invoke(handler, "boom", {}, {})
    assert handler.calls, "处理器抛了却一个字都没回（客户端会看到断连）"
    kind, code, payload = handler.calls[-1]
    assert kind == "json" and code == 500, handler.calls
    assert payload.get("kind") == "handler_crashed", payload
    assert "状态读数炸了" in str(payload.get("reason")), payload


def test_a_working_handler_is_still_handed_the_request():
    """正控：成功路径一个字没变（照旧把参数交给处理器）。"""

    seen: dict = {}

    def fine(params, query) -> None:
        seen["called"] = True
        seen["params"] = dict(params)

    handler = _FakeHandler()
    setattr(handler, "fine", fine)
    S.WebHandler._invoke(handler, "fine", {"a": "1"}, {})
    assert seen.get("called") is True, seen
    assert handler.calls == [], handler.calls


def test_a_broken_pipe_is_not_turned_into_a_500():
    """反真空：客户端自己断开 ⇒ 不吞成 500。"""

    def gone(params, query) -> None:
        raise BrokenPipeError("对端断了")

    handler = _FakeHandler()
    setattr(handler, "gone", gone)
    with pytest.raises(BrokenPipeError):
        S.WebHandler._invoke(handler, "gone", {}, {})
    assert handler.calls == [], handler.calls
