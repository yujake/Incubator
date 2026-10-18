# 研究手稿：W*(F_k) 与 W*(F_m)（k≠m）同构问题——已知事实、方法层结论、数值读数与缺口

- 稿件代号：`doc:000000`；类型：`note`；状态：`revised`（本版按 H 的 finding 000001 把 claim-9 与第 5 节的判定口径改写为与盘上脚本 `scripts/conj000000_verdict_gate.py` 逐字一致，并删除脚本中不存在的 `estimator_not_qualified` 一档；按 finding 000002 把 claim-2 的「性质 Gamma」改为包内无逐字陈述、不作断言；本轮（verify_fixes round=5 的事后复核）再按 finding 000000 与 finding 000002 两类未决问题做最小修法：3.1–3.5 各节补成连贯散文正文，每段说明该节讲什么、依据是哪几行台账；claim-2 的 Gamma 一句改写为显式标注「证据包内无逐字支撑、不作为已知事实」的元陈述，并说明为什么不能作为分离 k 的依据）
- 断言数：11（正文主结果区 11、**已作废 0（在附录 A，不在正文）**、移入 open 0）；依赖数：4（`dep:000000`–`dep:000003`，全 `closed`，对应 `lit:000000`/`lit:000001`/`lit:000003`/`lit:000004`）
- 本文件：`documents/note-fk-fm-research.md`（按 `documents.claims` / `documents.sections` 当前数据行重画）
- 本会话形式化通道关闭（Lean 已关闭）⇒ 全文没有任何 `proof` 档断言；最高档为 `cross_check`，其下为 `heuristic`

## 0. 阅读须知

1. **每条断言都带引用**（`citations`，形如 `rel:<id>` / `lit:<id>` / `exp:<id>` / `eval:<id>` / `doc:<id>` / `stmt:<id>`）。
   没有引用的断言在结构上无法进入本稿（`schema.Document.validate` 强制）。
2. 证据等级共 4 档，且**必须分列**：`proof`（形式化核验）、`proof_review`（逐行审阅）、`cross_check`（交叉验证）、`heuristic`（启发式）。
3. **`cross_check` 不是证明**：这类断言后面自动附「数值交叉验证，不构成证明」；
   `proof_review` 那一档同样自带「逐行审阅过的证明，未经机器检查」—— 两条声明各写在自己那一栏里。
4. 否定型结论分四类：未证明 / 已证否 / 未搜索 / 无本地证据 —— 它们的含义完全不同，
   合并计数会让人把「没搜过」读成「已证否」。

## 1. 证据等级统计（分档计数，不是单一通过率）

| 证据等级 | 含义 | 条数 |
|---|---|---|
| `proof` | 形式化核验 | 0 |
| `proof_review` | 逐行审阅 | 0 |
| `cross_check` | 交叉验证 | 7 |
| `heuristic` | 启发式 | 4 |

说明：一个「通过率」会掩盖「另外那一部分到底是失败还是没校验」这个决定性差异，因此这里**只报分档计数**（FC-10）。

## 2. 否定型结论分类（未证明 / 已证否 / 未搜索 必须分开）

| 分类 | 含义 | 条数 |
|---|---|---|
| `disproved`（已证否） | 见 schema.NEGATION_KINDS | 2 |
| `not_proved`（未证明） | 见 schema.NEGATION_KINDS | 1 |
| `not_searched_here`（未搜索） | 见 schema.NEGATION_KINDS | 0 |
| `no_local_evidence`（无本地证据） | 见 schema.NEGATION_KINDS | 0 |
| （非否定型断言） | 本表不计入 | 8 |

说明：「未证明」与「已证否」在数学上有天壤之别；检索上「库里没有」与「这世上没有」也是两件事（FC-25）。

## 3. 断言清单（每条带引用）

### 3.1 定义与已知

本节交代问题所在的对象与已知事实的边界：W*(F_k) 是自由群 F_k 的自由生成元生成的 II_1 因子，Dykema 的内插自由群因子族 L(F_t) 在 t 取整数时含全部 W*(F_k)（`lit:000000`），Popa–Shlyakhtenko 说明族中每个成员都同构于某个真群因子（`lit:000001`）。本节同时立两条口径边界：性质 Gamma 一项在本趟证据包内没有逐字陈述，故本稿不对它作数学断言（见 claim-2）；微态自由熵维数 δ_0 只对特定生成元元组有定义，不能当成因子的不变量来用（见 claim-3，依据 `lit:000003`、`lit:000004`）。本节不含关于 k≠m 时两个因子是否同构的任何结论。

**`claim-1`**｜证据等级 `cross_check`｜引用：`lit:000000`、`lit:000001`

W*(F_k)（k=2,…,∞）是自由群 F_k 的自由生成元生成的 II_1 因子；Dykema 的内插自由群因子族 L(F_t)（1<t≤∞）在 t 取整数时含全部 W*(F_k)，且按 Popa–Shlyakhtenko 的结果，族中每个成员都同构于某个真群因子。

> ⚠️ 数值交叉验证，不构成证明

**`claim-2`**｜证据等级 `cross_check`｜引用：`lit:000000`、`lit:000001`、`lit:000003`、`lit:000004`

W*(F_k) 是 II_1 因子（自由群因子），这一点按 lit:000000 与 lit:000001 转引；性质 Gamma 一项在本趟证据包内无逐字支撑：statements 台账里没有任何关于性质 Gamma 的命题行（现有 stmt:000000、stmt:000001 均涉自由熵维数），所挂 lit:000003/lit:000004 的题名与摘要也只涉 free entropy dimension，没有能分离 k 的逐字陈述。因此本条明确标注为元陈述：证据包内无逐字支撑、不作为已知事实；本稿不就性质 Gamma 作任何数学断言，也不以它为分离 k 或判定 W*(F_k) 与 W*(F_m)（k≠m）不同构的依据。

> ⚠️ 数值交叉验证，不构成证明

**`claim-3`**｜证据等级 `cross_check`｜引用：`lit:000003`、`lit:000004`

微态自由熵维数 δ_0 只对特定的生成元元组有定义，它是否只依赖因子本身在本趟没有落点；因此不能把 δ_0 在标准自由生成元上取 k 这一陈述当作因子的不变量来用，也不得由它推出 k≠m 时两个因子不同构。

> ⚠️ 数值交叉验证，不构成证明

**`claim-10`**｜证据等级 `heuristic`｜引用：`lit:000011`

文献行 lit:000011（Jung–Shlyakhtenko，J. Noncommutative Geometry 1 (2007)，DOI 10.4171/jncg/7）的题名为『Any generating set of an arbitrary property T von Neumann algebra has free entropy dimension ≤ 1』；按题名所述，任意性质 T 的 von Neumann 代数的任意生成元集上自由熵维数 ≤ 1，且不依赖生成元选取。全文未落盘（download.status=skipped，no_local_path），逐字引文未核；本条只转述题名层面的内容，不含关于自由群因子 W*(F_k) 的任何结论。

**`claim-11`**｜证据等级 `heuristic`｜引用：`lit:000012`

文献行 lit:000012（Shlyakhtenko，Analysis & PDE 2 (2009)，DOI 10.2140/apde.2009.2.119）的题名为『Lower estimates on microstates free entropy dimension』；按题名所述，该文给出微态自由熵维数的下界估计（生成元层面的估计工具）。全文未落盘（download.status=skipped，no_local_path），逐字引文未核；本条只转述题名层面的内容，不含关于自由群因子 W*(F_k) 的任何结论。

### 3.2 已知事实台账

本节逐条登记 statements 台账里已入库的命题，它们是本稿唯一可引的「已登记事实」来源。目前只有两行：`stmt:000000`（出处 `lit:000004`，Shlyakhtenko 2006 Lemma 6，逐字片段 quote_verified=true，内容是 δ_0=δ=δ*=δ⋆=k，且其生成元无关性只在同一复群代数 C F_k 内成立，不是 von Neumann 代数不变量）与 `stmt:000001`（出处 `lit:000009`，Mineyev–Shlyakhtenko 2005，内容是 δ*=δ⋆=β1−β0+1，取 G=F_k 得 δ*=δ⋆=k）。两行都只涉自由熵维数，都不涉及性质 Gamma，也不给出因子同构或不同构的判据；本节因此只作转引，不由此推出任何因子层面的结论。

**`claim-7`**｜证据等级 `cross_check`｜引用：`stmt:000000`、`lit:000004`

台账行 stmt:000000（出处 lit:000004，Shlyakhtenko 2006 Lemma 6，框架第 7 页，逐字片段 quote_verified=true）：设 k≥1、F_k 为秩 k 自由群、X_1,…,X_n 为复群代数 C F_k 的任意一组代数生成元（不求自伴），则 δ_0(X_1,…,X_n)=δ(X_1,…,X_n)=δ_*(X_1,…,X_n)=δ⋆(X_1,…,X_n)=k，即 δ_0=δ=δ*=δ⋆=k；取标准自由生成元 u_1,…,u_k 即得 δ_0(u_1,…,u_k)=k。该行明确不断言 δ_0 是 von Neumann 代数不变量：其生成元无关性只在同一个 C F_k 内的不同生成元组之间成立（原文引 [10] 说明 δ_0 是代数不变量）。

> ⚠️ 数值交叉验证，不构成证明

**`claim-8`**｜证据等级 `cross_check`｜引用：`stmt:000001`、`lit:000009`

台账行 stmt:000001（出处 lit:000009，Mineyev–Shlyakhtenko 2005 主结果，框架第 2 页，逐字片段 quote_verified=true）：对任意有限生成离散群 G 与任意自伴生成 n-元组 X_1,…,X_n ∈ CG（作为代数生成 CG），有 δ*(X_1,…,X_n)=δ⋆(X_1,…,X_n)=β1(G)−β0(G)+1；取 G=F_k 时 β1=k、β0=1，故 δ*=δ⋆=k。该行只涉及非微态维数 δ*、δ⋆，不涉及 δ_0，也不断言 δ_0 的因子不变性。

> ⚠️ 数值交叉验证，不构成证明

### 3.3 尝试与失败

本节记录本趟真正做过、并且有落点的尝试，以及它们各自卡在哪里。第一件是我们自己的估计器口径：`exp:000001` 判为 refutes，原因是采样器口径不一致（脚本抽「恰好 N 个字母、字母表均匀」，却去比「长度≤N 约化词」的计数）；改用修正采样器后 `exp:000003` 的读数自洽，但自洽只说明执行器内部一致，不构成对猜想的支持。第二件是字面微态体积口径：其在 N∈{8,16,32,64} 上不可行（量级 μ_N(B_r)≈r^{kN²}，k=2、N=16、r=2⁻⁸ 时约 e⁻²⁸³⁹），代理量 δ_N=ln V_N/ln N 随 N 发散、已由 F 判定作废。两件都属于方法层结论，不是关于 W*(F_k) 的数学结论。

**`claim-4`**｜证据等级 `cross_check`｜引用：`exp:000001`、`exp:000003`

我们自己的估计器口径被本趟的数值实验反驳：exp:000001 判为 refutes，原因是采样器口径不一致（脚本抽『恰好 N 个字母、字母表均匀』却去比『长度≤N 约化词』的计数）；改用修正采样器后 exp:000003 读数自洽，但自洽只说明执行器内部一致，不构成对猜想的支持。

> ⚠️ 数值交叉验证，不构成证明

- 否定分类：`disproved`（已证否）
- 台账字段 `numeric_evidence`（据 exp:000001 行）：script=`code/f_conj000000_delta_repro.py`；range=k∈{2,3,4}、N∈{8,16,32,64}，共 12 格，M≤200000，seed=102008，与闭式精确计数逐格比对，判据 rel_err≤0.1；n_cases=12；n_counterexamples=1

### 3.4 例子与反例

本节记录本趟唯一的有限截断数值反例，并说明它到底反驳了什么。 `exp:000000` 的 counterexample 字段：route B（Haar 随机置换矩阵求和的实部谱）、n=64、k∈{2,8} 的标准化自由累积量差约 1.94、合并标准误约 0.0344、比值约 56.34 —— 它反驳的是「截断矩与 k 无关」这一读法，而不是任何关于因子同构的命题。按 E→D 手稿 000002 的判读，矩/累积量按 −1/(2k) 区分 k 是归一化算术后果而非不变量，置换矩阵路线 k≥4 的「可区分」是有限 n 伪影；因此本条只作 heuristic 读数登记，不得升级为因子不同构的依据。本节的证据只有 `exp:000000` 一行。

**`claim-5`**｜证据等级 `heuristic`｜引用：`exp:000000`

exp:000000 以 refutes 记录：在 n=64、route B（Haar 随机置换矩阵求和的实部谱）下，k=2 与 k=8 的标准化自由累积量差约 1.94、合并标准误约 0.0344、比值约 56.34 —— 这反驳了『截断矩与 k 无关』这一读法；但这是启发式数值读数，按 E→D 手稿 000002 它属于归一化算术后果与有限 n 伪影，不得升级为因子不同构的依据。

- 否定分类：`disproved`（已证否）
- 台账字段 `numeric_evidence`（据 exp:000000 行）：script=`code/fk_truncation_moments.py`；range=route A（GUE）与 route B（Haar 置换矩阵实部谱）两条路线，k∈{2,3,4,8}、n∈{8,16,32,64}、前 6 阶矩与自由累积量，samples≤40，seed=20261018，读数取 n=64、route B、tag=k4_over_k2sq、pair=(2,8)、samples=12；n_cases=32；n_counterexamples=1

**`claim-9`**｜证据等级 `heuristic`｜引用：`lit:000003`、`lit:000004`、`exp:000001`、`exp:000003`

conjectures:000000 的判定形式（testable 字段）按盘上脚本 scripts/conj000000_verdict_gate.py 逐字转述：参数域 k∈{2,3,4}、m∈{3,4,5}（m≠k）、N∈{8,16,32,64} 且每个 N 固定一个确定性种子；判定入口只吃 --readings 的 JSON、出 --out 的 JSON，自身不产生任何数字。合格估计器闸门（GATE，脚本 docstring 第 19–23 行）为：Q1 不发散 —— 同 (k, estimator) 相邻档 N 与 2N 的均值比 |r−1| ≤ 0.15（常量 TOL_Q1 = 0.15）；Q2 种子可复现 —— 同 (k,N) 至少两个 seed，极差 ≤ 0.10（常量 TOL_Q2 = 0.10），一个 (k,N) 只有单 seed 记未测；Q3 量程 —— 每条读数 0 < delta_hat ≤ k（文档口径；脚本 gate() 的实现按 k×1.05 判界）；Q4 归一化不变（有数据才判）—— 同 (k,N,seed) 不同 normalization_scale 的极差 ≤ 0.10（常量 TOL_Q4 = 0.10）。gate 状态取 qualified / qualified_except_Q4 / disqualified 三种。分离判据：D1 单调（Δ_N 差序列在 N∈{8,16,32,64} 上逐步不低于 −0.05）、D2 外推（以 x=1/log N 做最小二乘，截距 Δ_∞ ≥ (m−k) 且 ≥ 1）、D3 硬反驳（N=32 与 N=64 两档 Δ 都 < 0.10，且 |Δ_64−Δ_32| < 0.05）。出口只有三档：supports / refutes / insufficient_data；gate 未通过（disqualified）时脚本把结论一律记 insufficient_data 并注明是缺合格估计器的结构性缺口，不得据此判猜想被反驳；脚本里没有 estimator_not_qualified 这一档。当前该猜想既无 supports 读数也无 refutes 读数，按脚本口径落在 insufficient_data（缺合格估计器），状态停在 proposed。本文所述的判定口径以盘上脚本 scripts/conj000000_verdict_gate.py 为准。

- 否定分类：`not_proved`（未证明）

### 3.5 未解问题与下一步

本节把本趟剩下的缺口按可攻性排开，并说明它们各自缺的是哪一类依据。主问题（2≤k<m≤∞ 时 W*(F_k) 与 W*(F_m) 是否同构）在本趟**没有结论**：本趟证据包内没有逐字支撑，检索请求 `r-000008` 仍在途；真正缺的一环是 δ_0 的因子不变性，本趟没有落点能判定它（`lit:000003`、`lit:000004` 只给出标准生成元元组上的取值，未给出因子层面的不变性）。其次，分离判据只写出了判据形式而没有任何读数，缺的是一个合格的 δ_N 估计器；判定口径与三档出口以盘上脚本 `scripts/conj000000_verdict_gate.py` 为准，当前该猜想既无 supports 读数也无 refutes 读数，落在 insufficient_data。再次，微态球 B_r 内的重要性采样/变分构造在本会话执行面上未接线，属结构性缺口而非算力问题。本节不含任何正面结论。

**`claim-6`**｜证据等级 `cross_check`｜引用：`lit:000003`、`lit:000004`

主问题（2≤k<m≤∞ 时 W*(F_k) 与 W*(F_m) 是否同构）在本趟没有结论：证据包内没有逐字支撑，检索请求 r-000008 仍在途；真正缺的一环是 δ_0 的因子不变性，本趟没有落点能判定它，因此有限 N 收敛率与微态球内的重要性采样构造成了仅剩的可攻方向。

> ⚠️ 数值交叉验证，不构成证明

## 4. 依赖（FC-23：引用的外部结论必须显式标记）

| 依赖代号 | kind | 标签 | 状态 | 来源 | 页码范围 | 未闭合原因 |
|---|---|---|---|---|---|---|
| `dep:000000` | prior_art | Dykema：内插自由群因子族 L(F_t)，t 取整数时含全部 W*(F_k)（claim-1） | closed | `lit:000000` | - | - |
| `dep:000001` | prior_art | Popa–Shlyakhtenko：族中每个成员同构于某个真群因子（claim-1） | closed | `lit:000001` | - | - |
| `dep:000002` | prior_art | Voiculescu/Shlyakhtenko：δ_0 在标准自由生成元元组上取 k（claim-2/3/6，一次源未核，仅转引） | closed | `lit:000003` | - | - |
| `dep:000003` | prior_art | Shlyakhtenko 2006 综述：同一 δ_0 陈述（claim-2/3/6，一次源未核，仅转引） | closed | `lit:000004` | - | - |

## 5. 未解决的问题

- 2≤k<m≤∞ 时 W*(F_k) 与 W*(F_m) 是否同构：证据包内无逐字支撑，检索 r-000008 在途
- δ_0 是否只依赖因子本身（因子不变性）：本趟无落点
- 有限 N 收敛率 δ_N(X_k) ≥ k − C/log N 中常数与 k 是否无关、取值多少：缺合格估计器
- 微态球 B_r 内的重要性采样/变分构造在本会话执行面上是否可行：未接线，交 E 判

## 附录 A. 已作废的断言（不在正文主结果区）

（无。本稿没有 `status='作废'` 的断言。）
