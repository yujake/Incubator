# 用户端人实测清单（照着敲就行；每一步都写清"该看到什么"）

> 给**人**用：跑一趟真机、看它**停在等你回答**、你答、再看它接着跑。
>
> **每个新终端先设这五个环境变量**（下面每块都重设一次，因为一块一块复制时最容易漏的就是它）：
>
> ```powershell
> $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'
> $env:PYTHONPATH='D:\Incubator\agentflow\src'
> ```
>
> ⚠️ `PYTHONPATH` 这里写的是**绝对路径**，不是 `src`。原因是实测踩到的：
> `src` 是相对路径，一旦某个块 `cd` 进工作区（`projects\…`）就再也找不到 `agentflow` 包，
> 报出来的是 `ModuleNotFoundError: No module named 'agentflow'` —— 看着像代码坏了，
> 其实只是这一行写成了相对的。**写绝对路径，`cd` 到哪儿都对。**
>
> **这份清单里哪些我跑过、哪些必须你跑**（2026-10-03 逐条记，不含糊）：
>
> | 节 | 状态 |
> |---|---|
> | §0 造工作区 / §1 零成本自检 / §2 起网页 / §4 的报错档 / §6 两道门 | **我在这台机器上逐字跑过**，下面"该看到"是实测输出 |
> | §3 / §5 / §7 的**付费整趟**（一趟 ≈ **0.30–0.49 美元**） | **你跑**。其中"停在等用户 ⇒ 你答 ⇒ 同一趟接着跑"的语义我在 12–15 号真机上验过，并且由 §1 那 32 条判据守着（不依赖模型这次问不问） |
>
> 四档退出码先记住：**0** 收工 / **1** 失败 / **2** 没查成 / **3** 停在等你回答。
> 第 3 档是本轮新加的"成功的中断"——既不是完成也不是失败。

## §0 造一个全新的跑批工作区

```powershell
cd D:\Incubator\agentflow
python -B D:\Incubator\temp\_p53_new_ws.py --name user-test-1
cd D:\Incubator\agentflow\projects\user-test-1
python -B code\make_paper.py
```

**该看到**（实测）：

```
{"workspace": "D:\\Incubator\\agentflow\\projects\\user-test-1", "source_sha256": "8c5c431b46f73dba…", "files": ["ACCEPTANCE.md", "main.pdf", "main.tex"]}
REPRO_RESULT: {"anchor": "written", "touched_main_tex": false}
```

> ⚠️ **上面这一段（以及下面 §6 那一屏）是"旧路"的真机记录**：`code/make_paper.py` /
> `code/compile_paper.py` 是**项目自带脚本**那条通道。业主 2026-10-13 裁定逐字
> 「paper_package 里那些东西都是古早废案了，我们要智能体写文章」⇒ 那条通道整条退场
> （`draft/117`）：不再有"渲染锚"，框架也不再要求任何项目脚本。**今天新面的走法**：
> 正文由 **G 自己用 `fs.write` 写进 `out/paper/main.tex`**（散文体、章节自排），
> 再调工具 **`doc.paper_compile`**（只给 G）编出 `out/paper/main.pdf`，并读**框架自己写**的
> 回执 **`out/paper/COMPILE-RECEIPT.json`** 核 `tex_sha256`（是不是盘上那份 `main.tex`
> 的摘要）与 `pages`；交付论文那一档还要两份验收表（`ACCEPTANCE.md` /
> `ACCEPTANCE-CHECKS.json`，**M** 写）。构件这个工作区的那支临时脚本
> （`D:\Incubator\temp\_p53_new_ws.py`）**仍然在按旧路往工作区里写 `code/` 那一对脚本**
> —— 它不在交付物里、这一轮没有跟着改；所以上面这一段记录**照原样保留**（它是当时真跑出来的）。

> ⚠️ 造场脚本 `D:\Incubator\temp\_p53_new_ws.py` 是我这轮的**临时工具**（在交付物
> `agentflow/` 之外、不进版本库 ⇒ 它可能被清掉）。它不在了就用**现成的工作区**
> `projects\p5-run15`（真机跑过 15 趟、有完整报告与台账）：把后面每一处的
> `projects\user-test-1` 换成 `projects\p5-run15`，其余一字不改。

## §1 真机之前：零成本自检（不花一分钱，也不依赖"模型这次问不问"）

```powershell
cd D:\Incubator\agentflow
python -B -m pytest tests\test_user_channel_stop_and_resume.py tests\test_webui.py -q -p no:cacheprovider
```

**该看到**（实测）：`32 passed`（15 + 17 条判据）。

这一节是**先量好尺子再量东西**：这两条文件守的正是本轮的三件语义 ——
①停下就真的停（不再发模型请求）；②没人回答就不许当成默许（`--resume` 也只回到"还在等"）；
③网页只是磁盘的投影（答一次只落一条 `user_answer`，跨会话也不会串号）。
真机那一趟如果"模型自己没问"，这三条仍然是绿的。

## §2 起用户端（网页）

```powershell
cd D:\Incubator\agentflow
# 这个终端会被服务占着；另开一个终端做 §3 之后的事
python -B -m agentflow.cli --root projects\user-test-1 web --port 8788
```

**该看到**（立刻出现三行）：

```
agentflow 用户端：http://127.0.0.1:8788/
工作区根：D:\Incubator\agentflow\projects\user-test-1
Ctrl-C 停止。
```

浏览器打开那个地址：**全局待回答面板**（此刻应是"没有待回答的问题"）+ 运行态（还没跑过 ⇒
"还没有跑过"）。`Ctrl-C` 停服务。

> 起后台任务、只想要一行机器可读地址时加 `--json`：

```powershell
cd D:\Incubator\agentflow
python -B -m agentflow.cli --root projects\user-test-1 web --port 0 --json
# 实测输出（立刻，不缓冲）：{"url": "http://127.0.0.1:3036/", "root": "…\\projects\\user-test-1"}
```

> 顺手验一眼"它只是磁盘的投影"：拿上面那个地址取 `/api/state`。
> 全新工作区实测是 `sessions=[] runs=[] pending_questions=[] problems=[]`、
> `last_run=null`、台账那格写着"台账还没有（合法初态）" —— 空工作区不该报红。
>
> `--token <口令>`（或环境变量 `AGENTFLOW_WEB_TOKEN`）可给网页加一道口令；> `--host 0.0.0.0` 才允许别的机器访问（默认只听本机）。

## §3 跑一趟真机 —— 它会**停在等你回答**

```powershell
cd D:\Incubator\agentflow
$task = Get-Content -Raw docs\USER-TEST-TASK.txt
python -B -m agentflow.cli --root projects\user-test-1 run-agent M --task $task `
    --budget-usd 2.0 --wall-clock-sec 3600 --sid user1 --max-steps 45
```

**该看到**（跑十几步之后，它问一个只有你能定的取舍，然后停下；下面这段取自真机 12–15 号）：

```
停在等待用户：q0001 <问题前 80 字>；下一步：
`agentflow --root …\user-test-1 inbox --sid user1` /
`agentflow --root …\user-test-1 answer q0001 "<回答>" --sid user1` / …
```

> 注意提示里 `--root` 一律写在**动词之前**：`--root` 是顶层参数，写成
> `agentflow inbox --root …` 会被 argparse 判成 `unrecognized arguments` 并退出码 2
> （看着像命令不存在）。这一条有判据：它把提示里打出来的命令**逐条真跑一遍**。

**退出码是 3**（`$LASTEXITCODE`）。**关键读数**：停下之后**不再有任何模型调用**
（`llm_call` 事件数停在原地，不烧钱）；网页面板里出现那条问题；
`agentflow inbox`（**不带 `--sid`**）也看得到它并标着会话号 `user1`。

> **为什么这一趟应当会问**：`docs\USER-TEST-TASK.txt` 是**本轮真机用的那一份任务**
> （逐字副本，11 条），它的第 8 条明确写着"关键取舍用 ask_user 问一次，然后停下等回答"。
> 所以它**不问就收工**本身是一条发现（模型行为层面），不是清单写错了 —— 把它记下来。
> 也可以换成你自己的任务，但那样"它会不会问"就不确定了。
>
> 想让它"问了就交还控制权、根本不等"：加 `--user-wait-sec 0`（默认是不限时地等，
> 也就是**真的阻塞**在你面前）。无人值守则加 `--no-ask`（见 §7）。

> **要跑"点名要求引文查询与形式化验证"的那一版**：换任务文件，并把预算与步数给足。
> **两份任务原文是同一件事的两种问法，用途不同**：
>
> | 任务文件 | 它长什么样 | 拿它量什么 |
> |---|---|---|
> | `docs\USER-TEST-TASK-QUOTE-FORMAL.txt` | 13 条，**把该怎么派活全写明了**（动作名、参数、报告九节都在里面） | **对照基线**：15 号那趟就是这种"手把手"问法跑通的 |
> | `docs\USER-TEST-TASK-NAIVE.txt` | 5 段，**一个动作名/工具名/步骤都不给** —— 只说"我要什么"、两件不放心的事、预算、"哪些没查成要说清"、"拿不准来问我" | **主控自己分析并派发**这件事：能不能不靠手把手的步骤把活派对。派不动，就是要加强的地方 |
>
> ```powershell
> cd D:\Incubator\agentflow
> # 形式化那一格：检查器在盘上但不在 PATH —— 这一行决定它能不能真验（见下）。
> # 检查器在哪的**正常落点**是机器级设置文件（agentflow/settings.json 的
> # toolchain.lean_bin，值可以是可执行文件或它所在的目录；见 docs/FORMAL-TOOLCHAIN.md §6）；
> # 下面这一行是"只想临时指一次"的写法（环境变量优先级高于设置文件）：
> $env:AGENTFLOW_LEAN_BIN = "_env\lean470\lean-4.7.0-windows\bin"
> $task = Get-Content -Raw docs\USER-TEST-TASK-NAIVE.txt      # 或换上一行的详细版
> python -B -m agentflow.cli --root projects\user-test-1 run-agent M --task $task `
>     --budget-usd 10 --wall-clock-sec 14400 --sid real16 --max-steps 150
> ```
>
> 两件先说清的事：①**形式化那一格取决于上面那一格配置** —— Lean 4.7.0 在盘上
> （`_env/lean470/lean-4.7.0-windows/bin`，commit 与框架钉住的相同；2026-10-07 起
> 环境整体从工作区 `temp/` 搬到了工作区根的 `_env/`），
> 但**没进 PATH**；把它配进设置文件（或按上面那行临时用环境变量）实测能真验
> （`check_formal` ⇒ `verified`、
> `run_experiment(method="formal")` ⇒ `evidence_kind=proof`），不加就只能如实报
> "没核到 + 理由"（两份任务里都写明了"不许写成通过"）。**Mathlib 那一档今天不行**
> （`import Mathlib` ⇒ `import_unavailable`：umbrella 的 `.olean` 不在缓存里），
> 所以引理优先挑能用核 Lean 写出来的。②按 15 号那趟的均价（0.304153 美元 / 31 次调用），
> 10 美元约合**上千次调用** ⇒ 真正卡住这一步的**不是钱，是步数与结构**（所以 `--max-steps` 要给足）。
> 天真版更容易在中途停下来问你（"这些引文要不要都逐条核"这类），所以 §4 那两条答问的路先看一遍。

## §4 你回答 —— 两条路任选（也可以都试）

**路 A：网页**。面板里点选项（单选直接点、多选可多选），或在下框里自己写一句，提交。
**该看到**：页面跳回首页、那条问题消失；`agentflow inbox --sid user1` 变空。

**路 B：终端**。

```powershell
cd D:\Incubator\agentflow
python -B -m agentflow.cli --root projects\user-test-1 inbox
# ↓ 把上面「选项」那一栏打出来的原文抄进 --select：
python -B -m agentflow.cli --root projects\user-test-1 answer q0001 --sid user1 `
    --select "<从 inbox 抄来的选项原文>"
# 或自己写一句（这条路不依赖选项长什么样）：
python -B -m agentflow.cli --root projects\user-test-1 answer q0001 --sid user1 `
    --custom "三处都保留，但第三处改成……"
# 位置参数也兼容（等价于 --custom）：agentflow answer q0001 "三处都保留" --sid user1
```

> **刻意不写死一个选项例子**：选项是模型当次写出来的。我写死一个（例如"保留（Recommended）"）
> 会让你以为必须那样答，或者照着敲一个当次不存在的选项。**抄 `inbox` 打出来的**，或直接用 `--custom`。

**该看到**：`已回答 q0001：…`，随后 `inbox` 报没有待答问题。三种"没答成"都是**明确报错**、不静默
（第一条是实测输出）：

```powershell
cd D:\Incubator\agentflow
# 答一个不存在的号 ⇒ 退出码 2：
python -B -m agentflow.cli --root projects\user-test-1 answer q9999 --sid user1 --custom "试试"
#   [answer] 没查成：没有 q9999 这个问题（当前待答：现在是空的）。若它落在别的会话里，
#   用 `agentflow inbox` 看会话号，再用 `--sid` 指名
# 再答一个已经答过的号 ⇒ 退出码 2，并告诉你"谁、什么时候答的"：
python -B -m agentflow.cli --root projects\user-test-1 answer q0001 --sid user1 --custom "再答一次"
```

## §5 接着跑 —— 两种情形，语义不同

**情形 A：那一趟还停着**（§3 的终端没关）⇒ 你一回答，**同一个进程自己接着跑**
（提问是阻塞的，等的是磁盘上那条回答事件，不产生 token 开销）。**该看到**：§3 的终端
立刻继续往下走，最后打印 `结论：…`，退出码变成 0。

**情形 B：那一趟已经退出了**（你 Ctrl-C 了）⇒ 用检查点续跑：

```powershell
cd D:\Incubator\agentflow
$task = Get-Content -Raw docs\USER-TEST-TASK.txt   # 新终端里要重新设一次
python -B -m agentflow.cli --root projects\user-test-1 run-agent M --task $task `
    --sid user1 --resume --max-steps 45 --budget-usd 2.0
```

**该看到**：它**不从头重推**（会话里那一趟的 `agent_run_start` 带 `resumed_from`），
而且读得到你刚写的那句回答。三种"没接着跑"的情形都是**明确报错**，不是静默：

| 情形 | 该看到 |
|---|---|
| 没答就 `--resume` | 退出码 **3** + "还在等 q0001"，且**一个模型请求都不发** |
| 换了任务去 `--resume` | 退出码 **2** + `checkpoint_mismatch`（拒续，不是失败） |
| 上一趟已收工 | 退出码 **2** + "已收工，续跑没有意义" |

## §6 验两道门（这才叫"能交"）

```powershell
cd D:\Incubator\agentflow\projects\user-test-1
python -B -m agentflow.cli --root . inbox      # 应为空
python -B -m agentflow.cli --root . closing --project-dir . --report out\review\REPORT.md
```

**该看到**（实测，这是真机跑过 15 趟的那个包）：

```
  · anchor：通过
  · contradictions：通过
  · load_bearing：通过
  · report_shape：通过
  · user_pending：通过
  · substance：通过
  · acceptance：通过
  · artifact_ledger：通过
收工门：八格全过 ⇒ 可交付
```

退出码 **0**。网页运行态里那一趟的 `stop_reason` 应是 `final`，花费与终端打印的一致。

> ⚠️ **这一屏也是"旧路"的真机记录**（那一格当时叫 `anchor`）。**2026-10-13 起它改名叫 `paper`**，
> 判据也从"渲染锚三维（源表 / 渲染出的源文件 / 编译回执）"换成
> **"回执里的 `tex_sha256` 与盘上那份 `out/paper/main.tex` 的摘要对得上"**
> （实现只有一处：`src/agentflow/papercompile.py::receipt_matches_tex`，`closing._check_paper` 读它）。
> 所以今天在新面下重跑，第一行会印 `· paper：…`。**而它的结论取决于那个工作区里那份
> `COMPILE-RECEIPT.json` 是不是新面写的** —— 老工作区（回执由 `code/compile_paper.py` 写）
> 很可能根本没有 `tex_sha256` 这一栏，那时这一格是 `unknown`（"没查成"，**不是通过**）。
> 本条**没有在盘上重跑**核对这一格，所以不在这里写一个新的读数。

> 两个"必须这样写"的原因（都实测过，写错就会得到一条看着像代码坏了的 warning）：
> ① `closing` 要**在项目目录里**跑：`--project-dir` 是**按当前目录**解析的，
> 在 `agentflow\` 下写 `--project-dir projects\p5-run15` 会被拼成
> `projects\p5-run15\projects\p5-run15\…` ⇒ 报 `paper_not_checked` + `report_not_written`、退出码 **2**；
> `paper_not_checked` 是**新的码**（论文那一格 2026-10-13 由 `anchor` 改名而来，
> 旧记录里写的是 `anchor_unknown` —— 旧码今天不再产生）；
> ② 所以这个块要先 `cd` 进项目目录，而这就更需要上面那条**绝对** `PYTHONPATH`。
> 这两条合起来正是"能交"这一步最容易假红的地方 —— 它报的不是包坏了，是路径写错了。
> ③ 另一头也要小心：**别把论文包目录本身当项目根传**（`--project-dir out\paper`）——
> `closing._check_paper` 会认出来（它看见那个目录下有 `main.tex`）并如实报
> `paper_not_checked`："给的目录看起来是论文包本身 ⇒ 论文那一格没查成"。
> 所以"项目根"始终是**装着 `out/paper/` 的那一层**。

## §7 无人值守一档（验证"不许把没问当成默许"）

```powershell
cd D:\Incubator\agentflow
$task = Get-Content -Raw docs\USER-TEST-TASK.txt
python -B -m agentflow.cli --root projects\user-test-1 run-agent M --task $task `
    --sid unattended1 --no-ask --max-steps 45 --budget-usd 2.0
```

**该看到**：它照跑，但一到"该问用户"的地方**不停**、也**不落问题**：它按最保守的做法继续，
并把"这件事本该问用户但没人可问"写进结论（事件里是 `ask_refused`）。
这是 DSH 的 `never` 策略：**确定性拒绝，而不是降级成悄悄替用户决定**。

> 多轮（`--rounds N`）也一样：某一轮停在等用户、而问题还挂着时，**不会**再开下一轮
> （`autonomy._stop_before_round` 的 `waiting_for_user` 那一档），退出码同样是 3。

## §8 出问题时我要的三样读数

1. §3 / §5 那个终端的**完整输出**（尤其"停在等待用户"那一行与 `$LASTEXITCODE`）；
2. `python -B -m agentflow.cli --root projects\user-test-1 inbox --json`；
3. 网页那一屏（截图，或浏览器里 `Ctrl+U` 存下 HTML）；
   外加 `Get-Content projects\user-test-1\sessions\user1.jsonl | Select-Object -Last 5`
   （看回答有没有落盘、落成什么形状）。

三样齐了，我就能判断问题出在"通道语义"、"界面"、还是"模型自己"。
