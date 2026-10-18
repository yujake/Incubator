# SELF-CHECK-FINDINGS —— 自检失败项的缺陷台账（待修，**不是文档问题**）

> 采集日期 **2026-10-18**。本文件只登记"跑出来的失败"，**不当场改代码**（本轮授权只写文档）。
> 判据：`docs/ROLE-SPECS.md` 的 §A.10–§M.10 与 `docs/ROLE-SPECS-APPENDIX.md` 的
> 「A.10–M.10 全部自检实测」引用的都是这里的事实。
> 复跑前置：`cd D:\Incubator\agentflow; $env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`

| # | 角色 | 失败项（逐字） | 复跑命令 | 当次读数 | 退出码 |
|---:|---|---|---|---|---:|
| F-1 | C | `FAILED: persist 落盘且登记行一致` | `python -m agentflow.agent_c` | `自检断言：43/46 通过` | 0 ⚠️ |
| F-2 | C | `FAILED: I3 正向：新增 ≤3 条，且 submitted_by/priority/mode/topic 全部合规` | 同上 | 同上 | 0 ⚠️ |
| F-3 | C | `FAILED: I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由` | 同上 | 同上 | 0 ⚠️ |
| F-7 | C | **自检 `FAILED` 却以退出码 0 结束** ⇒ **见下方单列（最高优先级）** | `python -m agentflow.agent_c; echo $LASTEXITCODE` | `SELF-CHECK FAILED` / `0` | 0 ⚠️ |
| F-4 | E | **`0 项失败` 与 `退出码 1` 同时成立**，且**没有汇总行**（输出止于 `[9] …`） | `python -m agentflow.agent_e; echo $LASTEXITCODE` | 42 行、无 `SELF-CHECK DONE（agent_e）` | 1 ⚠️ |
| F-5 | V | `[FAIL] 编号从 v-0001 起` | `python -m agentflow.agent_v` | 14 `[PASS]` + 2 `[FAIL]` | 1 |
| F-6 | V | `[FAIL] 五元位第 3 位 owner 是 V`；另：自检**标签**写「命题号必须 4 位」而规格是**六位**（`schema.ID_DIGITS == 6`，读侧兼容四位） | 同上 | 同上 | 1 |
| F-8 | Web | **9 个 Web 判据文件本次未跑**（`tests/test_webui{,_contracts,_pages,_readers,_settings_write,_sse,_static,_writes,_browser}.py`）⇒ 这一层**没有任何失败登记，也没有任何通过证据** | `python -m pytest -q tests/ -k webui` | 未跑 | — |

## ⚠️ 最高优先级：F-7 —— **C 三项 FAILED 却退出码 0**

**这是"失败不给非零"：任何基于退出码的判据（门 / CI / 发布检查 / `release_all`）都会把一次
真实的失败读成"通过"。失败本身还能修，折平成"通过"的那一档不会有人再来修。**

- 复跑：`python -m agentflow.agent_c; echo $LASTEXITCODE` ⇒ `SELF-CHECK FAILED` + **`0`**
- 同一形态还有 F-4（E：`0 项失败` 却退 1，且无汇总行）—— 两个方向都坏：一个该红不红、一个不该红却红。
- **建议修法：自检失败必须 `return 1`，并让汇总行在 FAILED 时必存在。**

## 每条为什么值得修（一句话）

- **F-1/F-2/F-3**：C 是唯一"只读但写自己的产出表"的角色，`persist` 与 I3 闸门正是它的写面与配额面；
  自检红着说明"我自己检查我自己"这一档已经不成立了。
- **F-7**：比失败本身更贵 —— **失败没有退出码**就等于"没失败"（三态被折平：`FAILED` 降级成 `pass`）。
  与 `DEVELOPMENT.md` 的退出码纪律直接冲突。
- **F-4**：`0 项失败` + `退出码 1` 是一对自相矛盾的读数，读它的人无从判断该信哪一半；
  汇总行缺失还让"通过"这件事无法被机械读出。
- **F-5/F-6**：V 的台账编号宽度与五元位 owner 是它**唯一的落库契约**；
  自检在这里红着，说明台账侧的改动（`format_id` 六位化）没有回头对齐自检断言。
- **F-8**：Web/用户端是**第八层**（`ROLE-SPECS.md` §0.8）。9 个判据文件存在但本次没跑 ——
  "没跑"必须与"跑过了、没问题"分开写（三态纪律），所以单列一行。

## 边界（本轮**没有**做什么）

- **没有改任何 `.py` / `src/` / `tests/`**：F-1…F-8 都是"如实记录"，不是"改代码让它变绿"。
- 没有为了让自检变绿去放宽断言：那会把"证据"改成"橡皮图章"。
- 修法方向（供授权后执行）：F-1…F-3 看 `agent_c` 的 `persist` 与 I3 闸门分支；F-7 让 `__main__`
  以 `SystemExit(0 if ok else 1)` 收尾；F-4 让 `core.selftest()` 打印汇总行并与退出码同源；
  F-5/F-6 按 `schema.format_id` 的六位宽度重算断言与 `evidencebits` 的 owner 判据。
