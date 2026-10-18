# 交付说明：正文编号清零 / 定理与分步证明 / 重编译回执对齐 / H 只读审校

本会话 Lean 形式化**已关闭**（`toolchain.lean_enabled=false`）⇒ 不写 Lean、不调检查器、不落 `method=formal`；`evidence_kind=proof` 这一档产不出来，正文与交付里都不出现「已证明 / 已形式化验证」。

## 一、任务与范围

本趟只做收尾，不动研究内容：①正文内部编号清零（编号整体归入 Appendix A）；②主结果以定理环境呈现、定理与引理配分步证明、证不了的写成 Conjecture / Open problem 并写明缺哪一步；③重编译 `main.pdf` 使 `COMPILE-RECEIPT.json` 的 `tex_sha256` 与盘上正文一致，并由 H 只读审校、findings 落 `review_findings`。**未新增实验、未改任何台账结论。**

## 二、谁做了什么（按台账与手稿）

| 台账号 / 手稿 | 角色 | 做了什么 | 落点 / 读数 |
|---|---|---|---|
| t-000063（本趟 M） | M | `fs.search` 定位编号、读附录边界、核对 theorem/proof 配对；两处体例改写（`fs.edit`） | `out/paper/main.tex` |
| t-000064（手稿 000050） | H | 只读审校第一轮（sha 4534fd5b），落 findings，含 warning 000009（两段证明为单段落未分步） | `data/review_findings.json` |
| t-000066（手稿 000051） | G | 重编译正文 | `out/paper/main.pdf`、`COMPILE-RECEIPT.json` |
| t-000068（手稿 000052） | H | 复核现行版（sha 58d146f4），三项指定检查在正文层面全通过 | `data/review_findings.json` |

## 三、逐条读数

### ① 正文编号 = 0（通过）

- M：`fs.search` 模式 `(exp|stmt|lit|rel|conj):[0-9A-Za-z]` 全文 14 处命中，行号 **832–845**，全部在 `\appendix`（816 行）之后的 Appendix A「Reproducibility index」表内；正文段（1–815 行）命中 **0**。
- H 独立复核（现行版 58d146f4）：模式 `\(exp|stmt|lit|rel|conj):[0-9]|conjectures?[ ~]?[0-9]{4,}` 全文命中 2 条，在 **856、857 行**（`conjectures 000000` / `conjectures 000001`），`\appendix` 在 **826 行** ⇒ 两条都在附录 A，正文命中 **0**。
- 结论：**正文编号数 = 0**，编号只保留在 Appendix A 并有可复现入口（脚本、参数、`out/eq_s1/results.json`、`out/experiments/`）。

### ② 定理环境与分步证明（通过）

- 环境配对（M 用 `fs.search` 逐条核）：`lemma` 210/242/322/437/501、`proposition` 254/293/406/655、`theorem` 354 —— 共 **10 个**定理类环境，对应 **10 个** `\begin{proof}`（221/247/265/298/333/372/417/448/507/670），无一缺证明。
- H 复核（现行版）：10 条编号结论 ↔ 10 个 proof，一一对应无遗漏；两段原先为单段落的证明（`lem:zero-var`、`prop:finite-scan`）现已改为 Step 1/2/3(/4) 分步 —— 依据 H 的 warning 000009。
- 无证明的结论：`conjecture` 2 条（689、700 行）与 `problem`（Open problem）7 条（716–760 行），每条写明缺哪一步（items (1)–(4) 缺计算或已知型估计，(5)–(7) 缺想法）。

### ③ 重编译与回执对齐（通过）

- 改正文后由 G 重编译（t-000066）：`tex_sha256=58d146f4d52e85e58194ce7f9a9701a2bd0e80914fa0983fe4fa2adb61b8d8fa`，与盘上 `out/paper/main.tex`（54098 字节）逐字一致；`pages=15`、`pdf_bytes=368745`、`exit_codes=[0,0]`、`pdf_fresh=true`、`pdf_sha256=393b7157f59ac83f837f1c5f9689123279c61558bc42c3518dbaf0ab761af294`。
- 改前那一版的回执是 `4534fd5b…`，已随重编被覆盖 —— **盘上 PDF 是现行正文编的**。

### ④ H 审校落库（通过，但裁决要分开读）

- H 两次审校的 findings 都经 `review` 动作写进 `data/review_findings.json`（doc_id=000000），不是只写在回复里。
- **要如实分开报的一句**：H 的最后一次回复里，三项指定检查（正文编号 / 定理配 proof / 无证明结论的写法）在**正文层面全部通过**，但整份 G1–G15 审校报告仍判 `rejected` —— 那不是这三条引起的，是更早一轮就挂着的 claims 侧欠账（见「还剩什么没做」）。

## 四、证据等级与不足

- 本趟所有改动都是**体例改动**（proof 分步标记），命题内容、数值、引文一字未动；无新增实验、无台账结论变动。
- 形式化关闭 ⇒ 承重结论的 T3 判据 `na`（不是通过，也不是失败）。

## 五、还剩什么没做

1. **H 的整份审校仍判 `rejected`**：欠账在 claims 侧（G1–G15 报告里 earlier 轮的 findings），与「正文编号 / 定理证明」这三条无关，本趟未处理（越出「只做两件收尾」的范围）。
2. **签名的版次**：`conductor.closing` 报 R10b「审校钉在现行版」0 条 —— 稿件 `documents/000000` 的签名钉的是 markdown 那一版的摘要（936ad599），不是 `out/paper/main.tex` 的 sha；要消这一格得由 G 走 `documents` 侧重建并把 H 的签名钉到现行版，本轮预算内未做。
3. **验收表机器可判行不满足**（`acceptance` 格 fail）：`statements` 三条缺 `page_range`、部分召唤缺 `input_key` —— 都是台账侧的既有欠账，不在本趟「不改台账」的允许范围内。
