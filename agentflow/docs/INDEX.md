# docs/INDEX.md —— 权威地图（哪份算数、哪份只作依据）

> 这份文件的职责只有一个：**告诉读文档的人，哪一份是「当前规格」、哪一份是「历史证据」、
> 哪一份只是「设计理由」**。三者混着读，是这套仓库最容易犯的错。
>
> 判据优先级（从高到低）：**代码与判据 > 本索引 > 各份规格 > 设计理由 > 历史提案**。
> 任何文档与代码冲突，以代码为准；本索引里的读数，以 §5 的复跑命令为准。

## 1. 入口（先读这三份）

| 文件 | 管什么 | 权威性 |
|---|---|---|
| [`../../README.md`](../../README.md)（仓库根） | 系统是什么、怎么装、怎么跑、有哪些命令与开关 | **当前**——数字都从代码现读 |
| [`../DEVELOPMENT.md`](../DEVELOPMENT.md) | **入口**：职责 + 两份指针 + 改代码前先读哪三节（行数不在这里写死，现算见 §5「文档行数」） | 入口 |
| [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md) | **开发规范本体**（每节 `## [规范]`）：改哪里、怎么验、判据在哪 | **当前规格** |
| [`DEVELOPMENT-APPENDIX.md`](DEVELOPMENT-APPENDIX.md) | 历史沿革（每节 `[附录·历史]`，数字为当时读数） | 附录·不构成判据 |
| [`../AGENTS.md`](../AGENTS.md) | FC-27 禁改区三条硬约束与退出码语义 | **当前规格** |

## 2. 当前规格（与代码同步维护）

| 文件 | 管什么 |
|---|---|
| [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) | **系统总览（新读者从这进）**：架构八层 / 十一角色职责与协作 / 17 张表与文件契约 / 一次运行的完整生命周期 / 收工门八格四态与退出码 0–1–2 / 证据与签名链 / 判据族与"tests 不随仓库交付"的本机门边界 / 当前状态与已知边界；每个数字带现算命令（2026-11-21 新增） |
| [`ROLE-SPECS.md`](ROLE-SPECS.md) | 十一个角色（A–H V L + 主控 M）的职责面 / 动作表 / 边 / 写集 —— **只放规格（判据）** |
| [`DESIGN-BASELINE.md`](DESIGN-BASELINE.md) | **现行设计基线**：51 条（B01–B51）＋六层权威序（§1）＋判级规则（甲乙丙丁）；判据 `tests/test_design_baseline_is_present.py`（文件在 / 51 条在 / 顶部指针 / INDEX 登记） |
| [`ROLE-GUIDE.md`](ROLE-GUIDE.md) | **角色指南（生成物）**：十个角色 + 主控逐一介绍 —— 角色设定 / 具体职责 / 协作面 / 工具面 / 主要读写（由 `tools/write_system_docs.py` 现算，判据 `tests/test_system_docs_are_generated.py`） |
| [`SYSTEM-COMPONENTS.md`](SYSTEM-COMPONENTS.md) | **组件总览（生成物）**：协作系统各主要组件逐一介绍 —— 功能 / 实现细节 / 落点 / 守着它的判据 |
| [`ROLE-SPECS-APPENDIX.md`](ROLE-SPECS-APPENDIX.md) | `ROLE-SPECS.md` 的**实测附录**：工具面明细 / 自检实测 / R0.1–R0.3 / M.4.2–M.4.3 / S1–S3（**读数带日期、不构成判据**） |
| [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md) | 各角色自检的**失败项台账**（待修缺陷证据，不是文档问题） |
| [`LEAN-MODES.md`](LEAN-MODES.md) | 有 Lean / 无 Lean 两模式的完整矩阵：开关、动作可用面、证据上限、收工门各格 |
| [`TWO-AXES-GRADE-AND-KIND.md`](TWO-AXES-GRADE-AND-KIND.md) | **等级（`GRADES`）与档位（`EVIDENCE_KINDS`）是两个轴**：五元位 ⇒ 等级（32 组现算）、五元位 ⇒ 档位（逐格标"不由五元位决定"并给出三处真落点）、等级 ⇄ 档位的现场横表（真机 77 工作区 / 3627 行 + 夹具）与两组反例；术语校准表（"证据等级"→"证据档位"）逐处登记。表由 `tests/test_two_axes_grade_and_kind.py` 逐格比对（改错一格即红） |
| [`READING-MAP.md`](READING-MAP.md) | 大文件的行数与「该读哪一段」的索引 |
| [`PROMPT-HISTORY.md`](PROMPT-HISTORY.md) | **提示词版本账**：每抬一格 `agent_prompts.PROMPT_VERSION` 在这里追加一段（2026-11-20 从 `agent_prompts.py` 逐字节搬出；**当前行数不写死**，现算见 §5「文档行数」—— 它随每次抬版本增长）。抬版本时往本文件末尾写；判据 `tests/test_the_prompt_history_is_the_only_ledger.py` 钉两件事 —— 源码里一段不留、本文件末节标题 == `PROMPT_VERSION` |
| [`PRESET-RETIREMENT.md`](PRESET-RETIREMENT.md) | **预设（presets）退役记录 + 两根轴**：写死的提示词正文归声明面（`specs/<role>.py`）而运行时值归 settings / config.yaml；为什么曾经有一层预设（`draft/103` §4.1b 的"写死的块由哪段文件给"）、为什么 2026-11-22 退役（随包预设只有 A 一份、机制没有第二个用户、那套东西的唯一效果是 A 的正文与同族 policy 分家）、正文现在住 `specs/a.py::SEARCH_STYLE` 并由 `agent_prompts` 注册成 `A_SEARCH_STYLE` 段（号 2000 不变）—— 十一格渲染逐字节不变，判据 `tests/test_presets_retired.py` |
| [`USER-GUIDE.md`](USER-GUIDE.md) | 用户视角：从哪进、怎么建项目、产物在哪、出错先看哪（CLI 一节含四个入口与 28 行新老对照表） |
| [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md) | **CLI 侧用户说明书**（2026-11-21 新增）：装 / `init` / 起一趟（`start` 与 `--dry-run`、`--seed-literature`）/ 看进度（`status`·`stats gates`·`closing`·`status-report`）/ 插话·答问·叫停 / 续跑与切换 / 常见错误与三态读法 —— 每条命令都实跑过（附录 A 给"命令 → 退出码 → 关键输出"清单）；网页侧不在这里，看上一行 |
| [`USER-GUIDE-WEB.md`](USER-GUIDE-WEB.md) | **Web 侧用户说明书**（2026-11-22 新增，同日 GUIDE-WEB-REFRESH 复核）：起服务两档（只读 / `--allow-writes`）· 端口与 `--root` 陷阱 · 十页各读什么（含"Compliance 不是独立路由"）· **十一条 POST 写端点**的实跑请求与回执（含 2026-11-21 落地的 `/api/ack` 收口 · `/api/void` 作废 · `/api/stop/clear` 撤销叫停，写端点条数以 `webui/writes.py:ROUTES` 现算为准）· CSRF 怎么拿（页面 / 脚本）· 只读档能做什么 · `GET /api/actions` 网页操作历史的用法 · 常见 403/400/409/404 的 `kind` 与修法 · 安全注意 · 这一版还没有的功能（页面切工作区 / `/compliance` 独立页）—— 每条响应都是临时实例上真发出来的（附录 A 给"URL/方法 → 状态码 → 关键字段"清单，A.7 是三条新端点的复核，附录 B 给复跑脚本与"说明书端点 ⊆ ROUTES"自检） |
| [`CLI-CONTRACT.md`](CLI-CONTRACT.md) | `inspect` 那一组 `--json` 的机器可读契约：外层四格 / 每条命令的 `data` 字段 / 三态语义 |
| [`USER-TEST.md`](USER-TEST.md) | 用户侧验收剧本 |
| [`FORMAL-TOOLCHAIN.md`](FORMAL-TOOLCHAIN.md) | 证明检查器桥接层的接法与失败分类 |
| [`FC27-PENDING-LEAN.md`](FC27-PENDING-LEAN.md) | 本批 Lean 改动的待批清单（**需要人审**，不由 AI 代签） |
| [`FC27-SIGNING-GUIDE-2026-10-27.md`](FC27-SIGNING-GUIDE-2026-10-27.md) | **给人看的签字操作单**：本批 39 条受保护路径怎么签（`scripts/noai_batch_sign.py`）、三条硬边界、签完怎么验、工具会拒的六种情形（判据 `tests/test_fc27_signing_guide_is_usable.py`） |
| [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) | 禁改区治理流程：谁能批、批几个、台账怎么写 |
| [`KNOWN-UNWIRED.md`](KNOWN-UNWIRED.md) | 已知未接线：`src/agentflow/tools/` 下哪个 `*_tools.py` 没被 `tools/__init__.py` 的 `_MODULES` 装配（现读清单——改了装配就要回来改它） |
| [`GUARDS.md`](GUARDS.md) | **三件只读护栏的最小说明**（2026-11-21 新增）：`wellformed/`（产物畸形 13 类统一判据）、`sysguard.py` + `sysresidue.py`（系统自动写点的 `refused/derived/unchecked` 读数）、`seedinject.py`（种子投放，只放文件不入库）—— 各自给代码落点、读数入口与判据 |
| [`AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04.md`](AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04.md) | 2026-11-04 的**提示词↔工具面一致性审查 + 两条凭据通道 + 委托入库 + 依赖面**交接：8 条口径（附业主原话 / draft 出处）、按面分组的 commit 与一句话、4 条已知缝隙、p234–p238 的 warm 账与冻结账、FC-27 待批 16 条清单（当次读数、带日期；判据本体散在 `tests/test_mapping_three_known_gaps.py` / `tests/test_e_gets_its_v_sign_like_f.py` / `tests/test_no_model_means_no_merge.py` 一族；**只因源码里有逐字引用它的白名单条目，留在 docs/ 而不退役**） |

## 3. 历史证据（**不构成判据**，但被代码注释与其它文档大量引用，故保留）

这些是「当时的提案 / 当时的停摆记录」。它们解释**为什么现在是这样**，
但不描述**现在是什么**。改动它们等于改历史；引用时请写成「历史依据」。

- `../NOAI-REVIEW-REGISTER.md` —— FC-27 的逐条审计台账
- `PROPOSALS.md` —— 提案总集（体量最大、被引用最多）
- `PROPOSAL-side-effect-axes.md`
- `SCHEMA-MIGRATION-PROPOSAL-claims.md`、
  `SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`
- `TOOLBOX-DRAFT-roles.md`、`ROLE-SPECS-DRAFT-N-O-Q.md`
- `USER-END-DSH-STYLE.md`

### 3.1 历史送审页 / 停摆记录 / 复算证据：谁被谁取代

**只在本索引里标注，不改那些文档的正文**（改它们等于改历史）。判据：`tests/test_docs_index_covers_every_doc.py`
要求盘上每一份 `docs/*.md` 都在本索引里出现一次，或登记进 §6「不入册」。

| 文件 | 日期 | 已被谁取代 / 备注 |
|---|---|---|
| `FC27-PENDING-LEAN.md` | 2026-10-17 | 已被 2026-10-19 与 2026-10-21 那两批送审页取代；**已退役 → `draft/archive-FC27-PENDING-LEAN.md`**（2026-11-21 CLEAN-ALIGN） |
| `FC27-REVIEW-2026-10-19.md` | 2026-10-19 | 已被 `FC27-PENDING-2026-10-21.md` 取代；**已退役 → `draft/archive-FC27-REVIEW-2026-10-19.md`**（2026-11-21 CLEAN-ALIGN） |
| `FC27-PENDING-2026-10-21.md` | 2026-10-21 | 与 `FC27-PENDING-CLEANING-2026-10-21.md` 同日**并列**（前者功能改动、后者只碰注释与 docstring，它自己在开头点名"上一批见…"）；这两批之后没有更晚的送审页。**这份留在 docs/**：`tests/test_deprecated_forms_are_gone.py` 的 `PHRASE_ALLOWED` 按路径登记了它（两向判据：移走会让"登记过期"变红） |
| `FC27-PENDING-CLEANING-2026-10-21.md` | 2026-10-21 | 同上（清洁批次，机器证据见它自己的 §3） |
| `NOAI-SUSPENSION-2026-09-25.md` | 2026-09-25 | 已被 `NOAI-SUSPENSION-2026-09-28.md` 取代（更晚的一次临时开放记录）；**已退役 → `draft/archive-NOAI-SUSPENSION-2026-09-25.md`**（2026-11-21 CLEAN-ALIGN） |
| `NOAI-SUSPENSION-2026-09-28.md` | 2026-09-28 | 目前最晚的一次开放记录，无后续；**已退役 → `draft/archive-NOAI-SUSPENSION-2026-09-28.md`**（2026-11-21 CLEAN-ALIGN） |
| `REPRO-eval-results-no-producer.md` | 2026-10-21 | 复算证据：`test_eval_results_has_no_producer.py` 那三条读数的原文（从判据 docstring 搬出来是为了保住转义序列）；它随那条判据活着，不是过时文档 |

### 3.2 已退役（2026-11-21 CLEAN-ALIGN 移到 `draft/`，本仓不再跟踪）

口径：**一次性取证说明 / 旧计划 / 已被取代的送审页**从交付面移走，原件改名
`archive-<原名>` 落 `draft/`（该目录在 `.gitignore` §448 里，不进仓）；正文一字不改 ——
退役的是"它在交付面上的位置"，不是它记的事。下表逐条给退役理由与复算入口。

| 原路径 | 退役理由 |
|---|---|
| `docs/WIRING-AUDIT-2026-10-27.md` | 当次接线审计（带日期读数）；现行面由 `KNOWN-UNWIRED.md` + `tests/test_wiring_edges.py` 承担 |
| `docs/AUDIT-VSIGN-5ROLES-E-2026-11-03.md` | 当次五方签字审计（带日期读数）；判据本体在 `tests/test_e_gets_its_v_sign_like_f.py` 一族 |
| `docs/RUN-2026-11-04-PAPER-REWRITE-BIG.md` | 当次真机收工总账（带日期读数），不构成判据 |
| `docs/D-COLLAB-AND-MANUSCRIPT-UNIFICATION-2026-11-05.md` | 当次交接记录；现行口径在 `ROLE-SPECS.md` 与 `tests/test_f_and_b_manuscripts_are_one_implementation.py` |
| `docs/REHEARSAL-A-LITERATURE-FLOW.md` | 当次彩排记录；判据本体在 `tests/test_rehearsal_a_literature_flow*.py` |
| `docs/NOAI-SUSPENSION-2026-09-25.md` / `…-09-28.md` | 已被取代的临时开放记录（见 §3.1） |
| `docs/NOAI-CHANGE-LIST-management.md` | 旧改动清单（过程件）；治理现行面见 `NOAI-GOVERNANCE.md` 与 `../NOAI-REVIEW-REGISTER.md` |
| `docs/SCHEMA-DRAFT-management.md` | 旧 schema 草案（旧计划） |
| `docs/SCHEMA-MIGRATION-PROPOSAL-review-axis.md` | 旧提案（review 轴） |
| `docs/ROLE-SPECS-DRAFT-V.md` | 旧角色草案（V 已按 `ROLE-SPECS.md` 落地） |
| `agentflow/temp/cc3/REPORT-CC3.md`、`temp/cc4/REPORT-CC4.md`、`temp/rs/RS-REHEARSAL-20261115.md`、`temp/vf/REPORT-VF.md` | 一次性路交付/彩排报告（`temp/` 按 `AGENTS.md` R2 只放探针；这四份是过程件） |

**为什么还有几份历史件留在 `docs/`**：`tests/test_docs_index_covers_every_doc.py` 的反真空下限是
`MIN_DOCS = 30`（盘上 `docs/*.md` 少于 30 份它就红）。本轮退役 11 份 `docs/*.md` + 4 份 `temp/`
报告 ⇒ 退役当刻盘上 34 份（含本轮新增的 `GUARDS.md` 与本索引），仍贴着下限附近。**今天的份数以
`(Get-ChildItem docs/*.md).Count` 现读为准 —— 这里刻意不写当前份数**（并发下写死一个数第二天就过期）。**剩下的提案/附录类**
（`PROPOSALS.md`、`PROPOSAL-side-effect-axes.md`、`SCHEMA-MIGRATION-PROPOSAL-claims.md` /
`…-usage-ledger-idem-key.md`、`TOOLBOX-DRAFT-roles.md`、`ROLE-SPECS-DRAFT-N-O-Q.md`、
`DEVELOPMENT-APPENDIX.md`、`ROLE-SPECS-APPENDIX.md`、`../NOAI-REVIEW-REGISTER.md`）**本轮不退役**，
理由逐条：`PROPOSALS.md` 被源码/测试/文档 70+ 处逐字点名（搬走就是 70+ 处断链）；
`ROLE-SPECS-DRAFT-N-O-Q.md` 被 `tests/test_role_specs_complete.py` 直接读；其余是同族的
历史提案与实测附录，且都还被人读。要在**改判据下限**（或业主直接裁定）之后再退一批 ——
这属于测试与业主口径，不由本文单方面改。

## 4. 设计理由（与代码冲突时以代码为准）

`../DESIGN.md`、`../DESIGN-ROLES.md`、`../DESIGN-TOOLS.md`、`../DESIGN-CONDUCTOR.md`、
`../DESIGN-INTERACTIONS.md` —— 回答「当初为什么这么设计」，**不是**行为规格。
读它们是理解取舍；查行为读代码与判据。

### 已知的整理欠账（如实登记）

1. ~~`DEVELOPMENT.md`（约 194 KB）与 `ROLE-SPECS.md`（约 241 KB）体量过大~~ **已拆完（2026-10-18）**：
   `DEVELOPMENT.md` → 入口 + `DEVELOPMENT-SPEC.md`（规范）+ `DEVELOPMENT-APPENDIX.md`（历史）；
   `ROLE-SPECS.md`（拆分前共 2644 行，2026-10-18 当时）→ `ROLE-SPECS.md`（规范）+
   `ROLE-SPECS-APPENDIX.md`（实测附录）+ `SELF-CHECK-FINDINGS.md`。
   **这四份的当前行数刻意不写死** —— 写死一个数，下一次拆分或增长它就变成「看着有、其实在说谎」
   的读数（本行原先的 `入口 42 行` / `1354` / `374` / `1576` / `1091` 就是这么漂掉的）；
   现行行数一律现算，命令见 §5「文档行数」那一行。
   原始欠账前半句（
   其中不少读数是 2026-09 的。计划拆成「规范（重写、短）」＋「附录（保留、只作查证）」；
   **2026-10-18 已拆**：`ROLE-SPECS.md`（规格）＋ `ROLE-SPECS-APPENDIX.md`（实测附录）。
   分层已由七层更正为八层（新增 Web/用户端）；
2. 「哪份算数」这件事**只有本索引一处维护** —— 所以**新增文档必须在这里登记**，
   否则下一个人只能靠猜；
3. `DESIGN*.md` 五份尚未逐句核对与当前代码的一致性；引用它们时请只引「理由」，不引「行为」。

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
               'agentflow/docs/DEVELOPMENT-SPEC.md','agentflow/docs/DEVELOPMENT-APPENDIX.md',
               'agentflow/docs/ROLE-SPECS.md','agentflow/docs/ROLE-SPECS-APPENDIX.md') {
  "{0}: {1} 行" -f $f, (Get-Content $f).Count
}
```

> 本目录的其余说明（历史沿革、发布检查入口 `tools/release_all.py` 与
> `scripts/release_check.py` 的关系）见 `PROPOSALS.md` P-11；那份是历史依据。

## 6. 不入册（**显式登记 + 理由**，不是"漏了"）

新增一份 `docs/*.md` 而不在 §1–§3 里登记，判据 `tests/test_docs_index_covers_every_doc.py`
会红。确实不该入册的（草稿、一次性复算输出、给外部看的临时纸），登记到这张表里并写清为什么 ——
"没登记"与"登记了不打算登记"必须在机器读数上分得开。

| 文件 | 为什么不入册 |
|---|---|
| （今天没有这一档） | 现盘每一份 `docs/*.md`（含本索引与 2026-11-21 新增的 `USER-GUIDE-CLI.md`、`SYSTEM-INTRO.md`）都在 §1–§3 里出现过或登记进 §3.2 —— **这里刻意不写份数**：`docs/` 在并发开发下随时增减，写死一个数第二天就过期；"盘上有几份"以 `(ls docs/*.md).Count` 现读为准 |
