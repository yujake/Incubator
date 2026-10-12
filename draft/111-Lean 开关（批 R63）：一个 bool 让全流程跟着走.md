# 111 —— Lean 开关（`toolchain.lean_enabled`）：一个 bool，全流程跟着它走（批 R63）

> 业主 2026-10-12 口径（逐字）：「由于某些用户没有 Lean 环境，再设计一个模式，在全程不做
> Lean 形式化的情况下尽可能用审阅自然语言证明的方式推进论文审阅或课题研究。至于有没有
> Lean 环境，这做一个 bool 值让用户设置。全流程涉及 Lean 的都要跟进这个开关的状态。」
>
> 业主对落地范围的裁定（同一天，选择题）：**乙①「一次做到位，走 FC-27 批量签字」**。

---

## §0 一句话

做一个开关：`toolchain` 段的 `lean_enabled`（JSON 布尔，环境变量 `AGENTFLOW_LEAN_ENABLED`，
缺省 `true` = 与今天逐字相同）。关掉它以后，**形式化这条路整条不存在**：桥接层连探测都不做、
提示词改讲"自然语言逐行审阅证明"、收工门那一格从"红"变成"不适用 + 替代读数"。
**"自然语言逐行审阅"这条腿不用新建** —— V 的 `verify.verify_proof` + `verifications/<命题号>.jsonl`
本来就在，这一批做的是把它接成形式化关掉时**唯一**的"审过"凭据。

---

## §1 六处落点（每处都有判据：`tests/test_lean_switch.py`，12 条）

| # | 落点 | 关掉时的行为 | 禁改区 |
|---|---|---|---|
| 1 | `settings.py`（`lean_enabled()` / `_bool_cell` / `BOOL_KEYS` / 写入口 / 示例） | 三档梯子：环境变量 > 设置文件 > `true`；**读不懂当场抛 `ValueError`**（不静默按缺省） | 否 |
| 2 | `toolchain.py`（`lean_enabled()` / `formal_mode()` / `toolchain_report()` /`mathlib_state()`） | `lean_enabled=False`、`formal_mode="prose_review"`、`can_do_formal=False`；**Mathlib 探针不跑** | 否 |
| 3 | `formalgw.py`（受控词表多一档 `lean_disabled`；`check_lean` 前置拒绝） | 状态 `lean_disabled`、`checked=False`、`evidence_kind=None`、**一次进程都不起** | 否 |
| 4 | `tools/verify_tools.py`（`check_formal` 前置开关检查） | `reason="lean_disabled"`（不是 `no_backend`：**用户关掉了** ≠ 机器上没有） | **是**（prover-bridge） |
| 5 | `agent_e`（`run_experiment(method='formal')` 前置拒绝 + 受控理由收口） | 跑脚本之前就拒，理由里给替代路线（`proof_text` + `verify.verify_proof`） | 否（`agent_e/**`） |
| 6 | 提示词 + 声明层 + 收工门 | 见 §2 | 部分是 |

`lean_disabled` 这一档**不进** `_CONCLUDED_STATUSES`（那会让"没启用"读成"查过了、命题不成立"），
也**不许**被折成 `no_backend`（那会让人去查环境，而该看的是设置文件）。

---

## §2 提示词与声明层的口径（`PROMPT_VERSION` p98 → **p99**）

| 落点 | 改了什么 | 禁改区 |
|---|---|---|
| `agent_prompts.toolchain_facts_text()` | 关掉时**第一行**就是「Lean 形式化：已关闭」+ 替代路线；机器事实降级成"背景读数（不改变处置）" | 否 |
| `agent_prompts.toolchain_formal_text()` | 关掉时不再讲"怎么写 Lean"，改讲"这一步该交什么"（`proof_text` → 派 V → 结论强度上限） | 否 |
| `agent_prompts` 纸包六 | "核验证明分两步"补一段：TOOLCHAIN_FACTS 第一行说已关闭 ⇒ 那两步整条不适用 | 否 |
| `specs/e.py` | Mathlib 政策前加开关分支（关掉时不写 Lean，改走 V 那条腿） | **是**（auth-audit） |
| `specs/h.py` | 采信规则补**一档例外**：关掉时第二条背书换成"V 逐行走查过"（并要写清强度不同） | **是**（auth-audit） |
| `specs/m.py` | 形式化政策 + 「算或造」验收档各补一句：`proof_experiment_rows` 必然 0 ⇒ 写 `na` + 换 `reviewed_proof_rows` | **是**（auth-audit） |
| `closing.py` 的 `load_bearing` | 关掉时记 `na` + 理由 + 替代读数（V 签「成立」的证明行数），**不是 pass、也不是 fail** | 否 |

`closing` 读 V 的审校走的是 `verifications.list_verifications()`（V 的审校**不是台账表**，
是工作区里 `verifications/<命题号>.jsonl`）—— 不在这里另写一份 JSONL 解析。

---

## §3 这一批的读数

- 全量套件（冻结树上）：**5084 passed, 5 skipped, 10 deselected, 1 xfailed, 124 warnings
  in 1556.64s**，退出码 0（读数 `temp/r63c-full-suite.txt`；上一批 5071 passed ⇒ 本批 +13 条）；
- lint（`python -B scripts/lint_rules.py --root .`）：**error 0 / warning 15 / info 49**（与基线一致）。
  中途 R009 抓出 **6 处 error**（我在注释/docstring 里写了 `**强调**`）—— 处置是逐行去掉那对星号，
  **不动**提示词字符串里的 markdown（那是发给模型看的文本，不是注释）；
- 相关一组（`test_lean_switch.py` + 桥接层 + 声明层 + 收工门 + 两快照 + webui 契约）：**369 passed, 1 skipped**；
- 新增判据：`tests/test_lean_switch.py`（12 条：三档梯子 / 读不懂当场报错 / 写入口 / 示例文件 /
  读数层 / 桥接层不起进程 / 开着时逐字不变 / E 的前置拒绝 / 理由不折叠 / 提示词两段 /
  收工门 `na` / 开着时老判据不变）；
- Web UI 契约：`webui/readers.py` 的 `MachineView` 补三格（`lean_enabled` / `lean_enabled_source` /
  `formal_mode`）；`ui/src/types.ts` 是**生成物**（裁定 M2），按生成器重跑（手改那条判据会红）。

### §3.1 中途抓出来的三处（都不是"顺手改"）

1. **R009 六条 error**：我自己的新注释写了 markdown 强调（见上）；
2. **Web UI 契约 C 条**：新读数进了后端面 ⇒ `MachineView` 与生成物必须跟上（否则台面上少三格，
   而"用户关掉了"会被读成"机器上没装"）；
3. **悬空引用判据**：调查产物 `agentflow/temp/LEAN-SWITCH-INVENTORY.md` 把 `settings.example.json`
   的三条**示例键名**写成了反引号 token（它们在 `.py` 面不是真符号）⇒ 按判据的口径改成纯文字
   （**不是**登记进豁免表：那条豁免面只放"历史叙述 / 示意"）。
- 重冻：`tests/golden/agent_surface_snapshot.json` **10 行**（E/G/H/M 四格的提示词字符串；
  逐格 diff 见提交信息）—— 这是 FC-27 命中项之一，重冻必须逐格看过；
- 冻结摘要表（`tests/test_agent_prompts.py` 的 `_FROZEN_PROMPT_DIGESTS`）：A/B/C/D/F/V 六格
  **逐字未动**，E/G/H/M 四格换值。

---

## §4 这一批**没有**做的（如实记）

1. `runflow --lean`（`cli.py`）与 `projects.run(lean=...)` 这两条**既有**的局部开关**没动**：
   它们默认就是关的，而且是能力层之上的一层"要不要跑"，所以关掉全局开关时它们照样跑不出
   proof 级证据（`formalgw` 那一层兜住了）。**要动的只是它们的 `--help` / 文档**（列进下一批）。
2. `evidencebits` 第 4 位（`formal`）的凭据**没有换**：它现在读 `experiments(method='formal')`，
   关掉时必然是 `pending`/`na`。收工门的替代读数（`prose_reviewed_statements`）已经给了，
   但"五元位第 4 位在关掉时改读 `verifications`"这件事要动 `evidencebits.py` 与它的判据 ——
   列进下一批（这一批的关闭档已经能收工，靠的是收工门那一格的 `na` + `sources[].na`）。
3. 文档：`docs/FORMAL-TOOLCHAIN.md` 的"本机实测表"与设置键表**待补**这一格
   （与它同族的三处陈旧说法也待处理：`:78` 的 `imports` 默认值、`DEV`/`DESIGN-ROLES` 对
   "本环境有没有 Lean"的两种说法）。
