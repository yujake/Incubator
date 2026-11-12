# -*- coding: utf-8 -*-
"""用户端 Web 界面的落点（本地小服务 + 单页前端 SPA）。

## 这是什么、为什么单独一个包

`agentflow` 的用户端除了 CLI（`agentflow.cli`）与人机频道（`agentflow.userio`）之外
还需要一个「不挑会话」的入口：CLI 够用，但「有一趟正停在等你回答」这件事，在终端里
只有你恰好打开那个终端才看得见；而 `DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」
意味着人得能在一个地方看见所有在等他的提问（提问正阻塞着某一趟，那一趟可能不在人
当前看的地方）。

所以这一层分两件，且服务端不引入任何依赖：

- :mod:`agentflow.webui` —— 标准库 `http.server` 上的本地服务：只读面 + 写端点
  （`/answer` / `POST /api/stop` / `POST /api/submit` / `POST /api/settings` /
  `POST /api/budget`，默认只读）+ 一条 SSE 流；
- :mod:`agentflow.web.assets` —— DSH 的令牌层（照搬，MIT；我们自己的组件样式在
  前端工程里）。

## 设计依据与判据

设计依据：`docs/USER-END-DSH-STYLE.md`（§2 令牌体系 = 抄的皮；§3 界面纪律 = 抄的界面纪律
＋ 我们自己的结构推论；§4 我们的运行时协作纪律；§6 三处刻意差异）。
判据：`tests/test_webui.py`（正控与负控都有）。

## 前端在哪

前端是独立工程 `ui/`（Preact + Vite），构建产物落 `web/static/`；页面读数每次请求都
从盘上重新派生，因此「刷新即最新」，没有缓存与失效这套东西要维护。
"""

from __future__ import annotations

__all__ = ["assets"]
