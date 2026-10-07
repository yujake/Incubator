# draft/64 两个 golden 的**逐格归因表**（人审用；HEAD → 盘上累计面）

- 目的：`AGENTS.md` 的登记理由要求"重冻必须由人**逐格**看过"。这份表就是给人审的那张逐格表。
- 只读、可复算。两个脚本都在 `temp/`，都不改盘：
  - `python -B temp/_golden_diff_cells.py` —— 逐格列表（哪一格变了）
  - `python -B temp/_golden_cell_reasons.py 6` —— 逐格**差在哪**（长文本给行级 diff 的头几行）
  - 落盘副本：`temp/R0-golden-cells.md`、`temp/R0-golden-cell-reasons.md`
- 归类口径 = `draft/63 §8` 的**十一类**（本次未新增第十二类，见 §5）。

---

## §1 三分钟怎么读

1. 看 §2 的**格数**：累计 **70 格**（agent 面 25 + tool 面 45）。
2. 看 §3/§4 的**主类**列：每格都有一个主类。**任何一格归不进 ①–⑪ ⇒ 我该停下报你**（本次没有）。
3. 看 §5 的两条"要注意"：**④ 与 ⑥ 没有独占格**（它们只作为内容落在九个 prompt 格里）；**③ 与 ② 共用一格**。这不是第十二类，但它是"十一类白名单"这套口径第一次暴露的形状，值得你看一眼再签。

---

## §2 格数：70 格，而 B 报的是 19 格 —— 两个数都对，量的是两件东西

| 量的是什么 | 格数 | 出处 |
|---|---|---|
| **HEAD → 最终（累计面）** —— 人审要看的那个面 | **agent 25 + tool 45 = 70** | 本表（`_golden_diff_cells.py` 实测） |
| B **自己那一批**造成的格 | agent 14 + tool 5 = 19 | `draft/63 §8` 末、"B 的探针 + 报文"（`temp/b_probe_golden_cells.py`） |

**为什么不一致（逐条对得上，不是漏报）**：B 那 19 格里**不含** ①（V 接线：`role_count`/`roles.V`/`tool_roles`/`cli.*`/`declarations.*.roles`/`summary.*`…）、②/③ 的 `conductor.closing.*`、⑤（`roles.M.init_signature`）。那些是 V 与 C 的落地，本来就该由它们各自的账记（`draft/59 §5`）。累计面把人审需要的**全部**变格摊开，所以是 70。

**给 B 的一条更正（记在我账上）**：B 的 §4.1 标题写"实测的差异格清单"，读起来像"整个重冻只有这些格"。它实际量的是"B 自己写过的格"。累计面必须由主控算（本表），不能让每条线各报各的 —— 否则人审拿到的是一堆局部清单，没人能回答"到底动了几格"。

---

## §3 agent 面 25 格（`tests/golden/agent_surface_snapshot.json`）

| # | json 路径 | 主类 | 凭据（一句话；`→` 前后 = HEAD → 盘上） |
|---|---|---|---|
| 1 | `read_only_roles.length` | ① | 2 → 3：V 是只读角色（13 步全 `read`） |
| 2 | `role_count` | ① | 9 → 10：V 入册 |
| 3 | `role_registry.V` | ① | 新增 `["str","function"]`：V 的构建入口 |
| 4 | `roles.A.actions.length` | ⑦ | 4 → 5：裁决 2 族 1 给 A 加 `A.shelf_search`（J-53） |
| 5 | `roles.A.handler_signatures.shelf_search` | ⑦ | 新增，签名 `(self, *, query='', limit=20, lit_id='', local_limit=5, max_chars=1200) -> dict` |
| 6 | `roles.A.prompt` | ⑧ | 14607 → 15187（+35/-26 行）；同格还落 ⑦（新增动作要教）与共享块的 ③⑤⑥ |
| 7 | `roles.B.actions[1].params.properties.proof_text.description` | ⑨ | P-06：`proof_text` 由"必需"改成"**可以不给**"（缺它 ⇒ 降档并进待办，不拒收） |
| 8 | `roles.B.actions[1].summary` | ⑨ | 同上（summary 里那句硬校验同步改写） |
| 9 | `roles.B.prompt` | ⑧ | 14099 → 14503（+31/-23）；删掉共享层那句与两处历史注脚 |
| 10 | `roles.C.prompt` | ⑧ | 12715 → 13179（+28/-19）；同格 ⑥（补 `judge_bad_verdict`/`judge_ungrounded_findings`）+ ③（七种→八种、`to="#public"`） |
| 11 | `roles.D.prompt` | ⑧ | 21126 → 21577（+32/-23） |
| 12 | `roles.E.prompt` | ⑧ | 19538 → 19232（**净减 306**）；同格 ⑥③ + S-10(a) 那半句（E 的政策） |
| 13 | `roles.F.edges.length` | ① | 5 → 6：`[A,B,C,D,E]` → `[A,B,C,D,E,**V**]` |
| 14 | `roles.F.init_signature` | ⑨ | 217 → 268：多 `budget_reading` 参数（P-09 代码半） |
| 15 | `roles.F.prompt` | ⑧ | 19714 → 20680（+34/-24） |
| 16 | `roles.G.prompt` | ⑧ | 28644 → 28941（+53/-42）；同格 ④（体例）②（九节段） |
| 17 | `roles.H.prompt` | ⑧ | 23863 → 24414（+49/-38）；**"八、交付说明的九节形状"整段删除** = ②（R9 废九节，改由 M 声明体例） |
| 18 | `roles.M.edges.length` | ① | 8 → 9：`[A..H]` → `[A..H,**V**]` |
| 19 | `roles.M.init_signature` | ⑤ | 270 → 295：多 `secretary` 参数（A 的秘书接入） |
| 20 | `roles.M.prompt` | ⑧ | 41887 → **39459**（+79/-67，**净减 2428**，全场最大一格）；同格 ④⑩⑪②③⑤⑥ |
| 21 | `roles.V` | ① | 新增整份角色声明（3 个 `verify.*` + 11 个只读工具） |
| 22 | `schema_roles.length` | ① | 8 → 9 |
| 23 | `tool_roles.length` | ① | 9 → 10 |
| 24 | `tool_roles[8]` | ① | `M` → `V`（V 排在 M 前） |
| 25 | `wiring_status.V` | ① | 新增 `wired` |

**agent 面主类计数**：① 10 · ⑤ 1 · ⑦ 2 · ⑧ 9 · ⑨ 3 ＝ 25 ✓

---

## §4 tool 面 45 格（`tests/golden/tool_surface_snapshot.json`）

同因合并写（同一原因、同一读法，逐格列出来只是把 45 行摊成 45 行）：

| # | json 路径 | 主类 | 凭据 |
|---|---|---|---|
| 1 | `cli.` | ① | 工具总数 78 → **81**；各角色工具数里多 `'V': 14`；只读泄漏 `{'C':[],'H':[],'V':[]}` |
| 2 | `cli.--json` | ① | 工具名清单里插进 `verify.list_verifications`/`read_proof`/`verify_proof`；`count` 78 → 81 |
| 3–10 | `cli.--role A` … `cli.--role H`（8 格） | ① | 只有一行变：`工具总数：78` → `81`（长度不变 ⇒ 逐字节 diff 只看得出这个数） |
| 11 | `cli.--role V` | ① | 新增：`角色 V 可用工具（14 个）` |
| 12 | `declarations.attack.step.returns` | ⑨ | 键集尾部多 `budget_known`、`budget_reading`（P-09 代码半） |
| 13 | `declarations.conductor.closing.returns` | ③ | **同格 ②**：321 → 719 chars，`status 的键是**七格**` → `**八格**`（多 `artifact_ledger`） |
| 14 | `declarations.conductor.closing.summary` | ② | 315 → 385：`报告九节齐全` → `报告体例兑现（R9 之后门不自带节名清单，逐节核的是 M 自己声明的体例）` |
| 15 | `declarations.conductor.ledger.summary` | ⑩ | 115 → 276：补"口径（`task_count` 与 tree 的行数）数的是 `tasks` **全量**，含**顶趟行**" |
| 16 | `declarations.conductor.state.summary` | ⑩ | 52 → 220：同上口径（`tasks` 这一格含顶趟行） |
| 17–24 | `declarations.{fs.list,fs.read,fs.search,fs.stat}.roles.length` + `.roles[8]`（8 格） | ① | 每对我一格：`9 → 10`，且 `roles[8]` 由 `M` → `V` |
| 25–31 | `declarations.{manuscripts.list,manuscripts.read,table.count,table.get,table.list,table.schema,table.search}.roles.length`（7 格） | ① | 每格 `8 → 9`（V 进只读工具的 roles） |
| 32 | `declarations.verify.check_formal.returns` | ⑪ | 211 → 223：键集尾部多 `exit_code`（E 族证据链） |
| 33–35 | `declarations.verify.{list_verifications,read_proof,verify_proof}`（3 格） | ① | 新增三份声明（params/returns/roles=`['V']`） |
| 36 | `readonly_write_leaks.V` | ① | 新增 `[]`（V 没有写工具） |
| 37–38 | `roles.V`、`roles_with_m.V`（2 格） | ① | 新增 14 个只读工具名 |
| 39–41 | `signatures.verify.{list_verifications,read_proof,verify_proof}`（3 格） | ① | 新增 `(statement_id=None, limit=None)` 等 |
| 42–45 | `summary.count`、`summary.params_checked`、`summary.tools.length`、`summary.tools[77]`（4 格） | ① | 78 → **81**；`tools[77]` 由 `verify.run_experiment` → `verify.list_verifications`（三件新工具排在 `run_experiment` 前后，字典序） |

**tool 面主类计数**：① 39 · ② 1 · ③ 1 · ⑨ 1 · ⑩ 2 · ⑪ 1 ＝ 45 ✓

---

## §5 归并：十一类各自的格数，与两条要注意的

| 类 | 主类格数 | 落点 |
|---|---|---|
| ① V 的 13 步接线 | **49** | agent 10 + tool 39（`cli.*` 11 · `declarations.*.roles` 15 · `verify.*` 3 · `summary.*` 4 · 其余 6） |
| ② C 的第八格（含 R9 的连带面） | **1** | tool `closing.summary`（+ agent 的 G/H/M prompt 里那几行） |
| ③ B 的同步 | **1** | tool `closing.returns`（**与 ② 同格**） |
| ④ R-1 提示词 | **0** | 只在 `roles.M.prompt` 里面（`REPORT-STYLE` / 体例归 M） |
| ⑤ A 的秘书接入 | **1** | agent `roles.M.init_signature` |
| ⑥ C 的码表收敛 | **0** | 只在九个 prompt 的共享块里（`judge_bad_verdict` / `judge_ungrounded_findings`） |
| ⑦ 裁决 2 族 1（`shelf_search`） | **2** | agent `roles.A.actions`、`roles.A.handler_signatures` |
| ⑧ P 族提示词按内容删改 | **9** | agent 九个 `roles.*.prompt`（+ `roles.V` 里那份新 prompt） |
| ⑨ P 族代码半 | **4** | agent `roles.B.actions`(×2)、`roles.F.init_signature`；tool `attack.step.returns` |
| ⑩ 顶趟行口径 | **2** | tool `ledger.summary`、`state.summary` |
| ⑪ E 族证据链接线 | **1** | tool `verify.check_formal.returns` |
| | **70** | 与 §3+§4 的格数逐格加得上 |

**结论（人审要看的那一句）**：**70 格全部归进 ①–⑪，没有第十二类** ⇒ 没触发 `draft/63 §8` 末那条"停下报主控"。

**要注意的两条**（都不是异常，但都是这套白名单第一次露出的形状，值得你判一句）：

1. **④ 与 ⑥ 没有独占格。** 九个角色 prompt 里都内联了同一份共享块（`LOOP_PROTOCOL`/`SHARED_FACULTIES_NOTE`/三态段），所以共享块改一句 ⇒ **九格同时变**。后果：格数**不能**当"改动量"读 —— ①（49 格）看着最大，其实大部分是 V 入册这条一次性的事实传播；④⑥ 看着是 0，其实内容都在那九格里。
2. **③ 与 ② 挤在同一格**（`closing.returns`：八格 = ②，受控档清单 = ③）。B 报"tool 面 5 格 = ⑨+③+⑩×2+⑪"时把这一格记成 ③，我记成 ③ 兼 ② —— 同一格、两个原因，拆不开。

---

## §6 复算（只读，两条命令）

```powershell
cd D:\Incubator
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"
python -B temp\_golden_diff_cells.py            # 70 格逐格列表（哪一格变了）
python -B temp\_golden_cell_reasons.py 6        # 每格差在哪（长文本给行级 diff 头 6 行）
```

判据：第一条命令的"共 N 格变化"必须是 **25**（agent）与 **45**（tool）；
第二条命令里每一格要么是"短值 → 短值"，要么是"长文本：X→Y chars，+a/-b 行" —— 后者是用来判 ⑧ 的删改量的。

## §7 我标"不确定"的格

**0 格。** 70 格每格都有 diff 证据，且都对照过 `draft/63 §8` 的类别定义逐字。

**但有一条口径是我的、你可以改**："主类 vs 同格的多类"这个分法（§5 的计数按主类）。若你要求"一格只许归一类、多类即停下报"，那 §3 有 9 格（九个 prompt）、§4 有 1 格（`closing.returns`）要报 —— 我按"同格多类是内联共享块的必然结果、不是新类别"处理了，理由写在 §5。

---

## §8 **R2b 起的第二轮**（预登记：新类 + 逐格账，**冻结日期待最后一次重冻**）

> 口径：J-47"只许一次性重冻"，且**每一轮都要在本表的归因表里加类**（不许并进原十一类）。
> 第二次重冻的所有者授权 = **`search.literature` 加 `providers=[…]`**（R2b-⑱，2026-10-07 单独授权）+
> `agent_prompts.py:456` 的"五条全过"（R6，同一次授权里的另一条）。**两条都会落在这一轮**。

### §8.1 **新类：⑫（R2b 预登记）—— "给一个既有工具加一个参数"**

定义：**声明面在既有工具上加/改一个参数**（不新增工具、不新增角色、不改权限面）。
它的射程是**三处**，而且**必须一起看**（这是本类与 ①–⑪ 都不同的地方）：

| 面 | 格 | 为什么 |
|---|---|---|
| tool 面 | `declarations.<工具>.params.properties.<参数>` | 参数表是声明的真身 |
| tool 面 | `declarations.<工具>.returns` | 返回形状会跟着多一套读数（本例多了 `sources[]` / `cost` / `providers_requested` / `source_count` / `source_failures` / `source_refusals`） |
| tool 面 | `signatures.<工具>` | 函数签名逐字 |
| **agent 面** | `roles.<角色>.prompt` | **声明面传播**：提示词里那张"可选参数"表是**现渲染**的 ⇒ 加了参数，拿着这个工具的那几个角色的提示词**自动多一个词** |

**R2b-⑱ 的实测（2026-10-07 02:31，我用 `temp/_golden_vs_live_cells.py` 现算的"冻结版 → 盘上"）**：
- agent 面 **1 格**：`roles.A.prompt`（15,187 → 15,197 字符）。
  **已逐字归因**：全文 diff **只有一行不同** ——
  ```
  - search.literature：…（必填 topic；可选 description、limit、mode、provider）；副作用 read
  + search.literature：…（必填 topic；可选 description、limit、mode、provider、providers）；副作用 read
  ```
- tool 面 **3 个叶**（测试粒度 = 2 格）：`declarations.search.literature.params.properties.providers`（新增）·
  `declarations.search.literature.returns`（483 → 704 字符）· `signatures.search.literature`
  （`(topic, mode='topical', description='', limit=10, provider='openalex')` → `…, providers=None)`）。

⇒ **这一轮"格数不能当改动量读"的第二次实例**：一条"加一个参数"的改动 = **4 个叶**，
其中 **1 个在 agent 面**（提示词），而且它**不是**谁去改了提示词 —— 是渲染出来的。

### §8.1b **新类：⑬（R6 预登记）—— "把提示词里的一句定值/陈旧陈述改成现算"**

定义：**改提示词正文里的一句话**（不动工具面、不动角色面），通常是把"手抄的定值/陈旧计数"换成"由当次读数给"或"框架现渲染"。
射程：**共享段改一句 ⇒ 拿到那一节的每个角色各一格**（与 §8.1 的"声明面传播"同族，但这次是**人写的**不是渲染的）。

**R6 第一段的实测（2026-10-07 04:4x，`temp/_golden_vs_live_cells.py` 现算"冻结版 → 盘上"）**：
| 面 | 格 | 逐字归因 |
|---|---|---|
| agent | **4 格** | `roles.A.prompt`（⑱ 的声明面传播，见 §8.1）· **`roles.G.prompt` / `roles.H.prompt` / `roles.M.prompt`**（各 **+70 字符**，`PAPER_PACK` 共享段改一句 ⇒ 拿到该段的三个角色同时变） |
| tool | **3 个叶** | 同 §8.1（⑱ 的那三处），**与 R6 无关** |

`roles.{G,H,M}.prompt` 那一格我**逐字 diff 过**（只一行不同，两处 hunk）：
```
- `documents.claims` 有 24 条断言，每条四列：来源（自证/文献/未决）、证据等级、…
+ `documents.claims` 每条断言四列：来源（自证/文献/未决）、证据等级、…
+   我方核到什么程度、能否证伪（条数由当次台账读数给，这里不写死）。
```
⇒ 这正是 `draft/63 §3` 的**第 3 条真缺陷**（"24 条断言"是随工作区变的定值）；同段另一处 hunk 是"五条全过"那一句（`agent_prompts.py:456`）。
**为什么算"新类"而不并进 ⑫**：⑫ 是"**框架渲染**跟着声明面走"（改的是数据，提示词自动变），本类是"**人改提示词正文**"（改的是文字）——两者都要人逐格看过，但**原因与责任人不同**（前者归 ⑱ 的工具面改动，后者归 R6 的删改决定）。

### §8.2 复算命令（第二轮）```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"
python -B D:\Incubator\temp\_golden_vs_live_cells.py          # **冻结版 → 盘上**（重冻要签的就是这个面）
python -B D:\Incubator\temp\_golden_diff_cells.py             # HEAD → 盘上（累计面，只作对照，**别拿它签**）
```
⚠️ 两个面**不是一回事**：R0 那次是"HEAD → 盘上"（因为那时 HEAD 就是基线）；**R2b 起基线是"冻结版"** ⇒
签的时候必须用第一条命令，用第二条会把"从头累计的 70 格"再算一遍。

### §8.3 第二次重冻的**前置**（写在这里免得漏）
1. 等 R2b 收工（A 的 ⑫⑬⑲ 与 B 的 ⑱ 全部落地）⇒ 重跑 §8.2 第一条命令，把**增量格**逐格抄进本表；
2. R6 之前**不冻**（R6 还要改 `agent_prompts.py:456` ⇒ 会再动 agent 面）；
3. 冻完必须重跑两个快照用例**以及它们旁边那两条负控**（`test_the_comparison_actually_sees_a_change` 这类
   负控有"基线本身对不上 ⇒ 先跑 --write"的前置断言 ⇒ 基线没冻时它必红，**冻完必须复跑确认绿**）；
4. 冻完重采 `draft/59` 的两张单（goldens 的 sha 变了 ⇒ 待签清单会变）。

### §8.4 **冻结前最后一次复算（= 要人签的那张面，逐格封闭）**（2026-10-07 05:0x）

执行时机：**A / B / C 三条线全部报"停手"之后**、重冻之前。命令 = §8.2 第一条（冻结版 → 盘上）。
读数：**agent 面 4 格 + tool 面 3 格 = 共 7 格，一格不多、一格不少**，且**全部落在 §8.1 / §8.1b 已预登记的类里**：

| # | 格 | 类型 | 归属 | 逐字原因 |
|---|---|---|---|---|
| 1 | `roles.A.prompt` | 声明面传播 | ⑫（R2b-⑱） | 15,187 → 15,197 字符；`search.literature` 那行多一个 `providers`（§8.1 已逐字给出） |
| 2 | `roles.G.prompt` | 人改提示词 | ⑬（R6） | 28,941 → 29,087 字符（**+70**）；`PAPER_PACK` 共享段两句（§8.1b 已逐字给出） |
| 3 | `roles.H.prompt` | 人改提示词 | ⑬（R6） | 24,414 → 24,560 字符（**+70**）；同上共享段 |
| 4 | `roles.M.prompt` | 人改提示词 | ⑬（R6） | 39,459 → 39,545 字符（**+86**，比 G/H 多 16 字符 = M 那一节另有"报告体例由 M 裁定"的条件渲染差异） |
| 5 | `declarations.search.literature.params.properties.providers` | 新参数 | ⑫（R2b-⑱） | 冻结版 `<缺>` → 盘上 `<dict>` |
| 6 | `declarations.search.literature.returns` | 返回形状 | ⑫（R2b-⑱） | 483 → 704 字符（多 `sources[]`/`cost`/`providers_requested`/`source_count`/`source_failures`/`source_refusals`） |
| 7 | `signatures.search.literature` | 函数签名 | ⑫（R2b-⑱） | 70 → 86 字符（尾部多 `providers=None`） |

**"没多出来的格"要一起交代（否则人审无法判断"是不是漏看了"）**：
- **R3（写侧与产物落盘）· R5-组 4（断言级污染面）· R7-⑯/⑰ 的落地改动**——改的是 `closing.py` / `verify.py` / 若干测试，
  **一个格都没动声明面**（本表读数 4+3 与 R2b/R6 之后完全一致，就是证据）。
- **⑤ 已在更早一轮冻过**：`agent_prompts.py:456` 的"五条"→"八格"**落在这一轮**（§8 开头口径说的两条授权之一），
  已包含在上表 2–4 号的 `+70/+86` 里。
- 本轮的**文档面改动**（`docs/READING-MAP.md` §3 行号、`docs/ROLE-SPECS.md` 待改的 §318）**不进 golden**
  （golden 只冻 agent 声明面与 tool 声明面，不冻文档）。

⇒ **结论（要人签的那句话）**：第二次重冻的改动面 = **7 格**，来源 **2 个类**（⑫ 工具加参数 3 叶 + 声明面传播 1 格；⑬ 人改提示词 3 格），
**每一格都能指到一条已授权的改动**，**没有"说不出原因"的格**。

### §8.5 **重冻执行记录**（一次性、已做、可复算）（2026-10-07 05:1x）

**执行前提**：**A / B / C 三条线全部报"停手"**（B、A 先停，C 最后一份报告到后才动手）⇒ 此后 `src/ tests/ docs/ tools/ scripts/` 未再改一个字节。

| 步 | 命令 | 读数 |
|---|---|---|
| ① 抄增量格 | `python -B temp/_golden_vs_live_cells.py` | agent **4 格** + tool **3 格** = **7 格**（逐格见 §8.4） |
| ② 重冻 | `python -B tests/test_agent_surface_snapshot.py --write` | exit 0，写入「10 个角色，59 条动作」 |
| ② 重冻 | `python -B tests/test_tool_surface_snapshot.py --write` | exit 0，写入「81 个工具 / 10 个角色 / 11 条 CLI 输出」 |
| ③ **立即复跑** | `python -B -m pytest -q tests/test_agent_surface_snapshot.py tests/test_tool_surface_snapshot.py` | **`5 passed`（6.23 s）** —— 与 R0 基线**同一个读数**（两条快照用例 + 三条旁证/负控：`test_the_surface_is_whole_and_not_vacuous`(×2) · `test_the_comparison_actually_sees_a_change`） |
| ④ 增量格归零复核 | `python -B temp/_golden_vs_live_cells.py` | **agent `0 格` · tool `0 格`** ⇒ 冻结版与盘上**逐字一致** |

**golden 的 sha 变化（登记用）**：

| 文件 | 重冻前 | **重冻后（当前）** |
|---|---|---|
| `tests/golden/agent_surface_snapshot.json` | `1ccf9237f843…` | **`95250e3a176c…`** |
| `tests/golden/tool_surface_snapshot.json` | `a22c78a62068…` | **`da87baf0f80b…`** |

⚠️ **R1–R3 的门里如实记为"本轮未能执行"的那两条负控，本轮已补跑并全绿**（它们的首句前置断言是
`assert not _differences(golden, live), "基线本身对不上 ⇒ 先跑 --write"` ⇒ 基线没冻时必红、且还没轮到跑真正的负控断言；
冻完复跑 = 前置成立 + 负控本体（改三个字节必须分别报出来）也成立）。
⚠️ **重冻 ⇒ `draft/67` 的待签清单已复采**（两个 golden 由"冻结前的 sha"换成上面这两个；档位仍是 `unregistered`）。
⚠️ **R8 落地之后不需要再冻第二次**（2026-10-07 10:0x 更正，先前这里写的是"若之后还有 R8 落地就再冻一次"）：
R8 的 **A-1…A-9 全部落在文档面与一个入口**（`cli.py` 的 `MENU`/`_shell_demo`/`SHELL_ACTIONS` 与四个根文档），**声明面一格都没动** ⇒ **第六趟门的 §4 仍是 `5 passed`**（这就是证据）。
⇒ 按 J-47，本轮的声明面变化**已经全部被 05:1x 那次一次性重冻吸收**，**不存在"待发生的第二次重冻"**。

### §8.6 **第三次重冻：R6-⑥"结构性搬移"之后**（2026-10-07 10:5x 起，进行中）

> ⚠️ **为什么又有一次**：J-47 的原话是"声明面变化攒到 **R7 后与 R8 后各一次性重冻**"。
> R8 之后**没有**再冻（见上）；但 **R6 的"结构性搬移"是一次真正的声明面变化**（改的是每个角色拿到的那份提示词），
> 而它是**在 R8 之后才开的一刀**（前两轮 B 因预算停手、我另开了一条线来做）。⇒ **这一次是对 R6-⑥ 的冻结**，不是"逐条重冻"。

**它改什么**（详见 `draft/63 §2-⑥` 与本次派单）：`LOOP_PROTOCOL`（所有角色共用的常量）里**三块只有主控 M 用得到**的文本 ⇒ 改成**按角色渲染**：
- `[a]` "主控（M）派活时留痕…别的角色派活不必带。"（`LOOP_PROTOCOL` L12–L17）
- `[b]` "主控（M）例外：它的 final 是给用户的回复，不必带 notify。"（L66）
- `[c]` `2b) 一次唤起一批…`（L19–L29，含 L25 那句"主控派这一批时同样走上面 2) 那段留痕"）

**渲染条件只有一个**：`role == S.CONDUCTOR_ROLE`（M）。⚠️ **不能用"动作表里有没有 `summon_many`"**：M 的动作表是**空的**（`specs/m.py:29` 逐字 `ACTIONS: tuple[ActionSpec, ...] = ()`），M 的动作在 conductor 工具面上。

**设计上"不许失败"的那条判据**：M 分支**直接 `return LOOP_PROTOCOL`**（不重新拼装）⇒ **`roles.M.prompt` 逐字节不变**。

**主控自取的改前/改后基线**（`temp/_r6_prompt_baseline.py`，口径 = `build_registry(...)` → `system_prompt(role, registry=…)`，与快照用例同源）：

| 角色 | A | B | C | D | E | F | G | H | V | **M** |
|---|---|---|---|---|---|---|---|---|---|---|
| 改前字符（**HEAD 只读 worktree** 渲染） | 15197 | 14503 | 13179 | 21577 | 19232 | 20680 | 29094 | 24560 | 12709 | **39545** |
| 改后字符（工作树渲染） | 14311 | 13617 | 12293 | 20691 | 18346 | 19794 | 28208 | 23674 | 11823 | **39545** |
| **差** | **−886** | **−886** | **−886** | **−886** | **−886** | **−886** | **−886** | **−886** | **−886** | **0** |

**✅ 主控独立复核（2026-10-07 11:0x，不是采信子代理的账）**：在 **HEAD 的只读 worktree**（`temp/head-wt-r6`）与工作树上用**同一个工作区**（`temp/r6-fixed-ws`）各渲染一遍十角色，再逐行比：
- **九个角色各恰好少 886 字符**（= 那三块的合计）；
- **M 的原文 468 行 → 468 行，逐行 diff 只差一行**：`- 提示词版本：p37` → `- 提示词版本：p38`（正是我们主动 bump 的版本记号）⇒ **"M 逐字节不变"成立（模掉版本记号那一行）**。

⚠️ **三条方法论留痕（前两条是我踩过的）**：
1. **我的第一版"改前基线"取样与子代理的首次改盘撞车**（它在 10:52:26 写盘、我就在前后取的样）⇒ 差集一度报"十个角色一个都没变"（**假读数**）。**正确做法 = 从 `HEAD` 检出源码渲染**（`git worktree add --detach`，"与 HEAD 比"这条纪律对提示词面同样适用）。
2. **M 的 sha 在两次运行间会变**：提示词里**嵌着 `PROMPT_VERSION`** ⇒ "逐字节不变"**不能只看 sha**，要比字符数 + 逐行 diff（或把版本记号那行排除后再算）；且**比 sha 必须固定工作区**（提示词里也嵌工作区相关事实，随机 `mkdtemp` 会让 sha 天然不同）。
3. **探针的输出路径必须带 tag**：我的 dump 目录一开始只按工作区名派生 ⇒ 第二次跑**把第一次的原文覆盖了**（这是同一族事故的第三次：`_prompt_facts_probe.py`、`_ocr_notext_scan.py`、本探针）。已改成 `r6-prompt-text-<tag>-<ws>/`。

**预期增量格 = 10 格**：`roles.{A,B,C,D,E,F,G,H,V}.prompt` 各 1 格 + **`roles.M.prompt` 1 格（只差版本记号那一行）**。
**逐格字符数（按 [c] 的作用域更正后）**：
- **C：−886 字符**（三块全删：它出边为空，`summon_many` 对它完全不可用）；
- **A/B/D/E/F/G/H/V 各 ≈ −319 字符**（只删 [a]+[b] 两块 M 专段 + 分隔换行）；
- **M：0**（只有 `提示词版本：p37 → p38` 那一行）。

> ⚠️ **一处更正（2026-10-07 11:4x，我派单的前提错了，执行方抓出来的）**：我最初把 [c]（`2b) 一次唤起一批…`，565 字）也写成"只有 M 用得到"，
> 依据是"按**角色动作表**算，十角色都没有 `summon_many`"。**那个判据不是真身**：M 的动作表本来就是空的（`specs/m.py:29`），非 M 的动作表也不含 conductor 工具。
> **真身是三条**（我逐条现算过）：① `agent_loop.py:2757` 把 `conductor=self.conductor` 传给**所有角色**的循环；② `conductor.py:1326` 按 **`frm=by`**（调用者自己）过**边表** ⇒ 非 M 只要有出边就能派活；③ `JSON_TAIL` 每步发给所有人，含 `summon_many` 骨架。
> **而普查的原话只点了 C**：`draft/63 §2-⑥` 逐字"**C 的 `summon_many` 整段 555 字在 C 完全不可用**（边为空）"。
> 实测出边：**只有 C = 0 条**；A=1 · B=1 · D=5 · E=2 · F=6 · G=4 · H=3 · V=1 · M=9。
> ⇒ **[c] 的作用域改成"该角色出边非空"**（用 `capabilities.ALLOWED_EDGES` 真身数据判，不写死 `role != "C"`）⇒ **今天恰好只有 C 失去它**。
> 判据要把 **[a]/[b]（M 专段）与 [c]（出边非空）分开断言**。

**归因类**：仍归 **`§8.1b` 的 ⑬（"把提示词里的东西按改正"那一族的顺延）**？—— **不**：本次**不是**改文字，是**改收件人/作用域**，
⇒ 按 J-47"每一轮都要在本表的归因表里加类"的要求，**本类记为 ⑭：`§8.6` "把只有某角色用得到的共享段改成按角色渲染"**（与 ⑫ 的"框架渲染跟着声明面走"不同：本类改的是**共用的那句话发给谁**）。
⚠️ 若重冻时看到**超出这 10 格**（第 11 格起，尤其**工具面**格跟着动）⇒ **停下报所有者**，不许并进"预期"。
