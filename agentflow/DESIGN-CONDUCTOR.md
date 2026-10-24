# 主控编队（Conductor）设计 —— v1.0

> ⚠️ **权威性（2026-10-18 标注）**：本文只回答「**当初为什么这么设计**」，**不是行为规格**。
> 与代码冲突时以代码为准；权威地图见 [`docs/INDEX.md`](docs/INDEX.md)。请只引「理由」，不引「行为」。
> 本文件是**正式版**（`D:\Incubator\agentflow\`）的核心设计之一。
> 它回答一个问题：**用户只对主控说话，主控按需召唤 A–H；A–H 之间也可以互相召唤；
> 其中一部分可以并发跑。这套东西在代码里长什么样？**
>
> 本文件是**设计理由**（"为什么这么设计"），**不构成判据**；与代码冲突处以代码为准。
> 框架的**权威现状描述与逐项路径索引**见
> [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)。
> 本文各节的实现落点（相对工作区根）：`agentflow/src/agentflow/conductor.py`（主控与 backend）、
> `agentflow/src/agentflow/policy.py`（上限与策略）、`agentflow/src/agentflow/capabilities.py`
> （**召唤边与写集的权威定义**）、`agentflow/src/agentflow/scheduler.py`（分波并发）、
> `agentflow/src/agentflow/cancellation.py`（协作式取消）、`agentflow/src/agentflow/schema.py`（`tasks` 表与 `REFUSAL_REASONS`）。

---

## 0. 与前三阶段的关系

前三阶段的 `pipeline.run_pipeline()` 是一条**固定顺序**的流水线
（实现：`agentflow/src/agentflow/pipeline.py::run_pipeline`）：
`C 分析 → D 消化 → A 检索 → B 抽取 → C 再分析 → …`。

它是对的，但它是**编排者写死的**，而不是**主控按情况决定的**。
本设计引入第四种东西：

| 层 | 是什么 | 谁决定 | 在哪 |
|---|---|---|---|
| **领域对象层** | 研究问题、难题攻坚计划、实验、稿件、依赖、审校发现 | 各角色 | `research_questions` / `attack_plans` / `experiments` / `documents` / `dependencies` / `review_findings`（表定义都在 `agentflow/src/agentflow/schema.py`） |
| **知识层** | 文献、概念、关系、引文 | A / B | `literature` / `concepts` / `relations`（同上） |
| **运行记录层** | **一次召唤**（谁召唤谁、为了什么、结果如何、花了多少） | 主控与所有角色 | **`tasks`**（本设计新增；在 `agentflow/src/agentflow/schema.py`） |
| **策略层** | 允许哪些召唤边、深度/扇出/并发/预算上限 | 人 + 主控 | 上限在 `agentflow/src/agentflow/policy.py`；**召唤边与写集在 `agentflow/src/agentflow/capabilities.py`** |

**把"运行记录"与"领域对象"分开，是这份设计最重要的一条取舍。**
上一阶段已经踩过一次同族问题：`AttackPlan` 的 docstring 里写着
"把攻坚塞进 `research_questions` 会让一个研究问题有四种互相打架的状态语义"。
召唤记录的性质与它们都不同 —— 它是**过程**，不是**结果**。

---

## 1. 角色与"召唤"的语义

### 1.1 主控 `M`

- **它是用户唯一面对的东西。** 用户说"帮我复现这篇论文"，主控负责：理解 → 拆解 → 召唤 → 汇总 → 报告。
- **它不是一个额外的"智能层"**：它不产出知识、不写关系、不改稿件。
  它的产出只有两类：**(a) 召唤**，**(b) 给用户的汇总**。
  这条约束让它可测试：主控的"正确性"= 它发出的召唤序列是否满足策略与预算，而不是"它聪不聪明"。
- **它在策略之内**：`M` 也在角色名单里（`schema.CONDUCTOR_ROLE`，实测在
  `agentflow/src/agentflow/schema.py`），"谁能召唤谁"的策略表对 M 同样生效。
  特例化会是权限模型最容易漏的地方。

### 1.2 A–H 既可以被动召唤，也可以主动召唤

- **被动**：`M → A`（用户让主控去检索）。
- **主动（同伴召唤）**：`D → C`（D 要问图上具体是什么情况）、`E → B`（E 发现引文不可核实，要 B 重抽取）、
  `F → A`（攻坚中发现新缺口要去查）、`H → G`（审校发现问题，请 G 修订）。
- **同伴召唤不是"自由发挥"**，它受三条约束（见 §3）：
  1. **边必须被策略允许**（`capabilities.ALLOWED_EDGES`，实测在
     `agentflow/src/agentflow/capabilities.py`；`policy.check_edge` 读的就是它）；
  2. **深度有限**（默认 3：`M(1) → A(2) → B(3)` 已到底）；
  3. **同一 `(role, action, input_key)` 不得在祖先链上重复**（防 A→B→A→B 的活锁）。

### 1.3 角色即"子智能体"，可以并发

用户的原话是"**有些角色的 Agent 可以并发。或者说这就是不同角色的 subagent**"。
落到代码上：**每个角色是一个可独立实例化、可并发调用的执行单元**。

- 我们的框架**不自己 spawn 进程**（那会让离线、确定性、可复现全部失守）。
  并发通过**有界线程池 + 每个角色一份独立的 `Store` 连接语义**实现，
  真正的隔离来自 `Store` 的文件锁与事务（那是它本来就有的能力）。
- 并发上限是**策略**而不是常量：`max_concurrency`（默认 4）。
- **可并发 / 不可并发的判据是"它们会不会写同一张表的同一批行"**：
  - 可并发：`M → (C 分析, E 实验, H 审校)` —— C 只读、H 只读、E 只写 `experiments`；
  - **不可并发**：两个 `B`（都写 `relations`，虽然事务是安全的，但语义上会让判重互相看不见）、
    两个 `G`（都写 `documents`）。
  - 实现方式：`capabilities.WRITE_SETS[role]` 列出该角色可能写的表
    （实测在 `agentflow/src/agentflow/capabilities.py`；**不在** `policy.py`）；
    **两张写集相交 ⇒ 串行**。这是**判据**，不是经验规则 —— 它可判定、可测。

---

## 2. 调用协议

```python
# 主控（或任何角色）这样召唤：
res = conductor.summon(
    "C",                       # 角色
    "paths",                   # 动作（该角色 capabilities() 里的一个）
    {"a": "0000", "b": "0001"},# 动作参数
    by="M",                    # 谁召唤的
    parent_task_id=None,       # 父任务（决定 depth 与判重链）
    budget={"max_tokens": 5000},
)
```

返回一个 **`SummonResult`**（**永远是结构化对象，永不抛业务异常**）：

```python
{
  "task_id": "t-0007",
  "role": "C",
  "action": "paths",
  "status": "done",              # pending|running|done|cancelled|failed
  "outcome": "ok",               # ok|no_result|not_applicable|refused|failed|cancelled
  "refusal_reason": None,        # outcome=refused 时必填（受控词表）
  "detail": "…",                 # 人可读
  "error": None,
  "payload": {...},              # 该动作的产出（由角色决定）
  "artifacts": ["analysis_reports:0003"],
  "tokens": 0, "usd": 0.0,
  "depth": 2,
  "elapsed_sec": 0.42,
  "children": ["t-0008"],        # 本次召唤又召唤出了哪些任务
}
```

### 2.1 为什么"拒绝"是 `status="done", outcome="refused"`

这是本设计里最容易写错、也最重要的一处。

- **`refused` 是一次成功的执行** —— 框架**正确地说了"不"**（越权 / 超预算 / 超深度 / 循环）。
  把它写成 `failed` 会让"策略拦住了"与"代码崩了"混在一起，而这两件事需要完全不同的处置。
- 反过来，**`ok` 也不等于"有结果"**：`outcome="no_result"` 表示"跑完了，确实没有"，
  `not_applicable` 表示"这个动作在当前状态下不适用（如没有待办）"。
- 于是 `status` 回答"**跑完了没有**"，`outcome` 回答"**跑出了什么**"。
  二者正交，六个组合都是**有意义且必须能区分**的。

> 这一条不是洁癖。本项目在**引文校验、OCR、D 溯源、C 预算截断**四处都踩过
> "把'没做'与'做了没结果'折叠成同一个值"的坑，每一次的后果都是
> **下游把'我们没查'读成了'查了没有'**。

### 2.2 三态在每个返回值上

`SummonResult.payload` 里凡是"查询"类动作，必须带 `checked` 位：

| 场景 | 禁止 | 要求 |
|---|---|---|
| 角色没有这个动作 | `refused` 里只写一句人话 | `refusal_reason="unknown_action"` |
| 动作没接线 | 抛异常 / 返回空 | `refusal_reason="not_wired"` |
| 查询无结果 | `payload={}` | `checked=True` + `empty=True` |
| 查询没法做 | `checked=True, empty=True` | `checked=False` + `reason` |

---

## 3. 策略（`agentflow/src/agentflow/policy.py`）

```python
@dataclass(frozen=True)
class Policy:
    max_chain_depth: int = 4          # 链长：台账 4 跳 = 链上 5 个代理（业主 2026-10-24 裁定）
    max_direct_children: int = 25     # 一个父能同时挂几个直接子（只数直接子，业主 2026-10-24）
    max_concurrency: int = 4           # 全局同时运行的任务数
    max_tasks_per_run: int = 200       # 一次 run 的召唤总数（生命周期总量）
    wall_clock_sec: float | None = 900 # 全局墙钟截止（FC-20）
    token_budget: int | None = None    # 全局 token 预算（FC-19，None = 不限）
    usd_budget: float | None = None    # 全局花销预算
```

**本机实测**：以上七个字段与默认值逐一与 `policy.Policy` 相同
（复跑：`python -c "import sys;sys.path.insert(0,'src');import dataclasses,agentflow.policy as p;[print(f.name,f.default) for f in dataclasses.fields(p.Policy)]"`）。

**四类上限必须同时存在**（FC-18）：
只有 `max_tasks_per_run`（总量）⇒ 瞬时可以把并发打爆；
只有 `max_concurrency`（瞬时）⇒ 扇出可以无限持续；
只有 `max_chain_depth` ⇒ 每一层都能无限宽；只有 `max_direct_children` ⇒ 链可以无限深。
**缺任一类，另三类都可以被绕过** —— 所以 `Policy.validate()` 要求四个都是正数，
且 `run` 启动时断言"四类都在"（完整性自检 `policy.assert_policy_complete`）。

### 3.1 允许的召唤边

`ALLOWED_EDGES: dict[str, frozenset[str]]` —— **谁能召唤谁，写在一处**。
它**不在 `policy.py` 里，而在 `agentflow/src/agentflow/capabilities.py`**
（`policy.check_edge` 读它）。实测 26 条召唤边，逐角色与下表逐条一致
（复跑：`python -c "import sys;sys.path.insert(0,'src');from agentflow import capabilities as C;print(sorted(C.ALLOWED_EDGES))"`）：

```
M → A B C D E F G H
A → B            # 检索完请 B 整理（A 不自己抽概念）
B → C            # 整理完请 C 看图的形状
C → (只读，不召唤任何人)      # ⚠️ C 是只读角色，它连"请求"都不直接发；见下
D → A B C E F    # 研究需要：补检索 / 重抽取 / 问图 / 做实验 / 立项攻坚
E → B D          # 实验失败/引文不可核实 → 请 B 重抽取；发现反例 → 回 D
F → A B C D E    # 攻坚需要一切
G → D E F        # 写稿时发现缺证据 → 回去要
H → G            # 审校发现问题 → 请 G 修订（H 不改稿）
```

**C 的边刻意是空的**，理由与"C 永远只读"同源：C 一旦能发起动作，
它就成了"绕过 B 引文回验"的写入路径。C 的 `candidate_gaps`/`structural_duplicates`
是**产出**，由 D 或编排层决定要不要变成请求。

**H 只能召唤 G**：审校者若能让别人改数据，它就同时是发现者与修正者。
（这条与"H 的写面钉死在两处登记例外上"是同一约束的两个面，都由结构保证：
`tools/base.py` 的 `for_role` 对只读角色一律剥掉写工具，放行的只有
`READONLY_CALL_EXCEPTIONS['H']` 那 4 件**该角色自己的落库代理**，外加
`UNIVERSAL_TOOLS` 里那 4 件通用能力（`clock.timer_start` / `clock.timer_cancel` /
`clock.alarm_start` / `conductor.ack` —— 业主 2026-10-26：「通用能力根本不该出现
谁能用这个说法」）。H 仍然拿不到任何 `fs.*` / `table.*` 写工具。）

### 3.2 循环与活锁

- **链长**：`depth > max_chain_depth` ⇒ `refused/depth_exceeded`。两种数法差一，
  两处都写清：业主数**链上的代理个数**（M W X Y Z ⇒ 5 个，第 5 个不能再派，业主 2026-10-24
  原话：「深度5的意思是假如M-W-X-Y-Z，Z就不能再派子代理」）；台账 `Task.depth` 数**跳数**
  （主控不落行，它的直接子 = 1）⇒ `max_chain_depth = 4` 跳 = 链上 5 个代理，
  换算只在 `policy.max_agents_on_chain`。这是结构闸门，不是成本闸门。
- **扇出**：一个任务名下的直接子达 `max_direct_children` 个（口径 = 单时刻在飞：被闸门拒掉、
  根本没跑的尝试照旧落台账但不占名额 —— 否则父任务触顶后就再也派不出活，且每次尝试再占一格＝自我毒化）
  ⇒ `refused/fanout_exceeded`。只数直接子，不管隔着几层的子（业主 2026-10-24：
  「12是只管直接子，不管隔着几层的子」）。上限按发起方角色取：默认档 = `policy.max_direct_children`（25），
  主控 `M` 一档 = 100（`policy.DIRECT_CHILDREN_LIMIT_BY_ROLE`，编排者一趟要派的活天然比工人多）。
- **判重**：`(role, action, input_key)` 若出现在**祖先链**上 ⇒ `refused/cycle_detected`。
  用 `input_key`（调用方给的输入指纹）而不是全部参数：参数里常有时间戳这类噪声，
  而"同样的问题问两遍"才是要防的事。
- **墙钟**：`deadline` 到了 ⇒ 新召唤一律 `refused/deadline_exceeded`，
  已在跑的**协作式取消**（见 §4）。

---

## 4. 取消（FC-20）

`agentflow/src/agentflow/cancellation.py`：

```python
class CancelToken:
    def cancel(self, reason: str) -> None: ...
    @property
    def cancelled(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    def raise_if_cancelled(self) -> None: ...   # 抛 CancelRequested
```

四条纪律（照 `04-…md` §B5 的 DSH 设计）：

1. **一个共享 signal 覆盖所有在飞与待启动的任务**（不是逐个取消 —— 逐个会漏）。
2. **终态先到先得**：`ended_at` 一旦写下就不再改写。因此"取消"与"完成"同时发生时，
   先写下的那个赢，另一个必须**什么都不做**（dispose 幂等）。
3. **每个 start 事件有且仅有一个 end 事件**：即使是被强杀或抛异常的任务，
   也必须合成一个 `cancelled` 的 end（否则台账里会有永远"在跑"的僵尸）。
4. **取消后不自动重试**，并把结果记成"**unknown outcome**"——
   一个被中途砍掉的实验**可能已经写了半张表**，声称它"失败"是过度声称。

---

## 5. 调度（`agentflow/src/agentflow/scheduler.py`）

极简、确定性：

```python
run_tasks(plan: Sequence[TaskCall], *, policy, conductor) -> list[SummonResult]
```

（实测该模块的三个公开入口：`run_waves` / `run_tasks` / `wave_summary`；
分波判据 `policy.waves_of`。）

- **波浪（wave）执行**：同一批里，**写集互不相交**的任务并发跑（线程池，上限 `max_concurrency`）；
  写集相交的**串行**。一个波浪全部结束再进下一波。
- **为什么用"写集"而不是"依赖图"**：依赖图需要每个动作声明前置，那会逼所有角色改签名；
  而写集是**从角色推出来的**（`WRITE_SETS`），零成本、可判定、可测。
  代价是它比真依赖图保守（可能少并发），但**保守的代价是多花时间，激进的代价是数据被改坏**。
- **确定性**：波浪内并发，但结果的**合并顺序按 `plan` 的输入顺序** ——
  于是"并发"不会让同一份输入产出不同的输出（可复现性优先于速度）。
- 每个任务完成后，**立刻**写 `tasks` 行（不攒到最后）：
  中途崩溃时台账必须已经能回答"它跑到哪一步了"。

---

## 6. 与 DSH（本会话的 harness）的关系

`Conductor` 有一个 `backend` 抽象：

| backend | 干什么 | 用在哪 |
|---|---|---|
| `LocalBackend` | 在进程内调用角色的 Python 实现（确定性、离线） | 测试、验收、可复现实验 |
| `SubagentBackend` | 把同一次召唤交给 DSH 的 `subagent` / `workflow` 工具（真 LLM 驱动） | 真实研究运行 |

**同一个角色规格同时驱动两种 backend**：`capabilities()` 声明动作与参数 schema，
两种 backend 都按它来。这条设计的价值在于：
**测试可以在离线、确定性的条件下覆盖编排逻辑**（谁召唤谁、预算怎么扣、取消怎么传播），
而"用 LLM 真的去想数学"这件事不进入测试的依赖。

---

## 7. 不变式（每一条都要有测试）

| # | 不变式 | 判据 |
|---|---|---|
| I-1 | 每个 `started_at` 有且仅有一个 `ended_at` | 扫 `tasks`：`status ∈ {done,cancelled,failed}` 的行 `ended_at` 非空；`running` 的行 `ended_at` 为空 |
| I-2 | 终态不可改写 | 对已结束任务再调 `finish()` ⇒ **零变更**（逐字节比对 `tasks.json`） |
| I-3 | 深度单调不减 | 子任务的 `depth` 恒等于父 `depth + 1` |
| I-4 | 拒绝必须带受控理由 | `outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS`（实测该词表在 `agentflow/src/agentflow/schema.py`，11 个取值） |
| I-5 | 并发度不超上限 | 峰值同时 `running` 的行数 ≤ `max_concurrency` |
| I-6 | 写集相交不并发 | 任一波浪内不存在两个任务写集相交 |
| I-7 | 预算耗尽后不再新开任务 | 预算用尽 ⇒ 后续召唤 `refused/budget_exceeded` |
| I-8 | 取消是协作式且不自动重试 | 取消后不产生新任务；被取消任务的 `outcome="cancelled"` |
| I-9 | 台账可重建 | `rebuild()` 后 `tasks` 表逐字节一致（FC-12） |
| I-10 | 结果合并顺序确定 | 同一 plan 跑两次，`SummonResult` 列表顺序相同（并发度不改变结果顺序） |

---

## 8. 待决问题

1. **主控自己的"思考"放哪？** 本轮：`M` 是**确定性的策略执行者**（不做 LLM 推理），
   "想做什么"由调用方给出 `plan`。真 LLM 主控由 `SubagentBackend` 承担（不在本轮测试范围）。
2. **跨会话恢复**：`tasks` 表的 `pending/running` 行在重启后如何处置？
   本轮：**不自动续跑**（僵尸 `running` 会被 `verify` 报出来，交人决定），
   因为"自动续跑一个可能已经写了半张表的任务"比重跑一遍危险。
3. **`WRITE_SETS` 的粒度**：本轮是**表级**（`documents` 互斥）。
   行级（两张不同的稿件可以并发写）留待需要时再做 —— 那时要有"行级锁"的判据。
