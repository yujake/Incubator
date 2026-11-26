# docs/INDEX.md —— 权威地图（哪份算数、哪份只作依据）

> 这份文件的职责只有一个：**告诉读文档的人，哪一份是「当前规格」、哪一份是「历史证据」、
> 哪一份只是「设计理由」**。三者混着读，是这套仓库最容易犯的错。
>
> 判据优先级（从高到低）：**代码与判据 > 本索引 > 各份规格 > 设计理由 > 历史提案**。
> 任何文档与代码冲突，以代码为准；本索引里的读数，以 §5 的复跑命令为准。

## 1. 入口（先读这几份）

> 三份入口的分工写死在这里：**本目录的 [`README.md`](README.md) 管顺序**（我是谁、先读哪份、
> 60 秒路线），**本文管权威性**（哪份算数 / 哪份是历史），**仓库根 README 管入门**（是什么、
> 怎么装、怎么跑）。三份互不替代，也不许任何一份自封"全部真相"。

| 文件 | 管什么 | 权威性 |
|---|---|---|
| [`README.md`](README.md)（本目录） | **交付集合的入口**：60 秒路线（新手 / 我要跑 / 我要改 / 我要查设计 / 我要看限制 / 我要查术语）、目录树（每份一句）、读前三条纪律 —— **2026-11-22 DOCS-GAPS 新增** | 入口（管顺序） |
| [`../../README.md`](../../README.md)（仓库根） | 系统是什么、怎么装、怎么跑、有哪些命令与开关 | **当前**——数字都从代码现读 |
| [`../DEVELOPMENT.md`](../DEVELOPMENT.md) | **入口**：职责 + 两份指针 + 改代码前先读哪三节（行数不在这里写死，现算见 §5「文档行数」） | 入口 |
| [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md) | **开发规范本体**（每节 `## [规范]`）：改哪里、怎么验、判据在哪 | **当前规格** |
| [`draft/archive-docs/DEVELOPMENT-APPENDIX.md`](../../draft/archive-docs/DEVELOPMENT-APPENDIX.md) | 历史沿革（每节 `[附录·历史]`，数字为当时读数）—— **2026-11-22 DOCS-CLEANUP 归档**：它自述"每一个数字都是当时读数、本轮一律未复跑"，描述的不是今天的行为，故移出交付面（见 §3.2） | 归档件·不构成判据 |
| [`../AGENTS.md`](../AGENTS.md) | FC-27 禁改区三条硬约束与退出码语义 | **当前规格** |

## 2. 当前规格（与代码同步维护）

| 文件 | 管什么 |
|---|---|
| [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) | **系统总览（新读者从这进）**：架构八层 / 十一角色职责与协作 / 16 张在用表（另有 1 张退役表 `eval_results`，见 `schema.RETIRED_TABLES`）与文件契约 / 一次运行的完整生命周期 / 收工门八格四态与退出码 0–1–2 / 证据与签名链 / 判据族与"tests 不随仓库交付"的本机门边界 / 当前状态与已知边界；每个数字带现算命令（2026-11-21 新增） |
| [`ROLE-SPECS.md`](ROLE-SPECS.md) | 十一个角色（A–H V L + 主控 M）的职责面 / 动作表 / 边 / 写集 —— **只放规格（判据）**。**何时读它**：要判"这一改合规不合规"、要引"哪一句才是判据"时读它（判据面）；只想弄懂"这个角色是干什么的"，先读 [`ROLE-A.md`](ROLE-A.md) 那一族 |
| [`DESIGN-BASELINE.md`](DESIGN-BASELINE.md) | **现行设计基线**：51 条（B01–B51）＋六层权威序（§1）＋判级规则（甲乙丙丁）；判据 `tests/test_design_baseline_is_present.py`（文件在 / 51 条在 / 顶部指针 / INDEX 登记） |
| [`ROLE-GUIDE.md`](ROLE-GUIDE.md) | **角色指南（生成物）**：十个角色 + 主控逐一介绍 —— 角色设定 / 具体职责 / 协作面 / 工具面 / 主要读写（由 `tools/write_system_docs.py` 现算，判据 `tests/test_system_docs_are_generated.py`）。**何时读它**：想**通读**一个角色（设定 / 职责 / 工具面按人话摆在一起）时读它；三份讲工具面的文档里**先看这份**，要引判据再回 `ROLE-SPECS.md`、要当次逐格读数再翻 `ROLE-SPECS-APPENDIX.md` |
| [`SYSTEM-COMPONENTS.md`](SYSTEM-COMPONENTS.md) | **组件总览（生成物）**：协作系统各主要组件逐一介绍 —— 功能 / 实现细节 / 落点 / 守着它的判据 |
| [`ROLE-SPECS-APPENDIX.md`](ROLE-SPECS-APPENDIX.md) | `ROLE-SPECS.md` 的**实测附录**：工具面明细 / 自检实测 / R0.1–R0.3 / M.4.2–M.4.3 / S1–S3（**读数带日期、不构成判据**）。**何时读它**：要**某一当次那种"逐格实测"读数**（某个角色拿了哪几件工具、自检当时怎么跑）时读它；它的数值槽由 `tools/verify_role_specs.py --write` 现算重写，判据 `tests/test_role_specs_appendix_is_live.py` 逐格对拍 |
| [`LEAN-MODES.md`](LEAN-MODES.md) | 有 Lean / 无 Lean 两模式的完整矩阵：开关、动作可用面、证据上限、收工门各格 |
| [`TWO-AXES-GRADE-AND-KIND.md`](TWO-AXES-GRADE-AND-KIND.md) | **等级（`GRADES`）与档位（`EVIDENCE_KINDS`）是两个轴**：五元位 ⇒ 等级（32 组现算）、五元位 ⇒ 档位（逐格标"不由五元位决定"并给出三处真落点）、等级 ⇄ 档位的现场横表（真机 77 工作区 / 3627 行 + 夹具）与两组反例；术语校准表（"证据等级"→"证据档位"）逐处登记。表由 `tests/test_two_axes_grade_and_kind.py` 逐格比对（改错一格即红） |
| [`READING-MAP.md`](READING-MAP.md) | 大文件的行数与「该读哪一段」的索引 |
| [`PROMPT-HISTORY.md`](PROMPT-HISTORY.md) | **提示词版本账**：每抬一格 `agent_prompts.PROMPT_VERSION` 在这里追加一段（2026-11-20 从 `agent_prompts.py` 逐字节搬出；**当前行数不写死**，现算见 §5「文档行数」—— 它随每次抬版本增长）。抬版本时往本文件末尾写；判据 `tests/test_the_prompt_history_is_the_only_ledger.py` 钉两件事 —— 源码里一段不留、本文件末节标题 == `PROMPT_VERSION` |
| [`PRESET-RETIREMENT.md`](PRESET-RETIREMENT.md) | **预设（presets）退役记录 + 两根轴**：写死的提示词正文归声明面（`specs/<role>.py`）而运行时值归 settings / config.yaml；为什么曾经有一层预设（`draft/103` §4.1b 的"写死的块由哪段文件给"）、为什么 2026-11-22 退役（随包预设只有 A 一份、机制没有第二个用户、那套东西的唯一效果是 A 的正文与同族 policy 分家）、正文现在住 `specs/a.py::SEARCH_STYLE` 并由 `agent_prompts` 注册成 `A_SEARCH_STYLE` 段（号 2000 不变）—— 十一格渲染逐字节不变，判据 `tests/test_presets_retired.py` |
| ~~`USER-GUIDE.md`~~ → 已归档 | **2026-11-22 DOCS-CLEANUP 归档到 `draft/archive-docs/USER-GUIDE.md`**（见 §3.2）：它的网页清单一栏停在"九页（导航八条）"，而现盘导航是 **9 条**（多一页「错误动作」`/errors`）+ `/run/<sid>` = **十页**；CLI 侧已被 [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md)（2026-11-21，逐条实跑）取代，网页侧由 [`USER-GUIDE-WEB.md`](USER-GUIDE-WEB.md)（2026-11-22，逐请求实跑）承担 |
| [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md) | **CLI 侧用户说明书**（2026-11-21 新增）：装 / `init` / 起一趟（`start` 与 `--dry-run`、`--seed-literature`）/ 看进度（`status`·`stats gates`·`closing`·`status-report`）/ 插话·答问·叫停 / 续跑与切换 / 常见错误与三态读法 —— 每条命令都实跑过（附录 A 给"命令 → 退出码 → 关键输出"清单）；网页侧不在这里，看下一行 `USER-GUIDE-WEB.md` |
| [`USER-GUIDE-WEB.md`](USER-GUIDE-WEB.md) | **Web 侧用户说明书**（2026-11-22 新增，同日 GUIDE-WEB-REFRESH 复核）：起服务两档（只读 / `--allow-writes`）· 端口与 `--root` 陷阱 · 十页各读什么（含"Compliance 不是独立路由"）· **十一条 POST 写端点**的实跑请求与回执（含 2026-11-21 落地的 `/api/ack` 收口 · `/api/void` 作废 · `/api/stop/clear` 撤销叫停，写端点条数以 `webui/writes.py:ROUTES` 现算为准）· CSRF 怎么拿（页面 / 脚本）· 只读档能做什么 · `GET /api/actions` 网页操作历史的用法 · 常见 403/400/409/404 的 `kind` 与修法 · 安全注意 · 这一版还没有的功能（页面切工作区 / `/compliance` 独立页）—— 每条响应都是临时实例上真发出来的（附录 A 给"URL/方法 → 状态码 → 关键字段"清单，A.7 是三条新端点的复核，附录 B 给复跑脚本与"说明书端点 ⊆ ROUTES"自检） |
| [`CLI-CONTRACT.md`](CLI-CONTRACT.md) | `inspect` 那一组 `--json` 的机器可读契约：外层四格 / 每条命令的 `data` 字段 / 三态语义 |
| [`USER-TEST.md`](USER-TEST.md) | 用户侧验收剧本 |
| [`FORMAL-TOOLCHAIN.md`](FORMAL-TOOLCHAIN.md) | 证明检查器桥接层的接法与失败分类 |
| ~~`FC27-SIGNING-GUIDE-2026-10-27.md`~~ → 已归档 | **2026-11-22 DOCS-CLEANUP 归档到 `draft/archive-docs/`**（见 §3.2）：它是 2026-10-27 **第二批**这一批的签字操作单，§1「现状」自述"2026-10-27 22:xx 的读数：清单条目 46 条唯一路径"，而现盘 `.noai-paths` 是 **71** 条条目 / **68** 条唯一路径（`python scripts/noai_gate.py --check-consistency` 退出码 0；这里的 45 原是按 `^\S+\.(py|json|toml|md)` 数的另一口径，不算唯一路径数）。现行的门语义读 [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md)，逐条硬约束读 `../AGENTS.md`，批次签字怎么做以 `scripts/noai_batch_sign.py --help` 为准 |
| [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) | 禁改区治理流程：谁能批、批几个、台账怎么写 |
| [`KNOWN-UNWIRED.md`](KNOWN-UNWIRED.md) | 已知未接线：`src/agentflow/tools/` 下哪个 `*_tools.py` 没被 `tools/__init__.py` 的 `_MODULES` 装配（现读清单——改了装配就要回来改它） |
| [`GUARDS.md`](GUARDS.md) | **三件只读护栏的最小说明**（2026-11-21 新增）：`wellformed/`（产物畸形 16 类统一判据）、`sysguard.py` + `sysresidue.py`（系统自动写点的 `refused/derived/unchecked` 读数）、`seedinject.py`（种子投放，只放文件不入库）—— 各自给代码落点、读数入口与判据 |
| [`WORKSPACE-LAYOUT.md`](WORKSPACE-LAYOUT.md) | **工作区目录与文件名的三级规范**（2026-11-25 新增，DIR-SPEC 路）：A 系统固定 / B 系统生成名 / C 有限自由，逐条给模式与层级上限；执行体是 `wellformed/naming.py` 的 `workspace_layout` 一类 |

### 2.1 角色 / 协作链 / 数据台账（2026-11-22 新增，ROLEDOC / SYSCOMP 路）

| 文件 | 管什么 |
|---|---|
| [`ROLE-A.md`](ROLE-A.md) | 检索（A）：职责 / 输入输出 / 动作面 / 边界 / 协作面 |
| [`ROLE-B.md`](ROLE-B.md) | 整理 / 手稿（B） |
| [`ROLE-C.md`](ROLE-C.md) | 分析 / 审查（C） |
| [`ROLE-D.md`](ROLE-D.md) | 研究侧主导（证明 / 推演） |
| [`ROLE-E.md`](ROLE-E.md) | 数值实验与反例 |
| [`ROLE-F.md`](ROLE-F.md) | 攻坚：把难题拆成可判步骤 |
| [`ROLE-G.md`](ROLE-G.md) | 手稿 / 写作 |
| [`ROLE-H.md`](ROLE-H.md) | 审读 |
| [`ROLE-L.md`](ROLE-L.md) | Lean 形式化者（默认关，唯一入口是 B） |
| [`ROLE-M.md`](ROLE-M.md) | 主控调度（唯一"派活的人"） |
| [`ROLE-V.md`](ROLE-V.md) | 验证 / 签发 |
| [`CHAIN-A-B-C.md`](CHAIN-A-B-C.md) | 文献 → 证据 → 命题 → 分析报告 |
| [`CHAIN-D-E-F.md`](CHAIN-D-E-F.md) | 问题 → 猜想 → 证明/实验 → 登记 → 送审 |
| [`CHAIN-G-H-V.md`](CHAIN-G-H-V.md) | 手稿 → 审读 → 送审 → 判 → 交付说明 |
| [`CHAIN-ALL-ROLES.md`](CHAIN-ALL-ROLES.md) | 十一角色协作总图 / 边表 / 典型流水 / 三条硬边界 |
| [`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) | 数据台账与存储：16 张在用表（另有 1 张退役表 `eval_results`）/ 文件落点 / 契约 / 原子写 / ID / 锁序 / 事件重放 |
| [`PART-EVIDENCE-AND-SIGNS.md`](PART-EVIDENCE-AND-SIGNS.md) | 证据与签名链：一条断言怎样走到 proof 级 |
| [`PART-ARTIFACTS-LEDGER.md`](PART-ARTIFACTS-LEDGER.md) | 产物台账（`ARTIFACTS.jsonl`） |

### 2.2 交付集合的入口与查证（2026-11-22 DOCS-GAPS 新增）

> 这一组补的是 DOCS-CLEANUP §5-B 报的四条缺口（安装入口 / 限制清单 / 术语表 / 抬版本清单）。
> 它们**不重写已有文档**，只做"最短路径"与"一次看全"；权威内容仍归各自点名的那几份。

| 文件 | 管什么 | 谁在什么时候读它 |
|---|---|---|
| [`INSTALL-AND-FIRST-RUN.md`](INSTALL-AND-FIRST-RUN.md) | **从 clone 到第一次 `--dry-run` 的最短路径**：六步、零模型零花费，每条命令都真跑过（输出来自 2026-11-22 21:24–21:33 的本机实跑）。装法 / 快速开始的英文权威版在仓库根 README，逐条详解在 `USER-GUIDE-CLI.md` §0–§7 —— 这份只是"第一次该按什么顺序做" | **第一次上手的人**（拿到 clone、还没跑过任何命令）；以及**要给人一条可复算的最小路径**的人 |
| [`LIMITS-AND-NON-GOALS.md`](LIMITS-AND-NON-GOALS.md) | **已知限制 ＋ 不做清单 ＋ 可证伪条件**：限制条目带读法 / 出处（素材：`draft/197` §十八「不做清单」、`draft/198` §四·§六、历史工作区不兼容、`tests/` 不交付、demo 线退役、reprocess 未启用）；不做清单逐条给一句理由 | **报缺陷之前**先读（多数"看起来坏"的东西已登记）；以及**要判断"这条限制是有意还是漏了"**的人 |
| [`GLOSSARY.md`](GLOSSARY.md) | **术语表**：工作区 / 角色 / 主控 / 名册 / 召唤 / 边 / 动作 / 写集 / 板项 / 交接 / 阶段 / 收编 / 契约 / 台账 / 三态 / 四态 / 收工门八格 / 门（三种）/ 禁改区 / 发签 / 等级 / 档位 / 引文回验 / 形式化 / 教法 / 提示词版本 / 十一格 / golden —— 每条一句话 ＋ 权威落点，末尾附同义词与旧名 | **读任何一份文档卡在词上**时；以及**写新文档要给词下定义**的人（先查这里有没有现成定义） |
| [`TEACHING-VERSION-BUMP.md`](TEACHING-VERSION-BUMP.md) | **抬提示词版本的同步清单**：改教法 / 工具面时必须同时改的 **7 处**（`PROMPT_VERSION` · 十一格 · 两份 golden · 账末 · volatile 账本 · 两份生成物 · warm 读数），每处给命令与"缺了谁红"，另附可复制的执行顺序与两条收尾判据 | **改到模型读得到的文本**（`specs/*.py` / 工具声明 / 技能索引行）的人，动手之前；以及**判据红在"十一格 / golden / 账末"**时先来这里对表 |

## 3. 历史证据（**不构成判据**，但被代码注释与其它文档大量引用，故保留）

这些是「当时的提案 / 当时的停摆记录」。它们解释**为什么现在是这样**，
但不描述**现在是什么**。改动它们等于改历史；引用时请写成「历史依据」。

> 2026-11-22 ARCHIVE2：原先列在这里的 `../NOAI-REVIEW-REGISTER.md`（FC-27 逐条审计台账）
> 与五份根级 `DESIGN*.md`（设计理由）已按业主指令退役到 `draft/archive-*`（逐条见 §3.2）。
> 本目录之外、产品根之下今天只剩入口文档（`DEVELOPMENT.md` / `AGENTS.md` / `README-PRODUCT.md`）。

- `USER-END-DSH-STYLE.md` —— Web 端样式的来源与三条纪律（DSH 令牌的 MIT 出处登记）

- `PAPER-WRITING-PLAYBOOK.md` —— 2026-11-26 彩排留下的**经验记录**（成文流水线五步 / 分章的
  自由度与硬边界 / 机械拼装真踩的三层坑 / 对齐四查 / 已知未做）。**不是规范条文**：判据在代码与
  `tests/` 里，这份只记"彩排里真踩了什么、真读数是多少"；与它同步的产品侧实现见
  `papermapping.order_reading`（编号按路径 + 依赖 DAG 拓扑序）。

> 2026-11-22 DOCS-CLEANUP：原先列在这里的 `PROPOSALS.md`（提案/缺口登记册，自述"条目正文记的是
> 登记当时的状态，不是当前状态"）与 `ROLE-SPECS-DRAFT-N-O-Q.md`（N/O/Q 三角色的草案，而现盘
> `schema.ROLES` = A–H + V + L，没有这三个角色）已归档到 `draft/archive-docs/`（逐条见 §3.2）。

> 2026-11-22 ARCHIVE：原先列在这里的四份**提案/草案**（`PROPOSAL-side-effect-axes.md`、
> `SCHEMA-MIGRATION-PROPOSAL-claims.md`、`SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`、
> `TOOLBOX-DRAFT-roles.md`）已退役到 `draft/`（逐条见 §3.2）。

### 3.1 历史送审页 / 停摆记录 / 复算证据：谁被谁取代

**只在本索引里标注，不改那些文档的正文**（改它们等于改历史）。判据：`tests/test_docs_index_covers_every_doc.py`
要求盘上每一份 `docs/*.md` 都在本索引里出现一次，或登记进 §6「不入册」。

| 文件 | 日期 | 已被谁取代 / 备注 |
|---|---|---|
| `FC27-PENDING-LEAN.md` | 2026-10-17 | 已被 2026-10-19 与 2026-10-21 那两批送审页取代；**已退役 → `draft/archive-FC27-PENDING-LEAN.md`**（2026-11-22 ARCHIVE 执行） |
| `FC27-REVIEW-2026-10-19.md` | 2026-10-19 | 已被 `FC27-PENDING-2026-10-21.md` 取代；**已退役 → `draft/archive-FC27-REVIEW-2026-10-19.md`**（2026-11-22 ARCHIVE 执行） |
| `FC27-PENDING-2026-10-21.md` | 2026-10-21 | 与 `FC27-PENDING-CLEANING-2026-10-21.md` 同日**并列**（前者功能改动、后者只碰注释与 docstring，它自己在开头点名"上一批见…"）；这两批之后没有更晚的送审页。**2026-11-22 DOCS-CLEANUP 归档 → `draft/archive-docs/FC27-PENDING-2026-10-21.md`**：它是一次性送审记录（正文一字未改），`tests/test_deprecated_forms_are_gone.py` 原先按路径给它的两条 `SYMBOL_ALLOWED` 登记在同批摘掉（归档件在 `draft/`，不在那条判据的扫描面 `src/tests/scripts/tools/docs` 里 ⇒ 摘掉登记不是放宽，是登记跟着对象走） |
| `FC27-PENDING-CLEANING-2026-10-21.md` | 2026-10-21 | 同上（清洁批次，机器证据见它自己的 §3）；**2026-11-22 DOCS-CLEANUP 归档 → `draft/archive-docs/FC27-PENDING-CLEANING-2026-10-21.md`** |
| `NOAI-SUSPENSION-2026-09-25.md` | 2026-09-25 | 已被 `NOAI-SUSPENSION-2026-09-28.md` 取代（更晚的一次临时开放记录）；**已退役 → `draft/archive-NOAI-SUSPENSION-2026-09-25.md`**（2026-11-21 CLEAN-ALIGN） |
| `NOAI-SUSPENSION-2026-09-28.md` | 2026-09-28 | 目前最晚的一次开放记录，无后续；**已退役 → `draft/archive-NOAI-SUSPENSION-2026-09-28.md`**（2026-11-21 CLEAN-ALIGN） |
| `REPRO-eval-results-no-producer.md` | 2026-10-21 | 复算证据：`test_eval_results_has_no_producer.py` 那三条读数的原文（从判据 docstring 搬出来是为了保住转义序列）；它随那条判据活着，不是过时文档 |

### 3.2 已退役（2026-11-21 CLEAN-ALIGN / 2026-11-22 ARCHIVE / 2026-11-22 ARCHIVE2 移到 `draft/`，本仓不再跟踪）

口径：**一次性取证说明 / 旧计划 / 已被取代的送审页 / 设计理由文档 / 历史登记表**从交付面移走，原件改名
`archive-<原名>` 落 `draft/`（该目录在 `.gitignore` §448 里，不进仓）；正文一字不改 ——
退役的是"它在交付面上的位置"，不是它记的事。下表逐条给退役理由与复算入口。

| 原路径 | 退役理由 |
|---|---|
| `docs/TOOLBOX-DRAFT-roles.md` | 2026-09-30 的角色工具箱设计草案（自陈"不构成判据"）；当前工具面由 `tests/test_tool_surface_snapshot.py` 一族现算 |
| `docs/PROPOSAL-side-effect-axes.md` | 提案：`side_effect` 两根轴已按 `tools/base.py` 落地（P-13），提案正文只作历史依据 |
| `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` | 迁移提案：`documents.claims` 的字段已在 `claimanatomy` 落地（提案自陈"多处把提案当成已经这样了"） |
| `docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md` | 迁移提案：幂等键三处（`UsageEntry.idem_key` / `validate_table` / `Tx.insert_unique`）都已在盘上 |
| `docs/FC27-REVIEW-2026-10-19.md` | 2026-10-19 送审页，已被 2026-10-21 两批取代（见 §3.1） |
| `docs/FC27-PENDING-LEAN.md` | 2026-10-17 Lean 待批清单，已被 2026-10-19 / 10-21 送审页取代（见 §3.1） |
| `docs/SELF-CHECK-FINDINGS.md` | 2026-10-18 自检失败项台账（文件自陈"修复轮已结账"）；`ROLE-SPECS.md` / `ROLE-SPECS-APPENDIX.md` 的引用已改指 `draft/archive-SELF-CHECK-FINDINGS.md` |
| `docs/AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04.md` | 2026-11-04 的一次性审计交接（带日期读数）；原先只因 `tests/test_f_does_not_work_for_a_statement_number.py` 的白名单条目留在 docs/，本次连带摘掉那条登记 |
| `docs/WIRING-AUDIT-2026-10-27.md` | 当次接线审计（带日期读数）；现行面由 `KNOWN-UNWIRED.md` + `tests/test_wiring_edges.py` 承担 |
| `docs/AUDIT-VSIGN-5ROLES-E-2026-11-03.md` | 当次五方签字审计（带日期读数）；判据本体在 `tests/test_e_gets_its_v_sign_like_f.py` 一族 |
| `docs/RUN-2026-11-04-PAPER-REWRITE-BIG.md` | 当次真机收工总账（带日期读数），不构成判据 |
| `docs/D-COLLAB-AND-MANUSCRIPT-UNIFICATION-2026-11-05.md` | 当次交接记录；现行口径在 `ROLE-SPECS.md` 与 `tests/test_f_and_b_manuscripts_are_one_implementation.py` |
| `docs/REHEARSAL-A-LITERATURE-FLOW.md` | 当次彩排记录；判据本体在 `tests/test_rehearsal_a_literature_flow*.py` |
| `docs/NOAI-SUSPENSION-2026-09-25.md` / `…-09-28.md` | 已被取代的临时开放记录（见 §3.1） |
| `docs/NOAI-CHANGE-LIST-management.md` | 旧改动清单（过程件）；治理现行面见 `NOAI-GOVERNANCE.md` 与 `draft/archive-NOAI-REVIEW-REGISTER.md`（该登记表 2026-11-22 退役，见本表末六行） |
| `docs/SCHEMA-DRAFT-management.md` | 旧 schema 草案（旧计划） |
| `docs/SCHEMA-MIGRATION-PROPOSAL-review-axis.md` | 旧提案（review 轴） |
| `docs/ROLE-SPECS-DRAFT-V.md` | 旧角色草案（V 已按 `ROLE-SPECS.md` 落地） |
| `agentflow/temp/cc3/REPORT-CC3.md`、`temp/cc4/REPORT-CC4.md`、`temp/rs/RS-REHEARSAL-20261115.md`、`temp/vf/REPORT-VF.md` | 一次性路交付/彩排报告（`temp/` 按 `AGENTS.md` R2 只放探针；这四份是过程件） |
| `agentflow/DESIGN.md` | **2026-11-22 ARCHIVE2（业主指令）**：`test/test1` 原型（包名 `abflow`）的设计基线 v0.1。正文自述「不是行为规格」，且读数已过期 —— 写着「顶层 62 个 `*.py`」（退役当日复跑 222）、「17 张表」（退役当日 `schema.TABLES` = 16），点名的 `agent_a.py` / `agent_b.py` 已是包。→ `draft/archive-DESIGN.md` |
| `agentflow/DESIGN-TOOLS.md` | **2026-11-22 ARCHIVE2（业主指令）**：工具层 + C/D 设计 v0.2。§1.1 自述「快照：观测 2026-09-26」（当时 13 个已装模块 / 79 个工具；退役当日复跑 110 件），§6 自述「以下是 2026-09 的历史快照」。现行工具面见生成物 `ROLE-GUIDE.md`。→ `draft/archive-DESIGN-TOOLS.md` |
| `agentflow/DESIGN-INTERACTIONS.md` | **2026-11-22 ARCHIVE2（业主指令）**：I1–I7（A/B/C/D 四角色）设计 v0.3。缺省值已过期（文中 2 / 10 / 20 / 2；退役当日 `interactions.DEFAULTS` = 12 / 100 / 200 / 8），且现行系统是十一角色 / 32 条召唤边。→ `draft/archive-DESIGN-INTERACTIONS.md` |
| `agentflow/DESIGN-ROLES.md` | **2026-11-22 ARCHIVE2（业主指令）**：E/F/G/H 四角色设计 v1.0。角色表停在 A–H（退役当日 `schema.ROLES` = A–H + V、L），§2.1 的接口只是示意（`DEVELOPMENT-SPEC.md` §12 明写「读签名用 `inspect.signature`」）。现行角色规格见 `ROLE-SPECS.md`，五条被推翻的条款逐条见 `DESIGN-BASELINE.md` §4。→ `draft/archive-DESIGN-ROLES.md` |
| `agentflow/DESIGN-CONDUCTOR.md` | **2026-11-22 ARCHIVE2（业主指令）**：主控编队设计 v1.0。§3 声称「七个字段与默认值逐一与 `policy.Policy` 相同」，而退役当日复跑：`max_concurrency=None`（文 4）、`max_tasks_per_run=5000`（文 200）、`wall_clock_sec=14400`（文 900）。边表与不变式已由 `DESIGN-BASELINE.md` B07/B08 承接。→ `draft/archive-DESIGN-CONDUCTOR.md` |
| `agentflow/NOAI-REVIEW-REGISTER.md` | **2026-11-22 ARCHIVE2（业主指令）**：2026-09-24 那一轮 FC-27 人工复核登记表。核心前提「`agentflow` 不是 git 仓库 ⇒ `--git` 永远 `unknown(2)`」今天不成立（`.git` 在 `D:\Incubator`）；治理现行面是 `NOAI-GOVERNANCE.md` + `.noai-approvals.json` + `scripts/noai_gate.py`。→ `draft/archive-NOAI-REVIEW-REGISTER.md` |
| `docs/PROPOSALS.md` | **2026-11-22 DOCS-CLEANUP（业主指令「内容过时就要归档」）**：424 KB 的提案/缺口登记册。它自己首行就写"本文是登记册：条目正文记录的是**登记当时**的状态，不是当前状态"，并在「⓪ 会漂的数」里自述"55 个工具 / 12 个模块"是历史快照（现盘 `python -m agentflow.cli tools` = **123** 件 / **17** 个已装模块，Lean 开时 126 件）。→ `draft/archive-docs/PROPOSALS.md`（正文一字未改；编号 `G-` / `P-` / `N-` 仍是测试 docstring 的引用命名空间，落点改为归档件） |
| `docs/DEVELOPMENT-APPENDIX.md` | **2026-11-22 DOCS-CLEANUP**：开发规范的历史面，自述"每一个数字都是当时读数，除明确写出复跑命令者外本轮一律未复跑"。现行面是 `DEVELOPMENT-SPEC.md`（规范）＋ `../DEVELOPMENT.md`（入口）。→ `draft/archive-docs/DEVELOPMENT-APPENDIX.md` |
| `docs/USER-GUIDE.md` | **2026-11-22 DOCS-CLEANUP**：2026-10-23 的合并版用户手册。§5 的网页清单写"九页（导航八条）"，而现盘 `ui/src/main.tsx` 的 `NAV` 是 **9 条**（含 `错误动作` `/errors`）＋ `/run/:sid` = **十页**；CLI 侧由 `USER-GUIDE-CLI.md`（2026-11-21 逐条实跑）、网页侧由 `USER-GUIDE-WEB.md`（2026-11-22 逐请求实跑）承担，钱 / 退出码 / doctor 三节在 CLI 册 §5.4 / §6.1 / §3.5，Lean 两档在 `LEAN-MODES.md`。→ `draft/archive-docs/USER-GUIDE.md` |
| `docs/FC27-SIGNING-GUIDE-2026-10-27.md` | **2026-11-22 DOCS-CLEANUP**：2026-10-27 第二批的签字操作单（一次性批次件）。§1 自述的"46 条唯一路径"已是旧读数（现盘 **68** 条唯一路径）。现行门语义见 `NOAI-GOVERNANCE.md` §5，硬约束见 `../AGENTS.md`。→ `draft/archive-docs/FC27-SIGNING-GUIDE-2026-10-27.md` |
| `docs/FC27-PENDING-2026-10-21.md` / `docs/FC27-PENDING-CLEANING-2026-10-21.md` | **2026-11-22 DOCS-CLEANUP**：2026-10-21 两批送审页（一次性送审记录）。→ `draft/archive-docs/`（见 §3.1） |
| `docs/ROLE-SPECS-DRAFT-N-O-Q.md` | **2026-11-22 DOCS-CLEANUP**：N/O/Q 三角色的**草案**（自述"新增"、工具面"设计 14 / 8 / 10 个"）。现盘 `schema.ROLES` = A–H + V + L，`capabilities.CAPABILITIES` 只有 11 个角色 —— 这三个角色从未登记。→ `draft/archive-docs/ROLE-SPECS-DRAFT-N-O-Q.md`（`tests/test_role_specs_complete.py` 的 `--roles N,O,Q` 夹具随之指到归档件：它守的是 `verify_role_specs.py` 的"查任意角色文档"能力，与批次无关） |
| `docs/USER-TEST-TASK.txt` / `docs/USER-TEST-TASK-NAIVE.txt` / `docs/USER-TEST-TASK-QUOTE-FORMAL.txt` | **2026-11-22 DOCS-CLEANUP**：2026-10-03 / 10-13 三次真机跑用的任务原文（一次性运行证据，其中 `-QUOTE-FORMAL` 里写着当时那台机器的 Lean 绝对路径）。这三份不是 `.md`、本来就不入册；归档后 `tests/test_settings.py` 的 `_RESIDUE_REGISTER` 里那两条按路径钉住的残渣登记同批摘掉。→ `draft/archive-docs/` |

**为什么还有几份历史件留在 `docs/`**：`tests/test_docs_index_covers_every_doc.py` 的反真空下限是
`MIN_DOCS = 45`（**2026-11-22 DOCS-GAPS 按现盘重钉**：DOCS-CLEANUP 之后盘上除 `INDEX.md` 外 40 份，
本轮新增 §1 的 `README.md` 与 §2.2 的四份（`INSTALL-AND-FIRST-RUN.md` / `LIMITS-AND-NON-GOALS.md` /
`GLOSSARY.md` / `TEACHING-VERSION-BUMP.md`）⇒ 现盘 45 份，门槛跟着现盘走。判据强度没变 ——
"每一份盘上文档都要在 INDEX 有落点"仍是硬判据；`MIN_DOCS` 只是"索引被清空"的反真空读数，
不是份数账；这一轮**没有**为了凑数留下任何过时文件，也没有为了压门槛归档任何现行文档）。
**今天的份数以 `(Get-ChildItem docs/*.md).Count` 现读为准**（并发下写死一个数第二天就过期）。

**本轮不退役**的文档，逐条理由（口径：**内容今天还准确**才算现行；"有判据引它"本身不是理由）：

- `ROLE-SPECS.md` / `ROLE-SPECS-APPENDIX.md`：终端的工具面 / 动作条数 / 逐角色清单由
  `tests/test_role_specs_complete.py`、`tests/test_role_specs_appendix_is_live.py` 与
  `tools/verify_role_specs.py` **逐格对拍现盘装配**（126 件 = Lean 开；关着 123）；
- `USER-END-DSH-STYLE.md`：DSH 令牌的 MIT 出处与 `tests/test_webui.py` 钉的三条纪律；
- `REPRO-eval-results-no-producer.md`：`tests/test_eval_results_has_no_producer.py` 读它的逐字文本；
- `USER-TEST.md`：人读的验收剧本；`tests/test_release_all.py` 钉它那句"现在的门…八格"与
  `closing.DEFAULT_CHECKS` 现读一致（组成换过就红）；
- `KNOWN-UNWIRED.md`：机器可读区块与盘上未装配的 `*_tools.py` 集合逐件对拍；
- `PRESET-RETIREMENT.md`：预设退役**之后**的现状（A 的正文住 `specs/a.py::SEARCH_STYLE`、
  段号 2000 不变），不是过时件。

要在**改判据下限**（或业主直接裁定）之后再退一批 —— 这属于测试与业主口径，不由本文单方面改。

## 4. 设计理由（2026-11-22 起全部退役到 `draft/`，**不是**行为规格）

五份 `DESIGN*.md` 已按业主指令（「经查都是老文件，派人清理归档，不要放在
`D:\Incubator\agentflow` 下」）退役到 `draft/archive-<原名>`，正文一字未改；逐条退役理由
见 §3.2。**现行设计基线**是 [`DESIGN-BASELINE.md`](DESIGN-BASELINE.md)（51 条 B01–B51）；
系统现状读 [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md)，角色规格读 [`ROLE-SPECS.md`](ROLE-SPECS.md)。
代码、注释与其它文档里按名字引 `DESIGN-*.md` / `NOAI-REVIEW-REGISTER.md` 的地方（只给文件名
与节号的那一类），一律经 §3.2 那张映射表落到 `draft/archive-*.md`（文件名一一对应，只多了
`archive-` 前缀）；本索引正文给的现行落点则直接读 `DESIGN-BASELINE.md` / `SYSTEM-INTRO.md` /
`ROLE-SPECS.md`。

**判据侧的同批处置**（不是 skip、不是放宽）：`tests/test_sysclean_design_side_is_current.py`
的三块"设计与实现两向对拍"换成了现行对象（`ROLE-SPECS.md` / `DESIGN-BASELINE.md` B07·B08 /
`ROLE-GUIDE.md`），`tests/test_release_all.py` 的 `_DOC_TEST_REF_DOCS` 从 4 份重钉为 3 份
（新成员 `SYSTEM-INTRO.md`），`DESIGN-TOOLS.md` §1.1 的工具表判据退役（`R6-AN-3`，
被 `test_tool_surface_snapshot.py` 与 `test_role_guide_does_not_name_retired_tools` 承担）。

### 已知的整理欠账（如实登记）

1. ~~`DEVELOPMENT.md`（约 194 KB）与 `ROLE-SPECS.md`（约 241 KB）体量过大~~ **已拆完（2026-10-18）**：
   `DEVELOPMENT.md` → 入口 + `DEVELOPMENT-SPEC.md`（规范）+ `DEVELOPMENT-APPENDIX.md`（历史；
   历史那一半已于 2026-11-22 归档到 `draft/archive-docs/`，见 §3.2）；
   `ROLE-SPECS.md`（拆分前共 2644 行，2026-10-18 当时）→ `ROLE-SPECS.md`（规范）+
   `ROLE-SPECS-APPENDIX.md`（实测附录）+ `draft/archive-SELF-CHECK-FINDINGS.md`（失败项台账，
   2026-11-22 退役）。
   **这四份的当前行数刻意不写死** —— 写死一个数，下一次拆分或增长它就变成「看着有、其实在说谎」
   的读数（本行原先的 `入口 42 行` / `1354` / `374` / `1576` / `1091` 就是这么漂掉的）；
   现行行数一律现算，命令见 §5「文档行数」那一行。
   原始欠账前半句（
   其中不少读数是 2026-09 的。计划拆成「规范（重写、短）」＋「附录（保留、只作查证）」；
   **2026-10-18 已拆**：`ROLE-SPECS.md`（规格）＋ `ROLE-SPECS-APPENDIX.md`（实测附录）。
   分层已由七层更正为八层（新增 Web/用户端）；
2. 「哪份算数」这件事**只有本索引一处维护** —— 所以**新增文档必须在这里登记**，
   否则下一个人只能靠猜；
3. ~~`DESIGN*.md` 五份尚未逐句核对与当前代码的一致性；引用它们时请只引「理由」，不引「行为」。~~
   **2026-11-22 已销账**：五份已按业主指令退役到 `draft/archive-DESIGN-*.md`（逐条见 §3.2），
   不再是本仓的交付面 —— 现行设计基线读 `DESIGN-BASELINE.md`，现状读 `SYSTEM-INTRO.md`。
   这条欠账的残余形态只剩一件事：代码注释里按名字引 `DESIGN-*.md` 的地方（§4 的映射表兜底）。

## 5. 复跑命令（把文档里的数字验一遍）

```bash
# 表 / 角色 / 动作 / 子命令 —— README 里那些数字的来源
python -c "import sys;sys.path.insert(0,'agentflow/src');from agentflow import schema as S;print(len(S.TABLES))"
python -c "import sys;sys.path.insert(0,'agentflow/src');from agentflow import capabilities as C;print(len(C.CAPABILITIES), sum(len(v) for v in C.CAPABILITIES.values()))"
python -m agentflow.cli --help

# 全量判据（约 25 分钟；**本机开发门**：tests/ 不随仓库交付，干净 clone 里没有这个目录）
python -m pytest -q

# 禁改区门（命中 ⇒ 退出码 1，需要 2 名 reviewer 批准）
python scripts/noai_gate.py --git
```

```powershell
# 文档行数 —— §1 的入口与 §4「已知的整理欠账」**刻意不写死**这些数字（会随开发漂）。
# 在仓库根（D:\Incubator）跑；输出即当前值，无需回来改本文。
foreach ($f in 'agentflow/DEVELOPMENT.md','agentflow/docs/PROMPT-HISTORY.md',
               'agentflow/docs/DEVELOPMENT-SPEC.md','../draft/archive-docs/DEVELOPMENT-APPENDIX.md',
               'agentflow/docs/ROLE-SPECS.md','agentflow/docs/ROLE-SPECS-APPENDIX.md') {
  "{0}: {1} 行" -f $f, (Get-Content $f).Count
}
```

> 本目录的其余说明（历史沿革、发布检查入口 `tools/release_all.py` 与
> `scripts/release_check.py` 的关系）见 `draft/archive-docs/PROPOSALS.md` P-11；那份是历史依据
> （2026-11-22 归档，见 §3.2）。

## 6. 不入册（**显式登记 + 理由**，不是"漏了"）

新增一份 `docs/*.md` 而不在 §1–§3 里登记，判据 `tests/test_docs_index_covers_every_doc.py`
会红。确实不该入册的（草稿、一次性复算输出、给外部看的临时纸），登记到这张表里并写清为什么 ——
"没登记"与"登记了不打算登记"必须在机器读数上分得开。

| 文件 | 为什么不入册 |
|---|---|
| （今天没有这一档） | 现盘每一份 `docs/*.md`（含本索引与 2026-11-21 新增的 `USER-GUIDE-CLI.md`、`SYSTEM-INTRO.md`）都在 §1–§3 里出现过或登记进 §3.2 —— **这里刻意不写份数**：`docs/` 在并发开发下随时增减，写死一个数第二天就过期；"盘上有几份"以 `(ls docs/*.md).Count` 现读为准 |
