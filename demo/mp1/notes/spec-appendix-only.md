# 重构规格（优先级高于上一版派活）

业主新硬要求：**计算证据只允许放附录**。

## 新的正文结构（严格）
1. Title
2. Abstract
3. 1 Introduction（含文献背景，真 \cite + 真 \bibitem）
4. 2 Definitions and notation
5. 3 Main results —— 定理与证明为主，**正文长度全部由这里撑起来**
6. 4 Discussion and open problems
7. References（真 \bibitem，与 \cite 一一对应）
8. Appendix A: Computational evidence —— 算法、参数域、量的表、内部编号全放这里

## 硬要求逐条
- 正文（Abstract / 1 / 2 / 3 / 4）里**不得出现**：数值实验小节、实验表、参数扫描结果、内部编号（exp: / stmt: / lit: / rel: / conj:）、台账 / 本轮 / 验收表 / sha256、"Reproducibility" "文献可核性" 这类自审小节。
- 正文需要交代实验时只许一句话：「Numerical evidence is deferred to Appendix A」，并把结论强度写成 depends on that evidence / supported, not proved。
- ≥6 个 theorem / lemma / proposition 环境，每个都带 `\begin{proof}...\end{proof}`，证明内分 (1)(2)(3) 步，可逐行检查。把工作区里所有真正成立的东西写成引理/命题（含平凡的、已知的、条件性的），标清来源与适用范围；证不了的写成 Conjecture / Open problem 并写明缺哪一步。
- 四条文献 \bibitem：ikm2006、manners2015、kravitzleng2025、mmr2013（与正文 \cite 对应）。
- 本会话无 Lean：**不许出现**「机器验证 / Lean 已验证 / formally verified / machine-checked」；自然语言证明照写；证据档按 proof_review 的口径在附录里说明。
- 改完必须重编译 `out/paper/main.pdf`，让 COMPILE-RECEIPT 的 tex_sha256 与盘上 main.tex 一致；把 pages、tex_sha256 写进你的 final。

## 可自证的数学内容（全部用自然语言证，逐条写清）
(1) 覆盖判据：∪_i R_{θ_i}E(ε) = R² ⟺ r(Θ) ≤ ε。
(2) 点下界：f(p)=min_i dist(p·u_i, Z) ≤ r(Θ)（sup 定义）。
(3) 1-Lipschitz：p ↦ dist(p·u_i, Z) 是 1-Lipschitz（|p·u−q·u| ≤ |p−q|，dist 到 Z 是 1-Lipschitz），故 f 是 1-Lipschitz；盒上网格最大 L 给 r(Θ) ≤ L + ½√(h_x²+h_y²)。
(4) 周期平行四边形上的紧上界（f 有两个独立精确周期时，同一 Lipschitz 论证在一个周期平行四边形上做）。
(5) r(Θ) ≤ 1/2 恒成立（dist ≤ 1/2），且 r 关于 Θ 单调不减（Θ ⊆ Θ' ⇒ r(Θ) ≤ r(Θ')）。
(6) k=1 精确：r({θ}) = 1/2 对任意 θ（p·u 取遍 R）。
(7) 标准正交对：Θ = {0, π/2} 时 r(Θ) = 1/2（用 sup over 两个方向的最大最小值，取 p = (1/2, 1/2) 类论证，注意写清）。
(8) 任何有限 Θ 有 r(Θ) ≥ 1/(2k) 的**反例形态**说明（写成 Conjecture 或 Open problem，写清缺哪一步）。

## 产出
- 覆盖写 `out/paper/main.tex`（用 fs.write 带 overwrite）。
- 重编译 `out/paper/main.pdf`。
- final 里逐条报告：定理环境个数、正文洁净度（自查了哪几个禁词）、pages、tex_sha256。
