# USER-GUIDE-CLI.md —— CLI 侧用户说明书

> **这份文件只管命令行。** 网页那一侧（页面、`/api/*`、写面开关）见
> [`USER-GUIDE-WEB.md`](USER-GUIDE-WEB.md)；`--json` 的逐字段契约见 [`CLI-CONTRACT.md`](CLI-CONTRACT.md)；
> 哪份文档算数见 [`INDEX.md`](INDEX.md)。
>
> **本文每一条命令都在 2026-11-21 实跑过**，输出是当次原文（过长的截断处标 `…`）。
> 实跑环境：Windows / Python 3.11.4 / `agentflow 1.0.0`（editable 装在本仓 `agentflow/`）。
> 全部命令 → 退出码 → 关键输出的清单见本文附录 A。
>
> 本文用的工作区变量（**每次开新终端先设一次**；换成你自己的空目录即可）：
>
> ```powershell
> $WS = "D:\Incubator\agentflow\temp\userguide\ws"
> ```

---

## 0. 安装与三个入口

### 0.1 装

在仓库根 `D:\Incubator`（`pyproject.toml` 在 `agentflow/` 里）：

```powershell
python -m pip install -e agentflow
```

实跑（`--dry-run` 只解析依赖、不真装，用来证明这条命令在这个仓里成立）：

```text
$ python -m pip install -e agentflow --dry-run --no-deps
Preparing editable metadata (pyproject.toml): finished with status 'done'
Would install agentflow-1.0.0
EXIT=0
```

装完 `pip show` 里应当有 `Editable project location:`（这条是判断"装的是这份源码"的唯一读数）：

```text
$ python -m pip show agentflow
Version: 1.0.0
Location: C:\Users\...\Python311\Lib\site-packages
Editable project location: D:\Incubator\agentflow
Requires: filelock, PyYAML
```

**不想装**也可以，直接从源码树跑 —— 效果一样（`PYTHONPATH` 排在 `site-packages` 之前）：

```powershell
$env:PYTHONPATH = "D:\Incubator\agentflow\src"
python -m agentflow --version
```

```text
$ python -m agentflow --version
agentflow 1.0.0
EXIT=0
```

### 0.2 验：版本与三个等价入口

`agentflow` 这个可执行名、`python -m agentflow`、`python -m agentflow.cli` 是**同一条命令**
（`pyproject.toml` 的 `[project.scripts] agentflow = "agentflow.cli:main"`，
`agentflow/__main__.py` 转给同一个 `main`）。三个都实跑过，输出逐字相同：

```text
$ agentflow --version
agentflow 1.0.0                                          EXIT=0
$ python -m agentflow --version
agentflow 1.0.0                                          EXIT=0
$ python -m agentflow.cli --version
agentflow 1.0.0                                          EXIT=0
```

### 0.3 有多少条子命令：现算 29

**不要背数字，现算**（`build_parser()` 是唯一真身）：

```powershell
python -c "import sys;sys.path.insert(0,'agentflow/src');from agentflow import cli;import argparse;p=cli.build_parser();s=[a for a in p._actions if isinstance(a,argparse._SubParsersAction)];print({len(x.choices) for x in s})"
```

```text
{29}
```

`python -m agentflow --help` 只把它们归成 **4 个组**（组内地名就是旧名）：

```text
$ python -m agentflow --help
usage: agentflow [-h] [--root ROOT] [--config CONFIG] [--no-color] [--plain]
                 [--version] [--help-legacy]
                 <命令> ...
命令（四个入口）:
  组内地名就是旧名；旧名本身也仍然可以直接敲
    incubate    孵化：把一趟研究开起来、管起来
                init  start  stop  status  answer  inbox  submit  interject
    inspect     查看：只读的读数与检查
                status-report  stats  evidence  artifacts  analyze  tools
                cache  budget  doctor  verify
    run         跑：流水线与角色循环，以及它们的维护
                topic  pipeline  run-a  run-b  run-agent  repair  rebuild
                project  closing
    serve       服务：网页与离线演示
                web  demo
  …
  --root ROOT      工作区根（缺省 = 当前工作目录；本进程此刻是 <绝对路径>）
                   所有读写工作区的子命令同这一条缺省；`web` / 不带任务的 `start --watch`
                   例外（找当前目录下最近的已初始化工作区）
  --plain          纯 ASCII 输出…
EXIT=0
```

29 条旧名的全文对照表（一条都没删，新旧逐字等价）：

```text
$ python -m agentflow --help-legacy
  init           →  agentflow incubate init
  start          →  agentflow incubate start
  …
  closing        →  agentflow run closing
  web            →  agentflow serve web
  demo           →  agentflow serve demo
EXIT=0
```

> 组名**不是**子命令：`agentflow inspect stats` 在解析前就被折回 `agentflow stats`
> （`cli.canonical_argv`），所以旗标、缺省、退出码一个字都不差。

### 0.4 两个会咬人的缺省（先读，能省掉一半的"命令没反应"）

**① `--root` 是全局旗标，必须写在子命令前面。**

```text
$ python -m agentflow status --root $WS
usage: agentflow [-h] [--root ROOT] …    ← （argparse 打的 usage）
agentflow: error: unrecognized arguments: --root D:\...\ws
EXIT=2

$ python -m agentflow --root $WS status      # 正确写法
EXIT=0
```

例外只有一个：**`start` 自己也收 `--root`**（写后面也认，两边同义，实测
`agentflow start --root $WS … --dry-run` → `工作区：…\ws\projects\x`）。
`project` / `budget` 收的是 `--projects-dir` 而不是 `--root`。**统一写在子命令前**永远是对的。

**② 不给 `--root` 时，"缺省工作区" = 当前目录（所有读写工作区的子命令同一条缺省）。**

> 2026-11-21 CLIFIX ①：此前有**两套** —— `init` / `verify` / `budget` / `interject` /
> `inbox` / `answer` / `stop` / `closing` / `run-agent` 这一族用**当前目录**，而
> `status` / `stats` / `status-report` / `submit` / `start` 用**代码检出目录**
> `DEFAULT_ROOT`。同一条命令族两套"缺省"，于是 `cd 我的项目; init`（建在这儿）之后
> 紧跟的 `status` 读的是 `agentflow/` —— 一个"建好了却看不见"的经典错觉。
> 现在缺省只有一处算法（`cli.default_workspace_root()`），`init` 建在哪，`status`
> 就读哪。

| 命令 | 不给 `--root` 时读到哪 | 实测（改后） |
|---|---|---|
| 所有读写工作区的子命令（`init` / `status` / `stats` / `status-report` / `submit` / `verify` / `interject` / `inbox` / `answer` / `stop` / `budget` / `closing` / `run-agent` / `start` …） | **当前目录** | `cd ws-empty; … status` → `工作区 D:\...\ws-empty`；`cd ws-cwd; … init` → `[init] 已初始化：…\ws-cwd\data`；同一处再 `status` → `工作区 D:\...\ws-cwd` |
| `doctor` | **不读工作区**（只探测环境） | 从空目录跑也给读数，`data/` 一个字节不写 |
| `web` / 不带任务的 `start --watch` | **当前目录下最近的已初始化工作区**（`_nearest_workspace`；业主 2026-10 的裁定） | `--help` 的 `--root` 那一行逐字写着这个例外 |

`--help` 把缺省写成**现算的绝对路径** —— "帮助里那个路径"就是"这一趟真会读的那个路径"：

```text
$ python -m agentflow --help | Select-String -- '--root'
  --root ROOT      工作区根（缺省 = 当前工作目录；本进程此刻是 D:\Incubator\agentflow）。…
```

所以：**仍然建议每条命令都显式给 `--root`**（干净、可复算），但"给与不给"读的是
同一份盘了 —— 忘了给不会再"看不见"。

> ⚠️ 根 `README.md` §From Install to First Run 第 4 条仍写着"It is not inferred from the
> current directory: omitted, it falls back to the package's own default workspace"
> —— 那句自 CLIFIX ① 起不成立（缺省就是当前目录）。根 `README.md` 不在
> USERGUIDE-CLI 路可写面，已登记交 CLEAN-DOCS / 业主（见 CLIFIX 报告 §3）。

---

## 1. 建工作区：`init`

工作区 = 任意一个目录，台账落在 `<工作区>/data/`。

```powershell
$WS = "D:\Incubator\agentflow\temp\userguide\ws"
New-Item -ItemType Directory -Force -Path $WS | Out-Null
python -m agentflow --root $WS init
```

```text
[init] 已初始化：D:\Incubator\agentflow\temp\userguide\ws\data
EXIT=0
```

落下来的东西（`data/` 是 16 张在用表各一份 JSON 快照 + 一份追加日志 `events.jsonl`，
`library/` 是文献库。下面那份 `init` 输出是 **2026-11-21 的实跑记录**：那时
`eval_results` 还没退役，所以它还出现在清单里；今天 `init` 只建 16 张，
`eval_results` 进了 `schema.RETIRED_TABLES`（旧工作区那份文件仍读得出来、带
`retired=true`，写侧一律拒））：

```text
D:\...\ws\data\{analysis_reports,attack_plans,conjectures,counters,dependencies,
  documents,eval_results,experiments,lit_candidates,literature,relations,
  reprocess_requests,research_questions,review_findings,search_requests,
  statements,tasks,usage_ledger}.json
D:\...\ws\data\events.jsonl
D:\...\ws\library\
```

**旧工作区不再兼容（2026-11-22 业主裁定）**：本文写的都是**新布局** —— 正文 `manuscripts/<角色>/`、
草稿 `work/<角色>/`、交接账本 `work/handoffs.jsonl`、产物 `out/package/` · `out/report/` ·
`out/exp-logs/`。早于这一版的旧布局（`reports/`、`documents/`、`manuscripts/handoffs.jsonl`、
`out/paper`、`out/review`、`out/experiments`、`library/<id>/`）**不再支持**：新代码对它报
「旧布局（不再支持）」，不静默读、不折成空、也不迁移。**要看旧工作区的读数，用当时的代码读** ——
拿新代码去读 `projects/lp-ball-*` 那批历史工作区，得到的就是这条读数；那不是数据坏了，是「它还是旧布局」。

### 1.1 三个开关

| 开关 | 干什么 | 什么时候用 |
|---|---|---|
| `--force` | 覆盖已有数据（**危险**） | 只在这个目录的数据确认可以丢时 |
| `--allow-foreign-entries` | 目录里已经有你的东西（PDF、笔记），仍然按工作区初始化 | 第一次把工作区建在自己的资料目录里 |
| `--seed-literature` | 把历史真机下载的种子文献投进**输入区** `reference/`（**只放文件，不写台账**） | 想要一批现成的文献种子时 |

**外来目录默认拒绝**（这条守卫是刻意的：在别人的目录里凭空建出整套 `data/`+`library/`
是不可逆的）：

```text
$ python -m agentflow --root $WS-foreign init
[init] 拒绝 init：…\ws-foreign 既不是工作区（没有 data/）、又不是空目录 ——
里面有 1 个不属于我们的条目：['我的笔记.txt']。…三条出路：① 换一个空目录；
② `init --force`；③ 走工具层：`projects.ensure_project`。
[init] …若它就是要用的工作区：加 --allow-foreign-entries 再跑一次 …
EXIT=2

$ python -m agentflow --root $WS-foreign init --allow-foreign-entries
[init] 已初始化：…\ws-foreign\data
EXIT=0
```

加开关之后，你的文件**不删不改**，只是从此算这个工作区的条目；同时落一个白名单标记
`.agentflow-workspace`（`store` 认它就是"这是工作区"）。

**种子文献**（`--seed-literature`）：

```text
$ python -m agentflow --root $WS-seed init --seed-literature
[init] 种子文献：25 份投到 D:\...\ws-seed\reference
（输入区，未入库、未判收；见 D:\...\ws-seed\reference\SEED-README.md）
[init] 已初始化：D:\...\ws-seed\data
EXIT=0

$ python -m agentflow --root $WS-seed status      # 只看 literature 那一行
│ literature         │    0 │ processed=0 downloaded=0 │
```

**`reference/` 里 25 个 PDF、`library/` 里一个都没有、`literature` 表 0 行** —— 这就是
"只放文件、不写台账"的读数：种子不是证据，A 仍然要逐篇判收才会有台账行。
`library/` 是**已登记书架**（`literature.path` 就指向它），种子不往那里放 ——
未登记的文件占着书架位置会让 A 侧维护的文献库结构异常。

**落声明**：用户说"这个文件夹里的都是可靠参考文献"时，把下面这份落成工作区根的
`RELIABLE-REFERENCES.json`（`verbatim` 用用户原话；没有声明 ⇒ 一份都不许入库，
非 dry 档会以 `not_declared_reference` 受控拒）：

```json
{"paths": ["reference/"], "verbatim": "reference/ 里的文件都是用户提供的可靠参考文献，可入库；其它地方的文件只作参考、不可入库"}
```

判收仍由 A 走候选链（`reference/SEED-README.md` 里逐字写着四步）。

### 1.2 `projects/` 落在哪（**先看这一节再跑 `start`**）

`--project <名字>` 的落点由 `--projects-dir` 决定，缺省**不是** `<root>/projects`：

| 你怎么写 | 落到哪 | 实测 |
|---|---|---|
| `--root $WS --project P`（没给 `--projects-dir`） | `$WS\projects\P` | `工作区：D:\...\userguide\ws\projects\demo-run` |
| `--project P --projects-dir D:\x\projects` | `D:\x\projects\P` | 见 §2 |
| 两者都不给 | **`D:\Incubator\projects\P`**（由包位置推出的仓库根下 `projects/`，`projects.DEFAULT_PROJECTS_DIR`） | `cd ws; start --project cwd-proj --dry-run` → `工作区：D:\Incubator\projects\cwd-proj` |
| 环境变量 `AGENTFLOW_PROJECTS_DIR` | 该变量指的目录 | `工作区：D:\...\userguide\ws\projects\env-proj` |

最后一行是真会咬人的：**"两者都不给"会写进仓库的真实 `projects/`**（那里躺着历史真机
`lp-ball-*`）。规矩只有一条：

> 跑 `start --project` 时，**要么给 `--root`，要么给 `--projects-dir`**；纯粹想换个落点
> 就设 `AGENTFLOW_PROJECTS_DIR`。三个都给时优先级：`--projects-dir` > 环境变量 >
> 设置文件 `workspace.projects_dir` > 缺省。

2026-11-21 CLIFIX ②：`--projects-dir` 的 `--help` 以前把这条缺省写错了两处（`start`
写成"缺省 `<root>/projects`"，而只有**给了** `--root` 才如此；`budget` 抄了"与 start
同一条口径"，而它根本不读 `--root`）。现在三处帮助都写**真实的绝对缺省**，且逐字写清
"`--root` 与 `--projects-dir` 的关系"：

```text
$ python -m agentflow start --help | Select-String -- '--projects-dir' -Context 0,6
  --projects-dir PROJECTS_DIR
                        projects 落点。给了 `--root` 而没给本旗标 ⇒
                        `<root>/projects`；两处都不给 ⇒
                        D:\Incubator\projects（由本包位置推出的工作区根下的
                        projects/，不是当前目录）。顺序：显式旗标 > 环境变量
                        AGENTFLOW_PROJECTS_DIR > 设置文件的 workspace.projects_dir
                        > 上面那个缺省

$ python -m agentflow budget --help | Select-String -- '--projects-dir' -Context 0,1
  --projects-dir PROJECTS_DIR
                        projects 落点。本命令不看 `--root`（它不参与这条推断）；不给本旗标 ⇒ …
```

`project` / `budget` 与 `start` 的差别不是笔误：`start` 有一条"给了 `--root` ⇒
`<root>/projects`"的改写，而 `project` / `budget` **从不读 `--root`**（`project run` 的
行为按 C2 逐字不变）。

`--dry-run` 会把将要写进的那个**绝对路径**印出来（`工作区：…`，以及 `--json` 的
`workspace` / `project.path`），所以去掉 `--dry-run` 之前就能看见它要落在哪：

```text
$ cd <任意目录>; python -m agentflow start --project cwd-proj --task t --dry-run --json
… "workspace": "D:\\Incubator\\projects\\cwd-proj" …
```

---

## 2. 起一趟：`start`

`start` 回答四个问题：**干什么 / 在哪干 / 花多少钱 / Lean 开不开**。它之外的入口
（`run` / `run-agent` / `project run` / `web`）都是它的子模式。

`--mode` 不写就按目录状态推断：没给 `--task` 且给了 `--watch` ⇒ 只开网页；
项目文件夹不存在或为空 ⇒ `cold`；已有台账 ⇒ `research`；存在但没台账 ⇒ `warm`。

### 2.1 先看会发生什么：`--dry-run`

**`--dry-run` 只打印、不建目录、不写字节、一次模型都不调、也不起 Lean 子进程。**

```powershell
python -m agentflow --root $WS start `
  --mode research --project demo-run --sid guide-s1 `
  --budget-usd 1 --task "验证一条最小研究回路：整数分拆的奇偶性" `
  --dry-run
```

```text
缓存：使用 非 Lean 版缓存（p315 · 11/12）

┌── 试运行：将要发生的一切（一个字节都不写、一次模型都不调） ──────────────────┐
│ 模式                research（十角色循环）                                    │
│ 模型                deepseek-flash（base=https://api.deepseek.com/v1）        │
│ 预算                1 美元（命令行显式给的，会落盘）                          │
│ Lean                开关现在关（来源 缺省）；这一趟 --lean off；自检没跑      │
│ 会召唤              M 起十角色循环（--subagents）：M 可以召唤 D、C、B、E、A…  │
│ 会写这些            工作区 …\ws\projects\demo-run（会新建…）                  │
│ 任务：验证一条最小研究回路：整数分拆的奇偶性                                  │
│ 冷启动：会新建文件夹、初始化工作区、登记书；热启动：复用已有工作区（已登记的书按内容 hash 跳过），产物写进新的 out/run-N │
└──────────────────────────────────────────────────────────────────────────────┘
  工作区：            D:\Incubator\agentflow\temp\userguide\ws\projects\demo-run
  · 不花钱（试运行一次模型都不调）
EXIT=0
```

跑完确认一个字节都没写：`Test-Path "$WS\projects"` → `False`。

### 2.2 机器可读的那一份：`--json`

```powershell
python -m agentflow --root $WS start --mode research --project demo-run --sid guide-s1 `
  --budget-usd 1 --task "验证最小回路" --dry-run --json
```

```json
{"mode": "research", "task": "验证最小回路",
 "workspace": "D:\\...\\ws\\projects\\demo-run",
 "project": {"name": "demo-run", "exists": false, "mode": "cold",
             "reason": "冷启动（auto）：文件夹不存在", "will_create": true, "run_index": 1},
 "model": {"name": "deepseek-flash", "base_url": "https://api.deepseek.com/v1"},
 "budget": {"usd": 1.0, "given": true, "register": "...\\projects\\demo-run\\budget.json"},
 "lean": {"choice": "off", "now_on": false, "selfcheck": "没跑（试运行不启动检查器）"},
 "summons": "M 起十角色循环（--subagents）…",
 "writes": ["工作区 …（会新建）", "运行记录与会话事件", "预算寄存器 budget.json（1）"],
 "spend": "不花钱（试运行一次模型都不调）"}
EXIT=0
```

键集合就是 `cli.START_PLAN_KEYS`（mode / task / workspace / project / model / budget /
lean / summons / writes / spend）。

> `mode` 与文本横幅是**同一个词、同一次计算**（`cli._mode_word(spec)`）：`--mode research`
> ⇒ 横幅 `research（十角色循环）` / JSON `"research"`；`--mode role` ⇒ 两边都是 `role`；
> `--mode topic|project` 同理。2026-11-21 CLIFIX ③ 之前 JSON 写的是 `"role"`（与横幅
> 不一致，脚本会读成"只跑一个角色"），现在不会了。

### 2.3 四种模式各是什么

| `--mode` | 跑什么 | 缺省预算 | 要不要 `--task` |
|---|---|---|---|
| `research` | 十角色循环（M 主控 + `--subagents`） | 不限量 | 要 |
| `role` | 只跑一个角色循环（必须 `--role A..H,V,L,M`） | 不限量 | 可（`--watch` 时不要） |
| `topic` | 端到端跑一个主题（检索→作答→逐字回验→记账→熔断→六件产物），**不召唤角色** | 1.0 | 要 |
| `project` | 项目工作区（端到端主题跑） | 0.5 | 要 |
| `cold` / `warm` | 冷/热启动（`--start cold\|warm` 同义） | — | 要 |

`topic` 与 `project` 的 `--dry-run` 实测差异（同一句话）：

```text
$ … start --mode topic --task "验证主题跑" --budget-usd 1 --dry-run
│ 模式                topic
│ 预算                1 美元（命令行显式给的，会落盘）
│ 会召唤              不召唤任何角色（端到端跑主题：检索 / 作答 / 逐字回验都不经角色循环）
│ 会写这些            工作区 …\ws；out/run-N 六件产物；预算…
│ 这一趟的落点还没有台账（data/tasks.json 0 行）
EXIT=0

$ … start --mode project --project p2 --task "验证项目跑" --dry-run
│ 模式                project
│ 预算                0.5 美元（该模式的缺省值，不落盘）
│ 会召唤              不召唤任何角色（项目工作区那一步是端到端主题跑）；要角色循环请 --mode res…
EXIT=0
```

### 2.4 `--seed-literature`：投放历史文献种子

与 `init --seed-literature` 是同一件事：**只把 PDF 放进 `<工作区>/reference/`（输入区），
不写台账**（见 §1.1 的 25 份 / `library/` 空 / `literature` 0 行那条读数）。只对
`project` / `research` 两档、且只在**新建**工作区时生效；`data/` 已经在了的热启动不投。

```powershell
python -m agentflow --root $WS start --mode research --project seed-run --sid guide-s3 `
  --seed-literature --task "验证种子投放" --dry-run
```

```text
│ 模式                research（十角色循环）
│ 会写这些            工作区 …\ws\projects\seed-run（会新建…）
EXIT=0
```

> 注意：`--dry-run` 的横幅**不单列"要投几份种子"**（只在真跑时打
> `[init] 种子文献：25 份投到 …`）。想先确认份数，用 `init --seed-literature` 在一个空目录上试（§1.1）。

#### 2.4.1 重新投放的命令序列（复制即用）

改前投到 `library/` 的那批工作区**不就地修**（`projects/lp-ball-16` 是错误投放形态的现场，
只读留证）。重投在**新工作区**上做，命令在 `agentflow/` 下跑：

```powershell
# 0) 选一个新的空工作区路径（不要指向已有证据的那个工作区）
$WS = "D:\Incubator\agentflow\temp\ws-seed"

# 1) 删旧工作区（仅当这个路径确实是要重投的那一个）
if (Test-Path $WS) { Remove-Item -Recurse -Force $WS }

# 2) 建工作区并把 25 份种子投进输入区 reference/
python -m agentflow --root $WS init --seed-literature

# 3) 复算种子包（sha256 / 字节 / 抽读字数；任何一份不符 ⇒ 退出码 1）
python scripts/seed_corpus.py --verify

# 4) 核对三件事：library/ 空 · reference/ 25 份 · 三张台账 0 行
(Get-ChildItem "$WS\library" -Recurse -File | Measure-Object).Count    # 期望 0
(Get-ChildItem "$WS\reference" -Filter *.pdf).Count                   # 期望 25
python -m agentflow --root $WS status | Select-String 'literature|lit_candidates|search_requests'

# 5) 落声明（用户说"reference/ 里都是可靠参考文献"时；verbatim 用用户原话）
@'
{"paths": ["reference/"], "verbatim": "reference/ 里的文件都是用户提供的可靠参考文献，可入库；其它地方的文件只作参考、不可入库"}
'@ | Set-Content -Encoding utf8NoBOM "$WS\RELIABLE-REFERENCES.json"

# 6) 起跑（M 会把声明当白名单，A 走 reference/SEED-README.md 里的判收链）
python -m agentflow --root $WS start --mode research --project seed-run --task "…"
```

投完的读数是：`reference/` 25 份 + `reference/SEED-README.md`；`library/` 一个文件都没有；
`literature` / `lit_candidates` / `search_requests` 三张表 0 行。种子进入 `library/` 只发生在
A 判收之后（那时才有 `literature` 行与 `path`）。

### 2.5 真跑要什么（本文**没有**真跑）

真跑要两样东西：**一个能用的模型 key** 和**一笔预算**。机器上没有 key 时
`doctor` 会直说（见 §3.5）。这两条本文一次都没触发 —— 说明书里所有 `start` 都是
`--dry-run`，一分钱没花。要真跑时把最后那个 `--dry-run` 去掉即可：

```powershell
python -m agentflow --root $WS start --mode research --project demo-run --sid guide-s1 `
  --budget-usd 1 --task "验证一条最小研究回路：整数分拆的奇偶性"
```

`--budget-usd` 显式给了就会落盘到 `<落点>/budget.json`，并在首屏打一次 `旧额 → 新额`；
不给则按模式的缺省值，且不写盘。**预算扣完自动优雅停**（不是报错）。

`start` 缺 `--task` 时的报错是人话，且点名该给哪个旗标：

```text
$ python -m agentflow start
[start] 缺一样要跑的东西：给 --task "这次要做的事"（研究 / 项目 / 主题三档都要它）。
只想开网页监督就加 --watch；只想跑某一条角色的循环就 --mode role --role <角色>；
想先看看会发生什么就再加 --dry-run
EXIT=2
```

---

## 3. 看进度

### 3.1 `status`：每张表几行

```powershell
python -m agentflow --root $WS status
```

```text
工作区 D:\Incubator\agentflow\temp\userguide\ws

┌────────────────────┬──────┬──────────────────────────────────────────────┐
│ 表                 │ 行数 │ 其它                                         │
├────────────────────┼──────┼──────────────────────────────────────────────┤
│ search_requests    │    0 │ done=0 pending=0                             │
│ literature         │    0 │ processed=0 downloaded=0                     │
│ relations          │    0 │ by_status={} quote_verified=0 quote_unverif… │
│ research_questions │    0 │                                              │
│ …                  │      │                                              │
│ tasks              │    0 │                                              │
│ usage_ledger       │    0 │                                              │
│ events             │    0 │ 追加日志                                     │
└────────────────────┴──────┴──────────────────────────────────────────────┘
EXIT=0
```

机器可读：`python -m agentflow --root $WS status --json`（`Store.stats()` 原样打出，
`root` + 每张表一节）。退出码 `0` 读到 / `2` 打不开工作区。

> **行为提示**：`status` 会顺手 `st.init()` —— 对一个空目录跑 `status` 会**把这个工作区建起来**。
> 不给 `--root` 时缺省就是当前目录（§0.4 ②），所以这条落点就是"你站的那个目录"；于是
> 在一个"有外来条目的目录"里跑 `status` 会以退出码 **2** 报 `[store 错误] 拒绝 init：…有 1 个
> 不属于我们的条目…`（与 `init` 同一道守卫，不会往别人的目录里建东西）。
> 只读体检请用 §3.5 的 `verify` / `doctor`。

### 3.2 `stats gates`：八格四态一张表（**最该先看的一条**）

```powershell
python -m agentflow --root $WS stats gates
```

```text
读数 gates（只读，零模型调用）
三态    checked=True  state=checked

格                  四态     原话（缩 46 字，全文见 --json）
------------------  -------  -----------------------------------------------------------------
contradictions      na
load_bearing        na
report_shape        unknown  没给报告路径 ⇒ 报告形状没查成（不是「报告没问题」）
user_pending        unknown  这次调用没有会话身份（装配期没注入 sid…）
substance           fail     这一趟没有任何实质产出（documents=0、relations=0、experiment…
acceptance          unknown  没给项目根 ⇒ 验收表的机器可判行没查成（不是「没有这一条」）
artifact_ledger     unknown  没给项目根 ⇒ 产物台账这一格没查成（不是「盘上一致」）
literature_pending  na

计数：pass=0  fail=1  unknown=4  na=3
机器口径 machine_pass=False；M 判据 m_says_done=False，机器口径 can_close=None
M 的判据：没有人判过（这一格是 unknown，不是『通过』）

要看见的 2 条：
  [no_substantive_output] 【substance】这一趟没有任何实质产出（documents=0…）⇒ 不许报「可交付」…
  [no_session] 没给运行号（sid）⇒ 待答问题那一格只能是 unknown（不是 pass）…
EXIT=0
```

**四态的读法（这是整份说明书最要紧的一张表）**：

| 四态 | 意思是 | 不是 |
|---|---|---|
| `pass` | 查过了，这一格过了 | — |
| `fail` | 查过了，这一格没过（附原话与处置） | 不是"跑挂了" |
| `unknown` | **没查成**（缺输入 / 缺会话号 / 缺项目根） | **绝不是 pass** |
| `na` | 没有可判对象（依赖的表一行都没有），记"不适用" | 不是 pass，也不是 unknown |

注意 `state=checked` 与 `pass` 是两件事：`checked` 说的是"这次读数读到了"，
八格里照样可以有 4 个 `unknown`、1 个 `fail`。

`--json` 是外层四格信封（`ok` / `state` / `data` / `problems`），完整契约见 `CLI-CONTRACT.md`：

```text
$ python -m agentflow --root $WS stats gates --json
{
  "checked": true,
  "state": "checked",
  "reason": "",
  "data": {
    "cells": [ { "name": "contradictions", "status": "na", "detail": "" }, … ]
  }
}
EXIT=0
```

### 3.3 `stats errors` / `stats cost` / `stats flow`

```text
$ python -m agentflow --root $WS stats errors
错误动作计数（角色侧 / 系统侧 / 状态读数分栏；只读，零模型调用）
三态    checked=True  state=checked  逐类 读到 46 / 没查成 0 / 不适用 0
读数    事件流 0 条（0 行读不明白）/ 会话记录 1 条（1 个文件，0 行读不明白）
三个数  角色侧 0 / 系统侧 2 / 状态读数 0   ← 刻意不相加：三种单位
…
角色侧错误动作（角色 × 类目；只有这张表进 total）：
  全 0（错误类目一条都没命中）
EXIT=0
```

```text
$ python -m agentflow --root $WS stats cost
读数 cost（只读，零模型调用）
三态    checked=True  state=checked
按角色：
  （0 行：一分钱都没记过）
按阶段（scope）：
  （0 行：一分钱都没记过）
EXIT=0
```

`stats all` 把四张一起打，三态取合取（有一条没查成就整条记 `unknown`）。

### 3.4 `closing`：收工门（八格 + 三方退出码）

```powershell
python -m agentflow --root $WS closing
```

```text
  · 会话：缺省会话（没给 `--sid` ⇒ 这一次调用没有会话身份：「待答问题」那一格是「没查成」…）
  · 收工结论：unknown（exit 2） · m_says_done=False · retire=干净 · programs=已停
  · contradictions：na —— 这一格依赖的表都在盘上但一行都没有（…）⇒ 没有可判对象，记 na
  · load_bearing：na —— …
  · report_shape：没查成 —— 没给报告路径 ⇒ 报告形状没查成（不是「报告没问题」）
  · user_pending：没查成 —— 这次调用没有会话身份…
  · substance：拦住 —— no_substantive_output: 这一趟没有任何实质产出（documents=0…）
  · acceptance：没查成 —— 没给项目根…
  · artifact_ledger：没查成 —— 没给项目根…
  · literature_pending：na —— …
  · 收工结论的理由：M 没有提交自己的判据（没人判过）⇒ 没查成，不是可以交
  [warning] report_path_missing：…        [blocker] no_substantive_output：…
收工结论：unknown（exit 2） · 八格 0/8 pass · m_says_done=False · retire=干净 · programs=已停；
收工门：机器八格：pass 0/8；fail=['substance']；
unknown=['acceptance','artifact_ledger','report_shape','user_pending']；
na=['contradictions','load_bearing','literature_pending'] —— M 没有提交自己的判据…
EXIT=2
```

**退出码三档（实测）**：

| 退出码 | 含义 | 实测触发方式 |
|---|---|---|
| `0` | 可以交（八格全 `pass` 且无 blocker **且** M 说做完了） | 空工作区做不到 |
| `1` | 查过了，不能交 | `closing --goal "…" --basis "…" --goal-not-met` → `EXIT=1`；`--goal-met` 在空工作区也 `EXIT=1`（`收工结论：fail（exit 1）… 格 fail：substance`） |
| `2` | **没查成**（缺输入 / 会话号不在盘上） | 不带任何旗标 → `EXIT=2` |

`--goal-met` 不等于"我说了算"：机器八格不过，它照样 `fail (exit 1)`。

给了不存在的会话号会**受控拒绝**（不出一份"八格全是没查成"的空读数）：

```text
$ python -m agentflow --root $WS closing --sid guide-nope
  · 拒绝：没有会话 'guide-nope'（sessions/guide-nope.jsonl 都不在盘上） ⇒ 不跑收工门
（退出码 2，不出一份「八格全是没查成」的空读数）。盘上有的会话号：guide-s1
EXIT=2
```

常用旗标：`--sid <这一趟>`、`--project-dir <项目根>`、`--report <报告路径>`、
`--cap-usd <成本上限>`、`--acceptance-sid <验收那一趟>`、`--goal/--goal-met/--goal-not-met`、
`--no-index`（只想看门过没过、不写盘）。

### 3.5 `verify` / `doctor`：读数与体检

```text
$ python -m agentflow --root $WS verify
✓ ok  校验完成  错误 0 / 警告 0
EXIT=0
```

`verify` 退出码：`0` 无 error / `1` 有 error（`--strict` 时 warning 也算）/ `2` 没查成。

```text
$ python -m agentflow --root $WS doctor
这台机器的体检
  · 模型 key：已配置；base=https://api.deepseek.com/v1；model=deepseek-flash
  · 证明检查器：lean（settings） ⇒ D:\Incubator\_env\lean470\...\lean.EXE；
    Lean (version 4.7.0, …)
  · Mathlib：没查（Lean 形式化关着 ⇒ 在第 ⑤ 步之前就返回了）—— 这一档既不是「不可用」，也不是「可用」
── Lean 工具链（开机自检） ──────────────────────────────────────────────
  · checked=True；ok=False；state=off；开关=关（来源 default）
  · 结论：这一趟做不了形式化核验（会如实报没核到）
EXIT=1
```

`doctor` 退出码：`0` 齐 / `1` 有缺（上面就是**有缺**：Lean 关着）/ `2` 没查成。
每一项失败都带 `fix_hint`（一条可直接复制执行的命令）。`doctor --selfcheck` 只做包内
源码自检（逐文件 compile，不探测工具链、不花钱）。

### 3.6 `status-report`：一份人读的状态报告

```text
$ python -m agentflow --root $WS status-report
[status-report] 报告已落盘：D:\...\ws\out\review\STATUS-20261121-2313.md
[status-report] 机器可读那一份：D:\...\ws\out\review\STATUS-20261121-2313.json
[status-report] 交接账本：0 行（模型填 0 / 派生 0）
[status-report] 在飞任务：0；在跑的循环：没有；停机开关：不在
[status-report] 下一步（从读数派生）：
  - 还没有可检验的猜想（`conjectures` 0 行）⇒ 先把模式写成带 `testable` 的猜想
  - 还没有稿件（`documents` 0 行）⇒ 有结论就落一份手稿，别只留在会话里
  - 发过 1 条插话而**一次都没被读到**（`agent_interjection_seen` 0 条）⇒ 那位同伴要么没在跑…
EXIT=0
```

它**只读**台账与手稿，写的是 `out/report/STATUS-<ts>.{md,json}`（不写任何表）。

> 上面那段实跑是 **2026-11-21 的原文**，当时落的是旧布局的 `out\review\`；现在落 `out\report\`。
> 旧名不回填 —— 盘上已有的 `out\review\STATUS-*` 属于旧布局（按「不再支持」读）。

`--since 2026-11-21` 只看那之后；`--out` 换落点；`--json` 给外层四格。

### 3.7 `run-digest`：**CLI 没有这条命令**

任务清单里提到的 `run-digest` 在 CLI 侧**不存在**（现算 29 条子命令里没有它）：

```text
$ python -m agentflow run-digest
agentflow: error: argument <命令>: invalid choice: 'run-digest'
(choose from 'init', 'interject', 'submit', 'run-a', …)
EXIT=2
```

"趟次档案"是**网页侧**的读数：`GET /api/run-digest`（`webui/readers.py::run_digest()`，
从 `sessions/*.jsonl` 现算，不读也不落索引）。CLI 侧的等价物：

| 想知道 | CLI 用哪条 |
|---|---|
| 每张表几行 | `status`（§3.1） |
| 八格四态 | `stats gates`（§3.2） |
| 汇总成一份人读报告 | `status-report`（§3.6） |
| 一趟到底发生了什么（逐步事件） | 直接读 `sessions/<sid>.jsonl` / `data/events.jsonl`（每行一条，带 `seq`/`ts`/`kind`） |

```powershell
Get-Content "$WS\sessions\guide-s1.jsonl" | Select-Object -First 3
```

### 3.8 `inbox`：谁在等你回答

```text
$ python -m agentflow --root $WS inbox
  · 没有待回答的问题。
  · 最近一趟的停止理由：读不到（这些会话里没有 agent_run_end 事件 —— 要么还没跑过，
    要么会话记录被挪走了）
EXIT=0
```

`--sid <号>` 只看一个会话（**推荐**：真机每一趟都有自己的 sid，只看缺省会话会把
"它在等什么"读成"没有待答"）；`--json` 给一个数组（空就是 `[]`）。

---

## 4. 插话 / 答问 / 叫停（CLI 侧全都有，不用去网页）

### 4.1 插话：`interject`

给主控 M 插一句话。**这是用户在跑动中的唯一直连通道**；M 在下一步开头会看到它。

```powershell
python -m agentflow --root $WS interject --text "请优先做最小可验证的例子" --subject "用户插话" --sid guide-s1
```

```text
[interject] 已写入 i-000001（收件人 M）；M 在下一步开头会看到它 · 台账 D:\...\ws\sessions
EXIT=0
```

写在 `<工作区>/sessions/<sid>.jsonl` 里。**写下去 ≠ 被读到**：`status-report` 会如实报
"发过 1 条插话而一次都没被读到（`agent_interjection_seen` 0 条）"（见 §3.6 的实测输出）——
那是因为当时没有循环在跑。

### 4.2 答问：`answer`

先看 `inbox` 拿到 `qid` 与 `--sid`，再答：

```powershell
python -m agentflow --root $WS inbox
python -m agentflow --root $WS answer q-000001 --select "选项 A" --custom "补充说明" --sid guide-s1
```

> 本文的临时工作区里**没有**待答问题（没有真跑过活），所以第一行实跑是
> `没有待回答的问题。`；成功路径没跑，**错误路径跑了**（见下）。

问题号不存在时是**受控拒绝**（退出码 `2`，不是崩）：

```text
$ python -m agentflow --root $WS answer q-999 --custom "示例回答" --sid guide-s1
[answer] 没查成：没有 q-999 这个问题（当前待答：现在是空的）。若它落在别的会话里，用
`agentflow --root D:\...\ws inbox` 看会话号，再用 `--sid` 指名
EXIT=2
```

`--select` 可重复（DSH 的 `selected`：0/1/n 个）；`--custom` 对多选是**补充**、对单选是**覆盖**；
位置参数 `text` 等价于 `--custom`。回答是 append-only 的：答过还能查到。

### 4.3 叫停：`stop`

```text
$ python -m agentflow --root $WS stop --reason user --sid guide-s1
[stop] 停机开关已落：D:\...\ws\.agentflow-stop（reason=user）
[stop] 优雅停止：正在跑的那一趟会在下一步之前收工（E 的实验子进程也会被终止）；
       多轮自主跑在每轮之间收工
[stop] 停机（优雅停）：这一次名下没有在跑的程序
EXIT=0
```

| 旗标 | 什么时候用 |
|---|---|
| （不带） | 优雅停：做完当前这一步再收工，留检查点与运行记录 |
| `--force` | 不等待收尾，按进程登记把子进程连子孙一起杀掉 |
| `--status` | 只看：开关在不在、登记里哪些进程还活着、在跑的循环 |
| `--clear` | 撤掉停机开关（**接着跑之前必须先撤**，否则下一趟第 0 步就收工） |

```text
$ python -m agentflow --root $WS stop --status
[stop] 开关：D:\...\ws\.agentflow-stop（在）
[stop] 开关内容：{"reason": "user", "by": "user", "force": false,
  "at": "2026-11-21T23:13:06+08:00", "sid": "guide-s1", …}
[stop] 停机历史（墓碑三态）：none（…\runs\stop-closed.jsonl）
[stop] 登记着的活进程：0 个
[stop] 在跑的循环：没有
EXIT=0

$ python -m agentflow --root $WS stop --clear
[stop] 停机开关已撤：D:\...\ws\.agentflow-stop
EXIT=0
```

**CLI 与网页的差别（如实）**：`start --watch` 起网页时，网页上的"起一趟 / 插话 / 答问 /
叫停 / 改设置 / 改预算"写面默认是**关着的**（`--allow-writes` 才开）。CLI 这边没有这个
总开关 —— 上面四条命令在本机直接生效。想边跑边在浏览器里点，就 `start --watch --allow-writes`。

---

## 5. 续跑与切换

### 5.1 续跑：`--resume`

停下的那一趟（优雅停、强停、预算耗尽、等着人回答）都能接着跑。
**`--task` 要给回原来那句话**（指纹要一致，换了任务描述会被拒）：

```powershell
python -m agentflow --root $WS start --mode role --role M --project demo-run --sid guide-s1 `
  --task "验证一条最小研究回路：整数分拆的奇偶性" --resume --dry-run
```

```text
$ … start --mode role --role M --project demo-run --sid guide-s1 --task "…" --resume --dry-run
┌── 试运行：将要发生的一切（一个字节都不写、一次模型都不调） ──────────────────┐
│ 模式                role                                                      │
│ 预算                不限量（没给 --budget-usd，这个模式也没有缺省上限）        │
│ Lean                开关现在关（来源 缺省）；这一趟 --lean off；自检没跑        │
│ 会召唤              只跑 M 这一个循环；它按边可以召唤 H、G、C、E、A、B、D      │
│ 会写这些            工作区 …\ws\projects\demo-run（会新建…）                   │
│ 任务：验证一条最小研究回路：整数分拆的奇偶性                                  │
└──────────────────────────────────────────────────────────────────────────────┘
EXIT=0
```

真跑时把 `--dry-run` 去掉。`--resume` 的口径：

- `--rounds > 1` 时**只跑没做过的轮**；单趟时**接着上一趟停下的那一步之后**（停在等用户、步数用尽都能接）；
- 没有检查点时**从会话记录重建**那一步（`sessions/<sid>.jsonl`）；
- **任务指纹不一致会被拒（退出码 2）** —— 换了任务描述就别指望它接旧进度；
- `--sid` 必须指回同一趟，否则是另一趟；
- **别忘了先 `stop --clear`**：停机开关还在的话，下一趟第 0 步就收工。

### 5.2 换工作区 / 换 projects 落点

| 想换 | 用哪个 | 注意 |
|---|---|---|
| 换工作区（台账在哪） | `--root <目录>`（**写在子命令前**） | 见 §0.4 的缺省差异 |
| 换项目落点 | `--projects-dir <目录>` | 见 §1.2：都不给会落进仓库的真实 `projects/` |
| 换项目名 | `--project <名字>`（或 `project run --name`） | 名字已存在 = 热启动 |
| 换会话 | `--sid <号>` | 每一趟一个；`inbox` / `closing` / `answer` 都认它 |
| 一次性换 projects 落点 | 环境变量 `AGENTFLOW_PROJECTS_DIR` | 适合 CI / 脚本 |

### 5.3 `project list`：现在有哪些项目

```powershell
python -m agentflow project list --projects-dir "$WS\projects"
```

```text
projects 落点 D:\Incubator\agentflow\temp\userguide\ws\projects
┌────────────┬──────┬───────┬──────┬────────────────────────────────────┐
│ 项目       │ 状态 │ 冷/热 │ 上次 │ 说明                               │
├────────────┼──────┼───────┼──────┼────────────────────────────────────┤
│ guide-proj │ ✓ ok │   1/0 │ cold │ 文件夹存在且是一个初始化过的工作区 │
└────────────┴──────┴───────┴──────┴────────────────────────────────────┘
EXIT=0
```

空目录时：

```text
projects 落点 …\ws\projects
  · 还没有任何项目；第一次跑会自动取 project1。
EXIT=0
```

`project` 另外四条：`plan`（只说怎么跑、不写字节）/ `run`（真跑）/ `create`（建审阅型
项目，`--paper` 给那篇外部论文）/ `rebuild-run-index`（建网页读的趟次索引，幂等）。

**不花钱建一个项目工作区**（不给 `--topic` 就只做登记与冷启动，不跑模型）：

```powershell
python -m agentflow project run --name guide-proj --projects-dir "$WS\projects" --start cold
```

```text
… 缓存：使用 非 Lean 版缓存（p315 · 11/12）
… [开机自检] Lean 工具链 （开关：关 … 首屏不跑自检，完整读数请跑 `agentflow doctor`）
┌── 项目 guide-proj ──────────────────────────────────────────────────────┐
│ 本次启动            · cold 冷启动：文件夹不存在                          │
└─────────────────────────────────────────────────────────────────────────┘
  落点：              D:\...\ws\projects\guide-proj
  产物目录：          (本次没跑模型那一步)
  · 没给 --topic ⇒ 本次只做登记与冷/热启动，不跑模型、不分配运行号、不建 out 目录
[project] 本次没有跑模型那一步（没给 --topic）
EXIT=0
```

落下来的：`data/`、`library/`、`project.json`、`.agentflow-workspace`
（开 `--seed-literature` 时还有输入区 `reference/`，里面是种子 PDF 与 `SEED-README.md`）。

### 5.4 钱：`budget`

```powershell
python -m agentflow budget --status --project guide-proj --projects-dir "$WS\projects"
python -m agentflow budget --set 5 --project guide-proj --projects-dir "$WS\projects" --note "首设"
python -m agentflow budget --add 2 --project guide-proj --projects-dir "$WS\projects" --by user
```

```text
$ … budget --status …                      # 还没设过
  总预算：不限量（来源 unlimited）；已花：$0.000000；剩余：—
  追加历史 0 条；寄存器：…\projects\guide-proj\budget.json
  （这一趟没有设过预算 ⇒ 不限量。要设：`agentflow budget --set 5`；要追加：`agentflow budget --add 2`）
EXIT=0

$ … budget --set 5 … --note "首设"
[budget] 设总额度：{"ok": true, "path": "…\\budget.json", "total_usd": 5.0,
  "entry": {"kind": "set", "usd": 5.0, "by": "user", "at": "2026-11-21T23:19:17+08:00", "note": "首设"},
  "added_count": 1}
  总预算：$5.000000（来源 register）；已花：$0.000000；剩余：$5.000000
EXIT=0

$ … budget --add 2 … --by user
[budget] 追加：{"ok": true, "total_usd": 7.0, "entry": {"kind": "add", "usd": 2.0, …}, "added_count": 2}
  总预算：$7.000000（来源 register）；已花：$0.000000；剩余：$7.000000
EXIT=0
```

`--set` 是覆盖式（第一次设用它），`--add` 追加一笔且**运行期生效**（下一个闸门就受新上限约束）。
两者都落 `<落点>/budget.json`，`added[]` 是 append-only 的追加历史（`--set` 也记一条）。
`--status` 只读；`--fallback-usd` 在寄存器缺席时给一个显示值（不给就是不限量）。

---

## 6. 常见错误与三态读法

### 6.1 一张表：退出码怎么读

**三态纪律贯穿全部命令**：`0` = 查过了（含"全 0"）/ `1` = 查过了、有问题 /
`2` = **没查成**。`2` 绝不是 `0`。

| 命令 | `0` | `1` | `2` |
|---|---|---|---|
| `init` / `start` / `interject` / `answer` / `stop` | 做成了 | — | 用法错 / 受控拒绝 / 没查成 |
| `status` / `stats` / `status-report` / `tools` / `budget` | 读到了 | — | 工作区打不开 |
| `verify` | 无 error | 有 error（`--strict` 含 warning） | 没查成 |
| `doctor` | 齐 | 有缺（例：Lean 关着） | 没查成 |
| `closing` | 可以交 | 不能交（`--goal-not-met`，或机器格 fail） | 没查成（缺输入 / sid 不在盘上） |
| 退场命令 `rebuild` / `demo` / `repair` / `evidence migrate` | — | — | **一律 `2`**（见 §6.4） |

`run-agent` 是**六档**（唯一一条不是三态的）：`0` 完成并给了 `final` / `1` 行为异常 /
`2` 研究启动失败 / `3` 等待用户 / `4` 正常且中途停止（用户叫停、预算耗尽）/ `5` 正常但没 `final`。
`3` 不是失败：答完用 `--resume` 接着跑。

### 6.2 `unknown` vs `0` / `pass`：三处最容易读错的地方

1. **`state=checked` 不等于八格全过**：`stats gates` 的 `三态 checked=True` 只说"读数读到了"，
   同一屏下面可以写着 `fail=1  unknown=4`。
2. **`na` 不是 `pass`**：依赖的表一行都没有时记 `na`（"没有可判对象"），
   它跟"查过了没问题"是两回事。四种态一张表见 §3.2。
3. **`--json` 里先看 `state`，再看 `data`**：`state="unknown"` 时 `data` 里的 `0`
   不是"没有"，是"没读到"。外层四格是 `ok` / `state` / `data` / `problems`，
   `0 → checked`、`1 → failed`、`2 → unknown`（`CLI-CONTRACT.md` §4 的规矩）。

### 6.3 `--json` 怎么读（两条规矩）

```text
# 规矩一：先看外层 state，再决定 data 里的数字能不能用
$ python -m agentflow --root $WS stats gates --json
{ "checked": true, "state": "checked", "reason": "", "data": { "cells": [ … ] } }

# 规矩二：problems 非空时，那不是"警告"，是这一条读数不成立的理由
```

`status --json` / `verify --json` 是各自命令的原生形状（不是四格信封，`verify` 是
`{ok, deep, checked, errors, warnings, …}`）；`inspect` 那一组（`stats` / `evidence` /
`artifacts` / `analyze` / `tools` / `cache` / `budget` / `doctor` / `verify` / `status-report`）
才是四格信封，逐条契约见 `CLI-CONTRACT.md`。

### 6.4 退场命令：**退出码 2**，不是 0，也不是 1

`rebuild` / `demo` / `repair`（除 `--backfill-grades`）/ `evidence migrate` 在 2026-11-20
（业主批准 A4）已经退场：**实现删了，名字留着**，行为是"明确拒绝 + 给替代指引"。
其中 `demo` 在 2026-11-22 又走了一步（业主裁定 DEMORETIRE）：命令行之外，**演示本体、
它的产物与夹具也一并删除** —— `src/agentflow/demo.py` 与 `agentflow/demo/`
（`run/` / `sources/` / `fixtures/` / `selftest/`）都不在了，库里**没有**替代入口。

```text
$ python -m agentflow rebuild
[rebuild] 这条命令已退场（2026-11 业主批准 A4：移植期工具删除）。
EXIT=2

$ python -m agentflow demo      → EXIT=2（提示逐字写"已彻底移除"，不再指向库入口）
$ python -m agentflow repair    → EXIT=2
$ python -m agentflow evidence migrate $WS → EXIT=2
```

为什么是 `2` 而不是 `0`：`0` 会被读成"跑过了、没问题"。`2` = "这条路已经不存在了，
没查成"。替代物：`Store.rebuild()` 仍在库里；**`demo` 没有库层替代物** —— 只想看这台机器
行不行用 `agentflow doctor`，"记录链路能不能写"用 `init` → `submit` →
`run-a --provider fixture`（候选清单放在 `<工作区>/fixtures/candidates.json`）。
沿革见根 `README.md` 的 *Latest Updates* 与 §3。

### 6.5 六个常见错误（都实测过）

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `unrecognized arguments: --root …` （exit 2） | `--root` 写在子命令**后面**，而这条命令自己没有 `--root` | 挪到子命令前：`agentflow --root X status` |
| `[init] 拒绝 init：…不是空目录` （exit 2） | 目录里有你的投料 | 换空目录，或加 `--allow-foreign-entries` |
| `[answer] 没查成：没有 q-999 这个问题` （exit 2） | 问题号不对 / 落在别的 `--sid` | 先 `inbox`（`--sid` 可指定） |
| `[closing] 拒绝：没有会话 'x'` （exit 2） | `--sid` 不在盘上 | `inbox` 或看 `sessions/` 目录 |
| `[start] 缺一样要跑的东西` （exit 2） | 没给 `--task`（且不是 `--watch`） | 给 `--task`，或 `--mode role --role M` |
| `[interject] 这里不像工作区：… 既没有 sessions/ 也没有 data/` （exit 2） | 当前目录不是工作区（而 `interject` 的缺省工作区 = 当前目录） | `--root <工作区>`，或先 `init` |
| 新跑的活第 0 步就收工 | 上一趟的 `.agentflow-stop` 还在 | `stop --status` 看，`stop --clear` 撤 |

**跑测试当门**：`tests/` **不随仓库交付**，所以 `python -m pytest -q` 是**本机开发门**
（需本机有这个目录），不是给用户的门。用户侧的门是上面这几条命令的退出码。

---

## 7. 一次最小可复现流程（8 条命令，零花费）

复制粘贴即可；结尾那几条是"看读数"，随时可加。

```powershell
# 0) 开一个空工作区（换成你自己的路径）
$WS = "D:\Incubator\agentflow\temp\userguide\ws"
New-Item -ItemType Directory -Force -Path $WS | Out-Null

# 1) 初始化工作区
python -m agentflow --root $WS init

# 2) 先看这一趟会发生什么（不写字节、不花钱）
python -m agentflow --root $WS start --mode research --project demo-run --sid guide-s1 `
  --budget-usd 1 --task "验证一条最小研究回路" --dry-run

# 3) 不花钱建一个项目工作区（不给 --topic 就只登记）
python -m agentflow project run --name guide-proj --projects-dir "$WS\projects" --start cold

# 4) 列出项目
python -m agentflow project list --projects-dir "$WS\projects"

# 5) 看表
python -m agentflow --root $WS status

# 6) 看八格四态
python -m agentflow --root $WS stats gates

# 7) 跑收工门（读退出码：0 / 1 / 2）
python -m agentflow --root $WS closing --project-dir "$WS\projects\guide-proj"

# 8) 体检（读退出码：0 齐 / 1 有缺 / 2 没查成）
python -m agentflow --root $WS doctor
```

这一趟的预期读数（与本文实测一致）：第 2 条 `EXIT=0`、横幅里写着
`不花钱（试运行一次模型都不调）`；第 6 条 `pass=0 fail=1 unknown=4 na=3`；
第 7 条 `EXIT=2`（`收工结论：unknown`）；第 8 条 `EXIT=1`（Lean 关着 = 有缺）。

想接着往下走（跑真活）时的顺序：
`start … --budget-usd N` → 跑动中 `inbox` 看有没有问你的 → `answer` 答 →
不对劲就 `stop`（要接着跑先 `stop --clear` 再 `--resume`）→ 收工前 `closing`。

---

## 附录 A：本文命令 → 退出码 → 关键输出（逐条实跑）

`$WS` = `D:\Incubator\agentflow\temp\userguide\ws`；`$WS-seed` / `$WS-foreign` / `$WS-cwd` /
`ws-empty` / `ws-empty2` / `ws-fresh` 是另建的临时目录（同样在 `agentflow/temp/userguide/` 下）。
全部只写这些临时目录，**没碰** `projects/lp-ball-*`（那一步只用 `--dry-run` 演示，见 #61）。

| # | 命令 | 退出码 | 关键输出（首行/摘要） |
|---|---|---|---|
| 1 | `pip install -e agentflow --dry-run --no-deps` | 0 | `Would install agentflow-1.0.0` |
| 2 | `pip show agentflow` | 0 | `Editable project location: D:\Incubator\agentflow` |
| 3 | `agentflow --version` | 0 | `agentflow 1.0.0` |
| 4 | `python -m agentflow --version` | 0 | `agentflow 1.0.0` |
| 5 | `python -m agentflow.cli --version` | 0 | `agentflow 1.0.0` |
| 6 | `python -m agentflow --help` | 0 | 四个组 + 29 条旧名 |
| 7 | `python -m agentflow --help-legacy` | 0 | 29 行新旧对照 |
| 8 | `python -c "…build_parser()…len(choices)"` | 0 | `{29}` |
| 9 | `python -m agentflow --root $WS init` | 0 | `[init] 已初始化：…\ws\data` |
| 10 | `python -m agentflow --root $WS-foreign init` | **2** | `[init] 拒绝 init：…有 1 个不属于我们的条目：['我的笔记.txt']` |
| 11 | `… init --allow-foreign-entries` | 0 | `[init] 已初始化：…\ws-foreign\data` |
| 12 | `python -m agentflow --root $WS-seed init --seed-literature` | 0 | `[init] 种子文献：25 份投到 …\reference` |
| 13 | `… --root $WS-seed status` | 0 | `literature │ 0 │ processed=0 downloaded=0` |
| 14 | `cd $WS; … status`（**无** `--root`） | 0 | `工作区 D:\...\ws`（CLIFIX ① 之后缺省 = 当前目录；改前这里是 `D:\Incubator\agentflow`） |
| 15 | `… status --root $WS`（旗标在后） | **2** | `unrecognized arguments: --root …` |
| 16 | `cd ws-cwd; … init`（**无** `--root`） | 0 | `[init] 已初始化：…\ws-cwd\data`；紧接着 `… status` → `工作区 …\ws-cwd`（与 14 同一处） |
| 17 | `… --root $WS start … --dry-run`（research） | 0 | `模式 research（十角色循环）` / `不花钱` |
| 18 | `… start … --dry-run --json` | 0 | `"mode": "research"`（与横幅同源，CLIFIX ③）、10 个键 |
| 19 | `… start --mode topic … --dry-run` | 0 | `模式 topic` / `这一趟的落点还没有台账` |
| 20 | `… start --mode project … --dry-run` | 0 | `模式 project` / `0.5 美元（该模式的缺省值，不落盘）` |
| 21 | `… start --mode role --role M … --task "…" --resume --dry-run` | 0 | `模式 role` / `只跑 M 这一个循环` / `任务：验证一条最小研究回路…` |
| 22 | `… start --mode research --seed-literature … --dry-run` | 0 | 横幅不单列种子份数（见 §2.4） |
| 23 | `python -m agentflow start`（无 `--task`） | **2** | `[start] 缺一样要跑的东西…` |
| 24 | `… --root $WS status` | 0 | 18 行表 / 全 0 |
| 25 | `… --root $WS status --json` | 0 | `{"root": …, "search_requests": {"count": 0, …` |
| 26 | `… --root $WS stats gates` | 0 | `pass=0 fail=1 unknown=4 na=3` |
| 27 | `… --root $WS stats gates --json` | 0 | `{"checked": true, "state": "checked", "data": {…}}` |
| 28 | `… --root $WS stats errors` | 0 | `角色侧 0 / 系统侧 2 / 状态读数 0` |
| 29 | `… --root $WS stats cost` | 0 | `（0 行：一分钱都没记过）` |
| 30 | `… --root $WS closing` | **2** | `收工结论：unknown（exit 2） … 八格 0/8 pass` |
| 31 | `… --root $WS closing --sid guide-nope` | **2** | `拒绝：没有会话 'guide-nope'` |
| 32 | `… --root $WS closing --goal … --goal-not-met` | **1** | `收工结论：fail（exit 1）` |
| 33 | `… --root $WS closing --goal … --goal-met` | **1** | `收工结论：fail（exit 1）… 格 fail：substance` |
| 34 | `… --root $WS closing --project-dir …\guide-proj` | **2** | 八格部分可判，`审稿验收：未通过` |
| 35 | `… --root $WS verify` | 0 | `✓ ok 校验完成 错误 0 / 警告 0` |
| 36 | `… --root $WS verify --json` | 0 | `{"ok": true, "deep": false, "checked": {…}}` |
| 37 | `… --root $WS doctor` | **1** | `state=off` / `结论：这一趟做不了形式化核验` |
| 38 | `… --root $WS status-report` | 0 | `报告已落盘：…\out\review\STATUS-20261121-2313.md` |
| 39 | `… --root $WS tools --role A` | 0 | `工具总数：123（已装模块 17…）` / `角色 A 可用工具（54 个）` |
| 40 | `… --root $WS inbox` | 0 | `没有待回答的问题。` |
| 41 | `… --root $WS inbox --json` | 0 | `[]` |
| 42 | `… --root $WS interject --text … --sid guide-s1` | 0 | `[interject] 已写入 i-000001（收件人 M）` |
| 43 | `… --root $WS answer q-999 --custom … --sid guide-s1` | **2** | `[answer] 没查成：没有 q-999 这个问题` |
| 44 | `… --root $WS stop --reason user --sid guide-s1` | 0 | `停机开关已落：…\.agentflow-stop（reason=user）` |
| 45 | `… --root $WS stop --status` | 0 | `开关：…（在）` / `登记着的活进程：0 个` |
| 46 | `… --root $WS stop --clear` | 0 | `停机开关已撤：…\.agentflow-stop` |
| 47 | `python -m agentflow project list --projects-dir …` | 0 | `还没有任何项目；第一次跑会自动取 project1。` / 有项目时出表 |
| 48 | `… project run --name guide-proj --projects-dir … --start cold` | 0 | `[project] 本次没有跑模型那一步（没给 --topic）` |
| 49 | `… project list --projects-dir …`（已有项目） | 0 | `guide-proj │ ✓ ok │ 1/0 │ cold │ 文件夹存在且是一个初始化过的工作区` |
| 50 | `… budget --status --project guide-proj --projects-dir …` | 0 | `总预算：不限量（来源 unlimited）；已花：$0.000000` |
| 51 | `… budget --set 5 … --note "首设"` | 0 | `总预算：$5.000000（来源 register）` / `added_count: 1` |
| 52 | `… budget --add 2 … --by user` | 0 | `总预算：$7.000000` / `added_count: 2` |
| 53 | `… start --root $WS … --dry-run`（`--root` 写在**子命令后**） | 0 | `工作区：…\ws\projects\x`（`start` 自己收 `--root`） |
| 54 | `… --root $WS evidence verify …\runs\nope` | **2** | `[evidence] 没查成：…\evidence.json 不存在` |
| 55 | `… --root $WS evidence migrate $WS` | **2** | `[evidence migrate] 这条命令已退场…` |
| 56 | `python -m agentflow rebuild` | **2** | `[rebuild] 这条命令已退场…` |
| 57 | `python -m agentflow demo` | **2** | `[demo] 这条命令已退场…` |
| 58 | `python -m agentflow repair` | **2** | `[repair] 这条命令已退场…` |
| 59 | `python -m agentflow run-digest` | **2** | `invalid choice: 'run-digest'` |
| 60 | `AGENTFLOW_PROJECTS_DIR=…; … start --project env-proj --dry-run` | 0 | `工作区：…\ws\projects\env-proj` |
| 61 | `cd $WS; … start --project cwd-proj --dry-run`（无 `--root`） | 0 | `工作区：D:\Incubator\projects\cwd-proj`（**写进真实 projects/**） |
| 62 | `cd ws-empty; … start --mode topic --task t --dry-run`（无 `--root`） | 0 | `工作区：D:\...\ws-empty`（CLIFIX ① 之后 `start` 的缺省也是当前目录） |
| 63 | `cd ws-empty2; … budget --status`（无 `--root`） | 0 | `[budget] D:\...\ws-empty2`（`budget` 的缺省 = cwd） |
| 64 | `cd ws-empty2; … interject --text x --sid s1`（无 `--root`） | **2** | `[interject] 这里不像工作区：…\ws-empty2 既没有 sessions/ 也没有 data/` |
| 65 | `cd ws-empty; … artifacts record x.txt --producer me`（无 `--root`） | 0 | `已登记 x.txt ← me`，台账落在 `…\ws-empty\ARTIFACTS.jsonl`（改前这块会落进一个字面叫 `None` 的目录） |

**没有跑过的**（如实登记）：所有非 `--dry-run` 的 `start` / `run` / `run-agent` / `pipeline`
（要模型 key、要花钱）；`web` / `start --watch`（要起服务器）；`cache warm`（会花钱）；
`run-a` / `run-b`（要检索后端或联网）；`repair --backfill-grades`（会改台账）。
这些的旗标含义来自 `--help`，不是本文的实跑读数。
