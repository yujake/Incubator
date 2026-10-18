# 研究手稿（跨趟记忆）

工作区：D:\Incubator\agentflow\projects\mp3　｜　更新：2026-10-18（第 3 轮）　｜　维护角色：D
本会话 Lean 形式化**关闭** ⇒ 本手稿任何一处都不写「已证明」；证据等级上限 cross_check / heuristic。

## 一、成果概述

- **问题与三档拆分已落台账**：`research_questions` 000000（kind=gap），把「U(g) Noetherian ⇒ dim_k g < ∞?」拆成 (a) 正向端点 / (b) 无限维阿贝尔 / (c) 待判定（一般无限维非交换）三档。
- **主问题在文献里是公开猜想，不是定理**：`stmt:000006`（Sierra–Walton 猜想 / Andruskiewitsch–Mathieu Conjecture 1.1，lit:000001 p.2、lit:000002 p.1，quote_verified=true）。lit:000001 p.2 逐字写明主流预期回答 **no**。本手稿不把 `stmt:000006` 当定理用。
- **正向端点**：dim_k g < ∞ ⇒ U(g) Noetherian，落 `stmt:000007`（PBW/滤过，gr U(g) ≅ Sym(g)）；**该行 proof_text 为空、evidence_kind=heuristic，本地没有逐字原文**（lit:000004 McConnell–Robson 全文始终未取得）——这是缺口，不是已核实事实。
- **反方向的已证特殊类**（都带假设）：无限维阿贝尔 ⇒ 非 Noetherian（`stmt:000004`，lit:000001 p.2 逐字）；KN 类与 Witt 类 ⇒ 非 Noetherian（`stmt:000008`、`stmt:000009`）；simple Z^n-graded 且齐次分支有限维 ⇒ Noetherian 推出有限维（`stmt:000010`，lit:000002 Theorem 1.3）；有限余维传递性（`stmt:000005`）。
- **攻坚链 D→F→E 拿到真推进**：`attack_plans` 000000（problem_key=000000）两轮 step 均 no_change（结构性卡点，见第四节）；`attack_plans` 000001（problem_key=000000-S2，parent_plan_id=000000）history 四条，round1 `counterexample_request`、round2 `reduction` 均 outcome=progress，第 3–4 轮把 s2 推到完成、s3 从 blocked 解除到布尔级、s4 边界隔离完成，台账 `reports/attack-000001.md`（末次 sha256 前缀 8d28b456d25d7f49…）。
- **数值证据（E，可复现，判等全由代码判）**：`exp:000008`（`code_path=code/expA_truncated_chain.py`，`code_hash` 前缀 e0f9cf577d0d56b6，`result=supports`）对 h_∞ 截断族 I_n=sum_{i<=n}U(g)·(a_i b_i) 在 n=1..8 逐项严格上升通过；`exp:000010`（`code_path=code/expB_center_translation_chain.py`，`code_hash` 前缀 5d4924f05e1792b0，`result=refutes`，带可复核 `counterexample` 分离泛函）证明中心平移族两两互不包含、不构成链。两条都**只覆盖声明界**。
- **本趟没有**证明任何新命题、**没有**构造出「无限维非交换 g 而 U(g) Noetherian」的例子。第 (c) 档仍未判定。

## 二、定义与已知

- `stmt:000000` U(g) Noetherian（左 ⇔ 右，lit:000001 p.1 逐字）；`stmt:000011` 有限维 Lie 代数；`stmt:000003` simple Z^n-graded（**必须带「齐次分支有限维」约定**，lit:000002 p.2）。
- `stmt:000004` 无限维阿贝尔 ⇒ U(g) ≅ Sym(g) 为无穷多元多项式环（lit:000001 p.2 逐字）。
- `stmt:000002` 「Witt 代数」两种命名约定（lit:000002 用 W(1)=Der K[t]，lit:000001 用 W=Der(k[t,t^-1]) 并记 Der(k[t]) 为 W≥−1）——混用会导出错误的有限余维推断。
- `stmt:000005` 有限余维子代数的 Noetherian 传递性（U(h) Noetherian ⇔ U(g) Noetherian，lit:000001 p.2）⇒ 靠「加一个有限维理想」造不出反例，反例必须本质无限维。
- 工作定义（本轮沿用，来源是实验/计划参数段而**不是文献**）：h_∞ = span{a_i,b_i,z : i=1..∞}，[a_i,b_i]=z，其余括号 0，PBW 基 z^k a^α b^β；见 `exp:000008` 脚本参数段与 `attack_plans` 000001 子目标 T1/T2 的 testable.params。

## 三、已确定的结论（按证据强度分档）

| 命题 | 落点 | 强度 |
|---|---|---|
| 有限维 ⇒ Noetherian（PBW/滤过） | `stmt:000007`（proof_text 空） | heuristic（经典，本地无逐字出处） |
| 无限维阿贝尔 ⇒ 非 Noetherian | `stmt:000004` | cross_check（逐字引文） |
| simple Z^n-graded（齐次分支有限维）下 Noetherian ⇒ 有限维 | `stmt:000010` | cross_check（强假设，不可省） |
| KN 类 / Witt 类 ⇒ 非 Noetherian | `stmt:000008` / `stmt:000009` | cross_check |
| 有限余维传递性 | `stmt:000005` | cross_check |
| h_∞ 截断族 I_1 ⊊ … ⊊ I_8 | `exp:000008`（code/expA_truncated_chain.py，code_hash 前缀 e0f9cf577d0d56b6） | cross_check（数值，n≤8、PBW 次数≤5 界内） |
| 中心平移族 J_n 两两互不包含（不是链） | `exp:000010`（code/expB_center_translation_chain.py，code_hash 前缀 5d4924f05e1792b0） | cross_check（数值，带 counterexample） |
| 一般问题（U(g) Noetherian ⇒ dim g<∞） | `stmt:000006` | 公开猜想，未证明、未反驳 |

## 四、尝试与失败

- **技术性**：A 首轮只登记到题名/DOI，lit:000000 / lit:000003 / lit:000004 无本地全文，无法产出逐字引文 ⇒ 不作证据、只作线索。
- **部分补救**：r-000003 取得 lit:000000（Sierra–Walton 2014）全文并挂盘。
- **仍未补救**：lit:000004（McConnell–Robson）全文始终未取得；其候选摘要字段返回的是与本书无关的 Goldie 定理文字，元数据不一致 ⇒ 未采信。
- **结构性（重要）**：`attack.step` 参数面封闭（只允许 plan_id），步骤依据 `cites` 与 `script_path` 只能在 create_plan 时写进子目标 ⇒ `attack_plans` 000000 两轮 step 均 `no_change`（S1 缺 cites、S2 缺 script_path）。处置：另立 000001 并在立项时把两格写进子目标，随后每轮均 progress。同一 problem_key 重复 create_plan 只返回既有计划，原地重立无效。
- **技术性**：`exp:000009` 因脚本自检缺陷作废，由 `exp:000010` 取代。
- **反例不成立（候选族被封）**：中心平移族 J_n=U(g)·(a_1b_1−n·z) 两两互不包含（`exp:000010` 带分离泛函证书）⇒ 该族造不出升链。这是对候选链路的否证，**不是**对主猜想的否证。
- **仍未做（s3 余数级证书）**：s3 只到布尔级（out/experiments/000008.log 第 12,14,16–20 行逐条 n=1..7 的 strict/subset/certificate 读数），**余数向量证书仍缺**；n>8 未跑、脚本不覆盖。
- **不是失败但必须记**：「无限维非交换 g 而 U(g) Noetherian」的例子本轮仍未命中 ⇒ `not_searched_here`，**不得**写成「不存在」。
- **等待集结构性停摆**：r-000004 的 lit:000023（Bell–Buzaglo IMRN 2025）与 lit:000024（Kobayashi–Sanami 1990）**只有 metadata、无本地全文**，B 无从消化 ⇒ 该请求永远停在 waiting_b。这是「没读到」，不是「没有内容」；lit:000005–000022 经 A 复核与本问句无关，**禁作证据**。

## 五、例子与反例

- 文献例：无限维阿贝尔 g ⇒ U(g) ≅ Sym(g) 非 Noetherian（`stmt:000004`）。
- 文献例：Witt / KN 类 ⇒ 非 Noetherian（`stmt:000008`、`stmt:000009`）。
- 数值例（E 造）：h_∞ 截断族在 n=1..8 严格上升（`exp:000008`，复现：`python code/expA_truncated_chain.py`）；**只覆盖声明界，不外推**。
- 数值反例（E 造）：中心平移族两两互不包含的逐对分离泛函证书（`exp:000010`）——反证的是「该族构成升链」这条候选命题。
- **主猜想层面的反例：无**。没有任何「无限维 g 而 U(g) Noetherian」的实例被找到或构造出来；这一格空着是查询结果，不是结论。

## 六、未解问题

1. (c) 档一般情形的真假仍未知（`stmt:000006`）。
2. 否定方向需要显式无限维非交换 g + 非 Noetherian 性证明（或反之，一条带附加假设的反向蕴含定理）。
3. `stmt:000007` 缺逐字出处；`stmt:000010` 的「齐次分支有限维」假设去掉后是否仍成立，未知。
4. `stmt:000005` 能否把问题归约到可数维 / 有限生成情形。
5. `exp:000008` 的 n≤8 能否推广成对任意 n 的统一论证（目前无归纳步骤）；s3 的余数级证书仍缺。
6. lit:000023 / lit:000024 / lit:000004 仍无本地全文。

## 七、下一步

1. **A**：只指向仍缺的两件事之一——(i) 无限维非交换 g 而 U(g) Noetherian 的构造，(ii) 带附加假设（幂零/可解/有限增长/affine Kac–Moody）的反向蕴含定理；英文关键词，短题名式。
2. **E**：补齐 s3 的余数级证书（逐 n 输出约化余数向量），并把界固化在 n≤8、PBW 次数≤5。
3. **F**（D→F 边）：在 plan 000001 余下预算（`max_rounds_left=2`）内推进 T2 收口；S1 的 F_∞ 方向需另立 problem_key（cross_check 级中间结论，不构成反例）。
4. **G/H**：不得把 `stmt:000006` 当定理用；`exp:000008` 只能写成「n≤8 的截断族逐项严格上升（数值，cross_check）」；`stmt:000007` 引用前须先补逐字出处。
5. **D 自己（下一趟）**：问题 000000 已如实推 `dropped`（理由：核心是公开猜想，本地证据无法收口；缺口已交 A）；接手者先读本手稿，再决定是否以新 qid 重开。
