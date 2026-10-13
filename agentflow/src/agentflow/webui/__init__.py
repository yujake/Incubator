# -*- coding: utf-8 -*-
"""用户端 Web 界面（包）：本地小服务 + 六个只读面 + 一支 SPA 外壳（只读投影 + 一个写回答的入口）。

## 这是什么

一个标准库级别的小服务（`http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把工作区盘上的东西发给两类消费者：

- 人：`ui/` 那份 SPA —— `GET /`、`GET /run/{sid}` 与"未知路径、但客户端要 HTML"的
  回退三条路都吐同一支外壳（`web/static/index.html`，注入了本进程的 CSRF 令牌）；
- 机器：`/api/*` 那一族只读 JSON 与 `POST /answer`（读模型与判据都读它们）。

外壳里没有任何盘上数据（它是一支静态页 + 一个挂载点），六个页面的读数一律现读现取：

- 「全局待回答面板」 —— 谁在问、问了多久、问了什么、有哪些选项，以及就地提交回答；
- 「运行态」 —— 每一趟（按会话号分组）的角色、步数、停止理由、花销、是否停在等谁；
- 「一趟详情」 —— 一趟的读数 + 交付说明 `out/review/REPORT.md` 的原文。

`GET /api/state` 给出与面板同一批读数的 JSON（前端读模型与判据都读它）。

## 为什么需要它（不是"CLI 不好用"）

CLI 够用，但「有一趟正停在等你回答」这件事在终端里只有你恰好打开那个终端才看得见。
我们在 `docs/USER-END-DSH-STYLE.md` §3 抄了 DSH 的界面纪律（状态不进组件 state、
卡片渲染已落盘的切片、全局面板），而其中「全局可达」这一条在「我们自己的结构」里
同样成立：`DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」⇒ 人需要一个不挑会话的
入口，因为提问正阻塞着某一趟、而那一趟可能不在人当前看的地方。
所以 `GET /` 的待答面板「从不按会话过滤」。

## 包里的分工（裁定 R1：W0 一次拆到位）

| 文件 | 职责 |
|---|---|
| `state.py` | 读模型：`snapshot()` 与它的内部件（语义与拆包前一字不改） |
| `readers.py` | 十个只读面的读模型与端点（`/api/state` 起，各带三态头；2026-10-12 加了预算 / 在飞 / 用量 / 状态报告四条） |
| `sse.py` | `GET /api/stream` 的广播器 + 写路径钩子（`attach`/`detach`） |
| `writes.py` | 写路径：`answer()`（提交回答，走 `userio.answer_question`）与它的写面 |
| `routes.py` | 路由表 `ROUTES`：`(method, path 模式, 处理器方法名)` |
| `server.py` | `WebHandler` / `serve()` / `run()` + 静态路由 + SPA 外壳 + 错误页 |

旧壳 `views.py` 已整件退场（裁定 P1 的最后一块，W5 清仓）：`/` 于 2026-10-07 先迁，
`/run/{sid}` 随后也改成吐同一支外壳（九页面全部由 SPA 提供），于是那个文件里
九个函数一个都不剩 —— 服务器自己还写 HTML 的地方只剩 `server._error_page`
（外壳不在盘上 / 静态未命中 / 写失败这三类诚实错误页）。

## 公开面（拆包时八个名字，W5 收窄到六个）

`snapshot` · `serve` · `run` · `WebHandler` · `answer_text_of` · `option_view` ——
见下面的 `__all__`；`cli.py` 用的就是这几个名字。

这次收窄去掉的是 `render_root` 与 `render_run`（W5 清仓的必然结果，不是"改宽判据"）：
它们是旧壳的两个渲染入口，随 `/` 与 `/run/{sid}` 两面迁到 SPA 而失去全部调用方
（`server.py` 不再读，`ui/` 也不读 —— 前端的页面在 TS 里）。判据那两处改动
（`tests/test_webui_contracts.py` 的公开面清单、`tests/test_webui.py` 里读旧壳 HTML
的那几条）在 W5 报告里逐条写明了"原来断言什么、现在断言什么、为什么是同一件事"。

## 三条纪律（两条抄的是 DSH 的界面纪律，一条是本项目结构决定的）

1. 「状态一律从盘上派生」（抄自 DSH）：每次请求都重新读会话文件、台账、报告，
   页面里不缓存、不做后台轮询线程。读一次快照抽成纯函数 :func:`snapshot`，
   同一份盘上数据读两次得到逐字节相同的 JSON（取钟那一处例外：判据会把它钉住）。
2. 「每个事实行给两个独立读数」（抄自 DSH）：例如运行态行同时给「盘上最后一条事件
   是什么」与「这一页读到了多少条事件」；读不到的东西写 `unknown` / `没查成`
   （本项目自己的三态纪律，`DESIGN-INTERACTIONS.md` §3.4），绝不折成 0 或空。
3. 「回答的文本两种口径都认」（本项目自己的兼容要求）：见 :func:`answer_text_of`。

## 安全与失败姿态

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`）；
- 服务器自己写的最后一页是 `server._error_page`（只有错误页），它把理由串转义后才
  写进 HTML；盘上的文本一律走 JSON（负控在 `tests/test_webui.py`：一条钉服务端那条
  转义路径，一条钉前端源码里没有把字符串当 HTML 用的写法）；
- 写失败不许折成 200（`POST /answer` 的三态在 `writes.py` 里）；
- 静态路由只服务静态根之下的真实文件，目录穿越一律拒（负控在
  `tests/test_webui_contracts.py`）。

## 设计依据与判据

设计依据：`docs/USER-END-DSH-STYLE.md`（§1 抄了什么、§2 令牌体系、§3 界面纪律、
§4 三处刻意差异）。判据：`tests/test_webui.py`（正控与负控各若干条）与
`tests/test_webui_contracts.py`（契约 A–D 四条 + 静态路由/生成物新鲜度）。
「组件样式只用 `--dsw-alias-*` / `--ds-*` 令牌」这条判据今天查的是前端源码
`ui/src/theme/app.css`（`tests/test_webui.py::test_app_css_uses_only_tokens`）——
旧壳内联的那份组件样式随 `views.py` 一起退场了。
"""

from __future__ import annotations

from .routes import ROUTES
from .server import (DEFAULT_HOST, DEFAULT_PORT, WebHandler, _STOP_BADGES, run,
                     serve)
from .state import CLIP, REPORT_REL, _now_iso, answer_text_of, option_view, snapshot

__all__ = ["snapshot", "serve", "run", "WebHandler",
           "answer_text_of", "option_view"]

# 说明：`CLIP` / `REPORT_REL` / `DEFAULT_HOST` / `DEFAULT_PORT` / `ROUTES` /
# `_now_iso` / `_STOP_BADGES` 也在包的命名空间里（不在 `__all__` 里）—— 它们是
# 既有调用方与判据直接读的名字（`tests/test_webui.py` 读 `REPORT_REL` 与
# `_now_iso`，`tests/test_loop_liveness.py` 读 `_STOP_BADGES`），拆包不该把它们
# 从 `agentflow.webui` 上拿走：拿走了判据会以 `AttributeError` 的形态红，
# 而那种红说不清"是设计变了还是漏了"。
# `_STOP_BADGES` 的落点随旧壳退场搬到了 `server.py`（那里写着为什么它还在）——
# `agentflow.webui._STOP_BADGES` 这个读法本身没变。
