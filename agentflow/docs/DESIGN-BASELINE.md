# 现行设计基线（CURRENT-DESIGN-BASELINE）

> **这是什么**：把「设计」从旧文档里**择出来**、**按裁定更新过**的**现行**基线。
> 它的用途只有一个：让另一路审计（AU2）报的每一处「设计≠实现」**能按它分级**，
> 而不是拿 2026-10 的旧散文当权威、返回一堆假异常。
>
> **口径来源（业主原话）**：「AU2 路很容易返回一堆异常，因为设计文档已经很旧了」
> ⇒ **旧文档不是权威**。本基线不抄旧文档，只抄**还没被更晚裁定推翻**的那部分，并逐条给出裁定出处。
>
> **盘**：`D:\Incubator`，HEAD `604e7d81`（2026-11-17 落库）。基线内容成形于 `eae92ac2`（2026-11-16）；
> 落库时按现读校正了 B19 / B22–B24 三处读数（`conductor.broadcast` 退场少一件工具、Q1 的
> `literature_pending` 成为收工门第 8 格），其余 48 条逐字保留。
> **条数**：现行 **51** 条（B01–B51）。另：已作废条款 11 条、部分作废 14 条、分不清 4 条（§4 是
> AU3 当时的台账指针，计数保留当时口径；其中 `USER-GUIDE.md:405,674` 已在 2026-11-17 按现盘修正），
> 逐条见 `temp/au3/DOC-STALENESS-LEDGER.md`；裁定时间线见 `temp/au3/ADJUDICATION-TIMELINE.md`。
>
> **路径约定**：本文的路径一律以**仓库根 `D:\Incubator`** 为基准（`agentflow/...` 是项目根，
> `draft/` 与 `projects/` 在仓库根下）。本文件住进 `agentflow/docs/` 之后仍沿用这一约定，
> 以免与它逐条引用的出处串位。
> **行号**：`file:line` 是成形时的读数（行号会漂，2026-11-17 的 AU2b 修正已经把
> `ROLE-SPECS.md` 的行号推移过）；引用时以**条款名 / 符号名**为准，别把行号当规格。
>
> **每条的形式**：`条款` — 一句话 — **裁定/出处**。
> 出处三类：`提交号`（git，仓库根 `D:\Incubator`）、`file:line`（盘上现文件）、`裁定日期＋逐字句`。

---

## §1 权威序（先读这一节；AU2 一半的假异常出在这里）

按强弱排，**上位吃掉下位**：

| 序 | 层 | 位置 | 说明 |
|---:|---|---|---|
| 1 | **业主逐字裁定** | `draft/*`、git commit message、源码里的 `#:` 引语块 | 最高。有一条逐字原话，就能判死任何文档条款 |
| 2 | **实现 + 判据** | `src/agentflow/**`、`tests/**` | `DESIGN-ROLES.md:3-9` 自述「与代码冲突时以代码为准」；`AGENTS.md:104,121` 说权限面的判据守「两层一致」 |
| 3 | **声明层** | `src/agentflow/specs/<角色>.py`（`ACTIONS` / `SPEC`） | `ROLE-SPECS.md:344-350` 自述「三处说法不一致时以 `specs/` 为准」。`capabilities.py` 的四张表是它的派生层 |
| 4 | **生成物** | `docs/ROLE-GUIDE.md`、`docs/SYSTEM-COMPONENTS.md` | `tools/write_system_docs.py` 生成，**不许手改** |
| 5 | **手写规格散文** | `docs/ROLE-SPECS.md`、`docs/ROLE-SPECS-APPENDIX.md`、`docs/USER-GUIDE.md` | 本次审计对象。**已确认有 11 条整条作废、14 条半条作废** |
| 6 | **设计理由文档** | `agentflow/DESIGN-ROLES.md` | 自己写着**「不是行为规格」「只引理由，不引行为」**（2026-10-18 自注）。按它判"实现错了"是最常见的一类假异常 |
| — | **不算裁定** | `docs/READING-MAP.md`、各文档里的工具条数/行数/字节数 | 读数，不是规格。`AGENTS.md:83` 已定「数字是读数不是规格」 |

**一句话**：AU2 若引 `DESIGN-ROLES.md`、`ROLE-SPECS.md` 的散文当"设计"，**先过本基线的 §3**；
基线里没有的，才轮到"设计≠实现"这个判断。

---

## §2 判级规则（AU2 的每一处发现按这四条归类）

```text
甲  实现违反【现行】裁定                      ⇒ 真异常
乙  两份文档互相矛盾、且没有裁定能裁决         ⇒ 交业主裁
丙  实现里有、文档与裁定都没提的新行为         ⇒ 可能是漏记，也可能是偷偷加的 ⇒ 要人看
丁  文档条款已被裁定取代（实现跟的是裁定）     ⇒ 文档过时，不算实现的错
```

**用法（三步）**

1. **定位**：AU2 说「文档 X 行说 A，代码做 B」。
2. **查基线**：A 在不在 §3？在 ⇒ 拿 B 与 §3 那一行比：
   - 一致 ⇒ 这条发现不成立（AU2 读的文档已过时）；
   - 不一致 ⇒ **甲**。
   A 不在 §3 ⇒ 去 `DOC-STALENESS-LEDGER.md` 查 A 的判定：
   - `已取代` / `部分取代` 的失效半句 ⇒ **丁**（并写明是哪条裁定取代的）；
   - `分不清` ⇒ **乙**（附"缺哪条证据"）；
   - 都没有 ⇒ 继续第 3 步。
3. **两边都没有**：A 与 B 都无裁定、也无基线 ⇒ 看是不是"实现多做了一点" ⇒ **丙**；
   若是"两份文档自己打架" ⇒ **乙**。

**四条各自的典型样本（本盘真实存在，可直接对照）**

| 类 | 样本 | 为什么是这一类 |
|---|---|---|
| **甲** | 若有人说「F 的出边应为 `A B C E V`（`ROLE-SPECS.md:187`），代码是 `A C D E V`」 | 反了 —— 代码跟的是 **2026-11-07 业主裁定**，文档过时 ⇒ 是**丁**不是甲。**真正的甲要长这样**：把 `F→B` 加回去（违反 2026-11-07 逐字裁定） |
| **乙** | `ROLE-SPECS.md:1536` 说 V 有 **9** 件通用写工具、`:1561` 与 `:1608` 说 **10** 件 | 同一份文档自相矛盾，而裁定只定了「escalate 是 `write_local`」（2026-11-06），没定"散文里该写几件" ⇒ 交业主/作者裁 |
| **丙** | `capabilities.WRITE_SETS["B"]` / `["E"]` / `["F"]` 都含 `conjectures`，而 `ROLE-SPECS.md:277-288` 三行都没写 | 猜想台账是 2026-11-07/08 之后加的，`83d322f1`（2026-11-15）只记了"conjectures 写集搬家"，**没有一条逐字裁定说"写集要含 conjectures"** ⇒ 要人确认这是有意的登记还是漏记 |
| **丁** | `USER-GUIDE.md:405,674`「收工门**八格**」的**旧组成**（含 `paper`） | 2026-11-14 裁定 `paper` 退出收工判定；2026-11-16 Q1 加 `literature_pending` 之后仍是八格、但**成员不同**（`paper` 不在门里）⇒ 旧组成是丁；2026-11-17 原文已按现盘修正 |

---

## §3 现行基线（51 条）

### A. 角色面（B01–B06）

**B01 — 角色集是 11 个名字：`A B C D E F G H L M V`；`L` 只在 Lean 开关打开时存在。**
「存在」这件事有两根轴：**声明面**（`capabilities.CAPABILITIES` 永远含 L 的 3 个动作，不看开关）
与**行为面**（`for_role("L")` 在 Lean 关时是空集、`formal.*` 不装配、`policy` 判 `forbidden_edge` 带 `lean_off`）。
两轴**不许折成一句"Lean 关时 L 不存在"**。
出处：`ROLE-SPECS.md:318-322`；`leanscope.LEAN_ONLY_ROLES`；裁定 **2026-10-22**（L 新设，`AGENTS.md:113`）。

**B02 — 只读角色 = `C` / `H` / `V`（`tools.READ_ONLY_ROLES`）。**
出处：`tools/__init__.py`；`ROLE-SPECS.md:1537`。

**B03 — 只读的口径是「对其它智能体的产出只读；**自己侧的产物可写**」。**
不是"零副作用"。只读约束的是「不能改别人的东西」。
出处：裁定 **2026-11-01**（`ROLE-SPECS.md:785, 1410, 1498, 1533`；`APPENDIX.md:603, 883, 915`）。

**B04 — 只读角色仍有写工具，且分成三族，全部是**登记**出来的例外：**
① 落库代理：H 4 件（`review.review_document` / `review.verify_fixes` / `review.report` / `review.record_finding`）、
   C 1 件（`analysis.register_report`）、V 1 件（`verify.verify_proof`）—— 走 `READONLY_CALL_EXCEPTIONS`；
② 通用簿记写工具 **10 件**：7 件 `clock.*`（`timer_start` / `timer_cancel` / `alarm_start` /
   `periodic_start` / `periodic_stop` / `timer_purpose` / `wait_any`）+ `conductor.ack` +
   `conductor.post_task` + **`conductor.escalate`**；
③ `conductor.escalate` 的 `side_effect` 是 **`write_local`**（它写父代理收件箱与会话事件流 ——
   通信事件也是工作区写）。
出处：`ROLE-SPECS.md:56-70`（②的清单）＋`APPENDIX.md:280, 301`（分族）；裁定 **2026-10-26**
「通用能力根本不该出现谁能用这个说法」；**2026-11-06** 裁定「丙/乙」把 `escalate` 改真成写（`8aa92286`）。
**注意**：散文层在"9 件还是 10 件"上自相矛盾，见 §4。

**B05 — 没有任何角色能召唤 `M`**（`capabilities.NON_SUMMONABLE == {"M"}`）。
出处：`ROLE-SPECS.md:269`。

**B06 — H 的门引擎有 15 道有名字的门**（`gates.gate_g1` … `gate_g15`）。
出处：`DESIGN-ROLES.md:16, 168`；本机现读。

### B. 召唤边（B07–B13）

**B07 — 出边表（11 行，逐行为准；本机现读，与代码逐字一致）**

| 召唤方 | 允许召唤 | 关键裁定 |
|---|---|---|
| `M` | `A B C D E G H` | 不直连 `F` / `V` / `L`：F 走 `M→D→F`，V 走 `M→B→V` / `M→D→F→V`（`M→V` 2026-10-18 开、**10-20 撤**） |
| `A` | `B` | — |
| `B` | `C D H L V` | `B→H` 2026-10-14；`B→L` / `B→D` 2026-10-22 |
| `C` | **（无出边）** | 2026-10-20 裁定 |
| `D` | `A B C E F` | **不含 `G`**（2026-11-11） |
| `E` | `B D V` | `E→V` 2026-10-23 |
| `F` | **`A C D E V`** | **2026-11-07**：删 `F→B`、加 `F→D` |
| `G` | `C D H` | 2026-11-11 |
| `H` | `A E` | 2026-11-11 去掉 `G` |
| `V` | **（无出边）** | 2026-11-05 |
| `L` | `C` | 2026-10-22 |

出处：`capabilities.ALLOWED_EDGES`（本机现读）＋`ROLE-SPECS.md:179-191`（除 `F` 行，见 B09）。

**B08 — 边总数 = 32**（`sum(len(v) for v in ALLOWED_EDGES.values())`）。
**重要**：2026-11-07 那次裁边是「一减一加」，**总数没变** —— 所以"总数对得上"不能证明"逐行对得上"。
出处：本机现读 32；`ROLE-SPECS.md:193`。

**B09 — `F` 的出边是 `A C D E V`（含 `D`、不含 `B`）。**
裁定 **2026-11-07**，业主逐字：「为了落实口径，裁去F到B的直接出边，防止向下交稿，F只能向上通过D向B交稿。」
＋「向上的意思是F向父代理D交稿」。
出处：`74e243df`（`specs/f.py` 的 `edges` 注释里原样留着这两句）；本机现读。
**⚠️ 这条是文档最没跟上的地方**：`ROLE-SPECS.md:187` 写 `A B C E V`，`:253-259` 还写着「2026-11-05 撤 `F→D`……
F 不再能唤起 D」。**按文档判会误报成甲，实际是丁。**

**B10 — `C` 无出边；链条是 `D → C` 单向，`C` 的"汇报"就是它的返回值。**
裁定 **2026-10-20**，逐字：「把协作改成『D 唤起 C、C 向 D 汇报』，并保留 C 无出边的原始设定」。
出处：`ROLE-SPECS.md:184, 213-216`；`APPENDIX.md:604`。

**B11 — `V` 无出边；入边是 `B` / `E` / `F` 三条。**
裁定 **2026-11-05** 逐字「V 不应该有出边」；`E→V` 由 **2026-10-23** 加。
退回写在**回执**里（点名第几步），由发件人自己改 —— 不靠唤起。
出处：`ROLE-SPECS.md:190, 250-259`；`APPENDIX.md:915`。

**B12 — `L` 的入边只有 `B`、出边只有 `C`；`M→L` / `F→L` / `E→L` / `D→L` 都不存在。**
「用户指定单条执行」（`run-agent L`）是**入口**，不是边 ⇒ 不进 `ALLOWED_EDGES`，也**不许**为它加边。
出处：裁定 **2026-10-22** 逐字（见时间线）；`AGENTS.md:113`；`ROLE-SPECS.md:229-246`；`specs/l.py::LATER_EDGES`。

**B13 — `M` 不直连 `F` / `V` / `L`（只走间接）。**
出处：`ROLE-SPECS.md:181`（M 行）、`:244-245`（`M→L` 不存在）。

### C. 写集（B14–B17）

**B14 — `WRITE_SETS`（11 行，本机现读）：**

```text
A  literature, search_requests
B  conjectures, literature, relations, reprocess_requests, statements
C  analysis_reports, search_requests
D  research_questions, search_requests
E  conjectures, experiments
F  attack_plans, conjectures, reprocess_requests, search_requests
G  dependencies, documents, review_findings
H  documents, review_findings
V  （空）
L  experiments
M  （空）
```

**⚠️ 与散文的差异（丙类）**：`ROLE-SPECS.md:277-288` 的 `B` / `E` / `F` 三行都**没有** `conjectures`。
出处：`capabilities.py`（本机现读）；`83d322f1`（2026-11-15「conjectures 写集搬家」）。

**B15 — `V` / `M` 写集为空；编排器自有 `CONDUCTOR_WRITE_SET = {tasks}`。**
「空」的含义是"在**数据表**这根轴上一张都不写"，不是"没有副作用"（V 写自己维护的凭据台账与签）。
出处：`ROLE-SPECS.md:285-288`；`V.8`。

**B16 — 两张写集相交 ⇒ 两个任务**串行**（并发判据）。**
出处：`ROLE-SPECS.md:273`；`policy.estimate_write_conflict` / `capabilities.write_sets_intersect`。

**B17 — 台账的唯一写者**：
① 命题台账（`statements`）的唯一写者是 `B`（`secretary.STATEMENT_WRITER_ROLES = ("B",)`）；
② **猜想台账的唯一写点在产出侧** —— `D` **没有** `register_conjecture` 这个动作
（2026-11-13 撤除，`8e398d74`；`ROLE-SPECS.md` 的动作表已无它）。
出处：`ROLE-SPECS.md:282, 290-297`；`8e398d74`、`68517bbd`。

### D. 动作与工具面（B18–B21）

**B18 — 动作表共 67 个，逐角色 `A6 B10 C10 D14 E4 F5 G7 H5 V3 L3 M0`。**
出处：`ROLE-SPECS.md:299-322`；本机现读 67（逐个动作名逐字相同）。
**注意**：`L` 的 3 个动作在 Lean 关着时**也在这张表里**（声明面不看开关）。

**B19 — 工具面：Lean 开 126 件 / Lean 关 123 件**（少的三件是 `formal.formalize` /
`formal.check_formal` / `formal.record`）。
出处：`ROLE-SPECS.md` 的 §R0 / §L.4；本机现读 123（Lean 关）。2026-11-16 `conductor.broadcast`
全面退场 ⇒ 127/124 → **126/123**（这一段是落库时按现读校正的，见文件头）。

**B20 — 两根受控轴**：
`side_effect ∈ ("none","read","write_local")`（**旧的 `network` 已删**）；
`external ∈ ("none","egress","exec")`。
「某工具是不是 `network`」这个问题**已经没有取值可答**；要问的是"它的 `external` 是什么"。
出处：`ROLE-SPECS.md:52-54`；`agentspec.EFFECT` / `SIDE_EFFECTS`。

**B21 — 官能轻重的唯一真身是 `specs/<角色>.py::SPEC.emphasis`。**
`agent_prompts.FACULTY_EMPHASIS` 是发布副本、`docs/ROLE-GUIDE.md` 是生成物，**两者都不是真身**。
出处：`ROLE-SPECS.md:344-350`。

### E. 门与收工（B22–B27）

**B22 — 收工门 `closing.DEFAULT_CHECKS` 是 8 格：**
`contradictions` / `load_bearing` / `report_shape` / `user_pending` / `substance` / `acceptance` /
`artifact_ledger` / `literature_pending`。**`paper` 不在格内。**
裁定 **2026-11-14**，业主逐字：「是否出 paper 退出收工判定，由 M 自行判断是否到这个时机」。
`literature_pending` 是 **2026-11-16 Q1** 加的第 8 格（业主口径：「清空待入库文献表及文献 → 真正收工」；
待入库列表还有 `pending`、或当前委托提交后没清表 ⇒ 拦）。
出处：`src/agentflow/closing.py` 的 `DEFAULT_CHECKS`；`tests/test_closing_gate.py`；本机现读 8 格。

**B23 — `paper` 改落 `readings.paper`（verdict 四档），由 `M` 判断时机，不进 `machine_pass`。**
「退出收工判定」不是「这一格不用查」：读收回执/PDF 过期这类事实**仍要报**，只是不再让 `machine_pass` 为假。
出处：同 B22；`28707d01`（把 `paper` 移出格的最后一处断言）；`tests/test_closing_gate.py:966`。

**B24 — 论文段的完成定义 = 八格全过且没有 blocker（`paper` 仍不在门里）。**
出处：`c2cead2b`（2026-11-16，业主逐字『apply补丁，预算批准』）；`tests/test_paper_pack_names_blockers_verbatim.py:10`。
注意 `statements_unsigned` / `mapping_not_written` **不落在八格里**；`paper_pdf_is_stale` 只是 `readings.paper` 的读数。

**B25 — 每格三态，`unknown` **绝不是**通过。**
`ClosingReport.can_close` 是**机器口径**的 `bool | None`，`None` = 没接线/算不出来（既不是过也不是不过）；
`m_says_done` 是 M 在 `m_verdict.met` 里说的那一句。`tri_state_exit_code`：0 要 M 说达成**且**机器读数也过。
出处：`docs/SYSTEM-COMPONENTS.md:40`；`closing.py`；裁定 2026-10-09 与 2026-11-03。

**B26 — 收工按**签**拦，不按计时器拦。**
未产出 V 签稿**且**未放弃 ⇒ 拦；签只是"可 finish"。旧口径「必须起 `wait_for=V` 的计时器」已撤。
出处：裁定 **2026-11-11** 追裁（乙），`50785384`；`specs/f.py` 的收工门按签拦。

**B27 — 收工门的 `contradictions` **自己现算**对立对**；没裁决行就拦，`persistent` 只进读数。
出处：`7e99507f`（2026-11-15，GC·①）。

### F. 上限与预算（B28–B34）

**B28 — 母原则（所有"撤上限"裁定的根据）**：业主 **2026-10-15** 逐字：

> 凡是可能阻止智能体完成大项目的（限制输入、思考、产出、步数等），删或把触发水平抬高到
> 几乎不可能触发（即使触发也是提醒而非强杀）；凡是为了防止智能体频繁犯错的，留；
> 凡是有利于智能体协作或和用户协作的，留。

出处：`draft/123-业主裁定落地（2026-10-15）：卡住智能体的每一道闸.md:3-8`。
**用法**：任何"某上限应当存在"的文档条款，都要先过这一条。

**B29 — F 的攻坚预算是**四类键缺一不可**：`max_rounds=6` / `max_parallel_subgoals=2` /
`max_persist_attempts=2` / `max_depth=2`。**
缺一类 ⇒ `check_budget(complete=False, allowed=False)`；`budget=None` ⇒ `checked=False`
（"没检查"与"预算用尽"是两件事）。`can_round` 与 `can_derive` **刻意分开**。
出处：`DESIGN-ROLES.md:124-126`；`ROLE-SPECS.md:1192-1199`；`tools/attack_tools.DEFAULT_BUDGET`（本机现读）。

**B30 — `policy.Policy` 默认值（现读）**：
`max_chain_depth=6`（台账 6 跳 = 链上 7 个代理）、`max_concurrency=None`（**不设限**）、
`max_direct_children=25`（M 一档 100）、`max_tasks_per_run=5000`、`wall_clock_sec=14400`、
`usd_budget=None`。**`token_budget` 这个字段已不存在**（2026-10-15 撤：只判钱）。
出处：`ROLE-SPECS.md:1963-1971`（逐条与现读对上）；裁定 **2026-11-05**「将深度锁调到6」＋「丙：全局不设限」。

**B31 — H 的复审**没有轮数上限**，收不收尾由 H 显式 `close_as` 决定。**
`unresolved_review` 作为终态保留，但**不再由计数器触发**；**不提供任何轮次读数**
（没有 `round_budget` / `remaining` / `capped` 这类字段）。
裁定 **2026-11-15**，业主逐字：「撤掉这个上限，一切由智能体自行决定，不做读数」。
出处：`99f6a08f`；`src/agentflow/tools/review_tools.py:2142`；`src/agentflow/specs/h.py:40`；
`src/agentflow/capabilities.py:1346`；`agent_skills.py:1436`。唯一受控值 `close_as="unresolved_review"`。

**B32 — 命令行 `--budget-usd 0` = **不设上限**（与 `--wall-clock-sec 0` 同口径）；
额度是**累计**上限，可以略微越界（最后一步已发出的费用收不回），越界只是读数不是错误。**
出处：`docs/USER-GUIDE.md:177-185`（2026-10-27 修）。

**B33 — 并发 plan 上限 2（机械拦截）。**
裁定 **2026-11-13**（业主 Q3+Q4）。
出处：`ae93c96d`。
**注意**：这是**计划级并发**，与 B29 的 `max_parallel_subgoals`（单批子目标规模）、
B30 的 `max_concurrency`（瞬时任务并发）是**三个不同的闸**，别混。

**B34 — 不卡 token，只卡总花销的钱。**
裁定 **2026-10-15** 逐字（见 B28 引语内）。
出处：`draft/123`；`ROLE-SPECS.md:1970, 1987`。

### G. 稿、签与流程先后（B35–B47）

**B35 — 一个稿号 = 一份文件 = 一份证明。`-pN` / 「第 N 份证明」/ `proof_no` 在**写侧退役**，
只作旧盘兼容读。**
出处：2026-11-11 / 11-12 多笔（`c2c25535`、`7601da70`、`ca709961` 等）；`ROLE-SPECS.md` §G / §V 相关行。

**B36 — `B` 与 `E` 各自发稿号（每族一条计数器）；稿号与命题号**解耦**，允许数值重合**
（「数值重合不能代表什么」）。
裁定 **2026-11-11** 逐字：「b侧稿号和命题号耦合是错的」。
出处：`d8d5b78c`（甲）、`48919cf2`（判据）、`84915e9e`。

**B37 — 稿头**不写命题号**；签块第 8 格（命题号）退役** —— 签的归属改锚「手稿号 + 正文 sha + 行上的稿记录」。
裁定 **2026-11-13** 逐字：「稿里没有命题号」。
出处：`a04de92c`（稿头停写 `- 命题号：`）、`893198b8`（第 8 格退役）。

**B38 — 拿签之后**冻结**：这一份稿只读。要改先走 `B.open_polish_copy` 拿副本。**
裁定 **2026-11-11**，逐字：②「后续只对稿允许有只读权」。
出处：`21190116`（丁）、`3e7044dd`、`662ee87e`（F 题面）。

**B39 — `B` 有一条**窄豁免**：只许 `fs.edit` 改**自己号段、未签**的
`reports/b-proof-<六位号>.md`（五道闸：角色 B / 整条路径形 / 只 `fs.edit` / 未签 / 自己号段已发号）。
**
裁定 **2026-11-11**，逐字：④ 后半句「之后 B 在那份 B 稿上改正文」。
出处：`aae2f66e`。

**B40 — `V` **只颁发**签；**落签归收方秘书**（颁发即写签文件）。
「无号先签」是正统主路：签必须有**独立台账背书**（有号 `verifications/<号>.jsonl`，
没号 `verifications/pending/<键>.jsonl`），稿头自述仍是假签。**
裁定 **2026-11-04** 裁定 ①②③ ＋ **2026-11-05 晚**「撤掉没有命题号 ⇒ 不许签那道挡错的闸」。
出处：`54d08e83`、`7927fb88`、`cf346a0e`、`e1bfe3e8`。

**B41 — `V` 对证明只有**两态**：`成立` / `有毛病`（`VERDICTS`）。「看不出来」整档退场**，
模型回那一族措辞按「成立（没找到缺陷）」收；「缺材料」是**没查成**（不落台账行），两者不许折平。
裁定 **2026-10-30**，逐字：「不应该有『看不出来』，『看不出错』就是没毛病」。
出处：`ROLE-SPECS.md:1595-1604`；`89e784a2`、`d839936b`；本机现读 `VERDICTS`。

**B42 — 同一份证明、同一版正文（同 `proof_sha256`）必须**连续 3 次**「成立」且秘书判定通过，
才轮到 V 的秘书落签；第 1、2 次只落台账、`bits.evidence` 不翻位。**
裁定 **2026-10-29**（定稿）。
出处：`ea28c61d`、`babea976`、`02daa512`、`8675ffe7`。
**注意**：这是**签的门槛**（3 次），不是**轮数上限**（上限已撤，见 B31）—— 两个数别混。

**B43 — `D` **只递指针**：命题 / 证明正文由 `B` 从手稿里读；`D` 只给研究方向，**不点命题号**。**
裁定 **2026-11-08**（业主三次改口径）。
出处：`68b01a1f`（块甲）、`7f1302d6`（块乙）、`20a6738c`（块丙）。

**B44 — `F` 交稿**向上走 `D`**：删 `F→B`、加 `F→D`，交稿只走 `D` 的携带单。**
裁定 **2026-11-07**（与 B09 同一条裁定的流程面）。
出处：`74e243df`；`depsection` 携带单第一格新增第三档 `mss:<稿号>`。

**B45 — 依赖面（`## 依赖`）**三列必填、路径号不进稿**（老盘带四列仍读得回）。**
裁定 **2026-11-13**。
出处：`ebdcad53`（示例）、`8f64ca16`（说明）、`94685c99`（拒信）、`f3a1558d`（depsection）、`82bdd0ed`（夹具）。
**⚠️** `ROLE-SPECS.md:282` 仍写「四列表」—— 丁。

**B46 — 命题形态闸：`F` 交稿之前必须证明「条件 → 结论」；持有者是**产出侧**。**
裁定 **2026-11-07**（B 块）＋ **2026-11-13** 裁决（持有者改产出侧；打桩 ⇒ 穷举那一趟写盘前受控拒）。
出处：`0cc085af`、`ea5a40a9`。

**B47 — 放弃的理由与残骸**：
① 命题级 / 计划级放弃理由都是**三档**（`math_error` / `difficulty` / `不再需要`）；
「需要调整」**不是理由**，是组合操作；
② `difficulty` 放弃之后可以拆出引理：**撤掉了"必须早于被放弃命题"的时间戳锚点**，`salvaged` 改**可空**。
出处：① 2026-11-13 业主更正（`a674c57b`、`30246bae`、`2412736a`）；
② 2026-11-15（`1e9b714d`）＋ 2026-11-16 apply（`c2cead2b`）。

### H. 审计与保护面纪律（B48–B51）

**B48 — 三态纪律：把"没查成"与"查过了没问题"折平，是本仓反复踩的坑。**
退出码三态：`0 = clean` / `1 = 已知问题` / `2 = 没查成`；`unknown` **绝不是** `clean`。
命令行侧另有六档（0–5），但那是**运行结局**，与这里的 `noai_gate` 三态不是一回事。
出处：`AGENTS.md:146-156`；`USER-GUIDE.md:630-641`；本机现读 `EXIT_CODE_BY_STOP` 值域 `{0..5}`。

**B49 — 判据不许为了守它而保留过时设计（过时的判据可以动掉）。**
裁定 **2026-11-12**，业主逐字：「不要为了守判据就保留过时设计，过时的判据可以动掉」。
出处：`340919c4`。
**这条对 AU2 直接有用**：判据红了不等于设计对；判据本身可能钉的是旧读数。

**B50 — FC-27 禁改区：7 类、**2 名 reviewer**、**登记 ≠ 批准**、两处清单逐条一致。**
现读：`.noai-paths` 的 `[category:]` 分组 **7** 个；`noai_gate.REQUIRED_APPROVALS_ON_HIT == 2`；
`--baseline` **永远不写 `reviewers`**；`AGENTS.md` 与 `.noai-paths` 由 `check_manifest_consistency()` 按位比对。
出处：`AGENTS.md:9-130`（清单本体）、`:138-144`、`:148-152`；本机现读。

**B51 — 发布门 `release_all.build_steps` 是 **7 步**：
`release-check` / `acceptance` / `repro` / `role-specs` / `coverage` / `per-file` / `frontend`。**
出处：`AGENTS.md:93`（该段刻意不写步号并给了复跑命令）；本机现读同上 7 个 key。

---

## §4 已作废 / 半作废（指针；逐条细节见台账）

**整条作废 11 条**（点名最容易被误当权威的几条）：

```text
DESIGN-ROLES.md:31,49        「E 计算类方法永远拿不到 proof」      ← 穷举通道 2026-10-23
DESIGN-ROLES.md:128-139      「F 的 C/D/F 子目标只记 no_change」   ← 2026-10-26「推理就是 F 的工作方式」
DESIGN-ROLES.md:186-188      「H 工具面全部 none/read」            ← 2026-11-01 只读定义（现 14 件 write_local）
ROLE-SPECS.md:1466,1472,1476-1478  H 的 review_rounds 上限         ← 2026-11-15「撤掉这个上限」
ROLE-SPECS.md:1616           「V 只能召唤 F」                      ← 2026-11-05「V 不应该有出边」
ROLE-SPECS.md:1617           「V 只能被 B/F 召唤」                 ← 2026-10-23 加 E→V（现 B/E/F）
ROLE-SPECS-APPENDIX.md:871   unresolved_review = 到轮数上限         ← 2026-11-15
USER-GUIDE.md:405,674        「收工门八格」的旧组成（含 paper）     ← 2026-11-14 paper 退出；2026-11-17 按 Q1 改成八格（含 literature_pending）
```

**半作废 14 条**（哪半句死、哪半句活，逐句在台账 §1–§4）：

```text
DESIGN-ROLES.md:96-100       E 的 check_formal（动作已归 L）        ← 2026-10-22
DESIGN-ROLES.md:150-154      G 的四个接口（少 render/refresh/write_mapping）
DESIGN-ROLES.md:166-173      H 的 verify_fixes 签名（多 close_as、少轮数参数）
DESIGN-ROLES.md:291-301      §5.3/§5.4（E 的 formal 不可用 / F 不自动推进）
ROLE-SPECS.md:60-70          通用写工具 9 件 vs 10 件（缺 escalate）
ROLE-SPECS.md:187            F 的出边 `A B C E V`                 ← 2026-11-07（B09）
ROLE-SPECS.md:253-259        「2026-11-05 撤 F→D，F 不再能唤起 D」 ← 2026-11-07 又加回
ROLE-SPECS.md:277-288        写集 B/E/F 缺 conjectures（丙类）
ROLE-SPECS.md:453            verify_proof「三态结论」（结论已两态）
ROLE-SPECS.md:466            收工门「论文那一格」+ 七格/八格自相矛盾
ROLE-SPECS.md:1536           V 的通用写工具 9 件（同节 1561/1608 写 10 件）
ROLE-SPECS.md:282            「## 依赖 四列表」                    ← 2026-11-13 三列
ROLE-SPECS-APPENDIX.md:883   H 的 13 件 write_local（现 14）
ROLE-SPECS-APPENDIX.md:915   V 的 10 件 write_local（另处写 11）
```

**分不清 4 条**（缺一次现算，不是设计问题）：
`ROLE-SPECS.md:125`（Issue.code 去重数）、`:329-342`（web 面 4 个读数）、
`USER-GUIDE.md:180-181`（各模式缺省预算）、`:220-318`（网页页数/端点/读面）。
缺的具体命令写在台账 §5。

---

## §5 维护规则（避免这份基线自己变旧）

1. **新增一条裁定 ⇒ 在 `ADJUDICATION-TIMELINE.md` 加一行，并在本文件 §3 改/加条目**（不要只改台账）。
2. **本条基线不许写"读数当规格"**：条数、行数、字节数、`Issue.code` 计数一律不进 §3；
   要写就写"读哪里、怎么复跑"。
3. **每条必须带出处**。只有"某文档说"而没有裁定/代码支撑的，**不许**进 §3 —— 进 §4 的"分不清"。
4. **判级口径变了要改 §2，不是改结论**：甲乙丙丁是业主口径，AU3 无权改。
