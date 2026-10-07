# B8a 证据：`G-18` · `G-13` · `G-20`

> 执行者：实现子智能体 B8a。核验者：主控。
> 工单：`temp/B8-workorder.md` §1.2 / §1.3 / §1.6。**§1.1（`P-8`）/ §1.4（`P-2`）/ §1.5（`P-3`）
> 未做**（落点与被 B4/B5 持有的 `agent_e.py` / `scripts/release_check.py` 共享）。
>
> 所有观测时刻都是本机时钟（UTC+08:00）。计数一律写成"区间 + 观测时刻"。
> 本文件里的原始输出全部来自 `temp/_b8a_*.txt`（探针脚本也在 `temp/_b8a_*.py`，可重跑）。

## 0. 两条必须最先说的更正（工单前提已过期）

工单 §1.2 / §1.3 的 **D 行**写的是"本机 Mathlib **没装**"。**这一条现在不成立**，
我实测到的是相反的事实。两条都在下面给出原始输出，请主控据此决定后续口径。

| # | 工单原文 | 我实测到的 | 证据 |
|---|---|---|---|
| 1 | "本机没有 Mathlib ⇒ `imports=[]` 的纯内核检查" | Mathlib **装了**：`temp\mathlib-pinned2\mathlib4-4.7.0`，4100 个 `.olean`，`Mathlib.olean` 在，`lake env lean` 下 `import Mathlib` **exit 0** | `temp/_b8a_mathlib_state.txt`、`temp/_b8a_mathlib_usable.txt`、`temp/_b8a_g13_importcheck2.txt` |
| 2 | "**Mathlib 本机根本没有安装**（两次独立探针结论相同）" | 见上。工单的两次探针大概只看了 `temp\lean470`（那确实只是一个 Lean 发行版），没看 `temp\mathlib-pinned2` | `temp/mathlib-pinned2/EVIDENCE.md`（别人早先的记录）；我复跑见上 |

**但工单观察到的那个现象是真的**：在 `D:\Incubator\agentflow` 里跑**裸 `lean`**
（没有 lake 工程上下文）时，`import Mathlib` 确实报 `error: unknown package 'Mathlib'`
—— 因为裸 `lean` 不会替你跑 `lake`。所以 `G-18` 的修法**不受影响**，
只是"C 行的成因"要改口径：不是"库没装"，而是"**这份源码没在 lake 环境里被检查**"。

⇒ `G-18` 的新取值我按工单要求做了（`import_unavailable` + 包名），
语义写成"检查器说找不到这些包，这次检查根本没发生"——它对"库没装"与
"没在 lake 环境里跑"两种情况都成立，且都**不是** `compile_error`。

## 1. `G-18`：库不可得给一个可区分的归处

### 1.1 改了什么

| 文件 | 改动 |
|---|---|
| `src/agentflow/formalgw.py` | `STATUSES` 八值 ⇒ **九值**（新增 `import_unavailable`）；新增 `missing_imports_of()` 与 `_MISSING_PACKAGE` 判据；`check_lean` 在"退出码非零"分支**之前**插入库不可得分支，并回传 `missing_imports` 包名列表；`_CONCLUDED_STATUSES` **不含**新值（它是"没查成"）；模块 docstring 的判据顺序表 + `evidence_of` docstring 同步 |
| `src/agentflow/tools/verify_tools.py`（**禁改区**） | `check_formal` 三条返回路径都新增 `missing_imports` 键；`returns=` 契约同步（第 7 个键）；summary 与三态表同步九值 |
| `tests/test_formalgw.py` | 词表断言八⇒九；新增 5 条离线用例（含**核心负控**：注入语法错仍须 `compile_error`） |
| `tests/test_tools_audit_fixes.py` | `test_check_formal_return_shape_matches_its_declaration` 的 `declared` 集合加 `missing_imports` |

**判据只认一种证据形态**：`unknown package '<名>'`（实测 Lean 4.7.0 的原话）。
刻意不认 `unknown module` / `object file ... does not exist`：判据越窄，
越不会把"真编译错"吞成"库不可得"。

### 1.2 四条控制（原文摘录）

探针：`temp/_b8a_g18_probe.py`（真起 Lean，PATH 里有 `temp\lean470\...\bin`）。
改前：`temp/_b8a_g18_before.txt`（观测 2026-09-26T03:27，退出码 0）。
改后：`temp/_b8a_g18_after.txt`（观测 2026-09-26T03:44，退出码 0）。

**正控（改前）** —— 内核路径今天是通的，这一条是"保护现状"：

```text
--- 正控 imports=[] ⇒ 期望 verified
    status='verified'
    reason="检查器退出码 0、无 sorry、公理 无 在允许集内、且声明 'agentflow_probe_add' 真的被检查到（用时 0.328 秒）"
    evidence={"checked": true, "proved": true, "evidence_kind": "proof", ...}
    output_head="'agentflow_probe_add' does not depend on any axioms"
```

**正控（改后）** —— 同一形态仍然绿：

```text
    status='verified'
    reason="检查器退出码 0、无 sorry、公理 无 在允许集内、且声明 'agentflow_probe_add' 真的被检查到（用时 0.344 秒）"
    evidence={"checked": true, "proved": true, "evidence_kind": "proof", ...}
```

**负控①（改前 ⇒ `compile_error`；改后 ⇒ `import_unavailable`）**：

```text
改前：status='compile_error'
      reason="...error: unknown package 'Mathlib'"

改后：status='import_unavailable'
      reason="检查器说找不到这些包：['Mathlib'] ⇒ 这次检查根本没发生（编译没开始），
              因此它既不是'证明通过'，也不是'证明没通过'。处置是装库或换 import 列表，不是改证明。..."
      evidence={"checked": false, "proved": false, "evidence_kind": null, ...}
      imports=['Mathlib']
```

**负控②（核心：注入语法错 ⇒ 必须仍是 `compile_error`）** —— 证明新判据没吞掉真编译错。
注入的是"缺 `:=`"（工单指定的形态）：源码
`theorem agentflow_probe_add (a b : Nat) : a + b = b + a Nat.add_comm a b`。

```text
改前：status='compile_error'  reason="...error: unexpected token '#print'; expected ':=', 'where' or '|'..."
改后：status='compile_error'  （逐字同上，未变）
      missing_imports=[]
```

**负控③（不存在的包 ⇒ 同样归新取值）**：

```text
改后：status='import_unavailable'  missing_imports=['Nonexistent']
      （Lean 回的是首段 `unknown package 'Nonexistent'`，如实记录这一点）
```

### 1.3 转发层（`verify.check_formal`）实测

探针：`temp/_b8a_g18_verify_tools_probe.py`（直接调函数，**绕开注册表** ——
避开 B4 正在改的 `.call(` 面）。输出：`temp/_b8a_g18_vt_after.txt`（观测 2026-09-26T03:45）。

```text
--- P1 无后端            keys=['checked','claim','detail','missing_imports','reason','verified','verifier_output']
                         reason='no_backend' checked=False missing_imports=[]
--- P2 有后端、没给源码   reason='no_script'  checked=False missing_imports=[]
--- P3 库不可得（默认）   reason='import_unavailable' checked=False missing_imports=['Mathlib']
--- P4 真语法错 imports=[] reason='compile_error' checked=True verified=False missing_imports=[]
--- P5 内核级正控 imports=[] reason='verified' checked=True verified=True
```

### 1.4 `G-18` 的两条**未核实 / 交接**

1. `agent_e.py` 侧**未改**（主控补充边界：它被 B4/B5 两边持有）。
   `agent_e` 的 `check_formal` 局部受控词表里接受新取值这一步**交接给 B5**（`G-24 ①` 那份词表）。
   **不是"忘了"，是有意留下的另一半**。
2. `tests/test_check_formal_wiring.py` 与 `tests/test_tools_audit_fixes.py` 的多数用例
   在本批**跑不出绿**，原因是 B4 正在给 `ToolRegistry.call()` 加 `role` 必填参数
   （观测 2026-09-26T03:20：`reg.call("verify.code_hash", ...)` ⇒
   `kind='role_denied'`）。**这与本批改动无关**：同一时刻 129 条失败全部落在
   `test_tools_*` / `test_agent_h` / `test_context_budget` 这些 B4/B5 的面上，
   我改到的模块一条都不在里面（分组明细见 `temp/_b8a_pytest_all.txt`）。
   ⇒ 我给 `returns=` 加第 7 个键这件事，**只能等 B4/B5 收口后由主控复跑确认**。

## 2. `G-13`：Lean/Mathlib 版本要求钉住并可核

### 2.1 改了什么

| 交付 | 落点 |
|---|---|
| ① 文档：装哪个、怎么装、装完怎么验 | **新增** `docs/FORMAL-TOOLCHAIN.md`（LF，106 行） |
| ② 可跑的检查，三态不折叠 | `formalgw.check_toolchain()` / `ToolchainReport` / `format_toolchain_report()` / `toolchain_main()`；CLI `python -m agentflow.formalgw --toolchain [--import-check]` |
| pin（唯一来源） | `formalgw.PINNED_LEAN_VERSION` = `4.7.0`、`PINNED_LEAN_COMMIT` = `6fce8f7d5cd1…`（40 位）、`PINNED_MATHLIB_COMMIT` = `a45ae6374714…`、`PINNED_MATHLIB_TAG` = `v4.7.0` |
| 测试 | `tests/test_formalgw.py` 新增 11 条（全部离线，注入 `which` / `run_fn` 构造"装了但版本不符"） |

**三态 + 第 4 个值**（写进 `VERSION_STATUSES` 与 docstring）：

| status | 含义 | 处置 | 退出码 |
|---|---|---|---|
| `installed_ok` | 装了且与 pin 逐位一致 | 可以用 | 0 |
| `version_mismatch` | 装了但版本不符 | 换版本（不是重装） | 3 |
| `not_installed` | 没装 | 装 | 2 |
| `check_failed`（不占三态） | 探测自己没做成 | 我们不知道 | 4 |

### 2.2 控制（原文摘录）

探针：`temp/_b8a_g13_probe.py`，输出 `temp/_b8a_g13_probe.txt`（观测 2026-09-26T03:46，退出码 0）。
**逐轴**报告（合起来的一句话结论只是便利；判据落在轴上，所以两面都能给）：

**正控 A：本机现状（`lean` 不在 PATH、没设 `AGENTFLOW_MATHLIB_ROOT`）**

```text
[toolchain] status=not_installed
  lean     : not_installed  (不在 PATH)        ← 与"装了但版本不符"分得开
  mathlib  : not_installed  (没有工程)
```

**正控 B：真 Lean（PATH 里）+ 真 Mathlib 工程根** —— ⚠️ **这里与工单 §1.3 的
"正控：本机现状（没装）⇒ 必须报'没装'"不同**：本机 Mathlib **是装了的**，
所以它如实报 `installed_ok`（见 §0 的更正）：

```text
[toolchain] status=installed_ok
  lean     : installed_ok  D:\Incubator\temp\lean470\lean-4.7.0-windows\bin\lean.EXE
             version=Lean (version 4.7.0, x86_64-w64-windows-gnu, commit 6fce8f7d5cd1, Release)
             commit =6fce8f7d5cd1  要求=6fce8f7d5cd1
  mathlib  : installed_ok  D:\Incubator\temp\mathlib-pinned2\mathlib4-4.7.0
             commit =a45ae63747140c1b2cbad9d46f518015c047047a  要求=a45ae6374714
             Mathlib commit a45ae6374714 与要求逐位一致（来源 stamp；tag 文件写的是 leanprover/lean4:v4.7.0）
```

**负控 C：故意传错的 commit（假 lean 报另一个 commit）⇒ 必须报"版本不符"**

```text
[toolchain] status=version_mismatch
  lean     : version_mismatch  C:/fake/lean.exe
             version=Lean (version 4.6.0, x86_64-w64-windows-gnu, commit deadbeefcafe, Release)
             commit =deadbeefcafe  要求=6fce8f7d5cd1
             装了 Lean，但版本不是 4.7.0：...
```

**负控 C2：版本号对、commit 不对 ⇒ 仍是"版本不符"**（证明 commit 是独立判据）

```text
  lean     : version_mismatch
             Lean 版本号对上了（4.7.0），但 commit 不是 6fce8f7d5cd1（读到 deadbeefcafe）⇒ 版本不符
```

**负控 D：Mathlib 树的 commit 是别的 ⇒ `mathlib: version_mismatch`**

```text
  mathlib  : version_mismatch  ...\tmpj4itifk9\mathlib4-4.7.0
             commit =00000000deadbeef000000000000000000000000  要求=a45ae6374714
             装了 Mathlib，但 commit 不是 a45ae6374714（读到 00000000dead，来源 git）⇒ 版本不符
```

**负控 E：探测自己炸了 ⇒ `check_failed`（不是"没装"）**

```text
  lean     : check_failed
             `lean --version` 没跑成（OSError: 起不来）⇒ 没查成，既不是'没装'也不是'版本不符'
```

**`--import-check` 真跑一次 `import Mathlib`**（`temp/_b8a_g13_importcheck2.txt`，观测 2026-09-26T03:47，退出码 0）：

```text
[toolchain] status=installed_ok
  import   : checked=True imports=True exit=0
             `import Mathlib` 真跑通了（工程声明的 lake 环境）
  ⇒ ok（退出码 0）
```

### 2.3 我自己核实到的两个 pin（不是引用文档）

| 事实 | 值 | 怎么核的 |
|---|---|---|
| Lean | `4.7.0`，commit `6fce8f7d5cd18a4419bca7fd51780c71c9b1cc5a` | `lean --version`（`temp/_b8a_lean_version.txt`）+ `lean --githash`（`temp/_b8a_lean_githash.txt`），均退出码 0 |
| Mathlib | commit `a45ae63747140c1b2cbad9d46f518015c047047a` | **本机这棵树没有 `.git`**（缓存解包出来的形态），所以我**无法从树内核实 commit** —— 我按 `docs/FORMAL-TOOLCHAIN.md` §2.2 第 4 步写下戳文件 `temp\mathlib-pinned2\mathlib4-4.7.0\.lake\agentflow-mathlib-rev`（一行 commit），值取自 `temp/mathlib-pinned2/EVIDENCE.md` 登记的 tree-integrity 结论（4451/4451 文件与 commit 逐一相同）。⚠️ **这是一个"别人早先的记录"转写的戳，不是我从树内独立核出来的** —— 如实登记为**未独立核实**。 |

**一处更正（B8a 自己踩的）**：`schema.py` 的备份
（`temp/schema.py.bak-b8a-20260926-034818`）是**改完之后**才拷的，
它的 sha256 与现在逐位相同 ⇒ **它不是改前形态**。判据的替代来源是
`git HEAD` 那一版（`temp/schema.py.HEAD-b8a`，sha256 `12cd4170adff…`）。
如实写在这里，不让它看起来像一次合规的改前备份。

## 3. `G-20`：成本归因（每次 `modelgw` 调用都带显式 `scope`）

### 3.1 缺陷的成因（就一行）

`modelcost.charge_reply(..., scope: str = "reason")` —— **缺省值本身**就是成因：
任何忘记传 scope 的调用点静默落进"推理"档，账本总额与条目数完全自洽，
只是"搜索/抽取/审校各花了多少"永远答不出来。
生产侧当时只有 **1 处**记账调用（`runflow.py` 的作答调用，硬写 `scope="reason"`）
⇒ 五档全无产出。

### 3.2 改了什么

| 文件 | 改动 |
|---|---|
| `src/agentflow/modelgw.py` | `complete(prompt, *, scope, ...)` —— **必填关键字参数**，取值必须在 `USAGE_SCOPES` 里（否则 `ValueError`）；`scope` 随 `ModelReply` 回传并进 `to_dict()`；四条 `_reply_failure` 失败路径也带上它（失败那一档也要能归口） |
| `src/agentflow/modelcost.py` | `charge_reply(..., scope: str, ...)` —— **去掉缺省值**；新增"`reply` 声明的 scope 与入账给的 scope 必须一致，否则 `ValueError`"；返回值也带 `scope` |
| `src/agentflow/schema.py`（**禁改区**） | 新增 `SCOPE_UNCLASSIFIED = "unclassified"`（**刻意不在** `USAGE_SCOPES` 里：那七档是调用方**声明**的用途，这个是读账方遇到编外值时的**显式落位**） |
| `src/agentflow/tokenmeter.py` | 新增 `by_scope()`：按用途归口汇总，**每一个 `USAGE_SCOPES` 档都出现（含零值）**，另加 `unclassified` 档（带 `raw_values` 记录编外原值） |
| `src/agentflow/runflow.py` | 新增 `SCOPE_ANSWER = "reason"` 常量；`gw.complete(..., scope=SCOPE_ANSWER)` + `charge_reply(..., scope=SCOPE_ANSWER)`；`_ledger_view` 加 `by_scope`（⇒ 进 `cost.json`）；`cost.json.per_call` 逐笔带 `scope`；自检加归口断言 |
| `tests/` | **新增** `test_usage_scope_attribution.py`（8 条：正控 4 + 负控 4）；`test_modelgw.py` 加 4 条 scope 契约用例、9 处调用点补 `scope=`；`test_modelcost.py` / `test_idem_key_writers.py` / `_mp_idem_worker.py` 补 `scope=` |

### 3.3 正控（原文摘录）

探针：`temp/_b8a_g20_probe.py`，输出 `temp/_b8a_g20_probe.txt`（观测 2026-09-26T03:48，退出码 0）。

```text
===== G-20 探针（改后）=====
USAGE_SCOPES = ('summon', 'experiment', 'search', 'extract', 'review', 'reason', 'other')
SCOPE_UNCLASSIFIED = 'unclassified'（不在 USAGE_SCOPES 里）
--- 正控：多角色流程 ['search', 'extract', 'review', 'reason']
    call0 role=A scope=search  -> charged=True reason=charged scope_returned='search'  reply.scope='search'  tokens=120
    call1 role=B scope=extract -> charged=True reason=charged scope_returned='extract' reply.scope='extract' tokens=120
    call2 role=H scope=review  -> charged=True reason=charged scope_returned='review'  reply.scope='review'  tokens=120
    call3 role=M scope=reason  -> charged=True reason=charged scope_returned='reason'  reply.scope='reason'  tokens=120
    summon         entries=0 tokens=0   usd=0.0 roles={}
    experiment     entries=0 tokens=0   usd=0.0 roles={}
    search         entries=1 tokens=120 usd=4.9e-05 roles={'A': 1}
    extract        entries=1 tokens=120 usd=4.9e-05 roles={'B': 1}
    review         entries=1 tokens=120 usd=4.9e-05 roles={'H': 1}
    reason         entries=1 tokens=120 usd=4.9e-05 roles={'M': 1}
    other          entries=0 tokens=0   usd=0.0 roles={}
    unclassified   entries=0 tokens=0   usd=0.0 roles={} raw_values=[]
    分档 tokens 之和 = 480
    非零档 = ['extract', 'reason', 'review', 'search']（4 档）
    账本总额 spent = {'entries': 4, 'tokens': 480, 'usd': 0.000196, 'attempts': 4}
    verify_all issues = []          ← usage_task_total_mismatch 不响
```

⇒ **≥4 档非零（4 档）**、**总额不变（分档之和 480 == spent 480）**、
`verify_all` 零 issue。用真 `ModelGateway` + 假传输 + 真 `TokenMeter`/`Store`。
⚠️ 如实说明这套多角色流程的边界：生产侧目前**只有 `runflow` 的作答一步**
接了记账（`scope=reason`），A/B/H 的模型调用今天还没有 `modelgw` 调用点
（它们是可选 `llm` 钩子）。所以本正控证明的是"**机制成立**：四个不同步的调用
各自落到自己那一档、且总额不变"，**不是**"生产的多角色链路今天已经全在记账"。
把 A/B/H 接上 `modelgw` 是后续工作，本批没有替它做（那会越界改 `agent_*.py`）。

`cost.json` 形状的正控（`tests/test_usage_scope_attribution.py::test_runflow_costs_are_readable_by_scope`
+ `formalgw` 风格的自检）：`usage_ledger.by_scope` 七档 + `unclassified` 全在场，
`per_call[].scope == ["reason", "reason"]`。

### 3.4 负控（原文摘录）

```text
--- 负控①：把 scope 注掉（不传）⇒ 必须当场报错，且该档不被顶上
    TypeError: charge_reply() missing 1 required keyword-only argument: 'scope'
    账本行数 = 4（应仍为 4，注掉的那次没落档）
    search 档 entries = 1（应仍为 1），other 档 = 0（应为 0）
    总额 spent 未变 = 480

--- 负控②：网关说 extract、入账说 review ⇒ 必须当场报错
    ValueError: reply 声明的 scope 是 'extract'，入账时给的是 'review' ⇒ 同一次调用在两处有两个归口，
                两个数字都会自洽而互相矛盾。...

--- 负控③：词表外的 scope ⇒ 写入侧当场拒绝
    scope=''         -> ValueError: scope 必须是 ('summon', 'experiment', 'search', 'extract', 'review', 'reason', 'other') 之一
    scope='shopping' -> ValueError: 同上
    网关侧 scope='shopping' -> ValueError: 同上
```

**"编外值落到未分类档"这一半**（工单负控要的"归零或落未分类必须可见"）：
写入侧是 fail-closed 的（`UsageEntry.validate` 与 `Charge.validate` 都当场拒绝），
所以账本里出现编外 scope 只能来自**另一个写入方**（旧版本进程 / 手改 JSON）。
读账那一侧必须对它有确定的可见处置 —— 用构造账本行验（
`test_a_scope_outside_the_vocabulary_lands_in_unclassified_visibly`）：

```text
unclassified   entries=2 tokens=10 raw_values=['', 'shopping']
other          entries=0        ← 编外值不许被塞进 other
search         entries=1 tokens=120
分档之和 == spent   ← 未分类那一档没把钱弄丢
```

## 4. EOL 判据（"与该文件改前形态一致"，**不是**"CRLF=0"）

脚本 `temp/_b8a_eol_check.py`，输出 `temp/_b8a_eol_vs_before.txt`（观测 2026-09-26T03:49）。

```text
=== ① 与 B8a 自备备份比（禁改区文件的改前形态）===
  EOL-SAME    改前=CRLF  现在=CRLF   src/agentflow/tools/verify_tools.py
  EOL-SAME    改前=LF    现在=LF     src/agentflow/formalgw.py

=== ①b schema.py：备份是改后拷的（无效），改用 git HEAD 快照 ===
  EOL-SAME    HEAD=CRLF  现在=CRLF   src/agentflow/schema.py

=== ② 改前 / 现在（B8a 自己改过的文件）===
  EOL-SAME  改前=LF   现在=LF    src/agentflow/formalgw.py
  EOL-SAME  改前=CRLF 现在=CRLF  src/agentflow/tools/verify_tools.py
  EOL-SAME  改前=CRLF 现在=CRLF  src/agentflow/modelcost.py
  EOL-SAME  改前=CRLF 现在=CRLF  src/agentflow/modelgw.py
  EOL-SAME  改前=LF   现在=LF    src/agentflow/tokenmeter.py
  EOL-SAME  改前=LF   现在=LF    src/agentflow/runflow.py
  EOL-SAME  改前=CRLF 现在=CRLF  src/agentflow/schema.py
  EOL-SAME  改前=LF   现在=LF    tests/test_formalgw.py
  EOL-SAME  改前=LF   现在=LF    tests/test_modelcost.py

结论：改过的既有文件里 EOL 形态变化的数量 = 0（应为 0）
```

**新造文件的 EOL 判据（自定并写下来）**：`tests/test_usage_scope_attribution.py`、
`tests/test_modelgw.py`、`tests/test_idem_key_writers.py`、`tests/_mp_idem_worker.py`、
`docs/FORMAL-TOOLCHAIN.md` 都是 **LF**。理由：本仓库的 `.py` **两种形态都有**
（LF 46 个 / CRLF 34 个，`temp/_b8a_eol_before.txt` 就是反例集合：
`formalgw.py`/`runflow.py`/`tokenmeter.py` 是 LF，`modelgw.py`/`verify_tools.py` 是 CRLF），
所以新文件的判据只能自定一条：**跟同目录同族文件的形态走**（这几支恰好都是 LF）。
**不是**"CRLF 才对"。

## 5. `sha256` 与备份

### 5.1 改前（本批观测）

| 文件 | 改前 sha256 | EOL |
|---|---|---|
| `src/agentflow/formalgw.py` | `b8ab0e81df5f37a546b03fe0ae64647da6c2c6d9b2bc34fe79eaf4afcbbe0b16` | LF |
| `src/agentflow/tools/verify_tools.py` | `8b8b87cf788bb1633c5e6201371e1488a1ec3a87e36683ba48ad4d8d272f0484` | CRLF |
| `src/agentflow/modelcost.py` | `70ca9d427b268f46de0f07ba382f0492d4d72a0fce5a0ea0645ed94463d03a1d` | CRLF |
| `src/agentflow/modelgw.py` | `12b38416bbc58fabb0e00d39a01cdcd6d02c2202f1603bb2a7ab6fa16c9cc578` | CRLF |
| `src/agentflow/tokenmeter.py` | `616ba8ce874a3de7bebec73d4facdcfe0165e87359a2561986efed6bb15b8c64` | LF |
| `src/agentflow/runflow.py` | `fd2bc73cff0c83b4ab3ea09df6a100a565fb866a6fe50c55a0295d9752ccf277` | LF |
| `tests/test_formalgw.py` | `ccfaede675acabef87bea0e1d6255fa461bbd259d45c9235164fc05b8f163aa4` | LF |
| `tests/test_modelcost.py` | `d0a17ee8ddc520d52f181c2cebda0dbd454379fec7fac873acb404c313c8abc1` | LF |
| `src/agentflow/schema.py` | ❓**未在改前测到**（见 §2.3 的更正）。`git HEAD` 版 = `12cd4170adffd8c15b6dabd3fcf1eb915a47da1503d4e502b18abd4e9035fe36` | CRLF |

来源：`temp/_b8a_sha_before.txt` / `temp/_b8a_eol_before.txt`（观测 2026-09-26T03:26）。

### 5.2 改后（观测 2026-09-26T03:50）

| 文件 | 改后 sha256 |
|---|---|
| `src/agentflow/formalgw.py` | `c431d532a57a022814b456201769b7ef2f9408f8cb24b4f47a0f46b6e13e7bce` |
| `src/agentflow/tools/verify_tools.py` | `3854edb25387ac1761c2edf658e88ee3e56421343974705ab3a823c402dc98b7` |
| `src/agentflow/schema.py` | `5b8d5d130ce209ac1020cc24942581730a6acfbe9b32de416fdc52fff7d75510` |
| `src/agentflow/modelcost.py` | `24849a42ce15cd302a17d19937092136ffe499ef2f7809578b73cf854a752e79` |
| `src/agentflow/modelgw.py` | `4756794dbf7d62f14d9d4857f654df54c35ed930d4334980982063be807028a2` |
| `src/agentflow/tokenmeter.py` | `94dec877e9085d0034d19b85b36658478f97d0019794901163f90fc58d898031` |
| `src/agentflow/runflow.py` | `b31d52e6f123698d3fb1f7a646bdeb1f8ca5c275a7c9278faa45533306dfeaea` |
| `tests/test_formalgw.py` | `792e1ac620c9e2d7a11939ed8960f508383582347066ba61513137209b11bf01` |
| `tests/test_modelgw.py` | `91c4a97cddceab0d4171d05f555b835a5360922c86b597fe3f822713e9f83d65` |
| `tests/test_modelcost.py` | `2c7be9be937282c906223a42a6ef5bfeafa1c2dc97e6e3c4ae2a3f30711a018d` |
| `tests/test_usage_scope_attribution.py` | `2efd56cf61acaf36cad24ce54ccc0d2b359545866409c9eceb033df87f1a38d5` |
| `tests/test_idem_key_writers.py` | `af53ee8892377125f46eaffb06c1bc82c1db5334ef44be2e734f77ad4f86eab1` |
| `tests/_mp_idem_worker.py` | `68b2fddbf73106619637048e141c93aa7ace6cd0ce52c8417e2d7defdc9c2bc3` |
| `tests/test_tools_audit_fixes.py` | `29d0e63da295e25c698a217b73ca9bf1cf0a774f7757e42a1b4e153b18d35dcf` |
| `docs/FORMAL-TOOLCHAIN.md`（新） | `623d050d0531177ed57f7137c0b3e3b62655209624c01e637f8aa86ddbf2a348` |

### 5.3 备份文件名

| 备份 | 覆盖的文件 | 说明 |
|---|---|---|
| `temp/verify_tools.py.bak-b8a-20260926-032545` | `src/agentflow/tools/verify_tools.py` | **改前**拷的，sha256 与 §5.1 逐位一致 ✅ |
| `temp/formalgw.py.pre-g18-20260926-032627` | `src/agentflow/formalgw.py` | **改前**拷的 ✅ |
| `temp/schema.py.bak-b8a-20260926-034818` | `src/agentflow/schema.py` | ⚠️ **改后**拷的，不是改前形态（见 §2.3） |
| `temp/schema.py.HEAD-b8a` | `src/agentflow/schema.py` 的 `git HEAD` 版 | 替代用的改前快照 |
| `temp/_b8a_mathlib_usage` 等探针 / 输出 | — | 见各节引用的 `temp/_b8a_*.txt` |

## 6. 禁改区台账（`noai_gate`）

### 6.1 一致性（观测 2026-09-26T03:49）

```text
$ python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
exit=0
```

### 6.2 命中的两条 + 基线刷新

`--paths` 命中 2 条禁改区路径：`src/agentflow/tools/verify_tools.py`（prover-bridge）
与 `src/agentflow/schema.py`（schema-migration + eval-criteria）。

```text
$ python scripts/noai_gate.py --paths ... --baseline --note "B8a/G-18：..."
[baseline] 登记 2 条 / 未登记 0 条；台账：D:\Incubator\agentflow\.noai-approvals.json
  · src/agentflow/tools/verify_tools.py  refreshed  sha256 3854edb25387  [prover-bridge]  reviewers=0
  · src/agentflow/schema.py              unchanged  sha256 5b8d5d130ce2  [schema-migration]  reviewers=0
exit=0
```

`reviewers_total` = **0**（16 条条目，观测 2026-09-26T03:49）—— **本批没有写 `reviewers`，
一个字都没有**。`--check-approvals` 如实报欠签（这是应有的方向）：

```text
$ python scripts/noai_gate.py --check-approvals --paths src/agentflow/tools/verify_tools.py src/agentflow/schema.py
[requires_human] required_approvals=2
命中 2 条禁改区路径，其中 2 条未获批准（insufficient_reviewers 2 条）
  - src/agentflow/schema.py              ⇒ [unapproved] insufficient_reviewers：hash 一致，但已完成的人工走查只有 0/2 名不同 reviewer
  - src/agentflow/tools/verify_tools.py  ⇒ [unapproved] insufficient_reviewers：hash 一致，但已完成的人工走查只有 0/2 名不同 reviewer
exit=1
```

⚠️ `schema.py` 在台账里是 `unchanged`：因为**别的智能体**在我改完之后、
我刷基线之前已经用它当前的内容刷过一次基线（我改的只有新增一个常量，
所以两边算出的 sha256 相同）。这一条如实记下。

### 6.3 `schema.py` 改动的性质（请主控据此判断要不要人审）

只新增一个模块级常量 `SCOPE_UNCLASSIFIED = "unclassified"`（+ 一段注释），
**没有**动 `SCHEMA_VERSION`、`TABLES`、`EVAL_REQUIRED_FIELDS`、`EvalResult`、
任何 `validate()`。也就是说：**磁盘格式契约与评测口径都没有变**。
它落在禁改区清单里是因为 `schema.py` 整体被登记（`schema-migration`），
不是因为这次改动碰了那两件事。

## 7. 本批跑过哪些测试

### 7.1 达标的一组（观测 2026-09-26T03:47）

```text
$ python -m pytest tests/test_formalgw.py tests/test_modelgw.py tests/test_modelcost.py \
    tests/test_tokenmeter.py tests/test_usage_scope_attribution.py tests/test_idem_key_writers.py \
    tests/test_usage_ledger_idem_key.py tests/test_runflow_lean.py tests/test_demo_end_to_end.py -q
168 passed in 17.58s
exit=0
```

（`tests/test_formalgw.py` 单跑 `62 passed`；`tests/test_usage_scope_attribution.py` 单跑 `8 passed`；
`tests/test_modelgw.py` 单跑 `20 passed`；`tests/test_modelcost.py` 单跑 `20 passed`。）

### 7.2 全量（**不是本批的绿**，如实报告）

```text
$ python -m pytest tests/ -q      # 观测 2026-09-26T03:29，耗时 323.82s
129 failed, 1773 passed, 8 deselected, 1 xfailed, 1 warning, 22 errors
```

**失败分组（全部落在 B4/B5 正在飞的文件上）**：

| 组 | 条数 | 文件 |
|---|---|---|
| A | 27 | `tests/test_tools_audit_fixes.py` |
| B | 26 | `tests/test_tools_table_fs.py` |
| C | 15 | `tests/test_tools_attack_graph_fixes.py` |
| D | 14 | `tests/test_tools_search_ocr.py` |
| E | 13 | `tests/test_tools_graph_trace.py` |
| F | 11 | `tests/test_agent_h.py`（ERROR） |
| G | 10 | `tests/test_tools_returns_declaration.py`（ERROR） |
| H | 7 | `tests/test_agent_h.py` |
| I | 5 | `tests/test_core_audit_efgh.py` |
| J | 5 | `tests/test_fc17_wiring.py` |
| K | 4 | `tests/test_context_budget.py` |
| L | 4 | `tests/test_tools_param_validation.py` |
| M | 3 | `tests/test_agent_g.py` |
| N | 2 | `tests/test_gates.py` |
| O | 1 | `tests/test_check_formal_wiring.py` / `tests/test_agent_f.py` / `tests/test_agent_e.py` / `tests/test_core_audit_abc_cli.py` / `tests/test_coverage_agent_h.py`（ERROR） |

根因（实测一条）：`ToolRegistry.call()` 现在要求 `role`，
`reg.call("verify.code_hash", path=...)` ⇒
`kind='role_denied'`、`error="调用方没有声明角色，无法判定它能不能调 ..."`（观测 2026-09-26T03:20）。
**我改到的模块（`formalgw` / `modelgw` / `modelcost` / `tokenmeter` / `runflow` / `schema` /
对应测试）一条失败都不在里面。** 全量两环境与逐文件那一遍按工单由主控复跑。

### 7.3 `lint_rules.py`

```text
$ python scripts/lint_rules.py --json <tmp>
[...] error 6 / warning 3 / info 17      # 观测 2026-09-26T03:49
```

**我改到的文件里 error = 0**（逐次核对：`formalgw.py` / `modelgw.py` / `modelcost.py` /
`tokenmeter.py` / `runflow.py` / `test_formalgw.py` / `test_modelgw.py` / `test_modelcost.py` /
`test_usage_scope_attribution.py` 全为 0）。剩下 6 条 error 的落点是
`src/agentflow/agent_h.py`、`src/agentflow/tools/doc_tools.py`、
`tests/test_dup_consolidation.py`、`tests/test_schema.py`、`tests/test_verify_extended.py`
与 `<linter>` 汇总行 —— **都是别的智能体正在飞的文件**。
⚠️ 另有 `info R009` 一条：禁改区 13 个文件里仍有 ~480 处装饰，其中
`tools/verify_tools.py` 占 ~38 处 —— **这些按 FC-27 不计入判据**，
我新增的注释/docstring 里没有强调标记。

## 8. 未核实 / 没做（明确列出，不含糊）

1. **`agent_e.py` 侧未改**（有意）：`check_formal` 的局部受控词表接受
   `import_unavailable` 这一步**交接给 B5**（`G-24 ①`）。
2. **`G-13` 的 Mathlib commit 不是我从树内独立核出来的**：本机那棵树没有 `.git`，
   戳文件的值转写自 `temp/mathlib-pinned2/EVIDENCE.md`（别人的记录）。标为**未独立核实**。
3. **`G-13` 正控与工单不同**：工单要"本机现状 ⇒ 必须报'没装'"，实测 Mathlib 装了
   ⇒ 报 `installed_ok`。见 §0 的更正（我按实测写，没有把结论改到迎合工单）。
4. **`G-20` 的多角色正控是"机制"而不是"生产链路"**：生产侧今天只有 `runflow`
   的作答一步在记账；把 A/B/H 接上 `modelgw` 会越界改 `agent_*.py`，本批没做。
5. **`test_check_formal_wiring.py` / `test_tools_returns_declaration.py` 未能证实我的改动**：
   被 B4 的 `role` 面挡住（§1.4 第 2 条）。我的替代证据是直接调函数的探针
   （`temp/_b8a_g18_vt_after.txt`，5 条路径全部按契约返回 7 个键）。
6. **`schema.py` 的改前备份没留**（§2.3 / §5.3 的更正）。
7. **未跑**：`python tools/run_each_test_file.py`、`pytest -m network`、
   `temp/_axes_snapshot.py` 差分 —— 按工单 §2 这三项由主控复跑。
8. **`§1.1 P-8` / `§1.4 P-2` / `§1.5 P-3` 一个字节都没碰**（核实过：本批 `--paths`
   给我的改动集里没有 `agent_e.py` / `scripts/release_check.py`；
   这两个文件在 2026-09-26T03:20–03:50 之间被 B4/B5 持续改动）。
