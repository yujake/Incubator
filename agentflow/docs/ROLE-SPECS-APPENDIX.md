# ROLE-SPECS-APPENDIX —— 实测附录（读数带日期，不构成判据）

> **本文件是 [`ROLE-SPECS.md`](ROLE-SPECS.md) 的实测附录**：`R0.1`–`R0.3`、各角色 `.4` 工具面明细、
> 全部 `.10` 自检实测、`M.4.2` / `M.4.3`、`M.8` 补核、`S1`–`S3`。
> **每一节的首行都标 `[附录·实测]`。读数带日期、不构成判据；与代码冲突以代码为准。**
> 采集日期：**2026-10-18**；**2026-10-21 按 `cli tools` 现读重算了各角色工具面**（`R0.1`、`R0.3`
> 右栏、`A.4`–`M.4`、`M.4` 的编排面条数、`S3` 第 1 行）；**2026-10-25 又按同一条命令重算了一遍**
> （总数 94 → **107**、Lean 关着时 104；`A.4`–`M.4` 的条数与逐件清单、`R0.1`–`R0.3`、`S3` 第 1 行），
> 其余节仍是 2026-10-18 的读数。
> ⚠️ **2026-10-26（`p210 待抬`）：本文件的实测面又整片现读重算了一遍** —— `R0.1`（handler 形态 /
> 两套口径 / 八角色共有面）、`R0.2` 标题、`R0.3`（对 `INVENTORY.md` 那张表的右栏五格）、
> `S3` 第 1 行（`cli tools` 的输出）、`A.4`–`M.4`（五格 = 总数 / `side_effect` / `external` /
> 需审批 / 逐件清单）全部按 `build_registry(...)` / `python -m agentflow.cli tools` 现算。
> **这一次的数值槽不再手抄**：它们由 `python tools/verify_role_specs.py --write` 从同一次装配
> 生成（幂等；只写数值槽与这一行日期，散文一个字不动）⇒ 下一次再进一件工具，只需要人写
> 正文 §R0 表的那一行契约，其余数字跑一条命令就全部跟上。
> 上一版那一批读数（`2026-10-27（p206）` 那几行）是别人的留痕，日期与数字一律照原样留着。
> 当前总数 **112 / Lean 关 109**（`conductor.post_task` 进册；Q15 裁定（2026-10-26）之后它登记进
> `UNIVERSAL_TOOLS` ⇒ 只读角色 C/H/V 也拿得到它：那三个角色的条数各加 1、只读泄漏清单各少一件）。
> **没有跟着重算的是**：`R0.2` 正文（9 件自注册面的逐条对账）、`A.10`–`M.10`（自检入口当次读数）、
> `M.4.2` / `M.4.3` / `M.8`、`S1` / `S2` —— 那几节仍是各自标注日期的留痕，读它们时以那一行的日期为准。
> 判据：`tests/test_role_specs_appendix_is_live.py` 把 `R0.1` / `R0.3` / `S3` 第 1 行与 `A.4`–`M.4`
> 一起对账 —— 每一处都得等于现算值，少一件、多一件、或谁把它改回手抄，都会红。
> 复跑前置：`cd D:\Incubator\agentflow` 且
> `$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`。
> 三类内容分家：**规格**在正文（判据）／**实测**在此（会过期，过期就重跑）／**历史**在
> `PROPOSALS.md`、`ROLE-SPECS-DRAFT-*.md` 等（只解释"为什么是现在这样"）。
> 权威地图：[`INDEX.md`](INDEX.md)。自检失败项的缺陷台账：[`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

---

## R0.1 [附录·实测] 114 个工具的公共事实（机械读数，现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`））

**handler 的形态**（现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`））：`functools.partial` **110** / `lambda` **4** / 具名闭包 **0**（共 114）。

```powershell
python -c "import collections,functools,tempfile,pathlib;from agentflow.store import Store;from agentflow.tools import ROLES,build_registry;d=pathlib.Path(tempfile.mkdtemp());st=Store(d);st.init();r=build_registry(store=st,workspace_root=d,roles=tuple(ROLES)).registry;c=collections.Counter('partial' if isinstance(s.handler,functools.partial) else ('lambda' if getattr(s.handler,'__name__','')=='<lambda>' else ('closure' if getattr(s.handler,'__closure__',None) else 'function')) for s in r._specs.values());print(dict(c))"
```

**两套口径的留档**（同一个包、同一版本，差的是 `store`）：

| 口径 | 命令 | 工具数 | 备注 |
|---|---|---:|---|
| A 口径（不含 store） | `build_registry(store=None, workspace_root='.', roles=schema.ROLES)` | 比 B 口径少"需要 store 才能注册"的那一族 | **本文与正文一律用 B 口径** |
| B 口径（含 store 的完整装配） | `python -m agentflow.cli tools` | **114**（Lean 关着时 111） | 权威读数 |

**八角色共有**（A–H 的交集）：25 件 —— `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 3（`ack` `escalate` `post_task`） · `fs.*` 4（`list` `read` `search` `stat`） · `manuscripts.*` 2（`list` `read`） · `program.*` 1（`list`） · `table.*` 5（`count` `get` `list` `schema` `search`） · `trace.*` 1（`children`）。

> 上表那一行是这个数在文档里的**唯一落点**：正文 §0.2 只给复跑命令，L.4 只说"与它逐件相同"。
> 它由 `tools/verify_role_specs.py --write` 现算重写；判据是附录判据里那一条逐格对账。

> ⚠️ **历史读数（留档，不构成判据）**：2026-09-26 那次装配是 **55** 个工具 / 11 个模块；
> 当时手抄的分布是 `side_effect {'read':32,'write_local':18,'none':5}`、
> `external {'none':49,'egress':4,'exec':2}`、需审批 21 / 55，且还有一个 `network: 2` 的取值。
> **那个取值现在不存在**（`agentspec.EFFECT == ("none","read","write_local")`），
> 所以任何"`network` 有几个"的问题都已经**没有取值可答**。
> 2026-10-21 那一次是 **94**；2026-10-25 是 **107**；2026-10-27（p206）是 **111**；
> 2026-10-26（本版，`p210 待抬`）是 **112**（`conductor.post_task` 进册；当时只读角色 C/H/V 被剥所以
> 它们的条数不变 —— 同一批的 Q15 裁定把它登记进 `UNIVERSAL_TOOLS` 之后，C/H/V 各加 1）。

**自注册面（9 件，不过 `build_registry` 的角色校验）**：9 个 `graph.*`（`agent_c.register_tools`）
—— **`cli tools` 的装配面里不含它们** ⇒ 引用"某角色有几个工具"时不要把它们加进去。
另两处同名面**不另算条数**：`agent_d._fallback_trace_tools` 的 3 个 `trace.*` 替身只在 D
自己构造的注册表里生效（装配面里的同名三件来自 `tools/trace_tools.py`，`roles=("C","D")`）；
`review_tools` 的 4 件写侧自 2026-10-17 起由装配器自动 `include_writers=True` 装进主表
（`roles=("H",)`）。

**一条只能在代理循环里用的工具**（真机读数，2026-10-27 `projects/dogfood-clock`）：
`clock.timer_start` 要一个**台账号** —— 到点该叫醒谁靠身份、不靠参数，所以裸调
`registry.call` 会受控拒绝（「不知道到点该叫醒谁（这不是没有任务，是没有身份）」）。
写例子时要说清这一步：它必须在代理循环里调。同一趟真机上模型自己调了
`clock.periodic_start` ×1 / `clock.timer_start` ×1 / `clock.timer_purpose` ×1 /
`clock.now` ×2 / `clock.timer_list` ×1，`out/clock/state.json` 与 `out/clock/waits.json`
都落盘，`timers` 里第一条是 `kind="program"`（问 lean 版本那一次）⇒ 这套工具在真机上是人能用的。

---

## R0.2 [附录·实测] 不经 `build_registry` 的那批工具的逐条对账（2026-10-18 记 14 件；2026-10-21 复核 ⇒ 9 件；2026-10-27 复核 ⇒ 仍是这 9 件，与总数 114 无关）

正文 §R0.2 已经把这张表写全（来源 / 位置 / 数量 / 工具 / `side_effect` / `roles` / 是否过角色校验）。
本节只登记**当次复核结论**（下面三条是 2026-10-18 的读数；14 → 9 的那次复核见正文 §R0.2）：

- 9 个 `graph.*` 的 `roles=("C","D")` —— **当次未逐字复核**（`agent_c.register_tools`）。
- 3 个 `trace.*` 替身的 `roles=("agent-C","agent-D")` **仍带 `agent-` 前缀** ——
  `install_d_tools` 直接构造 `ToolRegistry` 并 `register_function`，**不过那段校验**
  ⇒ `for_role("C")`/`for_role("D")` 永远拿不到这 3 个替身。**当次未复算**（S2 #5 仍挂"未复跑"）。
- `AgentH.install_h_tools` **不是新工具**：它把 `build_registry` 的 H 子集复制进新注册表，
  并用 `filter_readonly_h_surface` 再做一次显式拒绝 + 留痕（`refused_write_tools`）。

---

## R0.3 [附录·实测] `INVENTORY.md` / `tools.json` 的口径警告

`D:\Incubator\temp\inventory\INVENTORY.md:3` 逐字写明它普查的是 **`D:\Incubator\test\test1\`（包名 `abflow`）**，
不是本目录 `agentflow`。当次核对（2026-10-18）：该文件首行为 `# abflow 契约现状清单（机械产出）` ⇒ 口径警告**仍成立**。

**右栏读数已按 2026-10-27（p206）重测**（`python -m agentflow.cli tools` 现读；Lean 开）。旧版那一列写的是 2026-10-06 的装配读数（81 个工具、
`A26 B21 C21 D40 E24 F35 G40 H27 V14 M18`、`read 48 / write_local 28 / none 5`、
`external none 71 / egress 4 / exec 6`、审批 `32 / 81`、"只读泄漏 0"）——
那些旧值**作为历史读数留档**，**不要再引用**：

| 项 | `INVENTORY.md`（abflow） | 本文实测（agentflow，2026-10-27 p206） | 是否一致 |
|---|---|---|---|
| 工具总数 | 55 | **114**（`python -m agentflow.cli tools`；Lean 关着时 111） | ⚠️ |
| 各角色工具数 | `A20 B18 C17 D37 E21 F32 G32 H23`（§1.2） | `A52 B38 C36 D57 E39 F51 G53 H44 V28 L38 M37`（同一命令读"各角色工具数"那一行） | ⚠️ |
| `side_effect` 分布 | `read 30 / write_local 15 / none 5 / network 0`；`external`：`none 44 / egress 4 / exec 2` | **114 口径**：`read 56 / write_local 53 / none 5`；`external`：`none 104 / egress 5 / exec 5`（非 `none` 共 10 件；Lean 关着时 `read 55 / write_local 51 / none 5`、`none 104 / egress 5 / exec 2` ⇒ 7 件） | ⚠️ |
| 需审批 | 17 / 55 | **57 / 114** | ⚠️ |
| 只读角色泄漏 | 0 | **32 件**：`H` 13 件（4 件落库代理 `review.review_document` / `review.verify_fixes` / `review.report` / `review.record_finding` + 9 件通用能力：`clock.*` 的七件写工具 + `conductor.ack` + `conductor.post_task`）+ `C` 10 件（`analysis.register_report` 一件落库代理 + 同样那 9 件通用能力）+ `V` 9 件（只有那 9 件通用能力） | ⚠️ |
| 零测试工具 | 7 个（`table.list` `table.count` `table.schema` `table.search` `fs.list` `search.register` `search.download`） | 用"工具名字符串是否出现在 `tests/`"口径，**本次未复算** | ⚠️ |
| `INVENTORY` 未覆盖的 schema 对象 | 无 `Task`/`UsageEntry`/`EvalResult` | **有**（`schema.EvalResult`） | ❌ **INVENTORY 落后** |

> **因此**：凡引用 `INVENTORY.md` 的"4.x"条目，请在 `test/test1/` 下按该条目的**文本**检索，
> **不要按行号**（`agentflow` 是 `abflow` 的后继，同一处代码在两份目录里的行号不同）。
> 当次核对：`INVENTORY.md` 首行逐字为 `# abflow 契约现状清单（机械产出）`。

---

## A.4 [附录·实测] 工具面明细（52 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role A`

| 维度 | 读数 |
|---|---|
| 总数 | **52** |
| `side_effect` | `read 24 / write_local 28 / none 0` |
| `external` | `none 48 / egress 4`（`search.download` / `search.literature` / `search.providers` / `search.walk_citations`） |
| 需审批 | **31** |

**逐件清单（按模块，共 52）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `text.*` 1（`extract`） · `trace.*` 1（`children`）。

> 本节自 2026-10-27 起**五格一律现读**；旧版那几张手抄逐件表已漂过（写过 `network`、写过 "26 个工具"），所以这里只写"现读命令 + 分组清单"，不再手抄会变的分份数。

**A 拿不到**：另 62 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 15 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：29 → 37 → 45 → **49**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## B.4 [附录·实测] 工具面明细（38 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role B`

| 维度 | 读数 |
|---|---|
| 总数 | **38** |
| `side_effect` | `read 17 / write_local 21 / none 0` |
| `external` | `none 37 / egress 1`（`ocr.run`） |
| 需审批 | **21** |

**逐件清单（按模块，共 38）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `manuscripts.*` 2（`list` `read`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `program.*` 2（`list` `stop`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 1（`children`）。

> 本节自 2026-10-27 起五格一律现读（旧版手抄表已折成下面那行历史读数）。

**B 拿不到**：另 76 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 15 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：31 → **35**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## C.4 [附录·实测] 工具面明细（36 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role C`

| 维度 | 读数 |
|---|---|
| 总数 | **36** |
| `side_effect` | `read 26 / write_local 10 / none 0` |
| `external` | `none 36` |
| 需审批 | **10** |

**逐件清单（按模块，共 36）**：`analysis.*` 1（`register_report`） · `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 3（`ack` `escalate` `post_task`） · `fs.*` 4（`list` `read` `search` `stat`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `manuscripts.*` 2（`list` `read`） · `program.*` 1（`list`） · `search.*` 2（`local` `shelf`） · `table.*` 5（`count` `get` `list` `schema` `search`） · `trace.*` 5（`chain` `children` `concept` `literature` `relation`）。

> **C 的计数有两层，别把第二层加进 `cli tools`**：`cli tools --role C` 报的是走 `build_registry` 那一层；`agent_c.register_tools` 自注册的 9 个 `graph.*`（`hottest` `paths` `cold` `gaps` `svc_neighbors` `svc_relations_between` `contradictions` `structural_duplicates` `check_conflict`）**不在它的计数里**，也不进 `build_registry` 的角色校验（见 §R0.2）。旧版本节写"21 = 第一层 19 + 自注册 9"，那道算术不成立（19+9≠21）。

**C 拿不到**：另 78 件 —— `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 17 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `fs.*` 4（`delete` `edit` `move` `write`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `program.*` 1（`stop`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 7（`dedup_check` `download` `ingest_local` `literature` `providers` `register` `walk_citations`） · `table.*` 3（`create` `delete` `update`） · `text.*` 1（`extract`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：21 → 23 → 30 → **34**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

> 那 9 件自注册的 `graph.*` 只在 `agent_c.register_tools` 自己构造的注册表里生效，既不加进上面那个总数、也不进 `build_registry` 的角色校验（§R0.2 逐条）。

---

## D.4 [附录·实测] 工具面明细（57 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role D`

| 维度 | 读数 |
|---|---|
| 总数 | **57** |
| `side_effect` | `read 30 / write_local 22 / none 5` |
| `external` | `none 57` |
| 需审批 | **22** |

**逐件清单（按模块，共 57）**：`attack.*` 4（`check_budget` `list_plans` `pick_next_subgoal` `status`） · `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `doc.*` 3（`compose_claim` `list_documents` `scan_claim`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 2（`list_findings` `scan_document`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 5（`chain` `children` `concept` `literature` `relation`）。

> 本节自 2026-10-27 起五格一律现读（旧版手抄表已折成下面那行历史读数）。

**D 拿不到**：另 57 件 —— `analysis.*` 1（`register_report`） · `attack.*` 2（`create_plan` `step`） · `conductor.*` 15 · `doc.*` 4（`build_document` `paper_compile` `register_dependency` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `review.*` 4（`record_finding` `report` `review_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：42 → 50 → **54**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## E.4 [附录·实测] 工具面明细（39 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role E`

| 维度 | 读数 |
|---|---|
| 总数 | **39** |
| `side_effect` | `read 19 / write_local 20 / none 0` |
| `external` | `none 38 / exec 1`（`verify.run_experiment`） |
| 需审批 | **20** |

**逐件清单（按模块，共 39）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 1（`children`） · `verify.*` 4（`code_hash` `evidence_for` `list_experiments` `run_experiment`）。

> **`verify.check_formal` 不在 E 的工具面里**：它的 `roles` 现读是**空集**（形式化入口归 L 的 `formal.check_formal`），E 自己的 Lean 侧写死关闭（`agent_e._support.E_LEAN_SIDE_HARD_OFF`，受控拒绝码 `formal_moved_to_l`）。E 的写面只有 `experiments` 一张表。

**E 拿不到**：另 75 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 15 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 4（`detect_verifier` `list_verifications` `read_proof` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：25 → 32 → **36**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## F.4 [附录·实测] 工具面明细（51 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role F`

| 维度 | 读数 |
|---|---|
| 总数 | **51** |
| `side_effect` | `read 24 / write_local 22 / none 5` |
| `external` | `none 50 / exec 1`（`verify.run_experiment`） |
| 需审批 | **22** |

**逐件清单（按模块，共 51）**：`attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `doc.*` 3（`compose_claim` `list_documents` `scan_claim`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `review.*` 2（`list_findings` `scan_document`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 1（`children`） · `verify.*` 5（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `run_experiment`）。

> **F 自己的写面只有 `attack_plans`**：其余写工具都是共用的（`fs.*` 的四件 + `table.*` 的三件 + `conductor.broadcast` 一类），`statements` 与 `dependencies` **都不在** F 的写集里 —— 命题由秘书 / B 登记，依赖边由 B 读 F 的证明手稿落（`specs/f.py` 的 `write_set` 是这一格的真身）。

**F 拿不到**：另 63 件 —— `analysis.*` 1（`register_report`） · `conductor.*` 15 · `doc.*` 4（`build_document` `paper_compile` `register_dependency` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 4（`record_finding` `report` `review_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 3（`list_verifications` `read_proof` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：36 → 44 → **48**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## G.4 [附录·实测] 工具面明细（53 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role G`

| 维度 | 读数 |
|---|---|
| 总数 | **53** |
| `side_effect` | `read 24 / write_local 24 / none 5` |
| `external` | `none 51 / exec 2`（`doc.paper_compile` / `verify.run_experiment`） |
| 需审批 | **24** |

**逐件清单（按模块，共 53）**：`attack.*` 4（`check_budget` `list_plans` `pick_next_subgoal` `status`） · `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `review.*` 2（`list_findings` `scan_document`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 1（`children`） · `verify.*` 5（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `run_experiment`）。

> 本节自 2026-10-27 起五格一律现读（旧版手抄表已折成下面那行历史读数）。

**G 拿不到**：另 61 件 —— `analysis.*` 1（`register_report`） · `attack.*` 2（`create_plan` `step`） · `conductor.*` 15 · `formal.*` 3（`check_formal` `formalize` `record`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 4（`record_finding` `report` `review_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 3（`list_verifications` `read_proof` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：38 → 46 → **50**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## H.4 [附录·实测] 工具面明细（44 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role H`

| 维度 | 读数 |
|---|---|
| 总数 | **44** |
| `side_effect` | `read 26 / write_local 13 / none 5` |
| `external` | `none 44` |
| 需审批 | **13** |

**逐件清单（按模块，共 44）**：`attack.*` 4（`check_budget` `list_plans` `pick_next_subgoal` `status`） · `clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 3（`ack` `escalate` `post_task`） · `doc.*` 3（`compose_claim` `list_documents` `scan_claim`） · `fs.*` 4（`list` `read` `search` `stat`） · `manuscripts.*` 2（`list` `read`） · `program.*` 1（`list`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 2（`local` `shelf`） · `table.*` 5（`count` `get` `list` `schema` `search`） · `trace.*` 1（`children`） · `verify.*` 4（`code_hash` `detect_verifier` `evidence_for` `list_experiments`）。

> **H 的 `write_local` 分两族，别混算**：① `READONLY_CALL_EXCEPTIONS['H']` 里登记的 4 件**落库代理**（`review.review_document` / `review.verify_fixes` / `review.report` / `review.record_finding`）；② `UNIVERSAL_TOOLS` 里的通用能力（`clock.*` 的写工具 + `conductor.ack`，十一个角色全体都有，业主 2026-10-26：「通用能力根本不该出现谁能用这个说法」）。`cli tools` 的"只读角色写工具泄漏"那一行把两族都打出来并标 `!! 有泄漏` —— **那是声明面的读数**；行为面由 `for_role` 挡住：H 仍拿不到 `fs.*` / `table.*` 的任何写工具。

**H 拿不到**：另 70 件 —— `analysis.*` 1（`register_report`） · `attack.*` 2（`create_plan` `step`） · `conductor.*` 17 · `doc.*` 4（`build_document` `paper_compile` `register_dependency` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `fs.*` 4（`delete` `edit` `move` `write`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `program.*` 1（`stop`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `search.*` 7（`dedup_check` `download` `ingest_local` `literature` `providers` `register` `walk_citations`） · `table.*` 3（`create` `delete` `update`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 4（`list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：31 → 38 → **42**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## V.4 [附录·实测] 工具面明细（28 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role V`

| 维度 | 读数 |
|---|---|
| 总数 | **28** |
| `side_effect` | `read 19 / write_local 9 / none 0` |
| `external` | `none 28` |
| 需审批 | **9** |

**逐件清单（按模块，共 28）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 3（`ack` `escalate` `post_task`） · `fs.*` 4（`list` `read` `search` `stat`） · `manuscripts.*` 2（`list` `read`） · `program.*` 1（`list`） · `table.*` 5（`count` `get` `list` `schema` `search`） · `trace.*` 1（`children`） · `verify.*` 3（`list_verifications` `read_proof` `verify_proof`）。

> **V 的 `write_local` 不是落库代理**：全部是 `UNIVERSAL_TOOLS` 里的通用能力（`clock.*` 的写工具 + `conductor.ack`），业主 2026-10-26 口径。V 一件 `READONLY_CALL_EXCEPTIONS` 都没有 —— 它唯一的产物是 `verifications/<命题号>.jsonl` 这个**文件**，不是表。

**V 拿不到**：另 86 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 17 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `fs.*` 4（`delete` `edit` `move` `write`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `program.*` 1（`stop`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `table.*` 3（`create` `delete` `update`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 5（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `run_experiment`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：15 → 22 → **26**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## L.4 [附录·实测] 工具面明细（38 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`python -m agentflow.cli tools --role L`

| 维度 | 读数 |
|---|---|
| 总数 | **38** |
| `side_effect` | `read 17 / write_local 21 / none 0` |
| `external` | `none 35 / exec 3`（`formal.check_formal` / `formal.formalize` / `formal.record`） |
| 需审批 | **22** |

**逐件清单（按模块，共 38）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 5（`ack` `broadcast` `escalate` `post_task` `retire_child`） · `formal.*` 3（`check_formal` `formalize` `record`） · `fs.*` 8（`delete` `edit` `list` `move` `read` `search` `stat` `write`） · `manuscripts.*` 2（`list` `read`） · `program.*` 2（`list` `stop`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `trace.*` 1（`children`）。

> **L 的工具面 = 通用能力 + 三件 `formal.*`**：`formal.formalize` / `formal.check_formal` / `formal.record` 只挂给 L（`formal_tools._ROLES_L == ("L",)`）；写集只有 `experiments` 一格（`record` 落 `method="formal"` 的行），刻意**不含** `statements` ⇒ "L 绕过 V 的签给命题升档"在结构上不可能。**Lean 关着时这一节是 0 件**（`leanscope.LEAN_ONLY_ROLES` 决定这个角色存不存在，不是它的工具被剥）。

**L 拿不到**：另 76 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `conductor.*` 15 · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `text.*` 1（`extract`） · `trace.*` 4（`chain` `concept` `literature` `relation`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

---

## M.4 [附录·实测] 工具面明细（37 件）

**现读于 2026-10-26（p210，`AGENTFLOW_LEAN_ENABLED=1`）**：`build_registry(...).for_role("M")`（`cli tools --role` 的 choices 里没有 M）

| 维度 | 读数 |
|---|---|
| 总数 | **37** |
| `side_effect` | `read 17 / write_local 20 / none 0` |
| `external` | `none 37` |
| 需审批 | **20** |

**逐件清单（按模块，共 37）**：`clock.*` 9（`alarm_start` `now` `periodic_start` `periodic_stop` `timer_cancel` `timer_list` `timer_purpose` `timer_start` `wait_any`） · `conductor.*` 20 · `fs.*` 6（`edit` `list` `read` `search` `stat` `write`） · `program.*` 2（`list` `stop`）。

> **M 的工具面是三层相加**，拆开写才看得出哪一层在变：编排面 / 通用时钟 / 文件面白名单。**没有** `fs.delete` / `fs.move`（一个真删、一个换位置，都不可逆），也不碰任何表。三个拆项各是几件，见正文 §M.4 标题里那个等号右边（与本节同一批数，都由 `--write` 现算重写）。

**M 拿不到**：另 77 件 —— `analysis.*` 1（`register_report`） · `attack.*` 6（`check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step`） · `doc.*` 7（`build_document` `compose_claim` `list_documents` `paper_compile` `register_dependency` `scan_claim` `write_mapping`） · `formal.*` 3（`check_formal` `formalize` `record`） · `fs.*` 2（`delete` `move`） · `graph.*` 4（`build` `neighbors` `relations_between` `stats`） · `lit.*` 7（`admit` `admit_all` `overlap_check` `stage_add` `stage_list` `stage_reject` `stage_withdraw`） · `manuscripts.*` 2（`list` `read`） · `ocr.*` 3（`backends` `detect_text_layer` `run`） · `research.*` 5（`list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note`） · `review.*` 6（`list_findings` `record_finding` `report` `review_document` `scan_document` `verify_fixes`） · `search.*` 9（`dedup_check` `download` `ingest_local` `literature` `local` `providers` `register` `shelf` `walk_citations`） · `table.*` 8（`count` `create` `delete` `get` `list` `schema` `search` `update`） · `text.*` 1（`extract`） · `trace.*` 5（`chain` `children` `concept` `literature` `relation`） · `verify.*` 8（`code_hash` `detect_verifier` `evidence_for` `list_experiments` `list_verifications` `read_proof` `run_experiment` `verify_proof`）（逐件见正文 §R0 全表；本节只给条数）。

> 历史读数：21 → 30 → **34**（2026-10-21 / 10-25 那两次重算的链；逐条旧叙述已折成这一行，本节自 2026-10-27 起五格一律现读）。

---

## M.4.2 [附录·实测] M 的"召唤面"要过的策略判定 + `REFUSAL_REASONS`

**现读于 2026-10-27（p206）**：`REFUSAL_REASONS` 的条数与词表由 `schema.REFUSAL_REASONS` 现读
（判据逐字比）。下面那张"9 道判定"表是 `Conductor.summon` 的**调用顺序**，顺序本身没有机器读数可对账，
按代码现状描述；它每一行后面点名的"依据"都是可以对到的符号。

#### M.4.2 M 的"召唤面"要过的 9 道策略判定（按 `summon` 里的顺序）

| 序 | 判定 | 失败时 | 依据 |
|---:|---|---|---|
| 0 | `token.cancelled` / `_disposed` | `status=cancelled`, `outcome=cancelled`, **`task_id=None`，不产生新任务** | `conductor.Conductor._disposed` |
| 1 | `check_action`（角色存在？动作存在？） | `refused/unknown_role` 或 `refused/unknown_action` | `policy.check_action` |
| 2 | 参数 schema | `refused/unknown_action`（"这次没这么调"） | `conductor.Conductor.summon` |
| 3 | 深度链（从台账重建） | `refused/unknown_action` + detail | `conductor.Conductor.summon` |
| 4 | `check`：**边 / 不可召唤 / 深度 / 循环 / 扇出 / 并发 / 总量 / token 预算 / 花销预算 / 墙钟** | 见下表 | `policy.check` |
| 5 | 写 `running` 行（带 `started_at`） | — | `conductor.Conductor.summon` |
| 6 | 执行（**事务只包台账那行，不包 handler**） | 异常 ⇒ `status=failed` | `conductor.status` |
| 7 | 记账（用**本次 finish 实际写下的** tokens/usd） | — | `conductor.Conductor._charge_and_settle` |

`Refusal.reason` 的受控词表 `REFUSAL_REASONS`（`schema.REFUSAL_REASONS`，**11** 个）：

| reason | 触发 |
|---|---|
| `unknown_role` | 角色不在 `schema.ROLES` 里 |
| `unknown_action` | 该角色没有这个动作 / 父任务不存在 |
| `invalid_params` | **参数 schema 校验失败**（R-46 之后这一档单独成码，不再折进 `unknown_action`） |
| `forbidden_edge` | 策略不允许这条边（如 `C → B`）；或目标是 `NON_SUMMONABLE` |
| `depth_exceeded` | `depth > max_chain_depth`（链长；台账 4 跳 = 链上 5 个代理，第 5 个不能再派，业主 2026-10-24） |
| `fanout_exceeded` | 该任务**此刻在飞** `max_direct_children` 个直接子（只数直接子，不管隔着几层的子），且**等过之后仍然满**（口径 = 单时刻：直接子一返回就腾出名额；触顶时 `Conductor` 先等 `fanout_wait_sec`（默认 900s，所有者 2026-10-08：「只可等待子智能体返回结果」）；上限按发起方角色取，见 `policy.direct_children_limit_for`；主控那一档 = 100） |
| `concurrency_exceeded` | `running >= max_concurrency` |
| `budget_exceeded` | token / 花销预算耗尽 |
| `deadline_exceeded` | 墙钟到点（**并同时协作式取消在跑的**） |
| `cycle_detected` | `(role, action, input_key)` 已在祖先链上 |
| `not_wired` | 该角色该动作未接线（`SubagentBackend` 恒为此） |

> **当次改正**：`REFUSAL_REASONS` 现在是 **11** 个（旧文写 10 个）—— 多出来的是
> **`invalid_params`**：参数 schema 校验失败时它落 `invalid_params` 而不是 `unknown_action`
> （`conductor.py` 的 `summon` 分支与 `Refusal.reason="invalid_params"` 那一处）。
> 复跑：`python -c "from agentflow import schema as S;print(len(S.REFUSAL_REASONS),sorted(S.REFUSAL_REASONS))"`
> ⇒ `11 ['budget_exceeded','concurrency_exceeded','cycle_detected','deadline_exceeded','depth_exceeded','fanout_exceeded','forbidden_edge','invalid_params','not_wired','unknown_action','unknown_role']`。

---

## M.4.3 [附录·实测] 并发判据：写集相交 ⇒ 串行（**同一角色的不同实例除外**）

**现读于 2026-10-27（p206）**：本节讲的是**划分规则**与实例轴，没有计数值可对账；所以判据换了个形态
（判"符号与判据文件都还在"，防它悄悄消失）：`policy.waves_of` 与 `policy._same_role_other_instance` 存在、
`tests/test_scheduler.py`（实例轴的负控）与
`tests/test_agent_b_gates.py::test_i6_two_agents_write_concurrently_without_deadlock`（并发写不死锁）在。
判据：`tests/test_role_specs_appendix_is_live.py::test_m43_symbols_and_criteria_files_still_exist`。

#### M.4.3 并发判据：写集相交 ⇒ 串行（**同一角色的不同实例除外**）

- `policy.waves_of(calls, limit=…)`（`policy.waves_of`）：同一波内**写集互不相交**；
  `limit` 是单波容量（= `max_concurrency`），**"波内并发数 ≤ max_concurrency"由划分保证，
  不需要信号量兜底**。
- **实例轴（2026-09-30 加）**：`scheduler.TaskCall` 现在带一个 `instance` 标签。
  **同一角色、两边都显式给了不同标签** ⇒ 不算冲突，可以同波并发
  （`policy._same_role_other_instance`）；**没给标签或标签相同** ⇒ 照旧按角色串行
  （默认行为一个字没变，负控在 `tests/test_scheduler.py`）。
  它解决的是实测出来的结构性死结：3 个 B（都写 `literature`）会被排成 3 波串行
  （峰值真并发 = 1，"再多 B 也没用"），而数据面本来就支持并发写
  （B 的领取走 `claimed_by` + 租约；判据
  `tests/test_agent_b_gates.py::test_i6_two_agents_write_concurrently_without_deadlock`）。
  角色级 `WRITE_SETS` 的含义因此是"**这个角色的一个实例**会碰哪些表"。
- **批量入口**：`conductor.summon_many(targets=[…])`（M 专属）一次派一批，
  走 `Conductor.run_plan` ⇒ `scheduler.run_waves`；返回里带 `waves` 与 `concurrent_peak` ——
  "到底并发了没有"看这两个数，不看墙钟。
- 为什么用写集而不是依赖图（`DESIGN-CONDUCTOR.md:226-228` 逐字）：
  "依赖图需要每个动作声明前置，那会逼所有角色改签名；而写集是**从角色推出来的**（`WRITE_SETS`），
  零成本、可判定、可测。代价是它比真依赖图保守（可能少并发），但**保守的代价是多花时间，
  激进的代价是数据被改坏**。"
- **未知角色返回"整张表"而不是空集**（`capabilities.write_set_of`，`capabilities.write_set_of`）：
  "空集意味着'它什么都不写，可以和任何人并发'，**那是最危险的方向**。"
- **空写集的两种含义**（`capabilities.EMPTY_WRITE_SETS`，CS-14 / 批 R21）：
  `WRITE_SETS` 为空有两种原因，并发含义相反 —— V 写的是**文件**（`verifications/<命题号>.jsonl`）、
  没有子代理 ⇒ 真·空集，与任何人的表写集都不相交；M 的空集只是"没有逐表声明"
  （它派生的子任务可能写任何东西）⇒ 按整张表处理。上面 §0.6 的第 203/204 行早就把这两者
  分开了，而 `write_set_of` 从前把它们与"完全不认识的角色"折成同一个返回值 ⇒
  读返回值的人分不出这三种情形（批 R21 起按 `concurrent` 那一格分档）。

---

## M.8 [附录·实测] 不变式 I-1…I-10 的补核

**规格在正文 §M.8**（那张 I-1…I-10 表是判据，不在这里重复）。本节只登记**"状态"列里
唯一一个 `⚠️ 未核实`** 的补核结果：

| 项 | 旧状态 | **现读于 2026-10-27（p206）** 复核结论 |
|---|---|---|
| I-9「台账可重建：`rebuild()` 后 `tasks` 表逐字节一致」 | ⚠️ `test_rebuild.py` 是否覆盖 `tasks` 表：**未核实** | **没有专门判据**：`tests/test_rebuild.py` 共 **12** 个用例（`test_rebuild_preserves_diagnostic_fields` / `..._is_idempotent_and_keeps_tables_valid` / `..._ignores_corrupt_events_without_dying` / `..._folds_v1_concept_events_into_the_new_standard` / `..._keeps_the_stale_file_when_the_log_does_not_cover_it` / `..._removes_the_stale_file_once_the_log_covers_it` / `..._refuses_a_schema_version_other_than_the_previous_one` / `..._reports_schema_rejected_rows_by_reason_and_detail` / `..._cli_prints_the_skip_breakdown_when_there_is_one` / `..._cli_stays_quiet_on_a_clean_rebuild` / `..._reports_shape_broken_rows_and_does_not_narrow_the_except` / `..._skip_detail_keys_are_the_documented_ones`），**没有一处出现 `tasks`** ⇒ I-9 只能靠通用用例**间接**覆盖，`DESIGN-CONDUCTOR.md` 那句"逐字节一致"**仍未被专门判据钉住** |

复跑：`Select-String -Path tests\test_rebuild.py -Pattern 'tasks|def test_'` —— **2026-10-27 现读仍是
12 个 `def test_`、0 处 `tasks`**（与 2026-10-18 的结论逐字一致：I-9 至今没有专门判据，只能靠通用用例
间接覆盖）。判据：`tests/test_role_specs_appendix_is_live.py::test_m8_rebuild_coverage_row_matches`。

---

## 各角色 `.5` / `.7` / `.8` 的下沉明细 [附录·实测]

> 正文只留**主状态表**、**三态场景表**与**不变式的一句话**；下面是被下沉的
> **约束表 / 反例表 / 第二三个状态机**、**“已知会犯的错”逐条**、**不变式的代码名清单**。
> 读数带日期、不构成判据；与代码冲突以代码为准。

### A.5 [附录·实测] 下沉明细

A 产出的行有**两个**状态机。

**(a) `search_requests`（A 的输入队列）**

| 字段 | 取值 | 说明 |
|---|---|---|
| `done` | `False → True` | 唯一的状态位 |
| `claimed_by` / `lease_until` | 字符串 / ISO 时间 | 逻辑租约，防"重复干活" |
| `attempts` | 整数，上限 `lease.max_attempts=3`（`config.yaml:14`） | 超过则显式放弃并写 `last_error` |
| `outcome` | `SEARCH_OUTCOMES = ("ok","no_results","search_failed","gave_up")`（`schema.SEARCH_OUTCOMES`） | 与 `done` **正交**：`done=True` 时 `outcome` 必须说清是哪一种 |

**(b) `literature.download.status`（受控词表）**

`DOWNLOAD_STATUSES = ("ok","content_mismatch","failed","skipped")`（`schema.DOWNLOAD_STATUSES`）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `skipped → ok` | ✅ | — |
| `ok → content_mismatch` | ✅（**但必须保留字节作为证据**） | `verify.mismatch_without_evidence`（warning） |
| `ok → failed` | ✅ | — |
| `ok` 且 `path` 为空 | ❌ | `verify.ok_without_path`（warning） |

**终态**：就"一条请求"而言，`done=True` 是终态（A 的动作里没有"把 done 改回 False"）。
**但不是不可改的终态**：`literature.download.status` 可以被后续召唤改写
（`table.update` 在 A 的工具面里）。

### A.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 请求的 `result_lit_ids` 都真实存在 | `dangling_lit_ref` | error |
| 文献的 `source_request_ids` 指向真实请求 | `unknown_request_ref` | warning |
| `done=True` 必须能说清"跑出了什么" | `done_without_result` | error |
| 文献文件真的在盘上 | `file_missing` | error |
| `download.status="ok"` 必须有 `path` | `ok_without_path` | warning |
| `content_mismatch` 必须有证据 | `mismatch_without_evidence` | warning |
| 命中校验为 `mismatch` 的文献不许被消化（§2 R1b / §16 P2） | `mismatch_literature_processed` | error |
| `partial` 停在中间态要被看见 | `partial_match_processed` | warning |
| ID 唯一、无空洞、counters 不落后 | `duplicate_id` / `id_gap` / `counter_behind` / `counter_overflow` | error×3 / warning |
| 路径不逃逸工作区 | `path_escape` | error |

### A.7 [附录·实测] 下沉明细

**A 已知会犯的错**（引 `LESSONS.md` P1–P16 与 INVENTORY）：

| 模式 | 本项目的实例 | 出处 |
|---|---|---|
| P3 缺省折叠 | `_literature_rows` 吞异常 ⇒ 判重报"不是重复" | `tools.search_tools._literature_rows`；INVENTORY 4.3(a)③ |
| P13 恒值计数器 | `ARunResult.gave_up` 曾**恒为 0**（第一次失败就 `done`，放弃分支永不执行） | `LESSONS.md` P13；`draft/13` §8.7 |
| P1 字符串约定失配 | Crossref `select` 用 `abst`（应 `abstract`）→ 三模式全 400；`language` 是合法字段但不可 `select` | `LESSONS.md` P1；`README.md:156-159`（**已修复并联网复验**） |
| P14 外部契约只能实测 | `.pdf` URL 返回 **12.4 MB HTML**（后缀与状态码两条朴素策略同时失败） | `LESSONS.md` P14 / N19 / N20；`README.md:166-171` |
| P8 规则覆盖缺口 | `precise` 模式曾召回为 0（判据错，不是"本来就少"） | `README.md:160-165`（已修） |

### B.5 [附录·实测] 下沉明细

**终态**：`processed=True` 且至少有一条 `relations` 行，即 B 的终态。
**但关系行本身不是终态**：`relations.status` 可变（`active`/`suspect`/`rejected`）。

**(b) `relations.status`**

`RELATION_STATUS = ("active","suspect","rejected")`（`schema.RELATION_STATUS`）。

| 从 → 到 | 允许？ | 触发条件 | 谁拦 |
|---|---|---|---|
| `active → suspect` | ✅ | 写入期矛盾闸门命中（`conflicts_detected`） | `interactions.check_conflict` |
| `suspect → active` | ✅ | 定向重抽取后引文回验通过 | `relations_duplicate` / `resolve` 路径 |
| `any → rejected` | ✅ | 引文回验失败 / 人工剔除 | — |
| `rejected → active` | ✅（技术上） | 但**下游引用会变**：`documents` 引用 `rejected` 关系会被 verify 报 | `verify.citation_to_retracted_relation`（error） |
| 删除关系行 | ❌ | 会让 `documents` 的 `rel:` 引用悬空 | `verify.dangling_citation`（error） |

> **`suspect` 没有复核流程**（`README.md:173-174` 逐字）：
> "关系被标 `suspect` 后只是留在表里等人看，本原型没有做复核 UI/命令。"
> **本次核对：仍然如此**（未在 `agent_*.py` 里核到 `suspect` 的批量复核入口）。

**(c) `reprocess_requests.status`**

`REPROCESS_STATUSES = ("pending","done","rejected")`（`schema.REPROCESS_STATUSES`）。

| 迁移 | 允许？ | 上限 |
|---|---|---|
| `pending → done` | ✅ | — |
| `pending → rejected` | ✅ | 必须写原因（`REPROCESS_REASONS`，`schema.REPROCESS_REASONS`） |
| 同关系被重抽取次数 | ≤ `max_reprocess_per_relation = 2` | `interactions.admit_reprocess_request` |

### B.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| `concept_ids` 升序去重且 ≥ 2 个 | `unsorted_concepts` / `too_few_concepts` | error |
| 概念代号真实存在 | `dangling_concept` | error |
| `concept_group_key` 与 `concept_ids` 一致 | `stale_group_key` | error |
| `lit_id` 存在且该文献 `processed=true` | `dangling_lit` / `lit_not_processed` | error |
| 页码 `start ≤ end` | `bad_page_range` | error |
| 同概念组内无逐字重复引文 | `duplicate_quote` / `near_duplicate` | error / warning |
| `related_concepts` 与从关系表重算一致 | `related_drift` | warning |
| `related_concepts` 升序、不含自身、不悬空 | `unsorted_related` / `self_related` / `dangling_related` | error |
| 数组字段已声明集合/序列（FC-05） | `undeclared_array_field` | error |
| `--deep`：每条引文回到原文逐字核 | `quote_not_found` / `empty_quote` / `no_text_layer` / `not_found_page_unknown` / `quote_state_changed` | error / warning |

### B.7 [附录·实测] 下沉明细

**B 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P7 校验器与写入方参数不一致 | `agent_b` 读 config，`verify --deep` 曾硬编码 `widen=1` ⇒ **假报警** | `LESSONS.md` P7；`cli.cmd_verify` 已修 |

C 的产出有两类，状态语义完全不同。

**(a) `analysis_reports`（C 的产出登记行）**

| 字段 | 取值 | 硬约束 |
|---|---|---|
| `kind` | `REPORT_KINDS = ("hottest","paths","cold","gaps")`（`schema.REPORT_KINDS`） | `handle()` 可以返回 `kind="unknown"`，**该值不在词表里** ⇒ docstring 明写"**不可落库**"（`capabilities.CAPABILITIES`） |
| `markdown_path` / `abs_path` | 相对/绝对路径 | `verify.report_file_missing`（warning）：文件不在盘上报 |
| `truncated` | `bool` | 预算截断必须留痕（FC-10 判据） |
| `warnings` | `list[str]` | — |

| P16 修复过头 | 激活"仅标题匹配"第 3 轮时**必须同时补年份容差**，否则教材第 1 版与第 3 版被合并 | `LESSONS.md` P16 |
| P8 规则覆盖缺口 | 代词黑名单**只在 `len(words)==1` 时生效** ⇒ `This paper` / `when W` 全部通过 | `LESSONS.md` P8 |
| P14 外部契约 | 下载到的 `.pdf` 其实是 12.4 MB HTML ⇒ 网页导航文字被当成概念落库 | `LESSONS.md` P14；`README.md:166-171` |
| P4 检测到了却没消费 | 下载器**正确**打了 `content_type_mismatch`，B 仍照常抽取 | `LESSONS.md` P4；`tests/test_download_handoff.py`（7 例）守住 |

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| 新建一行 | ✅ | — |
| 改已有报告行 | ❌ | C 的能力表里**没有** update 类动作（`capabilities.CAPABILITIES`） |
| 落库 `kind="unknown"` | ❌ | `schema.REPORT_KINDS` 校验 + docstring 明写 |

**(b) 图上的"结论"（不是行，是 `payload`）**

| 结论 | 三态形态 | 判据 |
|---|---|---|
| `graph.gaps` | `verdict` 二元（"确实有"/"证据不足"）+ `candidate_gaps` + **`veto` 列表与 `score` 分离** | FC-26 |
| `graph.cold` | `isolated`（`degree==0`）**单独一类**："**'没人研究'和'没人连接'是两件事**" | `LESSONS.md` M7 / E8 |
| `graph.contradictions` | `strong_count` / `weak_count` **分开**；`method="literal"` + `method_note` 声明假阳性 | `LESSONS.md` P 附录；`draft/13` §8.1 |
| `graph.structural_duplicates` | `proposal ∈ {merge, review}`；`truncation_notice` **与 `candidates` 分开** | FC-26 / 自检断言 |
| `graph.svc_*` | `checked` / `empty` / `reason` 三态齐备 | FC-01 |
| `graph.build` / `graph.stats` | **三态位"无"**（INVENTORY 总表）| ⚠️ **未落地：这两个工具没有 `checked` 位** |

### C.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 报告 markdown 文件存在 | `report_file_missing` | warning |
| 报告行 ID 唯一 | `duplicate_id` | error |
| 数组字段已声明 | `undeclared_array_field` | error |
| **C 不能写知识表** | 由 `capabilities.assert_capabilities()` 的**只读角色写集例外**断言保证（`capabilities.assert_capabilities`） | 导入期 `AssertionError` |
| **C 的工具面 1 个写工具**（`analysis.register_report`，READONLY_CALL_EXCEPTIONS['C'] 逐条登记） | `tools.base.ToolRegistry.for_role` 结构性剥离 + `role_filter_notes` 留痕 | 实测 1（2026-10-20） |
| **C 不召唤任何角色**（它的汇报 = 返回值） | `ALLOWED_EDGES["C"] == frozenset()`（`capabilities.ALLOWED_EDGES`；2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C） | 静态表 |

### C.7 [附录·实测] 下沉明细

**C 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P12 恒值/死代码 | ~~`graph.neighbors` 的裸列表形状~~ ✅ **已修（本轮）**：有界层加在工具层，`RelationGraph.neighbors` 保持裸 list（有证据） | INVENTORY 4.7⑧；`test_tools_attack_graph_fixes.py::test_relation_graph_neighbors_stays_a_plain_list` |
| P9 文档漂移 | `graph.neighbors` / `graph.relations_between` 命名冲突：**服务版已改名 `graph.svc_*`**（low-level 名字仍被占用，`agent_c.py` 的注释记录了这次改名）；本节 §C.4 的契约已按实现更正 | INVENTORY 4.5#11；`test_core_audit_abc_cli.py::test_service_tool_names_resolve_the_documented_collision` |
| P14 外部契约 | `detect_contradictions` 的 `only_a != only_b` 逻辑错误：25 条真实关系上报出 6 条 `suspect`（24%），**没有一条是真矛盾** | `draft/13` §8.1 |
| P6 派生态当输入 | `concept_pair_key` 读了不存在的字段名（表里是 `concept_group_key`）⇒ 对**直接从表里读出来的行**恒返回 `[]`，**完全静默** | `draft/13` §8.2；`interactions.draft` 的注释逐字记录 |

### D.5 [附录·实测] 下沉明细

**关键约束**（`schema.py` 交叉检查，FC-04 判据②）：

| 状态 | 必须满足 | 违反时 |
|---|---|---|
| `needs_evidence` | `waiting_request_ids` **非空** | schema `ValueError` |
| `dropped` | `notes` **非空** | schema `ValueError` |
| `answered` / `dropped` | `waiting_request_ids` **应为空** | `verify.stale_waiting`（warning） |

**为什么非法迁移必须 fail 而不是静默接受**（`tools.research_tools.research_set_status` 逐字）：
"如果 `answered → open` 被放行，'已给出结论'这件事就不再是终局，
报告与台账之间会永久性地互相矛盾，而**没有任何一处会报错**。"

**D 的 `research()` 只处理 `researching`** —— 这正是 `LESSONS.md` P2
（状态机缺边）的原始现场：曾经「证据足够」这一支什么都不做，于是问题永远停在
`open`，而 `research()` 只处理 `researching` ⇒ **永远不被研究，报告里也没有证据**。
修法是新增 `consider()` 完成路由（足够 → `researching`；不足 → 提问）。

### D.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 概念/关系/文献/请求引用闭合 | `dangling_concept_ref` / `dangling_relation_ref` / `dangling_lit_ref` / `dangling_request_ref` | error |
| 终态不留等待集 | `stale_waiting` | warning |
| 研究问题不建立在被否关系上 | `question_based_on_retracted_relation` | warning |
| `research_request_ledger.json` 一致性 | `ledger_corrupt` / `ledger_bad_row` / `ledger_dangling_question` / `ledger_dangling_request` / `ledger_drift` | error×4 / warning |
| 实验/计划的 `for_question_id` 真实存在 | `dangling_question_ref`（experiments / attack_plans 两处） | error |

**(a) `Experiment` 的二维状态（结果 × 证据等级 × 否定分类）**

| 字段 | 取值 | 约束 |
|---|---|---|
| `method` | `EXPERIMENT_METHODS = ("numeric","symbolic","exhaustive_search","formal")`（`schema.EXPERIMENT_METHODS`） | 受控 |
| `evidence_kind` | `EVIDENCE_KINDS = ("proof","cross_check","heuristic")`（`schema.EVIDENCE_KINDS`） | **计算类拿不到 `proof`** |
| `result` | `EXPERIMENT_RESULTS = ("supports","refutes","inconclusive")`（`schema.EXPERIMENT_RESULTS`） | 受控 |
| `negation_kind` | `NEGATION_KINDS = ("disproved","not_proved","not_searched_here","no_local_evidence")`（`schema.NEGATION_KINDS`） | 受控 |
| `verifier_subject_key` | 字符串 | **`evidence_kind="proof"` 时必填**（`schema.Experiment.validate`）："否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'" |
| `counterexample` | 结构 | `result="refutes"` 时**必须给**（`verify.refutation_without_counterexample`，error） |
| `code_hash` | 字符串 | 必须有（`verify.unhashed_experiment_code`，error） |
| `for_question_id` | 编号（六位，旧四位仍可读） | 必须存在（`verify.dangling_question_ref`，error） |

### D.7 [附录·实测] 下沉明细

**D 已知会犯的错**：

### E.5 [附录·实测] 下沉明细

**允许的迁移**（由 `schema.Experiment.validate` 与 `verify` 共同硬拦）：

| 从 → 到 | 允许？ | 谁拦 |
|---|---|---|
| `supports` + `evidence_kind="cross_check"` → 计划 `closed` | ❌ | `verify.proof_claim_rests_on_weaker_evidence`（error）；自检实测："只有数值证据却标 closed ⇒ schema 抛（FC-22）" |
| `supports` ⇒ `negation_kind="not_proved"` | ✅ | 自检实测通过（"result=supports ⇒ negation_kind=not_proved"） |
| `refutes` ⇒ `negation_kind="disproved"` | ✅ | 但必须给 `counterexample` |
| `inconclusive` ⇒ `negation_kind="no_local_evidence"` | ✅ | 自检实测（崩溃/超时/无结论行三条路径） |
| `evidence_kind="proof"` 但无 `verifier_subject_key` | ❌ | `schema.verifier_subject_key` 抛 |
| 依赖 `status="closed"` 而 `experiment.result="inconclusive"` | ❌ | `verify.closed_dep_on_inconclusive_experiment`（error） |

**终态**：`Experiment` 行**写入即终态**（无 update 动作）。

### E.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| `for_question_id` 存在 | `dangling_question_ref` | error |
| 证据等级不许过度声称（FC-22） | `evidence_kind_overclaim` | error |
| 脚本必须有 `code_hash` | `unhashed_experiment_code` | error |

**(a) `attack_plans.status`**

`ATTACK_STATUSES = ("open","attacking","progress","supported_not_proved","stalled","resolved","abandoned")`（`schema.ATTACK_STATUSES`）。

| 状态 | 终态？ | 判据 |
|---|---|---|
| `open` | 否 | 刚立项 |
| `attacking` | 否 | 有子目标 `in_progress` |
| `progress` | 否 | 本轮有推进 |
| `supported_not_proved` | **是**（`tools.attack_tools.TERMINAL_STATUSES` 未列，但 `agent_f.AgentF._deploy_e` 会写它） | 全部子目标 `closed`/`supported_not_proved` 且**无任何 `proof`** |
| `stalled` | **是**（`TERMINAL_STATUSES` 含它） | 连续 3 轮无进展 或 轮数用尽 |
| `resolved` | **是** | 有 `proof` 级证据 |
| `abandoned` | **是** | 人/上层放弃 |

| `refutes` 必须给反例 | `refutation_without_counterexample` | error |
| 稿件不得把 `cross_check` 当 `proof` | `proof_claim_rests_on_weaker_evidence` | error |
| `closed` 的依赖不得指向 `inconclusive` 实验 | `closed_dep_on_inconclusive_experiment` | error |
| 同 `claim_key` 同口径的数字不许冲突 | `eval_duplicate_conflicting` | error |
| 路径不逃逸工作区 | `path_escape` | error |

### E.7 [附录·实测] 下沉明细

**E 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P14 / FC-07 副作用声明 | `verify.run_experiment` 声明 `write_local` 但**跑子进程且继承完整环境**；`verify.detect_verifier` 声明 `none` 却 `subprocess.run` | INVENTORY 4.4（7 处不一致中的 2 处） |
| P9 文档漂移 | `verify.detect_verifier` docstring 说 `checked=False` 只表示"探测本身没做成"，但实现里 `"checked": True` 是**硬编码**的，没有任何代码路径能返回 `False` | INVENTORY 4.5#1 |
| P9 文档漂移 | `verify.check_formal` 的 `summary` 写"把命题交给形式化检查器核验"，而主路径返回 `fail(kind="not_implemented")` | INVENTORY 4.5#2 |
| P1 路径判据两份 | `verify_tools._resolve`（拒绝工作区内绝对路径）vs `AgentE._resolve`（**接受**）⇒ `verify.code_hash` 会拒绝一个 `run_experiment` 乐意执行的路径 | INVENTORY 4.7⑩ |
| P3 返回值契约 | `verify.check_formal` 无后端时 `res.ok is True`（`checked=False`）⇒ **只看 `res.ok` 会误读** | INVENTORY 4.3(c) |

### F.5 [附录·实测] 下沉明细

> ⚠️ **两处"终态"名单不一致**（**本次实测发现**）：
> `attack_tools.TERMINAL_STATUSES = ("resolved","abandoned","stalled")`（`tools.attack_tools.TERMINAL_STATUSES`）
> **不含 `supported_not_proved`**，而 `schema.ATTACK_STATUSES` 有它、`agent_f.AgentF._deploy_e` 会写它。
    [PASS] 终止 ⇒ stalled
    [PASS] 轮数不超过 max_rounds
    [PASS] best_partial 非空（且如实）
    [PASS] 停止路径写清楚了（提前停止 或 轮数用尽）
    [PASS] stalled 后不再推进（终态不可重入）
```

**(b) 子目标 `Subgoal.status`**

`SUBGOAL_STATUSES = ("todo","in_progress","supported_not_proved","closed","blocked","dropped")`（`schema.SUBGOAL_STATUSES`）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `todo → in_progress` | ✅ | — |
| `in_progress → closed` | ✅ **仅当有 `proof` 级证据** | FC-22；自检实测 |
| `in_progress → supported_not_proved` | ✅（只有 `cross_check` 时唯一合法终点） | `agent_f._subgoal` |
| `in_progress → blocked` | ✅（**必须写 `blocked_reason`**） | `schema`；自检实测："卡点写进 `blocked_reason`（不许静默卡住）" |
| `closed → in_progress` | ❌（终态不可重入，自检实测） | `agent_f._subgoal` |
| `blocked → in_progress` | ✅（若卡点解除） | — |

**(c) `Subgoal.owner`**

`SUBGOAL_OWNERS = ("F","A","B","C","D","E","G")`（`schema.SUBGOAL_OWNERS`）。
**注意：`H` 不在其中** —— 审校者不能被派活给 F 的攻坚计划
（与"F 不能召唤 H"一致：`ALLOWED_EDGES["F"]` 里没有 H）。

### F.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| `for_question_id` 存在 | `dangling_question_ref` | error |
| `parent_plan_id` 存在 | `dangling_plan_ref` | error |
| `experiment_ids` 存在 | `dangling_experiment_ref` | error |
| `stalled` 必须写 `best_partial` | `stalled_without_partial` | error |
| `blocked` 子目标必须写 `blocked_reason` | schema `validate()` | `ValueError` |
| `history` 轮次单调不减 | `schema.AttackPlan.validate`（`schema.AttackPlan.validate`，据 `draft/13` §7 FC-18 行） | `ValueError` |
| 预算四类键齐全 | `attack.check_budget` + `schema.AttackPlan.budget`（`schema.AttackPlan` 缺即抛） | `ValueError` |

### F.7 [附录·实测] 下沉明细

**F 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P1 字符串约定 | `TERMINAL_STATUSES` 与 `ATTACK_STATUSES` 不同步（`supported_not_proved` 缺席） | 本次实测（`tools.attack_tools.TERMINAL_STATUSES` vs `schema.ATTACK_STATUSES`） |
| P3 折叠 | `can_derive` 的 `blocked_by="incomplete"` 表示"没检查" | INVENTORY 4.5#12 |
| P10 降级缺失 | `_deploy_e` 曾没有降级路径 | `draft/13` §8.6 |
| P14 外部契约 | `attack.check_budget` 对"没给预算"给 `checked=False`，而 `AgentF.create_plan` 对**同一个输入**静默改用 `DEFAULT_BUDGET` —— 同一个输入在两层被当成两件事 | INVENTORY 6.4 |
| FC-07 副作用 | `attack.step` 经 `_deploy_e` 跑 E 的脚本子进程 | INVENTORY 4.4 |

### G.5 [附录·实测] 下沉明细

**硬拦**（`tools.review_tools.review_document` / `tools.review_tools.verify_fixes`）：

```text
review_document: target_status = "accepted" if (scan["error_count"] == 0 and dep_checked) else "in_review"
                 （判 accepted 之后**紧接着签一条** —— 见下）
verify_fixes:    同样的前提，**外加一条**（`R-59`，2026-09-29）：
                 台账里必须**已有签名钉住当前这一版内容**（`signatures.signed_revision`）；
                 没有 ⇒ 改置 "in_review" 并在 reason 里逐字写明"内容已变，需重新 review 才能重新接受"
```

**逐字注释**（`review_document`）："不许在这个前提下判 accepted"。

> **`verify_fixes` 那一条为什么必需**：它原来与 `review_document` 用同一个公式 ⇒
> "G 改稿 → H 复审通过"会留下**状态 accepted + 签名钉旧版本**，`verify_all` 报
> `stale_signature`（"改稿之后旧审批不许沿用"，`draft/29` §8.8.4）。口径取的是
> **"接受 = 有一次针对这一版的审+签"**，而 `verify_fixes` 不是一次审（它只重跑旧发现的
> 对应检查，不重判全部判据）⇒ 它不签发，只把状态推到 `in_review`。
> 想让它回到 `accepted`，再走一次 `review`（H 的唯一签发入口）。

**(b) `dependencies.status`**

`DEP_STATUSES = ("closed","dangling","external_unavailable","refuted","disputed")`（`schema.DEP_STATUSES`）。
后两档是 `draft/37` §16 P1 加的（§8/§9 的矛盾与"文献错了"两个场景的落点）。

| 迁移 | 允许？ | 约束 |
|---|---|---|
| `→ closed` | ✅ **仅当** `source_lit_id`/`source_experiment_id` 真实存在 | `doc.register_dependency` 真的去核 `literature`/`experiments` 表 |
| `→ dangling` | ✅ | **必须写 `status_reason`** |
| `→ external_unavailable` | ✅ | **必须写 `status_reason`**（"本项目拿不到来源"是已知边界，降为 warning） |
| `→ refuted` | ✅ | **必须写 `status_reason`**（这条引用为什么被证否）。`verify.refuted_dependency_in_use`（error）—— 压在它上面的结论必须一起降档或撤回 |
| `→ disputed` | ✅ | **必须写 `status_reason`**（争议在哪、等谁裁决）。`verify.disputed_dependency_in_use`（warning，已知未裁决）；`draft/37` §16 P3 的**收工门**把未裁决的 `disputed` 当拦路条件（交付口径比 verify 更严，两处不同是刻意的） |
| `closed` 但指向文献不存在 | ❌ | `verify.dangling_dep`（error） |
| `closed` 但指向 `inconclusive` 实验 | ❌ | `verify.closed_dep_on_inconclusive_experiment`（error） |
| `proof` 级断言挂在 `refuted` 依赖上 | ❌ | `verify.proof_claim_on_refuted_dependency`（error） |
| `proof` 级断言挂在 `disputed` 依赖上 | ❌ | `verify.proof_claim_on_disputed_dependency`（error） |

**(c) `documents.claims` 的字段级状态**（不是行状态，是**断言**的状态）

| 字段 | 受控值 | 硬约束 |
|---|---|---|
| `evidence_kind` | `("proof","cross_check","heuristic")` | `cross_check` **必须**带 `disclaimer` |
| `is_negative` | `bool` | `True` 时**必须**给 `negation_kind`（自检实测："'未证明'与'已证否'必须分开"） |
| `citations` | `list[str]` | **非空**（"没有引用的断言不允许进入稿件"） |
| `claim_id` | 字符串 | 不许重复（G 侧检查） |
| `section` | 字符串 | 必填 |

### G.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 断言必须有引用 | `unsupported_claim` | error |
| 引用必须能解析（`rel:` / `lit:` / `exp:` / `eval:`） | `dangling_citation` | error |
| 未知引用种类 | `unknown_citation_kind` | warning |
| 不得引用被否关系 | `citation_to_retracted_relation` | error |
| 引用 `suspect` 关系 | `citation_to_suspect_relation` | warning |
| 不得过度声称（FC-22） | `overclaim` / `proof_claim_rests_on_weaker_evidence` | error |
| `proof` 断言的所有依赖必须闭合 | `proof_claim_with_unclosed_dependency` | error |
| `proof` 断言不得挂在被证否的依赖上（§9） | `proof_claim_on_refuted_dependency` | error |
| `proof` 断言不得挂在尚未裁决的依赖上（§8） | `proof_claim_on_disputed_dependency` | error |
| 依赖悬空 | `dangling_dep`（`external_unavailable` 降为 warning） | error / warning |
| 依赖本身被证否 / 有争议 | `refuted_dependency_in_use` / `disputed_dependency_in_use` | error / warning |
| 命题的出处（文献 / 稿件）必须存在 | `statements` 的 `dangling_lit_ref` / `dangling_doc_ref` | error |
| 承重链不得缺环（`derived_from`） | `dangling_stmt_ref` | error |
| `proof` 级命题不得压在不可用的命题上 | `proof_stmt_on_unusable_stmt`（`disputed` 降 warning） | error / warning |
| `active` 的文献命题必须逐字回验过 | `active_stmt_quote_unverified` | warning |
| `closed` 依赖不得指向 `inconclusive` | `closed_dep_on_inconclusive_experiment` | error |
| 依赖的 `used_by` 指向的稿件存在 | `dangling_doc_ref`（经 review_findings）；**未核到直接的 `used_by` 检查** | ⚠️ 未核实 |
| 数组字段已声明 | `undeclared_array_field` | error |

### G.7 [附录·实测] 下沉明细

**G 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P4 检测到了却没消费 | `doc.build_document` 可落库不存在的引用 | INVENTORY 4.3(a)② |
| P7 两套判据 | `scan_claim` 与 `review.scan_document` 重复检查**且已漂移**（H 侧不检查非法 `evidence_kind` / `negation_kind` / "非否定断言带否定分类"；G 侧没有 `claim_id` 重复与 `dangling_dep`） | INVENTORY 4.5#10 |
| P9 文档漂移 | `review_tools.py` 模块 docstring 声称"判据只有一份…本模块**不另写一套检查**" | INVENTORY 4.5#10 |
| — | **`agent_g` 的自检块当前失败**（见 G.10） | 本次实测 |

### H.5 [附录·实测] 下沉明细

**(b) `documents.status` 由 H 驱动**

见 §G.5(a)。**关键硬拦**：`accepted` 只在 `error_count == 0` **且** `dep_checked` 时才允许。

**(c) `verdict`（H 的返回，不是状态）**

`verdict ∈ {accepted, accepted_with_warnings, rejected, unverified, unresolved_review}`
（`tools.review_tools.scan_document` / `tools.review_tools._resolve_deps` / `tools.review_tools.verify_fixes`）。

| verdict | 判据 |
|---|---|
| `accepted` | `error_count == 0` **且** `dep_checked` |
| `accepted_with_warnings` | 无 error，有 warning |
| `rejected` | 有 error |
| `unverified` | **依赖闭合没查**（`dep_checked=False`） |
| `unresolved_review` | 到轮数上限仍有 open error |
| ⚠️ **`review.scan_document`（工具）不看 `dep_check.checked`** | INVENTORY 4.3(a)①：`verdict = "rejected" if errors else ("accepted_with_warnings" if warnings else "accepted")`（`tools.review_tools.verdict`）**完全没读 `dep_check["checked"]`** ⇒ 同一个返回值里 `dep_check` 说"没查"、`verdict` 说"通过" |

### H.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 发现指向的稿件存在 | `dangling_doc_ref` | error |
| 发现必须带证据 | `finding_without_evidence` | error |
| `accepted` 稿件不得有 open error | `accepted_with_open_error` | error |
| `proof` 断言的依赖闭合（H 是复核方） | `proof_claim_with_unclosed_dependency` / `proof_claim_on_refuted_dependency` / `proof_claim_on_disputed_dependency` | error |
| 证据等级不得过度声称 | `overclaim` / `proof_claim_rests_on_weaker_evidence` | error |
| **H 的写面只有 4 件已登记的落库代理** | `READONLY_CALL_EXCEPTIONS['H']`（`review.review_document` / `review.verify_fixes` / `review.report` / `review.record_finding`）+ `for_role` 把其余写工具结构性剥离 | 实测 4 件 `write_local`（声明面）/ 0 件（`fs.*`/`table.*` 写工具） |
| **H 只召唤 `A E G`** | `ALLOWED_EDGES["H"] == {"A","E","G"}` | 静态表 |

### H.7 [附录·实测] 下沉明细

**H 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P3 折叠（**最严重**） | `review.scan_document` 给出 `verdict="accepted"` 而依赖闭合**从未检查** | INVENTORY 4.3(a)①；`tools.review_tools.scan_document` vs `:171-176` |
| P7 两套判据 | `scan_document` 把 `scan_claim` 的 4 组检查逐条复制且**已漂移** | INVENTORY 4.5#10 |
| P9 文档漂移 | 模块 docstring 声称"本模块**不另写一套检查**" | INVENTORY 4.5#10 |
| **修复过头**（P16 的反例） | 修好后**没有借机放宽断言**，而是把附录标题改成明确写"未达正文标准、不作为证据"，并把断言换成段落级解析 ⇒ **测试反而更强** | `LESSONS.md` P11；`draft/11` §11.3 |

### V.5 [附录·实测] 下沉明细

**(b) 台账行的字段（`verifications.record_verification`）**

`verification_id`（`v-NNNN`，按文件内顺序由脚本发）/ `statement_id` / `verifier` /
`verdict` / `defect_step` / `quote` / `why` / `findings[]`（每项 `{level, step, kind, detail}`）/
`unresolved_errors` / `proof_sha256` / `proof_chars` / `round` / `used_faces` /
`submission_id` / `at` —— **`at` 与 `proof_sha256` 是"审的是哪一份、哪一刻"的凭据**。

**(c) `verdict` 是结论，不是状态**

`verdict ∈ {成立, 有毛病, 看不出来}`（`verifications.VERDICTS`）。
它**不落任何表**（没有 `statements.verdict` 这一格被 V 写）；下游读的是台账文件那一行。

### V.8 [附录·实测] 下沉明细

| 不变式 | 检查项名 / 判据 | 级别 |
|---|---|---|
| **V 的工具面 0 个写工具** | `for_role("V")` 结构性剥离 + `tools.READ_ONLY_ROLES` 里的 `"V"` | 实测 0（2026-10-21 现读：`{'C': ['analysis.register_report'], 'H': ['review.review_document','review.verify_fixes','review.report','review.record_finding'], 'V': []}` ⇒ V 一栏是空的） |
| **输出不合法绝不落台账行** | `verifications.parse_verdict` 抛 `VerificationError` ⇒ `record_verification` 不写行 | 自检 `[PASS] 没查成不落行` |
| **台账只追加、编号由脚本发** | `v-{S.format_id(len(rows) + 1)}`（六位，与手稿编号、台账 id 同一套做法） | 自检 `[PASS] 编号从 v-000001 起（六位；旧四位号读侧兼容）` —— **2026-10-18 修复轮后转绿**；采集当天红在写死四位的断言上（F-5，判为断言过期） |
| **第 3 位只在 `成立` 且无未解决 error 时被签** | `verifications.signs_bit3` / `bit3_payload`（签不了 ⇒ 返回 `{}`：**"没签"不是"忘了写"**） | 自检 `[PASS] 成立才签第 3 位` / `[PASS] 有毛病不签第 3 位` |
| **冷启动没有句柄** | `cold_start_prompt` 的签名里没有 `store`/`conductor`/`registry`/`session_root` | 自检 `[PASS] 冷启动提示词没有句柄参数` |
| **命题号必须是六位十进制（旧四位可读）** | `verifications.verification_ledger_path` → `schema.is_valid_id`（`schema.ID_DIGITS == 6`，读侧兼容四位） | 自检标签已对齐成「命题号必须 6 位（旧数据里的 4 位号仍可读）」，并加核 `detail` 里报出的宽度（采集当天标签写 4 位，F-6，已对齐） |
| **`limit=0` 是零条** | `verifications.list_verifications`（`out[-0:]` 的巧合已修） | 自检 `[PASS] limit=None 是全量而不是零条` |
| **V 不写任何表** | `capabilities.WRITE_SETS["V"] == frozenset()`；`schema.TABLES` 是 **17** 张（**V 没加表**） | 静态表 |
| **V 只能召唤 F** | `ALLOWED_EDGES["V"] == {"F"}` | 静态表 |
| **V 只能被 `B` / `F` 召唤** | `NON_SUMMONABLE` 里没有 V；指到 V 的边只有 `B→V` 与 `F→V`（`M` 的出边 `A B C D E G H` 里**没有** V） | 静态表 |
| **V 的只读读数由调用方取好传进来** | `verify.verify_proof` 的 `readonly_facts` 是**字符串**，不是 `store` 句柄 | 参数 schema |

### V.7 [附录·实测] 下沉明细

**V 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| **P3 折叠（最严重）** | 把"我没看出毛病"写成"成立" —— 漏检与通过是两件事，而台账上它们只差一个字 | `specs/v.py` 的 `signature_error` 逐字 |
| 拿 `看不出来` 冒充"审过了" | `没查成` 被折成第三个结论 ⇒ 台账上多一条假证据 | `verifications.py` 模块 docstring |
| 只写"这里不太严谨" | 不给步号 = 把改哪儿留给作者猜；`有毛病` 不给 `defect_step` 时**直接抛错**（结构性拦住） | `verifications.parse_verdict` |
| 把引到不干净命题当成这一处的笔误 | 那是**继承的缺陷**，要沿依赖边上溯（还是猜想 / 已作废 / 只是 assumption） | `specs/v.py` 的 `policy` 逐字 |

### M.5 [附录·实测] 下沉明细

**(b) `outcome`**

`TASK_OUTCOMES = ("ok","no_result","not_applicable","refused","failed","cancelled")`（`schema.TASK_OUTCOMES`）。

**六种组合的语义**（`conductor.SummonResult` 的表）：

| `status` | `outcome` | 含义 |
|---|---|---|
| `done` | `ok` / `no_result` / `not_applicable` / `refused` | 跑完了（可能"确实没有"，也可能"框架拒绝了"） |
| `failed` | `failed` | 执行中异常 |
| `cancelled` | `cancelled` / `refused` | 没跑完（被取消 / 因超预算被拒） |

**`SummonResult.ok` 的判据只有一处**（`conductor.SummonResult.ok` 逐字）：
`status=="done" and outcome=="ok"`。
"为什么 `refused` 不算 ok（它在 status 层是 done）：调用方问 `res.ok` 时想知道的
几乎总是'东西做出来了吗'，而不是'框架运转正常吗'。把 refusal 算成 ok 会让
'越权被拦住'在调用方看来像一次成功交付。"

**(c) handler 返回值 → 终态的映射**（`conductor.Conductor._end_from_payload`）

| handler 返回 | `status` | `outcome` |
|---|---|---|
| `None` | `done` | **`no_result`**（"**跑完了，确实没有**"） |
| `Mapping` 带 `status`/`outcome` | 取它（只认终态词表，中间态一律归 `done`） | 取它 |
| `Mapping` 带 `status="done"` 但没 `outcome` | `done` | `ok`，**并把"handler 未声明 outcome"写进 detail**（不许悄悄当 ok） |
| 其它任何值 | `done` | `ok` |

> ⚠️ **`None` 不许映射成 `ok`**（`conductor.Conductor._end_from_payload` 逐字）：
> "那正是'把『没做』与『做了没结果』折叠成同一个值'—— 本项目在引文校验、OCR、
> D 溯源、C 预算截断四处踩过它，每一次的后果都是下游把'我们没查'读成了'查了没有'。"

### M.8 [附录·实测] 下沉明细

`DESIGN-CONDUCTOR.md:254-265` 的 10 条 + 实现位置：

| # | 不变式 | 判据 | 实现/检查位置 | 状态 |
|---|---|---|---|---|
| I-1 | 每个 `started_at` 有且仅有一个 `ended_at` | 终态行 `ended_at` 非空；`running` 行 `ended_at` 为空 | `schema.ended_at` + `verify.task_still_running` + `_selftest` | **已落地**（双道） |
| I-2 | 终态不可改写 | 对已结束任务再调 `finish` ⇒ **零变更** | `conductor.Conductor.finish`（重读磁盘 + 什么都不做） | **已落地** |
| I-3 | 深度单调不减 | 子 `depth` ≡ 父 `depth + 1` | `conductor.depth` + `verify.task_depth_discontinuous` | **已落地**（双道） |
| I-4 | 拒绝必须带受控理由 | `outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS` | `schema.refusal_reason` + `Conductor.verify_tasks` | **已落地** |
| I-5 | 并发度不超上限 | 峰值同时 `running` ≤ `max_concurrency` | `policy.check` + `Conductor.peak_running`（`stats()` 暴露） | **已落地**（`peak_running` 是**可打印的事实**） |
| I-6 | 写集相交不并发 | 任一波浪内不存在两个任务写集相交 | `policy.waves_of` + `scheduler` | **已落地** |
| I-7 | 预算耗尽后不再新开任务 | ⇒ `refused/budget_exceeded` | `policy.check` | **已落地** |
| I-8 | 取消是协作式且不自动重试 | 取消后不产生新任务；被取消任务 `outcome="cancelled"` | `conductor.outcome` + `dispose` | **已落地** |
| I-9 | 台账可重建 | `rebuild()` 后 `tasks` 表逐字节一致 | `store.Store.rebuild`+ `tests/test_rebuild.py`（3 例） | ⚠️ **`test_rebuild.py` 是否覆盖 `tasks` 表：未核实** |
| I-10 | 结果合并顺序确定 | 同一 plan 跑两次，`SummonResult` 列表顺序相同 | `scheduler.run_waves`（按 plan 输入顺序合并） | **已落地**（`run_plan` docstring 逐字承诺"长度恒等于 `len(plan)` 且顺序与 plan 一致"） |

**另外**：`verify.py` 对 `tasks` 表的独立检查
（`dangling_parent_task` / `task_depth_discontinuous` / `task_without_input_key` /
`task_still_running` / `dangling_task_artifact` / `unknown_artifact_kind`）
与 `conductor.Conductor.verify_tasks`**判据一致但实现两份**
（`conductor.Conductor.verify_tasks` 逐字承认这一点并给出理由："`verify_all` 是**全库**审计、
由 CLI 跑；而'我刚跑完一次 run，台账是否自洽'是**即时**问题"）。
⇒ ⚠️ **这是"两套判据"的一个受控例外，但仍是 FC-11 的风险面**（两处会漂移）。

### M.7 [附录·实测] 下沉明细

**M 已知会犯/需要防的错**：

| 模式 | 防御 |
|---|---|
| 僵尸 `running`（有 start 没 end） | `summon` 的 `except Exception` **必须兜住一切**（`conductor.Conductor.summon` 逐字："这里**必须**兜住一切，否则僵尸 running"）+ `dispose()` 合成 end + `verify.task_still_running`（warning） |
| 取号撞车导致静默覆盖 | `conductor.Conductor._write_new_row` **取号 + 建行在同一事务与同一把锁内**，判据只有一处（`interactions.next_prefixed_id`） |
| `finish` 被重复调用累加 tokens | 用**本次 finish 实际写下的**值，而不是回读整行（`conductor.Conductor._charge_and_settle`） |
| 事务包住 handler ⇒ 死锁 | "事务**只包台账那一行**，绝不包 handler"（`conductor.Conductor.summon`）：(a) handler 可能跑几分钟；(b) handler 内部自己会 `store.tx(...)` |
| 静默丢弃多余参数 | `LocalBackend.call` **参数名对不上就拒绝**（`conductor.LocalBackend`）："静默丢弃会让'我传了但它没看'看起来像成功 —— 于是 `gaps()` 报告里说'已提交'，而请求一条也没有" |
| 未知 backend 拼错被当成"大概无所谓" | `Conductor.__init__` **fail-closed**（`conductor.Conductor`） |
| `LocalBackend` 猜依赖 | 只接受 `("factory", fn)` / `("object", obj)`；`("class", cls)` **明确拒绝**（`conductor.LocalBackend.resolve`） |
| `SubagentBackend` 假装跑通 | **明确 `refused/not_wired`**（`conductor.SubagentBackend.call` 逐字列出两条诚实的路并选后者） |

---

## A.10–M.10 [附录·实测] 全部自检入口与当次读数（现读于 2026-10-26（p210））

**口径**：Lean 关（出厂默认 `AGENTFLOW_LEAN_ENABLED` 未设 / 设为 0）。Lean 开着时 `agent_e`
多一段"未查 1 段"并多数几项，所以这一张表只在**关着**的那一档可比；两档的差写在正文 §E.4。

```powershell
cd D:\Incubator\agentflow; $env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python -m agentflow.agent_a   # 以及 agent_b … agent_h、agent_v、pipeline、llm
```

| 入口 | 当次读数（尾部逐字） | 退出码 | 行数 |
|---|---|---:|---:|
| `agent_a` | `[agent_a 自检] 29/29 项通过` | **0** | 31 |
| `agent_b` | `[agent_b 自检] 19/19 项通过` | **0** | 21 |
| `agent_c` | `自检断言：46/46 通过` + `SELF-CHECK DONE（agent_c）：46 项通过 / 0 项失败` | **0** | 243 |
| `agent_d` | `SELF-CHECK DONE（agent_d）` | **0** | 58 |
| `agent_e` | `SELF-CHECK DONE（agent_e）：22 项通过 / 0 项失败` | **0** | 37 |
| `agent_f` | `SELF-CHECK DONE（agent_f）：失败 0 项` | **0** | 42 |
| `agent_g` | `SELF-CHECK DONE（agent_g）` | **0** | 47 |
| `agent_h` | `SELF-CHECK DONE（agent_h）` | **0** | 85 |
| `agent_v` | `SELF-CHECK DONE（agent_v）：17 项通过 / 0 项失败` | **0** | 18 |
| `pipeline` | `SELF-CHECK DONE（pipeline）` | **0** | 48 |
| `llm` | `SELF-CHECK DONE` | **0** | 41 |
| `conductor` | **无入口**（`conductor.py` 是模块，不是包） | — | — |

> 判据：`tests/test_role_specs_appendix_is_live.py::test_a10_selfcheck_entries_match_a_live_run`
> 逐入口重跑一次（子进程、钉 Lean 关），对"尾部逐字 / 退出码 / 行数"三列逐格比。行数是刻意的
> 严格项：自检块多印或少印一段，正是"这套自检还在不在原位"的读数。

### 历史（2026-10-18 修复轮）：三行当时的读数与修前逐字

> 采集当天（同日早些时候）C 是 `43/46 + 3 FAILED + 退出码 0`、E 无汇总行 + 退出码 1、
> V 是 `14 PASS + 2 FAIL` + 退出码 1。修复轮逐条处理后，上面那张表按**复跑读数**写；
> 下面两段"修前逐字"是当时的原样，用作"修了什么"的对照（**留痕（2026-10-18，不作为当前值）**）。


**修前逐字（采集当天）—— `agent_c` 的 3 个 FAILED**：

```
  ========================================================================
  自检断言：43/46 通过
  FAILED: persist 落盘且登记行一致
  FAILED: I3 正向：新增 ≤3 条，且 submitted_by/priority/mode/topic 全部合规
  FAILED: I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由
SELF-CHECK FAILED
```

**修前逐字（采集当天）—— `agent_v` 的 2 个 FAIL**：

```
  [FAIL] 编号从 v-0001 起
  [FAIL] 五元位第 3 位 owner 是 V
```

> **修复轮（2026-10-18）的处理**（逐条依据见 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)）：
> **F-1/F-2/F-3**（C）判为**断言/夹具过期并已对齐** —— `rows[0]` 是"产出即登记"（CS-10 ②）之前的写法；
> I3 断言写死 `≤3` / 夹具写死 20 条在途，是 `interactions.DEFAULTS` 按裁定 C9 改成 30 / 200 之前的口径；
> 另有一处夹具混用四位概念号与六位关系号（`schema.ID_DIGITS` 已改六位）。
> **F-5/F-6**（V）判为**断言过期并已对齐**：第 3 位的 owner 确实是 V
> （`evidencebits.BIT_OWNERS["reviewed"] == "V"`，实测签名者 `agent-V`），红的只是写死的四位编号与过期标签。
> **F-4 / F-7** 是**真缺陷并已修**：E 的汇总行改为无条件打印、退出码与汇总同源，形式化路径按 Lean 开关走三态；
> C 的 `FAILED` 现在必定非零退出。判据 `tests/test_selfcheck_exit_codes.py`（子进程 + 注入失败负控）。

---

## S1 [附录·实测] 未核实清单（留痕（2026-10-18，当次审计范围相关，不作为当前值））

> 这一节记的是**当时没查的东西**，不是读数 —— 所以它不能"现读"，只能留痕；"要查什么、怎么复现"
> 就写在「我查了什么 / 缺什么」两列里（那两列本身就是复现手段）。
> 例外：#1 现在能现读，行内已经补了 2026-10-27 的结论。

| # | 未核实项 | 我查了什么 | 缺什么 |
|---:|---|---|---|
| 1 | `INVENTORY.md` 的"7 个零测试工具"在 `agentflow` 里是否仍成立 | 读了 INVENTORY §4.1 的方法（"在 `tests/**/*.py` 里搜索工具名字符串"） | **2026-10-27 现读（a）**：按同一条口径复算了 111 件 ⇒ **0 件**没有出现在 `tests/` 里（`INVENTORY` 那 7 个名字全部命中）。注意这个口径很弱（注释/夹具里的字符串也算命中），所以"7 个零测试工具"这个说法**不能再引用**；要判"真的没有测试"得看覆盖判据，那是另一本账 |
| 2 | `agent_d.AgentD.adjudicate` 处 D 到底改了 `relations` 的什么字段 | 读了 `capabilities.WRITE_SETS` 的注释（"agent_d.AgentD.adjudicate 的 research_questions+relations"） | 没逐行读那段代码 |
| 3 | `review.scan_document` 的手工复现 | INVENTORY §6.2 明确说"**我没有运行任何工具代码**"，并建议"后续审计第一件事就是写这两个复现用例" | 本次**也没有跑**这两个工具 |
| 4 | `max_questions` 超出时是否留痕 | 读了 `agent_d.AgentD.max_questions` | 没读 ingest 的截断分支 |
| 5 | `max_l3_lits` / `max_l2_context` 截断是否留痕 | 读了 `agent_d.AgentD.max_l2_context` | 没读对应的截断分支 |
| 6 | `review_rounds` 的具体上限数值 | 读了 `tools.review_tools.verify_fixes` 的分支 | 没找到显式常量；上限来自调用方 |
| 7 | `test_rebuild.py` 是否覆盖 `tasks` 表（I-9） | 读了 `DESIGN-CONDUCTOR.md:264` 声称"`rebuild()` 后 `tasks` 表逐字节一致" | 没读 `tests/test_rebuild.py` 的 3 个用例体 |
| 8 | `doc.build_document` / `doc.register_dependency` 的断言数/依赖数是否有间接上限 | 读了 `capabilities.CAPABILITIES` 的 params（无 `maxItems`） | 没读 `doc_tools.py` 的 handler 体 |
| 9 | G 的 `dependencies.used_by` 是否有直接的 verify 检查 | 读了 `verify.py` 当次的 code 列表（2026-10-21 现读 **105** 个去重 / **132** 处调用点，见正文 §0.4） | 只看到 `dangling_doc_ref`（经 `review_findings`），没看到 `used_by` 的检查 |
| 10 | `G → D/E/F` 的实际召唤是否有代码路径 | 读了边表（`capabilities.ALLOWED_EDGES`） | 没 grep `Conductor.summon("D", …)` 之类的调用点 |
| 11 | `LocalBackend.registry` 在真实运行里怎么接 | 读了 `conductor.LocalBackend` | 没找到任何生产调用方（**这可能意味着 M 目前只有测试驱动**） |
| 12 | `usage_ledger` 表是否有任何写入方 | 2026-10-21 复跑：grep `usage_ledger` 全仓 + 读 `tokenmeter.py` | **已核实（不再是"可能无写入方"）**：写入方是 `tokenmeter.TokenMeter.charge()` / `charge_once()`（`store.tx("usage_ledger", …)` + `tx.upsert`），由模型缝 `llmseam` 每次调用记一笔；`agent_*.py` 本身不直接写它 —— 旧结论"无写入方"是错的 |
| 13 | `subagent` backend 接上 DSH 后的行为 | 读了 `SubagentBackend`（恒 `not_wired`） | 无 API key / 无 harness 权限面，**无法实测** |
| 14 | `method="formal"` 的真实后端路径 | 读了 `verify_tools.py` 的 `fail(kind="not_implemented")` | 本机无 Lean/Coq/Isabelle，**无法实测** |
| 15 | 真实联网端到端 | 读了 `test_providers_online.py`（8 例，默认 deselect） | 本次**未跑 `-m network`** |
| 16 | 本机是否有 `easyocr`/`pytesseract`/`fitz` | 读了 INVENTORY §6.2 的"未探测"声明 | **本次也未探测** |

---

## S2 [附录·实测] 既有问题（现读于 2026-10-27（p206））

> 这张表 13 行。2026-10-27 这一遍：**能当场重跑的都重跑了**（#1 / #2 / #3 / #4 / #5 / #6 / #10 / #13
> 的"当次状态"改写成今天的结论 + 证据）；**仍要真机或人力逐条核的**在行内标
> `留痕（2026-10-18，需真机复现，不作为当前值）`，并给出复现命令 —— 不把"没查"写成"已修"。

| # | 问题 | 当次状态 | 证据（命令 + 输出） |
|---:|---|---|---|
| 1 | `cli tools --role E` 被 argparse 拒绝（`choices=["A","B","C","D"]`，退出码 2） | **已修复（现读）** | `python -m agentflow.cli tools --role E` ⇒ 正常输出工具清单，**退出码 0** |
| 2 | `agent_g` 的自检块完全跑不起来（`ValueError: … verifier_subject_key`，退出码 1） | **已修复（现读）** | `python -m agentflow.agent_g` ⇒ `SELF-CHECK DONE（agent_g）`，退出码 0 |
| 3 | `agent_a` / `agent_b` 没有自检入口 | **已修复（现读）** | 前者 `24/24 项通过`，后者 `19/19 项通过`，退出码均 0（见 §A.10–M.10） |
| 4 | `INVENTORY.md` / `tools.json` 是对 `test/test1/abflow` 的普查 | **仍成立（现读）** | 该文件在 `D:\Incubator\temp\inventory\INVENTORY.md`，首行逐字 `# abflow 契约现状清单（机械产出）` ⇒ 引用时必须写口径 |
| 5 | `agent_d._fallback_trace_tools` 的 `roles=("agent-C","agent-D")` 仍带前缀 | **已修复（现读）** | 现读是 `roles=("C", "D")`（`agent_d/_support.py` 里三处）—— 不再带 `agent-` 前缀，`for_role` 拿得到 |
| 6 | `attack_tools.TERMINAL_STATUSES` 缺 `supported_not_proved` | **已修复（现读）** | 现读 `sorted(TERMINAL_STATUSES)` = `['abandoned','resolved','stalled','supported_not_proved']` |
| 7 | `review.scan_document` 的 `dep_check` 与 `verdict` 自相矛盾 | 留痕（2026-10-18，需真机复现，不作为当前值） | 复现：造一行 `documents` + 调 `review.scan_document` 并**显式传 `dependencies=None`**，看 `dep_check.checked` 与 `verdict` 是否还矛盾（正文 §H 现在写的是"没查依赖闭合 ⇒ `verdict=unverified`"） |
| 8 | `search.dedup_check` 静默报"不是重复" | 留痕（2026-10-18，需真机复现，不作为当前值） | 复现：让 `tools.search_tools._literature_rows` 抛一次（例如给一个坏掉的工作区），看它是否仍静默报"不是重复"（正文 §R0 第 41 行的"已知问题"那一格记着它的现状） |
| 9 | `conductor.run_plan` 处曾有一处笔误引用（`condudctor.py`） | **已修复**（文档勘误） | 本文正文与附录均已写对 |
| 10 | `.noai-paths` 登记了尚不存在的路径（`src/agentflow/release_check.py`） | **仍成立（现读）** | `Test-Path src/agentflow/release_check.py` ⇒ `False`（有意设计：先登记以免"换目录就绕过"） |
| 11 | ~~`tests/test_noai_gate.py` 不存在~~ | **已关闭**（该文件存在） | 见旧版 S2 #11 的留档 |
| 12 | `README.md` 是 `test/test1` 的过时副本（写 "127 passed"） | 留痕（2026-10-18，需人逐条核，不作为当前值） | `D:\Incubator\README.md` 在（现读），但它是不是"过时副本"要人读一遍才判得动 —— 机器判不了"散文是否过时" |
| 13 | `data/` 目录在仓库里被提交了；旧文说"本目录不是 git 仓库" | **前半仍成立、后半已过期（现读）** | `agentflow/data/` 仍在；而 `D:\Incubator` **现在是 git 仓库**（`git rev-parse --show-toplevel` ⇒ `D:/Incubator`） |

---

## S3 [附录·实测] 本文引用的命令与当次真实输出（可复跑）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
```

| # | 命令 | 当次实测输出（摘要） | 退出码 |
|---:|---|---|---:|
| 1 | `python -m agentflow.cli tools` | `工具总数：114（已装模块 17…）`；`各角色工具数：{'A': 52, 'B': 38, 'C': 36, 'D': 57, 'E': 39, 'F': 51, 'G': 53, 'H': 44, 'V': 28, 'L': 38, 'M': 37}`；`只读角色写工具泄漏：{'C': ['analysis.register_report', 'clock.alarm_start', 'clock.periodic_start', 'clock.periodic_stop', 'clock.timer_cancel', 'clock.timer_purpose', 'clock.timer_start', 'clock.wait_any', 'conductor.ack', 'conductor.post_task'], 'H': ['clock.alarm_start', 'clock.periodic_start', 'clock.periodic_stop', 'clock.timer_cancel', 'clock.timer_purpose', 'clock.timer_start', 'clock.wait_any', 'conductor.ack', 'conductor.post_task', 'review.record_finding', 'review.report', 'review.review_document', 'review.verify_fixes'], 'V': ['clock.alarm_start', 'clock.periodic_start', 'clock.periodic_stop', 'clock.timer_cancel', 'clock.timer_purpose', 'clock.timer_start', 'clock.wait_any', 'conductor.ack', 'conductor.post_task']}（!! 有泄漏）`（现读于 2026-10-26；Lean 关着时是 `工具总数：111`） | 0 |
| 2 | `python -m agentflow.cli tools --role E` | 正常输出 E 的工具清单（**不再是 `invalid choice`**） | 0 |
| 3 | `python -m pytest --collect-only -q` | `5433/5461 tests collected (28 deselected) in 8.28s` | 0 |
| 4 | `python -m agentflow.agent_a` | `[agent_a 自检] 24/24 项通过` | 0 |
| 5 | `python -m agentflow.agent_b` | `[agent_b 自检] 19/19 项通过` | 0 |
| 6 | `python -m agentflow.agent_c` | **修复轮复跑**：`自检断言：46/46 通过` + `SELF-CHECK DONE（agent_c）：46 项通过 / 0 项失败`（采集当天是 `43/46` + 3 `FAILED` + 退出码 **0**，F-7） | 0 |
| 7 | `python -m agentflow.agent_d` | `SELF-CHECK DONE（agent_d）` | 0 |
| 8 | `python -m agentflow.agent_e` | **修复轮复跑**：`SELF-CHECK DONE（agent_e）：25 项通过 / 0 项失败 / 未查 1 段`（出厂默认 Lean 关闭；采集当天止于 `[9] …`、无汇总行） | 0 |
| 9 | `python -m agentflow.agent_f` | `SELF-CHECK DONE（agent_f）：失败 0 项` | 0 |
| 10 | `python -m agentflow.agent_g` | `SELF-CHECK DONE（agent_g）` | 0 |
| 11 | `python -m agentflow.agent_h` | `SELF-CHECK DONE（agent_h）` | 0 |
| 12 | `python -m agentflow.agent_v` | **修复轮复跑**：`SELF-CHECK DONE（agent_v）：17 项通过 / 0 项失败`（采集当天 14 `[PASS]` + 2 `[FAIL]`；F-5/F-6 判为断言过期） | 0 |
| 13 | `python -m agentflow.pipeline` | `SELF-CHECK DONE（pipeline）` | 0 |
| 14 | `python -m agentflow.llm` | `SELF-CHECK DONE` | 0 |
| 15 | `python -m agentflow.cli verify` / `demo` | **未复跑**（本轮未跑；旧文记 `通过 错误 0 / 警告 0` 与 `演示成功。`） | — |
| 16 | `python scripts/noai_gate.py --git` / `--paths …` | **未复跑**（旧文记 `[unknown] … Not a git repository`；这一句**已过期**：`D:\Incubator` 现在是 git 仓库，`--git` 需要 `--since <ref>` 才判得动） | — |

> ⚠️ **旧版 S3 的 #1（`567/835/957 passed`）、#2（`工具总数：55`）、#3（`--role E` 退出码 2）、
> #6（`46/46`，采集当天实测是 `43/46`）、#10（G 退出码 1）全部过期**，已按上表替换。
> **修复轮（同日）之后 #6 的 `46/46` 重新成立**，但成立的原因不同：采集当天是"断言过期导致的红"，
> 修复轮把 F-1/F-2/F-3 对齐到当前口径（CS-10 ② / 裁定 C9 / 六位编号）后才绿 —— 见
> [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。
> 判据类的命令（`pytest -q` 全量、`noai_gate`、`verify`、`demo`）本轮**没有跑全**，
> 表中如实标"未复跑"，不拿旧读数充当今天的读数。
