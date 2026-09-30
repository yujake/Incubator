# 35 · 框架现状：正式版 `agentflow` 的分层结构（逐项带工作区相对路径）

> **本文的定位**：把"现在的系统长什么样"讲清楚，**每一条都标出对应的程序/脚本路径**，
> 以便任何人（人或 AI）拿着本文逐条去盘上核对。它不提出新要求、不改变任何判据 ——
> 判据在 `agentflow/DEVELOPMENT.md` §6 与各门的实现里，本文只是**索引与描述**。
>
> **路径约定**：本文所有路径**相对工作区根**（本机 `D:\Incubator`）。
> 因此 `agentflow/` 内部的文档（`agentflow/README.md`、`agentflow/DEVELOPMENT.md`、
> `agentflow/docs/*.md`）写的是同一个文件少一层前缀的形式（`src/agentflow/agent_loop.py`）。
> 目录名一律带尾斜杠，文件名一律带扩展名。
>
> **数字口径**：凡是会漂的数（工具条数、模块数、规则条数、门数），本文都写**复跑命令**，
> 不写"永远正确"的定值；引用的数都注明是**哪一次实测**。

---

## 1. 一句话定位与目录地图

**这是个什么系统**：面向数学研究的**多智能体协同框架**，一个主控（M）+ 八个角色（A–H），
角色之间只能按一张**显式的召唤边表**互相唤起，所有产出落在一张**可重建的台账**上，
所有"通过了"的结论都要有一份**可复跑的读数**支撑。
包入口：`agentflow/src/agentflow/__init__.py`（包 docstring 第一句即此定位）；
命令行入口：`agentflow/src/agentflow/cli.py` + `agentflow/src/agentflow/__main__.py`。

**顶层目录各自是什么**（工作区根下）：

| 路径 | 是什么 | 复跑/入口 |
|---|---|---|
| `agentflow/` | **正式版代码与文档**（包名 `agentflow`） | `cd agentflow && python -m pytest -q -p no:cacheprovider` |
| `agentflow/src/agentflow/` | 包本体（62 个顶层 `*.py`） | `python -c "import agentflow"`（`PYTHONPATH=agentflow/src`） |
| `agentflow/src/agentflow/tools/` | 工具层（13 个 `*_tools.py` + `base.py` + `__init__.py`） | `python -m agentflow.cli tools` |
| `agentflow/tests/` | pytest（162 个 `test_*.py`） | `python -m pytest -q -p no:cacheprovider` |
| `agentflow/scripts/` | 发布与门禁脚本（5 个 `*.py`） | `python scripts/lint_rules.py`、`python scripts/noai_gate.py --git --since <ref>` |
| `agentflow/tools/` | 开发期工具与探针（14 个 `*.py`） | `python tools/release_all.py`、`python tools/coverage_zero_test.py --level 2` |
| `agentflow/docs/` | 判据性文档（14 个 `*.md`，含 `ROLE-SPECS.md`） | `python tools/verify_role_specs.py` |
| `agentflow/data/` | 运行时数据（16 张表的快照 JSON + 事件日志） | `python -m agentflow.cli status` |
| `agentflow/library/` | 本地书架（下载/灌入的原文与抽取产物） | `python -m agentflow.cli project ...`（见 §9.6） |
| `agentflow/demo/` | 离线演示素材 | `python -m agentflow.cli demo` |
| `agentflow/temp/` | 开发期临时产物（**不构成交付**） | — |
| `draft/` | 交付报告正文（本文件所在目录，38 个 `*.md`，其中 **35 份编号报告**） | `draft/README.md` 是索引 |
| `test/test1/`、`test/test2/` | 原型与独立复现规格 + 验收程序（正式版之外） | `python test/test2/run_acceptance.py` |
| `projects/` | **项目工作区**：一个项目一个文件夹（正式版的运行现场） | `python -m agentflow.cli project ...` |

---

## 2. 分层：七层，每层只有一份判据

系统的形状可以概括成"**声明在上、实现在下、判据各一份**"。下面每一层给路径 + 关键符号。

| 层 | 目录/文件（相对工作区根） | 这一层唯一的职责 |
|---|---|---|
| ① 数据面 | `agentflow/src/agentflow/schema.py`、`store.py`、`canonical.py` | 表结构、行级校验、事务与 ID 分配 |
| ② 声明面 | `agentflow/src/agentflow/capabilities.py`、`interactions.py`、`policy.py` | 谁能召唤谁、跨角色契约、四类上限 |
| ③ 工具面 | `agentflow/src/agentflow/tools/` | 角色拿到手的原子动作（含权限面过滤） |
| ④ 角色面 | `agentflow/src/agentflow/agent_a.py` … `agent_h.py`、`conductor.py` | 每个角色的职责/状态机/产出 |
| ⑤ 循环面 | `agentflow/src/agentflow/agent_loop.py`、`agent_prompts.py`、`llmseam.py`、`judge.py`、`judges.py` | 模型驱动的决策循环与提示词装配 |
| ⑥ 接线面 | `agentflow/src/agentflow/host.py`、`cli.py`、`projects.py` | 把角色/工具/主控接到一起，并给出命令行入口 |
| ⑦ 质量面 | `agentflow/scripts/`、`agentflow/tools/`、`agentflow/src/agentflow/gates.py`、`verify.py`、`deliver.py` | 门、审计、发布检查 |

**为什么"判据各一份"**：见 `agentflow/DEVELOPMENT.md` §3（六条硬纪律）。
机械体现是 lint 规则 `R003`（重复公开定义）与 `agentflow/src/agentflow/canonical.py`
（规范 JSON 字节串的唯一实现，稿件内容哈希与回执哈希共用）。

---

## 3. 数据面

### 3.1 表结构：`agentflow/src/agentflow/schema.py`

- `SCHEMA_VERSION = 1`；`TABLES` 共 **16** 张（实测 2026-09-30）：

  | 组 | 表 |
  |---|---|
  | 文献与知识 | `literature`、`concepts`、`relations` |
  | 检索与重抽 | `search_requests`、`reprocess_requests` |
  | 研究 | `research_questions`、`conjectures`、`experiments`、`attack_plans` |
  | 成稿 | `documents`、`dependencies`、`review_findings` |
  | 运行记录 | `tasks`、`usage_ledger`、`eval_results`、`analysis_reports` |

- 每张表一个 dataclass（`SearchRequest` / `Literature` / … / `EvalResult`），
  行级校验集中在 `validate_table` / `row_from_dict` / `empty_table`。
- **ID 口径**在同一文件里定义：`is_valid_id` / `require_id`（4 位十进制）、
  `is_valid_process_id` / `require_process_id`（`r-` / `p-` / `t-` 前缀）、
  `assert_id_space_contract`、`assert_process_id_contract`。
- **三态词表**也在这里（"没查"与"查过没问题"分得开）：
  `usage_scope_production`、`scopes_without_producer`、`array_kinds`、`check_array_invariants`。

复跑：`python -c "import sys;sys.path.insert(0,'agentflow/src');import agentflow.schema as s;print(s.SCHEMA_VERSION, len(s.TABLES))"`

### 3.2 存储：`agentflow/src/agentflow/store.py`

- 一个工作区一个 `Store`：`Store(root)`，`init()` / `tx(...)` / `rows(...)` / `alloc_id(...)` / `rebuild(...)`。
- **加锁顺序是常量**：`LOCK_ORDER`（17 项，最后一项 `counters`）—— 跨进程 `filelock`，
  顺序错就是死锁；`lease_expired` / `make_lease` 管租约。
- **唯一事实源是事件日志**：`<工作区根>/data/events.jsonl`（追加式），快照 JSON 可由 `rebuild` 重建；
  `MAX_ID` 与 `IdExhausted` 管 ID 空间耗尽这一档。
- 原子写、替换重试（`_REPLACE_ATTEMPTS` / `_REPLACE_BACKOFF_S`）都在这里。

复跑：`python -m agentflow.cli rebuild --help`、`python -m agentflow.cli status`

### 3.3 与之配套的四个"非表"落点

| 路径（相对工作区根） | 是什么 | 实现 |
|---|---|---|
| `<工作区根>/DOC-SIGNATURES.jsonl` | 稿件签名台账（append-only + 链式哈希；证据快照在 `<工作区根>/doc-signatures/`） | `agentflow/src/agentflow/signatures.py`（`ledger_path` / `append_signature` / `verify_signature` / `chain_problems`） |
| `<工作区根>/ARTIFACTS.jsonl` | 产物归属登记（谁在哪个路径产出了什么 + sha256 + 退出码） | `agentflow/src/agentflow/artifacts.py`（`record` / `verify_entries` / `summarize`） |
| `<工作区根>/sessions/<会话号>.jsonl` | 会话记录（一次终态一条叙事行） | `agentflow/src/agentflow/sessions.py`（`append` / `read_session`） |
| `<工作区根>/.fulltext/`（内容寻址） | 抽取正文只存一份，产物里只留引用 | `agentflow/src/agentflow/fulltextstore.py`（`store_dir_for` / `put` / `load` / `verify_ref`） |
| `<工作区根>/notes/<角色>.md`、`<工作区根>/runs/*.json` | 角色笔记与子循环的长产出落盘 | `agentflow/src/agentflow/agent_loop.py`（`note_path` / `write_note` / `RUNS_DIR_NAME`） |

---

## 4. 声明面

### 4.1 能力表与召唤边：`agentflow/src/agentflow/capabilities.py`

**这张表是"谁能做什么"的权威定义**（`interactions.py` 的 docstring 自己承认"矩阵真身在这里"）。

- `ALLOWED_EDGES`：**26** 条召唤边（实测 2026-09-30），逐角色：

  | 谁 | 能召唤 |
  |---|---|
  | A | B |
  | B | C |
  | C | （无） |
  | D | A、B、C、E、F |
  | E | B、D |
  | F | A、B、C、D、E |
  | G | D、E、F |
  | H | G |
  | M | A、B、C、D、E、F、G、H |

- `CAPABILITIES`：**50** 个动作（实测 2026-09-30），逐角色条数：
  A 2、B 6、C 9、D 14、E 5、F 4、G 6、H 4、**M 0**。
- `NON_SUMMONABLE = {'M'}`：主控不可被召唤（它只在顶层发起）。
- `WRITE_SETS` / `SIDE_EFFECTS` / `EFFECT` / `EXTERNAL`：写集与副作用轴。
- **导入期自检**（`assert_capabilities`）：参数覆盖 144/144 个 property、50 个动作、
  两层参数类型对账 73 对（读到 62 个工具的 schema）—— 这行字在**导入 `agentflow.capabilities`
  时**打印（角色与工具的装配必经此处），它是"声明与实现没分家"的现场读数。

复跑：`python -c "import sys;sys.path.insert(0,'agentflow/src');from agentflow import capabilities as C;print(sum(len(v) for v in C.ALLOWED_EDGES.values()), sum(len(v) for v in C.CAPABILITIES.values()))"`

### 4.2 跨角色冻结契约：`agentflow/src/agentflow/interactions.py`

- `CONTRACT_VERSION = 1`；契约编号 I1–I7 写在模块 docstring 里。
- **两条铁律**：全部函数**不接收 `Store`/`Tx`**（`assert_store_free` 在导入期自检签名）、
  且是**纯函数**（不读时间、不读随机数、不改入参）。
- 主要契约：`check_conflict`（I6 写入期闸门，B 在事务内调）、
  `adjudicate_contradiction`（矛盾闭环收敛点）、
  `admit_search_request`（I7 配额）、`admit_reprocess_request`（I4 配额）、
  `priority_rank` / `order_pending_requests`（I7 取任务顺序）、
  `structural_duplicate_pairs`（I5 候选）、`find_equivalent_question`、`next_prefixed_id`。

### 4.3 策略与四类上限：`agentflow/src/agentflow/policy.py`

`Policy` / `Decision` / `Refusal`；入口 `check_action` / `check_edge` / `check`，
写集冲突估计 `estimate_write_conflict`，波次划分 `waves_of`，
预算态 `budget_state`，完整性自检 `assert_policy_complete`。

---

## 5. 工具面

### 5.1 装配点：`agentflow/src/agentflow/tools/__init__.py`

- `build_registry(...)`（关键字参数：`store` / `workspace_root` / `graph` / `roles` /
  `name` / `strict` / `context_budget` / `config` / `conductor` / `role_registry`）
  返回 `RegistryBuild`（含 `.registry` / `.loaded` / `.skipped`）。
- 权限面的单一来源在同文件：`ROLES`、`READ_ONLY_ROLES = {'C','H'}`、
  `SIDE_EFFECTS_WRITE = {'write_local'}`。
- `build_for_role(role, ...)` 给"只要一个角色的面"的调用方。

### 5.2 基座：`agentflow/src/agentflow/tools/base.py`

`ToolSpec` / `ToolResult` / `ToolRegistry` / `ToolError` / `ParamError`；
装饰器 `tool(...)`（声明 `side_effect` / `roles` / `returns` / `tags`）；
参数校验 `validate_params`；参数缝 `check_param_seams` / `param_seam_reason`；
只读角色越权的**调用期**判据 `_role_surface` + 逐条登记的 `READONLY_CALL_EXCEPTIONS`。

### 5.3 十二个工具模块与 73 个工具（实测 2026-09-30）

复跑命令：`python -m agentflow.cli tools`（输出即下表来源）。

| 模块（相对工作区根） | 工具前缀 | 条数 | 主要给谁 |
|---|---|---|---|
| `agentflow/src/agentflow/tools/table_tools.py` | `table.*` | 8 | A–H 共用数据面 |
| `agentflow/src/agentflow/tools/fs_tools.py` | `fs.*` | 7 | 有工作区的角色（沙箱在工作区内） |
| `agentflow/src/agentflow/tools/search_tools.py` | `search.*` | 8 | A（`search.local`/`search.shelf` 另给 C、H） |
| `agentflow/src/agentflow/tools/ocr_tools.py` | `ocr.*` | 3 | B |
| `agentflow/src/agentflow/tools/graph_tools.py` | `graph.*` | 4 | C、D |
| `agentflow/src/agentflow/tools/trace_tools.py` | `trace.*` | 4 | C、D |
| `agentflow/src/agentflow/tools/research_tools.py` | `research.*` | 5 | D（`list_gaps` / `submit_gap` / `write_note` / `poll_waiting` / `set_status`） |
| `agentflow/src/agentflow/tools/verify_tools.py` | `verify.*` | 6 | E（F、G 借读） |
| `agentflow/src/agentflow/tools/attack_tools.py` | `attack.*` | 6 | F（D、G、H 借读） |
| `agentflow/src/agentflow/tools/doc_tools.py` | `doc.*` | 10 | G（H 借 `doc.paper_state` 等只读项） |
| `agentflow/src/agentflow/tools/review_tools.py` | `review.*` | 2 | H（D、F、G 借读） |
| `agentflow/src/agentflow/tools/conductor_tools.py` | `conductor.*` | 10 | M（含 `conductor.summon_many` = 批量并发派活，见 §8.4） |
| `agentflow/src/agentflow/tools/conjecture_tools.py` | `conjecture.register_conjecture` | 1 | 猜想台账产出面（**不在** `build_registry` 里，由 `agentflow/src/agentflow/agent_d.py::install_d_tools` 另行挂） |

按前缀合计（实测 2026-09-30）：table 8 + fs 7 + search 8 + ocr 3 + graph 4 + trace 4 +
research 5 + verify 6 + attack 6 + doc 10 + review 2 + conductor 10 = **73**；
另加 `conjecture.register_conjecture` 这一条装配在 D 的安装函数里。
（另外两个口径：`build_registry(store=None, workspace_root='.')` ⇒ 68；
`build_registry()` ⇒ 61 —— 缺 store / 缺工作区根时有些模块根本不装配。）

**逐角色工具条数**（同一条命令的另一半输出；`agentflow/tools/verify_role_specs.py` 会拿它
与 `agentflow/docs/ROLE-SPECS.md` 对账）：

```text
A 23 / B 18 / C 19 / D 37 / E 21 / F 32 / G 37 / H 25 / M 10    工具总数 73（已装模块 12）
只读角色写工具泄漏：{'C': [], 'H': []}（空 = 正常）
```

### 5.4 工具面里三条刻意的设计

1. **只读角色拿不到写工具**（结构过滤，不是提醒）：`agentflow/src/agentflow/tools/base.py::_role_surface`。
2. **写工具只对非只读角色可见**：`agentflow/src/agentflow/tools/fs_tools.py::_effective_roles`。
3. **声明与实现不许分家**：每个工具的 `returns=` 键表由
   `agentflow/tests/test_tools_returns_declaration.py` 机械核对；
   参数缝由 `agentflow/scripts/lint_rules.py` 的 `R010` 逐工具核对。

---

## 6. 角色面

### 6.1 八个角色 + 一个主控

| 角色 | 实现（相对工作区根） | 一句话职责（取自模块 docstring） | 主要产出表 |
|---|---|---|---|
| A | `agentflow/src/agentflow/agent_a.py` | 文献搜索 | `literature`、`search_requests` |
| B | `agentflow/src/agentflow/agent_b.py` | 文献整理 | `literature`、`reprocess_requests` |
| C | `agentflow/src/agentflow/agent_c.py` | 关系分析（程序做分析，LLM 只做排序与措辞） | `relations`、`analysis_reports` |
| D | `agentflow/src/agentflow/agent_d.py` | 研究循环 | `research_questions`、`conjectures` |
| E | `agentflow/src/agentflow/agent_e.py` | 数值实验与形式化验证 | `experiments` |
| F | `agentflow/src/agentflow/agent_f.py` | 多轮难题攻坚 | `attack_plans` |
| G | `agentflow/src/agentflow/agent_g.py` | 论文撰写 | `documents`、`dependencies` |
| H | `agentflow/src/agentflow/agent_h.py` | 审校（只读） | `review_findings` |
| M | `agentflow/src/agentflow/conductor.py` | 主控编队：召唤可审计、可拒绝、可取消、可重建 | `tasks` |

每个角色模块都能单独自检：`python -m agentflow.agent_a`（…`agent_h`）。
主控的召唤实现是 `Conductor` + `LocalBackend` / `SubagentBackend`
（`agentflow/src/agentflow/conductor.py`），"没接线"是一等状态（`NotWiredError`）。

### 6.2 角色规格文档：`agentflow/docs/ROLE-SPECS.md`

- 9 个角色节（A–H + M）× 每节 8 个必备子节（实际 10 个子节）。
- **有一道结构门**：`agentflow/tools/verify_role_specs.py`（退出码 0/1/2），
  它同时核对"每节的工具条数"与现场装配是否一致。实测 2026-09-30：
  `9 个角色节各自 8 个必备子节齐全；逐角色工具条数与现场装配一致`。

### 6.3 H 的门引擎：`agentflow/src/agentflow/gates.py`

15 道有名字、可单独查询的门（`GATES`；`run_gate` / `run_all_gates` / `gate_report` /
`render_review_report`）。逐门名与轴：

| 门 | 名 | 轴 |
|---|---|---|
| G1 | 自含性门 | 工程 |
| G2 | 引用解析门 | 证据 |
| G3 | 交叉引用门 | 体例 |
| G4 | 账本对账门 | 体例 |
| G5 | 禁词/手糊门 | 体例 |
| G6 | 虚证门 | 证据 |
| G7 | 台账完整门 | 证据 |
| G8 | 可复跑门 | 证据 |
| G9 | 计数一致门 | 体例 |
| G10 | 审校格式门 | 体例 |
| G11 | 版本冻结门 | 工程 |
| G12 | 反方门 | 数学 |
| G13 | 空结论自证门 | 体例 |
| G14 | 降级合规门 | 数学 |
| G15 | 自己的错入册 | 工程 |

`GateResult` 是四态（`pass` / `fail` / `unknown` / `not_applicable`），
且 `__post_init__` **结构强制"零发现必须自证"**（G13 的机制面）。

### 6.4 语义判据：`agentflow/src/agentflow/judges.py` 与 `judge.py`

- `agentflow/src/agentflow/judge.py`：**模型判定的唯一缝协议** —— `judge_json` /
  `is_judge_problem` / `reason_of`，一套失败词表 + "没查成不等于没找到"。
- `agentflow/src/agentflow/judges.py`：判据注册表 `CRITERIA`（6 条），每条 = 官能 + 三态词表：

  | 判据 id | 官能 | 三态取值 |
  |---|---|---|
  | `overview.essence` | 高观点 | `structural` / `listing` / `unsupported` |
  | `innovation.conjecture_value` | 敢创新 | `substantive` / `trivial` / `unfalsifiable` |
  | `taste.journal_style` | 有品味 | `journal_ready` / `needs_work` / `not_a_draft` |
  | `brain.blocker_specificity` | 脑子 | `specific` / `vague` / `none` |
  | `reasoning.source_fidelity` | 能思辨 | `primary` / `secondary` / `authority_only` |
  | `claims.conclusion_strength` | 能思辨 | `within_evidence` / `overclaimed` / `unjudgeable` |

- 每个判据必须配负控（`registry_problems` 机械核对）；
  `semantic_judge_for(seam)` 把 `claims.conclusion_strength` 适配成
  `agentflow/src/agentflow/tools/review_tools.py::SemanticJudge` 要的形状
  （`within_evidence` ⇒ `consistent`，`overclaimed` ⇒ `stronger_than_evidence`，其余 ⇒ `unknown`）。

### 6.5 可机械判的那一半：`agentflow/src/agentflow/faculty_checks.py`

十项官能里"不需要模型"的部分（12 个函数）：`ids_in` / `unknown_ids` / `link_status` /
`overview_findings` / `conjecture_hygiene` / `style_findings` / `snapshot_counts` /
`progress_findings` / `claim_strength_findings` / `trace_findings` 等。

### 6.6 断言的唯一判据来源

| 文件（相对工作区根） | 管什么 |
|---|---|
| `agentflow/src/agentflow/claimanatomy.py` | `documents.claims` 每个元素的字段规格（`ClaimSpec`）、生命周期裁决（`lifecycle_verdict`）、`validate_claim` / `validate_document_claims`、`claim_content_hash` / `revision_hash` / `is_retracted` |
| `agentflow/src/agentflow/claims.py` | 把一段模型答复**切成可逐条回验的原子断言**（`split_claims` / `parse_claims` / `ledger_rows`） |

---

## 7. 循环面：模型怎么决策，框架怎么留痕

### 7.1 循环：`agentflow/src/agentflow/agent_loop.py`

- **六种形状**：`SHAPES = ('tool', 'summon', 'message', 'note', 'ask_user', 'final')`（2026-09-30 复核：**仍然是六种** —— 代唤走的是 `message` + 固定 subject，没有新造形状）；
  解析入口 `_shape_of`（`tool` 是**字符串**工具名 + `args`，其余为嵌套对象）。
- **输出契约写在每一轮提示词的最后**（`JSON_TAIL`，六个骨架逐行可解析；
  判据 `agentflow/tests/test_agent_loop.py::test_every_documented_shape_actually_parses`
  与 `test_the_step_prompt_restates_the_output_contract_last`）。
- **观测层**：`RESULT_CHARS = 3000`（单步结果给模型看的字符预算）、`ECHO_CHARS = 600`
  （回显模型自己那一步的上限）；`_clip_fields` **逐字段限长**、
  `_flatten_one_level` 把工具 `data` 摊平一层、`_continue_hint` 从 `meta` 生成**可执行的续读办法**、
  `_observe` 把三者拼成一段；`_for_record` 只管落档（`RECORD_CHARS = 2000`）。
- **长产出落盘**：`RUNS_DIR_NAME = "runs"` ⇒ `<工作区根>/runs/<角色>-<时间戳>-<序号>.json`。
- **记忆与留言**：`read_messages` / `send_message` / `mark_delivered` / `inbox_digest` /
  `write_note` / `note_path` / `notebook_digest`（笔记落 `<工作区根>/notes/<角色>.md`）。
- **驱动方式**：`run_role(...)`；`LlmBackend(inner, loops, session_root, seam_factory,
  max_steps, store, sid)` 把"某个（角色, 动作）走 LLM 循环"做成登记表 ——
  **哪些动作走模型是部署选择**（CLI 的 `--drive`），不是写死的。
  被驱动的那个 `(角色, 动作)` 走的是 `agent_loop.AgentLoop`：**它就是一个 subagent**
  （自己的工具面、自己的步数上限、自己的台账行、能再唤起别人）。
- **子循环知道自己在为谁干活**（2026-09-30 修）：`LlmBackend._running_row(role)` 从
  `tasks` 表读出那条 `running` 行，用它的 `called_by` / `depth` / `task_id` 填
  `agent_run_start`。此前读的是 `params["_summoned_by"]`（**全仓没有生产者**），
  于是每个被同伴唤起的角色都以为"是主控直接派的、深度 1"。

### 7.4 协同：够不到的人怎么找（`agent_loop.py`）

边表（`capabilities.ALLOWED_EDGES`）是**设计**：谁该找谁是有意规定的，不是遗漏。
但"派不动就什么都不做"不是设计，所以框架给每条越权拒绝配了一条**兜底路**：

| 机制 | 落在哪 | 说明 |
|---|---|---|
| 自动代唤申请 | `agent_loop.py::_do_summon` → `_request_relay` | 被拒的理由是 `forbidden_edge` / `depth_exceeded`，**或者** `invalid_params` 且目标不在自己的伙伴表里（那时参数根本无从写对）⇒ 自动给 M 发一条 `subject=请代唤` 的留言 + 落一条 `agent_summon_request` 事件；这一步仍如实报 `ok=False`（不许假装成功） |
| 提示词 | `agent_prompts.py::partners_lines` 与 `LOOP_PROTOCOL` | 每个可被召唤的角色都读到"需要的人不在名单里就发『请代唤』给 M，写清要谁/动作/参数/为什么" |
| 主控的义务 | `agent_prompts.py` 的 M 简报 policy | "收到 subject=请代唤 的留言**本轮内必须处理**：要么替它派，要么写明为什么没派" |
| 端到端判据 | `agentflow/tests/test_agent_loop.py::test_the_collaboration_chain_works_end_to_end` | H 够不到 A ⇒ 申请 ⇒ M 读到 ⇒ M 派 A；断言锚在**台账**（`role=A` 且 `called_by=M`，且发生在申请之后） |

### 7.5 并发：同一角色的多个实例（`policy.py` / `scheduler.py` / `conductor.py` / `host.py`）

用户要的形态是"一批文献分给 3 个 B 同时读"。这条路上原本有三道结构闸门，2026-09-30 打通：

| 闸门 | 原来 | 现在 |
|---|---|---|
| 分波判据按**角色级**写集 | 3 个 B 必然排 3 波（峰值真并发 1，"再多 B 也没用"） | `scheduler.TaskCall.instance` + `policy._same_role_other_instance`：**同角色、两边都显式给了不同实例标签** ⇒ 不算冲突；没给或标签相同 ⇒ 照旧串行（默认行为一字未变，负控在 `agentflow/tests/test_scheduler.py`） |
| 每角色只有一个对象 | `LocalBackend._instances` / `host._Builder._made` 键里只有角色 | 缓存键加一维 `instance`；`host` 的工厂契约 `fn(*, store=..., instance="")`，A/D/E/F 把实例写进 `actor`（`agent-E-7`），G/H 写进 config 的 `actor` |
| 没有批量入口 | `Conductor.run_plan` / `scheduler.run_waves`（分波 + 线程池 + `ConcurrencyProbe`）**生产路径零调用**；M 的工具只能一次派一个 | `agentflow/src/agentflow/tools/conductor_tools.py` 的 **`conductor.summon_many`**（M 专属）：一次派一批，返回里带 `waves` 与 `concurrent_peak` —— "到底并发了没有"看这两个数，不看墙钟 |

四条上限仍然管着这件事（`agentflow/src/agentflow/policy.py`）：
`max_depth=3` / `max_fanout=5` / `max_concurrency=4` / `max_tasks_per_run=200`。

### 7.2 提示词装配：`agentflow/src/agentflow/promptkit.py` + `agent_prompts.py`

- `promptkit.py`：`Section` / `Scope` / `Assembly` / `PromptRegistry`（有序段 + 变量 + 作用域遮蔽）。
- `agent_prompts.py`：`PROMPT_VERSION = "p17"`；`ROLE_BRIEFS` 9 份（A–H + M）；
  段顺序在 `SECTION_ORDERS`：`AGENT_IDENTITY`、`ROLE_BOUNDARY`、`ROLE_POLICY`、`STANCE`、
  `FACULTIES`、`PARTNERS`、`WORKSPACE_FACTS`、`AGENT_TOOLS_SDK`、`TOOL_GUIDANCE_BASE`、
  `EVIDENCE_CONTRACT`、`THREE_STATE`、`OUTPUT_CONTRACT`、`TASK_FRAME`、`DEPLOYMENT_SUFFIX`。
- **事实部分一律现算**（工具面、伙伴边、工作区事实），手写的只有判断与边界 ——
  因此"提示词里说的"与"运行时的事实"不会分家（`prompt_audit` 落审计）。

### 7.3 模型调用与记账

| 文件（相对工作区根） | 职责 | 关键符号 |
|---|---|---|
| `agentflow/src/agentflow/modelgw.py` | provider 无关的模型网关；**全仓唯一读 API key 的地方** | `ModelSpec` / `ModelReply` / `ModelGateway` / `spec_from_env` / `urllib_transport` |
| `agentflow/src/agentflow/llmseam.py` | 统一的模型缝：一次调用 = 一条审计记录 | `LlmSeam` / `SeamCall` / `SeamSpend` |
| `agentflow/src/agentflow/modelclient.py` | 把网关适配成抽取层要的 `.complete(prompt) -> str` | `ModelClient` / `client_from_env` |
| `agentflow/src/agentflow/modelcost.py` | 花销入账适配器（reply → `usage_ledger` 一笔） | `Price` / `charge_reply` / `settle_key` / `price_from_env` |
| `agentflow/src/agentflow/tokenmeter.py` | token/花销预算，**重试也计入** | `TokenMeter` / `Charge` / `MeterReading` / `row_with_idem_key` |
| `agentflow/src/agentflow/contextbudget.py` | 压缩 / 剪枝 / spill 三件套 | `ContextBudget` / `prune` / `compact` / `prune_tool_result` |

---

## 8. 接线面：从命令行到一次真实运行

### 8.1 接线：`agentflow/src/agentflow/host.py`

| 函数 | 干什么 |
|---|---|
| `build_role_registry(store, *, llm=..., providers=..., extractor=..., config=..., workspace_root=...)` | 角色登记表 `role -> ("factory", fn)`；**没接线的角色不进表**（于是 `summon` 落 `refused/not_wired`，而不是拿空壳假装跑过） |
| `wiring_status(...)` | 逐角色接线态（同一份判定） |
| `wired_conductor(...)` | 建一个接了线的主控（复用 `agentflow/src/agentflow/tools/conductor_tools.py::conductor_for` 的按工作区缓存） |
| `wired_tool_registry(...)` | 组装接了线的工具层 |
| `wired_llm_conductor(..., loops=..., max_steps=..., semantic_review=...)` | 给主控接上"模型驱动的角色循环" |

实测（2026-09-30，未给 provider）：`{'A': 'no_provider', 'B': 'wired', 'C': 'wired', 'D': 'wired',
'E': 'wired', 'F': 'wired', 'G': 'wired', 'H': 'wired'}` —— A 需要检索 provider，缺了就如实报。

### 8.2 命令行：`agentflow/src/agentflow/cli.py`

21 个子命令（`python -m agentflow.cli --help`）：
`init`、`submit`、`run-a`、`run-b`、`status`、`verify`、`rebuild`、`repair`、`tools`、
`analyze`、`research`、`pipeline`、`demo`、`run`、`evidence`、`artifacts`、`project`、
`run-agent`、`gate`、`inbox`、`answer`。
其中 `run-agent` 是"一次真实的多智能体运行"的入口（`--role`、`--task`、`--drive`、
`--max-steps`、`--semantic-review` 等）。

### 8.3 编排与项目工作区

| 文件（相对工作区根） | 职责 |
|---|---|
| `agentflow/src/agentflow/projects.py` | 一个项目一个文件夹；冷/热启动按"文件夹在不在"判定（`create_project` / `resolve` / `classify` / `plan` / `run_project`） |
| `agentflow/src/agentflow/pipeline.py` | 把 A→B→C→D 串成可中断、可续跑、可审计的流水线（`run_pipeline`） |
| `agentflow/src/agentflow/runflow.py` | 端到端一条命令：一个主题 + 一个美元上限 ⇒ 一份可复核的完整运行记录（`run_topic` / `flow_main`） |
| `agentflow/src/agentflow/autonomy.py` | 自主轮次 + 周期汇报（`run_autonomous` / `save_checkpoint` / `task_fingerprint`） |
| `agentflow/src/agentflow/scheduler.py` | 按写集互斥分波并发（`run_waves` / `run_tasks` / `wave_summary`） |
| `agentflow/src/agentflow/cancellation.py` | 协作式取消（`CancelToken` / `current_token` / `raise_if_cancelled` / `run_cancellable`） |
| `agentflow/src/agentflow/demo.py` | 离线端到端演示（`build_fixtures` / `run_demo`，不访问网络） |
| `agentflow/src/agentflow/userio.py` | 用户频道：提问、等回答、"没答"这一档（`ask_user` / `answer_question` / `pending_questions`） |
| `agentflow/src/agentflow/console.py`、`tty.py` | 输出编码钉在 UTF-8；终端呈现原语（`pin_utf8` / `Style` / `panel` / `table`） |

---

## 9. 证据面与论文包面

### 9.1 证据链（A–D 的主线）

| 文件（相对工作区根） | 职责 | 关键符号 |
|---|---|---|
| `agentflow/src/agentflow/providers.py` | 检索 provider 层（OpenAlex / Crossref / DOAJ / EuropePMC / Fixture + 多路合并） | `SearchProvider`、`MultiProvider`、`build_providers`、`normalize_doi`、`dedup_key_of` |
| `agentflow/src/agentflow/fetch.py` | 下载层：流式、原子落盘、限速重试、镜像回退 | `HttpDownloader`、`Downloader`、`FetchResult`、`default_downloader` |
| `agentflow/src/agentflow/extract.py` | 文本抽取层 | `extract_text`、`DocumentText`、`page_count` |
| `agentflow/src/agentflow/tools/ocr_tools.py` | 扫描件 OCR（后端探测 / 文本层判断 / 按页 OCR） | `OcrBackend`、`EasyOcrBackend`、`PytesseractBackend` |
| `agentflow/src/agentflow/dedup.py` | 判重（文献 / 概念 / 关系） | `normalize_doi`、`literature_keys`、`title_key`、`decide_relation` |
| `agentflow/src/agentflow/quoteverify.py` | 引文逐字回验 | `check_quote`、`QuoteCheck` |
| `agentflow/src/agentflow/evidence.py` | 证据层：先检索、再逐字回验 | `retrieve`、`acquire_fulltext`、`verify_claims`、`materials_block` |
| `agentflow/src/agentflow/locallib.py` | 把一个本地目录的 PDF 灌进库（按内容 hash 幂等） | `ingest_directory`、`page_scores`、`search_fn_for_store` |

### 9.2 形式化：`agentflow/src/agentflow/formalgw.py`

Lean 4 后端：`detect_backend`、`check_toolchain`、`check_lean`、`evidence_of`、
`missing_imports_of`、`find_mathlib_root`。**"没查成"与"查了不成立"必须分开记**
（缺 Mathlib 落 `inconclusive`，不是 `fail`）。
包外依赖：本机 Lean 落在 `temp/lean470/lean-4.7.0-windows/bin`（部署选择）。

### 9.3 论文包：三层

| 层 | 文件（相对工作区根） | 职责 |
|---|---|---|
| 构建/编译/锚核对 | `agentflow/src/agentflow/paperbuild.py` | `resolve_script` / `run_script` / `render` / `compile_pdf` / `anchor_check`（进程内）/ `anchor_check_script`（起子进程）/ `build`（render → compile → anchor_check 三步）/ `state` |
| 锚与回执的本体 | `agentflow/src/agentflow/renderanchor.py` | `ANCHOR_NAME=RENDER-ANCHOR.json`、`RECEIPT_NAME=COMPILE-RECEIPT.json`、`HISTORY_NAME=BUILD-HISTORY.jsonl`；`build_anchor` / `build_receipt` / `append_history` / `history` / `check_package`；判定 `consistent` / `drifted` / `unknown` |
| 角色手里的动作 | `agentflow/src/agentflow/tools/doc_tools.py` | `doc.paper_render` / `doc.paper_compile` / `doc.paper_anchor` / `doc.paper_build`（exec，G）+ `doc.paper_state`（只读，G、H） |

**三维锚**的含义（`agentflow/src/agentflow/renderanchor.py::check_package`）：
源表（`rows_digest`）/ 渲染出的源文件（`package_files` + `file_digest`）/ 编译回执
（`tex_sha256` 与盘上 tex 是否一致）—— 第三维回答的是"这份 PDF 是不是从磁盘上这份 tex 编的"。

**项目侧的脚本**（论文包的实际生产者，相对工作区根）：
`projects/p2-review/code/make_paper.py`、`projects/p2-review/code/compile_paper.py`、
`projects/p2-review/code/p10_p11_meta.py`；
Lean 源：`projects/p2-review/code/lean/p2_L0_identity.lean`、`p2_rho_sum_zero.lean`、`p2_step_norm.lean`；
产物：`projects/p2-review/out/paper/`（`main.tex`、`main.pdf`、`ACCEPTANCE.md`、
`CLAIMS-LEDGER.md`、`tables/*.tex`、`RENDER-ANCHOR.json`、`COMPILE-RECEIPT.json`、`BUILD-HISTORY.jsonl`）。

### 9.4 交付闸门：`agentflow/src/agentflow/deliver.py`

`gate(name, artifact, *, session_root, seam=None, criteria=(), store=None, claimed_pairs=(),
context="", require_disclaimer=False, disclaimer="")` ⇒ `DeliveryGate`；
不通过时产出**可派回去的工作项**（`WorkItem` / `append_work_item` / `dispatch_work_items`）。

---

## 10. 质量面：门、审计与发布

### 10.1 全局不变量：`agentflow/src/agentflow/verify.py`

唯一入口 `verify_all(...)` ⇒ `VerifyReport`＋`Issue`。它是"审计的判据本身"，
所以它自己在禁 AI 区里（见 §11）。

### 10.2 机械规则：`agentflow/scripts/lint_rules.py`

`RULES` 共 **12** 条（`R004` / `R006` 已退休、编号保留）：

| 规则 | 查什么 |
|---|---|
| `R001_bare_except_pass` | 裸 `except: pass` |
| `R002_none_folds_to_empty` | "没查"被折叠成"空" |
| `R003_duplicate_public_defs` | 同一个公开名字两处定义 |
| `R004_registry_outside_tools`（已退休） | 判据移到注册期（`ToolRegistry.register*` 各核一次 `roles ⊆ schema.ROLES`） |
| `R005_hardcoded_role_list` | 硬编码角色表 |
| `R006_read_tool_touches_network`（已退休） | 判据移入 `R010` |
| `R007_missing_docstring` | 缺 docstring |
| `R008_scripts_without_exit_code` | 脚本没有退出码 |
| `R009_decoration_in_comments` | 注释/docstring 里的 Markdown 装饰与 emoji |
| `R010_external_axis_mismatch` | 逐工具核对 `external` 轴（含 `R010-a/b/c` 三档） |
| `R011_dead_vocab` | 受控词表里的死取值 |
| `R012_write_text_newline` | 写文本时的换行口径 |

复跑与当次读数（实测 2026-09-30）：
`python scripts/lint_rules.py` ⇒ `error 0 / warning 9 / info 47`；
`python scripts/lint_rules.py --strict` ⇒ `error 0 / warning 51 / info 46`。
这两个数由 `agentflow/DEVELOPMENT.md` §0.3 的 `LIVE-READINGS` 块与
`agentflow/tests/test_release_all.py` 对账。

### 10.3 覆盖门：`agentflow/tools/coverage_zero_test.py`

按 AST 把 `agentflow/src/agentflow/**` 的公开函数分成四档
（1 写路径 / 2 判据决策 / 3 只读读取 / 4 呈现格式），做传递闭包，算出"零直接测试"的函数。
发布门的口径是 `--level 2` ⇒ **等级 ≤ 2 的零测试函数必须为 0**。
实测 2026-09-30：公开函数 888 个、零直接测试 107 个，等级 1/2 各 0 个 ⇒ 退出码 0。

### 10.4 逐文件测试门：`agentflow/tools/run_each_test_file.py`

把"顺序依赖 / 跨文件状态泄漏"变成一条可判定的门：`discover` / `run_one` /
`classify_pytest_result`（`exit=5` 按汇总行拆成 `deselected` / `no_tests` / `all_skipped` / `all_xfail`）
+ `audit_exemptions`（允许整文件被跳过的豁免面，有上限）。

### 10.5 一键发布：`agentflow/tools/release_all.py`（6 步）

```text
release-check → acceptance → repro → role-specs → coverage → per-file
```

- `release-check` 调 `agentflow/scripts/release_check.py`（八项：test-suite / selftests /
  tool-census / verify / linter / noai / contract / imports）。
- `acceptance` / `repro` 调的是仓库根的 `test/test2/run_acceptance.py` 与
  `test/test2/repro/run_all.py`（正式版之外的独立复现资产）。
- 每步三态汇总（`verdict_from_subitems` / `overall`）；跳过的步骤记 `unknown` 还是 `pass`
  由这一步自己的取舍决定 —— 那一条取舍就是"门能不能被 `--skip` 绕过"。

### 10.6 ROLE-SPECS 结构门：`agentflow/tools/verify_role_specs.py`

核对 `agentflow/docs/ROLE-SPECS.md` 的 9 个角色节 × 8 个必备子节，
并逐角色比对工具条数与现场装配（§6.2）。

### 10.7 词表普查：`agentflow/tools/vocab_census.py`

`R011`（死取值）的**判据本体**：扫出全部词表定义点与产出点，
`RESERVED_VALUES` 是"已登记为预留"的唯一落点。

### 10.8 FC-27 禁 AI 区门：`agentflow/scripts/noai_gate.py`

- 清单在两处**逐条一致**：`agentflow/.noai-paths` 与 `agentflow/AGENTS.md` 的
  `NOAI-MANIFEST` 区块（27 条 glob / 24 条唯一路径 / 7 类；实测 2026-09-27 15:02）。
- 退出码三态：`0=clean` / `1=requires_human` / `2=unknown`；
  命中要求 `REQUIRED_APPROVALS_ON_HIT = 2` 名 reviewer。
- **批准台账**：`agentflow/.noai-approvals.json`（人签；台账不能批准自己）；
  人工复核登记表：`agentflow/NOAI-REVIEW-REGISTER.md`。
- 用法：`python scripts/noai_gate.py --git --since <ref>`（不给基线判 `unknown`，不是 `clean`）。

---

## 11. 一次真实运行的完整时序（每一跳都带路径）

以"给一个任务、只发一次"的运行为例（`--role M --task ... --drive ...`）：

1. **入口**：`python -m agentflow.cli run-agent` ⇒ `agentflow/src/agentflow/cli.py::cmd_run_agent`。
2. **装配**：`agentflow/src/agentflow/host.py::wired_tool_registry` /
   `wired_llm_conductor` ⇒ 角色登记表 + 主控 + 工具层
   （装配点在 `agentflow/src/agentflow/tools/__init__.py::build_registry`）。
3. **提示词**：`agentflow/src/agentflow/agent_prompts.py::system_prompt`（段顺序见 §7.2），
   审计读数落 `prompt_audit`。
4. **循环**：`agentflow/src/agentflow/agent_loop.py::run_role` ⇒ 每一步由
   `agentflow/src/agentflow/modelgw.py` 走一次模型调用，记账经
   `agentflow/src/agentflow/llmseam.py` + `agentflow/src/agentflow/tokenmeter.py` 落 `usage_ledger`。
5. **决策落地**：`tool` ⇒ `agentflow/src/agentflow/tools/base.py::ToolRegistry.call`（过
   `agentflow/src/agentflow/policy.py` 与 `agentflow/src/agentflow/capabilities.py`）；
   `summon` ⇒ `agentflow/src/agentflow/conductor.py::Conductor.summon`（落 `tasks` 一行）。
6. **数据面**：任何写都经 `agentflow/src/agentflow/store.py::Store.tx` ⇒
   `agentflow/data/events.jsonl` 追加 + 快照原子替换；行级校验在
   `agentflow/src/agentflow/schema.py`。
7. **产出登记**：`agentflow/src/agentflow/artifacts.py::record`（
   `<工作区根>/ARTIFACTS.jsonl`）；会话叙事落 `<工作区根>/sessions/<会话号>.jsonl`
   （`agentflow/src/agentflow/sessions.py`）。
8. **论文包**（如果这一步涉及）：`agentflow/src/agentflow/tools/doc_tools.py::_paper_build`
   ⇒ `agentflow/src/agentflow/paperbuild.py::build` ⇒ 项目脚本
   `projects/p2-review/code/make_paper.py`（渲染）与 `compile_paper.py`（编译）
   ⇒ 回执与锚落 `projects/p2-review/out/paper/{COMPILE-RECEIPT.json,RENDER-ANCHOR.json}`
   + 构建历史 `projects/p2-review/out/paper/BUILD-HISTORY.jsonl`。
9. **收尾**：`agentflow/src/agentflow/deliver.py::gate` 给判据；H 的门
   `agentflow/src/agentflow/gates.py` 给四态裁决；审计
   `agentflow/src/agentflow/verify.py::verify_all`。

---

## 12. 测试面

- 位置：`agentflow/tests/`（162 个 `test_*.py`，另有 `conftest.py` 提供 `store` 等夹具）；
  配置在 `agentflow/pyproject.toml`（`[tool.pytest.ini_options]`，**唯一一处**）。
- 复跑：`cd agentflow && python -m pytest -q -p no:cacheprovider`。
  实测 2026-09-30（§198 之后）：**3083 passed / 0 failed / 3 skipped / 1 xfailed**（21:25）。
  上一轮（§196 提交 `ffd5621` 之后）是 **3071 passed / 1 failed**，那一条失败是
  `agentflow/tests/test_release_all.py::test_every_only_example_in_the_docstring_is_a_real_step_key`
  —— 它起子进程跑 `release_all --only role-specs,coverage`，而那条命令有 600s 上限：
  **整轮并发下会超时，单独复跑 510s 通过**（两轮都观察到同一现象）。
- **命名约定**：负控在文件名或函数名里带 `negative_control`；
  每个角色有 `agentflow/tests/test_agent_<role>.py`（见 `agentflow/DEVELOPMENT.md` §4.5）。
- **注册税**：新增工具/模块必须在
  `agentflow/tests/test_tools_returns_declaration.py`（`TOOL_COUNT` / `tool_params()` /
  `EXECUTED_KEY_SOURCE`）、`agentflow/docs/ROLE-SPECS.md`（§R0 全局工具总表 + 逐角色条数）、
  `agentflow/tests/test_release_all.py::_AGENTFLOW_TOP_LEVEL_MODULES`、
  `agentflow/tests/test_tools_readonly_roles.py::KNOWN_EXEC_TOOLS` 四处登记。

---

## 13. 文档面：哪份文件说什么（以及它的权威顺序）

| 文件（相对工作区根） | 说什么 | 权威顺序 |
|---|---|---|
| `agentflow/DEVELOPMENT.md` | **开发规范主入口**：六条硬纪律、DoD、测试规范、禁止模式、提交评审、发布检查、FC 覆盖矩阵；§0.3 的 `LIVE-READINGS` 块钉住会漂的数 | **最高**（判据） |
| `agentflow/AGENTS.md` | 只覆盖 **FC-27 禁 AI 区**这一节；与 `agentflow/.noai-paths` 逐条一致 | 与 `.noai-paths` 同级；**禁 AI 改** |
| `agentflow/.noai-paths` | 禁改区清单本体 | 同上 |
| `agentflow/docs/ROLE-SPECS.md` | 9 个角色 × 每节 10 个子节的详细规格 | 低于代码与 `DEVELOPMENT.md`，高于 `DESIGN*.md` |
| `agentflow/docs/INDEX.md` | `docs/` 的索引与"按角色怎么读" | 导读 |
| `agentflow/docs/NOAI-GOVERNANCE.md` | FC-27 的机制与人工批准流程 | 机制细节以此为准 |
| `agentflow/docs/PROPOSALS.md` | 已裁决的缺口与提案（P / G / N 三类） | **不构成判据** |
| `agentflow/DESIGN.md`、`DESIGN-CONDUCTOR.md`、`DESIGN-INTERACTIONS.md`、`DESIGN-ROLES.md`、`DESIGN-TOOLS.md` | 设计**理由**（"为什么这么设计"） | **不构成判据**；与代码冲突以代码为准 |
| `agentflow/README.md` | 使用说明（怎么跑、已知限制、目录结构、数据文件速查、发布门状态） | **不构成判据**；与代码冲突以代码为准（该文件 §7 自己声明） |
| `agentflow/NOAI-REVIEW-REGISTER.md` | FC-27 人工复核登记表（人读） | 登记 ≠ 批准 |
| `draft/`（本文件所在目录） | 交付报告正文（38 个 `*.md`，其中 35 份编号报告）；索引 `draft/README.md` | 报告，不构成判据 |
| `agentflow/docs/SCHEMA-*.md`、`ROLE-SPECS-DRAFT-N-O-Q.md`、`TOOLBOX-DRAFT-roles.md`、`PROPOSAL-*.md`、`NOAI-SUSPENSION-*.md`、`NOAI-CHANGE-LIST-management.md` | 迁移提案 / 草案 / 暂停记录 | 提案，不构成判据 |

---

## 14. 已知边界与残留（如实清单，观测 2026-09-30）

1. **`CAPABILITIES['G']` 里没有"重渲染论文包"这个可召唤动作**（只有
   `compose_claim` / `register_dependency` / `build_document` / `render` / `refresh_markdown` / `revise`）。
   第 9 次 review 运行是靠 **G 的 LLM 循环自己调 `doc.paper_render` / `doc.paper_compile`** 走通的；
   若那一轮 G 不被驱动，主控结构上无法让包跟上台账。加动作要改
   `agentflow/src/agentflow/capabilities.py`（FC-27 / 权限面，需 2 名 reviewer）。
2. **语义判据是单样本**：同一份产物在不同轮给过不同结论（`brain.blocker_specificity`：
   `vague` / `vague` / `specific`）。判据在 `agentflow/src/agentflow/judges.py`，
   修法（N 样本一致 / 至少一条落地发现才判 fail）尚未落地。
3. **`agentflow/src/agentflow/paperbuild.py` 只认识 `out/paper/` 这一种布局**；
   换项目布局要改它。
4. **本地灌库的 `books_dir` 未进沙箱**：`agentflow/src/agentflow/locallib.py` 的
   `ingest_directory` 收任意目录；调用面是 `agentflow/src/agentflow/tools/search_tools.py::search.ingest_local`（A 专属）。
5. **`projects/p2-review/code/p10_p11_meta.py` 里有一个绝对工作区路径**（项目脚本，不在框架内）。
6. **锚与回执是"当前状态"而不是"全历史"**：历史另存
   `projects/*/out/paper/BUILD-HISTORY.jsonl`，没有轮转与 actor 字段。
7. **禁改区有欠签**：`agentflow/.noai-approvals.json` 的批准只能由人签；
   当次欠签数请用 `agentflow/NOAI-REVIEW-REGISTER.md` 的口径现算，不要抄本文。
8. **协同的那条边表仍然是设计**（2026-09-30 复核）：`G` 够不到 `A`、`H` 够不到 `A`/`E`、
   `C` 没有任何出边 —— 今天靠 §7.4 的"请主控代唤"兜底，而不是靠直接边。
   要改成直接边就得改 `agentflow/src/agentflow/capabilities.py`（FC-27 / 权限面，需 2 名 reviewer）。
9. **"主控必须受理代唤申请"只到提示词 + 可审计这一层**：申请会落
   `agent_summon_request` 事件与 M 的收件箱，但**没有任何机器判据**强制 M 处理
   （能加的判据在 `agentflow/src/agentflow/verify.py`，那是禁改区）。
10. **同角色并发多实例的安全性由派活方负责**：实例轴只回答"允许不允许并发"，
    它不知道两个实例会不会改同一行。B/A 靠 `claimed_by` + 租约天然安全（既有判据
    `agentflow/tests/test_agent_b_gates.py::test_i6_two_agents_write_concurrently_without_deadlock`）；
    D/E/F/G 要并发就必须派到**不同目标**上 —— 框架不做行级冲突检测。

---

## 15. 十分钟自查：怎么证明这篇正文没骗你

下面每一条都能在十分钟内跑完（在 `agentflow/` 下；先设
`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'`）。
**每条都写出"该看到什么"** —— 对不上就是本文错了，按 `agentflow/DEVELOPMENT.md` §10 提修改。

| # | 命令 | 该看到什么 | 正文哪一节 |
|---|---|---|---|
| 1 | `python -c "import sys;sys.path.insert(0,'src');import agentflow.capabilities"` | 两行导入期自检：`覆盖 144 / 声明 144 个 property，50 个动作，接缝 1 条` 与 `两层参数类型对账：比较 73 对（动作, property），读到 62 个工具的 schema` | §4.1 |
| 2 | `python -m agentflow.cli tools` | `工具总数：73（已装模块 12）` + 逐角色 `A23/B18/C19/D37/E21/F32/G37/H25/M10` + 只读角色写工具泄漏为空 | §5.3 |
| 3 | `python -c "import sys;sys.path.insert(0,'src');import agentflow.schema as s;print(s.SCHEMA_VERSION,len(s.TABLES))"` | `1 16` | §3.1 |
| 4 | `python -c "import sys;sys.path.insert(0,'src');from agentflow import capabilities as C;print(sum(len(v) for v in C.ALLOWED_EDGES.values()), sum(len(v) for v in C.CAPABILITIES.values()), C.NON_SUMMONABLE)"` | `26 50 frozenset({'M'})` | §4.1 |
| 5 | `python -c "import sys;sys.path.insert(0,'src');from agentflow import gates as g, judges as j;print(len(g.GATES), len(j.CRITERIA))"` | `15 6` | §6.3 / §6.4 |
| 6 | `python -B tools/verify_role_specs.py` | `[ok]`，9 个角色节 × 10 子节，逐角色工具条数与现场一致 | §6.2 |
| 7 | `python -B scripts/lint_rules.py` | `error 0 / warning 9 / info 47`（严格档 `0 / 51 / 46`） | §10.2 |
| 8 | `python -B scripts/noai_gate.py --check-consistency` | 退出码 0（清单两处逐条一致） | §10.8 |
| 9 | `python -m agentflow.cli --help` | 21 个子命令 | §8.2 |
| 10 | `python -m pytest -q -p no:cacheprovider tests/test_tools_returns_declaration.py tests/test_paper_pack.py` | 全绿（工具声明与论文包段的两组判据） | §5.4 / §12 |
| 11 | 打开 `agentflow/pyproject.toml` 与 `agentflow/.noai-paths` | 前者有 `[tool.pytest.ini_options]`；后者 27 条 glob / 24 条唯一路径 / 7 类 | §13 |

**两条"不要看错"的提醒**（本项目踩过）：

- 第 7 条的 `warning 9` **不是**"快坏了"：那 9 条里有 R007 一族与 R010-c 登记过的**字面假阳性**
  （逐条见 `agentflow/scripts/lint_rules.py` 的输出与 `agentflow/docs/PROPOSALS.md`）。
  发布门只看 `error` 那一栏必须为 0。
- 第 8 条的 `--check-consistency` 只保证"清单两处一致"，**不保证清单没被动过**；
  "动没动"由 `agentflow/.noai-approvals.json` 的 hash 台账回答（见 `agentflow/docs/NOAI-GOVERNANCE.md`）。
