# CLI 契约：`inspect` 那一组的 `--json`

> 面向上游脚本（以及将来的网页）的机器可读契约。人读的用法见 `docs/USER-GUIDE.md`
> 的 CLI 一节；命令分层与新旧对照表见 `agentflow --help-legacy`。

## 0. 为什么有这一层

这套框架的三态纪律是"查过了没问题 / 查过了有问题 / 没查成"三件事不许用同一个值表示。
命令行的人读输出一直守着它（退出码 0 / 1 / 2），但机器可读那一份此前是各命令自己长出来的：
`tools --json` 是一份、`budget --json` 是另一份、`stats errors --json` 又是第三份 ——
脚本要读三种壳子，而在"没查成"这件事上三者各说各的。

所以从 2026-10-24 起，`inspect` 那一组的 `--json` 一律是同一个外层四格：

| 键 | 类型 | 含义 |
|---|---|---|
| `ok` | bool | 这一趟做的事成立没有（等价于退出码 0，没有第二套判断） |
| `state` | str | 三态词：`checked`（查过了）/ `failed`（查过了、有问题）/ `unknown`（没查成） |
| `data` | object | 这一条命令自己的那一份读数（键集见下面逐条的表） |
| `problems` | list[str] | 要人看见的条目：stderr 的原话、读数自己的 problems（每条一行文本） |

`state` 与退出码一一对应（`_envelope_state`）：`0 → checked`、`1 → failed`、
`2 → unknown`。两处不许分家 —— 外壳是给人读的，退出码才是 CI 的判据。

## 1. 两条路，两个口径（这一节请先读完）

| 路径 | `--json` 的形状 | 为什么 |
|---|---|---|
| `agentflow inspect <成员> … --json` | 外层四格（本文档描述的契约） | 新入口，它就是为了统一口径而存在的 |
| `agentflow status-report|evidence|artifacts|analyze --json` | 外层四格（同上） | 这四条命令的 `--json` 是本轮新加的，没有旧形状可破坏 |
| `agentflow stats|tools|cache|budget|doctor|verify --json` | 各命令原来那一份（不变） | 那些输出早有消费者（其中 `tools --json` 被一份冻结快照逐字钉着），改字节就不是"旧指令行为不变"了 |

需要旧路径也拿外壳的地方：在命令前面加组名即可（`agentflow inspect tools --json`）。
两条路走的是同一份实现，只有"要不要套壳"这一件事不同（`cli._wants_json_envelope`）。

## 2. `data` 里那几格从哪来

`data` 的内容分三类，逐条列在下面每一节：

- 结构化读数（`tools` / `budget` / `verify` / `doctor` / `cache` / `stats`）：`data` 就是
  那条命令原来那份 JSON 对象（一行不改地搬进来）；
- 读数层（`stats`）：`data` 是 `readouts` 里那一张表（四个读数的键集写在
  `readouts.READOUT_DATA_KEYS`，判据从那里取期望值）；
- 还没结构化输出的四条（`status-report` / `evidence` / `artifacts` / `analyze`）：
  `data = {"text": "<这条命令打印的原文>"}`。这一格不假装有结构，但也不把原文丢掉；
  要结构化的那一份，看原文里点名的落盘文件（例如 `status-report` 的
  `out/review/STATUS-<ts>.json`）。

## 3. 逐条契约（`inspect` 组十条）

每条都写五件事：用途 / 参数 / `data` 字段 / 三态语义 / 实现方式一句话。

### 3.1 `inspect status-report`

- 用途：项目状态报告（只读台账与手稿，零模型调用），落 `out/review/STATUS-<ts>.{md,json}`。
- 参数：`--since <ISO 前缀>`、`--out <目录>`、`--json`。
- `data`：`{"text": <它打印的那段读数>}`（结构化那一份在它落盘的 `.json` 里）。
- 三态：`0` 报告已落盘；`2` 没查成（工作区不在盘上 / 打开失败）。
- 实现：`statusreport.write_status_report` 收集，`cmd_status_report` 只负责打印。

### 3.2 `inspect stats`

- 用途：四个只读读数（`errors` 错误动作 / `flow` 动作分布 / `cost` 钱与 token /
  `gates` 收工门八格）与一条合计 `all`。
- 参数：`stats <errors|flow|cost|gates|all> [--root <工作区>] [--json]`；
  `gates`/`all` 另有 `--project-dir`、`--report`（不给 ⇒ 那几格如实记 unknown）；
  `errors` 另有 `--readout`（给新的五键形状；不给则保持老形态）。
- `data`：`errors` → `by_role` / `role_total` / `total` / `categories` / `sources`；
  `flow` → `roles` / `totals`；`cost` → `by_role` / `by_scope` / `total`；
  `gates` → `cells` / `counts` / `machine_pass` / `can_close` / `verdict`；
  `all` → `errors` / `flow` / `cost` / `gates` 四栏。
- 三态：`0` 查过了（含全 0）；`2` 没查成（`state="unknown"`，`problems` 里逐条原因）。
  没有 `1`：这一层不是判据，它不判"错误太多"。
- 实现：`readouts.READOUTS` 里那张表（CLI 只选呈现与翻退出码）。

### 3.3 `inspect evidence`

- 用途：证据面三件事 —— `verify` 核一个运行的全文引用 / `store` 盘一个项目的正文库 /
  `migrate` 把历史内联正文迁成引用形态（缺省 dry-run）。
- 参数：`evidence <verify|store|migrate> <目标> [--apply] [--json]`。
- `data`：`{"text": <读数原文>}`。
- 三态：`0` 查过、都对得上；`1` 查过了、有坏引用（`verify` 那一档）；
  `2` 没查成（目标不是目录 / 读不了）。
- 实现：`_evidence_verify` / `_evidence_store` 现读现算；`migrate` 的真实现在
  `tools/legacy_cli/evidence_migrate.py`（移植期工具，下一版删除）。

### 3.4 `inspect artifacts`

- 用途：产物归属台账 —— `record` 登记 / `list` 列出 / `verify` 核哈希 /
  `owners` 问归属 / `unowned` 找没归属的 / `report` 渲染成表。
- 参数：`artifacts <action> [目标…] [--producer/--kind/--task-id/--exit-code/--note/--out] [--json]`。
- `data`：`{"text": <台账渲染出来的原文>}`。
- 三态：`0` 做成了；`2` 没查成（台账读不了）。`record` 用 `--exit-code` 区分"跑过"与"没跑过"。
- 实现：`cmd_artifacts` 按 action 分派到 `artifacts` 模块。

### 3.5 `inspect analyze`

- 用途：C 的关系分析（`hottest` / `cold` / `gaps` / `paths` 四类需求），零模型调用。
- 参数：`--kind <类>`、`--a/--b`（paths）、`--top-n`、`--max-paths`、`--max-len`、
  `--request`、`--text`、`--json`。`--root` 要写在组名之前（顶层开关）。
- `data`：`{"text": <分析报告原文>}`。
- 三态：`0` 产出报告；`1` 查过了、报告里有阻断（例如关系表为空 ⇒ 统计不出热度）；
  `2` 没查成。
- 实现：`cmd_analyze` → `agent_c` 的四个分析入口。

### 3.6 `inspect tools`

- 用途：列出工具层按角色的装配情况（"角色即权限面"的可打印事实）。
- 参数：`--role <A–H/M>`、`--json`。
- `data`：`tools` / `count` / `loaded_modules` / `skipped_modules` / `lean_off_modules` /
  `params_checked` / `context_budget`。
- 三态：`0` 读到了；`2` 没查成（工具层装配失败）。
- 实现：`tools.for_role` 现算（与运行期同一份装配表）。

### 3.7 `inspect cache`

- 用途：两档提示词缓存 —— `status` 只读（落盘/新鲜/覆盖/缺哪几段 + key 变化提醒）、
  `warm --lean on|off|both [--dry-run]`（真预热会花钱）。
- 参数：`cache <status|warm> [--lean …] [--dry-run] [--json]`。
- `data`：`schema` / `at` / `readings` / `lean_now` / `prompt_version` / `key` /
  `workspace` / `tiers` / `active` / `reminder` / `verdict`。
- 三态：`0` 新鲜且覆盖齐；`1` 查过了、缓存不新鲜或缺段（`verdict` 里点名）；
  `2` 没查成。
- 实现：`cachectl`（命令行与网页按钮读同一份实现）。

### 3.8 `inspect budget`

- 用途：这一趟的总预算 —— 看 / 设 / 追加（运行期生效）。
- 参数：`--status`、`--set <usd>`、`--add <usd>`、`--by`、`--note`、
  `--fallback-usd`、`--json`。
- `data`：`tri` / `reason` / `path` / `exists` / `source` / `total_usd` / `spent_usd` /
  `remaining_usd` / `exceeded` / `added` / `problem`。
- 三态：`0` 读到了（没设预算也是 0，`tri` 说明"不限量"）；`2` 没查成。
- 实现：`budget` 模块的寄存器读写。

### 3.9 `inspect doctor`

- 用途：体检 —— 这台机器能做哪些事（不花钱、不调模型）。
- 参数：`--json`、`--selfcheck`（只做包内源码自检）。
- `data`：`model` / `provers` / `lean_enabled` / `lean_enabled_source` / `formal_mode` /
  `lean_ready` / `can_do_formal` / `lean_path` / `lean_version` / `mathlib` /
  `lean_selfcheck` / `checks`。
  `checks` 是逐项读数：`[{"name", "state", "detail", "fix_hint"}]`，`state` 取
  `ok` / `fail` / `unknown` / `off`；没通过的那几项带 `fix_hint`（可直接复制执行的命令原文）。
- 三态：`0` 都齐；`1` 查过了、有缺（每项都能在 `checks` 里看到怎么办）；
  `2` 没查成（探测本身不成立）。
- 实现：`toolchain.toolchain_report` + `leantoolchain.lean_selfcheck_reading`，
  判定在 `cli.doctor_checks` 一次做完（人读与 `--json` 同源）。

### 3.10 `inspect verify`

- 用途：校验全局不变量（关系/引文/台账一致性），`--deep` 会重开文献复核。
- 参数：`--deep`、`--strict`、`--json`。
- `data`：`ok` / `deep` / `checked` / `errors` / `warnings` / `error_count` / `warning_count`。
- 三态：`0` 没有 error；`1` 有 error（`--strict` 时 warning 也算）；`2` 没查成。
- 实现：`verify.verify_all`（判定逻辑不在 CLI 里）。

## 4. 三条使用规矩

1. 先看 `state`，再看 `data`：`unknown` 时 `data` 里的 0 不是"没有"，是"没读到"。
2. `problems` 是逐行文本（外壳里不做结构化）：要机读的细节看 `data`。
3. 别按 `--help` 猜字段：本文档每一节就是那张表；改了 `data` 的键集要同时改
   `tests/test_cli_json_contract.py` 里的常量（那份判据逐字断言键集）。

## 5. 这一份由谁守着

| 文档里的说法 | 判据 |
|---|---|
| 外层四格、三态与退出码对应 | `tests/test_cli_json_contract.py` |
| 每条的 `data` 字段 | 同上（逐条断言） |
| `stats` 四张读数的键集 | `tests/test_cli_stats_four_tables.py` |
| 读数层的五键与三态 | `tests/test_readouts_are_the_single_shape.py` |
| `doctor` 的 `fix_hint` | `tests/test_doctor_fix_hint.py` |
| 旧名与新路径等价 | `tests/test_cli_grouped_entry_points.py` |
