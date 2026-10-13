# docs/ —— 索引

> **本目录只放"判据性"文档**（规范、规格）。设计理由在仓库根的 `DESIGN*.md`；
> 开发期探针在仓库根的 `tools/`；**一键发布检查的入口也是 `tools/release_all.py`**
> （它调用 `scripts/release_check.py` 那八项，并在外面补上**验收测试**与论文复现 ——
> 因为 `release_check.py` 在禁改区，加一项要人审，见 `PROPOSALS.md` P-11）。
>
> 📍 **要先看清"系统现在长什么样"**：读仓库根的
> [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)
> —— 七层结构逐项写明，**每一条都带工作区相对路径（相对 `D:\Incubator`）**，并给出每个数字的复跑命令。
> 它是导读、**不构成判据**。
>
> **路径约定**：本目录里的 `../src/agentflow/...`、`../tools/...` 相对 `agentflow/`；
> 换成相对工作区根（`D:\Incubator`）就是 `agentflow/src/agentflow/...`、`agentflow/tools/...`。
> 正文（`draft/35`）一律用**工作区根相对**的写法。

| 文件 | 是什么 | 读者 | 权威顺序 |
|---|---|---|---|
| [`ROLE-SPECS.md`](ROLE-SPECS.md) | **九个角色 + 主控（M）的详细规格**。每节 10 个子节（其中 8 个是结构门要求的**必备**子节）：定位 / 职责 / 明确不负责 / 工具面（逐条契约）/ 状态机（迁移表）/ 预算与终止条件 / 三态与失败模式 / 不变式 / 接口 / 自检入口 | 实现者（改哪个角色读哪节）、审计者、文档维护者 | 低于代码与 `DEVELOPMENT.md`，高于 `DESIGN*.md` |
| [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) | **FC-27 门的机制与人工批准流程**：三种结论与退出码、"登记 ≠ 批准"、hash 台账为什么比 git 更强（能抓"批准后被改"）、台账自指禁止、以及**本机制做不到的事** | 要改动禁改区的人、发布者、评审者 | 与 `../AGENTS.md` 同级；机制细节以本文为准，清单以 `../.noai-paths` 为准 |
| [`PROPOSALS.md`](PROPOSALS.md) | **已裁决的缺口与提案**。三类分开列：**P**（要改禁 AI 区的提案）/ **G**（已接受的缺口，**必须继续出现在报告里**）/ **N**（看起来像缺陷、经核查是刻意设计）。每条都带"为什么不由 AI 自己做" | 发布者、评审者、发现机械报告里有 warning 的人 | **不构成判据**；但它记录的判定会被 `DEVELOPMENT.md` 与 linter 引用 |
| [`FORMAL-TOOLCHAIN.md`](FORMAL-TOOLCHAIN.md) | 形式化后端（Lean / Mathlib）的工具链口径与"没查成"的记法。**§6 是机器级设置文件的逐字口径**（落点、`toolchain.*` 键名、优先级、三道 key 安全阀） | 用 E 的形式化路径的人 | 低于代码（实现 `../src/agentflow/toolchain.py`） |
| [`READING-MAP.md`](READING-MAP.md) | **七层与各自的文件 + "想改什么 ⇒ 读哪几个文件"**（3 跳以内）+ §3"这些文件为什么这么大"+ §4 判据在哪。它的判据是 `../tests/test_reading_map.py`（图里每个文件名都要真实存在；`src/agentflow` 每个模块都要在图里有位置；§3 的行数不许过期） | **第一次读这个仓的人**、要定位某个改动该读哪几个文件的人 | **不是判据**；它指到哪里就以哪里为准（过期的图比没有图更坏 ⇒ 有判据守着） |
| [`SCHEMA-DRAFT-management.md`](SCHEMA-DRAFT-management.md) · [`SCHEMA-MIGRATION-PROPOSAL-claims.md`](SCHEMA-MIGRATION-PROPOSAL-claims.md) · [`SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`](SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md) | 表结构与迁移提案（磁盘格式契约的**提案**，不是现状） | 要动表结构的人 | **不构成判据** |
| [`ROLE-SPECS-DRAFT-N-O-Q.md`](ROLE-SPECS-DRAFT-N-O-Q.md) · [`ROLE-SPECS-DRAFT-V.md`](ROLE-SPECS-DRAFT-V.md) · [`TOOLBOX-DRAFT-roles.md`](TOOLBOX-DRAFT-roles.md) | 角色与工具栏的草案（讨论稿）。**V 那一份的原任务（"进默认角色集"）已落地** ⇒ 角色 V 的判据是 `ROLE-SPECS.md` §V，草案只剩过程留痕 | 规格维护者 | **不构成判据** |
| [`PROPOSAL-side-effect-axes.md`](PROPOSAL-side-effect-axes.md) | 副作用第二根轴（`external`：`egress` / `exec`）的提案与落点清单 | 要动工具声明的人 | **不构成判据**；现状见 `../src/agentflow/tools/base.py` 与 `../DEVELOPMENT.md` |
| [`NOAI-CHANGE-LIST-management.md`](NOAI-CHANGE-LIST-management.md) · [`NOAI-SUSPENSION-2026-09-25.md`](NOAI-SUSPENSION-2026-09-25.md) · [`NOAI-SUSPENSION-2026-09-28.md`](NOAI-SUSPENSION-2026-09-28.md) | 禁改区的变更清单与两次暂停记录（历史档案） | 审计者 | 历史档案；当前值以 `.noai-approvals.json` 与 `DEVELOPMENT.md` §0.3 为准 |
| [`USER-END-DSH-STYLE.md`](USER-END-DSH-STYLE.md) | **用户端设计依据**：抄 DSH 的**皮**（两层令牌 + 明暗两套、界面纪律三条、接口形状，逐条带出处与 MIT 声明）；**运行时协作纪律用我们自己的**（`DESIGN-CONDUCTOR` §1.1 用户只对主控说话 等，逐条带本项目出处）；DSH 的提问/审批纪律降级为**参考读物（不构成我们的规则）**；并把**开发时纪律**与**运行时协作纪律**分节划开（用户 2026-10-03 的纠正）。**§3.1 是九个页面各自读什么**（路由 / 端点 / 栏位 / 空态 / 三态 + 缺口清单；2026-10-07 W1 落地，后三页 2026-10-13）；前端工程自己的说明（装依赖 / `pnpm build` / dist 入库的规矩）在 `../ui/README-DEV.md` | 改用户端（人机通道 / GUI / 九个页面）的人、评审者 | **设计依据，不构成判据**；判据在 `../tests/test_user_channel_*.py` 与 `../tests/test_webui*.py`（契约 A–D / 每页一条 / 流 / 静态与 `/` 的外壳） |
| [`USER-TEST.md`](USER-TEST.md) | **人实测清单**：零成本自检（32 条判据）→ 造工作区 → 起网页 → 跑一趟真机（它会停在等你回答，退出码 3）→ 你答（网页或终端）→ 接着跑（同一趟继续 或 `--resume`）→ 验两道门 → 无人值守档；逐节标明"我跑过"与"要你跑"，含两个实测踩到的路径陷阱（`PYTHONPATH` 必须绝对、`--project-dir` 按当前目录解析） | 要亲手试一遍用户端的人 | **不是判据**；命令与"该看到"都是实测产物 |
| [`USER-TEST-TASK.txt`](USER-TEST-TASK.txt) | 上面那份清单里 §3/§5/§7 喂给 `run-agent --task` 的**任务原文**（11 条，逐字副本；第 8 条要求"关键取舍用 ask_user 问一次，然后停下等回答" ⇒ 真机那一趟**应当**会问） | 要复跑同一趟真机的人 | **不是判据**；它是输入数据，改它等于换任务 |
| [`USER-TEST-TASK-QUOTE-FORMAL.txt`](USER-TEST-TASK-QUOTE-FORMAL.txt) | 同上，但**点名要求两条腿**的版本（13 条）：**(A) 引文逐字回验**（每条引用带 `quote`/`page_range`/三态 `quote_verified`，不是 true 必写 `quote_reason`，收尾给"真/假/未查"三个数）与 **(B) 形式化验证**（`method="formal"` 只吃 `.lean` 产物；本机无检查器 ⇒ 允许的结论是"没核到 + 理由"，**不许**写成通过，也**不许**把 `evidence_kind` 写成 `proof`，另派一条计算类实验作旁证）（2026-10-07 补：那两句括号里写的"检查器在 `temp\lean470\…`、启动前把它加进 PATH"是**当时**的落点与玩法 —— 机器环境已搬到工作区根的 `_env/`，而现在检查器在哪由设置文件给（`toolchain.lean_bin`，见 `FORMAL-TOOLCHAIN.md` §6 与 `../settings.example.json`）。**上面那份输入数据本身刻意不改**：它是一次真机运行的输入，改它等于换实验输入。） | 要跑"要求引文查询与形式化验证"那一趟的人 | **不是判据**；它是输入数据。第 (B) 条：**检查器在盘上但不在 PATH**（Lean 4.7.0 在 `temp\lean470\lean-4.7.0-windows\bin`，commit 与框架钉住的相同）—— 启动前把它加进 PATH 就能真验（实测出 `verified` / `evidence_kind=proof`），不加就只能如实报"没核到 + 理由"；Mathlib 那一档今天不行（umbrella 的 `.olean` 缺失）。**它把"该怎么派活"全写明了 —— 只能当对照基线用** |
| [`USER-TEST-TASK-NAIVE.txt`](USER-TEST-TASK-NAIVE.txt) | **"什么都不懂的用户"版**（5 段）：只说"我要什么"（审这篇论文并改好 + 两份交付）、两件不放心的事（引文是不是真引对了、定理能不能用机器验）、预算 10 美元、看不懂过程所以要说清"查了什么/结果/哪些没查成/为什么"、拿不准就来问我 —— **一个动作名、一个工具名、一个步骤都不给** | 要考"主控自己分析并派发"这件事的人 | **不是判据**；它是输入数据。它与上面那份详细版是**同一件事的两种问法**：能不能不靠手把手的步骤把活派对，是这一趟要量的东西；派不动就是要加强的地方 |

**本目录的结构完整性有一道门**（`tools/verify_role_specs.py`，退出码 0/1/2）：
`ROLE-SPECS.md` 必须保持"10 个角色节（A–H + V + M）× 8 个必备子节"齐全，
且每节的工具条数要与**真的跑一次** `python -m agentflow.cli tools` 对得上。
改 `ROLE-SPECS.md` 的章节结构后请复跑它（`DEVELOPMENT.md` §8.6）。

**规范与门的一致性也有断言**（在 `tests/test_lint_rules.py` 里）：
① 每条 lint 规则都挂进了 `RULES` 且编号连续无洞；② 每条规则都在 `DEVELOPMENT.md` §6
的禁止模式表里出现过；③ **反向**：§6 里写的 `R0NN` 编号必须真的有对应规则。
第 ③ 条防的是"规范承诺了一个不存在的门"——那是最坏的一种虚证：读者以为有自动判据，
于是**人不再去看**。

**不在本目录但属于同一套判据的文档**：

| 文件 | 是什么 | 备注 |
|---|---|---|
| `../DEVELOPMENT.md` | **项目开发规范**（六条硬纪律 / DoD / 测试规范 / 禁止模式 / 提交评审 / 发布检查 / FC 覆盖矩阵 / 文档不一致清单） | **本套文档的主入口** |
| `../AGENTS.md` | 禁 AI 区（FC-27）硬约束 | **只覆盖这一节**；与 `../.noai-paths` 逐条一致（`scripts/noai_gate.py --check-consistency`） |
| `../NOAI-REVIEW-REGISTER.md` | **FC-27 人工复核登记表**（人读）：这一轮改了哪些禁改区文件、复核人该逐行走查哪些符号、批准栏 | 机器可读部分在 `../.noai-approvals.json`；**批准只能由人签** |
| `../DESIGN.md` `../DESIGN-TOOLS.md` `../DESIGN-INTERACTIONS.md` `../DESIGN-ROLES.md` `../DESIGN-CONDUCTOR.md` | 设计**理由**（"为什么"） | **不构成判据**；与代码冲突时以代码为准 |
| `../README.md` | 使用说明（怎么跑、当前已知限制、目录结构、数据文件速查、发布门状态） | **不构成判据**；与代码冲突时以代码为准（该文件 §7 已声明这一点） |
| `../settings.example.json` | **机器级设置文件的示例**（本机工具链落点 / Mathlib 根 / 模型 key / `workspace.projects_dir`）：把它复制成同目录的 `settings.json`（那份被 git 忽略）再改值。逐字口径见 `FORMAL-TOOLCHAIN.md` §6 与 `../src/agentflow/settings.py` 的模块 docstring | **示例，不构成判据**；判据在 `../tests/test_settings.py`（含"真正那份既不在索引里、也确被忽略"与"示例里没有真 key"） |
| [`../../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md) | **现状描述正文**：七层结构逐项写明，每条带工作区相对路径（相对 `D:\Incubator`）+ 复跑命令 | **不构成判据**；它是"拿着一张表逐条核对代码"的入口 |

## 怎么读（按角色）

| 你是 | 读什么 | 顺序 |
|---|---|---|
| 第一次接触这个仓库 | `../DEVELOPMENT.md` §0（现状快照）→ §1（阅读顺序）→ §3（六条硬纪律） | 1 → 2 → 3 |
| 想先看清系统全貌 | `../../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`（七层结构 + 逐项路径）→ `../DEVELOPMENT.md` §0 | 1 → 2 |
| 要改某个角色 | `../DEVELOPMENT.md` §4.5（角色 DoD）→ `ROLE-SPECS.md` 对应那一节 | — |
| 要加一个工具 | `../DEVELOPMENT.md` §4.3（工具 DoD）→ `ROLE-SPECS.md` §R0（全局工具总表，看格式） | — |
| 要加一个验证门 | `../DEVELOPMENT.md` §4.6 + §5.1（一正一反） | — |
| 要发布 | `../DEVELOPMENT.md` §7（提交与评审）+ §8（发布检查）+ `../AGENTS.md` | — |
| 要审计 | `../DEVELOPMENT.md` §4（DoD 逐条质问）+ §9（FC 覆盖矩阵的**三档**状态）+ `ROLE-SPECS.md` 各角色的 §不变式 | — |

## 两条**引用纪律**

1. **数字必须有出处**。本文档里每个数字都指向 `文件:行号` 或某次实跑的**命令 + 输出**。
   引用 `temp/inventory/INVENTORY.md` 时**必须写条目编号（如"INVENTORY 4.3(a)③"），
   不许写行号** —— 那份清单普查的是 `test/test1/abflow`，行号与 `agentflow` 不同
   （口径警告见 `../DEVELOPMENT.md` §1.4）。
2. **三档状态**：`已落地` / `部分` / `未落地`，另加 `未核实`。
   **不许把"未核实"写成"已落地"**。每一条"未核实"都必须说明"我查了什么、缺什么"
   （见 `ROLE-SPECS.md` 附录 S1 与 `DEVELOPMENT.md` §9.3）。
