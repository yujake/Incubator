# 角色 A / B / C / D 实现调查报告

调查对象：`D:\Incubator\agentflow`，包 `agentflow`，源码 `src/agentflow/`。
范围：角色 A、B、C、D 的实现，以及与之直接相关的工具层转发。
方法：`read` / `grep` / `python -B`（AST 统计与只读探针）/ 读 `projects/*/data/*.json` 与 `projects/*/out/tasks/*.json` 当真机证据。
本报告只描述"是什么"，不含修改建议。未核实的地方逐条标注。

真机样本：22 个 `projects/*` 工作区；`tasks.json` 合计 1871 行（A 161 / B 406 / C 22 / D 192 / E 等其余）；`literature.json` 733 行、`relations.json` 120 行、`conjectures.json` 169 行、`search_requests.json` 187 行、`analysis_reports.json` 0 行、`research_questions.json` 表不存在（全 22 个工作区都没有该文件）。

---

## 1. 逐角色的机制

### 1.1 角色 A：检索请求的生产与消费

**职责边界**：只有两个方向的动作——生产检索请求（`search_literature` 入队）与消费检索请求（`run_once` / `run` 领跑）。不抽概念、不建关系（那是 B）。

**动作清单与输入/输出**

| 动作 | 输入 | 输出 | 落点 | file:line |
|---|---|---|---|---|
| `run_once` | 无参 | `ARunResult`（dataclass，非 dict） | `search_requests` + `literature` | `agent_a/run_once.py:10` |
| `run` | `max_requests` | 汇总 dict | 同上（累加） | `agent_a/run.py:10` |
| `search_literature` | `topic` / `mode` / `description` | dict（含 `claimed_request_ids` / `result_lit_ids`） | `search_requests`（入队 + 终局） | `agent_a/search_literature.py:11` |
| `ingest_local` | `books_dir` / `pattern` / `limit` / `max_bytes` / `dry_run` | dict（含 `counts` / `literature_ids`） | `literature`（经 `locallib`） | `agent_a/ingest_local.py:54` |

**队列的生产**

- 生产路径一：CLI `submit`（人工，不过准入闸门，`core.py:56-59` 的 docstring 明写这一差别）。
- 生产路径二：`_enqueue_search`（`agent_a/core.py:51-81`）：同一事务内先过 `interactions.admit_search_request`（I7 准入），再 `next_prefixed_id` 取号，再 `SearchRequest.validate()`，最后 `tx.upsert`。被拒 ⇒ 直接返回闸门结果、零写入（`core.py:64-65`）。
- 生产路径三（他人）：C 的 `_submit_gap_requests`（`agent_c/core.py:541`）、D 的 `adjudicate`（`agent_d/adjudicate.py:311` 带闸门）、D 的 `research.submit_gap`（`tools/research_tools.py:272`，见 §3.4）、F 的 `submit_search_request`。

**队列的消费**

- `run_once` → `_claim()`（`agent_a/core.py:104-234`）：在 `store.tx("search_requests")` 内取 `X.order_pending_requests(rows)`，排序键由 `interactions` 唯一决定，A 不另写排序（`core.py:165-167`）。
- 领取判据唯一：`lease_expired(r["lease_until"])`。**不看 `claimed_by`**（`core.py:178-183`）；`claimed_by` 只决定这条被跳过时记进 `skipped_lease_active`（别人持着）还是 `skipped_lease_backoff`（自己上次失败的退避）。
- 先判租约再判 `attempts`（`core.py:184-194`）：租约有效期内不放弃别人的活；`attempts >= max_attempts`（缺省 3）时当场 `done=True` + `outcome="gave_up"`。
- 领到时置 `claimed_by=self.actor` / `lease_until=make_lease(lease_seconds)`（缺省 900 秒）/ `attempts+=1`，并 `tx.info("claim_order", …)` 记下"为什么是这一条"（`core.py:195-210`）。
- 四态 `skipped_reason`（`core.py:218-234`）：`no_pending_request` / `pending_requests_all_leased` / `pending_requests_all_in_backoff` / `no_claimable_request`。中间两态要求该计数 == `pending`，混合情形落最后一态。
- `run`（`agent_a/run.py:10-43`）循环调 `run_once`，遇到 `skipped_reason` 非空即停；`max_requests=None` 表示处理到没有可领为止。

**租约与退避**

- 正常领跑租约：`lease_seconds`（缺省 900）。
- 搜索失败后的退避租约：`retry_backoff_seconds`（缺省 60，`core.py:47`），写在 `run_once.py:205` 与 `:216` 两支，且**同时把 `claimed_by` 置空**（`run_once.py:173`）。
- 退避生效的实测（我自己跑的探针，`temp/_probe_a_claim.py`，非 pytest）：

```text
A after #1: outcome=None done=False claimed_by=None lease_active=True attempts=1
A after #2: request_id=None skipped_reason='pending_requests_all_in_backoff' attempts=1 backoff_cnt=1
A run(max_requests=None) summary: {'processed': 0, 'gave_up': 0, 'skipped_reason': 'pending_requests_all_in_backoff', 'skipped_lease_backoff': 1}
A after run(): attempts=1 done=False outcome=None
```

即：失败后第一次重领领不到、`attempts` 不增、`run()` 立刻停。

**下载与本地登记**

- `_stage_download`（`core.py:302-360`）：无锁下到 staging 目录；`download=False` ⇒ `status="skipped"` + `error="download_disabled"`；无 `pdf_url` ⇒ `error="no_pdf_url"`；无 downloader ⇒ `no_downloader`；下载器抛异常 ⇒ `status="failed"`；`ok=True` 但 `error` 以 `content_type_mismatch` 开头 ⇒ 降级为 `status="content_mismatch"`（`core.py:340-343`）。同时把 `url` / `url_source` 记进下载证据（`core.py:317-320` 与 `:357-359`）。
- `_attach_staged`（`core.py:361-390`）：搬文件的唯一判据是 `status ∈ ("ok","content_mismatch")` 且有 staged 字节；`content_mismatch` 的字节照样落盘（当证据）；搬失败 ⇒ `status="failed"` + `error="move_failed: …"`，返回 `rel_path=None`。建目录只在这一处（`core.py:378-379`）。
- `ingest_local`（`agent_a/ingest_local.py:54-132`）：不联网，委托 `locallib.ingest_directory`；provenance 三件事为 `actor="agent-A"` / `submitted_by="unknown"` / `origin_note="由 agent-A 从一个本地目录登记"`（`ingest_local.py:46-48`），与工具 `search.ingest_local` 同口径（`tools/search_tools.py:946-952`）。三处拒绝走 `refuse()`：`bad_books_dir` / `dir_not_found` / `io_error`。
- `ok=True` 只表示"调用做完了"：`kind` 由计数派生（`ingested or already` ⇒ `""`；否则 `unreadable` ⇒ `unsupported_format`；`skipped` ⇒ `skipped_by_limits`；否则 `nothing_matched`，`ingest_local.py:109-116`）。

**`outcome` 各取值的产生条件**（`run_once.py:175-223`）

| outcome | 产生条件 | 行状态 | file:line |
|---|---|---|---|
| `ok` | `new_ids` 非空（本轮至少有 1 篇落成文献行，含判重命中） | `done=True`、租约清空 | `run_once.py:175-179` |
| `no_results` | 搜索正常执行、零候选、且无 `search_errors` | `done=True` | `run_once.py:218-223` |
| `search_failed` | 只有"没发出去"的错误（第三态，`_split_errors` 命中 `QUERY_NOT_APPLICABLE_CJK` / `QUERY_EMPTY`）⇒ 当场终结、不重试；或可重试但 `attempts >= max_attempts` | `done=True` | `run_once.py:190-198`、`:207-211` |
| `gave_up` | 只在 `_claim()` 里产生（`attempts` 用尽），不可能在提交阶段产生 | `done=True` | `core.py:185-193` |
| `None`（未结束） | 有可重试错误且未超限 ⇒ 保持 `done=False` + 退避租约 | — | `run_once.py:199-206`、`:212-217` |

`_split_errors`（`core.py:271-285`）与 `_not_sent_states`（`core.py:263-270`）是这一分档的唯一实现；`_query_description`（`core.py:235-262`）决定进查询串的那份描述（非 ASCII 全丢，剩不到 2 个英文词就传空串）。

**依赖谁的前置产物**：只依赖 `search_requests` 表（谁写的都行）。不依赖 B/C/D 的任何产物。

**失败与拒绝的形态与码**：`search_literature` 三处 `refuse()`（`bad_topic` / `bad_mode` / `no_provider`，`search_literature.py:70-79`）落 `refused/invalid_params`；准入被拒返回 `outcome="rejected_by_gate"`（`search_literature.py:119-122`）；题面抽不出英文关键词返回 `outcome="query_not_applicable"` + `kind=query_not_applicable_cjk`（`search_literature.py:104-116`，零写入）。

### 1.2 角色 B：一次抽取的流水线

**职责边界**：只处理 `literature` 里 `processed=False` 的行；写 `concepts` / `relations`；另外承担命题台账（`statements`）与结构重复的合并决定（I5）。

**一次抽取的流水线**（`agent_b/run_once.py:10-312`）

1. `_claim()`（`agent_b/core.py:76-132`）领一篇未处理文献，置 `claimed_by` / `lease_until` / `mine_attempts+=1`。
2. 三种"没有可抽取内容"先分流，都置 `processed=True` 并写 `last_mine_error`，避免永远堵在队首（`run_once.py:40-59`）：`content_mismatch`（`content_type_mismatch: <文件名>`）、`path is None`（`no_local_file`）、文件不存在（`file_missing:<path>`）。
3. `extractor_is_fallback` 拒抽（`run_once.py:64-76`）：判据是抽取器自己声明的类属性 `is_framework_fallback`（`core.py:133-153`），`llm.RuleExtractor` 声明 `True`、`llm.OfflineFixtureExtractor` 声明 `False`、第三方无此属性按 `False`。拒抽时**不置 `processed`**，计数 `skipped_no_extractor`。
4. `extract_text(path)` + `extractor.extract(doc, lit_id, meta)`；抛异常 ⇒ 记 `last_mine_error`、不置 `processed`、计数 `failed`（`run_once.py:78-93`）。
5. 逐条关系做引文回验 `check_quote(doc, quote, page_range, widen=…, allow_fulltext_fallback=…)`（`run_once.py:96-116`）：`verified is True` ⇒ `quotes_verified+=1`（其中 `reason == substring_match_outside_declared_range` 另计 `quotes_out_of_declared_range`）；`False` ⇒ `quotes_failed`；其余 ⇒ `quotes_unknown`。**不丢弃任何一条**——校验不过的仍然落库，只是 `status="suspect"`（`run_once.py:203-207`）。
6. 提交（一个事务，`run_once.py:119-310`）：概念解析 → 关系判重 → I6 冲突闸门 → 落 `relations` → 派生 `related_concepts` → 置 `processed=True`。
7. 概念解析 `resolve_concept`（`run_once.py:124-154`）：先 `D.find_concept` 复用；命中就合并别名并 `upsert`；未命中才 `tx.alloc_id("concept")` 建行。概念名 → 代号的唯一性靠锁内解析。
8. 关系判重 `D.decide_relation`（`run_once.py:180-200`）：`duplicate` ⇒ 只计数；`suspect` 等 ⇒ 落库并把 `duplicate_of` 指过去。
9. I6 闸门 `I.check_conflict(draft, existing_relations=self._conflict_scope(tx))`（`run_once.py:226-247`）：三态计数 `conflict_checks_run` / `conflicts_detected` / `conflict_checks_skipped`；矛盾照写但降 `suspect`。
10. `related_concepts` 由 `D.derive_related_concepts` 按关系表整体重算（`run_once.py:288-301`），不做增量 append。

**`RuleExtractor` 与模型抽取的分界**

- 分界不在"用不用模型"，而在抽取器自报的 `is_framework_fallback`（`core.py:146-149`）。
- `RuleExtractor.is_framework_fallback = True` ⇒ `_claim` 领到行后立即拒抽、不置 `processed`（`run_once.py:64-76`）。
- `host.py:61` 与 `host.py:71` 记录了 `run-agent` 从不给 B 任何 client 的事实：那条路径上 B 落到 `RuleExtractor` ⇒ 如实报 `no_llm_extractor`。
- 真机读数（`projects/*/data/literature.json`）：`last_mine_error` 取值分布为 `no_local_file` 350、`content_type_mismatch: …` 各 7、`no_llm_extractor` 1；`mine_attempts` 只有 `{0: 318, 1: 415}`。
- 另一处"框架侧拒抽"在 B 的任务派发层：`cli.py:241` 注释记着"此前这里写死 `RuleExtractor()` ⇒ `B.run_once` 永远拒抽（`R-56`）"。

**`register_statement` 的硬校验（逐条）**（`agent_b/register_statement.py:69-207`）：① `statement_full` 非空，只有短版不算数（`bad_statement`，`:88-92`）；② `origin ∈ S.STATEMENT_ORIGINS`（`bad_origin`，`:93-96`）；③ `evidence_kind ∈ S.EVIDENCE_KINDS`（`bad_evidence_kind`，`:97-101`）；④ `origin="external_lit"` ⇒ `source_lit_id` 非空（`missing_source`，`:102-106`）；⑤ `quote_verified is not True` ⇒ `quote_reason` 非空（`missing_quote_reason`，`:107-110`）；⑥ `origin="external_lit"` ⇒ `page_range` 的 `start` 或 `label` 至少一个（`missing_page_range`，`:120-128`）；⑦ `origin="own_result"` ⇒ `doc_id` 或 `line_range` 的 `start`/`label` 至少一个（`missing_own_source`，`:129-137`）；⑧ `origin="own_result"` ⇒ `proof_text` 非空（`missing_proof_text`，`:140-144`）；⑨ `source_lit_id`/`doc_id` 若给必须过 `S.is_valid_id`（4 位十进制，`bad_id`，`:149-155`）；⑩ 事务内 `tx.find("literature", lit_id=…)` 必须命中，否则拒绝并回带"表现在几行 / 现有哪些 lit_id（前 8 个）"（`unknown_lit_id`，`:159-177`）；⑪ `Statement.validate()` 第二道保险（`:200`）。命题三件套 = 完整命题正文（含假设）/ 逐字证明摘录 / 出处，`quote_verified` 与 `quote_reason` 的三态配对是第五、第六条必填。

**`decide_structural_duplicate` / `resolve_structural_duplicate`**：只决定不落盘（`decide_structural_duplicate.py:45`），执行合并另走 `resolve_structural_duplicate`（`resolve_structural_duplicate.py:10-41`），后者在同一个事务里重算决定再执行；判 `reject` 时一行都不写。

**依赖谁的前置产物**：`literature` 行（A 写的，且要求 `processed=False`）。

**失败与拒绝形态**：抽取失败 ⇒ 不置 `processed`、只留 `last_mine_error`（`run_once.py:84-93`）；`no_llm_extractor` ⇒ 同上且单独计数（`run_once.py:69-76`）；`register_statement` 的 10 种拒绝全部经 `refusals.refuse` 落 `refused/invalid_params`（`refusals.py:49-63`）。

### 1.3 角色 C：产物到底是什么、落不落盘

**C 的实现位置**

- 角色类：`agent_c/core.py:1132`：`class AgentC(_Hottest, _Paths, _Cold, _Gaps, _Neighbors, _RelationsBetween, _Contradictions, _StructuralDuplicates, _Handle, _Core)`。
- 动作文件：`agent_c/hottest.py`、`paths.py`、`cold.py`、`gaps.py`、`neighbors.py`、`relations_between.py`、`contradictions.py`、`structural_duplicates.py`、`handle.py`。
- 声明（权限面真身）：`specs/c.py:29-96`（9 个动作，全部 `side_effect="read"`）。
- 工具面：`agent_c/core.py:916-1131` 的 `register_tools`，注册 `graph.hottest` / `graph.paths` / `graph.cold` / `graph.gaps` / `graph.svc_neighbors` / `graph.svc_relations_between` / `graph.contradictions` / `graph.structural_duplicates` / `graph.svc_check_conflict`，全部 `side_effect="read"`、`roles=("C","D")`（`core.py:956`）；
- 低层图查询在 `tools/graph_tools.py`（`graph.build` / `graph.stats` / `graph.neighbors` / `graph.relations_between`，四者 `read`，该文件无 `store.tx`、无文件写）。

**产物是什么**：两种形状并存。

- `hottest` / `paths` / `cold` / `gaps` / `handle` 返回 `AnalysisReport` **dataclass 实例**（`agent_c/_support.py:205-325`），不是 dict。
- `neighbors` / `relations_between` / `contradictions` / `structural_duplicates` 返回 **dict**。

**落不落盘的直接证据**

1. `AnalysisReport.persist()`（`agent_c/_support.py:256-324`）是唯一把 markdown 写进 `<ws>/reports/<rid>-<kind>.md` 并把登记行 upsert 进 `analysis_reports` 的地方。调用者只有两处：CLI `analyze`（`cli.py:481`）与 `pipeline._persist_report`（`pipeline.py:87-148`）。
2. `conductor.summon` 路径只落"任务产物摘要"：`conductor.py:1184-1223` 的 `_write_task_digest` 写 `out/tasks/<task_id>.json`，其中 `payload_preview = blob[:2000]`、`payload_keys = sorted(...) if isinstance(payload, Mapping) else []`（`conductor.py:1213-1214`）。**整份 payload 不落任何地方**。
3. 真机 `out/tasks/*.json`（21 个 C 任务是 dataclass 返回值、1 个是 dict 返回值）：

```text
p2-review t-0169.json   hottest        done ok 744  []
p2-review t-0203.json   gaps           done ok 4890 []
p3-review-...-220936 t-0264.json contradictions done ok 663
    ['checked','contradictions','limit','method','method_note','missing_relation_ids',
     'reason','scanned','scope','strong_count','strong_relation_id_pairs','truncated','weak_count']
```

即 `hottest` / `gaps` / `paths` / `cold` 的 `payload_keys` 恒为 `[]`（因为 payload 是 dataclass 实例，`isinstance(payload, Mapping)` 为假），`payload_preview` 是 `repr` 字符串的前 2000 字节（`json.dumps(..., default=str)` 把 dataclass 打成 repr）。

4. 真机 `analysis_reports.json` 在全部 22 个工作区都是 `rows = 0`：

```text
p10-cite rows= 0 ; p2-review rows= 0 ; … ; project11 rows= 0
```

5. `tasks.artifacts` 指的就是那份摘要文件本身，不是完整产物：`p3-review-20261001-220936` 的 C 行 `artifacts=['out/tasks/t-0169.json']`、`['out/tasks/t-0203.json']`、`['out/tasks/t-0264.json']`。
6. `specs/m.py:79` 与 `agent_prompts.py:1137` 把这件事逐字写成口径："C 的产物是返回值本身、不落台账"；`closing.py:844` 的 `c_analysis_runs` 因此只能数 `tasks` 里 `role=C` 的行。

**与 `relations` 表（B 写的）的关系**

- C 只读 `relations`。`RelationGraph.from_store` 无锁快照读 `concepts` / `relations` / `literature`（`tools/graph_tools.py:354-358`）。
- 冲突判据不另写一份：`contradictions` 全部委托 `interactions.detect_contradictions`（`contradictions.py:92`），结构重复委托 `interactions.structural_duplicate_pairs`（`core.py:510`），I6 闸门是 `interactions.check_conflict` 的转发（`_support.py:118`）。
- C 的写入面只有两处：`analysis_reports`（靠 `persist()`）与 `search_requests`（I3，`gaps(submit_requests=True)`），登记在 `capabilities.py:1137` 的 `WRITE_SETS["C"] = {"analysis_reports","search_requests"}`。

**`gaps(submit_requests=true)` 如何把结果变成检索请求**

- 入口 `_Gaps.gaps(..., submit_requests: bool = False)`（`gaps.py:10`），默认关闭（docstring `gaps.py:26-27`）。工具面刻意不暴露这个参数（`core.py:1019-1023`），只有编排层直接调方法能开。
- 候选先算成 `worth`（通过 veto 且 `confidence >= medium`，`gaps.py:138`），再交给 `_submit_gap_requests(worth, enabled=…)`（`gaps.py:144` → `core.py:541-698`）。
- 一个事务 `store.tx("search_requests", actor="agent-C", note="gaps:submit_requests(run_by=…)")`（`core.py:623-625`），三条闸门顺序执行：主题规范化去重（`core.py:640-649`）→ 单次上限 `max_gap_requests_per_run`（缺省 3，`interactions.py:156`）→ 全局在途闸门 `interactions.admit_search_request`（`core.py:662-669`）。
- 落行的 `submitted_by="agent-C"`（`core.py:678`）、`mode="topical"`、`for_question_id=None`、`submit_note` 写清候选理由与优先级依据（`core.py:681-685`）。
- 返回里四个键始终存在（`submitted_request_ids` / `rejected_requests` / `skipped_duplicate_topics` / `request_submission`），用 `enabled` 位区分"没做"与"做了没结果"（`gaps.py:223-229`）。

**依赖谁的前置产物**：`relations` / `concepts` / `literature`（B 与 A 写的）。`hottest` 在关系表为空时返回 `ok=False`（`hottest.py:37-50`），`gaps` 同理（`gaps.py:312-313`）。

**真机读数（C 的动作被谁用过）**

```text
(role, action, outcome) 全库计数：
('C','hottest','ok') 14 ; ('C','gaps','ok') 7 ; ('C','gaps','refused') 7
('C','contradictions','ok') 1
refusal 明细：C.gaps 的参数不合法：出现未声明的参数：['top_n']（schema 只允许 ['limit','request','submit_requests']）
```

即 `gaps` 被召唤 14 次，一半因传了 `top_n` 被参数校验拒；`submit_requests` 在真机 tasks 参数里出现 **0 次**（`grep` 全部 `tasks.json` 的 `params`，命中 0）；真机 `search_requests.json` 里 `submitted_by` 分布为 `{agent-F: 154, human: 30, M: 1, M-as-probe: 1, probe: 1}`，**没有任何一行是 `agent-C`**。

### 1.4 角色 D：研究循环

**职责边界**：把 C 的报告消化成研究问题、评估证据是否就绪、必要时向 A 要检索、把就绪问题回答成结论、裁决矛盾、登记猜想、写研究报告。**不自己产证据**：证据全部来自 `trace.*` 读 C/B 的表。

**研究问题的状态机**

- 状态词表与迁移表（唯一权威实现）：取值 `("open","needs_evidence","researching","answered","dropped")`（`schema.py:450`）；`open -> (needs_evidence, researching, dropped)`、`needs_evidence -> (researching, dropped)`、`researching -> (needs_evidence, answered, dropped)`、`answered -> ()`（终态）、`dropped -> ()`（终态，必须写理由）（`tools/research_tools.py:508-514`）。
- 校验点：`research.set_status` 先查迁移表（`research_tools.py:556-563`），再交给 `schema.ResearchQuestion.validate` 终审。`researching → needs_evidence` 由 `research.submit_gap` 直接写（`research_tools.py:319`，与等待集同事务同锁）；`needs_evidence` 必须带非空 `waiting_request_ids`（docstring `research_tools.py:260-262`）；`poll` 把 `needs_evidence`/`open` 拉回 `researching`（`agent_d/poll.py:132`）；终局清空等待集的三处在 `adjudicate.py:292`/`:302`/`:366`。真机上 `research_questions` 表 22 个工作区全不存在。

**证据就绪判据（`assess`）**

- `assess(qid, evidence=None)`（`agent_d/assess.py:10-58`）：`evidence` 未给 ⇒ 自己 `trace_question(qid)`；`ev["c_queries"] is None` ⇒ 补一次 `probe_c(qid)`（`assess.py:26-27`，理由见 `assess.py:19-23` 的 I1）；`degree = max(concept.degree)`；`keywords = question_keywords(question, extra=[概念名])`。
- 真正的判据在 `analyze_gaps(...)`（`_support.py:241-330`）：三条可核实判据——(a) 关键词零命中 → high；(b) `degree < degree_threshold` 且无 `quote_verified=True` → medium；(c) 存在矛盾对 → high；任一成立即 `insufficient=True`（`_support.py:271-319`）。
- 另外给出 `sufficient = not insufficient`、`priority`、`confidence`（`evidence_confidence`，`_support.py:331-368`，阈值 ≥3 high / ≥1.5 medium / 否则 low）、`l3_needed`、`c_queries`、`c_evidence`、`c_wiring`，并把整个 verdict 存进 `self.last_assessment`（`assess.py:57`）。

**`research` / `run_round` 的产物**

- `research(qid)`（`agent_d/research.py:10-87`）：`trace_question` → 必要时 `probe_c` → `assess` → 必要时 `trace_l3` → `_compose`（LLM 可选）→ `_apply_c_evidence_caveat`。落库只有一处：`store.tx("research_questions")` 里追加 `evidence_lit_ids`、把 `status ∈ ("open","needs_evidence")` 推成 `researching`、把一行人话 note 追加进 `notes`（`research.py:44-62`）。**分析正文与结论只在返回值里**：`result` dict（`research.py:66-84`）另存进内存 `self.last_research[qid]`（`research.py:85-86`）。
- `run_round(report, submit=True, limit=None)`（`agent_d/run_round.py:10-112`）：`ingest → _adjudicate_ready_contradictions → 逐问题(trace → assess → consider) → poll → 对 `researching` 且 `kind != "contradiction"` 的问题 `research`。返回汇总 dict（`report_id` / `ingested` / `adjudications` / `traced` / `assessed` / `submitted` / `researched` / `confidence` / `poll`）。真实产物仍然只有落库的那几项。

**"证据包"由哪些行组成**

- `trace_question(qid)`（`agent_d/trace_question.py:10-199`）返回的 dict 就是证据包：
  - `claims[]`：每条关系一行，键含 `relation_id` / `lit_id` / `concept_ids` / `quote` / `description` / `statement` / `page_range` / `status` / `quote_verified` / `concept_pair_key` / `on_path` / `in_chain` / `hop` / `hop_from` / `hop_to`（`trace_question.py:85-107`）。
  - `l2[]`：每个概念一行（`concept_id` / `name` / `definition` / `aliases` / `related_concepts` / `degree` / `occurrences` / `relations`），`trace_question.py:166-180`。
  - `l3[]`：文献元数据 + 本地文件 + 正文可得性，由 `trace_l3` 填（`trace_l3.py:10-39`）。
  - `path_chains[]`：`trace.chain` 给的 `relation_ids` / `chain_text` / `missing`（`trace_question.py:117-131`）。
  - `traces[]`：L1/L2/L3 每一步"found 还是没有"的留痕；`trace_mode ∈ {external, fallback}`；`warnings = self.last_tool_errors`。
- 数据来源是 `trace.relation` / `trace.concept` / `trace.chain` / `trace.literature`；工具缺失时用内置降级替身（`_support.py:374-419`，`trace_mode="fallback"`），降级替身只读 `relations` / `concepts` / `literature` 三张表。

**`register_conjecture` 的状态机与 `testable` 的强制**

- D 侧 `register_conjecture(**params)`（`agent_d/register_conjecture.py:10-37`）是纯转发：调 `conjecture.register_conjecture`，失败时既 `append` 进 `last_tool_errors` 又 `raise EvidenceError`（`register_conjecture.py:26-36`），让终态落 `failed` 而不是"ok + payload=None"。
- 工具层 `conjecture_tools.register_conjecture`（`tools/conjecture_tools.py:71-241`）：新建/更新合一；`None` = 调用方没提（保留库里已有值）；没给 `conjecture_id` 时先按规范化 `statement` 判重，命中则更新既有行并记 `duplicate=true`，要新建必须显式 `force_new=true`（`:107-136`）。必填只有 `statement` 与 `origin`（`:115-122`；JSON Schema required 在 `:279`）。
- 状态词表 `S.CONJECTURE_STATUSES = ("proposed","needs_evidence","testing","supported_not_proved","refuted","proved","promoted","known_in_literature","withdrawn")`（`schema.py:464-465`）。
- **没有"从哪到哪"的迁移表**：`conjecture_tools.py` 里没有 `LEGAL_TRANSITIONS`；只在 `row_obj.validate()`（`:185`）按"这个状态必须带什么"拒收（模块 docstring `:19-21` 自陈）。
- 单行判据（`schema.Conjecture.validate`，`schema.py:756-820`）：`proposed` 必须给非空 `testable`，给不出就落 `needs_evidence`（`:782-785`）；`needs_evidence` 必须写 `notes` 或 `withdraw_reason`（`:786-789`）；`supported_not_proved` 必须至少一条 `experiment_ids`（`:790-791`）；`refuted` 必须给 `counterexample_experiment_id`（`:792-796`）；`proved` 必须给 `proof_experiment_id`（`:797-798`）；`promoted` 必须同时有 `proof_experiment_id` 与 `promoted_to.id`（`:799-804`）；`known_in_literature` 必须给 `known_lit_id`（`:805-808`）；`withdrawn` 必须给 `withdraw_reason`（`:809-810`）；所有状态都要 `statement` 非空且"读起来不是问题"、`form ∈ CONJECTURE_FORMS`、`origin` 非空、`experiment_ids` 升序去重且 ID 形态合法（`:762-781`、`:811-820`）。
- 跨对象判据在写入期也核一遍：引用的实验必须存在（`conjecture_tools.py:189-196`，`kind="dangling_experiment"`）、`known_lit_id` 必须在文献表（`:197-205`，`kind="dangling_lit"`）。
- 真机：`conjectures.json` 169 行，`testable` 非空 169/169；`status` 分布 `{supported_not_proved: 140, known_in_literature: 7, proposed: 22}`。

**依赖谁的前置产物**：`ingest` 要一份 C 的报告（`report` 参数，required）；`trace_*` 要 `relations` / `concepts` / `literature`；`research.submit_gap` 要 `research_questions` 行已存在；`adjudicate` 要 `kind="contradiction"` 且 `contradiction_relation_ids` 恰 2 条。

**失败与拒绝形态**：`trace_question` / `submit_gaps` 对不存在的问题 `raise EvidenceError`（`trace_question.py:33-34`、`submit_gaps.py:34-35`）；`adjudicate` 对不存在的问题抛错并列出在册 id（`adjudicate.py:70-85`）、对非矛盾问题返回 `checked=False` + `action="not_a_contradiction"`（`adjudicate.py:86-95`）、对 `contradiction_relation_ids != 2` 返回 `checked=False` + `bad_row`（`adjudicate.py:97-103`）；`register_conjecture` 失败抛异常（落 `failed`）。

**真机使用面**

```text
('D','register_conjecture','ok') 190 ; ('D','register_conjecture','refused') 1
('D','poll','ok') 1
```

`ingest` / `run_round` / `assess` / `research` / `consider` / `adjudicate` / `write_report` 在真机 tasks 里 **0 次**；`research_questions.json` 在 22 个工作区都不存在。

### 1.5 工具层如何转发 / 落库（只列与 A–D 直接相关的）

- `search.register`（roles=("A",)，write_local）落 `tools/search_tools.py:1010` 的 `store.tx("literature","search_requests")`：写 `literature` `:1101`，只更新既有请求行 `:1149`。
- `search.ingest_local`（("A",)，write_local）委托 `locallib.ingest_directory`（`search_tools.py:946-952`），行由 `locallib.py:247` 的事务写（`locallib.py:252-293`）。`search.download`（("A",)，write_local）只写文件系统 `downloads/`（`:723-726`），不写表。
- `graph.build` / `stats` / `neighbors` / `relations_between`（("C","D")，read）不写盘；`graph.build` 只把图缓存在内存（`graph_tools.py:829`）。
- `table.create` / `update` / `delete`（("A","B","C","D")，write_local）的 `store.tx` 在 `table_tools.py:637` / `:695` / `:753`；写工具在装配期剥掉只读角色（`table_tools.py:995-996`，`READ_ONLY_ROLES=("C","H")` 见 `tools/__init__.py:104`）。
- `research.submit_gap`（("D",)，write_local）落 `research_tools.py:272` 的 `store.tx("search_requests","research_questions")`：请求行 `:314`、问题行 `:327`、模块私有台账文件 `data/research_request_ledger.json`（`:339`，`LEDGER_FILE:57`）；`research.poll_waiting`（read）不写盘（`:418-503`）；`research.set_status` 落 `:556`，写 `:574`。
- `conjecture.register_conjecture`（("D",)，write_local）落 `conjecture_tools.py:125` 的 `store.tx("conjectures","experiments","literature","documents")`，写 `:212`。

`research.poll_waiting` 的 ready 判据：该问题所有请求都已结束（`done` 或 `outcome` 落在终局）**且**结果文献全部 `processed`（`research_tools.py:459-489`）；返回 `{'ready','waiting','counts'}`，每个 item 带 `new_lit_ids` 与 `details[].state ∈ {missing, waiting, waiting_b, ready}`。

---

## 2. 关键文件与函数表（只列承担机制的）

| file:line | 一句话职责 |
|---|---|
| `agent_a/core.py:51` | `_enqueue_search`：过 I7 准入 → 取号 → 落 `search_requests` |
| `agent_a/core.py:104` | `_claim`：唯一取任务判据 + 四态 `skipped_reason` |
| `agent_a/core.py:235` | `_query_description`：决定进查询串的那份描述（非 ASCII 丢掉） |
| `agent_a/core.py:271` | `_split_errors`：把失败分成"没发出去"与"发出去失败了" |
| `agent_a/core.py:302` | `_stage_download`：下载到 staging，含 `content_mismatch` 降级 |
| `agent_a/core.py:361` | `_attach_staged`：staging → `library/<lit_id>/`，建目录的唯一责任人 |
| `agent_a/run_once.py:10` | 消费一条请求的完整链路 + `outcome` 五态分流 |
| `agent_a/run.py:10` | 连续领跑（`skipped_reason` 即停） |
| `agent_a/search_literature.py:11` | 生产 + 立即领跑一次（入队过闸门） |
| `agent_a/ingest_local.py:54` | 本地目录 → `literature` 行（不联网、sha256 幂等） |
| `agent_b/core.py:76` | `_claim`：领未处理文献（判据与 A 不同，见 §3.2） |
| `agent_b/core.py:133` | `_is_fallback_extractor`：按类属性 `is_framework_fallback` 判回退 |
| `agent_b/core.py:237` | `_claim_reprocess`：I4 的四条准入判据 |
| `agent_b/run_once.py:10` | 一次抽取流水线（概念 → 关系 → 逐字回验 → 命题三件套的落库面） |
| `agent_b/register_statement.py:69` | 命题台账写入口的 10 条硬校验 |
| `agent_b/decide_structural_duplicate.py:10` | I5：两路独立证据 + 确定性 survivor 规则 |
| `agent_b/resolve_structural_duplicate.py:10` | 同事务内重算决定并执行合并 |
| `agent_c/hottest.py:10` | 热度统计（occurrences 口径）+ 代表关系 |
| `agent_c/gaps.py:10` | 缺口找法 + 二元 verdict + I3 提交入口 |
| `agent_c/core.py:541` | `_submit_gap_requests`：C 唯一的确定性写入路径（三条闸门） |
| `agent_c/core.py:916` | `register_tools`：C 的工具面（全 `read`） |
| `agent_c/_support.py:205` | `AnalysisReport` dataclass（C 的返回对象） |
| `agent_c/_support.py:256` | `persist()`：唯一把 C 报告落 `reports/` + `analysis_reports` 的地方 |
| `agent_d/assess.py:10` | 证据就绪判定的入口（转 `analyze_gaps`） |
| `agent_d/_support.py:241` | `analyze_gaps`：三条可核实判据的唯一实现 |
| `agent_d/_support.py:331` | `evidence_confidence`：置信度上限的唯一算法 |
| `agent_d/trace_question.py:10` | 证据包（claims / l2 / l3 / path_chains / traces） |
| `agent_d/research.py:10` | 回答一个就绪问题（落库只有 `evidence_lit_ids` / status / notes） |
| `agent_d/consider.py:10` | 足够 ⇒ 推 `researching`；不足 ⇒ `submit_gaps` |
| `agent_d/submit_gaps.py:10` | 不重复提交 + 两道预算 + 调 `research.submit_gap` |
| `agent_d/poll.py:10` | 等待集复查 + 证据相关性三态 + 降优先级 |
| `agent_d/adjudicate.py:10` | I2 裁决闭环（verdict → status 映射、三条终止条件） |
| `agent_d/run_round.py:10` | 一轮编排（ingest → 裁决 → trace/assess/consider → poll → research） |
| `agent_d/register_conjecture.py:10` | 猜想登记/更新（失败抛异常，不假装 ok） |
| `agent_d/write_report.py:10` | 研究报告渲染（10 个 out_path 兜底 + 审计一节） |
| `agent_d/core.py:27` | D 的阈值面（每问 2 次 / 全局 20 次 / 矛盾 2 轮 / …） |
| `agent_d/core.py:893` | `_budget`：按描述里的 `[q:NNNN]` 统计每问题提交数 |
| `conductor.py:1059` | `_end_from_payload`：handler 返回值 → 终态（`ok=False` 不许记 ok） |
| `conductor.py:1184` | `_write_task_digest`：唯一写 `out/tasks/<task_id>.json` 的地方（预览 2000 字节） |
| `tools/research_tools.py:508` | `LEGAL_TRANSITIONS`：研究问题状态机的唯一权威 |
| `tools/conjecture_tools.py:71` | 猜想的唯一写入口（判重 + 跨对象存在性） |
| `schema.py:756` | `Conjecture.validate`：猜想状态机的单行判据 |
| `refusals.py:49` | `refuse()`：动作拒绝的唯一形态（`refused/invalid_params`） |

---

## 3. 可疑的逻辑 bug

### 3.1 【C 的产物只在返回值里，没有落盘；落下来的也是被截断的】

- **现象**：`hottest` / `paths` / `cold` / `gaps` / `handle` 返回 `AnalysisReport` dataclass 实例。经 `conductor.summon` 调用时，只有 `out/tasks/<task_id>.json` 被写，其中 `payload_preview` 是 `repr` 的前 2000 字节、`payload_keys` 为空列表；完整 payload 与整篇 markdown 不落任何地方。`analysis_reports` 表保持 0 行。
- **证据**：
  - `conductor.py:1200`（`blob = json.dumps(payload, …, default=str)`）、`conductor.py:1213-1214`（`payload_keys` 只在 `isinstance(payload, Mapping)` 时非空；`payload_preview = blob[:2000]`）。
  - 真机：`p2-review/out/tasks/t-0203.json` 的 `payload_bytes=4890`、`payload_keys=[]`、`len(payload_preview)==2000`；`p2-review/out/tasks/t-0169.json`（hottest）`payload_keys=[]`；唯一非空的是 `t-0264.json`（`contradictions`，返回 dict）。
  - 真机：22 个工作区的 `data/analysis_reports.json` 全为 `rows = 0`（命令：`python -B -c "…json…len(rows)…"`）。
  - 落盘入口只有 `cli.py:481` 与 `pipeline.py:87-148`。
- **影响面**：`D.ingest(report)` 只能吃 `payload` 里的 `entries` / `paths` / `candidate_gaps`（`agent_d/core.py:285-461` 逐键读取）。经 `conductor` 召 C 的那些报告，D 侧拿不到 `payload`（只有 repr 字符串），也拿不到 `report_id`（`agent_c/_support.py:226` 默认 `None`）。同一份 C 结论要复用只能重跑 C。
- **是否复现**：真机已复现（21/22 条 C 任务行 `payload_keys=[]`、`analysis_reports` 全 0 行）。

### 3.2 【B 的 `_claim` 不认自己写的租约 ⇒ 失败当场重试、重试预算在同一次调用里烧光】

- **现象**：抽取失败时 `run_once` 把 `claimed_by=None` + `lease_until=None` 写回文献行（**没有**写退避租约）；`_claim` 的跳过判据是 `r.get("claimed_by") and not lease_expired(r.get("lease_until"))`——第一项为假即不跳过 ⇒ 同一个 B 实例立刻再领同一行。
- **证据**：
  - `agent_b/run_once.py:85-90`（失败分支只置 `last_mine_error`，不写租约）、`agent_b/core.py:97`（跳过判据）、`agent_b/core.py:100-113`（`attempts` 与领取）。
  - 同族的 A 写法相反：`agent_a/core.py:178-183` 只判租约是否过期（不看 `claimed_by`），失败分支另外写退避租约（`run_once.py:205`/`:216`）。
  - 我的探针（`temp/_probe_b_claim.py`，真 `Store` + 真 `AgentB` + 抛异常的替身抽取器，不联网）：

```text
after run_once #1: failed=1 processed=False claimed_by=None lease_until=None mine_attempts=1
after run_once #2: failed=1 processed=False claimed_by=None mine_attempts=2 last_err='RuntimeError: boom-probe'
after run_once #3: failed=1 processed=False claimed_by=None mine_attempts=3
after run_once #4: failed=0 processed=True skipped_reason='no_claimable_literature' mine_attempts=3
lease still active at this moment: False
```

  四次连续调用就把 `max_attempts=3` 烧光并当场判死；对照 A 的探针（`temp/_probe_a_claim.py`）在同一序列上 `attempts` 停在 1、`skipped_reason="pending_requests_all_in_backoff"`。

  - 同族写法还有两处：`agent_b/core.py:261`（`_claim_reprocess`）与 `agent_b/core.py:558-559`（`_record_reprocess_failure` 把 `claimed_by` 与 `lease_until` 一起清空）。
  - B 自带自检的覆盖面：`python -B -m agentflow.agent_b` 实测 `19/19 项通过`，其中第 4 段只断言"第一次失败后没有置 `processed`"，没有任何一条断言"再领一次领不到"（`agent_b/core.py:970-978`）；对照 A 的自检第 8b 段专门断言"再领一次领不到、`attempts` 不增"（`agent_a/core.py:592-610`）。
- **影响面**：抽取异常（依赖缺失、文件损坏、抽取器抛错）时，一次 `run()` 调用会在毫秒级把该文献的 `mine_attempts` 从 0 推到 `max_attempts` 并置 `processed=True`，`last_mine_error` 只留下最后一次的异常文本；"租约到期后重试"这条语义不成立。`reprocess_requests` 同型。
- **是否复现**：真机未复现（`literature.json` 里 `mine_attempts` 只出现 0 与 1；`last_mine_error` 的 358 条几乎全是"事先就判为不可读"的 `no_local_file` / `content_type_mismatch`，不走异常分支）；探针下稳定复现。

### 3.3 【队列的生产与消费在真机上错开（结构性断链）】

- **现象**：`search_requests` 的生产方与消费方在真机上错开：A 只在 2026-09-29 04:18–05:12 跑过；此后（含 09:53 提交的两条请求）没有任何 A 任务行。
- **证据**：
  - 真机 `tasks.json`：A 的 `run_once` 161 行，全部落在 `p2-review` 及其 6 个快照，时间窗口 `2026-09-29T04:18:29` – `2026-09-29T05:12:06`。其余 14 个工作区 A 任务 0 行。
  - 真机 `search_requests.json`：`p2-review` 22 行，时间窗 `04:18:28` – `09:53:11`；其中 `r-0021` / `r-0022` 至今 `done=false`、`outcome=None`、`attempts=0`、`claimed_by=None`，`submitted_by="agent-F"`。同一模式在 7 个快照工作区重复出现（合计 14 条未完成请求）。
  - 真机 `submitted_by` 分布：`{agent-F: 154, human: 30, M: 1, M-as-probe: 1, probe: 1}`——`agent-C` 与 `agent-D` 各 0 行；`tasks.json` 里 `params` 含 `submit_requests` 的行数 0。
  - 代码侧：消费入口只有 A 的 `run_once`（`specs/a.py:31`）/ `run`（`specs/a.py:40`）；生产入口有 `cli submit`、A 的 `search_literature`（`search_literature.py:118`）、C 的 `_submit_gap_requests`（`core.py:623`）、D 的 `research.submit_gap`（`research_tools.py:272`）、D 的 `adjudicate`（`adjudicate.py:317-341`）、F 的 `submit_search_request`。**没有任何生产入口自带"顺带消费"步骤**；"派 A 的 `run_once` 认领"是主控的纪律（`specs/m.py:73`）。
- **影响面**：请求一旦提交而无人认领，行会永久停在 `done=false`（`attempts` 只在被领到时 +1，`gave_up` 也只可能发生在被领取时，`agent_a/core.py:184-193`），`conductor.state` 的 `unfinished` 是唯一读数。
- **是否复现**：真机已复现（`r-0021`/`r-0022` 等 14 行）。成因（是主控没派、还是没人要求派）本次未核实。

### 3.4 【D 的缺口提交路径不过 I7 在途闸门；每题预算的键依赖描述文本】

- **现象一**：`research.submit_gap` 直接构造并写入 `search_requests` 行（`research_tools.py:304-314`），**没有**调 `interactions.admit_search_request`；`agent_d/submit_gaps.py:58-64` 也不调。同一件事在另外三处各判一次：A 的 `_enqueue_search`（`agent_a/core.py:63`）、C 的 `_submit_gap_requests`（`agent_c/core.py:662`）、D 的 `adjudicate`（`adjudicate.py:311`）都过闸门。
- **证据**（我的探针 `temp/_probe_d_gate.py`：先塞 25 条在途请求，再调真工具层）：

```text
inflight rows: 25
admit_search_request would say: {'admitted': False, 'reason': '在途检索请求已达上限 25/20 ⇒ **拒绝新请求**…', 'inflight': 25, 'limit': 20, …}
submit_gap ok=True kind=None
submit_gap data duplicated=False request_id=r-0026
inflight rows AFTER submit_gap: 26 (闸门上限 20)
```

- **现象二**：D 的"每问题 2 轮"预算靠描述文本里的 `[q:NNNN]` 正则（`agent_d/core.py:900-914`，`re.search(r"\[q:(\d{4})\]", note)`）与 `submitted_by == self.actor` 过滤；描述由 `_search_topic_and_desc` 拼（`core.py:927-934`）。探针确认这条链路当前是通的（`regex findall on desc: ['0000']`、`rows with submitted_by == 'agent-D': 1`）；但同一需求在 `adjudicate` 侧走另一套账（`contradiction_request_ids` 计数，`core.py:980-993`），且那边的 `submitted_by="agent-D:contradiction"`（`adjudicate.py:313`）不落进 `_budget` 的 `mine` 过滤。
- **影响面**：D 这条路径提交的请求数量只受 D 自己算的全局 20 次上限约束，不受共享的在途闸门约束；`specs/c.py:119` 把"C 的缺口要走 `submit_requests=true`"写成政策，而 D 的对口路径没有闸门。
- **是否复现**：探针下稳定复现（26 > 上限 20）；真机上 D 从未走过这条路径（`submitted_by` 无 `agent-D` 行），因此未在真机复现。

### 3.5 【"证据够不够"在多处各判一次】

- **现象**：同一件事（证据是否就绪）有四个入口，其中三个会各自重算一遍：
  1. `assess(qid, evidence)`（`agent_d/assess.py:10`）→ `analyze_gaps`（`_support.py:241`）；
  2. `consider(qid)` 自己先 `trace_question` 再 `assess`（`agent_d/consider.py:24-25`），不足时调 `submit_gaps`；
  3. `submit_gaps(qid)` 又 `trace_question` + `assess` 一遍（`agent_d/submit_gaps.py:28-30`）；
  4. `research(qid)` 再 `trace_question` + `assess`（`agent_d/research.py:29-32`），此外还单独判一次 `l3_needed`（`assess.py:51` 计算、`research.py:33` 使用）。
  另外 `run_round` 逐问题调 `trace_question` + `assess` + `consider`（`run_round.py:55-63`），`consider` 内部再算一次——同一问题一轮内 `trace_question` 至少 2 次、`assess` 至少 2 次。
- **证据**：上面逐条 file:line；`assess` 的返回值里 `sufficient = not insufficient`（`assess.py:51`），`consider` 用 `verdict["sufficient"]`（`consider.py:35`），`submit_gaps` 用 `verdict["insufficient"]`（`submit_gaps.py:30`）——两个互补字段分别被两处读。
- **影响面**：判据本身只有一份（`analyze_gaps`），所以口径不会漂移；漂移的是"这一轮到底判了几次"以及每轮的输入（`trace_question` 每次都重读关系表与概念表）。若两次调用之间表被改动，`consider` 与 `submit_gaps` 可能对同一 `qid` 给出相反结论（前者算"足够"就不会进后者；前者算"不足"则由后者重算，重算结果可能变成"足够"并直接 `return []`，此时 `consider` 的 `promoted=False` 与"证据足够"同时成立）。
- **是否复现**：真机上 D 的这两个动作 0 次调用，未复现；代码路径与调用计数可静态确证（`run_round.py:55-63` + `consider.py:24-25` + `submit_gaps.py:28-30`）。

### 3.6 【C 的 `gaps` 在真机上被"传错参数"拒了一半】

- **现象**：`C.gaps` 的声明参数是 `limit` / `request` / `submit_requests`（`specs/c.py:56`），工具面 `graph.gaps` 只暴露 `limit`（`agent_c/core.py:1011-1017`）。真机 14 次召唤里 7 次被拒。
- **证据**：

```text
('C','gaps','ok') 7 ; ('C','gaps','refused') 7
detail: C.gaps 的参数不合法：出现未声明的参数：['top_n']（schema 只允许 ['limit','request','submit_requests']）
```

  校验点：`conductor.py:1043-1056` 的 `_check_params`（判据唯一来源 `tools.base.validate_params`），`tools/base.py:483` 的拒绝文案。
- **影响面**：一半的 C 关系分析召唤没跑成；拒绝理由本身是行动可读的（列出了合法键）。同一形态在别处也出现：`E.run_experiment` 的 `['imports','name']`（各 7 次）、`H.review` 的 `dependencies` 形状、`H.review_document`（H 没这个动作，各 7 次）。
- **是否复现**：真机已复现（7 个工作区各一条）。

### 3.7 【A 的文献行与文件不在同一原子边界内（潜在半成品）】

- **现象**：`_attach_staged` 在 `store.tx("search_requests","literature")` 之内把文件从 staging 搬到 `library/<lit_id>/`（`run_once.py:132` → `core.py:377-390`），随后才 `tx.upsert("literature", …)`（`run_once.py:164`）。文件系统不在事务里。
- **证据**：`core.py:377-390`（`shutil.move` 在 try 内、无回滚）、`run_once.py:72`（事务边界）、`run_once.py:164`（落行）。
- **影响面**：事务在落行之前失败（schema 校验、锁超时、进程被杀）时，文件已经在新位置，而 `literature` 行没有写；`lit_rows` 里的半成品不会被清理。这是一次"顺序"问题：先落文献行再置请求完成这条纪律（`agent_a/_support.py:12`）保住了请求行，但没有覆盖文件与行之间。
- **是否复现**：未复现。真机 `library/` 目录树的孤儿文件本次没有清点（未核实）。

### 3.8 【D 的报告正文里，置信度措辞由 LLM 措辞决定，只有数字被夹住】

- **现象**：`_llm_refine` 只对 `confidence` 这一个字段做 `_rank_min` 夹取（`agent_d/core.py:1256-1264`），`conclusion` 文本原样采用（`core.py:1152-1156`）；返回值里的 `confidence` 与 `criteria` 又是确定性那份（`research.py:37`、`:72`）。于是同一份产物里，数字是"低"而结论句可以写成高置信度口吻；`_deterministic_compose` 那套"置信度：低 —— 本节的措辞刻意停在『可能存在/尚未证实』"（`core.py:1185-1192`）在 LLM 分支下不生效。
- **证据**：`core.py:1152-1156`（LLM 分支直接返回 `out["conclusion"]`）、`core.py:1256-1264`（只夹 `confidence`）、`schema`/报告层没有对 `conclusion` 文本做口径检查（`write_report.py:298-299` 原样写入）。
- **影响面**：报告里"结论与置信度"一节的措辞强度不受控；提示词层写了"证据不足时正确结论是低置信度与缺口清单，不是把话写圆"（`specs/d.py:178`），但那是提示词而不是代码判据。
- **是否复现**：未复现。真机上 D 的 `research` 0 次调用，且未接 LLM（`llm=None` 路径走 `_deterministic_compose`）。

### 3.9 【`_selftest` 与产物形状（覆盖面偏窄，不是 bug）】

- **现象**：A / B / D 的自检都通过，而 §3.2 那种"写了租约但没人读"的形态在 B 的自检里没有对应断言（A 有）。
- **证据**：`python -B -m agentflow.agent_b` 实测 `19/19 项通过`；`agent_b/core.py:970-978`（第 4 段只断言 `processed is False`）；`agent_a/core.py:592-610`（第 8b 段断言"再领一次领不到、attempts 不增"）。
- **影响面**：B 的租约语义目前没有机器判据守着。
- **是否复现**：不适用（这是覆盖面观察）。

---

## 4. 冗长与可读性观察（只描述读数）

统计命令：`python -B temp/_metrics.py`（`ast` 计函数、按"首非空白字符为 `#`"计注释行），以及 `python -B temp/_dup_claim.py`（结构化比对）。

### 4.1 四目录总量

| 目录 | 文件 | 物理行 | 非空行 | 注释行 | 注释比 | 函数/方法数 |
|---|---|---|---|---|---|---|
| `agent_a/` | 8 | 1422 | 1284 | 183 | 0.129 | 27 |
| `agent_b/` | 11 | 2127 | 1950 | 166 | 0.078 | 48 |
| `agent_c/` | 13 | 3497 | 3273 | 154 | 0.044 | 54 |
| `agent_d/` | 19 | 4413 | 4069 | 265 | 0.060 | 86 |

单文件最大：`agent_d/core.py` 1608 行 / 49 个函数；`agent_d/_support.py` 641 行 / 22 个函数；`agent_c/core.py` 1134 行 / 27 个函数；`agent_b/core.py` 1045 行 / 36 个函数；`agent_c/__main__.py` 584 行 / 11 个函数（自检）。

### 4.2 每目录最长的 5 个函数（行数 + 位置）

`agent_a/`

| 行数 | 位置 | 名字 |
|---|---|---|
| 239 | `core.py:398` | `_selftest` |
| 233 | `run_once.py:10` | `run_once` |
| 161 | `search_literature.py:11` | `search_literature` |
| 131 | `core.py:104` | `_claim` |
| 80 | `ingest_local.py:54` | `ingest_local` |

`agent_b/`

| 行数 | 位置 | 名字 |
|---|---|---|
| 303 | `run_once.py:10` | `run_once` |
| 266 | `core.py:780` | `_selftest` |
| 139 | `register_statement.py:69` | `register_statement` |
| 127 | `core.py:646` | `_apply_merge` |
| 119 | `decide_structural_duplicate.py:10` | `decide_structural_duplicate` |

`agent_c/`

| 行数 | 位置 | 名字 |
|---|---|---|
| 305 | `gaps.py:10` | `gaps` |
| 293 | `paths.py:10` | `paths` |
| 214 | `core.py:916` | `register_tools` |
| 158 | `core.py:541` | `_submit_gap_requests` |
| 153 | `cold.py:10` | `cold` |

`agent_d/`

| 行数 | 位置 | 名字 |
|---|---|---|
| 401 | `write_report.py:10` | `write_report` |
| 380 | `adjudicate.py:10` | `adjudicate` |
| 260 | `core.py:1349` | `_selftest` |
| 218 | `ingest.py:10` | `ingest` |
| 190 | `trace_question.py:10` | `trace_question` |

### 4.3 明显重复的实现

**拆包模板 docstring**：每个动作文件都以同一句话开头——"角色 X 的动作 `name`（`goal-7f5116c1` M6：从 `agent_X.py` 拆出来，逐字未改）"。计数（命令：正则扫这四个目录的 `*.py` 首部）：`agent_a` 3 个（`run.py` / `run_once.py` / `search_literature.py`，`core.py` 与 `ingest_local.py` 用另一种 docstring）、`agent_b` 6 个（`decide_structural_duplicate.py` / `reprocess_once.py` / `resolve_structural_duplicate.py` / `run.py` / `run_once.py` / `run_reprocess.py`）、`agent_c` 9 个（`cold.py` / `contradictions.py` / `gaps.py` / `handle.py` / `hottest.py` / `neighbors.py` / `paths.py` / `relations_between.py` / `structural_duplicates.py`）、`agent_d` 14 个（除 `core.py` / `_support.py` / `__init__.py` / `__main__.py` 之外的每个动作文件）。

**`_claim` 同族三份，判据不同**（`agent_a/core.py:104`、`agent_b/core.py:76`、`agent_b/core.py:237`）。结构化比对（`temp/_dup_claim.py`，去掉 docstring 后 A 39 行 / B 31 行）显示骨架相同（取候选 → 先判租约 → 再判 attempts → 领取并 `upsert` → 四态 `skipped_reason`），差异集中在两处：租约判据（A 只看租约是否过期，B 还要求 `claimed_by` 非空）与放弃后写哪一列（A 写 `done`/`outcome`，B 写 `processed`）。两族的 `skipped_reason` 词表也各一份（A 四态、B 三态，字段名 `request` vs `literature`）。

**租约读写点各写一遍**：A 写租约 `agent_a/core.py:196` 与 `agent_a/run_once.py:205`/`:216`、读租约 `agent_a/core.py:178`；B 写租约 `agent_b/core.py:112`/`:313`、读租约 `agent_b/core.py:97`/`:261`、清租约 `agent_b/run_once.py:53`/`:68`/`:88`。

**规格助手**：`_cfg_get` / `_cfg_int` / `_cfg_float` / `_service_int` 在**整包**里只有一份，落点 `agent_c/_support.py:120` / `:135` / `:157` / `:169`（命令：全包扫描这 4 个 `def`，无第二处）。

**其他样板**：`agent_c/core.py:953-958` 的 `_register` 内部函数 + 9 段 `_register(...)` 调用（`core.py:960-1131`，共 172 行），每段重写一遍 `params` schema 与 `returns` 字符串；四个目录的自检（`agent_c/__main__.py` 584 行、`agent_a/core.py:398` 239 行、`agent_b/core.py:780` 266 行、`agent_d/core.py:1349` 260 行）都是线性 `check(...)` 序列，无共享断言脚手架。

---

## 5. 未核实与缺口

1. **未核实**：`A` 的 `run_once` 任务为什么在 `out/tasks/` 里一个文件都没有。真机事实是 A 的 161 条 `tasks` 行 `artifacts` 全为 `[]`、`out/tasks/*.json` 里 `role=A` 的文件数为 0；A 的任务行全部来自 2026-09-29 那一趟，而 `_write_task_digest` 的当前版本在 `conductor.py:1184`。我没有找到"当前代码下 A 的 run_once 不落摘要"的确定性通路（`ARunResult` 是 dataclass，应当走 `default=str` 的 repr 分支，与 B 的 406 条完全同形）。因此这条只作为读数记录：**B 有摘要、A 没有，差异成因未核实**（可能是那次运行的代码版本没有该功能）。
2. **未核实**：`ingest` 对"没有 `report_id` 的报告对象"的行为。`agent_d/ingest.py:57` 直接读 `info["report_id"]`；`_as_report_dict` 给 `report_id` 的默认值是 `None`（`agent_d/_support.py:151`）。我没有构造一个 `report_id=None` 的真报告去跑，因此"会不会 KeyError / 会不会落一行 report_id=None 的问题"未核实。
3. **未核实**：`projects/*/out/tasks/t-0264.json` 之外，C 的其余动作（`neighbors` / `relations_between` / `structural_duplicates`）在真机上从未被召唤（`tasks.json` 里 0 行），因此这四个 dict 返回形状的动作只有静态阅读，没有真机 payload。
4. **未核实**：`D.propose_question` 在真机 0 次，`research_questions.json` 在 22 个工作区都不存在；因此状态机的真机迁移轨迹（`open → needs_evidence → researching → answered`）本次没有样本，全部结论来自代码与 schema。
5. **未核实**：`library/` 目录树里的孤儿文件（§3.7 的潜在半成品）本次没有清点；`agent_a/core.py:125-130` 记录了同类历史读数（"98 行里留下 60 个空目录"），但没有说文件残留。同样未核实：`fetch` / `providers` 层的失败分档（`content_type_mismatch` 的产生条件）与 A 的 `_stage_download` 降级判据之间的对应关系；`conjectures` 的跨对象不变量在 `verify.verify_all` 里的具体判据（不在本次阅读的五个工具文件范围内）。
6. **缺口**：本报告没有覆盖 E/F/G/H 与 M 的机制，凡涉及它们的地方只作为"A–D 的上下游"记录。
