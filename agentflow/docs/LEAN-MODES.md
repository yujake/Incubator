# 有 Lean / 无 Lean 的精确工作方式切分

> 依据：三份只读审计 `temp/probes/_lean_audit_switchpath.md`、`_lean_audit_prompts.md`、`_lean_audit_gate.md`
> （2026-10-17，每条都带 `file:line`）。本文把"两种模式下各角色该做什么 / 哪些动作可用或被拒 /
> 证据上限 / 收工门各格判什么"写成一张可核对的表。**它是判据的规格**：
> `tests/test_lean_modes_matrix.py` 逐行断言这里的每一条。

## 0. 先分清两个开关（最容易搞错的一条）

| 开关 | 位置 | 缺省 | 管什么 |
|---|---|---|---|
| CLI `--lean` | `cli.py` 的 `run` / `project`，`store_true` | **关** | **只**管 runflow 的 Lean 段：找答复里的 ```` ```lean ```` 块、调 `check_lean` |
| `toolchain.lean_enabled`（或 `AGENTFLOW_LEAN_ENABLED`） | `settings.py` | **关**（`DEFAULT_LEAN_ENABLED = False`，读不懂 ⇒ **当关**，fail-closed） | 管 `check_lean` / `check_formal` / `run_experiment(formal)` / 收工门 `load_bearing` / 用词上限 / **提示词改写** |

**两者无耦合**。

> ⚠️ **2026-10-17 实测更正**：`--lean` 与 `--prompt-version` 只挂在 **`run` / `project`（runflow）**两个子命令上；
> **`run-agent`（M 的智能体循环）不接受这两个参数**（`error: unrecognized arguments`）。
> 所以"带 Lean 跑一趟智能体任务"的**唯一**入口是设置开关：`AGENTFLOW_LEAN_ENABLED=1`（或设置文件
> `toolchain.lean_enabled`）。这也意味着 `v2-lean` 那套提示词**只属于 runflow**，与 M/E 的提示词无关。

四种组合：

| `--lean` | `lean_enabled` | 结果 |
|---|---|---|
| 关 | 关 | 无 Lean 模式（**当前默认**） |
| **开** | **关** | **假开**：`lean_disabled`（"开启=是、跑过=否"）——最常见误解 |
| 关 | 开 | 工具面允许形式化，但 runflow 那段不跑 |
| **开** | **开** | 真 Lean 模式；要 proof 级证据还需 `--prompt-version v2-lean`（`runflow.py` 逐字："用 `v1` + `--lean` 跑出来的永远是「开启=是、跑过=否、没有可检查的代码」"） |

## 1. 提示词面的可见差异（角色看到什么）

| 面 | 无 Lean | 有 Lean |
|---|---|---|
| `TOOLCHAIN_FACTS` **第一行**（六处指令都写"看第一行"） | `- Lean 形式化：**已关闭**（<来源> = false）⇒ 本会话不做形式化验证（系统做不了）` | `- Lean 形式化：**已开启**（lean_enabled = true）⇒ 本会话**可以**走形式化这条路` |
| `TOOLCHAIN_FORMAL` 段 | **整段不载入** | 载入 |
| `_apply_no_lean_variant` 改写 | 按表替换/删行/删块 | **逐字返回原文** |
| V 的强度声明 | `成立` 是逐行结论、**永远不是 `proof`** | **同一句**（强度声明不随开关变） |
| E 的形式化义务 | 不适用 | **必须至少试一次 `method=formal`**（"一次都不试"不算完成） |
| M 的派活义务 | 不适用 | 任务要求形式化时**必须**派 `check_formal` ＋ `run_experiment(formal)` |
| H 的采信 | 采信 V 的逐行签字 | 要 `evidence_kind=proof`；**"开着但无检查器"⇒ 按"没查"** ＋ findings 写环境缺口 |

### 1b. 另外四处也被同一开关改写的面（S6 收口，2026-10-17 补齐）

| 面 | 无 Lean | 有 Lean |
|---|---|---|
| `profiles_markdown`（`AGENT-PROFILES.md` 的产出源） | 出口套 `_apply_no_lean_variant` ⇒ E 那行变成「数值实验与**证明审阅**…（本会话不做形式化验证）」 | 原样保留「数值实验与形式化验证…可检查的形式化代码」 |
| `index_block`（技能索引） | 末尾加一句「**本会话 Lean 形式化关闭**：上面若有一条讲形式化的技能，它读来也做不了」 | 不加 |
| `FACULTY_LOCAL[("H","手")]` | 「找 A（引文）/ **E（形式化或实验）** 核实」——**措辞中性，两种模式同一句** | 同左 |
| `specs/h.py` 的 `local_notes` 副本 | 与上一条必须**逐字一致**（`test_agent_spec_reconciliation` 会判） | 同左 |

## 2. 动作面

| 动作 | 无 Lean | 有 Lean |
|---|---|---|
| `verify.check_formal` | 直拒：`ok` 但 `verified=None`、`reason="lean_disabled"`（**不是**工具失败） | 真起检查器（默认超时 **600 s**）；`read`+`exec` ⇒ 沙箱不可用时**每次都要签字** |
| `E.run_experiment(method="formal")` | 跑脚本前 `raise ExperimentError` | 三条硬前置：`.lean` 后缀、唯一声明名、`verified` 才给 `proof` |
| `verify.detect_verifier` | 报环境事实 ＋ `lean_enabled=False`、`can_do_formal=False` ＋ note（"那是**许可**问题，不是环境问题"） | 同上，`can_do_formal = 装了 且 开着` |
| `E` 的 `code/lean/<名字>.lean` | 该条政策被**整行删**（不要求） | 要求落盘（裁决与落库之间只差这一步） |
| Mathlib 编译探针（180 s） | 免做，读数"没查" | 真跑（只在开时） |

## 3. 证据上限（词表口径）

`method ∈ (numeric, symbolic, exhaustive_search, formal)`；**实验表**的 `evidence_kind ∈ (proof, cross_check, heuristic)` —— **`proof_review` 在实验表里结构上不存在**（它是"审阅"等级，凭据在 `verifications/<命题号>.jsonl`）。

| 档 | 何时可达 | 结构约束 |
|---|---|---|
| `proof` | **只有** `method="formal"` 且 `verified` | 必须 `verifier_output` 非空 ＋ `verifier_subject_key == claim_key`；`result="refutes"` 时**禁止** |
| `cross_check` / `heuristic` | 两种模式都可达 | 非 verified 的 formal 实验一律落 `heuristic` |
| `proof_review`（文档断言的用词档） | 无 Lean 时**多放一档**进用词上限 | 必须带"逐行审阅过的证明，未经机器检查" |

**已知边界**：`Statement.evidence_kind` 用全词表但**没有** method/verifier 耦合 ⇒ 命题台账可以自称 `proof` 而没有任何检查器输出。这是**已登记的边界**，不是本模式切分的一部分。

## 4. 收工门各格

| 验收行 | 无 Lean | 有 Lean |
|---|---|---|
| `load_bearing` | **`na`**（第四态：不进 `unknowns`/`failed`，但让 `machine_pass` 变假）＋ 替代读数 `prose_reviewed_statements` | `pass` / `fail`（blocker `load_bearing_without_t3`）：每条 `evidence_kind=proof` 的正文断言都要有 T3 背书（`method=formal` ＋ `evidence_kind=proof` ＋ `verifier_output` 非空） |
| `proof_experiment_rows` | **结构性恒 0**；`min` 缺省 **1** ⇒ **unmet** | 可达（要真有 formal 实验） |
| `reviewed_proof_rows` | 可达（读到 `pre_theorem` 等） | 可达 |
| `counterexample_or_proof_rows` | 可达 | 可达 |

> 三条 proof 类验收行**不看开关**。所以"关着 Lean 却把 `proof_experiment_rows` 写进验收表"必然 fail —— 要么开 Lean，要么把那一行写成 `na` ＋ 理由。

## 5. 失败分类（决定处置，不要混）

| kind | 含义 | 处置 |
|---|---|---|
| `lean_disabled` | 开关关着（或读不懂按关） | **改设置**，别重试 |
| `no_backend` | 开着但机器上没有检查器 | 装 Lean |
| `tool_crashed` ＋"探测没做成" | 显式配置指了**不存在的路径** | 修 `lean_bin` |
| `import_unavailable` | 退出码非零且 `error: unknown package` | 装库 / 换 import |
| `timeout` | 默认 600 s | 加时间 |
| `compile_error` | 真编译失败（记真实非零 `exit_code`） | 改代码 |
| `source_unreadable` / `decl_mismatch` / `uses_sorry` / `extra_axioms` | 受控拒收 | 按消息改 |

**"没查成"永不写 `failed`**：`EXPERIMENT_RESULTS` 只有 `supports/refutes/inconclusive`；行形状是 `result="inconclusive"` ＋ `evidence_kind="heuristic"` ＋ `observations.tri_state ∈ {verified, checked_failed, not_checked}`。任何按 `result`/`exit_code` 分成功失败的下游都会把"没查成"读成"没通过"。

## 6. 台账可复核性的两条已知缺口

1. **`lean_version` 未落台账**（`check_formal` 的 data 九键与 meta 都没有它；`toolchain_report` 里有但与台账无关）；
2. **`source_sha256` 只到工具层 meta**，落行的只有 `code_hash`（且仅当有 `code_path`，sha256 前 16 位）。

⇒ "哪个 Lean 版本核的哪一版源码"目前**读不出来**。要可复核就得补落这两格（`schema.py` 属禁改区）。

## 6b. 一条工程纪律（r61 的真实教训）

`verify.detect_verifier` 新增的 `note` **必须在两种模式下都存在**（开着时是空串）：
声明了 `returns` 的键如果按条件返回，"声明一套、返回另一套"的判据会红。
**结论：`returns` 里写了的键，任何模式下都要有那一格。**

## 7. 一句话总结

- **无 Lean 模式**：一切照旧，但**证据上限是 `proof_review`/`cross_check`**，`load_bearing` 是 `na`，`proof` 档产不出来；V 的「成立」是逐行结论。
- **有 Lean 模式**：E/M **有形式化义务**、H 要 `proof`、`load_bearing` 变成真判据；但**受环境约束**（`no_backend`/`tool_crashed`/`import_unavailable`），且"开着但没检查器"这一档 **H 必须按"没查"处置**。
