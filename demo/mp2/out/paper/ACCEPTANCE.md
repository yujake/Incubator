# 验收表（等弦点问题研究；本会话 Lean 关闭；读数按本趟台账现算）

| 编号 | 名称 | 结论 | 读数 |
|---|---|---|---|
| R1 | 立题 | pass | `research_questions`=1（一条简单闭曲线能否有两个相异等弦点；含凸情形 / 一般非凸情形 / 对称代数特例三子问题） |
| R2 | 检索（真的取回） | pass | `outcome=ok` 的检索 8 条；`search_requests.unfinished`=0；`literature`=32 行 |
| R3 | 算（数值） | pass | `experiments`=**21** 行（exp:000000–exp:000020）；多数 `method=numeric` / `evidence_kind=cross_check`；exp:000009 与 exp:000016 `exit_code=1` 如实记 inconclusive，分别由 exp:000010 / exp:000017 取代；exp:000013 自报 inconclusive，判读见 exp:000014；本趟新增口径读数 exp:000019（猜想 000001 判定性搜索）/ exp:000020（猜想 000000 的 var_inf 独立边界读数） |
| R4 | 造（proof / 形式化） | not_applicable | `proof_experiment_rows` 记 `na`：本会话 `lean_enabled=false` ⇒ `method=formal` 与 `evidence_kind=proof` 结构上产不出来（na ≠ 通过 ≠ 失败）。替代腿 `reviewed_proof_rows`=**0**：`statements` 3 行全是概念行、无 `proof_text`，本趟未派 V 逐行走查 —— 如实记 0，不写「已证明」 |
| R5 | 逐字出处 | pass | `relations`=**6** 行（rel:000000–rel:000005），全部 `quote_verified=true` / `quote_mode=verbatim`，来源 lit:000007（Klee 1960 全文，框架分页 p.28 / p.31）；Rychlik 1997（lit:000000）仍为 0 条逐字关系行 |
| R6 | 想（猜想 / 命题） | pass | `conjectures`=2，**两条均 `supported_not_proved`**：000000（exp:000000/000004/000008/000010/000020）、000001（exp:000002/000019）；`statements`=3（概念行，非证明行） |
| R7 | 看（关系分析 C） | not_applicable | `c_analysis_runs` 记 `na`：本趟未派 C；上一趟（t-000024）派过，得图 3 节点 / 4 关系 / 1 连通分量、密度 3.1%，但 `analysis_reports`=**0**（C 的登记口当时被判 unknown_tool，未落库）⇒ 这一档本趟无有效读数，不伪装成通过 |
| R8 | 攻（攻坚推进） | pass | `attack_plans`=1（plan 000000），`history` 非空（5 条推进，含 evidence_bound）；S1 / S2 记 supported_not_proved，S3 绑 exp:000018 |
| R9 | 交（手稿与正文落盘） | pass | `documents`=1（doc:000000，kind=note，21 条 claims）；本趟新增论文正文 `out/paper/main.tex`（35,983 字节，sha256=b99e9bb6…）与 `out/paper/main.pdf`（10 页，300,660 字节），编译回执 `tex_sha256` 与盘上正文一致、`exit_codes=[0,0]` |
| R9b | 正文每节有正文 | pass | H 通读 508 行分四段核过：摘要、§1–§7、Appendix 均有实质段落，无标题骨架节 |
| R9c | 带引文的断言条数 | pass | `document_claim_rows`=21 ≥ 研究问题 1 条；正文引 lit:（6 条逐字关系行，带 p.28 / p.31）、exp:（21 条实验中的主力行）与 conjecture 000000 / 000001 |
| R10 | 审校 | pass（带未结项） | H 本趟对现行正文跑 review（轮次 1，被审版本 hash `4f4777511d6f2fff`）：裁决 **`rejected`**（pass=9 / fail=3：G6、G7、G10；unknown=2：G8、G11；na=1：G12）；报告落 `out/review/000000-review.md`；`review_findings` 已落库（含本轮 5 条），无一条只留在对话里 |
| R10b | 审校钉在现行版 | unknown | 本趟 H 审的是 `main.tex`（sha256=b99e9bb6…）这一版并给出被审版本 hash；`reviewed_current_rows` 这一格按台账口径仍为 0（签名钉的是 `documents` 口径的 claims-hash，不是 `main.tex` 的 sha）⇒ 如实记 unknown，不折成通过 |
| R11 | 请求闭环 | pass（带未清零队列） | `search_requests.unfinished`=0；`reprocess_requests.unfinished`=0；`literature.unprocessed`=**32 未清零**（B 的 `run_once` 一次一篇，多数条目无本地全文 ⇒ 未在本趟派 B 清零，逐条留账） |
| R12 | 事实缺口（如实记） | pass | ① G6：claim-17 的 `numeric_evidence.script` 点名两个脚本路径不存在（虚证）⇒ 正文该条数值证据不可复跑；② G7：2 条数值断言在台账里缺对应的逐字行；③ G10：3 条发现缺「轴 + 严重度 + 行号 + ≤20 词逐字引文 + 最小修法」五要素；④ G8：本趟未实跑任何数值脚本（`run_evidence = {checked:false, reason:'本趟预算不足以再派 E 重跑数值脚本'}`）⇒ 记 unknown，不折成通过；⑤ G11：版本冻结门判不了；⑥ `reviewed_proof_rows`=0（无 proof_text、未派 V）；⑦ 未覆盖范围：a/b>5、a/b→1 极近端、exp:000019 只覆盖 Fourier 奇谐波族与 ε≥1e-3 |

## 结论一句话

本趟把已有研究整理成一篇可读论文（`out/paper/main.tex` + 10 页 `main.pdf`，回执与正文摘要一致），两条猜想都按 `supported_not_proved` 写进正文，6 条逐字引文带页码进正文，21 条 numeric experiments 如实入表；H 的只读审校裁决 `rejected`（3 条 fail 都是证据/体例层的可操作修订点），本趟**未**回去补修订、也**未**实跑脚本（G8 记 unknown）—— 强度上限仍是 cross_check / supported_not_proved，本会话无 Lean，正文与交付里没有任何「已证明 / 已形式化验证」的说法。
