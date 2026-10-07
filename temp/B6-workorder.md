# B6 工单：文档与数字（`G-30`/`G-31`/`G-32` · `X-5` · `G-15` · `G-16` · `P-16` · `P-11` · `G-28` · `X-8`）

> 执行者：文档/登记子智能体。核验者：主控。
> 前置：**B3 / B4 / B5 都已落地**（本批要把它们改出来的真值写进文档，不许提前写）。
> 铁律（`draft/25` §6 的 D-4）：**文档里每一个"`<命令> ⇒ <数字>`"都必须能被那条命令在
> 文档声称的环境下复现**；做不到就改成"**区间 + 观测时刻**"或删掉。

## 0. 一律照做的测量纪律

1. **不许抄旧数字，也不许抄我的转述**：每个数字都要你在**当前盘上真跑一次**那条命令，
   把"命令 + 原始输出 + 观测时刻"贴进证据。
2. **计数类数字写成"区间 + 观测时刻"**（`G-32`）：例如
   "`docs/PROPOSALS.md` 行数 4391–4405（2026-09-26 03:1x 观测）"。
   区间来自"同一观测窗口内重复两次"（并发仓库里的真实波动），**不许**写成单个定值。
3. 文件里的**代码块/命令**必须与盘上一致；引用行号的地方**一律改成符号名**
   （行号几十分钟就漂，这是本仓库实测过的）。
4. 只改这些文件：`agentflow/DEVELOPMENT.md`、`agentflow/README.md`、
   `agentflow/docs/INDEX.md`、`agentflow/docs/ROLE-SPECS.md`、`agentflow/docs/` 下的
   各类清单/矩阵文档、`draft/24-收官核验包（签字前）.md`、`draft/25-...md` 的 §10。
   **不要碰 `src/`、`scripts/`、`tests/`**（那是代码批次的地盘）。
5. 改完必跑：`python -m pytest tests/test_proposals_register.py tests/test_role_specs_complete.py -q`、
   `python tools/verify_role_specs.py`（退出码 0）、`python scripts/lint_rules.py`（`error 0`）。

## 1. 逐条

### `G-30`：`DEVELOPMENT.md` / `README.md` 的"实测数字"整批过期（同一文件内还互相打架）
- 把两文件里每一个"实测数字"逐个**重跑复算**；打架的两处**必须做出选择并写明依据**
  （选择标准：能被一条命令复现的那个；不能复现的一律降级为"区间 + 观测时刻"或删除）。
- 特别检查 `DEVELOPMENT.md` 第 187 行那条 `side_effect` 分布（`network` 已从词表删除
  ⇒ 它现在必然是错的）。

### `G-31`：`DEVELOPMENT.md` 说 `usage_ledger`"仍是零写入方" —— 早已接线
- 按盘上事实改写；并加一条**判据指向**（哪个函数是写入方、哪条命令能看出来）。

### `G-31b`（主控实测新增，同族）：`DEVELOPMENT.md` 说 `-m network`"S2 未跑 / 仍未关" —— **已经跑绿了**
- 位置：`DEVELOPMENT.md` 第 **1113** 行 `| 12 | 真实联网端到端 | S2 未跑 -m network | ⚠️ 仍未关 |`。
- 事实（主控实测，2026-09-26T02:42:12→02:42:41）：`python -m pytest -m network -q -p no:cacheprovider`
  ⇒ **`8 passed, 1873 deselected in 28.42s`，exit=0**（原始输出 `temp/pytest-network-run1.txt`，
  采集清单 `temp/network-collect.txt`；全部 8 条在 `tests/test_providers_online.py`）。
- ⇒ 把那一行改成**如实**：8 条已跑绿（crossref ×3 / openalex ×3 / precise 相关性 / wellformed 候选），
  并**同时写明它证明什么、不证明什么**（只证明 crossref+openalex 这条路；Semantic Scholar 实测 429、
  github 的 TLS 证书链验证失败 ⇒ easyocr 模型下不来；见 `temp/network-and-key-status.md`）。
- 这一条与 `G-30` 同族（**把"没查成"过久地挂在墙上**也是一种失真）。

### `G-32`：计数类数字在并发仓库里给不出定值
- 这条是**方法**不是某一处：把所有"行数/条数/命中数"改成"区间 + 观测时刻"，
  并在一处（`DEVELOPMENT.md` 的口径节）写下这条规矩本身，注明它是 `D-1.6` 的要求。

### `X-1`：发布检查**每跑一次就改写一批被跟踪文件**（主控已实测，比我原先写的范围更大）
- 原始定义在 `draft/25` **§5**（不是 `PROPOSALS.md`）——**这一条你要去读原文**。
- 主控实测补充（2026-09-26T02:52）：`python scripts/lint_rules.py` **不写** `.release-lint.json`
  （sha256 不变）；**`scripts/release_check.py` 的 lint 项写**（`B625A5B9…` → `E25FCCA4…`）
  ⇒ 我原先的落点判断**错了一半**，以实测为准（`temp/X1-lint-side-effect.txt`、
  `temp/X1-releasecheck-linter.txt`）。
- 另有**主控新观测**：B3 的逐文件门跑到一半时 `agentflow/data/events.jsonl`（03:15:50）与
  `agentflow/demo/run/data/*`（03:12:49）被重写；复核 `agentflow/data/` 有 **17 个被跟踪文件**、
  不在 `.gitignore`，而 `git status --porcelain -- agentflow/data` **为空** ⇒ 只有 mtime 变、内容未变。
  **未核实**：是哪条用例写的、是否为"同内容覆盖"。请顺手核一下并按这个口径写。
- **判据照原文**：负控 = **连跑两次** `release_all` ⇒ `git status` 除预期产物外无 `M`。

### `X-2`：仓库根残留 `pytest-of-unknown/`、`.pytest_cache/`（主控**漏列**，本批补上）
- 原文在 `draft/25` §5。成因：pytest 的 basetemp 用户名解析失败 ⇒ 落在 **cwd = 仓库根**。
- 修法：在 `conftest.py` 里把 basetemp 显式钉到系统临时目录（`--basetemp` 或 `tmp_path_factory`），
  并把两者 `.gitignore`。**判据**：跑一次全量 ⇒ 仓库根**不新增目录**（贴跑前跑后的目录清单差分）。

### `X-7`：`temp/` 的卫生说明（小，但有交付价值）
- 交付一份 `temp/README.md`：说明哪些能删、哪些是**证据物必须留**
  （Lean/Mathlib：`mathlib-pinned2` ~3.6 GB、`lean470` 854 MB；以及各批 `*.bak-*` 的回滚用途）。
  **只写清单与理由，不删任何东西**（删 = 不可逆）。

### `X-5`：清单 glob 数（19→实测）与台账条目数（14→实测）的**差集没有口径**
- 原文在 `draft/25` §5：要定"**glob 数 / 台账条目数 / 7 类**"三数并列的口径，
  并**核实差集是哪几条**（原文给的候选：`src/agentflow/release_check.py`（登记时不存在）、
  `.noai-paths`、`AGENTS.md`、`.noai-approvals.json`（不许自批）、以及**一处重复 glob**）。
- ⚠️ 主控实测现状（2026-09-26T02:47，`temp/D5-approvals-state.md`）：**清单 glob 21（唯一 18）/
  台账条目 16 / 欠签 32 / stale 0** ⇒ 原文的 19/14 与 `D-4.2` 的 19/14/7 **都过期**。
- **交付**：三数并列的口径写进 `README.md` + `DEVELOPMENT.md` + `draft/25` 的 `D-4.2`，
  并给出差集清单（逐条说明为什么它没有台账条目）。
- **判据**：口径表里的条数与 `--check-consistency` / `.noai-paths` / `.noai-approvals.json`
  的实测**逐条一致**（把三条命令的原始输出贴上）。

### `G-15`：`ROLE-SPECS.md` 的一条"没能核实"已经过期（它说 `tests/test_noai_gate.py` 不存在）
- 改成盘上事实（该文件存在），并在证据里贴 `Test-Path` / `Get-Item` 的原始输出。

### `G-16`：FC 覆盖矩阵自相矛盾（同一条 FC-05/17/19 在两处是两个互斥状态）
- **一条 FC 只能有一个状态**；两处冲突的，逐条判"哪个是事实"并给出判据
  （命令/文件/符号），不许两处都留着让读者自己猜。

### `P-16`：`DEVELOPMENT.md` §4.3 第 1 项曾是一句假承诺 + 两处漂移
- 按实现事实改写（实现侧已在 B2/B3 落地）；"六件套"到底哪几件有门、哪几件靠 census，
  **逐件写明**，并给"怎么验"的命令。

### `P-11`：`release_check.py` 的八项不含验收测试
- **先核实**（读 `scripts/release_check.py` 数它跑了几项、分别是什么，贴出来），
  再决定：(a) 把验收测试并进 `release_check` 的第八项；或 (b) 文档从此**不再声称**它含验收，
  而是明确写"验收由 `release_all` 的 `acceptance` 步承担"。
  **主控口径**：选 **(b)** —— 理由是 `release_all` 已经有独立的 `acceptance` 步（实测 pass），
  在 `release_check` 里再跑一遍会让同一件事有两个落点（FC-03 的反面）；
  `release_check` 自己是**禁改区**，`(b)` 只改文档，代价最小且不撒谎。
  **备选 (a) 要写进证据并说明"已否决的理由"**。

### `G-28`：发布门实测 FAIL 而三处文档把它写成"基本全绿"
- 改成**如实**：现在 `release_all --since 4293989` 的总判定是 `FAIL`，
  且 **`release-check` 那一项的红是"禁改区命中待 2 名 reviewer 签字"**（这是**制度要求**，
  不是代码坏）。把这句话逐字写进文档，并给出复现命令与观测时刻。

### `X-8`：`draft/22` §12 的排期表**已过期**（原文在 `draft/25` **§5**，**不是** `PROPOSALS.md`）
- 症状：表里仍写着"`43ce64a6` 正在写 / 同文件 ⇒ 排其后"这类**在飞**状态，而三个工作包**都已收工**。
- 交付：重写 §12 的"排其后"那一列 ⇒ 现在**没有文件级互斥**，只留"人审按批次付"。
- **判据（原文给的负控）**：表里**不再出现"在飞"字样**（贴 `rg` 的原样输出）；
  并且把 B3 之后真实存在的约束写清（不可逆操作要备份、禁改区改动要人审）。

## 1b. 登记子智能体**没做完**的部分（已交接给你；它把锚点留好了）

它做完的是：`PROPOSALS.md` 的 `P-13` B3 块 / `P-15`/`P-19`/`P-20`/`P-6` 状态 / `G-19` 战果 /
`G-46`/`G-47`/`G-48` 三条新条目 / `ROLE-SPECS.md` 的几处过期数字与一条口径说明。
**它明确没做完、要你接手**（详见 `temp/REGISTER-round-B3.md`）：

1. **`draft/22` §12.32**（B3 的差分表 + 状态 + B4/B5/B6/B8 剩余清单；锚点：文件末尾 `### 12.31` 之后）。
2. **`draft/25` §10.1**（"新发现"表加 `G-46`/`G-47`/`G-48` 三行）与 **§10.2 的数字变化表**
   （登记册区间 → `P 26 / G 48 / N 10`；台账 16 条 / 欠签 32 / 清单 glob 21（唯一 18））。
3. **词表三处**：`docs/DESIGN-TOOLS.md` 第 49/54/63/67 行、`README.md` 第 38 行、
   `docs/TOOLBOX-DRAFT-roles.md` 第 81/82/107 行（把 `network` 改成两根轴）。
   ⚠️ `README.md:38` 的"**唯一**联网角色"：**先核实再写**（登记子智能体**没核实所以没改**，
   它如实登记了这一点）。核实的口径 = 跑一次真实的 `build_registry` 数 `external != "none"` 的角色集合，
   把命令与原始输出贴进证据；核实不出来就写"未核实"，**不许**照抄"唯一"。
4. `docs/ROLE-SPECS.md` 里**其余**过期实测数字（它只改了几处，**没有**声称全改完）。
   **逐个用真跑一次的命令复算**（别手工推算）。

### ⚠️ 三条由登记子智能体**如实更正**的表述（你必须照它更正后的口径走，并写进证据）

1. **`network` 的"4 个"是迁移前的数**：今天真值 **0**（四个工具已迁到 `egress`）。
   任何写"4"的地方要标注"B3 迁移前"，写"0"的地方要给命令。
2. ⭐ **`50` 与 `55` 是**两个口径**：`build_registry(store=None)` 与"含 store 的完整装配"
   工具条数不同（登记子智能体实测 `store=None` ⇒ 50）。**文档里每一个工具条数都必须写明
   它对应哪条装配命令**，两种口径**不许互相替换**（这是 `X-5` 同族：数字没有口径就是噪声）。
3. 它的实测分布（`store=None`，观测 03:2x，**你复算后以你的为准**）：
   全局 `read 30 / write_local 15 / none 5 / network 0`；
   `external none 44 / egress 4 / exec 2`；`H n=22 {read 17, none 5}` 且 `check_formal` **不在 H**。

## 1c. 三条**待登记/待写清**的小项（登记子智能体已停，交给 B6）

1. **`P-23` 口径更正**（证据 `temp/B5a-evidence.md` §1.2.4）：`survey` / `lemma` / `dataset`
   **不是 `dead`**；原实现 `RESERVED_VALUES` **只在给 dead 分栏时被查** ⇒ 登记一个"不死的"值
   会在输出里**查无此条**（比静默豁免更糟），现已改成"按登记表原样打印 + 栏一附"。
   另：`capabilities:UNKNOWN_SIDE_EFFECT` **不是词表取值**（模块级常量）⇒ 不许登记为"预留"
   （**主控工单写错了**，一并记进条目）。
2. **`G-24③` 口径更正**（同证据 §1.3.1）：`cancellation.py` docstring 里的 `"user"`
   **是代码里真实存在的**（`G-24` 说"代码里根本没有" —— **登记册又错一条**）。
3. **新条目（编号由你按纪律定）**：**`evidence_of()` 的 `proved` ↔ 工具层契约的 `verified`
   是同一个量、跨两层两个名字**。它不是缺陷，但是真实陷阱 —— **主控自己在写 `G-18` 的探针时
   就踩了**（按工具层的名字去读底层返回值，读成 `None`；证据 `temp/VERIFY-B8a-G18.md` 的"我错了两次"表）。
   处置：在 `formalgw.evidence_of` 的 docstring 或 `DEVELOPMENT.md` 里写清两者的对应；
   若你判断值得单列编号，按 `G-45`/`G-47` 同族登记（**并说明与它们的关系**）。

## 2. 交付物

1. 文档改动；
2. `D:\Incubator\temp\B6-evidence.md`：逐条"命令 + 原始输出 + 观测时刻"、改前改后对比、
   以及**你推翻了主控/文档哪一处表述**（若没有就写"没有"）；
3. 回复 ≤25 行摘要（含 `D-4` 三项的逐项状态）。
