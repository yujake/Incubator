# ui/ —— 用户端前端工程（Preact + Vite）开发说明

> 这份文件写给"要改这个前端的人"。设计口径（抄 DSH 的皮、六个页面各自读什么、两套三态词表）
> 在 `../docs/USER-END-DSH-STYLE.md`（§1 皮 · §3 界面纪律 · **§3.1 六页逐栏**）；
> 契约表（端点逐条 / 事件 6 个 kind / 字段 / 路由 / 组件 props）在
> `../../draft/75-Web端伪代码（逐前端文件·互相对齐）.md` §1，**它是名字的唯一来源**
> （题 T2-a 新加的那一条端点由主控落进 §1.1 的 C1 表）。

---

## 1. 目录与文件清单（本机读数：19 个文件、4126 行）

```text
ui/
  package.json          # scripts: dev / build / typecheck（= tsc --noEmit）
  pnpm-workspace.yaml   # allowBuilds: esbuild（pnpm 11 起构建脚本默认不跑，逐条放行）
  vite.config.ts        # base="/static/"；outDir=../src/agentflow/web/static；哈希文件名；sourcemap=false
  tsconfig.json         # strict + noUncheckedIndexedAccess（把"可能缺的键"逼成编译错误）
  index.html            # <div id="app"> + <meta name="csrf-token" content="__CSRF__">（服务端注入）
  README-DEV.md         # 本文件
  src/
    main.tsx            # 挂载 + 客户端路由（ROUTES 是 C4 契约的前端一侧）+ 顶部导航
    api.ts              # ENDPOINTS（端点的唯一出口）+ 取数函数 + ApiError（三态）
    sse.ts              # KINDS（= 后端 EVENT_KINDS）+ EventSource 订阅 + ?since= 续传 + 降级轮询
    live.tsx            # 全站只订阅一次 SSE；快照/连接态/version 分发给六页（useLive/useFace）
    types.ts            # 生成物，勿手改（python -m agentflow.web.emit_types）
    pages/              # 六个页面：Home Run Evidence Artifacts Machine Acceptance
    components/         # 六个组件：Badge Card ConfirmButton Money Table TriState
    theme/app.css       # 只用令牌（var(--dsw-*)），一个色值都不许写死
    theme/generated/theme.css   # 生成物，勿手改（python -m agentflow.web.emit_theme）
```

`pages/Run.tsx` 里的 `EventTimeline` 是**一趟的逐条事件**（题 T2-a）：`api.getRunEvents(sid,
{ sinceIndex, limit })` 取一页，"继续加载"用上一页的 `to_index` 当 `sinceIndex` 续取；
`unreadable` / `not_applicable` 各有一句自己的话（**不许**画成一张空列表，也不许把条数写成 0
—— 那一档后端给的计数栏是 `None`）。`index` 与「趟次」那张表的 `start_index`/`end_index`
是同一套编号（会话里第几条事件，0 起）。

## 2. 装依赖与构建（三条命令）

```powershell
pnpm -C ui install        # 只跑一次
pnpm -C ui build          # 产物落 src/agentflow/web/static/（index.html + assets/*.js|css）
pnpm -C ui typecheck      # = tsc --noEmit（类型门，契约 §3-E）
```

依赖只有四个：`preact`（运行期）+ `vite` / `@preact/preset-vite` / `typescript`（开发期）。

**沙箱里的两个已知坑（实测 2026-10-07）**：

1. 没有"用管道 stdio 起子进程"权限的环境里，`pnpm build` 与 `node node_modules/vite/bin/vite.js build`
   都报 **`spawn EPERM`**（esbuild 的 service 进程拉不起来；`pnpm` 还会先在 `install` 那一步撞同一堵墙）。
   那**不是** `pass`：发布门里这一步记 `unknown`（`draft/80` 题 7）。产物本身入库，
   所以"没有 node 也能 `agentflow web`"这条不受影响。
2. 同一环境里 `node node_modules/typescript/bin/tsc --noEmit` **可以**直跑（一个 node 进程、不起子进程）
   ⇒ 类型门不必记 `unknown`。**绕过 `pnpm` 是刻意的**：`pnpm` 的前置 install 检查也走 spawn。

## 3. 产物入库的规矩（裁定 B1）

`src/agentflow/web/static/` **要入库**：clone 下来不必装 node 就能起网页。代价是三条纪律：

- **改了 `ui/` 就必须重建并一起提交**（`pnpm -C ui build` ⇒ `git add src/agentflow/web/static`）——
  `tests/test_webui_static.py` 会真跑"产物与源码一致 / 产物自洽"的判据（没有 node ⇒ skip 并写明理由，
  不是 pass）；
- **产物里不许出现真令牌**：外壳只放 `__CSRF__` 占位符，服务端吐它时才换成本进程的随机令牌
  （判据 `test_webui_static.py::test_the_index_html_source_has_no_real_token`）；
- **带内容哈希的文件名**（`assets/index.<hash>.js`）才 `immutable` 缓存；其余（`index.html`）`no-store`。

## 4. 两份生成物：手改必红

| 生成物 | 生成器 | 新鲜度判据 |
|---|---|---|
| `src/types.ts` | `python -m agentflow.web.emit_types` | `tests/test_webui_contracts.py::test_types_ts_is_generated_not_hand_edited` |
| `src/theme/generated/theme.css` | `python -m agentflow.web.emit_theme` | 同文件 `test_theme_css_is_generated_not_hand_edited` |

要改类型 ⇒ 改**源**：`webui/state.py` / `webui/readers.py` / `webui/writes.py` 三个模块各自的
`type_decls()`（三条零交线各写自己那一段），再重跑生成器。要改令牌 ⇒ 改 `web/assets.py` 的 `THEME_CSS`
（它是令牌的唯一来源），再重跑 `emit_theme`。

## 5. 改了前端之后跑哪几条判据

| 判据 | 守什么 |
|---|---|
| `tests/test_webui_contracts.py` | 四条名字层：A 端点集合 == `routes.ROUTES`；B `sse.ts` 的 `KINDS` == `sse.EVENT_KINDS`；C `types.ts` 的键集合 == 后端在夹具上真读出来的键；D `main.tsx` 的路由集合 == `draft/75 §1.4` 的 C4 表；外加两份生成物的新鲜度 |
| `tests/test_webui_pages.py` | 每页一条：真读数出现 + 空态 + 三态（读端点 + 读页面源码两头都比；含 Run 页逐条事件那一块的正控与"不许画成空列表"的负控） |
| `tests/test_webui_readers.py` | 各只读面的正控/负控（含逐条事件：编号口径与 `snapshot()` 同一套、`since_index`/`limit` 分页、`limit=0`/负数 ⇒ 400、超上限有界、会话不在盘上 ⇒ `unreadable`） |
| `tests/test_webui_static.py` | `GET /` 吐 SPA 外壳（`#app` + 注入过的令牌 + `no-store`）、静态路由与目录穿越、SPA 回退的 `Accept` 收窄 |
| `tests/test_webui_sse.py` | 后端那一条流（B 的判据；前端侧由契约 B 与 D 守着） |
| `node node_modules/typescript/bin/tsc --noEmit` | 类型层：组件 props 不匹配、后端键改名都会在这里断 |

**三态纪律在前端的落点**（改页面时最容易踩的一条）：`unreadable` / `unknown` 不许渲染成
`0` / `——` / `false`。两套词表（`Tri` 与 `ReportTri`）都投影到 `components/TriState.tsx` 的三种视觉态，
映射只有 `visualOf()` 一处；`components/Table.tsx` 的 `cell()` 把 `null` / 空串一律渲染成 `unknown`。
