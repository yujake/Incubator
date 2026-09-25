# PROPOSALS —— 已裁决的缺口与提案（**不构成判据**）

> 本文件收三类东西，**分开列**，因为它们的处置完全不同：
>
> | 类别 | 含义 | 谁来关 |
> |---|---|---|
> | **P（提案）** | 已判定是缺陷，但**关它需要改禁 AI 区**（或需要一次跨模块的口径决定） | 人（编写或逐行走查 + 2 名 reviewer） |
> | **G（已接受的缺口）** | 已判定是缺陷，**决定暂不关**，理由写清 | 每次发布时重新确认一次 |
> | **N（不是缺陷）** | 看起来像缺陷、经核查**是刻意设计** | 无需动作；本表的存在是为了让下一个人不必重新推一遍 |
>
> ⚠️ **G 类必须继续出现在机械报告里。** 把"接受"写成"已修复"是本文件最危险的失败形态 ——
> 所以 `scripts/lint_rules.py` 对 G-1 的两处**继续报 `warning`**，而不是加进豁免名单。
> 这与 FC-27 的 `unknown ≠ clean` 是同一条纪律：**"我知道它有问题"不等于"它没问题"**。
>
> ## 编号纪律（**一条编号指向一件确定的事**）
>
> - **编号唯一**：`G-1`…`G-n` / `P-1`… / `N-1`… 各自成命名空间，同一号**只能有一条**。
>   本轮**真的撞过一次号**（两条新增条目都被写成 `G-9`），而其中一条的号已被测试文件引用 ——
>   于是"`G-9` 指哪一条"在那一刻没有答案。**编号是命名空间，两人同时加一条就会撞**（与 FC-03 同族）。
>   由 `tests/test_proposals_register.py` 的 `test_proposals_ids_are_unique` 断言。
> - **引用必须存在**：全仓（文档/测试/源码）提到的每个编号都必须真的有一条
>   （否则是"读者去找一条不存在的登记项"这种虚证）。由 `test_every_referenced_id_exists` 断言。
> - **空洞必须写明**：编号不许留空（本轮曾经在 `G-4` 之后直接跳到 `G-6` —— 那个空洞
>   后来被补成了 **G-5**，因为一份测试的 docstring 已经引用了"PROPOSALS 的 G-5 条"，
>   而它当时**不存在**：这就是一条悬空引用）。由 `test_gap_in_numbering_is_documented` 断言。

---

## P-1：把 roles 校验下沉到 `ToolRegistry.register*`（**注册期 fail-closed**）

**现状**：`tools/__init__.py::build_registry` 在装配期核 `spec.roles ⊆ schema.ROLES`。
但 `ToolRegistry` 本身**不核** —— 任何绕过 `build_registry` 的装配入口都要自己补一次
（`agent_d.validate_tool_roles` 就是这么来的）。`scripts/lint_rules.py` 的 R004 就是这条的探测器。

**提案**：把这条断言移到 `tools/base.py` 的 `ToolRegistry.register` / `register_function` /
`register_spec` 里 —— 注册的那一刻就核。于是：

- **没有装配入口能绕过它**（包括未来新增的、以及第三方注入的注册表）；
- `agent_d.validate_tool_roles` 与 R004 的 `ROLE_VALIDATOR_CALLS` 一整类豁免都可以**删掉**；
- R004 从"警告层"退化成"多此一举"，可以整体删除。

**为什么不由 AI 做**：`tools/base.py` 在 FC-27 禁改区（`auth-audit`），理由逐字是
*"`for_role` 的结构性过滤：只读角色一律拿不到写工具 —— 它是**实现**，与上面的**声明**
分处两文件，两者必须同时人审"*。把校验从装配期挪到注册期，**改变的是权限面的失败时点**，
而失败时点正是"越权"这类不可逆错误发生的窗口。

**改动面（预估，需人工确认）**：
- `tools/base.py`：`register*` 三处入口各加一条断言；
- `tests/test_agent_d.py::test_install_d_tools_rejects_bad_role_name_at_assembly_time`
  与 `tests/test_dup_consolidation.py` 的负控 —— 它们现在断言"**装配期**抛"，
  改动后会变成"**注册期**抛"。**这一条必须人确认**：断言从"装配期"变成"注册期"
  是**变强了**还是**只换了地方**？（我的判断：变强了 —— 注册期更早，且覆盖所有入口。
  但"更早失败"会改变 `install_x_tools` 的错误传播路径，需要人看过调用方。）
- `tests/test_tools_*` 里可能有用 `roles=("agent-X",)` 做**其他**用途的夹具（例如
  想测"未登记角色"的过滤行为），它们会被注册期断言**提前打断**。这是最需要人扫一遍的地方。

**验收判据（可判定）**：`python scripts/lint_rules.py` 的 R004 命中数**降为 0**；
上面那条负控测试改成断言注册期抛；`agent_d.validate_tool_roles` 被删除或其 docstring
改为"历史遗留，见 P-1"。

---

## P-2：`release_check.py` 显式触发能力表自检

**现状**：`capabilities.assert_capabilities()` 挂在**导入期**（这是刻意的：
"一个没人运行的校验"与"没有校验"在结果上不可区分）。但 `agentflow/__init__.py`
刻意不 import 任何子模块，所以**只有真正 import 到 `capabilities` 的人**才触发它。
`release_check.py` 的八项里**没有一项**显式 import 它。

**提案**：在 `scripts/release_check.py` 的 `imports` 项（或 `verify` 项）里加一条
子命令：`python -c "import agentflow.capabilities"`，断言退出码 0。这样"导入期自检"
有一个**明确的触发者**，而不是靠"总会有人 import 到它"。

**为什么不由 AI 做**：`scripts/release_check.py` 在禁改区（`release-deploy`），
理由逐字是*"发布门本身 —— 改宽它等于让'发出去的东西'不再受检"*。
加一条检查是**收紧**，但仍必须人审：本项目的规则是"改宽与收紧都要人审"，
因为判断"这算收紧还是算改口径"本身需要人。

**实测代价（供人判断值不值）**：`import agentflow.capabilities` 会拉起全部 `agent_*`
（实测 167 ms / 159 个模块）。

---

## P-3：`release_check.py` 的 noai 项接 `.noai-approvals.json`

**现状**：`item_noai` 用 `--paths` + `--changed`；命中即判 `fail`。它**不知道**
`.noai-approvals.json` 的存在，所以即便 13 条禁改区改动已经被 2 名 reviewer 走查过，
它仍然报 `fail`（保守方向，不会漏报，但也**永远无法转绿** —— 于是发布门失去了
"批准完成"这个可判定状态）。

**提案**：把第 6 项改成调用 `noai_gate.py --check-approvals --changed …`，
把"未批准"判 `fail`、"台账读不到"判 `unknown`、"全部已批准"判 `pass`。

**为什么不由 AI 做**：同上 —— 它是发布门自身；而且这是**放宽**判决
（从"命中即 fail"到"命中 + 已批准 ⇒ pass"）。**放宽发布门的判断只能由人做。**

**关联**：`.noai-approvals.json` 与 `NOAI-REVIEW-REGISTER.md`（人读侧）。

---

## P-4：把 4 位 ID 的上限下沉进 `interactions.next_prefixed_id`（**越界产号**）

**现状（实测）**：`interactions.next_prefixed_id` **自身没有上限**。当某张表已经用到 `r-9999`
时，它会给出 `"r-10000"` —— 一个 **5 位**号，而 `store.py` 的 `MAX_ID = 9999` 与
`schema.is_valid_id` 都按 4 位契约设计（`store.alloc_id` 用满会 **fail-closed 抛错**，
但 `next_prefixed_id` 不会）。

**后果**：工具层的两个调用者（`table_tools` / `research_tools`）已被一个**契约检查**
（`table_tools.assert_request_id_in_space`）挡住，但**其余直接调用者仍会产出 `r-10000`**：
`agent_c` / `agent_d` / `agent_f` / `cli` / `demo`。
`SearchRequest.validate()` 只查"非空"，所以它会**静默落库** —— 一句报错都没有。

**提案**：在 `next_prefixed_id` 里对 `n > 9999` 抛 `ValueError`（与工具层那道守卫同一语义），
随后**删掉**工具层那道守卫（判据只有一份）。

**为什么不由 AI 做**：`interactions.py` 在 FC-27 禁改区（`auth-audit`）。
且这一改动会**改变已经冻结的取号语义**（从"静默越界"变成"抛错"）——
调用方是否需要处理这个新异常，需要人过一遍那 5 个调用点。

**可判定的验收**：`tests/test_agent_c_service.py` 里对 `is_valid_id` 的断言 +
一条新用例"表里已有 `r-9999` ⇒ 取号抛 `ValueError`，而不是返回 `r-10000`"。

---

## P-5：`verify.py` 的引用解析与 `doc_tools.citation_ref_parts` 是**两份实现**

**现状**：`verify.py` 的 `dangling_citation` 检查内联做引用解析（`partition(":")` +
`split("#")`）；工具层新增的 `doc_tools.citation_ref_parts()` **抄了同一口径** ——
它们必须逐字一致，否则"G 认为合法的引用"与"verify 认为悬空的引用"会给出不同答案，
而**两边各自都自洽**。这正是 FC-03（同一判据只有一份实现）禁止的形态。

**提案**：`verify.py` 导出 `parse_citation()`，`doc_tools` 改为转发。

**为什么不由 AI 做**：`verify.py` 在 FC-27 禁改区（`auth-audit`），
理由逐字是*"`verify_all` 的一致性审计：不变量检查的判据本身被改宽 ⇒ 审计从此永远『通过』"*。

**备注**：工具层代码里已打 `# 待修：` 标注指向本条。

---

## P-6：`verify.run_experiment` 的 `side_effect` 应为 `network`

**现状**：它跑的子进程**继承完整环境**（因此可以联网），但声明为 `write_local`。
`tests/test_agent_e.py` 也断言 `write_local`。

**为什么算低危**：`write_local` 与 `network` **两档都需要审批**（`NEEDS_APPROVAL` 含两者），
所以"声明不精确"在当前不影响权限面；它影响的是**审计口径**（"这次跑联网了吗"）。

**提案**：改为 `network` 并同步那条测试断言。

**为什么不由 AI 做**：改它要动既有测试断言，而"这条断言编码的是错误行为还是刻意选择"
需要一个判断：**子进程能联网**是否等价于**这个工具会联网**？（它跑的是工作区内的脚本，
脚本自带环境。）这个判断我不替人做 —— 记在这里。

---

## P-7：`quoteverify.check_quote` 在"一个窗口都没搜过"时返回 `verified=False`

**现状（实测，带证据）**：`quoteverify.py` 的 `page_unknown` 分支在
**页码未知且不许全文兜底**时，`tried == ("no_window",)` —— 即**一个窗口都没搜过** ——
却返回 `verified=False`（"校验失败"）。而该模块自己的 docstring 逐字写着
*"'没校验'和'校验失败'是两件不同的事"*。

**为什么这是缺陷**：`False` 在下游是**一个关于世界的断言**（"这句话不在原文里"），
而事实是"我没查"。三态纪律要求这里返回 `None` + 受控 `reason`
（例如 `not_searched_page_unknown`）。返回值里虽有 `reason="not_found_page_unknown"`
与 `tried=("no_window",)` 自我说明，但**判据字段 `verified` 本身在说反话** ——
而下游读的是 `verified`。

**提案**：该分支改返回 `None`；`tests/test_quoteverify.py::test_unknown_page_without_fallback_is_false`
相应改名并改期望（`..._is_none_not_false`），docstring 写明"这是修正编码错误行为的断言"。

**为什么不由 AI 做**：`quoteverify.py` 在 FC-27 禁改区（`prover-bridge`），
理由逐字是*"`check_quote` 引文级回验：把一条断言与来源文本逐字比对 ——
它是『外部证据』与『我们自己的断言』之间的桥，错判即幻觉引文进报告"*。
**并且**：改它要改一条既有测试的**期望值**（`False` → `None`），
而"改既有断言的期望"必须由人确认它是"修正错误行为"而不是"放宽断言掩盖失败"。

---

## P-8：`AgentE` 目前**一条 `proof` / `exhaustive_search` 实验都登记不了**

**现状（实测）**：`schema.py` 的新硬约束要求
`evidence_kind="proof"` 必须给 `verifier_output` + `verifier_subject_key == claim_key`，
`method="exhaustive_search"` 必须给 `certificate`。
而 `AgentE.build_experiment` 不传这三样 ⇒ 这两类实验**显式 `ValueError`**（不是静默失败）。

**根因不是"漏了一处"**：`verifier_subject_key` / `certificate` / `search_bound`
在全仓库**只有 `schema.py` 引用它们** —— 说明**接线是整体缺失**。

**提案（分两步，第二步依赖第一步的决定）**：
1. `build_experiment` 增参 `verifier_output` / `certificate` / `search_bound`；
   `evidence_kind=="proof"` 时把 `verifier_subject_key` 绑成 `claim_key`
   （这只是**数据绑定**，schema 仍要求 `verifier_output` 非空 ⇒ **proof 依旧拿不到**）。
2. `run_experiment` 只在**那一次真实的形式化调用**产出 `verifier_output` 时才传它 ——
   这需要先决定 `verify.check_formal` 怎么接线（当前主路径是 `fail(kind="not_implemented")`，未接线）。

**为什么不由 AI 做**：第 2 步取决于"`verifier_output` 该从哪来"，
而**本环境探测不到任何检查器**（无 Lean/Coq/Isabelle）。
擅自接线 = **自己发明一条判据**（例如"把脚本 stdout 当 verifier_output"），
那会把 `proof` 级证据变成假话 —— 正是禁改区要防的事。
**当前行为是显式异常，不是静默通过**，所以这个缺口是"功能缺失"而不是"数据污染"。

---

## P-9：**需要另一份提案** —— `review_findings` 的字段（否则 **G10 永远无法判定**）

**现状（规格本身的矛盾，由实现者指出的）**：`draft/17-…md` §8.3 只给 `documents.claims`
加字段，**完全没有**规定 `review_findings` 的字段；而 §8.4 的 **G10 审校格式门**判据逐字要求
"每条发现必须有：**轴 + 严重度 + 行号 + ≤20 词逐字引文 + 最小修法 + `maths: yes/no`**" ——
这六个字段里有**四个**在我们的 `schema.ReviewFinding` 上**不存在**。

**后果**：照 §8.3 做完，**G10 仍然无法判定**。也就是说"15 道门都在跑"这句话里，
有一道门**在当前数据模型上永远只能报 `unknown`**。

**本轮处置（正确的那一种）**：**保留这道门**，让它如实报 `unknown` + **逐条列出缺哪些字段**。
**没有**删门（删门会让"15 道门都在跑"变成假话），**也没有**判 `pass`（那是最坏的一种）。

**提案**：另写一份 `review_findings` 的字段提案（**不能**与 claims 那份合并 ——
`review_findings` 有去重键 `_dedup_key = (kind, target, message)`，加字段会改变去重语义，
风险面不同）。

**为什么不由 AI 做**：`schema.py` 在禁改区（同 P-4/P-5 的理由）；
且"一条发现要不要带**行号**"这个问题本身牵涉 `FIX_PROTOCOL.md` 的
"审校期间不改文件 + 报告钉住版本 hash" —— 行号只有在版本冻结的前提下才有意义。

**本轮可判定的替代品**：G11（版本冻结）已经落地，所以"行号"这一项**在 G11 通过之后**
才谈得上。这个顺序不能颠倒。

---

## P-10：`counterexamples`（清单）与 `n_counterexamples`（计数）**可能互相矛盾**

**现状（规格本身的第二处矛盾，由实现者指出的）**：§8.4 的 **G12 反方门**要求
"主动构造小参数反例"，而 §8.3 把反例放在 `counterexamples`（list）；
但 `n_counterexamples` 又出现在 `numeric_evidence` 里，是一个**计数**。
两者可以同时为真且互相矛盾：`counterexamples=[]` 而 `n_counterexamples=3`。

**本轮处置**：实现者**没有**为这个矛盾写一致性门（规格没要求，且"哪个更权威"是人的判断），
只在 G12 里把两个来源都当作"反例搜索的痕迹"。

**提案（三种可能的口径，请人选一个并写进规格）**：
1. `n_counterexamples` = **那一次数值运行**里扫到的反例数（机器产生的）；
   `counterexamples` = **人/文献已知**的反例清单（可能来自别处）。
   两者**本来就不该相等** ⇒ 若取这个口径，需要的是 `scope_caveat` 说明差异来源，
   而不是一致性门。
2. `counterexamples` 是 `n_counterexamples` 的**明细**，`len()` 必须 ≥ 计数 ⇒ 加一条
   `error` 级一致性门。
3. 取消 `n_counterexamples`，只留清单 ⇒ **改磁盘格式契约**（禁改区）。

**为什么不由 AI 做**：这不是实现问题，是**口径的定义问题**；而口径一旦定下，
历史报告里每个数字的含义都会被追溯性地改写（与 `EVAL_REQUIRED_FIELDS` 同类）。
**在裁定之前，不许为它加门** —— 加门等于替项目选了口径。

---

## P-11：`release_check.py` 的八项**不含验收测试**（用户点名的六项里缺一项）

**现状**：用户逐字要求的"一键发布检查"是
**"全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter"**。
`scripts/release_check.py` 覆盖其中**五项**（全量测试 / 模块自检 / verify / 工具普查 / linter，
外加禁 AI 区门 / 契约版本 / 源码树可导入三项），**唯独没有"验收测试"**。

**本轮的处置（不是提案，已完成）**：新建 `tools/release_all.py` ——
一个**编排层**：它把 `release_check.py`、`test/test2/run_acceptance.py`（`AGENTFLOW_TARGET=formal`）、
`test/test2/repro/run_all.py`、`tools/verify_role_specs.py`、`tools/coverage_zero_test.py`
串成一条命令，做**三态汇总**（任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`），
退出码 0/1/2。它有两条关键取舍，**都是刻意的**：
1. **`--skip` 掉的步骤记成 `unknown`，不是 `pass`** —— 否则 `--skip acceptance` 就成了
   "发布门全绿"的捷径；
2. **超时 / 起不来 ⇒ `unknown`**，且 `timed_out` 的判断**必须先于**退出码 ——
   Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 无法区分。

`tools/release_all.py` **自身已登记进禁改区**（`release-deploy` 类，`.noai-paths` 与 `AGENTS.md`
两处逐条一致）—— 一个新建的发布门必须当场登记，否则"换个目录就绕过"就成立了。

**提案（要人决定的部分）**：**要不要把验收测试并进 `release_check.py` 本身**？
- 并进去的好处：只有一个发布门，"少跑了一条"这种形态从结构上消失；
- 并进去的代价：`release_check.py` 会从 ~3.5 分钟变成 ~8 分钟，而**慢的门最后会被跳过**；
  且它要处理"验收程序在另一个目录（`../test/test2`）、依赖 `AGENTFLOW_TARGET` 环境变量"
  这种跨仓库耦合 —— 那是 `release_check.py` 现在没有的假设。
- 本轮的选择是"编排层在外、`release_check.py` 不动"，理由是**后者在禁改区**。

**为什么不由 AI 做**：`scripts/release_check.py` 在 FC-27 禁改区（`release-deploy`），
同一类判断见 P-3（放宽/收紧发布门的决定权在人）。

---

## P-12：`usage_ledger` 的**幂等唯一键**（跨进程重复记账；**B 已落地，A 待人工**）

**现状（实测）**：本项目**没有数据库**，`usage_ledger` 是 `data/usage_ledger.json`
（`filelock` 排他锁 + `os.replace`）。两条生产写入路径
（`modelcost.charge_reply`、`conductor._charge_and_settle`）都是
**"无锁快照读判重 → 有锁写账"**，两次操作分处两个临界区。
4 个真进程用同一个幂等键并发入账 ⇒ 账本落 **4 行**、总 token **6000**
（只该记 1500）⇒ **4 倍重复扣费**，且没有任何请求拿到幂等结果。

**为什么难发现**：重复的两行 `usage_id` **本来就不同**（`charge` 每次 `alloc_id`
发新号），所以按主键数重复的 `duplicate_id` **永远不响**；
而 `tasks.tokens` 与账本汇总是**一起**虚高的，所以 `usage_task_total_mismatch`
也不响 —— 它们仍然"相等"，只是相等的是错的数。**这条缺陷在既有判据下完全不可见。**

**已落地（提案 B，不在禁改区，AI 可独自做）**：`TokenMeter.charge_once()`
把判重搬进 `charge` 本来就持有的那把锁 ⇒ 后到者在锁内看得见先到者。
两处写入方都改走它。验收判据 ①–⑦ 全部满足（见下）。

**提案 A（要人决定 + 2 名 reviewer）**：给 `UsageEntry` 加一个**可选** `idem_key`
字段 + `validate_table` 对**非空**值断言唯一 + `store.Tx.insert_unique`
（`INSERT … ON CONFLICT DO NOTHING` 在本栈里的等价物）。
**完整 diff、向后兼容分析、迁移与回滚方案、逐 hunk 复核清单**见
`docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`。

**为什么不由 AI 做**：`src/agentflow/schema.py`（`schema-migration`：
"改它等于改磁盘格式契约"）与 `src/agentflow/store.py`（`schema-migration`：
"四者任一错都是**数据毁灭级**"）都在 FC-27 禁改区；§5 的检测不变量落在
`verify.py`（`auth-audit`）。三者各需人编写或人逐行走查 + **2 名 reviewer**。

**存量数据**：清洗工具 `scripts/usage_ledger_audit.py` 已交付（不在禁改区），
它处理了"只改快照会被 `rebuild` 复活"这个陷阱并做**回放自证**。
本仓库实测 **7 个 `usage_ledger.json` 全部为空表** ⇒ 本仓库无需清洗。

> ⚠️ **原位更正（2026-09-25 第三轮审计；并入，不新增号）**：
> `Get-ChildItem -Recurse -Filter usage_ledger.json` 实测 **5 个**（不是 7 个）。
> **影响有限但必须写清**：数字不影响结论（都指向"存量表是空的"），
> 但它属于 `G-30` 记的同一族"**文档里的实测数字过期**"——而这里更值得记的是**方向**：
> 数量**少了**，说明有 `usage_ledger.json` 在这轮之间被删/被合并。
> ⇒ **本条按 `G-32` 的口径补一句"观测时刻"**：
> "2026-09-25 22:1x–22:4x 实测 **5** 个，全部为空表（`Get-ChildItem -Recurse`）"。
> **不许**把 5 与 7 两个数字同时留在正文里而不管——那正是 `G-30` 的病因。

**验收判据（可判定）**：
① 同一幂等键并发 N 次 ⇒ 账本 1 行；② 总 token == 单笔；③ N−1 个返回
`duplicate` 且 `usage_id` 指向同一行；④ 不报错且重放不消耗 ID；
⑤ 负控：**不同**的键必须落 N 行；⑥ 4/4 进程都真的经过被放大的竞态窗口；
⑦ 存量清洗**扛得住真的 `Store.rebuild()`**。①–⑦ 已满足，
⑧⑨（表级唯一性断言、`verify` 的 `duplicate_idem_key`）待 A 实施。

---

## P-13：把 `side_effect` 这根轴**拆成两根正交轴**（`effect` × `external`）—— 完整提案见 `docs/PROPOSAL-side-effect-axes.md`

**一句话摘要**：`side_effect` 混了两个正交问题（能不能改**我们拥有**的东西 / 能不能触到
**我们不拥有**的东西），于是每个取值都是半个真话（`verify.check_formal` 对数据契约是 `read`、
对宿主是"跑任意程序"；`verify.run_experiment` 既写实验记录又执行调用方给的脚本）。
拆成 `effect ∈ {none, read, write_local}` × `external ∈ {none, egress, exec}` 之后，
审批与沙箱策略**可推导**（`needs_approval` / `sandbox_required`），不必逐工具手写布尔位。

**完整方案（改动清单 / 判据 / 分批验收 / 人审包 / 风险与反驳 / 与事实冲突）逐条写在
`docs/PROPOSAL-side-effect-axes.md`**。要点：词表与 `SIDE_EFFECTS` **同一处声明**；
`network` 降为**遗留取值**（显式翻译表，不许静默重解释，lint 报 `info` 列出剩余处数）；
只读角色在既有"剥写工具"之外**再剥 `external == "exec"`**（沙箱可用时除外），
`agent_h._H_WRITABLE_TOOLS` 那个窄口子必须重新审；新增**对偶判据 R010**
（声明 `external != "exec"` 却起子进程 ⇒ error；声明 `egress` 却全文无网络调用 ⇒ warning），
`DEVELOPMENT.md` 的 P7 由**单向**改**双向**；**最后删除** `network` 这个值（含两处词表的
**原子**删除）。AST 只用来**核对**声明与代码是否一致，**不**用来生成声明（**不是**重提 N-4）。

**为什么不由 AI 自己做**：`src/agentflow/tools/base.py` 与 `src/agentflow/tools/__init__.py`
都在 FC-27 禁改区（`auth-audit`），理由逐字是 *"`for_role` 的结构性过滤 …… 它是**实现**，
与上面的**声明**分处两文件，两者必须同时人审"* 与 *"只读角色（C/H）的权限面单一来源"*。
新增一根轴改变的是**审批与角色剥离的判据本身**（与 P-1 同族：改的是权限面的失败时点）。
另有三处**必须由人裁决**的事实冲突（`verify.detect_verifier` 落在轴的**定义**与 lint 的
**字面判据**之间；P-6 与本条的**排期冲突**；`check_formal` 在工具层是 `read`、在能力层是
`network` 的两层不一致）—— 见提案第 10 节，**提案没有替人裁任何一条**。

**分批与可判定判据**：B1 词表 + 派生策略 + 遗留翻译表 + 交叉断言（验收：`import agentflow.capabilities`
退出码 0，且**既有**测试证明 `for_role` 行为逐字不变）；B2 R010 正控/负控各一；
B3 逐个迁移声明并**删除** `network`（"迁移完成"的判据：lint 的遗留计数为 0 **且**两处词表里
已无该值）。

---

## G-1：`agent_e` / `agent_f` 的装配入口**确实没有** roles 校验（**已接受**）

**现状**：`agent_e.install_e_tools`（`agent_e.py`）与 `agent_f.install_f_tools`（`agent_f.py`）
各自 `ToolRegistry(name="agent-E"/"agent-F")` + `VT.register`/`AT.register`，
**没有任何地方核 spec 里的 `roles` 字面量**。`scripts/lint_rules.py` 的 R004 对这两处
**持续报 `warning`**。

**判定：这是真缺陷，不是假阳性；但决定暂不关**，理由：
1. 角色名在 `verify_tools` / `attack_tools` 里是**模块级 `_ROLES` 常量**，不是散落的字面量，
   拼错的概率低于"每个 spec 各写一遍"的形态（`agent_d` 当初出错正是因为后者）；
2. 正确的关法是 P-1（下沉到注册期），而不是在这两个入口各补一次断言 ——
   各补一次就是**同一判据的第三、第四份实现**，正是本项目禁止的形态；
3. 因此它的处置**依赖 P-1**，而 P-1 要人审。

**为什么继续报 `warning` 而不是加进豁免名单**：加豁免等于把它从报告里抹掉。
一个被接受的缺口**必须继续可见** —— 否则"接受"会伪装成"已修复"，
而下一次发布的人不会再看到它。

**每次发布时的确认动作**：跑 `python scripts/lint_rules.py`，确认这条 warning
**仍在**且**只有这两处**。若某天它消失了，要么是 P-1 落地了（好事，请更新本文件），
要么是有人加了豁免（坏事，请查是谁）。

---

## G-2：`attack_tools.py` 的 6 个 handler 失败类型被压成笼统的 `tool_error` + 2 条声明漂移 —— ✅ **已关闭**

> **本条的原始诊断有两处错，由实现者用实测证据反驳并更正。原文保留在下面（不删），
> 因为它是一份"评审也会诊错"的实例，而**修法必须按真实根因走**。**

**原文（我的诊断，部分是错的）**：`attack.*` 的 6 个工具
（`check_budget` / `pick_next_subgoal` / `create_plan` / `step` / `status` / `list_plans`）
的 `PlanError(RuntimeError)` / `ValueError` / `StoreError` **会逃逸出 `guard_result`**，
于是调用方在 `ToolResult` 里看到的是 `kind="unexpected"`。

**实现者实测（修复前，`temp/probe_attack_graph.py`）**：

| 异常 | 我断言 | 实测 | 结论 |
|---|---|---|---|
| `StoreError` | `unexpected` | **`unexpected`** | ✅ 我对 |
| `PlanError` | `unexpected` | **`tool_error`** | ❌ **我错了**：`agent_f.PlanError` 早已继承 `ToolError`，被 `base.py:458` 收编 |
| schema 的 `ValueError` | `unexpected` | **`tool_error`** | ❌ **我错了**：`AgentF.create_plan` 已把它包成 `PlanError` |

**真实根因**：不是"逃逸"，而是"**具体的失败类型被压进笼统的 `tool_error` 一档**" ——
调用方无法据此判断该重试、该改输入、还是该报环境故障。**仍算缺陷，但修法与判据不同**，
而且**不许把它说成"修之前是 `unexpected`"**（那是一句可被一条命令证伪的话）。

**已修的（本轮）**：
- `attack_tools.py` 新增**唯一一份** `_guard`（形态照抄 `doc_tools.guard_result` 与
  `verify_tools._run_experiment_tool`），6 个 handler 全部接线：
  `ValueError ⇒ validation_error`（消息带具体字段）、`PlanError ⇒ plan_error`
  （`except _plan_error_type()` **排在** `except ToolError` **之前** —— `PlanError` 是它的子类，
  顺序写反会让"计划层面的拒绝"被压成笼统的工具错误）、`ToolError ⇒ raise`（交给 `base.py`）、
  `StoreError ⇒ store_error`；
- `can_derive`：`checked=False ⇒ allowed=None + blocked_by="not_checked"`；
  `complete=False ⇒ allowed=False + blocked_by="incomplete"` —— **"没查"与"查了但不完整"分开了**，
  5 个受控取值写进 docstring 并由穷举测试钉住；
- `include_terminal`：**工具层那一份本来就是对的**（handler 只转发；`AgentF.list_plans` 已把
  `None` 解读为声明默认值）—— 补了一条工具层的上锁断言（省略键 / 显式 `True` / 显式 `None` 三路等价）。

**判据**：`tests/test_tools_attack_graph_fixes.py`（21 条，含 7 处变异试验全部 RED）。

---

## G-3：`graph_tools.py` 的 `StoreError` 逃逸 + `returns=` 漂移 + 不可截断的 `neighbors` —— ✅ **已关闭**

> **同理：我的诊断里有一个工具是凭空造出来的，由实现者指出。**

**原文（我的诊断，有一处是错的）**：`graph.*` 的 4 个 handler 有 `StoreError` 逃逸；
`graph.neighbors` / **`graph.concepts`** 的 `returns=` 与实际键集合不一致；
`RelationGraph.neighbors` 返回一个**不可截断的裸列表**却被直接暴露成工具。

**实现者实测**：
- **`graph.concepts` 这个工具不存在。** `graph_tools.register` 只注册 4 个：
  `graph.build` / `graph.stats` / `graph.neighbors` / `graph.relations_between`。
  实现者**没有为了对上简报而凭空造一个工具** —— 这是正确的处置。
- 逐条核对后发现**第三处真实漂移**（我的简报没写）：
  `graph.relations_between` 的 `returns=` 漏了 `a_name` / `b_name` / `concept_ids` /
  `statement` / `quote`。
- ⭐ **`returns=` 的"声明 vs 实现"判据在 `graph.*` 上从来没跑过**：
  旧 `returns=` 是**不带引号**且用 `...` 省略的，而 `declared_keys` 的正则
  `r"'([a-z_][a-z0-9_]*)'"` 对它们返回**空集** ⇒ `declared - actual == {}` **真空通过**。
  实测这个真空面覆盖 **36 / 55 个工具（65%）** —— 见本文件 **G-4**（正在修）。

**已修的（本轮）**：
- 4 个 handler 的 `StoreError` 走 `from .attack_tools import _guard` —— **转发，不另写一份**
  （有断言 `graph_tools._guard is attack_tools._guard`，且 AST 里没有第二个 `def _guard`）；
  `graph.neighbors` 的"未知概念"保留原形状（`ok=False` + `known_concepts`），
  用哨兵异常穿过守卫后翻回；
- 四条 `returns=` 逐键列全（含上面那处第三漂移）；
- **`RelationGraph.neighbors()` 保持裸 list**（证据：4 个调用点 `agent_c.py` ×3 与
  `trace_tools.py:305` 都按 list/set 语义用它，改返回类型会**静默破坏**；
  `agent_c.py:2682` 逐字写着"不改低层工具"）。**有界那一层加在工具层 + 新方法
  `neighbors_bounded()` 上**，两处转发唯一判据 `bounded_neighbors()`：
  新增 `max_neighbors`（默认 200）+ `total_neighbors` / `returned_neighbors` / `truncated` / `reasons`。
  实测证据：300 个邻居的完整 JSON 是 27046 字符，`prune_tool_result` 后 `pruned=False`、
  条数**一条没少**（它只剪长字符串）⇒ **上下文预算的剪枝在这上面本来就不生效**，
  所以必须有界 —— 这条证据是"为什么不照字面改 `RelationGraph.neighbors`"的关键。

**⚠️ 仍需人复核的一处口径**：`max_neighbors` 的默认 **200** 是实现者**选的口径**
（依据：同类服务面 `SERVICE_MAX_NODES` 也有上限，常规概念图邻居数是个位到几十）。
**没有在真实稠密数据上量过触发率** —— 本项目对"新门要在 ≥20 条真实样本上量过"是有要求的。

---

## G-4：`returns=` 的"声明 vs 实现"判据在 **36 / 55 个工具上真空通过** —— ✅ **已关闭**

**现状（实测，复现命令 `python temp\_probe_returns_parse.py`）**：
`ToolSpec.returns` 是工具**承诺返回哪些键**的声明，而检查它的判据是
`tests/test_tools_audit_fixes.py::declared_keys`：

```python
return set(re.findall(r"'([a-z_][a-z0-9_]*)'", returns))
```

它**只抓单引号键**。于是任何**不带引号**的写法（`data={src, dst}`、
`{question_id, from, to}`、`data=整数行数。`）都被抽成**空集** ——
而下游断言是 `declared - actual == set()`，**空集永远是子集** ⇒ **判据真空通过**。

| 事实 | 值 |
|---|---|
| `returns=` 为空 | **0** 个 |
| `returns=` 非空但**抽不出任何键** | **36 个 / 55 个（65%）** |

**为什么这是本类最贵的一种缺陷**：它不是"某条判据太松"，而是**"这条判据在大多数对象上
根本没执行"** —— 而报告里它看起来一直是绿的。这与 §0 记的"多数脚本不设退出码，
于是『未报错』被误读为『无问题』"是**同一条教训的第二种形态**：
**这次不是"没退出码"，是"抽不出键 ⇒ 空集 ⇒ 通过"。**

**修法（本轮已完成）**：
1. **35 个工具**（`attack` 4 / `doc` 3 / `fs` 7 / `ocr` 3 / `research` 5 / `search` 5 / `table` 8）
   的 `returns=` 统一成仓库里**已有的**合规写法（`{'k1','k2','neighbors':[{'k3'}]}`），
   **键名从真实实现里读出**（53 个靠**真跑**观测 ok 分支，2 个只能读代码，1 个真跑但带保留 ——
   四类在测试常量 `EXECUTED_KEY_SOURCE` / `CODE_ONLY_KEY_SOURCE` / `EXECUTED_WITH_CAVEAT` 里
   逐个登记，并有断言保证"读代码"那一档不能被悄悄清空）。**没有改任何 handler 行为。**
2. 新建反真空门 `tests/test_tools_returns_declaration.py`（18 条，含 4 条负控）。
3. `declared_keys` 之外新增**三态入口** `parse_declared_keys(returns) -> (set, status)`，
   `status ∈ {parsed, empty_declaration, unparseable}`；
   `declared_keys` 改为薄转发（签名与返回值逐字不变）。

**⚠️ 实现者对这份简报的三处更正（都有实测证据，其中两处会让门走向另一个错误）**：

1. **"36 处全都能机器化"不成立**：其中 **7 个**的 `data` 是**标量或行对象**
   （`table.count` 是 `int`、`table.create`/`table.update` 是主键字符串、
   `fs.delete`/`table.delete` 是 `bool`、`fs.read` 是正文 `str`、
   `table.get` 是"行对象或 None，形状由表 schema 决定"）—— **硬编键就是造假**。
   处置：**显式豁免清单**（7 条，理由写在 `returns=` 字符串**本身**里，供人直接看到），
   并加一条"豁免集必须恰好等于清单"的断言防它被悄悄改宽。
   ⇒ **反真空门的实际覆盖是 48 / 55，不是 55 / 55** —— 这个数字必须写进任何合规叙述。
2. **合规写法不只有顶层键**：仓库既有的合规声明**包含嵌套键**
   （`graph.neighbors` 的 `neighbors[]` 内字段、`doc.list_documents` 的 `documents[]` 内字段）。
   所以子集判据必须**递归**取实际键 —— 否则会把 **4 个本来就对**的声明判红。
   实现者先按顶层键写，**实测这 4 个真的红了**，才改成递归。
3. **这条判据的方向是"不对称"的**：它只抓"**声明了却没给**"，
   **抓不到"给了却没声明"**（变异 M4 故意少声明一个真键 ⇒ 仍然 GREEN，**这是设计内的边界证明**）。
   ⇒ 它**不能**支撑"docstring 与实现完全一致"这个更强的结论；
   测试常量 `SUBSET_CHECK_SCOPE` 与 docstring 把范围写死了，免得下一个人高估它。

**一条仍然敞着的小口子（已登记，未修）**：`declared_keys` 的正则只认
`[a-z_][a-z0-9_]*`，所以键名写成 `'Bad-Key'` 或中文会被判成 `unparseable` ——
对反真空门是**更严**（安全方向），但子集断言会**静默漏掉**它。
改它会同时改变既有判据的严格程度，超出授权 ⇒ 留给人。

**顺带的一处越界（如实登记）**：`src/agentflow/tools/verify_tools.py`（**prover-bridge 禁改区**）
的 `verify.run_experiment` 的 `returns=` 也被改了（1 处字符串，不带引号 ⇒ 抽不出键）。
**保留不回滚**（回滚会留下不可解析的声明，与 G-4 的目的相反），走 FC-27 人工走查流程，
已写进 `NOAI-REVIEW-REGISTER.md` 第 12 条并刷新台账基线。

**为什么它在这一轮才被发现**：它的**触发条件是"有人去看那条判据本身"**，
而不是"某次运行报红"。G-3 的实现者是顺着"为什么 `graph.*` 的 `returns=` 漂移没被抓到"
这条线才挖出来的 —— 而这正是**"逐个工具审计"**这项工作的价值所在：
**审计的对象不只是工具，还包括"检查工具的那些判据"。**

---

## G-6：`gates.gate_g1` 把 **Windows 盘符绝对路径**判成"工作区内的相对路径" ⇒ 自含性门报 `pass` —— ✅ **已关闭**

**现状（实测，由"零测试函数覆盖"那一轮的实现者发现，已登记为 `xfail(strict=True)` 的 `TEST-RED-1`）**：
`gate_g1` 用 `raw.split(":")[0]` 把 `C:/outside/p1.py:12` 切成 **`"C"`**（盘符被当成 `file:line`
的分隔符切掉），于是 `root / "C"` 解析成 `<root>/C` ⇒ 落在工作区**内** ⇒ `工作区外=0` ⇒ **G1 报 `pass`**。
同一份代码对相对逃逸（`../outside/p1.py`）判 `fail` —— 所以这不是"门没实现"，
而是**盘符绝对路径这一档被静默地判成了"包内"**。

**为什么这很严重**：G1 的判据逐字是"正文不得引用工作区**外**的路径"，失败处置是"**阻断交付**"。
而它守的对象之一是 `claims[*].proof_location`（形如 `file:line`）——
**在 Windows 上，一条指向 `C:\…` 的证明位置引用会通过自含性门。**
这是"门看起来在把关、实际对这一档输入从不生效"——与 **P16 / G-4** 是同一族。

**可修（`gates.py` 不在禁改区）**。判据已经写好了：`tests/test_coverage_gates.py::test_gate_g1_rejects_a_windows_drive_absolute_proof_location`（原为 `xfail(strict=True)`）——
**✅ 本轮已修，该测试现在以普通断言通过**。

**修法（本轮实际做的）**：新增**平台无关**的绝对路径判据 `_is_absolute_path_text()`
（`<盘符>:<分隔符>` 或 `/` `\` 开头），并把 `file:line` 的切分改成**只认"最后一个 `:` 且其后是数字"**。
docstring 里逐字写清了**为什么不能依赖 `pathlib.Path.is_absolute()`**：

- 在 **Linux** 上 `PurePosixPath("C:/x/y.py").is_absolute()` 为 **False** ⇒ 会把盘符绝对路径
  当成"工作区内的相对路径"，**缺陷原样复现**；
- 在 **Windows** 上 `PureWindowsPath("/abs/path.py").is_absolute()` 为 **False**
  （POSIX 根路径在 Windows 上算"当前盘符下的相对路径"）⇒ 依赖它会**漏掉另一档**。

另外 `relative_to` 抛 `ValueError`/`OSError` 的语义被改正：那是"**没法比**"，不是"在里面"。

---

## G-7：`gates.py` 的**判据文本写了两份且已漂移**（15 道门里 6 道不一致） —— ✅ **已关闭**

**现状（实测，`TEST-RED-3`）**：`gates.py` 的模块 docstring 说"门号、判据…都写进 `GATES` 的声明表里"，
但 15 道门里有 **6 道**（G2 / G3 / G4 / G7 / G11 / G15）的 `GateResult.criterion`
与 `GATES[gid]["criterion"]` **文本不一致** —— 而且每个 `gate_gN` 函数体里还各自有一个
`criterion` 局部变量，所以**同一句判据最多有三处副本**。

| 门 | 声明表 | 实际（`GateResult.criterion`） |
|---|---|---|
| G2 | 每个引用可解析…；**裸文件名也能在工作区内解析** | 每个引用**都**可解析…；**不可解析的必须阻断交付** |
| G3 | …**目标标签**真实存在… | …**目标**真实存在… |
| G4 | **索引/账本**点名的文件存在… | **账本**点名的文件存在… |
| G7 | …禁止**『仅泛证』** | …禁止**仅泛证型** |
| G11 | …一次改完一篇，**不二次编辑** | …一次改完一篇 |
| G15 | …『我在这轮里犯的错』一节 | …『我在这轮里犯的错』一节**；缺失则退回** |

**为什么这是缺陷而不是"措辞差异"**：这几处差异里有的是**语义**差异 ——
G2 的"裸文件名也能解析"与"不可解析必须阻断"是**两条不同的判据**；
G7 的"禁止仅泛证"与"禁止仅泛证型"是**同一档的不同名字**（词表漂移）；
G15 的"缺失则退回"在声明表里**丢了**，而它正是 G15 的**失败处置**。
读声明表的人与读门实现的人会据此**对同一条门得出不同结论**。

**这正是 FC-03 在本轮"新写的门"上的复发** —— 也就是：**我们刚建的那套门自己也犯了这条**。
可修（`gates.py` 不在禁改区）。判据：`tests/test_coverage_gates.py::test_gate_criterion_texts_are_a_single_source`
（原为 `xfail(strict=True)`）。**✅ 本轮已修，该测试现在以普通断言通过**；并补了一条 AST 反漂移断言
（`gate_g*` 函数体里**不再允许**出现 `criterion = "..."` 这样的第二个字面量），
所以"下一个人再写一份"会当场红。

---

## G-8：`interactions.admit_reprocess_request` 对**纯空白**的目标集合放行 ⇒ B 退化成"全量重抽"

**现状（实测，`TEST-RED-2`；`interactions.py` **在禁改区** ⇒ 只能提proposal）**：
守卫写的是 `if not rids`，其中 `rids = sorted({str(x) for x in relation_ids if x})`。
纯空白 `["", "  "]` 经 `if x` 过滤后得到**空集合** —— 但守卫判的是**过滤前**的 `rids`？
实测结果是 `admitted=True, reason="未超上限 2"`：

```
I.admit_reprocess_request([], relation_ids=["", "  "], reason=<合法理由>)
⇒ {'admitted': True, 'reason': '未超上限 2', 'blocked': [], 'counts': {}}
```

**为什么是缺陷**：守卫的**语义**是"没有任何有效目标就拒绝"，而 `["", "  "]` 与 `[]`
在归一后**同形**（都是零个有效目标）。实现里只有 `[]` 走拒绝分支 ⇒
**B 会拿着一个空目标集去重抽取，也就是退化成全量重抽**，把 A 的产能烧在整张关系表上。
`tests/test_interactions.py` 的负控只测了 `relation_ids=[]` 这一种写法，所以这个空档**至今无覆盖**。

**修法方向（明确）**：把 `strip()` 提到过滤条件里 ——
`rids = sorted({str(x).strip() for x in relation_ids if str(x).strip()})`，再 `if not rids: 拒绝`。
让"纯空白"与"空"在**归一之后**同形。

**为什么不由 AI 做**：`interactions.py` 在 FC-27 禁改区（`auth-audit`，
理由逐字："`check_conflict` / `admitting` 一类的角色间交互与授权规则 —— 矩阵错则
'不该能调的工具'变成'能调'"）。这一条改的是**授权矩阵的判据**。

---

## G-5：`gates.gate_verdict({})` 对**空结果集**判 `accepted`（"零道门在场 ⇒ 全 pass"）

**现状（实测，由"零测试覆盖"那一轮的实现者发现，见
`tests/test_coverage_gates.py::test_gate_verdict_rejects_an_empty_result_set_is_not_accepted`）**：
把**空的结果集**喂给 `gate_verdict()`，它返回 `verdict="accepted"` ——
因为 "0 道门 → 0 fail、0 unknown → 全 pass"。

**为什么它可疑（这是"可疑的设计"而不是"已证实的缺陷"，所以按 G 类登记而不是 P 类）**：
`accepted` 在下游是"**这份稿件可以交付**"。而这里的事实是"**一道门都没跑**"。
这与本项目的三态纪律直接冲突：**"没查"不能被读成"查过了没问题"**。
`GateResult` 层面已经有 `unknown` 这一档（G8 的"没有本轮实跑证据 ⇒ `unknown`"），
但**聚合层**在"集合为空"这个边界上把它折叠成了 `accepted`。

**本轮处置**：实现者**没有**在测试里把它改成"我觉得应该的样子"（那是改 `src` 的口径，
不是暴露缺陷），而是**把实测行为钉在纸上**：一旦有人修它，那条测试会红，
提醒他同时更新本条登记。**这是正确的处置。**

**修法方向（待定，需人判断）**：空结果集应判 `unverified`（或 `unknown`）而不是 `accepted`；
但"空集"也可能是合法的调用方式（例如调用方只想拿聚合器做一次空跑）——
所以这**首先是一个口径问题**：`gate_verdict` 的契约要不要覆盖 `results == []`。

---

## G-12：`criterion_revision` **也是两份且 15/15 全部漂移**，且声明表在运行期**从不被读到** —— ✅ **已关闭**

> **编号说明**：本条最初被写成 `G-9`，与另一条并发新增的 `G-9`（"106 个零直接测试的公开函数"）
> **撞了号**。**编号重复会让"G-9 指哪一条"变成不可判定** —— 而 `docs/PROPOSALS.md` 的全部价值
> 就在于"一条编号指向一件确定的事"。所以这里改为 **G-12**（保留后面那条 G-9 的号，
> 因为它的号已被 `tests/test_coverage_schema.py:10` 引用）。
> **教训**：编号是一种**命名空间**，"两个人同时加一条"就会撞 —— 这与 FC-03 是同一族。
> 现已由 `tests/test_proposals_register.py` 断言"编号唯一 + 引用存在 + 空洞写明"。

**现状（实测，由 G-7 的实现者顺带核出，探针 `temp/probe_g7_ming.py`）**：
G-7 修好了 `criterion` 的双份问题（15 个 `gate_gN` 函数体改为从 `GATES[gid]["criterion"]` 取），
但**同一形状的问题在 `criterion_revision` 上原样存在**：

- 15 道门的 `GateResult.criterion_revision` 与 `GATE_CRITERIA_REVISION[gid]` **15/15 全部不一致**；
- `GATE_CRITERIA_REVISION` 这张表在**运行期从未被读到** —— `gates.py` 只查了它的**键存在**，
  真正的值用的是函数里的字面量 ⇒ **声明表是死的，报告里印的是另一份**。

**其中 G10 的两份是"事实性对立"**（不是措辞差异）：

| 来源 | 文本 |
|---|---|
| 声明表 | "适配（实测缺口）… ⇒ 报 `unknown`" |
| 实现（`GateResult`） | "逐字照搬 §8.4（发现侧字段齐全时）" |

**为什么这是缺陷**：`criterion_revision` 记录的正是"**我们的门与参考体例差在哪、为什么**"——
它是"适配"这件事的**唯一留痕**。两份不一致时，读文档的人与读报告的人**得到相反的结论**
（一个说"这门口径已适配成交叉验证"，另一个说"这是按体例逐字做的"）。

**与 G-7 的关系**：同一次修复的**同一个形状**，只是漏了另一个字段。G-7 的实现者
**没有越界去改**（范围只到 `criterion`），而是把空档如实登记 —— 这是正确的处置。

**修法（与 G-7 同构）**：
1. 15 个 `gate_gN` 函数体的 `criterion_revision` 改为从声明表取；
2. 逐门决定"哪一份权威"并把**更完整/更准确**的那一份定为唯一来源
   （G10 尤其要人判断：是"适配成交叉验证"还是"逐字照搬" —— **这是口径决定，不是措辞统一**）；
3. 把 AST 反漂移断言从 `criterion` **扩到 `criterion_revision`**；
4. 补一条"声明表真的被读到"的断言（否则下一个人可以再把它变成死表）。

**⚠️ 一条顺带发现的测试盲点（小）**：G-6 的实现者做变异试验时发现
`_LINE_SUFFIX_RE` 去掉 `$` 锚点后**没有测试会红**（见证串 `C:/out12:30/p1.py` 被切坏，
但切坏的段仍是绝对路径 ⇒ 结论仍是 `fail`）。
也就是说"**只切尾部且必须是数字**"这条要求**缺少独立证据**。**✅ 已补**：给
`_strip_line_suffix` 加了四档点名单测（含"它不是恒等函数"的反陷阱），并**重跑该变异证明它现在会红**。

**✅ 本轮已修（实现者报告的关键内容）**：
1. 15 个 `gate_gN` + `_no_doc` 全部改为 `criterion_revision = GATE_CRITERIA_REVISION[gate_id]`；
   29 个 `GateResult(...)` 构造点全部显式传该参数。**210 个 `(门, 输入档)` 组合 0 处不一致**（修前 15/15 漂移）。
2. **发现了我没写的第三份副本**：`GateResult.criterion_revision` 的 **dataclass 默认值**
   `"逐字照搬 §8.4"` 修前从 **24 条返回路径**漏出（14 门的 `_no_doc` + 10 个"缺某项输入"分支）
   —— 于是一道**适配过**的门自称"逐字照搬"。已消掉，并由 AST 断言堵住（门内构造**必须**显式传）。
3. **"声明表真的被读到"用动态哨兵断言**（`monkeypatch` 把表里的值换成哨兵 ⇒ 报告必须跟着换），
   而不是静态查"源码里出现在取值位置"—— 后者的理由是**实测出来的**：
   `_ = GATE_CRITERIA_REVISION[gid]` 这种死代码、以及"把表里的文本抄回函数体"的死表，
   **都能骗过静态断言与逐字相等**（变异②实测：抄对文本 ⇒ 逐字相等绿、哨兵红）。
4. AST 反漂移断言扩到两栏并覆盖三种形态（字面量赋值 / 直接当关键字实参 / 漏传参数）。

**⚠️ 实现者对我这条简报的更正（有证据）**：我把 G10 的两份文本称为"**事实性对立**" ——
**不成立**。读实现（两条 `return`）+ 读测试后：两句**各说一条返回路径，都不假、也都不全**
（字段缺 ⇒ `unknown` 并逐条列出缺哪四个；字段齐 ⇒ **确实**按 §8.4 逐字判：
齐全 ⇒ `pass`，逐字引文 >20 词 ⇒ 报出来）。
所以处置**不是二选一**（二选一必然丢掉一句真话），而是**合成一句**。
真正"两句并存"的形态是**同一个门号在两条返回路径上打印两份不同的 revision**
（G10 修前 **3 份**、G5 **2 份**、其余各 2 份）—— 那才是必须消掉的，现已消掉。

**⚠️ 另一条更正（关于 G-7 的承诺）**：G-7 的 docstring 说 G4 丢掉的两档
"已在 `criterion_revision` 里如实登记为『本项目对不上』" —— **修前那句话并不存在**。
已补（G4 登记"卷内文件全被列出 / 声明字数在容差内 / 声明标签在正文存在 **本实现不判**"；
G6 登记"『数据文件』档**本实现不判**（只核 `script`）"）。
措辞刻意只断言"**本实现不判**"（可由 `gate_g4`/`gate_g6` 的代码直接验证），
**不**断言"数据模型没有对象"（那是更强的、未被逐条核实的说法）——
**这是三态纪律在文档上的又一次落地**。

---

## N-4：用 AST 扫 handler 源码来判 `side_effect` 是否如实 —— **试过，不可行**（**一个负面结果，记在案**）

**动机**：objective 的审计判据里有"**`side_effect` 与 roles 如实**"。一个自然的做法是：
对每个工具取 `spec.handler` 的源码、扫出"写/网络痕迹"、与 `spec.side_effect` 比对。

**实测（`temp\_probe_side_effect.py`，55 个工具逐个跑）**：

| 现象 | 规模 |
|---|---|
| **取不到或解析不了 handler 源码**（注册成**多行 lambda**） | **22 / 55（40%）** |
| 声明 `write_local`/`network` 但函数体里**没有任何痕迹**（因为 handler 只是**转发**到别处的 `_h_*`） | **9 个**（全部是**假阳性**：声明大概率是对的，痕迹在它转发到的那个函数里） |

⇒ **这个门不能上**。它有 **40% 的盲区**，而剩下的 60% 里还有一个**成规模的假阳性模式**。
按本项目的通用纪律（`DEVELOPMENT.md` §6 的 **P15**）：**一个会大量误报的门会被训练成噪音**，
而"红灯被训练成背景噪音"是**几乎不可逆的文化性损伤**。

**因此这一轮没有上它**，改为两件**sound** 的事：
1. `docs/ROLE-SPECS.md` §R0 的 55 行表里，**`side_effect` / 审批 / roles 三列**由
   `tests/test_role_specs_complete.py` 与**实时注册表**逐个比对
   （三列都是机器可判定的，所以这条门没有假阳性）。
   **它第一次跑就抓到 4 处真实文档漂移**：`ocr.backends`（文档 `read` / 实际 `write_local`）、
   `ocr.run`（`read` / `network`）、`search.providers`（`read` / `network`）、
   `verify.detect_verifier`（`none` / `read`）—— **读文档的人会以为那三个工具不需要审批，
   而注册表里它们需要**。四处已订正。
2. 逐工具的 `side_effect` 语义审计仍在**人工**那一档（工具层审计那一轮已修 4 处声明），
   并写进 `DEVELOPMENT.md` 的 `verify.run_experiment` 待收窄项。

**这一条的价值在于"试过并留下了为什么不行"**：否则下一个人会再写一遍同样的 AST 门，
再被 40% 的盲区与 9 个假阳性挡回来一次。

---

## N-3：`attack.check_budget` 的 `reason` **没有**打印成整个 budget 字典（**经核查不是缺陷**）

**看起来像**：实现这一批的子代理在"没做到"一节里报告 ——

> `attack.check_budget` 在 `budget` 完整时用 `f"预算完整：{ {k: budget[k] for k in _REQUIRED_BUDGET_KEYS} }"`
> —— 它打印的是**整个 budget 的字典**（即 `{k: ...}` 里的 `k` 被外层 f-string 当成了整个 dict），
> 不是那四类键。

**核查（主控实测，一条命令）**：

```powershell
python -c "import sys; sys.path.insert(0, r'D:\Incubator\agentflow\src'); \
  from agentflow.tools import attack_tools as A; \
  b={k:3 for k in A._REQUIRED_BUDGET_KEYS}; b['max_parallel_subgoals']=2; \
  print(A.check_budget(b)['reason'])"
```

实测输出：

```
预算完整：{'max_rounds': 3, 'max_parallel_subgoals': 2, 'max_persist_attempts': 3, 'max_depth': 3}
```

—— **正好是那四个必需键**，一个不多一个不少。f-string 里 `{ {...} }` 的**外层**花括号是替换字段、
**内层**是一个 dict 推导式，它按 `k` 逐键取值。所以这条**不是缺陷**。

**为什么仍记在这里**：它是**同一条经验的第二个实例**（见 `draft/18` §7.4）——
**评审者与实现者都会诊错，而"看起来像错"的写法会招来误诊**。
那句 f-string 的嵌套花括号确实**很难读**（一个熟练读者也要停下来数括号），
所以"下一批人再诊错一次"的概率不低。

**建议（不紧急，不建议为它单独改一次代码）**：把那句抽成一个具名局部变量
（`shown = {k: budget[k] for k in _REQUIRED_BUDGET_KEYS}`）再插进 f-string。
**收益是"不再招误诊"，不是功能** —— 所以它排在真缺陷后面。

⚠️ **不要**根据"有人报过这是缺陷"就去改它 —— 那正是本节要防的事。
**判据是上面那条命令的输出，不是任何人的转述。**

---

## N-1：`agent_c.gaps(submit_requests=True)` 会写 `search_requests`，而工具层声明 `side_effect="read"`

**看起来像**："权限面在说假话"（`read` 的工具其实会写）。

**经核查：不是缺陷。两句话说的是两件事**：
- **工具层的 `side_effect` 描述"默认调用"的副作用**。`submit_requests` **默认 `False`**
  （`_submit_gap_requests` 默认关闭），所以默认调用确实是纯读。
- **能力层的 `WRITE_SETS` 描述"可能写"的表**，条件性写**也算**可能写 ——
  所以 `WRITE_SETS["C"]` 必须包含 `search_requests`（已登记为受控例外）。

**为什么不能"照字面修"**：把 `graph.gaps` 标成 `write_local` 会让它被
`ToolRegistry.for_role` 的只读过滤**移出 C 的工具面** —— 于是"修一句措辞"会
**砍掉 C 的核心能力**。这是"照字面修反而更坏"的情形。

**结构上有两道防线**（都不需要新机制）：
1. **并发防线**：`WRITE_SETS["C"]` 含 `search_requests` ⇒ 调度器让 C 与 A/D **不并发**
   （`C ∩ A = C ∩ D = {search_requests}`）。这是保守方向。
2. **新增只读角色的防线**：失效点**不在 `for_role` 过滤**（它管的是工具面），
   **在 `READ_ONLY_WRITE_EXCEPTIONS`** —— 新角色若照抄这个模式而不登记，
   `assert_capabilities()` 会**当场抛**。

**已加的钉住措施**：测试断言 `"search_requests" in WRITE_SETS["C"]`，
docstring 写明"这条断言的作用是**让条件性写不会静默消失**：有人把 `_submit_gap_requests`
删掉时，这条测试会红，而不是让只读角色的写面悄悄变窄"。

---

## N-2：`E.check_formal` 的 `side_effect="unknown"`（唯一一个）

**看起来像**：声明不完整。

**经核查：这是三态纪律的正确用法**。在没有形式化检查器后端时，
"它到底写不写东西"**我读不出来**；按纪律"不知道 ⇒ 保守 ⇒ 当写者处理 ⇒ 与所有人串行"。

**代价（如实登记）**：E 因此与所有角色串行，并发度下降。
**这是一个待收窄的声明，不是终点** —— 等 `tools/verify_tools.check_formal` 的写面被读清后
（注意它也在禁改区），本条应当改成确定值。**未收窄前不许把它当"已解决"。**

> ⚠️ **已过期（2026-09-25 增补；来自 `P-13` 实测）**：本条正文里那句
> **"（唯一一个）"已经不准了**。
>
> **更正依据**：`src/agentflow/capabilities.py` 里那条 `side_effect="unknown"` 的注释
> **已经被改写**为"本条此前是 `side_effect=\"unknown\"`（『我读不出它写不写』）——
> 现在读得出来了，于是必须改成确定值 —— `unknown` 是『我不知道』，留着它就是一句已经不准的话"；
> **能力层实测 `unknown` 计数为 0**。
>
> **处置**：上面正文**原话保留**（它记录的是"当时确实只有一个、且当时读不出来"这一事实，
> 删掉它就抹掉了当时的判断依据），但**从今日起**：
> 1. 本条**不再是一条"待收窄的声明"** —— 收窄已经发生；
> 2. "E 因此与所有角色串行"这个**代价描述已经过期** ⇒ **不要**再按本条正文给 E 排串行、
>    也不要把 `unknown` 当作"当前存在的一个取值实例"去统计（今天是**零实例**）；
> 3. `unknown` 这个取值在**词表**里**仍然合法**（三态纪律不变：
>    `capabilities.UNKNOWN_SIDE_EFFECT` 与 `_WRITE_LIKE` 都保留它）——
>    所以"计数为 0"说的是**事实**，不是"这个词被删了"。**别把这两件事折叠。**

---

## G-9：`src/agentflow/**` 里仍有 **106 个零直接测试的公开函数**（等级 3/4，**本轮不强求**）

**现状（实测，可一条命令复跑）**：

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python tools/coverage_zero_test.py --json     # 逐模块清单 + 每条的 level_why
```

截至本次快照（`tools/coverage_zero_test.py` 首次落地）：

| 项 | 数 |
|---|---|
| `src/agentflow/**` 公开函数（R007 同一遍历口径，已排除 60 个嵌套定义） | 499 |
| 零直接测试 | **106** |
| ├ 等级 1（写路径） | **0** ✅ |
| ├ 等级 2（判据/决策） | **0** ✅ |
| ├ 等级 3（只读读取） | **9** |
| └ 等级 4（呈现/格式） | **97** |

逐模块（等级 3/4）：

| 模块 | 零测试条数 | 其中可能被间接覆盖 |
|---|---|---|
| `src/agentflow/cli.py` | 12 | 10 |
| `src/agentflow/claimanatomy.py` | 9 | 4 |
| `src/agentflow/schema.py` | 8 | 0 |
| `src/agentflow/providers.py` | 7 | 4 |
| `src/agentflow/tools/base.py` | 7 | 5 |
| `src/agentflow/tools/graph_tools.py` | 7 | 1 |
| `src/agentflow/agent_d.py` | 6 | 1 |
| `src/agentflow/scheduler.py` | 5 | 4 |
| `src/agentflow/textutil.py` | 5 | 0 |
| `src/agentflow/capabilities.py` | 4 | 1 |
| `src/agentflow/tokenmeter.py` | 4 | 4 |
| `src/agentflow/conductor.py` | 3 | 3 |
| `src/agentflow/dedup.py` | 3 | 1 |
| `src/agentflow/gates.py` | 3 | 2 |
| `src/agentflow/interactions.py` | 3 | 1 |
| `src/agentflow/agent_b.py` | 2 | 0 |
| `src/agentflow/agent_c.py` | 2 | 2 |
| `src/agentflow/llm.py` | 2 | 0 |
| `src/agentflow/store.py` | 2 | 0 |
| `src/agentflow/tools/doc_tools.py` | 2 | 0 |
| `src/agentflow/tools/research_tools.py` | 2 | 1 |
| `src/agentflow/cancellation.py` | 1 | 1 |
| `src/agentflow/contextbudget.py` | 1 | 1 |
| `src/agentflow/extract.py` | 1 | 1 |
| `src/agentflow/fetch.py` | 1 | 1 |
| `src/agentflow/policy.py` | 1 | 0 |
| `src/agentflow/tools/fs_tools.py` | 1 | 1 |
| `src/agentflow/tools/table_tools.py` | 1 | 1 |
| `src/agentflow/tools/trace_tools.py` | 1 | 1 |
| **合计** | **106** | **51** |

**为什么这条必须登记而不是"已经补完了"**：本轮只补了**等级 1 与 2**（那两档现在是 0）。
等级 3/4 是只读/呈现，风险低，**但它们仍然是零测试**。不登记它们，
下一个读这份文件的人会把"等级 1/2 已经清零"误读成"覆盖缺口已经补完了"。
而 `lint_rules.py` 的 R007 只数 **docstring** 缺失，**不数测试缺失** ——
所以这条缺口在**任何自动门里都不会变成红灯**，只有这张表记得它。

**为什么不由 AI 自己做完**：本轮的任务边界是"等级 1/2 全部 + 等级 3/4 登记"。
等级 3/4 有 106 条，逐条补测试是下一轮的量；而且其中 **51 条**（"可能被间接覆盖"那一列）
需要用覆盖率工具而不是名字匹配来定性 —— 那是**另一个口径**（见 G-10），
盲目补测试会写出一批"测试了一个已被别处覆盖的函数"的水分。

**判据（下一轮接手时的入口）**：`python tools/coverage_zero_test.py --level 4` 现在
以退出码 1 结束并列出全部 106 条；补完之后它应当以退出码 0 结束。

> ⚠️ **整表已过期（2026-09-25 第三轮审计实测；并入，不新增号）**：上表的每一列都已经不准。
> 实测（`python tools/coverage_zero_test.py`，**退出码 1**）：
>
> | 项 | 本文写的（第二轮快照） | 第三轮实测 |
> |---|---:|---:|
> | `src/agentflow/**` 公开函数 | 499 | **552** |
> | 零直接测试 | 106 | **114** |
> | ├ 等级 1（写路径） | 0 | 0（仍为 0，✅ 这一档没变） |
> | ├ 等级 2（判据 / 决策） | **0 ✅** | **2 ❌**（`formalgw.evidence_of`、`modelgw.gateway_main`） |
> | ├ 等级 3（只读读取） | 9 | **55** |
> | └ 等级 4（呈现 / 格式） | 97 | **356** |
> | 退出码 | 0（暗示可以关） | **1** |
>
> **更正依据**：`tools/coverage_zero_test.py`（第三轮审计与我各跑一次，结论一致）。
> **这一条的处置变了**：它**不再只是"等级 3/4 登记、本轮不强求"** ——
> **等级 2 = 2 已经把发布门弄红**，因此新增 `G-29` 专管那 2 个函数（含"补测试 vs 排除清单"的裁定），
> 新增 `G-28` 专管"文档把发布门写成全绿"。
> **本表不再是"下一轮的入口"，它是"当前的一条红门"** —— 读的人不要再按上表的数字规划。
> **为什么并入而不新增**：`G-9` 定义的就是这张表；表过期是它自己的状态过期，
> 另开一条会造成"两个号指向同一张表"（本文件第 1 条纪律禁止）。
> ⚠️ 与 `G-32` 一致：上表的数字是**计数类**，只应当以"**区间 + 观测时刻 + 命令**"引用。

---

## G-10：本轮的"零测试"判据是**按名出现**，它有两个方向的偏差，规模已量化

**现状（实测）**：`tools/coverage_zero_test.py` 的判据是"函数的限定名或裸名
作为标识符出现在 `tests/**/*.py` 里"。这条判据**可机械复跑**，但它不是"真的被调用"。

**实测到的偏差（这是本轮最有价值的一条方法论结论）**：

| 偏差方向 | 具体形态 | 实测规模 |
|---|---|---|
| **过报**（把有测试的报成零测试） | 测试名约定 `def test_<函数名>_...` 里的 `_` 既是标识符字符又是词分隔符 —— 朴素的"独立标识符"边界把整类测试名漏掉 | 补上 `test_<fn>` 约定判据后，**等级 2 的零测试函数从 31 降到 30**；单看 `interactions` 一类"测试名里有函数名"的模块影响更大 |
| **过报** | 函数**只被 src 内部间接调用**，名字从未出现在测试里 | 106 条零测试里 **51 条**属于这一类（`--json` 的 `indirect_only`），即**误报上界 48%** |
| **欠报**（把零测试的报成有测试） | 名字出现在测试的**注释或字符串**里 | 无法静态量化；用 `--json` 的 `tested_by` 逐条核（它记了命中位置与次数） |
| **欠报** | **同名顶包**：`register` 在 11 个模块里出现，测试里写一次就让 11 个都算"有测试" | `--json` 里 `tested_by` 会显示 `bare` 名命中而 `qualname` 未命中，可筛 |

**为什么不做成"按真被调用"**：那需要覆盖率/追踪，且"被调用"还要再分
"被测试调用"与"被别的 src 调用" —— 后者不是测试。本脚本把那个方向的**上界**
（`indirect_only`）算出来如实给出，而不是假装没有。

**唯一已核实的豁免**：`interactions.adjudicate_contradiction` 有 **7 条**测试
**直接**调用它（`tests/test_interactions.py`），但它的名字在那份文件里
只以 `I.adjudicate_contradiction(` 形态出现、且被脚本的边界规则判成了"未出现"。
脚本里为此有一张**可核的豁免表 `_EXONERATED`**：每条豁免必须写出覆盖它的测试函数名，
而 `_selfcheck_exonerations()` 会断言那些测试名**真的存在** ——
测试改名或被删 ⇒ 脚本以**退出码 2** 报出来。**静默豁免是本项目最忌讳的形态。**

**为什么不由 AI 改成"更准的判据"**：换判据会让**历史数字不可比**
（"上一轮 39 → 这一轮 12"这种说法失去意义）。正确处置是**两条判据都留着、
分开报告**（`tested_by` 的 `via:direct` / `via:test_name` / `via:exonerated` 三档），
并把它作为一个**已知偏差**登记在这里。

---

## G-11：脚本排除了 **60 个嵌套定义**，其中 8 个是**真正的工具 handler**

**现状（实测）**：按 R007 的遍历口径，`src/agentflow/**` 里名字不以 `_` 开头的
函数/方法有 559 个；其中 **60 个**定义在**另一个函数体**内、**私有类**内、
或 **`if __name__ == "__main__"` 自检块**内。典型：

- `agent_e.py:758 put_script`（在 `main()` 体内）；
- `agent_c.py:3113 _FakeLLM.judge_gaps`（在 `AgentC.selftest` 体内的私有类）；
- ⭐ `agent_c.py:2913 build_dataset`（在模块级 `if __name__ == "__main__"` 块里 ——
  **它不在任何函数里**，所以"父是函数"这条判据抓不到它；这是本脚本**实测漏掉过一个**
  的形态，修正后加了 `main_block` 这一档）。

**为什么排除**：这些是自检脚本的局部辅助与测试替身，给它们补测试是荒谬的，
而且会**稀释**真正需要的测试。

**代价（如实登记）**：`tools/graph_tools.py` 的 `register.graph_build` /
`register.graph_stats` / `register.graph_neighbors` / `register.graph_relations_between`
与 `tools/trace_tools.py` 的 `register.trace_*` 共 **8 个**是**在 `register()` 体内
定义的 `@tool` handler** —— 它们是货真价实的工具面。脚本的处置是
"**带 `@tool` 的嵌套 handler 不排除**"，所以这 8 个仍在统计范围内（实测它们的等级是 3）。
这条例外的理由与风险都写在这里：**一刀切会把工具从清单里静默抹掉。**

**判据**：`python tools/coverage_zero_test.py --json` 的 `excluded` 字段逐条列出
全部 60 条（含 `kind`: `function` / `private_class` / `main_block` 与一行理由）。
排除必须**可见** —— 静默排除就是抹掉缺口。

---

## G-13：形式化验证目前只到**无 Mathlib 的内核层** —— Lean/Mathlib 的**版本要求**已登记，"Mathlib 需钉版本安装"是待办

**现状（实测，逐条带证据；不是推理）**：

| 事实 | 证据（`文件:符号` 或可复跑的命令） |
|---|---|
| 本机 Lean 是 **4.7.0**（单文件发行版解压在 `D:\Incubator\temp\lean470\lean-4.7.0-windows\bin\lean.exe`） | `lean.exe --version` ⇒ `Lean (version 4.7.0, x86_64-w64-windows-gnu, commit 6fce8f7d5cd1, Release)`；`formalgw.detect_backend()` ⇒ `status='available'`、`version='Lean (version 4.7.0, …)'` |
| `formalgw.check_lean` 的 `imports` **默认 `("Mathlib",)`**（调用方不传就是它） | `src/agentflow/formalgw.py:425`；docstring `:446-448` 逐字写明"裸 `lean` 不会替你跑 `lake`：若这些模块在当前 `LEAN_PATH` 下不可用，结果是 `compile_error`（如实），而不是'没有后端'" |
| 缺 Mathlib olean 缓存时，默认参数下判成 **`compile_error`** | `python D:\Incubator\temp\W3-mathlib-probe.py` ⇒ `[Mathlib] status='compile_error' ran=True exit_code=1`，检查器原话 `error: unknown package 'Mathlib'` |
| 同一份源码在 `imports=()` 下**真的被 Lean 检查通过**（正控，不是假的） | 同上 ⇒ `[no-import] status='verified' ran=True exit_code=0 evidence_kind='proof'`，检查器原话 `'one_plus_one' does not depend on any axioms`（用时 0.39 秒） |
| `timeout` 与 `compile_error` **是两种结论，没有被折叠** | 同上 ⇒ `timeout_sec=0.001` 时 `status='timeout' ran=False exit_code=None` |

**判定**：**G（已接受的缺口）**。"本机没装 Mathlib"是**环境缺口**，**不是"没有形式化验证后端"** ——
内核层的四条硬判据（`sorry` 检出、公理审计、声明名匹配、超时与编译错误分开）已用真 Lean 4.7.0 实测成立
（正控/负控原始输出见 `draft/23-收官报告.md` §2）。

**待办（给人决策，AI 不做）**：**Mathlib 需钉版本安装**。三条理由：
1. **"钉哪个版本"是一次环境契约决定** —— Mathlib 与 Lean 工具链版本必须逐位匹配
   （本机 Lean 是 `4.7.0`，对应的 Mathlib 只能是该 toolchain 的那一版）；
   钉错版本会让"这次验证"与"下次验证"用的不是同一套数学库，而报告上看不出区别。
2. **体量与来源**：Mathlib 源码 + olean 缓存按 **GB 计**（我没实测到底多少 GB），
   下载源与校验方式要人定。
3. **装完之后默认参数才算真能用**：在那之前，调用方要么显式传 `imports=()`，
   要么就得接受 `compile_error`（这正是 §N-5 要区分的那件事）。

**判据**：`python D:\Incubator\temp\W3-mathlib-probe.py`（三行结论：`compile_error` / `verified` / `timeout`）。

> 本轮实测状态（如实，**两次观察，状态不稳定**）：`D:\Incubator\temp\mathlib-pinned\` 里有一个
> **进行中、且被重启过**的 `mathlib4` clone —— 20:56:41 观察到 **1146 个文件 / 31.6 MB**、
> `lean-toolchain`=`leanprover/lean4:v4.7.0`、`.git/HEAD`=`a45ae63747140c1b2cbad9d46f518015c047047a`；
> 约 20:58 再观察时该目录**已被重置**成 **20 个文件 / 27 KB**、`.git/HEAD`=`ref: refs/heads/.invalid`
> （又一批 `git` 进程于 20:57:21 启动）。`D:\Incubator\temp\mathlib-probe\` 只剩早期探测的 4 个文件。
> 两处都**没有 `.lake/`**、`*.olean` 计数 **0** ⇒ **`import Mathlib` 现在编译不过**，
> 本条的"待办"**尚未完成**。以上数字取自我停手那一刻，**clone 之后是否成功我没有继续跟**。

---

## N-5：缺 Mathlib 时 `check_lean` 返回 `compile_error` 而不是 `no_backend`（**经核查不是缺陷**）

**看起来像**：本机没装 Mathlib，而 `check_lean` 的默认值就是 `imports=("Mathlib",)`，
于是它直接给一个 `compile_error` —— 读起来像"这份证明编译失败了"，即"证明是错的"。

**核查（实测，一条命令）**：`python D:\Incubator\temp\W3-mathlib-probe.py` ⇒
`[Mathlib] status='compile_error' ran=True exit_code=1`，检查器原话 `error: unknown package 'Mathlib'`；
而同一时刻 `detect_backend()` 是 `status='available'`（Lean 本体在，版本 4.7.0）。
两条并排看才判得清：**问题在"库没装"，不在"检查器没在"，更不在"证明错了"。**

**为什么不能照字面修**：把这种情况改判成 `no_backend`，等于把一件**纯环境配置问题**
伪装成"环境不支持形式化验证"，调用方会据此把形式化验证整层标成"没有后端"而**不再尝试**
（`formalgw.py:446-448` 的 docstring 逐字禁止这个折叠）。`compile_error` 是**如实**的那一档：
**"查了、没编译过"**；`no_backend` 是**"没查成"**。两者与 `pass` 的关系和
`noai_gate` 的 `unknown ≠ clean` 是同一条三态纪律 —— **把"没查成"与"查了没过"折叠起来，
是本项目反复记过的最贵错误**。

**判据**：`tests/test_formalgw.py`（`compile_error` / `no_backend` / `timeout` 三档各有独立用例）。

---

# 增补（2026-09-25）：12 条新登记 + 1 条原位更正（`N-2` 已过期）

> 本节的 12 条**全部来自已实测的来源**（权限面考古 / `docs/PROPOSAL-side-effect-axes.md` §10.4、§10.5 /
> 已亲手复现 / schema 考古 / `draft/20` §11 / A·B·C 包报告第 3 条 / W1 报告自述），
> 本轮**只登记与排期，不修代码**。
>
> **分类判据只有一条：修复落点在哪** —— 落在 FC-27 禁改区（`.noai-paths` 与 `AGENTS.md` 两处清单）⇒ **P**；
> 落在非禁改区 ⇒ **G**；纯记录性更正 / 环境限制、无需修 ⇒ **N**。
> 这与原有三分类的口径有一处**需要读者注意的不一致**（我在最后一段如实写出，请裁决）：
> 本文件原有的 G 定义是"**决定暂不关**"，而本节按"落点非禁改区"把若干**AI 可修**的缺陷记成 G ——
> 它们不是"决定永不做"，而是"**本轮不修、且必须继续可见**"。
>
> **原有条目一字未删、一个号未改**（唯一动过的是 `N-2`，在它正文下面加了一段"已过期"标注）。
> 排期、批次与工作量增量见 `draft/22-企业级交付与竞争力方案（200万预算）.md` §12。

---

## P-14：只读约束**不是调用期强制** —— `ToolRegistry.call()` 里没有角色

**现状（实测，符号级）**：`tools/base.py:ToolRegistry.for_role` 是"只读角色拿不到写工具"的
**唯一实现点**，它返回的是一份**过滤后的列表**；而 `tools/base.py:ToolRegistry.call` 的**签名里**
**没有 `role`**，它按名字在**自己**的注册表里找 spec 就执行。
于是"只读"只在**装配路径**（`tools/__init__.py:build_registry` / `build_for_role`）上成立：
**任何拿到完整 registry 的路径都能调写工具**，而那一条路径上没有任何东西会红。

**影响**：这正是 FC-27 的原始失败形态 —— *"测试全绿、上线即越权"*。
今天两个只读角色（`tools/__init__.py:READ_ONLY_ROLES` 的 C/H）在**已知的**装配入口上是安全的；
不安全的是**未知入口**：未来新增的装配点、第三方注入的 registry、以及任何"顺手把 registry
直接传下去"的便利函数（`agent_h` 的 `writers` 落库代理表就是这么绕出来的，已逐点登记为例外）。
换句话说：现在的保证是"**枚举**了所有入口"，而不是"**结构上**不可能"。

**建议修法（两条，人选一条；不许两条都做）**：
1. **调用期带角色**：`call(name, args, role=...)`，且"该 spec 是否属于这个角色"的判据**取自**
   `for_role` 的同一份过滤（**不许**另写一份"哪些算写工具"的名单 —— 那是 FC-03 禁止的第二份实现）；
2. **角色视图**：`for_role` 返回一个受限视图（`RoleRegistry`），`call` **只认视图**，
   完整 registry 不再暴露 `call`。这一条更强：**"未按角色取用"在结构上不存在**。

**为什么不由 AI 做**：`src/agentflow/tools/base.py` 与 `src/agentflow/tools/__init__.py`
都在 FC-27 禁改区（`auth-audit`），理由逐字是
*"`for_role` 的结构性过滤：只读角色一律拿不到写工具 —— 它是**实现**，与上面的**声明**分处两文件，
两者必须同时人审"* 与 *"只读角色（C/H）的权限面单一来源"*。
而且这一改动改变的是**权限面的失败时点**（与 P-1 同族）——
失败时点正是"越权"这类不可逆错误发生的窗口。

**验收判据（可判定）**：
- **负控（改动前必须红）**：在 `tests/test_tools_readonly_roles.py` 加一条 ——
  拿**完整** registry、**不带角色**去 `call` 一个 `side_effect="write_local"` 的工具 ⇒ **必须被拒**。
  今天它会**成功**，所以这条负控在改动前是红的（这就是"可判定"的那一半）。
- **正控**：一条既有断言证明 `for_role("C")` / `for_role("H")` 的工具面**逐字不变**
  （"收紧"不许顺手改掉只读角色能做什么）。
- 可跑命令：`python -m pytest tests/test_tools_readonly_roles.py tests/test_tools_base.py -q`。

---

## P-15：`check_formal` 的**两层声明不一致**且无人对账（工具层 `read` / 能力层 `network`）

**现状（实测，已亲手复现）**：同一个工具在两处被声明成两件事 ——
`tools/verify_tools.py` 的工具 spec 写 `side_effect="read"`，`capabilities.py` 的能力层写 `network`。
两处**各自都自洽**，因为它们是两份字面量，中间**没有交叉断言**。
（这正是 `docs/PROPOSAL-side-effect-axes.md` §10.5 列为"必须由人裁决的事实冲突"之一。）

**影响**：审计口径随"读哪一层"而变。今天**落在判据上**的是工具层：
审批（`capabilities.NEEDS_APPROVAL`）与只读角色的剥离都按工具层 spec 走 ⇒
"一个真的会起子进程 / 触网的工具"在审批与角色剥离上被当作**纯读**。
这不是措辞问题，是"权限面在说假话"的最小实例（同族：`search.providers`、`ocr.run` 都曾如此）。

**建议修法（人选一个权威层，然后删掉另一份字面量）**：建议**工具层为权威、能力层为派生**，
并给 `capabilities.assert_capabilities()` 加一条**交叉断言**：能力层里每个工具的副作用
必须等于注册表里的声明，不一致 ⇒ 当场抛。理由：工具层是**调用期真正被读**的那一层，
能力层是它的投影；投影可以派生，**不能并列**。

**为什么不由 AI 做**：`src/agentflow/tools/verify_tools.py` 在 FC-27 禁改区（`prover-bridge`），
理由逐字是*"`detect_verifier` 与 `check_formal`：探测 Lean/Coq/Isabelle 并解释其输出 ——
桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印"*。
而且"哪一层是权威"是一次**口径决定**（与 P-3"放宽/收紧发布门的决定权在人"同族）。

**验收判据（可判定）**：
- **负控（改动前必须红）**：把两层故意改成不同值 ⇒ 新的交叉断言必须**抛**。
- **正控**：`python -c "import agentflow.capabilities"` 退出码 **0**（P-13 的 B1 既有判据）。
- 可跑命令：`python -m pytest tests/test_check_formal_wiring.py tests/test_agent_e.py -q`。

---

## P-16：`DEVELOPMENT.md` §4.3 第 1 项曾是一句**假承诺**（"六件套由 `ToolSpec.__post_init__` 校验"）—— 实现侧已由在飞包补上，**文档侧仍空且多两处漂移**

**现状（实测，来源：`docs/PROPOSAL-side-effect-axes.md` §10.4）**：
`DEVELOPMENT.md` §4.3 第 1 项逐字写着"**六件套齐全**：
`name / summary / params / returns / side_effect / roles`"，判据栏写的是
"**`ToolSpec.__post_init__`** + 实测 census"。
**我第一次实测（2026-09-25 22:18）时**，`tools/base.py:ToolSpec.__post_init__` 只核**两件**：
`side_effect` 在词表内，以及"名字里必须含 `.`（`组.动作` 形式）"——
`summary` / `params` / `returns` / `roles` **一个字都没核**。

> ⚠️ **本条登记期间实测到的事实变化（一小时之内，务必连时间一起读）**：
> **2026-09-25 22:19:35**（`tools/base.py` 的 mtime）观察到**在飞工作包 `43ce64a6`（拆轴 B1/B2）**
> 已经把这条承诺**兑现进了 `__post_init__`** —— 该方法现在的 docstring 逐字写着
> "`DEVELOPMENT.md` §4.3 第 1 项逐字声称……而实测它只校验了 `side_effect` 与『名字含 `.`』……
> **本轮把这条承诺兑现成真正的取值校验**"。
> ⇒ **本条的一半已经落地**（实现侧），而**另一半没有**：
> `DEVELOPMENT.md` 的 mtime 仍是 2026-09-24，§4.3 第 1 项**一字未改**，
> 它还带着**两处额外漂移**：判据栏写的是 `tools/base.py:198-202`（**行号**，
> 而本文件与 `AGENTS.md` 的纪律是"理由里写符号、**刻意不写行号**，行号几十分钟就漂"），
> 以及第 3 项的"**R006 有 30 条 warn**"（本轮实测：R006 共 **6** 条、全是 `info`，见 G-14）。
> **所以本条不是一个"待提案"，而是一条"待对账 + 待补负控"** ——
> 在飞包做了实现，文档与判据必须有人跟上去收口（否则"测试全绿、文档在说假话"）。

**影响**：读文档的人会以为"六件套在**注册那一刻**有断言"（**修前确实没有**），
于是把新字段的校验交给一个不存在的门。这是 FC-22（过度声称）在**文档**里的形态，
而且方向最坏 —— 它让"缺字段"这类**可机械发现**的问题退回给人读。
反过来，**实现已修而文档未改**的形态同样危险：文档会继续把复核人引向
"这里没有断言"，让他**重复一次已经做完的工作**（与 G-15 是同一个病）。

**建议修法（按当前实测状态，只剩 (b) 与 (c)）**：
- (a) ~~把六件套下沉进 `__post_init__`~~ —— **已由在飞包 `43ce64a6` 在 22:19:35 落地**；
  本条**不再要求人重做**，只要求**核对**（跑它的负控，见下）。
- (b) 把 §4.3 第 1 项按**当前实现**改写：写清"**哪一件由哪一层核**"，
  把 `tools/base.py:198-202` 这类**行号**换成**符号**，并订正第 3 项的 R006 条数（`30 条 warn` → 实测口径）；
- (c) 给"六件套齐全"补一条**负控**（缺 `summary`/`params`/`returns` 的 spec 必须被拒）——
  今天 `__post_init__` 里有实现，但我**没有**核到一条直接钉住它的负控；
  "有实现、没负控"正是本文件反复记的形态（G-4：判据在 36/55 个工具上真空通过）。

**为什么不由 AI 做**：实现侧 `src/agentflow/tools/base.py` 在 FC-27 禁改区（`auth-audit`）
⇒ 该处由在飞包的人审通道处理；
(b)(c) 的落点是 `DEVELOPMENT.md`（非禁改区）**+ 一条新测试**（非禁改区），
但 (b) 必须**等 (a) 稳定**（在飞包还在同一目录里写文件，见 `draft/22` §12.2 的事故记录），
否则文档会追着一个还在动的实现跑。

**验收判据（可判定）**：
- **负控（核 (a) 是否真的落地）**：构造一个"`side_effect` 合法、但
  `summary`/`params`/`returns` 缺项"的 spec，断言它**在 `__post_init__` 里被拒**；
  今天（22:19:35 之后）**应当已经是绿的** —— 若它**红**，说明在飞包的落地不完整，
  本条要退回给那个包；若**绿**，则本条只剩 (b)(c)。
- **(b) 的可跑判据**：一条文档自检 —— "§4.3 第 1 项声称由 `__post_init__` 核的字段集合"
  必须等于"该函数真正核的字段集合"，且该表里**不许出现行号**（`文件:行` 形态 ⇒ 红）。
- 可跑命令：`python -m pytest tests/test_tools_base.py tests/test_tools_returns_declaration.py -q`。

> ⚠️ **原位追加（2026-09-25 第三轮审计；并入，不新增号）**：实现侧（在飞包 `43ce64a6`）
> 已经把六件套校验落进 `__post_init__`，但**第三轮实测发现"六件套"里仍有一件从来没被核过**：
> `roles` **从不校验** —— `grep -n 'self.roles' src/agentflow/tools/base.py` 只命中 `to_dict`
> （即它只被**打印**，从未被**断言**）。当前 `__post_init__` 真正强制的集合是：
> `side_effect ∈ SIDE_EFFECTS`、`external ∈ EXTERNAL`、名字含 `.`、`params` 根为 object、
> `summary` 非空、`returns` 非空 —— **`roles` 不在其中**。
>
> **这条追加把 `P-16` 的剩余范围钉死了**：(b) 文档改写时必须**明写 `roles` 没有任何断言**
> （否则"六件套齐全"这句话在修完之后**仍然是假的** —— 只是假的程度变小了）；
> 若要做 (a) 的第二步，`roles ⊆ schema.ROLES` 这条断言应当**同时**落进 `__post_init__`
> （与 `P-1` 的"注册期 fail-closed"是同一件事，**不要写成第二份实现**）。
> **判据增量**：`python -c "import re,pathlib;t=pathlib.Path('src/agentflow/tools/base.py').read_text(encoding='utf-8');print(t.count('self.roles'))"`
> ⇒ 今天 = **1**（只在 `to_dict`）；做完 (a) 第二步后应 ≥ 2。

---

## P-17：`task_id` 的"**不占 4 位编号空间**"没有任何断言守着

**现状（实测，来源：schema 考古）**：`schema.py:Task.task_id` 的注释逐字是
`# "t-NNNN"（过程记录，不占 4 位编号空间）`；`DEVELOPMENT.md` 的"过程记录 ID"一行也逐字写
"`<前缀>-NNNN`（`r-` / `p-` / `t-`），**不占 4 位空间**"。
而这条契约**唯一**的"实现"是：`schema.py:ID_COUNTERS` 的键里**恰好没有** task ——
**一个"缺失"在替一条"契约"说话**。守着 4 位空间的是另外两处：
`schema.py:is_valid_id` 与 `store.py:MAX_ID` / `store.py:alloc_id`（用满即 fail-closed 抛错）。

**影响**：有人给"任务号"装一个计数器（或把 `t-` 塞进 `ID_COUNTERS`）时，**没有任何东西会红**：
`is_valid_id` 只看形状（前缀 + 4 位），于是"占不占号空间"这件事在测试里**不可判定**。
一旦真的占了，`interactions.py:next_prefixed_id` 静默越界出 5 位号的口子（P-4）就多一个入口。

**建议修法**：把这条契约变成**一条正控 + 一条负控**：正控断言
`set(ID_COUNTERS) ∩ {过程记录前缀}` 为空（"不占"从此有判据）；
负控把 task 前缀塞进 `ID_COUNTERS` ⇒ 断言红。**不要把注释删掉了事** ——
删注释会把"不占"从文档里也抹掉，于是连"契约曾经存在"都查不到了。

**为什么不由 AI 做**：`src/agentflow/schema.py` 在 FC-27 禁改区（`schema-migration` 与
`eval-criteria` 两类），理由逐字是*"`SCHEMA_VERSION` 与 `TABLES`：表结构与版本号 ——
改它等于改磁盘格式契约"*。而且"过程记录 ID 到底占不占号空间"是一次**契约口径**的确认。

**验收判据（可判定）**：上述正控 + 负控各一条；可跑命令
`python -m pytest tests/test_schema.py tests/test_store_alloc_guard.py -q`。

---

## P-18：`.noai-paths` 给 `interactions.py` 的**理由写错了**（矩阵不在那里，`admitting` 全仓不存在）

**现状（实测，来源：`draft/20-管理层与责任链的重设计草案.md` §11 第 1 项）**：
`.noai-paths` 与 `AGENTS.md` 的 `NOAI-MANIFEST` 区块**两处逐条一致地**写着
``src/agentflow/interactions.py`` `[category: auth-audit]` 的理由是
"`check_conflict` / `admitting` 一类的角色间交互与授权规则（**A–H 的调用矩阵**）"。
实测：**A–H 调用矩阵的权威定义在 `capabilities.py:ALLOWED_EDGES`**；
`interactions.py` 里**没有任何矩阵 / 角色 / 边符号**；
**`admitting` 这个符号在全仓不存在**。

**影响**：禁改区的**理由**是"人审该看什么"的唯一指针。理由写错 ⇒ 复核人按"矩阵"去读
`interactions.py`，找不到矩阵（于是要么放过、要么转去审 `capabilities.py` ——
而那一处**不在**清单里）。这是"声称 vs 实现"的不一致，而且落在**机器会强制**的清单上。

**改动必须两处同步（这是硬约束，不是形式）**：`.noai-paths` 与 `AGENTS.md` 必须**逐条一致**；
`scripts/noai_gate.py:check_manifest_consistency` 按 `(glob, category, 理由)` 三元组**按位比对**；
只改一处 ⇒ `python scripts/noai_gate.py --check-consistency` 以**退出码 2** 失败。

**建议修法**：由人重写这条理由，指向 `interactions.py` 里**真实存在**的符号与真实风险面
（`check_conflict` 是真的，留着；把"矩阵"这个词去掉或改指它真正在的地方），
并按事实决定**要不要把 `capabilities.py` 的矩阵登记进清单** ——
那是**清单面的扩张**，需要人判断"矩阵真身不在清单里"算不算一个洞。两处同改。

**为什么必须人单独做**：`.noai-paths` **自身**就是禁改区条目（`auth-audit`），
台账那一条的理由"改它等于改审计记录本身"同一条纪律适用 ——
**清单是门的输入，改清单等于改门的判据面**。此外这里还夹着一次口径决定（矩阵真身要不要入清单）。

**验收判据（可判定）**：
- `python scripts/noai_gate.py --check-consistency` 退出码 **0**（两处同步）；
- `python -m pytest tests/test_noai_gate.py -q`（其中 `test_python_manifest_referenced_symbols_exist`
  要求理由里用反引号写的**符号真的存在于对应文件** —— 重写后的理由必须过这一关，
  而 `admitting` 这种不存在的符号按设计会被它抓住）；
- **负控**：只改 `.noai-paths` 不改 `AGENTS.md` ⇒ 退出码 **2**（不是 0）。

---

## G-14：R006 的判据是**文件级共现** —— 它在最该抓的文件上给出的指针是错的

**现状（实测，本轮复跑并附原始输出）**：`scripts/lint_rules.py:rule_R006_read_tool_touches_network`
的判据**两半都在文件层**：① 文件里出现字面量 `side_effect="read"`；
② 文件里出现 marker 表（`urllib` / `http.client` / `socket` / `subprocess` / `requests.` /
`httpx` / `easyocr.Reader`）里任一**字面 token** 的非注释行。该规则自己的 docstring 已写明
"**判据是文件级共现** ……不是缺陷证据"。

本轮 `python scripts/lint_rules.py --json <out>` 的 R006 命中（`path` / `line` 取自 JSON，
文本输出**不打印 path**）：

| `path` | `line` | 那一行是什么 |
|---|---:|---|
| `src/agentflow/tools/search_tools.py` | **51**（附 265） | `import urllib.parse` / `urllib.parse.quote(...)` —— **URL 百分号编码，与网络无关** |
| `src/agentflow/tools/ocr_tools.py` | 43 | 同类 marker token |
| `src/agentflow/tools/research_tools.py` | 404 | 同上 |
| `src/agentflow/tools/table_tools.py` | 1101 | 同上 |
| `src/agentflow/tools/verify_tools.py` | 109 | 同上 |
| `src/agentflow/agent_c.py` | 3385 | 同上 |

**⚠️ 对来源简报的一处更正（我实测到的与简报不同，请裁决）**：来源说
"`search_tools.py`（三个真 HTTP 工具）**一次都不触发**"。实测：`search_tools.py` **有一条 R006 命中**
（`line=51`），但那一行是 `import urllib.parse`。我判断简报想说的是
"**它从来没有指到那三个真 HTTP 工具**"——那个更强的说法**成立**，且机制清楚：
1. `search_tools.py` 里**唯一**声明 `read` 的工具是 `search.dedup_check`（本地判重，不联网）；
   三个真发 HTTP 的工具（`search.providers` / `search.literature` / `search.download`）
   声明的是 `side_effect="network"` ⇒ **本规则按设计就不该点它们**；
2. 该文件的 HTTP **不是自己发的**，是转发到本项目自己的封装
   （`tools/search_tools.py` 里的 `P.http_get_json`）⇒ marker 表（只有裸 token）**认不出这种形态**；
   于是文件级共现给出的"指针"落在 `urllib.parse`（纯粹的 URL 编码）上。
3. **文本输出不打印 path**：`scripts/lint_rules.py` 的 `main` 渲染分支里，
   `error` / `warning` 打印 `path:line`，而 **`info` 只打印 `rule + message`** ——
   于是人读那份报告时**根本不知道这 6 条是 6 个文件**（本轮是我加 `--json` 才拿到 `path` 的）。

**判定：G（已判定是缺陷，本轮只登记不修）**。落点 `scripts/lint_rules.py`
**不在** FC-27 禁改区（`.noai-paths` 与 `AGENTS.md` 两处清单里都没有它）⇒ **AI 可做**。
之所以仍记成 G 而不是"顺手改掉"，是因为**改判据会让历史命中数失去可比性**
（与 G-10 同一条理由：口径一换，"上一轮 6 条 → 这一轮 N 条"就不再有意义），
而这条规则**是被刻意校准成低噪音指针的**（第一版逐行 warning 在真实代码上产生 19 条噪音，
后降级为每文件一条 `info`；它公开承认自己"不冒充缺陷"）。

**为什么不能照字面修**：**不许删 R006**（"少一道门"与"多一道噪音门"都不对，
见 `DEVELOPMENT.md` §6 的 P15 与 G-10 的处置）；**也不许**把 marker 表简单扩成"扫 `http` 字样"——
`urllib.parse` 正是那种会立刻把门变成噪音的假命中（本轮 6 条里至少 1 条已是这种形态）。

**建议修法（两条，建议一起做）**：
1. **判据降到工具级**：按工具的注册名 / `ToolSpec.handler` 归属把"哪些 read 工具"与
   "哪一行网络痕迹"配对，命中精确到 `工具名:行`；**并且**把 `path` 补进 `info` 的输出
   （这是最小的一步，收益最大：人读的那一行必须能定位）；
2. **marker 表承认"本项目自己的出口"**：把 `providers.http_get_json` / `fetch.*` 这类封装加进判据，
   或反过来要求"所有出网只经一个出口"，再据此判"read 工具是否**间接**出网"。

**验收判据（可判定）**：
- **正控（今天红）**：造一个声明 `read`、且**通过本项目自己的封装真出网**的 handler
  ⇒ R006 必须点名**那个工具**（今天不点，因为 marker 表不认这个形态）；
- **负控**：`search.dedup_check`（声明 `read`、只做本地判重）**不许被点名** ——
  防的是"加判据把门变成噪音"（噪音化的门会被训练成背景，见 G-10 的方法论结论）；
- 可跑命令：`python scripts/lint_rules.py --json <out>` 后逐条核对 R006 的 `path` / `line`。
  本轮基线：R006 共 **6** 条（均 `info`）、全库 `error 0` / `warning 2` / `info 15` ——
  改动后 R006 的**条数与指向都应当变化**，而 `error` 仍须为 **0**。

**与在飞工作包的关系**：`scripts/lint_rules.py` 同时被在飞工作包 `43ce64a6`（拆轴 B1/B2）改动
⇒ 本条**排在它之后**（理由见 `draft/22` §12.2）。

---

## G-15：`ROLE-SPECS.md` 的一条"没能核实"**已经过期** —— 它说 `tests/test_noai_gate.py` 不存在

**现状（实测，来源：`draft/20` §11 第 2 项）**：`docs/ROLE-SPECS.md` 的"缺口登记"表里
第 11 行逐字写着"**`scripts/noai_gate.py` 声明了 `tests/test_noai_gate.py` 的负控用例，
但该测试文件不存在**"，等级标 **高**。实测：`tests/test_noai_gate.py` **存在**。

**影响**：这是**虚证的反向形态** —— 一条**已经补上**的缺口被继续报成"高"级未修。
读的人会去"补一个已经存在的测试"；更坏的是，他会开始**不再相信这张表里的其他每一条**。
与 G-9 / G-10 同族：清单的全部价值在于"它说的与事实一致"。

**判定：G（已判定是缺陷，本轮只登记不修）**。落点 `docs/ROLE-SPECS.md` **不在**禁改区 ⇒ **AI 可做**。
之所以不顺手改，是因为**这一行没有判据守着**：`tools/verify_role_specs.py` 与本仓的结构门
核的是 §R0 的全局工具总表（工具数 + `side_effect` / 审批 / `roles` 三列 ↔ 实时注册表），
而**这张"缺口登记"表不在它们的比对范围内** —— 也就是说：**改这一行不会有门变红，不改也没有门变红**。
（这一句是本条最要紧的部分：先把"它为什么能长期错着"写下来，否则下一个人只会再订正一次。）

**为什么不能照字面修**：**不许只改这一行字**。只改一次表态、不把这张表纳入机械判据，
它下一次还会漂（本项目实测过：一份没有判据的"没能核实"清单，漂了没人知道）。
正解是"改这一行的**同时**给这张表一条最小判据"。

**建议修法**：①订正该行（`tests/test_noai_gate.py` 存在，并列出它实际覆盖的负控用例名）；
②给"缺口登记"表加一条**可判定的存在性断言**：表里提到的每个路径 / 符号都必须存在 ——
这条与 `noai_gate.py` 的 `test_python_manifest_referenced_symbols_exist` 是**同一个形状**，
直接抄它的形态，**不要**新造一套编号或口径。

**验收判据（可判定）**：
- **负控（改动前必须红）**：新增断言"`ROLE-SPECS.md` 的缺口表里提到的每一个路径都存在"
  ⇒ 它**今天**就会红（因为该行声称 `tests/test_noai_gate.py` 不存在），订正后转绿；
- 如实写明一条**不是**判据的命令：`python -m pytest tests/test_role_specs_complete.py -q`
  **今天就是绿的** —— 它守的是 §R0 那三列，守不住本表。免得下一个人以为门已经守住了。

---

## G-16：FC 覆盖矩阵**自相矛盾** —— 同一条 FC-05/17/19 在两处是两个互斥状态

**现状（来源：`draft/20-管理层与责任链的重设计草案.md` §11 第 3 项，逐字采信）**：
"FC 矩阵内部自相矛盾（**FC-05 / FC-17 / FC-19** 在 §9.1 标『部分/未落地』，
在 §9.2/§9.3 标『✅已落地』）"。矩阵本体在
`draft/13-数学研究多智能体协同框架-正式设计草案.md` 的 §7（FC-01…FC-27 覆盖矩阵）
与 §7.1（未落地 / 部分落地的完整清单）；本方案 `draft/22` §5.3 的 P2 / P3 阶段门按这些状态排。

**影响**：同一条经验在两份表里有两个状态 ⇒ **按哪一行给 P2 / P3 排版期都可以自证**。
这与本项目最贵的一条纪律直接冲突："一个数字是什么由口径决定"（`EVAL_REQUIRED_FIELDS` 同类）。
具体后果：FC-05（保序字段）/ FC-17（上下文预算）/ FC-19（token 预算与重试计费）
若按"已落地"排，P2 / P3 里对应的那部分工作会被**静默跳过**。

**判定：G（已判定是缺陷，本轮只登记不修）**。落点 `draft/*.md` **不在**禁改区 ⇒ 文本可由 AI 改；
但**"落地"这个词的可判定定义只能由人给**（这是一次口径决定），所以本轮只登记。

**为什么不能照字面修**：**不许**直接把两处改成一个值 —— 那等于**替人选定口径**
（"部分落地"与"已落地"是同一条经验的两个强度，哪个为真取决于"落地"怎么定义）。
本项目已有先例：G10 的两份门判据文本"各说一条返回路径，**都不假、也都不全**"，
正解是**合成一句并保留两边**，不是二选一（见本文件 G-7 的"⚠️ 更正"段）。

**建议修法**：①人给"落地"一个可判定定义（建议与 `draft/22` §7.2 的 DoD 同形：
**有可跑的测试或门 ⇒ 已落地；只有实现、没有判据 ⇒ 部分；只有设计 ⇒ 未落地**）；
②按该定义**逐行重算**矩阵，并**保留旧标注**（三列：旧标注 / 新标注 / 依据），不许覆盖；
③给矩阵加一条可跑的检查：**同一条 FC 在矩阵内只能有一个状态标签**。

**验收判据（可判定）**：
- **负控**：把一条 FC 人为写成两个状态 ⇒ 新增检查必须红；
- 可跑命令：一个小脚本（建议与 `tools/verify_role_specs.py` 同族的位置，
  **不要**新建第二份编号 / 口径体系）。**今天没有任何检查** ⇒ 本条的存在性
  是**人读出来的**，登记在此正是为了让下一次不必重新推。

> ⚠️ **原位追加（2026-09-25 第三轮审计；并入，不新增号）**：本条原来只点了 **FC-05 / 17 / 19**
> 三个号"两处不一致"。第三轮把范围与形态都量清了，**其中一条还是三态**：
>
> | FC | §9.1 主矩阵 | §9.2 清单 | §9.3 未核实清单 / §8.4 待办 | 实测 |
> |---|---|---|---|---|
> | **FC-17** | **部分** | — | §9.3 标"✅ **已落地**"、§8.4 待办 2 标"✅ **已关闭**" | **"部分"才对**（**三处三态**） |
> | **FC-19** | **未落地** | "**仍未关**" | §9.3 标"✅ **已落地（召唤级）**" | 两处对立，且**两处都不准**：写入方已接线、但归因缺失（见 `G-31` / `G-20`） |
>
> **FC-17 的实测证据（这条把"三态"从纸上争议变成可判定的红）**：
> `tests/test_fc17_wiring.py` **单独跑 = 6 failed / 4 passed**（连同 `tests/test_context_budget.py` 共 9 failed），
> 而全量 `pytest -q` 里全过 ⇒ "部分"是唯一站得住的标注。
> ⇒ 由此**派生出一条独立登记**：`G-27`（测试顺序依赖 —— 绿灯是排序给的）。
> **本条不吸收 `G-27`**：`G-16` 管"矩阵里的状态标注自相矛盾"，
> `G-27` 管"判据依赖执行顺序"，两件事的修法完全不同（改文档标注 vs 加一条逐文件门）。
>
> **结论**：本条的判据（"同一条 FC 在矩阵内只能有一个状态标签"）**从 3 个号扩到全部 27 条**，
> 且**至少 FC-17 是"三处三态"**（不是两处）—— 这比本条原来的描述更严重：
> 两处不一致还能靠对读发现，**三处不一致会让任何一处看起来都像是笔误**。

---

## G-17：`scripts/noai_gate.py` **自己**没有 stdout 编码兜底 ⇒ 门会以"崩"的形式结束

**现状（实测，来源：A/B/C 包报告第 3 条）**：`scripts/noai_gate.py` 会打印 reviewer 姓名与
中文路径 / 中文理由，但它**没有**任何 stdout / stderr 编码兜底 ——
在 84 KB 的脚本里搜 `reconfigure` / `PYTHONIOENCODING` / `errors=` 都是 **0 命中**。
在 GBK 控制台（Windows 默认代码页 936）下打印含中文的 reviewer 姓名 ⇒ `UnicodeEncodeError`。

**影响**：这是三态纪律在**门自己身上**的失效。门的退出码契约是
`0 = clean` / `1 = requires_human` / `2 = unknown`；异常逃逸时退出码是**另一个数**，
与三者都不同 —— 于是 CI 日志上"**门自己崩了**"、"**门查不下去了**"、"**命中了**"
看起来都是"这次没通过"。`AGENTS.md` 逐字写着"`unknown` **绝不是** `clean`"，
而这里更糟：**崩溃连 `unknown` 都不是**（同族：`formalgw` 的 `timeout` 与 `compile_error`
不许折叠；本条的折叠发生在**退出码**这一层）。

**判定：G（已判定是缺陷，本轮只登记不修）**。落点 `scripts/noai_gate.py` **不在** FC-27 禁改区
（清单里只有 `scripts/release_check.py` 与 `tools/release_all.py`）⇒ **AI 可做**；
而且它是本轮**唯一**与三个在飞工作包**完全没有同文件**的一条（见 `draft/22` §12.2）。

**为什么不能照字面修**：**不许**把 `print` 逐处改成 `print(...encode('gbk','replace'))` ——
那是把编码口径散进 N 个调用点（FC-03 同族："同一判据只有一份实现"）。
**也不许**只加 `try/except` 吞掉异常 —— 那会把"打印失败"变成"静默少打一行"，
而**少打的那一行可能正是 requires_human 那一条**。

**建议修法**：在 `main()` 的**唯一入口**处做一次编码加固
（`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，`stderr` 同理），
并把"输出写入失败"**显式映射成退出码 2（unknown）** + 一行说明，
使门的输出契约在**任何代码页**下都只有 0 / 1 / 2 三个值。

**验收判据（可判定）**：
- **负控（改动前必须红）**：`$env:PYTHONIOENCODING='gbk'`（或 `chcp 936`）下跑
  `python scripts/noai_gate.py --paths <4 个禁改区文件>` ⇒ 断言**退出码 ∈ {0,1,2}**
  且输出里**不出现** `Traceback`（今天会崩 ⇒ 这条在改动前是红的）；
- **正控**：UTF-8 默认环境下输出与今天**逐字一致**（加固不许顺手改口径）；
- 日常"没改坏"检查：`python scripts/noai_gate.py --check-consistency` 退出码 **0**。

---

## G-18：`formalgw` 默认 `imports=("Mathlib",)` ⇒ 未装全库 Mathlib 的环境**第一次调用就 `compile_error`**

**现状（实测，来源：W1 报告 + `draft/23-收官报告.md` §3）**：`formalgw.py` 的 `check_lean`
默认 `imports=("Mathlib",)`；在缺 Mathlib olean 缓存的机器上（含本机）
`status='compile_error'`，检查器原话 `error: unknown package 'Mathlib'`；
而同一时刻 `formalgw.detect_backend()` 是 `status='available'`（Lean 4.7.0 在）。
证据出处：`draft/23` §3 的 W1 现状（**未完成，如实写**）与
`D:\Incubator\temp\W3-mathlib-probe.py` 的三行输出。

**判定：G（已判定是缺陷，本轮只登记不修）** —— **与 N-5 不矛盾**：
`N-5` 说的是"**不许**把这种情况改判成 `no_backend`"（那会把"没查成"伪装成"环境不支持"，方向错）；
本条说的是另一件事：**`compile_error` 这个结论不够自解释** ——
它读起来像"这份证明编译失败了（= 证明错了）"，而真实原因是"**库没装**"。

**影响**：任何在没有全库 Mathlib 的环境上跑第一次形式化检查的人，
都会拿到一个"**证明错了**"形状的结论；这条**已实测**导致过误读
（`draft/23` §3 与 `N-5` 都是为纠正这个误读而写的）。对 `draft/22` 的 **P2** 阶段更直接：
P2 的 DoD 是"Lean 4 + pin 版 Mathlib 可编译一个引理文件"——
在 Mathlib 未装成之前，P2 的每一次调试都发生在这种输出上。

**为什么不能照字面修**：**不许**把默认值改成 `imports=()` ——
那会把"用 Mathlib 验证"悄悄降级成"用内核验证"（**两者是不同的证据等级**，
而报告上看不出区别）；**也不许**在缺库时静默回退到无 import。
正解是**把原因随结论一起返回**（这也正是 `N-5` 保留 `compile_error` 那一档的理由）。

**建议修法**：默认值**保留** `("Mathlib",)`；在 `compile_error` 的结果里**附一栏可判定的归因**
（`reason` / `scope_caveat` 里写清"本次 `imports=('Mathlib',)` 在当前 `LEAN_PATH` 下不可用"，
其判据由一次"`import Mathlib` 能否解析"的探测给出），并同步更新
`docs/ROLE-SPECS.md` §R0 的 `verify.*` 行（那一行已被结构门与实时注册表逐列比对）。

**验收判据（可判定）**：
- **负控（改动前必须红）**：缺 Mathlib 的环境下（本机）调 `check_lean`，
  返回里**必须能读出"缺库"这一栏**（今天读不出 ⇒ 改动前是红的）；
- **正控**：`imports=()` 下仍 `verified`（`W3-mathlib-probe.py` 的 `[no-import]` 行）；
  `timeout` 仍是 `timeout`，`compile_error` 仍是 `compile_error`（**三档不许折叠**）；
- 可跑命令：`python D:\Incubator\temp\W3-mathlib-probe.py` 与
  `python -m pytest tests/test_formalgw.py -q`。

**与在飞工作包的关系**：`formalgw.py` 同时被在飞工作包 `3da8c5e0` 改动 ⇒ 排其后。

---

## N-6：Mathlib 证据的**环境非原样**（为编 NormNum 放了 14 个 proofwidgets stub JS）（**经核查不是缺陷**）

**看起来像**："证据是造出来的" —— 为让 NormNum 编过，**放了 14 个 proofwidgets stub `.js`**。
**来源：W1 报告自述**：不影响证明可靠性，但复现**不是逐字原样**。

**核查：这是两件不同的事，必须分开说清**：
1. **证明可靠性不受影响**：Lean 侧真正判"证明对不对"的是 `formalgw` 的四条硬判据
   （`sorry` 检出 / 公理审计 / 声明名匹配 / 超时与编译错误分开），它们读的是**检查器输出**，
   与那 14 个 JS stub 是不是上游原版**无关**；
2. **"环境原样"这个说法在这一项上不成立**：stub 是**人为放置**的文件 ——
   这不影响结论，但它是一条**必须可见**的边界。

**为什么不是缺陷**：环境构造（装什么、补什么 stub）**不是本项目的代码**，
也不是任何门的判据；清单里没有一条规则要求"环境必须与上游逐字相同"。
按本节的三分类，"记录性更正 / 环境限制、**无需修**" ⇒ **N**。

**为什么不能照字面修**：**不许**把那 14 个 stub 删掉 —— 删掉 NormNum 就编不过，
**证据反而消失**（"照字面修反而更坏"的又一例，与 N-1 同形）。
正解是**登记 stub 清单 + 内容哈希**，让"原样"这个词有一个可判定的边界：
要么在复现报告里逐字写明"这 14 个文件**不是**上游原样"并附清单与 hash，
要么把整份 stub 目录归档成可复算的产物。

**判据（可判定）**：复现报告里必须能查到那 **14 条 stub 的清单**（文件名 + hash，目录与计数由
W1 报告给出）；查不到 ⇒ 该报告"环境原样 / 可逐字复现"的说法**不成立**。

---

## N-7：**我自己的报告错误**——欠人审批是 **14 条**（不是 8 条），且 `reviewers` 全部为空（**记录性更正**）

**看起来像**：一条已经登记在案的"欠人审批"数字。此前多轮（我自己写的）报告里，
这一栏一直写的是"**欠人：8 个文件 × 2 reviewer**"。

**更正（实测，本轮复跑）。更正自 8 → 14：**

| 口径 | 旧报告 | 实测（本轮） | 证据 |
|---|---|---|---|
| 条目数 | **8**（"8 个文件"；`draft/23-收官报告.md` §4.1 的标题口径是"**四个**禁改区文件：各需 2 名 reviewer"，4 × 2 = 8 **份批准**） | **14 条 entry**（14 个不同的 `path`，5 个类别） | `.noai-approvals.json:entries` |
| 已完成的人工走查 | （未核） | **0**（`reviewers` 元素**合计 0**） | `.noai-approvals.json:entries[*].reviewers` |

⇒ 准确的说法是：**14 个禁改区条目全部未获批准**；按"条"计，欠 **14 × 2 = 28 份** reviewer 走查记录。

**为什么这不是代码缺陷**：台账**没坏**、门**没坏** ——
`scripts/noai_gate.py --check-approvals` 如实报 `insufficient_reviewers`。
坏的是**我的报告口径**：我按"文件数 × 批准数"报，而台账是按"**条目**"记的
（同一条规则下 `pyproject.toml` 与 `scripts/release_check.py` 是**两个**条目）。**记录性更正 ⇒ N。**

**但它必须进登记**：否则下一个人会按 **8** 去安排人审，**直接漏掉 6 条** ——
而漏掉的那几条里包括 `src/agentflow/tools/base.py`、`src/agentflow/tools/__init__.py`、
`src/agentflow/schema.py`、`src/agentflow/verify.py`（**权限面与 schema 契约**，
正是"错了不可逆"的那一类）。

**为什么不能照字面修**：**不许**把 14 条改成 8 条（那是删审计记录）；
**绝对不许**由 AI 往 `reviewers` 里填 —— 台账自己的理由逐字是
*"批准是**人**的动作，AI 不许代填 `reviewers`"*，且 `ledger_self_approval` 是一条显式理由码。
唯一的"修"是**人的逐行走查 + 署名的 reviewers**（每文件 2 名）。
**本轮 AI 一个字节都没写进该文件。**

**判据（可判定，一条命令）**：

```powershell
cd D:\Incubator\agentflow
python -c "import json;d=json.load(open('.noai-approvals.json',encoding='utf-8'));print(len(d['entries']), sum(len(x['reviewers']) for x in d['entries']))"
```

今天 ⇒ `14 0`；全部走查完成后 ⇒ `14 28`（14 条 × 2 名）。
**负控**：若输出是 `8 …`，说明有人按旧口径删了记录 —— 那是审计记录被损坏，不是"修好了"。

---

## 增补节的自我申明（一处分类分歧 + 一处口径分歧，请裁决）

1. **分类分歧（G 这个词被我用得比原定义宽）**：本文件开头的表把 G 定义成
   "**已判定是缺陷，决定暂不关**"，"谁来关"一栏写"**每次发布时重新确认一次**"。
   本节按"**修复落点不在禁改区**"把 `G-14`…`G-18` 记成 G ——
   它们不是"决定永不做"，而是"**AI 可做、但本轮不修，且必须继续可见**"。
   两条读法会导致完全不同的排期（"发布时确认" vs "排进 `draft/22` 的工作包"）。
   我按后者排的期（见 `draft/22` §12），**若你裁定 G 只用于"永不关"，
   则 `G-14`…`G-18` 里至少有 4 条应当另立一类或直接指派给 AI 做**。
2. **口径分歧（"哑火"到底是 0 命中还是指错行）**：见 `G-14` 的"⚠️ 更正"段 ——
   来源说 `search_tools.py` "一次都不触发"，我实测是"**有 1 条、但指到了 `urllib.parse`**"。
   两种读法**指向同一个修法**，但**验收判据不同**（前者要求"从 0 变 ≥1"，后者要求"指向换人"）。
   我在 `G-14` 里按**实测**写了判据，并保留来源的表述在案。

---

# 增补（第二轮，同日）：只读审计 `8e4373ec` 的 13 条

> 来源：`D:\Incubator\temp\REPORT.md`（一次**只读**穷举审计：55/55 个工具逐个实调 +
> 定向子进程/OCR 探针 + AST/文本词表扫描；证据脚本 `audit_effects.py` / `audit_targeted.py` /
> `audit_dead.py`，逐处引用在 `audit_*.out`）。**该审计未改仓库任何文件。**
>
> **第一轮的 12 条没有被重做**：本节只追加这 13 条，编号接着第一轮往下排
> （`P-19`…`P-23`、`G-19`…`G-26`；N 类本轮无新增，故 `N` 仍到 `N-7` 为止 —— **无空洞**）。
> 分类判据与第一轮**逐字相同**：**最小修法必然要改禁改区文件 ⇒ P；能在非禁改区完成 ⇒ G；
> 纯记录性更正 / 环境限制、无需修 ⇒ N**（另有一条我判成 P 但可辩成 G 的，写在每条里并汇总在最后）。
>
> 这 13 条里有 **4 条**（`P-21`…`P-23`、一部分 `G-24`）是"**受控词表与产出不符**"，
> 而它们**全部**是人扫出来的 —— 因为**没有判据**查这件事（`G-26`）。
> 也就是说：`G-26` 不是一个缺陷，它是**这一整族缺陷不可见的那个原因**。

---

## P-19：只读角色 **H 手里有"起外部检查器"的能力** —— `check_formal` / `detect_verifier` 声明 `read`、实现起子进程

**现状（实测，来源：`temp\REPORT.md` §两层不一致 与 §判据能不能判）**：
- `tools/verify_tools.py::check_formal` 声明 `side_effect="read"`，而桩后端下**实测真的起子进程 2 次**
  （`subprocess.run` + `Popen`，命令行 `['lean', <temp>\t.lean]`；`audit_targeted.out`）；
- `tools/verify_tools.py::detect_verifier` 同样声明 `read`，实现里必起
  `subprocess.run(cmd.split(), …)` 做 `lean/coqc/isabelle --version`
  （**只有代码级证据**：本机 `shutil.which(...)` 三个全 `None` ⇒ 探针 0 次命中，报告如实标了"未实测"）；
- `tools/base.py:ToolRegistry.for_role` **只剥** `side_effect ∈ {write_local, network}` ⇒
  这两个工具都留在只读角色 **H 的工具面**里（来源报告把它点明为"结构性后果"）。

**影响**：H 是**审校者**，而它能跑一个**内容由调用方决定**的外部程序。
"H 只读"正是"发现问题"与"掩盖问题"能被区分开的前提（`for_role` 的 docstring 自己逐字这么写）。
这是 `P-14`（只读不是调用期强制）的**具体实例**，而且比 P-14 更直接：这次**装配期也没有剥**。

**建议修法**：**不许**给 `verify_tools.py` 单独打一个补丁。按 `P-13` 的 B1 规则办 ——
"只读角色在既有『剥写工具』之外**再剥 `external == "exec"`**"；
并把 `detect_verifier` / `check_formal` 排进 **B3 逐工具迁移清单的最前面**
（它们被真正声明成 `exec` 之后，那条剥除规则才生效）。

> ⚠️ **在那之前这个洞仍然存在**：`external` 的默认是 `none`（"我没说" ≠ "我会出网"），
> 所以**B1 落地本身并不修好这一条**。**不许**因为"B1 已落地"就把 `P-19` 标成已修。

**验收判据（可判定）**：
- **负控（今天红）**：断言 `for_role("H")` 的名字集合里**不含** `verify.check_formal`
  与 `verify.detect_verifier`（今天**含**，所以这条在改动前是红的）；
- **正控**：`for_role("E")` 仍含这两个工具（剥的是只读角色，不是砍 E 的能力）；
- 可跑命令：`python -m pytest tests/test_tools_readonly_roles.py -q`
  与 `python D:\Incubator\temp\audit_targeted.py`。

**为什么不由 AI 做**：`src/agentflow/tools/verify_tools.py` 在 FC-27 禁改区（`prover-bridge`，
理由逐字 *"桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印"*）；
剥 `exec` 的那一环在 `tools/base.py`（`auth-audit`）——
**改的是权限面的判据本身**（与 P-1 / P-13 / P-14 同族）。

---

## P-20：能力层**内部自相矛盾** —— 同类的两个子进程工具，一个升成 `network`、一个留在 `write_local`

**现状（实测，来源：`temp\REPORT.md` §两层不一致 第 2 条）**：
- `capabilities.py::ActionSpec("E","check_formal")` 的值是 **`network`**，理由逐字写着
  *"既起子进程、又可能触碰工作区之外 ⇒ 唯一不撒谎的值是 network"*；
- 而 `verify.run_experiment`：工具层 `write_local`（`tools/verify_tools.py` 自己注了
  *"待修……严格说应当是 network"*）、能力层**也是** `write_local`；
- 实现侧：`agent_e.py::run_experiment` 用 `env = dict(os.environ)` + `cwd=workspace_root`
  起子进程 ⇒ 子进程**可写工作区外、可联网**。

**⚠️ 与 `P-6` 的关系（必须写清，否则会变成"两个号指一件事"）**：
这**不是第二件缺陷**，它是 `P-6` 的**第二份证据**加上一条**新的、独立的事实**：
**能力层对两个同类工具给了两种处置**。两个号并存是刻意的 ——
`P-6` 管"`run_experiment` 该被声明成什么"，本条管"**能力层自己没有一致口径，而能力层是判据的输入**"。

**影响**：审批面不变（`write_local` 与 `network` 都在 `NEEDS_APPROVAL` 里），
受影响的是 `capabilities._WRITE_LIKE` 的保守性与**审计口径**；
更实在的是：能力层**已经承认过**这一类子进程工具必须写 `network`，
却在同一个文件里对另一个同类工具放行 ⇒ 读能力层的人**无法判断那条推理算不算数**。

**建议修法**：与 `P-6` **合并处置**：把 `run_experiment` 的声明升到 `network`
（或按 `P-13` 直接迁到 `external="exec"`），并让能力层的取值**派生**而非并列
（派生的判据见 `P-15` 与 `G-19`）。

**验收判据（可判定）**：
- **负控（今天红）**：断言"凡是被 `agent_e` 以 `env=dict(os.environ)` + `cwd=workspace_root`
  起子进程的工具，其**能力层**取值必须 ∈ {`network`, `exec`}"（今天 `run_experiment` 是
  `write_local` ⇒ 红）；
- **正控**：`python -c "import agentflow.capabilities"` 退出码 **0**；
- 可跑命令：`python -m pytest tests/test_agent_e.py tests/test_check_formal_wiring.py -q`。

**为什么不由 AI 做**：`tools/verify_tools.py` 在禁改区；且它要改一条**既有测试的期望值**
（`tests/test_agent_e.py` 断言 `write_local`）—— 本项目规则是"改既有断言的期望必须人确认
它是修正错误行为、而不是放宽断言掩盖失败"（同一判断见 P-6 与 P-7）。

---

## P-21：`verify.py` 写的产出值与登记词表**不符**（`no_results` vs 登记值 `no_result`）

**现状（实测，来源：`temp\REPORT.md` §漏取值 第 3 条）**：`schema.py:SEARCH_OUTCOMES`
登记的值是 **`no_result`**；而 `verify.py` 在注释与报错提示文案里写的是 **`no_results`**。
报告同时核实了一件事：**该处断言已经被改成 `outcome is None`，所以逻辑无差** ——
这是"**文字与词表分家**"，不是逻辑错。

**影响**：这是**语义漂移的入口**。今天只是错字；明天有人按那条报错提示去写
`outcome="no_results"`，就会造出一个**词表外的值**，而**没有任何东西会红**
（这正是 `G-26` 那条"没有判据检查词表取值是否被产出"的直接后果）。
按 FC-13 的纪律，"词表内的值"与"词表外的值"必须可区分，
而这里**文档在教人写词表外的值** —— 比错字严重。

**建议修法**：把 `verify.py` 的两处文案改成 `no_result`（**人改，禁改区**）。
**不许**反过来把词表改成 `no_results`：那会**追溯性地改写历史报告里该字段的取值含义**
（`schema.py` 的 `eval-criteria` 理由逐字如此）。

**验收判据（可判定）**：
- 可跑命令：`python -c "import pathlib;t=pathlib.Path('src/agentflow/verify.py').read_text(encoding='utf-8');print(t.count('no_results'))"`
  ⇒ 期望 **0**（今天 **> 0**）；
- **正控**：`schema.SEARCH_OUTCOMES` 的内容**逐字不变**（这一条修的是文案，不是词表）；
- **负控**：修完后全库 grep `no_results` 只应剩本文件 / 测试里的**历史引用**；若在 `src/` 里
  还有第二处 ⇒ 说明这条只改了一半。

**为什么不由 AI 做**：`verify.py` 在 FC-27 禁改区（`auth-audit`），理由逐字是
*"`verify_all` 的一致性审计：不变量检查的判据本身被改宽 ⇒ 审计从此永远『通过』"*。
这一处虽然只是文案，但它落在**审计文件**里 —— 而审计文件里的文案会被当成口径读。

---

## P-22：`FINDING_KINDS::quote_mismatch` 是一条**永远不可能出现**的取值（死取值之一）

**现状（实测，来源：`temp\REPORT.md` §死取值 第 3 条，逐处引用在 `audit_dead.out`）**：
`schema.py:FINDING_KINDS` 含 `quote_mismatch`（**仅此一处定义**，外加测试夹具）；
而两条 code→kind 的生产映射 —— `tools/doc_tools.py::_FINDING_KIND_OF_CODE` 与
`tools/review_tools.py::_H_FINDING_KIND_OF_CA_CODE` —— **都没有它** ⇒ 两条生产路径都不产出它。

**影响**：词表是**契约**。一条永不可能出现的取值会让读词表的人以为
"这个系统会报『引文不符』"，于是**不再自己检查引文**；而 H 的引文类发现实际上落在别的 kind 上。
（`N-5`/`G-13` 的教训在这里同样成立：**词表说的与系统做的是两件事时必须可见**。）

**建议修法（人选一条）** —— **在裁定之前不许两边都动**：
- (a) **补产出路径**：给两张映射表加 `quote_mismatch`，并让引文回验的失败真的产出它
  （落点 `doc_tools.py` / `review_tools.py`，**非禁改区** ⇒ 那一步 AI 可以做）；
- (b) **删词表取值**（落点 `schema.py`，**禁改区** ⇒ 人 + 2 名 reviewer）。

**验收判据（可判定）**：
- 可跑命令：`python D:\Incubator\temp\audit_dead.py`（本轮的证据脚本）⇒ `quote_mismatch`
  必须从"死取值"清单里消失；
- **负控（防"为消红灯而加一行永不命中的映射"）**：若只在映射表里加一行、却**没有任何 code**
  能算出它，审计脚本必须**仍然**报死取值 —— 即判据要能区分"接线了"与"只是写了名字"；
- **正控**：另外两个真的被产出的 kind 不许因此变成"无产出"（判据不许改宽）。

**为什么不由 AI 做**：(b) 的落点 `schema.py` 与 `eval-criteria` 理由同族
（*"改它等于追溯性地改写历史报告里每个数字的含义"*）；而 (a)(b) 之间是一次**口径决定**
（"这个 kind 该不该存在"），只能由人裁。

---

## P-23：受控词表的其余**死取值**（`DOC_KINDS` / `DEP_KINDS` / `UNKNOWN_SIDE_EFFECT`）

**现状（实测，逐处引用在 `audit_dead.out`；来源：`temp\REPORT.md` §死取值）**：
- `schema.py:DOC_KINDS`：`reproduction_report`（仅定义 + 测试夹具）、
  `survey`（只在 `providers.py` 里当"主题类别"字符串用，**不是**文档种类）；
- `schema.py:DEP_KINDS`：`proposition`、`prior_art`（仅定义）、
  `lemma`（仅定义 + `formalgw._DECL_KEYWORDS` 里的 Lean 关键字 —— **同名词、不同义**）、
  `dataset`（仅 `agent_g.py` 的演示夹具）；
- `capabilities.py:UNKNOWN_SIDE_EFFECT`：**没有任何 `ActionSpec` 用它**
  （这与已原位更正的 `N-2` 是**同一件事的词表侧**：那边是"实例没了"，这边是"词表还在"）。

**影响**：与 `P-22` 同族。多一层的是 `lemma`：它"看起来有产出"来自一个
**同名词但不同义**的东西（Lean 关键字）—— 正是 FC-22 记过的
"**同一个表面语法承载两套命名空间**"（`draft/18` §7.5）。

**建议修法（人选一条）**：
- (a) 逐个给产出计划并落地（非禁改区）；
- (b) 从词表删（`schema.py` ⇒ 禁改区，人 + 2 reviewer）；
- (c) **保留但显式登记为"预留取值"**（在词表旁写清"这些值目前无产出，保留的理由是 X"）——
  **建议优先 (c)**：它最便宜、且**不撒谎**（"预留"是一个真实的声明）。

**验收判据（可判定）**：
- 可跑命令：`python D:\Incubator\temp\audit_dead.py`；
- 若选 (c)：判据变成"审计脚本必须给出**两栏** ——『无产出**但**已登记为预留』与
  『无产出**且**无人认领』"，**不许把 (c) 混进『通过』**
  （静默豁免是本项目最忌讳的形态，同 `tools/coverage_zero_test.py::_EXONERATED` 的纪律）；
- **负控**：把一条**已登记为预留**的取值改成"无人认领" ⇒ 审计必须从"不算缺陷"变成"算缺陷"。

**为什么不由 AI 做**：同 `P-22` —— 词表本体在 `schema.py`（禁改区）；
且 `UNKNOWN_SIDE_EFFECT` 的去留牵动 `capabilities._WRITE_LIKE` 的保守性
（它现在把 `unknown` 与写档并列处理），那是**权限面口径**，不是措辞。

---

## G-19：**没有判据**比对同名动作的两层声明 ⇒ `P-15` 那对不一致从未被任何机器看见

**现状（实测，来源：`temp\REPORT.md` §两层不一致 第 3 条）**：
`capabilities.py:assert_capabilities()` 的第 `[5]` 条只交叉断言 **`SIDE_EFFECTS` 的字面量词表**
（它 `from .tools.base import SIDE_EFFECTS as TOOL_SIDE_EFFECTS` 之后比的是**词表本身**），
**不比任何同名动作的取值**；而 `capabilities.py` 的 docstring 声称两层之间有交叉断言。
19 对同名动作里唯一的冲突 —— `verify.check_formal`（工具层 `read` / 能力层 `network`）——
因此**从来没有被机器判据看见**（`R006` 仍只看工具层、且是文件级共现，见 `G-14`）。

**影响**：能力层的全部价值在于"它是工具层的**对账**"。一条只比词表、不比取值的断言，
会在报告与 docstring 里显示成"两层已对账" ⇒ **虚证**（本项目最忌讳的形态）。
**这一条同时就是 `P-15` 的"建议修法"本身** —— `P-15` 是"被它抓到的第一件事"，`G-19` 是"判据"。

**建议修法**：把第 `[5]` 条扩成**逐同名动作比对**：对每个在能力层有声明的工具，断言
`ActionSpec.side_effect == 注册表里同名 spec 的 side_effect`（判据只有一份：**取自注册表**）。
**顺序不能反**：**先让新断言红**（它会当场抓到 `check_formal`），**再**去修那一对（`P-15`）——
先修后加断言会**掩盖"当初为什么会不一致"**。

**验收判据（可判定）**：
- **负控（今天红）**：把 `capabilities` 里任意一条 `side_effect` 改成**另一个合法值** ⇒
  `python -c "import agentflow.capabilities"` 必须以**非 0** 退出（今天仍是 0 ⇒ 改动前红）；
- **正控**：`check_formal` 修好之后，这条断言必须转绿，且**只有那一处**曾红
  （绿了以后要把"曾红的那一处"写进本条，作为"判据真的跑过"的证据，而不是"从来就是绿的"）；
- 可跑命令：`python -m pytest tests/test_check_formal_wiring.py tests/test_role_specs_complete.py -q`。

**为什么不是 P**：落点 `capabilities.py`（`assert_capabilities`）**不在** FC-27 禁改区
⇒ **AI 可做**。注意它的**新断言会去读**禁改区文件里的声明，但**不改**它们。

---

## G-20：成本归因**不成立** —— `USAGE_SCOPES` 五档全无产出，账本答不出"搜索/抽取/审校各花了多少"

**现状（实测，来源：`temp\REPORT.md` §死取值 末条）**：`schema.py:USAGE_SCOPES` 含
`experiment` / `search` / `extract` / `review` / `other`；而入账路径只有 `Charge(scope=…)`，
**生产代码里只出现两档**：`"summon"`（`conductor.py`）与 `"reason"`（`modelcost.py` 的默认 + `runflow.py`）
⇒ 账本只能用**两档**归口。

**影响**：这是**企业级单位经济**的直接前提。本方案 §2.3 与 §6 要求"元/可验证产物"，
§5.3 的 P4 阶段要求"成本报告 + 单位经济出数"—— 而"搜索/抽取/审校/实验各花了多少"
**今天答不出**，只能按总额摊。⇒ 这不是一行代码的事，它**使 P4 的一个 DoD 项不可能达成**。

**建议修法**：在四条生产路径上**填 scope**（`agent_a` / `agent_b` / `agent_h` 的调用点、
`runflow.py`、`conductor.py`、`modelcost.py`）—— **不改词表**（词表已经是对的，缺的是产出）。

**验收判据（可判定）**：
- 可跑命令：读 `data/usage_ledger.json` 统计 `scope` 分布 ⇒ 修完后**至少 4 档非零**；
- **负控**：造一次 `Charge(scope="search")` ⇒ 必须真的落到账本里（今天落不进，因为**没有调用点**）；
- **正控**：`usage_task_total_mismatch` 仍**不响** —— 归因**不许改变总额**
  （这条防的是"为了填 scope 而重复计费"，与 `P-12` 同族）。

**为什么不是 P**：落点全在非禁改区（`conductor.py` / `modelcost.py` / `runflow.py` / `agent_*.py`），
且**不需要**动词表。
**⚠️ 与在飞工作包的关系**：`runflow.py` 在 `db08356a` 的文件清单里 ⇒ 本条**排其后**。

---

## G-21：`returns=` 判据**仍是纸面通过**（`∅ − ∅ = ∅`）

**现状（实测，来源：`temp\REPORT.md` §判据能不能判 第 1/2 条）**：
`tests/test_tools_returns_declaration.py` 的 `_declared_minus_actual` 在 `obs.keys is None`
（返回的 `data` 不是 dict）时**直接返回空集**；而这一批工具的 `declared_keys` **也抽不出**
（解析器读不到键）⇒ 判据对它们**一次都没有执行**（`fs.read` / `fs.delete` / `table.count` /
`table.create` / `table.update` / `table.delete` / `table.get` 一类，共 12 个），
而报告上显示的是"**55/55 缺键为空**"。
另外：它**抓不到"给了却没声明"**（只做单向差集），也**不比对失败分支 / 次分支**。

**影响**：`G-4`（"`returns=` 的判据在 36/55 个工具上真空通过"）**没有被关掉，只是被缩小**。
更贵的是：`55/55 空` 这个数字会被当成"声明与实现已对齐"的**正向证据** ——
与 `G-10` 同族：**判据的"真空真"比漏报更贵，因为它产生结论**。

**建议修法**：①`observations` 为 `None` / 非 dict ⇒ 记成 **`unknown`**（最差也要 `fail`），
**不许**记成"空集 = 通过"（三态纪律：`unknown ≠ clean`）；
②把判据改成**对称差**（"声明了却没给" **与** "给了却没声明"都算缺）；
③对**分支**各跑一次（分支由夹具**显式列出**，不许靠"恰好跑到的那一支"）。

**验收判据（可判定）**：
- **负控（今天红）**：造一个 `returns=` 声明为空、而 `handler` 返回含键 dict 的工具 ⇒
  判据必须红（今天的单向差集抓不到）；
- **负控（今天红）**：对一个返回非 dict 的工具，断言判据的输出是 `unknown` 而**不是** `pass`；
- **正控**：`search.register` 的 `created=false` 分支必须**被跑到**，或被显式登记为"未覆盖"
  （**不许静默只跑一支**）；
- 可跑命令：`python -m pytest tests/test_tools_returns_declaration.py -q`。

**为什么不是 P**：落点在测试（非禁改区）。
**与 `G-14`、`G-26` 合并为一个「判据可判性」工作项**（parent 的要求，见 `draft/22` §12.6）。

---

## G-22：`role_filter_notes == {}` 是**真空真**（一条不可能失败的断言）

**现状（实测，来源：`temp\REPORT.md` §两层不一致 末条）**：
`tests/test_tools_readonly_roles.py` 断言 `reg.role_filter_notes == {}`
（docstring 自己写着"防误伤：声明都正确时必须是空的"）；
而 `tools/fs_tools.py::_effective_roles` 与 `tools/table_tools.py::_effective_roles`
**已经在装配期**把只读角色从写工具里剥掉了 ⇒ `for_role` **无事可剥** ⇒ 这条断言**永远绿**。

**影响**：这是"**判据的判据**"出了问题。它想守的是"只读角色的工具面里没有写工具"，
但真正守那件事的是装配期的 `_effective_roles`。两种失效方式：
① 有人删掉装配期剥离 ⇒ notes 变非空（红，好，但它红在**另一个理由**上）；
② 有人**改宽**装配期剥离（放行一个写工具却把它排除在 notes 之外）⇒
**这条断言仍然绿**。⇒ 一条**看起来在守、实际守不住**的门（`G-10` 的同类形态）。

**建议修法**：断言**直接落在工具面**：`for_role("C")` / `for_role("H")` 返回的每个工具，
`spec.side_effect ∉ SIDE_EFFECTS_WRITE`（判据**取自工具层同一份** `SIDE_EFFECTS_WRITE`，
**不许**另列名单 —— FC-03）。`role_filter_notes` 的断言**保留但降级**：
它只是"装配期发生过剥离"的证据，**不是**权限面的判据。

**验收判据（可判定）**：
- **负控（今天红）**：在装配期放行一个 `side_effect="write_local"` 的工具给 H
  （例如临时把它加进 `_effective_roles` 的放行表），断言"工具面无写工具"必须红；
  **今天这条负控会绿**（它走到了 `role_filter_notes` 那条逻辑上，而 notes 是空的）——
  这正是"真空真"的可判定形态；
- **正控**：`role_filter_notes` 在**正常的**声明下确实为空（不许把这条断言删掉，
  它是"装配期剥离发生过"的唯一证据）；
- 可跑命令：`python -m pytest tests/test_tools_readonly_roles.py -q`。

**为什么不是 P**：落点在测试（非禁改区）。**与三个在飞包无同文件 ⇒ 可以立即做**。

---

## G-23：`search.register` / `search.dedup_check` 的 `returns=` **只描述主分支**

**现状（实测，逐键列出；来源：`temp\REPORT.md` §声明 vs 实现 第 6 条）**：
同一个工具的两条分支给出**不同的 `data` 键集合**：
- `search.register`：`created=true` 给 `{created, lit_id, path, dedup_key, keys, type_code, processed, download, request_linked, warnings}`；
  `created=false` 给 `{created, reason, lit_id, matched_key, existing, keys, request_linked, warnings}`
  ⇒ **少 5 个键**（`path` / `type_code` / `processed` / `download` / `dedup_key`）；
- `search.dedup_check`：失败时 `data` 是 **`None`**，`checked` / `would_be_duplicate` / `keys`
  **只在 `meta`** 里。

**影响**：`ToolSpec.returns` 是**契约**（它要喂给 function-calling，也是 `G-21` 那条判据的输入）。
按声明读另一支的调用方会 `KeyError` / `TypeError`，而**没有任何判据会报错**
（判据每个工具只跑一次、只覆盖声明的那一支）。
`tools/search_tools.py` 的注释把它记为"刻意的分支键集合不同" ——
**注释不是判据**（本项目记过的形态：一个可判定的契约被一句注释替代）。

**建议修法**：给 `returns=` 一个**能表达分支**的形态：要么标出"仅 `created=true` 时存在"的键，
要么给 `oneOf` 式的分支键集合；并让 `G-21` 的判据**按分支各跑一次**。

**验收判据（可判定）**：
- **负控（今天红的）**：按 `returns=` 读出全部键、在 `created=false` 分支上逐个取值 ⇒
  **不许抛 `KeyError`**（今天会抛）；
- **正控**：`created=true` 分支的键集合**逐字不变**（收口不许把主分支改小）；
- 可跑命令：`python -m pytest tests/test_tools_search_ocr.py tests/test_tools_returns_declaration.py -q`。

**为什么不是 P**：落点 `tools/search_tools.py` **不在**清单里（非禁改区）。
**与三个在飞包无同文件 ⇒ 可以立即做。**

---

## G-24：三处**漏词表**（代码在产生、词表里没有）

**现状（实测，来源：`temp\REPORT.md` §漏取值）**：
1. `agent_e.py::check_formal` / `::_formal_refusal` 的 `reason` **完全没有受控词表**：
   同一字段会出 `no_backend` / `no_script` / `path_outside_workspace` / `param_error`，
   **外加** `formalgw.STATUSES` 的**全部八值**（工具层**直传**）；
2. `agent_f.py::step` 返回 `"outcome": "no_change" | "progress" | "blocked"`，
   **不在** `schema.py:TASK_OUTCOMES` 里；
3. `cancellation.py::CancelReason.by` **无词表**：代码写 `"deadline"` / `"budget"`
   （`cancellation.py`）与 `"conductor.dispose"`（`conductor.py`），
   而它的 **docstring 另列了一个 `"user"`** —— 那个值代码里根本没有。

**影响**：与 `P-21` / `G-26` 同族，方向相反（这边是"词表外有值"）。三处里：
- ① 最贵：`reason` 是**审计字段**，一个"12 值混装"的字段等于**没有口径**
  （本项目反复记的纪律：`reason` 必须受控 —— 三态纪律要求 `reason` 可枚举）；
- ③ 最典型：docstring 列的 `"user"` 代码里不存在 ⇒ **文档在说假话**（`G-15` / `P-21` 同病）；
- ② 需要一次判断：`agent_f.step` 的 outcome 到底是不是 `TASK_OUTCOMES` 管的那个字段？
  （**可能是两个不同的字段同名** —— 那就是 FC-22 的"同一表面语法两套命名空间"。）

**建议修法**：①给 `reason` 一张局部受控词表（放 `agent_e.py` 或 `capabilities.py`，均非禁改区），
并把 `formalgw.STATUSES` 的八值**显式映射进去**（不许再直传）；
②先裁定"是不是同一个字段"，再决定是并入 `TASK_OUTCOMES`（⇒ 那时要动人审）
还是另立词表（AI 可做）；③立一张 `CancelReason.by` 词表，并**删掉 docstring 里那个不存在的 `"user"`**。

**验收判据（可判定）**：
- **负控（今天红）**：一条断言"`agent_e.check_formal` 返回的 `reason` 必在受控词表内"
  ⇒ 今天**红**（词表不存在）；
- **正控**：`formalgw.STATUSES` 的八值信息**不许因为收口而丢掉**
  （`reason` 可以是词表值 + 一个透传字段，但不许把八值压成一个模糊值 ——
  这与 `N-5`"不许把 `compile_error` 折叠成 `no_backend`"是同一条纪律）；
- **负控**：`grep '"user"' src/agentflow/cancellation.py` ⇒ 修完后 docstring 里**不再出现**它；
- 可跑命令：`python -m pytest tests/test_agent_e.py tests/test_agent_f.py tests/test_cancellation.py -q`。

**为什么不是 P**：三处落点（`agent_e.py` / `agent_f.py` / `cancellation.py`）**都不在** FC-27 禁改区。
**⚠️ 与在飞工作包的关系**：`agent_e.py` 在 `3da8c5e0` 的文件清单里 ⇒ 本条**排其后**
（②③ 本来可以提前做，但同属一条登记，整条排在后面更省事、也更符合"一条编号一件事"）。

---

## G-25：三处 **docstring 与实现不符**

**现状（实测，来源：`temp\REPORT.md` §声明 vs 实现 第 1/4/5 条）**：
1. `tools/fs_tools.py::_effective_roles` 的 docstring **整段抄自**
   `tools/table_tools.py::_effective_roles` —— 它描述的是 `table.*` 那 8 个表工具
   （"……`AgentH` 的工具面里出现了 `table.update`"），而本模块只注册 **7 个 `fs.*`**，
   `_TOOL_FUNCTIONS` 全是 `fs_*`，`table.*` **一个都不来自本模块**（两段 docstring 逐字相同）；
2. `tools/ocr_tools.py::EasyOcrBackend.available` 声称"探测会真的 `mkdir` 真实模型目录、
   并起 `tesseract --version` 子进程"；实测（真后端）本机 `import easyocr` 先失败
   （`TypeError: function() argument 'code' must be code, not str`）、
   `checks['model_dir'] = 'SKIPPED（前置检查已失败）'`、`EASYOCR_MODULE_PATH` 指向的目录**未被创建**；
   且代码里**没有任何地方**起 `tesseract --version`
   （`get_tesseract_version()` 失败即返回）⇒ **"起子进程"是编造的**（报告标为"低/未核实"：
   能 import 的机器上 `mkdir` 会真执行）；
3. `capabilities.py::ActionSpec("E","check_formal")` 的 docstring 声称
   "把它的**八值受控词表折成调用方看得懂的三态**"，而实现
   （`tools/verify_tools.check_formal`）**只把 `status` 原样塞进 `reason`**，没有任何折叠 / 映射表。

**影响**：① 最坏 —— **整段复制** ⇒ 读 `fs_tools` 的人以为它在管 `table.*`（"文档指向错误的模块"，
与 `P-18` 同病）；② 是"声明了一个不存在的行为"（本轮唯一一处**编造**）；
③ 与 `G-24` ① 是**同一处代码的两个面**：文档说折叠了、实现没折叠、词表也没有 ⇒
读的人会以为 `reason` 的八值**已经被归一**，于是不去处理它。

**建议修法**：三处按实测改写。③ 必须与 `G-24` ① **一起做**：
要么**真的实现**折叠（并给出映射表），要么把 docstring 改成"**原样透传 `status`**" ——
**不许**只改文档而留着"八值混装"当无事（那就是把"文档说谎"升级成"文档与代码一起说谎"）。

**验收判据（可判定）**：
- **负控（今天红）**：一条"docstring 里点名的行为必须在**本模块**里有对应符号"的检查
  （形态直接抄 `noai_gate` 的 `test_python_manifest_referenced_symbols_exist`）⇒
  ② 里的 `tesseract --version` 在 `ocr_tools.py` 里查无实据 ⇒ **红**；
  ① 里点名的 `table.update` 不在 `fs_tools.py` 的注册表里 ⇒ **红**；
- **正控**：`python -m pytest tests/test_tools_search_ocr.py tests/test_role_specs_complete.py -q` 仍绿；
- 可跑命令：`python -m pytest tests/test_tools_returns_declaration.py -q`（R007/角色表对账不受影响）。

**为什么不是 P**：三处落点（`fs_tools.py` / `ocr_tools.py` / `capabilities.py`）**都不在**禁改区。
**⚠️ 与在飞工作包的关系**：`capabilities.py` 在 `43ce64a6` 的文件清单里 ⇒ ③ 那一半**排其后**。

---

## G-26：**全库没有任何判据**检查"受控词表的取值是否真的被产出"

**现状（缺口，来源：`temp\REPORT.md` §判据能不能判 末条）**：全库无此断言 ⇒
**死取值与漏取值可以长期存在而不变红**；本轮 13 条里至少 **4 条**
（`P-21` / `P-22` / `P-23` / `G-24`）**全部**是人扫出来的。
对照物是现成的：`tools/coverage_zero_test.py` 就是"函数有没有被测试"的**同类判据**，
而**词表没有对应物**。

**影响**：**这是本轮最贵的一条** —— 它本身不产生缺陷，它让**一整族缺陷不可见**。
本项目已有同形先例（`G-9`：覆盖缺口"在任何自动门里都不会变成红灯，只有这张表记得它"）。
把 `P-21` / `P-22` / `P-23` / `G-24` 逐条修掉**并不能防止下一批**：
下一批死取值还会同样静默地长出来。

**建议修法**：把 `D:\Incubator\temp\audit_dead.py`（本轮的证据脚本，**已有逐处引用** `audit_dead.out`）
收敛成**仓内的一条判据**（建议 `scripts/lint_rules.py` 的新规则，或 `tools/` 下的小工具）。
输出**必须三栏**：
① 有产出；② **无产出但已登记为预留**（`P-23` 的 (c)）；③ **无产出且无人认领**。
**只有第 ③ 栏算缺陷** —— 否则"预留取值"会被迫删掉、或被逼着造一行假映射
（那正好是 `P-22` 负控要防的事）。

**验收判据（可判定）**：
- **负控（今天的行为即"红"）**：往 `DOC_KINDS` 加一条**永久不可能命中**的取值
  （例如 `"zzz_probe"`）⇒ 判据必须报出它（今天**什么都不报** ⇒ 这就是"改动前红"）；
- **正控**：`capabilities.UNKNOWN_SIDE_EFFECT` 若被登记为"预留"⇒ **不报**
  （两栏**不许合并** —— 合并就是静默豁免）；
- 可跑命令：`python scripts/lint_rules.py` —— **新规则必须先与"`error` 必须为 0"这条日常门对齐**
  （`scripts/lint_rules.py` 的 `--strict` 把 warning 也算失败），
  所以新规则大概率应以 `info` / `warning` 起步并**带一个 `--check-vocab` 式的显式子命令**；
- 判据自身的**假阳性边界要写明**：词表扫描是**文本近似**（`REPORT.md` §假阳性说明 第 1 条：
  字符串拼接、`getattr` 间接取值、经变量中转的赋值都可能漏判）⇒
  这条判据**只能报"疑似无产出"，不能报"一定无产出"**（措辞必须与能力一致，否则又是一次过度声称）。

**为什么不是 P**：落点在 `scripts/lint_rules.py` 或 `tools/`（**都不在**禁改区）。
**合并要求**：与 `G-14`（R006 按文件判）与 `G-21`（`returns=` 纸面通过）合成
**一个「判据可判性」工作项**（parent 的要求，见 `draft/22` §12.6）。

---

## 第二轮增补的自我申明（两条分类分歧，请裁决）

1. **`P-22` / `P-23` 我判成 P，但可以辩成 G**。理由：这两条的"最小修法"有两条路 ——
   (a) **补产出路径**（`doc_tools.py` / `review_tools.py` / `agent_*.py`，**非禁改区** ⇒ AI 可做）、
   (b) **删词表取值**（`schema.py`，**禁改区** ⇒ 人 + 2 reviewer）。
   我按"**词表本体在禁改区、且『留还是删』是口径决定**"归了 P；
   若你裁定"死取值一律走 (a)"，这两条应当**降为 G**，`draft/22` §12.6 的批次与谁做随之改写。
2. **`G-19` 会去读禁改区文件的声明**（它断言"能力层取值 == 注册表取值"），
   但它**不改**禁改区文件 ⇒ 我归 G。若你裁定"**任何以禁改区判据为输入的新门**都要人审"，
   则它应与 `P-15` 合成一次人审批次（落点仍是 `capabilities.py`）。

---

# 增补（第三轮，同日）：文档声称 vs 代码事实（`temp\audit-doc-vs-code.md`）

> 来源：`D:\Incubator\temp\audit-doc-vs-code.md`（只读审计：grep 抽出 466 条
> "实测 / 已落地 / 共 N 个 / N 处 / 退出码 N / 不存在"类句子、抽 250 条逐条跑命令取真值；
> **未改仓库任何文件**）。
>
> **按 parent 的规则"与已有条目同族的并入而不是新增"，本轮：**
> - **新增 6 条 G**（`G-27`…`G-32`）+ **2 条 N**（`N-8`、`N-9`）；
> - **原位追加 4 处**（不新增号）：`G-9`（整表更新）、`G-16`（FC-17 / FC-19 的"三处三态"）、
>   `P-16`（`roles` **从不**被校验）、`P-12`（`usage_ledger.json` 计数）；
> - 编号连续无洞：**P 1..23 / G 1..32 / N 1..9**。
>
> ⚠️ **本轮每一条都受"仓库正被并发修改"影响**：同一个命令在同一天内给出不同的数 ——
> `R009` 的禁改区装饰计数我实测 **430（22:18）→ 462 → 466 → 477**（`tools/base.py` 44→57），
> 审计方自己的序列是 **455 → 457 → 462**（详见 `G-32`）。
> **凡计数类主张，本文件只给"区间 + 观测时刻"。**
>
> ⚠️ **对来源的三处归属更正**（我核过原文，请以本文件为准）：
> ① 发布门的 `pass=4 fail=0 unknown=1` 在 **`DEVELOPMENT.md` §8.2** 的实测块里，
> **`README.md` §6 只有步骤说明、没有任何数字**（见 `G-28`）；
> ② `usage_ledger`"零写入方"的第二处在 **`DEVELOPMENT.md` §9.2 的 FC-19 行**，
> **§8.4 待办 7 是"禁改区漂移可机械检测"（✅），与此无关**（见 `G-31`）；
> ③ §0.1 行内的"`1329 个测试函数` vs `1497 passed`"**未必互斥**（`pytest` 的 `passed` 含参数化展开），
> 我按"**过期**"登记、**不**按"行内自相矛盾"登记（见 `G-30`）。
>
> **parent 的 10 项 → 登记落位**（便于对照）：
> ① →`G-27`（新增，**不**并入 `G-21`/`G-26`）· ② →`G-28` · ③ →`G-29` · ④ →`G-9` 原位 ·
> ⑤+⑥ →**合并为**`G-30` · ⑦ →`G-31` · ⑧ →`G-32` · ⑨ →`N-8` · ⑩ →`N-9`。

---

## G-27：测试**顺序依赖 / 跨文件状态泄漏** —— 绿灯是排序给的，不是判据给的

**现状（来源：`temp\audit-doc-vs-code.md` §自相矛盾 第 1 条）**：审计实测
`python -m pytest tests/test_fc17_wiring.py -q` **单独跑 = 6 failed / 4 passed**（连同
`tests/test_context_budget.py` 共 **9 failed**），而在全量 `pytest -q` 里**全过**。
根因：`tools/base.py:ToolSpec.__post_init__` 拒绝了夹具 `zz.big`（**缺 `returns`**）。

**⚠️ 本轮复跑：那个实例已经不在（时间线必须一起读）**
- 审计观测（约 22:2x）：单跑 6 failed / 4 passed；
- `tests/test_fc17_wiring.py` 的 mtime = **22:29:43**；夹具 `zz.big` 现在**有**
  `returns="{'blob','seen_budget'}（测试用的大字符串）"`；
- 我复跑（22:36）：`pytest tests/test_fc17_wiring.py -q` ⇒ **10 passed**；
  连同 `test_context_budget.py` ⇒ **47 passed**。
⇒ 那个实例是**在飞包 `43ce64a6` 顺手修掉的**（它同时改了 `__post_init__` 的六件套校验与这条夹具）。

**判定：仍然要登记（G），因为要的是判据，不是那一次修复。**
今天**没有任何门**会跑"每个测试文件单独跑"。全量绿的成因可以是共享夹具、模块级状态、
`pytest` 的收集顺序 —— 本条的名字就是"**绿灯是排序给的**"。
它与 `G-21` **不是**同一件事：`G-21` 是"判据没判到东西"，
本条是"**判据依赖执行顺序**"（同一份代码，换顺序结论就变）—— 所以 parent 要求新增一条，我照办。

**建议修法**：加一条**逐文件单跑**的门（最便宜形态：CI/自检里的一个循环，或 `tools/` 下一个小工具），
且它**不并入"全量绿"这个结论** —— 两者是两条独立证据。
注意它与 `draft/22` §12.2 记的另一件事**症状相同、成因不同**：并发半写文件也会让门随机红/绿
（我 22:18 亲自撞到 13 个模块收集期 `TypeError`）—— **治这条门不能治那条**，两条都要。

**验收判据（可判定）**：
- **负控**：逐个测试文件单独跑，**不许有任何文件红**；
  ⚠️ 写这条判据**禁止**用 `foreach` + 裸 `$LASTEXITCODE` —— 审计自己就栽在这上面
  （`N-8` 第 1 条：`foreach` 里 `$LASTEXITCODE` 会取到 `Select-Object` 的码，误报 `agent_c/d` exit 1）。
  必须逐条直跑或显式取 `$?`；
- **正控（判据有效性）**：**故意注入**一个顺序依赖（例如只在第二个文件里给夹具补 `returns`）
  ⇒ 单跑必须红、全量必须仍绿 —— 这证明门真能抓到这个形态（今天实例已被 `43ce64a6` 修掉，
  所以**必须**用注入法验，否则这条判据是"没有证据的绿"）；
- 可跑命令：`python -m pytest tests/test_fc17_wiring.py tests/test_context_budget.py -q`（现在 47 passed）。

**为什么不是 P**：落点在 `tests/`（非禁改区），AI 可做。
**⚠️ 与在飞包的关系**：`43ce64a6` 落地前这条会一直红（它改的正是同一个 `__post_init__`）；
**关闭本条需要复跑"每个测试文件单独跑"**（parent 已指定）。

---

## G-28：发布门**实测 FAIL**（`pass=3 fail=2`），而三处文档把它写成"基本全绿"

**现状（来源：审计 §命中 8 / 16 / 17 + 我复核的两半）**：
- `DEVELOPMENT.md` **§8.2** 的"复跑命令与当前实测状态"块逐字给出
  `[pass] coverage 等级 ≤ 2 的零测试函数 0`，以及
  `一键发布检查总判定：UNKNOWN    pass=4 fail=0 unknown=1     # 退出码 2`；
- `DEVELOPMENT.md` **§0.0 的 S2 行**又把发布门写成 **`pass=6 fail=1 unknown=1`**；
- **`README.md` §6 只有步骤说明、没有任何 pass/fail 数字** —— 来源把它记成
  "README §6 标 `pass=4 fail=0 unknown=1`"，**归属错了**（见本节开头的更正 ①）。

**实测（我复核了两半）**：
- `python tools/coverage_zero_test.py` ⇒ **退出码 1**，等级 2 = **2 个**
  （`formalgw.evidence_of`、`modelgw.gateway_main`）⇒ §8.2 那行 `[pass] coverage … 0` **是假的**；
- 审计实测 `python tools/release_all.py` ⇒ **`pass=3 fail=2 unknown=0`**
  （`release-check`、`coverage` 两项 fail）⇒ 与 §8.2 的 `pass=4 fail=0`、
  §0.0 的 `pass=6 fail=1` **都不符**；三处文档**互不相同**、**没有一处与实测一致**。
  **我未复跑 `release_all.py`（如实）**：它跑验收测试与论文复现、约 10–15 分钟**且会写产物**，
  而本轮我的边界是"只动两个 md"。

**影响**：发布门是 `draft/22` §7.2 的 P5 验收器具，也是 `E2`/`E5`（可验证 / 可交付）的判据来源。
文档给出**三个互不相同**的发布状态 ⇒ 读的人会得出"基本全绿，只差一个结构性 `unknown`"
（`§8.2` 还专门解释那个 `unknown` 不可消除），而实测是 **fail=2**。

**建议修法**：把 `§0.0 S2` 与 `§8.2` 的发布门块改成"**观测时刻 + 原始输出 + 判定**"
（与 `G-32` 同一条口径）；更好的是让这两块**由 `release_all.py --json` 生成** ——
手抄的数字必然再漂，本文件已有两轮实例（`G-30`）。

**验收判据（可判定）**：
- **负控（今天红）**：`python tools/release_all.py --json <out>` 的 `overall`
  必须与文档那一行**逐字一致**（今天不一致；且 `coverage` 项必须是 `fail`，文档写 `pass`）；
- **正控**：修好之后这条应转绿，**但不许**把 `fail`/`error` 改写成 `unknown` 来换绿 ——
  那正是 `tools/release_all.py` 自己防的"`--skip` 成为捷径"的形态（它的 docstring 逐字如此）。

**为什么不是 P**：落点 `DEVELOPMENT.md`（非禁改区）。
⚠️ 但 `tools/release_all.py` **在**禁改区 ⇒ 若裁定要改**门**（而不是改文档），那一步另需人审。

---

## G-29：**本会话新增的代码**把发布门的 `coverage` 项弄红了（等级 2 = 2）

**现状（实测）**：`python tools/coverage_zero_test.py` ⇒ 退出码 **1**；
等级 2（"判据 / 决策"档）有 **2 个**：`agentflow.formalgw.evidence_of`、
`agentflow.modelgw.gateway_main`。`formalgw.py` 与 `modelgw.py` **都是本会话新增的模块**。
而 `DEVELOPMENT.md` §0.2 第 7 项把这一档写成
"等级 1/2 的零测试公开函数 **0**（从 53 降下来），退出码 0"，§8.2 的 `coverage` 项据此标 `[pass]`。

**影响**：等级 2 是 `coverage_zero_test` 风险分档里**必须为 0** 的那一档，
而它现在是发布门 `fail=2` 的其中一项 ⇒ **新增代码把发布门弄红了，而文档仍写"已关闭"**。
这条与 `G-28` 是**因果链条**：`G-29` 是原因，`G-28` 是那个假状态。

**建议修法（需 parent 裁定；两条不许都做）**：
- (a) **补两个直接测试**：`evidence_of` 的判据键（`checked` / `reason`）、
  `gateway_main` 的决策分支；
- (b) 按既有惯例把 **CLI 入口类函数**登记进**显式排除清单**
  （`gateway_main` 与 `cli.main` 同族）。若走 (b)：**必须**让它出现在 `--json` 的 `excluded` 里
  并写明理由 —— `tools/coverage_zero_test.py` 自己的纪律逐字是
  "**排除必须可见，不许静默**"（它的 `excluded` / `_EXONERATED` 就是为此设计的）。

**验收判据（可判定）**：`python tools/coverage_zero_test.py` 退出码 **0**，
且等级 2 计数 = 0 **或**剩余项**全部**出现在 `--json` 的 `excluded` 里（含理由）。
**负控（今天红）**：把 `evidence_of` **静默**排除（只改代码、不写理由）⇒ `--json` 必须能看出
—— 看不出就是新造了一条静默豁免（本项目最忌的形态）。

**为什么不是 P**：落点在 `tests/` 与 `tools/coverage_zero_test.py`（都不在禁改区）。
**⚠️ 本条由本会话新增代码引入**（parent 要求注明）。

> ⚠️ **前置依赖（2026-09-25 第四轮审计追加；并入，不新增号）**：
> **先修 `G-34`（`tools/coverage_zero_test.py::_name_pattern` 的 `.` 盲区），再判本条的这两个函数。**
> 理由：第四轮实测该工具的左边界 `(?<![\w.])` 会让"`别名.函数名(`"形态**永远拿不到 `via:direct`**，
> 而本仓库 `tests/` 通篇是 `G.` / `S.` / `T.` 这类别名 ⇒ **39 个假缺口（19 个等级 ≤2）**。
> 因此 `formalgw.evidence_of` 与 `modelgw.gateway_main` 的"零测试"**可能是同一个盲区的产物**。
> ⇒ **裁定顺序被固定为**：① 修工具（`G-34`）→ ② 用修好的工具重跑 `--level 2` →
> ③ 只有那时仍然在清单里的，才轮到本条的 (a)/(b) 裁定。
> **现在就去补这两个测试是错的**：那是**拿假缺口当真缺口修**，会得出"发布门绿了"的假结论，
> 而真实的缺口（若 `evidence_of` 确实无测试）被这层噪音掩盖。

---

## G-30：`DEVELOPMENT.md` / `README.md` 的"实测数字"**整批过期**（同一文件内还互相打架）

> **合并说明**：parent 把"§0.1 `tests/` 行"与"§0.0 S2 的 linter 数字"列为两条，
> 我按"**同族并入**"合成**一条** —— 病因、修法、判据完全相同（文档正文里的**定值**，
> 而没有任何门守着它）；拆成两条只会产生两套判据与两次人读。
> 审计里另外 9 处同族实例（`README.md` §4、§4.3 R006、§6-P1、§6-P9/§10-D3/§7、
> `§0.2` 第 3 条、`§0.3` census、`§0.1` 文件表、`§0.2` 第 5 条）**一并进下表，不各开一条**。

**现状（逐项：文档写的 → 实测）**：

| 文档位置 | 文档写的 | 实测 | 证据命令 |
|---|---|---|---|
| `DEVELOPMENT.md` §0.0 S2 行 | linter `error 3 / warning 2 / info 14` | **22:18** `error 0 / warning 2 / info 15`（9 条规则）；**22:25** `error 3 / warning 4 / info 18`；**22:46** `error 0 / warning 3 / info 21`；**22:51** `error 2 / warning 3 / info 21`（10 条规则）—— **四个时刻四个数** | `python scripts/lint_rules.py` |
| `DEVELOPMENT.md` §0.2 第 2 项 / §0.3 第 12 项 | `error 0 / warning 2 / info 15` | 与 §0.0 的 `error 3` **互斥**（同一命令、两处都标"当前"）；**22:46 的真值是 `error 0 / warning 3 / info 21`** —— `error` 那一格"恰好对上"了 §0.0，**这正是"定值 + 无时刻"最危险的地方**：偶然相等会被读成"文档是对的" | 同上 |
| `DEVELOPMENT.md` §0.1 `tests/` 行 | `65 个 test_*.py` / `1329 测试函数` / `287 负控` / `1497 passed` | **76 个文件**；`def test_` **1601**（审计时 1575）；全量 `passed` 审计实测 **1763**（**我未复跑全量**） | `(Get-ChildItem tests -File -Filter 'test_*.py').Count`；`grep '^\s*def test_'` |
| `README.md` §4 `.noai-paths` 行 | **`18`** 条 glob、7 类 | **19** | `python -c "from scripts.noai_gate import load_manifest;print(len(load_manifest('.noai-paths')))"` |
| `DEVELOPMENT.md` §4.3 第 3 项 | `R006 有 30 条 warn` | R006 = **6 条 `info`、0 warn** | `python scripts/lint_rules.py --json <out>`（见 `G-14`） |
| `DEVELOPMENT.md` §6-P1 | R001 `20 个 error` | **0** | 同上 |
| `DEVELOPMENT.md` §6-P9 / §10-D3 / §7 | 公开函数 `556` / `471`；缺 docstring `190` / `180`（**四处互斥**） | R007 = **612 / 190**（22:18 口径；并发下会漂） | 同上 |
| `DEVELOPMENT.md` §0.2 第 3 条 / §10-D5 | `tests/test_noai_gate.py` **51 例** | **89 passed**（71 个 `def test_`） | `python -m pytest tests/test_noai_gate.py -q` |
| `DEVELOPMENT.md` §0.3 census 引文 | 字典含 `'M':0` | `cli tools` 的字典**无 `M` 键**（仅 A–H） | `python -m agentflow.cli tools --role E` |
| `DEVELOPMENT.md` §0.1 文件表 | 缺 `claims.py` / `evidence.py` / `formalgw.py` / `modelcost.py` / `modelgw.py` / `runflow.py` / `__main__.py` / `scripts/usage_ledger_audit.py` | **均存在** | `Get-ChildItem src/agentflow -Filter *.py` |
| `DEVELOPMENT.md` §0.2 第 5 条 | `--check-approvals` ⇒ `requires_human(1)`（14 条 unapproved） | **裸跑 = 退出码 2**（`[unknown] 没有给出改动集`）；加 `--paths` 才是 1 | `python scripts/noai_gate.py --check-approvals` |

**⚠️ 一处我不采信来源的定性**：§0.1 行内的"`1329 个测试函数`"**未必**与"`1497 passed`"互斥 ——
`pytest` 的 `passed` 计数含**参数化展开**，`passed > 函数数`是正常的
（我实测同样是 1601 个 `def test_` 对 1763 passed 的量级）。
⇒ 这一处我按"**过期**"登记，**不**按"行内自相矛盾"登记。**请裁决**（若你认为仍算互斥，我改回）。

**✅ 第五轮核验结论（parent 要求"花一分钟核一件事"）**：
`DEVELOPMENT.md` §0.1 `tests/` 行**确实同时出现了两个数字**，原文逐字（该行完整内容）：
> | `tests/` | 65 个 `test_*.py` + `conftest.py` + `demo_dataset_helper.py`（**1329 个测试函数**，其中按命名约定明确是**负控**的 **287** 个；实测 **1497 passed / 1 xfailed**） |

⇒ **来源说的"行内"这个限定词成立**（两个数字同行共现，我读到了原文）；
但"**自相矛盾**"这半句**仍不成立**，理由是我实测到的机制：
`pytest` 的 `passed` 计数含**参数化展开**，所以"函数数 < passed 数"是合法的
（我同一时刻的口径：`def test_` **1601** 个、全量 `passed` **1763** 个，比例与那一行同量级）。
**结论**：这一处按"**过期 + 同行并列两个不同口径的数**"登记，
**不**按"行内自相矛盾"登记；**并且**它其实暴露了一个更值得修的写法问题 ——
那一行把"测试函数数"与"运行通过数"并列且不标口径，读者无法判断二者是否应当相等。
⇒ 修法已并入本条的建议（改写时必须**逐项标出该数字的口径与观测时刻**）。

> **⚠️ 22:46 观测的增量归因（parent 要求注明）**：`warning 2 → 3`、`info 15 → 21` 的增量
> **全部来自新加的 `R010`**（"装置轴与代码不符"，由在飞包 `43ce64a6` 引入），
> **不是同一批规则报得更多**。对照：22:18 `规则 9 条 / error 0 / warning 2 / info 15`；
> 22:46 `规则 10 条 / error 0 / warning 3 / info 21`。
> **`error` 那一格在 22:25 曾因并发半写文件变成 3**（`R009` 命中 `capabilities.py` / `lint_rules.py` /
> `tests/test_tools_base.py`），**22:46 已回到 0**。
> **我这一轮没有把那次"红"登记成缺陷** —— 它是**与写入同秒的瞬时态**，
> 我单跑 `python -m pytest tests/test_lint_rules.py -q` 得到 **55 passed**（见 `draft/22` §12.9 的原始输出）。
> 记这一句是为了防止下一轮有人从我的报告里把它**当现存缺陷捡回去**。
>
> **🔴 22:51 追加观测（我在第五轮收口复跑时发现，`error` 又变成 2 —— 而且成因是新的）**：
> `python scripts/lint_rules.py` ⇒ **`error 2 / warning 3 / info 21`**，两条都是 `R009`：
>
> | 文件:符号 | 那一处 | 来源 |
> |---|---|---|
> | `tests/test_coverage_gates.py::test_gate_g12_reads_a_present_counterexamples_key_as_a_counter_search_trace` | docstring 里 `**同时**`（Markdown 强调） | `G-36` 的**新增负控用例**（parent 22:4x 落地） |
> | `tests/test_tools_audit_fixes.py::test_no_unexpected_escape_verify_code_hash_io` | docstring 里 `**打在 `open` 上**`（Markdown 强调） | `G-35` 的**文档改写**（parent 同日落地） |
>
> ⇒ **两条修复各自带进了一处 `R009`**（本项目 §6-P17 的"源码注释里的装饰"规则）。
> **影响不止是风格**：`release_all` 的 `release-check` 项**包含 `lint`**
> ⇒ **在清掉这两处星号之前，`release-all` 必然在 `lint` 那一格报红**，
> 而 `G-28` 正在追的就是"发布门的真实状态"。
> **修法（两处、各删一对星号，AI 可做，非禁改区）**：把 `**同时**` 改写成 `同时`，
> 把 `**打在 `open` 上**` 改写成 `打在 \`open\` 上`。
> **这条本身也是 `G-32` 的又一例**：`error` 在 33 分钟内走了 0 → 3 → 0 → 2，
> **任何不带时刻的"当前 error 数"都是错的**。

**影响**：这些数字是**复核者判断"门有没有接上"的唯一入口**
（`DEVELOPMENT.md` §0.0 的 S2/S1 对照就是为这个存在的）。
过期数字给的是**虚假的安心**：`§0.1` 说"1497 passed"而实际更多（无害）；
但 `§0.2 第 5 条`说"退出码 1"而实际 **2**（有害：`unknown` 被读成"已判定为 requires_human"，
而三态纪律要求这两件事必须分开）。

**建议修法**：把"实测数字"从正文搬到一个**由脚本生成的块**
（`DEVELOPMENT.md` §8.2 已经是半成品形态），至少每处补"**命令 + 观测时刻**"；
并加一条检查：**文档里每个 `<命令> ⇒ <数字>` 断言都由该命令复现**。

**验收判据（可判定）**：
- **负控（今天红）**：上面这条检查今天会**大面积红**（11 行里至少 9 行不符）—— 这就是"改动前红"；
- **正控**：`README.md` §4 与 `DEVELOPMENT.md` §0.1 对 `.noai-paths` 条数的说法必须**一致**（今天 18 vs 19）；
- 可跑命令：上表每行的"证据命令"。

**为什么不是 P**：`DEVELOPMENT.md` 与 `README.md` **都不在**禁改区。

---

## G-31：`DEVELOPMENT.md` 说 `usage_ledger`"**仍是零写入方**" —— 早已接线

**现状（实测）**：`DEVELOPMENT.md` **§9.2**「完全未落地（1 条）」的 **FC-19 行**逐字写着
"但**没有任何路径把花销写进 `usage_ledger`** …… **未找到写入方**"，
证据栏是 `grep -rn 'usage_ledger' src/agentflow/` "只在 `schema.py`（表定义）与 `verify.py`（检查）"；
**§9.3 第 5 条**又写"S2 实测：**仍是零写入方** …… ⚠️ **仍未关**"。
实测：写入方**存在且已接线** —— `tokenmeter.TokenMeter.charge_once`（写账 + 锁内判重）、
`conductor.py::_charge_and_settle` 调 `self.meter.charge_once(charge, idem_key=…)`、
`modelcost.charge_reply` 转发（`P-12` 已把这条落地登记在案）。

**⚠️ 对来源的归属更正**：报告 / parent 说"§8.4 待办 7 + §9.3 第 5 条"。
我核了原文：**§8.4 待办 7 是"让禁改区漂移可机械检测"（✅ 已关闭），与 `usage_ledger` 无关**；
第二个正确的落点是 **§9.2 的 FC-19 行**（见本节开头更正 ②）。

**影响**：这是**"未落地"清单里挂着一条已经做完的事** —— 与 `G-15`（ROLE-SPECS 说测试不存在）、
`P-21`（`verify.py` 里词表值写错）同族：**读者会去补一个已经存在的东西**。
更贵的一层：FC-19 的**真实缺口**因此被掩盖 —— 真实缺口不是"没有写入方"，
而是 `G-20`（`USAGE_SCOPES` 五档里只有两档有产出：**钱记了，但归不了口**）。

**建议修法**：把 §9.2 的 FC-19 行从"完全未落地"移到"**部分落地**"，
判据改成 `G-20` 的口径（"账本的 `scope` 分布 ≥4 档非零"）；
§9.3 第 5 条改写为"**已接线（`charge_once`）**，未关的是**归因**"。

**验收判据（可判定）**：
- **负控（今天红）**：一条检查"`DEVELOPMENT.md` 的『未落地』清单里，每条的**执行命令**必须仍成立"
  ⇒ 今天这一条会红：`grep -rn 'usage_ledger' src/agentflow/` 现在**不只**命中
  `schema.py` / `verify.py`，还命中 `tokenmeter.py` / `conductor.py` / `modelcost.py`；
- **正控**：`python -m pytest tests/test_usage_ledger_idem_key.py tests/test_modelcost.py -q` 仍绿
  （接线成立；**不许**因为改文档而回退代码）。

**为什么不是 P**：落点 `DEVELOPMENT.md`（非禁改区）；真值由 `P-12` 的 B 层落地保证（**已实施**）。

---

## G-32：**计数类数字在并发仓库里给不出定值** —— 一律改"区间 + 观测时刻"

**现状（我自己实测的序列；同一台机器、同一天、约 20 分钟内）**：
`python scripts/lint_rules.py` 的 R009 汇总行给出禁改区装饰计数
**430（22:18）→ 462 → 466 → 477**（`tools/base.py` 从 **44 涨到 57**）；
审计方自己的序列是 **455 → 457 → 462**。
而文档里的定值是 `DEVELOPMENT.md` §0.2/§0.3 的 **414** 与
`NOAI-REVIEW-REGISTER.md` 同项的 **430**（来源：审计 §命中 13 + §没扫到的 末条；序列值我复跑补齐）。

**影响**：这不是"数字过期"，而是"**这个数字在这个仓库里根本不可能有定值**"。
两个方向的后果都真实发生了：
1. **复核者被迫追求一个不存在的真值**（"到底 414 还是 430？"—— 都不是，是"**此刻**"）；
2. **任何以此数字做的判断都不可复核**：`draft/23` §4.3 那种"从 414 涨到 423/430 的 +9 归因"
   之所以能成立，是因为它**同时给了观测时刻与基线文件**；
   而没有时刻的定值（§0.2/§0.3）连"它是不是真的涨了"都判不了。

**建议修法（这是本轮唯一的"口径级"建议，应写进文档规范）**：
- 凡**计数类**实测值，一律写成 **"区间 + 观测时刻 + 命令"**
  （例："2026-09-25 22:18–22:40 实测 **430–477** 处；`python scripts/lint_rules.py`"）；
- **禁止**把计数类数字写成"当前真值 = N"：`DEVELOPMENT.md` §0.2/§0.3、`README.md` §4、
  `NOAI-REVIEW-REGISTER.md`、以及**本文件** `G-9` / `G-30` 的表**都适用**；
- 与 `draft/22` §12.2 记的"两个执行体同目录并发"合起来看，本轮最值得写进规范的结论是：
  **并发不只让门随机红/绿，它还让"实测数字"这个体裁本身失效。**

**验收判据（可判定）**：
- **负控（今天红）**：一条 grep 检查"文档里出现『实测 N 处 / N 个』时，同句必须有观测时刻或区间"
  ⇒ 今天红（§0.2/§0.3 与 `README.md` §4 都是裸定值）；
- **正控**：允许"区间 + 时刻"形态通过 —— **不许**把门写成"禁止写数字"，那会把**证据**也一起禁掉；
- 可跑命令：`1..3 | %{ python scripts/lint_rules.py } | Select-String '处装饰'`
  （同会话说出不同的数，即为证据本身）。

**为什么不是 P**：落点是文档口径（非禁改区）；且它要改的是**写法**，不是判据强度。

> ⚠️ **统一口径（2026-09-25 第四轮审计追加；并入，不新增号）** —— 本条从"R009 装饰计数"
> **升级为全仓计数类数字的统一口径**。第四轮又一次实测到同一现象（同一分钟内）：
> `public=561→562→563`、`zero=121→120→119`（22:33:50 / 22:35:24 / 数秒后）。
> ⇒ **规则（适用于本文件、`DEVELOPMENT.md`、`README.md`、`NOAI-REVIEW-REGISTER.md` 与 `draft/`）**：
> 1. 一切计数必须写成 **"区间 + 观测时刻 + 复跑命令"**，**禁止**"当前真值 = N"；
> 2. **不许**用两个不同时刻的数字做**趋势叙事**（"从 106 降到 99"）——
>    除非同时给出两个时刻与同一命令（`draft/23` §4.3 那种形态才是合规的）；
> 3. **`tools/coverage_zero_test.py` 自己 docstring 里"同一条命令 ⇒ 同一个数字"这句承诺，
>    在当前仓库条件下不成立，必须改写**（改成"同一命令 + 同一时刻快照 ⇒ 同一个数字"，
>    并要求引用时带时刻）。这是本条最具体、最容易漏的一个落点：
>    **判据工具对自身可复现性的承诺，也是一条需要被复核的判据**；
> 4. 由此得出一条**排期纪律**（已写进 `draft/22` §12.7.5/§12.8）：
>    凡"改文档"的工作，都要排在 `G-32` 的写法口径之后，否则改完立刻又成为过期定值。

---

## N-8：第三轮审计**主动纠正的两条假阳性**（**记录，免得后人重提**）

**来源：`temp\audit-doc-vs-code.md` §假阳性说明 第 1 条与第 7 条。**

1. **"8 个 agent 自检 exit 0"成立，文档没写错**（`DEVELOPMENT.md` §0.0 S2 / §8.4 待办 4）。
   审计第一遍用 `foreach` 跑自检时，`$LASTEXITCODE` 取到了 **`Select-Object` 的退出码**，
   于是误报 `agent_c` / `agent_d` exit 1；**逐条直跑后 8 个 agent 全部 exit 0**
   （`agent_a` 24/24、`b` 18/18、`c` 46/46、`d`–`h` `SELF-CHECK DONE`）。
2. **`README.md` §6 的 `acceptance` / `repro` 不是虚构**：它们不在仓库根，而在
   `D:\Incubator\test\test2\`（`tools/release_all.py::build_steps` 取的是
   `root.parent/"test"/"test2"`）；审计按"仓库内查找"判过"不存在"，**是错的**；实测两项 **exit 0**。

**为什么不是缺陷**：两条都是**审计手法 / 审读者**的错，不是被审对象的错。
登记它们的唯一目的是：**下一个人不要把同两条再当缺陷提一遍**（这正是 N 类存在的理由）。
**为什么不能照字面修**：**不许**为了让审计报告"全绿"去改 `DEVELOPMENT.md` 那两句或加注
（**文档是对的**）；要改的是**审计手法**（逐条直跑、跨目录查找），而这一条记在这里就够了。
**附带价值**：第 1 条直接变成 `G-27` 验收判据里的一条禁令（禁止 `foreach` + 裸 `$LASTEXITCODE`）——
一次假阳性换来一条判据的写法约束，这是本轮少见的"坏消息变资产"。

---

## N-9：第三轮审计的**未覆盖清单**（**记录：这一轮的结论边界在哪**）

**来源：`temp\audit-doc-vs-code.md` §没扫到的。逐条登记，免得"被审计过"被读成"已全部核实"：**
- `NOAI-REVIEW-REGISTER.md` 的 **14 条 hash 未逐条复核**（只确认 `entries` 长度 = 14）；
- `docs/ROLE-SPECS.md` **未逐节反查**（只跑了结构门）；`docs/INDEX.md`、`DESIGN*.md`、
  `docs/SCHEMA-*`、`docs/TOOLBOX-DRAFT-roles.md`、`docs/NOAI-*.md` **完全未扫**；
- 联网 / OCR / LLM 路径**未端到端跑**（无 `AGENTFLOW_MODEL_API_KEY`）
  ⇒ `FC-14`"未端到端"**未核实**；
- FC 矩阵 **27 条只核了 6 条**（FC-05 / 07 / 17 / 19 / 24 / 27）；
- 本文件 **25 条只核了 3 条**（P-12 / N-2 / G-9）；
- 计数类数值**只给区间，未定值**（因仓库被并发修改，见 `G-32`）。

**为什么这不是缺陷**：未覆盖是**审计的边界**，不是被审对象的缺陷。
这张清单的价值是**防止过度声称**：没有它，"跑过一次文档审计"会被读成
"文档与代码已经全部对账"（FC-22 的典型形态）。
**为什么不能照字面修**：**不许**靠"再扫一遍全部文档"把这张清单消掉 ——
那是把"边界可见"换成"边界消失"；正解是**让边界随每次审计重写**，
并把"P-1…P-11 / G-1…G-12 其余未核实"作为**下一轮的任务量**逐条消掉。

> **第四轮追加（`temp\AUDIT-REPORT.md` §没扫到的；并入，不新增号）**：
> ① **`src/` 里的判据本身是否真空通过只覆盖了 4 个点名入口**（外加 2 个补充入口），
> **未穷举 552+ 个公开函数**；
> ② **动态 mock 未穷举**（`patch.object` 走字符串拼接、`sys.modules` 注入）；
> ③ **"断言了但太弱"无法机械判定** —— 该审计给的是**形态判据**，不是强度判据；
> ④ 零测试清单里 `indirect_only` 的上界（**61**，22:33 快照）**未逐条核实**；
> ⑤ `via:test_name`（名义覆盖）**273 个**，其中 **43 个唯一证据就是名字**（抽核的 7 个都真的被调用，
> 但**未穷举**）；另有 **44 个**被判 `tested` 却 `via:direct` 为空 —— 全部**未逐条核实**；
> ⑥ 仓库并发改动使**任何计数都只是时刻快照**（该审计为只读，未冻结 `src/`）；
> ⑦ 第四轮的恒真断言扫描是**穷举的**（79 个测试文件 / 1764 用例全收集）——
> 这是本文件**第一次**能说"某一类形态已经穷举"，**其余所有未覆盖项仍适用第 1 条纪律**：
> **未覆盖必须随时间重写，不许因为"扫过一次"而被读成"已全部核实"。**

---

# 增补（第四轮，同日）：**不可能失败的测试**（`temp\AUDIT-REPORT.md`）

> 来源：`D:\Incubator\temp\AUDIT-REPORT.md`（只读审计，脚本在 `temp\`，**未改仓库任何文件**）。
> 方法：`ast` **穷举**全部 `tests/*.py` 的每条 `ast.Assert`（恒真形态）+
> 全量回收 31 个 mock 目标 + 4 个入口的"真空通过"直接探测（每条配"必须变红"的对照）+
> 直接调 `tools/coverage_zero_test.py` 的 `collect_src/mark_tested` 看 `via:` 分量。
>
> **本轮登记：新增 3 条 G（`G-33`…`G-35`）+ 1 条 N（`N-10`）；原位追加 3 处**
> （`G-29` 加**前置依赖**、`G-32` 加**统一口径**、`N-9` 加**第四轮的未覆盖清单**）。
> **P 类本轮无新增** —— 落点全在 `tests/` 与 `tools/`（非禁改区）。
> 编号连续无洞：**P 1..23 / G 1..35 / N 1..10**。
>
> ⚠️ **对来源的一处路径更正**：`_name_pattern` 的那个盲区在
> **`tools/coverage_zero_test.py`**，**不是** `scripts/coverage_zero_test.py`（后者不存在）。
> 本文件与 `draft/22` 一律用 `tools/` 的路径（见 `G-34`）。
>
> ⚠️ **本轮的"好消息"也一并登记**（`N-10`）：恒真断言全仓**只有 1 条真命中**；
> `assert True` / `not False` / `raises` 空体 / xfail 静默通过**全部 0 命中**；
> **`lint_rules.run_all(空树)` 会正确 fail-closed**（推翻了"lint 在空树上真空通过"的预期）。

---

## G-33：一条**恒真断言**（`or True`）—— 用例声称"两个版本概念必须分开"，而它在两者**相等**时照样绿

**现状（实测，穷举扫 79 个测试文件后**只有这一条真命中**）**：
`tests/test_fc05_contract.py::test_schema_version_and_contract_version_are_separate_concepts`
的断言逐字是

```python
assert agentflow.CONTRACT_VERSION != agentflow.__schema_version__ or True  # 允许偶合，但不要求相等
```

`or True` 让整条断言**无条件为真** ⇒ 它是**一条不可能失败的用例**。

**⚠️ 三个必须一起读的事实（否则修法会修错）**：
1. **作者是刻意的**：行尾注释逐字写着"**允许偶合，但不要求相等**" —— 所以这不是笔误，
   而是"我不打算断言这两个值不相等"的显式表态（按开头三分类的字面定义，它可以被辩成 N）。
   **但我判它是缺陷**：**用例名与它断言的事实不符** —— 名字说 `are_separate_concepts`，
   断言却什么都没说。这正是 `G-35` 的同一族（"断言不到声称对象"）。
2. **今天就相等**：`src/agentflow/__init__.py:__schema_version__ = 1` 与
   `src/agentflow/interactions.py:CONTRACT_VERSION` **都等于 1**（实测 `equal = True`）。
3. ⇒ **光删 `or True` 会让这条用例立刻红**（`1 != 1` 为假）。所以来源建议的
   "删掉 `or True`，不相等时绿、相等时红"**不能直接照做** —— 它会把一条恒真的用例
   换成一条**恒假的**用例（在当前的常量取值下）。

**真正可判定、且今天能成立的判据：断言"**两个版本常量的来源不同、单一来源**"**（不是值不相等）：
- `__schema_version__` **定义在** `src/agentflow/__init__.py`（管数据格式）；
- `CONTRACT_VERSION` **定义在** `src/agentflow/interactions.py`，`__init__.py` 只是
  `from .interactions import CONTRACT_VERSION`（**它自己的注释逐字写着**"权威定义在
  `interactions.CONTRACT_VERSION`（契约模块自己持有自己的版本）"）。
⇒ 可断言：`agentflow.CONTRACT_VERSION is agentflow.interactions.CONTRACT_VERSION`
（同一对象、**权威定义只有一处**），且两者各自的**赋值点**在**两个不同的模块**里。

**建议修法（两步，缺一不可）**：
1. 把用例名 / docstring 改成它**真正**断言的事（"两个版本常量各有**单一权威定义**、可独立升版"），
   并把断言换成上面那条**可判定**的形态 + 一条"值域"断言（都是 `int`）；
2. **不要**保留 `or True`，**也不要**写成 `assert A != B`（今天会红）。
   若人裁定"必须保证两者真的分开"，那是一次**口径决定**，且落点含
   `src/agentflow/interactions.py`（**禁改区**）⇒ 走 P 的人审通道，**不在本条范围内**。

**验收判据（可判定）**：
- **负控（必须会红，且要真的跑过）**：在 `src/agentflow/__init__.py` 里**复制**一份
  `CONTRACT_VERSION = 1`（造出"两个并列来源"）⇒ 新断言必须红
  （`is` 同一性 / 单一来源那条会失败）；这条负控**今天不红**（因为今天只有一个来源），
  所以它必须**手工注入一次并留下输出**，不许写成"应该会红"；
- **正控**：现有其它断言（`test_fc05_contract.py` 其余用例）不受影响；
- 可跑命令：`python -m pytest tests/test_fc05_contract.py -q`
  与 `python -c "import agentflow;print(agentflow.CONTRACT_VERSION is agentflow.interactions.CONTRACT_VERSION)"`。

**为什么不是 P**：最小修法落在 `tests/`（非禁改区）⇒ G。
（"让两个常量真的分开"那条路要动 `interactions.py`（禁改区）——那是**另一次**、需要人审的决定。）

> ✅ **裁决落定（2026-09-25 第五轮；parent 裁决 1）**：**按"来源单一"落**，
> 不采纳"值必须不相等"。六条逐字落定：
> ① 用例名与断言不符 ⇒ 判 G 成立；② 断言改成
> `agentflow.CONTRACT_VERSION is agentflow.interactions.CONTRACT_VERSION`（同一对象）+ 值域断言；
> ③ 负控：在 `src/agentflow/__init__.py` **复制**一份 `CONTRACT_VERSION = 1` 字面量 ⇒ 必须红
> （手工注入、留"注入前绿 / 注入后红 / 撤销后绿"三次原始输出）；
> ④ **不许只删 `or True`**（今天两者都 = 1 ⇒ 会立刻红）；
> ⑤ `interactions.py` 是禁改区，**本轮不动** ⇒ 人审 **0**；
> ⑥ "若必须真的分开 ⇒ 落禁改区"是**备选**，**默认口径是"来源单一"**。
>
> ⚠️ **我对裁决 ② 的技术更正（实测，必须先读）**：指定的 `is` 断言**单独用不可判定**。
> 只读探测（`temp\probe5.py`）：
> `agentflow.CONTRACT_VERSION is agentflow.interactions.CONTRACT_VERSION` **注入前 = True**；
> 执行 `agentflow.CONTRACT_VERSION = 1` —— **正是裁决 ③ 的负控动作** —— 之后**仍然 = True**。
> ⇒ **CPython 的小整数缓存（-5..256 interning）让"复制一份字面量"在 `is` 上看不出来**，
> 于是那条负控**不会红**，"可判定"这一半会**落空**（一条不会红的负控与没有负控同义）。
> ⇒ 实现时必须**再加一条静态来源检查**（这一条才可判定）：
> `src/agentflow/__init__.py` 的源码里 `CONTRACT_VERSION` **只允许以 import 形态出现**
> （`from .interactions import CONTRACT_VERSION`），**不得有任何赋值**。
> 判定命令：`grep -n "CONTRACT_VERSION" src/agentflow/__init__.py`
> ⇒ 今天只有第 50 行的 import 与 `__all__`，**没有任何 `CONTRACT_VERSION =`**；
> 负控 ③（复制字面量）**会让这条静态检查红**。
> ⇒ 判据必须是"**静态来源 + 动态 `is`**"两条并列，**不是只有 `is`**。
> **这是按实测对裁决的细化，不是推翻裁决** —— 口径仍然是"来源单一"。

---

## G-34：**判据工具自身的盲区**在制造假缺口 —— `tools/coverage_zero_test.py::_name_pattern` 把 `.` 也排除

**现状（实测，来源：`temp\AUDIT-REPORT.md` §零测试函数）**：
`tools/coverage_zero_test.py::_name_pattern` 返回
`re.compile(rf"(?<![\w.]){re.escape(needle)}(?![0-9A-Za-z])")` ——
**左边界 `(?<![\w.])` 把 `.` 也列为"不允许的前缀"** ⇒
**任何以"`别名.函数名(`"形态被调用的函数永远拿不到 `via:direct`**，
而本仓库 `tests/` 通篇是 `G.` / `S.` / `T.` / `I.` / `D.` / `P.` 这类别名。

**实测规模**：**83 个**函数确实以"`别名.名(`"形态出现在 `tests/` 里、却没拿到 `via:direct`；
其中 **39 个被工具报成 `zero_test`（假缺口）**、**19 个等级 ≤2**。
抽核 10 个（`S.now_iso`、`store.read_events`、`C.split_claims`、`S.is_valid_id`、
`P.dedup_key_of`、`D.find_existing_literature`、`cli.build_parser`、`spec.to_function_schema`、
`T.short_hash`、`IX.opposite_flags`）**全部真的被直接调用**（无一是注释 / 字符串）。
⇒ **"106 / 114 个零直接测试公开函数"这个数字被高估了约 39，实际零测试上界 ≈ 81**
（且这个 81 随并发改动每分钟在变，见 `G-32`）。
另有 **44 个**被工具判成 `tested` 但 `via:direct` 为空（只靠 `via:test_name` 兜住）——
它们的"有测试"结论**证据强度低于命名所暗示的**。

**影响**：这条比它造成的数字错误更严重 —— 它是**元缺陷**（与 `G-26` 同族）：
`tools/coverage_zero_test.py` 是**本仓库"补测试"这项工作的唯一驱动**，
它错报的方向是"**报多了**"，于是：
1. 有人会去给**已经被直接调用**的函数补测试（**重复劳动，且会稀释真正的缺口**）；
2. `G-9` 那张表、`draft/22` §12 的排期、以及 `release_all.py` 的 `coverage` 项
   **全都建立在这个数字上**。

**建议修法**：左边界放宽为 `(?<![\w])`（只排除真正的词字符），
**或**（更保险）保留现判据、**单加一条 `via:alias_direct` 分量**
（匹配 `\w+\.needle\(` 并要求那个前缀在文件里被 `import ... as` 绑定）——
后者能把"别名直呼"与"某个对象的同名属性"区分开。**建议先加分量、不先改判据**：
改判据会让历史数字不可比（`G-10` 的既有结论）。

**验收判据（可判定）**：
- **负控（今天红）**：抽核 10 个（上面那批）⇒ 新分量必须把它们从 `zero_test` 里移出；
  今天它们**在** `zero_test` 里 ⇒ 判据在改动前是红的；
- **正控**：**真的**零测试的函数（例如本轮核实的 `formalgw.evidence_of`，
  **前提是它不在别名盲区里** —— 见 `G-29` 的前置依赖）**不许**被新分量误判成"有测试"；
- 可跑命令：`python tools/coverage_zero_test.py --json <out>` 后查 `tested_by` 的 `via` 分量；
  以及 `python D:\Incubator\temp\probe_blind.py`（本轮的证据脚本）。

**为什么不是 P**：落点 `tools/coverage_zero_test.py`（非禁改区）⇒ G。
⚠️ **它有一个硬前置**：**先修工具，再判 `G-29` 的两个函数到底缺不缺测试**
（`G-29` 已按此更新；**不许**拿假缺口当真缺口去补测试）。

> ✅ **裁决落定 + 三处加深（2026-09-25 第五轮；parent 裁决 2 与其独立实测）**：
> **按"先加 `via:alias_direct` 分量、不改左边界"落**（保历史可比，`G-10` 的结论不作废）；
> **且 docstring 必须同轮改写**（见加深 1）。改完后**重跑 `--level 2`**，才裁定 `G-29` 的 (a)/(b)。
>
> **加深 1 · 同一段 docstring 内部自相矛盾（原文逐字，我复跑确认）**：
> `tools/coverage_zero_test.py::_name_pattern` 的 docstring 先写
> "于是 `test_adjudicate_contradiction_rejects_x` 与 `I.adjudicate_contradiction(` **都能命中**"，
> 紧接着的下一节又写 `_name_pattern` 的左侧要求让它**匹配不上** `def test_...`
> ⇒ 前一句是**第一版判据的过期理由**，修正后没有跟着改。**两句不可能同时为真。**
> 我的只读探针（直接调 `_name_pattern`）：
>
> | 探针文本 | 命中 |
> |---|---:|
> | `I.adjudicate_contradiction(` | **0** |
> | `def test_adjudicate_contradiction_rejects_x():` | **0**（由单独的 `_TEST_NAME_TMPL` 承接） |
> | `adjudicate_contradiction(x)`（对照） | 1 |
> | `subadjudicate_contradiction(`（对照，验右边界） | 0 |
>
> ⇒ docstring 前一句是**假的**，必须与本条的实现**同轮**改写
> （否则"理由比实现旧"会再骗一个人 —— 与 `G-15`、`G-31` 同病）。
>
> **加深 2 · 单点可复核的差分（比"39 个"那个聚合数更硬）**：
> 同一 needle `adjudicate_contradiction` 在 `tests/` 里以 `.adjudicate_contradiction(` 形态出现 **9 次**，
> 当前判据命中 **0 次**。⇒ "**9 vs 0**"是任何人一条命令就能复现的证据。
>
> **加深 3 · 根因比"左边界"更具体（会影响实现选择）**：这个盲区**不是正则不可救** ——
> 实测把 needle 换成**别名限定名** `I.adjudicate_contradiction` 时，**同一个 `_name_pattern` 命中 9 次**。
> 也就是说：**工具从来没有尝试过"别名限定名"这个 needle**（它只试 `info.qualname` 与 `info.bare`）。
> ⇒ 最便宜的实现可能不是新写一条正则，而是**在既有循环里补"别名限定名"这个 needle**
> （效果与 `via:alias_direct` 等价，还复用同一套左右边界语义）。
> 两种实现都可接受，但**必须各自带负控**（① 改成 `别名.名(` 形态 ⇒ 分量出现；
> ② 删掉那处别名调用 ⇒ 分量消失，证明它不是恒真），且**都不许改动 `via:direct` 的语义**。

---

## G-35：**断言不到声称对象** —— 用 `monkeypatch` 把**被测函数本身**换成替身

**现状（实测，来源：`temp\AUDIT-REPORT.md` §断言不到声称对象）**：
`tests/test_tools_audit_fixes.py::test_no_unexpected_escape_verify_code_hash_io` 的 docstring 声称
"`verify.code_hash`：`open()` 的 OSError（文件被占用 / ACL 拒绝）**不再逃逸**"，
而实现是 `def boom(_path): raise PermissionError("拒绝访问")` +
`monkeypatch.setattr(VT, "code_hash", boom)` ——
**它把被测函数整个换掉了**，于是断言测的是"**替身抛错时工具层的 guard**"，
`code_hash` 真实现里的 `open()` 分支**一行都没被走到**。
（同族：`…_ocr_page_count_and_pdf_pages` 打桩 `OT.page_count`。）
全仓 31 个打桩目标里，**只有这 2 处是真替被测函数**。

**⚠️ 如实降级（不许把这条说重）**：该用例**末尾有 `monkeypatch.undo()` 后的真路径复跑**，
所以它**不是**"只测桩"（来源自己标了这一点）。
准确的结论是：**"逃逸已被修好"这个判断，在真实现的 `open()` 分支上仍未经验证**。

**影响**：这是 `G-21` / `G-22` 的同族（"看起来在守、实际守不住"），但形态更隐蔽：
**它测的东西是真的**（替身抛错 ⇒ guard 生效），**只是它测的不是它声称的那个对象**。
⇒ 下一个人读到"`open()` 的 OSError 不再逃逸：✅ 有测试"，会**跳过真正的验证**。

**建议修法**：让**真** `code_hash` 撞一个**真实的** `PermissionError` ——
在 `tmp_path` 里造一个只读目录 / 占位文件（Windows 下可用
`os.chmod(path, stat.S_IREAD)` 或对目录加 ACL；**若该环境做不到**，
就在用例里**显式标注"本平台无法构造该条件 ⇒ 本分支未验证"**，
而不是用替身换掉被测函数 —— **"未验证"必须可见，不许伪装成已验证**）。

**验收判据（可判定）**：
- **负控（今天红）**：一条检查"用例声称验证的函数 `F`，在用例执行期间**不得**被
  `monkeypatch.setattr` / `patch` 替换掉"（可机械做：把打桩目标名与用例点名 / 被测入口名比对）
  ⇒ 今天这 2 处会红；
- **正控**：其余 29 个打桩目标（打的是**下游边界**：外部检查器、`S.Literature.validate`、
  `AgentA.run` 等）**必须保持绿** —— 打桩边界是正当的，判据**不许**一刀切禁 mock
  （那会把 `test_tools_audit_fixes.py` 的整类负控砍掉）；
- 可跑命令：`python -m pytest tests/test_tools_audit_fixes.py -q`。

**为什么不是 P**：落点在 `tests/`（非禁改区）⇒ G。

> ✅ **裁决落定（2026-09-25 第五轮；parent 裁决 3）**：**按"如实降级"落** ——
> 先试真 `PermissionError`；构造不出就**保留桩**，并把标签写成"**本平台未验证**"，
> **禁止**写成"已修复"。
>
> **我的构造尝试（只读探测，结论：本平台构造不出）**：
> ① `VT.code_hash(<一个真实目录>)` ⇒ 在 `open()` **之前**就被判成
> `ParamError: 文件不存在：src`（它先查 `is_file()`）⇒ **到不了 `open()`**；
> ② 用 `icacls <file> /deny <当前用户>:(R)` 造"拒绝读"的 ACL 之后，
> `VT.code_hash(<该文件>)` **仍然返回了哈希值**（本会话的进程没有被那条 deny 挡住）
> ⇒ **没有拿到 `PermissionError`**。
> ⇒ 结论：**在本机（Windows + 本会话的进程权限）无法构造真实条件**，走裁决 3 的第二条路。
>
> **实现要求（落在 `tests/`）**：标签逐字写
> "**本平台未验证：真实现的 `open()` 分支未被本用例执行**"，
> 并**同时保留**"替身抛错 ⇒ guard 生效"这一半 —— 它是**真的测到了东西**，
> 删掉等于丢掉唯一的证据（**降级**不等于**删除**）。

> ✅✅ **追加二（同日，parent 已落地）：本条已按"真路径"修完并实测通过 —— 上面那段"如实降级"的执行方案作废**。
> **最终结论不是"未验证"，而是"已验证（真路径）"。**
>
> **为什么走第三条路（前两条候选都被实测推翻，记录在此以免重走）**：
> 1. `open(一个目录)` 在 Windows 上**确实**抛 `PermissionError(13)`；`os.chmod(p, 0o444)` 后以**写**模式
>    `open` 也抛 13 —— 但这两条对 `code_hash` **都不成立**：它先做
>    `if not p.is_file(): raise ParamError(...)` ⇒ 目录被拦成 **`ParamError`**（不是 `PermissionError`）；
>    而只读属性在 Windows 上**只挡写、不挡读**，`code_hash` 是**读**打开的。
>    （我上面那两条探测独立复现了同一个障碍：目录 → `ParamError`；`icacls /deny` → **仍读得到**。）
> 2. 真实 ACL 路线要 `icacls /deny`，**会改 `tmp_path` 的 ACL**，失败时还会留下拒读 ACE ⇒ 得不偿失。
> 3. **正解是换"桩的位置"，不是换数据**：把桩从**被测函数** `code_hash` 挪到**它体内调用的 `open`** ——
>    `code_hash` 里的 `open` 按 globals → builtins 解析，所以
>    `monkeypatch.setattr(VT, "open", boom, raising=False)` 会在**真实函数体内**生效，
>    **函数体被真正执行**；`raising=False` 是为了容忍"某天实现把 `open` 显式导进本模块 globals"。
>    实测：未打桩时 `code_hash` 返回 `f1776ce4397fa7cb`；打桩后**真实 `code_hash`** 抛 `PermissionError`，
>    被拦路径正是传入的那个文件；撤桩后返回值**逐字相同** ⇒ 桩确实进到了函数体，且没有顺手改掉别的行为。
>
> **已落地（parent 做的）**：`tests/test_tools_audit_fixes.py::test_no_unexpected_escape_verify_code_hash_io`
> ① `monkeypatch.setattr(VT, "code_hash", boom)` → `monkeypatch.setattr(VT, "open", boom, raising=False)`；
> ② 被测路径从 `"x.py"`（不存在 ⇒ 真实现会先抛 `ParamError`）改成**先在 `store.root` 写一个真实
> `probe.py`** 再传 `path="probe.py"`；③ 负控保留在**同一个用例**里
> （`monkeypatch.undo()` 后同一条路径必须返回 **16 位 hash**）；
> ④ docstring 写明"桩打在被测函数上等于把整个函数体换掉，逃逸根本没被执行"。
> 实测：`pytest tests/test_tools_audit_fixes.py -q` ⇒ **45 passed**。
>
> **⚠️ 必须保留的残余说明（否则后来者会以为 `code_hash` 有兜底）**：
> `code_hash` **自身不做 try/except** —— 异常按设计**上抛**、由**工具层**映射成 `io_error`。
> 也就是说"逃逸"的兜底在**工具层**、不在 `code_hash` 里；
> 任何"给 `code_hash` 加个兜底更保险"的想法都是在**改判据面**
> （它在 `verify.py` 的禁改区族里，要人审）。
>
> **档位**：**P1（已闭环）**，**不计入"可立即插入"条数**
> （该档因此从 **7** 条降为 **6** 条：`G-17`·`G-22`·`G-23`·`G-27`·`G-33`·`G-34`；见 `draft/22` §12.9）。

---

## N-10：第四轮审计**排除的假想缺陷**与**两个正面结论**（**记录，免得后人重扫**）

**来源：`temp\AUDIT-REPORT.md` §恒真/无效断言、§被 mock 掉的被测对象、§真空通过、§假阳性说明。**

**已排除（扫过、不是缺陷）**：
1. **恒真形态全仓只有 `G-33` 那一条真命中**：`assert True` / `not False` /
   "唯一 `is not None`" / `pytest.raises` **空体** / **xfail 静默通过** 全部 **0 命中**；
   全仓**唯一** `xfail` 是 `strict=True`（`test_coverage_interactions.py::…_rejects_blank_only_relation_ids`）
   ⇒ **无 xpass 风险**。
2. **"声称并发但只跑单线程"：未找到真例** —— 所有含 `thread/race/concurren` 的用例要么真起
   `threading.Thread` + `Barrier`，要么测的是策略计数。**整类判为假阳性。**
3. `tests/test_modelcost.py::test_idempotency_key_is_stable_and_index_sensitive` 的
   `assert f(x) == f(x)` 形态：**确定性函数上的自比较是合法写法** ⇒ 记为"形态命中、判据误报"，
   **不是缺陷**（**不许**因为形似 `G-33` 就去改它 —— 那是把 `G-33` 的判据用成噪音）。

**真空通过探针的结论（穷举了 4 个点名入口 + 2 个补充入口）**：
| 入口 | 空输入 | 判定 |
|---|---|---|
| `gates.gate_verdict({})` | `accepted` + "15 道门全部通过"（**"15"写死**） | **真空**，但**已有自觉钉子**（`tests/test_coverage_gates.py` 对应用例 + 本文件 `G-5`）⇒ **不是新发现** |
| `verify_all(空工作区)` | `ok=True`、0 错 0 警 | **真空但设计如此**（零行库确实自洽）⇒ 无假信号 |
| `verify._id_contiguity([], 'lit_id')` | `(True, [], -1)` | 真空（零行上无条件真） |
| `capabilities.audit_task_ledger([], store=空)` | 0 issue | 真空（空台账绝对干净） |
| **`lint_rules.run_all(空树)`** | `src_py=0 tests_py=0`，**1 个 error**（R009 读不到 `.noai-paths`） | **不真空 —— 正确 fail-closed** |
| `ToolRegistry().for_role('C')` | 0 个工具 | 真空（空注册表下"只读拿不到写工具"无条件真） |

**其中最有价值的是第 5 行**：它**推翻了一个预期** —— "lint 在空树上真空通过"是错的，
`lint_rules` 会把"读不到清单"判成 `error`（而不是悄悄全绿）。
这与 `noai_gate` 的 `unknown ≠ clean`、`verify` 的三态是同一条纪律的第三次独立实例。
**为什么这不是缺陷 / 为什么不能照字面"修"**：前四条里，`gate_verdict` 那条**已有钉子与登记**，
另三条是"零行库 / 空台账 / 空注册表确实满足这些不变量"——它们**不是假信号**，
而是"这些判据的作用域本来就是非空输入"。⇒ 正解不是给它们加"非空"断言（那会改变语义），
而是**把作用域写进 docstring**（"本判据对空输入返回 X，因为……"），
让下一个做同类审计的人**不必再探一遍**（`N-4` 的价值在这一点上完全一样）。

> ⚠️ **范围更正（2026-09-25 第五轮；parent 独立复跑后指出，我复跑确认）**：
> 上面那句"**恒真形态全仓只有 1 条真命中**"**范围写错了** —— 它只对 `tests/` 成立。
> 全仓正则复跑（`temp\probe5.py`，只读）：
>
> | 文本命中 | 现状 |
> |---|---|
> | `tests/test_fc05_contract.py:156` 的 `assert ... or True` | **活的恒真**，归 `G-33`（按"来源单一"裁定处理） |
> | `src/agentflow/gates.py:1459` | **曾经是** `has_search = has_search or True`，**已修**，现在只剩一行注释说明（见 `G-36`） |
>
> ⇒ **修复前全仓 2 处活恒真；现在活的只剩 1 处**（`tests/` 那条）。
> **这次更正的价值不在数字，而在它暴露的形态**：我的普查**把范围限定在 `tests/`**
> （当轮简报说的是"不可能的测试"），而结论却写成了"**全仓**"
> ⇒ **普查范围没写清 ⇒ 结论被高估** —— 这与 `N-9`（未覆盖清单）是同一条纪律的又一次落地。
> **处置**：本条正文原句保留 + 本段范围更正，**不许**直接改成"全仓 2 处"了事
> （那会把"我为什么会写错"这条教训一起删掉）。
> **归谁修**：`tests/` 那处随 `G-33` 一起落；`gates.py` 那处**已闭环**（`G-36`）。

---

## P-24：禁改区（FC-27）**临时开放**（suspension）—— 决定、开放期底线与复闭判据

> **本条的时点**：2026-09-25。上面第四轮增补的结尾记的是"**P 类本轮无新增**（P 1..23）"，
> 本条是**同日的另一件事**（治理决定，不是审计发现），所以它**不与那 13+3 条同批**。

**一句话**：所有者授权"先开放"，于是禁改区那道"**先人编写 / 先人逐行走查**"的**顺序**被
**临时暂停**（清单与门**一处未动**）；完整的授权原文、开放期六条底线、八条复闭判据
（逐条带命令 + 期望输出）、风险与代价、以及"数字必须写成区间 + 观测时刻"的方法论纪律，
**逐条写在 `docs/NOAI-SUSPENSION-2026-09-25.md`**（本条的正文就是那份记录，此处不复制）。

**授权原文（逐字）**：

> "禁改区里的问题有点多，先开放吧，做得足够好了再封闭回去。"

**判据**：`Select-String -Path docs\PROPOSALS.md -Pattern '^## P-\d+'` 里 `P-24` **只出现一次**
（编号纪律：唯一 / 引用存在 / 空洞写明，由 `tests/test_proposals_register.py` 照常守它）。

**它明确地没有改什么**（这三条就是"可复闭"的全部理由）：

1. **`.noai-paths` 与 `AGENTS.md` 的清单一字不动** ⇒ `--check-consistency` 继续退出码 **0**；
   复闭时**不需要重建、也不需要逐字还原**（本仓库**不是 git 仓库**，删了就没有历史可回滚）；
2. **门继续判 `requires_human` / `required_approvals=2`** ⇒ 这笔债在开放期**一直显示**
   （复闭时一次性补签），不会被"开放"这件事抹掉；
3. **`.noai-approvals.json` 的 `reviewers` 仍只由人填**（`ledger_self_approval` 与
   "`--baseline` 不写 `reviewers`"两条纪律照旧）—— 开放期 AI 只做 `--baseline`（登记 hash）。

**为什么必须是"记录"而不是"删清单"**：本仓库**没有 git**。删掉 `.noai-paths` 的条目或改
`AGENTS.md`，等要复闭时**无法逐字还原**；而且两处一致性门
（`check_manifest_consistency` 按 `(glob, category, 理由)` 三元组按位比对）**立刻破**。
⇒ 停用的是**顺序**，不是**可见性**。

**为什么它仍占一个 P 号（而不是另开一套编号）**：它是**人授权**类条目，
其余两类都装不下它；而编号纪律对它是同一套（`G-19` 那条"只读禁改区声明、不改禁改区文件"
也是按"落点非禁改区"归 G 的 —— 本条的**落点是 `docs/`**，纯文档、无实现改动）。
⇒ 若所有者裁定"治理记录不入 P 类"，本条应整体搬去 `docs/` 另立编号，
**但那时必须同时给 `tests/test_proposals_register.py` 一条新的作用域**（否则引用完整性会断）。

**它排期在哪**：不进任何实现批次。它的**复闭**排在 `draft/22` §12 之后 ——
复闭的前置条件就是那份记录 §3.1–§3.7 的八条（其中 §3.3 的"每个测试文件单独跑"与
`G-27` 是同一件事的两种写法，**不要重复实现**）。

**为什么"复闭"不能由 AI 独自宣布**：复闭判据里最硬的两条是
"`--check-approvals --paths <14 条>` ⇒ `14 28`"与"走查包（§2.3–§2.7）全部签完" ——
它们要的是 **28 份人的签字**。AI 能算出"够不够格"，**签字本身是人的动作**。

---

## G-36：`gates.gate_g12` 里有一处**恒真表达式**（`has_search = has_search or True`），删掉它**没有测试变红** —— ✅ **已修 + 已钉住**

**现状（parent 独立复跑发现，随后已修；三条必须一起读）**：
1. `src/agentflow/gates.py::gate_g12` 里逐字有
   `if "counterexamples" in c: has_search = has_search or True` ——
   `or True` 让该分支等价于 `has_search = True`。**与它 docstring 声明的判据行为一致**
   ⇒ 这**不是活的逻辑错**，而是**真空表达式**：读者无法区分它与笔误
   （与 `G-33` 同族，但落在**生产门代码**里 —— 这是它比 `G-33` 更贵的原因）。
2. **变异存活（实测，非推测）**：把 `src/agentflow` 整包复制到 `temp\g36-mutant\`、删掉那两行、
   用 `-p mutant_shim` 强制 pytest 加载变异体（shim 打印并 assert `agentflow => temp\g36-mutant\...`，
   证明变异体**确实被加载**），跑 `tests/test_coverage_gates.py tests/test_gates.py -k g12`
   ⇒ **7 passed, 0 failed**。⇒ **删掉一条判据，仓库里没有任何一条测试变红，而行为已经变了**（见第 3 点）。
3. **差分实测（同一 claim，唯一差别是"字段在不在"）**：
   - `counterexamples=[]` **有键**、**无** `numeric_evidence.n_counterexamples`：
     线上 `('pass', 有反例搜索痕迹=1, findings=[])`；变异体 `('pass', 0, ['warning'])`；
   - 两样都无（对照）：线上 `('pass', 0, ['warning'])`；变异体同；
   - 有 `n_counterexamples=0`（对照）：两者都 `('pass', 1, [])`。
   ⇒ 被吞掉的那一格**是真实可观测的行为**，而 `tests/` 里没有任何用例构造过它：
   `tests/test_coverage_gates.py::_claim` 的 base **同时**给了 `counterexamples: []` **和**
   `n_counterexamples: 0` ⇒ 正向用例对这两行**免疫**；负控走的是 `pop` 掉键的那一侧。

**✅ 状态：已修 + 已钉住（附负控）—— 请勿排进待办档**（2026-09-25 第五轮，parent 落地）
- **修复**：`src/agentflow/gates.py::gate_g12` 改成**单一表达式**
  `has_search = ("counterexamples" in c) or (isinstance(ne, Mapping) and ne.get("n_counterexamples") is not None)`，
  并留两行注释说明"这里曾经是恒真表达式"。**三格行为与原文逐格相同**（回归证据见下）。
- **新增负控**：`tests/test_coverage_gates.py::test_gate_g12_reads_a_present_counterexamples_key_as_a_counter_search_trace`
  —— 它把"同一条 claim、只弹掉 `counterexamples` 键"的**正反两侧放进同一个用例**，
  并**显式断言两侧的数不相等**（防夹具漂移把差分抹平 —— 这是一条**判据的判据**）。
- **落地实测（原始输出）**：
  - 线上：`pytest tests/test_coverage_gates.py tests/test_gates.py -k g12 -q` ⇒ **8 passed, 114 deselected**
    （原 7 条 + 新增 1 条）；
  - 变异体（同一 `temp\g36-mutant\` + `-p mutant_shim`）⇒ **1 failed, 7 passed**，
    失败正是**新增的那一条**，断言差分 `{'标『证』的断言数': 1, '有反例搜索痕迹': 0, '问题数': 1} assert 0 == 1`。
  ⇒ **"判据被删必须有人变红"这件事第一次有了证据**（修复前同一条命令是 7 passed / 0 failed = 变异存活）。

**为什么这条是 G 而不是 N**：`has_search = has_search or True` 本身不改变行为，
但它是**门代码里的真空表达式**：任何要改这条判据的人（例如把"键存在"改成"键存在**且有值**"）
都会在**看不出区别**的情况下改动行为 —— 第 3 点证明那一格真的可观测。
⇒ 必须登记为"**曾经存在、已修、已钉住**"，而不是"从来没问题"。
**为什么不是 P**：`gates.py` **不在** FC-27 禁改区（`.noai-paths` 与 `AGENTS.md` 两处清单里都没有）
⇒ 不需人审；但它是**门**的实现 ⇒ **测试必须与改动同轮落地**（本次已满足）。
**档位**：**P1（已闭环）**，**不计入"可立即插入"条数**。
**与本文件其它条目的关系**：它同时**更正 `N-10` 的范围**（"全仓只有 1 条恒真"是错的，修复前是 2 处）；
并给 `draft/22` §12 提供了一条**硬判据**（"门代码里不许有恒真表达式"应有机械检查，
否则下一条还会以同样的方式活下来）。

---

## 本文件的维护规则

1. **新增一条必须同时给出三件东西**：现状（带 `文件:符号` 证据）、判定（P/G/N）、
   **为什么不由 AI 自己做**。缺第三件的一律退回 —— 那说明要么它是 AI 能做的（那就去做），
   要么它根本不该进这张表。
2. **G 类不许悄悄消失**。关掉一条 G 必须在本文件里留下"由谁、哪次、什么证据"。
3. **N 类要写"为什么不能照字面修"**，否则下一个人会再来一次同样的修改尝试。
