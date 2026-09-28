# A–H 角色的 LLM 接入草案（判断点投影 + 接线计划）

> **本文是设计草案，待人裁；不是实现记录。** 它只回答一件事：每个角色里
> 哪些判断该交给 LLM、哪些绝不许交，以及怎么接线才不破现有绿线。
>
> 证据纪律：本文出现的每个数字都标了来源（实测命令 / 文件:行 / 规格原文）；
> 凡未实测的都逐字标 **待实测**，不填占位数字。与 `draft/28` 的登记册编号无关，
> 本文自用 `L-` 前缀给判断点编号（`L-A1` 等），便于以后判据与测试直接引用。

---

## 0. 一句话原则

**LLM 只做三类事：生成候选 / 语义判定 / 排序与措辞。**
凡"判据"（证据等级、状态、计数、预算、去重键、依赖闭合、权限）一律机械判定。
**LLM 的输出永远是候选，不是事实**；事实由逐字回验、检查器输出、存在性核对确定。

这条原则不是我编的，它是规格里已经写好的减法：`test/test1/DESIGN-ROLES.md:14-23`
把 8 个角色"最容易犯的错"逐条配了**机械对策**（`outcome` 词表 / `quote_verified` 三态 /
`truncated` 字段 / L1-L3 溯源 / `evidence_kind` 词表 / 三维预算 / `Document.validate` /
`ReviewFinding.evidence` 必填）。机械对策占掉的那半边**不许**再让 LLM 碰；
没被占掉的另一半，才是本文要投影的部分。

---

## 1. 事实基线（全部实测，可复核）

### 1.1 每个角色模块内的 LLM 调用点（命令：`Select-String -Path src\agentflow\agent_*.py -Pattern '\.complete\(|llm\.'`）

| 角色 | 模块内 LLM 调用点 | 说明（逐字） |
|---|---|---|
| A | **0** | 检索走注入的 `providers` |
| B | **0** | 判断在注入的 `extractor` 里（`Extractor` 协议，`llm.py:170`） |
| C | 2（`agent_c.py:2406`、`:2411`） | docstring：「程序做分析，LLM 只做排序与措辞」「只有两处留 LLM 钩子，且**默认关闭**」 |
| D | 1（`agent_d.py:3297`，prompt 在 `:3271`） | 已经是注入式 `self.llm.complete(prompt)` |
| E | **0** | `agent_e.py:110`：「本模块不调用 LLM（`llm` 位置参数仅为与 A–D 的构造签名保持一致，当前未使用）」；`:598`：「数值实验的判读必须是确定性的（FC-16）」 |
| F | **0** | — |
| G | **0** | — |
| H | **0** | — |

### 1.2 构造缝（实测的 `__init__` 签名；关键字参数才是"缝"）

| 角色 | 位置参数 | 关键字注入 |
|---|---|---|
| A | `store` | `providers, downloader, config, actor` |
| B | `store` | `extractor, extract_text, config, actor` |
| C | `store, config, actor, llm` | — |
| D | `store, config, actor, tools, llm` | `trace_tools, c` |
| E | `store` | `config, workspace_root, log, llm, tools, actor` |
| F | `store` | `config, log, e, tools, actor` |
| G | `store` | `config, workspace_root, log, tools` |
| H | `store` | `config, log, tools, writers` |

`D` 手里有 `c`、`F` 手里有 `e`、`H` 手里有 `writers` —— **"谁能叫谁"在构造期就定死了**，
召唤时再过 `capabilities.ALLOWED_EDGES`（`capabilities.py:1571-1590`）与
`policy` 的四道上限。这条结构在本草案里**不动**。

### 1.3 工具面（实测：`build_registry()` + `registry.for_role(r)`）

- 注册表并集 **43 个工具**，其中通用表操作 **8 个**（`table.count/create/delete/get/list/schema/search/update`），
  语义工具 **35 个**；装配读数：`loaded 9 / skipped 2 / params_checked 43`；
  导入期交叉断言打印：`覆盖 127 / 声明 127 个 property，49 个动作，接缝 1 条`。
- 逐角色：A 13（通用 8 / 语义 5）、B 11（8/3）、C 13（5/8）、D 25（8/17）、E 14（8/6）、
  F 25（8/17）、G 25（8/17）、H 18（5/13）、**M 0**。
- **发现（与本草案直接相关）**：`table.update` 的 `roles=('A','B','D','E','F','G')` ——
  通用表工具只按"读/写角色"裁，**没有"角色→表"的调用期闸门**（`WRITE_SETS` 只被
  `scheduler` 用作并发判据）。⇒ 给 LLM 更大自主权之前，这条必须先收（见 §6 风险 3）。

### 1.4 两个"留了插座没插电"的确凿出处

- **F 的最大能力边界**（`test/test1/DESIGN-ROLES.md:113` 逐字）：
  `owner ∈ {C,D,F}` 时只记一条 `outcome="no_change"`，detail 写
  「需要 C/D/F 的推理，本框架尚未接线自动推理 ⇒ **未推进**」；`:239-240` 自评
  「这是本轮**最大的能力边界**」。
- **主控未接线**（`conductor.py:261-288`）：`SubagentBackend.call` 直接
  `raise NotWiredError` ⇒ 台账落 `refused/not_wired`；`:294-299` 逐字：
  「主控：确定性的策略执行者（本轮不做 LLM 推理）」，「"想做什么"由调用方给出 plan」。

### 1.5 三条"绝不许交给 LLM"的规格原文

- **E**：脚本自报 `evidence_kind="proof"` **一律降级为 `cross_check`**；理由逐字：
  「让被判定的对象自己当判官，是这一层最容易被绕过的地方」（`DESIGN-ROLES.md:91-92`）。
- **H**：§5.2 逐字「H 能否发现"数学错误"？**不能**，本轮明确不做。H 只判"稿件有没有把
  自己说清楚"」（`:234-236`）。
- **G**：`CROSS_CHECK_DISCLAIMER` 由结构强制填、H **精确匹配**该常量；理由逐字：
  「若允许多种写法，审校就只能靠语义判断，而"靠语义判断"正是要避免的东西」（`:60-68`）。

### 1.6 复核命令（本文每个读数都能一键重跑）

```powershell
# LLM 调用点
Select-String -Path agentflow\src\agentflow\agent_*.py -Pattern '\.complete\(|llm\.'
# 构造缝 / 工具面
python temp\_read_ctor.py ; python temp\_read_tool_mix.py ; python temp\_read_spec_roles.py
# 召唤矩阵
python temp\_read_edges.py
```

---

## 2. 判断点投影表（29 个点，逐格可核）

> 「猜想」相关与「跨语言」相关的判断点在 **§7.6**，编号 `J-*`（共 10 个：
> `J-A1`…`J-M1` 九个 + §9.7.5 的 `J-G2` 译文忠实性）—— 它们是跨角色的对象，
> 不属于任何单一角色。

读法：**判断点** = 该角色里"必须靠语义"的那一步；**允许的 LLM 动作** = 它可以产出什么；
**输出契约** = 落到哪个字段/文件、带什么证据；**禁止** = 机械判据清单里的对应项；
**负控** = 证明这个接入点真的在起作用的注入实验。

### 2.1 A —— 检索

| ID | 判断点 | 允许的 LLM 动作 | 输出契约（落点） | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-A1` | 主题 → 多组检索式 | 产出 ≤N 组检索式 + 每组一句理由 + 语言标记 | `agent_a.py` 新增 kwonly 缝 `query_planner`（默认 `None` = 现行单条查询，行为逐字节不变）；每组式作为**独立** provider 调用，合并走既有判重 | 改 `outcome` 落值；碰 `normalize_doi`/`dedup_key_of` | 注入"永远返回空计划"的 planner ⇒ 必须退回原始单条查询，并在审计字段里如实写 `plans_from="rule"`（不许静默当成功） |
| `L-A2` | 候选相关性精筛 | 对每条候选给 `keep/drop` + 一句理由 + 置信 | 只作为**候选**传给既有 `search.register`；落 `out/` 的检索审计文件（不新增表，见 §3.2） | 直接写 `literature`；把 drop 说成"这篇文献不存在" | 注入"全 drop"的判定 ⇒ 必须落 `outcome="no_results"` 且带 `judge_dropped=N`，**不许**写成"没有这篇文献"（A 的招牌错误） |
| `L-A3` | 继续搜 / 收手 | `continue` 或 `give_up` + 一句理由 | 写进请求行的审计字段（沿用 I7 的"为什么是它"那套可观察字段） | 把 `give_up` 落成 `no_results`；超预算继续搜 | 预算=0 时必须 `give_up`，且理由里必须含预算读数（可逐字核） |

> 现状：`providers._plan_mode` / `_precise_keep` / `_broad_sort_key` 是**确定性**检索口径，
> 且在 FC-27 禁改区（`solver-core`）。所以 `L-A1/A2` **只能走注入缝**，
> 不许为了塞 LLM 去改 `providers.py` —— 要改就是人审 + 2 名 reviewer（见 §4.6）。

### 2.2 B —— 整理

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-B1` | 概念与定义抽取（长句/隐含定义） | 产出概念候选 + 定义句 | 扩展 `Extractor` 协议**已有**的 `LLMExtractor`（`llm.py:716`）；不新增协议 | 协议改名/改签名（B 只认协议） | 用 `NullExtractor` 换掉 ⇒ 必须落"零抽取"并如实计数，不许把空结果当"这篇没概念" |
| `L-B2` | 概念名归一 / 同名判定 | 判"这两处名字是否同指"+ 证据句 | 只给**候选合并**；唯一性仍由锁内解析裁决（`agent_b.py:199+`） | 自己分配概念代号；自己决定合并落库 | 注入"全判同指" ⇒ 必须被"合并需两路独立证据"拦下并留理由（I5：假同义 ⇒ 拒绝并留理由） |
| `L-B3` | 关系抽取 + 关系类型 | 每条关系 + **逐字 quote** | quote 走 `quoteverify.check_quote` 回验 | 写 `quote_verified`（那是回验的判据） | 注入一条编造的 quote ⇒ 必须 `not_found`（这就是 B 的招牌错误的负控） |
| `L-B4` | 同义/矛盾的**语义**判定（I5/I6） | `strong` / `weak` + 证据句 | 只有 `strong` 允许驱动 `status="suspect"`；`weak` 进 `weak_signals` | 让 `weak` 驱动状态；不看证据就报矛盾 | 实测教训照搬（`DESIGN-ROLES.md:191-207`：字面判据 25 条真实关系报 6 条 suspect、真矛盾 0 条 ⇒ 假阳性 24%）。**上闸门前必须在 ≥20 条真实关系上量触发率并逐条可核**（§4.3 纪律） |

### 2.3 C —— 分析

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-C1` | 报告解读与排序 | 排序 + 每项一句理由 | 沿用现有两个钩子（`:2406`/`:2411`），默认仍关 | 改计数/枚举/路径/评分 | 关掉钩子 ⇒ 报告必须与确定性版逐字节相同（"默认关闭"必须真关） |
| `L-C2` | 缺口语义化（I3） | 候选缺口 + 图里的结构证据 | **只提候选**，不直接发请求（C 的边是空的） | C 直接发检索请求；把"没枚举完"说成"没有更多" | 注入"凭空造一个缺口"⇒ 必须被"候选缺口必须能对应到图里的结构证据"判据拦下 |
| `L-C3` | 措辞 | 统计 → 研究判断的措辞 | 措辞字段；不得引入新事实 | 在措辞里塞进未入库的结论 | 注入一条含新事实的措辞 ⇒ 判据必须报"措辞含未登记事实" |

### 2.4 D —— 研究

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-D1` | 问题生成 | 从 C 报告产出 `research_questions` **候选** | 落既有表（走既有状态机），带来源 report_id | 自己改问题状态；凭空造来源 | 注入无来源的问题 ⇒ 必须拒收（来源必填） |
| `L-D2` | 证据充分性判据 | `sufficient` / `insufficient` + 缺什么 | 判据落 `checked` 三态；`insufficient` 必须列出缺口项 | 把"查不到"写成"研究发现" | 注入"证据为空却判 sufficient" ⇒ 必须被"无 L1/L2/L3 命中不得判 sufficient"拦下 |
| `L-D3` | 裁决（真/假矛盾，I2） | 裁决码 + 证据 | 走 `interactions.adjudicate_contradiction`（纯函数、无 store） | 自己发明裁决码（受控词表在契约里） | 注入"永远判真矛盾" ⇒ 必须在预算内终止并标 `persistent`，不许无限循环 |
| `L-D4` | 结论溯源定位 | 指出该结论对应哪条 L1/L2/L3 | 溯源级别仍由证据判定，LLM 只**指认候选**位置 | 自己写溯源级别 | 注入"声称 L3 但给不出 L1 命中" ⇒ 必须落 L0/`unknown` |

### 2.5 E —— 实验（最窄：LLM 是"写代码的助手"，不是判定者）

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-E1` | 断言 → 可跑脚本 | 产出脚本内容 + `params` 建议 | 走 `verify.run_experiment`（`exit_code` / `REPRO_RESULT` 解析全归它） | 判定 `result` / `negation_kind` / `evidence_kind` | 让脚本自报 `proof` ⇒ **必须**被降级为 `cross_check` 并记进 `notes`（`:91-92`） |
| `L-E2` | 失败诊断 / 改脚本 | 诊断 + 新脚本 | 每次尝试落台账；受 `max_persist_attempts` | 无限重试；把 `inconclusive` 说成失败或成功 | 注入"永远失败的脚本生成"⇒ 必须在上限处停下并如实记 `inconclusive` |
| `L-E3` | 反例的人读解释（I11） | 描述 + 可复现代码与输出 | 反例存为可复现物；`result="refutes"` 才允许回流 | 用 `inconclusive` 触发回流 | 注入 `inconclusive` 的实验 ⇒ **不得**生成回流问题 |

### 2.6 F —— 攻坚（当前"最大的能力边界"）

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-F1` | 难题 → 子目标 | 子目标候选 + 每个一句判据 | `create_plan(subgoals=...)` 的入参改为可选 LLM 生成 | 子目标绕过三维预算；深度自增 | 注入"永远新增子目标" ⇒ 必须在 `max_rounds` / `max_depth` 处停下并记 `stalled` |
| `L-F2` | `owner` 分派建议 | 建议 owner + 理由 | **落值仍由 `ALLOWED_EDGES` + 闸门裁决** | 建议越权 owner；建议只读角色做写动作 | 注入"建议 owner=M / owner=H 去改稿" ⇒ 必须被 `ALLOWED_EDGES` 拦下并记 `refused` |
| `L-F3` | `owner ∈ {C,D,F}` 子目标的**真推理** | 推理记录 + 结论候选（带证据链） | 消掉 `:113` 的 `no_change` 占位：改为真推进，或如实记 `no_progress_with_reason` | 把推理结论当已证事实；无证据仍标推进 | 注入"无证据却报推进"⇒ 必须落 `no_change` + 理由（**不许**留一条看起来在推进的空轮次） |
| `L-F4` | 卡住时的 `best_partial` 与转向 | 摘要 + 转向建议 | `stalled` 必填 `best_partial`（schema 已有硬约束） | 把"卡住"说成"解决" | 注入"直接标 closed" ⇒ 必须被"无 `proof_experiment_ids` 不得 closed"拦下（`:51-58`） |

### 2.7 G —— 撰写

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-G1` | 断言成文 | 生成 `text` | `compose_claim(text, citations, evidence_kind, ...)`；后三项**由代码填** | LLM 决定 `evidence_kind`、`section`、`is_negative` | 注入"无引用断言" ⇒ `Document.validate` 必须拒（`:22`） |
| `L-G2` | 章节组织与过渡 | `sections` / `open_problems` 行文 | 仍走 `build_document` | 生成内部不一致的 dependence | 注入一条指向不存在 `lit_id` 的 `closed` 依赖 ⇒ 必须报 `dangling_dep`（I12） |
| `L-G3` | 选引用 | 指出哪条 lit/exp 支撑这句 | 落 `register_dependency`，`closed` 前**必须核 ID 真存在** | 跳过存在性核对 | 注入不存在的 ID ⇒ 必须拒（`:137-139`） |
| `L-G4` | 无出处自查 | 自评"这句有依据吗"+ 理由 | 只作候选提示；落库判据仍属 `validate` + H | 自己把自查当结论 | 关掉自查 ⇒ 交付判据（H 的 `unsupported_claim`）必须仍然能抓到 |

### 2.8 H —— 审校（只读；只判"说清楚没有"，**不判数学**）

| ID | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|
| `L-H1` | 说清楚没有（含糊 / 过度声称） | finding 候选 + **必填证据** | `ReviewFinding.evidence` 必填非空（`:23`）；严重度落受控词表 | 只写"这里有问题"；写文档状态 | 注入一条无证据的 finding ⇒ **必须拒收**（这是本项目"最贵的一课"的直接落地） |
| `L-H2` | 引用**支撑度**（引文存在但不支撑这句） | `warning`/`error` 建议 + 证据 | 这是 B 的逐字回验**查不到**的那一层；LLM 的判定必须带具体引文与断言对照 | 把"逐字存在"当"支撑"；判数学对错 | 注入"引文逐字存在但结论更强"的稿子 ⇒ 必须报 `overclaim`（不是 `unsupported_claim`） |
| `L-H3` | 告警分级（FC-13） | 分级建议 | `warning` = 表里已记录的边界；`error` = 表里记录与重算事实矛盾（`:152-158`） | 把已知边界报成 error（训练人忽略红灯） | 用 `external_unavailable` 依赖 ⇒ 必须 `warning`，不是 `error` |
| `L-H4` | 改好了没有（`verify_fixes`） | 判定 + 证据 | 仍须 evidence；error 全 fixed 才能 `accepted` | 凭印象说"修好了" | 注入"改了别处"的修订 ⇒ 必须判未解决 |

---

## 3. 共用基础设施（所有点共用；**不许**各角色各写一份）

### 3.1 唯一的 LLM 缝协议

沿用 D 已经在用的形态：`llm.complete(prompt) -> str`，解析走 `llm.parse_llm_json`。
新接线一律用**同一个协议名**（`Judge`），失败分类**三分**且不许折叠：

| 失败 | 落值 |
|---|---|
| 超时 / 网络错 | `unknown` + `reason` 逐字（**不许**落"没找到"） |
| 返回不是合法 JSON | `unknown` + `bad_json` |
| 预算用尽 / 未接线 | `not_wired`（`refused` 语义，与 `conductor` 一致） |

依据：`llm.py` 已有 `ExtractionError` / `parse_llm_json`；`conductor` 已有
`refused/not_wired` 语义（`conductor.py:261-288`）。

### 3.2 候选落点：**先落文件，不新增表**

**卡点**：新增一张表要改 `schema.TABLES`，而 `schema.py` 在 FC-27 禁改区
（`schema-migration` + `eval-criteria`）。P1–P3 阶段一律**不新增表**：候选落
`out/` 下的审计文件（与六件产物同族），或落既有表的既有审计字段。
要用真表，单列一条人审项（见 §6 风险 2）。

### 3.3 三态与证据（把 §4.1 的教训变成判据）

- 每个点必须落 `checked` + `reason`；
- **无证据的 LLM 判定不得驱动任何 `status`**（沿用"字面矛盾判据不许驱动状态"的裁决）；
- 语义闸门上线前必须在 **≥20 条真实样本**上量触发率并逐条可核（`DESIGN-ROLES.md:222-226`）。

### 3.4 预算与计量

每个点一个 `scope` 名（`llm-a-plan`、`llm-h-review`…），走既有 `tokenmeter` / `modelcost` /
`usage_ledger`（`projects.py` 已有 `scope="extract"` 的先例）。**每个点的美元上限标 待实测**：
先用同一主题跑 3 次取中位数再填，不许先写一个好看的数。

### 3.5 可复现

prompt 版本进 `run-manifest.json`（机制已有：`prompt_version`，见 `runflow.run_topic` 参数）；
温度 0；每点重试上限与幂等键（`usage_ledger` 已有幂等键先例）；同一输入两次跑必须同结果。

### 3.6 禁改区边界（硬约束）

| 若要接的点落在 | 归属 | 处置 |
|---|---|---|
| `providers.py`（检索核心） | FC-27 `solver-core` | **绕开**：把 LLM 放在 A 自己的注入缝里，分组调用 provider |
| `dedup.py` / `extract.py` | FC-27 | **不碰**（去重键、抽取主通道） |
| `schema.py` / `store.py` | FC-27 | 不加表、不改字段；需要就单列人审 |
| `tools/__init__.py` / `tools/base.py` | FC-27 `auth-audit` | 新增工具要走人审（工具面=权限面） |
| `verify.py` / `interactions.py` / `capabilities.py` | FC-27 | 契约与召唤矩阵**本草案不动** |
| `agent_a..h.py`、`conductor.py`、`llm.py` | 非禁改区 | 可直接改，仍走四道门 |

---

## 4. 接线顺序（四阶段；每阶段独立可验、可停、可回退）

| 阶段 | 内容 | 完成判据（可核） | 不许越界 |
|---|---|---|---|
| **P1 插插座** | A/F/G/H 加 kwonly `llm=None`；E 把已有的空插座接上；统一 `Judge` 协议 | 默认路径下**逐字节不变**：既有全量测试全绿 + 与改前产物的 sha256 对照；断言"未接线时零 LLM 调用" | 不改任何判据、不加表、不动 FC-27 |
| **P2 低风险判定类** | `L-B4`、`L-C2`、`L-D2`、`L-D3`、`L-H1`~`L-H4` | 每点一条判据 + 一条负控（§2 每格最后列）；语义闸门附 ≥20 条真实样本触发率读数 | 仍不新增表；候选只落文件 |
| **P3 生成类** | `L-A1`~`A3`、`L-E1`~`E3`、`L-F1`~`F4`、`L-G1`~`G4`、`L-B1`~`B3`、`L-D1`/`D4` | 每点一条"候选不落事实"判据（注入幻觉 ⇒ 必须被拦）+ 一条"未接线时行为不变"判据 | 不碰 FC-27；F 的预算/状态机不动 |
| **P4 LLM 主控** | plan 生成交 LLM（`conductor` 的 backend 面；可走 DSH `subagent`） | `policy` 四上限与 `scheduler` 分波**读数不变**；越权/超预算仍 `refused`；`NotWiredError` 路径保留给"未接线的动作" | 不改 `policy`/`scheduler`/`ALLOWED_EDGES` |

每阶段结束跑**同一套四道门**（lint / 全量 / 逐文件 / `release_all`），并按 `draft/28` 的
纪律把读数登记进册。P4 之前不动 `conductor`，因为它是审计面。

---

## 5. 判据与负控的写法（模板）

每个 `L-xx` 落地时必须带三样，缺一不许合：

1. **正控**：合法输入 ⇒ 该点产出候选且落三态；
2. **负控（注入会咬）**：把该点的实现短路/换成"永远返回某个方向"，对应用例**必须变红**
   （本项目已验证过的做法：`temp/_ev_inject_check.py` 用影子包逐条注入并断言红）；
3. **未接线等价**：`llm=None` 时该角色行为与改前**逐字节相同**（用 sha256 对照产物）。

---

## 6. 风险、代价与**不做**清单

1. **不做**：让 LLM 判 `evidence_kind`/`proof`、`quote_verified`、`checked` 三态、状态机、
   预算计数、去重键、依赖闭合、告警严重度落值、权限。后果逐条都在 §1.5 与 `:14-23` 里。
2. **风险 1｜新增表**：候选若要真表 ⇒ 命中 FC-27 `schema.py`，需人写或人逐行走查 + 2 名 reviewer。
   本草案的规避办法是"候选落文件"；要不要上表请裁。
3. **风险 2｜工具面授权缺口**（实测）：通用表工具只按读/写裁（`table.update roles=('A','B','D','E','F','G')`），
   没有"角色→表"的调用期闸门。LLM 自主度越高越危险。**建议在 P3 之前补一条**：
   调用期按 `WRITE_SETS` 判"这个角色的这个动作能不能写这张表"。注意这条落在
   `tools/base.py` / `tools/__init__.py` ⇒ **FC-27，需人审**。
4. **风险 3｜假阳性训练人忽略告警**：实证 24% 假阳性已让 `suspect` 失去意义
   （`DESIGN-ROLES.md:191-207`）。语义闸门必须有触发率上限，否则不上。
5. **风险 4｜成本**：每点一个 scope，美元上限 **待实测**；未接线时零成本（P1 判据保证）。
6. **风险 5｜"看起来在推进"的空轮次**：F 的 `no_change` 占位就是防这个；`L-F3` 接线时
   必须保留这个语义（真推进才写推进）。

---

## 7. 猜想（conjecture）：为什么它**不止**是 D↔E 的事

一句话：`test/test1/DESIGN-ROLES.md:14-23` 那张"每个角色的产出"表里**少了一行**。
八行产出分别是 文献 / 概念·关系·引文 / 报告 / 问题·结论 / 证据 / 过程 / 稿件 / 发现 ——
而"**一个可能为真、尚未检验的陈述**"（猜想）不在任何一行里。于是每个需要转手猜想的角色，
都只能把它塞进自由文本（`gap_reason` / `notes` / `origin`）。

### 7.1 现状：猜想的"半个词表"已经散落在三处（实测）

| 已有的半边 | 落点 | 逐字说明 |
|---|---|---|
| `supported_not_proved` | `schema.SUBGOAL_STATUSES`、`ATTACK_STATUSES`；产出点 `agent_f.py:911-921`、`:1101-1105`、`:1134`、`:1142` | F 的 docstring 逐字：「E 返回 `evidence_kind="cross_check"` 时子目标最多标 `supported_not_proved`」⇒ 这个词**只活在"攻坚子目标"上** |
| `overclaim` / `scope_drift` | `schema.py` 审校码表：`overclaim` =「把 cross_check 写成 proved」；`scope_drift` =「把假设当公理、结论范围被放大」 | H 的判据**已经预见到猜想被误用的两种形态**，只是没有"猜想"这个对象可指 |
| `cross_check` / `heuristic` / `disproved` | `EVIDENCE_KINDS` / `NEGATION_KINDS` | E 能表达"支持但不证明"与"被反例否证" |

| 缺的载体 | 实测 | 后果 |
|---|---|---|
| `research_questions` | `QUESTION_KINDS = ("gap","contradiction")`；`research_tools.LEGAL_TRANSITIONS`（`:509-511`）= open→{needs_evidence,researching,dropped} / needs_evidence→{researching,dropped} / researching→{needs_evidence,answered,dropped} | 猜想无处登记、也没有通向"有支持 / 被否证"的迁移 |
| `relations` | `RELATION_STATUS = ("active","suspect","rejected")`，且入 relations 必须带逐字 quote（B 的回验闸门） | 猜想**进不去**（它没有引文，这是对的；但因此它也没有别的地方可去） |
| 稿件断言 | `Document.validate` 要求 `citations` + `evidence_kind` | 猜想**写不进稿件** |
| 检索面 | 没有"这个猜想是不是已知结果"的请求类型 | A 无法替猜想做已知性排查 |

### 7.2 逐角色的接触面（"不止 D 和 E"的具体形态）

| 角色 | 与猜想的接触面 | 现状 |
|---|---|---|
| **A** | **已知性排查**：这个猜想有没有人做过、是不是已证定理 —— 把已知结果当新猜想是最常见的浪费 | ❌ 无请求类型 |
| **B** | 从图里**归纳出猜想**（"所有已入库例子都成立"）；以及"猜想 ≠ 知识关系"的分离 | ❌ 无 |
| **C** | 猜想的**主要产地**：结构类比、共现模式、"这个模式在已枚举范围内都成立" | ❌ C 只产 gaps / contradictions / duplicates |
| **D** | **登记猜想 + 给出可检验形式**，与 gap / 矛盾并列为第三类问题 | ❌ `kind` 两项装不下 |
| **E** | 检验猜想（`for_question_id` 字段**已存在**）并给 `supports/refutes/inconclusive` + `evidence_kind` | ⚠️ 链路字段齐了，被检验的对象不存在 |
| **F** | 子目标 = "证明或否证这个猜想"；`supported_not_proved` 本来就是为它造的 | ⚠️ 词有、对象没有（子目标与猜想无键关联） |
| **G** | 猜想必须以**独立一节 + disclaimer** 出现（今天的断言模板让它无处可写） | ❌ 无 |
| **H** | ① 猜想被写成结论（`overclaim`）② 猜想被当公理推出结论（`scope_drift`）③ 已被证否的猜想还留在稿里 | ⚠️ 码有、对象没有 |
| **M** | "检验一个猜想"必须是一个**可计量的预算单元**；猜想→检验→状态变更要可审计 | ❌ 无 |

### 7.3 缺它的代价（一句话可核）

E 的 `supports` **落不到任何一处**：落 `answered` 是过度声称（FC-22 明禁）、
落 `researching` 是把"有支持"说成"还在查"、落 `needs_evidence` 是把"检验过"说成"没证据"
—— **三条都是假陈述**。而 F 那边早已备好正确的落点 `supported_not_proved`，
它却只认得"子目标"不认得"猜想"。所以今天的 D↔E 只能做"给已入库断言跑一遍检查"，
做不了研究 —— 这就是"摆设"的准确机制。

### 7.4 载体形态：Shape B 当场撞坏一条不变量 ⇒ 推荐 Shape C（独立对象）

#### Shape B（把猜想当成 `research_questions` 的一个 `kind`）—— **不成立**，两条硬伤

1. **撞 schema 不变量**（`schema.py:604-609` 逐字）：
   `status="needs_evidence"` 时**必须**有非空 `waiting_request_ids`，理由原话是
   「否则无法判断『新到的文献是不是我正在等的那批』，D 的循环就接不上」。
   而猜想等的是**实验**，不是检索请求 ⇒ 要么编一个假的等待集（说谎），
   要么放弃 `needs_evidence`（"提不出可检验形式"就没有落点）。
2. **命题 ≠ 问题**：问题由**查明**了结（检索/分析/问 A），猜想由**证明或否证**了结
   （形式化检查器 / 反例）。两者的迁移表、消费者（`research_tools.LEGAL_TRANSITIONS`）、
   字段都不同；`answered` 一旦被两类共用，同一个词会同时意味着"查明了"与"证明了"
   —— 正是本仓反复禁止的"同一个词两种含义"。

#### Shape C（独立对象 `conjectures`）—— 推荐

理由不是洁癖，全都有实测出处：

| 理由 | 证据 |
|---|---|
| 命题需要自己的字段 | 需要 `statement`（必须可判真假）、`testable`（params/范围）、`negation_statement`、`proof_experiment_id`、`counterexample_experiment_id`、`promoted_to`；`research_questions` 装不下，而它的 `gap_reason` / `waiting_request_ids` 对猜想无意义 |
| 频繁增删要窄写集 | 猜想是**高频、可删**的对象；写集只有 `{"conjectures"}` ⇒ 不会与 `literature`/`relations` 的知识写入互相串行（`WRITE_SETS` 是并发判据）。塞进 `research_questions` 会让猜想的高频改动与 D 的循环共用一张表、共享加锁顺序 |
| 升格需要双向链接 | 猜想 → 定理/引理需要 `promoted_to`；被证明物需要能反查"它来自哪个猜想" |
| 前提引用需要新来源 | `Dependency` 只有 `source_lit_id` / `source_experiment_id` ⇒ H 的 `scope_drift`（把假设当公理）**今天无法执行**，因为查不到"这条结论建立在一个猜想上" |

**Shape C 的字段草案**（编号沿用本仓风格，落地时按 `schema.py` 惯例写）：

```text
Conjecture:
  conjecture_id            # 单调分配，永不复用（store.alloc_id）
  statement                # 命题本体：必须是可判真假的陈述句（判据：非空 + 不含疑问词）
  negation_statement       # 否命题（可空；给"否证"一个明确对象）
  form                     # 受控词表：universal / existential / identity / bound / structural
  testable                 # {"params": {...}, "bounds": {...}, "why": "..."}；空 ⇒ 只能落 needs_evidence
  origin                   # 必填：从哪来（report_id / 关系 id 列表 / gap / 检索结论）
  status                   # 见 §7.5
  experiment_ids           # 检验过它的实验（E 写）
  proof_experiment_id      # 仅 method=formal 且 evidence_kind=proof
  counterexample_experiment_id
  promoted_to              # {"kind": "document_claim", "id": "..."}
  known_lit_id             # A 的已知性排查命中文献（"别人已经证过"这条出路）
  withdraw_reason          # 撤下/放弃的理由（不许静默消失）
  created_at / updated_at / created_by
```

**升格的两跳（第二跳是我先前漏掉的）**：

1. **第一跳：进稿件断言**。新证出来的定理先落到 **G 的稿件断言**（`evidence_kind="proof"`
   + `verifier_output` 非空，FC-22），并配一条 `Dependency`（`source_experiment_id=<proof 实验>`，
   `status="closed"`）。"定理 / 引理"在本框架里是**排版标签**，不是新的证据等级 ——
   证据阶梯只有 `proof / cross_check / heuristic` 三级，另立一级就是第二份判据。
2. **第二跳：经 H 审定为 `accepted` 后，稿件自己成为可引来源**。
   （**更正**：我此前写"新定理进不了 relations、所以升格只能停在稿件断言"——
   那只在"外部文献是唯一可引来源"时成立。**只要稿件过了审，它自己就是来源**：
   `citations` 里出现 `doc:<doc_id>#<claim_id>@<revision_hash>`，
   后续断言就可以像引文献一样引它，B 也可以从我们自己的稿件里抽关系
   （引文取自稿件正文，仍走逐字回验）。这条链的完整设计见 **§8**。）
   由此"猜想 → 证明 → 定理 → 被后人引用"才形成闭环，而不是沉在一份稿子里。

### 7.5 状态机六态（与 F 对齐；同一个词不许造第二份定义）

| 状态 | 含义 | 允许的证据 | 禁止的读法 |
|---|---|---|---|
| `open`（提出） | 刚登记，未检验 | 无 | 不得进稿件正文（只许进"待检验"节） |
| `needs_evidence` | 提不出可检验形式 / 缺脚本 | 无 | **≠**"检验过、没结论" |
| `researching`（检验中） | E 在跑 | 未定 | **≠**"有支持" |
| `supported_not_proved` | 有 `cross_check` / `heuristic` 支持 | `experiment_id` 列表 | **绝不许**写成"成立 / 已证明" |
| `refuted` | 有反例（`result="refutes"` + `counterexample`） | `experiment_id` + 反例可复现物 | **≠**`inconclusive` |
| `answered`（= 已证明） | **仅** `method="formal"` + `evidence_kind="proof"` | `verifier_output` | — |
| `dropped` | 放弃 + 理由 | — | 不许静默消失 |

### 7.6 跨角色接线清单（9 个点，编号 `J-*`）

| ID | 角色 | 判断点 | 允许的 LLM 动作 | 输出契约 | 禁止 | 负控 |
|---|---|---|---|---|---|---|
| `J-A1` | A | 已知性排查 | 生成"是不是已知定理"的检索式 | 复用 `L-A1` 的缝，请求类型标 `intent="known_check"` | 把"没搜到"说成"这是新结果" | 注入"零命中"⇒ 必须落 `unknown`，**不许**输出"未见文献报道"这种结论式措辞 |
| `J-B1` | B | 归纳猜想 / 猜想≠关系 | 产出猜想候选 + 支撑它的已有关系 id 列表 | 猜想候选落 `research_questions(kind="conjecture")` 的候选文件；**绝不写 relations** | 把猜想写进 `relations`（它没有逐字引文） | 注入一条无引文的"关系"⇒ 必须被 quote 回验拦下 |
| `J-C1` | C | 猜想候选（模式 / 类比） | 猜想候选 + 图里的结构证据 | 只提候选（C 的边是空的） | 直接建问题；把"没枚举完"说成"普遍成立" | 注入"枚举被截断却称普遍成立"⇒ 必须带 `truncated` 读数并降级为候选 |
| `J-D1` | D | 登记猜想 + 可检验形式 | 陈述句 + `testable`（params/范围）+ provenance | `research_questions(kind="conjecture")`，`origin` 必填 | 无可检验形式却标 `open` | 注入"没有 testable 的猜想"⇒ 必须落 `needs_evidence`（不许当可检验猜想排期） |
| `J-E1` | E | 检验计划 | 从猜想生成脚本 | `run_experiment(..., for_question_id=<猜想号>)`；判据仍归 E 的机械层 | 判定 `evidence_kind` / 把 `supports` 说成 proof | 注入"脚本自报 proof"⇒ 必须降级 `cross_check`（`:91-92` 原文） |
| `J-F1` | F | 子目标挂猜想键 | 建议 `owner=E` 的子目标带猜想号 | 子目标与猜想用同一 `question_id` 关联；`supported_not_proved` 语义不变 | 无 `proof_experiment_ids` 却 `closed` | 注入"只有 cross_check 就 closed"⇒ 必须拒（`:51-58`） |
| `J-G1` | G | 猜想节 + disclaimer | 该节行文 | 稿件新增"猜想与待检验"一节；每条带 `testable` 与检验状态；disclaimer 由**代码**填（与 `CROSS_CHECK_DISCLAIMER` 同族，H 精确匹配） | 把猜想写进正常断言流（那会被 `validate` 拒，或被 H 判 `overclaim`） | 注入"猜想写成结论"⇒ H 必须报 `overclaim` |
| `J-H1` | H | 三条猜想判据 | 判定 + **必填证据** | `overclaim`（猜想当结论）/ `scope_drift`（猜想当公理）/**`stale_conjecture`**（已被证否却仍在稿里） | 只写"这里有问题" | 注入一条已 `refuted` 的猜想仍在稿中⇒ 必须报 `stale_conjecture`（第三个码要新登记） |
| `J-M1` | M | 预算与审计 | ——（主控不产知识） | "检验一个猜想"落一行可计量的账（scope 走 `tokenmeter`），并保证 `猜想→检验→状态` 可重放 | 让检验脱离预算；状态变更不落账 | 注入"状态变了但没落账"⇒ 审计判据必须红 |
| `J-G2` | G | **译文忠实性**（跨语言，见 §9.7.5） | 判定 + **必填证据**（主语言行号 + 译文行号 + 一句差异说明） | 落 `renditions`（claim 级）并进 `review_findings` 的证据字段 | 只写"翻译得不错"；无双语对照就下结论 | 注入一条无双语对照的"译文没问题"⇒ 必须按"证据必填"**拒收** |

### 7.7 判据与负控（五条，缺一不许合）

1. **正控**：一条有 `cross_check` 支持的猜想 ⇒ 状态 `supported_not_proved`，稿件里带 disclaimer；
2. **负控**：把 `supports` 写成 `answered` ⇒ 不变量必须拒（无 proof 实验）；
3. **负控**：`refutes` 却不更新猜想状态 ⇒ I11 闭环判据必须红（今天只生成 high 问题，闭环缺一半）；
4. **负控**：猜想无 provenance / 无可检验形式 ⇒ 拒收，**不许**静默降级成普通 `gap` 问题；
5. **负控**：猜想直接进 `relations` 或稿件断言（无引文）⇒ schema 必须拒。

### 7.8 增删与升格语义（"会频繁增删 + 可能升为定理/引理"的直接落地）

#### 7.8.1 增删

| 要求 | 落地形态 | 判据 / 负控 |
|---|---|---|
| **高频新增** | 写集只有 `{"conjectures"}`；一次事务可写多条（批写），避免 N 次往返 | 并发判据：猜想批量写入**不得**与 `literature`/`relations` 的写入互相串行（`WRITE_SETS` 相交才串行） |
| **可删** | **软删**：`status="withdrawn"` + `withdraw_reason` 必填（与 `dropped` 必须写 `notes` 同族，`schema.py:610-611`）；id 单调分配、**永不复用** | 负控：`withdrawn` 而无理由 ⇒ schema 必须拒 |
| **删有引用者** | 被 `dependencies`（作为前提）或稿件断言引用的猜想 **不得硬删**；只许撤下并让依赖方显式改状态 | 负控：撤下一条被引用的猜想而不动依赖 ⇒ `verify` 必须报 `dangling_dep` |
| **可重放** | 每次增删落 `events.jsonl`；N 次增删后 `rebuild` 必须得到一致快照 | 判据：做 100 次"增—删—改"后 `rebuild` 与快照逐字节一致 |

#### 7.8.2 升格（猜想 → 定理 / 引理）

```text
猜想 proposed → testing →（supports）supported_not_proved
                        →（refutes）refuted            ← 反例可复现物必存
                        →（formal proof）proved → promoted  ← 升格，落稿件断言
                        →（A 查到别人证过）known_in_literature
                        → withdrawn（撤下 + 理由）
```

五条判据，缺一不许合：

1. `proved` **仅当** `proof_experiment_id` 指向的实验 `method="formal"` 且
   `evidence_kind="proof"` 且 `verifier_output` 非空（与 FC-22 同族：计算类永远拿不到 proof）；
2. `promoted` **仅当**已有一条稿件断言 `evidence_kind="proof"` 引用它，
   且存在 `Dependency(source_experiment_id=<proof 实验>, status="closed")`；
   猜想行写 `promoted_to`，使"这个定理来自哪个猜想"可反查；
3. `refuted` **仅当**有 `counterexample`（`result="refutes"`）——
   `inconclusive` **不得**转 `refuted`（三态：没查成 ≠ 查过了、被否证）；
4. `known_in_literature` 只由 **A 的已知性排查**（`J-A1`）产生，且必须带文献 id
   —— "别人证过"与"我们证过"是两件事，**合并就是过度声称**；
5. `promoted` 之后，H **不再**报 `overclaim`（它已经不是猜想了），但
   `scope_drift` 仍要能查出"它被当作公理去推别的结论"⇒ 依赖链必须能追到这条断言。

#### 7.8.3 这三件事合起来的最小 schema 面（全部命中 FC-27，需人审 + 2 reviewer）

| 改动 | 位置 | 为什么绕不开 |
|---|---|---|
| 新表 `conjectures` + 受控词表（`CONJECTURE_STATUSES` / `CONJECTURE_FORMS`） | `schema.py` | 状态词表就是磁盘格式契约 |
| `Dependency.source_conjecture_id`（或把来源泛化成 `source_kind`+`source_id`） | `schema.py` | 否则 `scope_drift` 没有数据面，判据无法执行 |
| `experiments.conjecture_id`（可空外键） | `schema.py` | "检验了哪个猜想"必须可查询；也可以只靠 `for_question_id`，但那样猜想与检验的关联是间接的 |
| `store.LOCK_ORDER` 加入新表 | `store.py` | 加锁顺序一旦动过，**所有并发判据都要重测** —— 这是 Shape C 的主要代价 |
| `verify.py` 五条不变量（§7.8.2 的 1–4 + 引用完整性） | `verify.py` | 不变量是"审计能不能信"的判据本体 |

> 诚实交代：§7.4 我原先推荐的 Shape B 是错的，你已经用一个反例（猜想会升为定理/引理）
> 把它顶掉了；Shape C 的代价比 B 大一截（动了加锁顺序），换来的是
> "命题有了自己的生命周期、升格可反查、审校的 `scope_drift` 真的能执行"。
> 若你要求先小步走，可选的中间态是：**先只加表与状态词表、不动 `LOCK_ORDER`**
> （新表不进 `LOCK_ORDER` ⇒ 它不参与跨表事务的加锁顺序，代价是跨表原子性要靠
> 单表事务 + 事件重放来保证）—— 这条中间态需要单独评议，我不擅自选。

### 7.9 代价（必须付，别指望绕）

- **必然命中 FC-27，而且是本轮草案里最重的一处**：新表 + 受控词表（`schema.py`）、
  `Dependency` 的来源字段、`experiments` 的猜想外键、`store.LOCK_ORDER` 加表、
  `verify.py` 五条不变量都在禁改区 ⇒ 必须**人写或人逐行走查 + 2 名 reviewer 批准**。
  上一轮 B 案（evidence 瘦身）我找到了绕开禁改区的路；**这一条绕不开** ——
  它的本质就是改磁盘格式契约里的对象与状态词表。
- **主要代价是加锁顺序**：新表进 `LOCK_ORDER` ⇒ 所有并发判据都要重测
  （写集相交判据、跨表事务的原子性、`rebuild` 可重放）。§7.8.3 末尾给了
  "先不动 `LOCK_ORDER`"的中间态，但它要单独评议。
- **`supported_not_proved` 不许造第二份**：它已在 `SUBGOAL_STATUSES` 与 `ATTACK_STATUSES` 两处
  存在（产出点 `agent_f.py:911-921`），猜想状态加进来是**第三处引用**，必须复用同一常量
  （本仓"两份判据必然漂移"的教训）。
- **稿件侧**：G 的渲染今天强制三张表（证据等级 / 否定分类 / 依赖表），猜想进稿建议成为
  **第四张表**（猜想 + 检验状态 + 是否已升格），H 的三个码（`overclaim` / `scope_drift` /
  `stale_conjecture`）随之登记进受控词表。

## 8. 协作总图：两级引文经济（这就是全部协作逻辑）

### 8.1 一句话

整条流水线在做**一件事**：把**外部文献**变成**内部经审查的稿件**，而审查通过的稿件
又变成**可以继续被引用的来源** —— 引文图从外部向内部生长，每一跳都受同一条纪律约束：
**逐字可核 + 等级如实 + 依赖闭合**。

### 8.2 两个环

| 环 | 路径 | 交接物必须自带什么 |
|---|---|---|
| **外部环（接地）** | A 检索 → B 整理 → C 分析 → D 提问 | 文献行（含落盘路径/查重键）→ 概念/关系（每条带**逐字引文**，过 `quoteverify`）→ 报告（含 `truncated` 读数）→ 问题（含 L1/L2/L3 溯源与 `checked` 三态） |
| **内部环（生产 + 闸门）** | D 猜想/问题 → E 证据 / F 攻坚 → G 成稿 → H 审 → G 改 →（`accepted`）→ **成为可引来源** → 回到 C/D/E/F/G | 猜想（可检验形式）→ 实验（`evidence_kind` 三级）→ 断言（`citations` + `evidence_kind` + disclaimer）→ 审校发现（**带证据行**）→ 定稿（**带修订哈希**） |

两个环在 **D** 交汇：D 既是外部环的出口（把文献里的缺口变成问题），
也是内部环的入口（把问题变成猜想/攻坚计划）。这就是 D 模块最大的原因（228 KB）。

### 8.3 H 是把"内部文本"变成"可引来源"的那道闸 —— 省不掉

- 没有 H，**自引就是循环论证**："我说过"变成"我说过、且被独立复核过（带证据行）"，
  这一步是内部引文能成立的唯一依据；这也是规格里那句"审校记录能不能被信任"的真正分量
  （`ReviewFinding.evidence` 必填非空、H 只读、H 只能请 G 改）。
- H 的**证据锚已经具备**（实测字段）：`ReviewFinding` 的
  `axis / line / verbatim_quote / maths / line_unavailable_reason / evidence / target / level`。
- **前期审稿件、后期审论文，风格不同、码表同一套**：

| 阶段 | `DOC_KINDS` | 必审项（`ReviewFinding.kind` 码表） |
|---|---|---|
| 前期（草稿/便笺/复现报告） | `note` / `reproduction_report` / `survey` | `unsupported_claim`（断言无引用）· `overclaim`（把 `cross_check` 写成 proved）· `dangling_dep`（依赖悬空）· `missing_negation_kind` · `garbled` |
| 后期（论文） | `paper` | 上面全部 **+** 依赖表完整 · `external_unavailable` 的行必须显眼 · 证据三级统计 · **`maths` 轴**（数学表达本身）· 体例与跨语言要求 |

相同点是那句"**对内容严谨性的追求**"：两段都用同一套码 + 必须带证据行，
**没有一处判据是"读起来像不像论文"**。风格差异落在 profile（哪些码必审），
不落在"严不严"。

### 8.4 对称性（这套框架最漂亮的一点，且是实测的）

| 侧 | 谁核 | 怎么核 | 落点 |
|---|---|---|---|
| 外部文本 | B | `quoteverify.check_quote` **逐字回验**，三态 `quote_verified` | 关系行 + `claims` 的 `verified/not_found/unknown` |
| 内部文本 | H | **逐字锚定**：`verbatim_quote` + `line`（找不到行必须写 `line_unavailable_reason`） | `review_findings` |

⇒ 引文图两侧用的是**同一种纪律**："逐字，或者如实标注为什么没逐字"。
这也是为什么"足够好"必须由 H 定义：**B 的尺子量不了我们自己的稿子**。

### 8.5 "足够好"必须可判：三条硬前提（全部命中 FC-27）

| # | 缺什么（实测） | 要加什么 | 判据 |
|---|---|---|---|
| 1 | `Document.claims[].citations` 今天只认 `"rel:0007"` / `"lit:0003#p.4"` / `"exp:0002"`（schema 逐字），**没有 `doc:`** | 内部引用种类 `doc:<doc_id>#<claim_id>@<revision_hash>` | 引用必须能解析到一条**存在的、且仍 `accepted`** 的断言 |
| 2 | `Document` **没有内容哈希**（字段实测：`doc_id/kind/title/markdown_path/sections/claims/open_problems/status/review_rounds/created_at/updated_at/created_by`）⇒ 审批是"对某一版"的，却钉不住是哪一版 | `revision` + `content_sha256` | **可引 ⇔ `status="accepted"` ∧ 引用钉的哈希 == 该断言当前哈希**；G 改稿后旧审批**自动失效**。否则"审批过的版本"与"被引用的版本"静默分家（与"派生态被当输入"同族的静默失效） |
| 3 | `Dependency` 只有 `source_lit_id` / `source_experiment_id` | `source_doc_id` + `source_claim_id`（或把来源泛化成 `source_kind`+`source_id`） | `verify` 的 `dangling_dep` 扩到"被引内部断言是否存在、是否仍 `accepted`、修订哈希是否对得上" |

### 8.6 这条一旦成立，§7 的升格闭环就完整了

```text
猜想 ──(E: formal + proof)──▶ 稿件断言 ──(H: accepted@revision_hash)──▶ 可引来源
   ▲                                                                      │
   └────────── 后续断言以 doc: 引用它；promoted_to 可反查来自哪个猜想 ◀──────┘
```

顺带把两条本文档前面的判断也串起来：`scope_drift`（把假设当公理）能执行了
（前提链可查）；`stale_conjecture`（已证否的猜想仍在稿里）也有数据面了。

### 8.7 这条链还缺的"审核面"（H 的前后期 profile 落地）

1. 需要一张 **`REVIEW_PROFILES[kind]`** 受控表（今天没有）：每个 `DOC_KINDS` 值对应
   "必审码集合"与"必填证据形态"（前期松、后期全）；
2. `status` 迁移与 profile 绑定：`draft → in_review → (revised → in_review)*
   → accepted | unresolved_review`（`DOC_STATUSES` 已有这些值，缺的是"谁能推进"的闸门）；
3. 判据：`accepted` **仅当**该 profile 的必审码全部 `fixed`（error 全清），
   且与 I8 的 `max_review_rounds` 上限配合 —— 超限标 `unresolved_review` 并**列出未解决项**。

### 8.8 "稿件审批通过"怎么签名（签名了就是正式文本）

§8.5 的三条是"可引"的**技术前提**；这一条是"**正式**"的**判据本体**。
范式不用新造：本仓已有一台签名机（`.noai-approvals.json` + `scripts/noai_gate.py`），
实测形状如下，照搬到稿件上即可。

#### 8.8.1 现有的签名机（实测，可复核）

| 部件 | 实测形状 |
|---|---|
| 台账条目字段 | `path / glob / category / sha256 / authored / authored_basis / change_note / changed_this_session / also_hits / audits / reviewers` |
| 单条签名 | `{name, at, scope, verdict, note, evidence_path, evidence_sha256}` |
| 门槛常量 | `REQUIRED_APPROVALS_ON_HIT = 2` · `MIN_INDEPENDENT_AUDITORS = 2` · `MIN_DISTINCT_DIMENSIONS = 3` |
| 关键理由码 | `ledger_self_approval`（AI 把自己的改动写进台账声称已批准）· `unregistered`（**登记 ≠ 批准**）· `stale`（哈希变了）· `insufficient_reviewers` · `insufficient_independent_dimensions` · `reviewer_evidence_anchor_unverifiable` · `hash_unavailable` |
| 台账现状 | 23 条目 / **22 条有签名**；无 `reviewers` 的那条正是"只登记未批准"，与 `--baseline` 永不写 `reviewers` 一致 |

#### 8.8.2 搬到稿件上：签名对象与签名记录

- **签名对象是"某一个修订版"**：`doc_id + content_sha256`（§8.5 第 2 条），
  可选 `claims_hash` 以支持**单条断言级**签名（与 `lit:#p.4` / `exp:0002` 同粒度）。
- **签名记录**（新台账，形如 `DOC-SIGNATURES.jsonl`，append-only）：

```text
{doc_id, content_sha256, claims_hash?
 name, at, scope, verdict, note          # 与 .noai-approvals.json 的签名同字段语义
 instance_id                             # 签名的**那一次审核运行**（不是"agent-H"这个角色名）
 model, prompt_version, temperature      # 可复现性：这次判读是用什么做的
 inputs: {doc_sha256, evidence_hashes}   # 它读到的输入是什么（防"审的是另一版"）
 evidence_path, evidence_sha256          # H 的 review_findings 文件 + 其哈希（证据锚，非空）
 basis: {codes_checked: [...], finding_ids: [...], rounds: N, dimensions: [...]}
 prev_hash}                              # 链式，防事后插入/删除
```

签名者写 **`name: "agent-H"` + `instance_id`**：角色名说明"谁有资格签"，
`instance_id` 说明"是哪一次审"。为什么两个都要：只有角色名，同一角色写两条虚签名就能充当
"两次独立复核"；只有 instance_id，判据就没法强制"必须由审核角色签"。
`inputs` 三个哈希是 AI 签名特有的一条 —— H 是 LLM，**它审的是它读到的那一版**；
不钉住输入，就等于允许"用 A 版的审阅结论给 B 版签名"。

#### 8.8.3 分级：**Lean 形式化通过 ⇒ 毫不犹豫签**

| 稿件里的断言 | 审查面 | 签几条 |
|---|---|---|
| **全部 `proof` 级**（`method="formal"` + `evidence_kind="proof"` + `verifier_output` 非空 + 公理审计过） | **机械可判**：证据是外部检查器的输出，不是 H 的意见 ⇒ H 只做形式复核（码表跑一遍：无 `unsupported_claim` / `dangling_dep` / `missing_negation_kind`） | H **签一条，毫不犹豫** |
| 含 `cross_check` / `heuristic` | H 的正常审核：那些断言必须带 disclaimer、等级如实、不得写成"证明了" | H 签一条 |
| 含 `external_unavailable` 依赖 | H 给 `warning`（**已知边界，不是谎报**），依赖表里显眼 | 同上 |
| 出现 error 级发现 | 不许签，退回 G 改（I8）；超 `max_review_rounds` 标 `unresolved_review` 并**列出未解决项** | 不签 |

关键判断：**当证据是外部检查器给的，签字就是抄写，不是判断** —— 这就是"毫不犹豫"的含义；
而当证据只是数值/启发式时，"毫不犹豫"恰恰是最危险的动作（FC-22 的全部由来）。

**唯一保留的机械前置**（既有机制，不是新增）：Lean "通过"必须同时过**公理审计** ——
`formalgw.py` 已经拦"假设结论再宣布结论"（`axiom e_ax : P` + `theorem bad : P := e_ax`）
与 `FORBIDDEN_AXIOMS`；没有这一条，"Lean 通过了"可能是空转。

#### 8.8.4 判据（落 `verify.py`，最小形态）

```text
signed(doc) ⇔ 存在一条签名 s，满足：
    s.name == "agent-H"                        # 审核角色签，不是作者签
    s.content_sha256 == doc.content_sha256     # 签的是这一版
    s.inputs.doc_sha256 == doc.content_sha256  # 它审的就是这一版
    s.evidence_path 可解析且哈希相符            # 证据锚（H 的 review_findings 文件）
    s.verdict == "accepted"
formal(doc) ⇔ signed(doc) ∧ Document.status == "accepted"
```

**我原先写的下面这些砍掉了**（属于小题大做）：`N(internal)=1 / N(outbound)=2` 的对外加档、
"两条签名必须覆盖不同维度"、"对外成果再加一道人工加签"。理由：**证据等级已经在做那件事**。
一份全 `proof` 级的稿子，第二道眼睛看不出新东西；真正需要第二道眼睛的是
"数值支持被写成已证明"，而那件事由 FC-22 的 schema 硬约束 + H 的 `overclaim` 码 +
强制 disclaimer 来管，**不靠签名数量**。签名数量与维度覆盖留着，只会变成一个所有人都照抄的空仪式。

保留一项：`instance_id` 仍要写（审计"是哪一次审"），但只作**留痕**，不作门槛。

#### 8.8.5 H 凭什么能签（四条结构性事实，全是现有性质）

| # | 结构性事实 | 落点 |
|---|---|---|
| 1 | **H ≠ G**：H 的工具面 0 个写工具，只能写 `review_findings` 与 `documents.status`（经钉死的 writers 注册表）；改稿只能请 G 改 | `tools.review_tools` writers 注册表 + `schema.H` 装配期断言 |
| 2 | **H 的判定必须带证据锚**：`ReviewFinding.evidence` 必填非空，且带 `verbatim_quote` / `line`（找不到行必须写 `line_unavailable_reason`） | `ReviewFinding` 实测字段 |
| 3 | **签的是"这一版"**：签名钉 `content_sha256` 与 `inputs.doc_sha256`，改一字节即 `stale` | §8.8.4 |
| 4 | **H 也会错**（本项目原始教训：上一阶段评审方提的一条"缺陷"是错的，是实现方拿证据顶回来的） | ⇒ 所以签字的前提是**证据在外部可复核**（Lean 输出 / 引文逐字 / 存在性核对）；这正是把"`proof` 级"单列出来、且不含糊其辞的原因 |

#### 8.8.6 改一字节即失效（保留 —— 它防的是静默分家，不是仪式）

G 改稿 ⇒ `content_sha256` 变 ⇒ 旧签名转 `stale`（**append-only 留痕，不删**），
文档退回 `revised`；下游以 `doc:` 引用它的断言，`verify` 必须报
`stale_signature` / `dangling_dep` —— **不许静默沿用旧审批**。
这一条与"足够好"无关，它挡的是"审批过的版本"与"被引用的版本"悄悄变成两版。

#### 8.8.7 载体与"不做第二份判据"

抽一个共用实现（哈希一致 / append-only 链 / 禁自批），
**`noai_gate` 的台账与稿件签名台账各用各的文件、共用同一套实现与常量**。
一个台账混两类对象（代码路径 vs 文本修订）会让 `--check-ledger` 的语义立刻含糊；
而写两份实现就是本仓反复禁止的"第二份判据必然漂移"。

#### 8.8.8 负控（四条，只留真会咬的）

| # | 负控（注入） | 期望 |
|---|---|---|
| 1 | `proof` 级却缺 `verifier_output` / `code_hash` | 拒（不许"形式上写了 proof"） |
| 2 | Lean 通过但命中 `FORBIDDEN_AXIOMS`（假设结论再宣布结论） | 拒（`formalgw.py` 既有机制） |
| 3 | 签名者不是 H（G 自签 / `name == last_revised_by` / 缺 `name`） | 拒：`signer_not_reviewer` |
| 4 | 改一字节后旧签名仍被下游引用 | 旧签名 `stale` + 报 `stale_signature`（不许静默沿用） |

## 9. 我自己补的缺口（你没提，但通读后发现必须写清）

### 9.1 跨层等级对照表（唯一权威；防"每层各造一份词表"）

代码里同一件事有五个说法，今天散在五行词表里。**这张表必须只定义一次**
（`schema.py`），其它层引用；本仓的教训是"两份判据必然漂移"：

| 事实 | 猜想状态（新） | 子目标状态 | 实验 `result` / `negation_kind` | 稿件 `evidence_kind` | 引文回验 `verdict` |
|---|---|---|---|---|---|
| 形式化证明（含公理审计） | `proved` → `promoted` | `closed` | `supports` / `not_proved`→证毕 | `proof` | `verified`（引检查器输出） |
| 数值/穷举/符号支持 | `supported_not_proved` | `supported_not_proved` | `supports` / `not_proved` | `cross_check` / `heuristic` | `verified`（**只到 cross_check**） |
| 找到反例 | `refuted` | `blocked` | `refutes` / `disproved` | —（否定型断言 + `negation_kind`） | `verified` |
| 检验过、没结论 | 回 `testing` | `in_progress` | `inconclusive` / `no_local_evidence` | — | `unknown`（**不是 `not_found`**） |
| 文献里已有人证过 | `known_in_literature` | `closed`（带文献引用） | — | `proof`（引文献，不引自己） | `verified` + `level=fulltext` |
| 提不出可检验形式 | `needs_evidence` | `todo` | — | — | — |

两条硬纪律写进判据：**"没查成"（`inconclusive`/`no_local_evidence`/`unknown`）绝不许映射到
`refuted`/`disproved`/`not_found`**；**"数值支持"绝不许映射到 `proof`/`closed`/`proved`**。

### 9.2 契约影响矩阵（I1–I12 要改哪些 + 新增 I13–I15）

| 契约 | 影响 | 动作 |
|---|---|---|
| I9 F↔E 子目标外包 | 子目标要能指向被检验的猜想 | 子目标新增 `conjecture_id`；负控：只有 `cross_check` 的子目标不得 `closed`（现成） |
| I11 E→D 反例回流 | 今天**只建一条 high 问题**，不更新被否证的对象 | 扩展：`refutes` ⇒ 猜想转 `refuted` + 存反例可复现物；`inconclusive` 不得触发回流（现成） |
| I12 G→verify 依赖闭合 | 依赖来源多一类 | 扩到 `doc:`：检查"被引断言存在 ∧ 仍 `accepted` ∧ 哈希相符" |
| **I13（新）猜想生命周期** | 提出→检验→（支持｜否证｜证明）→升格/撤下 | 负控 = §7.7 的五条 |
| **I14（新）内部引文与签名失效传播** | 改稿 ⇒ 签名 `stale` ⇒ 下游 `dangling_dep` | 负控 = §8.8.8 第 4 条 |
| **I15（新）审核覆盖闭环** | H 的 `claims_reviewed/claims_total` 必须与 G 的断言数对得上 | 负控 = §9.3 |

`interactions.py` 是 FC-27 ⇒ 这批改动要人审，且 **`CONTRACT_VERSION` 要前进一格**；
所有读它做兼容判断的地方必须一起改（否则新旧契约会被同时当成有效）。

### 9.3 审核覆盖率必须显式（今天看不出来 H 到底审了多少）

`ReviewFinding` 只有"发现"，**没有"我审了哪些"** ⇒ 一份稿子 10 条断言只审了 3 条，
产物里读不出来，而读者会把它读成"审过了、没问题"。加：

```text
coverage: {claims_total, claims_reviewed, sections_reviewed, truncated, why}
```

判据（与 `truncated` 同族）：**`accepted` 要求 `claims_reviewed == claims_total`**；
若 `truncated` 为真，只许停在 `in_review` 并写明"已审 N/M + 为什么"。
这是本仓最深那条教训的同类形态：**"没做"绝不许折成"做了、没事"**。

### 9.4 数学正确性的唯一提升通路（把"H 不判数学"写精确）

H 不判数学**推理**；但 H **必须**核"这条断言声称的等级与它挂的证据是否相符"。
数学正确性只能由三类**外部**证据提升：**形式化检查器输出 / 文献逐字引文 / 反例**。
**任何人（含 H、含任何 LLM）不得以"我读了觉得对"提升等级** —— 这条要落成判据：
负控注入一条"读起来对但无任何证据"的断言却标 `proof` ⇒ 必须 `overclaim`。

### 9.5 猜想的查重与"同一命题多来源"

建猜想前必须对 `relations` / `concepts` / 既有猜想查重（复用 `interactions.check_conflict`
这个**纯函数**，别再写一份）。命中时**不合并**，登记为"同一命题的两个来源"：

- 文献来源（B 的 `rel:` + 逐字引文）与猜想来源（我们自己的检验链）各留各的；
- 猜想被我们证明后，`known_in_literature` 与 `promoted` 可以**并存**（别人证过 + 我们也证过），
  但稿件必须**分开引**（不然就把"别人的功"写成"我们的功"）。
- 稳定键：`statement_norm_hash`（归一化后哈希），归一化规则必须与判重层**同源**（不许第二份归一化）。

### 9.6 证据失效与传播（"证明也会过期"必须是机制）

Lean/Coq 版本变化、`FORBIDDEN_AXIOMS` 名单变化、检查器缺陷、脚本依赖漂移 ⇒
已签发的 `proof` 证据可能失效。因此实验行要记 `checker_name/version` + `code_hash`
（`verify.code_hash` 已有）+ 运行时刻；一旦重跑失败或公理审计失败：

```text
实验 → invalidated ⇒ 挂在它上的猜想：promoted → supported_not_proved（或 needs_evidence）
                  ⇒ 稿件对应断言 → dangling_dep
                  ⇒ H 的签名 → stale，重新审
```

**撤销必须能传播**；否则"曾经证明过"会永久躺在库里，而它已经不成立了。

### 9.7 跨语言：稿件语言**由用户设置**，译文锚跟着语言走

#### 9.7.1 先分清两件事（不许混成一条）

| | 是什么 | 谁管 | 现状 |
|---|---|---|---|
| **检索跨语言** | 中文题面 vs 英文书架（"同调代数"查不到英文书） | A/B 的检索口径 | 已知残差（`R-26`），**本节不解决** |
| **稿件语言** | 我们写出来的东西用哪种语言；以及"同一句话的两个语言版本" | G 撰写 / H 审校 / 引用语法 | 本节解决 |

#### 9.7.2 设置面（三层，**单一来源**，与 `config.yaml` 既有风格一致）

`config.yaml` 今天有七块（`store / lease / agent_a / agent_b / download / search / context_budget`），
`document.language` 按同一风格加为**第八块**；`config.yaml` **不在 FC-27**（实测 `.noai-paths` 0 命中），
所以这一层可以自由改。优先级**从低到高**：

```yaml
# config.yaml —— 新增块（示例；实现时必须与"读它的地方"同批落地，
# 否则就是本仓点名过的"加了配置项但没接线"，见 contextbudget.py:137）
document:
  # 稿件默认语言：zh（中文）/ en（英文）。报告与提示词是中文，故默认 zh。
  language: zh
  # paper 类**必须显式设定**：投出去的东西用什么语言是真决定，不许吃默认值。
  require_explicit_for: [paper]
  # 术语一致性检查用的译名表落点（见 9.7.4）
  glossary: glossary.yaml
```

| 层 | 形态 | 先例 |
|---|---|---|
| ① 项目默认 | `<project>/config.yaml` 的 `document.language` | 现有七块同款 |
| ② 环境变量 | `AGENTFLOW_DOC_LANG`（覆盖 ①） | `AGENTFLOW_PROJECTS_DIR`（`projects.py`）、`ABFLOW_OPENALEX_MAILTO` 已有同款 |
| ③ 运行级 | `agentflow project run --lang en` / `agentflow run --lang en` | `--lean` / `--fulltext` / `--config` 同款 |
| ④ 文档级 | `Document.language`（FC-27 新字段） | 与 `kind` / `status` 同级 |

**记录落点（三处都要，缺一处就有读者会读错）**：
`run-manifest.json` 增 `language`（与 `prompt_version` 同级）· `Document.language` ·
`report.md` 顶部显示"本次稿件语言 = zh/en（来源：项目默认 / 环境变量 / `--lang` / 文档显式）"。

**"无静默默认"纪律**：内部稿件（`note` / `survey` / `reproduction_report`）可以继承 ①；
**`paper` 必须显式**（`document.require_explicit_for`），未显式 ⇒ 拒绝出稿并把理由写进 `not_wired`——
理由与 `policy.Policy` 的四道上限同族：`None` 会让"我忘了设"与"我决定不限"长得一样。

#### 9.7.3 译文锚（claim 级；这才是"逐字"能成立的前提）

- `Document.claims[]` 增 `renditions: {lang: {"text": ..., "text_sha256": ...}}`，
  主语言由 `Document.language` 指定；**主语言那一份就是 `text` 本身**，不重复存。
- **引用语法必须带语言**：`doc:<doc_id>#<claim_id>@<revision_hash>#<lang>`。
  不带语言就等于允许"H 审的是中文版、论文里引的是英文版"静默分家。
- **改译文算改稿**：`renditions[lang].text_sha256` 变 ⇒ `content_sha256` 变 ⇒ 签名 `stale`。
- 逐字回验（`quoteverify`）作用在**该语言的文本**上：引哪一版就用哪一版的语言比对；
  跨语言时**不许**拿中文断言去英文文本里搜（那必然 `not_found`，而原因是"语言不同"，
  不是"引文不存在"——三态：这属于**没查成**，不是**查过了没有**）。

#### 9.7.4 术语一致性（可机械判定的那半边，先做）

`Concept` 今天只有 `name / normalized_name / aliases`，**没有语言维度**（实测字段）。
⇒ 增 **`glossary.yaml`**（`concept_id → {zh: 术语, en: term}`）并加一条**可机械判定的判据**：

```text
同一稿件内，同一 concept_id 只许出现一种译名（按 language 取 glossary）
唯一例外：首次出现可写 "中文（English）" —— 例外必须由 glossary 显式登记为 allow_bilingual
```

这条比"翻译得忠实"可靠得多（后者是语义判断，见下），而且它今天就能写判据。

#### 9.7.5 H 的两件事：profile 按语言选，"忠实性"归 LLM 点

- **profile 按语言选**：`Document.language=zh` 走中文体例；`=en` 走英文学术体例
  （与 §8.3 的"前期稿件 / 后期论文"两个 profile 交叉，共 2×2 档）。
- **"译文是否忠实"是语义判断 ⇒ 归 LLM 点**（新增 `J-G2`：双语对照 + **必填证据**
  = 主语言行号 + 译文行号 + 一句差异说明）。**不许**只写"翻译得不错"；
  H 若给不出双语对照，就按 `review_findings` 的"证据必填"拒收。
- **本仓自己那条待决问题就此了结**：`llm.py:327-329` 逐字写着
  「§9 待决问题 1（description 用中文还是英文）**尚无定论**，基线里任何'自作的转写'
  都会变成需要审计的额外假设」⇒ 现在它有答案了：**由 `document.language` 决定**，
  且抽取侧（B）仍坚持"用原句、不转写"（转写会变成需审计的假设），
  转写只发生在**稿件侧**（G），并且必须落 `renditions` + 哈希。

### 9.8 图/溯源工具必须标出猜想（否则猜想静默读成知识）

`graph.build/neighbors/relations_between/stats` 与 `trace.*` 的输出今天只有"关系/概念"；
猜想若并进去，读者会当成知识。要求：这些工具对每条相关项带 `kind` + `status`
（含 `conjecture`），并且 **C 的报告与 G 的稿件各加第四张表**（猜想清单 + 检验状态 + 是否升格）。

### 9.9 预算、缓存与降级

- 每个 LLM 点必须有**确定性回退**（=当前实现），且降级要留痕 `llm_skipped_budget`
  （**不许静默继续**，与 `not_wired` 同族）；
- 同一（输入哈希 + prompt 版本 + 模型）必须能复用（幂等键；`usage_ledger` 已有先例），
  否则多轮审核会把同一份稿子反复烧钱；
- 每点美元上限 **待实测**（同主题 3 次取中位数），并按"猜想数 / 稿件长度"线性外推。

### 9.10 签名判据缺一个字段：`last_revised_by`（我自己挖的坑）

§8.8.4 我写了 `s.name != last_revised_by`，但**这个字段今天不存在**
（`Document` 实测字段只有 `created_by`）。两条路：

- (a) 给 `Document` 加字段 —— 弱：文档行可被改，改掉它就能自签；
- (b) **从 `events.jsonl` 就地推导"这一版的最后写入者"** —— 强，且与本仓
  "派生态要么就地推导、要么装配期断言"的纪律一致。

**建议 (b)**：签名不信任文档行，信任事件流。

### 9.11 迁移与兼容

新表 / 新字段 / 新引用种类都要有升级路径：`SCHEMA_VERSION` 前进 + 旧数据默认值 +
迁移脚本 + **负控"旧产物仍可核"**（历史 12 份 `evidence.json`、旧 `relations` 仍要能过 `verify`）。
体例照 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md`（本仓已有的迁移提案范式）。

### 9.12 可观测读数（自动化不许退化成"人在跑工具"）

每个 LLM 点必须暴露四个数：**调用数 / 失败率（分类）/ 候选采纳率 / 被判据拦下的次数**，
并与 `draft/22:227-230` 的失败线绑定：

| 线 | 定义（逐字） | 对本草案的含义 |
|---|---|---|
| K1 | 元/可验证产物 **> ¥1000** | 每点预算与"每份可验证产物"的成本必须记账 |
| K2 | 内域集形式化成功率 **< 30%** | "猜想 → 形式化"的通过率就是这条线的输入 |
| K3 | 引文逐字回验 **无法达到 99%** | H 的内部逐字锚定与 B 的外部回验**共用这条线** |
| K4 | 人工介入率 **> 50%** | **H 必须能签**；签名若总要人加签，K4 立刻破线 |

## 10. 接入路径：按"爆炸半径"分四层（调查现状后的结论）

### 10.1 现状盘点（全部实测，命令可重跑）

| 面 | 现状 |
|---|---|
| 表 | `S.TABLES` **15 张**，每张 `{file, row, id_field, id_kind}`；`SCHEMA_VERSION = 1` |
| 加锁 | `store.LOCK_ORDER` **16 项**（15 张表 + `counters`） |
| ID | `ID_COUNTERS` **12 个**四位 id kind；`PROCESS_ID_PREFIXES` **3 个**（`r`/`p`/`t`）；两者与 `TABLES` 之间有交叉一致性判据（`tests/test_schema.py:187-198`） |
| 词表 | `table_tools._VOCAB_BY_FIELD` **手工 7 条**（`(表,字段) → 词表常量`） |
| 契约 | `interactions.CONTRACT_VERSION = 1` |
| 工具 / 动作 | 43 工具（其中 8 个通用表操作）· 49 动作 · 127 property 交叉断言 |
| 工作区判据 | `projects.classify` 认 `data/counters.json` 或 `.agentflow-workspace`，**不看表齐不齐** ⇒ 加表**不会**把 7 个旧项目判成 `not_a_project` |
| 迁移入口 | `Store.init()` 本来就是"缺哪张补哪张"（`if force or not p.exists(): _atomic_write(空表)`）⇒ 补新表 = **非 force 重跑 `init`** |
| 自动工具化 | `table_tools.ALL_TABLES = tuple(S.TABLES)`；`table.schema` 从 dataclass **反射**字段与 `ID_COUNTERS` |

### 10.2 三个"自然扩展点"（新设计该长在这上面）

1. **`S.TABLES` 自动工具化**：加一张表 ⇒ 立刻获得 8 个通用表操作 + 字段/词表暴露，
   角色面自动按读/写裁（`table.update roles=('A','B','D','E','F','G')`，C/H 只读）。
   **不需要新工具、不需要新动作、不需要新契约。**
2. **文件台账范式**：`.noai-approvals.json` 已证明"签名类对象不必进 store"
   （`sha256` 钉版本 + `reviewers{name,at,scope,verdict,note,evidence_path,evidence_sha256}` + append-only）。
   ⇒ **稿件签名台账走文件**，可以完全不碰 `LOCK_ORDER` 与 `schema.TABLES`。
3. **注入缝 + 非禁改区代码**：实测 `.noai-paths` 对 `agent_*.py` / `cli.py` / `llm.py` / `conductor.py` /
   `runflow.py` / `formalgw.py` / `tools/table_tools.py` **全部无命中** ⇒ LLM 接线、配套工具、
   词表映射都能在禁改区之外完成。

### 10.3 这批设计会碰到的禁改区文件 —— 只有 7 个，可分批评审

`schema.py` · `store.py` · `verify.py` · `interactions.py` · `capabilities.py` ·
`tools/__init__.py` · `tools/base.py`

（注意：**`tools/table_tools.py` 不在其中** —— §10.4 第 6 项那处改动是自由的。）

### 10.4 加一张表的完整触点清单（7 处；缺一处就有判据变红）

| # | 触点 | 文件 | 禁改区 | 谁会发现问题 |
|---|---|---|---|---|
| 1 | 行 dataclass + `validate()`（状态机、必填、引用） | `schema.py` | ✅ | 新表的负控用例 |
| 2 | `TABLES` 条目（`file/row/id_field/id_kind`） | `schema.py` | ✅ | `tests/test_core_audit_abc_cli.py:198` 会要求新表出现在工具普查输出里（它按 `S.TABLES` 全量断言，不写死数量） |
| 3 | 词表常量（如 `CONJECTURE_STATUSES` / `CONJECTURE_FORMS`） | `schema.py` | ✅ | `table.schema` 的 `enum` |
| 4 | `ID_COUNTERS` 加一个 kind（若用四位 id） | `schema.py` | ✅ | `tests/test_schema.py:187-198` 的 quartet 一致性判据 |
| 5 | `LOCK_ORDER` 插入位置 | `store.py` | ✅ | 并发判据（写集相交 ⇒ 串行）**需全部重测** |
| 6 | `_VOCAB_BY_FIELD` 加两条 | `tools/table_tools.py` | ❌ **自由** | 忘了就**静默不校验**那个字段（见 §10.7 第 16 条待裁） |
| 7 | `verify_all` 不变量（状态/升格/引用完整性/签名一致） | `verify.py` | ✅ | 不变量本身就是判据本体 |
| 附 | 旧工作区补新表文件 | —— | —— | 非 force 跑 `init`；负控"旧产物仍可核"（§9.11） |

### 10.5 四层爆炸半径（推荐落地顺序；每层独立可验、可停）

| 层 | 内容 | 触点 | 谁审 | 完成判据 |
|---|---|---|---|---|
| **T0** | LLM 缝（A/F/G/H 加 kwonly `llm=None`；E 用已有空插座）+ `Judge` 协议；候选先落文件；CLI 配套工具；B 案 evidence 瘦身 | 全在**非禁改区** | 四道门即可 | 默认路径**逐字节不变** + "未接线时零 LLM 调用" |
| **T1** | 猜想的**数据面**（§10.4 的 7 处） | `schema.py` + `store.py` + `table_tools.py` | 人审（schema/store） | 加完之后：6 个写角色用**既有 `table.*`** 就能读写猜想；7 个旧项目 `init` 补表后仍可核 |
| **T2** | 判据面：`verify_all` 不变量逐条加（猜想状态机 / 升格需 proof / 引用完整性 / 签名一致） | `verify.py` | 人审 | 每条都有正控 + 注入负控 |
| **T3** | 契约面：I13–I15 + `CONTRACT_VERSION` 前进；`capabilities.py` **只在确实要新动作时**动 | `interactions.py`（±`capabilities.py`） | 人审（冻结契约） | 新旧契约不同时有效；读 `CONTRACT_VERSION` 的地方一起改 |
| **T4** | 签名与内部引用：签名台账**走文件**；`doc:` 引用语法 + `Document` 修订哈希 + `Dependency` 内部来源 | `schema.py` / `verify.py` | 人审 | §8.8.8 四条负控 |

### 10.6 结论：最自然的三条做法

1. **猜想先当"表"进来，别先当"动作"进来。** 表一加就有 8 个通用操作与角色面，
   零新动作、零契约改动；语义动作（propose / test / promote）留到 T3，
   且闸门优先落在 `schema.validate` + `verify_all` 不变量上，而不是急着加能力项。
2. **签名当"文件台账"进来，别当"表"进来。** 复用 `.noai-approvals.json` 的范式
   （哈希钉版本 + 可核证据锚 + append-only），可以完全不碰 `LOCK_ORDER`。
3. **LLM 接线只长在注入缝上，并默认关闭。** 每个点 `llm=None` 时行为逐字节不变 ⇒
   "接线"与"行为变化"是两件可以分别验收的事（这正是 T0 的判据）。

### 10.7 我建议的第一批三件事（都在 T0，可立刻开工）

1. **A/F/G/H 插插座 + `Judge` 协议**（默认 `None`；判据：默认路径逐字节不变 + 未接线时零 LLM 调用）；
2. **CLI `evidence verify|store|migrate`**（配套工具，读侧只读，`migrate` 默认 dry-run）；
3. **B 案 evidence 瘦身**（`fulltextstore` 已备好，并在影子包里验过 12 条判据 + 四条注入全部咬住）。

## 11. 待你裁的十六件事

| # | 事项 | 我的建议 |
|---|---|---|
| 1 | 候选落点：文件还是新表？ | 先文件（P1–P3），要用表单独走 FC-27 人审 |
| 2 | LLM 能否**建议** owner / 子目标？ | 能建议，落值仍由 `ALLOWED_EDGES` + 预算裁决（`L-F2`） |
| 3 | 语义闸门假阳性率上限定多少？ | **待实测**后定；先量 ≥20 条真实样本再给数 |
| 4 | 每个点的 token/美元上限 | **待实测**（同主题 3 次取中位数） |
| 5 | H 的 LLM 输出是否必须逐条带证据行号？ | 必须（这正是"审校者自己的判断没有证据"那条最贵的课） |
| 6 | 是否把本表并进 `docs/ROLE-SPECS.md` 的 48 行能力表（新增"LLM 判断点"一列）？ | 建议并，保持"角色规格单一来源" |
| 7 | **猜想**的载体：Shape B（当作 `research_questions` 的一个 `kind`）还是 **Shape C（独立对象）**？ | **Shape B 已被否**（撞 `schema.py:604-609` 的不变量：`needs_evidence` 必须有 `waiting_request_ids`，而猜想等的是实验）；建议 Shape C，代价是动 `LOCK_ORDER`。**两者都必然命中 FC-27，需 2 名 reviewer** |
| 8 | 新表是否进 `store.LOCK_ORDER`（跨表事务原子性 vs 全部并发判据重测）？ | 我倾向进（原子性优先）；§7.8.3 末尾列了"先不进"的中间态，但它要单独评议 |
| 9 | 内部已审稿件是否当**可引来源**（加 `doc:` 引用种类 + `Document` 修订哈希）？ | 建议当 —— 否则"猜想→证明→定理"的升格没有第二跳，H 的审查成果也传不下去；代价是 §8.5 的三处 FC-27 改动 |
| 10 | 引用的**粒度**：整篇文档还是单条断言（`doc:id#claim_id`）？ | 建议**单条断言**（与 `lit:#p.4`、`exp:0002` 同粒度）；整篇引用会让"哪一句被引"变成不可查，`scope_drift` 也就无从判定 |
| 11 | 签名门槛：**H 签一条即生效**（`proof` 级"毫不犹豫"），不按对内/对外分档、不要维度覆盖、不要人工加签 —— 这样定？ | 按裁示已改成这个形态（§8.8.3/8.8.4）；**我原提的"对外加人工加签"已撤回** |
| 12 | 审核覆盖率：`accepted` 是否要求 100%（`claims_reviewed == claims_total`）？ | 建议要求；抽样只许出现在 `in_review`，且必须带 `truncated + why`（§9.3） |
| 13 | `last_revised_by` 从文档行加字段，还是从 `events.jsonl` 就地推导？ | 建议**事件流推导**（§9.10）：签名不该信任可被改的文档行 |
| 14 | 是否新增 I13–I15 三条契约（要动 FC-27 的 `interactions.py` + `CONTRACT_VERSION` 前进一格）？ | 建议新增（§9.2）；否则猜想生命周期、签名失效传播、审核覆盖三条都无处落判据 |
| 15 | 加表后的**迁移窗口**：要不要在 T1 合入的同一次操作里，对 7 个旧项目非 force 跑一遍 `init` 补表？ | 建议要（`Store.init` 只补缺文件、不覆盖已有）；否则旧项目里新表读写会撞 `事务未声明表` |
| 16 | `table_tools._VOCAB_BY_FIELD`（手工 7 条）是否改成**自动推导**？ | 建议改：忘了登记 ⇒ 该字段**静默不校验**（没报错、没告警）；可让行 dataclass 的字段元数据自带 `vocabulary=`，或加一条"schema 里的词表常量必须被某字段引用"的装配期断言 |
| 17 | **稿件语言**：默认给 `zh` 还是**不设默认**（每次必须显式）？`paper` 是否强制显式？ | 建议：内部稿件默认 `zh`（报告与提示词都是中文）、**`paper` 强制显式**（`document.require_explicit_for: [paper]`）；三层设置面见 §9.7.2，**实现必须与"读它的地方"同批落地**，否则就是本仓点名过的"加了配置项但没接线"（`contextbudget.py:137`） |
