# 等级（`grade`）是唯一的轴 —— 档位（`evidence_kind`）只是它的历史反算名

> **判据**：`tests/test_two_axes_grade_and_kind.py`（现算处 `tests/_two_axes.py`）。
> 本文件里五张表**逐格**由它比对：表里改错一格 ⇒ 红；`derive_grade` 的一条规则
> 改了而这里没跟着改 ⇒ 红；现场快照与这里对不上 ⇒ 红。
> 五张表（+ 两张附表）的原文可以用 `python -X utf8 tests/_two_axes.py` 打出来，
> 整段粘回去 —— 这是本文件唯一的更新方式（§8 给命令）。
>
> 本文件里的 `file:line` 是 **2026-11-05 的盘上读数**：行号会漂（本仓并行开发下
> 是常态），**符号名不会**。找落点请按符号名找；行号对不上时先按符号名定位、
> 再回来改这一格。

## 0. 一句话

**等级是唯一的轴**：`conjecture < strong_conjecture < pre_theorem < theorem`；
档位（`evidence_kind`）只是等级的历史反算名（`kind_from_grade`）。

```
conjecture        = 没有证据
strong_conjecture = 有普通数值实验支撑（原 cross_check）
pre_theorem       = 有 V 签、但不是机器可核（原 proof_review）
theorem           = V 签 ∧ 机器可核（Lean 形式化 或 穷举证书，两者同级）← 原 proof
```

「可引」也读等级：`depsection.CITATION_MIN_LEVEL = "pre_theorem"`（有 V 签）。
`statements.evidence_kind` 只作历史列保留；任何写它的地方都必须走
`evidencebits.kind_from_grade(等级)` 反算，不许有第二套真值。旧的双轴结论见 §6。

## 1. 两套词表（逐字从代码取）

| 轴 | 常量 | 落点 | 取值（逐字） | 序 | 谁产出 |
|---|---|---|---|---|---|
| **等级** | `GRADES` | `evidencebits.py` | `conjecture` / `strong_conjecture` / `pre_theorem` / `theorem` | 由弱到强 | 只有 `evidencebits.derive_grade` 一处；任何角色自报的等级都不认 —— 行上 `bits.grade` 与现算不一致时，`bit_problems` 报缺陷 |
| 等级（不参与链） | `GRADE_NOT_APPLICABLE` | `evidencebits.py` | `not_applicable` | 刻意不在 `GRADES` 里 | 同上，`kind="concept"` 短路那一支 |
| **档位（历史）** | `EVIDENCE_KINDS` | `schema.py` | `proof` / `proof_review` / `cross_check` / `heuristic` | 由强到弱 | 只由等级反算：`evidencebits.kind_from_grade` / `kind_from_bits`（映射表 `GRADE_TO_KIND`）。改前那三处"提交方声明 / 秘书升档 / V 落签按通道给档"随本次改造退场（§6 历史；`register_statement` 与 `secretary` 那两处由另一条 lane 接手，见 §7.2） |
| 档位（实验表那一档） | `EXPERIMENT_EVIDENCE_KINDS` | `schema.py` | `proof` / `cross_check` / `heuristic`（少 `proof_review`） | 同上 | `experiments` 表专用：一次实验没有"逐行审阅过的证明"这一档。**它不在本文件的"命题等级"坐标里** —— 改实验档位是另一条轴的事 |

三条容易读错的地方，逐条钉住：

1. **两套词表不相交**：`set(GRADES) | {GRADE_NOT_APPLICABLE}` 与 `set(EVIDENCE_KINDS)`
   没有交集（判据 `test_two_vocabularies_do_not_overlap_and_the_gate_judges_the_grade`）。
   判定面只认等级：把历史档位词传进 `citation_level_allowed` 必须落空（判据的反向断言）。
2. **档位只能反算**：`GRADE_TO_KIND` 是唯一换算表（`conjecture→heuristic`、
   `strong_conjecture→cross_check`、`pre_theorem→proof_review`、`theorem→proof`）。
   `KIND_TO_GRADE` 是它的逆，**只用于读数 / 审计**，绝不参与 `derive_grade`。
3. **`theorem` 的两个机器通道同级**：`proof ∧ formal=verified`（Lean）**或**
   `proof ∧ numeric=verified`（穷举证书）。业主 2026-11-05 逐字：「穷举证书相当于
   lean 形式化，表示绝对正确」。`numeric` 不是"随便一个数值实验"：位上的凭据必须指向
   一条 V 签下的穷举行（`numericproof.is_signed_exhaustion` 口径）。

## 2. 五元位（五位、取值域、判等级时各读什么）

| # | 位 | 取值域（逐字从代码取） | 常量 / 读口 | `derive_grade` 读它吗 | 赋权所有者 |
|---|---|---|---|---|---|
| 1 | `numeric` | `pending` / `na` / `failed` / `verified`（`BIT_STATES`） | `_state` → `_bit_state` | 读：`verified` 与第 4 位同级，配第 2 位 ⇒ `theorem`；否则只抬到 `strong_conjecture` | E |
| 2 | `proof` | `bool` | `bits_of` 收窄成 `bool(proof) or cited or bool(proof_process)` | 读（`bool`） | F |
| 3 | `reviewed` | `bool`（凭什么另有三态 `reviewed_source`：`v` / `citation` / 空） | `bits_of` | 读：配第 2 位 ⇒ `pre_theorem` | V（引用命题是"引用"） |
| 4 | `formal` | **二维** `{证明号: 状态}`；逐路径五态 `pending` / `na` / `failed` / `verified` / `stale`；标量也收 | `_bit_value` → `_bit_state` 的 OR（任一 `verified` 即算过） | 读汇总那一层：配第 2 位 ⇒ `theorem` | L |
| 5 | `audited` | `bool` | `bits_of`；落点是并列的 `audited_badge` | **不读**（§3.3） | H |

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
| 02 | verified | true | true | pending | true | theorem | true |
| 03 | verified | true | true | pending | false | theorem | false |
| 04 | verified | true | false | verified | true | theorem | true |
| 05 | verified | true | false | verified | false | theorem | false |
| 06 | verified | true | false | pending | true | theorem | true |
| 07 | verified | true | false | pending | false | theorem | false |
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

- 判定的优先级：概念短路 → 作废短路 → `proof ∧ (formal ∨ numeric)` → `proof ∧ reviewed`
  → `numeric` → 兜底 `conjecture`（`derive_grade`）。
- `proof` 是进入前两档的门票。两条机器通道（`formal` 与 `numeric`）**同级**：拿
  `proof ∧ numeric` 的 #02/#03/#06/#07 与拿 `proof ∧ formal` 的 #00/#04/#16/#20 一样到
  `theorem`；`reviewed` 在机器通道已在时不改变结果（#00/#04），它单独配 `proof` 只到
  `pre_theorem`（#18/#19）。
- 上下两半只差第 1 位（#00-#15 是 `numeric=verified`，#16-#31 是 `pending`）。
  第 1 位现在有两个作用：没有第 2 位时它只抬到 `strong_conjecture`（#08-#15）；
  有第 2 位时它与第 4 位同级把等级推到 `theorem`（#02/#03/#06/#07）。
- `theorem` 那一档**不要求**第 3 位（#04/#05/#20/#21 也是 `theorem`）：V 签与机器核验
  是两条并列凭据，名字只要求后者。

### 3.2 短路与不可达（32 组之外的两个总开关，以及表内两处"同样本"）

- **概念行短路**：`derive_grade(bits, kind="concept")` 第一句就返回 `not_applicable`，
  32 组无论填什么都不参与 —— 表一**不覆盖**这一支，单列在此。
- **作废行短路**：`bits.voided_by` 非空 ⇒ 一律 `conjecture`，同样压过 32 组。
- 表内**没有**不可达的组合：32 组都由 `bits_of` 造得出来（`bits_of` 对五位各自独立收值）。
- 两处"同样本"要说清：`audited` 翻转**从不**改变等级（32 组里 0 处不同）；
  `numeric` 的四态里 `pending` / `na` / `failed` 在等级上**完全等价**（只有 `verified`
  参与派生）。

### 3.3 第 5 位落在哪：`audited_badge`，不是等级

`derive_grade` 一个字节都不读 `audited`（判据
`test_table1_is_a_function_of_bits_but_ignores_audited` 用 16 对对照把它钉住）。
第 5 位的落点是 `bits["audited_badge"]`：`audited` 为真**且**等级不是
`conjecture` / `not_applicable` 时才为真。所以表一里 `audited=true` 而
`audited_badge=false` 的那些格（#22-#31）不是矛盾 —— 那是"审过了，但这一条还不够到能被
追加标记"。

## 4. 表二：五元位状态 ⇒ `signed` ＋ 档位反算名

**结论先行：档位是等级的反算名，等级是五元位的函数。** 下面 32 格最后一列是
`evidencebits.kind_from_bits` 的真输出（先 `derive_grade`、再 `kind_from_grade`），
`#05` 之后与表一的等级列一一对应。

<!-- TWO-AXES:TABLE2:BEGIN -->
| # | numeric | proof | reviewed | formal | audited | `signed`（五元位唯一能决定的那一格） | 档位（= 等级反算名） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00 | verified | true | true | verified | true | true | proof |
| 01 | verified | true | true | verified | false | true | proof |
| 02 | verified | true | true | pending | true | true | proof |
| 03 | verified | true | true | pending | false | true | proof |
| 04 | verified | true | false | verified | true | false | proof |
| 05 | verified | true | false | verified | false | false | proof |
| 06 | verified | true | false | pending | true | false | proof |
| 07 | verified | true | false | pending | false | false | proof |
| 08 | verified | false | true | verified | true | false | cross_check |
| 09 | verified | false | true | verified | false | false | cross_check |
| 10 | verified | false | true | pending | true | false | cross_check |
| 11 | verified | false | true | pending | false | false | cross_check |
| 12 | verified | false | false | verified | true | false | cross_check |
| 13 | verified | false | false | verified | false | false | cross_check |
| 14 | verified | false | false | pending | true | false | cross_check |
| 15 | verified | false | false | pending | false | false | cross_check |
| 16 | pending | true | true | verified | true | true | proof |
| 17 | pending | true | true | verified | false | true | proof |
| 18 | pending | true | true | pending | true | true | proof_review |
| 19 | pending | true | true | pending | false | true | proof_review |
| 20 | pending | true | false | verified | true | false | proof |
| 21 | pending | true | false | verified | false | false | proof |
| 22 | pending | true | false | pending | true | false | heuristic |
| 23 | pending | true | false | pending | false | false | heuristic |
| 24 | pending | false | true | verified | true | false | heuristic |
| 25 | pending | false | true | verified | false | false | heuristic |
| 26 | pending | false | true | pending | true | false | heuristic |
| 27 | pending | false | true | pending | false | false | heuristic |
| 28 | pending | false | false | verified | true | false | heuristic |
| 29 | pending | false | false | verified | false | false | heuristic |
| 30 | pending | false | false | pending | true | false | heuristic |
| 31 | pending | false | false | pending | false | false | heuristic |
<!-- TWO-AXES:TABLE2:END -->

### 4.1 这张表钉的三件事

1. 档位不再有第二个来源：`evidence_kind` 的每一个合法值都必须是某一级的反算名
   （判据 `test_legacy_kind_is_a_function_of_the_grade` 32 组逐格核
   `kind_from_grade(derive_grade(bits)) == kind_from_bits(bits)`）。
2. `signed` 那一列仍是秘书的读数（`secretary._manuscript_upgrade_basis`，那条 lane 未动）：
   "五元位能证明这一行有 V 签"不等于"它该报哪一档"——后者现在由等级反算，不由 `want`
   决定。
3. 反真空：`kind_from_grade` 对认不出的等级返回空串（"反算不出来就不写"），
   `kind_from_bits(…, kind="concept")` 也是空串 —— 概念没有档位可言。

## 5. 表三：等级 × 历史档位（存量审计横表）

两张现场横表：**真机**（全部工作区，频次快照）与**夹具**（`paper_rewrite_86` 那一份
逐行快照）。等级那一列全部由 `derive_grade` 现算（行上 `bits.grade` 只是缓存，不读它）。
**这两张表是审计读数**：历史档位与现算等级对不上的行，就是"重刷会让它动"的行。

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

### 5.3 怎么读这两张表（存量 362 条非概念行 / 169 条不一致）

- 非概念行 362 条；历史档位与"按五元位现算的等级反算名"对不上，有两种读数
  （当时的一次性探针 `temp/grade_audit.py` 已不在盘上（`temp/` 不入库），两种口径见下）：
  - **存量口径**（第 2 位按 `proof_text` 非空读、不做读侧降档）：**169 条** =
    `cross_check→heuristic` 106、`cross_check→proof_review` 30、
    `heuristic→proof_review` 25、`proof_review→heuristic` 6、
    `proof→heuristic` 1、`proof→proof_review` 1。业主 2026-11-05 当晚的基线也是
    **169 条**（105 / 31 / 25 / 6 / 1 / 1）——只有 `cross_check` 那一行的 `reviewed`
    位在两次读数之间变过（77 工作区 / 362 非概念行逐字相同，是盘上数据漂移，不是口径漂移）。
  - **严格口径**（`bits_from_row`：占位签 / 过期签 / 过期形式化一律压下来）：**168 条** =
    `cross_check→heuristic` 132、`heuristic→proof_review` 23、`proof_review→heuristic` 7、
    `cross_check→proof_review` 4、`proof→heuristic` 1、`proof→proof_review` 1。
- **重刷会让 106 条降档**（存量口径）：这 106 条历史写着 `cross_check`（自报"有数值
  交叉验证"），而五元位里没有任何证据（`numeric` 不是 `verified`），现算等级只是
  `conjecture` ⇒ 反算名 `heuristic`。这是纠虚报，不是把真结果降级：原来的
  `cross_check` 是写入方声明的，不是证据给的。同一性质还有 `proof_review→heuristic` 6 条、
  `proof→heuristic` 1 条、`proof→proof_review` 1 条（合计 114 条降档；业主基线 105 那条
  `cross_check` 的差 1 同上）。严格口径下这一格是 132 + 7 + 1 + 1 = 141 条。
- 反方向 55 条是"等级比历史档位更强"（`cross_check→proof_review` 30、
  `heuristic→proof_review` 25、`proof→proof_review` 1）：这些行的五元位有
  `proof ∧ reviewed`，历史列只是没跟上 —— 重刷会把它们抬到 `pre_theorem`
  （严格口径下升档 27 条：23 + 4）。
- 表里 `strong_conjecture` / `theorem` 两列全 0，因为现场没有任何一行的第 1 位是
  `verified`、也没有任何一行的第 4 位是 `verified`（Lean 侧全关；`formal` 这一格在
  3,627 行里只出现过 `pending` 与 `null`，二维的 `{证明号: 状态}` 一次都没落过盘）。
  这不是表没算，是现场确实没有 —— 本改造的 `theorem` 两个入口都还没有存量可用。

### 5.4 存量漂移的现场样本（逐格可由快照复核）

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

读法（这些样本现在证明的是"历史列不可信"，不再是"两个轴"）：

- **A 组（同五元位、不同历史档位）**：`R-mk-infinite-90/000013` 与 `/000014` 的五元位
  **逐字相同**，历史档位却是 `proof_review` 与 `heuristic` ⇒ 历史列不是五元位的函数；
  现在两者现算等级都是 `pre_theorem`、反算名都是 `proof_review`（重刷后一致）。
- **B 组（同历史档位、不同等级）**：`heuristic` 这一档上，`/000003` 是
  `not_applicable`（概念行）、`/000018` 是 `conjecture`、`/000014` 是 `pre_theorem`
  ⇒ 历史列读不出等级，判定面必须现算。
- **C 组（历史档位写着 `proof_review`、五元位却只到 `conjecture`）**：
  `ramsey-4-4-87/000001` 与 `mp3-r3/000000` 的历史档位"够格被引"，而现算等级是
  `conjecture` ⇒ 按新门槛（读 `pre_theorem`）它们会被拒引。这正是"判定面读等级"要的：
  自报档位不再换来引用学分。

## 6. 历史：2026-11-05 之前是「两个轴」

这一段**刻意保留**，不许删：这次改造是**语义变更**，不是"原来写错了"。

- 改造前：`「可引」读档位（evidence_kind）；「多硬」读等级（grade）。两者不是同一个轴，
  谁也替不了谁`。档位由提交方声明（`register_statement(evidence_kind=…)`）、秘书在重交
  时按 `want` 升档、V 落签时按证明通道给档；等级只由 `derive_grade` 现算。
- 当晚真机读数：**362 条非概念行里 169 条不一致**（105 / 31 / 25 / 6 / 1 / 1），
  且"可引"门槛 `proof_review` 读的是历史列 ⇒ 一批 `proof_review` 行等级只有
  `conjecture`，照样拿到引用学分。
- 业主 2026-11-05 裁定（逐字）：
  「cross_check等价于强猜想等价于有普通数值实验支撑的猜想（这很坏，为啥要叫cross_check）。
   不妨就用等级制平替掉」＋「穷举证书相当于lean形式化，表示绝对正确」。
- 改造后（本文件 §0–§5）：等级是唯一的轴；`evidence_kind` 只作历史列保留，判定面一律读
  等级；穷举证书与 Lean 同级。重刷的存量分布见 §5.3。

## 7. 术语校准（旧称 → 新称）

### 7.1 本次已改准的读数口径

| 落点 | 改前 | 改后 |
|---|---|---|
| `depsection.CITATION_MIN_LEVEL` | `"proof_review"`（读 `evidence_kind`） | `"pre_theorem"`（读现算等级） |
| `depsection.citation_levels()` | 从 `EVIDENCE_KINDS`/`_EVIDENCE_ORDER` 切档位 | 从 `EB.GRADES` 切等级；只核对 `LEGACY_KINDS` 与 `EVIDENCE_KINDS` 互逆 |
| `depsection.gate_rows` / `wash_dependency_section` | 读 `anchor["evidence_kind"]` | 读 `statement_grade(anchor)`（`bits_from_row` 现算） |
| `agent_f/manuscript.citable_statements` | 列 `evidence_kind >= proof_review` | 列现算等级 `>= pre_theorem`，提示词行写 `grade=` |
| `verifications._grade_recomputed_from_signature` | 按通道给目标档、写 `evidence_kind` | 只算等级、不写档位（读数带 `to`/`to_kind`/`basis`） |
| `verifications.weaker_than_evidence_gaps` | 读档位在 `(heuristic, cross_check)` | 读现算等级在 `(conjecture, strong_conjecture)` |
| `closing`（`own_hole` / `load_bearing`） | `evidence_kind == "proof"` | 现算等级 `== "theorem"` |

### 7.2 逐处登记（已改 / 未改分开写）

| 类别 | 落点 | 处置（已改 / 为什么不动） |
|---|---|---|
| 本次已改 | `evidencebits.py` / `depsection.py` / `verifications.py` / `agent_f/manuscript.py` / `closing.py` / 本文件 / `tests/test_two_axes_grade_and_kind.py` / `tests/_two_axes.py` / `tests/test_evidence_bits.py` / `tests/test_grade_is_the_only_axis.py` | 见 §7.1 与提交记录 |
| **另一条 lane 独占** | `agent_b/register_statement.py`、`secretary.py` | 2026-11-05 分工变更：那条 lane 正在修 D2（稿头号 vs 登记号错位），这两份归它独占。**"提交方声明档位退场"（`evidence_kind=` 形参一进来就被覆盖成派生值 + 回执写明"档位是派生的"）与 `secretary._upgrade_evidence_kind` 改成"档位=等级（派生）"这两项后延**，等 D2 落地后由父代理另派。本文件 §1 那一格已按目标语义写着（"只由等级反算"），代码落地前它是一句待办 |
| 运行期文案（报告 / 拒信） | `agent_e/*`、`exhaustionreport.py`、`doc_tools.py`、`claimanatomy.py` 等 | 不改：它们说的是**实验/文档断言**那一档（`EXPERIMENT_EVIDENCE_KINDS`、`claimanatomy` 的 `status × evidence_kind`），不是命题等级。把它读成"要改"就会串轴 |
| FC-27 禁改区（要 2 名 reviewer） | `schema.py`、`store.py`、`verify.py`、`tools/verify_tools.py` | 不碰：`schema` 不删列（本次只让判定面不再读它）；`verify.py` 的 `weaker_than_evidence_gaps` 调用仍然拿 warning，判据本体已改读等级 |
| 提示词 / 技能文本（进提示词缓存） | `agent_prompts.py`、`agent_skills.py`、`specs/m.py` | 按纪律不动（下一版 p243 统一批） |
| 名字本身（代码标识符） | `_grade_recomputed_from_signature`、`recompute_grades`、`GRADE_BACKFILL_COLUMNS`、CLI `recompute-grades` 等 | 不改名：改名会动导入面 / CLI 子命令 / golden；本文件只登记 |

## 8. 复跑与刷新

```bash
# 五张表（+ 两张附表）的原文：整段粘回本文件的标记块之间
python -X utf8 tests/_two_axes.py

# 判据（逐格比对 + 三条反真空 + 历史段）
python -m pytest -q tests/test_two_axes_grade_and_kind.py

# 只读存量审计（不写 projects/）：历史档位 vs 现算等级的 169/168 分布与降档清单
# ⚠️ 这一段当时跑的是 `temp/grade_audit.py` —— 一次性探针随 `temp/` 不入库，现盘上已不在
# （2026-11-21 CLEAN-ALIGN 复算 `Test-Path temp/grade_audit.py` = False）。169/168 是**当次读数**，
# 不是可复跑的判据；现行口径只认下面两条命令。

# 刷新现场快照（`projects/` 被 .gitignore 排除，判据读的是这份快照）
python -X utf8 tests/_two_axes.py --refresh-scene
```

快照里带 `captured_at` 与 `command`：它是**带日期的读数**，不是"永远正确"的口径。
新增工作区之后重跑上面最后一条命令、把 `tests/fixtures/two_axes_scene.json` 的 diff
看一眼，本文件的表会跟着红一次（这正是"表过期 ⇒ 红"该有的样子）。
