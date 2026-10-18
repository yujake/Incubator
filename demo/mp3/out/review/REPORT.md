# 交付说明（M · t-000066）：两项收尾（正文编号清零 / 主结果定理化）+ 重编译 + H 审校

体例：本说明按五节组织（一 做了什么、二 逐条读数、三 证据不足与未核到、四 还剩什么没做、五 台账引用核对）。本次未落 `out/review/REPORT-STYLE.json` ⇒ 收工门「报告体例兑现」那一格记「没有体例声明」，不按通过读。

范围：只做收尾，不改研究内容、不新增实验、不改台账结论。本会话 Lean 形式化关闭（`toolchain.lean_enabled=false`）⇒ 全稿强度上限 proof_review，正文与附录均无「已形式化验证」类用语。

## 一、做了什么、谁做的

| 步骤 | 执行者 | 结果 |
|---|---|---|
| ①正文内部编号清零：把所有 `exp:/stmt:/lit:/rel:/conj:` 指涉整体留在 Appendix A，正文对应处改成不带编号的话 | G（名册 G1，t-000067，交接手稿 000053） | ok（改前改后各搜一次并与 `\appendix` 同次比对） |
| ②主结果定理化：主结论用 `\begin{theorem}`，引理只作支撑，定理与引理带分步 `\begin{proof}`；四处 proof 只是 sketch 的（gradedsimple / kn / poly / solvable）按 H 的 finding 降成 `\begin{conjecture}` + 具名 remark 写明缺哪一步 | G（G1，t-000072，交接手稿 000055/000056） | ok |
| ③重编 `out/paper/main.pdf` 并核对回执 | G（`doc.paper_compile`） | ok，见第二节读数 |
| ④只读审校 `out/paper/main.tex` + `main.pdf`（doc_id=000003），findings 落 `review_findings` | H（名册 H1，t-000070，交接手稿 000054） | ok，裁决 **in_review（不是 accepted）**：finding 000018 error、000019 info |

## 二、逐条读数（我自己核过的，不转述别人的一句话）

- **编译回执与盘上正文一致**：回执 `tex_sha256 = 4ce977c0ee293117d43140cee19deeada2dc96acb92b94d719117816cc0e9898`；我用 `fs.stat` 现算盘上 `out/paper/main.tex` 的 sha256 = `4ce977c0ee293117d43140cee19deeada2dc96acb92b94d719117816cc0e9898`（49048 字节，mtime 22:42:29）—— **逐位相同**。`pages = 15`，`pdf_bytes = 404465`，`pdf_fresh = true`，`exit_codes = [0,0]`，`compiled_at = 2026-10-18T22:42:36+08:00`。
- **正文编号数 = 0**：一次 `fs.search`（`(exp|stmt|lit|rel|conj):[0-9]` 与 `\appendix`、定理/引理/猜想/证明环境同一正则）读出：`\appendix` 在**第 745 行**；全部编号指涉命中出现在**第 811 行及以后**（附录 A 内，含 exp:000011 / exp:000012 / stmt:000001–000019 / lit:000001–000025）。**正文 1–744 行命中 0 处**。
- **环境分布（同一读数）**：`\begin{theorem}` 在 280（thm:findim）、316（thm:abelian）、358（thm:descent）；`\begin{lemma}` 在 170/210/244/302/344（lem:pbw、lem:hilbert、lem:lift、lem:abelian、lem:module）；`\begin{conjecture}` 在 498（thm:gradedsimple）、557（thm:kn）、599（thm:poly）、633（thm:solvable）、686（conj:SW = Sierra–Walton 一类一般情形，写明缺哪一步）；`\begin{proof}` 共 11 处（178/216/250/285/306/321/349/366/407/432/486/545）。即：**留下的 3 条定理与 5 条引理都带 proof，4 条补不齐的降成 conjecture，一般情形单独一条 conj:SW**。
- **H 的裁决是真读数、不是通关**：`in_review`，finding 000018（error，四处 sketch proof 缺最后一步）+ 000019（info，正文编号 0 处的核验记录）。G 的第二次修订（t-000072）**正是对着 000018 改的**。
- **README 与核算**：本报告点到的台账引用只有 `review_findings 000018/000019`、`documents 000003`、交接手稿 000053/000054/000055/000056 —— 均在本轮工具返回里出现过。

## 三、证据不足与未核到（不许折成「没问题」）

1. **H 的审校是对「降级之前」那一版签的**（被审版本 sha256 = `62f6405cf74b3437…`，865 行）。降级之后盘上这一版 sha256 = `4ce977c0…`（49048 字节）。**降级后的现行版没有再走一轮 H 审校** —— 预算只剩 0.216 美元，我没有再派。所以严格说：`reviewed_current_rows` 这一档对现行版**没有闭环**，本轮不允许把它读成「已审过」。
2. **四条被降成 conjecture 的命题，缺的那一步是数学缺口，不是我这一趟能补的**：gradedsimple 的缺口写在 line 518 那个具名 remark 里（原话：this is the step that is not carried out in this note）；kn / poly / solvable 三处同理。这是我按任务要求「不许写成我们的结果」做的降级，**不等于它们被证否**。
3. **一般情形（Sierra–Walton 一类）我未核到任何我们的结论**：正文只有 `conjecture` 环境 `conj:SW`（line 686，引 `\cite{SW14}` 的表述）。这一档的证据读数是「本工作区内既无构造也无反向定理」。
4. **附录 A 的数值结论只在有界范围内成立**（$d=3$、$0\le n\le8$ 的过滤维数；$1\le n\le12$、次数界 12 的严格包含），本轮未重跑脚本、未新增实验（任务明令不许）。
5. **形式化**：本会话整条关闭 ⇒ `proof_experiment_rows` 一档是 `na` 而非 0；正文未出现任何机器验证用语（这是要求，不是缺陷）。

## 四、还剩什么没做

- 让 H 对**现行版**（sha256 `4ce977c0…`）重审一轮，把 000003 的签名钉到这一版上（处置 `reviewed_current_rows`）。
- 派 V 对留下的 3 条定理 + 5 条引理的证明逐条 `verify.verify_proof`（本会话唯一的「审过」凭据）—— 本轮**没有** V 的走查签名，`reviewed_proof_rows` 记 0，这是「没做」不是「无需做」。
- 附录 A 的数值断言在台账侧的对应行（上一轮 H 的 G7 fail）本轮未补，任务要求不动台账结论，故未动。

## 五、台账引用核对

- `documents 000003`：被审稿件行（kind=paper），H 的 review_findings 挂在这一行上。
- `review_findings 000018`（error，四处 sketch proof）、`000019`（info，正文编号 0 处）—— H（t-000070）落库。
- 交接手稿 000053（M→G 派活）、000054（M→H 派活）、000055（G→M 降级完成）、000056（M→G 第二轮派活）。
