# 读代码的入口：七层 + "想改什么 ⇒ 读哪几个文件"

> **这份文件回答一个问题：我现在要改的东西，代码在哪、判据在哪。**
>
> 起因（`draft/36` §3）：`src/agentflow` 77 个文件、77,391 行，**38 个文件超过 800 行**
> （最大 `agent_d/`（包） 4188 行）。新人打开任何一个文件都是一本小册子，
> 于是"从哪读起"本身成了一道门槛 —— 这份图就是为了把这道门槛拆掉。
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

## §1 七层与它们各自的文件

层与层之间是**单向**的：上层可以读下层，下层不反向 import 上层。
括号里是这个文件存在的理由（取自它自己的模块 docstring）。

### 第 0 层 · 入口

| 文件 | 是什么 |
|---|---|
| `cli.py` | 命令行入口（24 个子命令；`project`/`run`/`run-agent`/`verify`/`tools`/`web`/`doctor`…） |
| `webui.py` | 用户端网页：全局待回答面板 + 运行态 + 一趟的事件回放（只读投影；唯一写路径是 `POST /answer` → `userio.answer_question`） |
| `toolchain.py` | 这台机器上的证明工具链（一处定义）：显式配置 → `AGENTFLOW_PROVER_PATH` → PATH 三档查找 + 三态探测 + Mathlib 那一轴；探测（禁改区的 `verify_tools.detect_verifier`）与调用（`formalgw.find_lean`）共用这一个答案，`agentflow doctor` 把读数打给人看 |
| `web/` | 网页的样式与令牌：DSH 的令牌整份照搬（来源与 MIT 见 `docs/USER-END-DSH-STYLE.md`） |
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
| `manuscripts.py` | **交接手稿**的唯一实现（`draft/37` §134，用户口径）：`manuscripts/` 下的 `<编号>-<谁>to<谁>.md`（给所有人写 `toALL`）、编号从 `0000` 起**由脚本扫文件分配**（不从账本读）、文件锁下的并发写、账本文件只是流水。为什么要它：交接的"派活依据"与"溯源"此前只活在对话里 —— 写了手稿之后每一跳都能被第三方从盘上复核。写走循环形状 `handoff`（文件名要写"谁"，而工具层拿不到 per-call 身份），读/列走 `tools/manuscript_tools.py`（A–H 八面，M 用 `fs.*` 白名单读同一批文件） |

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

### 第 4 层 · 角色面（八个角色各自的一本账）

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

> 八个角色（除主控）的包形状是一样的（`goal-7f5116c1` M6/M7）：入口 `__init__.py`、
> 其余成员与 mixin 组装在 `agent_a/core.py` 这样的 core 模块里、模块级 helper 与常量在
> `agent_a/_support.py`、一个动作一个文件（如 `agent_a/search_literature.py`）、
> `python -m agentflow.agent_a` 的自检入口在同目录的 `agent_a/__main__.py`。
| `agents` 的公共零件：`claimanatomy.py` | 断言解剖学 —— `documents.claims` 每个元素的唯一判据来源 |
| `claims.py` | 原子断言拆分（把一段答复切成可逐条回验的断言） |
| `quoteverify.py` | 引文校验：引文级回验（禁改区） |
| `dedup.py` | 判重：文献 / 概念 / 关系（禁改区） |

### 第 5 层 · 循环面（模型自己决定调什么）

| 文件 | 是什么 |
|---|---|
| `agent_loop.py` | LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕 |
| `agent_prompts.py` | A–H（含 M）的前置提示词：身份、边界、政策、工具、伙伴、契约、三态、循环协议 |
| `llm.py` | 抽取层：`Extractor` 协议 + 离线基线 + 可插拔 `LLMExtractor` |
| `llmseam.py` | 统一的模型缝：一次模型调用 = 一条可审计的记录 |
| `judge.py` | LLM 判定的唯一缝协议 |
| `judges.py` | 语义判据的接入方式：注册表 + 三态 + 引用落地过滤 |
| `promptkit.py` | 提示词装配：有序段 + 变量 + 作用域遮蔽 |
| `contextbudget.py` | 上下文预算：压缩 / 剪枝 / spill |
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
| `closing.py` | 收工门（`draft/37` §16 P3）：五条各自一个三态读数 —— 锚 `consistent` / 无未裁决矛盾 / 承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题。**工具 `conductor.closing` 与 CLI `agentflow closing` 都调 `closing.check_closing`（同一份实现、两个入口）**；`unknown` 不是通过 |
| `reviewaccept.py` | 审稿场景的**内容级**验收（`draft/37` §17.3）：报告九节且每栏有读数 / 定理台账每条有完整假设与出处页码 / 三态分支落盘可查 / 在成本上限内 / 每跳留下可读输入。**判据与辅助读数分栏** —— `sha`/页数/锚/行数那五种"容易拿到"的读数照原样给出，但**一个都不参与 `passed`** |

### 第 7 层 · 质量与产物面

| 文件 | 是什么 |
|---|---|
| `evidence.py` | 证据层：先检索、再逐字回验 —— 每条结论都落在某段真实原文上 |
| `artifacts.py` | 产物登记：谁在哪个路径产出了什么 |
| `paperbuild.py` | 论文包的构建 / 编译 / 锚核对 |
| `renderanchor.py` | 渲染锚与编译回执：判"包还是不是库里现在的样子" |
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
| 动 **G 的写作** | `agent_g/`（包） | `gates.py`、`tools/doc_tools.py`、`paperbuild.py` | `tests/test_agent_g.py`、`tests/test_paper_pack.py` |
| 动 **H 的审校** | `agent_h/`（包） | `gates.py`、`tools/review_tools.py` | `tests/test_agent_h.py`、`tests/test_gates.py` |
| 动**主控编队 / 并发** | `conductor.py` | `scheduler.py` → `host.py` → `tools/conductor_tools.py` | `tests/test_conductor.py`、`tests/test_scheduler.py`、`tests/test_host_wiring.py` |
| 动**角色循环**（模型自己决定） | `agent_loop.py` | `agent_prompts.py` → `host.py` → `llmseam.py` | `tests/test_agent_loop.py`、`tests/test_agent_prompts.py` |
| 往**提示词**里加一句话 | `agent_prompts.py` | 它引用的现算来源：`capabilities.py` / `tools.build_registry` | `tests/test_agent_prompts.py`（每条都要与现算一致） |
| 动**模型调用与花销** | `modelgw.py`（唯一读 key 的地方） | `modelclient.py` → `tokenmeter.py` → `modelcost.py` → `llmseam.py` | `tests/test_modelgw.py`、`tests/test_tokenmeter.py` |
| 动**判据 / 质量门** | `verify.py`（禁改区） | `gates.py`、`deliver.py`、`faculty_checks.py` | `tests/test_verify*.py`、`tests/test_gates.py` |
| 动**发布门** | `tools/release_all.py`（禁改区） | `tools/coverage_zero_test.py`、`tools/run_each_test_file.py` | `tests/test_release_all.py`、`README.md` §6 |
| 动**lint 规则** | `scripts/lint_rules.py`（禁改区） | `tools/vocab_census.py`（禁改区） | `tests/test_lint_rules*.py` |
| 改**禁改区规则本身** | `AGENTS.md` + `.noai-paths`（两处必须逐条一致） | `scripts/noai_gate.py`（禁改区） | `tests/test_noai_gate.py`、`--check-consistency` |
| 加一个**子命令** | `cli.py`（`build_parser`） | 对应 `cmd_*` | `tests/test_cli_run.py`、`tests/test_user_quickstart.py` |
| 查**一次运行到底做了什么** | 产物目录 `out/run-N/`（六件） | `runflow.py`、`evidence.py` | `report.md` / `run-manifest.json` |
| 查**谁在什么时候说了什么** | `sessions.py` 的会话记录 | `agent_loop.py`（事件种类） | `tests/test_sessions.py` |

---

## §3 这些文件为什么这么大（读之前先知道边界）

| 文件 | 行数 | 它的边界 | 为什么大（不是"没整理"，是职责本身宽） |
|---|---:|---|---|
| `agent_d/core.py` | 1608 | D 的全部动作（15 个，**拆包**：一个动作一个文件；`agent_d/core.py` 是其余成员，1608 行；`agent_d/_support.py` 是模块级 helper 与常量，641 行）：摄入 / 溯源 / 评估 / 提问（`propose_question`）/ 裁决 / 研究 / 汇报 | 每个动作都自带"数据面前置检查 + 落库 + 三态"三段，15 个叠起来就是几千行 |
| `agent_c/core.py` | 1134 | C 的 9 个纯读分析动作（**拆包**：一个动作一个文件；`agent_c/core.py` 是其余成员，1134 行；`agent_c/_support.py` 是模块级 helper 与常量，325 行） | 分析类动作的**输出形状**很宽（每条都要给人读的措辞 + 给机器读的结构） |
| `capabilities.py` | 2267 | 动作表 + 写集 + 边表 + 导入期交叉断言 | 声明本身不长，长的是**逐条理由**与断言（禁改区，必须写清为什么） |
| `providers.py` | 2880 | 每个数据源一个 `_parse_*` + 查询编排 + 限速重试 | 上游越多、字段越脏，解析越长（禁改区） |
| `gates.py` | 2745 | G1–G15 十五道独立检查器 | 一道门一个函数，每道门都带判据说明与负控 |
| `schema.py` | 2764 | 17 张表的 dataclass + 词表 + 校验 | 字段多、每个字段都带契约注释（禁改区） |
| `runflow.py` | 2039 | 一次 `run` 的全流程（取材料 → 跑模型 → 落六件产物） | 主路径把每个阶段的失败分支都写全了；`run_topic` 已按 `T-7` 拆成 6 个 `_phase_*`（最长 228 行）+ 130 行编排层 |
| `evidence.py` | 1892 | 检索 + 逐字回验 + 来源登记 | 三档回验级别各一套路径 |
| `cli.py` | 2389 | 25 个子命令的入口与打印 | 每个子命令的 `--help`、三态退出码、卡片式输出 |
| `claimanatomy.py` | 1671 | 断言解剖学（每条断言的可判定性） | 判据多且互相独立 |
| `agent_b/core.py` | 1045 | B 的 7 个动作（**拆包**：一个动作一个文件；`agent_b/core.py` 是其余成员，1045 行；`agent_b/_support.py` 是模块级 helper 与常量，168 行）：入库 / 重抽取 / 结构重复裁决 / 登记命题 | 回验是"每条关系都要过"，代码密度高 |
| `verify.py` | 1605 | 全局不变量审计（`verify_all` 已按 `T-5` 拆成 13 个 `_check_*` + 30 行编排层） | 40 多条不变量平铺（禁改区，见 T-5） |

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
