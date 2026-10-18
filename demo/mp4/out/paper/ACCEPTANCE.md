# 验收表（成文阶段：自由群因子同构问题现状报告）

本表口径：每行一个环节、一个当次读数；读数全部来自本轮台账现算或本轮盘上产物，未重测的显式标注「沿用上一轮读数」。本会话 Lean 形式化关闭（`toolchain.lean_enabled=false`）⇒ `proof` / `proof_review` 档结构上产不出来；正文所有承重断言上限 `cross_check` / `heuristic`，全文不出现「已证明」「已形式化验证」（已用 fs.search 回核，命中 4 行全部是「不能说」的否定/告诫语境）。

| 名称 | 结论 | 读数 |
|---|---|---|
| P1 正文与 PDF 对得上 | pass | 盘上 `out/paper/main.tex` sha256=`44fbbc54a25e2560983e2bb9e2969b3bcd64103dcb43b3bbcac679fd9ab972bf`（19480 字节）；编译回执 `out/paper/COMPILE-RECEIPT.json`（`compiled_at=2026-10-18T22:22:06+08:00`）：`pdf_fresh=true`、`pages=7`、`pdf_bytes=1033027`、`engine=pdflatex`、`exit_codes=[0,0]`、`reason=由本次源码编出（pdflatex，7 页）`。回执 `tex_sha256` 与盘上正文一致 —— 本轮按 finding 000010 改 §3 的 GATE 表述后已重编一次 |
| P2 立题 | pass | `research_questions` 共 1 行：`000000`（2≤k<m≤∞ 时 W*(F_k) 与 W*(F_m) 是否同构），本轮实读 `status=dropped`、`kind=gap`、`waiting_request_ids=[r-000008,r-000009,r-000010]`；三档收口逐条写在 D 的 notes 里（2026-10-18T22:14:31） |
| P3 检索取回（真的取回） | pass | `search_requests` 中 `outcome=ok` 的当次读数 = **8**（table.count 过滤实测）；A 的终局手稿 000036：13 条 `no_local_path` 里 2 条 ok（`lit:000004`、`lit:000009`）、11 条 `external_unavailable` 逐条写题名与缺口 |
| P4 可检验猜想 | pass | `conjectures:000000` 仍 `proposed`；`testable` 已补成可执行形式（k∈{2,3,4}/m∈{3,4,5}/N∈{8,16,32,64}+确定性种子，入口 `scripts/conj000000_verdict_gate.py`，GATE Q1–Q4（逐字见 `testable.gate_criteria`：Q1 rel_se 随 N 单调不增且末档≤0.1；Q2 N=32→64 相对变化≤0.2；Q3 normalization_scale 相对差≤0.05；Q4 feasible=false 不可行档≥2），三档出口 supports/refutes/insufficient_data，未过 GATE 时另记 `reason=estimator_not_qualified`）；当前既无 supports 也无 refutes 读数 |
| P5 算或造（数值档） | pass（cross_check 档） | `experiments` 当次读数 = **11** 行（table.count 实测，含本轮 `exp:000010`：`method=numeric`、`evidence_kind=cross_check`、`exit_code=0`、脚本 `code/conj000000_verdict_run.py`、确定性闸门 `insufficient_data` / `gate=disqualified` / 结构性缺口＝缺合格估计器）；`proof`/`formal` 档因形式化关闭不适用，见 P11 |
| P6 关系分析（C） | not_applicable | 本趟未派 C（`c_analysis_runs=0`）：本趟三条腿是「已知事实台账 / 判定形式 / 检索终局」，预算优先给 D/E/A/H 与本角色的成文；这是「这一环本趟不发生」，不是「没查成」 |
| P7 攻坚推进（F） | 部分（如实） | `attack_plans:000000` 1 行（沿用上一轮读数，本趟未重测），非空 history；终态仍是「本会话无合格 δ_N 估计器 ⇒ 结构性缺口」（手稿 000021 与 reports/conj000000_infeasible_record.json），未推进到证明 |
| P8 稿件落盘与正文非空 | pass | `documents` 1 行（`doc:000000`，kind=note，7 节），markdown 落点 `documents/note-fk-fm-research.md`（sha256=`fd14f02aa2b76f8c0c4ca5c5e43ebc8b0e040b2e8b5cd70d32570d71a531421a`，147 行）；本轮按 finding 000005 把残留的双重编号从台账侧消掉（`section` 字段「2 定义与已知」→「定义与已知」，5 处定点替换，markdown 侧已无双编号）；另有成文阶段的论文本体 `out/paper/main.tex`（8 节，全部有非空散文正文） |
| P9 手稿断言带引文 | pass | `documents:000000` 的 claims 11 条（`claim-1`–`claim-11`），每条带 `lit:` / `exp:` / `stmt:` 引用，条数 ≥ 研究问题行数（1）；论文正文 `main.tex` 的承重断言逐条挂 `stmt:`/`exp:`/`lit:` 编号（见文末「证据索引」一节） |
| P10 请求闭环 | pass | `search_requests.unfinished=0`（`r-000009` 已闭环，outcome=ok）；`reprocess_requests.unfinished=0` |
| P11 形式化 | not_applicable | 本会话 `toolchain.lean_enabled=false`（Lean 形式化已关闭）⇒ `proof` / `proof_experiment_rows` 结构上产不出来；这一档不是失败，是不适用 |
| P12 文献未消化 | unknown（如实记） | `literature` 中 `processed=false` 的当次读数 = **13**（table.count 过滤实测）；`unprocessed_reason`：11 条 `external_unavailable`（全文不可得，见手稿 000036 逐条题名与缺口）、2 条待 B 消化（本趟未派 B 的消化轮）；缺的是全文，不是缺动作 |
| P13 审校台账 | pass（落盘） | `review_findings` 当次读数 = **10** 行（table.count 实测），全部挂在 `doc:000000`；报告落点 `out/review/000000-review.md`。残留档（finding 000005 的标题双重编号）本轮已在台账侧消掉，正文段落未改 |

注：`quote_verified` 三态按实际填写，未核到的写 `null` + `quote_reason`，不把「还没查」写成 `false`。`statement_rows` 当次读数 = 2（`stmt:000000`、`stmt:000001`，均 `quote_verified=true`，出处 `lit:000004` / `lit:000009`），`counterexample_or_proof_rows` = 0（本会话产不出 proof 档；反例侧只有 `exp:000000` 的有限截断启发式读数，不作因子不同构依据）。
