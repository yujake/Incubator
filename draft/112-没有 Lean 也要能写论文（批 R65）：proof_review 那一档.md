# 112 —— 没有 Lean 也要能写论文：`proof_review` 那一档（批 R65）

> 业主 2026-10-12（逐字）：「比如写论文那一档原先卡每个定理都要到 proof 水平，但没 Lean
> 显然做不到，但也要能写」。
>
> 这一批把上一批留下的那半个口子补上：R63/R64 做到了"关掉 Lean 能收工、E 的面里没有形式化"，
> 但**写作面的用词判据还没放开** —— 正文里写「定理 / 证明」仍会被 `overclaim` 挑出来。

---

## §0 一句话

新增一档受控证据等级 **`proof_review`**（"证明经逐行审阅"，凭据 = `statements` 表的
`proof_text` 非空 + V 的 `verifications/<命题号>.jsonl` 里签「成立」），并让**用词上限**
跟着 Lean 开关走：关掉时 `proof_review` 也算到顶（于是论文写得出来），开着时只有 `proof`
算到顶（老套路一个字不变）。这一档**必须自带声明**：`逐行审阅过的证明，未经机器检查`。

---

## §1 六处落点

| # | 落点 | 改了什么 | 禁改区 |
|---|---|---|---|
| 1 | `schema.py` | `EVIDENCE_KINDS` += `proof_review`；新增 `EXPERIMENT_EVIDENCE_KINDS`（**实验表不许用它**：审阅的凭据在 `verifications` 表，不属于任何一行实验）；`documents.claims` 的声明硬约束覆盖两档 | **是**（schema-migration + eval-criteria） |
| 2 | `doc_tools.py` | `PROOF_REVIEW_DISCLAIMER` / `DISCLAIMER_BY_EVIDENCE_KIND` / `_disclaimer_for()`；`wording_ceiling()`（**用词上限的唯一实现**）；`compose_claim` 自动补那一句；`EVIDENCE_LABELS` 补一档 | 否 |
| 3 | `claimanatomy.py` | `missing_disclaimer` 覆盖两档（各要各的那句话）；`overclaim` 改判 `ek not in _wording_ceiling()`；第 5/6 族的规则文字同步 | 否 |
| 4 | `review_tools.py`（H 的 `scan_document`） | 同一口径（惰性转发 `wording_ceiling`，不写第二份） | 否 |
| 5 | `verify.py` | `cross_check` 的那条 issue 扩成两档 | **是**（auth-audit） |
| 6 | `tools/verify_tools.py` | `_EVIDENCE_ORDER` 插入 `proof_review`（排在 `cross_check` 与 `proof` 之间；`_TOP_EVIDENCE` 仍是 `proof`） | **是**（prover-bridge） |
| 7 | `agent_prompts.py`（纸包三） | 「结论不许强于它挂的证据」那一条补开关分支与那句声明 | 否 |

判据：`tests/test_lean_switch.py::test_the_wording_ceiling_follows_the_switch`（五条：
关掉时 `proof_review` + 声明干净 / 缺声明报 `missing_disclaimer` / 开着时同一份断言报
`overclaim` / `cross_check` 不是上限 / 实验表不许声称这一档）。

---

## §2 读数

- 相关一组（`test_lean_switch.py` + `test_claimanatomy.py` + `test_paper_pack.py` +
  `test_closing_gate.py` + `test_check_formal_wiring.py` + `test_schema.py` + 两快照 + 读图）：全绿；
- 全量套件（冻结树上）：**5086 passed, 5 skipped, 10 deselected, 1 xfailed, 124 warnings
  in 1474.96s**，退出码 0（`temp/r65b-full-suite.txt`；上一批 5085 ⇒ 本批 +1 条判据）；
- lint：**error 0 / warning 15 / info 49**（中途 R009 抓出 5 处 `**强调**`，逐行去掉）；
- 提示词版本 **p99 → p100**（纸包三那一条变了）：冻结摘要表里 **只有 G / H / M 三格换值**
  （A–F 与 V 逐字未动，只有版本行那一行跟着动）；
- 两份 FC-27 冻结快照重冻，差异逐格核过：
  - `tool_surface_snapshot.json`：**2 处**（`doc.build_document` / `doc.compose_claim` 的
    `evidence_kind` enum 多一个 `proof_review`）；
  - `agent_surface_snapshot.json`：**11 处** —— 十格提示词各差一行版本号（p99→p100）、
    G/H/M 三格的正文（纸包三）、以及 `roles.B.actions` 里那两件动作的 params enum；
- `docs/READING-MAP.md`：`schema.py` 3303 / `claimanatomy.py` 1856 / `verify.py` 1811，
  头部总计 124,843 行（读图判据自己抓出来的三格）。

---

## §3 缺省翻转（批 R66，已落地）

`settings.DEFAULT_LEAN_ENABLED` 已从 `True` 翻成 **`False`**（业主：「默认设置中 Lean 关闭
帮用户在无严苛要求时省钱」），`settings.example.json` 同步写 `false`。两件事分开钉：

- **产品缺省是关的**：`test_lean_switch.py::test_the_product_default_is_lean_off`（含示例文件）；
- **判据套件跑在"开着"那一档**：`tests/conftest.py` 在导入期把 `AGENTFLOW_LEAN_ENABLED=1`
  钉上（子进程继承），由 `test_settings.py::test_the_suite_pins_the_lean_switch_on` 守卫。

为什么要分成两件事：这一套判据守的是**形式化那条路**的接线（桥接层、E 的动作与受控理由、
提示词里的"怎么写"、收工门的承重格、`runflow` 的 Lean 段、两份冻结快照）。缺省关掉它只是
"默认不烧那笔钱"，**不是"这条路没了"** —— 实测：翻缺省那一刻 **98 条判据变红**，全部落在这一档；
若让它们跑在关掉那一档，那几百条会静默变绿（关掉时那些分支根本不发生），
而"开着时逐字不变"这条性质就再没有判据看着了。

---

## §4 下一阶段的施工面（只读调查已做，读数见本条）

`agentflow` 的 UI 与预算轴现状（调查读数全文在 `agentflow/temp/LEAN-SWITCH-INVENTORY.md`
之外另有口头汇报，下面只留**要在本阶段动手的**）：

### 4.1 预算轴（四件，按依赖排序）

1. **`--budget-usd` 灌进 `Policy.usd_budget`**（`cli.py:1599` 今天只灌 `wall_clock_sec`）——
   这是"编排层全局闸门 + 实时扣除"真正生效的最短一刀；
2. **运行期可变的额度寄存器**（今天 `Policy` 是 `frozen` 值对象、`TokenMeter.budget_usd`
   只在构造期注入、`SeamSpend.usd` 只增）——最小做法是照 `stopctl` 那种
   "盘上开关 + 钩子 + SSE 广播"的成熟形态做一份 `budget` 版：盘上文件给**总预算与追加额**，
   每个闸门读它、`TokenMeter.spent()` 读同一张 `usage_ledger`（**已经幂等**）；
3. **扣完自动优雅停**：单趟（`agent_loop.py:2918`）与多轮（`autonomy.py:291`）都已经"优雅收尾"，
   缺的是**触发源**：现在只看内存 `spend`，要把额度寄存器并进来；同时**写 `.agentflow-stop`
   并发一帧 `stop`**（今天预算耗尽只落一个 `stop_reason="budget"`，跨进程没有通道）；
4. **只读端点 + UI**：`policy.budget_state()` 已经是现成的三态字典（`tokens_left/usd_left/…`），
   加一条 `GET /api/budget`（含 `spent/by_role/by_scope/limit/remaining/追加历史`）+
   `POST /api/budget`（追加，走 `writes` 那套授权/CSRF/审计/掩码），前端一页。

### 4.2 Web UI（三件）

1. **两页新面**：设置页（`POST /api/settings` 后端已就绪、`write_settings` 能写三段 10 个键）+
   使用说明页（今天只有 `README.md` 与 `docs/USER-TEST.md`，UI 里没有任何入口）；
2. **解禁三处 `disabled`**：`Machine.tsx` 的写设置、`Run.tsx` 的停机开关 —— 后端、授权、CSRF、
   审计**全部已就绪**；顺手清掉 6 处陈旧"没接线"文案（注意 `test_webui_contracts.py:963-993`
   反过来钉住其中一处，要一起改）；
3. **监控三条真缺口各加一条只读端点**：在飞子代理/活进程（`stopctl.live_pids/running_loops`）、
   状态报告 `STATUS-*`（`statusreport` 写了没人读）、`usage_ledger` 汇总（`UsageRow` 类型已声明
   但没有 face）。

### 4.3 FC-27 风险（调查结论逐字）

只要设计收敛到"**不新增动作、不新增工具、不新增表、不新增受控词表取值**"，
43 条禁改区**一条都不命中**（UI、`settings.py`、`tokenmeter.py`、`policy.py`、`llmseam.py`、
`stopctl.py`、`agent_loop.py`、`autonomy.py`、`conductor.py`、`cli.py`、`webui/` 全都不在清单里）。
一旦为了"让 M 追加预算"去加动作/工具 ⇒ 立刻命中 `specs/m.py`、`capabilities.py` 与**四份冻结
快照**，必须走 FC-27 人审 + 2 名 reviewer。**本阶段按前者做**（额度寄存器走盘上文件 +
HTTP 端点，不给角色加动作）。

### 4.4 然后才是业主点名的 T2 验收

无 Lean 模式（缺省关闭 + `lean_enabled=false`）跑 T2：预算敞开、让它研究到自己停；
停止后模拟用户继续下指令要求整理成论文；再核调查/研究/成文/审阅全链路。
研究中出现的报错**统一收集**（落一份 `TEMP` 读数），效果差就按产出文件分析架构问题。
