# INSTALL-AND-FIRST-RUN.md —— 从 clone 到第一次 `--dry-run`

> **最短路径：五个步骤（§1–§5），全部零模型调用、零花费。** 每条都真跑过，输出是当次原文
> （过长处按 `…` 截断，右边切到哪由终端列宽定）；工作区用一个空目录，**不要用仓库目录**。
> 装法与快速开始的英文权威版在仓库根 [`../../README.md`](../../README.md) §Installation /
> §Quick start；逐条详解（含体检、常见错误）在 [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md) §0–§7
> （`doctor` 在 §3.5）。**本文不重抄它们**，只给"第一次该怎么办"的顺序与真实读数。

## 0. 前提

| 项 | 要求 / 缺了会怎样 |
|---|---|
| Python **3.11+** ＋ 两个运行期依赖 `filelock` / `PyYAML` | `pip install -e` 会拉；缺 ⇒ 装不上 / 起不来 |
| 操作系统 | Windows 10/11 是参考平台；其它平台没人替你验过 |
| 模型 key | **只在真跑时要**：本文五步都不需要；没有它真跑以退出码 `2` 明说 |
| Node.js / Lean | 只在改前端 / 做形式化时要；前端构建产物已入库，不影响本文任何一步 |

## 1. 装（在仓库根 `D:\Incubator` 跑，只跑一次）

```powershell
python -m pip install -e agentflow
```

先不落盘试跑一遍（证明这条命令在这个仓里成立、不碰你的环境）：

```text
$ python -m pip install -e agentflow --dry-run --no-deps
Obtaining file:///D:/Incubator/agentflow
  Preparing editable metadata (pyproject.toml): finished with status 'done'
Would install agentflow-1.0.0                                        EXIT=0
```

判"装的是这份源码"的唯一读数是 `Editable project location:`（`python -m pip show agentflow`）；
**不想装**也行：`$env:PYTHONPATH = "D:\Incubator\agentflow\src"` 从源码树跑，只少了可执行名。

```text
Editable project location: D:\Incubator\agentflow
Requires: filelock, PyYAML
```

## 2. 验：三个入口是同一条命令

```text
$ python -m agentflow --version
agentflow 1.0.0                                                      EXIT=0
```

`agentflow` / `python -m agentflow` / `python -m agentflow.cli` 逐字等价：`pyproject.toml` 的
`[project.scripts]` 与 `__main__.py` 都转到同一个 `main`。

## 3. 建一个工作区（工作区 = 任何空目录）

```text
$ python -m agentflow --root D:\Incubator\agentflow\temp\docsgaps\ws2 init
[init] 已初始化：D:\Incubator\agentflow\temp\docsgaps\ws2\data        EXIT=0
```

只建 `data/`：每张表一份空 JSON（`{"schema_version": …, "rows": []}`）＋ `events.jsonl`；
**工作区之外一个字节都不写**。

## 4. 第一次 `--dry-run`：它打算做什么

```text
$ python -m agentflow --root <你的空工作区> start --task "研究一个有限群的问题" --dry-run
缓存：这一档不新鲜（这些目标的现渲染摘要与读数不一致），建议先点『试算』看要预热什么

┌── 试运行：将要发生的一切（一个字节都不写、一次模型都不调） ────────────────────────────────────┐
│ 模式                project                                                                    │
│ 模型                deepseek-flash（base=https://api.deepseek.com/v1）                         │
│ 预算                0.5 美元（该模式的缺省值，不落盘）                                         │
│ Lean                开关现在关（来源 缺省）；这一趟 --lean off；自检没跑（试运行不启动检查器） │
│ 会召唤              不召唤任何角色（项目工作区那一步是端到端主题跑）；要角色循环请 --mode res… │
│ 会写这些            工作区 …\ws2\projects\project1（会新建…）                                   │
│ 任务：研究一个有限群的问题                                                                     │
│ 冷启动：会新建文件夹、初始化工作区、登记书；热启动：复用已有工作区（已登记的书按内容 hash      │
│ 跳过），产物写进新的 out/run-N                                                                 │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
  工作区：            …\ws2\projects\project1
  · 不花钱（试运行一次模型都不调）                                   EXIT=0
```

**它真的没写**：跑完 `Test-Path <ws>\projects` 仍是 `False`。第一行 `缓存：这一档不新鲜` 是
提示词前缀缓存的一条 warning（`cachectl`），**只加读数、不拦跑**。

## 5. 读记录（空工作区的读数，抄下来当基线）

```text
$ python -m agentflow --root <ws> status
工作区 …\ws2
│ search_requests    │    0 │ done=0 pending=0                             │
│ literature         │    0 │ processed=0 downloaded=0                     │
…（16 张在用表各一行 ＋ 最后一行 events 追加日志）                       EXIT=0

$ python -m agentflow --root <ws> stats gates
计数：pass=0  fail=1  unknown=4  na=3
机器口径 machine_pass=False；M 判据 m_says_done=False，can_close=None   EXIT=0

$ python -m agentflow --root <ws> closing --no-index
  · 收工结论：unknown（exit 2） · m_says_done=False · retire=干净         EXIT=2
```

八格里 `substance` 是 `fail`（这一趟什么都没产出），其余 `unknown` / `na` —— **`unknown` 与 `na`
都不是 `pass`**，这就是这套系统的三态纪律。空工作区收工**故意**以 `2` 结束：没有可判对象 ⇒
读数"没查成"，不是"通过"（`--no-index` 让它只读、不写索引）。

## 6. 两个会咬人的缺省

1. **`--root` 是全局旗标，必须写在子命令前面**：`status --root <ws>` ⇒
   `agentflow: error: unrecognized arguments: --root`、退出码 `2`；`--root <ws> status` 才对。
2. **不给 `--root` 时缺省 = 当前目录**（读写工作区的子命令同一条缺省）；`init` 建在哪，`status` 就读哪。

## 7. 下一步

| 我要… | 去哪 |
|---|---|
| **真跑一趟**（要 key、要花钱） | [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md) §2 ＋ §5 |
| 体检这台机器（`doctor`） / 起网页 | [`USER-GUIDE-CLI.md`](USER-GUIDE-CLI.md) §3.5 · [`USER-GUIDE-WEB.md`](USER-GUIDE-WEB.md) |
| 看限制 / 查词 / 验收 | [`LIMITS-AND-NON-GOALS.md`](LIMITS-AND-NON-GOALS.md) · [`GLOSSARY.md`](GLOSSARY.md) · [`USER-TEST.md`](USER-TEST.md) |

> 复跑记录：**2026-11-22 21:24–21:33 +0800**，仓库根 `D:\Incubator`，Windows / Python 3.11.4 / `agentflow 1.0.0`（editable），工作区 `agentflow/temp/docsgaps/ws2`；原始输出另存同目录。
