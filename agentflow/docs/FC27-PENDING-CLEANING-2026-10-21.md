# FC-27 待批清单 · 代码清洁批次（2026-10-21）

> 本批全部改动**只碰注释与 docstring**（外加一处提示词的转义修复）。"代码一个字节没动"有机器证据，见 §3。
> 上一批（功能改动：名册静址、V 签名归属、概念闸、洗格式面两段式）见 `docs/FC27-PENDING-2026-10-21.md`。

## 1. 机器读数（`scripts/noai_gate.py --git --since cdcb843`）

```
[requires_human] required_approvals=2      —— 28 条改动落在禁改区
类别：auth-audit / eval-criteria / prover-bridge / release-deploy / schema-migration / solver-core
```

## 2. 命中清单（28 条）

| 文件 | 本批动了什么 |
|---|---|
| `scripts/lint_rules.py` | 注释块 + docstring（含 `rule_R010`/`rule_R011`/`rule_R009`） |
| `scripts/noai_gate.py` | 注释块 + docstring；**ZWSP 有意，保持原字节** |
| `src/agentflow/agentspec.py` | 模块 docstring + 注释 |
| `src/agentflow/capabilities.py` | 注释 16 块 + 模块 docstring |
| `src/agentflow/extract.py` | 注释（`**`→裸文本） |
| `src/agentflow/interactions.py` | 注释（`**`→裸文本） |
| `src/agentflow/schema.py` | 注释 15 块（含 44 行那块） |
| `src/agentflow/specs/{a,b,c,d,e,f,g,h,m,v}.py` | 注释块（a/b/e/h/m）＋ docstring 80 段（只删说理，`policy`/`boundary`/`duty` 一个字节未动） |
| `src/agentflow/store.py` | 注释 2 块 + 12 个 docstring（含 `rebuild 55→26`） |
| `src/agentflow/tools/__init__.py` | 注释 5 块 |
| `src/agentflow/tools/base.py` | 注释 10 块 + docstring 13 段（含恢复契约句「只有 `call` 走这里。」） |
| `src/agentflow/tools/verify_tools.py` | 注释 2 块 + `check_formal 183→73` |
| `src/agentflow/verify.py` | 注释 7 块（含 47 行那块）+ docstring |
| `tests/golden/agent_surface_snapshot.json` | **重冻**（p179：修掉提示词里被转义吃掉的 `\brief\ / \name\ / \reuse\`） |
| `tools/coverage_zero_test.py` | 注释 2 块 + 模块 docstring `149→18` |
| `tools/release_all.py` | 注释 1 块（`R.__doc__` / `R.build_steps.__doc__` **未动**） |
| `tools/run_each_test_file.py` | 注释 1 块 + docstring |
| `tools/vocab_census.py` | 注释 1 块 + 模块 docstring `46→19` |

## 3. 人审时可以直接采信的证据（每条可再生）

| 证据 | 怎么复现 |
|---|---|
| **去 docstring 后 AST 完全相同** | 对每个改动文件：`ast.parse` 后把 `body[0]` 的 `Expr(Constant(str))` 换成 `Expr(Constant(""))`，再比 `ast.dump` |
| **非 docstring 字符串字面量逐字节相同** | 同上取全部 `ast.Constant` 字符串节点逐个比（本批累计比对 3 万+ 条） |
| **整仓 `\r\n` = 0** | `git ls-files '*.py'` 742 个文件逐个 `read_bytes().count(b"\r\n")`（**别用 PowerShell 管道数**） |
| **注释改动只删不增** | 对每行改动做子序列校验：删掉的字符 ⊆ {`*`, 空格, emoji} |
| **指针零丢失** | `scripts/docstring_patch.py verify <file>` 的 `dropped pointers` / `first line changed` 两栏 |

## 4. 本批唯一的"内容性"改动

`src/agentflow/agent_prompts.py` 的 `\brief\ / \name\ / \reuse\` 原先被 `\b \n \r` 当转义吃掉（渲染成控制字符），
已修 ⇒ **`p178 → p179`**，十格摘要重算、`tests/golden/agent_surface_snapshot.json` 重冻、缓存重落。
这一条**不属于 FC-27**（`agent_prompts.py` 不在清单里），但它改了 golden 一份，故一并登记。

## 5. 人审之后要做的两件

1. `python scripts/noai_gate.py --approve <file> --reviewers A,B`：台账现在是 **stale**（旧批准钉的是清洁前的 sha），必须按新 sha 重签。
2. 签完后 `python scripts/noai_gate.py --git --since cdcb843` 应回到 `[clean]`（exit 0）；仍命中就说明清单与盘上不一致，别当成"没问题"。

## 6. 清洁批次顺带修掉的 6 处真缺陷（已单独提交 `ef7145e`）

1. `tools/base.py::_callable_for` 的契约句被压成单字「」」⇒ 恢复「只有 `call` 走这里。」
2. `tests/test_r4_roles_surface.py` 钉的是那对星号 ⇒ 改成钉裸文本（装饰不是契约）
3. `litstage.py` 是盘上多出的顶层模块、未登记 ⇒ 登记进 `_AGENTFLOW_TOP_LEVEL_MODULES`
4. `DEVELOPMENT-SPEC.md` 的 `lint_rules_strict_warning` 73 ⇒ 实测 74
5. `prompt_cache_warm.json` 里 secretary 只有 `pass=1` ⇒ 重落（判据要求两趟都在）
6. 我自己引入的一处 `\x08`（写 `\bibitem` 时的转义事故，正是那条判据在讲的事）

## 7. 仍未修的"前存缺陷"（清洁前就红，已逐条在 `cdcb843` 上复现）

```
test_the_wash_is_proposed_not_applied   3 failed   ← 洗格式面接受态只产 1 步
test_tools_branch_key_sets              1 failed   ← ok(...) 分布 12→13
test_tools_returns_declaration          1 failed   ← conductor.escalate 少声明 addressing/roster_unavailable
test_forced_notify                      2 failed   ← tasks 多一条 action='message'
test_id_width                           1 failed   ← secretary.py:181 的四位号
```

⇒ 这些属功能缺陷批次，不在清洁范围。
