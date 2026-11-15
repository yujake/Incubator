# CC4 路交付报告：把真机研究跑的另外五条链改成同路径（2026-11-15）

- 仓库：`D:\Incubator`（git 根），交付物在 `agentflow/`；开工 HEAD = `5ccb2041`，工作树干净
- 本路目标：F 计划生命周期 / D 只递指针 / C4 打回修订环 / C9 概念图链 / C13 多轮唤醒 ——
  从 `cli.main(["start","--mode","research", …])` 进、只替换出网层（`modelgw.urllib_transport`），
  缝 / 账本 / 闸 / 收工门全是产品原物；Lean 按链的性质跑两档或单档（c13 单档并写明理由）
- 零真模型调用、零花费、未起真机；`D:\Incubator\projects\lp-ball` 未触碰（本机不存在该目录）
- 不动 FC-27（`git status` 只在 `agentflow/tests/` 与 `agentflow/temp/` 下；产品源码一个字节没改）
- 两处产品缺陷**没有改**，按门先报：见 §六

---

## 〇 一句话结论

**五条链全部从 CLI 入口真跑、只换出网层；三格、一行账、会话归口在各自跑的档里全部干净
（f/c4/d/c9 各 Lean 开+关，c13 关档），`CHAIN_ONLY` 从 10 降到 5。其中 C13 撞到一条真产品
缺口（研究跑的唤醒只写不叫，`wake_failed`），C4 撞到第二处（未在册稿的"洗稿转达"没有落点）——
两条都按"先报判断+方案"停在报告里，没有单方面改产品。**

---

## 一 改动清单（不新造判据）

| 文件 | 改动 |
|---|---|
| `tests/rehearsal_contract.py` | `CHAIN_ONLY` 摘掉这五条（10 → 5），判据与数据结构一个字没动 |
| `tests/test_rehearsal_f_plan_lifecycle.py` | 重写：CLI 入口 + M→D→F（三个实例）+ F 的步循环 + 真秘书 |
| `tests/test_rehearsal_c4_revision_loop.py` | 重写：CLI 入口 + F 交稿/送审/重写/再签，V 与 secretary:V 都是产品原物 |
| `tests/test_rehearsal_d_pointer_only.py` | 重写：CLI 入口 + F 拿签 → D 写携带单 → B 在 D 的 `calling_as` 里按指针收录 |
| `tests/test_rehearsal_c9_concept_graph.py` | 重写：CLI 入口 + C（工具分发）→ `analysis_reports` → D `own.ingest` → B 结构重复裁决 |
| `tests/test_rehearsal_c13_wake.py` | 重写：CLI `--rounds 2` + M 的 `conductor.wake_blocked` 逐条审批（含幂等与未批准） |

判据文件 `tests/test_rehearsal_same_path.py` 一个字没改：五份新彩排过它的全部静态判据
（打桩白名单 / 入口 / 自造替身 / 私有调用 / CHAIN_ONLY 完整性 / 文档引用），autouse 三格探针
逐条跑过（读数见 §二）。`tests/test_rehearsal_c*.py`（C1/C3/C10/C12）与
`test_rehearsal_cli_proof_main_chain.py` 一行没动。

---

## 二 ① 五条链：入口 / 替换点 / 三格 / 一行账 / 会话归口 / Lean

五条入口是同一行（只有 `--task` / `--sid` / 额外开关不同）：

```text
cli.main(["start", "--mode", "research", "--root", <tmp 工作区>, "--sid", <本链 sid>,
          "--subagents", "--task", <本链任务>, "--max-steps", N])
```

替换点只有两处（都在白名单内）：`modelgw.urllib_transport`（回预置 OpenAI 兼容 JSON）
+ `AGENTFLOW_MODEL_API_KEY` 给假值（env 档，只让"配置已就绪"成立）。

### 2.1 三格（`resolved = 显式 or ambient` / `caller_role` / `ledger_rows>0 & unattributed=0 & dangling=0`）

原文取自 `pytest -s` 的三格探针行（Lean 关档那一趟；开档逐字同）：

```text
f plan lifecycle  ask=56  live=56  ①56/56  ②['D','F']      live_meter=56  ③ledger_rows=60 unattributed=0 dangling=0
c4 revision loop  ask=28  live=28  ①28/28  ②['D','F','V']  live_meter=28  ③ledger_rows=32 unattributed=0 dangling=0
d pointer only    ask=22  live=22  ①22/22  ②['D','F','V']  live_meter=22  ③ledger_rows=25 unattributed=0 dangling=0
c9 concept graph  ask=24  live=24  ①24/24  ②['B','C','D']  live_meter=24  ③ledger_rows=27 unattributed=0 dangling=0
c13 wake          ask=8   live=8   ①8/8    ②['D']          live_meter=8   ③ledger_rows=9  unattributed=0 dangling=0
```

（`ledger_rows` 是三格那一份 `reconcile_usage` 的行数，含召唤级结算行；判据①只数
`note` 以 `source=llmseam;` 开头的真调用行，见 2.2。两者差 3~4 行是 summon 结算行。）

### 2.2 一行账（每笔真调用有且只有一行）

```text
f-plan    真调用=56  出网=56  账本行=56  duplicate=0 未配对=0 未认领=0   （Lean 1 / 0 各一遍，逐字同）
c4        真调用=28  出网=28  账本行=28  duplicate=0 未配对=0 未认领=0   （两档）
d-pointer 真调用=22  出网=22  账本行=22  duplicate=0 未配对=0 未认领=0   （两档）
c9        真调用=24  出网=24  账本行=24  duplicate=0 未配对=0 未认领=0   （两档）
c13       真调用=8   出网=8   账本行=8   duplicate=0 未配对=0 未认领=0   （单档）
```

### 2.3 会话归口（全部 `llm_call` 落在本趟 sid）

```text
f-plan    lean=1 本趟=56 别处=0   f-plan    lean=0 本趟=56 别处=0
c4        lean=1 本趟=28 别处=0   c4        lean=0 本趟=28 别处=0
d-pointer lean=1 本趟=22 别处=0   d-pointer lean=0 本趟=22 别处=0
c9        lean=1 本趟=24 别处=0   c9        lean=0 本趟=24 别处=0
c13       本趟=8 别处=0
```

### 2.4 Lean 两档

- f / c4 / d / c9：`AGENTFLOW_LEAN_ENABLED=1` 与 `0` 各跑完整一条链，三格 / 一行账 / 会话归口
  与盘上终态逐字相同；开档 `leanscope.lean_reading().verdict="on"`、关档 `"off"` 且名册里没有 L。
- c13：**单档（关档）**，理由写在文件 docstring 末节：唤醒链不产出手稿、不碰 `formal.*`、
  `wake_blocked` 的判定里没有 Lean 那一格；开档多跑一遍不会多出任何读数（两档唯一差别是
  名册里多一个 L，而 L 不在唤醒对象里）。

---

## 三 ② 每条链的盘上终态（`temp/cc4/readings.json`，机读；此处摘要）

### F 线 · 计划生命周期（56 次真调用，rc=0）

| 读数 | 值 |
|---|---|
| `attack_plans` | **8 行，全部 `abandoned`**：pA(000000) / pB(000001) / pC(000002) / pD(000003) / pE(000004) / pF(000005) / pH(000006) / pI(000007) |
| pA | history `[('proof',None), ('abandon','math_error')`，rounds=1，放弃行点名"第 3 步"（F 边交稿边走的 `attack.step`） |
| pC | history `[('no_change',None), ('abandon','difficulty')]`，`difficulty` 与 `salvaged=[{label:部分紧性, stmt_id:000051}]` 都落行 |
| pB / pI | 按 D 的建议放弃成「不再需要」，放弃行逐字带「D 的建议」 |
| pG（并发上限那一笔） | 没有落行：拒信逐字含业主原话（同时推进的plan个数已达上限2…），外层 `ok=True` + `data.created=False` + `refusal_reason=invalid_params`（动作层受控拒） |
| 「需要调整」那一笔 | 工具面按 `reason` 枚举拒：`ok=False`、`meta.kind=param_error`、错误里点名三个合法取值；pH 行一个字节没改 |
| 派活文本闸 | 把计划号写进派活文本 ⇒ `dispatch_names_a_conjecture_id` 受控拒（1 次）；只说方向 ⇒ 放行（3 次成功 summon） |
| 秘书 | `proposition_form.jsonl` 有 `role=F` 一笔（F 交稿过了形态闸）；`dispatch_fit.jsonl` 三笔（第一笔"不是一个方向"只提醒不拦，F1 照派） |
| 收工门 | F1/F2 的 `agent_run_end` 是 `final_refused`（盘上各有一条"未签未放弃"的计划，拒信点名计划号）、F3 是 `final`；M/D 都是 `final` |
| 台账 | `tasks`：M ok / D ok / F1、F2 `no_result` / F3 ok；`manuscripts/handoffs.jsonl` 2 条 D 的建议 + 1 条 M 的派活 |

### C4 · 打回修订环（28 次真调用，rc=0）

| 读数 | 值 |
|---|---|
| v1（sha1=`01976abd…`） | `pending/01976….jsonl` 一行：`defect_step=2`、`secretary_judge.axis=fault`、`verdict=成立`、`why="第 2 步的记号没有定义。"`；v1 **没有签文件**、稿上没有签块 |
| 回到 F 的下一步 | wire 记下 F 每一拍的 prompt：第 4 拍起逐字含「第 2 步的记号没有定义」（V 的 notice 在下一拍被读到）—— `defect_in_f_prompt=[F,F,F,T,T,T]` |
| 重写 | `attack.step` 的 `proof_mode`：`registered` → `rewritten`；v2（sha2=`85f84949…`）与 v1 的 `## 证明` 都是 3 行、**只有第 2 行不同**，第 2 行正是加了记号说明的那一版 |
| 再送审 | `pending/85f849….jsonl` 三行，轴全 `clean`；稿上签块 `连续=3/3`、`签名者=secretary:F`、`正文sha=85f849…`；`out/vsigns/85f849….json` + `issued.json` 在盘上，签里的 `artifact_sha` 就是新正文 sha |
| V 的两趟 | `proof_unregistered_rejected`（defect_step=2）→ `proof_unregistered_signed`（review_passes=3） |
| 收工 | F 的 `agent_run_end=final`（稿有现行签才放行）、M `final` |

### D 线 · 只递指针（22 次真调用，rc=0）

| 读数 | 值 |
|---|---|
| D 的携带单 | 报告 `reports/0000-research.md` 有「## 携带的证明手稿」一节：`\| mss:000000 \| reports/f-proof-000000.md \| ab4fefc3…（文件字节 sha）\|`，报告里没有抄 `## 命题` 的正文 |
| D→B 回执 | 同一份报告里「D 交给 B 的登记回执」：覆盖 1 条、**B 收下 1 条**，稿的来源 `carried_by_D`、秘书洗过 `是` |
| B 的收录 | `statements` 一行：`statement_full` 逐字等于稿的 `## 命题`、`manuscript_id=000000`、`kind=theorem`、`bits.proof=true`、`bits.reviewed=true` |
| 证据档 | `evidence_kind=heuristic` —— f-proof 族在"按稿收录"这一档的声明缺省就是它（`register_statement.py:6573`；E 的 e-proof 才是 proof）；真读数在 `bits` 上 |
| 依赖 | 0 行：稿的 `## 依赖` 是空表（声明自足）。"没依赖"与"依赖没写进去"分得开 |
| 路径号 | `manuscriptpaths.path_reading(stmt 000000).count=1`，第 1 条路径的载体是 `reports/f-proof-000000.md` |
| B 的秘书 | `out/secretary/B.jsonl`（判档）、`nontriviality.jsonl`、`statement_same.jsonl` 各一笔 —— 这些模型调用发生在 D 的 `calling_as` 里 |

### C9 · 概念图链（24 次真调用，rc=0）

| 读数 | 值 |
|---|---|
| `analysis_reports` | 三行：`000000 gaps`（C 的 `own.gaps` 自动登记、人读版）、`000001 gaps`（C 登记的机器可读版）、`000002 paths`（结构重复候选） |
| C 的读数 | `own.gaps` 采到 1 条结构洞候选（概念 0002/0003、关系 8 个）；`own.structural_duplicates` 采到候选（0000/0001 同名、0000/0008 异名…）；报告里的概念号 / 关系号都能在台账里查到 |
| D 的立题 | `research_questions` 一行：`qid=000000`、`origin=C:gaps:000001:0002,0003`、`related_concept_ids=['0002','0003']`；`own.consider` 把它推到 `researching` |
| B 的合并 | 0000/0001：`merge`、`survivor=0000`、`merged=0001`、`applied=True`；`statements` 里 0001 `status=superseded`（墓碑）、`quote_reason` 点名并入 0000；老表视图 0001 有 `merged_into` |
| B 的拒绝（反真空） | 0000/0008（邻域相同、名字不同）：`verdict=reject`、`applied=False`、概念表逐字不变（连墓碑都不落） |

### C13 · 多轮唤醒（8 次真调用，rc=0）

| 读数 | 值 |
|---|---|
| 多轮 | stdout「角色 M 自主跑完 2 轮」；两条 M 的 `agent_run_start`；每轮 `final` |
| 盘上 prereq | owner 行 `t-000001`（D，`status=block`）+ 板项 `t-000002`（`item_state=block`），由真生产者 `stopctl.block_remaining_tasks` 写下 |
| 第 1 轮（不带批准） | 回执逐条 `skip/not_approved`、`started=False`、`mark=""`、`state=refused`：一个字节没写、一次没叫 |
| 第 2 轮（批准） | 审计判 `resume`；板项 `block → queued`、`inputs` 多一条 `wake:t-000007@…`；但 `started=False`、`refusal_code=wake_failed`、`state=refused`，原因逐字「这一趟没有接执行侧（resume_runner 未接线）」 |
| 第 2 轮再叫一次 | `skip/not_blocked`、`mark=""`、不翻倍、不再叫 |
| 被唤醒的 D | owner 行仍是 `block`；没有它的 `agent_run_start`（**见 §六缺陷 1**）。会话里那条 D 起跑是 M 在第 1 轮派活的子代理 `t-000004` |

---

## 四 ③ 反真空（逐条）

| 链 | 反真空 | 造的是什么 | 必须红在哪 | 实测 |
|---|---|---|---|---|
| F | `test_an_open_plan_refuses_fs_final_and_a_wider_cap_would_not` | 同一个工作区：F1 发 final 时盘上两条"未签未放弃"的计划 | 收工门拒 final（`final_refused`、task `no_result`），拒信点名计划号；并发上限那一条不落行；把前面放弃后同类计划建得成 | F1/F2 `final_refused`（why 点名 pA / pI）；F3 `final`；`attack_plans` 8 行里没有 pG |
| C4 | `test_a_clean_second_pass_skips_the_rejection_and_the_rewrite` | 同一个 wire、同一份夹具，只把 `secretary:V` 的判定换成恒 `clean` | 打回与重写一起消失：第一份稿当场三转签住、`proof_mode` 只有 `registered`、v1 的 sha 上三行 pending、final 直接过 | `steps=1`、`pending` 里没有 fault、sha 的签文件在盘上、`standing=signed` |
| D | `test_an_unsigned_manuscript_is_refused_by_the_ingest_gate` | 同一条链，只把 V 的第二转判成 fault | B 的收录闸受控拒：`statements` 零新增、报告写「B 收下 0 条」、`pending` 有 `defect_step=2`、F 的 final 被拒 | `statements=[]`、`b_decisions` 非空（B 确实被叫到了）、carried 里那一条仍在（携带不是这一格的闸）、F `final_refused` |
| C9 | 正控里的第二对候选（0000/0008 邻域相同、名字不同） | 同一个工作区、同一趟：第一对判 merge 并落墓碑，第二对判 reject | reject 必须 `applied=False` 且概念表逐字不变（连墓碑都不落） | `reject`、`applied=False`、`concepts` 前后逐字相等；merge 那一条的墓碑与关系改写都在 |
| C13 | `test_without_the_token_the_wake_writes_nothing` | 同一趟三轮里的第一轮：不带 `approve="yes"` | 逐条 `not_approved`、`started=False`、`mark=""`、`state!=woken`；盘上唯一的 `wake:` 落痕来自"批准"那一趟 | 第一趟 `not_approved`/`mark=""`；items 里唯一一条 `wake:` 等于第二趟回执里的 `mark` |

---

## 五 ④ 剩余 `CHAIN_ONLY`（10 → 5；每条一句"它没证明什么"）

登记表在 `tests/rehearsal_contract.py::CHAIN_ONLY`，两条判据钉着它（登记必须确实不是同一条路；
不得被文档引用为「彩排已走通」）。本 HEAD 上 `test_rehearsal_same_path.py` 49 passed。

| 文件 | 链 | 它没证明什么（不能当真机前置的理由） |
|---|---|---|
| `test_rehearsal_c2_proof_chain.py` | C2 · 证明主链 | 三个角色直调 + `_Seam`/`_Review`/`_FakeF` + 打桩 `vsigns.issue` ⇒ 真机循环里的三签次序与三格没证明（已由 `test_rehearsal_cli_proof_main_chain.py` 替代） |
| `test_rehearsal_b_intake_exits.py` | C5 · B 收编的形态闸 / 同一性门 | 直调 `register_statement` / `rewrite_manuscript_proposition`，打桩 `replace_section` 与私有形态闸 ⇒ "这些判断在真机步循环里同号同账"没证明 |
| `test_rehearsal_b_multi_path.py` | C6 · 同命题多路径 | 直调 `ingest_manuscript` + 手工 `Secretary` + `b_form_gate_ok` ⇒ 真机里 F 自己交第二份、B 的循环收没证明 |
| `test_rehearsal_two_f_independent_proofs.py` | 双 F · 独立第二份证明 | 直调 B + 手工秘书 + `manuscript_id_for_path` / `signed_v_handoffs` ⇒ 第二份证明由 F 自己交、B 收没证明 |
| `test_rehearsal_c11_formal.py` | C11 · 形式化链 | 走工具层 `build_registry().call("formal.*")`、打桩 `check_formal` / `detect_verifier` / `AgentL.check_formal` ⇒ 真机 `run-agent L` / 研究链的装配与账本没证明 |

---

## 六 ⑤ 撞到的产品缺陷 / 行为（判断 + 方案 + 停在哪）

### 缺陷 1（真缺陷，已报未改）：研究跑的唤醒"只写不叫"——`resume_runner` 没接

- **读数**（`temp/cc4/readings.json` → `c13_wake.wakes[1]`）：批准那一趟审计判 `resume`、板项
  `block → queued`、`wake:` 落痕写进 `inputs`，但 `started=False`、
  `refusal_code=wake_failed`、`why` 逐字「这一趟没有接执行侧（resume_runner 未接线）」，
  owner 行仍 `block`、没有它的 `agent_run_start`。
- **定位**：全仓只有一处 `cond.resume_runner = cond.resume_dispatched`（`host.py:406`，
  `host.wired_conductor`）；`start --mode research` / `run-agent` 走的是
  `host.wired_llm_conductor`（`host.py:453`），它建了 `LlmBackend`、把它换到
  `conductor.backend`，但**没有**接执行侧。于是 M 的工具面上有 `conductor.wake_blocked`
  （`conductor_tools.py` 把它挂给 M），研究跑里却永远只能写不能叫。
- **方案**（一处一行的接线，与 `wired_conductor` 同形）：在 `wired_llm_conductor` 里
  `conductor.backend = backend` 之后加
  `conductor.resume_runner = conductor.resume_dispatched`（后台线程跑，`resume_dispatched`
  本来就不抛）。代价：唤醒会在同一进程里起一个同号循环 —— 那正是 `wired_conductor`
  那一档已经在做的事（"静默的唤醒 = 接到消息"）。
- **停在哪**：按门"必要产品改动先报"，**没有改产品**；彩排按产品今天的实际三态判
  （`started=True` 就要求真起跑；`started=False` 就必须点名 `wake_failed` 且原因是没接执行侧）。
  修好之后这一条自动走前一支，判据不用改。

### 缺陷 2（真缺口，已报未改）：未在册稿的"洗稿转达"没有落点

- **读数**：`agent_v/core.py:2478-2481` 只在**已在册**那一档（`record_verification`）调
  `_wash_v_reply` 并传 `washed_relay`；F 的稿在收录前是**未在册**的，走
  `record_pending_sign`（`core.py:3236/3269`），那两处不接 `washed_relay`（`verifications.py`
  的 pending 写口也没有这一格）。实测：C4 那一趟的 `pending/<sha1>.jsonl` 有
  `secretary_judge.axis=fault`，但 `washed_relay` 一格都没有；`out/secretary/V.jsonl` 里也只有
  `v_reply_defect` 的决定行，没有 `wash_v_reply` 的决定行。
- **后果**：主路（F 的稿几乎总是先未在册）上，「秘书洗稿 → 转达给 F」这一步**并不发生**：
  F 拿到的是 V 自己的结论（真机由 V 的模型在 final 里写成人话，经 notice 投到下一拍），
  `secretary:V` 的语义判定只落在台账的 `secretary_judge` 里。
- **方案**：在未在册那一支照已注册那一支的做法，先 `wash = self._wash_v_reply(...)`（同一条
  `axis == fault` 且 `fault_kind` 不是 procedural/style 的条件），再把 `washed_relay=wash` 传给
  `record_pending_sign`，pending 写口补这一格（与 `record_verification` 同形）。这是三处小改，
  但改的是"V 的判词怎么到 F"这一条主路 ⇒ 先报。
- **停在哪**：**没有改产品**；C4 彩排按实际行为钉住（F 的下一拍确实带着那句意见，
  但它是 V 的 final / notice，不是洗过的转达），并在文件 docstring 里写明。

### 行为 3（不是缺陷，但要写清）：派活文本里点名 6 位号会被 `dispatchpolicy` 拒

F 线彩排里第一次派 F2 时把计划号（`000001`）写进了 `summon.task`，被
`dispatch_names_a_conjecture_id` 受控拒（业主 2026-11-08 那条闸）。真机上 D 的派活只能
只说方向；计划号要写就写进 `handoff`（建议，不走派活文本）。彩排因此把这条**当成反真空**
钉住（写号 ⇒ 拒；只说方向 ⇒ 放行），并让 F2 用 `attack.list_plans` 按 `problem_key` 自己
找号 —— 旧彩排用 `Secretary.handoff_add` 直调恰好绕过了这条闸，它的 F 也不会知道派活被拒过。

### 行为 4（不是缺陷，但旧彩排的夹具不成立）：D 线的"依赖三列"在真机上要第二份签过的稿

旧 D 线彩排预置了一条"可引命题"然后断言依赖三列。真机主路上走不通：V 会审这份稿，
引用闸要求被引的那条命题**自己也有一份盘上手稿**（`reports/f-proof-<号>.md`），否则
`citation_level_unreadable` ⇒ 整份稿判「有毛病」、签不下来。旧夹具那条预置命题没有手稿，
所以它只适合"直调 B"那一条低一层的路。新彩排把这一格缩成"空表声明自足"（`dependencies`
0 行），并在 docstring 里点名这件事；要让三列在真机上成立，得先有第二份真拿签的手稿
（E/F 的另一条交付），那是另一条链。

### 行为 5（不是缺陷）：长工具结果在 prompt 里被观测层截断

C9 的 `own.gaps` 回执（`AnalysisReport` 的 repr）约 11.5k 字，prompt 只给前 5944 字并附
"这是观测层的截断，不是内容没了"。真机模型因此读不到完整的候选（`related_relation_ids`
被切在中间）。新彩排按真机的做法办：C 用看得见的那几个字段登记一份**机器可读的紧凑报告**
（`analysis.register_report`，这是只读角色唯一的写入口），D 用
`table.list(filter, fields)` + `table.get` 去读紧凑的那一份 —— 报告里把这条截断写清楚，
没有假装模型能读到全文。

---

## 七 门（原文）

### 7.1 本路相关测试

```text
五份新彩排（f/c4/d/c9/c13）                    35 passed（约 2m20s，含三格探针）
tests/test_rehearsal_same_path.py              49 passed
全部彩排文件（16 份，含 CHAIN_ONLY 里剩下的 5 份） 161 passed（5m11s）
```

### 7.2 lint

```text
$ python scripts/lint_rules.py
[linter] error 0 / warning 21 / info 44
```

（中途 R009 报 5 个 error —— 新文件 docstring / 注释里的 Markdown 强调标记；逐处去掉成对
星号后归零，没有 skip / xfail / 放宽任何规则。）

### 7.3 三格（`tools/repo_survey.py --json`）

```text
>800 行文件 75（上限 75）、>200 行 def 94（上限 95）、重复 docstring 段 2（上限 5）
```

一格未抬（新文件都远不到 800 行；新函数都远不到 200 行）。

### 7.4 noai_gate / FC-27

```text
$ python scripts/noai_gate.py --git
[clean] required_approvals=0
clean：6 条改动路径均未命中禁改区（清单 49 条）⇒ 无需额外人工批准。
```

`git status` 只在 `agentflow/tests/` 下（判据、五份彩排、登记表），**产品源码一个字节没改**
⇒ FC-27 的七个分区一个都没碰（两条产品缺陷也因此按门停在报告里）。

---

## 八 ⑥ 一句结论：真机研究跑会踩的链，现在还有哪条没同路径

**本批五条（F 计划生命周期 / D 只递指针 / C4 打回修订 / C9 概念图 / C13 多轮唤醒）已经同路径
（CLI 入口 + 真 `LlmSeam` + 只换出网层，三格 / 一行账 / 会话归口全绿）**；连同此前的证明主链、
C1 文献、C3 数值（腿通、收工门被已修的 EC 缺陷挡住那一格已解）、C10 成文审校、C12 收工门，
真机研究跑的主路现在都有同路径彩排。**还差的不是彩排，而是产品本身的两处接线 / 落点**：
C13 的唤醒执行侧（缺陷 1）与 C4 的洗稿转达（缺陷 2）—— 两条都已在 §六 给出定位与一行/三行
改法，等业主裁定后由人改或人逐行走查。
