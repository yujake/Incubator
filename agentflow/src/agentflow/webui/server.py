# -*- coding: utf-8 -*-
"""用户端 Web 界面的 HTTP 层：`WebHandler` / `serve()` / `run()`。

## 这一层是什么

标准库 `http.server` 上的一个小服务（`ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把 :mod:`agentflow.webui.state` 的快照与十个只读面/写面的读数发成 JSON、
把两个页面入口（`/` 与 `/run/{sid}`）发成前端构建产物那一支外壳，
其余一切人可读的东西都由前端渲染。路由不再写成 `if path == …` 链 —— 它是
:data:`agentflow.webui.routes.ROUTES` 那张表（`draft/73` §1.2 的 R1 拆包）。

## 路由这一层做的四件事

1. 静态路由 `GET /static/<file>`：只服务 `agentflow/src/agentflow/web/static/` 之下的
   真实文件。防线是 `Path.resolve()` 之后必须仍在根内（目录穿越一律拒：
   `..%2f` 一类解出来就落到根外，直接 404）。带内容哈希的文件名按
   `immutable` 缓存，其余（`index.html`）按 `no-store`。
2. SPA 回退（裁定 Q1）：`/api/*` 未知 ⇒ JSON 404（绝不吐 HTML，前端要能区分）；
   其余未知路径 ⇒ 有 `web/static/index.html` 就吐它，否则沿用今天的 404 页。
3. `GET /` 与 `GET /index.html` 直接服务 SPA 外壳（裁定 P1）：SPA 只在"未知路径"的
   回退分支上挂得起来，而 `/` 是已知路径 ⇒ 不改这一格，浏览器地址栏就永远进不了
   SPA 首页。
4. `GET /run/{sid}` 也服务那一支外壳：它是 C4 表里的一条客户端路由，SPA 的 `Run` 页
   按 `sid` 去读 `GET /api/run/{sid}`；会话不在盘上这件事由那份读数如实报成
   `unreadable`（三态），服务端不为它渲染任何盘上数据。服务器自己还写 HTML 的地方
   只剩错误页（见 :func:`_error_page`：外壳不在盘上 / 静态未命中 / 写失败）。

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

## 安全与失败姿态

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`），
  给了就要求 `?token=` / `Authorization: Bearer` / 口令 cookie（见下一节）；
- 服务器自己写的最后一页是 :func:`_error_page`（只有错误页），它把理由串经
  `html.escape` 后才写进 HTML；盘上的文本一律走 JSON —— 前端用文本节点渲染它们
  （两条转义判据见 `tests/test_webui.py`：一条钉服务端，一条钉前端源码里没有
  把字符串当 HTML 用的写法）；
- 写失败不许折成 200（`writes.answer` 的三态）；
- 每个响应都带 `X-Content-Type-Options: nosniff`。

## 口令档（`--token`）：自证与页面各带一次口令

口令档不能"开关一开，服务站不住、站住了也是白屏"，所以有两条硬约束：

1. 自证不带口令（E1）：`run()` 的 `_self_check` 调 `verify_serving(url, root=root)`
   去打 `/api/state`，而口令那一格（:meth:`WebHandler._token_ok`）没有查询串就回 401
   ⇒ 自证 8 秒后判 `unknown`、`srv.shutdown()`、退出 1。打出去的那一行 URL
   于是是一个死地址。修法：口令是 `serve()` 挂到句柄上的同一个事实
   （`handler.token`），`verify_serving(..., token=...)` 把它带进自证请求
   （Bearer 头）；`run()` / `serve()` 的端口探测 / `ensure_serving` 的复用判断
   三处都传同一个值 —— 不许另造第二份口径。
2. 页面带不上口令（E2）：口令模式下外壳里的 `/static/*.js`、`/api/state` 与
   `/api/stream` 都是普通请求（浏览器不会给它们补 `?token=`）⇒ 全 401，`GET /` 拿到
   的 HTML 后面什么都没有。修法：`?token=` 校验通过时种一个同源会话 cookie
   （:data:`TOKEN_COOKIE_NAME`，`Path=/; HttpOnly; SameSite=Strict`），
   `_token_ok` 认它 ⇒ 浏览器随后请求的同源资源（含 `EventSource`）自动带上口令。

为什么是 cookie、不是"前端从 `meta` 里读出来再拼到每个请求/SSE 上"：后者要改
`ui/src/api.ts` / `ui/src/sse.ts` 并重新构建入库的前端产物，还要往外壳里注入第二个
令牌位；而静态资源那一支（`<script src>` / `<link href>`）根本不经过前端代码，
`meta` 方案对它完全无效 ⇒ 两条新面（新 meta 位、新拼串口径）换来的只是同一件事。
cookie 只多一个响应头，`_token_ok` 的口径（`secrets.compare_digest`，fail-closed）
一个字不改。外壳里的资源仍走绝对路径（`/static/assets/...`）：外壳在 `/` 与
`/run/{sid}` 两条路上各吐一次，相对路径到了 `/run/{sid}` 会解析成
`/run/static/...`（深链刷新立刻白屏）—— 缺的是口令，不是相对路径。

## 两个开关（裁定 C2 / E1）：它们真的改变行为

`serve(..., allow_writes=False, settings_write=True)` 与 CLI 的 `--allow-writes` /
`--no-settings-write` 不是"解析了但没人用"的两格：`writes.authorize()` 的授权矩阵
把它们当第 3 层与第 4 层真的判（`writes.py::authorize`）。

- 不开 `--allow-writes`（缺省）⇒ 写面是只读的：`/api/stop` / `/api/submit` /
  `/api/settings` / `/api/budget` / `/api/run` / `/api/task` / `/answer` 的写请求
  一律 403，且这一档一个字节都不往工作区写（连审计台账
  `web-actions.jsonl` 也不写 —— 见 `writes._finish` 的只读分支）。唯一的例外是
  `POST /api/cache/warm` 的「试算」档（`dry_run=1`）：它只保留回环来源那一层
  （`writes.authorize(read_only=True)`），不写盘、不花钱、不起进程 ⇒ 只读档也回 200；
  它「真跑」那一档照样要 `--allow-writes`。这一点以前被写成"七条写端点一律 403"，
  与实现相反 —— AUDIT F6 修的就是这句文案（试算本来就不该写盘，所以是文案错、
  不是行为错）；
- `--no-settings-write` 只关第 4 层：`POST /api/settings` 403，其余写端点照旧；
- `POST /answer` 也在这道闸门后面（2026-11-21 WEBFIX1 / 审计 F4）：它此前只靠
  `userio.answer_question` 兜底，跨站页面不带 CSRF 也能把一条待答答掉并落盘。
  现在 `handle_answer` 把请求句柄交给 `writes.answer()`，与其余写端点共用
  `writes._gate`；只读档连会话事件也不写。

`--help` 里逐字写着这三条（那两句"本批还没有接线：现在给不给都一样"与实现相反，
`agentflow web --help` 早就说的是对的 —— 同一仓库两套 help 不许互相打脸）。
`cli.py::cmd_web` 的 docstring 是第三份公开文本，三处必须同一口径。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..stop_reasons import STOP_REASONS
from . import routes, sse
from .state import _esc, _text
from .writes import answer, writes_allowed

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

#: 口令 cookie 的名字（E2）：`?token=` 校验通过之后种下的同源会话 cookie，
#: `_token_ok` 认它。浏览器随后请求的 `/static/*`、`/api/*` 与 `EventSource` 会自动带上
#: —— 这就是"口令随页面到达后续请求"那一条（理由见模块 docstring 的「口令档」一节）。
#: 名字带 `agentflow_` 前缀：同一台机器上别的服务另起一个 cookie 名，不会互相顶掉。
TOKEN_COOKIE_NAME = "agentflow_web_token"


def token_cookie_header(value: str) -> str:
    """口令 cookie 的 `Set-Cookie` 整行（`value` 在这里做百分号编码）。

    `HttpOnly`：前端脚本读不到它（少一条 XSS 泄漏面）；`SameSite=Strict`：跨站导航
    不带它（口令不能靠"受害者刚好打开一个链接"送达）；不写 `Secure`：本服务默认
    只听回环、走的是 `http://`，写上 `Secure` 会让浏览器直接丢掉它。
    不写 `Max-Age`：会话 cookie，关掉浏览器就没了（口令不该在盘上过夜）。
    """
    return (f"{TOKEN_COOKIE_NAME}={quote(str(value), safe='')}; "
            "Path=/; HttpOnly; SameSite=Strict")


def cookie_value(header: str, name: str) -> str:
    """从 `Cookie` 头里取一个值（解百分号编码；没有就是空串，不抛）。"""
    for part in str(header or "").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip() == name:
            return unquote(value.strip().strip('"'))
    return ""


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
#: 表体不在这里写：它与 `cli.EXIT_CODE_BY_STOP` 同源于
#: :data:`agentflow.stop_reasons.STOP_REASONS`。手写一份时，
#: `final_refused` 只进了退出码表（5），界面于是显示一个空徽标；反过来这里多一格
#: `max_steps`（旧读数）。现在这里投影全部条目，退出码表只投影 `live=True` 的那些，
#: 两表多出来的那一格必须是 `live=False`，判据双向钉住。
#:
#: 它留在 HTTP 层是因为两个既有读法都在这里：`agentflow.webui._STOP_BADGES`
#: （`tests/test_loop_liveness.py` 与 `tests/test_the_roster_and_the_interrupt.py` 读它）
#: 与 `W._STOP_BADGES` 这个落点。生产路径上今天没有读者 —— 前端
#: `ui/src/pages/Run.tsx` 原样显示 `stop_reason` 的文本，不读这张表；旧壳
#: `webui/views.py` 在 W5 退场后，这张表只剩判据与 :func:`stop_badge` 这一个渲染入口。
_STOP_BADGES: dict[str, tuple[str, str]] = {
    reason: (row[1], row[2]) for reason, row in STOP_REASONS.items()
}


def stop_badge(reason: str) -> tuple[str, str]:
    """把一个 `stop_reason` 渲染成徽标 `(class, 文案)`，未知也一定有文案。

    为什么兜底文案里带上原值：只写「未知」会让读的人不知道去查哪个词；把原值留在
    括号里，界面上的空徽标就成了一条可检索的读数。空字符串也走这一支（旧会话记录
    里确实有还没定论的趟）—— 它渲染成「未知收场（空）」，而不是一个空徽标。
    """
    key = str(reason or "")
    got = _STOP_BADGES.get(key)
    if got is not None:
        return got
    return ("badge-unknown", f"未知收场（{key or '空'}）")


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


#: "对端没了"的三种异常（唯一的名单，E3）。
#:
#: 为什么必须只有一处：同一个事实原先在这份文件里有两份名单 ——
#: `handle_one_request` 认三种，`_invoke` 只认两种（漏了 `ConnectionAbortedError`）。
#: 于是客户端导航（浏览器把连接掐掉）在处理器回话那一步抛出的
#: `ConnectionAbortedError: [WinError 10053]` 落到 `_invoke` 的兜底分支，
#: 被记成一次 `handler_crashed` 500 + 一整段 traceback（实测：一次浏览器套件 27 次）。
#: `sse.py` 的流循环另有自己的收尾（那边连 `OSError` 一起算正常终点，因为一条流的
#: 写失败就是它该结束的时候）—— 它问的是另一件事，所以不并进这里。
#: 判据 `tests/test_webui_client_abort_is_not_a_500.py` 钉着"这三个名字全树只出现一次"。
PEER_GONE = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)

#: 回"这一支不打算读正文"的响应（404 / 401 / 405 / 500）之前，最多补读多少字节。
#:
#: chunked 那一档按载荷累计（帧开销不计）；两档共用这一个上限。
#: 为什么要有上限：补读是"等客户端把它声明的那段正文发完"，不设上限等于让一个
#: 声明了 4 GB 的请求把这条连接线程占住。未知端点上的正文超出这个量时直接回话，
#: 客户端本来也不该往没有路由的地方贴大块正文。
UNREAD_BODY_CAP = 1 << 20

#: 补读正文的时限（秒）。客户端声明了 `Content-Length` 却不发，最多等这么久就回话。
UNREAD_BODY_SEC = 5.0


class WebHandler(BaseHTTPRequestHandler):
    """路由表驱动的小服务（表在 :data:`agentflow.webui.routes.ROUTES`）。

    四个由 :func:`serve` 挂上去的事实：工作区根、共享口令、静态根、CSRF 令牌；
    外加两个开关（`allow_writes` / `settings_write`，由 `writes.authorize` 真的判）。
    """

    server_version = "agentflow-webui"
    protocol_version = "HTTP/1.0"

    #: 由 :func:`serve` 挂上去的事实（类属性默认值让直接实例化也能跑）。
    root: Path = Path(".")
    token: str = ""
    static_root: Path = default_static_root()
    csrf_token: str = ""
    #: 两个开关（裁定 C2 / E1）：`writes.authorize` 把它们当第 3 / 第 4 层真的判。
    allow_writes: bool = False
    settings_write: bool = True
    #: 路由表可注入（`serve(routes_table=...)`）：空元组 = 用 `routes.ROUTES`（缺省）。
    #: 为什么要有这个注入点：判据要拿"多了一条子表的表"走一遍真实请求，证明接缝真的接通；
    #: 有了它就不必去改模块全局（改全局的判据会污染别的用例）。
    routes_table: tuple = ()

    #: 本次请求解出来的路径（`_parse` 填；未知路由那一条要用它说清"是什么没找到"）。
    _path: str = ""
    #: 这一趟请求的正文是否已经被读过（`_form()` 或 `_drain_unread_body()` 置真）。
    #: 每个请求一个实例，所以它是逐请求的事实，不是进程级开关。
    _form_read: bool = False
    #: 这一趟要不要在响应里种口令 cookie（`_token_ok` 在"地址栏带口令"那一档置真；
    #: 每个请求一个实例，所以它是逐请求的事实，不是进程级开关）。
    _set_token_cookie: bool = False

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 基类签名
        """默认日志会往 stderr 打每一行请求；改成一条短行（测试里也不吵）。"""
        sys.stderr.write("[webui] %s\n" % (fmt % args))

    # ------------------------------------------------------------ 口令
    def _want_token(self) -> str:
        """这一趟要求的口令（`serve()` 挂上来的那一格；没有就退回环境变量）。

        口令只有一个真身：`serve()` 挂到句柄上的 `token`（环境变量那一档在
        `run()` 里已经折进同一个值，但直接调 `serve()` 的嵌入方也可能只设了环境变量，
        所以这里照旧兜一层）。自证 :func:`verify_serving` 拿的是同一个值 —— E1 修的
        正是"自证另走一条不带口令的路"。
        """
        return str(self.token or os.environ.get("AGENTFLOW_WEB_TOKEN", ""))

    def _token_ok(self, query: Mapping[str, Sequence[str]]) -> bool:
        """给了口令就要求它：`?token=` / `Authorization: Bearer` / 口令 cookie。

        三个来路只认同一个口令值（`_want_token()`），比对一律走
        `secrets.compare_digest`。地址栏那一路（`?token=`）校验通过时顺手种 cookie
        （:data:`TOKEN_COOKIE_NAME`）—— 浏览器只会在地址栏里带一次 `?token=`，
        外壳里的 `/static/*` 与前端 fetch / `EventSource` 都不带查询串（E2）。
        """
        want = self._want_token()
        if not want:
            return True
        got = ""
        vals = query.get("token") or []
        if vals:
            got = _text(vals[0])
        if got:
            ok = secrets.compare_digest(got.encode("utf-8"), want.encode("utf-8"))
            if ok:
                # 只在"地址栏那一趟"种：Bearer / cookie 这两路都是后续请求，不再种。
                self._set_token_cookie = True
            return ok
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            got = auth[7:].strip()
        if not got:
            got = cookie_value(self.headers.get("Cookie", ""), TOKEN_COOKIE_NAME)
        # 与写面的 CSRF 那一格同一条口径（`writes._csrf_ok`）：口令比对走
        # `secrets.compare_digest`，不用 `==`。比的是令牌，逐字符提前返回的
        # 相等比较会把"对了几个字符"泄给对端；本服务默认只听回环，所以这
        # 一格不是主防线，但同一个仓库里两处口令用两种比法是没必要的分叉。
        return bool(got) and secrets.compare_digest(got.encode("utf-8"),
                                                    want.encode("utf-8"))

    # ------------------------------------------------------------ 输出
    def _send(self, code: int, body: bytes, ctype: str,
              extra: Mapping[str, str] | None = None,
              cache: str = "no-store") -> None:
        """一个响应（HEAD 只发头）。`cache` 是 Cache-Control 那一格。

        口令 cookie 在这里统一补（E2）：`_token_ok` 判定"这一趟是地址栏带口令来的"
        之后置 `_set_token_cookie`，于是这一趟的响应（外壳 200、`/api/*` 的 JSON、
        甚至一条诚实的错误页）都带上 `Set-Cookie`。放在 `_send` 而不是各个 handler
        里，是因为"哪个 handler 记得种 cookie"正是会漏一处的形态。
        """
        headers = dict(extra or {})
        if self._set_token_cookie:
            headers.setdefault("Set-Cookie", token_cookie_header(self._want_token()))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers.items():
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
        self._form_read = True
        raw = self.rfile.read(length) if length > 0 else b""
        return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)

    def _content_length(self) -> int:
        """`Content-Length` 声明的字节数（没有 / 不是数字 ⇒ 0）。"""
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except (TypeError, ValueError):
            return 0

    def _is_chunked(self) -> bool:
        """这一条请求的正文是不是 `Transfer-Encoding: chunked` 帧（没有长度可读）。"""
        return "chunked" in (self.headers.get("Transfer-Encoding") or "").lower()

    def _drain_declared(self, length: int) -> None:
        """按 `Content-Length` 读掉正文（上限 :data:`UNREAD_BODY_CAP`）。"""
        left = min(length, UNREAD_BODY_CAP)
        while left > 0:
            chunk = self.rfile.read(min(left, 65536))
            if not chunk:
                return
            left -= len(chunk)

    def _drain_chunked(self) -> None:
        """按 chunk 帧读到终止块（`0\\r\\n\\r\\n`），两道上限同 :meth:`_drain_unread_body`。

        帧解析失败（大小行没有换行 / 不是十六进制 / 帧尾不是 CRLF / 没等到终止块就
        断了）⇒ 立刻停止补读并回话：补读是为了"别让迟到的正文变成 RST"，
        不是为了替坏客户端把一条连接线程挂到时限。载荷累计超过
        :data:`UNREAD_BODY_CAP` 也立刻停（帧开销不计入）。
        """
        total = 0
        while True:
            line = self.rfile.readline(1024)
            if not line.endswith(b"\n"):
                return
            try:
                size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError:
                return
            if size < 0:
                return
            if size == 0:
                # 终止块之后还有 trailer（可以是空的），读到空行为止；同样有上限。
                for _ in range(64):
                    trailer = self.rfile.readline(1024)
                    if not trailer.endswith(b"\n"):
                        return
                    if trailer in (b"\r\n", b"\n"):
                        return
                return
            if total + size > UNREAD_BODY_CAP:
                return
            left = size
            while left > 0:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    return
                left -= len(chunk)
            total += size
            if self.rfile.read(2) != b"\r\n":
                return

    def _drain_unread_body(self) -> None:
        """把"这一支不打算读"的请求正文读掉，「再」回话（不读 ⇒ 客户端可能读到 RST）。

        ## 为什么必须读（WinError 10053 实测）

        `do_POST` 在"路由没命中"那一支直接回 404，从不碰正文；而 `http.client`
        发请求时分两次 `send()` —— 先发头块、再发正文（`http.client._send_output`
        里 `self.send(msg)` 之后才 `for chunk in chunks: self.send(chunk)`）。
        多任务负载下客户端可能在这两次之间被换下 CPU，服务器于是"只看到头就回 404、
        把连接关掉"；随后到达的正文落在已关闭的连接上 ⇒ 本机发 RST，客户端
        `getresponse()` 读到的是 `ConnectionAbortedError: [WinError 10053]`
        而不是那支 404（全量四路并行复现：`temp/pytest-all/20261110-131802/
        chunk-0.log`；确定性最小复现：`temp/probe_404_split_body.py 0.2`）。
        先读完正文再回话，404 就真的到得了客户端。

        ## 口径

        - `Content-Length` 那一档：只读声明的那一段（上限 :data:`UNREAD_BODY_CAP`），
          不从连接上多读一个字节（多读会吃掉下一条请求）；
        - `Transfer-Encoding: chunked` 那一档：按 chunk 帧读到终止块（`0\\r\\n\\r\\n`），
          同样受 :data:`UNREAD_BODY_CAP`（按载荷累计，帧开销不计）与
          :data:`UNREAD_BODY_SEC` 约束；帧解析失败就立刻停止补读、立即回话
          （不许因此把连接线程挂住）；
        - 时限 :data:`UNREAD_BODY_SEC` 秒：客户端声明了长度/开了 chunked 却不发，
          最多等这么久就回话，不把这条连接线程永远挂住；
        - `_form()` 已经读过（或本函数补读过）⇒ `_form_read` 为真，直接返回 ——
          重复补读会去等一段已经不存在的正文，把回话拖到时限。

        ## 已知限制（业主裁定：登记，不补）

        GET 带正文这一格不补读：HTTP 语义里 GET 正文没有定义，补它会把"未读正文"的
        责任从客户端搬到服务端，而现无客户端这么发。若将来有，按 chunked 那一套补。
        """
        if self._form_read:
            return
        self._form_read = True
        try:
            old = self.connection.gettimeout()
            self.connection.settimeout(UNREAD_BODY_SEC)
        except OSError:
            return
        try:
            if self._is_chunked():
                self._drain_chunked()
            else:
                self._drain_declared(self._content_length())
        except OSError:
            # 正文没发完就对端没了 / 等超时：回话比"读完"重要，照旧回。
            pass
        finally:
            try:
                self.connection.settimeout(old)
            except OSError:
                # 套接字已经关了 ⇒ 没有"原时限"可恢复；本连接反正到此为止。
                pass

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

        口径刻意只认三种"对端没了"的异常（名单只有一个：:data:`PEER_GONE`），
        其余异常一律照旧冒泡给 `socketserver.handle_error` —— 顺手 catch
        `Exception` 会让真错误从日志里消失，那比日志脏坏得多（本项目
        "没查成与查过了没问题必须分得开"的同一条纪律）。
        收尾方式与 `socketserver` 自己的 TimeoutError 那一支相同：置
        `close_connection = True`，让 `handle()` 的循环正常结束。
        """
        try:
            super().handle_one_request()
        except PEER_GONE:
            self.close_connection = True

    # ------------------------------------------------------------ 401 形态
    def _unauthorized(self) -> None:
        """口令不对/没给：`/api/*` 回 JSON，页面与静态资源回 HTML（E9）。

        为什么按路径分：`/api/*` 的其余错误一律 JSON
        （Q1：未知端点 404 JSON），只有 401 这一格不分路径、一律吐 HTML ——
        前端 `api.ts` 的 `readJSON` 只能把一整段 `<!DOCTYPE html>…` 当理由塞进
        `ApiError.reason` 上屏。两档的形状：`/api/*` → `{"ok": false, "tri":
        "not_applicable", "reason": …}`；其余 → 那张 401 HTML 页（浏览器看得懂）。
        """
        reason = "口令不对或没给（?token= / Authorization: Bearer / 口令 cookie）"
        # 401 也是"这一支不打算读正文"：POST 带正文到受口令保护的路径时，同样会
        # 在关口那一刻被迟到的正文变成 RST（口径见 `_drain_unread_body`）。
        self._drain_unread_body()
        if self._path.startswith("/api/"):
            self._json(401, {"ok": False, "tri": "not_applicable",
                             "reason": reason, "path": self._path})
            return
        self._html(401, "<!DOCTYPE html><html><body><h1>401</h1>"
                        f"<p>{_esc(reason)}</p></body></html>")

    # ------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 - 基类签名
        """GET：查 `ROUTES`；未命中走 :meth:`handle_unknown`（裁定 Q1）。

        响应形态不是一种：`routes.route_kind(path)` 里标成 `stream` 的那条
        （今天只有 `GET /api/stream`）会在处理器里一直推、不返回。普通 GET 的
        "读完即返"断言对它必超时 —— 那不是这条端点坏了，是断言用错了；
        清单（`routes.endpoint_inventory` / `--list-routes`）必须把它标成 stream。
        """
        path, query = self._parse()
        if not self._token_ok(query):
            self._unauthorized()
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
            self._unauthorized()
            return
        hit = routes.match("POST", path, table=self.routes_table or None)
        if hit is None:
            # 404 之前先把这一支不打算读的正文读掉（否则它会在关口那一刻变成 RST）。
            self._drain_unread_body()
            if path.startswith("/api/"):
                # 与 GET 同一条口径（裁定 Q1）：`/api/*` 未知一律 JSON 404，
                # 免得前端在读 JSON 时拿到一支 HTML。
                self._json(404, {"ok": False, "tri": "not_applicable",
                                 "kind": "unknown_endpoint",
                                 "how_to_fix": ("路由表里没有这一条 —— 前端与后端"
                                                "可能不是同一版；刷新页面，仍不行就重启服务"),
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

        ## 处理器抛了也必须有回话（真机）

        真机：`serve web` 在 8788 上把 URL 打了出来，而 `/api/state` 的请求被直接关掉
        （客户端看到 `RemoteDisconnected: Remote end closed connection without response`，
        裸 socket 探到的首行是空的）。原因就是这里没有兜底：处理器一抛，`BaseHTTPRequestHandler`
        的 `handle_one_request` 只会 `close_connection`，于是"服务器活着、却什么都不说"。
        那一档既看不见原因、也让 `verify_serving` 自证只能报"打不通"。

        所以这里兜住：回 500 JSON（`{"ok": false, "kind": "handler_crashed", ...}`），
        并把 traceback 逐行写进 stderr（人能从日志里读到是哪一行）。

        ## 例外：客户端先走了

        三种"对端没了"（:data:`PEER_GONE`）原样上抛，不记 500、不打 traceback：
        那不是处理器崩了，是浏览器导航时把连接掐掉了。这里原先自己列了一份两种的
        名单（漏了 `ConnectionAbortedError`），于是 WinError 10053 被记成事故
        （实测一次浏览器套件 27 次）。名单现在与 `handle_one_request` 共用一处。
        """
        try:
            local = getattr(self, name, None)
            if callable(local):
                local(params, query)
                return
            sub = routes.handler_for(name)
            if sub is not None:
                sub(self, params, query)
                return
        except PEER_GONE:
            # 客户端自己断了：不是我们的错，也没有可回话的对象。
            raise
        except Exception as exc:  # noqa: BLE001 —— 兜底是为了"有回话 + 有日志"
            import traceback

            sys.stderr.write(f"[webui] 处理器 {name} 抛了："
                             f"{type(exc).__name__}: {exc}\n")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            # 500 也是"这一支不打算把正文交给处理器"：处理器的正文没读过时补读，
            # 免得迟到的正文把这一支 500 变成 RST（口径见 `_drain_unread_body`）。
            # `_invoke` 也会被判据用最小句柄直接调用
            # （`tests/test_a_crashing_handler_still_answers.py`），那种句柄没有这一格。
            drain = getattr(self, "_drain_unread_body", None)
            if drain is not None:
                drain()
            try:
                self._json(500, {"ok": False, "tri": "unreadable",
                                 "kind": "handler_crashed",
                                 "how_to_fix": ("这是服务端缺陷：这一条读数没查成，"
                                                "盘上一个字节没动；把这一行与时间报给维护者"),
                                 "handler": str(name),
                                 "reason": f"{type(exc).__name__}: {exc}"})
            except Exception:  # noqa: BLE001 —— 连回话都写不出去时只能放弃
                pass
            return
        drain = getattr(self, "_drain_unread_body", None)
        if drain is not None:
            drain()
        self._send(500, f"500 路由表登记了没有实现的处理器：{name}\n".encode("utf-8"),
                   "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802 - 基类签名
        """HEAD 按 GET 处理（`_send` 不写正文），方便探活。"""
        self.do_GET()

    def _reject(self) -> None:
        """405：方法不在这一面的名单里。PUT/DELETE/PATCH 也可能带正文，先读掉。"""
        self._drain_unread_body()
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
        self._html(200, self._inject_placeholders(self._inject_csrf(shell)))
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

        doc = dict(SS.run_index_report(self.root))
        if str(doc.get("tri") or "") != "computed":
            # AUDIT F10：`unreadable` / `not_applicable` 那一档必须说清"为什么恒这样、
            # 怎么修"。真身在读侧 `readers.run_index_reason`（这一行只是转发）——
            # 它住读侧，是因为那是"盘上事实怎么读"，判据要能脱离 HTTP 直接钉住它。
            from . import readers as RD

            doc["reason"] = RD.run_index_reason(self.root, doc)
        self._json(200, doc)

    def handle_run_digest(self, params: Mapping[str, str],
                          query: Mapping[str, Sequence[str]]) -> None:
        """`GET /api/run-digest`：从事件流现算的趟次档案（业主裁定「甲」）。

        与 `/api/run-index` 是两条独立的读数，各自读自己的来源：

        - 索引那一格读盘上的 `index/run-index.json`（只在收工成功时建）；
        - 这一格每次都从 `sessions/*.jsonl` 现算，不给 `sid` 就是整个工作区，
          给了就只算那一段会话。不读、不写索引 —— 收工没做成/被叫停的趟
          在这一格里有值，索引那一格仍是 `unreadable`（裁定 ④a 要的正是这个）。

        三态在正文里（`tri` + `reason`），读不到也回 200：与 `handle_run_index`
        同一档 —— "没查成"是一条读数，不是一次请求失败。

        读数走 `facecache.cached_face`（按盘失效，与 `/api/package` 同一套）：
        这个面要扫全部会话文件，页面上每翻一次都要读；同一份盘、同一组参数直接复用。
        `cache` 只在 HTTP 外壳上，不进 `run_digest()` 的返回 —— 那是读模型，
        与 `ui/src/types.ts` 的 `RunDigestView` 逐格对齐。
        """
        del params
        from . import facecache
        from . import readers as RD

        sid = str((query.get("sid") or [""])[0])
        face, cache = facecache.cached_face(
            "run-digest", self.root, {"sid": sid},
            lambda: RD.run_digest(self.root, sid))
        self._json(200, {**face, "cache": cache})

    def handle_errors(self, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> None:
        """`GET /api/errors`：按角色 × 类目的错误动作计数（只读，零模型调用）。

        形状是 `readouts.errors_readout(self.root)` 的返回值逐字（五个键：
        `checked` / `state` / `reason` / `data` / `problems`）。为什么不在这里另算一遍：
        计数口径（角色归属、主码规则、三态）全在 `errorstats` 里，"谁算这个数"只有一个
        真身；这一层再拆一遍就是两份口径，而两份漂了不会有任何地方报错。

        读不到时照样回 200：三态在正文里（`state="unknown"` + `reason`），因为
        "没读到"是一条读数，不是一次请求失败（与 `handle_run_index` 同一档）。
        它不需要写权限：这一格只读盘、不花一分钱。
        """
        del params, query
        from .. import readouts as RD
        from . import readers as RD_FACES

        # 2026-11-24：`unclassified_signal` 那条说明改成能照做的一句（只改 detail，
        # 不改计数 —— 口径与族表在 `errorstats`，这里另算一份就是两个出口两句话）。
        self._json(200, RD_FACES.annotate_errors_readout(RD.errors_readout(self.root)))

    def handle_errors_categories(self, params: Mapping[str, str],
                                 query: Mapping[str, Sequence[str]]) -> None:
        """`GET /api/errors/categories`：错误类目 → 那一句含义（只读，源自 errorstats）。

        这一条只为一件小事存在：点开某一行时，每格旁边的"这个类目指什么"要是同一句话。
        那句话的真身在 `errorstats.ERROR_CATEGORIES`，网页这一层不许自己再写一份
        （写两份就迟早说两种话，而两种话没有任何机器读数看得见）。

        它没有三态：`ERROR_CATEGORIES` 是模块里的常量表，读不出来时进程在导入期就起不来，
        不存在"这一份没读到"的形态。`source` 那一格写清真身在哪，免得有人以为它是盘上的数据。
        """
        del params, query
        from .. import errorstats as ES

        self._json(200, {"categories": [{"name": name, "meaning": why}
                                        for name, why in ES.ERROR_CATEGORIES],
                         "source": "agentflow.errorstats.ERROR_CATEGORIES"})

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
            resolved = root.resolve()   # 一次解析，下面两处判据用同一份
            target = (root / rel).resolve()
            inside = target == resolved or resolved in target.parents
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
        """`POST /answer`：PRG（303 回首页）；闸门拒 403；qid 不待答 409；写失败 500。

        非 303 的正文由 `writes.answer()` 给（它自己转义过里面的用户文本），
        这里只把它嵌进错误页 —— 不重新渲染、也不二次转义。

        `handler=self` 是同一道写面闸门的输入（审计 F4）：`writes.answer()` 用
        它与其余写端点共用 `writes._gate`（回环来源 ⇒ CSRF ⇒ `allow_writes`）。
        在这之前 `/answer` 只靠 `userio.answer_question` 兜底，跨站页面不带 CSRF
        也能答掉一条待答；现在它和 `/api/task` 一样过闸门（拒时 403 + 同一份
        `kind` / `how_to_fix`），盘上零写入。

        `audit_enabled` 取 :func:`agentflow.webui.writes.writes_allowed` 这同一个事实：
        只读档不落 `web-actions.jsonl`（那是工作区根上的一个文件）。闸门先回
        403 `writes_off`，所以只读档连会话事件也不写。
        """
        del params, query
        code, location, body = answer(self.root, self._form(), handler=self,
                                      audit_enabled=writes_allowed(self))
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
                             "kind": "unknown_endpoint",
                             "how_to_fix": ("路由表里没有这一条 —— 前端与后端"
                                            "可能不是同一版；刷新页面，仍不行就重启服务"),
                             "reason": f"没有这个端点：{path}", "path": path})
            return
        if self._wants_html():
            # 外壳在不在由 `_serve_spa_shell` 自己判（那一次 `is_file` 就是这句话的
            # 唯一判据）：吐出去了就到此为止，吐不出去才落到下面那张诚实的 404 —— 与
            # 原来"先 is_file、再交给同一个函数再 is_file 一次"逐条同结局。
            if self._serve_spa_shell():
                return
        self._html(404, _error_page(404, "没有这个页面", f"没有路由：{path}"))

    # ------------------------------------------------------------ 外壳占位符
    def _inject_csrf(self, html_text: str) -> str:
        """把 `index.html` 里的 `__CSRF__` 换成这一次进程的令牌。

        令牌由 :func:`serve` 每进程随机生成，所以盘上的产物里没有真令牌
        （裁定 B1 把产物入库，写死一个令牌等于把它一起发布出去）。W0 没有任何端点
        消费它（写面在 W3）；它先占位，让"令牌从哪来"这件事在链路上是通的。
        """
        return html_text.replace("__CSRF__", self.csrf_token or "")

    def _inject_placeholders(self, html_text: str) -> str:
        """把外壳里的项目身份占位符换成这一趟服务真读到的读数。

        四个占位符 —— `__PROJECT_NAME__` / `__PROJECT_TITLE__` /
        `__PROJECT_ROOT__` / `__CURRENT_SID__` —— 都由 `webui.state` 那两个读者给
        （`project_reading` / `current_reading`），不在这里另算一份：项目名与路径的
        唯一来源是项目文件夹本身（`projects.resolve` 的口径），当前会话号的唯一来源是
        `serve(sid=…)` 交下来的那一个。

        为什么本项目要这一步：业主盯着跑时先看的是浏览器标签页。一页只有
        「agentflow 用户端」时，同时开两个项目的两页分不出谁是谁；而"我点开的到底是
        哪个项目"正是 2026-11-14 那起落点事故里最难自查的一格。

        读不出来时占位符换成空串/目录名兜底，不留字面量 `__PROJECT_NAME__`
        （那会被读成"项目的名字就叫这个"）。
        """
        import html as _html

        from .state import current_reading, project_reading

        try:
            proj = project_reading(self.root)
        except Exception:  # noqa: BLE001 - 外壳不该因为读数失败而 500
            proj = {}
        try:
            cur = current_reading(Path(self.root),
                                  getattr(self, "sid", "") or "")
        except Exception:  # noqa: BLE001 - 同上
            cur = {}
        name = str(proj.get("name") or "") or Path(str(self.root)).name
        if proj.get("is_project"):
            title = name
        elif str(proj.get("state") or "") in ("absent", "empty"):
            # `--watch` 先起网页、真机还没开跑：项目文件夹刚 mkdir 出来，还没有
            # project.json。标题如实说"还没初始化"，不冒充"这不是一个项目"。
            title = f"{name}（还没初始化）"
        else:
            title = "（不是项目文件夹）"
        return (html_text
                .replace("__PROJECT_NAME__", _html.escape(name, quote=True))
                .replace("__PROJECT_TITLE__", _html.escape(title, quote=True))
                .replace("__PROJECT_ROOT__",
                         _html.escape(str(self.root), quote=True))
                .replace("__CURRENT_SID__",
                         _html.escape(str(cur.get("sid") or ""), quote=True)))


# ====================================================================== 服务
#: 起服务那一层的受控拒绝：端口已被占、或绑完自证不通过。
#: 它继承 `RuntimeError` 而不是 `SystemExit`：`serve()` 是库函数，调用方（CLI / 判据）
#: 各自决定怎么收场；`run()` 把它翻成非零退出并打一行人话。
class WebStartupError(RuntimeError):
    """服务起不来（不是"起好了但没人来"）。`owner` 是端口占位者的读数（可能为空）。"""

    def __init__(self, message: str, *, owner: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.owner: dict[str, Any] = dict(owner or {})


def port_owner(host: str, port: int, *, timeout: float = 2.0,
               token: str = "") -> dict:
    """这个端口上有没有"正在服务的东西"（三态：`free` / `busy` / `unknown`）。

    ## 判据是"连得上"，不是"bind 得上"

    只用裸 `bind` 探会错：Windows 上对一个还挂在 TIME_WAIT 的端口 bind 同样报
    `WSAEADDRINUSE`，而那个端口上根本没有 listener —— 于是刚被杀掉的网页服务会让下一次
    "开网页"空等四分钟才报错（真机：`/api/state` 明确"积极拒绝"，而这里说"已经被占用"）。
    `SO_REUSEADDR` 不能用来区分这两件事：它连"另一个进程正在听"也一起放行（双绑静默成功）。

    所以改成先连一次（那才是"有没有人在服务"）：
    - 连上了 ⇒ `busy`；
    - 被积极拒绝 ⇒ `free`（TIME_WAIT 是这一档：没人听，只是四条元组还没老化）；
    - 超时 / 其它 ⇒ 退回裸 bind：bind 不上就 `busy`（fail-closed，宁可不绑也不双绑），
      bind 得上就是 `free`。

        返回 `{"checked","state","root","pid","reason"}`；`root` / `pid` 来自对面 `/api/state`
    的自述（读不出就是空串 / 0，不代表"没有占位者"）。

    `token` 是这一趟的口令：口令档下自述那一趟必须带它，否则 401 会让一个真正在
    服务的自己人被读成 `unknown`（E1 的同一处口径；这里缺了那一条，`--port N` 的
    第二次启动就会在 Windows 的 `SO_REUSEADDR` 下静默双绑，正是这个函数要防的事）。
    """
    import socket

    out: dict[str, Any] = {"checked": True, "state": "free", "root": "", "pid": 0,
                           "reason": ""}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.4)
            try:
                probe.connect((host, int(port)))
            except ConnectionRefusedError:
                out["reason"] = "连接被拒绝（没有 listener；TIME_WAIT 也走这一档）"
                return out
            except (socket.timeout, TimeoutError):
                out["reason"] = "连接超时 ⇒ 退回去用 bind 判"
                out["state"] = "unknown"
            except OSError as exc:
                # Windows 的 10061 会翻成 ConnectionRefusedError，走不到这里；
                # 其余（例如地址不可用）一律按"没查成"处置。
                out["state"] = "unknown"
                out["reason"] = f"连接探不了：{type(exc).__name__}: {exc}"
                return out
        if out["state"] == "unknown":
            # 连接超时 + bind 失败：可能是 TIME_WAIT（没人听），也可能是别的进程在听但
            # 回不了我们的连接。这一档判不了 —— 回 `unknown`，由起服务之后那一步
            # `verify_serving` 自证（根对不上就不假装在服务），而不是在这里折成 busy
            # 让人空等（真机：网页服务刚被杀掉，8788 被 TIME_WAIT 挡住四分钟）。
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bindprobe:
                try:
                    bindprobe.bind((host, int(port)))
                except OSError as exc:
                    out["reason"] = (f"连接超时且 bind 失败（{type(exc).__name__}）"
                                     "⇒ 判不了，交给起服务之后的自证")
                    return out
                out["state"] = "free"
                return out
        # 连上了不等于"在服务网页"：TIME_WAIT 里也连得上（真机 8788 全是 TimeWait、
        # 零个 listener，`Get-NetTCPConnection` 可核）。所以再用一次 `/api/state` 自述：
        # 真答得上来才判 busy，否则回 unknown（让真正的 bind + 起服务后的自证去决定）。
        got = verify_serving(f"http://{host}:{int(port)}/", root="", token=token)
        if isinstance(got, dict) and str(got.get("state") or "") in ("ok", "mismatch"):
            # "ok" = 在服务就是我们要的那个工作区；"mismatch" = 在服务、但根不是我们 ——
            # 两种都算"有人在服务这个端口"，只有 "unknown"（答不上来）才判不了。
            out["state"] = "busy"
            out["root"] = str(got.get("root") or "")
            return out
        out["state"] = "unknown"
        out["reason"] = ("连得上但 /api/state 没有正答 ⇒ 判不了（"
                         + str((got or {}).get("state") if isinstance(got, dict) else got)
                         + "），交给起服务之后的自证")
        return out
    except Exception as exc:  # noqa: BLE001 —— 探不了就是"没查成"
        return {"checked": False, "state": "unknown", "root": "", "pid": 0,
                "reason": f"{type(exc).__name__}: {exc}"}


def verify_serving(url: str, *, root: str | Path, timeout: float = 5.0,
                   token: str = "") -> dict:
    """绑完自证：这一趟的端口真是自己在服务吗（三态，`ok` 才放行）。

    `mismatch` = 200 但 root 不是这一趟 ⇒ 端口上答话的是别人（"绑上了却空转、
    真正答话的是旧服务"的形态）；`unknown` = 连不上/不通 ⇒ 没查成，不许折成 ok。

    `token` 是这一趟的口令（缺省空 = 不要求口令，与"服务没开口令"同一档）。
    E1 的修法就是这一个参数：自证要证明的是"带口令的这一趟在服务"，所以它必须
    带和 `handler._want_token()` 同一个值（`?token=` 这一档在这里走 Bearer 头，
    免得口令进 URL；两者在 `_token_ok` 里是同一条比对）。不带 ⇒ 口令档下恒 401
    ⇒ 自证判 `unknown`（今天那条 9.2 秒后退出 1 的路）。
    """
    import urllib.request

    want = str(Path(root).resolve())
    out: dict[str, Any] = {"checked": True, "state": "unknown", "code": 0, "root": "",
                           "reason": "", "url": url}
    target = url.rstrip("/") + "/api/state"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(target, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - 本机自检
            out["code"] = int(getattr(resp, "status", 0) or 0)
            body = resp.read()
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"打不通 {target}：{type(exc).__name__}: {exc}（没查成，不是通过）"
        return out
    if out["code"] != 200:
        out["reason"] = f"{target} 回了 {out['code']}（不是 200）"
        return out
    try:
        out["root"] = str((json.loads(body.decode("utf-8")) or {}).get("root") or "")
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"应答解不成 JSON：{type(exc).__name__}"
        return out
    if out["root"] != want:
        out.update(state="mismatch",
                   reason=f"答话的是 {out['root'] or '（空）'}，不是这一趟的 {want}")
        return out
    out.update(state="ok", reason="端口自证通过")
    return out


def serve(root: str | Path, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          token: str = "", allow_writes: bool = False, settings_write: bool = True,
          static_root: str | Path | None = None,
          csrf_token: str = "",
          routes_table: Sequence[tuple[str, str, str]] | None = None,
          heartbeat_sec: float = DEFAULT_HEARTBEAT_SEC,
          sid: str = "") -> ThreadingHTTPServer:
    """建好服务器并返回（不调 `serve_forever`）。

    测试用 `port=0` 起随机端口：返回后读 `srv.server_address[1]` 拿真实端口，
    在 `finally` 里 `srv.shutdown()` + `srv.server_close()`。

    `allow_writes` / `settings_write` 是两个真的改变行为的开关（裁定 C2 / E1）：
    挂到句柄上（`handler.allow_writes`），由 `writes.authorize()` 当第 3 / 第 4 层判。
    `static_root` / `csrf_token` 也是可注入的：判据要在临时目录里造一份前端外壳，
    并按需钉住令牌（缺省 = 每进程一个随机值）。

    `sid`（2026-11-14）：命令行 `start --watch` 自己定的那一段会话号，挂到句柄上
    （`handler.sid`）。它让 `/api/state` 的 `current.sid` / `current.round` 与
    `--watch` 印出来的两个数逐字同源 —— 不给就是"没人交代"，快照退回最近一段会话
    并在 `current.source` 里说明（不是假装知道）。SSE 的 `state` 帧也取同一个号
    （`sse.set_serving_sid`），否则"页面上刷新一下"与"流里推进来"会给出两个不同的当前会话。

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
    # 这一代是不是本函数开的：开了才由它接钩子，也才由它在 `server_close()` 时撤掉。
    # 撤钩子若只在 `run()` 里做，直接调 `serve()` 的判据
    # 会把 `sse.attach()` 装的四个钩子留在这个进程里 ⇒ 后面任何用例的
    # `sessions.append` 都走"发 SSE 事件"那条路，`observed_events()` 的计数不再增长，
    # `test_clock_governs_all_timed_work` 的 test_h / test_h3 / test_j 于是"单跑绿、
    # 跟缓存预热那一族一起跑就红"（二分实测：触发器是 test_cache_warm_button_is_honest.py）。
    owns_hooks = False
    if not sse.serving():
        sse.begin_serving(heartbeat_sec=heartbeat_sec)
        sse.attach()
        owns_hooks = True
    handler = type("BoundWebHandler", (WebHandler,), {
        "root": Path(str(root)), "token": token,
        "static_root": Path(str(static_root)) if static_root is not None
        else default_static_root(),
        "csrf_token": csrf_token or secrets.token_hex(16),
        "allow_writes": bool(allow_writes), "settings_write": bool(settings_write),
        "routes_table": tuple(routes_table) if routes_table is not None else (),
        # 「当前会话」：命令行交代的那一个（空串 = 没交代）。`/api/state` 与 SSE
        # 的 state 帧都读它，于是两处说的是同一段会话、同一个轮号。
        "sid": str(sid or ""),
    })
    # SSE 那一侧也要知道同一个号（广播帧没有 handler 可问）：同一代服务里只有一个
    # 当前会话，所以这条登记放在"这一代是谁开的"同一个位置。
    sse.set_serving_sid(str(sid or ""))
    # ---- 起之前先问一句"这个端口上是不是已经有东西在听"。
    # 为什么这一问不能省：Windows 的 SO_REUSEADDR 让第二个 bind 静默成功，于是下面那句
    # `ThreadingHTTPServer(...)` 不报错、URL 照打、请求却永远进不来。`port=0` 不探
    # （那是"让系统挑"，不构成撞车）。
    owner: dict[str, Any] = {"checked": False, "state": "port_zero", "root": "", "pid": 0,
                             "reason": "port=0：由系统挑空端口，不探测"}
    if int(port):
        owner = port_owner(host, int(port), token=token)
        if owner.get("state") == "busy":
            # 只有"明确有人服务"才拒；`unknown`（TIME_WAIT / 判不了）放行，
            # 由 `run()` 的自证把"在服务的是不是这一趟"钉死。
            who = owner.get("root") or "（占位者没回话/读不出工作区）"
            raise WebStartupError(
                f"{host}:{port} 已经被占用（占位者工作区：{who}）⇒ 不绑。"
                f"换 --port 0 让系统挑空端口，或先 `python -B temp/_web.py who --port {port}` "
                f"看清是谁、`taskkill /PID <pid> /T /F` 收掉它", owner=owner)
    srv = None
    try:
        srv = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        # 探测说"空着"、但绑的那一刻被抢了（竞态）：照旧不许静默，翻成同一条受控拒绝。
        raise WebStartupError(
            f"{host}:{port} 绑不上：{type(exc).__name__}: {exc} ⇒ 不绑。"
            f"换 --port 0 让系统挑空端口", owner=owner) from exc
    srv.daemon_threads = True
    if owns_hooks:
        # 谁开的谁撤：`server_close()` 是"这个服务器没了"的唯一时刻，钩子在那时撤掉，
        # 于是直接调 `serve()` 再 `server_close()` 的判据不会把这个进程的写路径带坏。
        _orig_close = srv.server_close

        def _close_and_detach() -> None:
            try:
                sse.close_all()
            finally:
                try:
                    sse.detach()
                finally:
                    _orig_close()

        srv.server_close = _close_and_detach  # type: ignore[method-assign]
    # 探测的读数挂上去：`run()` 的自证与判据都要读它（"探过没有"这件事必须看得见）
    srv.startup_probe = owner
    return srv


#: 端口登记文件名（放在工作区根下，跟 `budget.json` 一类同层）。
#:
#: 为什么要有它：每次起服务都让系统挑一个随机端口（`--port 0`）时，"开网页"这件事
#: 每次都是四步 —— 挑端口、起进程、从输出里抓 URL、把 URL 抄给人；重启一次 URL 就变，
#: 上一份链接立刻失效。业主说的是"为什么开网页还是那么累？优化"。
#: 记下端口只是第一步，真正省事的是 `ensure_serving` 的复用：同一个工作区第二次起服务时
#: 直接回"已经在服务它，地址就是这个"，不再起第二个进程。
PORT_FILE_NAME = "webui.json"


def recorded_port(root: str | Path) -> int | None:
    """这个工作区上一次记下的端口；没记过 / 读不成 ⇒ None（三态，不是 0）。"""
    path = Path(str(root)) / PORT_FILE_NAME
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 没有 / 坏掉都是"没读到"
        return None
    try:
        port = int(got.get("port") or 0)
    except (TypeError, ValueError):
        return None
    return port or None


def write_port_file(root: str | Path, port: int, url: str = "") -> str:
    """把这次用的端口记下来（写不成只返回原因，不拖垮服务）。"""
    path = Path(str(root)) / PORT_FILE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": int(port), "url": str(url),
                                    "pid": os.getpid(),
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                   ensure_ascii=False, default=str, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def free_port_near(host: str, start: int, *, span: int = 40) -> int:
    """从 `start` 起找一个真能绑的空端口；找不到 ⇒ 0（让系统挑）。

    用裸 bind 判空，不用"连一下看有没有人听"：Windows 上连一个没人听的端口是
    超时而不是立刻拒绝（秒级），而且是 `SO_REUSEADDR` 让双绑静默成功的同一个坑
    （判据 `tests/test_webui_startup_is_not_silent.py` 记着这两条）。
    """
    import socket

    for port in range(int(start), int(start) + max(1, int(span))):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        return port
    return 0


def ensure_serving(root: str | Path, *, host: str = DEFAULT_HOST,
                   port: int = 0, token: str = "") -> dict[str, Any]:
    """这一趟该"复用已在跑的那一个"还是"起一个新的"（只有这一处判）。

    返回 `{"action": "reuse"|"start", "port": N, "url": ..., "why": ...}`。

    判据三条：
    - 给了显式端口 ⇒ `start`（调用方指名要哪个，不去猜它的意图）；
    - 没给 ⇒ 读登记端口：那个端口上服务的就是这个工作区（`verify_serving` 三态里的
      `ok`）⇒ `reuse`，不再起第二个；
    - 登记端口被别的程序占着 / 服务的是别的工作区 ⇒ 从它往上找一个空端口再 `start`
      （找不到就交回 0 让系统挑）。

    `token` 是这一趟的口令（E1）：口令档下"复用"那一问必须带它，否则登记端口上
    真在服务的自己人也会被 401 读成"不是我"，于是每次开网页都白起第二个进程。
    """
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if int(port):
        return {"action": "start", "port": int(port),
                "url": f"http://{shown}:{int(port)}/", "why": "显式给了端口"}
    remembered = recorded_port(root)
    if remembered:
        url = f"http://{shown}:{remembered}/"
        got = verify_serving(url, root=root, token=token)
        if got.get("state") == "ok":
            return {"action": "reuse", "port": remembered, "url": url,
                    "why": "这个端口上服务的正是这个工作区（登记在 webui.json）"}
        owner = port_owner(host, remembered, token=token)
        if owner.get("state") == "busy":
            alt = free_port_near(host, remembered + 1)
            return {"action": "start", "port": alt,
                    "url": (f"http://{shown}:{alt}/" if alt else ""),
                    "why": (f"{remembered} 被占（工作区：{owner.get('root') or '读不出'}）"
                            f"⇒ 换 {alt or '系统挑'}")}
        return {"action": "start", "port": remembered, "url": url,
                "why": "登记端口现在空着，继续用它"}
    return {"action": "start", "port": int(DEFAULT_PORT),
            "url": f"http://{shown}:{int(DEFAULT_PORT)}/", "why": "第一次开（没有登记）"}


def run(argv: Sequence[str] | None = None) -> int:
    """命令行入口：起服务；`--json` 只打印一行 `{"url": ...}` 便于后台任务取 URL。

    为什么叫 `run` 而不是 `main`：`cli.py` 里已经有一个公开的 `main`（整套 CLI 的
    唯一入口），同名两份独立实现是本项目 R003 点名的形态。`cli.py` 那边加
    `agentflow web` 子命令时调本函数（或直接调 :func:`serve`）。
    """
    from ..cli import DEFAULT_ROOT

    ap = argparse.ArgumentParser(
        prog="agentflow-webui",
        description=("agentflow 用户端：SPA 外壳（九个页面）+ 十个只读面 + 一趟详情与提交回答。"
                     "端点形态：`GET /api/stream` 是 SSE 流（连上就一直推，不是一击即返的"
                     " JSON；拿普通 GET 的读完即返断言去测它必超时）；其余 `/api/*` 是一次性"
                     " JSON。`--list-routes` 打印带 kind 的完整清单（分类真身见 "
                     "`webui/routes.py` 的 ROUTE_KINDS / route_kind）"))
    ap.add_argument("--root", default="", help="工作区根（不给就用 DEFAULT_ROOT）")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    # 缺省 None = "调用方没给"（不是"给了 DEFAULT_PORT"）：`ensure_serving` 要靠这个
    # 区分"按登记端口复用/新起"与"你指名要这个端口"。缺省若写成 DEFAULT_PORT，
    # "没给"就会被读成"给了 8788" ⇒ 复用那一路永远走不到（实测）。
    ap.add_argument("--port", type=int, default=None,
                    help=f"监听端口（缺省：用 webui.json 记下的那个，没有就用 "
                         f"{DEFAULT_PORT}；给 0 让系统挑，且不登记）")
    ap.add_argument("--token", default="", help="共享口令（也可用 AGENTFLOW_WEB_TOKEN）")
    ap.add_argument("--open", action="store_true", help="起好之后用浏览器打开首页")
    ap.add_argument("--json", action="store_true",
                    help="只打印一行 URL 的 JSON（便于起后台任务后拿到确切 URL）")
    # 裁定 T1 的两个开关。它们真的改变行为（`writes.authorize()` 的第 3 / 第 4 层）：
    # 不给 `--allow-writes` ⇒ 写面只读，`/api/*` 下那六条写端点与 `/answer` 一律 403，
    # 而且这一档一个字节都不往工作区写（连审计台账也不写）。这一格曾经写成
    # "七条一律 403"—— 与实现相反：`POST /api/cache/warm` 的「试算」档（`dry_run=1`）
    # 只走回环那一层、不写盘不花钱，只读档照样回 200（真跑仍要 `--allow-writes`）。
    # AUDIT F6 修的是这句文案（不是行为 —— 试算本来就不该写盘）。
    ap.add_argument("--allow-writes", action="store_true",
                    help=("允许写面（缺省只读：不给 ⇒ /api/ 下六条写端点与 /answer 一律 403，"
                          "且只读档不往工作区写任何文件；`POST /api/cache/warm` 的试算档"
                          " dry_run=1 例外 —— 它只要求同源、不写盘不花钱，所以只读档也回 200，"
                          "真跑才要本开关）"))
    ap.add_argument("--no-settings-write", action="store_true",
                    help="关掉设置写面（只关 POST /api/settings：那条 403，其余写端点照旧）")
    # 端点形态的分类真身在 `routes.ROUTE_KINDS` / `routes.route_kind()`：`stream` 与
    # `json` 是两种连接生命周期，不是一个字段的两种取值 —— 拿普通 GET 的
    # "读完即返"断言去测 `/api/stream` 必超时。`--list-routes` 把这份分类印出来，
    # 于是清单、判据与帮助文本读的是同一处，不会各自维护一份"哪些是流"的名单。
    ap.add_argument("--list-routes", action="store_true",
                    help="打印端点清单（method / path / handler / kind）后退出；"
                         "kind=stream 的那条是 SSE 流，不能用读完即返的 GET 断言测")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.list_routes:
        for row in routes.endpoint_inventory():
            print(f"{row['method']:<5} {row['path']:<30} {row['kind']:<7} {row['handler']}")
        return 0
    root = Path(args.root).resolve() if args.root else Path(DEFAULT_ROOT).resolve()
    token = args.token or os.environ.get("AGENTFLOW_WEB_TOKEN", "")
    # ---- 先算"复用还是新起"（业主：为什么开网页还是那么累）。
    # `--port 0` 是显式的"让系统挑"，不复用也不登记；其余情况交给
    # `ensure_serving` 一处判（三条判据写在它的 docstring 里）。
    explicit_port = args.port is not None
    if explicit_port:
        plan = {"action": "start", "port": int(args.port), "url": "",
                "why": "显式给了端口"}
    else:
        plan = ensure_serving(root, host=args.host, token=token)
    if plan.get("action") == "reuse":
            url_now = str(plan.get("url") or "")
            if args.json:
                print(json.dumps({"url": url_now, "root": str(root),
                                  "reused": True}, ensure_ascii=False, default=str),
                      flush=True)
            else:
                print(f"agentflow 用户端（已在跑，复用）：{url_now}", flush=True)
                print(f"工作区根：{root}", flush=True)
            if args.open:
                try:
                    webbrowser.open(url_now)
                except Exception:  # noqa: BLE001 —— 打不开浏览器不该改变结论
                    pass
            return 0
    try:
        srv = serve(root, host=args.host, port=int(plan.get("port") or 0),
                    token=token, allow_writes=args.allow_writes,
                    settings_write=not args.no_settings_write)
    except WebStartupError as exc:
        # 起不来就说出来（非零退出 + 一行人话）。否则这一支会把"绑上、打印 URL、空转"
        # 当成成功：真机一次是端口上挂着两小时前的尸体，一次是 Windows 的双绑静默成功。
        sys.stderr.write(f"[webui] 起不来：{exc}\n")
        sys.stderr.flush()
        return 1
    host, port = srv.server_address[0], srv.server_address[1]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    # 端口只在自证通过之后才记下来：若在打印 URL 之前记，一次失败的启动（自证没过、
    # 退出 1）也会把那个端口写进 `webui.json`，下一次"开网页"就照着一个死地址去绑。
    # 记录跟着"真的在服务"走。
    def _remember_port() -> None:
        if explicit_port or not int(port):
            return
        problem = write_port_file(root, int(port), url)
        if problem and not args.json:
            print(f"[webui] 端口没记下来（下次还得重新挑）：{problem}", flush=True)
    # `flush=True` 是「必须」的，不是洁癖：这两行之后进程就进 `serve_forever()` 永不返回，
    # 而 stdout 被管道/文件接走时是「块缓冲」（8 KB 才吐一次）⇒ 起后台任务的人
    # 永远等不到那一行 URL。实测撞到：`python -B -m agentflow.webui --port 0 --json`
    # 在后台跑了很久，输出里一个字都没有（URL 就卡在缓冲区里）。
    # 而 `--json` 这个开关存在的唯一目的就是"让调用方立刻拿到确切 URL"。
    if args.json:
        print(json.dumps({"url": url, "root": str(root)}, ensure_ascii=False, default=str), flush=True)
    else:
        print(f"agentflow 用户端：{url}", flush=True)
        print(f"工作区根：{root}", flush=True)
        print("Ctrl-C 停止。", flush=True)
        if args.allow_writes or args.no_settings_write:
            # 这句曾说"只做到解析与透传，现在不改变任何行为"—— 与
            # `writes.authorize()` 的实现相反。现在照实说这一趟的写面是哪一档。
            print("（写面：" + ("已开 --allow-writes" if args.allow_writes
                              else "只读（没开 --allow-writes）：/api/ 下六条写端点与 /answer "
                                   "一律 403，只读档不往工作区写任何文件；"
                                   "`/api/cache/warm` 的试算档（dry_run=1）例外："
                                   "只要同源、不写盘不花钱 ⇒ 200")
                  + "；设置写面：" + ("关（--no-settings-write）"
                                     if args.no_settings_write else "开") + "）", flush=True)
    if args.open:
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001 - 打不开浏览器不该拖垮服务
            sys.stderr.write(f"[webui] 打不开浏览器：{type(exc).__name__}: {exc}\n")
    # ---- 绑完自证：在服务的必须是"这一趟"，不是端口上原来那个。
    # 为什么不能省：Windows 的 SO_REUSEADDR 让第二个 bind 静默成功（这次的现场），于是
    # "URL 打出来了"与"请求真的进这个进程"是两件事。打法：起服务之后从这个进程往自己
    # 端口打一次 `/api/state`，`root` 对不上就不再假装在服务（`verify_serving` 三态）。
    # 放进后台线程而不是挡住主线程：`serve_forever()` 必须在主线程上跑（Ctrl-C 才走得通），
    # 而自证要等 accept 循环起来才有意义。
    self_check: dict[str, Any] = {}

    def _self_check() -> None:
        from .. import clock as _CLK

        deadline = time.monotonic() + 8.0
        got: dict[str, Any] = {}
        while time.monotonic() < deadline:
            got = verify_serving(url, root=root, token=token)
            if got.get("state") == "ok":
                break
            # 等一等再试：这里不许裸 `time.sleep` —— 判据 `test_clock_governs_all_timed_work`
            # 的普查扫全树、零例外；框架里"等一会儿"只有 `clock.await_io` 一个入口，
            # 它把 purpose / kind / where 三样记进同一本等待账。
            _CLK.await_io(0.25, "网页绑完自证：等 accept 循环起来再打一次",
                          kind="poll", where="webui.server.run._self_check")
        self_check.update(got or {"state": "unknown", "reason": "自证没跑完"})
        if got.get("state") != "ok":
            sys.stderr.write(f"[webui] 绑完了但自证没过：{got.get('reason')} ⇒ 停止服务并退出 1\n")
            sys.stderr.flush()
            srv.shutdown()

    def _self_check_with_context() -> None:
        # 判据 `test_g8_a_program_belongs_to_the_run::test_d` 要求每一处起线程都带
        # 执行上下文（抄一份当时的）：这里起的是服务侧自证探针，不带也对，但那条
        # 判据是"扫落点"的 —— 按同一条纪律抄一份，不给它留豁免。
        from contextvars import copy_context

        copy_context().run(_self_check)

    threading.Thread(target=_self_check_with_context, name="webui-self-check",
                     daemon=True).start()
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
    if self_check and str(self_check.get("state") or "") != "ok":
        return 1
    # 走到这里 = 自证过了（或没跑），端口这才算数。
    _remember_port()
    if args.json:
        # 第二行：给"读到 URL 之后再确认一次"的调用方（第一行必须先打，launcher 要拿它）。
        print(json.dumps({"verified": True, "url": url, "root": str(root)},
                         ensure_ascii=False, default=str), flush=True)
    return 0


