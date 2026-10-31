# -*- coding: utf-8 -*-
"""判据（E1 + E2）：「开了口令」这一档必须真的能用 —— 自证要带口令，页面要能把口令带下去。

## 改前是什么样（2026-11-03 清点的两条，同一处根源）

E1（服务站不住）：`python -m agentflow.webui --root <ws> --port 0 --json --token X`
把 URL 打出来之后，`run()` 的自证 `verify_serving(url, root=root)` 不带口令去打
`/api/state`，于是拿到 401、8 秒后 `srv.shutdown()`、exit 1。打出去的那一行 URL
是一个已经死掉的地址。实测：`exit=1`、`elapsed=9.2s`。

E2（页面白屏）：口令模式下外壳里的 `/static/*.js`、`/api/state`、`/api/stream`
都是普通请求（不带 `?token=`），全部 401。`GET /?token=x` 能拿到 HTML，
浏览器随后拿不到任何脚本 ⇒ 白屏。

## 这一份守什么

| 判据 | 它钉的是 |
|---|---|
| ① `test_the_self_check_passes_when_the_service_requires_a_token` | 用 `--token` 起一个真进程：自证通过、进程不退；同时 `verify_serving(..., token=)` 自己给出 `state="ok"` |
| ② `test_the_shell_assets_and_the_api_come_through_the_page_cookie` | 浏览器那一步：`GET /?token=` 之后，外壳里 `<script src>` 的原样 URL（不带查询串）能拿到 200；`/api/state`、`/api/stream` 同 |
| ③ `test_a_request_without_the_token_is_still_refused` | 安全不许放宽：既没查询串、也没 Bearer、也没 cookie ⇒ 401（负控：错的 cookie 也 401） |

## 口令怎么"随页面到达后续请求"（E2 的选型）

`GET /?token=` 通过之后种一个同源会话 cookie（`Path=/; HttpOnly; SameSite=Strict`），
`_token_ok` 认它。为什么选 cookie 而不是"前端从 meta 里读出来再拼到每个请求/SSE 上"：

- 后一种要改 `ui/src/api.ts` / `ui/src/sse.ts` 并重新构建入库的前端产物，
  还要在服务端往外壳里注入第二个令牌位 —— 新面（新 meta、新拼串口径、
  新产物）比一个 cookie 大得多；
- 静态资源那一路（`<script src>` / `<link href>`）根本不经过前端代码，
  meta 方案对它完全无效，还得再改 `index.html` 的服务端改写；
- cookie 只多一个头，`_token_ok` 的口径（`compare_digest`）一个字不改，
  而且浏览器对同源资源（含 `EventSource`）自动带上它。

外壳里的资源仍是绝对路径（`/static/assets/...`），这一格刻意不改：
外壳在 `/` 与 `/run/{sid}` 两条路上各吐一次，相对路径 `static/...` 到了
`/run/{sid}` 会被解析成 `/run/static/...`（深链刷新立刻白屏）。缺的从来不是
"相对路径"，而是"口令没有随页面到达后续请求"。

## 反真空

①②都断言 200/ok 这类"真接通了"的读数；③是负控（口令不对不许过）。
没有 ③，把 `_token_ok` 改成恒真也能让 ①② 变绿。
"""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from agentflow import webui as W
from agentflow.webui import server as WS

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]

#: 口令档下浏览器那一步种下的 cookie 名字（前端/浏览器可见的线格式：
#: 判据按字面量读它，与 `X-CSRF-Token` 那一格同一种"线格式"口径）。
COOKIE_NAME = "agentflow_web_token"

#: 这一份用的口令（短、ASCII、不含 cookie 里要转义的字符）。
TOKEN = "tok-e1e2-0123456789"


def _ws(tmp_path: pathlib.Path, name: str = "ws") -> pathlib.Path:
    root = tmp_path / name
    (root / "data").mkdir(parents=True)
    return root


@contextmanager
def _server(root: pathlib.Path, token: str = TOKEN) -> Iterator[str]:
    """在临时端口上起一个要口令的服务（`base` = `host:port`）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, token=token,
                  csrf_token="csrf-e1e2-0123456789")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str, *, cookie: str = "",
         timeout: float = 10.0) -> tuple[int, str, dict[str, str]]:
    """一次 GET：返回 `(状态码, 正文, 小写化的响应头)`。"""
    conn = http.client.HTTPConnection(base, timeout=timeout)
    try:
        headers = {"Cookie": cookie} if cookie else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                {k.lower(): v for k, v in resp.getheaders()})
    finally:
        conn.close()


def _cookie_pair(set_cookie: str) -> str:
    """把 `Set-Cookie` 的整行折成"浏览器下一次会送回来的那一对"（只到第一个分号）。"""
    return set_cookie.split(";", 1)[0].strip()


# ====================================================================== ① E1
def _read_first_line(stream, *, timeout: float) -> str:
    """从子进程 stdout 读第一行（带超时：读不到就是失败，不无限等）。"""
    box: "queue.Queue[str]" = queue.Queue()

    def _reader() -> None:
        try:
            box.put(stream.readline())
        except Exception as exc:  # noqa: BLE001 - 读不到就是失败，把原因交回去
            box.put(f"<{type(exc).__name__}: {exc}>")

    threading.Thread(target=_reader, daemon=True).start()
    try:
        return box.get(timeout=timeout)
    except queue.Empty:
        return ""


def test_the_self_check_passes_when_the_service_requires_a_token(
        tmp_path: pathlib.Path) -> None:
    """①：`--token` 起真进程 ⇒ 自证通过、进程不退；`verify_serving` 自己回 `ok`。

    改前红（实测）：子进程在 ~9.2 秒后自己退出 1，stderr 是
    `绑完了但自证没过：… HTTP Error 401: Unauthorized（没查成，不是通过）`。
    """
    root = _ws(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", "agentflow.webui", "--root", str(root),
         "--host", "127.0.0.1", "--port", "0", "--json", "--token", TOKEN],
        cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        first = _read_first_line(proc.stdout, timeout=20.0)
        assert first.strip().startswith("{"), f"第一行不是 URL 的 JSON：{first!r}"
        url = str(json.loads(first).get("url") or "")
        assert url.endswith("/") and "://127.0.0.1:" in url, url

        # 自证失败那一档是"打完 URL 之后 ~9.2 秒自己退出 1"。等过那个窗口：
        # 进程还活着 = 自证没有以失败收场（它失败时唯一的收场就是 shutdown + exit 1）。
        deadline = time.monotonic() + 10.5
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=10)
                raise AssertionError(
                    "开了 --token 的服务自己退出了（exit=%r）—— 自证没有带口令。\n"
                    "stdout=%r\nstderr=%r" % (proc.returncode, out[-800:], err[-1200:]))
            time.sleep(0.1)
        assert proc.poll() is None, "自证窗内进程退出了"

        # 顺带把"带口令的这一趟真的在服务"读出来（自证用的就是这一条请求）。
        got = WS.verify_serving(url, root=root, token=TOKEN)
        assert got["state"] == "ok", got
        assert got["code"] == 200, got
        assert str(got["root"]) == str(root.resolve()), got
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001 - 收尾不许把用例的结论改掉
            proc.kill()


def test_the_self_check_without_the_token_still_says_unknown(
        tmp_path: pathlib.Path) -> None:
    """①的反面：口令档下不带口令自证 ⇒ `unknown`（不是"折成通过"）。"""
    root = _ws(tmp_path)
    with _server(root) as base:
        got = WS.verify_serving(f"http://{base}/", root=root)
        assert got["state"] == "unknown", got
        assert "401" in str(got["reason"]), got


# ====================================================================== ② E2
def test_the_shell_assets_and_the_api_come_through_the_page_cookie(
        tmp_path: pathlib.Path) -> None:
    """②：`GET /?token=` 之后，外壳里的原样 URL、`/api/*`、SSE 都能 200。

    改前红：`GET /?token=` 回 200，但外壳里的 `<script src>`（`/static/…`，不带
    查询串）与 `/api/state` 都是 401。
    """
    root = _ws(tmp_path)
    with _server(root) as base:
        code, shell, headers = _get(base, f"/?token={TOKEN}")
        assert code == 200, (code, shell[:200])
        raw_cookie = headers.get("set-cookie", "")
        assert raw_cookie, "带口令拿到外壳之后没有种 cookie（浏览器下一步就带不上口令）"
        pair = _cookie_pair(raw_cookie)
        assert pair.startswith(f"{COOKIE_NAME}="), raw_cookie
        low = raw_cookie.lower()
        assert "path=/" in low, raw_cookie
        assert "httponly" in low, "cookie 没有 HttpOnly（前端脚本能读到它就多一条泄漏面）"
        assert "samesite=strict" in low, raw_cookie

        # 外壳里的资源 URL 原样（不带查询串）请一次 —— 这就是浏览器下一步做的事。
        found = re.search(r'<script[^>]*\ssrc="([^"]+)"', shell)
        assert found is not None, f"外壳里没有 <script src>：{shell[:400]}"
        asset = found.group(1)
        assert asset.startswith("/static/"), asset
        assert "token" not in asset, f"外壳资源上不该出现口令：{asset}"
        code, body, headers = _get(base, asset, cookie=pair)
        assert code == 200, (asset, code, body[:200])
        assert "javascript" in headers.get("content-type", ""), headers

        # `/api/state`：同一个 cookie 就够（前端 fetch 同源默认带 cookie）。
        code, raw, headers = _get(base, "/api/state", cookie=pair)
        assert code == 200, (code, raw[:300])
        assert json.loads(raw)["root"] == str(root.resolve()), raw[:300]

        # `/api/stream`（SSE）：EventSource 同源默认带 cookie ⇒ 首行必须是 200。
        assert _sse_status(base, cookie=pair) == 200


def _sse_status(base: str, *, cookie: str) -> int:
    """只读 SSE 的响应首行（拿到状态码就关，不等事件）。"""
    host, _, port = base.partition(":")
    with socket.create_connection((host, int(port)), timeout=10.0) as sk:
        sk.sendall(("GET /api/stream HTTP/1.0\r\nHost: %s\r\nCookie: %s\r\n\r\n"
                    % (base, cookie)).encode("ascii"))
        first = sk.recv(256).decode("ascii", errors="replace")
    found = re.match(r"HTTP/1\.[01] (\d{3})", first)
    assert found is not None, f"SSE 的首行不是状态行：{first!r}"
    return int(found.group(1))


# ====================================================================== ③ 负控
def test_a_request_without_the_token_is_still_refused(tmp_path: pathlib.Path) -> None:
    """③（负控）：口令档下，没查询串 / 没 Bearer / 没 cookie ⇒ 401；错的 cookie 也 401。"""
    root = _ws(tmp_path)
    with _server(root) as base:
        for path in ("/", "/static/assets/nope.js", "/api/state", "/api/stream"):
            code, _body, _headers = _get(base, path)
            assert code == 401, (path, code)
        code, _body, _headers = _get(base, "/api/state",
                                     cookie=f"{COOKIE_NAME}=not-the-token")
        assert code == 401, code
        # Bearer 那一档照旧可用（它不是这一批新加的，但这批不许把它碰坏）。
        conn = http.client.HTTPConnection(base, timeout=10)
        try:
            conn.request("GET", "/api/state",
                         headers={"Authorization": f"Bearer {TOKEN}"})
            resp = conn.getresponse()
            assert resp.status == 200, resp.status
            resp.read()
        finally:
            conn.close()
