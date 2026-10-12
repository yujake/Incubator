# `toolchain.lean_enabled` 影响面清单（Lean / Mathlib / 形式化验证 / proof 级证据）

调查口径：只读。**未修改任何既有文件**（本清单是新建的调查产物）。
路径一律相对仓库根 `D:\Incubator`。

标注约定：`没查到/不确定` 一律明写，不猜。

---

## 0. 先说三条与开关设计直接相关的事实

1. 今天**不存在** `toolchain.lean_enabled` 这个键。`toolchain` 段认识的键只有四个
   （`agentflow/src/agentflow/settings.py:135`）。
2. 今天已存在**四个各自独立的 Lean 开关**，都不是 `toolchain.*`：
   - `runflow` 这条流程的 `--lean`（`agentflow/src/agentflow/cli.py:2309`、`:2348`）；
   - `projects.run` 的 `lean=` 形参（`agentflow/src/agentflow/projects.py:557`、`:661`）；
   - 提示词里的 `TOOLCHAIN_FACTS` / `TOOLCHAIN_FORMAL` 两段（现算，无开关）；
   - `check_formal` / `run_experiment(method='formal')` 这两个工具（无开关）。
   ⇒ 开关要落地，是**新增一根横切轴**，而不是打开一个已有的位。
3. "proof 级证据"不是一个开关，而是**六处硬约束的交点**（schema 写入期 / 收工门 /
   审计 / 文档工具 / 五元位 / 提示词）。所以 `lean_enabled=false` 不是"关掉一个工具"，
   而是"换一条证据口径"。

---

## 1. 设置与读数

| 文件:行 | 这里在干什么（口径/实现/判据/提示词/文档） |
|---|---|
| `agentflow/src/agentflow/settings.py:30-33` | **口径（文档）**：模块 docstring 的键表，逐字列出 `toolchain` 的四键含义（`lean_bin` / `mathlib_root` / `coq_bin` / `isabelle_bin`）。**新键要加在这一张表里**。 |
| `agentflow/src/agentflow/settings.py:135` | **实现（唯一词表）**：`TOOLCHAIN_KEYS = ("lean_bin", "mathlib_root", "coq_bin", "isabelle_bin")` —— `toolchain` 段认识的键的单一来源；`lean_enabled` 必须加进这里，否则 `toolchain_settings()` 会把它折成空串。 |
| `agentflow/src/agentflow/settings.py:197-209` | **实现**：`_section()` —— "只认登记过的键、值统一成去空白字符串、非字符串折成空串（=未设置）"。注意：**布尔值会被折成空串**（`isinstance(seg.get(k), str)` 为假）⇒ 若 `lean_enabled` 是真布尔，这一层必须改，否则永远读不到。 |
| `agentflow/src/agentflow/settings.py:212-219` | **实现**：`toolchain_settings()` —— `toolchain` 段的唯一取值口，四键"总是在"返回里（空串=未设置）。 |
| `agentflow/src/agentflow/settings.example.json:4-6` | **文档（示例文件）**：题录那几条示例说明行（工具链取值形态、工具链落点、Mathlib 落点）逐条给出本机落点的相对写法。开关要在这里补一行示例与说明。 |
| `agentflow/settings.example.json:11-16` | **文档（示例文件）**：`toolchain` 段实体（`lean_bin` / `mathlib_root` / `coq_bin` / `isabelle_bin` 全是空串）。**这里是 `lean_enabled` 的样板落点**。 |
| `agentflow/settings.json:2-7` | **本机配置（不入库）**：本机真值 `lean_bin=_env/lean470/lean-4.7.0-windows/bin`、`mathlib_root=_env/mathlib-pinned2/mathlib4-4.7.0`。开关的默认值要与它共存（今天该文件里没有 `lean_enabled`）。 |
| `agentflow/src/agentflow/toolchain.py:1-53` | **口径（实现层 docstring）**：这一层的唯一职责 = 把"这台机器能做形式化核验吗"变成可读、可判据、三态的读数；第 19-25 行写明"本机路径写在 settings.json 的 `toolchain.*`"。 |
| `agentflow/src/agentflow/toolchain.py:65-69` | **实现**：`__all__` —— 这一层对外只暴露 `CHECKERS` / 四个 ENV 名 / `ENV_PROVER_PATH` / `ENV_VERIFIER_BINS` / `VERSION_COMMANDS` / `resolve_checker` / `probe_checkers` / `mathlib_state` / `toolchain_report`。 |
| `agentflow/src/agentflow/toolchain.py:72-78` | **口径**：`VERSION_COMMANDS`（三个检查器的报版本命令）+ `CHECKERS = ("lean","coqc","isabelle")`，注释逐字写"Lean 是本项目形式化路径的唯一后端，排第一"。 |
| `agentflow/src/agentflow/toolchain.py:81-95` | **口径**：`ENV_LEAN_BIN` / `ENV_COQ_BIN` / `ENV_ISABELLE_BIN` / `ENV_PROVER_PATH` / `ENV_VERIFIER_BINS` / `SETTING_KEYS`（检查器名 → `settings.json` 的 `toolchain` 键）。 |
| `agentflow/src/agentflow/toolchain.py:120-185` | **实现**：`resolve_checker(name)` —— 一个检查器"在哪、从哪一档找到的、有没有配置问题"，返回 `{name, path, source, problem, looked}`。四档顺序：环境变量 > 设置文件 > `AGENTFLOW_PROVER_PATH` > `PATH`。`source` 取值 `explicit`/`explicit_dir`/`settings`/`settings_dir`/`prover_path`/`path`/`""`。 |
| `agentflow/src/agentflow/toolchain.py:188-197` | **实现**：`_version_of()` —— 真跑一次报版本命令（10 秒超时）。 |
| `agentflow/src/agentflow/toolchain.py:200-235` | **实现**：`probe_checkers()` —— 三态探测，返回 `{checked, available, available_names, probe_errors, reason, looked_in, sources}`。**这是 `detect_verifier` 的唯一实现**。 |
| `agentflow/src/agentflow/toolchain.py:238-265` | **实现**：`lean_path_for(root)` —— Mathlib 工程根 → 编译 `import Mathlib` 需要的 `LEAN_PATH`（认 `.lake/build/lib` 与 `.lake/build/lib/lean` 两种布局 + 各依赖包）。 |
| `agentflow/src/agentflow/toolchain.py:276-279` | **实现**：`_IMPORT_MATHLIB_PROBE_SRC` —— 真编译探针的源码（`import Mathlib` + `norm_num`），以常量的形式写在模块里。 |
| `agentflow/src/agentflow/toolchain.py:282-304` | **实现**：`_import_mathlib_probe(root)` —— **真编译一次 `import Mathlib`**（`lru_cache(maxsize=4)` 按根缓存，超时 180 秒，经 `formalgw.check_lean`），返回 `{checked, verified, status, reason, missing_imports, elapsed_sec, exit_code}`。 |
| `agentflow/src/agentflow/toolchain.py:307-323` | **实现**：`_measured_mathlib_verdict(probe)` —— 把探针读数变成三态人话（可用 / 不可用 / 没查成）。 |
| `agentflow/src/agentflow/toolchain.py:326-380` | **实现**：`mathlib_state(env)` —— Mathlib 那一轴的三态读数：工程根、commit/tag 与钉住的是否一致（`pinned_match`）、umbrella `.olean` 在不在、`lean_path`、文件面读数 `import_mathlib`、实测读数 `import_mathlib_measured` 与 `import_mathlib_probe`。 |
| `agentflow/src/agentflow/toolchain.py:399-420` | **实现**：`toolchain_report(env)` —— 给 `agentflow doctor` 的总读数：`{model, provers, lean_ready, lean_path, lean_version, mathlib, can_do_formal}`。**`can_do_formal` 的唯一定义就在这里**。 |
| `agentflow/src/agentflow/cli.py:1869` / `:1902-1907` | **实现（读数出口）**：`doctor` 子命令调 `toolchain_report()`；退出码 `2`=探测没做成、`0`=key 齐且 `can_do_formal`、`1`=查过了有缺。**开关若只改 `can_do_formal` 会连带改 doctor 的退出码语义**。 |
| `agentflow/src/agentflow/cli.py:1883-1901` | **实现（人话渲染）**：把检查器一行、Mathlib 两行（文件面 + 实测）打给人看。 |
| `agentflow/src/agentflow/webui/readers.py:959-983` | **实现**：`machine_face()` = `toolchain_report()` 的顶层键逐字保留（含 `can_do_formal`）+ 设置三段；坏值时进 `problems`。 |
| `agentflow/src/agentflow/webui/readers.py:1215-1219` | **实现（读模型契约）**：`machine_face()` 的字段声明，含 `("can_do_formal", "boolean | null")`。 |
| `agentflow/src/agentflow/formalgw.py:99-116` | **实现**：`formalgw` 的 `__all__`，其中与工具链读数直接相关的有 `PINNED_LEAN_*` / `PINNED_MATHLIB_*` / `MATHLIB_REV_STAMP` / `ENV_MATHLIB_ROOT` / `find_mathlib_root` / `mathlib_revision` / `toolchain_main`。 |
| `agentflow/src/agentflow/formalgw.py:974` | **实现**：`formalgw` 自己拼 `LEAN_PATH` 时调回 `TC.lean_path_for(root)`（口径只有一处）。 |
| `agentflow/src/agentflow/README.md:396-405` | **文档**：`settings.example.json` 与 `docs/FORMAL-TOOLCHAIN.md` 的目录说明（"改哪台机器就换那一份"）。 |

**关于"被投影进提示词的 `TOOLCHAIN_FACTS` 之类的常量叫什么"**：它不是常量，是**函数**，
名字与落点见第 5 组 —— `toolchain_facts_text()`（`agent_prompts.py:1825`）与
`toolchain_formal_text()`（`agent_prompts.py:1889`）；段名常量是
`promptkit.SECTION_ORDERS["TOOLCHAIN_FACTS"] = 9000` 与 `["TOOLCHAIN_FORMAL"] = 9010`。

---

## 2. 工具面

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/tools/verify_tools.py:1-32` | **口径（模块 docstring）**：本模块 = "E 的工具：数值实验与形式化验证"；写明"算对了"与"证完了"是天壤之别，以及 `formal.check` 无后端时必须返回 `checked=False, reason="no_backend"`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:49` | **口径（权限面）**：`_ROLES = ("E", "F", "G", "H")` —— 本模块声明的角色；注释写明 A/B/C/D 不在其中。 |
| `agentflow/src/agentflow/tools/verify_tools.py:54` | **口径（权限面）**：`_ROLES_WRITE = ("E", "F", "G")` —— **写工具**（跑子进程 + 写 `experiments` 表）单独声明；H 只读、拿不到它。 |
| `agentflow/src/agentflow/tools/verify_tools.py:56-61` | **口径（注释）**：形式化检查器的候选与查找口径只有一处定义（`agentflow.toolchain`），本模块**只转发**；含"两处口径独立 ⇒ 形式化那一条腿会静默降级"的真机读数。 |
| `agentflow/src/agentflow/tools/verify_tools.py:63-76` | **判据（导入期断言）**：`_EVIDENCE_ORDER = ("heuristic","cross_check","proof")`，`assert set(_EVIDENCE_ORDER) == set(S.EVIDENCE_KINDS)`；`_TOP_EVIDENCE = _EVIDENCE_ORDER[-1]`。**这是"proof 是最强档"在本模块的唯一落点**。 |
| `agentflow/src/agentflow/tools/verify_tools.py:79-93` | **实现**：`code_hash(path)` —— 脚本内容 sha256 前 16 位（可复现性的绑定）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:96-121` | **实现**：`detect_verifier()` —— **转发**到 `toolchain.probe_checkers()`，返回 `{available, available_names, checked, reason, probe_errors}`（+ `looked_in` / `sources`）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:124-133` | **实现**：`check_formal(claim, *, script_path, source, checker_name, imports, timeout_sec, root) -> ToolResult` —— 转发到 `formalgw.check_lean`。**这是形式化检查的唯一函数入口**。 |
| `agentflow/src/agentflow/tools/verify_tools.py:136-316` | **口径（长 docstring）**：参数名为什么是 `checker_name`、三态词表（`verified` 才 `verified=True`；`timeout`/`import_unavailable`/`no_backend`/`tool_crashed`/`source_unreadable` 都是"没查成"）、`E-3`/`E-4`/`P-8` 三条接线的理由、副作用与**审批面**（`check_formal` = `read`+`external="exec"` ⇒ 需要审批）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:317-366` | **实现**：无后端两支 —— `tool_crashed`（探测没做成）与 `no_backend`（探测完成确实没有）；两支都是 `checked=False, verified=None, exit_code=None`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:367-384` | **实现**：既无 `source` 又无 `script_path` ⇒ `no_script`（"没做验证"）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:389` | **实现**：`from ..formalgw import STATUSES, check_lean`（惰性导入，避免与 `formalgw` 反向 import 成环）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:426-435` | **实现**：真调用 `check_lean(src, name=nm, imports=tuple(imports or ()), timeout_sec=…, source_path=path_arg)`。**`imports` 默认注入空**。 |
| `agentflow/src/agentflow/tools/verify_tools.py:441-450` | **实现（失败收口）**：`param_error`（参数不合法）/ `check_failed`（桥接层抛异常）—— 两条都带 `checker_name`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:463-506` | **实现（返回形状）**：ok 分支九键 `{checked, verified, claim, reason, detail, verifier_output, missing_imports, verifier_status, exit_code}`；meta 里另有 `status` / `checked_source` / `axioms` / `sorry_count` / `decl_matches` / `declared_in_source` / `source_sha256` / `source_path` / `ran` / `backend_status` / `evidence_kind`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:515-618` | **实现**：`evidence_for()` —— 纯查询，三态（"没查" vs "查了没有"），`proved` 没查时是 `None`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:620-655` | **实现**：`list_experiments()` —— 纯查询。 |
| `agentflow/src/agentflow/tools/verify_tools.py:696-707` | **声明（ToolSpec）**：`verify.detect_verifier`，`side_effect="read"`，**`roles=_ROLES`（E/F/G/H）**，`returns="{'checked','available','available_names','reason','probe_errors'}"`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:716-805` | **声明（ToolSpec）**：`verify.check_formal`，摘要逐字含"只有 verified 才给 proof 级证据"；参数 `{claim(必填), script_path, source, checker_name, imports, timeout_sec}`；`side_effect="read"`，**`roles=_ROLES_WRITE`（E/F/G，H 拿不到）**，`external="exec"`（⇒ 需要审批）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:826-889` | **声明（ToolSpec）**：`verify.run_experiment`，摘要逐字含"脚本自报 evidence_kind='proof' 会被降级为 cross_check；method='formal' 时改走检查器（.lean 产物），只有检查器 verified 才登记 proof"；参数含 `run_name` / `imports`（仅 formal）；`side_effect="write_local"` + `external="exec"`。 |
| `agentflow/src/agentflow/tools/verify_tools.py:909-...` | **实现**：`_verify_run_experiment(...)` 的工具体（含 `imports` / `certificate` / `search_bound` 的透传）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:1003-1113` | **实现/声明**：`_ROLES_V = ("V",)` 与 V 的三件工具（`verify.verify_proof` / `list_verifications` / `read_proof`）—— **这是"自然语言逐行审阅证明"的现成落点**（见第 10 组）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:1118-1128` | **实现**：`_TOOL_FUNCTIONS` 装配清单（9 件工具，含 `_verify_check_formal` 的注入名 `base`）。 |
| `agentflow/src/agentflow/tools/verify_tools.py:1131-1312` | **实现**：`register(registry, store, root)` —— 装配 E/F/G/H 可见的实验工具；`store=None` 时照样注册但调用返回 `not_wired`（FC-08）。 |
| `agentflow/src/agentflow/tools/__init__.py:70` | **口径（注释）**：`E —— 数值实验与形式化验证（产出证据，且必须标注证据等级）`。 |

**谁拿得到它们（逐条结论）**：
- `verify.detect_verifier` → **E / F / G / H**（`_ROLES`，`verify_tools.py:704`）。
- `verify.check_formal` → **E / F / G**（`_ROLES_WRITE`，`verify_tools.py:776`）；H 明确拿不到
  （`verify_tools.py:769-774` 的注释记了这次收窄与"H 的工具面因此从 23 条变 22 条"）。
- `verify.run_experiment` → **E / F / G**（同 `_ROLES_WRITE`）。
- V 的三件（`verify.verify_proof` / `list_verifications` / `read_proof`）→ **只有 V**。

---

## 3. 角色与动作声明

### 3.1 `specs/e.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/specs/e.py:1-8` | **口径（docstring）**：本文件是权限面的真身，`capabilities.py` 从它派生三张表；它在 `.noai-paths` 里受保护。 |
| `agentflow/src/agentflow/specs/e.py:31-71` | **声明（动作）**：`E.run_experiment` —— 参数含 `method`（枚举自 `S.EXPERIMENT_METHODS`）、`name`（"仅 method='formal'：要核对的声明名"）、`imports`（"仅 method='formal'：这次检查要加载的库"）；`side_effect="write_local"` + `external="exec"`。 |
| `agentflow/src/agentflow/specs/e.py:36-45` | **口径（注释）**：`T0-13` —— formal 的两个参数（`name`/`imports`）为什么必须声明（否则"M 派不出形式化"，P6/P10 要的是后者）。 |
| `agentflow/src/agentflow/specs/e.py:80-84` | **声明（动作）**：`E.check_formal` —— 摘要逐字"转发到形式化检查器；没有后端时如实回答『没做』。必须给 `source`（Lean 源码全文）或 `script_path`（工作区里的 .lean 文件）：两者都不给 ⇒ `no_script`（没查成，不算核过）"。 |
| `agentflow/src/agentflow/specs/e.py:97-101` | **声明（参数）**：`{claim(必填), script_path("工作区里的 .lean 文件"), source("Lean 源码全文"), name, imports, timeout_sec}`。 |
| `agentflow/src/agentflow/specs/e.py:103-126` | **口径/声明**：为什么 `E.check_formal` 是 `side_effect="read"` + `external="exec"`（三条判据逐条从代码读出）；第 122-124 行登记代价：H 不再拥有它。 |
| `agentflow/src/agentflow/specs/e.py:165` | **声明（职责）**：`duty="数值实验与形式化验证：把一条断言变成可复现的实验或可检查的形式化代码"`。 |
| `agentflow/src/agentflow/specs/e.py:168` | **声明（边界）**：`"脚本自报的 proof 级证据一律降级为 cross_check：让被判定的对象自己当判官是最容易被绕过的地方。"` |
| `agentflow/src/agentflow/specs/e.py:169` | **声明（边界）**：`"实验失败、检查器不存在、代码跑不过，都要如实落 failed 或 unknown，不许补写结论。"` |
| `agentflow/src/agentflow/specs/e.py:173` | **声明（政策）**：`"形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。"` |
| `agentflow/src/agentflow/specs/e.py:177` | **声明（政策，整条）**：Mathlib 与写法口径 —— `check_formal` 的 `imports` 默认不注入任何库；要用 Mathlib 得显式传 `imports: ['Mathlib']`；**"这台机器上 Mathlib 到底能不能用看下面 TOOLCHAIN_FACTS 那一段的现算读数"**；还含"内联源码同时要落进工作区（`fs.write` 到 `code/lean/<名字>.lean`）"与"读数说 Mathlib 不可用时的写法口径 ①②③④"（`decide` 的局限、不要 sorry/admit、失败读检查器原话那一行、多声明要给 `checker_name`）。 |
| `agentflow/src/agentflow/specs/e.py:178` | **声明（政策）**：`"**试错要有代价意识**"` —— 失败档位 `compile_error`/`uses_sorry`/`extra_axioms`/`decl_mismatch` 逐个点名。 |
| `agentflow/src/agentflow/specs/e.py:182` | **声明（signature_error）**：`"把跑不过的代码块当成通过。"` |
| `agentflow/src/agentflow/specs/e.py:183` | **声明（deliverable）**：`"experiments 行与它们的证据字段（数值、检查器输出、复现命令）。"` |
| `agentflow/src/agentflow/specs/e.py:187` | **声明（stance）**：`"检查器跑不过时说跑不过；检查器不存在时说不知道。你的证据链是别人敢下结论的地基。"` |
| `agentflow/src/agentflow/specs/e.py:205` | **声明（local_notes['敢创新']）**：`'构造反例、设计新实验都算创新；形式化只认检查器真的说过的话。'` |
| `agentflow/src/agentflow/specs/e.py:207` | **声明（local_notes['眼睛']）**：`'读脚本、数据、检查器输出：证据要能原样重跑。'` |
| `agentflow/src/agentflow/specs/e.py:216` | **声明（写集）**：`write_set=frozenset(('experiments',))`。 |
| `agentflow/src/agentflow/specs/e.py:217` | **声明（实现类）**：`class_path='agentflow.agent_e:AgentE'`。 |

### 3.2 `specs/h.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/specs/h.py:110` | **声明（边界）**：`"…发现问题落 findings，然后按问题性质去要：引文对不上就找 A 核实原文、**断言能否形式化就找 E**…"` |
| `agentflow/src/agentflow/specs/h.py:114` | **声明（边界，采信规则 §16 P2）**：`"你采信一条命题的标准只有两条 —— 正文与 B 的台账逐字一致…，以及 E 给过背书（experiments 行 evidence_kind=proof）。两条都不在，你只能说「这条我采信不了」，不许自己读一遍证明就判它对。"` ← **这条把 H 的采信口径硬绑在 `proof` 上**。 |
| `agentflow/src/agentflow/specs/h.py:142` | **声明（local_notes['手']）**：`'…发现问题落 findings，再按性质找 A（引文）/ E（形式化）核实或请 G 修订。'` |

### 3.3 `specs/m.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/specs/m.py:57` | **声明（政策）**：`"一批同类的活（例如几十篇文献的阅读消化、**多条断言的逐条形式化**）要用 `conductor.summon_many` 一次派出去"`。 |
| `agentflow/src/agentflow/specs/m.py:62` | **声明（政策，整条）**：`"**形式化这条路：一次只核你给的那份源码**…`E.check_formal` 只给裁决、不落库，`E.run_experiment(method='formal')` 才落 proof 行…**Mathlib 能不能用，只从 TOOLCHAIN_FACTS 的现算读数来**（P-05）…读数说不可用…\u21d2 按不可用办，并如实记「未核到」——不许宣称可用。"` |
| `agentflow/src/agentflow/specs/m.py:63` | **声明（政策）**：`"**长文本不要内联进步子里的 JSON**…把整段构造脚本、**整段 Lean 源码**、整段命题原文塞进 `params` 里…"` |
| `agentflow/src/agentflow/specs/m.py:68` | **声明（政策）**：叫停口径里点名 `"（实验脚本、检查器进程）"`；并含"③有没有一条**判决性证据**（proof 级实验，或带反例的 refutes）"。 |
| `agentflow/src/agentflow/specs/m.py:70` | **声明（政策）**：研究链八环里第③环"算或造"含 `reviewed_proof_rows`；点名"数值 / 形式化 E、证明 F、审过 V、正式审查 H"是签位的人。 |
| `agentflow/src/agentflow/specs/m.py:76` | **声明（政策）**：受控档位表逐字列出 `proof_experiment_rows` 与 `reviewed_proof_rows`（收工门认识的档）。 |
| `agentflow/src/agentflow/specs/m.py:77` | **声明（政策）**：`"形式化要用 `proof_experiment_rows`（`method=formal` **且** `evidence_kind=proof`）—— 形式化没跑成（`compile_error`/`uses_sorry`）时这一档没有读数"`。 |

### 3.4 `specs/g.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/specs/g.py:141` | **声明（职责）**：`duty="论文撰写：把 D/F/E 的结论汇编成可审校的稿件…"` |
| `agentflow/src/agentflow/specs/g.py:144` | **声明（边界）**：`"`cross_check` 那一类结论的免责声明（「数值交叉验证，不构成证明」）由框架自动附上…你要写对的是 `evidence_kind`"`。 |
| `agentflow/src/agentflow/specs/g.py:146` | **声明（边界）**：`"发现证据不足时要回去要：文献原文找 A、**形式化找 E**、论证与实验找 D/F…"` |
| `agentflow/src/agentflow/specs/g.py:150` | **声明（政策）**：引到 `result=inconclusive`（含"编译失败"）的实验时必须写成"没得出结论"。 |

> **`specs/v.py`（额外发现，任务未点名但同族）**：`:52-57`（V 的 `verify_proof` 声明为
> `side_effect="read"`，台账是文件不是表）、`:63-72`（`proof_text` 参数与
> `v-NNNN / verdict / findings / proof_sha256` 返回）、`:82-89`（`read_proof`）。
> **这是"自然语言逐行审阅证明"这条腿的现成实现**。

### 3.5 `capabilities.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/capabilities.py:93` | **口径（注释）**：写集注释举例里点名"它跑调用方给的脚本，同时又写 experiments 表"。 |
| `agentflow/src/agentflow/capabilities.py:124` | **口径（注释）**：`"（工具层 `verify.check_formal` 声明 `read`、能力层 `E.check_formal`…）"` —— 两层 risk 轴对账的说明。 |
| `agentflow/src/agentflow/capabilities.py:171` | **口径（注释）**：V 的三条动作与工具名逐一对应（`verify.verify_proof` / `verify.list_verifications` / `verify.read_proof`）。 |
| `agentflow/src/agentflow/capabilities.py:341` | **口径（注释）**：`docs/PROPOSALS.md` 的 P-13 §10 第 3 条实测 —— 工具层/能力层两层声明的分歧就发生在这里。 |
| `agentflow/src/agentflow/capabilities.py:790-798` | **判据（登记表）**：`PARAM_SEAMS` 里两条与形式化直接相关 —— `("E","run_experiment")` 缺 `run_name`；**`("E","check_formal")` 缺 `checker_name`**（"动作面没声明 ⇒ 编排层选不了检查器"）。 |
| `agentflow/src/agentflow/capabilities.py:939-940` | **口径（注释）**：`agent_e.py AgentE` 的动作清单（`run_experiment / check_formal / evidence_for / list_experiments / run_script_experiment`）。 |
| `agentflow/src/agentflow/capabilities.py:993` | **口径（注释）**：`E.check_formal` 的 `name` 在实现上被接受、在工具层却会吞参数（撞名的登记）。 |
| `agentflow/src/agentflow/capabilities.py:1271` | **实现**：`WRITE_SETS: dict[str, frozenset[str]] = _specs.write_sets()` —— 写集**派生自 `specs/*.py`**（不是在这里另写一份）。 |
| `agentflow/src/agentflow/capabilities.py:1357` | **口径（注释）**：`"断言能不能形式化就找 E"`。 |
| `agentflow/src/agentflow/capabilities.py:2231-2258` | **判据（导入期断言）**：两层声明对账 —— error 级无条件断言（"能力层低估了风险轴"= 缺陷）；warning 级默认只报，`STRICT_DECLARATIONS=True` 时才断言。注释逐字提到 `verify.check_formal` 工具层 `read` / 能力层 `network` 的实测分歧。 |
| `agentflow/src/agentflow/capabilities.py:2454-2456` | **口径（注释）**：`C.proof_chain` 是角色级只读方法。 |
| `agentflow/src/agentflow/capabilities.py:2513` | **口径（注释）**：第 7 条 —— 真实树上现有的不一致里点名 `E.check_formal`。 |

### 3.6 `interactions.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/interactions.py:275` | **口径（注释）**：否定标记表的假阳性说明 —— `"numerical output is used as a proof"` 这类句子会命中否定标记，但它们不是对立主张。 |

**没查到/不确定**：`interactions.py` 里**没有**任何要求 `evidence_kind=proof` 或
"检查器 verified"的闸门。它管的是 `check_conflict`（B 的事务内一致性闸门）、
`adjudicate_contradiction`、`admit_search_request` / `admit_reprocess_request`
（I7/I4 配额）。**A–H 调用矩阵的权威定义不在这里**，在 `capabilities.ALLOWED_EDGES`
（`.noai-paths:128` 的理由串自己写着这件事）。

---

## 4. 实现（E 侧）

E 的实现是**包**（`src/agentflow/agent_e/`），不是单文件 `agent_e.py`
（`agent_e.py` 的类路径 `agentflow.agent_e:AgentE` 指向包的 `__init__.py`）。

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/agent_e/__init__.py:59-104` | **口径（docstring）**：形式化路径与计算类路径的分工 —— `method="formal"` 不走那三条规则，它把工作区里的 `.lean` 文件交给检查器；**"这是本模块唯一能产出 `evidence_kind='proof'` 的入口"**；4 条收口规则。 |
| `agentflow/src/agentflow/agent_e/__init__.py:13-16` | **口径**：`Experiment.evidence_kind` 是结构化字段不是注释里的告诫；`method="numeric"` 却写 `evidence_kind="proof"` 在写入那一刻就炸；脚本自报 `proof` 会被降到 `cross_check` 并把这件事记进 `notes`。 |
| `agentflow/src/agentflow/agent_e/_support.py:154-170` | **实现（受控词表）**：`FORMAL_REASONS` 共 15 个取值（`verified` / `compile_error` / `uses_sorry` / `extra_axioms` / `decl_mismatch` / `timeout` / `import_unavailable` / `no_backend` / `tool_crashed` / `source_unreadable` / `no_script` / `param_error` / `path_outside_workspace` / `tool_failed` / `status_unregistered`）。 |
| `agentflow/src/agentflow/agent_e/_support.py:171-183` | **实现**：`_FORMAL_REASON_BY_TOOL_REASON` —— 工具层 reason → 本层受控 reason 的**显式**映射表。 |
| `agentflow/src/agentflow/agent_e/_support.py:184-192` | **判据（导入期断言）**：`formalgw.STATUSES` 必须全部在映射表里（"不许靠透传兜底"）；`_NOT_CHECKED_REASONS` 必须全部在 `FORMAL_REASONS` 里。 |
| `agentflow/src/agentflow/agent_e/_support.py:145-148` | **判据（导入期断言）**：`COMPUTATIONAL_METHODS ∪ {"formal"} == S.EXPERIMENT_METHODS` —— "哪些方法拿不到 proof 必须只有一处定义"。 |
| `agentflow/src/agentflow/agent_e/_support.py:149` | **实现**：`_NO_EVIDENCE_KIND = "heuristic"` —— 检查器没认时落的那一档。 |
| `agentflow/src/agentflow/agent_e/_support.py:258-278` | **实现**：`_DECLARED_NAME_RX` / `_declared_name_note()` / `declared_name_of_notes()` —— "检查器实际检查的是哪条声明"的唯一写法与唯一读法（事后审计 `verify.selfreported_proof` 按它认）。 |
| `agentflow/src/agentflow/agent_e/_support.py:434-455` | **实现**：`_normalize_evidence_kind()` —— 脚本自报 `proof` 且 `method != "formal"` ⇒ 拒绝并降级为 `cross_check`（记 notes）。 |
| `agentflow/src/agentflow/agent_e/_support.py:503-630` | **实现**：`_derive()` —— 由"退出码 + 脚本输出"推导 `result` / `evidence_kind` / `negation_kind`；计算类一律 `_NO_EVIDENCE_KIND`。 |
| `agentflow/src/agentflow/agent_e/_support.py:645-720` | **实现**：`build_experiment()` —— 构造 `S.Experiment` 行；第 676-683 行登记：`evidence_kind="proof"` ⇒ `verifier_output` 必须非空、`verifier_subject_key` 必须非空且等于 `claim_key`（这四格此前不收 ⇒ "E 登记不了一条 proof 级实验"）。 |
| `agentflow/src/agentflow/agent_e/_support.py:745-760` | **实现**：`_result_reason(row)` —— 人话里带 `evidence_kind`。 |
| `agentflow/src/agentflow/agent_e/_support.py:763-775` | **实现**：`_formal_status_suffix(row)` —— 形式化行的人话后缀（检查器原样状态 + 本层受控理由）。 |
| `agentflow/src/agentflow/agent_e/check_formal.py:9-121` | **实现（整个文件）**：`_CheckFormal.check_formal(claim, *, script_path, source, name, imports, timeout_sec)` —— 唯一实现入口。 |
| `agentflow/src/agentflow/agent_e/check_formal.py:20-72` | **口径（docstring）**：无后端必须返回 `checked=False, reason="no_backend"`；与 `verified=False` 是两件事；参数透传史；`reason` 的收口与透传（`G-24①`）；`script_path` 的路径守卫（越界返回 `path_outside_workspace`）。 |
| `agentflow/src/agentflow/agent_e/check_formal.py:80-86` | **实现**：路径守卫 —— 越界 ⇒ `self._formal_refusal(claim, "path_outside_workspace", …)`。 |
| `agentflow/src/agentflow/agent_e/check_formal.py:88-105` | **实现**：调 `VT.check_formal(...)`，含 `checker_name=name`（两套名字之间的**唯一映射点**）与 `root=str(self.workspace_root)`。 |
| `agentflow/src/agentflow/agent_e/check_formal.py:106-121` | **实现**：失败 ⇒ `_formal_refusal(claim, "tool_failed", …)`；成功 ⇒ `reason` 收口 + `verifier_status` 逐字透传。 |
| `agentflow/src/agentflow/agent_e/core.py:17-53` | **实现**：`_mathlib_remedy_note(status, imports, path)` —— "这一次 formal 失败能不能被『忘了传 Mathlib』解释？"三条判据（① 状态是缺库类；② 本机 Mathlib **现算可用**；③ 这一次确实没要它）。 |
| `agentflow/src/agentflow/agent_e/core.py:119-...` | **实现**：`_resolve(rel)` —— 工作区路径守卫（`check_formal` 与 `run_experiment` 共用同一份）。 |
| `agentflow/src/agentflow/agent_e/core.py:279-311` | **实现**：`_record_formal(...)` 的 docstring —— `P-8` 的接线："把一次真实的形式化检查与一行 proof 级实验记录接起来"；`verified` ⇒ `evidence_kind="proof"`；其余一切 ⇒ `inconclusive` + `heuristic`（**刻意不是 `cross_check`**）。 |
| `agentflow/src/agentflow/agent_e/core.py:312-320` | **实现**：`method='formal'` 而产物后缀不是 `.lean` ⇒ 抛 `ExperimentError`（"本方法不会把一段 Python/文本当成 Lean 去核"）。 |
| `agentflow/src/agentflow/agent_e/core.py:322-339` | **实现**：声明名的取得 —— 不拿文件名词干，改从源码认名（`sole_declaration_name`）；0 条或多条 ⇒ 抛 `ExperimentError`。 |
| `agentflow/src/agentflow/agent_e/core.py:341-347` | **实现**：`data = self.check_formal(claim, script_path=rel, name=declared_name, imports=imports, timeout_sec=…)`。 |
| `agentflow/src/agentflow/agent_e/core.py:350-383` | **实现**：`status` / `formal_reason` / `output` / `verified` 的读法；notes 的四段（状态、声明名、脚本+hash+imports、检查器原话）；未通过时追加 `_mathlib_remedy_note`。 |
| `agentflow/src/agentflow/agent_e/core.py:385-414` | **实现**：`E-12` 三态恢复 —— `tri_state ∈ {verified, checked_failed, not_checked}`；`negation_kind` 再分 `not_proved` / `no_local_evidence` / `not_searched_here`。 |
| `agentflow/src/agentflow/agent_e/core.py:415-430` | **实现（关键）**：`derived = {"result": "supports" if verified else "inconclusive", "evidence_kind": "proof" if verified else _NO_EVIDENCE_KIND, ...}`；`observations` 里带 `verifier_status` / `formal_reason` / `checked` / `tri_state` / `missing_imports`。 |
| `agentflow/src/agentflow/agent_e/core.py:431-441` | **实现**：`verifier_subject_key = claim_key if output else ""`；`exit_code = 0 if verified else <检查器真实码> else None`。 |
| `agentflow/src/agentflow/agent_e/core.py:442-460` | **实现**：在 `store.tx("experiments", note="e.run_experiment")` 事务里 `alloc_id("experiment")` + `build_experiment(..., method="formal", verifier_output=output, verifier_subject_key=subject_key, …)` ← **这就是"把检查器结论写成 `evidence_kind=proof`"的落点**。 |
| `agentflow/src/agentflow/agent_e/core.py:480-...` | **实现**：`_formal_refusal(claim, reason, detail)` —— 与 `no_backend` / `no_script` 同形的受控三态 dict。 |
| `agentflow/src/agentflow/agent_e/core.py:563-576` | **实现（模块自检的期望值）**：第 2 条"脚本自报 proof ⇒ 被降级为 cross_check"；第 10 条"形式化路径（`P-8`）：`.lean` 产物真的走检查器那一条 —— 检查器给 `verified` 时登记的行必须是 `evidence_kind='proof'` 且 `verifier_subject_key == claim_key`；否则一行都不许标成 proof。**本机没有 Lean 时这一段的期望值自动降级成『不是 proof』**"。 |
| `agentflow/src/agentflow/agent_e/core.py:728-755` | **实现（自检第 10 条）**：真造 `.lean` 源码跑一遍，按 `r10["evidence_kind"] == "proof"` 分支断言（含 `verifier_subject_key == claim_key`、`verifier_output` 非空、`method == "formal"`）。 |
| `agentflow/src/agentflow/agent_e/core.py:756-764` | **实现（自检第 11 条）**：非 `.lean` 产物当场拒绝、且不留半条记录。 |
| `agentflow/src/agentflow/agent_e/run_experiment.py:10-...` | **实现**：`run_experiment(...)` 主入口（形参含 `name` / `imports`）。 |
| `agentflow/src/agentflow/agent_e/run_experiment.py:37-44` | **口径（docstring）**：形式化路径 —— 产物必须是 `.lean`；只有检查器 `verified` 才登记 `evidence_kind="proof"`。 |
| `agentflow/src/agentflow/agent_e/run_experiment.py:85-95` | **实现**：`certificate`/`search_bound` 只对穷举类有效；**`name`/`imports` 只对 `method='formal'` 有效**（给计算类传它们会被拒，不是静默忽略）。 |
| `agentflow/src/agentflow/agent_e/run_experiment.py:123-135` | **实现**：`if method == "formal": return self._record_formal(...)` ← 形式化与计算类的分叉点。 |
| `agentflow/src/agentflow/agent_e/author_script.py:103` | **口径（docstring）**：`"临时目录里跑，那份文件既不是 `proof_location`、也交不了…"` |
| `agentflow/src/agentflow/agent_g/core.py:215-218` | **口径（注释）**：自检里那行检查器输出**从前写的是 `"Lean4: no goals"`**，那种输出会被 `verify.selfreported_proof` 判成自报 ⇒ 改成 `'<声明名>' does not depend on any axioms` 才是 Lean 真跑过的形态。 |
| `agentflow/src/agentflow/agent_g/core.py:271-283` | **实现**：G 的自检自己造一份最小 `selftest.lean` 当落点，`proof_location="proofs/selftest.lean:1"`。 |

**没查到/不确定**：任务里问的 `src/agentflow/agent_e*.py` 单文件形式**不存在**
（只有 `agent_e/` 包 + 遗留的 `__pycache__/agent_e.cpython-311.pyc`）。上面用的是包内路径。

---

## 5. 提示词（`agent_prompts.py`）

**`PROMPT_VERSION` 当前值 = `"p98"`**（`agentflow/src/agentflow/agent_prompts.py:353`；
上一版 `p97` 的说明在 `:333-352`，`p98` 那一批改的是 `PAPER_PACK` 的文本经济与 `PAPER_08`）。

| 文件:行 | 属于哪一段 | 这里在干什么 |
|---|---|---|
| `agentflow/src/agentflow/agent_prompts.py:166-168` | **版本历史（p69）** | 逐字记录"工具链那一轴拆成『事实』与『怎么写』两段，后者（`TOOLCHAIN_FORMAL`，order 9010）只发给手上真有 `verify.check_formal` 的角色 ⇒ 只换 E / F / G 三格"。 |
| `agentflow/src/agentflow/agent_prompts.py:200-202` | **版本历史（p80）** | `COLLAB_FIVEBITS` 那一段现算自 `evidencebits`（位名 / owner / 凭据表 / 四态 / 等级）。 |
| `agentflow/src/agentflow/agent_prompts.py:218-225` | **版本历史（p84）** | `reviewed_proof_rows` 的三件事（等级现算、两种 0、签位的人）。 |
| `agentflow/src/agentflow/agent_prompts.py:233` | **版本历史（p85）** | "③ 子目标 `closed` 必须有 proof 级证据，数值/穷举支持只能 `supported_not_proved`（FC-22）"。 |
| `agentflow/src/agentflow/agent_prompts.py:284-285` | **版本历史（p90）** | V 的三条动作与 F 的 policy 第 6 条（proof 轮之后用 `summon` 唤起 V 的 `verify_proof`）。 |
| `agentflow/src/agentflow/agent_prompts.py:840` | **`STRUCTURE_NOT_PROMPT` 表** | `("自报的 proof 级证据", "一律降级为 cross_check（`DESIGN-ROLES.md` §2.1）")` —— "这件事由结构保证，不靠提示词"。 |
| `agentflow/src/agentflow/agent_prompts.py:969` | **`FACULTY_LOCAL[("E","敢创新")]`** | `"构造反例、设计新实验都算创新；形式化只认检查器真的说过的话。"`（与 `specs/e.py:205` 必须逐字一致）。 |
| `agentflow/src/agentflow/agent_prompts.py:980` | **`FACULTY_LOCAL[("H","手")]`** | `"数据面写是结构禁止的；发现问题落 findings，再按性质找 A（引文）/ E（形式化）核实或请 G 修订。"`（与 `specs/h.py:142` 逐字一致）。 |
| `agentflow/src/agentflow/agent_prompts.py:1038-1050` | **`EVIDENCE_CONTRACT`（全角色共享，2 块：`EVIDENCE_CONTRACT` / `EVIDENCE_RULES`）** | 证据契约 —— 逐字引文、页码口径、**"证据强度分层：确定性检查（数值、图结构、逐字回验）高于模型判断"**、置信度只能降不能抬、**"结论的强度不得超过引文能支撑的范围：交叉验证不是证明"**。注意：这一段里**没有出现 Lean / Mathlib / proof 字样**（只出现"证明"这个词的否定用法）。 |
| `agentflow/src/agentflow/agent_prompts.py:1112` | **`PAPER_PACK` 三** | `"结论不许强于它挂的证据：证据等级不是 proof 时，断言里不许出现「证明」「定理」「必然」这类词"`。 |
| `agentflow/src/agentflow/agent_prompts.py:1162-1171` | **`PAPER_PACK` 六（"两步形式化"）** | **这就是任务里问的"两步形式化"段**：`"**「核验证明」分两步，两步都要走**（`draft/37` §92 的真机读数，别只走第一步）：1. **裁决**：`E.check_formal` 逐条核工作区里已有的 Lean 源码（声明名可自动认名…；`imports` 默认不注入任何库，**要用 Mathlib 才显式传**；而这台机器上 **Mathlib 能不能用，看上面 TOOLCHAIN_FACTS 那一段的现算读数**）… 2. **落库**：要让一条断言真的升到 `proof` 级…必须派 `E.run_experiment(method='formal', source=…/script_path=…, name=…)` —— 它把 `experiments` 的 proof 行写进去（带 `proof_location` 与检查器原话）… 核不到就说核不到（`import_unavailable` / `decl_mismatch` / `unknown` 都不是证否）。"` |
| `agentflow/src/agentflow/agent_prompts.py:1065-1065`（段起）…`:1171`（段止） | **`PAPER_PACK`（10 块，只发给 M/G/H；`PAPER_PACK_ROLES = ("M","G","H")` 见 `:1063`）** | 整段是论文包交付口径；其中与形式化有关的就是上面那一条（`:1162-1171`）与 `:1112`。 |
| `agentflow/src/agentflow/agent_prompts.py:1365-1367` | **常量（受众判据）** | `_LEAN_TOOL = "verify.check_formal"`；注释逐字"『会写 Lean 源码』这件事的判据 = 手上真有这件工具（从工具面现算，不写死角色名）。实测（2026-10-11）：E / F / G 三家持有"。 |
| `agentflow/src/agentflow/agent_prompts.py:1385-1393` | **实现** | `_writes_lean(role, registry)` —— 决定这个角色拿不拿 `TOOLCHAIN_FORMAL`。 |
| `agentflow/src/agentflow/agent_prompts.py:1784-1787` | **常量** | `_NO_TOOLCHAIN` —— 没读到读数时那一段的诚实说法（"这一次没有读到读数 —— 探测没做，不是「没有检查器」"）。 |
| `agentflow/src/agentflow/agent_prompts.py:1790-1809` | **实现** | `_toolchain_readings()` —— `lru_cache(maxsize=1)`，一次探测两段文案共用；`None` = 探测本身崩了；内部调 `TC.probe_checkers()` 与 `TC.mathlib_state()`。 |
| `agentflow/src/agentflow/agent_prompts.py:1812-1821` | **实现** | `reset_toolchain_readings()` —— 清三层缓存（读数 + 两段文案）。 |
| `agentflow/src/agentflow/agent_prompts.py:1824-1877` | **实现** | `toolchain_facts_text()` —— `TOOLCHAIN_FACTS` 段的正文；输出四行：检查器、Mathlib 工程根、`import Mathlib`（文件面）、`Mathlib 实测（真编译一次）`。**这就是投影进提示词的"工具链事实"**。 |
| `agentflow/src/agentflow/agent_prompts.py:1880-1885` | **常量** | `_NO_TOOLCHAIN_FORMAL` —— `TOOLCHAIN_FORMAL` 没拿到读数时的最保守说法（"写不 import 任何库的自足文件…别在源码里 import Mathlib"）。 |
| `agentflow/src/agentflow/agent_prompts.py:1888-1947` | **实现** | `toolchain_formal_text()` —— `TOOLCHAIN_FORMAL` 段的正文，四档分支：探测没做成 / 没有可用检查器（**"本环境产不出 proof 级证据"**）/ 找不到 Mathlib 工程根（写自足文件）/ Mathlib 可用（显式传 `imports: ['Mathlib']`）/ Mathlib 不可用 / 那一轴没查成。 |
| `agentflow/src/agentflow/agent_prompts.py:2106-2114` | **实现（装配入口）** | `role_prompt_registry(role, *, registry, …, toolchain_facts="", toolchain_formal="", …)` —— 两段文案**由调用方传**（机器相关，不渲染进基础提示词）。 |
| `agentflow/src/agentflow/agent_prompts.py:2299-2308` | **实现（段注册）** | `reg.section(Section("TOOLCHAIN_FACTS", SECTION_ORDERS["TOOLCHAIN_FACTS"], (toolchain_facts or "").strip() or _NO_TOOLCHAIN))`（**全角色**）；随后 `if _writes_lean(role, registry):` 注册 `TOOLCHAIN_FORMAL`（**只发给持有者**）。 |
| `agentflow/src/agentflow/agent_prompts.py:2309-2314` | **实现** | `WORKSPACE_FACTS` 段（含 `SCHEMA_VERSION` / 表名 / 提示词版本）。 |
| `agentflow/src/agentflow/promptkit.py:81` | **实现（审计预算）** | `"PAPER_PACK": 3100`。 |
| `agentflow/src/agentflow/promptkit.py:144` | **实现（段序）** | `"TOOLCHAIN_FACTS": 9000`。 |
| `agentflow/src/agentflow/promptkit.py:147` | **实现（段序）** | `"TOOLCHAIN_FORMAL": 9010`。 |
| `agentflow/src/agentflow/promptkit.py:139-147` | **口径（注释）** | "后者由调用方传进来（机器相关）"的理由。 |
| `agentflow/src/agentflow/agent_loop.py:2764-2770` | **实现（接线）** | 装配时把 `AP.toolchain_facts_text()` 与 `AP.toolchain_formal_text()` 传进 `role_prompt_registry`；注释逐字记着 T1 第 3 趟"6 次 `check_formal` 花在 `import Mathlib`"的事故。 |
| `agentflow/src/agentflow/agent_loop.py:374` / `:418` / `:2001` | **口径（注释）** | 三处把"Lean 源码"当例子：主题字段不该变的例子；读数一路 `reason=compile_error`；"换一行 Lean"不算换做法。 |
| `agentflow/src/agentflow/agent_loop.py:2765-2766` | **口径（注释）** | "E 在 T1 第 3 趟把 6 次 `check_formal` 花在 `import Mathlib` 上，而框架早就知道本机没装 Mathlib —— 事实必须进模型看得见的地方。" |

**`TOOLCHAIN_FACTS` / `TOOLCHAIN_FORMAL` 是不是"常量"**：**不是**。它们是**函数**
（`toolchain_facts_text` / `toolchain_formal_text`），段名才是常量
（`SECTION_ORDERS["TOOLCHAIN_FACTS"] = 9000`、`["TOOLCHAIN_FORMAL"] = 9010`）。
`PROMPT_VERSION` 是常量（`"p98"`）。

**顺带（不在 `agent_prompts.py`，但同属"提示词"）**：
`agentflow/src/agentflow/runflow.py:182-187` 定义了另一套提示词版本
`PROMPT_VERSIONS = ("v1", "v2-lean")`，`:211-224` 是 `v2-lean` 的正文
（"给出一个 ```lean4 代码块…①自包含，只用 Lean 4 核心语法，**不要 import Mathlib 或任何第三方库**…"）。
**它与 `PROMPT_VERSION` 是两件不同的东西**（一个是角色提示词版本，一个是
`agentflow run` 这条流程的问答模板版本）。

---

## 6. 口径与门

### 6.1 `schema.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/schema.py:27` | **口径（常量）**：`SCHEMA_VERSION = 2`。 |
| `agentflow/src/agentflow/schema.py:936-941` | **口径（受控词表）**：`EXPERIMENT_METHODS = ("numeric", "symbolic", "exhaustive_search", "formal")`，注释逐字"`formal` —— 交给证明检查器（Lean/Coq/…）核验"。 |
| `agentflow/src/agentflow/schema.py:943-953` | **口径（受控词表，核心）**：`EVIDENCE_KINDS = ("proof", "cross_check", "heuristic")`；注释逐字"`proof` —— 由形式化检查器核验过的证明（**只有 `method="formal"` 才可能拿到**）"。 |
| `agentflow/src/agentflow/schema.py:955-956` | **口径**：`EXPERIMENT_RESULTS = ("supports", "refutes", "inconclusive")`。 |
| `agentflow/src/agentflow/schema.py:958-967` | **口径**：`NEGATION_KINDS`（四档，`not_proved` = "数值/穷举支持，但没有证明"）。 |
| `agentflow/src/agentflow/schema.py:969-974` / `:987` / `:989-991` | **口径**：`ATTACK_STATUSES` 含 `supported_not_proved`（"子目标都有数值支持，但没有任何形式化证明"）；`ATTACK_TERMINAL_STATUSES`；`SUBGOAL_STATUSES` 含 `supported_not_proved`。 |
| `agentflow/src/agentflow/schema.py:1239-1240` | **口径（字段）**：`verifier_output: str = ""` —— "形式化检查器的原始输出。`evidence_kind="proof"` 时必须非空。" |
| `agentflow/src/agentflow/schema.py:1241-1247` | **口径（字段）**：`verifier_subject_key: str = ""` —— "检查器输出管的是哪个命题"（防"把 A 命题的输出贴到 B 命题的行上"）。 |
| `agentflow/src/agentflow/schema.py:1248-1256` | **口径（字段）**：`certificate` / `search_bound`（穷举类，另一条证据腿）。 |
| `agentflow/src/agentflow/schema.py:1277-1283` | **判据（硬约束 1）**：`method != "formal"` 而 `evidence_kind == "proof"` ⇒ 当场抛 —— "计算类方法永远拿不到 proof 等级（FC-22 的机械落地）"。 |
| `agentflow/src/agentflow/schema.py:1284-1289` | **判据（硬约束 2）**：`evidence_kind == "proof"` 而 `verifier_output` 为空 ⇒ 抛。 |
| `agentflow/src/agentflow/schema.py:1290-1306` | **判据（硬约束 2b）**：`evidence_kind == "proof"` 而 `verifier_subject_key` 为空 ⇒ 抛；`verifier_subject_key != claim_key` ⇒ 抛（"验证工具必须与上下文绑定"）。 |
| `agentflow/src/agentflow/schema.py:1307-...` | **判据（硬约束 2c/2d）**：穷举类必须给 `certificate` 与 `search_bound`。 |
| `agentflow/src/agentflow/schema.py:1586-1587` | **判据（`Document.claims`）**：每条 claim 的 `evidence_kind` 必须在 `EVIDENCE_KINDS` 里。 |
| `agentflow/src/agentflow/schema.py:1811` / `:1847-1848` | **判据（`Statement` 侧）**：`evidence_kind` 复用 `EVIDENCE_KINDS`（proof / cross_check / heuristic）并做受控词表校验。 |
| `agentflow/src/agentflow/schema.py:2589-2600` | **口径（常量）**：`EVAL_REQUIRED_FIELDS`（7 个必填口径字段）。**注意：这一组里没有与 proof/formal 直接相关的字段名**（属"评测口径"那一类，`FC-24`）。 |
| `agentflow/src/agentflow/schema.py:2601-2690` | **实现**：`EvalResult`（`k` 必填、`value` 必须是 0..1 比率）。 |
| `agentflow/src/agentflow/schema.py:2849-2868` | **实现**：`TABLES` 里 `concepts` 已删（S1r 并表，`SCHEMA_VERSION=2`）；`eval_results` 一行的注册形态。 |

### 6.2 `closing.py`（收工门）

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/closing.py:18` | **口径（门表）**：`\| `load_bearing` \| 承重结论（正文里 `evidence_kind="proof"` 的断言）必须有 T3（形式化）或已降档 \|` ← **题面问的"哪一格会因为缺 proof 级证据而红"就是这一格**。 |
| `agentflow/src/agentflow/closing.py:21` | **口径（门表）**：`substance` —— "`documents`/`relations`/`experiments`/`review_findings`/`statements` 至少一张非空"。**这一格不直接要求 proof**，但它含 `experiments` 表。 |
| `agentflow/src/agentflow/closing.py:47-53` | **口径（门清单）**：收工门八格的名单 `(… "anchor", "contradictions", "load_bearing", "report_shape", "user_pending", "substance")`（全文见该处）。 |
| `agentflow/src/agentflow/closing.py:75-93` | **口径（档位说明）**：`:91` `"proof_experiment_rows": "台账里的 proof 级形式化实验行数（experiments 里…）"`；`:93` `"reviewed_proof_rows": "**我方**走完「有证明过程 + 审过」的命题行数"`。 |
| `agentflow/src/agentflow/closing.py:144` / `:207` / `:325` / `:738` / `:761` | **口径/实现**：验收档位的收口 —— `:761` `if kinds & {"reviewed_proof_rows", "counterexample_or_proof_rows"}:`（"算或造"那一环的口径分支）。 |
| `agentflow/src/agentflow/closing.py:583` | **口径（注释）**：形式化那一支（`method="formal"`）走检查器输出的口子 ⇒ `evidence_kind="proof"`。 |
| `agentflow/src/agentflow/closing.py:757` | **口径（注释）**：结论 + 界/证书（形式化那一支给出 `verifier_output`）。 |
| `agentflow/src/agentflow/closing.py:979` | **实现**：`if kind == "proof_experiment_rows":` 的读数分支。 |
| `agentflow/src/agentflow/closing.py:1422-1467` | **实现**：`if kind == "reviewed_proof_rows":` —— 五元位派生等级（`pre_theorem`/`theorem`）；等级**一律现算**（`bits_from_row` ⇒ `derive_grade`），不读盘上那份；引用命题（`origin=external_lit`）不算。 |
| `agentflow/src/agentflow/closing.py:1504` / `:1514` | **实现/口径**：`numeric_experiment_rows` 的判据（结论 + 界/证书；形式化那一支看 `verifier_output`）。 |
| `agentflow/src/agentflow/closing.py:2032` | **口径（注释）**：门替没写进表里的档说话（含 `reviewed_proof_rows` / `proof_experiment_rows`）。 |
| `agentflow/src/agentflow/closing.py:2278-2280` | **口径（注释）**：`numeric_experiment_rows` 的口径变更史。 |
| `agentflow/src/agentflow/closing.py:2307-2338` | **口径（`MUST_T3_CONDITIONS` 与缺口登记）**：`:2312-2314` 四条"什么时候必须上 T3"，第①条逐字"`documents.claims[].evidence_kind == "proof"` 的断言必须引到一条 T3 实验"；`:2330-2338` **`MUST_T3_GAP_NOTE`** —— "statements 表没有指向 experiments 的字段 ⇒ ②④今天只能数（承重命题几条 / 降档几条），判不了逐条有没有 T3 背书。补法…要动 schema.py，留给人裁"。← **这一条是"要真正解耦 proof 必须改 schema"的现成证据**。 |
| `agentflow/src/agentflow/closing.py:2987` / `:3134` | **口径（门的问题表）**：`我们自己的证明有洞 | contradiction_own_hole | D 给可挽救性评估，E 补 T3，或如实降档`。 |
| `agentflow/src/agentflow/closing.py:3161-3165` | **实现（`_has_t3`）**：`return (method == "formal" and evidence_kind == "proof" and verifier_output 非空)` ← **T3 的机械形态，这里是唯一实现**。 |
| `agentflow/src/agentflow/closing.py:3168-3241` | **实现（`_check_load_bearing`）**：`:3180-3182` 无 store ⇒ `unknown`；`:3196-3197` 只数 `evidence_kind == "proof"` 的 claim；`:3200-3205` 每条承重 claim 必须有引到的 T3 实验（否则进 `bad`）；`:3206-3220` 命题台账那一半（`active` + proof 级 + 有下游）；`:3231-3240` 有 `bad` ⇒ `status["load_bearing"] = "fail"` + `Finding("load_bearing","load_bearing_without_t3","blocker", …)`。 |
| `agentflow/src/agentflow/closing.py:3478-3527` | **实现（`_check_substance`）**：五张表全 0 ⇒ `fail`（`no_substantive_output`，blocker）；有表读不到 ⇒ `unknown`。**这一格不要求 proof**。 |
| `agentflow/src/agentflow/closing.py:3718-3725` | **实现**：八格的分发点（`elif name == "load_bearing": … elif name == "substance":`）。 |

**结论（题面问的那一问）**：会因为缺 proof 级证据而红的，**主要是 `load_bearing` 那一格**
（`closing.py:3168-3241`）；`substance` **不会**（它只看五张表有没有非空的，
proof 只是其中一张表的一种行）。另有一处是**验收档位**（`M` 的
`ACCEPTANCE-CHECKS.json` 里的 `proof_experiment_rows` / `reviewed_proof_rows`）——
它不是收工门的八格，而是 M 自己的验收表口径（`specs/m.py:70-77`）。

### 6.3 `verify.py`（一致性审计）

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/verify.py:37` | **实现（依赖）**：`from .formalgw import concluded_names` —— 审计层**直接依赖 formalgw**（见第 10 组的解耦代价）。 |
| `agentflow/src/agentflow/verify.py:674-680` | **判据**：`evidence_kind == "proof"` 而 `method != "formal"` ⇒ error（FC-22 第二道闸）。 |
| `agentflow/src/agentflow/verify.py:701` | **实现**：子目标的 `experiment_ids` + `proof_experiment_ids` 一并遍历。 |
| `agentflow/src/agentflow/verify.py:809-839` | **判据**：`proof` 级断言引用的实验本身不是 `proof` 级 ⇒ error（`proof_claim_rests_on_weaker_evidence`）。 |
| `agentflow/src/agentflow/verify.py:841-872` | **口径（注释）**：**"proof 只锚在自报字段上"** —— 手写一行 `method='formal'` + `evidence_kind='proof'` + 任意 `verifier_output` 就能进库；并记下判据的边界（②太宽：`claim_key='L'` 是 `'Lean4: no goals'` 的子串）。 |
| `agentflow/src/agentflow/verify.py:886-906` | **判据（`selfreported_proof`）**：`evidence_kind == "proof"` 而 `verifier_output` 里没有**绑在**声明名上的诊断 ⇒ error "**这条 proof 是自报的**：没有任何检查器对这条命题给出过结论。" |
| `agentflow/src/agentflow/verify.py:915-925` | **判据（`proof_claim_without_formal_experiment`）**：`evidence_kind == "proof"` 却一条 `exp:` 引用都没有 ⇒ error（`E-2`）。 |
| `agentflow/src/agentflow/verify.py:951-985` | **判据（`proof_claim_on_unclosed/refuted/disputed_dependency`）**：`proof` 级断言压在不可用依赖上 ⇒ error（四个理由码分列）。 |
| `agentflow/src/agentflow/verify.py:1570` / `:1607-1626` | **判据（猜想）**：`proved` 必须挂一条 `proof_experiment_id`；且那条实验必须 `method == "formal"`、`evidence_kind == "proof"`、`verifier_output` 非空 ⇒ 否则 error `proved_without_formal_proof`。 |
| `agentflow/src/agentflow/verify.py:1642-1649` | **判据（升格）**：升格断言的 `evidence_kind` 必须是 `proof`，且 citations 里必须有 `exp:<proof_id>`，且必须有 `status=closed` 的依赖。 |
| `agentflow/src/agentflow/verify.py:1693-1747` | **判据（命题侧）**：`proof` 级命题不许压在 `refuted`/`superseded` 命题上（`proof_stmt_on_unusable_stmt`）。 |

### 6.4 `gates.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/gates.py:436-459` | **实现**：`_candidates` 类 —— 引用/路径来源：显式 `files`，否则从稿件里的 **`proof_location`** 与依赖里抽（含 `claimanatomy.py` 对 `proof_location` 形态的定义）。 |
| `agentflow/src/agentflow/gates.py:507-...` | **实现**：把 `proof_location` 形态的 `file:line` 里的行号切掉。 |
| `agentflow/src/agentflow/gates.py:571-...` | **实现**：文件引用的两个来源（`claims[*].proof_location` 与依赖自由文本）。 |
| `agentflow/src/agentflow/gates.py:683` | **口径（注释）**：写入期 `doc_tools.check_proofs` 用的是 `is_file()`（与本门同口径）。 |
| `agentflow/src/agentflow/gates.py:718` / `:799` | **实现**：`evidence_used=("documents.claims[*].proof_location", "dependencies[*]", "workspace_root")`。 |
| `agentflow/src/agentflow/gates.py:919-933` | **口径（注释）**：`proof_location` 要么是本文档的 `claim_id`（裸写或带行号，允许自指），要么是路径；分类函数 `tools.doc_tools.classify_proof_location` 与写入期 `check_proofs` **同一份**；并注明"这一层比 `check_proofs` 弱，是刻意的"。 |
| `agentflow/src/agentflow/gates.py:955-1009` | **实现（G3 门）**：逐条 `proof_location` 分类 + P 读数 `"声明了 proof_location 的断言"` + `self_attestation` + `evidence_used`。 |
| `agentflow/src/agentflow/gates.py:2153` | **口径（注释）**：`evidence_kind != 'proof'` 的断言若标 `allowed_use='主结果'` ⇒ （判据）。 |

**注意（口径区分，别混）**：`gates.py` 里的 `proof_location` 是**主张的落点字段**
（`file:line` 锚），与"`evidence_kind=proof`（形式化检查器核过）"是**两件不同的东西**。
`gates.py` 里**没有**任何要求 `evidence_kind=proof` 或"检查器 verified"的判据。

### 6.5 `reviewaccept.py`

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/reviewaccept.py:488` | **口径/判据**：`"（有 proof 级的结论没有 T3 背书）⇒ 要么降档并改措辞，要么补 T3"` —— 验收面把收工门 `load_bearing` 的结论转写成可操作项。 |
| `agentflow/src/agentflow/reviewaccept.py:190` | **口径（注释）**：口径写进 `PAPER_PACK`（"无人值守那一趟拿不到这一格，答完再 `--resume`"）。 |
| `agentflow/src/agentflow/reviewaccept.py:448` | **口径（注释）**：`out/review/REPORT.md` 的路径口径（见 `PAPER_PACK` 第九节）。 |

### 6.6 顺带（不在任务点名里，但同属"口径与门"）

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/src/agentflow/evidencebits.py:9-17` | **口径（五元位表）**：`\| 2 \| 有证明 `proof` \| F \|`、`\| 4 \| 形式化通过 `formal` \| E \| 四态，同第 1 位；`verified` 才算过 \|`；凭据来源说明。 |
| `agentflow/src/agentflow/evidencebits.py:55-58` | **口径（词表）**：`BIT_NAMES = ("numeric", "proof", "reviewed", "formal", "audited")`；`BIT_OWNERS = {"numeric":"E","proof":"F","reviewed":"V","formal":"E","audited":"H"}`。 |
| `agentflow/src/agentflow/evidencebits.py:221-226` | **实现（等级派生）**：`has_proof` + `formal` ⇒ 最高档；`has_proof` + `reviewed` ⇒ 次档。 |
| `agentflow/src/agentflow/evidencebits.py:240` / `:266-269` | **判据**：第 4 位（形式化通过）必须写清是哪个检查器（`checker`：lean4 / coq / isabelle…）。 |
| `agentflow/src/agentflow/evidencebits.py:316-320` | **口径（凭据表）**：`"formal": {"ledger": "experiments（method='formal'）", "pointer": "bits.evidence.formal 里的 experiment_id / checker", "criteria": "位说 verified ⇒ 指针指的那条实验行必须在 experiments 表里，且 method='formal'"}`。 |
| `agentflow/src/agentflow/evidencebits.py:346-374` | **判据**：`proof` 位为真而 `statements.proof_text` 空 ⇒ error `bits_proof_without_evidence`（引用命题凭文献代号的不在此列）。 |
| `agentflow/src/agentflow/claimanatomy.py:424` | **口径**：**"证据类型轴（FC-22）：`proof` 只能是形式化检查器的产出"**。 |
| `agentflow/src/agentflow/claimanatomy.py:937` / `:968` / `:974` | **判据**：`status=待精化` + `evidence_kind=proof` ⇒ 一致；"「证」必须有 `proof` 级证据（形式化检查器的产出）"；`status='验'` 却 `evidence_kind='proof'` 是矛盾。 |
| `agentflow/src/agentflow/tools/doc_tools.py:90` | **口径**：`"proof": "形式化核验（proof）"`（渲染用的词表）。 |
| `agentflow/src/agentflow/tools/doc_tools.py:910-1036` | **判据（`check_proofs`，写入期 D-1）**：`evidence_kind="proof"` 的断言必须真的挂在一份形式化证据上（四种坏形态逐条）；`:1036` "文件位置是形式化证据…"。 |
| `agentflow/src/agentflow/tools/doc_tools.py:1334` / `:1668` / `:1726-1740` | **口径/实现**：证据等级三档必须分列（`proof` = 形式化检查器核验）；D-1 的写入期判据接线。 |
| `agentflow/src/agentflow/tools/conjecture_tools.py:20` | **口径（docstring）**：`proved` 必须有形式化证明（状态硬条件）。 |
| `agentflow/src/agentflow/specs/d.py:161` / `:190` | **声明**：猜想的 `proof_experiment_id` 字段与九个状态的硬条件（`proved` 要 `proof_experiment_id`）。 |
| `agentflow/src/agentflow/specs/d.py:196` / `:222` | **声明**：可挽救性评估里点名"要不要形式化"；"数学对错的最终背书在形式化（E）或人"。 |
| `agentflow/src/agentflow/specs/f.py:85` | **声明（边界）**：`"子目标标 `closed` 必须有 proof 级证据（`proof_experiment_ids` 非空）；只有数值或穷举支持就标 `supported_not_proved`（FC-22）"`。 |
| `agentflow/src/agentflow/specs/f.py:93` | **声明（政策）**：`F` 把证明全文（`proof_text`）交给 V 复核。 |
| `agentflow/src/agentflow/specs/b.py:117` / `:129` / `:142` / `:192` | **声明**：`proof_text` 可缺（缺则落最低等级）；命题台账三件套（含逐字 `proof_text`）。 |

---

## 7. 判据（测试）

| 文件:行 | 用例名 | 这里在断言什么 |
|---|---|---|
| `agentflow/tests/test_agent_prompts.py:101` | `test_the_toolchain_reading_is_in_every_prompt_and_is_not_hardcoded` | ① 每个角色的提示词里都有"证明工具链"那一段，且没传读数时说"没有读到读数"；② 传了读数时逐字出现，且换探针替身后正文跟着变（证明它是投影不是写死）。 |
| `agentflow/tests/test_agent_prompts.py:153` | `test_the_formal_writing_block_goes_to_whoever_holds_the_tool` | `TOOLCHAIN_FORMAL` 的受众 = 工具面上真有 `verify.check_formal` 的角色（按 `_writes_lean` 现算，不写死角色名）。 |
| `agentflow/tests/test_agent_prompts.py:180` | `test_the_toolchain_line_says_to_pass_mathlib_when_the_probe_says_it_works` | Mathlib 可用时那一段必须说"显式传 `['Mathlib']`"，而不是叫你去写自足文件（正控 + 负控两侧）。 |
| `agentflow/tests/test_agent_prompts.py:253` | `test_the_parent_limits_block_goes_to_whoever_can_summon` | （相邻协作块，受众判据同族。） |
| `agentflow/tests/test_agent_prompts.py:416` | `test_the_formal_verification_path_says_verdict_then_ledger_row` | ① 提示词必须有 `run_experiment(method='formal'` 这条落库路径；② 必须写明 `check_formal` "只给裁决、不落台账"；③ 负控：真跑一次 `check_formal` 后 `experiments` 行数不变。 |
| `agentflow/tests/test_agent_prompts.py:456` | `test_e_is_told_to_write_the_lean_source_into_the_workspace` | E 的提示词里必须有 `fs.write` / `code/lean/` / `script_path` / `proof_location`，以及无 Mathlib 时的三条写法口径（`decide` / `不归约` / `sorry` / `改一处再试` / `checker_name`）。 |
| `agentflow/tests/test_agent_prompts.py:1965-1970` | 夹具常量 `_SURFACE_FIXTURE_TOOLCHAIN` / `_SURFACE_FIXTURE_FORMAL` | 把两段工具链文案钉成与机器无关的固定串（冻结摘要不受本机装了什么影响）。 |
| `agentflow/tests/test_agent_prompts.py:1977+`（表）与 `:2289` | `test_the_prompt_version_moves_with_the_sections`（+ `_FROZEN_PROMPT_DIGESTS`） | 十格渲染摘要 + `PROMPT_VERSION` 必须与段一起动；**任何改段的改动都必须同轮改这张表与版本号**。 |
| `agentflow/tests/test_check_formal_wiring.py:106` | `test_check_formal_passes_source_name_imports_timeout_to_the_bridge` | `check_formal` 把 `source/name/imports/timeout` 透传给桥接层。 |
| `agentflow/tests/test_check_formal_wiring.py:135` | `test_check_formal_does_not_pass_the_filename_as_the_declaration_name` | 不拿文件名词干当声明名。 |
| `agentflow/tests/test_check_formal_wiring.py:167` | `test_check_formal_normalizes_script_path_and_keeps_old_signature` | `script_path` 归一 + 旧签名不变。 |
| `agentflow/tests/test_check_formal_wiring.py:224` | `test_the_contract_stub_comment_matches_the_live_key_set` | 契约桩注释与实况键集一致。 |
| `agentflow/tests/test_check_formal_wiring.py:272` | `test_negative_control_out_of_workspace_script_path_is_refused` | 越界 `script_path` 被拒。 |
| `agentflow/tests/test_check_formal_wiring.py:304` | `test_negative_control_validate_params_rejects_bad_timeout_and_imports` | 坏 `timeout` / `imports` 被 `validate_params` 拒。 |
| `agentflow/tests/test_agent_e.py:280` | `test_formal_method_keeps_proof_only_because_schema_requires_verifier_output` | formal 方法之所以能留 proof，只因 schema 要求 `verifier_output`。 |
| `agentflow/tests/test_agent_e.py:487` | `test_schema_accepts_formal_proof_with_verifier_output` | schema 接受带 `verifier_output` 的 formal proof。 |
| `agentflow/tests/test_agent_e.py:479` | `test_schema_rejects_numeric_experiment_claiming_proof` | schema 拒绝数值实验声称 proof。 |
| `agentflow/tests/test_agent_e.py:581` | `test_evidence_for_proved_only_with_proof_level_experiment` | `proved` 只在有 proof 级实验时为真。 |
| `agentflow/tests/test_agent_e.py:622` / `:642` / `:665` | `test_check_formal_without_backend_is_not_checked_not_failed` / `test_check_formal_with_backend_and_no_source_is_no_script_not_no_backend` / `test_check_formal_with_backend_and_a_source_really_calls_the_bridge` | `check_formal` 的三态行为（无后端 / 有后端无源码 / 有后端有源码真调桥接）。 |
| `agentflow/tests/test_agent_e.py:835` | `test_proof_requires_verifier_subject_key_matching_the_claim` | proof 行必须 `verifier_subject_key == claim_key`。 |
| `agentflow/tests/test_agent_e_formal_path.py:95` | `test_formal_path_registers_a_proof_row_when_the_checker_says_verified` | 检查器说 `verified` ⇒ 登记 proof 行。 |
| `agentflow/tests/test_agent_e_formal_path.py:135` | `test_the_formal_row_names_the_declaration_from_the_source_not_the_file` | 声明名从源码认，不从文件名。 |
| `agentflow/tests/test_agent_e_formal_path.py:161` | `test_a_formal_run_refuses_to_guess_the_declaration_name` | 不猜声明名。 |
| `agentflow/tests/test_agent_e_formal_path.py:179` | `test_formal_path_binds_the_checker_output_to_the_claim_key` | 检查器输出绑定到 `claim_key`。 |
| `agentflow/tests/test_agent_e_formal_path.py:195` | `test_the_proof_row_the_formal_path_writes_passes_the_selfreported_audit` | formal 路径写的 proof 行能过自报审计。 |
| `agentflow/tests/test_agent_e_formal_path.py:251` | `test_a_failed_check_is_never_registered_as_proof` | 检查没过 ⇒ 绝不登记 proof。 |
| `agentflow/tests/test_agent_e_formal_path.py:274` | `test_a_compile_error_without_mathlib_says_the_one_thing_to_change` | 缺 Mathlib 的 `compile_error` 要给出"该改的那一处"（`_mathlib_remedy_note`）。 |
| `agentflow/tests/test_agent_e_formal_path.py:303` | `test_no_remedy_note_when_mathlib_is_not_the_missing_piece` | 不是缺 Mathlib 时不给那条提示（负控）。 |
| `agentflow/tests/test_agent_e_formal_path.py:330` | `test_a_check_that_did_not_run_is_never_registered_as_proof` | 没查成 ⇒ 绝不登记 proof。 |
| `agentflow/tests/test_agent_e_formal_path.py:348` | `test_formal_path_refuses_a_non_lean_artifact_without_writing_anything` | 非 `.lean` 产物当场拒且不写任何行。 |
| `agentflow/tests/test_agent_e_formal_path.py:365` | `test_computational_methods_refuse_name_and_imports_instead_of_ignoring_them` | 计算类方法收 `name`/`imports` 要拒（不是静默忽略）。 |
| `agentflow/tests/test_agent_e_formal_path.py:418` | `test_real_lean_kernel_proof_registers_a_proof_row` | **真 Lean 内核**跑通的 proof 登记（依赖本机 Lean）。 |
| `agentflow/tests/test_agent_e_formal_path.py:442` | `test_e12_formal_failure_tri_state_is_recovered_from_the_checker` | `E-12` 三态从检查器恢复。 |
| `agentflow/tests/test_agent_e_formal_reasons.py:71` | `test_formal_reasons_is_a_well_formed_local_vocabulary` | `FORMAL_REASONS` 词表形态。 |
| `agentflow/tests/test_agent_e_formal_reasons.py:80` | `test_every_checker_status_is_explicitly_collected_in` | 每个检查器状态都被显式收口进映射表。 |
| `agentflow/tests/test_agent_e_formal_reasons.py:92` | `test_negative_control_a_checker_status_missing_from_the_map_breaks_the_import` | 负控：漏一个状态 ⇒ import 期炸。 |
| `agentflow/tests/test_agent_e_formal_reasons.py:109` | `test_all_nine_checker_statuses_survive_the_collection` | 九个检查器状态全部存活。 |
| `agentflow/tests/test_agent_e_formal_reasons.py:126` / `:140` / `:158` / `:219` / `:244` | （工具层两条拒绝 / 受控 reason / 词表外不透传 / 导入期真断言 / 映射表与词表一致） | 收口与透传的边界。 |
| `agentflow/tests/test_toolchain_paths.py:76` / `:88` / `:100` / `:108` / `:120` / `:136` | （`explicit_bin` 文件 / 目录、`prover_path`、未配置不可见、坏配置是问题不是缺失、`reason` 说出找过哪里） | `resolve_checker` 四档查找与三态。 |
| `agentflow/tests/test_toolchain_paths.py:145` | `test_probe_and_invocation_agree_under_the_same_environment` | 探测与调用共用同一个答案。 |
| `agentflow/tests/test_toolchain_paths.py:164` | `test_mathlib_state_reads_the_root_and_says_whether_import_works` | `mathlib_state` 读根并说 `import` 行不行。 |
| `agentflow/tests/test_toolchain_paths.py:193` | `test_formalgw_fills_in_lean_path_itself` | `formalgw` 自己拼 `LEAN_PATH`（走 `lean_path_for`）。 |
| `agentflow/tests/test_toolchain_paths.py:224` | `test_doctor_exit_codes_are_three_state` | `doctor` 退出码三态。 |
| `agentflow/tests/test_formalgw_toolchain.py:48` / `:58` / `:82` / `:92` | （revision 读戳文件 / 区分未核与不符 / 直读 git HEAD / ref 读不了） | Mathlib revision 的读数。 |
| `agentflow/tests/test_formalgw_toolchain.py:104` / `:114` / `:129` / `:168` | （imports 拒非目录 / 无 lake 时不算查 / 探针跑完不留痕 / checkdir 不可写） | `import Mathlib` 探针的边界。 |
| `agentflow/tests/test_formalgw.py:57`-`:92` | （`detect_backend` 五条） | 后端探测三态（available / no_backend / probe_failed）。 |
| `agentflow/tests/test_formalgw.py:115` / `:130` | `test_status_vocabulary_is_controlled` / `test_only_verified_may_produce_proof_level_evidence` | `STATUSES` 受控；**只有 `verified` 允许产出 proof 级证据**。 |
| `agentflow/tests/test_formalgw.py:137`-`:442` | （`sorry` / `axiom` / `decl_mismatch` / `timeout` / `import_unavailable` / `no_backend` / `tool_crashed` 各条 + 三条负控） | 每一条"查了没通过"与"没查成"的分界。 |
| `agentflow/tests/test_formalgw.py:530` | `test_the_default_imports_inject_nothing` | **默认不注入任何库**。 |
| `agentflow/tests/test_formalgw.py:620`-`:734` | （版本词表三态 + 钉住一致性） | `PINNED_LEAN_*` / `PINNED_MATHLIB_*` 的判据。 |
| `agentflow/tests/test_formalgw.py:741` | `test_the_module_selftest_passes_offline` | 模块自检离线可过。 |
| `agentflow/tests/test_formalgw_no_axioms_shortcircuit.py:41`-`:90` | （5 条：报告的 axioms 胜过"无公理"那句 / 干净声明仍干净 / 具名干净行不能豁免列出的公理 / 真 Lean 公理把戏不算 verified / 真干净内核定理仍 verified） | 公理审计的短路与负控。 |
| `agentflow/tests/test_verifier_role.py:39` / `:46` | （冷启动提示词不带句柄 / 只带对象与禁令） | **V 的"逐行审阅证明"入口口径**。 |
| `agentflow/tests/test_verifier_role.py:71` / `:98` / `:127` / `:143` / `:153` / `:168` | （脏证明被拒且不签 / 干净证明被签并推进五元位 / 三态不折叠 / 手造裁决坏字段写入期拒 / 台账追加式与脚本分配号 / 坏命题号被拒） | V 的完整行为面。 |
| `agentflow/tests/test_d1_proof_evidence_anchor.py:110`-`:237` | （10 条：缺文件 / 无 `proof_location` / 只引文献 / 压在 cross_check 上 / 真锚仍写 / cross_check 不受门限 / `check_proofs` 三态 / 问题分类 / `revise` 不能偷渡 / `revise` 保住锚） | `doc_tools.check_proofs` 的 D-1 写入期判据。 |
| `agentflow/tests/test_r2r2_proof_location_classification.py:64` / `:74` / `:136` / `:152` / `:165` | （分类函数逐例 / 两处调用点一致 / G3 交叉引用既不算 id 也不算 path / 裸 claim_id 单列 / 不存在的 claim_id 仍拒） | `proof_location` 的分类（注意：**这是落点字段，不是 proof 证据**）。 |
| `agentflow/tests/test_verify_selfreported_proof_boundary.py:71`-`:174` | （7 条 + 证据上限登记在判据旁 / 交叉验证会丢掉连字符控制） | `verify.selfreported_proof` 的边界。 |
| `agentflow/tests/test_runflow_lean.py:86`-`:246` | （10 条：默认关且如实说 / 开了且 verified 才摘牌 / 开了但无片段 / 开了但无后端 / 无名片段不算跑过 / `sorry` 退出码 0 不成 proof / 额外公理不成 proof / 声明不符退出码 0 不成 proof / 超时记没查成） | **`runflow` 那条流程的 `--lean` 开关面**（与角色工具的 formal 路径是两套）。 |
| `agentflow/tests/test_agent_prompts.py`（冻结摘要表，`:1977+`） | `_FROZEN_PROMPT_DIGESTS` | 十格摘要冻结（含工具链两段夹具）。 |
| `agentflow/tests/conftest.py:108-119` | `_MACHINE_ENV_NAMES` | 判据把 `AGENTFLOW_LEAN_BIN` / `AGENTFLOW_COQ_BIN` / `AGENTFLOW_ISABELLE_BIN` / `AGENTFLOW_PROVER_PATH` / `AGENTFLOW_MATHLIB_ROOT` 一起清掉，并把 `AGENTFLOW_SETTINGS` 钉到不存在的路径 —— **本机设置文件不许渗进判据**。 |
| `agentflow/tests/test_settings.py:63` / `:89-90` / `:109` / `:342` / `:548-569` / `:598` / `:611` / `:886` / `:912` | （`toolchain` 段读写的各档判据） | 设置层的 `toolchain.*` 判据（`lean` / `mathlib` 相关行在上面那几处）。 |
| `agentflow/tests/test_capability_seams.py:131-178` | `test_...`（含 `check_formal` 的 `name` 接缝与 `run_experiment` 的 T0-13 正控） | 能力表层与实现层的参数接缝（含"formal 的两格必须能过闸门"）。 |
| `agentflow/tests/test_tools_readonly_roles.py:196`-`:260` | （只读角色的工具面判据） | H 拿不到写工具（含 `check_formal` 收窄后的面）。 |
| `agentflow/tests/test_agent_loop.py:597-620` | （工具链两段文案的 monkeypatch 装配） | 提示词装配点上两段读数被传进去。 |
| `agentflow/tests/test_tools_audit_fixes.py:522-533` / `:847-1007` | （`check_formal` 返回形状 / 失败 kind 等） | `check_formal` 的 `returns=` 声明与实测逐分支对齐。 |

**注意（题面点名但实际不含 Lean 内容的文件）**：
`agentflow/tests/test_the_new_model_is_reachable_online.py` —— 全文 84 行，
**没有任何 Lean / Mathlib / 形式化相关断言**：它打的是 `pytest.mark.network`，
两条用例 `test_the_endpoint_knows_deepseek_flash`（`:58`）与
`test_a_bare_call_thinks_with_the_new_model`（`:72`），判的是**模型端点与思维链**。
⇒ 它在"Lean 影响面"里**可以不动**。

---

## 8. 文档

| 文件:行 | 这里在干什么 |
|---|---|
| `agentflow/DEVELOPMENT.md:477` | **文档（目录树）**：`settings.py ★ 机器级设置的一处定义（本机工具链落点 / Mathlib 根 / 模型 key / workspace.projects_dir…）`。 |
| `agentflow/DEVELOPMENT.md:1416` | **文档（已知缺口表第 11 行）**：`\| 11 \| method="formal" 的真实后端路径 \| 本机无 Lean/Coq/Isabelle \| ✅ **已关闭（B8a）**：Mathlib（Lean + Mathlib v4.7.0）就位后，真 Lean 四条控制实测 fail=0 …` ← **这一行是"写死『本机有 Lean/Mathlib』"的最明确落点**，开关落地后必须改。 |
| `agentflow/README.md:130` | **文档（故障排查表）**：`\| 汇总框里 `Lean 开启=否；proof 级证据 0 条` \| 没装 Lean（或没加 `--lean`）\| 装 Lean 后加 `--lean`；否则请把这一格读成"**没形式化核过**"…` |
| `agentflow/README.md:137` | **文档**：`**不建议**在没有网、没有 key、没有 Lean 的机器上跑"真活"那一条…` |
| `agentflow/README.md:157` | **文档（角色表图）**：`形式化` 那一格。 |
| `agentflow/README.md:171` | **文档（角色表 E 行）**：`\| **E** \| 数值实验 + 形式化验证（**计算类拿不到 `proof`**）\| `write_local` × **`external=exec`**（起 Lean/Coq/Isabelle 与实验脚本子进程）\| B D \|` |
| `agentflow/README.md:281` | **文档（Web UI 表）**：`\| `/machine` \| 本机（检查器 / Lean / Mathlib / 钥匙配没配）\| `GET /api/machine` \|` |
| `agentflow/README.md:396` | **文档（目录树）**：`settings.example.json 机器级设置的示例（本机工具链落点 / Mathlib 根 …）`。 |
| `agentflow/README.md:405` | **文档（目录树）**：`docs/FORMAL-TOOLCHAIN.md 形式化后端（Lean）的工具链口径`。 |
| `agentflow/README.md:457` | **文档（目录树）**：`formalgw.py Lean 形式化后端（缺工具链 ⇒ inconclusive，不是 fail）`。 |
| `agentflow/AGENTS.md:38` | **文档（FC-27 平移表）**：`\| 对外 API 破坏性变更 \| 数值求解器的核心算法 / 证明检查器的桥接层 \|` ← **这解释了为什么 `verify_tools.py` 在禁改区**。 |
| `agentflow/AGENTS.md:65-67` | **文档（禁改区清单副本）**：`[category: prover-bridge] 二、证明检查器的桥接层` + `src/agentflow/tools/verify_tools.py … 桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印`。 |
| `agentflow/AGENTS.md:143-162` | **文档（退出码语义节）**：`0 = clean` / `1 = requires_human` / `2 = unknown`，含"`unknown` 绝不是 `clean`"与"不给 `--since` 时改动集为空会判 `unknown`(2)"。 |
| `agentflow/DESIGN-ROLES.md:90` | **文档**：`### 2.1 E —— 数值实验与形式化验证`。 |
| `agentflow/DESIGN-ROLES.md:292` | **文档**：`3. **E 的 `formal` 方法在本环境无法使用**（无 Lean/Coq），因此 `evidence_kind="proof"` …` ← **这条与 `DEVELOPMENT.md:1416` 的"已关闭"互相打脸**（一处说没有、一处说已就位）；开关落地时必须一起对齐。 |
| `agentflow/DESIGN-TOOLS.md:394` | **文档（目录树）**：`verify_tools.py E：数值实验与形式化验证（6 条）`。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:1` | **文档（专文标题）**：`# 形式化验证工具链：装哪个版本、怎么装、装完怎么验` ← **整份文件（含 39 处 Lean/Mathlib 提及）就是"证明工具链"的专文**。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:8` | **文档**：`> agentflow/settings.json 的 toolchain.lean_bin / toolchain.mathlib_root`。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:24-25` | **文档（钉住表）**：Lean `4.7.0` / commit；Mathlib commit（tag `v4.7.0`）"Mathlib 与 Lean 版本必须配对"。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:30-31` | **文档**：四个钉常量 `PINNED_LEAN_VERSION` / `PINNED_LEAN_COMMIT` / `PINNED_MATHLIB_COMMIT` / `PINNED_MATHLIB_TAG`。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:37-46` | **文档（安装节 §2.1 Lean）**：取发行包、解压、写进 `toolchain.lean_bin`、本机落点 `_env/lean470/…`、环境变量 `AGENTFLOW_LEAN_BIN`。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:48-83` | **文档（安装节 §2.2 Mathlib）**：Mathlib 是 lake 工程；装完必须写 commit 戳；**"`formalgw` 的 `imports` 默认是 `("Mathlib",)`"**（← 与代码 `verify_tools.py:432` 的"默认不注入"**矛盾**，见下面第 10 组）；裸 `lean` 会报 `unknown package 'Mathlib'`。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:94-98` | **文档（验证命令）**：`python -m agentflow.formalgw --toolchain --import-check`（额外真跑一次 `import Mathlib`，约 1 分钟）。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:116-117` | **文档**：`import_unavailable` vs `compile_error` 的分界。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:128-131` | **文档（本机实测表）**：Lean 版本/commit/落点、Mathlib 装在哪（`_env/mathlib-pinned2/mathlib4-4.7.0`，4100 个 olean，`Mathlib.olean` 在）、Mathlib commit。← **这段逐字写着"本机有 Lean/Mathlib"**。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:141` | **文档**：`check_toolchain ⇒ mathlib: installed_ok` 的读法。 |
| `agentflow/docs/FORMAL-TOOLCHAIN.md:163-164` | **文档（设置键表）**：`toolchain.lean_bin` / `toolchain.mathlib_root`。 |
| `agentflow/docs/INDEX.md:22` | **文档（索引）**：`FORMAL-TOOLCHAIN.md 形式化后端（Lean / Mathlib）的工具链口径…§6 是机器级设置文件的逐字口径`。 |
| `agentflow/docs/INDEX.md:31` | **文档（索引）**：`USER-TEST-TASK-QUOTE-FORMAL.txt 同上，但点名要求两条腿的版本（13 条）：(A) 引文逐字回验 …` |
| `agentflow/docs/INDEX.md:54` | **文档（索引）**：`../settings.example.json 机器级设置文件的示例（本机工具链落点 / Mathlib 根 …）`。 |
| `agentflow/docs/READING-MAP.md:99` | **文档（阅读地图）**：`toolchain.py 这台机器上的证明工具链（一处定义）…四档查找`。 |
| `agentflow/docs/READING-MAP.md:149` | **文档**：`tools/verify_tools.py E 的工具：数值实验与形式化验证（禁改区）`。 |
| `agentflow/docs/READING-MAP.md:164` | **文档**：`agent_e/（包） E：数值实验与形式化验证`。 |
| `agentflow/docs/READING-MAP.md:181` | **文档**：`evidencebits.py 命题的五元证据位与派生等级…` |
| `agentflow/docs/READING-MAP.md:241` | **文档**：`formalgw.py Lean 形式化验证后端`。 |
| `agentflow/docs/READING-MAP.md:264` | **文档（改动路由表）**：`\| 动 **E 的实验 / 形式化** \| agent_e/（包） \| formalgw.py、tools/verify_tools.py（禁改区）\| tests/test_agent_e*.py \|` |
| `agentflow/docs/USER-TEST.md:128` | **文档**：`> **要跑"点名要求引文查询与形式化验证"的那一版**：换任务文件，并把预算与步数给足。` |
| `agentflow/docs/USER-TEST.md:138-142` | **文档**：`# 形式化那一格：检查器在盘上但不在 PATH —— 这一行决定它能不能真验`；`$env:AGENTFLOW_LEAN_BIN = "_env\lean470\lean-4.7.0-windows\bin"`。 |
| `agentflow/docs/USER-TEST.md:148-156` | **文档**：`①**形式化那一格取决于上面那一格配置**…Lean 4.7.0 在盘上…**Mathlib 那一档今天不行**（`import Mathlib` ⇒ `import_unavailable`）` ← **这条与 `FORMAL-TOOLCHAIN.md:130` 的"Mathlib 装了"直接矛盾**（见第 10 组）。 |
| `agentflow/docs/USER-TEST-TASK.txt:15` | **文档（任务模板）**：交付说明必须是九节，第四节是"形式化覆盖"。 |
| `agentflow/docs/USER-TEST-TASK-QUOTE-FORMAL.txt:5` | **文档（任务模板）**：`(B) **形式化验证**：把论文里可形式化的那条引理交给检查器真跑一次。**检查器在盘上，但不在 PATH**：Lean 4.7.0 在 `D:\Incubator\temp\lean470\…`（commit 6fce8f7d…）` ← **写死了绝对路径与 commit**。 |
| `agentflow/docs/USER-TEST-TASK-QUOTE-FORMAL.txt:18-20` | **文档（任务模板）**：`（a）挑论文里一条真的可以形式化的引理…（`method="formal"` 只接受 `.lean` 产物）…（b）派 E 走 `check_formal(claim=…)`，或 `run_experiment(method="formal", …)`。` |
| `agentflow/docs/USER-TEST-TASK-QUOTE-FORMAL.txt:28-29` | **文档（任务模板）**：第四节要写清"哪条引理被形式化、检查器在不在、结果是 checked / reason / verifier_status 各是什么"。 |
| `agentflow/docs/TOOLBOX-DRAFT-roles.md:55` / `:116` | **文档（草稿）**：E 的工具面统计里含"数值实验与形式化设计"与 `verify.check_formal`。 |
| `agentflow/docs/USER-END-DSH-STYLE.md:106` | **文档**：`/machine` 的字段里含 `mathlib` / `lean_ready` / `can_do_formal`。 |
| `agentflow/docs/PROPOSALS.md`（129 处提及） | **文档（提案集）**：未逐条展开（129 处，超出本次逐行清单的必要粒度）。**没逐条查到行号 —— 不确定它有哪几条是"必须改"**。 |
| `agentflow/docs/ROLE-SPECS.md`（20 处提及） | **文档（角色规格）**：同上，**没逐条查到行号**。 |
| `agentflow/docs/NOAI-*.md` / `docs/PROPOSAL-side-effect-axes.md` / `docs/SCHEMA-MIGRATION-*.md`（各 2-7 处） | **文档**：同上，**没逐条查到行号**。 |

---

## 9. FC-27 影响面

### 9.1 `agentflow/.noai-paths` 的条目数

实测：**43 条**（`Select-String -Pattern '^src/|^tests/|^scripts/|^tools/|^pyproject|^AGENTS|^\.noai'`
得 43 条匹配；文件共 147 行，其中 7 个 `[category: ...]` 分组头 + 若干注释与空行）。
⇒ 与题面"43 条条目"一致。

### 9.2 第 1–8 组里落在禁改区的路径（逐条）

| 路径 | 属哪一类（`[category:]`） | 命中原因（它与本任务的关系） |
|---|---|---|
| `src/agentflow/tools/verify_tools.py` | `prover-bridge`（同时也在 `.noai-paths:77` 逐字登记） | 唯一的形式化工具实现与声明（`detect_verifier` / `check_formal` / `run_experiment` / `_EVIDENCE_ORDER` / `_ROLES_WRITE`）。**开关要改工具面，必须动它**。 |
| `src/agentflow/quoteverify.py` | `prover-bridge` | `check_quote` 引文级回验。**与 Lean 无关**（属"桥接层"同一类但另一条腿）。⇒ 开关**不该动它**。 |
| `src/agentflow/schema.py` | `schema-migration`（`SCHEMA_VERSION` 与 `TABLES`）**且** `eval-criteria`（`EVAL_REQUIRED_FIELDS` 与 `EvalResult`） | `EVIDENCE_KINDS` / `EXPERIMENT_METHODS` / `Experiment.validate` 的硬约束 1/2/2b / `verifier_output` / `verifier_subject_key` 全在这里。**开关若要让"没有 Lean 也能推进"，口径的落点就是这里**。 |
| `src/agentflow/verify.py` | `auth-audit` | 一致性审计的判据本体（`selfreported_proof` / `proof_claim_*` / `proved_without_formal_proof` / `proof_stmt_on_unusable_stmt`），且第 37 行直接 `from .formalgw import concluded_names`。 |
| `src/agentflow/interactions.py` | `auth-audit` | 跨 agent 交互的冻结契约与闸门。**与形式化基本无关**（唯一一处是 `:275` 的否定标记注释）。⇒ 开关**不该动它**。 |
| `src/agentflow/capabilities.py` | `auth-audit` | A–H 调用矩阵的权威定义（`ALLOWED_EDGES` / `CAPABILITIES` / `WRITE_SETS` / `NON_SUMMONABLE`）；`PARAM_SEAMS[("E","check_formal")]` 也在这里。 |
| `src/agentflow/specs/__init__.py` | `auth-audit` | `specs/` 包的收表入口（`builtin_specs` / `action_table` / `edges` / `write_sets` / `non_summonable`）。 |
| `src/agentflow/specs/e.py` | `auth-audit` | 角色 E 的声明真身（动作表 + 职责 + 政策 + 写集）。**开关要改 E 的口径，必须动它**。 |
| `src/agentflow/specs/g.py` | `auth-audit` | 角色 G 的声明真身（其中 `:144` / `:146` / `:150` 与形式化有关）。 |
| `src/agentflow/specs/h.py` | `auth-audit` | 角色 H 的声明真身（其中 `:110` / `:114` / `:142` 与形式化有关）。 |
| `src/agentflow/specs/m.py` | `auth-audit` | 角色 M 的声明真身（其中 `:57` / `:62` / `:63` / `:68` / `:70` / `:76` / `:77` 与形式化有关）。 |
| `src/agentflow/specs/v.py` | `auth-audit` | 角色 V 的声明真身（`verify_proof` / `read_proof` —— "逐行审阅证明"这条腿的声明面）。 |
| `src/agentflow/specs/a.py` / `b.py` / `c.py` / `d.py` / `f.py` | `auth-audit` | 其余角色声明真身。**其中 `specs/b.py`（`proof_text` 台账）与 `specs/d.py`（猜想 `proof_experiment_id`）与 `specs/f.py`（子目标 `closed` 必须有 proof）与形式化有关；`a.py` / `c.py` 基本无关**（`specs/c.py:106-109` 只有 `C.proof_chain` 这个**名字**里带 proof 的动作）。 |
| `src/agentflow/agentspec.py` | `auth-audit` | 声明类型与四个受控词表（`SIDE_EFFECTS` / `EFFECT` / `EXTERNAL` / `UNKNOWN_SIDE_EFFECT`）。`check_formal` 的 `external="exec"` 走这一层。 |
| `tests/golden/agent_surface_snapshot.json` | `eval-criteria` | 冻结快照：「面」的基线（10 角色 / 60 动作）。**改 `specs/e.py` 的动作表 ⇒ 这份快照必 stale，必须由人逐格重冻**。 |
| `tests/golden/tool_surface_snapshot.json` | `eval-criteria` | 冻结快照：83 个工具 / 10 个角色 / 11 条 CLI 输出。**改 `verify_tools.py` 的工具声明 ⇒ 这份必 stale**。 |
| `tests/golden/run_topic_snapshot.json` | `eval-criteria` | 冻结快照：6 件产物 × 2 条路径。与 `runflow` 的 `--lean` 那一面相关。 |
| `tests/golden/verify_all_snapshot.json` | `eval-criteria` | 冻结快照：8 个工作区 / 8 条 issue。**改 `verify.py` 的判据 ⇒ 这份可能 stale**。 |
| `.noai-paths` 自身 | `auth-audit` | 禁改区清单本体。**开关若要新增/放宽受保护路径，必须改它**（且必须与 `AGENTS.md` 的副本逐条一致）。 |
| `AGENTS.md` | `auth-audit` | 上面那份清单在 `AGENTS.md` 里的副本（机器按位比对两处）。**改清单必须同轮改它**。 |
| `scripts/noai_gate.py` | `auth-audit` | 判据本体（`REQUIRED_APPROVALS_ON_HIT` 等）。**开关若改门强度，必须动它**。 |

**落在禁改区但与本任务无关（`不应动`）**：`src/agentflow/providers.py`、`src/agentflow/dedup.py`、
`src/agentflow/extract.py`、`src/agentflow/store.py`、`src/agentflow/release_check.py`、
`scripts/release_check.py`、`tools/release_all.py`、`tools/coverage_zero_test.py`、
`tools/run_each_test_file.py`、`pyproject.toml`、`src/agentflow/tools/__init__.py`、
`src/agentflow/tools/base.py`、`scripts/lint_rules.py`、`tools/vocab_census.py`、
`.noai-approvals.json`、`src/agentflow/quoteverify.py`。

**明确"不在禁改区"的关键文件（可直接改，不需要 FC-27 人审）**：
`src/agentflow/settings.py`、`src/agentflow/toolchain.py`、`src/agentflow/formalgw.py`、
`src/agentflow/agent_prompts.py`、`src/agentflow/agent_e/**`、`src/agentflow/closing.py`、
`src/agentflow/evidencebits.py`、`src/agentflow/claimanatomy.py`、`src/agentflow/runflow.py`、
`src/agentflow/cli.py`、`src/agentflow/reviewaccept.py`、`src/agentflow/gates.py`、
`settings.example.json`、`agentflow/tests/**`（除 `tests/golden/*`）、`agentflow/docs/**`、
`agentflow/README.md`、`agentflow/DEVELOPMENT.md`、`DESIGN-*.md`。

### 9.3 `agentflow/scripts/noai_gate.py` 的退出码语义与 `REQUIRED_APPROVALS_ON_HIT`

| 项 | 值 / 语义 | 出处 |
|---|---|---|
| `REQUIRED_APPROVALS_ON_HIT` | **`2`** | `agentflow/scripts/noai_gate.py:101` |
| `MIN_INDEPENDENT_AUDITORS` | `2` | `agentflow/scripts/noai_gate.py:110` |
| `MIN_DISTINCT_DIMENSIONS` | `3` | `agentflow/scripts/noai_gate.py:111` |
| `LEDGER_NAME` | `".noai-approvals.json"` | `agentflow/scripts/noai_gate.py:137` |
| `AUDIT_RECEIPT_NAME` | `".noai-audit-receipts.jsonl"` | `agentflow/scripts/noai_gate.py:156` |
| 退出码表 | `_VERDICT_EXIT_CODES = {"clean": 0, "requires_human": 1, "unknown": 2}` | `agentflow/scripts/noai_gate.py:175`（两处 return 用它：`:284` / `:613`） |
| `0 = clean` | **查过了，未命中禁改区** | `AGENTS.md:143` |
| `1 = requires_human` | **查过了，命中禁改区 ⇒ 需要 2 名 reviewer 批准** | `AGENTS.md:144`（与 `noai_gate.py:936` / `:3344` 的提示串一致） |
| `2 = unknown` | **没查成**（清单读不到 / 不在 git 仓库 / 没给改动集）—— **`unknown` 绝不是 `clean`** | `AGENTS.md:145-148`；`noai_gate.py:4305` / `:4373` / `:4652` / `:4679` / `:4721` 等也返回 2 |
| `--check-consistency` 不一致 | 退出码 **1**（"查过了、结论是坏了"，不是"没查成"；2 只留给没查成） | `AGENTS.md` 的清单节 + `noai_gate.py:4696` `return 0 if not diffs else 1` |
| `--check-approvals` | `clean` ⇒ 0；有缺 ⇒ 1；读不成 ⇒ 2 | `noai_gate.py:4716-4721` |
| 台账自指 | `LEDGER_NAME` 不能批准自己（`ledger_self_approval`） | `noai_gate.py:3580-3582` / `:3732-3734` |

---

## 10. 一处一句话的结论

### `lean_enabled=false` 必须跟着改的地方

（逐条给理由；"必须"= 不改就会有**假读数**或**走不通**）

**A. 开关本身的三处（新增，最低成本）**
1. `settings.py:135` `TOOLCHAIN_KEYS` 加 `"lean_enabled"` —— 否则这个键永远读不到
   （`_section()` 只认登记过的键）。
2. `settings.py:197-209` `_section()` 的 `isinstance(..., str)` 判据 —— **布尔值今天会被折成
   空串**，所以要么把开关写成字符串（`"true"`/`"false"`，与既有四键同形），要么改这一层。
   这是开关能不能读到值的**唯一硬点**。
3. `settings.example.json:11-16` + `settings.py:26-37` 的键表 + `docs/FORMAL-TOOLCHAIN.md:163-164`
   —— 口径文档（示例文件是样板落点；`FORMAL-TOOLCHAIN.md` 是逐字口径的专文）。

**B. 提示词那一段（否则模型会继续按"有 Lean"写）**
4. `agent_prompts.py:1824-1877` `toolchain_facts_text()` —— false 时要输出
   "本环境不做形式化核验"的确定读数，而不是继续报"检查器可用"。
5. `agent_prompts.py:1888-1947` `toolchain_formal_text()` —— false 时应改成
   "**逐行审阅证明**"那一档的写法口径（这才是"改用自然语言逐行审阅"的落点）。
6. `agent_prompts.py:2299-2308` 段注册 + `promptkit.py:144/147` 段序 —— 段的存在与否。
7. `agent_prompts.py:1162-1171`（`PAPER_PACK` 六的"两步形式化"）+ `:1112` —— 这段逐字教
   "裁决 → 落库（`method='formal'`）"，false 时必须换成逐行审阅的两步。
8. `agentflow/tests/test_agent_prompts.py:101/153/180/416/456` 五条判据 + `:1965-1970`
   两个夹具 + `:1977+` 冻结摘要表 + **`PROMPT_VERSION`（当前 `p98`）** —— 按本仓的
   维护规则（`test_the_prompt_version_moves_with_the_sections`），**改段与改版本必须同轮**。

**C. 口径与门（否则"没有 Lean"会被读成"没通过"）**
9. `schema.py:943-953` `EVIDENCE_KINDS` —— 若要给"逐行审阅过的证明"一个**自己的等级**
   （而不是硬塞进 `cross_check`），这里是唯一定义点。`SCHEMA_VERSION` 当前 `2`
   （`schema.py:27`），**加/改 evidence_kind 属磁盘格式契约 ⇒ 在禁改区**。
10. `schema.py:1277-1306` 硬约束 1/2/2b —— false 时 `proof` 行根本不该被写出来，
    但"不许写 proof"与"不许写 proof **却没有** verifier_output"是两条不同的判据。
11. `closing.py:3161-3165` `_has_t3` + `:3168-3241` `_check_load_bearing` —— **这是唯一
    会因为"缺 proof 级证据"而红的一格**（`load_bearing`）。false 时要么给"逐行审阅"
    一条等价的 T3 替代判据，要么把这一格降为 `not_applicable`/`pass`（**这是取舍，必须由人裁**）。
12. `closing.py:2307-2338`（`MUST_T3_CONDITIONS` + `MUST_T3_GAP_NOTE`）—— 这一段的注释
    已经明写"statements 表没有指向 experiments 的字段 ⇒ 判不了逐条有没有 T3 背书，
    补法要动 `schema.py`，留给人裁"。**要把 proof 真正解耦，这是必须由人做的 schema 取舍**。
13. `closing.py:1422-1467`（`reviewed_proof_rows`）与 `specs/m.py:70/76/77` —— M 的验收表
    里 `proof_experiment_rows` 这一档在 false 时没有读数，M 的口径必须跟着改
    （否则它会写一个永远 0 的档）。
14. `verify.py:841-925`（`selfreported_proof` / `proof_claim_without_formal_experiment` / …）
    —— 这些判据在 false 时对**新写的**行应当是"不会被触发"而不是"被改宽"
    （它们守的是"不许拿自报冒充检查器背书"，false 时这个风险不消失、只是换了对象）。
    ⚠️ `verify.py` 在禁改区（`auth-audit`）⇒ **必须人审**。
15. `doc_tools.py:910-1036`（`check_proofs`，写入期 D-1）—— 同样在 false 时要换口径。

**D. 实现与工具面（"走不通"的那一半）**
16. `verify_tools.py:716-805`（`verify.check_formal` 的 ToolSpec）+ `:1131-1312`（`register`）
    —— false 时是"不下发这件工具"还是"下发了但直接返回 `no_backend` 类的三态"？
    **这是设计取舍**；但无论哪一条都要动这个文件（**禁改区 ⇒ 必须人审**）。
17. `agent_e/core.py:279-460`（`_record_formal` 的整条链，含 `:417` 的
    `"proof" if verified else _NO_EVIDENCE_KIND` 与 `:442` 的落库事务）—— false 时
    `method='formal'` 该落什么、`tri_state` 该有哪几档（今天是 `verified`/`checked_failed`/
    `not_checked` 三档，false 时需要第四档或明确的 `not_checked`）。
18. `agent_e/check_formal.py:88-105` + `run_experiment.py:123-135` —— 分叉点。
19. `agent_e/_support.py:154-192`（`FORMAL_REASONS` 与两条导入期断言）—— false 时的
    受控 reason 词表要加一档（例如 `disabled_by_config`），且两条断言要仍成立。
20. `specs/e.py:177` 那条政策（**整条都在教"怎么用 Mathlib"**）—— false 时要整条换掉，
    否则 E 拿到的是一段它做不到的写法口径。**`specs/e.py` 在禁改区 ⇒ 必须人审**。

**E. 那一条"自然语言逐行审阅"的腿（好消息：它已经在了）**
21. **不必新建**：V 的 `verify_proof` / `read_proof`（`specs/v.py:52-89`、
    `verify_tools.py:1003-1113`、`agent_v/core.py`）+ 冷启动入口
    （`verifications.cold_start_prompt`，见 `agent_prompts.py:1371` 与
    `tests/test_verifier_role.py:39/46`）**已经就是"拿证明全文、逐行给 verdict/findings"**。
    开关要做的是**把 `proof` 级证据的产出方从"检查器"换成"V 的逐行审阅"**，
    即把 `evidencebits` 的第 4 位（`formal`，`evidencebits.py:11/55-58/316-320`）
    的凭据从 `experiments(method='formal')` 换成 `verifications/<命题号>.jsonl`。
    **`evidencebits.py` 不在禁改区**，但它与 `closing.py`、`doc_tools.py`、`verify.py`
    三处相扣 ⇒ 改它必须三处同轮。

### `lean_enabled=false` 可以不动的地方

| 可以不动的地方 | 理由 |
|---|---|
| `toolchain.py` 的探测层（`resolve_checker` / `probe_checkers` / `mathlib_state` / `lean_path_for` / `_import_mathlib_probe` / `toolchain_report`） | 它是**只读的机器事实层**，三态且不写任何东西。false 时"这台机器装了 Lean"仍然是一个**真事实**，读数继续可用（正是"没有读数"与"有读数说不可用"必须分开的那条纪律）。唯一可议的是 `can_do_formal`（`toolchain.py:419`）要不要纳入开关；**建议不纳入**（它答的是"机器能不能"，不是"这一趟要不要做"）。 |
| `formalgw.py` 整份 | 它是"唯一后端"的实现，字面量全是 Lean 的（`PINNED_LEAN_*` 等）。false 时它只是**不被调用**；删它或改它等于毁掉"以后想开回来"的路径。**但注意**：`formalgw.py` 不被任何门的判据直接读（`verify.py:37` 只 import 了 `concluded_names`），所以留着它不会让 false 的读数变假。 |
| `runflow.py:168-177`（`NOT_WIRED_ITEMS` 里的 `("lean", …)`）+ `:182-224`（`PROMPT_VERSIONS` 与 `v2-lean`）+ `cli.py:2309/2348` 的 `--lean` | 这是**另一条流程**（`agentflow run` 的问答模板），**默认就是关的**（`cli.py:645` 逐字"`--lean` 缺省关闭"），而且它已经有一套完整的"关着时如实报没有形式化证据"的读数（`test_runflow_lean.py:86` 就是这条判据）。**它与 `toolchain.lean_enabled` 是两个独立的开关** ⇒ 不动它没有任何假读数。**建议**：在 `lean_enabled=false` 时把 `--lean` 也**显式拒绝**（而不是静默忽略），否则会有"配置说关、命令行说开"的两个答案 —— 但这是**加固**，不是必须。 |
| `projects.py:557/656-661` 的 `lean=` 形参 | 同上：它只是把 `--lean` 透传下去（`:656-658` 的注释逐字写了"它必须透传"）。 |
| `cli.py:1869-1907` 的 `doctor` 子命令 | 它是**给人看的体检**（且 `--lean` 侧的三态退出码 0/1/2 是它自己的判据）。false 时"这台机器能做形式化但这一趟不做"正该被人看见 ⇒ 不动。 |
| `agent_prompts.py:840`（`STRUCTURE_NOT_PROMPT` 里"自报的 proof 级证据一律降级"） | 这条是**反越权**的（"让被判定的对象自己当判官是最容易被绕过的地方"），与有没有 Lean 无关 ⇒ 必须保留。 |
| `agent_prompts.py:1038-1050`（`EVIDENCE_CONTRACT`） | 它讲的是"引文逐字 / 置信度只能降 / 交叉验证不是证明"，**一个字都没提 Lean** ⇒ 不动。 |
| `gates.py` 的所有 `proof_location` 判据（`:436-1009`） | `proof_location` 是**主张的落点锚**（`file:line` 或 `claim_id`），不是"检查器核过" ⇒ 与开关无关。 |
| `claimanatomy.py:424/937/968/974` | 它守的是"`proof` 只能是形式化检查器的产出"这条**词表一致性**。false 时如果新增了等级，这里要跟着扩词表；**如果不新增等级（`proof` 一律不产生）则不动**。 |
| `interactions.py` 全部 | 唯一一处（`:275`）是评论里的假阳性例子。**闸门与形式化无关**。 |
| `agentflow/tests/test_the_new_model_is_reachable_online.py` | 全文 84 行，**没有任何 Lean 相关断言**（打的是 `network` 标记、判模型端点与思维链）—— 题面把它列进来了，但实测它**不含**形式化内容。 |
| `agentflow/tests/test_formalgw*.py`（`test_formalgw.py` / `test_formalgw_toolchain.py` / `test_formalgw_no_axioms_shortcircuit.py`） | 它们判的是**后端自己的词表与三态**（`verified` 才算 proof 等），与 `lean_enabled` 正交 ⇒ 不动（**它们应该继续全绿**，因为后端行为没变）。 |
| `agentflow/tests/test_toolchain_paths.py` / `test_settings.py` 的工具链部分 | 同族：判的是查找顺序与设置读取 ⇒ 只在加键时补一条用例，其余不动。 |
| `docs/PROPOSALS.md` / `docs/ROLE-SPECS.md` / 各 `NOAI-*.md` / `DESIGN-*.md` | **没逐条查到行号，不确定**它们里面有哪几条是"必须改"的硬口径。建议开关落地后单独扫一遍（尤其 `PROPOSALS.md` 有 129 处提及）。 |

### 顺便发现的**三处现存矛盾**（开关落地前建议先定口径）

1. **`formalgw` 的默认 `imports`**：`docs/FORMAL-TOOLCHAIN.md:78` 逐字写
   "`formalgw` 的 `imports` 默认是 `("Mathlib",)`"，而代码
   `verify_tools.py:432` 写的是 `imports=tuple(imports or ())`（**默认不注入任何库**），
   `specs/e.py:177`、`agent_prompts.py:1164`、`test_formalgw.py:530`
   （`test_the_default_imports_inject_nothing`）**全部站在"默认不注入"这一侧**。
   ⇒ `FORMAL-TOOLCHAIN.md:78` 是一句**陈旧文档**。
2. **本机 Mathlib 到底行不行**：`docs/FORMAL-TOOLCHAIN.md:130` 说"Mathlib 装了
   （4100 个 olean，`Mathlib.olean` 在）"，而 `docs/USER-TEST.md:154-155` 说
   "**Mathlib 那一档今天不行**（`import Mathlib` ⇒ `import_unavailable`：umbrella 的
   `.olean` 不在缓存里）"。两处日期不同（前者未标日期，后者是 2026-10-07 前后）。
   ⇒ **这正是 `toolchain._import_mathlib_probe` 那条真编译探针要解决的病**；开关的文案
   不该复制任何一处的结论，只能读现算读数。
3. **`DEVELOPMENT.md:1416` 与 `DESIGN-ROLES.md:292` 互相打脸**：前者说"本机无
   Lean/Coq/Isabelle"这一缺口"**已关闭（B8a）**：Mathlib 就位后真 Lean 四条控制
   实测 `fail=0`"，后者说"**E 的 `formal` 方法在本环境无法使用**（无 Lean/Coq）"。
   ⇒ 开关落地时这两处必须一起对齐。
