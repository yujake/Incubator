# RECON-B：真机七项对账（修正后口径）

一套**只读**的对账脚本：真机跑完一趟后，一条命令给出七项读数（人读表 + JSON）。
口径按业主 2026-11-19 的「修正后的口径」，旧口径（`llm_call 数 == 账本行数`、
`issued.json` 当签、不适用并进未判等）一律不用。

> 2026-11-21 RECONFIX 从 `temp/reconB/recon.py` 提升到这里（业主规矩：别把有用的做在
> temp 里 —— 它会被重跑第二次，`tests/test_reconfix_sign_backing.py` 也要按路径判它）。
> `temp/reconB/recon.py` 只剩一个转交参数的壳，实现只有本目录这一份。

## 用法（一行）

```bat
python agentflow/scripts/recon_b.py --root D:\Incubator\projects\lp-ball-11
```

- `--root`：项目根（真机工作区）。只读；projects/* 一个字都不改。
- `--outdir`：输出目录，默认 `agentflow/temp/reconB/out/`；写 `<项目名>.txt` 与 `<项目名>.json`。
- `--no-product`：强制走数据直读，用来验证降级路径（产品模块不可用时也能出读数）。
- `--print-json`：同时把 JSON 打到 stdout。
- 退出码：`0` 七项都读到了；`2` 至少一项 `unknown`（没查成）。有 `warn` 仍是 0。

## 七项与口径出处

| # | 项 | 口径 | 实现 / 出处 |
|---|---|---|---|
| ① | 账目 | 账本行 = `reason` + `summon`（0 token 结算）+ `extract`，三类**分别**对各自来源；不用 `llm_call == 账本行` | `data/usage_ledger.json#rows[].scope`；reason ↔ `sessions` 的 `llm_call`；summon ↔ 子趟收工结算；extract ↔ 账本内自洽（弱对账，见缺口） |
| ② | unattributed | 会话口径：`llm_call.usd` 累计 − 各趟自报 `spend_usd` 之和；同时给账本口径（`task_id=None` 行数）；两者都列构成 | `agentflow.sessions.unattributed_usd_of`（162②，与代码注释同口径） |
| ③ | 八格 | 逐格 pass / fail / not_applicable / unknown（四态，不折平）；另给 `can_close` / `machine_pass` / `closing_verdict` / `tri_state_exit_code` | `agentflow.closing.DEFAULT_CHECKS` + `closing.closing_verdict` + `closing.tri_state_exit_code`（ROOTGATE-①） |
| ④ | 签 | 只认 `out/vsigns/<sha>.json`（3 个 passes，逐 pass 查 `review_call` / `review_pass` / `object_sha256` / `at` / `verification_id`），并按签的**类型**分流回指台账（见下节）；`issued.json` 只作索引，且索引与文件双向对账 | `out/vsigns/*.json`、`out/vsigns/issued.json`；`agentflow.proofregistry.proof_sha` 复算 |
| ⑤ | 非平凡度 | T0–T4 + 不适用 + 未判**分开**；分母只算可判命题；必须印 T0 | `agentflow.closing.nontriviality_reading`（FIX186-B，业主 2026-11-19） |
| ⑥ | 销号/义务 | 板项 `item_state` 残留、`root_open_items`、`auto_retire` 实际销号；三族义务（`b-register@` / `v-resubmit@` / `b-awake@`）带收件实例、状态、是否挂死在已终态台账号 | `data/tasks.json#rows`、`out/roster/*-retired.jsonl`、`closing.machine_feeders`（retire 只读投影）、`agentflow.obligations` 的三个前缀 |
| ⑦ | 会话归口 | 只有 `sessions/<sid>.jsonl`？跨项目 / 跨 sid 各几条？读口 problems 几条？unattributed 的 task 是否都在范围内 | `sessions/` 目录、`sessions.read_session` 的 problems、`agentflow.run_start` 的 `workspace_root`、`runs/*.json#sid`、`m-verdicts`/`handoffs#sid` |

每条读数都带出处（`file:line` 或数据文件 + 字段名）；读不到时明确写 `unknown`，不当 0。
脚本末尾另给一段「口径差异（旧 → 新）」：同一份盘上旧口径会得出的数 vs 新口径的数。

## ④ 的回指：按签的类型分流（2026-11-21 RECONFIX）

盘上有两本 V 台账，**签的类型决定它住哪一本**：

| 类型 | 号 | 台账落点 | 出处 |
|---|---|---|---|
| 在册签 | `v-…` | `verifications/<命题号>.jsonl` | `v_paths.verification_ledger_path` / `v_ledger_write.next_verification_id` |
| 未在册签 | `u-…` | `verifications/pending/<object_sha256>.jsonl` | `v_pending_write.record_pending_sign`（键是 `object_sha256 or proof_sha256`）/ `v_vocab.PENDING_PREFIX` |

三核（两本同一套判据）：**在不在**（文件在盘上）、**行数对**（3 票都能在那一本里回指到
各自的行）、**proof_sha 对**（回指到的那一行 `proof_sha256` 等于签的 `artifact_sha`）。
另外交叉核一次：签自报的 `ledger` 锚点必须与「按类型算出来的那一本」一致。

类型按**那一行台账的号**判，不按「命题现在在不在册」判：pending 行被认领之后物理位置
不动（`verifications._claimed_pending_rows` 读的就是 pending 目录），号仍是 `u-…`。
`projects/lp-ball-15` 的 3 个合格签正是这种：命题已在册（000187 / 000188 / 000189），
签却是未在册时发的（`u-…`）。反过来说，`v-` 号只在**一份命题台账内**递增，同一个
`v-000006` 会同时出现在 `verifications/000031.jsonl` 与 `verifications/000032.jsonl` ——
按号跨文件找会串台，所以命题号只能从签上取（`statement_id`，退到 `statements` 表里
`proof_sha256` 对得上的那一条）。

分不清类型（号不是 `v-` / `u-`、或 3 票混装）⇒ `unchecked`：既不折成合格，
也不当成「回指缺失」，该项 state 记 `unknown`（没查成 ≠ 查过了没问题）。

## 只读与降级

- 对项目根只做读：`open(..., 'r')` / `Path.read_text`；唯一的写是 `--outdir`。
- 产品代码是加分项：导入 `agentflow.closing` / `agentflow.sessions` / `agentflow.obligations` /
  `agentflow.proofregistry`，失败或调用抛错就**逐项降级**为数据直读，并在该项
  `degraded=true` + `degraded_reason` 里写清原因；算不出来的格落 `unknown`（绝不当 pass）。
- 商店句柄用自带的 `RoStore`（只实现 `rows` / `root` / `read_events`），不打开真
  `agentflow.store.Store`，避免锁文件/建目录。

## 样例输出（`temp/reconB/out/`）

`lp-ball-11.txt/.json`、`lp-ball-10.txt/.json`，关键读数：

| 读数 | lp-ball-11 | lp-ball-10 |
|---|---|---|
| ① 账本 | 522 行 = reason 487 + summon 21 + extract 14（Δ 0） | 1255 行 = reason 1200 + summon 55 + extract 0（Δ 0） |
| ① 旧口径差 | 487 vs 522 ⇒ 35 行（其实是 summon+extract） | 1200 vs 1255 ⇒ 55 行（全是 summon） |
| ② unattributed（会话口径） | $0.151083 / 28 次（8 个 task 的事件和 > 自报） | $0.293697 / 91 次（26 个 task） |
| ② 账本口径（task_id=None） | 0 行 | 0 行 |
| ③ 八格 | 6 pass / 2 fail（acceptance、literature_pending） | 7 pass / 1 fail（acceptance） |
| ③ 新门 | fail / can_close=False / machine_pass=False / exit 1 | fail / can_close=False / machine_pass=False / exit 1 |
| ④ 签 | 1 个合格（3 passes，object 台账在，proof_sha 复算 match），索引 0 缺文件 | 3 个合格；另有 1 条有 proof_sha 无签文件（stmt:000016，不是矛盾） |
| ⑤ 非平凡度 | T0 1 / T1–T4 0；不适用 35；未判 1（已放弃）；分母 1 | T0 0 / T1 4；不适用 14；未判 0；分母 4 |
| ⑥ 销号 | 板项残留 0；root_open_items 0；auto_retire 实际 20（投影 0）；b-register 1（收口）/ v-resubmit 0 / b-awake 0 | 残留 0；root_open_items 0；auto_retire 实际 51；b-register 3（收口，1 条没人收）/ v-resubmit 0 / b-awake 0 |
| ⑦ 会话 | 1 个会话；跨项目 0；跨 sid（证据面）0（另有 1 个 cache 快照来自别的 sid）；problems 0；范围外 task 0 | 1 个会话；跨项目 0；跨 sid 0；problems 0；范围外 task 0 |

## 已知缺口（下一趟真机前值得知道）

1. **① 的 extract 没有独立第二来源**：extract 不进 `sessions/<sid>.jsonl`，脚本只能做
   账本内自洽（`note=modelgw` + `call_index` 1..N 连续），已如实标 `weak=true`。
   要变成「两处对上」，得让抽取调用也在会话流里留一条（或落一份可独立计数的回执）。
2. **② 只能到 per-task 差额**：能算清「哪个 task 的事件求和 > 它的自报」，
   但不能再往下把 28/91 次调用逐条归因到「哪一次、谁发的」（会话里没有更细的归属键）。
3. **b-awake 族在两个项目上都是 0 行**：脚本报的是「表读得到、这一族没有行」，
   不能替业主判断「本就不该有」还是「漏记」；b-register 有 1/3 条而唤醒行 0，已单独点名。
4. **`object_sha256` 与 `proof_sha256` 不是同一把尺**（2026-11-21 RECONFIX 改写：
   原文把两者说成"同一个送审对象台账"，那是错的）：`proof_sha256` / `artifact_sha` 是
   证明正文的 sha（`proofregistry.proof_sha`），`object_sha256` 是被审那份文件
   （`reports/f-proof-*.md` 一类）的**字节 sha**。回指用哪一把由签的类型决定：
   - 在册签：回指 `verifications/<命题号>.jsonl`，`object_sha256` 只是阅签的旁证
     （写侧 2026-11-21 起才补这一格，见 `agent_v/core.py` 的在册写口），**不**用于找台账；
   - 未在册签：`verifications/pending/<object_sha256>.jsonl` 的文件名就是对象字节 sha
     （对象 sha 为空时退到正文 sha，见 `record_pending_sign` 的 `obj or sha`）。
5. **④ 的「3 票」是这一档的定义**：`need` 不是 3 的历史签会记两条（`passes=N（要 3）`
   与 `need=N（要 3）`）；`legacy` 签照查，不因老形态放过。
