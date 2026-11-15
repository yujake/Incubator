# RS 路 · 全流程彩排（2026-11-15，offline 假缝）

> ## ⚠ 2026-11-15 RC2 更正：本文件下半部分那张表**不能**当"真机前置证据"读
>
> `temp/sp/REPORT-SP.md` 的审计（RC2 复核过）把这张表里那 14 份 `test_rehearsal_*.py`
> 逐份判成**不是真机同一条路**：入口是 `Conductor.summon` / 直接调 `AgentX`（没有
> `_run_spec` → `LlmBackend` → `AgentLoop.run`），模型那一层是自造 `_Seam(ask_json)`
> 替身（没有 meter / 不落账 / 不读 ambient），`LlmSeam.ask` 只被调用过 2 次、
> `AgentLoop.run` 0 次、11 份账本 0 行。
>
> 从本文件起，那 14 份的读数一律读作「**方法层读数**」：它们证明某一段函数单独能跑，
> 不证明真机那条路能跑。契约与登记表在 `tests/rehearsal_contract.py`（`CHAIN_ONLY`），
> 判据在 `tests/test_rehearsal_same_path.py`，本轮真路径彩排与读数见
> `temp/rc2/REPORT-RC2.md`。
>
> 表里"本轮"那一列已按这个口径改写；第 20 行（证明主链）现在有一条**从 CLI 入口 +
> 真 `LlmSeam` + 只换网线**的彩排（`tests/test_rehearsal_cli_proof_main_chain.py`），
> 它才是主链的机器证据。

> ## ⚠ 2026-11-15 CC3 更正：表里四行（#6 C1 / #7 C3 / #10 C10 / #12 C12）已改造成同路径
>
> 这四份 `test_rehearsal_*.py` 已重写为「从 `cli.main(["start","--mode","research", …])` 进、
> 只替换 `modelgw.urllib_transport`」的彩排，`CHAIN_ONLY` 从 14 条降到 10 条；它们的
> 三格 / 一行账 / 会话归口在 Lean 开/关两档都干净。**只有 C3 例外**：它的实验 / V 签 /
> B 收编三段都通，但 E 自己的 final 被产品缺陷挡住（E 两族稿号都从 000000 起，
> `manuscriptclosing.signed_candidates` 跨族按单号分桶 ⇒ `ambiguous_path`），该缺陷
> 已登记、未修。逐条读数与剩余 10 条 `CHAIN_ONLY` 的理由见 `temp/cc3/REPORT-CC3.md`。
> 上面那张表里 #6 / #7 / #10 / #12 的「方法层读数（非真机前置）」对本 HEAD 已过期。

HEAD=`090e4e07`（本轮唯一提交：§A.10 读数修复）。零真模型调用、零花费、`projects/lp-ball` 只读。

## 一、本仓「彩排」的既有口径（先摸清再动手）

- 判据形态 = `tests/test_rehearsal_*.py` 14 份（C1–C13 + C5/C6/C7/C8 + 双 F 同题）：**真 Store /
  真事务 / 真 Conductor.summon / 真 Secretary**，只把「模型这一轮说什么」换成预置 JSON 缝
  （`_Seam.ask_json` / `_FakeF.complete` / `_Review.ask`）。不是真机小预算跑。
- 另有大量端到端判据不以 `rehearsal` 命名（`test_closing_gate.py` /
  `test_artifact_registration_write_entries.py` / `test_salvaged_can_come_after_the_abandonment.py` …），
  它们同样是 offline 假缝，本轮一并当链的覆盖形态跑。
- 本轮新写的探针：`agentflow/temp/rs/rs_probe1.py`（NT2 判档三条子链，1.8s）；
  `agentflow/temp/rs/rs_prompt_version_fix.py`（在补丁工作树里重算 p283 读数）。

## 二、协作链清单与逐链读数

| # | 链 | 组成动作 | 入口（file:line） | 覆盖形态 | 本轮 |
|---:|---|---|---|---|---|
| 1 | 证明主链 | D propose_question → F create_plan → F step（写稿）→ V verify_proof 三转 → B ingest_manuscript(register) | conductor.py:8563 / agent_f/create_plan.py:42 / agent_f/step.py:112 / agent_v/core.py:1350 / agent_b/ingest_manuscript.py:41 | test_rehearsal_c2_proof_chain.py | 方法层读数（非真机前置，见文首更正） |
| 2 | 判档（NT2）内嵌主链 | 判在第一次台账写之前 → 拿到 stmt_id+path_group 后落一行 | agent_b/register_statement.py:3484（判 3596 / 落 5377）、ingest_manuscript.py:231、secretary.py:4251/4492 | 本轮 probe A1/A2/B + test_nontriviality_is_per_path.py | 方法层读数（`judged_body_sha256` = sha(`## 命题`+`## 证明`)，两种录入线都真带稿） |
| 3 | 指针式登记 | 只给 proof_manuscript、**不给 proof_text** → 从稿里读命题/证明 → 判档 | register_statement.py:6274 → :6472 → :3596 | test_rehearsal_d_pointer_only.py + 本轮 probe A1 | 方法层读数（非真机前置，见文首更正） |
| 4 | ingest_manuscript 线 | 另一条录入路径（mode=register）→ 判档 | ingest_manuscript.py:41/:206/:213 | 本轮 probe B | 方法层读数（非真机前置，见文首更正） |
| 5 | 同命题第 2 条路径 | path_group=2（apply 线，语义二态判不同种）→ 命题级取 min | ingest_manuscript.py:231 → register_statement.py:8560；secretary.py:14391 | 本轮 probe A2 + test_rehearsal_b_multi_path.py + test_nontriviality_is_per_path.py | 方法层读数（path1=T2、path2=T4 ⇒ 命题级 T2，`path_reading=2`） |
| 6 | 文献链 C1 | A search_literature/ingest_local → B run_once（真抽取+逐字回验） | agent_a/*、agent_b/run_once.py | test_rehearsal_c1_literature_chain.py | 方法层读数（非真机前置，见文首更正） |
| 7 | 数值链 C3 | E run_experiment（numeric / exhaustive）→ V 签 → B 收编 | agent_e/run_experiment.py | test_rehearsal_c3_numeric_chain.py | 方法层读数（非真机前置，见文首更正） |
| 8 | 打回修订环 C4 | V 点名缺陷 → F 定点重写 → 正文 sha 变 → 再送审 → 签 | agent_f/step.py、agent_v/core.py | test_rehearsal_c4_revision_loop.py | 方法层读数（非真机前置，见文首更正） |
| 9 | 概念图链 C9 | C 读数 → D 缺口立题 / B 结构重复裁决（墓碑 + 改写） | agent_c/*、agent_b/decide+resolve | test_rehearsal_c9_concept_graph.py | 方法层读数（非真机前置，见文首更正） |
| 10 | 成文/审校回路 | G compose_claim→build_document→revise；H review→verify_fixes（**close_as 自行收尾**） | agent_g/compose_claim.py:7、build_document.py:8、revise.py:18；agent_h/review.py:7、verify_fixes.py:7 | test_rehearsal_c10_writing.py + test_agent_h.py | 方法层读数（非真机前置，见文首更正） |
| 11 | 形式化链 C11 | B 命题 → L formalize→check_formal→record → C 读回 | agent_l/* | test_rehearsal_c11_formal.py | 方法层读数（本机无 Lean 时按 `unknown + 说得清原因` 认） |
| 12 | 收工链 + 七格门 | E/F autosubmit 按签拦 → closing 七格 + `machine_pass` | agent_f/autosubmit.py:138、agent_e/autosubmit.py:23、closing.py:68 | test_rehearsal_c12_closing.py + test_closing_gate.py（每格单独造红 + 反真空 + `machine_pass` 能为真） | 方法层读数（非真机前置，见文首更正） |
| 13 | 唤醒链 C13 | M 的 block 行 → 逐条审批 → 唤醒 / 不该叫就不叫 | stopctl.py:1584 | test_rehearsal_c13_wake.py | 方法层读数（非真机前置，见文首更正） |
| 14 | 放弃四档 + SV 语义 | math_error / difficulty / counterexample / space_too_large；difficulty 之后按正常流程注册新命题并补记 salvaged（时间戳锚点已撤） | statementabandon.py:1264/:832 | test_abandon_four_tiers*.py、test_abandon_reason_is_structured.py、test_salvaged_can_come_after_the_abandonment.py、test_f_plan_abandon.py | 方法层读数（非真机前置，见文首更正） |
| 15 | 停机 / 墓碑 / 结局 | 派活前查停机（拒派）；墓碑三态；removed 记结局 | stopctl.py:185 | test_dispatch_refuses_after_the_stop_switch.py、test_stop_tombstone_says_it_was_stopped.py、test_stop_history_separates_request_from_deletion.py | 方法层读数（非真机前置，见文首更正） |
| 16 | 并发两格 | 同 sha 已签短路；同稿路径写互斥 | verify/vsigns 短路、manuscriptids | test_a_signed_sha_is_not_bought_twice.py、test_a_signed_statement_is_not_reviewed_again.py、test_two_fs_never_share_one_manuscript_path.py | 方法层读数（非真机前置，见文首更正） |
| 17 | 产物归属 | 9 个内容写入口 × 双向（正控 + 反真空）= 18 格，`ARTIFACTS.jsonl` 有归属 | artifacts.py:168 | test_artifact_registration_write_entries.py（ENTRIES=9，4 条判据） | 方法层读数（非真机前置，见文首更正） |
| 18 | 账本对账 | 无主花销归零 | tokenmeter.py:120 / modelcost.py:549 | test_usage_reconciles_with_tasks.py + C12 | 方法层读数（非真机前置，见文首更正） |
| 19 | **声明面一致性**（不是协作链，是"链能否被正确驱动"的那一层） | H 的 verify_fixes 声明（动作摘要/参数面/policy）、能力矩阵反向缺口登记、两份 golden、prompt 版本痕迹 | specs/h.py:40/:143、capabilities.py:1353、golden×2、agent_prompts.py:2547 | 5 + 2 条判据在 HEAD 上红 | **不通 → 出补丁** |
| 20 | §A.10 自检读数 | agent_h 自检行数 | docs/ROLE-SPECS-APPENDIX.md:1032 | 1 条判据红 | 修（090e4e07） |

## 三、逐遍读数

### 第 1 遍（HEAD `a3795236`）

- 既有彩排 14 份：**81 passed / 62.4s**
- NT2 六份：**39 passed / 14.4s**
- 五~十三项 owner 文件 17 份：**262 passed / 198.8s**
- 本轮新探针（NT2 三条子链）：**1.8s，三条全通**（A1 指针判档 T2；A2 第 2 路 T4、命题级 min=2；B ingest 判档 T2）
- lint：**error 0 / warning 21**（未抬）
- 三格：`test_repo_survey_does_not_get_worse.py` **5 passed / 78.4s**（75/95/5 未抬，现值 75/94/2）
- 断点：声明面 7 红 + §A.10 1 红
  - `test_agent_surface_snapshot` ×2、`test_tool_surface_snapshot` ×1、
    `test_capabilities_reverse_param_gaps` ×2、`test_prompt_stability::…version_trace`、
    `test_agent_prompts::…moves_with_the_sections`、
    `test_role_specs_appendix_is_live::test_a10_selfcheck_entries_match_a_live_run`

### 修

- §A.10：`86 → 89`（RC 撤上限那笔给自检 [5]/[8] 加了三行打印）→ 提交 `090e4e07`
- 声明面：`temp/RS-fc27-close-as-and-stale-registration.patch` +
  `temp/RS-p283-prompt-version.patch`（均含 FC-27 文件 ⇒ 只出补丁，未 apply）

### 第 2 遍（补丁工作树，HEAD+两个补丁+A10 修复）

- 原先 7 红 + 相关：**13 passed / 11.2s**（capability ×5 / agent golden ×2 / tool golden ×1 / prompt ×2 / 语言面 3）
- 扩面（role_specs 四份 + dangling handlers + deprecated + capabilities 两层 + agent_h + prompt 两份）：**219 passed + 1 failed（就是 A10；补 A10 后 27 passed / 24.5s 全绿）**
- 既有彩排 14 份在补丁树上重跑：**81 passed / 91.9s**（补丁不破链）
- `git apply --check`：两个补丁对 `090e4e07` 均 exit 0

## 四、缺陷逐条

| # | 缺陷 | 位置 | 改前红 | 改后绿 | 判据 |
|---:|---|---|---|---|---|
| D1 | agent_h 自检行数写 86、实测 89（RC 那笔加了三行打印） | docs/ROLE-SPECS-APPENDIX.md:1032 | `test_a10_selfcheck_entries_match_a_live_run` 1 failed | 14 passed | 该判据自己 `python -m agentflow.agent_h` 现跑现数（不是抄现值） |
| D2 | H 的复审声明还在教「到轮数上限则 unresolved_review」，而实现（99f6a08f）已撤上限、收尾改 `close_as`；动作面参数未声明 `close_as` ⇒ 编排层看不见这个入口 | src/agentflow/specs/h.py:40 / :143；docs/ROLE-GUIDE.md:982/:985 | agent/tool 两份 golden + capability 反向缺口共 5 红 | 补丁后 13 passed | `stale_missing_in_action_entries()` / `unregistered_missing_in_actions()` / 两份 golden |
| D3 | 99f6a08f 改了 H 的提示词段（agent_skills「轮数上限已撤除」）却没抬 `PROMPT_VERSION`、没重算十一格摘要 ⇒ 审计里查不到那一次改动 | agent_prompts.py:2547；tests/test_agent_prompts.py:2522；tests/test_prompt_stability.py `_VOLATILE_FACT_SETS` | 2 红 | 补丁后绿（p283） | `_version_drift` + `facts_migration_problem` |
| D4 | `("D","register_conjecture")` 的反向缺口登记过期（2026-11-13 之后 D 已无这条动作） | capabilities.py:1327-1343 | `test_the_registration_has_no_stale_entries` 红 | 补丁后绿 | 同一条 stale 判据 |

## 五、仍需人做（FC-27）

1. `temp/RS-fc27-close-as-and-stale-registration.patch`
   - 触及 FC-27：`src/agentflow/specs/h.py`、`src/agentflow/capabilities.py`、
     `tests/golden/tool_surface_snapshot.json` ⇒ 2 名 reviewer + 逐格看 golden diff。
   - 非 FC-27 但同主题：`docs/ROLE-GUIDE.md`（H 的那两行）。
2. `temp/RS-p283-prompt-version.patch`（**必须在 1 之后 apply**）
   - 触及 FC-27：`tests/golden/agent_surface_snapshot.json`（p283 的 H 段）。
   - 非 FC-27：`agent_prompts.py`（PROMPT_VERSION p282→p283）、
     `tests/test_agent_prompts.py`（H 摘要 62f1ee38…）、`tests/test_prompt_stability.py`（账本追加 p283 一格）。
   - 为什么不能先提交 p283：H 的提示词摘要取决于补丁 1 改完的 `specs/h.py` 文本，
     只提交 p283 会在补丁 1 落地后再红一次。

## 六、结论

**还不能起真机**：只差上面 2 个补丁落地（H 的复审声明面 + p283 审计痕迹）。
其余 18 条已设计的链 offline 全通，lint 0/21、三格 75/94/2，零模型钱。

> **2026-11-15 RC2 更正上面这一句**："offline 全通"里的那 14 份 `test_rehearsal_*.py`
> 不是真机同一条路（见文首更正与 `temp/rc2/REPORT-RC2.md`）：它们现在只算
> **方法层读数**，不再进"可当真机前置证据"的名单。截至 RC2，从 CLI 入口 + 真
> `LlmSeam` + 只换网线走通的**整条协作链**是 1 条：证明主链
> （`tests/test_rehearsal_cli_proof_main_chain.py`，M→B→V 三签→收录→依赖）。
