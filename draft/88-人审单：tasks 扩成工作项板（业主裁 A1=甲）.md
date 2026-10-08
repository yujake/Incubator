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
- **A3=甲+seen**：空口 ack 的配对依据是 **`seen`（渲染 = 被读进某一步的提示词）**，
  不是 `claimed`（**接手** = 写 `running` 行那一刻）—— 于是"读过"必须是盘上的一格，
  不能只靠内存。
- **A5=甲+重复升级**：同一项**重复空口 ack** 或**跨多步未读**时，升级为告警/阻塞 ⇒
  被判据需要的量有："谁在第几步读的"（`seen_by` / `seen_step`）。
- **A6=丙**：由父在派活时声明 `keep_alive` ⇒ 多一格。

---

## §2 提议的列（**七格** ＝ 工作项轴六格 + 派活参数一格）

> **口径（业主 2026-10-08 晚）**：标题与全篇统一说 **七格**；
> 其中前六格是**工作项轴**（`kind` / `expects` / `item_state` / `item_close` / `seen_by` / `seen_step`），
> 第七格 `keep_alive` 是**派活参数**（A6=丙 要的，只有 `kind=="delegation"` 才谈得上）。
> 两类的区别在 §4 的校验里也体现：前六格互相有组合约束，`keep_alive` 只受 `kind` 约束。

| 列 | 类型 | 受控取值 | 缺省 | 语义（一句话） |
|---|---|---|---|---|
| `kind` | `str` | `"delegation"` / `"message"` / `"report"` / `"notice"` | `""` | 空 = **老行 / 纯实例行**（不进板）；非空 = 板上的工作项 |
| `expects` | `str` | `"ack"` / `"work"` | `""` | 什么算做完（`kind` 非空时必填） |
| `item_state` | `str` | `"queued"` / `"claimed"` / `"seen"` / `"done"` | `""` | 工作项轴：`claimed` = **接手**（写 `running` 行那一刻）、`seen` = **渲染**（被读进某一步的提示词）；**与 `status` 是两根轴**，见 §3 |
| `item_close` | `str` | `"acked"` / `"completed"` | `""` | `item_state=="done"` 时必填：是"知道了"还是"做完了" |
| `seen_by` | `str` | 实例号（`t-NNNN`）或空 | `""` | 谁读的（A3：**渲染即 `seen`**，记渲染它的那个实例） |
| `seen_step` | `int \| None` | 步号 | `None` | 第几步读的（A5 的"跨多步未读"要靠它） |
| `keep_alive` | `bool` | `True` / `False` | `False` | A6 丙：父声明"这个实例做完一件还待命"（只对 `kind=="delegation"` 有意义） |

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
6. **`expects` 与 `item_close` 的交叉校验（业主 2026-10-08 晚点名要补的一条）**：

```text
expects == "ack"   ⇒ item_close ∈ {"", "acked"}       # 只要"知道了"的项，不许被标成"做完了"
expects == "work"  ⇒ item_close ∈ {"", "completed"}   # 要交付的项，不许靠"知道了"收口
```

   为什么这一条必须有：`expects` 与 `item_close` 是**两个独立输入**，各自合法、合起来却是
   "用 ack 收了一件要交付的活"（或反过来）—— 那是本仓最忌的形态：**两个字段各自为真、
   合起来是假话**（同族先例：`status=done` + `outcome=refused` 必须成对校验，
   `no_results` 与 `retrieval_failed` 不许折平）。
   **负控**：`expects="ack"` + `item_close="completed"` ⇒ `validate` 抛；
   `expects="work"` + `item_close="acked"` ⇒ 抛；两条都要有（只写一条会让"反方向"漏过去）。
7. `keep_alive is True` ⇒ `kind == "delegation"`（只有派活项才谈得上"待命"）。

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
| **真机老行规模（实测）** | 59 个工作区共 **2276** 行；**没有一行有 `kind`/`expects`/`item_state`**；**没有一行处于 `pending`/`running`**（`done=2196 / failed=80`） | 迁移不需要逐行判断：`kind==""` 就是判据，且**没有中间态**要接管（证据：`draft/89` §1.2） |
| **`input_key` 不能占用（实测）** | 2276/2276 行非空，形态是 `<动作>@<12 位指纹>`（`revise@4b9122efd0dc`），而它是**循环判据的键**（`policy.check` 第 [4] 步） | 本次七格**一个都不碰 `input_key`**；`item_id` 就是 `task_id`（证据：`draft/89` §5.1） |
| **数组字段契约** | 七格全是标量（5×`str` + 1×`int|None` + 1×`bool`） | **不动 `ARRAY_FIELD_KINDS`**；若将来加数组列必须同笔登记（`tests/test_fc05_contract.py` 钉着） |
| `schema.SCHEMA_VERSION` | 加列 = 磁盘格式契约变更 | **抬一格**（业主已答）；夹具用的是 `S.SCHEMA_VERSION`（`tests/conftest.py:238` 等，**动态**，不会因抬版本而红），但 `tests/test_schema.py::test_validate_table_rejects_wrong_schema_version` 要同笔看 |
| `schema.TABLES["tasks"]` 的字段清单 | 多**七格** | 人写；**同时**要改 `tests/test_schema*.py` 里钉字段清单的判据 |
| `rebuild()` / `Task.to_dict()` 的键顺序 | 新列必须**加在末尾**（键顺序影响 `rebuild` 后逐字节一致，I-9） | 人写；判据：老行 rebuild 前后逐字节相同 |
| `conductor.state` 的 `tasks` 格 / `tools` 的 `tasks` 计数 | 行数含义不变（板项也是行） | 不需要改；但**要在读数里分开"实例行"与"板行"**（新加一格，见 `draft/86` §2.2） |
| R011 词表普查（`tools/vocab_census.py`） | 新词表若**没有产出点**会被判死取值 | 六张词表（`kind` / `expects` / `item_state` / `item_close` / 两格 `seen_*` 不是词表）的产出点就是板的状态迁移函数；人审第三问已答"算作有产出" |
| `verify_all` 的一致性审计 | 它读 `tasks` 行做不变量检查 | 人过一眼：新列的合法性由 `Task.validate` 保证，`verify` 不需要新增分支（除非人认为要） |
| 全量门的 `coverage_zero_test` | `schema.py` 的函数数变了 | 人写之后按既有流程重算（读数会漂，属于预期） |
| 金标 `agent_surface_snapshot` | 若 `tasks` 字段清单进了快照 ⇒ 会 diff | 人确认；进了就并进 D82 的重冻包 |

---

## §6 判据（红/绿 + 负控）—— 由 AI 写测试、人写实现

**照抄的先例**：上一次给 `tasks` 加列（`instance`，`draft/37` §16 P1）留下的模板就是
`tests/test_task_instance.py`（逐字：「I-9：加了 `instance` 这一栏之后，`rebuild()` 重建出的
`tasks.json` 必须逐字节不变」＋ 负控 ＋ 一条注释点明"往行字典里加键最容易踩的就是键序"）。
**本次的判据就按它那个形状写**（见 `draft/89` §4 的证据行）。

新增 `tests/test_task_board_columns.py`：

1. **老行不受影响**（最重要的反负控）：造一行老格式（`kind==""`）⇒ `validate` 通过、
   `rebuild` 前后**逐字节相同**、`conductor.board_view()` 里**不出现**它；
2. **开项 → claimed → seen → done** 四步各一条：每步的 `item_state` 都能从盘上读出来；
3. **负控（A3）**：只落 `seen` 不写 `seen_by` ⇒ `validate` 抛；
4. **负控（交叉校验，§4 第 6 条）**：`expects="ack"` + `item_close="completed"` ⇒ 抛；
   `expects="work"` + `item_close="acked"` ⇒ 抛（**两条都要有**）；
5. **负控（A6）**：`keep_alive=True` 落在 `kind!="delegation"` 上 ⇒ 抛；
6. **负控（I-9）**：新行写入后 `rebuild()` 两次，两次的 `tasks.json` 逐字节相同。

---

## §7 A5 的"重复升级"要落到哪（**首版不写阻塞档**，业主 2026-10-08 晚裁定）

业主裁的是「A5 甲+重复升级（同一项重复空口 ack 或跨多步未读时，升级为告警/阻塞）」，
并追加一句：**"阻塞"档首版不写**。⇒ 首版只有三档，**全是告警**（不新增任何拒绝路径）：

| 触发 | 落什么 | 强度 |
|---|---|---|
| 单项**一次**空口 ack（ack 与 `seen` 配不上） | `ack_unbacked` 读数（进 `agent_*` 事件 + `conductor.board` 可见 + `draft/85` §4 的 `board` 行硬事实） | 告警（**不改状态**） |
| **同一项重复**空口 ack（同一实例 ≥2 次） | 同上 + 板上该项标 `needs_attention`（**不加列**：由 `ack_unbacked` 计数推出来） | 告警升级 |
| **跨多步未读**（`item_state ∈ {queued, claimed}` 且 `seen_step is None` 且该项已存在 ≥N 步） | 板上单列一栏 + 父的下一步提示里点名 | 告警升级 |

**N 落 `settings.json`**（业主 2026-10-08 晚点名）：

```jsonc
{"board": {"unread_escalate_steps": 6}}     // 跨多少步还没被读到 ⇒ 升级为告警（默认 6）
```

**暂缓的那一档（写在这里备案，不在首版）**：同一项连续 ≥2 轮仍无人读 ⇒
该实例的下一步工具调用被拒（理由码 `item_unread_blocked`）。
暂缓的理由：它是**新增的拒绝路径**（会改变模型的可用动作面），
要先看到"三档告警在真机上够不够"（第一趟真机读数出来再定），
而且它与 T14/报告强制的落地顺序有耦合 —— 报告都没强制之前，用"阻塞"逼模型读信没有意义。

---

## §8 人审三问（走查时请逐条给结论）—— **业主 2026-10-08 晚已答**

| # | 问题 | 结论 |
|---|---|---|
| 1 | 列名与受控取值是否与 `draft/85` §2.1 的口径一致（`queued/claimed/seen/done` + `acked/completed` + `expects ∈ {ack, work}`）？ | **方向一致，同意**；**并补一条交叉校验**（`expects` × `item_close`，见 §4 第 6 条，含两条负控） |
| 2 | `SCHEMA_VERSION` 抬不抬？ | **抬**（磁盘格式契约变更；老盘要能被新码读） |
| 3 | 六张词表的定义落点：定义在 `manuscripts.py`、`schema.py` 引用（依赖方向 `schema → manuscripts`），并算作 R011 的有产出词表 —— 可以吗？ | **同意**（定义在 `manuscripts.py`，`schema.py` 引用） |

**⇒ 这三条答完，本单可以照 §2–§7 施工**（由人编写或人逐行走查 + 2 reviewer）。
**待办**：人签字后可动 `schema.py` 的那一笔（`SCHEMA_VERSION` + 七格 + §4 七条校验 + 字段清单判据），
之后 S1 由 AI 接（`conductor.py` / 工具面 / `agent_loop.py` / 提示词 / 状态报告）。
