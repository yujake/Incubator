# USER-GUIDE-WEB.md —— Web 侧用户说明书（逐条请求实跑）

> **这份文件只管网页那一侧**：怎么起服务、十个页面各读什么、写端点怎么打
> （**条数不写死在本文里**：唯一名单是 `webui/writes.py` 的 `ROUTES` 与
> `webui/readers.py` 的 `ROUTES`；2026-11-22 00:11 现算是**写面 12 条（POST 11 +
> GET 1 `/api/cache`）／读面 19 条**，现算命令与完整名单见 §3 开头）、
> 403/400/409 分别是什么意思、哪些事网页上还做不了。
> 命令行那一侧见 [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md)；`--json` 逐字段契约见
> [`CLI-CONTRACT.md`](CLI-CONTRACT.md)；哪份文档算数见 [`INDEX.md`](INDEX.md)
> （原先那份合并版 `USER-GUIDE.md` 已于 2026-11-22 归档到 `draft/archive-docs/`，见 `INDEX.md` §3.2）。
>
> **本文里的每一个状态码与响应片段都是临时实例上真发出来的**，两轮：
>
> - ① 2026-11-22 00:00（端口 8893 只读档 / 8895 可写档 / 8896 口令档 /
>   8700 自动挑端口那一档），工作区 `temp/userguide-web/ws`（真机项目
>   `projects/lp-ball-15` 的副本）；
> - ② 2026-11-22 00:11 **GUIDE-WEB-REFRESH 复核**（端口 8892 只读档 /
>   8893 可写档），新增的三条写端点（`/api/ack` · `/api/void` ·
>   `/api/stop/clear`）逐条实测，工作区 `temp/guideweb/ws`（上一份副本的副本，
>   六条 `block` 板项原样在盘上）。
>
> 真机工作区全程只读。逐请求清单在附录 A（新三条在 **A.7**），复跑脚本的名与用法在附录 B。
>
> 环境：Windows / Python 3.11.4 / `agentflow 1.0.0`（editable 装在本仓 `agentflow/`）。
> 本文**不写死**前端产物文件名与字节数（UI 一改就变）；要看现盘是哪一支，跑附录 B（§12）的第一条命令。

---

## 1. 起服务

### 1.1 两条命令（这是全部差别）

```powershell
# 只读档（缺省）
python -m agentflow --root <工作区> web --port 8893

# 可写档（能答问 / 插话 / 叫停 / 起跑 / 投放 / 改预算 / 改设置 / 预热缓存）
python -m agentflow --root <工作区> web --port 8893 --allow-writes
```

实跑（只读档，`--json` 让调用方立刻拿到确切 URL）：

```text
$ python -m agentflow --root D:\Incubator\agentflow\temp\userguide-web\ws web --port 8893 --json
{"url": "http://127.0.0.1:8893/", "root": "D:\\Incubator\\agentflow\\temp\\userguide-web\\ws"}
```

不给 `--json` 时是人话（可写档实跑，第一行是"当前用哪一档提示词缓存"的横幅）：

```text
$ python -m agentflow --root D:\Incubator\agentflow\temp\userguide-web\ws web --port 8899 --allow-writes
缓存：使用 非 Lean 版缓存（p315 · 11/12）
agentflow 用户端：http://127.0.0.1:8899/
工作区根：D:\Incubator\agentflow\temp\userguide-web\ws
Ctrl-C 停止。
（写面：已开 --allow-writes；设置写面：开）
```

最后那行只在"开了写面 或 关了设置写面"时才打 —— 只读档不打它。

`python -m agentflow.cli web …` 与 `python -m agentflow web …` 是同一个入口，两种写法都实跑过
（`web --help` 输出的 usage 行逐字相同）。

### 1.2 两档的差别只有一处，后果有一串

| | 只读档（缺省） | 可写档（`--allow-writes`） |
|---|---|---|
| 页面 | 十页全开 | 十页全开 |
| 读数端点（`/api/state`、`/api/live`、`/api/evidence` …） | 全开 | 全开 |
| 写端点（名单见 `webui/writes.py` 的 `ROUTES`，现 12 条：**POST 11 条** + 1 条只读的 `GET /api/cache`） | **一律 403 `writes_off`** | 放行（还要过来源与 CSRF，见 §4） |
| 缓存试算（`/api/cache/warm` + `dry_run=1`） | **200**（不写盘、不花钱、不起进程） | 200 |
| 往工作区写文件 | **一个字节都不写**（连审计台账 `web-actions.jsonl` 都不建） | 每一条到达写处理器的尝试追加一行 `web-actions.jsonl` |
| 页面怎么告诉你 | 顶栏与按钮 `title` 给 `writes_reason` | `writes_reason` 是空串 |

两档的读数（同一条 `/api/state`，只差这一格）：

```text
# 只读档 /api/state
"writes_allowed": false,
"writes_reason": "本服务未开 --allow-writes，写按钮不可用；重启时加该参数即可"

# 可写档 /api/state
"writes_allowed": true,
"writes_reason": ""
```

实跑证据（**2026-11-22 00:11 复核**，只读档 8892）：对新三条端点各打三种拒绝
（不带 CSRF / 跨站 `Origin` / 只读档）＝ **9 条写请求 ⇒ 9 条 403**
（`csrf_token`×3、`foreign_origin`×3、`writes_off`×3），另加 1 条未知端点探测 ⇒ 404。
全程工作区里 `web-actions.jsonl` **始终不存在**（`Test-Path` 为 False），
`.agentflow-stop` 也没被这次复核碰过。
换成可写档后打 21 条写请求（新三条的成功档 + 各种 400/409 + 一条叫停造开关）
→ 该文件出现：**21 条写请求 ⇔ 21 行台账**（附录 A.7 逐条对账）。

> 更早那一轮（2026-11-22 00:00，只读档 8893）打的是 14 条写请求 —— 13 条被拒
> （`403`×11、`404`×2）；那两条 404 就是当时还没落地的 `/api/ack` 与 `/api/stop/clear`。
> **现在它们都在 `ROUTES` 里了**：同一请求会回 403 `writes_off`（附录 A.3 的 #49/#50 已按新读数改注）。

### 1.3 端口：给、不给、给错了

| 你怎么给 | 会发生什么 | 实跑 |
|---|---|---|
| `--port 8893` | 就用它；被占 ⇒ **受控拒绝**（不绑、退出码非 0、告诉你是谁占着） | 见下 |
| `--port 0` | 让系统挑一个；**不登记**（`webui.json` 不写） | — |
| 不给 `--port` | 从 **8700** 起挑第一个能绑的；被占就换下一个并说明 | 实跑拿到 `http://127.0.0.1:8700/` |

端口被占时的原话（我把可写档错开到 8894，那里正躺着另一个临时实例）：

```text
[webui] 起不来：127.0.0.1:8894 已经被占用（占位者工作区：…\temp\webfix3\ws）⇒ 不绑。
        换 --port 0 让系统挑空端口，或先 `python -B temp/_web.py who --port 8894` 看清是谁、`taskkill /PID <pid> /T /F` 收掉它
[web] 8894 被占（占位者工作区：…\temp\webfix3\ws）⇒ 换一个号：--port 8895，或不给 --port 让它从 8700 起自动挑。
```

**这一档不会"静默双绑"**：它退出并把占位者的工作区告诉你。所以"网页打不开"第一件要看的
不是浏览器，是这行 stderr。

### 1.4 工作区根：`--root` 在 `web` 之前，而且启动那一刻就钉死

`--root` 是**全局参数**，必须写在子命令**前面**：

```powershell
python -m agentflow --root D:\path\to\ws web --port 8893     # ✅
python -m agentflow web --root D:\path\to\ws --port 8893     # ❌ argparse 直接拒
```

实跑（错位那一条的原文）：

```text
usage: agentflow [-h] [--root ROOT] [--config CONFIG] ...
agentflow: error: unrecognized arguments: --root temp/userguide-web/ws
```

不给 `--root` 时用"最近的工作区"（在仓库根或 `temp/` 里敲同一条命令时，打开的是
最近在跑的那个项目，不是 cwd 那个空目录）。

**根钉死在 `serve()` 那一刻，页面上没有切换工作区的入口。** 页面自己就这么说
（`/api/machine` 的 `serving` 那一格，逐字）：

```json
"serving": {
  "pinned": true,
  "pinned_by": "serve()",
  "root": "D:\\Incubator\\agentflow\\temp\\userguide-web\\ws",
  "switch_how": "工作区根在服务启动那一刻钉死（`serve(root=…)`）。要换工作区：停掉这个服务，用 `agentflow --root <另一个工作区> web` 重启（`--root` 是全局参数，必须写在 `web` 之前）。页面不提供切换入口 —— 那会是一个点了没反应的假按钮。",
  "switch_in_page": false
}
```

⇒ **换工作区 = 停服务 + 换 `--root` 重启**。没有别的路。

### 1.5 口令（`--token`）：三路进来，一路种 cookie

```powershell
python -m agentflow --root <工作区> web --port 8896 --token <口令>     # 也可 export AGENTFLOW_WEB_TOKEN
```

给了口令就必须带，三个来路只认同一个值：

| 来路 | 用法 | 实跑 |
|---|---|---|
| 地址栏 | `http://127.0.0.1:8896/?token=<口令>` | 200，并 `Set-Cookie: agentflow_web_token=…; Path=/; HttpOnly; SameSite=Strict` |
| 脚本 | `Authorization: Bearer <口令>` | `/api/state` 200 |
| 后续请求 | 上面那次种的 cookie | 外壳、`/api/*`、`/static/*` 都 200 |

不带口令的两档 401（**形状不同，别以为没回**）：

```text
GET /            -> 401 text/html   <h1>401</h1><p>口令不对或没给（?token= / Authorization: Bearer / 口令 cookie）</p>
GET /api/state   -> 401 {"ok": false, "path": "/api/state", "tri": "not_applicable",
                         "reason": "口令不对或没给（?token= / Authorization: Bearer / 口令 cookie）"}
```

### 1.6 停

`Ctrl-C`（控制台里；代码把 `KeyboardInterrupt` 当正常停止路径吞掉，退出码 0）。
端口与 URL 记在工作区的 `webui.json` 里，下次不给 `--port` 时复用它；**被强杀的实例不写
这个文件**（这一档来自代码 `webui/server.py::run` —— 本文的临时实例都是被强杀的，
所以没有正面实跑到"正常收尾"那一支）。

---

## 2. 十页各读什么

### 2.0 先说一件容易踩的事：页面 URL 要不要 `Accept: text/html`

十个客户端路由都由同一支 SPA 外壳服务（`GET /`、`GET /index.html`、`GET /run/{sid}`，
以及"未知路径的 SPA 回退"）。**回退只在请求带 `Accept: text/html` 时发生**
（`server.py` 的 `_wants_html`），因为 `curl` / `http.client` 不带那个头，服务就不拿
一支 HTML 糊弄它，而是给诚实的 404。

实跑（同一批路径，只差一个头）：

```text
# 不带 Accept: text/html（脚本/curl 的缺省形态）
GET /live      -> 404     GET /evidence -> 404     GET /help -> 404
# 带 Accept: text/html（浏览器导航的形态）
GET /live      -> 200     GET /evidence -> 200     GET /help -> 200
```

那一张 404 页自己也把话说清了（原文）：

```html
<title>没有这个页面</title>
<h1>404</h1><p>没有这个页面</p>
<p class="why"><code>没有路由：/live</code></p>
<p>回到 <a href="/">首页</a>（首页是 SPA 外壳，读数由前端从 <code>/api/state</code> 读）。</p>
```

两条推论：

1. **深链接刷新不会挂**：在浏览器里打开 `http://127.0.0.1:8893/live` 或按 F5 都拿到 200。
2. **脚本要抓页面源码就带上那个头**；不带时请把 404 读成"这条 URL 不是端点"，
   而不是"服务坏了"。

外壳里有四个占位符被服务端现填（实跑读到）：

```text
<title>agentflow 用户端 · （不是项目文件夹）</title>
<meta name="agentflow-project" content="ws">
<meta name="agentflow-root"    content="D:\Incubator\agentflow\temp\userguide-web\ws">
<meta name="agentflow-sid"     content="">
<meta name="csrf-token"        content="<32 位十六进制，每进程一个>">
```

`agentflow-sid` 只在 `serve(sid=…)` 被交代过时才非空（`start --watch` 那条路会给它）。
页面顶栏的"当前会话"另从 `/api/state` 的 `current` 取 —— 所以**这个 meta 是空串不等于
"没有当前会话"**（实跑里 meta 为空，而 `current.sid` 是 `2026-11-21b`）。

### 2.1 对话 —— `/`（顶部导航第一格）

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/` |
| 它回答什么 | 主控在问什么；团队说到哪；我这一句话会走到哪（答问 / 插话 / 续跑 / 起一趟） |
| 读哪条端点 | `GET /api/state`（全站共享快照）· `GET /api/chat` · `GET /api/live` · `GET /api/budget` |
| 关键读数 | `pending_questions`（待答清单，空数组是合法初态）；`current`（当前会话与轮）；`ledger`（台账写入笔数）；`problems`（读盘问题，**不是"没有"而是"没读到"） |

DOM 文本级（自上而下）：顶部是品牌 + 「项目 … · 工作区根 …（启动时钉死；换工作区要重启服务并换 `--root`）」
+ 「当前会话 … · 当前轮 … · 连接 …」；正文依次是
「监视」→「提示词缓存（两档）」→「对话」→「说一句」→「回答已记录」→「没查成」→
「会话概览」→「台账」→「落点」。
（读数还没到盘时只画一张「读数」卡：「正在读盘……（还没读到就是「还没读到」，不是「空工作区」）」。）

「监视」那一卡画成四行（左边是标签，右边是实跑读到的值）：

```text
项目        ws
落点        D:\Incubator\agentflow\temp\userguide-web\ws · 文件夹存在且是一个初始化过的工作区
工作区根    D:\Incubator\agentflow\temp\userguide-web\ws（这个服务启动时钉死；要换工作区请重启服务并换 --root —— 页面没有切换入口）
当前会话    2026-11-21b    当前轮 0    连接 <live / reconnecting / …>
```

「说一句」这一卡是**唯一的输入框**，它的占位符决定你这一句会走哪条端点（页面按
"有没有待答 / 有没有在跑的循环 / 有没有原任务"自动切模式）：

| 模式 | 触发条件 | 打哪条 | 页面这句话 |
|---|---|---|---|
| 回答 | 有 `pending_questions` | `POST /answer` | 「提交回答」 |
| 插话 | 这一段有循环在跑 | `POST /api/task` | 「插一句话给正在跑的那一趟」 |
| 续跑 | 没有在跑的循环、但读得到原任务 | `POST /api/task` 然后 `POST /api/run`（`resume=1`） | 「接着说」 |
| 起一趟 | 新会话 / 没有会话 / 读不到原任务 | `POST /api/run` | 「例如：帮我把工作区里那篇论文从头到尾审核一遍…」 |

会花钱的两条（起一趟 / 续跑）走**两次确认**（`ConfirmButton`：第一次点击只"上膛"
并把影响写给你看）；回答与插话不花钱，一下就提交。

### 2.2 在飞 —— `/live`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/live` |
| 它回答什么 | 现在有没有人在跑；盘上有没有停机开关；三族义务谁没人收；最近的状态报告与用量 |
| 读哪条端点 | `GET /api/live` · `/api/status-reports` · `/api/usage` · `/api/roster` · `/api/obligations` |
| 关键读数 | `tasks_running`（**在飞**：只数 `tasks` 里 `status=running` 的行）· `unclosed_loops`（**未收尾的循环**：有 `agent_run_start` 没 `agent_run_end`）· `unclosed_running` / `unclosed_stale`（**把 `unclosed_loops` 拆成"仍在跑 / 已不在跑"两档**）· `switch_present`（盘上有没有停机开关）· `answer`（"有没有活进程"：有 / 没有 / 没查成） |

**这一页最容易被误读的两格，页面自己就写了**：

```text
两个数分开读：「在飞」只数 tasks 里 status=running 的行（这里是 0）；
下面那张表读的是「未收尾的循环」（有 agent_run_start、没有 agent_run_end 的循环记录，这里是 0）
—— 它不是「在飞」：没收到 end 只说明这一段记录没有收尾，不说明它还在跑。
```

实跑（这份工作区干净，两档都是 0）：

```json
{"tasks_running": 0, "tasks_running_tri": "computed", "unclosed_loops": 0,
 "unclosed_running": 0, "unclosed_stale": 0, "unclosed_loops_tri": "computed",
 "answer": "没有", "switch_present": false, "switch": {}, "unreadable_sessions": [], "tri": "computed"}
```

**读法**：

- `unclosed_loops` 非 0 **不等于**"还有人在跑"。要看 `unclosed_running`：
  `unclosed_stale` 那一档是"上次没善终"（宿主进程已退出、被强杀，或顶趟已收尾），
  表格里逐行标 `宿主进程已退出/被叫停，不是活着`。
- `unclosed_loops_tri` / `tasks_running_tri` 不是 `computed` 时，**这一格是"没查成"**，
  页面会跟着写 `unclosed_loops_why` / `tasks_running_why`，不要当成 0。
- `unreadable_sessions` 非空时，页面写"有会话读不出来" —— 此时**不能**断言"每一趟都收到了 end"。
- 停机开关问的是"有没有活进程"（`answer`），**循环记录的多寡不改变这一格**。

「停机开关与历史」那一卡是叫停的落点，三个按钮：**「叫停这一趟」**（优雅停）/
**「强制停（连子孙进程）」**（与 `/run/<sid>` 页共用同一个组件）/
**「撤销叫停」**（撤掉盘上那把开关，§3.11 —— 只在可写档可用）。

同一页的**名册卡**是板项的落点：每个节点展开后，「收件箱」里每一条旁边有两个按钮 ——
**「收口」**（`POST /api/ack`，§3.9）与 **「作废」**（`POST /api/void`，§3.10）。
`/live` 没有单独的板项页（这一版没有 `/board` 路由）；台账里逐行的 `item_state` /
`item_close` 在 `/artifacts` 的任务台账（§2.7）。

### 2.3 证据链 —— `/evidence`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/evidence` |
| 它回答什么 | 每条命题的五元位（numeric / proof / reviewed / formal / audited）各到哪了；猜想、实验、审校发现、稿件台账、引文回验、证明级验证、秘书决策 |
| 读哪条端点 | `GET /api/evidence`（页面用 `?summary=1` 只取摘要；不带它时这次实跑 **2.1 MB**） |
| 关键读数 | 每一栏各自带 `*_tri`；`bit_*` 五格是**按证明/按路径**记的，不是按行 |

实跑（`/api/evidence?summary=1` 的骨架）：

```json
{"tri": "computed", "reason": "",
 "statements": [{"bit_numeric": "pending", "bit_proof": "pending", "bit_reviewed": "pending",
                 "bit_formal": "…", "bit_audited": "pending",
                 "bits": {"evidence": {"formal": {}, "proof_source": "", "reviewed_by": {}}},
                 "grade": "not_applica…"}],
 "statements_tri": "computed", "conjectures_tri": "…", "experiments_tri": "…",
 "documents_tri": "…", "relations_tri": "…", "review_findings_tri": "…",
 "verifications_tri": "…", "secretary_tri": "…", "store_problems": [], "rows_total": …}
```

读法：某一位是 `pending` = **这一位还没有发生过**（没验 / 没签 / 没审），不是"没过"；
`not_applicable` = 这一位对这一行不适用。八栏各自的 `*_tri` 才是"这一栏读没读到"，
不要把"没读到"折成"0 条"。

### 2.4 验收 —— `/acceptance`（含你问的 **Compliance「结构合规」**）

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/acceptance` |
| 它回答什么 | 论文包三块：**A 证明完整吗** · **B 结构合规吗** · **C 能不能收工**；外加内容级五条判据 |
| 读哪条端点 | `GET /api/package`（可带项目根 / 报告路径 / `cap_usd`），每格"原文"走 `GET /api/source`；内容级五条走 `GET /api/acceptance` |
| 关键读数 | 三块各自的 `checked` / 计数；内容级 `criteria` 五格（`pass` / `fail` / `unknown`）＋ `failed` / `unchecked` 两张清单 |

**「Compliance」不是一个独立路由**（客户端路由表里没有 `/compliance`）：
它就是 `/acceptance` 页里的 **B 结构合规吗** 那一块（定理↔proof 配对 · cites / refs /
inputs / duplicates · 字符六类 · 台账覆盖）。

顺带：**没有一条 `/api` 下的"合规"端点**（路由表里没有这种路径）；
结构合规的机器读数是 `/api/package` 的 `structure` 那一块与 `/api/acceptance` 的 `criteria` 五格。

在地址栏敲 `/compliance` 会发生什么（2026-11-22 复核）：

```text
GET /compliance   （浏览器形态，Accept: text/html） -> 200  同一支 SPA 外壳
GET /compliance   （脚本形态，不带 Accept: text/html） -> 404  text/html 诚实 404 页（<title>没有这个页面</title>）
```

外壳 200 只是"服务端把未知路径回退成外壳"（§2.0 的 Q1 口径），**不是"这一页存在"**：
客户端 `matchRoute` 读不出这条路由，于是渲染一张 **「没有这一页」** 的卡片
（`ui/src/main.tsx` 的 `UnknownPage`），把合规 / 收工门指到 `/acceptance` 的 B 块、
把板项指到 `/live` 的名册卡与 `/artifacts` 的任务台账。
**别把"显示了这张卡片"读成"这一页坏了"，也别把外壳 200 读成"这一页存在"。**

实跑（内容级五条）：

```json
{"tri": "computed",
 "criteria": {"attachment_is_honest": "unknown", "hops_have_readable_prompts": "pass",
              "statements_have_assumptions_and_source": "fail",
              "triage_branch_recorded": "unknown", "within_cost_cap": "unknown"},
 "failed": ["statements_have_assumptions_and_source"],
 "unchecked": ["attachment_is_honest", "triage_branch_recorded", "within_cost_cap"],
 "reason": "这些格子没查成（不是通过）：attachment_is_honest、triage_branch_recorded、within_cost_cap",
 "note": "`failed` 是真不过，`unchecked` 是没查成 —— 两档不许折平"}
```

**读法（这一页最要紧的一条）**：`fail` 是"查了、不过"；`unknown` 是"**没查成**"。
两者在页面上分列两栏，读数里也分两张清单（`failed` / `unchecked`）。
`/api/package` 的 `closing` 那一块同理（同一套算式）。

### 2.5 本机 —— `/machine`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/machine` |
| 它回答什么 | 这台机器能做哪些事（Lean / Mathlib / 证明检查器）；模型 key 配没配；设置三段；这一页也能改设置、翻 Lean 开关 |
| 读哪条端点 | `GET /api/machine`；网页操作历史走 `GET /api/actions` |
| 关键读数 | `lean_ready` / `lean_enabled` / `lean_version` · `mathlib.detected` / `mathlib.graph_import_measured` · `can_do_formal` / `formal_mode` · `provers.available` · `settings_tri` · `serving.switch_how` |

实跑（同一台机器，Lean 装着但这一档关着）：

```json
{"tri": "computed", "lean_enabled": false, "lean_ready": true,
 "lean_version": "Lean (version 4.7.0, x86_64-w64-windows-gnu, commit 6fce8f7d5cd1, Release)",
 "can_do_formal": false, "formal_mode": "prose_review",
 "mathlib": {"detected": true, "checked": true,
             "graph_import_measured": "没查（本会话的 Lean 形式化关着 ⇒ 第 ⑤ 步那条探针一次都没跑）—— 这不是「Mathlib 坏了」，也不是「没装」"},
 "provers": {"available_names": ["lean"], "checked": true},
 "serving": {"pinned": true, "switch_in_page": false, "root": "…"}}
```

读法：`lean_ready=true` 是"盘上有这个可执行文件"，**不是**"这一会话会用它"；
会不会用由 `lean_enabled`（开关）与 `can_do_formal` / `formal_mode` 决定。
`mathlib.graph_import_measured` 那种"没查（原因）"的句子是**读数**，别读成失败。
`serving` 那一格是"这个服务在服务哪个工作区、以及它换不了"：`pinned` / `pinned_by` /
`switch_in_page` / `switch_how` 四格都恒在（`switch_how` 逐字给出换法：停服务换 `--root`
重启，见 §1.4）—— 它**不是**一个还能点的按钮。

**网页操作历史（`GET /api/actions`）**：这一页的「操作历史」读
`<工作区>/web-actions.jsonl`（每一笔到达写处理器的尝试一行，被拒的也留），
**只读**（不需要 `--allow-writes`：读台账不该要写权限）。用法与回执（2026-11-22 实跑；
下面 `total=19` 是那一刻的读数 —— 同一轮末尾又补了两条边角用例，**最终 21 行**，见 A.7）：

```text
GET /api/actions                  -> 200（缺省 limit=20、offset=0）
GET /api/actions?limit=5          -> 200  total=19  limit=5  offset=0  has_more=true  order="newest_first"
GET /api/actions?limit=2&offset=1 -> 200  total=19  limit=2  offset=1  has_more=true
GET /api/actions?limit=999        -> 200  limit=200（上限是 200：ACTIONS_PAGE_MAX，静默截到上限）
GET /api/actions?limit=0          -> 400  "分页参数不合法：limit 必须 >= 1（要 0 行的话没有一页可取）"
GET /api/actions?limit=abc        -> 400  "分页参数不合法：limit 必须是整数，给的是 'abc'"
GET /api/actions?offset=-1        -> 400  "分页参数不合法：offset 不能是负数，给的是 -1"
```

```json
{"tri": "computed", "reason": "", "path": "…\\ws\\web-actions.jsonl",
 "problems": [], "rows": [{"at": "2026-11-22T00:11:56+08:00", "kind": "web_action",
   "endpoint": "/api/stop/clear", "source": "127.0.0.1",
   "params": {"confirm": true}, "params_sha256": "63547eaf…",
   "result": "盘上本来就没有停机开关 —— 当前没有叫停（这一下没有改动任何东西）",
   "tri": "computed", "ok": true, "http": 200}],
 "total": 19, "limit": 5, "offset": 0, "has_more": true, "order": "newest_first"}
```

读法（三态在这一格上最容易读错）：

- `order="newest_first"` 是读数的一部分：**最新的在最上面**，翻页别按旧序想。
- 台账文件**不在盘上** ⇒ `tri="computed"` + `rows=[]` + `total=0`（"这个工作区还没有人
  从网页上动过手"，是算出来的合法初态）；台账**读不出来** ⇒ `tri="unreadable"` 且
  `rows=[]` —— 那是"没读到"，**不是"没有操作"**。坏行说明在 `problems` 里，不并进 `reason`。
- `params` 里**不含**关键值（只有 `params_sha256`）：所以这一栏能回答"谁在什么时候按了
  什么、成了没有"，答不了"他填了什么"。`source` 是请求的来源地址。

### 2.6 错误动作 —— `/errors`（你问的 **Errors / RoleErrors** 是同一页）

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/errors` |
| 它回答什么 | 盘上每个角色撞上了哪一类判据、各几次（角色 × 类目矩阵，只读、零模型调用） |
| 读哪条端点 | `GET /api/errors` + `GET /api/errors/categories`（一次全量扫描，页面上有「重新读」按钮） |
| 关键读数 | `state`（`checked` / …）· `data.by_role`（角色→类目→次数）· `data.categories`（类目合计）· `data.total` · `problems`（没归类的信号，**不猜类目**） |

实跑：

```json
{"state": "checked", "checked": true, "reason": "",
 "data": {"by_role": {"A": {"param_invalid": 2}, "B": {"param_invalid": 7, "schema_invalid": 2},
                      "D": {"judge_bad_json": 1, "param_invalid": 4, "tool_refused_edit_window": 3, …},
                      "V": {"verdict_understated": 9}, "secretary:B": {"judge_no_reply": 1}},
          "categories": {"param_invalid": 16, "verdict_understated": 9, "reply_shape_rejected": 6, …},
          "total": …},
 "problems": [{"code": "unclassified_signal",
               "detail": "结构判据认不出族的那几条没有猜类目：{'tool': 49}（…要收进来就给 errorstats 的族表补一条原话）"}]}
```

读法：**这一页是一次快照，不是实时**（抬头写着读数时间，盘上一变就要按「重新读」）。
`state != "checked"` 时整栏只画"读不到"与理由，一个矩阵格都不画 ——
那时**不要**把空白读成"零错误"。`problems` 里 `unclassified_signal` 是"有信号但没归到类"，
它的出现不代表那几次没被计数（`detail` 会说清哪一格没加数）。

### 2.7 产物 —— `/artifacts`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/artifacts` |
| 它回答什么 | 台账上的产物与一致性对账；台账写入笔数与 commit 标记；交接手稿；验收表的机器可判行；体例；任务结果；文献库；实验产物落点 |
| 读哪条端点 | `GET /api/artifacts`（`?summary=1` 取摘要）· `GET /api/literature` · `GET /api/state`（共享快照，与首页同一份） |
| 关键读数 | `ledger`（产物登记行，每行带 `sha_consistency`）· `ledger_tri` · `ledger_verify`（逐行 sha 对账：`ok` / `changed` / `missing` / `unreadable` / `not_a_file`）· `checks`（机器可判行 C1…）· `products`（每个产物的 `exists` / `bytes` / `lines` / `sha256`） |

实跑（摘要骨架）：

```json
{"ledger": [{"path": "out/tasks/t-000003.json", "kind": "task-result", "sa…": "…",
             "bytes": 2877, "note": "outcome=ok", "by_role": "B", "by_task_id_tri": "missing"}],
 "ledger_tri": "computed",
 "products": [{"name": "run-manifest.json", "exists": false, "bytes": null, "lines": null, "tri": "not_applicable"}],
 "checks": [{"id": "C1", "name": "立题：研究问题在册", "kind": "research_question_rows", "min": 1, …}],
 "handoffs": [{"body": "# M → A｜派活：…"}]}
```

**读法（这一页最容易误读的一格）**：产物登记行看起来"都 ok"，但同一行还带两格对账读数 ——

- 每行 `sha_consistency`：`match` / `mismatch` / `unknown`（`unknown` = 没有对应的核对行，**没得比**，
  不是"一致"）；
- `ledger_verify[]` 每行 `status` 取五档之一：`ok` / `changed` / `missing` / `unreadable` / `not_a_file`。
  **`changed` 不等于"被偷改"**：它带 `reason` 与 `explained` —— 其中两档是"可解释、不用管"
  （后面还有一条同路径的新登记顶替了旧登记 / 登记之后才落签块），
  只有 `rewritten_after_registration`（`explained=false`）才是"登记之后有人改了内容"那一档，
  要人看。

sha 原文（`sha256` / `sha256_now`）在数据里，**页面只显示一致不一致**。
`exists=false` + `bytes=null` 是"这个产物还没生成"，不是"0 字节"。

### 2.8 预算 —— `/budget`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/budget` |
| 它回答什么 | 总额度 / 已花 / 剩余；追加历史（谁在何时改了多少）；按角色与按归口的拆解 |
| 读哪条端点 | `GET /api/budget` |
| 关键读数 | `total_usd` / `spent_usd` / `remaining_usd` / `entries` / `added` / `unattributed_usd` / `below_reserve` / `exceeded` |

实跑（这份工作区）：

```json
{"tri": "computed", "total_usd": 5.0, "spent_usd": 4.102949000000003,
 "remaining_usd": 0.897051, "entries": 1227, "problem": "",
 "spent_tri": "computed", "spent_unknown_usd_calls": 0, "unattributed_usd": 0.387873}
```

读法：`spent_unknown_usd_calls > 0` 或 `spent_tri != "computed"` 时，已花那一格是**下界**
（有调用没记到钱）—— `spent_reason` 会说清。`unattributed_usd` 是"钱花了但归不到哪一趟"，
它与 `spent_usd` 是两格，不要相加再当成总额。

### 2.9 使用说明 —— `/help`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/help` |
| 它回答什么 | 十页分工、名册怎么读、三态语义、退出码六档、预算怎么算、写面现状、常见误解 |
| 读哪条端点 | **一条都不调**（这一页是静态文案） |
| 关键读数 | 无（页内所有命令与码表都是写死的；与实现不一致时以本文与代码为准） |

这一页 2026-11-22 复核**已与实现同步**：三处「`POST /answer` 不进授权矩阵」的旧文案
已经改掉（现在写「2026-11-21 起答问也走同一道闸门」），写端点清单是**十一条 POST**
（含 `/api/ack` · `/api/void` · `/api/stop/clear`），`/api/actions` 那一栏也写了。
改前 / 改后逐条对照与位置见 §11（那一节现在的结论是「已同步」，不再是「待 UI 改」）。

### 2.10 一趟详情 —— `/run/<会话号>`

| 项 | 内容 |
|---|---|
| URL | `http://127.0.0.1:8893/run/2026-11-21b`（会话号换成一个真的） |
| 它回答什么 | 某一趟走到哪、花了多少（检查点与事件求和**并排**）、逐条事件、交付说明、停机 |
| 读哪条端点 | `GET /api/run/{sid}` · `/api/run-index` · `/api/run/{sid}/events` · `/api/run-digest` · `/api/live` |
| 关键读数 | `runs`（趟次）· `report` / `checkpoint` · `index.tri`（索引可不可用）· `drift`（索引与事件现算是否一致） |

实跑（这份工作区**没有建过索引**，所以走"现算"那一档）：

```json
{"usable": false, "index": null, "drift": [], "sessions": ["2026-11-21b"], "tri": "unreadable",
 "reason": "索引不在盘上（还没建）：D:\\Incubator\\agentflow\\temp\\userguide-web\\ws\\index\\run-index.json"}
```

读法：`/api/run-index` 的 `tri=unreadable` **不代表 Run 页坏了**：页面据此如实标
"这次是现算的"并回退到从事件流现算（另一条读数 `/api/run-digest`）。
`drift` 非空才是"索引与事件对不上"的信号（那时页面显红）。

### 2.11 这一批新读数怎么读（2026-11-22；四个「别误读」）

这一节只讲 2026-11-22 之后页面上**多出来**的几格。它们都挂在原有卡片里，没有新开页面。

**① 产物台账的「类别」：词表外 ≠ 读坏了（`kind_state` / `kind_unknown` / `unknown_kinds`）**

`/artifacts` 的「产物台账」卡里，「类别」那一列现在带三态徽标，数据来自
`GET /api/artifacts` 的三格新读数（`kind_states` / `unknown_kinds` / `kind_flag_mismatch`）：

| 徽标 | `kind_state` | 意思 | 该怎么读 |
|---|---|---|---|
| 没有徽标 | `canonical` | 取值在 `ARTIFACT_KINDS` 词表里 | 正常 |
| 灰色虚线「历史行」 | `legacy` | 词表生效**前**落的老行 | **照读**，不是缺陷、没有待办 |
| 红色「词表外」 | `unknown` | 词表生效**后**新写、行上带 `kind_unknown=true` | 写侧用了词表外的取值，要人看 |

**别把它读成"台账坏了"**：三档都照常读、照常显示行；`kind` 永远是盘上的原值
（读侧不改写历史）。真正要动的是红色那一档（新写应当在词表内）。
`kind_flag_mismatch > 0` 是第三种情况：行上写了 `kind_unknown=false`、取值却不在词表里
（写侧那一笔标记算错了）—— 读法不变，但值得看一眼。

**② 验收页的「签不背书这一行」：签真 ≠ 签到了这一行（`sign_does_not_back_the_row`）**

`/acceptance` 的 A 块「V 签」那一段多了一枚黄色徽标
`sign_does_not_back_the_row（不算签）`，计数来自 `GET /api/package` 的
`proofs.vsign.sign_does_not_back_row`：

- 它的意思是：**签文件是真的、`statement_id` 也对得上，但这一行结构上不可能持有那份正文**
  （典型：概念行 + 非 `b-proof` 稿）。真机 `projects/lp-ball-15` 的第 4 份签就是这个形态。
- 它**不算签**：不进 `proofs.vsign.signed`，所以「V 已签 N 条」里不会有它；
- 它也**不折进 `unbacked`**（那是"签文件自己复算不上"，另一档病因）；
- 徽标是**黄色**不是红色：凭据本身没坏、V 也没做错，但读的人绝不能把它读成「已签」；
- 计数是 `null` 时是「那一格没查成」，**不是 0**。

**③ 文献库卡的「种子」：`reference/` 是种子区，`library/` 是已登记书架（SEEDFIX）**

`/artifacts` 的「文献库」卡下面多一行（`GET /api/literature` 的 `data.seed`）：

- `种子：reference/ 里 N 份` —— 种子投在 **`reference/`**（不是 `library/`）；
- `已登记书架 library/：` 后面三档：
  - 绿色「没有未登记的文件」= `library_unregistered=[]`（干净）；
  - 黄色「N 份未登记」= 书架上有文件**没有任何 `literature` 行引用** —— 这是结构异常
    （真机事故：25 份未登记种子直接铺在 `library/` 根），悬停能看到那几份文件名；
  - 灰色「没查成」= `null`（`literature` 台账读不出来 ⇒ 没得比），**不是"干净"**。
- 这一行在「文献库 0 条」时也会显示 —— 那次事故现场页面正好只有"0 条"。

**④ 本机页的「库表档案」：退役 ≠ 0 行，未启用 ≠ 做完了（DATAHYGIENE）**

`/machine` 多了一张「库表档案（已退役 / 未启用）」卡（`GET /api/machine` 的 `tables`）：

- 灰色「已退役」：`eval_results` —— 全仓 0 个写点、51 个工作区全 0 行 ⇒ **从来没有产出方**。
  历史工作区里那份文件仍在盘上，读侧认得出、行照读，但**"0 行"不是"评测过 0 条"**；
- 黄色「未启用（0 行 ≠ 做完了）」：`reprocess_requests` —— 写点 / 消费点 / 闸都在，
  只是从来没有一条请求真的跑过。于是收工门 `unfinished_request_rows`（上限 0）永远是 0，
  那是**"这条队列没启用"**，不是"请求闭环做完了"。
- 「登记面读不出来」时整卡记 `checked=false`，**不是"没有退役表"**。

**⑤ 名册的「疑似停滞」：落痕是 `.jsonl` 轨迹（NAMEFIX-B1）**

名册节点上那枚「疑似停滞 N 分钟」的悬停现在写明读数出处：
`out/steps/<台账号>.jsonl` 的**最后一行**的 `at`。这个目录是**一行一步、追加**的轨迹
（`conductor.step_beats`），不是"最后一次步号"的指针文件；旧工作区里残留的
`out/steps/<号>.json` 不是这个读数读的东西。停滞**不改三态**（它仍然是 `flying`），
也绝不因此销号。

---

## 3. 写端点：怎么打、回什么

**条数一律现算、不写死在正文里** —— 两张子表就是全部名单（总表 `routes.ROUTES`
是「自有 + 读面 + 写面」拼的，`webui/routes.py:compose`）：

```powershell
# 写面：现 12 条（POST 11 + GET 1 /api/cache）
python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import writes as w;print('writes',len(w.ROUTES));[print(' ',m,p) for m,p,h in w.ROUTES]"
# 读面：现 19 条（全 GET；含 /api/state、/api/stream）
python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import readers as r;print('readers',len(r.ROUTES));[print(' ',m,p) for m,p,h in r.ROUTES]"
# 总表：现 39 条（自有 8 + 读面 19 + 写面 12）
python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import routes as R;print('all',len(R.ROUTES))"
```

2026-11-22 00:11 的现算读数（逐条，**这份名单就是判据**）：

| 表 | 条数 | 路径 |
|---|---|---|
| 写面 `writes.ROUTES` | 12 | `POST /answer` · `POST /api/stop` · `POST /api/submit` · `POST /api/settings` · `POST /api/budget` · `POST /api/run` · `POST /api/task` · `POST /api/ack` · `POST /api/void` · `POST /api/stop/clear` · `POST /api/cache/warm` · `GET /api/cache` |
| 读面 `readers.ROUTES` | 19 | `GET /api/state` · `/api/run/{sid}` · `/api/run/{sid}/events` · `/api/evidence` · `/api/artifacts` · `/api/acceptance` · `/api/package` · `/api/source` · `/api/machine` · `/api/budget` · `/api/live` · `/api/usage` · `/api/status-reports` · `/api/chat` · `/api/roster` · `/api/obligations` · `/api/stream` · `/api/literature` · `/api/actions` |

**11 条 POST 每一条本文都实跑过**：§3.1–§3.8 是 2026-11-22 00:00 那一轮，
§3.9–§3.11 是 00:11 复核新增的三条（`/api/ack` · `/api/void` · `/api/stop/clear`，
成功档与拒绝面在附录 A.7）；`GET /api/cache` 是只读的缓存状态读数（A.2 #27），
不要拿它当写端点。

每一条都过同一道闸门（来源 ⇒ CSRF ⇒ `--allow-writes`，
`/api/settings` 再多一层 `settings_write`；`/api/cache/warm` 的 `dry_run=1` 只留来源那一层）。
下面每条给"页面怎么触发 + 对等脚本请求 + 实跑回执"。

> 请求体一律是 `application/x-www-form-urlencoded`（不是 JSON）。
> `X-CSRF-Token` 怎么拿见 §4。

### 3.0 新三条端点先读这三句（用户最容易踩的地方）

1. **`block` 项的「收口」永远回 409，这是对的**：板项状态机里 `block → done` 是倒退
   （`conductor.ITEM_MOVES` 里 `("block","done") = back`），`/api/ack` 不许绕过它。
   这类项走 **「作废」`/api/void`**，不走走「唤醒 ⇒ 再 ack」（唤醒会把 `seen_by` 清空，
   随后收口撞上"空口 ack"那道闸，还是 409）。
2. **作废是不可逆的**：它把这一条记成 `done + expired`，义务不再要求完成。
   真机那种"必须收录"的义务项（`expects=work`、无主、不在任何收件箱里）**作废它
   = 放弃那件事**（实测：作废 `t-000170` 就是放弃收录 `f-proof-000003`，见 A.7 F21）——
   别当通知随手作废。
3. **撤销叫停只撤"盘上那把开关"**，不改"上一趟已经停下"这个事实；盘上本来没有开关时
   回 200 + `extra.cleared=false` —— 那是"你要的状态已经成立"，不是失败。

### 3.1 `POST /answer` —— 答问

页面：首页「说一句」在有待答时就是这一条（点选项 = 填 `selected`，自己写 = 填 `custom`）。
令牌按 §4 取（`$tok`），下面所有写请求都带同一个头。

```text
POST /answer    qid=q9001 & sid=2026-11-21b & selected=保守：先补证据 & X-CSRF-Token: <32 位>
 -> 303  Location: /
```

`qid` 与 `sid` 必须按 `(sid, qid)` **这一对**匹配（每段会话各自从 `q0001` 编号）。
被拒的两档都是 409，但**页面说的是两句话**：

```text
再答同一个号   -> 409 「已经答过了」：… 它已经被回答过：2026-11-21b（by web @ …）。这不是失败，是「迟到了」：回答只会在下一趟运行被读到。
答一个没这个号 -> 409 「没有这个号」：… 不在任何会话的待答清单里，也不是一条已落盘的问答 —— 什么都没写。
```

答完之后页面会另起一张「回答已记录」卡，把两件当刻事实分开说：那一段的循环**还在盘上**
⇒ 不用再做什么；**已经停了** ⇒ 回答只会在下一趟运行被读到，并给一个「继续（接着干）」
按钮（续跑**会花预算**，所以不自动做）。

### 3.2 `POST /api/task` —— 插话（**必须给 `sid`**）

页面：首页「说一句」在这一段有循环在跑时就是这一条。

```text
POST /api/task   body=换一下方向 & sid=2026-11-21b & confirm=1 & X-CSRF-Token: <…>
 -> 200 {"ok": true, "tri": "computed", "id": "i-000001",
         "reason": "已投递（i-000001）：主控会在下一步开头读到，当前这一步不被打断",
         "extra": {"interjection_id": "i-000001", "sid": "2026-11-21b"}}
```

**`sid` 是硬要求**（不给就是 400，见 §6.4）。`sid` 还必须是安全的文件名主干
（字母、数字与 `- _ .`，不许含 `..`）。送达方式：下一步开头单列一段【插话】，
**不打断当前这一步**，并写进会话事件流（`agent_interjection`），盘上可复查。

可选 `subject`（缺省「用户插话」）、`dry_run=1`（只回"试运行：没有写任何一条插话"）。

### 3.3 `POST /api/stop` —— 叫停

页面：`/live` 或 `/run/<sid>` 的「叫停这一趟」/「强制停（连子孙进程）」，按钮自带两次确认。

```text
POST /api/stop   reason=userguide 夹具 & confirm=1
 -> 200 {"ok": true, "id": "…\\.agentflow-stop", "reason": "已叫停：写下停机开关（reason=userguide 夹具）",
         "extra": {"outcome": "created", "force": false, "stop": {…}}}
```

盘上的开关（实跑之后读到的原文）：

```json
{"reason": "userguide 夹具", "by": "web", "force": false,
 "at": "2026-11-21T23:15:51+08:00", "sid": "", "path": "…\\.agentflow-stop"}
```

三档结局说得很清楚（`extra.outcome`）：`created` = 这次写下的；
`upgraded` = 盘上那份被这次升级成 `force`；第三档 = **盘上已经有了，这次什么都没改**
（回执会说清是谁、什么时候先叫停的 —— 别把这一档读成"是我按停的"）。
`force=1` 额外走 `kill_registered`，回执里带 `extra.killed`。
缺 `confirm=1` ⇒ **400，什么都不动**。

> **撤销叫停**现在是独立的一条写端点（`POST /api/stop/clear`，页面在 `/live` 的停机卡上）：
> 见 §3.11。叫停之后那把开关会一直留在盘上，不撤掉它的话"再起一趟"第一步就会被它停掉。

### 3.4 `POST /api/run` —— 起一趟 / 续跑

页面：首页「说一句」在"新会话 / 没有会话 / 读不到原任务"时起一趟；答完之后那个
「继续（接着干）」按钮是续跑。

```text
# 起一趟（试算：一个进程都不起，只把 argv 给你看）
POST /api/run  task=把这一轮的结论写成一页 & confirm=1 & dry_run=1
 -> 200 {"ok": true, "reason": "试运行：没有起任何进程（argv 见 extra）",
         "extra": {"argv": ["…\\python.exe", "-B", "-m", "agentflow", "--root", "…\\ws",
                            "run-agent", "M", "--task", "把这一轮的结论写成一页", "--subagents"]}}

# 续跑必须带 sid（resume 问的是"接着哪一段跑"）
POST /api/run  task=接着说 & confirm=1 & resume=1 & dry_run=1
 -> 400 "拒绝：resume 要配 sid —— 它问的是「接着哪一段会话跑」，缺了无从选窗口"
```

真起（不带 `dry_run`）时回执带 `extra.pid` 与 `extra.log`（`runs/web-run-<时间>.log`），
进程是 **detached** 的：关掉标签页不会杀掉它。

### 3.5 `POST /api/submit` —— 投放检索种子

```text
POST /api/submit  topic=…一个可判定的检索请求 & mode=topical & content=只要三篇 & confirm=1
 -> 200 {"ok": true, "id": "r-000009",
         "reason": "已入队 r-000009（topic=… · mode=topical）"}
```

空 `topic` ⇒ 400「topic 不能为空（整批未写入）」。工作区这一档有两半，**别混成一句**：

- **空目录**：`store.init()` 会顺手把它建成工作区 —— 实跑在一个空目录上投放**成功**，拿到 `r-000001`；
- **不是工作区、里面又有不属于本框架的条目**（没有 `data/`、但有别人的文件）：**400**，
  回执把三条出路逐条写出来：

```text
拒绝：这个工作区没有 data/（没 `agentflow init` 过），不能入队 —— 先 `agentflow init`，或换一个已初始化的工作区。
StoreError: 拒绝 init：…\ws4 既不是工作区（没有 data/）、又不是空目录 —— 里面有 1 个不属于我们的条目：['我的资料.txt']。
…三条出路：① 这确实是新工作区 ⇒ 换一个空目录；② 确认就要在这里建 ⇒ `init(force=True)`（或 CLI `init --force`）；
③ 走工具层：`projects.ensure_project`…
```

### 3.6 `POST /api/settings` —— 改设置

```text
POST /api/settings  toolchain.lean_bin=D:/fake/lean.exe & confirm=1
 -> 200 {"ok": true, "id": "D:\\…\\temp\\userguide-web\\settings.json",
         "reason": "已写入 D:\\…\\settings.json（只改了这几格：['toolchain.lean_bin']）",
         "extra": {"settings_tri": "written", "values": {…}, "permissions": {…}}}
```

表单键是「段.键」（`toolchain.lean_bin`、`models.<角色>.<键>`）。
`model.api_key` 这类 key **只写不读**：文件里是真值，回执里恒为 `***`。

⚠ **落点不是 `--root`**：`/api/settings` 写的是**机器级** `agentflow/settings.json`
（`settings.settings_path` 的三档：显式 `path` → 环境变量 `AGENTFLOW_SETTINGS` → 默认落点）。
本文那次实跑是把 `AGENTFLOW_SETTINGS` 指到 temp 才打的，否则会改到本机真设置 ——
**你若不是想改本机，请先设这个环境变量再起服务**。

### 3.7 `POST /api/budget` —— 追加 / 重设额度

```text
POST /api/budget  action=add & usd=1.5 & note=userguide 夹具 & confirm=1
 -> 200 {"ok": true, "id": "…\\ws\\budget.json",
         "reason": "已追加额度：总额现在是 $6.500000",
         "extra": {"action": "add", "total_usd": 6.5, "added_count": 2, "entry": {…}}}
```

`action` 只认 `add` / `set`；`usd` 读不成数字 ⇒ 400。改预算与停机同一档：**缺 `confirm=1` ⇒ 400**。
追加是**运行期生效**的：下一次花钱之前的闸门会现读到新上限，不用重启。

### 3.8 `POST /api/cache/warm` —— 预热提示词缓存

```text
POST /api/cache/warm  dry_run=1 & confirm=1          # 只读档也放行（这条不写盘、不花钱、不起进程）
 -> 200 {"ok": true, "tri": "computed", "state": "plan",
         "reason": "试算（没有发请求、花费 0 美元）：要预热 0 个目标，预计 0.000000 美元",
         "extra": {"argv": ["…python.exe", "-B", "-m", "agentflow", "--root", "…\\ws", "cache", "warm", "--lean", "off"], …}}
```

真预热（不给 `dry_run`）：过完整四层 + `confirm=1`，起 detached 子进程，回执 `state=running`
（这一档**本文没有实跑** —— 它会真花钱；`state` / `confirm` / `_spawn_warm` 的行为来自
`webui/cacheface.py::handle_cache_warm` 与实跑到的试算档）。
**试算那一档只保留"回环来源"这一层**（没有 CSRF、没有 `--allow-writes` 也放行）——
这是刻意的：它不写盘、不花钱、不起进程。注意 `confirm=1` **两档都要**：
缺它时回执那句写的是「真预热会真的花钱，必须带 confirm=1」（试算也照这句拒）。

### 3.9 `POST /api/ack` —— 收口一条板项

页面：`/live` → 名册卡 → 点开那个节点 → 「收件箱」里那一条旁边的 **「收口」**
按钮（`ui/src/components/Roster.tsx` 的 `AckButton`：它只递 `task_id` 与 `close=acked`，
**能不能收口不由前端判**）。收口结果落在台账里，也能在 `/artifacts` 的任务台账
（`item_state` / `item_close` 两列）看到。

```text
POST /api/ack   task_id=t-000180 & close=acked & confirm=1 & X-CSRF-Token: <32 位>
 -> 200 {"ok": true, "tri": "computed", "id": "t-000180",
         "reason": "已收口 t-000180（item_state=done · close=acked）",
         "extra": {"task_id": "t-000180", "item_state": "done", "item_close": "acked",
                   "seen_by": "t-000001", "kind": "notice", "expects": "ack",
                   "detail": "USERGUIDE-WEB 夹具：一条已经读进来、等收口的通知（item_state=seen）",
                   "audit": {"params_sha256": "d74e186b…", "path": "…\\ws\\web-actions.jsonl",
                             "tri": "computed"}}}
```

字段只有三个：`task_id`（哪一条）· `close`（`acked` / `completed` / `expired`，
缺省 `acked`；闭集是 `schema.ITEM_CLOSES`）· `confirm=1`（硬要求）。
**判据全在板项状态机里**（`conductor.close_item` → `ITEM_MOVES` + 空口 ack 闸）：
只有已经 `seen` 过的项能被推成 `done`；同一项再 ack 一次是**幂等 200**（回执与上一次同形）。

被拒的每一档（2026-11-22 实跑，都是 `tri=not_applicable`，`extra.item_state` 带当时的现态）：

```text
POST /api/ack  task_id=t-000055 & close=acked & confirm=1   # block 项（优雅停止翻下的）
 -> 409 {"kind": "conflict",
         "reason": "没收口 t-000055：t-000055 已经到过 'block'（不许倒退或重复迁移）（台账里现在是 item_state=block）",
         "how_to_fix": "这一条已被处理或不存在；刷新后再看"}

POST /api/ack  task_id=t-000181 & close=acked & confirm=1   # queued 项（还没被任何一步读到）
 -> 409 "没收口 t-000181：t-000181 还没有 seen（没被读进任何一步）就收到 ack ⇒ 空口 ack：读数留着，状态不动（业主 A5）（台账里现在是 item_state=queued）"

POST /api/ack  task_id=t-000001 & confirm=1                  # 不是板项（kind 为空，是代理行）
 -> 409 "没收口 t-000001：t-000001 不是板项（kind 为空）⇒ 它的状态不由状态机管（台账里现在是 item_state=（空））"

POST /api/ack  task_id=t-999999 & confirm=1                  # 没有这个号
 -> 409 "没收口 t-999999：没有这一项（task_id='t-999999'）—— 不是'已经做完'（台账里现在是 item_state=（空））"

POST /api/ack  task_id=t-000180 & close=acked                # 缺 confirm（盘上一个字节不动）
 -> 400 {"kind": "confirm_required",
         "reason": "拒绝：收口一条板项要 confirm=1 一次显式确认（它会让一条还在板上的事项从待办里消失）"}
POST /api/ack  close=acked & confirm=1                       # 空 task_id
 -> 400 "拒绝：task_id 不能为空 —— 要说清收口哪一条"
POST /api/ack  task_id=t-000180 & close=whatever & confirm=1 # close 不在闭集
 -> 400 "拒绝：close 只认 ('acked', 'completed', 'expired')（收到 'whatever'）"
```

> **`block` 项回 409 不是 bug，是迁移图在守门。** 它们在状态机里没有出边，
> 正确的收口路是 **§3.10 的「作废」**；"唤醒 ⇒ 再 ack"也不行（唤醒会清 `seen_by`，
> 随后撞上空口 ack 那道闸，仍是 409）。

### 3.10 `POST /api/void` —— 作废一条不再需要做的板项

页面：`/live` 名册卡 → 收件箱里那一条旁边的 **「作废」** 按钮
（`ui/src/components/Roster.tsx` 的 `VoidButton`：先"上膛"，再写一句
"为什么这一条不用再做了"，然后「确认作废」）。

```text
POST /api/void  task_id=t-000175 & why=USERGUIDE-WEB 夹具：这一条不用再做了 & confirm=1 & X-CSRF-Token: <32 位>
 -> 200 {"ok": true, "tri": "computed", "id": "t-000175",
         "reason": "已作废 t-000175（item_close=expired · 原 expects=ack）—— 这一条不再欠动作",
         "extra": {"task_id": "t-000175", "item_state": "done", "item_close": "expired",
                   "expects": "", "expects_was": "ack", "kind": "notice",
                   "voided": ["t-000175"], "already_closed": false,
                   "traces": [{"item_id": "t-000175", "by": "user", "owner": "t-000122",
                               "from": "block", "to": "done", "close": "expired",
                               "mode": "revoke", "authority": "human",
                               "at": "2026-11-22T00:11:53+08:00",
                               "reason": "USERGUIDE-WEB 夹具：这一条不用再做了"}]}}
```

台账里落成的样子（同一份盘，实跑后读行）：

```json
{"kind": "notice", "status": "block", "item_state": "done", "item_close": "expired",
 "expects": "", "expects_was": "ack",
 "inputs": ["revoke:expired:by=user:owner=t-000122:from=block:to=done:at=2026-11-22T00:11:53+08:00:reason=USERGUIDE-WEB 夹具：这一条不用再做了",
            "void-trace|item=t-000175|mode=revoke|by=user|owner=t-000122|from=block|to=done|close=expired|at=…|reason=…|authority=human"]}
```

**这一条端点守的四件事**（每条都有实跑或代码出处）：

1. **只作废"不再需要做"的项**：`block` 这类没有出边的项正是它的对象；
   `/api/ack` 对同一项照旧 409（见 §3.9 —— 作废**不是**给状态机开一条 `block → done` 的边）。
2. **记在人名下**：唯一写入口 `conductor.void_items_by_user`（≡
   `void_items(revoke=True, by_human=True)`），留痕写 `by=user` / `authority=human`
   （`conductor.ITEM_AUTHORITY_HUMAN`）。代理走工具那条路（`conductor.void_items`）
   冒用 `by_task_id="user"` ⇒ 台账里没有这个号 ⇒ `unknown_actor`（受控拒绝，一格不改）。
3. **理由必填**：`why` 逐字进 `inputs` 的 `revoke:expired:` 那一格与事件 note ——
   事后能回答"谁凭什么撤的"。缺它 ⇒ 400，盘上零改动。
4. **权限面**：回环来源 ⇒ CSRF ⇒ `--allow-writes`（这三层都 403），再加 `confirm=1`
   （缺它 400）—— 与其余写端点同一道闸门（§4）。

两档"不成功"要分开读：

```text
POST /api/void  task_id=t-000175 & why=… & confirm=1   # 同一项再来（已经终态）
 -> 200 {"ok": true, "tri": "computed",
         "reason": "t-000175 已经是收口状态（item_state=done）—— 这一下没有改动",
         "extra": {"already_closed": true, "traces": [], "voided": []}}
         # "你要的状态已经成立" ≠ "刚做成"：200 但 already_closed=true，别读成第二次作废成功

POST /api/void  task_id=t-999999 & why=x & confirm=1   # 没有这个号
 -> 409 {"kind": "conflict", "reason": "没作废 t-999999：没有这一项（不是'已经作废'）（台账里现在是 item_state=（空））"}
```

400 三档（盘上零改动）：缺 `confirm` ⇒ `kind=confirm_required`「作废不可逆」；
缺 `why` ⇒「作废要写清「为什么这一条不用再做了」」；空 `task_id` ⇒「要说清作废哪一条」。
读不成台账 ⇒ 500 `tri=unreadable`（**不是**"已经作废"）。

> ⚠ **"必须收录"那种义务项，作废它 = 放弃那件事。**
> 真机 `lp-ball-15` 的 `t-000170`（`expects=work`、无主、不挂在任何收件箱里）正是这一类：
> 实测作废它会**成功**（200 / `expects_was=work` / `item_close=expired`），
> 而它的意思是"放弃收录 `f-proof-000003`"（A.7 F21）。
> 作废不可逆，**别把它当通知随手按掉**。

### 3.11 `POST /api/stop/clear` —— 撤销叫停

页面：`/live` 的「停机开关与历史」卡里的 **「撤销叫停」**（`ClearStopButton`，
两次确认；按钮 `title` 写着"盘上本来就没有开关时也安全：回执会说「当前没有叫停」"）。

```text
# 1) 盘上本来就没有开关（幂等那一档）
POST /api/stop/clear  confirm=1 & X-CSRF-Token: <32 位>
 -> 200 {"ok": true, "tri": "computed",
         "reason": "盘上本来就没有停机开关 —— 当前没有叫停（这一下没有改动任何东西）",
         "extra": {"cleared": false, "cleared_switch": {}, "switch_present": false,
                   "stop_path": "…\\ws\\.agentflow-stop"}}

# 2) 先叫停造一把开关，再撤
POST /api/stop        reason=guideweb 夹具：给撤销叫停造开关 & confirm=1
 -> 200 {"ok": true, "id": "…\\ws\\.agentflow-stop",
         "reason": "已叫停：写下停机开关（reason=guideweb 夹具：给撤销叫停造开关）",
         "extra": {"outcome": "created", "force": false,
                   "stop": {"at": "2026-11-22T00:11:54+08:00", "by": "web", "force": false,
                            "reason": "guideweb 夹具：给撤销叫停造开关", "sid": "",
                            "path": "…\\ws\\.agentflow-stop"}}}
        # 同一刻 GET /api/live ⇒ switch_present=true（"在飞"页那一格就是它）

POST /api/stop/clear  confirm=1
 -> 200 {"ok": true, "tri": "computed",
         "reason": "已撤销叫停（撤掉了 web 在 guideweb 夹具：给撤销叫停造开关 上落的那把开关）—— 当前没有叫停，再起一趟不会被它停掉",
         "extra": {"cleared": true,
                   "cleared_switch": {"at": "2026-11-22T00:11:54+08:00", "by": "web",
                                      "force": false, "reason": "guideweb 夹具：给撤销叫停造开关", …},
                   "switch_present": false, "stop_path": "…\\ws\\.agentflow-stop"}}

# 3) 再撤一次 ⇒ 回到 1) 那一档（200 + cleared=false）
```

字段只有 `confirm=1`。三档结局分开说：`cleared=true` = 这次真撤掉了一把
（`cleared_switch` 是**撤之前**那份开关的原样副本 —— 撤掉之后盘上已读不到它，
这一格是这一笔唯一的留痕）；`cleared=false` + `switch_present=false` = 本来就没有，
"你要的状态已经成立"；撤失败 ⇒ 500（`tri=unreadable`，磁盘那份没被动过）。
缺 `confirm` ⇒ 400 `kind=confirm_required`（"撤错会让本该停的那一趟继续跑"）。

---

## 4. CSRF：页面怎么拿、脚本怎么拿

**每进程一个随机令牌**（32 位十六进制），由服务端在吐外壳时填进
`<meta name="csrf-token" content="…">`。盘上的构建产物里只有占位符 `__CSRF__`，
所以**刷新页面会拿到同一个令牌，重启服务就会换一个**。

页面侧（`ui/src/api.ts`）：所有写请求（表单编码 + `X-CSRF-Token` 头）都从那个 meta 读；
读不到（还是字面量 `__CSRF__`）就当空令牌 —— 结果是 403 `csrf_token`，不是"静默放行"。

脚本侧只有一条路（本文的探针就是这么做的）：**先 GET `/`，从 HTML 的 meta 里抠**。

```powershell
$html = (Invoke-WebRequest 'http://127.0.0.1:8895/' -UseBasicParsing).Content
$tok  = [regex]::Match($html, 'name="csrf-token" content="([^"]+)"').Groups[1].Value
# $tok 形如 8f3a…（32 位十六进制）
```

服务端**没有**把令牌放在任何响应头里（别去找 `X-CSRF-Token` 响应头 —— 它只出现在
请求头这一侧）；只能从外壳的 meta 读。写请求的最小形状（实跑用的就是它）：

```text
POST /api/task
Cookie: （无）
X-CSRF-Token: <32 位>
Content-Type: application/x-www-form-urlencoded

body=换一下方向&sid=2026-11-21b&confirm=1
```

**授权次序是四层，次序即失败理由**（都 403，但 `kind` 不同）：

```text
① 回环来源（Origin / Host / 对端地址；跨站一律拒）  -> kind=foreign_origin
② CSRF 令牌（X-CSRF-Token，比对走 compare_digest）   -> kind=csrf_token
③ --allow-writes（缺省只读）                        -> kind=writes_off
④ 只有 /api/settings：--no-settings-write            -> kind=settings_off
```

这四层之后还有一道**不是 403 的**闸：不可逆动作要显式确认 ⇒ 缺 `confirm=1` 回
**400 `kind=confirm_required`**（`/api/stop` · `/api/run` · `/api/task` ·
`/api/settings` · `/api/budget` · `/api/submit` · `/api/ack` · `/api/void` ·
`/api/stop/clear` · `/api/cache/warm` 的真跑档）。四层 + confirm 合起来就是本文说的
"写面那道闸门"。

`/answer` 与其余各条**同一道闸门**（`writes._gate`），所以它也会因为这几层被 403。
2026-11-22 复核：Help 页那三句旧文案已经改掉（§11），两处现在说法一致。

新三条端点（`/api/ack` · `/api/void` · `/api/stop/clear`）的三种 403 实跑读数
（只读档 8892）：

```text
ack 不带 CSRF   -> 403 {"kind": "csrf_token", "reason": "拒绝：POST /api/ack：CSRF 令牌不对或没带（写请求必须带 X-CSRF-Token）"}
ack 跨站 Origin -> 403 {"kind": "foreign_origin", "reason": "拒绝：POST /api/ack：Origin 不是回环地址（evil.example）—— 写面只对本机开"}
ack 只读档      -> 403 {"kind": "writes_off", "reason": "拒绝：POST /api/ack：写面没开 —— 要用 `agentflow web --allow-writes` 才允许写"}
（/api/void 与 /api/stop/clear 逐字同形，只换端点名 —— 见 A.7 E1–E9）
```

---

## 5. 只读档能做什么 / 不能做什么

| 想做的事 | 只读档 | 可写档 |
|---|---|---|
| 打开十页、看所有读数 | ✅ | ✅ |
| 看事件流（SSE） | ✅ | ✅ |
| 缓存**试算**（`/api/cache/warm` + `dry_run=1`） | ✅ 200 | ✅ 200 |
| 答问 `POST /answer` | ❌ 403 `writes_off` | ✅ 303 |
| 插话 `/api/task` | ❌ 403 | ✅ 200 |
| 叫停 `/api/stop` | ❌ 403 | ✅ 200 |
| 起跑 / 续跑 `/api/run` | ❌ 403 | ✅ 200 |
| 投放 `/api/submit` | ❌ 403 | ✅ 200 |
| 改预算 `/api/budget` | ❌ 403 | ✅ 200 |
| 改设置 `/api/settings` | ❌ 403 | ✅ 200（另需 `settings_write`） |
| 缓存真预热 | ❌ 403 | ✅ 200 |
| 收口板项 `POST /api/ack` | ❌ 403 `writes_off` | ✅ 200（状态机放行的项；`block` 项 409 是正确行为） |
| 作废板项 `POST /api/void` | ❌ 403 `writes_off` | ✅ 200（`block` 项也能收口；不可逆，要写理由） |
| 撤销叫停 `POST /api/stop/clear` | ❌ 403 `writes_off` | ✅ 200（本来就没开关时也 200 + `cleared=false`） |
| 在工作区里留下 `web-actions.jsonl` | **一个字节都不写** | 每次写尝试一行 |
| 换工作区 | ❌（重启服务换 `--root`） | ❌（同上） |
| 看网页操作历史 `GET /api/actions` | ✅ 200（只读，不要写权限） | ✅ 200 |

只读档被拒时**也会做审计**，但只进 stderr、不落盘 —— 回执里那一格写着：

```json
"extra": {"audit": {"params_sha256": "…", "path": "…\\web-actions.jsonl",
                    "reason": "本服务是只读档（没开 --allow-writes）：这一笔只进 …（不落盘）",
                    "tri": "not_applicable"}}
```

---

## 6. 常见错误：状态码 → 什么意思 → 怎么修

### 6.1 `403 foreign_origin` —— 来源不是本机

```json
{"ok": false, "tri": "not_applicable", "kind": "foreign_origin",
 "reason": "拒绝：POST /api/task：Origin 不是回环地址（evil.example）—— 写面只对本机开",
 "how_to_fix": "从本机浏览器打开这一页（跨站来源一律拒）"}
```

**修法**：从 `http://127.0.0.1:<port>/` 或 `http://localhost:<port>/` 那一页发；
脚本里**别自己加 `Origin` 头**（加了且不是回环就是这一档）。
判定看三处：`Origin`、`Host`、socket 对端地址。绑 `0.0.0.0` 时用
`http://0.0.0.0:<port>` 打开不会因此被拒（那是绑定地址，不是外来证据）。

### 6.2 `403 csrf_token` —— 令牌不对或没带

```json
{"ok": false, "tri": "not_applicable", "kind": "csrf_token",
 "reason": "拒绝：POST /api/task：CSRF 令牌不对或没带（写请求必须带 X-CSRF-Token）",
 "how_to_fix": "刷新页面重新拿令牌（每进程换一个）；不要手工拼 POST"}
```

**修法**：按 §4 从 `/` 的 meta 里抠令牌；**服务重启过就重新抠**（每进程一个）。
浏览器里出现这一档，多半是页面是旧外壳（服务重启过而标签页没刷新）⇒ F5。

### 6.3 `403 writes_off` —— 这一档是只读

```json
{"ok": false, "tri": "not_applicable", "kind": "writes_off",
 "reason": "拒绝：POST /api/task：写面没开 —— 要用 `agentflow web --allow-writes` 才允许写",
 "how_to_fix": "用 `agentflow web --allow-writes` 重启服务（缺省只读，只读档不写盘）"}
```

**修法**：`--allow-writes` 重启。页面上一眼能看到这一档：`/api/state` 的
`writes_allowed=false`、`writes_reason` 是那句中文，按钮被禁用并带 `title`。

### 6.4 `400` 缺 `sid`（插话）

```json
{"ok": false, "tri": "not_applicable", "kind": "bad_request",
 "reason": "拒绝：插话必须给 sid —— 它回答的是「写进哪一段会话」。缺省不再落到当天日期那一段：M 在自己的 --sid 段里读不到，而且那段空会话会把页面的「当前会话」顶掉",
 "how_to_fix": "读回执里那句理由，改参数后重试"}
```

**修法**：给 `sid`（页面永远知道自己看的是哪一段）。sid 也不是随便什么字符串：

```text
sid=../etc -> 400 "拒绝：sid 不是安全的会话号（'../etc'）—— 只许字母、数字与 - _ .，且不许含 .."
```

### 6.5 `400 confirm_required` —— 不可逆动作要显式确认

```json
{"ok": false, "tri": "not_applicable", "kind": "confirm_required",
 "reason": "拒绝：叫停不可逆，必须带 confirm=1 一次显式确认（draft/75 §1.1 第 8 行）",
 "how_to_fix": "带 confirm=1 重试（不可逆动作要显式确认一次）"}
```

**修法**：带 `confirm=1`。这一档覆盖 `/api/stop`、`/api/budget`、`/api/settings`、
`/api/submit`、`/api/run`、`/api/task`、`/api/cache/warm`（真跑那一档），以及
2026-11-22 复核的三条：**`/api/ack`**（「收口一条板项要 confirm=1 …」）、
**`/api/void`**（「作废一条板项要 confirm=1 …作废不可逆…」）、
**`/api/stop/clear`**（「撤销叫停要 confirm=1 …」）。缺 `confirm` 时**一个字节都不写**。

### 6.6 `409` 答问的两档「已经答过了」/「没有这个号」

见 §3.1。这不是失败：一档是"迟到了"（回答只会在下一趟运行被读到），
一档是"号不存在"（什么都没写）。两档都是 HTML 页（`/answer` 不是 JSON 端点）。

### 6.7 `401` —— 这个服务要口令

见 §1.5。页面是 HTML `<h1>401</h1>`，`/api/*` 是 `{"ok": false, "tri": "not_applicable", "reason": "口令不对或没给…"}`。
修法：地址栏带一次 `?token=<口令>`（会种 cookie），脚本用 `Authorization: Bearer <口令>`。

### 6.8 `404 unknown_endpoint` —— 这条端点不在这一版

```json
{"ok": false, "tri": "not_applicable", "kind": "unknown_endpoint",
 "reason": "没有这个端点：/api/nope",
 "how_to_fix": "路由表里没有这一条 —— 前端与后端可能不是同一版；刷新页面，仍不行就重启服务"}
```

（2026-11-22 实跑：`POST /api/nope` ⇒ 这条 404。`/api/nope` 是**探针里刻意打的未知路径**，
不是本文在教一条端点 —— 说明书里出现的端点名全部在 `ROUTES` 里，自检脚本见附录 B 第 6 条。）

**修法**：先核 §3 开头那张现算名单（端点是否存在以 `writes.ROUTES` / `readers.ROUTES`
为准）；页面深链接的 404 见 §2.0（脚本要带 `Accept: text/html`）。
**顺带**：2026-11-22 之前 `/api/ack` / `/api/stop/clear` 确实会回这条 404 ——
它们现在都在路由表里（只读档回 403 `writes_off`，不是 404）。

### 6.9 `409 conflict` —— 新三条端点的"状态机不认这一下"

`/api/ack` 与 `/api/void` 的 409 都是 `kind=conflict` + `tri=not_applicable`，
回执里带**当时的现态**（`extra.item_state` / `extra.item_close` / `extra.task_id`）：

```text
POST /api/ack  block 项      -> 409「已经到过 'block'（不许倒退或重复迁移）」   ⇒ 改用 §3.10 作废
POST /api/ack  queued 项     -> 409「还没有 seen … 空口 ack（业主 A5）」        ⇒ 等它被读进某一步再收口
POST /api/ack  不是板项/没这个号 -> 409「不是板项（kind 为空）」/「没有这一项」
POST /api/void 没有这个号    -> 409「没有这一项（不是'已经作废'）」
```

**修法**：读那一刻的 `extra.item_state` 再决定（`block` ⇒ 作废；`queued` ⇒ 等；
`done` ⇒ 已经是终态）。**别把 409 当"再试一次就好"**：重试同一请求会得到同一句话。

### 6.10 `500` —— 结局说不清

`tri=unreadable`。回执里那句 `reason` 会说明"盘上那一份没被动过"或原样给出错误。
把那一行与时间报给维护者；**不要重试着猜**（这一档是"没查成"，不是"再试一次就好"）。

---

## 7. 读数纪律：三种"零"不是一回事

写页面读数时最容易犯的错，是把三件事折成同一个 0：

| 你看到的 | 意思是 | 不是 |
|---|---|---|
| `0` / `[]` | 查过了，确实是零 | — |
| `unknown` / `unchecked` / `not_applicable` | **没查成**（或这一位不适用） | 不是 0 |
| `unreadable` | 读不出来（盘上没有 / 读坏了） | 不是 0 |

具体到几格：

- `/api/state` 的 `problems` 非空 = 有读盘问题，这时"没有待答"之类的话只能算**下界**。
- `/api/live` 的 `unclosed_loops` ≠ "在飞"；`unclosed_stale` 是"上次没善终"。
  两格的 `*_tri` 不是 `computed` 时那一格是"没查成"。
- `/api/run-index` 的 `tri=unreadable` = 没有索引（走现算），不是"没有趟次"。
- `/api/acceptance` 的 `unknown` 与 `fail` 分两张清单（`unchecked` / `failed`）。
- `/api/artifacts` 里"产物登记 ok"不等于"这份产物没被动过"：同一行还有 `sha_consistency`，
  对账行 `ledger_verify` 有 `changed` / `missing` / `unreadable` 等五档（§2.7）。
  `$0.000000` / `0 行` 这类读数**要看旁边的 `why` / `tri`**。
- `/api/errors` 的 `state != "checked"` 时整栏是"读不到"，**不画矩阵**（别读成零错误）。
- `/api/actions`：台账**文件不在盘上** ⇒ `tri=computed` + `total=0`（合法初态）；
  台账**读不出来** ⇒ `tri=unreadable` + `rows=[]`（"没读到"，不是"没有操作"），
  坏行在 `problems` 里（§2.5）。
- `/api/ack` 的 409 是 `tri=not_applicable`（状态机不认这一下），不是 `unreadable`；
  同一句重试还是 409 —— 先读 `extra.item_state`（§6.9）。
- `/api/void` 的 `already_closed=true`（200）是"已经是"、`voided=[…]`（200）是"刚做成"、
  409 是"没这一项/状态机拒"、500 `tri=unreadable` 是"读不成台帐"—— 四档不许折平（§3.10）。
- `/api/stop/clear` 的 `cleared=false`（200）是"本来就没有开关"（"你要的状态已经成立"），
  `cleared=true` 才是"这一下撤掉了"（§3.11）。
- `/compliance` 不是路由：浏览器形态回 200 的是**外壳**，里面渲染的是「没有这一页」卡片；
  别把外壳 200 读成"这一页存在"（§2.4）。

---

## 8. 安全注意

1. **别把这个服务暴露到公网。** 它缺省的信任模型是"本机单用户"：
   写面只对回环开（`Origin` / `Host` / 对端地址三重判），CSRF 令牌只防跨站，
   它**不是**一套账号体系。
2. 真要跨机访问，先给 `--token`（`?token=` 一次种 cookie / `Bearer`），
   并且清楚：令牌在 cookie 里是明文，`SameSite=Strict` 只挡跨站，挡不住拿到 cookie 的人。
   绑 `0.0.0.0` 之前先想清楚这条。
3. **跨站可答**这一类事 2026-11-21 修过一次（`/answer` 原先不走授权矩阵 ⇒ 带
   `Origin: evil.example` 的跨站表单也能把待答答掉并落盘）。现在它与其余各条同闸门 ——
   本文 §6.1 那条实跑就是回归证据。
4. 写面每一条到达写处理器的尝试都会落 `<工作区>/web-actions.jsonl`（含被拒的），
   `params` 里**不含**关键值（只有 `params_sha256`）—— 但那仍然是"谁在什么时候试过什么"的记录，
   分享工作区前想一下要不要清。
5. 只读档是**真的只读**：它连审计台账都不建（否则"只读服务"就在别人的目录里新建文件了）。
   要审计就别开只读档。
6. **板项作废是"人"的决定**：网页这条写端点把留痕记成 `by=user` / `authority=human`
   （`conductor.ITEM_AUTHORITY_HUMAN`）。代理那条工具路（`conductor.void_items`）
   冒用 `by_task_id="user"` 会拿 `unknown_actor` 受控拒绝 —— 所以网页上按「作废」
   就是一次人的决定，别让别人代按；它不可逆（§3.10）。
7. `/api/stop/clear` 撤的只是**盘上那把开关**，不改"上一趟已经停下"这个事实：
   撤完之后历史还是历史，只是"再起一趟"不会被旧开关停掉（§3.11）。

---

## 9. 这一版还没有的（别在页面上找）

| 缺什么 | 现状 | 替代 |
|---|---|---|
| 页面内切换工作区 | **刻意不做**（根在 `serve()` 时刻钉死） | 停服务 + 换 `--root` 重启 |
| `/compliance` 独立页 | 没有这个路由（敲这个路径会得到「没有这一页」卡片，§2.4） | `/acceptance` 的 B 块 |
| 独立 `/role-errors` 路由 | 没有（`/errors` 就是它） | `/errors` |
| 独立的 `/board` 板项页 | 没有这个路由 | `/live` 的名册卡收件箱 · `/artifacts` 的任务台账 |

2026-11-22 复核后**这四件已经不在"还没有"里**：板项收口 `/api/ack`（§3.9）、
板项作废 `/api/void`（§3.10）、撤销叫停 `/api/stop/clear`（§3.11）、网页操作历史
`GET /api/actions`（§2.5）。它们各自在页面上的按钮位置也写在那几节。

---

## 10. 附录 A：逐请求实跑清单

**实例**：A = 只读档 8893 · B = 可写档 8895 · C = 口令档 8896 · D = 自动挑端口（8700）
（以上是 00:00 那一轮）；**E = 只读档 8892 · F = 可写档 8893**（2026-11-22 00:11 复核，
工作区 `temp/guideweb/ws`，新三条端点在 **A.7**，编号 E1–E21/F1–F21）。
**工作区**：`temp/userguide-web/ws`（`projects/lp-ball-15` 的副本；
复核轮用的是它的副本 `temp/guideweb/ws` —— 六条 `block` 板项原样在盘上）。

### A.1 页面（浏览器形态：`Accept: text/html`）

| # | 请求 | 状态码 | 关键响应 |
|---|---|---|---|
| 1 | `GET /` (A) | 200 | `text/html` 外壳；meta 里有 `csrf-token`（32 位）、`agentflow-root`、`agentflow-project` |
| 2 | `GET /live` (A) | 200 | 同一支外壳（SPA 路由） |
| 3 | `GET /evidence` (A) | 200 | 同上 |
| 4 | `GET /acceptance` (A) | 200 | 同上 |
| 5 | `GET /machine` (A) | 200 | 同上 |
| 6 | `GET /errors` (A) | 200 | 同上 |
| 7 | `GET /help` (A) | 200 | 同上 |
| 8 | `GET /budget` (A) | 200 | 同上 |
| 9 | `GET /artifacts` (A) | 200 | 同上 |
| 10 | `GET /run/2026-11-21b` (A) | 200 | 同一支外壳 |
| 11 | `GET /compliance` (A) | 200 | 同一支外壳，但客户端路由读不出 ⇒ **画的是首页** |
| 12 | `GET /live`（**不带** `Accept: text/html`，A） | 404 | `text/html` 诚实 404 页（"没有这个页面"） |
| 13 | `GET /static/assets/index.<hash>.js` (A) | 200 | `text/javascript`（文件名随构建变，别抄） |
| 14 | `GET /` (C，无口令) | 401 | `<h1>401</h1><p>口令不对或没给…</p>` |
| 15 | `GET /?token=<口令>` (C) | 200 | `Set-Cookie: agentflow_web_token=…; Path=/; HttpOnly; SameSite=Strict` |
| 16 | `GET /api/state` (C，`Authorization: Bearer`) | 200 | 与无口令档同一份快照 |

### A.2 读数端点（只读档 A）

| # | 请求 | 状态码 | 关键字段（实跑值） |
|---|---|---|---|
| 17 | `GET /api/state` | 200 | `tri=computed` · `writes_allowed=false` · `writes_reason="本服务未开 --allow-writes…"` · `pending_questions=[]` · `ledger.events=5918` · `problems=[]` · `current.sid=2026-11-21b` |
| 18 | `GET /api/live` | 200 | `tasks_running=0` · `unclosed_loops=0` · `unclosed_running=0` · `unclosed_stale=0` · `answer="没有"` · `switch_present=false` · `unreadable_sessions=[]` |
| 19 | `GET /api/evidence` | 200 | 2.1 MB；`tri=computed`（`?summary=1` 时八个 `*_tri` 各自给） |
| 20 | `GET /api/acceptance` | 200 | `criteria` 五格 = pass 1 / fail 1 / unknown 3；`failed`/`unchecked` 两张清单 |
| 21 | `GET /api/package` | 200 | `closing` / `structure` / `proofs` / `cache` / `tri` |
| 22 | `GET /api/machine` | 200 | `lean_ready=true` · `lean_enabled=false` · `can_do_formal=false` · `formal_mode="prose_review"` · `serving.pinned=true` · `serving.pinned_by="serve()"` · `serving.switch_in_page=false` · `serving.switch_how=…`（换工作区的做法，§1.4） |
| 23 | `GET /api/errors` | 200 | `state="checked"` · `data.by_role` · `problems[0].code="unclassified_signal"` |
| 24 | `GET /api/errors/categories` | 200 | `categories` · `source` |
| 25 | `GET /api/artifacts?summary=1` | 200 | `ledger_tri=computed` · `products`（`exists=false` 的项） · `checks`（C1…） |
| 26 | `GET /api/budget` | 200 | `total_usd=5.0` · `spent_usd=4.102949…` · `remaining_usd=0.897051` · `entries=1227` |
| 27 | `GET /api/cache` | 200 | `active.text="当前使用：**非 Lean 版缓存**（p315 · 11/12…）"` · `writes_allowed=false` |
| 28 | `GET /api/usage` | 200 | `tri=computed` · `by_role` / `by_scope` / `spent` |
| 29 | `GET /api/run-index` | 200 | `usable=false` · `tri="unreadable"` · `reason="索引不在盘上（还没建）：…"` |
| 30 | `GET /api/status-reports` | 200 | `count` |
| 31 | `GET /api/roster` | 200 | 名册树（40 KB） |
| 32 | `GET /api/obligations` | 200 | `counts={"b-register":{"open":1,"unowned":1}, …}` · `recipient_rule=…` |
| 33 | `GET /api/actions` | 200 | 网页操作历史：`tri` · `rows` · `total` · `limit` · `offset` · `has_more` · `order="newest_first"`（分页与三态见 §2.5；2026-11-22 复核读数见 A.7） |
| 34 | `GET /api/literature` | 200 | 文献库（只算正式入库那一档） |
| 35 | `GET /api/chat` | 200 | 对话事件流视图（165 KB） |
| 36 | `GET /api/stream` (SSE) | 200 | `text/event-stream`；首帧 `event: state` + `data: {"snapshot": …}` |

### A.3 写端点 —— 只读档 A（除缓存试算外全部被拒）

| # | 请求（都带正确 CSRF） | 状态码 | `kind` / 回执 |
|---|---|---|---|
| 37 | `POST /api/task` | 403 | `writes_off` |
| 38 | `POST /api/task`（**不带** CSRF） | 403 | `csrf_token` |
| 39 | `POST /api/task`（`Origin: http://evil.example`） | 403 | `foreign_origin`「Origin 不是回环地址（evil.example）」 |
| 40 | `POST /answer` | 403 | HTML 错误卡「403 · 写回答被拒」+ 分档 `writes_off` |
| 41 | `POST /answer`（跨站 Origin） | 403 | HTML 错误卡 + 分档 `foreign_origin` |
| 42 | `POST /api/run` | 403 | `writes_off` |
| 43 | `POST /api/stop` | 403 | `writes_off` |
| 44 | `POST /api/submit` | 403 | `writes_off` |
| 45 | `POST /api/settings` | 403 | `writes_off` |
| 46 | `POST /api/budget` | 403 | `writes_off` |
| 47 | `POST /api/cache/warm`（真跑） | 403 | `writes_off` |
| 48 | `POST /api/cache/warm`（`dry_run=1`，**无令牌**） | **200** | `state="plan"`「试算…0 个目标，预计 0.000000 美元」 |
| 49 | `POST /api/ack` | 403（**当时 404**） | 当时这两条还没落地 ⇒ `unknown_endpoint`；2026-11-22 复核它们已在 `ROUTES` 里 ⇒ 只读档回 `writes_off`（A.7 E3） |
| 50 | `POST /api/stop/clear` | 403（**当时 404**） | 同上（A.7 E9） |

只读档这 14 条写请求（外加 1 条未知端点探测）之后，`ws/web-actions.jsonl` **仍不存在**。
（#49/#50 的状态码是复核后的现状；当时那次打到的确实是 404 —— 两件事都留在表里，
因为"端点从无到有"本身就是这一版的变化。）

### A.4 写端点 —— 可写档 B（2026-11-22 00:00 那一轮）

| # | 请求 | 状态码 | 关键字段 |
|---|---|---|---|
| 51 | `POST /api/task` 缺 `sid` | 400 | `kind=bad_request`「插话必须给 sid…」 |
| 52 | `POST /api/task` 缺 `confirm` | 400 | `kind=confirm_required` |
| 53 | `POST /api/task` `sid=../etc` | 400 | 「sid 不是安全的会话号（'../etc'）…」 |
| 54 | `POST /api/task` `dry_run=1` | 200 | 「试运行：没有写任何一条插话」`extra.dry_run=true` |
| 55 | `POST /api/task` 真投递 | 200 | `id=i-000001` · `extra.sid=2026-11-21b` |
| 56 | `POST /api/run` 缺 `task` | 400 | 「任务不能为空…」 |
| 57 | `POST /api/run` `dry_run=1` | 200 | `extra.argv=[…, "run-agent", "M", "--task", …, "--subagents"]` |
| 58 | `POST /api/run` `resume=1` 无 `sid` | 400 | 「resume 要配 sid…」 |
| 59 | `POST /api/submit` 空 `topic` | 400 | 「topic 不能为空（整批未写入）」 |
| 60 | `POST /api/submit` 正常 | 200 | `id=r-000009` |
| 61 | `POST /api/budget` `add 1.5` | 200 | 「总额现在是 $6.500000」· `extra.added_count=2` |
| 62 | `POST /api/settings` | 200 | `extra.settings_tri="written"` · 落点 = `AGENTFLOW_SETTINGS` 指的那个 temp 文件 |
| 63 | `POST /api/cache/warm` `dry_run=1` | 200 | `state="plan"` |
| 64 | `POST /answer` `qid=q9001` | **303** | `Location: /`；会话里落 `user_answer` |
| 65 | `POST /answer` 同一 `qid` 再来 | **409** | 「已经答过了」+ 谁在什么时候答的 |
| 66 | `POST /answer` `qid=q9999` | **409** | 「没有这个号」 |
| 67 | `POST /api/stop` 缺 `confirm` | 400 | `kind=confirm_required` |
| 68 | `POST /api/stop` `confirm=1` | 200 | `extra.outcome="created"` · `id=…\\.agentflow-stop` |

**台账对账**：可写档共 18 条写请求到达写处理器 ⇒ `web-actions.jsonl` **18 行**，
按 `(endpoint, http)` 拆开逐条对得上：

```text
('/answer',303) 1   ('/answer',409) 2   ('/api/budget',200) 1   ('/api/cache/warm',200) 1
('/api/run',200) 1  ('/api/run',400) 2  ('/api/settings',200) 1 ('/api/stop',200) 1
('/api/stop',400) 1 ('/api/submit',200) 1 ('/api/submit',400) 1 ('/api/task',200) 2 ('/api/task',400) 3
```

### A.5 起服务本身

| # | 命令 | 结果 |
|---|---|---|
| 69 | `python -m agentflow --root …\ws web --port 8893 --json` | `{"url": "http://127.0.0.1:8893/", "root": "…"}` |
| 70 | 同上 + `--allow-writes`（端口 8895） | `{"url": "http://127.0.0.1:8895/", "root": "…"}` |
| 71 | 同上但端口被占（8894） | 退出非 0；stderr 两行说明占位者与换号建议 |
| 72 | `python -m agentflow web --root … --port 8897` | argparse 拒：`unrecognized arguments: --root …` |
| 73 | 不给 `--port` | 自动挑到 `http://127.0.0.1:8700/` |
| 74 | `--token userguide-token`（8896） | 起服务正常；三路口令见 A.1 #14–16 |

### A.6 工作区形态（`/api/submit` 那两半）

| # | 工作区形态 | 请求 | 状态码 | 关键字段 |
|---|---|---|---|---|
| 75 | 空目录（`temp/userguide-web/ws2`，无 `data/`、无别的文件） | `POST /api/submit` `topic=x&confirm=1` | **200** | 顺手 `store.init()`；`id=r-000001`「已入队 r-000001（topic=x · mode=topical）」 |
| 76 | 别人的目录（`temp/userguide-web/ws4`，有 `我的资料.txt`、无 `data/`） | 同上 | **400** | `kind=bad_request`「这个工作区没有 data/（没 `agentflow init` 过），不能入队 …」+ `StoreError` 原文（点名那 1 个条目 + 三条出路） |

### A.7 新三条端点 —— 2026-11-22 00:11 复核（只读档 E=8892 / 可写档 F=8893）

**工作区是 `temp/guideweb/ws`**（`temp/userguide-web/ws` 的副本）：
真机 `lp-ball-15` 那 **6 条 `block` 板项原样在盘上**（`t-000055` / `t-000170` / `t-000175` /
`t-000176` / `t-000178` / `t-000179`）。开跑前清掉了副本继承的两件测试残留
（上一轮探针留下的 `.agentflow-stop` 与 18 行 `web-actions.jsonl`）⇒ 本轮台账从 0 行起算。
另外补了两条**夹具板项**（走产品自己的 `Conductor._write_new_row`，只动副本）：
`t-000180`（`item_state=seen`，给 ack 的成功档）、`t-000181`（`item_state=queued`，
给 ack 的空口 ack 闸）—— 因为这份副本上"还没收口的项"全是 `block`（状态机里没有出边）。

**只读档 E（8892）**：9 条写请求 ⇒ 9 条 403，另 1 条未知端点 404：

| # | 请求 | 状态码 | `kind` |
|---|---|---|---|
| E1 | `POST /api/ack` 不带 CSRF | 403 | `csrf_token`「拒绝：POST /api/ack：CSRF 令牌不对或没带…」 |
| E2 | `POST /api/ack` `Origin: http://evil.example` | 403 | `foreign_origin`「Origin 不是回环地址（evil.example）」 |
| E3 | `POST /api/ack` 带令牌（只读档） | 403 | `writes_off`「写面没开 —— 要用 `agentflow web --allow-writes`」 |
| E4 | `POST /api/void` 不带 CSRF | 403 | `csrf_token` |
| E5 | `POST /api/void` 跨站 Origin | 403 | `foreign_origin` |
| E6 | `POST /api/void` 带令牌（只读档） | 403 | `writes_off` |
| E7 | `POST /api/stop/clear` 不带 CSRF | 403 | `csrf_token` |
| E8 | `POST /api/stop/clear` 跨站 Origin | 403 | `foreign_origin` |
| E9 | `POST /api/stop/clear` 带令牌（只读档） | 403 | `writes_off` |
| E10 | `POST /api/nope`（未知端点探测） | 404 | `unknown_endpoint`「没有这个端点：/api/nope」 |
| — | `GET /api/actions`（只读档也放行） | 200 | `tri=computed` · `rows=[]` · `total=0`（台账不存在是合法初态） |
| — | `GET /api/state` | 200 | `writes_allowed=false` |

这 10 条写 / 探测请求（外加上面两条 GET）之后：`ws/web-actions.jsonl` **不存在**、
`.agentflow-stop` **不存在**。

**可写档 F（8893）**：21 条写请求 ⇒ 台账 21 行（逐条对得上）：

| # | 请求 | 状态码 | 关键字段 |
|---|---|---|---|
| F1 | `POST /api/ack` 缺 `confirm` | 400 | `kind=confirm_required` |
| F2 | `POST /api/ack` 空 `task_id` | 400 | `kind=bad_request`「task_id 不能为空」 |
| F3 | `POST /api/ack` `close=whatever` | 400 | 「close 只认 ('acked', 'completed', 'expired')（收到 'whatever'）」 |
| F4 | `POST /api/ack` `task_id=t-000055`（block 项） | **409** | 「已经到过 'block'（不许倒退或重复迁移）」· `extra.item_state=block` |
| F5 | `POST /api/ack` `task_id=t-000180`（seen 项） | **200** | `id=t-000180` · `extra.item_state=done` · `item_close=acked` · `seen_by=t-000001` |
| F6 | 同一项再 ack 一次 | **200** | 幂等：回执与 F5 同形（同一行） |
| F7 | `POST /api/ack` `task_id=t-000001`（非板项） | 409 | 「不是板项（kind 为空）⇒ 它的状态不由状态机管」 |
| F8 | `POST /api/ack` `task_id=t-999999` | 409 | 「没有这一项（task_id='t-999999'）—— 不是'已经做完'」 |
| F9 | `POST /api/ack` `task_id=t-000181`（queued 项） | 409 | 「还没有 seen（没被读进任何一步）就收到 ack ⇒ 空口 ack（业主 A5）」 |
| F10 | `POST /api/void` 缺 `confirm` | 400 | `kind=confirm_required`「作废不可逆」 |
| F11 | `POST /api/void` 缺 `why` | 400 | 「why 不能为空 —— 作废要写清「为什么这一条不用再做了」」 |
| F12 | `POST /api/void` 空 `task_id` | 400 | 「task_id 不能为空 —— 要说清作废哪一条」 |
| F13 | `POST /api/void` `task_id=t-000175`（block 项） | **200** | `reason=已作废 t-000175（item_close=expired · 原 expects=ack）` · `extra.traces[0].by=user` / `authority=human` |
| F14 | 同一项再作废一次 | **200** | `extra.already_closed=true` · `voided=[]`（"已经是"≠"刚做成"） |
| F15 | `POST /api/void` `task_id=t-999999` | 409 | 「没有这一项（不是'已经作废'）」 |
| F16 | `POST /api/stop/clear` 缺 `confirm` | 400 | `kind=confirm_required` |
| F17 | `POST /api/stop/clear`（盘上没开关） | **200** | `extra.cleared=false` · `switch_present=false` |
| F18 | `POST /api/stop` `confirm=1`（造开关） | 200 | `extra.outcome=created` · `id=…\\.agentflow-stop`；同一刻 `GET /api/live` ⇒ `switch_present=true` |
| F19 | `POST /api/stop/clear` `confirm=1` | **200** | `extra.cleared=true` · `extra.cleared_switch` 是撤之前那份开关的原样副本 |
| F20 | 再撤一次 | **200** | 回到 `cleared=false`（"当前没有叫停"） |
| F21 | `POST /api/void` `task_id=t-000170`（`expects=work` 义务项） | **200** | 「已作废 … 原 expects=work」—— 它等于**放弃收录 `f-proof-000003`**（§3.10 那条警告的实跑） |

同一轮里另外两条读数：`GET /api/actions?limit=5` ⇒ 200 · `total=19`（打这两条边角用例之前）
/ `has_more=true` / `order=newest_first`；`GET /api/state` ⇒ `writes_allowed=true`。

**台账对账**（21 条写请求读完 `web-actions.jsonl` 的 21 行）：

```text
('/api/ack',200) 2   ('/api/ack',400) 3   ('/api/ack',409) 4
('/api/void',200) 3  ('/api/void',400) 3  ('/api/void',409) 1
('/api/stop',200) 1  ('/api/stop/clear',200) 3  ('/api/stop/clear',400) 1
合计 21 行 ⇔ 21 条到达写处理器的写请求（F5/F6/F13/F14/F21 成功档、其余拒绝档都在里面）
```

收尾后盘上读数（**板项轴** `item_state`/`item_close`；任务轴 `status` 是另一根轴，
收口不改它）：`t-000180` = `done` + `acked`；`t-000175` = `done` + `expired`
（`status` 仍是 `block` —— 两根轴别混读；`inputs` 里两行留痕：`revoke:expired:by=user:…`
与 `void-trace|…|authority=human`）；
`t-000055` 仍是 `block`（ack 拒了、没被写坏）；`t-000170` = `done` + `expired`（`status` 仍是 `block`）；
`.agentflow-stop` 已撤（不在盘上）；`web-actions.jsonl` 21 行。
**真机工作区没被动过**（`projects/lp-ball-15` 全程没有写请求）。

---

## 11. 页面文案与实现：2026-11-22 已同步（改前 / 改后逐条）

2026-11-22 00:00 那一轮本文记过 Help 页（`/help`）的**三处**旧文案：它们说
"`POST /answer` 不进授权矩阵、缺省也放行"，与实现相反（`/answer` 自 2026-11-21
WEBFIX1 / 审计 F4 起与其余各条同走 `writes._gate`）。**复核时这三处已经改好了**
（UI 侧在本路之前落的），现在两处说法一致 —— 下表留的是"改前是什么 / 现在是什么"，
用来证明这一处漂移确实被收掉了，不是"看起来差不多"。

| # | 位置 | 改前的文案（摘） | 现在的文案（2026-11-22 复核读到） |
|---|---|---|---|
| 1 | `ui/src/pages/Help.tsx:59` | 「…**答问除外 —— POST /answer 是既有写路径，不进那张授权矩阵，缺省也放行**」 | 「…收口板项 / 撤销叫停 / 答问都走这一档（**2026-11-21 起答问也走同一道闸门**）」 |
| 2 | `ui/src/pages/Help.tsx:239` | 「…唯一例外是 `dry_run=1` 的试算档…（`/answer` 是既有写路径，不进那张矩阵）」 | 「**十一条 POST 全在路由表里**（/answer、/api/stop、…、/api/ack、/api/void、/api/stop/clear、/api/cache/warm）；…（**/api/ 下那十条写端点与 /answer 都如此**；唯一例外是 `dry_run=1` 的试算档…）」 |
| 3 | `ui/src/pages/Help.tsx:315-321` | 「`POST /answer` 是既有写路径，**不进那张矩阵**（只落审计）」 | 「授权次序是四层…这四层管的是 `/api/` 下那十条写端点；**`POST /answer` 从 2026-11-21（审计 F4）起也走这四层**」 |

顺带核对（现在是**一致**的，不是待改项）：

- 「十一条 POST」= `writes.ROUTES` 里 POST 的条数（现算 11，§3 开头）。Help 正文与
  「写面现状」那一段都列了全部十一条，含新三条 `/api/ack` · `/api/void` · `/api/stop/clear`。
- 帮助页给的命令形状（`python -m agentflow.cli --root … web …`）与本文实测一致：
  `--root` **必须写在 `web` 之前**（写在后面会 argparse 报错，§1.4）。
- `agentflow web --help` 里那句「不开这一档时 `/api/` 下的写端点一律 403 ——
  唯一例外是 `POST /api/cache/warm`」在只读档上成立（它**不写条数**，所以不会随条数漂）；
  但**缓存试算（`dry_run=1`）在只读档是 200** 这一档 `--help` 没提，只在 Help 正文
  与本文 §3.8/§4 里 —— 以正文为准。

---

## 12. 附录 B：怎么复跑

本文所有读数都由下面这几个脚本产生（在 `temp/userguide-web/` 与
`temp/guideweb/` 两个临时目录里，都不进产品）：

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'
$env:AGENTFLOW_SETTINGS='D:\Incubator\agentflow\temp\userguide-web\settings.json'  # 别改本机真设置

# 0) 现盘前端产物是哪一支（别抄本文没写的文件名）
(Get-Content src/agentflow/web/static/index.html | Select-String 'index\..*\.js').Line.Trim()

# 1) 起两个临时实例（00:00 那一轮）
Start-Process python -ArgumentList @('-m','agentflow','--root','D:\Incubator\agentflow\temp\userguide-web\ws','web','--port','8893','--json') -RedirectStandardOutput temp/userguide-web/logs/ro.out -RedirectStandardError temp/userguide-web/logs/ro.err
Start-Process python -ArgumentList @('-m','agentflow','--root','D:\Incubator\agentflow\temp\userguide-web\ws','web','--port','8895','--allow-writes','--json') -RedirectStandardOutput temp/userguide-web/logs/rw.out -RedirectStandardError temp/userguide-web/logs/rw.err

# 2) 逐页 + 读数端点（写 get-ro.json）
python temp/userguide-web/probe_get.py 8893 ro

# 3) 写面矩阵：只读档 / 可写档各一次（写 post-ro.json / post-rw.json）
python temp/userguide-web/probe_post.py 8893 ro
python temp/userguide-web/probe_post.py 8895 rw

# 4) 外壳、静态资源、SSE
python temp/userguide-web/probe_shell.py

# 5) 收尾：收掉自己起的实例（别动别人的端口）
Get-NetTCPConnection -LocalPort 8893,8895 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# 6) 新三条端点的复核（GUIDE-WEB-REFRESH，2026-11-22 00:11；工作区 temp/guideweb/ws）
python temp/guideweb/reset_copy.py temp/guideweb/ws        # 清副本里上一轮的 .agentflow-stop / web-actions.jsonl
python temp/guideweb/make_seen_item.py temp/guideweb/ws    # 夹具：一条 item_state=seen 的板项
#    起 E=8892（只读）/ F=8893（可写）两个临时实例，然后：
python temp/guideweb/probe_three.py 8892 ro                # 只读档：新三条 × 三种拒绝（写 three-ro.json）
python temp/guideweb/probe_three.py 8893 rw                # 可写档：400/409/200（写 three-rw.json）
python temp/guideweb/probe_edge.py 8893                    # queued 项的空口 ack + void 一条 expects=work 义务项
python temp/guideweb/probe_extra.py 8893                   # /api/machine · /compliance · /api/actions 分页边界
python temp/guideweb/summarize.py                          # 收成读数 + 台账对账 + 板项行
python temp/guideweb/check_doc_endpoints.py                # 自检：说明书里的端点集合 ⊆ ROUTES（见 §12.1）
Get-NetTCPConnection -LocalPort 8892,8893 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

判据（"这一次是真跑的"）：`get-ro.json` 里 `/` 的 `csrf_len=32`；`post-rw.json` 里
`答问 q9001` 的 `status=303`、`重复答问` 的 `status=409`；`web-actions.jsonl` 的行数
等于"到达写处理器的写请求数"（复核轮是 21 ⇔ 21）；`three-ro.json` 里九个 403 与一个 404；
`three-rw.json` 里 ack-block=409 / ack-seen=200 / void-block=200 / clear 无开关 `cleared=false`；
`check_doc_endpoints.py` 退出码 0。

### 12.1 自检：说明书里的端点集合 ⊆ `ROUTES`

这一份说明书是给人读的，所以它**自己也可能漂**（写出一条不存在的端点，读者照着打就 404）。
判据是一条脚本：把本文里出现的端点名（`/api/*` 与 `/answer` 两种写法）抽出来，
逐个查 `routes.ROUTES`；**差集必须为空**：

```powershell
python temp/guideweb/check_doc_endpoints.py
# 输出形如：doc endpoints 34 · 全部命中 ROUTES（另有 1 条刻意打的未知路径 /api/nope 在豁免表里）
# 退出码 0 = 子集成立；1 = 有端点不在 ROUTES 里（脚本会把漏网的逐条列出来）
```

脚本里那条**唯一的豁免**是 `/api/nope`：它是 §6.8 里用来实跑 404 的**探针路径**，
不是本文在教一条端点。豁免表写在脚本里、逐条带理由，不是"扫不到就算了"。
