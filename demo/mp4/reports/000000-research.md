# 研究问题 000000 — 报告（收口版）

**问句**：对 2≤k<m≤∞（k≠m），W\*(F_k) 与 W\*(F_m) 是否同构？已知内插族 L(F_t), 1<t≤∞ 含全部 W\*(F_k)；族内不同 t 是否互不同构未定；II_1 因子性与性质 Gamma 均不能分离 k，自由熵维数 delta_0 并非因子不变量而依赖生成元元组。

**终态**：`dropped`（收口为「已知事实汇总 + 明确未决」，不是 answered；也不是「没有这个问题」）。
**收口依据**：exp:000010（result=inconclusive，确定性闸门 verdict=insufficient_data、gate=disqualified、reason=estimator_not_qualified）、exp:000009（同向 inconclusive）、手稿 000036（13 条 no_local_path 的终局读数）、statements 现有 2 条（stmt:000000、stmt:000001）、conjectures:000000。

> **口径（硬约束）**：Sierra-Walton 一类关于微态自由熵维数在矩阵维数趋于无穷时收敛速率 / 重要性采样的工作，在本报告里一律写成 **开放问题（known_in_literature / open）**，**不是**我们的结果；本报告任何一处都不主张我们解决或推进了那条公开问题。

---

## 一、已判定（直接由已落台账的确定性读数或逐字引文支撑）

1. **stmt:000000（Shlyakhtenko 2006, Lemma 6；lit:000004，框架第 7 页，quote_verified=true）**
   设 k≥1，X_1,…,X_n 为复群代数 C F_k 的**任意代数生成元组**，则 δ_0(X_1,…,X_n)=δ=δ_*=δ⋆=k。
   该行的 `proof_text` 原文明确：δ_0 的生成元无关性用的是「δ_0 是**代数不变量**」（同一代数 C F_k 内不同生成元组之间），**不是** von Neumann 代数不变量。⇒ 这条**不能**升级成「δ_0 分离 W\*(F_k) 的 k」。这是已判定的一条**否命题边界**。
2. **stmt:000001（Mineyev–Shlyakhtenko 2005 主定理；lit:000009，框架第 2 页，quote_verified=true）**
   对有限生成离散群 G 与任意自伴生成 n-元组 X_1,…,X_n ∈ CG，δ\*(X)=δ⋆(X)=β_1(G)−β_0(G)+1；取 G=F_k 得 δ\*=δ⋆=k。⇒ 非微态维数在群代数内与生成元选择无关（代数不变量）——同样是**代数**层面的结论，不跨因子同构。
3. **实验侧（确定性）**：exp:000010 与 exp:000009 均在 k∈{2,3,4}、m∈{3,4,5}、N∈{8,16,32,64}（cells_measured=7，seeds_per_cell=1）实跑，exit_code=0，result 均为 `inconclusive`；判定闸门 `scripts/conj000000_verdict_gate.py` 判 **verdict=insufficient_data、gate=disqualified、reason=estimator_not_qualified**。两次实验同形（界/策略/耗时未变），所以**重复同一脚本不会产生新信息**——这一点本身是已判定的。
4. **可行性档（确定性、可复算）**：字面微态球 Haar 体积口径在 N∈{8,16,32,64} 命中率低至 ~e^-2839 量级（exp:000010 observations 的 analytic precheck：k=2 时 N=16/32/64 的 p_exact 分别约 1.94e-6 / 2.52e-12 / 4.22e-24，expected_hits≪1）⇒ **该口径在给定参数域不可行**，不是「数据不够」。

## 二、条件性成立（只在明确写出的前提下成立，离开前提即不成立）

1. **「δ_0 在标准自由生成元元组层面把 k 分开」**：这**只是 conjecture 000000 的 ①/② 判据**，且**必须**先有一个通过 GATE Q1–Q4 的合格估计器；目前该前提**未满足**，故本条只能写成「若存在合格估计器，则按 GATE 三档出口判定」，**不构成任何数值结论**。
2. **「δ_0 可能与因子不变量有关」**：条件性成立——只有当「δ_0 关于 von Neumann 代数同构不变」被证明时，stmt:000000 才对自由群因子同构问题有用。该不变性在证据包内**无落点**（lit:000004 只给代数不变量口径）。
3. **手稿 000036 的终局读数**：lit:000004（Shlyakhtenko 2006）与 lit:000009（Mineyev–Shlyakhtenko 2005）本地全文 ok，可作逐字引文来源；其余 11 条为 `external_unavailable`（Dykema 1994、Popa–Shlyakhtenko 2020、Houdayer 2009、Voiculescu 1999、Popa 2007 ICM、Juschenko–Popovych 2011、Brown–Dykema–Jung 2008、Ge 1998、Dykema 2016、Jung–Shlyakhtenko 等）——**它们是「查到了但拿不到全文」**，不是「不存在」，也不是「无贡献」。

## 三、未判定（本会话内无落点，不许写成已解决）

1. **主问句本身**：W\*(F_k) ≅ W\*(F_m)（2≤k<m≤∞）？——**文献公开问题（known_in_literature / open）**。本会话形式化关闭（Lean 关闭、`evidence_kind="proof"` 产不出来），最高证据档只能到 cross_check / heuristic；我们既没有证明、也没有反例。
2. **δ_0 的 von Neumann 代数不变性**：无逐字落点、无独立论证。这是把 stmt:000000 与主问句之间的**唯一缺环**。
3. **合格估计器**：不存在。缺的**是哪一类**：需要对微态测度在 N→∞ 下 **(i) 归一化不变（GATE Q3）、(ii) 随 N 收敛（rel_se 随 N 单调不增且末档 ≤0.1，Q1）、(iii) N-标度稳定（N=32→64 相对变化 ≤0.2，Q2）、(iv) 参数域可行（不可行档 <2，Q4）** 的可计算 δ 估计器；候选方向（**开放问题**，非我们的结果）：重要性采样 / 大偏差速率函数式计数 / 矩型微态约束计数。
4. **Sierra-Walton 一类的收敛速率—重要性采样问题**：登记为 **known_in_literature / open**。我们**没有**该方向的本地全文（手稿 000036 的 external_unavailable 档），也**没有**任何自己的数值或证明贡献。

## 结论

本问题在证据包内**不能 answered**：核心缺环（δ_0 的因子不变性）与估计器缺口（合格 δ_N 估计器）都不是本会话工具面内能补的。因此收口为 `dropped`，并把两条缺口变成具体请求（检索 r-000010 由 A 消费；estimate 实现链 A→B→E）。**这不是「问题不存在」或「已被推翻」，是「已定位到卡在哪一步」。**

## 建议 / 下一步

- A：消费 search_requests r-000010（topic = `microstates free entropy dimension estimator`，英文关键词已写在 description），交付估计器候选文献的终局与 result_lit_ids。
- B：把 A 命中的文献整理成关系行（逐字引文、quote_verified）。
- E：若 A/B 给出候选估计器，按 conjecture 000000 的 `testable.gate_criteria`（Q1–Q4）与 `input_schema` 落地实现，产出 readings 交 `scripts/conj000000_verdict_gate.py` 判三档。
- G/H：任何引用本问题时，主问句必须写成开放问题，不得写成我们的结果。
