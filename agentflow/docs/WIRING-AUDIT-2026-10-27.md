# 接线审计（2026-10-27 夜）

业主口径（唯一权威）：「有极大概率你的那些子代理们把功能实现好以后未接线，请务必检查接线」。

这份文件是那一轮审计的机器可核落点。判据本体在 `tests/test_wiring_edges.py`
（源码级 AST，只读盘、不 import 业务模块）。本文件是给人的那张表。

## 一、结论分档的判据

| 档 | 含义 | 机器形态 |
|---|---|---|
| WIRED | 有真机调用点、且调用者从入口集可达；另有运行探针读数 | `WIRED` 表 + `is_live` |
| ORPHAN | 只有 `tests/**` 调它（或只有它自己的读侧） | `KNOWN_ORPHANS` |
| UNREACHABLE | 有调用点，但调用者从任何入口都到不了 | 同上（`is_live` 为假且不在台账里即红） |

入口集 = `cli.py` 的 `cmd_*` + `host.py` 全部函数 + 带 `tool` 装饰器的函数。前两个是
argparse 的 `set_defaults(func=…)` 挂点、后一个是注册表按名字取，三者静态都不可解析，
所以必须显式种进可达集，否则整片工具体会被误判成孤儿。

边的三种形态都算：调用、裸引用（`sessions.set_append_hook(_observe_session_event)`）、
工厂默认值（`sleep = sleep or self._default_sleep`）。只算调用会把 `clock.observe_work`
与 `fetch._default_sleep` 误判成孤儿 —— 实测过，这一条是判据的已知误差来源。

## 二、十五项

| # | 项 | 定义点 | 谁在活着的那条路上调它 | 结论 |
|---|---|---|---|---|
| 1 | 时钟八件 | `tools/clock_tools.py:624/740/797/850/891/940/994/1060` | `clock_tools.register`（`tools/__init__.py:188` 的 `_MODULES` 收它）⇒ 十个角色 + M 的工具面 | WIRED |
| 2 | 挂机（waiter/park/唤醒） | `clock.py:1704 _register_parked`、`:783 park_state`、`:1666 observe_work`、`:2664 consume_wakes` | 登记：`start_timer/start_alarm`；观测：`clock_tools.py:1109` 的会话写路径旁路钩子；消费：`agent_loop.py:4255 _take_wakes` | 登记/观测/消费 WIRED；**控制流层没有挂机支（见第三节 a）** |
| 3 | 秘书链转发 | `secretary.py:6116 relay_out`、`:6187 relay_in`、`:6278 deliver_local`、`:1031 relay_path` | `conductor_tools.py:2311`（`conductor.guide` 的唯一收件人）；`relay_in` 逐跳递归 | WIRED |
| 4 | 链式寻址 | `conductor.py:793 parse_chain_address`、`:5179 resolve_chain`、`:5118 chain_of`、`:5130 chain_text` | `conductor_tools.py:2268`；`chain_of/chain_text` 另由 `Conductor.tree` 消费 | WIRED |
| 5 | 轮查带链 | `conductor_tools.py:2136 conductor_watch`、`:455 conductor_ledger`、`conductor.py:5405 tree`、`trace_tools.py:550 trace_children` | 三件都是 `@tool`，模块在 `_MODULES` 里；`chain` 格由 `conductor.py:5439/5446` 落 | WIRED |
| 6 | 依赖面：F 写稿 → 秘书洗稿 → 打回 | `agent_f/core.py:1415 _wash_manuscript`、`secretary.py:3756 wash_dependency_face` | `_apply_round` 的 proof 分支：`:1722` 洗、`:1760` 才 outlet（顺序是结构性的） | WIRED |
| 7 | D 携带 | `agent_d/write_report.py:568 _deliver_carried_to_b`、`depsection.py:498 carried_manuscripts` | `write_report:456` | WIRED |
| 8 | B 读稿落依赖（四档） | `agent_b/register_statement.py:932-967`、`:1868`、`secretary.py:3799` | `register_statement` 本体（B 的写入口） | WIRED |
| 9 | V 引用核实 | `verifications.py:166 citation_material`、`:281 reconcile_citation_checks`、`:393 apply_citation_gate`、`:1368 signs_bit3`、`:123 CITATION_EVIDENCE_FLOOR` | `agent_v/core.py:127 / 215 / 456`；`signs_bit3` 七处 | WIRED |
| 10 | 保留产物闸 | `tools/fs_tools.py:264 RESERVED_ARTIFACT_TABLE`、`:316 _reserved_artifact`、`:336 _reserved_refusal` | `fs_write` 与 `fs_edit` 两道闸共用 | WIRED（身份来源是 `conductor.current_caller_role()`，见第三节 e） |
| 11 | testable 闸 | `agent_f/create_plan.py:99-113`（受控码 `subgoal_without_testable`） | `attack_tools.py:451`（`attack.create_plan`） | WIRED |
| 12 | 非平凡度 | `secretary.py:6622 proof_effort_readings`、`:6705 nontriviality_from_effort`、`:6747 material_truncation` | `Secretary.judge_statement`（`:1772 / :1843 / :1796`） | WIRED |
| 13 | 命题同一性 | `secretary.py:3543 adjudicate_proposition`、`:6779 append_proposition_verdict`、`:6814 proposition_verdict_of`、`:6844 proof_routes_of`、`:6866 proof_route_of` | `record_statement:3997`（B 与 `table_tools` 的直写路由都走它） | 判定链 WIRED；**`proof_route_of` / `proof_routes_of` 是 ORPHAN** |
| 14 | F 无开关推理 | `host.py:531 f_llm = _seam("F")`、`:534 set_default_llm`、`agent_f/_support.py:52 UNWIRED_OWNERS = ("C","D")` | `wired_llm_conductor` 恒建；`attack_tools._agent_for` 那条路经 `default_llm()` 拿同一个缝 | WIRED |
| 15 | 时钟账 | `clock.py:2189 await_io`、`:2146 note_wait`、`:2514 coverage`、`:2447 raw_wait_census` | `await_io` 十三处；`note_wait` 四处；`coverage` 由 `clock.now` 读 | WIRED（普查真扫了 254 个文件） |

## 三、三条可疑项

### a）挂机的"真停摆"：不成立，循环层面没有挂机支

- `agent_loop.py` 全文含 `park` 的行数 = 0；`waiters()` 的唯一读者是 `clock.now` 与
  `clock.timer_list`（`clock_tools.py:658 / :1012`），也就是模型自己看的读数；
- `ask_step` 只有一个调用点（`agent_loop.py:5634`），它无条件执行，唯一的上游分支是
  `if not pending:`（`stepdispatch` 的待办队列），与挂机无关；
- 运行探针（`--provider` 不参与，替身缝，零模型钱）：父代理第 1 步
  `clock.timer_start(wait_for="task:t-000002")` 起表，之后循环照旧走了 3 个回合，
  `clock.waiters()` 读到 `park_state=parked` 且 `parked_steps=3 / parked_calls=3`。

结论：`test_clock_governs_all_timed_work.py::test_i_parked_waiter_has_no_steps_and_polling_is_detected`
里的 `parked_steps == 0` 在测试里成立，是因为那个夹具里父代理根本没在跑。真机上挂机的父
代理每一步都会落 `agent_step`，于是同一条读数会读到 3。这个缺口是"缺一根控制线"：循环
没有"这一拍不跑模型、等时钟叫醒"的那一支。

### b）时钟到点唤醒：读是真读，但唤醒只会多一次模型调用，不会少一次

- `_take_wakes`（`agent_loop.py:4255`）每一步都跑：`pending_wakes` → `consume_wakes`
  （`:4267 / :4274`）。探针：`max_wait_sec=600` 到期后 `pending_wakes` 读到 1，
  `_take_wakes` 返回 `consumed=1 / checked=True`，消费后再读 `count=0`；
- 消费掉之后走 `_monitor_block`（`:4326`）把这一次变成监控回合，并对出口加限定；
- 但同一步紧接着仍然 `ask_step`。所以"这一拍不跑模型"这件事在代码里不存在；
  `_wake_pending`（`:4511`）确实会在阻塞式等孩子（`_wait_for_children`，`:4497`）时提前
  返场，那是唤醒唯一改变控制流的地方。

### c）F.step 的 proof 档真的先洗再 outlet：是

`_apply_round` 的 proof 分支顺序：`proof_manuscript`（`:1711`）→ `_wash_manuscript`
（`:1722`）→ 不可提交则直接 return 打回（`:1723-1755`）→ 通过才 `_proof_outlet`
（`:1760`）。探针（引一条在册但档位 `heuristic` 的命题）：

```
wash_checked=True  manuscript_washed=False  deps_refused='dependency_row_unverified'
deps_refused_findings=1：line=19 got='stmt:000002（heuristic）'
statements 没有新增行；手稿停在 reports/f-proof-plan-000000.md（没改名 = 没登记）
attack_plans.history 里带走 deps_refused 与那条 finding（下一轮提示词看得到）
```

## 四、今天必须派人接的线

| 缺口 | 位置 | 差哪一根线 |
|---|---|---|
| `proof_route_of` / `proof_routes_of` 全仓 0 个非测试调用点 | `secretary.py:6866 / :6844` | `_proof_routes` 被 `record_statement:5038` 写进 statements 行之后，没有任何读侧调它回到人眼前。应该在哪调：`table.get` / `table.list` 的读数，或 M 的 `conductor.ledger(view="tree")` 每一行带一格 |
| 挂机没有循环层支 | `agent_loop.py:5622-5637` | `_deliver_mailbox` 之后、`ask_step` 之前要有一层：本趟有 `wait_for` 的 pending waiter 且无到期唤醒 ⇒ 不调模型，改为按 `max_wait_sec` / 下一个 `due_at` 睡到最近的事件（并且 `parked_steps` 必须保持 0） |
| F 的秘书没带缝（新） | `agent_f/core.py:1409` | `for_role("F", …)` 换成 `for_role_wired("F", …)`（B 与 `table_tools` 已经这么做了）；否则这一位秘书永远判不了命题 |
| 转发链的发送方秘书没带缝（新） | `tools/conductor_tools.py:2309` | 同上。转发本身不需要模型，但"这一位秘书将来要判东西"时它结构上判不了 |
| 主控读名册的秘书是裸构造（新） | `conductor.py:5175` | 同上（只读名册，但它是 `_secretary` 的三处构造点之一） |
| M 的工具面并集字面量过期 | `tests/test_tool_face_has_no_orphans.py:89` | 今晚新增 3 件 `clock.*`（`periodic_start/periodic_stop/timer_purpose`）：104 → 107。HEAD 上这条是绿的，今晚变红 |
| M 面计数过期（旧） | `tests/test_host_wiring.py:451` | 期望 21，实测 33（HEAD 上就已经是 30）—— 这条判据已经长期没在量东西 |

## 五、这条判据会不会误报

会。三个方向，都已写进 `tests/test_wiring_edges.py` 的 docstring：

1. 只做名字解析、不做类型解析 ⇒ 同名函数会互相借可达性。误差方向是"把不可达读成可达"
   （漏报孤儿），不会因为同名把可达读成不可达；
2. 经 `getattr(字符串)` / 注册表 / 反射得到的边看不见 ⇒ 会误报 ORPHAN。工具体因此不进
   `WIRED` 表，另走 `WIRED_BY_REGISTRY`（核 `@tool` 装饰器 + `tools._MODULES`）；
3. `KNOWN_ORPHANS` 是双向台账：新增孤儿会红，接上之后不改表也会红。后一半是故意的
   —— 接线事件必须有人看见（与 `test_cache_tools_are_known_unwired.py` 同一纪律）。

## 六、补线读数（2026-10-27 晚，本次施工）

第四节那七行里五条已接上，两条留在原处（理由在下面）。每条都是实测的"改前红 → 改后绿"：
改前 = `git show HEAD:…` 那棵树，改后 = 现在的工作树；全部 tmp 工作区 + 假时钟 +
替身缝，零模型钱（父代理与子代理都由 `LlmSeam` 的替身 `complete()` 照剧本回答）。

| 缺口 | 改前读数 | 改后读数 | 判据 |
|---|---|---|---|
| 挂机没有循环层支 | 父起表后走 5 拍：`model_calls=5`、`parked_steps=5`、`parked_calls=5`、`parked_sec=0` | 同一剧本：`model_calls=1`（只有起表那一步）、`parked_turns=4`、`parked_sec=7.5`；挂机区间增量 0 步 0 调用 | `tests/test_park_is_a_real_stop.py` |
| 唤醒只是多一次调用 | 子发消息那一拍照旧问模型 | 那一拍不问：整趟 `model_calls=3`、`woke_turns=1`、`woke_reasons=["event"]`；把"跳过"打桩成空 ⇒ `4`（正好多 1） | 同文件第 4 条 |
| 三处秘书裸构造没带缝 | 护栏红，逐条点名 `agent_f/core.py:1409` / `conductor.py:5175` / `tools/conductor_tools.py:2309` | 三处改成 `for_role_wired(...)`，护栏转绿 | `tests/test_secretary_adjudication_is_wired.py` |
| `proof_route_of` / `proof_routes_of` 是孤儿 | 全仓 0 个非测试调用点；`table.get` 的 statements 行里没有 `route` 那一格 | 读侧接在 `table_tools._with_proof_routes`：`table.get` / `table.list` 的 statements 行带 `route` 与 `proof_routes`；把写侧打桩成不写 ⇒ 两格为空 | `tests/test_proof_route_reaches_the_reader.py` |
| M 的工具面并集字面量过期 | 并集 107、字面量 104 ⇒ 红 | 改成从注册表现算（`spec.roles` 与普查角色集有交集）⇒ 绿；那个数字不再存在 | `tests/test_tool_face_has_no_orphans.py` |

留在原处的两条（都不是"接线"这一族，且都落在本轮禁改的文件上）：

- `tests/test_host_wiring.py` 的 M 面计数（期望 21，实测 33）；
- `tests/test_tools_returns_declaration.py` 的工具总数（期望 107，实际 110）与三条
  `clock.*` 的 `returns=` 声明缺口 —— 要补它们必须改 `tools/clock_tools.py`，那份文件
  在 FC-27 清单上，本轮不动。

一句话解释"挂机区间"的读数口径（真机路径上绝对值的那个 1）：起表那一步自己的
`agent_step` 事件落在计时器登记之后，于是"挂了机"那一刻已经记过一次；判据因此用
"挂机区间里的增量 == 0"，而"开跑前就挂在时钟上"那一档（`waiters()` 里已有 waiter）
读到的就是绝对的 `parked_steps=0 / parked_calls=0 / parked_sec>0`。

## 七、第二批六件（业主 2026-10-27 四条裁定）的接线复核

检查对象是这一批新增的六件 + 一件待工具化。方法同前：定义点 → 非测试调用点
（AST 列 `file:line`，只读盘不 import）→ 能不能从 `cli.py` / `host.py` / `@tool`
三处入口走到 → 跑一次探针贴读数。探针脚本 `temp/probe_six.py`，读数落在
`temp/probe_six.out`：假时钟 + 替身模型 + tmp 工作区，零模型钱。

| # | 项 | 定义点 | 非测试调用点（AST） | 可达 | 探针读数 | 结论 |
|---|---|---|---|---|---|---|
| ① | 等程序：`program_span` / `start_program` / `finish_program` | `clock.py:1901` / `:1733` / `:1783` | `cancellation.run_cancellable:519`、`agent_e/core.py:164`、`papercompile.compile_paper:236` 等 12 处活调用点；`start_program` 由 `ProgramSpan.open:1854` 调，`finish_program` 由 `ProgramSpan.finish:1883` 调 | 是 | 跑着时 `running=1 / state=pending / pid=有`；跑完 `state=fired / outcome=exited / exit_code=0 / elapsed_sec=0.718`；`program_census` 扫 `src`：`checked=true / findings=0 / exempt=0` | WIRED |
| ①（读侧） | `programs` / `program_census` | `clock.py:1941` / `:2064` | 0（只有 tests 调） | — | `programs` 的读数只在探针里被读；`clock.now` / `clock.timer_list` 的 data 里没有这一格 | ORPHAN |
| ② | 目的自动填：`set_target_probe` / `_target_probe` / `_roster_task_text` | `clock.py:695`、`tools/clock_tools.py:318` / `:287` | `tools/clock_tools.py:1211 register`（装配期挂口，`clock_tools` 在 `_MODULES` 里） | 是 | 名册有那一行 ⇒ `purpose_source=target_task`、`purpose_missing=false`、purpose 就是那一行 task 原文；显式给 ⇒ `given`；名册没有 ⇒ `unavailable` + `purpose_missing=true` + 到点消息带追问 | WIRED |
| ③ | `clock.wait_any`（写侧 `request_wait_any`） | `clock.py:2158` | 0 个非测试调用点（`wait_any_reading` 有 2 处：`agent_loop.py:4898 / :5090`） | 否（模型面） | `reg.call("clock.wait_any")` ⇒ `ok=false`，`没有名为 'clock.wait_any' 的工具`；`clock.request_wait_any` 只能由框架内部调 | UNREACHABLE（模型面）—— 已按业主放行做成工具，见第八节 |
| ④ | 计时器不阻塞动作：`_park_gate` / `_pending_work` | `agent_loop.py:4948` / `:4904` | `AgentLoop.run:6125`（唯一调用点，在 `_deliver_mailbox` 之后、`ask_step` 之前） | 是 | 见下面"改前/改后并排" | WIRED |
| ⑤ | 交差：`_hand_off` / `_note_child_handoff` / `record_handoff` / `mark_handoff_seen` / `read_handoffs` | `agent_loop.py:5058` / `:4339`、`clock.py:2351` / `:2389` / `:2422` | `AgentLoop.run:6131`（`_park_gate` 判成交差那一支）、`agent_loop._take_wakes:4328`、`_hand_off:5095`、`_note_child_handoff:4360`、`Conductor._handoffs_summary:2665` | 是 | 子代理：零模型调用、`stop_reason=final`、`handoff_id=ho-000001`、`reported=true`、收件箱里一条 subject 是 `交差` 的留言；父侧：`read_handoffs(parent)` 读到 1 条，`handoffs_reading(parent)` 的 `silent=[t-000002]` | WIRED |
| ⑤（读侧） | `handoffs_reading` | `conductor.py:2509` | 0（只有 tests 调） | — | 父侧读数只能由测试读到；`conductor.watch` / `conductor.ledger` 的 data 里没有 `silent_children` 那一格 | ORPHAN |
| ⑥ | 不变量：`_summon_preflight [5c]` → `arm_child_waiter` | `conductor.py:5160` / `:2375` | `Conductor.summon_begin:4824` → `_summon_preflight:5160` | 是 | 派两个子代理 ⇒ 账上自动两条 `wait_for=task:<子>` 的计时器，`state=pending`、`purpose_source=target_task`（目的 = 名册那一行 task）；`child_wait_invariant` 读到 `unwaited=[] / problems=[]`；两个子代理收口后两条计时器都变 `fired`、`active_children=[]` | WIRED |
| ⑥（读侧） | `child_wait_invariant` | `conductor.py:2437` | 0（只有 tests 调） | — | 不变量今天成立，但"成不成立"没有任何活路径会读 | ORPHAN |

### ④ 的改前 / 改后并排（这一条判据今晚改过两次，最容易被回退）

同一个夹具，唯一差别是 `_park_gate` 用哪一版判据（改前那一版按"本趟有 parked waiter
就停"逐字复现，见 `tests/test_timers_and_handoff_semantics.py::test_c4_the_old_rule_would_have_parked`）。
夹具 = 父名下一条等子代理的计时器 + 一条没消的板项（手上有活）：

| 口径 | 模型调用数 | 回合 | `run.park.decision` | `skip_calls` | 判据理由 |
|---|---|---|---|---|---|
| 改前：「有 waiter 就停」 | 0 | `[]` | `park` | 2 | 只看本趟有没有 parked waiter |
| 改后：「手上有活就照跑」 | 2 | `["tool", "tool"]` | `run` | 0 | `有 1 条计时器在后台走，但手上有活（这一拍新投递了 1 条；名下还有 1 条未消的板项）⇒ 照常问模型` |

两行读的是同一个夹具、同一条代码路径（`AgentLoop.run:6125`），所以这个差值就是判据
本身。改后的分支顺序（`agent_loop.py:4994-5036`）是：① 显式要求等 + 还有计时器 ⇒ 挂机；
② 显式要求等 + 一条计时器都没有 ⇒ 交差；③ 消费到"等谁"的唤醒 ⇒ 这一拍不问；④ 有计时器
且确实无事可做 ⇒ 挂机；⑤ 其余（有活 / 读不成）⇒ 照常问模型。

### 这一批"差哪一根线"（与 `tests/test_wiring_edges.py` 的 `KNOWN_ORPHANS` 逐条同源）

| 项 | 差哪一根线（应该在哪调） |
|---|---|
| `programs` | `tools/clock_tools.py:716 clock_now` 的 data 加一格 `programs`（或让 `clock.timer_list` 的 `timers` 带 kind 为 program 的行）—— 今天模型看不到"有程序在跑" |
| `program_census` | `clock.coverage()`（`clock.py:2514`，`clock.now` 读它）里加一格 `programs_outside_clock`，与 `raw_wait_census` 同一档 |
| `request_wait_any` | `tools/clock_tools.py` 新增 `clock.wait_any` 工具 —— **已做**，见第八节 |
| `read_wait_any` | `conductor.watch` / `conductor.ledger` 的每一行带"它在等什么"，或 `clock.wait_any` 的 `returns=` 里给一条全量意图读数 |
| `cancel_wait_any` | `agent_loop.py` 在"这一拍照常 ask_step"那一支（`_park_gate` 第 5 档，`:5033`）补一句 `CLK.cancel_wait_any(root, me)`；不撤的话下一次"改主意了、手上有活"仍会被旧意图按回挂机档 |
| `handoffs_reading` | `conductor.watch` / `conductor.ledger` 的 data 加一格 `silent_children`（`activity_snapshot` 已经算出来了） |
| `child_wait_invariant` | `conductor.watch` / `conductor.status_report` 的 data 加一格 `child_wait_invariant`，或 `verify.verify_all` 里加一条不变量检查 |

### 一句话读数

六件里三件（① 等程序、② 目的自动填、⑥ 不变量写侧）与两条控制流（④ 挂机判据、⑤ 交差）
都在真机路径上；③ 的写侧起初只有框架内部入口（模型面 UNREACHABLE），其余六条**只有测试
接线**。这两处已在同一天的第二批收口里补完：③ 做成工具见第八节，六条读侧判据见第九节，
`KNOWN_ORPHANS` 因此重新清空。

## 八、`clock.wait_any` 落地后的复核（② → ③ 由 UNREACHABLE 转 WIRED）

业主放行的那一件（第二段①）：把框架内部的 `clock.request_wait_any` 做成模型面的工具。
落点与判据逐条如下：

| 问题 | 读数 |
|---|---|
| 工具数 | 110 → 111（`tools/clock_tools.py` 的 `clock_wait_any` + `_TOOL_FUNCTIONS` 一行） |
| 通用轴 | `tools/UNIVERSAL_TOOLS["clock.wait_any"]` 一条，登记写集空（只写 `out/clock/wait_any.json`，是文件不是表）⇒ 只读角色不被 `for_role` 剥掉，也**不**进 `READONLY_CALL_EXCEPTIONS`（通用能力不是例外） |
| C/H/V 的 clock 件数 | 8 → 9（判据 `test_clock_governs_all_timed_work.py::test_l_readonly_roles_get_all_nine_clock_tools`：既核"九件都在"，也核"clock 件数恰好 9"与"例外表里没有 clock 条目"） |
| 触达 | `reg.call("clock.wait_any")` 从 `ok=false / 没有名为 'clock.wait_any' 的工具` 变成 `ok=true`；M 的面从 33 件到 34 件（`test_conductor_tools.py` 的 `M_TOOL_FACE` 是相等断言） |
| 接线判据 | `clock_wait_any` 进 `WIRED_BY_REGISTRY`（`@tool` + 模块在 `_MODULES` 里）；`request_wait_any` 从 `KNOWN_ORPHANS` 移进 `WIRED`（新的活边是 `clock_tools.py:1163 clock_wait_any`）—— 双向台账两向都判过 |
| 控制流没被工具偷走 | 工具只写意图 + 交回读数；挂机/交差的判定仍在 `agent_loop._park_gate` 一处（`agent_loop.py` 这一批一行未改） |

`read_wait_any` / `cancel_wait_any` 仍是 ORPHAN：前者是"全量意图"的公开读口（今天循环走
内部 `_load_wait_any`），后者是"回模型之后把意图撤掉"的写口（今天没有人撤）。
两条都留在 `KNOWN_ORPHANS` 里，差哪一根线写在同一张表上。

## 九、六条补线（同日第三批：ORPHAN → WIRED）

第八节之后剩下的六条都是同一族：读侧判据或写侧的第二个入口没有活的调用点。
业主放行后逐条补线，每一条都是"读数面加一格"或"判据里加一句"，并且各配一条会红的判据
（`tests/test_wiring_readouts.py`：每格都验"值来自那条被判据"+ 打桩成空必红）。
`test_wiring_edges.py` 的 `KNOWN_ORPHANS` 已经清空 —— 双向台账两向都判过。

| # | 项 | 补线落点 | 判据（`tests/test_wiring_readouts.py`） | 反真空 |
|---|---|---|---|---|
| 1 | `programs` | `clock.now` 的 `programs` 格（`checked` / `count` / `running` / `rows` / `unbooked`；rows 每行带 `program` / `pid` / `elapsed_sec` / `state`） | `test_programs_are_visible_on_clock_now` | 把 `clock.programs` 打桩成空 ⇒ `running` 必须变 0 |
| 2 | `program_census` | `clock.coverage()` 的 `programs_outside_clock` / `programs_outside_where` / `programs_checked` / `programs_files_scanned`（`clock.now` 照原样念出来） | `test_programs_outside_clock_is_on_the_coverage_readout` | 打桩报 2 处 ⇒ 读数必须变 2；普查"没查成" ⇒ 那一格是 `None` 不是 0 |
| 3 | `read_wait_any` | `clock.wait_any` 的 `intents` 格（全量意图账：`checked` / `count` / `rows` / `reason`） | `test_wait_any_hands_back_every_intent_in_the_workspace` | 打桩成空 ⇒ `intents.count` 必须变 0 |
| 4 | `cancel_wait_any` | `agent_loop._park_gate`：这一拍真的要回模型时撤掉等待意图（`run.park.wait_cancelled`） | `test_the_loop_drops_the_intent_when_it_goes_back_to_the_model` | 把撤意图打桩成空操作 ⇒ 账上那一行必须还在 |
| 5 | `handoffs_reading` | `conductor.watch` 的 `silent_children` + `conductor.ledger` 的 `silent_children` / `silent_children_checked` / `silent_children_reason` | `test_the_silent_children_show_up_on_watch_and_ledger` | 把 `clock.read_handoffs` 打桩成空 ⇒ 两处都必须空 |
| 6 | `child_wait_invariant` | `conductor.watch` 的 `child_wait_invariant` + `conductor.status_report` 的同一名格子（逐父给 `active_children` / `waited` / `unwaited` / `problems`） | `test_the_invariant_is_read_out_by_watch_and_status_report` | 造一个没人等的活跃子代理 ⇒ `unwaited` 必须点名它 |

### 第 4 条为什么落在"回模型那一拍"而不是"第 5 档"里

`_park_gate` 的分支顺序决定了这件事：显式要求等 + 还有计时器 ⇒ 第 1 档挂机，
所以"有意图时还在跑模型"只发生在一种情形 —— 起意之后已经有东西回来了
（`wait_any_reading` 的 `requested` 与 `waiting` 都为假，但意图那一行还在账上）。
那一行是陈的：不撤，下一拍"我改主意了、手上有活"仍会被旧意图拖着，而 `requested`
永远为假 ⇒ 连"无事可做 ⇒ 交差"都判不出来。所以撤的动作放在"这一拍 skip_model 为假"
那一段（覆盖第 5 档与兜底档两处），而挂机与交差那两档不动 —— 那两档的意图正是这次
要用的东西。

### 这一批的读数

- `test_wiring_edges`：4 条全绿，`KNOWN_ORPHANS` **空**（实测孤儿集合 == 台账 == 空集）；
- `test_wiring_readouts`：6 条全绿（每格一条正控 + 一条反真空）；
- 六格的落点全都进了 `returns=` 声明（`clock.now` / `clock.wait_any` / `conductor.watch` /
  `conductor.ledger` / `conductor.status_report`），`test_tools_returns_declaration` 24 条全绿；
- `clock.coverage()` 顺手给 `program_census` 加了缓存（按扫描根做键、`refresh=True` 强制重扫）：
  没有缓存的话一次 `clock.now` 要把整棵 `src` AST 一遍（实测 254 个文件）。




