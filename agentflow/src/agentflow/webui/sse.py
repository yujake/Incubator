# -*- coding: utf-8 -*-
"""服务端推送（SSE）的事件词表与广播器（`draft/73` §2.4 的本体；属于 B 线那一批）。

## 本批（W0）只安排接缝

`draft/78 §3` 的三条接缝里，这一条是"前端已经注册、后端还没发"的那种：
`ui/src/sse.ts` 的 `KINDS` 是本批就写好的（W0 的前端骨架），而它必须与后端的
:data:`EVENT_KINDS` 逐字相等 —— 判据
（`tests/test_webui_contracts.py` 的 B 条）拿这两个集合对比。

W0 这里是一个空词表：广播器、分帧、心跳、续传都在 W2。为什么先把文件建出来：
B 线接手时改的是自己这个文件，而不是去改 `routes.py` 或前端（前端那一半
已经在 W0 落地了）。空词表在判据里读作"后端还没填"，于是 B 条 skip 并写明理由，
绝不把"没查成"折成"查过了没问题"。

## W2 要在这里落什么（`draft/73` §2.4）

`format_event(*, kind, data, event_id)` · `Broadcaster.publish/subscribe/close_all` ·
`GET /api/stream` 的校验与补发 · 五条判据（content-type + no-store、首个事件 1 s 内、
心跳周期可注入、`?since=N` 补发、盘上新增事件 1 s 内进流）。
"""

from __future__ import annotations

__all__ = ["EVENT_KINDS", "HANDLERS", "PENDING_ENDPOINTS", "ROUTES"]

#: 后端会发的事件种类（C2 契约的后端一侧）。W0 是空的：广播器在 W2。
#: 填它的时候必须与 `ui/src/sse.ts` 的 `KINDS` 逐字相同，否则 B 条当场红。
EVENT_KINDS: tuple[str, ...] = ()

#: `GET /api/stream` 的落点（B 线在 W2 填）。`routes.compose` 只拼
#: `readers.ROUTES + writes.ROUTES` 两段子表 —— 所以 SSE 这条要么进
#: `readers.ROUTES`（同一个 B 线文件），要么由 A 线主控把它拼进总表；
#: 这里留 `ROUTES` 是给"SSE 自己一段子表"这个选项用的（见下条）。
ROUTES: tuple[tuple[str, str, str], ...] = ()

#: 处理器的落点（与 `readers.py`/`writes.py` 同一条约定）：键 = 处理器名字，
#: 值 = `(handler, params, query)` 签名的函数。`routes.handler_for()` 会来读它。
HANDLERS: dict[str, object] = {}

#: 契约判据 D 的例外面：本模块声明、但后端还没落地的端点（`{端点: 理由}`）。
#: `/api/stream` 现在挂在这里：前端 `api.ts` 已经声明它，后端要等 W2 ——
#: B 线落地 `GET /api/stream` 时，请把这一行删掉（判据有反向断言抓"永不生效的豁免"）。
PENDING_ENDPOINTS: dict[str, str] = {
    "/api/stream": "SSE 流端点在 W2 落地（`sse.ts` 先把订阅侧写好，判据 B 管词表对齐）",
}
