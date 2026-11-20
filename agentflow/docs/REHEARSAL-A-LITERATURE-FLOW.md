# 彩排（真路径）A 侧文献全流程 —— 记录与复跑（RA1，2026-11-16）

> 这是一份**证据记录**，不是规格：它写清这条彩排覆盖什么、怎么复跑、以及
> **今天在 HEAD 上跑到哪一格停住**。判据本体在
> `tests/test_rehearsal_a_literature_flow.py`（彩排）与
> `tests/test_rehearsal_a_literature_flow_criteria.py`（反真空 / 产品就绪）。

## 1. 这条链是什么

业主 2026-11-16 的 A 侧严格时序（Q1）：判收不注册、提交才注册、清表之后才许收工。
彩排从 **CLI 入口** 起跑，只替换出网那一层（`modelgw.urllib_transport`），其余全是
产品原物：

```text
cli.main(["start", "--mode", "research", "--sid", …])
  → _run_spec → _exec_role → host.wired_llm_conductor → LlmBackend → AgentLoop.run
  → M --summon--> A
      own.search_literature                     （检索请求一行：outcome=no_results 是有效结论）
      lit.stage_add                             （两条候选进待新增列表）
      lit.stage_list                            （回读回执：提交前必须回读）
      text.extract(lit_id="cand:000000")        （候选期抽读：回执落 data/lit_reads.jsonl）
      fs.read(out/texts/cand-000000.txt)        （真的读过那一版）
      lit.admit(items[].availability="readable")（判收：qualified、不注册、无号）
      lit.stage_reject                          （判拒：受控理由码）
      lit.admit_all                             （提交：无号原件 → 批量注册 → 回填 → 带号定稿 → 清表）
  → M --conductor.closing--> closing.check_closing（第八格 literature_pending）
```

## 2. 覆盖的九段与判据（逐段读盘）

| # | 时序 | 判据 |
|---|---|---|
| ① | `lit_candidates` 新增 `qualified` 态 | 判收后 literature 0 行；候选行 `status=qualified`、`lit_id` 空、`relevance` 非空；`judged_state` 读成"判过" |
| ② | `lit.admit` 判收不注册 | 回执 `registered=0`、`admitted[].lit_id` 全空；进度报告 `## 待注册（1 篇）` 且无 `lit:` |
| ③ | 提交落无号原件 `reports/lit-<rid>.submitted.md` | 原件在盘上；全文无 `lit:`、无 `cand:`、无「槽位 N」；带「有入库资格」 |
| ④ | `lit.admit_all` 只注册 `qualified` 行、回填同一行 | 回执 `registered=1`；候选行 `admitted` 且 `lit_id` 有值；`literature` 1 行且号相同 |
| ⑤ | 带号定稿 `reports/lit-<rid>.md` | 入库区带 `lit:NNNNNN`；未入库区无号且有 `理由：rejected_off_topic`；全文无 `cand:` |
| ⑥ | 清表：归档 + 逐行 `cleared_at` / `clear_reason` | 归档 2 行、槽位↔号成对；两行都有标记；表里无 `pending`（不物理删） |
| ⑦ | 收工闸第八格 | 清表前 `fail` + `delegation_not_cleared`；清表后 `pass`、`closed_delegations=1` |
| ⑧ | `report_violations` 两个渲染时刻各跑一次 | 两个时刻的报告各自过同一份判据；"真的拦门"由两条负控证明（带槽位号 ⇒ 提交被拦；定稿缺号 ⇒ 清表被拦） |
| ⑨ | 报告过期自动重渲染；清表后不可再生 | 判拒后进度报告已重渲染（待裁 0、未入库 1）；已清表再 `write_report` ⇒ `already_settled` |

三条账判据复用既有探针，不另写一套：`rehearsal_contract.ledger_identity`
（每笔真调用一行账）、`rehearsal_contract.session_split`（会话归口本趟 sid）、
`triplet_probe`（三格：resolved / caller_role / 账本行）。Lean 开/关两档各跑一遍。

## 3. 今天的读数（2026-11-16，HEAD `a4dadffb`）

### 3.1 HEAD 原样：卡在 ①（产品缺口，不是彩排缺陷）

- `python -m pytest tests/test_rehearsal_a_literature_flow.py -q`
  ⇒ **4 passed / 5 xfailed**（xfail 的 5 条就是链判据：它们先跑完整一趟让三格有对象，
  再断言"这份读数必红、红点必须正是 schema 缺 `qualified`"，最后按已知卡点登记 xfail）；
- `python -m pytest tests/test_rehearsal_a_literature_flow_criteria.py -q`
  ⇒ **1 failed / 7 xfailed**：那一条红是 `test_the_product_carries_the_qualified_status`，
  红点逐字是 `schema.CANDIDATE_STATUSES` 还没有 `qualified`
  （现值 `('pending','withdrawn','rejected','admitted','cleared')`）；
- 运行期读数（同一趟，13 次真调用）：`llm_call=13 / 出网=13 / 账本行=13 /
  duplicate=0 / 未配对=0 / 未认领=0`；会话归口 `本趟=13 / 别处=0`；
  三格 `resolved=13/13`、`caller_role=['A']`、`usage_ledger_rows=14`、`unattributed=0`、`dangling=0`。

会话里卡点的原文：`lit.admit` 回执 `ok=False, kind=unexpected`，错误文本
「status 必须是 ('pending','withdrawn','rejected','admitted','cleared') 之一，收到
'qualified'」⇒ `literature` 0 行、没有原件/定稿/归档，收工门第八格是
`fail/undecided_candidates`。

**结论：A 的这套流程今天彩排不通，卡在 ①。** 这是**产品侧缺口**（Q1 只落了一半）：
`schema.py` 那一格在 `temp/Q1-fc27-schema-qualified.patch` 里，命中 FC-27
（schema-migration / eval-criteria），须人编写或人逐行走查 + 2 名 reviewer approve
后 apply。同一红点也让 `tests/test_lit_submit_registers_only_at_submit.py` 的 6 条红。

旁证读数（同一批产品改动，不是本路造成）：`src_functions_gt200_lines` 实测已是
**95**（= `tests/test_repo_survey_does_not_get_worse.py` 的基线常量），不是上一批
commit 里写的 94 —— 跨线那一笔是 Q1 的 `6176a035`：`litstage.admission_plan` 210 行。
本路只动 `tests/` 与 `docs/`，三格一格未动（`src_files_gt800_lines=75`、
`dup_docstring_segments=2`）。

### 3.2 把 FC-27 schema 补丁打到一个一次性副本上：①–⑨ 全通

复跑方式（不碰交付树；`temp/` 已被 `.gitignore` 排除）：

```powershell
cd D:\Incubator
git worktree add agentflow\temp\ra1_head a4dadffb
git -C agentflow\temp\ra1_head apply D:\Incubator\agentflow\temp\Q1-fc27-schema-qualified.patch
cd agentflow\temp\ra1_head\agentflow
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/test_rehearsal_a_literature_flow.py `
                 tests/test_rehearsal_a_literature_flow_criteria.py `
                 tests/test_rehearsal_same_path.py -q
```

2026-11-16 实测：**71 passed**（9 + 8 + 54）。同一趟读数：
`llm_call=13 / 出网=13 / 账本行=13`、`本趟=13 / 别处=0`、三格 `13/13`；
Ledger 与报告终态：`literature` 1 行（`lit_id=000000`）、候选两行
（`admitted` + `rejected`，都有 `cleared_at`）、归档 2 行、第八格 `pass`。
Lean 开/关两档都绿（关档 `is_hidden("L")=True`，名册里没有 L）。

## 4. 它是不是「真机前置证据」

是。它在 `tests/rehearsal_contract.py` 的 **`SAME_PATH_EVIDENCE`** 里登记，
**不在** `CHAIN_ONLY` 里；判据 `tests/test_rehearsal_same_path.py` 钉住三件事：
不在黑名单、三格探针认它、四条静态判据（打桩白名单 / CLI 入口 / 不自造缝 / 不直调私有）
全过。反真空（跳过回读 / 跳过抽读 / 回填空 / 去号 / 定稿缺号 / 清表打掉 /
`judged_state` 打桩）在 `tests/test_rehearsal_a_literature_flow_criteria.py`，
它登记为判据文件（`FLOW_CRITERIA_FILES`），不提供同路径证据。
