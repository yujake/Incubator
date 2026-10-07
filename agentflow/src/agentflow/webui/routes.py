# -*- coding: utf-8 -*-
"""路由表：把 `do_GET` / `do_POST` 里的 `if path == …` 链换成一张可读的表。

## 为什么要有这张表

三条理由，一条比一条硬：

1. 一屏能看全"这个服务有哪些端点"，而 if 链只能靠通读；
2. 前端 `ui/src/api.ts` 的端点集合要与后端逐字对齐 —— 有一张表才能机械地比
   （`tests/test_webui_contracts.py` 的 A 条就是拿 `ROUTES` 当后端那一侧）；
3. 表的每一行都必须说清"谁实现它"：第三个元素是 :class:`agentflow.webui.server.WebHandler`
   上的方法名。写错名字在第一次请求时就炸（表驱动没有"漏网"的中间态）。

## 表怎么读

每条是 `(method, path 模式, 处理器方法名)`：

- 模式里的 `{name}` 匹配一段路径（`/run/{sid}` 不匹配 `/run/a/b`）；
- 末尾写成 `{name...}` 的那个匹配剩下整段（可以含 `/`）—— 静态资源要用它，
  因为 `assets/app.<hash>.css` 是两段；
- 未知路径不由这里处理：`GET` 走 :func:`agentflow.webui.server.WebHandler.handle_unknown`
  （裁定 Q1：`/api/*` 未知 ⇒ JSON 404；其余未知 ⇒ 有 `index.html` 就吐它，
  否则沿用今天的 404 页），`POST` 未知 ⇒ 404。

## 这张表由三段拼起来（`draft/78 §3` 的接缝）

:data:`ROUTES` 是 `_OWN`（A 线自有）＋ `readers.ROUTES`（B 线的只读面）＋
`writes.ROUTES`（C 线的写面）。三条零交线各自往自己的子表里加端点，本文件不必被
别人碰 —— 反过来，本文件里也不许再出现"别人的端点"。

## 本批（W0）的表

A 线自有五条（`/`、`/index.html`、`/run/{sid}`、`/api/state`、`/static/{file...}`）
＋ C 线的一条既有写路径（`POST /answer`，W0 就由 `writes.ROUTES` 提供）。
`draft/75 §1.1` 的 C1 表里另外那些（`/api/run/{sid}` 的 JSON 形态、`/api/evidence`、
`/api/artifacts`、`/api/acceptance`、`/api/machine`、`/api/stop`、`/api/submit`、
`/api/settings`、`/api/stream`）分别在 W1/W2/W3 由各自那一行落地 —— 它们不在这张表里，
因为"前端声明了而后端没有"正是 A 条要抓的漂移（反过来也一样：这一张表里有的，
`api.ts` 就必须有）。
"""

from __future__ import annotations

import re
from typing import Sequence

from .readers import ROUTES as READER_ROUTES
from .writes import ROUTES as WRITE_ROUTES

__all__ = ["ROUTES", "compose", "handler_for", "match"]


def compose(own: Sequence[tuple[str, str, str]],
            reader: Sequence[tuple[str, str, str]],
            write: Sequence[tuple[str, str, str]]) -> tuple[tuple[str, str, str], ...]:
    """把三段子表拼成总表（与导入期用的同一条公式）。

    为什么把它写成一个函数：判据要证明"子表真的被拼进去了"，而不是只在导入的那一刻
    拼过一次、之后谁把子表换掉都没人知道。有了它，判据可以喂一份"多了一条端点的
    子表"给同一条公式，看 A 条是否当场红。
    """
    return tuple(own) + tuple(reader) + tuple(write)


#: 子表模块放 handler 的约定名字：`HANDLERS: dict[str, Callable]`，键 = 路由表第三元素。
#: 为什么要有这条接缝：`routes.py` 的第三元素是"`WebHandler` 上的方法名"，而 B/C 两条线
#: 不许改 A 线的 `server.py` —— 没有这条约定，它们就只能往 `WebHandler` 上猴补丁
#: （`setattr(WebHandler, ...)`），那会让"谁实现了哪个端点"从源码里看不出来。
#: 有了它：B/C 在自己的模块里写 `HANDLERS = {"handle_evidence": _handle_evidence}`，
#: 签名 `(handler, params, query)`，`handler` 就是那个 `WebHandler` 实例。
_SUBTABLE_MODULES = ("readers", "sse", "writes")


def handler_for(name: str):
    """按名字找子表模块里的 handler（A 线自己的方法由 `server.py` 先用 `getattr` 找）。

    刻意在这里才 import 那三个模块：它们导入期就要 `from .routes import ...`，
    模块级互相导入会成环；调用期导入既安全又便宜（模块已缓存）。
    """
    from . import readers, sse, writes  # noqa: PLC0415 - 见上：避免导入期成环

    for mod in (readers, sse, writes):
        table = getattr(mod, "HANDLERS", None) or {}
        fn = table.get(name)
        if fn is not None:
            return fn
    return None


#: A 线（自有：页面 + 静态资源）那一段子表。
#:
#: 注意 `("GET", "/api/state", ...)` 不在这里：所有者裁定 2b 把那条路由迁到了
#: `readers.ROUTES`（B 线），A 线原来的 `WebHandler.handle_state` 也一并删掉 ——
#: 于是"哪条线上的模块声明这条路由"与"谁实现它"落在同一个文件里（`readers.py`），
#: 而公开面不变：`readers.handle_state` 回的就是 `state.snapshot(root)` 本身。
_OWN: tuple[tuple[str, str, str], ...] = (
    # --- 页面（服务端渲染的旧壳；裁定 P1：逐面迁到 SPA 之后删一个）
    ("GET", "/", "handle_root"),
    ("GET", "/index.html", "handle_root"),
    ("GET", "/run/{sid}", "handle_run"),
    # --- 静态资源（前端构建产物：裁定 B1 的落点）
    ("GET", "/static/{file...}", "handle_static"),
)

#: 总表 = 自有 + 只读面（B 线的 `readers.ROUTES`）+ 写面（C 线的 `writes.ROUTES`）。
#: 这条接缝是 `draft/78 §3` 的三条之一：三条零交线各自往自己的子表里加端点，
#: 于是"加一条路由"永远不会变成"两条线改同一个文件"。
#: 拼接发生在导入期，所以子表必须在导入期就存在（空元组也算存在）。
ROUTES: tuple[tuple[str, str, str], ...] = compose(_OWN, READER_ROUTES, WRITE_ROUTES)

#: `{name}` 与末尾的 `{name...}`（后者吃掉剩余路径，可含 `/`）。
_SEGMENT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_REST = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\.\.\.\}")


def _compile(pattern: str) -> re.Pattern[str]:
    """把一个模式编译成正则（模式里除占位符外的字符一律按字面量匹配）。"""
    rest = _REST.search(pattern)
    if rest is not None:
        head = re.escape(pattern[:rest.start()])
        return re.compile(head + f"(?P<{rest.group(1)}>.+)$")
    parts: list[str] = []
    pos = 0
    for m in _SEGMENT.finditer(pattern):
        parts.append(re.escape(pattern[pos:m.start()]))
        parts.append(f"(?P<{m.group(1)}>[^/]+)")
        pos = m.end()
    parts.append(re.escape(pattern[pos:]))
    return re.compile("".join(parts) + "$")


#: 编译一次、反复用（表是常量，编译结果也是）。
_COMPILED: tuple[tuple[str, str, re.Pattern[str], str], ...] = tuple(
    (method, pattern, _compile(pattern), handler)
    for method, pattern, handler in ROUTES
)


def match(method: str, path: str, *,
          table: Sequence[tuple[str, str, str]] | None = None) -> tuple[str, dict[str, str]] | None:
    """按 `(method, path)` 查表：命中返回 `(处理器方法名, 占位符取值)`，否则 `None`。

    `table=None` = 真表（用导入期编译好的 `_COMPILED`，快路径）；
    给了表就现场编译（判据与 `serve(routes_table=...)` 的可注入点要用它 ——
    这样"多一条端点的总表"能在不污染模块全局的前提下走一遍真实请求）。
    """
    rows = _COMPILED if table is None else tuple(
        (m, p, _compile(p), h) for m, p, h in table)
    for m, _pattern, rx, handler in rows:
        if m != method:
            continue
        hit = rx.match(path)
        if hit is not None:
            return handler, {k: v for k, v in hit.groupdict().items() if v is not None}
    return None


def patterns(method: str | None = None,
             table: Sequence[tuple[str, str, str]] | None = None) -> tuple[str, ...]:
    """表里的路径模式（给判据用；`method=None` 表示全部，`table=None` 表示真表）。"""
    rows = ROUTES if table is None else tuple(table)
    return tuple(p for m, p, _h in rows if method is None or m == method)


def api_paths(table: Sequence[tuple[str, str, str]] | None = None) -> tuple[str, ...]:
    """契约判据 A 比对的那一栏：`/api/*` 与 `/answer` 的路径模式。

    为什么把 `/`、`/run/{sid}`、`/static/{file...}` 排除在外：C1 那张端点表里
    只有 JSON 端点与写端点（`/api/*` 与 `/answer`），页面与静态前缀不是"端点"，
    它们是路由契约（C4）与静态路由那两条判据的地盘。这里是显式登记的口径，
    不是"找不到就算了"。

    `table` 可换（缺省 = 真表）：接缝那条负控要拿"多了一条子表的总表"喂给同一条
    比对逻辑，看它是否当场红。
    """
    return tuple(p for p in patterns(table=table)
                 if p.startswith("/api/") or p == "/answer")


def methods() -> tuple[str, ...]:
    """表里出现过的方法（排序去重）。"""
    return tuple(sorted({m for m, _p, _h in ROUTES}))


def handler_names() -> Sequence[str]:
    """表里登记的处理方法名（判据拿它断言"表里写的名字真的存在"）。"""
    return tuple(h for _m, _p, h in ROUTES)
