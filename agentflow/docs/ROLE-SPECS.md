# ROLE-SPECS —— 八个角色 + 主控的详细规格

> **本文件是"角色是什么"的判据。** 任何与它冲突的说法，以**代码**为准；
> 若代码与本文冲突，是**本文的 bug**，请提修改（见 `DEVELOPMENT.md` §10）。
>
> **取样口径（所有数字的来源）**：
> - 工具面：`build_registry(store=Store(tempfile.mkdtemp()), workspace_root=<同目录>, roles=schema.ROLES)`
>   一次装配后的**实测**结果（55 个工具、11 个模块 loaded、0 skipped）。
>   命令与输出见 `DEVELOPMENT.md` §9 附录与本文 §0.3。
> - 自注册工具：读 `agent_c.register_tools` / `agent_d._fallback_trace_tools` /
>   `tools/review_tools.register(include_writers=True)` 的源码逐个核出。
> - 状态机：读 `schema.py` 的 `validate()` 与各角色源码的 `LEGAL_TRANSITIONS` /
>   `TERMINAL_STATUSES`。
> - 预算：`interactions.DEFAULTS`（`interactions.py:100-107`）、
>   `tools/attack_tools.DEFAULT_BUDGET`（`attack_tools.py:63-68`）、
>   各 agent 的 `self.cfg.get(...)` 默认值、`policy.Policy`（`policy.py:38-60`）。
> - 不变式：`verify.py` 的 71 个 `Issue.code`（机械抽取，见 §0.4）。
>
> **凡未在代码中核实的一律标注** `（据 X，未在代码中核实）`。
> **凡本文件写"未落地"的，都是"我在代码里找不到实现"**，不是"我猜它没有"。

---

## 0. 公共约定（所有角色共用，逐节不再重复）

### 0.1 三态的四个位置

每个"查询/判定"类动作的返回都必须能回答三个问题，且**不许折叠**：

| 位置 | `checked` | `empty` / 值 | 含义 | 典型 `reason` |
|---|---|---|---|---|
| 没做 | `False` | 不给值 | **我们没查** | `not_wired` / `no_store` / `no_backend` / `caller_did_not_provide` |
| 做了，确实没有 | `True` | `empty=True`（或 `[]` + `empty`） | **查了，没有** | `no_hit` / `not_found` |
| 做了，有 | `True` | `empty=False` + 结果 | 查到了 | — |

判据（`schema.py:494-500` FC-01）：`reason` 必须来自受控枚举，
且枚举里必须至少有一个"未执行"值。

### 0.2 工具面的三条公共事实（实测）

| 事实 | 实测值 | 出处 |
|---|---|---|
| 工具总数（`build_registry`） | **55** | 本文 §0.3 |
| 全部 8 个角色**共有**的工具 | 9 个：`fs.list` `fs.read` `fs.search` `fs.stat` `table.count` `table.get` `table.list` `table.schema` `table.search` | 实测（交集） |
| 只读角色（C/H）工具面里的写工具 | **0**（`role_filter_notes = {}` ⇒ 结构性拦截一次都没触发） | 实测 |

> ⚠️ 上述 55 个**不含**各 agent 自注册的 **14** 个工具（它们不经
> `build_registry`，因此**不过 `build_registry` 的角色校验**）。14 个的清单见 §R0.2。

### 0.3 工具面 census 的复跑命令（本文所有工具数字的出处）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
python -m agentflow.cli tools
```

实测输出（2026 本轮）：

```
工具总数：55（已装模块 11：table_tools, fs_tools, search_tools, ocr_tools, graph_tools,
        trace_tools, research_tools, verify_tools, attack_tools, doc_tools, review_tools）

各角色工具数：{'A': 20, 'B': 18, 'C': 17, 'D': 37, 'E': 21, 'F': 32, 'G': 32, 'H': 23}
只读角色写工具泄漏：{'C': [], 'H': []}（空 = 正常）
```

`side_effect` 分布（实测）：`{'read': 32, 'write_local': 15, 'network': 2, 'none': 6}`；
需审批 **17 / 55**。

各角色的 `side_effect` 分布（实测）：

```
A: n=20 {'read': 11, 'write_local': 7, 'network': 2}
B: n=18 {'read': 12, 'write_local': 6}
C: n=17 {'read': 17}
D: n=37 {'read': 23, 'write_local': 9, 'none': 5}
E: n=21 {'read': 13, 'write_local': 7, 'none': 1}
F: n=32 {'read': 17, 'write_local': 9, 'none': 6}
G: n=32 {'read': 17, 'write_local': 9, 'none': 6}
H: n=23 {'read': 17, 'none': 6}
M: n=0
```

### 0.4 全库不变式检查项（`verify.py`，机械抽取 71 个 `Issue.code`）

**任何角色**的产出都会被下面这些检查覆盖（`verify_all`，`verify.py:94`）。
本节列出与角色直接相关的检查；完整 71 个清单见 `DEVELOPMENT.md` §9 附录。

| 检查码 | 级别 | 判什么 | 主要针对 |
|---|---|---|---|
| `schema_invalid` | error | 任一行的 `validate()` 失败 | 全体 |
| `duplicate_id` | error | 同表 ID 重复 | 全体 |
| `id_gap` | warning | 4 位 ID 出现空洞 | 全体 |
| `counter_behind` / `counter_overflow` | error | counters 落后（会撞号）/ 超出 4 位空间 | 全体 |
| `dangling_lit_ref` / `unknown_request_ref` | error / warning | 请求 ↔ 文献双向可追溯 | A |
| `done_without_result` | error | `outcome is None` 且无文献无错误 | A |
| `file_missing` / `ok_without_path` / `mismatch_without_evidence` | error / warning×2 | 文献文件与下载状态一致 | A |
| `unsorted_concepts` / `dangling_concept` / `stale_group_key` / `dangling_lit` / `lit_not_processed` / `bad_page_range` | error | 关系行自身的一致性 | B |
| `duplicate_quote` / `near_duplicate` | error / warning | 同概念组内引文重复 | B |
| `unsorted_related` / `self_related` / `dangling_related` / `related_drift` | error×3 / warning | 概念派生字段 | B |
| `dangling_concept_ref` / `dangling_relation_ref` / `dangling_lit_ref` / `dangling_request_ref` / `stale_waiting` | error×4 / warning | 研究问题的引用闭合 | D |
| `report_file_missing` | warning | C 报告的 markdown 不在了 | C |
| `dangling_question_ref` / `evidence_kind_overclaim` / `unhashed_experiment_code` / `refutation_without_counterexample` | error | 实验行的证据纪律 | E |
| `dangling_question_ref` / `dangling_plan_ref` / `dangling_experiment_ref` / `stalled_without_partial` | error | 攻坚计划 | F |
| `dangling_dep` / `dangling_dep_external` | error / warning | 依赖闭合（FC-23） | G |
| `proof_claim_rests_on_weaker_evidence` / `proof_claim_with_unclosed_dependency` / `closed_dep_on_inconclusive_experiment` | error | **过度声称**（FC-22） | G/H |
| `unsupported_claim` / `dangling_citation` / `citation_to_retracted_relation` / `citation_to_suspect_relation` / `overclaim` / `unknown_citation_kind` | error×5 / warning | 稿件的断言与引用 | G/H |
| `question_based_on_retracted_relation` | warning | 研究问题建立在被否关系上 | D |
| `dangling_doc_ref` / `finding_without_evidence` / `accepted_with_open_error` | error | 审校发现自身必须带证据 | H |
| `dangling_parent_task` / `task_depth_discontinuous` / `task_without_input_key` / `task_still_running` / `dangling_task_artifact` / `unknown_artifact_kind` | error×4 / warning×2 | 召唤台账（I-1/I-3/I-4） | M |
| `dangling_usage_task` / `usage_task_total_mismatch` | error / warning | 花销台账与任务一致 | M |
| `eval_duplicate_conflicting` | error | 同 `claim_key` 同口径的两条数字冲突 | E/G |
| `undeclared_array_field` | error | 数组字段未在 `ARRAY_FIELD_KINDS` 声明集合/序列（FC-05） | 全体 |
| `ledger_corrupt` / `ledger_bad_row` / `ledger_dangling_question` / `ledger_dangling_request` / `ledger_drift` | error×4 / warning | `research_request_ledger.json` 的受控偏离 | D |
| `deep_unavailable` / `reextract_failed` / `quote_state_changed` / `quote_not_found` / `empty_quote` / `no_text_layer` / `not_found_page_unknown` | warning / error | `--deep` 引文复核（FC-15 的归因分离） | B（写入方）/ H（复核方） |

### 0.5 召唤边（`capabilities.ALLOWED_EDGES`，`capabilities.py:593-603`）

| 召唤方 | 允许召唤 |
|---|---|
| `M`（主控） | `A B C D E F G H`（全部） |
| `A` | `B` |
| `B` | `C` |
| `C` | **（空）** —— 只读角色连"请求"都不直接发 |
| `D` | `A B C E F` |
| `E` | `B D` |
| `F` | `A B C D E` |
| `G` | `D E F` |
| `H` | `G` |

**没有任何角色能召唤 `M`**（`capabilities.NON_SUMMONABLE = {"M"}`，`capabilities.py:608`）。

### 0.6 写集（`capabilities.WRITE_SETS`，`capabilities.py:510-556`）

两张写集相交 ⇒ 两个任务**串行**（`policy.estimate_write_conflict` / `capabilities.write_sets_intersect`）。

| 角色 | 写集（表级） |
|---|---|
| `A` | `search_requests`, `literature` |
| `B` | `literature`, `concepts`, `relations`, `reprocess_requests` |
| `C` | `analysis_reports`（**只读角色的显式登记例外**） |
| `D` | `research_questions`, `search_requests`, `relations` |
| `E` | `experiments` |
| `F` | `attack_plans`, `search_requests`, `reprocess_requests` |
| `G` | `documents`, `dependencies`, `review_findings` |
| `H` | `review_findings`, `documents`（只读角色的显式登记例外） |
| `M` | （空 ⇒ 并发判据上按"整张表"处理，与任何人串行） |
| 编排器自有 | `CONDUCTOR_WRITE_SET = {tasks}` |

### 0.7 动作表（`capabilities.CAPABILITIES`，48 个动作）

| 角色 | 动作数 | 动作名 |
|---|---:|---|
| A | 2 | `run_once` `run` |
| B | 6 | `run_once` `reprocess_once` `run_reprocess` `decide_structural_duplicate` `resolve_structural_duplicate` `run` |
| C | 9 | `hottest` `paths` `cold` `gaps` `neighbors` `relations_between` `contradictions` `structural_duplicates` `handle` |
| D | 13 | `probe_c` `ingest` `ingest_detailed` `trace_question` `trace_l3` `assess` `submit_gaps` `consider` `poll` `adjudicate` `research` `run_round` `write_report` |
| E | 5 | `run_experiment` `check_formal` `evidence_for` `list_experiments` `run_script_experiment` |
| F | 4 | `create_plan` `step` `status` `list_plans` |
| G | 6 | `compose_claim` `register_dependency` `build_document` `render` `refresh_markdown` `revise` |
| H | 3 | `review` `verify_fixes` `list_findings` |
| M | **0** | `CAPABILITIES["M"] == ()`（可断言的事实） |

> 装配期由 `capabilities.assert_capabilities()`（**导入期执行**）逐条核：
> ① 键集合 == `schema.ROLES`（+`M`）；② 每个 `handler_name` 在
> `agent_<role>.Agent<Role>` 上**真的可调用**；③ 同角色动作不重复；
> ④ 只读角色的写集例外必须显式登记；⑤ `SIDE_EFFECTS` 与 `tools.base.SIDE_EFFECTS` 逐字一致。

---

## R0. 全局工具总表（55 个，逐条）

**列义**：`工具名 / summary / side_effect / 需审批 / roles / 参数（**粗体=required**） / 返回结构 / 测试 / 已知问题`。
`测试` 列指向 `tests/` 下**提到该工具名**的文件；`—` 表示本次未逐文件核对（**未核实**项已在 §0.8 汇总）。
"已知问题"列指向 `INVENTORY.md` 的条目（**注**：`INVENTORY.md` 是对 `test/test1/abflow`
的普查，见 §0.9 的口径警告）。

| # | 工具 | summary | `side_effect` | 审批 | roles | 参数 | 返回结构 | 测试 | 已知问题 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `attack.check_budget` | 检查攻坚预算是否完整、是否还允许再开一轮（四类键缺一不可） | `none` | 否 | F D G H | **budget**；depth, rounds_done | `{checked,complete,missing,allowed,reason}` | `test_agent_f.py` | INVENTORY 4.3(b)：`budget={"max_rounds":null}` 过校验 → `int(None)` `TypeError` |
| 2 | `attack.create_plan` | 为一个难题立项（预算四类键缺一不可，不完整就拒绝创建）；同 `problem_key` 已有未终结计划时不新建 | `write_local` | **是** | F | **problem**,**problem_key**；budget, depth, for_question_id, parent_plan_id, subgoals | `{created,plan_id,reason,plan?}` | `test_agent_f.py` | INVENTORY 4.3(b)：`PlanError`/`ValueError`/`StoreError` 逃逸成 `unexpected` |
| 3 | `attack.list_plans` | 列出全部攻坚计划（可按 `problem_key` 过滤） | `read` | 否 | F D G H | include_terminal, problem_key | `{checked,total,plans}` | `test_agent_f.py` | INVENTORY 4.5#13：handler 默认 `include_terminal=True`，显式传 `null` 被当 `False`（静默反转默认值） |
| 4 | `attack.pick_next_subgoal` | 按确定性次序选出下一个要推进的子目标（开始过的优先，卡住的最后） | `none` | 否 | F D G H | **subgoals** | `{picked,subgoal,reason}` | `test_agent_f.py` | INVENTORY 4.3(b)：`subgoals=null` 过校验 → `TypeError` |
| 5 | `attack.status` | 读一个攻坚计划的完整可读视图（子目标状态计数、预算余量、history 尾部） | `read` | 否 | F D G H | **plan_id** | `{checked,plan_id,status,rounds,subgoal_counts,history_tail,…}` | `test_agent_f.py` | INVENTORY 4.3(c)：计划不存在时 `ok=True` + `checked=False`（**必须看 `checked` 而不是 `ok`**） |
| 6 | `attack.step` | 推进攻坚计划一轮：按 owner 分派（E 做实验/A 提检索/B 提重抽取）；C/D/F 的推理未接线则如实记 `no_change` | `write_local` | **是** | F | **plan_id** | `{plan_id,round,sid,action,outcome,status,budget_left,reason}` | `test_agent_f.py` | INVENTORY 4.4：经 `_deploy_e` 跑 E 的脚本子进程（**声明里没有"执行进程"这一档**） |
| 7 | `doc.build_document` | 写一行 documents 并渲染 markdown 到工作区内（逐条机械检查后再落库；`out_path` 越界即拒绝） | `write_local` | **是** | G | **kind**,**title**,**claims**；open_problems, out_path, sections | 落库后的 documents 行（含 `doc_id`/`markdown_path`） | `test_agent_g.py` | INVENTORY 4.3(a)②：`citations:["lit:9999"]` 可通过全部闸门并落库（**引用存在性不核**）；4.3(b) `StoreError` 逃逸 |
| 8 | `doc.compose_claim` | 构造一条合规断言：`cross_check` 自动补"不构成证明"；无引用/否定未分类/过度声称在构造时就抛错 | `none` | 否 | G H F D | **text**,**citations**,**evidence_kind**,**section**；claim_id, is_negative, negation_kind | 合规的 claim dict（含 `claim_id`/`disclaimer`） | `test_agent_g.py` | INVENTORY 总表：三态位 **无**（据 INVENTORY，未在代码中核实） |
| 9 | `doc.list_documents` | 只读列举稿件（代号/类型/标题/状态/审校轮次/断言数与 markdown 路径） | `read` | 否 | G H F D | kind, status | `{count,documents:[{doc_id,kind,title,status,review_rounds,claim_count,markdown_path}]}` | `test_agent_g.py` | INVENTORY 4.3(b)：`StoreError` 逃逸 |
| 10 | `doc.register_dependency` | 登记外部依赖（FC-23）：`status="closed"` 会先用真实数据核 `lit_id`/`experiment_id`；`dangling`/`external_unavailable` 必须写 `status_reason` | `write_local` | **是** | G | **used_by**,**kind**,**label**；page_range, quote, source_experiment_id, source_lit_id, status, status_reason | 落库后的 dependencies 行（含 `dep_id`/`status`） | `test_agent_g.py` | — |
| 11 | `doc.scan_claim` | 对一条断言做机械检查：有无引用、证据等级是否被夸大、否定是否分类 | `none` | 否 | G H F D | **claim** | `{checked,claim_id,ok,findings,error_count,warning_count}` | `test_agent_g.py` | INVENTORY 4.5#10：与 `review.scan_document` 重复检查**且已漂移** |
| 12 | `fs.delete` | 删除文件；删目录必须显式 `recursive=true`（且不允许删工作区根） | `write_local` | **是** | A B D E F G | **path**；recursive | `data`=是否真的删掉；`meta.found` 区分本来就没有 | `test_tools_table_fs.py` | — |
| 13 | `fs.list` | 列出工作区内某目录（或单个文件）的条目；`recursive=true` 时递归 | `read` | 否 | A B C D E F G H | limit, path, recursive | `{entries:[{name,path,is_dir,is_file,is_symlink,size,mtime}],total,returned,truncated}` | **零提及** | INVENTORY 4.1：`limit`/`truncated` 分页逻辑无断言 |
| 14 | `fs.move` | 移动或重命名（目标已存在时拒绝，不静默覆盖） | `write_local` | **是** | A B D E F G | **src**,**dst** | `{src,dst}` | `test_tools_table_fs.py` | — |
| 15 | `fs.read` | 读文本文件；二进制与超限会如实说明（二进制直接拒绝，超限返回截断内容并标注） | `read` | 否 | A B C D E F G H | **path**；max_bytes | `data`=文本；`meta` 给 `encoding`/`bytes_read`/`total_bytes`/`truncated`/`had_errors` | `test_tools_table_fs.py` | — |
| 16 | `fs.search` | 在工作区文本文件里按 ripgrep 风格正则搜内容，返回「文件:行号: 行内容」 | `read` | 否 | A B C D E F G H | **pattern**；include, limit, path | `{matches:[{path,line,text}],lines,total,truncated,scanned,skipped}` | `test_tools_table_fs.py` | — |
| 17 | `fs.stat` | 查看路径的大小/类型/修改时间；文件另给 sha256 | `read` | 否 | A B C D E F G H | **path** | `{path,exists,is_dir,is_file,is_symlink,size,mtime,sha256,link_target}` | `test_tools_table_fs.py` | — |
| 18 | `fs.write` | 写文本文件（原子落盘；默认不覆盖已有文件） | `write_local` | **是** | A B D E F G | **path**,**content**；overwrite | `{path,bytes,sha256,created}` | `test_tools_table_fs.py` | — |
| 19 | `graph.build` | 从 store 的三张表构建概念图索引，返回图规模摘要 | `read` | 否 | C D | （无） | `{concept_count,relation_count,pair_count,isolated_concepts,degree_top,…}` | `test_tools_graph_trace.py` | INVENTORY 总表：三态位 **无** |
| 20 | `graph.neighbors` | 返回某概念的邻居概念代号（升序）及其连接的度数信息；**邻居数有上限**，截断时如实报出 | `read` | 否 | C D | **concept_id**；max_neighbors | `{'concept_id','name','degree','total_neighbors','returned_neighbors','truncated','reasons','neighbors':[{'concept_id','name','relation_count','relation_ids'}]}` | `test_tools_graph_trace.py` / `test_tools_attack_graph_fixes.py` | ✅ **已修**（本轮）：原先 `neighbors` 是**不可截断的裸列表**，上下文预算的剪枝在它上面不生效（实测 300 邻居 = 27046 字符、`prune_tool_result` 后一条没少）。现在有界层在**工具层**（`max_neighbors` 默认 200），`RelationGraph.neighbors` **保持裸 list**（4 个调用点按 list 语义用它） |
| 21 | `graph.relations_between` | 返回同时包含两个概念的全部关系（按 `quote_verified`/`status`/信息量确定性排序） | `read` | 否 | C D | **a**,**b** | `{a,b,count,relations:[{relation_id,description,status,quote_verified,lit_id,page_range}]}` | `test_tools_graph_trace.py` | — |
| 22 | `graph.stats` | 返回当前图的统计摘要与热度前列（不重建索引；未建图时按需构建一次） | `read` | 否 | C D | top_n | `{…summary…,hot:[…]}` | `test_tools_graph_trace.py` | INVENTORY 6.4：`summary().degree_top` 取前 5 而 `hot` 用 `top_n`（**未判断是否有意**） |
| 23 | `ocr.backends` | **真实探测** OCR 后端（easyocr / pytesseract / none）是否可用；探测阶段**不会**下载 easyocr 模型 | `write_local` | **是** | B | refresh | `backends[]` + `any_ocr_backend_available`/`selected_for_auto`/`verdict` | `test_tools_search_ocr.py` | ✅ **已修**：原先声明 `read`（= 不需审批）却在**工作区外 mkdir**（`~/.EasyOCR/model`）并起进程 ⇒ 改为 `write_local`（如实声明） |
| 24 | `ocr.detect_text_layer` | 判断 PDF 有没有文本层；无文本层时说明这是「无法校验」而不是「校验失败」 | `read` | 否 | B | **path** | `has_text_layer`/`pages`/`page_count`/`pages_with_text`/`chars`/`source_kind`/`reason`/`suggested_next` | `test_tools_search_ocr.py` | INVENTORY 4.3(b)：`page_count(p)` 在 `try` 之外，异常逃逸 |
| 25 | `ocr.run` | 对指定页（缺省全部页）做 OCR；`auto` 按 easyocr→pytesseract 选第一个可用者，都不可用时 **fail** 并给安装建议（绝不返回空文本假装成功） | `network` | **是** | B | **path**；backend, dpi, languages, max_pages, pages | `pages[]` + `backend`/`elapsed_s`/`warnings`/`truncated_pages`/`total_chars` | `test_tools_search_ocr.py` | ✅ **已修**：原先声明 `read`，实际 easyocr 首次用**下载 ~100MB 模型** ⇒ 改为 `network` |
| 26 | `research.list_gaps` | 列出研究问题台账（D 的工作台）。按 `priority`（high>medium>low）、`question_id` 稳定排序 | `read` | 否 | D | limit, status | `{questions:[…],count}`；每题带 `waiting_request_ids` | `test_agent_d.py` | — |
| 27 | `research.poll_waiting` | 复查等待中的查询请求：每条请求是否结束？其 `result_lit_ids` 是否都已被 B 消化？ | `read` | 否 | D | （无） | `{ready,waiting,counts}` | `test_agent_d.py` | — |
| 28 | `research.set_status` | 改研究问题的状态（按 schema 状态机校验，非法迁移与非法状态一律 fail） | `write_local` | **是** | D | **question_id**,**status**；notes | `{question_id,from,to,waiting_request_ids}` | `test_agent_d.py` | — |
| 29 | `research.submit_gap` | 把某研究问题的知识缺口提交给 A（在 `search_requests` 建一行，并把 `request_id` 追加进该问题的等待集） | `write_local` | **是** | D | **question_id**,**topic**,**mode**；description | `{request_id,question_id,duplicated,waiting_request_ids}` | `test_agent_d.py` | INVENTORY 4.7①：与 `table_tools._next_request_id` 的 `r-NNNN` 策略不同（**max+1 且无上限保护**） |
| 30 | `research.write_note` | 向某研究问题追加一条研究笔记（追加而非覆盖，保留研究过程） | `write_local` | **是** | D | **question_id**,**note** | `{question_id,notes_length,appended}` | `test_agent_d.py` | — |
| 31 | `review.list_findings` | 只读列举审校发现（可按稿件/状态/级别过滤），含每条发现的 `evidence` | `read` | 否 | H G F D | doc_id, level, status | `{count,findings:[{finding_id,doc_id,kind,level,target,message,evidence,status}]}` | `test_agent_h.py` | INVENTORY 4.3(b)：`StoreError` 逃逸 |
| 32 | `review.scan_document` | 对一份稿件做全量机械审校（引用/证据等级/否定分类/依赖闭合），每条发现都带 `evidence` | `none` | 否 | H G F D | **doc**；dependencies | `{checked,doc_id,findings,error_count,warning_count,verdict,dep_check}` | `test_agent_h.py` | INVENTORY 4.3(a)①：**依赖闭合没查却给出 `verdict="accepted"`**（`dep_check.checked=False` 与 `verdict` 矛盾）；4.5#10 与 `doc.scan_claim` 重复且漂移 |
| 33 | `search.dedup_check` | **不联网**：按三级硬键说明"这条会不会被判成已有的某篇"，并给出会命中的键 | `read` | 否 | A | **title**；doi, year | `would_be_duplicate`/`matched_key`/`keys`/`existing`/`near_misses` | `test_agent_a*.py` | INVENTORY 4.3(a)③：`_literature_rows` 的 `except Exception: return []` 静默报"不是重复"（**与 `store is None` 的严格 fail-closed 相反**） |
| 34 | `search.download` | 把候选的 `pdf_url` 下到工作区 `downloads/`（不覆盖同名文件） | `network` | **是** | A | **url**；hint, max_bytes | `ok`/`bytes`/`sha256`/`path`/`rel_path`/`filename`/`http_status`/`content_warning`/`warnings` | **零提及** | INVENTORY 4.1：唯一 `network` 工具之一，离线套件零断言 |
| 35 | `search.literature` | 按 topic/mode 检索文献候选；每条候选都带 `dedup_key` 与 `is_new`。`mode=precise` 时必须给 `description` | `network` | **是** | A | **topic**；description, limit, mode, provider | `candidates[]` + 计数与 `diagnostics` | `test_tools_search_ocr.py` | INVENTORY 4.2：`providers.py` 8 个联网用例默认 deselect |
| 36 | `search.providers` | 列出可用检索源，并**真实探测**各自是否可用（`ABFLOW_SKIP_NETWORK=1` 时标为未探测而不是猜） | `network` | **是** | A | （无） | `providers[]` + `available`/`unavailable`/`unverified` 三个名单 | `test_tools_search_ocr.py` | ✅ **已修**：原先声明 `read`（= **不需要审批**）却**发真实 HTTP 请求** ⇒ 改为 `network`。⚠️ **这是本轮审批面上唯一的实质变化**：三个工具从"不需审批"变成"需要审批" |
| 37 | `search.register` | 登记一条文献（`processed=false`）：先判重，命中则复用既有 `lit_id`；未命中则 `alloc_id('lit')` 并把文件收编进 `library/<lit_id>/` | `write_local` | **是** | A | **title**,**type_code**,**summary**；doi, path, request_id, year | `created`/`lit_id`/`path`/`dedup_key`/`download` | **零提及** | INVENTORY 4.1：**副作用最大、覆盖最少**；4.3(b) `row.validate()` 未包 guard，`ValueError` 逃逸 |
| 38 | `table.count` | 统计行数（可用 `filter` 做等值过滤） | `read` | 否 | A B C D E F G H | **table**；filter | `data`=整数行数 | **零提及** | INVENTORY 4.1：docstring 承诺「计数不该受 `limit` 影响」，**这个不变量没被测** |
| 39 | `table.create` | 新建一行：自动分配主键（`search_requests` 用 `r-NNNN`），校验通过才落盘，返回新 ID | `write_local` | **是** | A B D E F G | **table**,**row** | `data`=新主键**字符串**；`meta.row` 是实际落盘的整行 | `test_tools_table_fs.py` | INVENTORY 4.7①：`_next_request_id` 取**最小可用号**（与 `research_tools` 的 max+1 冲突） |
| 40 | `table.delete` | 删除一行；被引用的 `concepts`/`literature` 会被拒绝并列出引用者 | `write_local` | **是** | A B D E F G | **table**,**id** | `data`=是否真的删掉；`meta.references` 列出引用者 | `test_tools_table_fs.py` | — |
| 41 | `table.get` | 按主键取一行；不存在时返回 `ok=True` 且 `data=None`（用 `meta.found=False` 说明） | `read` | 否 | A B C D E F G H | **table**,**id** | `data`=行对象或 `None`；`meta.found` | `test_tools_table_fs.py` | — |
| 42 | `table.list` | 列出某张表的行（支持等值过滤与分页），并给出过滤后的总数 | `read` | 否 | A B C D E F G H | **table**；filter, limit, offset | `{rows,total,returned,limit,offset,table}` | **零提及** | INVENTORY 4.1：`total` 是**过滤后**总数，是分页正确性的唯一依据，**没有一条断言** |
| 43 | `table.schema` | 返回表的字段名/类型/是否必填/默认值，以及全部受控词表 | `read` | 否 | A B C D E F G H | （无） | `{tables:{表名:{fields,primary_key,vocabularies}},vocabularies}` | **零提及** | INVENTORY 4.1：反射出全部受控词表，**是 LLM 写参数的唯一依据**；4.5#9 `L3_STATUSES` 声称受控词表但无成员校验 |
| 44 | `table.search` | 在指定（默认全部标量字符串）字段里做大小写不敏感的子串匹配 | `read` | 否 | A B C D E F G H | **table**,**query**；fields, limit | `{rows,total,matched_fields:{主键:[命中的字段]}}` | **零提及** | INVENTORY 4.1：`casefold()` 承诺与 `truncated` 语义无断言 |
| 45 | `table.update` | 部分更新一行：只覆盖 `patch` 里给出的字段，其余字段（含诊断字段）原样保留；不允许改主键 | `write_local` | **是** | A B D E F G | **table**,**id**,**patch** | `data`=主键；`meta.row` 是合并后实际落盘的整行 | `test_tools_table_fs.py` | — |
| 46 | `trace.chain` | 把一条关系代号链的每一步表述串起来（D 写报告可直接引用），缺号如实列出 | `read` | 否 | C D | **relation_ids** | `{level:'chain',relation_ids,steps,chain_text,missing}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)④：无 store/无 graph 时**静默返回 `ok` + `step_count=0`**（唯一一个"成功"的静默空结果）；4.5#4 `returns=` 与 6 条错误分支不符 |
| 47 | `trace.concept` | L2 溯源：由概念代号取回定义 + 它参与的全部关系的表述（不下钻文献正文） | `read` | 否 | C D | **concept_id**；with_relations | `{level:'L2',concept,relation_count,relations,contains_fulltext:false}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑤：空图回退把「没查」报成「查了、没有」 |
| 48 | `trace.literature` | L3 溯源（按需、贵）：文献元数据 + 本地文件是否存在 + 正文片段；无文本层会如实报告而不是返回空串 | `read` | 否 | C D | **lit_id**；max_chars, pages | `{level:'L3',status,file_exists,has_text_layer,pages_returned,text,truncated}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑥：`store=None` 时**诚实的 fail 被前置检查遮蔽**；4.5#4 六条错误分支缺 `pages_returned`/`truncated` |
| 49 | `trace.relation` | L1 溯源：由关系代号取回引文/描述/陈述/页码/状态/引文校验三态，并翻译概念名、附文献元数据 | `read` | 否 | C D | **relation_id** | `{level:'L1',relation_id,quote,description,statement,page_range,status,quote_verified,concepts,literature}` | `test_tools_graph_trace.py` | INVENTORY 4.5#7：`returns=` 少列 2 个实际键，且多一个写死的 `contains_fulltext: False`（**看起来像检查结论**） |
| 50 | `verify.check_formal` | 把命题（Lean 源码/脚本）交给检查器真跑一次；只有 `verified` 给 proof 级证据，`compile_error`/`uses_sorry`/`extra_axioms`/`decl_mismatch` 是"查了没通过"，`timeout`/`no_backend`/`tool_crashed` 是"没查成" | `read` | 否 | E F G H | **claim**；script_path, source, name, imports, timeout_sec | `{'checked','verified','claim','reason','detail','verifier_output'}`（`reason` 取 `formalgw.STATUSES` 八值词表） | `test_tools_audit_fixes.py` | **P1 本轮接线**：工具层此前给 `script_path` 时返回 `checked=False` + `reason="not_implemented"`（全文零处提到 `formalgw`），现已转发到 `src/agentflow/formalgw.py` 的 `check_lean`。三态映射：`checked` 取自 `formalgw.evidence_of` 的结论位（`verified`/`compile_error`/`uses_sorry`/`extra_axioms`/`decl_mismatch` ⇒ True；`timeout`/`no_backend`/`tool_crashed` ⇒ False）；`verified` 只在 `status == "verified"` 时为 True，`checked=False` 时保持 `None`（未查成绝不写成 False）。`side_effect` 由 `none` 改为 `read`（它会起检查器子进程并写临时 `.lean`，与 `detect_verifier` 同一口径；`read` 与 `none` 都不需审批，审批面未变）。真实正控在这台机器的 Lean 4.7.0 上跑到 `verified` + `evidence_kind="proof"`，三条负控（含 sorry / 无后端 / 声明名对不上）各自如实失败（证据脚本 `temp/w5_p1_probe.py`）。已知缺口（本轮未改）：`script_path` 不经 `_resolve`，越出工作区的路径不会被工具层拦下 —— 记录在此待人工处置 |
| 51 | `verify.code_hash` | 计算工作区内一个脚本文件的 sha256（前 16 位），用于实验记录的可复现性绑定 | `read` | 否 | E F G H | **path** | `{path,code_hash}` | `test_agent_e.py` | INVENTORY 4.3(b)：`open()` 的 `OSError`/`PermissionError` 逃逸 |
| 52 | `verify.detect_verifier` | 探测环境里可用的证明检查器（Lean/Coq/Isabelle）。返回的是事实，不是猜测 | `read` | 否 | E F G H | （无） | `{'checked','available','available_names','reason','probe_errors'}` | `test_agent_e.py` | ✅ **已修**：原先声明 `none` 却 `shutil.which` + `subprocess.run` ⇒ 改为 `read`；`checked` 不再硬编码 `True`（探测失败 ⇒ `False` + `probe_errors`）；`returns=` 补齐（**注意** `read` 与 `none` **都不需审批**，所以这次修正不影响审批面，只影响"审计口径"） |
| 53 | `verify.evidence_for` | 查一条命题（`claim_key`）或一个研究问题（`for_question_id`）已有的实验证据。两个参数都不给 ⇒ `checked=False` | `read` | 否 | E F G H | claim_key, for_question_id | `{checked,experiments,best_evidence_kind,proved,reason}` | `test_agent_e.py` | INVENTORY 4.3(b)：`StoreError` 逃逸；4.7⑪ 排序键与 `list_experiments` 逐字重复 |
| 54 | `verify.list_experiments` | 按登记顺序列出实验记录（只读）：没有它就无法回答"这件事到底做过没有" | `read` | 否 | E F G H | claim_key, limit | `{checked,total,returned,truncated,experiments}` | `test_agent_e.py` | 同上 4.7⑪ |
| 55 | `verify.run_experiment` | 在独立进程里跑一个工作区内的脚本并登记一条 Experiment 行。脚本自报 `evidence_kind='proof'` 会被**降级**为 `cross_check`；崩溃一律记 `inconclusive` | `write_local` | **是** | E F G | **claim**,**claim_key**,**script_path**；for_question_id, method, params, timeout | `{experiment_id,recorded,result,evidence_kind,negation_kind,exit_code,reason}` | `test_agent_e.py` | INVENTORY 4.4：跑工作区脚本子进程，**子进程继承完整环境（可联网）**；4.3(b) `ExperimentError`/`ValueError` 全部逃逸；4.5#8 `returns=` 漏 FC-10 的 `count`/`result_counts`/`negation_counts` |

### R0.1 55 个工具的公共事实（机械可验证）

- `params_validated_by_layer = true`：`ToolRegistry.call` 在调 handler 之前**一定**跑
  `validate_params(spec.params, params)`（`tools/base.py:372`），参数非法返回
  `fail(kind="param_error")`，**不会进 handler**。
- `roles_consistent_with_side_effect = true`：**没有任何写工具声明了 C 或 H**。
  两道防线：`fs_tools`/`table_tools` 的 `_effective_roles` 在**注册期**剥掉
  `READ_ONLY_ROLES`；`ToolRegistry.for_role`（`tools/base.py:310-345`）还有第二道结构性拦截。
- `handler_accepts_kwargs_only = true`（55/55）：`spec.handler(**params)` 不会因位置参数报错。
- 27 个 handler 是 `lambda`，8 个是具名闭包，20 个是 `functools.partial`。
  **lambda 无法携带 docstring** ⇒ 这 27 个工具的**唯一**文档是 `ToolSpec.summary`。

### R0.2 不经 `build_registry` 的 14 个工具（**必须单列**）

> ⚠️ **这 14 个不过 `build_registry`，因此不过它的角色校验**
> （`tools/__init__.py:195-207` 的 `bad_roles` 断言）。这是**结构性缺口**，
> 不是文档问题。

| 来源 | 位置 | 数量 | 工具 | `side_effect` | `roles` | 是否过角色校验 |
|---|---|---:|---|---|---|---|
| `AgentC.register_tools` | `agent_c.py:2538-2737` | 9 | `graph.hottest` `graph.paths` `graph.cold` `graph.gaps` `graph.svc_neighbors` `graph.svc_relations_between` `graph.contradictions` `graph.structural_duplicates` `graph.check_conflict` | 全 `read` | `("C","D")`（`agent_c.py:2567`） | **否** |
| `tools/review_tools.register(include_writers=True)` | `review_tools.py`（写侧） | 2 | `review.review_document` `review.verify_fixes` | `write_local` | 待核（未在本次核到显式字符串） | 走 `build_registry` 的模块注册路径，但**默认不注册**（需 `include_writers=True`） |
| `agent_d._fallback_trace_tools` | `agent_d.py:466-574` | 3 | `trace.relation` `trace.concept` `trace.literature`（**降级替身**） | 全 `read` | `("agent-C","agent-D")`（`agent_d.py:483/509/546`） | **否**（`install_d_tools` 直接 `ToolRegistry(...)`，`agent_d.py:604`） |

**已知缺陷（`INVENTORY.md` §6.3，逐字）**：那 3 个替身的 `roles=("agent-C","agent-D")`
**带 `agent-` 前缀**，不是 `ROLES` 里的 `"C"`/`"D"`；`install_d_tools` 又
**直接构造 `ToolRegistry` 并 `register_function`，从来不经过那段校验**
⇒ `for_role("C")`/`for_role("D")` 永远拿不到这 3 个替身工具。
**本次在 `agentflow` 里复核：仍然如此**（`agent_d.py:483/509/546` 三处逐字命中）。
这正是 `build_registry` 在 `tools/__init__.py:195-207` 专门加断言要拦的那类错误。

`AgentH.install_h_tools`（`agent_h.py:94-111`）**不是新工具**：它把 `build_registry`
的 H 子集复制进新注册表，并用 `filter_readonly_h_surface` 再做一次显式拒绝 + 留痕
（`refused_write_tools`）—— 是"声明错了也要拦下"的第二道防线。

### R0.3 `INVENTORY.md` / `tools.json` 的口径警告（**重要**）

`D:\Incubator\temp\inventory\INVENTORY.md:3` 逐字写明它普查的是
**`D:\Incubator\test\test1\`（包名 `abflow`）**，不是本目录 `agentflow`。

本次核对结论：

| 项 | `INVENTORY.md`（abflow） | 本文实测（agentflow） | 是否一致 |
|---|---|---|---|
| 工具总数 | 55 | 55 | ✅ |
| 各角色工具数 | `A20 B18 C17 D37 E21 F32 G32 H23`（§1.2） | 同 | ✅ |
| `side_effect` 分布 | `read 32 / write_local 15 / none 6 / network 2` | 同 | ✅ |
| 需审批 | 17 / 55 | 同 | ✅ |
| 只读角色泄漏 | 0 | 0 | ✅ |
| 零测试工具 | 7 个（`table.list` `table.count` `table.schema` `table.search` `fs.list` `search.register` `search.download`） | 用"工具名字符串是否出现在 tests/"口径，**本次未复算**（**未核实**） | ⚠️ |
| `INVENTORY` 未覆盖的 schema 对象 | 无 `Task`/`UsageEntry`/`EvalResult` | **有**（`schema.py:1260/1387/1465`） | ❌ **INVENTORY 落后** |

**因此**：本文"已知问题"列的 `INVENTORY.md` 引用是**同一代码谱系的不同版本**
（`agentflow` 是 `abflow` 的后继），**同一处代码在两份目录里的行号未必相同**。
凡本文写"INVENTORY 4.x"的，请在 `test/test1/` 下按该条目的**文本**检索，不要按行号。

---

## A —— 文献检索

### A.1 一句话定位

**A 是唯一带网络副作用的角色**：它把 `search_requests` 里的一条待办变成"本地有全文的文献行"。
它回答的问题是：**"这条需求，外面有没有对应的文献，我拿得到吗？"**

### A.2 职责

| # | 职责 | 判据（可判定） |
|---|---|---|
| A-1 | 领取一条待办检索请求（租约内，幂等） | `AgentA.run_once`（`agent_a.py:306`）；`search_requests` 的 `claimed_by`/`lease_until` |
| A-2 | 按 `mode` 检索候选 | `search.literature`（`side_effect=network`）；`mode ∈ SEARCH_MODES`（`schema.py:23`） |
| A-3 | 判重后登记文献行（命中则复用既有 `lit_id`） | `search.register`；`dedup.literature_keys` 三级硬键 |
| A-4 | 下载全文到 `library/<lit_id>/`，记 `sha256` 与 `download.status` | `search.download`；`DOWNLOAD_STATUSES`（`schema.py:89`） |
| A-5 | 把请求标 `done` 并写 `result_lit_ids` / `outcome` | `SEARCH_OUTCOMES`（`schema.py:76`） |
| A-6 | 自己**不抽概念**；检索完请 `B` | `A → B`（`capabilities.py:595`） |

### A.3 明确不负责

| 不做什么 | 为什么不由 A 做 | 该由谁做 |
|---|---|---|
| 抽取概念与关系 | 抽取是**知识生产**，A 的产出是**来源**；混在一起会让"来源对不对"与"抽得对不对"无法分别归因 | **B** |
| 写 `concepts` / `relations` | A 的写集是 `{search_requests, literature}`（`capabilities.py:512`），**不含**知识表 | **B** |
| 判断一篇文献"有没有用" | 相关性判断需要图上的结构信息（度数、路径），A 拿到的是候选元数据 | **C**（分析）/ **D**（决策） |
| 逐字引文回验 | 回验需要**文献正文 + 关系断言**，断言由 B 产出 | **B**（`quoteverify`） |
| 决定研究问题该不该问 | A 只消费 `search_requests`；"该不该问"是研究判断 | **D**（`research.submit_gap` / `AgentD.submit_gaps`） |
| 发起第二次检索（"我再多找几篇"） | A 的动作只有 `run_once` / `run`（`capabilities.py:153-167`），**没有"自己决定再搜"这个动作** | **D**（`D → A`）/ **F**（`F → A`） |

### A.4 工具面（20 个，实测）

`side_effect` 分布：`{'read': 11, 'write_local': 7, 'network': 2}`

| 工具名 | summary | `side_effect` | 审批 | 参数（**粗体=required**） | 返回结构 | 测试 | 已知问题 |
|---|---|---|---|---|---|---|---|
| `search.dedup_check` | 不联网说明"这条会不会被判成已有的某篇" | `read` | 否 | **title**；doi, year | `would_be_duplicate`/`matched_key`/`keys`/`existing`/`near_misses` | `test_agent_a*.py` | INVENTORY 4.3(a)③：表坏了静默报"不是重复" |
| `search.download` | 下载到 `downloads/`（不覆盖同名） | `network` | **是** | **url**；hint, max_bytes | `ok`/`bytes`/`sha256`/`path`/`content_warning`/`warnings` | **零提及** | INVENTORY 4.1 |
| `search.literature` | 按 topic/mode 检索候选（带 `dedup_key`/`is_new`） | `network` | **是** | **topic**；description, limit, mode, provider | `candidates[]` + `diagnostics` | `test_tools_search_ocr.py` | 联网用例默认 deselect |
| `search.providers` | 列出检索源并**真实探测**可用性 | `read` | 否 | （无） | `providers[]` + 三个名单 | `test_tools_search_ocr.py` | INVENTORY 4.4：声明 `read` 却发真实 HTTP |
| `search.register` | 登记文献行（先判重，命中复用 `lit_id`；否则收编文件进 `library/<lit_id>/`） | `write_local` | **是** | **title**,**type_code**,**summary**；doi, path, request_id, year | `created`/`lit_id`/`path`/`dedup_key`/`download` | **零提及** | INVENTORY 4.1：副作用最大、覆盖最少 |
| `fs.list` `fs.read` `fs.search` `fs.stat` | 工作区只读（公共 9 个之一） | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | — |
| `fs.write` `fs.move` `fs.delete` | 工作区写（A 用它落下载/整理文件） | `write_local` | **是** | 见 §R0 | 见 §R0 | 见 §R0 | — |
| `table.count` `table.get` `table.list` `table.schema` `table.search` | 表只读（公共 9 个之一） | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | `table.list`/`table.count` 等**零提及** |
| `table.create` `table.update` `table.delete` | 表写 | `write_local` | **是** | 见 §R0 | 见 §R0 | 见 §R0 | INVENTORY 4.7①：`r-NNNN` 分配器有三份实现 |

> **A 拿不到**：`research.*`（那是 D 的决策）、`ocr.*`（那是 B 的解析）、
> `graph.*`/`trace.*`（C/D）、`verify.*`（E/F/G/H）、`doc.*`/`review.*`、`attack.*`。
> 实测：A 的 20 个工具里**没有**任何一个属于上述组。

### A.5 状态机

A 产出的行有**两个**状态机。

**(a) `search_requests`（A 的输入队列）**

| 字段 | 取值 | 说明 |
|---|---|---|
| `done` | `False → True` | 唯一的状态位 |
| `claimed_by` / `lease_until` | 字符串 / ISO 时间 | 逻辑租约，防"重复干活" |
| `attempts` | 整数，上限 `lease.max_attempts=3`（`config.yaml:14`） | 超过则显式放弃并写 `last_error` |
| `outcome` | `SEARCH_OUTCOMES = ("ok","no_results","search_failed","gave_up")`（`schema.py:76`） | 与 `done` **正交**：`done=True` 时 `outcome` 必须说清是哪一种 |

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `done=False → True` | ✅ | — |
| `True → False` | ❌ **不许** | `verify.done_without_result`（`verify.py:215`）与 schema 的追溯字段共同保证；A-7 的先写实体后置标志纪律（`DESIGN.md`） |
| `done=True` 且 `outcome is None` 且无 `result_lit_ids` 且无 `last_error` | ❌ | `verify.done_without_result`（error） |
| `outcome="no_results"`（搜了确实没命中）且无文献无错误 | ✅ | `schema` 明确允许（`verify.py:200-217` 的注释逐字记录曾把它误报为 error，已修 → 见 `DEVELOPMENT.md` §10-D4） |

**(b) `literature.download.status`（受控词表）**

`DOWNLOAD_STATUSES = ("ok","content_mismatch","failed","skipped")`（`schema.py:89`）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `skipped → ok` | ✅ | — |
| `ok → content_mismatch` | ✅（**但必须保留字节作为证据**） | `verify.mismatch_without_evidence`（warning） |
| `ok → failed` | ✅ | — |
| `ok` 且 `path` 为空 | ❌ | `verify.ok_without_path`（warning） |

**终态**：就"一条请求"而言，`done=True` 是终态（A 的动作里没有"把 done 改回 False"）。
**但不是不可改的终态**：`literature.download.status` 可以被后续召唤改写
（`table.update` 在 A 的工具面里）。

### A.6 预算与终止条件

| 循环 | 上限 | 出处 | 上限用尽时 |
|---|---|---|---|
| `AgentA.run(max_requests=…)` | 调用方给；CLI `--max` 默认 1 | `cli.py:427`；`agent_a.py:484` | 正常返回，**已处理数**是可读的 |
| 单条请求的尝试次数 | `lease.max_attempts = 3` | `config.yaml:14` | 显式放弃（`outcome="gave_up"`）+ 写 `last_error`；**不静默丢弃** |
| 租约时长 | `lease.seconds = 900` | `config.yaml:12` | 超时后其他实例可重新领取 |
| 单请求下载数 | `agent_a.max_downloads_per_request = 25` | `config.yaml:24` | 停止下载（**注意：`ARunResult.downloaded` 会小于候选数，这是截断，不是"没有找到"**） |
| 单次检索返回条数 | `broad=20 / topical=15 / precise=10` | `config.yaml:19-21` | 返回前 N 条 |
| 全局在途请求 | `interactions.DEFAULTS["max_inflight_requests"] = 20` | `interactions.py:101` | `admit_search_request` 拒绝新请求（**这就是 D 向 A 提问的刹车**，FC-19 判据③） |

> ⚠️ **FC-19 未落地**：**D 向 A 的总提问预算未定值**。现有的只有
> "在途条数 ≤ 20"（瞬时）与 `agent_d.max_total_requests = 20`
> （`agent_d.py:756`，每 run）。**没有 token 预算计量**：
> 实测 `token_meter` / `token_budget` 在 `src/agentflow/**` 里 **0 命中**。
> 新增的 `schema.UsageEntry`（`schema.py:1387`）与 `usage_ledger` 表**已存在**，
> 但**没有一个检索路径往里写**（本次未在 A/B/C 的任何代码里核到写 `usage_ledger` 的调用）。

### A.7 三态与失败模式

A 的"没有结果"逐个列：

| 场景 | 三态形态（实测/代码依据） | 判据 |
|---|---|---|
| **检索源没有命中** | `outcome="no_results"`，`result_lit_ids=[]`，**不是错误** | `SEARCH_OUTCOMES`（`schema.py:76`） |
| **检索源报错（HTTP 4xx/5xx、超时）** | `outcome="search_failed"` + `last_error` 非空 | 同上；`verify.done_without_result` 只在**无** `outcome` 时才报 |
| **尝试用尽** | `outcome="gave_up"` + `last_error` | `lease.max_attempts` |
| **下载失败** | `literature.download = {status:"failed", …}` | `DOWNLOAD_STATUSES` |
| **下载到的东西不是 PDF** | `status="content_mismatch"` + **保留字节** | `verify.mismatch_without_evidence` 保证"有 mismatch 必有证据" |
| **没下载（配置关闭）** | `status="skipped"` | 与 `failed` **分开** —— 这是"没做"不是"做了没成" |
| **`search.dedup_check` 读不到文献表** | ❌ **已知缺陷**：`_literature_rows` 的 `except Exception: return []`（`search_tools.py:585-586`）⇒ `would_be_duplicate=False`、`existing_table_size=0`、**没有任何 warning** | INVENTORY 4.3(a)③；**这是"把没做折叠成没有"的教科书例子** |

**A 已知会犯的错**（引 `LESSONS.md` P1–P16 与 INVENTORY）：

| 模式 | 本项目的实例 | 出处 |
|---|---|---|
| P3 缺省折叠 | `_literature_rows` 吞异常 ⇒ 判重报"不是重复" | `search_tools.py:583-586`；INVENTORY 4.3(a)③ |
| P13 恒值计数器 | `ARunResult.gave_up` 曾**恒为 0**（第一次失败就 `done`，放弃分支永不执行） | `LESSONS.md` P13；`draft/13` §8.7 |
| P1 字符串约定失配 | Crossref `select` 用 `abst`（应 `abstract`）→ 三模式全 400；`language` 是合法字段但不可 `select` | `LESSONS.md` P1；`README.md:156-159`（**已修复并联网复验**） |
| P14 外部契约只能实测 | `.pdf` URL 返回 **12.4 MB HTML**（后缀与状态码两条朴素策略同时失败） | `LESSONS.md` P14 / N19 / N20；`README.md:166-171` |
| P8 规则覆盖缺口 | `precise` 模式曾召回为 0（判据错，不是"本来就少"） | `README.md:160-165`（已修） |

### A.8 不变式（`verify` 检查项名）

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 请求的 `result_lit_ids` 都真实存在 | `dangling_lit_ref` | error |
| 文献的 `source_request_ids` 指向真实请求 | `unknown_request_ref` | warning |
| `done=True` 必须能说清"跑出了什么" | `done_without_result` | error |
| 文献文件真的在盘上 | `file_missing` | error |
| `download.status="ok"` 必须有 `path` | `ok_without_path` | warning |
| `content_mismatch` 必须有证据 | `mismatch_without_evidence` | warning |
| ID 唯一、无空洞、counters 不落后 | `duplicate_id` / `id_gap` / `counter_behind` / `counter_overflow` | error×3 / warning |
| 路径不逃逸工作区 | `path_escape` | error |

### A.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`D`（`:598`）、`F`（`:600`）。
  **A 能被 B/C/E/G/H 召唤吗？不能** —— 边表里没有这些来源。
- **A 能召唤谁**：只有 `B`（`capabilities.py:595`）。
- **入参从哪来**：`search_requests` 表的待办行（由 CLI `submit`、D 的
  `research.submit_gap`、C 的 `gaps(submit_requests=True)`、F 的 `attack.step` 的
  `_deploy_a` 写入）。**待办是唯一入口** —— A 不会被"直接调一个函数"而绕过。
- **产出被谁消费**：
  - `literature` 行 → **B**（抽取）、**D**（溯源到 L3）、**C**（图的节点来源经 B）
  - `library/<lit_id>/*` → **B**（`extract_text`）、`trace.literature`
  - `download.status` → **B**（跳过 `content_mismatch`）、`verify`

### A.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_a
```

**实测输出**：**空**（0 行），**退出码 0**。

⇒ **`agent_a.py` 里没有 `__main__` 自检块**（本次核对：`agent_a.py` 无
`if __name__ == "__main__"`）。因此：

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| **什么也没覆盖** | 全部：`run_once` 的租约/幂等、`SEARCH_OUTCOMES` 四值、判重复用 `lit_id`、下载状态机、`max_downloads_per_request` 截断行为 |

**A 的自检只存在于测试文件**：`tests/test_agent_a.py`（10 例）、
`tests/test_agent_a_priority.py`（26 例）。

---

## B —— 文献整理

### B.1 一句话定位

**B 是全系统唯一能自动发现"幻觉引文"的地方**（`tools/__init__.py:48-49` 逐字）。
它回答：**"这篇文献里到底说了什么？这句话逐字在不在里面？"**

### B.2 职责

| # | 职责 | 判据 |
|---|---|---|
| B-1 | 取未处理文献（`processed=false`） | `AgentB.run_once`（`agent_b.py:229`） |
| B-2 | 抽取概念与关系（`RuleExtractor` 离线基线 / `LLMExtractor` 可插拔） | `llm.py`；`extract_text` |
| B-3 | **逐字引文回验**：回到原文找一遍，定位成功则**存回原文的确切切片** | `quoteverify.py`；`agent_b.py:700-738` |
| B-4 | 关系判重（三级键 + 相似度档） | `dedup.decide_relation`（`dedup.py:203`）；阈值 `dup_strong=0.92` / `dup_review=0.72`（`config.yaml:30-31`） |
| B-5 | 写入期一致性闸门（I6）：问 C 这条新关系与已有关系是否矛盾 | `interactions.check_conflict`（`interactions.py:483`）；**纯函数、签名里没有 store** |
| B-6 | 定向重抽取（I4）：处理 `reprocess_requests` | `AgentB.reprocess_once`（`agent_b.py:496`）；同关系上限 2（`interactions.py:105`） |
| B-7 | 结构重复概念的**合并决定权**（I5） | `decide_structural_duplicate` / `resolve_structural_duplicate`（`agent_b.py:1035/1155`） |

### B.3 明确不负责

| 不做什么 | 为什么不由 B 做 | 该由谁做 |
|---|---|---|
| 检索/下载文献 | 网络副作用只归 A（`search.*` 的 `roles=("A",)`） | **A** |
| 判断一条关系"值不值得研究" | B 抽的是**表述**，不是**价值**；价值判断需要图上结构 | **C** → **D** |
| 决定两个概念该不该合并（当只有**结构**证据时） | 结构重复只是**候选**；`proposal="review"` 是"不得据此合并" | **C** 提候选，**B** 决定，**人**在只有结构证据时确认 |
| 改自己的历史产物（把 `relations` 行删掉） | 关系行一旦落库就有下游引用（`documents` 的 `rel:` 引用）；删除会让引用悬空 | 只能 `status ∈ {active, suspect, rejected}`（`schema.py:67`），**不许删** |
| 发检索请求（"这里缺证据，帮我再找"） | B 的动作里没有"提交请求"；它只能**接受** `reprocess_requests` | **D**（`submit_gaps`）/ **C**（`gaps(submit_requests=True)`，由编排层调） |
| 审校自己的抽取质量 | 自己审自己无法区分"发现"与"掩盖" | **H**（只读） |

### B.4 工具面（18 个，实测）

`side_effect` 分布：`{'read': 12, 'write_local': 6}` —— **B 没有 `network` 也没有 `none`**。

| 工具名 | summary | `side_effect` | 审批 | 参数（**粗体=required**） | 返回结构 | 测试 | 已知问题 |
|---|---|---|---|---|---|---|---|
| `ocr.backends` | 真实探测 OCR 后端 | `read` | 否 | refresh | `backends[]` + `verdict` | `test_tools_search_ocr.py` | INVENTORY 4.4：工作区外 mkdir + 起进程 |
| `ocr.detect_text_layer` | 判断 PDF 有没有文本层 | `read` | 否 | **path** | `has_text_layer`/`pages`/`reason`/… | `test_tools_search_ocr.py` | INVENTORY 4.3(b)：异常逃逸 |
| `ocr.run` | 对指定页做 OCR（都不可用时 **fail**，不返回空文本） | `read` | 否 | **path**；backend, dpi, languages, max_pages, pages | `pages[]` + `backend`/`warnings`/`truncated_pages` | `test_tools_search_ocr.py` | INVENTORY 4.4：**下载 ~100MB 模型**却声明 `read` |
| `fs.list` `fs.read` `fs.search` `fs.stat` | 工作区只读 | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | — |
| `fs.write` `fs.move` `fs.delete` | 工作区写 | `write_local` | **是** | 见 §R0 | 见 §R0 | 见 §R0 | — |
| `table.count` `table.get` `table.list` `table.schema` `table.search` | 表只读 | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | 零提及项见 §R0 |
| `table.create` `table.update` `table.delete` | 表写 | `write_local` | **是** | 见 §R0 | 见 §R0 | 见 §R0 | — |

> **注意**：B 的工具面里**没有** `graph.*` / `trace.*`。B 在写入期问 C 走的是
> **`interactions.check_conflict` 纯函数**（`AgentB` 直接 import），
> **不是**通过工具调用 —— 因为签名里不能有 `store`（锁重入/死锁）。
> 这是设计上的刻意选择，见 `DESIGN-INTERACTIONS.md` §I6。

### B.5 状态机

**(a) `literature.processed`**

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `False → True` | ✅ | — |
| `True → False` | ❌ | `verify.lit_not_processed`（error）—— 被关系引用的文献必须 `processed=true` |

**终态**：`processed=True` 且至少有一条 `relations` 行，即 B 的终态。
**但关系行本身不是终态**：`relations.status` 可变（`active`/`suspect`/`rejected`）。

**(b) `relations.status`**

`RELATION_STATUS = ("active","suspect","rejected")`（`schema.py:67`）。

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

`REPROCESS_STATUSES = ("pending","done","rejected")`（`schema.py:427`）。

| 迁移 | 允许？ | 上限 |
|---|---|---|
| `pending → done` | ✅ | — |
| `pending → rejected` | ✅ | 必须写原因（`REPROCESS_REASONS`，`schema.py:416`） |
| 同关系被重抽取次数 | ≤ `max_reprocess_per_relation = 2` | `interactions.admit_reprocess_request` |

### B.6 预算与终止条件

| 循环 | 上限 | 出处 | 用尽时 |
|---|---|---|---|
| `AgentB.run(max_docs=…)` | 调用方给；CLI `--max` 默认 1 | `cli.py:433` | 正常返回 |
| `run_reprocess(max_requests=…)` | 调用方给 | `agent_b.py:534` | 正常返回 |
| 单关系重抽取 | `max_reprocess_per_relation = 2` | `interactions.py:105` | `admit_reprocess_request` 拒绝（**返回理由，不静默**） |
| 关系判重：强重复 | `dup_strong = 0.92` | `config.yaml:30` | ≥ 阈值 → **拒绝写入** |
| 关系判重：复核档 | `dup_review = 0.72` | `config.yaml:31` | `[0.72, 0.92)` → 写入但标 `suspect` |
| 引文回验放宽 | `quote_widen_pages = 1` | `config.yaml:33` | 超出即 `quote_not_found`（**不许全文兜底**：`allow_fulltext_quote_fallback=false`，`config.yaml:36`） |
| 单关系概念数 | ≥ 2（`too_few_concepts`） | `verify.py:263` | error |

> **硬纪律（FC-11）**：`quote_widen_pages` / `allow_fulltext_quote_fallback`
> **必须由写入方（B）与复核方（`verify --deep`）共用同一份配置**。
> CLI 的 `cmd_verify` 逐字实现了这条（`cli.py:175-184`）。
> **但 `QuotePolicy` 统一配置对象仍不存在**（实测 0 命中）——
> 现在的保证靠"两处都从 `config.yaml` 取"，不是靠类型强制。

### B.7 三态与失败模式

B 的"没有结果"逐个列：

| 场景 | 三态形态 | 依据 |
|---|---|---|
| **引文逐字找到了** | `quote_verified=True` | `schema.py:385` |
| **引文逐字找不到（在声明的页码里）** | `quote_verified=False`，`quote_check.reason="quote_not_found"` | `quote_not_found` |
| **页码未知** | 不做全文兜底（除非显式允许）；`reason="not_found_page_unknown"` | `LESSONS.md` E2 / N7 |
| **空引文** | **不许因为"没得比"判通过**（`"" in "abc"` 是 `True` ⇒ 必须显式挡） | `LESSONS.md` E3 / N6；`reason="empty_quote"` |
| **文献无文本层（扫描版）** | `quote_verified=None`，`reason="no_text_layer"` | `README.md:177-178` |
| **重新抽取失败** | `verify.reextract_failed`（warning）；B 侧记 `unreadable` + `last_mine_error` | `verify.py:801` |
| **文件不存在 / path 为 null** | 记 `unreadable`，**不是** `quote_verified=False` | `agent_b.py:711-714` |
| **`tools=None`（未接线）** | ❌ **历史最尖锐缺陷**：D 曾走"无工具"降级并**静默返回空**，报告写成"未能取到任何关系表述——这本身就是一个重要事实" | `LESSONS.md` P3 / P10；`draft/13` §8 |
| **矛盾闸门没跑** | `conflict_checks_skipped` 单独计数；`checked=False` | `agent_b.py:105` |

**B 的统计字段（FC-10 三分档的正面范例，`agent_b.py:87-107`）**：

`quotes_verified` / `quotes_failed` / `quotes_unknown` **三个独立字段**；
`conflict_checks_run`（`checked=True`）/ `conflicts_detected` / `conflict_checks_skipped`（**`checked=False`**）。
**这是全项目最规范的计数设计**：它把"没查"从"查了没有"里分出来了。

**B 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P7 校验器与写入方参数不一致 | `agent_b` 读 config，`verify --deep` 曾硬编码 `widen=1` ⇒ **假报警** | `LESSONS.md` P7；`cli.py:175-184` 已修 |
| P16 修复过头 | 激活"仅标题匹配"第 3 轮时**必须同时补年份容差**，否则教材第 1 版与第 3 版被合并 | `LESSONS.md` P16 |
| P8 规则覆盖缺口 | 代词黑名单**只在 `len(words)==1` 时生效** ⇒ `This paper` / `when W` 全部通过 | `LESSONS.md` P8 |
| P14 外部契约 | 下载到的 `.pdf` 其实是 12.4 MB HTML ⇒ 网页导航文字被当成概念落库 | `LESSONS.md` P14；`README.md:166-171` |
| P4 检测到了却没消费 | 下载器**正确**打了 `content_type_mismatch`，B 仍照常抽取 | `LESSONS.md` P4；`tests/test_download_handoff.py`（7 例）守住 |

### B.8 不变式

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

### B.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`A`（`:595`）、`D`（`:598`）、
  `E`（`:599`）、`F`（`:600`）。
- **B 能召唤谁**：只有 `C`（`capabilities.py:596`）—— "整理完请 C 看图的形状"。
- **入参从哪来**：
  - `literature` 的 `processed=false` 行（A 写入）
  - `reprocess_requests` 的 `pending` 行（C 的 `structural_duplicates` → D/E/F 提交；
    `REPROCESS_REASONS` 受控）
  - `config.yaml` 的 `agent_b.*` 阈值（`dup_strong` / `dup_review` / `quote_widen_pages` /
    `allow_fulltext_quote_fallback`）
- **产出被谁消费**：
  - `concepts` / `relations` → **C**（图）、**D**（研究问题）、**E**（断言）、**G**（引用）、**H**（审校）
  - `relations.quote_verified` → **C** 的路径评分（`score_breakdown` 里 `quote_verified` 是最强信号，`DESIGN-ROLES.md` §5.4）
  - `suspect` → **D** 的矛盾裁决（I2）

### B.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_b
```

**实测输出**：**空**（0 行），**退出码 0** ⇒ **`agent_b.py` 也没有 `__main__` 自检块**。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| **什么也没覆盖** | 判重三级键、引文回验四种 reason、`suspect` 阈值边界、`reprocess` 上限、结构重复合并 |

**B 的自检只存在于测试文件**：`tests/test_agent_b.py`（9 例）、
`tests/test_agent_b_gates.py`（29 例）、`tests/test_quoteverify.py`（11 例）、
`tests/test_dedup.py`（22 例）、`tests/test_download_handoff.py`（7 例）。

---

## C —— 只读图分析

### C.1 一句话定位

**C 把三张知识表变成可读的结构结论**，且**全量只读**。
它回答：**"这张关系图长什么样？哪里是热点、哪里是空洞、哪两条路径最值得下钻？"**

**C 是唯一"只读但确实会写自己的产出表"的角色**（`capabilities.WRITE_SETS["C"] = {"analysis_reports"}`）。
这不是冲突：C 写的是**它自己说过什么**（`AnalysisReport.persist`，`agent_c.py:319-320`），
它**一行 `concepts`/`relations` 都不碰**。

### C.2 职责

| # | 职责 | 判据 |
|---|---|---|
| C-1 | 最热概念榜（度数中心性） | `AgentC.hottest`（`agent_c.py:469`） |
| C-2 | 两概念之间的路径 + **逐项信息量评分**（7 项 `score_breakdown`） | `AgentC.paths`（`agent_c.py:677`） |
| C-3 | 冷门概念（`degree==0` **单独归一类「完全孤立」**） | `AgentC.cold`（`agent_c.py:1051`） |
| C-4 | 结构缺口候选（`veto` 与 `score` **分离**） | `AgentC.gaps`（`agent_c.py:1347`） |
| C-5 | I1 服务面：`neighbors` / `relations_between`（**三态 + 有界**） | `agent_c.py:1694/1813` |
| C-6 | 矛盾检测（`method="literal"`，`strong`/`weak` 分档） | `AgentC.contradictions`（`agent_c.py:1887`） |
| C-7 | 结构重复候选（`proposal ∈ {merge, review}`） | `AgentC.structural_duplicates`（`agent_c.py:2014`） |
| C-8 | 自然语言需求分派（`kind` 可能是 `unknown`，**不可落库**） | `AgentC.handle`（`agent_c.py:2349`） |

### C.3 明确不负责

| 不做什么 | 为什么不由 C 做 | 该由谁做 |
|---|---|---|
| **写任何知识表** | **这是全系统最硬的一条**：C 一旦能写，它就成了"绕过 B 引文逐字回验"的写入路径 —— 而那是全系统**唯一**能自动发现幻觉引文的地方 | **B** |
| **发起任何召唤**（`ALLOWED_EDGES["C"] = frozenset()`） | 同上：能发起动作 = 能间接产生写入。且工具面里 `graph.gaps` **刻意不暴露 `submit_requests`**（`agent_c.py:2627-2631`） | **D** / 编排层 |
| 决定两个结构重复概念**是否合并** | 只有结构证据时 `proposal="review"` —— "**不得据此合并**" | **B**（`decide_structural_duplicate`） |
| 判一条矛盾"谁对" | 字面判据只能给线索；`weak` 档假阳性极高 | **D**（`adjudicate`）/ **人** |
| 决定要不要把缺口变成检索请求 | 候选缺口是**产出**，不是**决定** | **D**（`submit_gaps`）/ 编排层（`gaps(submit_requests=True)`） |
| 写报告以外的东西 | C 的写集只有 `analysis_reports` | — |

### C.4 工具面（**两层**，合计 17 个 = `cli tools` 报的 `C: 17`）

⚠️ **C 的工具面分两层，必须分开看**：

> **两层合起来才是 `cli tools` 报的那个 17**（`{'C': 17}`），
> 所以本节的口径必须与普查对得上 —— 否则"逐个工具的契约"就无法与工具面 census 对账。
> 第一层 17 个由 `build_registry` 给出（下 §C.4.1 的表格按**工具族**合并了同族的行，
> 展开后是 8 个 graph/trace 工具 + 4 个 `fs.*` + 5 个 `table.*` = 17）；
> 第二层 9 个由 `AgentC.register_tools` 自注册，**不进** `build_registry` 的 17，
> 它们是 §R0.2 点名的"不经 `build_registry` 的 14 个工具"里属于 C 的那一部分。

#### C.4.1 第一层：`build_registry` 给的 17 个（实测）

| 工具名 | summary | `side_effect` | 审批 | 参数 | 返回结构 | 测试 | 已知问题 |
|---|---|---|---|---|---|---|---|
| `graph.build` | 从三张表构建概念图索引，返回图规模摘要 | `read` | 否 | （无） | `{concept_count,relation_count,pair_count,isolated_concepts,degree_top,…}` | `test_tools_graph_trace.py` | 三态位**无** |
| `graph.neighbors` | 某概念的邻居（升序）+ 度数 + **截断信息** | `read` | 否 | **concept_id**；max_neighbors | `{'concept_id','name','degree','total_neighbors','returned_neighbors','truncated','reasons','neighbors':[{'concept_id','name','relation_count','relation_ids'}]}` | `test_tools_graph_trace.py` | ✅ 已修（有界 + 如实报截断） |
| `graph.relations_between` | 两概念间的全部关系（确定性排序） | `read` | 否 | **a**,**b** | `{a,b,count,relations[]}` | `test_tools_graph_trace.py` | — |
| `graph.stats` | 图统计摘要 + 热度前列 | `read` | 否 | top_n | `{…summary…,hot[]}` | `test_tools_graph_trace.py` | INVENTORY 6.4：两个不同长度的 top |
| `trace.chain` | 关系代号链的每一步表述 | `read` | 否 | **relation_ids** | `{level:'chain',relation_ids,steps,chain_text,missing}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)④：静默 `ok` + 空 |
| `trace.concept` | L2 溯源 | `read` | 否 | **concept_id**；with_relations | `{level:'L2',concept,relation_count,relations}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑤ |
| `trace.literature` | L3 溯源（贵） | `read` | 否 | **lit_id**；max_chars, pages | `{level:'L3',status,file_exists,has_text_layer,pages_returned,text,truncated}` | `test_tools_graph_trace.py` | INVENTORY 4.3(a)⑥ |
| `trace.relation` | L1 溯源 | `read` | 否 | **relation_id** | `{level:'L1',relation_id,quote,description,statement,page_range,status,quote_verified,concepts,literature}` | `test_tools_graph_trace.py` | INVENTORY 4.5#7 |
| `fs.list` `fs.read` `fs.search` `fs.stat` | 工作区只读 | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | — |
| `table.count` `table.get` `table.list` `table.schema` `table.search` | 表只读 | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 | 零提及项见 §R0 |

**实测：17 个全部 `read`，0 个写工具，0 个需审批。**

#### C.4.2 第二层：`AgentC.register_tools` 自注册的 9 个（**不经 `build_registry`**）

| 工具名 | summary | `side_effect` | roles | 参数（**粗体=required**） | 返回结构 | 测试 |
|---|---|---|---|---|---|---|
| `graph.hottest` | 最热 top_n 概念（含代表关系与概念名翻译） | `read` | `("C","D")` | top_n（1..100） | `{kind,summary,payload,markdown,warnings,truncated,ok}` | `test_agent_c.py` |
| `graph.paths` | 两个概念之间的多条低重合度路径 + 逐项评分 | `read` | `("C","D")` | **a**,**b**；max_paths(1..50), max_len(1..8), max_overlap(0..1) | `{kind,summary,payload.paths[…score_breakdown…],markdown,truncated}` | `test_agent_c.py` |
| `graph.cold` | 冷门概念（含 `isolated` 单列） | `read` | `("C","D")` | top_n（1..100） | `{kind,summary,payload.entries/undervalued_ids/isolated,markdown}` | `test_agent_c.py` |
| `graph.gaps` | 结构缺口候选 + `veto`/`score` 分离 | `read` | `("C","D")` | limit（1..100） | `{kind,summary,payload.verdict/candidate_gaps,markdown,truncated}` | `test_agent_c.py` |
| `graph.svc_neighbors` | 有界 BFS 邻域（超 `max_nodes` 给 `truncated=True`） | `read` | `("C","D")` | **concept_id**；depth(1..`SERVICE_MAX_DEPTH`), max_nodes | `{checked,concept_id,depth,nodes[],edges[],truncated,empty,reason}` | `test_agent_c_service.py` |
| `graph.svc_relations_between` | 两概念间全部关系（三态） | `read` | `("C","D")` | **a**,**b**；include_inactive | `{checked,a,b,relation_ids[],relations[],empty,filtered_out,reason}` | `test_agent_c_service.py` |
| `graph.contradictions` | 矛盾检查（判据来自 `interactions.detect_contradictions`） | `read` | `("C","D")` | relation_ids, limit | `{checked,scope,scanned,contradictions[],strong_count,weak_count,truncated,method,method_note,reason}` | `test_agent_c_service.py` |
| `graph.structural_duplicates` | 结构重复候选（I5 检测侧） | `read` | `("C","D")` | limit | `{checked,candidates[],truncation_notice,truncated,scanned_concepts,method,reason}` | `test_agent_c_service.py` |
| `graph.check_conflict` | I6 写入期闸门（**纯函数**，全项目唯一实现） | `read` | `("C","D")` | **draft_relation**；existing_relations | `{checked,conflict,conflicts_with[],reason,method,scope,compared}` | `test_agent_c_service.py` |

**⚠️ 已知命名冲突**（`agent_c.py:2554-2560` 与 `:2636-2645` 逐字）：
`graph.neighbors` / `graph.relations_between` 这两个名字**已被低层图工具占用**，
且两者**返回形状不同**（低层给 `{degree, neighbors[]}`，服务版给 `{checked, nodes[], truncated}`）。
按"同名跳过"的既有约定（`agent_c.py:2565-2566`：`if name in registry: return`），
**结果取决于注册顺序**。本次处置是服务版**改名 `graph.svc_*`**，
docstring 明确标注"已知的命名冲突（本次改造发现，未擅自修改）"——
`INVENTORY.md` §4.5#11 把它列为**未决项**。

### C.5 状态机

C 的产出有两类，状态语义完全不同。

**(a) `analysis_reports`（C 的产出登记行）**

| 字段 | 取值 | 硬约束 |
|---|---|---|
| `kind` | `REPORT_KINDS = ("hottest","paths","cold","gaps")`（`schema.py:396`） | `handle()` 可以返回 `kind="unknown"`，**该值不在词表里** ⇒ docstring 明写"**不可落库**"（`capabilities.py:268`） |
| `markdown_path` / `abs_path` | 相对/绝对路径 | `verify.report_file_missing`（warning）：文件不在盘上报 |
| `truncated` | `bool` | 预算截断必须留痕（FC-10 判据） |
| `warnings` | `list[str]` | — |

**终态**：`analysis_reports` 行**写入即终态**（C 没有"改报告"的动作；
`AnalysisReport.persist` 只 append）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| 新建一行 | ✅ | — |
| 改已有报告行 | ❌ | C 的能力表里**没有** update 类动作（`capabilities.py:212-271`） |
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

### C.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 路径条数 | `max_paths=5`（默认） | `agent_c.py:682`；CLI `--max-paths` 默认 5 | 截断并置 `truncated=True` |
| 路径最大跳数 | `max_len=4` | `agent_c.py:683`；CLI `--max-len` 默认 4 | 更长的路径不枚举 |
| 路径重合度 | `max_overlap=0.5` | `agent_c.py:684` | 高重合路径被过滤（"低重合度路径"是需求） |
| 服务面 BFS 深度 | `SERVICE_MAX_DEPTH`（schema 上限） | `agent_c.py:2654` | 参数校验拒绝更大值 |
| 服务面节点数 | `max_nodes` | `agent_c.py:2655` | `truncated=True`（**不静默截断**） |
| 结构重复枚举 | `structural_duplicate_max_pairs = 200` | `interactions.py:107` | 到上限给 `truncation_notice` |
| 缺口直连 A（I3） | `max_gap_requests_per_run = 3` | `interactions.py:104` | 逐条拒绝并**留理由**（自检实测："被拒=1 条，示例理由=本次 gaps 已达每轮上限 max_gap_requests_per_run=3 ⇒ 未提交。"） |
| 全局在途请求 | `max_inflight_requests = 20` | `interactions.py:101` | 在途到上限 ⇒ 新增=0、被拒=4（自检实测） |
| 评分阈值 | `threshold_high=3.0` / `threshold_medium=1.5` | `agent_c.py:122-123` | 分档为 high/medium/low |
| **缓存** | 无 | — | C 每次重新构建图索引（`graph.build` docstring：可自行构建） |

> ⚠️ **C 的"预算截断"是全项目三态纪律的四个动机之一**（`DESIGN-CONDUCTOR.md:116-118` 逐字）：
> "本项目在**引文校验、OCR、D 溯源、C 预算截断**四处都踩过'把没做与做了没结果折叠成同一个值'的坑"。
> 现在 `truncated` 是显式字段，自检也断言它（"另有 23 条中等以上置信度候选超出 limit=6 未展开（已在统计中计数）"）。

### C.7 三态与失败模式

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

**C 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P12 恒值/死代码 | ~~`graph.neighbors` 的裸列表形状~~ ✅ **已修（本轮）**：有界层加在工具层，`RelationGraph.neighbors` 保持裸 list（有证据） | INVENTORY 4.7⑧；`test_tools_attack_graph_fixes.py::test_relation_graph_neighbors_stays_a_plain_list` |
| P9 文档漂移 | `graph.neighbors` / `graph.relations_between` 命名冲突：**服务版已改名 `graph.svc_*`**（low-level 名字仍被占用，`agent_c.py` 的注释记录了这次改名）；本节 §C.4 的契约已按实现更正 | INVENTORY 4.5#11；`test_core_audit_abc_cli.py::test_service_tool_names_resolve_the_documented_collision` |
| P14 外部契约 | `detect_contradictions` 的 `only_a != only_b` 逻辑错误：25 条真实关系上报出 6 条 `suspect`（24%），**没有一条是真矛盾** | `draft/13` §8.1 |
| P6 派生态当输入 | `concept_pair_key` 读了不存在的字段名（表里是 `concept_group_key`）⇒ 对**直接从表里读出来的行**恒返回 `[]`，**完全静默** | `draft/13` §8.2；`interactions.py:232-238` 的注释逐字记录 |

### C.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 报告 markdown 文件存在 | `report_file_missing` | warning |
| 报告行 ID 唯一 | `duplicate_id` | error |
| 数组字段已声明 | `undeclared_array_field` | error |
| **C 不能写知识表** | 由 `capabilities.assert_capabilities()` 的**只读角色写集例外**断言保证（`capabilities.py:725-734`） | 导入期 `AssertionError` |
| **C 的工具面 0 个写工具** | `tools.base.ToolRegistry.for_role` 结构性剥离 + `role_filter_notes` 留痕 | 实测 0 |
| **C 不能发起召唤** | `ALLOWED_EDGES["C"] is empty`（`capabilities.py:597`） | 静态表 |

### C.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`B`（`:596`）、`D`（`:598`）、
  `F`（`:600`）。**C 也能被 `A`/`E`/`G`/`H` 召唤吗？不能。**
- **C 能召唤谁**：**没有人**（`ALLOWED_EDGES["C"] = frozenset()`，逐字理由见 `capabilities.py:588-590`）。
- **入参从哪来**：`concepts` / `relations` 表（B 写入）；`request` 原文（人/编排层给的）。
- **产出被谁消费**：
  - `analysis_reports` 行 + `reports/*.md` → **D**（`ingest` 把它消化成研究问题）
  - `candidate_gaps` → **D** / 编排层 → `search_requests`（I3）
  - `structural_duplicates` 候选 → **B**（`decide_structural_duplicate`）
  - `contradictions` → **D**（I2 裁决）

### C.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_c
```

**实测输出（末尾逐字）**：

```
    [PASS] I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由
========================================================================
自检断言：46/46 通过
SELF-CHECK DONE
```

**退出码 0**。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| 9 个动作的分析器主路径（含 `hottest`/`paths`/`cold`/`gaps`） | 真实规模图上的性能与内存 |
| I1 服务面三态（`checked`/`empty`/`truncated`） | `handle()` 的 NL 分派质量（`kind="unknown"` 的语料） |
| `contradictions` 的 `strong`/`weak` 分档与 `method_note` | `detect_contradictions` 在真实论文语料上的假阳性率（自检用的是**人造矛盾**） |
| `structural_duplicates` 的正反两向（含负控："邻域相同但名字不同 ⇒ `proposal=review`"） | `graph.build`/`graph.stats` 的三态（**它们没有 `checked` 位**） |
| I3 缺口直连 A 的闸门（开启/关闭/超限三态） | — |
| "I1 服务面只读：三张知识表逐字节不变" | — |

---

## D —— 研究

### D.1 一句话定位

**D 把 C 的分析结论变成"研究问题"，并在证据就绪时给出带置信度的回答**。
它回答：**"这个结构缺口值不值得研究？现在证据够不够？不够的话该问谁？"**

### D.2 职责

| # | 职责 | 判据 |
|---|---|---|
| D-1 | 把 C 报告消化成研究问题（**内容键去重**） | `ingest` / `ingest_detailed`（`agent_d.py:1200/1406`）；去重键 `(kind, 排序后的 related_relation_ids)` |
| D-2 | 用**可核实判据**判断"知识不足" | 三条：`a_no_keyword_hit` / `b_low_degree_unverified` / 矛盾（`DESIGN-INTERACTIONS.md` §6.4） |
| D-3 | 向 A 提问（把缺口变成 `search_requests` 行） | `submit_gaps`（`agent_d.py:2133`）；配额 `max_requests_per_question=2`、`max_total_requests=20` |
| D-4 | 复查在途请求与文献消化进度 | `poll`（`agent_d.py:2262`）；`poll_waiting` 纯只读 |
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
| 改关系的 `status`（把 `suspect` 改 `active`） | D 的写集是 `{research_questions, search_requests, relations}` —— **`relations` 在写集里** ⇒ 这是**已知的越界面**，需要专门看（见下方 ⚠️） | 理论上是 **B**（重抽取） |
| 做实验/形式化 | 实验需要子进程与脚本，是 E 的职责 | **E**（`D → E`） |
| 立项攻坚 | 攻坚有独立的三维预算与终止条件，必须唯一主人 | **F**（`D → F`，I10 升级） |
| 写稿件 | 稿件有话术/引用格式/降级规则 | **G** |
| 审校自己的结论 | D 是产出者 | **H** |

> ⚠️ **D 的写集包含 `relations`**（`capabilities.WRITE_SETS["D"]`，`capabilities.py:527`）。
> 代码里的注释给的理由是"`agent_d.py:2306 research_questions+relations`"（裁决矛盾时
> 会把关系标 `suspect`/`rejected`）。**这确实是一个需要审计的权限面**：
> 它是唯一一个"研究角色能改知识表"的路径。本次**未逐行核实**
> `agent_d.py:2306` 处到底改了什么字段 —— **标 `（据 capabilities.py 注释，未在代码中逐行核实）`**。

### D.4 工具面（37 个，实测 —— **全项目最宽**）

`side_effect` 分布：`{'read': 23, 'write_local': 9, 'none': 5}`

| 组 | 工具 | `side_effect` | 审批 |
|---|---|---|---|
| `research.*`（5） | `list_gaps` `poll_waiting` `set_status` `submit_gap` `write_note` | 3 读 2 写 | `set_status`/`submit_gap`/`write_note` **需审批** |
| `attack.*` 只读侧（4） | `check_budget` `list_plans` `pick_next_subgoal` `status` | `none`/`none`/`read`/`read` | 否（D **不能** `create_plan`/`step`） |
| `doc.*` 只读侧（3） | `compose_claim` `list_documents` `scan_claim` | `none`/`read`/`none` | 否 |
| `review.*` 只读侧（2） | `list_findings` `scan_document` | `read`/`none` | 否 |
| `graph.*`（4） | `build` `neighbors` `relations_between` `stats` | 全 `read` | 否 |
| `trace.*`（4） | `chain` `concept` `literature` `relation` | 全 `read` | 否 |
| `fs.*`（7） | `list` `read` `search` `stat` `write` `move` `delete` | 4 读 3 写 | 写侧**需审批** |
| `table.*`（8） | `count` `get` `list` `schema` `search` `create` `update` `delete` | 5 读 3 写 | 写侧**需审批** |

> **D 拿不到**：`search.*`（A）、`ocr.*`（B）、`verify.*`（E/F/G/H）、
> `doc.build_document`/`doc.register_dependency`（G）、
> `review.review_document`/`verify_fixes`（H）、`attack.create_plan`/`step`（F）。
> **这是"角色即权限面"的直接体现**：D 想立项必须显式调 `AgentF`
> （`attack_tools.py:54-60` 的注释逐字解释了为什么）。

### D.5 状态机（**全项目唯一有显式迁移表的状态机**）

`tools/research_tools.py:481-487` 的 `LEGAL_TRANSITIONS` **本身就是文档**：

| 从 | 允许到 | 谁拦 |
|---|---|---|
| `open` | `needs_evidence`, `researching`, `dropped` | `research.set_status`（`research_tools.py:532-537`）+ `schema.ResearchQuestion.validate` |
| `needs_evidence` | `researching`, `dropped` | 同上 |
| `researching` | `needs_evidence`, `answered`, `dropped` | 同上 |
| `answered` | **（空）终态** | 同上 |
| `dropped` | **（空）终态**（且**必须写明理由**） | `schema.ResearchQuestion.validate` |

**关键约束**（`schema.py` 交叉检查，FC-04 判据②）：

| 状态 | 必须满足 | 违反时 |
|---|---|---|
| `needs_evidence` | `waiting_request_ids` **非空** | schema `ValueError` |
| `dropped` | `notes` **非空** | schema `ValueError` |
| `answered` / `dropped` | `waiting_request_ids` **应为空** | `verify.stale_waiting`（warning） |

**为什么非法迁移必须 fail 而不是静默接受**（`research_tools.py:511-514` 逐字）：
"如果 `answered → open` 被放行，'已给出结论'这件事就不再是终局，
报告与台账之间会永久性地互相矛盾，而**没有任何一处会报错**。"

**D 的 `research()` 只处理 `researching`** —— 这正是 `LESSONS.md` P2
（状态机缺边）的原始现场：曾经「证据足够」这一支什么都不做，于是问题永远停在
`open`，而 `research()` 只处理 `researching` ⇒ **永远不被研究，报告里也没有证据**。
修法是新增 `consider()` 完成路由（足够 → `researching`；不足 → 提问）。

### D.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 一次 ingest 建多少问题 | `max_questions = 5` | `agent_d.py:753` | 只建前 5 个（**超出部分是否留痕：未核实**） |
| 冷门判据阈值 | `degree_threshold = 2` | `agent_d.py:754` | 度数 < 2 且未验证 ⇒ `b_low_degree_unverified` |
| 单问题提问数 | `max_requests_per_question = 2` | `agent_d.py:755` | 不再提问 |
| 单 run 总提问数 | `max_total_requests = 20` | `agent_d.py:756` | 不再提问 |
| L3 下钻文献数 | `max_l3_lits = 3` | `agent_d.py:757` | 截断（**应留痕 —— 未核实**） |
| L2 上下文条数 | `max_l2_context = 6` | `agent_d.py:761` | 截断 |
| 矛盾追问轮数 | `max_rounds_per_contradiction = 2` | `interactions.py:102`；`agent_d.py:776` | `adjudicate_contradiction` 返回 `persistent` |
| 矛盾检索请求总数 | `max_contradiction_requests = 10` | `interactions.py:103`；`agent_d.py:780` | 拒绝新请求 |
| 单轮 C 邻居查询 | `max_c_neighbor_queries = 2` | `agent_d.py:783` | 不再点菜 |
| 单轮 C 成对查询 | `max_c_pair_queries = 2` | `agent_d.py:784` | 不再点菜 |
| 单轮 C 矛盾扫描上限 | `max_c_contradictions = 20` | `agent_d.py:785` | 截断 |
| 单轮裁决数 | `max_adjudications_per_round = 10` | `agent_d.py:787` | 停止裁决 |
| 问题等价类阈值 | `question_jaccard_threshold = 0.6` | `interactions.py:106` | `find_equivalent_question` 判"这是新研究点" |
| 全局在途请求 | `max_inflight_requests = 20` | `interactions.py:101` | `admit_search_request` 拒绝 |
| `run_round` 轮数 | CLI `--gap-rounds` 默认 2 | `cli.py:477` | 正常返回 |

> ⚠️ **FC-19 未落地**（`DESIGN-CONDUCTOR.md` 与 `LESSONS.md` 都点名）：
> **token 预算计量的代码在 `src/agentflow/**` 里 0 命中**（实测 `token_meter` / `token_budget` = 0）。
> `schema.UsageEntry` + `usage_ledger` 表**已有**，`verify` 已有
> `dangling_usage_task` / `usage_task_total_mismatch` 两条检查，
> 但**没有任何 D/A/B 路径往里写**（本次未在 `agent_*.py` 里核到 `usage_ledger` 的写入调用）。

### D.7 三态与失败模式

| 场景 | 三态形态 | 依据 |
|---|---|---|
| **两个参数都不给** | `checked=False`（"**没查 ≠ 查了没有**"） | `verify.evidence_for` 的 `returns`（工具 #53） |
| 给了参数但没命中 | `checked=True` + `experiments=[]` | 自检实测（`agent_e` 自检第 [7] 项逐字："给了参数但没有 ⇒ `checked=True` 且 `experiments=[]`"） |
| 请求已结束但 B 未消化 | `waiting`，reason 逐字："请求已结束，但结果文献还没被 B 消化完（`processed=false`）" | 自检实测 |
| 请求未结束 | `waiting`，reason 逐字："仍有查询请求未结束（A 还没跑完 / 还没跑到）" | 自检实测 |
| **证据足够** | 走 `consider()` → `researching`（**不许什么都不做**） | `LESSONS.md` P2 |
| **置信度不许拔高** | 自检实测：确定性 `medium` + LLM 声称 `high` ⇒ **强制 `medium`** | `DESIGN-ROLES.md` §6.6；自检第 [10] 项 |
| 一致但样本有限 | `medium` + 判据 `a_no_keyword_hit`，结论逐字"证据方向一致但样本有限（且部分引文未通过校验），结论应视为待复核的假设" | 自检实测 |
| 证据不足 | `low` + 逐字"本节的措辞刻意停在「可能存在/尚未证实」，**不作为可引用的判断**" | 自检实测 |
| 内容重复的问题 | 按内容键去重，**已存在时不新建行，把新 `origin` 追加留痕**；实测问题数 4 → 2 | `LESSONS.md` P10 (#8) |
| 记录工具失败 | `last_tool_errors` 必须**可在任何路径上被写入**（曾因惰性创建使"记录失败的代码自己炸掉"） | `draft/13` §8.5；`agent_d.py:712-716` |

**D 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| **P3 缺省折叠（最尖锐）** | `tools=None` 走降级分支并**静默返回空**，报告写成"未能取到任何关系表述（L1/L2 均为空）——**这本身就是一个重要事实**"。而"L1/L2 为空"在 D 的判据里又是"知识不足"的信号之一 ⇒ "这个错误会**伪装成一个合理的结论**（'查过了，没有'）" | `LESSONS.md` P3 / P10；`draft/13` §8 |
| **P10 接线缺失** | 同上（D 未接 registry）；另有 `AgentF._deploy_e` 没有降级路径 | `draft/13` §8.6 |
| P2 状态机缺边 | 「证据足够」支什么都不做 ⇒ 问题永远停在 `open` | `LESSONS.md` P2 |
| P5 静默数据丢失 | `AgentD.last_tool_errors` 惰性创建 ⇒ `AttributeError` | `draft/13` §8.5 |
| P1 断言假绿 | `draft/13` §8.4 记录的"字段名用错导致断言假绿"在 `abflow` 里**未能复核** | `draft/13` §8.4（**未核实**） |

### D.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 概念/关系/文献/请求引用闭合 | `dangling_concept_ref` / `dangling_relation_ref` / `dangling_lit_ref` / `dangling_request_ref` | error |
| 终态不留等待集 | `stale_waiting` | warning |
| 研究问题不建立在被否关系上 | `question_based_on_retracted_relation` | warning |
| `research_request_ledger.json` 一致性 | `ledger_corrupt` / `ledger_bad_row` / `ledger_dangling_question` / `ledger_dangling_request` / `ledger_drift` | error×4 / warning |
| 实验/计划的 `for_question_id` 真实存在 | `dangling_question_ref`（experiments / attack_plans 两处） | error |

### D.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`F`（`:600`）、`G`（`:601`，**"写稿时发现缺证据 → 回去要"**）。
  `D` 也能被 `E` 召唤（`E → D`，反例回流，`:599`）。
- **D 能召唤谁**：`A B C E F`（`capabilities.py:598`）。**不能召唤 G/H。**
- **入参从哪来**：
  - `analysis_reports`（C 的产出）
  - `relations` / `literature`（B 的产出）
  - `config.yaml` 的 `agent_d.*`（**当前 `config.yaml` 里没有 `agent_d` 段** —— 全部走代码默认值）
  - CLI `research --report-id --gap-rounds`（`cli.py:475-478`）
- **产出被谁消费**：
  - `research_questions` → **C**（图上对应位置）、**F**（升级立项）、**E**（`for_question_id`）
  - `search_requests` → **A**
  - `reports/*-research.md` → **G**（写稿的证据）、**H**（审校）
  - 置信度 → **G**（`documents.claims` 的证据等级）

### D.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_d
```

**实测输出（末尾逐字）**：

```
[13] 最终状态：[('0000', 'researching', 'medium'), ('0001', 'researching', 'medium'), ('0002', 'needs_evidence', 'medium')]
========================================================================
SELF-CHECK DONE（agent_d）
```

**退出码 0**；自检共 13 个编号步骤。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| ingest → assess → submit → poll → research → write_report 全链 | "证据足够"支的完整迁移（自检里 `poll` 的 `promoted` 为空） |
| 内容键去重（"再提交一次（查重）：[] skip=已有未完成的查询请求，未重复提交"） | `D → F` 升级路径（I10） |
| poll 的四种等待原因（逐字人话） | 真实 LLM 钩子（`llm_used=False`，无 API key） |
| 置信度不许拔高（假 LLM 声称 high ⇒ 强制 medium） | 大图上 `max_l3_lits` / `max_l2_context` 的截断留痕 |
| `write_report` 的代号溯源（"含「置信度」小节：True；含代号溯源：True"） | `research_request_ledger.json` 的偏离检查 |

---

## E —— 数值实验与形式化验证

### E.1 一句话定位

**E 产出"证据"，且必须标注证据等级**。它回答：**"这条命题，跑一遍算不算支持它？形式化检查器认不认？"**

### E.2 职责

| # | 职责 | 判据 |
|---|---|---|
| E-1 | 在**独立进程**里跑工作区脚本，登记 `Experiment` 行 | `AgentE.run_experiment`（`agent_e.py:518`）；`verify.run_experiment` 工具 |
| E-2 | **计算类方法拿不到 `proof`**：脚本自报 `proof` 会被**降级**为 `cross_check` | 自检实测："脚本自报 proof 被降级为 cross_check"+"notes 里记下了这次越权" |
| E-3 | 崩溃一律记 `inconclusive` + `no_local_evidence` | 自检实测："崩溃 ⇒ inconclusive"、"崩溃 ⇒ no_local_evidence" |
| E-4 | 超时同样记 `inconclusive` + `exit=None` | 自检实测 |
| E-5 | 查已有证据（**三态**） | `evidence_for`（`agent_e.py:640`） |
| E-6 | 形式化检查：**没有后端时如实回答「没做」** | `check_formal`（`agent_e.py:619`）；`checked=False, reason="no_backend", verified=None` |
| E-7 | 绑定脚本的可复现性（`code_hash`） | `verify.code_hash`；`Experiment.code_hash` |

### E.3 明确不负责

| 不做什么 | 为什么不由 E 做 | 该由谁做 |
|---|---|---|
| 说"命题被证明了" | **数值实验不构成证明**（`LESSONS.md` M4；`draft/17` §4.4）；E 的 `proof` 只能来自**形式化检查器**，而桥接层未接线 | **形式化检查器**（外部）/ **人** |
| 把 `supports` 当成 `closed` | 实测断言："只有数值证据却标 closed ⇒ schema 抛（FC-22）" | **F** / **G** 的写入被 schema 硬拦 |
| 写稿件/断言 | 断言的话术、引用、降级规则是 G 的 | **G** |
| 决定要不要再跑一个实验 | E 的动作只有 5 个（`capabilities.py:354-390`），**没有"自己决定再跑"** | **F**（`attack.step` 的 owner 分派）/ **D**（`D → E`） |
| 改关系/概念 | E 的写集只有 `{experiments}` | **B** |
| 判断"这条实验的结论值不值得写进报告" | 价值判断在 G/H | **G** / **H** |

### E.4 工具面（21 个，实测）

`side_effect` 分布：`{'read': 13, 'write_local': 7, 'none': 1}`

| 组 | 工具 | `side_effect` | 审批 |
|---|---|---|---|
| `verify.*`（6） | `check_formal` `code_hash` `detect_verifier` `evidence_for` `list_experiments` `run_experiment` | read / read / none / read / read / **write_local** | 只有 `run_experiment` **需审批** |
| `fs.*`（7） | `list` `read` `search` `stat` `write` `move` `delete` | 4 读 3 写 | 写侧**需审批** |
| `table.*`（8） | `count` `get` `list` `schema` `search` `create` `update` `delete` | 5 读 3 写 | 写侧**需审批** |

**逐条契约**见 §R0 的 #50–#55（`verify.*`）+ 公共项。

> **E 拿不到**：`ocr.*`（B）、`graph.*`/`trace.*`（C/D）、`search.*`（A）、
> `research.*`（D）、`attack.*`、`doc.*`、`review.*`。
> ⚠️ **E 也没有 `attack.*`** —— 所以 E 无法自己立项；`attack.step` 里
> `owner="E"` 的分派是**由 F 调用 E 的方法**（`agent_f.py:767` 的 `_deploy_e`），
> 不是 E 调工具。

### E.5 状态机

**(a) `Experiment` 的二维状态（结果 × 证据等级 × 否定分类）**

| 字段 | 取值 | 约束 |
|---|---|---|
| `method` | `EXPERIMENT_METHODS = ("numeric","symbolic","exhaustive_search","formal")`（`schema.py:621`） | 受控 |
| `evidence_kind` | `EVIDENCE_KINDS = ("proof","cross_check","heuristic")`（`schema.py:633`） | **计算类拿不到 `proof`** |
| `result` | `EXPERIMENT_RESULTS = ("supports","refutes","inconclusive")`（`schema.py:636`） | 受控 |
| `negation_kind` | `NEGATION_KINDS = ("disproved","not_proved","not_searched_here","no_local_evidence")`（`schema.py:647`） | 受控 |
| `verifier_subject_key` | 字符串 | **`evidence_kind="proof"` 时必填**（`schema.py:810`）："否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'" |
| `counterexample` | 结构 | `result="refutes"` 时**必须给**（`verify.refutation_without_counterexample`，error） |
| `code_hash` | 字符串 | 必须有（`verify.unhashed_experiment_code`，error） |
| `for_question_id` | 4 位代号 | 必须存在（`verify.dangling_question_ref`，error） |

**允许的迁移**（由 `schema.Experiment.validate` 与 `verify` 共同硬拦）：

| 从 → 到 | 允许？ | 谁拦 |
|---|---|---|
| `supports` + `evidence_kind="cross_check"` → 计划 `closed` | ❌ | `verify.proof_claim_rests_on_weaker_evidence`（error）；自检实测："只有数值证据却标 closed ⇒ schema 抛（FC-22）" |
| `supports` ⇒ `negation_kind="not_proved"` | ✅ | 自检实测通过（"result=supports ⇒ negation_kind=not_proved"） |
| `refutes` ⇒ `negation_kind="disproved"` | ✅ | 但必须给 `counterexample` |
| `inconclusive` ⇒ `negation_kind="no_local_evidence"` | ✅ | 自检实测（崩溃/超时/无结论行三条路径） |
| `evidence_kind="proof"` 但无 `verifier_subject_key` | ❌ | `schema.py:810` 抛 |
| 依赖 `status="closed"` 而 `experiment.result="inconclusive"` | ❌ | `verify.closed_dep_on_inconclusive_experiment`（error） |

**终态**：`Experiment` 行**写入即终态**（无 update 动作）。

### E.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 脚本超时 | `agent_e.timeout` 默认 **600s** | `agent_e.py:388`；工具参数 `timeout` | 自检实测："超时 ⇒ inconclusive / exit=None / notes='[run] exit_code=None，**超时**（timeout=1s），runtime=1.031s，脚本 slow_probe.…'" |
| 一次 `run_experiment` 写几行 | **恰好 1 行** | 自检实测："事务性：experiments 5 -> 6"、"一次 run_experiment 只多一行" | — |
| 路径越界 | 必须来自工作区内相对路径 | 自检实测："路径越界被拒绝" | 拒绝 |
| 脚本自报 `proof` | **降级为 `cross_check`** | `verify.run_experiment` 的 `summary` 逐字；自检实测 | `notes` 记下这次越权 |
| 形式化检查器 | 无后端 ⇒ 不跑 | 自检实测："无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False）" | `checked=False` |
| 超时/崩溃的退出码 | 崩溃 `exit=3`；超时 `exit=None` | 自检实测 | 记 `inconclusive` |
| 子进程环境 | `env = dict(os.environ)`（**继承完整环境，可联网**） | INVENTORY 4.4（`agent_e.py:475`） | ⚠️ **未隔离**（FC-07 的"执行进程"档缺失） |

### E.7 三态与失败模式

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

**E 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P14 / FC-07 副作用声明 | `verify.run_experiment` 声明 `write_local` 但**跑子进程且继承完整环境**；`verify.detect_verifier` 声明 `none` 却 `subprocess.run` | INVENTORY 4.4（7 处不一致中的 2 处） |
| P9 文档漂移 | `verify.detect_verifier` docstring 说 `checked=False` 只表示"探测本身没做成"，但实现里 `"checked": True` 是**硬编码**的，没有任何代码路径能返回 `False` | INVENTORY 4.5#1 |
| P9 文档漂移 | `verify.check_formal` 的 `summary` 写"把命题交给形式化检查器核验"，而主路径返回 `fail(kind="not_implemented")` | INVENTORY 4.5#2 |
| P1 路径判据两份 | `verify_tools._resolve`（拒绝工作区内绝对路径）vs `AgentE._resolve`（**接受**）⇒ `verify.code_hash` 会拒绝一个 `run_experiment` 乐意执行的路径 | INVENTORY 4.7⑩ |
| P3 返回值契约 | `verify.check_formal` 无后端时 `res.ok is True`（`checked=False`）⇒ **只看 `res.ok` 会误读** | INVENTORY 4.3(c) |

### E.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| `for_question_id` 存在 | `dangling_question_ref` | error |
| 证据等级不许过度声称（FC-22） | `evidence_kind_overclaim` | error |
| 脚本必须有 `code_hash` | `unhashed_experiment_code` | error |
| `refutes` 必须给反例 | `refutation_without_counterexample` | error |
| 稿件不得把 `cross_check` 当 `proof` | `proof_claim_rests_on_weaker_evidence` | error |
| `closed` 的依赖不得指向 `inconclusive` 实验 | `closed_dep_on_inconclusive_experiment` | error |
| 同 `claim_key` 同口径的数字不许冲突 | `eval_duplicate_conflicting` | error |
| 路径不逃逸工作区 | `path_escape` | error |

### E.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`D`（`:598`）、`F`（`:600`）、`G`（`:601`）。
- **E 能召唤谁**：`B`（"引文不可核实 → 请 B 重抽取"）与 `D`（"发现反例 → 回 D"）
  （`capabilities.py:599`）。
- **入参从哪来**：`claim` / `claim_key` / `script_path`（调用方给的）；
  `capabilities.py:354-390` 的 params schema 是**唯一**的机器可读契约。
- **产出被谁消费**：
  - `experiments` 行 → **F**（`attack_plans.experiment_ids` / `proof_experiment_ids`）、
    **G**（`documents.claims` 的 `exp:` 引用）、**H**（审校证据）、**D**（`for_question_id`）
  - `evidence_kind` → **G**（断言等级）/ **H**（`overclaim` 检查）

### E.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_e
```

**实测输出（末尾逐字）**：

```
[9] check_formal ⇒ checked=False reason='no_backend' verified=None
    [PASS] 无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False）
========================================================================
SELF-CHECK DONE（agent_e）：失败 0 项
```

**退出码 0**。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| 三条失败路径（崩溃 / 超时 / 无结论行）= 3 个 `inconclusive` 分支 | `method="formal"` 的**真实**后端路径（本机无 Lean/Coq/Isabelle） |
| `proof` 越权的降级 + notes 留痕 | `evidence_kind="proof"` 的正常路径（需要真检查器） |
| `evidence_for` 的全部四态 | `params` 传递与 `for_question_id` 的引用闭合 |
| 路径越界拒绝 | `E → B` / `E → D` 的实际召唤（边表有，自检没跑） |
| 事务性（只多一行） | `code_hash` 的绑定校验 |

---

## F —— 多轮难题攻坚

### F.1 一句话定位

**F 产出"过程"，且必须有三维预算与终止条件**。
它回答：**"这个难题，我能在有限预算内推进到哪一步？推不动时我如实说什么？"**

### F.2 职责

| # | 职责 | 判据 |
|---|---|---|
| F-1 | 立项（**预算四类键缺一不可，不完整就拒绝创建**） | `AgentF.create_plan`（`agent_f.py:269`）；`attack.check_budget` |
| F-2 | 按确定性次序选下一个子目标 | `attack.pick_next_subgoal`（"开始过的优先，卡住的最后"） |
| F-3 | 推进一轮：按 `owner` 分派（E 做实验 / A 提检索 / B 提重抽取） | `AgentF.step`（`agent_f.py:423`） |
| F-4 | **C/D/F 的推理未接线时如实记 `no_change`，绝不假装做了** | `attack.step` 的 `summary` 逐字 |
| F-5 | 到终止条件时交 `best_partial`：**不是失败，也不是成功** | `status="stalled"` |
| F-6 | 数值实验**不许关闭子目标**（FC-22） | 自检实测："数值实验**不许**关闭子目标（FC-22）" |

### F.3 明确不负责

| 不做什么 | 为什么不由 F 做 | 该由谁做 |
|---|---|---|
| 自己"想数学" | `attack.step` 的 `summary` 逐字："C/D/F 的推理**未接线**" —— 本轮的 F 是**确定性调度器**，不是推理者 | 由 `SubagentBackend` 承担（**未接线**） |
| 写知识表 | F 的写集是 `{attack_plans, search_requests, reprocess_requests}` | **B** |
| 把 `supported_not_proved` 说成 `resolved` | FC-22：无任何 `proof` 时计划状态**只能**是 `supported_not_proved` | schema 硬拦（自检实测："计划状态随之变成 `supported_not_proved`（无任何 proof）"） |
| 无限重试 | `TERMINAL_STATUSES` 含 `stalled`；`stalled` 不可重入 | `attack_tools.py:72-75` |
| 决定难题值不值得攻坚 | 立项是**D 的升级决定**（I10） | **D**（`D → F`） |
| 审校自己的攻坚过程 | F 是产出者 | **H** |

> ⚠️ **`AgentF._deploy_e` 曾没有降级路径**（`draft/13` §8.6），现已是
> `blocked` + `blocked_reason` 并继续（FC-21 部分落地）。**无
> `run_best_effort` / `run_all_or_nothing` 两种显式 API**（实测 0 命中）。

### F.4 工具面（32 个，实测）

`side_effect` 分布：`{'read': 17, 'write_local': 9, 'none': 6}`

| 组 | 工具 | `side_effect` | 审批 |
|---|---|---|---|
| `attack.*`（6，**全部**） | `check_budget` `create_plan` `list_plans` `pick_next_subgoal` `status` `step` | none / **write** / read / none / read / **write** | `create_plan` / `step` **需审批** |
| `verify.*`（6） | `check_formal` `code_hash` `detect_verifier` `evidence_for` `list_experiments` `run_experiment` | read×3 / none / read×2 / **write** | `run_experiment` **需审批** |
| `doc.*` 只读侧（3） | `compose_claim` `list_documents` `scan_claim` | none / read / none | 否 |
| `review.*` 只读侧（2） | `list_findings` `scan_document` | read / none | 否 |
| `fs.*`（7） | 4 读 3 写 | — | 写侧**需审批** |
| `table.*`（8） | 5 读 3 写 | — | 写侧**需审批** |

> **`attack.create_plan` / `attack.step` 的 `roles=("F",)` —— 只有 F 能写计划**
> （`attack_tools.py:52-60` 的注释逐字："谁需要**看见**这件事与谁有权**决定**这件事
> 是两个不同的问题"）。
>
> **F 拿不到**：`graph.*` / `trace.*` / `research.*` / `search.*` / `ocr.*`。
> ⇒ **F 想"问图"必须通过同伴召唤 `F → C`**，不是自己调工具。这是边表与工具面**一致**的体现。

### F.5 状态机

**(a) `attack_plans.status`**

`ATTACK_STATUSES = ("open","attacking","progress","supported_not_proved","stalled","resolved","abandoned")`（`schema.py:654`）。

| 状态 | 终态？ | 判据 |
|---|---|---|
| `open` | 否 | 刚立项 |
| `attacking` | 否 | 有子目标 `in_progress` |
| `progress` | 否 | 本轮有推进 |
| `supported_not_proved` | **是**（`attack_tools.py:75` 未列，但 `agent_f.py:820` 会写它） | 全部子目标 `closed`/`supported_not_proved` 且**无任何 `proof`** |
| `stalled` | **是**（`TERMINAL_STATUSES` 含它） | 连续 3 轮无进展 或 轮数用尽 |
| `resolved` | **是** | 有 `proof` 级证据 |
| `abandoned` | **是** | 人/上层放弃 |

> ⚠️ **两处"终态"名单不一致**（**本次实测发现**）：
> `attack_tools.TERMINAL_STATUSES = ("resolved","abandoned","stalled")`（`attack_tools.py:75`）
> **不含 `supported_not_proved`**，而 `schema.ATTACK_STATUSES` 有它、`agent_f.py:820` 会写它。
> 后果：`attack.list_plans` 的 `include_terminal` 过滤会把 `supported_not_proved`
> 的计划当成**未终结**继续列出。**这是否会影响 `stalled` 的不可重入判据：未核实**。

**`stalled` 必须写 `best_partial`**（`verify.stalled_without_partial`，error）。
自检实测逐字：

```
[8] 终止 ⇒ status=stalled rounds=5 best_partial=[提前停止] 连续 3 轮无进展（全部 outcome=no_change）⇒ 不再烧预算。 已进行 5 轮。子目标进展（按'离终结有多近'排序）：…
    [PASS] 终止 ⇒ stalled
    [PASS] 轮数不超过 max_rounds
    [PASS] best_partial 非空（且如实）
    [PASS] 停止路径写清楚了（提前停止 或 轮数用尽）
    [PASS] stalled 后不再推进（终态不可重入）
```

**(b) 子目标 `Subgoal.status`**

`SUBGOAL_STATUSES = ("todo","in_progress","supported_not_proved","closed","blocked","dropped")`（`schema.py:658`）。

| 迁移 | 允许？ | 谁拦 |
|---|---|---|
| `todo → in_progress` | ✅ | — |
| `in_progress → closed` | ✅ **仅当有 `proof` 级证据** | FC-22；自检实测 |
| `in_progress → supported_not_proved` | ✅（只有 `cross_check` 时唯一合法终点） | `agent_f.py:1004` |
| `in_progress → blocked` | ✅（**必须写 `blocked_reason`**） | `schema`；自检实测："卡点写进 `blocked_reason`（不许静默卡住）" |
| `closed → in_progress` | ❌（终态不可重入，自检实测） | `agent_f.py:1286-1291` |
| `blocked → in_progress` | ✅（若卡点解除） | — |

**(c) `Subgoal.owner`**

`SUBGOAL_OWNERS = ("F","A","B","C","D","E","G")`（`schema.py:661`）。
**注意：`H` 不在其中** —— 审校者不能被派活给 F 的攻坚计划
（与"F 不能召唤 H"一致：`ALLOWED_EDGES["F"]` 里没有 H）。

### F.6 预算与终止条件（**FC-18 的落地核心**）

`tools/attack_tools.DEFAULT_BUDGET`（`attack_tools.py:63-68`）—— **四类键必须都在**：

| 键 | 默认值 | 维度 | 缺了会怎样（`attack_tools.py:103-105` 逐字） |
|---|---:|---|---|
| `max_rounds` | **6** | 生命周期总量 | "只有轮数上限则单轮可无限扇出" |
| `max_parallel_subgoals` | **2** | 单批规模 | 单轮可无限开子目标 |
| `max_persist_attempts` | **2** | 重试 | 落库可无限重试 |
| `max_depth` | **2** | 嵌套深度 | 可无限派生子计划 |

`check_budget` 的三态（`attack_tools.py:87-113`）：

| 输入 | `checked` | `complete` | `allowed` | `reason` |
|---|---|---|---|---|
| `budget=None` | **`False`** | `False` | **`None`** | "没有提供预算 ⇒ **没检查**。注意这与'预算用尽'是两件事" |
| 缺键 | `True` | `False` | `False` | 列出 `missing` |
| 完整 | `True` | `True` | `True` | 回显四类键 |

`can_round`（`attack_tools.py:116-149`）：`rounds_done >= mr` ⇒ `allowed=False, blocked_by="rounds"`；
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

### F.7 三态与失败模式

| 场景 | 三态形态 | 依据 |
|---|---|---|
| 预算没给 | `checked=False` / `allowed=None` / `blocked_by="not_checked"` | `attack_tools.py:87-94` |
| 预算不完整 | `checked=True` / `complete=False` / `allowed=False` / `blocked_by="incomplete"` | `attack_tools.py:95-106` |
| **`can_derive` 在 `checked is False` 时返回 `blocked_by="incomplete"`** | ❌ **已知折叠**：用"不完整"这个标签表示"没检查"，**正是模块 docstring 自己警告的那种折叠** | INVENTORY 4.5#12 |
| 子目标未接线 | `action="no_change"` / `outcome="no_change"` / detail 明说"未推进" | 自检实测 |
| 同一未接线子目标 | `in_flight` 过滤 ⇒ **不会被反复重选** | 自检实测 |
| 计划不存在 | `ok({"checked": False, "reason": "计划 … 不存在 ⇒ **没查**"})` —— 信息诚实但 `res.ok is True` | INVENTORY 4.3(c) |
| 数值实验想关子目标 | ❌ schema 抛 | 自检实测 |
| 只有数值证据却标 `closed` | ❌ schema 抛 | 自检实测 |

**F 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P1 字符串约定 | `TERMINAL_STATUSES` 与 `ATTACK_STATUSES` 不同步（`supported_not_proved` 缺席） | 本次实测（`attack_tools.py:75` vs `schema.py:654`） |
| P3 折叠 | `can_derive` 的 `blocked_by="incomplete"` 表示"没检查" | INVENTORY 4.5#12 |
| P10 降级缺失 | `_deploy_e` 曾没有降级路径 | `draft/13` §8.6 |
| P14 外部契约 | `attack.check_budget` 对"没给预算"给 `checked=False`，而 `AgentF.create_plan` 对**同一个输入**静默改用 `DEFAULT_BUDGET` —— 同一个输入在两层被当成两件事 | INVENTORY 6.4 |
| FC-07 副作用 | `attack.step` 经 `_deploy_e` 跑 E 的脚本子进程 | INVENTORY 4.4 |

### F.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| `for_question_id` 存在 | `dangling_question_ref` | error |
| `parent_plan_id` 存在 | `dangling_plan_ref` | error |
| `experiment_ids` 存在 | `dangling_experiment_ref` | error |
| `stalled` 必须写 `best_partial` | `stalled_without_partial` | error |
| `blocked` 子目标必须写 `blocked_reason` | schema `validate()` | `ValueError` |
| `history` 轮次单调不减 | `schema.AttackPlan.validate`（`schema.py:927`，据 `draft/13` §7 FC-18 行） | `ValueError` |
| 预算四类键齐全 | `attack.check_budget` + `schema.AttackPlan.budget`（`schema.py:869` 缺即抛） | `ValueError` |

### F.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、`D`（`:598`，I10 升级）、`G`（`:601`）。
- **F 能召唤谁**：`A B C D E`（`capabilities.py:600`）—— "攻坚需要一切"。
  **不能召唤 G/H。**
- **入参从哪来**：`attack_plans` 行（F 自己写）+ `capabilities.py:393-420` 的 4 个动作 schema。
- **产出被谁消费**：
  - `attack_plans` → **D**（`attack.status`）、**G**（写稿读攻坚结论）、**H**（核对 `stalled` 有没有谎报成 `resolved`）
  - `search_requests` / `reprocess_requests`（F 提交的）→ **A** / **B**
  - `experiments`（经 E）→ **G** / **H**

### F.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_f
```

**实测输出（末尾逐字）**：

```
[9] 工具 attack.*：['attack.check_budget', 'attack.create_plan', 'attack.list_plans', 'attack.pick_next_subgoal', 'attack.status', 'attack.step']
    [PASS] attack.status 可用且返回同一计划
    [PASS] attack.create_plan 可用
    [PASS] attack.list_plans 可用
========================================================================
SELF-CHECK DONE（agent_f）：失败 0 项
```

**退出码 0**。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| 三维预算的完整性检查与两个方向（提前停止 / 跑满） | `max_parallel_subgoals` 的实际并发约束 |
| `stalled` 的 `best_partial`、不可重入 | `max_persist_attempts` 的重试路径 |
| owner 分派（E 实验 / A 检索 / D no_change） | `F → C` 的召唤（边表有，自检没跑） |
| FC-22 两条硬约束（数值不许关子目标；只有数值证据不许标 `closed`） | `dangling_plan_ref` / 深度派生的 `deep` 路径 |
| 6 个 `attack.*` 工具的可用性 | `TERMINAL_STATUSES` 缺 `supported_not_proved` 的后果 |

---

## G —— 论文撰写

### G.1 一句话定位

**G 产出"稿件"，每条断言必须带引用**。
它回答：**"这些结论怎么写进一份可审的稿子里？哪些结论只能降级成 Remark？"**

### G.2 职责

| # | 职责 | 判据 |
|---|---|---|
| G-1 | 构造合规断言（**`cross_check` 自动补"不构成证明"**） | `doc.compose_claim`（`agent_g.py:161`）；`CROSS_CHECK_DISCLAIMER` |
| G-2 | 登记外部依赖（FC-23）：`closed` 时**先用真实数据核来源** | `doc.register_dependency`（`agent_g.py:193`） |
| G-3 | 写 `documents` 行并渲染 markdown | `doc.build_document`（`agent_g.py:229`） |
| G-4 | 渲染（不写库、不落盘） | `render`（`agent_g.py:263`） |
| G-5 | 按库里当前数据重画 markdown（**不改数据行，只改文件**） | `refresh_markdown`（`agent_g.py:278`） |
| G-6 | 按 H 的发现修订稿件 | `revise`（`agent_g.py:315`）；`review_rounds+1`、`status=revised` |

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

### G.4 工具面（32 个，实测）

`side_effect` 分布：`{'read': 17, 'write_local': 9, 'none': 6}`

| 组 | 工具 | `side_effect` | 审批 |
|---|---|---|---|
| `doc.*`（5） | `build_document` **write** / `compose_claim` none / `list_documents` read / `register_dependency` **write** / `scan_claim` none | — | `build_document` / `register_dependency` **需审批** |
| `verify.*`（6） | 同 F（含 `run_experiment` **write**） | — | `run_experiment` **需审批** |
| `attack.*` 只读侧（4） | `check_budget` `list_plans` `pick_next_subgoal` `status` | — | 否（**不能** `create_plan`/`step`） |
| `review.*` 只读侧（2） | `list_findings` `scan_document` | — | 否 |
| `fs.*`（7） | 4 读 3 写 | — | 写侧**需审批** |
| `table.*`（8） | 5 读 3 写 | — | 写侧**需审批** |

> **G 拿不到**：`graph.*` / `trace.*` / `research.*` / `search.*` / `ocr.*`。
> ⇒ G 想知道"图上是什么情况"必须 `G → D/F`（边表：`G → D E F`）。
>
> ⚠️ **G 能跑实验**（`verify.run_experiment` 在 G 的工具面里，`roles=("E","F","G")`）。
> 这是**刻意的**：`capabilities.py:422` 的注释说 G"**自己不改稿，只产出稿件与依赖**"，
> 但工具面里给了它跑实验的能力 —— 两者**不矛盾**（跑实验不是改稿），
> 但它使"G 能写 `experiments`"这件事成立（写集里没有 `experiments`，
> 因为写发生在 `verify.run_experiment` 里 —— **这是写集的一个已知近似**，见 §0.6 的注释约定）。

### G.5 状态机

**(a) `documents.status`**

`DOC_STATUSES = ("draft","in_review","revised","accepted","rejected","unresolved_review")`（`schema.py:665`）。

| 迁移 | 触发者 | 允许？ |
|---|---|---|
| `draft → in_review` | H 审校（`review.review_document`，写侧） | ✅ |
| `in_review → revised` | **G** 的 `revise()` | ✅ |
| `in_review → accepted` | H（仅在 `error_count == 0` **且** `dep_checked` 时） | ✅ |
| `in_review → unresolved_review` | H 到轮数上限 | ✅ |
| `accepted` → 任何 | — | ❌（`verify.accepted_with_open_error` 会抓"accepted 但有 open error"） |
| `revised → in_review` | H 复审 | ✅ |

**硬拦**（`review_tools.py:440/604`）：
`target_status = "accepted" if (scan["error_count"] == 0 and dep_checked) else "in_review"`。
**逐字注释**（`review_tools.py:432-434`）："不许在这个前提下判 accepted"。

**(b) `dependencies.status`**

`DEP_STATUSES = ("closed","dangling","external_unavailable")`（`schema.py:671`）。

| 迁移 | 允许？ | 约束 |
|---|---|---|
| `→ closed` | ✅ **仅当** `source_lit_id`/`source_experiment_id` 真实存在 | `doc.register_dependency` 真的去核 `literature`/`experiments` 表 |
| `→ dangling` | ✅ | **必须写 `status_reason`** |
| `→ external_unavailable` | ✅ | **必须写 `status_reason`**（"本项目拿不到来源"是已知边界，降为 warning） |
| `closed` 但指向文献不存在 | ❌ | `verify.dangling_dep`（error） |
| `closed` 但指向 `inconclusive` 实验 | ❌ | `verify.closed_dep_on_inconclusive_experiment`（error） |

**(c) `documents.claims` 的字段级状态**（不是行状态，是**断言**的状态）

| 字段 | 受控值 | 硬约束 |
|---|---|---|
| `evidence_kind` | `("proof","cross_check","heuristic")` | `cross_check` **必须**带 `disclaimer` |
| `is_negative` | `bool` | `True` 时**必须**给 `negation_kind`（自检实测："'未证明'与'已证否'必须分开"） |
| `citations` | `list[str]` | **非空**（"没有引用的断言不允许进入稿件"） |
| `claim_id` | 字符串 | 不许重复（G 侧检查） |
| `section` | 字符串 | 必填 |

### G.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 审校轮数 | `review_rounds` 上限（H 侧，`review_findings` 的 `verify_fixes` 轮数） | `review_tools.py:591-604` | `unresolved_review`（**并列出未解决项**） |
| 一次 `build_document` 的断言数 | 无显式上限（`maxItems` 未设） | `capabilities.py:447` 的 params | ⚠️ **无上限**（**未核实是否有间接约束**） |
| 依赖登记数 | 无显式上限 | `capabilities.py:435-439` | ⚠️ 无上限 |
| `out_path` | 必须是工作区内相对路径 | `doc.build_document` 的 `summary`："`out_path` 越界即拒绝" | 拒绝 |

> ⚠️ **G 的循环最少**：G 的动作里没有"重试/循环"（`capabilities.py:423-473`），
> 它的终止由**调用方**决定。这与 F（有三维预算）形成对比。

### G.7 三态与失败模式

| 场景 | 三态形态 | 依据 |
|---|---|---|
| `cross_check` 断言 | **自动**补 `CROSS_CHECK_DISCLAIMER`（"不构成证明"），**不靠人写** | `doc.compose_claim` 的 `summary` 逐字 |
| 无引用 | **构造时就抛错**（"不等写库"） | `doc.compose_claim` 的 `summary` |
| 否定未分类 | **构造时就抛错** | 同上 |
| 过度声称 | **构造时就抛错** | 同上 |
| 断言引用不存在的文献 | ❌ **已知缺陷**：`scan_claim` 只检查 `citations` 非空且非空白，**从不解析** `lit:`/`rel:`/`exp:` 是否真实存在 ⇒ `citations:["lit:9999"]` **会通过全部闸门，`documents` 行被写入、markdown 被渲染** | INVENTORY 4.3(a)② |
| 依赖 `closed` 但来源不存在 | ✅ **会被拦**（`register_dependency` 真去核表） | INVENTORY 4.3(a)② 的对比 |
| 文档状态更新失败 | **如实记录而不是假装成功** | `agent_h` 自检逐字："（状态未更新，**如实记录**而不是假装成功：`ValueError: documents.rows[2] 校验失败：claims[claim-9] 没有 citations`）" |

**G 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P4 检测到了却没消费 | `doc.build_document` 可落库不存在的引用 | INVENTORY 4.3(a)② |
| P7 两套判据 | `scan_claim` 与 `review.scan_document` 重复检查**且已漂移**（H 侧不检查非法 `evidence_kind` / `negation_kind` / "非否定断言带否定分类"；G 侧没有 `claim_id` 重复与 `dangling_dep`） | INVENTORY 4.5#10 |
| P9 文档漂移 | `review_tools.py` 模块 docstring 声称"判据只有一份…本模块**不另写一套检查**" | INVENTORY 4.5#10 |
| — | **`agent_g` 的自检块当前失败**（见 G.10） | 本次实测 |

### G.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 断言必须有引用 | `unsupported_claim` | error |
| 引用必须能解析（`rel:` / `lit:` / `exp:` / `eval:`） | `dangling_citation` | error |
| 未知引用种类 | `unknown_citation_kind` | warning |
| 不得引用被否关系 | `citation_to_retracted_relation` | error |
| 引用 `suspect` 关系 | `citation_to_suspect_relation` | warning |
| 不得过度声称（FC-22） | `overclaim` / `proof_claim_rests_on_weaker_evidence` | error |
| `proof` 断言的所有依赖必须闭合 | `proof_claim_with_unclosed_dependency` | error |
| 依赖悬空 | `dangling_dep`（`external_unavailable` 降为 warning） | error / warning |
| `closed` 依赖不得指向 `inconclusive` | `closed_dep_on_inconclusive_experiment` | error |
| 依赖的 `used_by` 指向的稿件存在 | `dangling_doc_ref`（经 review_findings）；**未核到直接的 `used_by` 检查** | ⚠️ 未核实 |
| 数组字段已声明 | `undeclared_array_field` | error |

### G.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）、**`H`**（`:602`，"审校发现问题 → 请 G 修订"）。
  **G 不能被 A/B/C/D/E/F 召唤。**
- **G 能召唤谁**：`D E F`（`capabilities.py:601`）—— "写稿时发现缺证据 → 回去要"。
- **入参从哪来**：`relations` / `experiments` / `analysis_reports`（别人的产出）；
  `capabilities.py:423-473` 的 6 个动作 schema。
- **产出被谁消费**：
  - `documents` 行 + `reports/*.md` → **H**（审校）、人
  - `dependencies` → **verify**（闭合检查）
  - `revise()` 消费 **H 的 `review_findings`**

### G.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_g
```

**实测输出（末尾逐字，本轮实测）**：

```
  File "D:\Incubator\agentflow\src\agentflow\schema.py", line 1692, in validate_table
    obj.validate()
  File "D:\Incubator\agentflow\src\agentflow\schema.py", line 810, in validate
    raise ValueError(
ValueError: evidence_kind='proof' 时必须给出 verifier_subject_key（检查器输出管的是哪个命题）。否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'

The above exception was the direct cause of the following exception:
  ...
  File "D:\Incubator\agentflow\src\agentflow\agent_g.py", line 487, in _selftest
    with st.tx("literature", "experiments", actor="seed", note="fixture") as tx:
ValueError: experiments.rows[0] 校验失败：evidence_kind='proof' 时必须给出 verifier_subject_key（检查器输出管的是哪个命题）。否则无法排除'把 A 命题的检查器输出贴到 B 命题的记录上'
========================================================================
[0] 临时工作区：C:\Users\ysc20\AppData\Local\Temp\dsh-...

**退出码 1**。
```

> ⚠️ **这是一个真实的既有缺陷（本次实测）**：
> `agent_g._selftest` 在 `agent_g.py:487` 的 fixture 里种了一条
> `evidence_kind="proof"` 的 `Experiment`，**没给 `verifier_subject_key`**，
> 而 `schema.py:810` 是**后加的硬约束**（FC-22 的三条机械保证之一）。
> ⇒ **G 的自检完全跑不起来**（在 `[0]` 就崩），**退出码 1**。
> 修法明确：给那条 fixture 补 `verifier_subject_key`（或改 `evidence_kind`）。
> **该文件不在本次授权修改范围内**（本次只写文档），故只记录。
>
> **注意**：全量测试套件曾 **567 / 835 / 957 passed** 逐轮增长
> （本文写作期间并行施工新增了大量用例），**与本缺陷不矛盾**——
> `_selftest` 在 `if __name__ == "__main__"` 里，**测试套件不执行它**。
> 这恰好是 `LESSONS.md` N10/N17 的又一例："测试全绿 ≠ 系统正确"，
> 以及"注释/自检块承诺的行为没有断言守住"。

| 覆盖了什么 | 没覆盖什么（即使修好 fixture 之后） |
|---|---|
| 6 个动作的主路径 | 引用存在性（**根本不做**，见 §G.7） |
| `cross_check` 自动免责声明 | `allowed_use` 降级规则（字段不存在） |
| `register_dependency` 的 `closed` 核验 | 断言数/依赖数的上限 |
| `revise()` 的轮次递增 | G↔H 的完整复审闭环（那在 H 的自检里） |

---

## H —— 审校（只读）

### H.1 一句话定位

**H 产出"发现"，且发现本身必须有证据**，并且**只读**。
它回答：**"这份稿件有没有不合格的地方？改过之后真的改好了吗？"**

**H 是唯一"能写，但只能写两样东西"的角色**：`review_findings`（自己的发现）
与 `documents.status`（只改状态，**改不了任何一句断言**）。
`capabilities.READ_ONLY_WRITE_EXCEPTIONS["H"]` 逐字登记了这个例外
（`capabilities.py:574-579`）。

### H.2 职责

| # | 职责 | 判据 |
|---|---|---|
| H-1 | 对一份稿件做全量机械审校 | `review.scan_document`（工具，`none`） |
| H-2 | 落发现 + 更新文档状态（**必须在被钉死的 `writers` 注册表里**） | `AgentH.review`（`agent_h.py:188`）；`review.review_document`（写侧） |
| H-3 | 复审：重跑检查判 `fixed` / 仍 `open`；到上限则 `unresolved_review` | `AgentH.verify_fixes`（`agent_h.py:220`）；`review.verify_fixes`（写侧） |
| H-4 | 只读列举发现 | `AgentH.list_findings`（`agent_h.py:240`） |
| H-5 | **依赖分级**（FC-13）：`external_unavailable`=warning，`dangling`=error | `review_tools.py:186`；自检实测逐字 |
| H-6 | 请 G 修订（**唯一能召唤的人**） | `H → G`（`capabilities.py:602`） |

### H.3 明确不负责

| 不做什么 | 为什么不由 H 做 | 该由谁做 |
|---|---|---|
| **改稿件的任何一句断言** | "若审校者能直接改稿，它就同时是'发现者'与'修正者'，于是**'发现问题'与'掩盖问题'在结构上无法区分**"（`tools/__init__.py:50-51` 逐字） | **G**（`revise`） |
| 写知识表 | H 的写集只有 `{review_findings, documents}` | **B** |
| 召唤除 G 以外的任何人 | "审校者若能让别人改数据，它就同时是发现者与修正者"（`capabilities.py:591` 逐字） | — |
| 决定一条发现要不要修 | H 只**报**；修与不修是 G/人的决定（`wontfix` 是**人**的判断） | **G** / 人 |
| 判数学对错 | H 的工具只有机械判据（引用/等级/否定/依赖闭合）；**数学正确性不在机械判据的射程内** | 形式化检查器 / 人 |
| 自己造证据 | 每条发现必须带 `evidence`；没有证据的发现是 error | `verify.finding_without_evidence`（error） |

### H.4 工具面（23 个，实测）

`side_effect` 分布：`{'read': 17, 'none': 6}` —— **0 个 `write_local`，0 个 `network`，0 个需审批**。

| 工具名 | summary | `side_effect` | 审批 | 参数 | 返回结构 | 测试 |
|---|---|---|---|---|---|---|
| `review.list_findings` | 只读列举审校发现 | `read` | 否 | doc_id, level, status | `{count,findings:[…]}` | `test_agent_h.py` |
| `review.scan_document` | 全量机械审校（每条发现带 `evidence`） | `none` | 否 | **doc**；dependencies | `{checked,doc_id,findings,error_count,warning_count,verdict,dep_check}` | `test_agent_h.py` |
| `doc.compose_claim` `doc.list_documents` `doc.scan_claim` | 断言只读侧 | `none`/`read`/`none` | 否 | 见 §R0 | 见 §R0 | `test_agent_g.py` |
| `verify.check_formal` `verify.code_hash` `verify.detect_verifier` `verify.evidence_for` `verify.list_experiments` | 证据只读侧（**无 `run_experiment`**） | read/none×4 | 否 | 见 §R0 | 见 §R0 | `test_agent_e.py` |
| `attack.check_budget` `attack.list_plans` `attack.pick_next_subgoal` `attack.status` | 攻坚只读侧 | none/read/none/read | 否 | 见 §R0 | 见 §R0 | `test_agent_f.py` |
| `fs.list` `fs.read` `fs.search` `fs.stat` | 工作区只读（**无 `fs.write`/`move`/`delete`**） | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 |
| `table.count` `table.get` `table.list` `table.schema` `table.search` | 表只读（**无 `table.create`/`update`/`delete`**） | `read` | 否 | 见 §R0 | 见 §R0 | 见 §R0 |

**第二道防线（`agent_h.py:78-111`）**：`AgentH.install_h_tools` 把 `build_registry`
的 H 子集复制进新注册表，并用 `filter_readonly_h_surface` 再做一次**显式拒绝 + 留痕**
（`refused_write_tools`）—— 是"声明错了也要拦下"。

**写侧**：`review.review_document` / `review.verify_fixes` 是 `write_local`，
**默认不注册**（`tools/review_tools.register(include_writers=True)` 才注册），
由 `AgentH` 的"落库代理"持有（`agent_h.py:163-165`）。

> **H 拿不到**：`graph.*` / `trace.*` / `research.*` / `search.*` / `ocr.*`、
> `verify.run_experiment`、`doc.build_document` / `doc.register_dependency`、
> `attack.create_plan` / `attack.step`、以及所有 `fs.*`/`table.*` 的写工具。

### H.5 状态机

**(a) `review_findings.status`**

`FINDING_STATUSES = ("open","fixed","wontfix","disputed")`（`schema.py:696`）。

| 迁移 | 触发 | 允许？ |
|---|---|---|
| `open → fixed` | `verify_fixes` 重跑检查，**发现消失** | ✅ |
| `open → open` | 重跑发现仍在（自检实测："未解决：✗ 0000 overclaim @claim-1 level=error"） | ✅（复发） |
| `open → disputed` | 人/G 明确不认同 | ✅（`disputed` 也算终结） |
| `open → wontfix` | 人决定不修 | ✅ |
| `fixed → open` | ❌（终态；实测"复审：error 一直不修 ⇒ 到轮数上限必须置 `unresolved_review`"） | `review_tools.py:591-604` |

**(b) `documents.status` 由 H 驱动**

见 §G.5(a)。**关键硬拦**：`accepted` 只在 `error_count == 0` **且** `dep_checked` 时才允许。

**(c) `verdict`（H 的返回，不是状态）**

`verdict ∈ {accepted, accepted_with_warnings, rejected, unverified, unresolved_review}`
（`review_tools.py:224/438-440/594-604`）。

| verdict | 判据 |
|---|---|
| `accepted` | `error_count == 0` **且** `dep_checked` |
| `accepted_with_warnings` | 无 error，有 warning |
| `rejected` | 有 error |
| `unverified` | **依赖闭合没查**（`dep_checked=False`） |
| `unresolved_review` | 到轮数上限仍有 open error |
| ⚠️ **`review.scan_document`（工具）不看 `dep_check.checked`** | INVENTORY 4.3(a)①：`verdict = "rejected" if errors else ("accepted_with_warnings" if warnings else "accepted")`（`review_tools.py:224`）**完全没读 `dep_check["checked"]`** ⇒ 同一个返回值里 `dep_check` 说"没查"、`verdict` 说"通过" |

### H.6 预算与终止条件

| 循环/上限 | 值 | 出处 | 用尽时 |
|---|---|---|---|
| 审校轮数 | `review_rounds` 上限 | `review_tools.py:591-604` | `unresolved_review` + **列出未解决项**（自检实测："`verdict=unresolved_review resolved=0 still_open=4 未解决(error)=3`"） |
| 同稿重复审 | **去重**（同一发现不重复落行） | 自检实测："去重：同一份坏稿件再审一次 ⇒ 新增=0 重复跳过=4 finding 行数 5 → 5" | — |
| 每条发现的信息量 | 必须带 `evidence`（含**实际值**） | 自检实测逐字："`unsupported_claim` 的 evidence（必须含实际值）：'`claim_id=claim-9` 的 `citations=[]`（空）'" | `verify.finding_without_evidence`（error） |

> ⚠️ **`review_rounds` 的具体上限值**：本次**未在代码中核到显式常量**
> （`review_tools.py:591-604` 是"到轮数上限时"的分支，上限来自调用方传入的 `round_no`
> 与稿件行的 `review_rounds`）。**标 `（未核实具体数值）`**。

### H.7 三态与失败模式

| 场景 | 三态形态（自检逐字） |
|---|---|
| **明确传 `dependencies=None`** | `dep_check.checked=False` / `verdict=unverified` / reason 逐字"依赖闭合**没查**（调用方未提供 `dependencies` ⇒ **没查依赖闭合**（不得读成'依赖都闭合'））⇒ 不能判 `accepted`" |
| 未解决发现 | `verdict=unresolved_review` + `unresolved_findings` 列表 |
| 修好后复审 | 逐字"修好后 → 复审 `verdict=accepted resolved=1 still_open=0` 库中状态=`accepted`" |
| **依赖分级** | 逐字"依赖分级（FC-13）：`external_unavailable`=warning（应为 warning）、`dangling`=error（应为 error）" |
| **文档状态更新失败** | 逐字"状态未更新，**如实记录**而不是假装成功" |
| `review.scan_document` 的 `dep_check` 与 `verdict` 矛盾 | ❌ **已知缺陷**（INVENTORY 4.3(a)①） |

**H 已知会犯的错**：

| 模式 | 实例 | 出处 |
|---|---|---|
| P3 折叠（**最严重**） | `review.scan_document` 给出 `verdict="accepted"` 而依赖闭合**从未检查** | INVENTORY 4.3(a)①；`review_tools.py:224` vs `:171-176` |
| P7 两套判据 | `scan_document` 把 `scan_claim` 的 4 组检查逐条复制且**已漂移** | INVENTORY 4.5#10 |
| P9 文档漂移 | 模块 docstring 声称"本模块**不另写一套检查**" | INVENTORY 4.5#10 |
| **修复过头**（P16 的反例） | 修好后**没有借机放宽断言**，而是把附录标题改成明确写"未达正文标准、不作为证据"，并把断言换成段落级解析 ⇒ **测试反而更强** | `LESSONS.md` P11；`draft/11` §11.3 |

### H.8 不变式

| 不变式 | 检查项名 | 级别 |
|---|---|---|
| 发现指向的稿件存在 | `dangling_doc_ref` | error |
| 发现必须带证据 | `finding_without_evidence` | error |
| `accepted` 稿件不得有 open error | `accepted_with_open_error` | error |
| `proof` 断言的依赖闭合（H 是复核方） | `proof_claim_with_unclosed_dependency` | error |
| 证据等级不得过度声称 | `overclaim` / `proof_claim_rests_on_weaker_evidence` | error |
| **H 的工具面 0 个写工具** | `filter_readonly_h_surface` 留痕 + `for_role` 结构性剥离 | 实测 0 |
| **H 只能召唤 G** | `ALLOWED_EDGES["H"] == {"G"}` | 静态表 |

### H.9 接口

- **能被谁召唤**：`M`（`capabilities.py:594`）。**只有 M**
  —— `D`/`E`/`F`/`G` 都不能召唤 H（这一点很重要：**产出者不能指挥审校者**）。
- **H 能召唤谁**：**只有 `G`**（`capabilities.py:602`）。
- **入参从哪来**：`documents` 行 + `dependencies`（**必须由调用方显式提供**，
  不提供就 `checked=False`）；`capabilities.py:475-495` 的 3 个动作 schema。
- **产出被谁消费**：
  - `review_findings` → **G**（`revise` 按 `fixed_findings` 修改）、人
  - `documents.status` → **G**（`revise` 前要读到 `in_review`）、**verify**

### H.10 自检入口

```powershell
$env:PYTHONPATH='src'; python -m agentflow.agent_h
```

**实测输出（末尾逐字）**：

```
[9] 三态：显式 dependencies=None ⇒ 依赖闭合**没查**，不许判 accepted
    dep_check.checked=False verdict=unverified status=accepted
    reason=机械检查发现 error=0、warning=0、info=0；依赖闭合**没查**（…）⇒ 不能判 accepted；…
========================================================================
SELF-CHECK DONE（agent_h）
```

**退出码 0**；自检共 9 个编号步骤。

| 覆盖了什么 | 没覆盖什么 |
|---|---|
| 三类负控（无引用 / 否定未分类 / 依赖悬空） | 数学正确性（**不在射程内**） |
| 落库级负控（"坏稿件（绕过 schema 直接改盘）"） | `review.scan_document` 的 `dep_check`/`verdict` 矛盾（**自检没查这个 contradiction**） |
| 复审闭环（不修 → `unresolved_review`；修好 → `accepted`） | 真实规模稿件的性能 |
| 发现去重（再审一次新增=0） | `disputed` / `wontfix` 两条迁移 |
| 三态（`dependencies=None` ⇒ `checked=False` ⇒ 不判 accepted） | 轮数上限的具体数值（无显式常量） |
| 依赖分级（FC-13 两档） | — |

---

## M —— 主控（Conductor）

> **M 的"工具面"就是"召唤能力"**。M 没有任何领域动作
> （`CAPABILITIES["M"] == ()`，`capabilities.py:501`），它的产出只有两类：
> **(a) 召唤**、**(b) 给用户的汇总**（`DESIGN-CONDUCTOR.md:37` 逐字）。

### M.1 一句话定位

**用户唯一面对的东西**。它回答：**"为了这个目标，该召唤谁、按什么顺序、花多少预算、被拦住时说什么？"**

**M 不是一个额外的"智能层"**：它**不做 LLM 推理**（`conductor.py:10-11` 逐字：
"本模块里**没有**任何 LLM 调用 —— 真 LLM 主控由 `SubagentBackend` 承担（本轮显式未接线）"）。
它**确定性地执行调用方给的 plan**。这让 M 可测试：M 的"正确性" =
它发出的召唤序列是否满足策略与预算，而不是"它聪不聪明"。

### M.2 职责

| # | 职责 | 判据（实现位置） |
|---|---|---|
| M-1 | **唯一的召唤入口**：`summon(role, action, params, by, parent_task_id, input_key, budget, token, lineage)` | `conductor.py:465-624` |
| M-2 | 过策略：角色/动作存在性、边、深度、扇出、循环、并发、总量、预算、墙钟 | `policy.check_action` / `policy.check`（`policy.py:167/218`） |
| M-3 | 写台账（**每个 start 恰好一个 end**） | `Conductor._write_row` / `finish`（`conductor.py:379/711`） |
| M-4 | 派给 backend（`LocalBackend` / `SubagentBackend`） | `conductor.py:123/212` |
| M-5 | **拒绝也落台账**（`status="done", outcome="refused"`） | `Conductor._refuse`（`conductor.py:411-462`） |
| M-6 | 波浪调度（写集不相交的并发） | `Conductor.run_plan` → `scheduler.run_waves`（`conductor.py:788`） |
| M-7 | 协作式取消（一个共享 signal 覆盖在飞与待启动） | `Conductor.cancel` / `dispose`（`conductor.py:818/841`） |
| M-8 | 幂等销毁，合成 `cancelled` 的 end | 同上 |
| M-9 | 台账的可读视图与统计 | `Conductor.tree` / `stats`（`conductor.py:878/922`） |
| M-10 | **自己的不变式自检** | `Conductor.verify_tasks`（`conductor.py:966-1014`） |
| M-11 | 汇总给用户 | 调用方消费 `stats()` / `tree()` / `SummonResult`（**M 本身不产出报告文件**） |

### M.3 明确不负责

| 不做什么 | 为什么不由 M 做 | 该由谁做 |
|---|---|---|
| 产出知识（概念/关系/文献） | "它不产出知识、不写关系、不改稿件"（`DESIGN-CONDUCTOR.md:37`）；`WRITE_SETS["M"] = frozenset()` | **A** / **B** |
| 写任何领域表 | 同上；M 只写 `tasks`（`CONDUCTOR_WRITE_SET`，`capabilities.py:562`） | 各角色 |
| 有领域动作 | `CAPABILITIES["M"] == ()` —— **可断言的事实**，不是一个约定 | 各角色 |
| 用 LLM 决定"想做什么" | 本轮 M 是**确定性策略执行者**；plan 由调用方给 | `SubagentBackend`（**未接线**） |
| 成为"谁能召唤谁"的特权路径 | M 也在角色空间里（`schema.CONDUCTOR_ROLE`）："特例化会是权限模型最容易漏的地方"（`DESIGN-CONDUCTOR.md:40`） | — |
| 被召唤 | `NON_SUMMONABLE = {"M"}`："**没人能召唤主控**"（没有"召唤 M"这件事） | — |
| 自动重试被取消的任务 | FC-20 第 4 条："取消后不自动重试，并把结果记成**unknown outcome**" | — |

### M.4 "工具面"= 召唤能力

#### M.4.1 M 能召唤的 8 个角色 × 它们的动作（48 个可召唤动作）

| 角色 | 可召唤动作数 | 动作名 |
|---|---:|---|
| A | 2 | `run_once` `run` |
| B | 6 | `run_once` `reprocess_once` `run_reprocess` `decide_structural_duplicate` `resolve_structural_duplicate` `run` |
| C | 9 | `hottest` `paths` `cold` `gaps` `neighbors` `relations_between` `contradictions` `structural_duplicates` `handle` |
| D | 13 | `probe_c` `ingest` `ingest_detailed` `trace_question` `trace_l3` `assess` `submit_gaps` `consider` `poll` `adjudicate` `research` `run_round` `write_report` |
| E | 5 | `run_experiment` `check_formal` `evidence_for` `list_experiments` `run_script_experiment` |
| F | 4 | `create_plan` `step` `status` `list_plans` |
| G | 6 | `compose_claim` `register_dependency` `build_document` `render` `refresh_markdown` `revise` |
| H | 3 | `review` `verify_fixes` `list_findings` |

每个动作的 `params`（JSON Schema 子集）、`returns`、`side_effect`、`handler_name`
在 `capabilities.py:151-501`；**装配期由 `assert_capabilities()` 用 `importlib`
把每个 `handler_name` 逐个 `callable(getattr(cls, name))` 核过**
（编造动作名会让模块**根本 import 不进来**）。

#### M.4.2 M 的"召唤面"要过的 9 道策略判定（按 `summon` 里的顺序）

| 序 | 判定 | 失败时 | 依据 |
|---:|---|---|---|
| 0 | `token.cancelled` / `_disposed` | `status=cancelled`, `outcome=cancelled`, **`task_id=None`，不产生新任务** | `conductor.py:490-512` |
| 1 | `check_action`（角色存在？动作存在？） | `refused/unknown_role` 或 `refused/unknown_action` | `policy.py:167-191` |
| 2 | 参数 schema | `refused/unknown_action`（"这次没这么调"） | `conductor.py:522-531` |
| 3 | 深度链（从台账重建） | `refused/unknown_action` + detail | `conductor.py:533-540` |
| 4 | `check`：**边 / 不可召唤 / 深度 / 循环 / 扇出 / 并发 / 总量 / token 预算 / 花销预算 / 墙钟** | 见下表 | `policy.py:218-326` |
| 5 | 写 `running` 行（带 `started_at`） | — | `conductor.py:580-595` |
| 6 | 执行（**事务只包台账那行，不包 handler**） | 异常 ⇒ `status=failed` | `conductor.py:597-613` |
| 7 | 记账（用**本次 finish 实际写下的** tokens/usd） | — | `conductor.py:614-624` |

`Refusal.reason` 的受控词表 `REFUSAL_REASONS`（`schema.py:1246-1257`，10 个）：

| reason | 触发 |
|---|---|
| `unknown_role` | 角色不在 `schema.ROLES` 里 |
| `unknown_action` | 该角色没有这个动作 / 参数不合法 / 父任务不存在 |
| `forbidden_edge` | 策略不允许这条边（如 `C → B`）；或目标是 `NON_SUMMONABLE` |
| `depth_exceeded` | `depth > max_depth` |
| `fanout_exceeded` | 该任务已派生 `max_fanout` 个子召唤 |
| `concurrency_exceeded` | `running >= max_concurrency` |
| `budget_exceeded` | token / 花销预算耗尽 |
| `deadline_exceeded` | 墙钟到点（**并同时协作式取消在跑的**） |
| `cycle_detected` | `(role, action, input_key)` 已在祖先链上 |
| `not_wired` | 该角色该动作未接线（`SubagentBackend` 恒为此） |

#### M.4.3 并发判据：写集相交 ⇒ 串行

- `policy.waves_of(calls, limit=…)`（`policy.py:355`）：同一波内**写集互不相交**；
  `limit` 是单波容量（= `max_concurrency`），**"波内并发数 ≤ max_concurrency"由划分保证，
  不需要信号量兜底**。
- 为什么用写集而不是依赖图（`DESIGN-CONDUCTOR.md:226-228` 逐字）：
  "依赖图需要每个动作声明前置，那会逼所有角色改签名；而写集是**从角色推出来的**（`WRITE_SETS`），
  零成本、可判定、可测。代价是它比真依赖图保守（可能少并发），但**保守的代价是多花时间，
  激进的代价是数据被改坏**。"
- **未知角色返回"整张表"而不是空集**（`capabilities.write_set_of`，`capabilities.py:626-640`）：
  "空集意味着'它什么都不写，可以和任何人并发'，**那是最危险的方向**。"

### M.5 状态机（`tasks` 表）

**(a) `status`**

`TASK_STATUSES = ("pending","running","done","cancelled","failed")`（`schema.py:1229`）。

| 从 → 到 | 允许？ | 谁拦 | 出处 |
|---|---|---|---|
| `pending → running` | ✅（写 `started_at`） | — | — |
| `running → done` | ✅（**必须给 `outcome` 与 `detail`**） | `schema.Task.validate` | `schema.py:1338-1344` |
| `running → failed` | ✅（**必须写 `error`**，且 `outcome` 必须 `"failed"`） | 同上 | `schema.py:1358-1361` |
| `running → cancelled` | ✅（`outcome ∈ {cancelled, refused}`） | 同上 | `schema.py:1362-1366` |
| `done/cancelled/failed → 任何` | ❌ **终态先到先得** | `finish` 重读磁盘后**什么都不做**（幂等）；`schema` 的 "pending/running 却已有 `ended_at` ⇒ 拒" 从数据层再兜一次 | `conductor.py:749-761`；`schema.py:1329-1333` |
| `running` 但无 `started_at` | ❌ | `schema.py:1327-1328` | — |
| `done` 但无 `outcome` | ❌ | `schema.py:1338-1342`（"'跑完了'与'跑完了有没有结果'是两件事"） | — |
| `done` 但 `detail` 为空 | ❌ | `schema.py:1343-1344` | — |
| `outcome="refused"` 但 `status != "done"` | ❌ | `schema.py:1345-1350`（"**拒绝是一次成功执行**"） | — |
| `outcome="refused"` 但 `refusal_reason` 不在词表 | ❌ | `schema.py:1351-1355` | — |
| `refusal_reason` 非空但 `outcome != "refused"` | ❌ | `schema.py:1356-1357` | — |
| `parent_task_id` 指向自身 | ❌ | `schema.py:1370-1371` | — |
| `parent_task_id` 不存在 | ❌ | `verify.dangling_parent_task`（error） | `verify.py:662` |
| 子 `depth ≠ 父 depth + 1` | ❌ | `verify.task_depth_discontinuous`（error）；`_depth_of` 也抛 | `verify.py:668`；`conductor.py:362-376` |
| `depth < 1` | ❌ | `schema.py:1321-1322` | — |
| 无父但 `depth ≠ 1` | ❌ | `Conductor.verify_tasks`（`conductor.py:1004-1006`） | — |
| `artifacts` 含空元素 | ❌ | `schema.py:1372-1374` | — |
| `artifacts` 指向不存在的行 | ❌ | `verify.dangling_task_artifact`（error） | `verify.py:694` |

**(b) `outcome`**

`TASK_OUTCOMES = ("ok","no_result","not_applicable","refused","failed","cancelled")`（`schema.py:1243`）。

**六种组合的语义**（`conductor.py:72-76` 的表）：

| `status` | `outcome` | 含义 |
|---|---|---|
| `done` | `ok` / `no_result` / `not_applicable` / `refused` | 跑完了（可能"确实没有"，也可能"框架拒绝了"） |
| `failed` | `failed` | 执行中异常 |
| `cancelled` | `cancelled` / `refused` | 没跑完（被取消 / 因超预算被拒） |

**`SummonResult.ok` 的判据只有一处**（`conductor.py:109-117` 逐字）：
`status=="done" and outcome=="ok"`。
"为什么 `refused` 不算 ok（它在 status 层是 done）：调用方问 `res.ok` 时想知道的
几乎总是'东西做出来了吗'，而不是'框架运转正常吗'。把 refusal 算成 ok 会让
'越权被拦住'在调用方看来像一次成功交付。"

**(c) handler 返回值 → 终态的映射**（`conductor.py:644-686`）

| handler 返回 | `status` | `outcome` |
|---|---|---|
| `None` | `done` | **`no_result`**（"**跑完了，确实没有**"） |
| `Mapping` 带 `status`/`outcome` | 取它（只认终态词表，中间态一律归 `done`） | 取它 |
| `Mapping` 带 `status="done"` 但没 `outcome` | `done` | `ok`，**并把"handler 未声明 outcome"写进 detail**（不许悄悄当 ok） |
| 其它任何值 | `done` | `ok` |

> ⚠️ **`None` 不许映射成 `ok`**（`conductor.py:653-655` 逐字）：
> "那正是'把『没做』与『做了没结果』折叠成同一个值'—— 本项目在引文校验、OCR、
> D 溯源、C 预算截断四处踩过它，每一次的后果都是下游把'我们没查'读成了'查了没有'。"

### M.6 预算与终止条件（`policy.Policy`，`policy.py:38-60`）

| 键 | 默认 | 维度 | 缺了会怎样（`policy.py:13-16` 逐字） |
|---|---:|---|---|
| `max_depth` | **3** | 深度 | "链可以**无限深**（每次只派生 1 个，但派生 10000 层）" |
| `max_fanout` | **5** | 单点扇出 | "每一层都能**无限宽**（深度 3，每层 9999 个）" |
| `max_concurrency` | **4** | 瞬时并发 | "扇出可以**无限持续**：每秒 4 个，跑一天" |
| `max_tasks_per_run` | **200** | 生命周期总量 | "**瞬时**把并发打爆：总量对了，但 200 个任务同时开跑" |
| `wall_clock_sec` | **900.0** | 墙钟（FC-20） | `None` = 不限 |
| `token_budget` | `None` | token（FC-19） | `None` = 不限 |
| `usd_budget` | `None` | 花销 | `None` = 不限 |

**四类上限必须同时存在**（FC-18）：`Policy.validate()` 要求四个都是正数
（`policy.py:67-87`），且 `run_plan` 启动时调 `assert_policy_complete(policy)`
（`condudctor.py:797`；`policy.py:392`）—— **缺任一类即 fail-closed**。

**上限用尽时的行为**：

| 用尽 | 行为 |
|---|---|
| `max_depth` | 新召唤 `refused/depth_exceeded` |
| `max_fanout` | 新召唤 `refused/fanout_exceeded` |
| `max_concurrency` | 新召唤 `refused/concurrency_exceeded` |
| `max_tasks_per_run` | 新召唤 `refused/...`（`total = _started_total + _cancelled_total`） |
| `wall_clock_sec` | 新召唤 `refused/deadline_exceeded`，**并 `_signal_stop("deadline", …)` 协作式取消在跑的** |
| `token_budget` / `usd_budget` | `refused/budget_exceeded` |
| `dispose()` | **合成 `cancelled` 的 end**（`detail` 写"结果未知"），**不自动重试** |

> ⚠️ **一个易被绕过的细节**（`conductor.py:305-309` 逐字）：
> **被取消而没有落台账的召唤数必须计入总量** —— "否则'取消了就不限次'会成为绕过
> `max_tasks_per_run` 的路径（取消一次不算数 ⇒ 取消一百万次也不算数）"。
> 它与 `_started_total` **分开记**。

### M.7 三态与失败模式

**`conductor.py:36-42` 的三态表（逐字）**：

| 场景 | 禁止 | 本模块的做法 |
|---|---|---|
| 角色没有这个动作 | 只写一句人话 | `refusal_reason="unknown_action"` |
| 动作没接线 | 抛异常 / 返回空 | `refusal_reason="not_wired"`（`backend=subagent` 亦然） |
| handler 返回 `None` | 当成 `ok` | `outcome="no_result"` |
| 查询没法做 | `checked=True, empty=True` | 原样透传 `checked=False` + `reason` |
| 被 dispose 砍掉 | 记成 `failed` | `status=cancelled` + detail 写"结果未知" |

**`SummonResult.checked` 的三态**（`conductor.py:102-104`）：
`None` = 这个动作不适用"查"这个概念（例如"写一行 documents"）；
`False` = **没法查**（`payload` 里必须有 reason）；
`True` = 查了。

**M 已知会犯/需要防的错**：

| 模式 | 防御 |
|---|---|
| 僵尸 `running`（有 start 没 end） | `summon` 的 `except Exception` **必须兜住一切**（`conductor.py:608` 逐字："这里**必须**兜住一切，否则僵尸 running"）+ `dispose()` 合成 end + `verify.task_still_running`（warning） |
| 取号撞车导致静默覆盖 | `_alloc_task_id` **取号 + 建行在同一事务与同一把锁内**（`conductor.py:391-408`），判据只有一处（`interactions.next_prefixed_id`） |
| `finish` 被重复调用累加 tokens | 用**本次 finish 实际写下的**值，而不是回读整行（`conductor.py:614-619`） |
| 事务包住 handler ⇒ 死锁 | "事务**只包台账那一行**，绝不包 handler"（`conductor.py:576-579`）：(a) handler 可能跑几分钟；(b) handler 内部自己会 `store.tx(...)` |
| 静默丢弃多余参数 | `LocalBackend.call` **参数名对不上就拒绝**（`conductor.py:202-208`）："静默丢弃会让'我传了但它没看'看起来像成功 —— 于是 `gaps()` 报告里说'已提交'，而请求一条也没有" |
| 未知 backend 拼错被当成"大概无所谓" | `Conductor.__init__` **fail-closed**（`conductor.py:276-281`） |
| `LocalBackend` 猜依赖 | 只接受 `("factory", fn)` / `("object", obj)`；`("class", cls)` **明确拒绝**（`conductor.py:150-164`） |
| `SubagentBackend` 假装跑通 | **明确 `refused/not_wired`**（`conductor.py:215-226` 逐字列出两条诚实的路并选后者） |

### M.8 不变式（I-1…I-10，都有实现或测试）

`DESIGN-CONDUCTOR.md:254-265` 的 10 条 + 实现位置：

| # | 不变式 | 判据 | 实现/检查位置 | 状态 |
|---|---|---|---|---|
| I-1 | 每个 `started_at` 有且仅有一个 `ended_at` | 终态行 `ended_at` 非空；`running` 行 `ended_at` 为空 | `schema.py:1329-1335` + `verify.task_still_running` + `_selftest` | **已落地**（双道） |
| I-2 | 终态不可改写 | 对已结束任务再调 `finish` ⇒ **零变更** | `conductor.py:749-761`（重读磁盘 + 什么都不做） | **已落地** |
| I-3 | 深度单调不减 | 子 `depth` ≡ 父 `depth + 1` | `conductor.py:362-376` + `verify.task_depth_discontinuous` | **已落地**（双道） |
| I-4 | 拒绝必须带受控理由 | `outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS` | `schema.py:1351-1355` + `Conductor.verify_tasks` | **已落地** |
| I-5 | 并发度不超上限 | 峰值同时 `running` ≤ `max_concurrency` | `policy.check` + `Conductor.peak_running`（`stats()` 暴露） | **已落地**（`peak_running` 是**可打印的事实**） |
| I-6 | 写集相交不并发 | 任一波浪内不存在两个任务写集相交 | `policy.waves_of` + `scheduler` | **已落地** |
| I-7 | 预算耗尽后不再新开任务 | ⇒ `refused/budget_exceeded` | `policy.check` | **已落地** |
| I-8 | 取消是协作式且不自动重试 | 取消后不产生新任务；被取消任务 `outcome="cancelled"` | `conductor.py:490-512` + `dispose` | **已落地** |
| I-9 | 台账可重建 | `rebuild()` 后 `tasks` 表逐字节一致 | `Store.rebuild`（`store.py:404`）+ `tests/test_rebuild.py`（3 例） | ⚠️ **`test_rebuild.py` 是否覆盖 `tasks` 表：未核实** |
| I-10 | 结果合并顺序确定 | 同一 plan 跑两次，`SummonResult` 列表顺序相同 | `scheduler.run_waves`（按 plan 输入顺序合并） | **已落地**（`run_plan` docstring 逐字承诺"长度恒等于 `len(plan)` 且顺序与 plan 一致"） |

**另外**：`verify.py` 对 `tasks` 表的独立检查
（`dangling_parent_task` / `task_depth_discontinuous` / `task_without_input_key` /
`task_still_running` / `dangling_task_artifact` / `unknown_artifact_kind`）
与 `Conductor.verify_tasks`（`conductor.py:966-1014`）**判据一致但实现两份**
（`conductor.py:969-972` 逐字承认这一点并给出理由："`verify_all` 是**全库**审计、
由 CLI 跑；而'我刚跑完一次 run，台账是否自洽'是**即时**问题"）。
⇒ ⚠️ **这是"两套判据"的一个受控例外，但仍是 FC-11 的风险面**（两处会漂移）。

### M.9 接口

- **能被谁召唤**：**没人**（`NON_SUMMONABLE = {"M"}`，`capabilities.py:608`；
  `policy.check` 在 `d.to in NON_SUMMONABLE` 时返回 `forbidden_edge`，`policy.py:229`）。
- **M 能召唤谁**：`A B C D E F G H`（全部 8 个，`capabilities.py:594`）。
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

M **没有 `python -m agentflow.conductor` 自检块**（本次核对：`conductor.py` 无
`if __name__ == "__main__"`；`agentflow` 下只有 `agent_c/d/e/f/g/h` + `pipeline` + `llm`
有自检块）。

M 的自检入口是**两个方法 + 测试文件**：

| 入口 | 覆盖了什么 | 没覆盖什么 |
|---|---|---|
| `Conductor.verify_tasks()`（`conductor.py:966`） | I-1 / I-3 / I-4 + `artifacts` 表名与存在性 | I-2（幂等）/ I-5（并发峰值）/ I-6（写集）/ I-7 / I-8 / I-10 |
| `Conductor.stats()`（`conductor.py:922`） | `by_role`/`by_status`/`by_outcome`/`by_depth`/`refusal_reasons`/`unknown_outcome`/`peak_running`/`started_total`/`budget`/`policy`/`disposed`/`deadline_hit` | 被 call 的**参数**（`_call_log` 只在 `log_calls=True` 时记） |
| `tests/test_fc05_contract.py`（**22 例**，含 5 例 M 相关） | `test_clean_task_row_has_no_errors` / `test_task_depth_must_be_parent_plus_one` / `test_dangling_parent_task_is_an_error` / `test_dangling_task_artifact_is_an_error` / `test_running_task_is_reported_as_a_start_without_end` / `test_task_without_input_key_is_reported` | — |
| `tests/test_fc05_contract.py` 的 usage/eval 部分 | `usage_zero_value_needs_a_note` / `usage_total_must_cover_components` / `usage_task_total_mismatch_is_reported` / `dangling_usage_task` / `eval_requires_every_scope_field` / `eval_value_must_be_a_ratio` / `eval_duplicate_conflicting` / `same_value_duplicate_eval_is_clean` / `document_can_cite_an_eval_result` | — |

> ⚠️ **M 缺一个"命令行的自检入口"**。这是 `DEVELOPMENT.md` §8 要补的一项：
> `python -m agentflow.conductor`（或 `cli conductor-selftest`）应当能跑
> I-1…I-10 十条不变式的正反两向，并以退出码表达结果。
> 现状：**没有**（退出码无从谈起）。

---

## 附录 S1：本文的"未核实"清单（按硬性要求，逐条列出）

| # | 未核实项 | 我查了什么 | 缺什么 |
|---:|---|---|---|
| 1 | `INVENTORY.md` 的"7 个零测试工具"在 `agentflow` 里是否仍成立 | 读了 INVENTORY §4.1 的方法（"在 `tests/**/*.py` 里搜索工具名字符串"） | **没有在 `agentflow/tests/` 上复算这 7 个名字** |
| 2 | `agent_d.py:2306` 处 D 到底改了 `relations` 的什么字段 | 读了 `capabilities.py:524-527` 的注释（"agent_d.py:2306 research_questions+relations"） | 没逐行读那段代码 |
| 3 | `review.scan_document` 的手工复现 | INVENTORY §6.2 明确说"**我没有运行任何工具代码**"，并建议"后续审计第一件事就是写这两个复现用例" | 本次**也没有跑**这两个工具 |
| 4 | `max_questions` 超出时是否留痕 | 读了 `agent_d.py:753` | 没读 ingest 的截断分支 |
| 5 | `max_l3_lits` / `max_l2_context` 截断是否留痕 | 读了 `agent_d.py:757/761` | 没读对应的截断分支 |
| 6 | `review_rounds` 的具体上限数值 | 读了 `review_tools.py:591-604` 的分支 | 没找到显式常量；上限来自调用方 |
| 7 | `test_rebuild.py` 是否覆盖 `tasks` 表（I-9） | 读了 `DESIGN-CONDUCTOR.md:264` 声称"`rebuild()` 后 `tasks` 表逐字节一致" | 没读 `tests/test_rebuild.py` 的 3 个用例体 |
| 8 | `doc.build_document` / `doc.register_dependency` 的断言数/依赖数是否有间接上限 | 读了 `capabilities.py:435-447` 的 params（无 `maxItems`） | 没读 `doc_tools.py` 的 handler 体 |
| 9 | G 的 `dependencies.used_by` 是否有直接的 verify 检查 | 读了 `verify.py` 的 71 个 code 列表 | 只看到 `dangling_doc_ref`（经 `review_findings`），没看到 `used_by` 的检查 |
| 10 | `G → D/E/F` 的实际召唤是否有代码路径 | 读了边表（`capabilities.py:601`） | 没 grep `Conductor.summon("D", …)` 之类的调用点 |
| 11 | `LocalBackend.registry` 在真实运行里怎么接 | 读了 `conductor.py:123-209` | 没找到任何生产调用方（**这可能意味着 M 目前只有测试驱动**） |
| 12 | `usage_ledger` 表是否有任何写入方 | grep 了 `agent_*.py` | 只见到 schema/verify，没见到写入调用（**结论可能是"无写入方"**） |
| 13 | `subagent` backend 接上 DSH 后的行为 | 读了 `SubagentBackend`（恒 `not_wired`） | 无 API key / 无 harness 权限面，**无法实测** |
| 14 | `method="formal"` 的真实后端路径 | 读了 `verify_tools.py` 的 `fail(kind="not_implemented")` | 本机无 Lean/Coq/Isabelle，**无法实测** |
| 15 | 真实联网端到端 | 读了 `test_providers_online.py`（8 例，默认 deselect） | 本次**未跑 `-m network`** |
| 16 | 本机是否有 `easyocr`/`pytesseract`/`fitz` | 读了 INVENTORY §6.2 的"未探测"声明 | **本次也未探测** |

## 附录 S2：本文发现的**既有问题**（带证据）

| # | 问题 | 证据（命令 + 输出 / 文件:行号） | 严重性 |
|---:|---|---|---|
| 1 | **`cli tools --role E` 被 argparse 拒绝** | 实测：`usage: agentflow tools [-h] [--role {A,B,C,D}]` → `error: argument --role: invalid choice: 'E'`，**退出码 2**。位置：`cli.py:460` 的 `choices=["A","B","C","D"]` | **高**（"角色即权限面"的**可打印事实**只覆盖 A–D，而 `cmd_tools` 的注释本身写着"角色清单必须来自 `ROLES`，**不许在这里写死**"） |
| 2 | **`agent_g` 的自检块完全跑不起来** | 实测：`python -m agentflow.agent_g` → `ValueError: experiments.rows[0] 校验失败：evidence_kind='proof' 时必须给出 verifier_subject_key`，**退出码 1**；位置 `agent_g.py:487` 的 fixture vs `schema.py:810` | **高**（G 无可用自检；且**测试套件不会发现它**——`_selftest` 在 `__main__` 里） |
| 3 | **`agent_a` / `agent_b` 没有自检入口** | 实测：`python -m agentflow.agent_a` 输出 **0 行**、退出码 0；`agent_b` 同 | 中（两个角色没有"我是否接线正确"的即时答案） |
| 4 | **`INVENTORY.md` / `tools.json` 是对 `test/test1/abflow` 的普查**，不是 `agentflow` | `INVENTORY.md:3` 逐字 | 中（引用它时必须说明口径，否则"数字对得上"是巧合） |
| 5 | **`agent_d._fallback_trace_tools` 的 `roles=("agent-C","agent-D")` 仍带前缀** | `agent_d.py:483/509/546` 三处逐字；`install_d_tools` 直接 `ToolRegistry(...)`（`:604`）⇒ **不过角色校验** | 中（`for_role("C")`/`for_role("D")` 永远拿不到这 3 个替身） |
| 6 | **`attack_tools.TERMINAL_STATUSES` 缺 `supported_not_proved`** | `attack_tools.py:75` = `("resolved","abandoned","stalled")` vs `schema.py:654` 的 `ATTACK_STATUSES` 有 `supported_not_proved` 且 `agent_f.py:820` 会写它 | 中（`include_terminal` 过滤会把已终结的计划当未终结） |
| 7 | **`review.scan_document` 的 `dep_check` 与 `verdict` 自相矛盾** | `review_tools.py:224` 的 `verdict` 完全没读 `dep_check["checked"]`；而 `:171-176` 的 `dep_check` 说"没查" | **高**（H 最常用的只读工具；只看 `verdict` 会把"依赖闭合从未检查"读成"通过"） |
| 8 | **`search.dedup_check` 静默报"不是重复"** | `search_tools.py:583-586` 的 `except Exception: return []`（与该函数 `store is None` 的严格 fail-closed 分支相反） | **高**（假阴性：已登记过的文献被判成新的） |
| 9 | **`conductor.py:797` 处有一处笔误引用**（本文档写作时的记录） | `condudctor.py:797` 是我在本文里先写错的；实际是 `conductor.py:797`。**这是本文的 bug，不是代码的**（保留在此以示勘误纪律） | 低（文档勘误） |
| 10 | **`.noai-paths` 登记了尚不存在的路径** | 逐字：`src/agentflow/release_check.py  [category: release-deploy] 发布前检查入口（**当前尚不存在**，先登记路径…）`；`scripts/release_check.py` **也不存在**（实测 `Get-ChildItem scripts` 只有 `__init__.py` 与 `noai_gate.py`） | 低（**这是有意设计**：先登记路径以免"换个目录就绕过"） |
| 11 | **`scripts/noai_gate.py` 声明了 `tests/test_noai_gate.py` 的负控用例，但该测试文件不存在** | 逐字（`.noai-paths:40`）："（有负控用例，见 `tests/test_noai_gate.py`）"；实测 `tests/` 下**没有** `test_noai_gate.py` | **高**（FC-27 判据②要求"该规则本身有一条**负控**"；声明存在而实际不存在 = **虚证**，正是 `draft/17` §6.2 的 `check_yan_anchors.py` 在防的那类错） |
| 12 | **`README.md` 是 `test/test1` 的过时副本** | `README.md:1` 标题"# test1 —— A/B 双智能体文献流水线（初步构造）"；`:23` 指向 `D:\Incubator\test\test1`；`:43` 写"127 passed"（实测 567）；`:100` 写"离线 127 条" | 中（**不在本次授权修改范围内**，只记录） |
| 13 | **`data/` 目录在仓库里被提交了**（16 个 JSON + `tasks.json`/`usage_ledger.json`/`eval_results.json` 空表） | 实测 `Get-ChildItem data`；`.gitignore` 不存在（**本目录不是 git 仓库**：`git diff` 退出码 129 "Not a git repository"） | 中（运行期数据混在源码树里；且**没有版本控制** ⇒ `LESSONS.md` C14 的"引入时点无法核实"在这个项目里**同样成立**） |

---

## 附录 S3：本文引用的全部命令与真实输出（可复跑）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
```

| # | 命令 | 实测输出（摘要） |
|---:|---|---|
| 1 | `python -m pytest -q` | 取样过程中三次实测：`567 passed, 8 deselected`（起点）→ `835 passed, 3 failed`（并行施工新增用例后）→ **`10 failed, 957 passed, 8 deselected in 191.56s`（末次）** |
| 2 | `$env:PYTHONPATH='src'; python -m agentflow.cli tools` | `工具总数：55`；`{'A':20,'B':18,'C':17,'D':37,'E':21,'F':32,'G':32,'H':23}`；`只读角色写工具泄漏：{'C': [], 'H': []}`；退出码 0 |
| 3 | `python -m agentflow.cli tools --role E` | `invalid choice: 'E' (choose from 'A', 'B', 'C', 'D')`；退出码 **2** |
| 4 | `python -m agentflow.cli verify` | `校验完成：通过  错误 0 / 警告 0`；退出码 0 |
| 5 | `python -m agentflow.cli demo` | `演示成功。`（10 项判定全 ✓）；退出码 0 |
| 6 | `python -m agentflow.agent_c` | `自检断言：46/46 通过` / `SELF-CHECK DONE`；退出码 0 |
| 7 | `python -m agentflow.agent_d` | `SELF-CHECK DONE（agent_d）`；退出码 0 |
| 8 | `python -m agentflow.agent_e` | `SELF-CHECK DONE（agent_e）：失败 0 项`；退出码 0 |
| 9 | `python -m agentflow.agent_f` | `SELF-CHECK DONE（agent_f）：失败 0 项`；退出码 0 |
| 10 | `python -m agentflow.agent_g` | `ValueError: … verifier_subject_key …`；退出码 **1** |
| 11 | `python -m agentflow.agent_h` | `SELF-CHECK DONE（agent_h）`；退出码 0 |
| 12 | `python -m agentflow.pipeline` | `SELF-CHECK DONE（pipeline）`；退出码 0 |
| 13 | `python -m agentflow.llm` | `SELF-CHECK DONE`；退出码 0 |
| 14 | `python -m agentflow.agent_a` | **0 行输出**；退出码 0（无自检块） |
| 15 | `python -m agentflow.agent_b` | **0 行输出**；退出码 0（无自检块） |
| 16 | `python scripts/noai_gate.py --check-consistency` | `一致：.noai-paths 与 AGENTS.md 的清单逐条相同`；退出码 0 |
| 17 | `python scripts/noai_gate.py --paths src/agentflow/cli.py` | `[clean] required_approvals=0`；退出码 0 |
| 18 | `python scripts/noai_gate.py --paths src/agentflow/schema.py` | `[requires_human] required_approvals=2`；退出码 **1** |
| 19 | `python scripts/noai_gate.py --git` | `[unknown] … 原因：git diff --name-only HEAD 退出码 129：Not a git repository`；退出码 **2** |
| 20 | 自建 census 脚本（`build_registry` + `Counter`） | `side_effect` 分布 `{'read':32,'write_local':15,'network':2,'none':6}`；需审批 17/55；`role_filter_notes = {}` |

> **本文的 census 脚本**是一次性探针（不落在 `scripts/`，因为它不是发布门）。
> `DEVELOPMENT.md` §8 要求把它**固化成 `scripts/release_check.py` 的一项**。
