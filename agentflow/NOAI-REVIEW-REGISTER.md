# NOAI-REVIEW-REGISTER —— FC-27 禁 AI 区**人工复核登记表**

> 本文件是 `AGENTS.md`（禁 AI 区硬约束）的**人读附件**。
> 机器可读部分是 `.noai-approvals.json`（hash 台账）与 `scripts/noai_gate.py`（门）。
> 三份东西的分工**不许混**：

| 文件 | 是什么 | 谁写 |
|---|---|---|
| `.noai-paths` / `AGENTS.md` 标记区块 | **禁改区清单**（该轮 **18** 条 glob、7 类；当前值见 `README.md` §6.2），两处逐条一致 | 人维护；AI 改动它本身也要被复核 |
| `.noai-approvals.json` | **hash 台账**：每个命中文件当前内容的 `sha256` + 变更摘要 + **已完成的人工走查记录** | `--baseline` 由工具写；`reviewers` **只能由人填** |
| **本文件** | **人读的登记表**：这一轮到底改了什么、复核人该读哪些、批准栏 | 主控 AI 起草；**批准栏由人签** |

---

## 0. 一句话结论（**如实，不修饰**）

**2026-09-24 这一轮里，15 个禁改区文件被登记/改过**（14 个源码与配置 + 台账自身），而在此之前本项目没有任何机器可执行的记录能说明"哪些改动已被 2 名 reviewer 走查过"。

这不是推测，是实测：

| 证据 | 值 |
|---|---|
| 命中清单的文件数 | **15**（该轮 `.noai-paths` 有 **19** 条 glob；其中 `src/agentflow/release_check.py` 仍未创建，另有 3 条落在同一批文件上） |
| 该轮被改动的 | **14**（新增：`tools/release_all.py` —— 该轮新建的发布检查**编排层**） |
| 该轮未被改动的 | **1**（`src/agentflow/quoteverify.py`，mtime 2026-09-23 21:22） |
| 已完成的**人工**逐行走查 | **0**（**该轮 2026-09-24 读数**：台账 `reviewers_total = 0`；该轮读数一律以 `python scripts/noai_gate.py --check-approvals` 的输出为准） |
| 为什么检测不到 | **`D:\Incubator\agentflow` 不是 git 仓库** ⇒ `noai_gate.py --git` 永远返回 `unknown(2)`；不给 `--paths` 也是 `unknown` |

> ⚠️ **这张表被修正过两次，每次修正本身就是这条纪律的实例**（都记在案）：
> 1. §2 第 12 条原先写 `tools/verify_tools.py` 的 mtime 是 **07:35**，而写完之后它**又被改过一次**
>    （实测 **07:59:55**）。也就是说：**"登记"这件事本身也会过期。**
> 2. **同一个文件后来又变了第三次**（该轮"把 `returns=` 统一成机器可读"的子代理改了它的
>    `returns=` 字符串）。台账因此报 **`stale`**，并**同时打印两个 hash**
>    （台账 `f0626116b6c3` ≠ 盘上 `0ec86a07b63e`）。
>    这正是 hash 台账比 mtime 强的理由 —— mtime 只能看出"变过"，
>    **hash 能指出"你批准的那一版与盘上这一版不是同一版"**。
>    **本表的任何一行都不该被当成"现在已经没再变了"。**

> 🗂 **本文件是历史档案，不是当前值文档。** 本文件里出现的**全部计数**
> （`.noai-paths` 的 glob 数 / 唯一路径数 / 类数，台账的条目数 / `reviewers_total` / 欠签，
> §2 的行数，§0 的文件数与 mtime 范围）都是 **2026-09-24 / 09-25 当轮**的读数，
> 此后**不再随盘上事实更新**。**当前值以 `README.md` §6.2 与 `DEVELOPMENT.md` §1.5 为准** ——
> 同一批数量在那两处是被判据钉住的当前值（`tests/test_release_all.py` 的
> `readme_number_problems` / `live_reading_problems` / `manifest_claim_problems` /
> `ledger_derived_claim_problems`），而本文件**不在那些数字对账判据的覆盖面里**：
> 本文件当前只有一条判据看着它 —— "点名的测试对象必须在盘上存在"
> （`doc_test_reference_problems`，见 `tests/test_release_all.py`）。
> 因此下面每一处计数都按"**该轮**读到的是多少"读，**不要**按"现在是多少"读；
> 二者的差是这份档案与当前值文档的正常分工，不是一处待修的漂移。

`AGENTS.md` 引用的那句教训逐字是 *"测试全绿、上线即越权"*。
该轮的实际形态比它更安静：**测试全绿、门也在、门查不了。**
`unknown(2)` 已经被正确地报出来了（这一点门是对的），但**没有任何东西会因为它是 `unknown` 而停下来** —— 于是 14 个文件的改动在"没有人工复核"的状态下向前推进。

**这份登记表就是那条缺失的记录。它本身不构成批准。**

> **2026-09-25 追加（第二轮）：又改了 4 个禁改区文件，且仍未获批准。**
> `schema.py` / `store.py` / `verify.py` / `tools/release_all.py` —— 内容是提案 A
> （`docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`）的三处落地 + 发布门自身的输出编码修复。
> 四条都已 `--baseline` 刷新 hash，`reviewers` **在该轮（2026-09-24/25）观测时仍为 0**（该轮以 `python scripts/noai_gate.py --check-approvals --paths <清单里的路径…>` 的输出为准；**裸跑 `--check-approvals` 会以 exit 2 / `[unknown]` 结束**（没有给出改动集），读不出 `reviewers_total`），走查清单见 §2.2。
> 也就是说：**上面那句"没有任何东西会因为它是 `unknown` 而停下来"在这一轮里又成立了一次。**

> **2026-09-25 追加（第三轮）：AI 没有碰任何禁改区文件；该轮把"签字包"做到可直接照做。**
> 改动只落在非禁改区：`src/agentflow/capabilities.py`（`E.check_formal` 的 `side_effect`
> 由 `unknown` 改为与真实行为一致的 `network`）、`src/agentflow/agent_e.py`
> （`check_formal` 的参数透传 + `script_path` 路径守卫）、新增
> `tests/test_check_formal_wiring.py`、`docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`
> 的 §4.2.1 实测更正，以及**本文件**。
> **因此这 8 条欠账的 hash 一条都没变**（`--check-approvals` 实测 `stale 0`，只有 `reviewers` 缺）。
> **人现在只需要做 §2.4 的四步**：跑两条门命令 → 按 §2.3 逐条走查 8 个文件 →
> `--approve` 签 2 个名字 → 复跑门看到 `clean`。
> 两条实验结论（回滚后 `rebuild` 到底丢不丢、字段级唯一性是否端到端生效）已登记为
> **§2.5 待确认项**，各带一个可直接跑的脚本；`reviewers` **在该轮观测时仍为 0**（证据在 §2.6；该轮读数以 `python scripts/noai_gate.py --check-approvals --paths <清单里的路径…>` 为准 —— 裸跑那一支是 `[unknown]`，不是「没人签」）。

---

## 1. 门怎么用（三档退出码，**`unknown` 绝不是 `clean`**）

```text
python scripts/noai_gate.py --paths <改动文件…>                    # 只判"命中没命中"
python scripts/noai_gate.py --check-approvals --paths <改动文件…>   # 命中 + 台账判定（推荐）
python scripts/noai_gate.py --check-consistency                    # 两处清单逐条一致（该轮两处各 19 条；当前值见 README §6.2）
python scripts/noai_gate.py --baseline --paths <文件…>              # 登记/刷新 hash（**不写 reviewers**）
python scripts/noai_gate.py --approve <文件> --reviewer <姓名> --scope "<走了哪些行/函数>" --note "<结论>"
```

`.noai-paths` 该轮有 **19 条 glob**（原 17 条 + `.noai-approvals.json` 自身那一条
+ 该轮新建的 `tools/release_all.py`，
见 `docs/NOAI-GOVERNANCE.md` 与 `AGENTS.md` 的标记区块 —— 两处**逐条一致**，
由 `--check-consistency` 按位比对三元组）。

| 退出码 | 结论 | 含义 |
|---|---|---|
| 0 | `clean` | 查过了：要么没命中，要么命中项的 hash 与台账一致**且**已有 2 名 reviewer |
| 1 | `requires_human` | 查过了：命中且**未获批准**（未登记 / hash 已漂 / 走查人数不足） |
| 2 | `unknown` | **没查成**（清单或台账读不到、不是 git 仓库、没给改动集）⇒ **不代表没问题** |

**"登记"（`--baseline`）与"批准"（`--approve`）是两个动作，不许合并。**
前者说"我记下了这个文件现在长这样"，后者说"我（人）逐行走查过这一版"。
合并它们等于让 AI 自己给自己发批准 —— 那正是 FC-27 要防的事。

---

## 2. ⭐ 逐文件登记表（该轮 14 条）

「符号面变化」一列来自 `temp/_symbol_diff.py`：把本仓库与原型 `test/test1/src/abflow/`
的**顶层符号集合**做差。用符号集合而不是行 diff 的理由：两份树的包名/缩进/换行都不同，
行 diff 会淹没在噪声里；而复核人真正要的是"**新增了哪些可被调用的东西**"。

⚠️ **符号集合相同 ≠ 实现没被改。** 有 5 个文件符号面一模一样而 mtime 是该轮当天 ——
它们的改动**全在函数体内部**，只能逐行走查。这一列必须按这个口径读。

| # | 文件 | 类别 | mtime | 符号面变化 | 归属 |
|---|---|---|---|---|---|
| 1 | `pyproject.toml` | release-deploy | 07:14 | 原型无此文件（正式版新建） | 主控 AI |
| 2 | `scripts/release_check.py` | release-deploy | 07:42 | 原型无此文件（正式版新建） | 子代理 AI + 主控 AI |
| 3 | `src/agentflow/dedup.py` | solver-core / provenance-dedup | 07:28 | **+4**：`def _to_halfwidth`、`var _DOI_SCHEME_PREFIX_RE`、`var _DOI_URL_PREFIX_RE`、`var _FULLWIDTH_RE` | 子代理 AI（有报告） |
| 4 | `src/agentflow/extract.py` | solver-core | 07:53 | **符号面相同** ⇒ 改动全在函数体内 | ⚠️ **归属未定** |
| 5 | `src/agentflow/interactions.py` | auth-audit | 07:26 | **+1**：`var CONTRACT_VERSION` | 主控 AI |
| 6 | `src/agentflow/providers.py` | solver-core / provenance-dedup | 07:41 | **符号面相同** ⇒ 改动全在函数体内 | 子代理 AI（有报告） |
| 7 | `src/agentflow/quoteverify.py` | prover-bridge | **09-23 21:22** | 符号面相同 | ✅ **该轮未改动** |
| 8 | `src/agentflow/schema.py` | schema-migration / eval-criteria | 07:42 | **+20**：`def Task`/`def UsageEntry`/`def EvalResult`（+各自 `validate`/`to_dict`）、`var ARRAY_FIELD_KINDS`、`def array_kinds`、`def check_array_invariants`、`var ATTACK_TERMINAL_STATUSES`、`var CONDUCTOR_ROLE`、`var ROLES`、`var REFUSAL_REASONS`、`var TASK_STATUSES`/`TASK_OUTCOMES`、`var USAGE_SCOPES`、`var EVAL_REQUIRED_FIELDS` | 主控 AI + 子代理 AI |
| 9 | `src/agentflow/store.py` | schema-migration | 07:42 | **符号面相同** ⇒ 改动全在函数体内 | ⚠️ **归属未定** |
| 10 | `src/agentflow/tools/__init__.py` | auth-audit | 07:44 | **−1**：`var ROLES` 不再在此**赋值**（改为引入，与清单理由"`ROLES` 的引入"一致） | 主控 AI + 子代理 AI |
| 11 | `src/agentflow/tools/base.py` | auth-audit | 07:44 | **+1**：`ToolResult.pruned` | 子代理 AI + 主控 AI |
| 12 | `src/agentflow/tools/verify_tools.py` | prover-bridge | **07:59** | **符号面相同** ⇒ 改动全在函数体内 | 子代理 AI（**越界改动**，见 §3.3） |
| 13 | `src/agentflow/verify.py` | auth-audit | 07:41 | **符号面相同** ⇒ 改动全在函数体内 | 主控 AI |
| 14 | `tools/release_all.py` | release-deploy | **08:50** | **该轮新建**（一键发布检查的编排层） | 主控 AI |

> **第 14 条是这一轮新登记进禁改区的**。理由（逐字写在 `.noai-paths` 与 `AGENTS.md` 的
> 标记区块里，两处一致）：它决定"**跳过的步骤记成 `unknown` 还是 `pass`**" ——
> 那一条取舍就是"发布门能不能被 `--skip` 绕过"。
> **一个新建的发布门必须当场登记**，否则"换个目录就绕过"就成立了。

### 2.1 逐条的改动摘要与复核要点

#### 1. `pyproject.toml` — release-deploy
- **改了什么**：包元数据（`name`/`version`/依赖/构建后端）+ **pytest 配置单一化**：`testpaths=["tests"]`、`addopts="-m 'not network'"`；同时**删除** `tests/pytest.ini`（配置两处落地会分叉）。
- **复核要点**：
  1. `version` 与 `src/agentflow/__init__.py` 的 `__version__`、`__schema_version__` 是否一致（有 `release_check` 的 `contract` 项在查）。
  2. `addopts` 里的 `-m 'not network'` 会不会把**该跑的**测试也筛掉 —— 这是"默认不跑网络"的**取舍**，必须有人认可：网络测试靠 `-m network` 显式跑。
  3. `[build-system]` 的构建后端与依赖是否与部署环境一致。

#### 2. `scripts/release_check.py` — release-deploy
- **改了什么**：八项检查（`tests`/`selftests`/`tools`/`verify`/`lint`/`noai`/`contract`/`imports`）、三档结论（`pass`/`fail`/`unknown`）、退出码 0/1/2；第 2 项原本把"模块没有自检块"读成 **PASS**，已改为 `unknown`。
- **复核要点**：
  1. `_VERDICT_EXIT_CODES` 与"有任何 `fail` ⇒ 退出 1、有 `unknown` 无 `fail` ⇒ 退出 2"的映射；**`unknown` 会不会被当 `pass` 统计**（这是本项目的核心教训，第 2 项的修复就是这条）。
  2. 第 6 项 `item_noai` 目前用 `--paths` + `--changed`；**它还没用上 `.noai-approvals.json`**（见 §4 待办 T2）。这一条**必须由人决定要不要现在接**。
  3. 本脚本的 docstring 自称 `authored_by: AI agent，尚未经人逐行走查` —— **这正是本条要人走查的原因**，不要因为看到了这句话就跳过。

#### 3. `src/agentflow/dedup.py` — solver-core / provenance-dedup
- **改了什么**：`normalize_doi` 成为**唯一实现**（原 `providers.normalize_doi` 与之分歧：`http://dx.doi.org/…`、尾随 `.`、全角数字三组输入给出不同结果 ⇒ **同一篇论文两个主键**且无任何报错）。吸收了更严的那一份：NFKC 折全角、吃掉 `https?://` + 可选 `dx.` + `doi.org/`、`rstrip(".")`（**不是** `strip(".")`）。附加 3 个模块级常量与 `_to_halfwidth`。
- **复核要点**：`normalize_doi` 的正则与 `rstrip`/`strip` 的**取舍本身**（多删一个前导字符是"两个不同 DOI 被合并"这种不可逆错误，所以选 `rstrip`）；`decide_relation` / `literature_keys` / `title_key` 是否被顺手改过（**符号面没变，必须逐行确认**）。

#### 4. `src/agentflow/extract.py` — solver-core
- ⚠️ **归属未定**：该文件该轮被改（mtime 07:53）且**符号面与原型完全相同**，改动全在函数体内。我**无法从仓库判定**是哪个执行单元改的（本会话有两个子代理的复核范围覆盖它，报告尚未到达）。
- **复核要点**：`extract_text` 及其 PDF 后端选择逻辑（pypdf/PyMuPDF/pdfminer 的降级顺序）、编码探测、失败时的三态返回。**抽取错一个字符，逐字引文回验就会把真引文判成幻觉** —— 这是该轮改动里风险最高的一处，请优先走查。

#### 5. `src/agentflow/interactions.py` — auth-audit
- **改了什么**：新增 `CONTRACT_VERSION = 1`（跨模块契约版本；`release_check` 的 `contract` 项断言它与包级 `CONTRACT_VERSION` 一致）。
- **复核要点**：`check_conflict` / `admitting` 一族角色间授权矩阵是否被改（**符号面没变**）；`CONTRACT_VERSION` 的**递增规则**是否写清（什么时候必须 +1）。

#### 6. `src/agentflow/providers.py` — solver-core / provenance-dedup
- **改了什么**：`normalize_doi` 改为**转发**到 `dedup`（函数内惰性 import，避免模块级循环）。
- **复核要点**：转发体是否**真的只是转发**（无补默认值、无吞异常、无改返回值）；`_plan_mode` / `_precise_keep` / `_broad_sort_key` / 各 provider 的 `_parse_work` / `_parse_item` 是否被改（**检索口径一旦偏移，"找到的文献"与"声称找到的文献"就分家了**）。

#### 7. `src/agentflow/quoteverify.py` — prover-bridge
- ✅ **该轮未改动**（mtime 09-23 21:22，早于该轮全部改动）。登记它只为**建立基线**，以免将来它被改时无从比对。
- **复核要点**：`check_quote` 的比对口径（空白/大小写/连字符的归一化边界）。**已知的一处设计争议**：把归一化放宽能减少假警报，但会放宽"逐字"的含义 —— 这是**判据本身**，属于禁改区的理由。

#### 8. `src/agentflow/schema.py` — schema-migration / eval-criteria
- **改了什么**：新增**四张运行记录层/台账层**的声明（`Task`、`UsageEntry`、`EvalResult` 及其 `validate`/`to_dict`）、`ARRAY_FIELD_KINDS` + `array_kinds` + `check_array_invariants`（**集合字段升序去重**的判据集中到一处，`validate_table` 调用它）、`ATTACK_TERMINAL_STATUSES`（消除 `attack_tools` 与 schema 的状态集合漂移 —— 该漂移的实测后果是**终态计划被重新当作在跑的**）、`CONDUCTOR_ROLE`、`ROLES`、`REFUSAL_REASONS`、`TASK_STATUSES`/`TASK_OUTCOMES`、`USAGE_SCOPES`、`EVAL_REQUIRED_FIELDS`。
- **复核要点**（这一类是"改它等于改磁盘格式契约"）：
  1. `SCHEMA_VERSION` 是否随表结构变化而被**正确递增**（**没有递增就是缺陷**：磁盘上老数据会被按新契约读）。
  2. `TABLES` 的 `id_field` / `id_kind` 与 `store.alloc_id` 的前缀约定是否一致。
  3. `EVAL_REQUIRED_FIELDS` 与 `EvalResult` 的比率口径（0..1）—— **改它等于追溯性地改写历史报告里每个数字的含义**。
  4. `check_array_invariants` 的排序键 `sorted(set(val), key=…)` 里那个 `if False else v` 的残留写法（看起来像调试遗留）需人确认是否有意为之。

#### 9. `src/agentflow/store.py` — schema-migration
- ⚠️ **归属未定**：该轮被改（mtime 07:42），**符号面与原型完全相同**，改动全在函数体内。
- **复核要点**（清单理由逐字点名这四处，四者任一错都是**数据毁灭级**）：`LOCK_ORDER` 的加锁顺序、`rebuild` 的事件重放、`alloc_id` 的 ID 分配、`_atomic_write` 的原子落盘。**优先走查 `alloc_id`**：该轮发现过一处"最小可用号会复用已删除的 ID"的缺陷（会静默误导 `literature.source_request_ids`），该缺陷的修复正是落在这类位置上。

#### 10. `src/agentflow/tools/__init__.py` — auth-audit
- **改了什么**：`build_registry` 增加 `context_budget=` / `config=` 参数与 `default_spill_root`，装配期校验预算几何；`ROLES` 改为从 `schema` **引入**（不再在此赋值）；`READ_ONLY_ROLES` / `SIDE_EFFECTS_WRITE` 维持为只读角色权限面的单一来源。
- **复核要点**：`READ_ONLY_ROLES` = {C, H} 是否仍然只包含这两个角色（**放宽它等于给只读角色发写工具**）；`build_registry` 的角色断言是否仍在装配期执行、且**没有被新参数分支绕过**。

#### 11. `src/agentflow/tools/base.py` — auth-audit
- **改了什么**：`ToolRegistry` 增加 `default_budget` / `default_spill_root`（FC-17 的装配期落点）；`ToolResult.pruned`（+1 符号）；`for_role` 的**结构性过滤**（只读角色一律拿不到写工具）；`ParamError`。
- **复核要点**：`for_role` 的过滤是**实现**，`tools/__init__.py` 的 `READ_ONLY_ROLES` 是**声明**，两者分处两文件、必须同时人审（清单理由逐字如此）；`default_budget` 为 `None` 与"预算存在但为 0"必须是两件事（三态）。

#### 12. `src/agentflow/tools/verify_tools.py` — prover-bridge
- **改了什么**：⚠️ 这已经是**第二次越界改动** —— 第一次是"修工具层缺陷"的子代理（`detect_verifier` 的 `checked` 改为如实、`side_effect` 由 `none` 改为 `read`、`check_formal` 三态分支结构统一、全部 `verified=None`），第二次是"把 `returns=` 统一成机器可读"的子代理（只改了 `returns=` 字符串，例如 `verify.code_hash` 现在是 `{'path': str, 'code_hash': str}`）。
- **⚠️ 两次都不是授权范围内的改动**，处置都是**接受而不回滚**（回滚会留下一个"声明不可解析"的工具，与 G-4 的目的相反；而且回滚本身又是一次禁改区改动），并登记为**待 2 名 reviewer 逐行走查**。
- **复核要点**：`detect_verifier` 的探测顺序与 `check_formal` 对检查器输出的**解释**。清单理由逐字：*"桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印"*。
  ⚠️ **`check_formal` 的 `proof` 路径在取得人工批准前不得主张为可用** —— 这是实现者自己写下的口径，请复核人确认或推翻。
  ⚠️ **与新建后端 `src/agentflow/formalgw.py` 尚未接线**（工具层仍返回 `not_implemented`）—— 处置待人工，见 §4 的 **T7**。
  ⚠️ 第二次改动只是声明字符串，**但它同样改的是"桥接层对外承诺什么"** —— 对 proof 级证据而言，"承诺的键集合"与实现一致正是 `verifier_output` 能不能被信任的前提。
- **该轮的时间戳漂移（这条登记表自己抓到的第一个实例）**：原记 `07:35` → 实测 `07:59:55` → **第二次改动后又是新的一版**。台账的 `--check-approvals` 因此报 **`stale`** 并**同时打印两个 hash**（台账 `f0626116b6c3` ≠ 盘上 `0ec86a07b63e`）。
  **这正是 hash 台账比 git 强的那一点**：git 只会说"文件变了"，而它说出"变的**不是被批准的那一版**"。
  处理流程（见 §3.1）：确认以哪一版为复核对象 ⇒ 必要时重跑 `--baseline`（会**清空该条的批准语义**，因为它换了对象）⇒ 再 `--approve`。

#### 13. `src/agentflow/verify.py` — auth-audit
- **改了什么**：新增渲染层门 `number_without_eval_scope`（一个数字出现在正文里却没有 `eval:` 引用 ⇒ 发现问题）与 `eval:` 引用的解析；为 `tasks` / `usage_ledger` / `eval_results` 三张新表补一致性检查。
- **复核要点**：`verify_all` 的**判据本身是否被改宽**（清单理由逐字：*"判据本身被改宽 ⇒ 审计从此永远『通过』"*）；新增的两条门是否**真的挂在 `verify_all` 的返回里**（如果只是定义了函数而没接进去，那"加了检查"这句话就是假的）；`unknown`/`not_applicable` 与 `pass` 是否分得开。

---

### 2.2 该轮（提案 A）的禁改区改动：逐 hunk 复核清单（**可直接照着签字**）

#### 2.2.1 一句话变更摘要（每处都写清"我凭什么认为它没把不变量改宽"）

| 文件 | 类别 | 改了哪几行（按符号走查） | 我凭什么认为安全 | 残余风险（如实说） |
|---|---|---|---|---|
| `src/agentflow/schema.py` | schema-migration / eval-criteria | `UsageEntry.idem_key`（1 个有默认值的新字段）+ `UsageEntry.validate`（1 条首尾空白断言）+ `validate_table`（1 段非空唯一性断言） | 纯附加：空串与缺字段的行不进唯一性；`SCHEMA_VERSION` 保持 1 所以无需迁移 | **混合版本窗口未覆盖**：未升级进程写下的行不带这个键 ⇒ 它逃过唯一性，滚动升级期间原竞态仍在 |
| `src/agentflow/store.py` | schema-migration | `Tx.insert_unique`（**纯新增方法**，未改任何既有行） | 不加新锁、不动 `LOCK_ORDER`、冲突路径不写事件也不分配 ID | 它是**显式工具**而不是自动保证：在 `store.tx` 之外调用它 = 窗口原样存在 |
| `src/agentflow/verify.py` | auth-audit | `verify_all` 内新增 `seen_idem` 循环（判据码 `duplicate_idem_key`） | 只**新增**一条检查，没有改宽任何既有判据 | 只对非空键生效（这是刻意的，见下） |
| `tools/release_all.py` | release-deploy | `main` 开头两行 `reconfigure` + `run_step` 的 `subprocess.run(... encoding=...)` | 不触碰三态判定、不触碰 `--skip` 语义、不改码表 | 只解掉输出编码这一处崩溃面 |

#### 2.2.2 逐条走查清单（**每条都必须自己跑一遍或看到原始输出**）

判据：每条都要能回答"我看了什么、结论是什么"。写"看过了"等于没看。

**A. `schema.py`（走查符号：`UsageEntry.idem_key` / `UsageEntry.validate` / `validate_table` / `SCHEMA_VERSION`）**

- [ ] A1 打开 `UsageEntry`：`idem_key: str = ""` 是不是**普通 dataclass 字段**（不是 `field(default_factory=...)`）？默认值是不是空串？
- [ ] A2 老快照（磁盘上没有这个键）读回来后 `idem_key` 是不是 `""`？跑：
      `python -c "import sys; sys.path.insert(0,'src'); from agentflow import schema as S; print(S.row_from_dict('usage_ledger', {'usage_id':'0000','scope':'search','at':'x','note':'n'}).idem_key)"`
      期望：打印一个空行（空串），不抛异常。
- [ ] A3 `UsageEntry.validate` 的首尾空白断言是不是**只**拒绝有首尾空白的值、**不**拒绝空串？（空串被拒 ⇒ 全部历史行非法 ⇒ 整表提交炸）
- [ ] A4 `validate_table` 的唯一性断言是不是**只在 `key_val` 非空时**执行？空键与**完全没有这个键**的行是不是都被跳过？
- [ ] A5 报错消息里是不是**同时给出两个 `usage_id`**？（只给一个 ⇒ 出错时无法定位那两行）
- [ ] A6 `SCHEMA_VERSION` 是不是仍为 **1**？（递增 ⇒ 全部旧工作区读不出来，且该轮改动没有迁移脚本）
- [ ] A7 `TABLES["usage_ledger"]` 的 `id_field` / `id_kind` 与 `store.alloc_id` 的前缀约定是否未被动过？
- [ ] A8 这份改动**没有**碰 `EVAL_REQUIRED_FIELDS` 与 `EvalResult`（那条同文件命中是既有的，不要把它算进该轮走查范围）。

**B. `store.py`（走查符号：`Tx.insert_unique` / `LOCK_ORDER` / `Tx.alloc_id` / `rebuild` / `_atomic_write`）**

- [ ] B1 `insert_unique` 冲突时是不是**只 `return False`**：不 `mark_dirty`、不 `_record`、不调 `upsert`？（写了一行事件 ⇒ 快照与事件流分家）
      判据（跑一次看事件数）：`python -m pytest tests/test_usage_ledger_idem_key.py::test_insert_unique_writes_once_then_reports_conflict -q`
- [ ] B2 它是不是**没有自己 `acquire` 锁**？（自己加锁 = 改加锁顺序 = 死锁面）
- [ ] B3 `LOCK_ORDER` 的元组内容与顺序是不是**逐字未变**（`git` 没有，所以请逐字比对 `AGENTS.md` 登记块里那句话描述的 16 张表）？
- [ ] B4 `alloc_id` 的既有行为是否未动？**并且**冲突路径确定不消耗号 —— 本实现把分配放在判重**之后**（`id_kind` 参数），请确认这个顺序没有被反转。
      判据：`python -m pytest tests/test_usage_ledger_idem_key.py::test_insert_unique_does_not_burn_an_id_on_conflict -q`
- [ ] B5 `id_kind` 是本实现对提案 §2.1 的**一处最小附加**（提案原文只写了"调用方填好主键"）。请确认：① 不打这个参数时行为与提案逐字一致；② 打这个参数时才分配号，且分配发生在判重之后。
- [ ] B6 空键抛 `StoreError` 而不是"当作不冲突"（后者会让唯一性完全失效）。
- [ ] B7 `rebuild` 与 `_atomic_write` 是不是**一个字节都没改**？

**C. `verify.py`（走查符号：`verify_all` / `Issue.code=="duplicate_idem_key"`）**

- [ ] C1 新判据是不是**真的挂在 `verify_all` 的返回里**（不是只定义了却忘了接线）？
      判据：`python -m pytest tests/test_usage_ledger_idem_key.py::test_verify_reports_duplicate_idem_key -q`（若没接线，它必红）
- [ ] C2 它对**空 `idem_key`** 与**没有这个键**的历史行是不是跳过？（否则历史行全部报错，审计被噪音淹没）
- [ ] C3 它是不是 `error` 级、且消息里给出**两个** `usage_id`？
- [ ] C4 该轮改动是否只**增加了**一条检查，没有把任何既有判据改宽或改窄？（`number_without_eval_scope` 等既有门未动）

**D. `tools/release_all.py`（走查符号：`main` 的 reconfigure / `run_step` / `classify` / `overall` / `build_steps`）**

- [ ] D1 `main` 开头是不是只加了"把 stdout/stderr 重设成 UTF-8 + `errors="replace"`"这几行？它在 `argparse` **之前**，所以连 `--help` 都不再依赖调用者 locale。
- [ ] D2 `run_step` 的 `subprocess.run` 是不是只是多了解码参数（`encoding="utf-8", errors="replace"`）？三态码表（`exit_map`）、`classify` 的分支顺序、`overall` 的优先级、`--skip`/`--only` 记 `unknown` 的取舍，是不是**一个字都没改**？
- [ ] D3 复现证据：`python D:\Incubator\temp\cp936_probe.py <repo> nofix` 必须因 `UnicodeEncodeError` 以退出码 1 结束；`... fix` 必须以 2 结束（`--only role-specs` ⇒ 其余 unknown）且无 `UnicodeEncodeError`。

#### 2.2.3 批准前必须由人亲自跑的两条（**AI 跑了不算**）

```text
python -m pytest tests/test_usage_ledger_idem_key.py -q          # 21 passed
python scripts/noai_gate.py --check-approvals --paths src/agentflow/schema.py src/agentflow/store.py src/agentflow/verify.py tools/release_all.py
```

第二条现在会报 `unapproved`（四条的 `reviewers` 都是空的）—— 这正是该轮要人补的那件事。

#### 2.2.4 该轮改动里**没有**做的事（如实登记，别当成已完成）

1. `SCHEMA_VERSION` 未递增、无迁移脚本 —— 提案 §3.1 的结论（纯附加字段不需要迁移）。
2. ✅ **已关闭（2026-09-25，原文照留备查 —— 不删历史）**：
   ~~**生产写入方仍未填 `idem_key`**：`tokenmeter.charge_once` 目前只把标记写在 `note` 里（提案 B 那一层）。
   于是"字段级唯一性"这条防线现在只被 `Tx.insert_unique` 的调用方与测试覆盖；接线的活留给下一次改动。~~
   **关闭依据 —— 由哪次改动关闭**：2026-09-25 **19:42–19:59** 那一轮"把幂等键同时填进字段"的改动
   （该轮**没有在 `docs/` 留下自命名**，所以下面用 mtime + 符号当它的身份；这本身就是 §5 第 1 条说的
   "本登记表不是 git"的又一次体现）。
   - **写入端（字段真的被填了）**：`src/agentflow/tokenmeter.py`（mtime 19:59:00）的
     `charge_once(c, *, idem_key)` 走 `_note_for(c, extra_token=key)` **与** `_row_for(..., idem_key=key)`
     —— 同一个 `key` 同时进 `note` 的 token 与 `UsageEntry.idem_key` 字段（`tokenmeter.py:415-433`）。
   - **模型调用级写入方**：`src/agentflow/modelcost.py`（mtime 19:58:43）的 `charge_reply` 用
     `key = idempotency_key(task_id, call_index)`（`modelcost.py:192`，唯一生成处）并
     `charge_once(..., idem_key=key)`（`modelcost.py:362`）；端到端路径 `runflow.py:660` 就是调它。
   - **召唤级写入方**：`src/agentflow/conductor.py`（mtime 19:42:57）的 `_charge_and_settle` 用
     `self.meter.charge_once(charge, idem_key=settle_key(res.task_id))`（`conductor.py:627`），
     `settle_key` 定义在 `modelcost.py:209`。
   - **现在的证据（判据）**：`tests/test_idem_key_writers.py`（mtime 19:47:32，两条写入方各一组断言 +
     会红的负控）；跑法 `python -m pytest tests/test_idem_key_writers.py -q`。
   - **关它的人（AI）该轮复跑过的原始输出**（`D:\Incubator\temp\taskA_evidence.py`，2026-09-25 W3 轮）：
     - `[1] charge_reply 写下的那一行` → `usage_id=0000 idem_key='idem-84fee6797695'`、`相等=True`、
       `note='modelgw;call_index=2;outcome=ok；idem-84fee6797695'`、重放 `charged=False reason=duplicate`（行数=1）；
     - `[2] conductor 结算写下的那一行` → `task_id=t-0001 idem_key='settle-e8bc47fc4e9f'`、`相等=True`；
     - `[3b]` 被塞进快照的两行同键 → `verify` 报 `['schema_invalid', 'duplicate_idem_key']`；
       `[3c]` 历史行（没这个键）与空键行 → `verify` 报 `[]`（不误报）。
   - **残余未关闭（别读成关闭）**：**混合版本窗口仍在** —— 未升级进程写下的行**连这个键都没有**，
     它照样逃过字段级唯一性；提案 §3.3 / §3.1 的结论未变。
3. 未做存量数据清洗（本仓库 7 个 `usage_ledger.json` 全为空表，不需要清洗）。

---

### 2.3 ⭐ **该轮（第三轮）需要人批准的全部禁改区文件 —— 8 条，可直接照做**

> 这一节是给**签字的人**用的：每个文件给四样东西 —— 走查符号、这次改动的意图一句话、
> 批准前必须**人亲自跑**的命令（可照敲）、以及**当前 hash**。
> 符号名代替行号：行号在本仓库实测几十分钟就会漂（见 `.noai-paths` 那段的理由）。
>
> **该轮 AI 的改动一个字都没落在这 8 个文件里**（改的是 `capabilities.py` /
> `agent_e.py` / `tests/` / `docs/`，均不在禁改区）。这 8 条是**此前各轮累积**、
> **到该轮（2026-09-24）为止** `reviewers_total = 0` 的欠账；它们的 hash 与台账当时**一致**（无 `stale`）。（该轮读数以 `python scripts/noai_gate.py --check-approvals` 的输出为准 —— 那个数每签一个字就变。）
>
> 命令统一前缀（PowerShell，工作目录 `D:\Incubator\agentflow`）：
>
> ```powershell
> $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
> ```

| # | 文件 | 类别 | 类别理由（`.noai-paths` 逐字摘要） | 当前 sha256（前 12 位） |
|---|---|---|---|---|
| 1 | `src/agentflow/schema.py` | schema-migration / eval-criteria | `SCHEMA_VERSION` 与 `TABLES`：改它等于改磁盘格式契约；`EVAL_REQUIRED_FIELDS` 改它等于追溯性改写历史报告里每个数字的含义 | `12cd4170adff` |
| 2 | `src/agentflow/store.py` | schema-migration | `LOCK_ORDER` / `rebuild` / `alloc_id` / `_atomic_write`：四者任一错都是**数据毁灭级** | `57b11548009f` |
| 3 | `src/agentflow/verify.py` | auth-audit | `verify_all` 的一致性审计：判据本身被改宽 ⇒ 审计从此永远"通过" | `46197051a7ce` |
| 4 | `tools/release_all.py` | release-deploy | 一键发布检查的编排层 `main` / `build_steps` / `overall`：决定"跳过的步骤记 `unknown` 还是 `pass`" | `ba86d8db713a` |
| 5 | `src/agentflow/tools/verify_tools.py` | prover-bridge | `detect_verifier` 与 `check_formal`：桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印 | `a99bba5cdbc5` |
| 6 | `src/agentflow/extract.py` | solver-core | `extract_text` 及其 PDF 后端：抽取错一个字符，逐字引文回验会把**真**引文判成幻觉 | `5f2d85a5b505` |
| 7 | `pyproject.toml` | release-deploy | `[project]` 与 `[build-system]`：决定"发出去的到底是什么"，且版本号一旦发布无法撤回 | `970999dc1973` |
| 8 | `scripts/release_check.py` | release-deploy | 发布前的一键检查 `main` 与它跑的那八项：改宽它等于让"发出去的东西"不再受检 | `568b958e0054` |

**每条的四问四答**（走查符号 / 意图一句话 / 批准前必须人亲自跑的命令 / hash）：

**1. `src/agentflow/schema.py`**

- **逐行走查的符号**：`UsageEntry.idem_key`、`UsageEntry.validate`、`validate_table`、`SCHEMA_VERSION`、`TABLES["usage_ledger"]`、`EVAL_REQUIRED_FIELDS`。
- **这次改动的意图（一句话）**：给账本行加一个**有默认值**的幂等键字段，并在 `validate_table` 里加一条"非空键全表唯一"的断言 —— 纯附加，不递增 `SCHEMA_VERSION`。
- **批准前必须人亲自跑**：

  ```powershell
  python -c "import sys;sys.path.insert(0,'src');from agentflow import schema as S;print(repr(S.row_from_dict('usage_ledger',{'usage_id':'0000','scope':'search','at':'x','note':'n'}).idem_key));print(S.SCHEMA_VERSION)"
  ```

  期望：先打印 `''`（老行读回来是空串，不抛），再打印 `1`（版本未递增）。
  ```powershell
  python -m pytest tests/test_idem_key_writers.py tests/test_schema.py tests/test_fc05_contract.py -q
  ```

- **hash**：`12cd4170adffd8c15b6dabd3fcf1eb915a47da1503d4e502b18abd4e9035fe36`

**2. `src/agentflow/store.py`**

- **逐行走查的符号**：`Tx.insert_unique`、`LOCK_ORDER`、`Tx.alloc_id`、`rebuild`、`_atomic_write`。
- **这次改动的意图（一句话）**：新增 `Tx.insert_unique`（**纯新增方法**，未改任何既有行），把"先读后写"搬进调用方已持有的同一把锁里。
- **批准前必须人亲自跑**：

  ```powershell
  python -m pytest tests/test_store_alloc_guard.py tests/test_store_concurrency.py tests/test_usage_ledger_idem_key.py -q
  python D:\Incubator\temp\b1_rebuild_idem_key.py
  ```

  第二条该轮刚建：它真调 `Store.rebuild()` 跑三种情形并打印快照行（见 §2.4 待确认项 B1）。

- **hash**：`57b11548009f1ad8e744c58f50aa217b48da509e1c5ed7a19075aaf888325dfc`

**3. `src/agentflow/verify.py`**

- **逐行走查的符号**：`verify_all`（`usage_ledger` 那一段的 `seen_idem` 循环）、`Issue.code == "duplicate_idem_key"`。
- **这次改动的意图（一句话）**：**只新增**一条 `duplicate_idem_key` 检查（不改宽任何既有判据），因为重复记账的两行 `usage_id` 不同、既有 `duplicate_id` 永远不响。
- **批准前必须人亲自跑**：

  ```powershell
  python -m pytest tests/test_verify.py tests/test_verify_extended.py tests/test_idem_key_writers.py -q
  python D:\Incubator\temp\b2_idem_key_e2e.py
  ```

  第二条该轮刚建：它真跑一条端到端路径并**人为制造重复**，让 `verify` 报出 `duplicate_idem_key`（见 §2.4 待确认项 B2）。

- **hash**：`46197051a7ce05d3774ad554dc69e24773dbaf8a782d4e6932f37a2ca7643871`

**4. `tools/release_all.py`**

- **逐行走查的符号**：`main`（开头的 stdout/stderr `reconfigure`）、`run_step`、`classify`、`overall`、`build_steps`。
- **这次改动的意图（一句话）**：只把子进程输出与自身 stdout 的编码钉成 UTF-8，解掉一处 locale 相关的崩溃面；三态判定与 `--skip` 语义一个字没改。
- **批准前必须人亲自跑**：

  ```powershell
  python -m pytest tests/test_release_all.py -q
  python tools/release_all.py --only role-specs
  ```

  第二条期望：其余步骤记 `unknown`（不是 `pass`），无 `UnicodeEncodeError`。

- **hash**：`ba86d8db713a5a57c8f8542b4275d5a45566232929d3c36e03a48447b81752b6`

**5. `src/agentflow/tools/verify_tools.py`**

- **逐行走查的符号**：`detect_verifier`、`check_formal`、`code_hash`、`evidence_for`、`list_experiments`，以及 `verify.check_formal` 那个 `ToolSpec.returns` 字符串。
- **这次改动的意图（一句话）**：把桥接层接到 `formalgw.check_lean`（真跑检查器、八值受控词表折三态）；`detect_verifier` 的 `checked` 改为如实、`side_effect` 由 `none` 改 `read`。
- **批准前必须人亲自跑**：

  ```powershell
  python -m pytest tests/test_formalgw.py tests/test_tools_audit_fixes.py tests/test_tools_returns_declaration.py tests/test_check_formal_wiring.py -q
  python -m agentflow.tools.verify_tools
  ```

  第二条期望：无后端时如实返回 `no_backend`（不是 `verified=False`）。

- **hash**：`a99bba5cdbc5c0fee1dd1dbb5550317348313429bb7615efe51964732e32a9bb`
- ⚠️ 这一条在 §3.3 被登记为**越界改动**（两次），处置是"接受 + 待 2 名 reviewer"。

**6. `src/agentflow/extract.py`**

- **逐行走查的符号**：`extract_text`、PDF 页级抽取的三个后端 `_pdf_pages_fitz` / `_pdf_pages_pdfminer` / `_pdf_pages_pypdf2`，以及按 fitz → pdfminer → PyPDF2 降级的调度 `_pdf_pages`、编码探测与失败时的三态返回。
- **这次改动的意图（一句话）**：⚠️ **归属未定**（符号面与原型相同，改动全在函数体内）—— 只能逐行读。
- **批准前必须人亲自跑**：

  ```powershell
  python -m pytest tests/test_verify_quote_levels.py tests/test_f4_ocr_detect_reason.py -q
  ```

  > ⚠️ 更正说明（该轮）：原写的 `tests/test_extract.py` 已不存在（实测 exit 4 / file not found），
  > 所以上面这一行换成这两个文件 —— 该轮各覆盖 `extract_text` 6 / 5 处。
  > 那句更正单独成行是刻意的：判据会跳过"带更正记号的行"（更正说明逐字引用旧名字，
  > 那是"它曾经写错成什么"的记录，不是指路），把旧名字留在命令行上会让整条命令一起免检。

- **hash**：`5f2d85a5b5056891ef3fc30c2844306962d0a577dcde87a20e11ffd0d6c5a959`

**7. `pyproject.toml`**

- **逐行走查的符号**：`[project]`（`name` / `version` / `dependencies` / `requires-python`）、`[build-system]`、`[tool.pytest.ini_options]`（`testpaths` / `addopts`）。
- **这次改动的意图（一句话）**：包元数据 + pytest 配置单一化（`addopts` 默认排除 `network` 标记的测试）。
- **批准前必须人亲自跑**：

  ```powershell
  python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print(d['project']['name'],d['project']['version']);print(d['tool']['pytest']['ini_options']['addopts'])"
  python -m pytest -q --collect-only | Select-Object -Last 3
  ```

  期望：版本号与 `src/agentflow/__init__.py` 的 `__version__` 一致；`addopts` 里能看到 `-m 'not network'`。

- **hash**：`970999dc19730376e50180aec74c329e792e21be2d76c9b1ca6b42fb4602e11d`

**8. `scripts/release_check.py`**

- **逐行走查的符号**：`main`、八项检查各自的 `item_*`、`_VERDICT_EXIT_CODES`、第 2 项"模块没有自检块"的 `unknown` 分支。
- **这次改动的意图（一句话）**：八项检查 + 三档结论；第 2 项原本把"没有自检块"读成 `PASS`，已改为 `unknown`。
- **批准前必须人亲自跑**：

  ```powershell
  python scripts/release_check.py
  ```

  期望：退出码 0/1/2 三档可区分；有任何 `fail` ⇒ 1，只有 `unknown` ⇒ 2（**绝不把 `unknown` 当 `pass` 统计**）。

- **hash**：`568b958e005410d456ad0a7d5484fd6dc837c50a57ca04d24fffd2d439d94c31`

> **hash 的权威副本在 `.noai-approvals.json`**（本节只给前 12 位便于人眼比对）。
> 上面 8 条的 hash 与台账**当前一致**（`--check-approvals` 实测 `stale 0`），
> 差的只是 `reviewers`。取权威 hash：
> `python scripts/noai_gate.py --check-approvals --paths <文件> --json`
>
> ⚠️ **另外 6 个禁改区文件也存在同样的欠账**（`src/agentflow/dedup.py`、
> `src/agentflow/interactions.py`、`src/agentflow/providers.py`、
> `src/agentflow/quoteverify.py`、`src/agentflow/tools/__init__.py`、
> `src/agentflow/tools/base.py`，明细见 §2.1 第 3/5/6/7/10/11 条）。
> 它们不在该轮点名的 8 条里，但**同样是 0 名 reviewer**，一起签更省事。

### 2.4 🔏 签字流程（**人照着做，AI 不得代填**）

**第 0 步 —— 环境**（每条命令前跑一次）：

```powershell
Set-Location D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
```

**第 1 步 —— 确认"你没被 stale 骗"**（看到 `stale` 就先决定以哪一版为对象）：

```powershell
python scripts/noai_gate.py --check-consistency
python scripts/noai_gate.py --check-approvals --paths src/agentflow/schema.py src/agentflow/store.py src/agentflow/verify.py tools/release_all.py src/agentflow/tools/verify_tools.py src/agentflow/extract.py pyproject.toml scripts/release_check.py
```

- **看到什么算通过**：
  - 第 1 条 ⇒ `一致：.noai-paths 与 AGENTS.md 的清单逐条相同`，退出码 **0**；
  - 第 2 条 ⇒ **该轮的预期输出是 `[requires_human] required_approvals=2` + `8 条未获批准` + 退出码 1**。
    这是**正确**的：门在说"查过了，命中禁改区，还没人签"。逐条读 `⇒ [unapproved] insufficient_reviewers`，
    只要**没有** `stale`，就说明"台账记的那一版 == 盘上这一版"，可以放心走查。

**第 2 步 —— 逐行读 + 跑该条的命令**（用 §2.3 里那 8 条各自给出的命令）。
走查的是**语义**：这条判据对不对、这个取舍你能不能接受。**写"看过了"等于没看。**

**第 3 步 —— 签字**（每人一条，`scope` 必须具体到符号；**2 名** reviewer，`REQUIRED_APPROVALS_ON_HIT = 2`）：

```powershell
python scripts/noai_gate.py --approve src/agentflow/schema.py --reviewer "<姓名1>" --scope "UsageEntry.idem_key + UsageEntry.validate + validate_table 的唯一性断言 + SCHEMA_VERSION 未变" --note "<你的结论>"
python scripts/noai_gate.py --approve src/agentflow/schema.py --reviewer "<姓名2>" --scope "同上" --note "<你的结论>"
```

- **签字写在哪**：`python scripts/noai_gate.py --approve ...` 会把它写进
  **`.noai-approvals.json` 的 `reviewers` 数组**（每条记录含 `reviewer` / `at` / `scope` / `note`）。
  也可以**手工**编辑那个 JSON 的同名字段（结构见已有条目）。
  **本表 §6 的签名区是人读的镜像**，以台账为准。
- `--approve` 会**先断言该条 hash 与磁盘一致**，不一致就拒绝写入并退出 2 —— 它堵的是"批准 A 版、盘上是 B 版"。
- 签完再跑一次第 1 步第 2 条：8 条全部变成已批准 ⇒ 退出码 **0** `clean`。

**第 4 步 —— 纪律（这一条没有例外）**

- **AI 不得代填 `reviewers`。** 不许跑 `--approve`、不许手工往 JSON 里写姓名、
  不许写"走查结论"来代替人的结论。**批准是人的动作**；AI 填 `reviewers` 等于自己给自己发批准，
  那正是 FC-27 要防的形态。该轮 AI 对台账**一个字节都没写**（证据见 §2.5）。
- **`--baseline` 不是批准。** 它只写 hash，`reviewers` 永远是空数组。
  刷新 baseline 会**清空该条的批准语义**（因为它换了对象）。
- **台账不能批准自己。** `--check-approvals --paths .noai-approvals.json` 永远 `unapproved / ledger_self_approval`。

### 2.5 📌 该轮登记的**待确认项**（一句话结论 + 指向证据脚本）

这两条是该轮新做的实验结论：**人只需要确认结论、不需要重做实验**（想重做就跑脚本）。

| # | 待确认项 | 一句话结论 | 证据（可直接跑） | 写进了哪份文档 |
|---|---|---|---|---|
| **B1** | 回滚后 `rebuild` 到底会不会丢 `idem_key`？ | **`rebuild` 的真相是"快照 := 事件流折叠结果"**：① 事件带键 + 新代码 ⇒ **不丢**；② 事件不带而快照带 ⇒ **值变成 `''`**（快照不是重建来源）；③ 回滚到老代码 ⇒ 值丢、键名留下（机制是 `row_from_dict` 过滤未知键，**不是**"合并删字段" —— 对照行 `_diag` 证明未知键被原样保留）。**兜底与代码版本无关**：`note` 里的 `settle-`/`idem-` 标记是老字段，提案 B 的锁内判重与 `usage_ledger_audit.py` 始终有效 | `python D:\Incubator\temp\b1_rebuild_idem_key.py`（退出码 0 = 全部符合预期） | `docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md` **§4.2.1「实测更正」**（原文保留未删） |
| **B2** | 字段级唯一性是否**端到端**生效？ | **通**：真 `ModelGateway`（只注入传输层）→ `charge_reply` → `charge_once` → 账本行 `idem_key='idem-…'` 非空 → 人为制造重复 ⇒ 走事务则 `schema.validate_table` 当场抛"出现重复的幂等键"、直接改快照则 `verify_all` 报 `duplicate_idem_key`（而 `duplicate_id` **不响**）。第二条写入方 `Conductor.summon → _charge_and_settle` 同样落非空 `settle-` 键、同样幂等。**没跑的一环**：真实网络那次调用（环境无 `AGENTFLOW_MODEL_API_KEY`） | `python D:\Incubator\temp\b2_idem_key_e2e.py`（退出码 0 = 全部通过） | 本表 §2.3 第 2/3 条的走查命令；结论也已由 `tests/test_idem_key_writers.py` 长期守住 |

> 两条实验脚本都在 `D:\Incubator\temp\`（**不是仓库内**，所以不产生新的禁改区命中）。
> 它们与 §2.3 第 1/2 条**同源**：B1 是 `store.rebuild` 的行为、B2 是 `verify`+`schema` 的行为。

### 2.6 ✅ 该轮"台账未被写"的实测证据（`reviewers` 元素总数为 0）

```text
python D:\Incubator\temp\ledger_check.py
  台账里的 `"reviewers": [` 逐字命中次数 = 14
  条目数 = 14
  所有条目 reviewers 数组的**元素总数** reviewers_total = 0
  有内容的 reviewers 条目 = 无（全部为空）
  结论 = 台账未被写（reviewers 元素总数 0）        [exit 0]
```

> ⚠️ **口径说明（别被字面数骗）**：`"reviewers": [` 的逐字命中数是 **14**，
> 因为台账每个条目都有一个 `reviewers` 键，而它们**全是空数组**（上表逐字列出了 14 个 `[]`）。
> **该为 0 的是"元素总数"** —— **该轮实测** `reviewers_total = 0`，
> `--check-approvals` 也仍然逐条报 `insufficient_reviewers`（见 §2.4 第 1 步）。
> 台账文件 mtime **在该轮（2026-09-24/25）观测时为 2026-09-25 21:27:01**（该轮 AI 未写它一个字节）；此后它会随任何一次 `--baseline` / `--approve` 变动 ⇒ 该轮值以 `Get-Item .noai-approvals.json`（或`python temp\_ledger_snapshot.py`）的读数为准。

### 2.7 ❌ 该轮**刻意没做**的事（说明理由，不要读成遗漏）

**禁改区里那 430 处注释装饰（R009）一处都没清。** R009 该轮复跑实测（逐字）：

```text
info R009  禁改区 13 个文件里仍有 430 处装饰（src/agentflow/schema.py=133、
           src/agentflow/interactions.py=55、src/agentflow/verify.py=48、
           src/agentflow/tools/verify_tools.py=35、tools/release_all.py=28…）
           —— 这些文件按 FC-27 只能由人改，本项不计入判据
```

> 数字口径：该轮实测是 **430**（`python scripts/lint_rules.py`）。立项前普查记的是 414、
> 上一轮的报告写的是"约 423" —— **三个数都是各自时点的真实读数**，差异来自这几轮里
> 禁改区文件本身被改过（新增注释也带星号）。**不要在别处引用一个固定数字**：以现场跑出来的为准。

**为什么不做**（三条，任一条都足够）：

1. **它会让已登记的 hash 全部作废。** 那 13 个文件里每一个的 hash 都在
   `.noai-approvals.json` 里钉着；为了清星号而改它们，等于**再制造 13 条新的未批准欠账**
   （该轮 §2.3 那 8 条就是这种欠账，已经很重了）。
2. **它会给人一大片无功能 churn。** 清清装饰不改变任何行为，却会让人**逐行走查**这些
   风险最高的文件（`store.py` 的加锁顺序、`extract.py` 的抽取主通道…）。把人的注意力
   花在星号上是净损失 —— 而"人只做核验签字"正是该轮的意图。
3. **R009 在禁改区内只报一条汇总 `info`，不计入判据**（`scripts/lint_rules.py` 的设计：
   区内只有人能改，报 `error` 等于造一条永远红的灯）。所以它**不阻塞任何门**。

**因此该轮的正确动作是"什么都不做 + 在这里说明为什么"**，而不是顺手清一遍。
若人决定要清，那是**人的**改动，需要重新 `--baseline` + 2 名 reviewer 签字。


### 2.8 ⏸ **临时开放（suspension）期：2026-09-25 起** —— 顺序暂停，**登记照做，签字后补**

> **授权原文（逐字）**：所有者 —— "禁改区里的问题有点多，先开放吧，做得足够好了再封闭回去。"
> **完整记录（授权 / 开放期六条底线 / 八条复闭判据 / 风险 / 数字口径）**：
> `docs/NOAI-SUSPENSION-2026-09-25.md`（登记为 `docs/PROPOSALS.md` 的 **`P-24`**）。

**这一小节只回答"本登记表在开放期怎么改"三个问题**：

1. **暂停的是顺序**：开放期内 AI **可以直接改**命中 `.noai-paths` 的文件，
   **不再先等人编写 / 等人逐行走查**。**清单（`.noai-paths` / `AGENTS.md`）一字不动**
   ⇒ `python scripts/noai_gate.py --check-consistency` 必须继续退出码 **0**。
2. **登记照做**：**开放期每次禁改区改动仍然登记 hash** ——
   改完立刻 `python scripts/noai_gate.py --baseline --paths <被改文件…>`
   （**只写 `sha256`，`reviewers` 永远是空数组**），并在 §2 留一行
   （改了什么 / 备份在哪 / 新的 hash）。**不登记 = 这次改动不可追溯**（本仓库没有 git）。
   ⇒ 台账在开放期会持续报 `stale` 或 `insufficient_reviewers`，
   **那两种都是"正确的显示"，不是故障**：门在如实说"这一版还没有人签"。
3. **签字后补（复闭时一次性补）**：开放期**不要求**当场签；
   **复闭的那一刻**要求 `--check-approvals --paths <该轮 14 条>` ⇒ **`14 28`**
   （14 条 × 2 名 reviewer，署名是**人**）。§6 的批准签名区因此会**长期为空**——
   **空栏在本表里的含义只有一个："还没签"，不是"没问题"。**

**开放期仍然不许做的事（与本表既有纪律一字不差）**：

- **AI 不许代填 `reviewers`**（不许跑 `--approve`、不许手写 JSON、不许写"走查结论"代替人的结论）；
- **`--baseline` 不是批准**，且它换对象会**清空该条已有的批准语义**；
- **台账不能批准自己**（`ledger_self_approval` 永远有效）；
- **不可逆操作**（`SCHEMA_VERSION` / `LOCK_ORDER` / `_atomic_write` / `id 分配` /
  删受控词表取值 / 迁移）在开放期**仍要求**：回滚方案 + 备份（`D:\Incubator\temp\`，命名含时间戳）
  + 一次自检证据，**缺任一项不得动手**（详见记录的 §2.5）。

**与本表 §5「做不到的事」的关系**：开放期**加重**了第 4 条
（"`unknown(2)` 需要人真的停下来"）—— 因为现在连"先走查再改"这道顺序也没有了。
唯一的新增缓冲是"**签字被允许迟到**"，而**迟到的代价**是复闭时要一次补齐
（`draft/22` §12.4 的口径：该轮 14 条存量 = 14–42 人时；开放期每多改一个文件就再多一份）。

---

## 3. 复核人怎么走（**逐行走查**的操作流程）

### 3.1 一次走查 =

1. **确认你看的是哪一版。** 先跑 `python scripts/noai_gate.py --check-approvals --paths <文件>`：
   - 若报 `stale`，说明**台账里记的那一版和盘上这一版不是同一版** —— 先决定要以哪一版为复核对象，必要时重跑 `--baseline`（这会**清空该条的批准语义**，因为它换了对象）。
2. **读文件**，对着 §2.1 该条的「复核要点」逐条确认。走查的是**语义**（这条判据对不对、这个取舍你能不能接受），不是格式。
3. **签字**：
   ```text
   python scripts/noai_gate.py --approve src/agentflow/verify.py \
       --reviewer "张三" --scope "verify_all + number_without_eval_scope + eval: 解析（全文）" \
       --note "判据未被放宽；新门确实挂在 verify_all 返回里；unknown/not_applicable 与 pass 分得开"
   ```
   `scope` **必须具体到符号或行区间**。写"看过了"等于没看 —— 清单理由里"理由也必须一致"是同一个道理：
   **只在一边写理由，等价于另一边没有理由。**
4. `--approve` 会**先断言该条的 hash 与磁盘一致**，不一致就拒绝写入并退出 2。这不是刁难，它堵的是"批准 A 版、盘上是 B 版"。

### 3.2 需要几名 reviewer

**2 名**（`scripts/noai_gate.py::REQUIRED_APPROVALS_ON_HIT = 2`，FC-27 写死）。
为什么不是 1：**1 名 reviewer 与"作者自己再看一遍"在结构上无法区分**；2 名才有互相独立的复核。
为什么不做成可配置：**可配置的准入门槛等于没有门槛**（下一个人会把它改成 0）。

### 3.3 关于"越界改动"的处置（本条已发生一次）

第 12 条（`tools/verify_tools.py`）是一次**越界改动**：任务范围外的文件被改了。处置**不是**回滚 ——
回滚会丢掉一个可能正确的修复，而且它已经被别的代码依赖。处置是：
**把它登记进台账、标为 `authored: "ai-agent"`、`reviewers: []`，然后由人决定接受还是重写。**
本项目**不许**用"补一个 `# noqa`"或"补一句注释说它合规"来消掉这类命中 —— 那是共谋。

---

## 4. 待办（**给人办的，AI 不许代办**）

| # | 待办 | 为什么必须人办 |
|---|---|---|
| T1 | 为 §2 的 **14** 条逐条填 `reviewers`（每 2 名、带 `scope`） | 批准是人的动作。AI 填 `reviewers` 等于自己给自己发批准 |
| T2 | 决定 `scripts/release_check.py::item_noai` 是否改接 `.noai-approvals.json`（现在它用 `--paths`，命中即 `fail`） | 它是禁改区文件本身；且这是**放宽还是收紧发布门**的决策 |
| T3 | 走查第 4 条 `extract.py` 与第 9 条 `store.py`（**归属未定**的两条） | 这两条我**无法从仓库判定改了什么**；只能逐行读 |
| T4 | 给第 8 条 `schema.py` 确认 `SCHEMA_VERSION` 是否该递增 | 磁盘格式契约；判错会让老数据被按新契约读 |
| T5 | 处理 `docs/SCHEMA-MIGRATION-PROPOSAL-claims.md`（G/H 升级所需的 `documents.claims` 新字段） | 同属 schema-migration 类 |
| T6 | 第 13 条之外：`verify.py` 与 `interactions.py` 的改动的**后续**是否也需要 `CONTRACT_VERSION` 递增 | 跨模块契约版本规则由人定 |
| T7 | 把工具层的 **`tools/verify_tools.check_formal`（禁改区）接到 `src/agentflow/formalgw.py`** —— 现在两处是**断开的**：`formalgw.check_lean` 已能真跑 Lean 并给出四类结论（见 `draft/23-收官报告.md` §2 的真实正控/负控），而工具层给 `script_path` 时**仍返回 `checked=False` + `reason="not_implemented"`**（`tools/verify_tools.py:160-221`；全文**零处**提到 `formalgw`）。**待人工**：接线点本身落在 `prover-bridge` 禁改区（清单理由逐字："桥接层说谎 ⇒ proof 级证据是假的，而报告照样打印"），只能由人编写或人逐行走查（+2 名 reviewer）。**注意口径**：`check_formal` 的 `proof` 路径在取得人工批准前不得主张为可用（见 §2.1 第 12 条） | 禁改区（FC-27） |

---

## 5. ⚠️ 这份登记表**做不到**的事（结构性限制，必须一起读）

1. **它不是 git。** 没有"改动集"这个客观事实：14 条里**有 2 条的归属我判定不了**（§2 标了"归属未定"），
   另有 5 条**符号面与原型完全相同**、改动全在函数体内部，**符号面差异查不出它们被改了什么**。
   `--baseline` 之后能机械抓到的是**从此往后的漂移**，抓不到**已经发生的**那次改动内容。
2. **hash 一致 ≠ 实现正确。** 台账证明的是"这一版就是被批准的那一版"，**不证明它是对的**。
   这是两类不同的问题，不要因为门变绿就跳过语义走查。
3. **它不保护清单之外的文件。** `.noai-paths` 该轮只有 **18** 条 glob（其中 1 条是台账自身）；
   清单漏一个文件，门不会报错，只会不命中（**静默的假阴性**）。清单的完备性本身要人定期复查。
4. **`unknown(2)` 需要人真的停下来。** 门会正确报 `unknown`，但**没有任何机制阻止人在 `unknown` 状态下继续** ——
   该轮的 14 个文件就是在 `--git` 恒为 `unknown` 的情况下被改的。要让 `unknown` 真的拦人，
   必须把它接到 CI 的**阻断**判决上。**当前状态（实测）**：
   `scripts/release_check.py` 第 6 项走的仍是旧的 `--paths`（**命中即 `fail`**），
   **还没有**接上 `--check-approvals`，也没有把退出码 2 计入 `fail`。
   也就是说 —— **这套台账现在是"可执行但尚未接线"的状态**（跟 `noai_gate.py` 当初一样）。
   要接线见 `docs/PROPOSALS.md` 的 **P-3**（那是**放宽**发布门，必须由人决定）。
5. **`--approve` 拦不住一个不诚实的人。** 它是给诚实流程用的：它记录"谁、什么时候、走了哪些行"，
   但它**无法验证**签名者真的读了。它的实际作用是让"没走查"变成一件**需要刻意说谎**才能做到的事 ——
   这比"忘记走查"高一个门槛，但不是密码学保证。

---

## 6. 批准签名区

> 每次 `--approve` 会往 `.noai-approvals.json` 里追加一条结构化记录。
> 下面是**人读的镜像**，供评审会与发布说明引用；**以台账为准**。

| 文件 | hash（前 12 位） | reviewer 1 | reviewer 2 | 日期 | 结论 |
|---|---|---|---|---|---|
| `pyproject.toml` | — | | | | 待走查 |
| `scripts/release_check.py` | — | | | | 待走查 |
| `src/agentflow/dedup.py` | — | | | | 待走查 |
| `src/agentflow/extract.py` | — | | | | 待走查（**归属未定**） |
| `src/agentflow/interactions.py` | — | | | | 待走查 |
| `src/agentflow/providers.py` | — | | | | 待走查 |
| `src/agentflow/quoteverify.py` | — | | | | 待走查（该轮未改动，仅登记基线） |
| `src/agentflow/schema.py` | — | | | | 待走查（**该轮又改**：提案 A 的 `idem_key`，走查符号见 §2.2.2 A） |
| `src/agentflow/store.py` | — | | | | 待走查（**归属未定**；**该轮又改**：`Tx.insert_unique`，见 §2.2.2 B） |
| `src/agentflow/tools/__init__.py` | — | | | | 待走查 |
| `src/agentflow/tools/base.py` | — | | | | 待走查 |
| `src/agentflow/tools/verify_tools.py` | — | | | | 待走查（**越界改动**，见 §3.3） |
| `src/agentflow/verify.py` | — | | | | 待走查（**该轮又改**：`duplicate_idem_key`，见 §2.2.2 C） |
| `tools/release_all.py` | — | | | | 待走查（**该轮又改**：输出编码与 locale 解耦，见 §2.2.2 D） |

**该轮的四行都已被 `--baseline` 刷新过 hash**（2026-09-25；台账里 `reviewers` **当时**为 0）。
上一版 hash 已失效：`schema.py` 3ea156cc3f75 → 12cd4170adff、`store.py` e533cb5b506c → 57b11548009f、
`verify.py` 06e9d7677875 → 46197051a7ce、`release_all.py` 218a4e1fec04 → ba86d8db713a。
**登记不等于批准** —— 这四行的批准栏在下面全都是空的。

**hash 与 `reviewers` 的权威副本在 `.noai-approvals.json`。** 本节不复制 hash，
因为同一份 hash 两处落地**必然**会分叉（两处不一致时，读本表的人与读台账的门
会依据不同的版本行事，而**没有任何测试会因此变红**）。要拿当前 hash：

```text
python scripts/noai_gate.py --check-approvals --paths src/agentflow/verify.py --json
```

**台账建立时的实测状态**（2026-09-24，由 `--baseline` 写入；**该轮读数，不是当前值**）：

| 事实 | 值 |
|---|---|
| 条目数 | **13**（**该轮 2026-09-24 读数**；当前值见 `DEVELOPMENT.md` §1.5） |
| hash 与磁盘一致 | **13 / 13**（该轮 `stale 0`） |
| `reviewers_total` | **0**（**该轮 2026-09-24 读数**）—— 批准是**人**的动作，AI 一个签名都没填 |
| `--check-approvals --paths <该轮 13 条>` 的结论 | `[requires_human] required_approvals=2`，退出码 **1**，该轮 13 条全部 `unapproved / insufficient_reviewers` |
| 台账自指 | `--check-approvals --paths .noai-approvals.json` ⇒ `unapproved / ledger_self_approval`（**永远**，与 hash 和人数无关） |

---

## 7. 本表的维护规则（**历史档案版**）

> 本节按上面的档案声明改过：本文件**不再维护当前值**。同一批数量的当前值在
> `README.md` §6.2 / `DEVELOPMENT.md` §1.5，那两处由 `tests/test_release_all.py` 的
> 读数对账判据钉住。要给新的一轮留记录，**新开一节**写清日期与复跑命令，
> **不要改写本节的旧数字** —— 改写旧数字等于把这份档案伪装成一份"在维护"的当前值文档，
> 而没有任何判据会去核它。

1. **任何一次命中禁改区的改动都必须留下一条记录**；当前的落点是 `DEVELOPMENT.md` §1.5
   与 `.noai-approvals.json`（`--baseline` / `--approve`）。本表 §2 是 2026-09-24/25 该轮的快照，
   **不再追加**；§6 的批准栏同样不再维护（权威副本在台账里）。
   hash 变了而批准栏没重置，是这一族最危险的状态 —— 它会让一次**未走查**的改动看起来已走查。
2. **本文件不再维护当前值。** §0 与正文里的实测数字是 2026-09-24/25 该轮的读数，
   **不随改动更新**（这正是"历史档案"的含义）。原规则写的"§0 的实测数字随每次改动更新"
   已作废：它要求更新、正文不更新，两者互相打脸，而没有任何判据会因此变红。
3. **§5「做不到的事」不许删。** 一份只说自己能做什么的合规文档，是这份文档最坏的形态；
   本项目 `02-…md`/`07-…md` 的教训逐字是 *"多数脚本不设退出码，于是『未报错』被误读为『无问题』"* ——
   本表对应的失败形态是 *"登记表在，于是被误读为已走查"*。

---

## 8. 2026-09-29 这一轮（`draft/28` §163–§174 那一批）—— **新开一节，不改上面任何旧数字**

> 按 §7 的维护规则办：这一轮的记录**新开一节**，日期 + 复跑命令 + 当次读数，
> 旧节的数字一个都不动。

**这一轮的性质**：AI 代写 + `--baseline` 只做登记（`reviewers` 一律 0），
窗口见 `docs/NOAI-SUSPENSION-2026-09-28.md`。**登记 ≠ 批准**；下面每一条都要人逐行走查。

| # | 路径 | 类别 | 这一轮改了什么（走查要点） | 台账（当次） |
|---:|---|---|---|---|
| 1 | `src/agentflow/schema.py` | `schema-migration` + `eval-criteria` | `REFUSAL_REASONS` 加 `invalid_params`（参数门不再把参数错误报成 `unknown_action`） | `--baseline` 登记，`reviewers=0` |
| 2 | `src/agentflow/providers.py` | `solver-core` + `provenance-dedup` | `_openalex_pdf_url` 标 `\|landing_same_as_pdf`（"落地页当直链"那类假 ok 的第①层） | 同上 |
| 3 | `src/agentflow/capabilities.py` | `auth-audit` | **新增导入期第 [9] 条**：两层参数**类型**对账（含 `array` 的 `items.type`）+ `G.register_dependency.page_range` 声明由 `array<string>` 改 `array<integer>` | 同上 |
| 4 | `src/agentflow/verify.py` | `auth-audit` | 签名读数拆名：`signature_problems` / `accepted_documents_checked`（旧键 `signatures` 删除）+ `SIGNABLE_STATUS` 交叉断言 | 同上 |
| 5 | `src/agentflow/signatures.py` | （**不在清单内**） | 新增 `SIGNABLE_STATUS` 与 `signed_revision`；规范哈希改调 `canonical` | 无需登记 |
| 6 | `tools/vocab_census.py` | `auth-audit` | 取词表面拓宽（`_FORMS` / 定义文件列表 / 类体默认值算产出点）+ **17 条预留登记**（7 条"由数据产出" + 10 条 `R-64`） | `--baseline`，`reviewers=0` |
| 7 | `scripts/noai_gate.py` | `auth-audit` | 新增 `--check-canonical`（规范哈希口径一致性）；`check_paths` 补只读的台账 `stale` 对账 | 同上 |

**当次读数**（复跑命令逐条给出；`stale` 与"未获批准"都是**当次**数）：

```text
$ python -c "import json;d=json.load(open('.noai-approvals.json',encoding='utf-8'));print('\n'.join(e['path'] for e in d['entries']))" `
  | python scripts/noai_gate.py --stdin --check-approvals
requires_human：命中 23 条禁改区路径，其中 **10 条未获批准**
  （approved 13 条、insufficient_reviewers 9 条、ledger_self_approval 1 条）
  ⇒ 必须由人编写或人逐行走查，并需要 2 名 reviewer 批准。  EXIT=1

$ python scripts/noai_gate.py --check-canonical
[canonical] consistent：同一份口径：同一载荷的哈希逐字相等（门侧 …aa5785ee52ba3e46）  EXIT=0

$ python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同                              EXIT=0
```

**两条"别误读"的话**（都踩过）：

1. `stale` 是 **0** —— 但那是**门的口径**（`.noai-approvals.json` 自指那一条会先短路成
   `ledger_self_approval`，所以它不参与 `stale` 计数）。拿一个"裸 hash 相减"的脚本去量，
   会得到"stale 1（台账自指）"，那是**量法不同**，不是矛盾（见 `draft/28` §174 的记录）。
2. `approved 13` 那 13 条是**更早几轮**人走过的（`tools/release_all.py` 等），
   **不是这一轮的**。这一轮 7 条全部 `reviewers=0`。

---

## 9. 2026-09-29 第二批（`draft/28` §175–§176）—— 同样**新开一节**，上面任何旧数字都不动

> 按 §7 的维护规则办：日期 + 复跑命令 + 当次读数。

**这一批的性质**：与前一批同族（AI 代写 + `--baseline` 只登记），但**这一批有明确的人授权**：
用户逐字授权改 `store.py`（"把 `store.py` 和其它一些改好，这轮我授权你改，当然改后必须仔细测试"）。
**授权改变的是"谁许可"，不改变 FC-27 的要求** —— 仍然必须由人逐行走查 +
2 名 reviewer；`--baseline` 只登记，`reviewers` 一律 0。

| # | 路径 | 类别 | 这一批改了什么（走查要点） | 台账（当次） |
|---:|---|---|---|---|
| 1 | `src/agentflow/store.py` | `schema-migration` | ① `Tx.delete`：新写方法，追加 `op="delete"` 事件（带**被删的整行** + `key`），返回被删行 / `None`；② `Tx._record` 加 `op=`/`extra=`（**事件长什么样只在这一处定义**，`upsert` 事件逐字节不变）；③ `rebuild()` 重放 delete（只按 `key`、不校验 `row`）+ 两个新读数 `deletes_replayed` / `unknown_ops` + 组行 `dict.fromkeys` 去重；④ `Store.init` 的 `R-32` fail-closed 守卫（白名单 `_WORKSPACE_ROOT_ENTRIES`） | `--baseline` 登记（最终版 `sha256 a6216da888d5…`），`reviewers=0` |
| 2 | `src/agentflow/tools/table_tools.py` | （**不在清单内**） | `table_delete` 改走 `tx.delete`（原来就地改 `tx.rows`）；删掉 `_mark_dirty` helper；"删到 `None`"那一格改成响亮失败 | 无需登记 |

**走查要点**（读数与正控/负控全在 `draft/28` §176）：

1. `Tx.delete` 的三个取舍：整行入日志（审计面）/ 重放只按 `key`（历史行可能不符合当前 schema）/
   `deletes_replayed` 与 `applied` 分开报（否则"重建后比删之前多"这件事又被盖住）。
2. `Store.init` 判据的**宽窄两侧都实测过一次**：窄的反面是事故 B（人的文件夹被补出整套 `data/`），
   宽的反面是我第一版的**误拦**（工作区根里有 `projects/` 被拒，`tests/test_conductor_tools.py` 当场变红）。
   这类判据改一个词就是"数据毁灭"与"功能报废"之间的选择，请逐字读 §176.3。
3. `rebuild()` 的兼容方向：新代码读旧日志 OK（没有 `key` 就从 `row` 取，再取不到 `skipped += 1`）；
   旧代码读新日志会把 `op="delete"` 当"读不懂的 op"**静默跳过** ⇒ 删除复活（§176.8 第 4 条）。

**当次读数**：

```text
$ python -c "import json;d=json.load(open('.noai-approvals.json',encoding='utf-8'));print('\n'.join(e['path'] for e in d['entries']))" `
  | python scripts/noai_gate.py --stdin --check-approvals
requires_human：命中 23 条禁改区路径，其中 **10 条未获批准**
  （approved 13 条、insufficient_reviewers 9 条、ledger_self_approval 1 条）  EXIT=1

$ python scripts/noai_gate.py --git
requires_human：2 条改动落在禁改区（agentflow/.noai-approvals.json、agentflow/src/agentflow/store.py）  EXIT=1

$ python scripts/noai_gate.py --check-canonical
[canonical] consistent：同一份口径：同一载荷的哈希逐字相等（门侧 …aa5785ee52ba3e46）  EXIT=0

$ python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同  EXIT=0
```

**两条"别误读"的话**（都踩过）：

1. `--git` 那 2 条里有一条是**台账自己** —— 因为 `--baseline` 刚写过它。
   它的理由码永远是 `ledger_self_approval`（台账不能批准自己），与 hash 是否一致、
   `reviewers` 有几个**都无关**；这不表示"这一批动了台账本体"。
2. `store.py` 那一条是 `insufficient_reviewers`，**不是** `hash_mismatch` ——
   台账里的哈希与盘上内容**一致**（我改完误拦之后重新登记过一次）。
   "已登记"不等于"有人看过"：`reviewers=0` 意味着**一次逐行走查都还没有发生**。

