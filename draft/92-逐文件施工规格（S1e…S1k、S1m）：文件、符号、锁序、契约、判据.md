# 92 · 逐文件施工规格（S1e…S1k / S1m）：文件、符号、锁序、契约、判据

> **这一页怎么用**：它是 T22 那一套（名册 + 对照表 + 接线员 + 退役三分支 + 消息两个方向）
> 的**施工规格**，按文件列到符号级。与 `draft/86` §15/§16 的关系是：
> **冲突以本页为准**（§5 列出被本页取代/订正的旧条目），`draft/90` 仍是口径与出入清单，
> `draft/91` 是只读核实。
>
> 纪律不变：每批一个提交、提交信息带读数与偏差；新红如实登记；`tests/golden` 由人重冻；
> `schema.py` / `projects.py` / `runflow.py` / 其它 FC-27 文件不动。

---

## §1 全局不变量（先定死，逐文件都按它写）

| # | 不变量 | 为什么（一句话） |
|---|---|---|
| I-1 | **代理轴与工作项轴分开**：`active_children(tid)` / `_children_of(tid)` 只数 `kind == ""` 的行；板项只走 `in_flight_items(tid)` | 板项行 `status="pending"` 永不终态 ⇒ 两轴混算会把扇出名额吃光（E1 实测） |
| I-2 | **绝对编码不进提示词**：模型侧只出现**本地名**（`D1`）与角色；`t-00xx` 只出现在台账、`roster-index`、会话事件与"未登记"读数里 | 业主："代理拿角色类型，秘书有绝对编码" |
| I-3 | **退役 = 父说名字，秘书执行**（三分支：活跃⇒报最近报告 / 在等待⇒查 A1 名下活跃子代理 / 空⇒退役）；**框架不自动退役**，只给"可就绪"读数 | 业主逐字（`draft/90` §1.9） |
| I-4 | **增 = 派活的一个分支**（新起 ⇒ 名册 +1；复用 ⇒ 名册不变）；**秘书不建 `tasks` 行** | 业主订正 + `_write_new_row` 是唯一新行临界区 |
| I-5 | **一个写者一片**：名册、对照表、秘书台账都按**所有者绝对编码**分片；每片只有一个写者（该父/该实例的秘书），跨进程用 `filelock`、进程内用 `threading.Lock` | `sessions.append` 的 house pattern；今天的秘书台账是裸 `open("a")`（D107） |
| I-6 | **锁序**：`_id_lock` → `tasks` 事务（conductor）→ 秘书片锁**只在台账事务之外**申请；禁止"持片锁时开 `tasks` 事务" | 与 `LOCK_ORDER` 同精神，避免交叉死锁 |
| I-7 | **三态**：每个读侧返回 `checked` + `reason`（读到 / 确实为空 / 没读成）；判据里"没读成"一律按**拒绝**处理 | "空"与"没查成"折平会让父误退役（E9） |
| I-8 | **只许追加**：名册、对照表、秘书台账都是 append-only；退役写事件行，不物理删 | 否则"名册里少过谁"读不回来 |
| I-9 | **零 schema 变更**：名册/对照表/分片台账在 `secretary/`（jsonl），`handoffs` 的新字段在 `manuscripts/`（jsonl）⇒ `schema.py` 一个字节不动 | 避开 FC-27 与 59 个工作区的版本契约 |
| I-10 | **幂等键**：派活 `input_key`（既有，不许挪用）；退役 `(owner, name, 尝试)`；复用不产生新键 | 重复宣布/重复退役不产生第二条读数 |
| I-11 | **一处实现**：译码只有秘书一处（`resolve_down` / `resolve_up` / `name_of`）；"我的子代理"只有 `active_children`；退役判定只有 `Secretary.retire` | 两处口径是本仓反复踩的形态 |

---

## §2 数据落点与格式（全部 append-only jsonl）

```text
<workspace>/out/secretary/<role>.jsonl                          # 老文件：保留可读（不分片的历史）
<workspace>/out/secretary/<role>-<task_id>.jsonl                # 新：一实例一片（S1m）
<workspace>/out/roster/<owner_task_id>.jsonl                    # 名册（owner = 父的绝对编码）
  {"kind":"add",   "seq":n, "at":…, "owner":"t-0003", "name":"D1", "role":"D",
   "task_id":"t-0011", "brief":"把 X 的族构造证据补齐"}
  {"kind":"retire","seq":n, "at":…, "owner":"t-0003", "name":"D1", "task_id":"t-0011",
   "by":"<父的本地名或角色>", "branch":"waiting_no_children",
   "reading":{"items_open":0, "checked":true}}
  {"kind":"keep_alive","seq":n, "at":…, "owner":"t-0003", "name":"D1", "value":true}
<workspace>/out/roster/<owner_task_id>-index.jsonl              # 对照表（电话簿）
  {"owner":"t-0003", "name":"D1", "role":"D", "task_id":"t-0011", "at":…}
<workspace>/manuscripts/handoffs.jsonl                          # 既有；新增两个**可空**字段
  … + "to_name":"D1", "from_name":"A1"                          # 本地名（老行没有这两格）
```

- **路径按既有常量**：`secretary.SECRETARY_DIR = ("out", "secretary")`（`secretary.py:69/97`）
  —— 我上一版写的 `<workspace>/secretary/…` **是错的**，已按真实路径改正。
- **名册与对照表放 `out/roster/`（另起一个目录），不放 `out/secretary/`**：因为
  `webui/readers.py:566 _secretary_rows` 是**目录 glob**（`sorted(d.glob("*.jsonl"))`），
  同目录会把名册行混进 WebUI 的"秘书决定台账"那一面（两种语义）。放另一个目录 ⇒
  WebUI 那一面一个字节不动；名册另有自己的读侧（工具/形状）。

- **本地名**：`<角色字母><序号>`；序号 = 该 owner 下该角色**当前最大序号 + 1**，在片锁内决定；
  **退役不回收**（I-8 的同族理由）。
- **谁写哪一片**：`roster-<owner>` / `roster-index-<owner>` 的唯一写者 = **owner 的秘书**；
  子代理的秘书**只读**父的那一片（拿自己的名字）。
- **事件名（会话面，审计用）**：`roster_added` / `roster_retired` / `roster_repaired` /
  `edge_released`（可选读数）/ `retire_reported`（"没退，把报告端上去了"）。
  写在**谁的会话**里：`roster_added` 写在**父**的会话（它说的这句话），`roster_retired` 同上。

---

## §3 逐文件伪代码

### 3.1 `src/agentflow/conductor.py`

```python
# ---- S1e：两轴分开（I-1）
def _in_flight_children_of(self, task_id: str) -> list[str]:
    ... and not str(r.get("kind") or "") ...             # ← 加这一个条件（另两处读数同步）
def _admitted_children_of(self, task_id: str) -> list[str]: ...   # 同上加一条
def dispose(self) -> dict:
    # 只收代理行；板项原样留着 + 新读数 board_items_left
    return {..., "board_items_left": len(skipped)}

# ---- S1h：三态读数（I-7；can_release_edge 不再单独存在，见 §5-①）
def active_children(self, task_id: str) -> dict:
    """`{"checked": bool, "rows": [{"task_id","role","state"}], "reason": ""}`
    `state` ∈ {活跃, 在等待}（活跃 = status==running；在等待 = 已终态但那一行还在）。"""

# ---- S1j：复用候选（业主："派活不一定是增"）
def reusable_child_of(self, parent_task_id: str, role: str, *, name: str = "") -> dict:
    """`{"checked","task_id","name","reason"}`。口径：
       ① `name` 给了 ⇒ 只要它（名册名 → `roster-index` 译码，见秘书）；没给 ⇒ 在该角色下找；
       ② 该子还活着（`active_children`）；
       ③ 它名下最新那条 `kind="delegation"` 项声明过 `keep_alive`（A6=丙；E15 落地后才有此形态）。
       读不成 ⇒ checked=False（**不许**折成"没有可复用的"，那会把复用静默变成新起）。"""

# ---- S1f（**被吸收**，只留就绪读数）：父的"可以退役了吗"
def retire_ready(self, parent_task_id: str) -> dict:
    """`{"checked","ready":[{"name","task_id","branch","reading"}],"reason"}`
    逐项按 §1.9 的三分支预判（活跃 ⇒ branch=active；在等待且名下空 ⇒ branch=waiting_no_children；
    在等待但名下有活跃子 ⇒ branch=waiting_with_children），**只报不动作**（I-3）。"""
```

- **会碰**：`tests/test_fanout_admission.py`（分子定义）、`tests/test_e13_concurrency.py`（dispose）、
  `tests/test_board_items.py`（`in_flight_items` 第一次有生产调用者）。
- **新判据**：`test_board_does_not_eat_the_fanout_quota.py`、`test_active_children_is_three_state.py`、
  `test_delegation_may_reuse_an_active_child.py`。

### 3.2 `src/agentflow/agent_loop.py`

```python
# ---- 形状面（**零新工具**，两个新形状；见 §5-⑧ 的联动清单）
SHAPES = (..., "retire", "roster")          # 8 → 10；同笔更新 JSON_TAIL / LOOP_PROTOCOL /
                                            # llmseam.META_FUNCTIONS（framework_retire/framework_roster）/
                                            # _param_table / 形状计数判据 / 两处金标 / PROMPT_VERSION
# summon 载荷新增两格（**不改形状个数**）
#   {"summon": {"role":"D", "action":"run_once", "params":{…},
#               "brief":"把 X 的族构造证据补齐",     # 必填（内容面）
#               "reuse":"D1"}}                        # 缺省 = 新起；给了名册名 = 复用
#   {"retire": {"name":"A1"}}
#   {"roster": {"of":"self"|"A1"}}                    # 查伪表（只读）

def _do_summon(self, payload) -> dict:
    # 0 校验 brief（缺 ⇒ 受控拒绝 invalid_params，**不替它编**）
    # 1 秘书洗格式（S1g）：wash_delegation → refused ⇒ 原样回绝
    # 2 reuse 给了 ⇒ 译码 + conductor.reusable_child_of ⇒ 复用那一支（不建代理行）
    # 3 新起 ⇒ conductor.summon（既有；闸门/建行/取号一个字不动）
    # 4 秘书 roster_add(owner=self.my_task_id, role, task_id=res.task_id, brief)
    #   失败 ⇒ 读侧"未登记" + 下次 roster_repair（§3.3）

def _do_retire(self, payload) -> dict:
    # 只做转发：self.secretary.retire(owner=self.my_task_id, name=payload["name"])
    # 并把 action / report / why 原样并进这一步的结果（判定一行都不写在这里，I-11）

def _do_roster(self, payload) -> dict:
    # of="self" ⇒ 我自己的名册；of="D1" ⇒ 先译码再查**它**的名册（业主 §1.9 第②支要的那一步）
    # 返回：rows（名册 + 状态 + 简介）+ their_children（递归一层）+ checked/reason

def board_digest(session_root, role, *, sid=None, conductor=None, my_task_id="", window=8):
    """S1i：板项进上下文。口径与 `inbox_digest` 同源（渲染集合 = 标记集合，D75 的教训）；
    只取挂在**我**名下的未消项；渲染多少标多少（`mark_item_seen`，带 seen_by/seen_step）。"""

def run(self, task, *, summoned_by="", my_task_id="", parent_task_id="", ...):
    # 事实表新增：my_name（我在父名册里的名字，读父的片）/ parent_name / roster（我的名册摘要）
    # 步首（与 mark_item_seen 同处）：读到"某个子已收工"的通报 ⇒ conductor.retire_ready(我)
    #   ⇒ 并进这一步的结果（{"retire_ready": …}）；**不自动退役**（I-3）
```

- **渲染**：`{{children}}` → 名册摘要（`D1 · 简介 · 活跃`）；新增 `{{my_name}}` / `{{parent_name}}`；
  `{{task_id}}` 保留但提示词里写明"跟同伴说话用名字"。
- **会碰**：`tests/test_agent_loop.py`（形状计数、`_summon_step`）、`tests/test_agent_prompts.py`
  （十格摘要）、`tests/test_native_tool_calls.py`、`tests/test_prompt_param_hints.py`、
  `tests/test_inbox_delivery.py`、`tests/test_children_and_parent_are_visible.py`（E17）。
- **新判据**：`test_board_items_reach_the_prompt.py`、`test_subagent_is_born_with_a_name.py`、
  `test_retire_is_a_three_branch_query.py`、`test_messages_go_by_roster_name.py`、
  `test_no_relay_of_messages.py`。

### 3.3 `src/agentflow/secretary.py`

```python
# ---- S1m：分片与锁（I-5/I-6）——**先做这一批，S1k 才有地基**
def decisions_path(root, role, task_id: str = "") -> Path:
    # task_id 空 ⇒ 老文件 `out/secretary/<role>.jsonl`（兼容读）
    # 给了 ⇒ `out/secretary/<role>-<task_id>.jsonl`（一实例一片）
# 分片会碰到的四处读侧（**已查清，必须同笔改**）：
#   ① `Secretary.decisions()`（`:184`）—— 聚合读：老文件 + 本实例片 + （可选）按角色合并全部片；
#   ② `Secretary.knowledge()`（`:279`）—— 里面那一格 `"ledger": str(decisions_path(...))`；
#   ③ `webui/readers.py:566 _secretary_rows` —— 目录 glob，分片会被自动读到（**这正是把名册
#      放到 `out/roster/` 的原因**）；它按 `*.jsonl` 收，所以分片名不能带别的扩展名；
#   ④ `secretary.selftest()`（`:1215`）—— 那一条"台账分角色"（D 有 / M 没有）要改成
#      "按实例分片 + 合并视图可读"，并保留一条"老文件仍可读"的反负控。
def append_jsonl(path, rec) -> tuple[bool, str]:
    """**唯一**的秘书追加口：进程内 `threading.Lock`（按路径）+ 跨进程 `filelock.FileLock`
    （与 `sessions.append` 同一做法），`seq` 在**锁内**读-改-写。失败 ⇒ `(False, 理由)`。"""
def note_decision(...): ...            # 改为走 append_jsonl(self.decisions_path 分片)
def secretary_alive(self) -> dict: ... # 存活/收尾读数：{pid, task_id, role, at, checked}

# ---- S1g：洗格式（**新增方法**，不动 optimize_outbound 的"只报不改"）
def wash_delegation(self, shape, payload) -> dict:
    """`{"payload","before","changes","refused"}`：只洗格式面（真名/键名/必填/受控取值/
    instance/input_key 归一）；内容面（谁/什么/值/notify 正文）一个字不许动；洗不动 ⇒ refused。"""

# ---- S1k：名册 / 对照表 / 译码 / 退役 / 调查（全部只碰 secretary/ 下的 jsonl）
def roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
               want_name: str = "") -> dict:
    """片锁内：①want/下一个序号定名 ②写 roster-<owner> 一行 ③写 roster-index-<owner> 一行
    （两行一笔：都写或都不写）。返回 {"name","role","task_id","problem"}。"""
def roster_repair(self, *, owner: str) -> tuple[int, str]:
    """补登记（自愈）：片锁内扫 owner 名下**代理行**、按 `task_id` 升序给没有 index 行的那些
    分配下一个序号 ⇒ 确定性 + 幂等（两个并发修复不会重复分配）。返回 `(补了几条, 问题)`。"""
def resolve_down(self, *, owner: str, name: str) -> tuple[str, str]:   # 我名下名册 → 编码
def resolve_up(self, *, my_task_id: str, name: str) -> tuple[str, str]: # 我父的名册 → 编码
def name_of(self, *, owner: str, task_id: str) -> tuple[str, str]:      # 反查（渲染用）
def roster_view(self, *, owner: str) -> dict:
    """伪表：`{"checked","rows":[{"name","role","brief","state","retirable","items_open"}],"reason"}`
    `state` ∈ {活跃, 在等待, 已退役}；**只读**。"""
def latest_report_of(self, *, task_id: str) -> dict:   # 退役第①支要端给父的东西（E19）
def active_children_of(self, *, task_id: str) -> dict: # 退役第②支：**它**名下的活跃子代理（代理轴）
def retire(self, *, owner: str, name: str, by_task_id: str) -> dict:
    """§1.9 三分支；**执行前**按 `active_children_of` 与 `latest_report_of` 判定；
    执行 = 写 roster 的 retire 事件 + index 同步标退役（编码保留、序号不回收）。"""
```

- **权限**：读面不变（`store.rows(<任意表>)` 含 `tasks` + 手稿 + registry）；
  **一处都不写 `tasks`**（I-4）。
- **会碰**：`tests/test_secretary_noise.py`（`:187` / `:306` 的口径要按 I-4/I-5 改写）、
  `tests/test_secretary.py`、`tests/test_secretary_is_mandatory.py`。
- **新判据**：`test_secretary_ledger_is_sharded_and_locked.py`（正控：两实例并发追加 200 行 ⇒
  `seq` 不重、行不丢 / 负控：老文件仍可读 + 分片文件按绝对编码命名 / 反真空：模板化字符串
  不许被当成路径注入）、`test_roster_index_reconciles_with_the_ledger.py`（对账判据②三个方向）。

### 3.4 `src/agentflow/manuscripts.py`（格式改写；**只加两个可空字段**）

```python
def write(..., to_name: str = "", from_name: str = "") -> dict:
    rec = {..., "to_name": str(to_name or ""), "from_name": str(from_name or "")}
# 读侧：`read_rows` 把这两格照读（老行没有 ⇒ 空串，**不许**用角色名去填）
# 必填三样（`to` / `summary` / `body`）**不动**（老行可读性）
```
- **谁填**：`secretary.handoff_add` 的 `to` 保持"角色或 `ALL`"，`to_name` / `from_name`
  由调用点（秘书，译码之后）填；**译码必须在写手稿之前**（今天 `to.upper()` 会把 `D1` 当角色，E20 的一半）。
- **会碰**：`tests/test_manuscript_handoff.py`、`tests/test_manuscripts_*`（若断言键集的，要逐条看）。

### 3.5 `schema.py` / `projects.py` / `runflow.py` / `store.py`

- **一个字不动**（I-9）。理由写在 §5-②。`store.py` 的 `alloc_id` / `LOCK_ORDER` 也不动：
  名册与对照表不走 `alloc_id`（它们的键是**名字**与**绝对编码**，不是 4 位编号空间）。

### 3.6 工具面与契约（**只在"要不要做成工具"那一岔口选甲时才动**）

- 若 `retire` / `roster` 做成**形状**（本页推荐）：`tools/` 零改动 ⇒
  `TOOL_COUNT` / observations / `M_TOOL_FACE` / `test_host_wiring` 两处硬计数**都不动**；
- 若做成**工具**：三处计数合同 + 两处硬计数同笔更新（S1b 漏改过的正是这里），
  并要决定它落在哪个面（M 的 `conductor.*` 还是 A–H 的 `manuscripts.*` —— 后者会顶到
  `manuscript_tools` 的"M 的读面是 `fs.*` 白名单"那一条裁定）。
- ⇒ 待业主一句话（§6）。

---

## §4 批次顺序、依赖与每批的"可以往下走"读数

```text
S1e（两轴分开 + dispose）──┬─▶ S1m（秘书分片 + 锁 + 存活读数）
                          │        └─▶ S1k（名册/对照表/译码/退役/调查 + 形状 + 渲染）
                          ├─▶ S1i（板项渲染 + 渲染即 seen）
                          │        └─▶ S1f'（就绪读数接线；不自动退役）
                          ├─▶ S1h（三态）      ──▶ S1k 依赖
                          ├─▶ S1j（复用分支）  ──▶ S1k（复用要译码）
                          └─▶ S2'（keep_alive 读侧）──▶ S1j
S1g（洗格式）——与 S1e 并行，独立
```

| 批 | 可以往下走的读数（硬） |
|---|---|
| S1e | 20 条板项不再拒派活；`test_fanout_admission` 全绿；dispose 不动板项行 |
| S1m | 两实例并发各追加 200 行 ⇒ `seq` 无重、行数 = 400；老 `decisions-<role>.jsonl` 仍可读 |
| S1i | 挂在我名下的项进提示词且被标 `seen`（`seen_by`/`seen_step`）；没渲染的不许被标 |
| S1h | 三态各一格读数；读不成 ⇒ 判据拒绝 |
| S1j | 复用那一支 `active_children` 不变、工作项轴 +1；子已停/换发起方 ⇒ 新起 |
| S2' | 待命不妨碍退役；真停的不被卡住 |
| S1f' | 父读到"子已收工"之后，结果里有 `retire_ready`；**没有**任何自动退役 |
| S1k | 造一个 D3 ⇒ `tasks` +1 / 名册 +1 / 对照表 +1 / 三处 `task_id` 一致 / 子提示词里读得到自己的名字；退役三分支各一条判据；对账判据②三个方向 |
| S1g | 错名/缺键被洗成受控形状且 `before`/`after` 都在台账；内容面的值改一个字节 ⇒ 红 |

---

## §5 逻辑匹配：这一轮解决掉的十二处不一致

① **`can_release_edge` / `release_edge` 取消** —— 它与我上一版写的"父自身已完全停止"是
   读错业主那句话留下的；业主 §1.9 的算法**取代它**：父的"决定"就是「A1 退役」这句话，
   "消边读数"就是那条 retire 事件。`draft/86` §15.3 那一节**作废**（保留作来路）。
② **零 `schema.py` 变更**（I-9）：名册/对照表/台账在 `secretary/`，`handoffs` 新字段在
   `manuscripts/` ⇒ 不碰禁改区、不碰 `SCHEMA_VERSION`、不碰 59 个工作区。
③ **分片键统一**：所有新 jsonl 一律按**所有者绝对编码**分片（名册/对照表按父，
   台账按实例）⇒ 一写者一片，锁不再跨片竞争。
④ **译码方向两个函数**（`resolve_down` / `resolve_up`）+ 一个反查（`name_of`）：
   下行查我自己的片、上行查我父的片（父的编码从我行 `parent_task_id` 读）。
⑤ **补登记自愈**（`roster_repair`）：解决"先落行、后登记"那个"有代理没名字"的窗口；
   确定性 + 片锁内 ⇒ 幂等。
⑥ **锁序写死**（I-6）：片锁只在台账事务之外申请 —— 与 `_write_new_row` 的
   `_id_lock → tasks 事务` 不交叉。
⑦ **复用用名册名表达**：`"reuse": "D1"`（而不是再加一个 `new_or_reuse` 枚举）——
   与"按编号沟通"同一套语法，也省掉一个字段。
⑧ **形状与工具面的联动清单**（改一处就要一起动的全部）：`SHAPES` / `JSON_TAIL` /
   `LOOP_PROTOCOL` / `llmseam.META_FUNCTIONS` / `_param_table` / `prompt_param_hints` /
   `tests/test_agent_loop.py` 的形状计数（`_shape_count_is_hand_copied`）/
   `tests/test_agent_prompts.py` 的十格摘要 + `PROMPT_VERSION` / 两处金标（人重冻）。
   **做成形状（不是工具）⇒ 工具面三处计数合同与两处硬计数不动**。
⑨ **`keep_alive` 的位置说清**：它在**派活项**（`kind="delegation"`，收件人 = 那个子）上，
   不在代理行上 ⇒ 复用候选的判据是"它名下最新那条派活项声明过 `keep_alive`"（E15 落地后才成立）。
⑩ **退役的执行者是秘书、触发者是父**：`_do_retire` **只转发**，判定与写在秘书一处（I-11）。
⑪ **`{{children}}` 改口径**：从绝对编码改成名册摘要；新增 `{{my_name}}` / `{{parent_name}}`；
   `{{task_id}}` 保留（对账用）但不再作为"指称"。
⑫ **`draft/86` §16.1 的 `retire` 形状名与本节一致**（`{"retire": {"name": "A1"}}`），
   §15.8 里"名册行写 `detail`"那句改成"名册行在秘书 jsonl 里，板项的 `detail` 只写一句人话"。
⑬ **路径按既有常量改正**：秘书台账的真实路径是 `out/secretary/<role>.jsonl`
   （`SECRETARY_DIR = ("out", "secretary")`，`secretary.py:69/97`）—— 我上一版写的
   `<workspace>/secretary/…` 是错的。
⑭ **名册另起 `out/roster/`**：`webui/readers.py:566` 是**目录 glob**，同目录会把名册行混进
   WebUI 的"秘书决定台账"面 ⇒ 换目录，WebUI 一个字节不动。
⑮ **分片会碰四处读侧**（已查清，见 §3.3 的清单）：`decisions()` / `knowledge()` /
   `webui/readers.py` / `selftest()`。**它们与分片同笔改**，否则"某处读不到"与"没有决定"
   会长得一样。

---

## §6 待业主一句话 / 未核实

1. **`retire` / `roster` 做成形状还是工具**（决定动不动工具面契约与权限面；本页推荐形状）。
2. **洗格式 = 建议还是改写载荷**（`draft/90` §4）；本页按"可改写、内容面一字不动"写。
3. **名册序号**：每父每角色各一套且**不回收**（本页按这个写）。
4. **兄弟之间能否盲转消息**（`draft/90` §5）；本页按"不许"写。
5. **已查清（不再是未核实项）**：秘书台账分片会碰到**四处读侧** —— `Secretary.decisions()`
   （`:184`，聚合读）、`Secretary.knowledge()`（`:279`，`ledger` 那一格）、
   `webui/readers.py:566 _secretary_rows`（目录 glob）、`secretary.selftest()`（`:1215`，
   "台账分角色"那一条）。⇒ 分片与这四处**同笔改**；名册另放 `out/roster/` 正是为了不让
   WebUI 那一面混进两种语义（见 §2 与 §5-⑭）。**这一条原先挂在 `draft/91` §13 的"没查完"，
   现已查完并写进本节。**
