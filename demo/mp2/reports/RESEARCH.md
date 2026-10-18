# 等弦点问题（Equichordal Point Problem）研究手稿

- 维护：D（本轮台账号 t-000006，深度 2，由 M 发起）
- 问题台账：research_questions `000000`
- 证据上限：**cross_check**（本会话 Lean 形式化关闭，无 proof 级凭据；任何断言都不是已证明）
- 本轮可用材料：literature `000000`–`000009`（A 登记）；experiments `000000`–`000003`（E 落库，method=numeric）；交接手稿 000000（E → D）

---

## 0. 本轮更新（t-000046，D；下一个接手的人先读这一节）

- **conjecture `000001`：`proposed` → `supported_not_proved`**（cross_check 数值支持，**不是证明**）。`experiment_ids` = experiments `000002`、`000019`（均 `method=numeric`、`evidence_kind=cross_check`、`exit_code=0`）：exp:`000002`（`code/eq_run_fourier.py`，`code_hash` 前 16 位 `3a8574a0e1287b2a`）给 odd_control 在原点 P=0 处 Var L≈6e-28；exp:`000019`（`code/eq_fourier_odd_second_point_search.py`，`code_hash` 前 16 位 `48a4a799ec8c377a`）在 ε∈{1e-3,3e-3,1e-2,3e-2}、|P|≤0.9·rmax 且 |P|≥1e-6 的多起点搜索 + 2000 方向方差 / 8000 方向复核下未找到第二等弦点（`result=supports`）。

- **conjecture `000000`：`testing` → `supported_not_proved`**（不是 proved：Lean 关闭，无 proof 级凭据）。`experiment_ids` = experiments `000000`、`000004`、`000008`、`000010`（全部 `method=numeric`、`evidence_kind=cross_check`、`exit_code=0`）；experiments `000009` 是 `exit_code=1` 的 `inconclusive` 作废行，不列入。三条限制照旧：a/b≥2.5 的 `P*` 落在 `|P|=0.9·min(a,b)` 边界（无全局下界证书）；a/b→1 时 `var_inf→0`（无一致正下界）；无 proof 级凭据。
- **`known_lit_id` 保持空、不置 `known_in_literature`**：rel:`000003`（lit:`000007`，Klee 1960，framework p.31 = printed p.27，`quote_verified=true`）逐字原文否证的是「关于其星形的 Jordan 曲线有两个相异等弦点」，而本猜想断言的是「a≠b 椭圆连**一个**等弦点都没有」（更强），故不覆盖。
- **research_questions `000000`：`needs_evidence` → `researching` → `answered`**（本趟收口）。(i) 凸情形：由 rel:`000002`（lit:`000007`，framework p.31 = printed p.27，`quote_verified=true`）逐字『no 2e-curve (of a type that includes convex curves) can have two equichordal points』支撑为 **known_in_literature，口径=二手**（Grünbaum 对 K10 的评注，不是 Rychlik 原文；本会话未逐字核 Rychlik 1997，lit:`000000` 无本地全文）。(ii) 一般非凸：rel:`000003`（同页，`quote_verified=true`）逐字覆盖『关于其星形的 Jordan 曲线』⇒『非凸=完全未解』不成立；但『任意非星形非凸简单闭曲线』无覆盖文献，残余缺口已收窄到一步（缺 lit:`000000` 定理陈述页逐字，或一篇明说该情形的文献），并**明写超出本会话可判范围**（无 Rychlik 原件全文）。
- **上一轮（t-000042）的读数保留**：conjecture `000000` = `supported_not_proved`（`experiment_ids`=experiments `000000`/`000004`/`000008`/`000010`；experiments `000009` exit=1 作废不列入），`known_lit_id` 仍空（rel:`000003` 只否证『关于其星形的 Jordan 曲线有两个等弦点』，不覆盖『a≠b 椭圆连一个等弦点都没有』）。三条限制照旧：a/b≥2.5 的 `P*` 落在 `|P|=0.9·min(a,b)` 边界（无全局下界证书）、a/b→1 时 `var_inf→0`（无一致正下界）、无 proof 级凭据（Lean 关闭）。
- **下一步（接手的人从这里起手，不要重做已收口部分）**：残余缺口只有一条 —— 取 lit:`000000`（Rychlik 1997）定理陈述页的逐字引文，或一篇明说『非星形非凸简单闭曲线』情形的文献；取法：A 把正文落地（r-000008 的 `result_lit_ids` 里 lit:`000010`–`000031` 与 lit:`000008` 现均 `processed=false`，三态=未取到正文、不是不存在）→ B 抽成 `relations` 行。**在此之前不许把『任意非星形非凸』写成已解或不存在。**

---

- **本轮追加（A 回执，名册 A1 / t-000047，outcome=ok）**：lit:`000000` 的 PDF 本就在盘，整本文字层转换被质量闸拒收（`kind=garbled_text`），第 1–6 页（印刷页 141–146）已入库 `library/000000.txt`；A 报「定理 1 及精确假设在第 3 页定位（matched=exact）」并已交 B（手稿 000035），另报「任意非星形非凸」不在定理假设里。纪律：以上均为 **A 的转述、不是逐字引文**，本节不据此改任何结论；残余缺口的下一个动作在 B（从 `library/000000.txt` 抽 `quote_verified=true` 的 rel 行），B 落行之前 question `000000` 的 `answered` 只覆盖 (i) 与 (ii) 的「星形」段。
- **未解问题与下一步**：唯一残余缺口 = 「任意非星形非凸简单闭曲线」是否有覆盖文献（或反例）——待 B 抽行后由 D 判；若仍无，按三态记「本轮未找到覆盖文献」，不得写成「已解」或「不存在」。

## 1. 成果概述

**这一节里每一句声称都指到别人落的落点；指不到的一律写「没有落点」。**

- **证明了哪些命题：无。** 本轮**没有**任何 `statements.proof_text` 落点（F 未开工），也**没有** `evidence_kind=proof` 的实验行 —— 本会话 Lean 关闭，proof 这一档产不出来。凡下文出现「成立」，一律指「有数值/文献支持」，**不指已证明**。
- **证伪了哪些猜想：无。** 两条登记的猜想（conjectures `000000`、`000001`）状态分别是 `testing` 与 `proposed`，都**没有**被反驳，也都没有 `counterexample_experiment_id`。
- **本轮（t-000025）新增的攻坚推进**（引 F 落盘的 attack_plans 行与 E 的实验行，不引任何未落盘的读数）：针对 conjecture `000000` 的攻击计划 plan_id=`000000`（problem_key=`000000`，子目标 3 条，budget `max_rounds=6`）已立项并推进 3 轮。history 原文三档：第 1、2 轮 `no_change`（「子目标 S1 派给 E，但没有给 `script_path` ⇒ **未推进**」），第 3 轮 `evidence_bound`。S1、S2 落 `supported_not_proved`，证据分别是 experiments `000008`（`scripts/eq_s1_powerlaw.py`，`code_hash` 前 16 位 `56a3bc5afaa8e095`，exit=0，11/11 点：var_inf 由 1.2254e-09（a/b=1.01）单调升到 1.4837（a/b=5），11 点全 >0）与 experiments `000010`（`scripts/eq_s2_pointwise_inf_v2.py`，`code_hash` 前 16 位 `bdf8e4a8238a1063`，exit=0，3.19s，`result=supports`；a/b=1.01 的 P*≈(-3.74e-10,-0.140371) 两侧方差同为 1.22537006e-09，a/b=1.1 的 P*≈(-2.47e-10,0.416616) 两侧同为 1.03304980e-05，均远 >1e-18，未命中 refutation_criterion）。**这两条只是数值支持，不是证明，也不构成对猜想的升级。** experiments `000009` exit=1 ⇒ `inconclusive`，其进度行不作结论，已由 `000010` 取代。S3 仍 `todo`，`blocked_reason` 原文：「依赖 S2 的最优点坐标：现有 exp:000010 只覆盖 a/b=1.01 与 1.1 两点，且 a/b>=2.5 时 S1 的 P* 落在 |P|=0.9*min(a,b) 搜索域边界（边界绑定未解），局部解析展开尚缺可信的极小点」。
- **做了哪些数值实验 / 测过哪些样例**（全部引 E 的代码文件与实验行，`evidence_kind=cross_check`、`exit_code=0`）：
  - 椭圆族无等弦点的数值支持：experiments `000000`，脚本 `code/eq_run_ellipse.py`（`code_hash` 前 16 位 `d9360f52db20abcf`），`result=supports`；5 个 `(a,b)` 上弦长方差下确界全部 > 0，最小者 `1.0330e-05`（`a/b=1.1`），其余 `0.030883 / 0.0034659 / 0.210864 / 0.019917`（见该行 `observations.data.cases` 与 `observations.min_var_over_cases`）。
  - 圆对照（算法能不能认出真等弦点）：experiments `000001`，脚本 `code/eq_run_circle.py`（`code_hash` 前 16 位 `600be5a53040762e`），`result=supports`；`P_star=(0,0)`、方差压到 `2.045e-27` 量级、`mean chord=2.0000000`。
  - Fourier 扰动族残差随 ε 的标度：experiments `000002`，脚本 `code/eq_run_fourier.py`；两点最小二乘残差 `2.128e-07 → 3.760e-04`（genericA）、`2.850e-07 → 5.002e-04`（genericB），拟合斜率 **1.885（R²=0.9975）**；`odd_control` 原点方差 ≈ `6e-28`。
  - 折线参考实现的自检异常：experiments `000003`，脚本 `code/eq_check_polyline.py`；`fast vs analytic` 最大偏差 `6.35e-14`，`polyline vs analytic` 偏差 `2.0`（2000 方向里 1517 个坏）—— 判定为**参考实现的近原点退化**，不是快方法算错。
- **过程中总结到的经验**（两条，都是本轮的取舍）：
  1. **「下确界 > 0」不是一个均匀的结论**：experiments `000000` 里 `a/b→1` 时 `var_inf→0`（`a/b=1.1` 时 `1.0330e-05`，`a/b=3` 时 `0.210864`）—— 数值上越接近圆越难判，所以「椭圆无等弦点」的数值证据强度**不是**在参数空间上均匀的，报告里不许把它写成「已在整个族上验证」。
  2. **参考实现出错会伪装成主方法出错**：experiments `000003` 的诊断说明，自检项 `polyline_crosscheck=2.0` 本身是坏读数，用解析弦长 `2√(1−d²)` 当裁判才分得清谁错。这条写进「尝试与失败」。

---

## 2. 定义与已知

### 定义（本手稿口径，后续接手的人以这里为准）

- **等弦点（equichordal point）**：设 Γ 是平面简单闭曲线，P 是 Γ 内一点。若过 P 的每一条弦（直线与 Γ 相交所得、以 P 为中点或不过中点均可，按文献口径为「过 P 的整条弦」）长度都相等，则称 P 是 Γ 的一个等弦点。
  —— 这一条定义目前**只有文献摘要层**的支持（literature `000001` 的 `summary` 写「defines equichordal points (every chord through the point has equal length)」），**没有逐字引文**（该行 `processed=false`，relations 表里没有对应关系行）。**口径按摘要层记，未逐字回验。**
- **本问题的判据（可算的那一个）**：固定 P，令 L_P(φ) 为方向 φ 上的弦长，考察 Var_φ L_P(φ)。P 是等弦点 ⟺ Var_φ L_P(φ) = 0。E 的所有实验用的都是这一判据（experiments `000000` 的 `claim` 与 `observations.strategy`）。

### 已登记的文献地图（lit:000000–lit:000009，只引 literature 行里真有的字段：`title` / `year` / `doi` / `summary`）

| lit | 题名（年） | 它在本问题上的位置 |
|---|---|---|
| lit:000000 | *A complete solution to the equichordal point problem of Fujiwara, Blaschke, Rothe and Weizenböck*（1997，Invent. Math. 129(1) 141–212，doi:10.1007/s002220050161） | **核心**：`summary` 称「no plane convex body has two distinct equichordal points」，方法归结为多值代数映射的异宿连接不存在 |
| lit:000001 | *The Equichordal Point Problem*（1996） | Rychlik 的宣告稿；`summary` 给出定义与 Fujiwara(1916)/Blaschke–Rothe–Weitzenböck(1917) 的问题来源 |
| lit:000002 | *Equichordal Points of Convex Bodies*（2025，Jang & Kim，arXiv:2501.02159） | 凸体的现代处理（推广到高维） |
| lit:000003 | *Why is Helfenstein's claim about equichordal points false?*（2012，Rychlik，arXiv:1202.1609） | **反证型参考**：Helfenstein 1956 的构造因计算错误不成立 |
| lit:000004 | *Equipower and equichordal extension*（2004，Stępnicki） | 轴对称凸曲线的延拓判据（二阶微分不等式），边缘相关 |
| lit:000005 | *Hedgehogs of constant width and equichordal points*（1997，Martinez-Maure） | 有等弦点的凸超曲面的**刻画**（局部对应物） |
| lit:000006 | *Can a Plane Convex Body have Two Equichordal Points?*（1969，Klee，Amer. Math. Monthly 76(1) 54–55） | 把它作为**未解决问题**提出；`summary` 称后被 Rychlik 否定解决 |
| lit:000007 | *Unsolved Problems in Intuitive Geometry*（1960，Klee） | 问题集，背景/开源出处，非证明 |
| lit:000008 | *Chord functions and equichordal problems*（2006，Gardner，Geometric Tomography ch.6） | 弦函数框架下的等弦型问题 |
| lit:000009 | *An equichordal characterization of the ellipsoid and the sphere*（2026） | 现代刻画型对应物 |

**关于这张表的三条限制（必须跟着表一起传下去）**：
1. 这 10 行的 `processed` 全部为 `false`，`download.status` 全部为 `skipped`（`error=no_local_path`）—— 即**没有任何一篇有本地全文**，因此**本手稿里没有一句逐字引文**，全部只有 `summary` 层的转述。
2. 因此「Rychlik 1997 否定了凸体情形」这句话在本轮的证据强度是**摘要层 + 无逐字回验**，**不是**「已读原文确认定理的假设与结论」。
3. 凸体情形与一般非凸情形的**边界**目前只有摘要层说法（lit:000000 的 `summary` 只提 convex body），**没有**任何一行文献明确说「非凸情形仍开放」或「非凸情形也被解决」。这是本条问题当前最大的证据缺口（见第 6 节，已提交 r-000008）。

---

## 3. 已确定的结论

> 「已确定」= **在给定证据上限（cross_check）下能站住的结论**，不指数学上已证明。

**结论 C1（确定，数值级）。圆是判据的可靠对照组。**
依据：experiments `000001`（`code/eq_run_circle.py`，`code_hash` 前 16 位 `600be5a53040762e`，`result=supports`）在 `P_star=(0,0)` 处给出方差 `2.045e-27`、`mean chord=2.0000000`。这说明「最小化 Var_φ L_P(φ)」这套算法在**存在**零方差点时确实能把方差压到机器零，而不是被数值噪声顶在正数上。**它的作用是把 C2 的读数变成可解释的**：椭圆上那个 `1.0330e-05` 不是算法分辨率的下限。

**结论 C2（确定，数值级，范围有限）。在 experiments `000000` 测过的 5 个椭圆上，弦长方差下确界严格大于 0。**
依据：experiments `000000`（`code/eq_run_ellipse.py`，`result=supports`），`observations.min_var_over_cases = 1.0330498044039167e-05`，逐例 `0.030883 / 0.0034659 / 0.210864 / 0.019917 / 1.0330e-05`。**范围限制（必须与结论同时引用）**：只覆盖 `(a,b) ∈ {(2,1),(1.5,1),(3,1),(2.5,1.5),(1.1,1)}`、2000 方向、搜索域 `|P| <= 0.6*min(a,b)`（该行 `observations.bound` 明写「数值判据，不是证明」）。

**结论 C3（确定，诊断级）。experiments `000001` 的 `polyline_crosscheck=2.0` 是参考实现退化，不是快方法算错。**
依据：experiments `000003`（`code/eq_check_polyline.py`）以解析弦长 `2√(1−d²)` 为裁判，`fast vs analytic` 最大偏差 `6.35e-14`，而折线参考在 2000 个方向里 1517 个坏。这条结论的价值是**排除了一个伪故障**：若不做这一步，`2.0` 会被误读成「主方法在近原点处失效」。

**结论 C4（确定，结构级）。本问题的「一般情形」与「凸情形」是两个不同强度的命题，本轮证据只覆盖后者。**
依据：lit:000000 的 `summary` 只声明 convex body；lit:000002 的 `summary` 也只讲 convex bodies；lit:000005、lit:000009 都是凸体/凸超曲面的刻画。**没有**任何已登记文献陈述一般非凸情形。这是**缺口**（第 6 节），不是结论说「非凸情形开放」——那是**没查到**，不是**不存在**（三态纪律）。

**结论 C5（数值级，范围有限）。椭圆族在 a/b∈{1.01,1.05,1.1,1.3,1.5,2,2.5,3,5} 上弦长方差下确界全部 >0，且 a/b∈{2.5,3,5} 的极小点不再是搜索域边界解（S1 边界绑定部分解开）。** 依据：experiments `000012`（`scripts/eq_s3c_confirm_ladder.py`，`code_hash` 前 16 位 `7893f134cb258f81`，exit=0，`result=supports`）：|P|≤0.99·min(a,b) 上 |P*|≈0.92383/0.95174/0.98920、`flat_between_0.99_and_0.999_all_ratios=true`；experiments `000015`（`scripts/eq_s3f_full_ellipse_search.py`，`9cfaf334e9e0a337`）：全椭圆 s≤0.98 重算 rel≈1e-13、`cases_below_disk_ref` 为空；experiments `000017`（`scripts/eq_s3g_boundary_layer.py`，`6f3b0b157827ab52`）：边界层 s∈[0.9,0.999] `tail_non_decreasing=true`、`boundary_bound_ratios` 为空。**范围：仅数值，无全局证书；a/b>5 与 a/b<1.01 未覆盖。**

**结论 C6（数值级）。S2 已扩到 a/b=1.5/2/3。** 依据 experiments `000012`：P*=(1.09e-09,-0.746758)/(-1.15e-09,-0.870680)/(-3.46e-10,0.951742)，`on_domain_boundary=false`，var_2000=var_8000=3.4658867033e-03/3.0883124670e-02/2.1086432542e-01 ≫1e-18。

**结论 C7（数值级，仅局部）。7 个已登记 P* 均为局部极小。** 依据 experiments `000018`（`scripts/eq_s3i_local_analytic.py`，`6b4ed827feddc944`，exit=0，5.83s，`result=supports`，输入 `data/s3_ref_coords.json`）：Hessian 2×2 λ_min 全 >0（1.98e-02…6.30e-01）、Var8000(mp50) 全 >1e-18、与登记值相对差 ≤7.27e-09。**只证局部，不证全局；S3 由此从 todo 变 supported_not_proved。**

**不成立的写法（明确禁止，写给接手的人）**：不许把 C5/C7 写成「椭圆族无等弦点已被证明」；不许把 C7 写成全局最小性。不许把 C2 写成「椭圆族无等弦点已被证明」；不许把 lit:000000 写成「已核实其定理假设」。citations 级证据是 `summary` 转述，`quote_verified` 从未为真。

---

## 4. 尝试与失败

> 纪律：每次失败写清卡在哪一步、属哪一档（技术性 / 结构性 / 反例不成立）。不建失败模式库。

- **F1｜想给「椭圆无等弦点」找一条可核的独立证明 —— 卡在「没有原文、没有关系行」。**
  档：**结构性**。卡点：lit:000000 等 10 行 `processed=false`、`download.status=skipped`、`path=null`，relations 表里没有一条等弦点关系行，所以既不能逐字引「凸体」这个假设，也不能引定理的结论。已把这一条转成检索请求 r-000008（`submit_gap` 落到 search_requests，并进 research_questions `000000` 的 `waiting_request_ids`）。
  可挽救性：需要 A 拿到 Rychlik 1997 的正文（或至少定理陈述页），再由 B 抽成带 `quote` 的关系行；预算估计：1 轮检索 + 1 轮 B 整理。

- **F2｜想用「a/b 越大越容易/jac 越小越难」的直觉把 C2 推广 —— 被自己的读数反驳。**
  档：**技术性（判据不成立）**。卡点：experiments `000000` 的读数**不单调**于 `a/b`：`a/b=3` 的 `var_inf=0.210864` 远大于 `a/b=1.5` 的 `0.0034659`，而最小的 `1.0330e-05` 出现在 `a/b=1.1`。所以「下确界随偏心率单调」这个想法是错的；正确读法是「越接近圆，下确界越小，判据越接近分辨极限」。结论：**放弃这个直觉**，C2 只按逐例读数陈述。

- **F3｜想用折线参考实现做独立交叉验证 —— 参考实现本身坏了。**
  档：**技术性（已查清，不是数学问题）**。卡点：近原点处折线求交退化，`polyline_crosscheck=2.0`。处理：换解析弦长当裁判（experiments `000003`），确认快方法 `6.35e-14` 准确。这条**不构成**对 C2 的打击，但它提醒：本问题上任何「两个实现互相比对」的验证，先要问参考实现自己准不准。

- **F4｜想用 Fourier 族的残差斜率当「存在第二等弦点」的证据 —— 目前只能说「残差不下降」。**
  档：**结构性（缺一条实验）**。卡点：experiments `000002` 测的是**两点最小二乘残差**随 ε 的标度（slope 1.885，R²=0.9975），它说明扰动族在「要同时满足两个点等弦」这件事上越来越难，但**没有**在原点之外做完整最小化搜索，所以不能反推「不存在第二等弦点」。已把这条写成猜想 `000001` 的 `testable`（谁=E、怎么被推翻、判据阈值 1e-18），等待实验。

---

## 5. 例子与反例

> 这一节由 E 的数值实验供料；**没有落点的例子不写**。

- **例子 E1（正例 / 对照组）。单位圆 + 圆心。**
  落点：experiments `000001`（`code/eq_run_circle.py`）。读数：`P_star=(0,0)`、方差 `2.045e-27`、`mean chord=2.0000000`。意义：这是「等弦点存在」的已知例子，用来标定判据的分辨率。附带读数：偏心 r 处 var≈r⁴/8（r=0.01→1.25e-9，r=0.3→1.06e-3）。

- **例子 E2（候选反例的排除 / 椭圆族）。5 个椭圆全部方差 > 0。**
  落点：experiments `000000`（`code/eq_run_ellipse.py`），`observations.data.cases`：`(2,1)→0.030883`、`(1.5,1)→0.0034659`、`(3,1)→0.210864`、`(2.5,1.5)→0.019917`、`(1.1,1)→1.0330e-05`；每条的最小点 `P_star` 全在短轴上（`(0,0.8707)`/`(0,0.7468)`/`(0,0.9517)`/`(0,1.2037)`/`(0,0.4166)`）。**注意**：`P_star` 只是「方差最小处」，**不是**等弦点 —— 这些点上方差并不为 0。

- **反例（真反例）：本轮一条也没有。** 关于「Helfenstein 的构造」：lit:000003 的 `summary` 称其 1956 年的论文因计算错误而结论不成立。这是**文献层的转述**，**没有**本地全文、**没有**逐字引文，所以本手稿**不把它当作已核的反例**，只记为「文献称其为错误的构造」。

- **一个必须避免的误读**：把 experiments `000002` 的 `odd_control var1≈6e-28` 当作「Fourier 奇谐波族已在原点精确等弦」的证明。它只是 cross_check 读数，且 `exp:000002` 的 `result` 是数值判据；原件里 `data.strategy` 也不含完备性论证。猜想 `000001` 因此保留 `proposed`。

---

## 6. 未解问题（按「卡在哪一步」分开写）

| # | 问题 | 卡在哪一步 | 缺的是哪一条 | 去处 |
|---|---|---|---|---|
| Q1 | **凸体情形**：Rychlik 1997 的定理到底以什么假设、什么结论成立？ | 缺原文 | 缺 lit:000000 的正文/定理陈述页 ⇒ 缺一条 `quote_verified=true` 的 relation 行 | 已在等待集：`search_requests` **r-000008**（research_questions `000000.waiting_request_ids`） |
| Q2 | **一般非凸情形**：一条非凸的简单闭曲线能否有两个相异等弦点？被解决了、还是开放？ | 缺定义/缺证据 | 缺任何一篇陈述非凸情形的文献（已登记 10 篇全是凸体口径） | 同 r-000008（检索式已写进该请求的 `description`） |
| Q3 | **对称代数特例如椭圆**：能否给一条不依赖一般定理的独立证明？ | 缺证明 | 缺 F 的一轮攻坚（`statements.proof_text` 空）；目前只有数值（C2） | 应转给 F（见第 7 节） |
| Q4 | **Fourier 奇谐波族是否真的不含第二等弦点？** | 缺实验 | 缺一次「原点之外多起点最小化」实验（不是残差斜率） | 猜想 `000001.testable` 已写清判据；待 E 执行 |
| Q5 | **椭圆族的下确界随 (a,b) 怎么变？** 是否 `var_inf(a,b) > c(a/b)` 有正的下界？ | 缺证据（且已有读数提示不单调） | 缺参数网格加密实验；`a/b→1` 时 `var_inf→0` 使「一致下界」不可能（除非允许 `a/b` 有界） | 待 E；见第 7 节下一步 |
| Q6 | **全局最小性**：报出的 inf 是真下确界，还是搜索启发式的下界？ | 缺证书 | 缺区间算术/分支定界式的全局下界证书（现为 601 起点网格 + 罗盘搜索到 1e-7，无全局保证；exp `000015` 的 `grid_starts=601`） | plan `000000` 明列的未解决项；待 E/F |
| Q7 | **参数覆盖**：a/b>5 与极近 1（a/b<1.01）没有实验行 | 缺实验 | 缺这两段参数上的读数（exp `000012` 只到 5，起点是 1.01） | 待 E（可复用 `scripts/eq_s3c_confirm_ladder.py`） |

**共同的证据缺口（一句话）**：本问题上**没有任何一条逐字引文** —— 10 条文献全部 `processed=false`、无本地全文。所有文献层陈述都停在 `summary` 转述，达不到证据契约要求的「关系行 + `quote_verified`」。

---

## 7. 下一步

**已提交的请求（不是「写在报告里」就算）**

- `search_requests` **r-000008**（对应 research_questions `000000`）：topic = `equichordal points non-convex simple closed curve`，mode = `topical`；description 里写明了要的是「Rychlik 1997 定理的**假设与结论原文**」与「非凸情形是被覆盖还是仍开放」两条，并给了英文检索式。**状态：未完成**（`research.poll_waiting` 会给出 ready/not ready）。
- 第二次 `submit_gap`（椭圆特例的独立证明检索）被**去重拒绝**：`duplicated=true`，reason 原文「该问题已有未完成的查询请求，未重复提交」—— 这是**没发出去**，不是「查过了没有」。要它落地，得等 r-000008 结束后再提交（记为待办，不要当成已完成）。

**给下一跳的具体动作（按优先级）**

1. **A**：完成 r-000008；若拿到 Rychlik 1997 的正文（哪怕只有定理陈述页），把它交给 B 抽成 relation 行 —— 这是本问题上**唯一**能让文献层从「摘要转述」升到「逐字可回验」的路。
2. **B**：对 lit:000000 / lit:000001 / lit:000006 各抽至少一条 relation（概念：等弦点、凸体、异宿连接；每个概念一条带 `quote` + `page_range` 的定义或定理行）。**这是把 Q1 从「缺定义」推到「可判」的关键一步。**
3. **F**：对猜想 `000000`（椭圆族无等弦点）做一轮攻坚，子目标建议：① 写出椭圆上过 P 的弦长 L_P(φ) 的显式表达式；② 证明 Var_φ L_P(φ) 在 `a≠b` 时对一切 P 严格为正（或给出失败的**第一步承重假设**）。注意：**这是凸情形的特例**，若 lit:000000 的定理可用，它应是推论 —— 因此 F 的价值在于判断「能不能不依赖 Rychlik 给出独立证明」，而不是重复 Rychlik。
4. **E**：执行猜想 `000001` 的 `testable`（原点之外多起点最小化，判据 1e-18 / 8000 方向复核）；另外把 `000000` 的参数网格按 Q5 加密（重点在 `a/b ∈ [1.05, 1.3]`，因为 `1.0330e-05` 就在这一带，判据最容易失灵）。
5. **G/H**：在拿到 relation 行之前**不要**把本手稿第 2 节的文献地图写进任何稿件 —— 它是摘要层转述，不是可引文献结论。

**本趟（t-000025）新增的下一步（全部指向 plan:`000000` 的卡点，已按「交给谁」分开）**

1. **E**：解开 S1 报出的搜索域边界绑定 —— `a/b>=2.5` 的 4 个点 `P*` 落在 `|P|=0.9*min(a,b)` 上（attack_plans `000000` 的 `best_partial` 原话：「值随域截断而变，不能读作真实下确界」）。请求：搜索域放大到 `|P|<=0.99*min(a,b)`，并在边界上单独报告是否出现序列极小；若极小值随域扩大持续下降，只能报「本域内无内部极小」，不得写成一个下界。
2. **E**：把 S2 从 `a/b=1.01, 1.1` 扩到 `1.5/1`、`2/1`、`3/1` 三点（S3 的 `blocked_reason` 原话：「现有 exp:`000010` 只覆盖 a/b=1.01 与 1.1 两点」）。判据照 conjecture `000000.testable.refutation_criterion`：2000 与 8000 方向方差皆 <1e-18 且 `|P|` 明显非 0 才算反例。
3. **F**（下一轮 `attack.step`）：前两轮 `no_change` 是同一个技术性卡点 ——「子目标 S1 派给 E，但没有给 `script_path` ⇒ 未推进」（这句是 history 原文，属**技术性**失败，不是数学上走不通）。下一轮要么带脚本路径，要么直接按第 3 轮的做法把已登记的 experiments 行（`000008`/`000010`）绑进子目标。
4. **A**：r-000008 仍未见结果；Rychlik 1997 的原文（哪怕只有定理陈述页）仍是本问题文献层从 `summary` 转述升到逐字可回验的唯一路径。状态按三态记「未完成」，不记「不存在」。

**接手须知（口径）**：本手稿的证据上限是 `cross_check`；任何「已证明」的说法在本轮都不成立。若下一轮 F/V 给出 `statements.proof_text` 与 `verifications`，才可以把第 3 节的 C1–C4 升级；否则保持现在的写法。
