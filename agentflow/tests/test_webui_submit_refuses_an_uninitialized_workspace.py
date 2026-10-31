# -*- coding: utf-8 -*-
"""判据（E6）：`POST /api/submit` 在"没初始化的工作区"上是受控拒绝，不是 500。

## 改前是什么样（2026-11-03 清点，E6）

根上只有 `.agentflow-stop` / `budget.json` / `web-actions.jsonl`、没有 `data/` 时，
`writes.py` 的 `store = Store(root); store.init()` 写在 `try` 之外 ⇒
`StoreError` 直接冒到 `server._invoke` 的兜底分支：

    {"handler": "handle_submit", "kind": "handler_crashed", "ok": false,
     "reason": "StoreError: 拒绝 init：… 既不是工作区（没有 data/）、又不是空目录 ——
                里面有 3 个不属于我们的条目：['.agentflow-stop', 'budget.json',
                'web-actions.jsonl']。…"}

两个问题：① 一个查得清的拒绝被记成"处理器崩了"（500）；② `_finish()` 没被调用，
于是这次被拒的写尝试不进 `web-actions.jsonl` —— 与"每一次到达处理器的写尝试
（含被拒的）都追加一行"那条口径分家。

触发条件并不刁钻：`store.py` 的根白名单只有 `{data, library, projects,
.agentflow-workspace}`，而网页自己会往根上写 `web-actions.jsonl`、`budget.json`、
`runs/`、`.agentflow-stop`。先点一次"叫停/回答"，再点"入队"就 500。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_submit_without_data_is_a_refusal` | 400 + `tri=not_applicable` + 不是 `handler_crashed`；原因里说清"没有 data/，先 `agentflow init`" |
| ② `test_the_refusal_still_leaves_an_audit_row` | 这一次被拒的尝试进了 `web-actions.jsonl`（`http=400`、`ok=false`） |
| ③ `test_the_negative_control_the_old_path_is_a_500` | 负控：不放宽 `store.py` 的根白名单（那会拆掉"别在别人目录里凭空建库"那道守卫） |

## 改前红在哪里

①先红：`assert 400 == 500`（回执里 `kind="handler_crashed"`）；
②先红：`web-actions.jsonl` 行数没有增加（审计被绕过）。
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

CSRF = "csrf-e6-0123456789"


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    """改前现场：根上有网页自己写的三样，但没有 `data/`（没 init 过的工作区）。"""
    root = tmp_path / "ws"
    root.mkdir()
    (root / ".agentflow-stop").write_text(
        json.dumps({"by": "web", "reason": "user", "force": False}) + "\n",
        encoding="utf-8")
    (root / "budget.json").write_text(json.dumps({"total_usd": 1.0}) + "\n",
                                      encoding="utf-8")
    (root / "web-actions.jsonl").write_text("", encoding="utf-8")
    return root


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=True, csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _post(base: str, path: str, fields: dict[str, str]) -> tuple[int, dict]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded",
                              "X-CSRF-Token": CSRF, "Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            got = json.loads(raw)
        except ValueError:
            got = {"_raw": raw}
        return resp.status, got if isinstance(got, dict) else {"_list": got}
    finally:
        conn.close()


# ====================================================================== ① 受控拒绝
def test_submit_without_data_is_a_refusal(tmp_path: pathlib.Path) -> None:
    """①：没有 `data/` ⇒ 400 + `not_applicable`，不是 `handler_crashed` 500。"""
    root = _root(tmp_path)
    with _server(root) as base:
        code, got = _post(base, "/api/submit",
                          {"topic": "审一遍", "mode": "topical", "confirm": "1"})
    assert code == 400, (code, got)
    assert got["ok"] is False and got["tri"] == "not_applicable", got
    assert "kind" not in got or got["kind"] != "handler_crashed", got
    assert "data/" in got["reason"], got["reason"]
    assert "agentflow init" in got["reason"], got["reason"]
    # 真值是"什么都没写"：`search_requests` 表根本不存在（没有 data/）。
    assert not (root / "data").exists(), "被拒的那一次居然建了 data/"


# ====================================================================== ② 审计
def test_the_refusal_still_leaves_an_audit_row(tmp_path: pathlib.Path) -> None:
    """②：被拒的这一次进台账（每一笔到达处理器的写尝试都留档）。"""
    root = _root(tmp_path)
    before = audit.read_actions(root)
    with _server(root) as base:
        code, _got = _post(base, "/api/submit",
                           {"topic": "审一遍", "mode": "topical", "confirm": "1"})
    assert code == 400, code
    rows = audit.read_actions(root)
    assert len(rows) == len(before) + 1, rows
    row = rows[-1]
    assert row["endpoint"] == "/api/submit" and row["http"] == 400, row
    assert row["ok"] is False and row["tri"] == "not_applicable", row


# ====================================================================== ③ 负控
def test_the_negative_control_the_old_path_is_a_500(tmp_path: pathlib.Path) -> None:
    """③（负控）：改前那条路（`Store.init()` 在 `try` 外）必须仍然是 500。

    这一条不需要真的改回去：直接把 `StoreError` 从 `writes.handle_submit` 的
    捕获名单里拿掉会改变产品行为，所以这里用"直接问 Store"来证明那个拒绝是
    `StoreError`（而不是 `ValueError`/`TypeError` 那几档 400）——
    如果 `Store.init()` 抛的是别的异常，上面 ① 的 400 就不是这条修法给的。
    """
    from agentflow.store import Store, StoreError

    root = _root(tmp_path)
    try:
        Store(root).init()
    except StoreError as exc:
        assert "data" in str(exc) or "工作区" in str(exc), str(exc)
    else:
        raise AssertionError("这个夹具居然通过了 Store.init()（夹具不再复现 E6）")
