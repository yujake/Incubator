# 43-旧设计调查-B：图书馆 / OCR / 本地库时代的残留

- 调查对象：`D:\Incubator\agentflow`（包 `agentflow`，源码 `src/agentflow/`，工具层 `src/agentflow/tools/`）
- 判据来源：`D:\Incubator\draft\*.md`（01–42）、`agentflow/DESIGN-TOOLS.md`、`agentflow/DESIGN.md`、`agentflow/README.md`、`agentflow/DEVELOPMENT.md`、`agentflow/docs/`
- 真机证据：两个工作区根 `D:\Incubator\agentflow\projects`（58 个）与 `D:\Incubator\projects`（23 个）
- 本报告只做**取证与描述**（是什么 / 当年为什么 / 今天谁在用 / 有没有负面效果），**不含修改建议**
- 允许的操作：`read`/`grep`/`glob`、`python -B -c` 与只读统计脚本、读工作区目录与台账；**未真跑模型、未联网、未真跑 OCR、未跑 pytest、未修改仓库任何文件**
- 计数口径：`src=` 指 `agentflow/src/agentflow/**.py`（含 `tools/`、`agent_*/`），`tests=` 指 `agentflow/tests/**.py`；`__pycache__` 已排除；**命中含注释与 docstring**（本报告靠它们读"当年为什么"，故未过滤）
- 真机读数一律注明扫的是**哪个根**。两个根内容完全不同，混用会让读数失去意义

## 1. 结论（先答核心问题）

**这条链路今天仍有活的入口与消费者，但"图书馆/OCR"这一层已经只剩外壳。**

三条事实合起来给出答案：

1. **"本地目录登记"这件事是活的**，而且已经从"图书馆"迁到"给审阅线灌入源文件"：`A.ingest_local` 动作在真机 `tasks` 里被派过 **27 次、27 次全 `ok`**，`search.ingest_local` 工具在 A 的原生工具面上（18 件之一），CLI 侧 `project run --books` 是活的。
2. **"扫描件 OCR"这件事是死的**：三个 `ocr.*` 工具进装配面、只给 B、B 的原生 `function_schemas` 里确实有 `ocr__run` / `ocr__backends` / `ocr__detect_text_layer`，但**两个根 140 个会话文件里这三个名字一次调用都没有**（只作为角色目录里的三行名字出现过）。而 B 的**动作表里没有任何 ocr 动作**，因此 OCR 既不能派也不能被编排层要求 —— 它只能靠 B 模型"自己想起来"去调，而真机上从未发生。
3. **"图书馆"这件事既无入口也无人消费**：两个根**没有任何** `books/` 目录、**没有一条** `out/ocr*` 产物、`literature` 里带 `locallib` 标记的行只有 **70 行**（40 + 30），而 A 的网络/收编路占了 **857 行**（578 + 279）。`locallib` 的检索接缝（`search_fn_for_store` / `local_fetch_fn` / `memo_extract_fn`）今天只有 `projects.run_project` 一个消费者，而 `projects.run_project` 在**新根 0 次**被跑过（新根 0 张 `project.json`），只在旧根留下 9 张卡、18 次运行。

**"当年为了本地书库而现在既无入口也无消费者"的清单**（逐条见 §3）：`ocr.run` / `ocr.backends` / `ocr.detect_text_layer`（门面在、能力在、无人派也无人调）；`locallib.search_fn_for_store` / `local_fetch_fn` / `memo_extract_fn`（唯一消费者是 `projects.run_project`）；`demo.py` 的 `FixtureDownloader` 一族（消费链已迁到 `--provider fixture`）；`search.local` / `search.shelf`（A/C/H 三面都有，真机 0 次调用）。

## 2. 总表

| # | 旧机制 | 主要落点 | 当年出处（`draft` 文件 + 行 + 原话） | 今天谁在用 | src / tests | 真机读数 | 负面效果 |
|---|---|---|---|---|---|---|---|
| 1 | `locallib.py` 整模块（`ingest_directory` / `sha256_file` / `BookPlan` / `IngestReport`） | `locallib.py:165,68,91,122` | `draft/28` §122.1（`:10271`）"文献来源用 `D:\books`｜`src/agentflow/locallib.py`…`--books D:\books`。不联网：书是本地文件，全文就地读，绝不搬动" | `projects.run_project:547`、`A.ingest_local`（`agent_a/ingest_local.py:90`）、`search.ingest_local`（`tools/search_tools.py:938`）、`conductor.ensure_project`（`tools/conductor_tools.py:659`）、`cli project run` | `locallib` src=17 / tests=12；`ingest_directory` src=18 / tests=15 | 两根本地灌入行合计 **70**（40 + 30）；带 `path` 的行 927 行里它只占 **7.5%**，另 857 行来自 A 的收编 | 有：工具的 docstring 把"当年本地书库"的口径当成今天的口径写（`search_tools.py:1351`"provenance 如实写「由 A 登记」"），而 A 登记的实际用途已是审阅线灌源，不是建图书馆 |
| 2 | `locallib` 检索接缝 `search_fn_for_store` | `locallib.py:549` | 同上 `:10271`（"`search_fn_for_store` / `local_fetch_fn`（接进 `run_topic` 已有的接缝）"） | **只有** `projects.run_project:603`（`search_fn={"localpdf": search_fn}`）与 `locallib.selftest:788` | src=5 / tests=7 | 唯一消费者 `projects.run_project` 在**新根 0 次**运行（新根 `project.json` = 0 张） | 有：`run_topic` 的 `search_fn` 接缝今天在真机上**只有 `None` 这一种取值**（`run-agent` 不传），这条通路生产侧只剩死路 |
| 3 | `locallib.local_fetch_fn`（本地"下载器"） | `locallib.py:616` | 同上 | 同上（`projects.py:604`） | src=5 / tests=6 | 同上 | 有：`fulltextstore` / `evidence._acquire_one` 的全文回验今天走的是网络下载器，这条本地分支只在旧根的 `project` 路用过 |
| 4 | `locallib.memo_extract_fn` | `locallib.py:648` | `draft/28` §187（`locallib.py:444-451` 引）；`projects.py:601` 引"给模型看的材料与回验比对的文本必须是同一份" | `projects.py:446,578,602`、`tools/search_tools.py:216` | src=9 / tests=7 | `search.shelf`/`search.local` 走它（`search_tools.py:212`），而这两个工具真机 0 次调用 | **无（只是残留）**：它是一份正确的记忆化实现，没有第二处以另一种口径实现同一件事 |
| 5 | `locallib.page_scores` / `excerpt_for`（页级打分与窗口） | `locallib.py:441,479` | `draft/28` §124（`locallib.py:444` 引"`draft/28` §187 真机读数逼出来的"）；`draft/28:11105-11142` 记两次修法与判据 | `tools/search_tools.py:313,1258`（`search.local`） | `page_scores` src=7 / tests=3；`excerpt_for` src=10 / tests=6 | 同上（`search.local` 0 次调用） | 有：判据本体在两处（`locallib.page_scores` 与 `search.local` 的 `returns` 声明逐字承诺"同一份口径"），而真机上没有任何调用把两者对上 |
| 6 | `ocr.run` / `ocr.backends` / `ocr.detect_text_layer` | `tools/ocr_tools.py:1002,947,978`（注册） | `DESIGN-TOOLS.md:80`（"OCR（B 专用）｜`ocr.run` / `ocr.detect_text_layer` / `ocr.backends`｜B"）；`DESIGN-TOOLS.md:16`"B 要有 OCR 工具"；`draft/11` §8（`:600`）"OCR 的现实约束" | **只在 B 的原生工具面**（`function_schemas('B')` 13 件里的 3 件）；**B 的动作表 0 个 ocr 动作**（`capabilities.actions_for('B')`），所以 `conductor.summon` 派不到 | `ocr_tools` src=6 / tests=21；`ocr.` src=59 / tests=61 | **两个根 124 + 16 个会话文件里，`ocr__run`/`ocr__backends`/`ocr__detect_text_layer` 的调用 0 次**；只有"角色目录"那 13 行长文本里出现过这三个名字（各 26 次，那 13 行是 `conductor.role_spec` 的回包） | **有（三重）**：① 门面上有、能力上做不到（`ocr_tools.py:1-20` 自述本机无任何可用后端）；② 编排层**结构上派不到**它（B 动作表里没有它），B 只能靠模型自发调用；③ 真机 0 次调用证明"自发调用"这条假设不成立 |
| 7 | `extract.py` 的 PDF 后端回退链与 `pages == []` 无文本层判据 | `extract.py:122`（`DocumentText`）、`_pdf_pages`、`_finish_pdf`（`:643-658`） | `draft/10` §6.3（`:2606-2663`）"无文本层返回 `None` 而不是 `False`：`verified` 是三态"；`draft/11` §8.2（`:610`）"`ocr.run` 的行为" | **活的、主角**：`extract.extract_text` 是全仓抽取主通道（`agent_b`、`quoteverify`、`search.shelf`、`evidence`） | `extract` 属 FC-27 禁改区（`.noai-paths`） | 两本 `literature` 里 `.pdf` 共 628 行、所有走 `project` 的登记读数 `has_text_layer` 均为真 | **无**：它**取代**了 OCR 的文本层判断那一半（`draft/41-H:313` 已记），自己不是残留 |
| 8 | `projects.extract_with_model`（用 `B.run_once` 读本地书） | `projects.py:403` | `draft/28` §200.2（`:18416`）"坑一：`--extract` 的花销挂在一条**不存在的任务**上"；§200.6（`:18539`）"新增判据（`tests/test_projects.py`：14 → 16 条）" | `projects.run_project:577`（`if extract:`）＋ CLI `project run --extract`（`cli.py:2256`）＋ 自检 | src=3 / tests=2 | 旧根 9 张项目卡里有 `--extract` 读数（`project1` 卡 runs 18，`ingest` 合计 ingested=30 / already_present=63）；新根 0 | 有：这条路的 `B.run_once` 是**队列驱动**（认 `processed=False` 的行），与 `run-agent M` 的 `conductor.summon('B','run_once')` 是两套入口，`_open_extract_task`（`projects.py:334`）只为前一套开 `tasks` 行 ⇒ 走后者的人看到 `B.run_once` 行数偏少 |
| 9 | `projects.py` 整条 `project` 流水线（冷/热启动 + 登记 + 端到端 + 项目卡） | `projects.py:516`（`run_project`）、`:157`（`resolve`）、`:132`（`classify`） | `draft/28` §122（`:10255-10290`）用户 2026-09-28 逐字授权"每个项目一个文件夹，均为 projects 文件夹下的子文件夹，默认命名方式为 project1,project2,…" | CLI `project list/plan/run`（`cli.py:2226-2265`、`cmd_project:1004`），**且它是交互台 MENU 第 1 项**（`cli.py:1179`） | `run_project` src=4 / tests=15；`projects` 属 FC-27 禁改区 | 旧根 9 张 `project.json` / 18 次运行 / 15 次带 `books_dir`（13 次 `D:\books`）；**新根 0 张**（主路径已是 `run-agent`） | 有：交互台第 1 项逐字写着"（本地书架、冷启动或热启动）"（`cli.py:1179`）——**文档教一个新用户从"图书馆时代"的入口进入**，而那个入口的落点（`D:\Incubator\projects`）与主路径（`agentflow/projects`）是两个根 |
| 10 | `A.ingest_local` 动作 | `specs/a.py:108-124`；实现 `agent_a/ingest_local.py:53` | `draft/37` §44.4（`specs/a.py:95` 引）："主控只能 `conductor.summon` **动作**，而『把盘上这个目录里的论文登记进台账』原先只有**工具**" | `conductor.summon('A','ingest_local')`；工具侧 `search.ingest_local`（同名两件） | `ingest_local` src=25 / tests=36 | **真机 27 次全 `ok`**（2026-10-03 13 次 / 2026-10-04 14 次，全在 `agentflow/projects`） | 有（历史性）：见第 11 条 —— 这个动作**未存在之前**，主控反复把这个名字派给 B |
| 11 | `B.ingest_local`（主控按错名派活） | 无实现；拒绝点 `conductor.py:255` / `policy.py:193` | `draft/42`（`:219`）逐字："真机 `tasks` 里 `B.ingest_local` 出现 10 次且**全部 `refused`「B 没有动作」**（模型按错名派活）"；`agent_prompts.py:1401` 记同一件事"主控把 `ingest_local` 派给了 B（那是 A 的动作，`refused/unknown_action`）" | 无（`B` 动作表至今 7 个动作、无 `ingest_local`） | 无实现可数 | **独立复核成立**：`tasks` 里 `(role=B, action=ingest_local)` **10 行**，`status=done / outcome=refused`，`detail` 逐字"B 没有动作 'ingest_local'（它有：['run_once','reprocess_once','run_reprocess','decide_structural_duplicate','resolve_structural_duplicate','run','register_statement']）"，`started_at` 全在 **2026-10-04**；分布 `p5-review-t5` 6 行、`p5-review-t10` 2 行、`p5-review-t14` 2 行 | 有：**动作名错配的残余**。同一工作区同一天，`p5-review-t5` 先撞 6 次拒绝（t-0001…t-0006）**然后**才改派 A（t-0008…t-0013 全 ok）—— 即这 10 行是"同一次运行内的自我纠错痕迹"，不是持续故障；但它证明**伙伴画像里"谁有 ingests 动作"当时没说清**（`agent_prompts.py:1400-1403` 自认这是补 `AgentBrief` 的直接动因） |
| 12 | `providers.FixtureProvider` + `demo/fixtures/candidates.json` | `providers.py`（`FixtureProvider`）；`cli.py:167-168` | `README.md:133`"只想验证链路就用 `--provider fixture`（**完全离线**，实测 0.4s：3 候选 → 登记 2、判重 1）" | `run-agent --provider fixture`（`cli.py:2323-2328`）、`demo.py:260` | src=9 / tests=2 | 两个根没有任何 `demo/fixtures/` 产物；`run_demo` tests=23 | **无（只是残留）**：见 `draft/41-H` §8.1，已被推广到新入口而不是被取代 |
| 13 | `demo.py` 离线演示（含 `FixtureDownloader`） | `demo.py` 全文；`run_demo:212`；CLI `cli.py:564-567`、`cli.py:2158`；**MENU 第 5 项**（`cli.py:1183`） | `demo.py:3-6`"单元测试证明『每块零件对』，但证明不了它们拼起来还能跑" | CLI `demo`（可达）；tests `test_demo_end_to_end.py`（6 条） | `run_demo` src=3 / tests=23 | 两个根没有 `demo/` 运行产物 | 有（与第 9 条同族）：MENU 5 项里第 1 项与第 5 项都是"图书馆/演示时代"的入口，而主入口 `run-agent` **不在 MENU 里**（`draft/41-H:74` 已记） |
| 14 | `search.shelf` / `search.local`（本地书架读面） | `tools/search_tools.py:1203,1236` | `draft/28` §187（`draft/28:16993` 逐字给 `search.shelf` 的口径）；`draft/28:19199` 记真机"IV｜**H**｜**本地书架 `search.local`**（不联网）｜H 在本地书架里拿到逐字原文" | A / C / H 三面都有（`for_role` 实测），但**不可召唤**（`capabilities.actions_for` 里没有它） | `search.shelf` src=3 / tests=12；`search.local` src=6 / tests=12 | **两个根里 `search.local`/`search.shelf` 的调用 0 次**（只有 `conductor.role_spec` 回包里出现过 3 行 / 16 行名字文本） | 有：真机读数与 `draft/28:19199` 记的"IV 路由通关"相反 —— 那条真机现场在**当前两个根里找不到**（可能已被清理），所以今天唯一的本地来源通路是 A/C/H 面上那两件**从未被调过**的工具 |
| 15 | `library/` 目录本身 | `store.py:452`（`self.library = self.root / "library"`）、`store.py:541`（`init()` 无条件 mkdir） | `DESIGN.md:469`"`library/` 下载的文献（lit_id 子目录）"；`draft/28` §122.1（`:10274`）"`library/`（书的副本）" | `Store.init()`、A 的收编（`agent_a/core.py:362-385`）、`store.library_path`（`:1414`） | `library_path` src 多处；`store.py` 属 FC-27 禁改区 | **57 / 22 个工作区有 `library/`**（不是因为它曾被用来装书，而是 `init()` 无条件建）；两个根 `library/` 共 **950 个文件 / 1.36 GB** | 有：**"有 `library/` 就是图书馆时代的证据"这个读法是错的** —— `library/` 是 `init()` 的固定产物，今天装的全是 A 下载/收编的文献（`0007/source.pdf` 形态） |

## 3. 逐条展开

### 3.1 `ocr.*` 三件：门面上有、编排层派不到、真机零调用

**它是什么**：`tools/ocr_tools.py`（1600+ 行）。三件工具在 `:947`（`ocr.backends`）、`:978`（`ocr.detect_text_layer`）、`:1002`（`ocr.run`）注册，`roles=("B",)`。副作用三态各不相同且如实声明：`ocr.run` = `write_local` × `egress`（`:1030,1042`），`ocr.backends` = `write_local` × `none`（`:959`），`ocr.detect_text_layer` = `read` × `none`（`:988`）。

**当年为什么存在**：
- `DESIGN-TOOLS.md:16` 逐字："给 A/B 配齐『所有涉及文件』的增删改查工具；A 要有强大的文献检索工具，**B 要有 OCR 工具**。"
- `DESIGN-TOOLS.md:24`："一切**能确定性做到**的（计数、图搜索、编号溯源、索引、CRUD、**OCR 调度**）都必须用程序实现，**不交给 LLM**。"
- `DESIGN-TOOLS.md:80` 给出两根轴的分配与 `run = egress`（首次下 easyocr 模型）。
- `draft/11` §8（`:600`）"OCR 的现实约束"＋ §8.2（`:610`）"`ocr.run` 的行为"给出本机实测：`easyocr` 因 torch 2.0.1+cpu × numpy 2.4.6 ABI 与模型目录权限失败、`pytesseract` 缺 `tesseract` 二进制。`draft/11:643-647` 另记一次成功现场（`test/test1/.venv-ocr` + `EASYOCR_MODULE_PATH` ⇒ `ok: True, backend: easyocr, total_chars: 44`），并逐字说"**最有价值的一点：无需改任何代码。**"
- 三态纪律的出处是 `draft/10` §6.3（`:2632`）："无文本层（扫描版）时返回 `None` 而不是 `False`：**『没校验』和『校验失败』是两件不同的事，前者需要 OCR，后者需要改引文。**"

**今天谁在用**：
- `src/` 调用点：`ocr_tools` src=6（只在本模块与 `tools/__init__.py` 的模块清单里）；工具名字符串 `ocr.` src=59（含 `agent_prompts.py:1304` 把前缀 `ocr.` 归进"正式类读面"）。
- 装配面（`build_registry` 的 role 表，本轮实测）：`B n=13`，其中 `ocr=['ocr.backends','ocr.detect_text_layer','ocr.run']`；A/C/H/M 四面的 ocr 数 = 0。
- 原生工具面：`reg.function_schemas('B')` 实测返回 13 件，含 `ocr__backends` / `ocr__detect_text_layer` / `ocr__run`。**所以模型确实拿得到这三个函数名。**
- 动作面：`capabilities.actions_for('B')` = `['run_once','reprocess_once','run_reprocess','decide_structural_duplicate','resolve_structural_duplicate','run','register_statement']` —— **7 个动作、0 个 ocr 动作**。`conductor.summon` 只派动作，因此**编排层结构上派不到 OCR**。
- CLI 可达性：`cli.py` 里 0 处 `ocr`（无子命令、无开关、MENU 无入口）。
- **真机读数（本轮独立复核，这是本报告最硬的一条）**：两个根共 124 + 16 = 140 个 `sessions/*.jsonl`；凡是行内出现 `ocr__run` / `ocr__backends` / `ocr__detect_text_layer` 的**非角色目录行 = 0**。唯一命中的 13 行是 `conductor.role_spec` 的返回体（角色目录里逐字列出 B 的工具名），每行同时含 13 个工具名。即：**OCR 三件从未被调用过一次**。
- 测试覆盖：`ocr_tools.py` tests=21 个命中（`tests/test_tools_search_ocr.py` 14 个 test 函数 + `tests/test_f4_ocr_detect_reason.py` 5 个）；判据**全部是单件工具的契约**，没有一条真跑 OCR（模块 docstring 自述本机无可用后端）。

**负面效果（具体机制）**：
1. **能力表说 B 能 OCR，环境说不能。** `docs/ROLE-SPECS.md:263-265` 把三件列给 B 并逐条写了"已修"；而 `ocr_tools.py:1-20` 的表是本机实测"easyocr 装了但跑不了 / pytesseract 装了但缺二进制 / 结论：本机没有任何可用的 OCR 后端"。调用者（人或其他角色）按能力表会认为 B 能 OCR。
2. **编排层与工具层的可派性不一致。** 工具在 B 面上（`function_schemas` 有），动作表里没有 —— 于是"谁能让 B 去 OCR"这个问题在今天的编排层**没有答案**：只有 B 模型在原生工具循环里**自发**调用。真机 0 次调用说明这条假设在 140 个会话里一次都没成立。
3. **文档教人走一个已废的入口。** `DESIGN-TOOLS.md:414` 的标题逐字是"## 7. OCR 的现实约束（已勘察）"，`:422-424` 还在写"`ocr.backends` 必须**真实探测**…**没有可用后端时必须返回 `available=False` 且理由明确**" —— 这是给一个**从未被调用**的工具写的使用规范。
4. 附带一处**判据重复**：`ocr.detect_text_layer` 的文本层判据（`ocr_tools.py:543` `has_layer = bool(doc.pages)`）与 `extract.extract_text` 的 `pages == []` 契约是同一件事的两处实现；`ocr_tools.py:660` 的 `rule` 字段逐字自认"与 `extract.py` / §6.3 的判据完全一致"——一致靠注释声明，不靠判据（`grep` 无交叉断言）。

**可复算命令**：
```powershell
cd D:\Incubator
# 1) 三件工具的装配面与两根轴
python -B -c "import sys;sys.path.insert(0,'agentflow/src');import agentflow.tools as T;r=T.build_registry().registry;print([(n,r.get(n).roles,r.get(n).side_effect,r.get(n).declared_external) for n in ('ocr.run','ocr.backends','ocr.detect_text_layer')])"
# 2) B 的原生函数面
python -B -c "import sys;sys.path.insert(0,'agentflow/src');import agentflow.tools as T;print([s['function']['name'] for s in T.build_registry().registry.function_schemas('B')])"
# 3) B 的动作表（0 个 ocr 动作）
python -B -c "import sys;sys.path.insert(0,'agentflow/src');import agentflow.capabilities as C;print([a.action for a in C.actions_for('B')])"
# 4) 会话里三个名字的真实调用次数（非角色目录行）
python -B -c "import os,re;N=('ocr__run','ocr__backends','ocr__detect_text_layer');[print(rt,{n:sum(1 for dp,dn,fn in os.walk(rt) if os.sep+'sessions' in dp for f in fn if f.endswith('.jsonl') for ln in open(os.path.join(dp,f),encoding='utf-8',errors='replace') if len(ln)<2500 and ('\"%s\"'%n) in ln) for n in N}) for rt in (r'agentflow\projects',r'projects')]"
```

### 3.2 `B.ingest_local` 10 次 `refused`：独立复核（成立）与它的真实性质

**它是什么 / 落在哪**：没有实现。拒绝由 `conductor.py:255`（`raise NotWiredError(f"{role} 没有动作 {action}")`）与 `policy.py:193` 产生；B 这一侧的动作表在 `specs/b.py`，共 7 个动作。

**当年线索的出处**：`draft/42`（`:219`）逐字："真机 `tasks` 里 `B.ingest_local` 出现 10 次且**全部 `refused`「B 没有动作」**（模型按错名派活）"。同一件事也被代码记下：`agent_prompts.py:1400-1403`"真机代价：主控把 `ingest_local` 派给了 B（那是 A 的动作，`refused/unknown_action`），也会拿『越权请求』去撞拒绝 —— 这些在事前本来就能避免。"

**独立复核（本轮自己扫两个根）**：
```
D:\Incubator\agentflow\projects
  (role=B, action=ingest_local): status=done  outcome=refused  2026-10-04  n=10
  (role=A, action=ingest_local): status=done  outcome=ok       2026-10-03  n=13
  (role=A, action=ingest_local): status=done  outcome=ok       2026-10-04  n=14
D:\Incubator\projects
  （无任何 ingest_local 行）
```
10 行的分布：`p5-review-t5` 6 行（t-0001…t-0006）、`p5-review-t10` 2 行（t-0009/t-0010）、`p5-review-t14` 2 行（t-0001/t-0002）。`detail` 逐字：
> `B 没有动作 'ingest_local'（它有：['run_once', 'reprocess_once', 'run_reprocess', 'decide_structural_duplicate', 'resolve_structural_duplicate', 'run', 'register_statement']）`

注意拒绝消息里的**动作清单是当时的真身**：它已经把 `register_statement` 算进去了（`draft/37` §87 那条线上加的动作），说明这 10 次发生在 `A.ingest_local` 落地（2026-10-02）**之后**、`p5-review` 那一轮（2026-10-04）。

**今天谁在用**：`B.ingest_local` **至今不存在**；存在的是 `A.ingest_local`（`specs/a.py:108`，`external="none"`，`side_effect="write_local"`）。

**负面效果（具体机制）**：
- 这是**动作名错配的残余**，而不是"图书馆时代的功能"。它的机制很具体：主控只能派**动作**，而"登记本地目录"在工具层是 `search.ingest_local`（A 的工具），在动作层（`A.ingest_local` 落地前）**根本不存在**。于是主控按工具名去猜动作名，猜成了 `B.ingest_local`（它以为"登记文献"是 B 的活 —— 这与 B 的职责描述"把新到的文献变成概念行与关系行"相邻）。
- **同一次运行内自我纠错**：`p5-review-t5` 的 `tasks` 行序是 t-0001…t-0006 = B 拒绝（6 次）、t-0008…t-0013 = A 成功（6 次）。也就是说这 10 行记录的是"撞了 6 次墙之后改派 A"的过程，**不是**一个持续到今天的故障。
- **但它留下一条今天仍然可见的形态**：`p5-review-t14/notes/M.md:4` 逐字写着"library/ 空。literature 表 0 行的根因是 B.run/run_once 没有真的登记（它需要 reprocess 或 register_statement 路径）" —— M 把"登记没做成"归因给了 B，而正确归因是"没人派 `A.ingest_local`"。`agent_b/register_statement.py:163` 也把这一现象记成"`literature` 表 0 行（那一趟没人派 `A.ingest_local`）"。**同一现象在三处有两种归因**，没有判据要求它们一致。

**可复算命令**：
```powershell
cd D:\Incubator
python -B -c "import os,json,collections;c=collections.Counter();[c.update([(str(r.get('role')),str(r.get('action')),str(r.get('status')),str(r.get('outcome')),str(r.get('started_at'))[:10])]) for rt in (r'agentflow\projects',r'projects') for d in os.listdir(rt) for f in [os.path.join(rt,d,'data','tasks.json')] if os.path.isfile(f) for r in json.load(open(f,encoding='utf-8')).get('rows',[]) if r.get('action')=='ingest_local'];print(*sorted(c.items()),sep='\n')"
# 逐条 detail（UTF-8 落盘后查看）
python -B -c "import os,json,io;o=io.open('_ingest_rows.txt','w',encoding='utf-8');[o.write(json.dumps({k:r.get(k) for k in ('task_id','role','status','outcome','detail','started_at')},ensure_ascii=False)+'\n') for rt in (r'agentflow\projects',r'projects') for d in os.listdir(rt) for f in [os.path.join(rt,d,'data','tasks.json')] if os.path.isfile(f) for r in json.load(open(f,encoding='utf-8')).get('rows',[]) if r.get('action')=='ingest_local'];o.close()"
```

### 3.3 `locallib.py`：唯一"活的"本地库层，但用途已经换了

**它是什么**：`locallib.py`（824 行）。对外面：`ingest_directory:165`、`list_books:83`、`search_fn_for_store:549`、`local_fetch_fn:616`、`memo_extract_fn:648`、`excerpt_for:479`、`page_scores:441`、`sha256_file:68`、`selftest:703`。

**当年为什么存在**：`locallib.py:1-33` 的模块自述是完整答案，逐字摘：
> "框架原来的『文献来源』是网络 provider（`openalex` / `crossref`），而用户手里常常已经有整柜 PDF（本仓库的测试源就是 `D:\books` 那七本书）。没有这一层，那些书只能靠人手写成 seed 清单（`test/test2/paper_seed.py` 走的就是人工清单那条路），『本地已有文献』这件事在框架里没有位置。"

用户侧的授权原文在 `draft/28` §122.1（`:10271`）与 `draft/28:10258-10262`："文献来源可用 `D:\books` 做测试…需真实完成一次全流程测试"。三条纪律（来源不许说假话 / 幂等靠内容 hash / 读不了就如实说）的出处是 `draft/28` §191（`locallib.py:182` 引）。

**今天谁在用**：
| 入口 | 调用点 | 可达性 |
|---|---|---|
| `projects.run_project` | `projects.py:547` | CLI `project run --books`（`cli.py:2239-2240`）；MENU 第 1 项 |
| `A.ingest_local` 动作 | `agent_a/ingest_local.py:90` | `conductor.summon('A','ingest_local')`；真机 27 次 `ok` |
| `search.ingest_local` 工具 | `tools/search_tools.py:938` | A 的原生工具面（18 件之一）；真机 0 次调用 |
| `conductor.ensure_project(books_dir=)` | `tools/conductor_tools.py:659` | M 的原生工具面；真机 `conductor.ensure_project` 被调 **10 次**（两个根），但 `args` 里只观测到 `{"start":"auto"}`，**没有一次带 `books_dir`** |

- `locallib` src=17 / tests=12；`ingest_directory` src=18 / tests=15；`tests/test_locallib.py` 16 个 test 函数。
- **真机读数**：两个根 `literature` 行合计 **1736** 行（1003 + 733）；其中带 `path` 的 **927** 行，**`locallib` 形态（裸文件名 + `download.note` 含"本地文件" + 有 `source_path`）只有 70 行**（40 + 30），其余 **857** 行是 A 的网络/收编形态（578 + 279，`<lit_id>/<slug>.<ext>`）；另有 385 + 424 = **809 行 `path` 为空**（927 + 809 = 1736）。复算：`total 1736 with path 927 empty 809 flat 70 nested 857`。

**负面效果（具体机制）**：
1. **`ingest_directory` 的 provenance 三参数（`actor` / `submitted_by` / `origin_note`，`locallib.py:174-176`）今天有三种不同取值同时活着**：`projects`/`conductor`/`search.ingest_local` 走缺省（`actor="human"`、`submitted_by="human"`、`"人直接提供"`），`A.ingest_local` 走 `actor="agent-A"`/`submitted_by="unknown"`/`"由 agent-A 从一个本地目录登记"`（`agent_a/ingest_local.py:46-48`）。**`search.ingest_local` 的 docstring 却逐字声称"provenance 如实写「由 A 登记」，不借「人直接提供」"（`tools/search_tools.py:1351`）**，而它的 handler `_h_ingest_local`（`:923`）**不传这三个参数** —— 即工具描述与工具实现相反。判据 `tests/test_intake_actions.py` 存在（11 个 test 函数），本轮**未跑 pytest**，因此"这条不一致是否已被判据抓住"**未核实**。
2. **`search_fn_for_store` / `local_fetch_fn` / `memo_extract_fn` 的唯一生产消费者是 `projects.run_project`**，而它在新根 0 次运行。具体机制：`run_topic` 的 `search_fn` / `fetch_fn` 是接缝（`projects.py:603-604,615`），`run-agent` 路径不传它们 ⇒ 真机上新根那 58 个工作区的来源**全部**来自 A 的网络检索或收编，本地书架这条通路一次都没跑。

**可复算命令**：
```powershell
cd D:\Incubator
# 三种 provenance 取值各在哪
cd agentflow; Select-String -Path src\agentflow\*.py,src\agentflow\tools\*.py,src\agentflow\agent_a\*.py -Pattern 'INGEST_ACTOR|INGEST_SUBMITTED_BY|INGEST_ORIGIN_NOTE|submitted_by=|origin_note=|actor='
# literature 行的来源分档（flat=locallib / nested=收编 / empty）
python -B -c "import os,json,collections;[print(rt,collections.Counter(('flat' if ('/' not in (str(r.get('path') or '')) and '\\' not in (str(r.get('path') or '')) and (r.get('path'))) else ('empty' if not r.get('path') else 'nested')) for d in os.listdir(rt) for f in [os.path.join(rt,d,'data','literature.json')] if os.path.isfile(f) for r in json.load(open(f,encoding='utf-8')).get('rows',[]))) for rt in (r'projects',r'agentflow\projects')]"
```

### 3.4 `projects.py` 整条 `project` 流水线：活的入口、旧时代的落点

**它是什么**：`projects.py`（737 行）。`resolve:157` / `classify:132`（四态 absent/empty/workspace/not_a_project）/ `create_project:258` / `plan:295` / `list_projects:314` / `extract_with_model:403` / `run_project:516`；`DEFAULT_PROJECTS_DIR = Path(r"D:\Incubator\projects")`（`:67`）。

**当年为什么存在**：`draft/28` §122（`:10255-10290`）记的是用户 2026-09-28 的逐字授权（`:10258-10262`）："需真实完成一次全流程测试，且每次运行时能选择冷启动还是热启动（就是看项目名所对应的文件夹是否存在），每个项目一个文件夹，均为 projects 文件夹下的子文件夹，默认命名方式为 project1,project2,…"。落点为什么在交付物外面，`draft/28:10277-10279` 逐字："四道门逐字节快照的受审树是 `agentflow/`。把每次运行都会写的数据放进受审树，等于每跑一次就让『这份读数覆盖的字节』再漂一次"。

**今天谁在用**：
- CLI：`project list/plan/run`（`cli.py:2226-2265`；实现 `cmd_project` 在 `cli.py:1004`）；`--books` / `--books-limit` / `--topic` / `--extract` / `--extract-rounds` / `--lean` / `--text-store-dir` 都在。
- **MENU 第 1 项**（`cli.py:1179`）：`("1", "项目：列出 / 计划 / 运行（本地书架、冷启动或热启动）", "project")`。
- `run_project` src=4 / tests=15；`tests/test_projects.py` 16 个 test 函数。
- **真机读数**：
  - 旧根 `D:\Incubator\projects`：**9 张 `project.json`、18 次运行、15 次带 `books_dir`**（`D:\books` ×13、`D:\Incubator\temp\one-book` ×1、`D:\Incubator\temp\scan-only\books` ×1）；`ingest` 计数合计 `ingested=30 / already_present=63 / skipped_limit=0 / skipped_too_large=0 / unreadable=0`。
  - 新根 `agentflow/projects`：**0 张 `project.json`**（主路径是 `run-agent --root`，不写项目卡）。

**负面效果（具体机制）**：
1. **"本地书架"是新用户看到的第 1 项菜单，而主入口不在菜单里。** MENU 5 项 = `project` / `run` / `status` / `tools` / `demo`；`grep run-agent src/agentflow/cli.py` 的命中里没有一处落在 MENU / SHELL_ACTIONS / `_shell_*` 上（`draft/41-H:74` 已记同一条）。
2. **两个根 + 两个默认值。** `projects.DEFAULT_PROJECTS_DIR`（`projects.py:67`）= `D:\Incubator\projects`，而 `cli.DEFAULT_ROOT`（`cli.py:28`）= 仓库里的 `agentflow/`。`project run` 的产物落在前者，`run-agent` 的落在后者。真机把这分叉坐实了：旧根有 9 张项目卡、新根 0 张。
3. **`extract_with_model` 与编排层的 `B.run_once` 是两套入口，只有一套开 `tasks` 行。** `projects._open_extract_task`（`:334`）逐字自述修的是"`f"{project_name}-extract"`…台账里也没有对应行"；而 `run-agent M` 派 `B.run_once` 走 `conductor._write_new_row`。真机 `tasks` 里 `('B','run_once')` 只在**旧根**出现 406 次（新根 0 次，新根用 `('B','run')` 60 次）—— 两套入口在台账上的行名不同，读数不可直接比。

**可复算命令**：
```powershell
cd D:\Incubator
python -B -c "import os,json;[print(rt,'cards',sum(1 for d in os.listdir(rt) if os.path.isfile(os.path.join(rt,d,'project.json')))) for rt in (r'agentflow\projects',r'projects')]"
python -B -c "import os,json,collections;bd=collections.Counter();[bd.update([str(r.get('books_dir'))]) for rt in (r'agentflow\projects',r'projects') for d in os.listdir(rt) for f in [os.path.join(rt,d,'project.json')] if os.path.isfile(f) for r in json.load(open(f,encoding='utf-8')).get('runs',[]) if r.get('books_dir')];print(bd)"
python -B -c "import sys;sys.path.insert(0,'agentflow/src');from agentflow import projects as P, cli;print('projects.DEFAULT_PROJECTS_DIR =',P.DEFAULT_PROJECTS_DIR);print('cli.DEFAULT_ROOT =',cli.DEFAULT_ROOT)"
```

### 3.5 `search.shelf` / `search.local`：本地书架的**读面**，真机零调用

**它是什么**：`tools/search_tools.py:1203`（`search.shelf`，`roles=("A","C","H")`，`read`×`none`）、`:1236`（`search.local`，同三面同轴）。`search.local` 的 `returns` 声明逐字写"score 是 `locallib.page_scores` 的同一份口径"（`:1258`）。

**当年为什么存在**：`draft/28:16993` 给了 `search.shelf` 的口径；`draft/28:19199` 记了真机现场："IV｜**H**｜**本地书架 `search.local`**（不联网）｜不唤起 A（这条路由不用 A）｜H 在本地书架里拿到逐字原文：`lit_id=0001《Commutativity in abelian groups》第 1 页…`"。同一节 `:19441` 把三条路由并列："真机 OpenAlex、离线 `fixture`、**本地书架 `search.local`**"。

**今天谁在用**：
- 装配面：A / C / H 三面的原生工具面里都有（`for_role` 实测：A n=18、C n=17、H n=23）。
- **不可召唤**：`capabilities.actions_for` 里 A/C/H 都没有 `search.local` / `search.shelf` 这类动作（动作与工具是两张表）。
- **真机读数**：两个根 140 个会话文件里，`search__local` / `search__shelf` 的**调用 0 次**。出现的行全是 `conductor.role_spec` 的回包（把工具名列给模型看）：`agentflow/projects` 15 个会话、`projects` 3 个会话。
- 测试覆盖：`search.shelf` tests=12、`search.local` tests=12（`tests/test_search_offline.py` 16 个 test 函数）。

**负面效果（具体机制）**：
1. **"离线本地来源"在真机上没有消费者。** `draft/28:19199` 记的那条真机现场**在本轮两个根里找不到**（无法核到该会话），因此今天唯一能提供"不联网的本地原文"的两个工具从未被调用过。具体机制：它们给的是**逐字摘录 + 页码**（`search.local`）与**书架清单**（`search.shelf`），而真机所有引文回验的来源都是 A 从网络取回并收编进 `library/<lit_id>/` 的 PDF —— 也就是说"本地全文"这件事仍然存在，但它是**A 下载的副产物**，不是"用户手里的书柜"。
2. **docstring 与真机读数相反。** `draft/28:19441` 那句"三条路由都通"是本报告唯一找不到现场的一条；本轮**未核实**它当时的工作区是否已被删除或改名。

**可复算命令**：
```powershell
cd D:\Incubator
python -B -c "import os;N=('search__local','search__shelf');[print(rt,{n:sum(1 for dp,dn,fn in os.walk(rt) if os.sep+'sessions' in dp for f in fn if f.endswith('.jsonl') for ln in open(os.path.join(dp,f),encoding='utf-8',errors='replace') if len(ln)<2500 and ('\"%s\"'%n) in ln) for n in N}) for rt in (r'agentflow\projects',r'projects')]"
cd agentflow; python -B -c "import sys;sys.path.insert(0,'src');import agentflow.tools as T;r=T.build_registry().registry;[print(role,[s.name for s in r.for_role(role) if s.name in ('search.local','search.shelf')]) for role in ('A','C','H')]"
```

### 3.6 `extract.py` / `fetch.py`：不是残留，是"取代者"那一侧

**`extract.py`**：PDF 后端回退链（fitz → pdfminer → PyPDF2）与 `pages == [] 即无文本层` 的判据在 `extract.py:643-658`。它是 `agent_b`、`quoteverify`、`search.shelf`、`evidence` 的共同底层，也是 `ocr.detect_text_layer` 的判据来源（`ocr_tools.py:660` 逐字自认）。**它是 FC-27 禁改区**（`.noai-paths` 的 `solver-core`）。**结论：不是残留 —— 它是"当年为 OCR 准备的文本层判定"的取代者。**

**`fetch.py`**：下载层（含镜像前缀回退、`FetchResult`、`kind` 受控取值）。`locallib.local_fetch_fn:634` 是它的一个"本地文件就地读"适配器。`fetch.py:1022` 只透传认识的配置键、安静忽略 `library_root` —— 说明"library 根"曾作为一个配置概念流经过这里。**今天 `fetch.py` 是活的**（A 的 `search.download`、`evidence._acquire_one`）。**它本身不是图书馆时代的残留。**

### 3.7 `providers.fixture` 与 `demo.py`：离线演示时代的两个落点

**`fixture` 后端**：`cli._build_providers` 的 `elif n == "fixture"`（`cli.py:167-168`）读 `root / "demo" / "fixtures" / "candidates.json"`；`FixtureProvider` src=9 / tests=2。出处 `README.md:133`（"只想验证链路就用 `--provider fixture`（**完全离线**，实测 0.4s：3 候选 → 登记 2、判重 1）"）。**今天被推广到新入口**（`run-agent --provider fixture`，`cli.py:2323-2328`）—— 见 `draft/41-H` §8.1，**只是残留，无负面效果**。一处值得记：fixture 素材有**两个来源**（`demo/fixtures/candidates.json` 与 `demo.py:30-52` 内置的 `DOCS`），都是离线路径，没有第二处口径分歧。

**`demo.py`**：`demo.py:3-6` 给出它当年为什么单独存在（"单元测试证明『每块零件对』，但证明不了它们拼起来还能跑"）。`run_demo` src=3 / tests=23（`tests/test_demo_end_to_end.py` 6 个 test 函数）。它是**唯一不需要模型 key 的端到端路径**，也在 MENU 第 5 项（`cli.py:1183`）。**负面效果：与 §3.4 同族 —— 交互台五项里有两项（第 1、第 5）指向"图书馆/演示"时代，主入口 `run-agent` 一项都没有。**

### 3.8 文档层的"时代地层"（文档教人走已废入口的地方）

| 文档 | 逐字 | 说的事 | 今天实测 |
|---|---|---|---|
| `cli.py:1179`（MENU 第 1 项） | "项目：列出 / 计划 / 运行（**本地书架**、冷启动或热启动）" | 把 `project` 定义成"本地书架入口" | `run-agent` 才是主路径；MENU 里没有它 |
| `README.md:280-284` | "### 3.1 项目式用法：一个项目一个文件夹 + **本地书架**（2026-09-28 新增）…**手里已经有整柜 PDF 时，不必先联网检索**" | 教人用 `--books D:\books` 建图书馆 | 新根 0 张项目卡；本地灌入行只占带 `path` 行的 7.5% |
| `README.md:294` | `project run --books D:\books --extract --extract-rounds 7` | 教人跑"7 本书"那一趟 | `D:\books` 今天仍在盘上（7 个 PDF），但那是**一台机器上的测试源**，不是框架的通用入口 |
| `README.md:312-313` | "实测（2026-09-28，7 本书 2418 页）：7/7 本抽出概念，174 个概念 / 110 条关系" | 把一次历史真跑写成能力陈述 | 与 `draft/28:10307-10308` 的读数一致（那一趟确实跑过），但没有任何判据把它与今天的读数绑起来 |
| `DEVELOPMENT.md:178` | 工具总数 **75**、已装模块 **12** | 工具面读数 | 本轮实测 78 件、**13** 个模块（`manuscript_tools`；`draft/41-H:418` 已记同一条） |
| `DESIGN-TOOLS.md:414-424` | "## 7. OCR 的现实约束（已勘察）… `ocr.backends` 必须**真实探测**" | 给 OCR 写使用规范 | 三件 OCR 工具真机 **0 次调用**、动作层 **0 个 ocr 动作** |

## 4. 可复算命令汇总

```powershell
# 0) 本报告所有真机读数的合订探针（只读；本报告 §1/§2 的数字都出自它）
cd D:\Incubator
python -B _probe_43_readings.py       # 见 §5 说明：该脚本是可复算的读数脚本，不是仓库文件

# 1) 工作区目录读数（library/ books/ out/ocr* project.json）
$roots = 'D:\Incubator\agentflow\projects','D:\Incubator\projects'
foreach ($r in $roots) {
  "== $r"
  "ws      = " + (Get-ChildItem $r -Directory).Count
  "library/= " + (Get-ChildItem $r -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'library') }).Count
  "books/  = " + (Get-ChildItem $r -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'books') }).Count
  "out/ocr*= " + (Get-ChildItem $r -Directory | ForEach-Object { Get-ChildItem (Join-Path $_.FullName 'out') -ErrorAction SilentlyContinue } | Where-Object { $_.Name -like '*ocr*' }).Count
  "project.json = " + (Get-ChildItem $r -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'project.json') }).Count
}

# 2) literature 行的来源分档与 library/ 体量（§3.3 / §2 第 15 条）
#    见 §3.3 的两条 python -B -c；library/ 体量：
foreach ($r in $roots) { $n=0;$b=0; Get-ChildItem $r -Directory | ForEach-Object { $l=Join-Path $_.FullName 'library'; if (Test-Path $l) { Get-ChildItem $l -Recurse -File | ForEach-Object { $n++; $b+=$_.Length } } }; "$r files=$n bytes=$b" }

# 3) B.ingest_local 的 10 次拒绝（§3.2）
#    见 §3.2 的两条命令

# 4) 装配面 / 动作表 / 原生工具面（§3.1）
cd D:\Incubator\agentflow
python -B -c "import sys;sys.path.insert(0,'src');import agentflow.tools as T;print([(s.name,s.roles,s.side_effect,s.declared_external) for s in T.build_registry().registry.for_role('B')])"
python -B -c "import sys;sys.path.insert(0,'src');import agentflow.capabilities as C;print([a.action for a in C.actions_for('B')])"

# 5) 测试覆盖（只数函数，不跑 pytest —— 本轮未跑）
foreach ($t in 'test_locallib.py','test_local_corpus_flow.py','test_projects.py','test_intake_actions.py','test_search_offline.py','test_tools_search_ocr.py','test_f4_ocr_detect_reason.py','test_demo_end_to_end.py') {
  "$t : " + (Select-String -Path "tests\$t" -Pattern '^\s*def test_').Count + " test funcs"
}

# 6) 磁盘上的"书柜"仍在（这是历史事实，不是框架入口）
Test-Path D:\books; Get-ChildItem D:\books | Measure-Object -Property Length -Sum
```

## 5. 边界与未核实项（如实列出）

1. **未跑 pytest**：本报告所有 `tests=` 计数都是**静态数函数**，不是"跑绿了"。因此"某条判据是否已抓住某处不一致"一律标为**未核实**（§3.3 的 provenance 那条是典型）。
2. **`draft/28:19199` 记的"本地书架 `search.local` 通关"现场**在当前两个根里**找不到**对应会话（`search__local` 调用 0 次）。是"当时的工作区已被清理"还是"那条读数另有出处"，**未核实**。
3. **`out/ocr*` 目录 = 0 个**：两个根里没有任何以 `ocr` 命名的产物目录。也就是说"OCR 产物"这件事在真机上**从来没有落过盘**（与 §3.1 的 0 次调用互相印证）。
4. **`books/` 目录 = 0 个**：两个根都没有 `books/`；`--books` 指向的三个目录（`D:\books`、`D:\Incubator\temp\one-book`、`D:\Incubator\temp\scan-only\books`）都在**交付物之外**，其中只有 `D:\books` 今天仍在盘上（7 个 PDF / 33.8 MB）。
5. **未真跑 OCR、未联网、未真跑模型**：所有"本机无可用 OCR 后端"的结论**引自模块自述与 `draft/11` §8 的实测**，本轮没有独立重测 `easyocr` / `pytesseract` 的可用性。
6. **`search.ingest_local` 的 provenance 与 docstring 相反**这一条，我只核到"handler 不传三参数"（`tools/search_tools.py:923-946` 的调用点）；`tests/test_intake_actions.py` 里是否有用例把它钉住，**未核实**。
7. **未修改仓库任何文件**：本报告的读数脚本写在 `D:\Incubator\`（工作区，不是 `agentflow/` 仓库内），报告写在 `D:\Incubator\draft\43-旧设计调查-B-图书馆与OCR时代.md`。
