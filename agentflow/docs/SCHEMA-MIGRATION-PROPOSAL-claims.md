# SCHEMA 迁移提案：`documents.claims` 的 §8.3 字段（**待人工批准并实施**）

> **现状导读（不构成判据）· 本文是提案/历史状态**：本仓当前分层结构的逐项事实（含路径与复跑命令）见
> [`../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md`](../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md)。
> 本文只作现状导读、**不构成判据**，**也不要把本文写成现状**。本文出现的路径一律**相对工作区根**（`D:\Incubator`）。
>
> ⚠️ **本文多处把"提案"当成了"已经这样了"，逐处更正如下（截至 2026-09-30 的实际状态见正文 / 代码，本文是提案）**：
> - §0/§1 说"`src/agentflow/schema.py` 一个字都没动" ⇒ 这一句**仍然成立**（实测 `SCHEMA_VERSION == 1`，
>   且 `agentflow/src/agentflow/schema.py` 里查不到 `CLAIM_KINDS` / `CLAIM_STATUSES` /
>   `ALLOWED_USE_KINDS` / `NUMERIC_EVIDENCE_KEYS`）。**但这不等于本提案的落点还空着**：
>   那四张词表今天定义在 `agentflow/src/agentflow/claimanatomy.py`（`CLAIM_KINDS` / `CLAIM_STATUSES` /
>   `ALLOWED_USE_KINDS` / `NUMERIC_EVIDENCE_KEYS`），§2.3 要的"第二处改为转发"因此**仍是提案**，
>   而 §5 说的"判据层 + 呈现层"（`claimanatomy.py` / `gates.py` / 工具层）**已在盘上**。
>   所以读本文时不要把"schema.py 未动"读成"整件事没做"。
> - §5 的"本轮已经落地的部分"把 `claimanatomy.py` / `gates.py` / `doc_tools.py` / `review_tools.py`
>   那一批写成**当时刚落地** ⇒ 那是历史状态；它们今天都在盘上。
>   **判据仍是本提案自己列的读法**：以 `agentflow/src/agentflow/` 下的实现与测试为准，
>   **本文不构成判据**。

> ⚠️ **这份提案不是已落地的改动。** 它由 AI 编写，**必须由人批准并实施**。
> 它与 `AGENTS.md` 的 FC-27（禁 AI 区）直接相关，理由见 §0。
>
> 状态：**未实施**（`src/agentflow/schema.py` 一个字都没动）。
> 作者：AI agent（本轮任务）；批准人：**（待填）**；`required_approvals = 2`。

---

## §0 为什么这件事不该由 AI 独自做

`src/agentflow/schema.py` 命中 `.noai-paths` 的 `[category: schema-migration]`：

> `src/agentflow/schema.py  [category: schema-migration] `SCHEMA_VERSION` 与 `TABLES`：
> 表结构与版本号 —— 改它等于改磁盘格式契约`

FC-27 的原始论证（`AGENTS.md` 逐字引 `draft/LESSONS-工程经验清单（FC-01…FC-27）.md:716`）：

> "IF 改动落在禁改区（认证/授权/支付/加密/迁移/CI 配置/对外 API 破坏性变更）
> THEN 必须人工编写或人工逐行走查，且需要 **2 名 reviewer approve**
> ——否则会：**测试全绿、上线即越权**。"

把这句话套到**这份**提案上，"测试全绿、上线即越权"的具体形态是：

| 若由 AI 独自实施 | 会发生什么 | 为什么测试不会红 |
|---|---|---|
| 把 `status` 加进 `Document.validate` 的必填集 | 磁盘上**每一条历史 claim 立刻非法**，`store.tx` 提交整张表时炸 | 测试夹具全是新造的，**没有一条测试读老数据** |
| 给缺失字段填默认值（如 `status="待精化"`） | "我们**没问过**这条断言的生命周期"被永久固化成"它处于待精化" | 默认值是**合法值**，任何断言都过得去 |
| 改 `SCHEMA_VERSION = 1 → 2` 而不写迁移 | `validate_table` 对老文件直接抛"schema_version 应为 2，收到 1" ⇒ **全部数据读不出来** | 单测只造 2 的新文件，从不读 1 的旧文件 |
| 加 `role="作废"` 之类的受控词表却不审计读点 | 渲染层/verify/H 三处各自决定怎么处理未知状态，**三份判据** | 三处都能跑，谁都不报错 |

这四行都不是"写错了代码"，而是**判据本身的形状**变了，而"测试覆盖的是我们想得到的情形"
（`AGENTS.md` 逐字）。所以本提案只提供**确切的 diff 与向后兼容分析**，实施与批准留给人。

**AI 这一轮做了什么**（不属于禁改区，因此可以独自做）：见 §5 的"当前落点"。

---

## §1 现状（实测）

| 项 | 值 | 出处 |
|---|---|---|
| `SCHEMA_VERSION` | `1` | `src/agentflow/schema.py:18` |
| claims 的容器 | `Document.claims: list[dict]`（**嵌套 dict，不是 dataclass**） | `schema.py:1043` |
| 校验位置 | `Document.validate()` | `schema.py:1051-1108` |
| 它认识的 claim 键 | `claim_id` / `text` / `citations` / `evidence_kind` / `disclaimer` / `is_negative` / `negation_kind` | 逐行读 `:1069-1106` |
| 未知键的处理 | **只读它认识的键，不拒绝未知键** | `:1069-1106` 逐行；`row_from_dict("documents", ...)` 把 `claims` 当**不透明 list** 传给 `Document`（`:1740-1741`） |
| 结论 | **新增 §8.3 的 12 个字段今天就能写、能读、能过 JSON 往返** | 实测：`tests/test_claimanatomy.py::test_full_claim_passes_schema_validate_and_store_round_trip`、`::test_documents_json_keeps_the_new_keys_verbatim` |

所以**本轮不需要改 `schema.py`**；改它的收益是"存储层强制"，代价是"动磁盘格式契约"。
下面的提案把这件事的**全部代价**写清楚，供人判断值不值得。

---

## §2 提案 A（**推荐**）：只加**受控词表 + 交叉检查**，不加必填

### §2.1 精确 diff

```diff
--- a/src/agentflow/schema.py
+++ b/src/agentflow/schema.py
@@
-SCHEMA_VERSION = 1
+# ⚠️ 1 → 2：见 docs/SCHEMA-MIGRATION-PROPOSAL-claims.md §3（向后兼容与迁移）
+SCHEMA_VERSION = 2
@@
 EVIDENCE_KINDS = ("proof", "cross_check", "heuristic")
+
+#: 断言的**数学类型**（draft/17 §8.3 第 1028 行）。检查脚本靠这个前缀建索引，
+#: 且编号规则是"按类型内连续" —— 所以它必须是受控词表，不是自由文本。
+#: **受控词表的唯一来源**（DEVELOPMENT.md §2.3）：claimanatomy 里的同名常量
+#: 改为从这里 import（见下方 §2.3 的"第二处"）。
+CLAIM_KINDS = ("定义", "定理", "命题", "引理", "推论", "例", "注", "反例")
+
+#: 断言的**生命周期**（draft/17 §8.3 第 1030 行，U0 的确切取值集合）。
+#: ⚠️ 它与 `EVIDENCE_KINDS`（**证据类型**）是**两个正交的轴**，不是同一件事：
+#:   evidence_kind 回答"支撑它的证据是哪一类"；
+#:   status        回答"这条断言当前处于什么生命周期"。
+#: `作废` 不是一种证据，而是"这条断言被撤销了"——本框架此前表达不了这件事。
+CLAIM_STATUSES = ("证", "验", "待精化", "作废")
+
+#: 论文线的**硬性降级规则**（draft/17 §8.3 第 1035 行；RP/00_STANDARD.md:105-110）：
+#: 只有数值支撑的结论不得出现在摘要/主结果，必须降为 Remark + 命令。
+ALLOWED_USE_KINDS = ("主结果", "Remark only", "移入 open")
+
+#: `numeric_evidence` 的**四元组**（§8.3 第 1032 行）。键名固定，多一个少一个都不可判定。
+NUMERIC_EVIDENCE_KEYS = ("script", "range", "n_cases", "n_counterexamples")
@@
 class Document:
@@
-    #: 断言列表。每个元素：
-    #: ``{"claim_id","section","text","evidence_kind","citations":[...],
-    #:    "is_negative","negation_kind","disclaimer"}``
+    #: 断言列表。每个元素**至少**含：
+    #: ``{"claim_id","section","text","evidence_kind","citations":[...],
+    #:    "is_negative","negation_kind","disclaimer"}``，
+    #: **可选**含 draft/17 §8.3 的字段：
+    #: ``{"kind","status","proof_location","numeric_evidence","counterexamples",
+    #:    "frozen","freeze_reason","allowed_use","scope_caveat","revision_hash",
+    #:    "errata_ids"}``。
+    #: ⚠️ 可选字段**一律不进 `validate()` 的必填集**：磁盘上已有大量老行没有它们，
+    #: 设成必填 = 让全部历史稿件立刻非法（见 SCHEMA-MIGRATION-PROPOSAL-claims.md §3）。
     claims: list[dict] = field(default_factory=list)
@@
             if c.get("is_negative") is not True and c.get("negation_kind") is not None:
                 raise ValueError(
                     f"claims[{cid}] 不是否定型断言却带了 negation_kind={c.get('negation_kind')!r}"
                     "（会让'否定'的计数虚高）"
                 )
+
+            # ================= draft/17 §8.3 的生命周期字段 =================
+            # 判据与 claimanatomy.status_evidence_consistency 必须**逐字一致**
+            # （写入期与审校期对同一份稿件给出相反结论，就是 FC-03 的分裂）。
+            # 这里只做"取值域 + 两个轴"的硬拦；**必填一律不加**（历史数据兼容）。
+            kind = c.get("kind")
+            if kind is not None and kind not in CLAIM_KINDS:
+                raise ValueError(f"claims[{cid}].kind 必须是 {CLAIM_KINDS} 之一，收到 {kind!r}")
+            status = c.get("status")
+            if status is not None and status not in CLAIM_STATUSES:
+                raise ValueError(
+                    f"claims[{cid}].status 必须是 {CLAIM_STATUSES} 之一，收到 {status!r}。"
+                    "注意 status（生命周期）与 evidence_kind（证据类型）是**两个轴**"
+                )
+            if status is not None and ek is not None:
+                # 已知的不一致组合（三条，逐条给理由；判不了的一律**不拦**）
+                if status == "证" and ek != "proof":
+                    raise ValueError(
+                        f"claims[{cid}] status='证' 却 evidence_kind={ek!r}："
+                        "「证」必须有 proof 级证据（FC-22）"
+                    )
+                if status == "验" and ek == "proof":
+                    raise ValueError(
+                        f"claims[{cid}] status='验' 却 evidence_kind='proof'："
+                        "有形式化核验却只标「验」，会让证/验两档计数同时失真"
+                    )
+            if status == "作废" and not (
+                c.get("errata_ids") or str(c.get("freeze_reason") or "").strip()
+            ):
+                raise ValueError(
+                    f"claims[{cid}] status='作废' 但没有 errata_ids 也没有 freeze_reason："
+                    "作废必须说清为什么（参考体例用稳定 ID 指勘误，如 `E-01`）"
+                )
+            allowed = c.get("allowed_use")
+            if allowed is not None and allowed not in ALLOWED_USE_KINDS:
+                raise ValueError(
+                    f"claims[{cid}].allowed_use 必须是 {ALLOWED_USE_KINDS} 之一，收到 {allowed!r}"
+                )
+            if c.get("frozen") is True and not str(c.get("freeze_reason") or "").strip():
+                raise ValueError(
+                    f"claims[{cid}] 标了 frozen=True 却没写 freeze_reason："
+                    "只标冻结不说原因，接手的人无从判断该不该解冻"
+                )
+            ne = c.get("numeric_evidence")
+            if ne is not None:
+                if not isinstance(ne, dict):
+                    raise ValueError(f"claims[{cid}].numeric_evidence 必须是对象（四元组）")
+                missing_ev = [k for k in NUMERIC_EVIDENCE_KEYS if k not in ne]
+                if missing_ev:
+                    raise ValueError(
+                        f"claims[{cid}].numeric_evidence 缺 {missing_ev}："
+                        "四元组缺一即不可复跑/不可判定覆盖范围"
+                    )
         if self.review_rounds < 0:
             raise ValueError("review_rounds 不能为负")
```

**总计**：3 处新增受控词表常量（+1 处 4 元组键名）、`Document.validate` 内新增约 **45 行**、
`SCHEMA_VERSION` 1→2、`Document.claims` 的字段注释扩充。

### §2.2 diff 覆盖了 §8.3 的全部 12 个字段吗

| 字段 | 提案 A 是否强制 | 为什么 |
|---|---|---|
| `claim_id` | 已强制（现状） | — |
| `kind` | 取值域 | 词表外的值无法被索引脚本理解 |
| `statement` | **不强制** | 磁盘键是 `text`（见 §4）；改名属于破坏性变更 |
| `status` | 取值域 + 交叉检查 | 两个轴的一致性必须有唯一判据 |
| `proof_location` | 不强制 | 免费文本或代号，**没有可机械判定的语法**（`file:line` 与 claim_id 都合法） |
| `numeric_evidence` | 给了就必须完整（四元组） | 缺键的"四元组"不可复跑，比没有更糟（**看起来有**） |
| `counterexamples` | 不强制 | `[]`（搜过、没有）与缺失（没搜）是两件事，强制会抹掉这个区别 |
| `frozen`/`freeze_reason` | 成对强制 | "冻结但不说原因"是**没交代**，不是隐私 |
| `allowed_use` | 取值域 | 它是降级规则的载体，自由文本读不了 |
| `scope_caveat` | 不强制 | 可空字段（§8.3 逐字"str，可空"） |
| `revision_hash` | 不强制 | 由渲染/审校期计算，不是作者填的 |
| `errata_ids` | 不强制（但 `status='作废'` 时它是两个合法原因之一） | 见下 |

**刻意不做的事**（写清楚"不做什么"和"做什么"一样重要）：

1. **不加任何必填**。理由见 §3.2 —— 这是本提案最重要的一个决定。
2. **不把 `status` 与 `evidence_kind` 建立满射**。`待精化` 可以配任何证据类型；
   `作废` 可以配任何证据类型（撤销与证据类型无关）。只拦 3 种**已知**不一致。
3. **本提案不碰 `review_findings`**。§8.4 的 G10 需要 `line`/`verbatim_quote`/`minimal_fix`/
   `maths` 四个字段；补它们是**另一份**提案（风险面不同：`review_findings` 是落库表、
   有去重键 `_dedup_key`）。
   ✅ **那另一份提案后来落地了**（观测 2026-09-27，`X-96.3-3` 更正本句）：`P-9` 候选 A 之后
   `schema.ReviewFinding` 带上了 `axis` / `line` / `verbatim_quote` / `maths`（"最小修法"那一格
   与 `suggestion` 对齐）⇒ **"本项目结构性不可判"这句话不再成立**：`gates.gate_g10` 今天只对
   "键不全的行"（契约生效日前的历史行、或尚未补键的产出方）报 `unknown` 并逐条列出缺哪些键，
   键齐全的行按 §8.4 逐字判。本提案自己"不改这张表"的判断不受影响。

### §2.3 改完之后必须同步的**第二处**（FC-03）

`schema.py` 一旦定义这三张词表，**`claimanatomy.py` 里的同名常量必须改为转发**
（否则就是"同一个词表两份定义"）：

```diff
--- a/src/agentflow/claimanatomy.py
+++ b/src/agentflow/claimanatomy.py
@@
-CLAIM_KINDS = ("定义", "定理", "命题", "引理", "推论", "例", "注", "反例")
-CLAIM_STATUSES = ("证", "验", "待精化", "作废")
-ALLOWED_USE_KINDS = ("主结果", "Remark only", "移入 open")
-NUMERIC_EVIDENCE_KEYS = ("script", "range", "n_cases", "n_counterexamples")
+from .schema import (
+    ALLOWED_USE_KINDS,
+    CLAIM_KINDS,
+    CLAIM_STATUSES,
+    NUMERIC_EVIDENCE_KEYS,
+)
```

这一步**必须与 §2.1 同一笔提交**完成，而且必须加一条断言把两者钉成**同一个对象**
（`tests/test_claimanatomy.py::test_evidence_kinds_are_not_a_second_copy` 就是这个形态）：

```python
assert CA.CLAIM_KINDS is S.CLAIM_KINDS        # 同一个对象，不是相等
assert tools.ROLES is schema.ROLES            # DEVELOPMENT.md §3 纪律 2 的原型
```

**为什么这处同步不能忘**：`scripts/lint_rules.py` 的 R005 抓的是"写死的**完整角色名单**"，
它**抓不到**"两张同名的中文词表"。也就是说这一步漏了，**没有任何检查会红**
（这正是 `DEVELOPMENT.md` §3 纪律 2 说的那种"没有任何报错，只是少了一点东西"）。

---

## §3 向后兼容分析

### §3.1 磁盘上已有的老 claim 行长什么样（实测）

```json
{
  "claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
  "evidence_kind": "proof", "citations": ["rel:0000"],
  "is_negative": false, "negation_kind": null, "disclaimer": ""
}
```

（`data/documents.json` 与全部测试夹具都是这 8 个键。见
`tests/test_agent_h.py:83`、`tests/test_tools_audit_fixes.py:53-67`、`tests/test_core_audit_efgh.py:602`。）

**缺**：`kind` / `status` / `proof_location` / `numeric_evidence` / `counterexamples` /
`frozen` / `freeze_reason` / `allowed_use` / `scope_caveat` / `revision_hash` / `errata_ids`。

### §3.2 默认值是什么，以及**为什么这个默认值不会把"没做"伪装成"做了"**

**答案：不设默认值。缺字段就让它缺着。**

这是本提案唯一正确的选择，理由是它直接对上 `DEVELOPMENT.md` §3 纪律 1
（三态纪律）与 FC-01：

> "布尔无法区分'未校验'与'校验失败'，而这两者需要**完全不同的处置**。"
> "每一次的后果都是**下游把'我们没查'读成了'查了没有'**。"

若给 `status` 设默认值 `"待精化"`：

| | 真实的两种情形 | 设默认值后它们变成 |
|---|---|---|
| ① | 作者**明确判断**这条断言还要精化 | `status="待精化"` |
| ② | 作者**从未过问**这条断言的生命周期（老数据、或新字段还没接线） | `status="待精化"`（**被默认值伪造出来的**） |

于是"这份稿件里有 12 条待精化的断言"这个数字**从诞生那一刻起就是假的**，
而它看起来完全合理 —— 因为默认值本身是一个合法值。任何门、任何审校、
任何报告都**不会**发现这件事。

**因此本提案的做法是**：缺字段 ⇒ 缺着；需要判它的地方**返回第三态**：

- `claimanatomy.status_evidence_consistency(None, "proof")` ⇒ `("未知", "`status` 缺失 ⇒
  生命周期轴**没有值可判**（**没判**，不是『判过、一致』）")`；
- `claimanatomy.ClaimSpec.decided is False`（`undecided_reason` 必非空）；
- 于是 H 与门**看得见"这件事没登记"**，处置是"要求补齐"而不是"当成待精化"。

这一条在代码里的形态是 `presence_of()` 的三态：
`"present"`（写了，包括 `false`/`[]`）/ `"empty"`（写了空串/`null`）/ `"absent"`（没这个键）。
设计要点：**`{"frozen": false}` 与"没有 `frozen` 键"必须是两件事** ——
前者是"作者明确说了不冻结"，后者是"作者没提这件事"。

### §3.3 `SCHEMA_VERSION` 1 → 2 的后果

```python
def validate_table(table: str, doc: dict) -> None:
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{table} schema_version 应为 {SCHEMA_VERSION}，收到 {...}")
```
（`schema.py:1691-1692`）

⇒ **每一份老快照都会突然读不出来**。所以版本号**不能单独改**，必须与迁移一起：

| 步骤 | 做什么 | 可回滚？ |
|---|---|---|
| 1 | `store.Store.rebuild()` 从 `events.jsonl` 重放（**事件日志是权威**，快照是派生物） | ✅ 只要 `events.jsonl` 完好 |
| 2 | 若某些部署**没有** event 日志（手工编辑过的库），用**读写分离**过渡：读时接受 1 与 2，写时一律写 2 | ✅ 回滚 = 换回旧代码（2 兼容读） |
| 3 | 迁移**不做**任何"补默认值"的动作（同 §3.2 的理由）：老行就让它缺字段 | ✅ |

**建议**：`SCHEMA_VERSION` 的修改与"新字段的强制"**分开两次发布**：

- **第一次**（低风险）：只加受控词表常量与"**打了这些字段才检查**"的取值域校验
  （即 §2.1 的 diff 去掉 `SCHEMA_VERSION` 那一行），`SCHEMA_VERSION` **不动**。
  这一版对老数据**完全无感**，但让新数据一旦带上这些字段就受检。
- **第二次**（高风险，需人主导）：`SCHEMA_VERSION = 2` + 读兼容层 + 迁移脚本。

**这份提案建议先做第一次**，因为它的收益（新数据受检）几乎全部到手，
而它的不可逆性（磁盘格式契约）为零。

---

## §4 ⚠️ 一处**必须由人拍板**的破坏性变更：`text` → `statement`

§8.3 的字段名是 `statement`，我们的磁盘键是 `text`。**两者是同一件事**，
所以只能有一条字段名（否则 `{"text": A, "statement": B}` 能让下游看到两个不同的断言，
而**没有任何地方会报错** —— FC-03 的形态）。

本轮的处置（**不需要改 `schema.py`**，已落地）：

- **判据层的正名 = `statement`**（规格逐字要求的就是它）；
- `text` 是它的**历史别名**，只在两个地方出现：
  ① `claimanatomy.migrate_claim()` / `to_storage_claim()`（唯一的迁移点）；
  ② `schema.Document.validate`（禁 AI 区，逐字读 `c.get("text")`）。
- 写入路径：判据用 `statement` → 落库前 `to_storage_claim` 转回 `text`；
- 读取路径：`claimanatomy.claim_statement()` 同时认得两种键。

**若要真正改名（把磁盘键也变成 `statement`）**，那是**破坏性变更**，需要人拍板：

```diff
-            if not str(c.get("text") or "").strip():
-                raise ValueError(f"claims[{i}] 的 text 不能为空")
+            if not str(c.get("statement") or c.get("text") or "").strip():
+                raise ValueError(f"claims[{i}] 的 statement（历史键名 text）不能为空")
```

并对**每一个**读 `text` 的点做同样处理。已知读点（实测）：

| 读点 | 文件 |
|---|---|
| `Document.validate` | `schema.py:1075` |
| `scan_claim` 的取值 | `doc_tools.py`（**本轮已改为 `claimanatomy.claim_statement`**） |
| `scan_document` 的取值 | `review_tools.py:131`（**本轮已改**） |
| 渲染层 | `doc_tools.render_markdown`（**本轮已改为 `claim_statement`**） |
| 测试夹具 | 多处（`tests/test_agent_h.py:83` 等） |

**建议**：**不改**。理由：改名的收益是"字段名与参考体例逐字一致"（形式价值），
代价是"磁盘格式破坏性变更 + 全部读点 + 全部夹具"（FC-27 的迁移类）。
判据层的正名已经让新代码与规格对齐，而别名只有一处转换 —— 这个折中更便宜。

---

## §5 本轮**已经落地**的部分（不改 `schema.py`，因此不属于禁改区）

| 落点 | 内容 | 测试 |
|---|---|---|
| `src/agentflow/claimanatomy.py` | 12 字段的**声明表** `CLAIM_FIELDS`（类型/必填/取值域/理由/出处）+ 三态判定 | `tests/test_claimanatomy.py`（49 例） |
| `src/agentflow/gates.py` | G1–G15 门引擎（声明表 `GATES` 15 门齐全 + 报告） | `tests/test_gates.py`（51 例） |
| `tools/doc_tools.py` | `compose_claim` 走 `claimanatomy` 的判据；渲染层排除 `status='作废'` | 同上 |
| `tools/review_tools.py` | `scan_document` 增补生命周期/降级检查；新增 `review.report` | 同上 |
| 存储层 | **未改**：新字段今天就能写、能读、能过 JSON 往返 | `test_full_claim_passes_schema_validate_and_store_round_trip` |

**也就是说：本轮交付的是"判据层 + 呈现层"，缺的是"存储层强制"。**
这个缺口的后果要如实登记：

- 一条**绕过 `doc.build_document`** 直接写盘的行（手工编辑、旧版本程序、rebuild 前的残骸）
  可以带 `status="已证"` 这种非法值，而 `schema.validate` **不拦它**；
- 它会被 `claimanatomy.validate_claim` 与 G14 抓到（**审校期**），但那时坏数据已经在盘上；
- 这正是 FC-09 的口径："**后面的闸门不能假设前面的闸门一定跑过**" ——
  所以缺口是**风险**，不是**缺陷**。是否值得用"动磁盘格式契约"来消除它，由人决定。

---

## §6 批准记录（**留空待填**；`scripts/noai_gate.py` 的批准台账要读它**之前**人类必须真的逐行走查**）

> `AGENTS.md` 第 3 条：**需要 2 名 reviewer 批准**。
> 为什么是 2 而不是 1：1 名 reviewer 与"作者自己再看一遍"在**结构上**无法区分。
> 台账（`.noai-approvals.json`）记的是 `sha256` 钉住的**那一版**，不是"某个文件" ——
> 本提案被修改后，旧批准**自动失效**。

```text
reviewer_1 = （待填）    日期 = （待填）    逐行走查结论 = （待填，"看起来没问题"不算）
reviewer_2 = （待填）    日期 = （待填）    逐行走查结论 = （待填）
采取的方案 = （A 第一次 / A 第二次 / 二者都做 / 不做）
理由 = （待填）
```

批准之后**才**执行 §2.3 的同步（`claimanatomy` 改为转发），
并跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python -m pytest -q
python scripts/lint_rules.py
python scripts/noai_gate.py --paths src/agentflow/schema.py src/agentflow/claimanatomy.py
```

最后一条**必须**打印 `[requires_human] required_approvals=2` 且**退出码 1** ——
它命中禁改区是**预期**的，不是故障。`requires_human` 绝不等于 `clean`。
