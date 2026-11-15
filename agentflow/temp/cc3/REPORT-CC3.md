# CC3 路交付报告：把真机研究跑的另外四条链改成同路径（2026-11-15）

- 仓库：`D:\Incubator`（git 根），交付物在 `agentflow/`；开工 HEAD = `998b7e31`，工作树干净
- 本路目标：C1 文献链 / C3 数值链 / C10 成文审校回路 / C12 收工链+七格门 —— 从 CLI 入口进、
  只替换出网层（`modelgw.urllib_transport`），缝 / 账本 / 闸 / 收工门全是产品原物；Lean 开/关各一档
- 零真模型调用、零花费、未起真机；`D:\Incubator\projects\lp-ball` 只读（`git status -- projects` 空）
- 不动 FC-27（`git diff` 只在 `agentflow/tests/` 下；产品源码一个字节没改）
- 一份必要的产品改动**没有做**，先报后等：见 §三「C3 的 E 收工门跨族撞号」

---

## 〇 一句话结论

**四条链全部从 `cli.main(["start","--mode","research", …])` 真跑，只换出网层；三格、一行账、
会话归口在 Lean 开/关两档都干净。其中 C1 / C10 / C12 的链级终态是完整的；C3 的三段腿
（实验 / 签 / 收编）完整，但 E 自己的 final 被一个**真实产品缺陷**挡住（跨族稿号撞号 ⇒
`ambiguous_path`），所以 C3 只能算「同路径、腿通、收工门未通」。**

---

## 一 复用与改动（不新造判据）

| 文件 | 改动 |
|---|---|
| `tests/rehearsal_contract.py` | 把 RC2 写在证明主链里的五个读数函数（`session_calls` / `ledger_identity` / `session_split` / `one_row_per_call_problems` / `session_problems`）搬到这里，**一份实现**给五条 CLI 彩排共用；`CHAIN_ONLY` 摘掉 C1/C3/C10/C12 四条（14 → 10） |
| `tests/test_rehearsal_cli_proof_main_chain.py` | 只把本地那五个函数换成对契约的引用（行为逐字不变；9 passed 复跑过） |
| `tests/test_rehearsal_c1_literature_chain.py` | 重写为 CLI 入口 + 真 `.txt` 抽取 + `--provider fixture`（旧版入口低一层、且打桩 `locallib.extract_text`） |
| `tests/test_rehearsal_c3_numeric_chain.py` | 重写为 CLI 入口 + `verify.run_experiment` / `verify.verify_proof` / `own.ingest_manuscript` |
| `tests/test_rehearsal_c10_writing.py` | 重写为 CLI 入口 + `doc.*` / `review.*` / `own.revise`（旧版直调 G/H 且打桩 `scan_document`） |
| `tests/test_rehearsal_c12_closing.py` | 重写为 CLI 入口 + M 在真循环里调 `conductor.closing`（旧版手工造 `AgentLoop` 并直调私有 `_v_wait_gate_reading`） |

判据文件 `tests/test_rehearsal_same_path.py` **一个字没改**：新四份过它的全部静态判据
（打桩白名单 / 入口 / 自造替身 / 私有调用 / CHAIN_ONLY 完整性 / 文档引用），并且
autouse 三格探针（`is_rehearsal_module` 现在对它们为真）逐条跑过。

---

## 二 ① 四条链：入口 / 替换点 / 三格 / 一行账 / 会话归口（Lean 开与关各一份）

四条的入口命令相同（只有 `--task` / `--sid` 不同）：

```text
cli.main(["start", "--mode", "research", "--root", <tmp 工作区>, "--sid", <本链 sid>,
          "--subagents", "--task", <本链任务>, "--max-steps", N])
```

替换点只有两处（都在白名单内）：
`modelgw.urllib_transport`（回预置 OpenAI 兼容 JSON）+ `AGENTFLOW_MODEL_API_KEY` 给假值
（env 档，只让"配置已就绪"成立）。

### 2.1 三格（`resolved = 显式 or ambient` / `caller_role` / `ledger_rows>0 & unattributed=0`）

原文取自 `python -m pytest <file> -q -s`（读数行逐字）：

```text
[三格] …c1…::test_the_literature_chain_runs_from_the_cli_with_only_the_wire_replaced  ask 次数=10  live=10
[三格] …c1…  ①resolved=10/10  ②caller_role=['A', 'B']  live_meter=10  ③ledger_rows=13 unattributed=0 dangling=0
[三格] …c1…[1]  同上  ①resolved=10/10  ②caller_role=['A', 'B']  ③ledger_rows=13 unattributed=0 dangling=0
[三格] …c3…::test_the_numeric_chain_runs_from_the_cli_with_only_the_wire_replaced  ask 次数=22  live=22
[三格] …c3…  ①resolved=22/22  ②caller_role=['B', 'E', 'V']  live_meter=22  ③ledger_rows=25 unattributed=0 dangling=0
[三格] …c10…::test_the_writing_chain_runs_from_the_cli_and_h_closes_it  ask 次数=21  live=21
[三格] …c10…  ①resolved=21/21  ②caller_role=['G', 'H']  live_meter=21  ③ledger_rows=25 unattributed=0 dangling=0
[三格] …c12…::test_the_closing_gate_passes_all_seven_cells_from_the_cli  ask 次数=5  live=5
[三格] …c12…  ①resolved=5/5  ②caller_role=['H']  live_meter=5  ③ledger_rows=6 unattributed=0 dangling=0
```

每条链的 Lean 开 / 关两档读数**逐字相同**（开关不改变这三格）：C1 `10/10`、C3 `22/22`、
C10 `21/21`、C12 `5/5`；格②在三档里都非空（`['A','B']` / `['B','E','V']` / `['G','H']` /
`['H']`）。反真空那几条也成立（C3 形态闸坏那一趟 `6/6`；C1 空书架 `10/10`）。

### 2.2 一行账（每笔真调用有且只有一行）

```text
[一行账] c1  lean=1 真调用=10 出网=10（另一次抽取走 modelclient，不经 LlmSeam） 账本行=10 duplicate=0 未配对=0 未认领=0
[一行账] c1  lean=0 真调用=10 出网=10（同上） 账本行=10 duplicate=0 未配对=0 未认领=0
[一行账] c3  lean=1 真调用=22 出网=22 账本行=22 duplicate=0 未配对=0 未认领=0
[一行账] c3  lean=0 真调用=22 出网=22 账本行=22 duplicate=0 未配对=0 未认领=0
[一行账] c10 lean=1 真调用=21 出网=21 账本行=21 duplicate=0 未配对=0 未认领=0
[一行账] c10 lean=0 真调用=21 出网=21 账本行=21 duplicate=0 未配对=0 未认领=0
[一行账] c12 lean=1 真调用=5  出网=5  账本行=5  duplicate=0 未配对=0 未认领=0
[一行账] c12 lean=0 真调用=5  出网=5  账本行=5  duplicate=0 未配对=0 未认领=0
```

C1 的例外只有一处、且是**真机同款**：B 的抽取走 `modelclient.client_from_env`（`host.b_extractor`
的唯一装配点），那条路不经 `LlmSeam`，所以不出 `llm_call` 事件；判据把它从"真缝调用"里分出去
（`_Wire` 给每次请求打 `kind=seam|extract`），并把抽取那一笔从链的六条读数里单独核
（`quotes_verified=1` / `concepts_created=2`）。这不是放宽：判据①问的是"每一笔真缝调用"。

### 2.3 会话归口（全部 `llm_call` 落在本趟 sid）

```text
[会话归口] c1  lean=1 本趟=10 别处=0 会话=['cc3-c1']
[会话归口] c1  lean=0 本趟=10 别处=0 会话=['cc3-c1']
[会话归口] c3  lean=1 本趟=22 别处=0 会话=['cc3-c3']
[会话归口] c3  lean=0 本趟=22 别处=0 会话=['cc3-c3']
[会话归口] c10 lean=1 本趟=21 别处=0 会话=['cc3-c10']
[会话归口] c10 lean=0 本趟=21 别处=0 会话=['cc3-c10']
[会话归口] c12 lean=1 本趟=5  别处=0 会话=['cc3-c12']
[会话归口] c12 lean=0 本趟=5  别处=0 会话=['cc3-c12']
```

（`temp/cc3/pytest_readings.txt` 是这四份 `-s` 的完整输出，`temp/cc3/readings.json` 是
盘上终态的机读读数。）

---

## 三 ② 每条链的盘上终态（`temp/cc3/readings.json`，Lean 关=开，此处并写）

### C1 · 文献链（`tests/test_rehearsal_c1_literature_chain.py`，9 passed）

| 读数 | 值 |
|---|---|
| `rc` | 0 |
| `search_requests` | 2 行：`("no_results", "abelian group")`（查过、没有）+ `("ok", "notes")`（本地收录那一笔） |
| `literature` | 1 行：`path="notes.txt"`、`processed=True`（`library/notes.txt` 真在盘上） |
| `relations` | 1 行：`status="active"`、`quote_reason="逐字命中（substring_match，窗口 declared:1-1…"` |
| `conceptrows` | 2 行：`abelian group` / `group` |
| B 的 `run_once` | `processed=1, concepts_created=2, relations_added=1, quotes_verified=1, quotes_failed=0` |
| `tasks` | M/A/B 三行 `outcome="ok"`（B 由 A 派：`A→B` 是真边） |
| 钱 | `ledger_rows=13`、`unattributed.count=0`、`dangling=[]`、`equal=True` |
| 会话 | 11 次出网（10 次真缝 + 1 次抽取），10 条 `llm_call` 全在 `sessions/cc3-c1.jsonl` |

### C3 · 数值链（`tests/test_rehearsal_c3_numeric_chain.py`，8 passed）

| 读数 | 值 |
|---|---|
| `rc` | 0 |
| `experiments` | 2 行：`000000 / numeric / supports / cross_check`、`000001 / exhaustive_search / supports / proof` |
| 稿 | `reports/e-num-000000.md`（`## 命题` + `## 数值结果`）、`reports/e-proof-000000.md`（`## 证明` 非空） |
| 签 | `out/vsigns/acd8c7ed…b2859.json` + `issued.json`；`review_passes=[1,2,3]`；`kind="proof_unregistered_signed"`；pending 台账 3 行、`path_group` 全是 1 |
| `statements` | 2 行：`000000 / conjecture / cross_check / bits.numeric=verified / proof_list=[1]`；`000001 / theorem / proof / bits.numeric=pending / proof_list=[1]`；路径读数 `count=1`、`path_group=1` |
| E 的 task | `outcome="no_result"` —— **E 的 final 被收工门拒**：`complete=false`、问题是「这一份 e-proof 没有现行的 V 签（ambiguous_path）」 |
| 钱 | `ledger_rows=25`、`unattributed.count=0`、`dangling=[]`、`equal=True` |

**这个 `ambiguous_path` 是本路发现的产品缺陷（不是彩排造出来的）**：
`manuscriptclosing.signed_candidates` 按 `manuscript_id` 单独分桶，而 E 的两族稿各有独立号段
（`e-proof` 与 `e-num` 都从 `000000` 起）⇒ 同一工作区里同时存在
`reports/e-num-000000.md` 与 `reports/e-proof-000000.md` 时，两份候选共用一个稿号 ⇒
`state="ambiguous_path"` ⇒ E 收不了工。V 的签与 B 的收编不受影响（上面两行都已落盘）。
修法要动 `manuscriptclosing`（候选带上 family、按 `(family, manuscript_id)` 分桶）与
`agent_loop`（`_v_wait_gate_reading` 的 `cands` 也按 family 索引、`_sign_gate_e` 逐族判）——
**两处产品改动，先报后未做**（本路没单方面改产品）。这一条已经用 `send_message` 报给上级。

### C10 · 成文/审校回路（`tests/test_rehearsal_c10_writing.py`，8 passed）

| 读数 | 值 |
|---|---|
| `rc` | 0 |
| `documents` | 1 行：`doc_id=000000`、`status="unresolved_review"`、`review_rounds=2`、`markdown_path="documents/000000.md"`（在盘上） |
| `claims` | `claim-1`，`disclaimer="数值交叉验证，不构成证明"`（合规） |
| H 首审 | `verdict="rejected"`；`review_findings` 1 行：`000000 / dangling_dep / error / open / target=000000` |
| `dependencies` | 1 行：`000000 / used_by="doc:000000" / status="dangling"`（G 自己登记的外部定理，拿不到） |
| G 修订 | `own.revise` 回执 `status="revised"`（真改稿、真重渲染） |
| H 复审 | `review.verify_fixes(close_as="unresolved_review")` ⇒ `verdict="unresolved_review"`、`still_open=[("dangling_dep","error")]`、`documents.status="unresolved_review"` |
| 钱 | `ledger_rows=25`、`unattributed.count=0`、`dangling=[]`、`equal=True` |

### C12 · 收工链 + 七格门（`tests/test_rehearsal_c12_closing.py`，8 passed）

| 读数 | 值 |
|---|---|
| `rc` | 0 |
| M 的 closing 回执 | `m_says_done=True`、`can_close=True`、`closable=True`、**`machine_pass=True`**、`failed=[]`、`unknowns=[]` |
| 七格 | `acceptance / artifact_ledger / contradictions / load_bearing / report_shape / substance / user_pending` 全 `pass`（键集取自产品 `closing.DEFAULT_CHECKS`） |
| 判据落盘 | `verdict_written={"tried":true,"ok":true,...}`；`out/review/m-verdicts.jsonl` 一行：`met=true`、`sid="cc3-c12"`、`who="M"`、`counts={done:1,total:1}` |
| 派活 | H 一行 `outcome="ok"`、被 M 销号；M 的 final 过 `_final_gate_reading`（整树已销号） |
| 钱 | `ledger_rows=6`、`unattributed.count=0`、`dangling=[]`、`equal=True` |

Lean 开/关两档 `machine_pass` 都是 `True`：夹具里有 T3 形态的实验行（`method=formal` +
检查器原话），所以 `load_bearing` 在开档也算有背书 —— 这是
`test_load_bearing_without_lean.py::test_machine_pass_can_become_true_on_a_lean_off_workspace_with_evidence`
那条单点判据在链级上的对应物。

---

## 四 ③ 反真空（逐条）

| 链 | 反真空 | 造的是什么 | 必须红在哪 | 实测 |
|---|---|---|---|---|
| C1 | `test_a_quote_that_is_not_verbatim_turns_the_chain_red` | 预置抽取回复的 `quote` 换成原文里没有的句子（真 `LLMExtractor` 的逐字回验是产品本体，一个字没改） | `relations` 0 行、链判据非空 | `relations=[]`、`relations_added=0`、`concepts_created=2`（抽取真的跑过）⇒ `_chain_problems` 报「relations 应恰好 1 行」；文献仍 `processed=True`（只红在关系那一格） |
| C1 | `test_an_empty_books_dir_turns_the_chain_red` | `books_dir` 指向空目录（A 的输入变了，A 的实现不变） | `literature` 0 行、链判据非空 | `literature=0`、`processed=0`、`relations=[]` ⇒ 判据报「literature 应恰好 1 行」 |
| C3 | `test_a_broken_producer_form_gate_turns_the_chain_red` | 预置回复把形态判定说成"形态不合规"（真 `_NumericProofFormGate` + 真秘书，只换模型那句话） | experiments / e-proof 稿 / statements 一个字节都不落 | `experiments=[]`、`reports` 无 `e-proof-*`、`statements=[]`、工具回执 `ok=False` 且拒信带受控码（`proposition_form`）；形态台账留 `role=E` 一行 |
| C10 | `test_without_close_as_h_does_not_close_the_document` | 同一条链、同一份盘，只把 H 复审时的 `close_as` 拿掉 | 判决落回 `revise_again`、`documents.status="in_review"`、盘上无 `unresolved_review` | `verdict="revise_again"`、`status="in_review"`、`still_open=[("dangling_dep","error")]`；H 首审 / G 修订两条腿不退化 |
| C12 | `test_one_red_cell_turns_machine_pass_false_while_m_still_says_done` | 开跑前用产品自己的 `userio.ask_user(..., sid=本趟)` 登记一个没被回答的问题 | 只 `user_pending` 一格 fail ⇒ `machine_pass=False`，其余六格仍 pass | `status={"user_pending":"fail", 其余 6 格 "pass"}`、`machine_pass=False`、`failed=["user_pending"]`；`m_says_done=True`、`closable=True`（两条轴分开） |

「每一格单独造红」的形态**没有**搬进来：单点判据仍在 `tests/test_closing_gate.py`
（每格一条负控 + 一条反真空），本路只借一格证明链级 `machine_pass` 承重。

---

## 五 ④ 剩余 `CHAIN_ONLY`（14 → 10；每条一句「它没证明什么」）

登记表在 `tests/rehearsal_contract.py::CHAIN_ONLY`，两条判据钉着它（登记必须确实不是同一条路；
不得被文档引用为「彩排已走通」）。判据在本 HEAD 上 25 passed。

| 文件 | 链 | 它没证明什么（不能当真机前置的理由） |
|---|---|---|
| `test_rehearsal_b_intake_exits.py` | C5 · B 收编的形态闸 / 同一性门出口 | 直调 `AgentB.register_statement` / `AgentF.rewrite_manuscript_proposition`，还打桩 `replace_section` 与私有形态闸 ⇒ 这些判断在真机步循环里同号同账这一步**没证明** |
| `test_rehearsal_b_multi_path.py` | C6 · 同命题多条证明路径 | 直调 `ingest_manuscript` + 手工 `Secretary` + `b_form_gate_ok` ⇒ 真机里 F 自己交第二份、B 收那一段**没证明** |
| `test_rehearsal_c2_proof_chain.py` | C2 · 证明主链 | 三个角色直调 + `_Seam`/`_Review`/`_FakeF` + 打桩 `vsigns.issue` ⇒ 三签次序与三格**没证明**（已由 `test_rehearsal_cli_proof_main_chain.py` 替代） |
| `test_rehearsal_c4_revision_loop.py` | C4 · 打回修订环 | 直调 `step` + 私有 `f._hand_proof`；缝是自造替身 ⇒ 打回消息经秘书洗稿到 F 下一步**没证明** |
| `test_rehearsal_c9_concept_graph.py` | C9 · 概念图链 | 直调 C/D/B，反真空还换 `AgentC.gaps` ⇒ 这些方法由模型经工具分发调到**没证明** |
| `test_rehearsal_c11_formal.py` | C11 · 形式化链 | 走工具层 `build_registry().call("formal.*")`、打桩 `check_formal`/`detect_verifier`/`AgentL.check_formal` ⇒ 真机 `run-agent L` / 研究链的装配与账本**没证明** |
| `test_rehearsal_c13_wake.py` | C13 · 停机 / 唤醒 | 直调 `wake_blocked` + 私有 `_stop_before_round`，打桩 `wake_on_lifeline`/`pending_questions` ⇒ 真机多轮驱动里这些判断被调用**没证明** |
| `test_rehearsal_d_pointer_only.py` | D 线 · 指针式登记 | 直调 `read_carried_manuscript` + `ingest_manuscript`，缝是自造 `_Seam` + `b_form_gate_ok` ⇒ D 在真机循环里递指针、B 的秘书在 `calling_as` 里判档**没证明** |
| `test_rehearsal_f_plan_lifecycle.py` | F 线 · 计划生命周期 | 直调 `create_plan/step/abandon_plan`，打桩 `_judge_core`/`_write_plan`/`PARALLEL_PLANS_LIMIT` ⇒ 真机 F 的步循环与秘书判断**没证明** |
| `test_rehearsal_two_f_independent_proofs.py` | 双 F · 同命题独立第二份证明 | 直调 B + 手工 `Secretary`，打桩 `manuscript_id_for_path`/`_optimization_replace_enabled` + `b_form_gate_ok`/`signed_v_handoffs` ⇒ 第二份证明由 F 自己交、B 的循环收**没证明** |

这 10 份**没有**被本路改写（只为好看而批量改写会稀释「同路径」的判据）；它们继续留在
`CHAIN_ONLY`，判据继续禁止把它们当「真机前置证据」。

---

## 六 ⑤ 结论：真机研究跑会碰到的链，现在哪几条同路径、哪几条还不能

- **已经同路径（CLI 入口 + 真 LlmSeam + 只换出网层，三格/一行账/会话归口全绿）**：
  **证明主链 a / 指针收录线 b**（RC2+VF 那两条）、**C1 文献链**、**C10 成文审校回路**、
  **C12 收工链 + 七格门（machine_pass 能为真，Lean 开/关两档）**。
- **同路径、但收工那一格还不通（产品缺陷，未修）**：**C3 数值链** —— 实验 / V 签 / B 收编
  三段都真走通、三格与两条账判据全绿；但 E 自己的 final 被
  `ambiguous_path`（E 两族稿号都从 000000 起，`signed_candidates` 跨族按单号分桶）挡住。
  要它变成「完全通」，必须先修 `manuscriptclosing` + `agent_loop` 两处（本路已报，未单方面动）。
- **仍然不能当同路径**：`CHAIN_ONLY` 里剩下的 10 份（C5 / C6 / C2 / C4 / C9 / C11 / C13 /
  D 线 / F 线 / 双 F）。它们证明的是「某段函数单独能跑」，不是「真机那条路能跑」。
- 边界（与 RC2/VF 同一句）：这一路验证的是入口 / 装配 / 缝的类型 / 记账四层一致；
  **出网那一端**（真重试、真超时、真拒答、真计价）仍然只有真机那一趟能回答。

---

## 七 门（原文）

### 7.1 本路相关测试

```text
tests/test_rehearsal_same_path.py + test_rehearsal_cli_proof_main_chain.py
  + c1 + c3 + c10 + c12                                   76 passed（163.62s）
剩余 10 份旧彩排 + test_ledger_identity_antivacuum.py     67 passed（72.25s）
```

### 7.2 lint

```text
$ python scripts/lint_rules.py
[linter] error 0 / warning 21 / info 44
```

（中途 R009 曾报 4 个 error —— 新彩排 docstring 里的 `**…**` 强调标记；按"要强调就写进句子"
逐处改成普通文字后归零。没有 skip / xfail / 放宽任何规则。）

### 7.3 三格（`tools/repo_survey.py --json`）

```text
>800 行文件 75（上限 75）、>200 行 def 94（上限 95）、重复 docstring 段 2（上限 5）
```

一格未抬（读数函数加在已经 >800 行的 `rehearsal_contract.py` 里，不新增 >800 文件；
新函数都远不到 200 行）。

### 7.4 noai_gate / FC-27

```text
$ python scripts/noai_gate.py --git --since 998b7e31
[clean] required_approvals=0
clean：12 条改动路径均未命中禁改区（清单 49 条）⇒ 无需额外人工批准。
```

`git diff --stat 998b7e31..HEAD` 只在 `agentflow/tests/` 与 `agentflow/temp/` 下（判据、彩排、
报告与读数），**产品源码一个字节没改** ⇒ FC-27 的七个分区一个都没碰。
