# 三件只读护栏：产物畸形 / 系统写点 / 种子投放（2026-11-21 新增，最小说明）

> 这三件同一天落地，此前没有任何文档面说它们是什么。本文只做**入口说明**：
> 每件给一句话、代码落点、读数入口与判据。**不铺开写**设计与取舍 —— 设计在各自
> 模块 docstring 里，改行为读那里。

## 1. `wellformed/` —— 产物畸形的统一判据（MALFORM 路）

- **是什么**：把"这个工作区里的产物有没有畸形"收成一处判据 —— 13 类产物
  （`KINDS`：vsigns / literature / relations / statements / lit_candidates / tasks /
  usage_ledger / sessions / manuscripts / proof_reports / acceptance / artifacts /
  roster_retired），每类一根轴：形状 / 词表 / 内部一致性 / 跨表指向。
- **三态**：`ok` / `malformed`（带 Finding：文件、位置、逐字读数、怎么改）/
  `unchecked`（没查成）。`unchecked` 不折成 `ok`。
- **落点**：`src/agentflow/wellformed/`（`__init__.py` 收口，规则按类别各一个模块；
  `RULES[kind][name]` 是登记表）；只读读数面接在 `statusreport.collect` 的
  `wellformed` 一格；**不进收工门、不加 blocker**（业主 2026-11-21：畸形要看得见，
  不是再拦一道）。
- **读数入口**：`python scripts/check_wellformed.py --root projects/<ws> [--kind ...] [--json]`
  （0 = 全 ok / 1 = 有畸形 / 2 = 没查成）。
- **判据**：`tests/test_wellformed_tool.py`、`tests/test_reading_map.py`。

## 2. `sysguard.py` + `sysresidue.py` —— 系统自动产物的写点读数（SYSGUARD / SYSRESIDUE 路）

- **是什么**：系统自己写的字段与文件，必须由**写点**保证每一格（不让模型补、不靠读侧宽容）。
  `sysguard` 给这一族写口一个统一读数形状（`ok` / `refused` / `derived` / `unchecked`），
  `sysresidue` 是剩下四处写点的校验：`literature.processed`、`bits.evidence.optimized_by_proof`、
  `runs.spend` 自报对账、`literature.dedup_key`。
- **落点**：`src/agentflow/sysguard.py`（`WriteReading` / `write_reading` / `record_reading` /
  `read_readings` / `summarize`）、`src/agentflow/sysresidue.py`（四处：`settle_processed` /
  `optimized_cells_problems` / `spend_reconcile` / `literature_dedup_cells`）。
- **台账**：`<工作区>/out/sysguard/write-readings.jsonl`（只读读数，不是表、不进重建、
  不进 `ARTIFACTS.jsonl`）。`refused` / `derived` 计数进 `errorstats` 过程类目
  `write_point_guarded`（看得见、不计错、不当门）。
- **判据**：`tests/test_sysguard_write_points.py`、`tests/test_sysresidue_write_points.py`。

## 3. `seedinject.py` —— 文献种子投进新工作区（SEEDINJECT 路）

- **是什么**：把 `agentflow/seed/literature/` 这份种子包原样复制进**新建**工作区的
  `library/`，并在工作区根落一份 `SEED-README.md`。**只放文件、不写台账**：不打开也不创建
  `data/literature.json`（业主 2026-11-21：不直接入库 —— 判收是 A 的动作）。
- **开关**：`agentflow start --seed-literature` / `agentflow init --seed-literature`，
  默认**关**；只对"真的是新建"生效（`data/` 已在 ⇒ 不投）；`SEED-README.md` 在 ⇒ 幂等返回读数。
- **落点**：`src/agentflow/seedinject.py`（`seed_workspace` / `read_seed_reading` /
  `candidate_chain_lines`）；种子包口径与判收链见 [`../seed/literature/README.md`](../seed/literature/README.md)。
- **复算**：`python scripts/seed_corpus.py --verify`；判据 `tests/test_seed_corpus.py`、
  `tests/test_seed_readme_says_the_chain.py`、`tests/test_a_workspace_literature_is_not_already_registered.py`。
