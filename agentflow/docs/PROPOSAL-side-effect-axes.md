# PROPOSAL：把 `side_effect` 拆成两根正交轴（`effect` × `external`）

> **本文是提案，不是判据。** 它不改任何代码，也不替人做决定。
> 目的只有一个：把一份**已经定好的设计**落成可逐条人审的具体改动清单。
> 逐条结论都带 `文件:符号` 证据（**刻意不写行号** —— 本仓库并行开发下行号几十分钟就漂，
> 这是 `AGENTS.md` 的禁改区清单已经写下来的纪律）。
>
> **登记**：`docs/PROPOSALS.md` 的 **P-13**。
> **明确不改**：本方案若通过，命中的禁改区文件（`src/agentflow/tools/base.py`、
> `src/agentflow/tools/__init__.py`）必须由人编写或人逐行走查 + 2 名 reviewer，
> 见第 8 节。AI 不得代填 `reviewers`、不得新建/修改 `.noai-approvals.json`。

---

## 1. 结论摘要（先读这一节就够判断要不要继续读）

- 现在只有一根轴 `side_effect ∈ {none, read, write_local, network}`，它把**两个正交问题**
  压进了同一个取值：**能不能改我们拥有的东西**、**能不能触到我们不拥有的事**。
  于是每个取值都是**半个真话**。
- 拆成两根轴之后，**审批与沙箱策略可以推导**（`needs_approval(tool)` /
  `sandbox_required(tool)`），不必逐工具手写布尔位。
- 这不是审美问题：`verify.run_experiment`（既写我们自己的实验记录、又执行调用方给的脚本）
  一旦存在，一根轴**必须二选一**，另一个事实被丢掉。
- 迁移是**有删除步骤的**：`network` 作为遗留取值只活到 B3 结束，之后从词表里**删掉**。
- 判据是**对偶的一对**：`R006`（声明读却联网/起进程）新增对偶 `R010`（声明不执行却起子进程），
  并把 `DEVELOPMENT.md` 的 P7 从**单向**改成**双向**。
- **不提议**用 AST **推断**声明（那是已被否决的 N-4）；AST 只用来**核对**声明与代码是否一致。
  这个区别是全文最关键的一句，见第 3.5 节与第 9 节①。

---

## 2. 核心判断：一根轴上的每个取值都是半个真话

### 2.1 两根轴的定义（受控词表）

| 轴 | 问题 | 取值 | 含义 |
|---|---|---|---|
| `effect` | 它能不能改**我们拥有**的东西？ | `none` | 不读也不写 |
| | | `read` | 只读我们拥有的东西（表 / 工作区） |
| | | `write_local` | 写我们拥有的东西（表 / 工作区） |
| `external` | 它能不能触到**我们不拥有**的东西？ | `none` | 触不到 |
| | | `egress` | **出网** |
| | | `exec` | 在宿主上执行一个**由调用方决定内容**的程序 |

两根轴的取值**互相独立**：`write_local × exec`（`verify.run_experiment`）
与 `none × exec`（`verify.check_formal`）都必须能被**如实**表达 —— 这正是现在做不到的事。

### 2.2 现状：每个取值都在一个方向上撒谎

| 现状取值 | 它说了什么 | 它瞒了什么 |
|---|---|---|
| `none` | 不改我们的东西 | 也不碰别人的东西（对 `verify.detect_verifier` 早期声明成立过，实际会起进程） |
| `read` | 只读我们的东西、**不需审批** | 可能已经出网 / 起了子进程（P7 的原始形态） |
| `write_local` | 写我们的东西、需审批 | 可能同时执行了调用方给的脚本（`verify.run_experiment`） |
| `network` | "会做本框架管不住的事"（一个**兜底**档） | 分不清是"出网"还是"起进程"；对纯本地的内核检查器是**假话** |

### 2.3 证据一：`verify.check_formal` 一根轴上怎么填都是假话

- **对我们的数据契约**：它是只读的 —— 源码走内存时桥接层只建
  `tempfile.TemporaryDirectory`（跑完即删），工作区字节不变；
  见 `src/agentflow/tools/verify_tools.py::check_formal` 的"副作用"一节。
- **对宿主**：它真的起检查器子进程（`formalgw._default_run` 是 `subprocess.run`，
  起的是 `lean` / `coqc` / `isabelle`）。
- 上一轮被迫填成 `network`（能力层）：
  `src/agentflow/capabilities.py::CAPABILITIES["E"]` 里 `check_formal` 的 `side_effect="network"`，
  理由是"唯一不撒谎的值"——**但它在审计口径上仍然在撒谎**：
  审计问"哪些动作会出网"，会把一个**纯本地的内核检查器**列进去（它不联网）。
- 反过来，工具层对同一个能力声明的是 `read`：`src/agentflow/tools/verify_tools.py`
  里 `verify.check_formal` 的 `side_effect="read"`。
  **同一个动作在两个文件里有两个不同的估值** —— 这不是谁写错了，
  是**一根轴装不下两个事实**的必然结果。
- `DEVELOPMENT.md` 的 **P7** 给出的处置是"声明成 `network`（或**新增『执行进程』档**）"。
  本方案选的正是括号里那一条，且把它做成**一根独立的轴**而不是词表里的第五个值（见第 9 节③）。

### 2.4 证据二：`verify.run_experiment` 是"既写、又执行"

`src/agentflow/tools/verify_tools.py` 里 `verify.run_experiment` 声明 `write_local`，
而它实际做两件事：

1. **写我们自己的实验记录**：登记一行 `experiments`（`WRITE_SETS["E"]` 就是 `{"experiments"}`）；
2. **执行调用方给的脚本**：`src/agentflow/agent_e.py` 里 `AgentE.run_experiment` 用
   `subprocess.run(...)` 跑工作区内的脚本，且**子进程继承完整环境**
   （`verify_tools.py` 里该工具的注释逐字登记了这一点）。

=> 一根轴上必须二选一，**另一个事实被丢掉**。
**这一类工具一出现，拆轴就不是审美问题。**

> P-6 已经把这件事登记成"应为 `network`"，但 P-6 的落点是**改一个取值**，
> 而它真正的问题是**一个取值不够用**。P-13 是 P-6 的结构性版本，不是它的重复。

### 2.5 证据三：拆轴之后策略可以**推导**，不必逐工具手写

| 策略 | 推导规则 |
|---|---|
| 进沙箱 | `external != "none"` => 禁网 + CPU / 内存 / 时间限额 |
| 人工审批 | `external == "exec"` 且沙箱不可用 => 走人工审批 |
| 不需要审批 | `external == "none"` 且 `effect != "write_local"` |

两个直接后果：

1. **比"一律要审批"更有用**：出网但不起程序的东西（`search.literature`）在沙箱里
   可以免人工审批地跑，而起程序的东西（`check_formal`）在沙箱缺位时**必须**签字。
2. **`check_formal` 的串行代价可以撤掉**：现在它因为被填成 `network`
   （`capabilities.SIDE_EFFECTS` 的"会做管不住的事"档）而与所有角色串行
   （`_WRITE_LIKE` 把它算成写者）。沙箱就位后，`external == "exec"` 由沙箱承接，
   它就**不该再进 `_WRITE_LIKE`**，串行代价随之消失。

---

## 3. 具体改动（逐项：改哪个文件的哪个符号、改什么、为什么）

### 3.1 `ToolSpec` 加 `external`，词表与 `SIDE_EFFECTS` **同一处声明**

- **改哪里**：`src/agentflow/tools/base.py::ToolSpec`（加字段 `external: str = "none"`）
  与 `src/agentflow/tools/base.py::ToolSpec.__post_init__`（加一条取值受控校验）。
- **词表来源只有一份**：在**同一个文件** `src/agentflow/tools/base.py` 里新增
  `EXTERNAL = ("none", "egress", "exec")`，与既有的 `SIDE_EFFECTS` 并排。
  **不许**在别的文件里再写一份取值清单（FC-03）。
- **为什么**：`SIDE_EFFECTS` 与 `external` 的取值都是**跨模块字符串约定**，
  分叉的症状不是崩溃而是"两套说法都自洽"。既有的交叉断言
  （`src/agentflow/capabilities.py::assert_capabilities` 第 5 条：
  `assert set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`）就是这条纪律的既有形态，
  新增的轴要沿用同一种形态而不是发明新机制。
- **`to_dict()` 必须带上它**：`src/agentflow/tools/base.py::ToolSpec.to_dict`
  现在输出 `side_effect` / `needs_approval`，要加 `external`。
  理由：`to_dict` 是 `cli.cmd_tools`、`ROLE-SPECS.md` 的 §R0 表、
  以及人类审计读的那一份，**它看不见的事实等于不存在**。

### 3.2 兼容与迁移：`network` 是**遗留取值**，用显式翻译表，不许静默重解释

- **改哪里（声明层）**：`src/agentflow/tools/__init__.py::SIDE_EFFECTS_WRITE`
  与 `src/agentflow/tools/base.py::SIDE_EFFECTS` / `NEEDS_APPROVAL` 所在的那一处词表区，
  新增一张**显式翻译表**（例如 `LEGACY_SIDE_EFFECTS = {"network": ("egress", "none")}`，
  语义是 `(external, effect)`）。
- **翻译表要说清三件事**：`network` => `external="egress"` + `effect="none"`；
  它**只在兼容期有效**；用到它的地方必须**逐条列出来**（见 3.2 的计数要求）。
- **不许静默重新解释**：迁移期里，一个声明了 `network` 的工具**不改变行为**
  （仍然需要审批），但**必须被数出来**。
- **lint 报一条 `info` 列出还剩多少处遗留**：在 `scripts/lint_rules.py` 里新增一条
  （见 3.6 的 R010 相邻项），内容是"全仓还有 N 处 `side_effect=network`，它们
  由翻译表承接；N 必须单调降到 0"。理由与本仓库 R007 的形态一致：
  一个**不可行动的数字**没有价值，所以这条 `info` 要给出**清单**（文件:符号）而不只是数字。
- **[注意] 这是一个删除步骤，必须写进方案**：B3 结束时 `network` 要从
  `SIDE_EFFECTS`（工具层）与 `capabilities.SIDE_EFFECTS`（能力层）里**删掉**，
  同时删掉翻译表本身。**只增不减的迁移不是迁移，是把第二个词表永久留在仓库里。**
- **两处词表必须同时删**：`src/agentflow/capabilities.py::SIDE_EFFECTS`
  与 `src/agentflow/tools/base.py::SIDE_EFFECTS` 由
  `assert_capabilities` 第 5 条**逐字**比对，只删一处会**导入期就炸**。
  这条约束是好事（它让"删一半"不可能静默），但排期上必须知道它们是**一个原子改动**。

### 3.3 派生策略（函数级描述，不写代码）

**`needs_approval(tool)`** —— 从两根轴推导，不再查一张取值表：

```
needs_approval(tool) =
      (tool.effect == "write_local")
   or (tool.external == "exec" and not sandbox_available())
```

- `external == "egress"` **不**单独构成审批理由：沙箱（禁网）能承接它。
- 沙箱不可用时**只有** `exec` 升级为审批；`egress` 在没有沙箱时同样升级为审批
  （此时它没有任何承接手段）—— 这一条实现时必须写成一个**显式三态**
  （沙箱可用 / 不可用 / **未声明**），因为"没声明沙箱"与"声明了沙箱正在用"
  折叠成同一个布尔，正是本仓库三态纪律禁止的形态
  （`DEVELOPMENT.md` §3 纪律 1）。

**`sandbox_required(tool)`** —— 纯推导，无例外：

```
sandbox_required(tool) = (tool.external != "none")
```

**`for_role` 的剥离规则** —— `src/agentflow/tools/base.py::ToolRegistry.for_role`：

在既有"只读角色剥掉写工具"之外，**再加一条**：

```
role ∈ READ_ONLY_ROLES  =>  还要剥掉 external == "exec"
                           除非沙箱被声明为可用
```

- **为什么**：只读角色（`READ_ONLY_ROLES = ("C", "H")`，
  见 `src/agentflow/tools/__init__.py::READ_ONLY_ROLES`）的语义是
  "它在结构上不能改世界"。**执行一个由调用方决定内容的程序**改变了世界
  （它能写工作区、能出网、能起更多进程）—— 所以它是与"能改表"同族的东西，
  不属于只读角色的能力面。
- **必须留痕**：被剥掉的名字要继续记进 `ToolRegistry.role_filter_notes`
  （`src/agentflow/tools/base.py::ToolRegistry.role_filter_notes`），
  理由与既有的写工具剥离**逐字相同**：静默过滤会让**声明错误**永远暴露不了。
- **沙箱可用时放行**：判据是"沙箱承接了这次执行"，不是"这个工具变安全了"。
  因此放行时也应当留痕（"因为沙箱可用而放行"），否则"为什么 H 拿到了一个 exec 工具"
  在报告里不可见。

**H 的那个窄口子必须重新审一遍** —— `src/agentflow/agent_h.py::_H_WRITABLE_TOOLS`：

- 现状：`_H_WRITABLE_TOOLS = ("review.review_document", "review.verify_fixes", "review.report")`，
  判据是 `t["side_effect"] in SIDE_EFFECTS_WRITE`
  （`src/agentflow/agent_h.py::AgentH.__init__` 里的落库代理断言）。
- 新轴下这条判据**会变宽**：一个 `effect="none"` + `external="exec"` 的工具
  **不在** `SIDE_EFFECTS_WRITE` 的派生结果里，于是它可能悄悄落进 `writers`。
- 因此落库代理的断言必须**显式改判据**：`writers` 里既不许有 `write_local`，
  也不许有 `external != "none"`。**这是一个待人在 B3 逐条核的清单**，
  不是可以顺手带过的改动（见第 8.2 节的"只读角色受影响清单"）。

### 3.4 交叉断言（让两根轴保持诚实的机制）

- **断言一**：`WRITE_SETS[role] != ∅ => 该角色的 effect == "write_local"`。
  落点：`src/agentflow/capabilities.py::assert_capabilities`（新增一条，与既有第 4 条并列）。
- **断言二**（轴的两份声明不许分叉）：`capabilities.EXTERNAL == tools.base.EXTERNAL`
  与 `capabilities` 侧的 `effect` 词表 == `tools.base.EFFECT`，
  形态照抄既有第 5 条（`assert set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`）。
- **为什么必须同时人审**：**声明与实现分处两地**是本仓库既有的纪律，
  `AGENTS.md` 的 auth-audit 类对 `tools/base.py` 的理由逐字是
  *"`for_role` 的结构性过滤 …… 它是**实现**，与上面的**声明**分处两文件，两者必须同时人审"*，
  而对 `tools/__init__.py` 的理由是
  *"`ROLES` 的引入、`READ_ONLY_ROLES` 与 `SIDE_EFFECTS_WRITE`：只读角色（C/H）的权限面单一来源"*。
  新加的轴落在**同样的两个文件**上 => 沿用**同样的**人审要求（2 名 reviewer）。

### 3.5 判据：新 R010（R006 的对偶）+ 双向一致性

**R010 的两条规则**（落点 `scripts/lint_rules.py`，与 `rule_R006_read_tool_touches_network` 并列）：

| 规则 | 判据 | 级别 | 为什么这个级别 |
|---|---|---|---|
| R010-a | 声明 `external != "exec"` 而 handler 里出现**起子进程**的调用 | **error** | 这是"声明与代码不符"的**确定**形态：声明说"我不执行程序"，代码在 `subprocess.run` / `Popen` / `os.system`。它直接决定审批与沙箱是否生效 => 必须挡 |
| R010-b | 声明 `external == "egress"` 而**全文没有任何网络调用** | **warning** | 可能只是**保守或临时**标注（"这个后端联网与否取决于配置"）。warning 而非 error，是因为本仓库有"假报警训练人忽略告警"的成文教训（`DEVELOPMENT.md` §6 的 **P15**） |

**R010 的两条校准（必须与既有 R006 的校准放在一起读）**：

1. R006 现在是**文件级共现**、级别 `info`、每个文件一条
   （`scripts/lint_rules.py::rule_R006_read_tool_touches_network`）。
   它的**实际敏感度被低估了很久**：实测快照里它只命中 6 个文件，
   而 `src/agentflow/tools/search_tools.py`（三个 `network` 工具，真的发 HTTP）
   **一次都不出现** —— 因为它的判据要求文件里同时有 `side_effect="read"` 的声明。
   => **一个真会出网的文件，因为"没有读工具"而完全不在 R006 的输出里。**
   这正是"声明与代码不符只查了一个方向"的具体形态。
2. R010 的方向必须与 R006 **相反**才有价值：R006 问"声明读、实际联网/起进程"，
   R010 问"声明不执行、实际起子进程"。两条一起才构成**双向**。

**正控与负控（每条规则各一，落点 `tests/`）**：

| 对象 | 正控（必须命中） | 负控（必须不命中） |
|---|---|---|
| R010-a | 一个声明 `external="none"` 而 handler 里 `subprocess.run` 的合成样本 | 声明 `external="exec"` 且确实起子进程的合成样本（**不许**因为"起了进程"就报） |
| R010-b | 声明 `external="egress"` 而全文无网络标记的合成样本 | 声明 `external="egress"` 且有真实 HTTP 调用的合成样本 |

**P7 从单向改成双向**（落点 `DEVELOPMENT.md` 的禁止模式清单 P7 那一行）：

- 现在 P7 只写了一个方向："**声明 `side_effect="read"` 却联网 / 起子进程 / 下模型**"。
- 改成双向之后要同时写另一个方向："**声明不执行（`external != "exec"`）却在起子进程**"
  与"**声明出网（`external == "egress"`）却全文无网络调用**"。
- 为什么这条改动是必要的：单向的判据会让人把"我声明得保守一点"当成安全行为，
  而**保守的假话仍然是假话** —— 审计问"哪些工具会出网"时会把不联网的工具列进去。

**[注意] 声明 vs 代码的一致性校验：AST 只用来核对，不用来生成**（这一句必须逐字读）

- **本方案主张的**：给每个 `ToolSpec` **人写**的 `external` 声明，配一条
  **AST 核对**：把 handler 的源码解析出来，检查"代码里有没有起子进程 / 出网的调用"
  与**人写的那条声明**是否一致。AST 的作用是**发现不一致**，
  不一致时**人**去改声明或改代码。
- **本方案不主张的**：用 AST **推断**出 `external` / `side_effect` 的取值，
  然后写进 `ToolSpec`（或据此判"声明撒谎"）。
- **为什么这个区别是本质的**：N-4 否决的正是后者，理由逐字保留在第 9 节①。
  用 AST **生成**声明会继承 N-4 实测出来的两个缺陷（22/55 取不到源码、
  9 个转发型 handler 的假阳性）；而用它**核对**声明，那两个缺陷的形态完全不同：
  取不到源码 => 这条工具**本次没核对**（三态里的 `unknown`，必须报出来），
  转发型 handler => 核对对象是它**转发到的那个函数**（由人决定看不看），
  两者都是"没查成 / 待人工"，**不是**"判它撒谎"。

### 3.6 分批落地与验收

每批都给：改什么、验收命令、退出码、可判定判据。

#### B1 词表与派生策略（含遗留翻译表、交叉断言）

- **改什么**：
  - `src/agentflow/tools/base.py`：`EXTERNAL` / `EFFECT` 词表、`ToolSpec.external`、
    `__post_init__` 的取值校验、`to_dict()` 加 `external`、
    `needs_approval` / `sandbox_required` 的派生实现、
    `for_role` 的 `exec` 剥离与留痕；
  - `src/agentflow/tools/__init__.py`：`SIDE_EFFECTS_WRITE` 的判据来源、
    遗留翻译表、`__all__`；
  - `src/agentflow/capabilities.py`：`SIDE_EFFECTS` 的对应轴、交叉断言（3.4）。
- **验收命令**：`python -c "import agentflow.capabilities"`（退出码 0 = 导入期断言全过）
  与 `python -m pytest tests/test_tools_base.py tests/test_tools_readonly_roles.py -q`。
- **可判定判据**：
  1. **导入期断言通过**（退出码 0）。任何一条轴的分叉都会让它以 `AssertionError` 退出。
  2. [重点] **`for_role` 的行为对既有工具逐字不变**：用**既有**测试证明，而不是新写一条
     "我觉得应该一样"的测试。具体是
     `tests/test_tools_readonly_roles.py::test_real_registry_gives_no_write_tool_to_read_only_roles`
     （C/H 的工具面 0 个写工具 + 每侧都非空）与
     `tests/test_tools_readonly_roles.py::test_no_role_filter_notes_when_declarations_are_correct`
     （声明正确时 `role_filter_notes` 为空）**继续通过**。
     [注意] 这一条有个**已知的前置**：见第 10 节"与事实冲突"第 3 条。
  3. 遗留计数可读：一条命令列出"还有 N 处 `network`"，N 的值在本批**允许非 0**。

#### B2 判据 R010 与双向一致性

- **改什么**：`scripts/lint_rules.py` 加 R010-a（error）/ R010-b（warning）
  与遗留计数那条 `info`；`DEVELOPMENT.md` 的 P7 改双向。
- **验收命令**：`python scripts/lint_rules.py`（退出码 **0**，且 `error` 数为 0）
  与 `python -m pytest tests/test_lint_rules.py -q`。
- **可判定判据**：
  1. **正控/负控各一**（第 3.5 节的四格表），四条都要在 `tests/test_lint_rules.py` 里有名字。
  2. R006 **不许被改宽或删掉**：它现在报 `info`，B2 之后**仍然是 `info`**、命中文件集合
     **不许变多**（改宽它就是制造噪音，见 P15）。

#### B3 逐个迁移实际声明，最后**删除** `network`

- **改什么**（迁移清单见第 4 节）：`src/agentflow/tools/search_tools.py`
  （`search.providers` / `search.literature` / `search.download`）、
  `src/agentflow/tools/ocr_tools.py`（`ocr.run`）、
  `src/agentflow/tools/verify_tools.py`（`verify.run_experiment` 加 `exec`、
  `verify.detect_verifier` 的 `external` 取值待判 —— 见第 10 节冲突 1 与第 4.3 节第 8 条）、
  `src/agentflow/capabilities.py`（`A.run_once` / `A.run` / `E.check_formal`）、
  以及 `docs/ROLE-SPECS.md` 的 §R0 表（见第 7.4 节）。
- **删除步骤（这是本批的重点）**：
  1. 从 `src/agentflow/tools/base.py::SIDE_EFFECTS` 删掉 `"network"`；
  2. 从 `src/agentflow/capabilities.py::SIDE_EFFECTS` 删掉 `"network"`（**同一原子改动**）；
  3. 删掉遗留翻译表本身；
  4. 删掉 lint 的遗留计数那条 `info`（**它已经没有对象可数了**）。
- **可判定判据（"迁移完成"的定义，两条都要满足）**：
  1. **lint 的遗留计数为 0**：那条 `info` 报 `0` 处，或（第 4 步之后）**该条规则已被删除**；
  2. **词表里已无该值**：一条命令断言
     `"network" not in agentflow.tools.base.SIDE_EFFECTS` **且**
     `"network" not in agentflow.capabilities.SIDE_EFFECTS`，退出码 0。
  3. **回归 0**：`python -m pytest -q` 全绿；`python scripts/lint_rules.py` 退出码 0。
- **验收命令**（三条，逐条给退出码）：

  | 命令 | 期望退出码 |
  |---|---|
  | `python -m pytest -q` | 0 |
  | `python scripts/lint_rules.py` | 0（`error` 数必须为 0） |
  | `python -c "from agentflow.tools.base import SIDE_EFFECTS as A; from agentflow.capabilities import SIDE_EFFECTS as B; assert 'network' not in A and 'network' not in B"` | 0 |

---

## 4. 迁移清单（B3 逐条，**逐工具人核**）

### 4.1 现状实测（快照，命令可复跑）

```powershell
python -c "import sys; sys.path.insert(0,'src'); from agentflow.tools import ROLES, build_registry;
from agentflow import store as S; from pathlib import Path; import tempfile; from collections import Counter;
td=tempfile.mkdtemp(); st=S.Store(Path(td)); st.init();
reg=build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry;
print(dict(Counter(s.side_effect for s in reg._specs.values())), len(reg))"
```

实测输出（**本提案写作时的原始输出**）：

```text
SIDE_EFFECT counts: {'read': 30, 'write_local': 16, 'network': 4, 'none': 5} total 55
network tools: ['ocr.run', 'search.download', 'search.literature', 'search.providers']
needs_approval count: 20
```

能力层（`agentflow.capabilities.CAPABILITIES`）实测：

```text
capability side_effect counts: {'network': 3, 'write_local': 25, 'read': 19, 'none': 1}
unknown: []
network: [('A', 'run_once'), ('A', 'run'), ('E', 'check_formal')]
```

### 4.2 逐条翻译（`network` => `external="egress"` + `effect` 按事实填）

| # | 声明处（`文件:符号`） | 现状 | 新值 | 依据 |
|---|---|---|---|---|
| 1 | `src/agentflow/tools/search_tools.py` 的 `search.providers` | `network` | `effect="read"` + `external="egress"` | 它真的发 HTTP 探测各源；**不改我们的表** |
| 2 | 同上 `search.literature` | `network` | `effect="read"` + `external="egress"` | 检索候选，不落库（落库是 `search.register` 的 `write_local`） |
| 3 | 同上 `search.download` | `network` | `effect="write_local"` + `external="egress"` | 它**写工作区**（下到 `downloads/`）**且**出网 => 两根轴都非 `none`。[注意] 这是"旧词表把它压成 `network`、于是写的事实被丢掉"的第三个实例 |
| 4 | `src/agentflow/tools/ocr_tools.py` 的 `ocr.run` | `network` | `effect="write_local"` + `external="egress"` | 首次构造 easyocr Reader 会**下载 ~100MB 模型**（写到工作区外，`~/.EasyOCR`）；按现状的口径它是"工作区外 mkdir"=> 归 `write_local`（与 `ocr.backends` 同口径） |
| 5 | `src/agentflow/capabilities.py` 的 `A.run_once` / `A.run` | `network` | `effect="write_local"` + `external="egress"` | 它们写 `search_requests` + `literature`（`WRITE_SETS["A"]`），**且**要跑联网检索 |
| 6 | `src/agentflow/capabilities.py` 的 `E.check_formal` | `network` | `effect="read"` + `external="exec"` | 见 2.3；`PROPOSALS.md` 的 N-2 也逐字登记了这条"待收窄的声明" |

### 4.3 不是 `network` 但**必须一起看**的（`external` 非 `none`）

| # | 声明处 | 现状 | 新值 | 依据 |
|---|---|---|---|---|
| 7 | `src/agentflow/tools/verify_tools.py` 的 `verify.run_experiment` | `write_local` | `effect="write_local"` + `external="exec"` | 见 2.4；`agent_e.py` 的 `subprocess.run` |
| 8 | 同上 `verify.detect_verifier` | `read` | **待判**（`effect="read"` + `external` ∈ {`none`, `exec`}） | 它 `shutil.which` + `subprocess.run` 起外部二进制的 `--version`。**命令内容是工具自己写死的，不是调用方给的** => 按轴的**字面定义**（`exec` = "执行一个由调用方决定内容的程序"）它落到 `none`；但 lint 的字面判据（"出现起子进程的调用"）会把它命中 => 见第 10 节第 1 条，**这是本方案里最需要人裁的一处** |
| 9 | `src/agentflow/tools/ocr_tools.py` 的 `ocr.backends` | `write_local` | `effect="write_local"` + `external="exec"` | 它**起进程**（`tesseract --version`）**且**在工作区外建目录。[注意] 现在它因为 `write_local` 而需要审批，**拆轴后审批理由要说清是哪一根轴**（这里是两根） |
| 10 | `src/agentflow/capabilities.py` 的 `F.step` | `write_local` | `effect="write_local"` + `external="exec"` | `docs/ROLE-SPECS.md` §R0 对 `attack.step` 的"已知问题"列逐字写着：*"经 `_deploy_e` 跑 E 的脚本子进程（**声明里没有『执行进程』这一档**）"* |

---

## 5. 审批面变化（**必须先算清楚再动手**）

拆轴会改变**哪些工具需要审批**。这份清单是 B1 的验收证据之一。

| 工具 | 现在 `needs_approval` | 新轴下 | 变化 |
|---|---|---|---|
| `search.providers` / `search.literature` | 是（`network`） | `effect=read` + `external=egress` => **沙箱可用时否、沙箱不可用时是** | 取决于沙箱声明 |
| `search.download` / `ocr.run` | 是 | `effect=write_local` => **是**（与沙箱无关） | 不变 |
| `verify.run_experiment` | 是（`write_local`） | `effect=write_local` => **是** | 不变 |
| `verify.check_formal` | **否**（工具层 `read`） | `external=exec` => 沙箱不可用时**是** | [注意] **变严** |
| `verify.detect_verifier` | 否 | 取决于第 10 节第 1 条的裁决 | 待定 |
| `ocr.backends` | 是 | 是 | 不变 |

=> **唯一确定会变严的是 `verify.check_formal`**。而它恰好是那个"保守填 `network`
仍然在撒谎"的工具 —— 变严是**如实**的代价，不是错误。

[注意] 这条会撞到**既有测试**（B1 的验收必须知道）：

- `tests/test_tools_audit_fixes.py::test_detect_verifier_side_effect_is_read_and_checked_is_honest`
  断言 `verify.detect_verifier` 的 `needs_approval is False`；
- `tests/test_tools_audit_fixes.py::test_side_effect_search_providers_declares_network`
  断言 `search.providers` 的 `side_effect == "network"`（**遗留取值阶段必须继续绿**，
  这正是"遗留翻译表不许静默重解释"的验收）；
- `tests/test_tools_base.py::test_toolspec_needs_approval_tracks_dangerous_side_effects`
  断言 `sp("network").needs_approval is True`；
- `tests/test_tools_readonly_roles.py::test_side_effect_vocabulary_is_the_single_source`
  断言 `set(SIDE_EFFECTS_WRITE) == {"write_local", "network"}`。

=> 这四条断言**编码的是旧词表**。B3 必须逐条改，且**改法要写明"这条断言编码的是遗留行为，
不是设计意图"**（否则下一个人会以为有人放宽了断言来掩盖失败）。

---

## 6. 为什么不由 AI 独自完成（禁改区）

`AGENTS.md` 的 FC-27 清单把本方案要动的两个文件**已经登记在案**：

| 文件 | 类别 | 清单理由（逐字） |
|---|---|---|
| `src/agentflow/tools/__init__.py` | `auth-audit` | `ROLES` 的引入、`READ_ONLY_ROLES` 与 `SIDE_EFFECTS_WRITE`：只读角色（C/H）的权限面单一来源 |
| `src/agentflow/tools/base.py` | `auth-audit` | `for_role` 的结构性过滤：只读角色一律拿不到写工具 —— 它是**实现**，与上面的**声明**分处两文件，两者必须同时人审 |

**判定**：新增一根轴 = **改变权限面的判据本身**（`needs_approval` 的推导来源、
`for_role` 的剥离条件）。这与 P-1 的理由同族：
*"把校验从装配期挪到注册期，改变的是权限面的失败时点，而失败时点正是『越权』
这类不可逆错误发生的窗口"*。=> 需要**人编写或人逐行走查 + 2 名 reviewer**。

**不在禁改区但属规范变更**（仍须人审，因为它是判据本身）：

| 文件 | 为什么仍需人审 |
|---|---|
| `src/agentflow/capabilities.py` | 交叉断言的落点；`WRITE_SETS` 与 `effect` 的对应关系是并发判据的输入 |
| `scripts/lint_rules.py` | 新增 error 级判据 = 改门的强度 |
| `docs/ROLE-SPECS.md` | §R0 表的三列有**机器比对**（见第 7.4 节），改列结构会同时改判据 |
| `docs/DEVELOPMENT.md` | P7 从单向改双向 = 改禁止模式清单的判据 |

---

## 7. 人审包

### 7.1 禁改区文件与逐一行走查的符号

| 文件（禁改区） | 必须逐行走查的符号 |
|---|---|
| `src/agentflow/tools/base.py` | `SIDE_EFFECTS`、新增 `EXTERNAL` / `EFFECT`、`NEEDS_APPROVAL`、`ToolSpec`、`ToolSpec.__post_init__`、`ToolSpec.needs_approval`、`ToolSpec.to_dict`、`ToolRegistry.for_role`、`ToolRegistry.role_filter_notes`、`tool()` 装饰器 |
| `src/agentflow/tools/__init__.py` | `ROLES` 的引入、`READ_ONLY_ROLES`、`SIDE_EFFECTS_WRITE`、遗留翻译表、`__all__`、`build_registry` 的装配期断言 |

**非禁改区但必须人看**：`src/agentflow/capabilities.py::assert_capabilities`（新增两条断言）、
`src/agentflow/capabilities.py::WRITE_SETS` / `READ_ONLY_WRITE_EXCEPTIONS`、
`src/agentflow/agent_h.py::_H_WRITABLE_TOOLS` 与 `AgentH.__init__` 的落库代理断言、
`scripts/lint_rules.py::rule_R010_*` 与遗留计数、`docs/ROLE-SPECS.md` §R0 的列结构、
`docs/DEVELOPMENT.md` 的 P7 行。

### 7.2 批准前**必须由人亲自跑**的命令（AI 的输出不算证据）

| # | 命令 | 期望 | 它证明什么 |
|---|---|---|---|
| 1 | `python -c "import agentflow.capabilities"` | 退出码 0 | 交叉断言真的接上了（导入期） |
| 2 | `python -m pytest tests/test_tools_readonly_roles.py tests/test_tools_base.py -q` | 全绿 | B1 的"`for_role` 行为逐字不变" |
| 3 | `python scripts/lint_rules.py` | 退出码 0，`error` 0 | B2 的 R010 没有把真实树打红 |
| 4 | 一条列出"还剩多少处 `network`"的命令 | 数字 + 清单 | B3 的迁移进度（**可判定的分母**） |
| 5 | `python scripts/noai_gate.py --paths src/agentflow/tools/base.py src/agentflow/tools/__init__.py` | 退出码 **1** + `required_approvals=2` | 门**确实**把这两个文件认成禁改区（"没报错"不等于"没问题"） |

### 7.3 台账纪律

- **AI 不得代填 `reviewers`**：`.noai-approvals.json` 在禁改区（auth-audit），
  且清单理由逐字写着 *"台账**不能批准自己**（理由码 `ledger_self_approval`），
  且 `--baseline` 永远不写 `reviewers`（登记 ≠ 批准）"*。
- 本提案**没有**新建、没有修改 `.noai-approvals.json` —— 这是刻意的。
- 2 名 reviewer 是 FC-27 的 `REQUIRED_APPROVALS_ON_HIT`，不是建议值。

### 7.4 `docs/ROLE-SPECS.md` §R0 的机器比对（**改表就是改判据**）

§R0 的 55 行表有三列是**机器可判定**的（`side_effect` / 审批 / roles），
由 `tests/test_role_specs_complete.py::_r0_rows` 解析。[注意] **它按固定列下标取**：

```text
"side_effect": cells[3], "needs_approval": cells[4], "roles": cells[5]
```

=> **在 `side_effect` 右侧插入 `external` 一列会把这三列的语义整体挪一格**，
门会以"文档与注册表不一致"的形式报红（而真正的原因只是列错位）。
所以 B3 改表时必须**同时**改 `_r0_rows` 的下标，并把这件事写进人审清单 ——
否则下一个人会把它诊成"有人改坏了文档"。

---

## 8. 风险与反驳

### 8.1 风险一：跨 4 个文件的词表变更，blast radius 大

- **事实**：`SIDE_EFFECTS` 出现在 `tools/base.py`、`tools/__init__.py`（`SIDE_EFFECTS_WRITE`）、
  `capabilities.py`，而它的**消费者**至少还有 `agent_h.py`（落库代理断言）、
  `cli.py`（`cmd_tools` 按 `SIDE_EFFECTS_WRITE` 统计与 `role_filter_notes` 打印）、
  `docs/ROLE-SPECS.md`（§R0 三列）、`tests/`（4 条编码旧词表的断言，见第 5 节）。
- **对策**：①遗留翻译表（3.2）—— 迁移期**行为不变**，只把事实**分开记**；
  ②分批（B1/B2/B3）+ 每批 0 回归；
  ③**两处词表的删除是原子的**（`assert_capabilities` 第 5 条会在删一半时导入期就炸）。
- **反驳一个可能的反对意见**："那不如保持 `network` 再补一个"是否认"布尔位"。
  见第 9 节②。

### 8.2 风险二：只读角色被剥 `exec` 可能削掉 C/H 的现有能力

- **事实**：`for_role` 现在只按 `side_effect in SIDE_EFFECTS_WRITE` 剥。
  新轴下 `external == "exec"` 的工具（沙箱不可用时）会被剥掉。
- **对策：逐个工具核，列出受影响清单**。实测的候选清单（`roles` 里含只读角色
  且 `external` 会是 `exec` 的）：

  | 工具 | `roles` | 含只读角色？ | 结论 |
  |---|---|---|---|
  | `verify.detect_verifier` | E F G H | **是（H）** | 若判为 `exec` => **H 会失去它**。H 的工具面里会出现一个"少了两个工具"的缺口，而 H 的"证据等级有没有被夸大"这条审校恰恰要用它（`ROLE-SPECS.md` 的 H 节把它列在"证据只读侧"） |
  | `verify.check_formal` | E F G H | **是（H）** | 同上；[注意] 这一处必须在沙箱就位前先裁决 |
  | `verify.run_experiment` | E F G | 否 | C/H 本来就没有（`_ROLES_WRITE` 刻意排除 H） |
  | `ocr.backends` | B | 否 | 不影响只读角色 |
  | `attack.step` | F | 否 | 不影响 |
  | `A.run_once` / `A.run` / `F.step`（能力层） | — | — | 能力层的剥离判据在 `capabilities._WRITE_LIKE`，不在 `for_role`；本方案**只**改 `for_role`，**不动** `_WRITE_LIKE`（见第 9 节④） |

  => **受影响清单是"H 会少掉 `verify.detect_verifier` 与 `verify.check_formal`"**，
  这必须由人判断是否可接受（H 的审校要靠形式化证据的可核性）。
- **一条明确的替代口径（供人选择，本方案不替人选）**：沙箱就位后**放行**，
  因为"沙箱承接了这次执行"是结构性保证 —— 这正是 3.3 那条"除非沙箱被声明为可用"的用意。

### 8.3 风险三：沙箱未就位时 `exec` 全部要审批，会拖慢 E/F

- **事实**：E 的 `check_formal` 与 `run_experiment`、F 的 `step` 都会是 `exec`。
  沙箱不可用时它们全部进人工审批 => E/F 的循环会被打断（现在是"`write_local` 也审批"
  所以 E 的 `run_experiment` 本来就已经要审批；真正的**新增**只有 `check_formal`）。
- **对策：给出沙箱的**最小实现范围**与它解锁什么**：

  | 最小范围 | 具体做法 | 解锁什么 |
  |---|---|---|
  | 进程级限额 | 起子进程时设 `timeout`（现在 `formalgw.check_lean` 已有 `timeout_sec`，`agent_e` 的 `subprocess.run` 已有 `timeout`）+ 资源限额 | 让"起进程"不再等价于"无限占用宿主机" |
  | 禁网 | 子进程环境里去掉代理配置 / 显式阻断出网（`formalgw` 起检查器时**不需要**网） | `external == "egress"` 的 `check_formal` 之外的场景可免人工审批 |
  | 声明可用 | 一个**显式**的沙箱可用性声明（三态：可用 / 不可用 / **未声明**） | `needs_approval` / `for_role` 的放行分支才有判据，而不是靠"我们觉得有沙箱" |
  | 工作区边界 | 子进程 cwd 钉在工作区内，且不继承完整 `os.environ`（现在 `agent_e.py` 是 `env = dict(os.environ)`） | 让"exec 能碰到工作区外"这件事变成可陈述的事实 |

- **[注意] 沙箱的落点很可能也在禁改区**：`formalgw.py` 的 `_default_run` 与
  `agent_e.py` 的 `subprocess.run` 决定了子进程环境；`tools/verify_tools.py`
  在 `prover-bridge` 类（`detect_verifier` 与 `check_formal`）。
  => 沙箱**不是**一个 AI 能独自落地的附件，它也要人审。

---

## 9. 明确不提议的（写清楚，防止被当成遗漏）

### ① AST 自动**推断**声明 —— N-4 已否，理由逐字保留

`docs/PROPOSALS.md` 的 N-4 逐字记录（**保留原文，不改一个字的结论**）：

> **这个门不能上**。它有 **40% 的盲区**，而剩下的 60% 里还有一个**成规模的假阳性模式**。

其实测规模（`temp\_probe_side_effect.py`，55 个工具逐个跑）：

| 现象 | 规模 |
|---|---|
| 取不到或解析不了 handler 源码（注册成多行 lambda） | **22 / 55（40%）** |
| 声明 `write_local`/`network` 但函数体里没有任何痕迹（handler 只是转发到别处的 `_h_*`） | **9 个**（全部是假阳性） |

=> 本方案**不**提议用 AST 推断 `side_effect`/`external`。
本方案提议的是**核对**（3.5 结尾那一节），两者的区别在那一节逐字写清了。

### ② 每个工具加一堆布尔位

- **不提议** `is_sandboxed` / `needs_human` / `can_write` / `can_exec` 这类**逐工具**的布尔字段。
- **为什么**：这些位是**派生的**，而 `DEVELOPMENT.md` §3 纪律 6 逐字写着
  *"派生态不许当输入（**就地推导** 或 **装配期断言**，没有第三种）"*。
  逐工具手写布尔位的必然结局是"声明与行为分叉"，而那正是本方案要解决的问题本身
  （R006/P7 的整族缺陷）。
- 正确形态：**从两根轴推导**（3.3 的两个函数），派生结果**不落成字段**。

### ③ 把 `exec` 塞进 `side_effect` 当第五个值 —— **显式收回上一轮的临时建议**

- 上一轮的临时建议是"声明成 `network`（或新增『执行进程』档）"，
  出处是 `DEVELOPMENT.md` 的 **P7** 与 `src/agentflow/capabilities.py`
  里 `E.check_formal` 的注释（那里逐字写着"或新增『执行进程』档"）。
- **本方案显式收回它**，理由：把 `exec` 做成 `side_effect` 的第五个值
  **继续把两轴压在一根轴上**，只是把假话换成"还算能接受"的话。
  具体地说，`verify.run_experiment`（`write_local` + `exec`）在五值词表里
  **仍然只能二选一** —— 2.4 那个证据在五值方案下**原样成立**。
- 因此 `exec` 必须是**另一根轴**上的取值，而不是这一根轴上的第五个取值。

### ④ 把能力层的 `_WRITE_LIKE` 一起改掉

- `src/agentflow/capabilities.py::_WRITE_LIKE` 现在是
  `("write_local", "network", UNKNOWN_SIDE_EFFECT)`，它决定"谁与谁串行"。
- **本方案只改 `for_role` 的剥离判据，不动 `_WRITE_LIKE`**。
  理由：`_WRITE_LIKE` 喂的是**并发判据**，改它会改变调度行为；
  而"沙箱就位后 `check_formal` 的串行代价可以撤掉"（2.5 第 2 条）是一个
  **依赖沙箱存在**的后续决定，不该与词表变更捆在同一批里。
  => 这是一条**有意留到下一份提案**的取舍，不是遗漏。

---

## 10. 与事实冲突（读了代码之后发现设计与事实不符的地方，逐条写；**本方案不擅自调整设计**）

> 这一节的每一条都是"我读了代码/文档之后发现的与设计叙述不符之处"。
> **处置一律是"记在这里，由人裁"**，本方案没有为了让设计成立而改任何一条事实。

### 冲突 1（最重要）：`verify.detect_verifier` 在"exec 的字面定义"与"lint 的字面判据"之间

- **设计的定义**：`external == "exec"` = "在宿主上执行一个**由调用方决定内容**的程序"。
- **事实**：`src/agentflow/tools/verify_tools.py::detect_verifier` 起的是
  **工具自己写死**的命令（`_VERIFIER_CANDIDATES` 里的 `lean --version` /
  `coqc --version` / `isabelle version`），调用方**决定不了**跑什么。
  => 按定义它**不是** `exec`。
- **但**：设计要求的新 R010-a 判据是"声明 `external != "exec"` 而 handler 里出现
  **起子进程**的调用 => error"。`detect_verifier` 里真的有 `subprocess.run`
  => 按 lint 的**字面**判据，它**必须**是 `exec`，否则 lint 会在真实树上产生
  一条 **error**（而它其实不是 exec）。
- **为什么这不是小事**：这两个判据（轴的**定义** vs lint 的**字面判据**）
  必须同时成立，否则要么 lint 常红、要么定义被架空。
  两条可能的出路（**都不替人裁**）：(a) lint 的判据收窄成"起子进程**且**命令/脚本内容
  来自参数或调用方"（需要 AST 追数据流，难度高）；(b) 承认"起外部二进制"一律算 `exec`
  （于是定义要改写成"执行一个**我们进程之外**的程序"）。
- **已核实的相关计数器**：实测"handler 自身源码里含起进程/联网标记的工具"为
  **空集**（`[]`）—— 因为 `detect_verifier` 的 handler 是 `lambda: ok(detect_verifier())`
  （一行转发），标记在**被调用的模块级函数**里。
  => 这一条与 N-4 的"转发型 handler"是同一个形态（见冲突 5）。

### 冲突 2：设计与 `PROPOSALS.md` 的 P-6 是**同一件事的两种处置**

- **设计的证据 2** 把 `verify.run_experiment` 当成"必须拆轴"的证明。
- **事实**：`docs/PROPOSALS.md` 的 **P-6** 已经登记了它，处置是"改为 `network`
  并同步那条测试断言"，而 `src/agentflow/tools/verify_tools.py` 里该工具的注释
  逐字写着 *"待修：它跑的子进程继承完整环境 …… 严格说应当是 `network`。
  但 `tests/test_agent_e.py` 断言了 `write_local`"*。
- **冲突点**：P-6 的落点是**换一个取值**，而本方案的落点是**一个取值不够用**。
  两者**不能同时执行**（先按 P-6 改成 `network`，再按本方案拆轴，会多一次迁移）。
  => **排期冲突必须由人裁决**：建议的顺序是"先 P-13（拆轴），把 P-6 作废或改成 P-13 的一步"。

### 冲突 3：设计说 `check_formal` "上一轮被迫填 `network`"，需要区分**哪一层**

- **事实（实测，两层不一致）**：
  - **工具层**：`src/agentflow/tools/verify_tools.py` 的 `verify.check_formal` 声明 **`read`**
    （注释逐字解释："起了进程但只读"）；
  - **能力层**：`src/agentflow/capabilities.py` 的 `CAPABILITIES["E"]` 里 `check_formal`
    声明 **`network`**（长注释逐字解释"唯一不撒谎的值是 `network`"）。
- **冲突点**：设计的证据 1 只提到"上一轮被迫填 `network`"。
  如果按字面去找，会在**工具层找不到它**（那里是 `read`），
  而 lint 的 R006 也**只**看工具层 => 这条最贵的不一致**从来没有被任何机器判据看见**。
  => 拆轴要**同时**覆盖两层，且两层的现状不同（工具层从 `read` 变、能力层从 `network` 变）。
- **顺带的一处文档漂移（实测）**：`docs/PROPOSALS.md` 的 **N-2** 声称
  `E.check_formal` 的 `side_effect="unknown"` 是"唯一一个"，而实测
  `CAPABILITIES` 里 **`unknown` 的数量是 0**（`unknown: []`）——
  N-2 的"现状"已经过期（`capabilities.py` 里该条的注释自己也写了
  "本条此前是 `side_effect="unknown"` …… 现在读得出来了"）。本方案不改 N-2，仅登记。

### 冲突 4：`ToolSpec.__post_init__` **并不校验"六件套"**

- **任务/文档的叙述**：`docs/DEVELOPMENT.md` 的 §4.3 第 1 行说
  *"**六件套齐全**：`name / summary / params / returns / side_effect / roles`"*
  的检查者是 **`ToolSpec.__post_init__`** + 实测 census。
- **事实**：`src/agentflow/tools/base.py::ToolSpec.__post_init__` 只有**两条**校验 ——
  `side_effect in SIDE_EFFECTS` 与"工具名含 `.`"。`summary` / `params` / `returns` / `roles`
  既没有必填校验，也没有非空校验（它们都有 dataclass 默认值）。
  => "六件套齐全"这件事**不是**由 `__post_init__` 保证的，而是由 census 观察出来的。
- **冲突点**：本方案要在 `__post_init__` 里加"第七件"的校验（`external` 的取值合法性）。
  如果叙述把它当成"六件套校验的延伸"，会以为那里已经有一套结构校验 —— **没有**。
  => B1 实现时要在正确的位置加（加一条与 `side_effect` 并列的**取值**校验，
  而不是假装那里有"齐全性"校验）。

### 冲突 5：R006 的**实际敏感度**远低于叙述，而它是 P7 唯一的机器判据

- **叙述**：`DEVELOPMENT.md` 的 P7 与 `docs/PROPOSALS.md` 的 N-4 都把 R006 当成
  "声明与代码不符"的探测器。
- **事实（实测快照，可复跑 `python scripts/lint_rules.py`）**：R006 的判据要求
  **同一个文件里**既有 `side_effect="read"` 的声明、又有网络/子进程标记 ——
  它今天只命中 6 个文件，而且 `src/agentflow/tools/search_tools.py`
  （三个 `network` 工具，真的发 HTTP）**一次都不出现**。
- **冲突点**：设计与 P7 说"R006 存在的理由正是『声明与代码不符』，只是它只查了一个方向"——
  这个说法**成立但偏乐观**：它不只是"只查一个方向"，它的判据形态
  （**文件级共现**）还让"一个真出网的文件"因为**没有读工具**而完全不进输出。
  => R010 的判据必须**按工具**而不是按文件，否则会继承同一个盲区。
  **这一条不改变设计的目标，只是把"对偶"的落点说清楚。**

### 冲突 6：`capabilities.SIDE_EFFECTS` 与 `tools.base.SIDE_EFFECTS` 的**删除是一个原子改动**

- 设计的第 2 条要求"迁移完再把 `network` 从词表里删掉"。
- **事实**：`src/agentflow/capabilities.py::assert_capabilities` 第 5 条逐字断言
  `set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`，两处**必须逐字一致**。
- **冲突点**：于是"从词表里删掉该值"**不可能分批**（只删工具层 => 导入期就炸）。
  这是**好事**（删一半不可能静默），但排期叙述里若写成"最后删掉工具层的 `network`"
  会让执行者以为可以分两次。=> 正确写法是"**同一个原子改动里删两处 + 删翻译表**"。

### 冲突 7：拆轴会撞到 4 条**编码旧词表**的既有测试断言

- **事实**（第 5 节已列清单）：`tests/test_tools_audit_fixes.py` 的两条、
  `tests/test_tools_base.py::test_toolspec_needs_approval_tracks_dangerous_side_effects`、
  `tests/test_tools_readonly_roles.py::test_side_effect_vocabulary_is_the_single_source`
  都按**旧词表**断言（`sp("network").needs_approval is True`、
  `set(SIDE_EFFECTS_WRITE) == {"write_local", "network"}` 等）。
- **冲突点**：设计与任务叙述里写的是"B1 的验收：`for_role` 行为对既有工具逐字不变
  （用既有测试证明）"。**这句在 B3 阶段会失效** —— 那 4 条断言必须改。
  => 叙述需要区分两件事：**B1 用既有测试证明"行为不变"**（成立），
  **B3 必须改那 4 条编码遗留行为的断言**（不成立的是"既有测试全程一字不改"）。

### 冲突 8：`docs/ROLE-SPECS.md` §R0 的列**按下标**解析

- 已在第 7.4 节写清：`tests/test_role_specs_complete.py::_r0_rows` 取
  `cells[3]` / `cells[4]` / `cells[5]`。插入 `external` 列会整体错位。
- **冲突点**：设计的第 6 节说"§R0 工具总表（那张表有机器比对）"，
  但没提"插入一列会**同时改判据**"。=> 人审包必须包含 `_r0_rows` 的下标改动。

---

## 11. 文档改动清单（本方案若通过，除代码外还要改哪些 md）

| 文件 | 改什么 | 为什么 |
|---|---|---|
| `docs/PROPOSALS.md` | 新增 **P-13**（已在本次交付里登记，一句话摘要 + 指向本文件） | 编号纪律：一条编号指向一件确定的事 |
| `docs/DEVELOPMENT.md` | §6 的 **P7** 改双向；§4.3 的"六件套"叙述与 `__post_init__` 的真实职责对齐（冲突 4）；§4.3 第 2 项的取值词表 | P7 的内容本身是判据；六件套的检查者写错了 |
| `docs/ROLE-SPECS.md` | §R0 表加 `external` 列 + 更新 §0 的 `side_effect` 分布统计 + `tests/test_role_specs_complete.py::_r0_rows` 的下标 | 表的列结构就是判据的输入（7.4） |
| `docs/PROPOSALS.md` | **P-6** 的处置与本方案的关系（冲突 2）；**N-2** 的"现状"已过期（冲突 3） | P-6/N-2 的描述与本方案的落点重叠/冲突，必须一起读 |

