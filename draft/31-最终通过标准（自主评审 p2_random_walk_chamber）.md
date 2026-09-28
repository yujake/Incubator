# 最终通过标准：自主评审 `p2_random_walk_chamber` 并产出更优论文包

> 来源：所有者逐字 —— "**给一个最后的通过标准：让智能体自主讨论待审核论文
> `C:\Users\ysc20\Desktop\投影度量论\research_papers\p2_random_walk_chamber`，
> 真实地能自己找到参考文献，能去验证或证伪文中的结果，并能产出一个质量更上乘的论文包**"。
>
> 本文件是**验收判据**，不是计划、不是报告。每条判据都写"怎么核"；
> 核不了的（需要人判的）单列在 §6，不许混进"通过"里。

---

## 1. 输入与不可动边界

- **输入（只读）**：`C:\Users\ysc20\Desktop\投影度量论\research_papers\p2_random_walk_chamber`
  实测 14 个文件 / 0.58 MB：`main.tex` 50.1 KB · `main.pdf` 434.5 KB · `EVIDENCE.md` ·
  `LIT.md` · `NOTES.md` · `REVIEW.md` · `SUBMISSION.md` · `code/{clt,engine,gaussian,tail}.py`
  （**只用标准库**：`fractions / itertools / math / random / os / sys`）+ LaTeX 中间产物。
- **不可动**：该目录**一个字节都不许改**。验收开始与结束各跑一次递归 sha256 清单，
  两次必须逐条相同（命令见 §5）。
- **工作区**：`projects/p2-review/`（冷启动建；热启动复用）。原包**只许读**，
  不许拷进工作区当"我们的产物"（拷贝仅允许作为 `library/` 里的只读材料，且要标来源路径）。

## 2. 通过判据 P1–P9

### P1 真实检索（"自己能找到参考文献"）

- 至少落盘 **≥6 条真实文献记录**，每条含：标题 / 作者 / 年份 / DOI 或 arXiv id /
  来源 provider / **落盘路径 + sha256** / 摘要。
- 其中**必须包含** `LIT.md §2` 自己点名的两类：
  - **Brown 1971**，DOI `10.1214/aoms/1177693494`（martingale CLT + invariance principle）；
  - **Hall & Heyde 1980**，*Martingale Limit Theory and Its Application*（Academic Press）。
- **核对方式**：`evidence.json` 的 `sources[]` 里每条 DOI 能被独立解析（我可复核），
  且每条至少到达 **abstract 级**逐字回验（`level` 字段如实）。**零条**也必须在
  `rejected`/`sources_status` 里带理由（三态：没查到 ≠ 没有）。
- **不许**：只写"据我所知有这篇"。没有落盘路径 + sha256 的记录不算找到。

### P2 `Companion` 依赖的判定（本条目是最锋利的一格）

原包 `main.tex` 有 `\bibitem{Companion}` / `\bibitem{Companion5}`，`LIT.md §2` 逐字承认
「The companion volumes and the companion papers of the series are **in preparation**」，
而正文逐字写「we take (eq:dist) as an input from the companion volumes and **do not reprove it here**」。

- 必须把每一条这样的依赖**逐条**落成 `external_unavailable`（带 `status_reason`），
  并给出**影响面**：受影响的是哪些定理/命题（逐条 id）。
- **核对方式**：`dependencies` 表逐行可查 + 报告里能读出"哪些结论因此是条件性的"。
- **反例判据**：若确实检索到了 companion 的正式出版版本（真的查到），
  则必须逐字回验被引定理并升级该依赖；"查不到"与"没查"必须分开（`checked` 三态）。

### P3 逐条断言台账

- `main.tex` 里每个 `\begin{theorem|lemma|proposition|corollary}` 各落一行台账，
  字段：`{来源：自证 / 文献 / 未决}` · `{证据等级：proof / cross_check / heuristic}` ·
  `{我方核到什么程度：证明 / 数值 / 只读了陈述}` · `{能否证伪}`。
- **核对方式**：台账行数 == 脚本从 `main.tex` 数出的条数
  （**实测 24**：`\begin{theorem}` 7 + `\begin{lemma}` 9 + `\begin{proposition}` 8；
  另有 `definition` 1 与 `remark` 5，不计入）；差一行就是漏。

### P4 证伪尝试（负控，必须有）

- 至少对 **3 条**关键结果做反例搜索：写明**搜索范围 / 判据 / 结果**（原始输出 + 退出码）。
- **硬纪律**：找不到反例**不等于**证明 —— 这类结果只能落 `cross_check` / `heuristic`；
  落 `proof` 需要形式化检查器输出（见 P6）。
- **核对方式**：`experiments` 行里逐条可查，`negation_kind` 如实（`no_local_evidence` 不许写成 `disproved`）。

### P5 数值证书复算

- 用 `code/` 的四个脚本（或我方等价实现）复算，报"一致 / 不一致"；
  不一致必须逐条解释（不是"忽略"）。
- **核对方式**：每条带 `code_hash` + 退出码 + 原始输出；我自己能重跑一遍得到同一读数。

### P6 形式化

- 能形式化的引理给 **Lean 4.7.0**（本机 `temp/lean470/.../lean.exe`，实测 `--version` 通过）证明，
  且**公理审计**过（禁 `FORBIDDEN_AXIOMS`；`axiom e_ax : P` + `theorem bad : P := e_ax` 这种空转必须被拦）。
- 不能形式化的引理**逐条**给"为什么不能"（不是"没时间"）。
- **核对方式**：`proof_experiment_ids` 指向的实验 `method=="formal"` ∧ `evidence_kind=="proof"`
  ∧ `verifier_output` 非空。

### P7 更优论文包

产出到 `projects/p2-review/out/paper/`：

1. 主稿（LaTeX 源码 + **编译成功的** pdf）；
2. **四张表**：证据等级统计（proof/cross_check/heuristic）· 否定分类（已证否/未证明/未搜索）·
   依赖表（`external_unavailable` 必须显眼）· 猜想表（提出→检验→支持/否证/升格）；
3. 六件配套：`EVIDENCE` / `LIT` / `NOTES` / `REVIEW` / `SUBMISSION` / 断言台账；
4. **H 的签名**：`accepted@content_sha256`（按 `draft/29` §8.8 的形态），
   且 `coverage{claims_total, claims_reviewed}` **如实**。

### P8 "质量更上乘"的七条可机械核判据（与原包逐条对比）

| # | 判据 | 原包现状（实测） |
|---|---|---|
| 1 | 每条断言有 `citations` 或显式 `heuristic`（schema 强制） | 散文式 provenance（`EVIDENCE.md §1`） |
| 2 | 引文逐字回验率 **100%**（K3 线 ≥99%） | 无机器可核的回验率 |
| 3 | Companion 依赖被判成 `external_unavailable` + 影响面 | 只在 `LIT.md` 写了"in preparation" |
| 4 | 每条证书带 `code_hash` + 退出码 + 原始输出 | 只有 `code/` 目录，无机器核对 |
| 5 | 证伪尝试有**可查询**台账 | 只有 `REVIEW.md` 的魔鬼代言人一节 |
| 6 | H 的签名钉在修订哈希 + 审核覆盖率如实 | 六角色**自查**，无签名、无覆盖率 |
| 7 | 四张表齐 | `SUBMISSION.md`/`NOTES.md` 是散文 |

**判据是"七条逐条成立"，不是"读起来更好"。** 任何一条不成立 ⇒ 本次不算通过。

### P9 四种不许出现的失败形态（每条配注入负控）

1. **编造引文**：注入一条假引文 ⇒ 逐字回验必须拦下（`not_found`）。
2. **把"没查成"写成"论文错了"**：注入"检索失败" ⇒ 结论必须是 `unknown`，**不许** `refuted`。
3. **把数值支持写成 proof**：注入"脚本自报 proof" ⇒ 必须降级 `cross_check`（FC-22）。
4. **引用原文却改原意**：注入"结论强于引文"⇒ H 必须报 `overclaim`（不是 `unsupported_claim`）。

### P10 派活必须由 **M（主 Agent）**完成（验收的元判据）

> 所有者逐字："**到时候要过关的时候不是你把任务派给这些智能体，用户只会一两句话描述需求，
> 要 M 亲自制定计划把活派下去**"；
> 以及同一位所有者对实现形态的纠正："**M 就是主 Agent 呀**"、
> "这又是个把智能体写成大程序的错误实现"。

- **形态**：M 是**主 Agent**（跑在 harness 里、有工具链的智能体），不是"我的代码里的一段计划器"。
  它的**计划就是它的工具调用序列**，轨迹落 `tasks` 台账（`by="agent-M"`）；
  **不许**出现"计划 JSON schema / prompt 模板库 / plan 解析器 / 重计划状态机"这类把智能体写成大程序的东西。
- **M 的工具面**（`roles=("M",)`，只放编排面）：`conductor.summon`（唯一的派活动作，
  内部过 `ALLOWED_EDGES` / `CAPABILITIES` / `_check_params` / `policy` 四上限 / 预算）、
  `conductor.ledger`（看台账）、`conductor.cancel`、`state.summary`（只读状态视图）、
  `role.spec`（把角色规格渲染成 brief）。
- **输入**：用户**一两句话**（例："评审这篇论文 <路径>，并给我一个更好的论文包"）。
- **核对方式**：① M 的工具面非空且**只有编排面**（`CAPABILITIES["M"]=()`、
  `WRITE_SETS["M"]={}` 不变）；② 一次真实运行里 M 连续多轮 `summon`（≥3 步），
  每步过闸门、被拒带 `refusal_reason` 且 M 改道；③ `tasks` 台账能重建 M 的决策序列；
  ④ **把开发者（会话里的父代理）从流程里拿掉**，只要 M 与 harness 还在，活照派。
- **负控**：把 `conductor.summon` 从 M 的面上摘掉 ⇒ M 必须如实报"没有可用工具"，
  **不许**退回"开发者在会话里手工派活"；派给不可召唤的角色 ⇒ `NON_SUMMONABLE` 拒；
  预算耗尽后继续派 ⇒ `refused/budget_exceeded` 留痕。
- **诚实边界**：本判据只保证"派活走工具与闸门、轨迹可审计"，**不保证计划好**；
  计划质量由 K 线与人工复核看，并如实写进 `unknowns`。

### P11 冷/热启动与"优雅停止"由 M 统筹

> 所有者逐字："**M 应该能统筹冷启动、热启动和'优雅停止'，不然怎么叫总控**"。

- **冷/热由 M 决定而不是由程序替它猜**：M 用 `project.ensure(start="auto|cold|warm")` 拿到
  `projects.resolve` 的**四态**（`absent` / `empty` / `workspace` / `not_a_project`）后自己选，
  选择与理由落台账。判据：产物里能读到"这次是冷还是热、为什么"。
- **优雅停止（不是 kill）**，五条同时成立：
  ① `stop` 之后**不再新开任务**；② 在飞任务收尾成终态、**无僵尸行**
  （`conductor.verify_tasks()` 为空）；③ 被砍的结果记 **unknown outcome** 且**不自动重试**（FC-20 第 4 条）；
  ④ 落一份**续跑简报**（做了什么 / 剩什么 / 从哪继续）；⑤ 第二次 `stop` **不改第一次的 `reason`**
  （终态先到先得）。
- **停得下、接得上**：`stop` 之后 `project.ensure(start="auto")` 必得**热启动**（文件夹在），
  M 凭 `resume_brief` 从"剩什么"接着做；停与续两次运行的台账能拼成一条完整链。
- **核对方式**：验收时**在跑到一半时喊停**，然后说"继续" —— 两次运行的 `tasks` 台账 +
  `resume_brief` + `verify_tasks()` 三者互相对得上。
- **负控**：`stop` 之后仍能新开任务 ⇒ 红；`stop` 后留 `running` 行 ⇒ `verify_tasks()` 必须报；
  被取消的任务被自动重试 ⇒ 红；`resume_brief` 缺失或空 ⇒ 红（那就是粗暴 kill）。

---

## 3. 环境事实（实测，决定可行性与边界）

| 事实 | 读数（2026-09-28 实测） | 对验收的影响 |
|---|---|---|
| **Python HTTPS 可用** | `urllib` 取 OpenAlex 200 / arXiv API 200（OpenSSL 1.1.1u） | 框架自己的下载器能取**真实**文献 |
| PowerShell / `curl.exe` 的 HTTPS 不可用 | Schannel 握手失败；明文 HTTP 200 | 探针与检索**不要**走 pwsh |
| DNS | `api.openalex.org` → 104.17.61.98 / 104.17.96.100 | 正常 |
| Lean | `lean.exe` = **4.7.0**（`temp/lean470`） | P6 可做 |
| 论文 `code/` | 只用标准库；**原包给了复算命令**（见下） | P5 可零依赖复算，且有现成锚 |
| hosts | 只有 Steam 系劫持条目 | 与检索无关 |

**原包自己给的证书复算命令**（`SUBMISSION.md` §Reproducing the certificates 逐字；
各自以 `ALL CHECKS PASS` 结束，种子写死在脚本里）：

```text
python -B <原包>/code/engine.py     # exact, ~1 min
python -B <原包>/code/gaussian.py   # ~4 min
python -B <原包>/code/clt.py        # ~10 min
python -B <原包>/code/tail.py       # ~5 min
```

---

## 4. 成本与人工介入（K 线）

- 预算上限：**待实测**（先跑一轮，3 次取中位数再定；不得先填好看的数字）。
- K1 元/可验证产物 ≤ ¥1000 · K3 引文逐字回验 ≥ 99% · K4 人工介入率 ≤ 50%
  （`draft/22:227-230` 逐字；**K4 破线就意味着这不是"自动研究"**）。

---

## 5. 复算命令（验收时逐条跑，读数带时刻）

```powershell
# 0) 原包不可动：开始 / 结束各一次，两次必须相同
Get-ChildItem '<原包路径>' -Recurse -File | Sort-Object FullName |
  ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash + '  ' + $_.FullName } |
  Set-Content temp\p2-original-sha-<before|after>.txt

# 1) 断言条数（P3 的对照数）
(Select-String -Path '<原包>\main.tex' -Pattern '\\begin\{(theorem|lemma|proposition|corollary)\}').Count

# 2) 见 §2 各条的"核对方式"；检索侧探针一律走 python（见 §3）
```

---

## 6. 不在标准内的（诚实边界，写在这里免得被读成"也要求了"）

1. **不要求解决未刊 companion 的数学内容** —— 拿不到就是拿不到，登记 + 影响面分析即为达标。
2. **不要求 Lean 覆盖全部引理** —— 只要求"能形式化的给了证明、不能的给了理由"。
3. **不要求与原包逐句对比打分** —— 那需要人判；只要求 P8 的**七条可机械核**维度逐条成立。
4. **H 必须独立跑**：不许把原包的 `REVIEW.md` 当输入（那是自查，不是复核）；
   对照放在最后（先出我方结论，再逐条对照，差异写进报告）。
5. **本机 HTTPS 的 Schannel 故障**不是本验收要修的东西 —— 框架走 Python 通道即可。

---

## 7. 这个任务到底在考什么：意图、每角色分工、论文包是谁的自然产物

> 所有者提示（逐字）："**待审的论文就是一堆猜想，这就是全部的 input**，
> 显然带着猜想做研究去验证或证伪它是数学研究的主要范式之一。"
> 本节把这句话翻译成设计判断；每条判断都挂实测证据（§1/§3 的那些数）。

### 7.1 我读出的意图（五条，都可核）

1. **输入形态逼着系统必须有"猜想"这个一等对象。**
   实测：`main.tex` 有 **24** 条定理类环境（theorem 7 / lemma 9 / proposition 8），
   其中 **13 条在标题行就 `\cite{Companion5|Companion}`**；而 `LIT.md §2` 自认
   companion 系列 "**in preparation**"。⇒ 超过一半的结论**没有可独立核实的来源**，
   它们的数学地位就是猜想（条件性结果）。**没有 `conjectures` 这张表，输入连装的地方都没有**
   —— 这就是"猜想先行"（`draft/29` §7）从设计偏好变成硬前提的地方。
2. **"真实找到参考文献"是可判、可核、可失败的一件事。**
   只有 **1** 条定理引真外文（Brown/HH）。⇒ 要么真拿到 Brown 1971 并把它声称的
   定理形式对上（martingale CLT + invariance principle），要么如实登记不可得。
   没有第三条路可走（"据我所知"不算）。
3. **"验证或证伪"有现成锚，不许嘴上说。**
   原包给了四个证书的复算命令（`engine.py` exact ~1 min / `gaussian.py` ~4 /
   `clt.py` ~10 / `tail.py` ~5，各以 `ALL CHECKS PASS` 结束、种子写死）。
   ⇒ 我方的每一条结论都要能落到"复算一致 / 复算不一致 / 独立检验 / 反例"中的一格。
4. **原包自己已经很小心 ⇒ "更上乘"不能定义成文笔。**
   `EVIDENCE.md §3` 逐字："None of them proves a statement about all N, all m, or all shapes…
   Simulations carry standard errors and are corroboration only"；
   `SUBMISSION.md` 逐字承认"explicitly does **not** prove the second-order tail constant
   of the companion volume… with the two exact defect locations"。
   ⇒ 质量只能定义成**机器能强制的性质**（这正是 §2 P8 那七条的存在理由）。
5. **原包只读 ⇒ 逼系统把"外部输入"与"我们的产出"分开。**
   这也是仓库里"只读角色 / 发现者≠修正者"（H 的 0 写工具）那条结构纪律的实战检验。

### 7.2 每个智能体在这件任务上做什么（角色 → 产物 → 对应判据）

| 角色 | 干的活 | 产物 | 判据 |
|---|---|---|---|
| **A** | 把论文的数学对象与每条待核结论变成检索式；优先拿 Brown / Hall–Heyde 的**全文**（不是摘要）；做**已知性排查**（这条是不是已有出版证明） | `literature` 行 + 落盘 + sha256 + provider | P1 |
| **B** | 整理成概念/关系 + **逐字引文**；把"来自未刊 companion 的定理"标成**没有引文来源**（它们是猜想，不是关系） | `concepts`/`relations` + quote 三态 | P1/P2 |
| **C** | 依赖图结构分析：哪几条只靠未刊前提（条件性）、哪几条本篇自证（可独立检验）、**哪条前提倒了会带走最多结论** | 报告 + 影响力排序 | P2/P3 |
| **D** | 把那 13 条未刊依赖与 11 条自证结果**登记成猜想台账**（`statement` + `testable` + `origin`）并派活：数值→E、形式化→E(Lean)、已知性→A、换证法→F | `conjectures` 行 + 研究问题 | P2/P3 |
| **E** | 复算四个证书（带 `code_hash` + 退出码 + 原始输出）；对自证结果做独立数值/符号检验；对可形式化的引理出 **Lean proof** 或给"不能"的理由；对 CLT 类结论做**反例搜索**（退化 `Σ_m`、非正则情形） | `experiments` 行 + `proof_experiment_id` | P4/P5/P6 |
| **F** | 把最难但可拆的结论拆成子目标（"距离极限律 = floor 引理 + CLT + 连续映射"），卡住时留 `best_partial` | `attack_plans` + 子目标 | P3/P4 |
| **G** | **成稿**：四张表 + 每条断言带引用或显式 heuristic；引用未刊 companion 处必须标"未刊、不可独立验证" | `documents` + 稿件（tex/pdf） | P7/P8 |
| **H** | **独立**复核（不许读原包 `REVIEW.md`）：过度声称 / 引用支撑度 / 依赖闭合 / 覆盖率如实 + **签字** | `review_findings` + 签名 | P7/P8/P9 |
| **M** | 把"检验一个猜想"当成可计量单元记账；保证状态变更可重放 | `tasks` / `usage_ledger` | K1/K4 |

### 7.3 最终论文包是谁的自然产物（这一问的答案决定设计方向）

- **署名意义上**：稿件正文与四张表是 **G** 的自然产物；"能不能发布"的判定与签名是
  **H** 的自然产物。⇒ 论文包 = **G 的产物 ⊗ H 的签名**（`accepted@content_sha256`）。
- **内容意义上**：包里的每一样东西都有**不同的**产出者 ——
  文献行(A) · 概念/关系与引文(B) · 结构分析(C) · 猜想台账与问题(D) · 证据与 proof(E) ·
  攻坚过程(F) · 措辞与排版(G) · findings(H) · 账(M)。
- **判据意义上的结论（设计方向的核心）**：论文包里每一件东西都必须**能追到它的产出者**
  （谁给的证据、谁定的级、谁签的字）。⇒ **论文包不是"一个智能体写出来的文档"，
  而是"一次运行的可审计对象图"**。这就是 `draft/29` §8 两级引文经济 + §8.8 签名
  在验收层面的落点：把"论文"从**文本**改造成**可审计对象**。

### 7.4 由此明确的设计方向（七条，可判定）

1. **猜想先于一切**（T1 排在 T3/T4 之前）：输入就是猜想堆；`conjectures` 表的 7 处触点
   不落地，后面所有"验证/证伪"都无处落账。→ 与 Goal 的批次顺序一致，现在有了理由。
2. **"检验"必须是可计量、可复现、带原始输出的动作**：证据 = 实验行 + `code_hash` +
   退出码 + 原始输出；"找不到反例"永远不能升格成 proof（FC-22）。
3. **已知性排查是猜想的第一道闸**（`J-A1`）：数学研究里最贵的浪费是重证已知定理。
4. **"更上乘"只落在机器可强制的性质上**（P8 七条）：原包散文已足够小心，比"读起来更好"不算标准。
5. **H 必须独立**：不许把原包的自查当输入，否则"更上乘"退化成互相抄。
6. **未刊依赖必须自动落 `external_unavailable` + 影响面**（P2）：K4（人工介入率 ≤50%）
   要求这类判定不能停在那里等人。
7. **必须会证伪**：13/24 依赖未刊前提 ⇒ 只会"验证通过"的系统没有研究能力；
   P4 的"≥3 条反例搜索"不是装饰，而是这条方向的下限。
8. **M 的落地是"给主 Agent 配工具链"，不是"写一个计划器"**（P10）：M 是主 Agent，
   它的计划就是它的工具调用序列；程序只提供**工具与闸门**（`conductor.summon` /
   `conductor.ledger` / `state.summary` / `role.spec`），不写计划 schema、不写解析器、
   不写重计划状态机 —— 那些都是"把智能体写成大程序"的形态。

### 7.5 这条任务反过来给设计提的三条硬要求

| # | 要求 | 反面形态（不许出现） |
|---|---|---|
| 1 | 不能只**回述**论文 | 把论文的证明重讲一遍就交差（判据：每条结论必须有我方证据，或明确标"未核"） |
| 2 | 不能只有"通过" | 只会落 `verified`；`refuted` / `unknown` 没有落点（三态被折平） |
| 3 | 不能"看起来好" | 用措辞与排版代替可核事实（判据：四张表 + 签名 + 覆盖率，逐条可机械核） |
