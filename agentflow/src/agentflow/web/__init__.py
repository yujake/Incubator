# -*- coding: utf-8 -*-
"""用户端 Web 界面的落点（本地小服务 + 服务端渲染）。

## 这是什么、为什么单独一个包

`agentflow` 的用户端此前只有 CLI（`agentflow.cli`）与人机频道（`agentflow.userio`）。
CLI 够用，但「有一趟正停在等你回答」这件事，在终端里只有你恰好打开那个终端才看得见；
而 `DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」意味着人需要一个「不挑会话」的入口
（提问正阻塞着某一趟，那一趟可能不在人当前看的地方）。

所以这一层只做两件事，且都不引入任何依赖：

- :mod:`agentflow.webui` —— 标准库 `http.server` 上的只读投影 + 一个写回答的入口；
- :mod:`agentflow.web.assets` —— DSH 的令牌与控制台样式（照搬，MIT；我们自己的组件）。

## 设计依据与判据

设计依据：`docs/USER-END-DSH-STYLE.md`（§2 令牌体系 = 抄的皮；§3 界面纪律 = 抄的界面纪律
＋ 我们自己的结构推论；§4 我们的运行时协作纪律；§6 三处刻意差异）。
判据：`tests/test_webui.py`（正控与负控都有）。

## 为什么不是「一个前端工程」

DSH 的前端是 React 组件树；我们抄的是它那几条「界面」纪律（状态不进组件 state、
卡片回放已落盘的切片、行里给两个独立读数），不是它的构建链。零客户端 JS、
零 CDN、零 npm：页面每次请求都从盘上重新派生，因此「刷新即最新」，
也就没有缓存与失效这套东西要维护。
"""

from __future__ import annotations

__all__ = ["assets"]
