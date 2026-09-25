# 14 · 本地先例对照：Danus

> **本文件怎么得来的**：对 `C:\Users\ysc20\Danus` 做**只读**观摩（`Get-ChildItem` 列目录 + `read`/`grep` 读文件）。
> **未运行 Danus 的任何代码，未发起任何网络 / LLM / 子进程调用。**
> **P1 验收基线**：`D:\Incubator\test\test1` 的 12 张表 / 8 角色（A–H）/ I1–I12 / FC-01…FC-27，
> 依据 `draft/13-数学研究多智能体协同框架-正式设计草案.md`（下称 **《草案》**）与 `test/test2/LESSONS.md` §6（下称 **《FC》**）。
>
> **证据规则（全文遵守）**：每条结论后给 `文件:行号`。只从 README/文档读到、未在代码中核实的，标
> `（据文档，未在代码中核实）`。查过但没找到的，写 **未核实**，不猜。

---

## 1. Danus 是什么

**一句话**：Danus 是一个**自动化数学证明搜索系统**——一支 codex worker 蜂群并行找证明，一个**冷启动 LLM 验证者**是正确性的唯一权威，通过验证的结果积累成一张**内容寻址的事实图（fact graph）**，最后由一条独立的写作流水线把事实图渲染成论文或人类进度报告。
（出处：`README.md:11-17`、`docs/concepts.md:10-18`）

**它与我们最根本的差别，一句话**：Danus 优化的是"**证明能不能被搜出来、能不能规模化地搜**"；我们优化的是"**没做与做了但没结果能不能互相伪装**"（《草案》§1.1）。所以 Danus 把全部纪律压在**一道写入门**（`fact_submit`）上，我们把它摊在**8 个权限面 + 12 张表的 `validate()` + I1–I12 的终止条件**上。这不是成熟度差异，是目标差异——第 8 节展开。

### 1.1 模块清单与职责

| 模块 | 职责 | 关键文件（行数） | 我们的对应物 |
|---|---|---|---|
| `danus/core/` | **真相层**：内容寻址事实图 + 三层记忆 + schema | `factgraph.py`(316)、`global_memory.py`(134)、`local_memory.py`(69)、`glossary.py`(119)、`schema.py`(130)、`bm25.py` | `schema.py` + `store.py` + 12 张表 |
| `danus/gateway/` | **唯一入口**：角色门控 MCP，6 个工具 | `roles.py`(45)、`server.py`(304) | `tools/base.py:for_role` + `tools/__init__.py`（55 工具） |
| `danus/verify/` | **唯一写入门**：冷启动证明验证 HTTP 服务 + 确定性前置检查 | `prechecks.py`(208)、`launcher.py`(265)、`agent/AGENTS.md`(239) | E 的 `evidence_kind` 推导 + H 的 `review.scan_document` + `verify.py` |
| `danus/execution/` | **worker 蜂群**：每 worker 轮次循环 + 落盘布局 + 脚手架 | `loop.py`(343)、`layout.py`(251)、`scaffold.py`(217) | F 的三维预算循环（`agent_f.py`） |
| `danus/orchestration/` | `danus` CLI 动词（list/new/assign/finalize/start/status/stop） | `cli.py`(26803B) | 无（我们是库，无 CLI 生命周期） |
| `danus/strategy/` | **方向咨询**：elaboration → 强推理模型 → master_guidance；花销台账 | `config.py`(210)、`ledger.py`(55)、`transport.py`(31349B) | D 的问题台账 + `research_request_ledger.json` |
| `danus/write_paper/` | 事实图 → 可发表 LaTeX 论文；**整篇论文再验证** | `assemble.py`(1142)、`server.py`(1832)、`paper_math_verify.py`(206)、`paper_chunked.py`(462) | G 撰写 + `verify.py` 的 `dangling_dep` |
| `danus/human_summary/` | 事实图 → 无 id 的进度报告 PDF（**任何时刻可跑、不被门禁**） | `assemble.py`(182)、`server.py` | 无对应物 |
| `danus/observability/` | 只读仪表盘（事实图 DAG / 记忆通道 / 咨询花销） | `app.py`(365) | 无对应物 |
| `danus/authoring/` | 两个渲染器共用的"一次性隔离 codex 驱动" | `common.py`(159)、`driver.py` | 无对应物 |
| `danus/integrations/` | arXiv 定理检索（Matlas） | `matlas.py` | A 的 `search.*` |
| `agents/contracts/` + `agents/skills/` | **契约与技能是数据、不是 Python**（9 个 worker 证明技能、3 个 verify 技能、论文角色提示词） | `worker.md`(298)、`write-paper/roles/*` | A–H 各角色的提示词 + 工具面 |

Danus 自述的八层模型与不变量见 `ARCHITECTURE.md:16-32`、`:73-101`。

---

## 2. 数据模型对照

### 2.1 Danus 的"表"

Danus **不叫表**，它有 3 个存储 + 2 类元数据文件：

| Danus 存储 | 物理形态 | 单元 | 是真相吗 | 出处 |
|---|---|---|---|---|
| local memory | `<worker_dir>/local_memory/{notes,events}.jsonl`，追加 | "我做了什么"的粗日志 | ❌ 私有草稿 | `local_memory.py:17,28-45`；`DATA_MODEL.md:50-81` |
| global memory | `<project>/global_memory/<kind>.jsonl`，**一个 kind 一个文件** + `_status.jsonl` | **claim + evidence** 的 finding，含死路 | ❌ 只是"awareness" | `global_memory.py:29-33,85-92`；`DATA_MODEL.md:85-104` |
| **fact graph** | `<project>/fact_graph/facts/<16hex>.md` + `glossary.json` + `revocation_log.jsonl` + `_revoked/` | **已验证 fact**（statement + proof + DAG 边） | ✅ **唯一正确性来源** | `factgraph.py:110-118`；`DATA_MODEL.md:211-231` |
| 花销台账 | `<project>/spend/consult.jsonl` | 一次咨询一行 | ❌（但"钱只记在这一处"） | `strategy/ledger.py:15-42` |
| 论文台账 | `paper/VERIFY_LEDGER.md` | 一个 unit 一段 | ⚠️ 是 **deliver 的门** | `paper_math_verify.py:53-56,150-168` |

**这 3 个存储合起来，大致相当于我们的 `literature`+`concepts`+`relations`+`experiments`+`documents` 五张表的功能**，但形态完全不同：Danus 用"**一个 kind 一个 JSONL 文件 + BM25**"代替"**一张表 + schema 校验 + 锁**"。

### 2.2 逐条对照：它有什么我们没有

| Danus 的字段/机制 | 出处 | 我们的现状 | 判断 |
|---|---|---|---|
| `fact_id` = 对 `{problem_id, sorted(predecessors), sorted(glossary), normalized(statement), normalized(proof)}` 的 SHA256 前 16 hex | `schema.py:104-130` | 我们的 ID 是发号器分配的 `NNNN`（`store.py` 的 `alloc_id` + `counters`） | **形态不同，各有取舍**：它的内容寻址带来**天然判重**与**不可变节点**；我们的发号器带来**可预期的 4 位空间**与**"发号与建行必须同锁"**（《草案》§4.3）。**不建议替换**（见 §6-I8、§7-W6） |
| `predecessors` + `descendants()` + `revoke()` **级联撤销**（撤一条，所有传递依赖它的都搬进 `_revoked/`，并留 `revocation_log.jsonl`） | `factgraph.py:254-268,296-316` | 我们只有 `dependencies` 表的**闭合检查**（`dangling_dep`），**没有"某条外部定理被推翻 ⇒ 依赖它的结论全部作废"的传播** | ⭐ **真缺口**。见 §6-I1 |
| `glossary_introduces` + 四层可见性（全局术语表 ∪ 项目术语表 ∪ 本 fact ∪ 各前驱）+ `undefined_symbols()` 机械检查 | `factgraph.py:271-293`；`glossary.py:98-119`；`DATA_MODEL.md:257-271` | 我们**没有符号定义覆盖率**这一概念（`concepts` 表存概念，但不校验"断言里用到的符号有没有定义"） | ⭐ 有价值。见 §6-I2 |
| `external_refs` **刻意不参与 fact_id**，并提供 `set_external_refs()` 只改那一行 | `schema.py:115-119`；`factgraph.py:231-252`；`DATA_MODEL.md:272-281` | 我们的 `relations.quote_verified` 与 `literature.download.status` 是**可变的**，但它们是行内字段，没有"哪些字段不进内容指纹"的显式划分 | ⭐ 可借的形式。见 §6-I3 |
| `status` 是**追加事件 + 读时折叠**（last write wins），不是就地改 | `global_memory.py:85-111`；`DATA_MODEL.md:161-172` | 我们 `events.jsonl` 已经是"整行 upsert + `rebuild()` 末次写赢"（《草案》§4.4），**我们更强** | ✅ 已覆盖，见 §6-C1 |
| `trusted` 台账状态：单元**本身已是一条被验证过的 fact**，如实呈现、不单独再验 | `paper_math_verify.py:153-160` | 我们无对应物 | ⭐ 见 §6-I4 |
| `ignorable` vs `must-fix` 两级 findings（**缺 class 默认 must-fix**） | `server.py:1590-1607` | 我们有 H 的 `error`/`warning`/`info`（FC-13），**更强**（两句话规则 + 落库级负控） | ✅ 已覆盖，见 §6-C2 |
| 论文台账 `attempts` / `last_verdict` / `last_checked_utc` | `paper_math_verify.py:72-82` | 我们 `documents.review_rounds` + `review_findings.round`，**语义等价且更强**（我们记 finding 级） | ✅ 已覆盖 |
| 花销台账（append-only + 容错求和 + **$0 也记** + 每次返回累计总额） | `strategy/ledger.py:1-12,22-55` | FC-19 **未落地**：我们连 `token_meter` 都没有（《草案》§7） | ⭐ 见 §6-I5 |
| 11 个受控 kind（含 `dead_end` / `obstacle` / `master_guidance` / `elaboration`） | `schema.py:26-38` | 我们**没有"负结果"的第一类通道**（C 的 `cold`/`gaps` 报告、F 的 `blocked` 子目标算半个） | ⭐ 见 §6-I6 |

### 2.3 逐条对照：我们有什么它没有

| 我们的东西 | 出处（《草案》） | Danus 的现状 | 谁更强 |
|---|---|---|---|
| **12 张表 + 每张表的 `validate()` 硬约束（违反即拒绝落库）** | §4.1、§4.2 | 只有 5 条机械约束：kind 受控（`global_memory.py:56-57`）、status 受控（`:87-88`）、verifiable 需 evidence（`:60-61`）、拒绝已撤销前驱（`factgraph.py:147-149`）、paper_id 单段路径（`assemble.py:79-88`）。**没有行级 schema、没有交叉检查、没有 `schema_version`** | **我们强得多** |
| **多表事务 + `LOCK_ORDER` 死锁排序 + 原子写 + `events.jsonl` + `rebuild()` 信息量守恒** | §4.3、§4.4 | 全部没有。`append_jsonl` 是裸追加；`gm.set_status` 与 `gm` 主体是两个文件，读时折叠 | **我们强得多** |
| **`evidence_kind ∈ {proof, cross_check, heuristic}` + "计算类方法拿不到 proof"的 schema 硬约束** | §6.2（`schema.py:758/765/771/902/1008`） | **完全没有**。`grep` 全 `danus/**/*.py` 搜 `evidence_kind\|cross_check\|negation` **零命中**；Danus 的判据是二元的 `correct/wrong` | **我们强得多**（这是 §7-W1） |
| **三态纪律 `True/False/None` + 受控 `reason`**（引文 / OCR / 溯源 / 预算 / 检索终局 / 形式化 / 依赖闭合 / 问题台账，八处） | §6.1 | 部分：`fact_id` 有 `None` 与 `write_error` 两态（`server.py:236-245`）、`verdict="error"` 区分"服务不可用"（`:194`）、`status` 有 `unverified/verifying/verified/refuted`（`schema.py:42-45`）。但**没有一处是 `bool\|None` 的三态判定字段**，也没有受控 reason 枚举 | **我们强** |
| **`SEARCH_OUTCOMES` 受控词表（`no_results` vs `gave_up`）** | §3.1 | Danus 无检索请求表；检索是 worker 直接调 `search_arxiv_theorems`，**没有"搜了没有"与"没搜"的区分** | **我们强** |
| **`dependencies` 表 + `dangling_dep` + `external_unavailable`（FC-23）** | §4.2(b)、§5 I12 | 有 `predecessors`（**内部**依赖的 DAG，纯 fact_id）+ `external_refs`（**外部**文献的结构化书目），但**没有"依赖闭合性检查"**：没有代码验证某个 `external_refs` 指向的定理是否真的存在/可获取——那是由**验证者提示词**去看的（`verify/agent/AGENTS.md:92-108`） | **我们强**（我们的检查是机械的；它是提示词级的） |
| **I1–I12 十二条带终止条件/预算/负控的交互** | §5 | 有 `DEFAULTS` 类预算（轮次/超时/连续失败：`loop.py:261-264`）与三条策略步骤（`docs/concepts.md:84-96`），但**没有交互规格层** | **我们强** |
| **8 个角色 = 8 个权限面（含 C/H 结构性只读剥离 + `role_filter_notes`）** | §2.3、§8.10 | Danus 是 **3 个角色**（worker/main/verifier），但**权限面是"物理不存在"**：`build_app(role)` 只注册该角色的工具（`server.py:297-304`），未注册的工具**在 MCP 层根本不存在** | **各有长处**：它的隔离更硬（跨进程、跨协议），我们的**分工更细**。见 §6-C3 与 §8 |
| **`research_questions` 问题台账 / `attack_plans` 三维预算 / `review_findings` 审校发现 / `analysis_reports` 只读分析** | §3.4–3.8 | 全部没有对应表。最接近的是 `plan`/`direction`/`obstacle` 三个判断型 kind（散文约定，无 schema） | **我们强** |

### 2.4 一句话结论

**Danus 的数据模型是"薄而尖"的**——它只把两件事做成了不可绕过的结构：① **内容寻址的事实 id**，② **只有验证者能写 fact**。其余一切（findings、计划、死路、指导）都是**受控 kind + 散文约定**，没有 schema 强制。
**我们的数据模型是"厚而平"的**——12 张表每张都有硬约束，代价是没有内容寻址、没有级联撤销、没有符号覆盖检查。
**两者可互补的地方在 §6-I1 / I2 / I3 / I6；冲突的地方在 §7-W6。**

---

## 3. 它的"验证"机制 vs 我们的 `verify.py` + H

### 3.1 Danus 的验证是**两段式**：确定性前置 + 冷启动 LLM 裁决

| 段 | 做什么 | 出处 |
|---|---|---|
| **第 0 段：确定性前置检查**（在**花钱之前**） | ① 空泛性（语句 <10 字符 / 证明 <30 字符 / <5 词 / 去 markdown 噪声后恰好等于 `"qed"`、`"obvious"`、`"trivial"`…）② 硬禁令 **P1**（把 `problem.md` 当数学来源）③ **P3**（"Assume the verified … reductions have narrowed…"这类**无条件前提**，**除非同一段里出现一个 16-hex `fact_id`**）④ **P5**（"by some classical/well-known argument"这类模糊指称） | `prechecks.py:1-16`（两层的设计理由）、`:27-36`（阈值与标记）、`:46-74`（P1/P3/P5 正则）、`:88-120`（空泛）、`:123-180`（三个禁令）、`:183-208`（编排） |
| **第 1 段：LLM 裁决** | 每个 `/verify` **现 spawn 一个全新 codex**（冷启动），读 `AGENTS.md` + 3 个 verify 技能，按 markdown 顺序**逐条**检查每个 lemma/proposition 的逻辑、定理应用、缺失假设、跳跃；外部引用必须用 `search_arxiv_theorems` 查、查不到就用 web search、再找不到就记 `critical_error` | `launcher.py:1-17,201-265`；`verify/agent/AGENTS.md:62-108` |
| **判决规则** | `correct` **当且仅当** `critical_errors == []` **且** `gaps == []`；否则 `wrong` + 非空 `repair_hints` | `verify/agent/AGENTS.md:123-133,166-172` |
| **状态性** | 验证者 **stateless**：什么都不持久化；持久化由 worker 的 `fact_submit` 做 | `verify/agent/AGENTS.md:52-60`；`gateway/server.py:220-232` |

**两段的接口是刻意的**：`prechecks.py:176-182` 明确写"HTTP 服务的前置检查已经在提示词之前拒掉了最露骨的单行违规，**但你要抓跨行、跨段的同类违规**"；`AGENTS.md:235-239` 反过来写"前置检查是确定性正则，**你的职责是抓它漏掉的多行与上下文情形**"。这是一次干净的**正则管可判定、LLM 管需要语境**的分工。

### 3.2 Danus 的验证还多一层：**链条继承检查**（我认为这是它最漂亮的一条）

```
### P3-supplement (chain check)
When a step cites a 16-hex `fact_id`, treat that fact's own `statement` as if it were inlined.
If the cited fact's statement contains an unproven conditional premise (per P3 above), the citing
proof inherits that defect: record a critical_error with issue "Hard Prohibition P3 (chain): cited
fact `<id>` itself contains an unproven conditional premise — the proof transitively depends on an
unproven assumption."
```
（`verify/agent/AGENTS.md:229-233`）

**即**：缺陷会**沿着依赖边传播**。一条证明引用了另一条"自带无条件前提"的事实，引用者**继承**这个缺陷。

### 3.3 与我们的对照

| 维度 | Danus | 我们 | 判断 |
|---|---|---|---|
| **验证者是否重算判决** | 单条 fact：**不重算**，服务原样返回 agent 写的 `verdict`（`verify/README.md:34-36`；`security-and-trust.md:18-20` 明确承认"trust flows from the prompt"）。**整篇论文：重算**（`server.py:1590-1644` 机械派生，缺 class 默认 `must-fix`） | 我们 `verify.py` 是纯确定性重算；H 的 `scan_document` 也是纯函数 | **论文侧我们可以直接借**（见 §6-I7）；单条 fact 侧我们更硬，**不要学它** |
| **前置闸门在花钱之前** | ✅ 有（`prechecks.py`） | ❌ 我们 E 的 `run_experiment` 是本地子进程（不花钱），但 G/H 的 LLM 钩子一旦真接上，**没有"花钱前的确定性拒绝"层** | ⭐ 见 §6-I9 |
| **只加严、从不放松** | ✅ `prechecks.py:1-16` 明说"purely ADDITIVE（只能拒更多，永不接受更多）"；每个开关可 env 关掉 | 我们的 `validate()` 也是拒绝式，但没有"这一层只准加严"的**显式契约与文档** | ⭐ 小改，见 §6-I9 |
| **禁令清单的落地形态** | 三个**可执行的**硬禁令（P1/P3/P5），带正则 + 提示词 + 双段覆盖 + env 开关 | 我们的 `overclaim` 检查（`verify.py:509` + `review_tools`）是**一条**；`unsupported_claim`（无引用）是 schema 层。**没有"模糊指称"这一类的机械禁令** | ⭐ 见 §6-I10 |
| **同一段必须有 16-hex 依据** | ✅ P3 的机械判据（`prechecks.py:143-162`） | 我们的"每条断言必须带 `citations`"是**非空**判据，不是"**同段**有依据"判据 | ⭐ 见 §6-I10 |
| **链条继承缺陷** | ✅ `AGENTS.md:229-233` | ❌ **完全没有**：我们 `dangling_dep` 只查"指向的 ID 存不存在"，不查"指向的那条本身有没有缺陷" | ⭐⭐ **最强的一条点子**，见 §6-I11 |
| **验证者自身无状态 / 冷启动** | ✅ 每次全新进程（`launcher.py:201`），有 per-run 目录 `results/<run_id>/{log.md,verification.json}` | ❌ H 在进程内、store 开着；**没有"每次审校都是全新上下文"的结构** | ⭐ 见 §6-I12 |
| **验证者输出契约的机械校验** | ⚠️ 由**提示词**保证 `verdict ⟺ errors==gaps==[]`；`launcher.py` 只校验"是 dict"，**不校验不变式** | 我们 `validate()` 校验；但 H 的 finding 与 `documents.status` 之间**没有"重算一遍判决"的代码** | ⭐ 见 §6-I7 |
| **验证结果三分档计数**（FC-10） | 只有 `correct/wrong` 二元 + `critical_errors`/`gaps` 两个列表 | 我们 `store.stats()` 有 `quote_verified/quote_unverified/quote_unknown`（FC-10 部分落地） | **半斤八两**，都不完整 |
| **验证失败的归因分离**（FC-15） | ✅ 有：`repair_hints` 与 `undefined_symbols` 是**两个不同字段**（`server.py:236-242`）；`verdict="error"`（服务挂了）与 `verdict="wrong"`（证明错了）**分开**（`:194` vs `:237`）——"服务不可用"不会被记成"证明错误" | 我们也有 reason 细分（12 处） | ✅ 双方都做了，**语义等价** |

---

## 4. 它的编排 / 循环 vs 我们的 A–H + I1–I12

### 4.1 Danus 的循环很简单，只有三层

| 层 | 内容 | 出处 |
|---|---|---|
| **① 战略环**（主控，小时级） | elaborate（写 `elaboration`）→ consult 强推理模型 → 记 `master_guidance` → `danus assign` 给每个 worker → 监控 | `docs/concepts.md:84-96`；`AGENTS.md:71-76` |
| **② worker 轮次循环**（每 worker 一个进程） | 每一轮 = **一个全新的 `codex exec` 会话**，**从持久化的记忆继续**（不是"一个增量"）；轮结束时挂起，循环再起一个新会话 | `execution/loop.py:1-23`；`execution/README.md:27-36` |
| **③ worker 内部的控制环** | 评估状态 → **自适应选技能**（9 个证明技能里挑）→ 行动 → 持久化 → `fact_submit` 验证与修复 | `agents/contracts/worker.md:63-196` |

**停止条件（全部在轮边界检查）**：`.stop` 旗标、`.run_deadline`（epoch 上限）、`DANUS_MAX_ROUNDS`（0=无限）、`DANUS_MAX_CONSEC_FAILURES`（5）。
（`loop.py:303-313`；`execution/README.md:31-34`）

**关键设计立场**：`README.md:138-142` 与 `worker.md:198-203` 明说——**"难问题不是停止的理由"**。主控只有在"所有目标都成了已验证事实**且**路线可信"时才主动停蜂群（`AGENTS.md:84-88`），但**宣布"这就是答案"（`danus finalize`）永远是留给人的分叉**（`docs/concepts.md:127-131`）。

### 4.2 与我们的对照

| 维度 | Danus | 我们 | 判断 |
|---|---|---|---|
| **角色数** | **3**（worker 蜂群同构 + main + verifier） | **8**（A–H，各不同权限面） | 见 §8：**我们的 8 角色不该被压成 3**（`LESSONS.md` §5 的反面清单；且 FC-06 要求"角色即权限面"）。Danus 的 3 角色之所以够用，是因为它只有**一个**子任务类型：证明。见 §7-W7 |
| **同构 worker 蜂群** | ✅ 人手靠 `--roles high:3,xhigh:4` 起 N 个**同构** worker，靠 main 的 `assign` 分工（`scaffold.py:155-195`、`layout.py:232-251`） | ❌ 我们没有"同构 worker 池"概念 | **不适用**：我们的分工是**异构的**（A 检索 / B 整理 / C 只读分析 / D 研究…），不是同一件事做 N 遍 |
| **停止条件** | 4 个（stop 旗标 / deadline / max_rounds / 连续失败） | F 有**四类预算键**（`max_rounds`/`max_parallel_subgoals`/`max_persist_attempts`/`max_depth`，`schema.py:869`）+ `history` 单调 + `stalled ⟹ best_partial` | **我们更强**（FC-18 已落地；Danus 只有"总量式"的上限，**没有并发上限、没有深度上限**） |
| **单任务重试上限** | 只有"连续失败 5 轮就退出循环"（`loop.py:327-330`） | `max_persist_attempts` + 子目标 `blocked ⟹ blocked_reason` | **我们更强** |
| **子任务可降级、整体不谎报**（FC-21） | ⚠️ 部分：一个 worker 轮次失败只累加 `consec_fail`，**继续跑**（`:327-330`）；但**没有"这一轮产出了什么"的如实记录**——只有 `last_rc` 与从日志里刮出来的 `last_fact_id`（`:319-322`、`_parse_last_fact_id` `:132-138`） | 我们 F 的 `_deploy_e` 降级 `blocked` + `blocked_reason` 且继续，`schema.py:899` 强制 | **我们更强** |
| **取消语义**（FC-20） | ✅ **有而且很硬**：Windows Job Object `KILL_ON_JOB_CLOSE` 装住整棵 codex 进程树（node → codex.exe → MCP gateway → pwsh → worker 的 python）、每轮结束 `reap_job`、SIGTERM 处理器 + `kill_tree`（taskkill /T /F 或 killpg）、loop 死掉时 OS 负责收官 | FC-20 **完全未落地**（搜 `cancelled`/`cancel_signal` = 0 命中，`《草案》` §7） | ⭐ **真缺口**。见 §6-I13 |
| **每 worker 的状态落盘** | ✅ 原子写 `.status.json`（state/round/pid/updated_at/last_rc/last_fact_id），状态标签有受控元组（`orchestration/cli.py:289`），`danus status` 的 `stuck?` 是**软信号** | 我们没有"运行期状态文件" | ⭐ 见 §6-I14 |
| **主控不碰数学** | ✅ 结构性保证：main **没有 `fact_submit`**（`roles.py:32-37`） | 我们由工具面剥离保证 C/H 只读（§2.3） | **等价**，双方都是"物理不存在"的做法 |
| **报告/进度可在任意时刻产出** | ✅ `human-summary` **不被 finalize 门禁**，任何时刻可跑，给操作员进度 PDF（`docs/concepts.md:125-126`） | ❌ 我们只有终局的 `research-report.md` / 稿件 | ⭐ 见 §6-I15 |
| **长任务的上下文预算**（FC-17） | ✅ **有真机制**：`paper_chunked.py` 的分块（PLAN 只给陈述 → FILL 给本节全文+他节陈述 → STITCH 确定性），阈值 `DANUS_PAPER_WRITE_CHUNK_CHARS`（默认 80 万字符） | FC-17 未落地 | ⭐ 见 §6-I16 |

---

## 5. 它的"写论文"机制 vs 我们的 G

### 5.1 `paper_math_verify.py` 在校验什么

**它校验的不是"论文里的数学对不对"这一笼统问题，而是三条具体的东西**：

| # | 校验什么 | 怎么做 | 出处 |
|---|---|---|---|
| **1** | **"论文作为独立文本是否自洽"** —— 即**缝合缝（seams）** | 理由写得很清楚：单条 fact 都过了验证，但**论文是另一个制品**：写手重新渲染、合并、省略"显然"的步骤、加"it suffices to…"/"WLOG…"的粘接、内联从未成为 fact 的化简。**这些缝正是"一组正确的 fact 能变成一篇错误的论文"的地方**。所以**整篇文档正文作为一次输入**，送给一个**专用的论文数学验证者**（一次全新的一次性 codex，**无常驻服务、无 fact graph、无切片**），它按顺序读整条 development，判断**自足性 + 正确性** | `paper_math_verify.py:1-26`（理由）、`:186-192`（为什么不切片：切片会既误拒 delta 证明、又掩盖不完备） |
| **2** | **deliver 门（台账中介）** | `VERIFY_LEDGER.md` 是**持久的门**：`deliver_ok()` 要求台账**存在**且**每一行**状态 ∈ `{correct, trusted, overridden}`；否则返回 blockers 列表（含 `"no ledger"`）。主控**读文件、不读自己的记忆** | `paper_math_verify.py:53-56`（8 个状态）、`:150-168`（门） |
| **3** | **尺寸诚实阻塞** | 正文超过 `whole_doc_budget()`（默认 70 万字符 ≈175K token）就记 `too_large`——**一个明确的 blocker**，而不是静默截断；**"按结果分解成自足的部分"是主控的活，工具永不自己切** | `paper_math_verify.py:16-20,194-206` |

**判决的机械派生**（这一条比它的单条-fact 验证更硬）：

> 论文验证者输出一个带 `findings` 的 JSON，每个 finding 有 `class: ignorable | must-fix`。
> **deliverability 是派生的、不是声称的**：`correct` **当且仅当** `must-fix` 为零；任何 must-fix ⇒ `wrong`。
> **`class` 缺失或未知的 finding 默认归 `must-fix`（绝不静默降级一个缺口）**。
> —— `server.py:1590-1607`

而 `must-fix` / `ignorable` 的**定义是叙述性的**：`must-fix` = "一个本科生**无法**自行补上的步骤"；`ignorable` = "一个本科生**能**独立补上的"——**后者永不阻塞交付，只上报给操作员，不要去追**。
（`paper_math_verify.py:60-66`、`server.py:1675-1683`）

### 5.2 写作流水线的其它机制

| 机制 | 做什么 | 出处 |
|---|---|---|
| **三角色最小输入隔离** | writer 拿到**目标闭包的全部 fact** + 风格 + 结构；auditor **只拿 `main.tex` + 台账**（不给 fact、不给风格）；verifier 只拿 `main.tex`（书目）+ 台账 + auditor 的 findings；reviser **完全不给 fact graph**。这是**被测试强制的隔离契约** | `assemble.py:1-29` |
| **PRIME DIRECTIVE（6 条）** | ① 输入里每一条数学断言都必须保留（压缩散文 = 删除数学）② 每条引用都保留、且每条引用都有 key（禁止"well-known"/"by classical results"）③ 禁止编造书目 ④ 保留 preamble（可加包、不可偷偷删）⑤ 编辑宏中性且锁定 ⑥ **不泄漏流水线内部**（fact id、长 hex、文件路径、团队名单）——**唯一允许出现系统名的地方是操作员配置的 disclosure 段**；做不到就发 `\note{[prime/blocker] …}`，**绝不静默违反** | `agents/skills/write-paper/roles/AGENTS.md:7-54` |
| **泄漏门（正则）** | 对产出的 `.tex` 扫：16-hex id、`author:` 前置行、`fact_*` slug、`master_guidance`、`fact_submit`。**注意它刻意不禁 `worker`/`verifier`/`predecessors`**——那些在真实的数学/CS 论文里合法出现 | `server.py:53-63`；扫描器本身 `authoring/common.py:150-159` |
| **分块（超预算时的降级）** | PLAN（闭包**只给陈述**，小）→ FILL（本节 fact 全文 + **其它每一条闭包 fact 的陈述**作 `\ref` 上下文，确定性**覆盖检查**：每条闭包 fact 必须被分到恰好一节）→ STITCH（纯 Python）。**任何一段不 ok 或覆盖失败 ⇒ 诚实失败，绝不吐出半成品论文** | `paper_chunked.py:1-38,50-66` |
| **provenance 映射** | 每段写作都产出一个 `%%%PROVENANCE%%%` 映射（哪段散文由哪些 fact 产生），最终合并 | `paper_chunked.py:24-28`；`server.py:342-375` |
| **编译门是法律** | 不过 `compile_verify.sh`（零 LaTeX error、无未定义引用）的 `.tex` 不算完成 | `roles/AGENTS.md:64-65` |
| **人类报告剥离全部前置元数据** | `human_summary` 的 fact 包里**只留 body 三节**，整个 YAML frontmatter（fact_id/author/predecessors/glossary…）**被剥掉**，不出现任何 id 或 slug——"写手只从数学工作" | `human_summary/assemble.py:8-21` |

### 5.3 与我们的 G 对照

| 维度 | Danus | 我们 | 判断 |
|---|---|---|---|
| **论文级再验证** | ✅ **独立的一次性验证者读整篇文档**，理由是"缝合缝" | ❌ **完全没有**：G 只保证"每条断言有引用"，H 只审"稿件有没有把自己说清楚"（《草案》§1.4 明确"不判定数学错误"） | ⭐⭐ **最强的点子之一**，见 §6-I17 |
| **每条断言带引用** | ✅ 提示词级（PRIME DIRECTIVE #2）+ 泄漏门正则（`fact_` slug 不得到正文） | ✅ **schema 级**（`documents.claims[].citations` 非空，`schema.py:996`） | **我们更硬**（它有被绕过的可能：换个说法就不是"weasel substitution"了） |
| **`cross_check` 必须带"不构成证明"** | ❌ 无此概念（没有 evidence_kind） | ✅ schema 强制 + `CROSS_CHECK_DISCLAIMER` 常量 + H 精确匹配 | **我们强得多** |
| **preamble / 引用 / 宏的保留** | ✅ PRIME DIRECTIVE #1/#2/#4/#5 + `\note{[*/blocker]}` 的**如实阻塞**通道 | 我们没有"编辑纪律 + 阻塞标记"这一层 | ⭐ 见 §6-I18 |
| **禁编造书目** | ✅ 提示词 + 专门的 `reference_audit`（离线，不给工具/网络）→ `reference_verify`（在线，arXiv+web）→ 台账就地更新 | 我们 B 的**引文逐字回验**更强（机械回验 + 三态 + 篡改负控） | **我们强**（我们是回验原文；它是分级审计） |
| **写手不接触流水线元数据** | ✅ 结构性（隔离 codex + 剥离 frontmatter + 泄漏门） | ⚠️ 我们没有"给写手一个干净上下文"的结构；G 在进程内、拿 store | ⭐ 见 §6-I19 |
| **超预算的诚实阻塞** | ✅ `too_large` 是一个明确的台账状态，分解是主控的活 | FC-17 未落地 | ⭐ 见 §6-I16 |
| **交付门在文件上、不在记忆里** | ✅ `deliver_ok` 读 `VERIFY_LEDGER.md`，"读文件、不读记忆" | 我们 I8 的 `error` 全 fixed 才能 `accepted` 是**表驱动**的 | **等价，我们更强**（我们有 finding 级 + 落库级负控） |

---

## 6. ⭐ 值得取用的具体点子

> ⚠️ **编号约定（避免与本框架的 I1–I12 混淆）**：本节用 **`I1`…`I21` 指"建议采纳的点子编号"**，
> **不是**《草案》§5 的交互 `I1`–`I12`。文中凡指后者的地方，都写作"**交互 Ix**"或"`《草案》`§5 Ix"。
>
> 筛选标准：**① 不破坏我们现有结构**（8 角色不合并、三态纪律不放松、证据等级不弱化、依赖闭合不取消）；
> **② 落在具体文件/函数/表字段/某条交互或 FC-xx**；**③ 有明确成本**。
> 每条结论在末尾给 **结论**：`取用` / `部分取用` / `不需要改（已覆盖，对应物在 X）`。

---

### I1 ⭐⭐ 派生"被撤销/被推翻"的**级联传播**（`invalidation` 传播）

- **它是什么**：Danus 的 fact 是一条 DAG 节点，`revoke(fact_id, reason)` 把该 fact **及其全部传递依赖者**搬进 `_revoked/`，并给每一条写一条 `revocation_log.jsonl`（含 `revoked_as_dependent_of`）；`add()` **拒绝接受任何已撤销的前驱**；`descendants()` 走传递闭包。
  `core/factgraph.py:254-268`（descendants）、`:296-316`（revoke）、`:147-149`（拒绝已撤销前驱）、`DATA_MODEL.md:289-290`。
- **为什么有价值**：我们的 `dependencies` 表能发现"**依赖指向一个不存在的 ID**"（`dangling_dep`），但发现不了"**依赖指向的那条东西已经被推翻了**"。数学上这是更严重的一类错误：**一个被数值反例证否的论断（I11 回流）或一条被判定为假的外部定理，会让所有建立在它上面的结论一起作废**——而我们的表此刻仍然全部显示 `closed`，`verify --deep` 也不会报。Danus 把"作废沿依赖边上溯"做成了**数据结构的性质**。
- **落在我们哪里**：`dependencies` 表加一个字段 `invalidated_by`（可空，指向触发作废的 `experiment_id` / `relation_id` / `review_finding_id`）+ `invalidated_at` + `status` 增加一个取值 `invalidated`；`verify.py` 增加两条检查：
  ① `dangling_dep_invalidated`（**error**：一条 `closed` 依赖指向的 `source_experiment_id` 的 `result == "refutes"`，或 `source_lit_id` 已被剔除）；
  ② `stale_dependent`（**error**：某条 `claim` 依赖一条 `invalidated` 的 dependency，但 `documents.status` 仍是 `accepted`）。
  触发点：I11（E 得到 `refutes` ⇒ 回流到 D 时**同时**扫描 `dependencies` 找出所有引用该 `claim_key` 的行，就地标 `invalidated`）；H 的 `verify_fixes` 也应把这批 finding 列为必须处理项。
- **成本**：**中改**（`dependencies` 表加 3 个字段 + `verify.py` 加 2 条检查 + I11 的回流路径加一段传播扫描 + 若干测试）。不动既有 12 张表的语义，不动 `LOCK_ORDER`（`dependencies` 已在其中，`《草案》` §4.3），不新增表。
- **是否值得现在做**：**值得**。它是"矛盾闭环"（I2）与"反例回流"（I11）的**收尾**——现在这两条闭环都在"发现问题"处停住了，没有"作废下游"这一步。这正是 `《草案》` §8.8 那条教训的同一模式：**把"声称"变成"必须交出的东西"**。优先级建议 **P1**。
- **结论**：**取用**（这是本次观摩最可落地的一条）。

---

### I2 ⭐ 符号定义覆盖率检查（`undefined_symbols`）

- **它是什么**：每条 fact 记 `glossary_introduces`（符号 → 定义），项目术语表 `glossary.json` 累积；`fact submit` 在写之前跑覆盖率检查——把 body 里出现的"数学符号样 token"（正则 `glossary.py:36-43`，含 STOPLIST `:45-49`）与**四层可见定义**（全局术语表 ∪ 项目术语表 ∪ 各前驱的 `glossary_introduces` ∪ 本条自己的）求差，返回未定义符号列表。**Advisory（建议性）**，验证者是后备。
  `core/factgraph.py:271-293`、`core/glossary.py:98-119`、`DATA_MODEL.md:257-271`。
- **为什么有价值**：我们的 `concepts` 表能回答"这个概念在库里吗"，但回答不了"**这条断言的正文里用到的符号，有没有人在这个作品链上定义过**"。对 G 来说这尤其相关：**"无引用断言进不了稿件"（`schema.py:996`）挡住了"没有出处"，但挡不住"有出处但那一段的符号读者无从理解"**。这是"断言可读性"的机械判据，比"我觉得这条写清楚了"强。
- **落在我们哪里**：`concepts` 表已有 `definition`/`normalized_name`/`aliases`（据《草案》§4.1 与 §3.2）。加一个**纯函数** `symbols_undefined(text, *, defined: set) -> list[str]`（放 `interactions.py`，**必须过 `assert_store_free`**，因为 I6 风格要求它能在事务内被调用），以及一个 `TABLES` 无关的检查：`verify.py` 新增 `undefined_symbol`（**warning**，不是 error——它是启发式的正则，Danus 自己就标 advisory）。G 的 `compose_claim` 在写 `documents` 前调用一次，把结果记进 claim 的 `notes` 或一个新字段 `undefined_symbols`（**不改 citations 的非空约束**）。
- **成本**：**小-中改**（一个纯函数 + 一条 warning 级 verify 检查 + `compose_claim` 里一次调用）。**注意**：不要照搬它的正则——我们的正文是中文+LaTeX，`glossary.py:36-43` 的 `_INTERESTING` 是英文数学记号调过的，**要重新定 STOPLIST**。
- **是否值得现在做**：**值得，但优先级低于 I1**。建议 **P1**；且**先做"记录不拦"**（warning + 落库），观察触发率后再决定是否升级（这正是《草案》§6.4 的"每个新增闸门都必须在 ≥20 条真实样本上量过触发率"）。
- **结论**：**取用**（形态照抄，正则必须重定）。

---

### I3 把"可变元数据"与"内容指纹"显式分开

- **它是什么**：`fact_id` 刻意**不含** `external_refs`——理由是"它是书目元数据，参考审计员会在事实被验证之后修改它；把它绑进 id 会在每次审计后改 id（并打断 DAG），还会扰动所有已存在 fact 的 id"。`external_refs` 的更新走 `set_external_refs()`，**只改 frontmatter 那一行，body 与 id 不动**。
  `core/schema.py:115-119`、`core/factgraph.py:231-252`、`DATA_MODEL.md:272-281`。
- **为什么有价值**：我们的存储是"行级 upsert + `events.jsonl` 整行事件"，没有内容指纹，所以目前没有这个问题。**但**我们**有一个同类问题**：《草案》§6.3 记载的 `concept_pair_key` 派生态当输入导致 `detect_contradictions` **恒返回 `[]`**（完全静默）——这是"哪个字段是派生的、哪些是权威的"没有显式划分造成的。Danus 的做法提供了一个**可复用的形式**：**在字段级声明"这个字段是可变的/不参与指纹/可以事后就地改"，并给一条唯一写路径。**
- **落在我们哪里**：在 `schema.py` 的字段声明处加一个**轻量标注**（不是新表）：给 `relations.quote_verified`、`literature.download.status`、`dependencies.status_reason` 这类"事后可被修正、且修正不改实体身份"的字段，加一个 `MUTABLE_AFTER_WRITE = {...}` 常量集合（**一处定义**，符合 FC-03），并让 `verify.py` 的一条新检查 `mutable_field_drift`（**info**）只统计"有多少行的这些字段在上次落库后被改过"。同时把 `《草案》`§6.3 的纪律写成一条**装配期断言**：任何被 `MUTABLE_AFTER_WRITE` 或 `DERIVED_FIELDS` 声明的字段名，**必须在 `verify` 里有对应检查**（对应 FC-02 的"每个外键字段名都有对应的 verify 检查"）。
- **成本**：**小改**（一个常量集合 + 一条 info 级检查 + 一条装配期断言 + 测试）。
- **是否值得现在做**：**值得**，成本低。它是 `《草案》` P0-4（"统一问题对象字段名"）与 §6.3 的**同一类工程的机械版本**。建议 **P1**。
- **结论**：**部分取用**（借"显式划分可变字段 + 唯一写路径"的形式；**不要**引入内容寻址 id，见 §7-W6）。

---

### I4 `trusted` 台账状态：**"这条本身就是已验证过的 fact，如实呈现、不重验"**

- **它是什么**：论文验证台账的 `deliver_ok` 允许 `{correct, trusted, overridden}` 三种状态通过。`trusted` 的定义是："该单元**本身是一条已经通过验证的 fact**（在 `fact_submit` 时被验证服务接受——事实图是正确性权威），**被如实呈现、且未在论文中单独重新验证**"。
  `paper_math_verify.py:153-160`。
- **为什么有价值**：这是一个**诚实的第三态**——它承认"这一节没有被论文级验证器单独检查过，但它不需要：它一字不改地来自一条已验证的东西"。没有这个状态，写手只有两条烂路：要么把"直接引用"也送去重验（浪费 + 可能因上下文缺失被误拒），要么把它标成 `correct`（**声称验过了，实际没验 —— 这正是我们最怕的那类谎报**）。**它与我们的三态纪律（FC-01）同源，但用在了"论文单元"这个我们还没有的粒度上。**
- **落在我们哪里**：**前提是先有 I17（论文级再验证）**。一旦有了，`documents` 表或一个新的 `paper_units` 概念就需要这个状态。若不采纳 I17，则本条**无处可落**。
- **成本**：**小改**（但**依赖 I17**）。
- **是否值得现在做**：**只在采纳 I17 时一起做**。单独做没有意义。
- **结论**：**取用，但绑定 I17**。

---

### I5 花销 / token 台账：append-only + 容错求和 + **零值也记** + 每次返回累计值

- **它是什么**：
  ① "**钱只记在这一处**"，项目总额 = `spend/consult.jsonl` 里 `cost_usd` 的和；
  ② **容错**：求和时跳过坏行，**永不因坏行崩溃**；
  ③ **$0 也记**："保持节奏/历史的完整"（一次 `off` transport 的咨询也留一行）；
  ④ `log_spend()` 每写一行就**返回全账本的累计总额**（格式化 4 位小数）；
  ⑤ 每行记 `model/effort/attempt/status/input_tokens/output_tokens/reasoning_tokens/cost_usd/seconds`。
  `strategy/ledger.py:1-12,22-42,45-55`。
- **为什么有价值**：**FC-19（token 预算是硬约束，重试也计入）在我们这里完全未落地**（《草案》§7 判"未落地"，搜 `token_meter`/`token_budget` = 0 命中）。Danus 给了这个字段的一个**已验证可用的最小形态**：不需要复杂的计量框架，只需要一张**追加式台账**，且它的三个细节都是我们容易漏的：
  - **重试也计**：`attempt` 字段是行的一部分 ⇒ 同一次逻辑调用的多次尝试**各占一行**（直接满足 FC-19 判据②"注入 N 次失败重试后，预算消耗 ≥ N × 单次成本"）；
  - **$0 也记**：否则"咨询次数"这个分母永远是错的；
  - **每次返回累计**：让调用方**不必自己求和**（我们的 `DEFAULTS` 全是常量，没有"已花费"的运行时事实）。
- **落在我们哪里**：**新增一个模块私有的台账文件**，形态上**等于**我们已有的受控偏离 `research_request_ledger.json`（《草案》§4.1：不进 `LOCK_ORDER`、不被 `verify` 校验、不能从 `events.jsonl` 重建，但**被 `verify` 的 5 条 `ledger_*` 检查变成可观测**）。所以最干净的做法是：**照抄这个偏离模式**——`token_ledger.jsonl`（或复用同名台账加 `kind` 区分），并在 `verify.py:538-560` 那 5 条 `ledger_*` 检查的基础上**再加 2 条**：`ledger_cost_negative`（error）、`ledger_budget_exceeded`（warning）。台账的写入口唯一：D 向 A 的提交路径（`research.submit_gap`）与 E/F/G/H 的 LLM 钩子入口。
- **成本**：**中改**（新增一个私有台账 + 唯一写入口 + 2 条 verify 检查 + 把 `DEFAULTS.max_inflight_requests` 扩展为"每问题轮数 / 全局上限"两个新键——后者正是 `《草案》` **P0-1**）。
- **是否值得现在做**：**值得，且是 P0 级**——《草案》§10 已把"提问预算定值"列为 P0-1，理由是"**接上真实检索后这是唯一的刹车**"。Danus 的台账恰好给了这个刹车一个不引入新表、不破坏 `LOCK_ORDER` 的落地形态。
- **结论**：**取用**（形态照抄**我们自己的受控偏离**模式 + Danus 的三个细节）。

---

### I6 把"负结果"升为第一类通道（`dead_end` / `obstacle`）

- **它是什么**：global memory 的 11 个受控 kind 里，有 **4 个是"判断型/负结果"**：`plan`、`dead_end`（"为什么这条路失败了"）、`direction`、`obstacle`。"失败是共享的，不是锁在每个 worker 的私有记忆里、只有成功浮上来"。且 `dead_end` 在"被反例杀死时可以是 verifiable 的"。
  `core/schema.py:26-38`、`DATA_MODEL.md:87-91,129-139`。
- **为什么有价值**：我们**有**负结果，但它们散落且**不是一等公民**：C 的 `cold` 报告把 `degree==0` 单列"完全孤立"（《草案》§7 FC-25）、F 的子目标 `blocked` 带 `blocked_reason`（`schema.py:899`）、E 的 `NEGATION_KINDS`。**但没有一张表/一个通道专门回答"这个方向已经被谁、用什么理由、在哪一步试过了"。** 这正是 FC-26（"每个缺口/结论必须是可核实判据"）的**孪生问题**：我们管住了"说'值得研究'要判据"，没管住"**说'这条路死了'也要判据**"。而 `dead_end` 恰恰是最容易被 LLM 随口宣称的一类——**一个没有理由的 `dead_end` 会让整个蜂群永久绕开一条可能有用的路**，其代价是隐蔽的。
- **落在我们哪里**：**不要新增表**（12 张表已冻结，加表要动 `LOCK_ORDER` 与 `verify`）。最省的落法是：`reprocess_requests` 表已存在且语义是"C/D 要求 B 重新处理已有内容"（《草案》§2.2 明确它与 `search_requests` 语义不同）——**`dead_end` 可以走 `analysis_reports` 的一个新 `kind`**（C 的唯一产出表，只读角色提出、天然可审计）：加 `kind="dead_ends"`，其行的字段里强制 `reason ∈ DEAD_END_REASONS`（受控词表）+ `evidence` 非空（**照抄 `ReviewFinding.evidence` 必填非空的形态**，`schema.py:1130`）。再由 D 在 `research_questions` 的 `notes` 里消费"这个问题所在的路线已被登记为 dead_end"。
- **成本**：**小-中改**（`analysis_reports` 的一个新 kind + 一个受控词表 + 一条"`reason` 非空"的交叉检查 + D 的消费逻辑）。**不加表、不改 `LOCK_ORDER`。**
- **是否值得现在做**：**值得**。它是 FC-26 的对称补全，且**直接降低 F 无效攻坚的概率**（F 的 `max_persist_attempts` 现在会在同一个死方向上重复尝试到预算耗尽）。
- **结论**：**取用**（但**必须落成 `analysis_reports` 的新 kind，不要新增第 13 张表**）。

---

### I7 判决**机械派生**，而不是采信被审对象的自报（"缺 class 默认 must-fix"）

- **它是什么**：论文验证者输出 `findings`，每个带 `class: ignorable | must-fix`；**deliverability 是派生的**：`correct` 当且仅当 must-fix 为零；**`class` 缺失或未知的 finding 默认归 `must-fix`**；`ignorable` 永不阻塞，只上报。
  `server.py:1590-1607`。注意这与它自己单条-fact 验证的立场**相反**（`verify/README.md:34-36` 明说"服务不重算 verdict"）——**它在论文这一侧更严**。
- **为什么有价值**：这是我们的**核心纪律在另一个粒度上的翻版**：**"标签只靠人写、没有机器判据，就会退化成'我觉得这条挺硬的'"**（《草案》§8.8）。我们已经在 `E.Experiment` 上做了（脚本自报 `proof` 一律降级 `cross_check`，`schema.py:758`）、在 `PROVED_HERE` 上做了（论证白名单 + 机械拒绝测量词，§8.8）。**但 H 这一侧还没有**：`ReviewFinding.level` 是 H 自己写的，`documents.status` 是 G 自己置的，**没有代码重算"H 报了什么 ⇒ G 该是什么状态"**。
- **落在我们哪里**：`verify.py` 新增一条**重算检查** `status_verdict_mismatch`（**error**）：对每条 `documents` 行，重算"其关联的 `review_findings`（同 `doc_id`、最新 `round`）里是否有 `level=="error"` 且 `status` 未 `fixed`/`wontfix`+`resolution_note`"——
  - 若有，而 `documents.status == "accepted"` ⇒ **error**（"声称已接受，但台账里有未解决的 error"）；
  - 反向：若**没有任何** finding 却已 `accepted` ⇒ **warning**（"状态找不到依据"）。
  以及**默认值方向**：`ReviewFinding.level` 缺失/未知 ⇒ **按 `error` 处理**（`schema.py` 现在是受控词表校验 ⇒ 必须有一处把"未知"映射成最严，这个映射写在 `verify` 里）。
- **成本**：**小改**（一条重算检查 + 一条默认映射 + 负控测试）。
- **是否值得现在做**：**非常值得，成本极低**。这是"**让状态可被独立重算**"的最小一步，且它**不需要**任何新表、新角色、新的 LLM 调用。
- **结论**：**取用**（建议列为最优先的"小改"项之一）。

---

### I8 内容指纹带来的**天然判重**（以及为什么**不要**照搬）

- **它是什么**：`fact_id` 是内容的 SHA256 前 16 hex，`_normalize` 先折叠空白（外观编辑不扰动 id）。**同样内容 ⇒ 同样 id ⇒ 天然判重**；节点不可变（改了 statement/proof/glossary ⇒ 新 id ⇒ 新文件）。`core/schema.py:98-130`、`DATA_MODEL.md:282-286`。
- **为什么有价值（以及它的边界）**：对我们的**判重**需求（B 的 `dedup_key`、`concept_group_key`、I5 的结构重复）它是一个干净的参照——**"判重键应当是内容的纯函数，而不是发号器或人工键"**。我们已经有 `dedup_key`/`concept_group_key`（《草案》§3.2），所以这一半**已覆盖**。
- **为什么不要照搬**：① 我们没有"不改 id 就无法增量修正"的需求面——我们的行是 upsert，且 `《草案》` §8.9 已经踩过"发号器 + 幂等 upsert = **静默数据丢失**"的坑并修好了；换成内容寻址会**同时**摧毁 `ID_COUNTERS` 的 4 位空间纪律、`_id_contiguity` 检查、以及 FC-12 的 `rebuild()` 信息量守恒断言，**是一次架构级重写**。② 它自己也有代价：`external_refs` 必须**刻意**排除在 id 之外（`schema.py:115-119`），这说明**内容寻址一旦引入，就必须立刻回答"哪些字段算内容"**——这个决定很贵。③ 它的 `predecessors` 是**纯 fact_id 列表、无元数据**，而我们 `relations` 一行要装 `quote`/`page_range`/`quote_verified`/`supporting_lit_ids`——**我们的行天然比它的节点胖**。
- **落在我们哪里**：**不落**。只落**一条纪律**：把 `dedup_key` / `concept_group_key` 明确声明为 `DERIVED_FIELDS`（与 I3 的机制合并），并加装配期断言"每个派生字段必须能在缺字段时**就地推导**"（`《草案》`§6.3 的教训）。
- **成本**：**小改**（就是 I3 那一份）。
- **是否值得现在做**：**不要做内容寻址**；只做 I3 的派生字段声明。建议 **P2**。
- **结论**：**不需要改（我们的 `dedup_key`/`concept_group_key` 已覆盖判重需求；内容寻址**不适用**，理由见上）**。

---

### I9 「花钱之前的确定性闸门」+「只加严」的显式契约

- **它是什么**：`prechecks.py` 在**任何 codex 调用之前**跑：空泛性 + P1/P3/P5。文件开头两行就写明这一层的性质：**"两层，都是纯粹附加的（它们只能拒绝更多，永不接受更多），每一层可 env 开关"**（`prechecks.py:1-16`）。防御性细节：正则异常被当成"不匹配"（`:202-205`），**"一个检查绝不能变成 500"**；P1/P3/P5 **对 proof 与 statement 都跑**（`:201`，"一个坏模式可以藏在 lemma 的假设里"）。
- **为什么有价值**：① 我们**没有任何"花费之前"的门**——一旦 G/H 的 LLM 钩子真接上（FC-14 当前"未端到端跑过"），第一道门就是花钱的那一道；② "只加严"是一条**可断言的契约**，而我们虽然有 `validate()`（拒绝式），却**没有把它写成一条被测试的界面性质**（"这一层永远不会让一个原本通过的输入通过"）；③ "对 statement 也跑一遍"这个细节很便宜而且有效。
- **落在我们哪里**：在 `interactions.py`（纯函数、已过 `assert_store_free`）里加 `preflight_*` 系列：`preflight_document(doc) -> list[dict]`（在 G 交给 H 之前、在任何 LLM 之前跑）；`verify.py` 加一条**不变式测试**（不是检查，是断言）：`preflight` 单独判定为"通过"的样本，在完整 `verify` 下的通过率**不低于**它——即**只加严**。env 开关形态照抄（每个检查一个 `ABFLOW_REJECT_*`，默认全开）。
- **成本**：**小改**。
- **是否值得现在做**：**值得，但优先级中**（当前 LLM 钩子默认关闭，需求面还没到；但"只加严"这条不变式测试现在就能写，且它防的是将来）。
- **结论**：**取用**（先取"只加严"的不变式测试与 env 开关形态；`preflight_*` 等接 LLM 时再填）。

---

### I10 可执行的**硬禁令清单**（P1/P3/P5/P6 + 双段覆盖 + 同段依据判据）

- **它是什么**：三类"形状"被写成**可执行的禁令**，每类都有：正则、提示词条款、双段（proof + statement）覆盖、env 开关、以及**修复指引**（"换成具体 fact_id / 外部论文引用"）。
  - **P1** 把 `problem.md` 当数学来源（`prechecks.py:46-56`）；
  - **P3** 无条件前提 —— **"除非同一段里出现一个 16-hex fact_id"**（`:60-65,140-163`）；
  - **P5** 模糊指称（`"by some classical/well-known argument"`，`:70-74`）；
  - **P6** 自足性（"statement 以 'Under the standard … hypotheses' 开头却没列假设" ⇒ `gap`，`AGENTS.md:225-227`）；
  - 以及**边界条款**："若证明合法地引用了被匹配的短语（例如引用一个有问题短语来反驳它），用你的判断，并在 `issue` 里讲清楚。**这里的假阳性是可恢复的（worker 可以换个说法）；假阴性会让假证明通过。**"（`AGENTS.md:235-239`）
- **为什么有价值**：**我们的 `overclaim` 检查只有"把 cross_check 写成证明性措辞"这一个人工枚举的一类**（《草案》§6.2）。而 `《草案》`§6.4 给了框架级规则——"每个新增闸门都必须在 ≥20 条真实样本上量过触发率"——**Danus 的 P1/P3/P5 正是这条规则的产物：它们是从真实事故里长出来的**。特别是 **P3 的"同段必须有依据 ID"**：我们的 FC-22/FC-23 目前只要求"有 `citations`"，没要求"**在用到它的那一段**里有 `citations`"——而引用放到脚注、放到别段、或者只在文档级存在，都是**真实会发生**的规避方式。
- **落在我们哪里**：
  ① 在 `interactions.py` 加 `HARD_PROHIBITIONS`（`(name, regex, fix_hint)` 三元组的受控元组，**一处定义** ⇒ 同时被 `verify.py` 与 `tools/review_tools.scan_document` 引用，满足 FC-11"校验器与写入方共享同一配置来源"）；
  ② 首两条落地：**`ambiguous_gesture`**（"易证"/"显然"/"由经典结果"这类模糊指称且同段无 `citation` / `relation_id` ⇒ `error`）与 **`uncited_in_paragraph`**（`cross_check`/`proof` 级断言所在段落内**没有任何引用标记** ⇒ `error`）。这两条都**直接对得上 `schema.py:996` 的现约束，只是把粒度从"文档级"收紧到"段落级"**；
  ③ **必须配 ≥20 条真实样本的触发率测试**（《草案》§6.4），否则不要上线。
- **成本**：**中改**（一个受控元组 + 两条检查 + `scan_document` 接线 + 触发率测试）。**风险**：段落级判据**假阳性率会显著高于文档级**——中文里"显然"/"易证"出现的语境极杂（Danus 自己也承认它这一层是"**整个验证栈里最带项目味的部分**"，`security-and-trust.md:113-116`）。所以**必须**先量触发率。
- **是否值得现在做**：**部分**。建议**先只做"量触发率"**（写一个只读脚本在 25 条真实关系上跑一遍，记录触发率与人工抽查的假阳性率），**再决定是否上线**。若假阳性率 > 10%，**不上线**——照 `《草案》`§6.4："**假报警比不校验更糟，因为它会训练人忽略告警**"。
- **结论**：**部分取用**（先测量，后决定；形态取"受控元组一处定义 + 同段依据判据 + 假阳性可恢复的边界条款"）。

---

### I11 ⭐⭐ **依赖的缺陷继承**（chain check）：被引用者的缺陷上溯给引用者

- **它是什么**：原文（`verify/agent/AGENTS.md:229-233`）：
  > 当一个步骤引用了一个 16-hex `fact_id`，就把那条 fact 自己的 `statement` **当作被内联进来**。如果被引用 fact 的 statement 含有一个无条件前提（按上面 P3），**引用它的证明就继承这个缺陷**：记 `critical_error`，说明"被引用的 fact `<id>` 自身含有一个未证明的条件前提——该证明传递地依赖了一个未证明的假设。"

  做法上它是**语义**的（LLM 读被引用者的原文、判断是否继承缺陷），不是机械的。
- **为什么有价值**：**这是我们框架里一处真空。** 我们的 `dependencies` 表 + `dangling_dep` 能回答"**依赖指向的东西存不存在**"（FC-23 判据②），但回答不了"**依赖指向的那条东西自己是不是干净的**"。而 `《草案》`§9.1 记录的**最漂亮的一条真实实例**恰恰是这类问题的另一半：`main.pdf` 的 Theorem 1.5 依赖配套书 `[6, Thm. 6.5]`，论文自己说"引用不重证"，我们把那条登记成 `external_unavailable` —— **我们诚实地记下了"这个前提我们没独立验证"，但没有让这个缺陷沿着依赖边上溯污染依赖它的结论**。Danus 的 chain check 干的正是这件事。它与 I1（级联作废）是**同一枚硬币的两面**：I1 是"**被推翻**"的传播，I11 是"**有缺陷**"的传播。
- **落在我们哪里**：
  ① **机械的一半**（可以直接做）：`verify.py` 新增 `inherited_dependency_defect`（**error**）：对每条 `dependencies` 行，若 `status ∈ {dangling, external_unavailable}`（即"已知不闭合"）而**引用它的 `documents.claims[]` 里那条 claim 的 `level`/`evidence_kind` 被标为 `proof`** ⇒ error（"声称是证明，却传递地依赖一条未闭合的外部前提"）；若引用者的 level 是 `cross_check` ⇒ **warning**（已知边界，符合 FC-13）。
  ② **语义的一半**（需要 LLM，现在不做）：让 H 的 `scan_document` 在读到 `citations` 时，**把被引用实体的一行"前提摘要"内联进去**再判断——这需要 H 能读 `concepts`/`relations` 的一行摘要（H 是只读角色，读得到）。
- **成本**：**机械的一半 = 小改**（一条 verify 检查 + 一条 FC-13 分级规则 + 负控测试）；**语义的一半 = 大改**（要给 H 加"内联被引用者摘要"的能力与提示词）。
- **是否值得现在做**：**机械的一半非常值得，现在就能做，成本极小**。它把 `《草案》`§9.1 那条"我们没独立验证 Theorem 1.5 的前提"从一条**孤立的可查询事实**，升级成**一条会让依赖它的证明自动降级的规则**。这正是 FC-13 两句话规则的第三个应用场景。建议 **P0/P1**。
- **结论**：**取用（机械的一半）；语义的一半暂不做（记入 §10 路线图）**。

---

### I12 **冷启动验证者**：每次审校都是一个全新上下文

- **它是什么**：每个 `/verify` spawn 一个**全新的 `codex exec` 会话**（`launcher.py:1-17,201-265`）；per-run 目录 `results/<run_id>/{log.md, verification.json}`，`run_id` 是 `时间戳_语句哈希前12位` 并有**原子分配**（`mkdir(exist_ok=False)` + 数字后缀重试，`:140-154`）；验证者**什么都不持久化**（`AGENTS.md:52-60`）；提示词注入的是**只读角色的 MCP**（`role=verifier` 只暴露 `search_arxiv_theorems`，`launcher.py:116-125`），它**按文件读 fact graph**（`AGENTS.md:34-41`）。
- **为什么有价值**：**"审校者的上下文里没有它要审的对象"是我们 H 的一个结构性弱点。** H 在进程内运行、store 开着、和 G 共享同一个进程——`《草案》`§9.2 第 4 条已经承认："**只读是'工具面'约束，不是存储层 ACL**……它们的模块代码仍可直接 `store.tx(...)` 写库"。Danus 用一个**跨进程的冷启动**把"审校者的独立性"变成了**操作系统级的性质**：它不但拿不到写工具，它**拿不到任何可以写的东西**——它只有一个输出文件路径，和一个只读的文献检索工具。
- **落在我们哪里**：**不必照搬跨进程**（我们是单进程原型，`《草案》`§1.4 明确"取消语义未落地、无跨进程需求面"）。但可以取它的**三条便宜的性质**：
  ① **per-run 目录**：H 的每次审校写 `review_runs/<NNNN>-round-<k>/{输入快照.md, findings.json, log}`（`reports/` 下已有同类惯例），让"H 当时看到的到底是什么"成为**可复查的事实**——现在 H 的输入是"当时的库状态"，事后无法复原；
  ② **run_id 原子分配**：照抄 `launcher.py:140-154` 的 `mkdir(exist_ok=False)` + 后缀重试形态（我们的 `reports/NNNN-*.md` 目前靠发号器，但**并发**下不够）；
  ③ **提示词里给审校者的只有"对象 + 只读查询面"**——不把 store 句柄、不把 G 的内部状态放进去（H 的工具面已只读，但**输入契约**没有这条明文）。
- **成本**：**小-中改**（H 的输出结构 + 一条"输入快照必须落盘"的检查 + run_id 分配）。
- **是否值得现在做**：**值得**（①②③ 都很便宜，且②顺带服务 C 的报告与 E 的实验产物）。建议 **P1**。
- **结论**：**取用**（取三条便宜性质；**不引入跨进程**）。

---

### I13 **进程树的生命周期治理**（作业对象 + 树杀 + 收割）

- **它是什么**：三层防线：
  ① Windows `Job Object` 带 `KILL_ON_JOB_CLOSE`，把整条后代链装进去（node → codex.exe → MCP gateway → pwsh → worker 自己的 python）——**句柄只存在于循环进程里，所以"循环怎么死的都行（优雅退出、崩溃、taskkill、TerminateProcess），最后一个句柄一关，Windows 就替我们收掉整棵传递树"**（`loop.py:44-57`）；
  ② 每轮结束 `reap_job` 收割"codex 退出了但它的 gateway / 工具 shell / 实验 python 还活着"的残留（`loop.py:224-229`、`launcher.py:240-246`）；
  ③ SIGTERM 处理器 `kill_tree`（Windows `taskkill /T /F`、POSIX `killpg`）+ 10 秒宽限再 SIGKILL（`loop.py:148-172,212-221`）。
- **为什么有价值**：**这是 FC-20（取消语义）在"单进程原型"范围内唯一真正能落地的一层**，而且它是**纯工程、无架构风险**。《草案》§7 把 FC-20 判为"未落地"，理由是"当前是单进程、短任务原型，没有跨进程取消的需求面"——**但 FC-20 判据③"每个 start 事件有且仅有一个 end 事件（死亡或强杀时合成 `cancelled` 的 end）"是可以在单进程里做的**，而"进程不残留"更是现在就成立的正确性要求（E 在独立子进程里跑实验脚本，`《草案》`§3.5）。
- **落在我们哪里**：E 的 `run_experiment`（独立子进程 + 超时）与 F 的攻坚循环。落法：① E 的子进程杀掉时**不止杀顶层 pid**（现在是什么行为**未核实**），用一个"后代树"句柄；② F 的每轮结束**收割残留**；③ 终态事件**配对**并写进 `events.jsonl`（`start_...` / `end_...`），强杀时合成一个 `cancelled` 的 end。
- **成本**：**中改**（跨平台的树杀 + 收割 + 事件配对；Windows 作业对象在 Python 里要 `ctypes` 或 `pywin32`，Danus 的实现在 `danus/proc.py`(21107B)，**未读**）。若要**严格跨平台**则升为**大改**。
- **是否值得现在做**：**部分值得**——③（事件配对）**现在就能做且便宜**；①② 建议在 E 真正接上重计算/长任务之前做。建议 **P2**（但③提到 P1）。
- **结论**：**部分取用**（③ 现在就做；①② 等有需求面）。

---

### I14 结构化的运行期状态（原子写 + 受控状态标签 + "stuck?" 是软信号）

- **它是什么**：`.status.json` **原子写**（临时文件 + `os.replace`，`loop.py:104-119`），字段是 `{worker, pid, state, round, started_at, round_started_at, last_round_at, last_rc, last_fact_id, updated_at}`；状态是**受控标签集**（`running/idle/stopped/terminated/deadline/max_rounds/error/created`，`orchestration/cli.py:289`）；`danus status` 暴露 `stuck?` 但**明确标注它是软信号**（`cli-and-tools.md:28`）。写状态**永不抛**（`try/except OSError`，`loop.py:295-298`）。
- **为什么有价值**：我们的运行期事实几乎全在表里（`counters`、`events.jsonl`），**没有"这个循环现在处于哪个阶段"的可查询落盘事实**。《草案》§8.7 那个"`gave_up` 恒为 0"的缺陷，本质就是**"看起来在统计、实际恒为假"**——Danus 的 `state` **是受控标签**而不是自由字符串，这一点直接对得上 FC-03（跨模块字符串约定集中定义）与 FC-04（受控词表在 schema 层强制）。
- **落在我们哪里**：F 的攻坚循环 + C 的分析运行。加一个 `run_state.json`（或进 `events.jsonl` 的一个 `kind="run_state"`），字段用**受控标签集**（`RUN_STATES = ("pending","running","idle","stalled","budget_exhausted","blocked","done","error")`，**一处定义在 `schema.py`**），并在装配期断言它 ⊆ 受控词表（FC-03 的落地）。特别地：`stalled` 应与 F 的 `status="stalled" ⟹ best_partial 非空`（`schema.py:930`）**共用同一个常量来源**。
- **成本**：**小改**。
- **是否值得现在做**：**值得**（便宜，且直接补 FC-03/FC-04 的一个空白面）。建议 **P1**。
- **结论**：**取用**。

---

### I15 **不被门禁的进度报告**（任何时刻都能产出、验证不是它的前提）

- **它是什么**：`human-summary` 把事实图渲染成一份**无 id 的人类进度报告 PDF**，可以在**运行中的任何时刻**跑，**不被 `finalize` 门禁**（`docs/concepts.md:125-126`）；它的输入被**结构性净化**——fact 包里**只留 body 三节**，整个 frontmatter 被剥掉，不出现任何 id 或 slug，"写手只从数学工作"（`human_summary/assemble.py:8-21`）；拓扑序排列、**一条不落**，深度与入度只在同层内破平（`:17-21`）。
- **为什么有价值**：我们的产物是**终局式**的（`research-report.md`、稿件），而"给人看的中间进度"是**另一个制品**，它的价值恰恰在于**在验证还没完成时就能输出**。Danus 明确把"**宣布这是答案**"（`finalize`，需要人确认）与"**报告现在到哪了**"（`human-summary`，随时可跑）分成两件事——`docs/concepts.md:127-131` 的立场是"**Danus 不自己决定'完成'**"。这为我们 F 的 `best_partial` 提供了一个**比"卡住时交一份部分结果"更好的用法**：不是只在 stall 时用，而是**定期产出**。
- **落在我们哪里**：D 的 `research-report.md` 侧加一个"**任意时刻可跑的进度视图**"（新的 `kind` 或一个新的只读渲染函数，**无 LLM 也能跑**——纯确定性从表里渲染）；并且**剥离内部 ID**（照抄 `human_summary/assemble.py` 的裁剪原则：给人看的版本里不出现 `concept_id`/`relation_id`）。
- **成本**：**小改**（一个只读的确定性渲染函数 + 一份模板）。
- **是否值得现在做**：**值得**（便宜；且它把"`best_partial` 只在 stall 时交"这条我们已有的纪律，扩展成"**进展随时可见**"）。建议 **P2**。
- **结论**：**取用**。

---

### I16 **超预算的诚实阻塞**（`too_large`）+ **确定性分块**（PLAN/FILL/STITCH + 覆盖检查）

- **它是什么**：
  ① 正文超过整篇预算 ⇒ 记账 `too_large`，**一个明确的 blocker**；**"按结果分解成自足的部分"是主控的活，工具永不自己切**（`paper_math_verify.py:16-20,194-206`）；
  ② 单遍写作的提示词超预算时启用分块：**PLAN**（闭包**只给陈述** → 固定 preamble + front matter + 分节计划 + 书目；分节计划有**确定性覆盖检查**：每条闭包 fact 必须恰好被分到一节）→ **FILL**（本节 fact 全文 + **其它每条闭包 fact 的陈述**作 `\ref` 上下文）→ **STITCH**（纯 Python，无 codex）；**任何一段不 ok 或覆盖失败 ⇒ 诚实失败，绝不吐半成品**（`paper_chunked.py:1-38`）；
  ③ 分块版**不是 agentic 检索写手**："planner 与每个分节写手都是**非 agentic 的隔离 codex**（空 cwd、全部内嵌、输出即文本、无工具调用）。我们保留'每次调用只要需要的 fact'，但**由 Python 决定**、按节切片"（`paper_chunked.py:8-13`）。
- **为什么有价值**：**FC-17（上下文预算：压缩/剪枝/spill）在我们这里完全未落地**（`《草案》`§7：搜 `compaction`/`maxInlineBytes`/`thresholdChars` = 0 命中）。Danus 给了一个**不引入新架构**的形态：**超预算 = 一个显式的状态，而不是静默截断**；**分解权归编排方，不归工具**；**分块用确定性切片 + 覆盖检查，不用 agentic 检索**（后者会引入不确定性、不可复现）。这三条与我们的"确定性优先"（FC-16）完全同向。
- **落在我们哪里**：G 的组稿路径。具体：`documents` 表加一个派生状态字段（或复用 `status` 的一个新取值 `too_large`）+ 一个 `paper_section` 级的概念（**不必新表**：可以落在 `analysis_reports` 的 `kind="section_plan"` 或一个模块私有文件，形态同 `research_request_ledger.json` 的受控偏离）；覆盖检查照抄"**每条闭包条目恰好被分到一节**"。
- **成本**：**大改**（真的做分块 = 大工程）。**但"超预算的诚实阻塞"这一半 = 小改**。
- **是否值得现在做**：**只做"诚实阻塞"这一半（小改），分块版记入路线图**。现在我们没有长上下文需求面（LLM 钩子默认关闭），做完整分块会是"没人用的配置"（《草案》P2-2 已这样判断）。
- **结论**：**部分取用**（`too_large` 状态 + "分解权归编排方"的立场 = 现在就取；PLAN/FILL/STITCH = 记入 P2）。

---

### I17 ⭐⭐ **论文级再验证**：把"缝合"当作一个独立的失效面

- **它是什么**：整篇论文正文**作为一次输入**送给一个**专用的论文数学验证者**（一次性全新 codex，**无 fact graph、无切片**），判断**自足性 + 正确性**。理由原文：单条 fact 都过了验证，但**论文是另一个制品**——写手重新渲染、合并、省略"显然"步骤、加 `it suffices…`/`WLOG…` 粘接、内联从未成为 fact 的化简；**这些缝正是"一组正确的事实能变成一篇错误的论文"的地方**。所以**论文必须按写成后的样子被重新验证，而不能因为它的事实被验证过就被信任**。
  `paper_math_verify.py:1-26`；gate 的落点 `server.py:1647-1806`；`deliver_ok` 门 `paper_math_verify.py:150-168`。
  并且它**刻意拒绝切片**："我们不把论文切成孤立的逐定理单元、再重建一个有损的 fact-graph 'grounding'（那**既误拒 delta 证明，又掩盖不完备**）。一个提示词，整篇正文。"
- **为什么有价值**：**这是我们框架里最大的一处真空，而且它的存在性论证与我们自己的教训完全一致。** 我们的四道门是：`schema.validate()`（形状）、`verify.py`（库内一致性）、E 的 `evidence_kind`（证据等级）、H 的 `scan_document`（引用/等级/依赖闭合）。**四道全部作用在"结构"，没有一道作用在"成稿后的连续文本"上。** 而 `《草案》`§8.8 与 §8.12 已经用自身经验证明了这个失效面是真实的：**"结构自洽 ≠ 内容正确"、"三个绿灯叠加仍不能证明系统有用"**（`LESSONS.md` FC-22 的论证）。G 的组稿恰恰要做"把 `claims[]` 渲染成连贯文章"这件事——**这正是产生缝合的一步，而我们对这一步之后没有任何检查**。
- **落在我们哪里**：**新增一个 I13 交互（G → 独立复核）或扩展 I8**。最小形态：
  - 一个**独立的一次性验证步骤**（可以是新的角色，也可以只是 H 的一个新模式 `review.full_document(render)`——**建议前者更贴 Danus，但不强求**），输入是**渲染后的完整稿件文本**，输出是**带 `class ∈ {must-fix, ignorable}` 的 findings**；
  - **判决机械派生**（照抄 `server.py:1590-1644`：must-fix 为零才 correct；**缺 class 默认 must-fix**）；
  - **落地成一张台账**（形态取 `VERIFY_LEDGER.md`：unit / source / status / last_verdict / repair_hints / attempts，`paper_math_verify.py:68-140`），并由 `verify.py` 加一条 `document_unverified`（**error**：`documents.status == "accepted"` 但台账不存在或无 `correct` 行）——**"你不能交付一篇数学从未被检查过的论文"**（`paper_math_verify.py:160-163` 的原话精神）；
  - **超预算 ⇒ 诚实阻塞**（I16 的那一半）。
- **成本**：**中-大改**（新增一个验证模式/角色 + 一张台账 + 一条 verify 检查 + 提示词）。**但可以分两步**：第一步只做"**台账 + `document_unverified` 检查 + `too_large` 阻塞**"（**小-中改**，不接 LLM 也能跑：台账可以是"人/脚本填的"），第二步再接 LLM。
- **是否值得现在做**：**第一步非常值得，现在就能做，且不依赖任何 LLM**。它把"**稿件交付**"这个动作从"G 说 accepted 就 accepted"变成"**有一张台账，且 `verify` 会检查台账存在**"。这与 I7（判决机械派生）是同一系列，建议**一起做**。**优先级 P0/P1**。
- **结论**：**取用**（先做"台账 + verify 检查 + 诚实阻塞"的第一步；LLM 验证者第二步）。

---

### I18 **如实阻塞的通道**（`\note{[*/blocker]}`）+ **保留式编辑纪律**

- **它是什么**：写论文的每个角色都受一条 PRIME DIRECTIVE 约束，**6 条一一点名**（每条数学断言必须保留、每条引用必须保留且有 key、禁编造书目、preamble 必须保留、编辑宏中性且锁定、不泄漏流水线内部）；并且给了一个**统一的如实阻塞通道**：
  > "**如果你无法满足 1–6 中的任何一条，在输出里发出一个 `\note{[prime/blocker] <reason>}` 旗标 —— 绝不静默违反。**"
  > 完成后："**回头再读一遍 1–6，逐条扫一遍输出，要么确认合规，要么插入旗标。**"
  `agents/skills/write-paper/roles/AGENTS.md:9-11,52-54`；"没有作者就发 `\note{[author/blocker] no author supplied}` 让操作员填，**绝不编造人名/单位/邮箱**"（`:62`）。
- **为什么有价值**：我们的纪律是**"产出物必须有依据"**（引用非空、evidence 非空、三态），但**当 LLM 无法满足时，它该做什么？** 我们的答案是"schema 拒绝落库"——**这挡得住，但代价是丢失了一条信息**：**它原本想说什么、卡在哪一条上**。Danus 的做法是让模型**产出一个结构化的、可被机械检出的阻塞旗标**（`\note{[<scope>/blocker] <reason>}`），于是：① 违规**不会静默发生**；② 卡点变成了**给操作员的、可检索的**事实（`[author/blocker]` / `[cite/blocker]` / `[prime/blocker]`）；③ 旗标本身可以在 `verify.py` 里被机械扫出来（**warning**），形成"**说做不到就必须说出来**"的闭环。
- **落在我们哪里**：G 的 `compose_claim` / `build_document` 与 H 的 `scan_document`。加一个**受控的阻塞旗标语法**（例如 claim 的 `notes` 里必须出现 `[ABFLOW-BLOCKER:<scope>] <reason>`，`scope ∈ BLOCKER_SCOPES`，**一处定义**）；`verify.py` 加 `unflagged_blocker`（**warning**：断言带 `disclaimer` 却缺 `citations` 时**必须**有旗标——**把"我不确定"变成必须交出的东西**）；`schema.py` 的 `claims[].citations` 非空约束**不变**（旗标不能替代引用，只能**伴随**引用缺失）。
- **成本**：**小改**（一个受控语法 + `BLOCKER_SCOPES` + 一条 warning 检查 + 提示词/文档一行）。
- **是否值得现在做**：**值得**（便宜；且它给"拒绝落库"这条硬约束加了一条**信息不丢失**的旁路）。建议 **P1**。
- **结论**：**取用**。

---

### I19 干净写手上下文：**输出前剥离一切内部标识**（并**按制品定制**泄漏集）

- **它是什么**：
  ① 写手/报告写手是**隔离的一次性 codex**，"喂给它一个**范围受限、无机器语言**的提示词，**绝不是编排者自己被污染过的窗口**；它无法泄漏它从没收到过的 `fact_id` 或蜂群词汇"（`ARCHITECTURE.md:98-101`）；
  ② **剥离是结构性的**：`human_summary` 的 fact 包**只留 body 三节**，frontmatter 全剥，"不出现任何 id 或 slug"（`human_summary/assemble.py:8-21`）；
  ③ **输出侧还有一道正则泄漏门**，**而且两个制品的泄漏集不同**：论文侧禁 16-hex id / `author:` 前置行 / `fact_*` slug / `master_guidance` / `fact_submit`，但**刻意不禁** `worker`/`verifier`/`predecessors`——"那些在真实的数学/CS 论文里合法出现"（`server.py:53-63`）。
- **为什么有价值**：我们 G 是在同一个进程、同一个 store 上下文里工作的。**"写手看到了它不该看到的东西"这件事，我们目前既没有输入侧的净化，也没有输出侧的检查。** 而这一条的价值不只是"防止泄漏内部 ID"——**它是防止 LLM 把内部词汇当数学词汇用**（"这个 claim 的 evidence_kind 是 cross_check" 出现在论文正文里）。第 ③ 条尤其值得学：**"泄漏集必须按制品定制"**，因为一个过宽的禁令会误伤合法内容（Danus 明确区分了论文与人类报告的集合，并在代码里写了一行注释说明为什么论文侧不禁 `worker`）。
- **落在我们哪里**：
  - **输入侧**：G 的 `build_document` 把 facts 渲染成稿件时，先经过一个**剥离函数**（只留断言正文与必要的引用标记，剥掉所有 `*_id` / `origin` / `level` / `status`）；放 `interactions.py`（纯函数）。
  - **输出侧**：`verify.py` 加 `internal_id_leak`（**error**：渲染后的稿件正文里出现 `^\d{4}$` 形态的实体 ID 或 `origin` 字符串，如 `C:paths:0000:...`）——这正是 `《草案》`§3.4 里 `origin` 形如 `C:paths:0000:0009->0010->0005`，**它是一个内部代号链，绝不该出现在给人看的稿件里**。
  - **泄漏集一处定义**：`LEAK_PATTERNS_PAPER` / `LEAK_PATTERNS_SUMMARY` 两个受控元组（FC-03）。
- **成本**：**小-中改**（一个剥离纯函数 + 一条 error 级检查 + 两个泄漏集常量 + 负控）。
- **是否值得现在做**：**值得**。这是我们 `origin` 字段（FC-02）的一个**直接副作用风险**，现在就该挡。建议 **P1**。
- **结论**：**取用**。

---

### I20 **环境读在调用时，不读在导入时**（可测性契约）

- **它是什么**：Danus 把这个模式在**四个模块**里一致地执行并**明文写出理由**："配置从环境在**调用时**读（不在导入时），所以服务是可测、可重配的"——`core`/`gateway`/`verify`/`execution`/`strategy`/`write_paper` 全部如此（`gateway/server.py:17-20`、`layout.py:31`、`strategy/config.py:1-7`、`execution/loop.py:14-16`、`paper_chunked.py:63-66`）。反例它也留了：`prechecks.py:27-29` 的**阈值**读在导入时（因为它们是模块级常量，且测试可以 monkeypatch 模块属性）。
- **为什么有价值**：我们的 `DEFAULTS`（`interactions.py`）与各模块常量是**导入时**常量。这意味着**任何"改配置 + 写边缘样本 + 断言复核不报错"的测试（FC-11 判据③）都必须 monkeypatch 模块属性**，而不是设一个环境变量。这是一个**可测性**问题，不是正确性问题——但它直接影响 FC-11（"校验器与写入方共享同一配置来源"）能否被**便宜地**验证。
- **落在我们哪里**：`interactions.DEFAULTS` 与 `verify.py` 的阈值。落法：保留 `DEFAULTS` 作为**默认值快照**（FC-11 已主张引入 `QuotePolicy` 配置对象），但把所有**运行时**读取改成一个 `load_policy()` 调用（调用时读 env，缺省回落到 `DEFAULTS`）；`verify_all(policy=...)` **强制传参**（这正是《草案》P1-2 的 `QuotePolicy`）。
- **成本**：**中改**（就是《草案》P1-2 的工作量；I20 只是给它补一条"为什么值得做"的理由）。
- **是否值得现在做**：**与 P1-2 合并做**，不单独做。
- **结论**：**部分取用**（并入 P1-2 的 `QuotePolicy`，并把"调用时读 env"写成该对象的接口契约）。

---

### I21 「目标未设定」是一个**显式状态**，而且**绝不静默兜底**

- **它是什么**：`resolve_headline()` 解析论文的目标定理 id，返回 `(ids, source)`，`source ∈ HEADLINE_SOURCES = ("arg", "brief", "target", "unset")`。四条优先级（显式参数 → brief 字段 → `TARGET.md`（`danus finalize` 写的）→ **UNSET**），且 docstring 里写死：
  > "**目标必须是被记录下来的；没有任何静默猜测**（there is NO silent guess）。"
  > "在 `"unset"` 时调用方**不得**回退到"所有 fact"——`fact_graph_content` 会抛 `TargetUnsetError`，`server.paper_write` 返回一个 `needs_target` 结果。**最深层的终端 fact 不是这里的回退**；它们只是 `danus finalize` 的**建议**。"

  `write_paper/assemble.py:280-310`（docstring `:284-301` 逐字给出四条与禁令）、`HEADLINE_SOURCES` 常量在 `:60`、`TargetUnsetError` 在 `:120`。
- **为什么有价值**：**这是 FC-08（"无工具 / 未接线必须显式失败，不得静默降级为空"）在"缺失的输入"上的同构形态**，而且它比 FC-08 多走了一步：它不仅"不返回空"，还**把"未设定"本身做成了一个受控枚举值**（`"unset"`）与一个**具名异常**（`TargetUnsetError`），并且**明确禁止了一个看似合理的兜底**（"那就拿所有 fact 吧"/"那就拿最深的那几条吧"）——因为那个兜底会**静默地把论文的目标换成另一个定理**，而结果看起来完全正常。`《草案》`§8.7（`gave_up` 恒为 0）与 §6.3（`concept_pair_key` 派生态当输入）是同一族缺陷：**一个"看起来合理的兜底"会让缺失变成静默的错误答案。**
- **落在我们哪里**：**`resolve_headline` 这一族问题的对应物在我们这里是"锚点/种子从哪来"**：D 的 `paper_seed`（人提供抽取选择，`《草案》`§9.2 第 5 条）、G 的 `build_document` 从 `research_questions`/`relations` 里选断言、F 从 `attack_plans` 里选下一个子目标。落法（三件，都很小）：
  ① 凡"选一组实体作为工作目标"的函数，**返回 `(ids, source)` 而不是裸 `ids`**，`source` 取自一个受控元组（**一处定义在 `schema.py`**，满足 FC-03）；
  ② `source == "unset"` 时**抛具名异常**（不是返回空、不是回退到"全部"或"最热的几条"）；
  ③ 在 `verify.py` 加一条 `implicit_target`（**warning**）：某个 `documents` 行/`attack_plans` 行的目标集合**恰好等于全库**或**恰好等于某个"默认选取规则"的输出** ⇒ 记录一条"这可能是一次静默兜底"的线索。
- **成本**：**小改**（改 2-3 个函数的返回形状 + 一个受控元组 + 一条 warning 检查）。
- **是否值得现在做**：**值得，且成本极低**。它是 FC-08 的**输入侧**补全——FC-08 管住了"工具没接线"，但没管住"**输入没给定**"。建议 **P1**。
- **结论**：**取用**。

---

### 点子清单（一句话 + 成本）

| # | 一句话 | 成本 | 建议 |
|---|---|---|---|
| **I1** | 把"被推翻"沿 `dependencies` 边**级联传播**（`invalidated_by` 字段 + 2 条 verify 检查） | 中改 | **P1 取用** |
| **I2** | 符号定义覆盖率检查（`symbols_undefined` 纯函数 + warning 级 verify 检查），正则须重定 | 小-中改 | P1 取用 |
| **I3** | 在 `schema.py` 显式声明**可变字段/派生字段**集合 + 装配期断言"每个都有 verify 检查" | 小改 | P1 取用 |
| **I4** | `trusted` 台账状态（"本身已是已验证事实，如实呈现不重验"） | 小改（依赖 I17） | 与 I17 同批 |
| **I5** | 花销/token 台账：append-only + 容错求和 + **零值也记** + 每次返回累计（落成我们自己的受控偏离台账） | 中改 | **P0 取用**（= 路线图 P0-1） |
| **I6** | 把"负结果"升为一等公民：`analysis_reports` 加 `kind="dead_ends"` + `reason` 受控 + evidence 非空 | 小-中改 | P1 取用 |
| **I7** | 判决**机械派生**：`status_verdict_mismatch`（error）+ 未知 level 默认按 error | 小改 | **P0 取用** |
| **I8** | 内容寻址 id / 天然判重 | — | **不需要改**（我们的 `dedup_key`/`concept_group_key` 已覆盖；换 id 方案是架构级重写，见 §7-W6） |
| **I9** | 「花钱前的确定性闸门」+「**只加严**」可断言契约 + env 开关 | 小改 | 先取"只加严"不变式测试 |
| **I10** | 可执行硬禁令清单 + **同段必须有依据**（P3 形态）+ 假阳性可恢复的边界条款 | 中改 | **先量触发率再上线**（<10% 才上） |
| **I11** | **依赖的缺陷继承**（`inherited_dependency_defect`：声称 proof 却传递依赖未闭合前提 ⇒ error；cross_check ⇒ warning） | 小改（机械半） | **P0/P1 取用**（语义半记路线图） |
| **I12** | 冷启动审校的**三条便宜性质**：per-run 输入快照 + run_id 原子分配 + 输入契约只给"对象+只读面" | 小-中改 | P1 取用（**不引入跨进程**） |
| **I13** | 进程树生命周期：事件配对（便宜）+ 作业对象/树杀/收割（贵） | 中-大改 | 只做事件配对（P1），其余 P2 |
| **I14** | 结构化运行期状态：原子写 + **受控状态标签** + `stalled` 与 F 共用常量来源 | 小改 | P1 取用 |
| **I15** | **不被门禁的进度报告**（任何时刻确定性渲染、剥离内部 ID） | 小改 | P2 取用 |
| **I16** | 超预算的**诚实阻塞** `too_large` + "分解权归编排方"（分块 PLAN/FILL/STITCH 记路线图） | 小改 / 大改 | 只取前半 |
| **I17** | **论文级再验证**：独立验证者读**整篇成稿** + 台账 + `document_unverified`（error） | 中-大改 | **P0/P1 取用**（第一步不依赖 LLM） |
| **I18** | 如实阻塞通道 `[ABFLOW-BLOCKER:<scope>] <reason>`（+ `unflagged_blocker` warning） | 小改 | P1 取用 |
| **I19** | 干净写手上下文：输入侧剥离 + 输出侧 `internal_id_leak`（error）+ **泄漏集按制品定制** | 小-中改 | P1 取用 |
| **I20** | 环境读在**调用时**、不读在导入时（并入 `QuotePolicy`） | 中改 | 并入路线图 P1-2 |
| **I21** | 「目标未设定」是**受控状态 + 具名异常**，且**禁止静默兜底**（`resolve_headline` 形态） | 小改 | P1 取用 |

### FC 对照速查（Danus 有没有做到）

| FC | Danus 的对应物 | 结论 |
|---|---|---|
| FC-01 三态 | 部分（`fact_id=None`/`write_error`/`verdict="error"` 三处；无 `bool\|None` 判定字段、无受控 reason） | **我们强** |
| FC-02 双向代号链 | ❌ 无反向链检查（`predecessors` 单向、无"我被谁引用"的校验） | **我们强** |
| FC-03 约定集中定义 | ✅ `roles.py` 一处定义 + `ALL_TOOLS`（"kept here so the role table and the implementation can't drift"，`roles.py:21-22`）；❌ 但 `observability/app.py:43-54` 的 `CHANNELS` **是手抄副本、要手工同步** | **打平，且它有一处已知漂移** |
| FC-04 受控词表在 schema 强制 | 部分：kind/status/paper_id 受控；无行级 schema、无交叉检查、无 `schema_version` | **我们强** |
| FC-05 顺序与集合分离 | ❌ 无此概念 | **我们强** |
| FC-06 角色即权限面 + 预期清单 | ✅ **比我们更硬**：`build_app(role)` 只注册该角色的工具（物理不存在），未知角色 fail-closed 到 verifier；❌ 无"预期工具名清单" | **它的隔离更硬**，见 §8 |
| FC-07 `side_effect` 一等公民 | ❌ 无 `side_effect` 概念（只有"这个角色能不能看见这个工具"） | **我们强**（`side_effect` 是审批判据） |
| FC-08 未接线必须显式失败 | ✅ `verdict="error"` 区分"服务不可用"（`server.py:194`）、`DANUS_VERIFY_URL` 未设时报清晰错、非 dict body 也当 error（`:199-202`）；`bin/codex` 缺失时 loop 返回 127 且不空转（`loop.py:324-326`） | **等价，双方都做了** |
| FC-09 每门配负控 | ✅ 有测试目录，且**离线可测**是明确设计目标（`execution/README.md:47`、`gateway/README.md:47`、`strategy/README.md:70` 都写"offline；用 fake codex stub"）；`verify/tests/` 与 `authoring/tests/` 下各有一个 `fake_codex.py`（据 `Get-ChildItem` 的**文件名**）；❌ 无独立负控套件目录、**是否有 CI 未核实**（根目录存在 `.github/` 目录，**未进入查看**） | 打平 |
| FC-10 三分档计数 | ❌ 二元 `correct/wrong` | **我们强** |
| FC-11 校验器与写入方同源配置 | ✅ 形态上：`prechecks.py` 的正则与 `AGENTS.md` 的禁令**成对出现**；但**是两份文本**（代码一份、提示词一份） | 打平：**我们提出 `QuotePolicy` 是对的** |
| FC-12 可重建存储信息量守恒 | ❌ 无重建概念；`_status.jsonl` 折叠无守恒断言 | **我们强** |
| FC-13 告警分级 | 部分：`critical_errors` vs `gaps` 是**两类问题**（不是两级严重性）；`ignorable` vs `must-fix` 是**两级**（`server.py:1590-1607`） | **我们强**（我们的两句话规则更可判定） |
| FC-14 LLM 产出回验 | ✅ **它的核心机制**（每条 fact 都要过验证者），且**存回原文**（fact 文件就是原文） | 打平；但它的回验是 **LLM 判 LLM**，我们是**逐字回验**（`quoteverify.py`）⇒ **我们的 B 更强**，它**没有**引文逐字回验 |
| FC-15 归因分离 | ✅ `repair_hints` / `undefined_symbols` / `verdict="error"` 三路分开 | 打平 |
| FC-16 确定性不交给 LLM | ✅ 部分：分块路径"由 Python 决定、按节切片"、`should_chunk` 确定性、覆盖检查确定性；❌ 验证与写作都是 LLM | **我们强**（我们的 C 完全不用 LLM） |
| FC-17 上下文预算 | ✅ **有真机制**（分块 + 阈值 + 覆盖检查 + 诚实失败）；❌ 无 compaction/剪枝/spill 三件套 | **它比我们强**，见 I16 |
| FC-18 三维预算 + 深度 | ❌ 只有轮次/超时/连续失败（无并发上限、无深度上限）；fact 图深度是**可计算的观测**不是预算 | **我们强** |
| FC-19 token 预算 | ✅ **有花销台账**（含 `attempt` ⇒ 重试计入）；❌ 无 token 上限的**硬约束**、无预算守卫 | **它比我们强**，见 I5 |
| FC-20 取消语义 | ✅ **很硬**（作业对象 + 树杀 + 收割 + 轮边界停止）；❌ 无"start/end 事件配对"、无 first-wins 的显式语义 | **它比我们强**，见 I13 |
| FC-21 部分失败语义 | ⚠️ 只有 `consec_fail` 累加；**没有"这一轮产出了什么"的如实记录** | **我们强** |
| FC-22 数值≠证明 | ❌ **完全没有**（无 `evidence_kind`）；但它用**另一条路**达到类似效果："禁止重计算"铁律（`worker.md:245-257`，理由是"**验证者无法复算你跑的计算**"）+ "数值检查是辅助、永远不是证明"（`standing-norms.md:19`） | **我们强**（类型级机械约束 > 提示词约束）；**但它那条"禁止重计算"的理由值得我们引用**，见 §7-W1 |
| FC-23 依赖显式 + 闭合检查 | 部分：`predecessors` 是内部 DAG（强）；`external_refs` 是外部书目（无闭合检查，靠提示词）；**且有 chain check**（缺陷继承，我们完全没有） | **打平**：闭合检查我们强，**缺陷继承它强**（见 I11） |
| FC-24 基准口径 | ❌ 无 | **我们强**（都未落地） |
| FC-25 三种否定分开 | 部分：`status` 有 `refuted`、`dead_end`/`obstacle` 是 kind；❌ 无 `negation_kind` 四值 | **我们强** |
| FC-26 可核实判据 + 否决 | 部分：提示词要求"报告阻碍时精确到'缺哪一步/缺哪条引理'"（`worker.md`/`standing-norms.md:39`）；❌ 无 `criteria`/`veto` 结构 | **我们强** |
| FC-27 禁 AI 区 | ❌ 无（**未核实**是否有 CI） | 打平（都未落地） |

---

## 7. 它的弱点 / 我们不该学的地方

全部具体、带出处。

### W1 没有**证据等级**，而它用提示词代替结构（**这是最不该学的一条**）

`grep` 全 `danus/**/*.py` 搜 `evidence_kind` / `cross_check` / `negation_kind`：**零命中**（唯一的 `budget`/`install` 命中是无关词）。Danus 的判据是**二元的**：`correct` 或 `wrong`。它对"数值 ≠ 证明"的处理是**提示词级的**：
- `agents/contracts/worker.md:245-257`（禁止重计算的铁律，理由写得好："**正确性来自验证者检查过的证明，永不来自机器产出的数字——验证者无法复算你跑的计算**"）；
- `docs/templates/standing-norms.md:19,28`（"数值检查是辅助，永远不是证明…最终证明不得依赖机器输出"）。

**为什么不该学**：提示词是**降低概率**，schema 是**消除后果**（这正是 `LESSONS.md` FC-14 的原话）。我们的 `schema.py:758`（`method != "formal"` ⇒ 不得为 `proof`）是**机械不可能**，而 Danus 的对应约束是**可以违反的**：一个 worker 完全可以在证明里塞一段数值论证，只要验证者没抓到，它就成为一条 fact。**我们这条最强的地方，在 Danus 那里是空的——这恰恰说明我们的设计选对了方向。**

**但有一条值得引用**：它禁止重计算的理由是"**验证者无法复算你跑的计算**"——这是一个**比"数值不构成证明"更根本的论证**：不是"数值不够强"，而是"**这条链上没有任何人能复核它**"。这可以直接补进我们 E 的 docstring 与 `《草案》`§1.2 的"E 最容易犯的错"。

### W2 单条 fact 的判决**由被验证者自己写**，服务不重算，且这是被文档承认的信任假设

`verify/README.md:34-36`："**不变式（由验证者的*提示词*强制，不是这段代码）：`verdict == "correct"` ⟺ `critical_errors == []` 且 `gaps == []`。这个服务原样返回 agent 写的东西；它不重算判决。**"
`docs/security-and-trust.md:18-20` 进一步承认："判决规则由验证 agent 产出并被**原样返回**；服务**不重新推导它**。信任来自验证者的提示词 + 技能是正确的。"

**为什么不该学**：一个模型返回 `{"verdict": "correct", "critical_errors": [{"..."}], "gaps": []}` 会被**直接接受并永久写入 fact graph**——`launcher.py:257-265` 只校验"是合法 JSON 对象"，**不校验不变式**。这不是一个理论风险，而是**一行代码就能关掉的门**。我们对 H 的 `ReviewFinding` 没有这个问题（`evidence` 非空是 schema 强制），但 **I7 指出的那个空位是同一类**：`documents.status` 与 findings 之间没有重算。**Danus 在论文那一侧意识到了这点并修了（`server.py:1590-1644`），在单条 fact 那一侧没有修——我们要两处都修。**

### W3 `CHANNELS` 是**手抄副本**，而且作者自己把它记成了 gotcha

`observability/app.py:43-54`：`CHANNELS` 列了 11 个 kind，注释写"镜像 `danus.core` 的 `GLOBAL_KINDS`（**刻意作为数据保留——仪表盘不 import core 运行时模块**）"；`observability/README.md:31-35` 把它单列为 "**Gotcha**"："`CHANNELS`（11 个 kind）是一份**手工维护的数据副本**……**如果 `GLOBAL_KINDS` 变了，手工重新同步 `CHANNELS`。**"

**为什么不该学**：这是 **FC-03 的正中靶心**，而且它是**故意的**（为了解耦）。`《草案》`§8.3 记录了我们在**测试代码里**写死第二份名单的同一类缺陷，教训是"**跨模块约定必须只有一处定义——测试代码也是代码，写死第二份名单同样会漂移**"。Danus 在**生产代码**里主动做了这件事，还把它文档化成"记得手工同步"。**如果我们做观测层，必须 import 单一来源，而不是抄一份。**（对照：Danus 自己在 `roles.py:21-22` 就写对了——"kept here so the role table and the implementation can't drift"——**它在同一个仓库里两种做法并用**，这更说明"一处定义"是需要纪律维持的，不是自然发生的。）

### W4 三层记忆里**没有 schema 校验、没有事务、没有锁**；`gm` 的 id 构造在理论上会撞

- **无事务/无锁**：`core/_util.append_jsonl` 是裸追加（`global_memory.py:66-82`、`local_memory.py:38-44`）。没有多文件事务，没有锁序，没有"先校验后落盘"。`gm.set_status` 与 `gm.append` 是两个文件，靠**读时折叠**统一（`global_memory.py:95-111`）。
- **id 构造的风险**：`global_memory.py:63-65`
  ```python
  entry_id = hashlib.sha256(json.dumps([kind, claim, author, ts], ...).encode()).hexdigest()[:16]
  ```
  其中 `ts = utc_now()`。**同一个 author、同一个 kind、同一条 claim、同一秒内发两次 ⇒ 同一个 id。** 而 `_latest_status()` 是**按 `id` 折叠**的（`:95-100`），`read()` 也是按 `id` 找最新状态（`:102-111`）——所以两条不同的 finding 会被折叠成同一条的状态。Danus 在 fact 侧用内容寻址解决了判重（`schema.py:104-130`），在 global memory 侧**忘了**。
  **诚实的边界**：我**没有运行**它，所以这是**从代码推出的可能性**，不是实测缺陷；且 `ts` 含微秒以外的精度**未核实**（`utc_now` 的实现未读）。但 `claim` 与 `author` 相同 + 同一时间粒度是**完全可能**的（一个 worker 连续发布两条同名 `dead_end` 只是换了 evidence，而 **`evidence` 不在 id 里**）。

**为什么不该学**：我们的 `store.py` 有锁、有 `LOCK_ORDER`、有"先校验后落盘"、有 `alloc_id_skipped_occupied` 留痕（`《草案》`§8.9）——**这些不是过度设计，Danus 这一处正好演示了省掉它们的代价**。

### W5 没有任何**运行期总账**：状态是单 worker 的，没有跨项目/跨阶段的可查询事实

`write_status` 只写单个 worker 的 `.status.json`（`loop.py:104-119`）；`last_fact_id` 是**从轮次日志里正则刮出来的**（`_parse_last_fact_id`，`loop.py:132-138`，正则 `_FACT_ID_RE` 只认 `fact_id` 字样后跟 16 hex）。没有项目级进度台账、没有"这一轮产出了什么"的结构化记录、没有 token/轮次的累计事实（除了 `spend/consult.jsonl`）。

**为什么不该学**：`《草案》`§8.7 的教训是"**字段存在、名字合理、永远是 0**"是最典型的一类假信号。Danus 走的是**另一个极端**：连字段都没有，只有"从日志里刮一个 id"。我们的 `events.jsonl` + `counters` 是更好的形态。

### W6 内容寻址 id 虽好，但**换到我们身上是架构级重写**（明确说明为什么不推荐）

Danus 的 `fact_id` 是它整个设计的支点：天然判重（`:104-130`）、节点不可变、级联撤销可算（`:254-268`）、提示词里可以用"16-hex `fact_id`"当**机械可检的依据标记**（`prechecks.py:67` 的 `_FACT_ID_PATTERN`）。

**但我们不该换**，理由有三条，都是具体的：
1. **它会摧毁我们的 4 位空间纪律**：`MAX_ID = 9999`（`store.py:50`）、`_id_contiguity` 检查、`ID_COUNTERS` 的 10 个 kind、以及"发号与建行必须同锁"（`《草案》`§4.3）。换成 16 hex 内容哈希，这一整套（以及它防的一类缺陷）**全部消失**，而它们不是负债。
2. **它的代价已经显形**：`external_refs` 必须**刻意排除**在 id 之外，理由是"否则改书目会改 id、打断 DAG、扰动所有既有 fact 的 id"（`schema.py:115-119`）。**引入内容寻址的当天就必须回答"哪些字段算内容"**，而这个问题的答案会随需求变。我们的行比它的节点胖得多（`relations` 一行要装 `quote`/`page_range`/`quote_verified`/`supporting_lit_ids`/`concept_group_key`），**每一次"该字段算不算内容"的判断都会成为一个 id 稳定性事故**。
3. **它解决的两个问题我们已用别的方式解决**：判重有 `dedup_key`/`concept_group_key`；"依赖指向的 id 存不存在"有 `dangling_dep`。**内容寻址唯一带来的、我们确实缺的东西是"级联撤销"**——而那个用 I1（一个字段 + 两条检查）就能拿到 90% 的价值，**不必重写 id 方案**。这正是 I8 结论是"不需要改"的原因。

### W7 三个角色能成立，是因为它只有**一种**子任务；压成三角色不适合我们

Danus 的 3 角色（worker 同构蜂群 / main 只编排 / verifier 只读）之所以够，是因为它的子任务类型只有一种：**证明**。main 不需要懂数学（`ARCHITECTURE.md:17`："conducts, never does math"），worker 池是同构的（`layout.py:232-251` 的 `high:3,xhigh:4`），verifier 只判"这段证明对不对"。

**我们不该学**：我们的 8 个角色**不是"同一件事做 8 遍"，而是 8 种不同的产出与 8 种不同的"最危险动作"**（`《草案》`§1.2 的表：A 把"没搜到"说成"没有"，B 把编的引文当原文，C 把"没枚举完"说成"没有更多"，D 把"查不到"写成"研究发现"，E 把"算对了"说成"证明了"，F 把"卡住"说成"解决"，G 写没有出处的断言，H 自己没证据）。**Danus 的模型里不存在这些区分，因为它的 LLM 验证者对每一条 fact 都做同一个判断。** 把我们的角色合并会**同时**删掉：`SEARCH_OUTCOMES` 的受控词表（A）、引文逐字回验 + `quote_verified` 三态（B）、`truncated`（C）、L1/L2/L3 溯源（D）、`evidence_kind` 的推导（E）、三维预算（F）、`citations` 非空（G）、`ReviewFinding.evidence` 非空（H）。**这正是 `《草案》`§1.1 那句"多几道权限面与验证门就更难骗人"的反面。**

### W8 `strategy/config.py` 的默认价格是**硬编码常量**，且 `cost_usd` 只进台账不进门禁

`strategy/config.py:14-37`：`DEFAULT_PRICE_IN = 31.5`、`DEFAULT_PRICE_OUT = 189.0` 等**内联的每百万 token 美元单价**。`strategy/ledger.py:22-42` 把 `cost_usd` 累加并返回总额，但**没有任何地方把这个总额与"操作员的 spend ceiling"做比较并拒绝**——`AGENTS.md:115` 只说主控**应当**把超过天花板的开销"surface 给操作员"，那是**提示词纪律**。

**为什么不该学**：① 单价写死在代码里 ⇒ **厂商调价后台账会静默失真**（`strategy/README.md:24-25` 承认 `claude-fae-5` 的默认定价是"Anthropic list price (2026-06)"——一个**带日期的**硬编码）；② "记账但不设闸"是**半个预算**：`《草案》`FC-19 的判据①要求"**每个子任务有 token 上限与最长轮次，超额即降级或返回当前最好答案**"。**我们做 I5 时，必须把台账与 I7 式的机械检查连起来**（`ledger_budget_exceeded` warning），否则就是抄了一个"记账但不停手"的形态。

### W9 论文级的再验证是**一次整篇 LLM 调用**，且它的 `must-fix` 判据是**叙述性**的

`paper_math_verify.py:186-192`："我们不切片……**一个提示词，整篇正文。**"；超过 70 万字符就记 `too_large`——**"分解是主控的活"**。而 `must-fix` / `ignorable` 的定义是"**一个本科生能否自行补上**"（`:60-66`）。

**我们该学的部分是"存在这一层"与"判决机械派生"，不该照抄的部分是**：① "整篇一次调用"在大稿件上会**直接撞预算上限**，然后退化成一个需要**主控手动分解**的阻塞——`《草案》`§1.4 对这类"需要人来兜底的自动机制"是**明确不做**的（"一个'假装在思考'的循环比不存在的循环更危险"）；② "本科生能不能补上"**不是一个可判定的判据**，它取决于审阅者是谁。我们要做 I17 时，`must-fix` / `ignorable` 的判据应当写成**可判定的形式**（例如：`must-fix` = "该步骤引用的前提在本库/外部引用中不存在"——那是我们已有的 `dangling_dep` 与 I11 的机械形态；`ignorable` = "该步骤是 Cholesky 分解这类标准教科书写法"——需要一个受控的**论证白名单**，形态照抄 `《草案》`§8.8 的 `ARGUMENTS`）。

### W10 大量"域内调参"的正则禁令（P1/P3/P5 里的 `post-W_q`、`master reduction package`）
`prechecks.py:13-15` 自己写明："**P1/P3/P5 的模式是为特定的证明失败形状调过的（例如 'master reduction package'、'post-W_q'）。它们安全（附加式）但域特定；保留、泛化或禁用以适配你的领域。**" `docs/security-and-trust.md:113-116` 也说这是"**整个验证栈里最带项目味的部分**"。

**为什么不该学（照搬）**：这些正则里有**第一个项目**的具体专名（`post-W_q`）。照搬到我们的框架里会得到一堆**永远不会命中**的检查，而**永远不命中的检查比没有检查更糟**——它给人"我们有这道门"的错觉（`《草案》`§8.12 的"不可能失败的负控比没有负控更糟"是同一个模式）。**要取的是它的形态（三个类别：把目标描述当来源 / 无条件前提 / 模糊指称 + 双段覆盖 + 同段依据判据 + env 开关 + 假阳性可恢复的边界条款），不是它的模式串。** 并且**必须**按 `《草案》`§6.4 在 ≥20 条真实样本上量触发率。

---

## 8. 一句话总结：Danus 相对我们"成熟"在哪些方面、不成熟在哪些方面

**Danus 比我们成熟的地方（三条，都是"系统真的被跑过"才有的东西）**：
1. **它有一个真的在被大量使用的系统**——README 报了一次真实研究运行的事实图规模：**3,157 条已验证事实、8,616 条依赖边、依赖链最深 54 层**，最终定理的支撑闭包 664 条（`README.md:77-83`）。我们最大的实测规模是 25 条真实关系。**规模带来的教训（分块、`too_large`、扇出、进程残留、多项目隔离）我们还没有机会遇到。**
2. **进程与生命周期治理是工业级的**：作业对象 / 树杀 / 收割 / 冷启动隔离 / 原子状态写 / 跨平台引导（`loop.py`、`launcher.py`、`proc.py`）。我们的 FC-20 是"明确的未落地"。
3. **权限面"物理不存在"这一条比我们更硬**：`build_app(role)` 只注册该角色的工具，未知角色 fail-closed 到最只读集合（`roles.py:40-45`），而且它跨的是**进程与协议边界**；我们的是同进程内的工具注册表剥离（`《草案》`§9.2 第 4 条已诚实承认"不是存储层 ACL"）。

**我们比 Danus 成熟的地方（四条，都是设计意图的差别，不是工程量）**：
1. **"没做 vs 做了但没结果"的区分是结构性的**：三态（`bool|None` + 受控 reason，八处形态各不同）、受控词表（`SEARCH_OUTCOMES`/`DEP_STATUSES`/`NEGATION_KINDS`）、`truncated`、`checked`、`no_backend`、`external_unavailable`。Danus 只有二元判决（W1）。
2. **证据等级是机械不可能，不是提示词**：`method != "formal" ⇒ evidence_kind != "proof"`（`schema.py:758`）等五条硬约束 + 复核侧 `PROVED_HERE` 的论证白名单（§8.8）。Danus 用"禁止重计算"的**提示词**代替（W1），而它自己的 `verify/agent/` 目录里躺着 12 个**一次性数值蛮力脚本**（`brute{1..5}.py`、`theorem_check{1..4}.py`、`search_dmin8.py` 等）——**这恰好说明数值计算会自然地长进这个系统，而提示词拦不住它**。
3. **依赖闭合与告警分级是可判定的**：`dependencies` 表 + `dangling_dep` + `external_unavailable` + FC-13 的两句话规则（"表里已记录的缺陷被重算确认 ⇒ warning；表里记录与重算事实矛盾 ⇒ error"）。Danus 的外部引用闭合**交给提示词**（`AGENTS.md:92-108`），且**没有"已记录的已知边界"与"谎报"的区分**。
4. **12 张表的硬约束 + 多表事务 + 可重建存储**：`validate()` 逐行、`LOCK_ORDER`、`events.jsonl` 整行 upsert、`rebuild()` 的信息量守恒三要求。Danus 是追加 JSONL + 读时折叠，无事务无锁无 schema 版本（W4）。

**最该带走的一句**：Danus 与我们是**同一份直觉的两条不同实现路径**——它把"不可信"压缩成**一道门**（只有验证者能写事实），我们把"不可信"摊成**多道面**（8 个权限面 + 12 张表的 `validate()` + 12 条交互的终止条件）。**它的门更窄更硬，我们的面更宽更密。** 而这次观摩最值钱的收获不是"它哪里更好"，而是它**恰好补上了我们几条闭环的最后一环**：**I1（被推翻的级联传播）、I11（依赖的缺陷继承）、I17（成稿后的独立再验证）**——这三条都在做同一件事：**让一个结论的"前提不干净"这件事，沿着我们已有的依赖结构传播下去**。我们已经有 `dependencies` 表了，缺的只是**让它在前提变脏时说话**。

---

## 9. 我没能核实的东西（如实清单）

| # | 未核实的东西 | 为什么没核实 |
|---|---|---|
| 1 | `utc_now()` 的时间精度（决定 W4 的 id 碰撞是否在**微秒**级也成立） | `danus/core/_util.py`（1146B）**未读** |
| 2 | `danus/proc.py`（21107B）的实际实现（作业对象的 Windows 细节、跨平台降级、`kill_tree` 的正确性） | 未读；§6-I13 的成本估计因此可能偏低 |
| 3 | Danus 是否有 **CI**、是否有独立负控套件、是否有"禁 AI 区"清单（FC-09、FC-27） | 只列到根目录有 `.github/` **目录存在**（`Get-ChildItem` 输出），**未进入查看** |
| 4 | `agents/contracts/verifier.md`（12624B）与 `danus/verify/agent/AGENTS.md`（12624B）**字节数相同**，我判断是同一份（`launcher.py:85-94` 把后者 symlink 到前者） | **未逐字比对**，只核对了尺寸与 launcher 的链接逻辑 |
| 5 | `agents/contracts/main_agent.md`（21988B）的完整内容 | 未读；§1/§4 里关于主控的结论来自 `AGENTS.md`(6688B)、`docs/concepts.md`、`docs/cli-and-tools.md`、`roles.py` —— **都在代码或文档中核实过**，未依赖此文件 |
| 6 | `strategy/transport.py`（31349B）的实际实现（重试、step-down、成本计算） | 未读；§6-I5 与 §7-W8 关于"每次显式改参数、失败不静默重试"的结论来自 `strategy/README.md:27-33`，**据文档，未在代码中核实** |
| 7 | `danus/write_paper/server.py` 的其余约 1750 行（含 `paper_write` 主路径、`reference_audit`/`reference_verify` 的提示词构造） | 只读了 `:50-119`、`:1585-1654` 与 grep 出的函数清单；§5 里关于写作流水线**主路径**的结论可能不全 |
| 8 | `orchestration/cli.py`（26803B）的全部动词实现 | 未读；`finalize`/`assign`/`status` 的结论来自 `docs/cli-and-tools.md:21-36` 与 `cli.py:289` 的一行 —— **据文档 + 一行代码** |
| 9 | `danus/verify/agent/*.py`（12 个 `brute*`/`theorem_check*`/`search_dmin8` 等）的用途 | **未读任何内容**；§8 里"这些是数值蛮力脚本"的判断**仅来自文件名与 grep 到的 `time_budget`/`budget_hits` 字样**，不是读代码得出的 |
| 10 | 任何**运行行为**：所有测试是否通过、Danus 是否真能跑起来、`gm` id 碰撞是否真会发生 | **按约束未运行任何代码**。W4 是**从代码推出的可能性**，不是实测缺陷 |
| 11 | `danus.egg-info`、`.backup-model-20260912-164630/`、`verify_scratch/`、`runtime/` 里有什么 | 未进入（`verify_scratch/` 与 `.backup-*` 疑为工作残留） |
| 12 | 我们自己的 `router`/`test1` 代码中 `run_experiment` 当前是否做进程树杀（§6-I13 的①） | **未读我们自己的 `agent_e.py`**；本报告对我方代码的行号引用**全部转引自 `《草案》`**，未独立复核 |

### 9.1 只从 README / 文档读到、**未在代码中核实**的陈述（逐条点名）

| 陈述 | 出处（我读的原文） | 状态 |
|---|---|---|
| **3,157 条已验证事实 / 8,616 条依赖边 / 依赖链最深 54 层 / 最终定理闭包 664 条** | `README.md:77-83` | `（据 README，未在代码中核实）`——这是**该次运行的数据**，我无法在代码里复核；但它决定了 §8 里"它被真正跑过、规模远超我们"这一判断的强度，故必须点名 |
| 一次真实运行的截图/图 `docs/assets/fact-graph.png` 等 4 张图 | `docs/assets/`（`Get-ChildItem` 列到 4 个 PNG，共约 500KB） | **未打开图片**（未用 `read_image`） |
| "六项研究工作案例被它解决" | `README.md:23-25` | `（据 README，未在代码中核实）`；**未去读 arXiv 论文**（按约束不发起网络请求） |
| 三种 consult transport 的具体行为（stream、step-down、`pause_turn`、拒绝回退模型、成本按真实 usage 计算） | `strategy/README.md:18-58` | `（据文档，未在代码中核实）`——`transport.py`(31349B) 未读 |
| `danus` CLI 七个动词的确切语义（`finalize` 只记录不停 worker 等） | `docs/cli-and-tools.md:21-36` | 部分核实（`cli.py:289` 一行）；其余 `（据文档，未在代码中核实）` |
| `write-paper` 六个工具与 `human-summary` 的一个工具的行为 | `docs/cli-and-tools.md:69-101` | 部分核实（`server.py` 的函数清单与两段实现已读）；工具级语义 `（据文档，未在代码中核实）` |
| `verify/agent/AGENTS.md` 里的 P1/P3/P5 禁令**真的会拒掉**一个证明 | `prechecks.py`（正则与编排已读，逻辑成立） | **逻辑已核实，行为未实测**——我没有构造样本、更没有调用验证者 |
| Danus 有 9 个 worker 证明技能 / 3 个 verify 技能 | `ARCHITECTURE.md:56-61`、`Get-ChildItem` 列到 `agents/skills/worker/` 下 9 个 `SKILL.md` | 技能**数量已核实**（列目录）；各技能的内容**未读**（只读了 `write-paper/roles/AGENTS.md` 一份） |
| 观测层只读、不发写调用 | `observability/README.md:1-6`、`app.py:1-23` | 文档 + 文件头已核实；**未逐函数审计**（只读了前 80 行） |
