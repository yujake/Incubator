# 三维 l^p 球 B_p^3 的最大面积中心截面 —— 交付说明（收口版）

本文件是主控（M，台账号 t-000001，本趟根 t-000292）的交付说明。任务：求
B_p^3 = { x∈R^3 : |x_1|^p+|x_2|^p+|x_3|^p ≤ 1 } 的最大面积过原点截面 A_max(p)，给出取到最大的平面法向（精确到旋转与坐标置换等价类）。
用户运行中插话追加：**继续研究，并最终产出论文** —— 据此把成文阶段走完。

## 一、交付物（逐件可核，均为本趟盘上读数）

| 件 | 路径 | 读数 |
|---|---|---|
| 论文正文 | `out/package/main.tex` | 32529 B，sha256=`a4174b2f0733b7fac2698c4b88ce9d01f204ab5d88d98ec1ecdb328b26dca365`（H findings 000006/000007 所指第 4 节 overclaim 收紧后的版本；前版 32396 B / 62efb2f6 已作废） |
| 论文 PDF | `out/package/main.pdf` | 编译回执 `tex_sha256` 与上式**逐字相同**（`receipt_matches_tex=consistent`），pages=10 |
| 编译回执 | `out/package/COMPILE-RECEIPT.json` | engine=pdflatex，pdf_bytes 见回执 |
| 论文对应表 | `out/package/MAPPING.json` | 3405 B，sha256=`4527b18a7738256fb930b102d7755ea41ee485bec84b97a14e9cf5b8232063e9` |
| 验收表 | `out/package/ACCEPTANCE-TARGETS.json` | 9 行（R1–R9），kind 全取自受控档 |
| 研究手稿 | `manuscripts/D/RESEARCH.md` | 七节齐，6 条目录行四格（evidence_kind / evidence_path / evidence_sha256 / v_signature）可核 |
| 稿件行 | `documents` doc_id=000001 | 经 H 三轮复审裁决 `accepted` 并签名 |

## 二、数学结论（三段结构，两个临界点）

记 A(n)=area(B_p^3 ∩ n^⊥)。三条候选方向族：

- 坐标向 n=(1,0,0) 及坐标置换：A_coord(p) = 4Γ(1+1/p)² / Γ(1+2/p)
- 体对角向 n=(1,1,1)/√3 及符号变体：A_diag(p) = (3/4)∫_0^{2π} (|cos(θ−π/6)|^p + |cos(θ+π/6)|^p + |sin θ|^p)^{−2/p} dθ
- 面对角向 n=(1,1,0)/√2 及坐标置换：A_face(p) = 平面 x+y=0 上的二重积分，p→∞ 时 → 4√2

**分段（两个临界点）**：

- **1 ≤ p < 2**：坐标向最大，A_max(p)=A_coord(p)（p=1 时八面体的最大中心截面为边长 √2 的正方形、面积 2，落在坐标向）；
- **p = 2**：各方向同值 π（欧氏球，各向同性）；
- **2 < p < p\* = 4.998215596862…**：体对角向最大，A_max(p)=A_diag(p)；
- **p > p\***：面对角向最大，A_max(p)=A_face(p)；
- **p → ∞**：A_face → 4√2 ≈ 5.657 > A_diag → 3√3 ≈ 5.196 > A_coord → 4（与立方体已知值一致）。

**证据强度（不许超过）**：
- A_diag(p) 的表达式与「Δ 连续性与尾段符号」两条有 **V 判「成立」的签**（stmt:000042 / stmt:000034 / stmt:000035 一族；verifications/0000{34,35,41,42}.jsonl 与 out/vsigns/ 对应签文件）——属 `pre_theorem` 档：**逐行审阅过的证明，未经机器检查**。
- 「p<2 坐标向占优」「2<p<p\* 体对角向占优」「p\* = 4.998215596862」三条目前只有**确定性数值支持**（exp:000004 12 个 p 的球面基本域扫描 + 6 轮嵌套加密；exp:000006 临界 p 二分；exp:000007 两条边界弧细扫描），等级 `strong_conjecture`，**不构成证明**。
- 数值求积核先用已知解析值认证（exp:000003：p=2 任意方向=π 到 4.4e-16、p=1 与八面体精确裁剪一致 6.7e-16、坐标截面 vs 闭式 7.0e-16、基旋转不变 8.9e-16）。

## 三、附件三件套（origin=own_result / 依据 / sha）

- **origin=own_result**：论文正文、三条方向族的面积表达式推导、12 个 p 的扫描与两次临界二分，全部由本趟角色（E / F / V / D / G）自己产出，不是复制外部论文；外部文献只作出处与背景（`lit:` 引用）。
- **依据**：`exp:000003`（求积核自检）、`exp:000004`（12 个 p 扫描）、`exp:000006`（临界 p）、`exp:000007`（边界弧端点性）、`stmt:000042`（A_diag 表达式，V 签成立）、`stmt:000034`/`stmt:000035`（Δ 连续性与尾段符号，V 签成立）、`analysis_reports` 000002（C 的关系分析）。
- **sha**：main.tex = `62efb2f6835297672a4839e2d374bcf36c9a1ba56707f36f4280250f37166b4e`；MAPPING.json = `4527b18a7738256fb930b102d7755ea41ee485bec84b97a14e9cf5b8232063e9`；验证签文件见 `out/vsigns/<正文 sha>.json`。

## 四、逐条读数（验收表 R1–R9 与收工门）

| 行 | kind | 读数 |
|---|---|---|
| R1 立题 | research_question_rows | 1（qid 000000） |
| R2 检索 | retrieval_ok_rows | search_requests 4 行 unfinished=0；`literature` 25 行（lit:000000–lit:000024），待裁表 30 行 pending=0（admitted 25 / rejected 5） |
| R3 造 | reviewed_proof_rows | 4 条带 V 签（stmt:000034/000035/000041/000042） |
| R4 想 | statement_rows | 台账 statements 14 条以上（含概念行与猜想行） |
| R5 看 | c_analysis_runs | 1（C 跑过；analysis_reports 3 行：000000 gaps / 000001 proof_chain / 000002 gaps） |
| R6 攻 | plan_progress_rows | plan 000002 第 2 轮 `statement_id` 已由 D2 更正为 000042（`data/attack_plans.json:2593`），而 verifications/000042.jsonl 末行判「成立」 |
| R7 交 | document_rows | 2 行（doc 000001 论文、研究手稿行），doc 000001 已 accepted |
| R8 闭 | unfinished_request_rows（上限 0） | search_requests unfinished=0、reprocess_requests unfinished=0、`literature.unprocessed` 已由 B2 归 0（手稿 000045） |
| R9 论文对应表 | paper_mapping_rows | `out/package/MAPPING.json` 在盘（3405 B，sha 见上） |

**收工门读数（`conductor.closing`，第 162 步）**：八格 **7/8 pass**，`machine_pass=false`，唯一的 fail 是 **acceptance**；`retire=干净`（children_unretired=0）、`programs=已停`、`m_says_done=true`。

## 五、未核到与限制（如实报，不折成通过）

1. **acceptance 那一格仍红（唯一 blocker）**：论文 doc 000001 的 **claim-6 引了 `lit:000000`（Cube slicing in R^n）**，而该断言讲的是 A_face(p)=2^{1/2−1/p}·4Γ(1+1/p)²/Γ(1+2/p) 与 A_face vs A_coord 的分段比较 —— 确定性判据判「断言实词与那篇题名/摘要无交集 ⇒ 引文可能跑题」。本轮尝试修它两次：G2 的 `table.get(documents, 000001)` 与 `own.revise(doc_id=000001)` 均被受控拒绝（`row_not_visible` / `row_not_yours`：该行归已销号的 G1 那一支笔）。**下一趟的可操作修订点**：由仍持有该行的 G 实例把 claim-6 的 citations 换成真的讲 l_p 球中心/超平面截面的那几行（例如题名含 plane sections of the unit ball of l_p / maximal hyperplane sections of the unit ball of l_p^n / on extremal sections of subspaces of l_p 的 lit 行），或删掉跑题引用只挂 `stmt:000042` / `exp:000004`，必要时同步改正文后重编。
2. **同一格另两条读数**（`conductor.closing` 原话）：24 条实验里 7 条 `result=inconclusive`（000009/000010/000011/000012/000013/000017 等），没有给出 `supports`/`refutes` + 界或证书；论文结果章节对本轮台账（`stmt:`/`exp:`/`rel:`）的引用偏少（G2 已补一处指向附录 A 数值比较的引用并重编，但判据仍要求结果章节直接引）。
3. **命题签收（读数，不拦门）**：`statements_unsigned` 10 条（000030–000033、000036–000039 等）、无签稿 1 份（`manuscripts/B/b-proof-000005.md`）；`open_questions` 1 条（qid 000000）。处置路径已写明：能补签的由产出者自己送 V（谁产出谁送审），补不了按四档明确放弃（abandon_kind + abandon_basis）。
4. **形式化已关闭**（本会话 `lean_enabled=false`）⇒ `load_bearing` 那一格按替代口径判：V 逐行走查签住 4 条命题（pre_theorem 档），没有 `theorem` 档结论；这是读数，不是「稿里没有带证据的结论」。
5. **triage_branch_recorded / within_cost_cap** 两格为 `unknown`：本轮一次都没向用户提问（用户插话进入后按插话执行）、收工门未给 cap_usd。`unknown` 不是通过。

## 六、任务列表（自报，与收工门口径对齐）

已完成 12 项：文献收编（A1/A2/A3）→ 数值扫描与两临界点（E1 与后续 E）→ 研究手稿七节（D1）→ 命题/猜想的登记与 V 签（B/F/V）→ 关系分析（C1）→ 验收表落盘 → 交付说明落盘 → 论文正文/PDF/对应表（G1，H 三轮复审 accepted）→ claim-6 定点尝试与正文补引重编（G2）→ request 闭环（A1/A3、B1/B2）→ 名册全部销号 → 收工门三次实跑。
未完成 2 项：① `acceptance` 转 pass（claim-6 归属受限，见 §五.1）；② 10 条未签命题与 b-proof-000005 的补签/放弃（预算余量不足，留续跑趟）。

## 七、结论

任务点名的数学答案已给出（三段结构 + 两个临界点 p=2 与 p\*=4.998215596862 + 三条方向族的面积表达式），并已按用户插话交付**论文包**（main.tex + main.pdf + MAPPING.json，PDF 与盘上正文逐字一致、10 页）。收工门 7/8：唯一未过的是 `acceptance`，根因是一条引文跑题（claim-6 引 lit:000000），归属受限未能本轮修掉 —— 这一条已如实写进本说明与 final，不折成通过。
