# NOAI-SUSPENSION-2026-09-28 —— 禁改区（FC-27）**设计期临时开放**记录

> **本文件是治理记录，不是清单、不是台账、不是批准。**
> 它登记一次**所有者授权**：在一段有明确终点的窗口里，**暂停**
> "禁改区改动必须先由人编写 / 人逐行走查"这道**顺序**要求；
> **不暂停**禁改区本身，也**不暂停**任何机器可执行的门。
>
> 与 `docs/NOAI-SUSPENSION-2026-09-25.md` 的关系：**同一口径的第二次授权**，
> 不替代、不删除前一份（前一份 §6.4 逐字要求"复闭后本文件不许删"）。
> 本次窗口的对象是**设计期的结构性改动**（新对象、新契约、新判据），
> 而不是上一次那种"欠账集中清偿"。

**生效时刻（观测）**：2026-09-28（本记录撰写会话本地时间 `2026-09-28 21:5x` 起）。
**状态**：**开放中（suspension in effect）**。

---

## 1. 决定与范围

### 1.1 所有者授权（**逐字**）

> "打开禁改区的修改权限。设计都没设计好怎么能不让改"

- **决定**：**临时开放**禁改区（suspension），**不是**拆除禁改区。
- **理由（所有者原话的含义，不引申）**：设计尚未定型时，"先由人写 / 先由人走查"
  这道**顺序**会把设计迭代卡住 —— 而设计稿本身正在改（`draft/29`）。
- **终点**：不是日历日期，而是 §3 的**可判定判据集**（命令 + 期望输出）。

### 1.2 暂停的是什么（**只有这一条**）

**暂停**：禁改区改动**先经人编写 / 人逐行走查**这道**前置顺序**。

开放期内，AI **可以直接改**命中 `.noai-paths` 的文件（`schema.py` / `store.py` /
`verify.py` / `interactions.py` / `capabilities.py` / `tools/__init__.py` / `tools/base.py` 等），
**不需要先等人写，也不需要先等人逐行走查**。

### 1.3 **没有**暂停的是什么（逐条；别读成"全放开了"）

前一份记录（`NOAI-SUSPENSION-2026-09-25.md` §1.3）的 N1–N8 **全部继续有效**，
本次逐字沿用，并新增 N9：

| # | 没有暂停 | 判据（怎么知道它还活着） |
|---|---|---|
| N1 | 授权只覆盖"顺序"，不覆盖"可见性" | `--check-consistency` 退出码 **0**；`--check-approvals` 继续报 `requires_human`、退出码 **1** |
| N2 | 禁改区**清单**（`.noai-paths` 与 `AGENTS.md` 两处逐条一致） | 两处**一字不动**；`check_manifest_consistency` 按 `(glob, category, 理由)` 三元组按位比对 |
| N3 | **门继续判"命中、需 2 名 reviewer"** | `--check-approvals` ⇒ `[requires_human] required_approvals=2` |
| N4 | `.noai-approvals.json` 的 **`reviewers` 只能由人填** | 本窗口内 **AI 不写 `reviewers`**；签字留到复闭由人补（§3.6）。历史代记名（`owner-1`/`owner-2`）是 2026-09-27 一次**单独授权**的产物，已如实留在台账里，边界照旧：脚本核得了"存在/大小/年龄/哈希"，**核不了署名归属** |
| N5 | 台账的 **hash 登记纪律** | 每次禁改区改动后跑 `--baseline`（登记 ≠ 批准）；否则门报 `stale` 并同时打印两个 hash |
| N6 | **只做已登记条目** | 每次改动必须能指向 `draft/29` 的条目（`L-*` / `J-*` / §10.4 触点编号 / `T0–T4` 分层）或 `draft/28` 的登记行 |
| N7 | **不可逆操作**的额外前置 | `SCHEMA_VERSION` / `LOCK_ORDER` / 新表 / id 分配 / 删词表取值 / 迁移 —— 仍要求**回滚方案 + 备份 + 一次自检证据**，缺一不得动手 |
| N8 | 本项目的一般工程纪律（三态、FC-03、证据带原始输出） | 见 `AGENTS.md` 与 `DEVELOPMENT.md`；本记录只**追加**顺序豁免，不豁免任何判据 |
| **N9（新）** | **两条结构性未批准**永远存在，且**不算**开放期要清的账 | 实测（2026-09-28 21:5x）：24 条清单路径中 `approved 22 / ledger_self_approval 1 / unregistered 1`。`: .noai-approvals.json` 是**台账不能批准自己**；`src/agentflow/release_check.py` 是**登记时并不存在**。⇒ 任何 `release_all` 的 `[fail] noai` 都可能是这两条引起的，**不许**把它读成"这一版有问题"，也不许为了让它变绿去改清单 |

> **一句话**（与上一份相同）：开放的只是"**谁先动**"，不是"**有没有人看**"。

---

## 2. 开放期仍然生效的底线（逐条 + 判据）

前一份的 §2.1–§2.6 继续有效（`reviewers` 不许 AI 填 · 每次改动后 `--baseline` ·
改动前先备份到 `temp/` 并登记路径 · 只做已登记条目 · 不可逆操作的额外前置 ·
每条改动自己跑并贴命令）。**本次新增三条**：

### 2.7 每个 FC-27 改动必须能回答"它属于哪一层"

指向 `draft/29` §10.5 的分层（`T0` 非禁改区 / `T1` 数据面 / `T2` 判据面 /
`T3` 契约面 / `T4` 签名与内部引用），并写出它落在 §10.4 的哪一个触点
（①行 dataclass ②`TABLES` ③词表常量 ④`ID_COUNTERS` ⑤`LOCK_ORDER` ⑥`_VOCAB_BY_FIELD` ⑦`verify_all`）。
答不出这一句的改动，不许进本窗口。

### 2.8 不可逆操作的额外要求（本次窗口的具体形态）

| 操作 | 额外要求 |
|---|---|
| 加一张表 | **触点逐条对照**（`draft/29` §10.4；`draft/30` §T1 原写 7 处，2026-09-29 实现时实测为 **10 处**：`row_from_dict` 分支、`ARRAY_FIELD_KINDS`、`tests/conftest.DATA_FILES` 三处是漏掉的）；`LOCK_ORDER` 插入位置写明理由；**迁移窗口**：对每个**真的是项目**的目录非 force 跑 `init` 补表文件（`not_a_project` 的一律跳过 —— 先 `classify()` 再动手），并留一次"旧产物仍可核"的证据 |
| 改 `SCHEMA_VERSION` | 回滚方案（降到旧版本后旧数据仍可读）+ 备份 + 自检 |
| 动 `interactions.CONTRACT_VERSION` | 列出所有读它的调用点并一起改；证明"新旧契约不同时有效" |
| 动 `verify_all` 不变量 | 每条不变量必须带正控 + **注入负控**（把实现短路 ⇒ 判据必须变红） |

### 2.9 每次 FC-27 改动后必须自己跑并贴（读数带观测时刻）

```powershell
python scripts/noai_gate.py --baseline --paths <本次改动的路径>   # 登记，不批准
python scripts/noai_gate.py --check-consistency                    # 期望 0
python -m pytest tests/ -q -p no:cacheprovider                     # 期望 0 failed
python scripts/lint_rules.py                                       # 期望 error 0
```

四道门（`temp/run_gates.py`）不必每次改都跑，但**复闭前必须跑满一次**。

---

## 3. 复闭判据（"做得足够好了"必须是可判定的）

| # | 判据 | 期望 |
|---|---|---|
| 3.1 | `draft/29` 的 `T1–T4` 触点逐条有终态（落地 / 明确放弃 + 理由） | 无"待办但没人认领"的条目 |
| 3.2 | `--check-consistency` | 退出码 **0** |
| 3.3 | `--check-approvals --paths <全部清单路径>` | 回到 **`approved 22 / ledger_self_approval 1 / unregistered 1`**（即：除两条**结构性**债务外全部 approved；两条见 §1.3 N9） |
| 3.4 | lint / 全量 / 逐文件（两种环境） | `error 0`；`0 failed`；逐文件"单独跑不过 0" |
| 3.5 | `release_all` | ⚠️ **判据从"0 fail"改成"唯一红的必须是 `noai`，且其两条理由逐字是 `ledger_self_approval` 与 `unregistered`"** —— 原判据（`NOAI-SUSPENSION-2026-09-25.md` §3.2 的"0 fail"）在本仓的现状下**不可达**（实测两次门运行都是 `[fail] noai`，见 §6） |
| 3.6 | `NOAI-REVIEW-REGISTER.md` | 开放期每条改动留一行（改了什么 / 备份在哪 / `--baseline` 后 hash），**复闭时由人一次性补签** |
| 3.7 | 备份清单 | `temp/` 下每处 FC-27 改动各一份含时间戳的备份 + sha256 |

---

## 4. 风险与代价（诚实写，不修饰）

1. **顺序豁免的固有风险**：改动先落地、走查后补 ⇒ 若走查发现语义错误，**已经写进盘的东西**
   可能已被下游读取（本项目对"静默失效"最敏感的地方正是这里）。补偿：每条改动都要求
   **注入负控**（§2.8 第 4 行）与"默认路径逐字节不变"（`T0` 判据）。
2. **署名归属不可机械核实**：门只能证明台账里有 2 个**不同字符串**的名字与内容锚是否对得上，
   **证明不了**这几次走查互相独立（本机实测输出逐字如此）。代记名必须自报家门。
3. **`LOCK_ORDER` 改动的连带成本**：加锁顺序一动，**所有并发判据都要重测**
   （写集相交 ⇒ 串行、跨表事务原子性、`rebuild` 可重放）。这是本窗口最贵的一项。
4. **窗口读数会漂**：开放期内文件在变 ⇒ 任何"当前真值"数字必须写成 **区间 + 观测时刻**
   （沿用前一份 §5 的纪律）。

---

## 5. 本记录的维护规则

1. **本文件不是清单、不是台账、不是批准。** 它不改门、不改判据；只登记"顺序被暂停了多久"。
2. `.noai-paths` 与 `AGENTS.md` **一处都不许**因为本记录而改；要改清单走 `PROPOSALS.md` 的 `P-18`。
3. 开放期每次禁改区改动在 `NOAI-REVIEW-REGISTER.md` 留一行。
4. **复闭后本文件不许删**（与 09-25 那份同一规则）。

---

## 6. 本次开放期的起点读数（逐字，未加工）

窗口从**这一版树**开始 —— `post11` 四道门（`temp/run_gates.py post11`，
`2026-09-28T19:50:47` 起，`21:42:32` 止）：

```text
1) lint  exit=0  7.9s        [linter] error 0 / warning 0 / info 25
2a) 全量（默认）   exit=0  892.8s   2597 passed, 3 skipped, 8 deselected, 1 xfailed
2b) 全量（Lean）   exit=0  941.8s   2600 passed, 8 deselected, 1 xfailed
3a) 逐文件（默认） exit=0 1082.0s   共 128 个文件：过 127 / 单独跑不过 0
3b) 逐文件（Lean） exit=0 1115.7s   共 128 个文件：过 127 / 单独跑不过 0
4)  release_all   exit=1  2634.2s   counts={'pass': 5, 'fail': 1, 'unknown': 0}
     [fail] release-check (8 项中 1 项 fail)  →  [fail] noai
# 收工核对：本窗口内改动 0 / 新增 0 / 消失 0 / 仅 mtime 变 1（data/events.jsonl）
```

**第 4 条那一条红的逐字原因**（`--check-approvals` 实测，2026-09-28 21:5x）：

```text
requires_human：命中 24 条禁改区路径，其中 2 条未获批准
                （approved 22 条、ledger_self_approval 1 条、unregistered 1 条）
  - .noai-approvals.json          ⇒ ledger_self_approval（台账不能批准自己）
  - src/agentflow/release_check.py ⇒ unregistered（登记时并不存在）
EXIT=1
```

⇒ 这就是 §1.3 N9 与 §3.5 的来源：**这两条按设计永远是 unapproved**，
所以 `release_all` 的"0 fail"在本仓现状下**不可达**，复闭判据必须照 §3.5 写。
