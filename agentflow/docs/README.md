# docs/README.md —— 交付集合的入口：先读哪份

> 这份文件只回答**顺序**：我是谁、我该先读哪一份。它**不**判定"哪份算数" —— 那件事仍然
> 只有 [`INDEX.md`](INDEX.md) 一处维护。分工写死在这里：**本文管顺序，INDEX 管权威性**
> （改一份文档要同时改 INDEX，见本文 §四）。
>
> `docs/` 是 `agentflow` 的**交付文档集合**：盘上每一份 `*.md` 都在 INDEX 里有落点
> （判据 `tests/test_docs_index_covers_every_doc.py` 强制）。历史件、一次性送审页与设计理由
> 原件**不在这里**：它们在 `../draft/archive-*`（**本地，不入库**，干净 clone 里没有）。

## 一、60 秒路线

| 我是… | 第一份读它 | 读完拿到什么 |
|---|---|---|
| **新手** —— 第一次听说这套系统 | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) | 它是什么、谁在干活、一次运行长什么样（每个数字带现算命令） |
| **我要跑** —— 想装起来跑一趟 | [`INSTALL-AND-FIRST-RUN.md`](INSTALL-AND-FIRST-RUN.md) | 从 clone 到第一次 `--dry-run`：零模型、零花费、可复算 |
| **我要改** —— 改代码 / 加工具 | [`../DEVELOPMENT.md`](../DEVELOPMENT.md) → [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md) | 改哪里、怎么验、哪条判据守它 |
| **我要查设计** —— 为什么是这样 | [`DESIGN-BASELINE.md`](DESIGN-BASELINE.md) | 51 条基线（B01–B51）＋六层权威序＋判级规则 |
| **我要看限制** —— 它做不到什么 | [`LIMITS-AND-NON-GOALS.md`](LIMITS-AND-NON-GOALS.md) | 已知限制 ＋ 不做清单 ＋ 可证伪条件，一次看全 |
| **我要查术语** —— role / 板 / 交接 / 八格… | [`GLOSSARY.md`](GLOSSARY.md) | 每个词一句话，并指到写着它的那一份 |
| **我要抬提示词版本** | [`TEACHING-VERSION-BUMP.md`](TEACHING-VERSION-BUMP.md) | 改教法 / 工具面时必须同时改的 7 处 ＋ 命令 |
| **我要验收** —— 照单跑真机 | [`USER-TEST.md`](USER-TEST.md) | 人读的验收剧本（付费、需要模型 key） |

**入口链（从仓库根起三跳）**：`../README.md`（仓库根）→ [`INDEX.md`](INDEX.md) → 本文 → 任意一份。
本文**一跳**能到达的五件事：装 / 跑（INSTALL）、查设计（DESIGN-BASELINE）、看限制（LIMITS）、
查术语（GLOSSARY）、改代码（`../DEVELOPMENT.md`）—— 陌生人从仓库根出发共三跳。

## 二、目录树（每份一句；份数以 `(Get-ChildItem docs/*.md).Count` 现读为准）

> 两份**生成物不许手改**（`ROLE-GUIDE.md` / `SYSTEM-COMPONENTS.md`）：它们由
> `python -B tools/write_system_docs.py` 现算，判据 `tests/test_system_docs_are_generated.py`
> 逐字节比；手改必红，且红的原因不是文档写错了。

```text
docs/
├─ 入口与地图
│  ├── README.md .................... 本文：先读哪份（顺序）
│  └── INDEX.md ..................... 权威地图：哪份算数 / 历史 / 已退役（§1–§6）
├─ 系统与设计
│  ├── SYSTEM-INTRO.md .............. 系统总览：八层 / 十一角色 / 16 张表 / 生命周期 / 收工门 / 证据链
│  ├── DESIGN-BASELINE.md ........... 现行设计基线 B01–B51 ＋ 六层权威序 ＋ 判级规则
│  ├── SYSTEM-COMPONENTS.md ......... （生成物）各组件：功能 / 实现 / 落点 / 守着它的判据
│  ├── PART-LEDGER-AND-STORE.md ..... 数据台账与存储：表 / 落点 / 契约 / 原子写 / ID / 锁序 / 重放
│  ├── PART-EVIDENCE-AND-SIGNS.md ... 证据与签名链：一条断言怎样走到 proof 级
│  ├── PART-ARTIFACTS-LEDGER.md ..... 产物台账（ARTIFACTS.jsonl）：谁写、写什么、怎么对账
│  ├── TWO-AXES-GRADE-AND-KIND.md ... 等级（GRADES）与档位（EVIDENCE_KINDS）是**两根轴**
│  ├── LEAN-MODES.md ................ 有 Lean / 无 Lean 两档矩阵：动作面 / 证据上限 / 各格
│  ├── FORMAL-TOOLCHAIN.md .......... Lean / Mathlib 装哪个版本、怎么装、装完怎么验
│  ├── PRESET-RETIREMENT.md ......... 预设机制为什么退役、A 的检索正文现在住哪
│  ├── GUARDS.md .................... 三件只读护栏：wellformed / sysguard+sysresidue / seedinject
│  ├── NOAI-GOVERNANCE.md ........... 禁改区门语义：谁能批、批几个、台账怎么写
│  └── KNOWN-UNWIRED.md ............. 已登记的未接线工具模块（机器可读区块 == 盘上实测）
├─ 角色与协作
│  ├── ROLE-SPECS.md ................ 十一角色的**规格**（判据）：职责面 / 动作表 / 边 / 写集
│  ├── ROLE-SPECS-APPENDIX.md ....... 上述规格的**实测附录**：数值槽由工具现算重写
│  ├── ROLE-GUIDE.md ................ （生成物）十角色＋主控逐一介绍：设定 / 职责 / 工具面
│  ├── ROLE-A.md … ROLE-V.md ........ 逐角色说明（十一个文件）：输入输出 / 动作面 / 边界 / 协作面
│  ├── CHAIN-A-B-C.md ............... 文献 → 证据 → 命题 → 分析报告
│  ├── CHAIN-D-E-F.md ............... 问题 → 猜想 → 证明 / 实验 → 登记 → 送审
│  ├── CHAIN-G-H-V.md ............... 手稿 → 审读 → 送审 → 判 → 交付说明
│  └── CHAIN-ALL-ROLES.md ........... 十一角色协作总图 / 边表 / 典型流水 / 三条硬边界
├─ 用户与运维
│  ├── INSTALL-AND-FIRST-RUN.md ..... 装到第一次 --dry-run（每条命令真跑过，输出是原文）
│  ├── USER-GUIDE-CLI.md ............ CLI 手册：装 / init / 起一趟 / 看进度 / 插话答问叫停 / 续跑
│  ├── USER-GUIDE-WEB.md ............ Web 手册：两档 / 十页 / 写端点 / CSRF / 状态码与修法
│  ├── USER-TEST.md ................. 人读验收剧本（付费真机：停在等答 → 答 → 接着跑 → 两道门）
│  ├── CLI-CONTRACT.md .............. inspect 组 --json 的机器可读契约：外层四格 / data / 三态
│  ├── LIMITS-AND-NON-GOALS.md ...... 已知限制 ＋ 不做清单 ＋ 可证伪条件
│  └── GLOSSARY.md .................. 术语表：每个词一句话 ＋ 权威落点
├─ 开发与判据
│  ├── DEVELOPMENT-SPEC.md .......... 开发规范本体：改哪里、怎么验、判据在哪
│  ├── TEACHING-VERSION-BUMP.md ..... 抬提示词版本的同步清单（7 处 ＋ 命令 ＋ 对应判据）
│  ├── PROMPT-HISTORY.md ............ 提示词版本账：每抬一格追加一段，末节标题 == 版本号
│  └── READING-MAP.md ............... 大文件行数与「该读哪一段」的索引
└─ 历史与复算证据
   ├── USER-END-DSH-STYLE.md ........ Web 皮的来源（MIT 出处登记）＋ 三条纪律
   └── REPRO-eval-results-no-producer.md  复算证据原文（有一条判据逐字读它）
```

## 三、读之前该知道的三条

1. **文档里的数字是读数，不是规格。** 多数数字就地带现算命令；与代码冲突一律**以代码为准**。
2. **判据（`tests/`）不随仓库交付**（业主 2026-11-21 裁定）：它是本机开发门，干净 clone 里
   没有这个目录 —— 所以"复现判据读数"在 clone 里做不到，能跑的是产品自己的门：
   收工门 `closing` / `verify` / lint / 禁改区门。
3. **不入库的邻居**：`../draft/`（业主裁定与施工单）、`../projects/`（真机运行数据）、
   `../temp/`、`../test/`。引用它们时必须写明"本地、不入库"，否则新读者找不到。

## 四、这份文件受谁管

它自己也是 `docs/*.md` 之一：新增、改名或归档任何一份文档，都要同时改 [`INDEX.md`](INDEX.md)
（§1–§3 登记，或 §6「不入册」写清理由），否则 `tests/test_docs_index_covers_every_doc.py`
当场红 —— 那条判据同时钉着"本文在不在"。
