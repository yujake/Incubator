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
| **A** | 文献检索 + 下载 + 登记 | `network`（**唯一联网角色**） | B |
| **B** | 抽取概念与关系（含**引文逐字回验**） | `write_local` | C |
| **C** | **只读**关系分析（最热/路径/冷门/缺口/矛盾/结构重复） | `read`（工具面 45 个只读工具，**零写工具**） | **无**（连"请求"都不直接发） |
| **D** | 研究循环：把 C 的报告变成研究问题并回答 | `write_local` | A B C E F |
| **E** | 数值实验 + 形式化验证（**计算类拿不到 `proof`**） | `write_local` | B D |
| **F** | 多轮难题攻坚（预算不足即拒绝立项） | `write_local` | A B C D E |
| **G** | 撰写：断言 / 依赖 / 稿件 / 修订 | `write_local` | D E F |
| **H** | **审校**：G1–G15 门、发现落库、状态更新 | `write_local`（**只有一个被钉死的写面**） | **只能召唤 G** |

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
├── .noai-paths               禁改区清单（**18** 条 glob、7 类）
├── pyproject.toml            包元数据 + pytest 配置（**唯一**一处；不要再加 tests/pytest.ini）
├── docs/
│   ├── INDEX.md              docs/ 的索引与"按角色怎么读"
│   └── ROLE-SPECS.md         ★ 八个角色 + 主控（M）的详细规格（每节 10 条同构结构）
├── scripts/
│   ├── lint_rules.py         linter（R001–R009；**有退出码**）
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
│   ├── cancellation.py       协作式取消（4 条规则，无自动重试）
│   ├── contextbudget.py      上下文预算（head/tail/spill）
│   ├── tokenmeter.py         token 记账（**重试按次计费**）+ 开工前守卫
│   ├── agent_a..h.py         八个角色（每个都能 `python -m agentflow.agent_x` 自检）
│   ├── tools/                工具层（base / doc / review / graph / table / fs / search / ocr /
│   │                         research / attack / trace / verify 共 12 个模块）
│   ├── providers.py / fetch.py / extract.py / quoteverify.py / textutil.py / dedup.py
│   ├── llm.py / pipeline.py / demo.py / cli.py
├── tests/                    pytest（离线 + 联网两套；见 §2）
├── tools/                    开发期探针脚本
└── data/ · library/ · demo/  运行时数据 / 下载的文献 / 演示素材
```

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
| `data/review_findings.json` | H 的审校发现 |
| `data/tasks.json` / `usage_ledger.json` / `eval_results.json` | **运行记录层**（编排台账 / token 记账 / 评测口径） |
| `data/counters.json` | 4 位 ID 分配器 |
| `data/events.jsonl` | **追加式事件日志，唯一事实源**；快照可从它重建 |
| `data/.locks/*.lock` | 跨进程排他锁（`store.LOCK_ORDER` 规定加锁顺序） |

> 快照被改坏时：`python -m agentflow.cli rebuild`（会先自动备份）。

---

## 6. 发布门（一键：`tools/release_all.py`）

用户点名的"一键发布检查"是 **全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter**。
`scripts/release_check.py` 覆盖其中五项（**没有验收测试**），所以正式入口是编排层：

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

**总判定三态**：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`；
退出码 0/1/2。⚠️ **两条刻意的取舍**：`--skip` 掉的步骤记成 `unknown`（**不是 `pass`**，
否则 `--skip acceptance` 就成了"发布门全绿"的捷径）；超时/起不来记成 `unknown`
（Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 无法区分）。

### 单跑某一项

```powershell
python scripts/release_check.py                     # 八项发布检查
python scripts/release_check.py --changed <文件…>    # 同时判禁改区命中
python scripts/lint_rules.py                        # R001–R009（`--strict` 加严）
python tools/verify_role_specs.py                   # 角色规格结构完整性（0/1/2）
python tools/coverage_zero_test.py                  # 零测试公开函数风险分档（0/1/2）
```

⚠️ **`unknown` 绝不是 `pass`。** 这是本项目的核心教训（`draft/17-…md:675-676` 记录成熟项目的同类问题：
*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*）。
本脚本自身位于 FC-27 禁改区，**发布前必须由人逐行走查 + 2 名 reviewer 批准** —— 这一条写在
[`NOAI-REVIEW-REGISTER.md`](NOAI-REVIEW-REGISTER.md) 里，**不要因为门是绿的而跳过**。
（`tools/release_all.py` 同样在禁改区：它决定"跳过的步骤算不算通过"。）

---

## 7. 已知限制（**务必先读**）

1. **`README.md` 不是判据。** 与代码冲突时以代码为准；判据入口是 `DEVELOPMENT.md` 与 `docs/ROLE-SPECS.md`。
2. **抽取质量取决于抽取器。** 离线 `RuleExtractor` 只认定义句式，**真实论文上产出的概念名大多是垃圾**；
   它是**可测试的基线**，不是可用的抽取器。
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
8. **`D:\Incubator\agentflow` 不是 git 仓库** ⇒ `noai_gate.py --git` **恒为 `unknown(2)`**。
   禁改区的漂移检测改用 `.noai-approvals.json` 的 hash 台账（见 `NOAI-REVIEW-REGISTER.md`）。
9. **本项目大量代码由 AI 编写，尚未经人逐行走查。** 禁改区那 13 个文件尤其如此 ——
   `NOAI-REVIEW-REGISTER.md` §0 记着确切的数字，**读它比读本节有用**。

---

## 8. 环境

- Python 3.11+（实测 3.11.4）；依赖见 `pyproject.toml`（`filelock`、`PyYAML`、`PyPDF2`、
  `pdfminer.six`、`PyMuPDF`、`pytest`）。OCR 需要额外环境（`easyocr` + `torch`，装在 `.venv-ocr`）。
- 控制台是 GBK 时请设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`，否则中文输出会乱码。
- PowerShell 下**不要**在 `python -c` 里写嵌套引号（会炸）—— 写脚本文件再跑。
