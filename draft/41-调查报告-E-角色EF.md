# 角色 E / F 实现调查报告

调查对象：`D:\Incubator\agentflow`，包 `agentflow`，源码 `src/agentflow/`。
范围：角色 E（数值实验与形式化验证）与角色 F（多轮难题攻坚）的实现，以及它们用到的判据/常量。
方法：`read` / `grep` / `glob`；`python -B -X utf8 -c` 做 AST 与文本统计、跑只读纯函数探针（`temp/` 下）；读 `projects/*` 与 `agentflow/projects/*` 的台账/会话/产物当真机证据。未跑模型、未跑网络、未跑 pytest、未跑 Lean 编译；除本文件外未改动任何仓库文件。
本报告只描述"是什么"，不含修改建议。每一条结论都带 `file:line` 或命令读数；拿不到证据的写"未核实"。

真机样本：两个工作区根共 76 个 `attack_plans.json` 行、406 条 `experiments` 行、124 个 `sessions/*.jsonl`。命令：`python -B -X utf8 -c "…glob('projects/*/data/experiments.json')…"`（合计见 §3.1）。

---

## 1. 机制

### 1.1 E：一次 `run_experiment` 的完整路径

入口 `AgentE.run_experiment`（`src/agentflow/agent_e/run_experiment.py:10`）。

**第一步：参数校验（全在起子进程之前，均抛 `ExperimentError`）**

| 判据 | 位置 | 拒绝形态 |
|---|---|---|
| `claim` / `claim_key` 非空 | `run_experiment.py:68-71` | `claim 不能为空` |
| `method ∈ schema.EXPERIMENT_METHODS`（`numeric/symbolic/exhaustive_search/formal`） | `run_experiment.py:72`，词表 `schema.py:864` | `method 必须是 … 之一` |
| `certificate` / `search_bound` 只对 `exhaustive_search` 有效 | `run_experiment.py:83-89` | `只对穷举/枚举类方法有效` |
| `name` / `imports` 只对 `formal` 有效 | `run_experiment.py:90-95` | `name / imports 只对 method='formal' 有效` |

注意这里**没有**校验"`exhaustive_search` 必须给 `certificate`"，也没有校验 `for_question_id` 的形状——这两条只在 `S.Experiment.validate()` 里（`schema.py:1136`、`schema.py:1185`），而 validate 发生在子进程跑完之后（见 B2）。

**第二步：路径与哈希**：`self._resolve(script_path)`（`agent_e/core.py:116-133`）把路径解析进工作区，越界即抛；`path.is_file()` 不存在即抛（`run_experiment.py:99`）；`VT.code_hash(path)` 取 sha256 前 16 位（`tools/verify_tools.py:79-93`）。

**第三步：`method="formal"` 分流**到 `_record_formal`（`run_experiment.py:109-120`），见 1.1.4。

**第四步：起子进程** `_run_script`（`agent_e/core.py:158-275`）

- 命令行按后缀构造：`.py` ⇒ `[self.python, path]`（默认 `sys.executable`，`core.py:91`、`core.py:145-152`）；`.ps1` ⇒ `pwsh -NoProfile -NonInteractive -File`；未知后缀抛（不猜）。
- `subprocess.Popen(..., cwd=workspace_root, stdout=PIPE, stderr=PIPE, text=True, encoding='utf-8', errors='replace')`，环境补 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`（`core.py:167-186`）。
- `OSError`（解释器不存在等）⇒ 返回 `launch_error` 且 `exit_code=None`，不当成"跑失败"（`core.py:187-196`）。
- 进程树治理：Windows 上装作业对象 `jobobject.create_job` + `assign_tree`；装不上就退回 `_kill_child`（`core.py:206-214`、`agentflow/jobobject.py:140/259/307`）。
- 等待循环用 `proc.communicate(timeout=0.2)` 轮询（`core.py:218-223`），每 0.2 s 判两件事：
  - `.agentflow-stop` 落盘（`_stop_requested`，`_support.py:192-204`；文件名 `stopctl.STOP_FILE_NAME`，`stopctl.py:51`）⇒ `grace_then_kill` / `_kill_child`，返回 `stopped_by_user=True`、`timed_out=False`（`core.py:224-237`、`core.py:255-266`）；
  - 墙钟超过 `limit` ⇒ 杀进程，返回 `timed_out=True`、`exit_code=None`，stderr 追加 `[超时] 超过 timeout=…s，进程已被杀掉`（`core.py:238-251`）。
- 生效超时 = `timeout if timeout is not None else self.default_timeout`（`run_experiment.py:123`），`default_timeout` 取 `cfg["timeout"]` 缺省 600（`core.py:84`）；另有 `timeout_cap` 声明但 `grep timeout_cap` 只有 `core.py:87` 一处定义、无消费者。
- 正常结束返回 `{exit_code, stdout, stderr, runtime_sec, timed_out, launch_error, process_tree}`（`core.py:267-275`）。

**第五步：stdout ⇒ `result` / `search_bound`**（`_derive`，`_support.py:486-589`）

三条规则（模块 docstring `_support.py:35-57` 与实现同处一份）：

1. `exit_code is None or != 0` ⇒ `inconclusive` + `no_local_evidence` + `heuristic`；仍从 `PROGRESS:` 行取进度读数放进 `observations`（`_support.py:501-517`）。
2. 解析 `REPRO_RESULT` —— 两种形态：行首 `REPRO_RESULT: {json}`（`_extract_stdout_lines`，`_support.py:340-351`）；容错形态 `{"REPRO_RESULT": {…}}`（`_json_key_form` 花括号配对，`_support.py:295-337`）。`_extract_conclusion` 汇总（`_support.py:354-372`）：**两种形态同时出现或多于一行 ⇒ 视为格式非法**，不替脚本挑一个。
3. 没有那行 / JSON 坏了 / `result` 不在词表 ⇒ 一律 `inconclusive` + `no_local_evidence` + `heuristic`，并把"是哪一种"写进 notes（`_parse_conclusion`，`_support.py:374-416`）。

`REPRO_RESULT` 各字段的要求与缺失后果：

| 字段 | 要求 | 缺了会怎样 | 位置 |
|---|---|---|---|
| `result` | ∈ `('supports','refutes','inconclusive')`（`schema.py:879`） | 整条结论不认，落 `inconclusive/heuristic` | `_support.py:409-415` |
| `counterexample` | `result="refutes"` 时必须非空对象 | **抛 `ExperimentError`**（带两条改法），不落行 | `_support.py:536-558` |
| `evidence_kind` | ∈ `EVIDENCE_KINDS`（`schema.py:876`） | 不在词表 ⇒ 降级 `heuristic` 并记 notes | `_support.py:427-431` |
| `bound` | Mapping | 非 Mapping ⇒ **静默丢弃**，只留 D38 note（且那句 note 说"没有 bound"，见 B16） | `_support.py:459-461` |
| `strategy` | 非空字符串 | 空/空白 ⇒ 静默丢弃 | `_support.py:467-469` |
| `scaling` | 序列（取前 40 条） | 非序列 ⇒ 静默丢弃 | `_support.py:462-466` |
| `data` | Mapping，原样留下（D39） | 非 Mapping ⇒ 静默丢弃 | `_support.py:592-605` |

`search_bound` 的来源优先级（`run_experiment.py:194-199`）：调用方显式给 > 脚本在 `REPRO_RESULT` 里自报的 `bound`（经 `observations["bound"]`）> 无。

**第五步半：两条"只说话不判定"的注记**：`_progress_note`（`run_experiment.py:221-274`）按 `claim_key` 取历史行、比"界/策略/耗时/脚本"；`_reused_evidence_note`（`run_experiment.py:276-308`）在"同脚本 + 同 `data`、不同 `claim_key`"时点名。

**第六步：一个事务落库**（`run_experiment.py:165-202`）：`tx.alloc_id("experiment")` → 写产物 `out/experiments/<eid>.log`（`_write_run_log`，`_support.py:682-705`；写不了只记 notes、照旧落行）→ `build_experiment(...)` → `row.validate()`（`_support.py:680`）→ `tx.upsert`。`tx` 是 contextmanager：事务体抛异常则**整笔不落盘**（`store.py:890-1008`）。

**各 method 的要求**

| method | 要求 | 证据等级 |
|---|---|---|
| `numeric` / `symbolic` | 无附加参数；传 `certificate`/`search_bound`/`name`/`imports` 均被拒 | 一律 `cross_check`（脚本自报 proof 会降级） |
| `exhaustive_search` | 传 `certificate`；`certificate` 非空则必须给 `search_bound`（`schema.py:1136`、`schema.py:1142-1149`） | 同上 |
| `formal` | 产物必须是 `.lean`（`agent_e/core.py:309-317`）；`name` 不给时从源码认唯一的具名声明（`core.py:320-336`、`formalgw.py:852-872`） | 只有检查器 `verified` 才是 `proof` |

真机核对（两工作区根合计 406 行）：`exhaustive_search` 24 行，其中 24 行有 `certificate`；`certificate` 非空而无 `search_bound` 的行 **0 条**。`search_bound` 非空的 74 行中 62 行的 `observations.bound` 存在（即来自脚本自报），12 行来自调用方显式传参。

**"脚本自报 proof 一律降级"落在哪一行**：`agent_e/_support.py:432-438`（`if kind == "proof" and method != "formal":` ⇒ 记 notes 并返回 `cross_check`）。运行期那一半在这里，写入期那一半在 `schema.py:1101`（`method != "formal"` 且 `evidence_kind == "proof"` 直接抛）。离线探针确认：`_derive(0, 'REPRO_RESULT: {"result":"supports","evidence_kind":"proof",…}', "numeric")` ⇒ `evidence_kind=cross_check`，notes 含"拒绝并降级为 cross_check"。

**真机读数（B1 的底数）**：406 行里 `inconclusive` 203 行 = 50.0%。分类：无 `REPRO_RESULT` 行（脚本 exit=0 却不说协议）82；formal 未通过/未查成 45；超时 28；非零退出 12；脚本自己说 `inconclusive`（带 `cross_check`）32；`result` 不在词表 2；多行 1；坏 JSON 1。

### 1.1.4 形式化那条路

`AgentE.check_formal`（`agent_e/check_formal.py:10-121`）只做三件事：路径守卫、转发 `VT.check_formal`、`reason` 收口 + `verifier_status` 透传。

- 路径守卫：越界 ⇒ `_formal_refusal(claim, "path_outside_workspace", …)`，即 `checked=False, verified=None`（`check_formal.py:80-86`、`_formal_refusal` 在 `agent_e/core.py:442-481`）。
- 工具层失败（`res.ok` 为假）⇒ `reason="tool_failed"`，种类放 `detail`（`check_formal.py:106-115`）。
- 收口：`_FORMAL_REASON_BY_TOOL_REASON`（`_support.py:170-182`）表外的值落 `status_unregistered`；原值逐字进 `verifier_status`（`check_formal.py:117-120`）。

**可达的返回码**（比"七种"多，逐值可判）：

- 工具层 `tools/verify_tools.py:124` 自己产生的 `reason`：`tool_crashed`（探测没做成，`:332`）、`no_backend`（探测完成、无后端，`:350`）、`no_script`（有后端但既没 `source` 也没 `script_path`，`:368`），以及成功分支透传的 `formalgw.STATUSES` 十值（`:461`）。参数非法与桥接层异常走 `fail(kind="param_error"/"check_failed")`（`:434`、`:437-443`），`data` 为 `None`。
- `formalgw.STATUSES`（`formalgw.py:127-138`）：`verified` / `compile_error` / `uses_sorry` / `extra_axioms` / `decl_mismatch` / `timeout` / `import_unavailable` / `no_backend` / `tool_crashed` / `source_unreadable`。
- E 层追加：`path_outside_workspace`、`tool_failed`、`status_unregistered`。局部受控词表 `FORMAL_REASONS` 共 15 值（`_support.py:153-169`），导入期断言保证 `formalgw.STATUSES ⊆ 映射表`（`_support.py:183-187`）与 `_NOT_CHECKED_REASONS ⊆ FORMAL_REASONS`（`_support.py:188-191`）。

**各状态的含义与三态位**（判据顺序在 `formalgw.py:45-65` 的 docstring，实现按序落点）：

| status | checked/proved | 含义 | 判定落点 |
|---|---|---|---|
| `verified` | True/True | 唯一算证明的状态 | `formalgw.py:1482` |
| `compile_error` | True/False | 查了，精化失败 | `:1446` |
| `uses_sorry` | True/False | 静态扫到 `sorry`/`admit`，或公理表出现 `sorryAx` | `:1348`、`:1440` |
| `extra_axioms` | True/False | 公理超出 `ALLOWED_AXIOMS`（`propext`/`Classical.choice`/`Quot.sound`） | `:1467-1473` |
| `decl_mismatch` | True/False | 源码里没有那条声明（静态），或退出码 0 但输出里没见到那个名字 | `:1342`、`:1476` |
| `timeout` | False/None | 没查完（不是证伪） | `:1415` |
| `import_unavailable` | False/None | 检查器回 `error: unknown package 'X'` ⇒ 编译根本没开始 | `:1421-1439` |
| `no_backend` | False/None | 可判定地没有后端 | `:1312`、`:1374` |
| `tool_crashed` | False/None | 探测失败 / 桥接层异常 / 被取消（`G-1`） | `:1314`、`:1382`、`:1409` |
| `source_unreadable` | False/None | `source_path` 给的源码读不到 | `:1327-1333` |

`checked` 的定义只有一处：`_CONCLUDED_STATUSES = ("verified","compile_error","uses_sorry","extra_axioms","decl_mismatch")`（`formalgw.py:196-197`、`evidence_of` `:1142-1173`）；`import_unavailable` 与 `source_unreadable` 刻意不在这一组。真机读数：80 条 formal 行里 `evidence_kind=proof` 的 35 条（`verifier_status=verified`），其余 45 条的 `verifier_status` 有 `compile_error`（`p8g` 0002/0003/0004 逐字是 `compile_error` + 检查器原话）、`decl_mismatch`（`D:\Incubator\projects` 下 4 条，声明名如 `paper_theorem_lemma_audit_L0` 在源码里不存在）等。

**试错预算的落点**：E/F 的代码里**没有**任何"同一命题最多试几次"的计数器或上限——`grep` 全仓，`最多连试 3 次` 只出现在提示词/声明层（`specs/e.py:171`、`specs/m.py:61`）。机器侧最接近的是 M 循环的"同一条路 + 同一类读数"连击读数 `stalled_max`（`agent_loop.py:1730-1739`，阈值 `stall_nudge=3` / `stall_alert=6`，`agent_loop.py:1276-1277`）与连续坏 JSON 的 `bad_json_limit`。E 自己接受无限次重复：真机读数（`specs/e.py:171` 与 `agent_prompts.py:763` 逐字记录）同一个 `check_formal` 命题被连试 19 次。

### 1.2 F：一次 `step` 的完整路径

入口 `AgentF.step(plan_id)`（`agent_f/step.py:10-288`）。

1. **读计划**：`_plan_row`（`agent_f/core.py:173-177`）。不在册 ⇒ `PlanError`，且把在册的 `plan_id`+`problem_key`+`status` 列出来（`step.py:37-53`）。
2. **终态不再推进**：`status ∈ TERMINAL_STATUSES`（`agent_f/_support.py:92` = `schema.ATTACK_TERMINAL_STATUSES`）⇒ 返回 `action="stop"`（`step.py:60-75`）。
3. **提前停止检测**：最近 `stall_after_no_progress_rounds`（缺省 3，`step.py:88`）条 history 的 `outcome` 全为 `no_change` ⇒ `status="stalled"` + `best_partial="[提前停止] …"` 并写回（`step.py:90-114`）。
4. **轮数用尽**：`AT.can_round(budget, rounds_done=rounds, depth=0)`（`step.py:120`，`tools/attack_tools.py:138`）⇒ `stalled` + `best_partial="[停止] 轮数已用尽…"`；只有 `len(history) < max_rounds × max(1, len(subgoals))` 时才追加那条 `action="stop"` 记录（`step.py:133-145`，上限与 schema 差 1，见 B18）。
5. **选子目标**：先摘掉 `in_flight` 的，再 `AT.pick_next_subgoal`（`step.py:170-171`，`attack_tools.py:245-274`，次序 `in_progress` > `todo` > `blocked`）。无可选 ⇒ 追加一条 `action="stop", outcome="no_change"` 的 history、`rounds += 1`、`status=_derive_status(...)` 后写回（`step.py:172-202`）。
6. **分派** `_deploy`（`agent_f/core.py:265-337`）按 `owner`：
   - `E` ⇒ `_deploy_e`（`core.py:514-657`）：先幂等（`experiment_ids`/`proof_experiment_ids` 非空 ⇒ `no_change`，`:523-535`）；没有 `script_path` ⇒ `no_change` + `status="todo"`（`:537-551`）；E 不可用 ⇒ 显式 `no_change` + `blocked_reason`（`:553-567`）；调 `agent_e.run_experiment`，异常降级为 `outcome="blocked"`（`:596-609`）；结果分三支：`evidence_kind="proof"` ⇒ `closed`（`:613-628`）、`result="supports"` ⇒ `supported_not_proved`（`:629-643`）、其余 ⇒ `no_change` + `in_progress`（`:644-657`）。
   - `A` ⇒ `_deploy_a`（`core.py:658-736`）：同一事务内过 `IX.admit_search_request`，被拒零写入；放行则取号 `next_prefixed_id(rows,"request_id","r")` 写 `search_requests`。
   - `B` ⇒ `_deploy_b`（`core.py:737-802`）：同形，过 `IX.admit_reprocess_request`。
   - `C`/`D`/`F`（`UNWIRED_OWNERS`，`_support.py:93`）：`self.llm is not None` ⇒ `_reason_self`；否则落 `dead_end(缺工具)` 并记"未接线"（`core.py:282-333`）。
7. **写回**（`agent_f/core.py:449-512` 的 `_apply_round` 产出 → `step.py:211-275`）：合并 `experiment_ids`/`proof_experiment_ids`/`evidence_ids`/`negation_kind`/`status`/`blocked_reason`/`in_flight`，`attempts += 1 if count_attempt`，挂新子目标（`step.py:236-237`），追加 history 行（`step.py:239-266`，带 `product` / `product_detail` / `strategy` / `best_partial` / `dead_end_reason`），`rounds += 1`，`_derive_status`，`_compose_best_partial`，`_write_plan`（`core.py:857-875`，写前 `validate()`，失败换 `PlanError` 且不写）。

**花钱前的闸门（I9）**：`_reason_self` 先调 `AR.pre_spend_gate(goal, testable, tried_strategies, budget_left_usd)`（`core.py:375-376`，实现 `attackround.py:197-228`）。判据四条：`goal` 非空；`testable` 非空；`deps_refuted` 为空；未试满全部 9 招；另可选 `budget_left_usd > 0`。

`testable` 缺失时的走法：`gate["spend"] is False` ⇒ `_self_dead_end(..., reason="缺定义", evidence="花钱之前的闸门没过：…", blocked_reason="；".join(gate["reasons"]))`（`core.py:377-384`），即**不发模型调用**，产物是 `dead_end`，`status="blocked"`，`in_flight=True`，`count_attempt=True`。`testable` 只做 `str(...)` 非空判断（`attackround.py:211`），所以 dict 形态的 `testable` 也算"有"（离线探针：`testable={"criterion":"c"}` ⇒ `spend=True`）。
真机读数：7 个子目标的 `blocked_reason` 逐字是"子目标没有可检验形式（`testable` 空）⇒ 先落 `needs_evidence` 并写清为什么"（`p6p` 3 / `p6q` 2 / `p6r` 2），这 7 条对应的计划都在第 3 轮被提前判 `stalled`。

第二道闸 `AR.budget_decision`（`core.py:385-393`，`attackround.py:231-246`）：`round_cost_usd` 缺省 0.02、`round_cost_cap_usd` 缺省 None（⇒ `unbounded`），`too_large` ⇒ `dead_end(超出本轮预算)`。

**模型调用的输入输出形状**

- 提示词 `_attack_prompt`（`agent_f/core.py:37-82`）：受控值现取 `attackround`——四档产物名、9 招 `STRATEGIES`（`attackround.py:44-47`）、7 个 `DEAD_END_REASONS`（`:53-55`）、禁用标记（`:49-51`）。提示词要求"只输出一个 JSON 对象"。
- 缝协议 `J.judge_json(self.llm, prompt, point="F.step")`（`core.py:396`，`judge.py:67`）：有 `ask_json` 就用它（`judge.py:88-104`），否则回落 `complete(prompt)`（`:105-124`）。真机缝 `llmseam.LlmSeam.ask_json(prompt, *, system, task_id, note, max_tokens) -> (dict|None, SeamCall)`（`llmseam.py:370-394`），坏 JSON 归 `judge_bad_json` 并把解析原话与诊断写进 `detail`。
- 成形判据 `AR.parse_round`（`attackround.py:64-152`）四档必填字段：

| 产物 | 必填 | 校验 |
|---|---|---|
| 公共 | `product` ∈ 四档、`strategy` ∈ 9 招、`why_strategy` 非空 | `:86-95`；出现 `no_change` 三字直接打回（`:81-85`） |
| `reduction` | `new_subgoals` 1–3 条，每条 `{goal, testable}` 都非空 | `:97-112` |
| `proof` | `steps` 非空；每步 `text` 非空，且 `cites` 非空或 `assumption: true`；`text` 命中禁用词而没声明成前提 ⇒ 打回 | `:113-117`、`_clean_step` `:155-177` |
| `counterexample_request` | `script_spec.{criterion,params,expected_bound}` 三项非空 + `why_it_decides` 非空 | `:118-129` |
| `dead_end` | `reason` ∈ 7 个受控值、`evidence` 非空、`best_partial` 非空数组（每项要有 `what`） | `:130-151` |

`_apply_round`（`core.py:449-512`）把产物写成：

| 产物 | action/outcome | 子目标状态 | 新子目标 | evidence |
|---|---|---|---|---|
| `reduction` | `reduction` / `progress` | `in_progress` | 每条 `new_subgoals` 一条，`sid` 由 `_next_sid` 发（`core.py:342-352`），`owner` 继承父目标 | 新 sid 列表进 history 的 `evidence` |
| `proof` | `proof` / `progress` | `in_progress`（不许 `closed`） | 无 | 空 |
| `counterexample_request` | `counterexample_request` / `progress` | `in_progress` | 一条 `owner="E"`，`testable=expected_bound` | 新 sid |
| `dead_end` | `dead_end` / `no_change` | `blocked` + `in_flight` | 无 | 空；`blocked_reason` = 产物的 `evidence` |

**预算与轮次怎么算**：`rounds` 每调一次 `step` 就 +1（含"无可选子目标"与"轮数用尽"这两条只写 stop 行的路径，`step.py:188`、`step.py:269`）；硬闸只有 `budget.max_rounds`（`can_round`，`attack_tools.py:166-174`）。`budget_left` 由 `_budget_left` 计算（`_support.py:164-171`），它把 `max_parallel_subgoals` / `max_persist_attempts` / `max_depth` **原值**当"余量"回报。`max_parallel_subgoals`、`max_persist_attempts` 与 `_Core.max_subgoals_per_round`（`core.py:110`）全仓无消费者（`grep` 只有定义与 schema 的必填校验）。

**`dead_end` 的受控理由**：`DEAD_END_REASONS` 七值（`attackround.py:53-55`：`反例`/`方法不适用`/`缺定义`/`缺文献`/`缺工具`/`超出本轮预算`/`需要先证别的命题`）。四处产生者：模型产物（`parse_round`）、`_self_dead_end`（闸门与预算两支，`core.py:428-447`）、未接线 owner（`core.py:295-333`，`reason="缺工具"`）。

**`best_partial` 怎么生成**：`_compose_best_partial`（`core.py:822-856`）把每个子目标的 `sid/owner/status/text` 加 `proof_experiment_ids`（或 `experiment_ids` 并注明"仅交叉验证"）、`evidence_ids`、`blocked_reason` 逐条列出，按"离终结有多近"排序（`closed` 0 … `blocked` 4），末尾固定一句"以上均为过程记录"。全空时用 `NO_PROGRESS_NOTE`（`_support.py:123`）。`dead_end` 产物里的 `best_partial` 另由 `_unwired_partial`（`core.py:241-263`）从子目标现有读数取；完全没读数时会写一条"子目标原文…这一条是原文本身，不是进展"。

**`judge_json` 的三态码在真机出现过哪些**（`glob('*/sessions/*.jsonl')` + 正则统计，124 个会话文件）：`judge_bad_json` 88 次、`judge_failed:AttributeError` 12 次、`judge_bad_args` 1 次；`judge_not_wired` / `judge_timeout` / `judge_over_budget` / `judge_refused` 在这批会话里 **0 次**。其中 F 侧的读数落成子目标的 `blocked_reason`，逐字是"LLM 判定没查成（判断点 F.step）：judge_failed:AttributeError"，共 6 个子目标（`p8b` 2 / `p8c` 2 / `p8d` 2）。`out/invalid/*.txt` 现存 11 个文件（如 `projects/p8b-fermat-shorter-proof/out/invalid/t5b-step21.txt`），内容都是 M 循环那一层的原始回复，不是 F 的。

---

## 2. 关键文件与函数表

### 2.1 E

| file:line | 职责 |
|---|---|
| `agent_e/core.py:55` `_Core` | E 的装配：阈值（`timeout` 600 / `timeout_cap` / `python` / `allowed_suffixes`）、工作区、工具栏绑定 |
| `agent_e/core.py:116` `_Core._resolve` | 把脚本路径解析进工作区，越界即抛（E 唯一的"外部输入→执行"闸） |
| `agent_e/core.py:158` `_run_script` | 起子进程、作业对象、停机开关轮询、超时杀进程、返回四个读数 |
| `agent_e/core.py:276` `_record_formal` | 形式化路径：认声明名 → 调 `check_formal` → 只有 `verified` 落 `proof` 行 |
| `agent_e/core.py:16` `_mathlib_remedy_note` | 只在 `compile_error` + 本机 Mathlib 可用 + 本次没传 imports 时才说"忘记传库" |
| `agent_e/core.py:442` `_formal_refusal` | `check_formal` 受控拒绝形态（八键、`verified=None`） |
| `agent_e/core.py:500` `selftest` | 12 段离线自检（含负控：脚本自报 proof、崩溃、越界、超时、非 `.lean`） |
| `agent_e/run_experiment.py:10` `run_experiment` | 参数闸 → 路径/hash → 分流 → 跑 → 推导 → 事务落库 |
| `agent_e/run_experiment.py:221` `_progress_note` | 与同 `claim_key` 历史比"界/策略/耗时/脚本"，没推进就明说"同形" |
| `agent_e/run_experiment.py:276` `_reused_evidence_note` | 同脚本 + 同 `data` + 不同 `claim_key` ⇒ 点名"同一份证据" |
| `agent_e/check_formal.py:10` `check_formal` | 路径守卫 + 转发工具层 + `reason` 收口 / `verifier_status` 透传 |
| `agent_e/_support.py:139` | `REPRO_RESULT_PREFIX="REPRO_RESULT:"`；`:142` `PROGRESS_PREFIX` |
| `agent_e/_support.py:486` `_derive` | 三条推导规则的唯一实现 |
| `agent_e/_support.py:417` `_normalize_evidence_kind` | 脚本自报等级归一 + proof 降级（FC-22 运行期那一半） |
| `agent_e/_support.py:440` `_search_facts` | 从结论/PROGRESS 行取 `bound`/`scaling`/`strategy`/`progress` |
| `agent_e/_support.py:606` `build_experiment` | 纯装配 + `row.validate()`（不吞异常） |
| `agent_e/_support.py:682` `_write_run_log` | 原始输出落 `out/experiments/<eid>.log`，失败只返回原因 |
| `agent_e/_support.py:706` `_result_reason` / `:724` `_formal_status_suffix` | 列表页的一句话解释（含检查器状态） |
| `agent_e/evidence_for.py:10` / `list_experiments.py:10` / `run_script_experiment.py:10` | 三个薄封装（转发 `verify_tools` / 别名） |
| `tools/verify_tools.py:79` `code_hash` | sha256 前 16 位 |
| `tools/verify_tools.py:124` `check_formal` | 探测三态 + 转发 `formalgw.check_lean` + 八键返回 |
| `tools/verify_tools.py:499` `evidence_for` | 三态证据查询（`proved` 也是三态） |
| `tools/verify_tools.py:1080` `_run_experiment_tool` | 把 `ExperimentError`/`ValueError`/`OSError` 折成四种 `kind` |
| `formalgw.py:1181` `check_lean` | "什么算证明"的唯一定义处（判据顺序见其 docstring） |
| `formalgw.py:1142` `evidence_of` | `checked`/`proved`/`evidence_kind` 的唯一算法 |
| `jobobject.py:140/259/273/307` | 作业对象：建 / 装整棵树 / 宽限后强杀 / 关句柄 |

### 2.2 F

| file:line | 职责 |
|---|---|
| `agent_f/step.py:10` `step` | 读计划 → 终态/停滞/轮数闸 → 选目标 → 分派 → 写回 |
| `agent_f/core.py:26` `set_default_llm` / `:32` `default_llm` | 进程级"工具层构造 F 时用哪个缝"（D42c） |
| `agent_f/core.py:37` `_attack_prompt` | 一轮的提示词（受控值全部现取 `attackround`） |
| `agent_f/core.py:86` `_Core.__init__` | F 的装配（`max_subgoals_per_round` / `search_mode` / `submitter` / 惰性 E） |
| `agent_f/core.py:195` `_normalize_subgoal` | 子目标形状归一（缺 `sid`/`text`/`owner` 当场抛） |
| `agent_f/core.py:265` `_deploy` | 按 owner 分派；未接线 owner 落 `dead_end(缺工具)` |
| `agent_f/core.py:342` `_next_sid` | 发新子目标号（避免模型给重复 `s1`） |
| `agent_f/core.py:354` `_reason_self` | I9 闸门 → I16 预算 → `judge_json` → `parse_round` → `_apply_round` |
| `agent_f/core.py:428` `_self_dead_end` | 闸门/预算失败时落受控 `dead_end` 产物 |
| `agent_f/core.py:449` `_apply_round` | 四档产物 → action/状态/新子目标/evidence |
| `agent_f/core.py:514/658/737` `_deploy_e/_deploy_a/_deploy_b` | 三条已接线分派（E 实验、A 检索、B 重抽取） |
| `agent_f/core.py:803` `_derive_status` | 计划状态推导（FC-22：无数值关闭、无 proof 不给 resolved） |
| `agent_f/core.py:822` `_compose_best_partial` | 计划级 `best_partial` 合成 |
| `agent_f/core.py:857` `_write_plan` | 校验后一个事务写回；schema 失败换 `PlanError` |
| `agent_f/create_plan.py:11` `create_plan` | 预算完整闸 + 同 `problem_key` 去重 + 写前 validate |
| `agent_f/status.py:10` `status` | 只读视图（子目标计数、`stale_blocked`、`last_touched_*`） |
| `agent_f/_support.py:101` `STEP_OUTCOMES` / `:107` `_step_outcome` | 一轮 outcome 的受控词表与收口 |
| `attackround.py:64` `parse_round` | 四档产物的唯一成形判据 |
| `attackround.py:155` `_clean_step` | 一步步证明的规范化 + 禁用词 + "有依据"判据 |
| `attackround.py:197` `pre_spend_gate` | I9 确定性闸门 |
| `attackround.py:231` `budget_decision` | I16 超上限显式阻塞 |
| `attackround.py:257` `dead_end_row` | 走同一套判据造 `dead_end` |
| `judge.py:67` `judge_json` | 唯一缝协议（`ask_json` 优先，`complete` 回落；失败落受控码） |
| `judge.py:38` `JUDGE_PROBLEMS` / `:57` `is_judge_problem` | 失败码词表与识别（含 `judge_failed:<类名>`） |

---

## 3. 可疑的逻辑 bug

### B1 `experiments` 的 `inconclusive` 长期占一半，主因是脚本不说协议

- 现象：两工作区根合计 406 行里 203 行 `inconclusive`（50.0%）。分类：无 `REPRO_RESULT` 行 82、formal 未通过/未查成 45、超时 28、非零退出 12、脚本自报 `inconclusive`（带 `cross_check`）32、`result` 不在词表 2、多行 1、坏 JSON 1。`D:\Incubator\projects` 那 189 行里 65 行 `inconclusive`（34%），58 行是"exit_code=0 但 stdout 没有 `REPRO_RESULT` 行"。
- 证据：命令 `python -B -X utf8 -c "…406 行交叉表…"` 输出 `inconclusive total: 203 = 50.0%`；`projects/p5-polish-20261001-234839/data/experiments.json` 5 行全 `inconclusive`，notes 逐字是"脚本未给出结构化结论（stdout 里没有 REPRO_RESULT 行）"（2 行）、"脚本打印了 10 行 REPRO_RESULT（多于一行）"、"REPRO_RESULT 行不是合法 JSON"、"REPRO_RESULT.result=None 不在受控词表"。代码落点：`agent_e/_support.py:383-416`（没有那行就整条不认）、`_support.py:392-397`（多于一行即拒）。
- 影响面：这些行的 `result` 是 `inconclusive`，但脚本其实跑出过 9 PASS / 1 FAIL 这类读数（同上 p5 的 stdout）；稿子只能引 `heuristic` 级断言，M 的收工门 `search_frontier_rows`（`closing.py:1072-1078`）也数不到东西。协议是"全有或全无"：脚本只要不打那一行，无论跑了多久，台账上只有一个"没有结论"。
- 是否复现：真机读数已复现（406 行统计）；解析器本身可用纯函数探针逐条复现（`_parse_conclusion` 对五种输入的返回见 §1.1）。

### B2 昂贵的子进程跑完之后才做 schema 校验：52 次失败、110.7 分钟、0 行、日志被覆盖

- 现象：`method="exhaustive_search"` 不给 `certificate`、`certificate` 形状不对、`certificate` 有了但没给 `search_bound`、`for_question_id` 不是 4 位数字——这四类**只在 `S.Experiment.validate()` 里判**（`schema.py:1136-1149`、`:1143`、`:1185`），而 validate 在 `run_experiment.py:180` 的 `build_experiment` 内、即子进程与 `_write_run_log` 之后执行。
- 证据：命令统计 `*/data/tasks.json` 里 `role=E, action=run_experiment, status=failed` ⇒ **52 次、合计 6643 秒 = 110.7 分钟**（`p6m` 70.1 分钟、`p6i` 30.0 分钟）；按错误分类 32 次是"必须给出 certificate"、17 次"certificate 必须是对象且含 kind"、2 次 `for_question_id 必须是 4 位十进制字符串，收到 'q-0001'`、1 次"给了 certificate 就必须给 search_bound"。`p6m-research-from-zero/data/tasks.json` 里 t-0015 的 `started_at=2026-10-06T02:25:35`、`ended_at=02:35:36`（601 秒）后报 `ValueError: 给了 certificate 就必须给 search_bound`；t-0009 是 600 秒、t-0012/t-0013 各 901 秒。这些 run 的 `experiments` 行 **0 条**，`counters.json` 里 `experiment` 计数只等于已提交的 5 条。
- 影响面：`out/experiments/<eid>.log`（`_write_run_log` 在事务内、`build_experiment` 之前，`run_experiment.py:171-177`）已经落盘，但行没提交。我用纯函数探针在同一 `Store` 上复现了完整链条：第一次"模拟 build_experiment 抛" ⇒ `rows=0 counters={}` 而 `0000.log` 已写好；第二次同样的调用重新拿到 `0000`、**把第一次的原始输出覆盖掉**（`0000.log` 里只剩第二次的内容）。工具层的失败文案写的是"（**没有落库**）"（`tools/verify_tools.py:1117`），与"盘上没有产物"是两件事，而这句话没有区分。
- 是否复现：是（真机 + 探针，探针脚本在 `temp/` 下临时目录运行，未改仓库）。

### B3 `observations.bound` 是标量时 `dict(...)` 抛 `TypeError`，落成 `kind="unexpected"`

- 现象：`run_experiment.py:197-199` 用 `dict((derived.get("observations") or {}).get("bound") or {})` 取 `search_bound`。脚本若在 `observations` 里把 `bound` 写成数字，`dict(42)` 抛 `TypeError: 'int' object is not iterable`。
- 证据：纯函数探针：`_derive(0, 'REPRO_RESULT: {"result":"supports","observations":{"bound":42}}', "numeric")` ⇒ `observations` 里 `bound=42`；把同一表达式单独跑 ⇒ `PROBE: dict(observations[bound]) raised TypeError 'int' object is not iterable`。工具层的捕获表只有 `ToolError` / `ValueError` / `RuntimeError` / `OSError`（`tools/verify_tools.py:1113-1134`），`TypeError` 逃到 `ToolRegistry.call` 的 `except Exception` ⇒ `kind="unexpected"`（`tools/base.py:1434-1435`）。
- 影响面：这正是 `_run_experiment_tool` 的 docstring 要避免的形态（"脚本路径越界"与"工具层有 bug"看起来一样）；同时它也在 `_write_run_log` 之后，所以同样留下孤儿日志（同 B2）。注意顶层 `bound: 42`（不在 `observations` 里）不会触发——它被 `_search_facts` 静默丢弃（见 B16）。
- 是否复现：是（探针，纯函数 + 表达式两级）。

### B4 超时分支不关作业对象句柄，且 `_run_script` 三条返回三套键

- 现象：`_JO.close(job)` 只在 `core.py:252-254` 一处，而超时分支在 `core.py:244-251` 直接 `return`，跳过了它；三处返回的键集合互不相同：正常结束有 `process_tree`，用户叫停多一个 `stopped_by_user` 与 `process_tree`，超时与启动失败都没有 `process_tree`。
- 证据：`agent_e/core.py:187-196`（启动失败：6 键）、`:238-251`（超时：6 键，无 `process_tree`）、`:255-266`（叫停：8 键）、`:267-275`（正常：7 键）；`grep -n "_JO\." agent_e/core.py` 只有 206-254 这几行，`close` 只出现在 254。
- 影响面：每次超时泄漏一个作业对象句柄（真机有 28 条超时行）；KILL_ON_JOB_CLOSE 只在进程退出时才收尾。`process_tree` 这个"这次走的是作业对象还是 kill_child"的读数在超时那一档取不到——而超时正是最需要它的场景（`draft/39` §3.21 I13 的原话在这里，见 `core.py:197-205`）。
- 是否复现：静态可确认（读 `core.py` 的控制流即可）；未在真机上观测句柄计数。

### B5 形式化失败在 `experiments` 表级把"没查成"与"查了没通过"折成同一行

- 现象：`_record_formal` 的 `derived` 只有两种取值——`verified` ⇒ `supports/proof/not_proved`；其余全部 ⇒ `inconclusive/heuristic/no_local_evidence`（`agent_e/core.py:382-394`）。`exit_code` 写成 `0 if verified else None`（`core.py:402`）。于是 `compile_error`（查了、精化失败，检查器退出码 1）与 `timeout`/`import_unavailable`（根本没查成）在 `result`/`evidence_kind`/`exit_code` 三列上**逐字相同**。
- 证据：三态区分只保留在 `observations.verifier_status` / `formal_reason` 与 `notes` 里（`core.py:386-391`、`:372-377`）。真机 `agentflow/projects/p8g-fermat-shorter-proof/data/experiments.json` 0002/0003/0004：`result=inconclusive`、`evidence_kind=heuristic`、`exit_code=None`，而 `observations={"verifier_status":"compile_error",…}`、`verifier_output` 里是检查器原话（`omega did not find a contradiction` / `failed to synthesize Decidable …`）。80 条 formal 行里 45 条是这一档。
- 影响面：只读 `result`/`exit_code` 的消费者（列表页、统计、`evidence_for` 的 `result_counts`，`tools/verify_tools.py:580-588`）无法区分"检查器说这份证明没通过"与"检查器没跑起来"；`_result_reason` 靠 `observations` 才把两者分开（`_support.py:724-736`）。而 `formalgw`/工具层那两层是分得很清的（`_CONCLUDED_STATUSES`，`formalgw.py:196`）——折叠发生在 E 落库这一步。另外 `protocol` 侧的 `mathlib` 现算提示只在 `compile_error` 时出现（`agent_e/core.py:30-32`），这是有意为之，不属于折叠。
- 是否复现：真机读数已复现（p8g 三行 + 406 行交叉表）。

### B6 `_apply_round` 造的 E 子目标不带 `script_path`，E 永远跑不了它

- 现象：`counterexample_request` 落成的新子目标是 `{"sid","text","owner":"E","testable":expected_bound,"status":"todo"}`（`agent_f/core.py:488-490`）——没有 `script_path`，也没有 `claim`/`claim_key`/`method`。
- 证据：`_deploy_e` 的第一道判据就是 `script_path = str(sg.get("script_path") or "").strip()`，为空 ⇒ 返回 `action="no_change"`、`status="todo"`、`count_attempt=False`（`core.py:537-551`）。真机已有这一档的产物但还没走到下一轮：`agentflow/projects/p8g-fermat-shorter-proof/data/attack_plans.json` 计划 0000 第 1 轮 `action=counterexample_request`，新建 `s3（owner=E, status=todo）`，该计划 `rounds=1`。
- 影响面：这类子目标会占住后续轮次（`pick_next_subgoal` 把 `todo` 排在 `blocked` 之前，`attack_tools.py:263`），每轮记一条 `no_change`，3 条之后整份计划被提前判 `stalled`。也就是说"F 提出了一个实验请求"这条链路的落点在真机上只能停住。
- 是否复现：代码路径确定；真机尚未推进到第 2 轮（未观测到后果，只观测到新子目标已生成）。

### B7 `_apply_round` 只写 `evidence` 不写 `evidence_ids`

- 现象：`reduction` / `counterexample_request` 返回 `"evidence": [...]` 而没有 `evidence_ids`（`agent_f/core.py:475`、`:493`、`:501-512`），而 `step` 只把 `evidence_ids` 合并进子目标（`step.py:217-218`）。对比 `_deploy_a`/`_deploy_b` 两个键都给，并在注释里写明"只写前者会让子目标看起来'一条证据都没有过'"（`core.py:723-728`）。
- 证据：真机 `agentflow/projects/p8f-fermat-shorter-proof/data/attack_plans.json` 计划 0000 第 1 轮 `evidence=['s3','s4']`，而 s1 的 `evidence_ids=[]`（计划 0001、`p8g` 计划 0000/0001 同形）。
- 影响面：`_compose_best_partial` 的 `brief()` 会按 `evidence_ids` 为空而跳过"证据"那一项（`core.py:838-839`），于是交接记录里看不到"这一轮产生了哪些新子目标"。
- 是否复现：真机读数已复现（4 个计划）。

### B8 `history` 里的 `progress` 不等于推进；停滞检测只认 `no_change`

- 现象：`_deploy_a` 把"提交了一条检索请求、结果还没回来"记成 `outcome="progress"`（`agent_f/core.py:715-722`，detail 里写明"在这一轮里它还没有证据"）；`_apply_round` 的 `proof` 也是 `progress` 而 `evidence=[]`（`core.py:477-482`、`:503`）。停滞检测数的是最近 N 条 `outcome` 是否全为 `no_change`（`step.py:88-90`）。
- 证据：真机 `D:\Incubator\projects` 下 8 个 `attack_plans.json` 的 history 共 273 行，其中 `submit_search_request/progress` 154 行、`stop/no_change` 119 行。`projects/p2-review` 计划 0000：6 轮全 `submit_search_request` ⇒ `progress`，`rounds=6/6` 用尽才停，`best_partial` 逐字是"[停止] 轮数已用尽（6/6）"；6 个子目标的状态都是 `in_progress` + `in_flight=True`，卡点是"等 A 完成检索请求 r-000X"。全库 155 个子目标的 `blocked_reason` 是"等 A 完成检索请求 …"。
- 影响面：一个计划可以"每轮都算进展"地把预算烧完，而实际推进只有"把请求交出去"这一件事。三态纪律在这里是"detail 里写清楚了"，但机器可读位（`outcome`）与另一条路（`_deploy_e` 的 `no_change`）不是一套刻度。
- 是否复现：真机读数已复现（154 行 + p2-review 计划 0000）。

### B9 `_derive_status` 没有"全部 blocked"这一档 ⇒ 子目标全卡住时计划仍报 `attacking`

- 现象：`_derive_status` 只有三个出口：全 `closed` ⇒ `resolved`；全在 `(closed, supported_not_proved)` ⇒ `supported_not_proved`/`resolved`；否则 `attacking`（`agent_f/core.py:803-821`）。
- 证据：真机 `agentflow/projects/p8c-fermat-shorter-proof/data/attack_plans.json` 计划 0001：`status=attacking`、`rounds=2/6`，两个子目标都是 `blocked` + `in_flight=True`，`blocked_reason` 是 `judge_failed:AttributeError`。
- 影响面：读计划行的人看到 `attacking` 会以为这轮还在动；真实情况要靠逐个子目标的 `blocked` 与 `in_flight` 才看得出。也解释了为什么计划要等"连续 3 轮 no_change"才被提前停（`no_pickable` 分支每次都写 `attacking`，`step.py:189`）。
- 是否复现：真机读数已复现（p8c 计划 0001）。

### B10 推理缝失败/不成形两条路径不交产物，`attempts` 也不计

- 现象：`judge_json` 出问题（`core.py:397-409`）与 `parse_round` 抛 `RoundError`（`core.py:410-425`）都返回 `action="no_change"`，**没有 `product` 键**，`count_attempt=False`。而 `dead_end` 那两条路径都带 `product`（`core.py:295-333`、`:428-447`）。
- 证据：`agent_f/step.py:254-265` 只在 `deploy.get("product")` 为真时才写 `product`/`product_detail`/`strategy`/`best_partial`/`dead_end_reason`。真机 `p8b`/`p8c`/`p8d` 的 6 个 F 子目标：`blocked_reason` = "LLM 判定没查成（判断点 F.step）：judge_failed:AttributeError"，对应 history 行的 `product=None`、`strategy=None`、`attempts=0`（`agentflow/projects/p8d-fermat-shorter-proof/data/attack_plans.json` 计划 0000/0001）。
- 影响面：与 `attackround.py:11-16` 自己写的"每轮只能以四种产物之一收尾（不许 `no_change`）"不一致：接口失败时这一轮既没有产物、`attempts` 也不涨，于是"这一轮模型到底说过什么"只剩 `detail` 一句话，而 M 的收工门读的是"history 里的有效推进"（`p8d` 的 `ACCEPTANCE-CHECKS.json` 逐字写了"非空推进 0 条"）。同时"同一子目标被反复重试"这条纪律失去了计数依据（`max_persist_attempts` 本来也没有消费者，见 B12）。
- 是否复现：真机读数已复现（6 个子目标 + 同批 history 行）。

### B11 I11（缺陷继承）与"多路并行"两条判据在生产代码里没有调用者

- 现象：`attackround.inherit_defects`（`:180-194`）与 `pick_parallel_routes`（`:249-254`）只被 `tests/test_attack_round.py`、`tests/test_invalidation_cascade.py` 调用；`agent_f` 一行都没调。
- 证据：`grep -n "inherit_defects|pick_parallel_routes|clean_statement_ids" src/agentflow` ⇒ 生产侧只有 `evidencebits.clean_statement_ids`（`:253`，被 `closing.py`/`statusreport.py` 用）与 `attackround` 自己的定义，`agent_f` 与 `agent_e` 都不在其中。`_reason_self` 的顺序是 `judge_json → parse_round → _apply_round`，中间没有缺陷检查（`core.py:396-426`）。
- 影响面：`_clean_step` 只要求 `cites` **非空**，不要求它在册（`attackround.py:172-176`）。真机 `agentflow/projects/p8f-fermat-shorter-proof/data/attack_plans.json` 计划 0002 第 1 轮 `product=proof`、`outcome=progress`，三步的 `cites` 逐字是 `["lit:Frey1986","lit:Ribet1990","lit:Serre1987"]`、`["lit:SophieGermain1823","lit:Edwards1977"]`、`["lit:Kummer1850","lit:Washington1997"]`——而该工作区 `literature.json` 的 id 是 `0000`-`0007`（`python -c` 读出），这些 id 一条都不在册。这一轮被记成推进。
- 是否复现：真机读数已复现（p8f 计划 0002 的 `product_detail`）。

### B12 三个声明过的预算键没有消费者

- 现象：`budget.max_parallel_subgoals` 与 `budget.max_persist_attempts` 是 schema 的必填键（`schema.py:1247-1253`），`_Core.max_subgoals_per_round` 也在构造时读 config（`agent_f/core.py:110`），但 `grep -n "max_subgoals_per_round|max_parallel_subgoals|max_persist_attempts" src/agentflow` 显示它们只出现在定义、schema 校验与 `_budget_left`（`_support.py:168-169`）里，没有任何判据读它们。`step` 每次只分派一个子目标，硬闸只有 `max_rounds`。
- 证据：同上 grep 输出（13 处，全部是定义/描述/回报）。`can_round(budget, rounds_done=rounds, depth=0)` 里 `depth` 恒传 0，`max_depth` 因此也永不触发（`step.py:120`，注释解释了这个取舍）。
- 影响面：`budget_left` 把这三个键的**原值**当"余量"回报（`_budget_left` 直接 `budget.get(...)`），名字是"left"而值是上限；F 的"瞬时并发"与"单点重试上限"两条预算在行为上不存在。
- 是否复现：静态可确认；真机未见任何一次由这两个键导致的拒绝。

### B13 `search_bound` 在 `numeric` 上只能靠脚本自报，显式传参会被拒

- 现象：`search_like = method in ("exhaustive_search",)`（`run_experiment.py:83`）；非穷举方法传 `certificate`/`search_bound` 一律 `ExperimentError`（`:84-89`）。
- 证据：真机三次拒绝逐字记录：`p6h` t-0008、`p8c` t-0031、`p6r` t-0067 的 `detail` 都是"E.run_experiment 拒绝了这次调用：certificate / search_bound 只对穷举/枚举类方法有效（收到 method='numeric'）"（`agentflow/projects/p6r-paper-from-results/manuscripts/handoffs.jsonl` 与 `sessions/20261006.jsonl`）。而 `search_frontier_rows`（M 的收工门）数的正是 `search_bound` 非空的行（`closing.py:1072-1078`）。真机 74 行有 `search_bound`，其中 62 行来自脚本自报的 `observations.bound`。
- 影响面：一条"我搜到哪儿了"的读数，能不能进台账取决于两件事之一：脚本自己会写 `REPRO_RESULT` 的 `bound`，或把方法写成 `exhaustive_search` 并凑出 `certificate`+`search_bound` 两个对象（后者还要在跑完之后才校验，见 B2）。这解释了早期工作区里 `search_bound` 全为 0 的读数（`D:\Incubator\projects` 的 189 行里 `search_bound` 非空 **0** 行）。
- 是否复现：真机读数已复现（3 次拒绝 + 两工作区根的 74/406）。

### B14 超时注记用的是形参而不是生效值

- 现象：`run_experiment.py:130-131` 的 `head += f"，超时（timeout={timeout}s）"` 读的是形参 `timeout`（缺省 600），而实际生效值是 `timeout if timeout is not None else self.default_timeout`（`:123`）。
- 证据：调用方显式传 `timeout=None` 时生效值是 `cfg["timeout"]`，而注记会写成 `timeout=Nones`。真机 28 条超时注记解析出来的值全是 `600/300/900/120/240`（命令：正则 `超时（timeout=([^s]*)s）` 统计 ⇒ `{'600':20,'300':5,'900':1,'120':1,'240':1}`），**没有观测到 `None`**。
- 影响面：只在"调用方显式传 None"时出现，而工具层的 `timeout=kw.get("timeout", 600)`（`tools/verify_tools.py:1098`）在键存在且值为 `None` 时会原样传下去，所以这条路径可达。
- 是否复现：静态可确认；真机未观测到（未复现）。

### B15 D38 注记在 406 行真机里出现 0 次

- 现象：`_support.py:574-581` 在 `result="supports"` 且 `bound`/`strategy`/`scaling` 三者都没有时追加一条"这一条只给了结论、没有留下界/策略/成本曲线"。`grep -n "没有留下界" agentflow/projects`（含 `experiments.json`）**0 命中**。
- 证据：26 条 `supports` 行的 `observations` 里三键都没有，它们全部早于该判据（最晚一条是 `p6k` `2026-10-06T00:34:13`，而该判据的动机正是"T2 第 9 趟 p6k 的 14 条实验 `search_bound` 有值 0 条"，见 `_support.py:575-576`）；`p6p`/`p6q`/`p6r` 之后的 `supports` 行都带了 `strategy`/`data`。纯函数探针确认这条 note 可达：`_derive(0, 'REPRO_RESULT: {"result":"supports","evidence_kind":"cross_check"}', "numeric")` 的 notes 里逐字出现它。
- 影响面：没有证据表明它失灵，只能说**在这批真机台账里它一次都没有触发过**；"没留下界"这条读数目前只存在于代码与提示词里。
- 是否复现：探针可复现 note；真机触发未复现。

### B16 `bound`/`strategy`/`scaling`/`data` 形状不对时静默丢弃，且 note 会说"没有"

- 现象：`_search_facts` 对 `bound`（非 Mapping）、`scaling`（非序列）、`strategy`（空白）一律 `continue`/跳过，不记任何"格式非法"（`_support.py:459-469`）；`_script_data` 对非 Mapping 的 `data` 也静默丢（`:602-605`）。与 `result`/`evidence_kind` 的处理（有 note）不同。
- 证据：纯函数探针：`{"result":"supports","evidence_kind":"cross_check","bound":123,"scaling":"oops","strategy":"  ","data":[1,2]}` ⇒ `observations={}`，notes 只有 D38 那一句"`REPRO_RESULT` 里没有 `bound`/`strategy`/`scaling`"——而脚本确实打印了这三个键。
- 影响面：那句话在"脚本给错形状"时是不准确的；同一次实验的"它到底写了什么"只剩 stdout 日志（`out/experiments/*.log`）可查，而台账的 `observations` 是空的。
- 是否复现：是（探针）。

### B17 `verifier_output` 与 notes 把机器相关的绝对临时路径写进台账

- 现象：`tools/verify_tools.py:463-465` 把检查器 stdout+stderr 原样放进 `verifier_output`，而检查器命令行里的文件是 `formalgw._materialize` 建的临时文件（`formalgw.py:1489-1505`，临时目录在调用结束即 `cleanup`）。
- 证据：真机 `p8g` 0002/0003/0004 的 `verifier_output` 逐字以 `C:\Users\ysc20\AppData\Local\Temp\dsh-3kM5Q4\agentflow-lean-t7xyzz95\flt3_core.lean:9:2: error: …` 开头；notes 里也有同一串。`formalgw.check_lean` 自己已经把"逐字查的是哪份源码"放在 `checked_source`、把调用方给的路径放在 `source_path`（`formalgw.py:1287-1302`），这两栏没有落进 `Experiment` 行（`build_experiment` 只收 `verifier_output`/`verifier_subject_key`，`_support.py:606-681`）。
- 影响面：复核者从台账里看到的路径在本机上不存在；能复核的只有 `code_hash`（脚本那份 `.lean`）与本行的 `notes`（`agent_e/core.py:358-360` 记了脚本相对路径与 sha256 前 16 位）。
- 是否复现：真机读数已复现（p8g 三行）。

### B18 `step` 追加"停止"记录的上限比 schema 少 1

- 现象：轮数用尽那一支的守卫是 `len(history) < max_rounds × max(1, len(subgoals))`（`step.py:133`），而 schema 允许的上限是同一个乘积 **+1**（`schema.py:1298`，注释写明那个 +1 就是为"轮数用尽那一轮要能记一条 stop"加的）。
- 证据：两处表达式并列可读；schema 注释逐字："上限是 `max_rounds × 子目标数 + 1`，那个 +1 是必要的…于是轮数用尽的那一轮无法追加一条 `action="stop"` 的如实记录"。
- 影响面：当子目标数为 1 时（`p8f` 计划 0002 就是 1 个子目标、`max_rounds=3`）乘积就等于 `max_rounds`，此时恰好顶到旧上限，那条 stop 记录仍写不进去——schema 那侧已经放宽，`step` 这一侧没有跟上。
- 是否复现：静态可确认（两个表达式的字面差异）；真机样本里 `len(history)` 都远小于该乘积，未观测到被挡住的实例。

### B19 `NEGATION_KINDS` 里有一个值没有生产者；`evidence_kind=cross_check` 与 `result=inconclusive` 可共存

- 现象：`NEGATION_KINDS = ("disproved","not_proved","not_searched_here","no_local_evidence")`（`schema.py:890`），而 E 的两条推导路径只会产出 `disproved`/`not_proved`/`no_local_evidence`（`_support.py:569`、`core.py:383-385`）。`not_searched_here` 在 406 行真机里 0 次（命令：`negation` 计数 ⇒ `no_local_evidence 203 / not_proved 179 / disproved 24`）。它的唯一其他出现处是 `claimanatomy.py:1533` 的返回元组与 `doc_tools.py:89` 的中文标签。
- 现象二：`evidence_kind` 与 `result` 是两根独立的轴，脚本自报的 `evidence_kind` 原样保留（`_support.py:439`）。真机有 32 行是 `result=inconclusive` + `evidence_kind=cross_check`（numeric 30、exhaustive_search 2）。
- 证据：406 行交叉表 ⇒ `numeric | inconclusive | cross_check 30`、`exhaustive_search | inconclusive | cross_check 2`；`evidence_kind` 分布里 `cross_check` 共 200 行（其中 32 行 `result=inconclusive`）、`heuristic` 171、`proof` 35，而 `result` 分布是 `supports` 179 / `inconclusive` 203 / `refutes` 24。
- 影响面：`evidence_for` 的 `best_evidence_kind` 只看 `evidence_kind`（`tools/verify_tools.py:574-577`），所以一条"脚本说 inconclusive"的行也能把某条 `claim_key` 的"最强证据等级"抬到 `cross_check`——`proved` 仍是 False，但"等级"这一栏与 `result` 不是同一件事这件事需要读者自己知道。
- 是否复现：真机读数已复现（交叉表）。

### B20 模型缝是进程级全局

- 现象：`_DEFAULT_LLM` 是模块级全局，`set_default_llm` 由 `host` 在装配时登记或清空（`agent_f/core.py:23-34`、`host.py:477-499`），工具层构造 `AgentF` 时读它（`tools/attack_tools.py:283-289`）。
- 证据：`host.py:496-499` 的注释写明"同一进程里跑第二趟时不许继承上一趟登记的缝"；`attack_tools.py:289` 是 `AgentF(store, llm=default_llm())`，不带 store 维度。
- 影响面：同一进程内两个工作区并存时，后登记的那一个会覆盖前一个；`AgentF` 的实例级 `llm=` 注入（`specs/f.py:70`）与这条全局是两条路，语义不完全等价。
- 是否复现：静态可确认；真机（每趟一个进程）未观测到串扰。

### B21 `evidencebits` 与 E/F 没有直接关系（范围修正）

- 现象：任务书把 `evidencebits.py` 列在 E/F 用到的判据里，但 `grep -n "evidencebits" src/agentflow` 的消费者是 `schema.py:1610/1680`（`Statement` 的五位校验转发）、`closing.py:892`、`statusreport.py:103`、`verifications.py:245`；`agent_e/*` 与 `agent_f/*` **一行都没有 import**。
- 证据：同上 grep 的 10 条命中里没有 agent_e/agent_f。E 的 `experiments` 行要变成某个命题的"第 1/4 位读数"，只能由登记 `statements` 的一方显式把 `exp:` 写进 `bits.evidence.numeric/formal`（`evidencebits.py:206-250` 的凭据要求）。
- 影响面：`bits_from_row` 对旧行按"五位全空"读（`:108-128`），意味着**E 跑了 proof 级实验这件事本身不会让任何命题升级**，除非有另一条链路显式指过去。真机 p6e 那两条 `formal` proof 行（0005/0006）在 `statements` 里没有对应指向，这与 `evidencebits.py:215-218` 记录的同一形态一致。
- 是否复现：静态可确认（grep）；未逐条核对每个工作区的 `statements.bits`。

### B22 `for_question_id` 只校验形状，不校验存在性

- 现象：`S.Experiment.validate` 对它调 `require_id`（4 位十进制，`schema.py:1185-1186`），不查它是否指向 `research_questions` 里的一行。
- 证据：真机 `agentflow/projects/p6m-research-from-zero`：`attack_plans[0].for_question_id = "0001"`，而该工作区 `research_questions.json` 只有 `0000` 一行（命令读出）；同一工作区两次 E 失败的原因是 `for_question_id='q-0001'` 不是 4 位数字（B2）。
- 影响面：一条实验/计划可以挂在一个不存在的问题号上而不报错；下游按 `for_question_id` 汇总（`evidence_for(for_question_id=...)`，`tools/verify_tools.py:549`）时结果是"查了、没有"，与"这条号根本不存在"看起来一样。
- 是否复现：真机读数已复现（p6m 的 plan 行 + questions 表）。

---

## 4. 冗长与可读性观察（只描述）

`#` 注释行占比按文件统计；docstring 行数单列（AST 读出）。命令：`python -B -X utf8 -c "…ast.parse 遍历…"`。

| 文件 | 行数 | 函数数 | 类数 | `#` 注释行（占比） | docstring 行 |
|---|---|---|---|---|---|
| `agent_e/_support.py` | 777 | 23 | 1 | 39（5.0%） | 273 |
| `agent_e/core.py` | 724 | 12 | 2 | 84（11.6%） | 125 |
| `agent_e/run_experiment.py` | 308 | 3 | 1 | 44（14.3%） | 71 |
| `agent_e/check_formal.py` | 121 | 1 | 1 | 26（21.5%） | 58 |
| `agent_e/__init__.py` | 144 | 0 | 0 | 6（4.2%） | 117 |
| `agent_e/{__main__,evidence_for,list_experiments,run_script_experiment}.py` | 13/14/12/12 | 0/1/1/1 | 0/1/1/1 | 0 | 7/5/5/5 |
| `agent_f/core.py` | 1071 | 26 | 2 | 126（11.8%） | 129 |
| `agent_f/step.py` | 288 | 1 | 1 | 54（18.8%） | 23 |
| `agent_f/_support.py` | 187 | 5 | 1 | 12（6.4%） | 96 |
| `agent_f/create_plan.py` | 135 | 1 | 1 | 16（11.9%） | 23 |
| `agent_f/status.py` | 109 | 1 | 1 | 22（20.2%） | 5 |
| `agent_f/list_plans.py` | 49 | 1 | 1 | 1（2.0%） | 20 |
| `agent_f/__init__.py` | 77 | 0 | 0 | 6（7.8%） | 63 |
| `judge.py` | 139 | 3 | 2 | 11（7.9%） | 52 |
| `attackround.py` | 308 | 8 | 1 | 8（2.6%） | 65 |
| `tools/verify_tools.py` | 1162 | 19 | 0 | 197（17.0%） | 348 |

**最长的 5 个函数**（跨上表全部文件，按 `end_lineno - lineno + 1`）：

1. `tools/verify_tools.py:124` `check_formal` —— 367 行（docstring 占绝大部分）。
2. `agent_f/step.py:10` `step` —— 279 行。
3. `agent_e/core.py:500` `selftest` —— 225 行。
4. `agent_e/run_experiment.py:10` `run_experiment` —— 209 行。
5. `agent_f/core.py:893` `selftest` —— 179 行。
   紧随其后：`tools/verify_tools.py:989` `register` 169 行、`agent_e/core.py:276` `_record_formal` 166 行、`agent_f/core.py:514` `_deploy_e` 144 行。

`agent_e` 合计 2125 行 / 42 个函数；`agent_f` 合计 1929 行 / 35 个函数；`judge.py` + `attackround.py` + `verify_tools.py` 合计 1609 行。

**重复实现/重复表述（给 `file:line` 对）**

1. 模块 docstring 维护两份：`agent_e/__init__.py` 的 docstring 117 行与 `agent_e/_support.py` 的 112 行做 `difflib.SequenceMatcher` ⇒ 相似度 **0.972**，最长公共块 4191 字符（同一份"推导规则/三态纪律"写了两处）。`agent_f/__init__.py`（63 行）对 `agent_f/_support.py`（58 行）⇒ 0.936、1776 字符。
2. 禁用词清单两份且逐字节相同、无交叉断言：`attackround.py:49-51` `F_BANNED_MARKERS` 与 `verifications.py:53-55` `HARD_BAN_MARKERS`（探针：`AR.F_BANNED_MARKERS == V.HARD_BAN_MARKERS` ⇒ `True`）；`grep` 显示没有代码把两者连起来。
3. `REPRO_RESULT` 读侧两份、语义不同：`agent_e/_support.py:340-416`（取**全部**行、多于一行即拒、另有 JSON 键形态容错）与 `paperbuild.py:54` `REPRO_PREFIX` + `:73`（取**最后一行**）。两者都是"读脚本结论行"的实现。
4. 路径越界守卫至少四份：`agent_e/core.py:116-133`（`_Core._resolve`）、`agent_e/_support.py:737-743`（`_relpath`，同文件第二处 `relative_to`）、`tools/verify_tools.py:398-408`（`check_formal` 内联）、`tools/verify_tools.py:1004-1015`（`register` 内的 `_resolve`）。工作区外的同族实现另有 `store.py:1424`、`gates.py:658`、`fs_tools.py:226` 等（不在本次范围内）。
5. 摘要/截断助手两份：`agent_e/_support.py:282` `_digest` 与 `agent_f/_support.py:182` `_short`（后者 docstring 自己写"与 `agent_d._digest` 同形"）。
6. `evidence_for` 一条实现两个包装：`agent_e/evidence_for.py:12` 与 `tools/verify_tools.py:935`，实现同在 `tools/verify_tools.py:499`。
7. 协议文本在提示词/声明层反复重述（同一段读数与告诫出现在多处）：`specs/e.py:167`、`specs/e.py:170`、`specs/e.py:171`、`specs/m.py:65`、`specs/m.py:83`、`agent_prompts.py:709`、`agent_prompts.py:964`、`agent_prompts.py:1174`、`closing.py:991`、`closing.py:1022`、`closing.py:1077`。
8. `check_formal` 是一条三层转发链（`agent_e/check_formal.py:88` → `tools/verify_tools.py:420` → `formalgw.py:1181`），三层各自有一份"受控状态"的说法：`formalgw.STATUSES`（10 值）、工具层 `reason` 透传（+`no_script`）、`agent_e._support.FORMAL_REASONS`（15 值）。三份之间只有导入期断言（`_support.py:183-191`）与测试守着。

---

## 5. 未核实与缺口

1. **作业对象在真机上的实际取值**：`process_tree`（`"job"` / `"kill_child"`）没有落进任何台账或产物，`grep` 全库无命中；无法从盘上回答"E 起的那 406 次子进程里有多少次真的装进了作业对象"。
2. **B4 的句柄泄漏**只做了静态确认：没有测进程句柄计数，也没有在真机上观测到超时后的树残留（`grace_then_kill` 的 `stragglers` / `left` 读数只返回给调用方，没有落库）。
3. **`_stop_requested` 那条路从未在真机触发**：`grep -l '叫停'` 在全部 `experiments.json` 里 0 命中，因此"用户叫停 vs 超时"的区分（`core.py:255-266`）只有代码与自检，没有真机证据。
4. **B18 的 off-by-one** 只有两个表达式的字面差异，没有找到被它挡住的真机实例（`len(history)` 都远低于该乘积）。
5. **B6 的后果**未观测：只观测到"带 `owner="E"` 且没有 `script_path` 的新子目标"已生成（p8g 计划 0000 的 s3），没有观测到下一轮它被选中之后的 `no_change` 记录。
6. **`stalled_max` 与 formal 试错预算的联动**未核实：`agent_loop.py:1265/1276/1277` 的阈值是 M 循环的读数，我没有逐趟核对"某个 `check_formal` 命题第 3 次被点名之后模型是否真的换了命题"。
7. **`out/invalid/*.txt` 是否覆盖 F 的失败**未核实：现存 11 个文件的内容都是 M 循环那一层的原始回复；F 侧的失败（B10）只落成 `attack_plans.history.detail`，没有对应的 invalid 快照。
8. **两个工作区根的覆盖度**：`D:\Incubator\projects\*`（189 行 experiments）与 `D:\Incubator\agentflow\projects\*`（217 行）。我没有核对这两棵树是否互为拷贝、也没有核对 `p5-review-t1/out/experiments/0000.log` 那条"有 log 无行"（该工作区 `experiments.json` 为 `rows: []`、`events.jsonl` 里 0 条 experiment 事件、`counters.json` 无 `experiment` 计数）是"失败事务"还是"台账被人工清过"。
9. **`p6e-research-from-zero/out/experiments/0008.log`** 有 log 无行，而该工作区 `events.jsonl` 里 experiment 事件只有 0000-0007 —— 无法从盘上判断这条 log 是本次失败事务留下的，还是工作区从别处拷来/重置过（`D:\Incubator\projects` 与 `agentflow\projects` 下有大量同名工作区）。
10. **`evidencebits` 与 `experiments` 的实际连线**未逐工作区核对（B21 只给了静态结论 + p6e 一个样本），因此"E 的 proof 行在多少条命题上被真正采信"没有读数。
11. **未跑**：任何 Lean 编译、任何真实模型调用、任何 pytest；`formalgw` 的状态判定顺序是读代码 + 读它自己的自检清单（`formalgw.py:1511-1641`），没有在本机真跑检查器。
