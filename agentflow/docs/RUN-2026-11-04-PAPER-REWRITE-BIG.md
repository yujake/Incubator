# 2026-11-04 大真机收工总账：`projects/paper-rewrite-big`

> 作用：把 2026-11-04 那趟「大真机」的逐格读数、八条巡查裁决、两条 V 判词、唯一断点、
> 可续跑位置与诚实清单一次写清，供下一趟接手。
>
> 读数时点：2026-11-04 17:34（本文件只读盘，不重跑模型；工作区最后一次写入是 15:16:07）。
> 口径：正文里的数字都是现算自 `projects/paper-rewrite-big/`、`src/`、`docs/` 的落盘件；
> 凡与交办口径不一致的，正文按盘上写，并在 §八逐条列出「交办口径 vs 盘上」。

## 一、这趟是什么

| 项 | 读数 | 来源 |
|---|---|---|
| 工作区 | `projects/paper-rewrite-big` | `.agentflow-workspace`（`created_at=2026-11-04T13:43:58+08:00`） |
| 任务 | 与 `paper-rewrite-83` 逐字相同：**1219 字**、sha256 前 32 位 `11c9964a30c89f10b16d0e03e53b762f` | 本工作区 `sessions/20261104.jsonl` 第 1 行 `opening_facts.task`；`paper-rewrite-83/sessions/20261102.jsonl` 第 1 行同值（两处 `len` 与 UTF-8 sha256 现算一致） |
| 预算 | **$8.00**（`total_usd`；业主备注「墙钟 5 小时，预算 8 美元」） | `budget.json` |
| 墙钟上限 | **18000 秒** | `sessions/20261104.jsonl` 第 1 行 `opening_facts.parent_limits` |
| 起跑 | 13:43:58（工作区建立；首条 usage 13:44:03） | `.agentflow-workspace`；`data/usage_ledger.json` 第 1 行 |
| 业主叫停 | **15:14:58** | `runs/stop-history.jsonl` 第 1 条 `at` |
| 实跑 | **91 分 00 秒**（13:43:58 → 15:14:58） | 同上两行相减 |
| 代码版本 | `PROMPT_VERSION = p238`；起跑时 HEAD **`28b813d6`**（2026-11-04 13:19:00） | `src/agentflow/agent_prompts.py:3132`；`git show -s 28b813d6` |

补：起跑后仓库 HEAD 又前进到 `20ae1e71`（14:15:00），但 `PROMPT_VERSION` 仍是 p238；
上表记的是「起跑时」那一版。任务文本的 `temp/_cold_start_task_uap.txt` 本身已不在 `temp/`，
同一个 1219 字 / `11c9964a30c8` 的读数另见 `docs/USER-GUIDE.md:585-586`。

## 二、收工读数（逐格）

### 2.1 台账与钱

| 格 | 读数 | 来源 |
|---|---:|---|
| `tasks` | **111** | `data/tasks.json`（111 行） |
| `tasks.status` | done **28** / pending **73** / running **10** | 同上，逐行计数 |
| done 的 `outcome` | ok 20 / cancelled **6** / cut_off_by_parent 2 | 同上 |
| 角色分布 | B 35 · M 23 · V 17 · F 16 · D 11 · A 5 · G 3 · E 1 | 同上 |
| `usage_ledger` | 403 行（403 次入账调用） | `data/usage_ledger.json` |
| 花费 | **$1.763941 / $8.00 = 22.05%** | 同上 403 行 `usd` 求和 |
| 事件 | **2405** 行（seq 1–2405；13:43:58 → 15:16:07） | `data/events.jsonl` |
| `reconnect` | **10 条**（`judge_no_reply:unknown` 4 + `judge_no_reply:network` 6；等待 2.6–9.7 秒，全部恢复） | `sessions/20261104.jsonl:2273,2274,2277,2278,2292-2297` |
| `model_unreachable` | **0** | 会话与事件全文检索无此串 |
| `waiting_for_user` | **0**（36 条 `agent_run_start` 的 `waiting_for` 全空） | `sessions/20261104.jsonl` |
| 任务 `error` / `refusal_reason` | 0 / 0 | `data/tasks.json` 逐行 |
| 被拒动作 | 0 | `out/review/STATUS-20261104-1516.md` §三 |

钱按角色：F 0.395479 · G 0.361127 · D 0.244846 · B 0.208926 · V 0.167329 · A 0.162140 ·
M 0.134278 · E 0.089816（合计 **1.763941**；源同上）。

### 2.2 产物

| 面 | 读数 | 来源 |
|---|---:|---|
| `statements` | **15**（000000–000014） | `data/statements.json` |
| 有正文 | **3**（000000 403 字 / 000001 292 字 / 000004 1309 字） | 同上 `proof_text` |
| `reviewed=True` | **3** | 同上 `bits.reviewed` |
| `evidence_kind` | cross_check 10 / heuristic 2 / proof_review 3 | 同上 |
| `bits.grade` | conjecture 12 / pre_theorem 3 | 同上 |
| `bits.formal` / `bits.numeric` | pending 15 / pending 15 | 同上 |
| `experiments` | **4** | `data/experiments.json` |
| `dependencies` | **0 行** | `data/dependencies.json` |
| `vsigns` | **4 个文件**（3 份 sign + `issued.json`） | `out/vsigns/` |
| `verifications` | **10 个台账文件**（8 份 + `pending/` 2 份；26 行 = 成立 16 / 有毛病 10） | `verifications/` |
| `reports` | **16 份**（attack 1 / b-lit-digest 1 / b-proof 4 / fulltext-fetch 1 / lit-landscape 1 / lit-r 4 / r1–r4 4；**无 f-proof / e-proof**） | `reports/` |
| `notes` | **4 份**（B.md / D.md / F.md / F-conj000000-proof.md） | `notes/` |
| 稿件目录 | `manuscripts/` 只有 `handoffs.jsonl`，无 `.md` 稿 | `manuscripts/` |

`reports` 的 4 份 `b-proof` 是 000000 / 000001 / 000002 / 000004；没有 000003、000005，也没有
任何 `f-proof-*.md` / `e-proof-*.md`。

## 三、八条巡查项的逐条裁决

| # | 巡查项 | 裁决 | 依据 |
|---|---|---|---|
| 1 | 进程 / 预算 | **通** | 花费 **$1.763941**；实跑 **91 分**；`model_unreachable` **0**。但盘上 `reconnect` **10 条**（全在 10 秒内恢复），不能记成 0 |
| 2 | 出稿 | **不通**（按「按号命名」口径） | `reports/f-proof-*.md` = **0 份**；F 的手稿在 `notes/F-conj000000-proof.md`（14376 B，sha `9537e028…`），不在 `reports/`，也没有号 |
| 3 | 派 V | **通** | V 任务 **17** 条：`called_by=B` 13 / `called_by=F` 4；M 直派 **0** |
| 4 | 落签 | **通** | 盘上 **4 处签**：`out/vsigns/` 3 份 sign JSON（000000 / 000001 / 000004）+ `reports/b-proof-000004.md` 的内嵌签块；4 处的 `written_by` / 签名者全是 `secretary:B`。`issued.json` 记 3 条颁发，每条 `streak=3 / need=3` |
| 5 | 收录 | **通** | 有正文 3 条全 `reviewed=True`，且 `reviewed_sha_by_proof` 与签的 `artifact_sha` 逐条相符；**有正文无签 = 0**。台账缺口：000004 的 `issued.json` 外键与 `reviewed_by.verification_id` 为空，签块自述「命题号=未在册」，但 sha 相符 |
| 6 | 依赖面 | **不通** | `dependencies` **0 行**；`reports/b-proof-000004.md` 的「## 依赖」是空表并写明「空表就是声明」；F 稿的「## 依赖」只写「本稿自足、不设四列表」，没有四列表行 |
| 7 | 档位 | **口径对，交办读数有误** | `proof_review` 3 条 ⇒ `pre_theorem`；无 formal ⇒ 无 `theorem`。盘上 **`bits.grade` 不是空**：12 `conjecture` / 3 `pre_theorem`；全 `pending` 的是 `bits.formal` 与 `bits.numeric`（各 15/15）。交办说的「15 条 bits.grade 全空」盘上不成立，**记为待查** |
| 8 | 异常 | **通** | 任务 `error` 0 / `refusal_reason` 0 / `waiting_for_user` 0；`reconnect` 10 条见第 1 条，属传输层重试，不是模型不可达 |

第 2 条补一句：这不是「没有稿」——F 的修订稿已经在盘上（`notes/F-conj000000-proof.md`，
14376 B），缺的是 `reports/f-proof-<号>.md` 这个**按号命名**的载体。按「有没有写」算通，
按「按号命名」算不通，本表采用后者。

第 5 条补一句：000004 的签在 `reports/b-proof-000004.md#V签`（sha `2603f7c5…`），
statement 的 `reviewed_by.evidence` 也指向那里；它没有进 `issued.json` 的 `statement_id`，
这是台账外键的缺口，不是「无签」。

## 四、两条真判词（逐字摘要）

### 000011#p1（`stmt:000011`，`proof_no=1`）

- 台账：`verifications/000011.jsonl#v-000001`，`verdict=有毛病`、`defect_step=3`、
  `unresolved_errors=1`（`at=14:52:59`）。
- 缺陷：第 (iii) 步（承重步）原句「`∫|f_λ − 1_{(c,d)}|^p ≤ (2ε/|L+−L−|)^p·(d−c) + C^p·4M/λ → 0`」——
  好区域 `R∖E_λ` 不止中间段 `(c,d)`，还包括 `x < c−M/λ` 与 `x > d+M/λ` 两条**无限测度**半直线；
  上界是正常数 `2ε/|L+−L−|`，不衰减，按 `(d−c)` 计测度漏掉的正是这两条。
- 反例（V 的 `final` 原文）：`σ(t)=sin(t²)/log(e+t²)+1_{t≥0}`（有界 Borel，`L−=0`、`L+=1`）
  ⇒ 外侧尾部 `|f_λ|` 在正测度集上约 `1/log(λ|x|)`，`∫|f_λ−1_{(c,d)}|^p=∞`
  ⇒ 该收敛断言对合法 σ 为假。
  （台账 `findings` 里另给了一个方向：`p=1`、`σ(t)=|t|^{-1/2}sin(t²)`；上面这条是 `final` 里
  的有界 Borel 取法。）
- 来源：`runs/V-20261104-145412-001.json` 的 `final`（同文见 `out/tasks/t-000065.json` 的
  `payload_preview`）。

### 000012#p1（`stmt:000012`，`proof_no=1`）

- 台账：`verifications/000012.jsonl#v-000001`，`verdict=有毛病`、`defect_step=4`、
  `unresolved_errors=1`（`at=14:53:35`）。
- 缺陷：Step 3 引理证明第一句「令坐标 `(u,s) := (b_1·y, b_2·y)`（线性同构，Jacobian 为常数）」——
  引理声明对任意 `n` 成立、条件只要求 `b_j` 两两不平行；`n=0` / `n=1` 时条件空洞成立，仍在断言范围内，
  但 `n≤1` 没有 `b_2` 可取，退化情形未单独处理 ⇒ 该引理不算完整证明。
- 来源：`verifications/000012.jsonl#v-000001`；`manuscripts/handoffs.jsonl:13`；
  `out/roster/t-000027-index.jsonl:5-6`。

### F 的修订与重送

- 新版：`notes/F-conj000000-proof.md`，sha `9537e02897597f73cb8000dab0a62038441ab192fa17b44be2c2aaf2d9dc4b7a`，
  **14376 字节**，标题「修订版 R2」（第 1 行），第 10–12 行逐条回应两条判词。
- 旧版：sha `5414d81111a00e808201a242987e0bc8293ee528be81d96616d4ee1dc03962b2`，作废
  （见 `runs/B-20261104-144551-001.json:33` 与 `out/clock/state.json:2070,2093,2106`）。
- 重送：15:14:26 同时绑定 V1/V2（`t-000098` / `t-000099`），15:15:00 / 15:15:26 被叫停
  ⇒ 重审没跑完（`out/roster/t-000027-index.jsonl:5-6`；`data/tasks.json` 两行 `outcome=cancelled`）。

## 五、唯一断点：`stmt:000000` 的实证链

| 时刻 | 动作 | 盘上证据 |
|---|---|---|
| 14:16:47 | B 登记命题，**正文 0** | `data/events.jsonl` seq 1026：`kind=conjecture`、`proof_text` 长 0、`reviewed=False`、`grade=conjecture` |
| 14:20:49 | V 台账 `verdict=成立`、`proof_sha256=3ad12fc1…` | `verifications/000000.jsonl#v-000001`（`proof_chars=403`、`defect_step=null`、`unresolved_errors=0`） |
| 14:22:46 | V 签发 `vsign/1` | `out/vsigns/3ad12fc1….json`：`artifact_path=""`、`manuscript_write.state="not_attempted"`、`why="没有手稿路径 ⇒ 签块没地方写"` |
| 14:25:44 | B 登记证明正文，**403 字** | `data/events.jsonl` seq 1330：`proof_text` 长 403、`reviewed=True`、`grade=pre_theorem` |
| 14:26:16 | B 升档 `proof_review` / `theorem` | `data/events.jsonl` seq 1353；`statements.json` 000000 的 `_kind_upgrade.at` 与 `_evidence_kind_upgrade.at` 都是 14:26:16 |

结论：

- **签是真的**：`sha256(statement 000000 的 403 字正文) = 3ad12fc1…` = 签的 `artifact_sha`
  = `bits.evidence.reviewed_sha_by_proof["1"]`（三处逐字相同，现算）。
- **载体是内联正文**：签记录没有手稿路径；`out/vsigns/issued.json` 的 `artifact_path` 也是空。
  于是三样同时缺席：签块没处落、`## 依赖` 段没有载体、`reports/f-proof-000000.md` 按号命名的稿不存在。
- 台账行里没有 `manuscript` / `subject_sha256` 这两个键；可核的替代读数是 `artifact_path=""`
  与 `manuscript_write.state="not_attempted"`（交办口径把它们写成空串，方向一致）。
- 业主裁定：**甲** —— 在册命题这一档也必须给 `proof_manuscript`，内联正文不再能单独过审。
- 叫停理由原文也指向同一形态：「业主叫停：F 绕过手稿直接写在册命题正文，先停下来查这条路」
  （`runs/stop-history.jsonl` 第 1 条 `reason`）。

## 六、可续跑的位置（供下一趟）

- 顶趟 `t-000001` 是 done/cancelled；`status=pending` 还有 **73** 条，另有 **10** 条
  `status=running`（`outcome=null`、`usd=0`、`ended_at=null`）是父退场时没结算的 orphan
  —— 续跑前先按 `tasks` 现状认一遍，别把 orphan 当在飞（`data/tasks.json`）。
- 续跑命令（与 V 收工回执里的原话一致）：

  ```powershell
  agentflow --root D:\Incubator\agentflow\projects\paper-rewrite-big run-agent --resume --task "<接着做什么>" --sid 20261104
  ```

- V 的两条判词对应的修订稿已经在盘上：`notes/F-conj000000-proof.md` 新版 sha `9537e028…`、14376 B；
  两条重送任务 `t-000098` / `t-000099` 已被叫停，可直接按原 `proof_manuscript` 重送，不必重写。
- 续跑的第一优先级是 §五 的断点：给 000000 这一档补 `proof_manuscript` 与签块；第二优先级是
  §三 第 6 条的 `dependencies` 行。

## 七、这趟证明了什么 / 没证明什么（诚实清单）

| 类别 | 条目 | 盘上读数 |
|---|---|---|
| 证明了 | V 只颁发 + 收方秘书落签 | 3 份 vsign + 1 处内嵌签块，签名者全是 `secretary:B`；`issued` 的 3 条各 3 转 |
| 证明了 | V 能给出可操作的真缺陷 | 000011#p1 `defect_step=3`、000012#p1 `defect_step=4`；两条都指到原句与最小补法 |
| 证明了 | F 能按判词自我修订并重送 | 新版 sha `9537e028…`、14376 B；15:14:26 重送，15:15:00/15:15:26 被叫停 |
| 没证明 | F 稿的签块落稿 | **0 处**（`notes/F-conj000000-proof.md` 全文无「V 签」）；盘上唯一签块在 `reports/b-proof-000004.md`（B 的稿） |
| 没证明 | 依赖面录入 | `dependencies` **0 行** |
| 没证明 | 按号命名的 `f-proof` | **0 份**；F 稿叫 `notes/F-conj000000-proof.md`，没有号 |
| 没证明 | F 稿的逐份签位 `reviewed_by_proof` | **0 条**；盘上 3 条 `reviewed_by_proof` 全落在内联正文的 000000 / 000001 / 000004 上 |
| 没走到 | G/H 的论文包与收工门 | `out/paper/main.pdf` 已编（17 页、396,066 B、14:33:29、`exit_codes=[0,0]`），但 `documents` **0 行**、H 未出场、`ACCEPTANCE-CHECKS.json` 只是 13 条清单没有 pass/fail ⇒ 只到「PDF 编出来」，没到「入库 + 收工门」 |

## 八、交办口径 vs 盘上读数（逐条）

| # | 交办口径 | 盘上读数（本文件采用） |
|---|---|---|
| 1 | `tasks` 111（done 28 / cancelled 6 / pending 73） | 111 = done 28 + pending 73 + **running 10**；`cancelled 6` 是 done 里的 `outcome`，不是 `status` |
| 2 | 事件 2229+ | **2405** 行（seq 1–2405） |
| 3 | `reconnect` / `model_unreachable` 0 | `model_unreachable` 0；`reconnect` **10** 条 |
| 4 | 15 条 `bits.grade` 全空 | `bits.grade` = 12 `conjecture` + 3 `pre_theorem`；全 `pending` 的是 `bits.formal` / `bits.numeric` |
| 5 | 4 个签文件全 `written_by=secretary:B` | `out/vsigns` 4 个文件 = 3 份 sign + `issued.json`；3 份 sign 有 `written_by`；第 4 处签是 `reports/b-proof-000004.md` 的内嵌签块；V 实际颁发 **3** 条 |
| 6 | 签块落稿 0 份 | B 的稿有 **1** 处签块；F 的稿 **0** 处 |
| 7 | 逐份签位 `reviewed_by_proof` 0 条 | **3** 条（000000 / 000001 / 000004，均来自内联正文） |
| 8 | G/H 论文包与收工门没走到 | PDF 已编 17 页；`documents` 0 行、H 未出场、收工门无 pass/fail |
| 9 | 任务文件 `temp/_cold_start_task_uap.txt`（1219 字 / `11c9964a30c8`） | 文本与哈希在本工作区 `sessions/20261104.jsonl` 第 1 行与 `paper-rewrite-83/sessions/20261102.jsonl` 第 1 行逐字一致；该临时文件本身已不在 `temp/`（读数另见 `docs/USER-GUIDE.md:585-586`） |

## 读数来源（复跑）

- tasks / usage / statements / experiments / dependencies / events：`projects/paper-rewrite-big/data/*.json` 逐行现算。
- 签与台账：`out/vsigns/*.json`、`verifications/*.jsonl`、`verifications/pending/*.jsonl`。
- 判词全文：`runs/V-20261104-145412-001.json`、`runs/V-20261104-151526-001.json`；
  任务结果 `out/tasks/t-000065.json`、`out/tasks/t-000066.json`。
- 叫停：`runs/stop-history.jsonl`；会话：`sessions/20261104.jsonl`。
- 稿与论文：`notes/F-conj000000-proof.md`、`reports/b-proof-000004.md`、
  `out/paper/COMPILE-RECEIPT.json`、`out/paper/ACCEPTANCE-CHECKS.json`、`data/documents.json`。
- 代码版本：`src/agentflow/agent_prompts.py:3132`；`git show -s 28b813d6`。

## 九、更正

> 本节只做更正，不修改上文任何历史读数。
>
> 本节追加在文末（上文含「读数来源（复跑）」一字未动）；读数现算于 2026-11-04 17:46。
> 每条按「原读数 → 盘上读数 → 出处（文件行号）→ 我为什么会读错（一句）」写。

### 9.1 巡查口径的三处错读

§三 第 7 条留的「记为待查」，与 §八 第 3 / 4 / 7 条的对照，在此一并结案。

**① `reconnect`：「0 次」→ 盘上 10 次**

- 原读数：**0 次**（按 `data/events.jsonl` 扫，全文 0 命中）。
- 盘上读数：**10 次** —— `judge_no_reply:unknown` 4 + `judge_no_reply:network` 6；
  单次 `wait_sec` 2.617–9.730 秒（2.6–9.7 秒），`attempts` 1/2，全部恢复。
- 出处：`sessions/20261104.jsonl:2273,2274,2277,2278,2292-2297`（10 行，逐行
  `"kind": "reconnect"`）；`data/events.jsonl` 全文检索 `reconnect` = **0 命中**。
- 我为什么会读错：**扫错了文件** —— `reconnect` 只写进会话（`sessions/`），不写进事件
  （`events/`），按 events 扫必然得 0；这是「文件选错 ⇒ 读数恒为 0」的教训。

**② `bits.grade`：「15 条全空」→ 12 `conjecture` / 3 `pre_theorem`**

- 原读数：15 条 `bits.grade` 全空。
- 盘上读数：**15 行全有值** —— `pre_theorem` **3**（000000 / 000001 / 000004）+
  `conjecture` **12**（000002、000003、000005–000014）；全 `pending` 的是
  `bits.formal` / `bits.numeric`（各 **15/15**）。
- 出处：`data/statements.json:61,162,410`（3 条 `pre_theorem`）、
  `:273,327,493,558,651,705,775,843,913,978,1043,1108`（12 条 `conjecture`）、
  `:25,28`（每行同构；两格全文各 15 个 `"pending"`）；旁证
  `out/review/STATUS-20261104-1516.md:40`（「pre_theorem 3 条、conjecture 12 条」）。
- 我为什么会读错：把 `bits.formal` / `bits.numeric` 两格的 `pending` 当成了
  `bits.grade` 的空 —— 前者是形式化 / 数值两轴「还没做」，后者是档位，不是同一格。

**③ `reviewed_by_proof`：「为空」→ 3 条有值**

- 原读数：`reviewed_by_proof` 为空（0 条）。
- 盘上读数：**3 条有值**，位置在 **`bits.evidence.reviewed_by_proof`**，值均为
  `{"1": true}`；配套的 `bits.evidence.reviewed_sha_by_proof["1"]` 与正文 sha 逐条相同：
  000000 `3ad12fc1…`（403 字）、000001 `b048ea6e…`（292 字）、000004 `2603f7c5…`（1309 字）。
- 出处：`data/statements.json:50-55` / `:151-156` / `:399-404`（两个键各三处）；
  正文在 `:11` / `:112` / `:360`；现算 sha 与 `:54` / `:155` / `:403` 一致。
- 我为什么会读错：只读到 `bits.evidence.reviewed_by`（一条审核记录）就收手，没有下钻到
  同层的 `reviewed_by_proof` —— 键名相似，位置差一层。

### 9.2 「甲」这条裁定的理由重述

裁定本身不变：**在册命题这一档也必须给 `proof_manuscript`，内联正文不再能单独过审**。
但原写法给出的理由里有两条经盘上核对不成立，**作废**；业主裁定的依据只保留下面三条
有效理由。

- 原读数（原写法）：签块不落稿，加上「逐份签位没落」「`reviewed_by_proof` 为空」。
- 盘上读数：签块不落稿成立；后两条不成立；真正成立的第三条是「稿没按号命名」。
- 出处：`data/statements.json:50-55` / `:151-156` / `:399-404`（3 条 `reviewed_by_proof`）；
  `out/vsigns/*.json` 的 `artifact_path` / `manuscript_write`；`data/dependencies.json:1-4`；
  `notes/F-conj000000-proof.md:91-92`；`reports/` 与 `manuscripts/` 目录实测。
- 我为什么会读错：把 `bits.evidence` 下的 `reviewed_by_proof` 当成没有（同 9.1③），
  又把「F 稿上没有签块」扩大成了「所有逐份签位都没落」。

**作废理由（盘上证明不成立）**

- 「逐份签位没落」（即 `reviewed_by_proof`）—— 盘上 `bits.evidence.reviewed_by_proof`
  **3 条有值**（见 9.1③）。
- 「`reviewed_by_proof` 为空」—— 同上，3 条有值，且 `reviewed_sha_by_proof["1"]`
  与正文 sha 相符。

**有效理由（三条，均为真机证据，也就是业主裁定「甲」的依据）**

1. **签块不落在稿上**：000000 / 000001 的签 `artifact_path=""`、
   `manuscript_write.state="not_attempted"`、`why="没有手稿路径 ⇒ 签块没地方写"`
   （`out/vsigns/3ad12fc1….json`、`out/vsigns/b048ea6e….json`）；`out/vsigns/issued.json`
   里这两条的 `artifact_path` 同样为空；F 的 `notes/F-conj000000-proof.md` 全文没有
   `- V 签：` 签块（96 行；第 95 行只自述尚未取得 V 的「成立」签）。000000 / 000001 的签只落在
   台账与内联正文上，没有落在任何「稿」上。
2. **依赖面不从稿读**：`data/dependencies.json` **0 行**（`:1-4`）；F 稿的 `## 依赖`
   只写「本稿是自足的（无在册命题引用，无外部文献引文），故不设引用四列表」
   （`notes/F-conj000000-proof.md:91-92`）；`reports/b-proof-000004.md` 的 `## 依赖`
   是空表（`:45-50`）。⇒ 依赖面在盘上没有可读的四列表，不能声称「从稿上读到了依赖」。
3. **稿没按号命名**：F 稿叫 `notes/F-conj000000-proof.md`，不带命题号；`reports/` 的
   16 份 `.md` 里没有一份 `f-proof-*.md`；`manuscripts/` 只有 `handoffs.jsonl`。
   出处：`reports/`、`manuscripts/` 目录实测；本文件 §二 2.2 的 63–64 行同读数。

一句话：三条有效理由指向同一件事 —— **载体不是「按号命名、能落签块、能读依赖」的稿**；
甲裁定不是「F 没写」，而是「写的地方 / 命名不对」。

### 9.3 F 并没有「绕过手稿」

- 原读数（§五 引的叫停原文）：「F 绕过手稿直接写在册命题正文，先停下来查这条路」
  （`runs/stop-history.jsonl:1-6`）。
- 盘上读数：F 写了攻坚手稿 `notes/F-conj000000-proof.md`（现版 96 行 / **14,376 B** /
  sha `9537e028…`），并且两次送审都用了 `proof_manuscript=notes/F-conj000000-proof.md`：
  14:46:15 首送（旧版 sha `5414d811…`）、15:14:26 重送（新版 sha `9537e028…`，
  `t-000098` / `t-000099`）。
- 出处：`sessions/20261104.jsonl:1874`（F 的 `summon_many`；两个 V 目标的
  `params.proof_manuscript` 都是 `notes/F-conj000000-proof.md`）、`:1892`（F 自述
  「都给的是 proof_manuscript=notes/F-conj000000-proof.md」）、`:2432`（重送两个 V 目标的
  `manuscript_sha256=9537e028…`）；手稿现算 14,376 B / `9537e028…`；重送任务起于 15:14:26
  （`data/tasks.json` 的 `t-000098` / `t-000099` 行）。
- 缺的一步：把 `notes/` 的稿转成 `reports/f-proof-<号>.md`。盘上 `reports/` 的
  `f-proof-*` = **0 份**，`manuscripts/` 只有 `handoffs.jsonl` ⇒ 缺的是「转成按号命名的
  `reports/` 稿」这一步，不是「没写稿」。
- 我为什么会读错：把「签块没落在稿上 / 稿不在 `reports/`」读成了「F 没写手稿」；
  `proof_manuscript` 的送审参数就在会话里，查一下就能看到。

### 9.4 G 已编出论文 PDF，但论文包没入库

- 原读数：G / H 的论文包「没走到」（笼统记成没做）。
- 盘上读数：`out/paper/main.pdf` **17 页 / 396,066 B / 编译于 14:33:29 /
  `exit_codes=[0,0]`**；但 `data/documents.json` **0 行**、`tasks` 里 **H 角色 0 条**、
  `out/paper/ACCEPTANCE-CHECKS.json` 只有 **13 条清单、没有 pass/fail**，
  `out/paper/ACCEPTANCE.md` 不在盘上 ⇒「论文包」这条链 **只走到编译**，没到「入库 + 收工门」。
- 出处：`out/paper/COMPILE-RECEIPT.json:6-13`（`exit_codes` / `pages` / `pdf_bytes` /
  `compiled_at`）；`data/documents.json:1-4`（`"rows": []`）；`data/tasks.json` 逐行
  （H = 0）；`out/paper/ACCEPTANCE-CHECKS.json:1-17`（13 条 check，无 verdict）。
- 我为什么会读错：把「`documents` 0 行 / 收工门没跑」笼统写成了「论文包没走到」，
  抹掉了 G 已经把 PDF 编出来这一步 —— 该记的是「编译完成、入库未做」，不是「没做」。

### 9.5 四条更正的一句话结论

| # | 一句话 |
|---|---|
| ① | 巡查三处错读：`reconnect` **10 次**（不在 `events.jsonl`）、`bits.grade` **12 + 3**（全 pending 的是 `bits.formal` / `bits.numeric`）、`reviewed_by_proof` **3 条**（在 `bits.evidence` 下）。 |
| ② | 「甲」保留三条有效理由（签块不落在稿上 / 依赖面不从稿读 / 稿没按号命名），作废两条（逐份签位没落 / `reviewed_by_proof` 为空）。 |
| ③ | F 写了 `notes/F-conj000000-proof.md` 并用 `proof_manuscript=notes/…` 送审；缺的是转成 `reports/f-proof-<号>.md`。 |
| ④ | G 的 `main.pdf` 已编（17 页 / 396,066 B / 14:33:29 / exit `[0,0]`），`documents` 0 行、H 未出场、收工门未跑 ⇒ 只到编译。 |
