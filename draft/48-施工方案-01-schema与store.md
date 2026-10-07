# draft/48 施工方案 01：`schema.py` / `store.py`（R-02 · R-05 · R-06 · F-01 · P-06 · P-07 · P-08 · E-09 · EE-06 · EE-07）

> 本文是把**已完成的**逐文件施工级调查转写成**可执行施工方案**。只写这一个文件；未改动仓库任何文件、
> 未跑 pytest、未跑模型、未跑网络、未跑 Lean、未跑会写盘的 `rebuild`。方法：`read` / `grep` / `glob` /
> `python -B -c`（只读统计与快照校验）。
> 每种读数都带来源标：**`[本次现算 + <命令>]`** = 本轮我在本会话里亲手跑出来的；**`[46-01 §Y.Z]`** =
> 从 `draft/46-施工级调查-01-schema与store.md` 抄来的（未再复算，照实标）；第三来源一律显式标注分级。

## 范围

| 项 | 内容 |
|---|---|
| 文件组 | `src/agentflow/schema.py`（2791 行）· `src/agentflow/store.py`（1449 行） |
| 覆盖条目 | R-02 · R-05 · R-06 · F-01 · P-06 · P-07 · P-08 · E-09 · EE-06 · EE-07（10 条） |
| 含直接调用点 | `agent_b/register_statement.py`（P-06/EE-07）· `tools/doc_tools.py`（P-07）· `claimanatomy.py`（P-07/EE-06）· `cli.py:328-336`（R-06）· `agent_e/run_experiment.py` + `agent_e/_support.py`（R-02 真凶，store 侧 0 改动） |
| 明确的**不施工**面 | E-09 加 `none` · EE-06 路线 1（`status` 进必填）与路线 3（删字段）· F-01 的 claims/Relation 派生等级 · R-02 的 store 侧计数器 · R-06 收窄 `except Exception` · P-08 的 schema 改动 |

## 依据清单（逐份 `draft/…` 路径）

| # | 文件 | 本文用到的节 | 用法 |
|---|---|---|---|
| 1 | `draft/46-施工级调查-01-schema与store.md`（550 行） | §0 ①–④、§1.1–§1.7、§2.1–§2.7、**§3 不可行/高风险表** | 落点、伪码、判定、负控、真机读数的主来源；**§3 的判定照抄，不重新裁定** |
| 2 | `draft/44-裁定登记册：全部待裁条目（分6批）.md` | 前面批次 0–5 的条目标题行 + **§19（J-01…J-27）** + §20 | 裁决建议（加/减/新）、触及面（`禁`/`提`/`行`/`读`/`文`）、施工级改判 |
| 3 | `draft/47-子代理报告登记与证据可信度分级.md` | §0 三级标记、§2 承重数字（第 17 组等）、§3 更正总账（C-2/C-13）、§4 未复核清单、§5 人裁点 | 哪些数字被复核过；哪些必须写成"未核实" |
| 4 | `draft/45-按文件改动清单与可行性论证.md` | **§1.1**（顶部有更正横幅） | 当时怎么想的；凡被 §19/`47` 证伪的前提**不采信** |

**`45` 顶部更正横幅与本文的关系（三处前提已被证伪，逐条照 `47` §3 执行）**：
① `45` §1.1 的"`LIT_MATCH_STATUSES` 增 `none`"（E-09）**不可行**（`47` 横幅第 1 条 + `46-01 §3`）；
② `45` §1.1 的"`claims[].status` 加进必填集"（EE-06）**不可行**（同上）；
③ `45` §1.1 的"`store.py` 回滚时推进计数器"（R-02 store 侧）**不可行**（同上，`47` §5 引 `46-01 §3`）。
另：`45` 另有三处前置被证伪（`temp/_sync_policy.py` 存在 / `extract` 非 0 调用 / 账本 51% 是口径错，见 `47` §3-C1/C6/C3），
它们**不在本组落点上**，本文只在"批次"一栏避免复用这些说法。

## 口径声明（两根工作区根，任何读数必须标明哪个根）

| 根 | 路径 | 目录数 | `data/*.json` 份数 | `counters.json` | `statements` 工作区数 |
|---|---|---|---|---|---|
| **根1** | `D:\Incubator\agentflow\projects` | 58 `[本次现算]` | 1029 `[本次现算]` | 57 `[本次现算]` | 57（138 行）`[本次现算]` |
| **根2** | `D:\Incubator\projects` | 23 `[本次现算]` | 375 `[本次现算]` | 22 `[本次现算]` | 1（0 行）`[本次现算]` |

**纪律**：
1. 本文每一处"真机读数"都先写根，再写读数（形如 `根1/p8c-…`）。两个根**不许合并算**——
   `47` §3-C3 已登记"合并算没有意义"（同类教训：`task_id=null` 根1 66% / 根2 0%）。
2. `46-01 §0` 里凡是**两根合计**的数（1322 / 1772 / 449 / 406），本文引用时写"两根合计"，
   并在需要根级分解时给出我自己的分根实测。
3. 本组施工涉及的读数口径一律**不新增**"合并根"的判据。

---

## §0 本组基线读数

### 0.1 历史快照兼容基线（**本组唯一的硬闸**）

```
命令（只读，1322 份逐份 validate_table）
python -B -c "…glob 两根 */data/*.json；按 S.TABLES 的 file 名归表；逐份 S.validate_table；
              分计 ValueError 与非 ValueError…"
```

| 读数 | 本次现算 | `46-01 §0①` | 结论 |
|---|---|---|---|
| 根1 `data/*.json` | 1029（counters 57）`[本次现算 + 上述命令]` | 1029（57） | 一致 |
| 根2 `data/*.json` | 375（counters 22）`[本次现算 + 上述命令]` | 375（22） | 一致 |
| 落到 `TABLES` 的份数 | **1322** `[本次现算 + 上述命令]` | 1322 | 一致（17 表 × 79 工作区 − `statements` 缺 21 份） |
| 非 TABLES | `{counters.json: 79, research_request_ledger.json: 3}` `[本次现算 + 上述命令]` | 同 | 一致 |
| **通过 / 失败(ValueError) / 逃逸(非 ValueError)** | **1322 / 0 / 0** `[本次现算 + 上述命令]` | 1322 / 0 / 0 | 一致 |

`46-01 §0①` 对 `draft/41` §3.7 的 969 份基线：口径一致，本次样本更大（两根全量 1322）。

### 0.2 三个候选改动的兼容性模拟（同进程改判据后重跑同一批 1322 份，只读）

| 改动 | 本次现算 | `46-01 §0②` | 结论 |
|---|---|---|---|
| A：`claims[].status` 必填 | **PASS 1270 / FAIL 52 / ESC 0** `[本次现算 + 同 §0.1 命令，逐表把 documents 的 claim 缺 status 判违规]` | PASS=1270 FAIL=52 | 逐字一致 |
| C：`LIT_MATCH_STATUSES += ("none",)` | **PASS 1322 / FAIL 0 / ESC 0** `[本次现算 + 同命令，进程内替换常量为 4 元组后重跑]` | 1322/0 | 逐字一致（**兼容 ≠ 可做**，见 §1.8） |
| E：`Statement.grade` 必填 | **PASS 1289 / FAIL 33 / ESC 0** `[本次现算 + 同命令]` | PASS=1289 FAIL=33 | 逐字一致 |

**读法**：A 与 E 是"加必填"的两个反例，各自当场打红 52 / 33 份历史快照 ⇒ 本组**只允许"放宽 + 带默认值新增"**。

### 0.3 题库读数（分根，两根合计在括号里）

| 表 | 根1 | 根2 | 两根合计 | 备注 |
|---|---|---|---|---|
| `statements` 行 | 138 `[本次现算]` | **0**（只有 1 份 `statements.json`，行数 0）`[本次现算]` | 138 | 与 `46-01 §0③` / `47` §2 第 17 组一致 |
| `bits` 非空 | 0 `[本次现算]` | 0 | **0/138** | `46-01 §0③` 同 |
| `evidence_kind` | `{cross_check:124, heuristic:8, proof:6}` `[本次现算]` | — | 同 | `46-01 §0③` 同 |
| `origin` | `{external_lit:125, own_result:13}` `[本次现算]` | — | 同 | `46-01 §0③` 同 |
| `quote_verified` | `{None:111, False:18, True:9}` `[本次现算]` | — | 同 | `46-01 §0③` 同 |
| `own_result` 带 `proof_text` | 13/13 全带 `[本次现算]` | — | 13/13 | `46-01 §1.2(c)` 同 |
| `experiments` 行 / `method` | 217 / `{numeric:143, formal:50, exhaustive_search:24}` `[本次现算]` | 189 / `{numeric:159, formal:30}` `[本次现算]` | 406 | 合计与 `46-01 §0③` 同 |
| `experiments` formal 的 `exit_code` | 50 行 `{None:41, 0:9}` `[本次现算]` | 30 行 `{None:4, 0:26}` `[本次现算]` | 80 行 | **`46-01 §0③` 写"formal 80 行 exit_code {None:45,0:35}"——两根合计相符；分根我这次给了新数** |
| `documents` 行 / `claims` | 69 / 281 `[本次现算]` | 7 / 168 `[本次现算]` | 76 / **449** | 合计与 `46-01 §0③` 同 |
| `claims.status` 非空 / `allowed_use` 非空 | 0 / 0 `[本次现算]` | 0 / 0 `[本次现算]` | **0/449、0/449** | 与 `47` §2 第 17 组一致 |
| `claims` 键全集 | 9 个 `[本次现算]` | 17 个 `[本次现算]` | 并集不含 `status`/`allowed_use` | `46-01 §0③` 说"18 个"（并集口径）；我按根分别数得 9 与 17，并集 18 与之相容 |
| `relations` 行 / `quote_verified` | 1652 / `{True:1646, False:6}` `[本次现算]` | 120 / `{True:108, False:12}` `[本次现算]` | **1772** / `{True:1754, False:18}`，**None 两根皆 0** | 与 `46-01 §0③`、§1.2(e) 同 |
| `literature` 行 / `matched` | 1003 / `{'': 1003}`（**全空串**）`[本次现算]` | 733 / `{None: 733}`（**全 None**）`[本次现算]` | 1736 | `46-01 §0③` 的 `{"":1003, None:733}` 即此；**三档（exact/partial/mismatch）两根各 0** |

**方法学更正（我自己的，必须摆出来）**：我第一次跑的累计脚本把根2 的行累加进了"根1"的输出里
（报出 `literature 1736 / relations 1772 / experiments 406` 挂在根1 名下），第二遍按根分开重算后才得
上表的分根值。上表是分开算的版本。

### 0.4 R-02 真机直接证据（根1 `p8c-fermat-shorter-proof`）

| 读数 | 本次现算 | `46-01 §0④` |
|---|---|---|
| `experiments` 行 | 4：`0000 formal []` / `0001 formal []` / `0002 exhaustive_search ["out/experiments/0002.log"]` / `0003 formal []` `[本次现算 + 只读 glob + 读 artifact_paths]` | 同 |
| 盘上日志 | `0000.log` 534 B `2046b2f0aa04aea8`；`0001.log` 534 B `e268de5b7f7a1cac`；`0002.log` 534 B `e268de5b7f7a1cac` `[本次现算，sha256 前 16 位]` | 字节数与哈希逐字一致 |
| 0001 与 0002 逐字节相同 | **是**（同 hash 同长度）`[本次现算]` | 同 |
| 无任何台账行引用的孤日志 | `0000.log`、`0001.log`（**2 个**）`[本次现算]` | 同 |
| `code_hash` 对照 | 行 `0002` 的 `code_hash=fb6863d8eefeb91c`，而 `0002.log` 实际 sha256 前 16 位 = `e268de5b7f7a1cac`（**不相等**）`[本次现算]`；`0000/0001/0003` 三行的 `code_hash` 为空 `[本次现算]` | `46-01`/`J-03` 只给了 `0000.log` 装的是 `flt-small-enum`、`fb6863d8eefeb91c` 那个 hash。**"artifact 文件 sha256 ≠ 行里的 code_hash"这一层本轮我第一次给出**，含义（`code_hash` 是脚本哈希而非日志哈希）**未核实**，见 §汇总"未核实项" |
| 全档案孤日志 | 3 工作区 5 个（`p5-review-t1:0000`、`p6e:0006,0008`、`p8c:0000,0001`）`[46-01 §0④]`（本轮**未复算**） | 同 |

### 0.5 三处负控探针的改前形态（`python -B -c` 只读，本会话实跑）

| # | 探针 | 改前结果 `[本次现算]` | 说明 |
|---|---|---|---|
| 1 | `Concept.validate()`，`related_concepts=["0001", 2]` | `TypeError: '<' not supported between instances of 'str' and 'int'` | R-05 行级内联件先抛 |
| 2 | `check_array_invariants("concepts", 同一对象)` | `TypeError`（同句） | R-05 表级也抛 |
| 3 | `validate_table("concepts", {rows:[{…related_concepts:["0001",2]}]})` | `TypeError`（**逃逸**，不是 `ValueError`） | 灾难恢复面 |
| 4 | `check_array_invariants("relations", 混类型 supporting_lit_ids)` | `TypeError`（同句） | R-05 第二类 |
| 5 | `row_from_dict("concepts", {"concept_id":"0003"})` | `TypeError: Concept.__init__() missing 2 required positional arguments: 'name' and 'definition'` | **R-06 不许收窄 `except` 的硬证据** |
| 6 | `Statement(origin="own_result", evidence_kind="proof", bits={}, proof_text="证明", quote_reason=…)`.validate() | **`None`（通过）** | EE-07："`evidence_kind=proof` 且 `bits={}` 今天完全合法" |
| 7 | 同 6 但 `proof_text=""` | `ValueError: origin='own_result' 必须给 proof_text…` | P-06 的改前必红对象 |
| 8 | `bits={}` 的行 与 不给 `bits` 的行 都通过 | 两者皆 `None` | `schema.py:1684` 的 `if self.bits:` ⇒ 空 bits 直接跳过，**"声明了五元位却一位都没记"没有任何判据** |

### 0.6 与既有测试的对照面（行号 `[本次确认]`，逐条 read 过）

| 文件:行号 | 断言原文（节选） | 本组谁会被它挡 |
|---|---|---|
| `tests/test_coverage_schema.py:77` | `test_check_array_invariants_rejects_unsorted_set_field`；`:89 assert len(bad) == 1`、`:91 assert "未升序去重" in bad[0]` | R-05（**必须保持绿**：文案不许改） |
| `tests/test_coverage_schema.py:110` 一族 | 重复元素亦然（同文件 `:94` 起的用例） | R-05（同上） |
| `tests/test_fc05_contract.py:66` | "集合字段由 `validate_table` **集中**检查（唯一权威点）" | R-05 的对账面（暂不动） |
| `tests/test_statements_table.py:142` | `def test_an_own_result_without_a_proof_cannot_enter(store)`；`:147 assert "proof_text" in msg and "自产" in msg` | **P-06 必红**（须改写，见 §1.3） |
| `tests/test_store_concurrency.py:229` | `assert store.read("counters")["counters"].get("concept", 0) == 0, "磁盘计数器应保持回滚后的值"` | **R-02 store 侧的反判据** |
| `tests/test_store_concurrency.py:234` | `assert cid == "0000", f"回滚后重新分配应仍从 0000 开始，实际拿到 {cid}（ID 空洞）"` | 同上 |
| `tests/test_store_concurrency.py:148` / `:164` / `:166` | `assert after == before, "回滚不彻底：磁盘上有文件被改动了"`；`assert read_data_bytes(store) == before`；`assert store.read("counters")["counters"] == {}` | 同上 |
| `tests/test_rebuild.py:69` | `assert out["applied"] == 4 and out["skipped"] == 0` | R-06（**加键不动它**：键只增） |
| `tests/test_p910_p9_review_finding_format.py:521` / `:557` | `assert out["skipped"] == 0, out` / `assert out["skipped"] == 1, out` | R-06（同上） |
| `tests/test_agent_surface_snapshot.py:207` | `test_the_agent_surface_matches_the_frozen_snapshot`；重冻命令在该文件 `:25` | `TABLES`/`SCHEMA_VERSION`/词表进提示词者 |
| `tests/test_literature_match.py:126-127` | `LIT_MATCH_STATUSES` 的三档 | E-09（不施工，故不动） |

---

## §1 `src/agentflow/schema.py`（2791 行）`[本次确认：行数=2791]`

> **本文件在 FC-27 禁改区**：`.noai-paths:93`（`src/agentflow/schema.py [category: schema-migration] SCHEMA_VERSION 与 TABLES…`）
> 与 `.noai-paths:102`（`[category: eval-criteria] EVAL_REQUIRED_FIELDS 与 EvalResult…`）**两条**都命中它。
> ⇒ 本节**每一条**改动都：**改后必须报备人审、不代签 `.noai-approvals.json`、需 2 名 reviewer**
> （`AGENTS.md` "命中之后要做什么"第 1–4 条 + `scripts/noai_gate.py` 的 `REQUIRED_APPROVALS_ON_HIT=2`）。
> 门是机器执行的：改完跑 `python -B scripts/noai_gate.py --git --since <基线>`，退出码 1 即命中（`0=clean / 1=requires_human / 2=unknown`，
> **2 绝不是 clean**）。

### 条目 R-05 — `check_array_invariants` 在混合类型数组上抛 `TypeError`（放宽判据 + 修 7 处行级内联件）

- **改什么**：把"集合字段必须升序去重"这条判据从"比较异类型即 `TypeError`"**放宽**为"元素非 `str` 先判类型并报 `ValueError`-级问题描述、不比较异类型"，并把 7 处行级内联件（共覆盖 9 个 set 字段）**同步改成复用同一私有谓词**（纯判据改动，不动任何表/字段/`SCHEMA_VERSION`）。
- **怎么改**：接口级，三步缺一不可。
  - **STEP-1（表级）** `schema.py:2429-2434`（问题行 `:2432` `[本次确认]`）：
    ```python
    if not isinstance(val, (list, tuple)):
        bad.append(f"{fname} 声明为集合但值不是数组：{type(val).__name__}"); continue
    # 新增：元素类型先判、不比较异类型（这就是"不抛 TypeError"的唯一切入点）
    if any(not isinstance(v, str) for v in val):
        bad.append(f"{fname} 声明为集合但元素不是字符串：{[type(v).__name__ for v in val]}"); continue
    if list(val) != sorted(set(val)):
        bad.append(f"{fname} 声明为集合但未升序去重：{list(val)}")
    ```
  - **STEP-2（行级内联件 7 处，必须同步；否则 `TypeError` 仍从 `validate()` 先抛）** `[本次确认：7 处行号全部逐处 read 过]`：
    `schema.py:374`（`Concept.related_concepts`）· `:418`（`Relation.concept_ids`）· `:577`（`ReprocessRequest.relation_ids`）·
    `:659`（`ResearchQuestion.contradiction_relation_ids`）· `:669-672`（`{related_concept_ids, related_relation_ids, evidence_lit_ids}` 三字段共用一支循环）·
    `:811`（`Conjecture.experiment_ids`）· `:1672`（`Statement.derived_from`）。
    推荐做法：抽一个私有谓词并全部改调它 —— `def _set_problems(field: str, val) -> list[str]`，
    返回 `["…声明为集合但元素不是字符串：…"]`（文案里保留原句"必须升序去重"，`tests/test_coverage_schema.py:91` 认这四个字）。
  - **STEP-3（可选，诊断）** 在 `store.py:947` / `store.py:1374` 之外把非 `ValueError` 翻成 `StoreError` 并带表名（**诊断改善，不解决根因**，且属 store 禁改区，须单独报备）。
- **改的依据**：`draft/46-01 §1.2(a)` + `§1.7 第 1 条` + `§3 表第 2 行`；`draft/44 R-05`（触及面 `禁`(schema)）+
  `draft/44 §19 J-27`（引 `46-01 §3` 的判定照用）；关键证据：`schema.py:2432` `[本次确认]`、
  `validate_table:2722` 先调 `obj.validate()` `[本次确认]`、7 处内联件行号 `[本次确认]`、
  `verify.py:156-159` 同样只 `except ValueError` `[46-01 §1.2(a)]`，以及 §0.5 的探针 1–4（改前四种路径全 `TypeError`）。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_coverage_schema.py` **新增** `test_check_array_invariants_reports_mixed_type_elements_instead_of_raising`：
    ```python
    obj = Concept.__new__(Concept); obj.related_concepts = ["0001", 2]
    bad = S.check_array_invariants("concepts", obj)
    assert bad and "元素不是字符串" in bad[0]
    ```
    **必须先跑一次、必须红**（改前抛 `TypeError`，见 §0.5 探针 2）。`tests/test_schema.py` **新增**
    `test_validate_table_reports_mixed_type_rows_as_value_error`（6 个 set 字段载体类各一条）：
    `with pytest.raises(ValueError): S.validate_table("concepts", {…"related_concepts":["0001",2]…})` —— **改前逃逸 ⇒ 必红**（§0.5 探针 3）。
  - **真机回放**：本条的"真机闸"就是兼容闸本身 —— 两根全部 1322 份逐份 `validate_table`，
    改前 `1322/0/0`（§0.1）→ 改后要求**失败数不增**（仍 `1322/0/0`；本条不动行形状，理论上恒等）。
    另跑根1 三个工作区的只读 `verify`：`python -B -m agentflow.cli --root D:\Incubator\agentflow\projects\p8c-fermat-shorter-proof verify`
    里的 `schema_invalid` 条数，改前 0 → 改后仍 0。**不适用"比状态词"那一条**（本条不是 `closing` 门类读数）。
  - **会红的既有判据（逐条列出，要求全部保持绿）**：`tests/test_coverage_schema.py:77`（`:89`/`:91`）、
    `tests/test_coverage_schema.py:110` 一族、`tests/test_schema.py:169/177`、`tests/test_fc05_contract.py:66`、
    `tests/test_statements_table.py:81`。**这些一条都不许改**——若它们红了，是本改动写错了，不是判据该改。
  - **快照/文档/计数同步**：本条**不进提示词**（词表/表数未动）⇒ 无需重冻 `agent_surface_snapshot.json`；
    但若 STEP-2 抽了公共谓词，跑一次 `python -B tests/test_tool_surface_snapshot.py --write` 前**先确认 diff 为空**（工具面未动，空 diff 是预期的）。
    文档面：`DEVELOPMENT.md` 里关于"集合字段唯一权威点"的措辞若被本次改动触碰，按 §1.6（`45`）的"先改代码 → 跑判据让它点名 → 再改文档"顺序办。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`
    （基线 0 错 / 9 警 / 49 提示；`--strict` 为 0 / 58 / 48）。
  - **兼容闸**：历史数据仍通过 —— §0.1 的 1322 份命令**必须在本条改动后原样重跑**（这是本条的必做闸）；
    969 份那份基线（`46-01 §0①` 末段 / `45` §3 第 1 条）同样要求失败数不增。只放宽、不加必填字段（`_set_problems` 只产出问题串，不新增任何字段）。
- **不许这么改 / 边界**：照抄 `46-01 §3` 的判定 ——
  ① **只改 `schema.py:2432` 不成立**（"必要但不充分"）：`validate_table:2722` 先调 `obj.validate()`，
  7 处行级内联件先抛；**必须同批改 7 处**（不施工 = 不成立）。
  ② **store 侧 0 改动**：不许把 `store.py:947`/`:1374` 的 `except` 加宽（那会把"库里有混类型"变成静默通过）
  ——`46-01 §2.2(c)` 逐字："只在这里把 `except` 加宽等于把'库里有混类型'变成静默通过 —— **不可行**"。
  ③ 不动 `ARRAY_FIELD_KINDS`（`:2361-2403`）的字段声明集合，不动 `TABLES`（`:2439`），不动 `SCHEMA_VERSION`（`:18`）。
  ④ 不建议顺带收紧 `tests/test_fc05_contract.py:66` 的"唯一权威点"表述（那是 F-07 元判据的题，不在本组）。
- **依赖与批次**：**无前置**，可独立开工（`46-01 §1.5`："R-05 局部，20–35 行，1（+1 若抽公共谓词）文件，前置无"）。
  批次归属 = `draft/44` 批次 0（红线）；与 R-06 **同批**（同属"灾难恢复不许被非 `ValueError` 打断 / 不许静默丢行"这一族）。
  顺序：**R-05 先，R-06 后**（R-06 的明细键会记录 `schema_rejected`，R-05 定完"什么算 schema 拒绝"它才有稳定语义）。
  与 `draft/44 §19 J-27` 无直接依赖；**禁改区报备**：每一次改动都要 `--git --since` 报备 + 2 名 reviewer。

### 条目 F-01 — 等级机制（`Statement` 侧"纯增量补产出方"；**claims/Relation 侧判不可行，不施工**）

- **改什么**：**纯增量**——不动任何字段、不加任何字段：让唯一的语句写入口在构造 `Statement` 时**真的把五元位算出来并落盘**（`bits` 字段早已存在，只是从没人写过）；读侧一律走现算。claims/Relation 的"各加一处派生 grade"**保留 `46-01` 的不可行判定，不施工**。
- **怎么改**：接口级（落点在**非本文件**，本文件 `schema.py` 0 改动）。
  - `src/agentflow/agent_b/register_statement.py:179-199`（构造块；`[本次确认]`：`:180` 是 `row = S.Statement(`，`:192` 是 `evidence_kind=evidence_kind`，**整个构造里没有任何 `bits=`**）：
    ```python
    # 在 row = S.Statement(...) 之前算一次（EB = agentflow.evidencebits）
    bits = EB.bits_of(proof=bool(str(proof_text or "").strip()) or origin == "external_lit",
                      proof_process=str(proof_text or ""),
                      origin=origin, source_lit_id=lit_id, quote_verified=quote_verified)
    row = S.Statement(..., bits=bits, ...)      # 其余参数一字不动
    ```
    只想先出声的极小版：把 `proof_text` 折成第 2 位（`proof_process`）——**零新字段**。
  - 读侧**不新增入口**：一律 `evidencebits.bits_from_row(row)["grade"]`（`46-01 §1.2(b)` 记 `closing.py:899`、`statusreport.py:108` 已如此）。
  - `schema.py` 侧**唯一**相关既有事实（只登记、不改）：`:1684` 的 `if self.bits:` ⇒ 空 bits 直接跳过（§0.5 探针 8）。
- **改的依据**：`draft/46-01 §1.2(b)` + `§3 表第 6 行`（半不可行）；`draft/44 F-01`（` 禁 `(schema) ` 行 `）+ `draft/44 EE-12`（"`bits_of` 零生产调用点；唯一语句写者构造 `Statement` 时**没有 `bits=` 参数**"）+ `draft/44 §19 J-22`（腿 2 的档位依赖本条）。
  关键证据：`statements.bits` 非空 **0/138** `[本次现算]`；`evidence_kind` 分布 `{cross_check:124, heuristic:8, proof:6}` `[本次现算]`；
  `grep 'bits=' src/` **0 命中** `[46-01 §1.2(b)]`；13 条 `own_result` 全带 `proof_text` 而现算等级 13/13 全 `conjecture` `[46-01 §1.2(c)]`；
  `evidencebits.derive_grade:186-203` `[本次确认]`（`has_proof and formal ⇒ theorem`；`has_proof and reviewed ⇒ pre_theorem`；`numeric verified ⇒ strong_conjecture`；否则 `conjecture`）。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_evidence_bits.py`（新增用例，形如 `46-01 §1.6` 第 3 条）：
    ```python
    r = register_statement(statement_full="我们猜…", origin="own_result", proof_text="")
    assert r["ok"] is True and EB.bits_from_row(r["row"])["grade"] == "conjecture"
    assert any(p.get("kind") == "missing_proof_text" for p in pending)
    ```
    **必须先跑一次、必须红**（改前这一步直接 `_refuse`，无 `row`/无 `pending`；见 §1.3 与 §0.5 探针 7）。
    配一条**正控**（不许只有负控）：`origin="external_lit"` 且 `quote_verified=True` ⇒ 第 2/3 位为真、等级 `pre_theorem`（口径见 `evidencebits.bits_of` docstring `[本次确认]`）。
  - **真机回放**：根1 `p6e-research-from-zero`（**`46-01 §1.6` 建议的 `p8c`/`p8e` 对"改写入口后新落盘行"无效，见下**）。
    读数 = 逐行 `EB.bits_from_row(r)["grade"]` 分布。改前（`p6e` 现有 2 行）`[本次现算]`：
    `0000 external_lit ek=cross_check bits=None grade=conjecture`、`0001 own_result ek=proof bits=None grade=conjecture`
    ⇒ 预期改后（**新写入口产生的新行**）出现非 `conjecture` 档；**历史行不会变**（本条只改产出方，不改读侧）。
    `46-01 §1.6` 点名的 `p8c-fermat-shorter-proof`、`p8e-fermat-shorter-proof` 两处**行号面已漂移**：
    `p8c` 与 `p8f` **今天没有 `statements.json`**，`p8e` 的 `statements.json` 是 **0 行** `[本次现算]`
    ⇒ 拿它们当 F-01 回放样本**读不到任何等级**。可用样本改为：根1 的 57 个有 `statements.json` 的工作区里挑 `p6e`（2 行）与 `p5-review-t9`/`p5-review-t6`（各 10 行）。
  - **会红的既有判据**：`tests/test_evidence_bits.py`、`tests/test_agent_b.py`（`46-01 §1.3` 列的两处覆盖）。
    本条**不加必填、不动词表、不动 `TABLES`/`SCHEMA_VERSION`** ⇒ `tests/test_agent_surface_snapshot.py:207` 与
    `tests/test_release_all.py:1039` 应保持绿（`specs/b.py:131` 的 enum 未动）。
  - **快照/文档/计数同步**：本条的**改动面不在 schema**，`agent_surface_snapshot.json` 不需要重冻（若 `specs/b.py` 的
    `evidence_kind` 描述文字也未动）。文档面：`docs/ROLE-SPECS.md` 里"等级机制"相关句若仍写着"未落地"，
    按 §1.6 顺序在代码落地并跑判据之后回填。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：`bits` 是**既有字段**（`schema.py:1613` `[本次确认]`）⇒ 历史 1322 份零影响（§0.1 命令改后仍须 1322/0/0）；
    §0.2 的 E 模拟（`grade` 必填 ⇒ 33 份红）**只用于证明"不许把 grade 做成必填字段"**，本条不新增该字段。
- **不许这么改 / 边界**：照抄 `46-01 §3 表第 6 行` 与 `§1.2(b)`、`§1.7 第 1 条`：
  ① **不许把 `grade` 落盘**：`evidencebits.bits_shape_problems:176-181` `[本次确认]` 逐字"等级不许自报（判据永远现算）"，
  `schema.py:1611` 逐字"等级**不落盘**"；`46-01` 另给二阶坑：只在 `to_dict()` 里多吐 `grade` 键，
  模型把该行原样回写时会被 `tools/table_tools.py:114-117`（`known = {f.name for f in dataclasses.fields(cls)}`）拒掉 —— "没有字段 `['grade']`" `[本次确认：:114-117 逐字命中]`。
  ② **claims / Relation 的等级不施工**：`derive_grade` 的入参是**五元位**，而 `claimanatomy.py`/`doc_tools.py` 全文 `grep '\bbits\b'` **0 命中** `[46-01 §1.2(b)]`
  ⇒ 要先发明 claim→bits / relation→bits 映射（新设计，未立项）⇒ `45` §1.1 的"各一处由 `derive_grade` 计算"**不成立**。
  ③ `closing.py:1454-1464` 的边界照抄：`statements` **没有**指向 `experiments` 的字段 ⇒ `MUST_T3_CONDITIONS` 的 ②④ 今天只能 `counted_only`
  ⇒ 本条**不许**顺手加 `proof_experiment_id`（那是新增字段 = 人裁，`46-01 §1.7 第 1 条`明列为"本批不做"）。
  ④ 形式化 `exit_code` 的折叠点在 `agent_e/core.py:402`（不在本文件），归姊妹件 `46-06 §2`，本条不碰。
- **依赖与批次**：**前置 = 无**（产出一侧自足）；但**收益侧有前置**：`draft/44 §19 J-22` 明写 S-05 的腿 2"必须等 F-01/EE-12 落地"（否则"我方派生命题"那一档恒红）。
  同批关系：`draft/44 §19 J-03` 与 F-01 无依赖；本条与 **EE-07 路线 B**（§1.10）**必须同批**——
  两者都在改"等级/证据类型到底谁说了算"这同一处口径，分开做会留下"手填 `evidence_kind` 而 `bits` 空"的中间态。
  批次归属 = `draft/44` 批次 1（地基）；`45` §4 批 1 的完成判据逐字含"`statements.bits` 非 0（首见）"。
  顺序：**F-01 的产出方先做，EE-07 路线 B 的一致性判据后做**（判据要有一个真产出方才有意义）。

### 条目 P-06 — `proof_text` 硬要求改为"缺 ⇒ 降级 + 待办"（删一条 raise + 写入口改"落库 + 待办"）

- **改什么**：**放宽 + 删校验**——删掉 `schema.py` 里"`origin='own_result'` 必须给 `proof_text`"这一条 `raise`；
  写入口 `register_statement` 的 `missing_proof_text` 从"拒"改"落库 + 返回 `pending`"。等级侧**不用另写**：第 2 位空 ⇒ `derive_grade` 已给 `conjecture`。
- **怎么改**：接口级，两处落点。
  - `schema.py:1657-1663`（`[本次确认：逐字与 46-01 §1.2(c) 相同]`）：
    ```python
    # ---- 自产结果：证明是它与"一句声称"的唯一分界（§10 的自产入库门）
    if self.origin == "own_result" and not self.proof_text.strip():
        raise ValueError("origin='own_result' 必须给 proof_text：…")
    ```
    ⇒ **整段删掉**（不拦）。注意：**不许**改成"改成警告后继续"以外的形态（例如塞进 `notes`）——那会让 `validate()` 又能抛别的错。
  - `agent_b/register_statement.py:140-144`（`[本次确认：:140` 是 `if not str(proof_text or "").strip():`，`:141` 是 `return _refuse("missing_proof_text", …)`）：
    ```python
    pending = []
    if origin == "own_result" and not str(proof_text or "").strip():
        pending.append({"kind": "missing_proof_text", "stmt_id": None})   # 落库后再回填 stmt_id
        # 不 return；继续走 tx 落库，且把 proof_text 记成 ""（第 2 位空 ⇒ 等级 conjecture）
    ```
    返回值里加 `"pending": pending`（键**只增**：`register_statement` 的既有返回键一字不动，形如 `agentflow/{...}` 的键集合见 `:203-204` `[本次确认]`）。
  - `schema.py:1658` 删除后**顺带核对**：`refusals.py:43-44` 的导入期断言 `PRECONDITION_REASON in S.REFUSAL_REASONS` 的对象**不是** `missing_proof_text` ⇒ 不受影响（`46-01 §1.2(c)` 已核为"已核"）。
- **改的依据**：`draft/46-01 §1.2(c)`（含"删掉这条 raise（不拦）"与 `refusals.py` 已核结论）；`draft/44 P-06`（` 禁 `(schema)，建议 `减`，实质理由逐字"用户点名'不该想自己的等级够不够'"）。
  关键证据：**13 条 `own_result` 全带 `proof_text`，而现算等级 13/13 全是 `conjecture`** `[46-01 §1.2(c)]`（我本次复核了"13/13 全带 `proof_text`"这一半 `[本次现算]`）
  ⇒ "降级"在数据面**已经发生**，schema 侧实质只是删一条 `raise`，收益在提示词与写入口；
  `schema.py:1657-1663` 与 `register_statement.py:140-144` `[本次确认]`；§0.5 探针 7（改前必红）。
- **怎么算过**：
  - **负控（改前必红）**：**改写** `tests/test_statements_table.py:142`（`test_an_own_result_without_a_proof_cannot_enter`，`:147` 断言 `"proof_text" in msg and "自产" in msg`）
    ⇒ 新名 `test_an_own_result_without_proof_text_is_recorded_and_downgraded`：
    ```python
    r = register_statement(statement_full="我们猜…", origin="own_result", proof_text="", doc_id="0000")
    assert r["ok"] is True
    assert EB.bits_from_row(r["row"])["grade"] == "conjecture"
    assert any(p["kind"] == "missing_proof_text" for p in r["pending"])
    ```
    **必须先跑一次、必须红**（改前 `register_statement` 直接 `_refuse`、无 `row`）。
  - **真机回放**：根1 的 `statements` 面（57 个工作区 / 138 行）—— 读数 = 受影响行数与 `grade` 分布。
    改前 `[本次现算]`：`bits` 非空 0/138、`own_result` 13 行全 `conjecture`。
    预期改后：**历史行一字不变**（走的是 `row_from_dict` 读，不重跑写入口），新产出方产生的新行带 `bits`。
    `46-01 §1.6` 建议的 `p8f-fermat-shorter-proof` 样本**行号面已漂移**：根1 `p8f` **没有 `statements.json`**、`p8e` 是 **0 行** `[本次现算]` ⇒ 改用 `p6e`（2 行）或 `p5-review-t9`（10 行）。
  - **会红的既有判据（逐条列出）**：`tests/test_statements_table.py:142`（本条改写）、
    `tests/test_action_surface_matches_acceptance.py:226`、`tests/test_conductor_payload_outcomes.py:126/133`、`tests/test_intake_actions.py:407`
    （`46-01 §1.6` 列；**逐条先跑一次确认红，再改断言**，顺序不能反）。
  - **快照/文档/计数同步**：本条**动 schema 的校验面**但**不动任何词表/表数** ⇒ `agent_surface_snapshot.json` 无需重冻；
    但 `specs/b.py:118` 的 `"自产的命题没有证明就入库，等于把猜测抬成事实"`（该行是 `proof_text` 的 `description`）`[本次确认]`
    与 `specs/b.py:122-127` 的 `origin` 描述（逐字含"**并且**给 `proof_text`"）`[本次确认]`**必须同步改口径**，
    否则提示词仍教"必填"⇒ 重冻 `python -B tests/test_agent_surface_snapshot.py --write`（命令见该文件 `:25` `[本次确认]`），
    并同步 `agent_prompts.py` 的 `ROLE_BRIEFS` 真身（`specs/*` 是它的镜像，镜像由 `temp/_sync_policy.py` 脚本重建、**不许手改**）。
    文档面：`tests/test_agent_surface_snapshot.py:207` 与 `tests/test_release_all.py:1039` 的读数。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：删一条 `raise` 是**纯放宽** ⇒ 历史 1322 份必须仍 `1322/0/0`（§0.1 命令改后重跑）；
    **不许**为了让 `pending` 有落点而在 `Statement` 上加必填字段（§0.2 的 A/E 两个反例就是代价证明）。
- **不许这么改 / 边界**：照抄 `46-01 §1.7 第 3 条` —— 不动 `Document.validate` 的四条既有硬约束（FC-02 引用 / FC-22 disclaimer / FC-25 否定分类 / P-10 反例两源）：**本批只谈"放宽或自动补"，不删任何一条**。
  另：`schema.py:1664-1670` 的"`status='active'` 必须有 `statement_full`"**不同条**，不许顺手删（`46-01 §1.2(c)` 只点 `:1657-1663`）。
  `agent_b/register_statement.py` **不在** FC-27 禁改区（`47` §3-C2 复核过 `tools/` 与若干模块的名单；`agent_*` 未被登记）
  ⇒ 它按普通改动走（仍建议先改后报备），但 `schema.py:1657-1663` 那半**必须报备人审、不代签、需 2 名 reviewer**。
- **依赖与批次**：**必须与 P-08 同批**（两条都在"把硬门槛改成'降级 + 待办'"这一族；`draft/44 §19 J-21` 的"**必须同批的依赖（否则留中间态）**"方法适用于本组）。
  **前置 = F-05 待办队列**（`46-01 §3` 末段逐字："F-05 待办队列（P-06/P-08 的'降级 + 待办'没有接手人就是空转）"）
  ⇒ 顺序：**F-05 的队列落点先有（或至少同批给出 `pending` 的消费方），P-06 再改**；若 F-05 未就绪，本条的 `pending` 只能是"记账不消费"，那要在提交信息里点名。
  批次归属 = `draft/44` 批次 3（提示词与减负）+ 批次 0 的"红线"气质（这条本身是放宽，不是红线）。
  顺序：**P-06 的代码先，提示词后**（`45` §2 硬约束逐字："不许'提示词先删、代码后补'（顺序必须是代码先接住）"）。

### 条目 P-07 — `cross_check` 必带 disclaimer 改为框架自动补（**落 `doc_tools`，不在 `schema.py`**；`schema` 侧只可选"减必填性"）

- **改什么**：**不在 `schema.py` 里补**——补在 `tools/doc_tools.py` 的落库规范化处，并**留痕**（`_autofilled` 诊断字段）；`schema.py:1412-1417` 的必填性**可选减**（若减，必须同步 `claimanatomy.FIELD_SPECS`）。
- **怎么改**：接口级，主落点在 `tools/doc_tools.py`。
  - `tools/doc_tools.py:1112-1169` 的 `normalize_claims`（`[本次确认：:1112 函数头；:1115-1118 是那段"刻意不自动补"的逐字说明；:1167 是 `check = scan_claim(row)`]）：
    ```python
    if str(row.get("evidence_kind") or "") == "cross_check" and not str(row.get("disclaimer") or "").strip():
        row["disclaimer"] = CROSS_CHECK_DISCLAIMER          # 常量在 doc_tools.py:67 [本次确认]
        row.setdefault("_autofilled", []).append("disclaimer")
    # 放在 :1167 的 scan_claim(row) 之前；`_` 前缀诊断字段被
    # tools/table_tools.py:114-117 的 known 过滤与 store.rebuild 的合并逻辑刻意保留 [本次确认]
    ```
  - 若同时在 schema 侧"减"：只删**必填性**并同步 `claimanatomy.py:447-458` 的 `FIELD_SPECS["disclaimer"]`（`:450 required=False` `[本次确认]`）
    与 `claimanatomy.py:1282-1291` 的 `missing_disclaimer` 判据口径（其口径逐字来自 `Document.validate`，`claimanatomy.py:72` `[本次确认]`），否则写入期与审校期两套口径（FC-03）。
  - 同题另有三个落点（`46-01 §1.2(d)` 列出，本组**只动 doc_tools**）：`verify.py:985-987`、`claimanatomy.py:1282-1291`、`review_tools.py:432-438`。
- **改的依据**：`draft/46-01 §1.2(d)` + `§3 表第 7 行`（"高风险（方向反了）"）；`draft/44 P-07`（` 禁 `(schema)，建议 `减`）。
  关键证据（**逐字，必须照抄**）：`tools/doc_tools.py:1115-1118` `[本次确认]`——
  "这里刻意不自动补 disclaimer（虽然 `compose_claim` 会补）：…让闸门顺手把违规项改好，会让'调用方漏写了声明'这件事从此不可见 —— 那正是本框架最忌讳的静默修复。"
  ⇒ 可行落点是 `normalize_claims` + `_autofilled` **留痕**，不是让 schema 静默补。
  另：常量 `CROSS_CHECK_DISCLAIMER = "数值交叉验证，不构成证明"` 在 `tools/doc_tools.py:67` `[本次确认]`。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_tools_audit_fixes.py`（或 `test_doc_tools` 族）新增
    `test_a_cross_check_claim_gets_the_disclaimer_autofilled_with_a_trace`：
    ```python
    out = doc_tools.normalize_claims([{"claim_id":"c1","text":"x","evidence_kind":"cross_check","citations":["lit:0000"]}])
    assert out[0]["disclaimer"] == DT.CROSS_CHECK_DISCLAIMER
    assert "disclaimer" in out[0]["_autofilled"]
    ```
    **必须先跑一次、必须红**（改前 `scan_claim` 报 `missing_disclaimer` 错误级 ⇒ `normalize_claims` 抛）。
    **配反控**（不许只有负控）：显式写了别的 disclaimer ⇒ **不许被覆盖**。
  - **真机回放**：根1 `p8e-fermat-shorter-proof`（`46-01 §1.6` 的样本）。
    我本次实测该工作区 `[本次现算]`：`claims` **4 条**，`evidence_kind=cross_check` **2 条**，`disclaimer` 非空 **2 条**，
    `status` 非空 0、`allowed_use` 非空 0；根2 侧 `p2-review` 一族的 `claims` 168 条里 `disclaimer` 非空 **168**、`cross_check` **0**。
    读数 = 受影响 `claims` 条数与 `disclaimer` 三键非空计数：**改前**（根1 全库）`claims` 449 条中 `disclaimer` 非空 121 `[本次现算]`；
    **预期改后** = 新增落库的 `cross_check` 行必带 disclaimer 且 `_autofilled` 有痕，**历史行一字不变**。
    注意 `46-01 §1.6` 说"`p8f-fermat-shorter-proof`；读数 = 受影响 claims 条数与 `status`/`allowed_use`/`disclaimer` 三键非空计数（改前 0 / 0 / 逐条）"——
    **行号面/样本面已漂移**：根1 `p8f` **没有 `documents.json` 行**（`documents.json` 不在它的表清单里，claims = 0）`[本次现算]` ⇒ 用 `p8e`（4 条）。三键改前读数我按根给了新数（见上）。
  - **会红的既有判据（逐条列出）**：`tests/test_verify_extended.py:433`、`tests/test_agent_h.py:261`、`tests/test_closing_gate.py:132-139`、
    `tests/test_refusal_family_numbers.py:61`（前两条按 `46-01 §1.6`："只要'schema 放宽、判据不放宽'就仍绿"）。
  - **快照/文档/计数同步**：本条**不动 schema 的词表**（`DISCLAIMER` 常量本就在 doc_tools）⇒ 原则上无需重冻；
    但 `specs/g.py:53`（`46-01 §1.1` 列的词表进提示词处之一）与 `agent_prompts.py` 里"必须手写 disclaimer"的措辞若被本次改动触碰，
    必须重冻 `python -B tests/test_agent_surface_snapshot.py --write`（命令在该文件 `:25` `[本次确认]`）。
    文档面：`docs/ROLE-SPECS.md` §G.3 提到 `allowed_use` 0 命中的那句与本条无关**不要动**。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：本条是"自动补 + 留痕"，**不新增必填、不删判据**（若删 `schema` 必填性则是纯放宽）⇒ 历史 1322 份必须仍 `1322/0/0`。
    注意 `_autofilled` 是 `_` 前缀诊断字段，`store.rebuild` 的合并逻辑刻意保留它以与"事件行里带了"这一条对齐（`store.py:1346-1359` `[本次确认]`）——**不许**把它写成正式 schema 字段。
- **不许这么改 / 边界**：① **不许在 `schema.py` 里自动补**（`46-01 §3` 判"方向反了"，证据即 `doc_tools.py:1115-1118` 的逐字）。
  ② 不许把 `disclaimer` 从 `Document.validate` **删掉整条**（`46-01 §1.7 第 3 条`：本批只谈"放宽或自动补"，**不删任何一条**既有硬约束）。
  ③ `46-01 §1.2(d)` 明写一条**未核实**（照抄，不许折成"没问题"）：
  "**未核实**：按逐字常量数，`src/`+`tests/` 共 **24 行 / 13 个文件**（`claimanatomy.py`4、`doc_tools.py`3、`schema.py`1、`tests/test_closing_gate.py`5…；`specs/` 0 命中）；
  **`draft/44` 的'81 处'本轮未能复现**，口径未核实。" ⇒ 引用处一律写 `[46-01 §1.2(d)，未核实]`。
- **依赖与批次**：**前置 = 若改 `schema` 的必填性，必须同步 `claimanatomy.FIELD_SPECS`**（`46-01 §1.5` 的"P-07 前置"列逐字）。
  批次归属 = `draft/44` 批次 3；与 P-06 同族但**无强同批**要求（P-06 动 `statements`，本条动 `documents.claims`）。
  顺序：**doc_tools 的自动补 + 留痕先做，schema 的可选"减必填"后做**（先有接住，再放宽）。

### 条目 P-08 — "没有逐字引文不许产出关系"改为三态 + 待核队列（**`schema.py` 0 改动**；纯提示词级）

- **改什么**：**不改 `schema.py`**（`46-01` 判定"现状方向正确"）。改提示词真身 `agent_prompts.py` + 其镜像 `specs/b.py`；"待核队列"的落点不在本文件（F-05）。
- **怎么改**：接口级（本文件 0 行）。
  - "没有逐字引文支撑的关系不许产出"这句话**不在 `schema.py`**，在提示词：`agent_prompts.py:595-597`（B 的 `boundary` 第 1 条；`[本次确认：:597` 逐字"没有逐字引文支撑的关系不许产出（判据会逐字回验，编造会被剔除并留痕）。"`]`），
    它等于 `specs/b.py` 的 B 边界第 4 条（进 golden 快照）⇒ **真身改 `agent_prompts.py`，镜像用 `temp/_sync_policy.py` 重建**（不许手改镜像）。
  - schema 侧**只登记事实**（不改）：`schema.py:430-431`（关系引文是**纯三态**，没有"必须 True"）`[本次确认]`：
    ```python
    if self.quote_verified is not None and not isinstance(self.quote_verified, bool):
        raise ValueError("quote_verified 必须是 bool 或 None（三态：通过 / 不一致 / 没校验）")
    ```
  - 落库侧**已经在做正确的事**（不改）：`agent_b/run_once.py:249-274`，含 `quote_verified=chk.verified,` 与 `d["_quote_check"] = chk.to_dict()`（诊断字段，`rebuild` 刻意保留）。
- **改的依据**：`draft/46-01 §1.2(e)`（` 禁 `(schema) ` 提 `）；`draft/44 P-08`（触及面 `禁`(schema) ` 提 `，建议 `减`，"用户点名"）。
  关键证据：`relations.quote_verified` = True 1754 / False 18 / **None 0**（两根，两根皆 0 个 None）`[本次现算]`
  ⇒ **三态中间档从未出现**；而真正缺的落点是 `not_found` / `no_text_layer` 这些 **reason** 只躺在 `_quote_check` 诊断字段里，**没有可查询的列**。
- **怎么算过**：
  - **负控（改前必红）**：`46-01 §1.2(e)` **没有给本条负控**（因为它不改代码）。本条的可执行判据是"**提示词一致性判据**"：
    在 `tests/test_agent_spec_reconciliation.py` 一族里钉住"`specs/b.py` 的 B 边界第 4 条 == `agent_prompts.ROLE_BRIEFS['B'].boundary[0]`"，
    并**新增**一条"改前必红"的注入式元判据（`monkeypatch` 把真身那一句改字 ⇒ 必须红）。
    ⇒ **必须先跑一次、必须红**（改前不存在这条判据 ⇒ 判据缺失本身就是"红"的失败面，按 `45` §2 第 2 步的口径记"负控未落地前不许声称本条已过")。
  - **真机回放**：根1 + 根2 的 `relations` 面 —— 读数 = `quote_verified` 三档分布 + `_quote_check` 里各 `reason` 的条数。
    改前 `[本次现算]`：根1 1652 行 `{True:1646, False:6}`、根2 120 行 `{True:108, False:12}`；**None 全 0**。
    预期改后：提示词改口径**不会**改历史行；真机闸改为"下一次真机运行里 `quote_verified=None`（没校验）是否有实例"——
    若无实例，则本条**不得声称已落地**（`45` §3 第 3 条：看不到变化 ⇒ 不算落地）。
    注意 本条**不是 `closing` 门类读数**，不适用"必须比 `findings.detail` 的原因行"那一条（那条见 `draft/44 §19 J-20`）。
  - **会红的既有判据**：`tests/test_agent_prompts.py` 一族（提示词快照/计数）、`tests/test_agent_spec_reconciliation.py`、
    `tests/test_agent_surface_snapshot.py:207`。
  - **快照/文档/计数同步**：**必须重冻** `python -B tests/test_agent_surface_snapshot.py --write`（命令在该文件 `:25` `[本次确认]`），
    因为 `specs/b.py` 的 B 边界进 golden；同步 `docs/ROLE-SPECS.md` 里对应条数与 `AGENT-PROFILES.md`（`45` §1.6 的"快照与计数"一行）。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：本条**不动存储契约**（`schema.py` 0 行）⇒ 历史 1322 份不受影响；仍按纪律重跑一次 §0.1 命令（应恒等 `1322/0/0`）。
- **不许这么改 / 边界**：① **`schema.py` 不改**（`46-01 §1.2(e)` 逐字"schema 不改（现状方向正确）"）——不许把 `quote_verified` 改成必填 `True`，
  也不许为了"待核队列"在 `relations` 上加列（那是新增字段 = 人裁）。
  ② "待核队列"的落点**不在本文件**（F-05）；本条施工不许顺手造队列。
  ③ `agent_prompts.py` **不在** FC-27 清单里（`47` §3-C2 复核名单，`closing.py`/`agent_prompts.py`/`signatures.py` 等**未命中**）
  ⇒ 按普通改动走（仍建议先改后报备）；但 `specs/b.py` **在**清单里（`.noai-paths:127`）⇒ 镜像重建那一步**必须报备人审、不代签、需 2 名 reviewer**。
- **依赖与批次**：**必须与 P-06 同批**（同一族的"硬门槛 → 降级 + 待办"）；
  **前置 = F-05 待核队列**（`46-01 §3` 末段逐字："P-06/P-08 的'降级 + 待办'没有接手人就是空转"）。
  批次归属 = `draft/44` 批次 3；顺序：**代码侧先接住（F-05 队列）→ 提示词后改**（`45` §2 硬约束）。

### 条目 E-09 — `LIT_MATCH_STATUSES` 补 `none`：**判定不可行，不施工**

- **改什么**：**不施工。** 保留 `46-01 §3 表第 4 行` 与 `§1.2(f)` 的判定 —— `LIT_MATCH_STATUSES += ("none",)` **不可行**。
- **怎么改**：**不施工，理由：**`schema.py:113-121` 逐字否证（`[本次确认：:113-121 与 :122 逐字]`）：
  ```
  （原文此句前有一个警示符号，按本文"无 emoji"格式要求去掉，文字逐字未改）
  **别与 §5.2 / §16 P2 的另一个 `matched` 串了**（同 `SEARCH_OUTCOMES` vs
  `TASK_OUTCOMES` 那一族的形态）：登记册里有**两个**同名但**不同问**的"三态"——
    - 本栏（§2 R1b）：问"**这一篇**是不是我要的那一篇"（文献身份）⇒ `mismatch`；
    - §5.2 / §16 P2 / §2 R14：问"**这条定理在不在这篇里**"（文内定位）⇒ 第三态叫 `none`，
      由 A 在回报里给出（`matched` + 页码 + 片段 + "最接近的三段"），**不落本栏**。
  两者的第三态名字不同（`mismatch` vs `none`）是**故意的**：一个是"拿错了文献"、
  一个是"这篇里没有它"，处置方向相反（重取 vs 换关键词/如实回报）。把它们折成一个
  字段会让"我下错了论文"与"论文里没有这条定理"在台账上同形 —— 而这两件事
  在真机里各自都发生过一次（§1.1 与 §2 R14 的负控①）。
  LIT_MATCH_STATUSES = ("exact", "partial", "mismatch")     # :122
  ```
  文内定位那一问的出口在 `agent_prompts.py:573` / `specs/a.py:152`（"回报定位结论（matched ∈ exact/partial/**none**）"），**在回报文本里**（`46-01 §1.2(f)`）。
- **改的依据**：`draft/46-01 §1.2(f)` + `§3 表第 4 行`；`draft/44 E-09`（` 禁 `(schema) ` 读 `，建议 `加`，实质理由"'取回 N 行'≠'取回对口'"）+ `draft/44 §19 J-27`（引 `46-01 §3`）；
  `draft/45 §1.1③`（原提议）**已被 `45` 顶部更正横幅第 1 条与本判定证伪**，不得采信。
  关键证据：`LIT_MATCH_STATUSES`（`:122`）与 `Literature.validate`（`:324-328`）、
  暴露面 `tools/table_tools.py:461/863-864`、判据 `verify.py:317-328`（`46-01 §1.2(f)`）；
  **兼容实测（我本次复算）**：加 `none` ⇒ `PASS 1322 / FAIL 0 / ESC 0`（§0.2 的 C 行）⇒ **兼容 ≠ 可做**；
  真机三档零产出 `[本次现算]`：根1 `literature` 1003 行 `matched` 全 `""`、根2 733 行全 `None`，**exact/partial/mismatch 各 0**。
- **怎么算过**：**不施工，故无"改后读数"。** 唯一要跑的"过"是**不回归**：
  ① `python -B -m pytest -q -p no:randomly` + `python -B scripts/lint_rules.py` 在本组其他条目落地后仍绿（本条不改判据）；
  ② `tests/test_literature_match.py:126-127`（三档断言）应保持绿；
  ③ 若有人未来真要加 `none`，`tools/vocab_census.py` 会**多报一条死取值**（`46-01 §1.2(f)` 逐字："加 `none` 只把死取值 3→4（`tools/vocab_census.py` 会多报一条）"）——
  这是"加一个立刻死的取值"的代价读数，记在 `draft/44` 该行即可。
- **不许这么改 / 边界**：**不许施工**（照抄 `46-01 §3`）。附加边界：
  ① 不许用"兼容 1322/0"当"可做"的理由（这正是 `46-01 §1.2(f)` 点名的误读：**兼容 ≠ 可做**）；
  ② **正确方向**（本件记录、不施工）＝给"文内定位三态"新落点列（如 `literature.finding_matched`）——**要新列 = 加字段，属人裁，本批不做**
  （`46-01 §1.2(f)` 逐字 + `§1.7 第 1 条`"E-09 的'新列'…都是新增字段，本批不做"）；
  ③ 不许把 `specs/a.py:152` 里的 `none` 删掉来"统一口径"（那是把两问折成一问，方向相反）。
- **依赖与批次**：**不施工**（无批次）。若将来人裁定"加新列"，则它的批次归 `draft/44` 批次 5（工程卫生/元判据）或新建批次，
  且必须与 `tools/vocab_census.py` 的 `RESERVED_VALUES` 登记同批（否则 lint `R011` 报死取值）。

### 条目 EE-06 — `documents[].claims` 的 `status` / `allowed_use` 0/449（路线 2 局部可做；路线 1 / 路线 3 **不施工**）

- **改什么**：**路线 2 = 纯增量 + 局部**——**不加必填、不升版**，只在字段**存在时**校验其取值域；
  并把 `claimanatomy` 的四张词表**搬到 `schema.py` 作唯一来源**（`claimanatomy` 改为转发 + 一句"同一个对象"断言）。
  路线 1（`status` 进必填）与路线 3（删空转字段）**不施工**。
- **怎么改**：接口级。
  - `schema.py:1344`（`claims: list[dict]` 容器形状）+ `Document.validate` 的 claim 级校验段 `:1387-1451`（`[本次确认：:1388-1393 是"只认固定键、不拒绝未知键"的那一段]`）：
    ```python
    # 在 :1393（claim_id 检查）之后插入：只在字段存在时校验取值域（不加必填）
    if (st := c.get("status")) is not None and st not in CLAIM_STATUSES:
        raise ValueError(f"claims[{cid}].status 必须是 {CLAIM_STATUSES} 之一，收到 {st!r}")
    if (au := c.get("allowed_use")) is not None and au not in ALLOWED_USE_KINDS:
        raise ValueError(f"claims[{cid}].allowed_use 必须是 {ALLOWED_USE_KINDS} 之一，收到 {au!r}")
    ```
    词表常量名以 `schema.py` 现有风格为准（`46-01 §1.2(g)` 的伪码写作 `CA.STATUS_VALUES`/`CA.ALLOWED_USE_VALUES`，
    但**实测这两个名字在仓库里不存在** `[本次确认：grep `STATUS_VALUES`/`ALLOWED_USE_VALUES` 命中 0]`；
    真身是 `claimanatomy.CLAIM_STATUSES = ("证","验","待精化","作废")`（`:135`）与
    `claimanatomy.ALLOWED_USE_KINDS = ("主结果","Remark only","移入 open")`（`:139`）`[本次确认]`）。
  - 搬运：把 `claimanatomy.py:130/135/139/142` 的 `CLAIM_KINDS`/`CLAIM_STATUSES`/`ALLOWED_USE_KINDS`/`NUMERIC_EVIDENCE_KEYS`
    搬进 `schema.py`（唯一来源），`claimanatomy` 改为 `from .schema import …` 转发，并加一句
    `assert schema.CLAIM_STATUSES is claimanatomy.CLAIM_STATUSES`（"同一个对象"，`46-01 §1.2(g)` 路线 2 的前置）。
    两处 `FieldSpec` 的 `domain=` 已分别是这两个词表（`claimanatomy.py:273` / `:349` `[本次确认]`）⇒ 转发后**零改动**自动同源。
  - **产出方**（`46-01 §1.2(g)` 的"建议改为加产出方"，本组只登记落点、可后置）：
    `tools/doc_tools.py:700/778`（`compose_claim` 已收 `allowed_use`）⇒ 改成"按 `evidence_kind` 由框架渲染默认值 + 区分'没写'与'写了空'"（三态工具已在 `claimanatomy.presence_of:865`）。
- **改的依据**：`draft/46-01 §1.2(g)`（三条互斥路线的完整判定）+ `§1.4` 表 + `§1.5` 表 + `§3 表第 5 行`；`draft/44 EE-06`（` 禁 `(schema)，建议"减（去掉空转字段）或 加（补产出方）"）+ `draft/44 EE-01`（"`status` 0/449、`allowed_use` 0/449（判据字段从未产出）"）。
  关键证据：**本次实测复核**（§0.3）`status` 0/449、`allowed_use` 0/449，claims 键全集不含二者；
  消费方 `gates.py:2178/2191`（G14）、`claimanatomy.py:1748`（`main_body_claims`）、`doc_tools.py:966/1100`（渲染）
  ⇒ **有读者、有声明、无产出方**（`46-01 §1.2(g)` 逐字）。
  **路线 1 的代价实测（我本次复算，§0.2 A 行）**：`PASS 1322 → 1270`，**52 份 `documents.json` 当场变红**。
  仓库内已有同题未实施提案 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md`：状态逐字"未实施（schema.py 一个字都没动）"，
  §3.2/§3.3 给出同一结论与分段建议（"第一次：只加受控词表常量与'打了这些字段才检查'的取值域校验，`SCHEMA_VERSION` 不动"）`[46-01 §1.2(g)]`。
- **怎么算过**：
  - **负控（改前必红）**：新增 `test_claims_status_is_checked_only_when_present`（`46-01 §1.6` 第 5 条）：
    ```python
    缺 status 的 claim 通过                                   # 改后必须仍通过（放行面）
    with pytest.raises(ValueError):
        status = "已证"                                     # 不在 ("证","验","待精化","作废") 里
    ```
    **必须先跑一次、必须红**（改前 `status="已证"` 不被拦；我本次实测复核：`validate_table("documents", …claims[0].status="已证"…)` **返回 OK** `[本次现算]`，见 §0.5 探针 9）。
  - **真机回放**：根1 `p8e-fermat-shorter-proof`（4 条 claims）+ 根2 `p2-review` 一族。
    读数 = `status`/`allowed_use` 两键非空计数。改前 `[本次现算]`：两根 `0 / 0`（合计 0/449）。
    预期改后：**历史行一字不变**（只加"存在时校验"，不改读写默认值）；**`0/449` 在路线 2 下不会变**
    ——这一点必须写在提交信息里：**路线 2 不解决"0 产出方"**（`46-01 §1.2(g)` 逐字"这一步**不解决'0 产出方'**"）。
  - **会红的既有判据**：**路线 1 无既有测试会红 —— 这正是它的危险**（`46-01 §1.6` 逐字）。
    路线 2 的会红面：`tests/test_agent_h.py:261`、`tests/test_verify_extended.py:433`、`tests/test_tools_audit_fixes.py:53-67`、`tests/test_closing_gate.py:132-139`
    （`46-01 §1.3` 列的 `Document.validate`(claims) 覆盖面）。
  - **快照/文档/计数同步**：**词表搬进 `schema.py` 会进提示词吗？** 会——`46-01 §1.1` 已逐字列出词表经 `specs/*` 进提示词的落点（`specs/b.py:122/131`、`specs/a.py:83`、`specs/d.py:126-127`、`specs/e.py:34`、`specs/g.py:53`）。
    若搬运改变了 `import` 图（`claimanatomy` 转发 `schema`），必须先跑
    `python -B tests/test_agent_surface_snapshot.py --write`（命令在该文件 `:25` `[本次确认]`）并**先看 diff 再提交**；
    若 diff 为空也要在提交信息里记"空 diff"。
    文档面：`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` 的状态行（"未实施"）要按事实改成"路线 2 已实施（取值域校验）"，
    并在 `draft/44` 该行记"从哪一趟起口径变了"（若口径有变）。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
    注意 词表搬到 `schema.py` 会改 `tools/vocab_census.py` 的"定义点"计数 ⇒ **lint 的提示数（49 / strict 48）可能变**；
    变了要**先确认是"定义点搬家"而不是"新死取值"**，并把新基线记在提交信息里（不许静默改基线）。
  - **兼容闸**：路线 2 是"存在才检查"的纯增量放宽 ⇒ 历史 1322 份必须仍 `1322/0/0`（§0.1 命令改后重跑）。
    **不许**在 `claims[]` 上加必填（§0.2 A 行：52 份红）；**不许**动 `SCHEMA_VERSION`（`schema.py:18`；`46-01 §1.4` 末段：动它 `validate_table:2702-2703` 拒掉全部 1322 份旧快照）。
- **不许这么改 / 边界**：照抄 `46-01 §1.2(g)` 与 `§3 表第 5 行`：
  ① **路线 1 不施工**（"把 `status` 加进必填集"）：实测 `PASS 1322→1270`，52 份当场红；且 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md §3.2` 逐字"默认值会把'从没问过'伪造成'待精化'"。
  ② **路线 3 做不到字面意义**：字段**不在 `schema.py`**，删不掉（要说清这一点，不许写成"已删"）。
  能删的只有消费侧 `gates.py:2143-2216`（G14 三条分支）、`claimanatomy.py:345-353`、`doc_tools.py:1544`——那等于**改读数口径**（`46-01 §1.2(g)` 逐字 + `45` §0 第 2 条）⇒ 本组**不删**。
  ③ 本条的**收益边界**必须写在提交信息里：路线 2 只让"写错取值"当场炸，"0 产出方"不动 —— 后者要靠"加产出方"（`compose_claim` 默认渲染），那一步本组只登记落点。
- **依赖与批次**：**前置 = 词表单一来源搬迁**（`46-01 §1.5` 的"EE-06 前置"列逐字"词表单一来源搬迁"）。
  批次归属 = `draft/44` 批次 4 追加之四（EE-06）但走"加"这一支；与 **EE-07 路线 B** **必须同批**
  （两条都在处理"声明了却没人产出"的同一族病，且都要动 `claimanatomy`/`schema` 的同源关系）。
  顺序：**词表搬迁 → 存在时校验 → （后置）产出方**。若产出方不做，本条**不算完成**（收益为零），须在 `draft/44` 该行明写"只做了验证面，未加产出方"。

### 条目 EE-07 — `evidence_kind` 被声明"派生只读视图"却被手填（路线 A 可选、路线 B 局部；**必须选一条并写明另一条为什么不做**）

- **改什么**：二选一（`46-01 §1.2(h)` 要求"必须选一条并写明另一条为什么不做"）。
  **路线 B（局部，推荐先做）= "减"注释 + 加一条一致性判据**：把 `schema.py:1604-1605` 那两行注释改成事实（"手填字段 + 一条一致性判据"），
  读法统一到"手填 + 一致性判据"；**路线 A（牵动接口）= 降成真·派生**：`Statement` 不再收 `evidence_kind`，读侧唯一入口改为由 `bits` 现算。
- **怎么改**：接口级。
  - **路线 B（本组施工面，2 行 + 1 条判据）**：
    `schema.py:1604-1605`（`[本次确认：:1604`"证据等级（复用 `EVIDENCE_KINDS`）：proof / cross_check / heuristic。"、`:1605`"`draft/39` §3.14 起它是**派生只读视图**：真正判等级的是 `bits`（五元证据位）。"）⇒ 改成事实；
    判据落点：写入口一致性检查（`agent_b/register_statement.py:97-101` 的 `bad_evidence_kind` 一族之后），
    形如"`evidence_kind == "proof"` 而 `bits` 的第 2/4 位为空 ⇒ 记一条 `pending`（或按人裁升级为 `_refuse`）"。
  - **路线 A（只给方案与代价，本组不施工）**：① `Statement` 去掉/标废弃 `evidence_kind`；② `evidencebits` 加 `kind_of(bits) -> "proof"|"cross_check"|"heuristic"`
    （口径与 `derive_grade` 同源：`formal verified ⇒ proof`；`proof 位 / numeric verified ⇒ cross_check`；否则 `heuristic`）；
    ③ 影响面（`46-01 §1.2(h)` 实测）：`specs/b.py:131` 的 enum 消失 ⇒ 提示词变 ⇒ 重冻 golden；`register_statement` 的 `bad_evidence_kind` 分支（`:98-101`）退场；
    `closing.py:1440/1450/1854/1877` 与 `claimanatomy` 的读法改走 `kind_of` ⇒ 牵动接口（≥6 文件 + 快照）。
- **改的依据**：`draft/46-01 §1.2(h)` + `§1.4` + `§1.5` + `§3 表第 8 行`；`draft/44 EE-07`（` 禁 `(schema) ` 行 `，建议 `加`："单一来源：要么派生、要么手填，不能两者都是"）。
  关键证据（"注释是假的"的硬读数）：`grep 'bits=' src/` = **0 命中** `[46-01 §1.2(b)/(h)]`；
  `statements.evidence_kind = {cross_check:124, heuristic:8, proof:6}` 而 `bits` 非空 **0** `[本次现算]`
  ⇒ **一条 `evidence_kind="proof"` 且 `bits={}` 的行今天完全合法**（6 行就是），`validate_table` 全过
  ——我本次实测复核了这一形态：`Statement(validation_kind="proof", bits={}, quote_reason=…).validate()` **返回 None** `[本次现算，§0.5 探针 6]`。
  三条口径各说各话：`evidencebits.derive_grade`（读 `bits`）、`claimanatomy.status_evidence_consistency:917`（读 `status`×`evidence_kind`）、
  `closing.py:1438-1451`（读 `evidence_kind`）。
  顺带（`46-01 §1.2(h)` 登记）：`schema.py:1684` 的 `if self.bits:` ⇒ **空 bits 直接跳过**，"声明了五元位却一位都没记"在数据面**没有任何判据**（§0.5 探针 8 复核）。
- **怎么算过**：
  - **负控（改前必红）**：新增 `test_evidence_kind_is_not_a_second_grade_source`（`46-01 §1.6` 第 6 条）：
    ```python
    row = {"stmt_id":"0000","origin":"own_result","proof_text":"证明","evidence_kind":"proof","bits":{}}
    assert S.row_from_dict("statements", row).validate() is None
    assert EB.bits_from_row(row)["grade"] == "conjecture"
    ```
    **必须先跑一次、必须红**（改前**两行都成立** ⇒ 这条"断言"是绿的，也就是说它**不带判据**；
    真正的"红"要由路线 B 新增的一致性判据提供：`evidence_kind="proof"` 且 `bits={}` ⇒ 必须有 `pending`/必须被拒。
    ⇒ **本条必须自己写出一条改前必红的负控**（形如 `assert r["pending"]` 含 `evidence_kind_without_bits`），否则不允许声称落地 —— 这是 `45` §2 第 2 步的硬约束）。
  - **真机回放**：根1 `p6e-research-from-zero`（`46-01 §1.6` 建议 `p8e`，**该样本行号面已漂移**，见下）。
    读数 = `evidence_kind=="proof"` 行数 与 `bits` 非空行数（**改前 6 与 0，不相等即 EE-07 的读数形态**）。
    我本次分根复核 `[本次现算]`：根1 138 行里 `evidence_kind=="proof"` **6** 行、`bits` 非空 **0** 行（**6 ≠ 0**）；根2 **0 行 statements**。
    逐工作区样本（根1）：`p6e-research-from-zero` 2 行 —— `0000 external_lit ek=cross_check bits=None`、`0001 own_result ek=proof bits=None`（**这正是"proof 而 bits 空"的活样本**）。
    注意 `46-01 §1.6` 写的样本 `p8e-fermat-shorter-proof`：我本次实测该工作区 `statements.json` **0 行**（`p8c`/`p8f` 甚至没有 `statements.json`）
    ⇒ **`46-01` 给的样本工作区已漂移，实测改用 `p6e`/`p5-review-t9`**。
  - **会红的既有判据**：**路线 A** → `tests/test_agent_surface_snapshot.py:207`、`tests/test_release_all.py:1039`
    （`specs/b.py:131` 的 enum 消失）；另 `tests/test_evidence_bits.py`、`tests/test_agent_b.py`。
    **路线 B** 的会红面：`tests/test_evidence_bits.py`、`tests/test_agent_b.py`（新增一致性判据若升级为拒）。
  - **快照/文档/计数同步**：**路线 B 不改词表** ⇒ 无需重冻（但 `schema.py:1604-1605` 是纯注释，改它不进提示词）；
    **路线 A 必须重冻** `python -B tests/test_agent_surface_snapshot.py --write`（命令在该文件 `:25` `[本次确认]`）+ 同步
    `tests/test_release_all.py:1039` 的读数 + `docs/ROLE-SPECS.md`。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：**路线 A** 的历史影响（`46-01 §1.4` 表）："是（减字段）⇒ 历史 1322 份 0 红 —— 历史行靠 `row_from_dict` 忽略未知键读进"
    （`schema.py:2747` docstring 逐字"未知字段会被忽略（向前兼容）"`[本次确认]`）；
    **路线 B** 是纯注释 + 新增判据（若判据只记 `pending` 不拒）⇒ 1322 份仍 `1322/0/0`。
    两条路线都**不动 `SCHEMA_VERSION`**（`46-01 §1.4` 末段）。
- **不许这么改 / 边界**：照抄 `46-01 §1.2(h)` 与 `§1.7 第 4 条`：
  ① **不真删 `Statement.evidence_kind`**（`46-01 §1.7 第 4 条` 逐字："不真删 `Statement.evidence_kind`（EE-07 路线 A 只给方案与代价）"）。
  ② **不许把 `evidence_kind` 变成第二份等级来源**（那是 EE-07 的病灶本身）；路线 A 若做，必须先定 `kind_of` 的口径表（`46-01 §1.5` 前置列逐字"路线A 先定 kind_of 口径表"）。
  ③ `schema.py:1684` 的 `if self.bits:` 空 bits 跳过**不许在这一条里顺手改成"空 bits 也报错"**——那会把 1322 份历史里的 0 个空 bits 变成新判据面，
  属"加必填"的同族，本批不做（`46-01 §1.4` 表已把它列在"不需要动"一侧）。
  ④ `schema.py`（`.noai-paths:93/102`）与 `specs/b.py`（`.noai-paths:127`）**都在禁改区** ⇒ **改后必须报备人审、不代签、需 2 名 reviewer**。
- **依赖与批次**：**前置**：路线 A "先定 `kind_of` 口径表"（`46-01 §1.5`）；路线 B 无前置。
  **同批**：与 **F-01（§1.2）必须同批**（两者都在把"等级/证据类型谁说了算"统一到一处）；
  与 **EE-06 路线 2 同批**（都动 `claimanatomy` ↔ `schema` 的同源关系）。
  批次归属 = `draft/44` 批次 4 追加之五（EE-07）+ 批次 1（地基）的等级族。
  顺序：**F-01 产出方 → EE-07 路线 B 判据 → （可选）EE-07 路线 A**。

---

## §2 `src/agentflow/store.py`（1449 行）`[本次确认：行数=1449]`

> **本文件也在 FC-27 禁改区**：`.noai-paths:94`（`src/agentflow/store.py [category: schema-migration] LOCK_ORDER / rebuild / alloc_id / _atomic_write：加锁顺序、事件重放、ID 分配、原子落盘 —— 四者任一错都是**数据毁灭级**`）。
> ⇒ 本条内**每一条**改动都：**改后必须报备人审、不代签 `.noai-approvals.json`、需 2 名 reviewer**；
> 门：`python -B scripts/noai_gate.py --git --since <基线>`（退出码 1 = requires_human）。

### 条目 R-02 — 实验日志被覆盖（**store 侧 0 改动**；真凶在 `agent_e`，本组只登记判定与落点）

- **改什么**：**store 侧不改**（不改计数器语义、不改 `tx` 的提交/回滚、"不许被覆盖"这一条的性质 = **不加计数器推进、改日志落盘时机/命名**）。
  真改动在 `agent_e`（≈15–30 行），本组只**保留判定**并写清落点与验收。
- **怎么改**：接口级（落点在 `agent_e`，本文件 0 行）。
  - **现状（本文件侧，只登记不改）**：`store.py:962-967`（counters 只在写者锁内合成、只在提交成功时落盘）`[本次确认]`；
    `store.py:994-999`（`finally` 里 `self._dirty_counters = None` **无条件**清进程内缓存）`[本次确认]`。
  - **真凶（`agent_e` 侧，可选三选一）**：`agent_e/run_experiment.py:165-174`（在事务体内用 `eid` 命名并**立即写盘**：`log_rel = f"out/experiments/{eid}.log"` 后立刻 `_write_run_log(...)`）`[本次确认：:165 with 块、:166 alloc_id、:171 log_rel、:172-174 _write_run_log]`
    + `agent_e/_support.py:689-702`（`target.write_text(...)` = **覆盖写**）`[本次确认：:691 target.write_text]`：
    ```
    (a) 把 _write_run_log 移到 with 块之后（提交成功再写，artifact_paths 提交后补一次 upsert）
    (b) 日志名带唯一后缀 <eid>.<pid>-<tid>.log，提交成功后 os.replace 成 <eid>.log
    (c) 先写 out/experiments/.pending/<eid>.<唯一>.log，提交后 rename
    三者都保持 artifact_paths 记的仍是 out/experiments/<eid>.log ⇒ 不动存储契约；
    与 46-06 §3.2(b) 的 _write_run_log(..., overwrite=False) 同族，建议合并为一处。
    ```
- **改的依据**：`draft/46-01 §2.2(a)` + `§3 表第 1 行`（"**不可行**"）；`draft/44 R-02`（` 禁 `(store) ` 行 `）+ `draft/44 §19 J-03`（逐字"**先只做 agent_e 侧'日志不覆盖/加序号'**（可独立落地）；store 侧的计数器语义与那条反判据**列入人裁**"）；
  `draft/45 §1.1` 的"事务回滚时推进计数器（或让 `alloc_id` 只在提交后生效）"**已被 `45` 顶部更正横幅第 1 条与 `46-01 §3` 证伪**，不得采信。
  关键证据：§0.4 的根1 `p8c` 读数（`0001.log` 与 `0002.log` **逐字节相同**、2 个孤日志）`[本次现算]`；
  `tests/test_store_concurrency.py:229/234`（`[本次确认]` 断言原文见 §0.6）是 store 侧改法的**反判据**；
  `46-01 §2.2(a)` 另给两条独立反驳（`rebuild` 的 counters 只由事件里的 alloc 推出 `store.py:1327-1332` `[本次确认]`；`alloc_id` 不能推迟为接口）。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_agent_e_run_log.py` 新增 `test_a_rolled_back_experiment_does_not_overwrite_the_previous_log`
    （`46-01 §2.6` 第 9 条）：同一 `eid` 第二次运行（第一次事务故意失败）之后，**断言第一次的日志字节仍在** —— **改前 `write_text` 覆盖 ⇒ 必红**。
  - **真机回放**：根1 `p8c-fermat-shorter-proof`（另有 `p6e-research-from-zero`、`p5-review-t1`）。
    读数 = "无任何台账行引用的 `out/experiments/*.log` 个数" + "同一 `<eid>.log` 被多行引用"。
    改前实测 `[本次现算，§0.4]`：`p8c` 孤日志 **2 个**（`0000.log`、`0001.log`），且 `0001.log` 与 `0002.log` **逐字节相同**（同 sha256 前 16 位 `e268de5b7f7a1cac`）。
    预期改后 = **0 个孤日志**（每次运行的日志都有对应台账行引用）。
    只读命令：`python -B -c "…glob <ws>/out/experiments/*.log；与 <ws>/data/experiments.json 的 artifact_paths 做差集…"`。
  - **会红的既有判据（若走 store 侧 = 反判据）**：`tests/test_store_concurrency.py:212`（`:229`/`:234`）、`:152`（`:148`/`:164`/`:166`）、
    `tests/test_store_alloc_guard.py:111` 一族 —— **本组不改 store 侧 ⇒ 这些必须保持绿**；它们红了就说明有人动了计数器语义（越界）。
    **若走 agent_e 侧**：`tests/test_agent_e_run_log.py`（`46-01 §2.6` 列）。
  - **快照/文档/计数同步**：`store.py` **不进任何 specs 镜像、不进 golden 快照**（`46-01 §2.3` 末段）⇒ 无需重冻。
    但 `cli.py:328-336`（`[本次确认：:333 rebuild、:334 打印 applied/skipped]`）与 R-06 同批需同步；
    文档面：`README.md:378`、`DESIGN.md:480`（17 表快照 + `events.jsonl`）、`DEVELOPMENT.md:171/486`（`data/` 18 个 JSON）**本条不动**（若 R-06 改了 `rebuild` 的返回键，才需要看这三处是否需要补一句）。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：本组 store 侧 0 改动 ⇒ §0.1 的 1322 份命令结果应**恒等** `1322/0/0`；
    历史 969 份快照同理（不含 counters）。**唯一不可逆点 = `counters.json` 的语义（ID 生命周期）**：本批**不动它**
    （`46-01 §2.6` 逐字："唯一不可逆点是 **`counters.json` 的语义（ID 生命周期）**。防法：本批不动它"）。
- **不许这么改 / 边界**：照抄 `46-01 §3 表第 1 行` 与 `§2.2(a)` 的**三条反驳**：
  ① **不许"事务回滚时推进计数器"**：与 `tests/test_store_concurrency.py:229`/`234` **逐字相反**（推进计数器要写 `counters.json` ⇒ 必红）；
    另 3 处 docstring 同侧：`tools/search_tools.py:1085`、`store.py:995-998` `[本次确认]`、`store.py:350-358` `[本次确认：R6-AN-1 段]`。
  ② **独立反驳**：`rebuild` 的 counters 只由事件里的 alloc 推出（`store.py:1327-1332` `[本次确认]`），而回滚事务的 alloc 事件**不在** `events.jsonl`（事件只在提交块追加，`:966-967` `[本次确认]`）⇒ 即使推进 `counters.json`，下一次 `rebuild` 会把它退回去。
  ③ **"`alloc_id` 只在提交后生效"不可实现为接口**：调用方要在事务体内用 `eid`（命名日志、写 `artifact_paths`、返回 `{"experiment_id": eid}`），号不能推迟。
  ④ 不动 `_atomic_write`（`store.py:761-830`）的临时名/重试/异常类型、不动 `LOCK_ORDER`（`:66-90`）与 `Tx` 的取锁/释放语义（`46-01 §2.7 第 1 条`）。
- **依赖与批次**：**与 `46-06`（角色 E/F）的 `_write_run_log(..., overwrite=False)` 同族，必须合并为一处施工**（`46-01 §2.5` 表内逐字"与姊妹件 §3.2(b) 合并为一处"）；
  `draft/44 §19 J-03` 的分半：**agent_e 侧可独立落地**（先做）；**store 侧的计数器语义列入人裁**（本组不做）。
  批次归属 = `draft/44` 批次 0（红线）+ `45` §4 批 0 的完成判据（"日志不再被覆盖"）。
  顺序：**R-02（agent_e 日志）与 R-06（store 明细）可并行**；R-02 与 R-05 无依赖。

### 条目 R-06 — `rebuild` 的行级失败静默丢行（`skipped` 类型不许变；**加"明细"两类键 + cli 打印**）

- **改什么**：**纯增量**——保留 `skipped` 这个整数键（3 处测试直接断言它的数值），**新增** `skipped_by_reason: dict[str,int]` 与 `skipped_details: list[dict]`；
  并把 `except` 从"一条 `except Exception` 静默 `skipped += 1`"改成**分类捕获并两支都记明细**（**不是收窄**）。
- **怎么改**：接口级，三处落点。
  - `store.py:1337-1342`（`[本次确认：1337 try、1338 row_from_dict、1339 obj.validate()、1340 except Exception、1341 skipped += 1、1342 continue]`）：
    ```python
    try:
        obj = S.row_from_dict(table, row); obj.validate()
    except ValueError as e:
        reason = "schema_rejected"
    except Exception as e:
        reason = "shape_broken"
    else:
        reason = None
    if reason is not None:
        skipped += 1
        skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
        skipped_details.append({"table": table, "id": row.get(S.TABLES[table]["id_field"]),
                                "reason": reason, "error": f"{type(e).__name__}: {e}",
                                "event_index": <当前 replay 下标>})
        continue
    ```
    另 `:1334-1336` 的 `if table not in S.TABLES:` 支也走 `skipped`：给它 `reason = "unrecognized_table"`。
    再在 `:1268`（`applied = skipped = 0` `[本次确认]`）附近初始化两个新容器。
  - `store.py:1377-1411` 的返回字典（`[本次确认：:1379 "skipped": skipped]`）：**只增键**：
    `"skipped_by_reason": dict(sorted(skipped_by_reason.items()))`、`"skipped_details": skipped_details`（放在 `:1410` 的 `unknown_ops` 之后即可）。
  - `cli.py:334`（`[本次确认：:334 print("[rebuild] 已从事件日志重建：应用 … 跳过 …")`]）后加一行，`skipped_by_reason` 非空时打印它（约 3 行）。
- **改的依据**：`draft/46-01 §2.2(b)` + `§3 表第 3 行`（"R-06 把 `except Exception` 改窄 **不可行**"）；`draft/44 R-06`（` 禁 `(store) ` 读 `，建议 `加`，实质理由"'重建成功'是假的第三态"）。
  关键证据：`store.py:1021-1023` 与 `schema.py:1021-1024` 逐字写明"静默丢"是数据遗失 `[46-01 §2.2(b)]`；
  本次复核：1322 份 `validate_table` 全过（§0.1）⇒ **今天被 schema 挡下的行是 0**，R-06 的收益在**未来加严判据**与**事件行形态坏**两类；
  `draft/41` §3.5 记 57 工作区 `skipped=0` `[46-01 §2.2(b)]`。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_rebuild.py` **新增**两条（`46-01 §2.6` 第 7/8 条）：
    ```python
    # 7)
    追加一条 level="bogus" 的 review_findings upsert（无 batch/无版本号）
    out = store.rebuild(backup=False)
    assert out["skipped"] == 1
    assert out["skipped_details"] == [{"table":"review_findings","id":"0002","reason":"schema_rejected", …}]
    # 8)
    追加 {"op":"upsert","table":"concepts","row":{"concept_id":"0003"}}（缺 name）
    assert out["skipped_by_reason"]["shape_broken"] == 1
    ```
    两条 **必须先跑一次、必须红**（改前 `KeyError("skipped_details")` / `KeyError`）。
    第 8 条同时**钉住"不许收窄 `except`"**：取证即 §0.5 探针 5（`row_from_dict` 对缺参行抛 `TypeError`）
    与 `tools/table_tools.py:121-123` 逐字（`[本次确认：:121 except TypeError、:122-123 注释"缺必填字段时 dataclass 抛的是 TypeError，不是 ValueError"`]）。
  - **真机回放**：**不能直接跑 `agentflow rebuild`（会写盘）**⇒ 只读替代品 = `python -B D:\Incubator\draft\_probe_c_rebuild_dryrun.py`（逐工作区模拟折叠、不落盘）；
    建议样本 = 根1 `p6e-research-from-zero`。改前读数 = `draft/41` §1.2 记的 57 工作区 `skipped=0 snapshot_ahead=0 incomplete=0` `[46-01 §2.4，未复算]`；
    预期改后 = `skipped` 不变、`skipped_by_reason` 为空字典、`skipped_details` 为空列表（**"0 静默丢行"从"一个数"变成"一个可核的空明细"**）。
  - **会红的既有判据（逐条列出，要求保持绿）**：`tests/test_rebuild.py:69`（`assert out["applied"] == 4 and out["skipped"] == 0`）、
    `tests/test_rebuild.py:104` 一族（`corrupt_events`，`:105 assert out["corrupt_events"] == 2`）、
    `tests/test_p910_p9_review_finding_format.py:521`（`skipped == 0`）/`:557`（`skipped == 1`）、
    `tests/test_store_delete_events.py:70-158`、`tests/test_store_r3_commit_order.py:79/127/145/182/301`。
    ⇒ **反向约束**：若把 `skipped` 改名或改成 list，这三条会一起红 —— **不许**。
  - **快照/文档/计数同步**：`store.py` 不进快照 ⇒ 无需重冻；`cli.py:334` 的打印行**必须同批改**（否则明细没有人看得见 —— `46-01 §2.2(b)` STEP-3 逐字"让明细看得见"）。
    文档面：`DESIGN.md:480`（`events.jsonl` 相关）与 `DEVELOPMENT.md:171/486`（`data/` 18 个 JSON）**本条不动**（返回值形状不进这些文档）；
    若 `README.md` 有 `rebuild` 返回值说明，按"先改代码 → 跑判据让它点名 → 再改文档"顺序补。
  - **全量门**：`python -B -m pytest -q -p no:randomly`（约 27–30 分钟）+ `python -B scripts/lint_rules.py`（基线 0/9/49；`--strict` 0/58/48）。
  - **兼容闸**：本条**不改行形状**（只改返回值与 `except` 分类）⇒ §0.1 的 1322 份命令结果应恒等 `1322/0/0`。
    `rebuild` 的**重放结果**会变吗？不会 —— 分类捕获两支都仍然 `continue`（丢行的决定**不变**，`46-01 §2.2(b)` 逐字："R-06 不改'丢'这个决定，只改可不见度"）。
    ⇒ 只读替代品（`_probe_c_rebuild_dryrun.py`）的读数应当与改前逐工作区一致（`skipped=0`）。
- **不许这么改 / 边界**：照抄 `46-01 §3 表第 3 行`：
  ① **不许把 `except Exception` 收窄成 `except ValueError`**：`S.row_from_dict` 对缺必填位置参数的行抛 `TypeError`（`tools/table_tools.py:121-123` 逐字承认，§0.5 探针 5 实测）⇒ 收窄后这类行会让**整次 rebuild 崩**，比静默丢更糟。正确做法是**分类捕获并两支都记明细**。
  ② **不许改 `skipped` 的类型/名字**（3 处测试直接断言数值，见上）；新键只增。
  ③ 不动 `_snapshot_keys`/`snapshot_ahead`/`snapshot_rows_not_in_log`（`store.py:1171-1195`、`:1290-1295`，R3-3 口径不变；R-06 的明细是**新增**键）——`46-01 §2.7 第 3 条`。
  ④ 不动 `rebuild` 的 counters 折叠规则（`:1327-1332`）与"先事件后快照"的提交顺序（`:913-929`）——`46-01 §2.7 第 2 条`。
  ⑤ 不在 store 侧兜 schema 的 `TypeError`（"只做诊断改善会掩盖数据问题"——`46-01 §2.7 第 3 条`末句）。
- **依赖与批次**：**无前置**（`46-01 §2.5`：R-06 局部，15–25 行 store + 3 行 cli，2 文件，前置无）。
  批次归属 = `draft/44` 批次 0（红线，触及面 `禁`(store) ` 读 `）。
  与 R-05 **同批**（同属"灾难恢复不许被非 `ValueError` 打断 / 不许静默丢行"这一族）；
  顺序：**R-05 先（schema 侧定"什么算 schema 拒绝"）→ R-06 后（明细的 `schema_rejected` 才有稳定语义）**。
  与 `draft/44 §19 J-21` 无直接依赖。

---

## §汇总

### 汇总表：本组 10 条条目总表

| 条目 | 文件（含直接调用点） | 可行性（照抄 `46-01`） | 是否 FC-27 禁改区（改后报备人审 / 不代签 / 2 名 reviewer） | 批次（`draft/44`） |
|---|---|---|---|---|
| **R-05** | `schema.py:2429-2434` + 7 处行级内联件（`:374/418/577/659/669-672/811/1672`）（调用点 `store.py:947/1374` **0 改动**） | **局部**（20–35 行 / 1–2 文件 / 前置无）；判定："改 `:2432`"**必要但不充分** | **是**（`.noai-paths:93/102`） | 批 0（红线），与 R-06 同批，**R-05 先** |
| **F-01** | 落点 `agent_b/register_statement.py:179-199`（`schema.py` **0 改动**）；claims/Relation 侧不施工 | **半不可行**：Statement 侧**局部**（10–25 行 / 2 文件）；claims/Relation 侧**牵动接口**（≥60 行 / ≥4 文件）⇒ 不施工 | **是**，只因"claims/Relation 侧若要动 schema"；本组只动 `agent_b`（非禁改区）⇒ 仍建议先改后报备 | 批 1（地基），与 EE-07-B 同批 |
| **P-06** | `schema.py:1657-1663` + `agent_b/register_statement.py:140-144` | **牵动接口**（15–30 行 / 4 文件 + 4 测试 / 前置 = F-05） | **是**（`schema.py:1657-1663` 半） | 批 3（提示词与减负），与 P-08 同批，**前置 F-05** |
| **P-07** | `tools/doc_tools.py:1112-1169`（主）；`schema.py:1412-1417` **可选减必填** + `claimanatomy.py:447-458` | **局部**（8–15 行 / 3 文件；落 doc_tools，**不在 schema**） | `doc_tools.py`/`claimanatomy.py` **不在**清单；**若改 `schema.py:1412-1417` 则是** | 批 3 |
| **P-08** | `schema.py` **0 改动**；`agent_prompts.py:595-597` + `specs/b.py` 镜像（待核队列 = F-05） | **纯提示词级**（本文件 0 改动 / 0 文件；前置 = F-05） | `agent_prompts.py` **不在**；`specs/b.py` **是**（`.noai-paths:127`）⇒ 镜像重建须报备 | 批 3，与 P-06 同批，**前置 F-05** |
| **E-09** | `schema.py:122`（+ `:103-121` 说明）/ `:324-328` | **不可行**（需新列 = 人裁）⇒ **不施工** | **是**（`schema.py`） | **不施工** |
| **EE-06** | 路线 2：`schema.py:1344` + `:1387-1451` + 词表搬自 `claimanatomy.py:130/135/139/142`；路线 1/3 **不施工** | 路线 2 **局部**（10 行 / 2–4 文件）；路线 1 **不可行**；路线 3 **牵动判据口径** | **是**（`schema.py`）+ `claimanatomy.py` 不在清单 | 批 4 追加之四（走"加"），与 EE-07-B 同批 |
| **EE-07** | 路线 B：`schema.py:1604-1605` + `agent_b/register_statement.py:97-101`；路线 A **牵动接口**、本组不施工 | 路线 B **局部**（2 行 + 1 判据 / 1–2 文件）；路线 A **牵动接口**（80 行 / 6 文件） | **是**（`schema.py`）；路线 A 另触 `specs/b.py`（**是**） | 批 4 追加之五 + 批 1，与 F-01/EE-06 同批 |
| **R-02** | `store.py` **0 改动**；真改动 `agent_e/run_experiment.py:165-174` + `agent_e/_support.py:689-702` | **不可行**（store 侧）/ **局部**（agent_e 侧，15–30 行 / 1–2 文件） | **是**（`store.py:994-999` 若动；本组不动 ⇒ 无命中） | 批 0（红线），与 `46-06 §3.2(b)` 合并为一处 |
| **R-06** | `store.py:1337-1342` + `:1377-1411`（返回键）+ `cli.py:334` | **局部**（15–25 行 store + 3 行 cli / 2 文件 / 前置无）；判定："收窄 `except`"**不可行** | **是**（`store.py`） | 批 0（红线），与 R-05 同批，**R-06 后** |

### 未核实项（明写，不许折成"没问题"）

| # | 项 | 出处 | 状态 |
|---|---|---|---|
| 1 | **1322 份历史快照逐份 `validate_table`** 的**原始**读数 | `46-01 §1.6`、`47` §4 第 1 行 | `47` §4 明写"未复核（可复算但耗时）"。**本轮我复算了 §0.1，得 1322/0/0** ⇒ 这一项由我本次补上；但 `47` §4 的口径（"主控未复核"）仍成立，引用时两处都要标 |
| 2 | **990 次逐档实跑（30 档 × 33 工作区）与 `32 fail / 1 unknown / 0 pass`** | `46-04 §3.3/§6.3`、`47` §4 | **未复算**（只复核了"33 份表逐格 = 32/1"这一层）。与本组无关，但引用 `closing` 面时必须标 |
| 3 | `ARTIFACTS` 分根全量 `1387 ok / 2599 ok + 589 changed` | `46-04 §6.3`、`47` §4 | 只抽验 80 行；**未复算** |
| 4 | `46-01 §1.2(d)` 的 **P-07 逐字常量计数（24 行 / 13 文件）** | `46-01 §1.2(d)` 自标"**未核实**" | 且 **`draft/44` 的"81 处"本轮未能复现，口径未核实** ⇒ 一律标 `[46-01 §1.2(d)，未核实]` |
| 5 | `46-01 §0④` / `§2.6` 的 **"全档案孤日志 3 工作区 5 个"** | `46-01 §0④` | 本轮**未复算**（只复算了根1 `p8c` 的 2 个孤日志）；引用时标 `[46-01 §0④]` |
| 6 | `draft/41` §3.5 / §1.2 的 **57 工作区 `skipped=0 snapshot_ahead=0 incomplete=0`** | `46-01 §2.2(b)`、`§2.4` | 本轮**未跑** `_probe_c_rebuild_dryrun.py`；引用时标 `[46-01 §2.4]` |
| 7 | **"artifact 文件的 sha256 ≠ 行里的 `code_hash`"这一形态的含义** | **本轮我第一次给出读数**（§0.4） | 我实测到"`0002` 行的 `code_hash=fb6863d8eefeb91c`，而 `0002.log` 实际 sha256 前 16 位 = `e268de5b7f7a1cac`（不相等）"；**该字段的设计语义（是脚本哈希还是日志哈希）未核实**，不许当成"台账说谎"的证据用 |
| 8 | `46-01 §1.6` 建议的真机样本 `p8c` / `p8e` / `p8f` 对 F-01/P-06/P-07 的适用性 | `46-01 §1.6` | **已漂移**：`[本次现算]` 根1 `p8c`、`p8f` **没有 `statements.json`**，`p8e` 的 `statements.json` 是 **0 行**，`p8f` **没有 `documents.json` 行**（claims=0）⇒ 样本改用 `p6e`（2 行 statements / 8 claims）、`p5-review-t9`（10 行 statements）、`p8e`（4 claims） |
| 9 | lint 基线"0 错 / 9 警 / 49 提示；`--strict` 0/58/48" | `46-01` 未给；**本方案按任务给定的基线口径** | **本轮未跑 lint**（只读任务未含脚本执行）；EE-06 的词表搬运**可能改变提示数** ⇒ 必须在施工时先记录改前实测基线，再改 |
| 10 | `46-01 §1.6` / `§2.6` 里各条"会红的既有判据"行号 | `46-01` | 我**逐条 read 过 §0.6 列出的那些行号**并记了断言原文；但 `46-01` 列的**其余**行号（如 `tests/test_action_surface_matches_acceptance.py:226`、`tests/test_conductor_payload_outcomes.py:126/133`、`tests/test_intake_actions.py:407`、`tests/test_verify_extended.py:433`）**本轮未逐条 read**，只按原文引用（施工时须先跑一次确认"确实红"） |

### 本组施工顺序（推荐 4 轮，每轮一次闭环）

> 闭环六步照 `45` §2：①清引用面 ②改代码 + 配负控 ③真机回放 ④全量套件一次 + lint + 快照重冻
> ⑤禁改区报备（`python -B scripts/noai_gate.py --git --since <基线>`，**不自签** `.noai-approvals.json`）⑥登记册回填。
> 硬约束照 `45` §2：不许跨批混改；**不许"提示词先删、代码后补"**；**不许加必填新字段**（只许放宽与带默认值新增）。

| 轮 | 内容 | 为什么这个顺序 | 该轮必过的闸 |
|---|---|---|---|
| **第 1 轮（schema，无前置）** | **R-05**（表级 + 7 处行级内联件 + 抽 `_set_problems`）→ **R-06**（`store.py` 明细两类键 + `cli.py:334` 打印） | 两条同属"灾难恢复面"，且 R-05 定完"什么算 schema 拒绝"后 R-06 的 `schema_rejected` 才有稳定语义 | §0.1 兼容闸（1322/0/0）+ 两条新负控（改前必红）+ 全量 + lint + 禁改区报备 |
| **第 2 轮（等级族：F-01 → EE-07-B → EE-06 路线 2）** | `agent_b` 补 `bits=` 产出方 → `schema.py:1604-1605` 注释改事实 + 一致性判据 → 词表搬进 `schema.py` + `claims` 存在时校验取值域 | 三条都在统一"等级/证据类型/生命周期三轴谁说了算"；**先在产出侧落地，再让判据说话**；EE-06 的"0 产出方"本组不解决，只做验证面 | §0.1 兼容闸（恒等）+ F-01/EE-06 两条新负控 + `statements.bits` 首见非 0（根1 `p6e`）+ 全量 + lint（注意提示数可能变）+ 快照（EE-06 词表搬家后先看 diff） |
| **第 3 轮（documents 面：P-06 与 P-07，前置 F-05）** | P-06（删 `schema.py:1658` 的 raise + 写入口改"落库 + `pending`"）与 P-07（`doc_tools.normalize_claims` 自动补 + `_autofilled` 留痕） | 两条都是"硬门槛 → 降级/自动补"；**没有 F-05 的队列接手人，`pending` 就是空转**（`46-01 §3` 末段）⇒ F-05 先有或同批给消费方 | 改写 `tests/test_statements_table.py:142` + 四条会红判据逐条确认 + 根1 `p8e` 真机读数 + 全量 + lint + 禁改区报备 |
| **第 4 轮（提示词面：P-08）** | 改 `agent_prompts.py:595-597` 真身 → `temp/_sync_policy.py` 重建 `specs/b.py` 镜像 → 重冻 golden | **代码侧必须先接住**（F-05 队列 + 第一/二/三轮的等级与降级），所以排在最后；且"必须与 P-06 同批"这条在轮次上体现为"第 3 轮与第 4 轮属于同一批，中间不许插入别的改动" | 提示词一致性元判据（注入式负控：改字必红）+ 重冻 `agent_surface_snapshot.json` 并看 diff + 全量 + lint + `specs/b.py` 的禁改区报备 |

**不施工条目**：E-09（不可行）· EE-06 路线 1（52 份红）· EE-06 路线 3（字段不在 `schema`，且会改读数口径）· F-01 的 claims/Relation 派生等级（要先发明映射）· R-02 的 store 侧计数器（反判据逐字钉住）· R-06 的"收窄 `except`"（会崩整次 rebuild）· P-08 的 schema 改动（现状方向正确）。
**跨条目前置（不在本组施工面，但缺了本组就是空转）**：F-05 待办/待核队列（`46-01 §3` 末段）；`statements → experiments` 的字段（`closing.py:1454-1464` 逐字说 `MUST_T3_CONDITIONS` 的 ②④ 今天只能 `counted_only`）。
