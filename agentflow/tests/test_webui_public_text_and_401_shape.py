# -*- coding: utf-8 -*-
"""判据（E8 + E9）：两处公开文本与实现对齐，`/api/*` 的 401 回 JSON。

## 改前是什么样（2026-11-03 清点，E8 / E9）

E8（文案与实现相反，两处）：

1. `python -m agentflow.webui --help` 与 `webui/server.py` 的模块 docstring 写着
   `--allow-writes` / `--no-settings-write` "本批还没有接线：现在给不给都一样"；
   而 `writes.authorize()` 真的按它判 403/放行（第 3 层 / 第 4 层），
   `cli.py` 的 `agentflow web --help` 也说"W3/W4 之后它们真的改变行为"——
   同一仓库两套 help 互相打脸。
2. `ui/src/components/Roster.tsx` 写死一句"后端给的计数栏是 null，不是 0"；
   而台账回退档（`out/roster` 不在盘上、`answer=unknown`）的
   `/api/roster` 是 `count=7`、`nodes=7`（`readers._roster_from_tasks`）——
   7 个真节点的页面上写着"计数栏是 null"。

E9（协议分家）：口令不对时 `do_GET` / `do_POST` 一律 `_html(401, …)`，
而同一文件的 Q1 口径是"`/api/*` 未知一律 JSON" ⇒ 前端 `readJSON` 把一整段
`<!DOCTYPE html>…` 当理由塞进 `ApiError.reason` 上屏。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_the_module_help_says_the_switches_really_work` | `run(["--help"])` 的真实输出：不再说"本批还没有接线"，而且写清 `--allow-writes` 真的让写端点放行/403 |
| ② `test_the_module_docstring_says_the_same_thing` | 模块 docstring 与 help 同一口径 |
| ③ `test_the_roster_panel_names_both_branches` | 页面把"计数栏可能是 null"与"台账回退有数"两档都说出来 |
| ④ `test_api_401_is_json_and_the_page_401_is_html` | `/api/*` 的 401 是 JSON（`{ok,tri,reason}`）；`/` 的 401 仍是 HTML（页面那条口径不变） |

## 改前红在哪里

①：help 里有"本批还没有接线"；②：docstring 里有"本批只做到解析并透传"；
③：页面只有"计数栏是 null，不是 0"一句；④：`/api/state` 的 401 是
`text/html`、正文是 `<!DOCTYPE html>…`。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
from contextlib import contextmanager
from typing import Iterator

import pytest

from agentflow import webui as W
from agentflow.webui import server as WS

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
ROSTER_TSX = REPO / "ui" / "src" / "components" / "Roster.tsx"


# ====================================================================== ① help
def test_the_module_help_says_the_switches_really_work(
        capsys: pytest.CaptureFixture[str]) -> None:
    """①：`--help` 不再说"本批还没有接线"，而是说清两个开关真的改变行为。"""
    with pytest.raises(SystemExit) as ei:
        WS.run(["--help"])
    assert int(ei.value.code or 0) == 0, ei.value.code
    out = capsys.readouterr().out
    assert "本批还没有接线" not in out, out
    assert "现在给不给都一样" not in out, out
    assert "--allow-writes" in out and "--no-settings-write" in out, out
    # 说清它们真的判：写面没开 ⇒ 写端点 403；`--no-settings-write` 只关设置那一条。
    assert "403" in out, out
    assert "只读" in out, out


# ====================================================================== ② docstring
def test_the_module_docstring_says_the_same_thing() -> None:
    """②：模块 docstring 与 help 同一口径（两份公开文本不许互相打脸）。"""
    doc = WS.__doc__ or ""
    assert "本批只做到" not in doc, "docstring 还写着「本批只做到解析并透传」"
    assert "还没有接任何一条判断" not in doc, "docstring 还写着「还没有接任何一条判断」"
    assert "allow_writes" in doc and "settings_write" in doc, doc[:200]
    assert "403" in doc, "docstring 没写清「不开写面 ⇒ 写端点 403」"


# ====================================================================== ③ 名册文案
def test_the_roster_panel_names_both_branches() -> None:
    """③：计数栏那两句要说全：可能是 null（名册没读到），也可能来自台账回退。"""
    src = ROSTER_TSX.read_text(encoding="utf-8")
    assert "计数栏是 null，不是 0" not in src, (
        "页面还写着「后端给的计数栏是 null，不是 0」—— 台账回退档是有数的（真机 count=7）")
    assert "台账回退" in src, "页面没提台账回退那一档"
    assert "null" in src, "页面没提「名册没读到 ⇒ 计数栏可能是 null」那一档"


# ====================================================================== ④ 401 形态
@contextmanager
def _token_server(root: pathlib.Path) -> Iterator[str]:
    srv = W.serve(root, host="127.0.0.1", port=0, token="tok-e8e9",
                  csrf_token="csrf-e8e9-0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _request(base: str, method: str, path: str) -> tuple[int, str, str]:
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        body = b"" if method == "GET" else b"confirm=1"
        headers = {"Accept": "application/json"} if method == "GET" else {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "")
    finally:
        conn.close()


def test_api_401_is_json_and_the_page_401_is_html(tmp_path: pathlib.Path) -> None:
    """④：`/api/*` 的 401 是 JSON；页面那条仍是 HTML。"""
    root = tmp_path / "ws"
    root.mkdir()
    with _token_server(root) as base:
        for method, path in (("GET", "/api/state"), ("GET", "/api/run-index"),
                             ("POST", "/api/stop"), ("POST", "/api/submit")):
            code, body, ctype = _request(base, method, path)
            assert code == 401, (method, path, code)
            assert ctype.startswith("application/json"), (method, path, ctype, body[:200])
            got = json.loads(body)  # 前端 readJSON 能解
            assert got["ok"] is False and got["tri"] == "not_applicable", (path, got)
            assert "口令" in got["reason"], (path, got)
        # 页面与静态资源那条口径不变：401 仍是 HTML（浏览器看得懂）。
        for path in ("/", "/run/x", "/static/assets/nope.js"):
            code, body, ctype = _request(base, "GET", path)
            assert code == 401, (path, code)
            assert ctype.startswith("text/html"), (path, ctype, body[:200])
            assert not re.match(r"^\s*\{", body), (path, body[:200])
