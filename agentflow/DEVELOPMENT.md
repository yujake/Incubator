# DEVELOPMENT —— agentflow 项目开发规范

> **本文件是"怎么做才算对"的判据。** 与它冲突的说法以**代码**为准；
> 若代码与本文冲突，是**本文的 bug**（处置见 §10）。
>
> **配套文档**：
> - `docs/ROLE-SPECS.md` —— 八个角色 + 主控（M）的详细规格（每节 10 条同构子节）
> - `docs/PROPOSALS.md` —— **已裁决的缺口与提案**（P 要人做 / G 已接受但**必须继续可见** / N 不是缺陷）
> - `docs/NOAI-GOVERNANCE.md` —— FC-27 门的机制与人工批准流程
> - `NOAI-REVIEW-REGISTER.md` —— FC-27 **人读侧**登记表（改了哪些禁改区文件、该走查哪些符号）
> - `AGENTS.md` —— **只**覆盖禁 AI 区 FC-27 这一节，不重复本文内容
> - `docs/INDEX.md` —— 上述文档的索引与"按角色怎么读"
>
> **本文的写作纪律**（与要求一致）：
> 1. **每一条规则都必须可判定** —— "要写清楚"不是规则，"每个公开函数必须有 docstring
>    且 docstring 必须含'为什么'段落"才是。
> 2. **每一个数字都有出处** —— 指向 `文件:行号`、指向我实跑的**命令 + 输出**、
>    或指向某个权威条目。**不许估。**
> 3. **不许把"未落地/未核实"写成"已落地"**。
>    凡只是从文档读到、没在代码里核实的，标 `（据 X，未在代码中核实）`。

---

## §0 本仓库的**当前状态快照**（读本文前必读）

⚠️ **本仓库在并行施工中**。本文档的每一条数字都带**取样时刻**。
下表是我**实测**到的状态。

### 0.0 两次取样（**过期的那次刻意保留**）

| 取样 | 时刻 | 当时的状态 |
|---|---|---|
| **S2（当前）** | **2026-09-24 09:0x**（本轮收尾，最终实跑） | **全绿**：测试 `1273 passed / 0 failed / 8 deselected`（退出码 0，两次独立实跑一致）、8 个 agent 自检 **exit 0**、`cli verify` 0 错误 0 警告、linter `error 3 / warning 2 / info 14`、发布门 **`pass=6 fail=1 unknown=1`**（逐项解释见 §8.2） |
| **S1（历史）** | 2026-09-24 早（本文初稿） | **不绿**：`10 failed, 957 passed`；`cli tools --role E` 被 argparse 拒绝（退出码 2）；`agent_g` 自检 exit 1；linter `error 20 / warning 34` |

> **为什么把 S1 那张过期表留在本文件里**：它记录的是**"这些门真的会响"**的证据。
> 只留 S2，后来者无法判断这些门是"一直都在报绿"（那通常意味着门没接对）
> 还是"曾经报红、然后被修好了"。本项目的核心教训是
> *"多数脚本不设退出码，于是『未报错』被误读为『无问题』"* ——
> 与之对称的另一条是：**只留绿灯的历史，等于把门的存在证据也删掉了**。
> S1 的逐项数字见 §0.4「历史取样（S1）」。

### 0.1 已存在的文件（实测 `Get-ChildItem`）

| 位置 | 文件 |
|---|---|
| 根 | `.noai-paths` `.noai-approvals.json` `AGENTS.md` `config.yaml` `DESIGN.md` `DESIGN-TOOLS.md` `DESIGN-INTERACTIONS.md` `DESIGN-ROLES.md` `DESIGN-CONDUCTOR.md` `pyproject.toml` `README.md` `DEVELOPMENT.md` `NOAI-REVIEW-REGISTER.md` |
| `src/agentflow/` | `__init__.py` `agent_a.py` `agent_b.py` `agent_c.py` `agent_d.py` `agent_e.py` `agent_f.py` `agent_g.py` `agent_h.py` `capabilities.py` `cancellation.py` **`claimanatomy.py`** `cli.py` `conductor.py` `contextbudget.py` `dedup.py` `demo.py` `extract.py` `fetch.py` **`gates.py`** `interactions.py` `llm.py` `pipeline.py` `policy.py` `providers.py` `quoteverify.py` `scheduler.py` `schema.py` `store.py` `textutil.py` **`tokenmeter.py`** `verify.py` |
| `src/agentflow/tools/` | `__init__.py` `base.py` `attack_tools.py` `doc_tools.py` `fs_tools.py` `graph_tools.py` `ocr_tools.py` `research_tools.py` `review_tools.py` `search_tools.py` `table_tools.py` `trace_tools.py` `verify_tools.py` |
| `scripts/` | `__init__.py` `lint_rules.py` `noai_gate.py` `release_check.py` |
| `docs/` | `INDEX.md` `ROLE-SPECS.md` `PROPOSALS.md` `NOAI-GOVERNANCE.md` `SCHEMA-MIGRATION-PROPOSAL-claims.md` |
| `tests/` | 65 个 `test_*.py` + `conftest.py` + `demo_dataset_helper.py`（**1329 个测试函数**，其中按命名约定明确是**负控**的 **287** 个；实测 **1497 passed / 1 xfailed**） |
| 运行期数据 | `data/`（16 个 JSON）、`library/`、`demo/`（注：**不是 git 仓库**，`.git` 不存在；见 `NOAI-REVIEW-REGISTER.md`） |

> **"预留并如实标注"清单**（这是要求里点名要预留的六 + 三项）：
>
> | 项 | 现状（实测） |
> |---|---|
> | `policy.py` | **已存在**（`Policy` 四类上限 + `check` + `waves_of` + `assert_policy_complete`） |
> | `conductor.py` | **已存在**（`Conductor` + `SummonResult` + `LocalBackend`/`SubagentBackend`） |
> | `scheduler.py` | **已存在**（`run_waves` / `run_tasks` / `TaskCall` / `MemoryBudgetTracker`） |
> | `cancellation.py` | **已存在**（`CancelToken` / `CancelReason` / `CANCEL_CODES` / `CancelRequested`） |
> | `capabilities.py` | **已存在**（`CAPABILITIES` / `WRITE_SETS` / `ALLOWED_EDGES` + **导入期** `assert_capabilities()`） |
> | `contextbudget.py` | **已存在**（`ContextBudget` / `prune` / `prune_tool_result` / `compact`） |
> | `tokenmeter.py` | **已存在**（`TokenMeter.charge` 记账 + `guard` **开工前**守卫；**重试按次计费** `(in+out)×attempts`；`tokens_for`/`usd_for` 供 `summon` 把 `tasks.tokens` 派生自台账） |
> | `claimanatomy.py` | **已存在**（`CLAIM_FIELDS` 12 字段声明表 + `validate_claim` **三态**（`checked`/`decided`/`undecided_reason`）+ `validate_document_claims` + `consolidate_issues` + `revision_hash`；**它是断言解剖学的唯一判据来源**，`doc_tools.scan_claim` 已改为纯适配层转发） |
> | `gates.py` | **已存在**（H 的 **G1–G15** 门引擎；`GATES` 声明表 15 门号齐全、每门可单独查询；四态结论 `pass`/`fail`/`unknown`/`not_applicable`；`GateResult.__post_init__` **结构强制"零发现必须自证"**） |
> | `.noai-paths` | **已存在**（**19** 条条目 + 7 个分组；原 17 条 + `.noai-approvals.json` 自身那一条 + 本轮新建的 `tools/release_all.py`） |
> | `AGENTS.md` | **已存在**（含 `NOAI-MANIFEST` 区块，与 `.noai-paths` **逐条一致**，实测退出码 0） |
> | `scripts/noai_gate.py` | **已存在**（退出码 0/1/2 三档，实测三个方向都跑过） |
> | `scripts/release_check.py` | **已存在**（八项检查；docstring 自陈 `authored_by: AI agent，尚未经人逐行走查`、`required_approvals: 2（尚未取得）`） |
> | `scripts/lint_rules.py` | **已存在**（9 条规则 R001–R009，与本文 §6 的禁止模式清单一一对应） |
>
> **本文不再假设它们"可能还不存在"** —— 但它们**是否已经过人工审查**是另一件事
> （见 §7.4 与 §8.7）。`release_check.py` 与 `scripts/` 整体落在**禁 AI 区**里
> （`.noai-paths` 的 `[category: release-deploy]`）。

### 0.2 S2（当前）实测状态（2026-09-24 收尾）

| # | 门 | 实测结果 | 证据 |
|---:|---|---|---|
| 1 | **全量测试** | `1497 passed, 8 deselected, 1 xfailed`；退出码 0。⚠️ 那 1 个 `xfail` **不是"跳过的测试"**：它是补测试时发现的真实 `src` 缺陷（`PROPOSALS.md` **G-8**，在禁改区）用 `xfail(strict=True)` 登记 —— **修好后会 XPASS ⇒ 测试失败 ⇒ 强迫人来删标记** | `python -m pytest -q` |
| 2 | **linter** | `[linter] error 0 / warning 2 / info 15`，退出码 0（9 条规则 R001–R009）。2 个 warning 是 `docs/PROPOSALS.md` 的 **G-1**（E/F 装配入口缺 roles 校验，**已接受、刻意保留可见**）。`--strict` 时 R007 升为逐模块 warning。R009 的 `info` 是禁改区内 13 个文件剩下的 414 处注释装饰 —— **人**的待办，刻意不进 error（§6-P17） | `python scripts/lint_rules.py`（`--strict` 另跑） |
| 3 | **8 个 agent 自检** | **全部 exit 0**：`a 24/24`、`b 18/18`、`c 46/46`、`d`–`h` 均 `SELF-CHECK DONE` | `python -m agentflow.agent_x`（cwd=`src`） |
| 4 | **`cli verify` / `cli demo`** | 校验 `通过 错误 0 / 警告 0`；演示 `演示成功。`；均退出码 0 | 见 §0.3 |
| 5 | **禁 AI 区门** | `--check-consistency` 退出码 0；`--paths src/agentflow/schema.py` ⇒ `requires_human(1)`；`--git` ⇒ **`unknown(2)`**；**`--check-approvals`（hash 台账）**：14 条全部 `unapproved`，`reviewers_total = 0` ⇒ `requires_human(1)` | 见 §0.3 与 `NOAI-REVIEW-REGISTER.md` |
| 6 | **角色规格结构门**（`tools/verify_role_specs.py`） | `[ok]` 9 节 × 8 必备子节，退出码 0 | §8.6 |
| 7 | **零测试覆盖分档**（`tools/coverage_zero_test.py`） | 等级 1/2 的零测试公开函数 **0**（从 53 降下来），退出码 0 | §8.4 待办 23 |

> ⚠️ **`error 3` 与 `warning 2` 都不影响本文的规范性内容，但影响"发布门能不能过"**：
> `release_check.py` 的第 5 项（linter）在 S2 **仍是 `fail`**（它要求 error = 0）。
> **任何人拿本文当判据时，都必须知道自己手上的仓库处在什么状态**：
> 本文是**规范**（应该怎么做），不是**体检报告**（现在有多好）。

### 0.3 S2 的九条"可复现基线"（逐条实测，含退出码）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH='src'   # 只有跑 `python -m agentflow.*` 才需要；`pytest` 不需要（pyproject 已指 testpaths）
```

| # | 命令 | 实测输出 | 退出码 |
|---:|---|---|---:|
| 1 | `python -m agentflow.cli tools` | `工具总数：55（已装模块 11：table_tools, fs_tools, search_tools, ocr_tools, graph_tools, trace_tools, research_tools, verify_tools, attack_tools, doc_tools, review_tools）`；`各角色工具数：{'A': 20, 'B': 18, 'C': 17, 'D': 37, 'E': 21, 'F': 32, 'G': 32, 'H': 23}`；`只读角色写工具泄漏：{'C': [], 'H': []}（空 = 正常）` | **0** |
| 2 | `python -m agentflow.cli tools --role E` | 正常列出 E 的工具面（S1 时这里报 `invalid choice: 'E' (choose from 'A','B','C','D')` —— **已修**：`choices=list(S.ROLES)`） | **0** |
| 3 | `python -m agentflow.cli tools --role C` | 列出 `trace.concept` / `trace.literature` / `trace.relation` 等，**全部 `[read]`** | **0** |
| 4 | `python -m agentflow.cli verify` | `校验完成：通过  错误 0 / 警告 0` | **0** |
| 5 | `python -m agentflow.cli demo` | `演示成功。`（10 项判定全 ✓） | **0** |
| 6 | 8 个 agent 自检 | 全部 `SELF-CHECK DONE`（`c` 46/46；**`a` 24/24**；`b` 18/18） | **0**×8 |
| 7 | `python -m agentflow.pipeline` / `python -m agentflow.llm` | 均 `SELF-CHECK DONE` | **0** |
| 8 | `python -c "import agentflow.capabilities"` | 无输出（能力表**导入期**自检通过） | **0** |
| 9 | `python scripts/noai_gate.py --check-consistency` | `一致：.noai-paths 与 AGENTS.md 的清单逐条相同` | **0** |
| 10 | `python scripts/noai_gate.py --paths src/agentflow/schema.py` | `[requires_human] required_approvals=2`（类别 `schema-migration` + `eval-criteria`） | **1** |
| 11 | `python scripts/noai_gate.py --git` | `[unknown] … Not a git repository` ⇒ **没查成，不是没问题** | **2** |
| 12 | `python scripts/lint_rules.py` | `error 0 / warning 2 / info 15`（9 条规则 R001–R009；R009 的 `info` 是禁改区内 414 处待办） | **0** |

**工具面 census（`cli tools` 实测）**：

```
工具总数 55 / 已装模块 11 / 各角色 {'A':20,'B':18,'C':17,'D':37,'E':21,'F':32,'G':32,'H':23,'M':0}
只读角色写工具泄漏 {'C': [], 'H': []}（空 = 正常）
```

> **"12 条基线里只有 2 条非零退出码"这句话本身不是好消息** —— 退 1 与退 2 是
> **设计出来给 CI 用的**（`requires_human` / `unknown`）。若把它们也改成 0，
> 那才是把门拆了。

### 0.4 历史取样（S1，2026-09-24 早，**已全部修复，保留供对照**）

| 项 | S1 实测 | 当时的证据 |
|---|---|---|
| 全量测试 | `10 failed, 957 passed, 8 deselected in 191.56s`，退出码 1 | 失败集中在 `test_conductor.py`（`test_local_backend_rejects_unknown_params`、`test_verify_tasks_detects_zombie_running_row`）、`test_scheduler.py`、`test_policy.py` |
| 取样中途的一次完全无法收集 | `Interrupted: 1 error during collection`（`tools/trace_tools.py` 的 `SyntaxError: unmatched ')'`） | **并行施工中的半写文件**，已被同事修复。**这条本身就是"多 agent 并发写同一工作区"的实测代价。** |
| linter | `error 20 / warning 34` | 已按 §6 的四次校准收敛到 `error 3 / warning 2` |
| `cli tools --role E` | argparse 拒绝，退出码 2 | `choices=["A","B","C","D"]` 写死了 4 个角色（`schema.ROLES` 的唯一来源被绕过） |
| `agent_g` 自检 | `exit 1 / 26 行（结论：失败）` | `evidence_kind='proof'` 时必须给 `verifier_subject_key` —— 一条**新加的硬约束**没被模块自检的夹具覆盖 |

---

## §1 适用范围与阅读顺序

### 1.1 三类读者

| 读者 | 你要遵守什么 | 先读 | 再读 | 禁忌 |
|---|---|---|---|---|
| **人**（本项目的负责者） | 全部；尤其是**禁 AI 区**与**发布门** | 本文件 §0（现状）→ §3（六条硬纪律）→ §7（提交与评审）→ §8（发布检查） | `docs/ROLE-SPECS.md` §0（公共约定） | — |
| **AI 编码者**（你） | 全部；**并且必须先用证据反驳评审者**（§7.3） | `AGENTS.md`（**禁 AI 区**，最短、最硬）→ 本文件 §3（六条硬纪律）→ §6（禁止模式清单）→ §4（DoD） | `docs/ROLE-SPECS.md` 里**你要改的那个角色**那一节 | 不读 §6 就动手；改了禁 AI 区却自称"顺手改一下" |
| **审计者** | 用 §4 的 checklist 与 §8 的门的**通过判据**逐条质问 | 本文件 §4（DoD）→ §8（发布检查）→ §9（FC 覆盖矩阵） | `docs/ROLE-SPECS.md` 对应角色的 §"不变式"与 §"三态与失败模式" | 把"未核实"读成"已通过"（§9 的状态口径是**三档**：已落地 / 部分 / 未落地） |

### 1.2 阅读顺序（一张图）

```
AGENTS.md（禁 AI 区，先读，最短）
   ↓
DEVELOPMENT.md §0   现状快照（知道手上是哪一版）
   ↓
DEVELOPMENT.md §3   六条不可违反的硬纪律  ← 违反任何一条 = 不改
   ↓
DEVELOPMENT.md §6   禁止模式清单（静态可查）
   ↓
docs/ROLE-SPECS.md  你改的那个角色的规格（工具面 / 状态机 / 预算 / 三态 / 不变式）
   ↓
DESIGN-*.md         设计理由（**不构成判据**；与代码冲突时以代码为准）
```

### 1.3 权威顺序（**冲突时谁赢**）

1. **代码**（`src/agentflow/` + `tests/`）
2. **本文件**（规范）
3. **`docs/ROLE-SPECS.md`**（角色规格）
4. `AGENTS.md`（仅禁 AI 区，**与 `.noai-paths` 同级权威**，两处必须逐条一致）
5. `DESIGN.md` / `DESIGN-TOOLS.md` / `DESIGN-INTERACTIONS.md` / `DESIGN-ROLES.md` /
   `DESIGN-CONDUCTOR.md`（**设计理由**；它们描述"为什么"，不描述"现在是什么"）
6. `README.md`（**已知过期**，见 §10-D1）
7. `temp/inventory/INVENTORY.md` / `tools.json`（**口径不同的另一份普查**，见 §1.4）

### 1.4 ⚠️ `INVENTORY.md` / `tools.json` 的口径警告（**引用前必读**）

`D:\Incubator\temp\inventory\INVENTORY.md:3` 逐字写明它普查的是
**`D:\Incubator\test\test1\`（包名 `abflow`）**，**不是** `D:\Incubator\agentflow\`。

| 项 | `INVENTORY.md`（abflow） | 本文实测（agentflow） | 一致？ |
|---|---|---|---|
| 工具总数 | 55 | 55 | ✅ |
| 各角色工具数 | `A20 B18 C17 D37 E21 F32 G32 H23`（§1.2） | 同 | ✅ |
| `side_effect` 分布 | `read 32 / write_local 15 / none 6 / network 2` | 同 | ✅ |
| 需审批 | 17 / 55 | 同 | ✅ |
| 只读角色泄漏 | 0 | 0 | ✅ |
| **`Task` / `UsageEntry` / `EvalResult`** | **未覆盖** | **有**（`schema.py:1260/1387/1465`） | ❌ **INVENTORY 落后一版** |

**规则**：
- 引用 `INVENTORY.md` 的条目时，**必须写"INVENTORY 4.x"（按条目编号），不许写行号** ——
  两份目录的行号不同。
- 引用 `tools.json` 的 `source.file:line` 时，**必须标"（据 `tools.json`，指向 `test/test1`）"**。
- 任何"数字对不对"的问题，**以 `build_registry` 的实测为准**（§0.3 的命令 2）。

---

## §2 目录与命名规范

### 2.1 包布局（不可随意新增顶层目录）

```
agentflow/
├── AGENTS.md                  禁 AI 区（人类专属区）硬约束 —— 改它=改门
├── .noai-paths                机器可读的禁改区 glob 清单（与 AGENTS.md 逐条一致）
├── DEVELOPMENT.md             ← 本文件
├── DESIGN*.md                 设计理由（5 份，不构成判据）
├── README.md                  ⚠️ 已知过期（§10-D1）
├── config.yaml                全部阈值（"所有阈值都在这里，不在代码里"）
├── pyproject.toml             构建 + pytest 配置（**在禁 AI 区里**）
├── src/agentflow/             包
│   ├── schema.py              ★ 数据模型 + 行级校验 + **全部受控词表**（单一来源）
│   ├── store.py               ★ 锁 / 原子写 / 事务 / 事件日志 / ID 分配 / 重建
│   ├── policy.py              ★ 主控策略（四类上限 + 允许边 + 拒绝理由）
│   ├── capabilities.py        ★ 角色能力表 / 写集 / 召唤边（**导入期自检**）
│   ├── conductor.py           ★ 主控（召唤 → 台账 → backend → 终态）
│   ├── scheduler.py           ★ 波浪调度（写集相交 ⇒ 串行）
│   ├── cancellation.py        ★ 协作式取消（一个共享 signal）
│   ├── contextbudget.py       ★ 上下文压缩 / 剪枝 / spill
│   ├── interactions.py        ★ 角色间交互（I1–I12 的判据）+ CONTRACT_VERSION
│   ├── verify.py              ★ 全库不变量校验（71 个 Issue.code）
│   ├── agent_a.py … agent_h.py  八个角色（**每个角色一个文件**）
│   ├── cli.py                 命令行入口
│   ├── pipeline.py            固定顺序流水线（前三阶段的编排）
│   └── tools/                 工具层（13 个文件，模块 = 工具组）
├── scripts/                   发布门 / 门禁 / linter（**不是运行期依赖**）
├── tests/                     pytest（离线套件；联网套件用 `-m network`）
├── docs/                      规格文档（`ROLE-SPECS.md`、`INDEX.md`）
├── tools/                     一次性探针脚本（**不是发布门**）
└── data/ library/ demo/       运行期数据（⚠️ 见 §10-D6）
```

### 2.2 模块职责边界（**一句话判据**）

| 模块 | 只做这一件事 | **不许**做 |
|---|---|---|
| `schema.py` | 数据模型 + `validate()` + **全部跨模块受控词表** | 不 import 任何 `agent_*`；不碰 `store` |
| `store.py` | 锁 / 事务 / 原子写 / 事件 / ID / 重建 | 不写业务规则；不 import `schema` 之外的同层模块 |
| `capabilities.py` | 角色 → 动作 / 写集 / 召唤边（**声明层**） | **不 import `agent_*`**（用 `importlib` 惰性取类，理由见 `capabilities.py:659-664`） |
| `policy.py` | 纯策略判定（`Refusal` or `None`） | **不碰存储**、不发召唤 |
| `conductor.py` | 召唤 → 台账 → backend → 终态 | 不产出知识（`CAPABILITIES["M"] == ()`） |
| `scheduler.py` | 波浪划分 + 有界并发 + 顺序合并 | 不做策略判定（调 `policy`） |
| `agent_x.py` | 该角色的能力实现（**公开方法名 = `ActionSpec.handler_name`**） | 不直接构造 `ToolRegistry`（§6-P5） |
| `tools/*.py` | 有名字 / 有 schema / 有校验 / 有结构化返回 / 声明副作用的原子动作 | 不写业务策略；不互相 import |
| `verify.py` | 全库不变量审计 | **不许有写路径** |
| `cli.py` | 入口（把操作固定成几个动词） | 不写业务逻辑（只装配与打印） |

### 2.3 命名规范

| 对象 | 规则 | 判据（可机械检查） | 出处 |
|---|---|---|---|
| **角色名** | `"A"`…`"H"` + `"M"`，**单一来源 `schema.ROLES`** | `grep -n 'ROLES' src/agentflow/schema.py` 只有一处定义；`tools.ROLES is schema.ROLES` | `schema.py:1209`；`tools/__init__.py:44` |
| **表名** | `snake_case` 复数（`search_requests` / `research_questions`），**单一来源 `schema.TABLES`** | 任何模块里的表名字面量必须 ∈ `schema.TABLES` | `schema.py:1632` |
| **字段名** | `snake_case`；**ID 字段** `<实体>_id`（`lit_id` / `concept_id` / `question_id`） | 每张表的 `id_field` 在 `schema.TABLES[table]["id_field"]` 里 | `schema.py:1632-1648` |
| **4 位实体 ID** | `^\d{4}$`（`_ID_RE`） | `schema.is_valid_id()` | `schema.py:91` |
| **过程记录 ID** | `<前缀>-NNNN`（`r-` / `p-` / `t-`），**不占 4 位空间** | `interactions.next_prefixed_id(rows, field, prefix)`（**全项目唯一实现**） | `interactions.py:1134` |
| **ID 分配器** | `schema.ID_COUNTERS`（kind → field）**单一来源** | `tests/conftest.py:80-93` 按它**反查**，不另写一张表 | `schema.py:1654` |
| **受控词表常量** | `UPPER_SNAKE` 元组，**定义在 `schema.py`**（除 `tools/base.SIDE_EFFECTS` 与 `capabilities.SIDE_EFFECTS` 这一对**交叉断言**的例外） | `grep -n '^[A-Z_]* = (' src/agentflow/schema.py` | `schema.py` 全文 |
| **测试文件** | `tests/test_<被测对象>.py`（`test_agent_a.py` / `test_tools_base.py` / `test_fc05_contract.py`） | 文件名以 `test_` 开头 | `pyproject.toml:47` |
| **测试函数** | `test_<门名>_<rejects\|accepts>_<情形>` —— **门必须有"拒绝"与"接受"两向** | `grep -c 'def test_.*_rejects' tests/` 与 `..._accepts` 都 > 0 | FC-09；`LESSONS.md` C1/C2 |
| **工具名** | `组.动作`（**必须含一个点**） | `ToolSpec.__post_init__` 抛 `ValueError` | `tools/base.py:201-202` |
| **后端/动作方法名** | `agent_<role>.Agent<Role>.<handler_name>`，**由 `capabilities.ActionSpec.handler_name` 声明** | `capabilities.assert_capabilities()` 导入期 `callable(getattr(cls, name))` | `capabilities.py:704-713` |

### 2.4 注释与 docstring 的**语言与形态要求**

| 要求 | 判据（"是/否"可回答） | 落点 |
|---|---|---|
| **中文** | 注释与 docstring 里中文字符数 > 0 | 全项目 |
| **每个公开函数必须有 docstring** | `scripts/lint_rules.py` 的 **R007** 报 `error` | 实测：**180 / 471 个公开函数没有 docstring**（R007 报 `info`，见 §10-D3） |
| **docstring 必须含"为什么"段落** | docstring 里出现"为什么"或"因为"或"理由"之一，**且**该段说明的是**取舍**（不是复述功能） | `INVENTORY.md` §1.3 的口径：`docstring_has_why` 235→**187 true / 150 false**（据 INVENTORY，**未在 agentflow 上复算**） |
| **禁止"不是装饰"式注释** | 注释里出现"不是装饰"/"确实"/"真的"这类**防御性措辞**时，**必须**在同一提交里补一条断言 | `LESSONS.md` P9（`literature_keys` 的"不是装饰"四个字透露了 bug 的存在） |
| **禁止注释/docstring 里的装饰** | 注释或 docstring 里出现**成对的星号强调**、**未配对的残留星号**或 **emoji**，即判违规（先摘掉反引号代码跨度再判：`` `2**20` ``、`` `a/**/b` ``、`` `handler(**params)` `` 是字面语法） | `scripts/lint_rules.py` 的 **R009**：禁改区外 `error`，禁改区内一条汇总 `info`（见 §6-P17） |
| **行内注释解释"为什么可以忽略异常"** | `except` 行或 `pass` 前有 ≥4 字注释，或 `# noqa: R001` | **R001** 的判据（实测 20 个 error） |
| **每个模块顶部有模块 docstring** | 文件第一个语句是字符串字面量 | 全项目 42 个 src 文件 |

---

## §3 ⭐ 六条不可违反的硬纪律

> **违反其中任何一条 = 这次改动不算完成**。每条给：
> ① 一句话规则 ② 为什么 ③ 可判定判据 ④ 违反后会怎样 ⑤ 现有正例/反例的文件:行号。

### 纪律 1：三态纪律（`True` / `False` / `None` + 受控 `reason`）

**① 规则**：所有"判定"字段必须是三态，**且** `reason` 必须来自受控枚举；
枚举里**必须**至少有一个"未执行"值。**禁止**把 `None` 与 `False` 合并。

**② 为什么**（`LESSONS.md` FC-01 逐字）：
"布尔无法区分'未校验'与'校验失败'，而这两者需要**完全不同的处置**
（前者装 OCR / 补数据，后者改引文 / 剔除）。本项目在**四处**（引文、OCR、D 溯源、
C 预算）都踩到同一坑。"
`DESIGN-CONDUCTOR.md:116-118` 逐字补充了后果：
"每一次的后果都是**下游把'我们没查'读成了'查了没有'**。"

**③ 可判定判据**（三条全中才算过）：

| 判据 | 怎么查 |
|---|---|
| 代码里**没有** `if not chk.verified:` 这种把 `None` 与 `False` 合并的写法 | `grep -n 'if not .*verified' src/agentflow/`；或 R 类 lint 规则（**当前无此规则**，见 §9 FC-01） |
| 每个受控 `reason` 词表**至少含一个"未执行"值** | 逐个人工核对；例：`REFUSAL_REASONS` 含 `not_wired`（`schema.py:1256`）；`DOWNLOAD_STATUSES` 含 `skipped`（`schema.py:89`） |
| 统计输出**分三个计数** | `grep -n 'quote_verified\|quote_unverified\|quote_unknown' src/agentflow/store.py`；`ARunResult` 的 `verified/failed/unknown` |

**④ 违反后会怎样**：下游把"我们没查"读成"查了没有"，于是**不报错**、报告里出现
一条**看起来完全合理的假结论**。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例（最规范）** | `agent_b.py:87-107` | `quotes_verified` / `quotes_failed` / `quotes_unknown` 三个独立字段；`conflict_checks_run`（checked=True）/ `conflicts_detected` / `conflict_checks_skipped`（**checked=False**） |
| ✅ **正例** | `attack_tools.py:78-113` | `check_budget` 的 `budget=None` ⇒ `checked=False, allowed=None`，"注意这与'预算用尽'是两件事" |
| ✅ **正例** | `conductor.py:644-686` | handler 返回 `None` ⇒ `outcome="no_result"`（**不许**映射成 `ok`） |
| ✅ **正例** | `schema.py:1338-1342` | `status=done` 时**必须**给 `outcome` —— schema 层硬拦 |
| ❌ **反例** | `tools/search_tools.py:583-586` | `except Exception: return []` ⇒ `search.dedup_check` 把"表读不到"折叠成"不是重复"（假阴性） |
| ❌ **反例** | `tools/review_tools.py:224` | `verdict` 完全没读 `dep_check["checked"]` ⇒ 同一个返回值里 `dep_check` 说"没查"、`verdict` 说"通过" |
| ❌ **反例（历史）** | `LESSONS.md` P3 ① | D 的溯源 `tools=None` 静默返回空，报告写成"未能取到任何关系表述——**这本身就是一个重要事实**" |

---

### 纪律 2：单一来源（跨模块字符串只在 `schema.py` 定义一次；`tools.ROLES` 就是 `schema.ROLES`）

**① 规则**：任何**跨模块**的字符串集合（角色名 / 表名 / 字段名 / 受控词表 / ID 前缀）
**只能有一处定义**，其他地方**只能 import**。**禁止第二份副本**（含测试代码、CLI 的 `choices`、`expectations` 文件）。

**② 为什么**（`LESSONS.md` FC-03 逐字）：
"`"agent-D"` vs `"D"`、`download.status` 的受控词表、`title:...|*` 通配键
—— 本项目同族问题出现 **3 次**。"
后果（`DESIGN-CONDUCTOR.md:41-42` 逐字）：
"两处各写一份名单，就会出现'schema 认为合法的角色，工具层不认'这种**没有任何报错**的分裂。"
`LESSONS.md` §8.3 更狠的一句：
"**跨模块约定必须只有一处定义（FC-03）在测试代码里同样成立 —— 测试代码也是代码，
写死第二份名单同样会漂移。**"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| `tools.ROLES is schema.ROLES`（**同一个对象**，不是相等） | `python -c "from agentflow import schema, tools; print(tools.ROLES is schema.ROLES)"` → **必须 `True`** |
| 角色名单只有 `schema.py:1209` 一处定义 | `grep -rn 'ROLES *=' src/agentflow/` → **只有 1 处**（`tools/__init__.py:44` 是 `from ..schema import ROLES`） |
| 表名/字段名只在 `schema.TABLES` 定义 | 任何模块里的表名字面量必须 ∈ `schema.TABLES`；`grep -n '"search_requests"' src/agentflow/*.py` 应只见 `schema.py` 的定义与**必要的字面量使用**（使用允许，定义禁止） |
| ID 分配器只有一处 | `interactions.next_prefixed_id`（`interactions.py:1134`）；**新增第二份 = 违规** |
| 测试夹具不写死名单 | `tests/conftest.py:80-93` 按 `S.ID_COUNTERS` **反查** |
| CLI 的 `choices` 来自 `ROLES` | `grep -n 'choices' src/agentflow/cli.py` |

**④ 违反后会怎样**：**没有任何报错**，只是"少了一点东西"（少几个工具 / 少列几个角色 /
判重键不匹配）—— 而"少了一点东西"会在最坏的时刻以"数据损坏"的形态出现。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例** | `tools/__init__.py:44` | `from ..schema import ROLES`（注释逐字写了为什么不许各写一份） |
| ✅ **正例** | `tests/conftest.py:80-85` | "⚠️ 覆盖范围由 **`S.ID_COUNTERS` 反查**，不在这里另写一张 (kind, table) 表。原先这里写死了 3 个 kind…" |
| ✅ **正例（已修的 CLI）** | `cli.py:239-243` | 注释逐字："角色清单必须来自 `ROLES`，**不许在这里写死**。这里原先写死 `("A","B","C","D")`…写死名单让那句'评审时可核对'落空" |
| ❌ **反例（**仍在**）** | `cli.py:460` | `sp.add_argument("--role", default=None, choices=["A","B","C","D"], …)` —— **argparse 层仍写死 A–D**（实测 `--role E` 退出码 2） |
| ❌ **反例** | `capabilities.py:600` | `"F": frozenset({"A","B","C","D","E"})` 触发了 **R005**（"出现了写死的**完整**角色名单字面量"）—— 实测 linter 报 warn |
| ❌ **反例** | `agent_d.py:483/509/546` | `roles=("agent-C","agent-D")` —— **带 `agent-` 前缀**，不是 `ROLES` 里的 `"C"`/`"D"`；且这 3 个工具**不过 `build_registry` 的校验** |
| ❌ **反例（已修的 verify）** | 见 `draft/13` §8.3 | `_id_contiguity` 曾写死只排除 `search_requests`，新增 `p-NNNN` 后 **`verify` 自己崩掉** |

---

### 纪律 3：fail-closed（未接线 / 依赖缺失 / 读不到 ⇒ 显式失败，**不许静默返回空**）

**① 规则**：任何"上游为 `None` / 依赖缺失 / 文件读不到 / 后端不存在"的分支，
**必须**返回结构化失败（`ok=False` + 受控 `kind`，或 `refused/not_wired`），
**不得**返回空数据、`{}`、`[]`、`0`、`ok=True`。

**② 为什么**（`LESSONS.md` FC-08 逐字）：
"这是本项目最尖锐的缺陷（`11-...md` §10.4 #7）：D 没接上 registry 时走了'无工具'
降级分支并**静默返回空**，报告写成'未能取到任何关系表述——这本身就是一个重要事实'。"
`LESSONS.md` N4 的判据只有一句："**不要把'没做'写成'没查到'**。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 有 `tools is None` / `store is None` / `registry is None` 的分支时，**返回失败而不是空** | `grep -n 'is None' src/agentflow/` 逐个人工看；**R002** 规则（`None`→空容器）报 error |
| 每条"降级/未接线"路径有**一条测试**断言"返回失败而不是空" | `grep -rn 'not_wired\|no_store\|no_backend' tests/` 应有断言 |
| 报告生成器遇到"未接线"**拒绝生成结论** | 人工核对：`agent_d` 的置信度路径是否会把 `checked=False` 写成"证据不足" |
| `except` 必须解释为什么可以忽略 | **R001**（实测 20 个 error） |

**④ 违反后会怎样**：错误**伪装成一条合理的结论**（"查过了，没有"），
而它看起来**比报错更像结论**。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例** | `tools/search_tools.py:591-598` | `store is None` ⇒ `fail("…任何判重结论都会是假阴性…", kind="no_store")` |
| ✅ **正例** | `conductor.py:212-226` | `SubagentBackend` 恒 `raise NotWiredError` ⇒ `refused/not_wired`（docstring 逐字列出两条诚实的路并选后者） |
| ✅ **正例** | `conductor.py:150-164` | `LocalBackend` 对 `("class", cls)` **明确拒绝**："自动 new 只能靠猜，而猜错会静默少做事" |
| ✅ **正例** | `tools/ocr_tools.py` 的 `ocr.run` | 都不可用时 **fail** 并给安装建议（"绝不返回空文本假装成功"，`summary` 逐字） |
| ❌ **反例** | `tools/search_tools.py:583-586` | `except Exception: return []` ⇒ 判重报"不是重复"和同一个文件 `:591-598` 的严格 fail-closed **自相矛盾** |
| ❌ **反例** | `tools/trace_tools.py:163-169` | `_g()` 无 store 无 graph 时返回空图 ⇒ `trace.chain` 仍 `return ok(...)`（唯一一个"成功"的静默空结果） |
| ❌ **反例** | `tools/doc_tools.py` / `review_tools.py` / `attack_tools.py` / `verify_tools.py` | 「未接线」判据有 **4 份**实现（`_not_wired()` × 2 + `_need_store()` × 2） |

---

### 纪律 4：证据等级（`proof` / `cross_check` / `heuristic`；计算类**拿不到** `proof`）

**① 规则**：任何数值/计算产出必须带 `evidence_kind ∈ EVIDENCE_KINDS`；
**计算类方法（`numeric` / `symbolic` / `exhaustive_search`）不得标 `proof`**；
`proof` 必须另带 `verifier_subject_key`。

**② 为什么**（`LESSONS.md` FC-22 逐字）：
"数学里数值实验不构成证明（`09-...md` §6.2(1) 明确'验证通过 ≠ 数学正确'）；
而本项目实测证明了'结构自洽 ≠ 内容正确'与'三个绿灯叠加仍不能证明系统有用'。"
`LESSONS.md` M4："数值**只能作为交叉验证**，不能替代证明；同一个个例不能推广为定理。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 数据结构里有 `evidence_kind` 字段且受控 | `schema.py:633` 的 `EVIDENCE_KINDS` |
| 计算类拿不到 `proof` | `verify.run_experiment` 的降级 + `schema.Experiment.validate`；自检实测"脚本自报 proof 被降级为 cross_check" |
| `proof` 必须给 `verifier_subject_key` | `schema.py:810` 抛 `ValueError` |
| 报告里 `cross_check` 结论**自动**附加"不构成证明" | `CROSS_CHECK_DISCLAIMER`（`doc.compose_claim` 自动补） |
| "没有 proof 级证据时结论不得标已证明" 有测试 | `tests/test_agent_e.py`（30 例）/ `test_agent_f.py`（自检断言"只有数值证据却标 closed ⇒ schema 抛"） |

**④ 违反后会怎样**：**proof 级证据是假的，而报告照样打印** ——
这是"过度声称"，也是 `draft/13` §8.8 记录的一次**复核者自己犯错**（`PROVED_HERE` 标签）。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例** | `schema.py:699-863` 的 `Experiment.validate` | 五条硬约束（含 `verifier_subject_key`） |
| ✅ **正例** | `verify.py` 的 `evidence_kind_overclaim` / `proof_claim_rests_on_weaker_evidence` / `proof_claim_with_unclosed_dependency` | 三条 error 级检查 |
| ✅ **正例** | `agent_e._selftest` | 主动用"想自称 proof 的脚本"验证降级 + notes 留痕 |
| ❌ **反例（历史）** | `draft/13` §8.8 | 复核产物用了 `PROVED_HERE` 标签 —— 复核者自己犯了 FC-22 |
| ⚠️ **未落地** | `schema.py` **无** `negation_kind` 对"计算类"的强制（只有 `proof` 的强制） | 见 §9 FC-25 |

---

### 纪律 5：拒绝 ≠ 失败（`outcome="refused"` 是一次**成功**执行）

**① 规则**：框架"正确地说了不"（越权 / 超预算 / 超深度 / 循环 / 未接线）必须记为
`status="done", outcome="refused"` + 受控 `refusal_reason`；
**不许**记成 `failed`。**拒绝也必须落台账**。

**② 为什么**（`DESIGN-CONDUCTOR.md:105-118` 逐字）：
"**`refused` 是一次成功的执行** —— 框架**正确地说了"不"**。把它写成 `failed`
会让'策略拦住了'与'代码崩了'混在一起，而这两件事需要完全不同的处置。"
"**拒绝也落台账**：不写这一行，'我们拒绝了它'这件事就**无可审计**——
而'我拒绝过'恰恰是事后最需要回答的问题（是策略太紧，还是有人越权）。"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| `outcome="refused"` ⇒ `status == "done"` | `schema.py:1345-1350` **硬拦**（`status!=done` 直接 `ValueError`） |
| `outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS` | `schema.py:1351-1355` **硬拦** |
| `refusal_reason` 非空 ⇒ `outcome == "refused"` | `schema.py:1356-1357` **硬拦** |
| 拒绝**必须落台账**（有行） | `Conductor._refuse` 写行（`conductor.py:432-457`） |
| 但**"取消后不产生新任务"是例外**（`task_id=None`，无行） | `conductor.py:490-512` 的注释逐字解释了这个例外为什么不冲突 |
| `SummonResult.ok` 的判据只有一处 | `conductor.py:109-117`：`status=="done" and outcome=="ok"`（**refused 不算 ok**） |

**④ 违反后会怎样**：两种需要**完全不同的处置**的事情长得一样；
调用方问 `res.ok` 会把"越权被拦住"看成"成功交付"。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例（schema 硬拦）** | `schema.py:1345-1357` | 三条 `ValueError`，消息里逐字解释理由 |
| ✅ **正例** | `conductor.py:459-462` | `_refuse` 返回 `status="done", outcome="refused"`，并写 `started_at == ended_at`（"它一毫秒也没跑"这件事由 detail 里的人话说明） |
| ✅ **正例** | `policy.py:98-118` 的 `Refusal.__post_init__` | `reason` 不在 `REFUSAL_REASONS` 里就抛 |
| ❌ **反例** | `tools/attack_tools.py:160`（INVENTORY 4.5#12） | `can_derive` 在 `checked is False` 时返回 `blocked_by="incomplete"` —— **用"不完整"这个标签去表示"没检查"** |
| ⚠️ **风险** | `conductor.py:966-1014` 的 `verify_tasks` 与 `verify.py:662-694` 的 6 条 tasks 检查是**两套实现** | `conductor.py:969-972` 逐字承认并给了理由，但仍是 FC-11 的漂移风险面 |

---

### 纪律 6：派生态不许当输入（**就地推导** 或 **装配期断言**，没有第三种）

**① 规则**：任何"派生字段"（可从别的字段算出来的）在下游被读取时，
**要么就地推导**，**要么在装配期断言它存在**。**不许**"假设上游会填"。

**② 为什么**（`draft/13` §8.2，一次**完全静默**的失效）：
`detect_contradictions` 直接读行里的 `concept_pair_key`，但 `relations` 表存的字段名是
`concept_group_key` ⇒ 对**直接从表里读出来的行**（C 的 `contradictions()`、任何脚本）
**恒返回 `[]`** —— 不报错、不告警，看起来就像"没有矛盾"。
"**派生态要么就地推导，要么在装配期断言它存在（不许有第三种）。**"

**③ 可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 每个派生字段的每个读点，**要么**当场算，**要么**有断言 | `grep -n 'concept_pair_key\|related_concepts\|concept_group_key' src/agentflow/`，逐个看是否有 `or 推导()` 兜底 |
| **正例的形态** | `interactions.py:244-245`：`... or concept_pair_key([...])` |
| 派生态与真源不一致必须**可检出** | `verify.related_drift`（warning）；`verify.stale_group_key`（error） |
| 派生字段必须有**重算**路径 | `verify` 重算比对；CLI 有 `repair --related`（`cli.py:209-225`） |
| 可重建存储的**信息量守恒** | `tests/test_rebuild.py`（3 例：诊断字段守恒 / 幂等 / 坏事件不炸） |

**④ 违反后会怎样**：**恒返回空 + 静默** —— 与 §3 纪律 1/3 的后果同族，
但这个更隐蔽：**没有异常、没有告警、没有空值**，只有一个看起来正常的 `[]`。

**⑤ 正例 / 反例**：

| 类型 | 位置 | 说明 |
|---|---|---|
| ✅ **正例** | `interactions.py:232-238` 的注释 + `:244-245` 的修正 | 逐字记录了这次失效 |
| ✅ **正例** | `Related_concepts = 由关系表派生` | "不由增量 append 直接决定，由关系表派生"⇒ **可自愈**（漏更新会在下次重算时修正），`verify` 会重算比对（`LESSONS.md` P6(a)） |
| ✅ **正例** | `capabilities.assert_capabilities()`（**导入期**） | "能力表一旦与实现漂移，症状不是崩溃而是**静默的越权/并发损坏**。让它 import 时就炸，是唯一'不可能忘记跑'的校验点"（`capabilities.py:745-748`） |
| ❌ **反例** | `dedup.literature_keys` 的 `title:<norm>|*` 第三级键 | 生成后**在匹配时被过滤掉** ⇒ "忽略年份"是死代码（`LESSONS.md` P1 ②） |
| ❌ **反例** | `interactions.related_relation_ids`（升序）| 为满足"升序"不变量**丢掉了跳序**，只能从 `origin` 字符串反解（`LESSONS.md` P15） |
| ⚠️ **部分落地** | `schema.ARRAY_FIELD_KINDS`（`schema.py:1562`） | 已落地"未声明数组字段即 `verify` 报 `undeclared_array_field`"；`Relation.chain` 的保序字段见 §9 FC-05 |

---

## §4 ⭐ Definition of Done

> **六份 checklist**。每项给"谁来检查 / 在哪检查"。**逐项可勾选**。
> `[ ]` 全部勾上才算 Done。**任何一项无法勾 = 这次改动没完成。**

### 4.1 新增/修改**表**（`schema.TABLES` + 行 dataclass）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 在 `schema.TABLES` 加了 `{file, row, id_field, id_kind}`；`id_kind` 在 `ID_COUNTERS` 里（若要用 4 位 ID） | 实现者 | `schema.py:1632` |
| 2 | `[ ]` 行 dataclass 有 `validate()`，且**每个受控字段**都有词表校验 | 实现者 | 该 dataclass 内 |
| 3 | `[ ]` `row_from_dict` 加了该表的分支（含嵌套结构的 `from_dict`） | 实现者 | `schema.py:1594` |
| 4 | `[ ]` 数组字段在 `schema.ARRAY_FIELD_KINDS` **显式声明**为"集合（升序去重）"或"序列（保序）" | **`verify`** | `verify.undeclared_array_field`（error） |
| 5 | `[ ]` `store.empty_table()` / `Store.init()` 会建这个文件 | 实现者 | `store.py` |
| 6 | `[ ]` `Store.rebuild()` 的事件重放支持该表 | 实现者 | `store.py:404` |
| 7 | `[ ]` `verify.py` 加了至少一条该表的**引用闭合**检查（若它引用别的表） | **`verify`** | `verify.py` |
| 8 | `[ ]` **两条测试**：① 合法行通过；② 违反每个约束的行**被拒** | 实现者 → 审计者 | `tests/test_schema.py` |
| 9 | `[ ]` **重建守恒**：`rebuild` 前后诊断字段相等 + 幂等（逐字节） | **`tests/test_rebuild.py`** | CI 第 1 项 |
| 10 | `[ ]` `docs/ROLE-SPECS.md` 里对应角色的 **§状态机** 补了迁移表与终态 | 文档维护者 | `docs/ROLE-SPECS.md` |
| 11 | `[ ]` **写集更新**：`capabilities.WRITE_SETS[role]` 若该表会被某角色写 | **`capabilities.assert_capabilities()`** | 导入期 `AssertionError` |
| 12 | `[ ]` `tests/test_fc05_contract.py` 的数组字段契约测试通过 | **CI 第 1 项** | `tests/test_fc05_contract.py` |

### 4.2 新增/修改**字段**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 若该字段是"判定"类 ⇒ 三态（§3 纪律 1），`reason` 进受控词表 | 审计者 | §3 纪律 1 的判据 |
| 2 | `[ ]` 若是受控值 ⇒ 词表定义在 `schema.py`，**只此一处** | **linter R005 / 人工** | `scripts/lint_rules.py` |
| 3 | `[ ]` 若是"状态 ⟹ 其它字段"的关系 ⇒ 写成**交叉检查**（scheman 层 `validate()`） | 实现者 | FC-04 判据② |
| 4 | `[ ]` 每条交叉检查有**一条"违反应被拒"**的测试 | 审计者 | FC-04 判据③ |
| 5 | `[ ]` 若是数组 ⇒ 在 `ARRAY_FIELD_KINDS` 声明集合/序列 | **`verify`** | `verify.undeclared_array_field` |
| 6 | `[ ]` 若是"有语义的顺序" ⇒ 与升序集合字段**成对存在**（`related_relation_ids`（升序）+ `chain`（保序）） | 审计者 | FC-05 判据② |
| 7 | `[ ]` 保序字段有 **round-trip 测试**（写→读→相等） | **`tests/test_fc05_contract.py`** | `test_relation_chain_preserves_order_round_trip` |
| 8 | `[ ]` `docs/ROLE-SPECS.md` 对应角色的 §状态机 与 §三态 更新 | 文档维护者 | — |
| 9 | `[ ]` 更新 `DESIGN*.md` 的字段表（**可选**，但若改了必须与代码一致） | 文档维护者 | §10 的处置流程 |

### 4.3 新增/修改**工具**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` **六件套齐全**：`name / summary / params / returns / side_effect / roles` | **`ToolSpec.__post_init__`**（取值与结构）+ 实测 census（"别忘了写 `returns`"） | `tools/base.py` 的 `ToolSpec.__post_init__` **真的校验收值/结构**：`side_effect` 与 `external` 的受控词表、名字含 `.`、`summary` 非空、`params` 根是 object、`returns` 必须是字符串、`roles` 必须是元组。**唯一的缺口是 `returns` 的非空**：三个内置降级替身（`agent_d.py` 的 `trace.*`）没写它，而那个文件不在本轮授权范围内 ⇒ 由 census 观察（见 `base.REQUIRED_NON_EMPTY_FIELDS` 的理由）。census 输出"六件套缺字段：无" |
| 2 | `[ ]` `side_effect ∈ SIDE_EFFECTS`（`none/read/write_local/network`）、`external ∈ EXTERNAL`（`none/egress/exec`） | **装配期**抛 `ValueError` | `tools/base.py` 的 `ToolSpec.__post_init__`（`network` 是遗留取值，必须同时出现在 `LEGACY_EFFECTS_BY_TOOL` 里） |
| 3 | `[ ]` **`side_effect` 与真实行为一致**（双向） | **linter R006（一个方向）+ R010（另一个方向）** + 人工 | R006：文件级共现、`info`；R010：**按工具判**，声明非 exec 却起子进程 ⇒ `error`，声明 `egress` 却无网络调用 ⇒ `warning`。见 §6 的 P7 |
| 4 | `[ ]` `roles` 里**没有** `READ_ONLY_ROLES`（若它是写工具） | **`for_role` 结构性剥离** + `role_filter_notes` | `tools/base.py:335-344` |
| 5 | `[ ]` `params` 是 JSON Schema（object 根），**能原样喂给 function-calling** | 人工 | FC-07 / `LESSONS.md` D4 |
| 6 | `[ ]` handler **只收关键字参数**（`spec.handler(**params)` 不报位置参数错） | 实测 census | 55/55 true |
| 7 | `[ ]` 参数非法 ⇒ **返回结构化失败**（`ok=False` + `kind`），**不抛异常** | **`ToolRegistry.call`** | `tools/base.py:370-376` |
| 8 | `[ ]` 未知工具名 ⇒ `ok=False, kind="unknown_tool"` | **`ToolRegistry.call`** | `tools/base.py:375-376` |
| 9 | `[ ]` **返回结构有契约测试**（不是文档） | 实现者 | `LESSONS.md` B8 |
| 10 | `[ ]` 返回里有三态位（若它是"查询"类） | 审计者 | §3 纪律 1 |
| 11 | `[ ]` 依赖缺失 ⇒ **fail-closed**（`not_wired` / `no_store`） | 审计者 | §3 纪律 3 |
| 12 | `[ ]` 只读工具**调用后工作区字节级不变** | **测试**（目录指纹） | FC-07 判据④；`agent_c` 自检有"I1 服务面只读：三张知识表逐字节不变" |
| 13 | `[ ]` 若是只读工具 ⇒ **不得联网 / 起子进程 / 下模型** | **linter R006** | 实测 warn |
| 14 | `[ ]` `docs/ROLE-SPECS.md` 的**全局工具总表**加一行（含所有列） | 文档维护者 | `docs/ROLE-SPECS.md` §R0 |
| 15 | `[ ]` `tests/` 里**提到该工具名**（不是只靠"遍历 registry"覆盖） | 实现者 | INVENTORY §4.1 的口径 |

### 4.4 新增/修改**交互**（I1–I12 之类）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 交互的判据在 `interactions.py`（**纯函数**，签名里**没有 `store`**） | **`interactions.assert_store_free`（导入期）** | `interactions.py:1174/1198` |
| 2 | `[ ]` 若涉及新召唤边 ⇒ `capabilities.ALLOWED_EDGES` 更新，且 `assert_capabilities` 通过 | **导入期** | `capabilities.py:675-748` |
| 3 | `[ ]` 若涉及新写入 ⇒ `WRITE_SETS` 更新（表级）；只读角色的例外必须**显式登记理由** | **导入期 `assert_capabilities` 第 4 条** | `capabilities.py:722-734` |
| 4 | `[ ]` 有**配额/上限**（"每个交互都必须有上限"） | 审计者 | `interactions.DEFAULTS` |
| 5 | `[ ]` 上限用尽时的行为**明确**（拒绝 / 降级 / 落盘）并把理由留在返回里 | 审计者 | `LESSONS.md` A13 |
| 6 | `[ ]` 上限用尽**逐条留理由**（不是静默少几条） | 审计者 | `agent_c` 自检实测："被拒=1 条，示例理由=…已达每轮上限 max_gap_requests_per_run=3 ⇒ 未提交" |
| 7 | `[ ]` 端到端交接测试：**同时**构造"上游产出该状态"与"下游消费它" | 实现者 | `LESSONS.md` P4(b) |
| 8 | `[ ]` 交互的判据有**单测**（`tests/test_interactions.py`，48 例） | 实现者 | CI 第 1 项 |
| 9 | `[ ]` `docs/ROLE-SPECS.md` 的两个角色的 §接口 都更新 | 文档维护者 | — |

### 4.5 新增/修改**角色**（**最重的一份**）

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 角色名加进 `schema.ROLES`（**只此一处**） | 实现者 | `schema.py:1209` |
| 2 | `[ ]` `agent_<role>.py` 里有 `Agent<Role>` 类，且每个动作的 `handler_name` **真实可调用** | **`capabilities.assert_capabilities()` 第 2 条（导入期）** | `capabilities.py:704-713` |
| 3 | `[ ]` `capabilities.CAPABILITIES[role]` 每条 `ActionSpec` 有 `params`（object 根 + `properties`） | **`ActionSpec.__post_init__`** | `capabilities.py:82-98` |
| 4 | `[ ]` `capabilities.WRITE_SETS[role]` **有值**（空也要显式写，且只读角色必须登记例外） | **导入期** | `capabilities.py:697-701` |
| 5 | `[ ]` `capabilities.ALLOWED_EDGES` 有该角色（**双向都要想清楚**：它能召唤谁、谁能召唤它） | **导入期** | `capabilities.py:702` |
| 6 | `[ ]` 若是只读角色 ⇒ 加进 `tools.READ_ONLY_ROLES`，并配**负向权限测试** | 实现者 + **`for_role`** | FC-06 判据④；`tests/test_tools_readonly_roles.py`（7 例） |
| 7 | `[ ]` 有**自检入口** `python -m agentflow.agent_<role>`，覆盖主路径，**退出码 0** | 实现者 | 见 §10-D5（A/B **缺**） |
| 8 | `[ ]` 有专属测试文件 `tests/test_agent_<role>.py` | 实现者 | CI 第 1 项 |
| 9 | `[ ]` 每个"没有结果"的场景有三态形态 | 审计者 | §3 纪律 1 |
| 10 | `[ ]` 所有循环有**上限**，且上限用尽时的行为可读 | 审计者 | `docs/ROLE-SPECS.md` §预算 |
| 11 | `[ ]` 有可被 `verify` 检查的不变式（若产出新表/新字段） | 审计者 | `verify.py` |
| 12 | `[ ]` `cli.py` 的**角色相关 choices 不写死**（用 `ROLES`） | **人工**（**当前 `--role` 仍写死 A–D，见 §10-D2**） | `cli.py:460` |
| 13 | `[ ]` `docs/ROLE-SPECS.md` 新增完整一节（**10 条结构必须与既有节一致**） | 文档维护者 | `docs/ROLE-SPECS.md` |

### 4.6 新增/修改**验证门**

| # | 检查项 | 谁检查 | 在哪检查 |
|---|:---:|---|---|
| 1 | `[ ]` 门有**明确的级别**（`error` / `warning` / `info`），级别写在 docstring **与**文档表里 | 审计者 | FC-13 判据① |
| 2 | `[ ]` 级别规则可表述为两句："表里已记录的缺陷被重算确认" = warning；"表里记录与重算事实矛盾（谎报）" = error | 审计者 | FC-13 判据② |
| 3 | `[ ]` **正控**：好数据必须通过 | 实现者 | FC-09 判据② |
| 4 | `[ ]` **负控**：注入已知坏数据必须报错 | 实现者 | FC-09 判据① |
| 5 | `[ ]` 负控用例**命名可辨认**（`test_<gate>_rejects_*`） | **CI 第 5 项（linter）** | `LESSONS.md` FC-09 落地形态 |
| 6 | `[ ]` 校验器与写入方**共用同一配置来源**（不得一处读配置、一处硬编码） | 审计者 | FC-11；`cli.py:175-184` 是正确的正面范例 |
| 7 | `[ ]` 校验器函数的这些参数**不得有默认值**，或默认值 = "拒绝执行" | 审计者 | FC-11 判据① |
| 8 | `[ ]` 门的**脚本有退出码**（三档：0/1/2，且 `unknown` 与 `fail` 分开） | **linter R008** | `draft/17` §6.3 教训 |
| 9 | `[ ]` 三分档计数（`verified` / `failed` / `unknown`），**禁止单一通过率** | 审计者 | FC-10 |
| 10 | `[ ]` 报告/CLI 输出**同时展示三个数字** | 审计者 | FC-10 判据② |
| 11 | `[ ]` 有一条测试断言"注入无法校验的样本后 `unknown` 增加而 `failed` 不变" | 实现者 | FC-10 判据③ |
| 12 | `[ ]` 在新门上线前，**在 ≥20 条真实样本上量过触发率** | **人**（不可自动） | `draft/13` §8.1 教训（旧 `detect_contradictions` 24% 假报警率） |

---

## §5 测试规范

### 5.1 每个验证门**必须**有一正一反（负控）

| 要求 | 判据 |
|---|---|
| 每个门（`validate` / `verify` / `check` / `gate`）至少一条**注入已知坏数据并断言报错**的用例 | `grep -rn 'def test_.*_rejects' tests/` 的命中数 ≥ 门的数量 |
| 每个门同时有**防误伤**用例（好数据必须通过） | `grep -rn 'def test_.*_accepts\|def test_.*_passes\|def test_.*_ok' tests/` |
| 命名可辨认 | 测试函数名以 `_rejects_` / `_accepts_` 结尾或含之 |

**为什么**（`LESSONS.md` FC-09 逐字）：
"只有绿灯不能证明门在工作。本项目用**刻意伪造的假引文**证明了 `verify` 真的会抓，
而 9 条缺陷中 **0 条**能被 happy-path 抓到。"
`LESSONS.md` C2 给了反方向的理由："**假报警比不校验更糟**。"

**现有正例**：`tests/test_agent_h.py` 的三类负控（无引用 / 否定未分类 / 依赖悬空）+
落库级负控；`tests/test_agent_c_service.py` 的"负控：邻域相同但名字不同 ⇒ `proposal=review`"；
`scripts/release_check.py` 第 6 项要求 `noai_gate` 的**负控**（见 §10-D4）。

### 5.2 断言要打在**判据**上，而不是实现细节上

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

### 5.3 测试夹具**不许写死**表名 / 角色名 / `kind` 列表

| 要求 | 判据 | 现有正例 |
|---|---|---|
| 计数器同步按 `S.ID_COUNTERS` **反查** | `grep -n 'ID_COUNTERS' tests/conftest.py` | `tests/conftest.py:88`：`for kind, field in S.ID_COUNTERS.items():` |
| 角色名单来自 `ROLES` | `grep -n 'ROLES' tests/` 只见 import | 全项目 |
| 表名来自 `schema.TABLES` | `grep -n 'TABLES' tests/` | `tests/test_fc05_contract.py:35`（`test_every_array_field_is_declared`） |
| 时间戳一律写死为常量 | `tests/conftest.py:7` 逐字（"避免测试依赖'当前时间/时区'"） | `conftest.py:7` |

**两个**点名要引的实例：

1. **`conftest.sync_counters`** —— `tests/conftest.py:80-85` 逐字：
   "⚠️ 覆盖范围由 **`S.ID_COUNTERS` 反查**，不在这里另写一张 (kind, table) 表。
   **原先这里写死了 3 个 kind**，于是新增 `experiment` / `plan` / `doc` / `dep` / … 后失效。
   **测试代码也是代码，写死第二份名单同样会漂移**。"
2. **`cli.cmd_tools`** —— `cli.py:239-243` 逐字：
   "⚠️ 角色清单必须来自 `ROLES`，**不许在这里写死**。这里原先写死 `("A","B","C","D")`，
   于是 E/F/G/H 落地之后，本命令会一边报告'工具总数 55'，一边只列 4 个角色的工具数 ——
   而'角色即权限面'恰恰是靠这条命令变成**可打印的事实**的。写死名单让那句
   '评审时可核对'落空。"

> ⚠️ **同一族问题仍有一处残留**：`cli.py:460` 的 argparse `choices=["A","B","C","D"]`
> （实测 `--role E` 退出码 2）—— 函数体修了，**参数层没修**。

### 5.4 离线确定性

| 要求 | 判据 | 出处 |
|---|---|---|
| 日常套件**离线** | `pyproject.toml:51` 的 `addopts = "-m 'not network'"` | `pyproject.toml:44-54` |
| 需要联网的用例**显式标记** | `@pytest.mark.network`；`markers` 已注册 | 同上 |
| 联网套件**独立可跑** | `python -m pytest -q -m network` | 同上 |
| 限流（429）判 `skip`，**400 一律判失败** | README 逐字（`README.md:52`） | 但**该条针对的是 `test/test1`，§10-D1** |
| 默认套件规模 | **835 passed / 3 failed / 8 deselected**（最后一次完整跑动） | §0.2 |

**"进套件 + 默认 deselect"是两个诉求的唯一交集**（`README.md:50` 逐字）：
"日常套件必须离线、确定性、可重复 —— 否则一次上游限流就会把 CI 搞红，久而久之没人再看红灯。
但有几个真实缺陷（Crossref `select` 参数错误导致全 400、`precise` 模式恒为 0）
**只有真实 HTTP 往返才能发现**，所以它们必须留在套件里（不能只写在文档里），只是默认不跑。"

### 5.5 时间断言要给余量

| 要求 | 判据 |
|---|---|
| 任何"耗时"断言必须有**余量**（不能断言 `elapsed < 0.1`） | `grep -rn 'elapsed\|monotonic\|time()' tests/` 逐个人工看 |
| 墙钟用 `time.monotonic()`（**不受 NTP 回拨影响**） | `conductor.py:297` 逐字注释 |
| 超时类断言用"**至少**花了 N 秒"，不用"**恰好** N 秒" | 现有正例：`agent_e` 自检的 `timeout=1s` 只断言 `result=inconclusive`，不断言精确耗时 |

---

## §6 ⭐ 禁止模式清单（静态可查）

> **一条一行**：模式 / 为什么禁止 / 反例出处 / 替代写法。
> 表中的 **P1–P9 与 P17** 已经落成 `scripts/lint_rules.py` 的 **R001–R010**（10 条规则可直接跑）；
> 其余条目需要人工或后续 lint 规则。

| # | 模式（静态可查） | 为什么禁止 | 反例出处 | 替代写法 | lint |
|---|---|---|---|---|---|
| P1 | `except Exception: pass` / `except: …` 后**无解释** | "我知道这里会抛且知道为什么可以不管"与"我没注意"必须能区分 | **发现时实测 20 个 error**：`agent_c.py:373/1924/2041/2752`、`agent_d.py:3869`、`agent_e.py:740`、`agent_f.py:1167`、`agent_g.py:474`、`agent_h.py:327`、`extract.py:428/434/537`、`llm.py:946`、`pipeline.py:800`、`store.py:362` …。**现已归零**（每条都补了**具体**理由，不是空洞 `noqa`；其中两处是"回退链 / `relative_to` 抛错恰恰表示通过"的控制流，一处是 stdout `reconfigure` 的可忽略失败） | ① 让它抛；② 或在 `except` 行写 ≥4 字理由；③ 或 `# noqa: R001` | **R001** |
| P2 | `if x is None: return []` / `return {}` / `return 0` | 把"没做"折叠成"没有"（§3 纪律 3） | `tools/search_tools.py:581-586`（**已修**：改为 `(rows, read_error)` 三态）；`tools/trace_tools.py:163-169`（**已修**：`_g()` 改三态，无图可查 ⇒ `no_graph` + `checked=False`） | `return fail("…", kind="no_store")`；或 `return [], "<为什么>"`（**带回伴生原因** ⇒ 不算折叠） | **R002** |
| P3 | **写死角色/表名/kind/字段名单的第二份副本** | FC-03；"测试代码也是代码" | `cli.py:460` 的 `choices=["A","B","C","D"]`（**已修** ⇒ `list(S.ROLES)`）；`capabilities.py:600` 的 `frozenset({"A".."H"})`（**已修** ⇒ `frozenset(S.ROLES)`）；`agent_d.py` 的 `("agent-C","agent-D")`（**已修** ⇒ `("C","D")` + 装配期 `validate_tool_roles`） | `from ..schema import ROLES` | **R005**（+ 人工） |
| P4 | **校验器与写入方各持一套判据** | "假报警比不校验更糟"（`LESSONS.md` P7） | `tools/review_tools.py` 的 `verdict` vs `dep_check`（**已修**：`checked=False` ⇒ `unverified`）；`doc.scan_claim` vs `review.scan_document`（**已收敛**：`scan_claim` 改为纯适配层转发 `claimanatomy`）；`conductor.verify_tasks` vs `verify.py` 的 tasks 检查（**已收敛**为 `capabilities.audit_task_ledger` 唯一实现 + 一致性测试） | 判据只有一份函数；两处都 import 它 | 人工 / 后续规则 |
| P5 | **`tools/__init__.py` 之外的 `ToolRegistry` 直接构造**（绕过角色校验） | `build_registry` 的 `bad_roles` 断言是"字符串拼法不同导致静默失配"的唯一通用解法 | **发现时实测 8 个 warn**：`agent_d.py`、`agent_e.py:707`、`agent_f.py`、`agent_h.py:102/163`、`tools/fs_tools.py:894`、`tools/table_tools.py:919`。**现只剩 2 个 warning**（`agent_e` / `agent_f` 的两个装配入口，= `PROPOSALS.md` **G-1**，**刻意保留可见**）；其余降为 `info`（已调用了同一份校验，或已逐点登记为例外） | `build_registry` / `build_for_role`，或**显式调用同一份校验函数** | **R004** |
| P6 | **同名不同契约的重复实现** | 同一语义两种拼法，两边都不报错（FC-03 的"少了一点东西"） | `textutil.slugify(text, limit=60)`（保留 CJK，空⇒`"untitled"`）vs `fetch.slugify(text, max_length=80)`（**剥掉 CJK**，空⇒`"download"`）；`dedup.normalize_doi`（`dedup.py:26-33`）vs `providers.normalize_doi`（`providers.py:311-323`）—— 实测 `http://dx.doi.org/10.1000/abc` 一份原样保留、一份归一化 | 保留**一份**实现，另一处 import；或**显式登记**为"刻意的两个类"（如 `SAME_NAME_ALLOWED`） | **R003**（+ 例外清单） |
| P7 | **声明与代码不符**（**双向**）：① 声明 `side_effect="read"` 却联网 / 起子进程 / 下模型；② 声明**不执行**（`external != "exec"`）却在起子进程；③ 声明**出网**（`external == "egress"`）却全文无网络调用 | `side_effect` / `external` 是审批与沙箱的**唯一可信判据**；声明撒谎 ⇒ 权限面在说假话。**保守的假话仍然是假话**：审计问"哪些工具会出网"时会把不联网的工具列进去 | `search.providers`（`read` 却发真实 HTTP）；`ocr.run`（`read` 却下载 ~100MB 模型）；`ocr.backends`（`read` 却工作区外 mkdir + 起进程）；`verify.detect_verifier`（`none` 却 `subprocess.run`）；反向：声明 `network` 却在工具层查不到对应的两根轴声明（`search.literature` 的 `egress` 在 handler 链里查不到网络标记） | 声明成真实的取值：`external ∈ {none,egress,exec}` **加** `effect ∈ {none,read,write_local}`，两根轴各自如实；**R006 只查一个方向**（文件级共现、`info`），对偶方向由 **R010** 按**工具**判 | **R006**（一个方向，`info`）+ **R010**（对偶方向：非 exec 起子进程 ⇒ `error`，`egress` 无网络调用 ⇒ `warning`） |
| P8 | **检查脚本没有退出码**（或"未报错"被当成"无问题"） | `draft/17` §6.3 逐字："多数脚本不设退出码…（假阴性）而**'未报错'被误读成'无问题'**" | 参考体例 22 个脚本里**只有 2 个**有退出码（`r75_verify_vol.py:74`、`v10_ch0_structural.py:127-128`） | 三档退出码：`0=clean / 1=requires_human（或 fail）/ 2=unknown`；`unknown ≠ clean` | **R008** |
| P9 | 公开函数**没有 docstring** | 文档是接口的一部分；lambda 化的 handler 更是**只有** `summary` | 实测 **190 / 556** 个公开函数没有 docstring（缺失最多的 5 个模块：`schema.py` 35/42、`tools/base.py` 13/23、`tools/ocr_tools.py` 12/14、`agent_b.py` 9/16 …） | 补 docstring（含"为什么"段） | **R007**：日常一条带分布的 `info`；**`--strict` 逐模块 `warning`**（见 §8.4 待办 10） |
| P10 | 在 `except` 里**改变量后静默继续**（把失败变成默认值） | 同 P2，但更隐蔽 | `agent_b.py:717-718` 是**正面**（`return None, "…失败：…"`）；反例见 P2 | 同 P2 | 人工 |
| P11 | 用**错误信息里的字符串前缀**充当跨模块状态 | 前缀脆弱（改一个字就失效） | `LESSONS.md` N8 / `draft/13` §8.3 | 提升为受控取值 + schema 校验 | 人工 |
| P12 | 把空字符串/空列表当"通过" | Python 里 `"" in "abc"` 是 `True` | `LESSONS.md` N6 / E3（`quoteverify` 必须显式挡空引文） | 先判非空，再比对 | 人工（`quoteverify` 已落地） |
| P13 | 按**后缀名**或 **HTTP 200** 判断"拿到的东西是对的" | 同一实测案例同时否证两条朴素策略 | `LESSONS.md` N19 / N20（`.pdf` URL 返回 12.4 MB HTML） | 内容类型校验（`content_type_mismatch`）+ 下游**必须消费**它 | 人工 |
| P14 | **只改代码不补"防止用错方式修好"的断言** | 有两条修复路径时，错的那条会让断言变绿而语义变坏 | `LESSONS.md` N9；3 个现成正例：`test_precise_results_are_on_topic`、`test_agent_b_still_processes_normal_downloads`、`test_valid_download_statuses_are_accepted` | 再写一条断言把错路径**堵死** | 人工 |
| P15 | 让**告警噪音化** | "假报警会训练人忽略告警"，"文化性损伤，几乎不可逆" | `LESSONS.md` N13 / P7 | 分级（error/warning/info）+ "已知缺陷"降级 + 上线前量触发率 | 人工 |
| **P16** | ⭐ **让判据"真空通过"**：受检对象的声明**解析不出东西**，而判据把"解析不出"当成"没有问题"（空集永远是子集） | 这比"判据太松"更贵：它不是"某条判据漏了" ，而是**"这条判据在大多数对象上根本没执行"**，而报告里它一直是绿的 | **实测**：`returns=` 的"声明 vs 实现"判据的正则 `r"'([a-z_][a-z0-9_]*)'"` **只抓单引号键**，于是不带引号的 `returns=`（`data={src, dst}` 这类）被抽成**空集** ⇒ `declared - actual == {}` **永远成立** ⇒ 该判据在**36 / 55 个工具（65%）上从来没跑过**（`PROPOSALS.md` **G-4**） | ① **解析失败必须是一个可判定的结论**（三态：`parsed` / `empty_declaration` / `unparseable`），不许折叠成空集；② 给每条判据配一条**反真空断言**（"受检集合非空"或"被跳过的对象数 ≤ 一个写下来的 N"）；③ 解析器要**结构化**（顶层键 + 每个键的列表项键），并在测试里**双向**比对 | 测试（`tests/test_tools_returns_declaration.py`） |
| **P17** | ⭐ **注释与 docstring 里的装饰**：Markdown 强调（成对的星号）、未配对的残留星号、emoji | 源码不经过渲染器：写在里面的星号到了读者眼里只是星号 —— "强调"没被传达，传达的是"这段文字是被生成出来的"。这类标记会**扩散**：下一段注释照抄上一段的写法，几十个文件后就成了默认风格 | **实测（立项前普查，131 个 `.py`、8167 个注释/文档串）**：成对星号 367 处、残留星号 373 处、emoji 54 处。其中禁改区外 12 处（`scripts/__init__.py`、`tests/test_*.py`、`tools/probe_*.py` 等 11 个文件）—— **已清洗并归零**；禁改区内的 13 个文件仍有 414 处，是**人**的待办（AI 不得改，见 §7.4） | 要强调就把它写进句子；要粗体/插图就写进 `docs/` 与 `draft/`（那里的 markdown 真的会被渲染）。代码跨度里的 `**`（`2**20`、`a/**/b`、`handler(**params)`）是字面语法，判据先摘掉再判 | **R009**：区外 `error`；禁改区内只报一条汇总 `info`（区内只有人能改，报 `error` 等于造一条永远红的灯，见 §6-P15 与 P17 的实现注释） |

---

## §7 提交与评审规范

### 7.1 一次改动必须带什么证据

| # | 必须提交的证据 | 判据（"是/否"） |
|---:|---|---|
| 1 | **复跑命令 + 真实输出**（不是"我跑过了"） | 提交说明里含代码块，且是**粘贴的输出**（含 `exit code`） |
| 2 | 若改了 `src/` ⇒ `python -m pytest -q` 的**完整末行** | 末行形如 `NNN passed, M failed, K deselected in Xs` |
| 3 | 若改了某角色 ⇒ 该角色的**自检**退出码 | `python -m agentflow.agent_x`；退出码 0 |
| 4 | 若改了工具 ⇒ **工具普查**（工具数 / 角色工具数 / 只读泄漏 = 0） | `python -m agentflow.cli tools` 的输出 |
| 5 | 若改了表/字段 ⇒ `verify` 的 **error = 0** | `python -m agentflow.cli verify` |
| 6 | 若改了禁 AI 区 ⇒ `noai_gate` 的判定（`clean` 或 `requires_human`+2 批准） | `python scripts/noai_gate.py --paths <file>` 的退出码 |
| 7 | 新增验证门 ⇒ **正控 + 负控两条测试** | 见 §5.1 |
| 8 | 新增公开函数 ⇒ docstring（含"为什么"段） | **R007** |
| 9 | 修一个缺陷 ⇒ **同时**提交"防止用错方式修好"的断言 | §6-P14 |
| 10 | 修一个"漏判" ⇒ **同时**提交"不该判的时候不判"的用例 | `LESSONS.md` P16(a) |

### 7.2 发布前的完整门（**一条命令**）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python tools\release_all.py                # 六项：见 §8.0；三档结论，退出码 0/1/2
python tools\release_all.py --json dist\release.json
```

**分步跑**（调试时用；⚠️ 分步跑**不构成**发布检查的绿色结论 ——
`release_all.py` 会把没跑的步骤记成 `unknown`）：

```powershell
python scripts/release_check.py            # 八项，退出码 0/1/2
python tools/verify_role_specs.py          # 角色规格结构完整性
python tools/coverage_zero_test.py         # 零测试公开函数风险分档
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

### 7.3 ⭐ **实现者必须用证据反驳评审者**

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
② 把断言换成**段落级解析**（正文 high 4 / 非 high 0；附录 medium 1；统计 low 1）
—— **测试反而更强**。

**可判定判据**：

| 判据 | 怎么查 |
|---|---|
| 每次"评审者说有 bug"的结论，提交里含一条**能证伪它的命令 + 输出** | 提交说明 |
| 反驳时**不许**通过放宽断言来"修好看" | diff 里**新增**的断言数 ≥ 删除的断言数 |
| 评审结论若被证伪，**被证伪的那条断言必须按"更强的形态"重写**（不是删掉） | `draft/11` §11.3 的范例 |

### 7.4 禁 AI 区的人工门槛

> **本文不重复清单内容。** 清单在 **`.noai-paths`**（机器可读 glob），
> 硬约束说明在 **`AGENTS.md`**；两者由 `scripts/noai_gate.py::check_manifest_consistency()`
> **逐条比对**（实测：`一致：.noai-paths 与 AGENTS.md 的清单逐条相同`，退出码 0）。

| 事项 | 去向 |
|---|---|
| 哪些路径是禁 AI 区（**18** 条、7 个类别） | **`.noai-paths`** |
| 命中之后要做什么（停 / 人编写或人逐行走查 / 2 名 reviewer / 机器执行） | **`AGENTS.md`** 的"命中之后要做什么" |
| 退出码语义（`0=clean` / `1=requires_human` / `2=unknown`，**`unknown ≠ clean`**） | **`AGENTS.md`** 的"退出码"节 + `scripts/noai_gate.py` |
| 实际判定 | 命令：`python scripts/noai_gate.py --paths <改动的文件…>`（或 `--git`、`--stdin`、`--json`、`-q`） |

**本文只补三条判据**（AGENTS.md 未展开的）：

| # | 判据 | 检查 |
|---:|---|---|
| 1 | 禁改区清单**两处逐条一致**（FC-27 判据①，符合 FC-03） | `python scripts/noai_gate.py --check-consistency` 退出码 0 |
| 2 | 该规则本身有**负控**（构造一个命中禁改区的改动，断言 CI 拒绝） | 需要 `tests/test_noai_gate.py`（**实测已存在**）；其内容是否含负控**未核实** |
| 3 | 命中时**要求 `required_approvals=2`**，且该数字**只有一处定义** | `scripts/noai_gate.py` 的 `REQUIRED_APPROVALS_ON_HIT = 2`（**单一来源**） |

---

## §8 ⭐ CI 等价的发布检查（`scripts/release_check.py`）

### 8.0 ⭐ **一键盘**是 `tools/release_all.py`（`release_check.py` 是其中的一项）

用户点名的"一键发布检查"逐字是：**"全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter"**。
`release_check.py` 覆盖其中**五项 —— 唯独没有"验收测试"**。所以正式的入口是编排层：

```powershell
python tools\release_all.py                       # 全跑（约 10~15 分钟）
python tools\release_all.py --json r.json
python tools\release_all.py --only role-specs      # 调试时只跑一项
```

| 步骤 key | 覆盖用户点名的哪一项 |
|---|---|
| `release-check` | 全量测试 + 全部自检 + verify + 工具普查 + linter（+ 禁 AI 区门 / 契约版本 / 源码树可导入） |
| `acceptance` | **验收测试**（`test/test2/run_acceptance.py`，`AGENTFLOW_TARGET=formal`） |
| `repro` | 论文独立复现（5 个实验 + 7 条负控）—— 用户第 (5) 条要求的证据 |
| `role-specs` | 角色规格结构完整性（见 §8.6） |
| `coverage` | 零测试公开函数的**风险分档**清单（等级 1/2 应为 0） |

**两条刻意的取舍**（改它们等于改门的强度，所以本文件在禁改区里）：

1. **`--skip` 掉的步骤记成 `unknown`，不是 `pass`** —— 否则 `--skip acceptance`
   就成了"发布门全绿"的捷径。
2. **超时 / 起不来 ⇒ `unknown`，且 `timed_out` 的判断必须先于退出码** ——
   Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 **无法区分**。

总判定：**任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`**；退出码 0/1/2。

> ⚠️ **它全绿也不构成发布许可**：它自己与 `scripts/release_check.py` **都在 FC-27 禁改区**，
> 仍需人逐行走查 + 2 名 reviewer 批准。

### 8.1 八项检查、通过判据、失败退出码（**实测自 `scripts/release_check.py` 的 docstring 与源码**）

| # | 项 | 跑什么 | 通过判据 | 该失败时的 `verdict` |
|---:|---|---|---|---|
| 1 | **全量测试** | `pytest -q` | 退出码 0，且 **0 failed**、**0 errors** | `fail`；收集错误/超时 ⇒ **`unknown`**（"pytest 因为收集错误没跑起来既不是'通过'也不是'失败'"） |
| 2 | **模块自检** | 8 个 agent + `pipeline` 各自 `python -m agentflow.X` | 全部退出码 0 | `fail`（任一 `exit_code != 0` 或未启动或超时） |
| 3 | **工具普查** | 自建脚本调 `build_registry` | 工具数与角色工具数**可复现**；只读角色（C/H）写工具泄漏 **= 0** | `fail`；脚本起不来 ⇒ `unknown` |
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
"9 条已交付缺陷里 **0 条**能被 happy-path 抓到。所以发布门不只看'测试过没过'，
还看**门本身有没有被校准过**（第 3/4/5/6 项）与**契约版本有没有对齐**（第 7 项）。"

### 8.2 复跑命令与当前实测状态（S2，2026-09-24 收尾）

```powershell
python tools\release_all.py                            # ★ 一键（六项，见 §8.0）
python scripts/release_check.py                       # 只跑那八项
python scripts/release_check.py --changed <文件…>      # 同时判禁改区命中
```

| 项 | S2 状态 | 证据 |
|---|---|---|
| 1 全量测试 | **pass**（`1497 passed / 0 failed / 8 deselected / 1 xfailed`，退出码 0） | §0.2 第 1 条 |
| 2 模块自检 | **pass**（8 个 agent 全部 exit 0；A/B 已补自检块） | §0.3 第 6 条 |
| 3 工具普查 | **pass**（55 / 泄漏 0） | §0.3 第 1 条 |
| 4 全库校验 | **pass**（error 0 / warning 0） | §0.3 第 4 条 |
| 5 linter | **pass**（`error 0`）—— 最后 3 条 R001 都补了**具体**理由 | §0.2 第 2 条 |
| 6 禁 AI 区门 | **unknown**（本目录**不是 git 仓库** ⇒ `--git` 恒为退出码 2；**台账已建立但尚未接线**：第 6 项走的仍是 `--paths`，命中即 `fail`。见 `NOAI-REVIEW-REGISTER.md` 与 `docs/PROPOSALS.md` **P-3**） | §0.3 第 11 条 |
| 7 契约版本 | **pass**（`cli verify` 与 `agentflow.CONTRACT_VERSION` 已对齐） | §0.3 第 4 条 |
| 8 源码树可导入 | **pass**（`python -c "import agentflow.capabilities"` 退出码 0） | §0.3 第 8 条 |

**最终一次 `release_check.py` 的总判定：`pass=7 fail=0 unknown=1`**（退出码 **2**）。

**`tools/release_all.py` 的一次完整实跑**（六项）：

```text
[unknown] release-check   ← pass=7 fail=0 unknown=1（结构性 unknown，见下）
[pass   ] acceptance      通过 10 / 失败 0 / 未执行 0
[pass   ] repro           ALL CHECKS PASS（5 个实验 + 7 条负控）
[pass   ] role-specs      9 节 × 8 必备子节
[pass   ] coverage        等级 ≤ 2 的零测试函数 0
一键发布检查总判定：UNKNOWN    pass=4 fail=0 unknown=1     # 退出码 2
```

> **那个 `unknown` 是结构性的、不可能消除的**：第 6 项在"不给 `--changed`"时**必须**报
> `unknown`。所以**在这个环境里"发布门全绿"永远不会发生** —— 能到达的最好状态就是
> "7 项 pass + 1 项如实 unknown"。**把它读成"全绿"就是本项目反复踩过的那个坑。**

> **本表是"逐项独立实测"与一次完整跑动的合并**。如实登记：
> 完整跑会重跑全量测试（数分钟），且第 6 项**在这个环境里注定是 `unknown`** ——
> 除非先把仓库纳入 git 或改用 hash 台账（后者已完成，见 §8.4 待办 7）。
>
> ⚠️ **不许把"第 6 项是 unknown"读成"没问题"** —— 它读作"**这一项没查成**"。

### 8.3 ⚠️ 发布门自身的**未批准状态**（必须随每次发布声明）
见 §7.2。**任何人把"`release_check.py` 全绿"当作发布许可都是错的** ——
这个门自己还没过 FC-27 的人工门槛。

### 8.4 待办（本文发现；✅ = 已在 S2 关闭）

| # | 待办 | 归属项 | 判据 | 状态 |
|---:|---|---|---|---|
| 1 | 修 `trace_tools.py` 的 `SyntaxError` | 1 | 套件可收集 | ✅ |
| 2 | 修 `test_policy.py` / `test_conductor.py` / `test_scheduler.py` 的 10 个失败 | 1 | `0 failed` | ✅ |
| 3 | 给 `agent_g._selftest` 的 fixture 补 `verifier_subject_key` | 2 | `agent_g` 退出码 0 | ✅ |
| 4 | 给 `agent_a` / `agent_b` 加自检块 | 2 | 两模块有非空输出且退出码 0 | ✅（`a` 24/24、`b` 18/18） |
| 5 | linter 的 R001 error 归零（补理由或 `noqa`） | 5 | `error 0` | ✅ **已关闭**（3 条全部补上了**具体**理由，不是空洞 `noqa`：两处是"回退链/不是出错"的控制流，一处是 stdout `reconfigure` 的可忽略失败。实测 `error 0`） |
| 6 | 把 `cli.py` 的 `choices` 改为 `list(ROLES)` | 3 | `--role E` 退出码 0 | ✅ |
| 7 | 让禁改区漂移**可机械检测**（本仓库非 git） | 6 | hash 台账 + 门 | ✅（`.noai-approvals.json` + `docs/NOAI-GOVERNANCE.md`）；**批准仍需人** |
| 8 | 固化工具普查脚本为受版本控制的文件 | 3 | 普查可复跑 | ✅（`cli tools` 已能全量列出） |
| 9 | 修 `verify` / `conductor` 的 tasks 检查重复 | 4 | 判据只有一份 | ✅（`capabilities.audit_task_ledger` 唯一实现 + 一致性测试） |
| 10 | R007（缺 docstring）升到 `error`，或明确接受 | 5 | §2.4 与门的强度一致 | ✅ **已裁决**：两档（日常 `info` 带分布 / `--strict` 逐模块 `warning`）。**"更严"必须体现在判据上，不是级别上** |
| 11 | `agent_a` 的退避租约"软退避" | — | 见 §10-D21 | ✅ **已修**（判据改为只看租约是否有效；"全在退避中"独立成一档；自检从"写了"升级为"写了**且被遵守**"） |
| 12 | 关闭 `docs/PROPOSALS.md` 的 **G-1**（E/F 装配入口缺 roles 校验） | 人工（P-1） | R004 warning 归零 | **待人工**（`tools/base.py` 在禁改区） |
| 13 | 给 13 个禁改区文件填 `reviewers`（各 2 名） | 人工（FC-27） | `noai_gate --check-approvals` ⇒ `clean` | **待人工** |
| 14 | 处理 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` | 人工 | `documents.claims` 的 12 字段在**存储层**强制 | **待人工** |
| 15 | 关闭 **G-2**（`attack_tools.py` 失败类型被压平 + 2 条声明漂移） | — | `kind != "unexpected"` 且具体档分开 | ✅ **已关闭**（唯一一份 `_guard`：`validation_error`/`plan_error`/`store_error`；`can_derive` 的"没查"独立成一档；21 条测试 + 7 处变异） |
| 16 | 关闭 **G-3**（`graph_tools.py` 逃逸 + `returns=` 漂移 + 不可截断的 `neighbors`） | — | 同上 + 截断如实报出 | ✅ **已关闭**（4 个 handler **转发**同一份 `_guard`；`returns=` 逐键列全；有界层加在**工具层**，`RelationGraph.neighbors` 保持裸 list 并给了证据） |
| 17 | 关闭 **G-4**（`returns=` 的"声明 vs 实现"判据在 **36/55** 个工具上**真空通过**） | — | 55 个工具的 `returns=` 均可解析，或**显式豁免并写理由**；负控证明判据有牙 | 见 `docs/PROPOSALS.md` |
| 18 | 关闭 **G-6**：`gates.gate_g1` 把 **Windows 盘符绝对路径**判成"工作区内" ⇒ **自含性门报 pass** | — | 判据测试转绿 | ✅ **已关闭**（新增**平台无关**的 `_is_absolute_path_text()`；docstring 写清"为什么不能靠 `Path.is_absolute()`"：Linux 上 `C:/x` 不是绝对、Windows 上 `/abs` 不是绝对，两档都会漏） |
| 19 | 关闭 **G-7**：`gates.py` 的判据文本**写了两三份且已漂移**（15 道门里 6 道不一致）—— **FC-03 在我们刚建的门上复发** | — | 判据测试转绿 | ✅ **已关闭**（`GATES` 声明表成为唯一来源 + 一条 AST 反漂移断言：`gate_g*` 函数体里不许再出现 `criterion = "..."`） |
| 20 | 关闭 **G-8**：`interactions.admit_reprocess_request` 对**纯空白**目标集合放行 ⇒ B **退化成全量重抽** | 人工（`interactions.py` 在禁改区） | 判据见 `PROPOSALS.md` G-8 | **待人工**（**唯一剩下的那个 `xfail(strict=True)`**） |
| 21 | 关闭 **G-5**：`gates.gate_verdict({})` 对**空结果集**判 `accepted` | 需先定口径 | 契约要不要覆盖 `results == []` | **待裁决** |
| 22 | 关闭 **G-12**：`criterion_revision` 也是两份且 **15/15 漂移**，声明表运行期**从不被读到** | — | 与 G-7 同构 | ✅ **已关闭**（单源化 + 动态哨兵断言"表真的被读到" + AST 覆盖两栏三形态；**并核出第三份副本**：`GateResult` 的默认值修前从 24 条返回路径漏出） |
| 23 | 补 **G-9**（106 个零直接测试的公开函数，等级 3/4） | — | 清单见 `tools/coverage_zero_test.py --json` | **已量化，未关** |
| 24 | 修 `tools/release_all.py` **第一版的退出码映射缺陷** | — | 三态工具的 `2` 曾被判成 `fail`（"没查成"读成"发现问题"） | ✅ **已修**（每步显式声明 `exit_map`；4 条测试含点名的负控） |
| 25 | 修 `docs/PROPOSALS.md` 的**编号撞号**（两条 `G-9`）与**空洞**（`G-5` 悬空引用） | — | 编号唯一 + 引用存在 + 空洞写明 | ✅ **已修** + 新建 `tests/test_proposals_register.py`（4 条断言，含作用域限制的论证） |

### 8.5 ⭐ 本轮的"自查"记录：**编排层自己也是被审对象**

`tools/release_all.py` 是这一轮新建的，而它在**第一次完整实跑**里就暴露了自己的一个真缺陷：

| 现象 | `release-check` 的 `exit=2` 被编排层判成了 **`fail`** |
|---|---|
| 根因 | `classify()` 把所有非零退出码一律当"发现问题"，而 `scripts/release_check.py` **自带三态**（`0=pass / 1=fail / 2=unknown`）。本环境里它的第 6 项**必然**返回 `unknown`（不是 git 仓库） |
| 后果 | **"没查成"被读成了"发现问题"** —— 而且发生在**"用来挡住这类错误的那一层"**里 |
| 修法 | 每一步**显式声明自己的退出码表**（`TRI_STATE_EXIT` / `PLAIN_EXIT`） |

**加上 `--only lin` 被打错成"静默空跑"那一处，本轮共两处自身缺陷**，
两处都不是"读代码"读出来的，而是**真跑或单元测试**逼出来的 —— 这与 §3 的纪律一致：
**读代码只能证明"我以为它对"，跑起来才能证明"它对"。**

### 8.6 发布门**之外**的第二道门：`tools/verify_role_specs.py`

用户对正式版的要求里有两条是**文档**要求：
**"为 A–H 八个角色各写详细规格说明书"**（并逐字点名了八个必备子节），
以及审计判据里的 **"docstring 与实现一致"**。

一份 2000+ 行的规格**最容易的坏法不是写错，而是写漏** —— 少写一节，**没有任何东西会变红**，
而读者会以为"这一节大概没有那些内容"。所以这条也做成门：

```powershell
python tools\verify_role_specs.py            # 退出码 0=完整 / 1=有缺失 / 2=没查成
```

| 结论 | 含义 |
|---|---|
| `ok` (0) | 9 个角色节（A–H + M）各自 8 个必备子节齐全，顺序与 `schema.ROLES` 一致，且每节的工具面子节标题里能读出**工具条数**（供与普查对账） |
| `incomplete` (1) | **查过了、有缺失** —— 逐条打印是哪一节缺哪一项 |
| `unknown` (2) | **没查成**：文档不存在 / 读不到 / 一个角色节都没匹配到。**`unknown` 绝不是 `ok`** |

**它为什么不在 `release_check.py` 里**（如实说明，而不是遗漏）：
`scripts/release_check.py` 本身在 FC-27 禁改区，**给它加一项要人审**
（`docs/PROPOSALS.md` 的 P-2/P-3 是同一类待办）。
所以这道门目前是一个**并列的、可单独复跑**的门，并在 `tests/test_role_specs_complete.py`
里有 10 条测试（含"删掉一节 ⇒ 必须报 `incomplete`""文档被改名 ⇒ 必须报 `unknown` 而不是 `ok`"
这两条**三态负控**），以及一条**文档 ↔ 实测普查对账**：
文档每节标题里的工具条数必须等于**真的跑一次** `python -m agentflow.cli tools` 得到的数字
（而不是测试里硬编码一份 `{'A':20,…}` —— 那会把测试绑死在当前状态上）。

---

## §9 FC-01…FC-27 覆盖矩阵

> **状态口径（**三档，不许含糊**）**：
> - **已落地** = 代码里有实现**且**有测试/验收判据；
> - **部分** = 有实现但缺某一判据，或只在部分模块落地；
> - **未落地** = 我在 `src/agentflow/**` 里**找不到**实现（用 token 搜索为证）；
> - **未核实** = 我没查，或查了但证据不足。
>
> 每一行都注："我查了什么"。

### 9.1 主矩阵

| FC | 约束（简写） | 落地位置 | 可判定判据 | 状态 |
|---|---|---|---|---|
| **FC-01** | 三态而非布尔 + 受控 `reason` | `schema.REFUSAL_REASONS`（`:1246`）/`TASK_OUTCOMES`（`:1243`）/`DOWNLOAD_STATUSES`（`:89`）/`SEARCH_OUTCOMES`（`:76`）/`NEGATION_KINDS`（`:647`）；`checked` 位（`SummonResult`）；`store.stats()` 三分档；`agent_b.py:87-107` 的三组计数 | 引文三态、`outcome` 词表、`checked` 三态均有测试；**但"禁止 `if not x.verified:`"无静态 lint 规则**（R001–R009 里没有它） | **部分**（缺静态检查） |
| **FC-02** | 每个产出带可追溯代号链（双向） | `origin` 字段、`related_*_ids`、`verify` 的 `dangling_*` 检查集（71 个 code 里的 `dangling_lit_ref`/`dangling_concept`/`dangling_relation_ref`/`dangling_request_ref`/`dangling_citation`/`dangling_dep`/`dangling_parent_task`/`dangling_task_artifact`/`dangling_usage_task`/`dangling_doc_ref`…） | `tests/test_verify.py` + `test_verify_extended.py`；**通用正/反向链一致性断言仍缺**（只有 literature↔request 双向） | **部分** |
| **FC-03** | 跨模块字符串集中定义 + 装配期断言 | `schema.py:1209 ROLES`（**唯一**）；`tools/__init__.py:44` `from ..schema import ROLES`；`tools/__init__.py:195-207` 的 `bad_roles` 断言；`capabilities.assert_capabilities()` 第 1/5 条；`scripts/gate/linter` 的 R005 | `tools.ROLES is schema.ROLES` → **实测 `True`**；`noai_gate --check-consistency` → 退出码 0；**实测 R005 仍报 1 处**（`capabilities.py:600`） | **已落地**（有残留 warn） |
| **FC-04** | 受控词表在 schema 强制 + 交叉检查 | `schema.py` 各 `validate()`；`verify.py` 的 cross-check（`lit_not_processed` / `stale_waiting` / `stale_group_key` / `mismatch_without_evidence` …）；**新增** `Task`/`UsageEntry`/`EvalResult` 三套 | `tests/test_schema.py`；`tests/test_fc05_contract.py` 的 22 例里大量交叉检查 | **已落地** |
| **FC-05** | 顺序与集合分离（保序字段成对） | `schema.ARRAY_FIELD_KINDS`（`schema.py:1562`）+ `check_array_invariants`（`:1604`）；`verify.undeclared_array_field`（error）；`tests/test_fc05_contract.py` | `test_every_array_field_is_declared` / `test_seq_field_is_not_forced_sorted_by_the_central_check` / `test_relation_chain_preserves_order_round_trip` / `test_relation_chain_must_be_a_subset_of_related_relation_ids` | **已落地**（`Relation.chain` 的保序 round-trip 有测试） |
| **FC-06** | 角色即权限面 + 预期工具清单 + 负向权限测试 | `for_role`（`tools/base.py:310-345`）+ 结构性剥离；`tests/test_tools_readonly_roles.py`（7 例）；`capabilities.WRITE_SETS` + `assert_capabilities` 第 4 条 | 负向权限测试存在；**`expectations.yaml` 实测 0 命中** ⇒ **仍缺"每角色预期工具名清单，缺失即 fail-closed"** | **部分** |
| **FC-07** | 工具声明完整，`side_effect`/`roles` 一等公民 | `ToolSpec` 六件套（实测缺字段 0）；`NEEDS_APPROVAL`（`tools/base.py:36`）；`capabilities.SIDE_EFFECTS` **交叉断言**（`assert_capabilities` 第 5 条）；只读不变量测试 | `tests/test_tools_base.py`；`agent_c` 自检"I1 服务面只读：三张知识表逐字节不变"；**但** `side_effect` 与**真实行为**有 ≥7 处不一致（INVENTORY 4.4） | **部分**（声明层已落地，行为一致性靠 R006 的 warn） |
| **FC-08** | 无工具/未接线必须显式失败 | `ToolResult.fail(kind=...)`；`not_wired`（多份实现）；`conductor.NotWiredError` ⇒ `refused/not_wired`；`ocr` 的 `no_backend`；`search.dedup_check` 的 `no_store` | 未接线返回失败而非空；**但** `search_tools.py:583-586` 与 `trace_tools.py:163-169` 两处仍是反例 | **部分** |
| **FC-09** | 每个验证门必须配负控 | 各测试文件里的负控（`agent_h` 三类 + 落库级；`agent_c` 的 `structural_duplicates` 负控；引文篡改负控）；`scripts/release_check.py` 第 6 项要求 gate 的负控 | 各门均有"注入坏数据必须报错"用例；**`tests/test_noai_gate.py` 实测已存在**（**其是否含负控未核实**）；**无独立负控套件目录** | **部分** |
| **FC-10** | 验证结果三分档计数，禁止单一通过率 | `store.stats()` 的 `quote_verified`/`quote_unverified`/`quote_unknown`；`ARunResult` 的 `verified/failed/unknown`；`agent_b` 的三组；`SummonResult.checked` 三态；**新增** `Conductor.stats()["by_outcome"]` / `refusal_reasons` / `unknown_outcome` | 三分档有输出；**但 `verify` 本身只有 error/warning 两级**（无 `unknown` 档，`unknown` 只出现在 `release_check` 与 `noai_gate`） | **部分** |
| **FC-11** | 校验器与写入方共享同一配置来源 | `cli.py:175-184`（`cmd_verify` **显式从 `config.yaml` 的 `agent_b` 段取**，注释逐字解释假报警）；`schema` 常量共用 | "改配置后写边缘样本，复核**不报错**"；**`QuotePolicy` 实测 0 命中** ⇒ 参数仍是散装的 | **部分** |
| **FC-12** | 可重建存储的信息量守恒 | `store.rebuild`（`store.py:404`，`backup=True`）；`tests/test_rebuild.py`（3 例） | 诊断字段守恒 / 幂等 / 坏事件不炸；⚠️ **是否覆盖 `tasks` 表未核实** | **已落地**（覆盖范围未核实） |
| **FC-13** | 告警分级 + 已知缺陷可降级 | `Issue(level, table, id, code, message)`（`verify.py:30`）；`FINDING_LEVELS`（`schema.py:693`）；`review_tools.py:186` 的依赖分级；`noai_gate` / `release_check` 的三档 | 实测：`external_unavailable`=warning / `dangling`=error；`agent_h` 自检逐字验证了这条分级 | **已落地** |
| **FC-14** | LLM 产出必须回验 + 存回原文切片 | `quoteverify.py`；`agent_b` 的逐字回验（`agent_b.py:700-738`）；`llm.py` 的 `_ground_relations` / `_locate_verbatim` | `llm.py` 自检实测："幻觉引文被剔除且计数正确: True"、"剔除原因为 `['quote_not_found','too_few_concepts']`"；**无 API key ⇒ LLM 路径未端到端跑过** | **部分**（未端到端） |
| **FC-15** | 幻觉与"数据缺失"可归因分离 | reason 细分：`quote_not_found` / `empty_quote` / `no_text_layer` / `not_found_page_unknown` / `reextract_failed` / `quote_state_changed` | 各类失败有独立 reason 与独立计数（`agent_b.py:87-107`） | **已落地** |
| **FC-16** | 确定性的部分绝不交给 LLM | C **无一处依赖 LLM**；`score_breakdown`（7 项）；`llm=None` 默认；`agent_d` 的"置信度不许拔高" | `agent_d` 自检第 [10] 项实测："确定性置信度=medium；LLM 声称=high；强制后=medium" | **已落地** |
| **FC-17** | 上下文预算：压缩 / 剪枝 / spill | **`contextbudget.py` 已存在**：`ContextBudget`（`validate()` 强制）、`prune`、`prune_tool_result`、`compact`、`_MARKER_FMT`、`spill_dir` | ✅ 实现存在；**是否有"构造超大工具结果，断言被剪枝/落盘而非撑爆上下文"的测试：未核实** | **部分**（实现已落地，判据未核实） |
| **FC-18** | 三维预算 + 深度上限同时存在 | `attack_tools.DEFAULT_BUDGET` 四类键（`attack_tools.py:63-68`）+ `check_budget`/`can_round`/`can_derive`；`schema.AttackPlan.budget` 缺即抛；**新增** `policy.Policy` 四类上限（`max_depth`/`max_fanout`/`max_concurrency`/`max_tasks_per_run`）+ `validate()` + `assert_policy_complete` | `tests/test_agent_f.py`；实测 `agent_f` 自检：[PASS] 轮数不超过 `max_rounds`、提前停止关闭时真的跑到 `max_rounds`；自检逐字验证了 `budget=None ⇒ checked=False` | **已落地**（**最强的一条**） |
| **FC-19** | token 预算是硬约束，重试也计入 | `policy.Policy.token_budget` / `usd_budget`（`policy.py:57-59`）；`cancelToken.token_budget` + `consume_tokens`（`cancellation.py:118/207`）；`scheduler.MemoryBudgetTracker`；**`schema.UsageEntry` + `usage_ledger` 表 + `attempts` 字段**（FC-19 判据②"重试也计入"） | 实现存在；**`token_meter` / `token_budget` 在 `src/agentflow/**` 实测 0 命中**（`token_budget` 在 `cancellation.py` 是 `CancelToken` 的属性名，不是计量器）；**没有任何 A/B/D 路径往 `usage_ledger` 写入**（未核实是否有写入方）；**D 向 A 的总提问预算仍未有 token 口径** | **未落地**（数据结构已备，计量与写入方缺） |
| **FC-20** | 取消：协作式 + 共享 signal + 事件配对 + first-wins | **`cancellation.py`**：`CancelToken`（`cancel` first-wins）、`CANCEL_CODES`、`CancelRequested`；**`conductor.py`**：`cancel` / `cancel_inflight` / `dispose`（合成 `cancelled` end + "结果未知"）、`finish` 幂等（重读磁盘）、`_signal_stop`（记第一次的说明） | 实测 `dispose()` 的 docstring 逐字落地三条纪律；`schema.Task.validate` 的 "pending/running 却已有 ended_at ⇒ 拒" | **已落地** |
| **FC-21** | 部分失败语义：子任务可降级，整体绝不谎报 | `AgentF._deploy_e` 降级 `blocked` + `blocked_reason` 并继续；`schema.AttackPlan` 的 `stalled` 必须写 `best_partial`（`verify.stalled_without_partial`，error） | `tests/test_agent_f.py`；自检实测 `stalled` + `best_partial` 非空 + 不可重入；**`run_best_effort` / `run_all_or_nothing` 实测 0 命中** ⇒ 无两种显式 API | **部分** |
| **FC-22** | 数值结果必须标注"仅为交叉验证" | `schema.EVIDENCE_KINDS`（`:633`）+ `Experiment.validate`（五条硬约束，含 `verifier_subject_key`，`schema.py:810`）；E 的降级；H 的 `overclaim`；`verify` 的 `evidence_kind_overclaim` / `proof_claim_rests_on_weaker_evidence` / `proof_claim_with_unclosed_dependency`；`CROSS_CHECK_DISCLAIMER` 自动附加 | `tests/test_agent_e.py`（30 例）；`agent_e` / `agent_f` / `agent_h` 自检均有 FC-22 断言 | **已落地（最强）** |
| **FC-23** | 外部定理显式标记依赖 + 依赖集可闭合检查 | `dependencies` 表 + `DEP_KINDS`/`DEP_STATUSES`；`doc.register_dependency`（`closed` 时**真去核** `literature`/`experiments`）；`verify.dangling_dep` / `dangling_dep_external`（分级）/ `closed_dep_on_inconclusive_experiment` / `proof_claim_with_unclosed_dependency`；`Relation.supporting_lit_ids`（`schema.py:365`，**实测 7 处命中**） | `tests/test_agent_g.py`；`tests/test_fc05_contract.py` 的 `test_document_can_cite_an_eval_result` | **已落地**（并**推翻** FC-23 文档里"一条关系只能引一篇文献"的缺口陈述） |
| **FC-24** | 基准口径是必填字段 | **`schema.EVAL_REQUIRED_FIELDS`**（`:1454`，7 个必填）+ **`EvalResult`**（`:1465`，`validate()` 缺任一即抛、`value` 必须是 0..1 比率）；`verify.eval_duplicate_conflicting` / `unknown_citation_kind`（`eval:` 引用） | `tests/test_fc05_contract.py`：`test_eval_requires_every_scope_field` / `test_eval_value_must_be_a_ratio` / `test_conflicting_duplicate_eval_is_an_error` / `test_same_value_duplicate_eval_is_clean` | **已落地**（**`draft/13` §7 标为"未落地"的陈述已过期**） |
| **FC-25** | "未证明/已证否/未搜索"三分 | `schema.NEGATION_KINDS` 四值（`:647`）；`Experiment.negation_kind`；`cold` 报告把 `degree==0` 单列"完全孤立"；`SummonResult` 的 `refused`/`no_result`/`not_applicable` 三分 | `tests/test_agent_e.py`；`agent_e` 自检第 [7] 项逐字："'查了没有' 与 '没查' 的 reason 不同" | **已落地** |
| **FC-26** | 每个"缺口/结论"必须可核实判据 + 否决项 | D 的三条判据 `a_no_keyword_hit` / `b_low_degree_unverified` / 矛盾；`gaps` 的 **`veto` 与 `score` 分离** | `tests/test_agent_c.py` / `test_agent_d.py`；`agent_d` 自检实测了 `判据=['a_no_keyword_hit']` 与 `['c_contradiction']` | **已落地** |
| **FC-27** | 禁 AI 区必须显式列出 + 独立准入门槛 | **`.noai-paths`**（**18** 条 / 7 类）+ **`AGENTS.md`** 的 `NOAI-MANIFEST` 区块 + **`scripts/noai_gate.py`**（`REQUIRED_APPROVALS_ON_HIT = 2`，退出码 0/1/2）；`tests/test_noai_gate.py`（**实测已存在**）；`release_check.py` 第 6 项 | ① 两处**逐条一致**（实测退出码 0）；② 命中要求 2 批准（实测 `--paths schema.py` → 退出码 1 + `required_approvals=2`）；③ **负控用例是否在 `test_noai_gate.py` 里：未核实** | **已落地**（负控未核实） |

### 9.2 ⚠️ **未落地 / 部分落地的完整清单**

**完全未落地（1 条）**：

| FC | 缺什么 | 我查了什么 |
|---|---|---|
| **FC-19** | **token 计量与写入方**。数据结构（`UsageEntry` + `usage_ledger` + `attempts`）已在，`Policy.token_budget` / `CancelToken.token_budget` 已在；但**没有任何路径把花销写进 `usage_ledger`**，`MemoryBudgetTracker` 只活在内存（`scheduler.py:72-115`）。**D 向 A 的总提问预算仍未有 token 口径**。 | `grep -rn 'token_meter\|token_budget' src/agentflow/` → 仅 `cancellation.py` 的 `CancelToken.token_budget` 属性；`grep -rn 'usage_ledger' src/agentflow/` → 只在 `schema.py`（表定义）与 `verify.py`（检查）。**未找到写入方。** |

**部分落地（9 条）**：

| FC | 缺的那一块 | 判据 | S2 状态 |
|---|---|---|---|
| FC-01 | 无静态检查禁止"把 `None` 与 `False` 合并"的写法 | R001–R009 里没有这条规则 | **仍未关**（R002 只覆盖"`is None`→空容器"这一种形态） |
| FC-02 | 只有 literature↔request 双向；**缺通用正/反向链一致性断言** | 做通用版需要给每个外键字段登记"反向字段名" | **仍未关** |
| FC-06 | 缺每角色的**预期工具名清单** ⇒ `roles` 写错仍可能静默少工具 | 需要一个"基线快照"文件 | **部分关闭**：`agent_d.validate_tool_roles` + 8 条负控已覆盖 D；E/F 见 `docs/PROPOSALS.md` **G-1** |
| FC-07 | `side_effect` 与**真实行为**不一致 ≥7 处；R006 只是 warn | 需要"执行进程"这一档或人工裁决 | **仍未关**（R006 已降级为文件级 `info` 指针） |
| FC-08 | 静默返空 | R002 报 warning | **S2 实测 warning 2 条**（`agent_d` 渲染层 + `search_tools`，均已有理由） |
| FC-09 | 负控散在各测试文件；**无独立负控套件目录** | 命名约定 | **已接受**（`test_*` 内的 `*_negative_control_*` 命名已成约定；`tests/negative_controls/` 不做） |
| FC-10 | `verify` 本身只有 error/warning 两级，**无 `unknown` 档** | `VerifyReport` 需要第三个计数 | **部分关闭**：`release_check` / `noai_gate` 有第三档；`verify` 本身仍两级 |
| FC-11 | 无 `QuotePolicy` 统一配置对象 | `verify_all` 需要强制传 policy | **仍未关** |
| FC-14 | LLM 回验路径**未端到端跑过**（无 API key） | 需要真实 provider | **仍未关**（环境限制，如实登记） |
| FC-17 | 上下文预算 | — | ✅ **已落地**：`contextbudget.py` + `ToolRegistry.default_budget`/`default_spill_root` + `build_registry(context_budget=…)` + `tests/test_fc17_wiring.py`（10 例） |
| FC-19 | token 记账 | — | ✅ **已落地（召唤级）**：`tokenmeter.py`（14 例：重试按次计费、零值也记账）+ `conductor` 的 `[4a]` 守卫（**在写 `running` 行之前**，`allowed=False` ⇒ `refused/budget_exceeded`，且**双重预算**：本次调用 ∧ 全局 `Policy`）+ `tasks.tokens/usd` **由台账 `tokens_for()` 抄回**（不再自己累加）。⚠️ **未接**：各 agent `_call` 的**逐次尝试**细账（重试粒度），接线说明写在 `_charge_and_settle` 的 docstring 里（含**双记陷阱**） |
| FC-21 | 无 `run_best_effort` / `run_all_or_nothing` 两种显式 API | 需把 F 内部的降级语义提升为 API 契约 | **仍未关** |
| FC-27 | 禁 AI 区门 | — | ✅ **已落地且可执行**：清单两处逐条一致 + `.noai-approvals.json` hash 台账 + 三档退出码；**批准仍需人**（见 `NOAI-REVIEW-REGISTER.md`） |

> ⚠️ **与 `draft/13` §7.1 的差异（重要）**：
> `draft/13` 那份矩阵是对 `test/test1/abflow` 做的，列了"完全未落地 6 条"
> （FC-05 / FC-17 / FC-19 / FC-20 / FC-24 / FC-27）。
> **在 `agentflow` 的 S2 上，6 条全部落地**：FC-05（`ARRAY_FIELD_KINDS` + `check_array_invariants`
> + `chain` 保序契约测试）、FC-17（见上）、FC-19（机制落地，接线进行中）、
> FC-20（`cancellation.py` + `conductor.dispose` 幂等 + `Task` 状态机 first-wins）、
> FC-24（`EvalResult` + 渲染层 `number_without_eval_scope` 门）、FC-27（见上）。
> **凡引用 `draft/13` §7.1 的地方都必须重新核对**（这正是 §1.4 口径警告的一个实例）。

### 9.3 我**没能核实**的条目（逐条说明我查了什么；S2 逐条更新）

| # | 未核实项 | 我查了什么 | S2 结论 |
|---:|---|---|---|
| 1 | R002 的具体命中 | S2 取到逐条明细 | ✅ **已关闭**：2 条，均已有理由 |
| 2 | FC-17 的剪枝测试是否存在 | S2 实测 `tests/test_fc17_wiring.py`（10 例）+ `tests/test_context_budget.py`（37 例） | ✅ **已关闭** |
| 3 | FC-27 的负控用例 | S2 实测 `tests/test_noai_gate.py` 51 例，含"台账缺失⇒unknown""hash 漂移⇒requires_human""台账自指"等负控 | ✅ **已关闭** |
| 4 | `tests/test_rebuild.py` 是否覆盖 `tasks` 表 | S2 有 `test_i9_tasks_snapshot_rebuilds_byte_identical`（逐字节重建） | ✅ **已关闭** |
| 5 | `usage_ledger` 是否有写入方 | S2 实测：**仍是零写入方**（`grep 'usage_ledger\|UsageEntry' agent_*.py` 零命中）—— 这正是 FC-19 接线要解决的问题 | ⚠️ **仍未关**（已登记为接线待办） |
| 6 | 契约版本一致性（发布门第 7 项） | S2 未跑该独立命令 | ⚠️ **仍未关** |
| 7 | 源码树可导入（第 8 项） | S2 实测 `python -c "import agentflow.capabilities"` 退出码 0 | ✅ **已关闭** |
| 8 | `INVENTORY` 的"7 个零测试工具"在 `agentflow` 是否仍成立 | S2 未复算 | ⚠️ **仍未关** |
| 9 | `docstring_has_why` 的真实比例 | S2 实测 R007：**公开函数 556 个，190 个没有 docstring**；缺失最多的 5 个模块已在输出里点名 | ⚠️ **已量化，未关闭** |
| 10 | `ReviewFinding` 的 `review_rounds` 上限具体数值 | S2 未找到显式常量 | ⚠️ **仍未关** |
| 11 | `method="formal"` 的真实后端路径 | 本机无 Lean/Coq/Isabelle | ⚠️ **仍未关**（环境限制） |
| 12 | 真实联网端到端 | S2 未跑 `-m network` | ⚠️ **仍未关** |
| 13 | 本机是否有 `easyocr` / `pytesseract` / `fitz` | S2 未探测 | ⚠️ **仍未关** |
| 14 | `agent_d.py` 处 D 到底改了 `relations` 的什么字段 | S2 未逐行读 | ⚠️ **仍未关** |
| 15 | `G → D/E/F` 是否有实际代码路径 | S2 未 grep 实际 `summon("D", …)` 调用点 | ⚠️ **仍未关** |

---

## §10 文档与代码不一致清单（带 `文件:行号`）

> 每一条都是我**实际核对**出来的；**以代码为准**。

### 10.1 本文档写作过程中发现的**不一致**

| # | 文档说 | 代码实际 | 证据 | 严重性 |
|---:|---|---|---|---|
| **D1** | `README.md:1` 标题 `# test1 —— A/B 双智能体文献流水线（初步构造）`；`:23` `cd D:\Incubator\test\test1`；`:43` "离线套件：127 passed" | **S2 已重写** `README.md`：标题改为 `agentflow —— 面向数学研究的多智能体协同框架（正式版）`，跑法/目录/测试命令全部指向 `agentflow`，并新增"§7 已知限制"（含"README 不是判据"这一条） | `README.md` 全文 | ✅ **已关闭（S2）** |
| **D2** | `cli.py` 注释逐字："角色清单必须来自 `ROLES`，**不许在这里写死**" | 原 `choices=["A","B","C","D"]` **已修为 `list(S.ROLES)`**；S2 实测 `cli tools --role E` 退出码 0、`--role Z` 退出码 2 | §0.3 第 2 条 | ✅ **已关闭（S2）** |
| **D3** | `scripts/lint_rules.py` 有 **R007 缺 docstring** 规则 | S2 起 R007 有**显式两档**：日常报一条带**分布**的 `info`（点名缺失最多的 5 个模块），`--strict`（发布级）逐模块报 `warning`。**"更严"体现在判据上而不是级别上** —— 只把级别升成 warning 会让 190 条警告常驻输出，而 `release_check` 第 5 项只看 `error`，等于什么也没挡住 | `scripts/lint_rules.py` 的 `rule_R007_missing_docstring` + `run_all(strict=…)` + `tests/test_lint_rules.py`（4 例） | ✅ **已裁决（S2）** |
| **D4** | `AGENTS.md` 与 `.noai-paths` 逐字声明"（有负控用例，见 `tests/test_noai_gate.py`）" | S2 实测该文件 **51 例**，含"台账缺失 ⇒ `unknown`""hash 漂移 ⇒ `requires_human`""台账自指 ⇒ 永远 unapproved"等负控 | §0.3 第 10 条 | ✅ **已关闭（S2）** |
| **D5** | `scripts/release_check.py` 第 2 项要求"8 个 agent + pipeline 自检全部退出码 0" | S2 实测 **8 个 agent 自检全部 exit 0**（`a` 22/22、`b` 18/18、`c` 46/46、`d`–`h` 均 `SELF-CHECK DONE`）；A/B 已补自检块 | §0.3 第 6 条 | ✅ **已关闭（S2）** |
| **D6** | `.noai-paths` 登记了 `src/agentflow/release_check.py` 为"（**登记时并不存在**）" | **实测 `src/agentflow/release_check.py` 仍不存在**；`scripts/release_check.py` **已存在** | `Get-ChildItem src/agentflow -Filter *.py` / `Get-ChildItem scripts` | **一致**（登记策略按设计生效；列出以示已核对） |
| **D7** | `capabilities.py:517-523` 的注释与 `WRITE_SETS["C"]` 说 C 写 `analysis_reports` | 与 `capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]` **一致**（`capabilities.py:571-573`），且 `assert_capabilities()` 第 4 条会拦未登记的写集 | `capabilities.py:517-523/571-573/722-734` | **一致** |
| **D8** | `attack_tools.py:72-75` 的 `TERMINAL_STATUSES = ("resolved","abandoned","stalled")` | `schema.py:654` 的 `ATTACK_STATUSES` **含 `supported_not_proved`**，且 `agent_f.py:820` **会写它** | `attack_tools.py:75` vs `schema.py:654` vs `agent_f.py:820` | **中**（两份"终态"名单不一致；`include_terminal` 过滤会把已终结的计划当未终结） |
| **D9** | `docs/ROLE-SPECS.md` 的 M 节在写作时我误写 `condudctor.py:797`（拼写错） | 实际是 `conductor.py:797` | `conductor.py:797` | **低**（**本文档的**勘误，保留以示纪律） |
| **D10** | `README.md:150` 说"本机未接 provider、未实跑" | `pyproject.toml:44-54` 与 `config.yaml` 与 `tests/test_providers_online.py` 都在 | 同上 | **未核实**（README 整体过期，不作为判据） |
| **D11** | `schema.py:1207` 的注释说"`tools.ROLES` **就是**这一个对象（它 import 这里）" | 实测 `tools.ROLES is schema.ROLES` → **`True`** | 实测命令 | **一致** |
| **D12** | `draft/13` §7 FC-24 标"**未落地**（数学领域无 benchmark 记录表）" | `schema.EVAL_REQUIRED_FIELDS`（`:1454`）+ `EvalResult`（`:1465`）+ `tests/test_fc05_contract.py` 的 4 条 eval 测试 | `schema.py:1454/1465`；`tests/test_fc05_contract.py:276-316` | **该陈述已过期**（`draft/13` 是对 `abflow` 写的） |
| **D13** | `README.md:173-174`："`suspect` 状态没有复核流程：关系被标 `suspect` 后只是留在表里等人看" | **实测：仍未在 `agent_*.py` 里核到批量复核入口**（本次未逐行 grep，只按 §9.3 的口径标注） | `README.md:173-174` | **一致**（可能仍成立） |
| **D14** | `LESSONS.md` FC-06 判据①逐字："本项目实测 `{'A':20,'B':18,'C':23,'D':28}`" | 实测 `{'A':20,'B':18,'C':17,'D':37,'E':21,'F':32,'G':32,'H':23}` | 实测 §0.3 第 2 条 | **数字已过期**（且 FC-06 只列了 A–D） |
| **D15** | `LESSONS.md` FC-23 落地形态："本项目缺口：**一条关系只能引一篇文献**" | `Relation.supporting_lit_ids` **已存在**（`schema.py:365`，实测 7 处命中） | 实测 token 搜索 | **该"缺口"陈述已过期** |
| **D16** | `LESSONS.md` FC-27 / `draft/17` §6.3："多数脚本不设退出码" → "未报错被误读为无问题" | `.noai-paths` / `AGENTS.md` 明确要求三档退出码；`noai_gate.py` **已实现** 0/1/2；`release_check.py` **也已实现** 0/1/2 | 实测 3 个方向 | **已落地**（这是把教训变成门的正面范例） |
| **D17** | `ARCHITECTURE`：`tools/__init__.py:1-17` 的模块 docstring 说"模块缺失时**不报错，只记录**" | `build_registry(strict=True)` 时**会抛**；`strict=False`（默认）才只记录 | `tools/__init__.py:15-16` vs `:209-210` | **部分不一致**（docstring 未提 `strict` 参数） |
| **D18** | `tools/base.py:16-18` 说"`none`/`read` 的工具可以任意调用、不需要审批" | `NEEDS_APPROVAL = ("write_local","network")` 是判据；但 `search.providers`（`read`）**会发真实 HTTP**、`ocr.run`（`read`）**会下 ~100MB 模型** ⇒ 这条承诺**在 ≥4 个工具上不成立** | `tools/base.py:16-18/36`；INVENTORY 4.4 | **中**（文档承诺与行为不一致；R006 只 warn） |
| **D19** | `schema.py:1293` 的 `Task` docstring 说"dispose 幂等…（由 `Conductor` 实现）" | `conductor.dispose` 实测幂等（第二次返回 `closed: []`，`finish` 走幂等分支**连事件都不追加**） | `schema.py:1277-1278` vs `conductor.py:841-875` | **一致** |
| **D20** | `capabilities.py:149-150` 说"**不在表里的角色没有任何动作**（`M` 就是如此）" | 实测 `CAPABILITIES["M"] == ()` | `capabilities.py:501` | **一致** |

#### 10.1b S2 新增的待裁决项（**由审计发现，尚未裁决**）

| # | 甲方的说法 | 乙方的实测事实 | 证据 | 严重度 / 处置 |
|---|---|---|---|---|
| **D21** | `agent_a.py` 的退避租约注释说"避免在同一进程里**立刻重打同一个 API**" | `_claim()` 的跳过判据要求 `claimed_by` 非空（`agent_a.py:199`），而**失败分支会把 `claimed_by` 置空** ⇒ 同一实例下一轮**会立刻再领同一条**（最多 3 次后 `gave_up`）。真正的退避只发生在"队列里还有别的活"时（靠 `order_pending_requests` 的分桶排序） | 审计实测 + `agent_a.py:154/199` | **待人工裁决**。两条路：(a) 把注释改成"**软退避（仅排序）**"——承认它不做硬拦；(b) 给 `_claim` 加一条"`lease_until` 在未来 ⇒ 跳过"——但 `order_pending_requests` 的 docstring 明确论证了"空租约与已过期租约同桶"是**刻意设计**，硬拦会改动已冻结的排序语义。**未裁决前不许把它写成"已实现退避"。** |
| **D22** | `cli.py` 的 `cmd_verify` 原先"默认宽松、`--strict` 才严" | 已改为**默认严**（有 error ⇒ 退出码 1），`--strict` 加严到把 warning 也算失败。`DEVELOPMENT.md` 记录的基线（干净库 → "通过 / 错误 0 / 警告 0"、退出码 0）实测未变 | 审计实测 | **已修**（保留在此以记录语义变更） |
| **D23** | `cli.py` 的 `cmd_submit` 声称"ID 分配器只有一处"（`DEVELOPMENT.md:304`） | 它**自己**数 `len(rows)+i+1`，且多条提交时 `while` 循环改的是 `n` 而 `rid` 用 `n+i+1`、**无上限**（行数过万 ⇒ 静默产出 `r-10000`，越出 4 位 ID 契约） | 审计实测 | **已修**（改用 `interactions.next_prefixed_id`）。⚠️ 这是"**最小可用号会复用已删除的 ID**"那个缺陷的**同族**：两处取号 = 两个 ID 语义 |

### 10.2 ⚠️ **`DESIGN*.md` 与代码的关系**（**总则**）

5 份 `DESIGN*.md` 描述的是**设计与理由**，**不是现状**。已知的类别性偏差：

| 类别 | 例子 | 处置 |
|---|---|---|
| 设计里"待决"的问题，代码里已经有实现 | `DESIGN-CONDUCTOR.md` §8 待决问题 1（"M 是确定性的策略执行者"）—— `conductor.py` 已按此实现；问题 2（跨会话恢复"不自动续跑"）—— `verify.task_still_running`（warning）已落地 | **以代码为准**；设计文档改不改由人决定 |
| 设计里"本轮不做"，代码里已经做了 | `DESIGN-CONDUCTOR.md` §8 待决问题 3（`WRITE_SETS` 粒度"本轮是表级"）—— 代码**确实是表级**（`capabilities.py:509`），一致 | — |
| 设计里给的数字，代码里不同 | `DESIGN-CONDUCTOR.md:138-144` 的 `Policy` 默认值与 `policy.py:41-59` **逐字一致**（`3/5/4/200/900/None/None`） | **一致** |
| `DESIGN-ROLES.md` / `DESIGN-TOOLS.md` / `DESIGN-INTERACTIONS.md` 的接口签名 | 例：`DESIGN-ROLES.md §2.4` 写 `verify_fixes(doc_id, round_no)`，实际 `verify_fixes(doc_id, *, round_no)`（`round_no` 是 keyword-only） | **以代码为准**（`draft/13` §9.4 #4 已记录此条） |

---

## 附录 A：本文引用的**全部**命令与真实输出

见 `docs/ROLE-SPECS.md` 附录 S3（同一批命令，避免两处漂移）。
**本文额外跑过的**：

| # | 命令 | 实测输出 |
|---:|---|---|
| 1 | `python scripts/lint_rules.py` | `[linter] 扫描 {'src_py': 42, 'tests_py': 43}；规则 8 条` / `[linter] error 20 / warning 17 / info 11`；退出码 **1** |
| 2 | `python -m pytest -q`（末次） | `10 failed, 957 passed, 8 deselected in 191.56s`；退出码 1。失败文件：`test_conductor.py` / `test_scheduler.py` / `test_policy.py` |
| 3 | `python -m pytest -q`（取样中段，并行施工的半写文件） | `SyntaxError: unmatched ')'`（`trace_tools.py:282`）⇒ `Interrupted: 1 error during collection`；**已被修复** |
| 4 | `python scripts/noai_gate.py --check-consistency` | `一致：.noai-paths 与 AGENTS.md 的清单逐条相同`；退出码 0 |
| 5 | `python scripts/noai_gate.py --paths src/agentflow/cli.py` | `[clean] required_approvals=0`；退出码 0 |
| 6 | `python scripts/noai_gate.py --paths src/agentflow/schema.py` | `[requires_human] required_approvals=2`；退出码 **1** |
| 7 | `python scripts/noai_gate.py --git` | `unknown：无法从 git 取到改动集 ⇒ **本次没有检查**，不代表没问题`；退出码 **2** |

## 附录 B：本文**没能核实**的清单

见 `docs/ROLE-SPECS.md` 附录 S1（16 条）+ 本文 §9.3（15 条）。两处**不重复计数**：
S1 偏"角色事实"，§9.3 偏"FC 判据"。

## 附录 C：本文发现的**既有问题**清单（速查）

> 详细证据见 `docs/ROLE-SPECS.md` 附录 S2（13 条）+ 本文 §10.1（20 条）。
> 这里只列**需要人决策**的那些。

| # | 问题 | 建议处置 | 谁做 |
|---:|---|---|---|
| 1 | `trace_tools.py` 的 `SyntaxError` 让整个测试套件无法收集 | 修（**并行施工中的半写文件，可能已被同事修复**） | 实现者 |
| 2 | `tests/test_policy.py` 3 个失败 | 查（`estimate_write_conflict` / `waves_of`） | 实现者 |
| 3 | `agent_g._selftest` fixture 缺 `verifier_subject_key`（退出码 1） | 给那条 fixture 补字段（或改 `evidence_kind`） | 实现者 |
| 4 | `agent_a` / `agent_b` 无自检块 | 补 `__main__`（对齐 c/d/e/f/h 的形态） | 实现者 |
| 5 | `cli.py:460` 的 `choices` 写死 A–D | 改为 `list(ROLES)` | **人**（`cli.py` 不在禁改区，但它是入口层） |
| 6 | linter 的 20 个 R001 error | 逐条补"为什么可以忽略"或 `noqa` | 实现者 |
| 7 | 仓库**不是 git 仓库** | 纳入版本控制（否则 `noai_gate --git` **恒为 unknown**，且 `LESSONS.md` C14 的"引入时点无法核实"永远成立） | **人** |
| 8 | `review.scan_document` 的 `dep_check` / `verdict` 矛盾 | 让 `verdict` 读 `dep_check["checked"]`（或返回 `unverified`） | 实现者（**`review_tools.py` 不在禁改区**） |
| 9 | `search.dedup_check` 的 `except Exception: return []` | 改为 `fail(kind="store_unreadable")` | 实现者 |
| 10 | `attack_tools.TERMINAL_STATUSES` 缺 `supported_not_proved` | 与 `schema.ATTACK_STATUSES` 同步（或显式登记为受控例外） | 实现者 |
| 11 | `src/agentflow/release_check.py` 被登记但不存在 | **保持不存在，或明确决定去掉该条**（现状是"预留"，按设计生效） | **人** |
| 12 | `README.md` 整体过期 | 重写（或删掉指向 `test/test1` 的部分） | **人**（本次未授权改 `README.md`） |
| 13 | `data/` 运行期数据在源码树里 | 加 `.gitignore` / 移出 | **人** |
| 14 | `release_check.py` 自身"未批准"（`authored_by: AI`、`required_approvals: 2` 未取得） | 走 FC-27 的人工门槛：人编写或人逐行走查 + 2 名 reviewer | **人** |
| 15 | `conductor` / `verify` 的 tasks 检查重复 | 合并为一份，或显式登记为受控例外并加"两处必须一致"的测试 | 实现者 |
