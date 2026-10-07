# DRIFT-LIST —— 会随仓库内容变化的硬编码数字（批次 `G2`，只读分析）

> **本文只写清单与处置建议，不改 `agentflow/` 下任何字节。**
> 写者：`G2`（只读分析者）。写域：`D:\Incubator\temp\`。
> 并行的 `G1` 正在改 `.noai-paths` 与 `AGENTS.md` —— 本文**只读**它们，**不碰**。
> 与本文相关的原始输出：`temp/G2-cmd-baseline.txt`、`temp/G2-lint-full.txt`、
> `temp/G2-drift-probe.{py,txt}`、`temp/G2-numscan.{py,txt}`、`temp/G2-measure{,2,3}.{py,txt}`、
> `temp/G2-p910-probe.{py,txt}`。

---

## 0. 判定标准（逐字）

> **「当仓库某处新增 1 条测试 / 1 条规则 / 1 个文件时，这个数字会不会变」**

- **会变** ⇒ 这是**活读数**（live reading）。按 `G-32` 必须写成「**命令 + 观测时刻**」，
  不许写成单个定值 —— 除非它有一条**当次对账的判据**在守着（那时可以留定值，但定值仍须能被判据改）。
- **不会变** ⇒ 这是**常量**（结构常量、受控词表长度、协议版本号、引文）。可以留定值。

三级细化（下文表格用 A/B/C 标）：

| 级 | 含义 | 例 |
|---|---|---|
| **A** | 必然漂：只要有人做正常的开发动作（加用例 / 加规则 / 加文件 / 加工具 / 加一条登记），它就变 | `noai_gate_pytest_collected`、`工具总数`、`.noai-paths` 条目数 |
| **B** | 条件漂：只在**特定那一类**对象变化时才变 | `DESIGN*.md 份数`、`data/*.json` 个数、`.noai-paths` 的「七类」 |
| **C** | 不漂：常量 / 引文 / 已经写成「区间 + 观测时刻」的合规样本 | `REQUIRED_APPROVALS_ON_HIT=2`、`draft/22` 的逐字引文、`§0.3` 第 13 项 |

---

## 1. 我实跑的六条命令与读数（观测 2026-09-27 11:49:25 – 11:52:17 +0800）

**要求实跑的那六条**（Windows 上 `tail -1` 用 `Select-Object -Last 1` 等价替代，其余逐字照跑）：

| # | 命令 | 实测读数 | 退出码 |
|---|---|---|---|
| 1 | `python -m pytest tests/ --collect-only -q -p no:cacheprovider` \| 末行 | `2403/2411 tests collected (8 deselected) in 4.43s` | 0 |
| 2 | `python scripts/lint_rules.py` | 汇总：`[linter] 扫描 {'src_py': 53, 'tests_py': 120}；规则 12 条；模式 日常` / `[linter] error 1 / warning 0 / info 25` | **1** |
| 3 | `python -c "import sys;sys.path.insert(0,'src');import agentflow.schema as s;print(len(s.TABLES))"` | `15` | 0 |
| 4 | `(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count` | `26`（**11:49:25 时是 23；11:50:23 时变 26** —— G1 在 11:50:57–11:51:08 之间给清单加 3 条并签了字，见 §4） | 0 |
| 5 | `(Get-ChildItem tests -Filter 'test_*.py').Count` | `116` | 0 |
| 6 | `(Get-ChildItem src/agentflow/tools -Filter '*_tools.py').Count` | `11` | 0 |

**补跑的量法**（`test_release_all.py::measured_readings()` 的原样调用，`temp/G2-drift-probe.py`）：

```
观测时刻 2026-09-27 11:50:23 +0800
lint_rules_rules            = 12      lint_rules_warning       = 0        lint_rules_info = 25
lint_rules_strict_warning   = 39      lint_rules_strict_info   = 24
noai_paths_glob             = 26      noai_paths_unique        = 23      noai_paths_categories = 7
tools_star_tools_py         = 11      noai_gate_pytest_collected = 116
```

**另外现场量的几个 doc 声称值**：

| 量法 | 实测 | 文档今天写的是 |
|---|---|---|
| `len(claimanatomy.CLAIM_FIELDS)` | **19** | `DEVELOPMENT.md:68`/`:1111` 写 **12 字段** |
| `verify.py` 里 `Issue(...)` 第 4 实参去重（AST） | **77** | `DEVELOPMENT.md:331`/`:1183` 写 **71 个 Issue.code** |
| R007 那条 `info` 的原文 | `公开函数 669 个，其中 192 个没有 docstr…` | `DEVELOPMENT.md:379`/`:844` 写 **191 / 661** |
| `python -m agentflow.cli tools` | `工具总数：55（已装模块 11：…）`；`各角色 {'A':20,'B':18,'C':17,'D':37,'E':21,'F':32,'G':32,'H':22}` | `DEVELOPMENT.md:144`/`:162` 同（**未漂**） |
| `build_registry(store=None)` | **43**（缺 `workspace_root` ⇒ fs 组不装） | `DEVELOPMENT.md:144` 写「`store=None` 口径是 **50**」 |
| `build_registry(store=None, workspace_root=.)` | **50** | 同上（⇒ 50 要靠 `workspace_root` 才复现） |
| `.noai-approvals.json` | entries **22**、带 sha256 **22**、`reviewers_total` **40** ⇒ 欠签 **4** | `DEVELOPMENT.md:70`/`:276`/`:278` 写 **16 条目 / 欠签 32** |
| `(Get-ChildItem src/agentflow -Filter '*.py').Count` | **40** | `DEVELOPMENT.md:384` 写「全项目 **42** 个 src 文件」 |
| `(Get-ChildItem src/agentflow/tools -File).Count` | **13** | `DEVELOPMENT.md:335` 写「工具层（**13** 个文件）」（**未漂**） |
| `(Get-ChildItem data -Filter '*.json').Count` | **16** | `DEVELOPMENT.md:55` 写「`data/`（**16** 个 JSON）」（**未漂**） |
| `(Get-ChildItem DESIGN*.md).Count` | **5** | `DEVELOPMENT.md:317`/`:1308` 写 5 份（**未漂**） |
| `len(schema.ROLES)` | **8** | 未在 doc 里以数字形式钉 |
| `len(gates.GATES)` / `gates.AXES` | **15** / `("数学","体例","工程","证据")` | `DEVELOPMENT.md:69` 写 15 门（**未漂**）；`gates.py:88` 注释写「**三道轴**」而元组有 **4** 个（注释内的漂） |

> ⚠️ **今天最重要的一条现场事实**：`python scripts/lint_rules.py` 的退出码是 **1**（`error 1`），
> 唯一那条 error 是 `R009 tests/test_release_all.py:1287` —— 一行 Python 注释里写了成对的星号
> `**不写死**`。它不在 HEAD 版里（`git show HEAD:agentflow/tests/test_release_all.py` 只有 191 行、
> 没有这段），是本轮未提交工作引入的。而 `DEVELOPMENT.md:155` 写着 linter「`error 0`…**退出码 0**」。
> ⇒ **「退出码 0」这个数今天已经漂了，而且没有任何判据会咬它**（`error` 栏被判据**刻意**排除）。

---

## 2. 数字漂移清单（逐条一行）

图例：**漂** = A / B / C（§0 的判定标准）；**有判据?** = 今天是否有一条测试会在它过期时变红。

### 2.1 测试计数类（新增 1 条用例 ⇒ 漂）

| 文件:行 | 那个数字是什么 | 今天由什么命令产出（实跑读数） | 漂 | 有判据? | 处置建议 |
|---|---|---|---|---|---|
| `DEVELOPMENT.md:138` | `LIVE-READINGS` 的 `noai_gate_pytest_collected = 116` | `python -m pytest tests/test_noai_gate.py --collect-only -q -p no:cacheprovider` ⇒ `116 tests collected` | A | ✅ `pytest_count_claim_problems` | **保留但按 G-32 补观测时刻**（这条已经被判据钉住，是今天唯一"能咬人"的用例数）。⚠️ **F10 加 1 例正是咬在这一格上** |
| `DEVELOPMENT.md:1208` | §9.1 FC-27 行的「当次 **116 passed** / 0 skipped」 | 同上 | A | ✅ 同判据（认 `tests/test_noai_gate.py` 那一行的 `N passed`） | 同上 |
| `DEVELOPMENT.md:1231` | FC-09 行的「当次 **116 passed** / 0 skipped」 | 同上 | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:54` | 「**105** 个 `test_*.py`」 | `(Get-ChildItem tests -Filter 'test_*.py').Count` ⇒ **116** | A | ❌ **无**（该行带 `S2`/`当时`/`原写` ⇒ 被 `_HISTORICAL_MARKERS` 整行豁免；而且没有正则认「个 `test_*.py`」这个写法） | **改命令 + 观测时刻**（`(Get-ChildItem tests -Filter 'test_*.py').Count`），并考虑给 `test_release_all.py` 加一条认「个 `test_*.py`」的判据 —— 否则这格永远静默漂 |
| `DEVELOPMENT.md:118` | 复跑命令的「（当次 `1 passed`）」 | `python -m pytest tests/test_release_all.py -q -k development_md_linter_readings` ⇒ 今天 **`1 failed`** | A | ❌ 无 | **改相对表述**（「当次读数见该命令输出」），或加观测时刻。今天它已经是假的 |
| `DEVELOPMENT.md:156` | §0.3 第 13 项全量 pytest 区间 | `python -m pytest -q`（本批**没跑全量**，按工单禁止） | A | ❌ 无（刻意不加） | **不动** —— 它已经是「区间 + 观测时刻」的**合规样板**（本清单把它当正例引用） |
| `README.md:268` | 「同一次运行：`2 failed, 1948 passed, 1 skipped, 8 deselected, 1 xfailed in 277.76s`」 | 同上 | A | ❌ 无 | **改命令 + 观测时刻**（它已写了"不是本批引入"，但缺时刻 ⇒ 读者无法判新旧） |
| `DEVELOPMENT.md:528` | 「`tests/test_agent_e.py`（**30 例**）」 | `python -m pytest tests/test_agent_e.py --collect-only -q`（本批未跑） | A | ❌ 无 | **改成相对表述**或「命令 + 观测时刻」 |
| `DEVELOPMENT.md:602` | 「`tests/test_rebuild.py`（**3 例**…）」 | `--collect-only` 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:688` | 「`tests/test_interactions.py`，**48 例**」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:700` | 「`tests/test_tools_readonly_roles.py`（**7 例**）」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:1187` | FC-06 行「`tests/test_tools_readonly_roles.py`（**7 例**）」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:1193` | FC-12 行「`tests/test_rebuild.py`（**3 例**）」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:1215` | 「`tests/test_fc17_wiring.py` **10 例**，…单跑实测 `10 passed`」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:1242` | 「FC-17（`test_fc17_wiring.py` **10 例**）、FC-19（`tokenmeter.py` **14 例**…）」 | 同上 | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:1252` | §9.3 待办「（**10 例**）+ `tests/test_context_budget.py`（**37 例**）」 | 同上 | A | ❌ 无 | 同上 |
| `tests/test_release_all.py:1230,1246-1251` | 判据本体 `_PASSED_CLAIM_RE = r"(\d+)\s*passed"` | 判据自身（不是数字） | C | — | **不动**。这是"把活读数钉住"的**正确形态**：它比对的是 `measured["noai_gate_pytest_collected"]` |
| `tests/test_release_all.py:1293` | 负控夹具 `f"当次 {current} passed"` / `f"当次 {current - 11} passed"` | 判据自身 | C | — | **不动**。这是 `F8-R11` 修出来的**相对表述样板**（不写死当次数） |

### 2.2 规则 / linter 计数类（新增 1 条规则 ⇒ 漂）

| 文件:行 | 那个数字是什么 | 今天由什么命令产出（实跑读数） | 漂 | 有判据? | 处置建议 |
|---|---|---|---|---|---|
| `DEVELOPMENT.md:129` | `lint_rules_rules = 12` | `len(lint_rules.RULES)` ⇒ **12** | A | ✅ `live_reading_problems` + `rule_claim_problems` | **保留 + 观测时刻**（已判据守） |
| `DEVELOPMENT.md:130-131` | `lint_rules_warning = 0` / `lint_rules_info = 25` | `python scripts/lint_rules.py` ⇒ `0 / 25`（error 1） | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:132-133` | `lint_rules_strict_warning = 39` / `strict_info = 24` | `python scripts/lint_rules.py --strict` ⇒ `error 1 / warning 39 / info 24` | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:74,85,86,95,155,673,814,1182,1226` | 「12 条规则」「R001–R012」「9 条规则（S2）」 | `len(RULES)` ⇒ 12 | A | ✅ `rule_claim_problems`（对 `DEVELOPMENT.md` 全文，逐行豁免历史记号行） | **保留** —— 这是全仓**覆盖最好**的一类 |
| `DEVELOPMENT.md` 全文 | 每一处 `error A / warning B / info C` 三元组 | 当次 `1 / 0 / 25` | A（`error` 栏）/ B（`warning`/`info` 栏） | ✅ `tally_claim_problems`（**只比 warning/info**） | **保留** —— 但 §2.1 的「退出码 0」这一句要单独改（`error` 栏刻意不钉，读它的人必须看当次输出） |
| `README.md:148,278` | 「R001–R012；R004/R006 已退休」「规则 **12** 条」 | `len(RULES)` ⇒ 12 | A | ❌ **无**（`readme_number_problems` 只核 `.noai-paths` 两个数 + `*_tools.py` 模块数） | **改成相对表述**（「规则条数与区间以 `python scripts/lint_rules.py` 摘要行为准」），或把 `rule_claim_problems` 的判据面扩到 `README.md`（注意它现在**只接受 `DEV_MD`**） |
| `DEVELOPMENT.md:379,844` | 「实测 **191 / 661** 个公开函数没有 docstring」 | 读 `python scripts/lint_rules.py` 的 `info R007` 那一行 ⇒ 今天 `公开函数 669 个，其中 192 个没有 docstring` | A | ❌ 无 | **改命令 + 观测时刻**（原文自己写了"复算：`python scripts/lint_rules.py`，读 `info R007` 那一行" —— 那就把数字换成那两行命令）。**它今天已经漂了** |
| `gates.py:88` | 注释「**三道轴**（`STYLE/RUBRIC.md:30-33`）」，而 `gates.py:91` 的 `AXES` 有 **4** 个 | `len(gates.AXES)` ⇒ 4 | C（注释文字，不是数） | ❌ 无 | **改成相对表述**（「轴见 `AXES`」）—— 这是一条**文字与元组不一致**的低成本修复 |

### 2.3 禁改区清单计数类（新增 1 条登记 ⇒ 漂）★ 今天已红

| 文件:行 | 那个数字是什么 | 今天由什么命令产出（实跑读数） | 漂 | 有判据? | 处置建议 |
|---|---|---|---|---|---|
| `DEVELOPMENT.md:134` | `LIVE-READINGS` 的 `noai_paths_glob = 23` | `(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count` ⇒ **26** | A | ✅ `live_reading_problems` | **改命令 + 观测时刻**（判据已红）。⚠️ 定稿前需等 G1 的清单），否则改完又被 G1 咬 |
| `DEVELOPMENT.md:135` | `noai_paths_unique = 20` | 上述条目行按第一栏去重 ⇒ **23** | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:136` | `noai_paths_categories = 7` | `[category: …]` 去重 ⇒ **7** | B（加一类才变） | ✅ 同上 | **保留**（未漂） |
| `DEVELOPMENT.md:274` | §1.5「**清单 glob 数** …  **23**」 | 同 §2.1 第 4 条 ⇒ **26** | A | ✅ `manifest_claim_problems` | **改命令 + 观测时刻** |
| `DEVELOPMENT.md:275` | §1.5「**唯一路径数** … **20**」 | ⇒ **23** | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:276` | §1.5「**台账条目数** … **16**」 | `json` 读 `.noai-approvals.json` 的 `entries` ⇒ **22** | A | ❌ **无（刻意）** —— `manifest_claim_problems` 的 docstring 逐字写"台账条目数 / 欠签两格**刻意不在这里钉**" | **人裁决**：要么保持"刻意不钉"（那就必须把「16」改成命令 + 时刻，否则读者拿到的是一个没有来源的定值），要么把它并入判据面 |
| `DEVELOPMENT.md:278` | §1.5「**欠签** … **32**」 | `entries × 2 − reviewers_total` = `22×2 − 40` ⇒ **4** | A（**每签一个字就变**） | ❌ 无（同上，刻意） | 同上。⚠️ 它今天**已经从 32 变成 4**，而文档里没有任何东西会红 |
| `DEVELOPMENT.md:277` | §1.5「**禁改区类别数** … **7**」 | `[category: …]` 去重 ⇒ **7** | B | ✅ `manifest_claim_problems`（`_MANIFEST_TABLE_RES`） | **保留** |
| `DEVELOPMENT.md:70` | §0.1 `.noai-paths` 行「**23** 条条目 / **20** 条唯一路径 / 7 个分组；台账 **16** 条目 / 欠签 **32**」 | ⇒ **26 / 23 / 7**；台账 **22 / 4** | A | ❌ **被豁免** —— 该行含「本条**原写**"19 条条目 + 7 个分组"」⇒ `_HISTORICAL_MARKERS` 命中「原写」⇒ **整行退出对账** | ⚠️ **这是本清单最重要的一条**：一条**当前值**声明因为句尾带了一句更正说明而被整行豁免，于是它静默漂。建议：把更正说明**拆到下一行**（或把 `_HISTORICAL_MARKERS` 的作用域从"整行"收窄到"引号内的旧值"），并让这一行的当前值接受对账 |
| `DEVELOPMENT.md:280,289-291,295,299,303-304` | 「差集…只有 **4** 条」「**23 − 20 = 3**」「超 **16** 条」「传 **23** 条 glob」 | 变量：`26 / 23 / 7 / 22 / 4 / 16` | A | 部分 ✅（`:303`/`:941`/`:1208` 被 `manifest_claim_problems` 覆盖） | **改成相对表述**（「差集 = 唯一路径数 − 台账条目数」），别再写算式结果 |
| `DEVELOPMENT.md:941` | §5「当次 **23** 条条目 / **20** 条唯一路径 / 7 个分组」 | ⇒ **26 / 23 / 7** | A | ✅ `manifest_claim_problems` | **改命令 + 观测时刻** |
| `DEVELOPMENT.md:1208` | §9.1 FC-27 行「当次 **23** 条条目 / **20** 条唯一路径 / 7 个分组」 | ⇒ **26 / 23 / 7** | A | ✅ 同上 | 同上 |
| `DEVELOPMENT.md:1110` | §9.3 待办 13「给 **13** 个禁改区文件填 `reviewers`（各 2 名）」 | 台账 entries **22** 条（全部带 sha256），`reviewers_total` **40** | A | ❌ 无 | **改命令 + 观测时刻**；「各 2 名」是常量（`REQUIRED_APPROVALS_ON_HIT`），可留 |
| `README.md:142` | 文件树「（**23** 条 glob / **20** 条唯一路径 / 7 类；台账 **16** 条目 ⇒ 欠签 **32**）」 | ⇒ **26 / 23 / 7 / 22 / 4** | A | 部分 ✅（`readme_number_problems` 核前两个；台账两数不核） | **改命令 + 观测时刻**（前两个已判据守，后两个要人裁决是否并入） |
| `README.md:326` | 「传 **23** 条 glob 进去它报的是 **16**」 | ⇒ `26` 进去报 `?`（本批**未跑** `--check-approvals`） | A | ❌ 无 | **改成相对表述**（「传清单条目数进去」） |
| `README.md:353` | 「禁改区那 **13** 个文件尤其如此」 | 台账 **22** 条 / 清单唯一 **23** 条 | A | ❌ 无 | **改命令 + 观测时刻**（「禁改区文件数」的口径本身要写清：22 = 台账条目 / 23 = 清单唯一路径） |
| `.noai-paths:21` | 「…发布脚本 / 权限与审计」——**七类** | `[category: …]` 去重 ⇒ **7** | B | ❌ 无（**在禁改区文件里**） | **保留**（结构常量），但**改它要人签**（见 §5） |
| `.noai-paths:57` | 「**第 1 类和第 3 类**：这两个文件…」 | 分组序号 | B | ❌ 无（**禁改区**） | **保留**（序号是结构约定） |
| `.noai-paths:111-112`（= `AGENTS.md` 副本对应行） | 「发布门**第 8 步**放行的东西」「发布门的两道子门之一/之二」 | `tools/release_all.py` 的步序号（本批**未跑**） | B（加一步就变） | ❌ 无（**禁改区**） | **改相对表述**（「`release_all` 的 `coverage` 步」已有名字，不必写序号）—— 但**改它是禁改区改动 ⇒ 要 2 名 reviewer 签字** |
| `.noai-paths:13` | 「`07-...md` §C.3.4 给出了 **7 类**必须由人主导的区域」 | 逐字引文 | C | — | **不动**（引文；改它等于伪造引文） |
| `.noai-paths:99` | 「同一个 miniF2F 数字在四个口径下相差 **13–30 个百分点**」 | 引用 `schema.py` 注释 | C | — | **不动**（引文） |
| `.noai-paths:40` | 「`normalize_doi` 从 **26 行**漂到 **44 行**」 | 历史观测（给"不写行号"这条纪律当证据） | C | — | **不动**（它自身就是"行号易失"的证据） |
| `AGENTS.md`（清单正文） | 「本框架…把上述**七类**平移成下面这**七类**」 | `[category: …]` ⇒ 7 | B | ❌ 无（**禁改区**） | **保留**，改动需人签 |
| `.noai-approvals.json` 全文 | `entries` / `sha256` 个数 / `reviewers` 长度 | 每签一个字就漂 | A | 由 `noai_gate --check-approvals` 覆盖（**本批未跑**） | 它是**审计记录本体**，不是文档读数 ⇒ **不改**，但**所有引用它的数字**（§2.3 那几行）都必须改成命令 |

### 2.4 文件 / 模块 / 目录计数类（新增 1 个文件 ⇒ 漂）

| 文件:行 | 那个数字是什么 | 今天由什么命令产出（实跑读数） | 漂 | 有判据? | 处置建议 |
|---|---|---|---|---|---|
| `DEVELOPMENT.md:74` | linter 摘要「扫描 {'src_py': **53**, 'tests_py': **120**}」 | `python scripts/lint_rules.py` 首行 ⇒ `{'src_py': 53, 'tests_py': 120}` | A | ❌ 无 | **改命令 + 观测时刻**（加一个 `.py` 就变） |
| `DEVELOPMENT.md:335` | 目录树「`tools/` 工具层（**13** 个文件，模块 = 工具组）」 | `(Get-ChildItem src/agentflow/tools -File).Count` ⇒ **13**（11 `*_tools.py` + `base.py` + `__init__.py`） | A | ❌ 无 | **改命令 + 观测时刻**或**相对表述**（「= `*_tools.py` + `base.py` + `__init__.py`」） |
| `DEVELOPMENT.md:384` | §2.4「全项目 **42** 个 src 文件」 | `(Get-ChildItem src/agentflow -Filter '*.py').Count` ⇒ **40** | A | ❌ 无 | **改命令 + 观测时刻**。**已漂**（42 → 40；口径也可能只是"是否含 `tools/` 子目录"，要写清） |
| `DEVELOPMENT.md:317` | 「`DESIGN*.md` 设计理由（**5** 份…）」 | `(Get-ChildItem DESIGN*.md).Count` ⇒ **5** | B | ❌ 无 | **保留**（未漂）但建议写成命令 |
| `DEVELOPMENT.md:55` | 「`data/`（**16** 个 JSON）」 | `(Get-ChildItem data -Filter '*.json').Count` ⇒ **16** | B | ❌ 无 | **保留**（未漂）但建议写成命令 |
| `DEVELOPMENT.md:9` | 「`#### X.N` 共 **100** 行 = **10** 个角色节 × **10**；`REQUIRED` **8** 项」 | `python tools/verify_role_specs.py`（本批**未跑**） | B | 部分（`tools/verify_role_specs.py` 是发布门一步） | **改命令 + 观测时刻** |
| `README.md:164` | 「工具层（**11** 个 `*_tools.py`…）」 | `(Get-ChildItem src/agentflow/tools -Filter '*_tools.py').Count` ⇒ **11** | A | ✅ `readme_number_problems`（`_README_TOOLS_RE`） | **保留** —— 这是"README 里的活读数被钉住"的**唯一**一处，是本清单的正例 |
| `README.md:160` | 「`cancellation.py` 协作式取消（**4** 条规则…）」 | 我**没有复算**（`cancellation.py` 的规则表口径不明） | B | ❌ 无 | **保留 + 观测时刻**（我核实不了，见 §6） |
| `DEVELOPMENT.md:993-994,1029-1036` | §10 发布门逐项（「8 个 agent + `pipeline`」「55 / 泄漏 0」…） | 未跑 | A | ❌ 无 | **改成相对表述**（这整节是 S2 的历史快照，已在表头声明；但 `:1029`「`1497 passed`」这类**不带**历史记号的行会被读者当当前值） |

### 2.5 工具面 / 受控词表计数类（新增 1 个工具 / 词表取值 ⇒ 漂）

| 文件:行 | 那个数字是什么 | 今天由什么命令产出（实跑读数） | 漂 | 有判据? | 处置建议 |
|---|---|---|---|---|---|
| `DEVELOPMENT.md:144,162` | 「工具总数 **55** / 已装模块 **11**」+ 各角色 `{'A':20,…,'H':22}` | `python -m agentflow.cli tools` ⇒ **55 / 11**，各角色与文档**逐字相同** | A | ❌ 无 | **改命令 + 观测时刻**（加一个工具就变；今天恰好没漂） |
| `DEVELOPMENT.md:144` | 「`build_registry(store=None)` 的 **50**」 | `build_registry(store=None)` ⇒ **43**；`build_registry(store=None, workspace_root=.)` ⇒ **50** | A | ❌ 无 | **把命令写全**（补 `workspace_root=.`）—— 这是**量法不完整**导致的漂，比数字本身更危险 |
| `DEVELOPMENT.md:255` | 「`read 32 / write_local 18 / none 5`」与「`external` = `none 49 / egress 4 / exec 2`」 | 我实测的是 43/50 口径的分布（`none 5 / write_local …`，`none 37 / egress 4 / exec 2`）；**55 口径的分布我没量到**（需要 store + workspace_root，`cli tools` 只打总数与角色数） | A | ❌ 无 | **改命令 + 观测时刻**，并补一条**打印分布**的命令（`cli tools` 今天不打印分布 ⇒ 这个数字**没有可复跑的量法**，是最该补的） |
| `DEVELOPMENT.md:256` | 「需审批 **21 / 55**」「`store=None` 口径是 **18 / 50**」 | 同上（未量到 55 口径） | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:68` | 「`CLAIM_FIELDS` **12 字段**声明表」 | `len(claimanatomy.CLAIM_FIELDS)` ⇒ **19** | A | ❌ 无 | **改命令 + 观测时刻**（`python -c "import agentflow.claimanatomy as c;print(len(c.CLAIM_FIELDS))"`）。**已漂**（12 → 19） |
| `DEVELOPMENT.md:1111` | §9.3 待办 14「`documents.claims` 的 **12 字段**在存储层强制」 | 同上 ⇒ **19** | A | ❌ 无 | 同上。⚠️ 这条是**待人工**项，写错会让签字的人按错的字段数走查 |
| `DEVELOPMENT.md:331` | 目录树「`verify.py` …（**71** 个 `Issue.code`）」 | AST 数 `Issue(...)` 第 4 实参去重 ⇒ **77**（`Issue` 调用点 85，其中 84 处第 4 参是字面量） | A | ❌ 无 | **改命令 + 观测时刻**。**已漂**（71 → 77）；而且它**没有单一可跑的量法**（要用 AST）⇒ 建议同时补一个 `--codes` 出口或写成「命令 + 观测时刻 + 量法说明」 |
| `DEVELOPMENT.md:1183` | FC-02 行「`verify` 的 `dangling_*` 检查集（**71 个 code** 里的 …）」 | 同上 ⇒ **77** | A | ❌ 无 | 同上 |
| `DEVELOPMENT.md:69` | 「H 的 **G1–G15** 门引擎；`GATES` 声明表 **15** 门号」 | `len(gates.GATES)` ⇒ **15** | A | ❌ 无 | **保留**（未漂），建议补判据（`len(GATES) == 15` 与 `GATE_IDS` 已由 `tests/test_gates.py` 守着 —— 那是 `src` 侧，文档侧没有） |
| `DEVELOPMENT.md:1182` | FC-01 行列举的受控词表（`REFUSAL_REASONS`/`TASK_OUTCOMES`/…） | 我实测：`REFUSAL_REASONS 10 / TASK_OUTCOMES 6 / DOWNLOAD_STATUSES 4 / SEARCH_OUTCOMES 4 / NEGATION_KINDS 4 / FINDING_KINDS 7 / DEP_KINDS 7 / DOC_KINDS 4 / EVAL_REQUIRED_FIELDS 7 / ID_COUNTERS 12` | A | ❌ 无（该行**未写条数**，只列名字 ⇒ 不漂） | **不动**（列名字而不列条数是**正确**的写法，本清单把它当正例） |
| `README.md:148` | 「linter（R001–R012；…）」 | `len(RULES)` ⇒ 12 | A | ❌ 无 | 见 §2.2 |

### 2.6 `tests/` 里"把某个计数写死"的**判据与夹具**（改 1 条用例 ⇒ 可能自伤）

| 文件:行 | 那个数字是什么 | 会不会漂 | 处置建议 |
|---|---|---|---|
| `tests/test_release_all.py:922-924,974-984` | `LIVE_BEGIN/END` 界标 + `_LIVE_LINE_RE`（`名字 = 数字`） | C | **不动**。这是"活读数"机制本体，是全仓的样板 |
| `tests/test_release_all.py:1042-1051` | `live_reading_problems`：逐键比对声明 vs 实测 | C | **不动** |
| `tests/test_release_all.py:1056-1086` | `tally_claim_problems`：全文所有 `error/warning/info` 三元组 | C | **不动**（`error` 栏刻意不比，理由在 docstring） |
| `tests/test_release_all.py:1103-1115` | `rule_claim_problems`：`R0NN–R0NN` 区间上界 + 「N 条规则」 | C | **不动** |
| `tests/test_release_all.py:1174-1188` | `_MANIFEST_CLAIM_RES` / `_MANIFEST_TABLE_RES` | C | **不动** |
| `tests/test_release_all.py:1154-1158` | 负控夹具 `text.replace("R001–R012", "R001–R011")` —— **写死了区间字面量** | **A** | ⚠️ **改成由 `rule_numbers()` 构造**（`f"R001–R{top:03d}"`），照 `F8-R11` 在 `:1287-1296` 修出来的样板。今天它靠 `R012` 这个字面量存在才能咬人：一旦规则改名/区间写法改变，`:1155` 的「夹具前提」断言先红，而**那与"判据会不会咬人"无关** |
| `tests/test_release_all.py:1143-1145,1160-1161` | `re.sub(rf"^(?m)^lint_rules_info\s*=\s*\d+", …measured+1)` / `rf"info\s*{cur}\b"` | C | **不动**（用 `measured` 构造 ⇒ 相对表述） |
| `tests/test_release_all.py:1277-1285,1292-1296` | `measured['noai_paths_glob'] - 2` / `current - 11` | C | **不动**（相对表述样板） |
| `tests/test_release_all.py:1302-1305` | `re.sub(...r"\g<1>21\g<2>", text)` —— 把「清单 glob 数」改回**字面量 21** | B | ⚠️ 半写死：`21` 是旧值。建议改成 `measured['noai_paths_glob'] - 2`（与上面同族） |
| `tests/test_release_all.py:1440-1450` | README 负控夹具 `f"**{measured['noai_paths_glob']}** 条 glob"` → **今天红** | A | ✅ **它已经咬人了**：G1 把清单从 23 加到 26、README 还是 23 ⇒ `**26** 条 glob` 找不到 ⇒ `:1446` 的「夹具前提」断言红。**修复方向是改 README（不是改夹具）**：夹具是"按实测值构造旧值"的**正确**形态，README 才是漂的那一侧 |
| `tests/test_release_all.py:1287-1291` | 那 5 行注释里的 `**不写死**` | C | ❌ **它今天违反 R009**（成对星号写进 `.py` 注释）⇒ lint `error 1`。**处置：把那两个星号去掉**（这是唯一一条让 `python scripts/lint_rules.py` 退 1 的原因，也直接让发布门第 5 项"linter 必须 error 0"报红） |
| `tests/test_coverage_gates.py:707-717,726-731,743-747` | G10 的固定夹具（`finding_id: "0000"`、`line: 12`、`verbatim_quote` …） | C | **不动**（这些是**协议形状的示例**，不是活读数） |
| `tests/test_coverage_gates.py:792-845` | G12 的 4 条夹具 | C | **不动** |

### 2.7 明确**不该改**的（历史观测 / 引文）—— 写出来免得下一个人"顺手统一"

| 文件:行 | 内容 | 为什么不动 |
|---|---|---|
| `DEVELOPMENT.md:35,36,94,98,201,794,1029-1036,1326-1327` | S1/S2 与"末次实测"快照 | 它们**证明这些门曾经报过什么**；表头已逐字声明「本表是 S2 的历史观测，任何一行都不许当当前值引用」。改它等于伪造历史 |
| `DEVELOPMENT.md:84-87,188-191` | 「今天是…」的对照段 | 已是「区间 + 观测时刻」的**合规写法** |
| `DEVELOPMENT.md:156` | §0.3 第 13 项 | 合规样板 |
| `.noai-paths:11-21,35-45,99` | 引文与"为什么不写行号"的论证 | 引文；改它=伪造引文 |
| `docs/PROPOSALS.md`、`docs/ROLE-SPECS.md`、`docs/NOAI-SUSPENSION-2026-09-25.md`、`docs/PROPOSAL-side-effect-axes.md` 里带日期/「当次」/「我实测」的读数（扫到 94 + 4 + 7 处） | 审计日志 | 它们是**当时的证据**。`G-32` 要求的是"新写的计数写成命令 + 时刻"，**不是**把历史日志重写成今天的读数 |
| `docs/PROPOSALS.md:2157`（PROPOSALS 内部 `:2995-3028` 的对照表） | 「文档数字过期」审计表 | 同上；它是"数字会漂"这件事**自己的证据** |

---

## 3. 按「改动代价 × 咬人频率」排序

**咬人频率** = （今天是否已经红）×（每次正常开发动作被咬的概率）×（是否有判据在咬，还是纯裸奔）。
**改动代价** = 要改几个文件 × 是否落禁改区 × 要不要人签 × 是否需要同时改判据本体。

| 序 | 对象 | 咬人频率 | 改动代价 | 建议动作 |
|---:|---|---|---|---|
| **1** | `DEVELOPMENT.md:134-135` + `:274-275` + `:941` + `:1208` + `:303`（`.noai-paths` 的 2 个数） | **今天已红**（4 条判据里 2 条红）；G1 每加一条登记就咬一次 | 小：只改 `DEVELOPMENT.md`（**非禁改区**）；但要**等 G1 定稿**，否则改完又被咬 | **改命令 + 观测时刻**；**先与 G1 约定口径**（`glob = 清单条目行数`，`unique = 去重路径数`） |
| **2** | `README.md:142`（glob / unique / 7 类 / 台账 16 / 欠签 32） | **今天已红**（负控夹具前提红）；README 是入口文档 | 小：只改 `README.md`（非禁改区） | **改命令 + 观测时刻**（前两数）；台账两数**交人裁决** |
| **3** | `tests/test_release_all.py:1287-1291` 的 `**不写死**`（R009） | **今天就红**（lint `error 1` ⇒ 发布门第 5 项 fail） | 极小：删 2 个星号；`tests/` **非禁改区** | **立刻改**（它是 `F8-R11` 那次"把数字改成相对量"的修复顺手引入的 —— 典型的"治漂的补丁自己引入新红"） |
| **4** | `DEVELOPMENT.md:138,1208,1231`（`noai_gate_pytest_collected = 116`） | 高：**F10 加 1 例就咬**（本次事故的本体） | 小：`DEVELOPMENT.md` 非禁改区；判据已存在 | **保留 + 观测时刻**（判据已守；不要为了躲它而删数字 —— 那会让判据"失去对象"） |
| **5** | `DEVELOPMENT.md:54`（`105 个 test_*.py` → 116） | 中高：加一个测试文件就漂；**无判据** | 小 | **改命令 + 观测时刻** + 建议给 `test_release_all.py` 加一条认「个 `test_*.py`」的判据 |
| **6** | `DEVELOPMENT.md:70`（`.noai-paths` 行被「原写」豁免） | 中：**判据结构上的已知漏口**，今天已漂 | 小（改文档）+ 中（改判据的豁免作用域） | **改文档**（把更正说明挪到下一行）+ **建议收窄 `_HISTORICAL_MARKERS` 的作用域**（这是一条**判据改进**，会动 `tests/`） |
| **7** | `DEVELOPMENT.md:331,1183`（`71 个 Issue.code` → 77）、`:68,1111`（`12 字段` → 19） | 中高：**今天已漂**，且都在"给人照着走查"的句子里 | 小 | **改命令 + 观测时刻**；顺带补一个可跑的量法（AST 计数脚本或 `verify --codes`） |
| **8** | `DEVELOPMENT.md:379,844`（`191 / 661` → 192/669） | 中高：**今天已漂**；R007 的 info 随补 docstring 变化 | 小 | **改命令 + 观测时刻**（原文已给命令，只是没把数字换掉） |
| **9** | `DEVELOPMENT.md:1110` + `README.md:353`（「13 个禁改区文件」→ 22） | 中：每次签一个字/加一条登记就漂 | 小 | **改命令 + 观测时刻**，并写清口径（台账条目 vs 清单唯一路径） |
| **10** | `DEVELOPMENT.md:144,162`（工具面 55/11/各角色） | 中：加一个工具就漂；**无判据** | 中：需要**先补一条打印分布的命令**（今天 `cli tools` 不打印 `side_effect` 分布） | **改命令 + 观测时刻**；`build_registry(store=None)` 那句要**补 `workspace_root=.`** |
| **11** | `DEVELOPMENT.md:255,256`（轴分布 / 需审批） | 中：加一个工具就漂；**今天没有可复跑的量法** | 中（要加 `cli tools --dist` 之类的出口；`cli.py` 非禁改区） | **改命令 + 观测时刻**，并把量法补上；补之前先标注"暂不可复跑" |
| **12** | `README.md:148,278`（规则区间/条数） | 中低：加一条规则才漂 | 小（改文档）或中（把 `rule_claim_problems` 的判据面扩到 README） | **改成相对表述**（「以 linter 摘要行为准」） |
| **13** | `DEVELOPMENT.md:384`（`42 个 src 文件` → 40） | 中低：加一个 src 文件就漂 | 小 | **改命令 + 观测时刻** + 写清口径（含不含 `tools/`） |
| **14** | `DEVELOPMENT.md:74`（lint 扫描 `src_py 53 / tests_py 120`） | 中低：加一个 `.py` 就漂 | 小 | **改命令 + 观测时刻** |
| **15** | `DEVELOPMENT.md:528,602,688,700,1187,1193,1215,1242,1252`（各测试文件「N 例」） | 中低：每批都在加用例 ⇒ 迟早全漂 | 小 | **改成相对表述**（「该文件的用例数以 `--collect-only` 为准」）—— 不要给 9 处各加一条判据（判据数量爆炸） |
| **16** | `DEVELOPMENT.md:155`（linter「退出码 0」） | 中低但**今天已漂**（实际退 1） | 极小 | **改相对表述**（「退出码见当次运行；`error` 栏刻意不钉」） |
| **17** | `tests/test_release_all.py:1154-1155,1302-1305`（夹具里的旧值字面量） | 中低：规则区间换写法/再加规则就自伤 | 小（`tests/` 非禁改区，但**它自己就是门**） | **照 `F8-R11` 的样板改成由 `rule_numbers()`/`measured` 构造**；改完必须证明负控仍有牙（跑一次对应测试） |
| **18** | `DEVELOPMENT.md:317,55,9`（DESIGN 份数 / data JSON / 角色规格结构） | 低 | 小 | **保留**（今天未漂）；建议顺手写成命令 |
| **19** | `gates.py:88`（注释「三道轴」vs `AXES` 4 个） | 低 | 极小（`src/` 非禁改区） | **改相对表述** |
| **20** | `DEVELOPMENT.md:276,278` + `README.md:142` 的台账两数（16 / 32 → 22 / 4） | 中：**每签一个字就漂**；判据**刻意不钉** | 中：涉及"要不要给台账计数加判据"的口径决定 | **交人裁决**：若不钉 ⇒ 至少改成命令 + 观测时刻；若钉 ⇒ 改 `manifest_claim_problems` 的覆盖面（动 `tests/`） |
| **21** | `.noai-paths:21,57,111-112` + `AGENTS.md` 正文「七类」/「第 8 步」 | 低（加一类/加一步才漂） | **最高**：**在禁改区文件里** ⇒ 2 名 reviewer 签字 + 同时改两处保持逐条一致 + 跑 `noai_gate --check-consistency` | **保留**（低收益）；若非要改，走 `NOAI-REVIEW-REGISTER.md` 流程，**且必须与 G1 的清单定稿排在一个批次里** |
| **22** | `docs/*.md` 里的历史读数（PROPOSALS 94 处等） | 零（已带日期/当次标记） | 零 | **不动** |

---

## 4. 现场事件记录：G1 的改动让 3 条门判据红了（11:49 → 11:51）

这条**不是**假设，是本次分析窗口内真实发生的：

| 时刻（+0800） | 事件 | 证据 |
|---|---|---|
| 11:49:25 | 我跑第 4 条必跑命令 ⇒ `.noai-paths` 条目 = **23**；`LIVE-READINGS` 的 23/20 与实测**一致** | `temp/G2-cmd-baseline.txt` |
| 11:50:23 | 同一命令 ⇒ **26**；`measured_readings()` 的 `noai_paths_glob/unique = 26/23` | `temp/G2-drift-probe.txt`（含 `sha256(.noai-paths)=e1aedbfaef1aad37`） |
| 11:50:57 / 11:50:58 | 台账里 `.noai-paths` 出现 `owner-1`/`owner-2` 两条「逐行走查通过」签字，scope 逐字写着「新增 `tools/coverage_zero_test.py`、`tools/run_each_test_file.py`（release-deploy）与 `tools/vocab_census.py`（auth-audit）**三条**」 | `.noai-approvals.json` 的 `entries`（我读的是盘上当前字节） |
| 11:51:00 / 11:51:01 | `AGENTS.md` 同样两条签字（清单副本同步） | 同上 |
| 11:51:32 | 我跑 `G2-measure.py` ⇒ `AGENTS.md` 清单副本条目行数 = **26**（与 `.noai-paths` 一致 ⇒ `--check-consistency` 应退 0） | `temp/G2-measure.txt` |
| 11:52:17 | 台账 `entries=22`、`reviewers_total=40`、欠签 **4** | `temp/G2-p910-probe.txt` |

**跑 `test_release_all.py` 的那 4 条文档读数判据（`-k "development_md or manifest_and_pytest or documented_readings or not_vacuous"`）⇒ `4 failed, 4 passed, 46 deselected in 20.12s`**：

```
FAILED test_development_md_linter_readings_and_rule_range_match_the_repo
FAILED test_development_md_manifest_and_pytest_counts_match_the_repo
FAILED test_the_manifest_and_pytest_count_criteria_are_not_vacuous
FAILED test_the_readme_numbers_criterion_is_not_vacuous
```

- 前两条是**正控**：`LIVE-READINGS` 里 `noai_paths_glob/unique` 过期（文档 23/20，实测 26/23）；`DEVELOPMENT.md` 散文里 5 行同样过期。
- 后两条是**负控**：它们的「夹具前提」断言要求"当前字节上是干净的"，而**前提已经不干净**（`:1274`、`:1446`）。
  注意 `:1446` 的失败形态：夹具用 `f"**{measured['noai_paths_glob']}** 条 glob"`（**26**）去 replace，
  而 README 里是 **23** ⇒ 找不到对象。**这不是判据没牙，是判据先被漂死的那一侧绊倒** ——
  与 `F8-R11` 在 `:1287-1296` 修掉的那个形态**同族但不同因**：那次是夹具自己写死了当次数，
  这次是**被对账的那份文档**没跟上。

> **给 G1 的一句话**：`.noai-paths` 从 23→26 这一步同时漂了 `DEVELOPMENT.md` 的 7 处与 `README.md` 的 1 处
> （外加 2 条负控的夹具前提）。**登记新条目的那个批次应当把这三份文档的对应数字一起改**，
> 否则每次加登记都会留下一棵红的树。

---

## 5. 落在**禁改区文件**里的数字（这些要人签）

按 `.noai-paths` 今天的 26 条条目逐条比对，本清单涉及的**文档/清单类**数字里只有下面这些落在禁改区：

| 禁改区文件 | 行 | 数字 | 类别 | 为什么它受保护 | 改动前置条件 |
|---|---|---|---|---|---|
| `.noai-paths` | `:21` | 「**七类**」（分组数） | `auth-audit` | 它是**清单本体**：「改它等于改『保护范围』本身」 | 人编写或人逐行走查 + **2 名 reviewer** 批准；**同时**改 `AGENTS.md` 副本且逐条一致；跑 `python scripts/noai_gate.py --check-consistency`（须退 0） |
| `.noai-paths` | `:57` | 「**第 1 类和第 3 类**」 | `auth-audit` | 同上 | 同上 |
| `.noai-paths` | `:111-112` | 「发布门**第 8 步**」「两道子门之一/之二」 | `release-deploy` | 这两条是 `release_all` 的两道子门**自身的登记**，改理由里的步序号 = 改登记内容 | 同上（另外这两条是 G1 本批刚加的，**签字 scope 只覆盖"新增三条"**，改它们要**重新签**） |
| `AGENTS.md` | 清单正文「上述**七类**…下面这**七类**」 | 7 | `auth-audit` | 副本受保护的理由逐字：「副本若能随便改，『两处一致』就失去了意义」 | 同上 |
| `AGENTS.md` / `.noai-paths` | 正文里的「**2 名 reviewer**」 | 2 | `auth-audit` | 它是 `scripts/noai_gate.py::REQUIRED_APPROVALS_ON_HIT = 2` 的**散文副本** | 这是**常量**（不漂，C 级）—— **不要为了"统一数字写法"去动它** |
| `.noai-approvals.json` | 全文的 `entries` / `sha256` / `reviewers` | 22 / 22 / 40 | `auth-audit` | 「改它等于改审计记录本身」 | 只能由 `noai_gate --baseline`（只登记）或**人签字**写入 |
| `scripts/noai_gate.py` | `REQUIRED_APPROVALS_ON_HIT` / `MIN_INDEPENDENT_AUDITORS` / `MIN_DISTINCT_DIMENSIONS` | 常量 | `auth-audit` | 「改它等于改『一个批准算不算数』」 | 人签 |
| `scripts/lint_rules.py` | `RULES` 的条数（12） | 常量 | `auth-audit` | 「改它等于改『哪一类形态算缺陷』」 | 人签。⚠️ **注意**：`DEVELOPMENT.md` / `README.md` / `docs/*.md` / `tests/*` **都不在清单里**（我逐条比对过 26 条条目）⇒ 上一节 20 项里的**前 20 项都是 AI 可改的**；**只有第 21 项（`.noai-paths`+`AGENTS.md` 的"七类"/"第 8 步"）与本节这些常量需要人签** |

> ⚠️ **一条口径提醒**：`DEVELOPMENT.md:941`/`:1208` 讲的是"哪些路径是禁 AI 区"，按 `.noai-paths` 的
> **字面 glob** 它们**不在**保护面里。但按 FC-27 的**平移原则**，"禁改区清单的计数"接近
> `eval-criteria`（"口径就是那个数字"）⇒ 有人在读这些数字来做批准决定。**是否要把"讲禁改区的计数"
> 也纳入保护面，本身是一个需要人裁决的口径问题**，我不能替所有者决定。

---

## 6. 我核实不了的部分（如实列出）

1. **`test_release_all.py` 里那 4 条判据的完整失败清单**：我通过 `G2-drift-probe.py` 逐函数调到了
   `live_reading_problems` / `rule_claim_problems` / `tally_claim_problems` / `manifest_claim_problems` /
   `pytest_count_claim_problems` 的返回值（`temp/G2-drift-probe.txt`），但 **`readme_number_problems`
   我没有单独调**（只在 pytest 输出里看到它的负控夹具前提红）。
2. **全量 `python -m pytest -q` 的当次读数**：工单**明令禁止**跑全量 ⇒ 我没有跑。
   因此 §2.1 里所有「N 例 / N passed」的**实际是否过期**我只对 `tests/test_noai_gate.py`（116）
   与 `tests/` 文件数（116）做了实测；其余 9 处**只判定"会不会漂"，没有判定"今天是否已漂"**。
3. **`cli tools` 的 55 口径下的 `side_effect` / `declared_external` / 需审批分布**：我只量到
   `store=None`（43）与 `store=None, workspace_root=.`（50）两个口径的分布
   （`none 5 / write_local …`、`none 37 / egress 4 / exec 2`）。`cli tools` 今天**不打印分布**，
   所以 `DEVELOPMENT.md:255-256` 那些数**今天没有可复跑的量法**。
4. **`verify.py` 的 Issue.code「口径」**：我用 AST 数 `Issue(...)` 第 4 个实参的字面量（85 个调用点、
   84 处字面量、去重 **77**）。文档写 71 —— **差额可能**来自"只在某一档里出现的 code"或
   "我数的是调用点而不是 code 集"，也可能就是漂了。**这一格建议由人核定口径**。
5. **`README.md:160` 的「`cancellation.py`（4 条规则）」**：我没找到这个"规则数"的机器可读来源
   （`cancellation.py` 里的规则表口径不明）⇒ **未复算**。
6. **`.noai-paths:111-112` 的「第 8 步」**：我没跑 `tools/release_all.py`（它会拉起全部门，
   工单禁止）⇒ `release_all` 今天有几步我没有实测。
7. **`docs/PROPOSALS.md` / `ROLE-SPECS.md` 里那 98 处数字是否"当次"**：我按日期/「当次」/「我实测」
   之类记号把它们整类判为**历史观测**（处置=不动）。**这个判定是启发式的**：其中可能有几处
   作者本意是"当前值"。逐条核需要 98 次翻上下文，超出本批的读预算。
8. **G1 的最终清单**：我读的是 **11:52:17 的盘上字节**。G1 若在本文件写完后继续改
   `.noai-paths`/`AGENTS.md`，§2.3 的所有行号与"23/20/26/23"都会再漂 ⇒ **处置这批数字时必须以
   G1 定稿 + `--check-consistency` 退 0 为前提**。

---

## 7. 给处置者的最短路径（把 22 条压成 5 步）

1. **先修红**（今天就能做，`tests/` 与 `docs/` 非禁改区）：
   删 `tests/test_release_all.py:1287-1291` 注释里的成对星号（消 lint `error 1`），
   并把 `DEVELOPMENT.md:155` 的「退出码 0」改成相对表述。
2. **等 G1 定稿，再一次改齐 `DEVELOPMENT.md` + `README.md` 的 `.noai-paths` 计数**
   （`:134-135`、`:274-275`、`:303`、`:941`、`:1208`、`:70`、`README.md:142`）——
   每处都写成「命令 + 观测时刻」。这一步做完，`test_release_all.py` 的 4 条红应该全绿。
3. **把 6 处"已漂但无判据"的数字改成命令 + 观测时刻**：
   `:54`（test 文件数）、`:331`/`:1183`（Issue.code 数）、`:68`/`:1111`（CLAIM_FIELDS 字段数）、
   `:379`/`:844`（docstring 比例）、`:384`（src 文件数）、`:1110`/`README.md:353`（禁改区文件数）。
4. **补两条"便宜的量法"**（否则第 3 步没有可复跑的命令）：`verify.py` 的 code 计数出口、
   `cli tools` 的分布出口。
5. **把两个需要人拍板的口径单独列给所有者**：
   ① `DEVELOPMENT.md:276/:278` 的**台账条目数 / 欠签**要不要并入判据面；
   ② `.noai-paths`/`AGENTS.md` 里「七类」「第 8 步」这类**禁改区内的数字**要不要一并规范
   （要签 2 名 reviewer）。
