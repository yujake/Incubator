# 交付说明 — M（台账号 t-000067，唤链深度 1）：把 Appendix A 补成可复现索引

附件三件套：`origin=own_result`（本趟改的是我们自己论文的附录 A，不是外部文献的转述）｜`依据`（G 的手稿 000054、H 的手稿 000055 与 000057、H 落成的 `review_findings` 000024–000029、`out/paper/COMPILE-RECEIPT.json`）｜`sha`：`out/paper/main.tex` = `c641682d2f56799d0826e4d39dd5a21f7ad38fb8f00d07134d9326c17721bb18`（34504 字节，327 行）；`out/paper/COMPILE-RECEIPT.json` 的 `tex_sha256` 与它逐字相等。

## 一、任务与范围

用户只交办一件：`out/paper/main.tex` 的 Appendix A 当前是空的（附录里一个内部编号都没有、可复现入口丢了），要求在不改正文、不改定理与证明的前提下把它补成真正的可复现索引，三块内容：① 正文结论实际依赖的 `experiments` 与 `statements`（`exp:`/`stmt:` 编号、方法、参数域、`exit_code`、脚本路径 `code/…`）；② 被引用的 `literature` 条目（`lit:` 编号 + 我们是否拿到本地全文 + 是否逐字核验过）；③ 重跑方式（命令 + 期望读数）。正文最多补一句「数值证据与可复现索引见附录 A」。补完重编译 `out/paper/main.pdf`，保证 `COMPILE-RECEIPT` 的 `tex_sha256` 与盘上 `main.tex` 一致，再由 H 审一遍并落 `review_findings`。

范围外（本趟不做）：不新增/削弱任何定理、证明、断言；不改参考文献表；不改第 1–4 节正文内容。

## 二、这一趟做了什么（谁做的）

| 顺序 | 谁 | 台账 / 手稿 | 做了什么 |
|---|---|---|---|
| 1 | M（t-000067） | 本报告 | 读盘定位附录 A（257 行处 `\appendix`）、核对台账（`data/statements.json` 两行、`data/experiments.json` 的 claim/method/exit_code/script 字段、`data/documents.json` 的 `doc_id=000000`），派活给 G，随后派 H 审 |
| 2 | G（t-000068，手稿 000054） | `out/paper/main.tex`、`out/paper/main.pdf` | 把 Appendix A 重写成带内部编号的可复现索引（A.0 正文依赖的 statements 表、A.0.1「正文不依赖任何脚本读数」、A.0.2 探索性计算表 exp:000000–exp:000005、A.0.3 其余五行 exp:000006–exp:000010、A.1 文献表 lit: 编号/本地全文/逐字核验、A.2 重跑命令与期望读数、A.3–A.6 保留原有叙述），并调 `doc.paper_compile` 重编 PDF |
| 3 | H（t-000070） | —（本趟一次失败调用） | 第一次派 H 走 `review`（doc_id=000000）时它只回了「占位」，**没有落任何 finding**；如实记入第四节 |
| 4 | H（t-000072，手稿 000057；它自己出的手稿 000056） | `review_findings` 000024–000029 | 复审附录 A：11 个 `exp:` 编号全部在 `data/experiments.json` 有行、`method` 全为 `numeric`、`code_path` 与附录逐条对上、`exit_code` 与 A.2 期望一致（含 `exp:000007`=1）；`stmt` 编号只有两个且与 `statements` 表一致；文献表三列与盘上事实一致；裁决 `accepted`，无拦截项 |
| 5 | M（t-000067） | 本报告 | 亲手核 `COMPILE-RECEIPT` 与盘上 `main.tex` 的 sha256 相等（`fs.stat` 读数）、逐段回读附录 A（第 225–327 行）、收敛成交付说明 |

## 三、逐条读数与验收表对齐

| 任务要求 | 读数（这一趟亲手取回的） | 结论 |
|---|---|---|
| ① 正文依赖的 statements 带 `stmt:` 编号 | 附录 A.0 表两行：`stmt:000000`（Shlyakhtenko 2006 Lemma 6，page 7）、`stmt:000001`（Mineyev–Shlyakhtenko 2005 主定理，page 2）；与 `data/statements.json` 的两行逐字对应，`origin=external_lit`、`quote_verified=true`、`quote_mode=verbatim` | pass |
| ① 探索性 experiments 带 `exp:` 编号 / 方法 / 参数域 / exit_code / 脚本 | A.0.2 + A.0.3 两张表共 11 行：`exp:000000`–`exp:000010`，`method` 全为 `numeric`，逐行给参数域（如 `exp:000000`：k∈{2,3,4,8}、n∈{8,16,32,64}、samples≤40、seed 20261018）、`exit_code`（唯一非零是 `exp:000007`=1）、脚本路径（`code/fk_truncation_moments.py` 等） | pass（带两条口径说明，见第四节） |
| ② literature 条目（编号 + 本地全文 + 逐字核验） | A.1 表：`lit:000009`（MS05，本地全文 yes，verbatim true，经 `stmt:000001`）、`lit:000004`（Sh06，yes，true，经 `stmt:000000`）、`lit:000000/000001/000002/000003`（no，not checked）、`\cite{Voi94}` 与 `\cite{At76}` 标为「no ledger row」（查不到台账行） | pass（三处「没查」照实写，未伪装成核过） |
| ③ 重跑方式（命令 + 期望读数） | A.2 表 11 行，每行三列：脚本命令（`python code/…`）+ 期望 exit code + 台账 `result` 字段（如 `exp:000000` → `refutes`；k=2 vs k=8 diff 1.9396、se 0.0344、ratio 56.34） | pass |
| 正文最多补一句 | G 报「第 212 行已有 `\paragraph{Numerical evidence.} Numerical evidence is collected in Appendix~A; …`，按『只许补一句』的口径没有再动正文」；我回读第 205–224 行确认该句存在且 `\appendix`（225 行）之前无新增内部编号 | pass（正文零改动，未新增句子） |
| 定理与证明未改 | 本趟唯一改动区在第 225–327 行（附录）；第 1–224 行（定义、定理、证明、讨论、参考文献）未动 | pass |
| 重编译且回执与盘上正文一致 | `out/paper/COMPILE-RECEIPT.json`：`tex_sha256=c641682d…21bb18`、`pdf_sha256=43cde09a…`、`runs=2`、`exit_codes=[0,0]`、`pages=11`、`pdf_bytes=325663`、`pdf_fresh=true`、`compiled_at=2026-10-18T22:48:40+08:00`；`fs.stat out/paper/main.tex` 的 sha256 = `c641682d…21bb18` ⇒ 逐字相等 | pass |
| H 审并落 `review_findings` | H 第二次调用经 `record_finding` 落 6 条（000024–000029，round 24，doc_id=000000），裁决 `accepted`；第一次调用只回占位、0 条 | pass（第二次；第一次如实记为失败） |

## 四、证据不足与未核到处

1. **H 的第一次调用没有落库**：t-000070 的返回值是 `final="占位"`，`review_findings` 里查不到这一轮的新增行。处置是重派一次（t-000072），第二次落了 6 条。第一次那一步**没有**任何 finding —— 不许按「H 审过了」记。
2. **A.1 的「local copy」列我未独立回查**：附录写 `lit:000009`/`lit:000004` 本地全文 yes，其余 no —— 这是 G 依据 `data/literature.json` 与 `library/` 下的落点给的读数，我没有逐条 `fs.list library/` 核对。H 报了「与 literature.json / library/ 盘上事实一致」，但那是 H 的读数，不是我亲手核的。
3. **两处「no ledger row」是缺口，不是通过**：`\cite{Voi94}` 与 `\cite{At76}` 在 `literature` 表里没有对应行 ⇒ 它们既没有 `lit:` 编号，也没有「本地全文 / 逐字核验」的读数。附录照实写成「no ledger row」，没有把它们伪装成已登记。要补齐得派 A 做 `search.register` / `search.ingest_local`（本趟没做）。
4. **`exp:000006`–`exp:000010` 的两处口径偏差**：① 脚本路径落在 `scripts/…`（`scripts/conj000000_infeasible_record.py`）而不是任务原话里的 `code/…` —— 附录抄的是台账 `code_path` 原值，没有为了让格式好看而改写；② 这五行的 `params` 字段为空，参数域由脚本内部常量决定、记在台账的 `observations` 字段，附录 A.0.3 明写了这一点，所以「参数域」这一列在它们身上是间接读数而非台账直读。
5. **我没有重跑任何脚本**：A.2 的「期望读数」全部来自台账登记的 `result` / `exit_code`，不是本趟现算的。派 E 复跑（G8 回执）本趟未做 —— 本趟没有新增数值结论，因此 H 那一格按 `{checked:false, reason:'本轮没有需要重跑的新数值脚本'}` 交。
6. **`documents` 表里没有「论文正文」这一行**：H 的 6 条 finding 挂在 `documents:000000`（研究手稿 note）上，不是挂在 `out/paper/main.tex` 上；这条口径缺口上一趟就存在，本趟没变，也不因本趟的附录改动而消解。

## 五、还剩什么没做

1. **给 `Voi94` / `At76` 补台账行**：派 A 登记这两篇（`search.register` 或 `search.ingest_local`），再派 B 抽 statements，附录 A.1 的「no ledger row」两处才能变成真编号。
2. **`exp:000006`–`exp:000010` 的参数域**：若要把「参数域」这一列做成台账直读，需回填这五行的 `params`（或把它们合并成一行并注明脚本内常量）。
3. **A.2 的期望读数未现算**：若要把它升级成「跑得通」的回执，派 E 用 `verify.run_experiment(script_path=…)` 逐条复跑 11 个脚本，把 `exit_code` 与 stdout 尾部凑成 `run_evidence` 交 H 判 G8；本趟预算下没做。
4. **论文侧仍悬着的一件（上一趟遗留）**：我方 7 条结论在 `statements` 表里没有命题行 ⇒ `reviewed_proof_rows` 仍签不到；补齐要派 B `register_statement`（`origin=own_result`、`proof_text` 取正文对应 proof 全文）再派 V `verify_proof`。与本趟的附录无关，但它是这份交付物更大的一处欠账，照实记在这里。
