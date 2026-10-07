# draft/78 Web 端排期拆成三条主线（**文件级零交**）

> **一句话**：把 W0–W5 重新切成 **A 骨架与前端 / B 只读面与索引 / C 写面与设置写面** 三条主线，**三条的文件集合两两不相交、且覆盖全部 55 个计划文件**（机器可证，见 §2）。
> **零交靠三条共享约定成立**（§3）：新端点与新类型由各线在**自己的模块**里声明，A 线的 `routes.py` / `emit_types.py` 只做拼接 —— 没有这三条，任何两条线都会撞在同一个文件上。
> **一线一个工作树**（`temp/wt-<线>`），各自提交在自己的分支；**主控按序合并**（§5）。

---

## §1 三条主线是什么

| 线 | 名字 | 覆盖的批次 | 范围（做什么） | 判据（该线自成闭环） |
|---|---|---|---|---|
| **A** | 骨架与前端 | **W0**（骨架）· **W1 的页面**· **W2 的前端**· **W4 的文档**· **W5**（旧壳清理） | `ui/**`（Preact+Vite、六页面、六组件、主题）· `webui/{__init__,server,routes,state,views}.py`（拆包 + 静态路由 + SPA 回退 + 路由拼接）· `web/**` 两个生成器 · `cli.py` 的两个开关 · 契约判据 + 静态/页面判据 · 三份文档 | 现有 17 条全绿 · 契约 A–D（含负控）· 静态穿越负控 · `/api/*` 未知不吐 HTML · 生成物新鲜度 · 旧壳删净后仍全绿 |
| **B** | 只读面与索引 | **W1 的 readers**· **O2 的趟次索引**· **L1 的收敛**· **W2 的后端 SSE** | `webui/readers.py`（六面读模型 + 自己的 `ROUTES` + 自己的 `type_decls()`）· `webui/sse.py`（广播器 + `EVENT_KINDS`）· `sessions.py`（`run_index_*` + `reconcile_run_index`）· `userio.py`（L1 的收敛入口）· 夹具（J2/K2 的两份样本造在 `conftest.py`） | 每面一条正控 + "数据源不可读 ⇒ `tri=unreadable`"的负控 · 索引对账（手改索引必红、删会话必报 drift）· SSE 五条（含端到端）· L1 收敛后待答判据仍绿 |
| **C** | 写面与设置写面 | **W3**（写面三件 + 审计）· **W4**（设置写面 + 浏览器端到端 + **G2 两份禁改区 patch**） | `webui/writes.py`（`/answer`·`/api/stop`·`/api/submit` + 授权 + 自己的 `ROUTES`/`type_decls()`）· `webui/audit.py`（`web-actions.jsonl`）· `settings.py`（`write_settings`）· 写面判据 + 浏览器判据 · `pyproject.toml` / `tools/release_all.py`（**只出 patch，等人签**） | 授权矩阵（403/404 四种）· 每一次写都留审计 · **绕闸门负控** · key 不回显四处 · 原子写 · 浏览器五条（opt-in） |

**注意 `I1` 的效应**：`/api/task` 不做 ⇒ C 线的写面只有**三件**（`/answer` 既有 + `/api/stop` + `/api/submit`），比原计划少一件。
**注意 `H1` 的效应**：C 线若发现某件事**没有既有闸门**可走 ⇒ **停下报所有者**，不自己开写路径。

---

## §2 文件所有权表（机器可证：`python -B temp/_check_line_ownership.py`）

**读数（2026-10-07 实跑）**：A **21** 条 glob · B **8** 条 · C **9** 条；`required_all` **55** 个文件；**被多条线认领 = 0** · **没人认领 = 0** · **覆盖率 55/55** ⇒ 结论行："三条主线文件级零交、且覆盖全部计划文件 ✓"。

| 线 | glob（逐条） |
|---|---|
| **A** | `agentflow/ui/**` · `webui/__init__.py` · `webui/server.py` · `webui/routes.py` · `webui/state.py` · `webui/views.py` · `web/assets.py` · `web/emit_theme.py` · `web/emit_types.py` · `web/static/**` · `cli.py` · `tests/test_webui.py`（既有）· `tests/test_release_all.py`（既有）· `docs/READING-MAP.md` · `docs/USER-END-DSH-STYLE.md` · `README.md` · `docs/INDEX.md` · `ui/README-DEV.md` ＋ §2.1 的 A 线 3 条新判据 |
| **B** | `webui/readers.py` · `webui/sse.py` · `sessions.py` · `userio.py` · `tests/conftest.py`（既有 · J2/K2 夹具落点）＋ §2.1 的 B 线 3 条新判据 |
| **C** | `webui/writes.py` · `webui/audit.py` · `settings.py` · `pyproject.toml` · `tools/release_all.py` · `src/agentflow/web-actions.example.jsonl` ＋ §2.1 的 C 线 3 条新判据 |

### §2.1 本表里**尚未建**的判据文件（9 条，逐条一行；归哪条线就由哪条线建）

> 单列一节的用处：所有权表里不再把"盘上有的"和"计划要建"混在一行 —— 上表每一行剩下的 `tests/` 条目都是**盘上真有的文件**（`tests/test_webui.py` 17 条用例、`tests/test_release_all.py`、`tests/conftest.py`），下面这 9 条是**计划新增**、当前盘上不存在。判据的描述照抄 `draft/73 §3` 与 `draft/75 §3` 的表，不另起说法。

**A 线（骨架与前端）**
- 计划新增 `tests/test_webui_contracts.py` —— 判据 **A 端点对齐 / B 事件对齐 / C 类型对齐 / D 路由对齐 / G 生成物新鲜度**，每条带负控（删一个端点、加一个 `EVENT_KINDS`、后端多一个键、页面用一个 C1 没有的端点、手改生成物 ⇒ 必红）；W0 新建
- 计划新增 `tests/test_webui_static.py` —— 静态路由 + content-type + 哈希缓存 + **dist 新鲜度**（node 缺 ⇒ 记 `unknown`，三态不许记 pass）；W0 新建
- 计划新增 `tests/test_webui_pages.py` —— 每页一条：该面的真读数出现 + 空态 + 三态；W1 新建

**B 线（只读面与索引）**
- 计划新增 `tests/test_webui_readers.py` —— 六个适配器各一条正控（造数据 ⇒ 读到）+ 一条负控（空工作区 ⇒ `unknown`，不是 `0`）；W1 新建
- 计划新增 `tests/test_webui_sse.py` —— SSE 五条（含端到端"盘上新增 ⇒ 流里出现"）；W2 新建
- 计划新增 `tests/test_run_index.py` —— 判据 **F 索引对账**：手改索引一个字节 ⇒ 必红；删一场会话而索引还在 ⇒ 报 `drift`；W1 新建

**C 线（写面与设置写面）**
- 计划新增 `tests/test_webui_writes.py` —— 授权矩阵 + 审计 + **不许绕闸门**的负控；W3 新建
- 计划新增 `tests/test_webui_settings_write.py` —— key 只写不读 / 原子写 / 权限 / 不回显（含扩展的 `_key_echo_problems`）；W4 新建
- 计划新增 `tests/test_webui_browser.py` —— Playwright opt-in（`-m browser`）；W4 新建

**两条边界要说清**（免得读成"随手划的"）：
1. `tests/conftest.py` 归 **B**（J2/K2 两份夹具住在那里）⇒ **A/C 不许改它**；A/C 要造夹具就造在自己文件的局部 fixture 里。
2. `docs/*` 与 `README.md` 归 **A** ⇒ B/C 需要文档改动时**写进自己的报告**，由 A 线或主控统一落（否则三条线会在同一份文档上撞车）。
3. **`.gitignore` 归主控、不在任何一条线里**（这张表只列"线内产出物"；`.gitignore` 与 `temp/` 下的探针是主控的账）。**实测教训**：W0 线在自己的工作树里也动了 `.gitignore`（加 `node_modules/`）—— 说明"没写进表"的文件照样会被碰，所以合并时这条由主控**整份取 master 版**再重跑生成器，不逐行合（见 §5 冲突预案）。
4. **有一处"表主是 B/C、但 W0 先建空壳"**：`webui/readers.py`/`webui/sse.py`（B 的）与 `webui/writes.py`（C 的）是 §3 那三条接缝的**导入目标** —— W0 必须先把它们建成"只有 `ROUTES`/`EVENT_KINDS`/`type_decls()` 的空壳"，`routes.py` 才导入得动。所以本表的口径是**"W0 之后谁改"**：空壳由 A 建、**之后只有 B/C 各自改自己那个**。这条也是"零交能成立"的一部分，写在 §3 的追记里有两边的读数。

---

## §3 三条共享约定（"零交"能成立的技术前提）

| # | 约定 | 谁在 W0 落地 | 之后 B/C 怎么做 |
|---|---|---|---|
| 1 | **路由子表**：`routes.py` 一开始就写 `from .readers import ROUTES as READER_ROUTES` 与 `from .writes import ROUTES as WRITE_ROUTES`（初始为空元组），再拼成总表 | A（W0） | B/C 只在**自己的模块**里往 `ROUTES` 加表项 ⇒ **不改 A 的文件** |
| 2 | **类型子表**：`emit_types.py` 调 `webui.state.type_decls()` + `webui.readers.type_decls()` + `webui.writes.type_decls()` 再拼成 `ui/src/types.ts` | A（W0） | B/C 各自在自己的模块里写 `type_decls()`（返回自己那些接口的 TS 文本） |
| 3 | **事件对齐**：`EVENT_KINDS` 由 **B** 定义在 `sse.py`；前端 `sse.ts` 的注册由 **A** 跟着改 | B（`sse.py`）+ A（`sse.ts`） | 两侧靠契约判据 **B（事件对齐）** 钉死：集合不等就红 |

> 约定的代价：类型与路由的"总表"在 A 线手里，A 线的 `routes.py`/`emit_types.py` 一旦改动拼接方式，**三条线都要重跑契约判据**（这是这套拆法唯一的耦合点，写在 §5 的合并协议里）。

> **实测追记（2026-10-07，主控核盘；已处置）**：W0 线**先于本文档开工**（基线 `65746a5`），所以它当时不知道这三条约定 —— 我在它的工作树里 grep 过，`READER_ROUTES`/`WRITE_ROUTES`/`type_decls` **一个都没有**（`routes.py` 当时是一张单表，`webui/readers.py` 还不存在）。这正是"设计与施工错位"的典型：**文档说 W0 落，W0 却已经在跑**。
> 处置：已 steer W0 补这三条接缝，**且已补上（同一工作树上的复查读数，尚未提交）**：
> `routes.py:47-48` 导入 `READER_ROUTES`/`WRITE_ROUTES`、`:81` 用 `compose(_OWN, READER_ROUTES, WRITE_ROUTES)` 拼总表；
> `readers.py`（4209 B，空壳占位 · `:32 __all__` 含 `ROUTES`/`type_decls`、`:69 def type_decls`）与 `sse.py`（1493 B）已建；
> `state.py:596` / `writes.py:63` 各有 `type_decls()`，`web/emit_types.py:83` 把三者拼成 `ui/src/types.ts`。
> **待回填**：合并进 master 后再核一次这三条（工作树读数不算落地），以及"往 `readers.ROUTES` 塞一条 `api.ts` 没有的路径 ⇒ 契约 A 必红"的那条负控。
> **退路（若最终没落）**：把 §2 的"零交"改成"按序合并 + `routes.py`/`emit_types.py` 由主控统一落"，并同步改 `temp/_check_line_ownership.py` 的读数口径 —— **不许**留一个假的"零交"说法在文档里。

---

## §4 依赖与开工顺序

```
W0（A 线，已在跑：line-w0 / temp/wt-w0，基线 65746a5）
   │  交付：webui/ 包结构 + routes 拼接 + emit_types/emit_theme + ui 骨架 + dist + 契约判据 + 两个 CLI 开关
   ▼  主控合并 + 全量门（约 18 分钟）
   ├──────────────► B 线开工（readers / run_index / sse.py / 夹具）        ┐
   └──────────────► C 线开工（writes / audit / settings.write_settings）  ┘ 两条线并行，文件零交
        │
        ▼  A 线继续：W1 六页面（吃 B 的 JSON 端点）· W2 前端 SSE · W5 旧壳清理
        │
        ▼  主控按序合并（见 §5）→ 每轮合并后跑门 → W4 的 G2 patch 交人签
```

**为什么 B/C 要等 W0 合入**：它们都依赖 `routes.py` 的**拼接形态**与 `emit_types.py` 的**子表协议**；W0 没落地就并行，等于三条线各自猜一个接口，合并时必然返工（那不是"零交"，是"零交但接口对不上"）。

**W0 合并前先过一道"公开面不变"的对账**（主控做，不比 18 分钟门便宜但**比返工便宜**）：
```powershell
# 拆包前（已完成：master 65746a5 上抓到基线）
python -B temp/_verify_w0.py capture     # → temp/_w0_public_face.json
# 拆包后（W0 分支上，或合并进 master 后）
python -B temp/_verify_w0.py check
```
它量的是**同一个真实工作区**（`agentflow/projects/p9b-post-fix-replay`）上的同一批读数：模块级公开名 + 签名（8 个）· `snapshot()` 顶层键（10 个）与各层键并集 · 源码里的 URL 字面量集合（5 条）· `render_root`/`render_run` 的**页面形状**（class 集与标签计数；**不比字节哈希** —— 页面带 `generated_at` 与"N 分钟前"，哈希必然漂移）。
**基线（2026-10-07 实跑）**：`render_root` 29699 字节 / 17 个 class；`render_run` 97712 字节；`public_names` 8 个（`WebHandler` `answer_text_of` `option_view` `render_root` `render_run` `run` `serve` `snapshot`）。**自检**：连着跑两次 `capture`+`check` 全同 ⇒ 这把尺子本身是稳的。

---

## §5 各线收工门与合并协议

**线内**（每条线自己跑，不占主控的 18 分钟）：
```powershell
cd <该线 worktree>\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="<该线 worktree>\agentflow\src"
python -B -m pytest -q -p no:cacheprovider -p no:randomly <该线的判据文件> 相邻文件
python -B scripts/lint_rules.py          # 必须 error 0
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_webui.py   # 现有 17 条
```

**主控**（我）：
1. 按 **A → B → C** 的顺序合并（A 的结构是另两条的地基；B 与 C 之间没有先后）；
2. **合并 A（W0）时先跑 `python -B temp/_verify_w0.py check`**：公开面硬读数变了就**不合并**（先查是谁动的），页面形状变了要把长度差打出来人判；这一关过了再进 `git status` 核对 → 全量门；
3. 每轮合并后：`git status` 核对只有预期改动 → 跑 `python -B temp/_merge_gate.py --with-pytest`（逐节读数看报告）→ 若两轮挨得近，允许"两轮一次门"，但**两次的改动面必须都在门覆盖内**；
4. **改前端 ⇒ 先 `pnpm build` 提交 dist，再跑门**（B1）；golden 只在必要且一次性时重冻（逐格归因 `draft/64 §8.12`）；
5. 冲突预案（真撞了怎么办）：**撞在 A 的文件上 ⇒ B/C 让 A**（A 的结构先定）；**撞在 `conftest.py` ⇒ 别人让 B**；**撞在 docs ⇒ 统一由 A 落**；**撞在 `.gitignore` / `temp/` 探针 ⇒ 取 master 版 + 重跑 `temp/_gen_cited_ignore.py`**（不逐行合：那条生成块的整体一致比任何单行都重要）；**撞在 `draft/` ⇒ 主控自己写**（三条线只读 draft）；任何一条"让"都要在 `draft/77 §1` 台账里留一行。

---

## §6 与 `draft/77` 台账的对应（W1–W5 怎么落到三条线上）

| 批次 | 主要归线 | 另一条线的部分 |
|---|---|---|
| W0 | **A** | — |
| W1 | **A**（六页面）+ **B**（readers / run_index / 夹具 / L1） | C 不参与（写面在 W3） |
| W2 | **B**（`sse.py`）+ **A**（`sse.ts` 与页面接线） | — |
| W3 | **C**（三件写面 + 审计 + 授权） | A 提供 `--allow-writes` 透传（W0 已给） |
| W4 | **C**（设置写面 + 浏览器判据 + G2 patch） | **A** 落文档（`USER-END-DSH-STYLE.md`/`README.md`/`INDEX.md`） |
| W5 | **A**（旧壳清理 + 收尾门） | B/C 只需要"确认自己的模块没引用旧函数" |

> **这套拆法的一个副产品**：`draft/77 §1` 的台账从"按批次"变成"按批次 × 线"两维 —— 每行记"谁在做、落在哪个 sha、读数是什么"，主控一眼能看出哪条线落后。

---

## §7 三条线的开工简报（交给子代理的唯一施工说明书）

三份都在 `temp/`，都是**可独立执行**的：自己说清"只许碰哪些文件、每件做什么、怎么算做完、报告怎么写"，不需要读主控的对话。

| 线 | 简报 | 覆盖批次 | 关键约束（简报里逐条展开） |
|---|---|---|---|
| **A** | `temp/_line_A_brief.md` | W0（已跑）· W1 页面 · W2 前端 SSE · W4 文档 · W5 旧壳清理 | 21 条 glob；端点契约 11 条 / 事件 kind 6 个的口径；`pnpm build` ⇒ 提交 dist |
| **B** | `temp/_line_B_brief.md` | W1 readers/夹具 · O2 索引 · L1 收敛 · W2 后端 SSE | 8 条 glob；三态不许塌成二态；索引与事件对账两条负控 |
| **C** | `temp/_line_C_brief.md` | W3 写面 + 审计 · W4 设置写面 + 浏览器 + G2 patch | 9 条 glob；授权矩阵四态；key 只写不读三处读数；**禁改区只出 patch** |

**写简报时真撞出来的两件事**（都留了痕，不是凭空）：
1. **`.gitignore` 不在任何一条线里，但 W0 线实际动了它** ⇒ 归属与合并办法补进 §2 边界 3 与 §5 第 5 条。
2. **`browser` marker 与 `addopts` 不一致**（`agentflow/pyproject.toml:69` 只排 `network`，而 `draft/77 §2.2` 的 marker 描述写着"默认排除"）⇒ 挂成新待裁 **T1**，收在 `draft/79-待裁清单（Web施工中新冒出）.md`，C 线简报里写明"等裁，别自己拍"。

**简报里出现过的、我核过的口径**（免得子代理拿"简报转述"当事实）：本仓**没有** `tests/test_userio.py`（userio 的相邻判据在 `tests/test_sid_scoped_questions.py` 等）；`run_index` 这个名字在 `projects.py:242` **已经**表示"项目第几趟"（配 `projects.py:309 _next_run_index` 与 `out/run-<n>`），与裁定 O2 的"会话内趟次索引"**不是一回事** —— B 线简报里专门有一条提醒，不许改名、不许混用。
