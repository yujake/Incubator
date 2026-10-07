# FIX6-F4 报告（第 6 轮修复批 · 权限面的导入期交叉断言 + 文档数字）

依据：`temp/FIX6-DISPATCH.md`（`F4` 行 + 并发写者纪律）、`temp/FIX6-PLAN.md`（§0/§1/§2/§3）、
`temp/REAUDIT6-R4.json`（`R4-AN-1`…`-5`）、`draft/28-…md` §83.2。

本批只改了自己清单里的文件；没有碰别人清单里的任何一个字节。
`tools/base.py` 与 `tools/__init__.py` 是 FC-27 禁改区（`auth-audit`）：前者只加指向注释、
后者加导入期判据 —— 两个文件都进人审清单（`tools/__init__.py` 的备份在改前就做好了）。

## 0. 文件与 sha256（改前 / 改后）

| 文件 | 改前 sha256 | 改后 sha256 | 改前备份（本批） |
|---|---|---|---|
| `src/agentflow/capabilities.py` | `160c7b5de22a9f4bc91877520bd317efdfd7a4e13f5a401643701503b0c49fa5`（前16 `160c7b5de22a9f4b`） | `2ea35c05a0038ad3b35a5f06a93fc0e1ab3f0b6e970c4f59784b8399a0fc736c`（`2ea35c05a0038ad3`） | `temp/FIX6-F4-before_src_agentflow_capabilities.py` |
| `src/agentflow/tools/__init__.py`（禁改区） | `51f1e650a340a28c9036c6b6613c121cd3680ef55997f4daa7a0ae6d9711cdcb`（`51f1e650a340a28c`） | `2a24d2fe4b5bcfed79c7939eca904a1ab004879d166ea97c2c269f614f831be7`（`2a24d2fe4b5bcfed`） | `temp/FIX6-F4-before_src_agentflow_tools___init__.py` |
| `src/agentflow/tools/base.py`（禁改区） | `93d6c12999856534cd23c05a20ca64295a85d61997d859b94438a013909def48`（`93d6c12999856534`） | `a4c9f4fc2365e7bf5ff18b29159f68965e7d57deab04ddece4c665bbd7b5f42b`（`a4c9f4fc2365e7bf`，只加了一段指向注释，判据与取值零改动） | `temp/FIX6-F4-before_src_agentflow_tools_base.py` |
| `tests/test_r4_roles_surface.py` | `952bdba96514af312e19fc4165355eadcb9f62d5f9532c9522d62c82aa7a430f`（`952bdba96514af31`） | `778415b85e4e38ef0f55c1aea9923d1acc012e9dacf313203d3ffebd39f71909`（`778415b85e4e38ef`） | `temp/FIX6-F4-before_tests_test_r4_roles_surface.py` |

- 备份与源文件的 sha256 改前逐字节相等（`Copy-Item` 复制后各自核对过）。
- 行尾：三个源文件是 CRLF，改动后仍 CRLF（`tools/__init__.py` CR=414/LF=414、
  `capabilities.py` CR=2147/LF=2147、`tools/base.py` CR=1345/LF=1345）；测试文件本来就是 LF（CR=0）。
- `temp/zone-head-backups.tsv` 里本批两行（该文件被别的批重新生成过，我按本批最终字节校正了
  `base.py` 的 `current_sha256` 并把两行的走查列写成 `pending-human-walkthrough-F4`）：
  `src/agentflow/tools/__init__.py` `51f1e650a340a28c` → `current_sha16=2a24d2fe4b5bcfed`；
  `src/agentflow/tools/base.py` `93d6c12999856534` → `current_sha16=a4c9f4fc2365e7bf`。

## 1. `R4-AN-4`（medium = 台账 `N-5`）：写等级登记表 × 第一根轴词表的导入期交叉断言

**缺陷（`tools/__init__.py` 的 `SIDE_EFFECTS_WRITE` 与 `tools/base.py` 的 `SIDE_EFFECTS` 之间零判据）**：
只读角色 C/H 的结构性剥离读的是 `SIDE_EFFECTS_WRITE`（`for_role` / `call` / `_callable_for`
三处共用 `_role_surface`）。往第一根轴加一个写等级、却忘了把它登记进这张表时，
新取值不算写工具 ⇒ C/H 静默拿到它，导入成功、测试全绿。

**修法（落点 `tools/__init__.py`，因为 `base.py` 先于本文件的 `SIDE_EFFECTS_WRITE` 执行、看不见这张表）**：
新增 `_NON_WRITE_EFFECTS = ("none", "read")` 与 `_check_write_levels_are_registered()`，
模块级调用一次。判据是一个二分（缺任何一条都留下一个方向的静默漂移）：
登记表与词表互为子集、两栏不相交、并集恰好等于词表。判据本体只有这一份 ——
`base.py` 里只加了一段**指向注释**（说明本词表是"哪些等级算写"的另一半、加取值时必须
在两栏之间做选择、断言落点在装配层、以及为什么不能落在 `base.py`：它先于
`SIDE_EFFECTS_WRITE` 执行、看不见那张表）。取值与判据：`base.py` 零改动。
`SIDE_EFFECTS_WRITE` 的注释里逐字写下了缺陷、后果与判据形态。

**正控（真树）**：`import agentflow.tools` 成功；`set(SIDE_EFFECTS_WRITE) <= set(base.SIDE_EFFECTS)`
为 True；`_check_write_levels_are_registered()` 在真表上不抛（读数见 `temp/fix6_F4_precheck.py`）。
新增常驻判据 `tests/test_r4_roles_surface.py::test_the_write_level_register_is_cross_checked_at_import`
在真树上过，并用**内存注入**证明反方向（词表加假轴 / 登记表引用假轴 / 同一等级落两栏）各抛一次。

**负控（本批要求的副本注入，证据 `temp/fix6_F4_probe.txt` 甲节）**：副本 = 整棵 `src/` 复制到 temp，
再把 `base.py` 与 `capabilities.py` 两处词表同步加 `write_remote`（注入指纹：
副本 `base.py` sha16 `b26dbd3b7c1ea9b9`、含 `write_remote=True` —— 与 `REAUDIT6-R4` 报告里那一次的
注入指纹逐字相同；副本 `capabilities.py` sha16 `b3deb8b69aafbdfc`）。同一批注入字节下只换一个变量：

| 副本里的 `tools/__init__.py` | 读数 |
|---|---|
| **改前**（= 本批备份那一版，sha16 `51f1e650a340a28c`） | 退出码 0；`IMPORT-OK ('write_local',)`；`for_role C ['probe.remote']`；`for_role H ['probe.remote']`；`call C => True` ⇒ **复现了 N-5** |
| **改后**（sha16 `2a24d2fe4b5bcfed`） | 退出码 1；`AssertionError: SIDE_EFFECTS 里的 ['write_remote'] 既不在 SIDE_EFFECTS_WRITE('write_local',) 里、也不在 _NON_WRITE_EFFECTS('none', 'read') 里` ⇒ **导入即抛**，`IMPORT-OK` 不再出现 |

**如实登记的边界**：这条判据挡的是"扩词表忘登记"这一半。若有人把新等级**显式**登记进
`SIDE_EFFECTS_WRITE`（两处词表 + 登记表都改），判据会放行 —— 那是"人主动登记了一个新写等级"，
判据的职责是让它不可能静默发生，而不是替人做决定；两处落点仍在 FC-27 禁改区 ⇒ 仍要人审。
`capabilities.SIDE_EFFECTS`（未在禁改区）由既有的第 [5] 条与 `tools.base` 对齐，本批未放宽它。

## 2. `R4-AN-5`（low）：`tests/test_r4_roles_surface.py` 的"负控 2"两重空转

**缺陷**：(1) `monkeypatch.setattr(T, 'SANDBOX_AVAILABLE', True)` 打在 `agentflow.tools` 包上，
而 `_role_surface` 读 `tools/base.py` 的模块全局 ⇒ 打不打都一样；
(2) 真表的 H 工具面里一个 `external=exec` 的工具都没有（`verify.check_formal` / `run_experiment`
的 roles 是 `('E','F','G')`）⇒ "放行了"那一句永不出现，两条断言恒真。

**修法**：monkeypatch 打到 `agentflow.tools.base`；工具面换成一张真的含
`probe.exec`（`read` + `external='exec'`）与 `probe.write`（`write_local`）的合成注册表；
断言改成**按工具名核对**（同一工具不许同时出现在"剥掉了"与"放行了"两句里），
并加两条前提断言（`before` 里 exec 探针必须真的被剥掉、不许有任何放行句）与一条
"状态置回后留痕与第一次逐字相同"的断言；docstring 里那句与实测相反的描述已改掉。

**正控（真树）**：`pytest -k notes` ⇒ `4 passed, 12 deselected`；单文件 `16 passed`。
**负控（`temp/fix6_F4_probe.txt` 乙节）**：副本里把 `for_role` 的 `self._drop_own_role_notes(role)`
换成 `pass`（= `roles-4` 改前的追加形态；注入指纹：副本 `base.py` sha16 `3f97d35d79ef6af7`、
该调用在副本里出现 0 次 / 真树 1 次）⇒ `2 failed`，其中包含
`test_for_role_notes_follow_the_current_state`（另一条是同样依赖重算的
`test_for_role_keeps_the_assembly_time_notes`，符合预期）。

## 3. `R4-AN-1`（low）：`_NO_ACTION_YET['review.report']` 的理由串与事实相反

**事实（先量后改）**：`matching_tool_name(find_action('H','review_report'))` 返回 `None`；
`'H.review_report' in _KNOWN_UNMATCHED_ACTIONS` 为 True。
**修法**：理由串改成今天的事实（handler_name 与工具名最后一段不同名 ⇒ 唯一性约定对不上、
仍属 unmatched 且在登记表里、② 走的是显式登记那一支），并删掉援引第 [7c] 条的那句
（改成"第 [7c] 条那条反方向断言已被撤回，见本文件『[7c] 撤回的判据』一节"）。

**正控/负控**：新增 `test_the_review_report_reason_matches_todays_facts`（真树过；
判据只切 `_NO_ACTION_YET` 那一段文本 —— 整份源码里"唯一对上"在
`two_layer_reconciliation` 的 docstring 里有正当用法，这一点在用例注释里写明了）。
负控两层：丙节（副本整份换成改前 `capabilities.py`）⇒ 该用例红；
丁节（**隔离注入**：只把那条理由串换回改前的 525 字节形态，改后是 666 字节）⇒ 只它一条红。
`_KNOWN_UNMATCHED_ACTIONS` / `_NO_ACTION_YET` 的口径未动：`review.review_document` 与
`review.report` 仍走"显式登记为比不了"那条路（`R4-A2` 的 `fix_holds=false` 只被改文字、
没有被放宽成"三条例外都有动作"）。

## 4. `R4-AN-2`（low）：对账面数字手抄过期

**事实**：`two_layer_reconciliation()` ⇒ total 49 / compared 16 / unmatched 33 / ambiguous 0；
`Counter` = `{('info','two_layer_name_unmatched'): 33}`。
**修法**：`two_layer_reconciliation` docstring 与第 [7b] 条注释里的 `48 个动作 = 16 + 32 + 0`
改成 `49 = 16 + 33 + 0`；第 [7] 条那段"这个数字怎么来的（不许手抄）"**删掉写死的 32**，
改成两条机器等式（总条数 == `len(two_layer_reconciliation()['unmatched'])` ==
`_KNOWN_UNMATCHED_ACTIONS` 的条数，由 [7] 的两条断言钉着），并记下它漂移的那一次。

**正控/负控**：新增 `test_the_reconciliation_numbers_in_the_source_match_the_live_reading`
——先用实跑读数拼出 `"49 个动作 = 16 compared + 33 unmatched + 0 ambiguous"`，
再去源码里找（它自己**不手抄** 49/33），另判 `"48 个动作"` 与 `": 32}"` 已不在源码里。
负控：丙节（整份改前 `capabilities.py`）与丁节（隔离注入：只把两处数字换回 48/32）⇒ 该用例红。

## 5. `R4-AN-3`（low）：`if STRICT_DECLARATIONS: pass` 是空转开关

**修法（选审计者的方案①，让开关真的接上）**：第 [7] 条里那一支改成
`soft = [d for d in divergences if d.level == "warning"]` + `assert not soft`，
断言消息里逐条给出 `where: message`；`declaration_divergences` 的 docstring、
`assert_capabilities` 的第 7 条、第 [7] 条注释与模块末尾 `STRICT_DECLARATIONS` 的登记一起改成实况
（error 级与开关无关、warning 级只在 True 档断言；今天真实树 warning 数为 0，所以翻成 True
不会让 `import agentflow.capabilities` 失败 —— 这是"能安全打开"的前提，已实测）。

**正控/负控**：新增 `test_strict_declarations_switch_is_not_a_no_op`
（注入点：把 `capabilities.declaration_divergences` 换成"真读数 + 一条合成 warning"，
注入不会被下一行覆盖——待测函数每次调用现取这个名字）：
`STRICT_DECLARATIONS=False` + 那条 warning ⇒ 正常返回；`True` + 同一条 ⇒ `AssertionError`
且消息里含 `probe.synthetic`。负控：丙节（改前 `pass`）与丁节（隔离注入：只把这一支换回
`pass`）⇒ 该用例红。

## 6. 父代理追加的小活：`R2b-AN-1-C` 的指向性注释（只加注释、不改取值）

在 `capabilities.py` 的 `E.check_formal` 的 `params` 前加了一段注释，说明本表声明的是
方法层 `AgentE.check_formal` 的真形参（`name` 在方法层是对的、它不经 `ToolRegistry.call`）、
工具层 `verify.check_formal` 的 schema 已改用 `checker_name`（避撞名 + `agent_e.py` 的
`checker_name=name` 翻译使接线仍通），因此两套参数集既非相等也非包含、且今天没有判据看着它们，
三个层面的逐字对照登记在 `src/agentflow/tools/verify_tools.py` 里 `check_formal` 的 docstring
（标题含 `R2b-AN-1-C`）那一节。**没有改任何取值**（`params` 的键集仍是
`{claim, script_path, source, name, imports, timeout_sec}`）。

**对派单文本的一处更正**：`E.check_formal` 在 `capabilities.py` 的 `CAPABILITIES` 里，
不在 `:452`/`:1975` 附近（那两处是 `two_layer_reconciliation` / 第 [7b] 条的**对账数字**注释）。
所以这条注释放在 `E.check_formal` 的落点上，与 `R4-AN-2` 的数字修正**不冲突**、互不覆盖；
两处都改完的读数：`import agentflow.capabilities` 成功、`total == 49`。
（这一处更正按 `draft/28` §83.3 的纪律办：派单文本里的位置断言我当场核过才照做。）

## 7. 收工读数

- **lint（全树）**：`python scripts/lint_rules.py` 在我收工那一刻的读数是
  `[linter] error 2 / warning 0 / info 20`，两条都在**别的批**那一刻正在写的文件里
  （`tests/test_r5_orchestration_cost.py:877` = `F5`、`tests/test_noai_gate_record_audit_cli.py:2` = `F1`，
  都是 R009）；本批四个文件不是命中项。窗口内我另有一次 `error 0 / warning 0 / info 20` 的读数
  （别的批落地之后、本批再改动之前）—— 这两次读数的差别全部来自并发写者，不是本批。
- **lint（只对本批四个文件）**：把这四个文件连同 `.noai-paths` / `AGENTS.md` 复制到一个 temp 根，
  `python scripts/lint_rules.py --root <temp>` ⇒ `error 0 / warning 1 / info 10`
  （唯一的 warning 是"temp 根里读不到 `tools/vocab_census.py`"这条"没查成"，不是装饰命中）。
  本批新增/改动的注释与 docstring 里 `**` 与 emoji 计数为 0
  （过程中 `base.py` 那段注释里我一度写下过一对 `**`，被 R009 的禁改区计数从 48 变成 49 当场看见并立刻删掉，
  现在 `base.py` 的装饰计数回到改动前的 48）。
- **用例（只跑相关的，没跑全量）**：
  - `python -m pytest -q -p no:cacheprovider tests/test_r4_roles_surface.py` ⇒ `16 passed`
    （改前 12 passed；新增 4 条判据，改写的 1 条没有减少任何既有点）；
  - 本批冻结集那 10 个测试文件（`test_r4_roles_surface` / `test_policy` / `test_coverage_policy` /
    `test_capabilities_two_layer` / `test_tools_base` / `test_r4_axes_two_axes` /
    `test_r4_readonly_exceptions_tables` / `test_agent_h` / `test_interactions` /
    `test_tools_readonly_roles`）⇒ `222 passed in 61.81s`
    （改前基线 218 passed；+4 = 本批新增判据）。原始输出：`temp/fix6_F4-tests.txt`。
- **正控/负控探针**：`python temp/fix6_F4_probe.py` ⇒ `失败项 0 条 / 全部符合期望`，
  原始输出 `temp/fix6_F4_probe.txt`（甲/乙/丙/丁四节，含每个副本的 sha16 与关键串计数）。
- 没跑全量、没跑发布门、没做"重证静止"与"重派被修批次"（`FIX6-PLAN` §3 的第 4–6 步是父代理的收口动作）。

## 8. 没修的 / 边界 / 构造不出负控的条目

- **5 条 finding 全部修了**，没有留下未处置项。
- **没有放宽任何既有判据**；发现被放宽过的既有判据：0 条（`R4-A2` 的 `fix_holds=false`
  只被改文字，口径没有被放宽成"三条例外都有动作"；`test_tools_readonly_roles.py` 的
  `set(SIDE_EFFECTS_WRITE) == {"write_local"}` 等既有断言未被触碰，重跑全绿）。
- **构造不出负控的条目：0 条**（5 条各自都有副本注入或内存注入的负控；强度分层已写在各节）。
  其中两条的负控写法要如实说明强度：`R4-AN-1`/`-2` 的丙节是"整份改前 `capabilities.py`"，
  它同时让三条判据变红；为了把每一条**单独**钉住，丁节对三条各做了一次隔离注入
  （只撤掉那一条修法 ⇒ 只有那一条红）。
- **`tools/base.py` 只加了指向注释**（无判据、无取值改动）：`R4-AN-4` 的判据落点只需要
  `tools/__init__.py`（见 §1），但"加一个写等级"的人读的正是 `base.py` 的 `SIDE_EFFECTS`，
  所以在那处留了 4 行指向（指向装配层的断言与本文报告）。它因此也在待人逐行走查清单里
  （`temp/zone-head-backups.tsv` 里两行的走查列都写成 `pending-human-walkthrough-F4`）。
- **本批写入的禁改区文件有两个**：`src/agentflow/tools/__init__.py`（判据）与
  `src/agentflow/tools/base.py`（注释）⇒ 都需人逐行走查；
  `capabilities.py` 不在禁改区清单里（`base.py` 的 `EXTERNAL` 注释逐字登记了这一点）。
- **本批没有改、但要报给父代理的一处同类问题**（不在我的文件清单里，按并发写者纪律不顺手改）：
  `tests/test_capabilities_two_layer.py:127` 的 docstring 仍写"48 个动作必须恰好落进三格之一"
  —— 与 `R4-AN-2` 同一族（手抄数字过期，实测 49）。该文件不在任何一批的文件清单里，故未动。

## 9. 证据文件

| 文件 | 内容 |
|---|---|
| `temp/fix6_F4_precheck.py` | 改前的四条事实读数（`matching_tool_name` / 对账面 / warning 数 / 词表关系） |
| `temp/fix6_F4_probe.py` | 正控 + 负控（甲/乙/丙/丁）探针本体，自校验，不满足期望即退出 1 |
| `temp/fix6_F4_probe.txt` | 探针原始输出（4 节，全部 ok，失败项 0） |
| `temp/fix6_F4-tests.txt` | 10 个相关测试文件的 pytest 原始输出（222 passed） |
| `temp/FIX6-F4-before_*.py` | 四个文件的改前逐字节备份 |
