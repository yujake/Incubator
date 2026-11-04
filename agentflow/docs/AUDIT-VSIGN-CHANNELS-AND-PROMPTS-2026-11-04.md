# AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04

> 观测时点：2026-11-04 13:45 +0800（HEAD `28b813d6`）。
> 口径：本文件只写今天真发生过的。commit 都能从 `git log --oneline` 核；读数都带来源
> （提交正文 / 现读命令 / 探针路径）。写不出来源的句子不写。
> 硬边界（本轮施工单）：`projects/**` 只读；不跑全量；不动 `PROMPT_VERSION` / golden /
> warm fixture / `docs/ROLE-GUIDE.md`（本文件不重冻任何冻结面）。
> 规模：今天 **141 笔提交、115 个唯一改动路径**（全部在 `agentflow/` 下）。按提交标题统计：
> 审区（提示词↔工具面对拍）**28 笔**（红 10 / 绿 12 / 其余 6）、判据（先红）**13 笔**、
> 修（转绿）**40 笔**。

---

## 一、今天定下的口径（每条附业主原话或 draft 出处）

1. **`experiments` = 机器核验与实验台账**：E 写 `numeric` / `symbolic` / `exhaustive_search`，
   L 写 `formal`（Lean 核验）。出处：业主裁定「不新增，直接改口径」——`701e7398` 的提交正文；
   同日落 `schema.EXPERIMENT_METHODS` 的说明、`Experiment` 的 docstring 与判据
   `tests/test_experiments_ledger_is_machine_verification.py`（a 钉口径 / b 反真空 / c 结构未变）。

2. **穷举 + 针对该穷举的 V 签 ⇒ 落签即 `proof`（不是 `proof_review`）；文字证明 + V 签 ⇒
   `proof_review`。** 出处：`f3408ef6`（甲）的提交正文——「`proof_review` 是「V 逐行审过
   文字证明」，V 不能逐行走查一份程序」，所以「穷举题停在 `proof_review` 本身就是错的终态」。
   档位只由 `verifications._exhaustion_proof_channel` 一处判；判据
   `tests/test_d34_evidence_index_chain.py::test_2b_a_signed_exhaustion_is_proof_before_b_files_it`
   与 `tests/test_t0_tier_and_exhaustion_proof.py::test_criterion1c_...`（`9c3473af`）。

3. **凭据格两类程序共用一格**：`MAPPING.json` 行的 `lean_file`，numeric ⇒ 证明栏第 ① 段那份
   `.py`；formal ⇒ `.lean` + `lean_target`；通道为空 ⇒ 两格必须留空（填了受控拒绝）。
   出处：业主 2026-11-04 逐字「lean 和数值证明程序同用一格不会打架，这一格的功能就是说
   这个命题是百分百真的」（`88dfc83f`）；「空通道两格必须留空」由 `51f81d97` / `12de46fd` /
   `36f7d282` 收口。

4. **合并判准：条件、结论语义上均一致才叫「可以并」；没查成 ⇒ 不并（fail-closed）；词面
   相似度只排序。** 出处：业主 2026-11-04 裁定「没查成 ⇒ 不并（`unknown` 一律不同一行）；
   词面相似度只许用于候选表排序，不许决定并」；「条件有强弱/包含关系（素数 vs 奇素数）⇒
   不一致 ⇒ 不并」（`76dd2971`）。结论那一半由 `28f94baf` 的 `_proposition_matches` 落：
   有模型 ⇒ 用秘书同一套题面复算（条件组 / 结论组，`checked=True`）；没缝 ⇒ 只做确定性
   结构粗筛并标 `basis=structural_probe` / `checked=False`。

5. **F 与 E 均委托入库（→ D 的携带单 → B）；归属判断在 B 的秘书，二维：哪条命题 ×
   哪条证明路径。** 出处：E 侧是业主 2026-11-04 逐字「E的穷举论证和V签也是委托入库」
   （`62aaf255`）；F 侧是既有的 `draft/178-V签三方分工口径（2026-11-02）.md` §五之二
   （业主原话「B侧需寻址获得F侧证明及V签」，D 的携带清单 → B 寻址）。归属收在
   `Secretary._proposition_owner` 一处（`884e514d`）；「第几条证明路径」由 `proof_no`
   （稿头 `- 证明号：<N>` + 携带单第四列）定（`f903822d`）。

6. **H 的「看不出来」不是第三态**：只有成立 / 有毛病 / 没查成（`checked=False`，台账不留行；
   旧行读成「没查成」，不是「成立」）。出处：业主 2026-10-30 裁定 + 2026-11-04 放权施工单
   ①–④（`df703c1c` 逐字引了施工单）。唯一代码读口 `schema.read_review_verdict`；模型面
   第二读口 `specs/h.py:133` 同笔堵上（`49729b99`）。

7. **稿的身份与签解耦**：登记成功（拿到命题号）就改名 `reports/f-proof-<命题号>.md`；
   签另算，搬签失败进 `publish_problem`。出处：业主 2026-11-04 逐字「把"改名"从"有没有
   V 签"里拆出来 —— 登记成功（拿到命题号）就改名，签另算」（`ab7e4fe8`）。

8. **读数必须与判据同一个答案**（「读数说齐、判据说缺」这类已逐个消除）。出处：业主
   2026-11-04 施工单「按通道改写上述每一处」（`6d6e6212`）。今天落地的三处：
   收工门「对应表齐了几行」按证明通道数格（`7dcaec91`）；凭据格「多填 / 填错」也按
   `_lean_problems` 同一结论读数（`dfea1d60`）；`mapping_not_written` 的 blocker 文案按
   通道列格子（`6d6e6212`）。

---

## 二、这一轮修了什么（按面分组，每条给 commit 与一句话）

> 主线是 10 个区的「提示词 ↔ 工具面」对拍：先落红判据、再转绿，最后统一记账与重冻。
> 28 笔审区提交里，10 笔是红、12 笔是绿、6 笔是直接修 / lint；下面只列带语义的落点，
> 纯 lint（R009 去星号强调）与纯文档重生成不逐笔展开。

### 1. 两条凭据通道（Lean / 数值穷举）真机验证

- `c4815086` —— Lean 通道真机读数 + 端到端判据：全仓 **33 条 `method="formal"` 行全是
  `created_by=agent-E*`、0 条 `recorded_by=agent-L`**，3587 条 `statements` 里
  `bits.formal` 有 `verified` 的 **0 条**；临时工作区真跑 Lean 4.7.0：L 的 `record` → B 再
  登记 ⇒ `bits.formal={1:"verified"}` / `grade="theorem"`，四条判据落
  `tests/test_lean_channel_readings.py`（含"Lean 不在就明确 skip、不伪装通过"）。
- `88dfc83f` —— 凭据格按通道判：numeric 必填且必须与证明栏第 ① 段那份 `.py` 同一份
  （`norm_rel` 比）；formal 仍要 `.lean` + `lean_target`；通道为空 ⇒ 两格允许为空；
  「盘上有 Lean 产物」不再是必填触发器（那是读数，不是某一条命题的凭据）。
- `9c3473af` —— 数值穷举通道的端到端回归：E 跑穷举 → B 按猜想登记 → V 三转签 ⇒ 行上直接
  `evidence_kind=proof`（d34 `test_2b` / t0 `test_criterion1c`）；反真空：把
  `numericproof.find_signed_exhaustion_for_column` 打桩成恒 `None` ⇒ 同一条链回到
  `proof_review`。
- `f3408ef6` —— 真回归（6 条全落 `duplicate_statement`）的修法（甲）：
  `_grade_recomputed_from_signature` 的目标档由 `_exhaustion_proof_channel` 定；B 的第二次
  登记认「已在终态」（`at_tier=True` 的空操作成功，不写盘、不新建行）。
- `0b86db09` —— V 落签那一笔按现行签回填档位：真机 `paper-rewrite-84` 的 000000、
  `paper-rewrite-85` 的 000004 / 000005 从 `evidence_kind=heuristic` 升到 `proof_review`，
  F 的可引清单不再恒空（改前 `citable_statements` 只收 `proof_review` 及以上）。
- `91b5affc` —— H 面也按证明通道核 `lean_file`、补索引四格（H 的 `judge` 与 G 的
  `write_mapping` 读同一处判据）。

### 2. 委托入库链

- `62aaf255` —— D 的携带单认 `exp:<实验号>` 键（行上多一格 `experiment_id`）；D 只带
  已签的 e-proof（`experiments.evidence_kind=proof` + `observations.proof_manuscript`
  + 稿在盘 + `vsigns.manuscript_sign_standing` 的 `state=signed`）；B 按地址寻址、第 3 位
  翻真；没签的不带。
- `f903822d` —— `proof_no` 进稿头与携带单第四列；B 按 `crafted | carried | fallback`
  收录并写 `proof_no_source`；在册分支也升档（读手稿签块与 `bits.reviewed`，三路任一命中
  即升，`basis` 多一格）。
- `803056bd` —— B 的改写有了可签载体：新 `src/agentflow/bmanuscript.py` 落
  `reports/b-proof-<命题号>.md`（与 F / E 同形：`## 命题` / `## 证明` / `## 依赖`）；V 用
  同一套未在册散文支、收方 `secretary:B` 落块；`land_rewrite` 三态（写成 / 已签同一份
  一个字节不动 / 已签另一份不覆盖）。
- `e91eb6e9` —— `b_rewrite_carrier`（`land_rewrite`）与 `b_rewrite_sign_landing`
  （`vsigns.land`）两个**真接住方**登记进 DUTIES，没有在 V 的 `decide_sign_issuance` 上
  加宽假探针。
- `b821e45b` —— B 的兜底读盘加第二段「按证明正文认计划名手稿」：87 的六份
  `reports/f-proof-plan-*.md` 里认得出 **3 份**（000000→stmt:000001、000002→stmt:000003、
  000003→stmt:000007），另 3 份被后续轮次覆盖过，必须维持受控拒绝（不许按 glob 取最新）。
- `ab7e4fe8` —— 改名与 V 签拆开（口径 7）：`publish_manuscript` 拆成「改名 + 可选搬签」，
  搬签失败落 `publish_problem`（`sign_sha_mismatch` / `renamed_without_retitle` /
  `target_holds_a_signed_version` 等）；`_apply_round` 的改名判据只剩 `if statement_id`。
- `cf346a0e` / `eaba3971` —— E 的三段改成「两态 / 签名者=收方秘书 / 真凭据是 V 台账那一行
  + `proof_manuscript`」；八份 spec 的「子任务被拒」格从 `refusals` 改名真名
  `subtask_refusals`（每岗都有「监控直接下级」那一条）。
- `d5d6209d` / `ef58b3e9` —— 携带单去重按 **键的身份**分家（`stmt:` / `exp:`）：裸号去重
  会让 `exp:` 行被同号 `stmt:` 行挤掉。
- `d8160787` / `c2c6e119` —— B 的手册从「三列表」改成按四列读：第四格是证明号
  （`#pN`，可空），`exp:` 键与"空表那句话"都写明。

### 3. 合并判准与 fail-closed

- `76dd2971` —— 件 1 收口：没查成 ⇒ 不并；实测「设 p 是素数；则 p 是奇数」vs「设 p 是
  奇素数；则 p 是奇数」`similarity=0.8889`，改前并成 1 行、改后 2 行；读数落
  `adjudication.checked=False` + `fail_closed=True` + `why_not_merged`（点名在册 stmt、
  相似度、阈值）；词面相似度只给候选表排序。
- `28f94baf` —— 件 2 收口：错并的后验判据读 `_proposition_matches`——有模型 ⇒ 用秘书同一
  套题面复算（`checked=True` / `coarse=False`）；没缝 ⇒ 只做结构粗筛并标注
  `basis=structural_probe` / `checked=False`，不许把粗筛写成「判过是错并」。
- `884e514d` —— 件 3 收口：`statementfission.suspected_splits` 接进
  `closing.readings["suspected_splits"]`（不拦门，与 `statements_unoptimized` 同档；读不到
  ⇒ `checked=False` + 理由）；没有证明正文的重复登记也判归属（`duplicate=True` /
  `no_proof=True`，不新建第二行、不并证明号）。
- `8d4046f5` / `315b933d` —— 两处旧用例的前提变了，按「前提变了」重判（前者记甲、后者记
  乙）：同一份证明重交 ⇒ 落新行 + fail-closed 读数；另补「模型判 same」的正控，证明
  fail-closed 关掉的只是「没查成」那一档（不是「什么都不并」）。

### 4. H 三态删除（含唯一读口与模型面第二读口）

- `df703c1c` —— `schema.REVIEW_VERDICTS` 从 `("", "成立", "有毛病", "看不出来")` 收成
  `("", "成立", "有毛病")`，新增 `REVIEW_LEGACY_VERDICTS = ("看不出来",)` 与唯一读口
  `read_review_verdict`（旧值 ⇒ `checked=False` / `legacy=True`，理由写明「旧数据…按没查成
  读」）；`tools/review_tools.py` 不再写第三态（没查成 ⇒ 审核轴三格一个字节不写 +
  `checked=False` + 理由）；`closing` 的 `reviewed_documents` / `accepted_documents` 走唯一
  读口，旧行另给 `legacy_unchecked` / `legacy_unchecked_total` / `legacy_note` 三条读数。
- `49729b99` —— 堵模型面第二读口：`specs/h.py:133` 的「审过 = `review_verdict` 非空」改成
  「审核轴上是「成立」或「有毛病」（旧值「看不出来」按没查成读、不算审过）」；
  `closing.py` 验收表里 `reviewed_documents` 的帮助文字同步改。
- `3e35b2c7` —— `H.judge_quote_semantics` 的 returns 补 `quote_span` /
  `quote_call_sha256`（实现早已返回、声明漏记；与 `e922ff66` 的 `attack.step` 同一类）。

### 5. 依赖面（从全 0 到有读数 + 内容寻址兜底 + C 能自己算污染面）

- `b821e45b` —— 内容寻址兜底（见 §二.2）；87 的六份计划名稿第一次能被收方在登记那一刻
  读到 3 份，另 3 份维持受控拒绝。
- `fdfcf0b0` —— C 的污染面从一句「给两样读数」改成教法：从 `dependencies` 反向多跳、用
  `table.list(table="dependencies", filter={"source_stmt_id": ...})` 读依赖行；`used_by`
  只取 `stmt:` 前缀（`doc:` / `relation:` / `experiment:` 不是命题）；先去掉 `#pN` 证明号
  尾巴再按命题号去重；逐轮迭代到不再长出新号；空集如实报（87 的 `dependencies` 就是
  0 行，空集 = 上游没有在册依赖，不等于这份证明没有问题）。
- `5b258d55` —— PAPER_PACK 第五节的三处码名 / 读数名改成实现里的真名
  （`agent_prompts.py` 的 PAPER_PACK 段）。
- `02e46866` / `5da74a83` —— M 的手册补「依赖节该长什么样」：一张四列表（引用 / 命题号 /
  用在哪一步 / 路径号）+ 被引档位下限 `inadmissible`；缺列、列数不对、号形不对都算没有
  这一节。
- `6d6e6212` —— `mapping_not_written` 的 blocker 文案按证明通道列格子：数值行 = `file`
  （证明栏第 ① 段那份 `.py`）+ `lean_file`（同一份程序）+ `numeric_evidence` +
  `exhaustion_note` + 索引四格，`lean_target` 留空；形式化行 = `file` + `lean_file`（`.lean`）
  + `lean_target`；空通道行两格允许为空。
- `7dcaec91` / `dfea1d60` —— 收工门读数按通道数格、凭据格「多填 / 填错」也按
  `_lean_problems` 同一结论读数 —— 消掉「读数说齐、判据说拒」。
- 真机读数（今天现查 `projects/*/data/dependencies.json`）：`paper-rewrite-84` /
  `paper-rewrite-85` / `ramsey-4-4-87` / `ramsey-4-5-88` / `ramsey-4-5-clean` 的
  `dependencies` **全是 0 行**；受控现场（`tests/test_dependency_wiring_is_live.py` 的 f）
  已能落 `deps_written=1` / `matched_by=proof_body`。

### 6. 新工具 `doc.mapping_cells`

- `838a7d87` —— 新增只读工具：入参 `project` + `statement_id`（`000004` / `stmt:000004` /
  `stmt:000004#p2`）或 `claim_key`，可选 `proof_no`；出参
  `{ok, cells, sources, problems, channel, checked}`。`cells` = 这一行该填的九格；
  `sources[格]` 指到「哪张表哪一行哪一格」或「现算 sha256」；`problems=[{cell, why}]` 逐格
  点名。判据只有一处：通道与「该填哪几格」走 `_credential_slot` →
  `numericproof.formal_slot` → `proof_channel`；`evidence_sha256` / `v_signature.sha256`
  一律现算（`numericproof.object_sha256`）。九条判据（a–h 加一条）先红后绿，含「工具说齐 ⇔
  `papermapping.mapping_reading` 判 pass」的六个现场逐一对拍。
- `6d0eba3c` —— 记账面四处：`TOOL_COUNT` 123→124（`tests/test_tools_returns_declaration.py`）、
  `docs/ROLE-SPECS.md` §R0 第 128 行、`doc_tools.py` 不可见 `ok(...)` 2→3、探针参数与
  `_seed_mapping_cells_probe`（另起 `projects/cells`，不动 p2）。
- `a599677e` —— `ROLE-SPECS` 的数值槽随工具面 124 件重写；`ROLE-GUIDE` 由 specs 现算重生成
  （随 p235 的工具面与文案变化）。

### 7. 提示词与工具面的记账面同步（ROLE-SPECS §R0、工具计数、returns 声明、baseline）

- `e922ff66` —— `attack.step` 的 returns 补 `v_sign` / `delivery_state` / `delivery_label`
  三格（实现早已返回、声明漏记）。
- `3e35b2c7` —— `H.judge_quote_semantics` 的 returns 补 `quote_span` /
  `quote_call_sha256`（见 §二.4）。
- `8bc13565` —— `G.write_mapping` 的 `rows` 补齐判据要求的七格声明。
- `ff67a154` —— `G.compose_claim` 的动作面补齐实现已经接收的 11 格。
- `055e435c` —— 12 个模型面拒因码进 `CODE_TABLE`（类目 `tool_refused_controlled`；出处走
  AST 核，注释里提过不算；一个码名都不新造）。
- `19ef65fc` —— `doc.write_mapping.params` 这次演进按**内容寻址**记进压缩基线（不是重冻、
  不是放宽）。
- `2bd8efc4` —— `repo_survey` 基线按该文件自述口径抬：`src_files_gt800_lines` 73→74、
  `src_functions_gt200_lines` 91→94（三条都能点名）。
- `1e4f40c1` —— 顶层模块登记 `bmanuscript.py`；`DEVELOPMENT-SPEC` §16.12 的
  `ALL_CATEGORIES` 43→44。
- `80f6cb02` —— `refusals` 处数表补两处同 `(模块, kind)` 的手写 `ok=False`。
- `42a803fa` —— 新用例的本地 helper 改名；两处 docstring 指路纠正。
- `06b601d1` —— `ROLE-GUIDE` 随凭据格口径重生成；`READING-MAP` 三格对齐。

### 8. 版本推进 p234 → p235 → p236 → p237 → p238（每版只抬一次）

抬版本各只有一笔：p234 `b5e0b1c6`、p235 `493afdbb`、p236 `36f7d282`、p237 `d0aba915`、
p238 `28b813d6`；其余「冻结面 / 预热读数」笔只补账、不抬版本。

| 版本 | 抬版本（日期） | 动了哪几格 | warm 关 / 开 | warm 合计 | 备注 |
|---|---|---|---|---|---|
| p234 | `b5e0b1c6`（11-03 12:43；`979c5934` 同日补账） | E 一格（`91cad508`→`7c174604`） | $0.021750 / $0.023867（另有诊断趟 $0.002279） | **$0.047896** | 本轮起点；诊断趟 = V 去工具面 + M 跨 run |
| p235 | `493afdbb`（11-04 10:47） | **十一格全换**（八份 spec 的 `refusals`→`subtask_refusals`；新工具 `doc.mapping_cells` 只进 G；A/B/E/F/G/H/L/M/V 的 policy / returns 收口；PAPER_PACK 的 blocker 两类读法） | 关档首跑撞 cap $0.110402（incomplete）+ 补跑 $0.003710；开档 $0.096875 | **$0.210987** | 十一格全换 ⇒ 冷跑 ~$0.10/档是必然代价，不是系统缺陷 |
| p236 | `36f7d282`（11-04 11:08） | G / H 两格（空通道的凭据格必须留空） | $0.057240 / $0.061986 | **$0.119226** | 另有 H 跨 run 探针补录 $0.004506（`8c70c9b6`） |
| p237 | `d0aba915`（11-04 12:27） | B / G 两格（B：`verify.verify_proof`→`V.verify_proof`；G：凭据格点着 L） | $0.025049 / $0.031058 | **$0.056107** | |
| p238 | `28b813d6`（11-04 13:19） | G 一格（`LEAN_FILE_ROW` 措辞定版） | $0.022089 / $0.028077 | **$0.050166** | HEAD |

- 五版 headline 合计 **$0.484382**；把 p236 的 H 跨 run 补录算进来是 **$0.488888**。
- 逐格旧值 → 新值（摘要口径 = Lean 开档）：p234 只有 E；p236 G `2aca56d9`→`fc79c5df`、
  H `4715fc66`→`ba7efe69`；p237 B `07a9cfcf…`→`8a9a5f98…`、G `fc79c5df…`→`7edc4042…`；
  p238 G `7edc4042…`→`9dd228d8…`。其余格逐字同值（现算 confirmed）。
- **为什么「只动一格」的版本也会让十一格字符串都变**：版本行在每一份提示词末尾，抬版本
  时 11 个角色的 prompt 字符串都多一处 `- 提示词版本：pNNN`；摘要按版本行归一之后才只显示
  实际改动的那几格。p237 的 golden 行级 diff 是「九格只有版本行 + B / G 各多一处」；p238 是
  「十格只有版本行 + G 多一处」。
- **判摘要口径 = Lean 开档**：`tests/conftest.py:178` 在导入期钉
  `os.environ["AGENTFLOW_LEAN_ENABLED"] = "1"`（由 `test_settings.py::test_the_suite_pins_the_lean_switch_on`
  守着）；产品缺省是关档，两档的 warm 读数分开记。

---

## 三、已知缝隙（每条：形态 / 后果 / 为什么现在不修 / 将来收平的落点）

1. **误拦：numeric 通道的 `example` / `experiment` 行。**
   - 形态：`papermapping.is_numeric_row` 今天已改成读通道（`51f81d97`，`kind` 不再参与），
     但通道判不出来时仍要兜底 `numerictheorem.is_program_proof`；`example` / `experiment`
     行的程序往往还没被 E 签成穷举，兜底会把「程序证明」当「数值定理」，于是缺
     `numeric_evidence` 时该行被按数值行拦。
   - 后果：这类行可能落到「一处读数说齐、另一处判缺」的老形态；真机 **0/110**（施工单给定
     读数）——它是**潜在缝隙**，不是今天正在流血的口子。
   - 为什么现在不修：要不要把 `example` / `experiment` 行算作「数值定理」本身是口径问题
     （不是 code patch）；改 `is_numeric_row` 会同时动 `_row_checks` / `mapping_cells` /
     `mapping_reading` 三处，且会改变 `mapping_proof_program_unbacked` 那条红的射程。
   - 落点：先由业主裁「example/experiment 行有没有数值凭据义务」；代码上只在
     `papermapping.proof_channel` 一处收（禁第二套「这行是不是数值定理」）；回归加在
     `tests/test_mapping_three_known_gaps.py` 的 a 旁边（现已有 a 的 example 现场）。

2. **读数更松：`numeric_evidence` 自报 numeric 而通道为空。**
   - 形态：`numeric_evidence` / `exhaustion_note` 是模型填的字符串；通道是从论文正文与
     E 的穷举台账推的。两者不是同一来源。
   - 后果：改前这类行在 `mapping_reading` 与收工门两边读数不一致。今天判据侧已收平
     （`51f81d97` 第 6 条：空通道而有 `numeric_evidence` / `exhaustion_note` ⇒
     `mapping_numeric_evidence_missing`，`mapping_reading` 与 `closing.paper_mapping_cell_reading`
     读同一条）；提示词侧也同步（`12de46fd`：空通道不许自称数值证据）。
   - 余项：`_lean_problems` 只判「有没有通道」，**不判「那条 `exp:` 是否真被签 / 是否与
     正文同一份程序」**——后者在 `numericproof.filing_problems` /
     `numerictheorem.evidence_index_problems`。所以「有通道 + 自报的 exp 号是假的」仍可能
     要等索引四格判据才拦。
   - 为什么现在不修：把「exp 是否真被签」并进 `_lean_problems` 会让凭据格判据依赖
     experiments 台账的读法，超出今天「按通道数格」的射程。
   - 落点：`numericproof.filing_problems` 已有三段式核；将来把它的结论并进
     `doc.mapping_cells.problems` 的同一格（工具已有 `problems` 通道，不必新开读口）。

3. **判据侧选择：空通道填凭据格。**
   - 形态：空通道（证明栏里既没有程序也没有 Lean 源码、台账里也没有 E 签的穷举）而
     `lean_file` / `lean_target` 填了东西——包括「合法的 `.lean` + 真实声明名」这种看起来
     最像对的填法。
   - 后果：改前 `_lean_problems` 对「合法 .lean + 真声明名」实测原话是「（无问题）」⇒ 读数
     按同一结论报齐（`dfea1d60` 的边界）。今天已改为**受控拒绝**（`51f81d97` 第 5 条：
     空通道填任一格 ⇒ `mapping_lean_file_missing`，点名「凭据格不许填，填了就是无依据的
     声称」）；`mapping_reading` / 收工门 / `doc.mapping_cells.problems` 读同一条。
   - 余项：`doc.mapping_cells` 是只读工具，它只**报** `problems`，不**拒**；真正拒的是
     `doc.write_mapping` 与收工门。若调用方只看 `cells` 不看 `problems`，仍可能把「填了」
     当成「齐」。
   - 为什么现在不修：给工具加 `forbidden_cells` 之类的键是新接口，今天只做读侧；而且「空
     通道」的判定本身依赖 `proof_channel`，先让它稳一版再动接口。
   - 落点：`doc.mapping_cells` 的 `cells` 里对空通道显式给 `""` + `sources` 写「必须留空」，
     或在 `problems` 之外加一个 `forbidden` 键；回归在
     `tests/test_doc_mapping_cells_tool.py` 的 c / d 旁边。

4. **提示词是开关的函数：Lean 关档时 L 不进提示词 ⇒ `lean_switch` / `l_collab` 两条判据在
   关档下没有对象。**
   - 形态：`leanscope.is_hidden` 在关档把 L 从提示词里摘掉（`test_lean_switch_points_at_l.py`
     ③ 钉着「关档时所有可见角色渲染文本里 `L` 出现 0 次、`formal.` 出现 0 次」）。
   - 后果：`test_lean_switch_points_at_l.py` 的 ①（「讲 Lean 形式化的句子都点着 L」）与 ②
     （「L 自己的提示词有实质内容」）只在开档有射程；关档下能判的只有「L 不出现」，判不了
     「L 的协作面说得对不对」——对象不存在。`test_l_collab_surface_is_exactly_this.py` 虽然
     两种档都测，但关档那一半断言的是「四条边与 L 全部不可见」，不是「L 的协作面文案逐字
     不变」。
   - 为什么现在不修：这是产品缺省的必然形状（业主 2026-10-12：「默认设置中 Lean 关闭帮用户
     在无严苛要求时省钱」）；要在关档下判「L 的协作面」就得先造一个「关档下 L 仍存在的
     对象」，那会反过来违反「L 被开关隔离」这条硬口径。
   - 落点：把「关档下 L 的协作面判据无对象」登记进 `LEAN-MODES.md` 的矩阵（不是判据），
     并在 `test_lean_switch_points_at_l.py` 的 ③ 上补一条读数「本档下 ①② 不适用（skip 的
     理由不是通过）」；将来若要判关档，判的对象应是「关档下 L 的四条边与提示词面都不存在」
     （已有 `test_l_collab_surface_is_exactly_this.py` 的 off 档）。

---

## 四、花费与冻结账

### 4.1 warm 花费（每版两档）

见 §二.8 的表。headline（与本轮施工单给的数逐字一致）：

| 版本 | warm 合计 |
|---|---|
| p234 | **$0.047896** |
| p235 | **$0.210987** |
| p236 | **$0.119226** |
| p237 | **$0.056107** |
| p238 | **$0.050166** |

- p235 是唯一撞过 `--cap-usd 0.10` 的一版：关档首跑 $0.110402（`incomplete`：A–M 已落、
  secretary 与二调样本没发）⇒ 补跑 $0.003710（命中 99%+）⇒ 开档 $0.096875；合计
  $0.210987 = 4.4× p234，原因就是「十一格全换」。
- p234 的 $0.047896 是三趟：关 $0.021750 + 开 $0.023867 + 诊断 $0.002279（V 去工具面 +
  M 跨 run）。第三趟是补 p230 那条诊断读数被挤出 `MAX_RUNS_KEPT=16` 窗口的缺口。
- p236 的 $0.119226 之外，`8c70c9b6` 另花 $0.002106 + $0.002400 补 H 的跨 run 探针
  （39,936/40,089 = 99.6% 关档；40,192/40,416 = 99.4% 开档）——这两笔不在 $0.119226 里。
- 五版合计 **$0.484382**（含 H 补录则 **$0.488888**）。

### 4.2 冻结账

| 版本 | `PROMPT_VERSION` | agent 面 golden | tool 面 golden / 声明基线 | warm fixture |
|---|---|---|---|---|
| p234 | `b5e0b1c6` | `979c5934` | — | `979c5934` |
| p235 | `493afdbb` | `f78eaaca` | `f78eaaca`（工具 123→124） | `5cab9ed3` |
| p236 | `36f7d282` | `5e1af58f` | `5e1af58f` | `6579587e` + `8c70c9b6` 补录 |
| p237 | `d0aba915` | `d0aba915` | 0 处改动 | `d0aba915` |
| p238 | `28b813d6` | `28b813d6` | 0 处改动 | `28b813d6` |

- **版本行在提示词末尾 ⇒ 抬版本时十一格字符串都变**；摘要按版本行归一后才只显示实际改动
  的那几格（p237 / p238 的 golden 逐角色 diff 都是「九格只有版本行」）。这条是 `d0aba915`
  与 `28b813d6` 正文里逐字写下的。
- **判摘要口径 = Lean 开档**（见 §二.8 的 conftest 那条）。两档 warm 读数分开记，判据阈值
  `_cross_run_problem` 的 floor 仍是 0.90，今天一个字没动（`8c70c9b6` 正文）。
- p238 的 `tests/golden/tool_surface_snapshot.json` 与
  `tests/fixtures/tool_declaration_baseline.json` **0 处改动**（这一批没加 / 删工具，也没改
  任何工具的说明 / 参数 / 返回）；agent 面 golden 只动 `/roles/*/prompt` 11 处。

---

## 五、还没做 / 待人的（明确列出）

### 5.1 FC-27 批准台账仍是 stale，需 2 名 reviewer 重新批准

`python agentflow/scripts/noai_gate.py --git --since 35d6432ed57ada84cde29ab31031c2f43ab66fe7 --check-approvals`
（`35d6432e` = 今天第一笔 `701e7398` 的父提交）⇒ **EXIT=1，命中 16 条禁改区路径，16 条未获
批准（stale 16），reviewers 0/2**。命中文件：

- `src/agentflow/capabilities.py`（auth-audit）
- `src/agentflow/schema.py`（schema-migration + eval-criteria）
- `src/agentflow/specs/a.py`（auth-audit）
- `src/agentflow/specs/b.py`（auth-audit）
- `src/agentflow/specs/c.py`（auth-audit）
- `src/agentflow/specs/d.py`（auth-audit）
- `src/agentflow/specs/e.py`（auth-audit）
- `src/agentflow/specs/f.py`（auth-audit）
- `src/agentflow/specs/g.py`（auth-audit）
- `src/agentflow/specs/h.py`（auth-audit）
- `src/agentflow/specs/l.py`（auth-audit）
- `src/agentflow/specs/m.py`（auth-audit）
- `src/agentflow/specs/v.py`（auth-audit）
- `src/agentflow/tools/verify_tools.py`（prover-bridge）
- `tests/golden/agent_surface_snapshot.json`（eval-criteria）
- `tests/golden/tool_surface_snapshot.json`（eval-criteria）

台账本身（`.noai-approvals.json`）AI 一个字节未动 —— 登记 ≠ 批准，批准栏只能由人
`--approve` 追加。业主 2026-11-04 的放权只改变「谁许可」，不改变 FC-27「人逐行走查 + 2 名
reviewer」的要求（`df703c1c` / `49729b99` / `99c6c2ec` 等提交正文都逐字写了这句）。

### 5.2 `repair --backfill-grades --apply` 未执行（dry-run 四栏表已有）

dry-run 是只读探针 `temp/probe_backfill_four_columns.py`，逐行调
`verifications._grade_recomputed_from_signature`，四栏口径（业主 2026-11-04 定稿）：
**会升 / 已是最高 / 凭据不够（`unsigned` / `stale` / `rejected` / `holding`）/ 没查成
（`checked=False`）**。今天现跑读数：

| 工作区 | 行数 | 会升 | 已是最高 | 凭据不够 | 没查成 |
|---|---|---|---|---|---|
| `paper-rewrite-84` | 65 | 1（000000 → `proof_review`） | 0 | 64（unsigned 61 / stale 1 / rejected 2） | 0 |
| `paper-rewrite-85` | 16 | 2（000004 / 000005 → `proof_review`） | 0 | 14（unsigned 10 / holding 1 / rejected 2 / stale 1） | 0 |
| `ramsey-4-4-87` | 8 | 0 | 5 | 3（unsigned 3） | 0 |
| `ramsey-4-5-clean` | 2 | 1（000000 → `proof`） | 0 | 1（unsigned 1） | 0 |
| `ramsey-4-5-88` | 0 | 0 | 0 | 0 | 0 |
| **合计** | **91** | **4** | **5** | **82** | **0** |

**执行前的一个硬前提**：HEAD `28b813d6` 上 `agentflow repair` 只暴露 `--related`
（`src/agentflow/cli.py:4959-4961`；`--related` 本身已随 S1r 并表受控退役），
`--backfill-grades` 这个开关**还没有接进 CLI**。也就是说上面这句「未执行」里的命令，在
当前 HEAD 上还跑不起来 —— apply 入口要先落这一格（CLI 子命令 + 四栏表的 `--json` 形态），
再谈执行。落点：`tools/legacy_cli/repair.py` 的 `main(args)` 或新命令；执行时按四栏表
逐条落 `evidence_kind`，不碰 `statements` 正文。

> **更正（2026-11-04，`repair --backfill-grades` 接进 CLI 之后）**：上面那张表由只读探针
> `temp/probe_backfill_four_columns.py` 产出，而探针在 `proof_review_gap().state` 为空串时
> 用 `or "unsigned"` 猜了一个值。历史读数不改，结论以本段为准：
>
> 1. `paper-rewrite-84` 的 65 行里有 60 行是 `kind="concept"`。概念不参与等级链
>    （`evidencebits.derive_grade` 对 `kind="concept"` 短路成 `not_applicable`）⇒ 它们既不是
>    "凭据不够"，也不在本命令这条轴上：单列、不计入四栏。84 的真实四栏是
>    会升 1 / 已是最高 0 / 凭据不够 4 / 没查成 0，另概念行 60（1 + 0 + 4 + 0 + 60 = 65）。
> 2. 表里那批 `unsigned` 有一批其实是 `state == ""`：`proof_review_gap` 在"台账文件不在
>    盘上 / 空文件 / 没有证明正文"三支提前 return，没写 `state`（该函数是写入期闸与审计
>    共用的判据，本次一个字都没改）。命令按"打印原值、不许自造枚举"的口径把它打成
>    `state=（空；ledger_missing=true，…）`（从来没送审）/
>    `state=（空；ledger_present=true、rows=0，…）`（台账在、但一行都没有）/
>    `state=（空；gap 没给台账路径…）`（没有证明正文）。
> 3. 下面那句"执行前的一个硬前提"已经过期：`--backfill-grades` 已接进
>    `src/agentflow/cli.py`（parser 的 func 是 `_repair_dispatch`；`cmd_repair` 本身一字未动，
>    不带旗标仍原样转发 legacy）。`--apply` 仍没有在 `projects/` 上执行过。
>
> 接进 CLI 之后现跑的四栏（`agentflow repair --backfill-grades`，dry-run，2026-11-04）：
>
> | 工作区 | 行数（概念行） | 会升 | 已是最高 | 凭据不够 | 没查成 |
> |---|---|---|---|---|---|
> | `paper-rewrite-84` | 65（60） | 1（000000 → `proof_review`） | 0 | 4（rejected 2 / stale 1 / state=（空：台账不在盘上）1） | 0 |
> | `paper-rewrite-85` | 16（0） | 2（000004 / 000005 → `proof_review`） | 0 | 14（state=（空：台账不在盘上）10 / holding 1 / rejected 2 / stale 1） | 0 |
> | `ramsey-4-4-87` | 8（0） | 0 | 5 | 3（state=（空：台账不在盘上）1 / state=（空：没有证明正文）2） | 0 |
> | `ramsey-4-5-clean` | 2（0） | 1（000000 → `proof`） | 0 | 1（state=（空：没有证明正文）1） | 0 |
> | `ramsey-4-5-88` | 0（0） | 0 | 0 | 0 | 0 |
> | `paper-rewrite-big`（5 小时真机跑动中，只读） | 0（0） | 0 | 0 | 0 | 0 |
> | **合计** | **91（60）** | **4** | **5** | **22** | **0** |
>
> 合计那一列的关系：会升 4 + 已是最高 5 + 凭据不够 22 + 没查成 0 + 概念行 60 = 91 行。

### 5.3 F 的发布解耦已做（甲），但 `projects/` 里的历史 plan 名稿不回填

- 已做：`ab7e4fe8` 把「改名」从「有没有 V 签」里拆出来，`_apply_round` 的改名判据只剩
  `if statement_id`；`publish_manuscript` 三态（只改名 / 搬签 / `publish_problem`）。
- 没做：`projects/ramsey-4-4-87/reports/f-proof-plan-000000.md` … `-000005.md` 六份**仍是
  原名**（真机读数：按号命名的 **0/6**）；今天新加的 `_retitle_applied` 只处理调用方手里
  这一份，不遍历、不回填。
- 为什么现在不做：`projects/**` 只读（本轮硬边界）；`ab7e4fe8` ④ 明确「老工作区不回填」；
  批量改名还会把「上一轮证明的依赖面」挂到这一条命题头上（不许按 glob 取最新）。
- 现在能做的替代：`b821e45b` 的内容寻址兜底在**登记那一刻**按证明正文认计划名稿，87 的
  六份里认得出 3 份；另 3 份被后续轮次覆盖过，必须维持受控拒绝。
- 落点：由业主决定是否对 87 做一次性回填（这是一次 `projects/` 写操作，需要人批），或者
  等下一次登记时按 `f-proof-<号>` 自然改名。

---

## 附：本文件用到的复跑命令（都不跑全量）

```bash
# 今天的分区计数（审区 / 判据 / 修）
git log --since="2026-11-04T00:00:00+08:00" --pretty=format:"%s" | grep -cE '^审 '
git log --since="2026-11-04T00:00:00+08:00" --pretty=format:"%s" | grep -cE '^判据'
git log --since="2026-11-04T00:00:00+08:00" --pretty=format:"%s" | grep -cE '^修'

# 版本 / 冻结面
grep -n 'PROMPT_VERSION = ' src/agentflow/agent_prompts.py
grep -n 'TOOL_COUNT = ' tests/test_tools_returns_declaration.py

# 依赖面真机读数（本文件引的那五个工作区）
python -c "import json,pathlib; [print(n, len(json.loads((pathlib.Path('projects')/n/'data'/'dependencies.json').read_text(encoding='utf-8')).get('rows', []))) for n in ('paper-rewrite-84','paper-rewrite-85','ramsey-4-4-87','ramsey-4-5-88','ramsey-4-5-clean')]"

# four-column dry-run（只读，一个字节不写）
python -X utf8 temp/probe_backfill_four_columns.py

# FC-27 台账（stale 16 / 0 approved）
python scripts/noai_gate.py --git --since 35d6432ed57ada84cde29ab31031c2f43ab66fe7 --check-approvals
```
