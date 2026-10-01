# AGENTS.md —— 给 AI 编码者的硬约束

> **本文件只覆盖「禁 AI 区（FC-27）」这一节。**
> 项目说明与开发规范见 `DEVELOPMENT.md`（另有人维护，本文件不重复）。
> 若你在本仓库里做改动，请**先读本文件**，再读 `DEVELOPMENT.md`。

---

## FC-27 禁 AI 区（人类专属区）

### 为什么存在

某些区域的错误的**代价不可逆**：认证被跳过、支付算错、密钥泄漏、迁移毁数据、
发布脚本失控。这类错误有一个共同特征 —— **单测、类型检查、lint 全都过得去**。

FC-27 的原始论证（`draft/LESSONS-工程经验清单（FC-01…FC-27）.md:716`）逐字如下：

> `07-...md` §C.3.4 给出了 7 类必须由人主导的区域，理由是这些区域的错误代价不可逆
> （认证被跳过、支付算错、密钥泄漏、迁移毁数据、发布脚本失控）；`07-...md` §D.2.1
> 把它制度化："IF 改动落在禁改区（认证/授权/支付/加密/迁移/CI 配置/对外 API
> 破坏性变更）THEN 必须人工编写或人工逐行走查，且需要 **2 名 reviewer approve**"
> ——"否则会：**测试全绿、上线即越权**"。

请特别注意最后那句：**测试全绿、上线即越权**。
"绿灯"在这里不是安全信号，而是最危险的形态 —— 因为**测试覆盖的是我们想得到的情形**，
而禁改区出错恰恰发生在想不到的那一类输入上。

本框架（面向数学研究的多智能体协同框架）把上述七类平移成下面这七类（实测 2026-09-27 12:19 +0800：`.noai-paths` 里的 `[category: ...]` 分组头去重 = 7，命令 `(Select-String -Path .noai-paths -Pattern '^\[category:').Count`）。
平移的原则是：**保留"错误不可逆"这个判据本身**，而不是保留具体的业务名词。

| 原七类（`07-…md` §D.2.1） | 本领域平移 |
|---|---|
| 认证 / 授权 | 权限与审计（角色即权限面） |
| 支付 | 评测口径的定义（口径就是那个数字） |
| 加密 | 来源解析与去重键（文献库的主键） |
| 迁移 | schema 迁移（磁盘格式契约） |
| CI 配置 | 发布与部署脚本 |
| 对外 API 破坏性变更 | 数值求解器的核心算法 / 证明检查器的桥接层 |

### 禁改区清单（机器可读清单在 `.noai-paths`，两处必须逐条一致）

下面这段区块与仓库根目录的 `.noai-paths` **逐条一致**
（`scripts/noai_gate.py::check_manifest_consistency()` 按位比对
`(glob, category, 理由)` 三元组；有负控用例，见 `tests/test_noai_gate.py`）。

> ⚠️ **改这条清单必须同时改两处、且逐条一致。**
> 只改一处 ⇒ `python scripts/noai_gate.py --check-consistency` 以退出码 **1** 失败
> （不一致是"查过了、结论是坏了"，不是"没查成"；2 只留给没查成）。
> 这不是形式主义：两处不一致时，读 `AGENTS.md` 的 AI 与执行门禁的 CI
> 会依据**不同的清单**行动，而**没有任何一条测试会因此变红**。

> 📌 理由里用反引号写**符号名**，**刻意不写行号**：行号易失（本仓库并行开发下
> 实测几十分钟就漂了），而 `test_python_manifest_referenced_symbols_exist` 会断言这些
> 符号真的存在于对应文件里 —— 比行号更强。

<!-- NOAI-MANIFEST:BEGIN -->

```text
[category: solver-core] 一、数值求解器的核心算法（检索/抽取/判重的算法主通道）

src/agentflow/providers.py       [category: solver-core] 检索核心：查询编排 `_plan_mode`、精筛 `_precise_keep`、候选打分 `_broad_sort_key`、各 provider 的 `_parse_work`/`_parse_item` —— 检索口径一旦偏移，"找到的文献"与"声称找到的文献"就分家了
src/agentflow/dedup.py           [category: solver-core] 判重主通道：`decide_relation` 决定一条关系是新增/重复/存疑 —— 判重错则概念图静默地少一条或多一条边，没有任何地方会报错
src/agentflow/extract.py         [category: solver-core] 文本抽取主通道 `extract_text` 及其 PDF 后端：PDF/正文 → 可回验文本 —— 抽取错一个字符，逐字引文回验就会把**真**引文判成幻觉（B 的唯一自动幻觉防线反被摧毁）

[category: prover-bridge] 二、证明检查器的桥接层（与外部检查器交互的部分）

src/agentflow/tools/verify_tools.py  [category: prover-bridge] `detect_verifier` 与 `check_formal`：探测 Lean/Coq/Isabelle 并解释其输出 —— 桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印
src/agentflow/quoteverify.py         [category: prover-bridge] `check_quote` 引文级回验：把一条断言与来源文本逐字比对 —— 它是"外部证据"与"我们自己的断言"之间的桥，错判即幻觉引文进报告

[category: provenance-dedup] 三、来源解析与去重键（同一篇文献必须只有一个键）

src/agentflow/dedup.py           [category: provenance-dedup] `normalize_doi` / `literature_keys` / `title_key`：来源标识的归一化 —— 归一化规则偏移即"同一篇文献两个主键"
src/agentflow/providers.py       [category: provenance-dedup] `normalize_doi` / `dedup_key_of` / `map_type_code`：provider 原始记录 → 统一候选键 —— 这里错则跨库同一篇文献无法合并

[category: schema-migration] 四、schema 迁移（存储布局与 ID 分配）

src/agentflow/schema.py          [category: schema-migration] `SCHEMA_VERSION` 与 `TABLES`：表结构与版本号 —— 改它等于改磁盘格式契约
src/agentflow/store.py           [category: schema-migration] `LOCK_ORDER` / `rebuild` / `alloc_id` / `_atomic_write`：加锁顺序、事件重放、ID 分配、原子落盘 —— 四者任一错都是**数据毁灭级**

[category: eval-criteria] 五、评测口径的定义（一个数字是什么，由口径决定）

src/agentflow/schema.py          [category: eval-criteria] `EVAL_REQUIRED_FIELDS` 与 `EvalResult`：必填口径字段与比率口径（0..1）—— 改它等于追溯性地改写历史报告里每个数字的含义

[category: release-deploy] 六、发布与部署脚本（发出去就收不回来）

src/agentflow/release_check.py   [category: release-deploy] 发布前检查入口（**登记时并不存在**：先登记路径，一旦有人在这里新建它，它会自动落入本清单而不是绕过门；截至本次登记仍未出现）
scripts/release_check.py         [category: release-deploy] 发布前的一键检查 `main` 与它跑的那八项：发布门本身 —— 改宽它等于让"发出去的东西"不再受检；另一种落位也一并登记，以免"换个目录就绕过"
tools/release_all.py             [category: release-deploy] 一键发布检查的**编排层** `main` / `build_steps` / `overall`：它调用并汇总全部门（含验收测试与论文复现），并决定"跳过的步骤记成 `unknown` 还是 `pass`"—— 那一条取舍就是"发布门能不能被 `--skip` 绕过"，改它等于改门的强度
tools/coverage_zero_test.py      [category: release-deploy] 发布门的两道子门之一（`release_all` 的 `coverage` 步）：`_classify` 按 AST 判据（写路径 / 判据决策 / 只读 / 呈现四档，`_CRITERIA` 里 1a–4c）逐函数分档，`_propagate_levels` 做传递闭包，`_EXONERATED` 是逐条登记的豁免表 —— 改它等于改"零直接测试"这个判据本身与风险分档口径，于是发布门 `release_all` 的 `coverage` 子门放行的东西换了口径而门照样亮绿（本处刻意不写步号：该步骤表实测 2026-09-27 12:19 +0800 为 `['release-check','acceptance','repro','role-specs','coverage','per-file']`（6 步），命令 `python -c "import sys,pathlib;sys.path.insert(0,'.');from tools.release_all import build_steps;print([s.key for s in build_steps(pathlib.Path('.').resolve())])"`；原写的"第 8 步"在该表里没有出处）
tools/run_each_test_file.py      [category: release-deploy] 发布门的两道子门之二（`release_all` 的 `per-file` 步）：`classify_pytest_result` 把 `exit=5`/`exit=0` 按汇总行拆成 `deselected` / `no_tests` / `all_skipped` / `all_xfail`，`audit_exemptions` 是"允许整文件被跳过/筛掉"的豁免面（上限 `MAX_EXEMPT_ALL_SKIPPED`）—— 改它等于改"哪些文件的绿灯算数、哪些只是没跑"，豁免一放宽就等于把文件从这条门里静默摘掉
pyproject.toml                   [category: release-deploy] `[project]` 与 `[build-system]`：包名、版本、依赖、构建后端 —— 这三个决定"发出去的到底是什么"，且版本号一旦发布无法撤回

[category: auth-audit] 七、权限与审计（谁能做什么，以及谁做过了什么）

src/agentflow/tools/__init__.py  [category: auth-audit] `ROLES` 的引入、`READ_ONLY_ROLES` 与 `SIDE_EFFECTS_WRITE`：只读角色（C/H）的权限面单一来源
src/agentflow/tools/base.py      [category: auth-audit] `for_role` 的结构性过滤（工具面：只读角色一律拿不到写工具）与 `call` / `_callable_for` 的调用期角色判据（可调用面）以及 `READONLY_CALL_EXCEPTIONS` 这张逐条登记的例外表（只读角色仍可调用的那几个落库代理只由它产生）三处共用同一个私有谓词 `_role_surface` —— 它们是同一件事的**实现**，与上面的**声明**分处两文件，必须同时人审；只读角色的权限面由这三处共同决定，改任意一处都是改权限（`P-14` 之后 `for_role` 只是这三处里的第一处）
src/agentflow/verify.py          [category: auth-audit] `verify_all` 的一致性审计：不变量检查的判据本身被改宽 ⇒ 审计从此永远"通过"
src/agentflow/interactions.py    [category: auth-audit] 跨智能体交互的冻结契约与它的闸门实现：`check_conflict` 是写入期一致性闸门（B 在事务内调，签名里不许有 `store`）、`adjudicate_contradiction` 是矛盾闭环的收敛点、`admit_search_request` / `admit_reprocess_request` 是 I7/I4 的准入配额闸门 —— 这里定的是"哪个角色调得到什么、哪些请求被放行"，并靠三态位（`checked` / `admitted`）保证"没查"与"查过了没问题"分得开；把闸门改宽或把三态折平，等于"不该能做的动作"变成"能做"，而测试照样全绿（注：**A–H 调用矩阵的权威定义不在这里**，在 `src/agentflow/capabilities.py` 的 `ALLOWED_EDGES`）
src/agentflow/specs/__init__.py    [category: auth-audit] `specs/` 包的收表入口：`builtin_specs` / `action_table` / `edges` / `write_sets` / `non_summonable` —— capabilities 的四张表与 agentspec 的注册表都从这里取 ⇒ 改它等于改「权限面怎么被读出来」
src/agentflow/specs/a.py    [category: auth-audit] 角色 A 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/b.py    [category: auth-audit] 角色 B 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/c.py    [category: auth-audit] 角色 C 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/d.py    [category: auth-audit] 角色 D 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/e.py    [category: auth-audit] 角色 E 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/f.py    [category: auth-audit] 角色 F 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/g.py    [category: auth-audit] 角色 G 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/h.py    [category: auth-audit] 角色 H 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/specs/m.py    [category: auth-audit] 角色 M 的声明真身（M3 起）：`ACTIONS`（动作表）与 `SPEC`（职责与门面 / 官能轻重 / 边 / 写集 / 实现类）—— capabilities 那四张表全部由它派生 ⇒ 改这里等于改权限面本身，而判据守的是「两层一致」，不是「这一改该不该由人批」
src/agentflow/agentspec.py    [category: auth-audit] 声明类型与声明词表：`ActionSpec`（动作声明的唯一类型）、`AgentSpec` / `AgentBrief`（一个 agent 的声明）、`AgentRegistry` / `builtin_registry`（装配面从这里读）、以及 `SIDE_EFFECTS` / `EFFECT` / `EXTERNAL` / `UNKNOWN_SIDE_EFFECT` 四个受控词表 —— 词表加一个取值就是放宽一整根轴（`tools/base.py` 与它是逐字对齐的两份），而 `assert_capabilities` 的交叉断言只保证'两处一致'，不保证'这次放宽该不该发生'
src/agentflow/capabilities.py    [category: auth-audit] A–H 调用矩阵的**权威定义**：`ALLOWED_EDGES` / `CAPABILITIES` / `WRITE_SETS` / `NON_SUMMONABLE` —— interactions.py 的理由串自己承认「矩阵真身在这里」，而它此前**不在清单里** ⇒ 改「哪个角色调得到什么」不需要任何人审（P-18 / H-4 的同族）；verify.py 的一致性审计把它当真身读 ⇒ 改它等于改权限面本身
.noai-approvals.json             [category: auth-audit] 批准台账：`sha256` 钉住「被批准的那一版」、`reviewers` 记「谁逐行走查过」—— 改它等于改审计记录本身；台账**不能批准自己**（理由码 `ledger_self_approval`），且 `--baseline` 永远不写 `reviewers`（登记 ≠ 批准）
.noai-paths                      [category: auth-audit] 禁改区清单本体：它决定哪些路径受保护 —— 改它等于改「保护范围」本身。它必须自己也在清单里，否则「放宽门」这件事不需要任何人审；一致性检查只保证两处一致，不保证两处都没被动过
AGENTS.md                        [category: auth-audit] 上面那份清单在 `AGENTS.md` 里的副本（机器按位比对两处）：副本若能随便改，「两处一致」就失去了意义 —— 同一份清单的两个落位必须同时受保护
scripts/noai_gate.py             [category: auth-audit] 判据本体：`REQUIRED_APPROVALS_ON_HIT` / `MIN_INDEPENDENT_AUDITORS` / `MIN_DISTINCT_DIMENSIONS` / `LEDGER_NAME` / `AUDIT_RECEIPT_NAME` 与批准台账的读写 —— 改它等于改「一个批准算不算数」；它此前不在自己的清单里，于是「放宽门」这件事不需要任何人审（`H-4`）
scripts/lint_rules.py            [category: auth-audit] 判据本体：`Finding` / `LintReport` 与 `rule_R001_bare_except_pass` … `rule_R011_dead_vocab` 各条规则 —— 改它等于改「哪一类形态算缺陷」；同样此前不在清单里（`H-4`）
tools/vocab_census.py            [category: auth-audit] lint 判据 R011（受控词表死取值）的**实现本体**：`census` 扫出全部词表定义点与产出点、`RESERVED_VALUES` 是"已登记为预留"的唯一落点、`MIN_VOCABS` / `MIN_PRODUCER_LINES` 是反真空下限（扫不到就判 `unknown`）—— `rule_R011_dead_vocab` 直接加载本文件当判据用，改它等于改"哪个取值算死、哪个算已登记"，而 lint 报告与发布门的 lint 步会照着新口径继续亮绿
```

<!-- NOAI-MANIFEST:END -->

### 命中之后要做什么

1. **停**。不要"顺手改一下"。命中禁改区意味着这次改动**不属于你独自完成的范围**。
2. **由人编写，或人逐行走查**。两种形态都合规：
   - 人**编写**：人写这段实现，你只做外围（测试、调用方、文档）；
   - 人**逐行走查**：你写，但人**逐行**看过并留下结论（不是"扫一眼"、不是"看起来没问题"）。
3. **需要 2 名 reviewer 批准**（FC-27 的 `= 2`，见 `scripts/noai_gate.py` 里的
   `REQUIRED_APPROVALS_ON_HIT`）。为什么是 2 而不是 1：
   1 名 reviewer 与"作者自己再看一遍"在**结构上**无法区分；2 名才有互相独立的复核。
4. **门是机器执行的，不是靠自觉。** 你不需要"记得"这条约束：
   跑 `python scripts/noai_gate.py --git`（或 `--paths <改动的文件>`），
   命中就会以**退出码 1** 结束并要求 `required_approvals=2`。
   CI 以这个退出码为判据 —— "没报错"绝不等于"没问题"。

### 退出码（为什么这个门有退出码）

```text
0 = clean          查过了，未命中禁改区
1 = requires_human 查过了，命中禁改区 ⇒ 2 名 reviewer 批准
2 = unknown        **没查成**（清单读不到 / 不在 git 仓库 / 没给改动集）
```

`unknown` **绝不是** `clean`。三态纪律：把"没检查"与"检查过了没问题"折叠成同一个
"通过"，是本项目反复踩过的坑。`17-正式文稿体例（参考投影度量论）.md:675-676`
记录了成熟项目的同类教训：**"多数脚本不设退出码，于是『未报错』被误读为『无问题』"**。

### `--git` 的覆盖范围（不给基线时它看不见已提交的改动）

`--git` 取的是三者的并集：`--since <ref>..HEAD` 的**已提交**改动、未提交改动、
以及**未跟踪的新文件**。三条都是踩过的坑：

- 只用 `git diff --name-only HEAD` 时，把禁改区改动**提交**掉就再也看不见（实测：不提交 ⇒
  `requires_human`(1)，提交后 ⇒ `clean`(0)）；
- `git diff` 只报已跟踪文件，所以在清单登记过的路径上**新建**文件同样看不见
  —— 而 `src/agentflow/release_check.py` 的登记理由恰恰是"一旦有人新建它会自动落入清单"。

所以：**不给 `--since` 时，改动集为空会判 `unknown`(2)，不是 `clean`**。
CI 必须给基线：`python scripts/noai_gate.py --git --since <ref>`。

本仓库的 `.git` 在**上一级**（交付物在 `agentflow/` 子目录里），因此 `git diff --name-only`
给出的是**仓库根相对**路径（形如 `agentflow/src/...`）。门的路径匹配会同时试
"仓库根相对 / 项目根相对 / 裸文件名"三种候选，有负控用例守着
（`tests/test_noai_gate.py::test_agentflow_prefixed_paths_still_hit`）。
