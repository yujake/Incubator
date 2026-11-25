# 工作区目录与文件名规范（WORKSPACE-LAYOUT）

> 业主口径（2026-11-25，逐字）：「你要看这些文件夹命名是不是系统定好的，还是随便起的，
> 要钉住一套规范，只允许少量自由发挥。」
>
> 执行体：`src/agentflow/wellformed/naming.py`（类别名 `workspace_layout`）。
> 判据：`tests/test_workspace_layout_naming.py`（15 条函数 / 16 个用例；含 2 条反真空：
> c6 摘规则、c7 摘分类器）。
> 读法：`python scripts/check_wellformed.py --root <工作区> --kind workspace_layout`。

## 0. 一句话

工作区的目录树里，**A 类（系统固定）与 B 类（系统生成名）占绝大多数**；真正留给模型
起名的是 **5 处 C 类自由档**，而每一处都规定了目录、模式与层级上限。三档的严重度不同：

| 档 | 违反时 | 读者看到什么 |
|---|---|---|
| **A 系统固定** | `error` | 「这一格被改名了 / 被顶替了」—— 框架按常量找它，找不到就当成「没有」 |
| **B 系统生成名** | `error` | 「这份产物的名字不是框架会产出的形态」—— 它进不了按名字认领的那条链 |
| **C 有限自由** | `error` | 「这个自由档越界了」—— 越层、后缀不对、或前缀不是角色 |
| **未知条目** | `warning` | 「盘上多了一样系统不认识的东西」—— 可能不是缺陷，但它没有归属 |
| **工具链缓存** | `warning` | 「某个外部工具把缓存落进了工作区」—— 不归框架管，但会跟着一起被打包 |

`warning` 与 `error` 都翻三态（`malformed`），但**分列**：前者是「没归属的自由发挥」，
后者是「系统固定的那一格被动过」。两者折平之后，读者分不出「该删」与「该登记」。
唯一不翻三态的是 `legacy`（`-vN` 历史名：读得通、可列出、不可签）。

---

## 1. A 类：系统固定（目录名与文件名都是代码常量，模型不得自创）

### 1.1 工作区根上的固定目录

| 目录 | 谁在拼 | 里面装什么 |
|---|---|---|
| `data/` | `store.py:868` | 台账表（`schema.TABLES`）+ 已登记账本（`events.jsonl` / `counters.json` / `lit_*.jsonl` / `research_request_ledger.json`）+ `data/.locks/` + `data/archive/lit_candidates/` |
| `sessions/` | `sessionnames.py:28/36` | 会话事件流 `<会话号>.jsonl` |
| `runs/` | `cacheface.py:222` / `errorstats.py:1346` / `manuscriptids.py:92` | 每趟记录、缓存档位、停历史 |
| `library/` | `schema.py:418` / `locallib.py` | 已登记书架（内部命名归 `wellformed/literature.py`） |
| `manuscripts/` | `manuscriptfamily.py:37/44-47/64` | 正文手稿 `manuscripts/<角色>/` |
| `work/` | `layout.py:72` | 草稿区 `work/<角色>/` 与交接账本 `work/handoffs.jsonl` |
| `notes/` | `agent_loop.py:215/2218` | 逐实例草稿本 |
| `code/` | `agent_skills.py:4718` | 脚本与 Lean 源码 |
| `out/` | 各子系统（见 1.2） | 框架产物区 |
| `reference/` | `seedinject.py:71` | 用户投放的可靠参考文献（文件名由用户给） |
| `source/` | `agent_b/run_once.py:46` | 用户给的论文源（`source/main.tex`） |
| `downloads/` | `search_tools.py:152` | 下载中间态（文件名由 `fetch` 层给；收编即搬走） |
| `verifications/` | `v_vocab.py:19` | V 的复核台账 |
| `doc-signatures/` | `signatures.py:254` | H 的文档签名快照 |
| `index/` | `sessions.py:52` | 派生索引（只 `run-index.json`） |
| `projects/` | `projects.py:497` | 多项目根（`projects/<项目名>/` 是另一个工作区，本层不往下判） |

**禁止**：模型新建任何不在上表的顶层目录。`datas/`、`docs/`、`reports/`、`documents/`
都不认（`reports/` 与 `documents/` 是已退役的旧布局，由 `wellformed/layout.py` 判 `error`）。

### 1.2 `out/` 下的固定子系统

| 目录 | 谁在拼 | 里的固定文件名 |
|---|---|---|
| `out/clock/` | `clockbase.py:41-46` / `clockwaitany.py:67/300` | `state.json`、`wake.json`、`waits.json`、`wait_any.json`、`handoffs.json` |
| `out/exp-logs/` | `agent_e/run_experiment.py:521` | `<实验号>.log`（B 类） |
| `out/experiments/` | `exhaustionreport.py:72-115` | `<实验号>/exhaustion.md`（B 类） |
| `out/invalid/` | `agent_loop.py:1112` | `<会话号>-<角色>-step<N>.txt`（B 类） |
| `out/package/` | `papercompile.py:57-95` | `main.tex`、`main.pdf`、`mapping-appendix.tex`、`MAPPING.json`、`MAPPING.md`、`ACCEPTANCE-TARGETS.json`、`COMPILE-RECEIPT.json` + `compile-<时间戳>.log`、`main.<引擎后缀>` |
| `out/report/` | `review_tools.py:2642` / `cli.py:5240` | `REPORT.md`、`NO-GATE.json`、`REPORT-STYLE.json`、`m-verdicts.jsonl` + `STATUS-<时间戳>.{md,json}`、`<文档号>-review.md`（B 类） |
| `out/roster/` | `secretary_ledger.py:293-330` | `<父>.jsonl`、`<父>-index.jsonl`、`<父>-surfaces.jsonl`、`<父>-retired.jsonl`、`refusals/<父>.jsonl`（B 类） |
| `out/secretary/` | `secretary_ledger.py:33` | `<角色>.jsonl`、`<角色>-t-<6位>.jsonl` + `relay.jsonl`、`nontriviality.jsonl`、`proposition_form.jsonl`、`proposition_verdicts.jsonl`、`statement_same.jsonl`、`dispatch_fit.jsonl`、`refusals.jsonl` |
| `out/steps/` | `conductor.py:489/606-613` | `<台账号>.jsonl`（B 类） |
| `out/surfaces/` | `secretary_ledger.py:345` | `<父>/<槽位>/…`、`archive/<父>-<名>/`（B 类；槽位形如 `S01`） |
| `out/sysguard/` | `sysguard.py:75/134` | `write-readings.jsonl` |
| `out/tasks/` | `conductor.py:10449` | `<台账号>.json`（B 类） |
| `out/texts/` | `text_tools.py:316/437` | `<名>.txt`、候选期 `cand-<槽位>.txt`（B 类） |
| `out/vsigns/` | `vsigns.py:114/449` | `issued.json` + `<正文 sha>.json`（B 类） |

### 1.3 工作区根上的固定文件

`ARTIFACTS.jsonl`（`artifacts.py:60`）、`DOC-SIGNATURES.jsonl`（`signatures.py:252`）、
`RELIABLE-REFERENCES.json`（`locallib.py:99`）、`budget.json`（`budget.py:60`）、
`web-actions.jsonl`（`webui/audit.py:82`）、`AGENT-PROFILES.md`（`agent_prompts.py:2752`）、
`.agentflow-workspace`（`projects.classify` 的标记）、`.agentflow-stop`（停止信号）。

**禁止**：把 `REPORT.md` 写成 `REPORT-1.md`、把 `state.json` 写成 `clock.json`、把
`issued.json` 写成 `issued-v2.json` —— 读侧按常量找，改名之后它读不到，而读不到会被读成
「没有」。

---

## 2. B 类：系统生成名（目录固定，名字由框架按 id / hash / 日期生成）

| 模式 | 生成者 | 例 |
|---|---|---|
| `out/exp-logs/<4-6位>.log` | `agent_e/run_experiment.py:521` | `out/exp-logs/000000.log` |
| `out/experiments/<4-6位>/exhaustion.md` | `exhaustionreport.py:115` | — |
| `out/invalid/<会话号>-<角色>-step<N>.txt` | `agent_loop.py:1112` | `out/invalid/2026-11-22n-B-step20.txt` |
| `out/roster/<父>-{index,surfaces,retired}.jsonl` | `secretary_ledger.py:294-350` | `out/roster/t-000001-retired.jsonl` |
| `out/secretary/<角色>-t-<6位>.jsonl` | `secretary_ledger.decisions_path` | `out/secretary/B-t-000004.jsonl` |
| `out/steps/<台账号>.jsonl` | `conductor.steps_dir` | `out/steps/t-000001.jsonl` |
| `out/tasks/<台账号>.json` | `conductor:10449` | `out/tasks/t-000002.json` |
| `out/report/STATUS-<YYYYMMDD-HHMM>.{md,json}` | `statusreport.py:650-661` | `out/report/STATUS-20261125-0359.md` |
| `out/report/<文档号>-review.md` | `review_tools.py:2685` | `out/report/000001-review.md` |
| `out/package/compile-<YYYYMMDD-HHMMSS>.log` | `papercompile.py:19-20` | `out/package/compile-20261125-035819.log` |
| `out/vsigns/<64位 sha>.json` | `vsigns.py:449` | `out/vsigns/099eb364…1148.json` |
| `out/texts/cand-<槽位>.txt` | `text_tools._text_name` | `out/texts/cand-000000.txt` |
| `manuscripts/B/b-proof-<号>.md` | `manuscriptfamily.relpath` | `manuscripts/B/b-proof-000001.md` |
| `manuscripts/F/f-proof-<号>.md` | 同上 | `manuscripts/F/f-proof-000001.md` |
| `manuscripts/E/e-proof-<号>.md` | 同上 | — |
| `manuscripts/D/<问题号>-research.md` | `depsection.py:1444` | `manuscripts/D/000000-research.md` |
| `manuscripts/G/<文档号>.md` | `doc_tools.py:1981` | `manuscripts/G/000001.md` |
| `work/A/lit-r-<文献号>.md` | `litstage.py:156` | `work/A/lit-r-000001.md` |
| `work/A/lit-<请求号>.submitted.md` | `litstage.py:158/164` | `work/A/lit-r-000001.submitted.md` |
| `work/C/<报告号>-<kind>.md` | `agent_c/_support.py:233` | `work/C/000000-gaps.md` |
| `work/E/e-num-<实验号>.md` | `manuscriptfamily.py:47` | `work/E/e-num-000000.md` |
| `work/F/attack-<计划号>.md` | `agent_f/core.py:2153-2157` | `work/F/attack-000000.md` |
| `notes/<角色>[-<实例>].md` | `agent_loop.py:2218-2229` | `notes/A-A1.md` |
| `doc-signatures/<文档号>-<16位hash>-<序号>.json` | `signatures.py:504-515` | `doc-signatures/000001-66c671e9a0e7361f-002.json` |
| `verifications/<命题号>.jsonl` | `v_vocab.py:19` | `verifications/000034.jsonl` |
| `verifications/pending/<载体 sha>.jsonl` | `vsigns.py:2284` | `verifications/pending/0cf2e9d6….jsonl` |
| `verifications/reviews/v-review-<6位>.md` | `vreviews.py:76-95` | `verifications/reviews/v-review-000001.md` |
| `sessions/<会话号>.jsonl` | `sessionnames.py:53` | `sessions/2026-11-25.jsonl` |
| `data/archive/lit_candidates/archive-r-<请求号>.jsonl` | `litstage.py:1107` | `data/archive/lit_candidates/archive-r-000001.jsonl` |
| `library/<6位号>/<名>` | `locallib.py`（内部名归 `literature.py`） | `library/000001/daac9fe7d2e3-….pdf` |

**禁止**：在 B 类目录里用别的名字（`out/vsigns/not-a-sha.json`、`out/steps/step1.jsonl`）。
B 类的名字是「框架认领它的凭证」：名字不对，这份产物就永远进不了那条链，而读侧不会报错。

---

## 3. C 类：有限自由（模型可以起名，但必须落指定目录、匹配模式、不新建层级）

| 自由档 | 目录 | 模式（可执行） | 层级上限 | 允许的例 | 违规的例 |
|---|---|---|---|---|---|
| 实验脚本 | `code/` | `<名>.py` / `<名>.lean` / `<名>.steps.jsonl`，名字 `[A-Za-z0-9_][A-Za-z0-9_.-]*` | `code/<名>` 或 `code/<一层目录>/<名>`（**不许第三层**） | `code/exp/lpsec_validate.py`、`code/formal/000004.lean` | `code/a/b/c.py`、`code/exp/x.txt` |
| 草稿本 | `notes/` | `<角色>[-<实例>].md`，实例标签 `[A-Za-z0-9._-]{1,40}` | 一层 | `notes/A.md`、`notes/A-A1.md`、`notes/B-B-digest1.md` | `notes/probe.md`（不以角色开头）、`notes/A/sub/x.md` |
| 草稿区 | `work/<角色>/` | `<名>.md`，名字 `[A-Za-z0-9][A-Za-z0-9._-]{0,119}` | 一层 | `work/E/lp3-section-report.md`、`work/A/lit-r-000001.md` | `work/A/sub/x.md`、`work/A/x.json` |
| 面池里的槽位 | `out/surfaces/<父>/` | `S<两位>`（池发的号） | 槽位目录里随便（那是子代理自己的根） | `out/surfaces/t-000001/S01/` | `out/surfaces/t-000001/scratch/` |
| Lean 声明名 | `code/formal/` | 同上（`<声明名>.lean`，声明名由模型写的 Lean 给） | 一层 | `code/formal/add_zero.lean` | `code/formal/深/层/add_zero.lean` |

**三条硬约束**（C 类与「随便起」的分界）：

1. **必须落在指定目录**：`code/` 的脚本不许写到 `notes/`、工作区根或 `out/`；
2. **必须匹配模式**：后缀、前缀、字符集都要对（`notes/` 的前缀是角色，不是题目）；
3. **不许新建目录层级**：`code/<一层>/<名>` 是上限；`work/<角色>/<名>` 与 `notes/<名>`
   只有一层。要多放几份就摊在同一层，用名字区分 —— 层级是框架的，不是模型的。

**违反时读者会看到什么**：`error` + 逐字读数（哪个路径、允许的形态是什么）。读者据此
判断是「模型越界了」（收窄那一处写口）还是「规范太窄了」（改这一份文档 + 判据）。

---

## 4. 自由档之外：本层不判的地方

| 路径 | 为什么不判 |
|---|---|
| `library/**` 的名字 | 归 `wellformed/literature.py`（LIB-LAYOUT 路）；本层只判结构（`<6位号>/<名>` 或扁平一段，两种都 `ok`） |
| `reference/`、`source/`、`downloads/` 的文件名 | 用户或下载器给的，框架不该替它们改名；本层只判层级 |
| `projects/<项目名>/` 以下 | 那是另一个工作区，由它自己那一次检查判 |
| `.miktex/`、`__pycache__/`、`.lake/` 的内容 | 工具链缓存；一条 `warning` 点到目录为止，不逐份报 |
| 各文件的内容 | 归各产物自己的规则（行/列/签块/证明稿） |

---

## 5. 真机读数（2026-11-25，本规范落地时）

`python scripts/check_wellformed.py --root <工作区> --kind workspace_layout` 的原样读数：

| 工作区 | ok | warning | error | 逐条 |
|---|---|---|---|---|
| `demo/lp-ball-22` | 835 | 2 | 0 | `.miktex`（缓存）、`code/exp/__pycache__`（缓存） |
| `demo/sylow-4` | 382 | 1 | 0 | `.miktex`（缓存） |

> 同一天 17:30 的另一次读数里 `demo/lp-ball-22` 是 **4 条 warning**：多出的两条是工作区根上的
> `_exp.py` / `_exp2.py`（无归属的实验脚本）。18:00 复跑时那两份未跟踪文件已被别的 lane 清掉 ——
> 写侧"能在工作区根上新建任意文件"这条缺口仍在，由 `temp/dirspec/REPORT.md` §7 ① 的探针复算
> （`fs_tools._landing_refusal("_exp.py", "E") is None`）。

`demo/lp-ball-22` 的 `library/` 是 2026-11-25 重打包后的 25 个 `<6位号>/` 目录（每个两份
文件）⇒ 新形态判 `ok`；`demo/sylow-4` 的 `library/` 还是扁平落点（历史形态）⇒ 也 `ok`
（宽严归 `literature.py`）。两份 demo 都**没有一条 `error`**：产品的写侧在这些落点上
没有自由过头。

**warning 是读数，处置建议**（本路不改写侧）：

- `.miktex/`：`papercompile` 起 LaTeX 时 `env` 没钉 `TEXMFVAR` / `TEXMFCONFIG` / `TEXMFHOME`
  （`papercompile.py:313-316`），缓存放哪由外部工具决定 ⇒ 实测落在工作区根上。它跟着工作区
  一起被打包，是**真缺陷**（不是命名缺陷）；收窄方案见 `temp/dirspec/REPORT.md` §7 ⑥。
- `code/exp/__pycache__/`：Python 的导入缓存。判 `warning` 而不是 `error`：清掉它不影响任何
  读数，但它不该进交付包。
