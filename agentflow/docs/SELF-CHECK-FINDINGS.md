# SELF-CHECK-FINDINGS —— 自检失败项的缺陷台账（**修复轮已结账**）

> 采集日期 **2026-10-18**（首轮：只登记，不改代码）。**修复轮 2026-10-18**：
> 8 条逐条复跑、定性、修掉或对齐，状态回写到本文件。
> 判据：`docs/ROLE-SPECS.md` 的 §A.10–§M.10 与 `docs/ROLE-SPECS-APPENDIX.md` 的
> 「A.10–M.10 全部自检实测」引用的都是这里的事实。
> 复跑前置：`cd D:\Incubator\agentflow; $env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`

## 状态总表

| # | 角色 | 失败项（逐字，首轮读数） | 修前 | 修后 | 状态 |
|---:|---|---|---|---|---|
| F-1 | C | `FAILED: persist 落盘且登记行一致` | `43/46 通过`，退出码 0 | `46/46 通过`，退出码 0 | **判为断言过期并已对齐** |
| F-2 | C | `FAILED: I3 正向：新增 ≤3 条，且 submitted_by/priority/mode/topic 全部合规` | 同上 | 同上（新增 4 条 = min(候选 4, 每轮上限 30)） | **判为断言过期并已对齐** |
| F-3 | C | `FAILED: I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由` | 同上 | 同上（在途 200/200 时拒绝 4/4） | **判为断言过期并已对齐** |
| F-7 | C | **自检 `FAILED` 却以退出码 0 结束** | `SELF-CHECK FAILED` / 退出码 **0** | `SELF-CHECK FAILED（agent_c）` 形态存在；**有 `FAILED` 必非零**（新判据实测） | **已修** |
| F-4 | E | **无汇总行**（输出止于 `[9]`）+ **退出码 1** | 无 `SELF-CHECK …` 行 / 退出码 **1**（stderr 是 `ExperimentError` traceback） | `SELF-CHECK DONE（agent_e）：25 项通过 / 0 项失败 / 未查 1 段` / 退出码 **0** | **已修** |
| F-5 | V | `[FAIL] 编号从 v-0001 起` | 14 `[PASS]` + 2 `[FAIL]`，退出码 1 | `17 项通过 / 0 项失败`，退出码 0 | **判为断言过期并已对齐** |
| F-6 | V | `[FAIL] 五元位第 3 位 owner 是 V`（+ 标签写「命题号必须 4 位」） | 同上 | 同上 | **判为断言过期并已对齐**（owner 结论本身成立，见下） |
| F-8 | Web | 9 个 Web 判据文件未跑 | 未跑（三态里的"没查"） | **194 passed / 0 failed / 18 deselected**，退出码 0 | **已跑（结果入账）** |

## 逐条结论（判"过期"还是"退化"，依据是什么）

### F-1 —— 断言过期：`rows[0]` 是"产出即登记"之前的写法

- **结论**：`persist()` 的实现没有退化；**过期的是取行方式**。
- **依据**：`agent_c/__main__.py` 第 [13] 段原写 `row = st.rows("analysis_reports")[0]`。
  而 2026-10-12 业主裁定 CS-10 ②（"直接调分析器也落库"）之后，
  `agent_c/core.py` 的 `_report()` 在 `ok` 且 kind 在受控词表里时**已收口一次
  `persist()`**（`core.py:104-114`，注释逐字："产出即登记（业主 2026-10-12 裁定
  CS-10 ②：直接调分析器也落库）"）。于是走到 [13] 时表里已有前面几个分析器各自
  落的行：修前实测 `info["report_id"] == "000009"` 而 `rows[0]["report_id"] == "000000"`
  —— 断言拿第一份报告去和这一份比，**必假**。
- **改了什么**：按**这次** `persist()` 返回的号去定位登记行，并断言该号在表里
  **恰好一行**（`len(matched) == 1`）——这比原来的 `rows[0]` 更紧，不是放宽。
- **为什么不是削弱**：判据仍然核"落盘文件存在 + 登记行与返回值一致"，只是把
  "哪一行是这一份"从"表里第一行"改成"这一份的号"。

### F-2 / F-3 —— 断言与夹具过期：写死的 3 / 20 是旧配额，且夹具用了四位号

- **结论**：**过期**（两条都是）。闸门实现没有退化。
- **依据一（配额）**：`interactions.DEFAULTS["max_gap_requests_per_run"]` 现为
  **30**（`interactions.py:168` 逐字："`max_gap_requests_per_run`: 30,  # I3 单次
  gaps 最多直连多少条检索请求（3 → 30，裁定 C9）"）；`max_inflight_requests` 现为
  **200**（`interactions.py:165` 逐字："`max_inflight_requests`: 200,  # I7 全局
  在途检索请求上限（20 → 200，裁定 C9）"）。自检却仍断言"新增 ≤3 条"、夹具仍只
  填 20 行并自称"20/20（上限）" ⇒ 该拒的没拒（20/200 当然放行），该限的没限。
- **依据二（夹具代号）**：`_i3_fixture` 里概念行用 `S.format_id(i)` 发号（六位），
  关系行却写死 `"0000"…`（四位）。2026-10-14 业主裁定"所有四位编号改成六位"
  （`schema.py:140-146`，`ID_DIGITS = 6`）之后，图里每个概念代号都查不到名字
  ⇒ `_looks_like_non_concept` 把**全部**候选按"概念名明显不是概念"否决
  ⇒ `candidate_gaps` 恒空，两条断言测的根本不是闸门。修前实测："候选=0 条"。
- **改了什么**：夹具的概念号/关系号统一走 `S.format_id`；"≤3" 改成
  **`新增 == min(候选数, max_gap_requests_per_run)`**（两端都从 `DEFAULTS` 现读）；
  闸门夹具按 `DEFAULTS["max_inflight_requests"]` 填满在途（200 行），断言不变。
- **为什么不是削弱**：`== min(候选数, 上限)` 同时钉住"候选真的被提交"与"每轮上限
  真的生效"，比"`<=3`"信息更强；闸门用例仍然要求"新增 0 条 + 一条都不落盘 +
  每条都有理由 + 理由含'已达上限'"。

### F-4 —— 真缺陷（自检崩在汇总行之前）：**已修**

- **结论**：不是断言过期，是**自检自己的结构缺陷**（汇总行/退出码纪律）。
- **依据**：修前 stderr 的第一行是
  `File "...\agent_e\core.py", line 744, in selftest` →
  `ExperimentError: 本会话的 Lean 形式化已关闭（toolchain.lean_enabled=false 或 AGENTFLOW_LEAN_ENABLED=0）…`。
  而 `settings.py` 的出厂默认就是 **`lean_enabled = false`**（业主 2026-10-12：
  "默认设置中 Lean 关闭帮用户在无严苛要求时省钱"）；`tests/conftest.py:182` 为了让
  形式化那一段能跑才把环境变量钉成 `1` —— 所以"pytest 里绿、手工敲命令崩"。
- **改了什么**（两件事都做）：
  1. 形式化那一段按**三态**写：开关开着 ⇒ 走检查器、核 proof 三件套（原判据不变）；
     开关关着 ⇒ 核"当场拒绝 + 不留行 + 理由给出 V 的替代路线"，并记 **1 段"未查"**；
  2. 主体搬进 `_run_selftest_checks()`，`selftest()` 用 `try/except/finally`
     **无条件**打印汇总行，异常本身记一条失败；退出码 = `0 if 失败==0 else 1`。
- **为什么不是削弱**：关掉的那一段没有变成"通过"，而是**明写"未查 1 段"**
  （三态纪律）；开着的那一段判据一条没动（修后 `AGENTFLOW_LEAN_ENABLED=1` 实测
  27 项通过、proof 三件套全绿）。

### F-5 —— 断言过期：编号宽度写死成四位

- **结论**：**过期**。台账发的号是正确的六位。
- **依据**：`schema.py:146` `ID_DIGITS = 6`（业主 2026-10-14 裁定）；
  发号点 `verifications.next_verification_id()` 是
  `return f"v-{S.format_id(len(rows) + 1)}"`（`verifications.py:200`）。
  修前实测 `clean["verification_id"] == "v-000001"`，而断言比的是 `"v-0001"`。
- **改了什么**：断言改成 `== f"v-{S.format_id(1)}"`，标签写明六位 + "旧四位号读侧
  兼容"；**同一个过期断言在 `verifications.py` 自己的 `selftest()` 里也有一份**
  （`verifications.py:342`），一并按同一口径对齐（同族缺陷，附在本条里）。
- **为什么不是削弱**：宽度不再手写，改由 `schema` 的**唯一发号形态**决定；
  另加一条"六位号必须被接受"的正控（防止"发号与收号一起改错"仍然绿）。

### F-6 —— 断言过期（owner 结论本身**成立**）：第 3 位该由 V 签，且确实签了

- **结论**：**判为断言过期并已对齐**。"V 不该拥有第 3 位"这条**不成立**。
- **依据（代码行 + 文档行）**：
  - `evidencebits.py:10`（模块 docstring 的五元位表）逐字："| 3 | 审过 `reviewed` |
    V（自己产出的命题）／引用（引用命题：凭据是文献代号） | …"；
  - `evidencebits.py:61` `BIT_OWNERS = {"numeric": "E", "proof": "F", "reviewed": "V", "formal": "E", "audited": "H"}`；
  - `verifications.py:6` 逐字："五元证据位（§3.14）的第 3 位（"审过"）的 owner 是 V"；
  - 修前实测 `clean["signed_bit3"] is True`、`clean["bits"]["reviewed"] is True`、
    `reviewed_by = {"verifier": "agent-V", "verification_id": "v-000001", …}`
    —— 签名行为与 owner 声明一致，**红的是那半句写死的 `"v-0001"`**。
- **改了什么**：断言拆成"位表 owner=V"（静态，`BIT_OWNERS["reviewed"] == "V"`）+
  "本次实际签名者是 `DEFAULT_VERIFIER`"+ "凭据就是本次发的号"三半；标签里
  「命题号必须 4 位」改成「必须 `S.ID_DIGITS` 位（旧四位仍可读）」，并加核
  `detail` 里报出的宽度与 `schema.ID_DIGITS` 逐字一致（标签也是判据的一部分：
  照错的标签去改数据会越改越不对）。
- **为什么不是削弱**：三条都比原来多核了一半；没有任何一条检查被删。

### F-7 —— 真缺陷（坏掉的锁）：**已修**

见下方单列。新判据 `tests/test_selfcheck_exit_codes.py`：**修前 6 红、修后 6 绿**。

### F-8 —— 已跑，结果入账（见下节）

## ⚠️ F-7 单列：**C 三项 FAILED 却退出码 0**

**这是"失败不给非零"：任何基于退出码的判据（门 / CI / 发布检查 / `release_all`）都会把一次
真实的失败读成"通过"。失败本身还能修，折平成"通过"的那一档不会有人再来修。**

- 修前复跑：`python -m agentflow.agent_c; echo $LASTEXITCODE` ⇒ `SELF-CHECK FAILED` + **`0`**
- 修后：汇总行与退出码同源 —— 任一 `[FAIL]` ⇒ `SELF-CHECK FAILED（agent_c）：N 项通过 /
  M 项失败` + **退出码 1**；全过 ⇒ `SELF-CHECK DONE（agent_c）：46 项通过 / 0 项失败` + 退出码 0。
- **新判据**：`tests/test_selfcheck_exit_codes.py`，**用子进程**跑
  `python -m agentflow.agent_c` / `agent_e` / `agent_v`，断言
  "有 `FAILED` 字样 ⇒ 退出码非 0；有 `SELF-CHECK DONE` ⇒ 退出码 0；两样都没有 ⇒ 判红（没量成）"。
- **负控选型（说明 + 证明）**：选了**注入假失败**（不是"只对当前真实失败断言"）：
  用 `python -c` 起子进程，先把自检读到的一个方法换成"形状合法、结论错"的替身
  （C: `AgentC.neighbors` 恒空；E: `AgentE.evidence_for` 恒"查过了没有"；
  V: `AgentV.list_verifications` 恒 0 行），再 `runpy.run_module(..., run_name="__main__")`。
  **没有一行生产代码为测试让路**（注入点是子进程内的模块全局）。
  同一个断言在两处被量过：
  - **修前**：`6 failed` —— C 的正控与负控都红在"`FAILED` 而退出码 0"，
    E/V 红在"没有汇总行"（正是 F-4 / F-5 的现场）；
  - **修后**：`6 passed`。
  这条负控同时钉住"汇总行必须存在"：注入失败后如果自检崩了（无汇总行），
  判据也会红，而不是以"非零退出码"假绿。

## F-8 实跑结果（Web 层，第八层）

命令（逐字）：

```text
python -m pytest -q tests/test_webui_contracts.py tests/test_webui.py tests/test_webui_pages.py \
  tests/test_webui_readers.py tests/test_webui_settings_write.py tests/test_webui_sse.py \
  tests/test_webui_static.py tests/test_webui_writes.py tests/test_webui_browser.py
```

读数（2026-10-18，**全部修改完成后的复跑**；首跑读数与此一致）：**`194 passed, 18 deselected in 71.38s`，退出码 0**。

| 档 | 条数 | 说明 |
|---|---:|---|
| 绿 | **194** | 9 个文件里被 `addopts` 选中的全部用例 |
| 红 | **0** | —— |
| 未跑 | **18** | 全部是 `tests/test_webui_browser.py` 的用例（该文件顶部 `pytestmark = [pytest.mark.browser]`，且 `pytest.importorskip("playwright.sync_api")`），被项目默认 `pyproject.toml:91` 的 `addopts = "-m 'not network and not browser'"` 筛掉 |

**"未跑"不等于"通过"**：浏览器层这 18 条本次没有执行证据（要跑得显式
`-m browser` 且本机有 playwright 浏览器）。这一行按三态纪律单列，不并进"194 绿"。

## 复跑证据（修前 / 修后，均含退出码）

```text
# C（F-1/F-2/F-3/F-7）
修前：python -m agentflow.agent_c  ⇒ 自检断言：43/46 通过 + 3 项 FAILED + SELF-CHECK FAILED；退出码 0
修后：python -m agentflow.agent_c  ⇒ 自检断言：46/46 通过 + SELF-CHECK DONE（agent_c）：46 项通过 / 0 项失败；退出码 0
      [16] 候选=4 条；新增=4 条（= min(4, 每轮上限 30)）；在途 200/200（上限）时新增=0 条、被拒=4 条
注入失败（负控）：退出码 1 + SELF-CHECK FAILED（agent_c）：42 项通过 / 4 项失败（邻居 4 条判据）

# E（F-4）
修前：python -m agentflow.agent_e  ⇒ 无汇总行（止于 [9]）+ stderr ExperimentError；退出码 1
修后：python -m agentflow.agent_e（出厂默认，lean 关闭）
      ⇒ SELF-CHECK DONE（agent_e）：25 项通过 / 0 项失败 / 未查 1 段；退出码 0
修后：AGENTFLOW_LEAN_ENABLED=1 python -m agentflow.agent_e（检查器那一段真跑）
      ⇒ SELF-CHECK DONE（agent_e）：27 项通过 / 0 项失败；退出码 0
注入失败（负控）：退出码 1 + SELF-CHECK FAILED（agent_e）：22 项通过 / 3 项失败 / 未查 1 段

# V（F-5/F-6）
修前：python -m agentflow.agent_v  ⇒ 14 PASS + 2 FAIL；退出码 1
修后：python -m agentflow.agent_v  ⇒ SELF-CHECK DONE（agent_v）：17 项通过 / 0 项失败；退出码 0
注入失败（负控）：退出码 1 + SELF-CHECK FAILED（agent_v）：14 项通过 / 3 项失败

# 同族（附）：verifications 自己的 selftest 也有一份写死四位的断言
python -m agentflow.verifications  ⇒ 10 PASS；退出码 0
```

测试行（判据本身）：

```text
python -m pytest -q tests/test_agent_c.py tests/test_agent_e.py tests/test_verifier_role.py \
  tests/test_role_specs_complete.py tests/test_selfcheck_exit_codes.py
⇒ 114 passed, 1 warning in 64.43s

# 加上守 `python -m` 契约的那一条（它会把 C/E 的退出码回归当场量出来）
python -m pytest -q tests/test_agent_c.py tests/test_agent_e.py tests/test_verifier_role.py \
  tests/test_role_specs_complete.py tests/test_selfcheck_exit_codes.py \
  tests/test_agent_split_is_one_action_one_file.py
⇒ 127 passed, 1 warning in 89.15s

# 相邻受影响面（编号宽度 / Lean 开关 / E 的形式化路径 / C 的服务面 / 发布门的模块自检）
python -m pytest -q tests/test_agent_split_is_one_action_one_file.py tests/test_id_width.py \
  tests/test_lean_switch.py tests/test_lean_modes_matrix.py tests/test_core_audit_efgh.py \
  tests/test_agent_c_service.py tests/test_agent_e_formal_path.py tests/test_agent_e_formal_reasons.py \
  tests/test_agent_e_run_log.py
⇒ 159 passed, 1 skipped, 1 warning in 71.63s

python -m pytest -q tests/test_release_check_items.py
⇒ 25 passed in 33.46s
```

> 注：任务里写的 `tests/test_agent_v.py` 在本仓**不存在**；V 的判据实际住在
> `tests/test_verifier_role.py`（按"文件名不对就按实际存在的那几个跑"执行），
> 另加 `tests/test_id_width.py` / `tests/test_agent_split_is_one_action_one_file.py`
> 守着编号宽度与 `python -m` 契约。

## 每条为什么值得修（一句话）

- **F-1/F-2/F-3**：C 是唯一"只读但写自己的产出表"的角色，`persist` 与 I3 闸门正是它的写面与配额面；
  三条都是断言/夹具停在旧口径（CS-10 ②、裁定 C9、六位编号），修它们**不是**让它变绿，而是让它重新测到闸门。
- **F-7**：比失败本身更贵 —— **失败没有退出码**就等于"没失败"（三态被折平：`FAILED` 降级成 `pass`）。
- **F-4**：`0 项失败` + `退出码 1` 是一对自相矛盾的读数；汇总行缺失还让"通过"这件事无法被机械读出。
- **F-5/F-6**：V 的台账编号与第 3 位签名是它**唯一的落库契约**；六位化之后自检没回头对齐。
- **F-8**：Web/用户端是**第八层**（`ROLE-SPECS.md` §0.8）。9 个文件已实跑（194 绿 / 0 红 / 18 条浏览器档未跑）。

## 边界（本轮**做了**什么 / **没有**做什么）

**改了**（全部在 `tests/`、`docs/`、以及如下 `src/` 文件）：

| 文件 | 改动 |
|---|---|
| `src/agentflow/agent_c/__main__.py` | F-7 退出码 + 汇总行；F-1 按号取行；F-2/F-3 夹具与断言对齐当前 `DEFAULTS` 与六位号 |
| `src/agentflow/agent_e/core.py` | F-4 汇总行无条件 + 退出码同源 + Lean 开关三态分支 |
| `src/agentflow/agent_v/core.py` | F-5/F-6 六位编号、owner 三半断言、标签宽度、汇总行 |
| `src/agentflow/verifications.py` | 同族：它自己的 `selftest()` 里那份写死四位的断言 |
| `tests/test_selfcheck_exit_codes.py` | **新增**：F-7 的子进程判据（正控 + 注入失败负控，覆盖 C/E/V） |
| `docs/ROLE-SPECS.md` | §C.10 / §E.10 / §V.10 的当次读数改成复跑后的真实值 |
| `docs/SELF-CHECK-FINDINGS.md` | 本文件（状态回写） |

**没有做**：

- 没有为了让自检变绿删检查、放宽断言：F-1/F-2/F-3/F-5/F-6 的每一条都是**换成更紧的
  写法**（按号定位、`== min(候选, 上限)`、按 `DEFAULTS` 填满、断言与 `schema` 同源）；
- 没有动 `tests/golden/*.json`、`.gitignore`、`draft/`、`temp/`、`test/`；
- 没有动 FC-27 禁改区的任何文件（`interactions.py` 只**读** `DEFAULTS`，未改）；
- 没有把"没跑"写成"通过"：F-8 的 18 条浏览器档与 E 的「未查 1 段」都单列。
