# `FIX15` 窗口收工账（2026-09-27 22:49–23:21；修第 12 轮的 7 条 finding）

## F15.1 四个写者的交付与读数

| 写者 | 文件（改前 → 改后） | 自证读数 |
|---|---|---|
| `B-FIX15-providers` | `providers.py` d03b96ca…/110390 → **9ba0d546…/111179**；`tests/test_providers_topicality.py` 03370d12…/17309 → **fb3e87d…/24565**（12→15 例） | R12-R3-1：拒绝路径三字段一并复位（含空题面提前 return）；正控 2 条绿、负控 `2 failed,13 passed`（打印上一跑检索串）。R12-R3-2：`_provider(stub)` 真绑定；正控 `calls=1`、负控 `1 failed,14 passed`（`calls=0`，装置 `MODULE_HTTP_IS_TRIPWIRE True / TRIPWIRE_CALLS 1` ⇒ **零出网**） |
| `B-FIX15-evidence` | `evidence.py` ed211225…/77582 → **3be6a46a…/92482**；`tests/test_evidence.py` 1e21470c…/51293 → **97c1c250…/69111**（68→77 例） | `SOURCE_STATUSES` 加第三态（`query_not_applicable_cjk` / `query_empty`，与 providers 常量逐字相同）；`_source_detail()` 折进 `topicality_buckets`（三档+total+complete）/`topicality_notes`（逐条 filter_note，超限记 truncated）/`topicality_state`；正控 77 passed；负控(b) 整树副本注入新判据 ⇒ 9 failed/68 passed。**整仓全量 2496 passed, 3 skipped, 8 deselected, 1 xfailed** |
| `B-FIX15-noai` | `noai_gate.py` e66ea356…/232478 → **f01d41ae…/233904**；`tests/test_noai_gate.py` 0f600cab…/124305 → **80b14d6a…/129056** | R12-R1d-1：`main` 显式解析两个路径（`--root` 生效、`--agents-md` 加 `type=Path` 当路径读），旧用例改成真的读文件；R12-R1d-2：读失败自成 `exit 2`（不动函数级契约）。副本六档 **0/0/1/2/2/2**、副本内 **136 passed**（改前 134，新增 2 条） |
| `B-FIX15-register` | `NOAI-REVIEW-REGISTER.md` 3663c0fb…/61940 → **6f55585f…/64487**；`tests/test_release_all.py` c520225e…/115391 → **b8c04ea9…/127872**（58→**60 collected**） | R6-AN-2：register 明确降为**历史档案**（:39–:49 声明 + §7/§7.2 改成"不再维护当前值" + `当次/本轮/本次`→`该轮` 50 处）+ 配套把 `doc_test_reference_problems` 扩到含 register（**并发现只加文档名不够**：`:405` 的"原写"记号让判据整行跳过 ⇒ 把更正说明拆到单独一行，命令行才落进覆盖面）；R6-AN-1 ③：`_AGENTFLOW_TOP_LEVEL_MODULES` 登记 **40** 个顶层模块 + 集合相等判据；负控 Arm B/C 各 2 failed |
| 父代理 | `DEVELOPMENT.md`（`noai_gate_pytest_collected` **119 → 121**，三处） | `-k development_md` 2 passed、`-k "manifest_and_pytest or pytest_count_criteria"` 1 passed（跨写者那 3 条红消失） |

## F15.2 签字（所有者授权选项 A；本窗口改到的 FC-27 文件）

```text
· `src/agentflow/providers.py`   9ba0d546e507…/111179 B  → `--baseline` + 两遍 `--approve` ⇒ **[approved] 2/2**
· `scripts/noai_gate.py`         f01d41aedc11…/233904 B  → 同上 ⇒ **[approved] 2/2**
· 台账：entries 23 / reviewers 元素 44 / 分布 {0:1, 2:22} / 0 签只剩 `.noai-approvals.json`（不能自签 = 设计）
· `--check-consistency` exit 0；`--check-ledger` exit 0
```

## F15.3 新登记的两行残余（都不在写者写面内，进下一窗口/回写）

```text
① provider 统计面没跟上第三态：`MultiProvider.last_stats[*].status` 与 `PROVIDER_STAT_STATUSES`
   仍是 `('not_run','ok','failed')`，同一次"这一问没发出去"在 evidence 侧是第三态名、在 providers 统计面仍是 failed
   （`tests/test_providers_topicality.py:348-351` 逐字钉着）⇒ 落在 `providers.py`（**FC-27**，要签字）
② `docs/PROPOSALS.md:4787` 的形态描述已过期（写的是改前"sources_detail 里 status=ok / rejected=0"）⇒ 回写时订正
```

## F15.4 一条要写进以后每一份派单的教训（`B-FIX15-register` 实测出来的）

```text
"把文档名加进判据的覆盖面"**不足以**让悬空引用类 finding 的负控变红 —— 因为判据对含"原写/改前"等
更正记号的行**整行跳过**（本仓 `_CORRECTION_MARKERS` 的既有设计）。要让覆盖面真的咬住，必须把
"更正说明"与"被更正的命令行"**拆到不同行**。只加文档名会得出"配套无效"的错误结论（Arm B0 vs B1）。
```
