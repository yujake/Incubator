# 角色规格（草案）—— V（验证者）

> **落地状态（2026-10-06）：V 已经进默认角色集** —— `schema.ROLES == ("A","B","C","D","E","F","G","H","V")`
> （9 个可召唤角色 + 主控 M = **10 个角色**）、边 29 → **32**（新增 `M→V`、`F→V`、`V→F`）、
> 动作 55 → **58**、工具 78 → **81**（`verify.verify_proof` / `verify.list_verifications` /
> `verify.read_proof` 加进已有的 `tools/verify_tools.py`）、只读角色 C/H → **C/H/V**。
> **因此角色的判据在 `docs/ROLE-SPECS.md` §V**（`python tools/verify_role_specs.py` 的默认角色集
> 已经含 V，报 `10 个角色节（A B C D E F G H V M）`）；本文件只剩**过程留痕**，
> 下面几节按落地后的实测数字同步过一遍。
> 依据：`draft/39` §3.21（用户 2026-10-05 定案"新增角色 V"）与 §6 批④/批⑤；
> 声明真身 `src/agentflow/specs/v.py`，实现 `src/agentflow/agent_v/`，读写在 `src/agentflow/verifications.py`。
> 单独检查本文件：`python tools/verify_role_specs.py --roles V --doc docs/ROLE-SPECS-DRAFT-V.md`
> —— 这一跑会同时与现场装配对账（V 的工具条数必须是 **14**）。

## V —— 验证者（Verifier）

### V.1 一句话定位

把 F 交回来的**一份证明**按写成后的样子整体重读，给三态结论并签"审过"（五元位第 3 位）。

### V.2 职责

1. **I12 冷启动**：每次审校开新会话，只给对象（证明全文）与只读读数（命题 / 文献 / 实验台账的摘要）；
2. **I10 硬禁令 + 同段依据**：逐条查无条件前提、无依据的步骤、"易证 / 显然 / trivial"这类缝、
   引用的命题是否干净；每条问题**指到那一步**并给理由；
3. **I17 整篇重读**：按写成后的样子整体读（缝正是"正确的事实变成错误证明"的地方）；
4. 签"审过"：只有 `verdict="成立"` 且 findings 无未解决 error 才允许把第 3 位置 true。

### V.3 明确不负责

- 不写、不改证明（那是 F）；
- 不判"这条命题值不值得做、下一步往哪儿走"（那是 D）；
- 不做稿件级正式审查（那是 H）；
- 不碰数据面（只读），只写自己的验证台账（一个**文件**，不是表）。

### V.4 工具面（14 个，实测）

`side_effect` 分布：`{'read': 14}` —— 0 个写工具、0 个需审批。**V 是只读角色**
（`tools.READ_ONLY_ROLES == ("C","H","V")`）。

| 工具 | 类型 | 作用 |
|---|---|---|
| `verify.verify_proof` | `read` | 读证明全文 + 只读读数 ⇒ 三态结论 + findings（每条指到步号），写 `verifications/<命题号>.jsonl`（六位编号，旧四位仍可读） |
| `verify.list_verifications` | `read` | 列验证台账（可按命题过滤） |
| `verify.read_proof` | `read` | 按命题号读回被审的那份证明全文（+ sha256 + 最近一次结论） |

现场实测的 14 个：上面 3 件 + `fs.list` `fs.read` `fs.search` `fs.stat` +
`table.count` `table.get` `table.list` `table.schema` `table.search` +
`manuscripts.read` `manuscripts.list`（后 11 件是"每个角色都有的那几件"，
装配器把实时角色表注入了它们）。

### V.5 状态机

`收到提交 → 冷启动读整篇 → 出 findings → 给结论（成立 / 有毛病 / 看不出来）→
落台账一行（`v-NNNN`）→ [成立且无未解决 error ⇒ 签第 3 位] → 交回 F`；
"有毛病"时回到 `收到提交`（同一份或改过的版本，新的一行，不覆盖）。

### V.6 预算与终止条件

一轮评审只花一次模型调用（整篇一次读，I17）；超预算 / 没接线 ⇒ 如实报"没查成"
（`checked=False` + `reason="judge_not_wired"`），**不许**降级成"看不出来"
（那是两个不同的东西）。

### V.7 三态与失败模式

- `成立` / `有毛病` / `看不出来` 是**对证明的结论**；
- 输出不合法 / 字段缺 / 取值不在词表 ⇒ **没查成**（`VerificationError`，工具回报
  `reason="unparsable"`），不写台账行；
- `有毛病` 必须给 `defect_step`（指不到步 = 让作者猜）；
- 没有证明全文 ⇒ `reason="no_proof_text"`；命题号不是编号形态（六位，或旧四位）⇒ `reason="bad_statement_id"`。

### V.8 不变式

1. 台账只追加、编号由脚本发（`v-{S.format_id(1)}` ⇒ 六位，如 `v-000001`；发号点是
   `verifications.next_verification_id` 的 `f"v-{S.format_id(len(rows) + 1)}"`，
   宽度只有 `schema.ID_DIGITS` 一处可改）；文件是 `verifications/<命题号>.jsonl`（六位编号）。
   **2026-10-18：编号规格是六位，四位号仅读侧兼容** —— 盘上已有的 `v-0001` 这类旧四位号
   照样读得进来（`schema.is_valid_id` 两种形态都认），但**新写的号一律六位**；
2. 第 3 位只在 `成立` 且无 error 时被签；
3. 冷启动：提示词里没有 F 的叙述、没有 store 句柄（由函数签名保证）；
4. **V 不写任何表**：`capabilities.WRITE_SETS["V"] == frozenset()`，`schema.TABLES` 17 张不变；
5. 边：`ALLOWED_EDGES["V"] == {"F"}`；V 只能被 M 召唤。

### V.9 接口

- 输入：`statement_id`（六位编号，旧四位仍可读）+ `proof_text`（不给时从 `statements` 取）+ `readonly_facts`
  （已渲染的只读读数，是**字符串**而不是 store 句柄）；
- 输出：一行台账 + `bit3_payload()`（五元位第 3 位那份读数）。

### V.10 自检入口

`python -m agentflow.agent_v`（`selftest()`：冷启动提示词、三态、签位条件、追加式编号、`limit=0`；
实测 16 条 `[PASS]`、退出码 0）。
