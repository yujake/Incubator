"""判据（鲁棒 f 的并发那一半）：只读服务上反复刷新 / 多标签页不产生任何写。

## 为什么这一条必须真起服务

"只读档一个字节都不往工作区写"这句话在 `writes._finish` 与 `audit` 的注释里写着，
但在屏上它是"刷新一下会不会多出文件"这个具体问题。只读两页源码证明不了：GET 的
处理器里可能有一次顺手落盘（审计 / 端口文件 / 缓存戳），而它只在真请求时发生。
所以本判据起一个 `serve(..., allow_writes=False)`（默认档），先给工作区拍一张
"路径 + 字节数 + mtime"的快照，再并发打十几次读端点，最后逐条比。

## 量法

- 并发：`ThreadPoolExecutor(max_workers=8)` 打 `/api/state`、`/api/evidence`、
  `/api/artifacts`、`/api/roster`、`/api/budget`、`/api/obligations` 各若干次
  （模拟多标签页一起刷新）；
- 快照：工作区下所有文件的相对路径、字节数、mtime_ns 三元组 —— 新增、删除、
  改写三种都逃不掉；
- 三态：全部响应必须是 200 + JSON；`/api/state` 的 `writes_allowed` 必须是 false
  （这一档就是"只读"，页面据此禁用写按钮，是同一个事实）。

反真空：把同一个工作区换成 `allow_writes=True` 再起一次，`writes_allowed` 必须变成
true（证明上面那条 false 不是写死的常量），而读数仍然不写盘（GET 不落审计）。
"""
from __future__ import annotations

import concurrent.futures
import http.client
import json
import pathlib
import threading

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow import webui as W

PATHS = ("/api/state", "/api/evidence", "/api/artifacts", "/api/roster",
         "/api/budget", "/api/obligations")


def _get(base: str, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        out[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return out


def _serve(root: pathlib.Path, *, allow_writes: bool):
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"{srv.server_address[0]}:{srv.server_address[1]}"
    return srv, thread, base


def _stop(srv, thread) -> None:
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5.0)


def test_refreshing_a_read_only_service_writes_nothing(tmp_path: pathlib.Path) -> None:
    """正控：并发读 30 次，工作区逐字节不变；state 说 writes_allowed=false。"""
    SS.append(tmp_path, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="2026-11-20")
    SS.append(tmp_path, {"kind": "agent_run_end", "role": "M", "task_id": "t-1"}, sid="2026-11-20")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "tasks.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": []}), encoding="utf-8")
    before = _snapshot(tmp_path)

    srv, thread, base = _serve(tmp_path, allow_writes=False)
    try:
        jobs = [PATHS[i % len(PATHS)] for i in range(30)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda p: (p, _get(base, p)), jobs))
        for path, (code, body) in results:
            assert code == 200, (path, code, body[:200])
            json.loads(body)
        code, body = _get(base, "/api/state")
        assert code == 200, (code, body[:200])
        assert json.loads(body)["writes_allowed"] is False, body[:200]
    finally:
        _stop(srv, thread)
    after = _snapshot(tmp_path)
    assert after == before, {
        "new": sorted(set(after) - set(before)),
        "gone": sorted(set(before) - set(after)),
        "changed": sorted(k for k in before if k in after and before[k] != after[k]),
    }


def test_the_switch_is_real_not_a_constant(tmp_path: pathlib.Path) -> None:
    """反真空：同一个工作区开 `allow_writes=True` ⇒ writes_allowed 变 true。"""
    SS.append(tmp_path, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="2026-11-20")
    srv, thread, base = _serve(tmp_path, allow_writes=True)
    try:
        code, body = _get(base, "/api/state")
        assert code == 200, (code, body[:200])
        assert json.loads(body)["writes_allowed"] is True, body[:200]
        # GET 仍然不写盘（审计只跟写请求走）。
        before = _snapshot(tmp_path)
        for _ in range(5):
            _get(base, "/api/state")
        assert _snapshot(tmp_path) == before
    finally:
        _stop(srv, thread)
