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
| [`../DEVELOPMENT.md`](../DEVELOPMENT.md) | **入口（42 行）**：职责 + 两份指针 + 改代码前先读哪三节 | 入口 |
| [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md) | **开发规范本体**（每节 `## [规范]`）：改哪里、怎么验、判据在哪 | **当前规格** |
| [`DEVELOPMENT-APPENDIX.md`](DEVELOPMENT-APPENDIX.md) | 历史沿革（每节 `[附录·历史]`，数字为当时读数） | 附录·不构成判据 |
| [`../AGENTS.md`](../AGENTS.md) | FC-27 禁改区三条硬约束与退出码语义 | **当前规格** |

## 2. 当前规格（与代码同步维护）

| 文件 | 管什么 |
|---|---|
| [`ROLE-SPECS.md`](ROLE-SPECS.md) | 十个角色的职责面 / 动作表 / 边 / 写集 —— **只放规格（判据）** |
| [`ROLE-SPECS-APPENDIX.md`](ROLE-SPECS-APPENDIX.md) | `ROLE-SPECS.md` 的**实测附录**：工具面明细 / 自检实测 / R0.1–R0.3 / M.4.2–M.4.3 / S1–S3（**读数带日期、不构成判据**） |
| [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md) | 各角色自检的**失败项台账**（待修缺陷证据，不是文档问题） |
| [`LEAN-MODES.md`](LEAN-MODES.md) | 有 Lean / 无 Lean 两模式的完整矩阵：开关、动作可用面、证据上限、收工门各格 |
| [`READING-MAP.md`](READING-MAP.md) | 大文件的行数与「该读哪一段」的索引 |
| [`USER-GUIDE.md`](USER-GUIDE.md) | 用户视角：从哪进、怎么建项目、产物在哪、出错先看哪（CLI 一节含四个入口与 28 行新老对照表） |
| [`CLI-CONTRACT.md`](CLI-CONTRACT.md) | `inspect` 那一组 `--json` 的机器可读契约：外层四格 / 每条命令的 `data` 字段 / 三态语义 |
| [`USER-TEST.md`](USER-TEST.md) | 用户侧验收剧本 |
| [`FORMAL-TOOLCHAIN.md`](FORMAL-TOOLCHAIN.md) | 证明检查器桥接层的接法与失败分类 |
| [`FC27-PENDING-LEAN.md`](FC27-PENDING-LEAN.md) | 本批 Lean 改动的待批清单（**需要人审**，不由 AI 代签） |
| [`FC27-SIGNING-GUIDE-2026-10-27.md`](FC27-SIGNING-GUIDE-2026-10-27.md) | **给人看的签字操作单**：本批 39 条受保护路径怎么签（`scripts/noai_batch_sign.py`）、三条硬边界、签完怎么验、工具会拒的六种情形（判据 `tests/test_fc27_signing_guide_is_usable.py`） |
| [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) | 禁改区治理流程：谁能批、批几个、台账怎么写 |
| [`KNOWN-UNWIRED.md`](KNOWN-UNWIRED.md) | 已知未接线：`src/agentflow/tools/` 下哪个 `*_tools.py` 没被 `tools/__init__.py` 的 `_MODULES` 装配（现读清单——改了装配就要回来改它） |
| [`WIRING-AUDIT-2026-10-27.md`](WIRING-AUDIT-2026-10-27.md) | 2026-10-27 夜的**接线审计**：逐条「实现了但没接上」的落点与复跑命令（当次读数、带日期；判据本体在 `tests/test_wiring_edges.py`） |

## 3. 历史证据（**不构成判据**，但被代码注释与其它文档大量引用，故保留）

这些是「当时的提案 / 当时的停摆记录」。它们解释**为什么现在是这样**，
但不描述**现在是什么**。改动它们等于改历史；引用时请写成「历史依据」。

- `../NOAI-REVIEW-REGISTER.md` —— FC-27 的逐条审计台账
- `NOAI-SUSPENSION-2026-09-25.md` / `NOAI-SUSPENSION-2026-09-28.md`
- `NOAI-CHANGE-LIST-management.md`
- `PROPOSALS.md` —— 提案总集（体量最大、被引用最多）
- `PROPOSAL-side-effect-axes.md`
- `SCHEMA-DRAFT-management.md`、`SCHEMA-MIGRATION-PROPOSAL-claims.md`、
  `SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`、
  `SCHEMA-MIGRATION-PROPOSAL-review-axis.md`
- `TOOLBOX-DRAFT-roles.md`、`ROLE-SPECS-DRAFT-N-O-Q.md`、`ROLE-SPECS-DRAFT-V.md`
- `USER-END-DSH-STYLE.md`

### 3.1 历史送审页 / 停摆记录 / 复算证据：谁被谁取代

**只在本索引里标注，不改那些文档的正文**（改它们等于改历史）。判据：`tests/test_docs_index_covers_every_doc.py`
要求盘上每一份 `docs/*.md` 都在本索引里出现一次，或登记进 §6「不入册」。

| 文件 | 日期 | 已被谁取代 / 备注 |
|---|---|---|
| `FC27-PENDING-LEAN.md` | 2026-10-17 | 已被 2026-10-19 与 2026-10-21 那两批送审页取代 |
| `FC27-REVIEW-2026-10-19.md` | 2026-10-19 | 已被 `FC27-PENDING-2026-10-21.md` 取代 |
| `FC27-PENDING-2026-10-21.md` | 2026-10-21 | 与 `FC27-PENDING-CLEANING-2026-10-21.md` 同日**并列**（前者功能改动、后者只碰注释与 docstring，它自己在开头点名"上一批见…"）；这两批之后没有更晚的送审页 |
| `FC27-PENDING-CLEANING-2026-10-21.md` | 2026-10-21 | 同上（清洁批次，机器证据见它自己的 §3） |
| `NOAI-SUSPENSION-2026-09-25.md` | 2026-09-25 | 已被 `NOAI-SUSPENSION-2026-09-28.md` 取代（更晚的一次临时开放记录） |
| `NOAI-SUSPENSION-2026-09-28.md` | 2026-09-28 | 目前最晚的一次开放记录，无后续 |
| `REPRO-eval-results-no-producer.md` | 2026-10-21 | 复算证据：`test_eval_results_has_no_producer.py` 那三条读数的原文（从判据 docstring 搬出来是为了保住转义序列）；它随那条判据活着，不是过时文档 |

## 4. 设计理由（与代码冲突时以代码为准）

`../DESIGN.md`、`../DESIGN-ROLES.md`、`../DESIGN-TOOLS.md`、`../DESIGN-CONDUCTOR.md`、
`../DESIGN-INTERACTIONS.md` —— 回答「当初为什么这么设计」，**不是**行为规格。
读它们是理解取舍；查行为读代码与判据。

### 已知的整理欠账（如实登记）

1. ~~`DEVELOPMENT.md`（约 194 KB）与 `ROLE-SPECS.md`（约 241 KB）体量过大~~ **已拆完（2026-10-18）**：
   `DEVELOPMENT.md` → 入口 42 行 + `DEVELOPMENT-SPEC.md` 1354 行（规范）+ `DEVELOPMENT-APPENDIX.md` 374 行（历史）；
   `ROLE-SPECS.md` 2644 → **1576 行**（规范）+ `ROLE-SPECS-APPENDIX.md` 1091 行（实测附录）+ `SELF-CHECK-FINDINGS.md`。
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

# 全量判据（约 25 分钟）
python -m pytest -q

# 禁改区门（命中 ⇒ 退出码 1，需要 2 名 reviewer 批准）
python scripts/noai_gate.py --git
```

> 本目录的其余说明（历史沿革、发布检查入口 `tools/release_all.py` 与
> `scripts/release_check.py` 的关系）见 `PROPOSALS.md` P-11；那份是历史依据。

## 6. 不入册（**显式登记 + 理由**，不是"漏了"）

新增一份 `docs/*.md` 而不在 §1–§3 里登记，判据 `tests/test_docs_index_covers_every_doc.py`
会红。确实不该入册的（草稿、一次性复算输出、给外部看的临时纸），登记到这张表里并写清为什么 ——
"没登记"与"登记了不打算登记"必须在机器读数上分得开。

| 文件 | 为什么不入册 |
|---|---|
| （今天没有这一档） | 33 份 `docs/*.md` 全部在 §1–§3 里出现过；将来真有临时件再往这里加一行 |
