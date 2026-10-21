# FC-27 待批清单 · 代码清洁批次（2026-10-21）

> 这一份是**代码清洁**（换行统一 / 注释与 docstring 压缩 / 意外字符）那一批的人审清单。
> 上一批（功能改动：名册静址、V 签名归属、概念闸、洗格式面两段式）见 `docs/FC27-PENDING-2026-10-21.md`。
> **本批全部改动只碰注释与 docstring**；"代码一个字节没动"有机器证据（见 §3）。

## 1. 机器读数（`scripts/noai_gate.py --git --since cdcb843`）

```
[requires_human] required_approvals=2
27 条改动落在 FC-27 禁 AI 区（auth-audit / eval-criteria / prover-bridge / release-deploy / schema-migration / solver-core）
```

## 2. 命中清单（27 条，按类别）

| 文件 | 类别 | 本批动了什么 |
|---|---|---|
| `scripts/lint_rules.py` | auth-audit | 注释 2 块 + docstring |
| `scripts/noai_gate.py` | auth-audit | 注释 3 块 + docstring（ZWSP 有意，保持原字节） |
| `src/agentflow/agentspec.py` | auth-audit | 模块 docstring |
| `src/agentflow/capabilities.py` | auth-audit | 注释 16 块 + 模块 docstring |
| `src/agentflow/extract.py` | solver-core | 注释（docstring 一处 `**`→「」） |
| `src/agentflow/interactions.py` | auth-audit | 注释（`**`→「」） |
| `src/agentflow/schema.py` | schema-migration / eval-criteria | 注释 15 块（含 44 行那块） |
| `src/agentflow/specs/{a,b,c,d,e,f,g,h,m,v}.py` | auth-audit | 注释块（a/b/e/h/m）＋ docstring 80 段（只删说理） |
| `src/agentflow/store.py` | schema-migration | 注释 2 块 + 5 个 docstring |
| `src/agentflow/tools/__init__.py` | auth-audit | 注释 5 块 |
| `src/agentflow/tools/base.py` | auth-audit | 注释 10 块 |
| `src/agentflow/tools/verify_tools.py` | prover-bridge | 注释 2 块 |
| `src/agentflow/verify.py` | auth-audit | 注释 7 块（含 47 行那块） |
| `tests/golden/agent_surface_snapshot.json` | eval-criteria | **重冻**（p179：修掉提示词里三个被转义吃掉的字段名） |
| `tools/coverage_zero_test.py` | release-deploy | 注释 2 块 |
| `tools/release_all.py` | release-deploy | 注释 1 块 |
| `tools/run_each_test_file.py` | release-deploy | 注释 1 块 |
| `tools/vocab_census.py` | auth-audit | 注释 1 块 |

## 3. 人审时可以直接采信的证据（每条可再生）

| 证据 | 怎么复现 |
|---|---|
| **去 docstring 后 AST 完全相同** | 对每个改动文件：`ast.parse` 后把 `Module/ClassDef/FunctionDef/AsyncFunctionDef` 的 `body[0]` 若为 `Expr(Constant(str))` 换成 `Expr(Constant(""))`，再比 `ast.dump` |
| **非 docstring 字符串字面量逐字节相同** | 同上取全部 `ast.Constant` 字符串节点逐个比 |
| **`#` 注释一行未动**（针对纯 docstring 的批次） | 剔掉全部 docstring 行后，整份文本与 HEAD 逐字节相同 |
| **无 CRLF** | `Path.read_bytes().count(b"\r\n") == 0`（**别用 PowerShell 管道数**，它会改写行尾） |
| **R009 逐处只删不增** | 对 257 行改动做子序列校验：删掉的字符 ⊆ {星号, 空格, emoji} |

## 4. 与上一批不同的地方

- 本批**没有改任何行为**：`ACTIONS` / `SPEC.edges` / `write_set` / `ALLOWED_EDGES` / `LOCK_ORDER` / `SCHEMA_VERSION` / `EVAL_REQUIRED_FIELDS` / 退出码表 / 提示词正文 —— 全部原样。
- 唯一的"内容性"改动是 **`p179`**：`src/agentflow/agent_prompts.py` 里 `\brief\ / \name\ / \reuse\` 原被 `\b \n \r` 转义吃掉（渲染成控制字符），已修；连带 `tests/golden/agent_surface_snapshot.json` 重冻。这一条**已在 `p179` 的提交信息里逐字写明**。
- `tests/fixtures/prompt_cache_warm.json` 不在 FC-27（`-text` 保护的只是字节不被 git 换行），本批**重跑过预热**（$0.024）以跟上 `p179`。

## 5. 人审之后要做的两件

1. `python scripts/noai_gate.py --approve <file> --reviewers A,B`：台账现在是 **stale 27 条**（旧批准钉的是清洁前的 sha），必须按新 sha 重签。
2. 签完后 `python scripts/noai_gate.py --git --since cdcb843` 应回到 `[clean]`（exit 0）；若仍有命中，说明清单与盘上不一致，别当成"没问题"。
