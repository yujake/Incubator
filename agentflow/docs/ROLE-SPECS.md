# ROLE-SPECS —— 十个角色的规格（A B C D E F G H V + 主控 M）

> 🧭 **导航 1/6 —— 本文件只放规格**：谁是哪个角色、职责与"明确不负责"、状态机、预算与终止、三态、不变式、接口。它是**判据**。
> 🧭 **导航 2/6 —— 实测附录** → [`ROLE-SPECS-APPENDIX.md`](ROLE-SPECS-APPENDIX.md)：§R0.1–R0.3、各角色 `.4` 工具面明细、全部 `.10` 自检实测、`M.4.2`/`M.4.3`、`M.8` 补核、S1–S3。**读数带日期、不构成判据**。
> 🧭 **导航 3/6 —— 权威地图** → [`INDEX.md`](INDEX.md)：哪份算数、哪份只作依据；**新增文档必须在那里登记一行**。
> 🧭 **导航 4/6 —— 三类内容分家**：**规格**（本文件，随代码同步改）／**实测附录**（带日期、会过期，冲突以代码为准）／**历史**（`PROPOSALS.md`、`ROLE-SPECS-DRAFT-*.md` 等，只解释"为什么是现在这样"）。
> 🧭 **导航 5/6 —— 数字口径**：会变的**分份数不手抄**，一律写「现读：`python -m agentflow.cli tools --role X`」；本文件保留的每一个读数旁都带复跑命令。
> 🧭 **导航 6/6 —— 冲突与分层**：与代码冲突以**代码**为准，冲突本身是**本文的 bug**（见 `DEVELOPMENT.md` §10）。系统分层 = **八层**，第 8 层是 **Web / 用户端**（见 §0.8）：它**不属于任何角色的权限面**。

---

## 0. 公共约定（所有角色共用，逐节不再重复）

### 0.1 三态的四个位置

每个"查询/判定"类动作的返回都必须能回答三个问题，且**不许折叠**：

| 位置 | `checked` | `empty` / 值 | 含义 | 典型 `reason` |
|---|---|---|---|---|
| 没做 | `False` | 不给值 | **我们没查** | `not_wired` / `no_store` / `no_backend` / `caller_did_not_provide` |
| 做了，确实没有 | `True` | `empty=True`（或 `[]` + `empty`） | **查了，没有** | `no_hit` / `not_found` |
| 做了，有 | `True` | `empty=False` + 结果 | 查到了 | — |

判据（`schema.reason` FC-01）：`reason` 必须来自受控枚举，
且枚举里必须至少有一个"未执行"值。

### 0.2 工具面的三条公共事实（现读，2026-10-20）

> ⚠️ 本节只有**读数**，没有"历史快照"。旧版本在这里手抄过一次装配结果（55 个工具），
> 那份读数早已过期且**没有判据盯着它**；现已改成"命令 + 当次读数"的形态。

| 事实 | 现读数 | 复跑命令 |
|---|---|---|
| 工具总数（完整装配 = 含 `store`） | **94**，已装模块 15 个 | `python -m agentflow.cli tools`（首行"工具总数"） |
| 全部 8 个角色（A–H）**共有**的工具 | **12** 件：`conductor.escalate` `fs.list` `fs.read` `fs.search` `fs.stat` `table.count` `table.get` `table.list` `table.schema` `table.search` `manuscripts.list` `manuscripts.read` | 见下方"交集"命令 |
| 只读角色（C/H/V）工具面里的写工具 | **5** 件：`C` 1 件（`analysis.register_report`，业主 2026-10-18 的产出登记通道）+ `H` 4 件（`review.review_document` / `review.verify_fixes` / `review.report` / `review.record_finding`）；`V` 0 件 | `python -m agentflow.cli tools`（末段"只读角色写工具泄漏"） |
| `side_effect` 分布（94 口径） | `read 51 / write_local 38 / none 5` | 同上 |
| 第二根轴 `external`（94 口径） | `none 86 / egress 5 / exec 3` ⇒ 非 `none` 共 **8** 件 | 同上 |

**交集那一条的复跑命令**（A–H 十件里的头八个角色取交集）：

```powershell
cd D:\Incubator\agentflow; $env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'
python -c "import tempfile,pathlib;from agentflow.store import Store;from agentflow.tools import ROLES,build_registry;d=pathlib.Path(tempfile.mkdtemp());st=Store(d);st.init();reg=build_registry(store=st,workspace_root=d,roles=tuple(ROLES)).registry;f=[{s.name for s in reg.for_role(k)} for k in 'ABCDEFGH'];i=set.intersection(*f);print(len(i),sorted(i))"
```

> ⚠️ **`side_effect` 的受控词表现在只有三个取值**：`("none","read","write_local")`（`agentspec.EFFECT` / `agentspec.SIDE_EFFECTS`）。
> 旧的 `network` 已从两处词表删除 —— 联网/起进程那件事搬到**第二根轴** `external ∈ ("none","egress","exec")` 上。
> 所以"某工具是不是 `network`"这个问题已经**没有取值可答**；要问的是"它的 `external` 是什么"。
>
> ⚠️ **H 那 3 件写工具是"已登记的例外"，不是泄漏**：`tools/base.py` 的 `READONLY_CALL_EXCEPTIONS['H']`
> 逐条登记了这三个**该角色自己的落库代理**（写面钉死在 `review_findings` / `documents.status`）。
> `cli tools` 会把它们打出来并标"!! 有泄漏"——那一行是**声明面的读数**，行为面已被 `for_role` 拦下：
> H 仍然拿不到任何 `fs.*` / `table.*` 写工具。**V、C 两栏是空的**。

### 0.3 复跑命令（本文所有工具数字的出处）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python -m agentflow.cli tools              # 全部角色的条数 + 两根轴的分布 + 泄漏栏
python -m agentflow.cli tools --role H     # 单个角色的逐件清单
```

**现读输出（2026-10-20，尾部逐字）**：

```
工具总数：94（已装模块 15：table_tools, fs_tools, search_tools, ocr_tools, text_tools, graph_tools,
        trace_tools, research_tools, verify_tools, attack_tools, doc_tools, review_tools,
        conductor_tools, manuscript_tools, analysis_tools）

各角色工具数：{'A': 37, 'B': 23, 'C': 23, 'D': 42, 'E': 26, 'F': 37, 'G': 38, 'H': 31, 'V': 15, 'M': 21}
只读角色写工具泄漏：{'C': ['analysis.register_report'], 'H': ['review.review_document', 'review.verify_fixes', 'review.report', 'review.record_finding'], 'V': []}（!! 有泄漏）
```

> **行尾（实测，不是约定）**：本文件与附录都是 **LF** ——
> `python -c "import pathlib;print(pathlib.Path('docs/ROLE-SPECS.md').read_bytes().count(b'\r\n'))"` ⇒ `0`。
> 2026-10-18 之前有文档把这里记成 CRLF，那是错的；**一律以 `raw.count(b"\r\n")` 的读数为准**。
>
> **两套口径必须写明是哪一条装配命令**（同一个包，同一个版本，差的是 `store`）：
>
> | 口径 | 命令 | 工具数 |
> |---|---|---:|
> | **A 口径（不含 store）** | `build_registry(store=None, workspace_root='.', roles=schema.ROLES)` | 见 `cli tools` 的注释；**本文一律用 B 口径** |
> | **B 口径（含 store 的完整装配）** | `python -m agentflow.cli tools`（= `build_registry(store=Store(ws), workspace_root=ws, roles=ROLES)`） | **94** |
>
> **引用工具条数时若不写口径，这个数字就是噪声**（`X-5` 同族）。
> 逐角色的 `.4` 小节不再手抄"29/41/22…"这类会变的分份数 —— 每节给出的都是
> **现读命令**，读数随代码走。

### 0.4 全库不变式检查项（`verify.py`，机械抽取 **103** 个去重 `Issue.code`、**126** 处调用点）

**任何角色**的产出都会被下面这些检查覆盖（`verify_all`，`verify.verify_all`）。

复跑（机械抽取：`Issue(level, table, id, code, msg)` 的第 4 个位置参数，去重）：

```powershell
cd D:\Incubator\agentflow; $env:PYTHONPATH='src'
python -c "import ast,pathlib,collections;c=collections.Counter();n=0
for p in sorted(pathlib.Path('src/agentflow').rglob('*.py')):
    t=ast.parse(p.read_text(encoding='utf-8'))
    for x in ast.walk(t):
        if isinstance(x,ast.Call) and getattr(x.func,'id','')=='Issue':
            n+=1
            if len(x.args)>3 and isinstance(x.args[3],ast.Constant) and isinstance(x.args[3].value,str): c[x.args[3].value]+=1
print('调用点',n,'字面量',sum(c.values()),'去重',len(c))"
```

| 检查码 | 级别 | 判什么 | 主要针对 |
|---|---|---|---|
| `schema_invalid` | error | 任一行的 `validate()` 失败 | 全体 |
| `duplicate_id` | error | 同表 ID 重复 | 全体 |
| `id_gap` | warning | 编号出现空洞（六位；旧四位数据按数值判） | 全体 |
| `counter_behind` / `counter_overflow` | error | counters 落后（会撞号）/ 超出编号空间上限（六位 = 999999） | 全体 |
| `dangling_lit_ref` / `unknown_request_ref` | error / warning | 请求 ↔ 文献双向可追溯 | A |
| `done_without_result` | error | `outcome is None` 且无文献无错误 | A |
| `inflight_over_limit` | warning | 在途请求超过 I7 上限（按提交方点名）。只报不拦：人工面（CLI `submit` / WebUI `/api/submit`）刻意不过闸门，人有权把队列排长，机器只把"谁排长的"记下来 | A |
| `unregistered_submitter` | warning | 在途行的提交方不在 `SUBMITTER_DEFAULT_PRIORITY` 里 ⇒ 过闸门的来源优先级会落到 low、理由串写成"陌生来源"（那对框架自己的角色是一句错话）。只读在途行 | A |
| `file_missing` / `ok_without_path` / `mismatch_without_evidence` | error / warning×2 | 文献文件与下载状态一致 | A |
| `unsorted_concepts` / `dangling_concept` / `stale_group_key` / `dangling_lit` / `lit_not_processed` / `bad_page_range` | error | 关系行自身的一致性 | B |
| `duplicate_quote` / `near_duplicate` | error / warning | 同概念组内引文重复 | B |
| `unsorted_related` / `self_related` / `dangling_related` / `related_drift` | error×3 / warning | 概念派生字段 | B |
| `dangling_concept_ref` / `dangling_relation_ref` / `dangling_lit_ref` / `dangling_request_ref` / `stale_waiting` | error×4 / warning | 研究问题的引用闭合 | D |
| `report_file_missing` | warning | C 报告的 markdown 不在了 | C |
| `dangling_question_ref` / `evidence_kind_overclaim` / `unhashed_experiment_code` / `refutation_without_counterexample` | error | 实验行的证据纪律 | E |
| `dangling_question_ref` / `dangling_plan_ref` / `dangling_experiment_ref` / `stalled_without_partial` | error | 攻坚计划 | F |
| `dangling_dep` / `dangling_dep_external` | error / warning | 依赖闭合（FC-23） | G |
| `refuted_dependency_in_use` / `disputed_dependency_in_use` | error / warning | 依赖被证否 / 有争议（`draft/37` §16 P1） | G/D |
| `proof_claim_rests_on_weaker_evidence` / `proof_claim_with_unclosed_dependency` / `closed_dep_on_inconclusive_experiment` / `proof_claim_on_refuted_dependency` / `proof_claim_on_disputed_dependency` | error | **过度声称**（FC-22） | G/H |
| `statements`: `dangling_lit_ref` / `dangling_doc_ref` / `dangling_stmt_ref` / `proof_stmt_on_unusable_stmt`（`disputed` 降 warning）/ `active_stmt_quote_unverified`（warning） | error×3 / warning×2 | 命题台账（`draft/37` §16 P1） | B/D |
| `mismatch_literature_processed` / `partial_match_processed` | error / warning | 命中校验（`draft/37` §2 R1b / §16 P2） | A |
| `unsupported_claim` / `dangling_citation` / `citation_to_retracted_relation` / `citation_to_suspect_relation` / `overclaim` / `unknown_citation_kind` | error×5 / warning | 稿件的断言与引用 | G/H |
| `question_based_on_retracted_relation` | warning | 研究问题建立在被否关系上 | D |
| `dangling_doc_ref` / `finding_without_evidence` / `accepted_with_open_error` | error | 审校发现自身必须带证据 | H |
| `dangling_parent_task` / `task_depth_discontinuous` / `task_without_input_key` / `task_still_running` / `dangling_task_artifact` / `unknown_artifact_kind` | error×4 / warning×2 | 召唤台账（I-1/I-3/I-4） | M |
| `dangling_usage_task` / `usage_task_total_mismatch` | error / warning | 花销台账与任务一致 | M |
| `eval_duplicate_conflicting` | error | 同 `claim_key` 同口径的两条数字冲突 | E/G |
| `undeclared_array_field` | error | 数组字段未在 `ARRAY_FIELD_KINDS` 声明集合/序列（FC-05） | 全体 |
| `ledger_corrupt` / `ledger_bad_row` / `ledger_dangling_question` / `ledger_dangling_request` / `ledger_drift` | error×4 / warning | `research_request_ledger.json` 的受控偏离 | D |
| `deep_unavailable` / `reextract_failed` / `quote_state_changed` / `quote_not_found` / `empty_quote` / `no_text_layer` / `not_found_page_unknown` | warning / error | `--deep` 引文复核（FC-15 的归因分离） | B（写入方）/ H（复核方） |
| `dangling_experiment` / `promotion_target_missing`（T1）· `proved_without_formal_proof` / `promoted_without_closed_dep` / `refuted_without_counterexample` / `supported_without_support` / `status_conflicts_with_experiment`（T2） | error | **猜想**：T1 判"它引的代号在不在"，T2 判"这个状态配不配它自己举出的证据"（状态是结论、不是声明）。依据 `draft/30` §T1/§T2；五条 T2 码各有正控 + 注入负控（`tests/test_conjectures_status.py`） | D（写入方）/ H（复核方） |

### 0.5 召唤边（`capabilities.ALLOWED_EDGES`）

| 召唤方 | 允许召唤 |
|---|---|
| `M`（主控） | `A B C D E G H V` —— **只剩 `F` 不许直接控制**（2026-10-10 裁定要间接转达 B / F / V，此后被业主逐个加回：`M→B` 2026-10-13「补 M 到 B」、`M→V` 2026-10-18「给 M 开 V 出边」；F 走 `M→D→F`） |
| `A` | `B` |
| `B` | `C H V`（`H` 是 2026-10-14 加的：语义档的引文回验由 H 判） |
| `C` | `D` —— **2026-10-19 业主裁定**：「C 要能把"候选的更短路径"交给 D」。改前这里是**空**（"只读角色连请求都不直接发"）；现在它只发这一种请求，`read_only` / `write_set` 一个字没动 —— 写入仍由 D 落表 |
| `D` | `A B C E F` |
| `E` | `B D` |
| `F` | `A B C D E V` |
| `G` | `A D E F` |
| `H` | `A E G` |
| `V` | `F` |

**边总数 = 34**（`sum(len(v) for v in capabilities.ALLOWED_EDGES.values())`；V 落地前是 29
—— 新增的三条是 `M→V`、`F→V`、`V→F`。观测 2026-10-06（角色 V 落地）。
**2026-10-10 减回 29**：业主第 146 轮第 4 条裁定去掉 `M→B` / `M→F` / `M→V` 三条直接边
（B / F / V 改由父代理转达；见 §M.4.1 上面那段）。
**2026-10-13 再加一条 `M→B` 到 31**（业主裁定逐字「补 M 到 B」：B 是采信链第一环，无 Lean 的 T1 实测 M 够不着 B/V ⇒ `verifications` 目录压根没被创建）。
**2026-10-13 加一条 `B→V` 回到 30**：业主裁定逐字「允许 B 唤起 V。理由是 B 需要初步检验
收录的证明」—— 审校链（B / H / V）的第一环要能把**收录进台账的证明**直接交给 V 逐行走查，
否则它得转两次手才够得着 V。
**2026-10-14 加一条 `B→H` 到 32**：业主裁定逐字「允许 B 和 H 协作，B 唤起 H」，理由是
引文回验的口径改了 ——「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」。
逐字那一档 B 自己走（`quoteverify.check_quote`，不花模型钱，先走它）；**逐字不中而语义相同**的
（作者自己改写、换记号、跨语言的引文）由 **H 判**（`H.judge_quote_semantics`），
B 拿 H 的判定回填 `quote_verified` + `quote_mode="semantic"` —— H 仍只读、落库代理仍钉死在
`review_findings` / `documents.status` 上（"判"与"落"分居两处）。读数：
`python -c "from agentflow import capabilities as C;print(sum(len(v) for v in C.ALLOWED_EDGES.values()))"`）。
**2026-10-18 加回 `M→V` 到 33**：业主裁定逐字「给 M 开 V 出边」。理由是 `projects/t3d` 三·1 的
读数：`reviewed_proof_rows = 0`，而那一趟正文里有三条证明级断言 —— V 的逐行走查签名一个都没有，
因为 V 只能经 `F→V`、那一趟没走。开放这条边之后 `M→V` 是**首选路径**（`M→B→V` 仍可走，
`M→D→F→V` 不必再绕）。复跑：`python -c "from agentflow import capabilities as C;print(sum(len(v) for v in C.ALLOWED_EDGES.values()))"` ⇒ `33`。
**2026-10-20 撤掉那条 `C→D`，回到 33（改回原设定：C 无出边）**：业主裁定逐字「把协作改成
「D 唤起 C、C 向 D 汇报」，并保留 C 无出边的原始设定」—— 2026-10-19 加的那条 `C→D`（到 34）
撤回，链条是 **`D → C` 单向**：D 用 `conductor.summon` 派 C，**C 的"汇报"就是它的返回值**
（C 没有出边、也不许给它加一条把话送回去的通道）。复跑 ⇒ `33`。
判据：`tests/test_d_summons_c_and_c_reports_back.py`（正控：D 派 C、报告随返回值交回且
D 的下一步读得到它；反真空：`ALLOWED_EDGES["C"] == frozenset()`、边总数 33；两条负控：
把 `ALLOWED_EDGES["C"]` 塞成 `{"D"}` ⇒ 反真空红；把 D 的 `_do_summon` 改成"不读返回值
直接 final" ⇒ 正控红）。
**读数的连带**：`secretary.reach_fit` 对 C 的闭包又只剩它自己（`unreachable` 那一档在实表上
重新有对象）—— 那是闭包**读数**，不是权限：真正的闸门仍只看**直接**出边（`policy.check`）。

**没有任何角色能召唤 `M`**（`capabilities.NON_SUMMONABLE = {"M"}`，`capabilities.NON_SUMMONABLE`）。

### 0.6 写集（`capabilities.WRITE_SETS`）

两张写集相交 ⇒ 两个任务**串行**（`policy.estimate_write_conflict` / `capabilities.write_sets_intersect`）。

| 角色 | 写集（表级） |
|---|---|
| `A` | `search_requests`, `literature` |
| `B` | `literature`, `statements`, `relations`, `reprocess_requests`（S1r 并表后：概念行住 `statements` 的 `kind="concept"` 那一档，`concepts` 已退役） |
| `C` | `analysis_reports`, `search_requests`（**两格都是只读角色的显式登记例外**：`analysis_reports` 是 `handle` 的产出登记口，`search_requests` 是 I3 直连那条通道；真身 `specs/c.py` 的 `write_set`，两条理由见 §C 的那张表与 `agent_c/core.py` 的注释） |
| `D` | `research_questions`, `search_requests`（**不含** `relations`：D 对关系是**读** —— `specs/d.py` 的 `write_set` 是它的真身，`capabilities.py` 的注释逐字写着"D 的 `relations` 是读"；改关系状态的是 B） |
| `E` | `experiments` |
| `F` | `attack_plans`, `search_requests`, `reprocess_requests` |
| `G` | `documents`, `dependencies`, `review_findings` |
| `H` | `review_findings`, `documents`（只读角色的显式登记例外） |
| `V` | （空 ⇒ 只读：唯一产物是 `verifications/<命题号>.jsonl` 这个**文件**，不是表；`READ_ONLY_ROLES` 里的 `"V"` 与 `for_role` 的结构性剥离一起守它） |
| `M` | （空 ⇒ 并发判据上按"整张表"处理，与任何人串行） |
| 编排器自有 | `CONDUCTOR_WRITE_SET = {tasks}` |

> **`statements`（命题台账，`draft/37` §16 P1）的现状（批 R27 按代码改正）**：这张表**已经**在
> `B` 的写集里 —— 见上面 `B` 那一行末尾的 `statements`，真身是 `specs/b.py` 的 `write_set`，
> 那里的注释逐字记着加它的理由："`draft/37` §46：`register_statement` 让'B 登记命题台账'
> 第一次有了实现 —— 而写集原先没有这张表（声明落后于边界里那句'三件套缺一不可'）"。
> 这一段此前写的是"为什么不在上面任何一行的写集里…到今天为止没有任何角色的实现写这张表…
> 等 P2 的提示词落地、`specs/b.py` 的写集必须同步加上 `statements`" ——
> **那句话与它上面三行之内的表格自相矛盾**（`B` 那一行已经写着它了），按代码为准改正。
> 写集登记的口径不变：它是"**角色的 Python 实现**会 `store.tx()` 哪些表"（并发判据的输入）。

### 0.7 动作表（`capabilities.CAPABILITIES`，61 个动作）

| 角色 | 动作数 | 动作名 |
|---|---:|---|
| A | 6 | `run_once` `run` `search_literature` `walk_citations` `ingest_local` `shelf_search` |
| B | 7 | `run_once` `reprocess_once` `run_reprocess` `decide_structural_duplicate` `resolve_structural_duplicate` `run` `register_statement` |
| C | 10 | `hottest` `paths` `cold` `gaps` `neighbors` `relations_between` `contradictions` `structural_duplicates` `handle` `proof_chain` |
| D | 15 | `probe_c` `ingest` `ingest_detailed` `trace_question` `trace_l3` `assess` `submit_gaps` `consider` `poll` `adjudicate` `research` `run_round` `write_report` `register_conjecture` `propose_question` |
| E | 5 | `run_experiment` `check_formal` `evidence_for` `list_experiments` `run_script_experiment` |
| F | 4 | `create_plan` `step` `status` `list_plans` |
| G | 6 | `compose_claim` `register_dependency` `build_document` `render` `refresh_markdown` `revise` |
| H | 5 | `review` `verify_fixes` `list_findings` `judge_quote_semantics` `review_report` |
| V | 3 | `verify_proof` `list_verifications` `read_proof` |
| M | **0** | `CAPABILITIES["M"] == ()`（可断言的事实） |

> 装配期由 `capabilities.assert_capabilities()`（**导入期执行**）逐条核：
> ① 键集合 == `schema.ROLES`（+`M`）；② 每个 `handler_name` 在
> `agent_<role>.Agent<Role>` 上**真的可调用**；③ 同角色动作不重复；
> ④ 只读角色的写集例外必须显式登记；⑤ `SIDE_EFFECTS` 与 `tools.base.SIDE_EFFECTS` 逐字一致。

### 0.8 八层与"角色面之外"的那一层（Web / 用户端）

> 本层**不属于任何角色的权限面**：它不增加任何一个 `ToolSpec`，也不在 `capabilities.ALLOWED_EDGES` 里。
> 所以**不要**把它写进 §A–§M 任何一节的工具面。它的权威描述见 `INDEX.md` 与 `src/agentflow/webui/`。

| 事实 | 现读数 | 复跑命令 |
|---|---|---|
| CLI 入口 | `agentflow ... web`（帮助逐字：「起用户端网页（本地小服务：待回答面板 / 运行态 / 事件回放）」） | `python -m agentflow.cli web --help` |
| 服务端模块 | `src/agentflow/webui/` **9** 个 `.py` | `(Get-ChildItem src/agentflow/webui/*.py).Count` |
| 端点 | `webui/routes.py` 的 `ROUTES` **25** 条（`GET 18` + `POST 7`） | `python -c "from agentflow.webui.routes import ROUTES;import collections;print(len(ROUTES),collections.Counter(r[0] for r in ROUTES))"` |
| 静态产物（**已构建，运行期不需要 `node_modules`**） | `src/agentflow/web/static/`：`index.html` 0.9 KB、`assets/index.*.js` 91.6 KB、`assets/index.*.css` 21.6 KB | `Get-ChildItem -Recurse src/agentflow/web/static` |
| 前端源码 | `agentflow/ui/`（`api.ts` 端点、`sse.ts` 事件 kind、`types.ts` 字段、`main.tsx` 路由） | `Get-ChildItem agentflow/ui/src`（相对仓库根） |
| 判据 | `tests/test_webui{,_contracts,_pages,_readers,_settings_write,_sse,_static,_writes,_browser}.py`，**9** 个文件 | `(Get-ChildItem tests/test_webui*.py).Count` |
| 已知边界 | 原始七层出处的 `draft/35` **没有这一层**（后加）；`draft/114` 记的是"九页 / 十条只读面 / 五条写端点"（**当次读数，未复跑**） | — |

---

## R0. 全局工具总表（94 个，逐条）

> **本表是 §R0 的权威落点**，`tests/test_role_specs_complete.py` 逐行对账三列
> （`side_effect` / 审批 / `roles`）与实时注册表是否一致；工具名集合也必须**不重不漏**。
> `#` 列是**历史行号**（`paper_package` 退场与 `search.walk_citations` 落地都刻意**不补位**：
> 本文别处按行号引用过旧号，补位会让那些引用静默指到别的工具上）⇒ `#` 不连续，行数按实际行数算 = 94。

| # | 工具 | summary | `side_effect` | 审批 | roles | 参数 | 返回结构 | 测试 | 已知问题 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `attack.check_budget` | 检查攻坚预算是否完整、是否还允许再开一轮（四类键缺一不可） | `none` | 否 | F D G H | **budget**；depth, rounds_done | `{checked,complete,missing,allowed,reason,blocked_by}` | `test_agent_f.py` | INVENTORY 4.3(b)：`budget={"max_rounds":null}` 过校验 → `int(None)` `TypeError` |
| 2 | `attack.create_plan` | 为一个难题立项（预算四类键缺一不可，不完整就拒绝创建）；同 `problem_key` 已有未终结计划时不新建 | `write_local` | **是** | F | **problem**,**problem_key**；budget, depth, for_question_id, parent_plan_id, subgoals | `{created,plan_id,reason,plan?}` | `test_agent_f.py` | INVENTORY 4.3(b)：`PlanError`/`ValueError`/`StoreError` 逃逸成 `unexpected` |
| 3 | `attack.list_plans` | 列出全部攻坚计划（可按 `problem_key` 过滤） | `read` | 否 | F D G H | include_terminal, problem_key | `{checked,total,plans}` | `test_agent_f.py` | INVENTORY 4.5#13：handler 默认 `include_terminal=True`，显式传 `null` 被当 `False`（静默反转默认值） |
| 4 | `attack.pick_next_subgoal` | 按确定性次序选出下一个要推进的子目标（开始过的优先，卡住的最后） | `none` | 否 | F D G H | **subgoals** | `{picked,subgoal,reason}` | `test_agent_f.py` | INVENTORY 4.3(b)：`subgoals=null` 过校验 → `TypeError` |
| 5 | `attack.status` | 读一个攻坚计划的完整可读视图（子目标状态计数、预算余量、history 尾部） | `read` | 否 | F D G H | **plan_id** | `{checked,plan_id,status,rounds,subgoal_counts,history_tail,…,stale_blocked}` | `test_agent_f.py` | INVENTORY 4.3(c)：计划不存在时 `ok=True` + `checked=False`（**必须看 `checked` 而不是 `ok`**） |
| 6 | `attack.step` | 推进攻坚计划一轮：按 owner 分派（E 做实验/A 提检索/B 提重抽取）；C/D/F 的推理未接线则如实记 `no_change` | `write_local` | **是** | F | **plan_id** | `{plan_id,round,sid,action,outcome,status,budget_left,reason,budget_known,budget_reading}` | `test_agent_f.py` | INVENTORY 4.4：经 `_deploy_e` 跑 E 的脚本子进程（**声明里没有"执行进程"这一档**）；`budget_known`/`budget_reading` 是 P-09 的预算读数（读不到时 `status="unknown"` + `why`，**不据此否决**花钱） |
| 7 | `doc.build_document` | 写一行 documents 并渲染 markdown 到工作区内（逐条机械检查后再落库；`out_path` 越界即拒绝） | `write_local` | **是** | G | **kind**,**title**,**claims**；open_problems, out_path, sections | 落库后的 documents 行（12 个字段，含 `doc_id`/`markdown_path`/`content_sha256`/`revision`） | `test_agent_g.py` | INVENTORY 4.3(a)②：`citations:["lit:9999"]` 可通过全部闸门并落库（**引用存在性不核**）；4.3(b) `StoreError` 逃逸 |
| 8 | `doc.compose_claim` | 构造一条合规断言：`cross_check` 自动补"不构成证明"；无引用/否定未分类/过度声称在构造时就抛错 | `none` | 否 | G H F D | **text**,**citations**,**evidence_kind**,**section**；claim_id, is_negative, negation_kind | 合规的 claim dict（含 `claim_id`/`disclaimer`/`revision_hash`/`scope_caveat`） | `test_agent_g.py` | INVENTORY 总表：三态位 **无**（据 INVENTORY，未在代码中核实） |
| 10 | `doc.list_documents` | 只读列举稿件（代号/类型/标题/状态/审校轮次/断言数与 markdown 路径） | `read` | 否 | G H F D | kind, status | `{count,documents:[{doc_id,kind,title,status,review_rounds,claim_count,markdown_path}]}` | `test_agent_g.py` | INVENTORY 4.3(b)：`StoreError` 逃逸 |
| 12 | `doc.register_dependency` | 登记外部依赖（FC-23）：`status="closed"` 会先用真实数据核 `lit_id`/`experiment_id`；`dangling`/`external_unavailable` 必须写 `status_reason` | `write_local` | **是** | G | **used_by**,**kind**,**label**；page_range, quote, source_experiment_id, source_lit_id, status, status_reason | 落库后的 dependencies 行（含 `dep_id`/`status`/`source_claim_id`/`source_doc_id`） | `test_agent_g.py` | — |
| 13 | `doc.paper_compile` | 把 `<项目根>/out/paper/main.tex`（**正文由智能体自己写**）编成 `main.pdf`，并写**框架自己产**的编译回执 `COMPILE-RECEIPT.json`；**不跑项目脚本**（LaTeX 引擎由框架直接起） | `write_local` | **是** | G | **project**；timeout_sec | `{tri,ok,reason,tex,pdf,engine,exit_codes,runs,pages,pdf_bytes,receipt_path,pdf_fresh,engine_stderr_tail,engine_stdout_tail,problems}`（`tri` ∈ `not_applicable` / `unknown` / `computed`） | `tests/test_papercompile.py` | **2026-10-13 重写**（业主裁定逐字「paper_package 里那些东西都是古早废案了，我们要智能体写文章」+ `draft/117`）：旧行跑项目里的 `code/compile_paper.py`，那条通道整条退场；`external=exec`（真的起 LaTeX 引擎）⇒ 审批列是；失败 kind ∈ `bad_project` / `paper_no_source` / `paper_compile_failed`；本机 MiKTeX 写完 PDF 却以 0xC0000409 退出 ⇒ 产物与退出码分两栏如实带回 |
| 14 | `doc.scan_claim` | 对一条断言做机械检查：有无引用、证据等级是否被夸大、否定是否分类 | `none` | 否 | G H F D | **claim** | `{checked,claim_id,ok,findings,error_count,warning_count,checked_fields,decided,revision_hash,status_axis,undecided_reason}` | `test_agent_g.py` | INVENTORY 4.5#10：与 `review.scan_document` 重复检查**且已漂移** |
| 17 | `fs.delete` | 删除文件；删目录必须显式 `recursive=true`（且不允许删工作区根） | `write_local` | **是** | A B D E F G | **path**；recursive | `data`=是否真的删掉；`meta.found` 区分本来就没有 | `test_tools_table_fs.py` | — |
| 18 | `fs.edit` | 定点替换文件里的一段文本（`old_string`→`new_string`）：默认要求唯一匹配、可要求前置 `sha256` 一致、`new_string` 有上限 —— 整文件覆盖之外的唯一正路 | `write_local` | **是** | A B D E F G **M**（§57：大文件只能靠它改） | **path**,**old_string**,**new_string**；sha256, allow_multiple, note | `{path,sha256_before,sha256_after,replacements,bytes_before,bytes_after,note}` | `tests/test_tools_fs_edit.py` | — |
| 19 | `fs.list` | 列出工作区内某目录（或单个文件）的条目；`recursive=true` 时递归 | `read` | 否 | A B C D E F G H **M**（§38） **V** | limit, path, recursive | `{entries:[{name,path,is_dir,is_file,is_symlink,size,mtime}],total,returned,truncated}` | **零提及** | INVENTORY 4.1：`limit`/`truncated` 分页逻辑无断言 |
| 20 | `fs.move` | 移动或重命名（目标已存在时拒绝，不静默覆盖） | `write_local` | **是** | A B D E F G | **src**,**dst** | `{src,dst}` | `test_tools_table_fs.py` | — |
| 21 | `fs.read` | 读文本文件；二进制与超限会如实说明（二进制直接拒绝，超限返回截断内容并标注） | `read` | 否 | A B C D E F G H **M**（§38） **V** | **path**；max_bytes | `data`=文本；`meta` 给 `encoding`/`bytes_read`/`total_bytes`/`truncated`/`had_errors` | `test_tools_table_fs.py` | — |
| 22 | `fs.search` | 在工作区文本文件里按 ripgrep 风格正则搜内容，返回「文件:行号: 行内容」 | `read` | 否 | A B C D E F G H **M**（§38） **V** | **pattern**；include, limit, path | `{matches:[{path,line,text}],lines,total,truncated,scanned,skipped}` | `test_tools_table_fs.py` | — |
| 23 | `fs.stat` | 查看路径的大小/类型/修改时间；文件另给 sha256 | `read` | 否 | A B C D E F G H **M**（§38） **V** | **path** | `{path,exists,is_dir,is_file,is_symlink,size,mtime,sha256,link_target}` | `test_tools_table_fs.py` | — |
| 24 | `fs.write` | 写文本文件（原子落盘；默认不覆盖已有文件） | `write_local` | **是** | A B D E F G **M**（§38：主控自己交报告） | **path**,**content**；overwrite | `{path,bytes,sha256,created}` | `test_tools_table_fs.py` | — |
| 25 | `graph.build` | 从 store 的三张表构建概念图索引，返回图规模摘要 | `read` | 否 | C D | （无） | `{concept_count,relation_count,pair_count,isolated_concepts,degree_top,…}` | `test_tools_graph_trace.py` | INVENTORY 总表：三态位 **无** |
| 26 | `graph.neighbors` | 返回某概念的邻居概念代号（升序）及其连接的度数信息；**邻居数有上限**，截断时如实报出 | `read` | 否 | C D | **concept_id**；max_neighbors | `{'concept_id','name','degree','total_neighbors','returned_neighbors','truncated','reasons','neighbors':[{'concept_id','name','relation_count','relation_ids'}]}` | `test_tools_graph_trace.py` / `test_tools_attack_graph_fixes.py` | ✅ **已修**（本轮）：原先 `neighbors` 是**不可截断的裸列表**，上下文预算的剪枝在它上面不生效（实测 300 邻居 = 27046 字符、`prune_tool_result` 后一条没少）。现在有界层在**工具层**（`max_neighbors` 默认 200），`RelationGraph.neighbors` **保持裸 list**（4 个调用点按 list 语义用它） |
| 27 | `graph.relations_between` | 返回同时包含两个概念的全部关系（按 `quote_verified`/`status`/信息量确定性排序） | `read` | 否 | C D | **a**,**b** | `{a,b,count,relations:[{relation_id,description,status,quote_verified,lit_id,page_range}]}` | `test_tools_graph_trace.py` | — |
| 28 | `graph.stats` | 返回当前图的统计摘要与热度前列（不重建索引；未建图时按需构建一次） | `read` | 否 | C D | top_n | `{…summary…,hot:[…]}` | `test_tools_graph_trace.py` | INVENTORY 6.4：`summary().degree_top` 取前 5 而 `hot` 用 `top_n`（**未判断是否有意**） |
| 29 | `manuscripts.list` | 列交接手稿（可按收件人/发件人过滤；默认最近 50 份） | `read` | 否 | A B C D E F G H **V** | to, sender, limit | `{'count','items':[{id,sender,recipient,title,summary,path,created_at}]}` | `test_manuscript_handoff.py` | — |
| 30 | `manuscripts.read` | 按编号读一份交接手稿的全文（编号不存在时如实说没有，而不是返回空文本） | `read` | 否 | A B C D E F G H **V** | **id** | `{'id','path','sender','to','summary','text','sha256','bytes','body','created_at','format','note','refs','sid','task_id'}` | `test_manuscript_handoff.py` | — |
| 31 | `ocr.backends` | **真实探测** OCR 后端（easyocr / pytesseract / none）是否可用；探测阶段**不会**下载 easyocr 模型 | `write_local` | **是** | B | refresh | `backends[]` + `any_ocr_backend_available`/`selected_for_auto`/`verdict` | `test_tools_search_ocr.py` | ✅ **已修**：原先声明 `read`（= 不需审批）却在**工作区外 mkdir**（`~/.EasyOCR/model`）并起进程 ⇒ 改为 `write_local`（如实声明） |
| 32 | `ocr.detect_text_layer` | 判断 PDF 有没有文本层；无文本层时说明这是「无法校验」而不是「校验失败」 | `read` | 否 | B | **path** | `has_text_layer`/`pages`/`page_count`/`pages_with_text`/`chars`/`source_kind`/`reason`/`suggested_next`/`page_count_known`/`page_count_source`/`failed_pages` | `test_tools_search_ocr.py` | INVENTORY 4.3(b)：`page_count(p)` 在 `try` 之外，异常逃逸 |
| 33 | `ocr.run` | 对指定页（缺省全部页）做 OCR；`auto` 按 easyocr→pytesseract 选第一个可用者，都不可用时 **fail** 并给安装建议（绝不返回空文本假装成功） | `write_local` | **是** | B | **path**；backend, dpi, languages, max_pages, pages | `pages[]` + `backend`/`elapsed_s`/`warnings`/`truncated_pages`/`total_chars` | `test_tools_search_ocr.py` | ✅ **已修两次**：原先声明 `read`，实际 easyocr 首次用**下载 ~100MB 模型** ⇒ 先改为遗留取值 `network`；B3 收官把它迁到两根轴上的确定值 —— `write_local`（下模型 + mkdir 模型目录 ⇒ 写我们拥有的东西）+ `declared_external="egress"`（真的下） |
| 34 | `research.list_gaps` | 列出研究问题台账（D 的工作台）。按 `priority`（high>medium>low）、`question_id` 稳定排序 | `read` | 否 | D | limit, status | `{questions:[…],count}`；每题带 `waiting_request_ids` | `test_agent_d.py` | — |
| 35 | `research.poll_waiting` | 复查等待中的查询请求：每条请求是否结束？其 `result_lit_ids` 是否都已被 B 消化？ | `read` | 否 | D | （无） | `{ready,waiting,counts}` | `test_agent_d.py` | — |
| 36 | `research.set_status` | 改研究问题的状态（按 schema 状态机校验，非法迁移与非法状态一律 fail） | `write_local` | **是** | D | **question_id**,**status**；notes | `{question_id,from,to,waiting_request_ids}` | `test_agent_d.py` | — |
| 37 | `research.submit_gap` | 把某研究问题的知识缺口提交给 A（在 `search_requests` 建一行，并把 `request_id` 追加进该问题的等待集） | `write_local` | **是** | D | **question_id**,**topic**,**mode**；description | `{request_id,question_id,duplicated,waiting_request_ids}` | `test_agent_d.py` | INVENTORY 4.7①：与 `table_tools._next_request_id` 的 `r-NNNN` 策略不同（**max+1 且无上限保护**） |
| 38 | `research.write_note` | 向某研究问题追加一条研究笔记（追加而非覆盖，保留研究过程） | `write_local` | **是** | D | **question_id**,**note** | `{question_id,notes_length,appended}` | `test_agent_d.py` | — |
| 39 | `review.list_findings` | 只读列举审校发现（可按稿件/状态/级别过滤），含每条发现的 `evidence` | `read` | 否 | H G F D | doc_id, level, status | `{count,findings:[{finding_id,doc_id,kind,level,target,message,evidence,status}]}` | `test_agent_h.py` | INVENTORY 4.3(b)：`StoreError` 逃逸 |
| 85 | `review.review_document` | 落审校发现（写 `review_findings` 并改 `documents.status`）—— 业主裁定「方案 1」后**对 H 可见**（写面钉死在 `READONLY_CALL_EXCEPTIONS`） | `write_local` | **是** | H | doc_id | — |
| 86 | `review.verify_fixes` | 复审：重跑检查判 fixed / 仍 open（写 `review_findings` 与 `documents.status`） | `write_local` | **是** | H | doc_id | — |
| 87 | `review.report` | 产出完整审校报告（markdown 落盘，不碰任何数据表） | `write_local` | **是** | H | doc_id | — |
| 40 | `review.scan_document` | 对一份稿件做全量机械审校（引用/证据等级/否定分类/依赖闭合），每条发现都带 `evidence` | `none` | 否 | H G F D | **doc**；dependencies | `{checked,doc_id,findings,error_count,warning_count,info_count,verdict,dep_check,reason,coverage,semantic_check}` | `test_agent_h.py` | INVENTORY 4.3(a)①：**依赖闭合没查却给出 `verdict="accepted"`**（`dep_check.checked=False` 与 `verdict` 矛盾）；4.5#10 与 `doc.scan_claim` 重复且漂移 |
| 41 | `search.dedup_check` | **不联网**：按三级硬键说明"这条会不会被判成已有的某篇"，并给出会命中的键 | `read` | 否 | A | **title**；doi, year | `would_be_duplicate`/`matched_key`/`keys`/`existing`/`near_misses` | `test_agent_a*.py` | INVENTORY 4.3(a)③：`_literature_rows` 的 `except Exception: return []` 静默报"不是重复"（**与 `store is None` 的严格 fail-closed 相反**） |
| 42 | `search.ingest_local` | **不联网**：把一个本地目录里的书登记进书架（按 sha256 幂等；dry_run 只算不写）。provenance 如实写「由 agent-A 登记」 | `write_local` | **是** | A | **books_dir**；pattern, limit, max_bytes, dry_run | `{root,dry_run,limit,books,count,counts,ingested,already_present,unreadable,skipped,provenance}` | `tests/test_search_offline.py` | **本轮新增**（§191）；借「人直接提供」会写出假 provenance，此工具明确写 `submitted_by=unknown` |
| 43 | `search.download` | 把候选的 `pdf_url` 下到工作区 `downloads/`（不覆盖同名文件） | `write_local` | **是** | A | **url**；hint, max_bytes | `ok`/`bytes`/`sha256`/`path`/`rel_path`/`filename`/`http_status`/`content_warning`/`warnings` | **零提及** | B3 收官：遗留取值 `network` ⇒ `write_local`（它下到 `downloads/`，**写我们拥有的东西** —— 这正是旧词表丢掉的那个事实）+ `declared_external="egress"`。INVENTORY 4.1：离线套件零断言 |
| 44 | `search.literature` | 按 topic/mode 检索文献候选；每条候选都带 `dedup_key` 与 `is_new`。`mode=precise` 时必须给 `description` | `read` | **是** | A | **topic**；description, limit, mode, provider | `candidates[]` + 计数与 `diagnostics` | `test_tools_search_ocr.py` | B3 收官：遗留取值 `network` ⇒ `read` + `declared_external="egress"`。INVENTORY 4.2：`providers.py` 8 个联网用例默认 deselect |
| 45 | `search.local` | **不联网**：在本地书架的全文里按主题取**最相关的一页**与逐字摘录（带 `lit_id`/页码/`score`） | `read` | 否 | A C H | **query**；limit, max_chars, lit_id, max_books | `{query,searched,count,candidates,scanned,skipped_no_file,unreadable,no_text_layer,hits,elapsed_s,note}`（`hits[]` 每项含 `lit_id/title/path/sha256_12/page/excerpt/pages/score`） | `test_search_offline.py` | **本轮新增**（`draft/28` §187）；`skipped_no_file` / `unreadable` / `no_text_layer` 三个『这一本没查到』的理由分开报；没有跨进程正文缓存 |
| 46 | `search.providers` | 列出可用检索源，并**真实探测**各自是否可用（`ABFLOW_SKIP_NETWORK=1` 时标为未探测而不是猜） | `read` | **是** | A | （无） | `providers[]` + `available`/`unavailable`/`unverified` 三个名单 | `test_tools_search_ocr.py` | ✅ **已修两次**：原先声明 `read`（= **不需要审批**）却**发真实 HTTP 请求** ⇒ 先改为遗留取值 `network`；B3 收官迁到两根轴上的确定值 —— `read`（不写我们的东西）+ `declared_external="egress"`（真的发出去）。审批面在当前环境下不变（沙箱未声明 ⇒ `external != "none"` 仍要签字） |
| 47 | `search.register` | 登记一条文献（`processed=false`）：先判重，命中则复用既有 `lit_id`；未命中则 `alloc_id('lit')` 并把文件收编进 `library/<lit_id>/` | `write_local` | **是** | A | **title**,**type_code**,**summary**；doi, path, request_id, year | `created`/`lit_id`/`path`/`dedup_key`/`download` | **零提及** | INVENTORY 4.1：**副作用最大、覆盖最少**；4.3(b) `row.validate()` 未包 guard，`ValueError` 逃逸 |
| 48 | `search.shelf` | **不联网**：列出库里全文在盘上的文献（本地书架），`origin` 分 `local_ingest`/`downloaded` 两档 | `read` | 否 | A C H | limit, lit_id | `{count,rows_total,have_path,missing_files,local_ingest,downloaded,truncated,books,note}` | `test_search_offline.py` | **本轮新增**（§187）；`pages` 对网络下载进来的行是 `null`（下载时没记页数） |
| 84 | `search.walk_citations` | 由一篇**已登记**的文献出发走一步引文图（`backward`=它引了谁 / `forward`=谁引了它）；**刻意不按热度排序** | `read` | **是** | A | **lit_id**；direction, limit | `{lit_id,doi,openalex_id,direction,count,candidates,note}` | `test_walk_citations.py` | 2026-10-15 新增（业主裁定「引文图是用新动作的方式落」）；**审批**：声明 `read`（不写我们的东西）＋ `external="egress"`（真的发出去）⇒ 与 `search.providers` 同一条口径，**要签字**；候选**不带判重标注**（不复制判重实现），登记走 `search.dedup_check`/`search.register`；出网在 provider 对象的方法里 ⇒ `walk_citations` 已补进 `scripts/lint_rules.py` 的 `_R010_NETWORK_MARKERS`（R010-b 与 R010-c 两个方向都盖住） |
| 49 | `table.count` | 统计行数（可用 `filter` 做等值过滤） | `read` | 否 | A B C D E F G H **V** | **table**；filter | `data`=整数行数 | **零提及** | INVENTORY 4.1：docstring 承诺「计数不该受 `limit` 影响」，**这个不变量没被测** |
| 50 | `table.create` | 新建一行：自动分配主键（`search_requests` 用 `r-NNNN`），校验通过才落盘，返回新 ID | `write_local` | **是** | A B D E F G | **table**,**row** | `data`=新主键**字符串**；`meta.row` 是实际落盘的整行 | `test_tools_table_fs.py` | INVENTORY 4.7①：`_next_request_id` 取**最小可用号**（与 `research_tools` 的 max+1 冲突） |
| 51 | `table.delete` | 删除一行；被引用的 `statements`/`literature` 会被拒绝并列出引用者 | `write_local` | **是** | A B D E F G | **table**,**id** | `data`=是否真的删掉；`meta.references` 列出引用者 | `test_tools_table_fs.py` | — |
| 52 | `table.get` | 按主键取一行；不存在时返回 `ok=True` 且 `data=None`（用 `meta.found=False` 说明） | `read` | 否 | A B C D E F G H **V** | **table**,**id** | `data`=行对象或 `None`；`meta.found` | `test_tools_table_fs.py` | — |
| 53 | `table.list` | 列出某张表的行（支持等值过滤与分页），并给出过滤后的总数 | `read` | 否 | A B C D E F G H **V** | **table**；filter, limit, offset | `{rows,total,returned,limit,offset,table}` | **零提及** | INVENTORY 4.1：`total` 是**过滤后**总数，是分页正确性的唯一依据，**没有一条断言** |
| 54 | `table.schema` | 返回表的字段名/类型/是否必填/默认值，以及全部受控词表 | `read` | 否 | A B C D E F G H **V** | （无） | `{tables:{表名:{fields,primary_key,vocabularies}},vocabularies}` | **零提及** | INVENTORY 4.1：反射出全部受控词表，**是 LLM 写参数的唯一依据**；4.5#9 `L3_STATUSES` 声称受控词表但无成员校验 |
| 55 | `table.search` | 在指定（默认全部标量字符串）字段里做大小写不敏感的子串匹配 | `read` | 否 | A B C D E F G H **V** | **table**,**query**；fields, limit | `{rows,total,matched_fields:{主键:[命中的字段]}}` | **零提及** | INVENTORY 4.1：`casefold()` 承诺与 `truncated` 语义无断言 |
| 56 | `table.update` | 部分更新一行：只覆盖 `patch` 里给出的字段，其余字段（含诊断字段）原样保留；不允许改主键 | `write_local` | **是** | A B D E F G | **table**,**id**,**patch** | `data`=主键；`meta.row` 是合并后实际落盘的整行 | `test_tools_table_fs.py` | — |
| 57 | `trace.chain` | 把一条关系代号链的每一步表述串起来（D 写报告可直接引用），缺号如实列出 | `read` | 否 | C D | **relation_ids** | `{level:'chain',relation_ids,steps,chain_text,missing}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)④：无 store/无 graph 时**静默返回 `ok` + `step_count=0`**（唯一一个"成功"的静默空结果）；4.5#4 `returns=` 与 6 条错误分支不符 |
| 58 | `trace.concept` | L2 溯源：由概念代号取回定义 + 它参与的全部关系的表述（不下钻文献正文） | `read` | 否 | C D | **concept_id**；with_relations | `{level:'L2',concept,relation_count,relations,contains_fulltext:false}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑤：空图回退把「没查」报成「查了、没有」 |
| 59 | `trace.literature` | L3 溯源（按需、贵）：文献元数据 + 本地文件是否存在 + 正文片段；无文本层会如实报告而不是返回空串 | `read` | 否 | C D | **lit_id**；max_chars, pages | `{level:'L3',status,file_exists,has_text_layer,pages_returned,text,truncated,source_kind,abs_path,chars_returned,encoding,page_count}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑥：`store=None` 时**诚实的 fail 被前置检查遮蔽**；4.5#4 六条错误分支缺 `pages_returned`/`truncated` |
| 60 | `trace.relation` | L1 溯源：由关系代号取回引文/描述/陈述/页码/状态/引文校验三态，并翻译概念名、附文献元数据 | `read` | 否 | C D | **relation_id** | `{level:'L1',relation_id,quote,description,statement,page_range,status,quote_verified,concepts,literature}` | `test_tools_graph_trace.py` | INVENTORY 4.5#7：`returns=` 少列 2 个实际键，且多一个写死的 `contains_fulltext: False`（**看起来像检查结论**） |
| 61 | `verify.check_formal` | 把命题（Lean 源码/脚本）交给检查器真跑一次；只有 `verified` 给 proof 级证据，`compile_error`/`uses_sorry`/`extra_axioms`/`decl_mismatch` 是"查了没通过"，`timeout`/`no_backend`/`tool_crashed` 是"没查成" | `read` | **是** | E F G | **claim**；script_path, source, name, imports, timeout_sec | `{'checked','verified','claim','reason','detail','verifier_output','missing_imports','verifier_status','exit_code'}`（`reason` 取 `formalgw.STATUSES` 八值词表；`exit_code` = 检查器进程的真实退出码，没跑成时是 `None`，**绝不用 0 冒充"跑过"** —— E-12(a)） | `test_tools_audit_fixes.py` | **P1 本轮接线**：工具层此前给 `script_path` 时返回 `checked=False` + `reason="not_implemented"`（全文零处提到 `formalgw`），现已转发到 `src/agentflow/formalgw.py` 的 `check_lean`。三态映射：`checked` 取自 `formalgw.evidence_of` 的结论位（`verified`/`compile_error`/`uses_sorry`/`extra_axioms`/`decl_mismatch` ⇒ True；`timeout`/`no_backend`/`tool_crashed` ⇒ False）；`verified` 只在 `status == "verified"` 时为 True，`checked=False` 时保持 `None`（未查成绝不写成 False）。`side_effect` 由 `none` 改为 `read`。**B3 收官**：新增 `declared_external="exec"`（它执行的是调用方给内容的检查器）⇒ 审批列由 `否` 变 `是`、`roles` 由 `E F G H` 变 `E F G`（H 只读，拿不到需要审批的工具）。真实正控在这台机器的 Lean 4.7.0 上跑到 `verified` + `evidence_kind="proof"`，三条负控（含 sorry / 无后端 / 声明名对不上）各自如实失败（证据脚本 `temp/w5_p1_probe.py`）。已知缺口（本轮未改）：`script_path` 不经 `_resolve`，越出工作区的路径不会被工具层拦下 —— 记录在此待人工处置 |
| 62 | `verify.code_hash` | 计算工作区内一个脚本文件的 sha256（前 16 位），用于实验记录的可复现性绑定 | `read` | 否 | E F G H | **path** | `{path,code_hash}` | `test_agent_e.py` | INVENTORY 4.3(b)：`open()` 的 `OSError`/`PermissionError` 逃逸 |
| 63 | `verify.detect_verifier` | 探测环境里可用的证明检查器（Lean/Coq/Isabelle）。返回的是事实，不是猜测 | `read` | 否 | E F G H | （无） | `{'checked','available','available_names','reason','probe_errors','looked_in','sources'}` | `test_agent_e.py` | ✅ **已修**：原先声明 `none` 却 `shutil.which` + `subprocess.run` ⇒ 改为 `read`；`checked` 不再硬编码 `True`（探测失败 ⇒ `False` + `probe_errors`）；`returns=` 补齐（**注意** `read` 与 `none` **都不需审批**，所以这次修正不影响审批面，只影响"审计口径"） |
| 64 | `verify.evidence_for` | 查一条命题（`claim_key`）或一个研究问题（`for_question_id`）已有的实验证据。两个参数都不给 ⇒ `checked=False` | `read` | 否 | E F G H | claim_key, for_question_id | `{checked,experiments,best_evidence_kind,proved,reason}` | `test_agent_e.py` | INVENTORY 4.3(b)：`StoreError` 逃逸；4.7⑪ 排序键与 `list_experiments` 逐字重复 |
| 65 | `verify.list_experiments` | 按登记顺序列出实验记录（只读）：没有它就无法回答"这件事到底做过没有" | `read` | 否 | E F G H | claim_key, limit | `{checked,total,returned,truncated,experiments}` | `test_agent_e.py` | 同上 4.7⑪ |
| 66 | `verify.run_experiment` | 在独立进程里跑一个工作区内的脚本并登记一条 Experiment 行。脚本自报 `evidence_kind='proof'` 会被**降级**为 `cross_check`；崩溃一律记 `inconclusive` | `write_local` | **是** | E F G | **claim**,**claim_key**,**script_path**；for_question_id, method, params, timeout | `{experiment_id,recorded,result,evidence_kind,negation_kind,exit_code,reason,code_hash,runtime_sec,notes}` | `test_agent_e.py` | INVENTORY 4.4：跑工作区脚本子进程，**子进程继承完整环境（可联网）**；4.3(b) `ExperimentError`/`ValueError` 全部逃逸；4.5#8 `returns=` 漏 FC-10 的 `count`/`result_counts`/`negation_counts` |
| 67 | `verify.verify_proof` | 把一份证明按写成后的样子整体重读一遍（V 的唯一主动作）：三态结论 + 每条问题指到步号，并写一行 `verifications/<命题号>.jsonl`。`side_effect=read` 是刻意的：V 不写任何表，它唯一的产物是一个文件（自己的台账） | `read` | 否 | V | **statement_id**,**proof_text**；readonly_facts | `{'checked','statement_id','verification_id','verdict','defect_step','findings','unresolved_errors','proof_sha256','proof_chars','signed_bit3','reviewed_by','bits','ledger','reason','detail'}`（三条返回路径键集合相同；`checked=False` = 没查成：`reason ∈ judge_not_wired / unparsable / no_proof_text / bad_statement_id` —— 此时**不落台账行**，绝不拿「看不出来」冒充「审过了」） | `test_verifier_role.py` | **本轮新增**（F-02，`draft/54` §1.1）：V 是唯一"写文件不写表"的角色 ⇒ `side_effect=read` 与它在 `tools.READ_ONLY_ROLES` 里同时成立，两者互为判据 |
| 68 | `verify.list_verifications` | 列验证台账（只读，可按命题过滤）：没有它就无法回答『这份证明到底审过没有』 | `read` | 否 | V | statement_id, limit | `{'checked','total','items','problems','truncated','reason'}`（`problems` 是坏行说明 —— 照实列出，不静默跳过） | `test_verifier_role.py` | **本轮新增**（F-02）：`limit=None` 是全量、`limit=0` 是零条（`out[-0:]` 那个"零条 == 全量"的运算符巧合已修，见 `verifications.list_verifications` 的 docstring） |
| 69 | `verify.read_proof` | 按命题号读回被审的那份证明全文 + 它的 sha256 + 最近一次结论（只读） | `read` | 否 | V | **statement_id** | `{'checked','statement_id','proof_text','source','sha256','proof_chars','verifications','last_verdict','last_verification_id','problems','reason'}`（三条返回路径键集合相同；`source` 为空 = 台账里没有这个命题的证明全文） | `test_verifier_role.py` | **本轮新增**（F-02）："没读到"由 `source` 与 `reason` 说出，不靠少给键来表达（三态纪律） |
| 70 | `conductor.summon` | 派活：召唤某角色做某动作；闸门在主控内部（允许的边 / 动作表 / 参数接缝 / 四类上限 / 预算），被拒也落台账并给 `refusal_reason` | `write_local` | **是** | M | **target_role**,**action**,params,input_key | `{task_id,role,action,status,outcome,refusal_reason,detail,error,tokens,usd,depth,elapsed_sec,children,checked}` | `tests/test_conductor_tools.py` | 形参刻意不叫 `role`/`name`：那是 `ToolRegistry.call` 自己的形参（撞名会让调用方身份被当成目标角色） |
| 71 | `conductor.ledger` | 看台账四个视图：tree / stats / issues / verify（给主控判断用的事实，不含建议） | `read` | 否 | M | view,root_task_id | `{view,rows,stats,issues,verify,task_count}` | `tests/test_conductor_tools.py` | 无 |
| 72 | `conductor.stop` | 优雅停止：不再新开任务 → 等在飞收尾（有界）→ 给剩下的合成终态（不留僵尸、结果记未知、不自动重试）→ 落续跑简报；幂等（第二次不改第一次的理由） | `write_local` | **是** | M | reason,drain_sec | `{reason,reason_mapped_from,detail,inflight_at_stop,drained_sec,disposed,resume_brief,verify,…,blocked_remaining}` | `tests/test_conductor_tools.py` | `reason` 回报**首次生效**的那个（FC-20 终态先到先得） |
| 73 | `conductor.resume_brief` | 读上一次优雅停止留下的续跑简报（做了什么 / 剩什么 / 从哪继续）；没有简报时如实说没有，未终态行逐条报出（不自动续跑） | `read` | 否 | M | （无） | `{present,brief,unfinished_now,path}` | `tests/test_conductor_tools.py` | 简报是工作区根下的文件，不是领域表 |
| 74 | `conductor.cancel` | 硬取消（协作式）：立刻置共享停止信号，不等在飞收尾；与 `conductor.stop` 的区别是 stop 先尝试收尾 | `write_local` | **是** | M | reason,detail | `{reason,reason_mapped_from,detail,inflight}` | `tests/test_conductor_tools.py` | 无 |
| 75 | `conductor.acceptance` | 只读：读某个项目的验收表（默认 `out/paper/ACCEPTANCE.md`），逐行解析出 P1–P11 的判据名 / 结论 / 读数 —— 交付说明必须逐条与它对齐 | `read` | 否 | M | project_dir, rel_path | `{found,path,title,conclusion,rows,row_count,ok_count,not_ok_count,problems,documents}`（`rows[]` 每项 `{id,name,ok,reading}`）| `tests/test_paper_pack.py` | **本轮新增**（`draft/28` §189）；解析不出来时 `rows` 空而 `problems` 非空（空表 ≠ 解析失败） |
| 76 | `conductor.ensure_project` | 冷启动 / 热启动由主控决定：给 start=auto / cold / warm，返回四态（absent/empty/workspace/not_a_project）与最终 mode；cold 才建目录，warm 必须已存在且是工作区（绝不替人删、也绝不把别人的目录当工作区） | `write_local` | **是** | M | project_name,start,books_dir,books_limit | `{name,path,mode,requested,state,why,created,ingested}` | `tests/test_conductor_tools.py` | 无 |
| 77 | `conductor.state` | 只读状态视图：各表计数 + 猜想按状态计数（有这张表时）+ 台账规模 | `read` | 否 | M | （无） | `{root,tables,conjectures,tasks}` | `tests/test_conductor_tools.py` | 表读不了记 -1，不编 0 |
| 78 | `conductor.role_spec` | 某角色的动作与各自参数、以及它今天有哪些工具（派活前确认「这个角色能不能做这件事」；与 `capabilities` 同源） | `read` | 否 | M | role_name | `{role,actions,tools,summonable,duty,boundary,policy,signature_error,deliverable,stance}` | `tests/test_conductor_tools.py` | 无 |
| 79 | `conductor.summon_many` | 一次派**一批**活并真的并发：按写集分波（`policy.waves_of`），同波用线程池跑（上限 `max_concurrency`）。同角色要多实例时给每个 target 一个不同的 `instance`（同角色不同实例允许同波并发）；返回里带 `waves` / `concurrent_peak` —— "到底并发了没有"看这两个数 | `write_local` | **是** | M | **targets**,why | `{count,ok_count,refused_count,failed_count,waves,max_wave,concurrent_peak,elapsed_sec,why,results}`（`results[]` 每项 `{role,action,instance,task_id,status,outcome,refusal_reason,detail,error,tokens,usd,elapsed_sec,checked,children}`） | `tests/test_conductor_tools.py` | **本轮新增**（`draft/28` §198）：并发引擎 `run_plan`/`run_waves` 早就有，但生产路径上零调用 ⇒ 主控只能一次派一个、同角色多实例被角色级写集排成 N 波串行 |
| 80 | `conductor.closing` | 只读：跑**收工门**（`draft/37` §16 P3 的八格）—— 论文那一格（回执里的 `tex_sha256` 与盘上那份 `main.tex` 的摘要对得上；没有 `main.tex` ⇒ 不适用，回执读不到 ⇒ 没查成）/ 无未裁决矛盾 / 承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题。**每条各自一个三态读数，`unknown` 不是通过**；`can_close` 只在八格全过时为真 | `read` | 否 | M | project_dir,report_path | `{can_close,status,failed,unknowns,findings,readings,summary}`；`status` 的键是八格检查、值是三态之一；`findings[]` 每项 `{check,code,level,detail}` | `tests/test_closing_gate.py` | **本轮新增**（`draft/37` §16 P3）：判据本体在 `agentflow/closing.py`，工具与 CLI（`agentflow closing`）都调**同一个**函数；不给 `project_dir`/`report_path` 时那两格是"没查成"而不是"通过" |
| 81 | `text.extract` | **A 负责把一篇 PDF 转成纯文字稿入库**（业主口径）：读 PDF 自带的文字层、页间插 `===== page N =====`、写 `library/<编号>.txt`；**原 PDF 原样保留**；写盘前核质量（NUL/替换字符/控制字符占比超标 ⇒ kind=garbled_text，**不写盘**）；纯文本文件直通入库（幂等） | `write_local` | **是** | A | lit_id 或 path | out_dir, pages, max_pages |
| 81 | `conductor.status_report` | 只读：收**项目状态报告**（`draft/39` §4）——四类读数（逐表计数与最近几条 / 交接账本（含模型填 vs 框架派生）/ 在飞与卡点 / 拒绝与插话）并落 `out/review/STATUS-<ts>.{md,json}`。**旁路观测**：零模型调用、不停任何人的循环（用户侧入口是 `agentflow status-report`；入口②就是本工具） | `read` | 否 | M | since,out_dir | `{ok,md,json,tables,manuscripts,in_flight,attack_rounds,interjections,next_steps,note}` | `tests/test_status_report.py` | **本轮新增**（`draft/39` §4）：实现在 `agentflow/statusreport.py`，两个入口共用同一份 `collect()`；它存在的理由是「问 M 一句」会让 M 停下来等人（与「不打断协作」相反） |
| 82 | `conductor.board` | 只读：板上还挂着什么（工作项 + 它走到哪一档 + 谁读的）。一行 = 一个工作项（`tasks` 里 `kind` 非空的行）；`expects=ack` 的项只要收件人确认读过就算完，`expects=work` 的项要交付才算完。不含建议，也不替你决定要不要重派 | `read` | 否 | M | limit | `{checked,open_items,open_count,readings}`（**读不成 ⇒ 报错**，不回一个空板：`checked=False` 是"没查成"、`open_count==0` 才是"板上没事"，折平就是本仓最忌的形态） | `tests/test_board_items.py`、`tests/test_conductor_tools.py` | **本轮新增**（业主 2026-10-08 裁 A1=甲、T16）：A–H 的那一半在 `manuscript_tools`（`manuscripts.items` / `manuscripts.ack`）—— M 不进 `manuscripts.*` 是既有判据钉着的（`test_m_tool_surface_is_orchestration_only`） |
| 83 | `conductor.broadcast` | 给我名下的**直接子代理**广播一条通告（每个收件人一条 `expects=ack` 的板项）：级联由收件人自己决定（框架不代转）—— 要覆盖全树就逐层向下调用；我名下没有子代理时如实报"没有收件人"（**不假装发出去了**）；不知道我是谁（没有台账号、也没有调用上下文）⇒ 受控拒绝 | `write_local` | **是** | A B D E F G M | subject, body | `{checked,ok,broadcast,recipients,items,cascade,readings,note}`（`readings` 把"开了几条 / seen 几条 / acked 几条"分开报：展开了 ≠ 读到了） | `tests/test_broadcast_reaches_my_children.py` | **本轮新增**（业主 T20/T21 附二 乙）：一件能力、所有角色同一个做法（T21 作废了"只有 M 有全树档"那一版）；只读角色（C/H/V）不在它的 `roles` 声明里（声明了再剥掉会被 `cli tools` 报成"声明本身应改"）；"我是谁"由 `AgentLoop._do_tool` 的 `calling_as` 挂进调用上下文 |
| 88 | `analysis.register_report` | C 的**产出登记通道**（业主 2026-10-18：「只读角色的产出要能进台账」）：把这一趟 C 自己算出来的图读数 / 结构洞 / 候选缺口落成 `analysis_reports` 一行（复用 `agent_c._support.AnalysisReport.persist` —— 存盘顺序、号段、文件名规则都还是那一份实现）。只写这张表：`claims` / `literature` / `relations` 零写入点 | `write_local` | **是** | C | kind, summary, markdown；request, payload, params, warnings | `{checked,report_id,markdown_path,kind,summary,created_by}` | `tests/test_readonly_output_channel.py` | 根因读数（`projects/mp3` 末节第 5 条）：`analysis_reports` = 0，而 C 的图读数只活在回复与手稿里；同趟 run 记录（`projects/mp3/runs/C-20261018-201536-001.json`）里它两次尝试 `gaps` / `handle` 都拿到「没有名为 … 的工具」⇒ 它必须在**只读角色的例外表**（`READONLY_CALL_EXCEPTIONS["C"]`）里，否则 `_role_surface` 会把写工具整类剥掉 |
| 89 | `review.record_finding` | H 把**自己读出来的**那一条发现落成 `review_findings` 行（机械扫描 `review_document` 覆盖不到的那一类）；不改 `documents.status`、不碰知识表；去重键仍是 `(kind,target,message)`（与 `review_document` 同一份） | `write_local` | **是** | H | doc_id, kind, target, message, evidence；level, axis, suggestion, round_no, verbatim_quote, line, line_unavailable_reason | `{checked,created,duplicate_skipped,finding_id,doc_id,kind,level,round,status}` | `tests/test_readonly_output_channel.py` | 与 `review_document` 的分工：后者落机器算得出的那批，这一件落角色自己读出来的那一条（「G8 回执没给退出码」「正文引用的材料盘上没有」）；`evidence` 必填且非空 —— 审校者的判断也要有依据 |
| 90 | `lit.stage_add` | 把广搜结果**追加**进本次委托的待新增列表（一次任意条，超过 10 条也允许）：槽位号自动分配、只增不复用；入库是另一件事（`lit.admit_all`） | `write_local` | **是** | A | **request_id**,**entries**；batch | `{request_id,batch,count,staged}`；失败：`ok=False` + `kind`（no_store / no_delegation / bad_delegation / empty_batch / bad_batch / bad_entry / store_error） | `tests/test_search_tools_stage_admit.py` | 2026-10-20 新增（业主裁定「方案 1」的**待新增列表**：候选先进列表、逐条筛，筛完才迁进 `literature`） |
| 91 | `lit.stage_list` | 查待新增列表：默认**只看当前委托**（列表按委托重置）；status 五态（pending / withdrawn / rejected / admitted / cleared），**撤掉的空槽位照样在列表里并带理由** | `read` | 否 | A | request_id, batch, status | `{request_id,current_request_id,batch,status,count,counts,gaps,rows,total_all_delegations,note}`（`counts` 是五个状态的计数） | `tests/test_search_tools_stage_admit.py` | 同上；`request_id="*"` 是"全部委托"，不给就是当前委托 |
| 92 | `lit.stage_withdraw` | 撤掉某一槽：**序号不变、不物理删除**，写受控理由码（`withdrawn_by_reviewer`）+ 一句说明；撤掉后可再 `stage_add` 补位（新条进**新**序号） | `write_local` | **是** | A | **slot**,**reason_code**；note | `{slot,status,reason_code,reason,title,request_id,batch}`；失败 `kind`（no_store / bad_reason_code / unknown_slot / not_pending / store_error） | `tests/test_search_tools_stage_admit.py` | 同上；"撤掉"与"拒收"是两条通道（`lit.stage_reject` 是审完内容后拒收） |
| 93 | `lit.stage_reject` | 审内容后**拒收**某一槽：写受控理由码（`rejected_off_topic` / `rejected_low_quality` / `overlap_without_new_content` / `duplicate_doi`）+ 一句说明；行保留、不物理删除 | `write_local` | **是** | A | **slot**,**reason_code**；note | `{slot,status,reason_code,reason,title,request_id,batch}`；失败 `kind` 同 `lit.stage_withdraw` | `tests/test_search_tools_stage_admit.py` | 同上 |
| 94 | `lit.overlap_check` | **不联网**：这一条与本地库重叠多少？DOI 完全相同 ⇒ 视为重复；否则标题词集 Jaccard（阈值 0.60）≥ 阈值 ⇒ 必须给 `new_content` 才许入库 | `read` | 否 | A | **title**；doi | `{title,doi,checked,duplicate,overlap_score,overlap_kind,overlap_with,requires_new_content,reason}`；失败 `ok=False` + `kind` + `checked=False`（**重叠没查**，不是「没有重叠」） | `tests/test_search_tools_stage_admit.py` | 同上；三态口径与 `search.dedup_check` 逐字一致（`checked` 是"查没查"，不是"重不重"） |
| 95 | `lit.admit` | 正式入库（逐条）：条数上限（单次 ≤10、单委托累计 ≤10）与重叠检查都过了才走现有登记路径；超限**整笔拒绝**。**不清空列表**（清空属于 `lit.admit_all`） | `write_local` | **是** | A | slots, items；request_id, batch, new_content, overlap_ok | `{ok,kind,whole_call_refused,reason,request_id,batch,call_size,call_limit,delegation_admitted,delegation_limit,admitted,refused,cleared,registered,report,report_path}` | `tests/test_search_tools_stage_admit.py` | 同上；"整笔拒绝"与"逐条拒收"是两个读数（`whole_call_refused` vs `refused[]`） |
| 96 | `lit.admit_all` | **一键迁移**：本委托待审且过筛（重叠检查）的行一次性迁进 `literature`（≤10 条），然后结算清空本委托的列表（全终态、不物理删），并写委托报告 `reports/lit-<request_id>.md`（**已入库 + 未入库含受控理由，两块都要有**） | `write_local` | **是** | A | request_id, new_content | `{ok,kind,whole_call_refused,reason,request_id,call_size,call_limit,delegation_admitted,delegation_limit,admitted,refused,cleared,registered,report,report_path}` | `tests/test_search_tools_stage_admit.py` | 同上；这是 `specs/a.py` 的 `boundary` 那条 97 字口径（"一次检索至多入库10篇 … 筛完一键迁移并清空列表；报告写清已入库与未入库"）的机器落点 |
| 97 | `conductor.escalate` | 把「我需要召唤者做什么」写进**父代理的收件箱**并让本趟以 `stop_reason=escalated` 收工（子代理跑到一半卡住时用它，别靠返回值等下一轮、也别借别人的边绕）；收件人 = 运行期解析出的**召唤者**，**不要求**在 `edges` 里登记；顶层（没有召唤者）受控拒绝 `not_caller`，一行都不写 | `read` | 否 | A B C D E F G H V M | **need**,**kind**；evidence | `{to,to_task_id,need,kind,evidence,msg_id,state,note}`；受控拒绝：`ok=False` + `kind`（`not_caller` / …） | `tests/test_escalate_goes_up_and_stops.py` | 2026-10-20 新增（业主裁定「子代理卡住要能往上抛」）：它的 `roles` 是**十个角色全体** ⇒ 它同时进了 §0.2 那张"共有工具"表；`side_effect=read` 是刻意的（它只写一条给**父代理**的消息，不写任何表）；`external=none`（不进网络） |

### R0.1 94 个工具的公共事实（现读）

- `params_validated_by_layer = true`：`ToolRegistry.call` 在调 handler 之前**一定**跑 `validate_params`，非法即 `fail(kind="param_error")`，**不会进 handler**。
- `roles_consistent_with_side_effect = true`：**没有任何写工具声明了 C 或 V**（两道防线：注册期 `_effective_roles` 剥 `READ_ONLY_ROLES` + `for_role` 的结构性拦截）。**H 是唯一例外**，且例外逐条登记在 `READONLY_CALL_EXCEPTIONS['H']`（4 件落库代理，见 §H.4）。
- handler 形态（94）：`functools.partial` **91** / `lambda` **3** / 具名闭包 **0** ⇒ 那 3 个工具的**唯一**文档是 `ToolSpec.summary`（lambda 无法携带 docstring）。
- 两套口径不许互换：A 口径 `build_registry(store=None, …)` 比 B 口径 `cli tools`（**94**）少"需要 store 才能注册"的那一族；**本文一律用 B 口径**。
- **V 的 12 件公共只读**（`conductor.escalate` 1 + `fs.*` 4 + `table.*` 5 + `manuscripts.*` 2）来自装配器注入的实时角色表 `tools.TOOL_ROLES`；V 自己那 3 件声明里 `roles=("V",)`。

复跑：`python -m agentflow.cli tools`（条数 + 两根轴）与 `python tools/verify_role_specs.py`（逐角色对账）。

### R0.2 不经 `build_registry` 的 14 个工具（**必须单列**）

| 来源 | 数量 | 工具 | `side_effect` | 是否过角色校验 |
|---|---:|---|---|---|
| `agent_c.register_tools` | 9 | `graph.hottest` `paths` `cold` `gaps` `svc_neighbors` `svc_relations_between` `contradictions` `structural_duplicates` `check_conflict` | 全 `read` | **否** |
| `agent_d._fallback_trace_tools` | 3 | `trace.relation` `trace.concept` `trace.literature`（降级替身） | 全 `read` | **否**（`install_d_tools` 直接 `ToolRegistry(...)`） |
| `review_tools.register(include_writers=True)` | 2 | `review.review_document` `review.verify_fixes` | `write_local` | 走模块注册路径，**默认不注册** |

> 9+3+2 = **14**，且**不在 `cli tools` 的 94 里** ⇒ 别把它们加进"某角色的工具数"。
> ⚠️ 那 3 个替身的 `roles=("agent-C","agent-D")` **带 `agent-` 前缀**（不是 `"C"`/`"D"`），而 `install_d_tools` 又直接构造注册表 ⇒ `for_role("C")`/`for_role("D")` **永远拿不到它们** —— 正是 `build_registry` 专门加断言要拦的那类错误。
> `AgentH.install_h_tools` **不是新工具**：它复制 H 子集并用 `filter_readonly_h_surface` 再拒一次 + 留痕（`refused_write_tools`）。

## A —— 文献检索

### A.1 一句话定位

**A 是联网副作用最重的角色**（4 件 `external="egress"`；全系统另有 `B` 的 `ocr.run` 一件 `egress`，`E`/`F`/`G` 那几件是 `exec`）：它把 `search_requests` 里的一条待办变成"本地有全文的文献行"。
它回答的问题是：**"这条需求，外面有没有对应的文献，我拿得到吗？"**

### A.2 职责

| # | 职责 | 判据（可判定） |
|---|---|---|
| A-1 | 领取一条待办检索请求（租约内，幂等） | `agent_a.AgentA.run_once`；`search_requests` 的 `claimed_by`/`lease_until` |
| A-2 | 按 `mode` 检索候选 | `search.literature`（**`effect=read` + `external=egress`**；B3 前写作 `side_effect=network`）；`mode ∈ SEARCH_MODES`（`schema.mode`） |
| A-3 | 判重后登记文献行（命中则复用既有 `lit_id`） | `search.register`；`dedup.literature_keys` 三级硬键 |
| A-4 | 下载全文到 `library/<lit_id>/`，记 `sha256` 与 `download.status` | `search.download`；`schema.DOWNLOAD_STATUSES` |
| A-5 | 把请求标 `done` 并写 `result_lit_ids` / `outcome` | `schema.SEARCH_OUTCOMES` |
| A-6 | 自己**不抽概念**；检索完请 `B` | `A → B`（`capabilities.ALLOWED_EDGES`） |
| A-7 | 按**召唤方给的主题**现查一次：入队（过 I7 准入闸门）→ 领跑 → 把来源交回对方 | `AgentA.search_literature`（2026-09-30 加）：落 `search_requests` 一行（`submitted_by=agent-A`）后走既有的 `run_once` 链路；缺省 `mode=precise` |
| A-8 | 把**盘上已有的**外部文件登记成 `literature` 行（不联网） | `AgentA.ingest_local`（2026-10-02 加，`draft/37` §46）：走 `locallib.ingest_directory`，与工具 `search.ingest_local` **同一口径**（sha256 幂等 + 同一份 provenance）；`external="none"` —— 真机那趟的断点正是"盘上有论文、动作表里没有登记它的入口" |

### A.3 明确不负责

| 不做什么 | 为什么不由 A 做 | 该由谁做 |
|---|---|---|
| 抽取概念与关系 | 抽取是**知识生产**，A 的产出是**来源**；混在一起会让"来源对不对"与"抽得对不对"无法分别归因 | **B** |
| 写 `statements`（含概念行）/ `relations` | A 的写集是 `{search_requests, literature}`（`capabilities.WRITE_SETS`），**不含**知识表 | **B** |
| 判断一篇文献"有没有用" | 相关性判断需要图上的结构信息（度数、路径），A 拿到的是候选元数据 | **C**（分析）/ **D**（决策） |
| 逐字引文回验 | 回验需要**文献正文 + 关系断言**，断言由 B 产出 | **B**（`quoteverify`） |
| 决定研究问题该不该问 | A 只消费 `search_requests`；"该不该问"是研究判断 | **D**（`research.submit_gap` / `AgentD.submit_gaps`） |
| 发起第二次检索（"我再多找几篇"） | A 的 `run_once` / `run` 只**消费**队列（`capabilities.CAPABILITIES`）；`search_literature` 也只在**被召唤方点名主题**时才查一次 —— "该不该再找、找什么"这个决定不在 A 手里 | **D**（`D → A`）/ **F**（`F → A`），或任何有到 A 的边的角色直接 `summon(A.search_literature, topic=…)` |

### A.4 工具面（37 个，实测）

**现读**：`python -m agentflow.cli tools --role A` ⇒ `side_effect` read 20 / write_local 17 / none 0；`external` none 33 / egress 4 / exec 0；需审批 20 件。逐件明细（分组清单 + 拿不到什么）见附录 §A.4。

> A 拿不到的组：`research.*`（D 的决策）、`ocr.*`（B 的解析）、`graph.*`/`trace.*`（C/D）、
> `verify.*`（E/F/G/H/V）、`doc.*`/`review.*`、`attack.*`、`conductor.*`
> （唯一的例外是 `conductor.escalate` —— 它按设计发给**十个角色全体**，见 §R0 第 97 行）。

### A.5 状态机（**只留主转移表**；状态/约束/反例表与其余状态机见附录 §A.5）

A 产出的行有**两个**状态机。

**(a) `search_requests`（A 的输入队列）**

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `done=False → True` | ✅ | — |
| `True → False` | ❌ **不许** | `verify.done_without_result`（`verify.verify_all`）与 schema 的追溯字段共同保证；A-7 的先写实体后置标志纪律（`DESIGN.md`） |
| `done=True` 且 `outcome is None` 且无 `result_lit_ids` 且无 `last_error` | ❌ | `verify.done_without_result`（error） |
| `outcome="no_results"`（搜了确实没命中）且无文献无错误 | ✅ | `schema` 明确允许（`verify.verify_all` 的注释逐字记录曾把它误报为 error，已修 → 见 `DEVELOPMENT.md` §10-D4） |

### A.6 预算与终止条件

| 循环 | 上限 | 出处 | 上限用尽时 |
|---|---|---|---|
| `AgentA.run(max_requests=…)` | 调用方给；CLI `--max` 默认 1 | `cli.build_parser`；`agent_a.AgentA` | 正常返回，**已处理数**是可读的 |
| 单条请求的尝试次数 | `agent_a.max_attempts = 3` | `config.yaml:46` | 显式放弃（`outcome="gave_up"`）+ 写 `last_error`；**不静默丢弃** |
| 租约时长 | `agent_a.lease_seconds = 900` | `config.yaml:44` | 超时后其他实例可重新领取 |
| 单请求下载数 | `agent_a.max_downloads_per_request = 25` | `config.yaml:39` | 停止下载（**注意：`ARunResult.downloaded` 会小于候选数，这是截断，不是"没有找到"**） |
| 单次检索返回条数 | `broad=20 / topical=15 / precise=10` | `config.yaml:34-36` | 返回前 N 条 |
| 全局在途请求 | `interactions.DEFAULTS["max_inflight_requests"] = 200` | `interactions.DEFAULTS` | `admit_search_request` 拒绝新请求（**这就是 D 向 A 提问的刹车**，FC-19 判据③） |

> ⚠️ **FC-19 未落地**：**D 向 A 的总提问预算未定值**。现有的只有
> "在途条数 ≤ 20"（瞬时）与 `agent_d.max_total_requests = 20`
> （`agent_d.AgentD.max_total_requests`，每 run）。**没有 token 预算计量**：
> 实测 `token_meter` / `token_budget` 在 `src/agentflow/**` 里 **0 命中**。
> 新增的 `schema.UsageEntry`与 `usage_ledger` 表**已存在**，
> 但**没有一个检索路径往里写**（本次未在 A/B/C 的任何代码里核到写 `usage_ledger` 的调用）。

### A.7 三态与失败模式（“已知会犯的错”明细见附录 §A.7）

A 的"没有结果"逐个列：

| 场景 | 三态形态（实测/代码依据） | 判据 |
|---|---|---|
| **检索源没有命中** | `outcome="no_results"`，`result_lit_ids=[]`，**不是错误** | `schema.SEARCH_OUTCOMES` |
| **检索源报错（HTTP 4xx/5xx、超时）** | `outcome="search_failed"` + `last_error` 非空 | 同上；`verify.done_without_result` 只在**无** `outcome` 时才报 |
| **尝试用尽** | `outcome="gave_up"` + `last_error` | `lease.max_attempts` |
| **下载失败** | `literature.download = {status:"failed", …}` | `DOWNLOAD_STATUSES` |
| **下载到的东西不是 PDF** | `status="content_mismatch"` + **保留字节** | `verify.mismatch_without_evidence` 保证"有 mismatch 必有证据" |
| **下回来的不是派活点名的那一篇** | `literature.matched`（`exact` / `partial` / `mismatch` / `""`=还没核） | `verify.mismatch_literature_processed`（`mismatch` + 已消化 ⇒ error）；`partial` + 已消化 ⇒ warning |
| **这篇里没有那条定理** | A 的**定位结论**（`matched ∈ exact / partial / none` + 页码 + 片段 + 最接近的三段），落在回报里 | §2 R14：`none` 不许交给 B。⚠️ 与上一行的 `matched` **同形不同问**（见 `schema.LIT_MATCH_STATES` 的长注） |
| **没下载（配置关闭）** | `status="skipped"` | 与 `failed` **分开** —— 这是"没做"不是"做了没成" |
| **`search.dedup_check` 读不到文献表** | ❌ **已知缺陷**：`_literature_rows` 的 `except Exception: return []`（`tools.search_tools._literature_rows`）⇒ `would_be_duplicate=False`、`existing_table_size=0`、**没有任何 warning** | INVENTORY 4.3(a)③；**这是"把没做折叠成没有"的教科书例子** |

### A.8 不变式（`verify` 检查项名）

- 请求的 `result_lit_ids` 都真实存在。
- 文献的 `source_request_ids` 指向真实请求。
- `done=True` 必须能说清"跑出了什么"。
- 文献文件真的在盘上。
- `download.status="ok"` 必须有 `path`。
- `content_mismatch` 必须有证据。
- 命中校验为 `mismatch` 的文献不许被消化（§2 R1b / §16 P2）。
- `partial` 停在中间态要被看见。
- ID 唯一、无空洞、counters 不落后。
- 路径不逃逸工作区。

### A.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`D`（`:598`）、`F`（`:600`）。
  **A 能被 B/C/E/G/H 召唤吗？不能** —— 边表里没有这些来源。
- **A 能召唤谁**：只有 `B`（`capabilities.ALLOWED_EDGES`）。
- **入参从哪来**：`search_requests` 表的待办行（由 CLI `submit`、D 的
  `research.submit_gap`、C 的 `gaps(submit_requests=True)`、F 的 `attack.step` 的
  `_deploy_a` 写入）。**待办是唯一入口** —— A 不会被"直接调一个函数"而绕过。
  **例外是 `shelf_search`**（2026-10-06 加，J-53 / 裁决 2 族 1）：它是 A 唯一的
  **只读**动作（不写表、不联网），入参由召唤方直接给（`query` 可选；不给就只列书架清单）
  —— 它不消费 `search_requests`，也不产生新的待办。
- **产出被谁消费**：
  - `literature` 行 → **B**（抽取）、**D**（溯源到 L3）、**C**（图的节点来源经 B）
  - `library/<lit_id>/*` → **B**（`extract_text`）、`trace.literature`
  - `download.status` → **B**（跳过 `content_mismatch`）、`verify`

### A.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_a`。**当次（2026-10-18）**：`[agent_a 自检] 24/24 项通过`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## B —— 文献整理

### B.1 一句话定位

**B 是全系统唯一能自动发现"幻觉引文"的地方**（`tools/__init__.py` 的模块 docstring 逐字）。
它回答：**"这篇文献里到底说了什么？这句话逐字在不在里面？"**

### B.2 职责

| # | 职责 | 判据 |
|---|---|---|
| B-1 | 取未处理文献（`processed=false`） | `agent_b.AgentB.run_once` |
| B-2 | 抽取概念与关系（`RuleExtractor` 离线基线 / `LLMExtractor` 可插拔）。⚠️ **`R-56`（2026-09-29）之后 `RuleExtractor` 是"框架的回退"而 `AgentB` 默认拒抽**：无 LLM 时不把它的产出灌进概念图（跳过时行上留 `last_mine_error="no_llm_extractor"`、返回值里 `skipped_no_extractor` 计数）。要显式用离线基线请换 `llm.OfflineFixtureExtractor`（同实现、声明自己不是回退），演示与单测走的就是它 | `llm.py`；`extract_text` |
| B-3 | **逐字引文回验**：回到原文找一遍，定位成功则**存回原文的确切切片** | `quoteverify.py`；`agent_b.AgentB.run_once` |
| B-4 | 关系判重（三级键 + 相似度档） | `dedup.decide_relation`；阈值 `dup_strong=0.92` / `dup_review=0.72`（`config.yaml:30-31`） |
| B-5 | 写入期一致性闸门（I6）：问 C 这条新关系与已有关系是否矛盾 | `interactions.check_conflict`；**纯函数、签名里没有 store** |
| B-6 | 定向重抽取（I4）：处理 `reprocess_requests` | `agent_b.AgentB.reprocess_once`；同关系上限 2（`interactions.DEFAULTS`） |
| B-7 | 结构重复概念的**合并决定权**（I5） | `decide_structural_duplicate` / `agent_b.resolve_structural_duplicate` |
| B-8 | 把一条命题登记进**命题台账**（含完整假设 + 逐字证明摘录 + 出处） | `AgentB.register_statement`（2026-10-02 加，`draft/37` §46）：写库前核 `literature` 行存在（坏引用不许进库）、`quote_verified` 三态且非 `True` 必带 `quote_reason`；`statements` 因此第一次进了 `WRITE_SETS["B"]` |

### B.3 明确不负责

| 不做什么 | 为什么不由 B 做 | 该由谁做 |
|---|---|---|
| 检索/下载文献 | 网络副作用只归 A（`search.*` 的 `roles=("A",)`） | **A** |
| 判断一条关系"值不值得研究" | B 抽的是**表述**，不是**价值**；价值判断需要图上结构 | **C** → **D** |
| 决定两个概念该不该合并（当只有**结构**证据时） | 结构重复只是**候选**；`proposal="review"` 是"不得据此合并" | **C** 提候选，**B** 决定，**人**在只有结构证据时确认 |
| 改自己的历史产物（把 `relations` 行删掉） | 关系行一旦落库就有下游引用（`documents` 的 `rel:` 引用）；删除会让引用悬空 | 只能 `status ∈ {active, suspect, rejected}`（`schema.status`），**不许删** |
| 发检索请求（"这里缺证据，帮我再找"） | B 的动作里没有"提交请求"；它只能**接受** `reprocess_requests` | **D**（`submit_gaps`）/ **C**（`gaps(submit_requests=True)`，由编排层调） |
| 审校自己的抽取质量 | 自己审自己无法区分"发现"与"掩盖" | **H**（只读） |

### B.4 工具面（23 个，实测）

**现读**：`python -m agentflow.cli tools --role B` ⇒ `side_effect` read 13 / write_local 10 / none 0；`external` none 22 / egress 1 / exec 0；需审批 10 件。逐件明细（分组清单 + 拿不到什么）见附录 §B.4。

### B.5 状态机（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §B.5）

**(a) `literature.processed`**

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `False → True` | ✅ | — |
| `True → False` | ❌ | `verify.lit_not_processed`（error）—— 被关系引用的文献必须 `processed=true` |

### B.6 预算与终止条件

| 循环 | 上限 | 出处 | 用尽时 |
|---|---|---|---|
| `AgentB.run(max_docs=…)` | 调用方给；CLI `--max` 默认 1 | `cli.build_parser` | 正常返回 |
| `run_reprocess(max_requests=…)` | 调用方给 | `agent_b.run_reprocess` | 正常返回 |
| 单关系重抽取 | `max_reprocess_per_relation = 2` | `interactions.DEFAULTS` | `admit_reprocess_request` 拒绝（**返回理由，不静默**） |
| 关系判重：强重复 | `dup_strong = 0.92` | `config.yaml:30` | ≥ 阈值 → **拒绝写入** |
| 关系判重：复核档 | `dup_review = 0.72` | `config.yaml:31` | `[0.72, 0.92)` → 写入但标 `suspect` |
| 引文回验放宽 | `quote_widen_pages = 1` | `config.yaml:33` | 超出即 `quote_not_found`（**不许全文兜底**：`allow_fulltext_quote_fallback=false`，`config.yaml:36`） |
| 单关系概念数 | ≥ 2（`too_few_concepts`） | `verify.verify_all` | error |

> **硬纪律（FC-11）**：`quote_widen_pages` / `allow_fulltext_quote_fallback`
> **必须由写入方（B）与复核方（`verify --deep`）共用同一份配置**。
> CLI 的 `cmd_verify` 逐字实现了这条（`cli.cmd_verify`）。
> **但 `QuotePolicy` 统一配置对象仍不存在**（实测 0 命中）——
> 现在的保证靠"两处都从 `config.yaml` 取"，不是靠类型强制。

### B.7 三态与失败模式（“已知会犯的错”明细见附录 §B.7）

B 的"没有结果"逐个列：

| 场景 | 三态形态 | 依据 |
|---|---|---|
| **引文逐字找到了** | `quote_verified=True` | `schema.quote_verified` |
| **引文逐字找不到（在声明的页码里）** | `quote_verified=False`，`quote_check.reason="quote_not_found"` | `quote_not_found` |
| **页码未知** | 不做全文兜底（除非显式允许）；`reason="not_found_page_unknown"` | `LESSONS.md` E2 / N7 |
| **空引文** | **不许因为"没得比"判通过**（`"" in "abc"` 是 `True` ⇒ 必须显式挡） | `LESSONS.md` E3 / N6；`reason="empty_quote"` |
| **文献无文本层（扫描版）** | `quote_verified=None`，`reason="no_text_layer"` | `README.md:177-178` |
| **重新抽取失败** | `verify.reextract_failed`（warning）；B 侧记 `unreadable` + `last_mine_error` | `verify.verify_all` |
| **文件不存在 / path 为 null** | 记 `unreadable`，**不是** `quote_verified=False` | `agent_b.AgentB.run_once` |
| **`tools=None`（未接线）** | ❌ **历史最尖锐缺陷**：D 曾走"无工具"降级并**静默返回空**，报告写成"未能取到任何关系表述——这本身就是一个重要事实" | `LESSONS.md` P3 / P10；`draft/13` §8 |
| **矛盾闸门没跑** | `conflict_checks_skipped` 单独计数；`checked=False` | `agent_b.BRunResult` |

### B.8 不变式

- `concept_ids` 升序去重且 ≥ 2 个。
- 概念代号真实存在。
- `concept_group_key` 与 `concept_ids` 一致。
- `lit_id` 存在且该文献 `processed=true`。
- 页码 `start ≤ end`。
- 同概念组内无逐字重复引文。
- `related_concepts` 与从关系表重算一致。
- `related_concepts` 升序、不含自身、不悬空。
- 数组字段已声明集合/序列（FC-05）。
- `--deep`：每条引文回到原文逐字核。

### B.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`A`（`:595`）、`D`（`:598`）、
  `E`（`:599`）、`F`（`:600`）。
- **B 能召唤谁**：`C H V`（`capabilities.ALLOWED_EDGES`）—— "整理完请 C 看图的形状"；`H` 是 2026-10-14 加的（语义档引文回验由 H 判），`V` 是 2026-10-13 加的（采信链第一环把收录进台账的证明直接交给 V 逐行走查）。
- **入参从哪来**：
  - `literature` 的 `processed=false` 行（A 写入）
  - `reprocess_requests` 的 `pending` 行（C 的 `structural_duplicates` → D/E/F 提交；
    `REPROCESS_REASONS` 受控）
  - `config.yaml` 的 `agent_b.*` 阈值（`dup_strong` / `dup_review` / `quote_widen_pages` /
    `allow_fulltext_quote_fallback`）
- **产出被谁消费**：
  - `statements`（含 `kind="concept"` 的概念行）/ `relations` → **C**（图）、**D**（研究问题）、**E**（断言）、**G**（引用）、**H**（审校）
  - `relations.quote_verified` → **C** 的路径评分（`score_breakdown` 里 `quote_verified` 是最强信号，`DESIGN-ROLES.md` §5.4）
  - `suspect` → **D** 的矛盾裁决（I2）

### B.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_b`。**当次（2026-10-18）**：`[agent_b 自检] 19/19 项通过`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## C —— 只读图分析

### C.1 一句话定位

**C 把三张知识表变成可读的结构结论**，且**全量只读**。
它回答：**"这张关系图长什么样？哪里是热点、哪里是空洞、哪两条路径最值得下钻？"**

**C 是唯一"只读但确实会写自己的产出表"的角色**（`capabilities.WRITE_SETS["C"] = {"analysis_reports", "search_requests"}`）。
这不是冲突：`analysis_reports` 是 C 写**它自己说过什么**（`AnalysisReport.persist`，`agent_c.AnalysisReport.persist`）；
`search_requests` 是 I3 直连那条通道（`handle` 分派需求时直接建检索请求行）—— **两条都是只读角色的显式登记例外**，真身是 `specs/c.py` 的 `write_set`；
它**一行 `statements`/`relations` 都不碰**。

### C.2 职责

| # | 职责 | 判据 |
|---|---|---|
| C-1 | 最热概念榜（度数中心性） | `agent_c.AgentC.hottest` |
| C-2 | 两概念之间的路径 + **逐项信息量评分**（7 项 `score_breakdown`） | `agent_c.AgentC.paths` |
| C-3 | 冷门概念（`degree==0` **单独归一类「完全孤立」**） | `agent_c.AgentC.cold` |
| C-4 | 结构缺口候选（`veto` 与 `score` **分离**） | `agent_c.AgentC.gaps` |
| C-5 | I1 服务面：`neighbors` / `relations_between`（**三态 + 有界**） | `agent_c.AgentC.neighbors` / `agent_c.AgentC.relations_between` |
| C-6 | 矛盾检测（`method="literal"`，`strong`/`weak` 分档） | `agent_c.AgentC.contradictions` |
| C-7 | 结构重复候选（`proposal ∈ {merge, review}`） | `agent_c.AgentC.structural_duplicates` |
| C-8 | 自然语言需求分派（`kind` 可能是 `unknown`，**不可落库**） | `agent_c.AgentC.handle` |

### C.3 明确不负责

| 不做什么 | 为什么不由 C 做 | 该由谁做 |
|---|---|---|
| **写任何知识表** | **这是全系统最硬的一条**：C 一旦能写，它就成了"绕过 B 引文逐字回验"的写入路径 —— 而那是全系统**唯一**能自动发现幻觉引文的地方 | **B** |
| **发起任何召唤**（`ALLOWED_EDGES["C"] = frozenset()`） | 同上：能发起动作 = 能间接产生写入。且工具面里 `graph.gaps` **刻意不暴露 `submit_requests`**（`agent_c.AgentC.register_tools`） | **D** / 编排层 |
| 决定两个结构重复概念**是否合并** | 只有结构证据时 `proposal="review"` —— "**不得据此合并**" | **B**（`decide_structural_duplicate`） |
| 判一条矛盾"谁对" | 字面判据只能给线索；`weak` 档假阳性极高 | **D**（`adjudicate`）/ **人** |
| 决定要不要把缺口变成检索请求 | 候选缺口是**产出**，不是**决定** | **D**（`submit_gaps`）/ 编排层（`gaps(submit_requests=True)`） |
| 写报告以外的东西 | C 的写集只有 `analysis_reports` | — |

### C.4 工具面（23 个，实测）

**现读**：`python -m agentflow.cli tools --role C` ⇒ `side_effect` read 22 / write_local 1 / none 0；`external` none 23；需审批 1 件。逐件明细（分组清单 + 拿不到什么）见附录 §C.4。

### C.5 状态机（**只留主转移表**；状态/约束/反例表与其余状态机见附录 §C.5）

C 的产出有两类，状态语义完全不同。

**(a) `analysis_reports`（C 的产出登记行）**

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| 新建一行 | ✅ | — |
| 改已有报告行 | ❌ | C 的能力表里**没有** update 类动作（`capabilities.CAPABILITIES`） |
| 落库 `kind="unknown"` | ❌ | `schema.REPORT_KINDS` 校验 + docstring 明写 |

### C.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 路径条数 | `max_paths=5`（默认） | `agent_c.AgentC.paths`；CLI `--max-paths` 默认 5 | 截断并置 `truncated=True` |
| 路径最大跳数 | `max_len=4` | `agent_c.AgentC.paths`；CLI `--max-len` 默认 4 | 更长的路径不枚举 |
| 路径重合度 | `max_overlap=0.5` | `agent_c.AgentC.paths` | 高重合路径被过滤（"低重合度路径"是需求） |
| 服务面 BFS 深度 | `SERVICE_MAX_DEPTH`（schema 上限） | `agent_c.SERVICE_MAX_DEPTH` | 参数校验拒绝更大值 |
| 服务面节点数 | `max_nodes` | `agent_c.AgentC.register_tools` | `truncated=True`（**不静默截断**） |
| 结构重复枚举 | `structural_duplicate_max_pairs = 200` | `interactions.DEFAULTS` | 到上限给 `truncation_notice` |
| 缺口直连 A（I3） | `max_gap_requests_per_run = 3` | `interactions.DEFAULTS` | 逐条拒绝并**留理由**（自检实测："被拒=1 条，示例理由=本次 gaps 已达每轮上限 max_gap_requests_per_run=3 ⇒ 未提交。"） |
| 全局在途请求 | `max_inflight_requests = 20` | `interactions.DEFAULTS` | 在途到上限 ⇒ 新增=0、被拒=4（自检实测） |
| 评分阈值 | `threshold_high=3.0` / `threshold_medium=1.5` | `agent_c.DEFAULT_THRESHOLD_HIGH` / `agent_c.DEFAULT_THRESHOLD_MEDIUM` | 分档为 high/medium/low |
| **缓存** | 无 | — | C 每次重新构建图索引（`graph.build` docstring：可自行构建） |

> ⚠️ **C 的"预算截断"是全项目三态纪律的四个动机之一**（`DESIGN-CONDUCTOR.md:116-118` 逐字）：
> "本项目在**引文校验、OCR、D 溯源、C 预算截断**四处都踩过'把没做与做了没结果折叠成同一个值'的坑"。
> 现在 `truncated` 是显式字段，自检也断言它（"另有 23 条中等以上置信度候选超出 limit=6 未展开（已在统计中计数）"）。

### C.7 三态与失败模式（“已知会犯的错”明细见附录 §C.7）

| 场景 | 三态形态 | 依据 |
|---|---|---|
| **必须给 `truncated=True` + "另有多少条未展开"** | 实测自检输出逐字："另有 23 条中等以上置信度候选超出 limit=6 未展开（已在统计中计数）" | `LESSONS.md` P3(d) |
| 一条 high 都没有 | 报告**必须明说**"没有找到高信息量路径"，**不许硬凑** | `LESSONS.md` M9；`DESIGN-ROLES.md` §5.3(2) |
| 概念代号不存在 | `checked=True` + `reason="该代号不在概念表里"`（**不是 `checked=False`**） | 自检实测通过 |
| 邻域超 `max_nodes` | `truncated=True`，**不静默截断** | 自检实测通过 |
| 无边 | `checked=True, empty=True` | 自检实测通过 |
| **`graph.gaps` 的 `veto` v.s. `score`** | 引文校验全失败的候选**必须被 veto 剔除**，不许靠正向分抬回 medium | FC-26；`DESIGN-ROLES.md` §5.3(4) |
| `graph.build` / `graph.stats` 没查到 | ❌ **无 `checked` 位**（INVENTORY 总表"三态位=无"） | ⚠️ 未落地 |
| 矛盾 false positive | `strong`/`weak` 两档；**只有 `strong` 允许驱动 `status="suspect"`** | `draft/13` §8.1（旧版 24% 假报警率） |

### C.8 不变式

- 报告 markdown 文件存在。
- 报告行 ID 唯一。
- 数组字段已声明。
- **C 不能写知识表**。
- **C 的工具面 1 个写工具**，且是**逐条登记的例外**：`analysis.register_report`
  （`tools/base.py` 的 `READONLY_CALL_EXCEPTIONS['C']`，写面钉死在 `analysis_reports`
  一张表）—— 除了它，`for_role("C")` 拿不到任何 `write_local` 工具。
  > 旧文写"0 个写工具"是 2026-10-18 之前的口径（业主那次裁定加了 C 的产出登记通道）。
- **C 不召唤任何角色**（`ALLOWED_EDGES["C"] = frozenset()`，2026-10-20 业主裁定：
  改回 C 无出边、由 D 唤起 C）—— 它的报告随返回值交给派它的人，不需要一条出边。

### C.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`B`（`:596`）、`D`（`:598`）、
  `F`（`:600`）。**C 也能被 `A`/`E`/`G`/`H` 召唤吗？不能。**
- **C 能召唤谁**：**没有人**（`ALLOWED_EDGES["C"] = frozenset()`，2026-10-20 业主裁定：
  改回 C 无出边、由 D 唤起 C —— 候选更短路径由 D 自己派 C 来要，C 的汇报就是它的返回值；
  **写面一个字没动**，只读身份不变）。2026-10-19 那一版曾写着"只有 `D`"，已撤回。
- **入参从哪来**：`statements`（含概念行）/ `relations` 表（B 写入）；`request` 原文（人/编排层给的）。
- **产出被谁消费**：
  - `analysis_reports` 行 + `reports/*.md` → **D**（`ingest` 把它消化成研究问题）
  - `candidate_gaps` → **D** / 编排层 → `search_requests`（I3）
  - `structural_duplicates` 候选 → **B**（`decide_structural_duplicate`）
  - `contradictions` → **D**（I2 裁决）

### C.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_c`。**当次（2026-10-18，F-1/F-2/F-3/F-7 修后复跑）**：`自检断言：46/46 通过` + `SELF-CHECK DONE（agent_c）：46 项通过 / 0 项失败`；**退出码 0**。
汇总行与退出码**同源**（任一 `[FAIL]` ⇒ `SELF-CHECK FAILED` ⇒ 退出码 1）；判据在 `tests/test_selfcheck_exit_codes.py`（子进程 + 注入失败负控）。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## D —— 研究

### D.1 一句话定位

**D 把 C 的分析结论变成"研究问题"，并在证据就绪时给出带置信度的回答**。
它回答：**"这个结构缺口值不值得研究？现在证据够不够？不够的话该问谁？"**

### D.2 职责

| # | 职责 | 判据 |
|---|---|---|
| D-1 | 把 C 报告消化成研究问题（**内容键去重**） | `ingest` / `agent_d.ingest_detailed`；去重键 `(kind, 排序后的 related_relation_ids)` |
| D-2 | 用**可核实判据**判断"知识不足" | 三条：`a_no_keyword_hit` / `b_low_degree_unverified` / 矛盾（`DESIGN-INTERACTIONS.md` §6.4） |
| D-3 | 向 A 提问（把缺口变成 `search_requests` 行） | `agent_d.submit_gaps`；配额 `max_requests_per_question=2`、`max_total_requests=20` |
| D-4 | 复查在途请求与文献消化进度 | `agent_d.AgentD.poll`；`poll_waiting` 纯只读 |
| D-5 | 溯源（L1/L2/L3） | `trace_question`（`:1738`）/ `trace_l3`（`:1968`） |
| D-6 | 裁决矛盾（I2 闭环） | `adjudicate`（`:2514`）；`max_rounds_per_contradiction=2` |
| D-7 | 对证据就绪的问题写出带**置信度**的结论 | `research`（`:2941`）；置信度**不许拔高** |
| D-8 | 渲染研究报告 | `write_report`（`:3341`） |
| D-9 | 按问题向 C 点菜 | `probe_c`（`:920`）；`max_c_neighbor_queries=2` / `max_c_pair_queries=2` |

### D.3 明确不负责

| 不做什么 | 为什么不由 D 做 | 该由谁做 |
|---|---|---|
| 检索/下载 | 网络副作用只归 A | **A** |
| 抽概念/关系 | 知识生产归 B；D 只读关系表 | **B** |
| 改关系的 `status`（把 `suspect` 改 `active`） | D 的写集是 `{research_questions, search_requests}` —— **`relations` 不在里面**（真身 `specs/d.py` 的 `write_set`；`capabilities.py` 的注释逐字写着"D 的 `relations` 是读"）⇒ 这一步 D 做不了 | 写者是 **B**（重抽取；裁决只把关系当输入读） |
| 做实验/形式化 | 实验需要子进程与脚本，是 E 的职责 | **E**（`D → E`） |
| 立项攻坚 | 攻坚有独立的三维预算与终止条件，必须唯一主人 | **F**（`D → F`，I10 升级） |
| 写稿件 | 稿件有话术/引用格式/降级规则 | **G** |
| 审校自己的结论 | D 是产出者 | **H** |

> ✅ **批 R27 按代码改正（原文与它上面那一行都写着"D 的写集包含 `relations`"，现算不是）**：
> 现算 `capabilities.WRITE_SETS["D"] = {research_questions, search_requests}`
> （真身 `specs/d.py` 的 `write_set`），而 `capabilities.py` 的注释逐字写着
> "**D 的 `relations` 是读**"；`agent_d/core.py` 里唯一写 `relations` 的地方是
> `_selftest`（自检夹具，不在生产路径上）；`agent_d/adjudicate.py` 只把关系当**输入**读。
> ⇒ "研究角色能改知识表"这条**越界面今天不存在**，改关系状态的仍是 B
> （与上面那张表里"改关系的 `status`"那一行的口径一致）。
> 原文还写着"本次**未逐行核实** `agent_d.AgentD.adjudicate` 改了什么字段" ——
> 本批核实的结果是它**什么都不改**。这一处与 `draft/108` §四 CS-14 同族：
> 文档里的旧结论比代码慢了一步，而没有任何判据看着它。

### D.4 工具面（42 个，实测）

**现读**：`python -m agentflow.cli tools --role D` ⇒ `side_effect` read 26 / write_local 11 / none 5；`external` none 42；需审批 11 件。逐件明细（分组清单 + 拿不到什么）见附录 §D.4。

### D.5 状态机（**全项目唯一在代码里有显式迁移表的状态机** —— `tools/research_tools.py` 的 `LEGAL_TRANSITIONS`）（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §D.5）

`tools.research_tools.LEGAL_TRANSITIONS` 的 `LEGAL_TRANSITIONS` **本身就是文档**：

| 从 | 允许到 | 谁拦 |
|---|---|---|
| `open` | `needs_evidence`, `researching`, `dropped` | `research.set_status`（`tools.research_tools.research_set_status`）+ `schema.ResearchQuestion.validate` |
| `needs_evidence` | `researching`, `dropped` | 同上 |
| `researching` | `needs_evidence`, `answered`, `dropped` | 同上 |
| `answered` | **（空）终态** | 同上 |
| `dropped` | **（空）终态**（且**必须写明理由**） | `schema.ResearchQuestion.validate` |

### D.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 一次 ingest 建多少问题 | `max_questions = 5` | `agent_d.AgentD.max_questions` | 只建前 5 个（**超出部分是否留痕：未核实**） |
| 冷门判据阈值 | `degree_threshold = 2` | `agent_d.AgentD.degree_threshold` | 度数 < 2 且未验证 ⇒ `b_low_degree_unverified` |
| 单问题提问数 | `max_requests_per_question = 2` | `agent_d.AgentD.max_requests_per_question` | 不再提问 |
| 单 run 总提问数 | `max_total_requests = 20` | `agent_d.AgentD.max_total_requests` | 不再提问 |
| L3 下钻文献数 | `max_l3_lits = 3` | `agent_d.AgentD.max_l3_lits` | 截断（**应留痕 —— 未核实**） |
| L2 上下文条数 | `max_l2_context = 6` | `agent_d.AgentD.max_l2_context` | 截断 |
| 矛盾追问轮数 | `max_rounds_per_contradiction = 2` | `interactions.DEFAULTS`；`agent_d.AgentD.max_rounds_per_contradiction` | `adjudicate_contradiction` 返回 `persistent` |
| 矛盾检索请求总数 | `max_contradiction_requests = 10` | `interactions.DEFAULTS`；`agent_d.AgentD.max_contradiction_requests` | 拒绝新请求 |
| 单轮 C 邻居查询 | `max_c_neighbor_queries = 2` | `agent_d.AgentD.max_c_neighbor_queries` | 不再点菜 |
| 单轮 C 成对查询 | `max_c_pair_queries = 2` | `agent_d.AgentD.max_c_pair_queries` | 不再点菜 |
| 单轮 C 矛盾扫描上限 | `max_c_contradictions = 20` | `agent_d.AgentD.max_c_contradictions` | 截断 |
| 单轮裁决数 | `max_adjudications_per_round = 10` | `agent_d.AgentD.max_adjudications_per_round` | 停止裁决 |
| 问题等价类阈值 | `question_jaccard_threshold = 0.6` | `interactions.DEFAULTS` | `find_equivalent_question` 判"这是新研究点" |
| 全局在途请求 | `max_inflight_requests = 20` | `interactions.DEFAULTS` | `admit_search_request` 拒绝 |
| `run_round` 轮数 | CLI `--gap-rounds` 默认 2 | `cli.build_parser` | 正常返回 |

> ⚠️ **FC-19 未落地**（`DESIGN-CONDUCTOR.md` 与 `LESSONS.md` 都点名）：
> **token 预算计量的代码在 `src/agentflow/**` 里 0 命中**（实测 `token_meter` / `token_budget` = 0）。
> `schema.UsageEntry` + `usage_ledger` 表**已有**，`verify` 已有
> `dangling_usage_task` / `usage_task_total_mismatch` 两条检查，
> 但**没有任何 D/A/B 路径往里写**（本次未在 `agent_*.py` 里核到 `usage_ledger` 的写入调用）。

### D.7 三态与失败模式（“已知会犯的错”明细见附录 §D.7）

| 场景 | 三态形态 | 依据 |
|---|---|---|
| **两个参数都不给** | `checked=False`（"**没查 ≠ 查了没有**"） | `verify.evidence_for` 的 `returns`（工具 #53） |
| 给了参数但没命中 | `checked=True` + `experiments=[]` | 自检实测（`agent_e` 自检第 [7] 项逐字："给了参数但没有 ⇒ `checked=True` 且 `experiments=[]`"） |
| 请求已结束但 B 未消化 | `waiting`，reason 逐字："请求已结束，但结果文献还没被 B 消化完（`processed=false`）" | 自检实测 |
| 请求未结束 | `waiting`，reason 逐字："仍有查询请求未结束（A 还没跑完 / 还没跑到）" | 自检实测 |
| **证据足够** | 走 `consider()` → `researching`（**不许什么都不做**）；`research()` 跑完按同一批判据现算收口 —— 判据没触发 ⇒ `answered` 并清空等待集（`research_tools.LEGAL_TRANSITIONS` 里 `researching → answered` 那条边，批 R20 / CS-5） | `LESSONS.md` P2；`tools/research_tools.py` 的状态机表 |
| **置信度不许拔高** | 自检实测：确定性 `medium` + LLM 声称 `high` ⇒ **强制 `medium`** | `DESIGN-ROLES.md` §6.6；自检第 [10] 项 |
| 一致但样本有限 | `medium` + 判据 `a_no_keyword_hit`，结论逐字"证据方向一致但样本有限（且部分引文未通过校验），结论应视为待复核的假设" | 自检实测 |
| 证据不足 | `low` + 逐字"本节的措辞刻意停在「可能存在/尚未证实」，**不作为可引用的判断**" | 自检实测 |
| 内容重复的问题 | 按内容键去重，**已存在时不新建行，把新 `origin` 追加留痕**；实测问题数 4 → 2 | `LESSONS.md` P10 (#8) |
| 记录工具失败 | `last_tool_errors` 必须**可在任何路径上被写入**（曾因惰性创建使"记录失败的代码自己炸掉"） | `draft/13` §8.5；`agent_d.AgentD.last_tool_errors` |

### D.8 不变式

- 概念/关系/文献/请求引用闭合。
- 终态不留等待集。
- 研究问题不建立在被否关系上。
- `research_request_ledger.json` 一致性。
- 实验/计划的 `for_question_id` 真实存在。

### D.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`F`（`:600`）、`G`（`:601`，**"写稿时发现缺证据 → 回去要"**）。
  `D` 也能被 `E` 召唤（`E → D`，反例回流，`:599`）。
- **D 能召唤谁**：`A B C E F`（`capabilities.ALLOWED_EDGES`）。**不能召唤 G/H。**
- **入参从哪来**：
  - `analysis_reports`（C 的产出）
  - `relations` / `literature`（B 的产出）
  - `config.yaml` 的 `agent_d.*`（**当前 `config.yaml` 里没有 `agent_d` 段** —— 全部走代码默认值）
  - CLI `research --report-id --gap-rounds`（`cli.build_parser`）
- **产出被谁消费**：
  - `research_questions` → **C**（图上对应位置）、**F**（升级立项）、**E**（`for_question_id`）
  - `search_requests` → **A**
  - `reports/*-research.md` → **G**（写稿的证据）、**H**（审校）
  - 置信度 → **G**（`documents.claims` 的证据等级）

### D.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_d`。**当次（2026-10-18）**：`SELF-CHECK DONE（agent_d）`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## E —— 数值实验与形式化验证

### E.1 一句话定位

**E 产出"证据"，且必须标注证据等级**。它回答：**"这条命题，跑一遍算不算支持它？形式化检查器认不认？"**

### E.2 职责

| # | 职责 | 判据 |
|---|---|---|
| E-1 | 在**独立进程**里跑工作区脚本，登记 `Experiment` 行 | `agent_e.AgentE.run_experiment`；`verify.run_experiment` 工具 |
| E-2 | **计算类方法拿不到 `proof`**：脚本自报 `proof` 会被**降级**为 `cross_check` | 自检实测："脚本自报 proof 被降级为 cross_check"+"notes 里记下了这次越权" |
| E-3 | 崩溃一律记 `inconclusive` + `no_local_evidence` | 自检实测："崩溃 ⇒ inconclusive"、"崩溃 ⇒ no_local_evidence" |
| E-4 | 超时同样记 `inconclusive` + `exit=None` | 自检实测 |
| E-5 | 查已有证据（**三态**） | `agent_e.AgentE.evidence_for` |
| E-6 | 形式化检查：**没有后端时如实回答「没做」** | `agent_e.AgentE.check_formal`；`checked=False, reason="no_backend", verified=None` |
| E-7 | 绑定脚本的可复现性（`code_hash`） | `verify.code_hash`；`Experiment.code_hash` |

### E.3 明确不负责

| 不做什么 | 为什么不由 E 做 | 该由谁做 |
|---|---|---|
| 说"命题被证明了" | **数值实验不构成证明**（`LESSONS.md` M4；`draft/17` §4.4）；E 的 `proof` 只能来自**形式化检查器**，而桥接层未接线 | **形式化检查器**（外部）/ **人** |
| 把 `supports` 当成 `closed` | 实测断言："只有数值证据却标 closed ⇒ schema 抛（FC-22）" | **F** / **G** 的写入被 schema 硬拦 |
| 写稿件/断言 | 断言的话术、引用、降级规则是 G 的 | **G** |
| 决定要不要再跑一个实验 | E 的动作只有 5 个（`capabilities.CAPABILITIES`），**没有"自己决定再跑"** | **F**（`attack.step` 的 owner 分派）/ **D**（`D → E`） |
| 改关系/概念 | E 的写集只有 `{experiments}` | **B** |
| 判断"这条实验的结论值不值得写进报告" | 价值判断在 G/H | **G** / **H** |

### E.4 工具面（26 个，实测）

**现读**：`python -m agentflow.cli tools --role E` ⇒ `side_effect` read 17 / write_local 9 / none 0；`external` none 24 / exec 2；需审批 10 件。逐件明细（分组清单 + 拿不到什么）见附录 §E.4。

### E.5 状态机（**只留主转移表**；状态/约束/反例表与其余状态机见附录 §E.5）

**(a) `Experiment` 的二维状态（结果 × 证据等级 × 否定分类）**

| 从 → 到 | 允许？ | 谁拦 |
|---|---|---|
| `supports` + `evidence_kind="cross_check"` → 计划 `closed` | ❌ | `verify.proof_claim_rests_on_weaker_evidence`（error）；自检实测："只有数值证据却标 closed ⇒ schema 抛（FC-22）" |
| `supports` ⇒ `negation_kind="not_proved"` | ✅ | 自检实测通过（"result=supports ⇒ negation_kind=not_proved"） |
| `refutes` ⇒ `negation_kind="disproved"` | ✅ | 但必须给 `counterexample` |
| `inconclusive` ⇒ `negation_kind="no_local_evidence"` | ✅ | 自检实测（崩溃/超时/无结论行三条路径） |
| `evidence_kind="proof"` 但无 `verifier_subject_key` | ❌ | `schema.verifier_subject_key` 抛 |
| 依赖 `status="closed"` 而 `experiment.result="inconclusive"` | ❌ | `verify.closed_dep_on_inconclusive_experiment`（error） |

### E.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 脚本超时 | `agent_e.timeout` 默认 **600s** | `agent_e.AgentE.__init__`；工具参数 `timeout` | 自检实测："超时 ⇒ inconclusive / exit=None / notes='[run] exit_code=None，**超时**（timeout=1s），runtime=1.031s，脚本 slow_probe.…'" |
| 一次 `run_experiment` 写几行 | **恰好 1 行** | 自检实测："事务性：experiments 5 -> 6"、"一次 run_experiment 只多一行" | — |
| 路径越界 | 必须来自工作区内相对路径 | 自检实测："路径越界被拒绝" | 拒绝 |
| 脚本自报 `proof` | **降级为 `cross_check`** | `verify.run_experiment` 的 `summary` 逐字；自检实测 | `notes` 记下这次越权 |
| 形式化检查器 | 无后端 ⇒ 不跑 | 自检实测："无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False）" | `checked=False` |
| 超时/崩溃的退出码 | 崩溃 `exit=3`；超时 `exit=None` | 自检实测 | 记 `inconclusive` |
| 子进程环境 | `env = dict(os.environ)`（**继承完整环境，可联网**） | INVENTORY 4.4（`agent_e.AgentE._run_script`） | ⚠️ **未隔离**（FC-07 的"执行进程"档缺失） |

### E.7 三态与失败模式（“已知会犯的错”明细见附录 §E.7）

**E 是全项目三态纪律**做得最完整**的角色** —— 自检逐条断言了它们：

| 场景 | 三态形态（自检逐字） |
|---|---|
| 无形式化后端 | `checked=False` / `reason="no_backend"` / `verified=None`（**不是 `False`**） |
| 两个参数都不给（`evidence_for`） | `checked=False`（没查） |
| 给了参数且命中 | `checked=True` |
| 命中但没有 `proof` | `proved=False` |
| 给了参数但没有 | `checked=True` 且 `experiments=[]` |
| 崩溃 | `result=inconclusive` / `negation_kind=no_local_evidence` / `exit_code=3` |
| 超时 | `result=inconclusive` / `exit=None` / notes 写明"**超时**" |
| 脚本没有结构化结论行 | `inconclusive` / `no_local_evidence` / notes 逐字"脚本未给出结构化结论" |
| 脚本自报 `proof` | `evidence_kind=cross_check` + notes 记下越权 |
| **"查了没有"与"没查"的 reason 不同** | 自检**专门断言**了这一条 |

### E.8 不变式

- `for_question_id` 存在。
- 证据等级不许过度声称（FC-22）。
- 脚本必须有 `code_hash`。
- `refutes` 必须给反例。
- 稿件不得把 `cross_check` 当 `proof`。
- `closed` 的依赖不得指向 `inconclusive` 实验。
- 同 `claim_key` 同口径的数字不许冲突。
- 路径不逃逸工作区。

### E.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`D`（`:598`）、`F`（`:600`）、`G`（`:601`）。
- **E 能召唤谁**：`B`（"引文不可核实 → 请 B 重抽取"）与 `D`（"发现反例 → 回 D"）
  （`capabilities.ALLOWED_EDGES`）。
- **入参从哪来**：`claim` / `claim_key` / `script_path`（调用方给的）；
  `capabilities.CAPABILITIES` 的 params schema 是**唯一**的机器可读契约。
- **产出被谁消费**：
  - `experiments` 行 → **F**（`attack_plans.experiment_ids` / `proof_experiment_ids`）、
    **G**（`documents.claims` 的 `exp:` 引用）、**H**（审校证据）、**D**（`for_question_id`）
  - `evidence_kind` → **G**（断言等级）/ **H**（`overclaim` 检查）

### E.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_e`。**当次（2026-10-18，F-4 修后复跑）**：汇总行**始终打印**、退出码与它同源 ——
出厂默认（`toolchain.lean_enabled` 关闭）下：`SELF-CHECK DONE（agent_e）：25 项通过 / 0 项失败 / 未查 1 段`，**退出码 0**；
把开关打开（`AGENTFLOW_LEAN_ENABLED=1`，形式化路径真的走检查器）后：`SELF-CHECK DONE（agent_e）：27 项通过 / 0 项失败`，**退出码 0**。
「未查 1 段」是形式化路径在开关关闭时**没走检查器**：那一段改判"当场拒绝、不留行、理由给出 V 的替代路线"，记成"未查"（没查 ≠ 通过 ≠ 失败）。
判据：`tests/test_selfcheck_exit_codes.py`（子进程 + 注入失败负控）。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## F —— 多轮难题攻坚

### F.1 一句话定位

**F 产出"过程"，且必须有三维预算与终止条件**。
它回答：**"这个难题，我能在有限预算内推进到哪一步？推不动时我如实说什么？"**

### F.2 职责

| # | 职责 | 判据 |
|---|---|---|
| F-1 | 立项（**预算四类键缺一不可，不完整就拒绝创建**） | `agent_f.AgentF.create_plan`；`attack.check_budget` |
| F-2 | 按确定性次序选下一个子目标 | `attack.pick_next_subgoal`（"开始过的优先，卡住的最后"） |
| F-3 | 推进一轮：按 `owner` 分派（E 做实验 / A 提检索 / B 提重抽取） | `agent_f.AgentF.step` |
| F-4 | **C/D/F 的推理未接线时如实记 `no_change`，绝不假装做了** | `attack.step` 的 `summary` 逐字 |
| F-5 | 到终止条件时交 `best_partial`：**不是失败，也不是成功** | `status="stalled"` |
| F-6 | 数值实验**不许关闭子目标**（FC-22） | 自检实测："数值实验**不许**关闭子目标（FC-22）" |

### F.3 明确不负责

| 不做什么 | 为什么不由 F 做 | 该由谁做 |
|---|---|---|
| 自己"想数学" | `attack.step` 的 `summary` 逐字："C/D/F 的推理**未接线**" —— 本轮的 F 是**确定性调度器**，不是推理者 | 由 `SubagentBackend` 承担（**未接线**） |
| 写知识表 | F 的写集是 `{attack_plans, search_requests, reprocess_requests}` | **B** |
| 把 `supported_not_proved` 说成 `resolved` | FC-22：无任何 `proof` 时计划状态**只能**是 `supported_not_proved` | schema 硬拦（自检实测："计划状态随之变成 `supported_not_proved`（无任何 proof）"） |
| 无限重试 | `TERMINAL_STATUSES` 含 `stalled`；`stalled` 不可重入 | `tools.attack_tools.TERMINAL_STATUSES` |
| 决定难题值不值得攻坚 | 立项是**D 的升级决定**（I10） | **D**（`D → F`） |
| 审校自己的攻坚过程 | F 是产出者 | **H** |

> ⚠️ **`AgentF._deploy_e` 曾没有降级路径**（`draft/13` §8.6），现已是
> `blocked` + `blocked_reason` 并继续（FC-21 部分落地）。**无
> `run_best_effort` / `run_all_or_nothing` 两种显式 API**（实测 0 命中）。

### F.4 工具面（37 个，实测）

**现读**：`python -m agentflow.cli tools --role F` ⇒ `side_effect` read 21 / write_local 11 / none 5；`external` none 35 / exec 2；需审批 12 件。逐件明细（分组清单 + 拿不到什么）见附录 §F.4。

### F.5 状态机（**只留主转移表**；状态/约束/反例表与其余状态机见附录 §F.5）

**(a) `attack_plans.status`**

`ATTACK_STATUSES = ("open","attacking","progress","supported_not_proved","stalled","resolved","abandoned")`（`schema.ATTACK_STATUSES`）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `todo → in_progress` | ✅ | — |
| `in_progress → closed` | ✅ **仅当有 `proof` 级证据** | FC-22；自检实测 |
| `in_progress → supported_not_proved` | ✅（只有 `cross_check` 时唯一合法终点） | `agent_f._subgoal` |
| `in_progress → blocked` | ✅（**必须写 `blocked_reason`**） | `schema`；自检实测："卡点写进 `blocked_reason`（不许静默卡住）" |
| `closed → in_progress` | ❌（终态不可重入，自检实测） | `agent_f._subgoal` |
| `blocked → in_progress` | ✅（若卡点解除） | — |

### F.6 预算与终止条件（**FC-18 的落地核心**）

`tools.attack_tools.DEFAULT_BUDGET`—— **四类键必须都在**：

| 键 | 默认值 | 维度 | 缺了会怎样（`tools.attack_tools.check_budget` 逐字） |
|---|---:|---|---|
| `max_rounds` | **6** | 生命周期总量 | "只有轮数上限则单轮可无限扇出" |
| `max_parallel_subgoals` | **2** | 单批规模 | 单轮可无限开子目标 |
| `max_persist_attempts` | **2** | 重试 | 落库可无限重试 |
| `max_depth` | **2** | 嵌套深度 | 可无限派生子计划 |

`check_budget` 的三态（`tools.attack_tools.check_budget`）：

| 输入 | `checked` | `complete` | `allowed` | `reason` |
|---|---|---|---|---|
| `budget=None` | **`False`** | `False` | **`None`** | "没有提供预算 ⇒ **没检查**。注意这与'预算用尽'是两件事" |
| 缺键 | `True` | `False` | `False` | 列出 `missing` |
| 完整 | `True` | `True` | `True` | 回显四类键 |

`tools.attack_tools.can_round`：`rounds_done >= mr` ⇒ `allowed=False, blocked_by="rounds"`；
`depth >= md` ⇒ `allowed=False, blocked_by="depth"`；
**`allowed=False` 可能来自两个不同维度 ⇒ 调用方必须看 `blocked_by`**。

`can_derive` 与 `can_round` **刻意分开**："一个计划'自己还能跑'与'还能再分子问题'是两个独立的问题，
共用一个布尔会让深度到顶的计划被误判成'该停了'。"

**上限用尽时会发生什么**（自检实测）：
1. 先试**提前停止**：连续 3 轮 `no_change` ⇒ `stalled`，`rounds=5 < max_rounds=6`；
2. 关闭提前停止后 ⇒ 真的跑到 `max_rounds`（`rounds=6`）；
3. **两个方向都有测试**（"[PASS] 提前停止关闭时，轮数真的跑到 `max_rounds`（两个方向都测到）"）；
4. `best_partial` **必须非空且如实**；
5. `stalled` 后**不再推进**。

### F.7 三态与失败模式（“已知会犯的错”明细见附录 §F.7）

| 场景 | 三态形态 | 依据 |
|---|---|---|
| 预算没给 | `checked=False` / `allowed=None` / `blocked_by="not_checked"` | `tools.attack_tools.check_budget` |
| 预算不完整 | `checked=True` / `complete=False` / `allowed=False` / `blocked_by="incomplete"` | `tools.attack_tools.check_budget` |
| **`can_derive` 在 `checked is False` 时返回 `blocked_by="incomplete"`** | ❌ **已知折叠**：用"不完整"这个标签表示"没检查"，**正是模块 docstring 自己警告的那种折叠** | INVENTORY 4.5#12 |
| 子目标未接线 | `action="no_change"` / `outcome="no_change"` / detail 明说"未推进" | 自检实测 |
| 同一未接线子目标 | `in_flight` 过滤 ⇒ **不会被反复重选** | 自检实测 |
| 计划不存在 | `ok({"checked": False, "reason": "计划 … 不存在 ⇒ **没查**"})` —— 信息诚实但 `res.ok is True` | INVENTORY 4.3(c) |
| 数值实验想关子目标 | ❌ schema 抛 | 自检实测 |
| 只有数值证据却标 `closed` | ❌ schema 抛 | 自检实测 |

### F.8 不变式

- `for_question_id` 存在。
- `parent_plan_id` 存在。
- `experiment_ids` 存在。
- `stalled` 必须写 `best_partial`。
- `blocked` 子目标必须写 `blocked_reason`。
- `history` 轮次单调不减。
- 预算四类键齐全。

### F.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、`D`（`:598`，I10 升级）、`G`（`:601`）。
- **F 能召唤谁**：`A B C D E`（`capabilities.ALLOWED_EDGES`）—— "攻坚需要一切"。
  **不能召唤 G/H。**
- **入参从哪来**：`attack_plans` 行（F 自己写）+ `capabilities.CAPABILITIES` 的 4 个动作 schema。
- **产出被谁消费**：
  - `attack_plans` → **D**（`attack.status`）、**G**（写稿读攻坚结论）、**H**（核对 `stalled` 有没有谎报成 `resolved`）
  - `search_requests` / `reprocess_requests`（F 提交的）→ **A** / **B**
  - `experiments`（经 E）→ **G** / **H**

### F.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_f`。**当次（2026-10-18）**：`SELF-CHECK DONE（agent_f）：失败 0 项`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## G —— 论文撰写

### G.1 一句话定位

**G 产出"稿件"，每条断言必须带引用**。
它回答：**"这些结论怎么写进一份可审的稿子里？哪些结论只能降级成 Remark？"**

### G.2 职责

| # | 职责 | 判据 |
|---|---|---|
| G-1 | 构造合规断言（**`cross_check` 自动补"不构成证明"**） | `agent_g.compose_claim`；`CROSS_CHECK_DISCLAIMER` |
| G-2 | 登记外部依赖（FC-23）：`closed` 时**先用真实数据核来源** | `agent_g.register_dependency` |
| G-3 | 写 `documents` 行并渲染 markdown | `agent_g.build_document` |
| G-4 | 渲染（不写库、不落盘） | `agent_g.render` |
| G-5 | 按库里当前数据重画 markdown（**不改数据行，只改文件**） | `agent_g.refresh_markdown` |
| G-6 | 按 H 的发现修订稿件 | `agent_g.revise`；`review_rounds+1`、`status=revised` |
| G-7 | **按体例写正文**（2026-10-18 起）：骨架顺序固定、第 3 节 ≥6 个定理/引理/命题且每个带分步 `proof`、正文禁令六项、内部编号与计算证据只进附录 A | `specs/g.py::SPEC.brief.policy` 里 2026-10-18 那四条；`tests/test_agent_prompts.py` 的冻结摘要 |

> **2026-10-18 起**：论文正文的体例（骨架 / 第 3 节证明线 / 正文禁令 / 附录 A 落点）不再只活在 G 的手感里 —— 它是 `specs/g.py::SPEC.brief.policy` 的四条硬条目，并由 H 的审稿清单逐条对拍（H-8）。G 原有的六条动作职责（G-1…G-6）不变。

### G.3 明确不负责

| 不做什么 | 为什么不由 G 做 | 该由谁做 |
|---|---|---|
| 审自己的稿 | 自己审自己无法区分"发现"与"掩盖" | **H** |
| 判一条断言是否被证明 | 证明要求 `proof` 级证据，那是 E 的形式化检查器的产出 | **E** + **形式化检查器** |
| 编造引文 | 该链路已被 schema 硬拦（"没有引用的断言不允许进入稿件"，见自检逐字） | — |
| 把只有数值支撑的结论放进主结果 | 硬性降级规则（`draft/17` §8.3 的 `allowed_use`） —— ⚠️ **该字段在当前 schema 里不存在**（实测 `allowed_use` 0 命中） | 现在只有"自动附加免责声明"这一层保障 |
| 改知识表 | G 的写集是 `{documents, dependencies, review_findings}` | **B** |
| 检索/实验 | 网络副作用归 A；子进程归 E | **A** / **E** |
| 决定依赖"够不够闭" | G 只能**登记**，闭合检查在 `verify` 与 H | `verify.dangling_dep` / **H** |

### G.4 工具面（38 个，实测）

**现读**：`python -m agentflow.cli tools --role G` ⇒ `side_effect` read 21 / write_local 12 / none 5；`external` none 35 / exec 3；需审批 13 件。逐件明细（分组清单 + 拿不到什么）见附录 §G.4。

### G.5 状态机（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §G.5）

**(a) `documents.status`**

`DOC_STATUSES = ("draft","in_review","revised","accepted","rejected","unresolved_review")`（`schema.DOC_STATUSES`）。

| 迁移 | 触发者 | 允许？ |
|---|---|---|
| `draft → in_review` | H 审校（`review.review_document`，写侧） | ✅ |
| `in_review → revised` | **G** 的 `revise()` | ✅ |
| `in_review → accepted` | H（仅在 `error_count == 0` **且** `dep_checked` 时；由 `review_document` 判并**当场签名**） | ✅ |
| `in_review → unresolved_review` | H 到轮数上限 | ✅ |
| `accepted` → 任何 | — | ❌（`verify.accepted_with_open_error` 会抓"accepted 但有 open error"） |
| `revised → in_review` | H 复审（`verify_fixes`；**复审通过也不再直接回 `accepted`** —— 见下） | ✅ |

### G.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 审校轮数 | `review_rounds` 上限（H 侧，`review_findings` 的 `verify_fixes` 轮数） | `tools.review_tools.verify_fixes` | `unresolved_review`（**并列出未解决项**） |
| 一次 `build_document` 的断言数 | 无显式上限（`maxItems` 未设） | `capabilities.CAPABILITIES` 的 params | ⚠️ **无上限**（**未核实是否有间接约束**） |
| 依赖登记数 | 无显式上限 | `capabilities.CAPABILITIES` | ⚠️ 无上限 |
| `out_path` | 必须是工作区内相对路径 | `doc.build_document` 的 `summary`："`out_path` 越界即拒绝" | 拒绝 |

> ⚠️ **G 的循环最少**：G 的动作里没有"重试/循环"（`capabilities.CAPABILITIES`），
> 它的终止由**调用方**决定。这与 F（有三维预算）形成对比。

### G.7 三态与失败模式（“已知会犯的错”明细见附录 §G.7）

| 场景 | 三态形态 | 依据 |
|---|---|---|
| `cross_check` 断言 | **自动**补 `CROSS_CHECK_DISCLAIMER`（"不构成证明"），**不靠人写** | `doc.compose_claim` 的 `summary` 逐字 |
| 无引用 | **构造时就抛错**（"不等写库"） | `doc.compose_claim` 的 `summary` |
| 否定未分类 | **构造时就抛错** | 同上 |
| 过度声称 | **构造时就抛错** | 同上 |
| 断言引用不存在的文献 | ❌ **已知缺陷**：`scan_claim` 只检查 `citations` 非空且非空白，**从不解析** `lit:`/`rel:`/`exp:` 是否真实存在 ⇒ `citations:["lit:9999"]` **会通过全部闸门，`documents` 行被写入、markdown 被渲染** | INVENTORY 4.3(a)② |
| 依赖 `closed` 但来源不存在 | ✅ **会被拦**（`register_dependency` 真去核表） | INVENTORY 4.3(a)② 的对比 |
| 文档状态更新失败 | **如实记录而不是假装成功** | `agent_h` 自检逐字："（状态未更新，**如实记录**而不是假装成功：`ValueError: documents.rows[2] 校验失败：claims[claim-9] 没有 citations`）" |

### G.8 不变式

- 断言必须有引用。
- 引用必须能解析（`rel:` / `lit:` / `exp:` / `eval:`）。
- 未知引用种类。
- 不得引用被否关系。
- 引用 `suspect` 关系。
- 不得过度声称（FC-22）。
- `proof` 断言的所有依赖必须闭合。
- `proof` 断言不得挂在被证否的依赖上（§9）。
- `proof` 断言不得挂在尚未裁决的依赖上（§8）。
- 依赖悬空。
- 依赖本身被证否 / 有争议。
- 命题的出处（文献 / 稿件）必须存在。
- 承重链不得缺环（`derived_from`）。
- `proof` 级命题不得压在不可用的命题上。
- `active` 的文献命题必须逐字回验过。
- `closed` 依赖不得指向 `inconclusive`。
- 依赖的 `used_by` 指向的稿件存在。
- 数组字段已声明。

### G.9 接口

- **能被谁召唤**：`M`（`capabilities.ALLOWED_EDGES`）、**`H`**（`:602`，"审校发现问题 → 请 G 修订"）。
  **G 不能被 A/B/C/D/E/F 召唤。**
- **G 能召唤谁**：`A D E F`（`capabilities.ALLOWED_EDGES`）—— "写稿时发现缺证据 → 回去要"（`A` 是 2026-10-13 加的：缺证据时要能直接再检索一轮）。
- **入参从哪来**：`relations` / `experiments` / `analysis_reports`（别人的产出）；
  `capabilities.CAPABILITIES` 的 6 个动作 schema。
- **产出被谁消费**：
  - `documents` 行 + `reports/*.md` → **H**（审校）、人
  - `dependencies` → **verify**（闭合检查）
  - `revise()` 消费 **H 的 `review_findings`**

### G.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_g`。**当次（2026-10-18）**：`SELF-CHECK DONE（agent_g）`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## H —— 审校（只读）

### H.1 一句话定位

**H 产出"发现"，且发现本身必须有证据**，并且**只读**。
它回答：**"这份稿件有没有不合格的地方？改过之后真的改好了吗？"**

**H 是唯一"能写，但只能写两样东西"的角色**：`review_findings`（自己的发现）
与 `documents.status`（只改状态，**改不了任何一句断言**）。
`capabilities.READ_ONLY_WRITE_EXCEPTIONS["H"]` 逐字登记了这个例外
（`capabilities.READ_ONLY_WRITE_EXCEPTIONS`）。

### H.2 职责

| # | 职责 | 判据 |
|---|---|---|
| H-1 | 对一份稿件做全量机械审校 | `review.scan_document`（工具，`none`） |
| H-2 | 落发现 + 更新文档状态（**必须在被钉死的 `writers` 注册表里**） | `agent_h.AgentH.review`；`review.review_document`（写侧） |
| H-3 | 复审：重跑检查判 `fixed` / 仍 `open`；到上限则 `unresolved_review` | `agent_h.AgentH.verify_fixes`；`review.verify_fixes`（写侧） |
| H-4 | 只读列举发现 | `agent_h.AgentH.list_findings` |
| H-5 | **依赖分级**（FC-13）：`external_unavailable`=warning，`dangling`=error | `tools.review_tools.scan_document`；自检实测逐字 |
| H-6 | 请 G 修订 / 向 A 核引文 / 向 E 核形式化 | `H → G`、`H → A`、`H → E`（`capabilities.ALLOWED_EDGES`） |
| H-7 | **采信规则**（`draft/37` §16 P2）：采信一条命题只有两条路 —— 正文与 B 的台账**逐字一致**（`statements.quote_verified is True` 且文本可比对）+ E 的背书（`experiments.evidence_kind="proof"`）；两条都不在只能说"这条我采信不了" | 提示词口径（`ROLE_BRIEFS["H"].boundary`）；`tests/test_review_line_prompts.py` 的 H 组事实 |
| H-8 | **按体例逐条打勾**（2026-10-18 起）：机器可判四条（proof 环境数 ≥6 / 正文内部编号 ==0 / 正文无「数值实验」类小节 / 有 Abstract＋`\bibitem`＋Appendix A）＋正文禁令六项＋骨架与证明粒度；发现稿子是研究报告 ⇒ 落 error 级 finding、裁决 `rejected`，**不许 `accepted`** | `specs/h.py::SPEC.brief.policy` 里 2026-10-18 那五条；`review.record_finding` |

> **2026-10-18 起**：H 判的不再只是「说清楚没有」这一档 —— 论文体例的机器可判四条与正文禁令成为**可逐条打勾的审稿清单**（`specs/h.py::SPEC.brief.policy`），任何一条不合格都落 finding；「稿子读起来是研究报告」这一形态的裁决不许 `accepted`（error 级 ⇒ `rejected`，只报 warning 也只能是 `accepted_with_warnings`）。采信规则（H-7）不变。

> **2026-09-30（`draft/28` §199，人批准）**：H 的出边由 `{G}` 扩到 `{A, E, G}`。
> 原状的理由是"审校者若能让别人改数据，它就同时是发现者与修正者" —— 那条理由
> 针对的是**改数据**；而 A 的检索与 E 的形式化都**不改 H 正在审的那份稿**
> （A 写 `literature`/`search_requests`，E 写 `experiments`）。原来的实际后果是：
> 审校时发现"这条引文对不上"，H 唯一的动作是把问题退回给写稿的 G ——
> 而 G 也未必拿得到那份原文。**H 仍然是只读角色**（`READ_ONLY_ROLES` 未动、
> 工具面未动）：新边只让它"请求核实"，不让它"自己改"。

### H.3 明确不负责

| 不做什么 | 为什么不由 H 做 | 该由谁做 |
|---|---|---|
| **改稿件的任何一句断言** | "若审校者能直接改稿，它就同时是'发现者'与'修正者'，于是**'发现问题'与'掩盖问题'在结构上无法区分**"（`tools/__init__.py` 的模块 docstring 逐字） | **G**（`revise`） |
| 写知识表 | H 的写集只有 `{review_findings, documents}` | **B** |
| 召唤除 A / E / G 以外的任何人 | "审校者若能让别人改数据，它就同时是发现者与修正者"（`capabilities.ALLOWED_EDGES` 逐字）—— 该理由针对"改数据"；A/E 不改 H 审的那份稿（`draft/28` §199） | — |
| 决定一条发现要不要修 | H 只**报**；修与不修是 G/人的决定（`wontfix` 是**人**的判断） | **G** / 人 |
| 判数学对错 | H 的工具只有机械判据（引用/等级/否定/依赖闭合）；**数学正确性不在机械判据的射程内** | 形式化检查器 / 人 |
| 自己造证据 | 每条发现必须带 `evidence`；没有证据的发现是 error | `verify.finding_without_evidence`（error） |

### H.4 工具面（31 个，实测）

**现读**：`python -m agentflow.cli tools --role H` ⇒ `side_effect` read 22 / write_local 4 / none 5；`external` none 31；需审批 4 件。逐件明细（分组清单 + 拿不到什么）见附录 §H.4。

### H.5 状态机（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §H.5）

**(a) `review_findings.status`**

`FINDING_STATUSES = ("open","fixed","wontfix","disputed")`（`schema.FINDING_STATUSES`）。

| 迁移 | 触发 | 允许？ |
|---|---|---|
| `open → fixed` | `verify_fixes` 重跑检查，**发现消失** | ✅ |
| `open → open` | 重跑发现仍在（自检实测："未解决：✗ 0000 overclaim @claim-1 level=error"） | ✅（复发） |
| `open → disputed` | 人/G 明确不认同 | ✅（`disputed` 也算终结） |
| `open → wontfix` | 人决定不修 | ✅ |
| `fixed → open` | ❌（终态；实测"复审：error 一直不修 ⇒ 到轮数上限必须置 `unresolved_review`"） | `tools.review_tools.verify_fixes` |

### H.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 审校轮数 | `review_rounds` 上限 | `tools.review_tools.verify_fixes` | `unresolved_review` + **列出未解决项**（自检实测："`verdict=unresolved_review resolved=0 still_open=4 未解决(error)=3`"） |
| 同稿重复审 | **去重**（同一发现不重复落行） | 自检实测："去重：同一份坏稿件再审一次 ⇒ 新增=0 重复跳过=4 finding 行数 5 → 5" | — |
| 每条发现的信息量 | 必须带 `evidence`（含**实际值**） | 自检实测逐字："`unsupported_claim` 的 evidence（必须含实际值）：'`claim_id=claim-9` 的 `citations=[]`（空）'" | `verify.finding_without_evidence`（error） |

> ⚠️ **`review_rounds` 的具体上限值**：本次**未在代码中核到显式常量**
> （`tools.review_tools.verify_fixes` 是"到轮数上限时"的分支，上限来自调用方传入的 `round_no`
> 与稿件行的 `review_rounds`）。**标 `（未核实具体数值）`**。

### H.7 三态与失败模式（“已知会犯的错”明细见附录 §H.7）

| 场景 | 三态形态（自检逐字） |
|---|---|
| **明确传 `dependencies=None`** | `dep_check.checked=False` / `verdict=unverified` / reason 逐字"依赖闭合**没查**（调用方未提供 `dependencies` ⇒ **没查依赖闭合**（不得读成'依赖都闭合'））⇒ 不能判 `accepted`" |
| 未解决发现 | `verdict=unresolved_review` + `unresolved_findings` 列表 |
| 修好后复审 | 逐字"修好后 → 复审 `verdict=accepted resolved=1 still_open=0` 库中状态=`accepted`" |
| **依赖分级** | 逐字"依赖分级（FC-13）：`external_unavailable`=warning（应为 warning）、`dangling`=error（应为 error）" |
| **文档状态更新失败** | 逐字"状态未更新，**如实记录**而不是假装成功" |
| `review.scan_document` 的 `dep_check` 与 `verdict` 矛盾 | ❌ **已知缺陷**（INVENTORY 4.3(a)①） |

### H.8 不变式

- 发现指向的稿件存在。
- 发现必须带证据。
- `accepted` 稿件不得有 open error。
- `proof` 断言的依赖闭合（H 是复核方）。
- 证据等级不得过度声称。
- **H 的写面只有 3 件已登记的落库代理**。
- **H 只召唤 `A E G`**。

### H.9 接口

- **能被谁召唤**：`M` 与 `B`（`capabilities.ALLOWED_EDGES`）。`D`/`E`/`F`/`G` 都不能召唤 H
  —— **"产出者不能指挥审校者"这条一般规则不变**；`B→H`（2026-10-14 业主裁定）是它唯一登记的例外：
  「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」⇒ **逐字那一档 B 自己走**
  （`quoteverify.check_quote`，不花模型钱，先走它），**逐字不中而语义相同**的由 **H 判**
  （`judge_quote_semantics`），B 拿判定回填 `quote_verified` + `quote_mode="semantic"`
  —— H 仍只读，落库代理仍钉死在 `review_findings` / `documents.status` 上（"判"与"落"分居两处）。
- **H 能召唤谁**：`A E G`（`capabilities.ALLOWED_EDGES`）。
- **入参从哪来**：`documents` 行 + `dependencies`（**必须由调用方显式提供**，
  不提供就 `checked=False`）；`capabilities.CAPABILITIES` 的 3 个动作 schema。
- **产出被谁消费**：
  - `review_findings` → **G**（`revise` 按 `fixed_findings` 修改）、人
  - `documents.status` → **G**（`revise` 前要读到 `in_review`）、**verify**

### H.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_h`。**当次（2026-10-18）**：`SELF-CHECK DONE（agent_h）`；**退出码 0**。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## V —— 证明级验证（只读）

### V.1 一句话定位

**V 把一份证明按写成后的样子整体重读一遍，给三态结论并签"审过"（五元位第 3 位）**，并且**只读**。
它回答：**"这份证明站不站得住？站不住的是哪一步？"**

**V 是唯一"能写，但写的是一个文件、不是一张表"的角色**：唯一的产物是
`<工作区>/verifications/<命题号>.jsonl`（追加式，一行 = 一次审校）。
`capabilities.WRITE_SETS["V"] == frozenset()`（空集）与 `tools.READ_ONLY_ROLES = ("C","H","V")`
一起说这件事：**在"会写哪几张表"这根轴上是只读的，而它确实要落一样东西** ——
两者不矛盾，只是分处两根轴（`schema.TABLES` 是 **16** 张，V 一张都没加）。

### V.2 职责

| # | 职责 | 判据 |
|---|---|---|
| V-1 | **I12 冷启动**：每次审校开新会话，只给对象（证明全文）与只读读数；**不给 F 的叙述、不给 store 句柄** | `verifications.cold_start_prompt`（纯函数：签名里没有 `store`/`conductor`/`registry`/`session_root`）；`verify.verify_proof`（工具） |
| V-2 | **I10 硬禁令 + 同段依据**：逐条查无条件前提 / 无依据的步骤 / `易证`·`显然`·`trivial` 这类缝 / 引用的命题是否干净；**每条问题指到那一步** | `verifications.HARD_BAN_MARKERS` / `banned_markers_in`；`verifications.parse_verdict`（`verdict="有毛病"` 必须给 `defect_step`，否则抛 `VerificationError`） |
| V-3 | **I17 整篇重读**：把证明当**一次输入**整体读（"缝正是正确的事实变成错误证明的地方"），不只逐单元核对 | `verifications.cold_start_prompt` 把证明全文整段放进一次调用；`agent_v.AgentV.verify_proof` 一轮一次模型调用 |
| V-4 | 给三态结论并落台账：一行 = 一次审校（`v-NNNN` + 三态结论 + 逐条 findings 带步号 + 被审证明的 `sha256`） | `verifications.record_verification`；`verifications.VERDICTS` |
| V-5 | **签五元位第 3 位**：**只有 `verdict="成立"` 且 findings 里没有未解决的 `error`** 才签；签不了就让它空着 | `verifications.signs_bit3` / `bit3_payload`；`evidencebits.bits_of` |
| V-6 | 只读侧：读回被审的证明全文、列验证台账（回答"这份证明到底审过没有"） | `verify.read_proof`、`verify.list_verifications` |
| V-7 | **退回 F**：把"有毛病"说成可操作的信息（哪一步、缺什么依据、补上之后能不能过） | `V → F`（`capabilities.ALLOWED_EDGES`） |

### V.3 明确不负责

| 不做什么 | 为什么不由 V 做 | 该由谁做 |
|---|---|---|
| **写、改证明的任何一句** | V 是判定者："你是判定者，你的产出只有一个三态结论与逐条 findings"（`specs/v.py` 的 `local_notes['敢创新']` 逐字）；能改稿的人不能同时是判它过没过的人 | **F** |
| 判"这条命题值不值得做、下一步往哪儿走" | 那是**方向判断**，不是证明判断；V 的官能表里 `敢创新` 是 `denied` | **D** |
| 稿件级正式审查（体例 / 引用是否得当 / 依赖闭合） | 那是**五元位第 5 位**，owner 是 H；V 只看证明本身 | **H** |
| 写任何一张表 | `capabilities.WRITE_SETS["V"] == frozenset()`；`for_role("V")` 的结构性剥离把它拿到的写工具全剥掉 | **B / D / E / G**（各自的写面） |
| 自己补证据、自己提新方向 | 引用到"不干净的命题"时，缺陷**沿依赖边上溯**并如实报出 —— 修是 F/D 的事 | **F**（改证明）/ **D**（改方向） |
| 拿"看不出来"冒充"审过了" | "检查器自己没跑成"不是三个结论之一：它是**没查成**，不许折平（`verifications.parse_verdict` 的 docstring 逐字） | —（结构性禁止） |
| 靠"再问 F 一句"补齐判断所需的信息 | 那会把冷启动绕过去；判不了就写 `看不出来`（`specs/v.py` 的 `policy` 逐字） | — |

### V.4 工具面（15 个，实测）

**现读**：`python -m agentflow.cli tools --role V` ⇒ `side_effect` read 15 / write_local 0 / none 0；`external` none 15；需审批 0 件。逐件明细（分组清单 + 拿不到什么）见附录 §V.4。

### V.5 状态机（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §V.5）

**(a) 一次审校的迁移（台账里的一行）**

`收到提交 → 冷启动读整篇 → 出 findings → 给三态结论 → 落台账一行（v-NNNN）→
[`成立` 且无未解决 error ⇒ 签第 3 位] → 交回 F`

| 迁移 | 触发 | 允许？ |
|---|---|---|
| `收到提交 → 落台账`（`成立`） | 证明站得住、findings 里没有 `error` | ✅（**并签第 3 位**） |
| `收到提交 → 落台账`（`有毛病`） | 命中硬禁令 / 缺依据 / 引到不干净的命题，且给了 `defect_step` | ✅（**不签**；`V → F` 退回） |
| `收到提交 → 落台账`（`看不出来`） | 信息不足、判不了 | ✅（**不签**；它不是 `成立`） |
| `收到提交 → 不落台账` | 输出不合法 / 取值不在词表 / `有毛病` 没给 `defect_step` | ❌ **没查成**（`VerificationError`） |
| `有毛病 → 收到提交` | F 改过（或没改）再交一次 | ✅（**新的一行**，不覆盖旧行 —— 台账只追加） |

### V.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 一轮审校的模型调用 | **1 次**（I17：整篇一次读，不逐单元往返） | `agent_v.AgentV.verify_proof` | 没有模型缝 ⇒ `checked=False` + `reason="judge_not_wired"`（**如实报"没查成"**，绝不拿确定性文本假装审过） |
| 同一命题的台账行数 | **不设上限**（只追加；每一轮审校一行） | `verifications.record_verification` | 新的一行，旧行原样保留 |
| 台账读取的条数 | `limit=None` ⇒ 全量；`limit=0` ⇒ **零条**；`limit=n>0` ⇒ 末尾 n 条 | `verifications.list_verifications` | 三态语义（"要零条"与"要全部"是两件事） |
| 终止条件 | 三态结论之一落台账即终止；**"没查成"不是终止** —— 它不落行、如实报出来 | `verifications.parse_verdict` | 不落行 |
| 命题号 | 必须 **六位十进制**（旧数据里的四位仍可读） | `verifications.verification_ledger_path` | 抛 `VerificationError`（`verify.verify_proof` 回报 `reason="bad_statement_id"`） |

### V.7 三态与失败模式（“已知会犯的错”明细见附录 §V.7）

**三态（对证明的结论，都不是"没查成"）**：

| 结论 | 含义 | 落台账？ | 签第 3 位？ |
|---|---|---|---|
| `成立` | 站得住（findings 为空或只有 `info`/`warning`） | ✅ | ✅（**且** `unresolved_errors == 0`） |
| `有毛病` | 至少一处站不住；**必须**给 `defect_step` | ✅ | ❌ |
| `看不出来` | 信息不足、判不了（**诚实结论，不是客气的退让**） | ✅ | ❌ |

### V.8 不变式

- **V 的工具面 0 个写工具**。
- **输出不合法绝不落台账行**。
- **台账只追加、编号由脚本发**。
- **第 3 位只在 `成立` 且无未解决 error 时被签**。
- **冷启动没有句柄**。
- **命题号必须是六位十进制（旧四位可读）**。
- **`limit=0` 是零条**。
- **V 不写任何表**。
- **V 只能召唤 F**。
- **V 只能被 `B` / `F` 召唤**。
- **V 的只读读数由调用方取好传进来**。

### V.9 接口

- **能被谁召唤**：`M` / `B` / `F`（`capabilities.ALLOWED_EDGES`）；`D` / `E` / `G` / `H` 不能直接召唤 V。
  V 的对话对象仍是 F（"提交/退回"那条边是 `F ↔ V`），而 `B→V` 是 2026-10-13 加的那条
  （业主逐字：「允许 B 唤起 V。理由是 B 需要初步检验收录的证明」）；`M→V` 是 **2026-10-18 加的那条**
  （业主逐字「给 M 开 V 出边」：`projects/t3d` 三·1 的读数 `reviewed_proof_rows = 0`，
  V 只能经 `F→V`、那一趟没走那条链 ⇒ 证明级断言一行都没被逐行走查签过名）。
  复跑：`python -c "from agentflow import capabilities as C;print(sorted(C.ALLOWED_EDGES['M']))"` ⇒ 含 `V`。
- **V 能召唤谁**：**只有 `F`**（`capabilities.ALLOWED_EDGES["V"] == {"F"}`）。
- **入参从哪来**：`statements` 行（命题全文与完整假设）+ `proof_text`（不给时从 `statements` 取）
  + 调用方取好的 `readonly_facts`（只读读数：命题现状 / 文献与实验台账摘要 ——
  传字符串而不是传 `store`，是为了让"它能碰什么"在接口上就固定下来，I12 的结构形态）。
- **产出被谁消费**：
  - `verifications/<命题号>.jsonl` 那一行 → **F**（退回时的可操作依据）、
    **收工门**（`reviewed_proof_rows`）、**`evidencebits`**（五元位第 3 位那份凭据）
  - `verify.list_verifications` / `verify.read_proof` → 任何需要回答"审过没有"的只读面
- **动作 schema**：三个动作的 `params`/`returns`/`side_effect`/`handler_name` 见
  `capabilities.CAPABILITIES` 与 `specs/v.py`；`§R0` 的 #67–#69 是它们的逐个契约。

### V.10 自检入口

**命令**：`$env:PYTHONPATH='src'; python -m agentflow.agent_v`。**当次（2026-10-18，F-5/F-6 修后复跑）**：`SELF-CHECK DONE（agent_v）：17 项通过 / 0 项失败`；**退出码 0**。
台账编号是**六位**（`v-000001`；发号点 `verifications.next_verification_id` 走 `schema.format_id`，旧四位号读侧兼容）；五元位第 3 位的 owner **就是 V**（`evidencebits.BIT_OWNERS["reviewed"] == "V"`，实际签名者 `reviewed_by.verifier == "agent-V"`）。
明细（覆盖/未覆盖对照、失败项）见附录「A.10–M.10」与 [`SELF-CHECK-FINDINGS.md`](SELF-CHECK-FINDINGS.md)。

## M —— 主控（Conductor）

### M.1 一句话定位

**用户唯一面对的东西**。它回答：**"为了这个目标，该召唤谁、按什么顺序、花多少预算、被拦住时说什么？"**

**M 不是一个额外的"智能层"**：它**不做 LLM 推理**（`conductor.py` 的模块 docstring 逐字：
"本模块里**没有**任何 LLM 调用 —— 真 LLM 主控由 `SubagentBackend` 承担（本轮显式未接线）"）。
它**确定性地执行调用方给的 plan**。这让 M 可测试：M 的"正确性" =
它发出的召唤序列是否满足策略与预算，而不是"它聪不聪明"。

### M.2 职责

| # | 职责 | 判据（实现位置） |
|---|---|---|
| M-1 | **单件召唤的入口**：`summon(role, action, params, by, parent_task_id, input_key, budget, token, lineage)`（批量的那条是 `conductor.summon_many`，见 §R0 的第 79 行与 §M 的"批量入口"） | `conductor.summon` |
| M-2 | 过策略：角色/动作存在性、边、深度、扇出、循环、并发、总量、预算、墙钟 | `policy.check_action` / `policy.check` |
| M-3 | 写台账（**每个 start 恰好一个 end**） | `Conductor._write_row` / `conductor.finish` |
| M-4 | 派给 backend（`LocalBackend` / `SubagentBackend`） | `conductor.SubagentBackend` |
| M-5 | **拒绝也落台账**（`status="done", outcome="refused"`） | `conductor.Conductor._refuse` |
| M-6 | 波浪调度（写集不相交的并发） | `Conductor.run_plan` → `scheduler.run_waves`（`conductor.Conductor.run_plan`） |
| M-7 | 协作式取消（一个共享 signal 覆盖在飞与待启动） | `Conductor.cancel` / `conductor.dispose` |
| M-8 | 幂等销毁，合成 `cancelled` 的 end | 同上 |
| M-9 | 台账的可读视图与统计 | `Conductor.tree` / `conductor.stats` |
| M-10 | **自己的不变式自检** | `conductor.Conductor.verify_tasks` |
| M-11 | 汇总给用户，并把**交付说明落盘**（`out/review/REPORT.md`，用 `fs.write` 写） | `conductor.state`/`ledger` + `fs.write`（`draft/37` §38/§41 的用户裁定；这一格在 2026-10-02 之前写的是"M 本身**不产出报告文件**"—— 那是那条裁定之前的实情） |

### M.3 明确不负责

| 不做什么 | 为什么不由 M 做 | 该由谁做 |
|---|---|---|
| 产出知识（概念/关系/文献） | "它不产出知识、不写关系、不改稿件"（`DESIGN-CONDUCTOR.md:37`）；`WRITE_SETS["M"] = frozenset()` | **A** / **B** |
| 写任何领域表 | 同上；M 只写 `tasks`（`CONDUCTOR_WRITE_SET`，`capabilities.CONDUCTOR_WRITE_SET`）+ 交付说明文件 `out/review/REPORT.md`（文件面白名单，不是表） | 各角色 |
| 把外部论文当成我方稿件 | 外部论文走 `literature` + `statements`（A / B），我方修订稿才由 G `build_document` 另起一行 `documents`（`draft/37` §41 的方案 A；`Document.validate()` 要求 claims 非空） | **A** / **B** / **G** |
| 有领域动作 | `CAPABILITIES["M"] == ()` —— **可断言的事实**，不是一个约定 | 各角色 |
| 用 LLM 决定"想做什么" | 本轮 M 是**确定性策略执行者**；plan 由调用方给 | `SubagentBackend`（**未接线**） |
| 成为"谁能召唤谁"的特权路径 | M 也在角色空间里（`schema.CONDUCTOR_ROLE`）："特例化会是权限模型最容易漏的地方"（`DESIGN-CONDUCTOR.md:40`） | — |
| 被召唤 | `NON_SUMMONABLE = {"M"}`："**没人能召唤主控**"（没有"召唤 M"这件事） | — |
| 自动重试被取消的任务 | FC-20 第 4 条："取消后不自动重试，并把结果记成**unknown outcome**" | — |

### M.4 工具面（21 个，实测）= 编排面 15 个 + 文件面白名单 6 个

**现读**：`python -m agentflow.cli tools --role M` ⇒ `side_effect` read 13 / write_local 8 / none 0；`external` none 21；需审批 8 件。逐件明细（分组清单 + 拿不到什么）见附录 §M.4。

#### M.4.1 M 能召唤的 8 个角色 × 它们的动作（57 个可召唤动作）

> 这张表与 §0.7 是**同一份数据的第二个落点**（都从 `capabilities.CAPABILITIES` 读）。
> 两处都由 `tests/test_role_specs_action_table.py` 逐角色比对。
> **`M` 的出边今天只剩 `F` 不在里面**（2026-10-10 裁定要间接转达的那三个角色，
> 此后被业主逐个加回）：`B` 于 2026-10-13 加回（逐字「补 M 到 B」：采信链第一环要够得到），
> **`V` 于 2026-10-18 加回**（逐字「给 M 开 V 出边」：`projects/t3d` 三·1 的读数
> `reviewed_proof_rows = 0`，V 只能经 `F→V` ⇒ 证明级断言一行都没被逐行走查签过名）。
> 今天 `F` 走 `M→D→F`；V 有两条进路（`M→V` 是首选，`M→B→V` 仍可走）。
> 被拒时的理由码是 `forbidden_edge`（"这条边不存在"，不是故障）。

| 角色 | 可召唤动作数 | 动作名 |
|---|---:|---|
| A | 6 | `run_once` `run` `search_literature` `walk_citations` `ingest_local` `shelf_search` |
| B | 7 | `run_once` `reprocess_once` `run_reprocess` `decide_structural_duplicate` `resolve_structural_duplicate` `run` `register_statement` |
| C | 10 | `hottest` `paths` `cold` `gaps` `neighbors` `relations_between` `contradictions` `structural_duplicates` `handle` `proof_chain` |
| D | 15 | `probe_c` `ingest` `ingest_detailed` `trace_question` `trace_l3` `assess` `submit_gaps` `consider` `poll` `adjudicate` `research` `run_round` `write_report` `register_conjecture` `propose_question` |
| E | 5 | `run_experiment` `check_formal` `evidence_for` `list_experiments` `run_script_experiment` |
| G | 6 | `compose_claim` `register_dependency` `build_document` `render` `refresh_markdown` `revise` |
| H | 5 | `review` `verify_fixes` `list_findings` `judge_quote_semantics` `review_report` |
| V | 3 | `verify_proof` `list_verifications` `read_proof` |

> **`M.4.2`（召唤面的 9 道策略判定）与 `M.4.3`（写集相交 ⇒ 串行的并发判据）已移入附录**，
> 因为这两节的主体是**读数**（`REFUSAL_REASONS` 的取值表、波次划分的实测）：
> [`ROLE-SPECS-APPENDIX.md`](ROLE-SPECS-APPENDIX.md) §M.4.2 / §M.4.3。
> 规格侧的硬事实留在 §0.5（边）、§0.6（写集）、§M.6（Policy）与 §M.8（不变式）。

### M.5 状态机（`tasks` 表）（**只留主转移表**；其余约束表/反例表/第二三个状态机见附录 §M.5）

**(a) `status`**

`TASK_STATUSES = ("pending","running","done","cancelled","failed")`（`schema.TASK_STATUSES`）。

| 从 → 到 | 允许？ | 谁拦 | 出处 |
|---|---|---|---|
| `pending → running` | ✅（写 `started_at`） | — | — |
| `running → done` | ✅（**必须给 `outcome` 与 `detail`**） | `schema.Task.validate` | `schema.Task.validate` |
| `running → failed` | ✅（**必须写 `error`**，且 `outcome` 必须 `"failed"`） | 同上 | `schema.Task.validate` |
| `running → cancelled` | ✅（`outcome ∈ {cancelled, refused}`） | 同上 | `schema.outcome` |
| `done/cancelled/failed → 任何` | ❌ **终态先到先得** | `finish` 重读磁盘后**什么都不做**（幂等）；`schema` 的 "pending/running 却已有 `ended_at` ⇒ 拒" 从数据层再兜一次 | `conductor.Conductor.finish`；`schema.ended_at` |
| `running` 但无 `started_at` | ❌ | `schema.started_at` | — |
| `done` 但无 `outcome` | ❌ | `schema.outcome`（"'跑完了'与'跑完了有没有结果'是两件事"） | — |
| `done` 但 `detail` 为空 | ❌ | `schema.detail` | — |
| `outcome="refused"` 但 `status != "done"` | ❌ | `schema.status`（"**拒绝是一次成功执行**"） | — |
| `outcome="refused"` 但 `refusal_reason` 不在词表 | ❌ | `schema.refusal_reason` | — |
| `refusal_reason` 非空但 `outcome != "refused"` | ❌ | `schema.outcome` | — |
| `parent_task_id` 指向自身 | ❌ | `schema.parent_task_id` | — |
| `parent_task_id` 不存在 | ❌ | `verify.dangling_parent_task`（error） | `verify.verify_all` |
| 子 `depth ≠ 父 depth + 1` | ❌ | `verify.task_depth_discontinuous`（error）；`_depth_of` 也抛 | `verify.verify_all`；`conductor._depth_of` |
| `depth < 1` | ❌ | `schema.depth` | — |
| 无父但 `depth ≠ 1` | ❌ | `conductor.Conductor.verify_tasks` | — |
| `artifacts` 含空元素 | ❌ | `schema.artifacts` | — |
| `artifacts` 指向不存在的行 | ❌ | `verify.dangling_task_artifact`（error） | `verify.verify_all` |

### M.6 预算与终止条件（`policy.Policy` 的 dataclass 默认值，现读）

| 键 | 默认 | 维度 | 缺了会怎样（`policy.Policy` 逐字） |
|---|---:|---|---|
| `max_depth` | **12** | 深度 | "链可以**无限深**（每次只派生 1 个，但派生 10000 层）" |
| `max_fanout` | **25** | 单点**同时在飞**的派活数 | "每一层都能**无限宽**（深度 5，每层 9999 个）" |
| `max_concurrency` | **16** | 瞬时并发 | "扇出可以**无限持续**：每秒 4 个，跑一天" |
| `max_tasks_per_run` | **5000** | 生命周期总量 | "**瞬时**把并发打爆：总量对了，但 200 个任务同时开跑" |
| `wall_clock_sec` | **14400** | 墙钟（FC-20） | `None` = 不限 |
| ~~`token_budget`~~ | **该字段已不存在** | token（FC-19） | `Policy` 的 dataclass 只有上面五个 + `usd_budget`（复跑：`python -c "import dataclasses;from agentflow.policy import Policy;print([f.name for f in dataclasses.fields(Policy)])"`） |
| `usd_budget` | `None` | 花销 | `None` = 不限 |

**四类上限必须同时存在**（FC-18）：`Policy.validate()` 要求四个都是正数
（`policy.assert_policy_complete`），且 `run_plan` 启动时调 `assert_policy_complete(policy)`
（`conductor.Conductor.run_plan`；`policy.assert_policy_complete`）—— **缺任一类即 fail-closed**。

**上限用尽时的行为**：

| 用尽 | 行为 |
|---|---|
| `max_depth` | 新召唤 `refused/depth_exceeded` |
| `max_fanout` | 新召唤 `refused/fanout_exceeded`（上限按发起方角色取：默认档 = `max_fanout`，主控 `M` 一档 = 20；读的是**此刻在飞**的子代理数 —— 子代理返回即腾出名额） |
| `max_concurrency` | 新召唤 `refused/concurrency_exceeded` |
| `max_tasks_per_run` | 新召唤 `refused/...`（`total = _started_total + _cancelled_total`） |
| `wall_clock_sec` | 新召唤 `refused/deadline_exceeded`，**并 `_signal_stop("deadline", …)` 协作式取消在跑的** |
| `token_budget` / `usd_budget` | `refused/budget_exceeded` |
| `dispose()` | **合成 `cancelled` 的 end**（`detail` 写"结果未知"），**不自动重试** |

> ⚠️ **一个易被绕过的细节**（`conductor.Conductor.__init__` 逐字）：
> **被取消而没有落台账的召唤数必须计入总量** —— "否则'取消了就不限次'会成为绕过
> `max_tasks_per_run` 的路径（取消一次不算数 ⇒ 取消一百万次也不算数）"。
> 它与 `_started_total` **分开记**。

### M.7 三态与失败模式（“已知会犯的错”明细见附录 §M.7）

**`conductor.py` 的模块 docstring「三态纪律在本模块的落点」表 的三态表（逐字）**：

| 场景 | 禁止 | 本模块的做法 |
|---|---|---|
| 角色没有这个动作 | 只写一句人话 | `refusal_reason="unknown_action"` |
| 动作没接线 | 抛异常 / 返回空 | `refusal_reason="not_wired"`（`backend=subagent` 亦然） |
| handler 返回 `None` | 当成 `ok` | `outcome="no_result"` |
| 查询没法做 | `checked=True, empty=True` | 原样透传 `checked=False` + `reason` |
| 被 dispose 砍掉 | 记成 `failed` | `status=cancelled` + detail 写"结果未知" |

### M.8 不变式（I-1…I-10，都有实现或测试）

`DESIGN-CONDUCTOR.md:254-265` 的 10 条 + 实现位置：

- **I-1**：每个 `started_at` 有且仅有一个 `ended_at`
- **I-2**：终态不可改写
- **I-3**：深度单调不减
- **I-4**：拒绝必须带受控理由
- **I-5**：并发度不超上限
- **I-6**：写集相交不并发
- **I-7**：预算耗尽后不再新开任务
- **I-8**：取消是协作式且不自动重试
- **I-9**：台账可重建
- **I-10**：结果合并顺序确定

**另外**：`verify.py` 对 `tasks` 表的独立检查
（`dangling_parent_task` / `task_depth_discontinuous` / `task_without_input_key` /
`task_still_running` / `dangling_task_artifact` / `unknown_artifact_kind`）
与 `conductor.Conductor.verify_tasks`**判据一致但实现两份**
（`conductor.Conductor.verify_tasks` 逐字承认这一点并给出理由："`verify_all` 是**全库**审计、
由 CLI 跑；而'我刚跑完一次 run，台账是否自洽'是**即时**问题"）。
⇒ ⚠️ **这是"两套判据"的一个受控例外，但仍是 FC-11 的风险面**（两处会漂移）。

### M.9 接口

- **能被谁召唤**：**没人**（`NON_SUMMONABLE = {"M"}`，`capabilities.NON_SUMMONABLE`；
  `policy.check` 在 `d.to in NON_SUMMONABLE` 时返回 `forbidden_edge`，`policy.check`）。
- **M 能召唤谁**：`A B C D E G H V`（**8 个**；`capabilities.ALLOWED_EDGES` 的 `M` 那一行**只不含 `F`** ——
  F 仍走 `M→D→F`；V 于 2026-10-18 由业主加回，`M→V` 是走查证明的首选路径）。
- **入参从哪来**：
  - `plan: Sequence[TaskCall]`（`scheduler.TaskCall`，`scheduler.py:46`）—— **由调用方给**；
  - `Policy`（人 + 调用方配）；
  - `registry: Mapping[str, Any]`（`LocalBackend` 的接线；**必须显式给**，
    不给 ⇒ `not_wired`）；
  - `CancelToken`（共享 signal）。
- **产出被谁消费**：
  - `tasks` 行 → **`verify`**（6 类检查）、**人**（审计"谁召唤了谁、为了什么"）
  - `SummonResult` → 调用方（**永远不抛业务异常**）
  - `stats()` / `tree()` → 给用户的汇总
  - `usage_ledger` 行（`UsageEntry`）→ **M 的 `budget.spend()` 目前只写内存**
    （`MemoryBudgetTracker`，`scheduler.py:72-115`）。
    ⚠️ **`tasks.tokens`/`usd` 会落库**（`finish(..., tokens=, usd=)`），但
    **`usage_ledger` 表没有写入方** —— 这是 FC-19 未落地的一部分。

### M.10 自检入口

当次（2026-10-18）：**无 CLI 自检入口**（`conductor.py` 是模块，不是包）。入口是两个方法 `Conductor.verify_tasks()` / `Conductor.stats()` + 测试文件（`test_conductor_tools.py` / `test_scheduler.py` / `test_fc05_contract.py`）。明细见附录「A.10–M.10」。
