# 审计派单模板（把每个派单回合压到十几行 —— 细节让审计者自己去读文件）

> 为什么要有它：轮次是按**父代理的回合**消耗的，而派单文本如果每次重述协议，
> 一个派单回合就要几百行。**协议、批次清单、三条约定都已经在文件里**，
> 派单只需要说"你是谁、审哪批、读哪几个文件、交什么"。

## 派单前（父代理，两条都要做）

1. `list_agents` ⇒ 确认没有 writer 在跑；
2. `python temp/run_gates.py <标签> --check-only --assert-no-writers` ⇒ **exit 0**
   （读数 `temp/<标签>-gates.txt`；exit 2 且点名文件 = 有写者 ⇒ 不派）。

## 任务文本模板（把 `{批}` / `{一句话主题}` / `{冻结集}` 三处填掉即可）

```
你是 `D:\Incubator\agentflow` 的**独立重审者**（第 5 轮 · 批次 {批}：{一句话主题}）。
你**没有写过**这批代码；本批的可写集合**只有** `D:\Incubator\temp\` 下你自己的证据文件。

**先逐字读这三个文件**（它们就是你的协议，本消息只补充本批特有的东西）：
1. `D:\Incubator\temp\reaudit5-COMMON.md` —— §0 窗口纪律、§0.1 前置门、§1 交付 JSON 字段、
   §2 每条 `verified_items` 的硬要求（正控 + 证明注入生效的负控）、§3 六批清单与"反着查"重点；
2. `D:\Incubator\temp\reaudit5-DISPATCH.md` —— **§0.2 的三条新约定**（冻结集=scope 清单 /
   静止证明要落档 / 旧探针可能已过期）以及 **{批} 那一节的本批增量**；
3. `D:\Incubator\draft\28-全面体检问题总清单、修复建议与交付标准.md` 的 **§40–§56**（父代理的处置
   与已知陷阱；你可以读它，但**必须自己重跑判据**，不许引用其中的读数当自己的读数）。

**本批冻结集（逐字，`files_sha256_before/after` 只放这些）**：
{冻结集}

**静止证明**：父代理已在 `temp/{标签}-gates.txt` 里落了"30 秒逐字节未变 + 操作者断言"，
把它抄进你 JSON 的 `notes`。窗口内若有别的文件被并行写者改了 ⇒ 写进 `notes` 当**观察**，
**不要**因此把 `sha256_unchanged` 报成 false（§0.2 约定一）。

**交付**：`temp/REAUDIT5-{批}.json`（字段见 COMMON §1）+ `.md` + `temp/REAUDIT5-{批}.sha-before.txt`
/ `.sha-after.txt` + 你的探针与读数 `temp/reaudit5-{批}-*.py|.txt`。
**判据**：`findings` 为空（0 条，含 low）才算这批通过；有 finding 就照实写，不许为了让它通过而放过。
**不许**放宽任何判据来"让 tests 变绿"；发现判据被放宽了，那本身就是一条 high finding。

**最后用中文报**：`findings` 数（按级别）、`verified_items` 里 `fix_holds=false` 的条目、
你**构造不出负控**的条目（如实说，不许算成强证据）、以及任何"读到一半发现协议与现实不符"的地方。
```

## 各批的填充值（冻结集照抄 COMMON §3 的"文件清单"那一行，一个不多一个不少）

| 批 | 一句话主题 | 冻结集来源 |
|---|---|---|
| `R1d` | 门与台账（`R1c` 修完之后的复验） | COMMON §3 R1 的文件清单 + `temp/batchR1c-*` 证据；**旧攻击探针要先修**（§0.2 约定三） |
| `R2b` | 证据链（第 5 轮 R2 作废后的重做，含 `Batch S` 的四项） | COMMON §3 R2 的 6 个源文件 + `quoteverify.py` + 它列的测试文件 |
| `R3` | 数据与并发（含 `批 Q` 的改动） | COMMON §3 R3 的文件清单 + `test_f4_page_level_tristate.py`、`test_store_r3_commit_order.py` |
| `R4` | 两轴与权限面（含 `批 Q` 的 `capabilities.py`、父代理的 `tools/base.py` 注释） | COMMON §3 R4 的文件清单 |
| `R5` | 编排与成本（含 `批 Q` 的 `runflow.py`） | COMMON §3 R5 的文件清单 |
| `R6` | 测试与文档（含 `批 N` 的发布门、`R1c`/`d09eea42` 的测试改动、README 数字修正） | COMMON §3 R6 的文件清单 |

## 收账（父代理，每批回来之后）

1. `findings` 逐条登记（新 id、级别、落点、**状态**、`temp/` 证据）；
2. 只要某批 `findings` 非空 ⇒ 开修复批（同一落点文件族）⇒ **回到"派单前"重跑门**（手册第 3 条）；
3. 六批全空 ⇒ 判据二成立，写进 `draft/28` 新节（含每批的 `sha256_unchanged` 与 `findings` 数）。
