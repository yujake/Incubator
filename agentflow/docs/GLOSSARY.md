# GLOSSARY.md —— 术语表（每个词一句话，并指到写着它的那一份）

> 用途：读别的文档时卡在一个词上，先来这里。每条只给**一句话定义 ＋ 权威落点**；
> 定义与权威冲突时以权威那份（最终以代码）为准。
>
> 收录口径：**这套系统自己造的、或在这个仓里有专门含义的词**。普通编程词（函数、测试、锁）
> 不收。同义词 / 旧名在最后一节单列。

## 一、运行与工作区

| 词 | 一句话 | 权威落点 |
|---|---|---|
| **工作区**（workspace） | 任何空目录都能当工作区：台账落 `<ws>/data/`，正文落 `<ws>/manuscripts/`，产物落 `<ws>/out/`；产品**不写工作区以外** | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §4.1 |
| **工作区根**（`--root`） | 指定工作区的**全局**旗标，必须写在子命令**前面**；不给时缺省 = 当前目录 | [`INSTALL-AND-FIRST-RUN.md`](INSTALL-AND-FIRST-RUN.md) §7 |
| **一趟 / 运行**（run，`sid`） | 从 `start` / `run-agent` 起到结束的这一段；会话事件流落 `sessions/<sid>.jsonl` | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §5 |
| **收工**（closing） | 判"这一趟能不能交"的那道门；结论是 `0` 可交付 / `1` 被拦 / `2` 没查成 | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §6.1 |
| **`final`** | 这一趟最后交回给派活方的那份交代；**与收工是两半**，收工门不看 `final` 写得好不好 | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §5.2 |

## 二、角色与协作

| 词 | 一句话 | 权威落点 |
|---|---|---|
| **角色**（role） | 十一个：执行面 A–H、V、L ＋ 主控 M；权限、动作、写集都按角色声明 | [`ROLE-SPECS.md`](ROLE-SPECS.md) |
| **主控 M**（conductor） | 唯一"派活的人"：能召唤任意可召唤角色，能看树、能收工 | [`ROLE-M.md`](ROLE-M.md) |
| **名册**（roster） | 一趟里谁在、谁是谁的父与子；寻址按**名册名 / 绝对编号**，不按角色代号 | [`CHAIN-ALL-ROLES.md`](CHAIN-ALL-ROLES.md) |
| **绝对编号**（task id） | `tasks` 表里的 `t-NNNNNN`；寻址与追责都用它 | [`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) |
| **召唤**（summon） | 派一趟活；走 `conductor.summon`，受边表约束（不是想叫谁就叫谁） | [`CHAIN-ALL-ROLES.md`](CHAIN-ALL-ROLES.md) |
| **边 / 可召唤**（edge / summonable） | 谁允许叫谁；"可召唤"指 M 能直接把它派起来 | [`ROLE-SPECS.md`](ROLE-SPECS.md) §R0 |
| **动作**（action） | 一个角色能做的动作条目；动作表由声明面 `specs/<role>.py` 派生 | [`ROLE-SPECS.md`](ROLE-SPECS.md) |
| **写集**（write set） | 一个角色允许写哪张表；它是**并发轴的读数，不是权限闸** | [`ROLE-SPECS.md`](ROLE-SPECS.md)、[`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) |
| **板项**（board item） | 挂在板上的一条待办；撤销走 `conductor.void_items`（撤了就撤了，不是"删记录"） | [`ROLE-M.md`](ROLE-M.md) |
| **交接**（handoff） | **两个同名的东西**：① 交接手稿（**有正文**，"我要你接着做什么"，`work/handoffs.jsonl`）；② 交差账（**没有正文**，"我不再有活"的静默信号，`out/clock/handoffs.json`） | [`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) §12 |

## 三、文献与证据

| 词 | 一句话 | 权威落点 |
|---|---|---|
| **阶段 / 候选槽**（stage / slot） | 文献入库**之前**的候选流水：`lit.stage_add` 落候选行，槽位是候选的临时号 | [`ROLE-A.md`](ROLE-A.md) |
| **收编**（admit） | 候选 → `literature` 行的判收那一步；没有可读正文会被整批受控拒（不是"没检索到"） | [`ROLE-A.md`](ROLE-A.md) |
| **断言 / 命题**（statement） | 一条可判真假的结论；由 B 的秘书登记，不是谁都能落 | [`PART-EVIDENCE-AND-SIGNS.md`](PART-EVIDENCE-AND-SIGNS.md) |
| **关系**（relation） | 两条断言 / 概念之间的一条边（支撑、推翻、推广…）；引用闸只认它的 `kind` / `quote` | [`PART-EVIDENCE-AND-SIGNS.md`](PART-EVIDENCE-AND-SIGNS.md) |
| **发签 / 签**（sign） | V 对命题或手稿的签发动作；没有签不许升档 | [`PART-EVIDENCE-AND-SIGNS.md`](PART-EVIDENCE-AND-SIGNS.md) |
| **等级**（grade） | 结论的**强度**（最低到 `proof` 那一档） | [`TWO-AXES-GRADE-AND-KIND.md`](TWO-AXES-GRADE-AND-KIND.md) |
| **档位**（kind / 证据档位） | 证据的**类型**（引文、数值、形式化…）。**等级与档位是两根轴，不是一件事** | [`TWO-AXES-GRADE-AND-KIND.md`](TWO-AXES-GRADE-AND-KIND.md) |
| **引文回验**（quote verify） | 断言与来源逐字比对；`quote_verified` 是**三态**（查过一致 / 查过不一致 / 没查成），不是布尔 | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §7.2 |
| **形式化**（formal） | 交给检查器（Lean）验的那一路，归角色 L；默认关，关着时 `formal.*` 不装配 | [`LEAN-MODES.md`](LEAN-MODES.md)、[`FORMAL-TOOLCHAIN.md`](FORMAL-TOOLCHAIN.md) |

## 四、三态 / 四态 / 门

| 词 | 一句话 | 权威落点 |
|---|---|---|
| **三态**（0 / 1 / 2） | 命令与脚本的退出码语义：`0` 查过且一致、`1` 查过且不一致、`2` **没查成**。**`2` 不是 `0`** | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §6.5 |
| **四态**（`pass` / `fail` / `unknown` / `na`） | 收工门每一格的取值；**`na` 不是 pass，`unknown` 也不是 pass** | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §6.2 |
| **收工门 / 八格** | 一次运行能不能收工的八项判据（组成以 `closing.DEFAULT_CHECKS` 现读为准） | [`SYSTEM-INTRO.md`](SYSTEM-INTRO.md) §6.1、[`USER-TEST.md`](USER-TEST.md) |
| **门**（gate） | 本仓有三种，别混：**收工门**（产品内、判一趟运行）、**禁改区门**（FC-27，判一次改动）、**发布门**（本机，判一份交付） | [`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md)、[`../DEVELOPMENT.md`](../DEVELOPMENT.md) |
| **禁改区 / FC-27** | 错误**不可逆**的路径清单；改它要人写或人逐行走查 ＋ 2 名 reviewer 批准 | [`../AGENTS.md`](../AGENTS.md)、[`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md) |
| **契约**（contract） | ① 表的落盘形态：每张表一份 `{"schema_version", "rows"}` 的 JSON；② `--json` 输出另有机器读写契约 | [`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) §4、[`CLI-CONTRACT.md`](CLI-CONTRACT.md) |
| **台账**（ledger） | `data/*.json` 里的表（`schema.TABLES`）；与追加写的事件流 `events.jsonl` 是两件东西 | [`PART-LEDGER-AND-STORE.md`](PART-LEDGER-AND-STORE.md) |
| **产物台账**（`ARTIFACTS.jsonl`） | 工作区里每一份产物的登记流水：谁写、写什么、怎么对账 | [`PART-ARTIFACTS-LEDGER.md`](PART-ARTIFACTS-LEDGER.md) |

## 五、提示词与版本

| 词 | 一句话 | 权威落点 |
|---|---|---|
| **教法** | 角色"该怎么干"的那一半正文（policy / 手册 / 工具摘要）；它进提示词，所以改它要抬版本 | [`PROMPT-HISTORY.md`](PROMPT-HISTORY.md)、[`TEACHING-VERSION-BUMP.md`](TEACHING-VERSION-BUMP.md) |
| **提示词版本**（`PROMPT_VERSION`） | 教法与工具面的版本号（`pNNN`）；改教法 / 工具面就抬一格 | [`TEACHING-VERSION-BUMP.md`](TEACHING-VERSION-BUMP.md) |
| **十一格摘要** | 十一个角色各自的提示词指纹，冻结在判据表里；抬版本就把十一格逐格重算 | [`TEACHING-VERSION-BUMP.md`](TEACHING-VERSION-BUMP.md) |
| **golden（冻结快照）** | `tests/golden/` 下的可比对象：重冻一次 = 换一把尺子，属禁改区动作 | `tests/golden/README.md`（本机，不随仓库交付） |

## 六、同义词 / 旧名（读老文档时会对上）

| 会看到的写法 | 今天叫什么 | 备注 |
|---|---|---|
| 证据等级 | **证据档位**（kind） | 等级（grade）与档位（kind）是两根轴，这个混用已在 [`TWO-AXES-GRADE-AND-KIND.md`](TWO-AXES-GRADE-AND-KIND.md) 里逐处校准 |
| `manuscript_rows`（旧键） | `handoff_rows` | 交接**账本**的行数，不是论文份数；旧键仍有同值读数 |
| "预设"（presets） | 已退役 | 正文归声明面 `specs/`，见 [`PRESET-RETIREMENT.md`](PRESET-RETIREMENT.md) |
| "演示 / demo" | 已退役（受控退场） | `agentflow demo` 仍能解析但只给退出码 `2` 与指路 |
| "七格" / "六格" | 今天组成的格数（现读 `closing.DEFAULT_CHECKS`） | 那两种是旧版收工门的**历史读数**，别照它数今天的格 |

> 新增术语的口径：**它必须在这一页有一行，且"权威落点"指向一份已经在
> [`INDEX.md`](INDEX.md) 里登记过的文档**（否则读者点进去看到的是一份没人负责的文件）。
