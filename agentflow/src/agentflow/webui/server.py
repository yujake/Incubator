# -*- coding: utf-8 -*-
"""用户端 Web 界面的 HTTP 层：`WebHandler` / `serve()` / `run()`。

## 这一层是什么

标准库 `http.server` 上的一个小服务（`ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把 :mod:`agentflow.webui.state` 的快照与六个只读面/写面的读数发成 JSON、
把两个页面入口（`/` 与 `/run/{sid}`）发成前端构建产物那一支外壳，
其余一切人可读的东西都由前端渲染。路由不再写成 `if path == …` 链 —— 它是
:data:`agentflow.webui.routes.ROUTES` 那张表（`draft/73` §1.2 的 R1 拆包）。

## 路由这一层做过的四件事（第 1、2 件是 W0 的，第 3 件 2026-10-07，第 4 件 W5）

1. 静态路由 `GET /static/<file>`：只服务 `agentflow/src/agentflow/web/static/` 之下的
   真实文件。防线是 `Path.resolve()` 之后必须仍在根内（目录穿越一律拒：
   `..%2f` 一类解出来就落到根外，直接 404）。带内容哈希的文件名按
   `immutable` 缓存，其余（`index.html`）按 `no-store`。
2. SPA 回退（裁定 Q1）：`/api/*` 未知 ⇒ JSON 404（绝不吐 HTML，前端要能区分）；
   其余未知路径 ⇒ 有 `web/static/index.html` 就吐它，否则沿用今天的 404 页。
3. `GET /` 与 `GET /index.html` 直接服务 SPA 外壳（裁定 P1 的第一块迁移，
   2026-10-07）：这一格原来是服务端渲染的旧壳。SPA 只在"未知路径"的回退分支上挂得
   起来，而 `/` 是已知路径 ⇒ 不改这一格，浏览器地址栏就永远进不了 SPA 首页。
4. `GET /run/{sid}` 也服务那一支外壳（P1 的最后一块迁移，W5 清仓）：它是 C4 表里的
   一条客户端路由，SPA 的 `Run` 页按 `sid` 去读 `GET /api/run/{sid}`；会话不在盘上
   这件事由那份读数如实报成 `unreadable`（三态），服务端不再为它渲染任何盘上数据。
   旧壳 `webui/views.py` 随之整件退场，服务器自己还写 HTML 的地方只剩错误页
   （见 :func:`_error_page`：外壳不在盘上 / 静态未命中 / 写失败）。

## 一处刻意的收窄（必须写在最显眼的地方）

Q1 说"其余未知路径吐 index.html"，而既有判据
`tests/test_webui.py::test_unknown_paths_and_methods` 要求 `GET /nope` 是 404。
两条同时成立只有一种做法：只有"要 HTML 的客户端"才拿到 index.html ——
判据是请求头 `Accept` 里含 `text/html`。浏览器地址栏导航一定带它，于是前端路由的
深链（刷新 `/evidence`）照旧进 SPA；而 `http.client` / `curl` / 任何要 JSON 的
客户端不带它，于是拿到诚实的 404。同一条收窄也管着 `/static/<file>` 的未命中：
一个不存在的 `.css` 若回一支 HTML 200，浏览器会把它当样式表解析（静默全白）——
那比 404 坏得多，所以静态那一支永远 404，绝不回退到 `index.html`。

这条收窄不管 `GET /`：根路径是一条已知路由，它对谁都吐同一支外壳（不挑 `Accept`）——
浏览器地址栏、`curl` 与 `http.client` 拿到的都是那一支（`GET /` 的 200 与"未知路径
回退到 404"是两件事，不要混起来）。

## 安全与失败姿态（与拆包前逐条相同）

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`），
  给了就要求 `?token=` 或 `Authorization: Bearer`；
- 服务器自己写的最后一页是 :func:`_error_page`（只有错误页），它把理由串经
  `html.escape` 后才写进 HTML；盘上的文本一律走 JSON —— 前端用文本节点渲染它们
  （两条转义判据见 `tests/test_webui.py`：一条钉服务端，一条钉前端源码里没有
  把字符串当 HTML 用的写法）；
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

from . import routes, sse
from .state import _esc, _text
from .writes import answer

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "WebHandler", "default_static_root", "serve",
           "run"]

#: 默认监听端口。
DEFAULT_PORT = 8788
#: 默认监听地址（只对本机开）。
DEFAULT_HOST = "127.0.0.1"
#: 默认心跳周期（秒）：`GET /api/stream` 闲着时多久发一条 `heartbeat`。
#: `serve(heartbeat_sec=...)` 可注入（判据用 0.2 秒跑，不等 15 秒）。
DEFAULT_HEARTBEAT_SEC = 15.0

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


#: 停止理由 → 徽标词汇：三态加一档「停在等待用户」。
#:
#: 为什么它在 HTTP 层：旧壳 `webui/views.py` 退场之后（裁定 P1 的 W5 清仓），这张表
#: 在生产路径上已经没有读者了 —— 前端 `ui/src/pages/Run.tsx` 原样显示 `stop_reason`
#: 的文本，没有徽标表。它留在包命名空间里，是因为 `tests/test_loop_liveness.py` 拿
#: `W._STOP_BADGES` 当"新停止理由必须登记"的落点。这条残留与"SPA 一侧该不该照它
#: 做一张徽标表"一起写在 W5 报告里交主控裁（改前端不在本批的写面里）。
_STOP_BADGES = {
    "final": ("badge-pass", "跑完"),
    "budget": ("badge-unknown", "预算用尽"),
    # 裁定 12-K 之后循环不再产生它（步数只上报、不收工），这一格留着是给历史读数
    # 用的：旧会话记录里真有 `max_steps` 的趟，徽标表要把它们解释得出来。
    # 与"读它去决定行为"是两件事 —— 决策点上那一格已经删了（`agent_loop._emit_settlement`）。
    "max_steps": ("badge-unknown", "步数用尽（旧读数）"),
    "not_wired": ("badge-fail", "没接线"),
    "bad_json_limit": ("badge-fail", "坏 JSON 连击"),
    "bad_args_limit": ("badge-fail", "坏参数连击"),
    # `draft/37` §136：同调用 + 同读数连着到上限 ⇒ 这一趟停在"没有新事实"。
    # 刻意不是 `badge-fail`：那不是出错，是"这一趟没有往前走"（一档读数）。
    "no_progress_limit": ("badge-unknown", "原地打转"),
    "waiting_for_user": ("badge-pending", "停在等用户"),
}


def _error_page(code: int, title: str, why: str, *, fragment: str = "") -> str:
    """服务器自己写的最后一页：一张最小错误页（旧壳退场后只剩它这一处）。

    为什么不是"一律吐 SPA 外壳"：不是每一条未命中都能给外壳 —— `/static/<未命中>`
    与"客户端没要 HTML"那两条分支必须回诚实的错误码（裁定 Q1 的收窄，理由见模块
    docstring）；给一个要 `.js` 的请求塞一支 HTML 200，浏览器会把它当脚本解析
    （静默全白），那比 404 坏得多。

    `fragment` 是调用方手上已经有的一段 HTML（今天只有 `writes.answer()` 的 409
    正文，它自己已经转义过用户给的文本）；`why` 在这里转义 —— 它可能带着工作区路径
    （路径里有 `<` 也完全合法），所以这一处不是形式主义。
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        "</head>\n<body>\n"
        f"<h1>{code}</h1>\n"
        f"<p>{_esc(title)}</p>\n"
        f'<p class="why"><code>{_esc(why)}</code></p>\n'
        f"{fragment}"
        '<p>回到 <a href="/">首页</a>（首页是 SPA 外壳，读数由前端从 '
        "<code>/api/state</code> 读）。</p>\n"
        "</body>\n</html>\n"
    )


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

    # ------------------------------------------------------------ 请求循环
    def handle_one_request(self) -> None:
        """一次请求：客户端中途挂了 ⇒ 安静收尾，不劳 `socketserver` 打一条回溯。

        为什么覆写这一层、而不是给每个 `do_*` 加 try：对端消失可能发生在请求行/头/
        正文的读上，也可能发生在响应的写与 flush 上（`handle_one_request` 的最后
        一步），还可能发生在 `send_error` 那一支 —— 三处都在这一格里发生。
        只包 `do_GET` 会漏掉另外两处（实测：SSE 的响应头写着 `Connection: keep-alive`
        ⇒ handler 返回后本层会再读一次请求行，读到的正是那条已被掐断的套接字，
        `ConnectionAbortedError` 就从这里冒出来，`socketserver.handle_error` 于是把
        `Exception occurred during processing of request …` 与整段回溯打进 stderr）。

        口径刻意只认三种"对端没了"的异常：`ConnectionAbortedError` /
        `ConnectionResetError` / `BrokenPipeError`（都是 `OSError` 的子类）。
        其余异常一律照旧冒泡给 `socketserver.handle_error` —— 顺手 catch
        `Exception` 会让真错误从日志里消失，那比日志脏坏得多（本项目
        "没查成与查过了没问题必须分得开"的同一条纪律）。
        收尾方式与 `socketserver` 自己的 TimeoutError 那一支相同：置
        `close_connection = True`，让 `handle()` 的循环正常结束。
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

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
            self._html(404, _error_page(404, "没有这个页面",
                                        f"POST 没有路由：{path}"))
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
        """`GET /` 与 `GET /index.html`：服务 SPA 外壳（裁定 P1 的第一块迁移）。

        这一格原来是服务端渲染的旧壳（`views.render_root`）。为什么必须改：SPA 只在
        "未知路径"的回退分支上挂得起来，而 `/` 是一条已知路径 ⇒ 浏览器地址栏
        永远进不了 SPA 首页（判据 C 那边有一条浏览器判据记录的正是这件事）。

        外壳由 :meth:`_serve_spa_shell` 吐（与静态路由、回退分支同一份实现）；
        外壳不在盘上（前端还没构建）⇒ 404 + 一句说清为什么 ——
        不静默给一个空白页（"没构建"与"页面坏了"必须分得开）。
        """
        del params, query
        self._serve_shell_or_404("根路径")

    def _serve_shell_or_404(self, what: str) -> None:
        """吐外壳；不在盘上 ⇒ 404 说清是哪一条入口要它（两条页面路由共用这一处）。"""
        if self._serve_spa_shell():
            return
        self._html(404, _error_page(
            404, "前端外壳不在盘上",
            f"{what}要吐的是 SPA 外壳 web/static/index.html，而它不在盘上"
            "（前端还没构建？）"))

    def _serve_spa_shell(self) -> bool:
        """吐前端外壳 `web/static/index.html`（注入本进程的 CSRF 占位符）。

        返回"吐出去了没有"：`True` = 已经回了 200；`False` = 外壳不在盘上或读不出来
        （调用方接着走它自己的 404/500 分支）。

        为什么把这一件事收成一处：`GET /`、`GET /index.html`、未知路径的 SPA
        回退三条路都要吐同一支外壳，而"注入 CSRF"这一步漏掉一处，前端拿到的就是
        字面量 `__CSRF__` —— 写请求会以"令牌不对"失败，而那时没人会想到是外壳
        那条路径忘了注入。三处各写一遍是这类缺陷的温床。
        """
        index = Path(self.static_root) / "index.html"
        if not index.is_file():
            return False
        try:
            shell = index.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._html(500, _error_page(500, "前端外壳读不出来",
                                        f"{type(exc).__name__}: {exc}"))
            return True
        self._html(200, self._inject_csrf(shell))
        return True

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
        """`GET /run/<sid>`：SPA 外壳（裁定 P1 的最后一块迁移，W5）。

        这一格原来是旧壳的"一趟详情"（`views.render_run`：事件卡片 + 交付说明）。
        为什么改成吐外壳：`/run/:sid` 是 C4 表里的一条客户端路由，SPA 的 `Run` 页
        按 `sid` 去读 `GET /api/run/{sid}` —— 服务端再渲染一遍盘上数据，就是同一件事
        两份实现（P1 要的清仓正是这个）。会话号不合法或会话不在盘上这件事，
        由那份读数如实报成 `unreadable`（三态），不再是一张服务端 404 页：
        外壳对谁都一样（它是静态页 + 一个挂载点），而"没有这一段会话"是前端按读数说的。

        `sid` 仍然只匹配一段路径（`routes._SEGMENT`）：`/run/`、`/run/a/b` 与
        `..%2f` 那一类解出来带斜杠的串根本不进这一格，它们走
        :meth:`handle_unknown`（404）。
        """
        del params, query
        self._serve_shell_or_404("`/run/{sid}` 这条路由")

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
            self._html(404, _error_page(404, "没有这个文件",
                                        f"静态资源不在盘上或越出根：{rel}"))
            return
        try:
            body = target.read_bytes()
        except OSError as exc:
            self._html(500, _error_page(500, "静态资源读不出来",
                                        f"{type(exc).__name__}: {exc}"))
            return
        ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        cache = ("public, max-age=31536000, immutable" if _HASHED.search(target.name)
                 else "no-store")
        if target.name == "index.html" and ctype.startswith("text/html"):
            body = self._inject_csrf(body.decode("utf-8", errors="replace")).encode("utf-8")
        self._send(200, body, ctype, cache=cache)

    def handle_answer(self, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
        """`POST /answer`：PRG（303 回首页）；qid 不待答 409；写失败 500。

        非 303 的正文由 `writes.answer()` 给（它自己转义过里面的用户文本），
        这里只把它嵌进错误页 —— 不重新渲染、也不二次转义。
        """
        del params, query
        code, location, body = answer(self.root, self._form())
        if code == 303:
            self._redirect(303, location)
            return
        self._html(code, _error_page(code, f"回答没有落地（{code}）",
                                     "写路径自己给的理由在下面这一段里", fragment=body))

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
            self._serve_spa_shell()
            return
        self._html(404, _error_page(404, "没有这个页面", f"没有路由：{path}"))

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
          routes_table: Sequence[tuple[str, str, str]] | None = None,
          heartbeat_sec: float = DEFAULT_HEARTBEAT_SEC) -> ThreadingHTTPServer:
    """建好服务器并返回（不调 `serve_forever`）。

    测试用 `port=0` 起随机端口：返回后读 `srv.server_address[1]` 拿真实端口，
    在 `finally` 里 `srv.shutdown()` + `srv.server_close()`。

    `allow_writes` / `settings_write` 是本批新增的两个开关（裁定 C2 / E1）：
    今天只解析并透传（挂到句柄上、可在 `handler.allow_writes` 读到），
    写面要等 W3、设置写面要等 W4 —— 这一点在 `--help` 与模块 docstring 里都写明了。
    `static_root` / `csrf_token` 也是可注入的：判据要在临时目录里造一份前端外壳，
    并按需钉住令牌（缺省 = 每进程一个随机值）。

    ## 起服务时顺带做的两件事（裁定 1a 的装配，B 线只提供钩子，接的是这里）

    1. `sse.begin_serving(heartbeat_sec=...)` —— 换一代干净的广播器（于是上一个
       进程/上一条判据的事件不会被新服务看见），`heartbeat_sec` 就是这一档；
    2. `sse.attach()` —— 把 `sessions.append` / `userio.ask_user` /
       `userio.answer_question` / `stopctl` 四个钩子接到"发对应 kind 的事件"上。
       它幂等（第二次是替换），所以重复起服务不会把回调叠起来。

    第 1 步与第 2 步都带同一个条件：这一代是 `serve()` 自己开的才做。
    为什么不是无条件调用：判据 `tests/test_webui_sse.py` 的 `_bound_server` 是先
    `begin_serving(heartbeat_sec=0.2)` 再 `serve()` 的，而且那一条用例自己用
    `sse.publish(...)` 造事件、只读一帧 —— 无条件接钩子会多出 `state`/`question`
    两帧、把它的读数挤掉，也会把它那一档心跳换回 15 秒。那是既有的、正确的判据，
    不许为了让接线好看去改它。口径因此写成一句话：这一代谁开的，钩子就谁接
    （调用方先 `begin_serving` 了，说明它自己管接线）；`serve()` 自己开的那一代
    由它接上，于是生产路径（`run()` 与任何直接调 `serve()` 的嵌入方）不缺钩子。

    收尾（`close_all()` + `detach()`）不在这里做：`serve()` 只建服务器、不拥有
    它的生命周期，收尾在 :func:`run` 的 `finally` 里。判据自己起的服务器要自己收
    （`tests/test_webui_sse.py` 的 `_bound_server` 就是这么做的）。
    """
    if not sse.serving():
        sse.begin_serving(heartbeat_sec=heartbeat_sec)
        sse.attach()
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
        description="agentflow 用户端：SPA 外壳（六个页面）+ 六个只读面 + 一趟详情与提交回答")
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
        # 收尾顺序有讲究（裁定 1a 的那一半，B 写明了理由）：
        # ① 先 `close_all()` 关掉所有流 —— `srv.shutdown()` 只停 accept 循环，
        #    `ThreadingHTTPServer` 的入站请求线程不受它影响，一条开着的流会把那个
        #    线程一直占住（`sse.py` 的 `_GENERATION` 就是为这件事设的：流循环每次
        #    迭代读它，看到代结束就自己退出）；
        # ② 再关服务器；
        # ③ 最后 `detach()` 撤掉四个写路径钩子 —— 回到"没人接"的状态（缺省行为），
        #    于是这个进程里剩下的代码不会继续往一个已经关掉的广播器发事件。
        sse.close_all()
        srv.shutdown()
        srv.server_close()
        sse.detach()
    return 0
