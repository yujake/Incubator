# 等级（`grade`）与档位（`evidence_kind`）—— 两个轴、三张表

> **判据**：`tests/test_two_axes_grade_and_kind.py`（现算处 `tests/_two_axes.py`）。
> 本文件里五张表**逐格**由它比对：表里改错一格 ⇒ 红；`derive_grade` 的一条规则
> 改了而这里没跟着改 ⇒ 红；现场快照与这里对不上 ⇒ 红。
> 三张表（+ 两张附表）的原文可以用 `python -X utf8 tests/_two_axes.py` 打出来，
> 整段粘回去 —— 这是本文件唯一的更新方式（§8 给命令）。
>
> 本文件里的 `file:line` 是 **2026-11-05 21:4x 的盘上读数**：行号会漂（本仓并行开发下
> 是常态），**符号名不会**。找落点请按符号名找；行号对不上时先按符号名定位、
> 再回来改这一格。

## 0. 一句话

「**可引**」读**档位**（`evidence_kind`）；「**多硬**」读**等级**（`grade`）。
两者不是同一个轴，谁也替不了谁 —— 不是"等级更细所以能替档位"，也不是"档位更强
所以能当等级读"。今晚的真机反例（§6）：`R-mk-infinite-90/000013` 档位 `proof_review`
（可引）而等级 `pre_theorem`（不是定理）；`ramsey-4-4-87/000001` 档位 `proof_review`
（可引）而等级 `conjecture`（连"有证明"都没有）。

## 1. 两套词表（逐字从代码取）

| 轴 | 常量 | 落点 | 取值（逐字） | 序 | 谁产出 |
|---|---|---|---|---|---|
| **等级** | `GRADES` | `evidencebits.py:94` | `conjecture` / `strong_conjecture` / `pre_theorem` / `theorem` | 由弱到强 | 只有 `evidencebits.derive_grade`（`:1060`）一处；任何角色自报的等级都不认 —— 行上 `bits.grade` 与现算不一致时，`bit_problems`（`:1289`）报缺陷 |
| 等级（不参与链） | `GRADE_NOT_APPLICABLE` | `evidencebits.py:98` | `not_applicable` | 刻意不在 `GRADES` 里 | 同上，`kind="concept"` 短路那一支 |
| **档位** | `EVIDENCE_KINDS` | `schema.py:1237` | `proof` / `proof_review` / `cross_check` / `heuristic` | 由强到弱 | 提交方在 `register_statement(evidence_kind=…)` 里声明（缺省 `cross_check`，`agent_b/register_statement.py:1582`；词表校验 `:2272`）；V 落签那一刻按通道重算（`verifications._grade_recomputed_from_signature:2625`）；秘书在"同一份内容再交一次"时升档（`secretary._upgrade_evidence_kind:7008`） |
| 档位（实验表那一档） | `EXPERIMENT_EVIDENCE_KINDS` | `schema.py:1245` | `proof` / `cross_check` / `heuristic`（少 `proof_review`） | 同上 | `experiments` 表专用：一次实验没有"逐行审阅过的证明"这一档 |

三条容易读错的地方，逐条钉住：

1. **两条序方向相反**：`GRADES` 从弱往强写，`EVIDENCE_KINDS` 从强往弱写。
   `depsection.citation_levels()`（`:189`）靠的正是这一点从 `EVIDENCE_KINDS` 的声明序
   **逆序**切出"`proof_review` 级及以上 = `{proof_review, proof}`"，所以它先在导入期断言
   `tools/verify_tools._EVIDENCE_ORDER` 与声明序互为逆序（`:209-217`）。两条序不是一回事：
   把一条当成另一条，放行的就是弱档。
2. **两套词表不相交**：`set(GRADES) | {GRADE_NOT_APPLICABLE}` 与 `set(EVIDENCE_KINDS)`
   没有交集（判据 `test_two_vocabularies_do_not_overlap_and_the_gate_judges_the_kind` 钉住这一点）。所以把等级当档位
   传下去**不会报错**，只会静默落空 —— `citation_level_allowed('theorem')` 走的是
   "词表外 ⇒ 假"那一支，读起来像"这一条不够格"，而它其实是一句读错词表的读数。
3. **"可引"判的是档位**：`CITATION_MIN_LEVEL = "proof_review"`（`depsection.py:134`）与
   `citation_level_allowed(level)`（`:225`）的入参是 `statements.evidence_kind`，
   调用点见 `agent_f/manuscript.py:110-113`（`level = row["evidence_kind"]`）。

## 2. 五元位（五位、取值域、判等级时各读什么）

| # | 位 | 取值域（逐字从代码取） | 常量 / 读口 | `derive_grade` 读它吗 | 赋权所有者 |
|---|---|---|---|---|---|
| 1 | `numeric` | `pending` / `na` / `failed` / `verified`（`BIT_STATES`，`evidencebits.py:92`） | `_state`（`:139`）→ `_bit_state`（`:188`） | 读，但只在 `== "verified"` 时抬一档（封顶在"强猜想"） | E |
| 2 | `proof` | `bool` | `bits_of` 收窄成 `bool(proof) or cited or bool(proof_process)`（`:246`） | 读（`bool`） | F |
| 3 | `reviewed` | `bool`（凭什么另有三态 `reviewed_source`：`v` / `citation` / 空，`:217-218`） | `bits_of:248` | 读（`bool`） | V（引用命题是"引用"） |
| 4 | `formal` | **二维** `{证明号: 状态}`；逐路径五态 `pending` / `na` / `failed` / `verified` / `stale`（`FORMAL_PATH_STATES`，`:129`）；标量也收（形状原样保留） | `_bit_value`（`:176`）→ `_bit_state` 的 OR（`_BIT_OR_ORDER`，`:136`：任一 `verified` 即算过） | 读汇总那一层（任一路径 `verified`） | L |
| 5 | `audited` | `bool` | `bits_of:251`；落点是并列的 `audited_badge`（`:273`：`audited` 且等级不是 `conjecture`/`not_applicable`） | **不读**（见 §3.3） | H |

> 口径校正（业主原话里的"三态"）：代码里第 1/4 位的写侧词表是**四态**（`BIT_STATES`），
> 第 4 位的读侧多一档 `stale`（"验过、但验的不是现在这一份"）。本表按代码写。

## 3. 表一：五元位状态 ⇒ 等级

32 组 = 五位的"就绪/未就绪"全枚举（`numeric` 取 `verified`/`pending`，`formal` 取二维的
`{"1": "verified"}` 与标量 `pending`）。**等级那一列是 `derive_grade` 的真输出**，
不是推测；`audited_badge` 那一列是 `bits_of` 的真输出（第 5 位的实际落点）。

<!-- TWO-AXES:TABLE1:BEGIN -->
| # | numeric | proof | reviewed | formal | audited | 等级 | `audited_badge` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00 | verified | true | true | verified | true | theorem | true |
| 01 | verified | true | true | verified | false | theorem | false |
| 02 | verified | true | true | pending | true | pre_theorem | true |
| 03 | verified | true | true | pending | false | pre_theorem | false |
| 04 | verified | true | false | verified | true | theorem | true |
| 05 | verified | true | false | verified | false | theorem | false |
| 06 | verified | true | false | pending | true | strong_conjecture | true |
| 07 | verified | true | false | pending | false | strong_conjecture | false |
| 08 | verified | false | true | verified | true | strong_conjecture | true |
| 09 | verified | false | true | verified | false | strong_conjecture | false |
| 10 | verified | false | true | pending | true | strong_conjecture | true |
| 11 | verified | false | true | pending | false | strong_conjecture | false |
| 12 | verified | false | false | verified | true | strong_conjecture | true |
| 13 | verified | false | false | verified | false | strong_conjecture | false |
| 14 | verified | false | false | pending | true | strong_conjecture | true |
| 15 | verified | false | false | pending | false | strong_conjecture | false |
| 16 | pending | true | true | verified | true | theorem | true |
| 17 | pending | true | true | verified | false | theorem | false |
| 18 | pending | true | true | pending | true | pre_theorem | true |
| 19 | pending | true | true | pending | false | pre_theorem | false |
| 20 | pending | true | false | verified | true | theorem | true |
| 21 | pending | true | false | verified | false | theorem | false |
| 22 | pending | true | false | pending | true | conjecture | false |
| 23 | pending | true | false | pending | false | conjecture | false |
| 24 | pending | false | true | verified | true | conjecture | false |
| 25 | pending | false | true | verified | false | conjecture | false |
| 26 | pending | false | true | pending | true | conjecture | false |
| 27 | pending | false | true | pending | false | conjecture | false |
| 28 | pending | false | false | verified | true | conjecture | false |
| 29 | pending | false | false | verified | false | conjecture | false |
| 30 | pending | false | false | pending | true | conjecture | false |
| 31 | pending | false | false | pending | false | conjecture | false |
<!-- TWO-AXES:TABLE1:END -->

### 3.1 怎么读这张表

- 判定的优先级**不是**按位从 1 到 5，而是：概念短路 → 作废短路 → `proof ∧ formal`
  → `proof ∧ reviewed` → `numeric` → 兜底 `conjecture`（`derive_grade:1073-1089`）。
  所以 `proof` 是"进入前两档的门票"，`reviewed` 与 `formal` 各自是**并列**的一条硬凭据；
  `numeric` 只在门票拿不到时给一个封顶的抬升。
- 上下两半只差第 1 位（#00-#15 是 `numeric=verified`，#16-#31 是 `pending`）。
  第 1 位只在"另外两条硬凭据都没有"时才看得见：凡是拿到 `proof ∧ formal`（#00/#04/#16/#20）
  或 `proof ∧ reviewed`（#02/#18）的格，第 1 位翻不翻都一样；而 `proof` 有、`reviewed`
  与 `formal` 都没有的 #06/#07 与 #22/#23，第 1 位把它从 `conjecture` 抬到
  `strong_conjecture`；`proof` 也没有的 #08-#15 一律 `strong_conjecture`、#24-#31 一律
  `conjecture`。数值验证再多也进不了 `proof` 那两档。
- `reviewed` 在 `formal` 也在时**不改变**结果（#00/#04 都是 `theorem`）：两条硬凭据
  各管一档，`theorem` 那一档不需要第 3 位（这也是 `evidencebits.kind_following_grade`
  的 docstring `:1137-1147` 那一段裁定的依据）。

### 3.2 短路与不可达（32 组之外的两个总开关，以及表内的两处"同样本"）

- **概念行短路**：`derive_grade(bits, kind="concept")` 第一句就返回 `not_applicable`
  （`:1073-1074`），32 组无论填什么都不参与 —— 表一**不覆盖**这一支，单列在此。
- **作废行短路**：`bits.voided_by` 非空 ⇒ 一律 `conjecture`（`:1075-1076`），
  同样压过 32 组。这一支也是表一**不覆盖**的。
- 表内**没有**不可达的组合：32 组都由 `bits_of` 造得出来（`bits_of` 对五位各自独立收值，
  没有交叉约束）。真正的"不可达"只有上面两个总开关。
- 两处"同样本"要说清，免得读者以为表漏了格：
  `audited` 翻转**从不**改变等级（32 组成 16 对，32/32 对照里 0 处不同）；
  `numeric` 的四态里 `pending` / `na` / `failed` 三态在等级上**完全等价**（只有
  `verified` 抬档）。

### 3.3 第 5 位落在哪：`audited_badge`，不是等级

`derive_grade` 一个字节都不读 `audited`（判据
`test_table1_is_a_function_of_bits_but_ignores_audited` 用 16 对对照把它钉住）。第 5 位的落点是 `bits["audited_badge"]`（`bits_of:273`）：
`audited` 为真**且**等级不是 `conjecture` / `not_applicable` 时才为真。
所以表一里 `audited=true` 而 `audited_badge=false` 的那些格（#22-#31）不是矛盾 ——
那是"审过了，但这一条还不够到能被追加标记"。

## 4. 表二：五元位状态 ⇒ 档位

**结论先行：档位不是五元位的函数。** 下面 32 格逐格算出的是同一句话；这不是"表还没填"，
而是代码的形状 —— 档位由另外三处定（§4.1），五元位在其中的作用只有一条：`proof ∧ reviewed`
⇒ "这一行有 V 签"（`secretary._manuscript_upgrade_basis:1652`），它**只发许可、不选档**。

<!-- TWO-AXES:TABLE2:BEGIN -->
| # | numeric | proof | reviewed | formal | audited | `signed`（五元位唯一能决定的那一格） | 档位（`evidence_kind`） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00 | verified | true | true | verified | true | true | 不由五元位决定 |
| 01 | verified | true | true | verified | false | true | 不由五元位决定 |
| 02 | verified | true | true | pending | true | true | 不由五元位决定 |
| 03 | verified | true | true | pending | false | true | 不由五元位决定 |
| 04 | verified | true | false | verified | true | false | 不由五元位决定 |
| 05 | verified | true | false | verified | false | false | 不由五元位决定 |
| 06 | verified | true | false | pending | true | false | 不由五元位决定 |
| 07 | verified | true | false | pending | false | false | 不由五元位决定 |
| 08 | verified | false | true | verified | true | false | 不由五元位决定 |
| 09 | verified | false | true | verified | false | false | 不由五元位决定 |
| 10 | verified | false | true | pending | true | false | 不由五元位决定 |
| 11 | verified | false | true | pending | false | false | 不由五元位决定 |
| 12 | verified | false | false | verified | true | false | 不由五元位决定 |
| 13 | verified | false | false | verified | false | false | 不由五元位决定 |
| 14 | verified | false | false | pending | true | false | 不由五元位决定 |
| 15 | verified | false | false | pending | false | false | 不由五元位决定 |
| 16 | pending | true | true | verified | true | true | 不由五元位决定 |
| 17 | pending | true | true | verified | false | true | 不由五元位决定 |
| 18 | pending | true | true | pending | true | true | 不由五元位决定 |
| 19 | pending | true | true | pending | false | true | 不由五元位决定 |
| 20 | pending | true | false | verified | true | false | 不由五元位决定 |
| 21 | pending | true | false | verified | false | false | 不由五元位决定 |
| 22 | pending | true | false | pending | true | false | 不由五元位决定 |
| 23 | pending | true | false | pending | false | false | 不由五元位决定 |
| 24 | pending | false | true | verified | true | false | 不由五元位决定 |
| 25 | pending | false | true | verified | false | false | 不由五元位决定 |
| 26 | pending | false | true | pending | true | false | 不由五元位决定 |
| 27 | pending | false | true | pending | false | false | 不由五元位决定 |
| 28 | pending | false | false | verified | true | false | 不由五元位决定 |
| 29 | pending | false | false | verified | false | false | 不由五元位决定 |
| 30 | pending | false | false | pending | true | false | 不由五元位决定 |
| 31 | pending | false | false | pending | false | false | 不由五元位决定 |
<!-- TWO-AXES:TABLE2:END -->

### 4.1 档位实际由谁定（三处 + 两个"不是派生点"）

| # | 落点 | 它定的是什么 | 判据 |
|---|---|---|---|
| ① | `agent_b/register_statement.py:1582`（缺省 `cross_check`）、`:2272`（词表校验）、`numericproof.filing_problems:1752` | 新建那一行的**初值**：提交方声明什么就是什么（模型选，不是五元位算） | 词表 + 入库闸 |
| ② | `secretary._upgrade_evidence_kind:7008`（目标档在 `:7148` 写进 `row["evidence_kind"]`） | 同一份内容再交一次时，**升到这次声明的那个更强档**（`want`，`:7051`）；升不升由凭据闸判，升到**哪一档由 `want` 决定** | `want ∈ {proof_review, proof}` ∧ `have ∈ WEAKER_THAN_PROOF_REVIEW`（`:4205`）∧ 凭据三路任一：`proof_review_gap` / 手稿签块 / `bits.reviewed`（`:7136-7141`） |
| ③ | `verifications._grade_recomputed_from_signature:2625`（目标档在 `:2685-2686`） | V 落签那一刻**按通道**重算：穷举程序 ⇒ `proof`，文字证明 ⇒ `proof_review` | 通道判据 `_exhaustion_proof_channel:2566` → `numericproof.find_signed_exhaustion_for_column:875`，读的是 `proof_text` 的证明栏 + `experiments` 台账 —— **与五元位无关** |

不是派生点的两处（别当成第四处）：

- `numericproof.proof_channel:1990` 返回的是**证明通道** `numeric` / `formal` / `""`，
  落点是 `formal_slot` 的 `FORMAL_SLOT_KINDS`；它与 `EVIDENCE_KINDS` 不是同一个词表。
  （交接时这一处曾被列为"档位派生处"，实测不是 —— 记在这里免得再传。）
- `verifications.weaker_than_evidence_gaps:4208` 是**诊断**（warning："凭据够格却登记成
  弱档"），它不写档位；`recompute_grades:4300` 是同一判据的事后回填入口，不是第二套口径。

所以要回答"这一行为什么是这一档"，得看四样东西：**提交方声明**、**证明通道**
（`proof_text` 的分段 + `experiments` 台账）、**V 的签**（连续次数 / sha 是否盖住现行正文）、
**写入期闸**（`store._refuse_fake_proof_review:196` 拒收没有凭据的 `proof_review`）。
五元位不在这个清单里 —— 它只回答"这一行有没有签"，不回答"这一行该报多强的档"。

### 4.2 把"不由五元位决定"跑成读数（32 × 2）

同一批 32 组五元位、同一份凭据，只换**证明通道**，`_grade_recomputed_from_signature`
给出的档位：

| 通道（由 `proof_text` 的证明栏 + `experiments` 台账定） | 32 组五元位产出的档位 | 读数 |
|---|---|---|
| 文字证明（台账里没有对应的穷举证明） | `proof_review` × 32（同一个值） | 通道内换五元位 ⇒ 档位**不变** |
| 穷举程序（台账里有 V 签下的穷举证明） | `proof` × 32（同一个值） | 换通道 ⇒ 档位**变** |

两条读数合起来就是表二那一列的字面意思：**档位对五元位不敏感、对通道敏感**。
判据 `test_kind_is_not_a_function_of_bits` 每次跑都重做这个实验（含反真空：
两条通道的档位必须**真的不同**，否则这条实验什么都没量到）。

## 5. 表三：等级 ⇄ 档位（互相换算）

两张现场横表：**真机**（全部工作区，频次快照）与**夹具**（`paper_rewrite_86` 那一份
逐行快照）。等级那一列全部由 `derive_grade` 现算（行上 `bits.grade` 只是缓存，不读它）。

### 5.1 真机现场：77 个工作区 / 3,627 行（`projects/*/data/statements.json`）

<!-- TWO-AXES:TABLE3:BEGIN -->
| 档位 \ 等级 | conjecture | strong_conjecture | pre_theorem | theorem | not_applicable | 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| proof | 1 | 0 | 1 | 0 | 0 | 2 |
| proof_review | 7 | 0 | 17 | 0 | 0 | 24 |
| cross_check | 106 | 0 | 30 | 0 | 44 | 180 |
| heuristic | 177 | 0 | 23 | 0 | 3221 | 3421 |
| 合计 | 291 | 0 | 71 | 0 | 3265 | 3627 |
<!-- TWO-AXES:TABLE3:END -->

### 5.2 夹具现场：`tests/fixtures/paper_rewrite_86_reviewed_bit.json`（2 行）

<!-- TWO-AXES:TABLE3F:BEGIN -->
| 档位 \ 等级 | conjecture | strong_conjecture | pre_theorem | theorem | not_applicable | 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| proof | 0 | 0 | 0 | 0 | 0 | 0 |
| proof_review | 0 | 0 | 0 | 0 | 0 | 0 |
| cross_check | 1 | 0 | 1 | 0 | 0 | 2 |
| heuristic | 0 | 0 | 0 | 0 | 0 | 0 |
| 合计 | 1 | 0 | 1 | 0 | 0 | 2 |
<!-- TWO-AXES:TABLE3F:END -->

### 5.3 哪些方向是函数、哪些不是

| 方向 | 是函数吗 | 读数 |
|---|---|---|
| 等级 → 档位 | **不是** | `pre_theorem` 在真机上落在三档（`cross_check` 30 / `heuristic` 23 / `proof_review` 17）；`conjecture` 落在两档（`cross_check` 106 / `heuristic` 177） |
| 档位 → 等级 | **不是** | `heuristic` 落在三个等级（`conjecture` 177 / `pre_theorem` 23 / `not_applicable` 3221）；`cross_check` 也落在三个（`conjecture` 106 / `pre_theorem` 30 / `not_applicable` 44） |
| `proof_review` → 等级 | 样本里单值，**结构上不是函数** | 真机 24 条全是 `pre_theorem`，但"样本单值"不等于"函数"：只要同一行第 4 位有一条 `verified`，等级就是 `theorem`（表一 #16），而档位仍可停在 `proof_review`（表二：五元位不选档）⇒ `(theorem, proof_review)` 可达 |
| `proof` → 等级 | **不是** | 真机 2 条：一条 `conjecture`、一条 `pre_theorem`（同一个档位，两个等级） |

> 表里 `strong_conjecture` / `theorem` 两列全 0，因为**整个盘上没有任何一行的第 1 位是
> `verified`、也没有任何一行的第 4 位是 `verified`**（Lean 侧全关；`formal` 这一格在 3,627
> 行里只出现过 `pending` 与 `null` 两种形态，二维的 `{证明号: 状态}` 一次都没落过盘）。
> 第 5 位也一样：`audited=true` 的行是 0 行，所以 `audited_badge` 在现场全为假。
> 这不是表没算，是现场确实没有 —— 也正因如此，档位与等级在这批现场上"看起来很像"，
> 而它们其实是两个轴。

### 5.4 "不是函数"的现场反例（逐格可由快照复核）

<!-- TWO-AXES:TABLE3X:BEGIN -->
| 反例 | 工作区 | 命题 | numeric | proof | reviewed | formal | audited | 等级 | 档位 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | R-mk-infinite-90 | 000003 | pending | false | false | pending | false | not_applicable | heuristic |
| A | R-mk-infinite-90 | 000013 | pending | true | true | pending | false | pre_theorem | proof_review |
| A | R-mk-infinite-90 | 000014 | pending | true | true | pending | false | pre_theorem | heuristic |
| A2 | R-mk-infinite-90 | 000015 | pending | false | false | pending | false | conjecture | heuristic |
| B | R-mk-infinite-90 | 000018 | pending | false | false | pending | false | conjecture | heuristic |
| A2 | R-mk-infinite-90 | 000020 | pending | false | false | pending | false | conjecture | cross_check |
| C | mp3-r3 | 000000 | pending | false | true | pending | false | conjecture | proof_review |
| C | ramsey-4-4-87 | 000001 | pending | true | false | pending | false | conjecture | proof_review |
<!-- TWO-AXES:TABLE3X:END -->

读法（三组，各自否定一件事）：

- **A 组（同五元位、不同档位）**：`R-mk-infinite-90/000013` 与 `/000014` 的五元位**逐字相同**
  （`pending / true / true / pending / false`），档位却是 `proof_review` 与 `heuristic`
  ⇒ **档位不是五元位的函数**。A2 组（`/000015` vs `/000020`）是同一形态的第二个样本
  （`heuristic` vs `cross_check`）。
- **B 组（同档位、不同等级）**：`heuristic` 这一档上，`/000003` 是 `not_applicable`
  （概念行）、`/000018` 是 `conjecture`、`/000014` 是 `pre_theorem`
  ⇒ **等级不是档位的函数**。
- **C 组（可引而不硬）**：`ramsey-4-4-87/000001` 与 `mp3-r3/000000` 的档位都是
  `proof_review`（**够格被引**），等级却只是 `conjecture`（第 2 位或第 3 位缺一格）
  ⇒ "可引"与"多硬"分家到了极端：拿等级去判可引，这两条会被拒引；拿档位去判硬度，
  这两条会被读成"证明级"。

## 6. 为什么是两个轴（今晚的真机反例）

业主今晚的指令是"给出五元位状态和这两种读法的换算表以及这两种读法互相的换算表"。
换算表能成立的前提是**两种读法各自是一个口径**；一旦把它们并成一个，就会在下面这两条
真机行上读错：

1. **档位 `proof_review` 而等级 `pre_theorem`**（`R-mk-infinite-90/000013`、`/000017`）：
   这两行的第 2、3 位都是真（有证明、V 签过），第 4 位 `formal` 还是 `pending`
   —— Lean 那一侧关着，形式化没有 `verified`。于是：
   - 按**档位**读：这份文字证明"已过 V 的逐行走查"⇒ **可引**（`citation_level_allowed`
     放行，F 写证明时能引它，B 落稿时不会拒 `citation_below_proof_review`）；
   - 按**等级**读：`pre_theorem` —— 它**不是**定理，缺的就是"形式化核验过"那一格。
   两句话都对，而且是同一条行上的两件事。若只留一个读数：拿等级当可引判据，这两条会被
   拒引（等级词表与档位词表没有交集，`citation_level_allowed('pre_theorem')` 静默返回
   假）；拿档位当硬度判据，`proof_review` 会被读成"定理级"，而它只是 `pre_theorem`。
2. **档位 `proof_review` 而等级 `conjecture`**（`ramsey-4-4-87/000001`、`mp3-r3/000000`，
   真机共 7 条）：档位是"这份被审过的证明"的声明，等级还要求第 2 位（有证明）与第 3 位
   （V 签）**同时**在 —— 这两行的第 3 位（或第 2 位）是假，于是"能引"成立、"多硬"不成立。
   这是上面那句"谁也替不了谁"最刺眼的一侧。

反过来还有个方向要注意：`derive_grade` 读第 5 位（`audited`）**一个字节都不读**，
第 5 位落在 `audited_badge`（§3.3）。所以"等级"里也不含"审过没有" ——
"多硬"问的是**数学上站到什么程度**，"可引"问的是**这一条的凭据够不够格当引用源**，
"审过没有"是第三个读数（`audited_badge`）。三个读数各有各的落点，谁也不折叠谁。

## 7. 术语校准（旧称 → 新称，逐处）

`EVIDENCE_KINDS` 在本仓的注释与文案里长期被叫**"证据等级"**。这正是同名混淆的源头：
本仓的"等级"已经被 `GRADES` 占住，而 `proof_review` **不在** `GRADES` 里 ——
把它叫"等级"，读的人就会以为等级链上还有第五档。下面逐处列出处置。

### 7.1 已改准（只动注释与 docstring；行数一字未增，`READING-MAP` 的读数不动）

| 落点 | 旧（逐字） | 新（逐字） |
|---|---|---|
| `agent_e/_support.py:399` | 脚本没报证据等级 | 脚本没报证据档位 |
| `agent_e/run_experiment.py:193` | 等级由 `numericproof` 现算，不由这里判 | 档位由 `numericproof` 现算，不由这里判 |
| `agent_e/run_experiment.py:341` | 等级全落 cross_check | 档位全落 cross_check |
| `deliver.py:175` | 把稿件的每一条断言与它挂的证据等级 | 把稿件的每一条断言与它挂的证据档位 |
| `deliver.py:176` | 证据等级是 cross_check | 证据档位是 cross_check |
| `formalgw.py:1269` | 这次检查实际到达了什么证据等级 | 这次检查实际到达了什么证据档位 |
| `formalgw.py:1273` | 这次没有拿到任何等级的证据 | 这次没有拿到任何档位的证据 |
| `runflow.py:1501` | 等级写进 `claims.json` 的 `lean` 段 | 档位写进 `claims.json` 的 `lean` 段 |
| `exhaustionreport.py:24` | 等级由 `exhaustion_problems` 单点决定 | 档位由 `exhaustion_problems` 单点决定 |

这九行分布在六个文件里，全部是注释 / docstring：不改变任何运行期输出，也不改变任何
判据的断言语义（`git diff --numstat` 逐文件 1/1 或 2/2 —— 增删行数相等，
`docs/READING-MAP.md` 开头那三个读数因此不动）。

### 7.2 逐处登记（已改 / 未改分开写）

| 类别 | 落点 | 处置（已改 / 为什么不动） |
|---|---|---|
| 同族注释，但**与另一条线共用文件** | `depsection.py:27,190,201,211`、`agent_b/register_statement.py:1692`、`agent_f/core.py:1769` | 本笔开工时这三个文件带着另一条线的未提交改动（那一笔已作为 `33e25783` 落地，改的正是依赖面），同一时间段里 `secretary.py` / `agent_v/core.py` / `conductor.py` 仍在被改。本仓的提交纪律是 `git commit -F 消息 -- 精确路径`，而 pathspec 提交的是**整份文件** ⇒ 与别线共用文件时不碰，免得把别人写了一半的东西卷进这笔提交。这几处的改法就是同一句"等级"→"档位"，留给人手批 |
| 运行期文案（报告 / 拒信里的字） | `agent_e/_support.py`、`agent_e/run_experiment.py`、`exhaustionreport.py`、`judges.py`、`runflow.py`、`tools/doc_tools.py`（阅读须知 / 统计表）、`tools/review_tools.py`、`faculty_checks.py`、`claimanatomy.py`、`statusreport.py`、`closing.py`、`formalgw.py`、`agent_g/*` | **2026-11-05 第二批已改**：报告、拒信与读数里的「证据等级」统一成「证据档位」；同批把钉旧字面量的断言迁到新字面量（`test_runflow_lean.py` / `test_agent_g.py` / `test_paper_pack.py`），判定条件一字未改。工具声明（进 golden）与禁改区（`schema.py` / `verify.py` / `tools/verify_tools.py`）仍按下面两行原样登记 |
| FC-27 禁改区（要 2 名 reviewer） | `schema.py:1224,1239,1607,1674,2335`、`verify.py:887` | 这两份文件在 `.noai-paths` 里（`[schema-migration]` / `[eval-criteria]` / `[auth-audit]`）；`scripts/noai_gate.py --git` 会以退出码 1 要求 2 名 reviewer ⇒ 本笔不碰 |
| 工具声明（进 golden） | `doc_tools.py:2260`、`review_tools.py:125,596`、`tools/verify_tools.py:23` | 工具描述进 `tests/fixtures/tool_declaration_baseline.json`；改字就要重冻 golden ⇒ 本笔不碰 |
| 提示词 / 技能文本（进提示词缓存） | `agent_prompts.py:2044`、`agent_skills.py:1717,1768,4037`、`specs/m.py:347` | 改它们要抬 `PROMPT_VERSION` 并重冻 warm fixture（`tests/fixtures/prompt_cache_warm.json`）⇒ 按纪律先报业主，本笔不动 |
| 名字本身（代码标识符） | `verifications._grade_recomputed_from_signature:2625`、`recompute_grades:4300`、`GRADE_BACKFILL_COLUMNS:4296`、CLI `recompute-grades`、`depsection.CITATION_MIN_LEVEL:134`、`citation_level_allowed:225`、`citation_levels:189` | 这几处名字里的 `grade` / `level` 指的都是**档位**（它们读写的字段是 `statements.evidence_kind`），名与实不符。改名属**代码改动**（会动导入面、CLI 子命令名与判据），按纪律先报，本笔只登记 |


## 8. 复跑与刷新

```bash
# 三张表（+ 两张附表）的原文：整段粘回本文件的标记块之间
python -X utf8 tests/_two_axes.py

# 判据（逐格比对 + 三组反真空）
python -m pytest -q tests/test_two_axes_grade_and_kind.py

# 刷新现场快照（`projects/` 被 .gitignore 排除，判据读的是这份快照）
python -X utf8 tests/_two_axes.py --refresh-scene
```

快照里带 `captured_at` 与 `command`：它是**带日期的读数**，不是"永远正确"的口径。
新增工作区之后重跑上面第三条命令、把 `tests/fixtures/two_axes_scene.json` 的 diff 看一眼，
本文件的表会跟着红一次（这正是"表过期 ⇒ 红"该有的样子）。
