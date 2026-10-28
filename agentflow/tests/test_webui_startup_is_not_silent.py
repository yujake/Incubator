# -*- coding: utf-8 -*-
"""判据：网页服务起不来时必须说出来，不许"绑上了、打印 URL、空转"。

## 真机（2026-10-28，两次撞同一面墙）

第一次：后台作业被 kill 时只死了 `pwsh` 外壳，`python -m agentflow … serve web` 还活着、
仍占着 8787，而且已经半死（接受连接、一个字节都不回）。第二次：新服务起在同一端口上，
`ThreadingHTTPServer`（`http.server.HTTPServer.allow_reuse_address = 1`）在 Windows 的
`SO_REUSEADDR` 下"绑定成功"、永远收不到连接，却照样把 `{"url": …8787…}` 打出来 ——
读报表的人以为它在服务。没有任何地方会红。

## 这一组守什么

1. 端口已被占 ⇒ 受控拒绝（非零、点名占位者），不许悄悄绑成第二份；
2. `port=0` 永远放行（那是"让系统挑"，不构成撞车）；
3. 绑完自证：`verify_serving(url, root)` 三态 —— 200 且 root 对得上才 `ok`；
   root 不对是 `mismatch`；连不上是 `unknown`（不许折成 ok）；
4. 负控：把 `allow_reuse_address` 改回 1（即"退回改前"）⇒ 判据 1 必须红。
"""
from __future__ import annotations

import pathlib
import threading

import pytest

from agentflow.webui import server as WS


def _srv(root: pathlib.Path, port: int = 0):
    return WS.serve(root, host="127.0.0.1", port=port, token="", allow_writes=False)


def _run(srv):
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return th


def _stop(srv, th):
    srv.shutdown()
    srv.server_close()
    th.join(timeout=5)


def _ws(tmp_path: pathlib.Path, name: str = "ws") -> pathlib.Path:
    ws = tmp_path / name
    (ws / "data").mkdir(parents=True)
    return ws


# ---------------------------------------------------------------- 1) 撞车


def test_a_second_server_on_the_same_port_is_refused(tmp_path: pathlib.Path):
    """端口已被占 ⇒ 必须受控拒绝，不许"绑定成功"。

    改前的形态就是这条会红的那一版：`allow_reuse_address = 1` 让第二个 bind 静默成功。
    """
    ws = _ws(tmp_path)
    first = _srv(ws)
    th = _run(first)
    try:
        port = int(first.server_address[1])
        with pytest.raises(WS.WebStartupError) as ei:
            _srv(ws, port=port)
        msg = str(ei.value)
        assert str(port) in msg, msg
        assert "占用" in msg or "占用" in msg, msg
    finally:
        _stop(first, th)


def test_the_refusal_names_the_occupant(tmp_path: pathlib.Path):
    """拒绝要说清占位者是谁（这一格才是"人不用自己 netstat"的那一步）。"""
    ws = _ws(tmp_path)
    first = _srv(ws)
    th = _run(first)
    try:
        port = int(first.server_address[1])
        with pytest.raises(WS.WebStartupError) as ei:
            _srv(ws, port=port)
        owner = getattr(ei.value, "owner", {}) or {}
        assert owner.get("state") == "busy", owner
        assert str(owner.get("root") or "") == str(ws.resolve()), owner
    finally:
        _stop(first, th)


def test_a_free_port_is_never_refused(tmp_path: pathlib.Path):
    """`port=0` 永远放行：那是"让系统挑"，不是撞车（正控，防修过头）。"""
    ws = _ws(tmp_path)
    a = _srv(ws)
    b = _srv(ws)
    try:
        assert int(a.server_address[1]) != int(b.server_address[1])
    finally:
        a.server_close()
        b.server_close()


def test_negative_control_without_the_probe_the_collision_is_silent(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """负控：把端口探测摘掉（假装"端口是空的"）⇒ 第二个服务不再被拒 ⇒ 判据 1 必须红。

    为什么这条负控打在这里而不是打 `allow_reuse_address`：Windows 的 `SO_REUSEADDR`
    本来就让第二个 bind 静默成功 —— 所以"能不能拒绝"完全取决于探测那一步在不在。
    没有这一条，"判据 1 会红"只是我一句话。
    """
    ws = _ws(tmp_path)
    first = _srv(ws)
    th = _run(first)
    try:
        port = int(first.server_address[1])
        monkeypatch.setattr(WS, "port_owner",
                            lambda *a, **k: {"checked": True, "state": "free", "root": "",
                                             "pid": 0, "reason": "负控：探测被摘掉"})
        second = None
        try:
            second = _srv(ws, port=port)
        except WS.WebStartupError:
            pytest.fail("摘掉探测之后仍然拒绝 ⇒ 判据 1 分辨不出'有探测'与'没探测'")
        finally:
            if second is not None:
                second.server_close()
    finally:
        _stop(first, th)


# ---------------------------------------------------------------- 2) 绑完自证


def test_the_self_check_passes_on_a_real_server(tmp_path: pathlib.Path):
    ws = _ws(tmp_path)
    srv = _srv(ws)
    th = _run(srv)
    try:
        url = f"http://127.0.0.1:{int(srv.server_address[1])}/"
        got = WS.verify_serving(url, root=ws)
        assert got["state"] == "ok", got
        assert got["code"] == 200, got
    finally:
        _stop(srv, th)


def test_the_self_check_tells_a_wrong_root_apart_from_a_dead_port(tmp_path: pathlib.Path):
    """三态：root 不对 ⇒ `mismatch`；连不上 ⇒ `unknown`。两者都不许是 ok。"""
    ws = _ws(tmp_path)
    srv = _srv(ws)
    th = _run(srv)
    try:
        url = f"http://127.0.0.1:{int(srv.server_address[1])}/"
        wrong = WS.verify_serving(url, root=tmp_path / "someone-else")
        assert wrong["state"] == "mismatch", wrong
        assert str(wrong["root"]) == str(ws.resolve()), wrong
    finally:
        _stop(srv, th)
    dead = WS.verify_serving(f"http://127.0.0.1:{int(srv.server_address[1])}/", root=ws,
                             timeout=1.0)
    assert dead["state"] == "unknown" and dead["code"] == 0, dead


def test_the_occupant_probe_is_three_state_on_a_free_port(tmp_path: pathlib.Path):
    """端口没人听 ⇒ `free`（不是"有东西但不认识"）。"""
    ws = _ws(tmp_path)
    srv = _srv(ws)
    port = int(srv.server_address[1])
    srv.server_close()
    got = WS.port_owner("127.0.0.1", port)
    assert got["state"] == "free", got
