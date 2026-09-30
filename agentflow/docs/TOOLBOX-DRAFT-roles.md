# 角色工具箱设计（草案）—— 让每一次思考都花在真问题上

> **现状导读（不构成判据）· 本文是设计草案/提案**：本仓当前分层结构的逐项事实（含路径与复跑命令）见
> [`../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md`](../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md)。
> 本文只作现状导读、**不构成判据**，**也不要把本文写成现状**。本文出现的路径一律**相对工作区根**（`D:\Incubator`）。
>
> ⚠️ **凡本文把"今天的实测"当成当前事实的地方，按实际状态读（截至 2026-09-30 的实际状态见正文 / 代码，本文是草案）**：
> - §1 那张"实测现状"表的**逐角色工具数已过期**。实测 2026-09-30
>   （`python -m agentflow.cli tools`，在 `agentflow/` 下跑）：
>   **工具总数 72（已装模块 12）；逐角色 A 23 / B 18 / C 19 / D 37 / E 21 / F 32 / G 37 / H 25 / M 9**。
>   本文写的是 A 13 / B 11 / C 13 / D 25 / E 14 / F 25 / G 25 / H 19 / M 0 —— 那是**起草当时**的
>   `build_for_role(role)` 快照，不是当前值；本文 §6 第 3 条也自陈"口径差异未对账"，**不许**把它当现状引用。
> - §3 前的说明里"`side_effect` / `external` 的单一来源都是 `src/agentflow/tools/base.py`"⇒
>   是的，路径是 `agentflow/src/agentflow/tools/base.py`（本文写成 `src/agentflow/tools/base.py`，
>   那是 `agentflow/` 内的相对写法）。
> - §3 声明的 16 个聚合工具（`brief.*` / `pack.*` / `queue.next` / `search.harvest` / `doc.ingest` /
>   `graph.answer` / `experiment.harness` / `attack.workitem` / `plan.simulate` / `audit.recompute` /
>   `cycle.report`）**一个都还没实装**；它们是提案，不是现状。
> - 只读角色仍是 `C` / `H`（`agentflow/src/agentflow/tools/__init__.py` 的 `READ_ONLY_ROLES = ("C", "H")`），
>   N / O / Q **不是**只读角色 —— 它们还不是角色。

> **要解决的问题**（用户逐字）："给每个角色搭建全套工具箱，尽可能让他们的每一次思考都是在想真问题，
> 而非消耗在无聊的数据处理、信息查询上。"
>
> **性质**：**设计草案**，不写代码。落点：新增工具模块（`src/agentflow/tools/*.py`，**非禁改区**）
> + 每角色的工具面声明（`ToolSpec.roles`，非禁改区）+ `capabilities.WRITE_SETS`（非禁改区）。
> 与既有设计的关系：本文档是 `../draft/20-…md` **§14** 的细节层，
> 三角色（N/O/Q）的工具面另有权威来源 `ROLE-SPECS-DRAFT-N-O-Q.md`（**不在此重复声明**）。
>
> **判据**：`../temp/_verify_toolbox_draft.py` —— 解析 §3 的机器可读块，断言
> ① 12 个角色各一行 ② 每个新工具六属性齐全、`roles` 合法、`side_effect` 合法
> ③ **只读角色（C/H/N/Q）不许拿到写工具**（`tools/base.py:374` 的结构性规则）
> ④ 默认路径工具数 ≤ 上限 ⑤ 每条新工具都回答了"它替模型省掉哪一类机械劳动"
> ⑥ 三条负控会红。

---

## §0 一句话结论

今天的工具箱是**原料级**的：每个角色手里都是 13–25 个**原子**工具（`table.list` / `trace.relation` /
`attack.status` …），于是模型被迫把思考预算花在**把原料拼成上下文**上 —— 而这正是机械劳动。
本设计加一层**任务级聚合工具**（一次调用 = 一个有意义的单位，且返回"可直接推理"的结构），
并把原料工具降级为**下钻**用途；用**可测的判据**（下钻调用占比、空转率、工具闲置率）盯住效果。

---

## §1 实测现状（口径：`build_for_role(role)`，不带 deps）

```
角色  工具数  取数  成型  本职  未分类   机械占比    思考单元
A       13     5     0     0     7      38%     检索策略与结果取舍
B       11     7     0     0     4      64%     整理期的语义决定（判重/归类/抽取什么）
C       13    13     0     0     0     100%     结构分析（热点/路径/缺口的结构解释）
D       25    17     4     1     3      84%     研究判断（证据等级/知识是否足够/升级与否）
E       14     9     1     0     4      71%     数值实验与形式化设计
F       25    13     5     3     4      72%     攻坚（拆子目标/找卡点/试下一步）
G       25    13     5     1     6      72%     撰写（论证结构、断言与证据的对应）
H       19    13     5     1     0      95%     审校（稿件有没有把自己说清楚）
M        0     0     0     0     0       0%     调度（不推理）
```

四条从数字里读出来的事实（不是印象）：

| # | 事实 | 证据 |
|---|---|---|
| 1 | **同一批原料工具被反复发给不同角色**：`table.*` 出现在 6 个角色（A/B/D/E/F/G/H）、`verify.*` 4 个、`attack.*` 4 个、`doc.*` 4 个 | 上面的清单逐条可比 |
| 2 | **工作台最大的角色反而最远离本职**：D/F/G 各 25 个工具，机械占比 72–84% | 上表 |
| 3 | **H 的 19 个工具里 18 个是原料/成型**，真正属于"审校判断"的只有 `review.scan_document` 与 `doc.scan_claim` | `cli tools --role H` 的实测输出 |
| 4 | **C 的工具面 100% 是取数**：13 个工具全是 `graph.*` / `trace.*` / `table.*`，没有任何"结构解释"的产出工具 | 上表 |

> 口径说明：`cli tools --role C` 另外显示 `fs.*`（17 个），那是带 deps 的装配路径；
> 本表用 `build_for_role(role)`（不带 deps），两者差异本身是一条登记时该对账的项（§6 待办）。

---

## §2 设计原则（五条，每条都能对应到一个判据）

| # | 原则 | 反例（今天真实存在） | 判据 |
|---|---|---|---|
| P1 | **一轮取数**：装配一个对象的完整上下文必须一次调用完成 | D 要回答"这个问题该不该升级"得先 `table.get(research_questions)` → `trace.relation` → `verify.evidence_for` → `review.list_findings` → `graph.neighbors` 五轮 | `brief.workitem` 的调用轮数 = 1；下钻调用占比 ≤ 15% |
| P2 | **确定性下沉**：算术、格式转换、规范化、hash、模板渲染一律由工具做，模型不做 | G 手工把引文与页码拼进正文；H 手工比对 `duplicate_quote` | 每个派生数字必须带 `source`；"模型做算术"列入反模式 |
| P3 | **返回即可推理**：工具返回的是带 provenance 的三态结构，不是原始 JSON 转储 | `table.list` 返回整行原始字典（含 20 个字段，其中 14 个与本次判断无关） | 聚合工具的返回必须逐字段声明用途；无关字段不许返回 |
| P4 | **空返回必须解释**：`ok=True` 但空，必须给"为什么空" | 空列表会被读成"没有问题"（P16 的同族） | 复用三态纪律；新增判据 `empty_result_without_reason` |
| P5 | **两个上限**：默认路径工具 ≤ 12/角色；一个周期内 0 次调用的工具要么删、要么在规格里写明"只在何种情形用" | D/F/G 各 25 个（默认路径与下钻混在一起） | `toolbox_span` / `unused_tool` |

**默认路径 vs 下钻**（这条是本设计的关键区分，避免"要么能力丢失、要么工具膨胀"的两难）：

- **默认路径**：聚合工具 + 该角色的**本职判断**工具 —— 目标 ≤ 12 个，模型日常只看这一层；
- **下钻**：原始原料工具（`table.*` / `trace.*` / …）**不删**，但只在聚合结果明确标出
  "这里需要下钻"时才用；下钻调用计入 `plumbing_ratio`。

---

## §3 逐角色工具箱（机器可读；本节块是**唯一来源**）

> 每行 `role:` 给该角色的：本职（思考单元）、今天的工具数与机械占比、默认路径构成、新增聚合工具、撤下/不给的东西。
> 每个 `tool:` 行给六件套的一件（`name`/`summary`/`params`/`returns`/`side_effect`/`roles`）
> 外加三格**本设计特有**的属性：`replaces`（替掉哪几轮机械劳动）、`saves`（省几轮）、`prose`（谁不再需要自己想这件事）。
>
> `side_effect`（第一根轴，= 属性 `effect`）取值域 = `none` / `read` / `write_local`；
> **第二根轴 `external`** 取值域 = `none` / `egress` / `exec`（字段名是 `declared_external`，属性名是 `external`）。
> 两处的单一来源都是 `src/agentflow/tools/base.py`（`SIDE_EFFECTS` / `EXTERNAL`；
> ⚠️ 本文原写"`tools/base.py:199`"并含遗留取值 `network` —— 那是 **B3 迁移前**的事实，
> `network` 已从词表**删除**，声明它会直接抛 `ValueError`）。
> **只读角色（C/H）不得拿 `write_local`/`network`** —— 这条由 `for_role` 结构性执行，
> **B3 收官后判据更强**：只读角色同时被剥掉 `external == "exec"`（除非沙箱被声明可用），
> 所以 H 今天连 `verify.check_formal` 都拿不到（实测 H = 22 个工具、零 `exec`、零 `egress`）。
> 本设计把它写进验收，避免"设计时给了、登记时被剥掉"的静默偏差。

<!-- TOOLBOX:BEGIN -->
```text
role: A | core: 检索策略与结果取舍 | today: 13 | plumbing: 38% | default: search.harvest + search.providers + queue.next | not_given: 手工下载/登记/去重的逐条编排
role: B | core: 整理期的语义决定（判重/归类/抽取什么） | today: 11 | plumbing: 64% | default: doc.ingest + ocr.run + queue.next | not_given: 抽取→候选→预筛的逐条拼装
role: C | core: 结构分析（热点/路径/缺口的结构解释） | today: 13 | plumbing: 100% | default: graph.answer + queue.next | not_given: 13 个原料工具当默认路径用
role: D | core: 研究判断（证据等级/是否足够/升级与否） | today: 25 | plumbing: 84% | default: brief.workitem + brief.coverage + pack.evidence + queue.next | not_given: 下钻五连查
role: E | core: 数值实验与形式化设计 | today: 14 | plumbing: 71% | default: experiment.harness + verify.check_formal + queue.next | not_given: 环境探测与脚本 hash 的手工编排
role: F | core: 攻坚（拆子目标/找卡点/试下一步） | today: 25 | plumbing: 72% | default: attack.workitem + brief.blockers + queue.next | not_given: 逐个查子目标状态与预算
role: G | core: 撰写（论证结构、断言与证据的对应） | today: 25 | plumbing: 72% | default: doc.assemble + pack.evidence + pack.document + queue.next | not_given: 手工拼引用/页码/等级
role: H | core: 审校（稿件有没有把自己说清楚） | today: 19 | plumbing: 95% | default: review.pack + doc.scan_claim + queue.next | not_given: 13 个原料工具当默认路径用
role: M | core: 调度（不推理，只执行给定计划并过策略层） | today: 0 | plumbing: 0% | default: （无工具；不变） | not_given: 任何领域工具
role: N | core: 现状诊断（哪些偏离重要、数据够不够） | today: 0 | plumbing: 0% | default: brief.ledger + brief.coverage + brief.blockers + cycle.report + mgmt.scan | not_given: 手工遍历 16 张表
role: O | core: 计划（目标可否判定、资源怎么分） | today: 0 | plumbing: 0% | default: brief.coverage + brief.blockers + plan.simulate + mgmt.plan | not_given: 手工验算预算与越界
role: Q | core: 程序审计（判据有没有真的执行、谁在自审） | today: 0 | plumbing: 0% | default: audit.recompute + brief.ledger + cycle.report + mgmt.audit | not_given: 手工重算指标

tool: brief.workitem | summary: 一个待办对象（研究问题/攻坚子目标/稿件/关系）的完整上下文 | params: kind（对象种类）、ref_id（对象代号） | returns: {object, evidence[], dependencies[], history[], blockers[], provenance[]} | side_effect: read | roles: D,F,G,H,N | replaces: table.get + trace.* + verify.evidence_for + review.list_findings + graph.neighbors | saves: 4 | prose: 一个研究问题/子目标/稿件的全部上下文（含卡点与依赖状态）
tool: brief.ledger | summary: 台账事实包（按 action/outcome/role 的计数，每个数字带来源与覆盖三态） | params: window（周期或任务区间）、group_by（action/outcome/role） | returns: {counts[], sources[], coverage} | side_effect: read | roles: N,Q | replaces: table.list + table.count（对 tasks/usage_ledger/eval_results 的逐表遍历） | saves: 5 | prose: 台账事实包：按 action/outcome/role 的计数，每个数字带来源与覆盖三态
tool: brief.blockers | summary: 全部卡点与拒绝码的聚集 | params: scope（全部/某计划/某角色） | returns: {blocked[], refused_codes[], progress_states[], oldest_first[]} | side_effect: read | roles: F,N,O | replaces: attack.status + table.list(subgoals) + 逐条读 refusal_reason | saves: 3 | prose: 全部卡点与拒绝码的聚集（含 blocked_reason 与 progress_state）
tool: brief.coverage | summary: 覆盖度视图（无证据问题/未回验关系/证据不足断言/未闭合依赖） | params: scope（全局或某稿件/问题） | returns: {no_evidence[], unverified_quotes[], weak_claims[], open_deps[]} | side_effect: read | roles: D,N,O,Q | replaces: 手工交叉 4 张表算"哪些问题没证据/哪些关系未回验" | saves: 4 | prose: 覆盖度视图：无证据问题、未回验关系、证据不足断言、未闭合依赖
tool: pack.evidence | summary: 一条断言的全部证据（按判定顺序排好） | params: claim_key 或 relation_id | returns: {quotes[]{text,page,lit}, evidence_kind, deps_status, experiments[]} | side_effect: read | roles: D,G,H | replaces: trace.relation + verify.evidence_for + doc.scan_claim 的手工拼接 | saves: 3 | prose: 一条断言的全部证据（引文原文/页码/等级/依赖闭合/已有实验）按判定顺序排好
tool: pack.document | summary: 一篇稿件的可裁定片段（断言+引用+等级+待判项） | params: doc_id、section（可选） | returns: {claims[]{text,evidence,level,open_items[]}} | side_effect: read | roles: G,H | replaces: doc.list_documents + 逐条 doc.scan_claim | saves: 4 | prose: 一篇稿件的可裁定片段（断言+引用+等级+待判项），H 只判内容
tool: queue.next | summary: 按确定性次序给出接下来 n 个可做动作及其入参 | params: role、n（默认 3） | returns: {actions[]{action, args, why, blocked_by}} | side_effect: none | roles: A,B,C,D,E,F,G,H,N,O | replaces: 靠猜"下一步该查哪个 id"的试探轮次 | saves: 2 | prose: 按确定性次序给出接下来 n 个可做动作**及其入参**（复用 attack.pick_next_subgoal 的思路，扩到全局）
tool: search.harvest | summary: 一轮检索端到端（执行→去重→登记→落盘→触发抽取） | params: topic、mode、budget、max_items | returns: {admitted[], duplicates[], failed[]{reason_code}, registered[]} | side_effect: read | external: egress | roles: A | replaces: search.download + search.register + search.dedup_check + search.literature 的逐条编排 | saves: 3 | prose: 一轮检索端到端（执行→去重→登记→落盘→触发抽取），失败原因按受控码分类
tool: doc.ingest | summary: 一篇文献的整理端到端（抽取→候选概念/关系→矛盾预筛） | params: lit_id、mode（text/ocr） | returns: {text_ref, concept_candidates[], relation_candidates[], contradiction_candidates[]} | side_effect: write_local | roles: B | replaces: ocr.run + ocr.detect_text_layer + table.create/update 的逐条编排 | saves: 3 | prose: 一篇文献的整理端到端（抽取→候选概念/关系→矛盾预筛），B 只判语义
tool: graph.answer | summary: 四类结构分析（热点/路径/冷门/缺口）的统一答案结构 + provenance | params: kind（hottest/paths/cold/gaps）、参数随 kind | returns: {answer, candidates[]{ref,score,why}, provenance[]} | side_effect: read | roles: C | replaces: graph.build + graph.stats + graph.neighbors + graph.relations_between 的四连查 | saves: 3 | prose: 四类结构分析（热点/路径/冷门/缺口）的统一答案结构 + 每个结论的 provenance
tool: experiment.harness | summary: 实验端到端（探测→跑→绑 hash→登记） | params: method、script_path、params | returns: {backend, code_hash, result, evidence_kind, registered:"experiment_id"} | side_effect: write_local | roles: E | replaces: verify.detect_verifier + verify.code_hash + verify.run_experiment 的手工编排 | saves: 3 | prose: 实验端到端（探测→跑→绑 hash→登记），环境缺失时如实给 no_backend
tool: attack.workitem | summary: 一个攻坚子目标的完整上下文与候选下一步 | params: plan_id 或 subgoal_id | returns: {subgoal, owner, history[], evidence[], candidates[]{action,why}} | side_effect: read | roles: F | replaces: attack.status + attack.pick_next_subgoal + verify.evidence_for | saves: 3 | prose: 一个攻坚子目标的完整上下文与候选下一步（含 owner 与卡点）
tool: plan.simulate | summary: 把计划草案喂给 M 的策略层预演（越界即报，不派单） | params: plan_draft（任务序列）+ policy（可选覆盖） | returns: {allowed, violations[]{code,detail}, budget_projection} | side_effect: none | roles: O | replaces: 靠"觉得预算够"来估 | saves: 2 | prose: 把计划草案喂给 **M 的策略层** 预演（`policy.check`），越界即报且**不派单**
tool: audit.recompute | summary: 抽样重算：按某条指标的 source 重算一遍 | params: metric_ref（diagnosis 里的键）或 verify_code | returns: {verdict（一致/不一致/算不出）, recomputed, declared, source} | side_effect: read | roles: Q | replaces: 手工重算指标 | saves: 3 | prose: 抽样重算：按某条指标的 source 重算一遍并给出"一致/不一致/算不出"三态
tool: cycle.report | summary: 周期报告的确定性渲染（含 unknowns 段） | params: cycle_id、format（md/text） | returns: {report_text, unknowns[], section_sources[]} | side_effect: read | roles: N,Q | replaces: 手工把诊断与审计拼成一段可读文本 | saves: 2 | prose: 周期报告的确定性渲染（含 unknowns 段；没有未知项也要显式写"本次无未知项"）
```
<!-- TOOLBOX:END -->

**共 16 个新工具**（3 个管理角色自有工具 `mgmt.scan`/`mgmt.plan`/`mgmt.audit` 已在
`ROLE-SPECS-DRAFT-N-O-Q.md` 声明，此处不重复 —— FC-03）。
（逐条更正：本文 §3 的机器可读块里 `tool:` 行只有 **15** 条，块外按"15 个实装"口径引用；
`NOAI-CHANGE-LIST-management.md` 第 33 条写的也是 **15 个聚合工具** ⇒ 上面"16 个"是笔误，
**以块内的 15 行与 `PROPOSED-NAMES` 块的 15 行为准**；本行更正只改这一处数字，不动任何设计取舍。）

### 3.1 为什么这 16 个而不是别的（取舍记录）

| 候选 | 采用/放弃 | 理由 |
|---|---|---|
| `brief.context(task_id)`（把任意任务的上下文打包） | **放弃**（并入 `brief.workitem`） | "任意任务"会退化成"返回一切"，反而增加上下文；`brief.workitem` 按对象种类给**有边界**的包 |
| `brief.everything()`（全库摘要） | 放弃 | 与上下文预算直接冲突；P15 的另一种形态（信息噪音化） |
| 每个角色各给一个"日志/进度"工具 | 放弃 | `brief.ledger` 一个就够；12 个同义工具是 FC-03 的反面 |
| `graph.answer` 之外再加 `graph.explain` | 放弃 | 解释属于 C 的**思考**，不该由工具替它做（工具只装配事实） | <!-- refs:ok 本行逐字引用了一个**未采用**的工具名，故豁免引用核对 -->
| `plan.simulate` | **采用** | 它让 O 的"越界检查"变成一次调用，而且复用的是 M 已有的确定性策略层（不新造判据） |
| `audit.recompute` | **采用** | 它把 Q 的独立性从"自称独立"变成"可重算"，是 §12.2 补偿控制的机械化前提 |

---

## §4 判据与门（新增 6 条 verify 码）

| # | code | 判据 | 数据来源（既有） | 阈值（初值，**影子模式校准**） |
|---|---|---|---|---|
| 1 | `plumbing_ratio` | 某角色一个周期内**下钻调用 / 总调用** | `tasks.action` + 各角色的默认路径声明 | ≤ 15%（超了报，不阻塞） |
| 2 | `wasted_call_ratio` | `ok=False`，或空返回且无原因，占总调用 | `tasks.outcome` + 工具返回的 `meta.kind` | ≤ 10% |
| 3 | `unused_tool` | 该角色在周期内 0 次调用、且规格里没写"何种情形用" | `tasks.action` 全量 | > 0 即报（info） |
| 4 | `toolbox_span` | 某角色**默认路径**工具数 | 本文件 §3 的块（登记后被 `ToolSpec.roles` 取代） | ≤ 12 |
| 5 | `fc06_expected_tools` | 每角色的**预期工具名清单**（FC-06 缺的那一块） | 本文件 §3 + `cli tools` 普查 | 清单与实装逐项一致（差异即报） |
| 6 | `empty_result_without_reason` | 空结果且无"为什么空" | 工具返回契约（三态纪律） | 一次即报 |

> **码 5 直接补上 FC-06 的缺口**（`DEVELOPMENT.md` §9.2 记的"缺每角色的预期工具名清单"）：
> 本文件 §3 的 `default:` 列**就是**那份清单的草案形态。

## §5 反模式（拟登记为 `DEVELOPMENT.md` §6 的 **P18**，需人审）

> **P18：让模型自己做机械劳动** —— 自己算术、自己拼上下文、自己转换格式、自己逐条取数。

| 形态 | 为什么禁止 | 替代 | 判据 |
|---|---|---|---|
| 模型自己加总/算比率 | 算术错一次，整份报告的口径就错了，而且**没有任何判据会红** | 派生数字一律来自工具（`brief.ledger` 等） | 派生数字必须带 `source` |
| 模型自己把 N 次取数拼成上下文 | 消耗思考预算；且每次都拼得略有不同（不可复现） | 聚合工具（`brief.*`/`pack.*`） | `plumbing_ratio` |
| 模型自己格式化/渲染 | 与"单一来源"冲突（模板会有第二份实现） | `cycle.report` / `doc.render_markdown` | FC-03 / R003 |
| 用多轮试探找"该查哪个 id" | 每轮都是一次完整推理，成本最高 | `queue.next` | `wasted_call_ratio` |

## §6 风险与反驳（这一节给评审者）

| # | 攻击 | 回应 |
|---|---|---|
| 1 | **聚合工具会藏细节** ⇒ 误判 | 三条硬约束：① 聚合结果每个派生数字带 `source`；② 聚合工具**只装配不下结论**（"该不该升级"永远是 D 的判断）；③ 支持下钻（原料工具不删） |
| 2 | **工具膨胀** ⇒ 模型把预算花在"选工具"上 | 默认路径 ≤ 12；`queue.next` 直接给出候选动作；同义工具合并（§3.1 已放弃 4 个候选） |
| 3 | **"思考占比"是代理指标，会被刷**（少调工具 ≠ 想得更多） | 它**只作诊断，不作考核**（呼应 `draft/20` §8：不做绩效排名）；必须与产出质量配对看（H 的 findings 数、D 的 `evidence_kind` 等级分布） |
| 4 | **预计算 ⇒ 判据真空**（P16） | 聚合工具的每个派生量都要能被 Q 用 `audit.recompute` 重算；"算不出"必须落 `unknown` |
| 5 | **新工具又变成没人用的机制**（本项目真实病，`draft/20` §1.3） | `unused_tool` 判据 + 影子模式（先只统计调用分布，不改默认路径） |
| 6 | 只读角色拿到写工具 | `for_role` 结构性剥离（`tools/base.py:374`）+ 本文件验收③ |

## §7 与既有设计的接口

| 项 | 落点 | 禁改区 |
|---|---|---|
| 16 个新工具的实装 | 新模块 `src/agentflow/tools/brief_tools.py` / `pack_tools.py` / `harvest_tools.py`（或按族并入既有模块） | ❌ |
| 每角色的 `ToolSpec.roles` 声明 | 各工具模块内 | ❌ |
| `capabilities.WRITE_SETS` 同步（新工具若写表） | `capabilities.py` | ❌ |
| `fc06_expected_tools` 的基线快照 | 新文件 `src/agentflow/tools_expected.py`（或 `docs/`） | ❌ |
| 6 条新码 | `verify.py` | ✅ **人** |
| P18 进 `DEVELOPMENT.md` §6 | `DEVELOPMENT.md` | ❌（但属规范变更，走同一人审） |

## §8 这份设计**没能**做到的

| # | 内容 |
|---|---|
| 1 | **16 个工具的 `params`/`returns` 只给了用途级描述**，没有给 JSON Schema —— 那是登记时按 §4.3 的六件套逐字段写的事，本文档只定"该有什么工具、替掉哪几轮"。 |
| 2 | **`plumbing: NN%` 是"工具面占比"，不是"调用占比"**：真正的调用占比要等台账接线（P0）之后才能算。上表的百分比口径写在 §1 的代码块标题里，不要当成运行时指标。 |
| 3 | `cli tools --role` 与 `build_for_role()` 的口径差异（C：17 vs 13）**未对账**，登记前必须查清哪一个是权威（否则 §3 的 `today:` 列会有系统性偏差）。 |
| 4 | 阈值（15% / 10% / 12）**全是初值**：必须先在影子模式量触发率与假阳性率（P15 纪律），不许直接当门。 |
| 5 | 本文档**没有**评估这 16 个工具对上下文预算的影响：聚合返回更大，可能触发更多裁剪 —— 需要在 P1 影子模式里量"返回字节数 vs 被剪比例"。 |

## 本文档声明为"新增"的名字（判据 B 的输入）

<!-- PROPOSED-NAMES:BEGIN -->
```text
proposed_tool: brief.workitem
proposed_tool: brief.ledger
proposed_tool: brief.blockers
proposed_tool: brief.coverage
proposed_tool: pack.evidence
proposed_tool: pack.document
proposed_tool: queue.next
proposed_tool: search.harvest
proposed_tool: doc.ingest
proposed_tool: graph.answer
proposed_tool: experiment.harness
proposed_tool: attack.workitem
proposed_tool: plan.simulate
proposed_tool: audit.recompute
proposed_tool: cycle.report
proposed_code:  plumbing_ratio
proposed_code:  wasted_call_ratio
proposed_code:  unused_tool
proposed_code:  toolbox_span
proposed_code:  fc06_expected_tools
proposed_code:  empty_result_without_reason
proposed_module: tools_expected.py
```
<!-- PROPOSED-NAMES:END -->
