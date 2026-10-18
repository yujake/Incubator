# 验收表：U(g) Noetherian 是否推出 g 有限维（论文交付）

本工作区是**从零研究**型（没有 `source/` 基线稿）：`manuscript_edited` / `citation_records_vs_bibitems` 两档记 `not_applicable`。
机器可读版见 `out/paper/ACCEPTANCE-CHECKS.json`；逐行读数由台账现算。本会话 `lean_enabled=false` ⇒ 证据上限 cross_check / known_in_literature，任何一处不得写成「已证明」。
本趟新增产物：论文正文 `out/paper/main.tex`（G 亲手写，31991 字节，sha256 前缀 8a075e5adecb35e4）＋ `out/paper/main.pdf`（8 页）＋ `documents` 行 **000002**（kind=paper，17 条 claims）。

| 编号 | 名称 | 结论 | 读数 |
|---|---|---|---|
| P1 | 立题（研究问题已登记） | pass | `research_questions` = 1 行（000000）；D 收口到终态 **dropped**（一般无限维非交换情形证据不足，不是「没有这个问题」）。论文摘要、§1、§6、§7 一律写成开放问题 —— H round 1 复核该口径为 pass。`conjectures` = 1 行（000000，status=known_in_literature） |
| P2 | 检索（真的取回了什么） | pass | `search_requests` = 6 行，`outcome=ok` **6/6**（r-000001…r-000006），`unfinished`=0；lit:000024（Kobayashi–Sanami 1990 PAMS）有本地全文（10481 字符 / 5 页 / sha256 15c482e9…）。`literature` 26 行；000005–000022 由 A 逐行核题名/DOI 判为离题，**未用作证据** |
| P3 | 算或造（可复现计算证据） | pass（cross_check 档） | `experiments` = **13** 行在册（exp:000000–exp:000012），论文 §6 逐条引到：exp:000000（无限维阿贝尔升链 201 步全严格）、exp:000001（有限维滤过/GK 维数）、exp:000008（截断族 n≤8，supports）、exp:000010（中心平移族，**refutes**，带分离泛函反例）。脚本在 `code/`，stdout 打 `REPRO_RESULT:` 一行。`proof_experiment_rows` / `reviewed_proof_rows` 记 **na**：Lean 关闭，proof 级证据结构上产不出来 |
| P4 | 想（猜想/命题） | pass | `statements` = **21** 行（任务书写的 18 条是上一趟读数；本趟台账现算 21，本轮 B 追加 stmt:000018–000020 三条概念行，全部 quote_verified=true），论文引到 stmt: 共 21 处；`relations` = 11 行；猜想 000000 带 `testable` 与否定形式，论文 §5 把它定位为**文献中已有的公开猜想**（known_in_literature，等于 Sierra–Walton） |
| P5 | 看（关系分析） | pass（有保留） | `c_analysis_runs`：C 被派过 2 次（t-000009 / t-000013），产星形图读数（中心 000000 度 6、6 条全为桥、割点仅中心）与 6 条候选缺口；`analysis_reports` = 0 行 —— C 自报「收口需要面外工具」，未闭环项如实记 |
| P6 | 攻（攻坚推进） | pass | `attack_plans` = 2 行：plan 000000（两轮 step 均 no_change，如实记失败）→ plan 000001（history 均 progress；s2 = 两脚本哈希与在册记录一致、exit 0，s3 到布尔级（n=1..7 逐条证书，余数向量仍缺），s4 边界隔离完成）；`plan_progress_rows` ≥ 2 |
| P7 | 交（论文正文落盘） | pass | `documents` = **2** 行：000000（kind=note，rev5，19 claims）与 **000002（kind=paper，17 claims，citations 覆盖 exp:13 / stmt:21 / lit:6）**。论文 11 个 `\section`，每节均有正文（`document_body_rows` ≥ 1）；`document_claim_rows`=17 ≥ 问题数 1。正文落点 `out/paper/main.tex`，PDF 落点 `out/paper/main.pdf` |
| P8 | 闭（请求闭环） | pass（附理由） | `search_requests.unfinished` = **0**；`reprocess_requests` = 0；`literature.unprocessed` = 21 —— 这批是 A 判定离题的题录（000005–000022），按 A 的订正不再逐条消化，理由见 P2（不是「没人做」而是「判定为离题、不进证据面」） |
| P9 | 审校链（B/H/V） | pass（有未清项） | `review_findings` = **15** 行：000000–000012（上一趟 H 四轮）+ 本趟 **000013 / 000014（均 open，挂在 doc:000002 round 1）**；`review_files` = **2**（`out/review/000000-review.md`、`out/review/000002-review.md`）。本趟 H 对 doc:000002 的裁决是 **rejected**（pass=9 / fail=2 / unknown=2 / na=2），未核项：statements 000005–000020 的 page_range/quote_verified 因观测层截断「部分核到」、G8 复跑门 unknown、语义级判据未接线（claims_semantically_judged=0）。**注意**：H.review 机械层 0 error 已把 documents.status 置 `accepted` 并签 content_sha256=deab641e…，但那是机械层，不是 H 的语义裁决。V 无对象：本会话无我方定理级 `proof_text` |
| P10 | 证据等级与用词 | pass | 全部断言 `evidence_kind` ≤ cross_check / known_in_literature，disclaimer 统一为「数值/文献交叉验证，不构成证明」；H 本趟用 `已证明|已形式化|形式化验证|必然成立|证毕` 复扫 `out/paper/main.tex` 命中 **0** 处（仅命中文献定理名）；主问句 dropped 口径 3 处一致 |
| P11 | 基线 `source/` 逐字节未改 | not_applicable | 本工作区没有 `source/` 基线稿（从零研究型），两档都不适用 |

## 证据不足与未做的事（逐条）

1. **核心问句未判定**：U(g) Noetherian ⇒ dim g < ∞ 既没被证明也没被反驳；主问句记 `dropped`（证据不足以判定一般情形），文献一侧称其为长期公开问题（stmt:000006 / stmt:000013，一手逐字陈述）。
2. **没检索到「无限维非交换 g 且 U(g) Noetherian」的构造**：r-000006 零命中，属 `not_searched_here`，不许写成「不存在」。
3. **受限类只前进腿的一半**：lit:000024 给的是否定方向（有限生成二步可解 + 多项式增长 ⇒ U(g) 非 Noetherian），不是反向蕴含定理。
4. **lit:000023 / lit:000025 只有 metadata，无本地全文** ⇒ 按纪律没有为它们造关系行。
5. **PBW 滤过那一步没有逐字论证正文**：lit:000004 取不到全文（403），dependencies 000000 记 `external_unavailable`，该步只算 cross_check 级重组。
6. **计算界有限**：exp:000008 只到 n≤8、PBW 次数≤5；exp:000010 只到 n≤8；F 的 s3 余数级证书仍缺。
7. **H 本趟 2 条 open finding（000013 / 000014）与 3 处 unknown 未清**：本趟预算耗尽前未再派 G 修订 + H 复核 —— 因此 `reviewed_current_rows` 对 doc:000002 记的是「机械层已签名、H 语义裁决为 rejected」，不是通过。
8. **G8 复跑门 unknown**：本趟没有人用 `verify.run_experiment` 把 §6 的脚本按 claim 级回执重跑一遍（H 只读、无 exec），这一格没有写成 pass。
