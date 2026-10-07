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

__all__ = ["EVENT_KINDS"]

#: 后端会发的事件种类（C2 契约的后端一侧）。W0 是空的：广播器在 W2。
#: 填它的时候必须与 `ui/src/sse.ts` 的 `KINDS` 逐字相同，否则 B 条当场红。
EVENT_KINDS: tuple[str, ...] = ()
