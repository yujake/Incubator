# -*- coding: utf-8 -*-
"""用户端 Web 界面的 HTTP 层：`WebHandler` / `serve()` / `run()`。

## 这一层是什么

标准库 `http.server` 上的一个小服务（`ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把 :mod:`agentflow.webui.state` 的快照交给 :mod:`agentflow.webui.views` 渲染，
并服务前端构建产物。路由不再写成 `if path == …` 链 —— 它是
:data:`agentflow.webui.routes.ROUTES` 那张表（`draft/73` §1.2 的 R1 拆包）。

## 本批（W0）新增的两件事

1. 静态路由 `GET /static/<file>`：只服务 `agentflow/src/agentflow/web/static/` 之下的
   真实文件。防线是 `Path.resolve()` 之后必须仍在根内（目录穿越一律拒：
   `..%2f` 一类解出来就落到根外，直接 404）。带内容哈希的文件名按
   `immutable` 缓存，其余（`index.html`）按 `no-store`。
2. SPA 回退（裁定 Q1）：`/api/*` 未知 ⇒ JSON 404（绝不吐 HTML，前端要能区分）；
   其余未知路径 ⇒ 有 `web/static/index.html` 就吐它，否则沿用今天的 404 页。

## 一处刻意的收窄（必须写在最显眼的地方）

Q1 说"其余未知路径吐 index.html"，而既有判据
`tests/test_webui.py::test_unknown_paths_and_methods` 要求 `GET /nope` 是 404。
两条同时成立只有一种做法：只有"要 HTML 的客户端"才拿到 index.html ——
判据是请求头 `Accept` 里含 `text/html`。浏览器地址栏导航一定带它，于是前端路由的
深链（刷新 `/evidence`）照旧进 SPA；而 `http.client` / `curl` / 任何要 JSON 的
客户端不带它，于是拿到诚实的 404。同一条收窄也管着 `/static/<file>` 的未命中：
一个不存在的 `.css` 若回一支 HTML 200，浏览器会把它当样式表解析（静默全白）——
那比 404 坏得多，所以静态那一支永远 404，绝不回退到 `index.html`。

## 安全与失败姿态（与拆包前逐条相同）

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`），
  给了就要求 `?token=` 或 `Authorization: Bearer`；
- 用户与模型产生的一切文本都经 `html.escape` 后才进 HTML（`views` 那一层负责）；
- 写失败不许折成 200（`writes.answer` 的三态）；
- 每个响应都带 `X-Content-Type-Options: nosniff`。

## 两个开关（裁定 C2 / E1，本批只做到"解析并透传"）

`serve(..., allow_writes=False, settings_write=True)` 与 CLI 的 `--allow-writes` /
`--no-settings-write` 今天还没有接任何一条判断：写面要等 W3（授权 + 审计）、
设置写面要等 W4。它们先落在这里，是为了让"默认只读"这个口径在调用链上有名字，
而不是等 W3 再改一遍签名。`--help` 里逐字写了"本批还没有接线"，免得读的人
以为自己已经拿到了写面。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from . import routes
from .state import _text, snapshot
from .views import _not_found, _page, render_root, render_run
from .writes import answer

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "WebHandler", "default_static_root", "serve",
           "run"]

#: 默认监听端口。
DEFAULT_PORT = 8788
#: 默认监听地址（只对本机开）。
DEFAULT_HOST = "127.0.0.1"

#: 静态资源的落点（相对包目录）：前端构建产物（裁定 B1）。
_STATIC_REL = ("web", "static")
#: 静态路由的前缀（与 `ui/vite.config.ts` 的 `base` 逐字一致；不一致时页面全白）。
STATIC_PREFIX = "/static/"

#: 静态资源的 content-type 表（认不出来的一律 `application/octet-stream`：
#: 猜错的类型比不认识的类型更危险，尤其配上 `nosniff`）。
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

#: 带内容哈希的文件名（`assets/main.<hash>.js`）⇒ 可以 immutable 缓存。
#: 判据是"点号之间夹着一段 8 位以上的哈希"，字母表按 Vite 5 的 `[hash]` 实测形态取
#: —— 它是 base64url（`assets/index.Bpmfy4ek.js`），不是十六进制。原先这里写的是
#: `[0-9a-fA-F]{8,}` 并声称"与 vite 的 `[hash]` 对齐"，那句话与盘上产物不符：真实产物
#: 一个都匹配不上 ⇒ 带哈希的资源全被发成 `no-store`，immutable 这条设计静默失效，
#: 而当时的判据用的是自造的十六进制夹具名，所以照样亮绿（测试与产品各说各话）。
#: 现在同时认两种字母表，并由 `tests/test_webui_static.py` 用盘上真产物钉住
#: （`test_the_hash_pattern_matches_the_real_built_asset_names` + 反例负控）。
_HASHED = re.compile(r"\.[A-Za-z0-9_-]{8,}\.")


def default_static_root() -> Path:
    """前端构建产物的默认落点（由本文件的位置推出来，不看当前工作目录）。"""
    return Path(__file__).resolve().parents[1].joinpath(*_STATIC_REL)


class WebHandler(BaseHTTPRequestHandler):
    """路由表驱动的小服务（表在 :data:`agentflow.webui.routes.ROUTES`）。

    四个由 :func:`serve` 挂上去的事实：工作区根、共享口令、静态根、CSRF 令牌；
    外加两个开关（`allow_writes` / `settings_write`，本批只透传不判断）。
    """

    server_version = "agentflow-webui"
    protocol_version = "HTTP/1.0"

    #: 由 :func:`serve` 挂上去的事实（类属性默认值让直接实例化也能跑）。
    root: Path = Path(".")
    token: str = ""
    static_root: Path = default_static_root()
    csrf_token: str = ""
    #: 两个开关（裁定 C2 / E1）：W0 只解析并透传，W3/W4 才真正判它们。
    allow_writes: bool = False
    settings_write: bool = True
    #: 路由表可注入（`serve(routes_table=...)`）：空元组 = 用 `routes.ROUTES`（缺省）。
    #: 为什么要有这个注入点：判据要拿"多了一条子表的表"走一遍真实请求，证明接缝真的接通；
    #: 有了它就不必去改模块全局（改全局的判据会污染别的用例）。
    routes_table: tuple = ()

    #: 本次请求解出来的路径（`_parse` 填；未知路由那一条要用它说清"是什么没找到"）。
    _path: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 基类签名
        """默认日志会往 stderr 打每一行请求；改成一条短行（测试里也不吵）。"""
        sys.stderr.write("[webui] %s\n" % (fmt % args))

    # ------------------------------------------------------------ 口令
    def _token_ok(self, query: Mapping[str, Sequence[str]]) -> bool:
        """给了口令就要求它：`?token=` 或 `Authorization: Bearer`。"""
        want = self.token or os.environ.get("AGENTFLOW_WEB_TOKEN", "")
        if not want:
            return True
        got = ""
        vals = query.get("token") or []
        if vals:
            got = _text(vals[0])
        if not got:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        return got == want

    # ------------------------------------------------------------ 输出
    def _send(self, code: int, body: bytes, ctype: str,
              extra: Mapping[str, str] | None = None,
              cache: str = "no-store") -> None:
        """一个响应（HEAD 只发头）。`cache` 是 Cache-Control 那一格。"""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, code: int, text: str,
              extra: Mapping[str, str] | None = None) -> None:
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8", extra)

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
        self._send(code, (body + "\n").encode("utf-8"),
                   "application/json; charset=utf-8")
        return

    def _redirect(self, code: int, location: str) -> None:
        self._send(code, b"", "text/plain; charset=utf-8", {"Location": location})

    # ------------------------------------------------------------ 请求解析
    def _parse(self) -> tuple[str, dict[str, list[str]]]:
        """解出本次请求的路径与查询串（路径先 `unquote`，判据按解出来的字面量走）。"""
        parsed = urlparse(self.path)
        self._path = unquote(parsed.path)
        return self._path, parse_qs(parsed.query, keep_blank_values=True)

    def _form(self) -> dict[str, list[str]]:
        """读表单正文（`application/x-www-form-urlencoded`）。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)

    def _wants_html(self) -> bool:
        """客户端是不是冲着"要一张网页"来的（浏览器导航带 `Accept: text/html`）。

        SPA 回退只在它为真时才走（Q1 的收窄，理由见模块 docstring）：
        `http.client` / `curl` 不带这个头，于是拿到诚实的 404 而不是一支 HTML。
        """
        return "text/html" in self.headers.get("Accept", "")

    # ------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 - 基类签名
        """GET：查 `ROUTES`；未命中走 :meth:`handle_unknown`（裁定 Q1）。"""
        path, query = self._parse()
        if not self._token_ok(query):
            self._html(401, "<!DOCTYPE html><html><body><h1>401</h1>"
                            "<p>口令不对或没给（<code>?token=</code> 或 "
                            "<code>Authorization: Bearer</code>）。</p></body></html>")
            return
        hit = routes.match("GET", path, table=self.routes_table or None)
        if hit is None:
            self.handle_unknown({}, query)
            return
        name, params = hit
        self._invoke(name, params, query)

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802 - 基类签名
        """POST：查 `ROUTES`；未命中 ⇒ 404（POST 没有 SPA 回退这回事）。"""
        path, query = self._parse()
        if not self._token_ok(query):
            self._html(401, "<!DOCTYPE html><html><body><h1>401</h1>"
                            "<p>口令不对或没给。</p></body></html>")
            return
        hit = routes.match("POST", path, table=self.routes_table or None)
        if hit is None:
            if path.startswith("/api/"):
                # 与 GET 同一条口径（裁定 Q1）：`/api/*` 未知一律 JSON 404，
                # 免得前端在读 JSON 时拿到一支 HTML。
                self._json(404, {"ok": False, "tri": "not_applicable",
                                 "reason": f"没有这个端点：{path}", "path": path})
                return
            state = snapshot(self.root)
            self._html(404, _page(state, "没有这个页面",
                                  _not_found(state, f"POST 没有路由：{path}")))
            return
        name, params = hit
        self._invoke(name, params, query)

    def _invoke(self, name: str, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> None:
        """把一条路由交给它的 handler 执行。

        两种落点（`draft/78 §3` 的接缝）：
        - A 线自己的：`WebHandler` 上的方法（`getattr` 找得到）；
        - B/C 线的：各子表模块里的 `HANDLERS[name]`（签名 `(handler, params, query)`，
          第一个参数就是这个句柄）—— 于是那两条线加端点只改自己的模块，不必碰本文件。
        两边都没有 ⇒ 那是路由表与实现的漂移，回 500 并把名字说清（表驱动不该静默 404）。
        """
        local = getattr(self, name, None)
        if callable(local):
            local(params, query)
            return
        sub = routes.handler_for(name)
        if sub is not None:
            sub(self, params, query)
            return
        self._send(500, f"500 路由表登记了没有实现的处理器：{name}\n".encode("utf-8"),
                   "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802 - 基类签名
        """HEAD 按 GET 处理（`_send` 不写正文），方便探活。"""
        self.do_GET()

    def _reject(self) -> None:
        self._send(405, b"405 method not allowed\n", "text/plain; charset=utf-8",
                   {"Allow": "GET, HEAD, POST"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _reject  # type: ignore[assignment]

    # ------------------------------------------------------------ 处理器（表里点的名）
    def handle_root(self, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> None:
        """`GET /` 与 `GET /index.html`：服务端渲染的旧壳（裁定 P1：逐面迁到 SPA 后删）。"""
        del params, query
        self._html(200, render_root(snapshot(self.root)))

    def handle_state(self, params: Mapping[str, str],
                     query: Mapping[str, Sequence[str]]) -> None:
        """`GET /api/state`：同一批读数的 JSON（前端 Home 页读的就是它）。"""
        del params, query
        self._json(200, snapshot(self.root))

    def handle_run_index(self, params: Mapping[str, str],
                         query: Mapping[str, Sequence[str]]) -> None:
        """`GET /api/run-index`：趟次索引与"它与事件现算结果是否一致"的读数。

        W1 新增（裁定 O2 的页面消费端）。Run 页要用它做两件事，两件都要求同一次读：

        1. 索引可用 ⇒ 用它列趟次；不可用 ⇒ 如实标"这次是现算的"并回退；
        2. `tri != "computed"`（索引读不出来，或与事件现算结果对不上）⇒ 显红。

        形状是 `sessions.run_index_report(root)` 的返回值逐字，另加 `index` 那一栏
        （`None` 表示索引没读成）。为什么不在这里拆成"先读索引、再对账"两次：两次
        之间盘上的东西可能已经变了，于是页面拿到的索引与它旁边的对账结论不是同一份。
        """
        del params, query
        from .. import sessions as SS

        self._json(200, SS.run_index_report(self.root))

    def handle_run(self, params: Mapping[str, str],
                   query: Mapping[str, Sequence[str]]) -> None:
        """`GET /run/<sid>`：一趟的详情（事件卡片 + 交付说明）。"""
        del query
        sid = unquote(str(params.get("sid", "")))
        state = snapshot(self.root)
        code, text = render_run(self.root, sid, state)
        self._html(code, text)

    def handle_static(self, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
        """`GET /static/<file>`：只服务静态根之下的真实文件（目录穿越一律拒）。

        未命中（含被拒的穿越）一律 404 —— 不回落 `index.html`：给一个不存在的
        `.js`/`.css` 回一支 HTML 200，浏览器会拿它当脚本/样式表解析（静默全白）。
        """
        del query
        rel = str(params.get("file", ""))
        root = Path(self.static_root)
        try:
            target = (root / rel).resolve()
            inside = target == root.resolve() or root.resolve() in target.parents
        except (OSError, RuntimeError):
            inside, target = False, root
        if not inside or not target.is_file():
            state = snapshot(self.root)
            self._html(404, _page(state, "没有这个文件",
                                  _not_found(state, f"静态资源不在盘上或越出根：{rel}")))
            return
        try:
            body = target.read_bytes()
        except OSError as exc:
            state = snapshot(self.root)
            self._html(500, _page(state, "静态资源读不出来",
                                  _not_found(state, f"{type(exc).__name__}: {exc}")))
            return
        ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        cache = ("public, max-age=31536000, immutable" if _HASHED.search(target.name)
                 else "no-store")
        if target.name == "index.html" and ctype.startswith("text/html"):
            body = self._inject_csrf(body.decode("utf-8", errors="replace")).encode("utf-8")
        self._send(200, body, ctype, cache=cache)

    def handle_answer(self, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
        """`POST /answer`：PRG（303 回首页）；qid 不待答 409；写失败 500。"""
        del params, query
        code, location, body = answer(self.root, self._form())
        if code == 303:
            self._redirect(303, location)
            return
        state = snapshot(self.root)
        self._html(code, _page(state, f"回答没有落地（{code}）", body))

    def handle_unknown(self, params: Mapping[str, str],
                       query: Mapping[str, Sequence[str]]) -> None:
        """未命中的路径（裁定 Q1）：`/api/*` ⇒ JSON 404；其余 ⇒ SPA 回退。"""
        del params, query
        path = self._path
        if path.startswith("/api/"):
            self._json(404, {"ok": False, "tri": "not_applicable",
                             "reason": f"没有这个端点：{path}", "path": path})
            return
        index = Path(self.static_root) / "index.html"
        if self._wants_html() and index.is_file():
            try:
                shell = index.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                state = snapshot(self.root)
                self._html(500, _page(state, "前端外壳读不出来",
                                      _not_found(state, f"{type(exc).__name__}: {exc}")))
                return
            self._html(200, self._inject_csrf(shell))
            return
        state = snapshot(self.root)
        self._html(404, _page(state, "没有这个页面", _not_found(state, f"没有路由：{path}")))

    # ------------------------------------------------------------ CSRF 占位符
    def _inject_csrf(self, html_text: str) -> str:
        """把 `index.html` 里的 `__CSRF__` 换成这一次进程的令牌。

        令牌由 :func:`serve` 每进程随机生成，所以盘上的产物里没有真令牌
        （裁定 B1 把产物入库，写死一个令牌等于把它一起发布出去）。W0 没有任何端点
        消费它（写面在 W3）；它先占位，让"令牌从哪来"这件事在链路上是通的。
        """
        return html_text.replace("__CSRF__", self.csrf_token or "")


# ====================================================================== 服务
def serve(root: str | Path, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          token: str = "", allow_writes: bool = False, settings_write: bool = True,
          static_root: str | Path | None = None,
          csrf_token: str = "",
          routes_table: Sequence[tuple[str, str, str]] | None = None) -> ThreadingHTTPServer:
    """建好服务器并返回（不调 `serve_forever`）。

    测试用 `port=0` 起随机端口：返回后读 `srv.server_address[1]` 拿真实端口，
    在 `finally` 里 `srv.shutdown()` + `srv.server_close()`。

    `allow_writes` / `settings_write` 是本批新增的两个开关（裁定 C2 / E1）：
    今天只解析并透传（挂到句柄上、可在 `handler.allow_writes` 读到），
    写面要等 W3、设置写面要等 W4 —— 这一点在 `--help` 与模块 docstring 里都写明了。
    `static_root` / `csrf_token` 也是可注入的：判据要在临时目录里造一份前端外壳，
    并按需钉住令牌（缺省 = 每进程一个随机值）。
    """
    handler = type("BoundWebHandler", (WebHandler,), {
        "root": Path(str(root)), "token": token,
        "static_root": Path(str(static_root)) if static_root is not None
        else default_static_root(),
        "csrf_token": csrf_token or secrets.token_hex(16),
        "allow_writes": bool(allow_writes), "settings_write": bool(settings_write),
        "routes_table": tuple(routes_table) if routes_table is not None else (),
    })
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def run(argv: Sequence[str] | None = None) -> int:
    """命令行入口：起服务；`--json` 只打印一行 `{"url": ...}` 便于后台任务取 URL。

    为什么叫 `run` 而不是 `main`：`cli.py` 里已经有一个公开的 `main`（整套 CLI 的
    唯一入口），同名两份独立实现是本项目 R003 点名的形态。`cli.py` 那边加
    `agentflow web` 子命令时调本函数（或直接调 :func:`serve`）。
    """
    from ..cli import DEFAULT_ROOT

    ap = argparse.ArgumentParser(
        prog="agentflow-webui",
        description="agentflow 用户端：全局待回答面板 + 运行态 + 一趟回放（服务端渲染）")
    ap.add_argument("--root", default="", help="工作区根（不给就用 DEFAULT_ROOT）")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口（默认 {DEFAULT_PORT}；给 0 让系统挑）")
    ap.add_argument("--token", default="", help="共享口令（也可用 AGENTFLOW_WEB_TOKEN）")
    ap.add_argument("--open", action="store_true", help="起好之后用浏览器打开首页")
    ap.add_argument("--json", action="store_true",
                    help="只打印一行 URL 的 JSON（便于起后台任务后拿到确切 URL）")
    # 裁定 T1：只加这两个开关。（注意）本批它们还没有接线（W3 的写面、W4 的设置写面），
    # 下面两句 help 逐字说明这一点 —— 免得读 help 的人以为写面已经开了。
    ap.add_argument("--allow-writes", action="store_true",
                    help="允许写面（本批还没有接线：W3 才真正生效，现在给不给都一样）")
    ap.add_argument("--no-settings-write", action="store_true",
                    help="关掉设置写面（本批还没有接线：W4 才真正生效，现在给不给都一样）")
    args = ap.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve() if args.root else Path(DEFAULT_ROOT).resolve()
    token = args.token or os.environ.get("AGENTFLOW_WEB_TOKEN", "")
    srv = serve(root, host=args.host, port=args.port, token=token,
                allow_writes=args.allow_writes,
                settings_write=not args.no_settings_write)
    host, port = srv.server_address[0], srv.server_address[1]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    # `flush=True` 是「必须」的，不是洁癖：这两行之后进程就进 `serve_forever()` 永不返回，
    # 而 stdout 被管道/文件接走时是「块缓冲」（8 KB 才吐一次）⇒ 起后台任务的人
    # 永远等不到那一行 URL。实测撞到：`python -B -m agentflow.webui --port 0 --json`
    # 在后台跑了很久，输出里一个字都没有（URL 就卡在缓冲区里）。
    # 而 `--json` 这个开关存在的唯一目的就是"让调用方立刻拿到确切 URL"。
    if args.json:
        print(json.dumps({"url": url, "root": str(root)}, ensure_ascii=False), flush=True)
    else:
        print(f"agentflow 用户端：{url}", flush=True)
        print(f"工作区根：{root}", flush=True)
        print("Ctrl-C 停止。", flush=True)
        if args.allow_writes or args.no_settings_write:
            print("（提示：--allow-writes / --no-settings-write 本批只做到解析与透传，"
                  "W3 / W4 才真正生效 —— 现在它们不改变任何行为。）", flush=True)
    if args.open:
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001 - 打不开浏览器不该拖垮服务
            sys.stderr.write(f"[webui] 打不开浏览器：{type(exc).__name__}: {exc}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        # Ctrl-C 是停止服务的正常路径（不是错误）：吞掉它，
        # 让 finally 去 shutdown + close，退出码仍是 0。
        pass
    finally:
        srv.shutdown()
        srv.server_close()
    return 0
