# D 初步研究报告

- 生成时间：2026-09-25T22:55:50+08:00
- 智能体：`agent-D`；问题总数：1
- 置信度分布：（本轮尚未形成任何结论）（**低就是低，不因篇幅或措辞调整**；括号内为受控词表取值）
- 溯源模式：外部 trace_tools

## 0. 阅读须知

1. 每条问题都带**代号溯源**（`origin` + 概念/关系代号）：任何一句结论都能回到
   关系表里对应的 `quote` 去核对，这是「完全引用参考文献」要求的延续。
2. 置信度由**可核实的证据量**算出（通过引文校验的条数、度数、矛盾对数），
   LLM 只能调低、不能调高。
3. 「知识不足」由三条可核实判据触发（关键词零命中 / 度数低且无可核验引文 / 表述互相矛盾），
   不使用「感觉不够」这类无法反驳的判据。
4. 每个问题都列出**对 C 的按需查询**（I1）：查了就写拿到什么，没查到就写**无 C 侧证据**，并且那一节的结论不作确定语气。
5. 矛盾驱动的问题（I2）走**裁决闭环**：追问有轮数上限与全局配额，用尽即标 `persistent`（交人复核），不会无限追问。

## 1. 问题台账总览

| 状态 | 数量 |
|---|---|
| open | 1 |

| 问题 | 类型 | 优先级 | 状态 | 来源（代号溯源） | 等待中的请求 |
|---|---|---|---|---|---|
| 0000 | gap | high | open | `C:hottest:0000:0000,0001,0005` | - |

## 2. 逐个问题

### 0000. 最热门的 3 个概念（K(m)、S̃_m、spectrum of a periodic graph）为何成为关系网络的枢纽？它们之间的联结是否构成一个可检验的共同机制？

- **优先级**：high；**状态**：open
- **结论置信度**：**低（low）**
- **代号溯源**：`origin=C:hottest:0000:0000,0001,0005`；
  相关概念 `0000, 0001, 0005`；相关关系 `0000, 0001, 0002, 0003, 0004, 0005, 0006, 0007, 0008, 0009, 0011, 0012, 0013, 0014, 0015, 0016, 0017, 0018, 0019, 0020, 0021, 0022, 0023, 0024`

**为什么值得研究（引用 C 的证据）**

- C 的证据：C 报告 `0000`（kind=hottest，需求原文：最热概念（验收 P2））的摘要：最热门的 5 个概念：K(m)(16次)、S̃_m(11次)、spectrum of a periodic graph(11次)、girth(8次)、Floquet matrix(3次)

**现有证据（L1/L2 逐字引用 + 代号链）**


**链条自身的表述（L1，按跳序）**

1. `R0000` K(m) → periodic graph（status=active，quote_verified=True）（报告期补取）：
   K(m) 是 Q^∨-周期的且周期秩为 m−1，且 Q^∨ 在 V_K 上恰有两个轨道（Σx_i = 0 与 Σx_i = 1）。
   引文 > K(m) is Q∨-periodic of rank m−1 with exactly two orbits on VK, namely {P
   ← 文献 `0000`，p. 3
2. `R0001` S̃_m → periodic graph（status=active，quote_verified=True）（报告期补取）：
   S̃_m 是 Q^∨-周期的且周期秩为 m−1，且 |W_a/Q^∨| = m!。
   引文 > and eSm is Q∨-periodic of rank m −1 with |Wa/Q∨| = m!. Both graphs are m-
   ← 文献 `0000`，p. 3
3. `R0002` K(m) → S̃_m → vertex-transitive（status=active，quote_verified=True）（报告期补取）：
   两个图都是 m-正则、无限、局部有限、顶点传递的，并且都带一个秩 m−1 的自由阿贝尔群作用、商有限。
   引文 > Both graphs are m-regular, infinite, locally finite and vertex-transitive, and both carry a free
   ← 文献 `0000`，p. 2
4. `R0003` K(m) → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.3：对 m ≥ 3，Spec K(m) = [−m, m]（周期图的谱定义为 Floquet 矩阵谱在对偶环面上的并的闭包）。
   引文 > Theorem 1.3 (spectrum of K(m)). Let m ≥3. Then Spec K(m) = [−m, m], where the spectrum
   ← 文献 `0000`，p. 2
5. `R0004` S̃_m → spectrum of a periodic graph → companion book [6]（status=active，quote_verified=True）（报告期补取）：
   Spec S̃_m = [−m, m]（3 ≤ m ≤ 5）**取自配套书 [6, Thm. 6.5]**，本文未重证。
   引文 > the companion book that Spec eSm = [−m, m] for 3 ≤m ≤5.
   ← 文献 `0000`，p. 1
6. `R0005` K(m) → girth（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.4：对 m ≥ 3，girth K(m) = 6。
   引文 > Theorem 1.4 (girths). Let m ≥3. Then girth K(m) = 6. For the chamber graph, girth eSm = 6
   ← 文献 `0000`，p. 2
7. `R0006` S̃_m → girth（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.4：girth S̃_m = 6（m = 3），girth S̃_m = 4（一切 m ≥ 4）。
   引文 > when m = 3 and girth eSm = 4 for every m ≥4.
   ← 文献 `0000`，p. 2
8. `R0007` K(m) → S̃_m → spectrum of a periodic graph → cospectral（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.5：对 m ∈ {4,5}，Spec K(m) = [−m, m] = Spec S̃_m，即两者同谱。
   引文 > Spec K(m) = [−m, m] = Spec eSm,
   ← 文献 `0000`，p. 2
9. `R0008` K(m) → S̃_m → girth（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.5：girth K(m) = 6 ≠ 4 = girth S̃_m，故 K(m) ≇ S̃_m —— **谱不决定图**。
   引文 > but girth K(m) = 6̸ = 4 = girth eSm. In particular K(m)̸ ∼= eSm: the spectrum does not determine
   ← 文献 `0000`，p. 2
10. `R0009` spectrum of a periodic graph → spectral invariant（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.5 是关于**一个特定程序**的否定结果：任何只用谱（作为集合）的识别都会给 K(m) 与 S̃_m 相同的值，因而无法区分它们。
   引文 > read as a set, can decide the identity of a periodic graph within this family.
   ← 文献 `0000`，p. 1
11. `R0011` K(m) → S̃_m → girth → spectral invariant（status=active，quote_verified=True）（报告期补取）：
   Rem. 1.7：本文中区分这一对的是**围长**，一个初等的度量不变量。
   引文 > girth, an elementary metric invariant.
   ← 文献 `0000`，p. 2
12. `R0012` S̃_m → spectrum of a periodic graph → companion book [6]（status=active，quote_verified=True）（报告期补取）：
   Rem. 1.6：Spec S̃_m = [−m, m] 对该书而言只对 3 ≤ m ≤ 5 已证；对 m ≥ 6 只证明了包含关系 Spec S̃_m ⊆ [−m, m] 与两个端点 ±m，**等号是公开问题**。
   引文 > matching the known range; the case of eSm for m ≥6 is an open problem that would extend it. The
   ← 文献 `0000`，p. 2
13. `R0013` S̃_m → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   §6：m ≥ 6 的障碍是 S̃_m 的 cell 有 m! 个顶点，而 K(m) 的只有两个；对 K(m) 只需证 |S(χ)| 取到 0（有显式见证），对 S̃_m 则必须证明两个分支相交，而**没有显式见证可用**。
   引文 > one must show that two branches meet, with no explicit witness available.
   ← 文献 `0000`，p. 8
14. `R0014` K(m) → Floquet matrix（status=active，quote_verified=True）（报告期补取）：
   Lemma 3.1(iii)：K(m) 的 cell 是两个顶点、m 条平行边，电压为 0, e_1, …, e_{m−1}。
   引文 > are m parallel edges A–B with these voltages.
   ← 文献 `0000`，p. 5
15. `R0015` K(m) → spectrum of a periodic graph → Floquet matrix（status=active，quote_verified=True）（报告期补取）：
   Lemma 3.1(iii)：Floquet 矩阵的非对角元是这 m 条边的 χ-权之和 S(χ) = χ(0) + Σ_{i<m} χ(e_i) = 1 + Σ_{i<m} z_i。
   引文 > i<m zi, and the conjugate in the opposite direction; so Aχ is as
   ← 文献 `0000`，p. 5
16. `R0016` K(m) → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.3 的证明 (a)：S(χ) 是 m 个单位复数之和，故 |S(χ)| ≤ m（三角不等式）；0 也被取到（m = 2 取 z_1 = −1；m = 3 取两个本原三次单位根；m ≥ 4 取 z_1 = −1 与全部 (m−2) 次单位根）。
   引文 > |S| = 0 is attained: for m = 2 take z1 = −1; for m = 3 take z1 = e2πi/3, z2 = e4πi/3, the two
   ← 文献 `0000`，p. 5
17. `R0017` K(m) → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   Theorem 1.3 的证明 (a)：χ ↦ |S(χ)| 连续且 T^{m−1} 连通，故 |S(T^{m−1})| 是 [0,m] 的连通子集且含 0 与 m，从而等于 [0,m] —— **这是唯一用到环面拓扑的地方**。
   引文 > Finally χ 7→|S(χ)| is continuous and Tm−1 is connected, so |S(Tm−1)| is a connected subset of
   ← 文献 `0000`，p. 5
18. `R0018` K(m) → Floquet matrix（status=active，quote_verified=True）（报告期补取）：
   Rem. 3.5（陷阱）：把 2m 个有向步 ±e_i 各算一项会得到 S(1) = 2m−1 与 λ_max = 2m−1 —— **错的**；cell 里每个方向只有一条边，故 S(1) = m。m = 4 时错答案 7，而真正的度数是 4。
   引文 > term χ(±ei) to S(χ) gives S(1) = 2(m −1) + 1 = 2m −1 and λmax = 2m −1. That is also wrong:
   ← 文献 `0000`，p. 6
19. `R0019` K(m) → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   Rem. 3.3（陷阱）：|S| = 0 的见证是显式的，所以端点 0 **不必**用数值搜索 —— 粗网格会漏掉它（论文称每角 60 点的网格上 m = 4 的 min|S| 约为 0.04 而非 0）。
   引文 > for m = 4 is about 0.04 rather than 0).
   ← 文献 `0000`，p. 6
20. `R0020` K(m) → girth（status=active，quote_verified=True）（报告期补取）：
   §5：K(m) 的 girth 由盒子里的 BFS 得到 6（m = 3,4,5）。
   引文 > Girth (Theorem 1.4). K(m): BFS in a box gives girth 6 for m = 3, 4, 5. eSm: the affine
   ← 文献 `0000`，p. 7
21. `R0021` S̃_m → girth（status=active，quote_verified=True）（报告期补取）：
   §5：把仿射 Weyl 群实现为 {(w,λ)}、群律 (w,λ)(v,μ) = (wv, λ + w(μ))，从 Coxeter 表现构造半径 6 的球，在球内算得 girth 为 6（m = 3）、4（m = 4,5）。
   引文 > Weyl group is realised as {(w, λ)} with the group law (w, λ)(v, µ) = (wv, λ + w(µ)), the ball
   ← 文献 `0000`，p. 7
22. `R0022` K(m) → spectrum of a periodic graph（status=active，quote_verified=True）（报告期补取）：
   §5：数值校验**不作为证明** —— 论文明确写出 'No numerical output is used as a proof'。
   引文 > No numerical output is used as a proof: every statement is proved in the text.
   ← 文献 `0000`，p. 7
23. `R0023` K(m) → girth（status=active，quote_verified=True）（报告期补取）：
   Example 1.8：K(4) 中的一个 6-环，(0,0,0,0) → (0,0,0,1) → (−1,0,0,1) → (−1,0,1,1) → (−1,0,1,0) → (0,0,1,0) → 回到起点，差向量 e_4, −e_1, e_3, −e_4, e_1, −e_3。
   引文 > returning to (0, 0, 0, 0). The successive differences e4, −e1, e3, −e4, e1, −e3 are signed standard
   ← 文献 `0000`，p. 2
24. `R0024` S̃_m → girth（status=active，quote_verified=True）（报告期补取）：
   Example 1.8：S̃_4 中的一个 4-环是 1, s_1, s_1s_3, s_3 —— 在 Ã_3 的 Coxeter 圈里节点 1 与 3 不相邻，故 s_1 与 s_3 可交换、walk 闭合。
   引文 > A 4-cycle in eS4 is the square 1, s1, s1s3, s3: the nodes 1 and 3 are not adjacent in the Coxeter
   ← 文献 `0000`，p. 3

**相关概念的定义与度数（L2）**

- `C0000`「K(m)」定义：论文 Definition 1.1 定义的折叠图：顶点集 V_K = {x ∈ Z^m : Σ_i x_i ∈ {0,1}}，x 与 y 相邻当且仅当 y = x ± e_i。；度数 16
- `C0001`「S̃_m」定义：论文 Definition 1.2 定义的腔图：仿射 Weyl 群 W_a(Ã_{m-1}) 关于生成元 {s_0, s_1, …, s_{m-1}} 的 Cayley 图。；度数 11
- `C0004`「periodic graph」定义：周期图：局部有限连通简单图 X 连同在 V(X) 上自由作用、轨道有限的自由阿贝尔群 Γ ≤ Aut(X)；rank Γ 称为周期秩。；度数 2
- `C0005`「spectrum of a periodic graph」定义：周期图的谱：Floquet（Bloch）矩阵的谱在对偶环面上的并的闭包（式 (2)）。；度数 11
- `C0006`「Floquet matrix」定义：Floquet 矩阵 A_χ：以 X/Γ 的类为指标，从 x 的类到 y 的类的元素是 χ(λ) 对实现该转移的全部平移 λ 之和。；度数 3
- `C0007`「cospectral」定义：同谱：两个图的谱（作为集合）相等。；度数 1
- `C0008`「girth」定义：围长：图中最短环的长度。；度数 8
- `C0009`「vertex-transitive」定义：顶点传递：自同构群在顶点集上传递。；度数 1
- `C0011`「spectral invariant」定义：谱不变量：只由谱（作为集合）决定的量，例如 λ_max、λ_min、'谱是区间'这一陈述。；度数 3
- `C0013`「companion book [6]」定义：论文引用的配套书（Companion book on quotient lattices, tori and periodic graphs, vol. 11, Theorem 6.5）。论文的 Spec S̃_m 结果**取自**该书，本文未重证。；度数 2

- 关系链 `0000->0001->0002->0003->0004->0005->0006->0007->0008->0009->0011->0012->0013->0014->0015->0016->0017->0018->0019->0020->0021->0022->0023->0024` 的逐步表述（`trace.chain`）：

```text
1. [0000] K(m)、periodic graph（active，已校验（引文在文献原文中逐字命中））：K(m) 是 Q^∨-周期的且周期秩为 m−1，且 Q^∨ 在 V_K 上恰有两个轨道（Σx_i = 0 与 Σx_i = 1）。｜引文：「K(m) is Q∨-periodic of rank m−1 with exactly two orbits on VK, namely {P」｜出处：文献 0000 p. 3
2. [0001] S̃_m、periodic graph（active，已校验（引文在文献原文中逐字命中））：S̃_m 是 Q^∨-周期的且周期秩为 m−1，且 |W_a/Q^∨| = m!。｜引文：「and eSm is Q∨-periodic of rank m −1 with |Wa/Q∨| = m!. Both graphs are m-」｜出处：文献 0000 p. 3
3. [0002] K(m)、S̃_m、vertex-transitive（active，已校验（引文在文献原文中逐字命中））：两个图都是 m-正则、无限、局部有限、顶点传递的，并且都带一个秩 m−1 的自由阿贝尔群作用、商有限。｜引文：「Both graphs are m-regular, infinite, locally finite and vertex-transitive, and both carry a free」｜出处：文献 0000 p. 2
4. [0003] K(m)、spectrum of a periodic graph（active，已校验（引文在文献原文中逐字命中））：Theorem 1.3：对 m ≥ 3，Spec K(m) = [−m, m]（周期图的谱定义为 Floquet 矩阵谱在对偶环面上的并的闭包）。｜引文：「Theorem 1.3 (spectrum of K(m)). Let m ≥3. Then Spec K(m) = [−m, m], where the spectrum」｜出处：文献 0000 p. 2
5. [0004] S̃_m、spectrum of a periodic graph、companion book [6]（active，已校验（引文在文献原文中逐字命中））：Spec S̃_m = [−m, m]（3 ≤ m ≤ 5）**取自配套书 [6, Thm. 6.5]**，本文未重证。｜引文：「the companion book that Spec eSm = [−m, m] for 3 ≤m ≤5.」｜出处：文献 0000 p. 1
6. [0005] K(m)、girth（active，已校验（引文在文献原文中逐字命中））：Theorem 1.4：对 m ≥ 3，girth K(m) = 6。｜引文：「Theorem 1.4 (girths). Let m ≥3. Then girth K(m) = 6. For the chamber graph, girth eSm = 6」｜出处：文献 0000 p. 2
7. [0006] S̃_m、girth（active，已校验（引文在文献原文中逐字命中））：Theorem 1.4：girth S̃_m = 6（m = 3），girth S̃_m = 4（一切 m ≥ 4）。｜引文：「when m = 3 and girth eSm = 4 for every m ≥4.」｜出处：文献 0000 p. 2
8. [0007] K(m)、S̃_m、spectrum of a periodic graph、cospectral（active，已校验（引文在文献原文中逐字命中））：Theorem 1.5：对 m ∈ {4,5}，Spec K(m) = [−m, m] = Spec S̃_m，即两者同谱。｜引文：「Spec K(m) = [−m, m] = Spec eSm,」｜出处：文献 0000 p. 2
9. [0008] K(m)、S̃_m、girth（active，已校验（引文在文献原文中逐字命中））：Theorem 1.5：girth K(m) = 6 ≠ 4 = girth S̃_m，故 K(m) ≇ S̃_m —— **谱不决定图**。｜引文：「but girth K(m) = 6̸ = 4 = girth eSm. In particular K(m)̸ ∼= eSm: the spectrum does not determine」｜出处：文献 0000 p. 2
10. [0009] spectrum of a periodic graph、spectral invariant（active，已
```

**C 侧按需查询（I1）**

- 本轮**未对 C 发起按需查询**（该问题未进入研究/评估步骤，`evidence.c_queries` 为空）⇒ 本节**无 C 侧证据**：下面的判断未经 C 的图查询核对。

**缺口与已提交的查询**

- 尚未提交查询请求（证据已足够，或受预算限制；详见审计一节）。

**初步分析**

（本轮未运行到研究步骤：该问题未进入 `researching`，因此没有分析。上一节给出的是**报告期补取的溯源证据**，不是研究结论。）

**结论与置信度**

**本轮未形成结论**：该问题还没进入研究步骤（无 `research()` 记录），因此**不给出置信度** —— 没有可评估的证据时，任何档位都是编出来的。

**后续建议**

- （无）

<details><summary>研究笔记（原始记录）</summary>

```
[ingest] 来源报告 0000（kind=hottest）。理由：C 报告 0000 统计出这些概念的出现次数最高：K(m)(occurrences=16,relation_count=16)、S̃_m(occurrences=11,relation_count=11)、spectrum of a periodic graph(occurrences=11,relation_count=11)
[ingest] weak_conflict_clue: 关系 0016、0017 出现「否定标记出现与否不一致（0016 neg=True / 0017 neg=False）—— **这只是线索，不是对立主张**」。strength=weak ⇒ **只记录为线索，不建矛盾问题、不自动追问**（弱信号的假阳性极高，不能让 A 的产能烧在假矛盾上）。若后续证据让其中一方明确被否定，再走 I2。
[ingest] weak_conflict_clue: 关系 0021、0024 出现「否定标记出现与否不一致（0021 neg=False / 0024 neg=True）—— **这只是线索，不是对立主张**」。strength=weak ⇒ **只记录为线索，不建矛盾问题、不自动追问**（弱信号的假阳性极高，不能让 A 的产能烧在假矛盾上）。若后续证据让其中一方明确被否定，再走 I2。
merged_origins: C:paths:0001:0008（§3.1 等价类命中：与已有问题共享关系代号 0008；来源报告 0001）
merged_origins: C:paths:0001:0016->0007->0007（§3.1 等价类命中：与已有问题共享关系代号 0007、0016；来源报告 0001）
merged_origins: C:paths:0001:0023->0011->0011（§3.1 等价类命中：与已有问题共享关系代号 0011、0023；来源报告 0001）
merged_origins: C:cold:0002:0004（§3.1 等价类命中：与已有问题共享关系代号 0000、0001；来源报告 0002）
merged_origins: C:cold:0002:0013（§3.1 等价类命中：与已有问题共享关系代号 0004、0012；来源报告 0002）
merged_origins: C:gaps:0003:0000,0001,0008（§3.1 等价类命中：与已有问题共享关系代号 0000、0001、0002、0003、0004、0005、0006、0007、0008、0011、0012、0013、0014、0015、0016、0017、0018、0019、0020、0021、0022、0023、0024；来源报告 0003）
merged_origins: C:gaps:0003:0000,0001,0008,0011（§3.1 等价类命中：与已有问题共享关系代号 0000、0001、0002、0003、0004、0005、0006、0007、0008、0009、0011、0012、0013、0014、0015、0016、0017、0018、0019、0020、0021、0022、0023、0024；来源报告 0003）
merged_origins: C:gaps:0003:0000,0005,0006（§3.1 等价类命中：与已有问题共享关系代号 0000、0002、0003、0004、0005、0007、0008、0009、0011、0012、0013、0014、0015、0016、0017、0018、0019、0020、0022、0023；来源报告 0003）
[ingest] 另见报告 0000（kind=hottest）的同一条链：origin=C:hottest:0000:0000,0001,0005。多份报告指向同一研究点 = 该点更值得做的信号。
```
</details>

## 3. 审计信息（结论可复核性）

- 工具调用错误 / 降级记录：
  - 无

- 本轮 ingest 情况：
  - 报告 `0000`（kind=hottest）：候选 1 个，新建 0 个
  - §3.1 等价类：命中已有问题而**未新建** 0 个；内容键合并 1 个
  - I2 矛盾吸收：来源=c_service checked=True 读入 2 条；范围=given_relation_ids，扫描 10 条关系，命中 2 对字面候选（strong 0 对、weak 2 对）；其中 2 条是 weak（仅否定词出现与否不一致），**实测假阳性极高，不得当作矛盾呈现**，只能作为继续查的线索
    - 跳过：弱线索（0016、0017，strength=weak）：只记录，不建问题/不追问
    - 跳过：弱线索（0021、0024，strength=weak）：只记录，不建问题/不追问
  - I2 **弱线索（不追问）** 2 条：`strength != strong` 的矛盾对只记录为线索，不建矛盾问题、不向 A 提问（弱信号假阳性极高）
    - 关系 0016、0017：否定标记出现与否不一致（0016 neg=True / 0017 neg=False）—— **这只是线索，不是对立主张**；落痕=0000
    - 关系 0021、0024：否定标记出现与否不一致（0021 neg=False / 0024 neg=True）—— **这只是线索，不是对立主张**；落痕=0000

- I1 C 服务接线：
  - mode=auto：调用方未注入 C 服务，D 自行装配 agent_c.AgentC（只读服务，不写盘）
- I2 本轮矛盾裁决：
  - 本轮没有可裁决的矛盾问题（没有 kind=contradiction 的问题，或都还有在途请求）
  - 全局矛盾检索配额：0/10（用尽后不再追问，一律标 persistent 交人复核）

- poll 复检：
  - 就绪 []；未就绪 []；拉回 researching []

- 每条判据的中间值（命中数 / 度数 / 校验分布）见各问题的「触发判据」一节；
  完整数值由 `AgentD.last_assessment` 保留在内存中，可另行落盘。

