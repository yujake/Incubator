# -*- coding: utf-8 -*-
"""判据（E7）：`allow_writes=False` 的服务一个字节都不往工作区写。

## 改前是什么样（2026-11-03 清点，E7）

`writes._finish()` 无条件 `audit.record_action`，而 `server.py` 的模块 docstring 与
`--help` 把缺省档叫"只读"。于是只发过 GET + 几条被拒的 POST 的只读服务，会在
别人的工作区根上新建 `web-actions.jsonl`（实测：`projects/chain-v1` 与
`projects/p6t2-research-20261012` 各被创建，内容全是 403/409 的"被拒"行）。

这不只是口径问题：那一行审计正是让下一次 `Store.init()` 拒绝该目录的原因
（E6 的现场里 `web-actions.jsonl` 就是"3 个不属于我们的条目"之一）。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_a_read_only_service_writes_nothing_into_the_workspace` | 只读档：GET + 三条被拒的 POST 之后，工作区目录里一个字节都没变（没有 `web-actions.jsonl`，也没有 `.lock`） |
| ② `test_the_refusal_says_the_audit_was_not_written` | 被拒的回执如实说"没有落审计"（`extra.audit.tri=not_applicable` + 一句原因），不是假装记了 |
| ③ `test_an_open_write_face_still_audits_refusals` | 负控（口径的另一半）：`--allow-writes` 开了之后，被拒的尝试照旧留档 —— 修法不许把审计整个关掉 |

## 改前红在哪里

①先红：`assert not (root / "web-actions.jsonl").exists()` —— 只读服务已经把它建出来了
（3 行：403 / 409 / 403）。②也红：回执里 `extra.audit.tri == "computed"`。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import threading
import urllib.parse
from contextlib import contextmanager
from typing import Iterator

from agentflow import webui as W
from agentflow.webui import audit

CSRF = "csrf-e7-0123456789"


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个裸目录（没有 `data/`）：只读服务连"附带产物"都不许留下。"""
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _names(root: pathlib.Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


@contextmanager
def _server(root: pathlib.Path, *, allow_writes: bool) -> Iterator[str]:
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> int:
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def _post(base: str, path: str, fields: dict[str, str], *,
          csrf: str = CSRF) -> tuple[int, dict]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            got = json.loads(raw)
        except ValueError:
            got = {"_raw": raw}
        return resp.status, got if isinstance(got, dict) else {"_list": got}
    finally:
        conn.close()


# ====================================================================== ① 只读不写盘
def test_a_read_only_service_writes_nothing_into_the_workspace(
        tmp_path: pathlib.Path) -> None:
    """①：只读档下，GET 与三条被拒的写尝试之后目录里一个字节都没变。"""
    root = _root(tmp_path)
    before = _names(root)
    with _server(root, allow_writes=False) as base:
        assert _get(base, "/api/state") == 200
        assert _get(base, "/") == 200
        code_stop, _ = _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
        assert code_stop == 403, code_stop
        code_ans, _ = _post(base, "/answer", {"qid": "q0001", "sid": "t",
                                              "selected": "甲"}, csrf="")
        assert code_ans == 409, code_ans
        code_submit, _ = _post(base, "/api/submit", {"topic": "t", "confirm": "1"})
        assert code_submit == 403, code_submit
    assert _names(root) == before, f"只读服务在根上留下了 {_names(root)!r}"
    assert not (root / audit.LEDGER_NAME).exists(), "只读服务写了审计台账"
    assert not (root / (audit.LEDGER_NAME + ".lock")).exists(), "只读服务留下了台账锁文件"


# ====================================================================== ② 回执说实话
def test_the_refusal_says_the_audit_was_not_written(tmp_path: pathlib.Path) -> None:
    """②：被拒的回执里 `extra.audit` 如实说"没有落盘"，不是假装记了。"""
    root = _root(tmp_path)
    with _server(root, allow_writes=False) as base:
        code, got = _post(base, "/api/stop", {"reason": "user", "confirm": "1"})
    assert code == 403, (code, got)
    extra = got.get("extra") or {}
    audit_info = extra.get("audit") or {}
    assert audit_info.get("tri") == "not_applicable", audit_info
    assert "只读" in str(audit_info.get("reason") or ""), audit_info
    assert "web-actions.jsonl" in str(audit_info.get("reason") or ""), audit_info


# ====================================================================== ③ 负控
def test_an_open_write_face_still_audits_refusals(tmp_path: pathlib.Path) -> None:
    """③（负控）：开了 `--allow-writes` 之后，被拒的尝试照旧留一行。"""
    root = _root(tmp_path)
    with _server(root, allow_writes=True) as base:
        code, got = _post(base, "/api/stop", {"reason": "user", "confirm": "1"},
                          csrf="wrong-csrf-token")
    assert code == 403 and "CSRF" in got["reason"], (code, got)
    rows = audit.read_actions(root)
    assert len(rows) == 1, rows
    assert rows[0]["endpoint"] == "/api/stop" and rows[0]["http"] == 403, rows[0]
    assert rows[0]["tri"] == "not_applicable" and rows[0]["ok"] is False, rows[0]
