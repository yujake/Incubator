# -*- coding: utf-8 -*-
"""判据（E4）：验收行的阈值是 `min` 或 `max` 二选一 —— 页面不许把 `undefined` 印上屏。

## 改前是什么样（2026-11-03 清点，E4）

盘上的形状（真项目原文，`projects/chain-v1/out/paper/ACCEPTANCE-CHECKS.json`）：

    {"id": "C3", "name": "请求闭环", "kind": "unfinished_request_rows", "max": 0, …}
    {"id": "C4", "name": "文献未消化", "kind": "literature_unprocessed_rows", "max": 0, …}

而 `readers.py` 的 `_TS_TYPES` 把 `AcceptanceCheck` 的 `min` 写成必填、`max` 压根没声明
⇒ 生成物 `ui/src/types.ts` 里 `min: number`；`Artifacts.tsx` 那一列 `String(r.min)`
⇒ 真浏览器上 C3/C4 两行显示字面量 `undefined`。规模：99 份验收表里 60 份含
`max`-only 行（98 行），也就是 60 个真实工作区的产物页会印 `undefined`。

为什么判据没红：夹具三行全是 `min`（`tests/conftest.py` 的 `ACCEPTANCE_CHECKS_SAMPLE`），
契约 C 又只读第一行（`_take` 原先是 `set(rows[0])`）—— 两层盲区叠在一起。
这一笔同时补了这两处：夹具加一条 `max`-only 行，`_take` 取**每一行**键的并集。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_a_max_only_row_keeps_its_upper_bound` | 端点：夹具里那一行只有 `max`、没有 `min`，`/api/artifacts` 原样透传 |
| ② `test_the_generated_type_covers_both_directions` | 生成物：`AcceptanceCheck` 的 `min` / `max` 都是可选（`min?:` / `max?:`），不再是必填 |
| ③ `test_the_page_renders_both_bounds` | 页面：`Artifacts.tsx` 同时有下限与上限两列，且没有 `String(r.min)` 这种无条件渲染 |

## 改前红在哪里

①先红：`assert "max" in row` 失败（夹具已经加了 max-only 行，读出来的那一行只有
`min` 的行键集合）——不，改前红的是 ②③：`types.ts` 里 `min: number;`（必填、无 `max`），
`Artifacts.tsx` 里只有一列 `key: "min"` / `render: (r) => String(r.min)`。
端到端那一半在浏览器判据里（`test_webui_browser.py` 的逐页核对：产物页正文里
出现字面量 `undefined`）。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Iterator

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
TYPES_TS = REPO / "ui" / "src" / "types.ts"
ARTIFACTS_TSX = REPO / "ui" / "src" / "pages" / "Artifacts.tsx"


@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {"_list": body}
    finally:
        conn.close()


def _interface_body(name: str) -> str:
    """`types.ts` 里某个接口的大括号体（没有该接口 ⇒ 空串）。"""
    text = TYPES_TS.read_text(encoding="utf-8")
    found = re.search(r"export interface %s \{(.*?)\n\}" % re.escape(name), text, re.S)
    return found.group(1) if found else ""


# ====================================================================== ① 端点
def test_a_max_only_row_keeps_its_upper_bound(artifacts_ws: pathlib.Path) -> None:
    """①：夹具里那一条 `max`-only 行原样到达 `/api/artifacts`（`min` 不在）。"""
    with _server(artifacts_ws) as base:
        code, art = _get(base, "/api/artifacts")
    assert code == 200, code
    assert art["checks_tri"] == "computed", art["checks_tri"]
    upper = [r for r in art["checks"] if r.get("id") == "C4"]
    assert len(upper) == 1, art["checks"]
    row = upper[0]
    assert row["max"] == 0, row
    assert "min" not in row, f"夹具里的 max-only 行居然带上了 min：{row}"
    # 反向：另外三行是下限档（这一条防"把 min 删掉就当修好了"）。
    lowers = [r for r in art["checks"] if r.get("id") == "C1"]
    assert lowers and lowers[0]["min"] == 1 and "max" not in lowers[0], lowers


# ====================================================================== ② 生成物
def test_the_generated_type_covers_both_directions() -> None:
    """②：`AcceptanceCheck` 的 `min` / `max` 都是可选的（形状真身：`closing.py` 三档阈值）。"""
    body = _interface_body("AcceptanceCheck")
    assert body, "types.ts 里没有 AcceptanceCheck 接口"
    assert re.search(r"^\s*min\?:", body, re.M), f"min 不是可选：{body!r}"
    assert re.search(r"^\s*max\?:", body, re.M), f"max 没声明（或不是可选）：{body!r}"
    # `id` / `kind` / `name` / `note` 仍然必填（别把整张表都放宽成可选）。
    for key in ("id", "kind", "name", "note"):
        assert re.search(r"^\s*%s:" % key, body, re.M), f"{key} 不该变成可选：{body!r}"


# ====================================================================== ③ 页面
def test_the_page_renders_both_bounds() -> None:
    """③：产物页同时有下限与上限两列，且不再无条件 `String(r.min)`。"""
    src = ARTIFACTS_TSX.read_text(encoding="utf-8")
    assert 'key: "min"' in src, "产物页没有下限那一列"
    assert 'key: "max"' in src, "产物页没有上限那一列（max-only 行会印出 undefined）"
    assert "r.max" in src, "上限那一列没有读 r.max"
    assert "String(r.min)" not in src, (
        "产物页仍然无条件 String(r.min) —— max-only 行会印出 undefined")
