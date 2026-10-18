# 研究报告 000000：U(g) Noetherian 是否一定推出 dim_k g < ∞

- 问题：`research_questions` 000000（kind=gap，priority=medium）
- 猜想：`conjectures` 000000（form=universal，status=known_in_literature，known_lit_id=000001）
- 攻坚：`attack_plans` 000000（problem_key=000000，2 轮 step 均 no_change）与 000001（problem_key=000000-S2，parent_plan_id=000000，rounds=4，status=attacking）
- 检索：r-000002 / r-000003 / r-000004 三条 outcome=ok；r-000004 的 lit:000023、lit:000024 仅 metadata、无本地全文（B 无从消化）
- 证据等级上限：**cross_check / heuristic**。本会话 Lean 形式化关闭 ⇒ 本报告任何一处都不写「已证明」
- 落点：本文件是工作稿（不进任何报告表）；跨趟记忆见 `reports/RESEARCH.md`

## 一、分析

### 1. 三档划分（本报告的主结构）

| 档 | 命题 | 证据落点 | 强度 |
|---|---|---|---|
| **已判定 (a)** | dim_k g < ∞ ⇒ U(g) Noetherian（PBW/滤过：gr U(g) ≅ Sym(g) 有限生成多项式环） | `stmt:000007`（proof_text 为空，evidence_kind=heuristic） | heuristic（经典，本地无逐字原文：lit:000004 McConnell–Robson 全文未取得） |
| **已判定 (b)** | 无限维阿贝尔 g ⇒ U(g) ≅ Sym(g) 为无穷多元多项式环 ⇒ 非 Noetherian | `stmt:000004`（lit:000001 p.2，quote_verified=true）；数值侧 `exp:000000` | cross_check |
| **条件性判定 (c)** | simple Z^n-graded 且齐次分支全有限维 ⇒ U(g) Noetherian ⇒ dim g < ∞（强假设，假设不可省） | `stmt:000010`（lit:000002 Theorem 1.3） | cross_check |
| **条件性判定 (d)** | KN 类 / Witt 类 ⇒ U(W) 非 Noetherian | `stmt:000008` / `stmt:000009` | cross_check |
| **条件性判定 (e)** | h ⊂ g 有限余维 ⇒ U(h) Noetherian ⇔ U(g) Noetherian（故「加有限维理想」造不出反例，反例必须本质无限维） | `stmt:000005`（lit:000001 p.2） | cross_check |
| **未判定** | 一般无限维**非交换** g：U(g) Noetherian ⇒ dim_k g < ∞? | `stmt:000006`（Sierra–Walton 猜想，quote_verified，lit:000001 p.2 / lit:000002 p.1） | 公开猜想，**不是定理**；主流预期答 no，但本轮无任何构造 |

### 2. 原问题在文献里已有名有姓，且是未解猜想

- Sierra–Walton 写成 Conjecture 0.1（lit:000001 引作 [7, Conjecture 0.1]），Andruskiewitsch–Mathieu 引作 Conjecture 1.1（lit:000002 p.1）。逐字落点 `stmt:000006`。
- lit:000001 p.2 逐字："It is widely believed that the answer to this question is \"no\"" —— 即学界普遍猜**存在**无限维 g 而 U(g) Noetherian，但至今无公开反例落在本地库里。
- 因此 (未判定) 这一档**既未被证明、也未被反驳**；本轮对它的处置只能是「未判定」，不得写成「否」也不得写成「是」。

### 3. 攻坚链的实际推进（plan 000001，本轮 F 回报）

`attack.status 000001` 现读：rounds=4，status=attacking，budget_left.max_rounds_left=2，subgoal_counts={in_progress:1, todo:7}。history 里 outcome=progress 的两条（原样摘录关键字段）：

- **round 1**：`sid=T1`，`action=counterexample_request`，`outcome=progress`，`strategy=小情形搜索找模式`，`product=counterexample_request`；`detail` 原文：「把这一轮的实验判据交给 E（新子目标 s1）：该请求把 T1 的每个 n 化为有限维精确线性代数问题：包含性由约化余数是否为 0 决定，非包含性由精确有理数线性系统是否不可解决定。脚本的 SHA-256 与 exit 0 锁定执行版本；逐项输出使每个 n 的证书可独立复算。若全部通过，则只在声明界 n<=8、PBW 次数<=5 内支持逐项严格上升；若失败，则失败 n 就是受控反例位置。」
- **round 2**：`sid=T1`，`action=reduction`，`outcome=progress`；`detail` 原文：「归约（小情形搜索找模式）：T1 是 n=1..8 的有限情形集合，PBW 次数 <=5，包含关系与严格性都能化为有限个 PBW 单项式约化和非零坐标检查；用逐项小情形搜索比引入更高层结构论证更适合当前无 Lean 形式化、证据等级上限为 cross_check/heuristic 的限制，也能在失败时直接定位到具体 n 并生成受控反例证书。；新子目标 ['s2', 's3', 's4']（每条都带可检验形式）」

本轮（第 3-4 轮）F 的逐子目标读数（见 `reports/attack-000001.md`，末次 sha256 前缀 8d28b456d25d7f49，与手稿 000034 一致）：

- **s2（progress）**：`verify.code_hash` 实测 `code/expA_truncated_chain.py`=e0f9cf577d0d56b6（与 `exp:000008` 记录一致、exit 0）、`code/expB_center_translation_chain.py`=5d4924f05e1792b0（与 `exp:000010` 记录一致、exit 0）⇒ 在册实验的执行版本可锁定。testable：两哈希逐字节一致 + exit 0；改脚本即哈希变、旧读数失效须重跑。
- **s3（progress，布尔级）**：`out/experiments/000008.log` 第 12,14,16-20 行为 n=1..7 的 `strict=true, subset_holds=true, certificate_verified=true`（8 成员 7 次相邻比较，与 bound `n_comparisons=[1,7]` 一致）。**余数向量级证书仍缺**（s3 未推到满档）。
- **s4（progress）**：边界隔离完成 —— exp:000010 的 refutes 只封「中心平移族构成升链」这一候选命题，不与 exp:000008 的 supports 混用；n>8 一律不覆盖。
- F 另报一处分派空转（`attack.step` 反复重派 T1 的结构性卡点），已记入手稿 000034 与 `reports/RESEARCH.md` 第四节。

### 4. 数值证据（E，可复现、判等全由代码判）

- `exp:000008`（method=numeric，result=supports，evidence_kind=cross_check）：`code/expA_truncated_chain.py`，code_hash=e0f9cf577d0d56b6；h_∞ 截断族 I_n = sum_{i<=n} U(g)·(a_i b_i)，n=1..8 逐项 I_n ⊊ I_{n+1} 全过。**范围严格限于 n≤8、PBW 次数≤5，不得外推成「U(h_∞) 非 Noetherian」**。
- `exp:000010`（method=numeric，result=refutes，带分离泛函 counterexample）：`code/expB_center_translation_chain.py`，code_hash=5d4924f05e1792b0；J_n = U(g)·(a_1 b_1 − n·z) 两两互不包含 ⇒ 候选族封。
- `exp:000009` 因自检缺陷作废，由 000010 取代。

## 二、结论（三档分开，强度与证据相称）

1. **已判定**：有限维 ⇒ Noetherian（`stmt:000007`，heuristic，本地无逐字原文 —— 这一格是缺口）；无限维阿贝尔 ⇒ 非 Noetherian（`stmt:000004` + `exp:000000`，cross_check）。
2. **条件性判定**：simple Z^n-graded（齐次分支有限维）下 Noetherian ⇒ 有限维（`stmt:000010`）；KN / Witt 类非 Noetherian（`stmt:000008`/`stmt:000009`）；有限余维传递性（`stmt:000005`）。三者都带假设，**不可去假设外推**。
3. **未判定**：一般无限维非交换情形。没有证据支持蕴含普遍成立，也**没有**任何「无限维 g 而 U(g) Noetherian」的实例被找到或构造 —— 后者属 `not_searched_here`，**不得**写成否定结论。
4. 攻坚侧确定读数：plan 000000 两轮 no_change 是**结构性卡点**（`attack.step` 参数面封闭，`cites`/`script_path` 只能在 create_plan 时写进子目标）；plan 000001 的 round1/round2 与本轮 s2/s3/s4 均为 `outcome=progress` 的真推进，但仍是 cross_check 级局部证据。
5. 问题 000000 的诚实处置：核心命题是公开猜想，本地证据在一趟内收不口 ⇒ 按缺口清单与等待集如实落定，不收口成 «answered» 冒充结论。

## 三、缺口清单（可执行的下一步）

仍缺的只有两件事（其余都已落库或已如实记为「读到不到」）：

- **缺口 1**：无限维**非交换** g 而 U(g) Noetherian 的具体构造（或证明其不存在）。
- **缺口 2**：带附加假设（幂零 / 可解 / 有限增长 / affine Kac–Moody）的**反向蕴含定理**：U(g) Noetherian ⇒ dim_k g < ∞。
- 结构性读数：r-000004 的 lit:000023（Bell–Buzaglo, IMRN 2025）与 lit:000024（Kobayashi–Sanami 1990）**只有 metadata、无本地全文** ⇒ `poll_waiting` 这一条会一直停在 `waiting_b`。这是「没读到」不是「没有内容」，也不是 B 的失职。
- lit:000004（McConnell–Robson）全文仍未取得 ⇒ `stmt:000007` 的 proof_text 依旧为空。
- plan 000001 余下：s3 的余数向量级证书、s1/s5 的 E 侧逐 n 复算、budget_left.max_rounds_left=2。

## 四、建议

- **交 A**：两条英文检索式，分别只打缺口 1 与缺口 2；不要再要综述式检索。
- **交 E**：按 sha256 锁定版本复算 exp:000008 的逐 n 余数向量（把 s3 从布尔级推到向量级），界固定 n≤8 / PBW 次数≤5；要外推须另立带更大界与独立脚本的子目标。
- **交 F**：plan 000001 余 2 轮，优先把 s3 推到向量级、把 T2 收成否证记录；再另立 problem_key 覆盖 S1 的 F_∞ 方向（F 的 P1 只是 cross_check 中间结论）与 S3 的充分条件族。
- **交 G/H**：`stmt:000006` 只能写成猜想；`stmt:000007` proof_text 为空，引用前须补 PBW 滤过论证的逐字出处或证明；`exp:000008` 只能写成「n≤8 的截断族逐项严格上升（数值，cross_check）」。

## 五、未解问题（留给下一趟）

1. 缺口 1 / 缺口 2 两条（见第三节）——本趟未动。
2. 「widely believed answer is no」背后的具体证据是什么？（lit:000001 只给信念陈述，没给反例）
3. 非分次的无限维单 Lie 代数有无 Noetherian 判据？
4. `stmt:000005` 能否把问题归约到「可数维 / 有限生成」情形？
5. `exp:000008` 的 n≤8 结论能否给出统一归纳步骤（现只有逐 n 数值证书）？
