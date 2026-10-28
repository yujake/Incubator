# -*- coding: utf-8 -*-
"""判据：同一个工作区"开网页"要一次命令、同一个地址（不再每次挑随机端口）。

## 现场（业主 2026-10-28：「为什么开网页还是那么累？优化」）

改前每次起服务都 `--port 0` 让系统挑：于是"开网页"是四步（挑端口 / 起进程 / 从输出抓
URL / 把 URL 抄给人），重启一次地址就变、上一份链接立刻失效。

## 这一组守什么

1. 复用：登记端口上服务的正是这个工作区 ⇒ `ensure_serving` 回 `reuse`（不起第二个）；
2. 让路：登记端口被别的程序占着 ⇒ 回 `start` 且换一个真能绑的端口（不静默双绑）；
3. 口径：显式给了端口 ⇒ 一律 `start`（不替调用方猜）；
4. 反真空：换了端口之后那个端口真的能绑（不是只把数字换个样子）。
"""
from __future__ import annotations

import pathlib
import socket

import pytest

from agentflow.webui import server as S


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_the_same_workspace_reuses_the_server_already_serving_it(tmp_path: pathlib.Path,
                                                                 monkeypatch: pytest.MonkeyPatch):
    """正题：登记端口上服务的正是这个工作区 ⇒ reuse（不起第二个）。"""
    root = _root(tmp_path)
    monkeypatch.setattr(S, "recorded_port", lambda r: 8788)
    monkeypatch.setattr(S, "verify_serving",
                        lambda url, *, root: {"state": "ok", "reason": ""})
    got = S.ensure_serving(root)
    assert got["action"] == "reuse", got
    assert got["port"] == 8788 and got["url"].endswith(":8788/"), got


def test_a_foreign_occupant_makes_it_move_to_a_free_port(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    """让路：登记端口被别人占着 ⇒ start，且选中的端口真能绑。"""
    root = _root(tmp_path)
    monkeypatch.setattr(S, "recorded_port", lambda r: 8788)
    monkeypatch.setattr(S, "verify_serving",
                        lambda url, *, root: {"state": "mismatch", "reason": "别的工作区"})
    monkeypatch.setattr(S, "port_owner",
                        lambda host, port: {"checked": True, "state": "busy", "root": "别的"})
    got = S.ensure_serving(root)
    assert got["action"] == "start", got
    assert got["port"] != 8788 and got["port"] > 0, got
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((S.DEFAULT_HOST, int(got["port"])))   # 不抛 ⇒ 那个端口真空着


def test_an_explicit_port_is_never_reused(tmp_path: pathlib.Path,
                                          monkeypatch: pytest.MonkeyPatch):
    """口径：显式给端口 ⇒ 一律 start（不替调用方猜）。"""
    root = _root(tmp_path)
    monkeypatch.setattr(S, "recorded_port", lambda r: 8788)
    monkeypatch.setattr(S, "verify_serving",
                        lambda url, *, root: {"state": "ok", "reason": ""})
    got = S.ensure_serving(root, port=9123)
    assert got["action"] == "start" and got["port"] == 9123, got


def test_the_port_is_written_down_and_read_back(tmp_path: pathlib.Path):
    """落盘：写下去再读回来是同一个数（复用全靠这一格）。"""
    root = _root(tmp_path)
    assert S.recorded_port(root) is None
    assert S.write_port_file(root, 8788, "http://127.0.0.1:8788/") == ""
    assert S.recorded_port(root) == 8788
    assert (root / S.PORT_FILE_NAME).is_file()
