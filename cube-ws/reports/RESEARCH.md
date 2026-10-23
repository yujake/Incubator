# 研究手稿（跨趟记忆·D）

> 本趟委托：立题并产出一条完整、逐行可查的自然语言证明 —— 对任意正整数 n，1^3+2^3+...+n^3 = (n(n+1)/2)^2。

## 1. 成果概述

- **命题已证明并落库**：`stmt:000000`（`statements` 表，`statement_text` = 「对任意正整数 n，1^3+2^3+...+n^3 = (n(n+1)/2)^2。」，`proof_text` 全文 2082 字，`line_range` 指向 `reports/proof-p000000-cubesum.md` 全文 79 行，`src_sha256=36bbf5dae92a7d1089fd0a0cdeb230e8b9bb2709dafc89e5b5b76001408cce4c`）。证明由 F 逐行写出、经 B 登记（`created_by=secretary-B`）。
- **V 已签字「成立」**：`v-000001`（V 的台账落成文件 `verifications/000000.jsonl`，`verdict="成立"`、`proof_sha256="36bbf5dae92a7d1089fd0a0cdeb230e8b9bb2709dafc89e5b5b76001408cce4c"`、`unresolved_errors=0`）。该 sha 与 `stmt:000000` 的 `line_range.label` 里记的 `src_sha256`、与我本趟读回的 `reports/proof-p000000-cubesum.md` 的 `meta.sha256` **三处一致** ⇒ 签字对应的就是现行正文，不是旧版。
- **两条独立路径都齐**：(a) 归纳法（base n=1 + 归纳步五步代数变形）；(b) 差分/telescoping（引理 L 的纯代数验证 + 裂项相消）。见 `stmt:000000` 的 `proof_text`；两条路径互不引用的声明写在正文「两条路径的关系」一节（`reports/proof-p000000-cubesum.md` 末段）。
- **承重的那一步**：归纳步的代数恒等 —— `n^2(n+1)^2 + 4(n+1)^3 = (n+1)^2·(n+2)^2`（即 `n^2+4(n+1) = (n+2)^2`）。整条归纳路径的重量全压在这里：基始是一次算术，末尾配方只是 `(ab)^2=a^2b^2`。路径 (b) 的对应承重点则是引理 L 的恒等式 `k^3=(k(k+1)/2)^2-((k-1)k/2)^2`（它把求和的“难”换成了裂项）。
- **过程中总结到的经验**：F 如实报告 `attack.step` 对 owner=F 的子目标只记 `dead_end(缺工具：未接线自动推理)`，三轮 step 没有一轮是框架替它推的推理 —— 证明是 F 手写、B 登记、V 走查的。也就是说这条链上“谁真做了事”与“台账上记的推进”不是一回事，读台账时必须分清。

## 2. 定义与已知

- 记号：对正整数 n，`S(n) := 1^3+2^3+...+n^3`；命题 `P(n) : S(n) = (n(n+1)/2)^2`（见 `stmt:000000` 的 `proof_text` 开头「记号」一节）。
- 用到的已知初等事实（均在同段推导内自证，未引外部文献）：平方展开 `(x±y)^2 = x^2 ± 2xy + y^2`、`(ab)^2=a^2b^2`、通分、有限和的分拆与裂项相消、数学归纳法原理。
- **外部文献面：本命题没有入库引文。** `stmt:000000` 的 `quote_verified=null`，`quote_reason` 明确写「origin=own_result 的自产结果，没有外部文献引文可做逐字回验；proof_text 是 reports/proof-p000000-cubesum.md 的全文，不是 literature 里的句子」。所以本手稿**不声称**该公式在文献中的归属（谁先证、叫什么名字），这一块是空的（见第 6 节）。

## 3. 已确定的结论

1. **对任意正整数 n，S(n) = (n(n+1)/2)^2 成立** —— 依据 `stmt:000000`（两条独立路径的 `proof_text`），审过凭据 `v-000001`（`verdict=成立`，`proof_sha256` 与现行正文相符）。
2. **两条路径独立**：路径 (a) 不需要引理 L，路径 (b) 不需要归纳假设（`reports/proof-p000000-cubesum.md` 末节）。这条独立性是写法上的声称、不是另一个定理。
3. **`evidence_kind` 的现状**：`stmt:000000` 的 `evidence_kind="proof_review"`，由 `secretary-B` 在 `2026-10-23T21:09:38+08:00` 依 `verifications/000000.jsonl` 从 `heuristic` 升档，`proof_sha256_matched=true`。`bits` 里 `formal` / `numeric` / `audited` 均为空 ⇒ **没有形式化（L）签字、没有数值实验行、没有 H 审计**。`kind` 字段仍是 `conjecture`（B 登记时被框架硬校验强制从猜想起步），**这是登记流程的产物，不是内容上的不确定性**；我没有自行改写它。

## 4. 尝试与失败

- **技术性**：F 那三轮 `attack.step` 里，对 s1/s2（owner=F 的子目标）框架只记 `dead_end(缺工具：未接线自动推理)`，对 s3 记 `no_change(未给 relation_ids)`。卡点：这条攻坚链上没有把“自然语言推理”接成可自动推进的步骤，所以 `attack_plans 000000` 的 `status` 仍停在 `attacking` 而不是靠 step 收敛。**这不影响证明本身**（证明正文已落库、已签字），只影响“计划是否被自动推进”这一读数。
- **结构性**：本趟任务书说的 “verifications 表” 在现库 schema（17 张表）里**没有**这一张表；V 的签字实际落在文件台账 `verifications/000000.jsonl`，而 `statements._evidence_kind_upgrade` 里带出 `verification_id=v-000001` 与 `ledger=verifications/000000.jsonl`。所以找“审过”凭据要读这个 jsonl，不是 `table.get`。
- **反例不成立**：本趟没有出现过反例，也没有人提出过反例（见第 6 节关于 n=0 的口径）。

## 5. 例子与反例

- **小情形算术核对：本趟没有做，也没有落成 `experiments` 行。** 因此这里**没有**可引的 `exp:` 编号 —— 不写一个没有落点的例子。
- 唯一可引的“具体数”是证明正文里基始那一步的算术：`S(1)=1`、`(1·2/2)^2=1`（`reports/proof-p000000-cubesum.md` 路径 (a) 基始段）。它是一次代入，不是实验读数。

## 6. 未解问题

1. **文献归属空缺**：这条公式是谁先证、在文献里叫什么，本库零引文、零关系行。若要写进论文体例，需要 A 检索 + B 建关系（带逐字引文）。
2. **口径问题（未定）**：命题写的是“任意正整数 n”。n=0 时两边都是 0（左边空和取 0，右边 `(0·1/2)^2=0`），但**本趟证明没有覆盖 n=0**，我也没有把它写进命题 —— 若要的是“任意非负整数”，需要把基始改成 n=0 或补一句空和约定。这是口径取舍，不是数学缺口。
3. **`kind` 仍是 `conjecture`**：是否需要向 B 申请把 `stmt:000000` 的 `kind` 从 `conjecture` 改为 `theorem`/`proposition`（等级位由框架现算，不由我自报）。

## 7. 下一步

- 若还要更强凭据：派 E 做 n=1..10（或 n=1..100）的整数算术核对，落成 `experiments` 行（`method=numeric`，带 `code_path` 与输出），作为**辅助读数**补 `numeric` 位 —— 明确写着它不算证明。
- 若要文献归属：派 A 以英文题名/关键词检索（如 “sum of cubes identity” / “Nicomachus theorem”），交 B 建带逐字引文的关系行；不要由我自己写归属。
- 若要形式化：`lean_enabled=true`，但 L 的入口只经 B（`B → L`）或用户直派；本趟不主动开。
- 交接纪律：下一趟接手的人先读本文件；本趟的会话记录不必翻。`attack_plans 000000` 停在 `attacking` 是已知读数，不要误读成“证明没做完”。
