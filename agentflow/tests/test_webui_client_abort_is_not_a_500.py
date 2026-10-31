# -*- coding: utf-8 -*-
"""判据（E3）：客户端先走了，不许记成 `handler_crashed` 500。

## 改前是什么样（2026-11-03 清点，E3）

`server.py::_invoke` 的"对端没了"名单只有 `(BrokenPipeError, ConnectionResetError)`，
漏了 `ConnectionAbortedError`；而同一个文件的 `handle_one_request` 把三种都算"对端
没了"，`sse.py` 的流循环也把三种（还多一个 `OSError`）算正常终点 —— 三处对同一件事
有三种名单。

现场：一次浏览器套件（18 条，50.59 秒）在服务端日志里留下 27 条
`" 500 -`、27 条 `处理器 … 抛了`、27 段 traceback，异常全是
`ConnectionAbortedError: [WinError 10053] 你的主机中的软件中止了一个已建立的连接。`，
栈底统一是 `_send → wfile.write`。也就是说：一次正常导航被记成了一次服务端事故。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_every_peer_gone_exception_is_not_a_handler_crash` | 三种"对端没了"（`ConnectionAbortedError` / `ConnectionResetError` / `BrokenPipeError`）一律原样上抛：不回 500、不打"处理器 … 抛了" |
| ② `test_a_real_handler_error_is_still_a_500` | 负控：真异常（`ValueError`）照旧回 500 + 打日志 —— 修法不许把真错误一起吞掉 |
| ③ `test_the_peer_gone_list_is_one_constant` | 名单只有一处（`server.PEER_GONE`），`handle_one_request` 与 `_invoke` 共用它 |

## 改前红在哪里

①先红：对 `ConnectionAbortedError` 那一档，`_invoke` 回了一支
`{"ok": false, "kind": "handler_crashed", …}` 并往 stderr 打了 `处理器 … 抛了`
（另两种本来就是绿的 —— 这正是"三处三份名单"的形态：漏的只有一个）。
②③改前也红：`server.PEER_GONE` 不存在（`AttributeError`），
`handle_one_request` 与 `_invoke` 各写一份 tuple。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow.webui import server as WS


class _Handler:
    """`_invoke` 需要的最小句柄：一个会抛的处理器方法 + 两个回话出口。

    为什么不拿真套接字造这一条：这里要钉的是"哪一类异常算对端没了"，
    而真套接字那一侧（RST / FIN 的时机）在 Windows 上不稳定 —— 造一个"写到一半
    对端没了"的处理器，异常类型与真机日志里的那个完全相同
    （`ConnectionAbortedError(10053, …)`），判据因此是确定的而不是碰运气的。
    """

    _path = "/api/machine"

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.replies: list[tuple[Any, ...]] = []

    def handle_machine(self, params, query) -> None:
        raise self.exc

    def _json(self, code: int, obj: dict) -> None:
        self.replies.append((code, obj))

    def _send(self, code: int, body: bytes, ctype: str, *a, **k) -> None:
        self.replies.append((code, ctype))


#: 真机日志里那三种（`WinError 10053` 那一档就在其中）。
_PEER_GONE = (
    ConnectionAbortedError(10053, "你的主机中的软件中止了一个已建立的连接。"),
    ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"),
    BrokenPipeError(32, "管道已关闭。"),
)


# ====================================================================== ① 正控
@pytest.mark.parametrize("exc", _PEER_GONE, ids=lambda e: type(e).__name__)
def test_every_peer_gone_exception_is_not_a_handler_crash(
        exc: BaseException, capsys: pytest.CaptureFixture[str]) -> None:
    """①：三种"对端没了"都不回话、不记为崩溃（异常原样上抛给请求循环）。"""
    handler = _Handler(exc)
    with pytest.raises(type(exc)):
        WS.WebHandler._invoke(handler, "handle_machine", {}, {})
    err = capsys.readouterr().err
    assert handler.replies == [], f"客户端已经走了，还回了 {handler.replies}"
    assert "处理器" not in err, f"对端没了被记成处理器抛异常：{err!r}"


# ====================================================================== ② 负控
def test_a_real_handler_error_is_still_a_500(
        capsys: pytest.CaptureFixture[str]) -> None:
    """②（负控）：真异常照旧 500 + 日志（修法不许把真错误一起吞掉）。"""
    handler = _Handler(ValueError("这一格真坏了"))
    WS.WebHandler._invoke(handler, "handle_machine", {}, {})
    codes = [r[0] for r in handler.replies]
    assert codes == [500], handler.replies
    body = handler.replies[0][1]
    assert body["kind"] == "handler_crashed" and body["ok"] is False, body
    err = capsys.readouterr().err
    assert "处理器 handle_machine 抛了" in err and "ValueError" in err, err


# ====================================================================== ③ 名单一处
def test_the_peer_gone_list_is_one_constant() -> None:
    """③：名单只有一处，`handle_one_request` 与 `_invoke` 共用 `server.PEER_GONE`。"""
    assert WS.PEER_GONE == (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError), WS.PEER_GONE
    source = (pathlib.Path(WS.__file__).read_text(encoding="utf-8"))
    # 两处（请求循环、处理器调用）都用这一个名字，不再各自列一遍。
    assert source.count("except PEER_GONE") == 2, source.count("except PEER_GONE")
    # 写死的那三元组在整份源码里只出现一次（就是常量定义那一行）——
    # 多出一处就是"名单又抄了一份"，而两份名单迟早会漂（E3 就是这么来的）。
    assert source.count(
        "(ConnectionAbortedError, ConnectionResetError, BrokenPipeError)") == 1, (
            "除 PEER_GONE 之外还有一处手写的三元组（名单又分家了）")
