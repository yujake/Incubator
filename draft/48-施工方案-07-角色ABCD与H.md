# 48 施工方案 07：角色 A / B / C / D 与 H

> 本文件把 `draft/46-施工级调查-07-角色ABCD与H.md`（639 行）这份**已经完成**的逐文件调查，
> 转写成**可执行施工方案**。逐条给：改什么 / 怎么改（接口级）/ 改的依据 / 怎么算过 / 不许这么改 / 依赖与批次。
>
> 覆盖条目：**D-2 · EE-12 · EE-07 · S-01 · S-03 · S-02/S-07/S-08/S-09 · R-04-H**。
>
> 本文件**不新增任何判定**：凡 §14 汇总表给过的可行性与禁改区判定、§0 给过的读数、§8/§9 给过的
> 口径，一律照抄；本文件只做三件事 ——（1）把每个改动点落到 `文件:行号`；（2）给负控与真机回放的判据；
> （3）把"不许做什么"写成施工期边界。凡与 `46-07` 冲突处，以 `46-07` 为准。

---

## 范围

文件组（9 个施工单元）：

| 单元 | 文件 |
|---|---|
| B-1 | `src/agentflow/agent_b/core.py` |
| B-2 | `src/agentflow/agent_b/run_once.py` |
| B-3 | `src/agentflow/agent_b/register_statement.py` |
| C-1 | `src/agentflow/agent_c/_support.py` |
| C-2 | `src/agentflow/agent_c/{hottest,gaps,cold,paths}.py`（文件组，同一改动） |
| C-3 | `src/agentflow/agent_c/core.py` |
| C-4 | `src/agentflow/tools/graph_tools.py` |
| CD-1 | `src/agentflow/conductor.py`（S-01 的摘要截断那一半） |
| A-1 | `src/agentflow/agent_a/core.py` |
| D-1 | `src/agentflow/agent_d/{assess,consider,submit_gaps,research,core}.py` + `agent_d/_support.analyze_gaps` |
| D-2 | `src/agentflow/agent_d/write_report.py` |
| H-1 | `src/agentflow/agent_h/{core,verify_fixes}.py` + `src/agentflow/tools/review_tools.py`（R-04 的 H 侧） |

**只读依据（本文件不许改它们一个字）**：`agent_b/{core,run_once,register_statement}.py`、
`agent_c/{hottest,gaps,cold,paths,_support,core}.py`、`tools/graph_tools.py`、`conductor.py`、
`agent_a/core.py`、`agent_d/{assess,consider,submit_gaps,research,write_report,core}.py`、
`agent_d/_support.py`、`agent_h/{core,verify_fixes}.py`、`tools/review_tools.py`、
`specs/{b,d}.py`、`schema.py`。

---

## 依据清单

| 依据 | 用途 | 分级 |
|---|---|---|
| `draft/46-施工级调查-07-角色ABCD与H.md` | 主依据：§0 基线、§1…§13 逐文件施工点、§14 可行性/禁改区/可证伪表 | 本文件逐条引用；§14 判定照抄 |
| `draft/46-施工级调查-05-审校签名与状态.md` | `tools/review_tools.py` 侧的唯一依据（§1 R-04 全文、§8.1 依赖顺序、§8.2 五处判定） | 本文件 §12 引用 |
| `draft/44-裁定登记册：全部待裁条目（分6批）.md` §19 | J-01（S-07 改判不可行）、J-02（S-01 收窄+通道已存在）、J-09（不存在逐字判据）、J-10（`payload_keys` 结构性恒空） | 照抄，不重判 |
| `draft/47-子代理报告登记与证据可信度分级.md` | §0 三级标记与两条纪律；§2 承重数字（第 17 组 `statements` 138 / `bits` 0；第 21 组 `review_findings` 13/1771；第 25 组 `analysis_reports` 0）；§4 未复核清单；§5 `46-07 §14` 人裁点 | 引用时必须带分级 |
| `agentflow/AGENTS.md`（FC-27 清单本体） | 判定"哪些文件是禁改区" | 本文件 §汇总的"是否禁改区"一列 |

**分级纪律（照抄 `47 §0` 两条）**：

1. `46-07 §0` 的读数是 `[子代理]` 现算 + 主控抽验（`47 §2` 第 17/21/25 组已标 `[我复核]` 一致）；
   本文件中凡标 `[本次现算 + 命令]` 的，是我在写本文件时用只读脚本重跑得到的。
2. **未被复核的数不许被当成"已核实"引用。** 本文件不做任何新的可行性判定；`46-07 §14` 的
   "低（当前形态不可行）""**不可**（真机不可证伪）"一律按原文照抄。

---

## 口径声明

**两根工作区根**（本文件所有"真机"读数都必须写明是哪一根）：

| 代号 | 路径 | 规模（`46-05 §0` 口径 + 本次现算） |
|---|---|---|
| 根1（= `46-07` 的 "agentflow 根"、`46-05` 的 "根 A"） | `D:\Incubator\agentflow\projects` | 58 子目录；`statements` 138 行；`analysis_reports` 0 行（57 份文件存在） |
| 根2（= `46-07` 的 "Incubator 根"、`46-05` 的 "根 B"） | `D:\Incubator\projects` | 22 个有 `data/` 的工作区；`statements` 0 行；`analysis_reports` 0 行（22 份文件存在） |

**两条前置结论**（引用 `46-07` 所在批次的既定口径，本文件不重开）：

- **不许加必填字段**。加字段一律带默认值；`schema.py` 在 FC-27 清单里（`[category: schema-migration]`
  与 `[category: eval-criteria]` 两处登记），除本文件明确点名的落点外一律不碰。
- **读数口径变更必须写明"从哪一趟起变了"**，落点在 `draft/44`（`draft/45 §3` 第 2 条）。
  本文件 §13 末节把三条必须登记的分界逐字列出。

**复算环境**（每次都要）：

```text
workdir = D:\Incubator\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONPATH="D:\Incubator\agentflow\src"
只读统计：python -B -c "<内联统计>"（遍历两根 data/*.json 与 out/tasks/*.json）
探针：python -B temp\_probe_b_claim.py
```

---

## §0 基线（照 `46-07 §0` + `46-05 §0`，并本次复算）

### 0.1 B 的 `pending` 队列与两处租约不一致（D-2 的现场）

`[46-07 §0①]` 探针 `python -B D:\Incubator\temp\_probe_b_claim.py` 重跑输出：

```text
after run_once #1: failed=1 processed=False claimed_by=None lease_until=None mine_attempts=1
after run_once #2: failed=1 processed=False claimed_by=None mine_attempts=2 last_err='RuntimeError: boom-probe'
after run_once #3: failed=1 processed=False claimed_by=None mine_attempts=3
after run_once #4: failed=0 processed=True skipped_reason='no_claimable_literature' mine_attempts=3
lease still active at this moment: False
```

不一致的**判据面**是 `agent_b/core.py:97`：`if r.get("claimed_by") and not lease_expired(...)` ——
跳过判据**同时要求 `claimed_by` 非空**；而失败分支写的租约恰好是 `claimed_by=None`
（`run_once.py:84-90`）。同族的 `_claim_reprocess()`（`agent_b/core.py:261`）与
`_record_reprocess_failure()` 同一个形状。同一件事在 A 侧的正确实现是
`agent_a/core.py:42-47`（注释逐字写着"若判据额外要求 `claimed_by` 非空，这条租约就写了等于没写"）。

### 0.2 `statements` / `bits`

`[46-07 §0 与 §3]` + `[本次现算 + 命令]`：

```text
D:\Incubator\agentflow\projects  statements 138  bits_nonempty 0  analysis_reports 0  files 57
D:\Incubator\projects            statements 0    bits_nonempty 0  analysis_reports 0  files 22
```

复算命令（只读）：遍历 `<root>/*/data/statements.json` 计行数与 `bool(row.get("bits"))`；
遍历 `<root>/*/data/analysis_reports.json` 计行数。与 `47 §2` 第 17/25 组 `[我复核]` 一致。
`bits` 字段**已存在**（`schema.py` 的 `Statement.bits`，缺省 `field(default_factory=dict)`）⇒ 加参数
是"写一个已有字段"，不是加字段。

### 0.3 C 的产物落点（S-01 的现场）

`[46-07 §0②]` + `[本次现算 + 命令]`（遍历 `<root>/*/out/tasks/*.json`，取 `role=="C"`）：

```text
agentflow: C 产物 37 份；payload_keys 空的 26 份（hottest 11 / gaps 12 / cold 2 / paths 1），
           非空 11 份（contradictions 8 / structural_duplicates 1 / neighbors 1 / relations_between 1）
incubator: C 产物 22 份；payload_keys 空的 21 份（hottest 14 / gaps 7），非空 1 份（contradictions 1）
样本：t-0146.json hottest keys=[] bytes=15271 prevlen=2000；t-0148.json gaps keys=[] bytes=65544 prevlen=2000
```

两根 `analysis_reports` **全 0 行**（文件存在：根1 57 份、根2 22 份）。
`[44 J-10]`：这不是个别现象，而是结构性的（`isinstance(payload, Mapping)` 为假）。

### 0.4 D 的五个核心动作（S-02/S-08/S-09 的现场）

`[46-07 §0③]` + `[本次现算 + 命令]`（遍历 `<root>/*/data/tasks.json`，取 `role=="D"`）：

```text
两根全 0：assess 0 / submit_gaps 0 / adjudicate 0 / trace_question 0 / trace_l3 0
根1 的 D 其余动作（本次现算）：research 70 / run_round 18 / write_report 45 / consider 3 /
    ingest 2 / ingest_detailed 5 / poll 2 / probe_c 1 / propose_question 89 / register_conjecture 122
根2 的 D 其余动作（本次现算）：poll 1 / register_conjecture 191
```

（`46-07 §0③` 给的是 `ok/refused` 拆分口径 `research ok=45/refused=25`、`write_report ok=45`、
`propose_question ok=46/refused=43`、`register_conjecture ok=70/refused=52`；两个口径不冲突 ——
本文件计"行数"，`46-07` 计"状态拆分"。施工时**用本文件的行数做基线**，因为回放只需比行数。）

### 0.5 `review_findings`（R-04-H 的现场）

`[46-05 §0.1]` + `47 §2` 第 21 组 `[我复核]` + `[本次现算 + 命令]`：

| 根 | 总行数 | `kind` | `status` |
|---|---:|---|---|
| 根1 | **13** | `overclaim` 13 | `open` 6 / `fixed` 7 |
| 根2 | **1771** | `scope_drift` 1680 / `dangling_dep` 91 | `fixed` 1706 / `open` 65 |

根1 的 13 行**全部**是语义判据产出（`evidence` 逐字以
`语义判据（judge:claims.conclusion_strength）判定结论强于引文` 开头）；
根2 的 1771 行全部来自旧 `gates` 一族，语义那条 0 行。
**R-04-H 要保护的就是这 13 行**（`46-07 §13` 逐字）。

### 0.6 未闭环检索请求（S-03 的现场）

`[46-07 §0 附加读数]` + `[本次现算 + 命令]`（`done` 不为真且 `outcome` 为 `None`）：

| 根 | 未闭环条数 | `submitted_by` 分布 |
|---|---:|---|
| 根1 | **7** | `agent-D` 3 / `agent-C` 3 / `agent-F` 1 |
| 根2 | **14** | `agent-F` 14 |

这两组数就是 S-03"改后应当归零"的目标读数，也是回放对比的基线。
`conductor.state` 侧的读数落点是 `tools/conductor_tools.py:683-709`
（`_is_open_search` = `r.get("done") is not True`；`unfinished` = 未真行数；
读不出来记 `-1`，**不是 0**）。

### 0.7 一处**本次确认**的行号漂移（施工时必须按本文件的锚点，不按 `46-07` 的）

`[本次确认]`：`46-07 §7` 写 `tools/graph_tools.py:354-358` 是 `RelationGraph.from_store(cls, store, *, service=False)`，
**现状不是**。实测：

```text
tools/graph_tools.py:266  class RelationGraph:
tools/graph_tools.py:347  def from_store(cls, store: Any) -> "RelationGraph":
tools/graph_tools.py:357      literatures=list(store.rows("literature")),   # 注意：literatures，不是 literature
```

即：`service` 形参已消失，第 357 行的关键字是 `literatures`。`46-07 §7` 的**结论**
（"本文件不需要改"）不变；变的是行号。施工时以 `:347-358` 为准。

---

## §1 `src/agentflow/agent_b/core.py` —— D-2 的判据面

### 块 1.1 `_claim` 的跳过判据改为"只看租约是否有效"（含新增退避分档）

- **改什么**：`AgentB._claim()` 的跳过判据从"`claimed_by` 非空且租约未过期"改为"租约未过期"这**唯一**判据；
  把自己的退避租约（`claimed_by=None` + `lease_until` 在未来）单独计数、单独给 `skipped_reason`；
  `_claim_reprocess()`（`:261`）同一改法。**不改盘上任何字段**。
- **怎么改**：接口级，锚点 `[46-07 §1]` 给出，本次逐行确认。

  ```python
  # agent_b/core.py:96-99（现状，逐字）
  for r in cands:
      if r.get("claimed_by") and not lease_expired(r.get("lease_until")):
          skipped_lease_active += 1
          continue  # 别人正拿着有效租约
  # agent_b/core.py:111-114（现状，逐字）
  r["claimed_by"] = self.actor
  r["lease_until"] = make_lease(self.lease_seconds)
  r["mine_attempts"] = n + 1
  tx.upsert("literature", r, note="claimed")
  # agent_b/core.py:260-262（同族，现状，逐字）—— `_claim_reprocess`
  for row in cands:
      if row.get("claimed_by") and not lease_expired(row.get("lease_until")):
          continue  # 别人正拿着有效租约
  ```

  伪码（照 `46-07 §1` 的伪码 + `agent_a/core.py:592-610` 的写法）：

  ```text
  _claim():
      新增计数器 skipped_lease_backoff = 0
      for r in cands:
          if not lease_expired(r.get("lease_until")):           # 唯一判据（:97 去掉 claimed_by 那一半）
              if r.get("claimed_by"):
                  skipped_lease_active += 1                     # 别人持着
              else:
                  skipped_lease_backoff += 1                    # 自己的退避租约（新增）
              continue
          ...（:100-114 不变：attempts 判超、取到活时置 claimed_by / lease_until / mine_attempts）
      四种 skipped_reason：新增 "pending_literature_all_in_backoff"
          （pending==0 → no_unprocessed_literature；
            active==pending → pending_literature_all_leased；
            backoff==pending → pending_literature_all_in_backoff（新）；
            否则 → no_claimable_literature）
      _claim_reprocess(): 同一改法，另加自己的 skipped_reason 分档
      BClaimOutcome: 新增字段 skipped_lease_backoff（dataclass 在 agent_b/_support.py:130）
      BRunResult: 新增字段 skipped_lease_backoff（dataclass 在 agent_b/_support.py:111 附近）
  ```

  已知锚点（本次确认，逐条）：`agent_b/core.py:96-99`（跳过判据）、`:111-114`（取活写入）、
  `:213-216`（四种 `skipped_reason` 的计算，`46-07 §1` 第 5 条提到的 `_claim` 约 8 行改动面即此）、
  `:260-262`（`_claim_reprocess` 同族）、`:48-49`（`lease_seconds` 缺省 900 / `max_attempts` 缺省 3，
  **禁改**）；`agent_b/_support.py:111`（`BRunResult.skipped_lease_active`）、`:130`（`class BClaimOutcome`）、
  `:157-161`（`BClaimOutcome.skipped_lease_active` / `gave_up` / `skipped_reason`）。
- **改的依据**：`draft/46-07 §1` 第 1/2/5 条；`draft/44 §19` 无对应编号（D-2 不在 §19 的 10 条改判里，
  它是 `46-07 §1` 的原判定）；关键证据 `agent_b/core.py:97` vs `run_once.py:84-90` 的写入形状不一致；
  对照实现 `agent_a/core.py:42-47`（"判据额外要求 `claimed_by` 非空 ⇒ 租约写了等于没写"逐字）；
  `agent_a/core.py:592-610`（8b 段自检，**这段是本条要照搬的判据形态**）。
- **怎么算过**：
  - **负控（改前必红）**：新建 `tests/test_agent_b_backoff.py`。照 `46-07 §1` 第 6 条两条分开数：
    ①造"别人持着"（`claimed_by="agent-B-other"` + 未来 `lease_until`）⇒ 断言
    `skipped_lease_active == 1 and skipped_lease_backoff == 0`；②造"自己的退避租约"
    （`claimed_by=None` + 未来 `lease_until`）⇒ 断言 `skipped_lease_backoff == 1 and request is None`；
    ③退避过期（过去 `lease_until`）⇒ 断言**领得到**且 `mine_attempts` 增 1。改前 ②③ 必红（② 现在会被领到）。
  - **既有判据会红（必须同批改写）**：`tests/test_agent_b.py:182`
    断言原文 `assert row["claimed_by"] is None and row["lease_until"] is None, "必须释放租约以便重试"`
    —— §2 的改动会让 `lease_until` 非空 ⇒ **必须先跑、必须红**，然后改成
    `assert row["claimed_by"] is None and row["lease_until"] is not None`；
    `tests/test_agent_b.py:183` 的 `assert row["mine_attempts"] == 1` 保持（退避后重领不该让 attempts 跳档）。
  - **会红的既有判据（不该红 ⇒ 回归）**：`tests/test_core_audit_abc_cli.py:561/566/589`
    （`_add_leased_literature` 造 `claimed_by="agent-B-other"` / `mine_attempts=3` 两档）必须仍绿 ——
    这两档在改动前后分档不变。
  - **快照/文档/计数同步**：`BClaimOutcome` / `BRunResult` 各 +1 字段 ⇒ 若有 `.to_dict()` 快照
    （`BRunResult.to_dict()` 进 `res.task` 一类的落点）要重冻；`skipped_reason` 新增取值只在返回值里，**不进表**。
  - **真机回放**：`p5-review-t14` 一类有 `last_mine_error="no_llm_extractor"` 的工作区重跑 `B.run_once`，
    确认它不再立刻重领（`mine_attempts` 不增）。
  - **全量门**：`python -B -m pytest -q -p no:randomly` + `python -B scripts/lint_rules.py`
    （基线 0 错 / 9 警 / 49 提示；`--strict` 0/58/48）。
- **不许这么改 / 边界**：不动 `lease_seconds` / `max_attempts` 缺省值（`46-07 §1` 第 7 条）；
  不给 `literature` 加"退避次数"字段（`schema.py` 禁改区）；**不把 `_claim` 与 `_claim_reprocess`
  合成一个函数**（两者准入判据不同，合并等于给重抽取加四条无关判据）；不动 `_is_fallback_extractor`。
- **依赖与批次**：与 §2 同批（同一机制的一半），**§2 必须先落**（没有写入面的退避租约，§1 的负控 ② 无法构造出
  "自己的退避租约"这一档）。与 EE-12（§3）不同批（两文件、两机制，虽可并行但不共享判据）。

---

## §2 `src/agentflow/agent_b/run_once.py` —— D-2 的写入面（三个失败分支）

### 块 2.1 三个失败分支至少两支改写短退避租约

- **改什么**：`run_once()` 里的"释放租约"分支，把 `row["lease_until"] = None` 改成
  `make_lease(self.retry_backoff_seconds)`；`__init__` 新增 `retry_backoff_seconds` 配置。**不改字段集**。
- **怎么改**：接口级，锚点 `[46-07 §2]` 给出，本次逐行确认。

  ```python
  # agent_b/run_once.py:83-93（现状，逐字；抽取失败分支）
  except Exception as e:
      # 抽取失败：不置 processed，让租约过期后重试
      with self.store.tx("literature", actor=self.actor, note="extract_failed") as tx:
          row = tx.find("literature", lit_id=lit_id) or lit
          row["claimed_by"] = None
          row["lease_until"] = None
          row["last_mine_error"] = f"{type(e).__name__}: {e}"
          tx.upsert("literature", row, note="extract_failed")
  # 同族的另两支（本次确认）：
  #   :48-59  不可读：已置 processed=True（:51）⇒ 不再会被领到，**不需要**退避
  #   :64-76  回退抽取器拒抽：刻意不置 processed（:70 的注释逐字）⇒ 唯一会被无限重领的一支
  ```

  伪码（照 `46-07 §2` 的伪码；`get(..., 60)` 而非 `or 60`，与 `agent_a/core.py:45-47` 同口径）：

  ```text
  __init__: self.retry_backoff_seconds = int(self.cfg.get("retry_backoff_seconds", 60))
  :84-90（抽取失败）: row["lease_until"] = make_lease(self.retry_backoff_seconds)   # 唯一改动
  :65-71（no_llm_extractor）: row["lease_until"] = make_lease(self.retry_backoff_seconds)  # 必改
  :49-55（不可读）: 不改（它已置 processed=True）
  :303-309（成功路径）: 继续清空租约（既有行为，不作改动）
  ```

  已知锚点（本次确认）：`run_once.py:84-90`（抽取失败分支）、`:48-59`（不可读）、`:64-76`（拒抽）、
  `:303-309`（成功路径，`46-07 §2` 第 2 条点名保留）。
- **改的依据**：`draft/46-07 §2` 第 1/2/5/6 条；`draft/44 §19` 无对应编号（同 §1）；
  关键证据 `run_once.py:88` 与 `agent_a/run_once.py:205` / `:216` 的对比（A 写的是
  `retry_backoff_seconds`，B 写 `None`）；`agent_b/core.py:43-44` 的注释逐字说明
  `no_llm_extractor` 这一支"刻意不置 processed ⇒ 接线 LLM 之后那一轮还会重新领到这些行"
  —— 它就是无限重领的来源。
- **怎么算过**：
  - **负控（改前必红）**：三条，写进 §1 的新测试文件（同批）：
    ①抽异常 ⇒ 写退避 + 再领领不到 + `mine_attempts` 不增；
    ②`no_llm_extractor` ⇒ 同上；
    ③退避秒数置 0 ⇒ **立刻可重领**（三态：0 是合法配置而不是"没配"，照 `agent_a/core.py:45-47`；
    这条正控防"改成退避后 B 真的卡住 900 秒"）。
  - **会红的既有判据（必须同批改写）**：`tests/test_agent_b.py:182`
    （逐字见 §1 块 1.1）—— **必须先跑、必须红**；
    `tests/test_agent_b.py:163` 的 `assert rows["0000"]["claimed_by"] is None`（不可读支）**不许红**
    （该支不动）。
  - **快照/文档/计数同步**：`retry_backoff_seconds` 是新的构造期配置键 ⇒ 若 `config` 有一份
    逐键清单（提示词面或 `host.py` 的装配置），要同步登记；`lint_rules.py` 的 R011（受控词表死取值）
    不涉及（没有新词表）。
  - **真机回放**：`p2-review` 快照（`last_mine_error` 分布最全）跑一次 `B.run()`，
    确认 `processed` 行数不变、`mine_attempts` 不再跳档。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改概念/关系/引文回验主链路（`run_once.py:95-301`）；
  **不改"不可读 ⇒ 置 processed"的处置**（刻意设计，避免永远堵队首）；
  不给 `BRunResult` 加"新计数以外的字段"；不动 `R-56` 拒抽判据（`:64` 的 `extractor_is_fallback`）。
- **依赖与批次**：**必须与 §1 同批，且本块先落**（先有写入面，`_claim` 的退避分档才有可测的输入）。
  与 §3 不同批。

---

## §3 `src/agentflow/agent_b/register_statement.py` —— EE-12 / EE-07

### 块 3.1 EE-12：补 `bits=` 参数并写入已有字段

- **改什么**：`register_statement` 的参数表新增与 `evidencebits.bits_of` 同名的可选位参数；
  构造 `S.Statement` 时传 `bits=bits`；写入前用 `bits_shape_problems` 预检。
- **怎么改**：接口级。

  ```python
  # agent_b/register_statement.py:69-86（现状参数表，逐字；注意：没有 bits 参数）
  def register_statement(self, *, statement_full: str, source_lit_id: str = "",
      proof_text: str = "", kind: str = "theorem", label: str = "",
      statement_text: str = "", origin: str = "external_lit",
      page_range: dict | None = None, evidence_kind: str = "cross_check",
      quote_verified: bool | None = None, quote_reason: str = "",
      derived_from: list | None = None, doc_id: str = "", line_range: dict | None = None) -> dict:
  # agent_b/register_statement.py:180-193（现状构造，逐字；注意：没有 bits=）
  row = S.Statement(
      stmt_id=stmt_id, origin=origin, kind=str(kind or "theorem"), label=str(label or ""),
      statement_text=str(statement_text or ""), statement_full=full,
      proof_text=str(proof_text or ""), source_lit_id=lit_id or None,
      page_range=S.PageRange.from_dict(page_range), quote_verified=quote_verified, ...
  ```

  伪码（照 `46-07 §3` 的伪码）：

  ```text
  新增参数（都可省略，带默认值）：
      numeric / numeric_evidence / proof / proof_process / reviewed / reviewed_by /
      formal / formal_evidence / audited / audited_by        # 与 evidencebits.bits_of 的形参同名
  构造：
      bits = EB.bits_of(origin=origin, source_lit_id=lit_id, quote_verified=quote_verified,
                        numeric=..., proof=..., reviewed=..., formal=..., audited=..., ...)
      row = S.Statement(..., bits=bits, ...)
  写入前：problems = EB.bits_shape_problems(bits) ⇒ 有问题就 refuse("bad_bits", ...)（照 :98-101 的形状）
  向后兼容：调用方一个位都不给 ⇒ bits 传 {}（不得写非空 bits）
  ```

  已知锚点（本次确认）：`register_statement.py:69-86`（参数表）、`:180-193`（构造）、
  `evidencebits.py:64`（`def bits_of(*, numeric..., ...)`）、`evidencebits.py:157`
  （`def bits_shape_problems(raw)`）、`evidencebits.py:186`（`def derive_grade(bits)`）、
  `schema.py` 的 `Statement.bits`（缺省 `dict`）。
- **改的依据**：`draft/46-07 §3` 第 1/2/4/5 条；`draft/44 §19` 无对应编号（EE-12 是 `46-07 §3` 原判定）；
  关键证据 `schema.py` 里 `evidence_kind` 的注释逐字声明它是"派生只读视图"、真正判等级的是 `bits`；
  `46-07 §0` / `[本次现算]`：`statements` 138 行里 `bits` 有值 **0 行**。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_intake_actions.py`（14 处 `register_statement`）里新增一例：
    传 `proof=True` + `formal=True` ⇒ 断言落库行的 `bits["proof"] is True`。改前该断言必红
    （`bits` 恒 `{}`）。**必须先跑、必须红。**
  - **真机回放（EE-12 的判据）**：比 `statements.bits` **首次非 0**。基线 `[本次现算]`：
    根1 138 行 / `bits` 非空 **0**；根2 0 行。选根1 里 `statements` 最多的工作区
    （`46-07 §3` 第 6 条点名 `p2-review`）跑一条带位参数的动作，确认 `bits` 非空行数从 0 变正。
  - **会红的既有判据**：`tests/test_intake_actions.py` 的既有 14 例必须仍绿（全都不传位参数 ⇒
    `bits={}` ⇒ 读数不变）；`tests/test_evidence_bits.py` 与 `tests/test_verifier_role.py:121`
    只测 `bits_of` 本身，不改它们。
  - **快照/文档/计数同步**：`specs/b.py` 的参数表要加这些参数名（**FC-27 禁改区，见下**）⇒
    `tests/test_agent_spec_reconciliation.py` 的参数覆盖读数（`46-03 §0` 的 177/177）与
    `tests/golden/agent_surface_snapshot.json` 要重冻。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改 `schema.py`（`Statement.bits` 与 `evidence_kind` 的字段定义、
  `SCHEMA_VERSION`）；不改 `closing.py` 第④条（E-05 读数口径，另一批）；不改 `claimanatomy` 的交叉门；
  **不**顺手把 `documents[].claims` 的 `status`/`allowed_use` 一起填（那是 EE-06，`schema` 禁改区、另一条产线）。
  **禁改区**：`src/agentflow/specs/b.py` 在 FC-27 清单里（`[category: auth-audit]`，理由串逐字：
  "改这里等于改权限面本身"）⇒ **需 2 名人审**。
- **依赖与批次**：EE-12 先落（`46-07 §3` 第 2 条的伪码顺序）；EE-07（块 3.2）**紧随其后同批**，
  因为 EE-07 的派生函数与 EE-12 的位写入共用同一个 `bits` 值。与 D-2（§1/§2）不同批。

### 块 3.2 EE-07：`evidence_kind` 由 `bits` 派生（新增纯函数）

- **改什么**：新增 `evidencebits.derive_evidence_kind(bits)`（5–10 行映射），
  `register_statement` 里 `evidence_kind` 从手填改为派生。**这是读数口径变更**。
- **怎么改**：接口级。

  ```python
  # agent_b/register_statement.py:97-101（现状，逐字：手填 + 校验）
  evidence_kind = str(evidence_kind or "heuristic")
  if evidence_kind not in S.EVIDENCE_KINDS:
      return _refuse("bad_evidence_kind",
                     f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}"
                     "（它是证据**强度**，不是来源；来源走 source_lit_id）")
  ```

  伪码（照 `46-07 §3`）：

  ```text
  evidencebits.py 新增：derive_evidence_kind(bits) -> str
      GRADES（evidencebits.py:35，4 档）× EVIDENCE_KINDS（schema.py:876，3 值）的映射
  register_statement：
      evidence_kind = EB.derive_evidence_kind(bits)
      （`:97-101` 的校验保留为兜底：派生结果不在词表里 ⇒ 同一条 refuse）
  quote_verified 的分寸（`46-07 §3` 第 6 条风险二）：
      bits_of:80-84 的 cited 分支把第 2、3 位置真 ⇒ `quote_verified is True` 会抬到 proof 位。
      而 `quote_verified` 只证明"这句话在文件里"（agent_b/core.py:39-43 的原文）⇒
      映射里**要么只取 cross_check，要么把 cited 分支封在 cross_check**。这一档必须显式定。
  ```

  已知锚点（本次确认）：`register_statement.py:97-101`（手填与校验）、`:180-193`（构造，见块 3.1）；
  `evidencebits.py:35`（`GRADES`）、`:64`（`bits_of`）、`:157`（`bits_shape_problems`）、
  `:186`（`derive_grade`）；`schema.py:876`（`EVIDENCE_KINDS = ("proof","cross_check","heuristic")`）。
  **`derive_evidence_kind` 现在不存在**（`grep '^def ' evidencebits.py` 只有 13 个函数，无此名）⇒ 本块是**新写**。
- **改的依据**：`draft/46-07 §3` 第 4/5/6 条；`draft/44 §19` 无对应编号；
  关键证据 `schema.py:1604` 附近逐字声明 `evidence_kind` 是"复用 `EVIDENCE_KINDS`"的**派生视图**；
  三条读它的路径各说各话（`evidencebits.derive_grade` 读 `bits`、`claimanatomy.status_evidence_consistency`
  读 `status`×`evidence_kind`、`closing.py:1438` 第④条读 `evidence_kind`）。
- **怎么算过**：
  - **负控（改前必红）**：`46-07 §3` 第 6 条两条必须都能红：
    ①`bits.proof=True` + `status="证"` ⇒ 两侧一致；②`bits` 全空 + `status="证"` ⇒ 报不一致。
    第 ① 条依赖块 3.1 的位写入（`bits` 恒 `{}` 时它必然红）。
  - **真机回放（EE-07 的判据）**：`46-07 §3` 第 6 条 —— 在 `p2-review`（`statements` 最多的工作区）
    **逐行比对改前/改后的 `evidence_kind` 与现算 `grade`**，确认"变了的正是该变的"；
    旧行 `bits={}` 一律按"五位全空"读（`evidencebits.bits_from_row`）⇒ **旧行等级仍是"猜想"**。
    预期：`origin=external_lit` 且 `quote_verified=True` 的行会得 `proof`
    （`bits_of:80-84` 的 cited 分支）⇒ **根1 现有 `proof` 6 行之外的行读数会变**，这是口径变更不是 bug。
  - **会红的既有判据**：`tests/test_evidence_bits.py` 里凡断言"`evidence_kind` 缺省 `cross_check`"的一类，
    在派生口径下会红 ⇒ 逐条改成"由 `bits` 现算"。
  - **快照/文档/计数同步**：`draft/44` 必须登记三条分界中的第②条（见 §13）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改 `schema.py` 的 `EVIDENCE_KINDS` / `Statement.evidence_kind` 定义；
  不改 `claimanatomy` 的交叉门；**不扩大 `EVIDENCE_KINDS` 词表**（它是 FC-27 的 eval-criteria 面）。
  **禁改区**：`specs/b.py`（同块 3.1）。
- **依赖与批次**：**必须在块 3.1 之后**（没有 `bits` 就没有可派生的输入）；两者同批。

---

## §4 `src/agentflow/agent_c/_support.py` —— S-01 的落盘机制

### 块 4.1 新增 `AgentC._finish_report`，把 `persist()` 从"调用方负责"变成"收口负责"

- **改什么**：不改 `AnalysisReport.persist()`（它是唯一写入口，位置与顺序已经对）；
  新增 `_finish_report(rep)` 统一收口（`ok` 且 `kind ∈ REPORT_KINDS` 且 markdown 非空才落），
  失败**不抛给调用方**（记进 `rep.warnings`，保留 `ok=False` + `error`）。
- **怎么改**：接口级。

  ```python
  # agent_c/_support.py:300-306（现状，逐字；这是唯一的写入口体内）
  who = actor or self.created_by or "agent-C"
  out_dir = Path(reports_dir) if reports_dir else (Path(st.root) / "reports")
  with st.tx("analysis_reports", actor=who, note=f"analysis_report:{self.kind}") as tx:
      rid = tx.alloc_id("report")
      rel_name = f"reports/{rid}-{self.kind}.md"
      abs_path = out_dir / f"{rid}-{self.kind}.md"
      _atomic_write_text(abs_path, self.markdown)
  ```

  伪码（照 `46-07 §4`）：

  ```text
  persist(): 保持不变（四道硬校验：kind ∈ REPORT_KINDS（:284）、markdown 非空（:289）、
             summary 非空（:291）、payload 可 JSON 序列化（:293-298）；顺序理由见 :263-272）
  新增：AnalysisReport.to_task_payload() -> dict      # 供 conductor 的摘要用（§8）：返回 to_dict() 并保证可 json.dumps
  新增：AgentC._finish_report(rep) -> AnalysisReport  # 统一收口
          if rep.ok and rep.kind in S.REPORT_KINDS and rep.markdown.strip():
              try: rep.persist()
              except Exception as e: rep.ok = False; rep.error = ...; rep.warnings.append(...)
          return rep
  ```

  已知锚点（本次确认）：`agent_c/_support.py:204-252`（`AnalysisReport` dataclass，注意它**已经**有
  `report_id` / `markdown_path` 字段 `:226-227`）、`:256-324`（`persist()` 全body，含
  `:300-306` 的写文件段与 `:307-319` 的登记行段）、`:284`（kind 校验）、
  `agent_c/__init__.py:53`（`persist()` 在包 docstring 里被点名；**真身在 `_support.py:256`**）。
- **改的依据**：`draft/46-07 §4` 第 1/2/4/5/6 条；`draft/44 §19 J-02`（"C **已有 `persist()`**
  （`agent_c/__init__.py:53`、`__main__.py:381-398`），缺的是**在 conductor 路径上调用**"）；
  关键证据：两根 `analysis_reports` **0 行**（文件存在：根1 57 份、根2 22 份）。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_agent_c_service.py:641`，断言原文逐字：
    `assert kn.rows("analysis_reports") == [], "gaps 不落报告表（要落盘必须显式 persist）"`
    —— **必须先跑、必须红**，然后按新语义反向（落盘后应为非空）。
    另一条 `tests/test_agent_c.py:522`：断言原文 `assert demo.rows("analysis_reports") == []`
    （在 `test_persist_rejects_kind_outside_the_controlled_vocabulary` 内，`AnalysisReport(kind="unknown"...)`
    与两个非法 markdown/summary 各一次）—— **必须先跑、必须红**；
    改后它必须**仍绿**（三条非法路径都不该落盘），所以这一条的期望**不改**，改的是它前面的前提。
    `[44 J-02]` 逐字要求"**必须改写那两条反判据**"，不许靠删测试绕过。
  - **真机回放（S-01 的判据①）**：比 `analysis_reports` **首次非 0**。基线：两根 0 行。
    选 `p6j-research-from-zero`（C 被召唤最多）跑一次 `C.gaps`，确认表里首次非 0 且
    `reports/<rid>-gaps.md` 存在。
  - **会红的既有判据（必须同批改写）**：`tests/test_core_audit_abc_cli.py:793`
    断言原文 `assert len(st.rows("analysis_reports")) == 3, "它自己的产出（analysis_reports）应当照常登记"`
    —— 该用例显式调三次 `.persist()`（`:783-785`）⇒ 自动落盘后 3 个动作会各再落一次 ⇒ 计数变。
    `tests/test_core_audit_abc_cli.py:425` 的 `assert st.rows("analysis_reports") == []`
    （`kind="unknown"` 不落盘）**不许红**（那是 persist 的硬规则，不动）。
  - **快照/文档/计数同步**：`reports/` 目录会新增 markdown 文件；`closing.py` 的
    `analysis_report_rows` 档会第一次有读数 ⇒ 见 §13 分界①。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改 `S.REPORT_KINDS`（`schema.py:442`，禁改区）⇒
  **`contradictions`/`neighbors`/`relations_between`/`structural_duplicates`/`handle`
  这五个动作仍然不能落盘**（`46-07 §4` 第 7 条）；不删 `pipeline._persist_report`（L-03 是另一条）；
  不改 `persist()` 的校验。
- **依赖与批次**：S-01 的四个半边（§4/§5/§6/§8）**同批**；本块先落（其余三块都依赖
  `_finish_report` 存在）。与 §7（`graph_tools.py`）**不同批且不该改**。

---

## §5 `src/agentflow/agent_c/{hottest,gaps,cold,paths}.py`（文件组，同一改动） —— S-01 的返回值形状

### 块 5.1 在 `_report()` 一处收口，四个动作文件 0 行改动

- **改什么**：`AgentC._report()` 末尾按开关调 `_finish_report`。**不改四个动作的签名**。
- **怎么改**：接口级。

  ```python
  # agent_c/core.py:89-103（现状，逐字；唯一的收口点）
  rep = AnalysisReport(
      kind=kind, request=request, params=dict(params), summary=summary,
      payload=dict(payload), markdown=markdown, warnings=list(warnings),
      truncated=bool(truncated), ok=ok_, error=error, created_by=self.actor,
  )
  rep._store = self.store  # type: ignore[attr-defined]  让 report.persist() 免参数可用
  return rep
  # agent_c/hottest.py:108-116（四个动作同形；本次确认，与 46-07 §5 逐字一致）
  return self._report(
      "hottest", request, {"top_n": top_n},
      summary=f"最热门的 {len(entries)} 个概念：" + "、".join(...),
      payload=payload, markdown="\n".join(md) + "\n", warnings=warnings,
  )
  ```

  伪码（照 `46-07 §5`）：

  ```text
  _report(...) -> AnalysisReport:
      rep = AnalysisReport(...)                    # 不动
      rep._store = self.store                      # 不动
      if self.auto_persist:                        # 新增开关
          rep = self._finish_report(rep)           # §4：ok 且 kind ∈ REPORT_KINDS 才落
      return rep
  四个动作文件本身 0 行改动
  ```

  **真正的难点（`46-07 §5` 第 5 条逐字）**：`auto_persist` 缺省 False 时真机不会落盘
  （真机调用方是 conductor，它不会传这个开关）。两条合规路线：
  ①缺省 True（则 `test_agent_c_service.py:641` 与 `test_agent_c.py:522` 必改）；
  ②在 `host.py` / `specs/c.py` 的构造配置里打开（`_config_for(role)` 一类），**后者不碰禁改区**。
  **施工时选 ②**（理由：`specs/c.py` 是禁改区、`host.py` 不是；且 ① 会让 CLI 直调也落盘，
  与 `pipeline` 的旧路径重复）。
- **改的依据**：`draft/46-07 §5` 第 1/2/5/6 条；`draft/44 §19 J-02`（落盘只能覆盖 4 个 kind）；
  `draft/44 §19 J-10`（`payload_keys` 恒空是结构性的）；关键证据 `[本次现算]`：
  `hottest.py:108-116` 返回 dataclass ⇒ `isinstance(payload, Mapping)` 为假 ⇒ `payload_keys=[]`。
- **怎么算过**：
  - **负控（改前必红）**：①`ok=False`（关系表为空，`hottest.py:37-50`）⇒ 落盘与否必须**显式定档**
    （`46-07 §5` 第 6 条建议**落**：它带完整 markdown 与 `error`，是"这次没能给出结论"的证据）；
    ②`handle` 的 `kind="unknown"` ⇒ **绝不落**（`persist` 会抛，`_finish_report` 接住）；
    ③`submit_requests=True` 的 `gaps` ⇒ 落盘 + 写 `search_requests` **两件事都要在返回值里可见**。
  - **真机回放**：`p2-review` 的两次 `gaps`（`t-0203.json`，65544 字节）改后应各产生一行
    `analysis_reports` 与一份 markdown。
  - **会红的既有判据**：同块 4.1（`:641` / `:522` / `:793`）；另
    `tests/test_agent_c.py:485-503`（`test_persist_writes_markdown_file_and_registers_report_row`）
    显式调 `.persist()` ⇒ 若同时开了自动落盘，`len(rows) == 1` 这条会变 ⇒ 该用例要么显式关自动落盘，
    要么改成"文件 + 行数按落盘次数计"。**不许删它**。
  - **快照/文档/计数同步**：见 §6 的 `returns` 串与快照重冻。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改四个动作的参数表（`specs/c.py` 禁改区）；
  **不把 dataclass 直接写进 `analysis_reports`**（表里的行必须是 `schema.AnalysisReport`，
  两回事，见 `_support.py:206-211` 的 docstring）；不做"落盘后回读再返回"
  （会让 D 读到上一次的快照，语义漂移）。
- **依赖与批次**：**必须在 §4 之后**（依赖 `_finish_report`）；与 §6、§8 同批。

---

## §6 `src/agentflow/agent_c/core.py` —— S-01 的工具面与 I3 写入面

### 块 6.1 工具面**不动**；只把"这次落过盘"暴露进返回值

- **改什么**：9 个动作的 `side_effect="read"` / `roles=("C","D")` **一个字不改**；
  只把 persist 后的 `report_id` / `markdown_path` 从 `to_dict()` 里如实露出（非持久字段，形状是增量）。
- **怎么改**：接口级。

  ```python
  # agent_c/core.py:953-958（现状，逐字）
  def _register(name: str, summary: str, params: dict, fn: Any, returns: str) -> None:
      if name in registry:
          return
      wrapped = tool(name, summary, params, side_effect="read", roles=("C", "D"), returns=returns)(fn)
      registry.register_function(wrapped)
      added.append(name)
  # agent_c/core.py:969（现状，逐字）
  lambda top_n=5: self.hottest(int(top_n)).to_dict(),
  ```

  伪码（照 `46-07 §6`）：

  ```text
  工具面不动（side_effect="read" 是正确声明，理由见 capabilities.py:1086-1099 —— 改它会
    让 ToolRegistry.for_role 把 graph.gaps 从 C 的工具面里滤掉，是"照字面修反而更坏"）
  落盘发生在方法层（§5），不在工具面；工具面返回的仍是 rep.to_dict()（形状不变）
  唯一需要动的是把"这次调用落过盘"暴露出来：
      rep.to_dict() 增加 "report_id" / "markdown_path"（persist 后回填）
  ```

  已知锚点（本次确认）：`agent_c/core.py:953-958`（`_register` 的唯一一处 `tool(...)` 调用）、
  `:969`（`graph.hottest` 的 lambda）、`:916-1129`（`register_tools` 全体，9 个动作）、
  `:1019-1023`（`graph.gaps` 刻意不暴露 `submit_requests`）、`:541-698`（`_submit_gap_requests`，
  C 唯一的确定性写入路径）。
- **改的依据**：`draft/46-07 §6` 第 1/2/5/6 条；`draft/44 §19 J-02`；
  关键证据 `capabilities.py:1137` 已登记 `WRITE_SETS["C"] = {"analysis_reports","search_requests"}`
  于 `READ_ONLY_WRITE_EXCEPTIONS` ⇒ **权限面不需要动**（`assert_capabilities` 的 [6] 条先减已登记例外再判）。
- **怎么算过**：
  - **负控（改前必红）**：①`graph.gaps` 的 `side_effect` **仍是 `read`**
    （防有人图省事改成 `write_local`，那会砍掉 C 的工具面）—— 直接断言 `describe()` 里的取值；
    ②`graph.gaps` 的返回值里**不得**出现 `submit_requests`（防 I3 后门）。
    这两条在改动前就应当绿（它们是**防回退**判据，不是"改前必红"）；本块的"改前必红"是
    块 4.1/5.1 那两条反判据。
  - **真机回放**：跑一次 `python -B -c "import agentflow.capabilities as C; C.assert_capabilities()"`，
    确认导入期断言读数不变（`46-03 §0` 的 177/177 与类型对账 80 对 / 64 工具）。
  - **会红的既有判据（若改 `returns` 串）**：`tests/test_tool_surface_snapshot.py` +
    `tests/golden/tool_surface_snapshot.json`（`returns` 串逐字钉在快照里）⇒ **改 `returns` 必须重冻**；
    同时跑 `tests/test_agent_spec_reconciliation.py`（两层动作表对账）。
  - **快照/文档/计数同步**：`tests/test_capabilities.py` / `test_capabilities_two_layer.py`
    两层动作表必须仍对得上（9 个动作名与 `specs/c.py` 逐个对齐，**不改名**）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改 `graph.*` 的名字与参数（改名要动禁改区 `specs/c.py`）；
  不给 `graph.gaps` 加 `submit_requests`；不把 `_submit_gap_requests` 的闸门挪到工具层
  （理由在 `:566-569`）；不做 C 的"自动消费检索请求"（那是 §9）。
- **依赖与批次**：与 §4/§5/§8 同批；**必须在 §5 之后**（先有落盘，才有 `report_id` 可露）。

---

## §7 `src/agentflow/tools/graph_tools.py` —— 低层图查询（S-01 的邻居面）

### 块 7.1 本文件**不需要改**（写进方案是为了钉住"不许在这里落盘"）

- **改什么**：**不改**（改动量 0）。写进本方案的理由：S-01 的"或等价落点"若被理解为
  "在 `graph_tools` 里落盘"，那是**错的落点**。
- **怎么改**：接口级 —— 现状原文（**本次确认，锚点与 `46-07 §7` 不同，见 §0.7**）：

  ```python
  # tools/graph_tools.py:347-358（现状，逐字；46-07 §7 写的是 :354-358 且含 service= 形参 —— 已漂移）
  def from_store(cls, store: Any) -> "RelationGraph":
      ...
      return cls(
          concepts=list(store.rows("concepts")),
          relations=list(store.rows("relations")),
          literatures=list(store.rows("literature")),
      )
  ```

  伪码：**无**。原因（照 `46-07 §7` 逐字）：这里没有 `store.tx`、也没有角色身份
  （`roles=("C","D")` 两个角色共用），落盘会失去"谁产的"这一栏。
- **改的依据**：`draft/46-07 §7` 第 1/2/5/6 条；关键证据：它全 `read`、无 `store.tx`、无文件写；
  真机 `graph` 族工具 **0 次调用**（43-F 记，48 件零调用工具里的一部分）。
- **怎么算过**：
  - **负控（防回退）**：断言 `tools/graph_tools.py` 源码里仍然**没有** `store.tx(` 与文件写
    （现有测试与 lint 已覆盖一部分）。这条改动前后都应绿。
  - **不会红的既有判据**：`tests/test_graph_tools.py` 一类必须**全程绿**（本块 0 行改动）。
  - **真机回放**：不适用。
  - **全量门**：同 §1（本块不产生代码 diff，门只是复核"什么都没变"）。
- **不许这么改 / 边界**：不改 `RelationGraph` 的读法（它是 `_support.py` 与 `core.py` 共用的图本体）；
  不给它加 `side_effect="write_local"`（那会撞 `tools/__init__.py` 的 `READ_ONLY_ROLES`、
  `tools/base.py` 的 `_role_surface` 三处判据 —— 三处都在 FC-27 的 auth-audit 面）；
  不把 `analysis_reports` 的写入口放到工具层。
- **依赖与批次**：**与 S-01 的其它四块同批（作为"不改"的显式条目）**，但**不许与它们合并改动面**；
  与任何条目都无先后。

---

## §8 `src/agentflow/conductor.py` —— S-01 的摘要截断那一半

### 块 8.1 新增 `_payload_view(payload)`，让 dataclass 返回值也能有键集

- **改什么**：新增一个私有"投影"函数（先 `to_dict()` 再算键集），`conductor._write_task_digest`
  与 `tools/conductor_tools._summon_view` **共用它**（防两份口径分家）。
- **怎么改**：接口级。

  ```python
  # conductor.py:1200-1214（现状，逐字）
  blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
  doc = {
      ...
      "payload_keys": sorted(str(k) for k in payload) if isinstance(payload, Mapping) else [],
      "payload_preview": blob[:2000],
  }
  # conductor.py:1159（现状，逐字：非 Mapping 的返回值原样进 _end）
  return self._end(tid, status="done", outcome="ok", detail="执行完成", payload=raw)
  ```

  伪码（照 `46-07 §8`）：

  ```text
  新增 _payload_view(payload) -> tuple[dict, dict]        # 唯一口径，conductor 与 conductor_tools 共用
      if hasattr(payload, "to_dict") and callable(payload.to_dict):
          payload = payload.to_dict()                     # dataclass（C 的 AnalysisReport）先投影
      if isinstance(payload, Mapping): keys = sorted(payload); preview = blob[:2000]
      else: keys = []; preview = blob[:2000]              # 保持"不是对象就没有键集"这条语义
  写入：payload_keys 用 keys；新增 "payload_class"（payload 的类名）与 "payload_truncated"
  调用点：_write_task_digest（:1200）与 conductor_tools._summon_view（:100）改调 _payload_view
  不动的部分：payload_preview 的长度 2000（M 的读法已经建立在它上面，见 specs/m.py:69）
  风险一的处置（46-07 §8 第 6 条逐字）：摘要里对超长字段做**逐字段**截断
      （例如 markdown 只留 sha256 + 长度），而不是把整份 to_dict() 塞进 preview
  ```

  已知锚点（本次确认）：`conductor.py:1159`（`_end_from_payload` 的兜底行）、
  `:1184-1215`（`_write_task_digest` 全体，`:1200` blob、`:1213` `payload_keys`、`:1214` preview）、
  `:1192-1193`（`payload is None ⇒` 不写文件）、`:1278`（`def finish`）、`:1345` 附近（`finish` 调 digest）、
  `:792`（`def summon`，派活唯一入口）；
  `tools/conductor_tools.py:88-116`（`_summon_view`，`:100` blob、`:105-106` keys 判定、`:113-115` 三个字段）、
  `specs/m.py:69`（M 的读法建立在 `payload_preview` / `payload_keys` / `payload_bytes` / `payload_truncated` 上）。
- **改的依据**：`draft/46-07 §8` 第 1/2/4/6 条；`draft/44 §19 J-10`
  （`payload_keys` 恒空是结构性的）；关键证据 `[本次现算]`：根1 C 产物 37 份里 26 份 `payload_keys=[]`、
  根2 22 份里 21 份空；`conductor.py:1213` 的 `isinstance(payload, Mapping)` 就是那个分岔点。
- **怎么算过**：
  - **负控（改前必红）**：①dataclass 返回值 ⇒ `payload_keys` 非空、`payload_preview` 是合法 JSON 的前缀；
    ②dict 返回值 ⇒ 行为与今天**逐字相同**（回归）；③`payload=None` ⇒ 不写文件（`:1192-1193` 的既有语义）。
    第 ① 条改前必红。
  - **真机回放（S-01 的判据②）**：`p6j-research-from-zero` 派一次 `C.gaps`，读 `out/tasks/<task_id>.json`
    确认 `payload_keys` 含 `candidate_gaps` / `verdict`（基线：该文件 `payload_keys=[]`）。
    **注意**：历史 26 份文件**不会被改写**（摘要只在召唤时写一次）⇒ "两根 `payload_keys` 恒空"
    这条读数会从改后那一趟起**分裂**，读数说明必须写清分界点。
  - **会红的既有判据（必须同批重冻）**：`tests/test_tool_surface_snapshot.py` +
    `tests/golden/tool_surface_snapshot.json` 里 `conductor.summon` 的 `returns` 串
    逐字列了 `payload_preview` / `payload_bytes` / `payload_keys` / `payload_truncated`
    —— **改字段集必须重冻**；`tests/test_conductor.py` / `tests/test_core_audit_efgh.py` 相关用例同批跑。
  - **快照/文档/计数同步**：`out/tasks/*.json` 的字段集是**盘上产物契约**（不是 `schema.py` 的表），
    新增字段是"放宽"（旧文件缺字段不影响读）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不改 `tasks` 表（它在 FC-27 禁改区，且 `payload` 本来就不进表）；
  **不把整份 payload 落进 `out/tasks`**（那是"把产物塞进索引"）；
  不改 `_end_from_payload` 的终态映射（`ok=False` 分档那一大段是另一批）；
  **不许只改 `conductor.py` 而漏改 `conductor_tools._summon_view`**（`46-07 §8` 第 6 条风险二：
  "两份口径必然分家"）⇒ 必须由 `_payload_view` 单一来源。
- **依赖与批次**：与 §4/§5/§6 同批；可与 §5 并行（不同文件、无共享判据），
  但**回放要等 §5 落地**（否则没有 dataclass 返回值可投影）。

---

## §9 `src/agentflow/agent_a/core.py` —— S-03 的队列生产与消费

### 块 9.1 方案甲：编排层收口（`conductor.finish` 末尾自动派 A）

- **改什么**：`conductor.finish` 末尾按"这一趟是否写了 `search_requests`"自动召唤 `A.run_once`；
  带开关（缺省开启）与深度封顶（自动消费的任务不得再触发自动消费）。
  `agent_a/core.py` 本身**只加一段自检**（照 `:592-610` 的 8b 段），不改 `_claim` 的四态。
- **怎么改**：接口级。

  ```python
  # agent_a/search_literature.py:127-136（现状，逐字；仓库里唯一"提交即消费"的现成实现）
  for _ in range(max(1, int(self.search_max_rounds))):
      res = self.run_once()
      rounds.append(res.to_dict())
      if res.request_id:
          claimed_ids.append(str(res.request_id))
      row = self._request_row(rid)
      if row is not None and (row.get("done") or row.get("outcome")):
          break
      if res.request_id is None:
          break                      # 没有可领的了（原因见 skipped_reason）
  # specs/m.py:73（当前的口径：靠主控纪律，逐字节选）
  "**请求闭环：别人提交的检索请求要有人去做**…消费这条队列的动作是 A 的 `run_once`（无参）/ `run`…"
  ```

  伪码（照 `46-07 §9` 的**方案甲**；方案乙已被权限面否掉）：

  ```text
  方案甲（编排层收口，不碰权限面）：
    conductor.finish(task_id, …) 末尾：
        if self.auto_consume and role != "A" and _wrote_search_requests(action):
            self.summon("A", "run_once", {}, by="conductor:auto-consume", parent_task_id=task_id)
    _wrote_search_requests(action): 读 capabilities.WRITE_SETS[role] ∋ "search_requests"，且该动作的
        影响面 = D.submit_gaps / D.adjudicate / C.gaps / F.step / CLI submit（名单封闭，写在 conductor 里）
    开关：CLI `--no-auto-consume`（缺省开启）／config `auto_consume_search: true`
    深度封顶：自动消费的任务不得再触发自动消费（深度为 1 的封顶；`parent_task_id` 非空即不再触发）
    agent_a/core.py：新增一段自检（照 :592-610 的 8b 段形态）：
        断言自动消费后该请求 done=True 或 outcome 非 None；并断言 A 自己的 run_once 不重复触发
    超时如实记：自动消费后仍 done=False 的请求，在交付说明与 conductor.state 的
        queues.search_requests.unfinished 上如实留读数（不许吞）
  ```

  已知锚点（本次确认）：`agent_a/core.py:42-47`（`retry_backoff_seconds` 与"0 是合法配置"）、
  `:51-81`（`_enqueue_search`，过 I7 闸门）、`:590-610`（8b 段自检，**新段的写法模板**）、
  `:104-234`（`_claim`）、`:592`（`# ---- 8b)` 注释起点）；
  `agent_a/search_literature.py:118`（`_enqueue_search` 调用）、`:127-136`（同轮领跑）；
  `specs/m.py:73`（政策原文）、`tools/conductor_tools.py:683-709`（`unfinished` 的读数实现）。
- **改的依据**：`draft/46-07 §9` 第 1/2/4/5/6 条；`draft/44 §19` 无对应编号；
  关键证据 `[本次现算]`：根1 未闭环 7 条（`agent-D` 3 / `agent-C` 3 / `agent-F` 1）、
  根2 14 条（全 `agent-F`）；`46-07 §9` 第 1 条列出队列的 **5 处生产者**与唯一两个消费入口。
- **怎么算过**：
  - **负控（改前必红）**：①`D.submit_gaps` 成功 ⇒ 同轮 `A.run_once` 被召唤且 `search_requests`
    出现 `done=True`（改前必红）；②`--no-auto-consume` ⇒ 不召唤且 `unfinished` 仍是 1
    （**这就是今天的行为**，是"改前必红"的对照）；③A 自己的 `run_once` / `search_literature`
    ⇒ 不重复自动消费（幂等）；④深度封顶：自动消费产生的任务行 `parent_task_id` 非空
    ⇒ 它**不再**触发下一次自动消费。
  - **真机回放（S-03 的判据）**：比 `unfinished_request_rows` **归零**。
    基线：根1 `unfinished` 7、根2 14（见 §0.6）。回放对象：`p8e-fermat-shorter-proof`
    （`r-0004` 由 F 提交，`unfinished` 期望 1→0）与 `p6j-research-from-zero`
    （`r-0004/0005/0006` 由 C 提交，期望 3→0）。
  - **会红的既有判据（必须同批改写或新增）**：`tests/test_conductor.py` 里"`finish` 之后
    任务树只有一层"一类（本改会第一次让 `depth` 真的非 1 —— `47 §2` 第 3 组 `[我复核]`
    记着现状 `parent_task_id` 非空 **0**、`depth` 全 1）；`tests/test_agent_a.py`
    （16 处 `run_once`）、`test_agent_a_backoff.py`（9）、`test_agent_a_priority.py`（9）、
    `test_agent_a_backfill.py`（6）必须**全绿**（本块不动 A 的 `_claim`）；
    `tests/test_closing_gate.py` 的 `unfinished_request_rows` 档要跟着改期望。
  - **快照/文档/计数同步**：`cli.py` 的新开关 `--no-auto-consume` 要进 CLI 面与文档
    （`test_agent_cli.py` 的子命令快照若钉了参数表要重冻）；`specs/m.py:73` 的政策句
    是**提示词面**（`agent_prompts.py` 有同句，`specs/m.py` 在 FC-27 禁改区）
    ⇒ **不许在 `specs/m.py` 里改那句话**，改的是代码行为，政策句按 `47 §3-C1` 的教训
    （提示词面同步是另一条）另行登记。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不给 A 加边（`specs/a.py:187` 的 `edges=('B',)`，禁改区）；
  **不走方案乙**（给 C/D/F 的提交路径各补一次 `A.run_once` ⇒ 需要 C/D/F → A 的边
  ⇒ `specs/*.py` 的 `edges` + `capabilities.ALLOWED_EDGES` ⇒ **不选**）；
  不改 `_claim` 的四态与退避（A 侧行为不动）；不在 `admit_search_request` 里做"提交即消费"
  （闸门是纯函数）；不给 B 的重抽取队列做同样的自动认领（`reprocess_requests` 是另一条，L-05g）。
  **`agent_a/core.py` 与 `conductor.py` 都不在 FC-27 清单**（`47 §3-C2` `[我复核]`）。
- **依赖与批次**：**必须在 D-2（§1/§2）之后**（同一条 `run_once` 链，但 A/B 两条队列不共享判据
  —— `46-07 §9` 第 7 条明确"不给 B 的重抽取队列做同样的事"）；与 §4…§8 不同批。
  自动消费的开关与深度封顶**同批落**，不许分两次。

---

## §10 `src/agentflow/agent_d/{assess,consider,submit_gaps,research}.py` + `_support.analyze_gaps`（文件组） —— S-02 / S-08

### 块 10.1 S-02"减"：判据单一来源（`_verdict` 收口 + 同轮缓存）

- **改什么**：新增 `AgentD._verdict(qid, evidence=None) -> (ev, verdict, cached)`，
  让 `consider` / `submit_gaps` / `research` 全部改调它；`assess` 动作本身保留（它是对外入口）。
- **怎么改**：接口级。

  ```python
  # agent_d/consider.py:24-25（现状，逐字）
  ev = self.trace_question(qid)
  verdict = self.assess(qid, ev)
  # agent_d/submit_gaps.py:28-30（现状，逐字：同一问题算第二遍）
  ev = self.trace_question(qid)
  verdict = self.assess(qid, ev)
  if not verdict["insufficient"]:
      return []
  # agent_d/assess.py:36-43（现状，逐字：判据本体只有这一处）
  verdict = analyze_gaps(
      [c["relation_id"] for c in ev.get("claims") or []],
      ev.get("claims") or [],
      keywords=keywords, degree=degree, degree_threshold=self.degree_threshold,
      concept_count=len(concepts),
  )
  ```

  伪码（照 `46-07 §10`）：

  ```text
  单一来源（S-02 的"减"那半边）：
    AgentD._verdict(qid, evidence=None) -> (ev, verdict, cached: bool)
        缓存键 = (qid, 关系表 sha / 行数, 概念表行数)；同一轮内同一个 qid 只 trace+assess 一次
        consider / submit_gaps / research 全部改调它；assess 动作本身保留（它是对外入口）
    对外动作面不变（specs/d.py 的 12 个动作一个不动）
  ```

  已知锚点（本次确认）：`agent_d/consider.py:24-25`（trace+assess）、`:46`（`self.submit_gaps(qid)`，
  即**同一 qid 第二次算**）、`agent_d/submit_gaps.py:28-30`、`agent_d/assess.py:25-43`
  （`ev = evidence if ... else self.trace_question(qid)`，`:36-43` 调 `analyze_gaps`）、
  `agent_d/_support.py:241-330`（`analyze_gaps` 本体）、`:331-368`（`evidence_confidence`）。
- **改的依据**：`draft/46-07 §10` 第 1/2/5/6 条；`draft/44 §19 J-08`（S-08/S-09 真机不可证伪）；
  关键证据 `46-07 §10` 第 1 条：判据本体只有一份，但**调用链四处各自重算**
  （`assess.py:36-43` / `consider.py:24-25` / `submit_gaps.py:28-30` / `research.py:29-32`）。
- **怎么算过**：
  - **负控（改前必红）**：①同一 qid 一轮内 `trace_question` **只调 1 次**（计数可观测：
    给 `AgentD` 打桩包一层计数器）；改前 `consider` 一轮里 `trace_question`
    至少 2 次（`consider` 一次 + `submit_gaps` 一次）⇒ **必须先跑、必须红**。
    ②缓存失效正控：关系表行数变化 ⇒ 必须重算（不许拿旧缓存）。
  - **真机回放**：**做不到**（`46-07 §10` 第 6 条逐字：D 这五个动作真机 **0 次**、
    `research_questions` 表在 22 个工作区**都不存在**）⇒ 只能靠单测与自检，
    且必须在 `draft/44` 记"本条无法用真机证伪"。`[44 J-08]` 同判。
  - **会红的既有判据**：`tests/test_agent_d.py`（`assess` 2 / `submit_gaps` 3 / `trace_question` 1）、
    `tests/test_agent_d_interactions.py`（`write_report` 3）、`tests/test_dup_consolidation.py`
    （`submit_gaps` 1 / `trace_question` 1）必须全绿 —— 本块是纯重构，对外行为一字不改。
  - **快照/文档/计数同步**：`_verdict` 是新的私有方法 ⇒ 无需快照；缓存命中率若要露出，
    只能进返回值（**不落表**）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不动 `evidence_confidence` 的评分档（≥3/≥1.5 是用户口径）；
  不合并 `judge.py` / `judges.py`（L-05b 是另一条）；不改 `ingest` 的三级去重与 `enabled_kinds`；
  **不给 D 加写 `analysis_reports` 的动作**（S-01 的落盘方是 C，见 §4/§11）。
- **依赖与批次**：与块 10.2/10.3 **同批**（三块共用 `AgentD` 一处改动面），本块先落。

### 块 10.2 S-02"接通"：`trace_l3` 的可召唤性（**必须走方案乙**）

- **改什么**：`trace_l3` **不改签名**；只让 `evidence` 允许接受
  `{"qid_from": "<qid>"}` 的引用形状（向后兼容）。**不许改 `specs/d.py` 的 params。**
- **怎么改**：接口级。

  ```python
  # agent_d/trace_l3.py（现状：需要 evidence 参数；46-07 §10 第 1 条点名）
  def trace_l3(self, ...): ...   # evidence 的唯一生产者是 trace_question 的返回值（只经 payload_preview 露出）
  ```

  伪码（照 `46-07 §10`，**选乙**）：

  ```text
  trace_l3 的可召唤性（S-02 的"接通"那半边，二选一）：
    甲：trace_l3(qid: str) —— 内部自取证据包（签名改动，specs/d.py 的 params 要改 ⇒ 禁改区）⇒ 不选
    乙：trace_l3 保持 evidence 参数，但 evidence 允许是 {"qid_from": "<qid>"} 的引用形状（向后兼容）⇒ 选它
  判据：M 结构上造不出 evidence ⇒ 乙让 M 只用一个 qid 就能下钻（`evidence` 由 D 自取）
  ```

  已知锚点（本次确认）：`agent_d/` 下 `trace_l3` 的实现文件需在开工时再 `grep` 一次定位
  （`46-07 §10` 引的是 `trace_l3.py:10` 的形参）；`agent_d/_support.py:374-419`
  （trace 工具的降级替身）。
- **改的依据**：`draft/46-07 §10` 第 1/2/5 条；`draft/44 §19 J-08`；
  关键证据 `46-07 §10` 第 1 条：`evidence` 的唯一生产者是 `trace_question` 的返回值，
  **只经 `payload_preview` 露出** ⇒ M 结构上造不出这个参数；`D.trace_l3` 在 `tests/` 的调用点 **0 处**。
- **怎么算过**：
  - **负控（改前必红）**：`tests/test_agent_d.py` 新增一例：传 `evidence={"qid_from": "0001"}`
    ⇒ 断言内部自取证据包并返回与"直接传完整 evidence"**逐字相同**的结构。
    改前必红（现状会把 `{"qid_from": ...}` 当成证据包用 ⇒ 拿不到 claims）。
  - **真机回放**：**做不到**（同块 10.1 的理由）。
  - **会红的既有判据**：`tests/test_agent_d.py` / `tests/test_coverage_agent_d_demo.py` 全绿；
    `tests/test_agent_spec_reconciliation.py` 的 params 覆盖读数**不许变**（本块不动声明）。
  - **快照/文档/计数同步**：`specs/d.py` 的 `returns` 串若写死了 `evidence` 的形状，要在**不动禁改区**的
    前提下把兼容形状写进 docstring（`specs/d.py` 是禁改区 ⇒ **本块不许碰它**；docstring 落点在
    `agent_d` 内的动作文件）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：**不许走方案甲**（动 `specs/d.py` 的 params = 禁改区 auth-audit）；
  **不为 `trace_l3` 新增持久化字段**。
- **依赖与批次**：与块 10.1/10.3 同批；本块可在块 10.1 之后独立落。

### 块 10.3 S-08 采信口径：`analyze_gaps` 新增可选 `trusted`，**上限不抬高**

- **改什么**：`analyze_gaps` 新增可选输入 `trusted`；判据 b 增加"trusted 非空 ⇒ 不触发"一支；
  `evidence_confidence` 的输入从"关系行"改成"行 + trusted"，但**上限不抬高**。
- **怎么改**：接口级。

  ```python
  # agent_d/_support.py:283-294（现状，逐字；判据 b 是唯一会被 trusted 影响的一条）
  if degree < degree_threshold and not verified:
      criteria.append({"id": "b_low_degree_unverified", "ok": True, "priority": "medium",
          "detail": (f"相关概念度数 {degree} < 阈值 {degree_threshold}，且 {len(relations)} 条关系里"
                     "没有一条 quote_verified=True（连一条有原文支撑的关系都没有）")})
  # agent_d/_support.py:331-337（现状，逐字；上限在 _rank_min 那一支，不许松）
  def evidence_confidence(relations, *, degree=0, concept_count=0, contradictions=0) -> str:
  ```

  伪码（照 `46-07 §10`）：

  ```text
  analyze_gaps 新增可选输入 `trusted: Sequence[str] = ()`（D 自己读过的 proof/引文关系 id）
  判据 b（度数低且无 quote_verified）增加"但 trusted 非空 ⇒ 不触发"这一支
  置信度上限：evidence_confidence 的输入从"关系行"改成"行 + trusted"，
      但**上限不抬高**（`_rank_min` 那条不许松）：采信只影响"方向"，不影响数字
  不落新字段：trusted 只进返回值与 notes，**不写进 research_questions 行**
  ```

  已知锚点（本次确认）：`agent_d/_support.py:241-249`（`analyze_gaps` 签名，无 `trusted`）、
  `:266-268`（`verified` / `hits` / `contradictions` 的现算）、`:283-294`（判据 b）、
  `:311-330`（优先级与返回 dict）、`:331-337`（`evidence_confidence` 签名）。
- **改的依据**：`draft/46-07 §10` 第 2/4/5/6 条；`draft/44 §19 J-08`；
  关键证据 `46-07 §10` 第 6 条风险二逐字："`trusted` 一旦来自 D 自己（"我看了一遍没毛病"），
  就**等于把"自证"重新引入**，而本节整套设计的核心是"自报不算凭据"（`evidencebits.py:118-120` 逐字）"
  ⇒ 必须给 `trusted` 定义**可复核的来源**（例如"引文 `quote_verified is True` 且被 D 在报告里逐条点名"）。
- **怎么算过**：
  - **负控（改前必红）**：①`trusted` 非空时判据 b 不再触发，而**没有** `trusted` 时行为与今天
    **逐字相同**（改前必红的是"`trusted` 非空 ⇒ 不触发"这一支——现状根本没有这个参数）；
    ②`_rank_min` 仍然**只降不升**（`tests/test_agent_d.py` 已有类似断言）；
    ③`trusted` 的来源可复核：给一个**不在 evidence 里的 relation_id** ⇒ 必须被忽略（不许凭口号采信）。
  - **真机回放**：**做不到**（同块 10.1）。
  - **会红的既有判据（必须同批改写）**：`tests/test_agent_d.py` 里凡断言"度数低且无
    `quote_verified` ⇒ `insufficient is True`"的用例；新增一个带 `trusted` 的用例。
    既有用例**不传 `trusted` ⇒ 行为不变**（它们是"不误伤"对照，必须仍绿）。
  - **快照/文档/计数同步**：`46-07 §10` 第 5 条要求"按 `draft/45 §3` 第 2 条写清'从哪一趟起口径变了'"；
  本块**改的是判据**（不是措辞）⇒ 必须在 `draft/44` 登记；且必须写明"这是用户点名的那条口径，
  与 `evidencebits` 的位机制不冲突"。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：**不新增持久化字段**（`trusted` 的持久化 = 加字段 ⇒ 违反"不许加必填字段"）；
  不给 `trusted` 留"模型自称的采信"入口；不改 `evidence_confidence` 的评分档（≥3/≥1.5）。
  **本块不在禁改区**（判据在 `_support.py`）。
- **依赖与批次**：与块 10.1/10.2 同批；**必须最后落**（它依赖块 10.1 的 `_verdict` 提供统一证据包）。

---

## §11 `src/agentflow/agent_d/write_report.py` —— S-07 的报告双写

### 块 11.1 S-07 **当前形态不可行**（照 `46-07 §14` + `44 J-01` 的判定，不改判）

- **改什么**：**不改 `analysis_reports`**。本块的产出是"改判 + 登记"，不是代码。
  正确的落点是二选一：**新增 D 自己的报告落点**（新表）或**随 L-01/L-03 走 `documents`**；
  两条路都要动 `schema.py`（禁改区）⇒ 属另一批，**不在本方案执行**。
- **怎么改**：接口级 —— 现状原文（留档，供下一批接手）：

  ```python
  # agent_d/write_report.py:38-45（现状，逐字）
  rows = sorted(self.store.rows("research_questions"), key=lambda r: str(r.get("question_id")))
  analyses = getattr(self, "last_research", {}) or {}
  run_id = rows[-1]["question_id"] if rows else "0000"
  from ..tools.doc_tools import resolve_out_path
  _rel, path = resolve_out_path(Path(self.store.root).resolve(), out_path,
                                f"{run_id}-research", self.reports_subdir)
  path.parent.mkdir(parents=True, exist_ok=True)
  # agent_d/write_report.py:407-410（现状，逐字：只有文件写，没有落库）
  text = "\n".join(lines) + "\n"
  path.write_text(text, encoding="utf-8")
  self.last_report_path = path
  return str(path)
  ```

  伪码：**无（不许按 `46-07 §11` 第 2 条的伪码施工）**。判据本体（两条硬卡点，逐字照抄 `46-07 §11` 第 5 条）：

  ```text
  ①kind 只能是 hottest/paths/cold/gaps（schema.py:442 + schema.AnalysisReport.validate:842-843）
    —— D 的研究报告**没有合法 kind**，写进去等于对一个表外 kind 撒谎，
    而 closing.py:165-169 的 analysis_report_rows 会把"C 的产出"与"D 的报告"混成一档；
  ②WRITE_SETS["D"] 要加一张表（specs/d.py:232-235）⇒ 改禁改区。
  ⇒ S-07 的正确落点**不是** analysis_reports，而是新增 D 自己的报告表，
     或把 write_report 的结果登记进 documents/manuscripts，两者都要动 schema.py（禁改区）。
  ```
- **改的依据**：`draft/46-07 §11` 第 1/5/6 条；`draft/46-07 §14` 汇总表的 S-07 行
  （可行性 **低（当前形态不可行）**）；**`draft/44 §19 J-01`**（逐字："S-07 改判为'不可按原形态做'…
  **不许**为它扩 `REPORT_KINDS`（schema 禁改区）"）；
  关键证据 `schema.py:442`（`REPORT_KINDS = ("hottest","paths","cold","gaps")`）、
  `schema.py:842-843`（`validate` 抛错）、`specs/d.py:232-235`（`write_set` 只有
  `research_questions` / `search_requests`）；真机：`write_report` 召唤 **45** 次全 `ok`
  而 `analysis_reports` **0 行**，盘上 `<qid>-research.md` 只有 **5** 份（同名覆盖）。
- **怎么算过**：
  - **负控（改前必红，且它是"证明不可行"的负控）**：造一条 `S.AnalysisReport(kind="research", ...)`
    ⇒ `validate()` **必须抛**（`schema.py:842-843`）。这条是**现状**行为，
    用来钉住"不许为 S-07 扩 `REPORT_KINDS`"：一旦有人扩了词表，这条就绿了 ⇒ 它是**反向门**。
  - **真机回放**：**部分可证伪**（`46-07 §14` 逐字：S-07 的真机可证伪性 = "部分（文件数 vs 表行数）"）
    ⇒ 本块**不做回放**（没有改动能回放）；下一批做时，判据是"文件数不变、表里出现对应行"。
  - **会红的既有判据（下一批必须同改）**：`tests/test_write_report_path.py`（4 处，
    专测"相对路径按工作区根解析、越界拒绝"）—— 本块不动它；
    `tests/test_scheduler.py:828-839`（用 `WRITE_SETS` 相交观察分波）—— 下一批若让
    `analysis_reports` 同时出现在 C 与 D 的写集里，会把并发的 C 与 D 排成两波 ⇒ 必须复算这条。
  - **快照/文档/计数同步**：`draft/44 §19 J-01` 已登记本改判；本方案的义务是**照抄不改判**。
  - **全量门**：同 §1（本块不产生代码 diff）。
- **不许这么改 / 边界**：**不许为 S-07 扩 `REPORT_KINDS`**（`schema.py` 禁改区）；
  **不许从四个合法 kind 里挑一个**（例如拿 `gaps` 顶）—— 读数说谎；
  不改 `write_report` 的签名（返回值是 `str`，`test_write_report_path.py` 逐字依赖）；
  不把整篇 markdown 塞进 `payload`；不改 `closing.py` 的 `report_files` 档。
- **依赖与批次**：**独立成批（下一批）**，与本方案其余条目无耦合。
  与 S-01（§4…§8）**必须分开**：S-01 落地后 `analysis_reports` 是 **C 的产出表**，
  S-07 若同批进来会把两件事混成一档 —— 这正是 J-01 要防的。

---

## §12 `src/agentflow/agent_d/core.py` —— S-09 的 `conclusion` 与数字一致性

### 块 12.1 结论文本由置信度档位渲染，不由模型渲染（保留模型原话）

- **改什么**：`_llm_refine` 返回前，保留模型原话到 `conclusion_body`，把 `conclusion`
  用**唯一渲染点** `_conclusion_for(forced, ...)` 重写；`_CONF_HEAD` 与
  `_deterministic_compose` 的三句**同源**。
- **怎么改**：接口级。

  ```python
  # agent_d/core.py:1152-1156（现状，逐字：LLM 的三段文本被直接采用）
  if self.llm is not None:
      try:
          out = self._llm_refine(ev, verdict)
          if out is not None:
              return out["analysis"], out["conclusion"], out["suggestions"], True
  # agent_d/core.py:1256-1264（现状，逐字：只夹取 confidence，conclusion 之后原样返回）
  forced = _rank_min(str(payload.get("confidence") or "low"), verdict.get("confidence") or "low")
  if forced != payload.get("confidence"):
      self.last_tool_errors.append({"tool": "llm", "error": f"LLM 试图把置信度从 … 已强制降回 {forced}"})
  payload["confidence"] = forced
  # agent_d/core.py:1265-1269（现状，逐字：conclusion 走 setdefault 原样进返回值）
  payload.setdefault("analysis", "")
  payload.setdefault("conclusion", "")
  # agent_d/core.py:1184-1192（现状，逐字：确定性分支的三句，措辞强度的唯一落点）
  if conf == "low": conclusion = "**置信度：低** —— …本节的措辞刻意停在「可能存在/尚未证实」…"
  ```

  伪码（照 `46-07 §12`）：

  ```text
  _llm_refine 返回前（:1264 之后）：
      payload["conclusion_body"] = payload.get("conclusion", "")     # 保留模型原话（审计用）
      payload["conclusion"] = _conclusion_for(forced, body=payload["conclusion_body"], verdict=verdict)
  _conclusion_for(conf, *, body, verdict) -> str:      # 新增纯函数（唯一渲染点）
      head = _CONF_HEAD[conf]        # 与 _deterministic_compose:1184-1192 逐字相同的那三句
      tail = "（模型原话保留在 conclusion_body；本节措辞由置信度档位渲染）" —— 只在 body 与 head 明显不一致时加
      return head + ("\n\n" + body if body else "")
  另外两处一致化：
      ①research.py 的 result["confidence"] 与 result["conclusion"] 都取自同一 verdict ⇒ 已一致，不动
      ②write_report.py:296-299 不动（它只写 conclusion；一致性由上游保证）
  ```

  已知锚点（本次确认）：`agent_d/core.py:1145-1159`（`_compose`）、`:1152-1156`（LLM 分支）、
  `:1160-1207`（`_deterministic_compose`，含 `:1184-1192` 的三句）、`:1208-1269`（`_llm_refine`，
  含 `:1250-1255` 解析失败退回、`:1256-1264` 夹取、`:1265-1269` 原样返回）；
  `agent_d/core.py:66`（`enabled_kinds` 默认 = `S.REPORT_KINDS`，见 §汇总边界）。
- **改的依据**：`draft/46-07 §12` 第 1/2/5/6 条；`draft/44 §19 J-08`（S-09 真机不可证伪）；
  关键证据 `core.py:1265-1269` 逐字：`conclusion` 走 `setdefault` ⇒ **模型原话直接进报告**；
  而 `:1184-1192` 的确定性分支里措辞强度**是**由 `conf` 决定的（低档逐字写"本节措辞刻意停在…"）。
- **怎么算过**：
  - **负控（改前必红）**：①需要一个"模型写出高置信度口吻、数字是 low"的替身模型
    （照 `tests/test_semantic_review.py` 的 `_Model` 返回合规 JSON 的写法）
    ⇒ 断言最终 `conclusion` 以"**置信度：低**"开头且 `confidence == "low"`。改前必红。
    ②LLM 解析失败（`_parse_json_block` 返回 None，`:1247`）⇒ 走确定性结论（既有行为，回归）。
    ③`llm=None` ⇒ 输出与今天**逐字相同**（回归，可用现有 `tests/test_agent_d.py` 的固定串做快照）。
  - **真机回放**：**做不到**（`46-07 §12` 第 6 条逐字：D 从未接 LLM，45 次 `research` 全走
    `_deterministic_compose`）⇒ 在 `draft/44` 写明"本条只能用替身模型验证"。`[44 J-08]` 同判。
  - **会红的既有判据（必须同批改）**：`tests/test_coverage_agent_d_demo.py`（`write_report` 5 处）
    里若断言了结论小节的固定文本；`tests/test_agent_d.py` 的确定性分支快照必须仍绿
    （`_CONF_HEAD` 与 `:1184-1192` **必须逐字同源**）。
  - **快照/文档/计数同步**：`conclusion_body` 是返回值里的新键（放宽，不是加必填字段）；
    `46-07 §12` 第 6 条风险一要求"让 `write_report` 在某一处能读它，或明确'原话只进返回值'"
    —— 施工时必须**二选一并写明**。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不动 `_deterministic_compose` 的三句正文（它们是"低就是低"的唯一落点）；
  不动 `_rank_min`（S-08 的"只降不升"是它的职责）；不给 `conclusion` 加"必须包含某个词"的机械判据；
  不改 `write_report` 的结论小节结构（九节/五段属 closing 读数，另一批）。
  **本块不在禁改区**（`conductor.py` / `agent_d/core.py` 都不在 FC-27 清单）。
- **依赖与批次**：与 §10 的 S-08 同批（两者共用"置信度是唯一数字真源"这条口径）；
  **与 §10 的块 10.3 有先后**：块 10.3 定的是"数字从哪来"，本块定的是"文本怎么跟数字走"
  ⇒ 块 10.3 先落。

---

## §13 `agent_h/{core,verify_fixes}.py` + `tools/review_tools.py`（文件组） —— R-04 的 H 侧

### 块 13.1 R-04-a：让 `verify_fixes` 拿得到语义判据（注入面打通）

- **改什么**：`tools/review_tools.verify_fixes` 签名加 `semantic_judge=None`；
  `scan_document` 调用带上它；`_WRITE_TOOL_FUNCTIONS` 里 `verify_fixes` 的注入元组加 `'semantic_judge'`。
- **怎么改**：接口级。

  ```python
  # tools/review_tools.py:1177-1185（现状，逐字：签名里没有 semantic_judge）
  def verify_fixes(store: Any, doc_id: str, *, round_no: int, dependencies: Any = _UNSPECIFIED,
                   max_review_rounds: int = 2, actor: str = "agent-H") -> dict: ...
  # tools/review_tools.py:1213-1216（现状，逐字：复扫不带语义判据 ⇒ 上一轮的语义 finding 不可能复现）
  doc = _doc_of(store, doc_id)
  deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
  scan = scan_document(doc, dependencies=deps)
  current = {_dedup_key(f): f for f in scan["findings"]}
  # tools/review_tools.py:1737-1741（现状，逐字：verify_fixes 那一项只注入三个名）
  _WRITE_TOOL_FUNCTIONS = (
      (_review_review_document_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
      (_review_verify_fixes_tool, ('_not_wired', 'store', 'actor')),
      (_review_report_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
  )
  ```

  伪码（照 `46-07 §13` 第 2 条 + `46-05 §1.2` 的 R-04-a）：

  ```text
  def verify_fixes(..., semantic_judge=None) -> dict:
      scan = scan_document(doc, dependencies=deps, semantic_judge=semantic_judge)   # 唯一改动
  _WRITE_TOOL_FUNCTIONS 的 verify_fixes 那一项注入名加 'semantic_judge'（第 4 项）
  工具体（review_tools.py:1653）与 @tool properties：由装配期注入，不进模型参数表
  agent_h/verify_fixes.py（:10-38）转发层透传 self._semantic_judge
      （角色层不给参数时，由 self.writers 的 partial 注入 —— semantic_judge 已在 register 里绑定，
       见 review_tools.py:1744 附近的 register(...)）
  ```

  已知锚点（本次确认）：`tools/review_tools.py:1177-1185`（签名）、`:1213-1216`（复扫）、
  `:1232-1238`（`key in current` 判据与 `resolved` 落点）、`:1259-1266`（`_apply_finding_status` 写 `fixed`）、
  `:1728-1741`（读/写两张装配表）、`:1744`(起)（`register`，`semantic_judge` 形参已存在）；
  `agent_h/core.py:69-75`（`JG.semantic_judge_for(self.llm)` → `RV.register(..., semantic_judge=judge)`）、
  `:83-94`（`_H_WRITABLE_TOOLS` 装配期断言）；
  `agent_h/verify_fixes.py:10`（角色层签名，无 `semantic_judge`）、`:31-38`（`params` 组装 + `self._writer(...)`）。
- **改的依据**：`draft/46-07 §13` 第 1/2/5 条；`draft/46-05 §1.2` 改动点 R-04-a（逐字）；
  `draft/46-05 §8.1` 第 3 条（"R-04-b（零成本兜底）可以先做；R-04-a（接模型）放
  `--semantic-review` 之后"）；关键证据 `[本次现算]`：根1 `review_findings` **13 行全 `overclaim`**、
  其中 7 行 `fixed`；`46-05 §1.3` 记真机 `H.verify_fixes` **7** 次恰好对应这 7 行 `fixed`。
- **怎么算过**：
  - **负控（改前必红）**：照 `46-05 §1.6` 三条独立口径：
    ①造 `cross_check` 且措辞干净的稿件 + 恒返回 `stronger_than_evidence` 的假判据 ⇒
    `review_document` 得 `accepted_with_warnings` 且库里有 1 行 `overclaim/warning/open`；
    ②再调 `verify_fixes(round_no=2)` ⇒ 必须仍 `open`（块 13.2）或在 `still_open` 里出现（本块），
    **不许** `resolved=[overclaim]`；
    ③直接读 `data/review_findings.json` 断言该行 `status != "fixed"`。改前 ②③ 必红。
  - **真机回放（R-04-H 的判据）**：比**13 行 `overclaim` 的 `resolved` 数**。
    基线：7 行 `fixed`（`46-05 §0.1`）；`46-05 §1.4` 的内存探针已证明 `p8d` 现行版上
    claim-3/claim-4 **仍被语义判据判为"结论强于引文"**，而库里写着 `fixed`。
    回放对象：`p8e-fermat-shorter-proof` / `p8g-fermat-shorter-proof`（有 `H.review` 与改稿的历史）
    重跑 `review → verify_fixes`，对比改前/改后 `resolved` 里 `overclaim` 的条数
    （改前应能复现 R-04 探针的 `resolved=[overclaim]`，改后应为 **0**）。
  - **会红的既有判据（必须同批改写或重冻）**：`tests/test_agent_h.py` 的 5 条
    `verify_fixes_*`（`:474` 真修好 / `:524` 没修 / `:542` 终止性 / `:558` 谎报重开 / `:589` 依赖清单）
    —— 其中 3 条断言"标 fixed 仍复现要重开"，**语义维要新增第 6 条**；
    `tests/test_semantic_review.py`（全 8 例，**没有一例覆盖 `verify_fixes` 的语义维**）⇒ 必须补；
    `tests/test_coverage_agent_h.py`（2，转发层）；`tests/test_tools_returns_declaration.py`（7）
    与 `tests/golden/tool_surface_snapshot.json`（`review.*` 的 properties）⇒ **改 `@tool` 要重冻**；
    `tests/test_r4_readonly_exceptions_tables.py:53-247`（`review.verify_fixes` 的写集逐工具登记）。
  - **快照/文档/计数同步**：`TOOL_WRITE_SETS["review.verify_fixes"] == ["documents","review_findings"]`
    **不许变**（本改动不改工具名与写集 ⇒ 不碰权限面）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不把 `semantic_judge` 放进 `@tool` 的参数表（它是装配期注入，不进模型参数表）；
  不改工具名与写集（`_H_WRITABLE_TOOLS` 是从 `READONLY_CALL_EXCEPTIONS` 派生的，
  `capabilities.py` 的断言守着）；不改 `agent_h/core.py:48-55` 与 `:83-94` 两条装配期断言。
  **`tools/review_tools.py` 不在 `.noai-paths`**（`47 §3-C2` `[我复核]`：未命中），
  但它在 **auth-audit 的相邻面** ⇒ 先改后报备。
- **依赖与批次**：**块 13.2 先落**（零成本兜底，`46-05 §8.1` 第 3 条逐字），
  本块（接模型）随后同批；两块的测试在同一个新用例文件里。

### 块 13.2 R-04-b：没重跑语义判据时，语义发现**不许**被判 `fixed`

- **改什么**：在写 `status` 之前加一支：`evidence` 以 `语义判据（` 开头的 finding，
  本轮没重跑语义判据 ⇒ 进 `still_open` 并标 `source="not_rechecked"`，`status` 保持 `open`。
- **怎么改**：接口级。

  ```python
  # tools/review_tools.py:1232-1238（现状，逐字：去重键不等 ⇒ 进 resolved）
  key = _dedup_key(r)
  if key in current:
      base["evidence"] = current[key].get("evidence"); base["source"] = "prev_round"
      still_open.append(base)
  else:
      resolved.append(base)
  # tools/review_tools.py:1259-1266（现状，逐字：resolved 一律写 fixed）
  ```

  伪码（照 `46-05 §1.2` 的 R-04-b + `46-07 §13` 第 2 条的三态）：

  ```text
  插在 1257-1266 的落状态之前：
  for item in resolved:
      if _is_semantic_finding(item):        # evidence 以 "语义判据（" 开头（review_tools.py:605-609 给了前缀）
          changes.append({"finding_id": item["finding_id"], "status": "open",
                          "resolution_note": f"[round {round_no}] 本轮未重跑语义判据 ⇒ 不许判 fixed（没查 ≠ 修好）"})
          continue
      changes.append({... "status": "fixed" ...})
  三态（缺一不可，46-07 §13 第 2 条逐字）：
    ①判据没接线（None）⇒ 这一维"没查"：这类 finding 进 still_open 且标 source="not_rechecked"（新增取值），
       并在 reason 里逐字写"语义判据这次没跑 ⇒ 不许当已修好"
    ②判据跑了且不再复现 ⇒ 才允许 resolved ⇒ fixed
    ③判据跑了但答 unknown / 抛异常（checker_errors）⇒ 同样不许 resolved（照 scan_document:566-595 的处置）
  风险一的处置（46-07 §13 第 6 条）：只对**上一轮由语义判据产生的 finding**应用"没查就不算修好"，
    其余仍按现口径；机械那一支（OVERCLAIM_MARKERS）与语义那一支必须能分开 —— 判据在 evidence 串里
  ```

  已知锚点（本次确认）：`tools/review_tools.py:1213-1238`（复扫与 `resolved`/`still_open` 分派）、
  `:1259-1266`（写状态）、`:1267-1282`（`_apply_finding_status` 的重开逻辑，**不许动**）、
  `:1287-1304`（`verdict/target_status` 映射，**不许动**）、`:1305` 起（`R-59` 的签名门，**不许动**）；
  `46-05 §1.1` 给的语义前缀落点在 `review_tools.py:605-616`（语义级 `overclaim` 的 `message`）
  与 `:899-901`（`_dedup_key`）。
- **改的依据**：`draft/46-05 §1.2` 改动点 R-04-b（逐字："更保守、零成本"）；
  `draft/46-05 §1.1` R-04 的机制两句话；`draft/46-07 §13` 第 2/6 条；
  `draft/46-05 §8.1` 第 3 条（先做 b）；
  关键证据 `46-07 §13` 第 4 条逐字："真机 `review_findings` agentflow 根 **13 行**（全 `overclaim`，
  warning 级）… **这 13 行正是本条要保护的对象**：改后复审若没接判据，它们**不再**能被自动置 `fixed`
  （改前它们可以）"。
- **怎么算过**：
  - **负控（改前必红）**：照 `46-07 §13` 第 6 条四条必须都能红：
    ①接判据 + 模型仍判 `overclaimed` ⇒ finding **不许** `resolved`、`status` 保持 `open`/重开
    （今天的反例是它会变 `fixed`）；
    ②不接判据（`semantic_judge=None`）⇒ 上一轮的语义 finding 进 `still_open` 且
    `source="not_rechecked"`、verdict **不是** `accepted`；
    ③`llm=None` 的默认路径 ⇒ `review` 那一维 `checked=False`（`scan_document:547-555`），
    复审同样"没查就是没查"；
    ④正控：G 真的把那条断言改弱了 ⇒ 语义判据答 `within_evidence` ⇒ 才允许 `fixed`。
  - **真机回放**：同块 13.1（比 13 行 `overclaim` 的 `resolved` 数）。
  - **会红的既有判据**：同块 13.1；另加"不误伤"对照：
    `46-05 §1.6` 逐字 —— `p6o`（4 行本来就 `open`，必须**保持不变**）。
  - **快照/文档/计数同步**：`still_open` 项的 `source="not_rechecked"` 是**返回值**取值（不落表）；
    `review_findings.status` 的取值**不动**（不新增 `status` 取值）。
  - **全量门**：同 §1。
- **不许这么改 / 边界**：不动 `scan_document` 的机械判据与三态排序（`tools/review_tools.py:528-625`）；
  不动 `_apply_finding_status` 的重开逻辑与 `verdict/target_status` 映射；
  **不把语义判据升到 error 级**（`review_tools.py:543-546` 逐字说"要不要升到 error 是口径问题，
  属 FC-27 的 eval-criteria 类 ⇒ 留给人裁"）；不新增 finding `kind`（`schema.FINDING_KINDS` 是受控词表）；
  **不动 `_dedup_key`**（`46-05 §1.2` 改动点 R-04-c 判"不做"：改动面大于 R-04 本身）。
- **依赖与批次**：**本块先落**（零成本、不动装配面），块 13.1 随后；两块同批，测试同文件。
  与 §4…§8（S-01）不同批。

---

## §汇总

### 汇总.1 条目总表

| 条目 | 文件 | 可行性（照 `46-07 §14`） | 是否禁改区 | 批次 |
|---|---|---|---|---|
| D-2 | §1 `agent_b/core.py` + §2 `agent_b/run_once.py` | 高 | 无 | 批 1 |
| EE-12 | §3 `agent_b/register_statement.py`（补 `bits=`） | 高 | `specs/b.py`（参数表）⇒ **需 2 名人审** | 批 2 |
| EE-07 | §3（`evidence_kind` 派生） | 中高 | `specs/b.py`；口径变更要在册 | 批 2 |
| S-01 | §4 §5 §6 §8（+ §7 作为"不改"条目） | 中 | `schema.py:442 REPORT_KINDS`（若要覆盖 9 个动作 ⇒ **不许**） | 批 3 |
| S-03 | §9 `agent_a/core.py` + `conductor.py` | 中 | `specs/*.edges`（若走方案乙，**已否**） | 批 4 |
| S-02 | §10 | 中 | `specs/d.py`（`trace_l3` 签名，若走方案甲 ⇒ **不选**） | 批 5 |
| S-07 | §11 | **低（当前形态不可行）** | `specs/d.py` WRITE_SETS + `schema.py`（kind/新表） | 下一批（独立） |
| S-08 | §10 | 中 | 无（判据在 `_support.py`） | 批 5 |
| S-09 | §12 | 高 | 无 | 批 5 |
| R-04-H | §13 | 高 | 无（`review_tools.py` 不在清单） | 批 6 |

**禁改区核对**（照 `47 §3-C2` 的 `[我复核]`）：
`tools/review_tools.py`、`agent_b/*`、`agent_c/*`、`agent_d/*`、`agent_h/*`、`conductor.py`
**一条都不在** FC-27 清单；`specs/b.py`、`specs/d.py`、`schema.py`、`specs/*`（含 `specs/c.py`、`specs/m.py`）
**在册**（`[category: auth-audit]` / `[category: schema-migration]` / `[category: eval-criteria]`）。
⇒ 本方案中凡要求改这三处的（只有 EE-12/EE-07 的 `specs/b.py`），**必须走 2 名人审**；
其余条目一律**不许**借"顺手"改它们。

### 汇总.2 未核实项（不许折成"没问题"）

| 项 | 为什么未核实 | 出处 |
|---|---|---|
| `tests/` 里 `trace_l3` 的实现文件与行号 | `46-07 §10` 引的是 `trace_l3.py:10` 的形参，本文件未逐行打开该文件 | 本文件 §10 块 10.2 已标"开工时再 `grep` 一次定位" |
| `agent_b/_support.py` 的 `BRunResult.to_dict()` 是否有快照依赖 | 未跑快照测试 | `47 §4` 同族（"快照重冻的具体字节差"未复算） |
| S-02/S-08/S-09 的真机行为 | **真机不可证伪**（`46-07 §14` 逐字："**不可**"）：22 个工作区没有 `research_questions` 行、D 未接 LLM ⇒ 只能替身 + 负控 | `46-07 §14` + `44 J-08` |
| S-07 的真机行为 | **部分可证伪**（"文件数 vs 表行数"），但本块不改代码 ⇒ 不回放 | `46-07 §14` |
| S-05 腿 2 | **不可行**（`46-07 §14` 末段：`statements` 138 行里 `own_result` 13 行、`grade` 全是 `conjecture`，6 行 `pre_theorem` 全是 `external_lit` ⇒ 这一档恒红）⇒ 必须等 F-01/EE-12 落地 | `46-07 §14`；`44 J-22` |
| 全量门的基线读数（0 错 / 9 警 / 49 提示；`--strict` 0/58/48） | 本文件未跑（任务禁止跑 pytest） | 任务给定的基线；施工时**第一次跑必须复现它** |
| `AGENTS.md` 与 `.noai-paths` 的逐条一致 | 本文件未跑 `scripts/noai_gate.py --check-consistency` | `AGENTS.md` 的警告区逐字 |

### 汇总.3 施工顺序

```text
批 1（D-2）    §2 run_once.py（写入面）→ §1 core.py（判据面）   【必须同批，§2 先】
批 2（EE-12/07） §3 块 3.1（补 bits=）→ §3 块 3.2（evidence_kind 派生）【必须同批，3.1 先】
                     ⚠ specs/b.py 需 2 名人审
批 3（S-01）   §7 graph_tools.py（作为"不改"的条目，先钉住）
               → §4 _support.py（_finish_report）→ §5 四个动作（_report 收口，选路由②）
               → §8 conductor.py（_payload_view，可与 §5 并行，回放要等 §5）
               → §6 agent_c/core.py（露出 report_id / markdown_path）
               ⚠ §7 与其余四块同批但**不许合并改动面**
批 4（S-03）   §9 方案甲（conductor.finish 收口 + 开关 + 深度封顶，一次落齐）
               → agent_a/core.py 的新自检段
批 5（S-02/08/09）§10 块 10.1（_verdict 单一来源）→ 块 10.2（trace_l3 走乙）
               → 块 10.3（trusted，上限不抬高）→ §12（_conclusion_for）
               ⚠ 三块+§12 同批；真机不可证伪 ⇒ 只跑替身 + 负控
批 6（R-04-H） §13 块 13.2（零成本兜底）→ 块 13.1（接语义判据）
下一批（独立） §11 S-07 改判的落地：新增 D 自己的报告落点，或随 L-01/L-03 走 documents
               ⚠ 不许为它扩 REPORT_KINDS；不许从四个合法 kind 里挑一个
```

**跨批纪律**（照 `46-07 §14` 末段与 `46-05 §8.1`）：

- 每批**只跑一次全量门**，跑在批内最后一块落地之后。
- 每批**先跑负控、看它红**，再改代码；**不许**先改代码再补负控。
- 批 3 与批 4 之间**没有依赖**，可以交换顺序；但批 3 的 §8 回放要等 §5 —— 这是**批内**顺序。
- 批 5 与批 6 之间没有依赖。

### 汇总.4 三条口径分界（照 `46-07 §14` 末尾逐字，必须写进 `draft/44`）

1. **`analysis_reports` 从 S-01 落地那一趟起才有产出方**。
   —— 本方案落地前：两根 **0 行**（文件存在：根1 57 份、根2 22 份）；落地后：C 的
   `hottest`/`paths`/`cold`/`gaps` 四个 kind 会各落一行 + 一份 markdown，
   `contradictions`/`neighbors`/`relations_between`/`structural_duplicates`/`handle`
   **仍然不落**（`REPORT_KINDS` 限制，`schema.py:442`，禁改区）。
   同时 `closing.py` 的 `analysis_report_rows` 档会第一次有读数。
2. **`statements.evidence_kind` 从 EE-07 落地那一趟起由 `bits` 派生**。
   —— 历史行的读数会变：`bits={}` 的旧行仍按"五位全空"读（`evidencebits.bits_from_row`），
   等级仍是"猜想"；但 `origin=external_lit` 且 `quote_verified=True` 的行在派生口径下会得 `proof`
   （`bits_of` 的 cited 分支）⇒ 根1 现有 `proof` 6 行之外的行的 `evidence_kind` 读数会变。**这是口径变更，不是 bug。**
3. **`review_findings` 的语义级 `overclaim` 从 R-04-H 落地那一趟起不再能被自动置 `fixed`**。
   —— 落地前：根1 的 13 行里 **7 行 `fixed`**（恰好对应真机 `H.verify_fixes` 的 7 次）；
   落地后：没重跑语义判据的那些 finding 进 `still_open` 并标 `source="not_rechecked"`，
   `46-05 §1.4` 的内存探针已证明 `p8d` 的 claim-3/claim-4 **在现行版上仍被语义判据命中**
   ⇒ 它们会**重新打开**（预期变化，`44 J-02` 同族的"历史行状态不再被静默改写"）。

### 汇总.5 两处必须改口径的施工单（照 `46-07 §14` 末段）

1. `draft/45 §1.4` 把 S-07 写成"`write_report` 也落台账"，但 `analysis_reports` 的 `kind` 词表
   （`schema.py:442`）里没有 D 的研究报告种类，且 `WRITE_SETS["D"]`（`specs/d.py:232-235`）不含该表
   ⇒ 这条路在当前结构下**不可行**（`44 J-01` 已登记），应改判为"新增 D 自己的报告落点"或
   "随 L-01/L-03 一起让 D 的报告走 `documents`"。
2. `draft/45 §1.4` 把 S-01 写成"落盘形态一变，D.ingest 与读数都要跟着改"，但 `D.ingest` 的
   `enabled_kinds` 默认等于 `S.REPORT_KINDS`（`agent_d/core.py:66`，本次确认逐字：
   `self.enabled_kinds = tuple(self.cfg.get("enabled_kinds") or S.REPORT_KINDS)`）
   ⇒ **只有那 4 个 kind 会被 D 吸收**，其余五个动作落盘也不会进 D。这一点必须在下一批的施工单里写明。

---

## 边界声明

1. 本文件**只写这一个文件**。没有改 `agentflow/src/`、没有改任何工作区文件、没有跑 pytest、
   没有跑模型、没有联网。只读操作：`read` / `grep` / `glob` / `python -B -c`（只读统计）。
2. 本文件**不做任何新的可行性判定**：§汇总.1 的"可行性"一列逐字来自 `46-07 §14`。
3. 本文件里标 `[本次现算 + 命令]` 的读数由我重跑得到；标 `[本次确认]` 的行号由我逐行打开确认；
   其余读数逐条标注来源（`46-07 §0`、`46-05 §0`、`44 J-zz`、`47 §2`）。
   未被复核的数一律带 `[子代理]` 语义，不许被当成"已核实"引用。
4. 本文件与 `46-07` 冲突处**以 `46-07` 为准**；唯一的例外是 §0.7 记的行号漂移
   （`tools/graph_tools.py` 的 `from_store` 现状是 `:347`，不是 `46-07 §7` 的 `:354-358`）——
   那是**行号**漂移，结论（"本文件不需要改"）不变。
