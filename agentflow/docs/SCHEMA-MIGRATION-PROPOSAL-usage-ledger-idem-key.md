# SCHEMA 迁移提案：`usage_ledger` 的**幂等唯一键**（**待人工实施 + 2 名 reviewer 走查**）

> ⚠️ **这份提案不是已落地的改动。** 它由 AI 编写，**必须由人实施并批准**。
> 它与 `AGENTS.md` 的 FC-27（禁 AI 区）直接相关，理由见 §0。
>
> | 项 | 值 |
> |---|---|
> | 状态 | **未实施**（`src/agentflow/schema.py` 与 `src/agentflow/store.py` 一个字都没动） |
> | 作者 | AI agent（本轮任务） |
> | 批准人 | **（待填）** |
> | `required_approvals` | **2**（`scripts/noai_gate.py::REQUIRED_APPROVALS_ON_HIT`，写死不可配置） |
> | 关联 | `docs/PROPOSALS.md` 的 **P-12**；**提案 B 已由 AI 落地**（不在禁改区，见 §6） |

> 📌 **状态更正（本轮实测，2026 本轮）**：上表那一行"**未实施**"**已经不成立**，
> 保留它是为了不删历史。实测：`schema.UsageEntry.idem_key`（含空白断言）、
> `schema.validate_table` 的幂等键唯一性断言、以及 `verify.py` 的
> `duplicate_idem_key` 都**已在盘上**（`grep -n idem_key src/agentflow/{schema,verify}.py`）。
> 因此 §2.1 / §5 的 diff 应当读作"**这就是已落地的那一版**"而不是待办；
> §8 的判据 ⑧⑨ 也已可判。**这不改变本文档的结论：落地的那些行在禁改区，
> 仍然需要 2 名 reviewer 逐行走查 + 签字**（见 §7）。

---

## §0 为什么这件事不该由 AI 独自做

两个文件命中 `.noai-paths`：

```text
src/agentflow/schema.py  [category: schema-migration] `SCHEMA_VERSION` 与 `TABLES`：
                         表结构与版本号 —— 改它等于改磁盘格式契约
src/agentflow/store.py   [category: schema-migration] `LOCK_ORDER` / `rebuild` / `alloc_id`
                         / `_atomic_write`：加锁顺序、事件重放、ID 分配、原子落盘 ——
                         四者任一错都是**数据毁灭级**
```

FC-27 的原始论证（`AGENTS.md` 逐字引 `draft/LESSONS-工程经验清单（FC-01…FC-27）.md:716`）：

> "IF 改动落在禁改区（认证/授权/支付/加密/迁移/CI 配置/对外 API 破坏性变更）
> THEN 必须人工编写或人工逐行走查，且需要 **2 名 reviewer approve**
> ——否则会：**测试全绿、上线即越权**。"

套到**这份**提案上，"测试全绿、上线即越权"的具体形态：

| 若由 AI 独自实施 | 会发生什么 | 为什么测试不会红 |
|---|---|---|
| 给 `UsageEntry` 加字段却忘了它是 `asdict` 序列化的 | 老快照读回来时字段缺失 ⇒ 需确认默认值真的存在 | 测试夹具全是新造的，**没有一条测试读老数据** |
| 在 `validate_table` 里断言唯一性但**漏了空值分支** | 所有"没有幂等身份"的历史行互相冲突 ⇒ **整张表提交直接炸** | 夹具里每行都带键，空值分支从不被执行 |
| 把唯一性断言放在 `store.tx` **之外** | 判重与写入分处两个临界区 ⇒ 窗口原样存在，但代码**看起来**加了约束 | 单进程测试顺序执行，窗口永远不出现 |
| 递增 `SCHEMA_VERSION` 却不写迁移 | `validate_table` 对老文件抛"应为 N，收到 1" ⇒ **全部数据读不出来** | 单测只造新版本的文件 |

这四行都不是"写错了代码"，而是**判据本身的形状**变了。所以本提案只提供**确切的
diff、向后兼容分析与回滚方案**；实施与批准留给人。

---

## §1 现状（**实测**，不是推理）

### §1.1 本项目**没有数据库**

全仓 `grep -rn 'sqlite3|sqlalchemy|psycopg|CREATE TABLE|INSERT INTO|ON CONFLICT' src/`
只有 **1** 处命中，且是一个文件扩展名白名单（`tools/fs_tools.py` 的 `.sqlite3`）。

`usage_ledger` 是 `data/usage_ledger.json`：一个 JSON 数组，写入形态是
**取 `filelock` 排他锁 → 读全表 → 改 → `os.replace` 原子替换**（`store.py::tx`）。

> **因此"给 `usage_ledger` 加一个被索引的唯一键 / `INSERT … ON CONFLICT DO NOTHING`"
> 不能照搬** —— 这句话预设了一个 SQL 引擎。本栈里的等价物是
> **"把判重与写入放进同一个临界区"**，以及**表级唯一性断言**。
> 本提案做的正是这两件事；**提案 B（§6）只做了前一件，且已经交付**。

### §1.2 生产写入方**只有两处**，两处都是"先读账再写账"

| # | 位置 | 读（判重） | 写 | 键 |
|---|---|---|---|---|
| 1 | `modelcost.charge_reply` | `_find_by_marker` → `Store.rows()`，**无锁快照读** | `TokenMeter.charge()`，**有锁** | `idem-<hash>`（写在 `note` 里） |
| 2 | `conductor._charge_and_settle` | `self._task()` 读 `tasks.inputs` 的 `tokenmeter:settled`，**无锁快照读** | `TokenMeter.charge()`，**有锁** | `settle-<hash>`（**2026 本轮之前：不存在**，见下） |

两处的读与写**分处两个临界区**，窗口就在中间。
`TokenMeter.charge` 每次都 `alloc_id` 一个新号，所以两行会拿到**不同**的 `usage_id` ——
**按主键去重（`duplicate_id`）救不了**：主键本来就不同。

### §1.3 缺陷**确定性复现**（同一装置，修复前后各跑一次）

4 个真进程、同一个幂等键、屏障把"读账 → 写账"的窗口放大到必现：

```text
修复前：账本 4 行，总 token 6000，4/4 进程全部 charged=true/reason="charged"
        （只该记 1 笔 1500 ⇒ **4 倍重复扣费**，且没有一个请求拿到幂等结果）
修复后：账本 1 行，总 token 1500，1 个 charged + 3 个 duplicate，无异常
```

复现装置：`tests/test_usage_ledger_idempotency_mp.py` + `tests/_mp_idem_worker.py`。

### §1.4 ⚠️ **现有 `verify` 抓不到这个缺陷**（这是本提案存在的一半理由）

`verify.py` 对账本只查两件事：

| 判据 | 查什么 | 对本缺陷 |
|---|---|---|
| `duplicate_id` | 同一个 `usage_id` 出现两次 | **永远不响** —— 重复行的 `usage_id` 本来就不同 |
| `usage_task_total_mismatch` | `tasks.tokens` 与账本汇总不等 | **不响** —— 重复记账时两处**一起**虚高，它们仍然"相等"，只是相等的是错的数 |
| `id_gap` | `usage_id` 不连续 | 只在**清洗后**才响（warning） |

也就是说：**这条缺陷在现有判据下是完全不可见的**，只能靠"同一幂等键出现两行"
这个**新判据**抓住。见 §5。

---

## §2 提案 A（**推荐**）：可选唯一键字段 + 非空唯一断言 + `Tx.insert_unique`

### §2.1 `schema.py` 的精确 diff（3 处）

```diff
--- a/src/agentflow/schema.py
+++ b/src/agentflow/schema.py
@@ class UsageEntry
     usd: float = 0.0
     attempts: int = 1
     at: str = ""
     note: str = ""
+    #: 幂等键：**同一个非空值在整张表里只能出现一次**。
+    #: 空串 = "这一行没有幂等身份"（历史行、以及直接调 `TokenMeter.charge` 的行），
+    #: **不受唯一性约束** —— 把它也算进唯一性会让所有历史行互相冲突、整表提交炸掉。
+    #: 为什么是字段而不是 `note` 里的文本标记：见本提案 §1、§3.3。
+    idem_key: str = ""
@@ def validate(self)
         if self.task_id is not None:
             if not str(self.task_id).strip():
                 raise ValueError("task_id 给了就必须非空")
+        if self.idem_key != self.idem_key.strip():
+            raise ValueError(
+                "idem_key 不许有首尾空白 —— 否则 '  k' 与 'k' 是两个不同的键，"
+                "唯一性就形同虚设（同一笔账会被记两次，且不变量不会响）"
+            )
@@ def validate_table(table: str, doc: dict) -> None
     seen_ids: set[str] = set()
+    # ---- 幂等键的唯一性（"被索引的唯一键"在本栈里的落点）
+    #
+    # 判据是**通用的**：任何行只要带一个**非空**的 `idem_key`，它在整张表里就必须唯一。
+    # 没有把 `idem_key` 特判成"只有 usage_ledger 才有"：那样每新增一张需要幂等的表
+    # 都要改这里一次，而漏改的表现是"静默没有唯一性"（没有任何检查会响）。
+    seen_idem: dict[str, str] = {}
     for i, raw in enumerate(rows):
         ...
         rid = getattr(obj, id_field)
         if rid in seen_ids:
             raise ValueError(f"{table} 出现重复 ID：{rid}")
         seen_ids.add(rid)
+        key_val = str(getattr(obj, "idem_key", "") or "")
+        if key_val:
+            if key_val in seen_idem:
+                raise ValueError(
+                    f"{table} 出现重复的幂等键 {key_val!r}"
+                    f"（{id_field}={seen_idem[key_val]} 与 {rid}）—— "
+                    "同一笔账被记了两次，花销与预算都会翻倍。"
+                    "这在本项目的既有判据下**完全不可见**（两行的 usage_id 不同，"
+                    "duplicate_id 不响），所以这条断言是它唯一的自动防线。"
+                )
+            seen_idem[key_val] = str(rid)
```

`row_from_dict("usage_ledger", ...)` **不需要改**：它按
`UsageEntry.__dataclass_fields__` 过滤，字段加上后自动流转。

### §2.2 `store.py` 的精确 diff（1 处，**纯新增方法**）

```diff
--- a/src/agentflow/store.py
+++ b/src/agentflow/store.py
@@ class Tx
+    def insert_unique(self, table: str, row: dict, key_field: str, note: str = "") -> bool:
+        """**`INSERT … ON CONFLICT DO NOTHING`** 在本栈里的等价物。
+
+        返回 `True` = 真的插进去了；`False` = 这个键**已经有一行**，本次什么都没写。
+
+        ⚠️ **它不自己加锁，唯一性只在"读与写同一个临界区"内成立。**
+        由 `store.tx` 持有该表排他锁来保证：`tx.rows()` 在锁内读的是
+        **前一个进程刚提交的那一版**，所以后到者一定看得见先到者。
+        在 `store.tx` **之外**调用它 = 把"先读后写"的窗口原样搬回来，
+        而代码看起来像加了约束 —— 这是本方法唯一危险的误用方式。
+
+        为什么空键要抛而不是"当作不冲突"：空键要么让每一行都冲突
+        （唯一性变成"全表只能有一行"），要么让唯一性完全失效 ——
+        两种都不是调用方想要的，所以不给它一个静默的解释。
+        """
+        if table not in self.tables:
+            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
+        key = str(row.get(key_field) or "").strip()
+        if not key:
+            raise StoreError(
+                f"insert_unique({table}) 的 {key_field} 为空 —— "
+                "空键在唯一性语义下没有定义（见 docstring）"
+            )
+        for r in self.rows(table):
+            if str(r.get(key_field) or "") == key:
+                return False
+        self.upsert(table, row, note=note)
+        return True
```

### §2.3 **不需要改**的东西（明确列出，减少复核面）

| 项 | 为什么不改 |
|---|---|
| `LOCK_ORDER` | `usage_ledger` **已经在里面**（第 14 位）。`insert_unique` 复用调用方已有的锁，**不加新锁、不改顺序** ⇒ 死锁面不变 |
| `alloc_id` | 不改。`insert_unique` 在冲突时不调它，所以重放**不消耗号**（见 §8 判据④） |
| `rebuild` | 不改。字段是 dataclass 成员 ⇒ `to_dict()`/`row_from_dict` 自动带上（**但见 §4.2 的回滚陷阱**） |
| `_atomic_write` | 不改 |
| `SCHEMA_VERSION` | **刻意不递增**，见 §3 |

---

## §3 向后兼容分析（**这份提案的核心论证**）

### §3.1 老数据：**不需要迁移**

`idem_key: str = ""` 有默认值。磁盘上没有这个键的老行经
`row_from_dict` 还原后 `idem_key=""`，于是：

- `UsageEntry.validate()` 通过（空串是合法值）；
- `validate_table` 的唯一性断言**跳过**它（判据是"非空才断言"）；
- JSON 往返不丢别的键。

**所以本次不需要 `SCHEMA_VERSION` 递增，也不需要任何数据迁移。**

### §3.2 为什么**不该**顺手把 `SCHEMA_VERSION` 1 → 2

递增版本号的代价见 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` §0 那一行：
`validate_table` 会拒读所有 `schema_version=1` 的文件 ⇒ **旧工作区全部读不出来**。
本次改动是**纯附加、有默认值**的，递增版本号会平白引入一次
"磁盘格式破坏性变更 + 全部读点 + 全部夹具"的迁移。

**什么时候才必须递增**：把 `idem_key` 从"可选"改成"必填"，或改
`TABLES` 的 `id_field`/`id_kind`，或改变任何**已存在字段**的含义。

### §3.3 ⚠️ 混合版本运行期间，**老写入方仍然会重复记账**

字段是新的：一个**尚未升级**的进程写下的行**不带 `idem_key`**，
于是它逃过唯一性断言。在滚动升级（多实例、新旧版本并存）的窗口里，
§1.3 那个竞态**仍然存在**。

**这一点正是提案 B（§6）不可被提案 A 取代的理由**：B 把幂等键写在
`note` 的**文本标记**里，而 `note` 是老字段 —— 老版本写下的行**同样带标记**，
所以 B 的判重对**所有**行都有效，与写入方的版本无关。

> **结论：A 是加固，不是替代。两者都留着。**
> `note` 里的标记是"跨版本可用但靠解析"的那一层；
> `idem_key` 字段是"有结构、有唯一性断言"的那一层。

---

## §4 迁移与回滚方案（⚠️ 本仓库**不是 git 仓库**）

`D:\Incubator\agentflow` 不是 git 仓库（`git rev-parse` 退出码 128 ⇒
`noai_gate.py --git` 恒为 `unknown(2)`）。所以**没有"改动集"这个客观事实，
也没有 `git revert` 这道后悔药**。回滚只能靠文件级备份 + 事件流重放。

### §4.1 实施前的备份（**必做，且必须落在仓库之外**）

```text
<backup>/schema.py            # 改之前逐字节复制
<backup>/store.py
<backup>/data/usage_ledger.json
<backup>/data/events.jsonl
<backup>/data/counters.json
<backup>/noai-approvals.json  # 若同时刷新了批准台账
```

### §4.2 回滚步骤与**它自己的陷阱**

| 步骤 | 动作 |
|---|---|
| R1 | 用备份覆盖 `schema.py` / `store.py` |
| R2 | 用备份覆盖 `data/` 的三件套（若本轮跑过数据操作） |
| R3 | `python -m agentflow.cli verify` ⇒ 应回到改动前的结论 |

> ⚠️ **回滚陷阱（本轮新发现，请复核人确认）**：
> `row_from_dict` 按 `__dataclass_fields__` **过滤**未知键。所以**回滚代码之后**，
> 一次 `agentflow rebuild` 会把账本行上的 `idem_key` **静默丢掉**
> （`rebuild` 走 `row_from_dict` → `to_dict()`，字段不在老 dataclass 里就消失）。
>
> - 正常读改写走的是 `Tx.rows()`（**原始 dict**，不过滤）⇒ 字段能存活；
> - **只有 `rebuild` 会丢它。**
>
> **后果**：回滚之后不要跑 `rebuild`；若必须跑，要知道 `idem_key` 会没了。
> **但保护不会消失** —— `note` 里的标记还在，提案 B 的判重照样生效。
> 这正是 §3.3 "两者都留着"的第二个理由。

#### §4.2.1 📌 **实测更正**（保留上面原文，不删历史）

> 上面那段是**推断**，不是实测。本轮用真 `Store.rebuild()` 把三种情形都跑了一遍，
> 结论与原文**不一致**，现按实测更正。装置与原始输出：
> `D:\Incubator\temp\b1_rebuild_idem_key.py`（`python D:\Incubator\temp\b1_rebuild_idem_key.py`）。
>
> **`rebuild` 的真相是一句话：快照 := 事件流折叠结果。** 折叠时
> `state[t][id] = {事件行里不在 canonical 的键} ⊕ {当前代码的 canonical 值}`
> （`store.py::rebuild` 的 `merged` 那三行）。于是"会不会丢"只取决于两件事：
> 事件行里有没有这个键、**当前跑的代码**认不认这个键。
>
> | 情形 | 事件里 `idem_key` | 快照里 `idem_key` | 跑的代码 | rebuild **实测**结果 |
> |---|---|---|---|---|
> | ① | `settle-t-0001` | `settle-t-0001` | 新版 | **`settle-t-0001`**（原样存活） |
> | ② | 缺 | `settle-t-0001` | 新版 | **`""`** —— 值丢了（被 canonical 的默认值覆盖），键名还在 |
> | ③ | 缺 | 缺 | 新版 | **`""`**（没有凭空生成） |
> | 对照 | 带一个谁都不认识的 `_diag` | — | 新版 | **`keepme`**（非 canonical 的未知键被原样保留） |
> | 回滚仿真 | `settle-t-0001` | `settle-t-0001` | 老版（`row_from_dict` 不认这个键） | **`""`** —— 值丢了，键名留下 |
>
> **三处更正**：
>
> 1. **"只有 `rebuild` 会丢它"是错的。** 老代码的那次 **重建**之所以丢值，
>    是因为 `row_from_dict` 把事件行里的这个键**过滤掉了**（于是它不算 canonical，
>    值以 canonical 的空默认值为准）。机制确实是原文说的"按 `__dataclass_fields__`
>    过滤"，但**不是"合并把字段删掉"** —— 对照行证明合并会**原样保留**未知键。
> 2. **"正常读改写 ⇒ 字段能存活"也是错的，方向恰好相反。** 本轮的读改写仿真里，
>    老代码的一次 `Tx.rows()` → `tx.upsert()` 把键**真的写没了**：
>    `Tx.rows()` 给的是原始 dict（字段在），但**老代码写回时不会带上它**
>    （`UsageEntry(**{k: v for k in raw if k in 老 __dataclass_fields__})` 之后 `to_dict()`）。
>    所以真正的丢失点是**读改写**，不是 `rebuild`。
> 3. **快照从来不是重建的来源。** 情形 ② 证明"快照上独有、事件里没有"的东西
>    一律不保 —— 快照只是投影，`events.jsonl` 才是真源。
>
> **回滚时到底会不会丢、靠什么兜底**（可直接引用的结论）：
>
> - **事件里带 `idem_key` 且跑的是新版代码 ⇒ 不丢**（情形 ①）。
> - **事件里带、跑的是老版代码 ⇒ 值会丢；键名留下**（回滚仿真）。
> - **事件里本就不带 ⇒ 无论如何都没有**（情形 ②、③）。
> - **兜底与代码版本无关**：`note` 里的 `settle-` / `idem-` 标记是**老字段**，
>   老写入方会写、老读取方读得到 ⇒ 提案 B 的锁内判重
>   （`TokenMeter.charge_once` 的 `row_with_idem_key`）**始终有效**，
>   `scripts/usage_ledger_audit.py` 的发现与清洗也始终有效。
>   该脚本 `--apply` 会**同时压实事件流**并做回放自证 —— 这正是"只删快照不持久"的解药。
> - 因此**纪律不变**（结论对、理由换了）：回滚之后不要跑 `rebuild`；
>   若必须跑，`idem_key` 的**值**会没，但**保护不会没**。


### §4.3 存量重复数据的清洗

本轮已交付（**不在禁改区**，AI 可独自做）：

```text
python scripts/usage_ledger_audit.py --root <工作区>            # 只检查（默认，一个字节都不改）
python scripts/usage_ledger_audit.py --root <工作区> --apply --backup-dir <目录>
```

三态退出码 `0 clean / 1 requires_action / 2 unknown`。它处理了一个**不显然的陷阱**：

> `usage_ledger.json` 只是快照，`data/events.jsonl` 才是可重放的真源。
> **只把重复行从快照里删掉是不持久的** —— 下一次 `Store.rebuild()` 会按
> `upsert` 事件把它们**原样装回来**，而那时脚本早就"成功"退出了。
> 所以 `--apply` 同时压实事件流，并做一次**回放自证**
> （在压实后的事件流上按 `rebuild` 的同一规则折叠，断言与清洗后的快照一致）。

本仓库实测：**7 个 `usage_ledger.json` 全部是空表**（各 40 字节）
⇒ **本仓库无需清洗**；该脚本是给真实部署用的。

---

## §5 缺失的检测不变量（`verify.py`，**也在禁改区**）

见 §1.4：现有判据**抓不到**本缺陷。建议在 `verify_all` 里新增一条：

```diff
--- a/src/agentflow/verify.py
+++ b/src/agentflow/verify.py
@@ 主控编队 / 花销 / 评测口径（tasks / usage_ledger / eval_results）
     usage = store.rows("usage_ledger")
+    # ---- 幂等键的唯一性（"同一笔账被记了两次"的**唯一**自动防线）
+    #
+    # 为什么必须新增而不是复用 duplicate_id：重复记账的**两行 usage_id 不同**，
+    # 所以按主键数重复永远不响；而 tasks.tokens 与账本汇总是**一起**虚高的，
+    # 所以 usage_task_total_mismatch 也不响 —— 它们仍然"相等"，只是相等的是错的数。
+    seen_idem: dict[str, str] = {}
+    for u in usage:
+        k = str(u.get("idem_key") or "").strip()
+        if not k:
+            continue
+        if k in seen_idem:
+            rep.issues.append(Issue(
+                "error", "usage_ledger", u.get("usage_id"), "duplicate_idem_key",
+                f"幂等键 {k} 出现两次（{seen_idem[k]} 与 {u.get('usage_id')}）⇒ "
+                "同一笔账被记了两次，花销与预算翻倍",
+            ))
+        else:
+            seen_idem[k] = str(u.get("usage_id"))
```

> **复核要点**：新增一条检查与"把判据改宽"是**相反**方向的操作（不会让审计变松），
> 但它仍然改的是"不变量检查的判据本身" ⇒ 按 `.noai-paths` 落在 `auth-audit` 类。
> 请确认它**真的挂在 `verify_all` 的返回里**（只定义不接线 = "加了检查"这句话是假的，
> `NOAI-REVIEW-REGISTER.md` §2.1 第 13 条已经踩过一次这个形态）。

---

## §6 提案 B（**已由 AI 落地**，不在禁改区）—— 本次的真正修复

| 文件 | 改动 | 在禁改区吗 |
|---|---|---|
| `src/agentflow/tokenmeter.py` | 新增 `charge_once()`（**锁内判重 + 入账**）、`marker_of` / `note_tokens` / `row_with_idem_key`；`charge()` 与它共用行构造 | ❌ 不在 |
| `src/agentflow/modelcost.py` | `charge_reply` 改走 `charge_once`；`idempotency_key` 委托 `marker_of`；`_find_by_marker` 降级为**纯快速通道**并改为 token 精确比对 | ❌ 不在 |
| `src/agentflow/conductor.py` | `_charge_and_settle` 改走 `charge_once(idem_key=marker_of("settle", task_id))`；`tasks.inputs` 的标记保留为快速通道 | ❌ 不在 |

**B 满足全部验收标准**（§8），且**不需要任何禁改区授权**。
A 让这件事从"靠 `note` 的文本 token 判重"升级为"表上有结构、有唯一性断言"。

---

## §7 复核要点（**给 2 名 reviewer 的逐 hunk 清单**）

先跑（`unknown` 绝不是 `clean`）：

```text
python scripts/noai_gate.py --check-consistency
python scripts/noai_gate.py --check-approvals --paths src/agentflow/schema.py src/agentflow/store.py src/agentflow/verify.py
python scripts/noai_gate.py --baseline --paths src/agentflow/schema.py src/agentflow/store.py src/agentflow/verify.py   # 登记 hash（不写 reviewers）
```

| # | 位置 | 必须逐行确认的问题 | 判错的后果 |
|---|---|---|---|
| 1 | `schema.py` `UsageEntry.idem_key` | 默认值是不是 `""`？是不是 dataclass 字段（而不是 `field(default_factory=...)`）？ | 老快照读不回来 / 序列化形状变 |
| 2 | `schema.py` `UsageEntry.validate` | 首尾空白断言是否**只**拒绝空白，不拒绝空串？ | 空串被拒 ⇒ 历史行全非法 ⇒ 整表提交炸 |
| 3 | `schema.py` `validate_table` | 唯一性断言是否**只在 `key_val` 非空时**执行？ | 同上 |
| 4 | `schema.py` `validate_table` | 报错信息里是否同时给了**两个** `usage_id`？ | 出错时无法定位那两行 |
| 5 | `schema.py` | `SCHEMA_VERSION` 是否**保持 1**？ | 递增 ⇒ 全部旧工作区读不出来 |
| 6 | `store.py` `Tx.insert_unique` | 冲突时是否**只 return False、一个字节都不写**（不 `mark_dirty`、不 `_record`）？ | 重放也会写事件 ⇒ 快照与事件流分家 |
| 7 | `store.py` `Tx.insert_unique` | 是否**没有**自己 `acquire` 锁？ | 改变加锁顺序 ⇒ 死锁面 |
| 8 | `store.py` | `LOCK_ORDER` 是否**未被改动**？ | 数据毁灭级 |
| 9 | `store.py` | `alloc_id` 是否**未被改动**？冲突路径是否确定不调它？ | 重放消耗 ID ⇒ 永久空洞 |
| 10 | `verify.py` | 新判据是否**真的挂在 `verify_all` 的返回里**？ | "加了检查"是假的 |
| 11 | `verify.py` | 新判据对**空 `idem_key`** 是否跳过？ | 历史行全部报错 ⇒ 审计被噪音淹没 |
| 12 | 三处 | 是否**没有任何地方**把唯一性判断放在 `store.tx` **之外**？ | 窗口原样存在，而代码看起来有约束 |

签字（`scope` 必须具体到符号；写"看过了"等于没看）：

```text
python scripts/noai_gate.py --approve src/agentflow/schema.py \
    --reviewer "<姓名1>" --scope "UsageEntry.idem_key + UsageEntry.validate + validate_table 的唯一性断言" \
    --note "<结论>"
```

**2 名** reviewer（FC-27 写死 = 2：1 名与"作者自己再看一遍"在结构上无法区分）。

---

## §8 验收判据（**可判定**）

| # | 判据 | 命令 / 证据 | 状态 |
|---|---|---|---|
| ① | 同一幂等键并发提交 N 次 ⇒ 账本**只有 1 行** | `python -m pytest tests/test_usage_ledger_idempotency_mp.py -q` | ✅ **已满足**（提案 B） |
| ② | **只扣一次费/额度** | 同上：总 `tokens_total == 1500`（不是 N×1500） | ✅ **已满足** |
| ③ | 重复请求返回**幂等结果** | 同上：N−1 个 `charged=False, reason="duplicate"`，且 `usage_id` 指向同一行 | ✅ **已满足** |
| ④ | **不报 500**，且重放**不消耗 ID** | 同上：全部进程 `ok=True`；`test_charge_once_duplicate_does_not_burn_an_id` 断言计数器不变 | ✅ **已满足** |
| ⑤ | 装置本身**能变红**（负控） | `test_negative_control_distinct_keys_write_n_rows`：不同的键必须落 N 行 | ✅ **已满足** |
| ⑥ | 竞态窗口**真的被压到过** | `test_reply_mode_really_exercises_the_race_window`：4/4 进程都经过 `postread` 屏障 | ✅ **已满足** |
| ⑦ | 存量重复可发现、可清洗、**清洗扛得住 `rebuild`** | `tests/test_usage_ledger_audit.py::test_cleaning_survives_a_real_rebuild` | ✅ **已满足** |
| ⑧ | 表级唯一性由存储层断言 | 提案 A 实施后：`validate_table` 抛"重复的幂等键" | ⏳ **待人工实施** |
| ⑨ | 审计能报出重复幂等键 | 提案 §5 实施后：`verify` 报 `duplicate_idem_key` | ⏳ **待人工实施** |

---

## §9 这份提案**做不到**的事（必须一起读）

1. **它不是 git。** 没有"改动集"，`--git` 恒为 `unknown(2)`；回滚靠文件级备份，
   而"备份是什么时候做的"没有任何机器可读的记录。
2. **hash 一致 ≠ 实现正确。** `--baseline` 只钉住"批准的这一版就是盘上这一版"。
3. **提案 A 不覆盖老版本写入的行**（§3.3）：滚动升级窗口里仍有重复记账。
   只有等所有写入方都升级完，字段级唯一性才是完备的。
4. **`note` 里的键仍然是文本。** 即使 A 落地，只要还有一行靠 `note` 标记判重，
   "自由文本里出现同形 token"这个理论风险就还在（已用 token 精确比对把概率压到很低，
   但**不是零**）。彻底解决要等字段成为唯一判据、标记退化为给人看的注释。
5. **清洗会留下 `usage_id` 空洞**，`verify` 会报 `id_gap`（warning）。
   这是**如实登记的代价**，不是清洗的失败。
6. **本提案未经任何人工走查**（`reviewers_total = 0`）。
   一份"写得很像已经想清楚了"的提案，正是 FC-27 说的那种最容易被跳过的形态。
