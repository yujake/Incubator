# 角色规格（草案）—— N / O / Q 与确定性周期驱动

> **这是一份草案，不是权威规格。** 权威规格是 `ROLE-SPECS.md`（A–H + 主控 M）。
> 本文档存在的原因：`N`/`O`/`Q` **还没进 `schema.ROLES`**，工具面也没登记；
> 此刻改 `ROLE-SPECS.md` 等于让权威规范承诺三个不存在的角色。
> 登记完成（S3 清单执行后）时，本文档的三节按同样的 10 小节顺序并入 `ROLE-SPECS.md`。
>
> **来源**：`../draft/20-管理层与责任链的重设计草案.md` §3（目标组织）、§4（权责与监督）、
> §5（七功能机制）、§12（九条裁决）。本文件只做一件事：把那些结论落成**可核对的角色规格**。
>
> **判据**：`../temp/_verify_role_specs_draft.py` —— 复用 `tools/verify_role_specs.py::check()`
> 的解析与判定逻辑（在内存中把角色模式放宽到 `N/O/Q`），并要求本文档的
> `PROPOSED-NAMES` 块与 `RACI-CHECK` 块成立。负控：删掉任一小节 ⇒ 必须以 `incomplete` 结束。

---

## 与既有机制的三条对齐（先说清，否则规格会与代码打架）

| # | 规格里的要求 | 既有的落点（**复用，不新造**） |
|---|---|---|
| 1 | N/O/Q 都是只读角色，各自只有一个窄写面 | `READ_ONLY_ROLES`（`tools/__init__.py:55`）+ `ToolRegistry.for_role` 的结构性过滤（`tools/base.py:349/374`）+ **`READ_ONLY_WRITE_EXCEPTIONS`**（`capabilities.py:623`）。`assert_capabilities` 要求例外的写集**必须显式登记并写下理由**（`capabilities.py:956-962`） |
| 2 | 只读角色也能写自己的产出表 | H 已经是这个形态：只读 + `review_findings`/`documents.status` 的窄写面（`agent_h.py` 的 `writers` 落库代理 + 装配期 fail-closed 白名单断言）。N/O/Q 照这个形态做 |
| 3 | 角色集合是单一来源，新角色必须同时改能力表 | `schema.ROLES` → `capabilities.CAPABILITIES`/`WRITE_SETS`/`ALLOWED_EDGES` 的导入期断言（`capabilities.py:913-929`）。**漏改会在导入期直接抛**，不会静默 |

> 设计计数说明：下文各角色 `X.4 工具面` 标题里的数字是**设计条数**（复用哪些既有工具 + 新增几个），
> **不是实测值**。真实条数只能在角色登记、工具 `roles` 声明补齐之后，由
> `python -m agentflow.cli tools --role <X>` 读出 —— 那条命令是唯一的对账口径。

---

## N —— 现状官（Situation Officer）

### N.1 一句话定位

把作业层与执行层的**事实**聚合成一份可追溯的诊断：管理层唯一"知道发生了什么"的窗口。
它**只描述，不解释目标，不派单**。

### N.2 职责

| # | 职责 | 可判定判据 |
|---|---|---|
| N-1 | 从既有权威来源读事实（`tasks`/`usage_ledger`/`eval_results`/`verify_all` 的 Issue/progress_state/subgoals 的卡点） | 诊断里每个数字都带 `source`（`表.字段` 或 `模块.函数`） |
| N-2 | 产出异常清单与未知清单 | `anomalies[]` 与 `unknowns[]` 都存在；`unknowns` 为空时必须显式写"本次无未知项" |
| N-3 | 给出数据完整性三态 | 每条指标带 `coverage ∈ {complete, partial, unavailable}` |
| N-4 | 落一行 `diagnoses` | 该表是 N 的**唯一**写面，且已在 `READ_ONLY_WRITE_EXCEPTIONS` 登记 |
| N-5 | 不许自己重算权威口径 | 预算数只能来自 `usage_ledger` 的汇总函数，**不许**从 `tasks.tokens` 求和（`conductor.py:1139-1142` 的反面教材） |
| N-6 | 困难上报的归集口 | `progress_state ≠ ok` 的任务必须在诊断里成组列出（`failure_without_reported_difficulty` 的另一半） |

### N.3 明确不负责

| 不做 | 为什么 | 该由谁 |
|---|---|---|
| 制定目标或计划 | 诊断者与计划者分离，避免"先有结论再找证据" | O（计划官） |
| 派单 / 决定优先级 | 参谋无指挥权（`draft/20` §3.1） | M（唯一召唤入口） |
| 改任何业务表 | 只读角色的写面是 `diagnoses` 一张表 | 各作业角色 |
| 解释"为什么失败"并给方案 | 那会把诊断变成计划，并让 O 失去独立判断的输入 | O / 该作业角色 |
| 评价角色的能力或排名 | 绩效口径只记事实（`draft/20` §8）；排名会激励隐藏困难 | — |

### N.4 工具面（设计 14 个；实测条数须在登记后由 `cli tools --role N` 读出）

复用（全部 `side_effect="read"`，名字取自 `cli tools --role C` 的实测输出）：

| 工具 | 用途 |
|---|---|
| `table.schema` / `table.list` / `table.count` / `table.get` / `table.search` | 读 `tasks`/`usage_ledger`/`eval_results` 与领域表 |
| `fs.read` / `fs.list` / `fs.search` | 读报告与产物文件 |
| `attack.status` / `attack.list_plans` | 读攻坚计划与子目标卡点（`blocked_reason` 的所在地） |
| `review.list_findings` | 读 H 的内容审核结论 |
| `verify.list_experiments` / `verify.evidence_for` | 读实验登记与已有证据 |

新增（1 个）：`mgmt.scan` —— 跑一次现状扫描，把结果写成一行 `diagnoses`（`side_effect="write_local"`，
写面登记为 `{"diagnoses"}`）。

### N.5 状态机

```text
idle ──(cycle 触发 / 用户点名)──► scanning
scanning ──读到完整数据──► diagnosed（coverage=complete）
scanning ──部分来源不可读──► diagnosed（coverage=partial，逐条列出缺哪一块）
scanning ──关键来源全不可读──► undiagnosed（coverage=unavailable，落一行说明）
diagnosed / undiagnosed ──► handed_off（交给 O；N 不参与后续）
```

**不变式**：`undiagnosed` 也必须落一行（"没查成"必须留痕，不是不留痕）。

### N.6 预算与终止条件

- 单次扫描的 token/墙钟上限由管理池给出（`draft/20` §13 S4+ 的 P4）；
  管理池有**自己的硬顶**（§12.3），超顶即停管理层，不停作业层。
- 终止条件：落下一行 `diagnoses`（三态之一）。**不许**因为"数据不好看"而重扫 ——
  重扫必须在诊断里写成一次独立的扫描记录，且计入管理池。
- 不许自旋：同一 `cycle_id` 的扫描最多一次；重扫需要新的触发原因。

### N.7 三态与失败模式

| 情形 | 必须的形态 |
|---|---|
| 某个来源读不到 | 该指标的 `coverage="unavailable"` + 一条 `unknowns`；**不许**省略该指标 |
| 数据自相矛盾（如 `tasks` 与 `usage_ledger` 不一致） | 两条都报，并各带 `source`；**不许**挑一个当真相 |
| 一个异常都没有 | 显式写 `anomalies: []` 且附"扫了哪些来源、各多少行"（零发现必须自证） |
| 扫描器自身坏了 | 抛错落 `undiagnosed`；**不许**返回空诊断（空集会被读成"一切正常"，P16） |

### N.8 不变式

| # | 不变式 | 判据 |
|---|---|---|
| N-I1 | 每个数字可追溯 | `metrics[*].source` 非空，且 Q 抽样重算能复现 |
| N-I2 | 完整性三态齐全 | 每条指标恰好一个 `coverage` 值 |
| N-I3 | 零发现自证 | `scanned_sources` 非空 |
| N-I4 | 只读 | 写集 == `{"diagnoses"}`（`READ_ONLY_WRITE_EXCEPTIONS` 登记） |
| N-I5 | 不重算权威口径 | 诊断里不出现从 `tasks.tokens` 求和的预算数 |

### N.9 接口

| 形态 | 签名（设计） | 说明 |
|---|---|---|
| 工具 | `mgmt.scan(cycle_id: str, window: str \| None) -> ToolResult` | 供 M/CycleRunner 调用 |
| 函数 | `agentflow.management.situation.mgmt_diagnose(store, *, cycle_id, window=None) -> dict` | 纯函数入口，便于自检与测试 |
| 落表 | `diagnoses`（1 行/次） | 主键 `diagnosis_id` |

### N.10 自检入口

`python -m agentflow.management.situation`（设计）—— 造一个含 `refused`/`blocked`/预算耗尽的
最小台账，断言诊断把它们逐条抓到，且 `coverage` 三态各出现一次。**未实现前不自称有自检。**

---

## O —— 计划官（Planning Officer）

### O.1 一句话定位

把一份**已落表**的诊断变成"目标 + 任务 + 资源 + 风险"的草案，交用户批准。
它是参谋：**只有建议权，没有派单权**。

### O.2 职责

| # | 职责 | 可判定判据 |
|---|---|---|
| O-1 | 只从 `diagnoses` 读现状（`diagnosis_id` 必填） | 计划里不出现原始表名；`diagnosis_id` 可解析 |
| O-2 | 出目标，且目标可判定 | 每条目标有 `criterion`（可判定）与 `falsifier`（否决项） |
| O-3 | 出任务草案 | 每条任务给 角色/动作/参数/预算；不写执行细节以外的内容 |
| O-4 | 出资源方案 | `allocation` 含 `pool`/`shares`/`reserve`/`lease_cycles`；每项 share 带 `basis_metric_ref` |
| O-5 | 落一行 `mgmt_plans` | 该表是 O 的**唯一**写面 |
| O-6 | 标出"证据不足"的部分 | 关键指标 `coverage ≠ complete` 时，计划必须 `provisional=true` 并列出探测任务 |

### O.3 明确不负责

| 不做 | 为什么 | 该由谁 |
|---|---|---|
| 派单 / 召唤任何角色 | 参谋无指挥权；派单权只在 M（`NON_SUMMONABLE` 的对称面） | M |
| 修改诊断 | 计划者改现状=自己给自己发论据 | N |
| 越过用户直接生效 | Q3=A：用户逐周期批准 | 用户 |
| 决定目标意图（"要解决什么"） | 目标意图归所有者 | 用户 |
| 自己评估计划是否合规 | 自查不是审核 | Q |

### O.4 工具面（设计 8 个；实测条数须在登记后由 `cli tools --role O` 读出）

复用：`table.schema` / `table.list` / `table.get` / `table.count`（读 `diagnoses`、`mgmt_plans`、`attack.*`）、
`fs.read`（读诊断附带的证据）、`attack.check_budget`（`[none]`，验证资源方案是否越界）、
`attack.pick_next_subgoal`（`[none]`，排序参考）。

新增（1 个）：`mgmt.plan` —— 产出计划草案并落 `mgmt_plans`（`side_effect="write_local"`，
写面登记为 `{"mgmt_plans"}`）。

### O.5 状态机

```text
idle ─► drafting（读 diagnosis，出草案）
drafting ─► proposed（provisional=false）
drafting ─► proposed_provisional（关键指标不完整，附探测任务）
proposed / proposed_provisional ─► approved（用户批准；Q3=A）或 rejected（用户否决）
approved ─► handed_off（交 CycleRunner 编译成 TaskCall）
```

**不变式**：只有用户能把 `proposed*` 变成 `approved`；O 自己**没有任何**路径写 `approved`。

### O.6 预算与终止条件

- 草案规模上限：任务条数 ≤ `Policy.max_tasks_per_run` 的剩余额度（不许提出一个注定被拒的计划）。
- 终止条件：落一行 `mgmt_plans`。**不许**反复重写同一 `diagnosis_id` 的计划：
  同一诊断的第二份计划必须带 `supersedes` 指向第一份（留痕，不是覆盖）。

### O.7 三态与失败模式

| 情形 | 必须的形态 |
|---|---|
| 诊断 `coverage="unavailable"` | 计划必须 `provisional=true` 且**不得**含高成本任务（先取证） |
| `metric_ref` 指向不存在的指标 | 计划**不许**落表（构造期拒绝，复用 `doc.compose_claim` 那种"构造时就抛"的形态） |
| 目标写不出 `criterion`/`falsifier` | 该目标不许进计划（"希望"不是目标） |
| 资源方案超出池子 | 拒绝落表并给出余量；不许"先写着" |

### O.8 不变式

| # | 不变式 | 判据 |
|---|---|---|
| O-I1 | 引用完整性 | `metric_ref ⊆ diagnosis.metrics.keys()`（新 verify 码 `plan_metric_ref_dangling`） |
| O-I2 | 目标可判定 | 每条目标 `criterion` 与 `falsifier` 均非空 |
| O-I3 | 参谋无指挥权 | 写集 == `{"mgmt_plans"}`；`ALLOWED_EDGES` 里 O 出边为空（不召唤任何人） |
| O-I4 | 不得自批 | `approved_by == "user"`；O 无法写该字段 |
| O-I5 | 资源守恒 | `Σ shares ≤ pool − reserve`，`reserve ≥ 10%` |

### O.9 接口

| 形态 | 签名（设计） | 说明 |
|---|---|---|
| 工具 | `mgmt.plan(diagnosis_id: str, intent: str) -> ToolResult` | 供 CycleRunner 调用 |
| 函数 | `agentflow.management.planning.mgmt_propose(store, *, diagnosis_id, intent, budget_view) -> dict` | 纯函数入口 |
| 落表 | `mgmt_plans`（1 行/份草案） | 主键 `mplan_id`；**不是** `plan_id`（`attack_plans` 已占，见 `draft/20` §12.6） |

### O.10 自检入口

`python -m agentflow.management.planning`（设计）—— 负控三连：野 `metric_ref` 必须抛；
缺 `falsifier` 的目标必须抛；`Σ shares > pool − reserve` 必须抛。**未实现前不自称有自检。**

---

## Q —— 内审（Internal Audit）

### Q.1 一句话定位

程序面的独立审计：越权、判据真空、自审、报告与台账不一致、阈值被绕过。
它**不改任何业务数据**，只登记结论并要求整改。

### Q.2 职责

| # | 职责 | 可判定判据 |
|---|---|---|
| Q-1 | 审程序：`ALLOWED_EDGES`/`READ_ONLY_WRITE_EXCEPTIONS`/`NON_SUMMONABLE` 是否被绕过 | 每条结论指向一个具体判据名 |
| Q-2 | 审续真空（P16）：判据是否在受检对象上真的执行过 | 抽样率必须自证（`sampled`/`sampled_of`） |
| Q-3 | 审自审：`auditor != producer`，`pass` 需 2 名独立同意 | 新 verify 码 `audit_self_review` |
| Q-4 | 审一致性：诊断报告与权威台账是否对得上 | 不一致时**两边都报**，并给 `source` |
| Q-5 | 落一行 `audits`，**先写结论再抄送** | `cc_at > verdict_at` 可机械检查（`draft/20` §12.2） |
| Q-6 | 长期 `unknown` 要升级 | 连续 2 个周期 `coverage="unavailable"` ⇒ 直报用户 |

### Q.3 明确不负责

| 不做 | 为什么 | 该由谁 |
|---|---|---|
| 改任何业务数据 | 内审一旦能改数据，独立性就不存在了 | 各作业角色 |
| 重写字面判据 | FC-03：判据只有一处实现；Q 只**引用** `verify`/`audit_task_ledger` 的判据 | verify / capabilities |
| 复核 H 的内容结论（引用、证据等级） | 那是 H 的权限面（`review_findings`）；Q 审的是"H 有没有证据"这类程序面 | H |
| 决定整改怎么做 | Q 只登记要求；方案归 O/M | O / M |
| 被 M 召唤 | 独立性要求 Q 不经 M 的调度链 | CycleRunner / 用户 |

### Q.4 工具面（设计 10 个；实测条数须在登记后由 `cli tools --role Q` 读出）

复用：`table.schema` / `table.list` / `table.get`（读 `tasks`/`audits`/`diagnoses`/`mgmt_plans`）、
`fs.read`、`review.list_findings`、`attack.list_plans`、
`verify.list_experiments` / `verify.evidence_for` / `verify.code_hash`。

新增（1 个）：`mgmt.audit` —— 跑一次程序审计并落 `audits`（`side_effect="write_local"`，
写面登记为 `{"audits"}`）。

### Q.5 状态机

```text
idle ─► auditing（抽判据、重算、比对）
auditing ─► concluded（三态结论 + evidence + 抽样自证）──► verdict_at 写下
verdict_at 之后 ─► cc_to_M ──► cc_at 写下（判据：cc_at > verdict_at）
concluded ─► escalated（连续 2 周期 unknown，或发现越权）
```

**不变式**：`verdict_at` 一写下即不可改写（复用主控 I-2"终态不可改写"的形态）。

### Q.6 预算与终止条件

- 审计的抽样量有上限（否则内审自己变成资源黑洞）；管理池硬顶同样适用。
- 终止条件：落一行 `audits`；"没查成"也必须落一行（`unknown`），不许沉默。
- 同一周期重复审计要新开一行（append-only），不许覆盖上一行。

### Q.7 三态与失败模式

| 情形 | 必须的形态 |
|---|---|
| 判据在受检对象上抽不到样本 | `verdict="unknown"` + `no_sample` + 理由（**不许**判 pass） |
| 发现不一致 | 两边都报，交用户；不替任何一边下结论 |
| Q 自己读不到数据 | `unknown` + 直报用户（内审停摆是最高优先级的信号之一） |
| 汇总项数为 0 | 必须自证"查了什么"，不许返回空结论集 |

### Q.8 不变式

| # | 不变式 | 判据 |
|---|---|---|
| Q-I1 | 无人可自审 | `auditor_role != producer_role`；`pass` 需 ≥2 名独立同意 |
| Q-I2 | 先结论后抄送 | `cc_at > verdict_at` |
| Q-I3 | 结论不可被 M 撤回 | `audits` append-only；M 的写集里没有 `audits` |
| Q-I4 | 抽样自证 | `sampled`/`sampled_of` 必填；为 0 时必须 `no_sample` |
| Q-I5 | 只引用判据 | Q 的代码里不出现判据的**第二份实现**（只调 `verify`/`audit_task_ledger`） |

### Q.9 接口

| 形态 | 签名（设计） | 说明 |
|---|---|---|
| 工具 | `mgmt.audit(cycle_id: str, subject: str) -> ToolResult` | 供 CycleRunner 调用；**不由 M 调用** |
| 函数 | `agentflow.management.audit.mgmt_audit_cycle(store, *, cycle_id, subject=None) -> dict` | 纯函数入口 |
| 落表 | `audits`（1 行/次，append-only） | 主键 `audit_id` |

### Q.10 自检入口

`python -m agentflow.management.audit`（设计）—— 负控三连：`auditor == producer` 必须被拒；
`pass` 只有 1 名同意必须被拒；抽样率为 0 却 `verdict="pass"` 必须被拒。
**未实现前不自称有自检。**

---

## 确定性周期驱动 `CycleRunner`（不是 LLM 角色）

| # | 项 | 内容 |
|---|---|---|
| 1 | 定位 | 管理层的执行器：**只执行给定的周期脚本**，不推理、不定目标、不改计划内容。与 `Conductor` 同构（`conductor.py:262` 的"确定性执行者"哲学） |
| 2 | 职责 | ① 按触发原因开周期 ② 调 N → 调 O ③ 收用户批准 ④ 把已批准计划编译成 `TaskCall` 交 `Conductor.run_plan` ⑤ 调 Q ⑥ 写周期报告 ⑦ 落 `cycles` |
| 3 | 不负责 | 目标、计划内容、资源方案的具体数字、审计结论 —— 四项全归别人 |
| 4 | 工具面 | **没有工具**：它是 Python 层驱动（同 M：`CAPABILITIES["M"] == ()` 的对称形态） |
| 5 | 状态机 | `opened → diagnosed → planned → approved → dispatched → audited → reported → closed/cancelled` |
| 6 | 预算与终止 | 周期数与并发有上限；管理池硬顶适用；**无批准不派单** |
| 7 | 三态 | 周期 `outcome ∈ {ok, no_result, refused, failed, cancelled}`（**复用** `schema.TASK_OUTCOMES`，不新造词表）；`unknown` 必须显式 |
| 8 | 不变式 | ① 无 `diagnosis_id` 不开计划 ② 无 `approved_by="user"` 不派单 ③ 派单唯一键 `(cycle_id, mgmt_plan_id, task_key)`（重入幂等） ④ 每周期恰好一份诊断与一份审计 |
| 9 | 接口 | `agentflow.management.cyclerunner.mgmt_run_cycle(store, *, trigger, cycle_id=None) -> dict`（设计） |
| 10 | 自检入口 | `python -m agentflow.management.cyclerunner`（设计）—— 负控：把同一周期跑两遍，断言 `tasks` 行数**不变**（幂等） |

---

## 交叉检查：七功能 × 管理侧角色（恰好一个执行者 P，无自监督）

| 功能 | N | O | Q | M | 用户 |
|---|---|---|---|---|---|
| 分析现状 | **P** | | C | | |
| 制定计划 | | **P** | C | | C |
| 派发任务 | | | C | **P** | |
| 交叉审核 | | | **P** | | C |
| 员工协作 | | **P** | C | | |
| 资源倾斜 | | **P** | C | | C |
| 状态更新 | **P** | | C | | |

机器可读副本（脚本按它断言）：

<!-- RACI-CHECK:BEGIN -->
```text
分析现状 | P=N | C=Q
制定计划 | P=O | C=Q,用户
派发任务 | P=M | C=Q
交叉审核 | P=Q | C=用户
员工协作 | P=O | C=Q
资源倾斜 | P=O | C=Q,用户
状态更新 | P=N | C=Q
```
<!-- RACI-CHECK:END -->

**监督矩阵（谁监督谁）**：A–H ← H（内容）/N（事实）/Q（程序）；M ← Q + N；N ← Q；
O ← Q + **M 的策略层**（越界即拒，`policy.check`）+ 用户（批准）；Q ← 用户。
对角元全部为空：**没有任何角色审自己**。

## 本文档声明为"新增"的名字（判据 B 的输入）

<!-- PROPOSED-NAMES:BEGIN -->
```text
proposed_tool:   mgmt.scan
proposed_tool:   mgmt.plan
proposed_tool:   mgmt.audit
proposed_func:   mgmt_diagnose
proposed_func:   mgmt_propose
proposed_func:   mgmt_audit_cycle
proposed_func:   mgmt_run_cycle
proposed_table:  diagnoses
proposed_table:  mgmt_plans
proposed_table:  audits
proposed_table:  cycles
proposed_field:  progress_state
proposed_field:  mgmt_plan_id
proposed_vocab:  PROGRESS_STATES
proposed_policy: management_pool_budget
proposed_role:   N
proposed_role:   O
proposed_role:   Q
```
<!-- PROPOSED-NAMES:END -->

## 本文件没能做到的（诚实边界）

| # | 内容 |
|---|---|
| 1 | 三个角色的**工具条数是设计值**，不是实测值：工具 `roles` 声明与 `READ_ONLY_WRITE_EXCEPTIONS` 登记完成后，必须以 `cli tools --role N/O/Q` 复算 |
| 2 | `X.10 自检入口` 全部是**设计**：本文档没有实现任何代码，因此三节都写着"未实现前不自称有自检" |
| 3 | 三节的 `X.9 接口` 里的函数名是**约定**：名字一旦进代码，`PROPOSED-NAMES` 块必须同步删除对应行（否则判据 B 会红 —— 那是刻意的） |
| 4 | 本文档**没有**改 `ROLE-SPECS.md`：角色登记是人审工作（S3 清单），合并时用同样的 10 小节顺序追加 |
