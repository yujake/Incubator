# DEVELOPMENT-APPENDIX —— agentflow 开发规范（历史面）

> ⚠️ **本文不构成判据。** 它只回答"当时是什么样、为什么会这样"。
> 判据在 [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md)（规范面）；
> 入口在 [`../DEVELOPMENT.md`](../DEVELOPMENT.md)。
> 每节首行标 `[附录·历史]`；**这里出现的每一个数字都是当时读数**，
> 除明确写出复跑命令者外，**本轮一律未复跑**（照 §1.1，它们只能当"当时发生了什么"读）。
>
> **为什么保留失败的历史**：只留绿灯的历史，等于把门的存在证据也删掉了。
> 本项目最核心的教训是*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"* ——
> 与之对称的一条是：**一份只记"现在是好的"的文档，读不出"这些门真的会响"**。
> 所以 S1/S2 那两次不绿的取样刻意留着，并且**不许把它们读成当前值**。
>
> **读法（三条）**：
> 1. 要**当前值** ⇒ 去 `DEVELOPMENT-SPEC.md` §0.2 的 `LIVE-READINGS` 块（那里每条读数都有复跑命令）；
> 2. 要**当前规矩** ⇒ 去 SPEC 的 §5（纪律）/ §6（DoD）/ §8（禁止模式）；
> 3. 本文的每一行都带"当时/观测/原写"这类记号 —— **那是刻意的**，它让这些句子退出对账
>    （判据逐行豁免历史读数；把记号删掉，历史就会静默变成"当前值"）。

---

## A1 [附录·历史] 本仓库的状态快照：两次取样（S1 / S2）

⚠️ **本仓库在并行施工中**。SPEC 里的每一条读数都带**取样时刻**；本文记的是**取样本身**。

| 取样 | 时刻 | 当时的状态 |
|---|---|---|
| **S2（当时的最新一次）** | 2026-09-24 09:0x（那一轮收尾，最终实跑） | **全绿**：测试 `1273 passed / 0 failed / 8 deselected`（退出码 0，两次独立实跑一致）、8 个 agent 自检 **exit 0**、`cli verify` 0 错误 0 警告、linter `error 3 / warning 2 / info 14`、发布门 **`pass=6 fail=1 unknown=1`** |
| **S1（历史）** | 2026-09-24 早（本文初稿） | **不绿**：`10 failed, 957 passed`；`cli tools --role E` 被 argparse 拒绝（退出码 2）；`agent_g` 自检 exit 1；linter `error 20 / warning 34` |

> **为什么把 S1 那张过期表留在文档里**：它记录的是**"这些门真的会响"**的证据。
> 只留 S2，后来者无法判断这些门是"一直都在报绿"（那通常意味着门没接对）
> 还是"曾经报红、然后被修好了"。
>
> S1 那一次逐项是什么、当时的证据是什么（全量测试/Pytest 失败集中在
> `test_conductor.py` 的 `test_local_backend_rejects_unknown_params` 与
> `test_verify_tasks_detects_zombie_running_row`、`test_scheduler.py`、`test_policy.py`；
> 取样中途一次 `Interrupted: 1 error during collection` 是并行施工的半写文件
> ——`tools/trace_tools.py` 的 `SyntaxError: unmatched ')'`，已被同事修复；
> linter `error 20 / warning 34`；`cli tools --role E` 被 argparse 拒绝是因为
> `choices=["A","B","C","D"]` 写死了 4 个角色；`agent_g` 自检 exit 1 是因为
> `evidence_kind='proof'` 必须给 `verifier_subject_key` 这条新硬约束没被自检夹具覆盖）
> —— 这一节的原始表格已从规范面删除（它与上下文无关、且数字全是 S1 的），
> 保留下来的**只剩这段叙述**：它是"多 agent 并发写同一工作区"的实测代价。

---

## A2 [附录·历史] 当时已存在的文件（逐格实测，**本轮未复跑**）

> 这一节的价值不在清单本身（清单会漂），而在**每一格都记了"观测时刻 + 复算命令"** ——
> 那是 `G-32` 要求的形态。份数与清单**以 SPEC §4.1 的命令当次读为准**，
> 本文只留"当时量到的是什么样"。

| 位置 | 当时的实测 |
|---|---|
| `agentflow/`（仓库根） | `.noai-paths` `.noai-approvals.json` `AGENTS.md` `config.yaml` `DESIGN.md` `DESIGN-TOOLS.md` `DESIGN-INTERACTIONS.md` `DESIGN-ROLES.md` `DESIGN-CONDUCTOR.md` `pyproject.toml` `README.md` `DEVELOPMENT.md` `NOAI-REVIEW-REGISTER.md`（`README.md` 已于 2026-10-18 挪到仓库根 `D:\Incubator/README.md`） |
| `agentflow/src/agentflow/` | 包根一层 **79 个 `.py`** + **9 个角色包**（观测 2026-10-13：`paper_package` 整条退场后复算 ⇒ `(Get-ChildItem src/agentflow/*.py).Count` 与"目录数减去 `specs`/`tools`/`web`/`__pycache__`"）。同一批文件在 `agentflow/` 内部按少一层前缀的形式引用（`src/agentflow/gates.py`）。2026-10-13 那一趟：删 `paperbuild.py` / `renderanchor.py`（三维锚那一层），加 `papercompile.py` |
| `agentflow/src/agentflow/tools/` | **16 个文件** = 14 个 `*_tools.py` + `base.py` + `__init__.py`（观测 2026-10-04；`manuscript_tools.py` 是交接手稿的读面）。2026-09-30 更正：本节原先漏列 `conjecture_tools.py` 与 `conductor_tools.py` |
| `agentflow/scripts/` | 共 **6** 个 `.py`（观测 2026-10-05）：`__init__.py` `lint_rules.py` `manuscripts_query.py` `noai_gate.py` `release_check.py` `usage_ledger_audit.py` |
| `agentflow/docs/` | 共 **14** 个文件，且这一层没有非 `.md` 的文件（观测 2026-09-30） |
| `agentflow/tests/` | `test_*.py` 的**份数按命令当次读**（观测 2026-09-30 ⇒ 162）+ `conftest.py` + `demo_dataset_helper.py`。**全量实测是"区间 + 观测时刻"**：当时从 `draft/35` §12 转记的读数是 `3071 passed, 1 failed, 3 skipped, 1 xfailed`（观测 2026-09-30 23:52）—— 唯一那条失败是起子进程跑 `release_all` 的用例撞上 600s 上限 |
| 运行期数据 | `agentflow/data/`（份数按命令当次读；观测 2026-10-02 ⇒ 18 个 JSON；并表后 2026-10-10 ⇒ **16 张表 ⇒ 17 个 JSON**，`concepts.json` 已随表退役）、`agentflow/library/`、`agentflow/demo/`。注：**`D:\Incubator\agentflow` 自己不是 git 仓库**；`.git` 在**上一级** `D:\Incubator` |

**"预留并如实标注"清单**（当时点名要预留的那几项；这是**历史**，不是待办）：

| 项 | 当时的状态 |
|---|---|
| `policy.py` | **已存在**（`Policy` 四类上限 + `check` + `waves_of` + `assert_policy_complete`） |
| `conductor.py` | **已存在**（`Conductor` + `SummonResult` + `LocalBackend`/`SubagentBackend`） |
| `scheduler.py` | **已存在**（`run_waves` / `run_tasks` / `TaskCall` / `MemoryBudgetTracker`） |
| `cancellation.py` | **已存在**（`CancelToken` / `CancelReason` / `CANCEL_CODES` / `CancelRequested`） |
| `capabilities.py` | **已存在**（`CAPABILITIES` / `WRITE_SETS` / `ALLOWED_EDGES` + **导入期** `assert_capabilities()`） |
| `contextbudget.py` | **已存在**（`ContextBudget` / `prune` / `prune_tool_result` / `compact`） |
| `tokenmeter.py` | **已存在**（`TokenMeter.charge` 记账 + `guard` **开工前**守卫；**重试按次计费**；`tokens_for`/`usd_for` 供 `summon` 把 `tasks.tokens` 派生自台账） |
| `claimanatomy.py` | **已存在**（`CLAIM_FIELDS` 的字段数按命令当次读；**观测 2026-09-27 ⇒ 19**，而 `G3` 之前这里写的是 12）+ `validate_claim` 三态 + `validate_document_claims` + `consolidate_issues` + `revision_hash`；**它是断言解剖学的唯一判据来源**，`doc_tools.scan_claim` 已改为纯适配层转发 |
| `gates.py` | **已存在**（H 的 `G1–G15` 门引擎；`GATES` 声明表门号齐全、每门可单独查询；观测 2026-09-27 ⇒ 15；四态结论 `pass`/`fail`/`unknown`/`not_applicable`；`GateResult.__post_init__` **结构强制"零发现必须自证"**） |
| `.noai-paths` | **已存在**。三个数**不在这里写定值**：现值住 `docs/DEVELOPMENT-SPEC.md` §0.2 的 `LIVE-READINGS` 块（键 `noai_paths_glob` / `noai_paths_unique` / `noai_paths_categories`，由 `tests/test_release_all.py::test_development_md_manifest_and_pytest_counts_match_the_repo` 逐处对账）。本行只留历史：观测 2026-10-12 时是 **43** 条条目 / **40** 条唯一路径 / 7 个分组（批 R61 把 `tests/golden/*.json` 拆成逐文件四条 ⇒ 40/37 → 43/40；**冻结基线，不再更新**）。台账条目数 / 欠签 / `stale` 计数**都不写定值**（每签一个字就变） |
| `AGENTS.md` | **已存在**（含 `NOAI-MANIFEST` 区块，与 `.noai-paths` **逐条一致**，实测退出码 0） |
| `scripts/noai_gate.py` | **已存在**（退出码 0/1/2 三档，三个方向都跑过） |
| `scripts/release_check.py` | **已存在**（八项检查；docstring 自陈 `authored_by: AI agent，尚未经人逐行走查`、`required_approvals: 2（尚未取得）`） |
| `scripts/lint_rules.py` | **已存在**（当时 12 条规则 R001–R012，与 SPEC §8 的禁止模式清单一一对应；其中 R004/R006 已退休、编号保留） |

> ⚠️ **上面 `.noai-paths` 那一行的口径更正（历史）**：这一条**原写**"19 条条目 + 7 个分组"、
> 后又写"21 / 18"，**三个数各有各的口径**。
> **更正说明刻意另起一段**：把"原写 / 旧值"这类历史记号留在当前值那一行里，
> 会让**整行**退出对账（判据是**逐行**豁免的）⇒ 一条当前值声明因为句尾带了一句更正说明
> 而**静默漂**。这正是 `G3` 修掉的那个结构性漏口：
> **当前值那一句不许带历史标记**，历史记号的豁免面不许覆盖当前值那一行。

---

## A3 [附录·历史] S2 的实测状态表（2026-09-24 收尾；**任何一行都不许当当前值引用**）

> 本表刻意保留原值**（它证明这些门**曾经报过什么**）。
> 例如本表第 1 行是 `1497 passed`；此后它又被观测到 `2889 passed, 3 skipped, 8 deselected, 1 xfailed`
> （`python -m pytest -q -p no:cacheprovider`，观测 2026-09-29 16:0x）、
> `1925 passed` / `1956 passed, 1 skipped` / `2133 passed` 等多次 —— 这个数**每加一条用例就变**。

| # | 门 | 实测结果（**S2 = 2026-09-24**） | 证据 |
|---:|---|---|---|
| 1 | **全量测试** | `1497 passed, 8 deselected, 1 xfailed`；退出码 0。⚠️ 那 1 个 `xfail` **不是"跳过的测试"**：它是补测试时发现的真实 `src` 缺陷（`PROPOSALS.md` **G-8**，在禁改区）用 `xfail(strict=True)` 登记 —— **修好后会 XPASS ⇒ 测试失败 ⇒ 强迫人来删标记** | `python -m pytest -q` |
| 2 | **linter** | `[linter] error 0 / warning 0 / info 21`（**S2 当次读数**；此后 warning 一栏再没回到 0：观测 2026-09-29 12:5x ⇒ `warning 9`，2026-10-07 ⇒ `warning 15`） | `python scripts/lint_rules.py`（`--strict` 另跑） |
| 3 | **8 个 agent 自检** | **全部 exit 0**：`a 24/24`、`b 18/18`、`c 46/46`、`d`–`h` 均 `SELF-CHECK DONE` | `python -m agentflow.agent_x`（cwd=`src`） |
| 4 | **`cli verify` / `cli demo`**（`demo` 是**旧路径**：保留可达、唯一不需要模型 key 的端到端路径；主路径 = `run-agent`） | 校验 `通过 错误 0 / 警告 0`；演示 `演示成功。`；均退出码 0 | 见 A4 |
| 5 | **禁 AI 区门** | `--check-consistency` 退出码 0；`--paths src/agentflow/schema.py` ⇒ `requires_human(1)`；`--git` ⇒ **`unknown(2)`**（当时 `agentflow` 自己不是 git 仓库）；`--check-approvals`（hash 台账）：当时**一条都没签**（`reviewers` 全是空表）⇒ `requires_human(1)` | 见 A4 与 `NOAI-REVIEW-REGISTER.md` |
| 6 | **角色规格结构门**（`tools/verify_role_specs.py`） | `[ok]` 当时的结构 × 8 必备子节，退出码 0（当时的写法把节数写成了单个定值，`G3` 之后改成"按命令当次产出"） | `python tools/verify_role_specs.py` |
| 7 | **零测试覆盖分档**（`tools/coverage_zero_test.py`） | 等级 1/2 的零测试公开函数 **0**（从 53 降下来），退出码 0 | `python tools/coverage_zero_test.py` |

> ⚠️ **`error 3` 与 `warning 2` 都不影响规范面的内容，但影响"发布门能不能过"**：
> 发布门的第 5 项（linter）在 S2 **仍是 `fail`**（它要求 error = 0）。
> **任何人拿文档当判据时，都必须知道自己手上的仓库处在什么状态**：
> 规范是**应该怎么做**，不是**体检报告**。

---

## A4 [附录·历史] S2 的"可复现基线"（逐条实测，含退出码）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH='src'   # 只有跑 `python -m agentflow.*` / `python -c "...import agentflow..."` 才需要
```

> 这一段当时是 `LIVE-READINGS` 块的导语。**块已迁进 `DEVELOPMENT-SPEC.md` §0.2**
> （并扩了键：`cli tools` 的三个数与 Web 面的四个数）。这里只留**历史那一半**：
> 那批命令当时给出了什么。

| # | 命令 | 当时的输出 | 退出码 |
|---:|---|---|---:|
| 1 | `python -m agentflow.cli tools` | `工具总数：81（已装模块 13：…）`；`各角色工具数：{'A': 26, 'B': 21, 'C': 21, 'D': 40, 'E': 24, 'F': 35, 'G': 40, 'H': 27, 'V': 14, 'M': 18}`；泄漏 `{'C': [], 'H': [], 'V': []}`。⚠️ **这是"含 store 的完整装配"口径**，与 `build_registry(store=None)` 的口径是**两个口径**，不许互换 | **0** |
| 2 | `python -m agentflow.cli tools --role E` | 正常列出 E 的工具面（S1 时这里报 `invalid choice: 'E'` —— **已修**：`choices=list(S.ROLES)`） | **0** |
| 3 | `python -m agentflow.cli tools --role C` | 列出 `trace.concept` / `trace.literature` / `trace.relation` 等，**全部 `[read]`** | **0** |
| 4 | `python -m agentflow.cli verify` | `校验完成：通过  错误 0 / 警告 0` | **0** |
| 5 | `python -m agentflow.cli demo`（**旧路径**，保留可达） | `演示成功。` | **0** |
| 6 | 各角色自检 | A–H 八个全部 `SELF-CHECK DONE`（`c` 46/46；`a` 24/24；`b` 18/18）；**V** 打印 16 条 `[PASS]`、退出码 0（观测 2026-10-06） | **0** |
| 7 | `python -m agentflow.pipeline` / `python -m agentflow.llm`（**旧机制**：`pipeline` 的中间产物落盘实现 `_persist_report` 已退场 ⇒ 这一格只证明"自检能跑"，不再证明编排能落盘；主路径 = `run-agent`） | 均 `SELF-CHECK DONE` | **0** |
| 8 | `python -c "import sys;sys.path.insert(0,'src');import agentflow.capabilities"` | 无输出（能力表**导入期**自检通过） | **0** |
| 9 | `python scripts/noai_gate.py --check-consistency` | `一致：.noai-paths 与 AGENTS.md 的清单逐条相同` | **0** |
| 10 | `python scripts/noai_gate.py --paths src/agentflow/schema.py` | `[requires_human] required_approvals=2`（类别 `schema-migration` + `eval-criteria`） | **1** |
| 11 | `python scripts/noai_gate.py --git` | 建仓**之前**是 `[unknown] … Not a git repository`（**没查成，不是没问题**）。建仓**之后**（`.git` 在上一级 `D:\Incubator`）它看的是**伞仓库**的改动集。**口径（逐字）**：`--git` 取的并集是"`--since <ref>..HEAD` 已提交的 + 未提交的 + 未跟踪的新文件"；**不给 `--since` 时，若改动集为空就判 `unknown`（退出码 2）—— `unknown` 是"没查成"，它不是 `pass`**。CI 必须给基线：`python scripts/noai_gate.py --git --since <ref>` | **0/1/2** |
| 12 | `python scripts/lint_rules.py` | 当次数见 SPEC §0.2 的 `LIVE-READINGS`（当时观测 ⇒ `error 0 / warning 15 / info 49`；`--strict` ⇒ `error 0 / warning 51 / info 46`）。**本节不抄定值**：这个数由块与判据对账，而抄进正文的副本没有人对账（它已经因此错过两回：`info 25` → `30` → `37` → `47`） | 见当次运行 |
| 13 | `python -m pytest -q` | **区间 + 观测时刻**：`4 failed, 2130 passed, 3 skipped, 8 deselected, 1 xfailed in 497.16s`（观测 22:28:48→22:37:05）/ `1 failed, 2133 passed, … in 417.13s`（观测 22:38:29→22:45:26）。两次的失败都不是本批文件的（并行批次正在改 `schema.py` 的过程记录号校验；另一条当时正被并行写入，随后单跑 `11 passed`） | **1** |
| 14 | `python tools/verify_role_specs.py` | `[ok]` + `[OK ]` 逐角色，每行带"工具条数 [`N`] 现场 `N`"（这道门**自己真装配一次注册表**再对账）+ `[OK ] §M 主控（Conductor） 子节 … 工具条数 [6, 12, 18]`（M 的编排面；观测 2026-10-06 ⇒ 逐角色条数 `A 26 / B 21 / C 21 / D 40 / E 24 / F 35 / G 40 / H 27 / V 14`）。**行号刻意不抄** | **0** |

**工具面 census（`cli tools` 当时的完整输出）**：

```
工具总数 81 / 已装模块 13 / 各角色 {'A':26,'B':21,'C':21,'D':40,'E':24,'F':35,'G':40,'H':27,'V':14,'M':18}
只读角色写工具泄漏 {'C': [], 'H': [], 'V': []}
# 三个数都由 `python -m agentflow.cli tools` 当次产出（观测 2026-10-06；
# M 拿到 18 件 = 编排面 12 + 文件面白名单 6（`draft/37` §38 + §57））；
# 「加一个工具 / 加一个模块」就变 ⇒ 这里不写死，复跑那条命令即可。
# （2026-10-06 更正：本块原先记的是 `75 / A24 B19 C19 D38 E22 F33 G38 H25 M17`（观测 2026-10-02）；
#   更早记的是 `73 / A23 B18 C19 D37 E21 F32 G37 H25 M10` 与 `63 / A20 B18 C17 D37 E21 F32 G32 H22 M8`。）
```

> ⚠️ **上面那个泄漏行今天已不成立**：`H` 后来有了一组**已逐条登记**的落库代理
> （`review.report` / `review.review_document` / `review.verify_fixes` /
> `review.record_finding`），`C` 也有一件（`analysis.register_report`），全部由
> `tools/base.py` 的 `READONLY_CALL_EXCEPTIONS` 产生（2026-10-21 实测，复跑
> `python -m agentflow.cli tools`，读「只读角色写工具泄漏」那一行 ⇒ `{'C': ['analysis.register_report'],
> 'H': ['review.review_document', 'review.verify_fixes', 'review.report',
> 'review.record_finding'], 'V': []}`）⇒ 现在的输出**不是空表**。
> 这一条正是"读数会漂"的活标本：**"空 = 正常"这个读法本身也是要过期的**。

> **"上表里只有两条非零退出码"这句话本身不是好消息** —— 退 1 与退 2 是
> **设计出来给 CI 用的**（`requires_human` / `unknown`）。若把它们也改成 0，
> 那才是把门拆了。

---

## A5 [附录·历史] 发布门的两次历史判定（S2 与 2026-09-26 重测）

### [附录·历史] A5.1 S2 的逐项状态（2026-09-24）

```powershell
python tools\release_all.py                            # ★ 一键（当时是六步）
python scripts/release_check.py                       # 只跑那八项
python scripts/release_check.py --changed <文件…>      # 同时判禁改区命中
```

| 项 | S2 状态（**逐行都是 S2 当次读数，不许当当前值引用**） | 证据 |
|---|---|---|
| 1 全量测试 | **pass**（S2 当次：`1497 passed / 0 failed / 8 deselected / 1 xfailed`，退出码 0） | A3 第 1 条 |
| 2 模块自检 | **pass**（S2 当次：8 个 agent 全部 exit 0） | A4 第 6 条 |
| 3 工具普查 | **pass**（S2 当次：55 / 泄漏 0） | A4 第 1 条 |
| 4 全库校验 | **pass**（S2 当次：error 0 / warning 0） | A4 第 4 条 |
| 5 linter | **pass**（S2 当次：`error 0`）—— 最后 3 条 R001 都补了**具体**理由 | A3 第 2 条 |
| 6 禁 AI 区门 | **unknown**（S2 当次：本目录**不是 git 仓库** ⇒ `--git` 恒为退出码 2；台账已建立但尚未接线：第 6 项走的仍是 `--paths`，命中即 `fail`） | A4 第 11 条 |
| 7 契约版本 | **pass**（S2 当次：`cli verify` 与 `agentflow.CONTRACT_VERSION` 已对齐） | A4 第 4 条 |
| 8 源码树可导入 | **pass**（S2 当次：`python -c "...import agentflow.capabilities"` 退出码 0） | A4 第 8 条 |

**最终一次 `release_check.py` 的总判定（S2）：`pass=7 fail=0 unknown=1`**（退出码 **2**）。

### [附录·历史] A5.2 重测：**当时的真实判定是 `FAIL`**（不是"基本全绿"，`G-28`）

⚠️ **上表是 S2 的观测，它在重测那一刻已不成立**。
**重测（观测 2026-09-26T04:54:45→04:59:39，无并发）**：

```powershell
python tools/release_all.py --since 4293989 --only release-check --json-out D:\Incubator\temp\b6-release-check.json
```

```text
[run  ] release-check  全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入（预计 ~300s）
[fail  ] release-check  exit=1 293.0s
         发布检查总判定：FAIL    pass=6 fail=2 unknown=0
[skip ] acceptance / repro / role-specs / coverage / per-file
一键发布检查总判定：FAIL    pass=0 fail=1 unknown=5   # 退出码 1
```

**逐项（8 项）**：`tests` **fail** / `selftests` pass / `tools` pass / `verify` pass /
`lint` **pass**（`error 0`）/ `noai` **fail** / `contract` pass / `imports` pass。

| 红项 | 性质 | 逐字判据 |
|---|---|---|
| `noai` | ⭐ **制度要求，不是代码坏** | **`release-check` 那一项的红是"禁改区命中待 2 名 reviewer 签字"** —— `consistency_exit=0` 而 `gate_exit=1`，理由逐字：`命中禁改区 ⇒ 需人编写或人逐行走查 + 2 名 reviewer 批准（FC-27）`。**这一格在人真的签出那些名字之前永远是红的**，与代码质量无关 |
| `tests` | **真红，且是"并发/顺序态"** | `2 failed, 1948 passed, 1 skipped, 8 deselected, 1 xfailed in 277.76s`；两条失败单跑都绿（`3 passed` / `1 passed`）。⚠️ **同一棵树在无并发的另一次全量里是 `1925 passed, 0 failed`**（观测 04:43:55→04:48:40） |

> ⚠️ **另一条当时不成立的旧陈述**："第 6 项在'不给 `--changed`'时**必须**报 `unknown`"
> —— **已修**（`P-25`）：`release_all` 现在会把改动集传进去（`--since <ref>`），
> 所以第 6 项**能**给出 `pass` 或 `fail`，不再是结构性 `unknown`。

**`tools/release_all.py` 的一次完整实跑（S2，当时是六步）**：

```text
[unknown] release-check   ← pass=7 fail=0 unknown=1（结构性 unknown）
[pass   ] acceptance      通过 10 / 失败 0 / 未执行 0
[pass   ] repro           ALL CHECKS PASS
[pass   ] role-specs      逐角色节结构 × 必备子节
[pass   ] coverage        等级 ≤ 2 的零测试函数 0
一键发布检查总判定：UNKNOWN    pass=4 fail=0 unknown=1     # 退出码 2
```

> **那个 `unknown` 是当时结构性的、不可能消除的**：第 6 项在"不给 `--changed`"时**必须**报
> `unknown`。所以**在那个环境里"发布门全绿"永远不可能发生** —— 能到达的最好状态就是
> "如实 unknown 一项"。**把它读成"全绿"就是本项目反复踩过的那个坑。**
>
> ⚠️ **今天的步骤表是七步**（多了一步 `frontend`，裁定 G2）：步骤 key 与顺序以
> `build_steps` 当次产出为准（命令见 SPEC §10.1）。上面那个"六步"是**当时**的事实。

---

## A6 [附录·历史] FC-01…FC-27 覆盖矩阵（2026-09-26 的快照）

> **状态口径的三档定义在 SPEC §11**（已落地 / 部分 / 未落地；`未核实` 另列）。
> 本节是**那一次快照**的逐条落地位置与判据。**它不构成判据** ——
> 要当前值就照每行的判据当场跑。每一行都注明了"当时查了什么"。

| FC | 约束（简写） | 落地位置 | 可判定判据 | 当时状态 |
|---|---|---|---|---|
| **FC-01** | 三态而非布尔 + 受控 `reason` | `schema` 的 `REFUSAL_REASONS` / `TASK_OUTCOMES` / `DOWNLOAD_STATUSES` / `SEARCH_OUTCOMES` / `NEGATION_KINDS`；`checked` 位（`SummonResult`）；`store.stats()` 三分档；`agent_b` 的三组计数 | 引文三态、`outcome` 词表、`checked` 三态均有测试；**但"禁止 `if not x.verified:`"无静态 lint 规则** | **部分**（缺静态检查） |
| **FC-02** | 每个产出带可追溯代号链（双向） | `origin` 字段、`related_*_ids`、`verify` 的 `dangling_*` 检查集 | `tests/test_verify.py` + `test_verify_extended.py`；**通用正/反向链一致性断言仍缺**（只有 literature↔request 双向） | **部分** |
| **FC-03** | 跨模块字符串集中定义 + 装配期断言 | `schema.ROLES`（唯一）；`tools/__init__.py` 的 `from ..schema import ROLES`；`bad_roles` 断言；`assert_capabilities()`；linter 的 R005 | `tools.ROLES is schema.ROLES` ⇒ **实测 `True`**；`noai_gate --check-consistency` ⇒ 退出码 0；当时 R005 仍报 1 处 | **已落地**（有残留 warn） |
| **FC-04** | 受控词表在 schema 强制 + 交叉检查 | `schema.py` 各 `validate()`；`verify.py` 的 cross-check（`lit_not_processed` / `stale_waiting` / `stale_group_key` / `mismatch_without_evidence` …）；`Task`/`UsageEntry`/`EvalResult` 三套 | `tests/test_schema.py`；`tests/test_fc05_contract.py` 的大量交叉检查 | **已落地** |
| **FC-05** | 顺序与集合分离（保序字段成对） | `schema.ARRAY_FIELD_KINDS` + `check_array_invariants`；`verify.undeclared_array_field`（error）；`tests/test_fc05_contract.py` | `test_every_array_field_is_declared` / `test_seq_field_is_not_forced_sorted_by_the_central_check` / `test_relation_chain_preserves_order_round_trip` / `test_relation_chain_must_be_a_subset_of_related_relation_ids` | **已落地** |
| **FC-06** | 角色即权限面 + 预期工具清单 + 负向权限测试 | `for_role` + 结构性剥离；`tests/test_tools_readonly_roles.py`；`capabilities.WRITE_SETS` + `assert_capabilities` 第 4 条 | 负向权限测试存在；**`expectations.yaml` 实测 0 命中** ⇒ 仍缺"每角色预期工具名清单，缺失即 fail-closed" | **部分** |
| **FC-07** | 工具声明完整，`side_effect`/`roles` 一等公民 | `ToolSpec` 六件套（实测缺字段 0）；`ToolSpec.needs_approval`（两根轴推导）；`capabilities.SIDE_EFFECTS` **交叉断言**；只读不变量测试 | `tests/test_tools_base.py`；`agent_c` 自检"I1 服务面只读：三张知识表逐字节不变"；**但** `side_effect` 与**真实行为**当时有 ≥7 处不一致 | **部分**（声明层已落地，行为一致性靠 R010） |
| **FC-08** | 无工具/未接线必须显式失败 | `ToolResult.fail(kind=...)`；`not_wired`（多份实现）；`conductor.NotWiredError` ⇒ `refused/not_wired`；`ocr` 的 `no_backend`；`search.dedup_check` 的 `no_store` | 未接线返回失败而非空；**但** `search_tools.py` 与 `trace_tools.py` 两处当时仍是反例 | **部分** |
| **FC-09** | 每个验证门必须配负控 | 各测试文件里的负控（`agent_h` 三类 + 落库级；`agent_c` 的 `structural_duplicates` 负控；引文篡改负控）；`release_check.py` 第 6 项要求 gate 的负控 | 各门均有"注入坏数据必须报错"用例；`tests/test_noai_gate.py` 当时已存在（是否含负控当时**未核实**）；**无独立负控套件目录** | **部分** |
| **FC-10** | 验证结果三分档计数，禁止单一通过率 | `store.stats()` 的三栏；`ARunResult` 的 `verified/failed/unknown`；`agent_b` 的三组；`SummonResult.checked` 三态；`Conductor.stats()` 的 `by_outcome` / `refusal_reasons` / `unknown_outcome` | 三分档有输出；**但 `verify` 本身只有 error/warning 两级**（无 `unknown` 档） | **部分** |
| **FC-11** | 校验器与写入方共享同一配置来源 | `cli.py` 的 `cmd_verify`（**显式从 `config.yaml` 的 `agent_b` 段取**，注释逐字解释假报警）；`schema` 常量共用 | "改配置后写边缘样本，复核**不报错**"；**`QuotePolicy` 实测 0 命中** ⇒ 参数仍是散装的 | **部分** |
| **FC-12** | 可重建存储的信息量守恒 | `store.rebuild`（`backup=True`）；`tests/test_rebuild.py` | 诊断字段守恒 / 幂等 / 坏事件不炸；⚠️ **是否覆盖 `tasks` 表当时未核实** | **已落地**（覆盖范围未核实） |
| **FC-13** | 告警分级 + 已知缺陷可降级 | `Issue(level, table, id, code, message)`；`FINDING_LEVELS`；`review_tools.py` 的依赖分级；`noai_gate` / `release_check` 的三档 | 实测：`external_unavailable`=warning / `dangling`=error；`agent_h` 自检逐字验证了这条分级 | **已落地** |
| **FC-14** | LLM 产出必须回验 + 存回原文切片 | `quoteverify.py`；`agent_b` 的逐字回验；`llm.py` 的 `_ground_relations` / `_locate_verbatim` | `llm.py` 自检实测："幻觉引文被剔除且计数正确: True"；**无 API key ⇒ LLM 路径未端到端跑过** | **部分**（未端到端） |
| **FC-15** | 幻觉与"数据缺失"可归因分离 | reason 细分：`quote_not_found` / `empty_quote` / `no_text_layer` / `not_found_page_unknown` / `reextract_failed` / `quote_state_changed` | 各类失败有独立 reason 与独立计数 | **已落地** |
| **FC-16** | 确定性的部分绝不交给 LLM | C **无一处依赖 LLM**；`score_breakdown`；`llm=None` 默认；`agent_d` 的"置信度不许拔高" | `agent_d` 自检第 [10] 项实测："确定性置信度=medium；LLM 声称=high；强制后=medium" | **已落地** |
| **FC-17** | 上下文预算：压缩 / 剪枝 / spill | `contextbudget.py`：`ContextBudget` / `prune` / `prune_tool_result` / `compact` / `_MARKER_FMT` / `spill_dir`；装配侧 `ToolRegistry.default_budget` / `default_spill_root` + `build_registry(context_budget=…)` | `tests/test_fc17_wiring.py`（含"剪枝"与"落盘"两条断言）、`tests/test_context_budget.py` | **已落地**。⚠️ **这一条当时自相矛盾过**（`G-16`）：主矩阵写"部分"而另一表写"✅ 已落地" ⇒ 以判据为事实，**一条 FC 只保留一个状态** |
| **FC-18** | 三维预算 + 深度上限同时存在 | `attack_tools.DEFAULT_BUDGET` 四类键 + `check_budget`/`can_round`/`can_derive`；`schema.AttackPlan.budget` 缺即抛；`policy.Policy` 四类上限 + `validate()` + `assert_policy_complete` | `tests/test_agent_f.py`；`agent_f` 自检逐字验证了 `budget=None ⇒ checked=False` | **已落地**（当时评"最强的一条"） |
| **FC-19** | token 预算是硬约束，重试也计入 | `policy.Policy.token_budget` / `usd_budget`；`cancellation.CancelToken.token_budget` + `consume_tokens`；`scheduler.MemoryBudgetTracker`；`tokenmeter.TokenMeter`（**唯一的 `usage_ledger` 写入方**）；`conductor` 的开工前守卫；`schema.UsageEntry` + `usage_ledger` 表 + `attempts` | `tests/test_tokenmeter.py` 等；`conductor` 的双重预算（本次调用 ∧ 全局 `Policy`）；`tasks.tokens/usd` **由台账 `tokens_for()` 抄回** | **已落地（召唤级）**。⚠️ 同一处曾自相矛盾（`G-16`）；**仍未接的一小块**是各 agent `_call` 的逐次尝试细账（改的是"打几折"而不是"落没落地"） |
| **FC-20** | 取消：协作式 + 共享 signal + 事件配对 + first-wins | `cancellation.py`：`CancelToken`（first-wins）/ `CANCEL_CODES` / `CancelRequested`；`conductor` 的 `cancel` / `cancel_inflight` / `dispose` / `finish` 幂等 / `_signal_stop` | `dispose()` 的 docstring 逐字落地三条纪律；`schema.Task.validate` 的"pending/running 却已有 ended_at ⇒ 拒" | **已落地** |
| **FC-21** | 部分失败语义：子任务可降级，整体绝不谎报 | `AgentF._deploy_e` 降级 `blocked` + `blocked_reason` 并继续；`schema.AttackPlan` 的 `stalled` 必须写 `best_partial`（`verify.stalled_without_partial`，error） | `tests/test_agent_f.py`；自检实测 `stalled` + `best_partial` 非空 + 不可重入；**`run_best_effort` / `run_all_or_nothing` 实测 0 命中** ⇒ 无两种显式 API | **部分** |
| **FC-22** | 数值结果必须标注"仅为交叉验证" | `schema.EVIDENCE_KINDS` + `Experiment.validate`（五条硬约束，含 `verifier_subject_key`）；E 的降级；H 的 `overclaim`；`verify` 的三条 error 级检查；`CROSS_CHECK_DISCLAIMER` 自动附加 | `tests/test_agent_e.py`；`agent_e` / `agent_f` / `agent_h` 自检均有 FC-22 断言 | **已落地（当时评"最强"）** |
| **FC-23** | 外部定理显式标记依赖 + 依赖集可闭合检查 | `dependencies` 表 + `DEP_KINDS`/`DEP_STATUSES`；`doc.register_dependency`（`closed` 时**真去核**）；`verify.dangling_dep` / `dangling_dep_external` / `closed_dep_on_inconclusive_experiment` / `proof_claim_with_unclosed_dependency`；`Relation.supporting_lit_ids`（实测 7 处命中） | `tests/test_agent_g.py`；`tests/test_fc05_contract.py` 的 `test_document_can_cite_an_eval_result` | **已落地**（并推翻了旧文档里"一条关系只能引一篇文献"的缺口陈述） |
| **FC-24** | 基准口径是必填字段 | `schema.EVAL_REQUIRED_FIELDS` + `EvalResult`（`validate()` 缺任一即抛、`value` 必须是 0..1 比率）；`verify.eval_duplicate_conflicting` / `unknown_citation_kind` | `tests/test_fc05_contract.py`：`test_eval_requires_every_scope_field` / `test_eval_value_must_be_a_ratio` / `test_conflicting_duplicate_eval_is_an_error` / `test_same_value_duplicate_eval_is_clean` | **已落地**（旧文档标"未落地"的陈述已过期） |
| **FC-25** | "未证明/已证否/未搜索"三分 | `schema.NEGATION_KINDS` 四值；`Experiment.negation_kind`；`cold` 报告把 `degree==0` 单列"完全孤立"；`SummonResult` 的 `refused`/`no_result`/`not_applicable` 三分 | `tests/test_agent_e.py`；`agent_e` 自检第 [7] 项逐字："'查了没有' 与 '没查' 的 reason 不同" | **已落地** |
| **FC-26** | 每个"缺口/结论"必须可核实判据 + 否决项 | D 的三条判据 `a_no_keyword_hit` / `b_low_degree_unverified` / 矛盾；`gaps` 的 **`veto` 与 `score` 分离** | `tests/test_agent_c.py` / `test_agent_d.py`；`agent_d` 自检实测了 `判据=['a_no_keyword_hit']` 与 `['c_contradiction']` | **已落地** |
| **FC-27** | 禁 AI 区必须显式列出 + 独立准入门槛 | `.noai-paths` + `AGENTS.md` 的 `NOAI-MANIFEST` 区块 + `scripts/noai_gate.py`（`REQUIRED_APPROVALS_ON_HIT = 2`，退出码 0/1/2）；`tests/test_noai_gate.py`；`release_check.py` 第 6 项 | ① 两处**逐条一致**（实测退出码 0）；② 命中要求 2 批准（实测 `--paths schema.py` → 退出码 1）；③ 负控用例**在** `tests/test_noai_gate.py` 里 | **已落地**。⚠️ 发布门上它当时**仍报红**，原因是"禁改区命中待 2 名 reviewer 签字"（制度要求），不是代码坏 |

### [附录·历史] A6.1 未落地 / 部分落地的完整清单（当时）

> ⚠️ 本节曾有一处**自相矛盾**（`G-16` 的实体）：**FC-17** 与 **FC-19** 在主矩阵里是
> "部分 / 未落地"，而在同一份文件的下表里却是"✅ 已落地" —— 同一条 FC 有两个互斥状态。
> 处置：**判据优先，取"能被命令复现的那一个"**，两条都从"部分"表里删除。

**完全未落地（当时）：无。**

**部分落地（当时 9 条）**：

| FC | 缺的那一块 | 判据 | 当时状态 |
|---|---|---|---|
| FC-01 | 无静态检查禁止"把 `None` 与 `False` 合并"的写法 | 规则表里没有这条 | **仍未关**（R002 只覆盖"`is None`→空容器"这一种形态） |
| FC-02 | 只有 literature↔request 双向；**缺通用正/反向链一致性断言** | 做通用版需要给每个外键字段登记"反向字段名" | **仍未关** |
| FC-06 | 缺每角色的**预期工具名清单** ⇒ `roles` 写错仍可能静默少工具 | 需要一个"基线快照"文件 | **部分关闭**：`agent_d.validate_tool_roles` + 负控已覆盖 D；E/F 见 `PROPOSALS.md` **G-1** |
| FC-07 | `side_effect` 与**真实行为**不一致；R006 已退休（判据面在 R010） | 需要"执行进程"这一档或人工裁决 | **仍未关**（两轴已如实声明；R010 逐工具判。`ocr.run` 那一条后来**降级为 `info`** —— 复核确认"声明与代码不符"不成立） |
| FC-08 | 静默返空 | R002 报 warning | **仍未关**（两个观测都保留：S2 曾报 2 条，之后 R002 一轮 0 条 —— **不是矛盾，是不同时刻**） |
| FC-09 | 负控散在各测试文件；**无独立负控套件目录** | 命名约定 | **已接受**（`test_*` 内的 `*_negative_control_*` 命名已成约定；`tests/negative_controls/` 不做） |
| FC-10 | `verify` 本身只有 error/warning 两级，**无 `unknown` 档** | `VerifyReport` 需要第三个计数 | **部分关闭**：`release_check` / `noai_gate` 有第三档；`verify` 本身仍两级 |
| FC-11 | 无 `QuotePolicy` 统一配置对象 | `verify_all` 需要强制传 policy | **仍未关** |
| FC-14 | LLM 回验路径**未端到端跑过**（无 API key） | 需要真实 provider | **仍未关**（环境限制，如实登记） |
| FC-21 | 无 `run_best_effort` / `run_all_or_nothing` 两种显式 API | 需把 F 内部的降级语义提升为 API 契约 | **仍未关** |
| FC-27 | 禁 AI 区门 | — | ✅ **已落地且可执行**：清单两处逐条一致 + hash 台账 + 三档退出码；**批准仍需人**。⚠️ 它在发布门上仍然报红，原因是制度要求（见上表） |

> ⚠️ **与 `draft/13` §7.1 的差异（重要）**：`draft/13` 那份矩阵是对 `test/test1/abflow` 做的，
> 列了"完全未落地 6 条"（FC-05 / FC-17 / FC-19 / FC-20 / FC-24 / FC-27）。
> **在 `agentflow` 上，6 条全部落地**（FC-05 的 `ARRAY_FIELD_KINDS` + `chain` 保序契约测试；
> FC-17 的 `test_fc17_wiring.py`；FC-19 的 `tokenmeter.py` + `conductor` 开工前守卫；
> FC-20 的 `cancellation.py` + `dispose` 幂等 + `Task` 状态机 first-wins；
> FC-24 的 `EvalResult` + 渲染层 `number_without_eval_scope` 门；FC-27 见上）。
> **凡引用 `draft/13` §7.1 的地方都必须重新核对**（这正是 SPEC §3.4 那条口径警告的实例）。

### [附录·历史] A6.2 当时**没能核实**的条目（逐条说明当时查了什么）

| # | 未核实项 | 当时查了什么 | 当时的结论 |
|---:|---|---|---|
| 1 | R002 的具体命中 | 取到逐条明细 | ✅ **已关闭**：2 条，均已有理由 |
| 2 | FC-17 的剪枝测试是否存在 | 实测 `tests/test_fc17_wiring.py` + `tests/test_context_budget.py` | ✅ **已关闭** |
| 3 | FC-27 的负控用例 | 实测 `tests/test_noai_gate.py` 当时 51 例，含"台账缺失⇒unknown""hash 漂移⇒requires_human""台账自指"等负控 | ✅ **已关闭** |
| 4 | `tests/test_rebuild.py` 是否覆盖 `tasks` 表 | 有 `test_i9_tasks_snapshot_rebuilds_byte_identical`（逐字节重建） | ✅ **已关闭** |
| 5 | `usage_ledger` 是否有写入方 | 本条原写"**仍是零写入方**"（依据是一条 grep 零命中）。**那条 grep 的口径是错的**：写入方**不在 `agent_*.py` 里**，所以"零命中"只证明"不在那几个文件里" | ✅ **已关闭（`G-31`）**：**唯一的写入方是 `tokenmeter.TokenMeter.charge`**（`charge_once` 是幂等版）；模型调用那条路上游是 `modelcost.charge_reply`（`runflow.py` 调它）。权威账在 `usage_ledger`，`tasks.tokens/usd` 是**从它派生**的 |
| 6 | 契约版本一致性（发布门第 7 项） | 当时未跑该独立命令 | ✅ **已关闭**：`release_check` 第 7 项 `contract` 实测 **pass**（观测 2026-09-26T04:59） |
| 7 | 源码树可导入（第 8 项） | 实测 `python -c "import agentflow.capabilities"` 退出码 0 | ✅ **已关闭**（`release_check` 第 8 项 `imports` 实测 pass，`bad={}`） |
| 8 | `INVENTORY` 的"7 个零测试工具"在本仓是否仍成立 | 当时未复算 | ⚠️ **仍未关** |
| 9 | `docstring_has_why` 的真实比例 | 实测 R007 的两组读数（不同时刻两组，都保留） | ⚠️ **已量化，未关闭**（**两组数不矛盾，是不同时刻** —— 这正是 §1.1 那条规矩的实例） |
| 10 | `ReviewFinding` 的 `review_rounds` 上限具体数值 | 当时未找到显式常量 | ⚠️ **仍未关** |
| 11 | `method="formal"` 的真实后端路径 | 本机当时无 Lean/Coq/Isabelle | ✅ **已关闭（B8a）**：Mathlib 就位后真 Lean 四条控制实测 `fail=0`（`temp/B8a-evidence.md`；独立验收 `temp/VERIFY-B8a-G18.md`）。⚠️ 它证明的是"**桥接层能把真检查器的结论如实读出来**"，不证明"数学上证明了什么"。**2026-10-07 起这份后端在哪由机器级设置文件给**（`settings.json` 的 `toolchain.lean_bin` / `toolchain.mathlib_root`，见 `FORMAL-TOOLCHAIN.md`）—— 代码与文档里都不再写某台机器的路径 |
| 12 | 真实联网端到端 | 当时未跑 `-m network` | ✅ **已关闭（`G-31b`）**：观测 2026-09-26T02:42:12→02:42:41，`python -m pytest -m network -q -p no:cacheprovider` ⇒ `8 passed, 1873 deselected in 28.42s`，exit=0（原始输出 `temp/pytest-network-run1.txt`；采集清单 `temp/network-collect.txt`）。**它证明什么**：Crossref + OpenAlex 两条真实 HTTP 通路可用，且"`precise` 模式恒为 0"与"Crossref `select` 字段名错导致全 400"这两个**只有真实往返才能发现**的缺陷已被守住。**它不证明什么**（`temp/network-and-key-status.md`）：不证明"所有域都通"（`api.semanticscholar.org` 实测 429；`github.com`（easyocr 模型源）实测 `CERTIFICATE_VERIFY_FAILED` ⇒ easyocr 的模型**下不来**，所以 `ocr.run` 的 `egress` 通路**没有**被这 8 条覆盖），也不证明 LLM/provider 端到端（无真实 key） |
| 13 | 本机是否有 `easyocr` / `pytesseract` / `fitz` | 当时未探测 | ⚠️ **仍未关** |
| 14 | D 到底改了 `relations` 的什么字段 | 当时未逐行读 | ⚠️ **仍未关** |
| 15 | `G → D/E/F` 是否有实际代码路径 | 当时未 grep 实际 `summon("D", …)` 调用点 | ⚠️ **仍未关** |

---

## A7 [附录·历史] 文档与代码不一致清单（带 `文件:行号` 的那一版）

> 每一条都是当时**实际核对**出来的；**以代码为准**。
> ⚠️ **行号一律是当时的**，今天可能已经漂了 —— 这条清单的价值在"哪一类不一致存在过"，
> 不在行号。要复现就按每条的描述去 `grep` 那个符号。

### [附录·历史] A7.1 写作过程中发现的不一致（D1–D20）

| # | 文档说 | 代码实际 | 证据 | 当时的严重性 |
|---:|---|---|---|---|
| **D1** | `README.md` 的标题与 `cd` 路径都指向 `test\test1`，还写着"离线套件：127 passed" | **已重写** `README.md`：标题改为 `agentflow —— 面向数学研究的多智能体协同框架（正式版）`，跑法/目录/测试命令全部指向 `agentflow`，并新增"§7 已知限制"（含"README 不是判据"这一条） | `README.md` 全文 | ✅ **已关闭（S2）** |
| **D2** | `cli.py` 注释逐字："角色清单必须来自 `ROLES`，**不许在这里写死**" | 原 `choices=["A","B","C","D"]` **已修为 `list(S.ROLES)`**；实测 `cli tools --role E` 退出码 0、`--role Z` 退出码 2 | A4 第 2 条 | ✅ **已关闭（S2）** |
| **D3** | `scripts/lint_rules.py` 有 **R007 缺 docstring** 规则 | R007 有**显式两档**：日常报一条带**分布**的 `info`（点名缺失最多的几个模块），`--strict` 逐模块报 `warning`。**"更严"体现在判据上而不是级别上** —— 只把级别升成 warning 会让上百条警告常驻输出，而发布门第 5 项只看 `error`，等于什么也没挡住 | `scripts/lint_rules.py` 的 `rule_R007_missing_docstring` + `tests/test_lint_rules.py` | ✅ **已裁决（S2）** |
| **D4** | `AGENTS.md` 与 `.noai-paths` 逐字声明"（有负控用例，见 `tests/test_noai_gate.py`）" | 当时实测该文件 51 例，含"台账缺失 ⇒ `unknown`""hash 漂移 ⇒ `requires_human`""台账自指 ⇒ 永远 unapproved"等负控 | A4 第 10 条 | ✅ **已关闭（S2）** |
| **D5** | `scripts/release_check.py` 第 2 项要求"8 个 agent + pipeline 自检全部退出码 0" | 实测全部 exit 0（`a` 22/22、`b` 18/18、`c` 46/46、`d`–`h` 均 `SELF-CHECK DONE`）；A/B 已补自检块 | A4 第 6 条 | ✅ **已关闭（S2）** |
| **D6** | `.noai-paths` 登记了 `src/agentflow/release_check.py` 为"（**登记时并不存在**）" | **实测它仍不存在**；`scripts/release_check.py` **已存在** | `Get-ChildItem src/agentflow -Filter *.py` / `Get-ChildItem scripts` | **一致**（登记策略按设计生效） |
| **D7** | `capabilities.py` 的注释与 `WRITE_SETS["C"]` 说 C 写 `analysis_reports` | 与 `capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]` **一致**，且 `assert_capabilities()` 第 4 条会拦未登记的写集 | `capabilities.py` | **一致** |
| **D8** | `attack_tools.py` 的 `TERMINAL_STATUSES = ("resolved","abandoned","stalled")` | `schema.ATTACK_STATUSES` **含 `supported_not_proved`**，且 `agent_f.py` **会写它** | `attack_tools.py` vs `schema.py` vs `agent_f.py` | **中**（两份"终态"名单不一致；`include_terminal` 过滤会把已终结的计划当未终结） |
| **D9** | `ROLE-SPECS.md` 的 M 节在写作时误写成 `condudctor.py`（拼写错） | 实际是 `conductor.py` | `conductor.py` | **低**（**文档自己的**勘误，保留以示纪律） |
| **D10** | `README.md` 说"本机未接 provider、未实跑" | `pyproject.toml` 与 `config.yaml` 与 `tests/test_providers_online.py` 都在 | 同上 | **未核实**（README 整体过期，不作为判据） |
| **D11** | `schema.py` 的注释说"`tools.ROLES` **就是**这一个对象（它 import 这里）" | 实测 `tools.ROLES is schema.ROLES` → **`True`** | 实测命令 | **一致** |
| **D12** | `draft/13` §7 FC-24 标"**未落地**（数学领域无 benchmark 记录表）" | `schema.EVAL_REQUIRED_FIELDS` + `EvalResult` + `tests/test_fc05_contract.py` 的 4 条 eval 测试 | `schema.py`；`tests/test_fc05_contract.py` | **该陈述已过期**（`draft/13` 是对 `abflow` 写的） |
| **D13** | `README.md`："`suspect` 状态没有复核流程：关系被标 `suspect` 后只是留在表里等人看" | **实测：仍未在 `agent_*.py` 里核到批量复核入口**（当时未逐行 grep） | `README.md` | **一致**（可能仍成立） |
| **D14** | `LESSONS.md` FC-06 判据①逐字："本项目实测 `{'A':20,'B':18,'C':23,'D':28}`" | 当时的实测是 `{'A':20,'B':18,'C':17,'D':37,'E':21,'F':32,'G':32,'H':23}` | A4 第 2 条 | **数字已过期**（且 FC-06 只列了 A–D） |
| **D15** | `LESSONS.md` FC-23 落地形态："本项目缺口：**一条关系只能引一篇文献**" | `Relation.supporting_lit_ids` **已存在**（实测 7 处命中） | 实测 token 搜索 | **该"缺口"陈述已过期** |
| **D16** | `LESSONS.md` FC-27 / `draft/17` §6.3："多数脚本不设退出码" → "未报错被误读为无问题" | `.noai-paths` / `AGENTS.md` 明确要求三档退出码；`noai_gate.py` **已实现** 0/1/2；`release_check.py` **也已实现** 0/1/2 | 实测 3 个方向 | **已落地**（把教训变成门的正面范例） |
| **D17** | `tools/__init__.py` 的模块 docstring 说"模块缺失时**不报错，只记录**" | `build_registry(strict=True)` 时**会抛**；`strict=False`（默认）才只记录 | `tools/__init__.py` | **部分不一致**（docstring 未提 `strict` 参数） |
| **D18** | `tools/base.py` 说"`none`/`read` 的工具可以任意调用、不需要审批" | 判据是 `ToolSpec.needs_approval`（两根轴推导）；B3 收官后四个检索/OCR 工具都如实声明了第二根轴（`egress`），`verify.check_formal` 声明 `exec` ⇒ 这条承诺现在由**声明**承担，不再靠遗留取值兜底 | `tools/base.py` 的 `ToolSpec.needs_approval`；`tests/test_tools_base.py` | **已收口**（遗留的 `NEEDS_APPROVAL` 表已删除，审批只剩一条推导规则） |
| **D19** | `schema.py` 的 `Task` docstring 说"dispose 幂等…（由 `Conductor` 实现）" | `conductor.dispose` 实测幂等（第二次返回 `closed: []`，`finish` 走幂等分支**连事件都不追加**） | `schema.py` vs `conductor.py` | **一致** |
| **D20** | `capabilities.py` 说"**不在表里的角色没有任何动作**（`M` 就是如此）" | 实测 `CAPABILITIES["M"] == ()` | `capabilities.py` | **一致** |

### [附录·历史] A7.2 S2 新增的待裁决项（由审计发现）

| # | 甲方的说法 | 乙方的实测事实 | 证据 | 当时的处置 |
|---:|---|---|---|---|
| **D21** | `agent_a` 的退避租约注释说"避免在同一进程里**立刻重打同一个 API**" | `_claim()` 的跳过判据要求 `claimed_by` 非空，而**失败分支会把 `claimed_by` 置空** ⇒ 同一实例下一轮**会立刻再领同一条**（最多 3 次后 `gave_up`）。真正的退避只发生在"队列里还有别的活"时（靠 `order_pending_requests` 的分桶排序） | 审计实测 + `agent_a` | **待人工裁决**。两条路：(a) 把注释改成"**软退避（仅排序）**"——承认它不做硬拦；(b) 给 `_claim` 加一条"`lease_until` 在未来 ⇒ 跳过"——但 `order_pending_requests` 的 docstring 明确论证了"空租约与已过期租约同桶"是**刻意设计**，硬拦会改动已冻结的排序语义。**未裁决前不许把它写成"已实现退避"。** |
| **D22** | `cli.py` 的 `cmd_verify` 原先"默认宽松、`--strict` 才严" | 已改为**默认严**（有 error ⇒ 退出码 1），`--strict` 加严到把 warning 也算失败。文档记录的基线（干净库 → "通过 / 错误 0 / 警告 0"、退出码 0）实测未变 | 审计实测 | **已修**（保留在此以记录语义变更） |
| **D23** | `cli.py` 的 `cmd_submit` 声称"ID 分配器只有一处" | 它**自己**数 `len(rows)+i+1`，且多条提交时 `while` 循环改的是 `n` 而 `rid` 用 `n+i+1`、**无上限**（行数过万 ⇒ 静默产出 `r-10000`，越出 4 位 ID 契约） | 审计实测 | **已修**（改用 `interactions.next_prefixed_id`）。⚠️ 这是"**最小可用号会复用已删除的 ID**"那个缺陷的**同族**：两处取号 = 两个 ID 语义 |

---

## A8 [附录·历史] 本文引用的全部命令与真实输出

见 [`ROLE-SPECS.md`](ROLE-SPECS.md) 附录 S3（同一批命令，避免两处漂移）。
**那一处是唯一落点**：这一节原先在规范面里重复列了一遍，split 之后只留这一句指针。
