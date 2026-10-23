# 验收表 —— 立方和公式 1^3+2^3+...+n^3 = (n(n+1)/2)^2 的证明与形式化

本趟任务不是「写论文」，因此没有 out/paper/main.tex / main.pdf 这一档产物。本表逐行给出**本趟实际做了什么、读数是多少**；不可判定或不适用的一律写 `na` 并给理由，不折成「通过」。

| 编号 | 名称 | 结论 | 读数 |
|---|---|---|---|
| R1 | 立题（研究问题已登记） | 成立 | `research_questions` 1 行，qid=000000（priority=high）；问题原文见 `data/research_questions.json` |
| R2 | 检索（真的取回） | na | 本题是教科书级初等恒等式，证明不依赖外部文献；`search_requests`=0、`literature`=0。na ≠ 通过 ≠ 失败 |
| R3 | 造（证明落盘 + 逐行走查） | 成立 | `statements` 1 行（stmt:000000，proof_text 2082 字，双路径：归纳法 / 差分-telescoping）；`verifications/000000.jsonl#v-000001` 最近一签「成立」，被审证明 sha256=36bbf5da…08cce4c 与现行正文相符 |
| R4 | 想（命题登记） | 成立 | `statements` 1 行（kind=conjecture，origin=own_result）；本任务命题是待证恒等式而非探索性猜想，`conjectures` 表 0 行是这一档的如实读数 |
| R5 | 看（关系分析） | na | 本趟 `literature`/`relations` 均为 0 行，没有可做关系分析的语料；派 C 只会得到空图。na 附理由 |
| R6 | 攻（攻坚推进） | **不成立（如实记 0）** | `plan_progress_rows`=0：attack_plans plan_id=000000 三轮全为 `no_change` / `dead_end(缺工具)`（s1/s2 的 owner=F 侧无可调用的推理入口）。证明正文实际由 D 直接写出、不是 F 攻坚推进的产物 —— 这一格的 0 是准确读数，不用别的档顶替 |
| R7 | 交（交付落盘） | 成立 | 本表 + `out/paper/ACCEPTANCE-CHECKS.json` + `out/review/REPORT.md`（本报告即交付本体：证明已落 `statements`，形式化已落 `experiments`）；`report_files`=2 |
| R8 | 闭（请求闭环） | 成立 | `search_requests.unfinished`=0、`reprocess_requests.unfinished`=0、`literature.unprocessed`=0（`conductor.state` 现读） |
| R9 | 形式化（proof 级证据） | 成立 | `experiments` 1 行 exp:000000：`method=formal`、`evidence_kind=proof`、`checker_status=verified`、`exit_code=0`、产物 `code/formal/sum_cum… |
| R10 | 已知缺陷（未修） | 见读数 | stmt:000000 的 `quote_reason` 仍写着「V 尚未签字」，与盘上 v-000001「成立」矛盾。B 试过三条写路（table.update → `direct_write_refused`；重复 `register_statement` → `new_row=false` 且 quote_reason 未变；再交 → `duplicate_statement`），均无正路可改。**这一句是过期文案，不是证据缺失**：V 的签字与形式化读数都在盘上 |
