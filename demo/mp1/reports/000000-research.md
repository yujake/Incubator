# 000000 — Pyjama 问题定量化：N(eps) 的已知上界与增长阶（收口，带保留）

> 角色：D（台账号 t-000043）。本会话 **Lean 形式化关闭** ⇒ 全部结论等级上限 `cross_check`，任何一条都不写成「已证明」。
> 台账状态：`research_questions` 000000 已清零等待集（r-000002 已终局）并推至 `answered`（带保留）。

## 一、分析

### 1.1 问题（原样）
R^2 中宽度 2eps 的周期竖条 E(eps)={p: dist(p·e_1,Z)<=eps} 与其绕原点的有限多个旋转之并集，覆盖全平面所需最少旋转数 N(eps)；N(eps) 是否对每个 eps>0 有限，随 eps->0 的增长阶是什么（1/eps 型还是更快）。

### 1.2 证据盘点（每条都能指回关系/文献行）
| 位 | 内容 | 落点 |
|---|---|---|
| 上界（定量） | 存在万有常数 C>0，使 0<eps<1/10 时 exp exp exp(eps^{-C}) 个旋转覆盖全平面 | stmt:000000（Kravitz–Leng Theorem 1.1，source_lit_id=000001，`quote_verified=true`，`quote_mode=verbatim`，`page_range=p.1`，`evidence_kind=cross_check`） |
| 上界（逐字） | 「Our main result is that exp exp exp(ε^{−O(1)}) rotations of E(ε) suffice to cover the complex plane.」 | lit:000001 p.1（经 r-000002 submit_note 逐字转述） |
| 有限性（存在性，无定量界） | Manners 2015 证明任意 eps>0 有限多旋转可覆盖；其论证**未给任何关于 eps 的定量界** | lit:000000；r-000002 submit_note 明言 |
| 原问题 | IKM 2006 | lit:000002 |
| 侧信息 | eps>1/3 时三个旋转足够；MMR 2013：eps<1/3 无共同格周期解、eps>1/5 肯定回答、有限多一般位置旋转永不覆盖 | stmt:000002、stmt:000003（均 source_lit_id=000001，转引） |

### 1.3 五路检索路径与其读数（r-000002：done=true / outcome=ok / claimed_by=t-000035 / result_lit_ids=[000000,000001,000002]）
1. `topical`，providers=[openalex,crossref,doaj]，topic='quantitative Kakeya strip covering number of rotations N(eps)' → **crossref 交付 10 条，全不相关**。
2. 同批 **openalex HTTP 429** —— 这一路**没查成**，不是「没有结果」。
3. 同批 **doaj HTTP 400** —— 同样**没查成**，不是「没有结果」。
4. `precise`，provider=crossref，topic='Kakeya strips covering rotations' → 7 条，仅 Bateman 2009（方向极大算子）沾边，非覆盖数增长率，判不相关、未进结果。
5. 引文前 walk（forward citations of lit:000000 Manners 2015）→ 5 条全不相关。
6. `precise`，provider=crossref，topic='Quantitative pyjama' → 10 条，其中 **1 条去重命中既有 lit:000000**（doi:10.1007/s00222-014-0571-7），其余（striped pyjama squid 等）不相关。
7. `local`（search.local）逐字核对 lit:000001 / lit:000000 / lit:000002 首页 —— 见 §1.2。

> 三态纪律：②③ 两条是「没查成」（429/400），不得读成「没有这类文献」。④⑤⑥ 只记「未进结果」，不主张这些文献不存在。

## 二、结论（强度与证据相称）

**(a) 可说的（已判，等级 cross_check）**
- 对每个 eps>0，N(eps) **有限**（lit:000000 存在性；lit:000001 定量化）。
- 已知**显式定量上界**：N(eps) ≤ exp exp exp(eps^{-C})，C>0 万有常数，0<eps<1/10（stmt:000000 / lit:000001 Thm 1.1，p.1）。
- 该上界是**三重指数**，远弱于 O(1/eps)：不可被读成「N(eps)=O(1/eps)」。
- 本会话无 Lean、无形式化验证 ⇒ 上述是文献陈述的 cross_check，**不是已证明**。

**(b) 不可说的（开放；本轮检索未取回任何文献）**
- N(eps) 随 eps->0 的**精确增长阶**：是否 O(1/eps)、是否带对数因子（如 (1/eps)·log(1/eps)）。
- **下界侧**的 1/eps 型显式阶（本轮无任何文献给出）。
- 缺的那一步：从「存在性/定量存在上界」到「可算常数界 / 匹配阶」的定量化推导；属文献型缺口，检索路径已走完（含②③两路没查成）。

**(c) 数值侧（E 的实验，引用须带条件）**
- k=1、2 精确取等 r=1/2（exp:000000 / exp:000002 / exp:000021）；k=3..10 五族 40 格全部认证下界 r_lower≥1/(2k)，认证上界 r_upper_box<1/(2k) 的格 **0** 个，certified_global_refutations=0（exp:000023）。
- **限制**：exp:000023 的 `r_upper_box` 只在 [-1,1]^2 盒内成立，**不是全局上界**；exp:000012 的 `r_ub_safe` 已被 exp:000018 的反例推翻，引用须同时引反例。

## 三、建议（下一步）
1. **要收增长阶**：这是检索型缺口，不是本会话能算出来的 —— 需新开检索请求（英文关键词建议：`quantitative Kakeya covering number strip`、`Green quantitative pyjama`、`lower bound number of rotations Kakeya`），交 A；429/400 那两路应换 provider 或换措辞重试，且**不得**记为「无结果」。
2. **自有可推进的一侧是数值上界**：给出显式 Θ 并认证 r(Θ)≤eps 是提高 N(eps) 上界的唯一本地手段；下界靠逐点 witness（p 必须逐点给出）。若要在此基础上立猜想，应交给 F 攻坚并把 problem_key 设为该 conjecture_id。
3. **写作纪律**：任何下游（G/H）引用本条时必须带 (i)「cross_check，非已证明」、(ii)「上界三重指数 ≠ O(1/eps)」、(iii) 数值引用的盒限制与 exp:000018 反例。
