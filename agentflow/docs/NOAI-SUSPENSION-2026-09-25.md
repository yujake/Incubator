# NOAI-SUSPENSION-2026-09-25 —— 禁改区（FC-27）**临时开放**记录

> **本文件是治理记录，不是清单、不是台账、不是批准。**
> 它登记一次**所有者授权**：在一段有明确终点的窗口里，
> **暂停**"禁改区改动必须先由人编写 / 人逐行走查"这道**顺序**要求，
> **不暂停**禁改区本身，也**不暂停**任何机器可执行的门。
>
> **三份东西的分工不许混**（与 `NOAI-REVIEW-REGISTER.md` 开头同一张表）：

| 文件 | 是什么 | 本次开放对它的影响 |
|---|---|---|
| `.noai-paths` / `AGENTS.md` 标记区块 | 禁改区**清单**（14 条命中路径 / 7 类），两处逐条一致 | **一个字节都没动**。清单保持原样 ⇒ `--check-consistency` 继续绿 |
| `.noai-approvals.json` | hash **台账**：`sha256` 钉住"被批准的那一版" + `reviewers`（人） | **AI 不写 `reviewers`**；`--baseline` 仍可刷新 hash（登记 ≠ 批准） |
| **本文件** | **临时开放的授权与边界**：停了什么、没停什么、什么时候可以复闭 | 新建（AI 起草，授权来自所有者，见 §1） |

**生效时刻（观测）**：2026-09-25（本记录撰写会话本地时间 `2026-09-25 22:37` 起）。
**状态**：**开放中（suspension in effect）**。

---

## 1. 决定与范围

### 1.1 所有者授权（**逐字**）

> "禁改区里的问题有点多，先开放吧，做得足够好了再封闭回去。"

- **决定**：**临时开放**禁改区（suspension），**不是**拆除禁改区。
- **生效日期**：**2026-09-25**（文件名即生效日；本记录的观测时刻见每处数字旁的时间戳）。
- **终点**：不是日历日期，而是 §3 的**可判定判据集**——"做得足够好了"在本文里被翻译成
  8 条命令 + 期望输出。

### 1.2 暂停的是什么（**只有这一条**）

**暂停**：禁改区改动**先经人编写 / 人逐行走查**这道**前置顺序**。

- 开放期内，AI **可以直接改**命中 `.noai-paths` 的文件（含 `schema.py` / `store.py` /
  `verify.py` / `tools/base.py` / `tools/__init__.py` / `pyproject.toml` 等），
  **不需要先等人写、也不需要先等人逐行走查**。
- 理由（所有者的原话）："禁改区里的问题有点多" —— 欠账已经积到
  **14 个条目 × 2 名 reviewer = 28 份走查**（见 §3.5），
  而 14 条**全部**未获批准；先走查再改，会把每一轮改动都卡在同一个人的队列上。

### 1.3 **没有**暂停的是什么（逐条，别读成"全放开了"）

| # | 没有暂停 | 判据（怎么知道它还活着） |
|---|---|---|
| N1 | **所有权授权本身**只覆盖"顺序"，不覆盖"可见性" | `--check-consistency` 退出码 **0**；`--check-approvals` 继续报 `requires_human`、退出码 **1**（§5 实测①④） |
| N2 | 禁改区**清单**（两处逐条一致） | `.noai-paths` 与 `AGENTS.md` 的 `NOAI-MANIFEST` 区块**一字不动**；`check_manifest_consistency` 按 `(glob, category, 理由)` 三元组按位比对 |
| N3 | **门继续判"命中、需 2 名 reviewer"** | `python scripts/noai_gate.py --check-approvals --paths <14 条>` ⇒ `[requires_human] required_approvals=2`、**14 条未获批准**、退出码 **1** |
| N4 | `.noai-approvals.json` 的 **`reviewers` 只能由人填** | `reviewers_total` 仍为 **0**；理由码 `ledger_self_approval`（台账不能批准自己）与"`--baseline` 永远不写 `reviewers`"两条**照旧有效** |
| N5 | 台账的 **hash 登记纪律** | 每次禁改区改动后仍跑 `--baseline`（见 §2.2）；否则门报 `stale` 并同时打印两个 hash —— 这是**只有台账能给**的证据（本仓库没有 git，见 §4） |
| N6 | **只做已登记条目**的方针 | 改动必须能指向 `docs/PROPOSALS.md` 的 **P- 类**条目或 `draft/22` §12 的排期（§2.4） |
| N7 | **不可逆操作**的额外前置 | `SCHEMA_VERSION` / `LOCK_ORDER` / `_atomic_write` / `id 分配` / 删受控词表取值 / 迁移 —— 仍要求**回滚方案 + 备份 + 一次自检证据**，缺一不得动手（§2.5） |
| N8 | 本项目的一般工程纪律（三态、FC-03、证据带原始输出） | 见 `AGENTS.md` 与 `DEVELOPMENT.md`；本记录只**追加**顺序豁免，不豁免任何判据 |

> **一句话**：开放的只是"**谁先动**"，不是"**有没有人看**"。
> 门继续显示这笔债（`requires_human` + `required_approvals=2`），
> 台账继续记"改了什么"，只是**签字被允许迟到**（复闭时一次性补签，见 §3.8）。

---

## 2. 开放期仍然生效的底线（逐条 + 判据）

这 6 条**不是建议**。每条都写明"怎么判它有没有被破"。破一条 ⇒ 这次改动**不算**开放期改动，
按越界处置（登记 + 待 2 名 reviewer，见 `NOAI-REVIEW-REGISTER.md` §3.3）。

### 2.1 `reviewers` **永远不许 AI 代填**（签字是人的动作）

- **纪律**：AI 不许跑 `--approve`、不许手写 JSON 的 `reviewers`、不许写"走查结论"代替人的结论。
- **为什么**：填 `reviewers` 等于**自己给自己发批准**，那正是 FC-27 要防的形态。
- **判据（两条，都可机械跑）**：

  ```text
  python scripts/noai_gate.py --check-approvals --paths .noai-approvals.json
  ⇒ 永远 unapproved / ledger_self_approval（台账不能批准自己，与 hash 与人数无关）

  python D:\Incubator\temp\ledger_check.py
  ⇒ `reviewers` 数组的元素总数 reviewers_total = 0（开放期开始时的基线）
  ```

  本记录撰写期间**实测**：`reviewers` 元素总数 = **0**（§5 的 `--check-approvals` 输出逐条
  给出 `0/2 名不同 reviewer`）。**这个数字在开放期只会因为"人签了字"而变大** ——
  若它在没有人的情况下变大，就是一次违规。

### 2.2 每次禁改区改动后仍跑 `--baseline` 刷 hash（**登记 ≠ 批准**）

- **纪律**：改完一个命中文件，立刻 `--baseline` 把新 hash 登记进台账，并在本记录/登记表里记下"改了什么"。
- **为什么**：没有 git（§4），台账的 `sha256` 是**唯一**能回答"你改的是不是当初那一版"的东西。
  不刷 ⇒ 门报 `stale` 并打印两个 hash —— 那不是"通过"，是"账对不上"。
- **命令与判据**：

  ```powershell
  python scripts/noai_gate.py --baseline --paths <被改的文件…>
  # 期望：写入本题的新 sha256；reviewers 仍为空数组（登记 ≠ 批准）
  python scripts/noai_gate.py --check-approvals --paths <被改的文件…>
  # 期望：不再是 stale（改为 insufficient_reviewers）；仍然 [requires_human]、退出码 1
  ```

- **⚠️ 复闭时要先说清**：`--baseline` 换对象会**清空该条已有的批准语义**
  （`NOAI-REVIEW-REGISTER.md` §2.4 第 4 步）。开放期频繁刷 hash 会让"复闭时补签"针对
  **最后一版**——这是刻意的：签字针对被交付的那一版，不针对中间态。

### 2.3 改动前**先备份**到 `D:\Incubator\temp\`（命名含时间戳）+ 登记备份路径

- **纪律**：动任何禁改区文件**之前**，把它复制到 `D:\Incubator\temp\`，
  文件名**必须含时间戳**（形如 `<原名>.bak-YYYYMMDD-HHMMSS`），
  并把该路径写进本次改动的记录（留痕在 `NOAI-REVIEW-REGISTER.md` 与/或本轮报告）。
- **为什么**：这是**没有 git 时唯一的回退手段**（§4 第 2 条）。备份不在记录里 = 没人知道回哪去。
- **判据**：

  ```powershell
  Get-ChildItem D:\Incubator\temp -Filter '*.bak-*' | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,LastWriteTime
  # 每条禁改区改动记录里给出的备份路径，必须能在这一列里找到（文件名含时间戳）
  ```

- **反例（不许发生）**：只有"我改之前看过原文"这句话，没有文件。**那不是备份。**

### 2.4 只做**已登记条目**（不许"顺手重构"、不许顺手清装饰）

- **纪律**：开放期的每次改动必须能指向 `docs/PROPOSALS.md` 的 **P- 类条目**
  或 `draft/22` §12 的排期批次。范围之外的东西**不许顺手动**。
- **明确不许**：
  1. **顺手重构**（把"改 A"扩成"顺便把 B 也理一理"）；
  2. **顺手清装饰**（禁改区里的 Markdown 强调标记 / emoji）——
     装饰**另有条目**，且清它会让已登记的 hash 全部作废、把人一大片无功能 churn 拖进逐行走查
     （`NOAI-REVIEW-REGISTER.md` §2.7 的三条理由）。
- **判据**：本次改动的 diff 涉及的每个文件/符号都能在 `PROPOSALS.md` 或 `draft/22` §12 里
  找到**对应的编号**；找不到编号的改动 ⇒ 越界登记（不是"小事不值一提"）。

### 2.5 **不可逆操作**在开放期**仍要求**：回滚方案 + 备份 + 一次自检证据

> 这是开放期**唯一**"顺序被暂停、门槛没降"的一档。**缺任一项不得动手。**

- **哪些算不可逆**（逐条点名，不是"你判断"）：
  `schema.SCHEMA_VERSION` 变更 · `store.LOCK_ORDER` · `store._atomic_write` · `id 分配`
  （`store.alloc_id` / `interactions.next_prefixed_id`）· **删除受控词表取值** · 任何**迁移**。
- **动手前必须齐三样**：
  1. **回滚方案**：写清"出问题怎么退"——退到哪一版、退哪些文件、退完跑什么；
  2. **备份**：§2.3 的带时间戳副本，路径登记在案；
  3. **一次自检证据**：一个**能红的负控**或一条**实测命令 + 原始输出**
     （"我认为它没问题"不算证据）。
- **判据**：改动记录里这三样缺任一项 ⇒ 该改动**不许合并**；已合并的按越界登记并回滚或补证据。
- **为什么**：这一类错误的代价是**数据毁灭级**（`.noai-paths` 逐字）——
  开放的是"谁先写"，不是"写错了还能不能救"。**这一类没有 git 兜底，只有备份。**

### 2.6 每条改动必须**自己跑并贴**四类命令

**（a）全量**：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
python -m pytest tests/ -q
```

**（b）规则 linter**：

```powershell
python scripts/lint_rules.py          # 期望 error 0（复闭判据 §3.4；今天实测 error 2）
```

**（c）清单一致性**：

```powershell
python scripts/noai_gate.py --check-consistency    # 期望：一致，退出码 0
```

**（d）⭐ 每个被改文件的相关测试文件**单独跑一次（**不是**只跑全量）：

```powershell
python -m pytest tests/test_<那个模块>.py -q
```

- **为什么要单独跑（这条是实测逼出来的）**：本项目已发现**顺序依赖**——
  `tests/test_fc17_wiring.py` **单独跑红 / 全量跑绿**。
  全量绿因此**不能**证明单文件绿：pytest 的收集顺序把状态喂给了它。
  ⇒ 判据是"**两种跑法都绿**"，只有一种绿等于没绿。
- **⚠️ 本记录撰写时的实测更正（请与时间一起读）**：撰写会话（2026-09-25 **22:37**）
  在默认环境下单独跑 `python -m pytest tests/test_fc17_wiring.py -q` ⇒ **`10 passed`，退出码 0**。
  也就是说：**"单独跑红"这一条在今天这个时点上没有复现**。
  它可能是被别的改动顺手治好了，也可能是**另一重顺序/环境依赖**（例如 Lean 在 `PATH` 上与否）。
  **处置**：判据不变（两种跑法都要绿），但**不许**把"曾经红过"当成"现在也红"，
  也**不许**把"今天单跑绿"当成"顺序依赖已消失"——复闭前必须**逐个测试文件单独复跑**（§3.3）。
- **每个改动还要跑被改文件本身的负控/正控**（如 `tests/test_noai_gate.py`、
  `tests/test_proposals_register.py`），并在报告里贴原始输出。

---

## 3. 复闭判据（"做得足够好了"必须是**可判定**的）

> 复闭 = 把 §1.2 暂停的那道顺序**装回去**。
> 下面 8 条**全部满足**才允许复闭；每条给**命令 + 期望输出**。
> 任何一条只做到"接近"（例如"大部分测试文件单跑绿"）⇒ **不许复闭**。

### 3.1 所有 P- 类条目关闭，或被**明确降级**为 G/N

- **命令**：

  ```powershell
  Select-String -Path docs\PROPOSALS.md -Pattern '^## P-\d+'
  ```

- **期望**：`PROPOSALS.md` 里**不再有未关闭的 P- 条目**。
  "关闭"的写法是条目标题带 `✅ **已关闭**`（照 `G-2`/`G-3`/`G-4`/`G-6`/`G-7`/`G-12` 的既有形态）；
  "降级"必须在**条目正文**里写明"降为 G/N + 依据"，
  并同步更新 `draft/22` §12 的排期（编号与批次都要跟着改，**不许留悬空引用**）。
- **并且**：`draft/22` §12 的**批次一 / 三 / 四全部完成**
  （批次定义见该文件 §12.3 与 §12.6.3）。
- **守护门**：`python -m pytest tests/test_proposals_register.py -q`
  ⇒ 现在实测 **`4 passed`**，退出码 **0**；复闭时仍须 `4 passed`
  （它守"编号唯一 / 引用存在 / 空洞写明"三条，改 `PROPOSALS.md` 必然触及它）。

### 3.2 `python tools/release_all.py` **0 fail**

- **命令**：

  ```powershell
  python tools/release_all.py
  ```

- **期望**：**0 fail**。`unknown` **允许**，但**每一条 `unknown` 都必须在记录里逐条解释**
  （"为什么这次是没查成，而不是没问题"）—— 理由：`unknown ≠ clean`。
- **注意**：`tools/release_all.py` **自身在禁改区**（`release-deploy`）⇒
  开放期改它要按 §2 走；复闭时它也必须被补签（§3.5）。

### 3.3 **每个测试文件单独跑** 0 failed；且**两种环境**（默认 / Lean 在 `PATH`）全量 0 failed

- **命令（逐个文件，不是通配）**：

  ```powershell
  # 默认环境
  Get-ChildItem tests\test_*.py | ForEach-Object {
    python -m pytest $_.FullName -q
    # 期望：每一行都是 `N passed`（0 failed）；把退出码连同文件名单一起贴出来
  }
  python -m pytest tests/ -q          # 期望：0 failed

  # 第二种环境：Lean 在 PATH 上（W3/W5 轮用的那种），重跑上面两条
  $env:PATH = "D:\Incubator\temp\lean470\lean-4.7.0-windows\bin;" + $env:PATH
  ```

- **⚠️ 写这条判据时的一条禁令（血泪教训，抄自 `PROPOSALS.md` 的 `G-27` / `N-8` 第 1 条）**：
  上面那个 `ForEach-Object` **不许**配裸 `$LASTEXITCODE` 判成败 ——
  `foreach` 里 `$LASTEXITCODE` 会取到管道末端（`Select-Object` / `Where-Object`）的退出码，
  实测因此**误报过 `agent_c` / `agent_d` exit 1**（实际 8 个 agent 自检全部 exit 0）。
  ⇒ 必须**逐条直跑**，或显式取 `$?`，或让每个文件单独一行一个命令。
  **判据工具的假阳性会把人训练成不看红灯**（`DEVELOPMENT.md` §6 的 P15）。

- **期望**：**所有**测试文件单跑 **0 failed**，**并且**两种环境下全量 **0 failed**。
- **⚠️ 当前状态（如实）**：撰写会话实测全量 `python -m pytest tests/ -q`
  ⇒ **`2 failed, 1787 passed, 8 deselected, 1 xfailed`**，退出码 **1**。失败两条都在
  `tests/test_lint_rules.py`（`R009` 的两条：`test_r009_flags_bold_and_emoji_in_comment_and_docstring`、
  `test_r009_zone_hits_are_info_not_error`）—— 即 §3.4 那个 `error 2` 的**同一件事**。
  ⇒ **今天不满足复闭条件**，这一条是**开放期要还的第一笔债**。
- **为什么必须逐个文件**：见 §2.6(d) 的顺序依赖证据（`tests/test_fc17_wiring.py`）。

### 3.4 `python scripts/lint_rules.py` ⇒ **`error 0`**

- **命令**：

  ```powershell
  python scripts/lint_rules.py
  ```

- **期望输出（逐字形态）**：

  ```text
  [linter] error 0 / warning N / info M
  ```

- **当前实测（2026-09-25 22:37 前后）**：`[linter] error 2 / warning 3 / info 21`，退出码 **1**。
  两条 `error` **都是 `R009`**：`src/agentflow/capabilities.py:1378`（9 处）与
  `scripts/lint_rules.py:923`（4 处）—— 这两处**不在**禁改区（可由 AI 改），
  且 `tests/test_lint_rules.py` 已因此红（§3.3）。
- **判据不许写成"error 接近 0"**：`--strict` 会把 `warning` 也算失败，
  但**复闭的门槛是 `error 0`**；`warning` 的处置按既有登记（`G-1` 的 R004 两处 `warn`
  **必须继续可见**，不许加豁免）。

### 3.5 `--check-approvals --paths <全部 14 条>` ⇒ 走查后为 **`14 28`**

- **命令（14 条 = `.noai-approvals.json` 的全部条目，不是 `.noai-paths` 的 glob 数）**：

  ```powershell
  python scripts/noai_gate.py --check-approvals --paths pyproject.toml scripts/release_check.py `
    src/agentflow/dedup.py src/agentflow/extract.py src/agentflow/interactions.py `
    src/agentflow/providers.py src/agentflow/quoteverify.py src/agentflow/schema.py `
    src/agentflow/store.py src/agentflow/tools/__init__.py src/agentflow/tools/base.py `
    src/agentflow/tools/verify_tools.py src/agentflow/verify.py tools/release_all.py
  ```

- **期望（复闭时）**：**14 条全部已批准 × 2 名 reviewer = `14 28`**（28 份走查记录，署名是**人**）。
- **当前实测（本记录撰写时，逐字见 §5④）**：
  `[requires_human] required_approvals=2`、**14 条未获批准**
  （`insufficient_reviewers` **12** 条 + `stale` **2** 条）、退出码 **1**。
  按"文件 × 人数"记就是 **`14 0`**。
- **⚠️ 两条 `stale` 必须先定版**：`src/agentflow/tools/__init__.py`
  （台账 `f0838932dcb2` ≠ 盘上 `69272d9746a3`）与 `src/agentflow/tools/base.py`
  （台账 `ca910534d980` ≠ 盘上 `1b6ccc4e30a6`）。
  定版动作：确认以哪一版为复核对象 ⇒ 必要时 `--baseline`（**会清空该条批准语义**）⇒ `--approve`。
- **这一步**AI 只能做前一半（定版/刷新 hash），**后一半（签字）必须人做**（§2.1）。

### 3.6 禁改区 `R009` 装饰计数：**要么归零、要么按"区间 + 观测时刻"明确接受**

- **命令**：

  ```powershell
  python scripts/lint_rules.py | Select-String 'R009.*禁改区'
  ```

- **两条路，人选一条并写进复闭记录**：
  1. **归零**：禁改区 13 个文件里的装饰处数降到 **0**（并按 §2 走查 + 补签）；
  2. **明确接受**：写明一个**区间**（不是单点）+ **观测时刻** + 接受的依据
     （例如"这些文件按 FC-27 只能由人改，本项不计入判据；清它的性价比低于走查风险"）。
- **为什么不许写单点**：**并发下这个数字不可复现**。实测：
  同一会话内 **455 → 457 → 462**；本记录撰写时两次相邻读数**都是 477**
  （**2026-09-25 22:37:13** 与 **22:43:39**，两次都逐字为
  `禁改区 13 个文件里仍有 477 处装饰（schema.py=133、tools/base.py=57、interactions.py=55、verify.py=48、tools/verify_tools.py=35…）`）——
  `NOAI-REVIEW-REGISTER.md` §2.7 记的上一轮读数是 **430**。
  **这几个数都是各自时点的真实读数**，差异来自"这几轮禁改区文件本身被改过"（新增注释也带星号）；
  本会话两次读到同一个数**不能**推出"它稳定了"。
  ⇒ 正确写法：**"禁改区 R009 ≈ 4xx 处（区间 430–480，观测时刻 2026-09-25 22:37–22:44，Python 3.11.4，默认环境）"**。
- **注意 `R009` 的另外两条 `error`**（`capabilities.py` / `lint_rules.py`，非禁改区）
  走 §3.4，**不**属于本条的"禁改区计数"。

### 3.7 `NOAI-REVIEW-REGISTER.md` 的走查包（§2.3–§2.7）全部签完

- **命令**：

  ```powershell
  Select-String -Path NOAI-REVIEW-REGISTER.md -Pattern '待走查'
  ```

- **期望**：§6 的批准签名区里**不再有"待走查"**；
  §2.3 的 8 条 + §2.1 另外 6 条（`dedup.py` / `interactions.py` / `providers.py` /
  `quoteverify.py` / `tools/__init__.py` / `tools/base.py`）**共 14 条**全部有 2 名 reviewer；
  §2.4 签字流程走完（`--approve` 之后复跑门 ⇒ 退出码 **0 `clean`**）。
- **判据与 §3.5 是同一件事的两种视角**：§3.5 看**机器台账**，本条看**人读镜像**；
  两者必须一致（不一致时**以台账为准**，并订正登记表）。

### 3.8 复闭动作（**谁做什么，逐条**）

复闭不是"说一句恢复"，是**四个动作**：

1. **把本记录标"已复闭"**：在本文顶部加一行
   `**状态：已复闭（closed on <日期>）**` + 指向支撑它的原始输出（§3.1–§3.7 的命令输出）；
2. **更新 `NOAI-REVIEW-REGISTER.md`**：把 §3.7 的签名补完，并在其增补节里写明
   "开放期（2026-09-25 起）的欠账**已一次性补齐**" + 逐条 hash；
3. **在 `PROPOSALS.md` 登记关闭**：把开放期关闭的 P- 条目按既有形态标 `✅ **已关闭**`
   （含"由谁、哪次、什么证据"——`PROPOSALS.md` 维护规则第 2 条），
   并**升一条新编号**记录"复闭"这件事本身；
4. **把暂停的顺序装回去**：`AGENTS.md` / `.noai-paths` **本来就一字未动** ⇒
   无需恢复动作；要恢复的是**执行习惯**（AI 命中禁改区 ⇒ 停、等人写或人逐行走查）。

> **第 4 条是本次记录最重要的设计**：因为**没有拆掉任何东西**，
> 复闭不需要"重建清单"、不需要"逐字还原"、不需要动一致性门。
> 这也是为什么**不许**用"删掉 `.noai-paths` 的条目"的方式来实现这次开放（§4 第 1 条）。

---

## 4. 风险与代价（**诚实写，不修饰**）

1. **开放期 AI 直改 schema / 存储 / 权限面的风险是真实的，而且测试抓不到它。**
   `AGENTS.md` 引用的原话是 *"测试全绿、上线即越权"*。开放期把这道人审顺序移到事后，
   等于**把"越权/数据毁灭"的发现时点从"改动前"推到"补签时"**。
   缓解手段只有 §2 的六条底线，其中**最硬的一条是 §2.5**（不可逆操作三样齐备），
   因为它挡的是**唯一一类"发现时已经晚了"的错误**。
2. **本仓库不是 git 仓库 ⇒ 没有版本回退，只有备份。**
   `noai_gate.py --git` 在这个仓库里**永远**返回 `unknown(2)`；`NOAI-REVIEW-REGISTER.md` §5
   第 1 条把这条结构性限制写死了："`--baseline` 之后能机械抓到的是**从此往后的漂移**，
   抓不到**已经发生的**那次改动内容。"
   ⇒ 备份（§2.3）不是"好习惯"，是**唯一**的回退手段；备份没做 = 那次改动**不可回退**。
3. **台账的 `sha256` 能回答"是不是同一版"，不能回答"这一版对不对"。**
   `NOAI-REVIEW-REGISTER.md` §5 第 2 条逐字："hash 一致 ≠ 实现正确。"
   开放期更容易把"hash 已登记"误读成"已审过"——**登记是机器动作，审查是人的动作**。
4. **债不会因为改得快而变小，只会因为走得快而积累。**
   开放期每改一个禁改区文件就多一份**待补签**（`--baseline` 只写 hash、不写 `reviewers`）。
   本记录撰写时全库欠账是 **14 × 2 = 28 份走查**（`draft/22` §12.4 按 0.5–1.5 人时/份
   折算成 **14–42 人时**）；开放期**只会把它推高**。
   ⇒ 因此 §3 的复闭判据里，"把签字补齐"（§3.5 / §3.7）**不是收尾工作，是复闭的前置条件**。
5. **"先开放"会改变人的行为，而不只是流程。** 一旦"命中禁改区"不再触发"停"，
   最可能的失效形态是**范围蔓延**（顺手重构、顺手清装饰）——
   这正是 §2.4 单独列一条的原因。**范围蔓延不产生自己的红灯。**

---

## 5. 一条方法论纪律：开放期的一切"当前真值"数字必须写成**区间 + 观测时刻**

**仓库正被并发修改，单点数字在这里是假话。**

实测证据（**同一会话内**漂移，全部是这个仓库里发生过的）：

| 数字 | 观测到的值（同一会话内） | 出处 |
|---|---|---|
| 禁改区 R009 装饰处数 | **430 → 455 → 457 → 462 → 466 → 477**（**同一天，约 20–30 分钟内**，含本记录撰写时的 **477 / 477**：22:37:13 与 22:43:39） | 本记录 §3.6 / §5.1、`PROPOSALS.md` `G-32`、`NOAI-REVIEW-REGISTER.md` §2.7 |
| 零直接测试的公开函数 | **106**（等级 3/4），另有"被间接覆盖 51"的**上下界**口径 | `PROPOSALS.md` `G-9` / `G-10` |
| 公开函数总数 / R007 口径 | **499**（`G-9` 快照）vs **625**（本记录撰写时 `lint_rules` 的 R007 读数）| `PROPOSALS.md` `G-9` vs §5 实测 |
| 工具数与声明核对数 | **55 个工具**（`G-4`/`N-4` 口径）vs R010 实测"逐工具核对了 **58** 条声明" | `PROPOSALS.md` `G-4` vs §5 实测 |

**规则（开放期强制）**：

1. 任何"当前真值"数字（装饰处数、测试数、工具数、函数数、人时）**必须**写成
   **区间 + 观测时刻 + 观测环境**，形如：
   `禁改区 R009：约 430–480 处（观测时刻 2026-09-25 22:37–22:5x，Python 3.11.4，默认环境）`；
2. **不许**在别处引用一个固定数字（`NOAI-REVIEW-REGISTER.md` §2.7 已把这条写成纪律）；
3. 两个读数不一致时，**两个都要保留**并注明各自时刻 —— 那是"仓库在动"的证据，
   不是"其中一个错了"；
4. **`unknown` / `stale` / `xfail` 仍然是三态里的独立档**：漂移的区间**不许**把
   "没查成"折进"查过了"。

### 5.1 本记录撰写时的四条门命令 —— **原始输出（逐字贴，未加工）**

> 环境：`D:\Incubator\agentflow`，`Python 3.11.4`，
> `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'`，
> 观测时刻 **2026-09-25 22:44:26**（本地）。

```text
[1] python scripts/noai_gate.py --check-consistency
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
EXIT=0                                        ← 证明清单一处未动

[2] python -m pytest tests/test_proposals_register.py -q
....                                                                    [100%]
4 passed in 0.29s                             ← 编号纪律（唯一 / 引用存在 / 空洞写明）通过
EXIT=0

[3] python -m pytest tests/test_noai_gate.py -q
................................................s....................... [ 80%]
.................                                                       [100%]
88 passed, 1 skipped in 8.50s                 ← 台账与门未被破坏
EXIT=0

[4] python scripts/noai_gate.py --check-approvals --paths <全部 14 条>
[requires_human] required_approvals=2
requires_human：命中 14 条禁改区路径，其中 **14 条未获批准**
（insufficient_reviewers 12 条、stale 2 条）⇒ 必须由人编写或人逐行走查，并需要 2 名 reviewer 批准。
台账：D:\Incubator\agentflow\.noai-approvals.json
EXIT=1                                        ← 如实：这是"没签"，不是"没问题"
```

**第 [4] 条的两条 `stale` 逐字**（它们必须先定版，见 §3.5）：

```text
  - src/agentflow/tools/__init__.py  ⇒ [unapproved] stale：台账里被批准的那一版是 f0838932dcb2，
      盘上现在这一版是 69272d9746a3 —— 两者不是同一版。
  - src/agentflow/tools/base.py      ⇒ [unapproved] stale：台账里被批准的那一版是 ca910534d980，
      盘上现在这一版是 1b6ccc4e30a6 —— 两者不是同一版。
```

**⚠️ 贴这四条时必须一起贴它们的局限**：这四条**只是时刻快照**（§5 的规则对它们同样适用）——
同一天里 `R009` 禁改区计数读到过 **430 / 455 / 457 / 462 / 466 / 477**，
`tests/test_noai_gate.py` 读到过 **`89 passed`（22:36 前后）** 与 **`88 passed, 1 skipped`（22:44）**
（这一处的差异来自 `tests/` 正在被并发修改，本记录未核实是哪一个改动造成的）。
⇒ **不要把本节任何数字抄到别处当定值。**

---

## 6. 本记录的维护规则

1. **本文件不是清单、不是台账、不是批准。** 它不改门、不改判据；它只登记"顺序被暂停了多久"。
2. **`.noai-paths` 与 `AGENTS.md` 一处都不许因为本记录而改**——
   本记录的存在**不构成**对清单的任何修改授权。要改清单，走 `PROPOSALS.md` 的 `P-18` 那条路
   （两处同改 + `--check-consistency` + 人单独做）。
3. **开放期的每次禁改区改动都要在 `NOAI-REVIEW-REGISTER.md` 留一行**（改了什么、
   备份在哪、`--baseline` 后的 hash），并在**复闭时一次性补签**。
4. **复闭后本文件不许删**：它记录的是"我们曾经暂停过 FC-27 的顺序"这一事实，
   以及"凭什么允许复闭"。删掉它，下一个人会以为禁改区从来没有被开放过。
