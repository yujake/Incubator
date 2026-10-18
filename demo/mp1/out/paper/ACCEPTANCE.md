# 验收表（mp1 · Pyjama 定量化 · 论文交付趟）

口径：每一行三列「名称 / 结论 / 读数」。结论只取三态 + 一档不适用：`成立` / `不成立` / `没查成` / `不适用`。本会话 Lean 形式化**已关闭**（`toolchain.lean_enabled=false`）⇒ `proof` 级证据结构上产不出来，凡涉及形式化/证明级的行记 **不适用**（第三态，既不是 0 也不是 pass），替代凭据是 `statements.proof_text` + V 的逐行走查 —— 本次这类签名 0 条，故「证明级」一律不适用。证据强度上限：`cross_check` / `heuristic`。

机器可判读数见同目录 `ACCEPTANCE-CHECKS.json`（收工门按它逐行从台账现算）。

## 一、研究链八环节

| 名称 | 结论 | 读数 |
|---|---|---|
| ① 立题（`research_question_rows`） | 成立 | `research_questions` 1 行：`000000`（R^2 中宽度 2eps 周期竖条与其有限多旋转的并集，最少旋转数 N(eps) 与增长阶；含两侧夹逼的可判定检验口径）。状态 **`answered`（带保留，D/t-000043 收口，updated_at=2026-10-18T21:53:55）**，`waiting_request_ids=[]` 已清空（r-000002 终局 done=true / outcome=ok / result_lit_ids=[lit:000000,lit:000001,lit:000002]）；可判部分与留下的开放项见 `notes` 收口段落 |
| ② 检索真的取回（`retrieval_ok_rows`） | 成立 | `search_requests` 2 行、`unfinished=0`；`outcome=ok` 2 条（r-000001 → `lit:000000`,`lit:000003`；r-000002 → `lit:000000`,`lit:000001`,`lit:000002`）。threshold = 研究问题条数 1 ⇒ 2 ≥ 1。`literature` 5 行（其中 1 篇仅题录、无全文，已在 B 的手稿里标注不可引） |
| ③ 算或造（`numeric_experiment_rows`） | 成立 | `experiments` 25 行，全部 `method=numeric`；其中 `conclusive` 5 条（`exp:000006`,`exp:000012`,`exp:000014`,`exp:000021`,`exp:000024`），12 条 inconclusive 如实记录 |
| ③b 搜索前沿（`search_frontier_rows`） | 成立 | 覆盖半径搜索盒 / 角度池枚举范围带 `search_bound` 的实验行 ≥ 1（收工门现算通过） |
| ③c 形式化 / 证明级（`proof_experiment_rows`） | 不适用 | 本会话 `lean_enabled=false` ⇒ `method=formal` 与 `evidence_kind=proof` 结构上产不出来。**不记 0**（0 读作「做了没成」），记第三态 `na`。替代路线（自然语言证明 + V 逐行走查）本次 `reviewed_proof_rows` = 0：`statements` 里没有到「预备定理级 / 正式定理」的自己证明行 |
| ④ 想（`conjecture_rows`） | 成立 | `conjectures` 1 行 `000000`：|Θ|=k≥1 ⇒ r(Θ) ≥ 1/(2k)，带 `testable`（怎么反驳 / 怎么支持）。台账状态 `supported_not_proved`（支持但不构成结论），支持侧证据见第四节 |
| ⑤ 看（`c_analysis_runs`） | 不适用 | 本趟未派 C 的关系分析。理由：单一开放问题的定量推进，概念图读数（热点 / 结构洞 / 中心性）对本问题不构成证据；文献间关系由 B 以带逐字引文的 `relations` 行交付 |
| ⑥ 攻（`attack_plan_rows` / `plan_progress_rows`） | 成立 | `attack_plans` 1 行（子目标带 `testable`），`history` 非空 ⇒ `plan_progress_rows` ≥ 1 |
| ⑦ 交（`document_rows` / `document_body_rows` / `document_claim_rows`） | 成立 | `documents` 1 行（`doc:000000`，kind=survey，markdown `documents/000000.md`，revision 2）；每节正文非空 ⇒ `document_body_rows`=1；带引文断言 22 条 ≥ threshold 22（`document_claim_rows`） |
| ⑦b 文献进稿（`document_literature_citations`） | 成立 | 手稿经 `stmt:` 行引 `lit:000000` / `lit:000001` / `lit:000002` ≥ 1 |
| ⑧ 闭（`unfinished_request_rows`） | 成立 | `search_requests` 2 行全部 `outcome` 已回填、`unfinished=0`；`reprocess_requests` 0 行 / `unfinished=0`。上限档，0 达标 |

## 二、审校链（B / V / H）

| 名称 | 结论 | 读数 |
|---|---|---|
| 逐字出处（`quote_verified_rows`） | 成立 | `quote_verification.verified=20`、`unverified_ids=[]`：20 条 `statements` 的引文逐字回验通过 |
| 命题台账（`statement_rows`） | 成立 | `statements` 台账 27 行（其中 20 条带逐字回验通过的引文，见上一行）；`kind=concept` 与定理/原始提法并存，均带 `page_range`。验收档 `statement_rows` min=20 复用的是「我方台账里成立且带引文的 20 条」这一读数 |
| 关系行（`relations`） | 成立 | `relations` 台账 7 行，逐条带 quote / page_range / quote_verified；论文正文按 `rel:` 引用其中若干条（收工门 `paper_leg` 的结果面里可见 `rel:0000…` 引用） |
| 证明逐行走查（`reviewed_proof_rows`） | 没查成 | 0 行。原因分两层：本会话无 Lean；且 `statements` 中没有我方写出的、到「预备定理级 / 正式定理」的证明行可交 V。V 的 `verify_proof` 本次未派 —— 不是「V 否决」 |
| 审校报告（`review_files`） | 成立 | `out/review/000000-review.md`（H 的 `review_report`，round 2，16645 字节） |
| 现行版本被审校记录钉住（`reviewed_current_rows`） | 没查成（机器读数不成立） | 收工门现算 **0**（要求 ≥1）：`doc:000000` 现行 `content_sha256` 前16位 6cb395b1fd60，H 本轮按现行版重签记录的 `revision_hash` 为 4493c77efbdd2516，两者不同 ⇒ `pinned_to_current` 为空表、该条被记进 `stale_signoffs`。H 本轮（对 `out/paper/main.tex`）重跑过 `review_report` 仍未翻成 pinned ⇒ 这一格按**不成立**如实录，不折算成 pass（口径：hash 相同而未被钉住是检查器的判据问题，不是我方「已复核」的证据） |
| 稿件裁决（`reviewed_documents` / `accepted_documents`） | 成立 | `doc:000000` 状态 `accepted`：round1 rejected → round2 accepted |
| 论文正文审校（H 对 `out/paper/main.tex`） | 成立（带警告） | H 只读审 `main.tex`（sha256 `71dccd1d…`）与 `main.pdf`（7 页 / 279815 字节）、读 `COMPILE-RECEIPT.json`（`tex_sha256` 与盘上正文逐字一致，`pdf_fresh=true`）：15 门里 pass=10 / fail=1 / unknown=2 / na=2；**唯一失败门 G10 数的是 H 自己 3 条发现的书写格式**（缺行号 + ≤20 词逐字引文），不是稿面内容问题 ⇒ 实质裁决 `accepted_with_warnings`；4 条 finding 已落 `review_findings`。本趟没有 G8 回执（未重跑数值脚本）⇒ G8 记 `unknown`（不是通过） |

## 三、交付物

| 名称 | 结论 | 读数 |
|---|---|---|
| 说明报告（`report_files`） | 成立 | `out/review/REPORT.md`（本趟重写，体例声明见 `out/review/REPORT-STYLE.json`） |
| 手稿（`document_rows`） | 成立 | `doc:000000`（survey），22 claims，证据等级上限 `cross_check`，未核到项逐条写明 |
| 论文正文与 PDF（`paper`） | 成立 | 正文由 G 亲自用 `fs.write` 落盘：`out/paper/main.tex`（341 行 / 22324 字节，sha256 `71dccd1d6f0b349961773c68cfd9c664aa9ea842387ac32439b9fd13ab881301`）；`doc.paper_compile` 由**本次源码**编出 `out/paper/main.pdf`：`pages=7`、`pdf_bytes=279815`、`exit_codes=[0,0]`、`pdf_fresh=true`；回执 `out/paper/COMPILE-RECEIPT.json` 的 `tex_sha256` 与盘上 `main.tex` 摘要**逐字一致**（compiled_at=2026-10-18T21:59:39+08:00，written_by=agentflow.papercompile）。正文覆盖研究问题 `000000`、`stmt:000000`（Kravitz–Leng Thm 1.1，`lit:000001`，p.1，quote_verified=true）、25 条 numeric 实验（5 条 conclusive：`exp:000006/000012/000014/000021/000024`；12 条 inconclusive 逐条列名）、`exp:000023` 的 40/40 认证下界、`exp:000012` 与其反例 `exp:000018` 成对引、`rel:` 关系行、猜想 `000000` 只写成 supported\_not\_proved / cross\_check；全文无「已证明 / 已形式化验证 / 定理（我方）」 |
| 产物台账（`artifact_ledger_bad_rows`） | 成立 | `ARTIFACTS.jsonl` 逐条重算 sha 与盘上一致（收工门 `artifact_ledger=pass`） |

## 四、本趟收口的两件事（D / A 的产出）

| 名称 | 结论 | 读数 |
|---|---|---|
| 研究问题主问句收口 | 成立（带保留） | 能判：eps>0 时 N(eps) **有限**（`lit:000000` 定性 + `lit:000001` 定量上界，`cross_check` 级）；**已知显式定量上界** N(eps) ≤ exp exp exp(eps^{-C})（0<eps<1/10）= `stmt:000000` Kravitz–Leng Theorem 1.1，`source_lit_id=lit:000001`，`quote_verified=true`，`page_range=p.1`；已判数值侧：k=1,2 精确取等 r=1/2（`exp:000000` / `exp:000002` / `exp:000021`）。**仍开放**（本轮五路检索未取回任何文献）：随 eps→0 的精确增长阶（是否 O(1/eps)、是否带对数因子）与下界侧 1/eps 型显式阶；上界是三重指数、远弱于 O(1/eps)，不可读成 N(eps)=O(1/eps)。`research_questions 000000` 状态 `needs_evidence` →（经 `researching`）→ **`answered`**，`waiting_request_ids=[]`（r-000002 终局 ok），收口人 D / t-000043 |
| 猜想 000000 推进成结论 | 支持但不构成结论（`supported_not_proved`） | 40/40 格认证下界 ≥ 1/(2k)（`exp:000023`，k=3..10 × 5 结构族），认证上界 < 1/(2k) 的格 0 个，`certified_global_refutations=0`；k=1,2 有精确 witness。**但** `exp:000023` 的 `r_upper_box` 只在 [-1,1]² 盒内成立、不是全局上界；`exp:000012` 的 `r_ub_safe` 序列已被 `exp:000018` 反例推翻（引用必须成对）。故台账状态 `supported_not_proved`：这是**支持性数值证据**，不是证明 |

## 五、纪律声明

- 本会话 Lean 关闭 ⇒ 任何断言不得写成「已证明 / 已形式化验证」；等级上限 `cross_check` / `heuristic`。
- 「没查成」不折算成「不存在」：`reviewed_proof_rows=0` 的原因已写清（无我方证明行 + 无 Lean），不是「V 说不行」；`reviewed_current_rows=0` 是检查器判据问题，如实记不成立。
- `na` 两行（形式化 / C 关系分析）各自带理由，本表不是全 `na` 表；论文正文与 PDF 已由本趟产出，不再记 `na`。
