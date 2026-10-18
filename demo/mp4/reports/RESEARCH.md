# 研究手稿 — W*(F_k) 与 W*(F_m)（k≠m）是否同构

研究问题：`research_questions:000000`　猜想：`conjectures:000000`　攻坚计划：`attack_plans:000000`
证据包：`lit:000000`–`lit:000008`（A 已登记；本稿只引其中我实际读过元数据的那几行）
本稿状态：**没有证明，也没有反驳**。下面每一句声称都带落点；引不到落点的地方我写成「没有落点」。

> **2026-10-18 收口（D，台账号 t-000047）**：研究问题 `research_questions:000000` 终态 = **dropped**（不是 answered：主问句是文献公开问题，我们既无证明也无反例；也不是「没有这个问题」）。猜想 `conjectures:000000` 终态 = **needs_evidence**（依据 `exp:000010`：result=inconclusive、exit=0、code_path `code/conj000000_verdict_run.py`、code_hash 前16位 `299dd83f09401839`，确定性闸门 verdict=insufficient_data、gate=disqualified、reason=estimator_not_qualified；前一次 `exp:000009` 同向；**不是** supported_not_proved、**不是** refuted）。结构性缺口 = **缺一类合格估计器**（须过 GATE Q1–Q4：rel_se 随 N 单调不增且末档≤0.1、N=32→64 相对变化≤0.2、归一化尺度差≤0.05、可行档不足 2 档即 disqualify；候选类别：重要性采样 / 大偏差速率函数 / 矩约束计数的可计算替代量）。已提交检索请求 `r-000010`（topic: microstates free entropy dimension estimator），消费链：A 检索 → B 整理成关系行 → E 落地实现，D 只消费读数。本趟**未新增实验、未改 statements、未碰 out/paper/**。三档逐条（已判定 / 条件性 / 未判定）见 `reports/000000-research.md` 与 `research_questions:000000` 的 notes。参考文献里 Sierra-Walton 一类工作一律按**开放问题（known_in_literature / open）**记，不写成我们的结果。

## 1. 成果概述

- **登记了什么**：研究问题 `research_questions:000000`（问题：对 2≤k<m≤∞，W*(F_k) 与 W*(F_m) 是否同构）；猜想 `conjectures:000000`（statement：标准自由生成元元组 X_k 的有限截断微态熵维数估计 δ_N(X_k) 满足 δ_N ≥ k − C/log N，且 δ_N(X_m) − δ_N(X_k) 在 N→∞ 外推下 ≥ m−k；`testable` 给了 k∈{2,3,4}、m∈{3,4,5}、N∈{8,16,32,64}、种子与支持/反驳/数据不足三档判据）。落点：两张台账行本身。
- **证明了什么**：**没有**。本趟没有产生任何 `evidence_kind="proof"` 的落点（本会话形式化关闭，且 F 的计划也只到 supported_not_proved 档）。
- **证伪了什么**：**没有证伪数学命题**。被判定作废的是**我们自己的估计器**，不是文献命题：
  1. 字面微态球 Haar 体积口径在 N∈{8,16,32,64} 上**不可行**（量级 μ_N(B_r)≈r^{kN²}，k=2,N=16,r=2⁻⁸ 约 e⁻²⁸³⁹，M=2×10⁵ 一个命中都拿不到）—— 落点 `reports/attack-000000.md` §A5（F 的定量估计）。
  2. F 自写的代理量 δ_N = ln V_N/ln N（V_N = 长度≤N 约化词计数）**不是维数**（≈ N·ln(2k−1)/ln N 随 N 发散）⇒ 该口径作废 —— 落点 `reports/attack-000000.md`「轮 2–3」。
- **做了哪些数值实验**：
  - `experiments:000001`（result=refutes，归因是**采样器口径不一致**，不是计数公式被反驳）与 `experiments:000003`（修正采样器后 result=supports，**只说明执行器自洽**，不构成对猜想的支持）—— 依据行写在 `reports/attack-000000.md`「轮 2–3」，脚本 `scripts/f_conj000000_delta.py`。
  - `experiments:000000`（method=numeric，exit_code=0，code_path `code/fk_truncation_moments.py`，code_hash `e6cd75226694bd91`）：在 n≤64 的有限维截断上比较 k=2,3,4,8 的前 6 阶矩/自由累积量；该行的 `counterexample` 字段记录了 route B、n=64、k∈{2,8} 的差异（`ratio_diff_over_se`≈56.34），即该截断读数**可以区分**这两个 k。
  - E→D 手稿 `000002`：矩/自由累积量按 −1/(2k) 区分 k，是**归一化算术后果，不是不变量**；置换矩阵路线 k≥4 的「可区分」是有限 n 伪影；d1 型亏缺 k-盲。
- **本趟（D）补做的两件事**：① `conjectures:000000.testable` 补成可执行形式（参数域 / 脚本入口 `scripts/conj000000_verdict_gate.py` / GATE Q1–Q4 / 支持·反驳·数据不足三档出口）；② 攻坚计划第 4 轮由 F 按 (B) 出口收口（落点 `exp:000008`、手稿 `000021`）。**本趟没有新增任何数学结论**：既没证明也没反驳任何关于 W*(F_k) 的命题。
- **经验（写下来给下一次）**：① 先估量级再写脚本 —— 体积型口径在高维矩阵群上极易不可行，§A5 这种量级估计只要一行纸笔；② 一个「能跑通、自洽」的脚本不等于一个合格的估计器（`exp:000003` 就是反例）；③ 有限截断里「能区分 k」的读数必须先过一遍「它是不是归一化/有限 n 伪影」这一关（手稿 `000002`）。

## 2. 定义与已知

- **对象**：W*(F_k) 是自由群 F_k 的自由生成元生成的 II_1 因子（k=2..∞）。
- **内插族**：L(F_t)，1<t≤∞，由 `lit:000000`（Dykema 1994，Pacific J. Math. 163，"Interpolated free group factors"）引入；该族含全部 W*(F_k)（k 取整数时）。
- **族与邻近类的关系**：`lit:000001`（Popa–Shlyakhtenko 2020，Groups Geom. Dyn.，"Representing interpolated free group factors as group factors"）—— 每个内插自由群因子都同构于某个真群因子；`lit:000002`（Houdayer 2009，Math. Ann.，"Strongly solid group factors which are not interpolated free group factors"）—— 存在强固体 II_1 因子不在内插族内。这两条只界定族的位置，**都不回答族内不同 t 是否同构**。
- **候选分离量**：微态自由熵维数 δ_0（`lit:000003` Voiculescu 1999，Crelle；`lit:000004` Shlyakhtenko 2006 综述 "Remarks on Free Entropy Dimension"）。
- **口径红线（本稿全程遵守）**：
  - **II_1 因子性**与**性质 Gamma** 都**不能**分离 k —— 它们在所有 W*(F_k) 上同时成立（证据包内没有反例行，也没有能分离的逐字陈述）。
  - **δ_0 不是因子不变量**：它只对**特定的生成元元组**有定义；把 δ_0(W*(F_k))=k 写成「因子的不变量」是**越界**。文献里 δ(W*(F_k))=k 的地位是**猜想/陈述**，不是本趟的证明。

## 3. 已确定的结论

分三档（强弱不同，不许混）：

- **(a) 关于我们自己的估计器（强，有落点、可复核）**：字面微态体积口径在 N∈{8,16,32,64} 不可行；代理量 δ_N=ln V_N/ln N 不是维数、已作废。落点：`reports/attack-000000.md` §A5 与「轮 2–3」。这是**方法层**的确定结论，**不是**关于 W*(F_k) 的数学结论。
- **(b) 文献转引（cross_check 档，一次源未核）**：`lit:000004`（Shlyakhtenko 2006 综述）第 7 页 Lemma 6 逐字："Let X1, . . . , Xn be any generators of the group algebra of the free group Fk. Then δ0(X1, . . . , Xn) = … = k." —— matched=exact，但它是**综述里的引理、二次引用 Voiculescu IMRN 1998，一次源未核**；依据是 A→F 手稿 `000004`，以及 `reports/attack-000000.md`「轮 5 · 文献校准」。
  由此可得的**唯一**推论：猜想 `conjectures:000000` 的第 ② 条（外推极限差 ≥ m−k）**在标准生成元元组上已有发表陈述**，它不是本趟的新猜想。**不许**据此说「W*(F_k) 与 W*(F_m) 不同构」—— 缺的那一环是 δ_0 的**因子不变性**（见 §5）。
- **(c) 否定档（not_proved / no_local_evidence）**：
  - 「W*(F_k) ≇ W*(F_m)（k≠m）」在证据包 `lit:000000`–`lit:000008` 内**没有**逐字支撑 —— 判据 `not_proved`。
  - 「L(F_t) 族内不同 t 互不同构」在证据包内同样**没有**逐字结论 —— 判据 `no_local_evidence`；已提交检索请求 `r-000008`（topic: interpolated free group factors nonisomorphic，状态在途）。

## 4. 尝试与失败

逐条写清卡在哪一步、属哪一档：

1. **字面微态体积口径** —— 卡在**可行性**：量级估计 μ_N(B_r)≈r^{kN²} 使 MC 命中率 ~e⁻²⁸³⁹。档：**结构性**（不是算力问题，需要重要性采样/变分构造在 B_r 内直接生成微态，本会话未接线）。落点 `reports/attack-000000.md` §A5。
2. **代理量 δ_N=ln V_N/ln N** —— 卡在**口径**：该量随 N 发散，既不是维数也不落在 (0,k] 量级，用它检验 ① 恒真无意义、检验 ② 会把单调性读成平凡成立。档：**技术性/口径错**（F 自己判定，不是 E 判的）。落点「轮 2–3」。
3. **`exp:000001` 的 refutes** —— 卡在**采样器**：脚本抽「恰好 N 个字母、8 字母表均匀」却去比「长度≤N 约化词」计数。档：**反例不成立**（被反驳的是口径不一致，不是计数公式）—— 修正后 `exp:000003` 全部对上，但那只是自洽。落点「轮 2–3」+ 手稿 `000001`。
4. **分离判据（sg-c）** —— 只写出判据（D1 单调 / D2 外推 / D3 硬反驳 + 支持/反驳/数据不足三档出口），**没有读数**，因为缺一个合格的 δ_N 估计器。档：**结构性**（缺工具，不是缺算力）。落点「轮 4」。
5. **文献校准** —— 不是失败，是收窄：② 的极限部分进了文献，可攻的只剩「有限 N 收敛率里 C 与 k 无关」这一格。落点「轮 5」。
6. **「合格估计器」这一格（本趟，计划第 4 轮，F 执行）** —— 卡在**工具**，已按 (B) 出口收口：本会话执行面上不存在能过 GATE Q1–Q4 的 δ_N(X_k) 估计器。逐条被排除：E1 字面球体积（最有利格 k=2,N=8,r=2⁻⁴ 仍 ln p=−354.9 ⇒ 需 ~10¹⁵⁴ 样本，可行档 0/60）、E2 δ_N=ln V_N/ln N（相邻倍档比 1.50/1.60/1.667，破 Q1；N≥16 时 δ>k 破 Q3）、E3 矩/累积量缺陷（无 D_N→δ_N 的已证桥）、E4 重要性采样/变分采样器（本会话未接线）。档：**结构性**（缺工具，不是缺算力，也不是数据不足）。落点：手稿 `000021`、`reports/conj000000_infeasible_record.json`、脚本 `scripts/conj000000_infeasible_record.py`（`exp:000008`，其 `result` 落成 `inconclusive` 是因为脚本打印的 verdict 不在受控词表内 —— 格式不合规，不是结论被推翻）。

## 5. 例子与反例

- **E 送的料（不是 F 造的命题）**：`experiments:000000` 的 `counterexample` 字段记录：route B（Haar 随机置换矩阵求和的实部谱）、n=64、k∈{2,8} 的标准化自由累积量差异 `diff`≈1.94、合并标准误≈0.0344、`ratio_diff_over_se`≈56.34 ⇒ 该有限截断读数**能区分**这两个 k。
- **这个「反例」怎么读（关键）**：E→D 手稿 `000002` 明确：矩/累积量按 −1/(2k) 区分 k 是**归一化算术后果、不是不变量**；置换矩阵路线 k≥4 的「可区分」是**有限 n 伪影**；d1 型亏缺 k-盲。⇒ 任何「有限截断能区分 k」的读数，**都不得**升级成「W*(F_k) 与 W*(F_m) 不同构」的证据。这是本趟最值得记住的一条纪律。
- **反例侧的空缺（如实写）**：本趟**没有**任何落点记录「在有限截断下 δ_N 的 k-分离被判死」的实验 —— 即猜想 `conjectures:000000` 现在既没有支持读数也没有反驳读数，状态停在 `proposed`。

## 6. 未解问题

1. **主问题**：W*(F_k) ≇ W*(F_m)（k≠m）？现状：证据包内无逐字结论（`not_proved`）。检索 `r-000008` **已结束**，结果 `lit:000000`/`000001`/`000002`/`000010` 尚未被 B 消化（`research.poll_waiting` 读数：ready=0、waiting=1、state=`waiting_b`）⇒ 这一格不是「查不到」，是「查到了、还没整理进关系表」。
2. **缺的那一环**：δ_0 的 **von Neumann 代数不变性**（δ_0 是否只依赖代数而不依赖生成元元组）。手稿 `000004`/`000005` 都把这一条点成真正的未决处 —— 只有它成立，(b) 档那条转引才对因子同构问题有用。**本趟没有落点能判定它**。
3. **估计器缺口（本趟升级为结构性结论）**：F 第 4 轮按 (B) 出口收口 —— 本会话执行面上**不存在**能过 GATE Q1–Q4（`conjectures:000000.testable.gate_criteria`）的 δ_N(X_k) 估计器。落点：手稿 `000021`、`reports/conj000000_infeasible_record.json`、脚本 `scripts/conj000000_infeasible_record.py`（`exp:000008`；该行 `result=inconclusive`、`observations.conclusion_source=out_of_vocab` —— 意思是脚本打印的 verdict 不在受控词表内，落盘格式不合规，**不是**它的结论被数据推翻）。⇒ 「有限 N 收敛率 C 与 k 无关」这一格现在**连一个可读的数都没有**：这是**缺工具**，不是「数据不足」。
4. **工具缺口**：如何在微态球 B_r 内做重要性采样/变分构造（决定字面口径能否复活）；被排除的四条口径 E1–E4 与各自判据见手稿 `000021`。

## 7. 下一步

- **交给 B**：`r-000008` 已结束，结果 `lit:000000`/`000001`/`000002`/`000010` 尚未消化（`waiting_b`）⇒ 请把这四篇抽成概念/关系行（逐字引文），特别是**族内不同 t 是否同构**与 **δ_0 不变性**两处的逐字陈述。
- **交给 A（现在可以提了）**：在途闸门随 `r-000008` 结束已解除，可提交新的检索：① `microstate free entropy dimension convergence rate`（找可过 GATE 的估计器口径）；② `free entropy dimension invariance under isomorphism`（δ_0 不变性）；③ `importance sampling microstates free group factor`。topic 要短、英文。
- **交给 E**：判断「在 B_r 内做重要性采样/变分构造」在本会话的执行面上做不做得到；做不到就如实记为结构性缺口（不许伪造 δ_N 读数）。
- **交给 F**：`attack_plans:000000` 第 4 轮已由 F 按 (B) 出口收口（手稿 `000021`、`exp:000008`）：本会话无合格估计器 = 结构性缺口。**台账订正**：F 那一轮没有落进本行 `history`（`history_len` 仍 3），D 只把 `rounds` 由 3 订正为 4，未改写 history 原文 —— 下一趟不要以为第 4 轮没发生。**续攻前提**：先有能过 GATE 的估计器（见 §6 第 3 条），否则再开轮就是空转。
- **交给 A**：查 free group factor isomorphism problem 的**现状**（不是族的存在性），以及 δ_0 不变性的最新结果；topic 要短、英文。
- **给下一趟的提醒**：本稿 §3(b) 是**二次来源**，用之前先核一次源（Voiculescu IMRN 1998）；§5 那条「有限截断可区分 k」的读数**不许**当不变量证据。
