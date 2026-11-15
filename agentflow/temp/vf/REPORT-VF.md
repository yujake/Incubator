# VF 路交付报告：V 的工具路径接回装配缝 + 幂等键不再吞账（2026-11-15）

- 仓库：`D:\Incubator`（git 根），交付物在 `agentflow/`；开工 HEAD = `519bd05b`，工作树干净
- 本路只修 RC2 用 **CLI 入口 + 真 LlmSeam** 彩排暴露的两处产品缺陷，并先补两条判据
- 零真模型调用、零花费、未起真机；`projects/lp-ball`（在 `D:\Incubator\projects\lp-ball`，
  不在 `agentflow/projects` 下）只读：`git status -- projects` 空，最后修改时间仍是 2026-11-14
- 不动 FC-27：四个产品文件（`llmseam.py` / `host.py` / `agent_v/core.py` / `secretary.py`）
  与两份判据文件都不在 `.noai-paths` 清单里

---

## 〇 一句话结论

**两处缺陷都修在装配层与记账层，不在判据层放宽：V 的工具路径现在拿到 host 装配的那条
缝（`sid` / `meter` / `budget_of` 都在），幂等键的命名空间不再按召唤号一刀切。同一趟
CLI 真路径彩排：真调用 16 次 ↔ 账本 16 行、`duplicate` 0 笔、16 条 `llm_call` 全部落在
本趟 `sid`（改前 10 行 / 6 笔 duplicate / 7 条落缺省会话）。**

---

## 一 缺陷一：V 的工具路径靠 env 现造第二条缝

### 1.1 改法（两处产品代码 + 一处必要装配）

| 落点 | 改了什么 |
|---|---|
| `src/agentflow/host.py:593-594` | 装配期 `v_llm = _seam("V")` + `set_role_seam("V", v_llm)`：与 F 同一条纪律（V 出场就有缝）、与 E 同形（登记到 `llmseam` 的按角色表，只此一处注册表）。不登记时 `verify_tools._agent_v` 只读得到 `role_seam("V") is None` |
| `src/agentflow/agent_v/core.py:1118-1150` | `AgentV._seam()` 三档优先级：显式注入（`llm=`，单条执行入口 / 剧本缝）→ `llmseam.role_seam("V")`（工具路径）→ env 现造（没有登记时的受控兜底）。改前只有第 1 / 3 档 |
| `src/agentflow/secretary.py:15664,15710,15766` | 必要装配：`_ambient_session_sid()` + `for_role_wired` / `seam_for_secretary` 在 `sid is None` 时读 `conductor.calling_as` 挂的会话号。改前 `AgentV._secretary` / `AgentB._statement_secretary` 一律传 `sid=None` ⇒ 秘书那几笔照样落缺省会话（7 条里占 4 条） |

为什么修在 `host.py` 而不是让 `AgentV` 自己在工具路径上"再找一个 root"：工具路径拿不到
host 的装配上下文（`verify_tools.py` 是 FC-27，只从 `register(...)` 得到 store 与工作区根）；
能装出 `sid` / `meter` / `budget_of` 的只有装配期。`llmseam` 的按角色表本来就是这个
"装配期写入、工具层读取"的通道（F 已经在用），V 只是从来没接上去过 ——
改前全仓没有任何 `set_role_seam("V", …)`（`grep` 只有 `host.py` 给 E 登记过）。

### 1.2 为什么"只有 run-agent V 才走自己的注入"

`AgentV._seam()` 的第 1 档（`llm=`）保留原样：`run-agent V` 经 `specs/v.py` 拿到的缝、
判据里的 `_ScriptedSeam`、以及 `verify_tools._agent_v` 显式传进来的 `role_seam("V")`
都走这一档。工具路径（M 派 `V.verify_proof`）没有显式注入，于是落到第 2 档 ——
它拿到的正是 host 装配的那一条（同一 `sid`、同一个 `TokenMeter`、同一个 `budget_of`），
不是 env 现造的第二条。

---

## 二 缺陷二：幂等键吞账

### 2.1 改法

| 落点 | 改了什么 |
|---|---|
| `src/agentflow/llmseam.py:294-341` | 新增 `_idem_namespace(session_root, sid, role, task_id)`：命名空间 = `root:…\|sid:…\|role:…\|task:…`。前三格合起来是这条缝的实例身份，与 `_next_call_index` 的计数键 `(工作区, 会话, 角色, 召唤号)` 逐字同源 |
| `src/agentflow/llmseam.py:827-831` | `_charge_ledger` 用它构造幂等键（改前是 `f"task:{tid}"`，`tid` 为空时才退回 `f"{sid}:{role}"`） |
| `src/agentflow/llmseam.py:343-361` | 新增 `ambient_sid()`：与 `ambient_task_id()` 同族、同一个挂点（`conductor.current_session()`），供秘书装配读"这一趟是哪一段会话" |

**为什么不是关掉幂等**：命名空间是确定性的（不含随机量 / 内存计数器）。同一条缝、同一个
召唤、同一进程或重跑一遍算出来的第 i 个键逐字相同 ⇒ 真正的重复记账（跨进程重放 /
同一笔重试）仍被判 `duplicate`；改掉的只是"两条不同的真调用互相吞"。反过来说，
关掉幂等会让重复记账进来，那是把"少记"换成"多记"，比原来更坏。

**为什么只加这三个维度就够**：序号 `call_index` 是在 `(工作区, 会话, 角色, 召唤号)` 上数的；
键的命名空间只有与计数键同源，"第 i 次"在两处才指同一件事。只写召唤号时，
`V` / `secretary:V` / `secretary:B` 各自的 `idx=0` 撞同一个键（RC2 现场：
16 次真调用只落 10 行，6 笔 duplicate）。

---

## 三 TDD：先看红，再改代码看绿

### 3.1 新判据（两份文件）

`tests/test_rehearsal_cli_proof_main_chain.py`（与 RC2 那条 CLI 真路径彩排同一份 `_run`）：

| 判据 | 读数函数 / 判据本体 | 行 |
|---|---|---|
| ① 每笔真调用有且只有一行账 | `_ledger_identity` / `_one_row_per_call_problems` | 305 / 383 |
| 正控（Lean 开 + 关各一遍） | `test_every_real_call_has_exactly_one_ledger_row` | 507 |
| ② 全部 `llm_call` 落在本趟 `sid` | `_session_split` / `_session_problems` | 363 / 407 |
| 正控（Lean 开 + 关各一遍） | `test_every_llm_call_lands_in_this_runs_session` | 543 |
| Lean 开档主链（新增，补上 RC2 缺的那一档） | `test_the_same_chain_runs_with_lean_on` | 676 |

判据本体是纯函数（只吃读数，不读盘、不抛异常）：正控与反真空用同一份判据，
避免"两处各写一份什么叫不对"。

`tests/test_ledger_identity_antivacuum.py`：把修复的每一半改回旧形态，证明判据会红。
它刻意不叫 `test_rehearsal_*` —— 它跑的是"坏掉的产品形态"，不是可当真机前置的彩排。

### 3.2 改前红（TDD 第一跑，原文）

```text
$ python -B -m pytest tests/test_rehearsal_cli_proof_main_chain.py -q -k "exactly_one_ledger_row or lands_in_this_runs_session"
4 failed, 4 deselected in 12.95s
```

判据①（Lean 关档）：

```text
[一行账] lean=0 真调用=16 出网=16 账本行=10 duplicate=6 未配对=0 未认领=0
E  AssertionError: 6 笔真调用被判 duplicate、静默不记账：[{'session': '20261115', 'role': 'V', 'task_id': 't-000003', 'reason': 'duplicate', 'usage_id': '000002'}, {'session': '20261115', 'role': 'secretary:V', ...}, {'session': '20261115', 'role': 'secretary:V', ...}, {'session': '20261115', 'role': 'secretary:V', ...}, {'session': '20261115', 'role': 'secretary:B', ...}, {'session': 'rc2-main-chain', 'role': 'V', ...}]
```

判据②（Lean 关档）：

```text
[会话归口] lean=0 本趟=9 别处=7 会话=['20261115', 'rc2-main-chain']
E  AssertionError: 7 条 `llm_call` 落在本趟 `sid=rc2-main-chain` 之外：[('20261115', 'V', 't-000003'), ('20261115', 'secretary:V', 't-000003'), ('20261115', 'V', 't-000003'), ('20261115', 'secretary:V', 't-000003'), ('20261115', 'V', 't-000003'), ('20261115', 'secretary:V', 't-000003'), ('20261115', 'secretary:B', 't-000002')]
```

### 3.3 改后绿（原文）

```text
[一行账] lean=1 真调用=16 出网=16 账本行=16 duplicate=0 未配对=0 未认领=0
[一行账] lean=0 真调用=16 出网=16 账本行=16 duplicate=0 未配对=0 未认领=0
[会话归口] lean=1 本趟=16 别处=0 会话=['rc2-main-chain']
[会话归口] lean=0 本趟=16 别处=0 会话=['rc2-main-chain']
```

逐笔的 `(sid, role, task, 序号)` 对账（`temp/vf/probe_reading.py`，Lean 关档）：

```text
rc=0 calls=16 rows=18
| # | session | role | task | call_index | reason | usage_id |
|---|---|---|---|---|---|---|
| 0 | rc2-main-chain | M | t-000001 | 0 | charged | 000000 |
| 1 | rc2-main-chain | B | t-000002 | 0 | charged | 000001 |
| 2 | rc2-main-chain | V | t-000003 | 0 | charged | 000002 |
| 3 | rc2-main-chain | V | t-000003 | 1 | charged | 000003 |
| 4 | rc2-main-chain | secretary:V | t-000003 | 0 | charged | 000004 |
| 5 | rc2-main-chain | V | t-000003 | 2 | charged | 000005 |
| 6 | rc2-main-chain | secretary:V | t-000003 | 1 | charged | 000006 |
| 7 | rc2-main-chain | V | t-000003 | 3 | charged | 000007 |
| 8 | rc2-main-chain | secretary:V | t-000003 | 2 | charged | 000008 |
| 9 | rc2-main-chain | V | t-000003 | 4 | charged | 000009 |
| 10 | rc2-main-chain | B | t-000002 | 1 | charged | 000011 |
| 11 | rc2-main-chain | B | t-000002 | 2 | charged | 000012 |
| 12 | rc2-main-chain | secretary:B | t-000002 | 0 | charged | 000013 |
| 13 | rc2-main-chain | B | t-000002 | 3 | charged | 000014 |
| 14 | rc2-main-chain | M | t-000001 | 1 | charged | 000016 |
| 15 | rc2-main-chain | M | t-000001 | 2 | charged | 000017 |
```

`rows=18` = 16 行模型调用 + 2 行召唤结算（`000010` / `000015`，`note` 是 `settle-…`，
不是一次真调用；判据①按 `note` 前缀 `source=llmseam;` 只数前者）。
16 个 `(sid, role, task, call_index)` 全部互不相同，每一笔 `usage_id` 都指到属于自己的那一行。

### 3.4 反真空（逐半改回旧形态，原文）

```text
$ python -B -m pytest tests/test_ledger_identity_antivacuum.py -q -s
[反真空·键] calls=16 rows=12 duplicates=[('secretary:V', 'rc2-main-chain'), ('secretary:V', 'rc2-main-chain'), ('secretary:V', 'rc2-main-chain'), ('secretary:B', 'rc2-main-chain')]
[反真空·会话] in_run=13 elsewhere=[('V', '20261115'), ('V', '20261115'), ('V', '20261115')]
[反真空·秘书会话] in_run=12 elsewhere=[('secretary:V', '20261115'), ('secretary:V', '20261115'), ('secretary:V', '20261115'), ('secretary:B', '20261115')]
[反真空·全旧] calls=16 rows=10 duplicates=['V', 'secretary:V', 'secretary:V', 'secretary:V', 'secretary:B', 'V'] elsewhere=['V', 'secretary:V', 'V', 'secretary:V', 'V', 'secretary:V', 'secretary:B']
4 passed in 13.22s
```

读法（这几条正是"判据承重"的证据）：

| 反真空 | 改回旧形态的那一半 | 判据① | 判据② |
|---|---|---|---|
| 键 | 命名空间回到 `task:<号>` | **红**：16 次调用 / 12 行 / 4 笔 duplicate | 仍绿（键只吞账，不改事件落哪个文件） |
| V 缝 | 不登记 `role_seam("V")` | 仍绿（钱照记） | **红**：V 的 3 条落缺省会话 |
| 秘书会话 | 秘书装配不读 ambient sid | 仍绿 | **红**：secretary:V ×3 + secretary:B ×1 落缺省会话 |
| 全旧 | 三半一起 | **红**：16 / 10 / 6 笔 | **红**：7 条落缺省会话 |

"全旧"那一行逐字复现 RC2 的现场读数：16 次真调用、10 行模型调用账（+2 行结算 = 12）、
6 笔 duplicate、7 条缺省会话。

---

## 四 重跑 RC2 那条 CLI 真路径彩排（Lean 开 + 关）

跑法（`-s` 才看得到三格；判据② / ① 的打印也在里面）：

```text
$ python -B -m pytest tests/test_rehearsal_cli_proof_main_chain.py -q -s
9 passed in 27.82s
```

### 4.1 三组读数一览

| 档 | 用例 | 三格 | 会话归口 | 每笔一行账 |
|---|---|---|---|---|
| Lean 关 | 主链 a（`test_the_proof_main_chain_runs…`） | 16/16、①16/16、②`['B','V']`、live_meter=16、③ rows=18 unattributed=0 dangling=0 | —（正控） | —（正控） |
| Lean 关 | 判据①`[0]` | 同上 | — | 真调用 16 / 出网 16 / 账本 16 / duplicate 0 |
| Lean 关 | 判据②`[0]` | 同上 | 本趟 16 / 别处 0 / 会话 `['rc2-main-chain']` | — |
| Lean 开 | 判据①`[1]` | 16/16、①16/16、②`['B','V']`、live_meter=16、③ rows=18 unattributed=0 dangling=0 | — | 真调用 16 / 出网 16 / 账本 16 / duplicate 0 |
| Lean 开 | 判据②`[1]` | 同上 | 本趟 16 / 别处 0 / 会话 `['rc2-main-chain']` | — |
| Lean 开 | 主链（`test_the_same_chain_runs_with_lean_on`，本路新增） | 16/16、①16/16、②`['B','V']`、live_meter=16、③ rows=18 unattributed=0 dangling=0 | 由判据本体复核：别处 0 | 由判据本体复核：16 / 16 / 0 |
| Lean 关 | 指针线 b | 16/16、①16/16、②`['B','V']`、live_meter=16、③ rows=18 unattributed=0 dangling=0 | — | — |
| Lean 关 | 反真空（V 判有毛病） | 12/12、①12/12、②`['B','V']`、live_meter=12、③ rows=14 unattributed=0 dangling=0 | — | — |

### 4.2 三格原文（`-s`，Lean 开 / 关各一份）

```text
[三格] …::test_every_real_call_has_exactly_one_ledger_row[1]  ask 次数=16  live=16
[三格] …::test_every_real_call_has_exactly_one_ledger_row[1]  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
[三格] …::test_every_real_call_has_exactly_one_ledger_row[0]  ask 次数=16  live=16
[三格] …::test_every_real_call_has_exactly_one_ledger_row[0]  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
[三格] …::test_every_llm_call_lands_in_this_runs_session[1]  ask 次数=16  live=16
[三格] …::test_every_llm_call_lands_in_this_runs_session[1]  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
[三格] …::test_every_llm_call_lands_in_this_runs_session[0]  ask 次数=16  live=16
[三格] …::test_every_llm_call_lands_in_this_runs_session[0]  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
[三格] …::test_the_same_chain_runs_with_lean_on  ask 次数=16  live=16
[三格] …::test_the_same_chain_runs_with_lean_on  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
[三格] …::test_the_same_chain_runs_with_lean_off_and_no_l_in_the_roster  ask 次数=16  live=16
[三格] …::test_the_same_chain_runs_with_lean_off_and_no_l_in_the_roster  ①resolved=16/16  ②caller_role=['B', 'V']  live_meter=16  ③ledger_rows=18 unattributed=0 dangling=0
```

`ledger_rows` 从改前的 12 变成 18：多出来的 6 行正是原来被判 duplicate 的那 6 笔
（三格只要求"有行、无主 0、悬空 0"，所以它改前也是绿的 —— 这正是它守不住这一格的原因）。

会话归口与一行账的原文：

```text
[一行账] lean=1 真调用=16 出网=16 账本行=16 duplicate=0 未配对=0 未认领=0
[一行账] lean=0 真调用=16 出网=16 账本行=16 duplicate=0 未配对=0 未认领=0
[会话归口] lean=1 本趟=16 别处=0 会话=['rc2-main-chain']
[会话归口] lean=0 本趟=16 别处=0 会话=['rc2-main-chain']
```

### 4.3 盘上终态没有退化

同一个文件里原有的正控 / 反真空 / 指针线 / Lean 关档四条全部照旧通过（9 passed）：
`statements` 1 行、pending 三行、稿上 `- V 签：…连续=3/3`、`nontriviality.jsonl` 一行 T2、
`deps_state="none_in_proof"`；反真空下 statements 0 行、无签块；Lean 关档名册里没有 L。
新增的 Lean 开档一条另钉：`lean_reading().verdict == "on"`、`is_hidden("L") is False`，
同一条链照样签 + 收录，两组新读数也干净。

---

## 五 原来 6 笔吞账与 7 条缺省会话事件，修后逐笔"去哪了"

### 5.1 6 笔 duplicate：全部正常入账，没有一笔"本就该合并"

它们不是重复调用：每笔的 `(role, 召唤号, 序号)` 都不同，只是旧命名空间只带召唤号，
让不同角色的 `idx=0`（以及 V 的两条缝）撞了同一个键。修后各自有行：

| 改前被吞的那一笔 | 改后行 | 归口 |
|---|---|---|
| `V`（工具路径，缺省会话）×2 | `000005`、`000007` | `V / t-000003 / idx 2、3` |
| `secretary:V` ×3 | `000004`、`000006`、`000008` | `secretary:V / t-000003 / idx 0、1、2` |
| `secretary:B` ×1 | `000013` | `secretary:B / t-000002 / idx 0` |

原来的 10 行模型调用账 + 2 行召唤结算 = 12 行，现在是 16 + 2 = 18 行。
两行结算（`settle-…`）本来就不是模型调用，改前改后都是 2 行 —— 它们不是被吞的那一类。

### 5.2 7 条缺省会话事件：全部搬回本趟会话

| 改前落在 `20261115.jsonl` 的 | 条数 | 为什么搬回来了 |
|---|---|---|
| `V`（工具路径） | 3 | `host.py` 装配期登记了 `role_seam("V")`，工具路径拿到带 `sid` 的那条缝 |
| `secretary:V`（V 的秘书） | 3 | `for_role_wired` 在 `sid is None` 时读 ambient sid（`calling_as` 挂的就是本趟 `sid`） |
| `secretary:B`（B 的秘书） | 1 | 同上（同一个装配点，一处修复覆盖两条角色） |

这三组在反真空里是分开验的：只撤 V 的登记 ⇒ 恰好 3 条；只摘秘书的 ambient sid ⇒
恰好 4 条；两半都撤 ⇒ 7 条。修后 16 条 `llm_call` 全在 `sessions/rc2-main-chain.jsonl`。

---

## 六 门

### 6.1 `noai_gate --paths`（提交前，9 条改动路径）

```text
$ python scripts/noai_gate.py --paths src/agentflow/agent_v/core.py src/agentflow/host.py src/agentflow/llmseam.py src/agentflow/secretary.py tests/test_rehearsal_cli_proof_main_chain.py tests/test_ledger_identity_antivacuum.py temp/vf/REPORT-VF.md temp/vf/probe_reading.py temp/vf/probe_antivacuum.py
[clean] required_approvals=0
clean：9 条改动路径均未命中禁改区（清单 49 条）⇒ 无需额外人工批准。
```

### 6.2 lint

```text
[linter] error 0 / warning 21 / info 44
```

warning 数与开工前一致（21）；中途 R009 曾报 6 个 error（新增注释里的 `**…**` 强调标记），
按"要强调就写进句子"逐处改成普通文字后归零。没有 skip / xfail / 放宽任何规则。

### 6.3 三格（`tools/repo_survey.py --json`）

```text
>800 行文件 75（上限 75）、>200 行 def 94（上限 95）、重复 docstring 段 2（上限 5）
```

一格未抬：`llmseam.py` 本来就在 `>800` 名单里（新增的是函数与注释，行数仍在该档），
新增的 `_idem_namespace` / `ambient_sid` / `_ambient_session_sid` 都远不到 200 行，
没有新增重复 docstring 段。

### 6.4 本路相关测试

```text
tests/test_rehearsal_same_path.py + test_rehearsal_cli_proof_main_chain.py + test_ledger_identity_antivacuum.py
    35 passed（82.64s）
tests/test_rehearsal_cli_proof_main_chain.py -q -s
    9 passed（27.82s）
tests/test_ledger_identity_antivacuum.py -q -s
    4 passed（13.22s）
```

另外跑了 3 批相关面（host/CLI/V/秘书/账本/verify/agent_b/agent_f/agent_e 等）：

```text
158 passed, 1 failed      （失败那条见下）
933 passed, 1 skipped, 4 failed（其中 1 条与上一行同一条）
```

**失败的全部 5 条（去重后 4 条）在 pristine HEAD 上一模一样地红**（用 `git stash` 把本路
改动全部收走后逐条复跑确认）：

```text
tests/test_secretary_adjudication_is_wired.py::test_the_agent_b_registration_route_wires_the_seam
tests/test_b_addressing_and_the_sign_gate.py::test_c_an_unreadable_address_is_a_refusal_not_a_disk_fallback
tests/test_b_addressing_and_the_sign_gate.py::test_d_stubbing_the_addressing_function_turns_a_red
tests/test_v_opinion_chain_reaches_f.py::test_c_tool_entry_reports_keys_its_declaration_does_not_promise
```

它们是与本路无关的既有红（前三条都是"多了一次 `secretary:statement_aesthetic` 判档调用"、
第四条是 `verify_proof` 返回键比声明多一个 `issued_sign`），本路没有为了让它们变绿改任何东西，
也没有把它们算进"修后绿"。

---

## 七 ⑤ 结论：这条链现在还差什么才配当"起真机"的前置

**这条链现在把"入口 / 装配 / 缝的实例 / 记账"四层都对齐到真机同形了（16 次真调用
↔ 16 行账、0 笔 duplicate、16 条事件全在本趟会话），但还差最后一层没验：真实出网那一端
的模型回复（真重试 / 真超时 / 真拒答 / 真计价）—— 彩排只换了网线，所以它配当"起真机"
的**前置**，而"这一趟的钱在真模型下也一分不少地记下来"仍要等真机那一趟来回答。**
