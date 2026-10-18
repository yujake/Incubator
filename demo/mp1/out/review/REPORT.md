# 交付说明：两项表述层收尾（M · t-000058 · projects/mp1）

> 本份覆盖同一路径的上一版说明（上一版记的是 t-000049 那一趟的重写读数）。本轮不改研究内容：只有 G 改表述并重编译、H 只读审校，未新增实验、未改台账结论。

体例：一、任务与范围；二、逐条读数；三、谁做了什么；四、证据不足与未做；五、下游必须遵守的约束。

## 一、任务与范围

① 正文（`\appendix` 之前）内部编号（`exp:`/`stmt:`/`lit:`/`rel:`/`conj:`）必须为 0，编号指涉只许留在 Appendix A；② 主结果用 `theorem` 环境，引理只支撑定理、命题用于次要结论，定理/引理各带分步 `proof`，证不了的写成 Conjecture / Open problem 并写明缺哪一步；③ 重编译 `out/paper/main.pdf` 使 COMPILE-RECEIPT 的 `tex_sha256` 与盘上 `main.tex` 一致，并由 H 审一遍、裁决落 `review_findings`。

## 二、逐条读数

**① 正文编号数 = 0**
- `fs.search`（正则 `(exp|stmt|lit|rel|conj):[0-9]`，path=`out/paper/main.tex`）total=18，命中行 662、664–667、669–673、675–683，全部在 `\appendix`（第 558 行）之后 ⇒ **正文命中数 = 0**（G 与 H 两次独立搜出同一个数）。
- H 用 `record_finding` 落了一条（finding 000013），evidence 写明「附录 A 之前 = 0」。

**② 主结果体例**
- proof 环境 10 处（行 195、219、256、287、334、367、384、399、415、451），带证结果 10 个（lemma 185/245/271、theorem 209/315/358、proposition 379/394/442）。
- 本轮由 G 把三条承重结论从 lemma 升为 theorem：Covering criterion（209）、Period-lattice reduction（315）、Universal bound and monotonicity（358），每条各配分步 proof（三步）。
- `conj:main`（r(Θ) ≥ 1/(2|Θ|)，|Θ| ≥ 3）保持 `conjecture` 环境，**未配 proof**，并写明缺的那一步。

**③ 编译回执（我用 `fs.read` 自核回执，不转述）**
- `tex_sha256` = `9720c473c9ded20c0a9eeba864323ba2d3aaae8df565a3a46f231e9a93782987`，与盘上 `main.tex` 的 sha256 逐字相同（H 亦独立核过同一读数）；
- `pages` = 10，`pdf_bytes` = 304543，`exit_codes` = [0, 0]，`pdf_fresh` = true，`compiled_at` = 2026-10-18T22:36:53+08:00。

**④ H 审校**
- doc_id = `000000`（`data/documents.json` 只有一行），第 5 轮；H 自核被审版本 hash、回执 `tex_sha256` 与盘上正文一致；findings 已落 `review_findings`（本轮新增 finding 000013 等）。
- H 的**总裁决是 rejected**，但拒的不是本轮两条硬要求：它给的四项机器可判读数全绿（正文编号 0、proof 10 处且逐条配对、conj 未配 proof、四件套齐），rejected 来自 G10（我方台账格式缺口）与 G8 记 unknown。按任务口径（正文仍有编号或缺证明时才不许 accepted），本条不是由这两条触发的；H 未判 accepted 这一读数我照实记下，不折成通过。

## 三、谁做了什么

- **G**（t-000059，手稿 000046）：核验正文编号、把三条承重结论升为 theorem 并补分步 proof、调 `doc.paper_compile` 重编 PDF，回报 tex_sha256 / pages。
- **H**（t-000061，手稿 000048）：只读审校 `main.tex` + `main.pdf` + `COMPILE-RECEIPT.json`，逐条打勾落 `review_findings`，给裁决与最小修法。
- **M**（t-000058）：定位盘上现状、读台账确认 doc_id、按顺序派 G → H、回读编译回执自核、写本份说明。

## 四、证据不足与未做

- **H 的最终裁决不是 accepted**：原因是 G10 台账格式缺口与 G8 unknown，不是本轮的两条硬要求。要让 doc 000000 翻成 accepted，需要补 G10 那一格与一份 G8 回执（`run_evidence` 需要一次真实重跑，本轮未派 E 重跑，故如实记 unknown，不写「跑过」）。
- **G8 未跑**：本轮明确「不新增实验」，M 无执行工具，故没有 `run_evidence`；H 记 unknown。
- **本轮没有做 V 的逐行走查**（任务未要求；纯表述层改动，未动命题内容）。

## 五、下游必须遵守的约束

1. 正文（`\appendix` 之前）永远不许出现 `exp:`/`stmt:`/`lit:`/`rel:`/`conj:` 编号；新写的内容要引证据，一律写「见附录 A」。
2. 承重结论只能放在 `theorem` 环境且必须自带分步 `proof`；证不了的必须降成 `conjecture` / Open problem 并写缺哪一步，不许配 proof。
3. 任何改动 `main.tex` 之后必须重调 `doc.paper_compile`，回执 `tex_sha256` 对不上盘上正文就等于 PDF 是旧版。

## 附：重写那一趟（t-000049）的追记

**① 第 3 节的定理进了台账（B，手稿 000050）**：10 条有证明的结果登记为 `stmt:000027`–`000036`，全部 `origin=own_result`、`evidence_kind=proof_review`、`proof_text` 逐字取自正文证明全文（含分步）。对应 `lem:saw` / `lem:criterion` / `lem:lower` / `lem:box` / `lem:period` / `prop:univ` / `prop:k1` / `prop:orth` / `cor:two` / `prop:cond`。第 430 行的 conjecture 与 462 行的 remark 按「有证明才登记」的口径未登记。

**② V 逐行走查（手稿 000052）**：10 条里 **7 条成立、3 条有毛病**——`stmt:000031` 第 (3) 步、`stmt:000032` 第 (1)(3) 步、`stmt:000036` 第 (2) 步，各有步号与所缺依据；这 3 条**未签**第 3 位。按证据契约，正文对应定理的强度不得超过 `proof_review`，且这 3 处不能写成「已证明」。

**③ 本趟未做**：①对 3 条有毛病处回改正文（那要 G 改稿 + 重编译 + H 复核，本趟预算未及）；②H 回执里 3 道 unknown 门的逐一定性（回复只给了计数与 finding 000012 的明细）。
