# 审计：五方 × 四步（产出 / 签字 / 收录 / 优化）与 E 的特例（2026-11-03）

> 口径唯一来源（已全文读）：
> - `draft/178-V签三方分工口径（2026-11-02）.md`
> - `draft/179-证明优化两阶段录入口径（2026-11-02）.md`
> - 业主新裁逐字：「E 在数值证明拿 V 签的时候流程和 F 一模一样，若未实现请先实现」
>
> 机器：`projects/paper-rewrite-86`（只读）：161 条 tasks、15 条 statements、6 条 experiments、
> 27 条 V 任务、1 条 E 任务、9 个 `verifications/<号>.jsonl`、3 份 `out/vsigns/*.json`。
> 代码读数按本次改动之后的 HEAD（`3bfd1ae4`）现读；`file:line` 都是当前行号。

---

## 〇、一句话结论

- **F 那条链是通的**（稿 → 派 V → 三轮 → 收方秘书落块 → B 读稿收录），但**真机 86 里它一次都没完整跑过**：
  F 产出 0 份证明手稿、D 的携带单 0 行、V 的 3 份签 `artifact_path` 全是空串（签不在稿上）、
  B 自己写了 7 份正文（`out/B-proofs/`）。
- **E 那条链改前是断的**（三处：没有"被签的稿"、收方表没有 `secretary:E`、"签"是 E 自报的
  `e_signature`）。本批已按 F 的同一套实现（§五），判据 7 条全绿，反真空两处都咬得住。
- **提示词面还差两块**：E 的 policy（FC-27 禁改区）仍只说"把证明栏交给 V"、不说手稿；
  B 的 policy/手册对 179 的两阶段录入（`optimized` / 精准替换）**0 处提及**。

---

## 一、主表（行 = 五方 × 四步；列 = 设计 / 代码 / 差在哪 / 严重度）

| 方 | 步 | 设计怎么走（口径） | 代码怎么走（file:line） | 差在哪（读数） | 严重度 |
|---|---|---|---|---|---|
| **B** | 产出 | B 不产证明：只把来源正文登记进 `statements`（179 §二之一「机械录入」= D 的手稿逐条记一笔） | 写口唯一：`Secretary.record_statement`（`secretary.py:1289` `STATEMENT_WRITER_ROLES=("B",)`），入口 `register_statement`（`agent_b/register_statement.py:1237`） | 86：15 条里有 8 条 `proof_authors=['F']` 而盘上 0 份 F 稿；B 自己写了 7 份正文（`out/B-proofs/000000-p1.md` …）；这些正文当时的签读数是 `reviewed 2/15` | 偏差（历史读数）；今天同一形态会被 `_unsigned_proof_gate` 拒（`register_statement.py:2091`） |
| | 签字 | 文献侧才派 V；F/E 产的天生带签，不重复要（178 §六） | `specs/b.py:341-344`；B 的 V 入口 `specs/b.py:545` `edges=(…,'V')` | 86：B 派 V 22 条（占 27 条的 22），全部是"在册命题 + 无稿"路径；V 的 parent 是 B ⇒ 收方 = `secretary:B`，而 8 条命题作者写的是 F（"谁产出谁送审"在这 8 条上不成立；`submitter_is_not_author` 只读不拦） | 偏差 |
| | 收录 | 第一来源 = D 呈递的研究手稿（命题号 / 地址 / sha），按地址寻址取正文与签；兜底读盘只是降级 | 三来源：`proof_manuscript` 参数（`register_statement.py:1237`）→ D 清单 `## 携带的证明手稿`（`depsection.carried_manuscripts`）→ 盘上 `reports/f-proof-<号>.md`（`depsection.manuscript_relpath`）；认签三处：手稿块 `register_statement.py:2981`、pending 台账、侧文件 | 86：D 的携带单 0 行（`reports/000000-research.md:108` 原话"这一趟没有可携带的 F 证明手稿"）；B 于是走了"无稿"路径。兜底读盘**只认 `f-proof-`**（`depsection.py:131-143`）：E 的 `reports/e-proof-*.md` 进不了这一路 | 偏差（E 的稿进不来；F 那一路设计正确） |
| | 优化 | 两阶段：一阶段机械录入（`optimized=false`）→ 二阶段逐个洗、重拿签、精准替换（旧正文进 `proof_history`）→ `optimized[proof_no]=true` | `register_statement.py:819`（换正文时按 `_signature_covers` 置 true/false）、`:859`（新挂一份 = false）；读口 `evidencebits.with_optimized_flag:711`、`closing.py:4947`（第二阶段读数）、`papermapping.py:730` / `webui/readers.py:1466`（页面三态） | 86：`optimized` 缺格 14/15（`not_recorded`），`{'1': true}` 只有 1 条（000000）；代码行为对，但**提示词 0 处提及**（见 §三 第 8 条）。另：000000 出现 `optimized=true` 而 `reviewed_sha_by_proof` 仍指旧正文的 sha（`_bits_after_canonical_write` 刻意保留旧值，`register_statement.py:584-610`）⇒ 同一行两个读数各说一份正文 | 偏差 |
| **D** | 产出 | D 写研究手稿（七节）+ 带「## 携带的证明手稿」三列表；索引四格由 G 的 `write_mapping` 落（D 只凑格） | `agent_d/write_report.py:10`；携带表 `depsection.CARRIED_HEADING`（`depsection.py:95`）、渲染 `write_report.py:511`；索引四格 `numericproof.INDEX_*`（`numericproof.py:976-983`）+ `papermapping.index_rows` | 86：研究手稿在、携带节在、表空；D 的 V 任务 0 条（一致） | 偏差（无稿可带，不是 D 写错） |
| | 签字 | D 不派 V；只核"F 交回的证明带 V 的签字"，缺就让 F 补签 | `specs/d.py:240`（"你不要自己派 V"）；核签读数 `verifications.proof_review_gap` | 86：D→B 回执"覆盖 0 条携带行，B 收下 0 条"（`reports/000000-research.md:112`） | 一致（设计层面） |
| | 收录 | D 不写 `statements`；把（命题 + 地址 + sha + v_signature）交 B | `write_report.py` 报告 + 派 B；`register_statement` 的 `index_rows` 读的是 MAPPING.json | 86：0 条经 D 的路入册（15 条全是 B 自己登的） | 偏差 |
| | 优化 | D 不参与 `optimized`（无写口） | 无 | — | 一致 |
| **F** | 产出 | F.step 把论证渲染成 `reports/f-proof-<号>.md`（`## 命题` / `## 证明` / `## 依赖`）；F 不手写这份稿 | `agent_f/manuscript.py:204`（`proof_manuscript`）、`:283`（`publish_manuscript` 改名）；`fs.write` 对它是 `reserved_framework_artifact` 受控拒绝 | 86：F 12 条任务、0 份 `reports/f-proof-<号>.md`（只有 2 份 `f-proof-plan-*.md` 计划稿）；`reports/` 里 0 份证明手稿 | 偏差（F 没产出；不是链断） |
| | 签字 | F 自己派 V 审这一份；未在册给 `proof_manuscript`；三转成立才落块 | `specs/f.py:138-145`；V 侧 `agent_v/core.py:1504`（散文那一支） | 86：V parent=F 4 条（t-000049 / t-000086 / t-000118 / t-000090）；3 份签文件 `artifact_path=""`（没走手稿）⇒ `manuscript_write.state=not_attempted`（"没有手稿路径"） | 偏差（签落在侧文件，不在稿上） |
| | 收录 | B 读 F 的稿（`proof_manuscript` / D 清单 / 盘上） | 同 B 收录那一行 | 86：0 条 F 稿被收录过 | 偏差 |
| | 优化 | 改稿 ⇒ 重派 V（新正文新签），旧签读成 stale | `verifications.review_standing:2980`；`register_statement.py:795-823` | 86：000000 有两份正文两份签（`2ea6d066…` / `186d45ed…`）⇒ 逐份签这一档是通的 | 一致 |
| **V** | 产出 | V 只产：`verifications/<号>.jsonl` 一行 / `verifications/pending/<对象sha>.jsonl` 一行、`out/vsigns/<正文sha>.json`、以及"该由谁落"的信封 | 台账 `verifications.record_verification` / `record_pending_sign:627`；签 `vsigns.issue:919`（`written_by` + `envelope.to`） | 86：9 个台账文件、3 份签、0 个 pending 文件；签文件 `written_by=secretary:B`（收方对） | 一致（颁发这一半） |
| | 签字 | V **不写**手稿块、**不写**台账位：块与位由收方秘书落（178 §一、§三） | `vsigns.land:1097`（`by` 只认 F/E/B 的秘书）；`Secretary.land_unregistered_sign:3312`；位 `verifications.sign_statement:2643` | 86：3/3 份签 `artifact_path=""` ⇒ 手稿块 0 处；位是 `sign_statement` 翻的（000000/000013 = 2 条） | 偏差（"签不在稿上"：正路是未在册那一支，86 没走） |
| | 收录 | V 不参与（只读角色；`write_set=∅`） | `specs/v.py:319-322` | 一致 | 一致 |
| | 优化 | 改稿后旧签读成 stale，不删可查（178 §十 4 推论） | `review_standing` 的 `stale` 分支 | 86：无 stale 读数（没有改稿后重登） | 一致（未验证） |
| **E** | 产出 | 穷举实验落 `experiments` 行 + ②③ 读数 `out/experiments/<号>/exhaustion.md`；本批起另落**被签的证明手稿** `reports/e-proof-<号>.md` | `agent_e/run_experiment.py:450`（`exhaustionreport.land_manuscript:517`）；手稿形状 `compose_manuscript:445` | 86：E 1 条任务（t-000003，parent M）、6 条 `method=numeric`、`exhaustive=True` 0 条、`exhaustion.md` 0 份、`reports/e-proof-*` 0 份 ⇒ 从没产出过数值证明 | 偏差（E 没走到穷举那一档） |
| | 签字 | **与 F 一模一样**：E 派 V → 三轮 → V 颁发 → 收方秘书（`secretary:E`）落块 | 改前：`specs/e.py:270-283` 有 `E→V` 边，但 `vsigns.SECRETARY_OF` 没有 E（`vsigns.py:135` 旧值只有 F/B）⇒ 能颁发、没人落；"签"是 E 自报的 `e_signature`（`numericproof.suspect_self_signed` 报的就是它）。改后：`agent_v/core.py:1677` `_review_unregistered_exhaustion` + `vsigns.SECRETARY_OF` 加 `secretary:E` | 86：V parent=E **0** 条；15 条命题的 `bits.evidence.numeric` 全 False（E 的证据一条都没入册） | **阻断（改前）→ 本批已实现** |
| | 收录 | D 索引四格（`evidence_kind=report` / `evidence_path` / `evidence_sha256` / `v_signature`）→ B 的 `numericproof.filing_problems:1752` 核（三段式 + V 台账行按对象 sha + `exhaustionreport` 落盘） | `numericproof.py:1752-1902`；B 侧 `register_statement.py:1745` | 86：`evidence_kind` 分布 `cross_check 8 / heuristic 7`，`proof 0`；E 的 `numeric` 位 0/15 | 偏差（E 没产出） |
| | 优化 | E 优化 = 新实验 + 新稿 + 重拿签；B 换正文 + `optimized=true` | 本批判据 ④ 造了整条：新实验 → 新 `e-proof-000001.md` → 未在册签 → 在册三转 → B 再交 ⇒ `optimized={'1': True}` + `proof_history` 有旧正文 | 86：无 E 的优化读数（未产出）；`optimized` 缺格 14/15 | 未验证（判据已造） |

---

## 二、把整条链串起来（谁做 / 写哪一处 / 唯一写者 / 缺哪一环）

| 步 | 谁做 | 写哪一处 | 唯一写者 | 缺哪一环 |
|---|---|---|---|---|
| 1 产出证明 | F（或 E） | F：`reports/f-proof-<号>.md`（`agent_f/manuscript.py:204`）<br>E：`out/experiments/<号>/exhaustion.md` + **`reports/e-proof-<号>.md`**（本批，`exhaustionreport.py:517`） | 框架（作者调 action，模型不手写；`reserved_framework_artifact` 拒手写） | **E 的稿此前不存在**（已补）；F 的稿在 86 没产出 |
| 2 派 V | 产出方自己派 | `tasks` 一行（`parent_task_id` = 送审方；`specs/f.py:138` / `specs/e.py:183`） | conductor | 86：22/27 是 B 派 V（作者 F/E）⇒ "谁产出谁送审"不成立，只有读数 |
| 3 V 三轮 | V | `verifications/<号>.jsonl`（在册）或 `verifications/pending/<对象sha>.jsonl`（未在册） | V（append-only；`record_verification` / `record_pending_sign:627`） | 86：0 个 pending 文件 ⇒ 未在册那一支从没走过 |
| 4 颁发 | V | `out/vsigns/<正文sha>.json`（`vsigns.issue:919`，含 `written_by` 与信封 `to`） | 颁发工具（非模型驱动，178 §一.3） | 86：3 份签的 `artifact_path` 全空 |
| 5 落签（手稿块 + 台账位） | **收方秘书** | 块：签文件 `artifact_path` 那份稿的 `- V 签：` 那一行（`vsigns.write_manuscript_sign:825`）；位：`bits.evidence.reviewed_by_proof`（`verifications.sign_statement:2643`） | 秘书（`Secretary.land_unregistered_sign:3312` → `vsigns.land:1097`）；`by` 只认 `SECRETARY_OF`（`vsigns.py:135`，本批含 E） | **E 此前没人能落**（已补）；在册路径下"块"根本没落（`_vsign_payload` 的 `artifact_path` 只在 F 的稿名里找，`verifications.py:2547`） |
| 6 收录 | B（写者是 B 的秘书） | `statements` 一行（含 `bits`）；依赖边 `dependencies` | `Secretary.record_statement`（`secretary.py:1289`） | 兜底读盘不认 `e-proof-*`（`depsection.py:131`）⇒ E 的稿只能靠参数/清单进来 |
| 7 优化 | B | 换正文（旧正文进 `proof_history`）+ `bits.evidence.optimized_by_proof[proof_no]` | B（`register_statement.py:819/859`；`evidencebits.with_optimized_flag:711`） | `reviewed_sha_by_proof` 不随新签刷新（`_bits_after_canonical_write:584`）⇒ `optimized=true` 与"签的 sha"并存两份答案；提示词 0 处提两阶段 |

---

## 三、不一致的提示词句子（原文 + 建议改法）

> 逐条给原文。`specs/*.py` 是 FC-27 禁改区：标「待批」的三条本批**没有动**。

1. **`specs/v.py:201`**（原文）：「只有 `成立` 且 findings 里没有未解决的 error，**你的秘书**才可能发签（第 3 位置真）」
   → 与 178 §三「V 只颁发；手稿块与台账位由**收方**秘书落」不一致（把"V 的秘书"写成发签/落签者）。
   建议：「你的秘书只判『发不发』；手稿块与台账位由**收方**（送审方）那一侧的秘书落」。

2. **`specs/e.py:183`（待批）**（原文）：「立刻派 V 会审（E → V 是直接边，用 `summon` 唤起 V）：把证明栏（程序相对仓库的路径 + 你写的 ②③）与只读读数一起交给它的 `verify_proof`」
   → V 的落块入口只认**手稿**（`proof_manuscript`）；照这句送审只会落到 pending，稿上永远没有签块。
   建议：「…并把**你那份证明手稿** `reports/e-proof-<实验号>.md` 用 `proof_manuscript` 一并交给它；三转成立后签块由收方落回那份稿」。

3. **`specs/e.py:181`（待批）**（原文）：「落点固定是 `out/experiments/<实验号>/exhaustion.md`」
   → 只说了 ②③ 的读数落点，没说"被签的那份正文"另有一份手稿（本批 `reports/e-proof-<号>.md`）。
   建议：同第 2 条补一句（读数一份、手稿一份）。

4. **`specs/e.py:134`（待批）**（原文）：「把证明过程逐字写成正文**交 B**（由 **D** 派 B 登记进 `statements`；你不直接写那张表）」
   → 同一句里"交 B"与"由 D 派 B"并存，与本批"上报 D"不一致。
   建议：「…写成正文后**上报 D**（由 D 派 B 登记）」。

5. **`specs/e.py:270-272`**：`edges=('B', 'D', 'V')` 里有 `B`，而同文件 policy ⑤ 逐字「你既不要写对应表，**也不要自己去找 B 的 `register_statement`**」。
   → 边在、动作不在 E 的动作表里、policy 又禁止 ⇒ `E→B` 没有任何合法用法（86：E 任务 0 次 summon）。
   建议：要么删这条边，要么写清"只在某情形用"。

6. **`agent_skills.py:1803`**（F 手册的 summary，原文）：「proof 由 V 签才算数；自报 proof 会被降级；要复核就派 V（**F 才有到 V 的边**）」
   → E 也有一条（`specs/e.py:282`，2026-10-23 加）。
   建议：「（F / E 有到 V 的直达边；B 只在文献侧用）」。

7. **`specs/b.py:341-344`**（原文）：「**F 产的证明天生带 V 签字**（那是 F 送审时拿到的、盖在**F 那一版正文**上的签）—— 原样入库时认这份签，不要重复要求签」
   → 没写 178 §五之二「B 的第一来源是 D 呈递的研究手稿，按地址寻址」（B 的 policy 全文 0 处「呈递 / 寻址 / 携带」，只有手册有）。
   建议：补一句「第一来源是 D 的清单；清单里的地址读不到 ⇒ 受控拒绝，不许自己猜路径」。

8. **`specs/b.py` 与 `agent_skills.py` 对 179 的两阶段录入 0 处**（grep 读数：`机械录入|两阶段|精准替换|优化` 在 `specs/*.py` + `agent_skills.py` 只命中 M 的决策词表「已优化」，与命题台账无关）。
   → 179 §二 的五条要求（两阶段 / `optimized` 二维布尔 / 精准替换 / 文献侧占位签 / 不许 `proofs=0` 绕行）没有一条进提示词；B 只从工具返回值看到 `optimized`。
   建议：B 的 policy 补一段（一阶段机械录入 `optimized=false`；二阶段只看 `optimized`，重拿签后精准替换写 `true`；文献侧 V 签位 = 文献编号）。

9. **`tests/test_v_signing_belongs_to_b_e_f.py:2`**（原文）：「V 的签字只有两个入口 —— F 产出时签、B 入库文献侧内容时签」
   → E 是第三个入口（178 §九已记这笔文字漂移，一直没改）。
   建议：改成「三个入口：F / E / B」。

10. **`specs/v.py:321`**：`edges=('F',)` —— V 的退回只有 F 一条边；E 的证明被拒时判词只能落 pending，递不到 E（F 那侧有 `V→F`）。
    建议（待批）：加 `V→E` 退回边，或明写"E 的退回经 D"。

11. **`verify_tools.py:1031`（待批）**（工具声明，原文）：「`proof_manuscript`：**F 的证明手稿路径**（工作区相对；命题还没在册时用它…）」
    → 本批起 E 的 `reports/e-proof-*.md` 也走这一格，声明面没跟上（FC-27，本批未动）。
    建议：「F / E 的证明手稿路径（`reports/f-proof-*.md` / `reports/e-proof-*.md`）」。

12. **`agent_skills.py` 的 E 手册（本批已改）**：「反例优先」第 5 步原文「让 `B.register_statement` 把…如实登记」+ 动作清单里的 `B.register_statement` → 与 policy ⑤ 矛盾。已改成「交 D（由 D 派 B 登记）」，动作清单只留 `E.run_experiment`。

---

## 四、工具面缺口（该有却没有 / 有却没人登记 / 声明与实际不符）

工具面读数：107 件工具（`build_registry(...).registry.names()`）。与签/收录相关的只有这些：

| 工具 | side_effect | roles |
|---|---|---|
| `verify.verify_proof` | read | V |
| `verify.read_proof` | read | V |
| `verify.list_verifications` | read | V |
| `verify.run_experiment` | write_local（external=exec） | E / F / G |
| `manuscripts.read` / `manuscripts.list` | read | 十角色 |
| `table.update` | write_local | A/B/D/E/F/G/L（`statements` 被封，撞了白跑） |
| `attack.step` / `attack.status` | write_local / read | F（status 还含 D/G/H） |

1. **该有却没有：落签没有任何工具**。`Secretary.land_unregistered_sign`（`secretary.py:3312`）与
   `vsigns.land`（`vsigns.py:1097`）都是进程内方法，工具面 0 件"签写口"。
   → 与 178 §十 困惑 2 的"方法 ⇒ 0 处（不动 `TOOL_ROLES` / 工具面快照）"一致；这也是
   `tests/test_v_unregistered_manuscript_review.py::test_g` 钉住的结构判据（`agent_v/**` 里 0 处签写口）。

2. **该有却没有：V 的退回边到 E**（`specs/v.py:321` 只有 F）。E 的负判只能落 pending +
   返回值，递不到 E 本人（F 有 `V→F` 的退回）。严重度：偏差（不阻断，靠 pending 读得到）。

3. **该有却没有：D 的结构化索引写口**。索引四格是 `out/paper/MAPPING.json` 的字符串列，
   写者是 G 的 `write_mapping`（`specs/d.py:296` 明写"不要自己写"），D 只"把格凑齐"。
   读侧唯一（`papermapping.index_rows` → `numericproof.INDEX_*`），但写侧没有 schema 校验器
   （写错列名/写成人话只有到 B 的 `index_problems` 才报）。严重度：偏差。

4. **有却没人用：`E → B` 这条边**（`specs/e.py:272`）。E 的动作表里没有 `register_statement`
   （那是 B 的动作），policy 又禁止 E 自己去找 B ⇒ 这条边在 86 里 0 次使用。严重度：仅结构。

5. **声明与实际不符（可接受但要知道）**：`verify.verify_proof` 声明 `side_effect="read"`，
   而它在正判那一转会让收方秘书写出三样东西：`out/vsigns/*.json`、手稿块、台账位。
   178 §一.3 把"签文件由颁发工具自动写"算在 V 侧合规；但"read 的工具体会写盘"在工具声明上不可见。
   严重度：仅措辞（结构已由 `SECRETARY_OF` + `land` 守着）。

6. **快照类**：`tests/golden/tool_surface_snapshot.json` / `agent_surface_snapshot.json` 本批
   **0 处变更**（没有加动作、没有加工具）—— 与"落签走方法、不走工具"这一档一致。

---

## 五、E 的实现（与 F 同形的证据）

### 5.1 改前断在哪（三处，逐条有读数）

| # | F 有 | E 改前 |
|---|---|---|
| 1 | `reports/f-proof-<号>.md` 的 `## 证明` 就是被签的那一份正文 | 只有 `out/experiments/<号>/exhaustion.md`（②③ 读数，没有 `## 证明`）⇒ `agent_v/core.py:1542` 的入口守卫（只认 `reports/f-proof*.md`）把它拒成 `bad_manuscript_path` |
| 2 | 收方秘书落块（`vsigns.SECRETARY_OF`） | 表里只有 F / B（旧 `vsigns.py:127`）⇒ `secretary_id("E")` 空串 ⇒ `land_unregistered_sign` 受控拒绝 `not_a_secretary`（"能颁发、没人能落"） |
| 3 | 签在稿上，B 收录时从稿上读到 | "签"是 `experiments.observations.e_signature.signed_by="V"`（E 在 `build_experiment` 里自己写）+ V 的台账行；没有"签在稿上"这一格 |

### 5.2 改后（同一套，四个落点逐个对齐）

| 环节 | F | E（本批） |
|---|---|---|
| 手稿 | `reports/f-proof-<号>.md`，`agent_f/manuscript.py:204` | `reports/e-proof-<实验号>.md`，`exhaustionreport.compose_manuscript:445` / `land_manuscript:517`（由 `run_experiment` 落，`agent_e/run_experiment.py:450`） |
| 正文口径 | `depsection.proof_body` 的 `## 证明` 节 | 同一节；正文 = `numericproof.compose_proof_column` 三段（B 登记的 `proof_text` **逐字同源**，判据 ① 三处读口对拍） |
| 送审 | `verify_proof(proof_manuscript=…)` | 同一格；`agent_v/core.py:1677` `_review_unregistered_exhaustion`（新） |
| 三轮 | 散文三转（问模型） | 穷举三转（机械七项，`exhaustionreport.review:1037`；2026-10-23 既定口径） |
| 颁发 | `vsigns.issue:919` | 同一个（`_issue_and_land_unregistered:1855`） |
| 落签 | 收方秘书 `land_unregistered_sign` | 同一个；收方 = `secretary:E`（`vsigns.SECRETARY_OF` 加一格，`vsigns.py:135`） |
| 块的内容 | 9 格（`手稿号` = 裸稿号、`正文sha`、`签名者=secretary:F`） | 同 9 格（`签名者=secretary:E`，`手稿号=000000`） |
| B 收录 | `v_sign.applied`（手稿块） | 同一个（判据 ③ 实测 `applied=true`、`why` 里写着「手稿里的签块」） |
| 两阶段 | 一阶段 `optimized=false`、二阶段重签后 `true` | 同一个（判据 ③/④ 实测 `{'1': False}` → `{'1': True}` + `proof_history` 有旧正文） |

另：正判也落一行 pending（按**报告对象**的字节 sha，`record_pending_sign:627`）—— B 的入库闸认 E
这一路的第三方签字读的就是它（`numericproof.filing_problems:1752`）；F 那一侧 B 读手稿块，
E 这一侧两条都要在（少前者，稿上没有签；少后者，B 过不了 `proof` 档的闸）。

### 5.3 判据（`tests/test_e_gets_its_v_sign_like_f.py`，7 条，零模型调用）

| # | 造什么 | 期望 |
|---|---|---|
| ① | E 跑一条真穷举实验 | 落 `reports/e-proof-000000.md`；`## 证明` 的正文三处读口同一把尺（`depsection` / `vsigns` / `exhaustionreport`）、`proof_sha256` 相等、三段可解析、三节齐 |
| ② | E 派 V（未在册） | 三轮 `pass=1/2/3` 全「成立」；块 `signed/3/3/signer=secretary:E`；签文件 `written_by` 与信封 `to` 都是 `secretary:E`；pending 行的 `object_sha256` = 报告真 sha |
| ③ | B 收录 | `v_sign.applied=True`（why 含「手稿」）；`bits.reviewed=True`；`optimized_by_proof={"1": False}`；`reviewed_sha_by_proof={"1": 正文sha}` |
| ④ | 第二阶段 | 换策略重跑 → 新 `e-proof-000001.md` → 未在册签 → 在册三转（`signed_bit3=True`）→ B 再交 ⇒ `optimized={"1": True}`、canonical = 新版、`proof_history` 有旧正文 |
| ⑤ | 反真空（边） | 摘掉 `E→V` ⇒ `forbidden_edge`（正控：`E→V` 在 `C.ALLOWED_EDGES` 里且 `check_edge` 放行） |
| ⑥ | 反真空（落签） | 把 `secretary:E` 从 `SECRETARY_OF` 摘掉 ⇒ 稿上没块、`v_sign` 走不到手稿那一支（签仍颁发、pending 行仍在） |
| ⑦ | 反真空（载体） | 只给证明栏、不点名手稿 ⇒ 退回 pending、块不出现；同一份稿点名之后再送 ⇒ 才落块 |

定向复跑（本批）：
```
python -B -m pytest tests/test_e_gets_its_v_sign_like_f.py \
  tests/test_v_unregistered_manuscript_review.py tests/test_agent_v_exhaustion_review.py \
  tests/test_b_reads_the_manuscript_sign.py tests/test_missing_material_never_lands_a_pending_sign.py \
  tests/test_secretary_prompt_alignment.py tests/test_agent_skills.py \
  tests/test_agent_prompts.py tests/test_prompt_stability.py -q
→ 158 passed, 1 warning
```

### 5.4 已知未闭环（如实写）

- **`specs/e.py` 与 `verify_tools.py` 的措辞**（FC-27，禁改区）：E 的 policy 仍只说"把证明栏交给 V"，
  不说 `proof_manuscript`；工具声明的 `proof_manuscript` 仍写"F 的手稿"。所以 E 要拿到手稿签块，
  必须**在送审时点名那份稿**（`run_experiment` 的返回值 `proof_manuscript` 就是这一格）——
  本批判据 ⑦ 把"不点名 ⇒ 没有块"钉住了。**这两句需要人批**。
- **D 的携带单按命题号寻址**（`depsection.carried_manuscripts` 的 `命题号 → 路径 → sha`）：
  E 的稿在**在册之前**没有命题号 ⇒ D 无法用它带 E 的未在册稿。今天能走的是
  "E→D 交正文（地址）→ D 索引四格指报告 → B 按参数/清单拿到稿正文"。
  「B 按 D 的清单寻址拿到 E 的**手稿**」这一半只在"稿正文被递进来"这一档成立。
- **`reviewed_sha_by_proof` 不随新签刷新**（B 侧 `_bits_after_canonical_write:584` 刻意保留旧值）：
  000000 在 86 里就是 `optimized=true` 而 `reviewed_sha_by_proof` 指旧正文。读侧两套答案。

---

## 六、86 真机读数（四步各发生了什么）

| 方 | 产出 | 签字 | 收录 | 优化 |
|---|---|---|---|---|
| **B** | 79 条任务（161 条里最多）；自写 7 份正文 `out/B-proofs/*.md` | 派 V 22 次（V 的 parent=B）；2 份签 `written_by=secretary:B` | 登 15 条命题：`cross_check 8 / heuristic 7`，`proof 0`；`proof_authors=['F']` 8 条 | `optimized`：缺格 14 条、`{'1':true}` 1 条（000000） |
| **D** | 14 条任务；研究手稿在（`reports/000000-research.md`，含 `## 携带的证明手稿`） | 派 V **0** 次 | 携带单 **0 行**、给 B 的回执"收下 0 条" | 无写口 |
| **F** | 12 条任务；**0 份** `reports/f-proof-<号>.md`（只有 2 份 `f-proof-plan-*.md`） | 派 V 4 次；3 份签 `artifact_path=""` | 无稿可被收录 | 无改稿重签 |
| **V** | 27 条任务；9 个 `verifications/*.jsonl`；3 份签文件；**0** 个 pending 文件 | 手稿块 **0** 处（3/3 签 `artifact_path` 空）；台账位翻 2 条（000000、000013） | 不参与 | 无 stale 读数 |
| **E** | 1 条任务（t-000003，parent M）；6 条 `numeric` 实验；`exhaustive=True` **0** 条；`exhaustion.md` **0** 份；`reports/e-proof-*` **0** 份 | 派 V **0** 次（V parent=E 0 条）；`bits.evidence.numeric` 0/15 | 0 条 E 证据入册（`evidence_kind` 无 `proof`） | 无（未产出） |

补充读数：

- V 的 parent 分布：`B 22 / F 4`（另有 1 条 `t-000149` 的 parent 是 V 任务 `t-000126`，`called_by=B`，
  status=pending，父被掐断 ⇒ 没跑）。⇒ 178 §九的"已知反例生成器（M→B→V）"在 86 里有 22 条现场，
  且 `t-000149` 说明"parent 与 caller 不是同一个人"这件事在数据里真的存在
  （`current_parent()` 读 parent_role 会读到 V ⇒ 收方空串 ⇒ 签颁发了没人落）。
- `manuscripts/` 只有 `handoffs.jsonl`（无证明手稿）；`verifications/pending/` 不存在。
- `reports/f-proof-plan-000000.md` / `000001.md` 是**计划**稿（F 的计划），不是证明手稿。

---

## 七、本批动过的东西（hash / lint / 判据）

| 内容 | hash |
|---|---|
| 实现（E 的 V 签与 F 同形）+ 判据 `tests/test_e_gets_its_v_sign_like_f.py` | `b5e0b1c6bee1fe0355bd3109b2713a9d77247774` |
| 修（E 手册的动作清单：只列 E 自己的动作） | `3bfd1ae4148fae34a06235b599514ab38e676368` |

改动文件（8 改 1 新）：

```
src/agentflow/exhaustionreport.py   +283   E 的证明手稿（compose/land/read/proof_manuscript_relpath/experiment_id_of）
src/agentflow/agent_v/core.py       +188   _review_unregistered_exhaustion（三转 + 颁发 + 收方落块）
src/agentflow/agent_e/run_experiment.py +32 穷举那一档同时落手稿，返回值多四格
src/agentflow/vsigns.py             +32   SECRETARY_OF 加 secretary:E（收方仍只有送审那一方）
src/agentflow/agent_skills.py       +67   E 手册新增「穷举证明-拿签与上报收养」；修「反例优先」两处矛盾
src/agentflow/agent_prompts.py       2    PROMPT_VERSION p233 → p234
tests/test_agent_prompts.py          4    冻结摘要 E 那一格 + 冻结版本
tests/test_prompt_stability.py      10    facts 账本末尾追加 p234 一格
tests/test_e_gets_its_v_sign_like_f.py  +310（新）
```

`python -B scripts/lint_rules.py`（原样末行）：

```
[linter] 扫描 {'src_py': 265, 'tests_py': 871}；规则 12 条；模式 日常
[linter] error 0 / warning 21 / info 49
```

**未跑全量**（业主统一跑）。定向复跑见 §5.3。
