# 三维 l^p 球 B_p^3 的中心截面最大面积 —— 研究手稿（D）

问题号：`research_questions` 000000（kind=gap，priority=high）
本趟接手：先读本文；会话记录不会自己走到下一趟。

> **第 2 轮改写（A 腿文献读数回来后）**：第 0 节的「新」字已按 `lit:` 收窄。第 1 轮里我把
> 「1≤p<2 坐标向最大」当成本问题的未证卡点（s1），A 的检索读数表明这条在文献里**已经是定理**
> （见 §1.1）。这一处改主意的依据逐条写在 §3「尝试与失败」第 4 条。

---

## 0. 成果概述

### 0.1 文献定位：谁已知、谁是新（本趟最重要的一条判断）

| 结论 | 状态 | 落点 |
|---|---|---|
| 1 ≤ p < 2 时坐标超平面给**最大**中心截面（体对角向给最小） | **已知（定理）** | `lit:000001` p.2 逐字；已回验关系 `rel:000007` |
| p = ∞（立方体）时极大中心截面正交于二维面的主对角，体积 √2·2^{n−1}（n=3 ⇒ 4√2） | **已知（Ball）** | `lit:000003` p.1 逐字；`rel:000000`/`rel:000001`/`rel:000002`（立方体切片那一支） |
| 2 < p < ∞、n=3 的**完整三段结构** + 临界 p\* ≈ 4.9982 | **新**（所查文献无显式结论） | 见 `lit:000006` p.2 逐字「The question of determining the maximal hyperplane sections of B^p_n(R) for p ∈ (2, ∞) remains open」；`lit:000001` 只覆盖 p ≥ p_0 与 20 < p < p_0 两档 |

⇒ **本问题真正的新东西是 `2 < p < ∞` 这一段的 n=3 解**（三段切换点 + p\* 的数值位置 +
三个候选方向闭式的两两比较），不是 p<2 一侧的定性结论。

### 0.2 有 V 签的（我方证明，等级 `proof` 那一档）

1. **极坐标公式 + 48 阶对称归约 + 坐标/面对角闭式 + p=2 门槛**：`manuscripts/F/f-proof-000000.md`
   （V 判「成立」，零 finding），收录为 **`stmt:000034`**。
2. **零坐标法向族的闭式与族内极值**（n^⊥ 含某条坐标轴的全部法向）：
   `manuscripts/F/f-proof-000001.md`（V 判「成立」），收录为 **`stmt:000035`**。
   B 的第二阶段副本 `manuscripts/B/b-proof-000001.md` 被 V 判「有毛病」—— 理由**只**是稿头
   （标题 / 子目标 s3）与正文所证命题 000035 不一致，正文逐步核对无缺口，改稿头即可
   （V 的交接手稿 000006）。**这不影响 `stmt:000035` 所依据的 F 原稿**。

### 0.3 数值实验（E）

E 四件：`exp:000003`（求积核自检 `code/exp/lpsec_validate.py`）、`exp:000004`（12 个 p 的球面扫描
`code/exp/lpsec_sweep.py`）、`exp:000006`（临界 p 与单调性 `code/exp/lpsec_critical.py`）、
`exp:000007`（两条边界弧细扫描 `code/exp/lpsec_arcs.py`），全部 `result=supports`、`exit_code=0`。
它们落成 `stmt:000030`–`stmt:000033`（等级 `strong_conjecture`，普通数值档，按业主口径不过 V）。

### 0.3b 第 3 轮补记（E 的反例读数，2026-11-24 晚）

E 后续三行 `method=numeric` 实验（`exp:000020` **refutes**、`exp:000022` **refutes**、`exp:000023` supports，
全部 `exit_code=0`；脚本 `code/exp/e5_delta_second_root.py` / `e6b_pstar_peak_deriv_v2.py` /
`e7_largep_asymptotics.py`）把「ρ 单调」这条**自然证明路线否掉了**：`ρ = A_face/A_diag` 在 `p = 3.02439`
处取**极小** `0.98856`（< 1），随后升向立方体极限 `4√2/(3√3) = 1.088662`；`Δ = A_face − A_diag` 在
`(20, ∞)` 上**没有第二个零点**。交叉点读数收紧为 `p* = 4.998215596840938`（E→D 交接手稿 `0015`；
收录为 `stmt:000040`，`strong_conjecture`）。⇒ 「恰有一个交点」在数值上仍成立，但**不能靠 ρ 的单调性**
去证 —— 这条被推翻的前提写进 §3「尝试与失败」。

### 0.4 过程中总结到的经验

- **「数值看起来三段」不等于「三段已经成立」**：E 的读数给出 p\* 的 10 位数值与「中间方向不占优」，
  但连续域上的支配性一条都没证 —— 派 F 之后才把「哪些能落成证明、哪些只能停在数值」分开。
- **先派 A 再写「新」字**：第 1 轮我把 p<2 一侧当成自己的卡点，A 一轮检索就把它定位成已知定理。
  手稿第二节因此从「我们的 s1 卡点」改成「文献已知 + 我方未自证」。

---

## 1. 定义与已知

### 1.1 定义

- `B_p^3 = { x ∈ R^3 : |x_1|^p + |x_2|^p + |x_3|^p ≤ 1 }`，`1 ≤ p < ∞`；`p = ∞` 取立方体极限。
- 中心截面：`H = n^⊥`（`n` 单位法向，过原点），`A_p(n) = area(B_p^3 ∩ n^⊥)`；`A_max(p) = max_n A_p(n)`。
- 等价类口径：`p ≠ 2` 时 `B_p^3` 的对称群是 48 阶超八面体群（带符号坐标置换）⇒ 面积只依赖排序后的
  绝对值 `0 ≤ a ≤ b ≤ c`；**一般旋转不是对称**。三个候选方向：坐标向 `(1,0,0)`、面对角向
  `(1,1,0)/√2`、体对角向 `(1,1,1)/√3`。

### 1.2 已知（文献，逐条按 `lit:` 引）

- **`lit:000003` 的题录（A 按本地 PDF 首部核实，交接手稿 000039）**：作者 GERGELY AMBRUS（首部全大写，单作者）；
  arXiv:2107.14778v3 [math.MG]，22 Jun 2023；PDF 共 12 页；期刊名与卷期页 PDF 上取不到（如实记取不到，不从外部补）。
  台账落点：`lit:000003.pages`（12 pp.）与 `.summary`（含题录读数）已写；`authors`/`venue`/`year` 三个**身份格**
  被 `identity_cell_refused` 挡住（通用写口不改身份格，改它会造出第二个 dedup 主键）⇒ 逐字读数落在手稿 000039，
  关系行落 `rel:000077`–`rel:000080`（均 `quote_verified=true`）。
- **Ball（立方体切片）**：`lit:000003` p.1 逐字『Ball [B86] proved that maximal hyperplane sections are
  orthogonal to a main diagonal of a 2-dimensional face of Q_n, hence, their volume is √2·2^{n−1}』
  —— n=3 即 4√2。切片极值问题的来历见 `rel:000000`、Hensley 猜想见 `rel:000001`、
  「Q_n 与 k 维子空间交的最大体积」这一问法见 `rel:000002`。
- **3 维临界方向判据**：`lit:000003` 逐字给出「critical central hyperplane sections in the
  3-dimensional case are all diagonal to a (possibly lower dimensional) face of the cube」，
  以及 4 维非对角临界截面的存在（法向 `(1,1,2,2)`，`lit:000004`）。
- **p<2 一侧（本条改写了第 1 轮的判断）**：`lit:000001` p.2 逐字『They proved that the normalized
  volume of central hyperplane sections of the unit ball B^n_p of l^n_p is monotone increasing in p,
  implying that coordinate hyperplanes provide the minimal sections for 2 < p < ∞ and the maximal
  sections for 1 ≤ p < 2. The minimal sections of B^n_p for 1 ≤ p < 2 are those orthogonal to the main
  diagonals』（已回验：`rel:000007`；同族见 `rel:000003`–`rel:000011`）。⇒ **1 ≤ p < 2 的极大方向 =
  坐标向，这是已知定理**，我们的 `stmt:000030`–`stmt:000033` 在这一侧只是独立数值复现。
- **n 维的已知边界**：`rel:000004`（Eskenazis–Nayar–Tkocz：p ≥ 10^15 的 Ball 型结论）、
  `rel:000005`（Oleszkiewicz：2 < p < p_0 ≈ 26.265 时 Ball 的结论不成立）、
  `rel:000016`（该文猜想 n 维极大截面只在 `(a(2))^⊥` 与 `(a(n))^⊥` 之间取）。
- **文献缺口（我们这条新结论的依据）**：`lit:000006` p.2 逐字『The question of determining the
  maximal hyperplane sections of B^p_n(R) for p ∈ (2, ∞) remains open』。
- **结构类比（可迁 / 不可迁）**：截面 ↔ 投影的对偶（`p ↔ p'`，极 ↔ 极互换，`rel:000008`）与
  Khintchine 型最佳常数同构（`rel:000009`、`rel:000010`）。**可迁**：极值截面 = 某型 Khintchine
  最佳常数这一等价结构；**不可迁**：体积本身（体积在对偶下不变性差，`lit:000001` p.2 逐字）。

---

## 2. 已确定的结论

目录行（四格照抄，不改写 E 的读数、不把 V 的签写成我自己核过的）：

### 结论 1 —— 极坐标公式、48 阶归约、坐标与面对角闭式、p=2 门槛

一句话：`A_p(n) = (1/2)∫_0^{2π} ‖cosψ·u + sinψ·v‖_p^{-2} dψ`（与 `n^⊥` 正交基选取无关、在 48 阶
带符号坐标置换下不变）；坐标截面 `A_coord(p) = 4Γ(1+1/p)²/Γ(1+2/p)`；面对角截面
`A_face(p) = 2^{1/2−1/p}·4Γ(1+1/p)²/Γ(1+2/p)`；`A_face(p) < A_coord(p)`（p<2）、`>`（p>2），
门槛精确为 p=2；p=2 时一切单位法向都给 π。

- `evidence_kind`: `proof`
- `evidence_path`: `manuscripts/F/f-proof-000000.md`
- `evidence_sha256`: `b23016f984ba580b1ae319c1880e3b6752fff958e847492571e53e7756d29187`
- `v_signature`: `{"verdict": "成立", "sha256": "4cb054c6745ec737591bd41c456ea83a22efa7fa072fbd8f529843d22bfa3c9f"}`
  （签文件 `out/vsigns/4cb054c6745e….json`；台账 `verifications/pending/4cbbbeaf….jsonl#u-000004`）
- 台账：`stmt:000034`（B 已收录；第二阶段处置见 B 手稿 000005）

### 结论 2 —— 零坐标法向族的闭式与族内极值

一句话：`n^⊥` 含坐标轴 `e_i` 的全部法向（含面对角向与坐标平面内整族）满足
`A_p(n) = C_p·(Σ_{j≠i}|n_j|^p)^{-1/p}`；该族内 1≤p<2 时坐标向**唯一**最大、p>2 时坐标向严格最小，
门槛仍恰好 p=2。

- `evidence_kind`: `proof`
- `evidence_path`: `manuscripts/F/f-proof-000001.md`
- `evidence_sha256`: `ce111f6f78463987d972f950fd4db83227fa8e455fc792fa8f7abaddb6951d69`
- `v_signature`: `{"verdict": "成立", "sha256": "6c6accee9f0db73f1db0526a3bbbdeda9cc2f1dc61d376e5cc36439d35874625"}`
  （`manuscripts.submission_reading` 读到 state=submitted、via=sign_issued、sign_at 2026-11-24T19:12:21+08:00）
- 台账：`stmt:000035`。B 的副本 `manuscripts/B/b-proof-000001.md` 被 V 判「有毛病」——**只**在稿头，
  正文无缺口（V 手稿 000006）；本结论的依据是上表那份 F 原稿。

### 结论 3 —— 三段结构（p<2 / 2<p<p\* / p>p\*）与 p\* 的数值位置【`strong_conjecture`，非定理】

一句话：在 `p ∈ {1.05,1.1,1.2,1.5,2,2.5,3,4,5,8,16,1000}` 上，最大方向分段为 p<2 坐标向、
2<p<p\* 体对角向、p>p\* 面对角向，`A_diag = A_face` 于 `p* = 4.998215596841106` 唯一变号，
且基本域内部与 `(1,1,t)`/`(0,1,t)` 两条弧上都不存在占优的中间方向。

- `evidence_kind`: `report`（E 的确定性数值报告）
- `evidence_path`: `work/E/lp3-section-report.md`
- `evidence_sha256`: `a5b2b1121cfd19df3003d3ea3ee9e4c1dbe1a968d9f45adf2d9257efadcb7436`
- `v_signature`: **无**（普通数值档，按业主口径不过 V；等级由框架五元位现算为 `strong_conjecture`）
- 台账：`stmt:000031`、`stmt:000032`、`stmt:000033`（及核自检 `stmt:000030`）；
  实验 `exp:000004`、`exp:000006`、`exp:000007`

### 结论 4 —— p = ∞ 端的极限值（文献值 + 我方数值对照）

一句话：`A_coord→4`、`A_face→4√2`、`A_diag→3√3`；E 在 p=1000 读到 3.9999934 / 5.6529253 / 5.1961354，
残差是 1/p 阶而非误差。

- `evidence_kind`: `report`；`evidence_path`: `work/E/lp3-section-report.md`；
  `evidence_sha256`: `a5b2b1121cfd19df3003d3ea3ee9e4c1dbe1a968d9f45adf2d9257efadcb7436`；
  `v_signature`: 无（数值档）
- 文献侧：`lit:000003` p.1 逐字（Ball，n=3 ⇒ 4√2）

### 结论 5 —— A_diag(p) 的可算表达式与三个精确值（V 签「成立」）

`A_diag(p) = (1/2)∫_0^{2π}‖e(θ)‖_p^{-2}dθ = (3/4)∫_0^{2π}(|cos(θ-π/6)|^p+|cos(θ+π/6)|^p+|sinθ|^p)^{-2/p}dθ
= √3·area{|x|^p+|y|^p+|x+y|^p≤1}`；`A_diag(1)=3√3/4`、`A_diag(2)=π`、`lim_{p→∞}A_diag(p)=3√3`，
且在 `[1,∞)` 上连续。

- `evidence_kind`: `proof`
- `evidence_path`: `manuscripts/F/f-proof-000002.md`
- `evidence_sha256`: `099eb36449cf134dd531f1a7d7e34e4d13e987904a2738315c60f28220cd1148`（F 报的正文 sha；盘上字节与签是否同一份由 B 收录时核，见 t-000151）
- `v_signature`: `{"verdict": "成立", "sha256": "099eb36449cf134dd531f1a7d7e34e4d13e987904a2738315c60f28220cd1148"}`（签文件 `out/vsigns/099eb364….json`；台账 `verifications/pending/c3799ef6….jsonl#u-000021`）

---

### 结论 6 —— A_max(p) 的分段结构与两个临界点（最终表述，证据等级逐条标）

- `1 ≤ p < 2`：`A_max(p) = A_coord(p) = 4Γ(1+1/p)²/Γ(1+2/p)`，取到方向 = 坐标向 `(1,0,0)` ——
  **文献已知（定理）**：`lit:000001` p.2 逐字『coordinate hyperplanes provide … the maximal sections
  for 1 ≤ p < 2』（已回验 `rel:000007`）；我方只是数值复现（`stmt:000030`–`stmt:000033`）。
- `p = 2`：一切单位法向都给 `π`（**V 签**，结论 1 第 (iv) 条）。
- `2 < p < p* = 4.998215596862`：`A_max(p) = A_diag(p)`（结论 5 的三条等价形式），取到方向 =
  体对角向 `(1,1,1)/√3` —— **数值档 `strong_conjecture`**（`stmt:000031`–`stmt:000033`、`stmt:000040`；
  E 的 `exp:000006` / `exp:000020` / `exp:000022`），**这一段没有证明**。
- `p > p*`：`A_max(p) = A_face(p) = 2^{1/2−1/p}·4Γ(1+1/p)²/Γ(1+2/p)`，取到方向 = 面对角向
  `(1,1,0)/√2` —— 闭式本身 **V 签**（结论 1），但「这一段它最大」的判断仍是数值档。
- 两个临界点：`p = 2`（解析，V 签）与 `p* = 4.998215596862`（`Δ = A_face − A_diag` 的**唯一内部零点**，
  E 的二分 `exp:000020` + F 的尾段符号读数；数值档，无证明）。

⇒ 一句话：`A_max(p) = max{A_coord(p), A_face(p), A_diag(p)}`（三个闭式里 `A_coord` 解析已知、
`A_face` 在结论 1 里证了、`A_diag` 在结论 5 里证了），**取哪个的判据是两个临界点**，
其中**只有 `p = 2` 是解析证明过的**，`p*` 仍是数值读数 —— 不许把它写成定理。

---

## 3. 尝试与失败

1. **s1（全法向支配性 `A_p(n) ≤ A_coord(p)`，1≤p<2）—— 我方未证，但文献已解**（技术性 → 已定位置）：
   F 只解决了「n 至少一个坐标为 0」这一子族（结论 2），缺一条把 `A_p(n)` 在法向参数化后逐点比较
   的估计。**处置**：不改写成本方定理；按 §1.2 引 `lit:000001` 的单调性定理（已知），
   我方在这一侧只保留数值复现（`stmt:000030`–`stmt:000033`）。**这一处是本趟改主意的落点。**
2. **s3（`A_diag(p) = A_face(p)` 的唯一性）—— 没证出来，且「比值单调」这条路线已被反例否掉**（结构性）：
   **第 3 轮改主意留痕**：第 2 轮我写的是「`r(p)=A_diag/A_face` 单调 ⇒ 唯一穿越」。E 的三行数值实验
   （`exp:000020`、`exp:000022` 均 `refutes`；脚本 `code/exp/e5_delta_second_root.py` /
   `e6b_pstar_peak_deriv_v2.py`）表明 **ρ = A_face/A_diag 非单调**：它在 `p = 3.02439` 处取极小 `0.98856`
   （<1），随后升向立方体极限 `4√2/3√3 = 1.088662`。⇒ 「比值单调」这条路**不成立**，上一轮的证明思路
   作废，必须换。F 的读数给出真实结构：`Δ = A_face − A_diag` 在 `p = 2`（端点）与 `p* = 4.9982155968…`
   （内部唯一）各一个零点，`(20, ∞)` 上无第二零点（E 手稿 `0015`、F 手稿 `0020`、`stmt:000040`）。
   ⇒ **分段结构仍是三段**（`Δ<0` 于 `(2, p*)` ⇒ 体对角向大；`Δ>0` 于 `(p*, ∞)` ⇒ 面对角向大），
   但「唯一内部零点」至今只有数值读数，没有证明。
3. **中间方向的排除** —— 数值上成立、连续域上没有穷举（结构性）：`exp:000004`/`exp:000007` 给的是
   两条弧 + 20×20 嵌套网格上的读数，不是连续域证明。E 自己已写明「连续域无法穷举 ⇒ 不给 exhaustive、
   不送 V 签」。
4. **改主意留痕（依据哪条读数不成立）**：第 1 轮我把「p<2 坐标向最大」列为本问题的未证卡点；
   A 的检索（`r-000004`，执行记录在板项 t-000078）取回 `lit:000001` p.2 的逐字句与 `rel:000007`，
   表明它是 Koldobsky / Meyer–Pajor 单调性的推论 ⇒ 上一轮的「卡点」定位不成立，本节第 1 条据此改写。
5. **`stmt:000030` 的证明归属被误指（结构性 → 已由 B 更正归属，**不是**做不动）**：本条是 E 的数值自检命题
   （`work/E/e-num-000003.md`、`exp:000003`、`result=supports`、`exit_code=0`），按 E 侧 `numeric` 凭据现算应为
   `strong_conjecture`（普通数值档不过 V，业主口径）。它原来的 2 号证明路径指向 `manuscripts/F/f-proof-000003.md`，
   而该稿 `## 命题` 逐字等于 `stmt:000042` 的 `statement_full`，稿上 V 的三行判词
   （`verifications/pending/202ee4208a4ce6d75677880f11e5e6aa9aec87f24a3e6bf0384977e1899759b8.jsonl#u-000022/23/24`）
   `statement_id` 全是 `000042`、`path_group=1` ⇒ 那一份**构不成对 `stmt:000030` 的签**，不得用来抬成 `theorem`。
   **处置（本趟）**：先试「明确放弃（difficulty）」这一档，被秘书**受控拒** `abandon_difficulty_not_genuine`
   （盘上零字节改写）；研究侧复核判**归属错误 ≠ 做不动**，改由 B 做归属更正：`kind` `theorem → conjecture`、
   `quote_reason` 换成归属更正说明、`status` 仍 `active`、`stmt:000042` 那一行未动。
   **回执口径（可核）**：`verifications/000030.jsonl` **不存在**（`verifications/` 根下只有 000034/000035/000041/000042）
   ⇒ 没有一行「成立」；`statements` 000030 的 `status=active`、`abandon_kind` **无**（未放弃）。
   **下一步**：若真要给本条一处 V 签得住的凭据，只能走 E 的穷举档 `manuscripts/E/e-proof-<实验号>.md`
   （要 V 逐行走查），不是文字证明 —— 因为本条说的是浮点求积的偏差界（≤1e-15 / ≤1e-13），
   在形式化/机器核验通道关着的本会话里，文字证明给不出这种保证。

---

## 4. 例子与反例

- **p = 1（八面体端）**：坐标截面 2、面对角 2/√2·…（E 的端验：2 / √2 / 3√3/4，`exp:000003`
  的 V5 段，`stmt:000030`）。这是把闭式压到边界的可用反例带：任何声称「p<2 一切方向都 ≤ π」的
  粗估计在这里会立刻被证伪。
- **p = 2 的退化**：一切单位法向都给 π（结论 1 的第 (iv) 条，V 签成立）。它不是反例，但它是
  「最大方向唯一」这一说法在 p=2 处的反例 —— 写结论时必须把它单列。
- **p = 1000 的立方体极限**：`A_face` 读到 5.6529253 vs 精确 4√2 = 5.6568542，差 3.9e-3；
  E 如实报成 1/p 阶残差（`work/E/lp3-section-report.md` §1、§5），**不当事后误差抹掉**。
- **4 维的非对角临界截面存在**（`lit:000003`/`lit:000004` 逐字，法向 `(1,1,2,2)`）：
  它是对「临界方向一律是面对角/体对角」这一朴素猜想的**文献反例**（维度 ≥ 4），
  提醒我们 n=3 的三段结构不能无脑推广到 n≥4。

---

## 5. 未解问题

1. **s3**：`r(p) = A_diag(p)/A_face(p)` 在 `(2, ∞)` 上严格单调、`p*` 存在唯一 —— 只有数值读数
   （`exp:000006`：`p* = 4.998215596841106`，区间 (4,5) 内唯一变号）。**需要证明**。
2. **全法向支配性（n=3 的完整版）**：文献给了 p<2 与 p≥p_0 两端；`2<p<p_0` 的 n=3 结论是
   本趟的数值新读数，缺证明。`lit:000001` 的 n 维猜想（`rel:000016`）在 n=3 上是否落成定理，无材料。
3. **r-000004 的检索记录**：OpenAlex 首查 HTTP 429（未查成，不是无结果）⇒ 换 crossref 用同一英文
   规范式成功（10 条 / 1.0s：3 条已在库、7 条新）；7 条新候选**未取全文 ⇒ 未入库**，
   标题逐条记在 `r-000004` 的 submit_note。这是一条未清的口子，不是「不存在」。
4. `research_questions` 000000 的现场态：`own.consider` 判 `sufficient=false`
   （判据 `a_no_keyword_hit`、`b_low_degree_unverified`），自动提交 `r-000004`（已由 A 终局）。
   问题未收口。

---

### 5.5 statements 未签 9 条的逐条处置（M 的收口清单第 (3) 条）

九条是 `stmt:000030`–`stmt:000033`（E 的四件扫描：核自检 / 12 个 p 扫描 / 临界 p 与单调性 / 两条边界弧）与 `stmt:000036`–`stmt:000039`（E 后来的四条：A_diag 三路对拍、A_face 闭式对拍、Δ 的第二零点、大 p 渐近）。逐条结论相同，理由逐条写清：

- **处置：保留，不补签、不放弃。** 九条全是 `method=numeric`、`result=supports`、`exit_code=0`、有 `code_path` 的普通数值实验，等级由框架五元位现算为 `strong_conjecture`（`numeric=verified`／`proof=false`／`reviewed=false`）。普通数值档按业主口径不过 V ⇒「未签」是**这一档的证据形态**，不是漏做的工序。
- **不放弃的理由**：放弃（`abandon_kind` 四档）记的是「这条做不动了」；这九条**没有被推翻**（`stmt:000030`–`000033` 早先有两版 `refuted`，那是求积核的错、已随实验撤销；现行版本全部 supports）。标 abandoned 会把「有支持」写成「做不动」，与盘上读数相反。
- **升级的两条路（都写明，本趟没走完）**：① E 走穷举档（`manuscripts/E/e-proof-<实验号>.md` + V 逐行走查）—— 本问题的连续域支配性无法穷举，E 已如实拒绝；② F 给文字证明 —— 本趟已覆盖 p=2 门槛、零坐标法向族、A_diag 表达式三块（`stmt:000034`、`stmt:000035`、`stmt:000041`），剩下的 `2<p<p*` 段缺一条单调性引理（见 §3 第 2 条）。

---

## 6. 下一步

1. **派 F 攻 s3**（最划算的一条）：目标是把 `r(p)=A_diag/A_face` 的单调性与唯一穿越写成命题；
   可用工具：`A_diag(p) = 3√3∫_0^1 (1+t^p+(1-t)^p)^{-2/p} dt` 与结论 1 的 `A_face` 闭式。
2. **`2<p<p_0` 的 n=3 结论要么证、要么明确定位**：先派 A 取 `lit:000001` Thm 1.1/1.2 的精确条件
   （p ≥ p_0 与 20<p<p_0 两档的 n 依赖），说清 n=3 是否落在其覆盖内；不在覆盖内才谈「新」。
3. **7 条未取全文的新候选**：要 A 取全文后交 B 收编，再判是否覆盖 n=3 的中间段。
4. `manuscripts/B/b-proof-000001.md` 的稿头按 V 的意见改（标成 `stmt:000035`，子目标 s3 归到未证那一档），
   由 B 重送 V；**不要**在改好前把它当「已签副本」引用。
