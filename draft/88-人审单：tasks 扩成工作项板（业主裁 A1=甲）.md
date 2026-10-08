# 88 · 人审单：`tasks` 扩成工作项板（业主 2026-10-08 裁 A1=甲）

> **这份是 FC-27 禁改区的送审材料**：改动落在 `src/agentflow/schema.py`
> （`[category: schema-migration]` + `[category: eval-criteria]`）。
> 按 `AGENTS.md`：**由人编写或人逐行走查 + 2 名 reviewer 批准**；**AI 不落盘、不自批**。
> 我（AI）能做的是：把"要加哪几列、每列的受控取值、每列的校验、对既有判据的影响、
> 以及要人逐行看的三问"写全，供人照着写或照着走查。

---

## §1 依据

- **业主 2026-10-08 晚（T16）**：「留言就塞 task_board，因为每句话都是需要有行为的，
  即使是光知道个信息也要确认读过再消掉。」
- **业主同日裁 A1=甲**（`draft/87` 的 A 组第 1 问）：给 `tasks` 加列 ⇒ **物理上真是一块板**。
- **A3=甲+seen**：空口 ack 的配对依据是 **`seen`（读过）**，不是 `claimed`（认领）——
  于是"读过"必须是盘上的一格，不能只靠内存。
- **A5=甲+重复升级**：同一项**重复空口 ack** 或**跨多步未读**时，升级为告警/阻塞 ⇒
  被判据需要的量有："谁在第几步读的"（`seen_by` / `seen_step`）。
- **A6=丙**：由父在派活时声明 `keep_alive` ⇒ 多一格。

---

## §2 提议的列（最小集，六格）

| 列 | 类型 | 受控取值 | 缺省 | 语义（一句话） |
|---|---|---|---|---|
| `kind` | `str` | `"delegation"` / `"message"` / `"report"` / `"notice"` | `""` | 空 = **老行 / 纯实例行**（不进板）；非空 = 板上的工作项 |
| `expects` | `str` | `"ack"` / `"work"` | `""` | 什么算做完（`kind` 非空时必填） |
| `item_state` | `str` | `"queued"` / `"claimed"` / `"seen"` / `"done"` | `""` | 工作项生命周期（**与 `status` 是两根轴**，见 §3） |
| `item_close` | `str` | `"acked"` / `"completed"` | `""` | `item_state=="done"` 时必填：是"知道了"还是"做完了" |
| `seen_by` | `str` | 实例号（`t-NNNN`）或空 | `""` | 谁读的（A3：渲染即 seen，记 **渲染它的那个实例**） |
| `seen_step` | `int \| None` | 步号 | `None` | 第几步读的（A5 的"跨多步未读"要靠它） |
| `keep_alive` | `bool` | `True` / `False` | `False` | A6 丙：父声明"这个实例做完一件还待命" |

**命名为什么带 `item_` / `seen_` 前缀**（这一条要人在走查时确认）：
`tasks` 上已经有 `status`（`pending/running/done`）与 `outcome`，它们说的是**实例**的生命周期；
板的工作项生命周期是**另一根轴**（一项可以"实例刚开始跑"而"还没被读过"）。
两根轴共用一个名字（例如把工作项状态也叫 `status`）就是把三态塌成一态的经典形态 ——
本仓为此吃过多次亏（`no_results` 折平 `retrieval_failed`、`delivered` 冒充 `read`）。

---

## §3 两根轴怎么共存（这是本次改动最容易写错的地方）

```text
实例轴（既有）：status = pending → running → done            （+ outcome / refusal_reason）
工作项轴（新）：item_state = queued → claimed → seen → done   （+ item_close）
```

对齐规则（提议，写进 `Task.validate` 或 `_write_new_row` 的注释）：

| 情形 | 实例轴 | 工作项轴 | 说明 |
|---|---|---|---|
| 老行（`kind==""`） | 照旧 | **五格全空** | **一个字节的行为都不变**（I-9：`rebuild` 后逐文件稳定） |
| `kind=="delegation"` | `pending/running/done` 照旧 | `queued`（开项）→ `claimed`（写 running 行时）→ `seen`（被读到时）→ `done` | 派活这一项与实例行**同一行**：`claimed` 与 `status=="running"` 同时发生 |
| `kind` ∈ {message, report, notice} | `pending` → `done`（`outcome="ok"`） | 同上（这两轴对它都成立，只是没有实例语义） | 它**不是**被"跑"出来的，是被"读/做"出来的 |

**一个必须写清的不变量**：`item_state=="claimed"` ⇒ `status ∈ {"pending","running"}`；
`item_state=="done"` ⇒ `status=="done"`。反向不成立（实例可以 done 而工作项还 `seen` 没 done ——
那就是"它读到了但没 ack"，正是 A5 要抓的形态）。

---

## §4 校验规则（提议，逐条给负控）

1. `kind == ""` ⇒ `expects/item_state/item_close/seen_by/seen_step` **必须全空**、`keep_alive is False`；
   （负控：老行硬塞一个 `item_state` ⇒ `validate` 抛）
2. `kind != ""` ⇒ `kind ∈ ITEM_KINDS`、`expects ∈ ITEM_EXPECTS`（负控：`expects="read"` ⇒ 抛）；
3. `item_state == "done"` ⇒ `item_close ∈ ITEM_CLOSES`；否则 `item_close == ""`；
4. `item_state == "seen"` ⇒ `seen_by` 非空（负控：只标 seen 不写 who ⇒ 抛）—— 这条是 **A3** 的机器形态；
5. `seen_step is None` ⇔ `seen_by == ""`；
6. `keep_alive is True` ⇒ `kind == "delegation"`（只有派活项才谈得上"待命"）。

词表落点（**两处必须同源**，这是本次人审的第二问）：词表常量建议放 `manuscripts.py`
（对齐 `KIND_REVISION` / `SEARCH_OUTCOMES` 的既有做法），`schema.py` 只做**校验引用**
（`from .manuscripts import ITEM_KINDS`）还是**自己再定义一份**？
—— 本仓的纪律是"同一受控词表只有一处定义"（`tests/test_claimanatomy.py` 那条
"六张词表在 schema 里各只有一处定义"的判据就是同族），所以建议：**定义在 `manuscripts.py`，
`schema.py` 引用它**；但 `schema.py` 不能 import `tools`（依赖方向），import `manuscripts`
是允许的（`manuscripts` 只依赖 `store/sessions`）。**请人在走查时确认这个依赖方向没问题。**

---

## §5 对既有判据与读数的影响（逐条，都要人过一眼）

| 地方 | 影响 | 处置 |
|---|---|---|
| `schema.SCHEMA_VERSION` | 加列 = 磁盘格式契约变更 | **抬一格**（人写）；不抬的话老盘新码会静默少校验 |
| `schema.TABLES["tasks"]` 的字段清单 | 多六格 | 人写；**同时**要改 `tests/test_schema*.py` 里钉字段清单的判据 |
| `rebuild()` / `Task.to_dict()` 的键顺序 | 新列必须**加在末尾**（键顺序影响 `rebuild` 后逐字节一致，I-9） | 人写；判据：老行 rebuild 前后逐字节相同 |
| `conductor.state` 的 `tasks` 格 / `tools` 的 `tasks` 计数 | 行数含义不变（板项也是行） | 不需要改；但**要在读数里分开"实例行"与"板行"**（新加一格，见 `draft/86` §2.2） |
| R011 词表普查（`tools/vocab_census.py`） | 新词表若**没有产出点**会被判死取值 | 六格词表的产出点就是 `append_item` / 状态迁移函数；人审第三问 |
| `verify_all` 的一致性审计 | 它读 `tasks` 行做不变量检查 | 人过一眼：新列的合法性由 `Task.validate` 保证，`verify` 不需要新增分支（除非人认为要） |
| 全量门的 `coverage_zero_test` | `schema.py` 的函数数变了 | 人写之后按既有流程重算（读数会漂，属于预期） |
| 金标 `agent_surface_snapshot` | 若 `tasks` 字段清单进了快照 ⇒ 会 diff | 人确认；进了就并进 D82 的重冻包 |

---

## §6 判据（红/绿 + 负控）—— 由 AI 写测试、人写实现

新增 `tests/test_task_board_columns.py`：

1. **老行不受影响**（最重要的反负控）：造一行老格式（`kind==""`）⇒ `validate` 通过、
   `rebuild` 前后**逐字节相同**、`conductor.board_view()` 里**不出现**它；
2. **开项 → claimed → seen → done** 四步各一条：每步的 `item_state` 都能从盘上读出来；
3. **负控（A3）**：只落 `seen` 不写 `seen_by` ⇒ `validate` 抛；
4. **负控（A5）**：同一项连续两次 ack（第二次是"空口"）⇒ 第二次必须落
   `ack_unbacked` 且**不改状态**（重复升级的判据见 §7）；
5. **负控（A6）**：`keep_alive=True` 落在 `kind!="delegation"` 上 ⇒ 抛；
6. **负控（I-9）**：新行写入后 `rebuild()` 两次，两次的 `tasks.json` 逐字节相同。

---

## §7 A5 的"重复升级"要落到哪（需要与实现一起定，但语义先写死）

业主裁的是「A5 甲+重复升级（同一项重复空口 ack 或跨多步未读时，升级为告警/阻塞）」。提议：

| 触发 | 落什么 | 强度 |
|---|---|---|
| 单项**一次**空口 ack | `ack_unbacked` 读数（进 `agent_*` 事件 + `conductor.board` 可见） | 告警（不改状态） |
| **同一项重复**空口 ack（同一实例 ≥2 次） | 同上 + 板上该项标 `needs_attention`（新读数格，**不加列**：由 `ack_unbacked` 计数推出来） | 告警升级 |
| **跨多步未读**（`item_state=="queued"` 且 `seen_step is None` 且该项已存在 ≥N 步；N 进 `settings.json`，建议 6） | 板上单列一栏 + 父的下一步提示里点名 | 告警升级 |
| 上一条在**同一项**上连续 ≥2 轮仍无人读 | 建议**阻塞**：该实例的下一步工具调用被拒（理由码 `item_unread_blocked`），直到它 ack 或父改派 | 阻塞（要人点头，因为它是**新增的拒绝路径**） |

**要人点头的那一格**：最后一档（阻塞）是新增的**拒绝路径** —— 它会改变模型的可用动作面
（`tools/base` 的调用期判据）。如果人认为"阻塞"太重，就退成"每轮都告警"。

---

## §8 人审三问（走查时请逐条给结论）

1. **列名与受控取值**是否与 `draft/85` §2.1 的口径一致（`queued/claimed/seen/done` +
   `acked/completed` + `expects ∈ {ack, work}`）？
2. **`SCHEMA_VERSION` 抬不抬**？（抬 = 磁盘契约变更、老盘要能被新码读；不抬 = 新列弱校验，
   一旦有坏行两边读法会分叉）
3. **六张词表的定义落点**：定义在 `manuscripts.py`、`schema.py` 引用（依赖方向 `schema → manuscripts`），
   并算作 R011 的有产出词表 —— 可以吗？
