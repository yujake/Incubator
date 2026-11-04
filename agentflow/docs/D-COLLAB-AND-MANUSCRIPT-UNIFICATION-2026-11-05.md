# D 侧协作 + F/B 落稿统一（2026-11-04 夜 → 2026-11-05 晨，p241）

> **给明天接手的人：先读这一份，再读 `docs/INDEX.md`。**
>
> 这一轮只做一件事：把「D 只出想法、证明由 F 落稿拿签」从业主裁定变成**机器拦得住的形态**，
> 并把 F 的证明手稿与 B 的改写手稿收成**一份实现**。本文只写盘上与 git 史里查得到的句子；
> 每个读数都带出处，复跑命令见 §7。
>
> 本文的"当次读数"观测于 **2026-11-05 03:0x +0800**，工作区为 `D:\Incubator\agentflow`，
> git 根在上一级 `D:\Incubator`（所以提交里的路径形如 `agentflow/docs/...`）。

---

## 1. 业主的三条裁定（逐字）

```text
①「F 落证明手稿和 B 优化证明落稿形式上应该完全统一」
②「D 侧提示词里明确 D 可提供证明思路，甚至提供依赖面参考，最终的证明落稿拿签必须派给 F 完成，
   D 只是提供想法并收获数值实验和理论攻坚的成果，然后再提出新的想法」
③「D 侧落的研究手稿就是既有指定形式的那种（收录 F、E 侧成果以及其他一些东西，具体看已有口径）」
```

出处与盘上转述：

- ① 的盘上转述在 `src/agentflow/manuscriptform.py:6-7`（"在形式上必须完全统一"）与
  `tests/test_f_and_b_manuscripts_are_one_implementation.py:6-7`；措辞与上面这句有差（"应该"→"必须"），
  按业主口述记。
- ② 逐字进了 `035b7365` 的 commit message，也逐字进了 D 的 policy
  （`src/agentflow/specs/d.py:253-255`）。
- ③ 逐字进了 `035b7365` 的 commit message；落成的地方是 `src/agentflow/specs/d.py:275-285`
  （`reports/RESEARCH.md` 七节、先读后改、收录者/引用者）。

---

## 2. 落成什么

### 2.1 唯一实现：`src/agentflow/manuscriptform.py`（F/B 两族共用）

一个顶层模块、743 行，六个入口各只有一处定义：

| 入口 | 行 | 管什么 |
|---|---|---|
| `name_reading` | `manuscriptform.py:151` | 拼候选名 / 读号读页，内部只走 `vsigns.parse_manuscript_name` |
| `render_proof_manuscript` | `:216` | 三节（命题 / 证明 / 依赖）+ 洗稿行 + 命题号行；前缀与角色名只是参数 |
| `validate_manuscript` | `:319` | 形状 / 洗稿 / 依赖段；四个拒信码与 detail 模板一份 |
| `carry_sign_block` | `:377` | 改名时搬签块；sha 相符才搬，第 9 格按新名重算 |
| `commit_manuscript` | `:520` | 写稿 + `## 依赖` 段 + 落 `dependencies` 边**同一事务**；落边失败回滚 |
| `promote_formal` | `:672` | 两族的"转正"改名走同一段 |

转发壳（旧模块只许转发）：

- `src/agentflow/agent_f/manuscript.py:55-59` 把 `carry_sign_block` / `ensure_statement_line` /
  `formal_shape_problem` 改成 import 转发，`promote_manuscript`（`:439`）转发到 `promote_formal`；
- `src/agentflow/bmanuscript.py:63` `relpath` / `:99` `render` / `:120` `land_rewrite` /
  `:193` `promote_formal` 做转发与适配；`bmanuscript.py` 全文 230 行，`re.compile` 为 0；
- `src/agentflow/depsection.py:439-452` 的 `manuscript_relpath` 也转发到 `name_reading`
  （命名规则不许有第二个落点）。

判据：`tests/test_f_and_b_manuscripts_are_one_implementation.py`

- a（`:149`）同一正文 + 同一号，两族除前缀与角色名外逐字相同；
- a2（`:187`）反真空：把 B 的渲染改回旧实现 ⇒ a 立刻红；
- b（`:215`）`f-/b-proof-000000-p2.md` 都解析成 `(000000, 2)`，乱名两族都受控拒；
- c（`:254`）带签块的稿改名，签块跟着搬；
- d（`:321`）写稿 + 依赖段 + 落边是一次事务，打桩落边失败两边都不留半截；
- e（`:465`）AST 扫描钉住"第二份实现不能复活"：三个符号各只许 `manuscriptform.py` 一处定义，
  `parse_manuscript_name` 只许 `vsigns.py`，两个旧模块里不许再有 `re.compile`；
- f（`:393`）五个拒信码与 detail 模板两族共用。

改前/改后读数（`196b2b62` 的 message）：先落判据 **7 failed**，统一实现后同一份文件 **7 passed**。

### 2.2 D 的协作面

三句可执行的话进了 `src/agentflow/specs/d.py:252-264`：

1. **想法由你给**：哪些引理要引、按什么顺序、用哪条已证命题（`stmt:` 号），写进派活或
   `F.create_plan` 的 `problem` / `subgoals`；
2. **证明的落稿与拿签不属于 D**：`reports/f-proof-<号>.md` 由 F 落、签由 F 带 V 拿；
   D 自己写"可提交的证明稿"会被 `fs.write` / `fs.edit` 受控拒绝（`reserved_framework_artifact`）；
3. **D 的产物 = 想法 + 收获 + 下一个想法**，即"读回 F 的结果 → 立新猜想 → 再派 F"。

手册里的同一件事：`src/agentflow/agent_skills.py:2745-2762`「三步循环：想法 → 派 F → 读回 → 新想法」。

fs 层三档拒（唯一收口在 `src/agentflow/tools/fs_tools.py`）：

| 档 | 何时拒 | 拒信常量 | 落点 |
|---|---|---|---|
| 路径 | D 写 F 的证明稿名（`f-proof-*` / `*-proof.md`，任何目录） | `D_PROOF_LANDING_MESSAGE`（`:396`） | `D_PROOF_PATH_RULES`（`:314`）命中后由 `_reserved_refusal` 分支拒（`:646-648`） |
| `out/proofs/` | 正文里有 `## 证明` 节 | `D_ATTACK_RECORD_MESSAGE`（`:404`） | `_d_proof_body_refusal`（`:597`）→ `:613` |
| `reports/RESEARCH.md` | 有 `## 证明` 节、且**没**引用/转载 F 的稿 | `D_RESEARCH_PROOF_MESSAGE`（`:412`） | `_d_proof_body_refusal`（`:597`）→ `:616` |

**只收一处**：`_reserved_refusal`（`:621`）是四个写口（`fs.write` / `fs.edit` / `fs.delete` /
`fs.move`）共用的唯一结论点；`specs/d.py` 的 `write_set` 一个字没动 —— `write_set` 是表级权限
（`research_questions` / `search_requests`），它管不了"路径 + 内容"。

判据：`tests/test_d_does_not_land_the_proof.py`

| 判据 | 行 | 钉什么 |
|---|---|---|
| a | `:115` | `RESEARCH.md` 可以写；自写 `## 证明` 节拒，且盘上逐字未动 |
| a2 | `:151` | D 写 F 的证明稿名字 ⇒ 拒、指路"要落稿就派 F" |
| b | `:167` | `out/proofs/*.md` 带 `## 证明` ⇒ 拒；`fs.edit` 同一闸 |
| c | `:195` | 只写 `## 思路` / `## 依赖面参考` ⇒ 允许（正控，不许被误伤） |
| d | `:234` | 交 B 时缺 F 的证明稿 ⇒ 既有携带单口径报「缺携带单」 |
| e | `:263` | 反真空：把 a/b 的闸打桩成放行 ⇒ 同一批写入必须成功 |

改前红 4（a / a2 / b / e）、改后绿 6（`035b7365`）。

### 2.3 研究手稿按既有形式

- `reports/RESEARCH.md` **七节（0–6）**：`projects/paper-rewrite-87/reports/RESEARCH.md:5,15,25,32,40,46,53`；
- **它是收录者/引用者**：第 3 行逐字写着
  "**本文件不写任何自撰的证明正文**：证明正文只在 F 的稿 `reports/f-proof-<号>.md` 里，
  本文件只做收录与引用。"；
- 引用 F 的稿：`:7` 与 `:27` 点名 `reports/f-proof-000003.md`（并带稿内证明段 sha256
  `bdac0620…390b15`）；
- 全文 `## 证明` 节 **0 处**（`Select-String '^##\s*证明'` 命中 0）；
- D 交 B 时的携带单不动：`src/agentflow/agent_d/write_report.py:646` / `:720` 的
  `carried_by_D` 这条读数仍在；本轮对该文件 **0 次提交**（`git log --since="2026-11-04 17:00"
  -- src/agentflow/agent_d/write_report.py` 为空）。

---

## 3. 真机证据：81 vs 87（本文的核心）

两趟都是 `paper-rewrite` 系列；81 是**改前**（业主叫停："看形态（D 自写证明、F 空转）已够"），
87 是**改后**（业主停机理由："三样已判"）。

```text
                         81（改前）                       87（改后）
F 任务                    0                               29
V 任务                    0                               12
f-proof 稿                0                               3（000000 已签；000002/000003 未签）
dependencies              0                               3
RESEARCH.md               无                              8,255 B，七节齐（0–6），
                                                          点名引用 reports/f-proof-000003.md，
                                                          自写 `## 证明` 节 0 处
out/proofs                3 份（D 自写，89,983 B）         不存在
签块                      无                              `签名者=secretary:F；手稿号=000000；
                                                          判词=成立；连续=3/3；
                                                          台账=verifications/000000.jsonl#v-000008`
花费                      $0.399831                        $0.472063
墙钟                      67 分 47 秒                      44 分 30 秒
```

**逐项出处（都在 `projects/paper-rewrite-{81,87}/`）：**

| 读数 | 怎么读出来的 |
|---|---|
| F / V / D / B 任务数 | `data/tasks.json` 的 `rows[*].role` 计数：81 = M17/E8/D20/A3（F 0、V 0、B 0）；87 = M8/A7/D26/E6/**F29**/B1/**V12** |
| statements | `data/statements.json`：两趟都是 4 行，`evidence_kind` 全 `heuristic`，`reviewed` 字段没有，`bits.reviewed=false`，`proof_text` 长度 0 |
| dependencies | `data/dependencies.json`：81 是 `[]`；87 是 3 行 |
| f-proof | `reports/f-proof-*.md`：81 无；87 三份 000000 / 000002 / 000003，共 10,846 B（4,950 + 3,065 + 2,831） |
| RESEARCH.md | 87 的 `reports/RESEARCH.md`，8,255 B；`^## ` 标题 7 个（0–6） |
| out/proofs | 81 三份 `B-classical-zerofree.md` 17,908 B + `C-part1.md` 37,457 B + `D-part2.md` 34,618 B = **89,983 B**；87 目录不存在 |
| 花费 | `data/usage_ledger.json` 的 `usd` 求和：$0.399831 / $0.472063（四舍五入 $0.3998 / $0.4721） |
| 墙钟 | `runs/agent-M-*.json` 的 `started_at` → `end_ts`：81 22:09:47→23:17:34 = 67分47秒；87 02:12:48→02:57:18 = 44分30秒 |

### 3.1 签块原文与一处必须知道的偏差

`projects/paper-rewrite-87/reports/f-proof-000000.md:5` 逐字：

```text
- V 签：已签=true；判词=成立；连续=3/3；正文sha=43a2b34764a618993f29680c899baca3fd9bd256dd9f06502a821bcf95be685e；
  时间=2026-11-05T02:50:58+08:00；签名者=secretary:F；台账=verifications/000000.jsonl#v-000008；
  命题号=000000；手稿号=000000
```

**偏差（下一趟读签必须知道）**：同一份稿、同一个 sha 之后还有三笔 ——
`v-000009`（02:53:31，**有毛病**，第 6 步）、`v-000010`（02:54:06，成立）、
`v-000011`（02:56:35，成立）。签块仍然指向 `v-000008`，没有回头改台账号。
所以："签是真的（sha 对得上），但签块里的台账号不是最新那一笔"。
若下一趟要拿它当"最后一次判定"，先读 `verifications/000000.jsonl` 的尾三行。

### 3.2 三个数字与施工单不一致（以盘上为准，已复核）

1. **87 墙钟**：施工单写 47 分钟，`runs/agent-M-20261105.json` 的 `started_at` / `end_ts`
   是 **44 分 30 秒**（02:12:48 → 02:57:18）。取 44 分 30 秒。
2. **81 的 out/proofs 体量**：施工单写 72 KB，盘上三份合计 **89,983 B**（≈87.9 KiB）。
   "72" 最接近的是 C-part1 + D-part2 两份之和（72,075 B），不是三份之和。
3. **87 的 dependencies 3 行，不是 F 手稿依赖表进来的**：三行逐字是
   `dep_id=000000/000001/000002`、`used_by=stmt:000001`、`label=lit:000001..000003`、
   `source_lit_id=000001..000003`、`created_by=secretary-B`、`created_at=2026-11-05T02:37:17`；
   而三份 `f-proof-*.md` 的 `## 依赖` 表**都是空表**（"这一份证明没有引用任何在册命题 —— 空表就是声明"）。
   这三行是 B 登记 `stmt:000001`（`external_lit` 概念行，成员 lit:000001–000003）时落的
   文献依赖，不是"B 读 F 手稿的四列表"那一支。**"0 → 3"这个读数成立，但归因要改。**
   真正的"F 手稿依赖表 → B 读稿落边"这一支，两趟都还没有真机读数。

### 3.3 教法生效的直接证据（D 自己写的）

`projects/paper-rewrite-87/reports/RESEARCH.md:3`：

```text
> 本文件是下一趟接手的人先读的那一份。七节次序固定。**本文件不写任何自撰的证明正文**：
> 证明正文只在 F 的稿 `reports/f-proof-<号>.md` 里，本文件只做收录与引用。
```

同一趟 `notes/D.md`（02:28:05）写的是"更新 `reports/RESEARCH.md`（先 `fs.read` 再 `fs.edit`，
只收录 F 的证明稿与 E 的实验行，不自写 `## 证明` 节）" —— 教法与落稿一致。
对照 81 的 `notes/D.md`（23:08:53）："本轮未派子代理（本方向是自证写作，深度 2、墙钟剩量不足以再开
攻坚链；未派是判断不是遗漏）" —— 同一句话在改前是"自证写作"的自我授权。

---

## 4. 这一轮查出并修掉的七类缺陷

### 4.1 F/B 两套实现（渲染/命名/搬签/事务/拒信码各一份）

- **症状**：两族的页头一开始就不一样；两套命名、两套渲染、两套搬签、两套落盘、两套拒信；
  没有任何一条判据会因此变红（`910b3031` 的 message）。
- **根因**：F 与 B 各自演化出一份"看起来对"的实现，重复代码没有唯一落点。
- **修法**：新增 `manuscriptform.py` 一份（§2.1），旧模块只留转发。
- **判据**：`tests/test_f_and_b_manuscripts_are_one_implementation.py` a–f；
  e（`:465`）是 AST 防复活。改前 7 failed ⇒ 改后 7 passed（`196b2b62` / `910b3031`）。

### 4.2 D 自写证明（81 里 3 份、89,983 B）

- **症状**：81 全程没派 F，D 自己在 `out/proofs/` 落了 3 份证明，`F`/`V`/`B` 任务数 0、
  `statements` 0、`dependencies` 0；D 自述"自证写作"。
- **根因**：`reports/RESEARCH.md` 当时被整份当"保留面"拒掉，`out/proofs/` 却是敞开的 ⇒
  D 唯一写得进去的"证明稿落点"就是 `out/proofs/`；而没有任何内容闸判"这一节是不是证明正文"。
- **修法**：fs 层三档拒（§2.2），唯一收口 `_reserved_refusal`；`write_set` 不动。
- **判据**：`tests/test_d_does_not_land_the_proof.py` a / a2 / b / c / d / e；
  改前红 4、改后绿 6（`035b7365`）。

### 4.3 研究手稿旧口径写反（"`RESEARCH.md` 是保留面、别手写"）

- **症状**：D 的 policy 教"项目级 `reports/RESEARCH.md` 是框架保留面……别去手写它"，
  `tests/test_the_unsigned_loop_is_taught.py::u5` 也按这个口径断言。
- **根因**：2026-11-01 的审计 D-08 结论是"RESEARCH.md 没有渲染器"⇒ 整份拒；
  2026-11-04 的补充裁定③把落点翻回"既有指定形式"，旧口径没跟着翻。
- **修法**：`035b7365` 把 policy 那一段从"两处落点 + 保留面"改成"三处落点（`RESEARCH.md` 七节
  先读后改 / `research.write_note` / `write_report`）+ 禁区是自己新写的 `## 证明` 节"
  （`specs/d.py:275-285`）；fs 侧只在"没引用 F 的稿"时拒（`fs_tools.py:597-618`）。
- **判据**：`tests/test_the_unsigned_loop_is_taught.py:137`（u5：必须教"七节 / 先读后改"、
  `research.write_note`、"`## 证明`"；不许再出现"RESEARCH.md 是框架保留面"/"别去手写它"）；
  正控是 `test_d_does_not_land_the_proof.py:195`（c：只写 `## 思路` / `## 依赖面参考` 放行）。
  旧期望 `test_fs_reserved_framework_artifacts.py` b / n-b 同批翻转（见 `035b7365` message）。

### 4.4 生成器与产物不同源（`out/proofs` 那行、F/V 两行也错位）

- **症状**：`tools/write_system_docs.py` 的 `out/proofs` 那格仍写"写 | 证明正文（manuscripts
  那套读的正是它）"，而 F 的证明正文行、V 的被审正文行也还指着 `out/proofs` ⇒
  `docs/ROLE-GUIDE.md` 与新闸冲突；只改产物会在下次重生成时被覆盖。
- **根因**：产品文档是生成物，生成器（`ARTIFACTS`）才是真身；"闸拒谁"与"文档写谁"没有对表。
- **修法**：`4cca5c27` 三处改对：D 新增 `out/proofs/*.md` 一行（写；`## 思路` /
  `## 依赖面参考`；带 `## 证明` ⇒ 受控拒），F 的证明正文落点改成 `reports/f-proof-*.md`（`:78`），
  V 的被审正文改成 `reports/f-proof-*.md`（以及 `e-proof-*.md` / `b-proof-*.md`，`:95`）；
  重生成两份文档，`--check` 两份都一致。
- **判据**：`tests/test_system_docs_are_generated.py:230`（正控：生成器与产物同口径）+
  `:243`（反真空两个方向：生成器改回旧措辞 ⇒ 红；**只改产物**（生成器新、产物旧）⇒ 也红）。

### 4.5 warm 滚存挤掉诊断档（`--probe-no-tools` / 跨 run H、M）

- **症状**：读数文件只留最近 `MAX_RUNS_KEPT` 趟；p241 两趟预热把唯一带 `--probe-no-tools`
  的 p234 那趟挤出窗口 ⇒ `test_the_two_diagnostic_readings_say_what_they_measured` 红。
- **根因**：诊断是"每趟可选开关"，于是滚存窗口决定了"诊断还在不在"；补跑两趟只是花钱掩盖，
  调大窗口只是推迟复发。
- **修法**：`2ee7dfaa` 把 `--probe-no-tools` / `--probe-cross-run` 变成每一趟的固定组成
  （缺省目标 V 去工具面、H 换一趟活；run 记录新增 `diagnostics`）；`a286324a` 把跨 run 伙伴
  固定成 H 与 M 两个；`MAX_RUNS_KEPT` 不动。代价：每趟多 3 次调用。
- **判据**：`tests/test_cross_run_prefix_is_reused.py:21` 与 `:533`（"最近一趟的 `cross_run_hit`
  是 4 行，不是 4 行就红"）；`tests/test_prompt_cache_warm.py:1386` 同样断言 4。
  实测：`tests/fixtures/prompt_cache_warm.json` 最后一趟（2026-11-05T00:24:34+08:00）
  `cross_run_hit` = **4 行**（H×2 + M×2，`cross_run_probes=["H","M"]`）；此前各趟 2 行（只有 H）。
  反真空：`6a1897a2`（摘掉固定诊断 ⇒ 同一刀红）、`bd4d14c9`（关档夹具收尾后仍读到五条开档锚点）。

### 4.6 Lean 状态跨测试泄漏（三种写法，含包装实参绑定）

- **症状**：`test_g_...` **单独跑绿、成套跑红** —— G 的渲染缺五条只在开档才出现的锚点
  （`numeric（数值证明` / `formal（形式化）` / `` `lean_target` 必填 `` / `无依据的声称` /
  `自称有数值证据`）。
- **根因**：三种关档写法（① `delenv` / `setenv` 假值；② 本地包装的实参绑定
  `_lean_env(monkeypatch, False)` / `_set(False)`；③ 直接 `os.environ[SWITCH] = 假值`）都可能
  "关档 + 渲染过提示词 + 收尾不收回"；而 `monkeypatch` 的 undo 在夹具之后才跑，
  只 `importlib.reload(settings)` 清不掉 `agent_prompts` 的 `lru_cache`。
- **修法**：唯一助手 `tests/conftest.py:185` `restore_lean_baseline`（显式 `setenv("1")`、
  摘掉临时 `AGENTFLOW_SETTINGS`、依次重载 `settings` / `agent_prompts` / `verifications`）；
  三处旧收尾改调它（`920de6e1`），10 处调用点（`682339c4`），3 条直接写 `os.environ` 的
  （`d432d1ea`）；判据扫描面扩到三档（`e58ce133` / `68f7a5b1`）。
- **判据**：`tests/test_lean_state_does_not_leak_between_tests.py` —— a（`:155`）、
  b（`:184`，反真空：摘掉 `setenv("1")` 同一读法当场红）、c（`:454` / `:476` / `:521`，
  扫全 `tests/` 三档写法；收尾只认"调助手"或"豁免表里且能自证收干净"）。
  读数：修前同进程 1 failed / 10 passed，修后 11 passed（`920de6e1` / `682339c4`）；
  最终普查 **20 个候选**（setenv 字面量 11 / 经本地包装 6 / `os.environ` 字面量 2 / delenv 1），
  13 个调助手、6 个在豁免面、**0 个漏**（`68f7a5b1`）。

### 4.7 台账/读数过期（五处）

| # | 过期形态 | 真身 | 修法 / 判据 |
|---|---|---|---|
| 1 | `fs_tools._reserved_artifact` 是只返回 bool 的壳，非测试调用点 **0** | 唯一调用点是 `_reserved_refusal` 里的 `_reserved_artifact_rule`（四个写口共用） | `f7e22261` 删壳；`WIRED` 台账改跟 `_reserved_artifact_rule`；`test_wiring_edges` ①② 绿 |
| 2 | `bmanuscript._dependency_section` 零提及 | 唯一实现在 `depsection.render_dependency_section`；`land_rewrite` 走 `_dependency_rows` + 已算好的字符串 | `8e0abada` 删掉；`test_clean_invariant::test_no_dead_private_function_without_a_ledger_entry` |
| 3 | refusals 处数：`agent_f/manuscript.py` 记 2，实测 **live=1 / want=2** | `preview_dependencies` 的 `out` 初值还在该文件；`proof_manuscript` 的写盘失败已搬进 `commit_manuscript` | `1835e928` 把 `_REPEAT_COUNTS` 2→1 并写清理由；`test_refusals` 6 passed |
| 4 | r5 注释引用：7 处私有符号名全仓不存在（另 4 处随 ① 删壳消失） | `_rel_is_inside` / `_retitle_applied` 是历史叙述；`_carry_sign_block` 是 `_Manuscript` 里的零调用转发 | `f7fc5b21`：两条历史名字登记进 `_REF_KNOWN_MENTION_TOKENS`；`_carry_sign_block` 删掉、docstring 改指真身；`test_r5_orchestration_cost` 35 passed |
| 5 | `READING-MAP` 头部行数漂了（248,079 → 248,042） | 今晚 p241 删死代码/重复实现后 `src/` 实际 268 个 `.py` / 248,042 行 / 74 个 >800 行 | `134e1257` 按现算重抓（观测日 2026-11-05）；`test_reading_map_counts` 2 passed。另 `b9e8ecf4` 把 `manuscriptform.py` 登记进 READING-MAP |

---

## 5. 四条"施工单会写错、实现是对的"的教训

### ① 位置按"闸实际拒谁"，不按施工单写的行号

施工单让改 `tools/write_system_docs.py:72`，但那一行在 `ARTIFACTS["F"]` 里（角色 F 的读写表），
不是 D 的。照字面把"带 `## 证明` ⇒ 受控拒 / 要落稿就派 F"写给 F 会变成三处假话：
闸只拒 D 的 `out/proofs/*.md`（F 写它并不受控拒）；对 F 说"要落稿就派 F"等于让它派自己；
F 的证明正文早就不在 `out/proofs/`。所以 `4cca5c27` 按语义落位到 D 新增一行、F 与 V 各自改到
`reports/f-proof-*.md`。**先问"这道闸实际拒谁"，再决定文档写给谁。**

### ② "台账过期"有两种：名字搬了 / 只剩一部分还在

`_reserved_artifact` 是**真死**（0 调用，删）；而 `agent_f/manuscript.py` 的 refusals 是
**只剩一部分**：`proof_manuscript` 那半搬走了，`preview_dependencies` 的 `out` 初值还在 ——
"按原话删行会让 want=0 / live=1 翻成 missing 1，判据仍然红"。**先量 `want` 与 `live`，
再决定删行还是改数**（`1835e928` 原话）。

### ③ 扫描面里不能有历史副本

p241 期间 `temp/` 下积了 **17 份整树副本**（`unify_green` / `unify_red` / `head_*` / `lint_*` /
`before_u09_pkg` / `red_before` / `reviewed_red` / `pkg159_swap` / `161_before_tree` / `_idx` /
`_p238_repo` / `_redcheck_20261102` …），把旧符号带进 r5 的注释引用扫描面。
`f7fc5b21` 把它们全部移出交付树到 `D:\Incubator\temp\`（`_idx` 重名，改存
`_idx_p241_snapshot`），结论是"temp 是易失工作区，副本不进交付物……扫描面里不再有'古物'"。
**扫描面要么钉死在 `tests/`（`test_lean_state_does_not_leak_between_tests.py:54-55`），
要么先清历史副本；两者混着来，判据会替旧代码作证。**

### ④ 夹具不许比真机宽松

`sign_before_registration` 曾经的形态是"只写 pending 台账的 `object_path`，不落盘也能签" ——
真机上不可能发生（签要盖在手稿上）。现在正常夹具必须真写一份
`reports/f-proof-999999.md`（`tests/conftest.py:369-406`），"不落盘也能签"只许以
`sign_before_registration_legacy`（`:409`）存在；判据
`tests/test_fixture_sign_carrier_is_a_real_manuscript.py` a（盘上真有稿）/ b（legacy 名字必须带
`legacy` 且一个文件都不落）/ c（pending 行指向那份真文件）。`1e40224b` 是这一笔的入口。
**夹具比真机宽松一次，后面所有"这条链是通的"读数都要打折。**

---

## 6. 仍然缺的（如实）

87 那趟 44 分 30 秒里 **B 只出场 1 次**（`tasks.json` 里 B 只有 `t-000027`，02:34:46–02:38:28，
`called_by=A`、`depth=4`、`outcome=ok`、$0.035545），而 `statements` 4 条**都没有正文、没有
`reviewed`**：

```text
stmt  status  evidence_kind  reviewed  bits.reviewed  proof_text  len
000000 active  heuristic     （无）    false           ""          0
000001 active  heuristic     （无）    false           ""          0
000002 active  heuristic     （无）    false           ""          0
000003 active  heuristic     （无）    false           ""          0
```

所以现状是：**签了（`v-000008`）但还没走到"B 收录 → `ek=proof_review` → 档位回抬"**。
`stmt:000000` 在 02:35:56 就由 `secretary-B` 建行，签在 02:50:58 才落；签之后没有第二趟 B
读稿，`bits.reviewed` 因此还是 `false`。

**原因不是链断了，是按目标停机**：业主在 02:56:47 写 `.agentflow-stop`，理由逐字是
"三样已判：签块落 f-proof 稿（secretary:F/手稿号=000000）、dependencies 3 行、RESEARCH.md
七节且引用 F 的稿、D 无 out/proofs"（`runs/stop-history.jsonl`）。下一趟要补的是**第二趟 B
回读**这一格，不是重跑整条链。

另外两处要如实记账：

- §3.2 第 3 条：`dependencies` 那 3 行是 `lit:` 档（`stmt:000001` 的概念成员），不是 F 手稿
  依赖表；"F 手稿四列表 → B 读稿落边"这一支仍无真机读数（判据 d 只有 tmp 工作区的证据）。
- 签块的台账号停在 `v-000008`，之后同 sha 还有 `v-000009`（有毛病）/ `v-000010` / `v-000011`
  （成立）—— 签本身有效，但"最后一次判定"要另读 §3.1。

---

## 7. 怎么复跑

```bash
# 看真机（81 / 87 任一）：
agentflow --root projects/paper-rewrite-87 runs

# 这一轮的三条核心判据（约 45 秒；本文写作时 27 passed）：
python -B -m pytest tests/test_f_and_b_manuscripts_are_one_implementation.py \
    tests/test_d_does_not_land_the_proof.py \
    tests/test_fs_reserved_framework_artifacts.py -q

# 文档侧两条：
python -B -m pytest tests/test_docs_index_covers_every_doc.py \
    tests/test_reading_map_counts.py -q

# 生成器与产物同源（只改产物也红的那条）：
python -B -m pytest tests/test_system_docs_are_generated.py -q

# Lean 泄漏三档：
python -B -m pytest tests/test_lean_state_does_not_leak_between_tests.py -q

# warm 滚存 4 行：
python -B -m pytest tests/test_cross_run_prefix_is_reused.py tests/test_prompt_cache_warm.py -q
```

读数复算（与 §3 同口径，`projects/` 只读）：

```bash
python -B -c "import json;d=json.load(open('projects/paper-rewrite-87/data/dependencies.json'));print(len(d['rows']))"
python -B -c "import json;u=json.load(open('projects/paper-rewrite-87/data/usage_ledger.json'));print(round(sum(r['usd'] for r in u['rows']),6))"
python -B -c "import pathlib;print(pathlib.Path('projects/paper-rewrite-87/reports/RESEARCH.md').stat().st_size)"
```

---

## 8. 一句话交接

**D 的教法、fs 三档拒、F/B 唯一实现都已经在盘上并有判据；87 证明了"D 不再自己落稿"，
但"签完之后 B 回读把档位抬起来"还没在真机上走完 —— 明天先补这一格，别重跑整条链。**
