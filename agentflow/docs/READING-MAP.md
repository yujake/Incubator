# 读代码的入口：七层 + "想改什么 ⇒ 读哪几个文件"

> **这份文件回答一个问题：我现在要改的东西，代码在哪、判据在哪。**
>
> 起因（`draft/36` §3）：`src/agentflow` 里文件多、单文件大。**当次读数（观测 2026-10-13
> （`paper_package` 整条退场后复算），
> 口径：`src/` 下全部 `*.py`（`__pycache__` 不在里面），逐文件 `read_text().splitlines()` 求和）：
> **211 个 `.py`、125,026 行**，**45 个文件超过 800 行**（**全仓最大的是 `agent_loop.py`，5,988 行** —— 批 R40 把它补进了 §3 的表；
> §3 那张表里最大的一行是 `schema.py`，逐文件行数见那张表）。
> 复跑命令（三格一次打全）：
> `python -c "import pathlib;fs=sorted((pathlib.Path('src')).rglob('*.py'));L=[len(p.read_text(encoding='utf-8').splitlines()) for p in fs];print(len(fs), sum(L), sum(1 for n in L if n>800))"`
> 新人打开任何一个文件都是一本小册子，
> 于是"从哪读起"本身成了一道门槛 —— 这份图就是为了把这道门槛拆掉。
> （本行原先写"188 个 `.py`、98,217 行、37 个文件超过 800 行"（观测 2026-10-06），
> 再原先写"77 个文件、77,391 行、38 个文件超过 800 行"，都过期了 ——
> 批 R27 按现算改正并把复跑命令写进这一行；**批 R46 又改了一次行数**：
> 123,924 → **123,931**（动的是 `agent_prompts.py` 的 `p95` 变更，净 +7 行 ——
> 这个数会被 `temp/_probe_doc_vs_code.py` 的 ③ 抓住，见 `draft/108` §三 的常驻探针那一段）；
> **批 R47 再改一次**：123,931 → **123,991**（`llmseam.py` 补 `framework_handoff` /
> `framework_interrupt` 两个广告面与 `framework_final.blocked` 的透传，净 +60 行）；
> **批 R48 再改一次**：123,991 → **124,026**（`llmseam.py` 补派活那一栏的
> `DISPATCH_NOTIFY_JSON_SCHEMA` 并挂到 `framework_summon` / `framework_summon_many`，
> 净 +35 行）；**批 R52 再改一次**：124,026 → **124,044**（工具层改
> `doc.paper_render` 的摘要 + `agent_prompts.py` 的纸包两处，净 +18 行）；
> **批 R54 再改一次**：124,044 → **124,068**（CS-10 ② 的产出即登记 + 四处 `specs/` 的文本，
> 净 +24 行）；**批 R56 再改一次**：124,068 → **124,112**（纸包第六节的删减 + G/H 版的
> 第八节整块替换，净 +44 行）；**2026-10-13 再改一次**：125,256 → **124,829**
> （`paper_package` 整条退场：删 `renderanchor` / `paperbuild` / `agent_g/paper_package`
> 三个模块、加 `papercompile.py`，净 −427 行；三格里的文件数 213 → **211**，`>800 行` 仍是 44。
> **2026-10-13 R72 收尾再改一次**：124,829 → **124,841**（净 +12 行：改掉三条被全量套件抓出来的
> 陈旧读数 —— `capabilities.py` 里被 `test_r4_roles_surface` 逐字比对的那句对账读数、
> `tools/doc_tools.py` 的成功支从 `ok(body)` 改成字面量键表；文件数 211 与 `>800 行` 的 44 都不变。
> 复算命令就是上面那一条）。
> **退场的那三个模块名这里刻意不写 `.py` 扩展名**：本图自己的判据要求图里每个像文件名的
> token 都在盘上真的存在，写全名会让那条判据红 —— 而它们确实已经不在盘上了）。）
>
> **它自己也有判据**：`tests/test_reading_map.py` 会断言
> ①图里提到的每个文件名都真实存在；②`src/agentflow` 的每个模块至少在这张图里出现一次
> （不许有"孤儿文件"）。所以图不会烂成过期文档。

---

## §0 三条使用规则

1. **先看"谁是权威"再看实现**。这个仓库里同一件事的**声明**与**实现**常常分处两个文件
   （声明：`capabilities.py` / `schema.py` / `AGENTS.md`；实现：`agent_*.py` / `store.py`）。
   改之前先问："这条规则的权威定义在哪？"——§2 的表里"先读"那一列就是它。
2. **每个结论都要落到一条会红的判据上**。§4 给"哪一类判据在哪个测试文件"。
   找不到判据的改动 = 改完没人拦。
3. **禁改区先看 `AGENTS.md`**。清单在 `AGENTS.md` 与 `.noai-paths` 两处，必须逐条一致；
   命中就要 2 名 reviewer（`scripts/noai_gate.py` 是机器判据）。

---

### §0.1 已知欠账（可见地记着，不许静默）

- **`ocr.*` 三件（`ocr.detect_text_layer` / `ocr.backends` / `ocr.run`）—— 已接线（2026-10-07）。**
  **接线前的欠账**（2026-10-07 02:2x）：只有角色 B 的工具面拿得到这三件，而 `agent_b/core.py` 的抽取链撞到
  "无文本层"时直接放弃（`_load_doc_for` 里那句「无文本层（扫描版？）⇒ 无从逐字定位」），从不调它们
  ⇒ 文档在教一个生产面没人调的工具。
  **接线的落点**：`agent_b/core.py` 的 `_load_doc_for` ⇒ `_ocr_retry`（经**工具面**调 `ocr.backends` /
  `ocr.detect_text_layer` / `ocr.run`）—— 无文本层 ⇒ 先试 OCR ⇒ 重新抽取 ⇒ 仍空才回原来那句原因，
  且原因要能区分"没试 OCR"与"试了 OCR 还是没有"。
  **接线后的真机读数**（`temp/_r2b_ocr_probe_after.txt`，2026-10-07）：真机扫描件
  `projects/project5/library/扫描件.pdf`（6.5 MB）上 `_load_doc_for` 返回的不可用原因是
  「文献 0000 无文本层，**且本机没有可用的 OCR 后端（unavailable）**⇒ 无从逐字定位」——
  本机 `ocr.backends` 报 `available: []`（easyocr 因 torch/numpy 不兼容不可用、pytesseract 缺 tesseract
  可执行文件），`ocr.detect_text_layer` 报 `has_text_layer: False | source_kind: pdf | pages: 0 | chars: 0`。
  即：这条路径**真的被走到了**，且"没试过 OCR"与"试了、后端不可用"在原因里分得开。
  **两版读数并列**。**口径逐字写死**（免得下一个人按"出现处数"去数、数出第三种结果）：
  数的是**含 `ocr.` 的「行数」**（不是匹配总数 —— 同一行出现多次只算一行），
  `src` 递归 `-Recurse`、`docs` 只算顶层 `.md`。**在 `agentflow/` 目录下跑**（本文档所在目录）：
  ```powershell
  (Get-ChildItem src  -Recurse -File -Filter *.py | Select-String -Pattern 'ocr\.' | Measure-Object).Count
  (Get-ChildItem docs -File -Filter *.md          | Select-String -Pattern 'ocr\.' | Measure-Object).Count
  ```
  | 时刻 | `src/**/*.py` | `docs/*.md` 原始 | 本条自身 | `docs` 扣除本条 |
  |---|---:|---:|---:|---:|
  | 接线前（2026-10-07 02:2x） | 56 | 39 | 0（本条当时还没写） | 39 |
  | 接线后（2026-10-07，A 落地并复核后） | 68 | **47（测于 2026-10-07 02:47）** | **8（同刻）** | **39** |
  「原始」与「本条自身」两格是**自指**的（改这一条，它们自己就变）⇒ 它们各带**测量时刻**：
  上面那两个数是 **2026-10-07 02:47** 测的。**净数 `39` 是可复算的稳定量**（只要 `docs/` 别的文件不动），
  下一个读者按上面的命令数出别的数时，看时刻就知道那是本条改写前的读数。
  docs 明细（接线后，同一口径，测于 2026-10-07 02:47）：`ROLE-SPECS.md` 18 · `PROPOSALS.md` 12 · `READING-MAP.md` 8 · `PROPOSAL-side-effect-axes.md` 7 · `TOOLBOX-DRAFT-roles.md` 2。
  **读这张表时要知道四件事**（否则会把数读歪）：
  ① 唯一干净的接线前后对比是 `src` 一列：**56 → 68**（+12 = 接线新增的引用；`agent_b/core.py` 里 `ocr.` 现为 14 行）；
  ② `docs` 侧的 **+8 全部是本条目自己**（这一条本身就在讲 `ocr.`）⇒ **扣除本条后 39 → 39，无净变化** ——
  所以 `docs` 那一列**不能当接线效果的读数**，它只证明"文档侧没有因此多出/少掉别的引用"；
  ③ 本条目自身的 8 行是**同一口径下的行数**；它还会随这条被改写而变（**这个数只在本条定稿的那一刻成立**），
  所以引用本表时请连口径与时刻一起引；要现值就用上面那两条命令重跑；
  ④ 旧记的「44 → 53 处」口径不明，**本条目一律以本口径为准**；历史读数**不改成现值**
  （按主控判例：带日期、带口径的历史读数保留原样）。

---

## §1 七层与它们各自的文件

层与层之间是**单向**的：上层可以读下层，下层不反向 import 上层。
括号里是这个文件存在的理由（取自它自己的模块 docstring）。

### 第 0 层 · 入口

| 文件 | 是什么 |
|---|---|
| `cli.py` | 命令行入口（24 个子命令；`project`/`run`/`run-agent`/`verify`/`tools`/`web`/`doctor`…） |
| `webui/` | 用户端网页（包；2026-10-07 的 W0 从单文件模块一次拆到位）：`webui/state.py` 是**读模型**（`snapshot()`：全局待回答面板 + 运行态 + 一趟的事件回放，只读投影；待答与选项按裁定 L1 转发到 `userio`）、`webui/readers.py` 是**只读面**（`/api/state` · `/api/run/{sid}` · `/api/run/{sid}/events`（题 T2-a 的逐条事件：`index` 与 `run_view` 的 `start_index`/`end_index` 同一套编号，`since_index`/`limit` 游标分页） · `/api/evidence` · `/api/artifacts` · `/api/acceptance` · `/api/machine`，各带三态头）、`webui/sse.py` 是 `GET /api/stream` 的广播器 + 写路径钩子（`attach`/`detach`，谁开的代谁接 —— 生产路径在 `server.serve()`）、`webui/writes.py` 是唯一写路径（`POST /answer` → `userio.answer_question`）与它的写面、`webui/routes.py` 是路由表 `ROUTES`（= `_OWN` + `readers.ROUTES` + `writes.ROUTES`）、`webui/server.py` 是 http.server + 静态路由 + 两条页面入口（`/` 与 `/run/{sid}`）的 SPA 外壳 + SPA 回退 + 服务器自己写的那几张错误页；服务端渲染的旧壳已在 W5 清仓（裁定 P1 的两面都迁到 SPA 外壳，那个文件整件退场）；公开面由 `webui/__init__.py` re-export（W5 收窄：旧壳的两个渲染入口随之退场） |
| `settings.py` | **机器级设置的一处定义**（2026-10-07 起）：落点（默认是 `agentflow/` 下的那份，被 git 忽略；`AGENTFLOW_SETTINGS` 指到别处）、键名（`toolchain.*` / `model.*` / `workspace.projects_dir`）与**唯一口径的优先级**（环境变量 > 设置文件 > 内置默认/自动探测，唯一实现 `env_or_setting`）。为什么要有它：本机路径与模型 key 此前散在"代码里的字面量 + 环境变量"两处 —— 换一台机器就有一句假话。判据 `tests/test_settings.py`（含"源码里 0 条死地址"与三道 key 安全阀） |
| `budget.py` | 可追加的总预算：盘上寄存器（工作区根下那一个 JSON）+ 每次花钱前现读的口子 —— 花销不在这里（唯一权威账是 `usage_ledger`） |
| `toolchain.py` | 这台机器上的证明工具链（一处定义）：显式配置（`AGENTFLOW_LEAN_BIN` 等）→ `AGENTFLOW_PROVER_PATH`（两者都是环境变量）→ **设置文件的 `toolchain.*`** → PATH 四档查找 + 三态探测 + Mathlib 那一轴；探测（禁改区的 `verify_tools.detect_verifier`）与调用（`formalgw.find_lean`）共用这一个答案，`agentflow doctor` 把读数打给人看（打的是"从哪一档找到的"） |
| `web/` | 网页的样式与令牌：DSH 的令牌整份照搬（来源与 MIT 见 `docs/USER-END-DSH-STYLE.md`）；`web/assets.py` 是令牌的唯一真身（**我们自己的组件样式在 W5 随旧壳退场，搬到了前端工程的 `ui/src/theme/app.css`**）、`web/emit_theme.py` 把它生成到前端；`web/static/` 是**前端构建产物**（裁定 B1：入库；`index.html` + `assets/*.js|css`，`GET /` 与 `GET /run/{sid}` 吐的就是它） |
| `ui/` | 用户端前端工程（Preact + Vite，裁定 A2）：源码在 `ui/src/`（九页 `pages/*.tsx` · 六组件 `components/*.tsx` · `main.tsx` 路由 · `api.ts` 端点表 · `sse.ts` 订阅 · `live.tsx` 一次订阅分发给九页 · `theme/app.css`），其中 `ui/src/types.ts` 与 `ui/src/theme/generated/theme.css` 是生成物（`python -m agentflow.web.emit_types` / `python -m agentflow.web.emit_theme`，手改必红）；构建产物落到 `src/agentflow/web/static/` 并按裁定 B1 入库；开发说明见 `ui/README-DEV.md` |
| `__main__.py` | `python -m agentflow` 的入口 |
| `__init__.py` | 包说明与公开面 |
| `demo.py` | 离线端到端演示：不访问网络，把 A→B→校验整条链路真跑一遍 |
| `console.py` | 把 CLI 的输出编码钉在 UTF-8 上 —— 这一件事只有一份实现 |
| `tty.py` | 终端呈现层（统一、好看、在任何终端都不崩） |
| `userio.py` | 用户频道：向用户提问、等回答、"没答"这一档三态 |

### 第 1 层 · 数据面（磁盘契约）

| 文件 | 是什么 |
|---|---|
| `schema.py` | 数据模型与校验（**表的权威定义**；禁改区） |
| `store.py` | 共享存储：跨进程锁、原子写、事务、事件日志、ID 分配、重建（禁改区） |
| `canonical.py` | 规范 JSON 字节串 —— 唯一实现（判定"同一份数据"的前提） |
| `jsonlfile.py` | JSONL 文件的读法 —— 唯一实现（`draft/36` T-6：三处曾各写一份） |
| `sessions.py` | 按项目存放的会话记录 |
| `fulltextstore.py` | 抽取正文的内容寻址库：整本书的正文只存一份 |
| `signatures.py` | 稿件内容的规范哈希 |

### 第 2 层 · 声明面（"谁能做什么"的权威定义）

| 文件 | 是什么 |
|---|---|
| `capabilities.py` | 角色能力表 + 写集 + 允许的召唤边（**A–H 调用矩阵的权威定义**；禁改区） |
| `agentspec.py` | **一个 agent 的声明**（`AgentSpec`/`AgentBrief` + 注册表）：职责与门面、官能轻重、只读与否、能召唤谁、写集、实现类。每个角色在自己的模块里写一份 `SPEC`；装配面正在从它读（`goal-7f5116c1` 的 M2/M3/M4，对账判据见 `tests/test_agent_spec_reconciliation.py`） |
| `specs/<角色>.py` | **角色动作表的真身**（`goal-7f5116c1` M3）：一个角色一个文件，`ACTIONS`（动作表，逐条 `ActionSpec`）+ `SPEC`（职责与门面、官能轻重、边、写集、实现类）。`capabilities.py` 的四张表**从它派生**，`agent_<角色>.py` 只是再导出 —— 这一包在 `.noai-paths` 里受保护（改它等于改权限面） |
| `policy.py` | 策略层：允许哪些召唤、四类上限 |
| `interactions.py` | 跨智能体交互的冻结契约（I1–I7）（禁改区） |
| `verify.py` | 全局不变量校验（表与表之间的一致性；禁改区） |
| `gates.py` | H 的 G1–G15 门引擎 —— 15 道独立、有名字、可单独查询的检查器 |
| `stopctl.py` | 停机的唯一实现（`draft/37` §128）：停机开关（`.agentflow-stop`）+ 子进程登记（`runs/<role>-<sid>.pid`）+ 优雅停止与强制停止（`taskkill /T /F` 连子孙）。为什么要它："用户叫停"这条通道此前只在多轮路径存在 —— 单趟 `run-agent` 里叫停之后它继续跑到第 123 步；而 E 的实验子进程会把 600 s 跑满（开关落盘后 0.2 s 内被终止） |
| `refusals.py` | 角色动作的「拒绝」只有一个形态（`draft/37` §88）：`refuse(kind, error, **extra)` 造出 `ok=False` + 受控 `refusal_reason` 的那一笔。为什么要它：终态映射原先只看"handler 有没有返回 dict"，于是 `ok=False` 被记成 `outcome=ok`（T1 第 2 趟真机：8 次拒绝在台账上像 8 次成功，而 `statements` 是 0 行）—— 现在声明了受控理由的落 `refused`，没声明的落 `failed`，两者不再同形 |
| `manuscripts.py` | **交接手稿**的唯一实现（`draft/37` §134 用户口径 + `draft/39` §C1 存储改追加式）：账本 `handoffs.jsonl`（在 `manuscripts/` 下）**一行一份交接**（`to`/`summary`/`body` 必填），编号从 `0000` 起**由脚本在锁内分配**（扫"账本行 + 旧 `.md` 文件"的并集），并发写不撞号不覆盖；旧格式 `<编号>-<谁>to<谁>.md`（给所有人写 `toALL`）仍然读得回来但不算账本行。为什么要它：交接的"派活依据"与"溯源"此前只活在对话里 —— 写了手稿之后每一跳都能被第三方从盘上复核。写走循环形状 `handoff`（要知道"我是谁"，而工具层拿不到 per-call 身份），收工时的强制 `notify` 表也走它；读/列走 `tools/manuscript_tools.py`（A–H 八面，M 用 `fs.*` 白名单读同一批文件），按编号/收发/时间/引用检索走 `scripts/manuscripts_query.py`（顺手打被引用命题的五元位快照） |

### 第 3 层 · 工具面（角色手上的"手与眼"）

| 文件 | 是什么 |
|---|---|
| `tools/__init__.py` | 工具层装配（按角色组装 `ToolRegistry`；禁改区） |
| `tools/base.py` | 工具层基座：`ToolSpec`/`ToolResult`/`ToolRegistry`/参数校验（禁改区） |
| `tools/table_tools.py` | 表 CRUD（共用数据面原子动作） |
| `tools/fs_tools.py` | 文件 CRUD（共用，沙箱在工作区内） |
| `tools/search_tools.py` | A 专用：provider 探测 / 检索 / 下载 / 判重检查 / 文献登记 |
| `tools/ocr_tools.py` | B 专用：后端探测 / 文本层判断 / 按页 OCR |
| `tools/graph_tools.py` | 图索引与查询（纯读） |
| `tools/trace_tools.py` | 代号溯源（纯读） |
| `tools/research_tools.py` | D 专用：研究问题台账 + 知识缺口提问 |
| `tools/verify_tools.py` | E 的工具：数值实验与形式化验证（禁改区） |
| `tools/attack_tools.py` | F 的工具：多轮难题攻坚 |
| `tools/conjecture_tools.py` | 猜想台账的产出面 |
| `tools/doc_tools.py` | G 的工具：论文撰写 |
| `tools/review_tools.py` | H 的工具：审校 |
| `tools/conductor_tools.py` | 主控工具：给 M 配手与眼（派活 / 台账 / 停止 / 状态） |

### 第 4 层 · 角色面（九个角色各自的一本账）

| 文件 | 是什么 |
|---|---|
| `agent_a/`（包） | A：文献搜索（唯一带网络副作用的角色）；`goal-7f5116c1` M7 起：一个动作一个文件 |
| `agent_b/`（包） | B：文献整理（抽取概念与关系，引文逐字回验）；M7 起同上 |
| `agent_c/`（包） | C：关系分析（程序做分析，LLM 只做排序与措辞） |
| `agent_d/`（包） | D：研究循环（**最大的角色**，见 §3） |
| `agent_e/`（包） | E：数值实验与形式化验证 |
| `agent_f/`（包） | F：多轮难题攻坚 |
| `agent_g/`（包） | G：论文撰写 |
| `agent_h/`（包） | H：审校（只读） |
| `agent_v/`（包） | V：**证明级验证**（只读，`draft/39` §3.21 一/五/六）：把 F 交回来的证明按写成后的样子整体重读，给三态结论（`成立`/`有毛病`/`看不出来`）并签五元位第 3 位；`agent_v/core.py` 的 `AgentV`（三个动作：`verify_proof`/`list_verifications`/`read_proof`）+ `agent_v/__main__.py` 的自检入口（`python -m agentflow.agent_v`，16 条 `[PASS]`）。声明真身在 `specs/v.py`，读写在 `verifications.py` |

> 九个角色（除主控 M）的包形状是一样的（`goal-7f5116c1` M6/M7 + F-02 的 V）：入口 `__init__.py`、
> 其余成员与 mixin 组装在 `agent_a/core.py` 这样的 core 模块里、模块级 helper 与常量在
> `agent_a/_support.py`、一个动作一个文件（如 `agent_a/search_literature.py`）、
> `python -m agentflow.agent_a` 的自检入口在同目录的 `agent_a/__main__.py`。
| `agents` 的公共零件：`claimanatomy.py` | 断言解剖学 —— `documents.claims` 每个元素的唯一判据来源 |
| `claims.py` | 原子断言拆分（把一段答复切成可逐条回验的断言） |
| `jobobject.py` | 进程树治理（`draft/39` §3.21 五 I13，D03 的根因修法）：Windows **作业对象**（`KILL_ON_JOB_CLOSE`）—— `create_job`/`assign`/`assign_tree`（根 + 现有后代；作业归属**不向前追溯**）/ `grace_then_kill`（先宽限再 `TerminateJobObject`）/ `reap`/`close`；后代枚举走 Toolhelp 快照。`stopctl` 的强制停止优先走它（`via="job"`），`taskkill` 只作退路 |
| `attackround.py` | F 的**一轮真推理**形态（`draft/39` §3.16）：四种产物 `reduction`/`proof`/`counterexample_request`/`dead_end`（**没有 `no_change`**）、策略工具箱（每轮必填方法与理由）、#5 缝的两条合法出口（写出来 / 声明成前提）、花钱前的确定性闸门（I9）、缺陷继承（I11）、超预算的 `too_large`（I16） |
| `statusreport.py` | M 的**状态报告**（`draft/39` §4）：`collect()` **只读**四类读数（台账增量 / 交接链 / 在飞与卡点 / 拒绝与超时），`render_status_markdown()` 渲染成人读四节，`write_status_report()` 落 `out/review/STATUS-<ts>.{md,json}` —— 用户侧入口是 `agentflow status-report`（零模型调用、不打断任何循环；不是去问 M 一句） |
| `verifications.py` | 验证者 **V** 的证明级审校台账（`draft/39` §3.21）：`verifications/<命题号>.jsonl` 追加式一行一次审校（三态结论 `成立/有毛病/看不出来`、`defect_step`、逐条 findings 带步号、输入证明 sha）；`cold_start_prompt()` 是纯函数（签名里没有 store/conductor/registry ⇒ 冷启动是结构性质）；`signs_bit3()`/`bit3_payload()` 决定并产出五元位第 3 位的凭据 |
| `secretary.py` | **「秘书」**：每个智能体自带的随员（`draft/53` v3 定位 · `draft/55` 接口规范 · `draft/54 §2`）。它**不是一个同级角色**：不占 `schema.ROLES`、不加注册工具、不改权限面声明 ⇒ 一个计数都不变。四条职责（格式与内容优化 / 委派评估 / 委托加工 / 闭环提醒）+ 手稿通道的增改查（`handoff_add`/`handoff_rework`/`handoff_query`）+ **命题写入代理**（`wash_statement`/`record_statement`，业主 2026-10-09：B 交内容、秘书落盘——洗格式 / 拿编号 / 查重 / 改表四件，写集只有 `statements` 与 `dependencies`）；两条实质红线（格式补不全、或加工后发现实质缺陷）走 `negotiate()`（≤2 轮）+ 台账留痕 —— **它从不替本体表态** |
| `evidencebits.py` | 命题的**五元证据位**与派生等级（`draft/39` §3.14）：哪位角色欠哪一位（数值验证/有证明/审过/形式化通过/正式审查）、`na` 与"还没做"分得开的四态、等级**机械派生**（数值封顶在"强猜想"）、引用命题凭文献代号进第 2+3 位、作废四条缺一不可。另加**位 ⇒ 台账的映射**（`BIT_LEDGERS`：哪一位去哪张表查；`bit_evidence_gaps`：位上说有、表里要查得到）——业主 2026-10-09 点名的那一条。纯函数层：不读盘、不写盘，读入口是 `bits_from_row()`（收工门的 `reviewed_proof_rows` 与状态报告都走它） |
| `quoteverify.py` | 引文校验：引文级回验（禁改区） |
| `dedup.py` | 判重：文献 / 概念 / 关系（禁改区） |

### 第 5 层 · 循环面（模型自己决定调什么）

| 文件 | 是什么 |
|---|---|
| `agent_loop.py` | LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕 |
| `agent_prompts.py` | A–H + V（含 M）的前置提示词：身份、边界、政策、工具、伙伴、契约、三态、循环协议 |
| `agent_skills.py` | 各智能体的 skills（业主 2026-10-14「现做现读」）：目录 / 正文 / 索引只有 `CATALOG` 一处定义，正文由 `materialize` 落到工作区 `skills/<角色>/<slug>.md`，前置提示词里只出现 `index_block(role)` 那一小段；`validate()` 逐条核"动作真实存在且够得到、工具在该角色自己的面上、描述无歧义"（`draft/120` §②） |
| `llm.py` | 抽取层：`Extractor` 协议 + 离线基线 + 可插拔 `LLMExtractor` |
| `llmseam.py` | 统一的模型缝：一次模型调用 = 一条可审计的记录 |
| `judge.py` | LLM 判定的唯一缝协议 |
| `judges.py` | 语义判据的接入方式：注册表 + 三态 + 引用落地过滤 |
| `promptkit.py` | 提示词装配：有序段 + 变量 + 作用域遮蔽 + 动态上下文（快照那一类） |
| `persona.py` | 身份的两个具名槽位 + 唯一注册入口：部署那一份无条件注册、角色那一份靠同名遮蔽、`scope` 必填（学 DSH 的 `dsh-persona`；`draft/101` §3） |
| `presets.py` | 预设机制：目录 = 一个预设（`preset.<yaml>` + `agent.<宿主>.yml`，DSH 的 YAML 形状；两份的名字是常量 `PRESET_MANIFEST_NAME` / `COMPOSITION_NAME`）、根优先级、坏预设带理由、挂一次 + 生成戳、只许复制式创作、`!!js` 门落 conditional（学 DSH 的 `dsh-agent-presets`；`draft/101` §2） |
| `composition.py` | 预设的**接线层**：组装行名 → 解析函数（今天两行：`agentflow.text_blocks` 给写死的正文块、`agentflow.brief_blocks` 声明五格身份文本由真身 `specs/<role>.py` 渲染）、随包预设根 `agentflow/presets/roles/`、角色 id → 预设 id（小写化）、以及回落时的读数 `prompt_audit["preset"]`；约定只有一条：预设决定"写死的块由哪段文件给"，代码永远给现算的块（`draft/103` §4.1b） |
| `instructions.py` | 工作区指令通道：AGENTS.md 一类文件的发现 / 去重 / maxBytes 降级 / 转义 / 追加式状态（学 DSH 的 `dsh-agent-instructions`；`draft/101` §4） |
| `contextbudget.py` | 上下文预算：压缩 / 剪枝 / spill |
| `tokenestimate.py` | 固定密度估值器（S-B/12-H：DSH 常数 + `chars_per_token` 配置项） |
| `tool_timeout.py` | 逐工具超时：协作式截止 + 一张限时表（S-E/12-D/12-G） |
| `fs_observation.py` | 文件"读后写"的观测闸门（S-A/9甲：没读过就不许改） |
| `autonomy.py` | 自主轮次 + 周期汇报 |

### 第 6 层 · 编排与接线面

| 文件 | 是什么 |
|---|---|
| `conductor.py` | 主控编队：把"一次召唤"做成可审计、可拒绝、可取消、可重建的台账行 |
| `scheduler.py` | 调度：按写集互斥分波并发 |
| `host.py` | 主控接线：把 A–H 接到 `LocalBackend` |
| `runflow.py` | 端到端一条命令：给一个主题、一个美元上限，产出可复核的完整运行记录 |
| `pipeline.py` | 编排：把 A→B→C→D 串成可中断、可续跑、可审计的流水线 |
| `projects.py` | 项目工作区：一个项目一个文件夹，冷/热启动按"文件夹在不在"判定 |
| `locallib.py` | 把本地目录里的 PDF 灌进项目库（按内容 hash 幂等） |
| `cancellation.py` | 取消语义（四条纪律） |
| `faculty_checks.py` | 十项官能里"可机械判的那一半" |
| `deliver.py` | 交付前的判据闸门：逐项判据 + 机械半 → 结论、报告、派回去的工作项 |
| `closing.py` | 收工门（`draft/37` §16 P3）：**八格**各自一个三态读数（`closing.DEFAULT_CHECKS` 是权威清单）—— 论文那一格（回执里的 `tex_sha256` 与盘上那份 `main.tex` 的摘要对得上；没有 `main.tex` ⇒ 不适用，回执读不到 ⇒ 没查成）/ 无未裁决矛盾 / 承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题 / 实质产出（`documents`/`relations`/`experiments`/`review_findings`/`statements` 至少一张非空）/ 验收表的机器可判行 / 产物台账与盘上一致（`ARTIFACTS.jsonl` 逐条重算）。**工具 `conductor.closing` 与 CLI `agentflow closing` 都调 `closing.check_closing`（同一份实现、两个入口）**；`unknown` 不是通过 |
| `reviewaccept.py` | 审稿场景的**内容级**验收（`draft/37` §17.3）：报告九节且每栏有读数 / 定理台账每条有完整假设与出处页码 / 三态分支落盘可查 / 在成本上限内 / 每跳留下可读输入。**判据与辅助读数分栏** —— `sha`/页数/锚/行数那五种"容易拿到"的读数照原样给出，但**一个都不参与 `passed`** |
| `migrate_concepts.py` | `concepts` 并进 `statements` 的折叠内核与**迁移计划**（`draft/97` §10/§14/§15.2）：`plan_migration`（计划 = 折叠 + 关系改号 + 逐条落账 + 边界读数，真跑的那一笔照抄它）、`counter_alloc`（确定性发号替身，让预演与真跑的号逐条对得上）、`ledger_lines`（改号台账的行形状：`out/` 下那份 `migrate-map` 记录）、`fold_concepts` / `remap_concept_ids`（内核：概念号走同一分配器重发、定义待补标记、别名带过）。纯函数，不碰盘 |
| `conceptrows.py` | 并表**过渡期**概念行的唯一读写口（`draft/97` §10.3）：写的时候新标准（`statements`）先写、老表（`concepts`）照旧镜像且**两处同号**；读的时候合成一个视图（新标准优先，逐行标 `via="statements"/"legacy"`）；`legacy_present` 三态（表已退役而老文件还在 ⇒ `stale_file` 点名）；四个计数分开给（`merged` / `legacy_only` / `definition_only_in_legacy` / `statements`）—— 有了它，读侧可以一个一个搬到新标准，而"两边不同步"永远看得见 |
| `paperledger.py` | S1q **正文重建**（`draft/97` §9.5 + §16.1）：台账里的定理搬进论文正文时，逐字（①）、重写论文号（②）、带 `stmt:` 引用（③）、映射落 `dependencies`（④，字段组合照 §9.5 —— 只挂**手稿**那一端，"四选一"是硬闸），以及 `check_paper_ledger` 的五条判据（逐字 / 引用在 / 映射唯一 / **两个方向都判**：正文有而映射缺、映射有而正文没有、`\ref` 悬空 / 论文里不许引 `doc:`）。正文排版仍归人/模型 —— 这一层只判"搬进来的对不对得上台账" |

### 第 7 层 · 质量与产物面

| 文件 | 是什么 |
|---|---|
| `evidence.py` | 证据层：先检索、再逐字回验 —— 每条结论都落在某段真实原文上 |
| `artifacts.py` | 产物登记：谁在哪个路径产出了什么 |
| `papercompile.py` | 把智能体写好的 `out/paper/main.tex` 编成 `main.pdf`，并写框架自己的编译回执：判"这份 PDF 是不是盘上这份 tex 编的"（`receipt_matches_tex`） |
| `modelgw.py` | 模型网关：全仓唯一读 API key 的地方 |
| `modelclient.py` | 把 `modelgw` 适配成抽取层要的 `.complete(prompt) -> str` |
| `modelcost.py` | 模型花销入账适配器 |
| `tokenmeter.py` | token / 花销预算（硬约束，重试也计入） |
| `providers.py` | 文献检索 provider 层（禁改区） |
| `fetch.py` | 下载层：流式下载、原子落盘、限速重试、镜像回退 |
| `extract.py` | 文本抽取层：`extract_text(path) -> DocumentText`（禁改区） |
| `formalgw.py` | Lean 形式化验证后端 |
| `textutil.py` | 文本规范化、相似度、slug、页码解析 |

**仓库根还有四处不属于 `src/`，但改代码时会碰到**：
`agentflow/tests/`（判据）、`agentflow/tools/`（发布门）、`agentflow/scripts/`（lint 与 FC-27 门）、
`agentflow/docs/`（角色规格 `ROLE-SPECS.md`、提案 `PROPOSALS.md`、治理 `NOAI-GOVERNANCE.md`）。

---

## §2 想改什么 ⇒ 读哪几个文件（3 跳以内）

| 我想… | 先读（权威） | 再读（实现） | 判据 / 副作用 |
|---|---|---|---|
| 加一个新的**工具** | `tools/base.py`（`ToolSpec`/`register`） | `tools/<模块>.py` | `tests/test_tools_returns_declaration.py`（`TOOL_COUNT`）、`docs/ROLE-SPECS.md` §R0、`tests/test_role_specs_complete.py` |
| 加一个**角色动作** | `capabilities.py`（`CAPABILITIES`；禁改区） | `agent_<x>.py` 的方法 | `tests/test_coverage_policy.py`、`tests/test_capabilities_two_layer.py`、`_KNOWN_UNMATCHED_ACTIONS` |
| 改**谁能叫谁**（召唤边） | `capabilities.py`（`ALLOWED_EDGES`；禁改区） | `policy.py`、`conductor.py` | `tests/test_policy.py`、`.noai-approvals.json`（登记 ≠ 批准） |
| 改**表结构 / 字段** | `schema.py`（禁改区） | `store.py`、`verify.py` | `tests/test_schema.py`、`tests/test_verify*.py` |
| 跑一次**端到端** | `cli.py`（`cmd_run`） | `runflow.py`（`run_topic`）→ `evidence.py` / `claims.py` | `tests/test_r5_orchestration_cost.py` |
| 动**项目工作区 / 本地书架** | `cli.py`（`cmd_project`） | `projects.py` → `locallib.py` | `tests/test_projects.py`、`tests/test_user_quickstart.py` |
| 动 **A 的检索** | `agent_a/`（包） | `providers.py` → `fetch.py` → `tools/search_tools.py` | `tests/test_agent_a.py`、`tests/test_providers_online.py` |
| 动 **B 的抽取** | `agent_b/`（包） | `llm.py` → `extract.py` → `dedup.py` | `tests/test_agent_b*.py`、`tests/test_quoteverify.py` |
| 动 **C 的图分析** | `agent_c/`（包） | `tools/graph_tools.py`、`tools/trace_tools.py` | `tests/test_agent_c*.py` |
| 动 **D 的研究循环** | `agent_d/`（包） | `claimanatomy.py`、`tools/research_tools.py` | `tests/test_agent_d*.py`、`tests/test_claimanatomy.py` |
| 动 **E 的实验 / 形式化** | `agent_e/`（包） | `formalgw.py`、`tools/verify_tools.py`（禁改区） | `tests/test_agent_e*.py` |
| 动 **F 的攻坚** | `agent_f/`（包） | `tools/attack_tools.py` | `tests/test_agent_f.py` |
| 动 **G 的写作** | `agent_g/`（包） | `gates.py`、`tools/doc_tools.py`、`papercompile.py` | `tests/test_agent_g.py`、`tests/test_papercompile.py` |
| 动 **H 的审校** | `agent_h/`（包） | `gates.py`、`tools/review_tools.py` | `tests/test_agent_h.py`、`tests/test_gates.py` |
| 动 **V 的证明级验证** | `agent_v/`（包）、`specs/v.py`（禁改区：边与写集在那里） | `verifications.py`（台账 / 冷启动提示词 / 签位）、`tools/verify_tools.py`（禁改区：三件工具） | `tests/test_verifier_role.py`、`tests/test_capabilities_two_layer.py` |
| 动**主控编队 / 并发** | `conductor.py` | `scheduler.py` → `host.py` → `tools/conductor_tools.py` | `tests/test_conductor.py`、`tests/test_scheduler.py`、`tests/test_host_wiring.py` |
| 动**角色循环**（模型自己决定） | `agent_loop.py` | `agent_prompts.py` → `host.py` → `llmseam.py` | `tests/test_agent_loop.py`、`tests/test_agent_prompts.py` |
| 往**提示词**里加一句话 | `agent_prompts.py` | 它引用的现算来源：`capabilities.py` / `tools.build_registry` | `tests/test_agent_prompts.py`（每条都要与现算一致） |
| 动**模型调用与花销** | `modelgw.py`（key 的**唯一入口**：环境变量 → 设置文件 → 默认，见 `settings.py`） | `modelclient.py` → `tokenmeter.py` → `modelcost.py` → `llmseam.py` | `tests/test_modelgw.py`、`tests/test_tokenmeter.py` |
| 换一台机器 / 改**本机的工具链落点与模型 key** | 设置文件的示例 `settings.example.json`（真正那份被 git 忽略，本机键名与优先级见 `settings.py` 的模块 docstring） | `docs/FORMAL-TOOLCHAIN.md` §6（落点表 / 键名表 / 安全阀） | `tests/test_settings.py`（含"真正那份既不在索引里、也确被忽略"与"示例里没有真 key"） |
| 动**判据 / 质量门** | `verify.py`（禁改区） | `gates.py`、`deliver.py`、`faculty_checks.py` | `tests/test_verify*.py`、`tests/test_gates.py` |
| 动**发布门** | `tools/release_all.py`（禁改区） | `tools/coverage_zero_test.py`、`tools/run_each_test_file.py` | `tests/test_release_all.py`、`README.md` §6 |
| 动**lint 规则** | `scripts/lint_rules.py`（禁改区） | `tools/vocab_census.py`（禁改区） | `tests/test_lint_rules*.py` |
| 改**禁改区规则本身** | `AGENTS.md` + `.noai-paths`（两处必须逐条一致） | `scripts/noai_gate.py`（禁改区） | `tests/test_noai_gate.py`、`--check-consistency` |
| 改**用户端网页**（页面 / 端点 / SSE） | `ui/src/api.ts` 的 `ENDPOINTS`（端点的唯一出口）+ `webui/routes.py`（`ROUTES`） | `ui/src/pages/*.tsx`（九页）· `ui/src/live.tsx`（一次订阅分发给九页）· `webui/readers.py`（只读面：十个面，含 2026-10-13 加的预算/在飞/用量/状态报告）· `webui/sse.py`（流与钩子）· `webui/server.py`（`/` 的外壳与静态路由） | `tests/test_webui_contracts.py`（A–D 四条名字层 + 新鲜度）、`tests/test_webui_pages.py`（每页真读数/空态/三态）、`tests/test_webui_readers.py`（各面正控/负控 + 逐条事件的分页与编号口径）、`tests/test_webui_sse.py`（流）、`tests/test_webui_static.py`（`/` 与静态）、`ui/README-DEV.md` |
| 加一个**子命令** | `cli.py`（`build_parser`） | 对应 `cmd_*` | `tests/test_cli_run.py`、`tests/test_user_quickstart.py` |
| 查**一次运行到底做了什么** | 产物目录 `out/run-N/`（六件） | `runflow.py`、`evidence.py` | `report.md` / `run-manifest.json` |
| 查**谁在什么时候说了什么** | `sessions.py` 的会话记录 | `agent_loop.py`（事件种类） | `tests/test_sessions.py` |

---

## §3 这些文件为什么这么大（读之前先知道边界）

| 文件 | 行数 | 它的边界 | 为什么大（不是"没整理"，是职责本身宽） |
|---|---:|---|---|
| `agent_d/core.py` | 1772 | D 的全部动作（15 个，**拆包**：一个动作一个文件；`agent_d/core.py` 是其余成员，1771 行；`agent_d/_support.py` 是模块级 helper 与常量，999 行）：摄入 / 溯源 / 评估 / 提问（`propose_question`）/ 裁决 / 研究 / 汇报（批 R22 把两处请求账本收成一处 `_d_requests`，1702 → 1772 行） | 每个动作都自带"数据面前置检查 + 落库 + 三态"三段，15 个叠起来就是几千行 |
| `agent_loop.py` | 6218 | 角色循环：模型决定调哪个工具 / 唤起谁 / 给谁留言，框架负责执行与留痕（**全仓最大的文件，批 R40 补进本表** —— 它此前只在 §2 的用途表里）。批 R62：`max_output_tokens` 8,192 → 32,768（严格口径 T1 的 `ModelReplyNotOk` 与 2026-10-03 第八趟的整份重写被截断，是同一格）。批 R68：新增一档 `no_reply`（"没拿到可用的回复"：超时与"思考吃光输出预算"分开计数、分开收场，各配一句只对它说的纠正）。批 R105：新增 `_registry_with_own_action`（把"我这一趟被派的那个动作"包成 `own.<动作>` 交给循环 —— `--subagents` 那一档的收尾）。批 R119：新增 `_statement_filing_refusal`（B 入库前让它的秘书判一次"太平凡吗"，只在那件动作**真在注册表里**时才问） | 一次循环要管八种形状、每一步的提醒/闸门/读数与续跑重建 |
| `agent_c/core.py` | 1153 | C 的 9 个纯读分析动作（**拆包**：一个动作一个文件；`agent_c/core.py` 是其余成员，1153 行（批 R54 的 CS-10 ② 加了 `_report` 的产出即登记）；`agent_c/_support.py` 是模块级 helper 与常量，325 行）（批 R22 把 payload 里那句取不到的 `graph.*` 换成 `detail_reading`） | 分析类动作的**输出形状**很宽（每条都要给人读的措辞 + 给机器读的结构） |
| `capabilities.py` | 2577 | 动作表 + 写集 + 边表 + 导入期交叉断言（批 R21 加了空写集的并发含义表 `EMPTY_WRITE_SETS` 与它的两条反真空断言：2490 → 2569 行） | 声明本身不长，长的是**逐条理由**与断言（禁改区，必须写清为什么） |
| `agent_skills.py` | 2020 | 各智能体的 skills（业主 2026-10-14「现做现读」）：38 条操作手册的**目录 + 正文 + 索引**（一处定义）、`SURVEY`（38 个来源 skill 的调研记录）、`validate()`（动作可达 + 工具在**本角色**的面上 + **正文里点名**的动作/工具也算 + **落点必须在登记过的根下** + slug 可当文件名，配一张具名的"指到别人"豁免表）与 `materialize()` | 正文是**给人（模型）读的操作手册**，一条一大段；38 条叠起来就是近两千行 —— 但它**不占前置提示词**（前置里只有索引），这正是"现做现读"要换来的东西 |
| `providers.py` | 2939 | 每个数据源一个 `_parse_*` + 查询编排 + 限速重试 | 上游越多、字段越脏，解析越长（禁改区） |
| `gates.py` | 2752 | G1–G15 十五道独立检查器 | 一道门一个函数，每道门都带判据说明与负控 |
| `schema.py` | 3461 | 16 张表的 dataclass + 词表 + 校验 | 字段多、每个字段都带契约注释（禁改区）。S1r 并表（2026-10-10）：`concepts` 从 `TABLES` 退役、`SCHEMA_VERSION=2` |
| `runflow.py` | 2043 | 一次 `run` 的全流程（取材料 → 跑模型 → 落六件产物） | 主路径把每个阶段的失败分支都写全了；`run_topic` 已按 `T-7` 拆成 6 个 `_phase_*`（最长 228 行）+ 130 行编排层。批 R113：单价改成按**这一趟自己的时间戳**取（`price_of(cfg, at=stamp)`），不再读结账时的墙钟 |
| `evidence.py` | 1892 | 检索 + 逐字回验 + 来源登记 | 三档回验级别各一套路径 |
| `cli.py` | 2701 | 25 个子命令的入口与打印 | 每个子命令的 `--help`、三态退出码、卡片式输出 |
| `claimanatomy.py` | 1889 | 断言解剖学（每条断言的可判定性）；批 R71 加了第 5 族的第二个码 `uncontrolled_disclaimer`（自造免责声明不再过关，见 `draft/116`） | 判据多且互相独立 |
| `agent_b/core.py` | 1316 | B 的 7 个动作（**拆包**：一个动作一个文件；`agent_b/core.py` 是其余成员，1314 行；`agent_b/_support.py` 是模块级 helper 与常量，186 行）：入库 / 重抽取 / 结构重复裁决 / 登记命题 | 回验是"每条关系都要过"，代码密度高 |
| `verify.py` | 1935 | 全局不变量审计（`verify_all` 已按 `T-5` 拆成 14 个 `_check_*` + 30 行编排层；批 R19 在 `_check_2` 里加了 I7 在途上限的两条读数） | 40 多条不变量平铺（禁改区，见 T-5） |

---

## §4 判据在哪（改完拿什么证明没改坏）

| 你改的是 | 至少跑这些 | 说明 |
|---|---|---|
| 任何东西 | `python -m pytest -q -p no:cacheprovider` | 全量（约 20 分钟） |
| 任何东西 | `python -B scripts/lint_rules.py` | error 必须 0（warning/info 有基线读数） |
| 工具面 / 角色面 | `python -B tools/verify_role_specs.py`、`tests/test_role_specs_complete.py` | 工具条数与文档一致 |
| 禁改区 | `python -B scripts/noai_gate.py --git --since <ref>` | 退出码 1 = 需要 2 名 reviewer |
| 发布相关 | `python -B tools/release_all.py`、`python -B tools/coverage_zero_test.py --level 2` | 发布门与覆盖门 |
| 文档里写了数字 | 先看 `DEVELOPMENT.md` §0.3 的"手抄数字清单" | 哪些数字有判据、哪些要人同步 |

---

## §5 这张图自己的判据

`tests/test_reading_map.py` 钉两件事（这条判据本身也是"文档不许烂"的一部分）：

1. **图里出现的每个文件名都真实存在**（相对 `agentflow/` 或仓库根解析得到）；
2. **`src/agentflow` 的每个模块都被这张图提到过**（不许有"孤儿文件"）——
   新增一个模块却忘了在这张图上给它位置，判据会红。
