# 管理层设计的禁改区改动清单（移交人审）

> **这份清单是给"人"的移交件**，不是给我自己的待办。它把
> `../draft/20-管理层与责任链的重设计草案.md` §6.2 的落点、
> §12.5 的补漏项，以及 `SCHEMA-DRAFT-management.md` §8 的存储层落点，
> 压成一张**逐条可勾选**的表。
>
> **为什么需要它**：本设计有 6 类落点落在 FC-27 禁 AI 区（`schema.py` / `store.py` /
> `verify.py` / `tools/__init__.py` / `tools/base.py` …）。按 `AGENTS.md`：
> 命中的改动**必须由人编写或人逐行走查**，且需要 **2 名 reviewer** 批准
> （理由逐字："1 名 reviewer 与'作者自己再看一遍'在**结构上**无法区分"）。
> 我（AI）不能独自完成这些改动 —— 这份清单就是那条边界的具体位置。
>
> **判据**：`../temp/_verify_change_list.py` —— 解析本文件的机器可读块，
> 用 `scripts/noai_gate.py` 的 `check_paths()`（**同一个实现**，不是另写一份匹配逻辑）
> 逐条核对本清单自报的 `zone:` 是否与门的判定一致：
> `zone: yes` ⟺ 命中且 `required_approvals=2`；`zone: no` ⟹ 未命中。
>
> ⚠️ `noai_gate.py --git` 在本仓库**恒为 `unknown(2)`**（不是 git 仓库），
> 所以只能按路径判定；`unknown` 绝不能读成 `clean`。

---

## §0 两种改动，两类责任

| 类别 | 谁做 | 为什么 |
|---|---|---|
| `zone: yes`（禁改区） | **人**（编写或逐行走查 + 2 名 reviewer） | 错误的代价不可逆：schema 迁移毁数据、权限面错误 = 测试全绿上线即越权 |
| `zone: no`（区外） | AI 可写，但**必须在人审通过之后** | 区外的改动本身不危险，但它**依赖**禁改区的新角色/新表；先改区外会让代码引用不存在的角色（`assert_capabilities` 会在导入期直接抛） |

**执行顺序**：每条都标了 `batch:`。**第一批（P2）先做，门全绿之后再动第二批。**

---

## §1 第一批（P2：诊断上线）—— 14 条

| # | 路径 | 改什么 | zone | 谁 | batch |
|---:|---|---|:--:|:--:|:--:|
| 1 | `src/agentflow/schema.py` | `ROLES` 加 `N`/`O`/`Q`（**唯一名单**，`tools.ROLES` 是它的 import） | ✅ | 人 | 1 |
| 2 | `src/agentflow/schema.py` | `TABLES` 登记 `cycles` / `diagnoses`（`file`/`row`/`id_field`/`id_kind`） | ✅ | 人 | 1 |
| 3 | `src/agentflow/schema.py` | `ID_COUNTERS` 加 `cycle` / `diagnosis`（4 位空间） | ✅ | 人 | 1 |
| 4 | `src/agentflow/schema.py` | `ARRAY_FIELD_KINDS` + `row_from_dict` 分支（两张表 + `metrics` 嵌套） | ✅ | 人 | 1 |
| 5 | `src/agentflow/schema.py` | `Task` 加 `cycle_id` / `progress_state` / `progress_reason`（C6 交叉检查） | ✅ | 人 | 1 |
| 6 | `src/agentflow/schema.py` | 4 个新词表：`CYCLE_TRIGGERS` / `CYCLE_STAGES` / `COVERAGE` / `PROGRESS_STATES` | ✅ | 人 | 1 |
| 7 | `src/agentflow/store.py` | `LOCK_ORDER` 把两张新表追加在 `counters` **之前** | ✅ | 人 | 1 |
| 8 | `src/agentflow/tools/__init__.py` | `READ_ONLY_ROLES` 加 `N`/`O`/`Q`（只读角色权限面的**唯一声明点**） | ✅ | 人 | 1 |
| 9 | `src/agentflow/tools/base.py` | `for_role` 的**逐行走查**（逻辑不改，确认窄写面不被结构性剥离误伤） | ✅ | 人 | 1 |
| 10 | `src/agentflow/verify.py` | 第一批 2 条码 + 引用闭合：`failure_without_reported_difficulty`、`management_pool_overrun` | ✅ | 人 | 1 |
| 11 | `src/agentflow/capabilities.py` | `CAPABILITIES` / `WRITE_SETS` / `ALLOWED_EDGES` 加三行（导入期断言会立刻验） | ❌ | AI | 1 |
| 12 | `src/agentflow/capabilities.py` | `READ_ONLY_WRITE_EXCEPTIONS` 登记三个窄写面 `{diagnoses}` / `{mgmt_plans}` / `{audits}`（**必须带理由**） | ❌ | AI | 1 |
| 13 | `src/agentflow/policy.py` | 加 `management_pool_budget`（默认 `None` = 不限制，且必须显式说出"守卫没生效"） | ❌ | AI | 1 |
| 14 | `src/agentflow/management/situation.py`（新） | N 的扫描器 + 自检入口 | ❌ | AI | 1 |

## §2 第二批（P3/P5：计划与内审）—— 10 条

| # | 路径 | 改什么 | zone | 谁 | batch |
|---:|---|---|:--:|:--:|:--:|
| 15 | `src/agentflow/schema.py` | `TABLES` 登记 `mgmt_plans` / `audits` | ✅ | 人 | 2 |
| 16 | `src/agentflow/schema.py` | `ID_COUNTERS` 加 `mplan` / `audit` | ✅ | 人 | 2 |
| 17 | `src/agentflow/schema.py` | `ARRAY_FIELD_KINDS` + `row_from_dict`（两张表 + `allocation`/`objectives` 嵌套） | ✅ | 人 | 2 |
| 18 | `src/agentflow/schema.py` | `Task` 加 `mgmt_plan_id`（外键指向第二批表 —— 这正是它必须晚一批的原因） | ✅ | 人 | 2 |
| 19 | `src/agentflow/schema.py` | 3 个新词表：`PLAN_STATUSES` / `AUDIT_SUBJECTS` / `AUDIT_VERDICTS` | ✅ | 人 | 2 |
| 20 | `src/agentflow/store.py` | `LOCK_ORDER` 再追加两张 | ✅ | 人 | 2 |
| 21 | `src/agentflow/verify.py` | 第二批 3 条码：`plan_metric_ref_dangling`、`audit_self_review`、`audit_cc_before_verdict` | ✅ | 人 | 2 |
| 22 | `src/agentflow/capabilities.py` | `WRITE_SETS` 加 `mgmt_plans` / `audits` 的写集 | ❌ | AI | 2 |
| 23 | `src/agentflow/management/planning.py`（新） | O 的计划器 + 负控三连 | ❌ | AI | 2 |
| 24 | `src/agentflow/management/audit.py`（新） | Q 的审计器 + 负控三连 | ❌ | AI | 2 |

## §3 收尾（与批次无关，但必须与人审之后一起做）—— 8 条

| # | 路径 | 改什么 | zone | 谁 |
|---:|---|---|:--:|:--:|
| 25 | `src/agentflow/management/cyclerunner.py`（新） | 确定性周期驱动（幂等：同周期跑两遍 `tasks` 行数不变） | ❌ | AI |
| 26 | `src/agentflow/conductor.py` | `stats()` 的预算口径**删掉**从 `tasks` 求和的第二份实现，改读 `usage_ledger`（`draft/20` §6.4 删除清单第 1 条） | ❌ | AI |
| 27 | `src/agentflow/scheduler.py` | （可选）按波指定并发上限 —— 分支级资源倾斜的落点 | ❌ | AI |
| 28 | `src/agentflow/verify.py` | **删除**自带的 tasks 健康检查，改调 `capabilities.audit_task_ledger`（§6.4 删除清单第 2 条，P4 的正解） | ✅ | 人 |
| 29 | `tools/verify_role_specs.py` | 角色集合与文档路径改为可配置 —— 今天它写死 `[A-HMm]`，**新角色登记后它看不见 N/O/Q**（不报错 = 假通过，`draft/20` §12.5） | ❌ | AI |
| 30 | `docs/ROLE-SPECS.md` | 并入 N/O/Q 三节（10 小节同构）；收窄 §M.1 与 M-9/M-11 的对外语义 | ❌ | AI |
| 31 | `docs/PROPOSALS.md` | 登记本设计产生的待裁决项（管理池默认值、4 位 ID 额度、`SCHEMA_VERSION` 是否 +1） | ❌ | AI |
| 32 | `DEVELOPMENT.md` | 若需补一条 DoD（"新表必须声明登记批次"），按规范变更走同一个人审 | ❌ | AI |
| 33 | `src/agentflow/tools/brief_tools.py`（新） | §14 工具箱的 **15 个聚合工具**实装（按族拆模块：`brief_*` / `pack_*` / `harvest_*`）+ `ToolSpec.roles` 声明 | ❌ | AI |
| 34 | `src/agentflow/tools_expected.py`（新） | **每角色的预期工具名清单**基线快照 —— 补 `DEVELOPMENT.md` §9.2 记的 **FC-06** 缺口 | ❌ | AI |
| 35 | `src/agentflow/verify.py` | §14 的 **6 条工具箱码**：`plumbing_ratio` / `wasted_call_ratio` / `unused_tool` / `toolbox_span` / `fc06_expected_tools` / `empty_result_without_reason` | ✅ | 人 |
| 36 | `DEVELOPMENT.md` | 登记反模式 **P18**（让模型自己做机械劳动：算术/拼上下文/格式转换/多轮试探） | ❌ | AI |

---

## §4 人审时要**逐行走查**的符号（不是"扫一眼"）

`AGENTS.md` 允许两种合规形态：人**编写**，或人**逐行走查**并留下结论。
下面是把"逐行走查"落到具体符号上的清单 —— 审这几个，不必读整文件：

| 路径 | 要看的符号 | 看什么 |
|---|---|---|
| `schema.py` | `ROLES` / `TABLES` / `ID_COUNTERS` / `ARRAY_FIELD_KINDS` / `row_from_dict` / `Task.validate` | 新角色与新表是否**只有一处**声明；4 位空间是否够；嵌套 `from_dict` 是否覆盖 `metrics`/`allocation`/`objectives` |
| `store.py` | `LOCK_ORDER` / `Store.init` / `Store.rebuild` | 新表在 `counters` 之前；重建守恒 |
| `verify.py` | 5 条新码 + 6 条引用闭合 | 每条码是否真的会红（要有人写的负控） |
| `tools/__init__.py` | `READ_ONLY_ROLES` | N/O/Q 是否都在里面（参谋与内审不得有业务写权） |
| `tools/base.py` | `for_role` | 窄写面是否被"结构性剥离"误伤（H 的先例） |
| `scripts/noai_gate.py` | （不改） | 只是用它验本清单 —— `--paths` 的判定必须与本清单的 `zone:` 列一致 |

## §5 机械对账（本文档的自检）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python ..\temp\_verify_change_list.py            # 逐条比对 zone 列与门的判定
python scripts/noai_gate.py --paths src/agentflow/schema.py src/agentflow/store.py src/agentflow/verify.py `
    src/agentflow/tools/__init__.py src/agentflow/tools/base.py      # 应退 1，required_approvals=2
python scripts/noai_gate.py --paths src/agentflow/cli.py             # 应退 0（clean）—— 反向对照
```

## §6 这份清单**没能**做到的

| # | 内容 |
|---|---|
| 1 | 它**不是**批准记录：`AGENTS.md` 要求 2 名 reviewer 逐条 approve，那要写进 `.noai-approvals.json`（`--approve`），由人做，AI 不得代写 |
| 2 | 它**不判断**改动内容对不对 —— 那是 review 的职责；它只回答"哪些改动必须由人做" |
| 3 | `noai_gate.py --git` 在本仓库恒 `unknown`（非 git 仓库），因此**漂移检测**只能靠路径清单 + hash 台账 |
| 4 | 第 5、18 条（`Task` 加字段）会改变 `tasks` 表的磁盘形态：`SCHEMA_VERSION` 是否 +1 **未裁决**（`SCHEMA-DRAFT-management.md` §9 第 4 条） |

## 机器可读清单（判据的输入）

<!-- CHANGE-LIST:BEGIN -->
```text
item: 1  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: ROLES 加 N/O/Q
item: 2  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: TABLES 登记 cycles/diagnoses
item: 3  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: ID_COUNTERS 加 cycle/diagnosis
item: 4  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: ARRAY_FIELD_KINDS + row_from_dict
item: 5  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: Task 加三个字段
item: 6  | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 1 | action: 4 个新词表
item: 7  | path: src/agentflow/store.py               | zone: yes | who: human | batch: 1 | action: LOCK_ORDER 两张新表
item: 8  | path: src/agentflow/tools/__init__.py      | zone: yes | who: human | batch: 1 | action: READ_ONLY_ROLES 加三角色
item: 9  | path: src/agentflow/tools/base.py          | zone: yes | who: human | batch: 1 | action: for_role 逐行走查
item: 10 | path: src/agentflow/verify.py              | zone: yes | who: human | batch: 1 | action: 第一批 2 条码 + 引用闭合
item: 11 | path: src/agentflow/capabilities.py        | zone: no  | who: ai    | batch: 1 | action: 能力/写集/边 加三行
item: 12 | path: src/agentflow/capabilities.py        | zone: no  | who: ai    | batch: 1 | action: READ_ONLY_WRITE_EXCEPTIONS 登记
item: 13 | path: src/agentflow/policy.py              | zone: no  | who: ai    | batch: 1 | action: management_pool_budget
item: 14 | path: src/agentflow/management/situation.py | zone: no | who: ai   | batch: 1 | action: N 的扫描器（新）
item: 15 | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 2 | action: TABLES 登记 mgmt_plans/audits
item: 16 | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 2 | action: ID_COUNTERS 加 mplan/audit
item: 17 | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 2 | action: ARRAY_FIELD_KINDS + row_from_dict
item: 18 | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 2 | action: Task 加 mgmt_plan_id
item: 19 | path: src/agentflow/schema.py              | zone: yes | who: human | batch: 2 | action: 3 个新词表
item: 20 | path: src/agentflow/store.py               | zone: yes | who: human | batch: 2 | action: LOCK_ORDER 再追加两张
item: 21 | path: src/agentflow/verify.py              | zone: yes | who: human | batch: 2 | action: 第二批 3 条码
item: 22 | path: src/agentflow/capabilities.py        | zone: no  | who: ai    | batch: 2 | action: WRITE_SETS 加两张表
item: 23 | path: src/agentflow/management/planning.py | zone: no | who: ai    | batch: 2 | action: O 的计划器（新）
item: 24 | path: src/agentflow/management/audit.py    | zone: no  | who: ai    | batch: 2 | action: Q 的审计器（新）
item: 25 | path: src/agentflow/management/cyclerunner.py | zone: no | who: ai | batch: 0 | action: 周期驱动（新）
item: 26 | path: src/agentflow/conductor.py          | zone: no  | who: ai    | batch: 0 | action: stats() 删除第二份预算口径
item: 27 | path: src/agentflow/scheduler.py          | zone: no  | who: ai    | batch: 0 | action: 按波并发上限（可选）
item: 28 | path: src/agentflow/verify.py             | zone: yes | who: human | batch: 0 | action: 删除重复的 tasks 检查
item: 29 | path: tools/verify_role_specs.py          | zone: no  | who: ai    | batch: 0 | action: 角色集合可配置
item: 30 | path: docs/ROLE-SPECS.md                 | zone: no  | who: ai    | batch: 0 | action: 并入 N/O/Q 三节 + 收窄 M
item: 31 | path: docs/PROPOSALS.md                  | zone: no  | who: ai    | batch: 0 | action: 登记待裁决项
item: 32 | path: DEVELOPMENT.md                     | zone: no  | who: ai    | batch: 0 | action: DoD 补批次声明（若需要）
item: 33 | path: src/agentflow/tools/brief_tools.py | zone: no  | who: ai    | batch: 0 | action: 15 个聚合工具实装 + roles 声明
item: 34 | path: src/agentflow/tools_expected.py   | zone: no  | who: ai    | batch: 0 | action: 每角色预期工具名清单（补 FC-06）
item: 35 | path: src/agentflow/verify.py            | zone: yes | who: human | batch: 0 | action: §14 的 6 条工具箱码
item: 36 | path: DEVELOPMENT.md                     | zone: no  | who: ai    | batch: 0 | action: 登记 P18 反模式
```
<!-- CHANGE-LIST:END -->

<!-- PROPOSED-NAMES: NONE（本文件只声明**改动路径**，不声明新的代码标识符；
     路径的存在性由 `_verify_refs.py` 的判据 B'（待创建产物）负责） -->
### 附：本文件为什么不声明"拟新增标识符"

本清单关心的是**哪些路径要改**，不是**新代码里会出现哪些名字** ——
后者的唯一权威声明在 `SCHEMA-DRAFT-management.md` 与 `ROLE-SPECS-DRAFT-N-O-Q.md`
的 `PROPOSED-NAMES` 块里。这里显式写 `NONE` 而不是留空：
留空会让引用核对脚本把"判据 B 没查成"与"判据 B 不适用"混成同一件事。
