# agentflow —— 面向数学研究的多智能体协同框架（正式版）

> 原型（A/B 双智能体文献流水线）在 `D:\Incubator\test\test1`（包名 `abflow`），**保持不动**；
> 本目录是**正式版**。两份的关系、以及为什么要另起一份，见 `DEVELOPMENT.md` §0 与
> `..\draft\13-数学研究多智能体协同框架-正式设计草案.md`。

**本文件只讲"怎么跑"与"现在到底有没有跑通"。** 判据性文档的入口是 [`DEVELOPMENT.md`](DEVELOPMENT.md)
（开发规范）与 [`docs/ROLE-SPECS.md`](docs/ROLE-SPECS.md)（角色规格）；设计**理由**在
`DESIGN*.md`（不构成判据，与代码冲突时以代码为准）。

---

## 1. 这是什么

**一个用户控制的主控（M），按需唤起 A–H 八个角色；角色之间也可以互相唤起。**

```
                        ┌──────────── 用户 ────────────┐
                        │                              │
                        ▼                              │
                   M（主控 · conductor）               │
        召唤 / 策略 / 并发调度 / 取消 / 台账(tasks)      │
                        │                              │
   ┌────────┬───────────┼───────────┬─────────┬────────┤
   ▼        ▼           ▼           ▼         ▼        ▼
   A ──────▶ B ───────▶ C           D ◀──────▶ E       F
 文献检索  文献整理   只读关系分析  研究        实验/    难题攻坚
   │        │           │           │         形式化    │
   └────────┴───────────┴───────────┴──────────┴────────┘
                        │
                        ▼
                   G（撰写）──▶ H（审校）──▶ G（修订）
```

| 角色 | 一句话职责 | 副作用面 | 它能召唤谁 |
|---|---|---|---|
| **M** | 召唤、策略判定、并发调度、取消、写运行台账 | 只写 `tasks` | A–H 全部 |
| **A** | 文献检索 + 下载 + 登记 | `effect` = `read`/`write_local` × **`external=egress`**（3 件：`search.literature`/`providers`/`download`）；**不是唯一有外呼的角色**，见下 | B |
| **B** | 抽取概念与关系（含**引文逐字回验**） | `write_local` × **`external=egress`**（`ocr.run` 首次会下 easyocr 模型） | C |
| **C** | **只读**关系分析（最热/路径/冷门/缺口/矛盾/结构重复） | `read`（工具面 **17** 个只读工具，**零写工具**、`external` 恒 `none`） | **无**（连"请求"都不直接发） |
| **D** | 研究循环：把 C 的报告变成研究问题并回答 | `write_local`；`external` **恒为 `none`**（零 `egress`、零 `exec`） | A B C E F |
| **E** | 数值实验 + 形式化验证（**计算类拿不到 `proof`**） | `write_local` × **`external=exec`**（起 Lean/Coq/Isabelle 与实验脚本子进程） | B D |
| **F** | 多轮难题攻坚（预算不足即拒绝立项） | `write_local` × **`external=exec`**（`verify.run_experiment` / `verify.check_formal`；`attack.step` 经 `_deploy_e` 起 E 的脚本子进程，见 P-13 §4.3 第 10 条） | A B C D E |
| **G** | 撰写：断言 / 依赖 / 稿件 / 修订 | `write_local` × **`external=exec`**（与 F 同源） | D E F |
| **H** | **审校**：G1–G15 门、发现落库、状态更新 | `write_local`（**只有一个被钉死的写面**）；两根轴上 `external` **恒为 `none`**（零 `egress`、零 `exec`） | **只能召唤 G** |

> ⭐ **"副作用面"这一列在 B3 收官后是两根轴**（`effect` × `external`，`docs/PROPOSALS.md` **P-13**）。
> **"A 是唯一联网角色"这句话今天不成立** —— 已按实测更正（观测 2026-09-26T04:44）：
> `external != "none"` 的工具有 **6 件**（`ocr.run` / `search.download` / `search.literature` /
> `search.providers` / `verify.check_formal` / `verify.run_experiment`），它们分布在
> **`{'A','B','E','F','G'}`** 这五个角色上（C / D / H 一个都没有）。
> 复跑：`$env:PYTHONPATH='src'; python -m agentflow.cli tools`，再看某角色 `--role <X>`。
> ⚠️ 工具条数有**两个口径**，不许互换：`build_registry(store=None)` ⇒ **50**；
> 含 store 的完整装配（= `cli tools`）⇒ **55**。见 `docs/ROLE-SPECS.md` §0.3。

**三层结构**（`DEVELOPMENT.md` §2.1）：

- **领域对象层**：`research_questions` / `attack_plans` / `experiments` / `documents` / `dependencies` / `review_findings`
- **知识层**：`literature` / `concepts` / `relations`
- **运行记录层**：`tasks`（编排台账） / `usage_ledger` / `eval_results` —— **与领域对象分层**，
  因为"跑过什么"和"知道了什么"是两件事（`status` 与 `outcome` 正交：
  `status ∈ pending/running/done/cancelled/failed` 回答"跑完没有"，
  `outcome ∈ ok/no_result/not_applicable/refused/failed/cancelled` 回答"产出了什么"。
  **`refused` 是一次成功执行** —— 框架正确地说了"不"）。

**贯穿全项目的三条纪律**（细节见 `DEVELOPMENT.md` §3）：

1. **三态纪律**：`True` / `False` / `None` + 受控 `reason`。**"没做" ≠ "做了没结果"**。
2. **单一来源**：同一判据只有一处实现，别处必须**转发**（不许多写一份并行的）。
3. **fail-closed**：未接线 / 依赖缺失 / 读不到 ⇒ **显式失败**，不许静默返回空。

---

## 2. 30 秒跑通（完全离线，不访问网络）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
cd src
python -m agentflow.cli demo
```

`demo` 自建素材与独立工作区，把整条链路跑一遍并打印逐项判定；**退出码 0 = 全部通过**。

### 跑测试

```powershell
cd D:\Incubator\agentflow
python -m pytest -q                  # 离线套件（配置在 pyproject.toml：testpaths + addopts "-m 'not network'"）
python -m pytest -q -m network       # 联网套件（默认 deselect）
```

**为什么分两套**：日常套件必须离线、确定性、可重复 —— 否则一次上游限流就会把红灯搞成背景噪音，
久而久之没人再看。但有几个真实缺陷（Crossref `select` 字段名错导致全 400、`precise` 模式恒为 0）
**只有真实 HTTP 往返才能发现**，所以它们留在套件里、只是默认不跑。
**"进套件 + 默认 deselect"是两个诉求的唯一交集。**
联网套件里 HTTP 429 判 `skip`（环境状况），**400 一律判失败**（那是真 bug）。

### 每个模块都有独立自检

```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.agent_h              # 每个 agent_*.py 都能这样跑
python -m agentflow.capabilities         # （能力表在导入期自检；import 不进来就是自检失败）
```

`python scripts/release_check.py` 的第 2 项会跑**每一个**模块的自检，并对"**没有自检块**"的模块
报 `unknown`（不是 `pass` —— 把"没检查"读成"检查通过"是本项目反复踩过的坑）。

---

## 2.1 交互台：不带参数运行就是一份菜单（2026-09-28 新增）

```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.cli          # 不带任何参数 ⇒ 进交互台
```

它把常用的五件事列成一份菜单（项目 / 端到端主题 / 数据状态 / 角色工具面 / 离线自检），
逐项问清参数再调对应的子命令 —— 于是"能用"这件事不必依赖记住十几个开关。
菜单里每一步都走**同一条实现**（它只是把回答翻成子命令的 argv），
所以手敲命令与走菜单的结果逐字一致。

呈现规则（都在 `src/agentflow/tty.py` 里，有 14 条判据守着）：

```text
· 管道里自动不带颜色（stdout 不是 tty / 设了 NO_COLOR / TERM=dumb ⇒ 关）；
  想强制关用 `--no-color`，想全 ASCII（老终端、粘进邮件）用 `--plain`。
· 框与表按"显示列数"对齐：中文在等宽终端里占两列，用 len() 补空格会差一截 ——
  判据是"同一个框里每一行的显示宽度必须相等"。
· 编码：先问当前编码能不能表示 ─│✓，不能就退成 +-| 与 [ok]；GBK 控制台下不会崩。
```

---

## 3. 真实网络模式（会联网、会下载）
```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.cli init
python -m agentflow.cli submit --topic "abelian group" --mode topical
python -m agentflow.cli run-a --provider openalex      # 检索 + 下载 PDF
python -m agentflow.cli run-b                          # 抽取概念与关系
python -m agentflow.cli status
python -m agentflow.cli verify --deep                  # 重新打开文献复核引文
python -m agentflow.cli tools --role H                 # 看某个角色的工具面（只读角色看不到写工具）
```

**已实测可用**：OpenAlex 检索、真实 PDF 下载（含 sha256）、Crossref / DOAJ / Europe PMC 客户端。

本机网络说明：`github.com` 系域名被 hosts 劫持到 `127.0.0.1`；镜像可用 `https://ghproxy.net/`、
`https://gh-proxy.com/`。`config.yaml` 的 `download.mirrors` 用于直连失败时的前缀回退。

### 3.1 项目式用法：一个项目一个文件夹 + 本地书架（2026-09-28 新增）

手里已经有整柜 PDF 时，不必先联网检索。`project` 这个动词把三件事绑在一起：
**项目工作区**（一个项目一个文件夹）、**本地书架**（把目录里的 PDF 登记进项目库）、
**冷启动 / 热启动**（判据就是那个项目的文件夹在不在）。

```powershell
cd D:\Incubator\agentflow\src
$env:AGENTFLOW_MODEL_API_KEY = "..."          # 模型 key 只从环境变量来，命令行不许传

python -m agentflow.cli project list           # 现有项目与冷/热次数
python -m agentflow.cli project plan --books D:\books --topic "convex duality"   # 只说明会怎么跑，不写字节

# 冷启动（project1 还不存在 ⇒ 建工作区 + 登记书 + 跑）
python -m agentflow.cli project run --books D:\books --extract --extract-rounds 7 `
    --topic "convex optimization duality and Lagrange multipliers" --budget-usd 0.5 --max-calls 1

# 热启动（同一个项目文件夹已存在 ⇒ 复用工作区；已登记的书按内容 hash 跳过，不重灌）
python -m agentflow.cli project run --name project1 --books D:\books --topic "另一个主题"
```

落点：默认 `D:\Incubator\projects\project<N>`（`--projects-dir` 或环境变量
`AGENTFLOW_PROJECTS_DIR` 可改；缺省名字是 `project1`/`project2`/…，编号不重用）。
每个项目文件夹里是 `data/`（表）、`library/`（书的副本）、`out/run-<n>/`（每次运行的六件产物）、
`project.json`（项目卡：建了什么、每次是冷还是热、跑了什么）。

`--extract` 那一步是模型读书：它按 `llm.LLMExtractor` 的契约抽概念与关系，
**每条关系的引文都要在原文里逐字找到**，找不到的当场剔除并计数
（`relations_dropped` / `drop_reasons`）。所以"模型读了这些书"不是一句话，
而是一组可复核的数字（概念数 / 关系数 / 引文过验 / 被剔除）。

```text
实测（2026-09-28，7 本书 2418 页）：7/7 本抽出概念，174 个概念 / 110 条关系；
主题那一跑 5 条断言全部 verified，回验级别 = fulltext（页码逐条给出）。
两步的花销分开记：抽取那一步走 scope='extract'，主题作答走 scope='reason'；
`--budget-usd` 只管后者（前者由轮数=本数封顶），两个数都在输出与 cost.json 里。
```

边界（不写清楚就会被读成"已经解决了"）：一本书一次只读前 6 万字符
（`LLMExtractor.max_chars` 的缺省；大书的后半本这一跑读不到）；
抽取要的输出上限与"最多 12 条概念 / 12 条关系"的提示词限制都在
`llm.DEFAULT_PROMPT_TEMPLATE` 里，超了会被截断 ⇒ 整次抽取作废。

#### 3.1.1 四层证据各自的强度（**读产物前先看这个**）

这套东西的产物同时印出四类东西，而它们的**可复核程度差得很远**。
2026-09-28 在 7 本书（2418 页）上实测的读数（`draft/28` §126.2）：

| 层 | 有没有回验门 | 实测读数 | 读的时候该怎么用 |
|---|---|---|---|
| 断言（`claims.json`） | 有：每条结论必须带一段逐字引文 | 主题那一跑 5/5 `verified`，级别 `fulltext`，逐条带页码 | 可以按"有原文依据"用 |
| 关系（`relations.json`） | 有：`quote` + `page_range`，回验不过标出来 | 110 条里 **98 条**引文逐字可达；另 12 条引文为真但页码恒偏 5（模型用了书里印的页码），已修提示词 | 按 `quote_verified` 那一列读；`False` 的先看页码 |
| 概念（`concepts.json`） | **没有**：只记"来自哪篇文献" + 模型写的定义 | 174 条里只有 **19%** 的定义能在被引书里找到成句原文（37% 部分重合、44% 找不到） | 把它读成"模型的概念名与措辞"，**不是**"都能在书里指出来" |
| 来源（`evidence.json`） | 有：全文 sha256 与库里的文件逐字节一致 | 7/7 条来源 `fulltext.status=ok` | 可以顺着 `fulltext.path` 自己复核 |

```text
最要紧的一句：**"概念定义没有逐字回验门"不等于"定义是错的"** ——
实测抽查（Yoneda 引理 / path integral / Hadamard product）显示，模型常常是
"书里确实有这个术语，但定义用了自己的措辞"，公式型定义还会因符号不同而字符级比对落空。
所以这一层的正确读法是"模型的措辞"，而不是"抄错了"。
```

---

## 4. 目录结构

```
agentflow/
├── DEVELOPMENT.md            ★ 项目开发规范（六条硬纪律 / DoD / 测试规范 / 禁止模式 / 发布检查 / FC 覆盖矩阵）
├── AGENTS.md                 ★ 禁 AI 区（FC-27）硬约束 —— 只覆盖这一节，与 .noai-paths 逐条一致
├── NOAI-REVIEW-REGISTER.md   ★ FC-27 人工复核登记表（哪一轮改了哪些禁改区文件、谁走查过）
├── README.md                 本文件
├── DESIGN.md / DESIGN-TOOLS.md / DESIGN-INTERACTIONS.md / DESIGN-ROLES.md / DESIGN-CONDUCTOR.md
│                             设计理由（不构成判据）
├── .noai-paths               禁改区清单（**27** 条 glob / **24** 条唯一路径 / 7 类；**台账条目数与欠签不写定值**（每签一个字就变 —— 量法与当次值见 §6.2 那两格，别再往这一行抄数）；前两个数由 `tests/test_release_all.py::test_readme_file_tree_numbers_match_the_repo` 守着）
├── pyproject.toml            包元数据 + pytest 配置（**唯一**一处；不要再加 tests/pytest.ini）
├── docs/
│   ├── INDEX.md              docs/ 的索引与"按角色怎么读"
│   └── ROLE-SPECS.md         ★ 八个角色 + 主控（M）的详细规格（每节 10 条同构结构）
├── scripts/
│   ├── lint_rules.py         linter（**规则区间与条数以 `python scripts/lint_rules.py` 的摘要行为准**；当次 R001–R012、R004/R006 已退休；**有退出码**）
│   ├── noai_gate.py          FC-27 门（0=clean / 1=requires_human / 2=unknown）
│   └── release_check.py      ★ 发布前八项检查（本文件自身在禁改区里）
├── src/agentflow/
│   ├── schema.py             ★ 数据模型 + 行级校验 + 全部跨模块词表（单一来源）
│   ├── store.py              ★ 锁 / 原子写 / 事务 / 事件日志 / ID 分配 / 重建
│   ├── interactions.py       ★ 角色间交互矩阵 + 契约版本 CONTRACT_VERSION
│   ├── verify.py             ★ 全局不变量校验（审计的判据本身）
│   ├── capabilities.py       角色能力表 + 写集 + 允许的召唤边（**导入期自检**）
│   ├── policy.py             策略判定（四类上限、越权边、只读角色写面）
│   ├── conductor.py          M 的实现：召唤 / 台账 / 合并
│   ├── scheduler.py          波次调度器（写集相交 ⇒ 串行）
│   ├── cancellation.py       协作式取消（受控理由见该文件的 `CANCEL_CODES`；**份数按它当次读**、不写定值：观测 2026-09-27（`G3` 复测）⇒ 5 个取值，其中 `cancelled` 是"未分类、不要用"那一档 ⇒ 4 个真实停止来源；无自动重试）
│   ├── contextbudget.py      上下文预算（head/tail/spill）
│   ├── tokenmeter.py         token 记账（**重试按次计费**）+ 开工前守卫
│   ├── agent_a..h.py         八个角色（每个都能 `python -m agentflow.agent_x` 自检）
│   ├── tools/                工具层（**13** 个 `*_tools.py`：table / fs / search / ocr / graph /
│   │                         trace / research / verify / attack / doc / review / conjecture /
│   │                         conductor，外加 `base.py` 与装配点 `__init__.py`）
│   ├── providers.py / fetch.py / extract.py / quoteverify.py / textutil.py / dedup.py
│   ├── llm.py / pipeline.py / demo.py / cli.py
│   ├── sessions.py           按项目存放的会话记录（`<项目根>/sessions/<会话号>.jsonl`；学 harness 的按工作区存放）
│   ├── artifacts.py          产物归属登记（`<工作区根>/ARTIFACTS.jsonl`：谁在哪个路径产出了什么；
│   │                         CLI 动词 `artifacts record|list|verify|owners|unowned|report`）
│   ├── canonical.py          规范 JSON 字节串的**唯一实现**（稿件内容哈希与回执哈希共用的那一份口径）
│   ├── promptkit.py          LLM 接入（一）：提示词装配（有序段 + 变量 + complete + 作用域遮蔽）
│   ├── agent_prompts.py      LLM 接入（二）：A–H 与主控的前置提示词（手写判断 + 现算的工具面/伙伴边）
│   ├── llmseam.py            LLM 接入（三）：统一的模型缝（一次调用一条审计记录 + 三态词表 + 预算守卫）
│   ├── agent_loop.py         LLM 接入（四）：模型驱动的循环（tool / summon / message / final）
├── tests/                    pytest（离线 + 联网两套；见 §2）
├── tools/                    开发期探针脚本（`vocab_census.py` 的 R011 判据本体也在这里）
└── data/ · library/ · demo/  运行时数据 / 下载的文献 / 演示素材
```

> ⚠️ 上面这份树**只列会在意的那些**；完整的顶层模块清单（以及"新增一个模块必须在哪登记"）
> 由 `tests/test_release_all.py::test_agentflow_top_level_modules_match_the_registry` 守着 ——
> 那份登记表是判据，这份树是导读（README 自己的第 7 节第 1 条就写着"与代码冲突时以代码为准"）。

---

## 5. 数据文件速查

| 文件 | 内容 |
|---|---|
| `data/search_requests.json` | 检索请求清单（含 `claimed_by` / `lease_until` 租约字段） |
| `data/literature.json` | 文献表（含下载状态、sha256、`quote_verified`） |
| `data/concepts.json` / `relations.json` | 知识层（`related_concepts` 由关系**派生**，不是输入） |
| `data/research_questions.json` | D 的研究问题（状态机 + 证据链 + `relation_chain`） |
| `data/attack_plans.json` | F 的攻坚计划（子目标 + 预算 + 历史） |
| `data/experiments.json` | E 的实验记录（`method` 是计算类时 `evidence_kind` **不得**为 `proof`，schema 强制） |
| `data/documents.json` / `dependencies.json` | G 的稿件与外部依赖（`external_unavailable` 是一等状态） |
| `data/conjectures.json` | D 的猜想台账（`status` / `form` / 反例与证明实验的外键；依据 `draft/30` §T1） |
| `data/review_findings.json` | H 的审校发现 |
| `data/tasks.json` / `usage_ledger.json` / `eval_results.json` | **运行记录层**（编排台账 / token 记账 / 评测口径） |
| `data/counters.json` | 4 位 ID 分配器 |
| `data/events.jsonl` | **追加式事件日志，唯一事实源**；快照可从它重建 |
| `data/.locks/*.lock` | 跨进程排他锁（`store.LOCK_ORDER` 规定加锁顺序） |

**不在 `data/` 里、但同样属于工作区的三样**（都不是表，因此不进 `schema.TABLES`）：

| 文件 / 目录 | 内容 |
|---|---|
| `DOC-SIGNATURES.jsonl` | 稿件签名台账（append-only JSONL + 链式哈希；证据快照在 `doc-signatures/`） |
| `ARTIFACTS.jsonl` | **产物归属登记**：谁在哪个路径产出了什么（`sha256` + 字节 + 生产者 + 召唤号 + 退出码）；`changed/missing/unreadable` 四态由 `artifacts verify` 现算 |
| `sessions/<会话号>.jsonl` | **按项目存放的会话记录**（一次终态 = 一条叙事行；换项目就是另一段历史，互不污染） |

> 快照被改坏时：`python -m agentflow.cli rebuild`（会先自动备份）。

---

## 6. 发布门（一键：`tools/release_all.py`）

用户点名的"一键发布检查"是 **全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter**。
`scripts/release_check.py` 覆盖其中五项（**没有验收测试**），所以正式入口是编排层：

> ⚠️ **"`release_check` 不含验收测试"是刻意的分工，不是缺项**（`P-11`，(b) 方案）：
> 验收测试由 `release_all` 的**独立 `acceptance` 步**承担，在 `release_check` 里再跑一遍
> 会让同一件事**有两个落点**（FC-03 的反面），而 `release_check` 本身在禁改区（加一项要人审）。
> **八项逐项**（`scripts/release_check.py` 的 `main` 里的 `runners` 元组，按此顺序）：
> `tests` / `selftests` / `tools` / `verify` / `lint` / `noai` / `contract` / `imports`。
> **验收测试不在其中，也不该在其中** —— 复跑：`python tools/release_all.py --only acceptance`。

> ⚠️ **写文件的纪律在这一区里已经收敛成一条（`D8` 落地，`R6-AN-5` 于 2026-09-27 复核）**：
> 三处 `--json` 出口 —— `tools/release_all.py`、`scripts/release_check.py`、
> `scripts/lint_rules.py` —— **都是** `with open(..., "w", encoding="utf-8", newline="")`，
> 没有一处用 `Path.write_text()`。`newline=""` 关掉平台的换行转换：在 Windows 上
> `Path.write_text()` 会把 LF 刷成 CRLF，而产物的 sha256 必须与"盘上那一版"对得上
> （见 `draft/22` §12.15.2 记的那次事故）。
>
> 实测（复跑：跑一次 `--json` 出口再数字节）：两处产物都是 **CR=0**
> （`R6-AN-5` 于 2026-09-27 复核并更正：这一段原写"`release_check` 的产物 CRLF=10"，
> 那是 `c-12` 修完之前的读数）。这里刻意只钉 **CR=0**、不写死行数：
> `lint_rules` 的产物行数随 findings 条数变化，写死就是下一个过期数字。
> `scripts/lint_rules.py` 的 `R012`（`rule_R012_write_text_newline`）在真树上报
> **0 条 warning**，唯一豁免是 `tools/make_demo_dataset.py`（它写的是工作区载荷，
> 逐条登记在 `R012_NEWLINE_EXEMPTIONS`，登记过期会被反向报出来）。
> 所以"整个发布区都禁 `write_text`"这句话今天**已经成立** ——
> 它由 `R012` 这条机器判据守着，不再只是一段散文（`G-42`）。

```powershell
python tools\release_all.py                   # 全跑（约 10~15 分钟）
python tools\release_all.py --json r.json
python tools\release_all.py --only role-specs  # 调试：只跑一项
```

| 步骤 | 是什么 |
|---|---|
| `release-check` | `scripts/release_check.py` 的八项：`tests` / `selftests` / `tools` / `verify` / `lint` / `noai` / `contract` / `imports` |
| `acceptance` | 验收测试 P1–P9（`test/test2/run_acceptance.py`，`AGENTFLOW_TARGET=formal`） |
| `repro` | 论文独立复现（5 个实验 + 7 条负控） |
| `role-specs` | `tools/verify_role_specs.py`：角色规格结构完整性（9 节 × 8 必备子节） |
| `coverage` | `tools/coverage_zero_test.py`：零测试公开函数的**风险分档**清单 |
| `per-file` | 逐文件单跑测试（把顺序依赖/跨文件状态泄漏变成可判定的门） |

**总判定三态**：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`；
退出码 0/1/2。⚠️ **两条刻意的取舍**：`--skip` 掉的步骤记成 `unknown`（**不是 `pass`**，
否则 `--skip acceptance` 就成了"发布门全绿"的捷径）；超时/起不来记成 `unknown`
（Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 无法区分）。

### 6.1 现在的真实判定：**`FAIL`**（不是"基本全绿"）

⚠️ **这一节是"如实"，不是"唱衰"**（`G-28`）。实测（观测 **2026-09-26T04:54:45 → 04:59:39**，
无并发干扰的那一次）：

```powershell
python tools/release_all.py --since 4293989 --only release-check --json D:\Incubator\temp\b6-release-check.json
```

```
[run  ] release-check  全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入（预计 ~300s）
[fail  ] release-check  exit=1 293.0s
         发布检查总判定：FAIL    pass=6 fail=2 unknown=0
[skip ] acceptance / repro / role-specs / coverage / per-file
一键发布检查总判定：FAIL    pass=0 fail=1 unknown=5
```

**两条红里有一条是制度要求，不是代码坏**：

| 红项 | 性质 | 逐字判据 |
|---|---|---|
| `noai` | **制度要求（需人签字）** | `release-check` 那一项的红是"**禁改区命中待 2 名 reviewer 签字**" —— `consistency_exit=0`（两处清单逐条一致）而 `gate_exit=1`（`命中禁改区 ⇒ 需人编写或人逐行走查 + 2 名 reviewer 批准`）。**这一格在人来签字之前永远是红的**，与代码质量无关 |
| `tests` | **真红（可复现，但不是本批引入）** | **这是一条历史读数（原始观测时刻没记 ⇒ 只能当历史；权威读数是本格下面两组带时刻的区间）**：同一次运行 `2 failed, 1948 passed, 1 skipped, 8 deselected, 1 xfailed in 277.76s`；失败两条是 `tests/test_agent_f_step_outcomes.py::test_the_collection_is_actually_consumed_by_the_write_path` 与 `tests/test_core_audit_efgh.py::test_agent_e_resolve_accepts_absolute_inside_and_refuses_outside`。**两条单跑都绿**（`3 passed` / `1 passed`）⇒ 形态是**全量下的顺序依赖/并发态**（`G-27` 的族）。⚠️ **它随并发变动**：同一小时内两次**无并发**全量分别是 **`1925 passed`（观测 04:43:55→04:48:40）** 与 **`1956 passed, 1 skipped`（观测 05:10:23→05:15:43）**，两次退出码都是 0 —— 区间来自别的执行体在持续加测试。所以 `tests` 这一格的读法是"**区间 + 观测时刻 + 逐文件门（`per-file`）**"，不是"读一次就下结论" |

（**`G-28` 的处置就是这一段本身**：三处文档原先把它写成"基本全绿"，
现在写"总判定 `FAIL`，且 `noai` 那一格的红是禁改区命中待 2 名 reviewer 签字（制度要求，不是代码坏）"。）

### 单跑某一项

```powershell
python scripts/release_check.py                     # 八项发布检查
python scripts/release_check.py --changed <文件…>    # 同时判禁改区命中
python scripts/lint_rules.py                        # 规则区间与条数以该命令的摘要行为准（当次 R001–R012；R004/R006 已退休；`--strict` 加严）
python tools/verify_role_specs.py                   # 角色规格结构完整性（0/1/2）
python tools/coverage_zero_test.py                  # 零测试公开函数风险分档（0/1/2）
```

⚠️ **`unknown` 绝不是 `pass`。** 这是本项目的核心教训（`draft/17-…md:675-676` 记录成熟项目的同类问题：
*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*）。
本脚本自身位于 FC-27 禁改区，**发布前必须由人逐行走查 + 2 名 reviewer 批准** —— 这一条写在
[`NOAI-REVIEW-REGISTER.md`](NOAI-REVIEW-REGISTER.md) 里，**不要因为门是绿的而跳过**。
（`tools/release_all.py` 同样在禁改区：它决定"跳过的步骤算不算通过"。）

### 6.2 禁改区的**三个数**必须并列写（`X-5` 的口径）

`draft/25` 的 `D-4.2` **原写**"19 glob / 14 台账条目 / 7 类"——**这三个数今天都过期了**，
而它们过期的方式恰好说明为什么要**并列**写：它们量的**不是同一件事**。

| 数 | 量的是什么 | 实测（观测 **2026-09-27 15:1x（`FIX11` 题 3 落地后复测）**；这个时间戳是这一格的一部分 —— 数字会变，量法不会） | 复跑方式 |
|---|---|---:|---|
| **清单 glob 数** | `.noai-paths` 里的**条目行**数（同一个文件可以登记两次） | 由命令当次产出：**27**（**唯一路径 24**） | `(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count` |
| **唯一路径数** | 上述 glob 去重 | 由命令当次产出：**24** | 同上再加 `ForEach-Object { ($_.Line -split '\s+')[0] } \| Select-Object -Unique` |
| **台账条目数** | `.noai-approvals.json` 里**有 hash 记录的路径**数（= 需要签字的行数） | **不写定值**（每签一个字就变）：当次由右列命令产出 | `python -c "import json;print(len(json.load(open('.noai-approvals.json', encoding='utf-8'))['entries']))"` |
| **禁改区类别数** | `.noai-paths` 的 `[category: …]` 分组数 | **7** | `Select-String -Path .noai-paths -Pattern '^\[category:'` |
| （派生）**欠签** | 台账条目 × 2 名 reviewer | **不写定值**（每签一个字就变）：由右列命令当次产出 `entries × 2 − Σ len(reviewers)`；**0 签的条目也随签字而变**（当次以 `python scripts/noai_gate.py --check-approvals` 的输出为准，这里不点名具体文件） | `python -c "import json;d=json.load(open('.noai-approvals.json',encoding='utf-8'));print(len(d['entries'])*2-sum(len(e['reviewers']) for e in d['entries']))"` |

**差集 = 「清单唯一路径数」−「台账条目数」**（两个数都见上表；**本行不写定值** —— 差集随人跑 `--baseline` 与新增登记而变，当次以 `python scripts/noai_gate.py --check-approvals` 报出的 `unregistered` 条目为准）逐条说清（`X-5` 要求"差集是哪几条"）：

| 不在台账里的路径 | 为什么它没有台账条目 |
|---|---|
| `src/agentflow/release_check.py` | **盘上不存在**（`Test-Path` ⇒ `False`）。它是**刻意先登记路径**的（"一旦有人在这里新建它，会自动落入清单而不是绕过门"）⇒ 没有文件就没有 hash 可言。判据面仍然有效：`--paths src/agentflow/release_check.py` ⇒ `unregistered`（`requires_human`, exit 1）。**当次它是唯一的一条**（差集是派生量：以 `python scripts/noai_gate.py --check-approvals` 的输出为准）：`.noai-approvals.json`、`scripts/noai_gate.py`、`scripts/lint_rules.py` 的台账条目都已由人跑 `--baseline` 补登记（早前版本把它们算作差集，那已过期） |

⚠️ **`ledger_self_approval` 这一档仍然成立**（只是它不再表现为"差集"）：`.noai-approvals.json` **在**清单里、也**在**判定输出里，但它**永远**是 `unapproved`，与 hash 是否一致、reviewers 有几个无关 —— 台账不能批准自己。

**另：清单两处本体的台账记录今天已经是"hash 一致 + 各 2 名 reviewer"**（观测 2026-09-27（`G3` 复测）：
`.noai-paths` 与 `AGENTS.md` 的台账 `sha256` 与盘上逐字节相同，各 2 名 reviewer）。
仍然 `unapproved` 的条目**随签字而变**：唯一**永远** 0 reviewer 的是**台账自身**（`.noai-approvals.json`
的台账 `sha256` 与盘上永远对不上 —— 它自己也在被写 —— 且它**不能自签**，见上一段）。
其余哪几条 0 签、哪几条 `stale`，一律以 `python scripts/noai_gate.py --check-approvals` 当次输出为准；
**本段不点名、不写定值**（旧版这里点名过 `pyproject.toml` 是 0 reviewer，它已由人补签 2/2 ⇒ 那个说法已过期）。
⚠️ **"哪些路径 stale / 谁是零 reviewer"随人签字而变 ⇒ 本段不写定值**，复跑口径：
读 `.noai-approvals.json` 的 `entries`，逐条把 `sha256` 与盘上 `hashlib.sha256(文件字节)` 比对
（**不经过门的任何写路径**）。
**门报得对，不是坏**；收敛它要重跑 `--baseline`，而那会改禁改区台账 ⇒ **必须由人做**（判据五）。

**其余两条曾被猜为"差集"的其实是台账条目**（这条更正很重要，`X-5` 原文的候选清单猜错了）：
`.noai-paths` 与 `AGENTS.md` **各自都有自己的台账条目**（`--baseline` 已登记），
所以"清单两处本体没有批准记录"这个猜测**不成立**。
**「清单条目行数 − 唯一路径数」= 同一文件登记两次的条数**（**派生量，不写定值**：
两个数都见上表）：`src/agentflow/dedup.py`、`src/agentflow/providers.py`
各登记两次；`src/agentflow/schema.py` 登记两次（`schema-migration` + `eval-criteria`）。

**判据**：本表的三个数与 `python scripts/noai_gate.py --check-consistency`（退出码 0）、
`.noai-paths`、`.noai-approvals.json` 的实测**逐条一致**。⚠️ **`--check-approvals --paths` 的入参是
「命中路径数」而不是「清单 glob 数」**——传清单的条目数进去，它报的是**台账条目数**，
**而那不是"清单有那么多条"**。**这两个数都不写定值**（每签一个字就变）。
把两个数读成一个数，就是 `X-5` 要防的那类口径混用。

---

## 7. 已知限制（**务必先读**）

1. **`README.md` 不是判据。** 与代码冲突时以代码为准；判据入口是 `DEVELOPMENT.md` 与 `docs/ROLE-SPECS.md`。
2. **抽取质量取决于抽取器。** 离线 `RuleExtractor` 只认定义句式，**真实论文上产出的概念名大多是垃圾**；
   它是**可测试的基线**，不是可用的抽取器。
   > ⚠️ **`R-56`（2026-09-29）之后它还是"框架的回退"，而 `AgentB` 见到它会直接拒抽**：
   > 无 LLM 时不会把它的产出灌进概念图（实测症状：`ANU` / `cingled property` / `Ultimately this`
   > 这类碎片进图，而 `quote_verified=True` 让它们看起来有证据）。跳过时行上留
   > `last_mine_error="no_llm_extractor"`，`run_once()` 的返回值里有 `skipped_no_extractor` 计数。
   > **要显式选离线基线**（演示 / 单测 / 自检）请用 `llm.OfflineFixtureExtractor`
   > ——与 `RuleExtractor` 同实现，只是声明自己**不是**回退；`cli` / `pipeline` / `host` 的默认装配
   > 仍然是 `RuleExtractor`（也就是：默认**不抽**）。
   > 口径是：**允许人明确选一条已知较弱的路径，不允许框架在被问到时假装那条路径没有被选过。**
   > ⚠️ **最重要的一条认知**：离线 demo 全绿 + 千条测试全绿 + 真实数据 `verify --deep` 零错误零警告，
   > **三个绿灯叠加仍然不能证明系统有用**，只能证明它**自洽**。不变量检查的是"结构自洽"，
   > 它不检查也无法检查"这个概念名是不是一个概念"。
3. **"下载成功"不等于"拿到的是论文"**：实测碰到以 `.pdf` 结尾的 URL 返回 12.4 MB HTML。
   下载器标 `content_type_mismatch`，A 降级为 `content_mismatch` 并**保留字节作为证据**，
   B 跳过并记 `last_mine_error`。**更广义的内容校验（是不是真 PDF、是不是目标论文）仍未做。**
4. **`suspect` 状态没有复核流程**（关系被标 `suspect` 后只是留在表里等人看）。
5. **4 位 ID 上限 10000 条/类**。用满会 fail-closed 报错，不会静默升位宽。
6. **A/B/D/E/F 是轮询式**，没有消息队列；主控的调度是**波次级**的，不是抢占式。
7. **扫描版 PDF（无文本层）**：`quote_verified` 会是 `null` 而非 `true`，`verify` 把它与"校验失败"
   区分开。这类文献需要 OCR 才能真正校验。
8. **`D:\Incubator\agentflow` 自己不是 git 仓库根**（`.git` 在**上一级** `D:\Incubator`）⇒
   `noai_gate.py --git` **不是** `unknown(2)`：实测 `--git` 与 `--git --since 4293989`
   都返回 **1（requires_human）**并逐条列出命中路径（`D-12` 更正；旧版这里写"不是 git 仓库
   ⇒ 恒为 unknown(2)"，两处都不成立）。漂移检测仍以 `.noai-approvals.json` 的 hash 台账为准
   （见 `NOAI-REVIEW-REGISTER.md`）；**不给 `--since` 时改动集为空会判 unknown(2)** ——
   那一条是真的，理由见 `AGENTS.md` 末节。
9. **本项目大量代码由 AI 编写，尚未经人逐行走查。** 禁改区台账里的**每一条**尤其如此
   （**份数不写定值**：口径是 `.noai-approvals.json` 的 `entries` 长度 vs `.noai-paths` 的唯一路径数 ——
   **两个口径不许互换**；两个数都由 §6.2 那两条命令当次产出）——
   当前值以本文 §6.2 与 `DEVELOPMENT.md` §1.5 的 `LIVE-READINGS` 为准；
   `NOAI-REVIEW-REGISTER.md` §0 是**历史档案**（它自己 §0/§7 逐字声明"当前值以那两处为准"），
   不当当前数字的真源（2026-09-28 集中审查 `R6-F4`：全仓 16 个引用里只有这一处用错）。

---

## 8. 环境

- Python 3.11+（实测 3.11.4）；依赖见 `pyproject.toml`（`filelock`、`PyYAML`、`PyPDF2`、
  `pdfminer.six`、`PyMuPDF`、`pytest`）。OCR 需要额外环境（`easyocr` + `torch`，装在 `.venv-ocr`）。
- 控制台是 GBK 时请设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`，否则中文输出会乱码。
- PowerShell 下**不要**在 `python -c` 里写嵌套引号（会炸）—— 写脚本文件再跑。
