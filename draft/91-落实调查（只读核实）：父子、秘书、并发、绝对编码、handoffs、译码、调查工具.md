# 91 · 落实调查（只读核实）：父子、秘书、并发、绝对编码、handoffs、译码、调查工具

> 目的：把 `draft/90` 那一套（名册 + 对照表 + 接线员 + 退役三分支 + 消息两个方向）
> **落到现有系统的真实结构上**。本页只读核实，每条结论都带 `文件:行`；
> 末尾给出"每一条落到哪个批次"与"新查出的出入"。
>
> 查法（全部只读，命令在 §0）；没有跑任何写操作、没有改代码。

---

## §0 怎么查的（可复现）

```powershell
# 秘书：职责表 / 台账文件 / 协商 / 手稿三件 / 读面
Select-String -Path src\agentflow\secretary.py -Pattern '^\| [0-9]|decisions_path|def negotiate|def handoff_add|self\.store\.'
# 取号与建行：唯一临界区
#   （读 conductor.py:813-862 的 _write_new_row；store.py:306 的 alloc_id；store.py:65 的 LOCK_ORDER）
# 并发：ThreadPoolExecutor 与波次
Select-String -Path src\agentflow\scheduler.py -Pattern 'def run_waves|ThreadPoolExecutor|max_concurrency'
# 会话追加的锁（house pattern）
Select-String -Path src\agentflow\sessions.py -Pattern 'FileLock|_append_lock|def append'
# 会话追加 vs 秘书台账：秘书那一处用的是裸 path.open("a")
```

---

## §1 父子代理的真实实现

- **一次召唤的完整链条**（父 → 子）：模型发出 `summon` 形状 → `agent_loop._do_summon`
  → `conductor.summon`（`conductor.py:1556`）→ 第 [5] 步 `_write_new_row`
  （`:1807`，写 `status="running"` 的**代理行**，`parent_task_id` = 父的绝对编码）
  → 第 [6] 步 `self.backend.call(role, action, params, token=…, task_id=tid)`（`:1821`）
  → `LlmBackend.call`（`agent_loop.py:3056` 起）**新建一个 `AgentLoop`** 并**同步**跑完这个子代理
  → 返回后父的调用栈写子行终态（`_end_from_payload` → `finish`，`:2233`）。
- **同步、同进程**：子代理不是进程，是一次同步调用（`LlmBackend.call` 内 `loop.run(...)`）。
  **一进程一顶趟**：只有顶趟在 `stopctl.register_pid` 登记（`agent_loop.py:1776`）。
  `SubagentBackend`（把召唤交给外部 harness）**未接线**，它显式返回 `refused/not_wired`
  （`conductor.py:355` 的类注释逐字："本轮未接线"）。
- **子代理拿到什么身份**：`run(..., my_task_id=<绝对编码>, depth=…)`；
  提示词里 `{{task_id}}` = 绝对编码，`{{parent_task_id}}` = 父的绝对编码（S1d 加的）。
  ⇒ **两侧的"身份"今天都是绝对编码**，没有本地名（`draft/90` E16/E17/E18）。
- **父子关系的唯一载体**：子行自己的 `parent_task_id`（边不落表）。
  `_children_of` / `_in_flight_children_of`（`conductor.py:650/676`）是它唯一的读侧。

## §2 秘书的真实实现与读写权限

- **职责表**（`secretary.py:15-18`，四项）：① 格式与内容优化（发件方，`optimize_outbound`）
  ② 委派评估（发件方，`assess_delegation`）③ 闭环提醒（收件方，`remind_closure`）
  ④ 委托加工（收件方，`rework_inbound`）；手稿通道另有增 / 改 / 查三件
  （`handoff_add` / `handoff_revise` / `handoff_query`，`:1057/1082/1108`）。
- **装配点（一实例一秘书的唯一落点）**：`AgentLoop.__post_init__` → `_secretary_for(role, root,
  store, registry, seam, sid)`（`agent_loop.py` 的 `_secretary_for`）。三个条件写在它的
  docstring 里（同一个缝实例 / `enable_model=True` / 可归因）。派生失败 fail-open，
  理由落 `secretary_problem` 并写 `agent_note`。
- **读面（比"只读手稿"宽得多）**：
  · `self.store.rows(<table>)` —— 任意表，含 `tasks`（`:815` 与 `:833` 就是读 `tasks` 的），
    这是"秘书能查子代理的活跃子代理"的**现成权限基础**；
  · `manuscripts.read_rows`（手稿全文）；
  · `build_registry(...).registry.names()`（工具真名）；`specs` 的角色定位与动作表。
- **写面（只有两处）**：
  · `secretary/decisions-<role>.jsonl`（`decisions_path(root, role)`，`:89`）—— 唯一的台账；
  · 通过 `MS.write` / `MS.revise` 写**手稿**（`handoff_add` / `handoff_revise`）。
  · **秘书一处都不写 `tasks`**（全仓 `_write_new_row` 的调用者只有 `conductor.py`）。
- **编排层怎么用它**：`agent_loop._outbound_hook`（发件前，`:2801`）与 `_inbound_hook`；
  M 的派活还会走 `_dispatch_notify`（把 `notify` 交给秘书写成手稿）。

## §3 多智能体并发的真实实现

- **波内并发、波间串行**：`scheduler.run_waves`（`scheduler.py:215`）按
  `P.waves_of(calls, limit=policy.max_concurrency)` 分波，每波一个
  `ThreadPoolExecutor(max_workers=min(len(wave), policy.max_concurrency))`（`:257`）。
  `max_concurrency` 缺省 4（`draft/83` §8；业主 T1b 已裁"保持 4 + 写明名额上界 ≠ 并发上界"）。
- **两道闸门**：`policy.estimate_write_conflict` 决定"同不同波"（同写集不同波）；
  `conductor._running`（进程内集合，含"已接受未结束"的占位令牌）管全局并发上限；
  `_await_fanout_slot` 管单父在飞。
- **进程模型**：并发是**线程**；子代理是同步调用（§1）。所以"几个代理同时在跑"在盘上表现为
  **同一进程内的多个线程**各写自己的会话文件；跨进程只有顶趟级。
- **对设计的直接含义**：秘书必须假设**同一角色有多个并发实例**（同波的不同 `instance` 标签），
  见 §7 的重号风险。

## §4 绝对编码：取号与"无冲突注册 / 销号"

- **取号与建行是同一个临界区**：`_write_new_row`（`conductor.py:841`）
  `with self._id_lock: with self.store.tx("tasks", …)` 内
  `row["task_id"] = next_prefixed_id(tx.rows("tasks"), "task_id", "t")`（取 max+1 并跳过已占用）
  → `Task.validate()` → `tx.upsert("tasks", task.to_dict())`。docstring 记了"先算号再写行"
  在并发下必错的那次实测（两个召唤拿到同一个 `t-0003`、凭空少一次召唤）。
- **另一条取号路**：`store.alloc_id(kind)`（`store.py:306`），真源是各表已用号，
  `counters.json` 只是缓存；`LOCK_ORDER`（`store.py:65`）把 `counters` 放最后（任何 alloc 都要它）。
  `tasks` 走的是前一条（`next_prefixed_id`），因为它必须与建行同临界区。
- **"销号"今天不存在**：没有任何地方把 `t-00xx` 还回去或复用；号是单调的。
  ⇒ 名册口径下**建议维持"号不复用"**（本地名序号也不回收，见 `draft/90` §1.6）：
  复用号会让"退役过的人"与"新来的人"在历史读数里同名 —— 电话簿里最坏的形态。
- **"无冲突注册"要的两件事**（今天都只有一半）：
  ① 取号无冲突 —— **已有**（上面那个临界区）；
  ② **登记无冲突**（名册名 + 对照表）—— **没有**：名册/对照表不存在，而且它们要写的是
  `secretary/` 下的 jsonl，**不在** `_id_lock` 的保护区里（见 §7 的锁问题）。

## §5 handoffs 格式改写（现状与要改的地方）

- **一行手稿的字段**（`manuscripts.py:372`）：
  `id`（4 位 `NNNN`，`MS.write` 在同一把锁里分配）/ `sender`（写的人的角色，秘书替本体执笔时
  **仍写被服务的角色**）/ `to`（收件人角色或 `ALL`）/ `summary`（一行）/ `body`（markdown）/
  `refs`（引用编号，逐条核）/ `created_at` / `task_id`（实例号）/ `sid` / `note`。
  必填三样：`to` / `summary` / `body`（`:63`）。
- **两处与名册口径冲突/需要动的地方**：
  ① `handoff_add` 里 `recipient=str(to).upper()`（`secretary.py:1066`）—— 本地名 `D3` 会被
  当成角色名 `D3`（今天没有这个角色）⇒ 译码必须发生在**写手稿之前**（接线员）；
  ② 一行手稿只有 `sender`/`to` 两个**角色**格，没有本地名格 ⇒ 名册口径要么给 `to` 允许本地名
  并在其中带上绝对编码（`task_id` 已有），要么加 `to_name` / `from_name` 两格。
  **建议**：`to` 保持"角色或 `ALL`"（兼容既有 1562 行），**新增 `to_name` / `from_name`**
  两格（可空），绝对编码继续走 `task_id` —— 这样老行读得回来、新行带名册名。
- **谁写**：模型自撰那一半走 `_do_handoff` → 秘书 → `MS.write`；框架派生那一半由动作结果
  与派活派生（真机 1562 行全是框架派生，模型自撰 0 —— `draft/89` §3）。

## §6 秘书职责改写（加三档，不动原来四档的语义）

| 档 | 现在的入口 | 加什么 |
|---|---|---|
| 名册（增 / 退役） | 无 | `roster_add` / `roster_retire`（三分支，`draft/90` §1.9） |
| 对照表（译码） | 无 | `resolve(parent, name) -> task_id` / `name_of(task_id)`（**唯一实现**） |
| 调查（查伪表） | 无（只有 `handoffs_digest`） | `roster_view(parent)` / `latest_report_of(tid)`：名册 + 状态 + **子代理的活** |
| 洗格式 | `optimize_outbound`（**只报不改**） | `wash_delegation`（格式面可改写，内容面一字不动，`draft/90` E5） |

- **一项纪律不变**：秘书**不建 `tasks` 行**（`_write_new_row` 的临界区与扇出闸门都在
  conductor 手里）⇒"增"落地成"父说意图 → 秘书洗格式 + 定名 → conductor 落行 → 秘书登记"。

## §7 秘书并发：一实例一秘书**成立**，但盘上不成立（"同生同死"要补三样）

- **成立的那一半**：`AgentLoop.__post_init__` **每个循环对象派生一个秘书**；而每个召唤
  （`LlmBackend.call`）新建一个 `AgentLoop` ⇒ **一代理一秘书对象**，生命周期 = 那个循环对象
  （子代理返回后循环对象不再被引用）。**同生**这一条今天是真的。
- **不成立的那一半（盘上）**：
  ① **台账文件只有角色维度**：`decisions_path(root, role)` ⇒ 同角色的一切实例（同波并发的
  `instance=` 标签、不同父下的同角色）**共用一个文件**，读的人分不出是哪一个代理写的；
  ② **写没有锁**：`note_decision`（`secretary.py:243-247`）是裸 `path.open("a")` +
  `json.dumps` 一行 —— 既没有 `sessions.append` 那套"进程内 `threading.Lock` + 跨进程
  `filelock.FileLock`"（`sessions.py:36/92/150`），也没有进 `_id_lock`；
  ③ **`seq` 是"读全表再 max+1"**（`:210-211`）⇒ 并发下两个秘书会拿到**同一个 `seq`**
  （与 `_write_new_row` 修过的那个缺陷同族，**这一处没修**）。
  ④ **没有存活/收尾读数**：`stopctl` 登记的只有"角色 + pid"（顶趟级），
  没有"哪个秘书属于哪个代理""代理死了秘书留下了什么"这一类读数 ⇒ **同死**这一条没有载体。
- **建议的修法**（与既有 house pattern 对齐，不改秘书的职责面）：
  · 台账文件按**绝对编码**分片（`secretary/decisions-<role>-<task_id>.jsonl`），
    读侧提供"合并视图"（按角色/按父）；
  · 写入走 `sessions.append` 同族的锁（进程内 `threading.Lock` + `filelock`），
    `seq` 改成"锁内读-改-写"（或直接不写 `seq`，用 `(role, task_id, at, 序号)` 组合键）；
  · 加一条**存活读数**：秘书随代理登记（`register_pid` 里带 `task_id`），
    代理收尾时写一条 `secretary_closed`；读侧回答"某个代理的秘书还活着吗"。

## §8 父代理的记录方式（按业主口径：**父拿角色类型，秘书拿绝对编码**）

业主原话："父代理的记录方式（应该是代理拿角色类型（因为只可能有一个父亲），秘书有绝对编码）"。

- **含义**：一个子代理**只可能有一个父亲** ⇒ 在父这一侧，子代理的身份可以用
  **角色类型**（+ 同角色序号）表达，父**不需要**知道 `t-00xx`；绝对编码只活在**秘书**那层
  （对照表 `roster-index.jsonl`）。
- **由此定的三件事**：
  ① 名册行（父侧）的键 = `(parent, role, 序号)`，字段 = 名字 + 一句任务简介 + 状态；
  ② 绝对编码**只**出现在 `roster-index.jsonl`、`tasks` 行、会话事件里；**不出现在父的提示词里**
  （`draft/90` E17：`{{children}}` 要改成名册摘要）；
  ③ 父要跟某个子说话 / 退某个子，**只写名字**；译码是秘书的事。
- **今天的状态**：正好相反 —— 提示词里 `{{task_id}}` / `{{parent_task_id}}` / `{{children}}`
  全是绝对编码；没有任何"角色类型 + 序号"的父侧记录。

## §9 秘书之间通信与译码

- **今天有的是**：`Secretary.negotiate(with_role=…, point=…, rounds=…)`（`secretary.py:1033`）——
  最多 2 轮，之后"上报本体"。但它**只写自己那一侧的台账**
  （`note_decision(..., negotiation=…)` → `decisions-<自己的角色>.jsonl`）+ 一份**内存**
  `self._negotiations`；docstring 逐字："本方法只记录协商这件事本身：真正的来回由两侧真身驱动"。
  ⇒ **秘书 ⇄ 秘书今天没有真正的通道**（不写对方、不发消息、不落对方台账）。
- **译码（本地名 ⇄ 绝对编码）今天不存在**：没有任何 `resolve` / `name_of`。
- **建议的落地形态**（两件，都不新开特权通道）：
  ① **译码**：`Secretary.resolve(parent_task_id, name)` / `name_of(task_id)` 唯一实现，
     内部读 `roster-index.jsonl` + 台账做对账（`draft/90` §1.6 判据②），三态返回；
  ② **秘书 ⇄ 秘书**：用**既有的项通道**（`kind="message"` 的板项，收件人写对方的秘书），
     即"秘书之间也按编号沟通"，不许代读；两轮不收敛 ⇒ 上报本体（既有规则不变）。
     另可选一条**只读**的"对方名册查询"（§10 的调查工具）——它不写对方任何东西。

## §10 调查工具（业主："能允许秘书查子代理的活跃子代理的工作内容"）

- **今天有的**：
  · `conductor.ledger(view="tree" / "issues" / "verify" / "relays", root_task_id=…)`
    （`conductor_tools.py:412`）—— 只给**编号树**，没有简介、没有"在干什么活"；
  · `conductor.state` / `conductor.board`（M 面）—— 板项与读数；
  · `manuscripts.list` / `manuscripts.read`（A–H 面）—— 手稿编号与全文。
- **缺的正是业主点名的那一件**：**按名册名查任意实例的"活跃子代理 + 任务简介"**。
  它需要三样输入：`(父的绝对编码或名字)` → `名册` → 其中每一项 → `它自己的活跃子代理`
  → `它们的任务简介`。前两样今天不存在（E16），第三样存在（`_in_flight_children_of`，
  S1e 之后才是"只看代理"），第四样不存在（没有"简介"这一格 —— E18）。
- **落地形态**：一件查名册的工具（`conductor.roster` / `manuscripts.roster` 同族），
  `returns = {'checked','rows','their_children','reason'}`；`rows[] = {name, role, brief, state}`，
  `their_children[]` 是**递归一层**（业主 §1.9 第 ② 支要的就是它）。
  **不挂空**：注册它的同笔要接三处计数合同（observations 夹具 / `M_TOOL_FACE` /
  `test_host_wiring` 的两处硬计数 —— S1b 漏改过的正是这里）。
- **权限**：秘书用它（秘书已有 `store.rows("tasks")` 的读面，§2）；模型侧那一件只读、
  只给"我自己名下的"（越权查别人的名册要走父/秘书，别开洞）。

---

## §11 每一条落到哪个批次

| 设计条目 | 依赖的真实结构 | 批次 |
|---|---|---|
| 两轴分开（代理 vs 工作项） | `_in_flight_children_of` / `in_flight_items` | **S1e** |
| 板项渲染 + 渲染即 seen | `inbox_digest` 同族 + `mark_item_seen` 接线 | **S1i** |
| 复用分支（派活不一定是增） | `summon` 的 [5] 步前加分支 | **S1j** |
| 三态与幂等键 | `active_children` / `inputs` 里的受控标记 | **S1h** |
| `keep_alive` 读侧（待命不妨碍退役） | `keep_alive_of` | **S2'** |
| 消边判定点 | 步首（与 S1i 同址）+ 会话事件 | **S1f** |
| 名册 / 对照表 / 接线员 / 退役工具 / 消息两个方向 | §2 的写面 + §4 的取号 + **§7 的锁与分片** | **S1k** |
| `#public` 可见面 | `message` 的接收面 | **S6** |

**新增一批（§7 的锁与分片，建议编号 S1m）**：`decisions` 文件按绝对编码分片 + 追加加锁 +
`seq` 锁内读改写 + 秘书存活读数。**它是 S1k 的前置**（名册与对照表就是"要并发追加的两份
jsonl"，不先把锁与分片定下来，S1k 一上线就会重号/串行化）。

## §12 新登记的出入（详见 `draft/83` §11 续三）

- **E22** 秘书台账**文件只有角色维度**（同角色并发实例共用一个文件）⇒ "一跟一"在盘上不成立；
- **E23** 秘书台账写入**没有锁**、`seq` 是"读后写"⇒ 并发下**重号**（`sessions.append` 有锁，
  这一处没有）；
- **E24** 秘书 ⇄ 秘书**没有真通道**（`negotiate` 只写自己那一侧 + 内存）；
- **E25** 没有"秘书 ⇄ 代理"的**存活/收尾读数**（"同死"无载体）；
- **E26** 没有"按名册名查任意实例的活跃子代理 + 任务简介"这件调查工具。

## §13 未核实 / 待业主一句话

- **待一句话**：① 洗格式 = 建议还是改写载荷（`draft/90` §4）；② 兄弟之间能否"盲转"
  （`draft/90` §5）；③ 名册序号是否每父每角色各一套且不回收（`draft/90` §5）。
- **未核实 → 已查清（同日晚补）**：秘书台账分片会碰到**四处读侧** —— `Secretary.decisions()`
  （`secretary.py:184`，聚合读）、`Secretary.knowledge()`（`:279`，`ledger` 那一格）、
  `webui/readers.py:566 _secretary_rows`（**目录 glob** `out/secretary/*.jsonl`）、
  `secretary.selftest()`（`:1215`，"台账分角色"那一条）。分片必须与这四处同笔改；
  名册建议另放 `out/roster/`（不同目录 ⇒ WebUI 那一面一个字节不动）。
  落地写法见 `draft/92` §2/§3.3/§5-⑬⑭⑮。
