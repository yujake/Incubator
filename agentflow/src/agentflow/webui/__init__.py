# -*- coding: utf-8 -*-
"""用户端 Web 界面（包）：本地小服务 + 服务端渲染（只读投影 + 一个写回答的入口）。

## 这是什么

一个标准库级别的小服务（`http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把工作区盘上的三样东西渲染成人能读的页面：

- 「全局待回答面板」 —— 谁在问、问了多久、问了什么、有哪些选项，以及就地提交回答；
- 「运行态」 —— 每一趟（按会话号分组）的角色、步数、停止理由、花销、是否停在等谁；
- 「一趟详情」 —— 会话事件的可回放卡片 + 这一趟的交付说明 `out/review/REPORT.md`。

外加 `GET /api/state` 给出同一批读数的 JSON（前端读模型与判据都读它）。

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
| `views.py` | 旧的服务端渲染（裁定 P1：逐面迁到 SPA，迁完一面删一面） |
| `writes.py` | 写路径：今天只有 `answer()`（提交回答，走 `userio.answer_question`） |
| `routes.py` | 路由表 `ROUTES`：`(method, path 模式, 处理器方法名)` |
| `server.py` | `WebHandler` / `serve()` / `run()` + 静态路由 + SPA 回退 |

## 公开面（拆包前后不许变）

`snapshot` · `render_root` · `render_run` · `serve` · `run` · `WebHandler` ·
`answer_text_of` · `option_view` —— 见下面的 `__all__`；`cli.py` 与
`tests/test_webui.py` 用的就是这几个名字。

## 三条纪律（两条抄的是 DSH 的界面纪律，一条是本项目结构决定的）

1. 「状态一律从盘上派生」（抄自 DSH）：每次请求都重新读会话文件、台账、报告，
   页面里不缓存、不做后台轮询线程。读一次快照抽成纯函数 :func:`snapshot`，
   同一份盘上数据渲染两次得到逐字节相同的 HTML（取钟那一次例外：判据会把它钉住）。
2. 「每个事实行给两个独立读数」（抄自 DSH）：例如运行态行同时给「盘上最后一条事件
   是什么」与「这一页读到了多少条事件」；读不到的东西写 `unknown` / `没查成`
   （本项目自己的三态纪律，`DESIGN-INTERACTIONS.md` §3.4），绝不折成 0 或空。
3. 「回答的文本两种口径都认」（本项目自己的兼容要求）：见 :func:`answer_text_of`。

## 安全与失败姿态

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`）；
- 用户与模型产生的「一切文本都经 `html.escape` 转义后」才进 HTML（负控在
  `tests/test_webui.py`）；
- 写失败不许折成 200（`POST /answer` 的三态在 `writes.py` 里）；
- 静态路由只服务静态根之下的真实文件，目录穿越一律拒（负控在
  `tests/test_webui_contracts.py`）。

## 设计依据与判据

设计依据：`docs/USER-END-DSH-STYLE.md`（§1 抄了什么、§2 令牌体系、§3 界面纪律、
§4 三处刻意差异）。判据：`tests/test_webui.py`（正控与负控各若干条）与
`tests/test_webui_contracts.py`（契约 A–D 四条 + 静态路由/生成物新鲜度）。
`APP_CSS` 只用 `--dsw-alias-*` / `--ds-*` 令牌这条，由
`tests/test_webui.py::test_app_css_uses_only_tokens` 用正则机械地查。
"""

from __future__ import annotations

from .routes import ROUTES
from .server import DEFAULT_HOST, DEFAULT_PORT, WebHandler, run, serve
from .state import CLIP, REPORT_REL, _now_iso, answer_text_of, option_view, snapshot
from .views import _STOP_BADGES, render_root, render_run

__all__ = ["snapshot", "render_root", "render_run", "serve", "run", "WebHandler",
           "answer_text_of", "option_view"]

# 说明：`CLIP` / `REPORT_REL` / `DEFAULT_HOST` / `DEFAULT_PORT` / `ROUTES` /
# `_now_iso` / `_STOP_BADGES` 也在包的命名空间里（不在 `__all__` 里）—— 它们是
# 既有调用方与判据直接读的名字（`tests/test_webui.py` 读 `REPORT_REL` 与
# `_now_iso`，`tests/test_loop_liveness.py` 读 `_STOP_BADGES`），拆包不该把它们
# 从 `agentflow.webui` 上拿走：拿走了判据会以 `AttributeError` 的形态红，
# 而那种红说不清"是设计变了还是漏了"。
