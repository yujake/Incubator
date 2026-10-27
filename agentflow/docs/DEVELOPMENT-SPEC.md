# DEVELOPMENT-SPEC —— agentflow 开发规范（判据面）

> ⚠️ **权威性**：本文是「开发规范」，属**当前规格**，是"怎么做才算对"的**判据**。
> 与代码冲突时**以代码为准**；若代码与本文冲突，是**本文的 bug**（处置见 §12）。
> 「哪份文档算数」的权威地图见 [`INDEX.md`](INDEX.md)。
>
> **本文与另外两份的关系**：
> - [`../DEVELOPMENT.md`](../DEVELOPMENT.md) —— **入口**（一页，指路：改代码前先读哪三节）；
> - **本文** —— **规范**（判据都在这；每节首行标 `[规范]`）；
> - [`DEVELOPMENT-APPENDIX.md`](DEVELOPMENT-APPENDIX.md) —— **历史**（取样记录、FC 覆盖矩阵、
>   已知不一致清单；每节首行标 `[附录·历史]`，**不构成判据**）。
>
> **配套文档**：
> - [`ROLE-SPECS.md`](ROLE-SPECS.md) —— 各角色（A–H + V）与主控（M）的详细规格；
>   节数与必备子节由 `python tools/verify_role_specs.py` 当次产出（本文不抄定值）
> - [`PROPOSALS.md`](PROPOSALS.md) —— **已裁决的缺口与提案**（`P-` 要人做 / `G-` 已接受但**必须继续可见** / `N-` 不是缺陷）
> - [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) —— FC-27 门的机制与人工批准流程
> - [`../NOAI-REVIEW-REGISTER.md`](../NOAI-REVIEW-REGISTER.md) —— FC-27 **人读侧**登记表
> - [`../AGENTS.md`](../AGENTS.md) —— **只**覆盖禁 AI 区 FC-27 这一节，不重复本文内容
> - [`INDEX.md`](INDEX.md) —— 上述文档的索引与"按角色怎么读"
> - `../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md` ——
>   **现状导读**：逐项带**相对工作区根**的路径。它**不构成判据**；与它冲突时以本文与代码为准
> - `LESSONS.md` —— 本文多处按这个短名引用它，但 `agentflow/` 下没有这个文件；
>   实体在工作区根的 `draft/LESSONS-工程经验清单（FC-01…FC-27）.md`
>
> **本文的写作纪律**（读它的人可以用这三条反过来质问我）：
> 1. **每一条规则都必须可判定** —— "要写清楚"不是规则，"每个公开函数必须有 docstring
>    且 docstring 必须含'为什么'段落"才是。
> 2. **每一个数字都有出处** —— 指向 `文件:行号`、指向实跑的**命令 + 输出**、或指向某个权威条目。
>    **不许估。** 本文正文因此**只写命令与键名**，定值一律住 §0.2 的 `LIVE-READINGS` 块。
> 3. **不许把"未落地/未核实"写成"已落地"**。凡只是从文档读到、没在代码里核实的，
>    标 `（据 X，未在代码中核实）`。
>
> **本批（2026-10-27）新设计住哪**：**§16**。它把本批 745 条新增符号归成 **13 个机制簇**，
> 每簇三格（**规则** / **落点** / **判据**），索引表在 **§16.0**。判据本体是
> `tests/test_new_designs_are_in_the_spec.py`：逐簇核"落点里的符号真的在盘上"与"现算格里的数字真的相等"，
> 并各带一条反真空（改错一个字母 / 改大一个数，判据必红）。

---

## [规范] §0 怎么读这份规范

### [规范] §0.1 三条口径，先立后文

1. **读数只住一处**：任何"当次数"（工具数 / 表数 / lint 三栏 / 禁改区数 / 端点数是几）
   只写在 §0.2 的 `LIVE-READINGS` 块里，正文只写**命令 + 键名**。
   理由见 §1.1：同一个数字抄在几处，读者分不出哪一处是当次值、哪一处是历史快照。
2. **历史不许当当前值**：带 `S1` / `S2` / `当时` / `观测 YYYY-MM-DD` / `原写` 这些字样的句子
   是**历史读数**，一律住在 `DEVELOPMENT-APPENDIX.md`，且**不构成判据**。
3. **"没查成"必须写"没查成"**（三态纪律，见 §5 纪律 1）：`unknown` / 未复跑 ✅ 允许；
   把"没查"写成某个数 ❌ 一律是缺陷（§8-P16）。

### [规范] §0.2 当次读数（`LIVE-READINGS` 块）

**这一块就是判据的对象**：`tests/test_release_all.py` 的 `measured_readings()` 逐键量一遍，
`live_reading_problems()` 逐键比对"这里写的"与"当次实测的"，对不上就红并在报错里点名。
改这里的数，只要跑一遍块里点名的复跑命令。
判据本体是两条：正控 `tests/test_release_all.py::test_development_md_linter_readings_and_rule_range_match_the_repo`
与它的负控 `test_the_documented_readings_criterion_is_not_vacuous`（把一块读数打回过期值，
判据必须红 —— 这是"判据本身不是橡皮图章"的证明）。

**linter 的当次三栏（日常档）**：`error 0 / warning 21 / info 49`（观测 2026-10-27，
复跑 `python -B scripts/lint_rules.py`；`warning` / `info` 是当次读数，判据逐行拿它们对账。
`error` 那一格写的是发布门第 5 项的**要求值**、不是读数 —— 它按"必须为 0"强制，而并行施工期间
同一棵树上的实测在 0–4 之间跳（那一刻是 4，全部落在 `readouts.py` / `cli.py` 与它们的判据文件的
docstring 星号强调上，不在本批改动里）。**严格档的两个数只写进块里的 `lint_rules_strict_*` 两行**，
正文不另抄一份三元组，因为判据是逐行拿日常档的 warning/info 对账的）。

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH='src'   # 只有跑 `python -m agentflow.*` / `python -c "...import agentflow..."` 才需要
```

```text
LIVE-READINGS:BEGIN
# 本块按判据口径量（`tests/conftest.py` 钉 `AGENTFLOW_LEAN_ENABLED=1`）；CLI 缺省 shell（Lean 关）少三件 `formal.*`（`lean_scope` 决定装不装那个模块）
# 名字 = 数字        # 含义 + 复跑命令 + 观测时刻
# 量法说明：前 11 个键与 `tests/test_release_all.py::measured_readings()` 逐键同名同量法。
# 判据不认的键（拼错）与判据要的键缺失，都会被同一处报出来 —— 所以加键要同时改判据。
lint_rules_rules        = 12   # `len(RULES)`；复跑 `python -B scripts/lint_rules.py` 摘要行的"规则 N 条"。其中 R004/R006 已退休、编号保留，`RETIRED_RULES` 里逐条给了去向
lint_rules_warning      = 21   # `python -B scripts/lint_rules.py`（日常档）末行 warning 栏
lint_rules_info         = 49   # 同一档的 info 栏
lint_rules_strict_warning = 84 # `python -B scripts/lint_rules.py --strict` 的 warning 栏（日常档那条 R007 info 在这一档拆成逐模块 warning）
lint_rules_strict_info  = 48   # 同一档的 info 栏
noai_paths_glob         = 46   # `(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count`
noai_paths_unique       = 43   # 上述条目行按第一栏去重：`(... | ForEach-Object { ($_.Line -split '\s+')[0] } | Select-Object -Unique).Count`
noai_paths_categories   = 7    # `.noai-paths` 里 `[category: …]` 的分组数
tools_star_tools_py     = 19   # `(Get-ChildItem src/agentflow/tools -Filter '*_tools.py').Count`
schema_tables           = 17   # `python -c "import sys;sys.path.insert(0,'src');import agentflow.schema as s;print(len(s.TABLES))"`
noai_gate_pytest_collected = 124 # `python -m pytest tests/test_noai_gate.py --collect-only -q -p no:cacheprovider` 的 `N tests collected`
cli_tools_total        = 114  # `python -m agentflow.cli tools` 首行"工具总数：N"（含 store 的完整装配口径；Lean 关档少三件 `formal.*`，本块钉的是 Lean 开档）
cli_tools_modules      = 17  # 同一行"已装模块 N"
cli_tools_role_a       = 52  # `python -m agentflow.cli tools` 的"各角色工具数"逐角色格（键名 = 角色小写）
cli_tools_role_b       = 38
cli_tools_role_c       = 36
cli_tools_role_d       = 57
cli_tools_role_e       = 39
cli_tools_role_f       = 51
cli_tools_role_g       = 53
cli_tools_role_h       = 44
cli_tools_role_v       = 28
cli_tools_role_l       = 38
cli_tools_role_m       = 37
webui_modules           = 10   # `(Get-ChildItem src/agentflow/webui -Filter '*.py').Count`
webui_routes            = 31   # `python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import routes as r;print(len(r.ROUTES))"`
webui_routes_get        = 23   # 同上，按 `x[0] == 'GET'` 计数
webui_routes_post       = 8    # 同上，按 `x[0] == 'POST'` 计数
webui_event_kinds       = 6    # `python -c "...from agentflow.webui import sse;print(len(sse.EVENT_KINDS))"`
webui_test_files        = 16   # `(Get-ChildItem tests -Filter 'test_webui*.py').Count`
LIVE-READINGS:END
```

**`cli tools` 的三个数是三个口径，不许互换**（详见 §3.5 与 §4.2）：
`cli tools`（含 store）给出上表那 11 个逐角色数；`build_registry(store=None, workspace_root='.')`
与 `build_registry(store=None)` 各自再给一组**不同的**数。**把一个口径的数搬到另一个口径下，
比写错一个数字更贵** —— 它看起来是精确的。

**`cli tools` 还会打印一行"只读角色写工具泄漏"**：今天的值**不是空表** —— `H` 有一组
**已逐条登记的落库代理**（`review.report` / `review.review_document` / `review.verify_fixes` /
`review.record_finding`），`C` 也有一件（`analysis.register_report`），全部由
`tools/base.py` 的 `READONLY_CALL_EXCEPTIONS` 产生，命令自己会打印这些名字与放行理由
（2026-10-21 实测，复跑 `python -m agentflow.cli tools`，读「只读角色写工具泄漏」那一行 ⇒
`{'C': ['analysis.register_report'], 'H': ['review.review_document', 'review.verify_fixes',
'review.report', 'review.record_finding'], 'V': []}`；取法就是读 `tools/base.py` 的
`READONLY_CALL_EXCEPTIONS` 两个键）。
旧的"`{'C':[],'H':[],'V':[]}`（空 = 正常）"**已不成立**；判据要看的是"命令的输出里有没有
未登记的泄漏"，不是"这一行是不是空表"。

### [规范] §0.3 一份读数的三档身份

| 档 | 长什么样 | 住哪 | 谁能改 |
|---|---|---|---|
| **当次值** | `LIVE-READINGS` 块里的 `名字 = 数字` | 本文 §0.2 | 跑一遍块里的命令，随手改 |
| **历史读数** | 带 `S1` / `S2` / `当时` / `观测 2026-…` / `原写` | `DEVELOPMENT-APPENDIX.md` | 只许加，不许改（改它等于伪造历史） |
| **区间读数** | `N1–N2（<UTC+8 观测时刻> 观测）` | 本文正文（只在无法钉住的量上） | 每次观测重写一行 |

---

## [规范] §1 计数类数字的写法（`G-32` / `D-1.6`）

### [规范] §1.1 规矩：**区间 + 观测时刻**，或者**命令 + 键名**

⭐ **本条是"怎么写数字"的规矩本身，不针对某一处。** 它由 `draft/25` 的 **`D-1.6`** 要求：
*"证据落 `temp/`：命令 + 原始输出 + **观测时刻**；所有计数写成**区间 + 观测时刻**"*。

**规矩（三条，缺一条这个数字就不可用）**：

1. **行数 / 条数 / 命中数 / 通过数**一律写成 `N1–N2（<UTC+8 观测时刻> 观测）`，
   **不许写成单个定值**。区间来自**同一观测窗口内重复两次**（本仓库是并发施工的仓库，
   同一棵树在几分钟内就能从一组读数变成另一组 —— 而那不是"回归"，是别的执行体在同一目录里写文件）。
   **能钉住的量就不走这一档，改走 §0.2 的 `LIVE-READINGS` 块**（有判据守着，比区间强）。
2. **必须写清是哪条装配/哪条命令口径**。同一个量在不同命令下**可以**是两个数，
   且**两个数都不许被丢掉**（三个口径的例子见 §0.2 与 §3.5）。
3. **"没查成"必须写"没查成"**（三态纪律）：`unknown` / 未复跑 ✅ 允许；
   把"没查"写成某个数 ❌ 一律是缺陷（`P16`）。

**反例（这份文档里真实发生过的）**：`tests/` 的份数那一行**原写**过一个没有观测时刻的定值
（读者无法判断该不该信）。现在的写法是**相对形态**：写 `N1–N2`（观测 `<开始时刻>→<结束时刻>`）
的区间，并把"并发写会让同一棵树在几分钟内给出另一组读数"写成一句**不带任何定值的**说明 ——
**每一次读数都带自己的观测时刻，读者自己能判它是不是当次值**。
⇒ 示范段本身**不再复写任何定值**：要看当次数就照 §0.2 块里那条命令复跑。

**为什么这条值得单列**：本项目已经有 `G-30`/`G-31`/`G-32` 三条登记都指向同一个病根 ——
**数字看起来是客观的，于是没有人去问它的口径**。而"口径就是那个数字"这句话，
`AGENTS.md` 已经把它列成**禁改区的一类理由**（评测口径的定义）。

### [规范] §1.2 手抄数字清单：每个数字**住在哪、谁在守、怎么复跑**（`draft/36` 的 T-4）

**为什么要有这一节**：`draft/36` 的体检读数里，⑥ 是"文档-代码漂移面"。加判据时实测到
动作表已经漂了（三处数字与名字都过期），而**没有任何东西会红**。根因不是"打错一个数"，而是：
**同一个数字抄在好几处、读者分不出哪一处是当次值、哪一处是历史快照。**
本节把这类数字逐个登记，并写清它属于哪一档：

- **有判据**：改了代码不改文档 ⇒ 有测试会红（列到具体测试名）；
- **人工维护**：没有判据盯着，改动时请同步（并给出复跑命令）。

| 数字 | 住在哪 | 数的是什么 | 谁在守 | 复跑 |
|---|---|---|---|---|
| 工具总数 | `LIVE-READINGS` 块的 `cli_tools_total`；`ROLE-SPECS.md` §R0 标题 / §R0.1 / §R0.2 | `build_registry()` 装配出的 `ToolSpec` 条数 | **有判据**：`tests/test_role_specs_complete.py`（§R0 标题 vs 实时装配）、`tools/verify_role_specs.py` | `python -m agentflow.cli tools` |
| 逐角色工具数 | 同块的 `cli_tools_role_*`；`ROLE-SPECS.md` §R0 与各角色节标题 | 每个角色的工具面条数（含公共工具） | **有判据**：`tools/verify_role_specs.py`（逐角色条数 vs 现场装配） | 同上 |
| 动作总数 / 可召唤动作数 | `ROLE-SPECS.md` §0.7 与 §M.4.1 的**标题** | `capabilities.CAPABILITIES` 的动作条数 / 按 `ALLOWED_EDGES["M"]` 覆盖的动作之和 | **有判据**：`tests/test_role_specs_action_table.py`、`tests/test_doc_code_consistency.py` | `python -c "import sys;sys.path.insert(0,'src');from agentflow import capabilities as c;print(c.two_layer_reconciliation()['total'])"` |
| 逐角色**动作名** | `ROLE-SPECS.md` §0.7 与 §M.4.1 **两处**（同一份数据两个落点） | 每角色有哪些动作 | **有判据**：同上（两处都扫，含两条负控） | `python -m agentflow.cli tools --role <X>` |
| 子命令数 | `README.md` §0 与 §4 文件树 | `cli.build_parser()` 的子命令数 | **有判据**：`tests/test_user_quickstart.py`、`tests/test_doc_code_consistency.py` | `python -m agentflow.cli --help` |
| lint 五个读数 | `LIVE-READINGS` 块的 `lint_rules_*` | `scripts/lint_rules.py` 的摘要行 | **有判据**：`tests/test_release_all.py`（`measured_readings()` / `live_reading_problems()` 逐键比对） | `python -B scripts/lint_rules.py`（`--strict` 另跑） |
| 禁改区三读数 | 同块的 `noai_paths_*` | `.noai-paths` 的条目行 | **有判据**：`tests/test_noai_gate.py` + 上面的 `live_reading_problems` | `python -B scripts/noai_gate.py --check-consistency` |
| `schema.TABLES` / `tools_star_tools_py` / `noai_gate_pytest_collected` | 同块 | 表数 / 工具模块数 / 收集到的用例数 | **有判据**：同 `LIVE-READINGS` 那一条 | 见块里逐行的复跑命令 |
| 角色节结构 | `LIVE-READINGS` 之外（由工具产出） | `ROLE-SPECS.md` 的节结构 | **有判据**：`tools/verify_role_specs.py`、`tests/test_role_specs_complete.py` | `python -B tools/verify_role_specs.py` |
| 已装模块数 | 同块的 `cli_tools_modules` | `tools.build_registry` 装了几个工具模块 | **人工维护**（没有逐模块数的判据；模块名清单见 §4.1） | `python -m agentflow.cli tools` 的摘要行 |
| Web 面三个数（模块 / 端点 / 判据文件） | 同块的 `webui_*` | `webui/` 的模块数、`ROUTES` 的条数、`test_webui*` 的文件数 | **有判据**：`tests/test_webui_contracts.py`（端点集合 vs `ROUTES`） | 见 §2 第 ⑧ 层与块里逐行的复跑命令 |
| `ROLE-SPECS.md` §0.2 的历史快照 | §0.2 的表 | 某一次装配的读数 | **历史快照**（已在原地标注并指向 §R0.1） | 见该节的观测时刻 |

**三格"判据要的逐字字面量"**（`tests/test_doc_code_consistency.py` 逐格对拍；
它们**必须逐字**长成这样，否则判据报"再也找不到这一格"。旁边的命令就是它们的量法）：

| 字面量 | 量法（复跑命令） |
|---|---|
| 动作总数 **64** | `python -c "import sys;sys.path.insert(0,'src');from agentflow import capabilities as c;print(c.two_layer_reconciliation()['total'])"`（2026-10-23 加 L 的三件形式化动作 ⇒ 62 → 65） |
| 可召唤动作数 **54** | 同上，再算 `sum(len(c.actions_for(r)) for r in c.ALLOWED_EDGES['M'])`（2026-10-22 加 `G.write_mapping` ⇒ 54 → 55；此前 2026-10-20 撤 `M→V` ⇒ 57 → 54） |
| 子命令数 **28** | `python -m agentflow.cli --help`（数子命令那一栏；判据直接读 `build_parser()` 的 choices。2026-10-24 加 `stats` 那一组：统计量，今天只有 `errors` 一档 ⇒ 27 → 28） |

**两条使用规矩**（与 §1.1 同源）：
1. **引用任何计数前先在这张表里找它**：找到"有判据"⇒ 可以信当次值；
   找到"人工维护"⇒ 它是人写的，改动时请同步；找不到 ⇒ 说明它是一张**没登记的手抄数字**，
   请登记进来（这一节本身就是**漂移面的清单**）。
2. **同一份数据抄在两处就是风险**（§0.7 与 §M.4.1 就是例子）。能合成一处就合成；
   暂时不能合的（结构上各有各的读者），就**让同一条判据同时盯着两处**。

### [规范] §1.3 注释分三层：`[契约]` / `[为什么]` / `[踩过]`（`draft/36` 的 T-2）

> 本节就是拆分前 `DEVELOPMENT.md` 的 **§0.3d（注释三层）** 全文迁入版。旧编号逐字保留在
> 这里，是因为判据（`tests/test_comment_layers.py`）按那个编号定位这一节 ——
> 编号在入口里消失、约定却还在，会让"约定还在"与"判据找不到约定"同时成立。
> 拆分只改"它住哪个文件"，三层标签、写法与三条纪律一个字都没改。

**为什么要有这条规矩**：本仓库的注释密度很高（每百行代码的注释/文档串行数按命令当次量，
**本文不抄定值**；原文那个 `78.7` 是 2026-09 的一次读数，**本轮未复跑**）——
那是**资产**，不是负债：`LESSONS.md` 就是靠这些"为什么"长出来的。
外人觉得乱的**真正原因不是多，而是没分层**：读者分不出"我必须守住的不变量"
与"某次事故的故事"，于是要么全信、要么全跳过。

**三个标签（只许这三个，写错就红）**：

| 标签 | 写什么 | 硬要求 |
|---|---|---|
| `[契约]` | 调用方**可以依赖**的事实：不变量、边界、承诺。改了它 = 破坏契约 | 必须是一句可判真假的话（"X 一定在 Y 之前发生"），不是感想 |
| `[为什么]` | 为什么这样选（含**被否掉的选项**与它为什么更坏） | 要能让读者判断"我这次该不该照旧" |
| `[踩过]` | 实测读数与事故：当时看到了什么、代价是什么 | **必须能追到出处**：`YYYY-MM-DD` 或 `draft/28` §NNN（任一即可，判据认） |

**写法（两种位置，同一条规矩）**：

```python
"""模块或函数 docstring —— 章节标题带标签：

## [契约] can_round 的两个维度不能混为一谈
## [为什么] 为什么"攻坚"需要独立的预算模型
## [踩过] 六个 handler 都过 _guard（2026-09-30，draft/28 §150）
"""

# 行内注释块 —— 块首那一行带标签，后面照旧写细节：
# [踩过] 改前这一句只写源名 + 自由文本，"没有这一篇"与"上游坏了"读起来一样
# （2026-09-29，draft/28 §150）。
```

**三条纪律**：

1. **标签只加在注释或 docstring 里**，绝不出现在代码行上（判据用 `tokenize` 证明这一点）；
2. **不加标签也合法** —— 文件结构导航、纯事实描述不必硬塞进三层；
   判据只要求**样板文件**里三层都出现过，不要求每段注释都有标签；
3. **`[契约]` 与 `[为什么]` 不许互相冒充**：把"我为什么这么写"写成 `[契约]`，
   会让下一个人以为那是不能动的承诺；把不变量写成 `[为什么]`，会让它看起来可以商量。

**样板文件**（判据点名的四个，见 `tests/test_comment_layers.py`）：
`agent_d/`（包；原 `agent_d.py` 的大文件在 `goal-7f5116c1` M6 拆成了一个动作一个文件，
三层标签现在分布在 `agent_d/_support.py` 与 `agent_d/adjudicate.py` 等文件里 ——
判据按**整个包**取文本）、`tools/attack_tools.py`（工具层最密）、
`claimanatomy.py`、`evidence.py`。这四份按上面的写法各标了一轮，供新代码照抄。

---

---

## [规范] §2 系统分层：**八层**，每层只有一份判据

> ⭐ **本层的形状：由七层改为八层。** 七层的原始出处是
> `draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md` §2
> 「分层：七层，每层只有一份判据」；**那一份里没有 ⑧ 这一层**（业主 2026-10 裁定补上）。
> 所以本文的分层表比 `draft/35` **多一层** —— 这是**刻意的增量**，不是抄写错误。
> 两处冲突时以本文为准；`draft/35` 里那句"七层"是**历史**（`DEVELOPMENT-APPENDIX.md` 的 A1 同理）。

**系统的形状可以概括成"声明在上、实现在下、判据各一份"**。下面每一层给四件事：
**职责 / 入口文件 / 契约与判据 / 已知边界**。路径一律**相对工作区根**（`agentflow/` 之下）。

| 层 | 这一层的名字 | 相对工作区根的入口 |
|---|---|---|
| ① | 数据面 | `agentflow/src/agentflow/schema.py`、`store.py`、`canonical.py` |
| ② | 声明面 | `agentflow/src/agentflow/capabilities.py`、`interactions.py`、`policy.py` |
| ③ | 工具面 | `agentflow/src/agentflow/tools/` |
| ④ | 角色面 | `agentflow/src/agentflow/agent_a/` … `agent_h/`、`agent_v/`、`conductor.py` |
| ⑤ | 循环面 | `agentflow/src/agentflow/agent_loop.py`、`agent_prompts.py`、`llmseam.py`、`judge.py`、`judges.py` |
| ⑥ | 接线面 | `agentflow/src/agentflow/host.py`、`cli.py`、`projects.py` |
| ⑦ | 质量面 | `agentflow/scripts/`、`agentflow/tools/`、`agentflow/src/agentflow/gates.py`、`verify.py`、`deliver.py` |
| ⑧ | **Web / 用户端**（本轮新增） | `agentflow/src/agentflow/webui/`、`web/`、`agentflow/ui/` |

**"判据各一份"凭什么**：见 §5（六条硬纪律）。机械体现是 lint 规则 `R003`（重复公开定义）
与 `canonical.py`（规范 JSON 字节串的唯一实现 —— 稿件内容哈希与编译回执哈希共用它）。

### [规范] §2.1 逐层：职责 / 入口文件 / 契约与判据 / 已知边界

**① 数据面**
- **职责**：表结构、行级校验、事务与 ID 分配。**唯一的写入口**是 `store.py` 的事务对象。
- **入口文件**：`src/agentflow/schema.py`（`TABLES` / 各 `validate()` / 全部受控词表）、
  `store.py`（锁 / 原子写 / 事件日志 / `rebuild` / `alloc_id`）、`canonical.py`。
- **契约与判据**：`verify.py` 的全库不变量（§6.1 的第 4/7 项就是给这一层加的）；
  `tests/test_rebuild.py`（重建守恒：诊断字段相等 + 幂等）；`tests/test_fc05_contract.py`
  （数组字段的集合/序列二分）。表数由 `LIVE-READINGS` 的 `schema_tables` 钉住。
- **已知边界**：`schema.py` 与 `store.py` 在 FC-27 禁改区（`[category: schema-migration]`），
  **改它们要人写或人逐行走查 + 2 名 reviewer**（§9.4）。

**② 声明面**
- **职责**：谁说谁能做什么 —— 召唤边、跨角色契约、四类上限。
- **入口文件**：`capabilities.py`（`CAPABILITIES` / `WRITE_SETS` / `ALLOWED_EDGES` +
  **导入期** `assert_capabilities()`）、`interactions.py`（I1–I12 的判据，纯函数，
  签名里**没有** `store`）、`policy.py`（`Refusal` 或 `None`）。
- **契约与判据**：`assert_capabilities()` 导入期就炸（"不可能忘记跑"）；`interactions.assert_store_free`；
  动作总数与可召唤动作数见 §1.2 那两格（有判据逐字对拍）。
- **已知边界**：这一层的能力表由 `specs/` 包里的逐角色声明派生，改 `specs/*.py`
  等于改权限面本身，而判据守的是「两层一致」、不是「这一改该不该由人批」（`AGENTS.md` 的 `auth-audit`）。

**③ 工具面**
- **职责**：角色拿到手的原子动作，含**权限面过滤**（只读角色一律拿不到写工具）。
- **入口文件**：`src/agentflow/tools/__init__.py`（`build_registry` 是**唯一**装配点）、
  `tools/base.py`（`ToolSpec` 六件套校验 / `for_role` / `ToolRegistry.call`）。
- **契约与判据**：`ToolSpec.__post_init__` 逐件校验（`§6.3` 第 1 项）；
  `python -m agentflow.cli tools` 的普查（工具总数 / 已装模块 / 逐角色 / 只读泄漏，
  四个数在 `LIVE-READINGS` 里）；`tests/test_tools_base.py`、`tests/test_tools_readonly_roles.py`。
- **已知边界**：**只读角色的泄漏那一行今天不是空表** —— `H` 有 4 个**已逐条登记**的落库代理
  （`review.report` / `review.review_document` / `review.verify_fixes` / `review.record_finding`），
  `C` 有 1 个（`analysis.register_report`），全部由
  `tools/base.py` 的 `READONLY_CALL_EXCEPTIONS` 产生（2026-10-21 实测，复跑
  `python -m agentflow.cli tools` 的「只读角色写工具泄漏」那一行，见 §0.2）。
  "空 = 正常"这个读法**已过期**：要判的是"命令有没有打印**未登记**的泄漏"。

**④ 角色面**
- **职责**：每个角色的动作实现与自检；主控的"召唤 → 台账 → backend → 终态"。
- **入口文件**：`agent_a/` … `agent_h/`、`agent_v/`（**一个动作一个文件** + `core.py` +
  `_support.py` + `__main__.py`；V 只有 `core.py` + `__init__.py` + `__main__.py`，只读）、
  `conductor.py`（主控 M 不在角色包里，它是这个模块）。
- **契约与判据**：每个角色都有 `python -m agentflow.agent_<role>` 自检（退出码 0）；
  `tests/test_agent_<role>.py`；`capabilities.assert_capabilities()` 第 2 条核
  `ActionSpec.handler_name` 真实可调用。
- **已知边界**：**M 的 `CAPABILITIES["M"] == ()`** 是刻意设计（主控不产出知识，它只编排），
  所以"M 没有动作"**不是**缺口；M 有工具面（编排面 + 文件白名单），见 `cli tools --role M`。

**⑤ 循环面**
- **职责**：模型驱动的决策循环与提示词装配。
- **入口文件**：`agent_loop.py`（六种形状 + 观测层 + 长产出落盘）、`agent_prompts.py`
  （`PROMPT_VERSION` / `ROLE_BRIEFS` / `SECTION_ORDERS`）、`llmseam.py`（一次调用 = 一条审计记录）、
  `judge.py` / `judges.py`（`CRITERIA` 与模型判定的唯一缝）。
- **契约与判据**：`llmseam` 的每次调用都落 `usage_ledger`（唯一写入方是
  `tokenmeter.TokenMeter.charge`）；`tests/test_llmseam_charge_discipline.py`、
  `tests/test_agent_loop.py`。
- **已知边界**：**无真实 provider key ⇒ LLM 路径未端到端跑过**（`DEVELOPMENT-APPENDIX.md`
  的 A6 / FC-14）。这条不许写成"已落地端到端"。

**⑥ 接线面**
- **职责**：把角色 / 工具 / 主控接到一起，并如实报出接线态；给命令行入口。
- **入口文件**：`host.py`（角色登记表 / 接线态 / 接了线的工具层与主控）、`cli.py`、
  `projects.py`（一个项目一个文件夹）。
- **契约与判据**：**未接线 ⇒ 不进登记表**（不假装"没接线"是"跑过了"）；
  `tests/test_doc_code_consistency.py` 逐格对拍子命令数（§1.2 那格）。
- **已知边界**：`cli.py` 的 `--role choices` 曾经写死 A–D（`DEVELOPMENT-APPENDIX.md` 的 D2），
  已修；**判断这件事的方法是 `python -m agentflow.cli tools --role E` 的退出码**，不是读注释。

**⑦ 质量面**
- **职责**：门、审计、发布检查。
- **入口文件**：`src/agentflow/gates.py`（`GATES` 声明表 + 四态裁决）、`verify.py`、
  `deliver.py`、`scripts/`（linter / 禁 AI 区门 / 发布检查）、`tools/`（`release_all` 编排层等）。
- **契约与判据**：与语言无关的三档退出码 `0/1/2`（`unknown ≠ pass`，§10.1）；
  `python tools/release_all.py` 的一键判定；`python -B scripts/lint_rules.py` 的三栏读数
  （`LIVE-READINGS` 的 `lint_rules_*`）。
- **已知边界**：`tools/release_all.py` 与 `scripts/release_check.py` **自身在 FC-27 禁改区、
  且未经人逐行走查** ⇒ **它们全绿也不构成发布许可**（§9.3）。

**⑧ Web / 用户端**（**本轮新增的一层**；下表的每个数都是当次实测 + 就地给出复跑命令）
- **职责**：把"待回答面板 / 运行态 / 事件回放"变成一个本机网页；**只读为主，写面走 CSRF + 白名单**。
  它不产生知识、不改台账语义 —— 它是**呈现与提问面**，不是第八个角色。
- **入口文件**：
  - 命令行入口是 `web` 子命令：`python -m agentflow.cli --help` 里逐字
    「`web   起用户端网页（本地小服务：待回答面板 / 运行态 / 事件回放）`」；
  - 服务端 `src/agentflow/webui/` —— **9 个模块**（`__init__.py` / `__main__.py` /
    `routes.py` / `server.py` / `state.py` / `writes.py` / `readers.py` / `sse.py` / `audit.py`）；
    复跑 `(Get-ChildItem src/agentflow/webui -Filter '*.py').Count`，键 `webui_modules`；
  - 端点清单的唯一来源是 `webui/routes.py` 的 `ROUTES`：**26 条**（GET **19** / POST **7**；
    按读写二分 `READER_ROUTES` **14** / `WRITE_ROUTES` **7**，余 **5** 条是自有端点与外壳/静态：
    `/`、`/index.html`、`/run/{sid}`、`/static/{file...}`、`/api/run-index` —— 最后这条是 A 线自有端点，
    不属于只读面那六个）。2026-10-21 实测，复跑
    `python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import routes as r;print(len(r.ROUTES),len(r.READER_ROUTES),len(r.WRITE_ROUTES))"`
    ⇒ `26 14 7`；键 `webui_routes` / `webui_routes_get` / `webui_routes_post`；
  - 事件种类在 `webui/sse.py` 的 `EVENT_KINDS`：**6** 个
    （`state` / `question` / `answered` / `checkpoint` / `stop` / `heartbeat`）。复跑
    `python -c "import sys;sys.path.insert(0,'src');from agentflow.webui import sse;print(len(sse.EVENT_KINDS))"`，
    键 `webui_event_kinds`；
  - 静态产物在 **`src/agentflow/web/static/`**：外壳 `static/index.html`（948 B）+
    `static/assets/index.D_uyFXzU.js`（115109 B）+ `static/assets/index.C9Q9zyMH.css`（23080 B）；
    （2026-10-21 实测，复跑 `(Get-ChildItem src/agentflow/web -Recurse -File | Select-Object Name,Length)`；
    文件名带构建哈希 ⇒ 重建前端就会换名，别把这三个名字当规格）；
    `src/agentflow/web/` 根一层是**源码/生成器**（`__init__.py` 1753 B、`assets.py` 23902 B、
    `emit_theme.py` 3383 B、`emit_types.py` 6280 B）。**所以运行期不需要 `node_modules`**，
    只有重建前端时才需要（复跑 `(Get-ChildItem src/agentflow/web -Recurse -File | Select-Object Name,Length)`）；
  - 前端源码在 `agentflow/ui/`：`src/api.ts` 声明端点字面量（`ENDPOINTS`）、
    `src/sse.ts` 声明事件 kind（`KINDS`）、`src/types.ts` 声明字段、`src/main.tsx` 声明路由（`ROUTES`）。
- **契约与判据**：
  - `tests/test_webui_contracts.py` 的四条对拍 —— **A 端点**（前端 `ENDPOINTS` vs 后端 `ROUTES`
    逐字）、**B 事件**（`sse.KINDS` vs 后端 `EVENT_KINDS` 逐字）、**C 类型字段**、
    **D 路由**（`main.tsx` 的 `ROUTES`）；正控 + 负控都在；复跑
    `python -m pytest -q tests/test_webui_contracts.py`（当次 26 passed）；
  - 另外两条形态被单独钉住：**静态路由与目录穿越**（`GET /static/<file>` 只服务
    `web/static/` 之下的文件，穿越一律 404、**不回落 `index.html`**）、
    **`/api/*` 未知路径不许吐 HTML**（给 API 客户端一段 HTML 比 404 更坏）；
  - 判据文件共 **15** 个：`test_webui{,_contracts,_help_is_current,_pages,_readers,_readings_format,_roster_panel,_settings_write,_sse,_static,_writes,_browser,_ledger_counts_writes,_live_names_the_host_process,_pending_is_one_list}.py`；
    复跑 `(Get-ChildItem tests -Filter 'test_webui*.py').Count`，键 `webui_test_files`（2026-10-23 复跑实测：15；
    这一格随并行施工变 —— 本节第一次量到的是 10，`test_webui_help_is_current.py` 落地后变 11，
    2026-10-22 的三条（台账写入计数 / 直播点名宿主进程 / 待答只有一张清单）落地后变 14，
    之后再量到 15：多出来的那一件是 `test_webui_readings_format.py`）。
- **已知边界**（照实写，**不许写成"已解决"**）：
  1. `draft/35` 的七层里**没有这一层**（整份文件里 `webui` / `web/` / `Web 端` **0 命中**，
     复跑 `Select-String -Path 'draft\35-… .md' -Pattern 'webui|web/|Web 端'`）——
     它是业主后加的，本文是它第一次被写进分层表；
  2. Web 面另有一份草稿 `draft/114` 记着"九页 / 十条只读面 / 五条写端点"，
     **它与今天盘上的读数不是一个口径**（`ui/src/pages/` 的页数、`READER_ROUTES` 的条数、
     `WRITE_ROUTES` 的条数各自按上面的命令量）—— 引用草稿前先跑命令；
  3. `--allow-writes` / `--no-settings-write` 两个开关**已接线**（裁定 T1 的 W3 / W4）：
     判据在 `webui/writes.py` 的 `authorize()` —— `--allow-writes` 是第 3 层（不开 ⇒
     所有写端点一律 **403**），`--no-settings-write` 是第 4 层（只关 `POST /api/settings`）。
     复跑 `python -m agentflow.cli web --help`（2026-10-21 实测）：help 文本逐字写着这两条行为，
     那句"W3 / W4 才真正生效"**已经不在** help 里了 ⇒ 别再把它写成"还没接线"；
  4. 静态产物的字节数是**构建产物**，重建前端就会变 —— 它们**不是**规格，
     要比对就以 `web/static/assets/` 的盘上事实为准。

---

---

## [规范] §3 适用范围与阅读顺序

### [规范] §3.1 三类读者

| 读者 | 你要遵守什么 | 先读 | 再读 | 禁忌 |
|---|---|---|---|---|
| **人**（本项目的负责者） | 全部；尤其是**禁 AI 区**与**发布门** | `DEVELOPMENT.md`（入口）→ 本节 §3.2 → §5（六条硬纪律）→ §9（提交与评审）→ §10（发布检查） | `ROLE-SPECS.md` §0（公共约定） | — |
| **AI 编码者**（你） | 全部；**并且必须先用证据反驳评审者**（§9.2） | `AGENTS.md`（**禁 AI 区**，最短、最硬）→ §5（六条硬纪律）→ §8（禁止模式清单）→ §6（DoD） | `ROLE-SPECS.md` 里**你要改的那个角色**那一节 | 不读 §8 就动手；改了禁 AI 区却自称"顺手改一下" |
| **审计者** | 用 §6 的 checklist 与 §10 的门的**通过判据**逐条质问 | §6（DoD）→ §10（发布检查）→ §11（FC 状态口径）→ `DEVELOPMENT-APPENDIX.md` A6（FC 覆盖矩阵） | `ROLE-SPECS.md` 对应角色的 §"不变式"与 §"三态与失败模式" | 把"未核实"读成"已通过"（§11 的状态口径是**三档**：已落地 / 部分 / 未落地） |

### [规范] §3.2 阅读顺序（一张图）

```
AGENTS.md（禁 AI 区，先读，最短）
   ↓
DEVELOPMENT.md（入口：改代码前先读哪三节）
   ↓
DEVELOPMENT-SPEC.md §5   六条不可违反的硬纪律  ← 违反任何一条 = 不改
   ↓
DEVELOPMENT-SPEC.md §8   禁止模式清单（静态可查）
   ↓
DEVELOPMENT-SPEC.md §2   八层里你要改的那一层（职责 / 入口 / 判据 / 边界）
   ↓
docs/ROLE-SPECS.md       你改的那个角色的规格（工具面 / 状态机 / 预算 / 三态 / 不变式）
   ↓
DESIGN-*.md              设计理由（**不构成判据**；与代码冲突时以代码为准）
```

**"改代码前先读哪三节"**（`DEVELOPMENT.md` 也逐字给这三条）：**§5（六条纪律）→ §8（禁止模式）→ §6（DoD）**。
改的是某个角色时加读 `ROLE-SPECS.md` 该角色那一节；改的是 Web 面时加读 §2 第 ⑧ 层。

### [规范] §3.3 权威顺序（**冲突时谁赢**）

1. **代码**（`src/agentflow/` + `tests/`）
2. **本文**（规范）
3. **`ROLE-SPECS.md`**（角色规格）
4. `AGENTS.md`（仅禁 AI 区，**与 `.noai-paths` 同级权威**，两处必须逐条一致）
5. `DESIGN.md` / `DESIGN-TOOLS.md` / `DESIGN-INTERACTIONS.md` / `DESIGN-ROLES.md` /
   `DESIGN-CONDUCTOR.md`（**设计理由**；它们描述"为什么"，不描述"现在是什么"；份数按
   `(Get-ChildItem DESIGN*.md).Count` 当次读）
6. `README.md`（**已知过期**；它的两处读数有判据盯着，其余以代码为准）
7. `../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`
   （**现状导读**：逐项带"相对工作区根"的路径。**不构成判据** —— 它排在本清单最后一位，
   冲突时以代码与本文为准。⚠️ 它的 §2 是**七层**，本文是**八层**，见 §2 开头）
8. `DEVELOPMENT-APPENDIX.md`（**历史**；不构成判据，只用来回答"当时是什么样、为什么"）

### [规范] §3.4 盘点方法（怎么量本仓的"现在长什么样"）

> ⚠️ **这一节取代了原文的 §1.4**。原文整节是围绕一份**外部普查**
> 的数字对比表，而那张表的"本文实测"列是一个早已过期的口径
> ⇒ 按 §1.1 它属于**必须删掉**的那一类（读数没有判据、也没有观测时刻之外的凭据）。
> 保留下来的是**口径警告 + 盘点方法**，这才是能长期用的那一半。

**① 外部普查不是本仓读数。** `D:\Incubator\temp\inventory\INVENTORY.md`（盘上存在；
机械产出于 2026-09-24）第 3 行逐字写明它普查的是
**`D:\Incubator\test\test1\`（包名 `abflow`）**，**不是** `D:\Incubator\agentflow\`。
机器可读明细是同目录的 `tools.json`。引用它的规矩：

- 引用 `INVENTORY.md` 的条目时，**必须写"INVENTORY 4.x"（按条目编号），不许写行号** ——
  两份目录的行号不同；
- 引用 `tools.json` 的 `source.file:line` 时，**必须标"（据 `tools.json`，指向 `test/test1`）"**；
- **不要把它的任何数抄进本仓的当前值**：两份代码谱系的角色/工具/动作集合不同。

**② 本仓的盘点以装配为准，不以文档为准。** 任何"工具有几个 / 每个角色有几个 /
哪个角色能拿到写工具"的问题，只有一个权威答案来源：

```powershell
python -m agentflow.cli tools                 # 含 store 的完整装配（LIVE-READINGS 的 cli_tools_* 就是它）
python -m agentflow.cli tools --role <X>      # 单个角色的工具面（含 side_effect 与「需审批」标记）
python -m agentflow.cli tools --json          # 同一份装配的机器可读形态
```

**③ 三个口径不许互换**（见 §3.5）。`build_registry(store=None)` 单独给不出
`build_registry(store=None, workspace_root='.')` 的那个数 —— **缺 `workspace_root` 时 fs 组不装配**。

**④ 判据面优先。** 想知道"这个数有没有人守"，查 §1.2 的手抄数字清单；
想知道"现在是多少"，跑 §0.2 块里那一行点名的命令。**两条都不做、直接相信一段散文，是本节要治的病。**

### [规范] §3.5 禁改区的**三个数**必须并列写，且每个数写清口径（`X-5`）

`draft/25` 的 `D-4.2` **原写**"统一为 **19 glob / 14 台账条目 / 7 类**"——
**这三个数今天全部过期**，而且它们**量的不是同一件事**，所以"统一"这个动词本身就是错的：
把它们并成一个数，读者会拿"清单 glob 数"去对"台账条目数"，然后得出"少了 5 条"的错误结论。

| 数 | 量的是什么 | 当次值 |
|---|---|---:|
| **清单 glob 数** | `.noai-paths` 的**条目行**数（**同一个文件可以登记两次**） | **46** |
| **唯一路径数** | 上述 glob 去重后的路径数 | **43** |
| **台账条目数** | `.noai-approvals.json` 里**有 hash 记录的路径**数 = **需要签字的行数** | **不写定值**（每签一个字就变） |
| **禁改区类别数** | `.noai-paths` 的 `[category: …]` 分组数 | **7** |
| **欠签** | 台账条目 × 2 名 reviewer（`REQUIRED_APPROVALS_ON_HIT = 2`） | **不写定值**（每签一个字就变） |

**前两格与类别数**的复跑命令逐字如下（它们就是 `LIVE-READINGS` 的 `noai_paths_*` 三个键）：

```powershell
(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count                  # ⇒ 46
(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:' |
  ForEach-Object { ($_.Line -split '\s+')[0] } | Select-Object -Unique).Count           # ⇒ 43
(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:' |
  ForEach-Object { if ($_.Line -match '\[category:\s*([a-z\-]+)\]') { $matches[1] } } |
  Select-Object -Unique).Count                                                          # ⇒ 7
```

**后两格**（台账条目数 / 欠签）由 `python scripts/noai_gate.py --check-approvals` 当次产出：
`entries` 的长度是条目数、`sum(len(e['reviewers']) for e in entries)` 是已签数、
`entries × 2 − 已签数` 是欠签。

**差集 = 清单唯一路径数 − 台账条目数**（两个数都见上表；**本行不写定值** ——
差集随人跑 `--baseline` 与新增登记而变，当次以 `python scripts/noai_gate.py --check-approvals`
报出的 `unregistered` 条目为准）。已知的两条边界，逐条说清：

| 不在台账里的路径 | 为什么它没有台账条目 |
|---|---|
| `src/agentflow/release_check.py` | **盘上不存在**（`Test-Path` ⇒ `False`）。它由 `.noai-paths` **刻意先登记路径**（"一旦有人在这里新建它，会自动落入清单而不是绕过门"）⇒ 没有文件就没有 hash。判据面仍有效：`--paths src/agentflow/release_check.py` ⇒ `[requires_human]` + 理由码 **`unregistered`**。**它是差集里最稳的那一条** |
| `src/agentflow/capabilities.py` | **刚纳入清单时台账条目待补、现已补上**：它由决策页**题 3** 的裁决纳入 FC-27 —— 它是 `A–H` 调用矩阵的**真身**。**登记 ≠ 批准**：`--baseline` 只登记 hash、**永远不写 `reviewers`** |

**清单条目行数 − 唯一路径数 = 同一文件重复登记数**（**是派生量，不是差集**，所以这里不写定值）：
`src/agentflow/dedup.py`（`solver-core` + `provenance-dedup`）、
`src/agentflow/providers.py`（同两类的两处）、`src/agentflow/schema.py`
（`schema-migration` + `eval-criteria`）—— `.noai-paths` 自己的注释逐字说明了这是**刻意的重复**。

> ⚠️ **两处被猜错的地方**（`X-5` 原文的候选清单）：`.noai-paths` 与 `AGENTS.md`
> **各自都有自己的台账条目**，所以"清单两处本体没有批准记录"**不成立**。
> 「差集是 5 条」也不成立。**差集是派生量**：加一条登记、或人跑一次 `--baseline`，它就会变。

**判据（三条命令）**：
1. `python scripts/noai_gate.py --check-consistency` ⇒ `一致：.noai-paths 与 AGENTS.md 的清单逐条相同`，**退出码 0**；
2. `python scripts/noai_gate.py --check-approvals --paths <台账里的路径…>` ⇒ 逐条报出
   "命中若干条禁改区路径，其中若干条未获批准（`insufficient_reviewers`）"，退出码 **1**
   （`stale 0`）。**这两个数是当次读数 —— 每签一个字就变，所以本行刻意不写定值**；
3. `.noai-paths` 的条目行计数与 `[category:` 行计数 ⇒ 由 §0.2 的 `LIVE-READINGS` 块产出的
   那三个键（`noai_paths_glob` / `noai_paths_unique` / `noai_paths_categories`）。

⚠️ **`--check-approvals --paths` 的入参是「命中路径数」，不是「清单 glob 数」**：
传清单的条目数进去，它报的是**台账条目数**（因为最小复现集去重 + 剔除台账自身）——
**那不是"清单有那么多条"**。这正是 `X-5` 要防的口径混用。

---

## [规范] §4 目录与命名规范

### [规范] §4.1 包布局（不可随意新增顶层目录）

> **路径口径**：下面的树以 `agentflow/` 为根（这是本文内部的写法）。**相对工作区根**
> 要加一层前缀 —— 例：`schema.py` ⇒ `agentflow/src/agentflow/schema.py`、
> `tools/` ⇒ `agentflow/src/agentflow/tools/`。
> **份数一律不写定值**：包根一层的 `.py` 清单与份数用
> `(Get-ChildItem src/agentflow/*.py).Count` 当次读（完整清单见 `DEVELOPMENT-APPENDIX.md` 的 A2，
> 那是 2026-10-13 的一次历史快照）。

```
agentflow/
├── AGENTS.md                  禁 AI 区（人类专属区）硬约束 —— 改它=改门
├── .noai-paths                机器可读的禁改区 glob 清单（与 AGENTS.md 逐条一致）
├── DEVELOPMENT.md             ← 入口（指路）
├── DESIGN*.md                 设计理由（**份数按命令当次读**：`(Get-ChildItem DESIGN*.md).Count`；不构成判据）
├── README.md                  ⚠️ 已知部分过期；两处读数有判据盯着
├── config.yaml                全部阈值（"所有阈值都在这里，不在代码里"）
├── pyproject.toml             构建 + pytest 配置（**在禁 AI 区里**）
├── docs/                      规格文档（份数按 `(Get-ChildItem docs -Filter '*.md').Count` 当次读）
│   ├── DEVELOPMENT-SPEC.md    ← 本文（规范）
│   ├── DEVELOPMENT-APPENDIX.md ← 历史（不构成判据）
│   └── …
├── src/agentflow/             包（包根一层的 `.py` 清单与份数见本节上方那条命令）
│   ├── schema.py              ★ 数据模型 + 行级校验 + **全部受控词表**（单一来源）
│   ├── store.py               ★ 锁 / 原子写 / 事务 / 事件日志 / ID 分配 / 重建
│   ├── canonical.py           ★ 规范 JSON 字节串的唯一实现（稿件哈希与回执哈希共用）
│   ├── policy.py              ★ 主控策略（四类上限 + 允许边 + 拒绝理由）
│   ├── capabilities.py        ★ 角色能力表 / 写集 / 召唤边（**导入期自检**）
│   ├── conductor.py           ★ 主控（召唤 → 台账 → backend → 终态）
│   ├── scheduler.py           ★ 波浪调度（写集相交 ⇒ 串行）
│   ├── cancellation.py        ★ 协作式取消（一个共享 signal）
│   ├── contextbudget.py       ★ 上下文压缩 / 剪枝 / spill
│   ├── interactions.py        ★ 角色间交互（I1–I12 的判据）+ CONTRACT_VERSION
│   ├── host.py                ★ 接线面：角色登记表 / 接线态 / 接了线的工具层与主控
│   ├── gates.py               ★ H 的门引擎（`GATES` 声明表；门数按 `len(gates.GATES)` 当次读，四态裁决）
│   ├── judges.py / judge.py   ★ 语义判据（`CRITERIA`）与模型判定的唯一缝协议
│   ├── deliver.py             ★ 交付闸门（`gate(...)` ⇒ `DeliveryGate`；不通过时产出可派回的工作项）
│   ├── papercompile.py        ★ 论文包只剩一件事：把 `<项目根>/out/paper/main.tex`（**正文由智能体自己写**）编成 `main.pdf`，并写**框架自己产**的编译回执 `COMPILE-RECEIPT.json`（`tex_sha256` / `pages` / `exit_codes` …）；`receipt_matches_tex()` 是"这份 PDF 是不是盘上这份 tex 编的"的唯一判据
│   ├── agent_loop.py          ★ 模型驱动的决策循环（六种形状 + 观测层 + 长产出落盘）
│   ├── agent_prompts.py       ★ 提示词装配（`PROMPT_VERSION` / `ROLE_BRIEFS` / `SECTION_ORDERS`）
│   ├── modelgw.py             ★ provider 无关的模型网关（**key 的唯一入口**：环境变量 → 机器级设置文件 `settings.json` 的 `model.api_key` → 缺省）
│   ├── settings.py            ★ 机器级设置的一处定义（本机工具链落点 / Mathlib 根 / 模型 key / `workspace.projects_dir`）
│   ├── llmseam.py             ★ 统一的模型缝：一次调用 = 一条审计记录
│   ├── projects.py            ★ 项目工作区（一个项目一个文件夹）
│   ├── verify.py              ★ 全库不变量校验（`Issue(...)` 的调用点/字面量/去重条数**按命令当次读**；量法见 `DEVELOPMENT-APPENDIX.md` A2 那一格里那条 `ast` 命令）
│   ├── agent_a/ … agent_h/ · agent_v/   角色包（**每个角色一个包**：一个动作一个文件 + core.py + _support.py + __main__.py；V 只读，只有 core.py + __init__.py + __main__.py）
│   ├── webui/                 ★ Web 服务端（第八层；模块清单与条数见 §2 第 ⑧ 层）
│   ├── web/                   ★ Web 静态产物与生成器（`static/index.html` + `static/assets/`；见 §2 第 ⑧ 层）
│   ├── cli.py                 命令行入口
│   └── pipeline.py            固定顺序流水线（前三阶段的编排；旧机制，主路径是 `run-agent`）
├── ui/                        前端源码（Vite；`pyproject` 之外的独立子工程，构建产物落到 `src/agentflow/web/static/`）
├── scripts/                   发布门 / 门禁 / linter（份数与清单按 `(Get-ChildItem scripts/*.py).Count` 当次读；**不是运行期依赖**）
├── tests/                     pytest（份数按 `(Get-ChildItem tests -Filter 'test_*.py').Count` 当次读 —— **这一格老得最快**；离线套件，联网套件用 `-m network`）
├── tools/                     开发期工具与探针（份数按命令当次读；其中 `release_all.py`、`coverage_zero_test.py`、`run_each_test_file.py`、`verify_role_specs.py`、`vocab_census.py` 是**发布门/判据本体**）
└── data/ library/ demo/       运行期数据（`data/` 的 JSON 份数 = `schema_tables` + `counters.json`，按 §0.2 那两行命令当次读）
```

### [规范] §4.2 模块职责边界（**一句话判据**）

| 模块 | 只做这一件事 | **不许**做 |
|---|---|---|
| `schema.py` | 数据模型 + `validate()` + **全部跨模块受控词表** | 不 import 任何 `agent_*`；不碰 `store` |
| `store.py` | 锁 / 事务 / 原子写 / 事件 / ID / 重建 | 不写业务规则；不 import `schema` 之外的同层模块 |
| `capabilities.py` | 角色 → 动作 / 写集 / 召唤边（**声明层**） | **不 import `agent_*`**（用 `importlib` 惰性取类，理由见该模块的注释） |
| `policy.py` | 纯策略判定（`Refusal` or `None`） | **不碰存储**、不发召唤 |
| `conductor.py` | 召唤 → 台账 → backend → 终态 | 不产出知识（`CAPABILITIES["M"] == ()`） |
| `scheduler.py` | 波浪划分 + 有界并发 + 顺序合并 | 不做策略判定（调 `policy`） |
| `agent_<x>/` | 该角色的能力实现（**公开方法名 = `ActionSpec.handler_name`**） | 不直接构造 `ToolRegistry`（§8-P5） |
| `tools/*.py` | 有名字 / 有 schema / 有校验 / 有结构化返回 / 声明副作用的原子动作 | 不写业务策略；不互相 import |
| `host.py` | 把角色 / 工具 / 主控接到一起，并如实报出接线态 | 不假装"没接线"是"跑过了"（未接线 ⇒ 不进登记表） |
| `gates.py` | H 的门引擎：`GATES` 声明表 + 四态裁决（`GateResult`） | 不做"没查"与"查了没问题"的折叠（零发现必须自证） |
| `judges.py` / `judge.py` | 语义判据注册表（`CRITERIA`）与模型判定的唯一缝协议 | 不把"没查成"写成"没找到" |
| `deliver.py` | 交付闸门：给一份产物出裁决，不通过时产出**可派回去的工作项** | 不自己改产物 |
| `papercompile.py` | 把智能体写好的正文（`<项目根>/out/paper/main.tex`）编成 `main.pdf`，并写框架自己的编译回执 | **不生成正文、不渲染、不核锚**（正文归智能体自己写） |
| `webui/` | 把台账 / 运行态 / 待回答面板**读出来**给人看，并把人的回答写回去 | 不产生知识、不改台账语义、不绕过 `READONLY_CALL_EXCEPTIONS` 的权限面 |
| `verify.py` | 全库不变量审计 | **不许有写路径** |
| `cli.py` | 入口（把操作固定成几个动词） | 不写业务逻辑（只装配与打印） |

### [规范] §4.3 命名规范

| 对象 | 规则 | 判据（可机械检查） | 出处 |
|---|---|---|---|
| **角色名** | `"A"`…`"H"` + `"V"` + `"M"`，**单一来源 `schema.ROLES`** | `grep -n 'ROLES' src/agentflow/schema.py` 只有一处定义；`tools.ROLES is schema.ROLES` | `schema.py`；`tools/__init__.py` |
| **表名** | `snake_case` 复数（`search_requests` / `research_questions`），**单一来源 `schema.TABLES`** | 任何模块里的表名字面量必须 ∈ `schema.TABLES` | `schema.py` 的 `TABLES` |
| **字段名** | `snake_case`；**ID 字段** `<实体>_id`（`lit_id` / `concept_id` / `question_id`） | 每张表的 `id_field` 在 `schema.TABLES[table]["id_field"]` 里 | 同上 |
| **4 位实体 ID** | `^\d{4}$`（`_ID_RE`） | `schema.is_valid_id()` | `schema.py` 的 `_ID_RE` |
| **过程记录 ID** | `<前缀>-NNNN`（`r-` / `p-` / `t-`），**不占 4 位空间** | `interactions.next_prefixed_id(rows, field, prefix)`（**全项目唯一实现**） | `interactions.py` |
| **ID 分配器** | `schema.ID_COUNTERS`（kind → field）**单一来源** | `tests/conftest.py` 按它**反查**，不另写一张表 | `schema.py` 的 `ID_COUNTERS` |
| **受控词表常量** | `UPPER_SNAKE` 元组，**定义在 `schema.py`**（除 `tools/base.SIDE_EFFECTS` 与 `capabilities.SIDE_EFFECTS` 这一对**交叉断言**的例外） | `grep -n '^[A-Z_]* = (' src/agentflow/schema.py` | `schema.py` 全文 |
| **测试文件** | `tests/test_<被测对象>.py`（`test_agent_a.py` / `test_tools_base.py` / `test_fc05_contract.py`） | 文件名以 `test_` 开头 | `pyproject.toml` |
| **测试函数** | `test_<门名>_<rejects\|accepts>_<情形>` —— **门必须有"拒绝"与"接受"两向** | `grep -c 'def test_.*_rejects' tests/` 与 `..._accepts` 都 > 0 | FC-09 |
| **工具名** | `组.动作`（**必须含一个点**） | `ToolSpec.__post_init__` 抛 `ValueError` | `tools/base.py` |
| **后端/动作方法名** | `agent_<role>.Agent<Role>.<handler_name>`，**由 `capabilities.ActionSpec.handler_name` 声明** | `capabilities.assert_capabilities()` 导入期 `callable(getattr(cls, name))` | `capabilities.py` |

### [规范] §4.4 注释与 docstring 的**语言与形态要求**

| 要求 | 判据（"是/否"可回答） | 落点 |
|---|---|---|
| **中文** | 注释与 docstring 里中文字符数 > 0 | 全项目 |
| **每个公开函数必须有 docstring** | `scripts/lint_rules.py` 的 **R007**：日常档一条 `info`、`--strict` 逐模块 `warning`（**两档都不报 `error`** —— 这条规则今天没有 error 档） | 实测：**`R007` 默认档那条 `info` 消息里的两个数**（公开函数数 / 缺 docstring 数；**按命令当次读，本文不抄定值**）。复算：`python -B scripts/lint_rules.py`，读 `info R007` 那一行 |
| **docstring 必须含"为什么"段落** | docstring 里出现"为什么"或"因为"或"理由"之一，**且**该段说明的是**取舍**（不是复述功能） | 无静态判据；`R007` 只查"有没有"，不查"有没有为什么" |
| **禁止"不是装饰"式注释** | 注释里出现"不是装饰"/"确实"/"真的"这类**防御性措辞**时，**必须**在同一提交里补一条断言 | `LESSONS.md` P9（`literature_keys` 的"不是装饰"四个字透露了 bug 的存在） |
| **禁止注释/docstring 里的装饰** | 注释或 docstring 里出现**成对的星号强调**、**未配对的残留星号**或 **emoji**，即判违规（先摘掉反引号代码跨度再判：`2**20`、`a/**/b`、`handler(**params)` 是字面语法） | `scripts/lint_rules.py` 的 **R009**：禁改区外 `error`，禁改区内一条汇总 `info`（见 §8-P17） |
| **行内注释解释"为什么可以忽略异常"** | `except` 行或 `pass` 前有 ≥4 字注释，或 `# noqa: R001` | **R001** 的判据（当次数见 linter 输出） |
| **每个模块顶部有模块 docstring** | 文件第一个语句是字符串字面量 | 口径：`(Get-ChildItem src/agentflow -Filter '*.py').Count`（**只数包根一层**，不含 `tools/` 子目录；要含子目录得用 `-Recurse`，那是另一个数） |

---

---

## [规范] §5 ⭐ 六条不可违反的硬纪律

> **违反其中任何一条 = 这次改动不算完成**。每条给：
> ① 一句话规则 ② 为什么 ③ 可判定判据 ④ 违反后会怎样 ⑤ 现有正例/反例的落点。
> ⚠️ **落点刻意不写行号**：行号易失（并行开发下几十分钟就漂），
> 所以一律给「文件 + 符号名」，读者用 `grep -n '<符号>'` 定位。

### [规范] §5.1 纪律 1：三态纪律（`True` / `False` / `None` + 受控 `reason`）

**① 规则**：所有"判定"字段必须是三态，**且** `reason` 必须来自受控枚举；
枚举里**必须**至少有一个"未执行"值。**禁止**把 `None` 与 `False` 合并。

**② 为什么**（`LESSONS.md` FC-01 逐字）：
"布尔无法区分'未校验'与'校验失败'，而这两者需要**完全不同的处置**
（前者装 OCR / 补数据，后者改引文 / 剔除）。本项目在**四处**（引文、OCR、D 溯源、
C 预算）都踩到同一坑。"
`DESIGN-CONDUCTOR.md` 逐字补充了后果：
"每一次的后果都是**下游把'我们没查'读成了'查了没有'**。"

**③ 可判定判据**（三条全中才算过）：

| 判据 | 怎么查 |
|---|---|
| 代码里**没有** `if not chk.verified:` 这种把 `None` 与 `False` 合并的写法 | `grep -n 'if not .*verified' src/agentflow/`；**当前无专用 lint 规则**（R001–R012 里没有它；`DEVELOPMENT-APPENDIX.md` 的 A6 里 FC-01 那一行记着同一件事） |
| 每个受控 `reason` 词表**至少含一个"未执行"值** | 逐个人工核对；例：`REFUSAL_REASONS` 含 `not_wired`；`DOWNLOAD_STATUSES` 含 `skipped` |
| 统计输出**分三个计数** | `grep -n 'quote_verified\|quote_unverified\|quote_unknown' src/agentflow/store.py`；`ARunResult` 的 `verified/failed/unknown` |

**④ 违反后会怎样**：下游把"我们没查"读成"查了没有"，于是**不报错**、报告里出现
一条**看起来完全合理的假结论**。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例（最规范）** | `agent_b` 的引文三态字段 | `quotes_verified` / `quotes_failed` / `quotes_unknown` 三个独立字段；`conflict_checks_run`（checked=True）/ `conflicts_detected` / `conflict_checks_skipped`（**checked=False**） |
| ✅ **正例** | `tools/attack_tools.py` 的 `check_budget` | `budget=None` ⇒ `checked=False, allowed=None`，"注意这与'预算用尽'是两件事" |
| ✅ **正例** | `conductor.py` 的 handler 返回值处理 | handler 返回 `None` ⇒ `outcome="no_result"`（**不许**映射成 `ok`） |
| ✅ **正例** | `schema.py` 的 `Task.validate` | `status=done` 时**必须**给 `outcome` —— schema 层硬拦 |
| ❌ **反例** | `tools/search_tools.py` 的 `search.dedup_check` | `except Exception: return []` ⇒ 把"表读不到"折叠成"不是重复"（假阴性） |
| ❌ **反例** | `tools/review_tools.py` 的 `review.report` | `verdict` 完全没读 `dep_check["checked"]` ⇒ 同一个返回值里 `dep_check` 说"没查"、`verdict` 说"通过" |
| ❌ **反例（历史）** | `LESSONS.md` P3 ① | D 的溯源 `tools=None` 静默返回空，报告写成"未能取到任何关系表述——**这本身就是一个重要事实**" |

### [规范] §5.2 纪律 2：单一来源（跨模块字符串只在 `schema.py` 定义一次；`tools.ROLES` 就是 `schema.ROLES`）

**① 规则**：任何**跨模块**的字符串集合（角色名 / 表名 / 字段名 / 受控词表 / ID 前缀）
**只能有一处定义**，其他地方**只能 import**。**禁止第二份副本**（含测试代码、CLI 的 `choices`）。

**② 为什么**（`LESSONS.md` FC-03 逐字）：
"`"agent-D"` vs `"D"`、`download.status` 的受控词表、`title:...|*` 通配键
—— 本项目同族问题出现 **3 次**。"
后果（`DESIGN-CONDUCTOR.md` 逐字）：
"两处各写一份名单，就会出现'schema 认为合法的角色，工具层不认'这种**没有任何报错**的分裂。"
`LESSONS.md` §8.3 更狠的一句：
"**跨模块约定必须只有一处定义（FC-03）在测试代码里同样成立 —— 测试代码也是代码，
写死第二份名单同样会漂移。**"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| `tools.ROLES is schema.ROLES`（**同一个对象**，不是相等） | `python -c "import sys;sys.path.insert(0,'src');from agentflow import schema, tools; print(tools.ROLES is schema.ROLES)"` → **必须 `True`** |
| 角色名单只有一处定义 | `grep -rn 'ROLES *=' src/agentflow/` → **只有 1 处**（`tools/__init__.py` 是 `from ..schema import ROLES`） |
| 表名/字段名只在 `schema.TABLES` 定义 | 任何模块里的表名字面量必须 ∈ `schema.TABLES`；`grep -n '"search_requests"' src/agentflow/*.py` 应只见 `schema.py` 的定义与**必要的字面量使用**（使用允许，定义禁止） |
| ID 分配器只有一处 | `interactions.next_prefixed_id`；**新增第二份 = 违规** |
| 测试夹具不写死名单 | `tests/conftest.py` 按 `S.ID_COUNTERS` **反查** |
| CLI 的 `choices` 来自 `ROLES` | `grep -n 'choices' src/agentflow/cli.py` |

**④ 违反后会怎样**：**没有任何报错**，只是"少了一点东西"（少几个工具 / 少列几个角色 /
判重键不匹配）—— 而"少了一点东西"会在最坏的时刻以"数据损坏"的形态出现。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例** | `tools/__init__.py` 的 `from ..schema import ROLES` | 注释逐字写了为什么不许各写一份 |
| ✅ **正例** | `tests/conftest.py` 的 `sync_counters` | "⚠️ 覆盖范围由 **`S.ID_COUNTERS` 反查**，不在这里另写一张 (kind, table) 表。原先这里写死了 3 个 kind…" |
| ✅ **正例（已修的 CLI）** | `cli.py` 的 `cmd_tools` | 注释逐字："角色清单必须来自 `ROLES`，**不许在这里写死**" |
| ❌ **反例（已修，保留形态）** | `cli.py` 的 argparse `--role` | 曾写死 `choices=["A","B","C","D"]`（实测 `--role E` 退出码 2）—— 函数体修了、**参数层没修**。今天它已改成 `list(S.ROLES)`；**判据是那条命令的退出码** |
| ❌ **反例（已修，保留形态）** | `capabilities.py` 的 `ALLOWED_EDGES["F"]` | 曾写死 `frozenset({"A","B","C","D","E"})`，触发 **R005**（"出现了写死的**完整**角色名单字面量"）—— 已改 `frozenset(S.ROLES)` |
| ❌ **反例（已修，保留形态）** | `agent_d` 的工具 `roles=` | 曾写 `roles=("agent-C","agent-D")` —— **带 `agent-` 前缀**，不是 `ROLES` 里的 `"C"`/`"D"`；且那 3 个工具**不过 `build_registry` 的校验** |
| ❌ **反例（已修，保留形态）** | `verify._id_contiguity` | 曾写死只排除 `search_requests`，新增 `p-NNNN` 后 **`verify` 自己崩掉** |

### [规范] §5.3 纪律 3：fail-closed（未接线 / 依赖缺失 / 读不到 ⇒ 显式失败，**不许静默返回空**）

**① 规则**：任何"上游为 `None` / 依赖缺失 / 文件读不到 / 后端不存在"的分支，
**必须**返回结构化失败（`ok=False` + 受控 `kind`，或 `refused/not_wired`），
**不得**返回空数据、`{}`、`[]`、`0`、`ok=True`。

**② 为什么**（`LESSONS.md` FC-08 逐字）：
"这是本项目最尖锐的缺陷：D 没接上 registry 时走了'无工具'
降级分支并**静默返回空**，报告写成'未能取到任何关系表述——这本身就是一个重要事实'。"
`LESSONS.md` N4 的判据只有一句："**不要把'没做'写成'没查到'**。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 有 `tools is None` / `store is None` / `registry is None` 的分支时，**返回失败而不是空** | `grep -n 'is None' src/agentflow/` 逐个人工看；**R002** 规则（`None`→空容器）报 error |
| 每条"降级/未接线"路径有**一条测试**断言"返回失败而不是空" | `grep -rn 'not_wired\|no_store\|no_backend' tests/` 应有断言 |
| 报告生成器遇到"未接线"**拒绝生成结论** | 人工核对：`agent_d` 的置信度路径是否会把 `checked=False` 写成"证据不足" |
| `except` 必须解释为什么可以忽略 | **R001**（当次数见 linter 输出） |

**④ 违反后会怎样**：错误**伪装成一条合理的结论**（"查过了，没有"），
而它看起来**比报错更像结论**。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例** | `tools/search_tools.py` 的 `search.dedup_check`（修后那一段） | `store is None` ⇒ `fail("…任何判重结论都会是假阴性…", kind="no_store")` |
| ✅ **正例** | `conductor.py` 的 `SubagentBackend` | 恒 `raise NotWiredError` ⇒ `refused/not_wired`（docstring 逐字列出两条诚实的路并选后者） |
| ✅ **正例** | `conductor.py` 的 `LocalBackend` | 对 `("class", cls)` **明确拒绝**："自动 new 只能靠猜，而猜错会静默少做事" |
| ✅ **正例** | `tools/ocr_tools.py` 的 `ocr.run` | 都不可用时 **fail** 并给安装建议（"绝不返回空文本假装成功"） |
| ❌ **反例** | `tools/search_tools.py` 的 `except Exception: return []` | 与同一文件 `:591-598` 的严格 fail-closed **自相矛盾**（同一函数里两种口径） |
| ❌ **反例** | `tools/trace_tools.py` 的 `_g()` | 无 store 无 graph 时返回空图 ⇒ `trace.chain` 仍 `return ok(...)`（唯一一个"成功"的静默空结果） |
| ❌ **反例** | `tools/doc_tools.py` / `review_tools.py` / `attack_tools.py` / `verify_tools.py` | 「未接线」判据有 **4 份**实现（`_not_wired()` × 2 + `_need_store()` × 2） |

### [规范] §5.4 纪律 4：证据等级（`proof` / `cross_check` / `heuristic`；计算类**拿不到** `proof`）

**① 规则**：任何数值/计算产出必须带 `evidence_kind ∈ EVIDENCE_KINDS`；
**计算类方法（`numeric` / `symbolic` / `exhaustive_search`）不得标 `proof`**；
`proof` 必须另带 `verifier_subject_key`。

**② 为什么**（`LESSONS.md` FC-22 逐字）：
"数学里数值实验不构成证明（'验证通过 ≠ 数学正确'）；
而本项目实测证明了'结构自洽 ≠ 内容正确'与'三个绿灯叠加仍不能证明系统有用'。"
`LESSONS.md` M4："数值**只能作为交叉验证**，不能替代证明；同一个个例不能推广为定理。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 数据结构里有 `evidence_kind` 字段且受控 | `schema.py` 的 `EVIDENCE_KINDS` |
| 计算类拿不到 `proof` | `verify.run_experiment` 的降级 + `schema.Experiment.validate`；自检实测"脚本自报 proof 被降级为 cross_check" |
| `proof` 必须给 `verifier_subject_key` | `schema.py` 的 `Experiment.validate` 抛 `ValueError` |
| 报告里 `cross_check` 结论**自动**附加"不构成证明" | `CROSS_CHECK_DISCLAIMER`（`doc.compose_claim` 自动补） |
| "没有 proof 级证据时结论不得标已证明" 有测试 | `tests/test_agent_e.py` / `test_agent_f.py`（**用例数以 `--collect-only` 为准，本行不写定值**） |

**④ 违反后会怎样**：**proof 级证据是假的，而报告照样打印** ——
这是"过度声称"，也是一次**复核者自己犯错**的实例（`PROVED_HERE` 标签）。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例** | `schema.py` 的 `Experiment.validate` | 五条硬约束（含 `verifier_subject_key`） |
| ✅ **正例** | `verify.py` 的 `evidence_kind_overclaim` / `proof_claim_rests_on_weaker_evidence` / `proof_claim_with_unclosed_dependency` | 三条 error 级检查 |
| ✅ **正例** | `agent_e._selftest` | 主动用"想自称 proof 的脚本"验证降级 + notes 留痕 |
| ❌ **反例（历史）** | `DEVELOPMENT-APPENDIX.md` A7 的 D 清单族 | 复核产物用了 `PROVED_HERE` 标签 —— 复核者自己犯了 FC-22 |
| ⚠️ **未落地** | `schema.py` **无** `negation_kind` 对"计算类"的强制（只有 `proof` 的强制） | 见 `DEVELOPMENT-APPENDIX.md` A6 的 FC-25 行 |

### [规范] §5.5 纪律 5：拒绝 ≠ 失败（`outcome="refused"` 是一次**成功**执行）

**① 规则**：框架"正确地说了不"（越权 / 超预算 / 超深度 / 循环 / 未接线）必须记为
`status="done", outcome="refused"` + 受控 `refusal_reason`；
**不许**记成 `failed`。**拒绝也必须落台账**。

**② 为什么**（`DESIGN-CONDUCTOR.md` 逐字）：
"**`refused` 是一次成功的执行** —— 框架**正确地说了"不"**。把它写成 `failed`
会让'策略拦住了'与'代码崩了'混在一起，而这两件事需要完全不同的处置。"
"**拒绝也落台账**：不写这一行，'我们拒绝了它'这件事就**无可审计**。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| `outcome="refused"` ⇒ `status == "done"` | `schema.py` 的 `Task.validate` **硬拦**（`status!=done` 直接 `ValueError`） |
| `outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS` | 同上，**硬拦** |
| `refusal_reason` 非空 ⇒ `outcome == "refused"` | 同上，**硬拦** |
| 拒绝**必须落台账**（有行） | `Conductor._refuse` 写行 |
| 但**"取消后不产生新任务"是例外**（`task_id=None`，无行） | `conductor.py` 的注释逐字解释了这个例外为什么不冲突 |
| `SummonResult.ok` 的判据只有一处 | `conductor.py` 的 `SummonResult.ok`：`status=="done" and outcome=="ok"`（**refused 不算 ok**） |

**④ 违反后会怎样**：两种需要**完全不同的处置**的事情长得一样；
调用方问 `res.ok` 会把"越权被拦住"看成"成功交付"。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例（schema 硬拦）** | `schema.py` 的 `Task.validate` | 三条 `ValueError`，消息里逐字解释理由 |
| ✅ **正例** | `conductor.py` 的 `_refuse` | 返回 `status="done", outcome="refused"`，并写 `started_at == ended_at`（"它一毫秒也没跑"由 detail 里的人话说明） |
| ✅ **正例** | `policy.py` 的 `Refusal.__post_init__` | `reason` 不在 `REFUSAL_REASONS` 里就抛 |
| ❌ **反例** | `tools/attack_tools.py` 的 `can_derive` | 在 `checked is False` 时返回 `blocked_by="incomplete"` —— **用"不完整"这个标签去表示"没检查"** |
| ⚠️ **风险** | `conductor.verify_tasks` 与 `verify.py` 的 tasks 检查是**两套实现** | `conductor.py` 逐字承认并给了理由，但仍是 FC-11 的漂移风险面 |

### [规范] §5.6 纪律 6：派生态不许当输入（**就地推导** 或 **装配期断言**，没有第三种）

**① 规则**：任何"派生字段"（可从别的字段算出来的）在下游被读取时，
**要么就地推导**，**要么在装配期断言它存在**。**不许**"假设上游会填"。

**② 为什么**（一次**完全静默**的失效）：
`detect_contradictions` 直接读行里的 `concept_pair_key`，但 `relations` 表存的字段名是
`concept_group_key` ⇒ 对**直接从表里读出来的行**（C 的 `contradictions()`、任何脚本）
**恒返回 `[]`** —— 不报错、不告警，看起来就像"没有矛盾"。
"**派生态要么就地推导，要么在装配期断言它存在（不许有第三种）。**"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 每个派生字段的每个读点，**要么**当场算，**要么**有断言 | `grep -n 'concept_pair_key\|related_concepts\|concept_group_key' src/agentflow/`，逐个看是否有 `or 推导()` 兜底 |
| **正例的形态** | `interactions.py` 的 `... or concept_pair_key([...])` |
| 派生态与真源不一致必须**可检出** | `verify.related_drift`（warning）；`verify.stale_group_key`（error） |
| 派生字段必须有**重算**路径 | `verify` 重算比对；CLI 有 `repair --related` |
| 可重建存储的**信息量守恒** | `tests/test_rebuild.py`（**用例数以 `--collect-only` 为准**：诊断字段守恒 / 幂等 / 坏事件不炸） |

**④ 违反后会怎样**：**恒返回空 + 静默** —— 与 §5.1/§5.3 的后果同族，
但这个更隐蔽：**没有异常、没有告警、没有空值**，只有一个看起来正常的 `[]`。

**⑤ 正例 / 反例**：

| 类型 | 落点 | 说明 |
|---|---|---|
| ✅ **正例** | `interactions.py` 的注释 + 修正 | 逐字记录了这次失效 |
| ✅ **正例** | `Related_concepts = 由关系表派生` | "不由增量 append 直接决定，由关系表派生"⇒ **可自愈**（漏更新会在下次重算时修正），`verify` 会重算比对 |
| ✅ **正例** | `capabilities.assert_capabilities()`（**导入期**） | "能力表一旦与实现漂移，症状不是崩溃而是**静默的越权/并发损坏**。让它 import 时就炸，是唯一'不可能忘记跑'的校验点" |
| ❌ **反例** | `dedup.literature_keys` 的 `title:<norm>\|*` 第三级键 | 生成后**在匹配时被过滤掉** ⇒ "忽略年份"是死代码 |
| ❌ **反例** | `interactions.related_relation_ids`（升序） | 为满足"升序"不变量**丢掉了跳序**，只能从 `origin` 字符串反解 |
| ⚠️ **部分落地** | `schema.ARRAY_FIELD_KINDS` | 已落地"未声明数组字段即 `verify` 报 `undeclared_array_field`"；`Relation.chain` 的保序字段见 `DEVELOPMENT-APPENDIX.md` A6 的 FC-05 行 |

---

---

## [规范] §6 ⭐ Definition of Done

> **六份 checklist**。每项给"谁来检查 / 在哪检查"。**逐项可勾选**。
> `[ ]` 全部勾上才算 Done。**任何一项无法勾 = 这次改动没完成。**

### [规范] §6.1 新增/修改**表**（`schema.TABLES` + 行 dataclass）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 在 `schema.TABLES` 加了 `{file, row, id_field, id_kind}`；`id_kind` 在 `ID_COUNTERS` 里（若要用 4 位 ID） | 实现者 | `schema.py` 的 `TABLES` |
| 2 | `[ ]` 行 dataclass 有 `validate()`，且**每个受控字段**都有词表校验 | 实现者 | 该 dataclass 内 |
| 3 | `[ ]` `row_from_dict` 加了该表的分支（含嵌套结构的 `from_dict`） | 实现者 | `schema.py` 的 `row_from_dict` |
| 4 | `[ ]` 数组字段在 `schema.ARRAY_FIELD_KINDS` **显式声明**为"集合（升序去重）"或"序列（保序）" | **`verify`** | `verify.undeclared_array_field`（error） |
| 5 | `[ ]` `store.empty_table()` / `Store.init()` 会建这个文件 | 实现者 | `store.py` |
| 6 | `[ ]` `Store.rebuild()` 的事件重放支持该表 | 实现者 | `store.py` 的 `rebuild` |
| 7 | `[ ]` `verify.py` 加了至少一条该表的**引用闭合**检查（若它引用别的表） | **`verify`** | `verify.py` |
| 8 | `[ ]` **两条测试**：① 合法行通过；② 违反每个约束的行**被拒** | 实现者 → 审计者 | `tests/test_schema.py` |
| 9 | `[ ]` **重建守恒**：`rebuild` 前后诊断字段相等 + 幂等（逐字节） | **`tests/test_rebuild.py`** | 发布门第 1 步 |
| 10 | `[ ]` `docs/ROLE-SPECS.md` 里对应角色的 **§状态机** 补了迁移表与终态 | 文档维护者 | `docs/ROLE-SPECS.md` |
| 11 | `[ ]` **写集更新**：`capabilities.WRITE_SETS[role]` 若该表会被某角色写 | **`capabilities.assert_capabilities()`** | 导入期 `AssertionError` |
| 12 | `[ ]` `tests/test_fc05_contract.py` 的数组字段契约测试通过 | **发布门第 1 步** | `tests/test_fc05_contract.py` |

### [规范] §6.2 新增/修改**字段**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 若该字段是"判定"类 ⇒ 三态（§5.1），`reason` 进受控词表 | 审计者 | §5.1 的判据 |
| 2 | `[ ]` 若是受控值 ⇒ 词表定义在 `schema.py`，**只此一处** | **linter R005 / 人工** | `scripts/lint_rules.py` |
| 3 | `[ ]` 若是"状态 ⟹ 其它字段"的关系 ⇒ 写成**交叉检查**（schema 层 `validate()`） | 实现者 | FC-04 判据② |
| 4 | `[ ]` 每条交叉检查有**一条"违反应被拒"**的测试 | 审计者 | FC-04 判据③ |
| 5 | `[ ]` 若是数组 ⇒ 在 `ARRAY_FIELD_KINDS` 声明集合/序列 | **`verify`** | `verify.undeclared_array_field` |
| 6 | `[ ]` 若是"有语义的顺序" ⇒ 与升序集合字段**成对存在**（`related_relation_ids`（升序）+ `chain`（保序）） | 审计者 | FC-05 判据② |
| 7 | `[ ]` 保序字段有 **round-trip 测试**（写→读→相等） | **`tests/test_fc05_contract.py`** | `test_relation_chain_preserves_order_round_trip` |
| 8 | `[ ]` `docs/ROLE-SPECS.md` 对应角色的 §状态机 与 §三态 更新 | 文档维护者 | — |
| 9 | `[ ]` 更新 `DESIGN*.md` 的字段表（**可选**，但若改了必须与代码一致） | 文档维护者 | §12 的处置流程 |

### [规范] §6.3 新增/修改**工具**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` **六件套齐全**：`name / summary / params / returns / side_effect / roles` | **`ToolSpec.__post_init__`（逐件）+ 实测 census** | `tools/base.py` 的 `ToolSpec.__post_init__` **真的逐件校验**：① `side_effect ∈ SIDE_EFFECTS` ② `declared_external ∈ EXTERNAL`（两根轴的受控词表）③ `name` 非空**且含 `.`** ④ `summary` 非空（`strip()` 后）⑤ `params` 是 `Mapping` 且 `params["type"] == "object"` ⑥ `returns` **必须是字符串** ⑦ `roles` 必须是元组。<br>**唯一不由 `__post_init__` 保证的是"`returns` 非空"**：三个内置降级替身没写它 ⇒ 由 census 观察（判据常量 `base.REQUIRED_NON_EMPTY_FIELDS`）。<br>**怎么验（两条命令，都要跑）**：① 负控 —— 构造 `ToolSpec(side_effect="network", …)` ⇒ **导入期就抛 `ValueError`**；② census —— 发布门第 3 项 `tools` 的输出（"六件套缺字段"那一栏） |
| 2 | `[ ]` `side_effect ∈ SIDE_EFFECTS`（`none/read/write_local`）、`external ∈ EXTERNAL`（`none/egress/exec`） | **装配期**抛 `ValueError` | `tools/base.py` 的 `ToolSpec.__post_init__`（B3 收官已删掉遗留取值 `network` 与两张翻译表） |
| 3 | `[ ]` **`side_effect` 与真实行为一致**（双向） | **linter R010（逐工具，三个方向）** + 人工 | R010：**按工具判**，声明非 exec 却起子进程 ⇒ `error`（R010-a），声明 `egress` 却无网络调用 ⇒ `warning`（R010-b），声明 `none` 却链里联网 ⇒ `warning`（R010-c）。**R006 已退休**（文件级共现指不出是哪一个工具，判据面移入 R010；编号保留以免历史报告悬空）。见 §8 的 P7 |
| 3b | `[ ]` 两层声明（工具层 `ToolSpec` vs 能力层 `ActionSpec`）在两根轴上对同一动作说同一句话 | **`capabilities.declaration_divergences()`**（`assert_capabilities` 里的 error 级导入期断言；warning 级只报告） | 判据三种：能力层**低估**外部轴 ⇒ `two_layer_external_divergence`（error）；两层都非 `none` 但**精度不同** ⇒ `two_layer_external_imprecise`（warning，必须可见）；名字对不上或一对多 ⇒ `two_layer_name_unmatched` / `two_layer_name_ambiguous`（info，三态里的 unknown，不是"一致"） |
| 4 | `[ ]` `roles` 里**没有** `READ_ONLY_ROLES`（若它是写工具） | **`for_role` 结构性剥离** + `role_filter_notes` | `tools/base.py` 的 `for_role` |
| 5 | `[ ]` `params` 是 JSON Schema（object 根），**能原样喂给 function-calling** | 人工 | FC-07 / `LESSONS.md` D4 |
| 6 | `[ ]` handler **只收关键字参数**（`spec.handler(**params)` 不报位置参数错） | 实测 census | 对 `build_registry(...)` 的每个 `spec.handler` 取 `inspect.signature`，数有没有 `POSITIONAL_ONLY` 形参；**当次实测：没有发现一例**（数目随装配变，本文不抄定值） |
| 7 | `[ ]` 参数非法 ⇒ **返回结构化失败**（`ok=False` + `kind`），**不抛异常** | **`ToolRegistry.call`** | `tools/base.py` 的 `ToolRegistry.call` |
| 8 | `[ ]` 未知工具名 ⇒ `ok=False, kind="unknown_tool"` | **`ToolRegistry.call`** | 同上 |
| 9 | `[ ]` **返回结构有契约测试**（不是文档） | 实现者 | `LESSONS.md` B8 |
| 10 | `[ ]` 返回里有三态位（若它是"查询"类） | 审计者 | §5.1 |
| 11 | `[ ]` 依赖缺失 ⇒ **fail-closed**（`not_wired` / `no_store`） | 审计者 | §5.3 |
| 12 | `[ ]` 只读工具**调用后工作区字节级不变** | **测试**（目录指纹） | FC-07 判据④；`agent_c` 自检有"I1 服务面只读：三张知识表逐字节不变" |
| 13 | `[ ]` 若是只读工具 ⇒ **不得联网 / 起子进程 / 下模型** | **linter R010（逐工具）+ 人工** | 三个方向见第 3 项；级别是 `warning` 而不是 `error`（判据是字面标记可达，`search`/`download` 按末段相等匹配 ⇒ 真实树上会命中 `re.search`/`rx.search`，那些已逐条登记在 R010 的假阳性表里，以 `info` 继续出现）。**当次数见 §0.2 的 `LIVE-READINGS` 块** |
| 14 | `[ ]` `docs/ROLE-SPECS.md` 的**全局工具总表**加一行（含所有列） | 文档维护者 | `docs/ROLE-SPECS.md` §R0 |
| 15 | `[ ]` `tests/` 里**提到该工具名**（不是只靠"遍历 registry"覆盖） | 实现者 | 见 §1.2 的判据清单 |

### [规范] §6.4 新增/修改**交互**（I1–I12 之类）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 交互的判据在 `interactions.py`（**纯函数**，签名里**没有 `store`**） | **`interactions.assert_store_free`（导入期）** | `interactions.py` |
| 2 | `[ ]` 若涉及新召唤边 ⇒ `capabilities.ALLOWED_EDGES` 更新，且 `assert_capabilities` 通过 | **导入期** | `capabilities.py` |
| 3 | `[ ]` 若涉及新写入 ⇒ `WRITE_SETS` 更新（表级）；只读角色的例外必须**显式登记理由** | **导入期 `assert_capabilities` 第 4 条** | `capabilities.py` |
| 4 | `[ ]` 有**配额/上限**（"每个交互都必须有上限"） | 审计者 | `interactions.DEFAULTS` |
| 5 | `[ ]` 上限用尽时的行为**明确**（拒绝 / 降级 / 落盘）并把理由留在返回里 | 审计者 | `LESSONS.md` A13 |
| 6 | `[ ]` 上限用尽**逐条留理由**（不是静默少几条） | 审计者 | `agent_c` 自检实测："被拒=1 条，示例理由=…已达每轮上限 max_gap_requests_per_run=3 ⇒ 未提交" |
| 7 | `[ ]` 端到端交接测试：**同时**构造"上游产出该状态"与"下游消费它" | 实现者 | `LESSONS.md` P4(b) |
| 8 | `[ ]` 交互的判据有**单测**（`tests/test_interactions.py`，**用例数以 `--collect-only` 为准**） | 实现者 | 发布门第 1 步 |
| 9 | `[ ]` `docs/ROLE-SPECS.md` 的两个角色的 §接口 都更新 | 文档维护者 | — |

### [规范] §6.5 新增/修改**角色**（**最重的一份**）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 角色名加进 `schema.ROLES`（**只此一处**） | 实现者 | `schema.py` 的 `ROLES` |
| 2 | `[ ]` 角色包里有 `Agent<Role>` 类，且每个动作的 `handler_name` **真实可调用** | **`capabilities.assert_capabilities()` 第 2 条（导入期）** | `capabilities.py` |
| 3 | `[ ]` `capabilities.CAPABILITIES[role]` 每条 `ActionSpec` 有 `params`（object 根 + `properties`） | **`ActionSpec.__post_init__`** | `capabilities.py` |
| 4 | `[ ]` `capabilities.WRITE_SETS[role]` **有值**（空也要显式写，且只读角色必须登记例外） | **导入期** | `capabilities.py` |
| 5 | `[ ]` `capabilities.ALLOWED_EDGES` 有该角色（**双向都要想清楚**：它能召唤谁、谁能召唤它） | **导入期** | `capabilities.py` |
| 6 | `[ ]` 若是只读角色 ⇒ 加进 `tools.READ_ONLY_ROLES`，并配**负向权限测试** | 实现者 + **`for_role`** | FC-06 判据④；`tests/test_tools_readonly_roles.py` |
| 7 | `[ ]` 有**自检入口** `python -m agentflow.agent_<role>`，覆盖主路径，**退出码 0** | 实现者 | `python -m agentflow.agent_<role>` |
| 8 | `[ ]` 有专属测试文件 `tests/test_agent_<role>.py` | 实现者 | 发布门第 1 步 |
| 9 | `[ ]` 每个"没有结果"的场景有三态形态 | 审计者 | §5.1 |
| 10 | `[ ]` 所有循环有**上限**，且上限用尽时的行为可读 | 审计者 | `docs/ROLE-SPECS.md` §预算 |
| 11 | `[ ]` 有可被 `verify` 检查的不变式（若产出新表/新字段） | 审计者 | `verify.py` |
| 12 | `[ ]` `cli.py` 的**角色相关 choices 不写死**（用 `list(S.ROLES)`） | **人工**（`grep -n 'choices' src/agentflow/cli.py`；`--role E` 退出码 0） | `cli.py` |
| 13 | `[ ]` `docs/ROLE-SPECS.md` 新增完整一节（**结构必须与既有节一致**：必备子节由 `tools/verify_role_specs.py` 的 `REQUIRED` 当次读） | 文档维护者 | `docs/ROLE-SPECS.md` |

### [规范] §6.6 新增/修改**验证门**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 门有**明确的级别**（`error` / `warning` / `info`），级别写在 docstring **与**文档表里 | 审计者 | FC-13 判据① |
| 2 | `[ ]` 级别规则可表述为两句："表里已记录的缺陷被重算确认" = warning；"表里记录与重算事实矛盾（谎报）" = error | 审计者 | FC-13 判据② |
| 3 | `[ ]` **正控**：好数据必须通过 | 实现者 | FC-09 判据② |
| 4 | `[ ]` **负控**：注入已知坏数据必须报错 | 实现者 | FC-09 判据① |
| 5 | `[ ]` 负控用例**命名可辨认**（`test_<gate>_rejects_*`） | **发布门第 5 步（linter）** | `LESSONS.md` FC-09 落地形态 |
| 6 | `[ ]` 校验器与写入方**共用同一配置来源**（不得一处读配置、一处硬编码） | 审计者 | FC-11；`cli.py` 的 `cmd_verify` 是正确的正面范例 |
| 7 | `[ ]` 校验器函数的这些参数**不得有默认值**，或默认值 = "拒绝执行" | 审计者 | FC-11 判据① |
| 8 | `[ ]` 门的**脚本有退出码**（三档：0/1/2，且 `unknown` 与 `fail` 分开） | **linter R008** | `draft/17` §6.3 教训 |
| 9 | `[ ]` 三分档计数（`verified` / `failed` / `unknown`），**禁止单一通过率** | 审计者 | FC-10 |
| 10 | `[ ]` 报告/CLI 输出**同时展示三个数字** | 审计者 | FC-10 判据② |
| 11 | `[ ]` 有一条测试断言"注入无法校验的样本后 `unknown` 增加而 `failed` 不变" | 实现者 | FC-10 判据③ |
| 12 | `[ ]` 在新门上线前，**在 ≥20 条真实样本上量过触发率** | **人**（不可自动） | `draft/13` §8.1 的教训（旧 `detect_contradictions` 的假报警率；量法与读数见那一节，本文不抄定值） |

---

## [规范] §7 测试规范

### [规范] §7.1 每个验证门**必须**有一正一反（负控）

| 要求 | 判据 |
|---|---|
| 每个门（`validate` / `verify` / `check` / `gate`）至少一条**注入已知坏数据并断言报错**的用例 | `grep -rn 'def test_.*_rejects' tests/` 的命中数 ≥ 门的数量 |
| 每个门同时有**防误伤**用例（好数据必须通过） | `grep -rn 'def test_.*_accepts\|def test_.*_passes\|def test_.*_ok' tests/` |
| 命名可辨认 | 测试函数名以 `_rejects_` / `_accepts_` 结尾或含之 |

**为什么**（`LESSONS.md` FC-09 逐字）：
"只有绿灯不能证明门在工作。本项目用**刻意伪造的假引文**证明了 `verify` 真的会抓，
而当时的缺陷里**没有一条**能被 happy-path 抓到。"
`LESSONS.md` C2 给了反方向的理由："**假报警比不校验更糟**。"

**现有正例**：`tests/test_agent_h.py` 的三类负控（无引用 / 否定未分类 / 依赖悬空）+
落库级负控；`tests/test_agent_c_service.py` 的"负控：邻域相同但名字不同 ⇒ `proposal=review`"；
`scripts/release_check.py` 第 6 项要求 `noai_gate` 的**负控**。

### [规范] §7.2 断言要打在**判据**上，而不是实现细节上

| 反例（弱断言） | 正例（判据断言） |
|---|---|
| `assert count >= 1` | `assert relations_suspect == 1 and suspect_by_quote == 1 and relations_added == 0` |
| `assert "0000→0001" not in body` | **段落级解析**后断言"正文 high 4 / 非 high 0；附录 medium 1；统计 low 1" |
| `assert res.ok` | `assert res.data["checked"] is True and res.data["empty"] is True` |

**为什么**（`LESSONS.md` P11 逐字）：
"一个只做 `count >= 1` 的断言'**既能因正确原因通过，也能因错误原因通过**'——
它在'给结论'上是有害的，因为它会让**相邻的、真正有判别力的断言**看起来像'边界错了'。"
那次误判的真实代价：审查者据此错判了一个**不存在**的缺陷，实现者**用证据反驳**才纠正。

**纪律**：新增断言时**必须同时问**"它会不会把合法的正确实现判错？"（`LESSONS.md` P11(c)）。

### [规范] §7.3 测试夹具**不许写死**表名 / 角色名 / `kind` 列表

| 要求 | 判据 | 现有正例 |
|---|---|---|
| 计数器同步按 `S.ID_COUNTERS` **反查** | `grep -n 'ID_COUNTERS' tests/conftest.py` | `tests/conftest.py` 的 `sync_counters` |
| 角色名单来自 `ROLES` | `grep -n 'ROLES' tests/` 只见 import | 全项目 |
| 表名来自 `schema.TABLES` | `grep -n 'TABLES' tests/` | `tests/test_fc05_contract.py` 的 `test_every_array_field_is_declared` |
| 时间戳一律写死为常量 | `tests/conftest.py` 逐字（"避免测试依赖'当前时间/时区'"） | `conftest.py` 头部 |

**两个**点名要引的实例：

1. **`conftest.sync_counters`** —— `tests/conftest.py` 逐字：
   "⚠️ 覆盖范围由 **`S.ID_COUNTERS` 反查**，不在这里另写一张 (kind, table) 表。
   **原先这里写死了 3 个 kind**，于是新增 `experiment` / `plan` / `doc` / `dep` / … 后失效。
   **测试代码也是代码，写死第二份名单同样会漂移**。"
2. **`cli.cmd_tools`** —— `cli.py` 逐字：
   "⚠️ 角色清单必须来自 `ROLES`，**不许在这里写死**。这里原先写死 `("A","B","C","D")`，
   于是 E/F/G/H 落地之后，本命令会一边报告'工具总数 55'，一边只列 4 个角色的工具数 ——
   而'角色即权限面'恰恰是靠这条命令变成**可打印的事实**的。写死名单让那句
   '评审时可核对'落空。"

> ⚠️ **同一族问题的那处残留已经收口**：`cli.py` 的 argparse `--role` 曾写死 A–D
> （实测 `--role E` 退出码 2）—— 函数体修了、**参数层没修**。今天两层都是 `list(S.ROLES)`；
> **判据仍是那条命令的退出码**：`python -m agentflow.cli tools --role E` ⇒ 0。

### [规范] §7.4 离线确定性

| 要求 | 判据 | 出处 |
|---|---|---|
| 日常套件**离线** | `pyproject.toml` 的 `addopts = "-m 'not network'"` | `pyproject.toml` |
| 需要联网的用例**显式标记** | `@pytest.mark.network`；`markers` 已注册 | 同上 |
| 联网套件**独立可跑** | `python -m pytest -q -m network` | 同上 |
| 限流（429）判 `skip`，**400 一律判失败** | `README.md` 逐字 | 注意：该条最初针对的是 `test/test1` 那一份代码谱系 |
| 默认套件规模 | **不写定值**（读数随并行施工变化）：口径见 §1.1 的"区间 + 观测时刻"与 §0.2 的复跑命令 | §1.1 / §0.2 |

**"进套件 + 默认 deselect"是两个诉求的唯一交集**（`README.md` 逐字）：
"日常套件必须离线、确定性、可重复 —— 否则一次上游限流就会把 CI 搞红，久而久之没人再看红灯。
但有几个真实缺陷（Crossref `select` 参数错误导致全 400、`precise` 模式恒为 0）
**只有真实 HTTP 往返才能发现**，所以它们必须留在套件里（不能只写在文档里），只是默认不跑。"

### [规范] §7.5 时间断言要给余量

| 要求 | 判据 |
|---|---|
| 任何"耗时"断言必须有**余量**（不能断言 `elapsed < 0.1`） | `grep -rn 'elapsed\|monotonic\|time()' tests/` 逐个人工看 |
| 墙钟用 `time.monotonic()`（**不受 NTP 回拨影响**） | `conductor.py` 的逐字注释 |
| 超时类断言用"**至少**花了 N 秒"，不用"**恰好** N 秒" | 现有正例：`agent_e` 自检的 `timeout=1s` 只断言 `result=inconclusive`，不断言精确耗时 |

---

## [规范] §8 ⭐ 禁止模式清单（静态可查）

> **一条一行**：模式 / 为什么禁止 / 反例出处 / 替代写法。
> 表中的 **P1–P9 与 P17–P18** 已经落成 `scripts/lint_rules.py` 的 **R001–R012**
> （**12 条规则**编号可直接跑；其中 **R006 已退休**：判据面移入 R010 的逐工具判定、
> 编号保留以免历史报告悬空；**R004 也已退休**：判据面移入**注册期**
> （`P-1` 把 `roles ⊆ schema.ROLES` 下沉到 `ToolRegistry.register*`），构造点不再有
> 绕过校验的可能，编号同样保留。跑 linter 时摘要行会打印退休名单 ——
> "规则 12 条"不等于"12 条都在干活"）。
>
> **另有一条 `R011`（受控词表的死取值）**：判据落在
> `tools/vocab_census.py`（0.3 秒可复跑），报的是"词表里登记了、而 `src/` 里找不到产出点"
> 的取值。原先那几条已逐条处置（补产出 / 删词表 / 登记为预留）——
> 对一个从来没有产出路径的取值做"预留"，等于把一句办不到的承诺留在词表里；删值 + 写明边界
> 才是根除（边界见 `quoteverify.check_quote` 的 docstring）。它**刻意不做成红灯**：正解是
> `P-22`/`P-23` 的人类口径裁定，用门逼出来就是拿红灯替人做决定。
> 反向那一半（"漏词表"）**本版未实现**，由规则自己打成一条 `info` 声明 ——
> "没查"不许被读成"没问题"。
> ⚠️ **两条"没查成"退路报 `warning`** —— ①读不到 `tools/vocab_census.py`；
> ②普查 `checked=False`（反真空下限不满足）。它们此前与"查过了、干净"一样报 `info`，
> 而 `info` 恰是发布门看不见的那一档（`scripts/release_check.py::item_linter` 只看 `error`）
> ⇒ "探测器坏了"与"词表很干净"在报告里同形。`warning` 让它们在 `--strict` 档可见。
> 第三条"没查成"（反向：漏词表）保持 `info`，因为那是**结构上不可能变绿**的已知缺口。

| # | 模式（静态可查） | 为什么禁止 | 反例出处 | 替代写法 | lint |
|---|---|---|---|---|---|
| P1 | `except Exception: pass` / `except: …` 后**无解释** | "我知道这里会抛且知道为什么可以不管"与"我没注意"必须能区分 | **发现时的一批**（`agent_c` / `agent_d` / `agent_e` / `extract` / `llm` / `pipeline` / `store` 等十几处）；**现已归零** —— 每条都补了**具体**理由，不是空洞 `noqa`（其中两处是"回退链 / `relative_to` 抛错恰恰表示通过"的控制流，一处是 stdout `reconfigure` 的可忽略失败） | ① 让它抛；② 或在 `except` 行写 ≥4 字理由；③ 或 `# noqa: R001` | **R001** |
| P2 | `if x is None: return []` / `return {}` / `return 0` | 把"没做"折叠成"没有"（§5.3） | `tools/search_tools.py` 的 `search.dedup_check`（**已修**：改为 `(rows, read_error)` 三态）；`tools/trace_tools.py` 的 `_g()`（**已修**：改三态，无图可查 ⇒ `no_graph` + `checked=False`） | `return fail("…", kind="no_store")`；或 `return [], "<为什么>"`（**带回伴生原因** ⇒ 不算折叠） | **R002** |
| P3 | **写死角色/表名/kind/字段名单的第二份副本** | FC-03；"测试代码也是代码" | `cli.py` 的 `--role choices`（**已修** ⇒ `list(S.ROLES)`）；`capabilities.py` 的 `frozenset({"A".."H"})`（**已修**）；`agent_d` 的 `("agent-C","agent-D")`（**已修** ⇒ `("C","D")` + 装配期校验） | `from ..schema import ROLES` | **R005**（+ 人工） |
| P4 | **校验器与写入方各持一套判据** | "假报警比不校验更糟"（`LESSONS.md` P7） | `tools/review_tools.py` 的 `verdict` vs `dep_check`（**已修**：`checked=False` ⇒ `unverified`）；`doc.scan_claim` vs `review.scan_document`（**已收敛**：`scan_claim` 改为纯适配层转发 `claimanatomy`）；`conductor.verify_tasks` vs `verify.py` 的 tasks 检查（**已收敛**为 `capabilities.audit_task_ledger` 唯一实现 + 一致性测试） | 判据只有一份函数；两处都 import 它 | 人工 / 后续规则 |
| P5 | **`tools/__init__.py` 之外的 `ToolRegistry` 直接构造**（绕过角色校验） | `build_registry` 的 `bad_roles` 断言是"字符串拼法不同导致静默失配"的唯一通用解法 | 发现时的一批（`agent_d` / `agent_e` / `agent_f` / `agent_h` / `tools/fs_tools.py` / `tools/table_tools.py`）。**现在一个 `warning` 都没有**：R004 退休后那两处由**注册期断言**（`P-1`）覆盖，而注册期断言**不进 linter 报告**；其余早已降为 `info`（已调用了同一份校验，或已逐点登记为例外） | `build_registry` / `build_for_role`，或**显式调用同一份校验函数** | **R004 已退休**（判据移入注册期，见 `scripts/lint_rules.py::RETIRED_RULES`） |
| P6 | **同名不同契约的重复实现** | 同一语义两种拼法，两边都不报错（FC-03 的"少了一点东西"） | `textutil.slugify(text, limit=60)`（保留 CJK，空⇒`"untitled"`）vs `fetch.slugify(text, max_length=80)`（**剥掉 CJK**，空⇒`"download"`）；`dedup.normalize_doi` vs `providers.normalize_doi` —— 实测 `http://dx.doi.org/10.1000/abc` 一份原样保留、一份归一化 | 保留**一份**实现，另一处 import；或**显式登记**为"刻意的两个类" | **R003**（+ 例外清单） |
| P7 | **声明与代码不符**（**双向**）：① 声明 `side_effect="read"` 却联网 / 起子进程 / 下模型；② 声明**不执行**（`external != "exec"`）却在起子进程；③ 声明**出网**（`external == "egress"`）却全文无网络调用 | `side_effect` / `external` 是审批与沙箱的**唯一可信判据**；声明撒谎 ⇒ 权限面在说假话。**保守的假话仍然是假话**：审计问"哪些工具会出网"时会把不联网的工具列进去 | `ocr.run`（曾声明 `read` 却下载模型 —— B3 收官已改成 `write_local` + `egress`）；`ocr.backends`（`read` 却工作区外 mkdir + 起进程）；`verify.detect_verifier`（`none` 却起子进程，已逐条登记为例外）；`verify.check_formal`（曾声明 `read` + `none` 却起调用方给内容的检查器 —— B3 收官已改成 `read` + `exec`） | 声明成真实的取值：`external ∈ {none,egress,exec}` **加** `effect ∈ {none,read,write_local}`，两根轴各自如实 | **R010**（逐工具，三个方向）；**R006 已退休** |
| P8 | **检查脚本没有退出码**（或"未报错"被当成"无问题"） | `draft/17` §6.3 逐字："多数脚本不设退出码…（假阴性）而**'未报错'被误读成'无问题'**" | 参考体例里只有极少数脚本有退出码 | 三档退出码：`0=clean / 1=requires_human（或 fail）/ 2=unknown`；`unknown ≠ clean` | **R008** |
| P9 | 公开函数**没有 docstring** | 文档是接口的一部分；lambda 化的 handler 更是**只有** `summary` | 实测**由 `R007` 默认档那条 `info` 消息当次产出**（公开函数数与缺 docstring 的模块分布都在那条消息里；**本文不抄定值**，复算同 §4.4） | 补 docstring（含"为什么"段） | **R007**：日常一条带分布的 `info`；**`--strict` 逐模块 `warning`** |
| P10 | 在 `except` 里**改变量后静默继续**（把失败变成默认值） | 同 P2，但更隐蔽 | `agent_b` 的 download 失败分支是**正面**（`return None, "…失败：…"`）；反例见 P2 | 同 P2 | 人工 |
| P11 | 用**错误信息里的字符串前缀**充当跨模块状态 | 前缀脆弱（改一个字就失效） | `LESSONS.md` N8 / `draft/13` §8.3 | 提升为受控取值 + schema 校验 | 人工 |
| P12 | 把空字符串/空列表当"通过" | Python 里 `"" in "abc"` 是 `True` | `LESSONS.md` N6 / E3（`quoteverify` 必须显式挡空引文） | 先判非空，再比对 | 人工（`quoteverify` 已落地） |
| P13 | 按**后缀名**或 **HTTP 200** 判断"拿到的东西是对的" | 同一实测案例同时否证两条朴素策略 | `LESSONS.md` N19 / N20（`.pdf` URL 返回的是 HTML） | 内容类型校验（`content_type_mismatch`）+ 下游**必须消费**它 | 人工 |
| P14 | **只改代码不补"防止用错方式修好"的断言** | 有两条修复路径时，错的那条会让断言变绿而语义变坏 | `LESSONS.md` N9；3 个现成正例：`test_precise_results_are_on_topic`、`test_agent_b_still_processes_normal_downloads`、`test_valid_download_statuses_are_accepted` | 再写一条断言把错路径**堵死** | 人工 |
| P15 | 让**告警噪音化** | "假报警会训练人忽略告警"，"文化性损伤，几乎不可逆" | `LESSONS.md` N13 / P7 | 分级（error/warning/info）+ "已知缺陷"降级 + 上线前量触发率 | 人工 |
| **P16** | ⭐ **让判据"真空通过"**：受检对象的声明**解析不出东西**，而判据把"解析不出"当成"没有问题"（空集永远是子集） | 这比"判据太松"更贵：它不是"某条判据漏了"，而是**"这条判据在大多数对象上根本没执行"**，而报告里它一直是绿的 | **实测**：`returns=` 的"声明 vs 实现"判据的正则只抓单引号键，于是不带引号的 `returns=` 被抽成**空集** ⇒ `declared - actual == {}` **永远成立** ⇒ 该判据在**多数工具上从来没跑过**（`PROPOSALS.md` **G-4**；当次比例见那一节） | ① **解析失败必须是一个可判定的结论**（三态：`parsed` / `empty_declaration` / `unparseable`），不许折叠成空集；② 给每条判据配一条**反真空断言**（"受检集合非空"或"被跳过的对象数 ≤ 一个写下来的 N"）；③ 解析器要**结构化**（顶层键 + 每个键的列表项键），并在测试里**双向**比对 | 测试（`tests/test_tools_returns_declaration.py`） |
| **P17** | ⭐ **注释与 docstring 里的装饰**：Markdown 强调（成对的星号）、未配对的残留星号、emoji | 源码不经过渲染器：写在里面的星号到了读者眼里只是星号 —— "强调"没被传达，传达的是"这段文字是被生成出来的"。这类标记会**扩散**：下一段注释照抄上一段的写法，几十个文件后就成了默认风格 | 立项前的普查（含成对星号 / 残留星号 / emoji 三类计数，逐条见 `draft/28` §176 与 `PROPOSALS.md` 的 P17，**本文不抄定值**）：**禁改区外**曾两次归零、两次被并行施工重新积起来；**禁改区内**仍是**人**的待办（AI 不得改，见 §9.4） | 要强调就把它写进句子；要粗体/插图就写进 `docs/` 与 `draft/`（那里的 markdown 真的会被渲染）。代码跨度里的 `**`（`2**20`、`a/**/b`、`handler(**params)`）是字面语法，判据先摘掉再判 | **R009**：区外 `error`；禁改区内只报一条汇总 `info`（区内只有人能改，报 `error` 等于造一条永远红的灯，见 P15） |
| **P18** | ⭐ **编排层写产物不控行尾**（`Path.write_text()` 不带 `newline=`） | `write_text` 在 Windows 上把 `\n` 刷成 `\r\n` ⇒ 产物的 `sha256` 与"盘上那一版"对不上，而禁改区批准台账钉住的正是 `sha256` | `tools/release_all.py` 的注释引用过一条禁令 `G-42：禁止 Path.write_text()`，而当时 `RULES` 里只有 R001–R011 —— **那条"被引用的禁令"在门里查不到**（实测）：读者以为有机器防线，实际只有一段散文 | 写产物的两种合规写法：`open(..., newline="")` 或 `write_bytes`；逐条登记的豁免见 `scripts/lint_rules.py::R012_NEWLINE_EXEMPTIONS`（登记过期会被反向报出来） | **R012**（`warning`；`scripts/release_check.py::item_linter` 走严格档，会逐条打印） |

---

---

## [规范] §9 提交与评审规范

### [规范] §9.1 一次改动必须带什么证据

| # | 必须提交的证据 | 判据（"是/否"） |
|---:|---|---|
| 1 | **复跑命令 + 真实输出**（不是"我跑过了"） | 提交说明里含代码块，且是**粘贴的输出**（含 `exit code`） |
| 2 | 若改了 `src/` ⇒ `python -m pytest -q` 的**完整末行** | 末行形如 `NNN passed, M failed, K deselected in Xs` |
| 3 | 若改了某角色 ⇒ 该角色的**自检**退出码 | `python -m agentflow.agent_<x>`；退出码 0 |
| 4 | 若改了工具 ⇒ **工具普查**（工具数 / 角色工具数 / 只读泄漏） | `python -m agentflow.cli tools` 的输出（**三个数当次读**；泄漏那一行今天**不是空表**，见 §2.1 ③） |
| 5 | 若改了表/字段 ⇒ `verify` 的 **error = 0** | `python -m agentflow.cli verify` |
| 6 | 若改了禁 AI 区 ⇒ `noai_gate` 的判定（`clean` 或 `requires_human`+2 批准） | `python scripts/noai_gate.py --paths <file>` 的退出码 |
| 7 | 新增验证门 ⇒ **正控 + 负控两条测试** | 见 §7.1 |
| 8 | 新增公开函数 ⇒ docstring（含"为什么"段） | **R007** |
| 9 | 修一个缺陷 ⇒ **同时**提交"防止用错方式修好"的断言 | §8-P14 |
| 10 | 修一个"漏判" ⇒ **同时**提交"不该判的时候不判"的用例 | `LESSONS.md` P16(a) |

### [规范] §9.2 ⭐ **实现者必须用证据反驳评审者**

**规则**：当评审者给出一个判断（尤其是"这里有个 bug"或"你的断言太松"）时，
**实现者有责任用证据检验它**；若评审者错了，**必须用证据反驳**——
**"评审者说"本身不是判据**。

**为什么**（`LESSONS.md` P11 与 `draft/11` §11 的一手教训）：
一次真实的审查者误判：审查者看到 C 的自检失败 `正文只含 high 路径`，结合上一行
`[PASS] low 路径没有进正文`，**断言**"`medium` 进了正文，违反需求"。
**判断是错的**：正文渲染的是 `群(0000) → 阿贝尔群(0001)` 这种**带名字**的形式，
而失败断言查的是紧凑串 `"0000→0001→0002"` —— 那个串**只出现在统计段**，
所以断言**恒假**，与 medium 毫无关系。
误判根因："**是因为上一条 low 断言同样很弱**（只做 `count >= 1`），
于是'一个 pass 一个 fail'的组合被我看成了'分级边界错了'"。

**处理方式才是重点**：实现者**没有借机放宽断言**，而是
① 把附录标题改成明确写"**未达正文标准、不作为证据**"；
② 把断言换成**段落级解析** —— **测试反而更强**。

**可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 每次"评审者说有 bug"的结论，提交里含一条**能证伪它的命令 + 输出** | 提交说明 |
| 反驳时**不许**通过放宽断言来"修好看" | diff 里**新增**的断言数 ≥ 删除的断言数 |
| 评审结论若被证伪，**被证伪的那条断言必须按"更强的形态"重写**（不是删掉） | `draft/11` §11.3 的范例 |

### [规范] §9.3 发布前的完整门（**一条命令**）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python tools\release_all.py                # 七步：见 §10.1；三档结论，退出码 0/1/2
python tools\release_all.py --json dist\release.json
```

**分步跑**（调试时用；⚠️ 分步跑**不构成**发布检查的绿色结论 ——
`release_all.py` 会把没跑的步骤记成 `unknown`）：

```powershell
python scripts/release_check.py            # 八项，退出码 0/1/2
python tools/verify_role_specs.py          # 角色规格结构完整性（§10.3）
python tools/coverage_zero_test.py         # 零测试公开函数风险分档
python tools/frontend_gate.py              # 前端步：typecheck + 构建 + 入库产物新鲜度
```

**⚠️ 当前状态如实登记**：`scripts/release_check.py` 的 docstring 自陈

```
authored_by: AI agent（本框架的构建者），**尚未经人逐行走查**
required_approvals: 2（尚未取得）
```

逐字理由（该文件 docstring）：
"**这个门现在是'未批准'状态**，它跑出来的绿灯**不构成发布许可**。
把这句话写进 docstring 而不是写进某个聊天记录里，是因为它是这个文件**最重要的属性**——
一个'看起来在把关、其实自己还没被审过'的发布脚本，正是 FC-27 说的那种
'测试全绿、上线即越权'的形态。"

### [规范] §9.4 禁 AI 区的人工门槛

> **本文不重复清单内容。** 清单在 **`.noai-paths`**（机器可读 glob），
> 硬约束说明在 **`AGENTS.md`**；两者由 `scripts/noai_gate.py::check_manifest_consistency()`
> **逐条比对**（实测：`一致：.noai-paths 与 AGENTS.md 的清单逐条相同`，退出码 0）。

**四个本体都实测在盘上**（这一格是判据要的字面量，`tests/test_release_all.py` 逐字锚着它；
它**必须**保持"引用块里的表格行"这个形状 —— 那条负控往这一行尾部注入更正说明来证明判据咬人）：

> | 本体 | 现状 |
> |---|---|
> | `.noai-paths` | **已存在**（机器可读的禁改区 glob；条目数与类别数见 §3.5，判据见 §0.2 的 `noai_paths_*`） |
> | `AGENTS.md` | **已存在**（含 `NOAI-MANIFEST` 区块，与 `.noai-paths` **逐条一致**，`--check-consistency` 退出码 0） |
> | `.noai-approvals.json` | **已存在**（批准台账：`sha256` 钉住"被批准的那一版"；**登记 ≠ 批准**，`--baseline` 永不写 `reviewers`） |
> | `scripts/noai_gate.py` | **已存在**（退出码 0/1/2 三档；`REQUIRED_APPROVALS_ON_HIT = 2` 是**单一来源**） |

| 事项 | 去向 |
|---|---|
| 哪些路径是禁 AI 区（当次 **46** 条条目 / **43** 条唯一路径 / 7 个分组；口径与复跑命令见 §3.5） | **`.noai-paths`** |
| 命中之后要做什么（停 / 人编写或人逐行走查 / 2 名 reviewer / 机器执行） | **`AGENTS.md`** 的"命中之后要做什么" |
| 退出码语义（`0=clean` / `1=requires_human` / `2=unknown`，**`unknown ≠ clean`**） | **`AGENTS.md`** 的"退出码"节 + `scripts/noai_gate.py` |
| 实际判定 | `python scripts/noai_gate.py --paths <改动的文件…>`（或 `--git`、`--stdin`、`--json`、`-q`） |

**本文只补三条 AGENTS.md 未展开的判据**：

| # | 判据 | 检查 |
|---:|---|---|
| 1 | 禁改区清单**两处逐条一致**（FC-27 判据①，符合 FC-03） | `python scripts/noai_gate.py --check-consistency` 退出码 0 |
| 2 | 该规则本身有**负控**（构造一个命中禁改区的改动，断言 CI 拒绝） | `tests/test_noai_gate.py`（负控在跑，见 §11 的 FC-27 那一行） |
| 3 | 命中时**要求 `required_approvals=2`**，且该数字**只有一处定义** | `scripts/noai_gate.py` 的 `REQUIRED_APPROVALS_ON_HIT = 2`（**单一来源**） |

---

## [规范] §10 ⭐ CI 等价的发布检查

### [规范] §10.1 ⭐ **一键盘**是 `tools/release_all.py`（`release_check.py` 是其中的一步）

用户点名的"一键发布检查"逐字是：**"全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter"**。
`release_check.py` 覆盖其中**五项 —— 唯独没有"验收测试"**。所以正式的入口是编排层：

```powershell
python tools\release_all.py                       # 全跑
python tools\release_all.py --json r.json
python tools\release_all.py --only role-specs      # 调试时只跑一项
python -c "import sys,pathlib;sys.path.insert(0,'.');from tools.release_all import build_steps;print([s.key for s in build_steps(pathlib.Path('.').resolve())])"
```

**步骤清单以上面最后那条命令当次产出为准**（本文不抄定值；当前是 `release-check` /
`acceptance` / `repro` / `role-specs` / `coverage` / `per-file` / `frontend`）：

| 步骤 key | 覆盖用户点名的哪一项 |
|---|---|
| `release-check` | 全量测试 + 全部自检 + verify + 工具普查 + linter（+ 禁 AI 区门 / 契约版本 / 源码树可导入） |
| `acceptance` | **验收测试**（`test/test2/run_acceptance.py`，`AGENTFLOW_TARGET=formal`） |
| `repro` | 论文独立复现 —— 用户要求的证据 |
| `role-specs` | 角色规格结构完整性（`tools/verify_role_specs.py`，见 §10.3） |
| `coverage` | 零测试公开函数的**风险分档**清单（`tools/coverage_zero_test.py`；**发布门的口径是 `--level 2`** ⇒ 等级 ≤ 2 的零测试函数必须为 0、退出码 0；等级 3/4 不在门里，只列清单） |
| `per-file` | **逐文件单跑门**（`tools/run_each_test_file.py`）：把"全量绿掩盖单文件红/顺序依赖"变成可判定的结论 |
| `frontend` | **前端步**（裁定 G2）：`tools/frontend_gate.py` 的 typecheck + 构建 + **入库产物新鲜度** —— 它守的是"入库的前端产物与源码脱节"，自带三态 `0/1/2` |

**两条刻意的取舍**（改它们等于改门的强度，所以这些文件在禁改区里）：

1. **`--skip` 掉的步骤记成 `unknown`，不是 `pass`** —— 否则 `--skip acceptance`
   就成了"发布门全绿"的捷径。
2. **超时 / 起不来 ⇒ `unknown`，且 `timed_out` 的判断必须先于退出码** ——
   Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 **无法区分**。

总判定：**任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`**；退出码 0/1/2。

> ⚠️ **它全绿也不构成发布许可**：它自己与 `scripts/release_check.py` **都在 FC-27 禁改区**，
> 仍需人逐行走查 + 2 名 reviewer 批准（§9.3）。

### [规范] §10.2 八项检查、通过判据、失败退出码（实测自 `scripts/release_check.py` 的 docstring 与源码）

| # | 项 | 跑什么 | 通过判据 | 该失败时的 `verdict` |
|---:|---|---|---|---|
| 1 | **全量测试** | `pytest -q` | 退出码 0，且 **0 failed**、**0 errors** | `fail`；收集错误/超时 ⇒ **`unknown`**（"pytest 因为收集错误没跑起来既不是'通过'也不是'失败'"） |
| 2 | **模块自检** | 各 agent + `pipeline` 各自 `python -m agentflow.X` | 全部退出码 0 | `fail`（任一 `exit_code != 0` 或未启动或超时） |
| 3 | **工具普查** | 自建脚本调 `build_registry` | 工具数与角色工具数**可复现**；只读角色写工具泄漏逐条可解释 | `fail`；脚本起不来 ⇒ `unknown` |
| 4 | **全库校验** | `verify_all` | **error = 0** | `fail`；跑不起来 ⇒ `unknown` |
| 5 | **linter** | `scripts/lint_rules.py` | **error = 0** | 退出码 2 ⇒ **`unknown`**；其它非 0 ⇒ `fail` |
| 6 | **禁 AI 区门** | `noai_gate --check-consistency` + `--paths <改动集>` | 一致性退出码 0，**且**本次改动集判定明确 | 一致性非 0 ⇒ `fail`；gate 退出码 1 ⇒ `fail`（requires_human）；退出码 2 ⇒ **`unknown`** |
| 7 | **契约版本** | 比 `agentflow.CONTRACT_VERSION` vs `interactions.CONTRACT_VERSION`；`schema.SCHEMA_VERSION` vs `__schema_version__` | 一致 | `fail` |
| 8 | **源码树可导入** | 每个模块单独 import | 全部成功（**循环依赖**会在这里炸） | `fail`；跑不起来 ⇒ `unknown` |

**总判定与退出码**（`release_check.py` docstring 逐字）：

```
0 = 全部 pass
1 = 有 fail
2 = 有 unknown（**没跑成 ≠ 通过**），或检查器自身出错
```

**⭐ 三态纪律在发布门上的落地**（逐字）：
"`unknown` 与 `fail` 分开，且都不等于 `pass`。这是三态纪律在发布门上的落地：
'pytest 因为收集错误没跑起来'既不是'测试通过'，也不是'测试失败'，
把它算成任何一档都会掩盖真相。"

**为什么第 1 项全绿进不了"可以发布"**（逐字）：
"已交付的缺陷里**没有一条**能被 happy-path 抓到。所以发布门不只看'测试过没过'，
还看**门本身有没有被校准过**（第 3/4/5/6 项）与**契约版本有没有对齐**（第 7 项）。"

### [规范] §10.3 发布门**之外**的第二道门：`tools/verify_role_specs.py`

用户对正式版的要求里有两条是**文档**要求：
**"为 A–H 八个角色各写详细规格说明书"**（并逐字点名了八个必备子节），
以及审计判据里的 **"docstring 与实现一致"**。

一份几千行的规格**最容易的坏法不是写错，而是写漏** —— 少写一节，**没有任何东西会变红**，
而读者会以为"这一节大概没有那些内容"。所以这条也做成门：

```powershell
python tools\verify_role_specs.py            # 退出码 0=完整 / 1=有缺失 / 2=没查成
```

| 结论 | 含义 |
|---|---|
| `ok` (0) | 每个角色节（A–H + V + M）的必备子节齐全、顺序与 `schema.ROLES` 一致，且每节的工具面子节标题里能读出**工具条数**（供与普查对账） |
| `incomplete` (1) | **查过了、有缺失** —— 逐条打印是哪一节缺哪一项 |
| `unknown` (2) | **没查成**：文档不存在 / 读不到 / 一个角色节都没匹配到。**`unknown` 绝不是 `ok`** |

**它为什么不在 `release_check.py` 里**（如实说明，而不是遗漏）：
`scripts/release_check.py` 本身在 FC-27 禁改区，**给它加一项要人审**
（`PROPOSALS.md` 的 P-2/P-3 是同一类待办）。
所以这道门目前是一个**并列的、可单独复跑**的门，并在 `tests/test_role_specs_complete.py`
里有负控（"删掉一节 ⇒ 必须报 `incomplete`""文档被改名 ⇒ 必须报 `unknown` 而不是 `ok`"；
**用例数以 `--collect-only` 为准**），以及一条**文档 ↔ 实测普查对账**：
文档每节标题里的工具条数必须等于**真的跑一次** `python -m agentflow.cli tools` 得到的数字
（而不是测试里硬编码一份逐角色字典 —— 那会把测试绑死在当前状态上）。

---

## [规范] §11 FC-01…FC-27 的状态口径

> **状态口径（三档，不许含糊）**：
> - **已落地** = 代码里有实现**且**有测试/验收判据；
> - **部分** = 有实现但缺某一判据，或只在部分模块落地；
> - **未落地** = 在 `src/agentflow/**` 里**找不到**实现（用 token 搜索为证）；
> - **未核实** = 没查，或查了但证据不足。
>
> **一条 FC 只允许一个状态**。逐条的落地位置、判据、状态**全表**在
> `DEVELOPMENT-APPENDIX.md` 的 A6（那是 2026-09-26 的一次快照，**不构成判据**；
> 要当前值就按 A6 表里的判据当场跑）。
> 本文只保留**唯一一条**必须留在这里的 FC —— 因为它的判据就是 §9.4 与本节。

| FC | 约束（简写） | 落地位置 | 可判定判据 | 状态 |
|---|---|---|---|---|
| **FC-27** | 禁 AI 区必须显式列出 + 独立准入门槛 | **`.noai-paths`**（当次 **46** 条条目 / **43** 条唯一路径 / 7 个分组，见 §3.5）+ **`AGENTS.md`** 的 `NOAI-MANIFEST` 区块 + **`scripts/noai_gate.py`**（`REQUIRED_APPROVALS_ON_HIT = 2`，退出码 0/1/2）；`tests/test_noai_gate.py` 当次 124 passed（复跑 `python -m pytest tests/test_noai_gate.py --collect-only -q -p no:cacheprovider`，键 `noai_gate_pytest_collected`）；`release_check.py` 第 6 项 | ① 两处**逐条一致**（实测退出码 0）；② 命中要求 2 批准（实测 `--paths src/agentflow/schema.py` → 退出码 1 + `required_approvals=2`）；③ 负控用例**在** `tests/test_noai_gate.py` 里（该文件当次 **0 skipped** ⇒ 负控真的在跑） | **已落地**。⚠️ 发布门上它**仍报红**，红的原因是"**禁改区命中待 2 名 reviewer 签字**"（制度要求；台账当次的 `reviewers` 元素总数**不写定值**，每签一个字就变），不是代码坏 |

---

## [规范] §12 `DESIGN*.md` 与代码的关系（**总则**）

`DESIGN*.md` 描述的是**设计与理由**，**不是现状**（份数按 `(Get-ChildItem DESIGN*.md).Count` 当次读）。
已知的类别性偏差与处置：

| 类别 | 例子 | 处置 |
|---|---|---|
| 设计里"待决"的问题，代码里已经有实现 | `DESIGN-CONDUCTOR.md` §8 待决问题 1（"M 是确定性的策略执行者"）—— `conductor.py` 已按此实现；问题 2（跨会话恢复"不自动续跑"）—— `verify.task_still_running`（warning）已落地 | **以代码为准**；设计文档改不改由人决定 |
| 设计里"本轮不做"，代码里已经做了 | `DESIGN-CONDUCTOR.md` §8 待决问题 3（`WRITE_SETS` 粒度"本轮是表级"）—— 代码**确实是表级** | — |
| 设计里给的数字，代码里不同 | `DESIGN-CONDUCTOR.md` 的 `Policy` 默认值与 `policy.py` 的默认值 **逐字一致** | 一致即不必动；不一致时**以代码为准** |
| 接口签名 | 例：`DESIGN-ROLES.md` §2.4 写 `verify_fixes(doc_id, round_no)`，实际 `verify_fixes(doc_id, *, round_no)`（`round_no` 是 keyword-only） | **以代码为准** |

**本文与代码冲突时的处置流程**：① 先按 §9.2 用证据确认是谁错了；② 若错在本文 ⇒
改本文（并把那一格数字换成"命令 + 键名"，见 §1.1）；③ 若错在代码 ⇒ 按 §6 的 DoD 改代码 +
补判据；④ 两边都对但口径不同 ⇒ 把两个口径**都写出来**（§3.5 就是范例）。

## [规范] §13 ⭐ 提示词与判据的分工（2026-10-19 业主裁定）

**一句话**：**提示词管「想让它这么做」，判据管「不许它不这么做」。**

### §13.1 三条去向，先分类再动手

任何一条要求，动手前先问：**它能不能被机器判？**

| 能不能被机器判 | 放哪儿 | 本仓的例子 |
|---|---|---|
| **能** | **判据**（pytest / 写入期闸 / 审计档 / 收工门），**并且必须配负控** | `proof_review` 必须绑 V 签（`store._refuse_fake_proof_review` ＋ `verify._check_13`）；system prompt 逐字节稳定（`promptstability.step_stability`）；预算耗尽 ⇒ 退出码 4（`cli._run_agent_exit_code`） |
| **不能，但想让它这么做** | **提示词（prompt-only）**，并**在原文里写明它是嘱托不是门** | 「每轮产出一批新事实」（`agent_f/core.py` 的 `## 2` 段）；「读者四问」（`specs/g.py`）；「投稿级标准」（`specs/g.py`） |
| **两者都要** | 提示词给方向 ＋ 判据卡下限 | 「不许虚报 `proof_review`」：提示词教它"该升就升"，判据卡住无签名的写入 |

**第四种必须拒绝**：**判不了、却写成判据**。那种判据只有两种下场 —— 要么永远绿（假门，比没有更坏），要么大面积误伤（真门假判）。2026-10-19 实测过一例：给十条新产出标准做「义务句必须有能力锚点」的判据，按字面扫会误伤 **38/51 = 74.6%**（`A.policy[0]`「必须在结论里写明预算读数」这类正当条目会被点红）⇒ 该判据**未落地**，只保留人工核对的清单。

### §13.2 两条配套硬规矩

1. **没有负控的判据不算判据**。写完必须证明"把它弄坏，判据会红"。本仓已有血账：某条判据只断言下界（`>= 24`），于是"改了段、忘了动版本"在它下面**永远绿**（后由 `test_the_prompt_version_moves_with_the_sections` 两个方向都判补齐）。
2. **提示词里的每一条义务必须有能力锚点**：这条要求靠该角色的哪个动作/工具真能做到？做不到就不许写，或改写成"如实报告缺什么"（那才在能力面内）。2026-10-19 的十条产出标准逐条给了锚点，其中 D/F 的「每轮 ≥3 条新事实」被改写成「**有模型缝时**才要求，缝没接时如实报 `not_wired` / `dead_end(缺工具)`」—— 否则它就是许愿。

### §13.3 往提示词里写字之前，先看三件事

1. **这条要求判得了吗**？判得了就别只写在提示词里（模型可以忽略，判据不能）。
2. **这个角色做得到吗**？拿 `capabilities.CAPABILITIES[role]` 现读，核那个动作/工具的 `side_effect`、`returns` 能不能产出这条要求的东西。
3. **加了它，提示词变重了吗**？本仓十格合计 ≈ 31 万字符（M 一格 ≈ 5.1 万），且**每步都要带**；加之前先算它省不省、值不值（前缀缓存只在 system 逐字节稳定时才命中 —— 见 §13.4）。

### §13.4 与缓存的关系（为什么"稳定"也是判据）

上游 prompt 缓存按前缀命中计价；**system prompt 只要有一步变了，整段前缀的命中就没了**。所以：
- `promptstability.split_facts` 把每步会变的事实键（`budget_left` / `notebook`）移出 system，改由 user 消息承载；
- `promptstability.DYNAMIC_SECTION_WHITELIST` 是**允许在 system 里变**的段白名单（初始为空）；
- `_check_13` 之外，`prompt_cache` 读数（hit / miss / unknown / hit_rate / saved_usd）落进每步记录与 `agent_run_end`，上游不给读数时记 **unknown 而非 0**。

**结论**：往 system prompt 里塞"每步会变的东西"= 同时踩两条线（判据红 + 缓存失效）。这不是风格问题，是机器会算的账。

## [规范] §14 ⭐ 提示词缓存（落定十个角色 + 秘书，2026-10-21 真机读数）

**一句话**：本仓**没有**"写缓存"的开关 —— 上游（DeepSeek）的**服务端**前缀缓存是自动的，
唯一能控的是"前缀逐字节相同"；所以这一节的全部内容是：**读数在哪、实测命中了多少、
怎么再落一次**。

### §14.1 写缓存：没有开关，只有一个前提

全仓 grep `cache_control` 命中 **0 处**；六个模型档环境变量（真身
`src/agentflow/modelgw.py:163-168` 的 `ENV_KEY` / `ENV_BASE` / `ENV_NAME` /
`ENV_TIMEOUT` / `ENV_RETRIES` / `ENV_EFFORT`，值都是 `AGENTFLOW_MODEL_…`）
里**没有一个是缓存开关**。

请求体的唯一组装置是 `modelgw.ModelGateway._payload`（`src/agentflow/modelgw.py:739-764`）：
`model` / `messages`（system 一条 + user 一条）/ `temperature` / `stream` / 推理强度 /
`tools`。没有任何缓存注解可写 —— 上游自己为"没命中的那部分"建索引，下一次同前缀就命中。

⇒ **"把提示词写进缓存"= 把同一份前缀发一次。** 于是本节的"开关"实际上是三条：
① system 逐字节稳定（`promptstability.split_facts` + `DYNAMIC_SECTION_WHITELIST`，见 §13.4）；
② 请求形状与生产一致（同一个 `system` + 同一份工具面）；
③ 真的发过一次（这就是 `scripts/warm_prompt_cache.py` 干的事）。

### §14.2 读缓存：读数从哪来（逐跳给文件:行）

| 跳 | 落点 |
|---|---|
| 上游 `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | `modelgw.py:878-888` 读进 `ModelReply.cache_hit_tokens` / `cache_miss_tokens`（三态：`None` = 上游没给） |
| 一次调用的审计记录 | `llmseam.py:477-478` 转成 `SeamCall` 两格（`to_dict()` 也带，`llmseam.py:150-151`） |
| 每一步 | `promptstability.prompt_cache_record`（`promptstability.py:478` = `def` 所在行）⇒ `agent_step.prompt_cache`（`agent_loop.py:3785` / `:3876` / `:4176` 三处 `"prompt_cache": dict(step_cache)`） |
| 一趟的汇总 | `promptstability.summarize_prompt_cache`（`promptstability.py:556`）⇒ `LoopRun.prompt_cache`（`agent_loop.py:4275` 的 `run.prompt_cache = …`；字段声明在 `:997`、`to_dict()` 在 `:1178`） |
| 收工两个落点 | `agent_run_end`（`agent_loop.py:4345` 的 `SS.append(...)` 事件，`prompt_cache` 那一格在 `:4358`）与检查点 payload 的第 9 个键（`agent_loop.py:7115` 的 `"prompt_cache": dict(prompt_cache or {})`，判据 `promptstability.checkpoint_prompt_cache_problem`） |

**`write` 这一格是推导量，不是上游字段**：上游没有"写"计数，本仓把它定义为
`write = prompt_cache_miss_tokens`（`write_source="derived:miss"`）。它说的是
"这部分**被送去建索引**了"，**不是**"下一次一定能命中"。实证只有 `hit` 那一格 ——
秘书那一行就是两者分开的例子（见 §14.3 最后一行）。

### §14.3 实测读数（十个角色 + 秘书，`2026-10-21 05:31–05:41 +08:00`）

命令（`$env:PYTHONPATH='src'`，下同；2026-10-22 起两档各一趟，顺序固定：先关后开）：

```powershell
# ① Lean 关（产品缺省：不设 AGENTFLOW_LEAN_ENABLED）
python scripts/warm_prompt_cache.py --roles A,B,C,D,E,F,G,H,V,M,L,secretary `
  --hit-sample M,C --cap-usd 0.10
# ② Lean 开（同一份读数文件里落第二档）
python scripts/warm_prompt_cache.py --lean on `
  --roles A,B,C,D,E,F,G,H,V,M,L,secretary --hit-sample M,C,L --cap-usd 0.10
```

两档的读数落在同一个容器里，按 `lean_enabled` 区分；唯一装载入口是
`scripts/warm_prompt_cache.cache_readings(lean)`（`lean` 不给就现读
`leanscope.lean_on()`）：匹配不到这一档就返回 `tri="unknown"` 与
`reason="cache_missing_for_lean_state"`，**不回落到另一档**。L 在 Lean 关那一档
按产品规则不存在（`leanscope.LEAN_ONLY_ROLES`）：装载结果里它是
`state="absent"`（受控缺席），不是缺行。

读数落在 `tests/fixtures/prompt_cache_warm.json`（**一个容器，保留最近 16 趟**：
第一趟是"冷写"，后面每一趟都是"重落一次"；两趟都要留，因为
"写进去了"与"下次能命中"是两件事。2026-10-22 从 8 提到 16：要同时留两档，
而诊断读数（带 `tools_in_prefix` / `cross_run_hit` 的那几趟）本来就是更早跑出来的，
8 趟的窗口会被两趟新预热挤掉）。

| 角色 | system 字符 | 工具函数 | 冷写 `write`（第一趟 pass1，= miss） | 重落一次命中（最新趟 pass1） | 命中率 | 二调样本命中（pass2） | 跨 run 可复用前缀（字符） |
|---|---|---|---|---|---|---|---|
| A | 27,305 | 47 | 24,909 | 24,704 / 24,909 | 99.2% | — | 114 |
| B | 26,429 | 33 | 21,268 | 21,120 / 21,268 | 99.3% | — | 117 |
| C | 21,943 | 33 | 194（见下） | 18,432 / 18,626 | 99.0% | **18,432 / 18,626（99.0%）** | 117 |
| D | 31,907 | 52 | 26,571 | 26,368 / 26,571 | 99.2% | — | 118 |
| E | 27,291 | 36 | 22,164 | 22,016 / 22,164 | 99.3% | — | 139 |
| F | 28,421 | 47 | 24,645 | 24,448 / 24,645 | 99.2% | — | 114 |
| G | 36,759 | 48 | 30,177 | 29,952 / 30,177 | 99.2% | — | 119 |
| H | 36,360 | 41 | 28,171 | 28,032 / 28,171 | 99.5% | — | 112 |
| V | 23,068 | 25 | 18,190 | 18,048 / 18,190 | 99.2% | — | 145 |
| M | 50,671 | 31 | 35,203 | 35,069 / 35,203 | 99.6% | **35,069 / 35,203（99.6%）** | 116 |
| secretary | 0（没有 system） | 0 | 175 | **0 / 175** | **0.0%** | — | 307（稳定头） |

三行读数各自的一句话（**别把它们读成同一件事**）：

- **十个角色：前缀真的进了缓存。** 冷写那一趟每个都是"整份 prompt 全 miss"
  （`write` = 那一整行 token 数），下一趟同样的请求就变成 99%+ 命中 ——
  "命中"是这里唯一能证明"索引留下了它"的读数。
- **C 那一行的 `write=194`** 不是异常：它是在调通链路时被一条探针先预热过的
  （`--roles C --cap-usd 0.02`），所以主趟的第一发已经是命中。留痕，不回头改。
- **秘书那一行：当时没有落地。** 同一份 175 token 的提示词**连发两趟都是
  `hit=0 / miss=175`**（`python scripts/warm_prompt_cache.py --roles secretary
  --hit-sample secretary` ⇒ 退出码 1，"第二次调用没命中的样本：`['secretary']`"）。
  原因**不知道**（可能是太短、够不到上游的索引粒度；也可能是"只有 user 消息、
  没有 system 的请求不建索引"）—— 这一格记 unknown，不编。

> ⚠️ **上面那段的三条对今天的树已经不成立（2026-10-21 实测的三处更正，逐条带取法）**：
> ① **秘书的调用形状当天就改了**：`secretary.Secretary.judge` 现在把稳定头走 `system=`
> 通道 —— `secretary.py:1269-1271` 是 `self.seam.ask_json(_judge_material(context),
> system=_judge_system(kind), …)`，"`ask_json(prompt)` 没有 system 参数"这句**已过期**；
> 盘上的读数容器里秘书那一行的 `system_chars` 也**不再是 0**（取法：
> `python -c "import json;d=json.load(open('tests/fixtures/prompt_cache_warm.json',encoding='utf-8'));print([(r['role'],r.get('system_chars')) for r in d['runs'][-1]['rows']])"`
> ⇒ 秘书那一格 304）。**"改了形状 ⇒ 它一定命中"没有人复跑过** ⇒ 这一格仍是 unknown，
> **不许**把上面那行读数反着读成"秘书现在已落地"。
> ② **可复用前缀已不是 112–145 字符**（§14.6 那条"跨 run 命中"的更正讲的是同一件事）：
> 活账那几格已被挪出 system，读数容器里的 `cross_run_prefix_chars` 实测 `M 51,726–51,727` /
> `H 37,380–37,381`（取法：`python -c "import json;d=json.load(open('tests/fixtures/prompt_cache_warm.json',encoding='utf-8'));print([(r['role'],r['cross_run_prefix_chars']) for run in d['runs'] for r in (run.get('cross_run_hit') or [])])"`）。
> ③ **这张表的 `system 字符` / `write` 三栏是那一版提示词的读数**：`prompt_version` 现在
> 是 **p179**（`agent_prompts.PROMPT_VERSION`），盘上容器里最近 8 趟（`04:34–07:35Z`）
> 的 `system_chars` 已经是另一组（例：`A` 28,414 / `M` 51,727），本表那组（`A` 27,305 /
> `M` 50,671）是更早那一版。**本轮没有真发请求复跑**（那要花真钱）⇒ 表里三栏**不是当次值**，
> 要当次值就按 §14.5 重跑一遍。

**另外两条诊断读数**（同一趟，`--probe-*` 打出来的）：

| 问题 | 读数 | 那句话 |
|---|---|---|
| 工具面在不在缓存前缀里？ | 去掉工具面再发一次：`hit=11,904 / tokens_in=12,126`（98.2%） | **不在**。缓存按 `messages` 建索引，`tools` 不参与前缀 ⇒ 工具面省不进/废不掉缓存 |
| 换一趟活（不同 task / task_id / depth）还能命中多少？ | 第一次见：`hit=0 / 18,635`；同一份第二次见：`hit=18,432 / 18,635`（98.9%） | **第一次 0**。可复用前缀只有 112–145 字符（AGENT_IDENTITY 里带 `task_id` / `depth`，第 ~95 个字符起就不同），够不到一个缓存块 |

### §14.4 这条判据在哪、它怎么红

判据本体 = `tests/test_prompt_cache_warm.py`（9 条，逐条带负控；**不发请求、不联网**，
只读 §14.3 那份读数并重算十个角色的摘要）：

| 判据 | 正控 | 负控（必须红） |
|---|---|---|
| ① 每个目标都有缓存写记录（`write>0` 或 `hit>0`），逐角色打一行 | 11/11 | 删掉某个角色的行 ⇒ 点名它 |
| ①-b 十个角色的 prompt **被下一次命中过**（实证 `hit>0`） | 10/10；秘书 `landed=False` 但读数自洽 | 删掉一个已落地角色的行 ⇒ 不再判落地 |
| ② 第二次调用命中（样本只有 2 个：`M` / `C`） | `hit>0` 且 `hit/(hit+miss)>0` | 把样本那一行的 `hit` 改成 0 ⇒ 红 |
| ③ 同一角色两次调用的 `prompt_sha256` 相同 | 每一行都同摘要 + 两次独立渲染逐字节相同 | **把 `budget_left` 塞回 system**（改前那个形态）⇒ 红，并报出"从第几个字符起不同"与段名 `TASK_BUDGET` / `TASK_NOTEBOOK` |
| ④ 读数不许烂 | 盘上记的 `prompt_sha256` = 今天重算的 | 提示词一改（`agent_prompts.py` / `specs/*` / 预设）⇒ 红，处置是"重跑 §14.5 那条命令"，**不是**改测试 |
| ⑤ 两条诊断读数与本节一致 | 工具面不在前缀里 / 换一趟活第一次 0 命中 | 探针口径被改（例如 task_id 没变）⇒ 红 |

`③` 的负控是这一节最要紧的一条：它证明这条判据守的是**"提示词不许抖"**，
而不是"两边都不是空的"。§13.4 那条纪律（每步会变的东西不许进 system）就靠它咬人。

### §14.5 再落一次（两档两条命令）

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
# ① Lean 关（不设 AGENTFLOW_LEAN_ENABLED，产品缺省）
python scripts/warm_prompt_cache.py --roles A,B,C,D,E,F,G,H,V,M,L,secretary
# ② Lean 开（同一份读数文件里落第二档；顺序固定：先关后开）
python scripts/warm_prompt_cache.py --lean on `
  --roles A,B,C,D,E,F,G,H,V,M,L,secretary --hit-sample M,C,L
```

- **两档都要在**：`system_prompt` 在 Lean 开关两档下渲染出的不是同一段前缀，只落一档
  回答不了"开关有没有影响渲染"。判据 `tests/test_prompt_cache_warm.py` 逐档重算摘要，
  两档缺一档、或两档摘要相同，都会红。
- **装载侧**：`scripts/warm_prompt_cache.cache_readings(lean)` 是唯一入口；它按
  `lean_enabled` 选那一档最近一趟，逐 target 给 `measured` / `absent` / `missing`
  三态。匹配不到就 `unknown`（`cache_missing_for_lean_state`），不回落另一档。
- **L 在关档是缺席**：`leanscope.LEAN_ONLY_ROLES` 只有 `L`，Lean 关着时
  `system_prompt("L")` 按产品规则抛 `RoleHidden`。所以关档那一趟 L 记 `kind=absent`，
  不伪造一段预热；开档那一趟 L 真预热，并用 `--hit-sample M,C,L` 拿到第二次命中。

- **幂等**：同一 scenario 再跑一遍，`prompt_sha256` 不变、`hit` 接近满、`write` 接近 0
  （读数文件里多一趟，前一趟不动）。
- **自带花费上限**：`--cap-usd`（缺省 **0.10** 美元）既是 `LlmSeam(usd_budget=…)` 的真闸，
  也在每次发请求之前被预检一次 ⇒ 超了自停并说清"剩下的没预热"，不会跑超。
- **不联网抓文献、不跑研究**：每个目标只发一条"只回两个字 OK"的最小请求
  （推理强度缺省 `off` —— 它不进 `messages`，不改变缓存前缀，只省输出 token）。
- **`--dry-run`**：只渲染、打印摘要与字符数，**一个请求都不发**（花费 0）——
  改完提示词想先看"这一版有多大、摘要是什么"就用它。
- 本次落定的实际花费：**两趟留在读数文件里** —— 第一趟（冷写）**$0.035138** +
  重落一趟 **$0.004245** = **$0.039383**；另有调通链路与两条诊断的 5 次重跑
  （$0.011674）。**合计 $0.051057**，低于 0.10 的上限。

### §14.6 预热买到了什么、没买到什么（别把它读大）

- **买到了**：同一份前缀的**第二次**调用命中 99%+。这覆盖两件事 ——
  ① 同一趟的第 2..N 步（真机历史命中率 91–95% 就是它）；
  ② `--resume` / 重跑同一任务（`task` / `task_id` / `depth` 不变 ⇒ 是同一段前缀）。
- **没买到**：**下一趟不同的活**。实测第一次见那份 system 命中 **0** token
  （当时可复用前缀 112–145 字符 ≈ 50–65 token，够不到一个缓存块）。
  结构原因不是"预热没做对"，而是 `AGENT_IDENTITY` 段里带 `task_id` / `depth`，
  它在 system 的开头（第 ~95 个字符）—— 这一段一变，后面整条前缀作废。
- **改法已经做了，不是待批**（2026-10-21 实测）：那几格**已经从 system 挪进 user 消息** ——
  `promptstability.STEP_VOLATILE_FACTS` 现在含 `task` / `task_id` / `depth` /
  `parent_task_id` / `summoned_by` / `inbox` / `board` / `children` / `user_replies` /
  `workspace_root` / `availability` / `parent_limits`（复跑
  `python -c "import sys;sys.path.insert(0,'src');from agentflow import promptstability as P;print(sorted(P.STEP_VOLATILE_FACTS))"`）。
  可复用前缀也随之从一百多个字符变成数万（读数容器的 `cross_run_prefix_chars` 实测
  `M 51,726–51,727` / `H 37,380–37,381`；取法见 §14.3 那条更正的第 ② 条）。
  ⚠️ **"跨 run 第一次就命中"仍要真发请求才量得出来**，本轮没有复跑 ⇒ 那一格仍是 unknown。


## [规范] §15 ⭐ 优先级：读数让位于能力，最小改法让位于治本（2026-10-22 业主裁定）

> 业主原话：「读数重要还是能力重要？一时最小改法重要还是治本重要？」—— 本节是这两问的成文答案。
> 它不新增判据，改的是**做判断时的优先级**；每一轮改动都要按它自检。

### §15.1 两条不对称关系

```
① 能力是目的，读数是能力的证据。证据可以错，能力不会因为证据好看而存在。
   ⇒ 两者冲突时**读数让路**；让路的方式不是删读数，而是让读数重新对准能力。
② 最小改法只在"缺陷是局部的、语义已定"时成立；
   缺陷若是**被破坏的不变量**，最小改法只是把症状按下去，并留下"两套口径"。
```

判据式的一句话：**修完之后，若"同一条事实仍有两个来源、两个答案"，那就不是治本。**

### §15.2 四条硬性禁止（都是实际发生过、并被审计抓到的形态）

```
P-读数-1 不许把缺陷冻成"受保护期望值"。
         判据与不变量冲突时，**判据是缺陷**：同一次改动里改判据，并把"旧期望值错在哪"写进注释。
P-读数-2 不许"自己批准自己"：**冻结快照/基线不得与它要保护的声明改动在同一个提交里重冻**；
         重冻必须单独一个提交、且由人审。禁改区的批准台账只能由人写。
P-读数-3 不许写兼容垫片：凡"两处都能解释同一份数据"的实现（读侧按 sha 猜是哪一份、
         用 `x or DEFAULT` 兜住认不出的值、两边各放宽一点让相等），**视为缺陷本身**。
P-读数-4 不许用"最小改法"改语义：OR/AND、门锁/凭证、所有权与派生方向这类问题，
         必须一次改到不变量为止；中途允许树是红的、快照是脏的、文档数字是过期的。
```

### §15.3 治本优先时的作业顺序（照此执行）

```
1. 先写"不变量"的一句话陈述（例如"说签住了就必须真的签住了"）；
2. 找出**真身**：同一件事只有一个权威来源，其余必须**派生**、并在导入期断言等价；
3. 修实现到不变量为止；**允许**既有判据因语义纠正而红，逐条列出"原来断言什么、为什么现在错"；
4. 全部修完再做**唯一一次**"重算读数"：golden / 基线 / 文档数字 / 受保护期望值，
   单独一个提交、附逐格 diff、交人审；
5. 在这之前，任何"为了让树变绿"的临时放宽都不许进仓。
```

### §15.4 与 §13（提示词与判据的分工）的关系

§13 说的是"想让模型做的事写提示词、不许它做的事写判据"；
§15 说的是"**判据本身也不许冒充能力**"。两条合起来才是完整口径：
**提示词管方向，判据管下限，读数只是测出来的水位 —— 水位不是河。**

---

## [规范] §16 2026-10-27 新设计的十三个机制簇（收进规范）

> **为什么必须有这一节**：本批改动（`git diff b83362c~1..HEAD -- agentflow/src`）在 44 个文件里
> 新增了 **745** 条符号（func / const / class / tool / toolname，机器清单见 `agentflow/temp/_inventory_master.md`），
> 而在这之前**一条都没有进规范** —— 判据住在 `tests/` 里，可"这个设计该长什么样"只能靠读代码。
> 业主的判词是「新设计未被规范收录」：判据绿不等于规范在，**规范不在，下一个人就无法判断自己该照哪个口径改**。
>
> **本节怎么读**：745 条不是 745 个设计，而是 **13 个机制簇**（簇是按"一条规则能否把它们的共同点说完"切的，
> 不是按文件切的 —— 一个簇可以横跨五六个文件，一个文件也可以落在两个簇里）。每簇三格，缺一格判据就红：
>
> - **规则**：一句可执行的话。"要做得好"不是规则，"等待只有 `after_sec` 或 `wait_for` 两半，两个都给就受控拒绝"才是。
> - **落点**：符号名（**刻意不写行号**：本仓并行施工，行号几十分钟就漂；符号名由判据核存在性，比行号强）。
> - **判据**：哪个测试守它 + 哪些数字可以现算。"没法机器核"的条目在 §16.14 逐条写明指路，**不许写成数字**。
>
> **本节的判据本体**：`tests/test_new_designs_are_in_the_spec.py`。它做四件事：
> ① `§16.0` 的索引表与 `§16.1–§16.13` 的节必须一一对上（少一节 / 多一节都红）；
> ② 每簇**落点**里点名的 `file::symbol` 必须在盘上真的存在（改错一个字母就红）；
> ③ 每簇**判据**里点名的 `tests/x.py::test_...` 必须真的有那个用例；
> ④ **现算**格里写的每个数必须等于当次现算值（文档说 4 而代码是 5 ⇒ 红）。
> 两条反真空：把某个符号改错一个字母、把某个数改大 1，判据都必须红。
>
> **与旧口径的关系**：本节各条按 2026-10-27 的口径写。凡旧文字与新口径冲突的，**就地改成新口径并标日期**
> （本批改了 `ROLE-SPECS.md` §F.2 / §F.3 两处，见 §16.14）。本节**不改**任何功能代码、不动 golden / `PROMPT_VERSION`。

### [规范] §16.0 索引表：簇 → 段落 → 判据

> 这张表就是"新设计清单"。它按**机制簇**列，不按最初那 11 条列 —— 那 11 条只覆盖了其中三簇，
> 业主的判词是「远不止这些」。新增一簇要同时改三处：本表、§16.N 那一节、判据文件里那张现算表（若它有现算格）。

| 簇 | 名称 | 段落 | 判据文件 |
|---|---|---|---|
| C1 | 时钟族：九件工具、计时申请形状、程序计时器、挂机与交差 | §16.1 | `tests/test_timers_and_handoff_semantics.py`、`tests/test_clock_governs_all_timed_work.py`、`tests/test_clock_is_a_native_tool.py`、`tests/test_park_is_a_real_stop.py` |
| C2 | 三态与销号族：在飞 / 待机 / 静默 / 未读到，静默才可销号 | §16.2 | `tests/test_three_states_flying_standby_silent.py`、`tests/test_retire_only_for_the_silent.py`、`tests/test_child_count_and_active_cascade_retire.py`、`tests/test_retire_ready_is_a_reading_not_an_action.py`、`tests/test_information_items_are_acked_when_read.py` |
| C3 | 会话循环族：等谁、唤醒、收工门 | §16.3 | `tests/test_park_is_a_real_stop.py`、`tests/test_mailbox_delivers_mid_run_and_wakes_the_parent.py`、`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py` |
| C4 | 并发调度族：可抢占的派活与波次收口 | §16.4 | `tests/test_summon_is_preemptible.py`、`tests/test_delegation_may_reuse_an_active_child.py`、`tests/test_e13_concurrency.py` |
| C5 | 消息与板项族：绝对编号链、公告栏、ack 与落点 | §16.5 | `tests/test_guide_goes_down_the_secretary_chain.py`、`tests/test_the_public_channel_is_the_senders_children.py`、`tests/test_board_items_reach_the_prompt.py`、`tests/test_summons_and_numbered_addressing.py`、`tests/test_broadcast_reaches_my_children.py`、`tests/test_a_message_that_asks_for_work_becomes_a_work_item.py`、`tests/test_information_items_are_acked_when_read.py` |
| C6 | 依赖面族：手稿四列表 → 秘书洗稿 → D 携带 → B 读稿登记 | §16.6 | `tests/test_dependency_face_is_read_from_f_manuscript.py`、`tests/test_f_secretary_washes_dependencies.py`、`tests/test_dependency_wiring_is_live.py`、`tests/test_d_to_b_carried_road.py`、`tests/test_b_manuscript_must_be_framework_rendered.py`、`tests/test_d_carried_missing_reading.py` |
| C7 | 引用核实族：六档与挡签 | §16.7 | `tests/test_v_checks_fs_citations.py`、`tests/test_signing_never_lies.py`、`tests/test_quote_verification_leaves_evidence.py`、`tests/test_verify_quote_levels.py` |
| C8 | 命题同一性族：条件→结论一致、洗定理名、概念按定义项 | §16.8 | `tests/test_one_concept_is_one_row.py`、`tests/test_secretary_recognizes_the_same_proposition.py`、`tests/test_the_secretary_washes_internal_work_names.py`、`tests/test_one_theorem_many_proofs_is_not_three_theorems.py`、`tests/test_suspected_split_proposition.py` |
| C9 | 非平凡度族：按证明花的力气分 T0–T4 | §16.9 | `tests/test_nontriviality_is_judged_by_effort.py`、`tests/test_secretary_rates_nontriviality.py`、`tests/test_nontriviality_reading_is_read_only.py`、`tests/test_b_nontriviality_language_is_tiers.py` |
| C10 | 形式化入口族：只有用户指定 ⇒ M→B，`B→L` 唯一入边，F 不立 formal 子目标 | §16.10 | `tests/test_f_formal_subgoal_owner_l.py`、`tests/test_f_has_no_formal_entry.py`、`tests/test_f_reasoning_is_its_working_mode.py`、`tests/test_lean_switch_points_at_l.py` |
| C11 | 权限面与写口族：`statements` 只经 B、手填 ID 拒、通用写口只写簿记、保留产物 | §16.11 | `tests/test_statements_are_registered_by_b.py`、`tests/test_hand_filled_ids_are_refused.py`、`tests/test_universal_tools_are_for_everyone.py`、`tests/test_fs_reserved_framework_artifacts.py`、`tests/test_set_fields_are_normalized_on_write.py`、`tests/test_direct_write_is_routed_to_the_secretary.py`、`tests/test_tasks_write_port_refuses_forgeries.py`、`tests/test_a_concept_row_is_registered_by_the_secretary.py` |
| C12 | 读数与用户端族：名册三态读数、书目面、聊天行 ID、预热三态、错误两轴 | §16.12 | `tests/test_webui_three_state_reading.py`、`tests/test_webui_readers.py`、`tests/test_library_face_only_counts_admitted_works.py`、`tests/test_chat_lines_carry_the_absolute_id.py`、`tests/test_chat_page_shows_who_and_which_id.py`、`tests/test_cache_warm_button_is_honest.py`、`tests/test_the_root_is_named_m.py` |
| C13 | 清洁与判据基础设施族：死函数台账、绿灯不造假、仓库不更脏 | §16.13 | `tests/test_clean_invariant.py`、`tests/test_green_is_not_faked.py`、`tests/test_demo_selftest_leaves_the_repo_clean.py`、`tests/test_repo_survey_does_not_get_worse.py` |

### [规范] §16.1 C1 时钟族：九件工具、计时申请形状、程序计时器、挂机与交差

**规则**：全系统只有一处取时口与一本计时台账 —— 要等什么只能写成 `after_sec`（等时间）或 `wait_for`（等谁：名册名 / 绝对编号 / `task:<号>` / `agent:<名>`）两半之一（两半都给、或一个都不给 ⇒ 受控拒绝），目的缺了照常受理但读数标 `purpose_missing` 并在到点消息里追问，到点那条消息必须同时带**目的 + 现场时长 + 时间到**（唯一拼法 `clock.due_message`），程序在跑就自动有一条 `kind="program"` 计时器、计时器**不阻塞**动作、无事可做才 `clock.wait_any`、真挂机是"挂在时钟上"（零步零调用）、无事可做且一条计时器都没有就是**交差**。

- 补充：目的有四个来源（`clock.PURPOSE_SOURCES`）：显式给的（`given`）、从被等对象的 task 抄的（`target_task`）、程序计时器按程序名自动填的（`program`）、三路都拿不到的（`unavailable`，此时 `purpose_missing` 为真）。四档都要真的落进 `Timer.to_dict` 的 `purpose_source` —— 只活在读数里的话，"为什么这一条没目的"在盘上就退化成一句空串（2026-10-27 口径）。
- 补充：九件是 `clock.now` / `timer_start` / `timer_list` / `timer_cancel` / `alarm_start` / `periodic_start` / `periodic_stop` / `timer_purpose` / `wait_any`；它们十一个角色全体都有（`tools.UNIVERSAL_TOOLS` 里登记，不经只读角色的例外表）。
- 补充：老的、不依赖时钟的计时入口一律退场，写出旧名字得到的是指路而不是"未注册的工具"（`clock.RETIRED_TIMING_TOOLS` + `clock.retire_hint`）。
- 补充："主时钟控制了所有计时类工作"这句话是机器判据不是声明：`clock.raw_wait_census` 用 AST 点出没走 `await_io` / `note_wait` 的原始等待，`clock.program_census` 点出"起进程却没进程序计时器"的地方；两者读不成都是 `checked=false`，不许折成 0 处。
- **落点**：`src/agentflow/clock.py::TIMER_KINDS`、`src/agentflow/clock.py::PROGRAM_OUTCOMES`、`src/agentflow/clock.py::PURPOSE_SOURCES`、`src/agentflow/clock.py::PARK_STATES`、`src/agentflow/clock.py::due_message`、`src/agentflow/clock.py::program_span`、`src/agentflow/clock.py::finish_program`、`src/agentflow/clock.py::record_handoff`、`src/agentflow/clock.py::read_handoffs`、`src/agentflow/clock.py::request_wait_any`、`src/agentflow/clock.py::wait_any_reading`、`src/agentflow/clock.py::raw_wait_census`、`src/agentflow/clock.py::program_census`、`src/agentflow/clock.py::await_io`、`src/agentflow/clock.py::note_wait`、`src/agentflow/clock.py::RETIRED_TIMING_TOOLS`、`src/agentflow/tools/clock_tools.py::clock_timer_start`、`src/agentflow/tools/clock_tools.py::clock_periodic_start`、`src/agentflow/tools/clock_tools.py::clock_timer_purpose`、`src/agentflow/tools/clock_tools.py::clock_wait_any`、`src/agentflow/tools/clock_tools.py::clock_now`、`src/agentflow/tools/__init__.py::UNIVERSAL_TOOLS`、`src/agentflow/autonomy.py::_pump_and_read_clock`、`src/agentflow/agent_e/core.py::_note_process_wait`、`src/agentflow/cancellation.py::_note_process_wait`、`src/agentflow/fetch.py::_default_sleep`、`src/agentflow/modelgw.py::_default_sleep`、`src/agentflow/jobobject.py::_grace_wait`
- **判据**：`tests/test_timers_and_handoff_semantics.py::test_b_the_purpose_is_filled_from_the_target_task`、`tests/test_timers_and_handoff_semantics.py::test_a_a_program_that_runs_is_on_the_clock_while_it_runs`、`tests/test_timers_and_handoff_semantics.py::test_c_a_timer_does_not_block_work_in_hand`、`tests/test_timers_and_handoff_semantics.py::test_c3_wait_any_wakes_when_any_timer_returns`、`tests/test_timers_and_handoff_semantics.py::test_d_nothing_to_do_and_no_timer_is_a_handoff`、`tests/test_clock_governs_all_timed_work.py::test_g_due_message_has_all_three_parts`、`tests/test_clock_governs_all_timed_work.py::test_l_readonly_roles_get_all_nine_clock_tools`、`tests/test_clock_governs_all_timed_work.py::test_e_waits_outside_clock_is_zero_and_a_raw_sleep_turns_it_red`；现算：`clock.TIMER_KINDS` = 4、`clock.PROGRAM_OUTCOMES` = 4、`clock.PURPOSE_SOURCES` = 4、`clock.PARK_STATES` = 3、`tools.UNIVERSAL_TOOLS[clock.*]` = 9

### [规范] §16.2 C2 三态与销号族：在飞 / 待机 / 静默 / 未读到，静默才可销号

**规则**：一个子代理只有四个状态词 —— `flying`（在飞）/ `standby`（待机：有活没在跑，名下有计时器）/ `silent`（静默：无工作 ∧ 无计时器）/ `unknown`（未读到，**不许折成静默**），`active` 只等于"非静默"、`active_child_count` 就是非静默数；销号只可针对**静默**，在飞 / 待机 / 读不到一律 `target_not_silent` 并给逐条 `blocking`（"待机"要列出那几个计时器），而"有活跃子代理 ⇒ 必有一个等它的计时器"是让 `silent` 定义良好的那条不变量（由父派活时自动起表保证、由 `conductor.child_wait_invariant` 判定）。

- **落点**：`src/agentflow/conductor.py::AGENT_STATES`、`src/agentflow/conductor.py::ACTIVE_AGENT_STATES`、`src/agentflow/conductor.py::agent_state`、`src/agentflow/conductor.py::agent_states`、`src/agentflow/conductor.py::retire_state_of`、`src/agentflow/conductor.py::retire_blocking`、`src/agentflow/conductor.py::retire_refusal`、`src/agentflow/conductor.py::retire_integrity`、`src/agentflow/conductor.py::retire_ready`、`src/agentflow/conductor.py::child_wait_invariant`、`src/agentflow/conductor.py::arm_child_waiter`、`src/agentflow/conductor.py::RETIRE_REFUSAL_TARGET_NOT_SILENT`、`src/agentflow/conductor.py::clock_waiters`、`src/agentflow/tools/conductor_tools.py::conductor_retire_child`、`src/agentflow/tools/conductor_tools.py::RETIRE_CHILD_STATES`、`src/agentflow/secretary.py::retire`、`src/agentflow/readouts.py::roster_readout`
- **判据**：`tests/test_three_states_flying_standby_silent.py::test_d_a_finished_agent_without_timers_reads_silent`、`tests/test_three_states_flying_standby_silent.py::test_g_an_unreadable_clock_is_unknown_not_silent`、`tests/test_three_states_flying_standby_silent.py::test_the_four_state_words_are_one_vocabulary`、`tests/test_retire_only_for_the_silent.py::test_b_a_flying_child_is_refused_by_the_silent_gate`、`tests/test_retire_only_for_the_silent.py::test_d_an_unreadable_clock_is_refused_fail_closed`、`tests/test_retire_only_for_the_silent.py::test_f_stubbing_the_state_judgement_makes_b_c_d_red`、`tests/test_child_count_and_active_cascade_retire.py::test_a_two_counts_are_named_and_counted_separately`、`tests/test_information_items_are_acked_when_read.py::test_c_a_child_with_only_wake_notices_can_be_retired`、`tests/test_information_items_are_acked_when_read.py::test_c2_a_child_with_an_unacked_verdict_is_still_refused`、`tests/test_timers_and_handoff_semantics.py::test_e_every_active_child_has_a_waiter`；现算：`conductor.AGENT_STATES` = 4、`conductor.ACTIVE_AGENT_STATES` = 2、`conductor.RETIRE_REFUSAL_TARGET_NOT_SILENT` = target_not_silent

### [规范] §16.3 C3 会话循环族：等谁、唤醒、收工门

**规则**：等待是循环的一个分支而不是一次轮询 —— 挂机期间这一趟**零步零模型调用**（判据数 `agent_step` 事件），唤醒只由"计时器到点 / 被等的对象真说了话 / 子代理全部回来"这三种事实触发（读不到唤醒就明说读不到，不许猜），而收工门（`final`）在整棵树还有未销号节点时**拒绝落账**，且这一条对"被唤醒的那一趟"不给豁免。

- 补充：唤醒是两份落盘一起给的 —— 一条可审计的板项 + 一条可读的唤醒标记（`clock.record_wake` 是唯一的标记落点）。
- **落点**：`src/agentflow/agent_loop.py::_park_gate`、`src/agentflow/agent_loop.py::_park_slice`、`src/agentflow/agent_loop.py::_wait_any_reading`、`src/agentflow/agent_loop.py::_wake_pending`、`src/agentflow/agent_loop.py::_final_gate_reading`、`src/agentflow/agent_loop.py::_settle_children_at_exit`、`src/agentflow/agent_loop.py::_children_round_trip`、`src/agentflow/agent_loop.py::_take_child_results`、`src/agentflow/agent_loop.py::_do_handoff`、`src/agentflow/agent_loop.py::MONITOR_TURN_SHAPES`、`src/agentflow/agent_loop.py::MONITOR_TURN_TOOLS`、`src/agentflow/agent_loop.py::PARK_EVENT`、`src/agentflow/agent_loop.py::_pending_work`、`src/agentflow/secretary.py::deliver_local`
- **判据**：`tests/test_park_is_a_real_stop.py::test_a_parked_parent_takes_no_model_calls_and_no_steps`、`tests/test_park_is_a_real_stop.py::test_a_wake_that_ends_the_park_costs_no_model_call`、`tests/test_park_is_a_real_stop.py::test_the_park_branch_is_load_bearing`、`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py::test_a_final_with_an_unretired_node_is_not_recorded`、`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py::test_a_woken_turn_gets_no_exemption_from_the_gate`、`tests/test_mailbox_delivers_mid_run_and_wakes_the_parent.py::test_the_monitor_turn_only_lets_watch_guide_supplement_and_close`；现算：`agent_loop.MONITOR_TURN_SHAPES` = 5、`agent_loop.MONITOR_TURN_TOOLS` = 2、`agent_loop.PARK_EVENT` = agent_park

### [规范] §16.4 C4 并发调度族：可抢占的派活与波次收口

**规则**：一批派活一次发出、按写集分波并发跑，父代理在子代理还在跑的时候**也拿到回合**（单条 `summon` 与 `summon_many` 返回的是同一个句柄形状，折叠回来的结果与阻塞式那一趟等价），并且"一次派活"的每一个可结算结果都只由句柄交回一次（`take_settled` 拿走的不再回来）—— 抢占是循环的形态，不是给某个角色开的特权。

- 补充："同一角色在跑、且这条派活与它手上那件不冲突" ⇒ 允许复用那个在跑的实例，而不是并排再开一个。
- **落点**：`src/agentflow/scheduler.py::CallTicket`、`src/agentflow/scheduler.py::WaveHandle`、`src/agentflow/scheduler.py::start_waves`、`src/agentflow/scheduler.py::take_settled`、`src/agentflow/scheduler.py::wait_any`、`src/agentflow/conductor.py::summon_begin`、`src/agentflow/conductor.py::start_summon`、`src/agentflow/conductor.py::summon_preemptible`、`src/agentflow/conductor.py::SummonHandle`、`src/agentflow/conductor.py::SummonStart`、`src/agentflow/conductor.py::open_handle`、`src/agentflow/agent_loop.py::PREEMPTIBLE_DISPATCH`、`src/agentflow/tools/conductor_tools.py::conductor_summon_many`
- **判据**：`tests/test_summon_is_preemptible.py::test_the_parent_gets_a_turn_while_three_long_children_are_still_running`、`tests/test_summon_is_preemptible.py::test_without_preemption_the_first_two_criteria_go_red`、`tests/test_summon_is_preemptible.py::test_the_single_summon_returns_a_handle_and_folds_back_like_a_batch`、`tests/test_delegation_may_reuse_an_active_child.py`、`tests/test_e13_concurrency.py`；现算：`agent_loop.PREEMPTIBLE_DISPATCH` = True

### [规范] §16.5 C5 消息与板项族：绝对编号链、公告栏、ack 与落点

**规则**：三件事各有**唯一落点**，不许互相代替 —— ① 姓名/编号只经名册解析（"按角色名发给一个不在自己名册里的人"是受控拒绝，不是就近投递）；② 跨层的指导沿**绝对编号链**逐跳由秘书转发、**正文只到链尾**（中间几跳不读正文，收据带逐跳时刻）；③ `ALL` 是**公告栏**不是对话（可见面 = 发信人的直接子代理，公告里点名又带指令语气 ⇒ 受控拒绝 `public_is_not_a_conversation`，一步一发都不落盘）。而"板上挂着一项"就是一条消息的落点：开项只有 `conductor.open_item` 一个口，`kind ∈ ("delegation","message","report","notice")`、`expects ∈ ("ack","work")`，**信息型（notice / message）读到即收口**（`seen` 就是 ack，`_settle_if_informational` 三条件缺一条就不动它）；**收到"要求做事"的消息时，收件人自己落一条 `kind="delegation"` + `expects="work"` 的板项**（`conductor.post_task`：收件人只能是调用者自己、`key` 是幂等键、四态 `posted` / `existing` / `refused` / `unknown`），办完用 `conductor.ack` 的 `close="completed"` 收口 —— 于是"这条消息要办的事"从一句会被读丢的话变成板上一条可追踪、销号门也看得见的活项（业主 2026-10-27 逐字：「如果 message 是要求做事，智能体需自己写任务塞进 task_board」）。

- 补充：`CLOSED_ITEM_STATES`（`done` / `block`）是时钟与销号两边共用的"这一项已经收口"读数。
- 补充：`conductor.post_task` 是 2026-10-27 晚进册的那一件（工具总数因此 111 → 112，读数重算见 §16.14 第五节）；它与 `table.create(table="tasks")` 那条野路的关系是"正路 vs 被堵住的旁路"（`_tasks_write_refusal` 只许给自己落项、不许伪造收口或已读）。
- **落点**：`src/agentflow/conductor.py::absolute_chain`、`src/agentflow/conductor.py::chain_of`、`src/agentflow/conductor.py::chain_text`、`src/agentflow/conductor.py::parse_chain_address`、`src/agentflow/conductor.py::resolve_chain`、`src/agentflow/conductor.py::CHAIN_SEPARATOR`、`src/agentflow/conductor.py::CHAIN_MAX_HOPS`、`src/agentflow/conductor.py::CHAIN_HOP_ROSTER`、`src/agentflow/conductor.py::CHAIN_DELIVERY_STATES`、`src/agentflow/conductor.py::CHAIN_REFUSAL_REASONS`、`src/agentflow/conductor.py::open_item`、`src/agentflow/conductor.py::mark_item_seen`、`src/agentflow/conductor.py::_settle_if_informational`、`src/agentflow/conductor.py::INFORMATIONAL_ITEM_KINDS`、`src/agentflow/conductor.py::ACK_REQUIRED_ITEM_PREFIXES`、`src/agentflow/conductor.py::ack_items`、`src/agentflow/schema.py::ITEM_KINDS`、`src/agentflow/schema.py::ITEM_EXPECTS`、`src/agentflow/schema.py::ITEM_STATES`、`src/agentflow/schema.py::ITEM_CLOSES`、`src/agentflow/tools/conductor_tools.py::conductor_guide`、`src/agentflow/tools/conductor_tools.py::conductor_ack`、`src/agentflow/tools/conductor_tools.py::ACK_STATES`、`src/agentflow/tools/conductor_tools.py::conductor_escalate`、`src/agentflow/tools/conductor_tools.py::conductor_post_task`、`src/agentflow/tools/conductor_tools.py::POST_TASK_STATES`、`src/agentflow/tools/clock_tools.py::CLOSED_ITEM_STATES`、`src/agentflow/secretary.py::relay_in`、`src/agentflow/secretary.py::relay_out`、`src/agentflow/secretary.py::relay_path`、`src/agentflow/secretary.py::RELAY_LEDGER`、`src/agentflow/agent_prompts.py::collab_board_text`
- **判据**：`tests/test_a_message_that_asks_for_work_becomes_a_work_item.py::test_a_a_message_that_asks_for_work_becomes_a_work_item`、`tests/test_a_message_that_asks_for_work_becomes_a_work_item.py::test_c_the_hand_only_posts_to_itself`、`tests/test_a_message_that_asks_for_work_becomes_a_work_item.py::test_d_stubbing_the_post_makes_a_red`、`tests/test_information_items_are_acked_when_read.py::test_a_a_clock_wake_notice_is_closed_on_the_tick_it_is_rendered`、`tests/test_information_items_are_acked_when_read.py::test_b_a_work_item_is_not_acked_by_being_read`、`tests/test_information_items_are_acked_when_read.py::test_a3_a_notice_that_was_never_rendered_stays_queued`、`tests/test_guide_goes_down_the_secretary_chain.py::test_a_the_guide_walks_the_secretary_chain_and_only_the_tail_reads_it`、`tests/test_guide_goes_down_the_secretary_chain.py::test_f_leaking_the_body_to_every_hop_makes_a_red`、`tests/test_guide_goes_down_the_secretary_chain.py::test_e_the_patrol_tools_report_the_absolute_chain_for_every_node`、`tests/test_the_public_channel_is_the_senders_children.py::test_public_visibility_reads_the_sender_instance`、`tests/test_the_public_channel_is_the_senders_children.py::test_a_public_message_without_a_task_id_is_refused_with_nothing_written`、`tests/test_board_items_reach_the_prompt.py::test_a_board_item_reaches_the_prompt_and_is_marked_seen`、`tests/test_board_items_reach_the_prompt.py::test_another_instances_items_never_enter_my_prompt`、`tests/test_summons_and_numbered_addressing.py::test_a_roster_name_addresses_the_role_inbox`、`tests/test_broadcast_reaches_my_children.py::test_broadcast_opens_one_ack_item_per_child`、`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py::test_the_hand_does_not_need_a_seen_first`；现算：`schema.ITEM_KINDS` = 4、`schema.ITEM_EXPECTS` = 2、`schema.ITEM_STATES` = 5、`conductor.CHAIN_DELIVERY_STATES` = 3、`conductor.CHAIN_MAX_HOPS` = 64、`conductor_tools.POST_TASK_STATES` = 4

### [规范] §16.6 C6 依赖面族：手稿四列表 → 秘书洗稿 → D 携带 → B 读稿登记

**规则**：一条依赖边的唯一来源是**证明手稿末尾那一节 `## 依赖` 的四列表**（列 `quote` / `stmt_id` / `step` / `path_group`：引文、命题号、第几步、路径组），走的是**同一条链**：F 写手稿 → 秘书洗稿（缺那一节就补空的、有引用的核号、洗不干净就打回，洗过才盖 `wash` 标记）→ D 携带（正文按 sha256 交出去）→ B 读稿登记（四态来源 `param` / `carried` / `disk` / `none`；读不到就明说读不到，不许当"没有依赖"）—— 并且**能进依赖列的引用只有 `proof_review` 级及以上**（低于它 ⇒ 受控拒绝，不是降级采信）。

- 补充：手写的证明手稿与研究报告都被框架产物表挡下（保留产物不许智能体自己写盘），"洗过"是文件上的标记而不是一句声明。
- **落点**：`src/agentflow/depsection.py::COLUMN_KEYS`、`src/agentflow/depsection.py::SECTION_HEADING`、`src/agentflow/depsection.py::SECTION_PROOF`、`src/agentflow/depsection.py::CITATION_LEVELS`、`src/agentflow/depsection.py::CITATION_MIN_LEVEL`、`src/agentflow/depsection.py::SOURCE_PARAM`、`src/agentflow/depsection.py::SOURCE_CARRIED`、`src/agentflow/depsection.py::SOURCE_DISK`、`src/agentflow/depsection.py::SOURCE_NONE`、`src/agentflow/depsection.py::parse_dependency_section`、`src/agentflow/depsection.py::render_dependency_section`、`src/agentflow/depsection.py::wash_dependency_section`、`src/agentflow/depsection.py::manuscript_wash_reading`、`src/agentflow/depsection.py::mark_washed`、`src/agentflow/depsection.py::read_manuscript`、`src/agentflow/depsection.py::manuscript_relpath`、`src/agentflow/agent_f/manuscript.py::proof_manuscript`、`src/agentflow/agent_f/manuscript.py::publish_manuscript`、`src/agentflow/agent_f/manuscript.py::render_dependency_section`、`src/agentflow/agent_f/manuscript.py::dependency_rows`、`src/agentflow/agent_f/manuscript.py::citable_statements`、`src/agentflow/agent_f/manuscript.py::manuscript_path`、`src/agentflow/agent_b/register_statement.py::_receive_carried_manuscript`、`src/agentflow/agent_b/register_statement.py::_deps_reading`、`src/agentflow/agent_b/register_statement.py::_manuscript_deps_after_write`、`src/agentflow/agent_d/write_report.py::_carried_manuscripts`、`src/agentflow/agent_d/write_report.py::_carried_missing_reading`、`src/agentflow/agent_d/write_report.py::_deliver_carried_to_b`、`src/agentflow/secretary.py::record_manuscript_dependency_face`、`src/agentflow/secretary.py::wash_dependency_face`、`src/agentflow/secretary.py::record_proof_deps`、`src/agentflow/secretary.py::DEPS_MISSING_STATES`、`src/agentflow/refusals.py::EMPTY_PROOF_TEXT`、`src/agentflow/tools/fs_tools.py::RESERVED_ARTIFACT_KIND`
- **判据**：`tests/test_dependency_face_is_read_from_f_manuscript.py::test_f_manuscript_section_is_read_by_b_and_lands_a_dependency`、`tests/test_dependency_face_is_read_from_f_manuscript.py::test_three_paths_in_one_manuscript_make_three_dependency_rows`、`tests/test_dependency_face_is_read_from_f_manuscript.py::test_a_broken_row_is_refused_with_the_line_and_the_missing_column`、`tests/test_f_secretary_washes_dependencies.py::test_the_wash_happens_before_the_outlet_and_marks_the_manuscript`、`tests/test_f_secretary_washes_dependencies.py::test_a_below_proof_review_source_is_caught_here_not_at_b`、`tests/test_dependency_wiring_is_live.py::test_the_whole_chain_f_write_d_carry_b_read_v_sign`、`tests/test_d_to_b_carried_road.py::test_the_washed_flag_travels_with_the_file`、`tests/test_d_carried_missing_reading.py::test_a_missing_carried_sheet_is_a_reading_not_a_silence`、`tests/test_b_manuscript_must_be_framework_rendered.py::test_a_handwritten_manuscript_is_refused_by_name`；现算：`depsection.COLUMN_KEYS` = 4、`depsection.CITATION_LEVELS` = 2、`depsection.CITATION_MIN_LEVEL` = proof_review、`secretary.DEPS_MISSING_STATES` = 3

### [规范] §16.7 C7 引用核实族：六档与挡签

**规则**：一条引用被核成六档之一 —— `consistent` / `weaker` / `stronger` / `unrelated` / `inadmissible` / `unknown`，**可签的只有 {`consistent`, `weaker`}**（另外四档一律挡签，`unknown` 不是"待定"而是"没核成，不许签"）；核实**不要求逐字**（业主：「正常写证明就是不会逐字的」——同一句话换个写法仍可 `consistent`），但"把弱证据当强证据用"必须落 `stronger`、跨证据等级取材必须落 `inadmissible`。

- 补充：六档是**证据面的判据**，不是措辞判据：行里还留着摘要（`CITATION_DIGEST_CHARS`）与证据地板（`CITATION_EVIDENCE_FLOOR`），挡签的理由必须能指到档位。
- 补充：`quote_verified` 的逐字回验仍然存在，但它是 B 那一侧的第一道自动幻觉防线；"逐字不中"不等于"引用不成立"，语义那一档由六档判。
- **落点**：`src/agentflow/verifications.py::CITATION_VERDICTS`、`src/agentflow/verifications.py::CITATION_SIGNABLE`、`src/agentflow/verifications.py::CITATION_BLOCKING`、`src/agentflow/verifications.py::CITATION_CHECK_KEYS`、`src/agentflow/verifications.py::CITATION_EVIDENCE_FLOOR`、`src/agentflow/verifications.py::CITATION_DIGEST_CHARS`、`src/agentflow/verifications.py::citation_gate`、`src/agentflow/verifications.py::apply_citation_gate`、`src/agentflow/verifications.py::citation_blocks`、`src/agentflow/verifications.py::signing_gate_problem`、`src/agentflow/verifications.py::admissible_evidence_kinds`、`src/agentflow/verifications.py::evidence_kind_admissible`、`src/agentflow/verifications.py::dep_note`、`src/agentflow/verifications.py::DEP_NOTE_KEYS`、`src/agentflow/agent_v/core.py::_citation_admissibility`、`src/agentflow/agent_v/core.py::_citation_checks`、`src/agentflow/agent_v/core.py::_citation_material`、`src/agentflow/agent_h/_support.py::h_free_toolbox_accepts`
- **判据**：`tests/test_v_checks_fs_citations.py::test_a_consistent_use_signs_even_though_the_words_differ`、`tests/test_v_checks_fs_citations.py::test_a_verbatim_quote_used_more_strongly_cannot_sign`、`tests/test_v_checks_fs_citations.py::test_a_cross_check_citation_is_inadmissible_and_cannot_sign`、`tests/test_v_checks_fs_citations.py::test_an_unknown_citation_lands_as_undetermined_and_does_not_sign`、`tests/test_v_checks_fs_citations.py::test_signs_bit3_refuses_a_row_whose_citation_check_blocks`、`tests/test_v_checks_fs_citations.py::test_the_allowed_level_set_is_computed_from_the_shared_evidence_order`、`tests/test_signing_never_lies.py::test_unsigned_is_a_checked_conclusion_not_an_unchecked_ledger`、`tests/test_quote_verification_leaves_evidence.py::test_a_quote_that_is_not_on_that_page_is_false_with_a_named_reason`；现算：`verifications.CITATION_VERDICTS` = 6、`verifications.CITATION_SIGNABLE` = 2、`verifications.CITATION_BLOCKING` = 4、`verifications.CITATION_CHECK_KEYS` = 4

### [规范] §16.8 C8 命题同一性族：条件→结论一致、洗定理名、概念按定义项

**规则**：两条命题是不是同一条，按"**条件 → 结论 一致**"判（不是按字面、也不是按编号），记不住就落 `unknown`、**`unknown` 永不合并**；落库前秘书要把定理名洗成人话（内部工作名如「F 攻坚 000000 子目标 s1」一律洗掉，洗不出就退回而不是留空）；概念行同一性按**定义项**判（同一被定义项换了标签仍是一条概念）；而"这条定理走哪条路证出来的"属于**证明层**，不进命题名。

- 补充：三条落点都在秘书那一侧 —— 判定、合并、洗名，各有一处；判定要过一次模型（`test_the_same_text_twice_costs_one_call` 数的是这一次），洗名**不花模型钱**（规则表 + 截断）。
- **落点**：`src/agentflow/propositionkey.py::same_concept`、`src/agentflow/propositionkey.py::candidates_for`、`src/agentflow/propositionkey.py::concept_keys`、`src/agentflow/propositionkey.py::defined_term`、`src/agentflow/propositionkey.py::concept_similarity`、`src/agentflow/propositionkey.py::BASIS_CONCEPT_TERM`、`src/agentflow/propositionkey.py::BASIS_CONCEPT_LABEL`、`src/agentflow/propositionkey.py::CONCEPT_GENERIC_TERMS`、`src/agentflow/secretary.py::wash_working_name`、`src/agentflow/secretary.py::_strip_working_names`、`src/agentflow/secretary.py::_same_concept_candidate`、`src/agentflow/secretary.py::_merge_into_concept`、`src/agentflow/secretary.py::adjudicate_proposition`、`src/agentflow/secretary.py::append_proposition_verdict`、`src/agentflow/secretary.py::proposition_verdicts_path`、`src/agentflow/secretary.py::PROPOSITION_VERDICTS`、`src/agentflow/secretary.py::CONCEPT_IDENTITY_KINDS`
- **判据**：`tests/test_secretary_recognizes_the_same_proposition.py::test_two_phrasings_of_one_proposition_become_one_row_with_proof_two`、`tests/test_secretary_recognizes_the_same_proposition.py::test_unjudgeable_texts_are_unknown_and_never_merged`、`tests/test_secretary_adjudication_is_wired.py::test_a_wired_secretary_really_issues_one_proposition_identity_call`、`tests/test_one_concept_is_one_row.py::test_a2_the_same_defined_term_under_another_label_is_one_concept`、`tests/test_one_concept_is_one_row.py::test_c_stubbing_the_criterion_to_different_turns_a_red`、`tests/test_the_secretary_washes_internal_work_names.py::test_a_the_real_mp3_work_name_never_becomes_the_theorem_name`、`tests/test_the_secretary_washes_internal_work_names.py::test_b_legitimate_theorem_names_are_not_touched_at_all`、`tests/test_one_theorem_many_proofs_is_not_three_theorems.py::test_a_the_route_leaves_the_label_and_lands_on_the_proof`、`tests/test_suspected_split_proposition.py::test_too_short_texts_are_unknown_and_never_folded_into_different`；现算：`secretary.PROPOSITION_VERDICTS` = 3、`secretary.CONCEPT_IDENTITY_KINDS` = 1、`propositionkey.BASIS_CONCEPT_TERM` = concept_defined_term

### [规范] §16.9 C9 非平凡度族：按证明花的力气分 T0–T4

**规则**：一条命题的非平凡度分五档 `T0`–`T4`，判据是**证明花了多少力气**（体量 / 步骤数 / 引理数 / 用到几个工具簇 / 有没有绕路），不是"值不值得做"那两个旧问题 —— 旧的两问**不再作判据**（判据文件里有一条专测它）；读数与判定分开：`proof_effort_readings` 只读，`nontriviality_from_effort` 把读数折成档，判不出就写 `unknown` 而不退回 `T1`。

- 补充：档位边界住在 `EFFORT_TIER_BANDS`（五档，`(下限, 上限, 档名)` 三元组），工具簇跨度住在 `EFFORT_TOOL_CLUSTERS`，"绕路"靠步号不连续（`_step_numbers` 那张表在依赖面那一侧）看出来。
- **落点**：`src/agentflow/secretary.py::EFFORT_TIER_BANDS`、`src/agentflow/secretary.py::EFFORT_TOOL_CLUSTERS`、`src/agentflow/secretary.py::nontriviality_from_effort`、`src/agentflow/secretary.py::proof_effort_readings`、`src/agentflow/secretary.py::effort_tier_label`、`src/agentflow/secretary.py::PROOF_BODY_CAP`、`src/agentflow/refusals.py::EMPTY_STATEMENT_TEXT`、`src/agentflow/depsection.py::proof_steps`、`src/agentflow/depsection.py::proof_body`
- **判据**：`tests/test_nontriviality_is_judged_by_effort.py::test_c_a_big_proof_with_many_lemmas_and_two_clusters_is_t2_or_above`、`tests/test_nontriviality_is_judged_by_effort.py::test_d_a_three_line_proof_that_only_uses_definitions_stays_t0`、`tests/test_nontriviality_is_judged_by_effort.py::test_e_the_two_old_questions_are_not_criteria`、`tests/test_nontriviality_is_judged_by_effort.py::test_f_zeroed_effort_readings_break_the_big_proof_case`、`tests/test_secretary_rates_nontriviality.py::test_the_five_levels_are_declared_with_the_owner_semantics`、`tests/test_secretary_rates_nontriviality.py::test_unknown_is_not_a_tier`、`tests/test_nontriviality_reading_is_read_only.py::test_counts_keep_unjudged_apart_from_t1`、`tests/test_b_nontriviality_language_is_tiers.py::test_b_source_has_no_trivial_wording_outside_history_comments`；现算：`secretary.EFFORT_TIER_BANDS` = 5、`secretary.EFFORT_TOOL_CLUSTERS` = 8

### [规范] §16.10 C10 形式化入口族：只有用户指定 ⇒ M→B，`B→L` 唯一入边，F 不立 formal 子目标

**规则**：形式化**不是流水线的一环**：只有用户指定时才走，入口是 `M` 交给 `B`、由 `B` 判成本后逐条派 `L`（`B→L` 是 L 的**唯一**入边，`L→C` 是它唯一的出边），F 不许立 `formal` 子目标（`FORMAL_IS_NOT_F_TODO`）、不许把 formal 的方法派给 E（`FORMAL_OWNER` = `L`），F 的推理**就是它的工作方式**（没有开关；缺缝要明说"缺缝"，不许落"未接线"的死胡同）。

- 补充：Lean 关着时这条协作面整条看不见 —— `formal.*` 不装配、`B→L` 与 `L→C` 都被 policy 判 `forbidden_edge`（理由串点名 `lean_off`），但**声明面**（`capabilities`）照样有 L 那三件动作。
- 补充：论文对应表那一侧也是同一个口径 —— Lean 那一行按开关换形状（`LEAN_FILE_ROW` / `LEAN_FILE_ROW_NO_LEAN`），台账 kind 与"谁签过"分两格写，读不出就写读不出。
- **落点**：`src/agentflow/agent_f/core.py::FORMAL_OWNER`、`src/agentflow/agent_f/core.py::E_METHODS`、`src/agentflow/agent_f/core.py::FORMAL_EDGE_MISSING_REASON`、`src/agentflow/agent_f/core.py::_is_formal_subgoal`、`src/agentflow/agent_f/core.py::_formal_not_in_f_round`、`src/agentflow/agent_f/core.py::_formal_dispatch_facts`、`src/agentflow/agent_f/core.py::_seam_missing_round`、`src/agentflow/agent_f/core.py::_wash_manuscript`、`src/agentflow/agent_f/create_plan.py::FORMAL_IS_NOT_F_TODO`、`src/agentflow/agent_f/_support.py::UNWIRED_OWNERS`、`src/agentflow/agent_prompts.py::_reaches_proof_review`、`src/agentflow/agent_prompts.py::conductor_tool_count`、`src/agentflow/agent_prompts.py::prompt_text_problems`、`src/agentflow/specs/g.py::LEAN_FILE_ROW`、`src/agentflow/specs/g.py::LEAN_FILE_ROW_NO_LEAN`、`src/agentflow/papermapping.py::CONJECTURE_KIND`、`src/agentflow/papermapping.py::THEOREM_ENV_KINDS`、`src/agentflow/papermapping.py::LEDGER_KIND_FIELD`、`src/agentflow/papermapping.py::REVIEWED_FIELD`、`src/agentflow/papermapping.py::kind_gap_reading`、`src/agentflow/attackround.py::PROOF_EXIT_CRITERIA`
- **判据**：`tests/test_f_formal_subgoal_owner_l.py::test_create_plan_refuses_a_formal_subgoal_whichever_way_it_is_written`、`tests/test_f_formal_subgoal_owner_l.py::test_f_does_not_dispatch_an_owner_l_subgoal_to_e`、`tests/test_f_formal_subgoal_owner_l.py::test_no_edge_reaches_l_except_from_b`、`tests/test_f_has_no_formal_entry.py::test_a_f_tool_surface_has_no_lean_or_formal_tool`、`tests/test_f_has_no_formal_entry.py::test_b_the_rendered_prompt_makes_no_formal_promise`、`tests/test_f_reasoning_is_its_working_mode.py::test_unwired_owners_does_not_contain_f`、`tests/test_f_reasoning_is_its_working_mode.py::test_a_f_round_never_lands_the_not_wired_dead_end`；现算：`agent_f.core.FORMAL_OWNER` = L、`agent_f.core.E_METHODS` = 3、`agent_f.core.FORMAL_EDGE_MISSING_REASON` = formal_edge_missing、`agent_f.create_plan.FORMAL_IS_NOT_F_TODO` = formal_is_not_f_todo、`papermapping.THEOREM_ENV_KINDS` = 2

### [规范] §16.11 C11 权限面与写口族：`statements` 只经 B、手填 ID 拒、通用写口只写簿记、保留产物

**规则**：写面只有四条硬事实 —— ① `statements` **只经** `B` 的 `register_statement` 落（别的角色直写是受控拒绝且一行都不落，`no_caller_role` 不是后门）；② **手填 ID 一律拒绝**（编号由台账分配；写错前缀的拒信要点名正确的那一个）；③ 通用能力那一批（`UNIVERSAL_TOOLS`）只许写**簿记表**（`BOOKKEEPING_TABLES`），碰知识表（`KNOWLEDGE_TABLES`）在运行期就被拒；④ 框架自有产物（证明手稿 / 研究报告）**不许智能体手写**（`RESERVED_ARTIFACT_*`），要改走正路。

- 补充：集合型字段在写入期归一化（顺序与去重不留两套口径），`tasks` 不许种到别人名下、`item_state` 不许伪造 —— 这两条由板项状态机（只许前进、`done` 之前必须 `seen`、`acked` 只配 `ack`）与 `ack` 的"只许 ack 收件人是自己的项"一起守。
- 补充：`tasks` 的写路只有两条 —— `conductor.post_task`（给自己落一条活项）与框架自己的收口路径（`conductor.ack` / `mark_item_seen` / `open_item`）；通用写口的 `table.create(table="tasks")` / `table.update(table="tasks")` 由 `_tasks_write_refusal` 受控拒绝（`TASKS_POSTED_BY_THEIR_OWNER`：收件人只能是自己、不许伪造 `item_state`），"种到别人名下"在结构上办不到。
- **落点**：`src/agentflow/tools/__init__.py::UNIVERSAL_TOOLS`、`src/agentflow/tools/__init__.py::UniversalTool`、`src/agentflow/tools/__init__.py::BOOKKEEPING_TABLES`、`src/agentflow/tools/__init__.py::KNOWLEDGE_TABLES`、`src/agentflow/tools/__init__.py::is_universal_tool`、`src/agentflow/tools/__init__.py::universal_tool_is_bookkeeping_only`、`src/agentflow/tools/__init__.py::universal_tool_tables`、`src/agentflow/tools/__init__.py::stale_universal_tools`、`src/agentflow/tools/__init__.py::_check_universal_tools_are_registered`、`src/agentflow/tools/table_tools.py::_hand_typed_id_refusal`、`src/agentflow/tools/table_tools.py::_tasks_write_refusal`、`src/agentflow/tools/table_tools.py::TASKS_POSTED_BY_THEIR_OWNER`、`src/agentflow/tools/table_tools.py::_with_proof_routes`、`src/agentflow/tools/fs_tools.py::RESERVED_ARTIFACT_KIND`、`src/agentflow/tools/fs_tools.py::RESERVED_ARTIFACT_TABLE`、`src/agentflow/tools/fs_tools.py::_reserved_artifact`、`src/agentflow/tools/fs_tools.py::_reserved_refusal`、`src/agentflow/schema.py::normalize_set_fields`、`src/agentflow/schema.py::id_allocator_kind`、`src/agentflow/schema.py::looks_like_prefixed_id`、`src/agentflow/capabilities.py::_assembled_groups`、`src/agentflow/capabilities.py::_candidates_impl`、`src/agentflow/conductor.py::claim_item`、`src/agentflow/conductor.py::mark_item_seen`
- **判据**：`tests/test_tasks_write_port_refuses_forgeries.py::test_b_posting_on_somebody_elses_board_is_refused`、`tests/test_tasks_write_port_refuses_forgeries.py::test_c_forging_a_closed_item_is_refused`、`tests/test_tasks_write_port_refuses_forgeries.py::test_d_forging_a_seen_item_is_refused`、`tests/test_tasks_write_port_refuses_forgeries.py::test_f_the_gate_is_a_permission_surface_not_a_param_check`、`tests/test_statements_are_registered_by_b.py::test_f_direct_write_is_refused_with_the_code_and_lands_nothing`、`tests/test_statements_are_registered_by_b.py::test_every_non_b_role_is_refused_and_b_still_registers`、`tests/test_a_concept_row_is_registered_by_the_secretary.py::test_stubbing_the_route_back_to_a_direct_write_turns_the_reading_red`、`tests/test_hand_filled_ids_are_refused.py::test_a_hand_filled_relation_id_is_refused_with_the_actionable_sentence`、`tests/test_hand_filled_ids_are_refused.py::test_every_table_key_is_ledger_allocated`、`tests/test_universal_tools_are_for_everyone.py::test_b_no_universal_tool_writes_a_knowledge_table`、`tests/test_universal_tools_are_for_everyone.py::test_d3_a_universal_entry_that_writes_knowledge_tables_is_refused_at_runtime`、`tests/test_fs_reserved_framework_artifacts.py::test_a_f_cannot_hand_write_his_proof_manuscript`、`tests/test_fs_reserved_framework_artifacts.py::test_the_table_names_match_the_one_definition`、`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py::test_acking_somebody_elses_item_is_refused_by_code_not_yours`；现算：`tools.UNIVERSAL_TOOLS` = 13、`tools.BOOKKEEPING_TABLES` = 1、`tools.KNOWLEDGE_TABLES` = 9

### [规范] §16.12 C12 读数与用户端族：名册三态读数、书目面、聊天行 ID、预热三态、错误两轴

**规则**：用户端只许**读**，且每一块读数都是三态 —— 名册面的"在飞 / 待机 / 静默 / 未读到"由后端算完再下发（前端不许自己拿一个旧布尔冒充），书目面**只数已准入的**（没有台账是 `unknown` 不是 0），每条聊天行都带**绝对编号与它的来源**（行里没有就写"没有"，不许留空猜），预热按钮的三态（计划 / 运行 / 完成或失败）与写权限开关分开报（关着就说关着），而错误统计是**两根轴**：真错误（`ERROR_CATEGORY_NAMES`）与过程读数（`PROCESS_CATEGORIES`）不许合并成一个总数。

- 补充：`webui/writes.py` 是"这个服务此刻许不许写"的唯一判据，页面上的禁用态与后端的拒绝必须同源。
- **落点**：`src/agentflow/readouts.py::roster_readout`、`src/agentflow/readouts.py::ROSTER_DATA_KEYS`、`src/agentflow/webui/readers.py::CHAT_PUBLIC`、`src/agentflow/webui/readers.py::library_face`、`src/agentflow/webui/readers.py::handle_library`、`src/agentflow/webui/readers.py::ADMISSION_BASIS_CANDIDATE`、`src/agentflow/webui/readers.py::PROBLEM_ADMISSION_UNDECIDABLE`、`src/agentflow/webui/cacheface.py::warm_job`、`src/agentflow/webui/cacheface.py::WARM_JOB_STATES`、`src/agentflow/webui/cacheface.py::handle_cache_status`、`src/agentflow/webui/writes.py::writes_allowed`、`src/agentflow/webui/writes.py::WRITES_OFF_REASON`、`src/agentflow/webui/server.py::handle_errors`、`src/agentflow/webui/server.py::handle_errors_categories`、`src/agentflow/webui/state.py::type_decls`、`src/agentflow/errorstats.py::ALL_CATEGORIES`、`src/agentflow/errorstats.py::ERROR_CATEGORY_NAMES`、`src/agentflow/errorstats.py::PROCESS_CATEGORIES`、`src/agentflow/errorstats.py::process_categories`
- **判据**：`tests/test_webui_three_state_reading.py::test_active_is_computed_from_the_definition_not_copied_from_a_lying_cell`、`tests/test_webui_three_state_reading.py::test_an_unread_tally_says_unreadable_with_the_reason_and_never_a_zero`、`tests/test_webui_readers.py::test_every_face_carries_tri_and_reason`、`tests/test_library_face_only_counts_admitted_works.py::test_c_a_missing_or_broken_table_is_unknown_and_never_zero`、`tests/test_chat_lines_carry_the_absolute_id.py::test_every_line_carries_the_absolute_id_keys`、`tests/test_chat_lines_carry_the_absolute_id.py::test_a_line_without_an_id_says_so_instead_of_pretending`、`tests/test_chat_page_shows_who_and_which_id.py::test_the_chat_page_really_reads_the_id_and_its_source`、`tests/test_cache_warm_button_is_honest.py::test_a_a_service_without_the_write_switch_says_so_and_the_page_disables`、`tests/test_the_root_is_named_m.py::test_the_root_state_is_the_same_three_state_as_every_other_node`、`tests/test_the_root_is_named_m.py::test_the_real_workspace_root_is_m`；现算：`readouts.ROSTER_DATA_KEYS` = 9、`errorstats.ALL_CATEGORIES` = 26、`errorstats.PROCESS_CATEGORIES` = 3

### [规范] §16.13 C13 清洁与判据基础设施族：死函数台账、绿灯不造假、仓库不更脏

**规则**：这一批收的是"让判据自己可信"的四件事 —— ① **死私有函数必须有台账条目**（`test_clean_invariant`：扫出来的孤儿要么被删、要么在登记表里说清为什么留着）；② **绿灯不许造假**（`test_green_is_not_faked`：不许 `assert True` 这类恒真断言、每个判据文件里至少有一条非打桩的正控、新判据不许被 skip 掉、反真空用例必须真的碰到它的对象）；③ **跑完自检要留下干净的仓库**（`test_demo_selftest_leaves_the_repo_clean`）；④ **仓库体检不许变差**（`test_repo_survey_does_not_get_worse`：比分母是当次的旧债，只许少不许多）。

- 补充：`_chain_cells` 与 `_unknown_tool_problems` 与 `child_counts_reading` 是这三件事各自在代码里的一个读数口 —— 它们都只读，且"读不到"与"读到 0"分得开。
- **落点**：`src/agentflow/closing.py::child_counts_reading`、`src/agentflow/closing.py::mapping_gaps`、`src/agentflow/agenttrace.py::_chain_cells`、`src/agentflow/agent_skills.py::_unknown_tool_problems`
- **判据**：`tests/test_clean_invariant.py::test_no_dead_private_function_without_a_ledger_entry`、`tests/test_clean_invariant.py::test_each_watched_concept_has_exactly_one_implementation`、`tests/test_green_is_not_faked.py::test_no_assert_is_forever_true`、`tests/test_green_is_not_faked.py::test_every_criterion_file_has_a_non_stubbed_case`、`tests/test_green_is_not_faked.py::test_no_new_criterion_can_be_skipped_away`、`tests/test_green_is_not_faked.py::test_every_anti_vacuum_case_touches_its_subject`、`tests/test_demo_selftest_leaves_the_repo_clean.py`、`tests/test_repo_survey_does_not_get_worse.py`（数字格：无 —— 这一簇的可核面是四个落点符号与上面八份判据，理由见 §16.14）

### [规范] §16.14 收尾：没法机器核的条目、就地更正、与旧文档的关系

**一、哪些条目没法机器核（写成"指路 + 判据文件位置"，刻意不写数字）**：

| 条目 | 为什么机器核不了 | 指路 |
|---|---|---|
| C1 "计时器不阻塞动作"、"挂机是零步零调用" | 这是**行为**，要真跑一圈循环才看得见（不是文档里的一个数） | `tests/test_park_is_a_real_stop.py::test_a_parked_parent_takes_no_model_calls_and_no_steps`、`tests/test_timers_and_handoff_semantics.py::test_c_a_timer_does_not_block_work_in_hand` |
| C5 "正文只到链尾" | 同上：中间几跳的收件箱里有没有正文，只有在真跑一条五跳链之后才量得出来 | `tests/test_guide_goes_down_the_secretary_chain.py::test_a2_a_five_hop_chain_leaves_three_intermediate_agents_at_zero`、`...::test_f_leaking_the_body_to_every_hop_makes_a_red` |
| C5 "公告里点名 + 指令语气 ⇒ 拒" | 判"是不是指令语气"有一次语义判定，不是词表比对 | `src/agentflow/agent_prompts.py` 的公共频道那一段 + `tests/test_the_public_channel_is_the_senders_children.py` |
| C7 "不要求逐字（同一句话换写法仍可 `consistent`）" | "意思一样"不可枚举；能机器核的是**档位与挡签** | `tests/test_v_checks_fs_citations.py::test_a_consistent_use_signs_even_though_the_words_differ` |
| C8 "条件 → 结论 一致" | 判一条命题是不是同一条要过一次模型；机器核的是它的**后果**（合并成一行 / `unknown` 不合并） | `tests/test_secretary_recognizes_the_same_proposition.py` |
| C9 "按花的力气" | 五档的**边界**可核，"这次算不算绕路"不行 | `tests/test_nontriviality_is_judged_by_effort.py` |
| C13 三条基础设施判据 | 它们守的是"别的判据可不可信"，没有自己的读数 | `tests/test_clean_invariant.py`、`tests/test_green_is_not_faked.py` |

> 这一栏本身就是三态纪律的一次落地：**"核不了"要写"核不了"，不写一个看起来精确的数字。**

**二、就地更正（旧口径 → 新口径，均标 `（2026-10-27 口径）`）**：

- `docs/ROLE-SPECS.md` §F.2：补 F-7 一条（**写证明手稿 + 末尾 `## 依赖` 四列表**）。旧表六条职责里没有"手稿"这件事，
  而今天 F 的产出、秘书洗稿、D 携带、B 读稿登记整条链都从那份手稿开始 —— 不写进去，读者会以为依赖边是"某处自动生成的"。
- `docs/ROLE-SPECS.md` §F.3：把"自己'想数学'"那一行的旧理由改掉。旧文字说"本轮的 F 是**确定性调度器**，不是推理者"，
  业主 2026-10-26 已裁定逐字「没有默认开，这个就是F的工作方式，没有开关的说法」⇒ 推理是 F 的工作方式，
  判据 `tests/test_f_reasoning_is_its_working_mode.py`（它还守着"那个开关的字面量全仓清零"）。

**三、没有旧版文字可改的簇**：C1–C7、C9、C11–C13 在这三份规范里此前**一条都没有**（不是"写得不对"，是"没写"）——
这就是业主那句「新设计未被规范收录」的字面含义。它们只新增，不需更正；C8、C10 各有一处旧文字，已在上表更正。

**四、这一节不做的事**：不改任何功能代码、不改 `specs/*`、不动 golden / `PROMPT_VERSION` / 缓存；
本节引用的 745 条符号清单是输入（`agentflow/temp/_inventory_master.md`），**不在本批改动范围内**。

**五、本批欠一次"读数重算"（按 §15.3 第 4 步，单独一次、附逐格 diff、交人审）**：

`conductor.post_task` 进册（2026-10-27 晚）之后，工具总数 **111 → 112**，逐角色数与本文件 §0.2 的
`LIVE-READINGS` 块、`ROLE-SPECS.md` §0.2 / §R0 表与各角色 `.4` 标题、`ROLE-SPECS-APPENDIX.md`
§R0.1 / §A.4–§M.4 / §S3 都还是**旧口径**。机器读数（复跑见下）：

```powershell
# 声明面的差集：HEAD 的 @tool 声明 110 件 → 工作树 111 件，多出来的只有 conductor.post_task
git diff HEAD -- src/agentflow/tools | Select-String '^\+\s*"conductor\.post_task"'
# 装配面的读数：112 件（Lean 开），conductor.* 一族 20 件
python -m agentflow.cli tools
```

因此 `tests/test_role_specs_complete.py` 与 `tests/test_role_specs_appendix_is_live.py` 里
那几条"文档计数 vs 现场装配"的用例**现在是红的**，红的理由是**读数过期**，不是本节的规则写错 ——
这两件事必须分开说：把"设计没进规范"和"读数没重算"混成一个红，接下来的人就不知道该改哪一处。
本批不动那些数，理由正是 §15.3 第 4 步：重算读数是**一次单独的改动**，要逐格 diff 交人审，
不许夹在"把设计写进规范"这一批里悄悄滑过去（`P-读数-2`：不许自己批准自己）。

