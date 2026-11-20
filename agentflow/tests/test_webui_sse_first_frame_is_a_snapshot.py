# -*- coding: utf-8 -*-
"""判据：`/api/stream` 连上就发首帧（一份当前快照），不等 15 秒心跳。

## 改前是什么样（`draft/187` P3-3 的现场读数）

真机连上 `GET /api/stream` 只收到响应头（215B），第一帧在 15.1s（那一帧是心跳），
第二帧 30.2s。首屏本来靠 `/api/state`，所以页面不算白屏，但「连上了」与「收到第一帧」
之间那 15 秒空窗会被读成卡死 —— 而这一条流的意义正是"从此以后有变化就推给你"。

## 修法与它的两条硬约束

连上之后立刻发一条 `kind=state` 的帧（`{snapshot, reason}`）；它必须不带 `id:`：
这一帧没有被 `publish` 过，吃一个编号会让同一客户端的下一次 `?since=` 跳过一段真实事件
（`draft/73 §2.4` 的补发契约）。

## 三条

1. 首帧在 1 秒内（心跳周期调到 5 秒，证明它不等心跳）；
2. 首帧是 `state` 且带 `snapshot`（页面按这一档处置：`live.tsx` 的 `state` handler）；
3. 不带 `id:` —— 正控里先 `publish` 两条（拿到 id 1/2），再连上：首帧的 id 必须是
   `None`（否则客户端会把 1 当成"已经收到的最后一条"）；反真空：带 id 的帧格式确实能
   读出 id（证明"读不到 id"不是因为解析器瞎了）。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from agentflow import webui as W
from agentflow.webui import sse


@contextmanager
def _bound_server(root: pathlib.Path, *, heartbeat_sec: float) -> Iterator[Any]:
    sse.begin_serving(heartbeat_sec=heartbeat_sec)
    srv = W.serve(root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        sse.close_all()
        thread.join(timeout=5.0)


def _open(base: str, path: str) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(base, timeout=5)
    conn.request("GET", path)
    return conn.getresponse()


def _read_frames(resp: http.client.HTTPResponse, *, want: int, timeout: float,
                 ) -> list[tuple[str, int | None, str]]:
    """读 `want` 帧；返回 `[(kind, id, data), ...]`（超时就返回已读到的）。"""
    out: list[tuple[str, int | None, str]] = []
    resp.fp.raw._sock.settimeout(timeout)  # noqa: SLF001 - 判据要能超时收手
    buf = b""
    while len(out) < want:
        try:
            chunk = resp.fp.read1(4096)  # noqa: SLF001
        except (socket.timeout, TimeoutError, OSError):
            break
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            kind, eid, data = None, None, ""
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("id: "):
                    eid = int(line[4:])
                elif line.startswith("data: "):
                    data = line[6:]
            if kind is not None:
                out.append((kind, eid, data))
    return out


# ====================================================================== 1 首帧
def test_the_first_frame_is_a_snapshot_without_waiting_for_the_heartbeat(
        tmp_path: pathlib.Path) -> None:
    """心跳 5 秒时，首帧仍必须 1 秒内到，且是 `state` + `snapshot`。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root, heartbeat_sec=5.0) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        resp = _open(f"{host}:{port}", "/api/stream")
        try:
            began = time.monotonic()
            got = _read_frames(resp, want=1, timeout=1.0)
            elapsed = time.monotonic() - began
        finally:
            resp.close()
    assert got, f"1 秒内一帧都没收到（等了 {elapsed:.2f}s）—— 首帧仍在等 5 秒的心跳"
    kind, event_id, data = got[0]
    assert kind == "state", (kind, data)
    assert elapsed < 1.0, elapsed
    payload = json.loads(data)
    assert "snapshot" in payload, payload
    # 硬约束：这一帧不是广播出来的，不许吃编号。
    assert event_id is None, (
        f"首帧带了 id={event_id} —— 它没被 publish 过，吃了编号会让下一次 ?since= 跳过事件")


# ====================================================================== 2 反向
def test_a_published_frame_does_carry_an_id(tmp_path: pathlib.Path) -> None:
    """反真空：广播出去的事件帧带 id —— 证明上一条的「读不到 id」不是解析器瞎了。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _bound_server(root, heartbeat_sec=5.0) as srv:
        host, port = srv.server_address[0], srv.server_address[1]
        bc = sse.default_broadcaster()
        first = bc.publish("state", {"n": 1})
        second = bc.publish("question", {"qid": "q0001", "sid": "t"})
        resp = _open(f"{host}:{port}", f"/api/stream?since={first}")
        try:
            got = _read_frames(resp, want=2, timeout=1.0)
        finally:
            resp.close()
    assert got, "带 since 的连接一帧都没收到"
    kinds = [kind for kind, _eid, _data in got]
    assert "question" in kinds, got
    # 首帧（快照）之后，补发的那一条必须带着 broadcast 器的编号（= second）。
    published = [(kind, eid) for kind, eid, _data in got if eid is not None]
    assert ("question", second) in published or ("question", 2) in published, (
        kinds, published)
