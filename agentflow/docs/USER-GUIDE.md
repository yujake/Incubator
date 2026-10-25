# 用户手册：一个入口、在哪看、钱怎么算

> 读者是**用的人**，不是改它的人。下面的命令 2026-10-23 真机跑过；
> 权威口径永远是代码：`python -m agentflow start --help`、`python -m agentflow doctor --help`。
> 本手册里的旗标与文案都是从这两份 help 与 `cli.py` 里逐字取的，改代码就要回来改这里。

---

## 0. 三分钟起步

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'

# ① 先看看会发生什么（不建目录、不写字节、一次模型都不调）
python -m agentflow --root projects\my-topic start --task "研究这个问题：<一句话>" --dry-run

# ② 真跑（工作区不存在或为空时，start 自己会把它初始化好）
python -m agentflow --root projects\my-topic start --task "研究这个问题：<一句话>" --budget-usd 5

# ③ 要边跑边盯（打印 URL / 工作区 / sid / 当前轮；这一趟跑完网页就收）
python -m agentflow --root projects\my-topic start --task "同一句话" --watch --port 52060 --open

# ④ 只想再看那个网页（不跑活，Ctrl-C 停）
python -m agentflow --root projects\my-topic start --watch --port 52060 --open
```

> 没把 `agentflow` 装进 site-packages 的话，上面三行 `$env:` 必须先在**同一个窗口**里执行，
> 否则报 `No module named agentflow`。装过之后 `agentflow <命令>` 与
> `python -m agentflow <命令>` 是同一个入口。

---

## 1. 统一入口：`agentflow start`

一句话（`--task`）+ 四个问题：**干什么 / 在哪干 / 花多少钱 / 开不开 Lean**。其余都是它的子模式。
`start --help` 把旗标分成四组，逐组照它读：

| help 里的组 | 管什么 | 最常用的旗标 |
|---|---|---|
| 要跑什么 | 这一趟走哪条路 | `--task`、`--mode`、`--role`、`--project` |
| 在哪干 | 落点 | `--root`、`--projects-dir`、`--start`、`--out`、`--books`、`--books-limit`、`--text-store-dir` |
| 花多少钱 / 开不开 Lean / 要不要盯 | 额度、Lean、监督 | `--budget-usd`、`--lean`、`--watch`、`--dry-run`、`--json`、`--host`、`--port`、`--open`、`--token`、`--allow-writes`、`--no-settings-write` |
| 透传下去的老旗标（与同名子命令同义） | 老命令那几个开关 | `--max-calls`、`--provider`、`--max-steps`、`--wall-clock-sec`、`--rounds`、`--sid`、`--resume`、`--stop-file`、`--allow-foreign-entries` 等 |

### 1.1 `--mode` 不写就按目录状态推断

`--mode` 的取值是 `auto` / `topic` / `role` / `research` / `project` / `cold` / `warm`
（缺省 `auto`）。`auto` 的四档推断（与 `start --help` 的 description 逐字同口径）：

| 现状 | 推断结果 |
|---|---|
| 没给 `--task` 且给了 `--watch` | 只开网页（`start --help` 说"只开网页"） |
| 项目文件夹不存在或为空 | cold（项目工作区，会新建） |
| 已初始化、且 `data/tasks.jsonl` 有行 | research（十角色循环，角色缺省 M） |
| 已初始化、但没有台账 | warm（项目工作区） |

显式那几档：`--mode role` 必须给 `--role`（可选 `A`–`H` 与 `V`/`L`/`M`）；
`--mode research` 不用给角色（缺省 M）；`--mode cold` / `--mode warm` 与 `--start cold|warm` 表达同一件事。

缺参数时报的是人话，会**点名**该给哪个旗标（不是 argparse 那句
`the following arguments are required`）：

```
[start] 缺一样要跑的东西：给 --task "这次要做的事"（研究 / 项目 / 主题三档都要它）。
只想开网页监督就加 --watch；只想跑某一条角色的循环就 --mode role --role <角色>；
想先看看会发生什么就再加 --dry-run
```

### 1.2 `--dry-run`：六格预检怎么读

它只说、不做：**不建目录、不写字节、一次模型都不调、也不起 Lean 自检子进程**。
（`--root` 指向的目录在这一档里一个都不会被创建 —— 这是真机验过的那一条。）

```
┌── 试运行：将要发生的一切（一个字节都不写、一次模型都不调） ──────────────────────────────┐
│ 模式                topic                                                              │
│ 模型                deepseek-flash（base=https://api.deepseek.com/v1）                  │
│ 预算                3 美元（命令行显式给的，会落盘）                                     │
│ Lean                开关现在关（来源 缺省）；这一趟 --lean auto；自检没跑（试运行不启动检查器） │
│ 会召唤              不召唤任何角色（端到端跑主题：检索 / 作答 / 逐字回验都不经角色循环）    │
│ 会写这些            工作区 <绝对路径>；out/run-N 六件产物                                │
│ 任务：把这篇论文审一遍                                                                   │
│ 这一趟的落点还没有台账（没有 data/tasks.jsonl）                                           │
└────────────────────────────────────────────────────────────────────────────────────────┘
  工作区：            <绝对路径>
  · 不花钱（试运行一次模型都不调）
```

六格逐格的读法（下面这份是本机 2026-10-23 的输出抄录；终端窄的时候右边会被截断，
截断只发生在显示上，`--json` 那一份永远是完整值）：

1. **模式**：`topic` / `research（十角色循环）` / `role` / `project` / `web` 之一 —— 它与 `--mode` 不是同一个词：
   `--mode cold` / `warm` 在这一格显示 `project`，`--mode research` 显示 `research（十角色循环）`。
2. **模型**：模型名 + `base_url`。key 一律来自环境变量/`settings.json`，命令行不许传。
3. **预算**：显式给的写"（命令行显式给的，会落盘）"；没给的写"（该模式的缺省值，不落盘）"；
   这个模式没有缺省上限时写"不限量（没给 --budget-usd，这个模式也没有缺省上限）"。
4. **Lean**：开关**现在**的开/关与来源 + 这一趟的 `--lean` 档 + "自检没跑（试运行不启动检查器）"。
5. **会召唤**：这一趟按边能不能召唤、召唤谁（`research` 那一档写"起十角色循环（--subagents）"）。
6. **会写这些**：工作区（会不会新建）、`out/run-N 六件产物`、以及显式额度时的
   `预算寄存器 budget.json（N）`。只开网页那一档是"（不写任何东西）"。

`--dry-run --json` 的键集合逐字是 `cli.START_PLAN_KEYS`：
`mode` / `task` / `workspace` / `project` / `model` / `budget` / `lean` / `summons` / `writes` / `spend`。

### 1.3 `--watch`：打印四格，跑完就收

- 起网页后**立刻**打印四格：`网页：<URL>`、`工作区：<绝对路径>`、`会话：<sid>；当前轮：<N>`；
  `--json` 那一档是 `{url, root, sid, round}`（一行）。
- **不带 `--task`**：只开网页，服务一直开着，`Ctrl-C` 停（此时会多印一行 `Ctrl-C 停。`）。
- **带 `--task`**：服务在后台线程里，边跑边可监督；**这一趟跑完就收**——想接着看就再敲一次
  `start --watch`（或老命令 `web`）。
- `--host` 缺省 `127.0.0.1`（只听本机）；`--port` 缺省 `8788`，`--port 0` 让系统挑；
  `--token` 也可以走环境变量 `AGENTFLOW_WEB_TOKEN`。写面缺省**只读**：`--allow-writes` 才放开
  `/api/` 下那六条写端点（`POST /answer` 是既有写路径，缺省也放行），`--no-settings-write`
  只关 `POST /api/settings`。

---

## 2. 三条老命令仍是别名（行为逐字不变）

`start` 与四条老命令（`run` / `run-agent` / `project run` / `web`）**共用一个执行体**
（`cli._run_spec`）：解析层一个字没动，只在执行层收口。所以老命令的旗标、缺省值与 `--help`
输出与升级前逐字一致 —— 已有的脚本不用改。

| 你想干的事 | 统一入口 | 老命令（等价，逐字不变） | 什么时候用老命令 |
|---|---|---|---|
| 端到端跑一个主题 | `start --mode topic --task <主题>` | `run --topic <主题>` | 脚本里已经在用 `run`，或要 `--out` / `--fulltext` / `--max-calls` 那一套 |
| 跑一条角色的循环 | `start --mode role --role <角色> --task <一句话>` | `run-agent <角色> --task <一句话>` | 单角色调试、`--drive`、`--rounds` 多轮 |
| 十角色循环 | `start --mode research --task <一句话>` | `run-agent M --task <一句话> --subagents` | 需要显式指定顶层角色时 |
| 项目工作区 | `start --mode project --task <一句话>`（或 `--project <名字>`） | `project run [--name <名字>]` | 要用 `project list` / `project plan` / `project create --paper <pdf>` 时 |
| 只开网页 | `start --watch` | `web` | 只要 URL 一行的 `--json`，或脚本里按 `web` 的参数调用 |

两处**必须知道**的差别（这是别名与统一入口唯一不同的地方，也是刻意的）：

1. **`--root` 必须写在子命令之前**：`--root X start --task ...` 对；`start --root X` 也对
   （`start` 自己也有一个 `--root`，与顶层同义）；但 `run --root X` / `web --root X` 会被
   argparse 拒（退出码 2）。
2. **`project run` 从来不读 `--root`**（它认 `--projects-dir` 或环境变量/配置里的 projects 落点）；
   `start` 这一层做了额外的一格：给了 `--root` 又没给 `--projects-dir` 时，
   `--project` 的落点跟着 `--root` 走（`<root>/projects`）。老命令保持原样。

---

## 3. 钱：`--budget-usd` 会落盘，并点名"寄存器 N → M"

- 寄存器是工作区里那一份 `<工作区>/budget.json`：一格 `total_usd`（总额度）+ append-only 的
  `added[]`（谁、什么时候、多少、为什么）。
- **显式给了 `--budget-usd` 就落盘**（`start` / `run` / `run-agent` / `project run` 都一样），
  并打印一行点名"原来多少 → 现在多少"：

  ```
  · 预算：0.5 → 10 美元（寄存器里原来是 0.5，命令行给了 10；已按命令行落盘，旧的那一笔留在追加史里）
  ```

  原来没有寄存器时打的是 `预算：10 美元（已落盘 <路径>）`；与寄存器一致时打
  `预算：10 美元（与寄存器一致）`。旧的那一笔按 `kind="set"` 留在 `added[]` 里，不删。
- **不给就按各模式的缺省**，且**一个字节都不写**：topic 1.0 / project 0.5 / role 不限
  （主题那一趟的缺省 1.0、项目那一趟 0.5，角色循环没有缺省上限 —— 由墙钟与步数管）。
- 写不成（只读盘、坏寄存器被拒）时**这一趟不跑**：拿旧额度接着跑等于让寄存器静默压过
  `--budget-usd`。两行说明都在 stderr 上，退出码 2。
- 额度是**累计**上限：已花取 `usage_ledger` 的累计（唯一权威账），剩余 = 总额度 − 已花；
  可以略微越界（最后一步已发出的费用收不回），网页显示"已越上限"——那是读数不是错误。

```powershell
python -m agentflow --root <ws> budget --status          # 总额度 / 已花 / 剩余 / 追加历史
python -m agentflow --root <ws> budget --set 10 --note "第二批"
python -m agentflow --root <ws> budget --add 5 --note "让它跑完"
```

---

## 4. `--lean on|off|auto`：三档各自意味着什么

| 档 | 这一趟做什么 | 形式化结论 |
|---|---|---|
| `--lean` 或 `--lean on` | 注入 `AGENTFLOW_LEAN_ENABLED=1`（并清掉提示词侧的读数缓存） | 检查器真跑过才记 `verified` |
| `--lean off` | 注入 `AGENTFLOW_LEAN_ENABLED=0` | 不做形式化，如实记"没核到" |
| `--lean auto` | **先跑一次自检**（`refresh=True`，不吃旧缓存），`usable` 才当 on | 见下 |

三档的两条细节：

1. **不写 `--lean` 与 `--lean off` 不是一回事**：不写就一个字都不动（命令行"从不提 Lean"
   不等于"要求关掉 Lean"）；只有显式写 `--lean off` 才注入 `=0`。裸写 `--lean` 等于 `--lean on`。
2. **`auto` 不是 usable 时照常跑，但结论降级并点名原因**：

   ```
   [lean] --lean auto：自检没给出 usable（<state>）⇒ 这一趟照常跑，但一切形式化结论记 unknown。原因：<为什么>
   ```

   这就是"防虚构 Lean 环境"那一档：一个只打印版本、永远 0 退出的回显器在前一档里像"可用"，
   自检里必须是 `unusable`。跑之前想先看清这台机器，用 §6 的 `doctor`。

`--lean` 只出现在 `start` / `run` / `project` 三条路上（`web` 那一档不碰它）。

---

## 5. 网页有哪几页、各看什么

九页（导航八条，`/run/<sid>` 是第九页）：

| 页 | 看什么 | 读的端点 |
|---|---|---|
| 对话 Home | 这个工作区的来回、待答问题、会话概览、台账 | `/api/state`、`/api/chat`、`/api/live` |
| 一趟详情 Run | 某次跑（一个 `sid`）的全过程与逐条事件 | `/api/run/<sid>`、`/api/run-index`、`/api/run/<sid>/events`、`/api/live` |
| 在飞 Live | 有没有在跑、进程面、停机开关与历史、名册树 | `/api/live`、`/api/status-reports`、`/api/usage`、`/api/roster` |
| 预算 Budget | 总额度、已花、剩余（含"已越上限"）、追加历史 | `/api/budget` |
| 证据链 Evidence | 命题、猜想、实验、审校发现、引文回验、证明级验证、秘书决策 | `/api/evidence` |
| 产物 Artifacts | 落盘了什么（含交付说明与 sha 对账） | `/api/artifacts` |
| 验收 Acceptance | 五条判据 + 五种辅助读数 | `/api/acceptance` |
| 本机 Machine | provider / 模型 / 开关（key 恒显示 `***`） | `/api/machine` |
| 使用说明 Help | 本手册的网页版 | —（一条端点都不调） |

四格这轮变过的读数，逐字读法：

- **名册面板的收件箱徽标**（「在飞」页）：写 `未读 N · 已读未 ack M`
  （没有未消条目时写"收件箱：没有未消的条目"，读不到时写"收件箱：未读到"）。
  `未读` = `queued + claimed`（还没被读进任何一步）；`已读未 ack` = `seen`（读了、缺的是那个 ack）。
  点开节点另给三格：`未读` / `已读未 ack` / `未消`（`open_total`），以及"其中状态读不出来 N 条"。
  真身是工作区里的 `out/roster/<父编号>.jsonl`（append-only，另加对照表 `<父编号>-index.jsonl`）。
- **会话概览的「待答」与「说一句」的副标题**：两处都写 `（全局待答清单）` —— 同一份清单、同一个数
  （不按当前选中的会话过滤：别的会话在等人回答也是事实，而且 `qid` 只在会话内唯一）。
- **台账卡**：写 `台账写入 N 笔（其中 commit 标记 M 行）`。`N` 是写入笔数（= 非 commit 标记的行数），
  `M` 是提交标记的行数；两者相加 = `data/events.jsonl` 的总行数（每提交一次事务占两行）。
  改前那一格数的是文件总行数、名字却叫"事件 N 条"，于是它把"写了多少笔"翻倍地回答。
- **进程面（「在飞」页）**：列名逐字是 `宿主进程 pid`，表头上方有一句说明 —— 同一趟 run 里
  所有角色共用同一个宿主进程，所以多行会印出同一个号；要分辨"这一行是谁"看角色与会话号
  （绝对编号 `task_id` 在名册那张卡里）。
- **状态报告里的"在飞"**（`status-report` / `agentflow status-report`）：只数**实例行**
  （`tasks` 里 `kind` 为空、`status ∈ {pending, running}` 的那些），**不算板项行**
  （`kind` 非空：`message` / `notice` / `report` / `delegation`，它们的 `status` 永远是 `pending`）。
  不分开数会把"板上有 19 条要消的项"写成"在飞 19"。

---

## 6. `doctor`：两级自检的区别与代价

| | 触发方式 | 抓什么 | 代价 |
|---|---|---|---|
| 第一级（启动兜底） | 任何子命令**碰巧** import 到一个坏模块 | `SyntaxError` / `ImportError`，打 `文件:行 + 错误`，退出码 2 | 0 毫秒（只在那条 `except` 上） |
| 第二级（显式全扫） | `doctor --selfcheck` | 逐文件 `compile()`，坏文件报 `文件:行:列 + 错误`；不探测工具链、不编译 Mathlib、不花钱 | 秒级（本机实测 238 个文件 / 1234 ms） |

第二级的退出码三档：0 干净 / 1 有坏文件（或读不了的文件）/ 2 没查成（连包目录都找不到）。
它按 `(路径, mtime_ns, size)` 在进程内缓存 —— 同一次体检里重复扫、或判据连着扫两次都命得中。

```
[自检] 包内源码：238 个文件（本次真扫 238、命中 stat 缓存 0；1234.0 ms）
[自检] 结论：语法错误 0 个
```

不带开关的 `doctor` 是另一件事：探工具链（有没有模型 key、有没有证明检查器、Mathlib 对不对得上）
并跑一次 Lean 工具链自检，同样不发起任何模型调用；退出码 0 齐 / 1 有缺 / 2 没查成。
后者每个没通过的项后面会跟一条 `fix_hint`（可直接复制执行的命令原文），`--json` 里在
`data.checks[].fix_hint` —— 用法见下面 7.4。

---

## 7. 命令行：四个入口 + 28 个旧名（一个都没删）

`agentflow --help` 的首屏现在只印四行入口 + 一段"旧名仍可用"。`agentflow --help-legacy`
印出完整的 28 行对照表（旧名 → 新路径），那张表在下面 7.2 也抄了一份。

### 7.1 四个入口各管什么

| 入口 | 一句话用途 | 成员 |
|---|---|---|
| `incubate` | 孵化：把一趟研究开起来、管起来 | `init`、`start`、`stop`、`status`、`answer`、`inbox`、`submit` |
| `inspect` | 查看：只读的读数与检查 | `status-report`、`stats`、`evidence`、`artifacts`、`analyze`、`tools`、`cache`、`budget`、`doctor`、`verify` |
| `run` | 跑：流水线与角色循环，以及它们的维护 | `topic`（= 旧 `run`）、`pipeline`、`run-a`、`run-b`、`run-agent`、`repair`、`rebuild`、`project`、`closing` |
| `serve` | 服务：网页与离线演示 | `web`、`demo` |

写法是 `agentflow <入口> <成员> [旗标]`，例如：

```powershell
agentflow inspect stats cost --json          # 钱花在哪了
agentflow incubate start --task "…" --mode research --dry-run
agentflow run topic --topic "Saxl 猜想"      # 与 agentflow run --topic … 同一条命令
```

三件要知道的事：

1. 新路径与旧名是**同一条命令**（不是别名层）：`agentflow inspect stats` 在解析之前就折回
   `agentflow stats`，所以旗标、缺省、输出、退出码一个字都不差。
2. 组名本身只出现在首屏，不在 `--help` 的子命令清单里 —— 子命令数仍然是 28。
3. `run` 这个组的组名同时是旧命令名：`agentflow run`（不带成员）仍然是"端到端跑一个主题"，
   组页走 `agentflow run --help`（那一页会把旧命令的全部旗标接在后面）。

### 7.2 新老命令对照表（`agentflow --help-legacy` 的那一份）

| 旧名 | 新路径 | 旧名 | 新路径 |
|---|---|---|---|
| `init` | `agentflow incubate init` | `doctor` | `agentflow inspect doctor` |
| `start` | `agentflow incubate start` | `verify` | `agentflow inspect verify` |
| `stop` | `agentflow incubate stop` | `run` | `agentflow run topic` |
| `status` | `agentflow incubate status` | `pipeline` | `agentflow run pipeline` |
| `answer` | `agentflow incubate answer` | `run-a` | `agentflow run run-a` |
| `inbox` | `agentflow incubate inbox` | `run-b` | `agentflow run run-b` |
| `submit` | `agentflow incubate submit` | `run-agent` | `agentflow run run-agent` |
| `status-report` | `agentflow inspect status-report` | `repair` | `agentflow run repair` |
| `stats` | `agentflow inspect stats` | `rebuild` | `agentflow run rebuild` |
| `evidence` | `agentflow inspect evidence` | `project` | `agentflow run project` |
| `artifacts` | `agentflow inspect artifacts` | `closing` | `agentflow run closing` |
| `analyze` | `agentflow inspect analyze` | `web` | `agentflow serve web` |
| `tools` | `agentflow inspect tools` | `demo` | `agentflow serve demo` |
| `cache` | `agentflow inspect cache` | | |
| `budget` | `agentflow inspect budget` | | |

旧名**这一版全部保留**（业主口径：新指令接管且行为确认正常之后再清理；清理不是这一版的事）。
`repair` / `rebuild` / `demo` / `evidence migrate` 四条的实现在这一版已经搬出 CLI
（`tools/legacy_cli/`），CLI 里只剩一行转发 —— 下一版删除时只删那一行与那个目录。

### 7.3 `stats` 的四张读数

`agentflow stats <errors|flow|cost|gates|all> [--root <工作区>] [--json]`。四张表都是
只读、零模型调用、不落盘；`all` 是四张一起打（三态取合取：有一张没查成，合计就是 unknown）。

| 读数 | 回答什么问题 | 数据源 | 主要字段 |
|---|---|---|---|
| `errors` | 每种角色犯了几次"错误动作"，各属哪一类 | `events.jsonl` 的 `tasks` 行 + `sessions/*.jsonl` | `by_role` / `role_total` / `total` / `categories` |
| `flow` | 每种角色走了几步、各是什么形状、被拦下多少、转投多少 | 同一批会话记录（`agent_step` 的 `shape` 与 `result`） | `roles[角色].steps/shapes/blocked/relayed`、`totals` |
| `cost` | 钱与 token 按角色、按阶段怎么分布 | `data/usage_ledger.json` | `by_role` / `by_scope` / `total`（`usd` / `tokens_*` / `attempts` / `rows`） |
| `gates` | 收工门八格各是什么状态（三态一张表） | 现跑 `closing.check_closing`（不读缓存） | `cells` / `counts` / `machine_pass` / `can_close` / `verdict` |

三态在这里是硬口径：

- `state=checked`：读到了。**全 0 也是 checked** —— "这一趟 0 次错误动作"是一个答案。
- `state=unknown`：没查成（工作区不在、事件流读不明白…）。此时表里的 0 不是"没有"，是
  "没读到"；`problems` 里逐条写着为什么。
- `errors` 那一档还有个老形态：不给 `--readout` 时它按 `errorstats` 原来的样子打（那份输出
  有消费者）；`--readout` 给出与新三张表同一个五键形状，数值与三态两处必须一致。

`gates` 需要知道"哪个项目"才知道论文/验收那几格查什么：

```powershell
agentflow inspect stats gates --root projects\my-topic --project-dir projects\my-topic --report out\report.md
```

不给 `--project-dir` 时那几格如实记 `unknown`（不是 pass）——十格里有几格 unknown 是正常的，
但"unknown 当成通过"不是。

### 7.4 `doctor` 的 `fix_hint`：失败项后面那条可以直接复制的命令

`agentflow inspect doctor` 只诊断、**不会替你改**（没有 `--fix`，也不写任何配置）。
它把逐项读数打完后，会多打一段"下一步"，每个没通过的项后面跟一条能直接复制的命令：

```
下一步（2 档没通过；doctor 只诊断，不会替你改）
  · [model_key] base=… ；model=…（环境变量与 agentflow/settings.json 的 model.api_key 两处都没有 key）
    照这条改：$env:AGENTFLOW_MODEL_API_KEY='<把模型 key 填在这里>'
  · [mathlib_root] 没找到 Mathlib 工程根
    照这条改：$env:AGENTFLOW_MATHLIB_ROOT='<Mathlib 工程的根目录>'
```

`--json` 里同一份判定在 `data.checks`：每项 `{name, state, detail, fix_hint}`，`state` 取
`ok` / `fail` / `unknown` / `off`（`off` = 你自己关掉的，不是缺陷）。脚本可以只读那一格：

```powershell
agentflow inspect doctor --json | ConvertFrom-Json | ForEach-Object { $_.data.checks } |
  Where-Object { $_.state -eq "fail" } | ForEach-Object { $_.fix_hint }
```

`doctor --selfcheck` 是另一档（只扫包内源码、秒级、不碰工具链）；它的 `checks` 里只有
`package_syntax` 一项 —— 没探测的东西不许下结论。

### 7.5 `--json` 的契约（`inspect` 那一组）

从 `inspect` 那一组走的 `--json` 一律是外层四格：

```json
{"ok": true, "state": "checked", "data": { … }, "problems": []}
```

`state` 取 `checked`（查过了）/ `failed`（查过了有问题）/ `unknown`（没查成），与退出码
0 / 1 / 2 一一对应。旧路径上早就有 `--json` 的那六条（`stats`/`tools`/`cache`/`budget`/
`doctor`/`verify`）保持原样不变 —— 要外壳就在前面加组名。逐条的字段表见
`docs/CLI-CONTRACT.md`。

### 7.6 `cache` 那一组

`cache status` 是只读读数（已落盘 / 新鲜 / 覆盖 / 缺哪几段 + key 变化提醒），
`cache warm --lean on|off|both` 是**真预热**（会花钱；先看 `--dry-run` 那一档，它花 0）。
两档读的是 `cachectl` 里同一份实现（命令行与网页按钮同源）。

---

## 8. 用户投料目录第一次进来：`--allow-foreign-entries`

**为什么需要它**：工作区初始化会在目标目录里建出整套 `data/` 与 `library/`。如果那个目录本来
就有你的东西（一篇 PDF、几份笔记），框架**默认拒绝**——在别人的目录里凭空建出整套数据是
不可逆的（实测事故：一个复核脚本往只放着 `我的资料.txt` 的文件夹里写了 19 个条目）。
拒绝原文是这样的：

```
[init] 拒绝 init：<目录> 既不是工作区（没有 data/）、又不是空目录 —— 里面有 1 个不属于我们的条目：['用户投料.txt']。
… 三条出路：① 这确实是新工作区 ⇒ 换一个空目录；② 确认就要在这里建 ⇒ `init(force=True)`（或 CLI `init --force`）；
③ 走工具层：`projects.ensure_project`，它本来就有「拒绝外来目录」的守卫。
[init] <目录> 里那 1 个条目要么是用户自己投的料（例如一篇 PDF）、要么是这个目录本来就不干净。若它就是要用的工作区：
加 --allow-foreign-entries 再跑一次 —— 它会先落 .agentflow-workspace（`store` 的白名单出口），再按工作区初始化；
那些文件不删、不改，只是从此算这个工作区的条目。
```

加了开关之后：

```powershell
python -m agentflow --root projects\my-topic init --allow-foreign-entries
```

它先落一个 `.agentflow-workspace` 标记（`store` 明写的白名单出口），再照常 init；你的文件
**不删、不改**。标记文件里记着是谁、什么时候、认了几个外来条目：

```
agentflow workspace
created_at=<ISO 时间>
created_by=cli init --allow-foreign-entries
accepted_foreign_entries=1
accepted_entries=用户投料.txt
```

三个要点：

1. `--force` **不是**这条出口（它是清空重建）。要保住自己的文件，用 `--allow-foreign-entries`。
2. 同一个开关也长在 `run-agent` 与 `start` 上（`start` 走 role 那条路时用它）。
3. **项目那一档不用它**：`--mode project` / `project run` 落的 `projects/<名字>` 如果非空，
   走的是"收编"——把原有条目逐条记进项目卡 `project.json` 的 `user_files`，一个字节都不动。

---

## 9. 让它跑活：老命令 `run-agent` 的常用旗标

```powershell
python -m agentflow --root projects\my-topic run-agent M --task "<题目>" `
  --semantic-review --provider crossref,doaj,europepmc,openalex `
  --budget-usd 5 --sid my-1 --stop-file projects\my-topic\runs\.agentflow-stop
```

| 参数 | 含义 |
|---|---|
| `--task "<文本>"` | 题目（必填）；也可以是"继续上一趟"的话 |
| 角色（位置参数） | `run-agent M` 里的 `M`：`A`–`H` 与 `V`/`L`/`M` |
| `--budget-usd N` | 累计上限；显式给了就落盘（见 §3） |
| `--sid` | 会话号（台账按它分片；`--resume` 也认它） |
| `--resume` | 从检查点续跑（没有检查点时按会话记录重建那一步） |
| `--max-steps N` | 步数**报告**阈值（每满几步向父代理报一次账；不设步数闸） |
| `--wall-clock-sec N` | 墙钟上限（秒）；不给 = 不设上限 |
| `--rounds N` / `--report-every N` | 跑几轮 / 每几轮汇报一次 |
| `--stop-file <路径>` | 优雅停的开关文件：它一出现就停（步与步之间查） |
| `--semantic-review` | 给 H 接上语义判据 |
| （无） | F 的攻坚推理不是开关：它出场就有推理缝（2026-10-26 业主裁定，原来的那个 flag 已删除） |
| `--experiment-reasoning` | 给 E 接上写脚本的推理 |
| `--provider a,b,c` | A 的检索后端（`openalex` / `crossref` / `doaj` / `europepmc` / `fixture`） |

**停**：`python -m agentflow --root <ws> stop --reason "<一句>"`（`--force` 连子孙进程一起杀；
`--status` 只看开关与还活着的进程；`--clear` 撤掉遗留的开关）。

---

## 10. 退出码六档（别把 1 当"正常结束"）

| 码 | 含义 |
|---|---|
| 0 | 正常完成（给了 `final`） |
| 1 | **行为异常**（没接线 / 没认 key / 没返回 / 连不上 / 坏 JSON 或坏参数超限 / 没 notify，以及任何没登记的 `stop_reason` 一律归这一档） |
| 2 | 研究启动失败（检查点读不到、指纹不符、上一趟已收工、重建不出那一步），或用法错/前提不满足 |
| 3 | 等你（`waiting_for_user`）—— 去网页「对话」页看它在问什么，答完用 `--resume` 接着跑 |
| 4 | 正常且中途停：用户叫停（强停与优雅停）/ 父叫停 / 预算耗尽 —— 加预算或答完即可 `--resume` |
| 5 | 正常自停但没有 `final`（原地打转 / escalated 交给召唤者） |

`start` / `run` / `project` 另有一条共有的约定：0 做成了 / 1 查过了有问题 / 2 没查成（用法错或前提不满足）。

---

## 11. 出问题先看这三处

```powershell
# ① 这一趟到底发生了什么（每一步一行事件）
Get-Content projects\<ws>\sessions\<sid>.jsonl -Tail 30

# ② 台账真的落了东西吗（不是"它说落了"）
python -c "import json,pathlib;d=pathlib.Path(r'projects\<ws>\data');print({t:len(json.loads((d/f'{t}.json').read_text(encoding='utf-8'))['rows']) for t in ('statements','tasks','documents','experiments')})"

# ③ 收工门（8 格）+ 内容级验收读数
python -m agentflow --root projects\<ws> closing
```

`closing` 逐格印 `paper / contradictions / load_bearing / report_shape / user_pending / substance / acceptance / artifact_ledger`，
再印非平凡性那一行（`T0..T4` + 未判；T0 = 基础定理或初步结论，平凡不再拒收），以及论文侧缺铺垫与 T4 缺造梯子记录（`[warning]` 行）。
另有一条零模型调用的进度读数：`python -m agentflow --root <ws> status-report`
（落 `out/review/STATUS-<时间>.md|json`，其中"在飞"只数实例行，见 §5）。

---

## 12. 这次测试要盯的两件事

1. **格式是否规范**：产出的 `theorem/lemma/proof` 环境齐不齐、`\cite` 带不带页码、
   正文有没有内部编号（`exp:`/`stmt:` 之类只许出现在附录 index）。
2. **宏大的定理有没有被派"搭梯子 / 拆分"**：
   - 「在飞」页的名册树看派活结构（谁派的、派给谁、绝对编号）；
   - `closing` 的非平凡性那一行看档位分布（T3/T4 就是"宏大"的那几条；T0 是平凡但真的那些，它们照旧收录）；
   - 出现 `[warning] nontriviality：T4 缺造梯子记录` ⇒ 研究侧没接这个信号；
   - 论文里 `definition` 环境数应当随 T4 的处理**上升**（"造梯子"的可见形态）。

---

## 13. 一句话

**一个入口 `start` 讲清四件事；网页用来看、命令行用来跑；钱按累计算、显式给了就落盘；退出码 1 不是正常结束。**

