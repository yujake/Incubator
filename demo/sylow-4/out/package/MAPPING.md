# 论文对应表（`MAPPING.json` 的人读版）

这一份由 `MAPPING.json` 生成，不许手写第二份 —— 两份不一致时，读 md 的人与读 json 的机器会得出两个结论，而没有东西会报错。

重生成：`sync_markdown(项目根)`（`agentflow.papermapping`）。
正文附录里印的就是这张表（「附录：产出对应表」，由 `render_appendix` 渲染）。
`env_no` 的口径：正文里第几个该环境，1 起，按正文出现顺序按类计数（theorem 单独数、lemma 单独数）。
`proof_no` 的口径：1 = canonical（台账行上的 `proof_text`）；2 及以上 = 该行 `proofs` 清单里那一份。多证明时每一条证明各占一行。
`file` 与 `citation_loc.file` 都是论文包内的相对路径：绝对路径在别人的机器上等于不存在，指到包外的相对路径同样过不了复核。
`file` 的指向：`proof_no` = 1 指台账行本身或附录里那一段正文；2 及以上指那一份证明自己的文件。
`lean_file` 那一格是「机器核验凭据（Lean 程序 / 数值证明程序）」：它说的是「这条命题有机器核验过的凭据（百分百为真）」，填的类别要与这条命题的证明通道一致 —— 形式化通道填 `.lean`（另带 `lean_target`：那份源码里字面出现的声明名）；数值证明通道填证明栏第 ① 段那份数值程序（`.py`，与证明栏指同一份）；没有通道时这一格允许为空（不适用）。开关关或没填时这两列印「（未开 Lean）」/「（没填）」—— 空不等于验过。
`numeric_evidence` 与 `exhaustion_note`：数值实验定理那一行（证明栏是程序）多这两格 ——E 的那条穷举读数编号（`exp:NNNNNN`）与 E 写的那两块（程序设计思路 / 穷举论证）落在哪一份读数里；那一行的 `file` 写的是那份程序的相对路径（相对仓库根），不是论文包内的 tex。
`ledger_kind` 与 `reviewed`（D-69）：台账那一行自己的 `kind`，以及 V 拿这一份怎么办（四档：「已签（判决：…）」/「未通过」/「未审」/「未读到」）。两格由写侧按台账现读现填（`fill_ledger_cells`），读不到就写 `未读到` —— 那一档既不折成「未通过」也不折成「未审」。它们让「论文里排成定理、台账里还是猜想」与「论文里排成定理、V 没签」这两件事在表上自己可见。
`optimized` 与 `proof_source`（业主 2026-11-02 的两阶段录入）：这一份证明洗过没有、以及它是哪条路交上来的。前者三档 ——「已优化」（换过正文且拿到覆盖新正文的 V 签）/「未优化」（机械录入那一版，还等着洗）/「未记录」（这一行还没有那一格，存量行）—— 第二阶段只读这一格（「洗过的肯定能保证V签」）。后者两档：own（我们自己的证明）/ citation（文献侧录入：V 签位填的是文献编号 = 占位签，它不算已签）；读不出来就是空。

| # | kind | label | env_no | ledger_id | ledger_kind | reviewed | optimized | proof_source | proof_no | file | lean_file | lean_target | citation_loc | citation_loc_reason | page_or_section | numeric_evidence | exhaustion_note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | theorem | thm:sylow1 | 1 | stmt:000060 | theorem | 已签（判决：成立） | 已优化 | 我方证明 | 1 | main.tex | （未开 Lean） | （未开 Lean） | main.tex · line_range 104-107 |  | 3 | （非数值证明） | （非数值证明） |
| 2 | theorem | thm:sylow2 | 2 | stmt:000061 | theorem | 已签（判决：成立） | 已优化 | 我方证明 | 1 | main.tex | （未开 Lean） | （未开 Lean） | main.tex · line_range 118-121 |  | 3 | （非数值证明） | （非数值证明） |
| 3 | theorem | thm:sylow3 | 3 | stmt:000062 | theorem | 已签（判决：成立） | 已优化 | 我方证明 | 1 | main.tex | （未开 Lean） | （未开 Lean） | main.tex · line_range 128-131 |  | 3 | （非数值证明） | （非数值证明） |
| 4 | theorem | thm:index | 4 | stmt:000063 | theorem | 已签（判决：成立） | 已优化 | 我方证明 | 1 | main.tex | （未开 Lean） | （未开 Lean） | main.tex · line_range 142-145 |  | 3 | （非数值证明） | （非数值证明） |
| 5 | theorem | thm:unique | 5 | stmt:000064 | theorem | 未通过 | 未优化 | 文献侧录入 | 1 | main.tex | （未开 Lean） | （未开 Lean） | main.tex · line_range 152-155 |  | 3 | （非数值证明） | （非数值证明） |

合计 5 行：theorem 5。
