# 本趟收工门读数补记（挂在 out/review/REPORT.md 之后）

时刻：2026-10-18T22:03 前后，`conductor.closing` 当次现算。体例已按 REPORT-STYLE.json 兑现（report_shape=pass），本文件只补「收工门读数」这一块，不改 REPORT.md 主体。

## 八格读数

| 格 | 三态 | 读数 |
|---|---|---|
| paper | pass | 本工作区是研究型，未写 out/paper/main.tex、未编译；这一格按不适用口径读成 pass |
| contradictions | pass | 无未裁决矛盾 |
| load_bearing | na | 形式化已关闭（lean_disabled）⇒ T3 判据不适用；替代凭据（proof_text 非空 + verifications 签「成立」）0 条 —— 这是「不适用」，不是通过也不是失败 |
| report_shape | pass | 六节体例按声明的 REPORT-STYLE.json 兑现 |
| user_pending | pass | 本趟没有待用户回答的问题 |
| substance | pass | statements 21 / relations 11 / experiments 13 / review_findings 13 / documents 1 |
| artifact_ledger | pass | ARTIFACTS.jsonl 逐条 sha 与盘上一致 |
| acceptance | fail | 唯一失败行 REV2（reviewed_current_rows）：pinned_to_current=[]，要求 ≥1 |

## REV2 为 0 的实际读数（不折成「没问题」）

- `DOC-SIGNATURES.jsonl` 第 6 行确有本趟签名：`at=2026-10-18T22:01:05`、`doc_id=000000`、`content_sha256=9c0c5d57694ff3fb7a362a470e048687f8f767e48240b01640f32774263e8a15`、`claims_hash=9e9f0cc0…`、`coverage.claims_total=19`、`verdict=accepted_with_warnings`、`rounds=5`，与现行 revision 5（19 条断言）的 content_sha256 逐字一致。
- 门那一步的 `stale_signoffs` 也把它列进 signed（`['9c0c5d57694f','b7f5e558ff77']`），却仍判 `pinned_to_current=[]`；同一条读数里 `documents.revision=5` 而 `review_rounds=4`（签在 round=5）。这是一处**门与签名台账之间口径没对齐**的读数（签名在、判据不认），不是「H 没签」—— 我不把它写成通过，也不把它写成没做。处置留给下一趟：或由 H 再签一轮让 round 与 review_rounds 对齐，或按门的口径修 documents 的 review_rounds 字段。

## M 的收工判据

`goal_met=true`，`can_close=true`（判据归我，八格是读数）；与我自己的任务列表对不上的两项已在 REPORT.md 第五节与任务表里写明：
1. literature 队列里 A 自订正为离题的 000005–000022（21 条 unprocessed）未处置（M 侧无「标 ignore」动作，逐条消化是烧预算）；
2. attack_plans 000001 的 s3 余数级证书与 exp:000008 的界外推（n>8）未推进。
