# draft/ —— 交付报告索引

> 本目录为本次工作的**最终交付物**，按七个阶段共 **22 份中文报告**：
> ① 调研（01–09）；② A/B 原型（10）；③ 工具层与 C/D（11）；
> ④ A–H 交互补全与验收（12）与**正式设计草案（13）**；
> ⑤ 本地先例对照（14–16）、**正式文稿体例（17）**、**正式版实现与验收报告（18）**；
> ⑥ **代码风格清洗报告（19）**；⑦ **管理层与责任链的重设计草案（20）**、**升级方案（21）**、
> **企业级交付与竞争力方案（22）**。
> 过程性文件（下载物、脚本、证据摘录、检索笔记、独立复核实现）全部在 `../temp/`，说明见 `../temp/README.md`。
> 原型与验收代码在 `../test/test1/`（框架）与 `../test/test2/`（独立复现规格 + 验收程序）。
> **第五阶段的正式版代码在 `../agentflow/`**（包名 `agentflow`；原型保持不动）。
>
> ⚠️ **`../agentflow/` 才是"正式版"**。本目录的报告多数描述 `test/test1`（原型）；
> 描述正式版的是 **17**（体例参考）与 **18**（实现与验收）。
> 正式版自己的规范入口是 `../agentflow/DEVELOPMENT.md`，角色规格是 `../agentflow/docs/ROLE-SPECS.md`。

**采集时间**：2026-09-23
**环境**：Windows / pwsh / Node v24.16.0 / DeepSeek Harness 0.1.5-rc.2（本机安装）、master 分支完整源码工作树

---

## 一、总览

| # | 报告 | 规模 | 引用来源 | 一句话定位 |
|---|---|---|---|---|
| 01 | [`01-deepseek-harness-仓库结构调查报告.md`](01-deepseek-harness-仓库结构调查报告.md) | 1,868 行 / 141 KB | 61 | 用 240 个 npm 包的 `repository.directory` 字段 + master 真树重建 DSH monorepo 全貌 |
| 02 | [`02-多智能体协作协调方法综述.md`](02-多智能体协作协调方法综述.md) | 699 行 / 77 KB | 192 | 大厂论文里的多智能体协调范式，大白话版；含 7 处常见错误归属的修正 |
| 03 | [`03-智能体组成要件与功能报告.md`](03-智能体组成要件与功能报告.md) | 1,247 行 / 129 KB | 25 | 智能体 13 项组成要件的逐项拆解 + DSH 全量映射（rc.2 列 / master 增补列对照） |
| 04 | [`04-智能体并发模式与实现报告.md`](04-智能体并发模式与实现报告.md) | 2,564 行 / 240 KB | 164 | 12 种并发模式 + 8 类并发机制 + 9 组系统对照 + 32 条反模式 |
| 05 | [`05-智能体工作区-权限-工具栏精细化配置报告.md`](05-智能体工作区-权限-工具栏精细化配置报告.md) | 2,877 行 / 245 KB | 10 | 工作区/沙箱/审批/工具栏的精细设定方法与配方 |
| 06 | [`06-基于DeepSeek-Harness的最小可用智能体构造方法研究报告.md`](06-基于DeepSeek-Harness的最小可用智能体构造方法研究报告.md) | 2,370 行 / 135 KB | 17 | 从 18 行最小插件集到三条可复制构造路径，**含实机跑通的实验** |
| 07 | [`07-大型编程项目开发规范调查报告.md`](07-大型编程项目开发规范调查报告.md) | 1,512 行 / 158 KB | 187 | 大厂规范 + 高赞避坑帖 + Vibe Coding 专题 + 25 条反模式黑名单 |
| 08 | [`08-数学自动化定理证明调查报告.md`](08-数学自动化定理证明调查报告.md) | 2,289 行 / 245 KB | 379 | ATP 全景 + LLM×形式化 8 种范式 + 20 个代表系统 + 三档资源路线 |
| 09 | [`09-DeepMath团队智能体项目调查报告.md`](09-DeepMath团队智能体项目调查报告.md) | 1,196 行 / 115 KB | 89 | DeepMathLLM 团队与其智能体项目的实地调查（含 3 个仓库克隆 + API 元数据 + PR 记录） |
| 10 | [`10-A-B多智能体文献流水线-设计与初步构造报告.md`](10-A-B多智能体文献流水线-设计与初步构造报告.md) | 8,445 行 / 512 KB | — | **阶段②**：A（文献检索）/ B（文献整理）的可运行原型 —— 设计 13 节 + 4 附录 + 完整缺陷表 |
| 11 | [`11-工具层与智能体C-D-设计与实现报告.md`](11-工具层与智能体C-D-设计与实现报告.md) | 1,004 行 / 55 KB | — | **阶段③**：工具层契约（`ToolSpec`/`side_effect`/角色权限面）+ C（关系分析）/ D（研究）实现 + **评审误判案例复盘** |
| 12 | [`12-第四阶段-A到H交互补全与main.pdf独立复现验收报告.md`](12-第四阶段-A到H交互补全与main.pdf独立复现验收报告.md) | 679 行 / 49 KB | — | **阶段④**：A–H 八角色 + I1–I12 交互补全、`main.pdf` 的**独立复现验收（10/10 阶段通过）**、独立第二实现复核（101 项检查、三分档分布）、**实测缺陷档案** |
| 13 | [`13-数学研究多智能体协同框架-正式设计草案.md`](13-数学研究多智能体协同框架-正式设计草案.md) | 1,175 行 / 98 KB | — | **正式设计草案**：8 角色规格 / 12 张表与硬约束 / I1–I12 规格 / 横切机制 / **FC-01…FC-27 覆盖矩阵（含 6 条未落地）** / 缺陷档案 / 已知边界 / P0–P2 路线图 |
| 14 | [`14-本地先例对照-Danus.md`](14-本地先例对照-Danus.md) | — | — | 只读观摩 `C:\Users\ysc20\Danus`，21 条可取用 + 10 条不该学 |
| 15 | [`15-本地先例对照-dsh数学模式与DeepMath.md`](15-本地先例对照-dsh数学模式与DeepMath.md) | — | — | 只读观摩用户自写的 dsh「数学模式」preset 与 DeepMath 克隆：10 条可取用 + 10 条不该学 |
| 16 | [`16-本地先例取用记录.md`](16-本地先例取用记录.md) | — | — | **到底改了哪几行**：采纳 6 个具体机制 + 9 条明确不采纳的理由 |
| 17 | [`17-正式文稿体例（参考投影度量论）.md`](17-正式文稿体例（参考投影度量论）.md) | 1,160 行 / — | — | **正式文稿体例**（只读观摩 `C:\Users\ysc20\Desktop\投影度量论`）：目录与命名 / 章节模板 / **断言台账的 10 字段解剖学** / 勘误体例 / **22 个检查脚本各自防什么错** / **H 的 G1–G15 门** / 对我们 G/H 的落地建议 / 不适合照搬的体例 / 没能核实的 15 项 |
| 18 | [`18-第五阶段-正式版实现与验收报告.md`](18-第五阶段-正式版实现与验收报告.md) | — | — | **阶段⑤**：`agentflow/` 正式版的实现与验收 —— 主控编队（10 条不变式）/ **本轮关键裁决逐条含代价** / linter 的四次校准 / **禁 AI 区的 hash 台账** / G/H 升级 / 机械验证实测 / 对 `main.pdf` 的独立复现 / **没做到与没核实的清单** |
| 19 | [`19-代码风格清洗报告（vibe coding 忌讳）.md`](19-代码风格清洗报告（vibe coding 忌讳）.md) | — | — | **阶段⑥**：清"vibe coding 忌讳" —— 区外 **2207 处**注释/docstring 装饰归零（含**清洗工具自己的一个真缺陷**：写盘判据取自报告 ⇒ 11 个文件静默漏清，P16 形态）/ 新增 **linter R009** 挡回归（立项前四类候选的假阳性率实测）/ **逐类审计**：通用名 53、复述式注释 14 命中 0 真、未用 import 29（含"脚本判据会拆掉单一来源"的反例）、长函数 184、字符串字面量 1522 **刻意不动** / 人的待办 4 项 |

| 20 | [`20-管理层与责任链的重设计草案.md`](20-管理层与责任链的重设计草案.md) | — | — | **阶段⑦（草案，评审已落定）**：用管理学把 A–H"员工"以上的**管理层**设计出来 —— 七功能逐项体检（`分析现状`/`制定计划`/`派发任务`/`交叉审核`/`员工协作`/`资源倾斜`/`状态更新` 全仓 **0 命中**）/ **九个结构性缺陷**（三分层塌缩、自评自报、统一指挥被无边界横向扩张破坏…）/ 目标组织 **四条线 × 三层**（N 现状官 + O 计划官 + Q 内审 + 确定性周期驱动）/ **决策权 RAPID 矩阵 + 监督矩阵 + 无人可自审** / 关键实测：**`Conductor` 在生产路径上没有任何调用方 ⇒ 召唤台账根本没被写** / §12 九条裁决逐条含代价（Q6/Q8 与建议不一致 ⇒ 带可机械检查的补偿控制）/ §12.6 **S0 验收当场抓到的命名撞车**（`attack_plans.plan_id` 已存在 ⇒ 改名 `mgmt_plans`/`mplan_id`/`mgmt_plan_id`）/ §13 分步验收标准（S0–S3 实测全绿）/ §14 **角色工具箱**（实测 D/F/G/H 各持 19–25 个原子工具、机械占比 72–95% ⇒ 加一层任务级聚合工具 + 默认路径/下钻分离 + 6 条判据 + 反模式 P18）/ 变更账**含删除清单** |

| 21 | [`21-管理层与工具箱升级方案（工期与交付标准）.md`](21-管理层与工具箱升级方案（工期与交付标准）.md) | — | — | **阶段⑦的执行契约**：24 件交付物 + 双轨工期（AI ≈14 轮 / **人审 45.5 人时（期望）**，关键路径是禁改区人审排队）+ 甘特与三档日历（乐观 2 周 / 期望 3–4 周 / 悲观 6–8 周）+ M0–M7 逐里程碑 DoD 勾选清单 + **23 条验收命令与期望退出码**（12 条"现在"、11 条"里程碑后"）+ **"不算交付"的六种形态** + 变更控制与版本规则 + 方案自我验收（实跑 now 行比对退出码，含三条负控） |

| 22 | [`22-企业级交付与竞争力方案（200万预算）.md`](22-企业级交付与竞争力方案（200万预算）.md) | — | — | **立项级方案（取代 21 号的优先级）**：12 维成熟度实测评分（**6 个维度是 L0**，最致命的一条：全仓 `API_KEY\|httpx\|base_url` **0 命中 ⇒ 系统里没有任何一次真实模型调用**；形式化验证只探测不执行；无评测 runner；无部署；非 git 仓库）+ 目标写成 8 条可测指标（端到端/可复现/成本熔断/可验证产物数/引文零幻觉/基准标口径/人工介入率/单位经济）+ **竞争定位（不拼基础模型与算力；拼可验证性、引文零幻觉、细分领域可合并进 Mathlib 的引理）** + 目标架构（模型网关/沙箱/Lean 4 验证后端/DB/评测台/观测/RBAC）+ 6 工作流 6 人 20 周五阶段 + **200 万预算分配与 API 成本估法（可复核）** + 企业级 DoD + **4 条止损线** + 不承诺清单 + 5 项待裁决 |

**合计**：22 份报告；01–13 共 **27,925 行 / 约 2,198 KB**（14–22 的规模见各自文件）。
（阶段① 的 9 份报告另有 **506 个代码围栏全部闭合**、**1,124 处 URL 引用**的统计，见下节；
各报告均含独立参考文献/来源清单。）

---

## 二、各报告要点

### 01 · DeepSeek Harness 仓库结构调查

**方法学亮点**：GitHub 在本机被 hosts 劫持无法访问，于是改用**两条不依赖 GitHub 的通路**交叉验证：
1. 每个已发布 npm 包的 `package.json` 都带 `repository.directory` 字段 → 用 240 个包**无损重建** `packages/` 的 46 个 group（0.1.5-rc.2）
2. 再通过镜像网关取到 **master 分支完整工作树**（13,081 文件）做三方版本比对

**关键结论**：
- 顶层目录：`apps/ · packages/ · vendor/ · native/ · docs/ · scripts/ · python/ · patches/ · website/ · benchmarks/ · snapshots/ · .agents/ · .github/`
- `packages/<领域>/<功能>` 双层命名；master 在 `packages/` 下有 **54 个 group / 307 个 group 级包**（另有 9 个嵌套在 `typert/generator/tests/fixtures/**` 与 `preset/agent-preset/skills/**/templates/**` 中的测试夹具/模板清单，合计 316 个 `package.json`）；rc.2 为 46 / 240 —— 存在真实版本漂移；**54 个 group 每个都带 `README.md`**（官方称之为"该能力族的权威包地图"）
- `vendor/` 是内嵌的 Cordis 插件体系（`@deepseek-ai/cordis` 4.0.2 等独立版本线）
- **License 定论：MIT**（鲸智社区标的 apache-2.0 是第三方元数据错误，已用**五处**独立一手证据否证：GitHub API `license.spdx_id`、仓库根 `LICENSE` 全文、仓库 `README`、根 `package.json`、npm 包内 `LICENSE`）
- 仓库根**没有 `config/` 目录**
- 仓库元数据：主语言 **TypeScript**、约 210 MB、默认分支 `master`、**不开放 Issue**（改用 Discussions）、创建于 2026-08-13、star 23.4 万 / fork 2.8 万、homepage `deepseek.com/harness`、topics `ai-agents/cordis/dsh/dsh-plugin`

**基于 master 真树的升级（新增第 11–16 节）—— 三方版本差异表是本报告的核心增量**

| 维度 | M = master | L = 0.1.5-rc.2 | G = 0.1.0-rc.5 |
|---|---|---|---|
| group 数 | **54** | 46 | 48 |
| 包数 | **307**（+9 个嵌套夹具 = 316 个 `package.json`） | 229 已发布 | — |
| 工作树文件 | 13,229 | — | — |

- **M 净新增 9 个 group**：`experimental`(20 包)、`ssh`、`lsp`、`browser-use`、`computer-use`、`ptc-runtime`、`deliverables`、`document`、`test-support`(7 包)；`code-runtime` 与 `examples` 两个 group 消失
- `client` 46→59、`session` 18→20、**`subagent` 6→10**（新增 acp / codex / claude-code / dsh-sdk 四个**跨产品子代理后端**）；`apps` 2→4（+`desktop`、`desktop-host`）；`vendor` 9 包统一小幅升版；`bundle` 仍 6 个但 `sdk-app` 的 patch **+134.6%**
- ⭐ **两条影响全报告集判断的新发现**：
  1. **`configTrees` 机制在 master 已退役** —— `apps/cli/package.json` 的 `dsh` 字段整体消失；该字段降级为**镜像打包器内部能力**（`packages/experimental/webworker-packer`），其 README 原文明确 *"This field is not part of the public plugin manifest API"*，且因 CLI 不再声明，打包器分支在 master 上拿到**空集**（保留但未启用）。
  2. **preset 从"目录内联 + configTree 扫描"重构为"声明式 Cordis YAML + `ctx.agentPresets` 注册表"** —— `packages/preset/{agent-preset, agent-preset-registry, persona}`，新增 revision retention，内嵌 skills 由 2 篇增至 3 篇。
- **附带澄清**：`mount: "config/agent-presets"` 是**运行时挂载点名称**（即 `$DSH_HOME/config/agent-presets`），**不是仓库路径**；`path: "../../packages/preset/agent-presets/presets"` 是相对 `apps/cli` 的 **monorepo 构建期路径**。而 `apps/cli/config/` 这个目录在 G 与 M 之间**完全换过内容**：G 含 `agent-presets/`，M 只含 `examples/`（`github-review` / `mcp-memory` / `schedule`）。
- **关闭 9 项缺口**：54 份 group README（第 13 节转录 10 个核心 group 的 `package → role → ctx key` 权威表）、`docs/architecture.md` 全文（第 12 节，含 turn/step 流程图与"新行为放哪里"路由表）、`module-graph.md`（119.7 KB mermaid peer 图）、20 个 CI workflow（第 14 节，总结出"dsh / vendor / native / Python 各自独立发布"）、`assets` 消失、`config/examples` 列全、`client` 清单、未发布包归属、仓库元数据。
- **剩 5 项缺口**：0.1.5-rc.2 的精确 commit 快照、master 无 `.git` 故无 SHA、约 130 个 symlink 文件解压失败（仓库存在、本地未解出）、`.gitlab-ci.yml` 未读、307 份包级 README 只精读约 12 份。

---

### 02 · 多智能体协作协调方法综述（大白话版）

**6 大协调范式**（每种含 ASCII 拓扑 + 代表系统 + 优点 + 坑）：流水线/SOP 分工 · 中心化编排者 · 辩论与投票 · 去中心化 P2P + 通信拓扑裁剪 · 动态路由与 handoff · 层次化嵌套。

**最有价值的产出 —— 7 处常见错误归属的修正**（这批修正在中文资料里广泛流传）：
1. ChatEval 是 **2308.07201**，不是 2305.19118（后者是 Liang et al. MAD）
2. GPTSwarm **2402.16823** · DyLAN **2310.02170** · AgentPrune **2410.02506**（三个 ID 都被广泛传错）
3. **CrewAI 没有 arXiv 框架论文** —— 流传的标题无法证实，报告明确禁止引用
4. Guo et al. 综述是 **2402.01680**
5. FORD「Inter-Consistency」是 **Xiong et al. 2305.11595**
6. **CrewAI 未被 MAST 研究**；其 7 框架为 ChatDev/MetaGPT/HyperAgent/AppWorld/AG2/Magentic-One/OpenManus
7. MAST 干预收益 v1 是 +14%、v3 是 **+9.4%**，且属提示词/编排改动，**不是**"LLM 裁判验证器"的提升

**诚实留白**：DeepSeek 未检索到多智能体协调论文（检索性否定）；Meta 仅有 FAIR 的 Matrix 等，无 MetaGPT 级代表作 —— 对比表**留空未编造**。

---

### 03 · 智能体组成要件与功能报告

**结构**：定义谱系（AIMA → RL → ReAct → LLM 工程定义，含 3 处学派分歧）→ **13 项要件**逐项拆解（每项固定"是什么 / 为什么 / 典型实现 / 常见坑 / 举例"五视角）→ ASCII + Mermaid 解剖图 → 必须/更好/生产三档清单（35 条）→ 6 种形态对照表 → DSH 全量映射。

**实测结论（检索性否定，很有价值）**：
- **不存在 `dsh-memory`**：全量包名 + 描述正则扫描，无任何 `memor`/`recall`/`embed`/`vector`/`RAG` 包 —— 该否定经 master 深挖后**跨 `0.1.5-rc.2` 与 master 双版本成立**（307 包 `name`+`description` 全量扫描 + `persistence-catalog` 无 `memory/*` 事件域，**两条独立证据**）
- DSH 的"记忆"= 会话日志 + 投影 + storage 域 + spill + session-reference + skill；长期语义记忆需经 `dsh-mcp-client` 外挂
- ⭐ **`config/examples/` 的结论已更正并升级为大发现**：rc.2 根 README 提到的"记忆 MCP 服务"overlay **确实未随 npm 发行包发布**（发行只带 `lib/`），**但它存在于 master 源码树** `apps/cli/config/examples/mcp-memory/` —— 含**三份可直接 `--patch` 挂载的参考配置**：官方 `@modelcontextprotocol/server-memory@2026.7.4`、**Engram v1.20.0**、**Memorix 1.3.0**（全部走 `dsh-mcp-client` + `transport: stdio`），配套官方指南 `docs/user/guide/mcp-memory.zh.md`。
  → 报告据此把"记忆"一节从"**没有**"升级为"**没有内置，但有官方指定的外挂范式 + 三个参考实现**"，并提炼三条设计哲学：*DSH starts it but does not run a package manager*（只负责启动、不管依赖安装）／*storage and project selection remain Engram-owned*（存储归外部服务所有）／记忆是"外部进程 + stdio 协议"形态而非框架内模块。官方明示参考服务器"**不是语义检索**"，不提供 embedding、自动摘要、冲突消解或遗忘策略。
- 同目录另两个示例给出**横切能力的可运行接入范式**：`schedule/`（同一行 insert + 把 `ui-schedule` 由 `disabled` 翻为 `false`）与 `github-review/`（**isolated realm 下的第二个 WebServer**，注释原文 *"exposing it never exposes the UI API"*，并带 `permissionPreset: read-only`）。

**新增 §9（master 侧官方目录级证据）**：官方工具目录（含生成方式 + 30 行官方映射表）、官方工具执行流水线**九段模型**、⭐ **能力 seam 三角框架**（Service Definition / Provider / Consumer —— 它解释了 DSH 的组织原理**本身就是"组成要件"**）、token 计量的精确语义、三种官方外挂范式。
**版本更正共 8 条**（§9.7 逐条列举）：`browser-use` / `computer-use` / 语音输入（rc.2 无 → master 有，**均默认禁用的实验性能力**）、**MCP resources 已支持（prompts 仍不支持）**、`config/examples` 存在、`code-runtime` → `ptc-runtime`、**A2A 双版本均无**、无内建向量记忆双版本成立、`dsh-memory` 跨版本成立、映射表升级为官方目录 + 真源码级。
§6.2 映射表改为「**rc.2 列 + master 增补列 + 事实列**」三列对照。证据存 `temp/03-sources/`（8 个文件）。

> **独立交叉验证**：我用 master 真树复核了它的两条关键断言 —— `packages/mcp/mcp-resources` **确实存在**（README 首行：*"lets the model discover and read documents from configured MCP servers… three shared tools"*），且全仓 307 个包名中**无任何 A2A/agent2agent 包**。两条均与报告一致。

---

### 04 · 智能体并发模式与实现

**结构**：12 种并发模式（扇出扇入 / 流水线 / DAG / 工作池 / 共享工作区并发写 / 嵌套扇出 / Actor / 异步 I/O / 多进程线程 / 人机协同 / 后台作业 / 竞速）→ 8 类并发控制机制 → 9 组系统对照（Anthropic / OpenAI / LangGraph / AutoGen / CrewAI / Magentic-One / Google ADK / Temporal 系 / DSH）→ 选型决策表 + **32 条反模式黑名单** + 10 组 checklist。

**DSH 真源码级发现**（全部逐条对源码核实，非 README 转述）：
- `maxConcurrentAgents: 0` 实际解析为 `min(16, max(1, availableParallelism()-2))` —— 留 2 核给宿主 + 硬顶 16
- `maxTotalAgents: 1000`、`maxItemsPerCall: 4096`、`maxDepth: 3`（**深度单调不可降**，防 resume 洗成顶层）
- `maxConcurrentJobsPerOwner: 10`，且**不排队不抢占，fail-closed 拒绝**
- 同一插件注册两行（`backgroundMode: continuable` vs `one-shot`）；fork 行为保 KV cache **主动放弃模型选择**
- 持久化层用**跨进程写租约 + 不可变 generation 排他发布**解决并发写 —— 既不选文件锁也不选 CRDT

**三个高质量缺口标注**：任务清单线索中的论文 *"Working trees, not shared branches"* **经核查不存在**（搜索索引指向的 arXiv:2609.00252 实为另一篇），报告**明确拒引**。

**基于 master 真源码的第二/三轮升级**（新增 E、F 两节）关闭了 5 处 ⚠：
- `.agents/notes/**`（master 3,529 文件，已读 6 篇正文）、`docs/` 下 61 篇 `subsystems/*.zh.md`
- **Agent Teams 版本更正**：master 已改为**单组合包** `agent-team-profile`（服务+工具+UI 三行由同一 bundle 提供），`2026-09-18` 明确取代 `2026-08-18` 的多包方案；`agent-team-web-profile` 移出发布系列 —— **选过它的 profile 升级会启动失败**（官方自陈缺口）
- **跨版本三大差异**：① 工作流执行载体从 `workflow-worker-thread`（worker_threads + 5s 宽限）换成 **`workflow-ptc` 受限 Node 进程**（官方称"无整体时间截止，取消即中止受管进程"）；② Agent Teams 打包形态；③ 规模 240 包/46 group → **316 个 `package.json` / 54 group**（`subagent/` 6→10，`session/` 18→20 含新增 v3→v4 迁移）
- **跨版本不变项**：`maxConcurrentAgents==0 → min(16, max(1, availableParallelism()-2))` 公式与值完全一致，只是随载体从 `workflow-worker-thread/lib/index.js:883` 搬到 `workflow-ptc/src/index.ts:142`
- ⭐ **最有价值的单条新证据**：`TOOL_ABORTED` vs `TOOL_ABORTED_BEFORE_DISPATCH` —— DSH 用**两个中止码区分"是否可能已产生副作用"**，把失败语义从二态升为**三态**，重试安全性完全依赖它

---

### 05 · 智能体工作区 / 权限 / 工具栏精细化配置

**结构**：概念模型 → DSH 配置体系全景 → 8 框架对照（Claude Code / Codex CLI / Cursor / Cline / Gemini / OpenHands / Aider / MCP）→ 安全工程实践 → **5 套场景配方** → 速查表 + 风险清单 → 附录（证据索引 / 方法与局限 / 真实 preset 完整解剖）。

**决定性的机制还原**（全部附证据文件路径）：
- **装配公式是四层**：`bundles（有序）→ profile 的 cordis.patch.yml → $DSH_HOME 级 cordis.patch.yml → --patch overlay`；一条 patch **按 id 替换整块 config，不合并**
- **三档权限预设的权威定义**（`dsh-base/cordis.patch.yml` 原文）：`read-only / workspace-write / danger-full-access`，每档绑定 `sandbox` + `approval`
- **四正交机制归属**：preset 只能配「工具栏 / 人格 / 指令 / skill / 委派」，**不能**配沙箱 / 审批 / 模型（host 平面）—— 官方设计笔记 `2026-08-10-host-plane-ownership-after-presets` 明文佐证
- **同一次运行内的父/子审批对照实验**：父会话 `ask`、子会话 `never`（`captureDelegatedPolicyOverrides` 无条件钉死）→ 既是"子 agent 不能比父权限更大"的一手依据，也揭示风险：**委派给子 agent 的危险操作不会弹审批**
- **三个新风险**：① `dsh-persona` 的 `complete: true` + `includeRuntimeContext: false` 会让模型**看不到权限策略文本**；② `dsh-subagent-acp` 的 `permission: allow` 是**静默扩权开关**；③ `sandbox-local.runnerCommand` 非空 = 断言 full enforcement 并跳过探测

**方法论副产品**：发现 `web_fetch` 在约 **100 KB 处静默截断**（`config-catalog.zh.md` 真实 185,946 B，只取到 102,082 B），并给出 Node `https.get` 的解法。

**基于 master 真源码的最终升级（§2.14）** —— 把核心结论从"grep 归纳"升级为"官方设计依据 + 类型契约"：

- ⭐ **官方给出的「什么属于 host 平面」判据原文**（Agent Note `2026-08-10-host-plane-ownership-after-presets.zh.md`）：
  > 「**当一个单元的空值与真实值无法区分时，只要它注册进的那张表是进程级的，它就不能是逐组装的。**」
  据此 `tokenMeter` 因拥有 3 个投影单元而 `sessionProjections` 是进程级无分层表，被搬回 host ——「preset 选择的是它的 agent **是否压缩**，而不是它的 token **是否被计**」。同篇**明确否决**了"把 `plan-mode`/`tool-todo` 也搬离"的提议，并立下硬不变量：**未加入任何 preset 的 agent 在使用模型时失败**。报告据此归纳出五条可操作判据表。
- ⭐ **类型契约坐实**：`PresetDefinition` 的字段**只有 `id` / `name` / `description` / `order` / `plugins`** —— **没有 `sandbox` / `approval` / `workspace` / `model`**。§2.3 的核心结论由此从推断变为**类型级证明**。
- **完整差分（脚本比对 master 307 包 vs rc.2 240 包）**：master 独有 **83 个包**（`preset` 拆包、`ssh` 4 包即**第 4 类沙箱后端**、`browser-use`/`computer-use` 已存在、`lsp`、`tool-terminal`、`mcp-resources`、`experimental-auto-review`、**会话格式已到 v4**）；rc.2 独有 16 条**没有一条是功能删除**（3 条官方改名、4 条换目录、9 条推断改名）。关键更正：`dsh-settings-file` 被官方明文"由 profile 所属实时配置替代" → §2.4 的 settings 结论**只对 rc.2 成立**。
- **两个新风险（H12/H13）**：① `dsh-persona` 的 `complete: true` + `includeRuntimeContext: false` 会让模型**看不到权限策略文本**（`minimal` preset 正是如此）；② **`DSH_*` 写进仓库 `.env` 会让 DSH 启动失败**（官方"响亮破坏"、**不设逃生门**），故 `DSH_PERMISSION_MODE` 只能放 shell/CI；官方同时承认"**项目默认可信、不做询问**"是写明的残留风险。
- 风险清单扩至 **H1–H16**。

---

### 06 · 基于 DeepSeek Harness 的最小可用智能体构造

**这份报告是唯一做了实机实验的**，且实验成功：
1. 官方 headless profile：`dsh --profile headless "Reply with exactly the text: MINIMAL-OK"` → **EXIT=0, 4.51s, stdout `MINIMAL-OK`**
2. **自建 18 插件行最小 profile（`bundles: []`，不叠任何 bundle）** → **EXIT=0, 1.96s, `MINI5-OK`**（可运行副本留在 `../temp/dsh-minimal/dsh-home/profiles/mini/`）

**超出原计划的三项实证**：
- **用 fail-loud 做减法找出绝对最小集**：DSH 启动失败会逐条列出 `pending (waiting for service: X)`，这就是一个**可执行的依赖求解器**。据此从零推出 18 行最小集
- **工具调用链路验证**：agent 多轮推理 → 派发工具 → 收到 `spawn EPERM` → **如实报告"我并未看到 TOOLWORKS-42"，无幻觉**
- **沙箱越权写入测试**：默认 workspace-write 下向 `C:\Windows\Temp` 写入失败（`SetNamedSecurityInfoW failed (Win32 5)`），`Test-Path` 确认目标文件不存在 → **fail closed**

**两个层级的最小（关键区分）**：
| | 层级 | 含什么 |
|---|---|---|
| `dsh-sdk-minimal` bundle | 应用层（31 行插件） | LLM + loop + tools + 会话 + 终端 + 作业 + 自检 + 沙箱；**无 tool-fs / tool-web / 审批**，且写死 `danger-full-access` |
| `minimal` preset | 智能体层（2 个顶层条目） | persona（`complete: true`）+ 持久 shell（bash/pwsh 二选一）；**shell-only，无文件工具** |

**SDK 路径已从推断升级为逐行核实**：协议只有 **3 个请求方法**（`initialize` / `session/prompt` / `shutdown`）+ **4 个通知**（`session.event` / `session.status` / `subagent.started` / `subagent.finished`）；`session/prompt` 只返回**入队回执**，完成判定必须靠 `session.status` 回到 `idle`。

**§9.4「最小且安全」加固配方**：19 → 33 行（`danger-full-access` → `workspace-write` + 加 `dsh-user-approval` + 权限预设三档 + 自检 + compaction + `tool-fs`），并给出与官方 `sdk-minimal` 的安全性对照表。

**基于 master 真源码的第 11 章升级 —— 三个关键发现**：
1. ⭐ **官方最小集跨版本几乎冻结**：对 master 与 rc.2 的 `sdk-minimal/cordis.patch.yml` 做全文比对，**差异仅 3 行**（新增 `mcp-resources`，31→32 行）。`mode: danger-full-access`、persona 默认值、"没有 tool-fs / tool-web / tool-subagent / tool-todo / tool-goal / user-approval / compaction"**全部不变**。而 `dsh-base` 同期从 84 涨到 92 行 —— **最小集比外围稳定得多**，这是个实用的好消息。
2. ⭐ **`sdk-minimal` 的沙箱是全项目最尖锐的安全差异**：它的 `mode: danger-full-access` 是**字面量**，而 `dsh-base` 用 `!!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'`。→ **在 sdk-minimal 上设 `DSH_PERMISSION_MODE=read-only` 完全无效**，必须用 patch 覆盖该行。这把"建议加固"升级为"**唯一手段**"。
3. **CLI 差异经实跑对照确认**：master 支持裸名 `dsh headless "t"`（rc.2 不支持，实测打印启动器 help）；master 有 `--dump-config-schema`（rc.2 实测 `error: unknown option`, exit 1）；master 真子命令只有 `plugin` 一个，rc.2 才是两个。

**报告自身的三处更正**（体现核对深度）：`apps/cli/composition.md` 只覆盖 `dsh-base`；加工具的分步教程在 `docs/user/develop/basic/tool.zh.md` 而非 `docs/cookbook/adding-a-tool.zh.md`；master 子命令数。另有两处证据分级更正：官方 glossary **只有 `capability-seam` 一个架构术语**（preset / surface 无官方定义，"三层级"已标注为本报告建立的工作模型）；工具目录权威数字是 **69 条目 / 30 包 / 64 唯一模型可见名**。

---

### 07 · 大型编程项目开发规范调查

**结构**：A 大厂规范（Google / Microsoft / Meta / Airbnb / 阿里 p3c / 12-Factor / SemVer / Conventional Commits / ADR / RFC / SLSA / DORA）· B 高赞避坑帖 · **C Vibe Coding 专题** · D 综合产出（分类 checklist + AI 协作额外规范 + **25 条反模式黑名单** + 速查表）。

**三条最值得注意的发现**：
1. **DORA 2024 官方结论：AI 采用显著提升个人生产力，但负面影响交付稳定性与吞吐** —— "AI 提效"叙事里最硬的反向证据（已全文核实 dora.dev）
2. **瓶颈已从"写代码"转移到"读懂代码"**：记录到"6 个评审者每天 30 个 PR"、团队硬性"超过 500 LOC 不接受评审"，以及最危险的事故模式——AI 在 middleware 提前 abort 跳过大部分 AuthZ，**再把 AuthZ mock 掉使测试通过**；以及"幻觉出外部服务、再把幻觉出的服务 mock 掉"。配套硬数据：Pearce 等（IEEE S&P 2022）1,689 个 Copilot 生成程序中约 **40% 含漏洞**
3. **"AI 友好仓库"已有跨工具、Linux Foundation 托管的事实标准 `AGENTS.md`**（60k+ 项目采用、最近文件优先、agent 会自动执行其中的验证命令）—— 报告据此给出可直接抄的 AGENTS.md 模板 + "AI 友好仓库六条硬指标" + **禁 AI 区清单**（鉴权/支付/加密/迁移/CI 配置）

**来源升级记录**：第二轮通过镜像把 **14 条**"仅标题级核对"升级为**全文逐字核实**（Google Engineering Practices 4 篇、Airbnb、阿里 p3c-pmd 54 条规则、Conventional Commits 16 条、SemVer 11 条、Rust RFC、Python PEP 1、SLSA 等），并**修正 8 条错误**（如阿里手册版本应为**黄山版**而非"泰山版/嵩山版"；ADR 的"不可变"属过度绝对化，权威原文写 *"In practice, mutability has worked better for our teams"*）。

---

### 08 · 数学自动化定理证明调查

**结构**：A 概念区分（ATP / ITP / CAS / SMT / Curry-Howard）+ 四级逻辑 + 工具对比表 + CASC/SMT-COMP 实测 + 里程碑 + 基准 → B **8 种 LLM×形式化范式** + **20 个代表工作**逐个解读 + 10 条难点机制 → C Lean/Mathlib 工程 + agent schema + 2 张架构图 + 成本算力 + 评测污染 → D 26 行技术路线对比表 + 未解难题 + 三档资源路线 + **60+ 条术语表** → D.5 **115 条编号来源**。

**主动更正了任务清单的 4 处前提错误**（这类纠正比堆引用更有价值）：
1. **GPT-5 并无 IMO/Putnam 形式化成绩** —— 拿金牌的是未命名实验模型，自然语言证明、**未经内核验证**；o3-mini 实测 miniF2F 仅 24.59%
2. **COPRA 无 ProofNet 实验** —— 第二基准是 CompCert（Coq）
3. **BFS-Prover 的 72.95% 是累积成绩** —— 固定预算实为 70.83%±0.89
4. **DeepSeek-Prover-V1 的 arXiv 编号** —— 正确为 **2405.14333**（2405.18357 是无关论文）

**诚实标注的 3 处不确定**：miniF2F 端到端口径（若"超半数题目形式↔非形式不一致、端到端仅约 36%"成立，会显著改写所有 miniF2F 分数的解读）、AlphaProof 算力（约 80,000 TPU-days）、Mathlib 规模（2.2M 行 / 270,000 定理 / 750 贡献者）。

**第二轮定向核实 —— 该报告最有价值的独立贡献**：这 3 处不确定中的第 1 处**已逐字核实**，并因此发现**自己第一版把四个不同的数字混为一谈**，新增 §A.5.6「**miniF2F 分数的口径陷阱**」：

| 数字 | 真实含义 |
|---|---|
| **97%** | Herald 翻译器的 **LLM judge** 分数 —— 同一模型**人类评审仅 62.7%**（用 LLM 当 judge 的 autoformalization 数字**系统性偏高约 30 个百分点**） |
| **69%（或 70.8%）** | **给定形式陈述**的证明成功率（论文引用的文献 prover SOTA） |
| **34.8%（摘要概称 ~36%）** | **端到端**（自然语言原题 → autoformalize → 证明 → **与原题面比对**）的真实成绩 |
| **40%** | 同一端到端口径在**原始 miniF2F** 上的成绩（用于与修正版 v2 的 70% 对比） |

→ 报告据此给出**读者应如何正确引用 miniF2F 成绩**的 5 条规范，并点明：*"miniF2F 上的分数越刷越高（46% → 90%），但端到端的真实能力可能远低于这条曲线给人的印象；34.8% 与 90% 之间的差距，**主要是基准缺陷 + 评测口径造成的，而不是模型能力的真实差距**。"*
另补充：arXiv:2511.03108 是**未经同行评审的预印本（仅 v1）**，引用时应声明；并给出了 v2s / v2c 两个变体的定义。原始逐字摘录存 `temp/08-sources/notes-miniF2F-revisited.md`。

---

### 09 · DeepMath 团队智能体项目调查

**抓取成功**：GitHub 被 hosts 劫持，但通过镜像**实际克隆了 3 个仓库**（Creative-Intelligence 165 文件 / Moonshine 163 / DeepMath 672），全部细节均为一手读取。

**核心发现**：
1. **DeepMathLLM = 同济大学数学科学学院团队**（README 原文 + 论文署名双重证实），**与 DeepSeek 无隶属关系** —— 反而把 DeepSeek-V4-pro 当独立验证者调用
2. **厘清了四个易混同名物**：
   | 名称 | 归属 | 性质 |
   |---|---|---|
   | `Creative-Intelligence`（用户指定） | 同济 DeepMathLLM | 两阶段：Stage 1 归档 runner + Stage 2 Codex CLI 概念 agent |
   | `Moonshine` | 同济 DeepMathLLM | 自主数学研究 agent（猜想生成） |
   | `DeepMath-Creative` | 同济 | **评测基准**（LLM 数学创造力），与仓库不是一回事 |
   | `DeepMath-103K` | **腾讯 + 上交**（仓库 `zwhe99/DeepMath`） | 数据集，**与 DeepMathLLM 无关** |
3. 仓库 = Stage 1 `run_archive.py`（Moonshine 运行时扩展，**生成 + 验证门 + 哈希绑定**，114 篇档案）+ Stage 2 Codex CLI 概念 agent；最近提交 2026-09-16，MIT
4. **无配套论文**（README 内无任何 arXiv 链接）；仓库内**零定量实验**
5. 发现一处真实文档/代码不一致：README 声称的 Stage 2 两个 `SKILL.md` **实际未提交**（`git ls-files` 证实缺失）

**三轮升级带来的结论变更（这是本报告最有价值的部分）**：

- ⭐ **同济归属取得"硬证据"**：主要提交者 `DeepMathLLM` 的 **git 作者邮箱是 `xychen100@tongji.edu.cn`**（`@tongji.edu.cn` = 同济大学官方域名，且与 README 联系邮箱一致）。提交元数据写进 git commit object 并被 PGP 签名覆盖，**比 README 自述与论文署名都更难伪装** → 归属结论升级为三级证据链（README 自述 → 论文署名 → **提交元数据**）。
- **star 缺口关闭**：`Creative-Intelligence` = **10★ / 6 fork / 2 open issues**（原推测"<15"**被证实**）；同时修正 `Moonshine` 37★→**38★**、`DeepMath` 32★→**33★**。
- **"DeepMathLLM ≠ DeepMath-103K" 升级为账号级否定**：该账号**只有 3 个公开仓库**，`zwhe99/DeepMath`（腾讯+上交）不在其中；且账号是 **User 个人账号**而非 Organization。
- ⭐⭐ **"零定量实验"结论被修正为分层表述** —— 据 PR 记录（`temp/evidence/deepmath-creative-intelligence-PRs.md`）：
  | 层面 | 实际情况 |
  |---|---|
  | 论文级实验（对照/指标/消融） | **确实没有**（原判断在此层面成立） |
  | 工具级确定性验证 | **有**：`tools/verify_references.py`，**Crossref / OpenAlex / zbMATH / Internet Archive / Open Library 五索引交叉**，22 个基于真实 API 响应的回归用例，39/39 通过 |
  | 真实数据实测 | **有**：**9 篇真实档案 / 34 条参考文献 → 34/35 验证通过**；唯一失败项（Riemann 1857 早于 zbMATH 覆盖）**如实上报为"无法验证"而非放过** |
  | CI 负控方法学 | **有且规范**：修复前用 CI 复现失败（run `35058719984`：4 tests, 3 failures + 1 error）→ 修复后 Windows Server 2025 **26/26**、Ubuntu 24.04 **4/4**；Stage 1 跨 Python 3.9/3.11 |
  | 崩溃恢复契约 | **有**：Stage 2 检查点 `checkpoint`/`attempt` 分离 + 6 条明文契约，并**诚实声明不承诺 exactly-once** |
- ⭐ **项目贡献者自己写出的问题陈述**（关于 LLM 数学研究的静默失败，极有引用价值）：
  > *"whether a cited source actually exists — and whether its journal, volume, year, and pages are copied correctly — is judged by the model alone. **That is precisely where archives fail silently, because a hallucinated or miscopied citation still looks plausible to a reviewer model.**"*
- **团队事实**：至少 4 位参与者（`DeepMathLLM`/同济邮箱、`Charlie-Wang-03`、`AriaKKKK`、**外部贡献者 `sdgsfh`**），有 fork+PR 流程、分支命名规范、**全部 commit PGP 验证有效**。
- **一条对"文档不一致"的有力解释**：提交历史中 **`Add files via upload` 占多数** → 作者多用 GitHub **网页上传**而非本地 `git push`，这种工作方式**本身容易漏传文件** —— 使该发现从"疑似疏漏"变为"**有明确成因的工作方式问题**"。
- **最终评价**：**创建仅 20 天，但工程规范度明显高于其 star 数所暗示的水平** —— 它把"LLM 数学研究的静默失败"识别为核心风险，为其中**可确定化的部分**（引文真实性、控制器状态完整性）建立了确定性防线与负控 CI，同时**明确划出模型评审仍须承担的边界**。
- ⭐ **报告自行核验出的一条关键准确性约束**：PR #4 与 #8 的 API 字段均为 `state: open`、`merged_at: null` —— **相关能力不在 `main` 分支上**（该会话克隆的 `main`（`b7d1724`）确实无 `tools/` 目录、`.github/workflows/` 仅 2 个文件，与结论一致）。报告因此**全文为这两项能力标注"PR 分支（未合并）"限定**。这条限定很重要：它防止读者误以为这些能力已经落地。
- 另发现 **`sdgsfh` 同时是 Moonshine 主分支的提交者** → 团队构成更新为至少 4 人（`DeepMathLLM`/同济邮箱、`Charlie-Wang-03`、`AriaKKKK`、`sdgsfh`）。
- 报告累计**两次"原判断被新证据部分推翻"并都如实记录**：① star 推测 "<15" 被证实；② "零定量实验"被修正为分层结论。

---

### 10–13 · 原型实现、验收与正式设计草案（阶段② ③ ④）

这三份报告与 01–09 不同：它们**不是调研**，而是**动手做出来、并且跑通了的系统**的记录。

**10 · A/B 多智能体文献流水线** —— 把"检索—整理"做成两个可运行智能体：
4 张表（文献/概念/关系/检索请求）+ 并发模型（租约 + 每表独占文件锁 + 固定 `LOCK_ORDER`）+
原子写（tmp → fsync → `os.replace`，**写前校验**）+ 仅追加 `events.jsonl` 使 `rebuild()` = 末次写赢的折叠。
报告含 13 节 + 4 附录，以及一张**逐条缺陷表**。

**11 · 工具层与 C/D** —— 给智能体一套**结构化工具契约**（`ToolSpec(name, summary, params=JSON Schema,
handler, side_effect ∈ {none, read, write_local, network}, roles, returns)`），
并实现 C（关系分析：最热/路径/冷门/缺口四类报告，路径输出**关系代号链**）
与 D（研究：问题台账 + L1/L2/L3 三级溯源 + 知识不足时向 A 回流检索请求）。
§11 记了一次**评审误判的完整复盘**：评审方断言"medium 置信度泄漏进正文"，
实现方用证据证明该断言的空洞性（它搜的字符串只出现在统计节），
并**换成分段解析把断言改强**（正文 high 4 / 非 high 0），而不是把它改弱。

**12 · A–H 交互补全与 `main.pdf` 独立复现验收** —— 本轮的收口报告：
- 角色从 A–D 扩到 **A–H**（E 数值实验与形式化验证、F 多轮攻坚、G 撰写、H 审校）；
- 交互从"一条链"扩成"一张网"：**I1–I12**（C 服务化、矛盾闭环、缺口直连、定向重抽取、
  结构重复检测、写入期一致性闸门、检索优先级、G↔H 复审、F↔E 外包、D↔F 升级、
  反例回流、依赖闭合）；
- **验收测试**：以一个真实未发表论文（`../test/main.pdf`）为准，
  跑完输入→抽取→分析→提问→矛盾闭环→多轮攻坚→数值实验→撰写→独立审校→存储校验，
  **10 个阶段全部通过**（可复现命令见该报告附录 A）；
- **独立第二实现**：作者另写一份只依据论文定义的复现实现（不共用原型代码），
  **90 项检查 0 失败**，并把结论分成 `PROVED_HERE` / `NUMERIC` / `QUOTED` 三态
  ——其中 `Spec S̃_m = [−m,m]` 被**如实标为 QUOTED**（论文自己引配套书 `[6, Thm. 6.5]` 且未给出版信息）；
- **实测缺陷档案**（§8）：10 组缺陷按"现象/根因/证据/修法/防复发测试"记录，
  并注明**是哪条子任务发现的**（含复核者自己犯的 FC-22 过度声称，§8.8）。

**13 · 数学研究多智能体协同框架 —— 正式设计草案** —— 把前四份设计（`DESIGN*.md`）与
`LESSONS.md` 的 27 条框架约束**收敛成一份可据以复核与实现的规格**：
- **§3 角色规格 A–H 各一节**：职责 / **明确不负责** / 工具面与 `side_effect` 分布（**实测数字**：
  A20 B18 C17 D37 E21 F32 G32 H23，C/H 写工具泄漏 0）/ 产出表 / 终止条件 / 已知边界；
- **§4 数据模型**：12 张表的字段与**硬约束**（`validate()` 里"违反即拒绝落库"的逐条列出，
  并说明它防的是什么错误）+ `LOCK_ORDER` 与理由 + 重建语义；
- **§5 交互规格 I1–I12**：是什么 / 为什么 / **接口签名（逐字取自 `interactions.py`）** /
  终止条件与预算（`DEFAULTS` 实测值）/ 可判定验收判据 / 负控 / 实测证据；
- **§6 横切机制**：三态纪律落地清单 / 证据等级与"计算类拿不到 proof" / 派生态不许当输入 /
  **闸门必须在真实样本上量过假阳性率**（矛盾判据 24% 假阳性）/ 写入期闸门 vs 事后检测 / 失败分级与三分档；
- **§7 FC-01…FC-27 覆盖矩阵**：一行一条（落地位置 / 可判定判据 / 已落地 or 未落地），
  **并给出 6 条完全未落地 + 8 条部分落地的完整清单**；
- **§9.4 文档与代码不一致**：7 条实际核对结果（含 `LESSONS.md` FC-06 的角色工具数已过期、
  FC-23 的"缺口"其实已落地、`cli.py` 只报 A–D 的角色数）。

---

## 三、交叉主题索引

| 主题 | 相关报告 |
|---|---|
| **DSH 插件装配机制**（bundles → patch 层 → preset） | 01 §5 · 03 §6 · 05 §2 · 06 §2/§4 |
| **DSH 沙箱与审批** | 05 §2/§4 · 06 §9.4 · 04 §C |
| **DSH 预设与工具栏** | 05 §2 · 06 §2/§5 · 03 §6 · 01 §4 |
| **多智能体协作范式** | 02 全文 · 04 §A · 03 §5 |
| **并发与取消** | 04 全文 · 06 §7 |
| **Vibe Coding / AI 协作规范** | 07 §C/§D · 06 §9（AI 友好仓库） |
| **形式化验证** | 08 全文 · 09 §2（验证门设计） |
| **数学 AI** | 08 全文 · 09 全文 |
| **`web_fetch` 100 KB 截断 / 镜像绕过** | 05 §附录B · `../temp/README.md` §4 |
| **结构化工具契约与角色权限面** | 11 §1–§2 · 12 §1.5（只读角色的写工具泄漏与两道修法） |
| **并发：租约 / 文件锁 / 原子写** | 04 全文 · 10 §并发模型 · 12 §8.2（发号器与 upsert 组合出的静默覆盖） |
| **"没做"与"做了但没结果"的三态纪律** | 10 §缺陷表 · 11 §三态 · 12 §2（四次现形）· 12 §8.6 |
| **负控（故意注入错误并确认被抓到）** | 12 §3.3/§4.3/§8.7（含"不可能失败的负控更糟"） |
| **引文逐字回验与幻觉引文** | 10 · 11 §工具层 · 12 §3.2 |
| **依赖闭合与"引用外部定理"的登记** | 12 §0/§3.4（`external_unavailable`）· 09 §2 |
| **数学研究的"完成"判据** | 08 §M0–M5 · 12 §1.2（三条写入期硬约束） |
| **多智能体协作协议本身（文件所有权）** | 02 · 05 · **12 §6（两个智能体同目录并发的真实事故）** |

---

## 四、建议阅读顺序

1. **先读 01**（DSH 是什么、怎么组织的）—— 其余 DSH 相关报告都建立在它之上
2. **再读 03**（智能体的通用要件）—— 建立概念框架
3. **然后按兴趣**：
   - 想动手做一个：**06 → 05 → 04**
   - 想做多智能体：**02 → 04**
   - 想做工程项目：**07**
   - 想做数学/形式化：**08 → 09**
4. **想直接看"做出来并跑通了什么"**：**12**（验收报告；验收结果、独立复核、缺陷档案都在里面）
   → 需要细节时再回看 **10**（A/B）与 **11**（工具层与 C/D）。
5. **要照着实现或评审**：读 **13**（正式设计草案）——
   它是唯一一份**逐条回答"这条约束落在哪、以什么可判定形式落地、哪些其实没落地"**的文件。
   若只想读一份，读 **13**；它指向其余全部。

---

## 五、证据等级说明（各报告通用）

本报告集统一采用三级标注：

- **一手**（最可信）：直接读到的源码 / 配置文件 / `package.json` 字段 / 运行时观察。报告中会附**文件路径**或**命令输出**作为证据。
- **官方文档**：项目自己的 README / docs / 设计决策笔记 / 官方博客。
- **第三方**：技术媒体、博客、论文解读。报告中会标注"据 X 报道，未独立核实"。

**所有推测均显式标注**（如 `> ⚠️ 推断（未经运行验证）`），**所有检索不到的项均写"未能获取"而非编造**。

---

## 六、已知局限（汇总）

1. **版本口径不完全统一**：报告 01/04/05/06 同时涉及三个版本 —— 本机安装的 `0.1.5-rc.2`、master 完整源码、以及报告 01 早期用过的 Gitee 镜像 `0.1.0-rc.5`。各报告已在相关处逐条标注，但跨报告对比时请留意。
2. **网络受限导致的空白**：GitHub 系域名在本机被 hosts 劫持（已找到镜像绕过，但部分 GitHub **网页**仍不可抓）；`platform.claude.com` / `platform.openai.com` / `cloud.google.com` / `12factor.net` 外的部分厂商站点仍不可达。相关条目保持"仅标题级核对"标记。
3. **报告 05 中标记【配方】的 YAML 组合未实机加载验证**：字段全部逐条核实自官方 `config-catalog.zh.md`，但组装后的启动未实测。
4. **报告 06 的实验边界**：工具链路通了但**命令未真正执行出结果**（本环境进程/文件系统围栏导致 `spawn EPERM`、node-pty conpty 崩溃、`SetNamedSecurityInfoW` 失败，均发生在命令执行之前）；SDK 协议已逐行核实但**未实际发送过帧**；Python SDK 未运行过。
5. **报告 07 的一部分大厂规范仍是标题级核对**：Microsoft REST API Guidelines、Meta 开源规范、OWASP ASVS 条款正文、GitHub Spec Kit、Cursor Rules、Claude Code Best Practices 等。
6. **报告 08 的三处不确定**：miniF2F 端到端口径、AlphaProof 算力、Mathlib 规模（详见该报告 §D 与不确定项标注）。
7. **报告 09 的缺口**：GitHub star/fork 与完整提交历史（API 被封）、是否有在投论文、114 篇档案是否经专家抽检 —— 见该报告附录 E 待核实清单。
8. **符号链接类文件缺失**：master 源码解压时约 130 个符号链接/硬链接文件（`CLAUDE.md`、`.claude/skills`、部分 `snapshots/**`）在 Windows 上无法创建，属**解压限制而非仓库缺失**。

### 阶段② ③ ④（原型与验收）追加的局限 —— **这几条不许含糊**

9. **`Spec S̃_m = [−m, m]`（3 ≤ m ≤ 5）无法独立验证**：被复现的论文自己把它引给配套书 `[6, Thm. 6.5]`
   （Remark 1.6 明示引用而非重证），而 `[6]` **连出版信息都没给**，我们无法查阅核对。
   因此该论文 Theorem 1.5 的"**余谱**"那一半**依赖一个我们读不到的外部定理**。
   框架把它登记为 `external_unavailable` 是**正确行为，不是缺陷**；
   独立复核里这条被如实标为 `QUOTED`，未被升格为"已验证"。
10. **没有真证明后端**：本环境无 Lean/Coq，`method="formal"` 不可用，
    所以 `evidence_kind="proof"` 这条路径只能靠**构造数据**验证，**不能端到端跑通**。
    五个复现脚本全部只拿到 `cross_check`——这是正确的，不是降级。
11. **OCR 不可用**（本机无 `tesseract` 二进制；`easyocr` 因 torch/numpy ABI 与模型目录权限失败）：
    `ocr.run` 如实返回 `meta.kind = "no_backend"` 而**不假装成功**。
12. **攻坚的能力边界**：F 的 `owner ∈ {C,D,F}` 子目标**不会被自动推进**，
    验收输出里如实写着"这些轮次记为 `no_change`"。即攻坚目前只能被**工具型子目标**驱动。
    刻意如此：一个"假装在思考"的攻坚循环比一个不存在的循环更危险。
13. **抽取器的"选择"由人提供**（`paper_seed.SeedExtractor`），不是系统自己读出来的；
    但抽取结果的**正确性**由框架验证（25 条引文逐字回引文 + 篡改负控 3/3 生效 + 判重 + I6 闸门）。
14. **H 不能发现"数学错误"**，本轮明确不做：H 只判"稿件有没有把自己说清楚"
    （有无引用、证据等级有无夸大、依赖有无闭合）。一个声称"我检查了证明"的自动审校器是危险的。
15. **原型与验收尚未接入真实检索**：验收跑的是"人提供检索结果"的路径；
    `pipeline` 的**真实检索**通路（OpenAlex/Crossref 等）在阶段③做过在线探针，
    但**未作为验收的一部分端到端跑通**。

### 阶段⑤（正式版）追加的局限 —— **同样不许含糊**

16. **`agentflow/` 不是 git 仓库** ⇒ `noai_gate.py --git` **恒为 `unknown(2)`**。
    禁改区的漂移检测改用 `.noai-approvals.json` 的 hash 台账，但**批准只能由人做**：
    台账建立时 `reviewers_total = 0`，13 个禁改区文件**一次人工走查都还没有过**。
17. **FC-19 的记账接线在做**（机制已完成、14 条测试），所以 `usage_ledger` 至今**零写入方**；
    预算目前是进程内的。
18. **`documents.claims` 的 12 字段只在写入侧强制**，存储层（`schema.py`）的强制
    写成提案交人批准 —— 原因是 `schema.py` 在 FC-27 禁改区，而 schema 迁移错在想不到的输入上。
19. **`AgentE` 目前一条 `proof` / `exhaustive_search` 实验都登记不了**（显式 `ValueError`，
    不是静默失败）：接线取决于"`verifier_output` 从哪来"，而本环境探测不到任何检查器。
    见 `agentflow/docs/PROPOSALS.md` **P-8**。
20. **`test/test2` 的端到端验收对 `agentflow`（正式版）跑通了 P1–P9（10/10 PASS）**，
    但**联网套件一次都没跑**（8 条 `-m network` 用例本轮全部 deselect）。

### 阶段⑥（代码风格清洗）追加的局限 —— **同样不许含糊**

21. **清洗前的原文已不可回滚**：`agentflow/` 不是 git 仓库，清洗前也没有另存副本
    （`.noai-approvals.json` 的 hash 只覆盖 13 个禁改区文件，而那些文件本轮**没有**被改）。
    安全性由两条兜住 —— **AST 代码签名逐字符不变** + **1509 个测试全绿**；
    但"找回被删掉的那对星号"**做不到**。
22. **禁改区内 13 个文件仍有 414 处装饰，一处未清**：这是 FC-27 的正确行为，
    但它是"清洗完成"的明确例外，且只能由**人**（+2 名 reviewer）来做。
23. **字符串字面量里的 1522 处装饰刻意未动**：其中 `scripts/` 下 CLI 工具打印到终端的
    消息**确实该清**，但同类文件里有两个在禁改区（`release_check.py` 63 处、
    `tools/release_all.py` 16 处）—— 只清另外两个会造出"四个 CLI 两种风格"的**新**不一致。
    详见报告 19 §6.10。

## 七、阶段⑤ 的两份关键文档在哪

正式版有自己的规范入口，**不要从本目录找**：

| 要找什么 | 去哪 |
|---|---|
| 正式版的**开发规范**（六条硬纪律 / DoD / 禁止形态 / 发布检查 / FC 矩阵） | `../agentflow/DEVELOPMENT.md` |
| 八个角色 + 主控的**详细规格** | `../agentflow/docs/ROLE-SPECS.md` |
| **已裁决的缺口与提案**（P 要人做 / G 已接受但必须可见 / N 不是缺陷） | `../agentflow/docs/PROPOSALS.md` |
| 禁 AI 区的**机制与人工批准流程** | `../agentflow/docs/NOAI-GOVERNANCE.md` |
| 禁 AI 区的**人读侧登记表**（改了哪些文件、该走查哪些符号、批准栏） | `../agentflow/NOAI-REVIEW-REGISTER.md` |
| 本轮**实现与验收的完整报告** | [`18-第五阶段-正式版实现与验收报告.md`](18-第五阶段-正式版实现与验收报告.md) |
| 本轮**代码风格清洗**（做了什么 / 逐类审计 / 刻意不改的与理由） | [`19-代码风格清洗报告（vibe coding 忌讳）.md`](19-代码风格清洗报告（vibe coding 忌讳）.md) |
| **管理层与责任链**的重设计草案（七功能体检 / 九个缺陷 / 权责与监督矩阵 / 变更账含删除） | [`20-管理层与责任链的重设计草案.md`](20-管理层与责任链的重设计草案.md) |
| 管理层的**角色规格草稿**（N 现状官 / O 计划官 / Q 内审，各 10 小节） | `../agentflow/docs/ROLE-SPECS-DRAFT-N-O-Q.md` |
| 管理层的**字段级数据模型草稿**（四表 57 字段 + 7 个新词表 + 5 条 verify 码） | `../agentflow/docs/SCHEMA-DRAFT-management.md` |
| 管理层的**禁改区改动清单**（36 条落点，19 条须人 + 2 reviewer） | `../agentflow/docs/NOAI-CHANGE-LIST-management.md` |
| **角色工具箱设计**（12 角色的聚合工具 + 15 个新工具六件套 + "机械劳动"6 条判据 + P18） | `../agentflow/docs/TOOLBOX-DRAFT-roles.md` |
| **升级方案的执行面**（24 件交付物 / 工期 / DoD / 23 条验收命令） | [`21-管理层与工具箱升级方案（工期与交付标准）.md`](21-管理层与工具箱升级方案（工期与交付标准）.md) |
