# E/F/G/H 角色与 I8–I12 交互 —— 设计 (v1.0)

> 本文件是 `DESIGN.md`（A/B 基线）、`DESIGN-TOOLS.md`（工具层 + C/D 基线）、
> `DESIGN-INTERACTIONS.md`（I1–I7）之后的**第四份**。
> 前三份的结论不变；本文件只加**新角色**与**新交互**，以及 I1–I7 落地后暴露出的调整。

---

## 0. 为什么要加四个角色

A/B/C/D 覆盖了"文献 → 知识 → 分析 → 问题"这条链，但**数学研究的产出不是"问题"**，
而是**证据、攻坚过程、稿件、与对稿件的独立复核**。这四样东西的性质完全不同：

| 角色 | 产出 | 它最容易犯的错 | 结构性对策 |
|---|---|---|---|
| **A** 检索 | 文献 | 把"没搜到"说成"没有" | `outcome` 受控词表（`ok`/`no_results`/`search_failed`/`gave_up`） |
| **B** 整理 | 概念、关系 + 引文 | 把模型编的引文当原文 | `quote_verified` 三态 + 逐字回验 |
| **C** 分析 | 报告 | 把"没枚举完"说成"没有更多" | `truncated` 显式字段（I1） |
| **D** 研究 | 问题、结论 | 把"查不到"写成"研究发现" | L1/L2/L3 溯源 + `checked` 三态（I1） |
| **E** 实验 | **证据** | **把"算对了"说成"证明了"** | `evidence_kind` 受控词表 + **schema 拒绝计算类方法拿 `proof`** |
| **F** 攻坚 | **过程** | 无限循环 / 把"卡住"说成"解决" | 三维预算 + `stalled` 必填 `best_partial` |
| **G** 撰写 | **稿件** | 写出听起来合理但没有出处的断言 | `Document.validate` 拒绝无引用断言 |
| **H** 审校 | **发现** | **审校者自己的判断没有证据** | `ReviewFinding.evidence` 必填非空 |

**最后一行是本项目最贵的一课**：上一阶段的评审里，评审方提出的一条"缺陷"
（"medium 置信度泄漏进了正文"）**是错的**，是实现方拿证据顶回来才纠正的。
若审校记录可以只写"这里有问题"而不给依据，审校就会变成**另一种幻觉的来源** ——
而且因为它站在更高的位置，**更难被纠正**。

---

## 1. 三条把"过度声称"变成写入期错误的硬约束

这三条都不是文档里的告诫，而是 `schema.py` 里的 `validate()`，
**违反即拒绝落库**：

### 1.1 E：计算类方法**永远**拿不到 `proof` 等级（FC-22）

```python
if self.method != "formal" and self.evidence_kind == "proof":
    raise ValueError(...)
```
`method ∈ {numeric, symbolic, exhaustive_search}` 时 `evidence_kind` 只能是
`cross_check` 或 `heuristic`。要主张"已证明"，必须 `method="formal"` **且**给出
`verifier_output`（检查器原始输出）。

**为什么必须机械执行**：论文 `test/main.pdf` 第 404 行自己写着
"No numerical output is used as a proof" —— 而这句话之所以要写，正是因为
**数值对了几千个点就想说"证明了"是这一行最自然也最危险的动作**。

### 1.2 F：子目标只有拿到 `proof` 级证据才允许 `closed`（FC-22）

```python
if st == "closed" and not sg.get("proof_experiment_ids"):
    raise ValueError(...)
```
有数值支持但无证明的子目标只能标 `supported_not_proved` ——
**这个状态是刻意单列的**，因为"有数值支持"与"已解决"在数学上不是一回事。

### 1.3 G：`cross_check` 的断言必须自带"不构成证明"（FC-22）

```python
if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
    raise ValueError(...)
```
这句话**由结构强制，不靠人记得写**。`AgentG.compose_claim` 会自动填上
`tool.doc_tools.CROSS_CHECK_DISCLAIMER`，而 H 会精确匹配这个常量 ——
若允许多种写法，审校就只能靠语义判断，而"靠语义判断"正是要避免的东西。

---

## 2. 四个角色的接口

### 2.1 E —— 数值实验与形式化验证

```
run_experiment(claim, claim_key, script_path, *, params, method, for_question_id, timeout) -> dict
check_formal(claim, *, script_path) -> dict          # 无后端 → checked=False, reason="no_backend"
evidence_for(claim_key=None, *, for_question_id=None) -> dict
```

**证据等级推导规则**（唯一权威，写在 `run_experiment` 的 docstring 里）：

| 情形 | `result` | `negation_kind` |
|---|---|---|
| `exit_code != 0` | `inconclusive` | `no_local_evidence` |
| 脚本打印了 `REPRO_RESULT: {...}` 且它说 `supports` | `supports` | `not_proved` |
| 同一行说 `refutes` + 给了 `counterexample` | `refutes` | `disproved` |
| 脚本没打印那一行 | `inconclusive` | `no_local_evidence` |

**脚本自报 `evidence_kind="proof"` 一律被降级为 `cross_check`** 并记进 `notes` ——
让被判定的对象自己当判官，是这一层最容易被绕过的地方。

### 2.2 F —— 多轮难题攻坚

```
create_plan(problem, problem_key, *, for_question_id, subgoals, budget, depth, parent_plan_id) -> dict
step(plan_id) -> dict
status(plan_id) -> dict
```

**三维预算（FC-18）四类键缺一不可**：`max_rounds`（生命周期总量）/
`max_parallel_subgoals`（瞬时并发）/ `max_persist_attempts`（单点重试）/ `max_depth`（嵌套深度）。
只有总量没有并发 ⇒ 一轮可以无限扇出；只有并发没有总量 ⇒ 扇出可以无限持续。

**`step()` 按 `owner` 分派，且只做框架内真实存在的事**：

| owner | 动作 |
|---|---|
| `E` | 有 `script_path` 就调 `AgentE.run_experiment`，把 `experiment_id` 记进 `experiment_ids`；`evidence_kind=="proof"` 时同时记进 `proof_experiment_ids` |
| `A` | 过 `interactions.admit_search_request` 闸门后提交检索请求 |
| `B` | 过 `interactions.admit_reprocess_request` 闸门后提交重抽取请求 |
| `C`/`D`/`F` | **记录一条 `outcome="no_change"` 的轮次**，`detail` 写明"需要 C/D/F 的推理，本框架尚未接线自动推理 ⇒ **未推进**" |

最后一行是刻意的：**不允许把"没做"写成"做了但没结果"**。
一个"假装在思考"的攻坚循环比一个不存在的循环更危险，因为它会产出一堆
看起来在推进的轮次记录。

**终止**：轮数用尽 ⇒ `status="stalled"` 且 **`best_partial` 必填**。
"绝不谎报成功"不等于"什么都不报"。

### 2.3 G —— 论文撰写

```
compose_claim(text, *, citations, evidence_kind, section, is_negative, negation_kind) -> dict
register_dependency(used_by, kind, label, *, source_lit_id, source_experiment_id, page_range, quote, status, status_reason) -> dict
build_document(kind, title, *, claims, sections, open_problems, out_path) -> dict
revise(doc_id, *, fixed_findings, new_claims, note) -> dict
```

**G 的渲染强制包含三张表**（不靠人记得写）：

1. **证据等级统计**：`proof` / `cross_check` / `heuristic` 各多少条 —— 这是 FC-10 的三分档，不是单一通过率；
2. **否定分类**：已证否 / 未证明 / 未搜索 各多少条（FC-25）；
3. **依赖表**：`external_unavailable` 的行必须显眼。

**依赖闭合的第一道闸在 G 自己**：`register_dependency(status="closed")` 时，
G 必须真的去 `literature` / `experiments` 表核对该 ID 存在。
schema 只能检查"字段非空"，**"这个 lit_id 真的存在"必须由 G 用真实数据核**。

### 2.4 H —— 审校（**只读**）

```
review(doc_id, *, round_no) -> dict
verify_fixes(doc_id, *, round_no) -> dict
```

**H 的工具面全部 `side_effect ∈ {"none","read"}`。** 理由不是洁癖：
若审校者能直接改，它就同时是"发现者"与"修正者"，
于是**"发现问题"与"掩盖问题"在结构上无法区分**。

**告警分级（FC-13）—— 两句话，必须记牢**：

- **"表里已记录的缺陷被重算确认" ⇒ `warning`**（例如 `external_unavailable` 的依赖：
  那是**已经知道的边界**，不是谎报）
- **"表里记录与重算事实矛盾（谎报）" ⇒ `error`**

若不这样分，红灯会被训练成背景噪音，于是真正的 `error` 也会被忽略。

---

## 3. 新增交互 I8–I12

| 交互 | 是什么 | 为什么需要 | 终止条件 | 负控 |
|---|---|---|---|---|
| **I8** G↔H 复审闭环 | G 出稿 → H 审 → G 修 → H 复审 | "写"与"审"必须由**结构上不同**的权限面承担 | `max_review_rounds`（默认 2）；error 全 fixed 才能 `accepted`；超限标 `unresolved_review` 且**必须列出未解决项**（不许隐藏） | 注入一条无引用断言 → H 必须报 `unsupported_claim`+`error` |
| **I9** F↔E 子目标外包 | F 把可数值判定的子目标派给 E，拿 `experiment_id` 决定子目标状态 | 攻坚循环需要"外部证据"才能推进，而证据必须带等级 | `max_persist_attempts` | 只有 `cross_check` 证据的子目标**不得** `closed` |
| **I10** D↔F 升级 | D 判定某问题"多轮未收敛且证据相关" → 升级为 F 的攻坚计划；反向 F 发现新缺口 → 生成检索请求（过 I7 闸门） | 问题的**难度分层**：有的缺口一次检索就能补，有的要攻坚 | F 的三维预算；升级本身不设额外轮数 | 证据不相关的问题**不得**被升级（否则 F 被无意义的难题填满） |
| **I11** E→D 反例回流 | E 得到 `result="refutes"` → 生成 `priority="high"` 的问题给 D（"论断 X 被数值反例否定"），反例本身存为可复现的代码+输出 | 反例是**最强的一种信息**：它直接否定一条已入库的知识 | 一条反例对应一个问题（按 `claim_key` 去重） | `inconclusive` 的实验**不得**触发回流 |
| **I12** G→verify 依赖闭合 | G 每引用一条外部定理就登记 dependency；`verify` 新增 `dangling_dep` 检查 | 把假设当公理会**静默放大结论范围**（FC-23） | —— | `closed` 但指向不存在的 lit/exp → **必须**报 error |

### 3.1 I12 在真实论文上的实例（这是本轮最漂亮的一条）

论文 `test/main.pdf` 的 Theorem 1.5 依赖 "companion book [6, Thm. 6.5]" 给出的
`Spec S̃_m = [−m, m]`。而：

- 论文自己在 Remark 1.6 说这个结果**是引用来的**，本文未重证；
- 参考文献 `[6]` 只写了 "Companion book on quotient lattices, tori and periodic graphs,
  vol. 11, Theorem 6.5"，**连出版信息都没有**；
- 因此**我们无法独立验证这个前提**。

本框架把它登记为 `status="external_unavailable"` + `status_reason`，
于是"我们没有独立验证 Theorem 1.5 的这个前提"变成一条**可查询的事实**，
而不是藏在引文角标里。H 会给它 `warning`（已知边界，不是谎报），
而若有人把它登记成 `closed` 却不给来源，H 会给 `error`。

---

## 4. I1–I7 落地后暴露出的调整（本轮实测）

### 4.1 字面矛盾判据的**假阳性率**必须被量化，并且**不许驱动状态**

实测：25 条真实论文关系，旧判据报出 **6 条 `suspect`（24%）**，**没有一条是真矛盾**。
根因两个：

1. **逻辑错误**：条件 `only_a != only_b`（`only_x = 命中肯定式 and 未命中否定式`）
   把"**提到肯定式**"与"**压根没提这个词**"当成两种相反态度。
   中文 `("是","不是")` 的"是"无处不在（"等号是公开问题"）⇒ 大量误报。
2. **裸否定标记不是否定主张**："**不必**用数值搜索"、"**No** numerical output is used
   as a proof" 都命中否定标记，但它们不是对立主张。

**修正**：判据分两档 —— `strong`（一方明确肯定 **且** 另一方明确否定）/
`weak`（仅否定标记出现与否不一致）。**只有 `strong` 允许驱动 `status="suspect"`**；
`weak` 进 `weak_signals` 作为线索。

**为什么这条修正比"多报一点"更重要**：24% 的报警率意味着 `suspect` 这个标记
**不再指示任何东西** —— 而"假报警比不校验更糟，因为它会训练人忽略告警"。

### 4.2 **派生态绝不能被当成输入**（一次完全静默的失效）

`detect_contradictions` 原先直接读行里的 `concept_pair_key`。但 `relations` 表存的
字段名是 `concept_group_key` ⇒ 对**直接从表里读出来的行**（C 的 `contradictions()`、
任何脚本），该函数**恒返回 `[]`**，不报错、不告警，看起来就像"没有矛盾"。

**修正**：字段缺失时就地用 `concept_pair_key(concept_ids)` 推导 ——
与 `RelationGraph.group_counts` 的做法一致（"由 `concept_ids` 现场推导才是唯一权威"）。

**一般化教训**：任何"缓存的/派生的"字段一旦被当作输入，
忘记计算它的那一方就会**静默拿到空结果**。所以：
**派生态要么就地推导，要么在装配期断言它存在**（不许有第三种）。

### 4.3 闸门必须在**真实数据**上量过假阳性率才能上

这两条缺陷都不是单元测试能发现的：单元测试里我构造的是"人为矛盾"，
它当然通过。**它们只在把 25 条真实关系过一遍时暴露**。
所以：**每个新增闸门都必须在 ≥20 条真实样本上跑一遍并记录触发率**。

---

## 5. 待决问题

1. **I10 的"多轮未收敛"如何判定？** 本轮：`researching` 状态连续 N 轮（默认 2）无状态变更
   且 `assess` 判据仍不满足 ⇒ 升级给 F。N 的取值没有理论依据，是经验值。
2. **H 能否发现"数学错误"？** **不能**，本轮明确不做。H 只判"稿件有没有把自己说清楚"
   （有没有引用、证据等级有没有被夸大、依赖有没有闭合）。
   把这两件事分清是审校可被信任的前提 —— 一个声称"我检查了证明"的自动审校器是危险的。
3. **E 的 `formal` 方法在本环境无法使用**（无 Lean/Coq），因此 `evidence_kind="proof"`
   这条路径只能靠**手工构造的测试数据**验证，不能端到端跑通。这一点必须如实报告。
4. **F 的 `owner ∈ {C,D,F}` 子目标不会被自动推进**（见 §2.2）——
   这意味着"攻坚"目前只能被"外部工具型子目标"驱动。这是本轮**最大的能力边界**。
