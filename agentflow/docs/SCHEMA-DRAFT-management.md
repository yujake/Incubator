# 管理层数据模型（草案）—— 四张表 + `tasks` 三个新字段

> **性质**：字段级**设计**，不写代码。落点是 FC-27 禁改区（`schema.py` / `store.py` / `verify.py`），
> 因此本文档的用途是**给人审**：审过之后按 §5 的批次登记。
>
> **来源**：`../draft/20-管理层与责任链的重设计草案.md` §6（数据模型与变更账）、§12（九条裁决）、
> `ROLE-SPECS-DRAFT-N-O-Q.md`（三角色的写面）。**本文件只做一件事**：把字段定死，并让每一格都可判定。
>
> **判据**：`../temp/_verify_schema_draft.py` —— 解析本文档 §4 的机器可读字段块，断言：
> ① 每字段六属性齐全 ② §4.1 的 12 项与 §4.2 的 9 项都有处置 ③ **第一批字段里没有任何指向第二批表的外键**
> ④ Q6=B 与 Q8=C 的补偿控制在场 ⑤ 每条新 verify 码有正控与负控。负控：删掉任一属性 ⇒ 必须红。
>
> ⚠️ **更正一处在先的说法**：`draft/20` §13.3 写的"每字段过 §4.2 的 **DoD 六项**"是笔误 ——
> `DEVELOPMENT.md` §4 说的是"**六份** checklist"（§4.1 表 12 项 / §4.2 字段 9 项 / §4.3 工具 9 项 …）。
> 本文档按真实条目数（12 / 9）逐项处置，不再用"六项"这个错数。

---

## §1 范围与两个批次

| 批次 | 阶段 | 表 | `tasks` 新字段 | 词表 | verify 码 |
|---|---|---|---|---|---|
| **第一批** | P2（诊断上线） | `cycles`、`diagnoses` | `cycle_id`、`progress_state`、`progress_reason` | `CYCLE_TRIGGERS`、`CYCLE_STAGES`、`COVERAGE`、`PROGRESS_STATES` | `failure_without_reported_difficulty`、`management_pool_overrun` |
| **第二批** | P3 / P5（计划与内审） | `mgmt_plans`、`audits` | `mgmt_plan_id` | `PLAN_STATUSES`、`AUDIT_SUBJECTS`、`AUDIT_VERDICTS` | `plan_metric_ref_dangling`、`audit_self_review`、`audit_cc_before_verdict` |

**Q5=B 的裁决形式**：字段**一次设计完**（本文档包含两张批次的全部字段），
**登记分两批**（禁改区的人工成本按批次付：一次改动 = 人编写/逐行走查 + 2 名 reviewer）。

**批次规则（可机械检查）**：外键方向**只许从后批指向前批** —— 第一批字段的 `type` 里
不得出现 `→mgmt_plans` 或 `→audits`。理由：第一批登记完成时，第二批的表还不存在，
一个指向它的外键会让 `verify` 的悬空引用检查在**第一批刚落地的瞬间**就报错，
而那时无法通过"把第二批也登记了"来解决（那是人审流程，不是一次提交）。

**命名更正（`draft/20` §12.6）**：管理层计划表叫 `mgmt_plans`（主键 `mplan_id`），
`tasks` 上的外键叫 `mgmt_plan_id` —— `attack_plans.plan_id` 已经占了 `plan_id`
（`schema.py:1654`），且 `verify.py:439` 的 `dangling_plan_ref` 已经专指攻坚计划。

---

## §2 词表：新增还是复用（FC-03 要求逐条给理由）

> 立项时先把 `schema.py` 里现存的 **33 个受控词表**全列出来核过一遍（`grep '^[A-Z_]+ = ('`）。
> 下面每一条只回答一件事：**最近的既有词表是什么，差在哪**。

### 2.1 复用（不新增）

| 用在 | 复用的词表 | 为什么复用 |
|---|---|---|
| `cycles.status` | `TASK_STATUSES`（`schema.py:1260`） | 周期的推进态与任务同构（pending/running/done/cancelled/failed），且 `store` 的"终态不可改写"判据认这一套 |
| `cycles.outcome`、`audits.outcome` | `TASK_OUTCOMES`（`:1274`） | 含 `refused`/`not_applicable`/`no_result`，正是管理周期需要的三态面 |
| `diagnoses.confidence` | 既有 `CONFIDENCES`（high/medium/low） | 诊断的置信度与其它产出的置信度同义 |
| `*.created_by` / `auditor_role` / `producer_role` / `approved_by` | `ROLES`（`:1240`） | 角色码只有一处来源；`approved_by` 额外断言**只能**是 `"user"` |
| `*.quote`/`evidence` 的形态 | 沿用 `review_findings.evidence` 的既有规定（`schema.py:1213`"审校者的判断也需要证据"） | 不新造"证据必填"的第二套判据 |

### 2.2 新增（7 条，逐条给"最近的既有词表 + 差在哪"）

| 新词表 | 取值 | 最近的既有词表 | 差在哪（为什么不能复用） |
|---|---|---|---|
| `CYCLE_TRIGGERS` | `user` / `periodic` / `threshold` | 无 | 全库没有任何词表表达"这一轮是谁开的"；没有它就无法区分用户指令与系统自发（那正是 Q3=A 与阈值纪律的前提） |
| `CYCLE_STAGES` | `opened`/`diagnosed`/`planned`/`approved`/`dispatched`/`audited`/`reported`/`closed` | `TASK_STATUSES` | **正交维度**：一个周期可以 `status="running"` 同时 `stage="dispatched"`。把它塞进 `status` 会让本文档的 `status` 失去"终态"语义，而 `store` 的终态判据依赖那个语义 |
| `COVERAGE` | `complete` / `partial` / `unavailable` | `DEP_STATUSES`（closed/dangling/external_unavailable） | `DEP_STATUSES` 讲的是**依赖**闭合，不是**数据**完整性；把"这次没查成"记进依赖词表会让两种语义混在一起（P6） |
| `PROGRESS_STATES` | `ok`/`no_progress`/`blocked`/`needs_decision`/`needs_resource`/`needs_evidence`/`impossible_as_specified` | `SUBGOAL_STATUSES`（`schema.py:689`） | 后者的 `blocked` **只活在 F 的 `attack_plans.subgoals` 里**（`schema.py:982-983` 逐字"不许静默卡住"），与 `tasks` 派发链不连通。本词表就是把它**提升到执行层**；复用会让"谁卡住了"继续只有 F 内部知道 |
| `PLAN_STATUSES` | `proposed`/`proposed_provisional`/`approved`/`rejected`/`superseded` | `REPROCESS_STATUSES`（pending/done/rejected） | 缺 `approved`（Q3=A 的核心状态）、缺 `superseded`（O-I 不许覆盖前一份计划，只能取代） |
| `AUDIT_SUBJECTS` | `cycle`/`diagnosis`/`mgmt_plan`/`task`/`report`/`role` | 无 | 全库没有任何"受审对象种类"的词表 |
| `AUDIT_VERDICTS` | `pass`/`fail`/`unknown` | `FINDING_STATUSES`（open/fixed/wontfix/disputed） | 后者是**处置**（要不要修），不是**结论**；本词表要的是三态结论，且 `unknown` 必须与 `fail` 分开（三态纪律） |

> **不新增**：`AUDIT_STATUSES` 被砍掉了 —— 用复用的 `audits.outcome`（`TASK_OUTCOMES`）
> + 一个布尔 `escalated` 表达同一件事。少一个词表就少一处会漂移的地方。

---

## §3 DoD 逐项处置

### 3.1 `DEVELOPMENT.md` §4.1（新增/修改**表**，12 项）

| # | 检查项（原文摘要） | 本设计的处置 |
|---|---|---|
| 1 | `TABLES` 加 `{file, row, id_field, id_kind}`；`id_kind` 进 `ID_COUNTERS` | 四表各一行；`id_kind` = `cycle`/`diagnosis`/`mplan`/`audit`（4 位空间，见 §8） |
| 2 | 行 dataclass 有 `validate()`，每个受控字段都有词表校验 | §4 每个 `vocab:` 非 `-` 的字段都列进 §3.3 的校验清单 |
| 3 | `row_from_dict` 加分支（含嵌套 `from_dict`） | 4 张表 + 3 个嵌套结构（`metrics`/`allocation`/`objectives`）——见 §8 |
| 4 | 数组字段在 `ARRAY_FIELD_KINDS` 显式声明集合/序列 | 见 §8 的表；`audits.agreements` 是**集合**（升序去重），其余是**序列**（保序） |
| 5 | `store.empty_table()` / `Store.init()` 建文件 | 4 个 JSON 文件名按 `TABLES` 的 `file` 字段自动建（沿用既有机制） |
| 6 | `Store.rebuild()` 的事件重放支持该表 | 无事件重放的特殊要求；`rebuild` 守恒测试按 §4.1 第 9 项 |
| 7 | `verify.py` 加至少一条引用闭合检查 | 引用了别的表的字段：`diagnoses.cycle_id`、`mgmt_plans.cycle_id`/`diagnosis_id`/`supersedes`、`audits.cycle_id`、`tasks.cycle_id`/`mgmt_plan_id` —— 逐条给闭合码（§7） |
| 8 | 两条测试：合法行通过 / 违约束被拒 | 见 §7 每条判据的"正控/负控"（登记时落成 pytest 用例） |
| 9 | 重建守恒（逐字节 + 幂等） | 归入登记时的 `tests/test_rebuild.py` |
| 10 | `ROLE-SPECS.md` 对应角色 §状态机 补迁移表 | 由 `ROLE-SPECS-DRAFT-N-O-Q.md` 的 `X.5` 并入 |
| 11 | `capabilities.WRITE_SETS[role]` 更新 | N→`{diagnoses}`、O→`{mgmt_plans}`、Q→`{audits}`、M**不变**（`{tasks}`）；三者同时进 `READ_ONLY_WRITE_EXCEPTIONS` |
| 12 | `tests/test_fc05_contract.py` 数组契约测试 | `audits.agreements`（集合）与 `mgmt_plans.objectives`（保序）各一条 round-trip |

### 3.2 `DEVELOPMENT.md` §4.2（新增/修改**字段**，9 项）

| # | 检查项（原文摘要） | 本设计的处置 |
|---|---|---|
| 1 | "判定"类字段 ⇒ 三态 + `reason` 进受控词表 | `verdict`（三态）、`coverage_overall`（三态）、`progress_state`（含 `needs_evidence` 等"做不下去"的档）；三者的"说不清"档都有配对的 reason 字段（`no_sample_reason`/`progress_reason`） |
| 2 | 受控值词表定义在 `schema.py`，只此一处 | §2.2 的 7 个新词表全部落在 `schema.py`（linter R005 管"不许有第二份名单"） |
| 3 | "状态 ⟹ 其它字段"写成 `validate()` 交叉检查 | §3.3 的 6 条交叉检查 |
| 4 | 每条交叉检查有一条"违反应被拒"的测试 | §7 的负控 |
| 5 | 数组 ⇒ 在 `ARRAY_FIELD_KINDS` 声明 | 见 §8 |
| 6 | "有语义的顺序" ⇒ 与升序集合字段成对存在 | `mgmt_plans.objectives` 是**保序序列**（目标有优先级顺序）且**没有**配对的升序集合字段 —— 这是刻意的：复用 §4.2 第 6 项的豁免形态（该项目里 `chain`（保序）与 `related_relation_ids`（升序）成对是因为两者都有语义；这里只有一种顺序语义） |
| 7 | 保序字段有 round-trip 测试 | `mgmt_plans.objectives` / `tasks` 的 `progress_reason` 无顺序语义；`objectives` 落 round-trip 用例 |
| 8 | `ROLE-SPECS.md` 的状态机与三态更新 | 同 §3.1 第 10 项 |
| 9 | 更新 `DESIGN*.md` 字段表（可选，改了必须一致） | 本文件即字段表；登记时同步 `DESIGN-CONDUCTOR.md` 的字段表（若有冲突以代码为准并登记 §10 的处置流程） |

### 3.3 交叉检查（`validate()` 里的"状态 ⟹ 其它字段"）

| # | 交叉检查 | 违反时的行为 |
|---|---|---|
| C1 | `cycles.stage == "closed"` ⟹ `closed_at` 非空 且 `outcome` 非空 | 拒收（`ValueError`） |
| C2 | `mgmt_plans.status in {approved}` ⟹ `approved_by == "user"` 且 `approved_at` 非空 | 拒收 |
| C3 | `mgmt_plans.provisional is True` ⟹ `objectives` 里至少一条目标带 `needs_evidence` 类探测任务 | 拒收 |
| C4 | `audits.verdict == "pass"` ⟹ `len(agreements) >= 2` 且 `sampled > 0` | 拒收 |
| C5 | `audits.verdict == "unknown"` ⟹ `sampled == 0` 且 `no_sample_reason` 非空 | 拒收 |
| C6 | `tasks.progress_state != "ok"` ⟹ `progress_reason` 非空（与 `schema.py:982-983` 同形） | 拒收 |

---

## §4 字段规格（机器可读；本节的块是**唯一来源**）

> 每行六属性：`type` / `required` / `vocab` / `dod` / `why` / `guards`。
> - `vocab:` = `-`（无受控值）/ `名字`（复用） / `名字(new)`（新增，理由见 §2.2）
> - `dod:` 只列**适用**的 §4.2 条目号；不适用的条目由 §3.2 的表统一处置（不逐字段重复）
> - `type:` 里的 `→表` 表示外键目标（脚本用它检查批次方向）
> - `guards:` = "这个字段防的是什么错"；写不出这一格的字段**不该存在**

<!-- SCHEMA-FIELDS:BEGIN -->
```text
table: cycles | batch: 1 | pk: cycle_id | id_kind: cycle
field: cycles.cycle_id | type: str | required: yes | vocab: - | dod: 1 | why: 主键，把诊断/计划/审计归到同一轮 | guards: 无主键 ⇒ 三个新表无法归组，"这一轮"变成一句空话
field: cycles.opened_at | type: str(ISO) | required: yes | vocab: - | dod: - | why: 周期起点 | guards: 没有起点 ⇒ 无法判"超期"，也无法算管理开销的窗口
field: cycles.trigger | type: str | required: yes | vocab: CYCLE_TRIGGERS(new) | dod: 1,2 | why: 谁开的这一轮（用户/周期/阈值） | guards: 分不清用户指令与系统自发 ⇒ Q3=A 的批准链无从审计
field: cycles.trigger_detail | type: str | required: no | vocab: - | dod: - | why: 阈值触发时记下触发码 | guards: 阈值被绕过时看不出来（§7.2 的例外码只能从日志里猜）
field: cycles.goal_intent | type: str | required: yes | vocab: - | dod: - | why: 用户给的目标意图原文 | guards: 目标在传递中被改写而无人知晓
field: cycles.status | type: str | required: yes | vocab: TASK_STATUSES | dod: 3 | why: 推进态（复用既有终态语义） | guards: 第二份状态词表（P3/R005）
field: cycles.stage | type: str | required: yes | vocab: CYCLE_STAGES(new) | dod: 3 | why: 控制回路走到第几步（与 status 正交） | guards: 把"走到哪一步"塞进 status ⇒ 终态语义被污染
field: cycles.outcome | type: str | required: no | vocab: TASK_OUTCOMES | dod: 1,3 | why: 终态结论（含 refused/not_applicable） | guards: 把"没做"折叠成"做了没结果"
field: cycles.closed_at | type: str(ISO) | required: no | vocab: - | dod: 3 | why: 终态时间（终态不可改写） | guards: 周期永不结束（C1）
field: cycles.management_tokens | type: int | required: yes | vocab: - | dod: 3 | why: 本周期管理池花了多少 token（Q8=C 单列） | guards: 管理开销被藏进作业池，谁也看不见
field: cycles.management_usd | type: float | required: yes | vocab: - | dod: 3 | why: 同上（美元口径） | guards: 同上

table: diagnoses | batch: 1 | pk: diagnosis_id | id_kind: diagnosis
field: diagnoses.diagnosis_id | type: str | required: yes | vocab: - | dod: 1 | why: 主键 | guards: 计划无法指向"基于哪份现状"
field: diagnoses.cycle_id | type: str→cycles | required: yes | vocab: - | dod: 3 | why: 属于哪一轮 | guards: 诊断脱离周期 ⇒ 无法按轮审计
field: diagnoses.created_at | type: str(ISO) | required: yes | vocab: - | dod: - | why: 产出时间 | guards: 无法判断计划是基于"哪一时刻的现状"
field: diagnoses.window | type: str | required: yes | vocab: - | dod: - | why: 观测窗口（任务区间或"上一轮"） | guards: 复算时窗口不明 ⇒ 诊断不可复核
field: diagnoses.metrics | type: dict | required: yes | vocab: - | dod: 3,5 | why: 指标字典，每项 {value, source, coverage} | guards: 数字无出处（N-I1）；也是 O 只能引用它的前提
field: diagnoses.anomalies | type: list | required: yes | vocab: - | dod: - | why: 异常清单（可为空但必须显式） | guards: 空列表被读成"没问题"（P16）
field: diagnoses.unknowns | type: list | required: yes | vocab: - | dod: - | why: 未知清单（为空必须写"本次无未知项"） | guards: "没查成"被折叠成"查了没问题"
field: diagnoses.scanned_sources | type: list | required: yes | vocab: - | dod: - | why: 扫了哪些来源、各多少行 | guards: 零发现无法自证（N-I3）
field: diagnoses.coverage_overall | type: str | required: yes | vocab: COVERAGE(new) | dod: 1,2 | why: 整体数据完整性三态 | guards: 部分数据被当成完整数据用
field: diagnoses.confidence | type: str | required: yes | vocab: CONFIDENCES | dod: 2 | why: 诊断置信度 | guards: 第二份置信度词表
field: diagnoses.created_by | type: str | required: yes | vocab: ROLES | dod: 2 | why: 谁产出的（登记后为 N） | guards: 责任无处存放（D7）

table: mgmt_plans | batch: 2 | pk: mplan_id | id_kind: mplan
field: mgmt_plans.mplan_id | type: str | required: yes | vocab: - | dod: 1 | why: 主键（不叫 plan_id，见 §1） | guards: 与 attack_plans.plan_id 撞名（P6）
field: mgmt_plans.cycle_id | type: str→cycles | required: yes | vocab: - | dod: 3 | why: 属于哪一轮 | guards: 计划脱离周期
field: mgmt_plans.diagnosis_id | type: str→diagnoses | required: yes | vocab: - | dod: 3 | why: 基于哪份现状（唯一合法依据） | guards: O 凭印象规划（O-I1 的根）
field: mgmt_plans.created_at | type: str(ISO) | required: yes | vocab: - | dod: - | why: 产出时间 | guards: 无法判断计划晚于诊断（先有结论再找证据）
field: mgmt_plans.supersedes | type: str→mgmt_plans | required: no | vocab: - | dod: 3 | why: 取代哪一份旧计划 | guards: 覆盖式改写 ⇒ 计划历史消失（O 的自证链断裂）
field: mgmt_plans.objectives | type: list | required: yes | vocab: - | dod: 3,5,7 | why: 目标清单，每条 {text, criterion, falsifier} | guards: 目标不可判定或没有否决项（"希望"不是目标）
field: mgmt_plans.tasks | type: list | required: yes | vocab: - | dod: 5 | why: 任务草案（角色/动作/参数/预算） | guards: 计划与派单对不上账
field: mgmt_plans.allocation | type: dict | required: yes | vocab: - | dod: 3 | why: 资源方案 {pool, shares, reserve} | guards: 倾斜无依据（§5.6 判据 2）
field: mgmt_plans.risks | type: list | required: yes | vocab: - | dod: - | why: 风险清单（可为空但必须显式） | guards: 风险段被省略 ⇒ 无"已知会坏在哪"的记录
field: mgmt_plans.provisional | type: bool | required: yes | vocab: - | dod: 3 | why: 关键指标不完整时必须为真 | guards: 拿残缺现状做冒进计划（C3）
field: mgmt_plans.status | type: str | required: yes | vocab: PLAN_STATUSES(new) | dod: 1,2,3 | why: 草案/已批/被否/被取代 | guards: 分不清"用户批过"与"O 自己写了"（Q3=A）
field: mgmt_plans.approved_by | type: str | required: no | vocab: ROLES | dod: 1,3 | why: 只允许 "user" | guards: O 自批（O-I4；这是本项目"台账不能自批"的同一条原则）
field: mgmt_plans.approved_at | type: str(ISO) | required: no | vocab: - | dod: 3 | why: 批准时间 | guards: 批准链无时间 ⇒ 无法与派单时间对账

table: audits | batch: 2 | pk: audit_id | id_kind: audit
field: audits.audit_id | type: str | required: yes | vocab: - | dod: 1 | why: 主键（append-only） | guards: 审计结论被覆盖 ⇒ 内审历史消失
field: audits.cycle_id | type: str→cycles | required: yes | vocab: - | dod: 3 | why: 审的是哪一轮 | guards: 审计脱离周期 ⇒ 无法按轮追责
field: audits.subject_kind | type: str | required: yes | vocab: AUDIT_SUBJECTS(new) | dod: 1,2 | why: 受审对象种类 | guards: 无法统计"哪类对象从没被审过"
field: audits.subject_id | type: str | required: yes | vocab: - | dod: 3 | why: 受审对象代号 | guards: 结论悬空、无法回溯到具体对象
field: audits.created_at | type: str(ISO) | required: yes | vocab: - | dod: - | why: 结论写下时间 | guards: 与 verdict_at 混淆（见下）
field: audits.criterion | type: str | required: yes | vocab: - | dod: - | why: 引用判据名（不许重写判据） | guards: 判据出现第二份实现（FC-03/P4）
field: audits.verdict | type: str | required: yes | vocab: AUDIT_VERDICTS(new) | dod: 1,2,3 | why: 三态结论 | guards: 二态结论 ⇒ "没查成"被读成"通过"（P16）
field: audits.sampled | type: int | required: yes | vocab: - | dod: 3 | why: 实际抽了几条 | guards: 抽样率不可自证 ⇒ 抽样变成形式（Q-I4）
field: audits.sampled_of | type: int | required: yes | vocab: - | dod: 3 | why: 总体有多少条 | guards: 同上
field: audits.no_sample_reason | type: str | required: no | vocab: - | dod: 1,3 | why: 抽样为 0 的理由（必填当 sampled==0） | guards: "没抽"被写成"通过"（C5）
field: audits.evidence | type: list | required: yes | vocab: - | dod: 5 | why: 结论的证据（非空） | guards: 无证据的判断（与 review_findings.evidence 同一条规定）
field: audits.auditor_role | type: str | required: yes | vocab: ROLES | dod: 2,3 | why: 谁审的 | guards: 无人可自审的前提字段（Q-I1）
field: audits.producer_role | type: str | required: yes | vocab: ROLES | dod: 2,3 | why: 谁产出的 | guards: 无法判定自审（缺它则 Q-I1 判不出来）
field: audits.agreements | type: list | required: yes | vocab: ROLES | dod: 3,5 | why: 独立同意者（pass 时 ≥2） | guards: 1 名同意 ≡ 自审在结构上不可区分（AGENTS.md 的既有论证）
field: audits.verdict_at | type: str(ISO) | required: yes | vocab: - | dod: 3 | why: 结论定稿时间（Q6=B 的锚点） | guards: 无锚点 ⇒ 无法证明"先结论后抄送"
field: audits.cc_at | type: str(ISO) | required: no | vocab: - | dod: 3 | why: 抄送 M 的时间（Q6=B） | guards: 抄送早于结论 ⇒ M 可以预先解释掉（§12.2）
field: audits.outcome | type: str | required: no | vocab: TASK_OUTCOMES | dod: 1,3 | why: 整改的终态（复用词表，不新增 AUDIT_STATUSES） | guards: 第三份状态词表
field: audits.escalated | type: bool | required: yes | vocab: - | dod: 3 | why: 是否已升级给用户 | guards: 长期 unknown 沉默下去（Q-6）

table: tasks | batch: 1 | pk: task_id | id_kind: task
field: tasks.cycle_id | type: str→cycles | required: no | vocab: - | dod: 3 | why: 这次召唤属于哪一轮（用户直派可为空） | guards: 任务无法归轮 ⇒ 责任链断裂（D7）
field: tasks.progress_state | type: str | required: yes | vocab: PROGRESS_STATES(new) | dod: 1,2,3 | why: 执行层的困难上报（默认 ok） | guards: 子智能体无法说"我做不下去"（D5/D9）；也是新 verify 码的判据源
field: tasks.progress_reason | type: str | required: no | vocab: - | dod: 1,3 | why: progress_state ≠ ok 时的理由（必填） | guards: 静默卡住（与 schema.py:982-983 同形）

table: tasks | batch: 2 | pk: task_id | id_kind: task
field: tasks.mgmt_plan_id | type: str→mgmt_plans | required: no | vocab: - | dod: 3 | why: 由哪份管理计划授权（用户直派可为空） | guards: 计划外派单无处追溯（§5.3 判据 1）
```
<!-- SCHEMA-FIELDS:END -->

**统计**（实测自 `../temp/_verify_schema_draft.py`）：4 张新表 + `tasks`；字段 **57 条**
（第一批 25 条、第二批 32 条 —— `tasks` 的三个字段分属两批，所以块里 `tasks` 出现两次）。

---

## §5 批次验收：前向外键必须为 0

| 检查 | 判据 |
|---|---|
| 第一批字段里没有指向第二批表的外键 | 第一批字段的 `type` 中不含 `→mgmt_plans`、`→audits`（脚本按 `batch:` 分组断言） |
| 第二批可以指向前批 | `mgmt_plans.cycle_id→cycles`、`mgmt_plans.diagnosis_id→diagnoses`、`audits.cycle_id→cycles`、`tasks.mgmt_plan_id→mgmt_plans`（批内） |
| 表内自引用 | 只有 `mgmt_plans.supersedes→mgmt_plans`（第二批内），登记时 `verify` 需要一条"自引用悬空"检查 |
| 第一批登记完成时 `verify` 应当零 error | 那时 `mgmt_plans`/`audits` 还不存在，而**没有任何字段指向它们** ⇒ 悬空引用检查不会误报 |

---

## §6 两条"与建议不一致"裁决的落地（Q6=B / Q8=C）

### 6.1 Q6=B（Q 向用户汇报并抄送 M）的三条补偿控制

| # | 判据 | 字段/机制 | 正控 | 负控 |
|---|---|---|---|---|
| 1 | `cc_at > verdict_at` | `audits.verdict_at` / `audits.cc_at` + verify 码 `audit_cc_before_verdict` | `verdict_at=10:00, cc_at=10:05` ⇒ 不报 | `cc_at=09:55` ⇒ error |
| 2 | M 对 `audits` **无写权** | `capabilities.WRITE_SETS["M"] == {"tasks"}`（既有事实，登记新角色时不得放宽） | 断言 M 的写集不含 `audits` | 若有人给 M 加 `audits` ⇒ 导入期断言/契约测试红 |
| 3 | 结论不可撤回 | `audits` append-only；`verdict_at` 一写即终态（复用主控 I-2"终态不可改写"） | 二次写同一 `audit_id` ⇒ 拒 | 允许改写 ⇒ 判据红 |

### 6.2 Q8=C（管理开销单独预算池）的三条补偿控制

| # | 判据 | 字段/机制 | 正控 | 负控 |
|---|---|---|---|---|
| 1 | 管理池有**自己的硬顶** | `Policy.management_pool_budget`（新字段） | 池内花费 < 硬顶 ⇒ 管理层继续 | 超硬顶 ⇒ 管理层停（不是作业层停） |
| 2 | 管理开销**单列**且可对账 | `cycles.management_tokens/_usd` 与 `diagnoses.metrics["management_overhead"]` 必须相等 | 两处相等 ⇒ 不报 | 两处不等 ⇒ error（同 `tasks.tokens` vs `usage_ledger` 的既有形态） |
| 3 | 两池之和 ≤ 总预算 | verify 码 `management_pool_overrun` | `管理 + 作业 ≤ 总预算` ⇒ 不报 | 超出 ⇒ error |

---

## §7 新增 verify 码（每条配正控与负控）

| # | code | 判据 | 正控（不许报） | 负控（必须报） | 批次 |
|---|---|---|---|---|---|
| 1 | `failure_without_reported_difficulty` | `tasks` 终态 `failed`，且该任务生命周期内**没有任何**非 `ok` 的 `progress_state` | 失败前有 `progress_state="blocked"` + reason ⇒ 不报 | 直接 `failed`、全程 `ok` ⇒ error | 第一批 |
| 2 | `management_pool_overrun` | `Σ(管理池 + 作业池) ≤ 总预算`；且 `cycles.management_tokens` 与 `diagnoses.metrics["management_overhead"]` 相等 | 两池之和为总预算的 80% ⇒ 不报 | 之和为 105% ⇒ error；两处数字不一致 ⇒ error | 第一批 |
| 3 | `plan_metric_ref_dangling` | `mgmt_plans` 每个 `metric_ref` ∈ 其 `diagnosis.metrics` 的键集 | 引用一个真实存在的指标键 ⇒ 不报 | 引用 `metrics["不存在"]` ⇒ error | 第二批 |
| 4 | `audit_self_review` | `auditor_role != producer_role`，且 `verdict=="pass"` 时 `len(agreements) >= 2` | 两个独立角色、2 名同意 ⇒ 不报 | `auditor == producer` ⇒ error；`pass` 但只有 1 名同意 ⇒ error | 第二批 |
| 5 | `audit_cc_before_verdict` | `cc_at` 为空或 `cc_at > verdict_at` | `cc_at` 为空（还没抄送）⇒ 不报 | `cc_at <= verdict_at` ⇒ error | 第二批 |

**另外三条引用闭合检查**（§4.1 第 7 项要求）：`diagnoses.cycle_id`、`mgmt_plans.cycle_id`/`diagnosis_id`、
`audits.cycle_id` 各一条"指向不存在的主键"检查；`mgmt_plans.supersedes` 与 `tasks.mgmt_plan_id`
（第二批）各一条。它们沿用既有的 `dangling_*` 命名惯例，**不复用** `dangling_plan_ref`（那个名字已属攻坚计划）。

---

## §8 与存储层的接口（登记时的必改点）

| # | 落点 | 内容 | 禁改区 |
|---|---|---|---|
| 1 | `schema.TABLES` | 4 行（`file`/`row`/`id_field`/`id_kind`） | ✅ schema-migration |
| 2 | `schema.ID_COUNTERS` | `cycle`/`diagnosis`/`mplan`/`audit` 四个 kind（4 位空间，与既有 12 种同空间 ⇒ 受 4 位上限判据约束） | ✅ |
| 3 | `schema.ARRAY_FIELD_KINDS` | `diagnoses.anomalies`（序列）、`diagnoses.unknowns`（序列）、`diagnoses.scanned_sources`（序列）、`mgmt_plans.objectives`（序列）、`mgmt_plans.tasks`（序列）、`mgmt_plans.risks`（序列）、`audits.evidence`（序列）、`audits.agreements`（**集合**：升序去重） | ✅ |
| 4 | `schema.row_from_dict` | 4 个表分支 + 3 个嵌套 `from_dict`（`metrics`/`allocation`/`objectives`） | ✅ |
| 5 | `store.LOCK_ORDER` | 4 张表追加在 `counters` **之前** | ✅ |
| 6 | `policy.Policy` | 新字段 `management_pool_budget`（默认 `None` = 不限制 ⇒ 与既有 `token_budget` 同一形态，且**同样要显式说出"守卫没生效"**） | ❌（非禁改区） |
| 7 | `capabilities.WRITE_SETS` / `READ_ONLY_WRITE_EXCEPTIONS` | N/O/Q 的窄写面登记（**必须带理由**，`capabilities.py:956-962` 断言） | ❌ / 前者非禁改区，后者同文件 |
| 8 | `verify.py` | 5 条新码 + 6 条引用闭合 | ✅ auth-audit |

---

## §9 没能做到的（诚实边界）

| # | 内容 |
|---|---|
| 1 | 本文档**没有**实现任何代码；§7 的"正控/负控"是**设计**，登记时才落成 pytest 用例 |
| 2 | `management_pool_budget` 的**默认值**没有定：与既有 `token_budget` 一样默认 `None`（= 不限制）。`None` 意味着"资源倾斜"没有可倾斜的硬顶 —— 这是 P0-2 的待办，不是本文档能定的 |
| 3 | 4 位 ID 空间的**剩余额度未核算**：四个新 kind 与既有 12 种共用 `NNNN`，是否能容纳预期周期数**未验证**（登记前应算一次，`verify` 有 `id_gap`/`counter_overflow` 判据可复用） |
| 4 | **迁移**未设计：`SCHEMA_VERSION` 是否要 +1、老库如何升到含 `progress_state` 的形态 —— 按 `schema.py` 的既有理由（迁移是禁改区、错误不可逆），这一条要由人在登记时裁决 |
| 5 | 本文档**没有**改 `DEVELOPMENT.md` 的 §4.1/§4.2：登记时若发现 DoD 本身需要补充（例如"新表必须声明批次"），那属于规范变更，走同一个人的审批 |

## 本文档声明为"新增"的名字（判据 B 的输入）

<!-- PROPOSED-NAMES:BEGIN -->
```text
proposed_table:  cycles
proposed_table:  diagnoses
proposed_table:  mgmt_plans
proposed_table:  audits
proposed_field:  cycle_id
proposed_field:  diagnosis_id
proposed_field:  mplan_id
proposed_field:  audit_id
proposed_field:  progress_state
proposed_field:  progress_reason
proposed_field:  mgmt_plan_id
proposed_vocab:  CYCLE_TRIGGERS
proposed_vocab:  CYCLE_STAGES
proposed_vocab:  COVERAGE
proposed_vocab:  PLAN_STATUSES
proposed_vocab:  AUDIT_SUBJECTS
proposed_vocab:  AUDIT_VERDICTS
proposed_vocab:  PROGRESS_STATES
proposed_policy: management_pool_budget
proposed_code:   failure_without_reported_difficulty
proposed_code:   management_pool_overrun
proposed_code:   plan_metric_ref_dangling
proposed_code:   audit_self_review
proposed_code:   audit_cc_before_verdict
```
<!-- PROPOSED-NAMES:END -->
