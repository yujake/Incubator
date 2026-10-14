# 120-花销口径、按角色用不同厂商的 key、以及「按需读」的协作 skills（批 R106 计划）

> **这份文件就是「记载新 goal 的文件」。**
> 业主 2026-10-14 当面下达；上一阶段那三件（① `reach_fit` 提示词 ② 四位编号改六位
> ③ 二层唤起）已在 `b02b393` / `018b3ae` / `2371d6f` / `ff96251` / `4921556` 落地，
> 全套 `pytest tests` 5159 passed —— **老 goal 到此为止，结尾那句话是**：
>
> > **做完了就去看记载新 goal 的文件** —— 就是这一份。
>
> 新 goal：上限 **30 轮**，**每一轮必须完成足够多的任务**。四件事的落点在 §一，
> 现状清点在 §一的那张表，施工顺序在 §三，**待业主审批的 10 条能力在 §四**。

## 〇、新 goal 的原话（逐字留档，免得中转一次就走样）

> 将花销计算标准调整到与模型供应商定价吻合。更新设置面板与相应文件，允许不同角色智能体
> 用不同模型厂商的不同 api key（所有智能体的秘书另外共用一个 api key）。做提示词增强，
> 将面对不同类型任务应唤起的协作方式写成各智能体的 skills，以防止前置大量提示词，现做现读。
> 大量调研现有科研类 skills，抽出其中适用的工作逻辑改写成我们系统的智能体协作链 skills
> 或者各智能体自己的 skills，如果特别适合该智能体职责可直接写进智能体的前置提示词，
> 至少为每种智能体特地去找至少 5 个 skill 来综合考量（注意不是硬性要求给每个智能体写 5 个
> skill，定制 skill 时需保证描述无歧义、准确适配角色、动作都可实现），特别要给 M 多找素材
> （毕竟它是军师）。一个优质来源是 `D:\Incubator\temp\deepmath\moonshine\assets\skills\builtin`。
> 注意一定要改写成适合智能体协作系统的工作模式，不能照搬市面上 skill 的原文，
> 不能虚构我们系统不存在的动作！如果有某些动作是那些科研 skill（特别地，我们做的是数学科研）
> 特别推荐的但我们系统无法完成的，请先记录，统一等我审批是否实现这些动作。
> 这是下一阶段的 goal。请开一篇 draft 记录后开始工作。在 goal 的每一轮必须完成足够多的任务，
> 总轮次上限 30 轮。

（进度：R106 已落地 —— 花销口径三档 token + 本文件；逐条见 §三 的施工顺序。）

## 一、这一阶段要做的四件事（业主原话逐条落点）

### ① 花销口径与「谁能用哪个厂商的哪把 key」

业主原话：「将花销计算标准调整到与模型供应商定价吻合。更新设置面板与相应文件，
允许不同角色智能体用不同模型厂商的不同 api key（所有智能体的秘书另外共用一个 api key）。」

现状（本轮现读）：

| 那一格 | 今天在哪 | 今天是什么样 |
|---|---|---|
| 单价 | `modelcost.py` 的 `DEFAULT_PRICE_IN_USD_PER_M = 0.27` / `DEFAULT_PRICE_OUT_USD_PER_M = 1.10`（可被两条环境变量覆盖） | **一把价**打天下：不分厂商、不分模型、不分缓存命中/未命中 |
| 计价 | `LlmSeam(price=...)` → `modelcost.price_of()` → `usage_ledger.usd` | 每趟按当次 `tokens_in/out × 单价` 记账 |
| 机器设置 | `settings.py`：三段 `toolchain` / `model` / `workspace`，`MODEL_KEYS = (api_key, base_url, name, reasoning_effort)` | **只有一段 `model`**：全部角色共用一把 key、一个端点、一个模型名 |
| 角色拿缝 | `llmseam.LlmSeam.for_role(role, ...)` → `modelgw.spec_from_env()` | 与角色无关：谁都拿同一个 `ModelSpec` |
| 秘书 | `Secretary` 由宿主按角色派生（业主 T14「每唤起一个智能体就自带一个秘书」） | 秘书没有自己的模型缝 ⇒ 谈不上「另外共用一把 key」 |
| 设置面板 | `ui/src/pages/Machine.tsx` + `POST /api/settings`（`webui/writes.py::handle_settings`）+ `GET /api/machine`（`webui/readers.py::_settings_reading`） | 只编辑那一段 `model`；`api_key` 回显恒为掩码 |

要做成什么（**先把口径订死，再动代码**）：

1. **价目表按「厂商 × 模型」落一份**（一处定义），并区分**输入/输出/缓存命中**三类单价 ——
   供应商定价表就是这么给的（DeepSeek 的定价页把 cache hit / cache miss / output 分开）。
   口径来源要写进注释（哪一个厂商、哪一天抓的、单位是「每百万 token 的美元」）。
2. **记账口径改成「这次调用用的是哪一档价」**：`usage_ledger` 里那笔 `usd` 必须能追到
   `(vendor, model, price_tier)`，否则「花销与供应商账单对不上」这件事无法定位。
3. **按角色配模型**：设置文件从「一段 `model`」扩成「一段 `models`（按角色）+ 一段 `secretary`」，
   角色缺档时回落到 `models.default`；秘书那一段**所有角色的秘书共用**（业主点名的第二把 key）。
4. **设置面板**跟上：能按角色填 `vendor / base_url / model / api_key`，能填秘书那一档；
   `api_key` 永远只回显掩码（沿用今天那条纪律，不许为了「看得见」就回显真 key）。
5. 判据：单价表的**唯一来源** + 按角色取缝的回落链 + 秘书那一档真的被用上（三态读数）+
   面板与 `/api/settings` 的键集合一致（不许有一边偷偷多一格）。

### ② 把「该唤起谁」写成按需读的 skills（现做现读）

业主原话：「做提示词增强，将面对不同类型任务应唤起的协作方式写成各智能体的 skills，
以防止前置大量提示词，现做现读。」

形态（本轮定）：skills 落盘成**一目录一文件**（`skills/<角色>/<slug>.md`），
前置提示词里只留**一张极短的索引**（slug + 一句话 + 什么时候读它），
正文按需用 `fs.read` 现读。判据：索引里每一条都必须能在盘上找到那个文件、
且索引不许把正文抄进来（抄了就等于回到「前置塞大量提示词」）。

### ③ 调研科研类 skills 并改写成我们的协作链

业主点名的来源：`D:\Incubator\temp\deepmath\moonshine\assets\skills\builtin`（现读：**38 个** skill，
每个一目录一 `SKILL.md`，带 `name/description/allowed-tools/Execution Steps/Tool Calls/Output Contract`）。
它们调用的工具（`query_memory` / `search_knowledge` / `memory/*.jsonl`）**在我们的系统里不存在**
⇒ 一律只抽**工作逻辑**，改写成「哪一步由哪个角色做、用我们哪一个真实动作」。

硬约束（业主逐字）：不照搬原文；不虚构本系统不存在的动作；每种智能体至少调研 5 个 skill
综合考量（不是硬性给每个角色写 5 个）；定制 skill 必须描述无歧义、准确适配角色、动作都可实现。

### ④ 我们做不了但科研 skill 特别推荐的动作：**记录，等审批**

单列一节（本文件 §四）：逐条记「哪个 skill 推荐了什么能力 → 我们缺哪个动作/工具 →
为什么值得实现 / 代价」。**不擅自实现。**

## 二、来源清点（第一轮已读）

`builtin/` 下 38 个 skill（按目录名）：

```
conclusion-manage  construct-counterexamples  construct-counterexamples-neural-network-functions
construct-toy-examples  cross-domain-explore  direct-proving
direct-proving-neural-network-functions  examination-of-special-cases-neural-network-functions
extract-conclusion-memory  extract-project-claims  extract-project-memory  extract-reference-memory
extract-user-memory  identify-key-failures  lemma-prover  literature-survey  math-research-loop
memory-hygiene  memory-trigger-evaluator  pessimistic-verifier  problem-generator
problem-generator-neural-network-functions  problem-refiner  problem-solver  proof-constructor
proof-corrector  propose-research-plan-neural-network-functions  propose-subgoal-decomposition
quality-assessor  query-memory  record-novelty  research-consolidation  strengthening-agent
understanding-problems-neural-network-functions  verify-correctness-assumption
verify-correctness-computation  verify-correctness-logic  verify-overall
```

我们这一侧的「真实动作面」是唯一权威：`capabilities.ACTION_TABLE`（10 角色 / 60 动作）与
`capabilities.ALLOWED_EDGES`（32 条边）。**任何 skill 里出现的动作名都必须在这两张表里存在**，
否则它只能进 §四 的待审批清单。

## 三、施工顺序（每轮至少完成一件可验证的事）

1. **R106**：本 draft + ① 的价目表与记账口径（先把「单价从哪来、记到哪一格」订死，再动设置面）。
2. **R107**：`settings.models`（按角色）+ `secretary` 那一档 + `llmseam.for_role` 的回落链 + 判据。
3. **R108**：设置面板（`Machine.tsx`）+ `/api/settings` / `/api/machine` 的键集合判据 + 类型再生成。
4. **R109–R113**：② 的 skills 骨架（目录约定 + 索引段 + 判据）与 ③ 的第一批角色 skills
   （先 M，再 B/H/V，再 A/C/D/E/F/G）。
5. 每批都跑全套 + FC-27 流程（`noai_gate.py` → `noai_batch_sign.py` → 提交台账）。

## 四、待审批：科研 skill 推荐、而我们今天做不到的能力（逐条累积）

> 口径：**只记录，不实现**。每条写清「哪个 skill、要什么能力、我们缺什么、我的判断（该不该做）」。

| # | 来源 skill | 它要的能力 | 我们今天的缺口 | 初步判断 |
|---|---|---|---|---|
| 1 | `math-research-loop` / `extract-*-memory` / `query-memory`（几乎全部） | 跨趟的**结构化科研记忆**（`memory/research_log.jsonl`、按类型的 `verified_conclusion.md`、可查询索引 `*.sqlite`） | 我们有会话记录（`sessions/*.jsonl`）、草稿本（`notes/<角色>.md`）、台账表，但**没有「按类型可查询的结论记忆」**（`query_memory` / `search_knowledge` 这两个工具不存在） | 值得做：它是这批 skill 的地基（「现做现读」也靠它）；但它是**新工具 + 新表**，属架构级改动，等业主裁 |
| 2 | `lemma-prover` / `proof-constructor` / `direct-proving` | 逐引理**交互式**证明推进（一次一个引理、带回溯） | 我们有 `F` 的 `create_plan` / `step` / `attack_plan` 与 Lean 桥（`verify_tools`），但**没有「引理级」的计划对象**（计划是「难题」级） | 值得做的小半步：把 plan 的粒度降到引理；要先看 F 的真机读数 |
| 3 | `verify-correctness-*`（assumption / computation / logic 三条） | 把「验证」拆成**假设、计算、逻辑**三条独立的检查轴 | 我们有 V 的三态复核 + E 的数值/形式化实验 + H 的审校，**没有「按这三条轴分别出结论」的动作** | 值得做：三条轴与我们的五元位能对上（假设↔前提、计算↔numeric、逻辑↔proof），但要先与业主对齐「哪条轴由谁签」 |
| 4 | `pessimistic-verifier` | **悲观验证**：默认「这条结论有问题」，找反例优先 | 我们的 V/H 是「审」，没有「默认否定」的把关角色 | 可做：V 的提示词里加一档，成本低；但要业主认这是不是 V 的职责 |
| 5 | `record-novelty` / `quality-assessor` | 新颖性 / 质量**打分**并与既有文献对照 | 我们没有「新颖性」这一格读数（`relations` 有重复判定，但没有「新不新」） | 谨慎：打分口径难定死，容易变成自报；建议先不做 |
| 6 | `identify-key-failures` | 从失败里抽出**关键失败模式**并回灌下一轮 | 我们有 `review_findings`、`attack_plans.history`，但没有「失败模式库」 | 与 §四#1 同族（记忆），一起裁 |
| 7 | `cross-domain-explore` | 跨领域类比检索 | `A.search_literature` 能检索，但没有「跨领域」这一维的编排 | 可做：`search_requests` 的 `mode` 里加一档；等业主裁 |
| 8 | `propose-subgoal-decomposition` / `propose-research-plan-*` | 把难题拆成子目标并排序 | 我们有（F 的 `create_plan` + `subgoals`），**只差提示词侧的写法** | 不用新动作：直接改写成 F/D 的 skill |
| 9 | `literature-survey` | 系统性文献综述（检索式、纳入/排除、缺口表） | 我们有检索（`A`）、关系图（`C`）、台账；**没有「综述」这一件产物** | 可做：`documents` 的 `kind` 里加一类 + G 的编排 |
| 10 | `construct-counterexamples` / `construct-toy-examples` | 构造反例 / 玩具例子作为一等动作 | 我们有（E 的实验、D 的立题），没有「反例/玩具例」的**独立交付物** | 值得做：它是数学科研里最常用的两手，建议进「动作表」待批 |

（本表随每轮调研继续加行；业主批一条我实现一条。）
