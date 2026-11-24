# Sylow 定理论文包 —— 交付说明

## 一、任务与范围

被派的活：证明 Sylow 第一定理（有限群 G，|G| = p^a·m，(p,m)=1 ⇒ 存在阶 p^a 的 p-Sylow 子群），并给出推论：任两个 p-Sylow 子群共轭（共轭意义下唯一）、n_p ≡ 1 (mod p)、n_p | m。要求走完整链（文献 → 证明 → 验证 → 论文），交付论文包 `out/package/main.tex` + `main.pdf` + `MAPPING.json` + `ACCEPTANCE-TARGETS.json` 与收工报告。

范围约束：Lean 形式化关闭（AGENTFLOW_LEAN_ENABLED=false）⇒ 证明一级走「文字证明 + V 逐行走查签『成立』」（`pre_theorem` 档），不走机器检查。预算 $3、墙钟 14400 秒。

## 二、链条与派活

| 环节 | 收件人（台账号） | 结局 | 台账落点 |
|---|---|---|---|
| 文献摄取 | A（t-000002） | done / ok | `search_requests` r-000001（outcome=ok, done=true）；`literature` 000000–000003 四份全部 readable、已注册，待裁表清表 |
| 文献消化 | B（t-000006，由 A 派） | done | `statements` 概念行 60 条、`relations` 72 行（quote_verified 全 true），另 4 条命题线索行（手稿 000011） |
| 研究立项与攻坚 | D（t-000003） | done / ok | `research_questions` 000000 = answered；`manuscripts/D/RESEARCH.md` 七节齐全；F 的 `manuscripts/F/f-proof-000000.md` 经 V 判「成立」（手稿 000016） |
| 命题收录 | B（t-000153，由 D 派） | done | `statements` 000060–000064（Sylow 第一定理 + 三条推论 + 索引/唯一性行），`proof_text` 取自 f-proof-000000.md |
| 成文 | G（t-000109） | done / ok | `documents` doc:000000（kind=paper）→ `out/package/main.tex` → `doc.write_mapping`（state=pass，5 行）→ `doc.paper_compile`（7 页，pdf_bytes=232739，exit 0/0，tex_sha256 与盘上正文相符） |
| 审校 | H（t-000112/120/136/140，由 G 派） | done | `review_findings` 多轮；第 8 轮 `documents.status=accepted`（手稿 000014） |

派活留痕：`work/handoffs.jsonl` 000011–000016 六份手稿（B→A、H→G ×3、G→M、V→F）。

## 三、逐条验收读数（对应 `out/package/ACCEPTANCE-TARGETS.json` 的 id）

研究链八环：
- ① 立题：`research_questions` 000000（Sylow 定理及其推论），status=answered —— 成立。
- ② 检索：`search_requests` r-000001 outcome=ok，`literature` 000000–000003 四份由用户点名的 `reference/` PDF 本地摄取（正文可读，非仅题录）—— 成立。
- ③ 算或造：形式化关闭 ⇒ 走「造」的文字证明这一腿。`statements` 000060–000064 带 `proof_text`，`verifications/` 里有 V 的「成立」签（f-proof-000000.md，sha 对齐）—— 成立（说明见第五节关于 000064 的残余）。
- ④ 想：命题行 6 条（000060–000064 及 000065）；概念行 60 条 —— 成立。
- ⑤ 看（关系分析）：`C` 未派（本趟关系读数由 B 的 `relations` 72 行直接提供，未单独跑 C 的分析动作）—— 如实记为未做，理由见第五节。
- ⑥ 攻（攻坚推进）：D 的研究循环有推进记录（研究问题从 open 到 answered，F 的证明稿经 V 成立），`attack_plans` 为空（F 的工作经 D 的研究手稿承载，未另开 attack_plans 行）—— 见第五节如实说明。
- ⑦ 交（手稿落盘）：`documents` 2 行；`out/package/main.tex`（散文体正文，Abstract + 4 节 + 五个定理环境）、`main.pdf` 7 页 —— 成立。
- ⑧ 闭（请求闭环）：`search_requests.unfinished=0`、`reprocess_requests.unfinished=0` —— 成立；`literature.unprocessed` 见第五节。

论文包：`main.tex` / `main.pdf`（7 页）/ `MAPPING.json`（5 行，逐行对正文 5 个定理类环境）/ `ACCEPTANCE-TARGETS.json` / `COMPILE-RECEIPT.json`（tex_sha256 与盘上正文一致、pdf_fresh=true、exit 0/0）齐。

## 四、论文包与正文改动依据

- 正文由 G 自己写：`doc.build_document` 先登记 doc:000000（5 条 claims，citations 全部指到台账已有号 `stmt:000060`–`stmt:000064`、`lit:000000`、`lit:000002`），再 `fs.write` 落 `out/package/main.tex`，再无手写绕过。
- 论文对应表：`doc.write_mapping` 落 `MAPPING.json` / `MAPPING.md` / `mapping-appendix.tex` 三份，state=pass；5 行分别对应 thm:sylow1 / thm:sylow2 / thm:sylow3 / thm:index / thm:unique，每行带 `stmt:` 号、`proof_no=1`、`file=main.tex` 与 citation_loc；Lean 未开 ⇒ `lean_file` / `lean_target` 留空。
- 编译：`doc.paper_compile` 用 pdflatex 出 7 页 PDF，回执 `tex_sha256` 与盘上这一版正文相符（`pdf_fresh=true`），退出码 0/0。
- 审校：H 共 8 轮，前几轮判 `in_review`/`revise_again`（1 error：过程词 / 论断强度；2 warning：below 指反、附录过程词），G 逐条改，第 8 轮 `documents.status=accepted`。findings 全部落在 `review_findings` 台账。

## 五、未尽项与如实缺口

1. `statements_unsigned` = 1（`stmt:000064`，唯一性/索引一行）—— 该行没有 V 签。它对应正文 thm:unique 一节的表述，正文已按 G 与 H 的要求降级表述；本趟**未拿到「成立」签，也未走 `abandoned` 放弃**，如实记在这里。
2. `manuscript_unsigned` = 4（`manuscripts/B/b-proof-000001.md`、`-000004`、`-000005`、`-000008`）—— 都是 B 第二阶段洗稿过程中的中间副本，最终现行正文是 `manuscripts/F/f-proof-000000.md`（V 已判成立，手稿 000016）；这四份中间副本未再送签。
3. `literature.unprocessed`：`conductor.state` 的 `queues.literature.unprocessed` 此前读数为 0；如收工门读到非 0，是因为 B 的消化面只覆盖到 4 份中的一部分 —— 以收工门读数为准。
4. 「看（关系分析）」与「攻（attack_plans）」两项未按最严格形态落读数：C 未单独派关系分析动作（关系由 B 的 72 行提供）；F 的工作由 D 的研究手稿承载，`attack_plans` 未落行。这两项在 `ACCEPTANCE-TARGETS.json` 里如实标 `na`/说明，不虚报成通过。
5. 名册上有若干已交差的子代理（多为 V 与 B 的实例）尚未销号，收工前按下项处理。

## 六、结论

论文包本体（main.tex / main.pdf 7 页 / MAPPING.json）已齐，且 PDF 由盘上这一版正文编出（回执 tex_sha256 对得上）；正文的每条承重断言都能回溯到 `stmt:` 号，其中 Sylow 第一定理与两条计数推论由 V 判「成立」的 f-proof-000000.md 支撑。残余未见底的是 `stmt:000064` 一行的签与四份 B 中间副本，已如实登记，不折成「没有问题」。
