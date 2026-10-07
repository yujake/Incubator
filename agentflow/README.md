# agentflow —— 面向数学研究的多智能体协同框架（正式版）

> 原型（A/B 双智能体文献流水线）在 `D:\Incubator\test\test1`（包名 `abflow`），**保持不动**；
> 本目录是**正式版**。两份的关系、以及为什么要另起一份，见 `DEVELOPMENT.md` §0 与
> `..\draft\13-数学研究多智能体协同框架-正式设计草案.md`。

**本文件只讲"怎么跑"与"现在到底有没有跑通"。** 判据性文档的入口是 [`DEVELOPMENT.md`](DEVELOPMENT.md)
（开发规范）与 [`docs/ROLE-SPECS.md`](docs/ROLE-SPECS.md)（角色规格）；设计**理由**在
`DESIGN*.md`（不构成判据，与代码冲突时以代码为准）。

> 📍 **要先看清"系统现在长什么样"**：读
> [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)
> —— 那一份把七层结构（数据面 / 声明面 / 工具面 / 角色面 / 循环面 / 接线面 / 质量面）逐项写清，
> **每一条都标注对应程序相对工作区根（`D:\Incubator`）的路径**，并给出每个数字的复跑命令。
> 它同样是导读、不构成判据。
>
> **本文件的路径约定**：目录树与行文里的 `src/agentflow/...`、`tools/...` 相对**本目录
> （`agentflow/`）**；换成相对工作区根（`D:\Incubator`）就加一层前缀，写作
> `agentflow/src/agentflow/...`、`agentflow/tools/...`。

---

## 0. 先跑通（五分钟；前两步不花钱、不联网）

> 这一节是给**第一次用它的人（比如要用它做点东西的数学家）**的。每条命令都在 2026-09-30
> 实测过，读数写在旁边；跑不通时的对照表在最后。

**装**（二选一）：

```powershell
# ① 不装：直接进源码目录跑（最快，本机实测可用）
cd D:\Incubator\agentflow\src
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python -m agentflow.cli --help          # 该看到 24 个子命令

# ② 装成一个命令（打包元数据齐：`[project.scripts] agentflow = "agentflow.cli:main"`、
#    包布局 `src/`、运行期依赖只有 filelock）
python -m pip install -e "D:\Incubator\agentflow[pdf]"    # 需要 PDF 解析时带 [pdf]
agentflow --help                        # 与上面是同一个入口
```

第 ② 条实测（2026-09-30）：在一个 `--system-site-packages` 的干净 venv 里
`pip install --no-deps --no-build-isolation -e D:\Incubator\agentflow` 装成功，
产出 `Scripts\agentflow.exe`、`agentflow-1.0.0.dist-info\entry_points.txt` 里逐字是
`agentflow = agentflow.cli:main`、可编辑落点 `.pth` 指向 `agentflow\src`；
**换一个目录**（不在源码树下）跑 `agentflow --help` 与 `agentflow demo` 都是**退出码 0**。
`--no-deps` 的含义是：这里唯一那个运行期依赖 `filelock` 由外层解释器提供
（本机已有）—— 你在一台干净机器上装，去掉 `--no-deps` 让它自己拉即可。

**只想先看看它能不能跑，就先走第 ① 条**：它不需要装任何东西，实测可用。

**三步验证**（离线、零花费）：

| 命令 | 该看到什么 |
|---|---|
| `python -m agentflow.cli demo`（**旧路径**：保留可达 —— 唯一不需要模型 key 的端到端路径；主路径是 `run-agent`） | 一串 `✓` 与最后一行「演示成功」，**退出码 0** |
| `python -m agentflow.cli tools --role H` | H 的工具面清单（只读角色看不到写工具 —— 那是设计） |
| `python -m agentflow.cli status` | 各表计数表（空工作区全 0 是正常的） |

**跑完之后一定要自查**（这一步是把"跑完了"与"跑对了"分开的唯一手段）：

```powershell
python -m agentflow.cli verify   # 不给 --root ⇒ 用代码里的缺省根（`cli.DEFAULT_ROOT`）；该看到「错误 0 / 警告 0」
```

`verify` 是**离线的不变量审计**（表之间对不上就报，例如"有一笔花销挂在不存在的任务上"）。
它绿了**不等于**结论对，但它红了就意味着这份工作区的数据自相矛盾 —— 那一刻产物里的
任何读数都不该被引用。本项目把"刚跑成功的那一跑、自查却说数据不一致"当成必须修的 bug
（2026-09-30 实测撞到过一次：`project run --extract` 的花销挂在 `first-extract` 这个
不存在的任务号上 ⇒ `verify` 报两条 error 加一条 warning；修法见 `draft/28` §200）。

**一步真活：拿你柜子里的 PDF 跑一条研究流水线**（要模型 key；key 从环境变量
`AGENTFLOW_MODEL_API_KEY` 或机器级设置文件 `agentflow/settings.json` 的 `model.api_key` 来，
命令行不许传 —— 命令行参数会进 shell 历史与进程列表）：

```powershell
$env:AGENTFLOW_MODEL_API_KEY = "..."       # DeepSeek 的 key（或写进 agentflow/settings.json）
python -m agentflow.cli project run --name first --books D:\books `
    --topic "分支布朗运动的极值过程" --budget-usd 0.05 --max-calls 6
```

实测（2026-09-30，2 本书 87 页 + 0.05 美元上限）：冷启动登记 2/2 本，6 次模型调用花
**0.0032 美元**，退出码 0；产物在**项目根**（默认 `projects.DEFAULT_PROJECTS_DIR` —— 由本包位置推出的工作区根下的 `projects/`，可用 `--projects-dir`、`$env:AGENTFLOW_PROJECTS_DIR` 或设置文件的 `workspace.projects_dir` 覆盖）下的 `<工作区>/out/run-1/` 的**六件**：
`run-manifest.json`（这一跑的全部读数）/ `model-transcript.jsonl`（逐次调用）/
`evidence.json`（来源 + 全文 sha256 + 逐字回验）/ `claims.json`（拆出来的断言）/
`cost.json`（花销账）/ `report.md`（**人读的那一份**）。同一次实测里 9 条断言
**9/9 逐字通过全文级回验**。

**想让库里有概念与关系**（否则 `concepts` 是空的 —— 离线基线抽出来的概念名大多是垃圾，
所以 B 在没有模型时宁可空着）：加上 `--extract`，它是"模型读书"那一步：

```powershell
python -m agentflow.cli project run --name first --books D:\books --extract --extract-rounds 2 `
    --topic "分支布朗运动的极值过程" --budget-usd 0.05 --max-calls 6
```

实测（2026-09-30，同一批 2 本书，`--extract --extract-rounds 2`）：**0 个失败轮次**、
新建 **24 个概念 / 16 条关系**，每条关系都回原文逐字找过 —— **16/16 引文过验**；
另外有 **8 条在抽取阶段就被剔除**（模型给的关系里，引文在原文里逐字找不到的那一些，
它们没有进库）。

读数框把这两档**分开印**，因为它们是两个阶段、不是一个数的两种说法：

```text
│ 新增关系           │ 16 │   ← 进库了
│ 引文过验           │ 16 │
│ 抽取阶段剔除       │  8 │   ← 模型的引文在原文里根本找不到（没进库）
│ 引文未过（已剔除） │  0 │   ← 活到落库那一步、带页码窗口的回验没过
```

所以「模型一共提了多少条关系」= `新增关系 + 抽取阶段剔除` = 16 + 8 = 24。
抽取那一步花 **0.017294 美元 / 2 次调用**（它**不吃** `--budget-usd`：那个上限只管主题作答
那一跑，抽取的上界是轮数 = 本数）。这一跑结束时的 `verify` 是**错误 0 / 警告 0**。

**多智能体真跑**（主控 M 自己决定派谁；`role` 是**位置参数**，不是 `--role`）：

```powershell
python -m agentflow.cli run-agent M --task "读台账并报告各表计数" --max-steps 3
python -m agentflow.cli run-agent M --task "…" --drive H.review --drive G.revise   # 被召唤的角色走 LLM 循环
python -m agentflow.cli run-agent M --task "…" --semantic-review                   # 给 H 接上语义判据
python -m agentflow.cli run-agent M --task "…" --subagents                         # 所有角色动作都交给模型
```

**卡住时先看这张表**（每一条都实测过）：

| 症状 | 是什么意思 | 怎么办 |
|---|---|---|
| `[run-agent] 没查成：没有接模型…`，退出码 **2** | 没有 key（不是"跑过了没问题"） | 设 `AGENTFLOW_MODEL_API_KEY`，或写进 `agentflow/settings.json` 的 `model.api_key`（那份文件被 git 忽略，见 `.gitignore` 第 13 节） |
| `project run` 退出码 2，`report.md` 里写 `检索状态：not_configured` | 同上：检索一次都没发起 | 同上；不带 `--topic` 时只登记书、本来就不调模型 |
| 汇总框里 `Lean 开启=否；proof 级证据 0 条` | 没装 Lean（或没加 `--lean`） | 装 Lean 后加 `--lean`；否则请把这一格读成"**没形式化核过**"，不是"核过没问题" |
| 模型连着几步不回 JSON ⇒ 结论写 `bad_json_limit` | 模型没按循环协议回一行 JSON（框架会纠正两次，第三次停） | 重跑；或把 `--max-steps` 调大，让纠正消息有机会生效。**它是如实停，不是崩** |
| 结论写 `no_progress_limit`（界面上是「原地打转」） | 同一个形状 + 同一份参数 + 同样的读数连着 6 次：那几步一步也没产生新事实（第 3 次时框架已在结果里点名过） | 这是读数不是崩溃：看那一步的【没有新事实】提醒，换参数/换脚本/换子目标再跑；真机样本见 `draft/37` §136（T2 第 4 趟里 M 连调 9 次 `conductor.ledger`、6 次写同一份验收表） |
| 满屏 `得到 HTTP 429` | 上游限流（AMS 的直链最常见） | 等一会儿重跑；或改用手里的本地书架 |
| `concepts` 一条没有，`last_mine_error=no_llm_extractor` | 没给 B 抽取器时它**拒绝抽**（离线基线产出的概念名大多是垃圾，所以宁可空着） | 给 key，或在 `project run` 上加 `--extract`；这是设计，不是坏 |
| `python -m agentflow.cli run-a` 很慢（实测 62s / 15 条） | 默认 `topical` 模式会联网、会下载、会重试 | 只想验证链路就用 `--provider fixture`（**完全离线**，实测 0.4s：3 候选 → 登记 2、判重 1） |

**不建议**在没有网、没有 key、没有 Lean 的机器上跑"真活"那一条：它会如实告诉你缺什么
（退出码 2 + 一行说明），但不会替你产出结论。

---

## 1. 这是什么

**一个用户控制的主控（M），按需唤起 A–H 与 V 九个角色；角色之间也可以互相唤起。**

```
                        ┌──────────── 用户 ────────────┐
                        │                              │
                        ▼                              │
                   M（主控 · conductor）               │
        召唤 / 策略 / 并发调度 / 取消 / 台账(tasks)      │
                        │                              │
   ┌────────┬───────────┼───────────┬─────────┬────────┤
   ▼        ▼           ▼           ▼         ▼        ▼
   A ──────▶ B ───────▶ C           D ◀──────▶ E       F
 文献检索  文献整理   只读关系分析  研究        实验/    难题攻坚
   │        │           │           │         形式化    │
   └────────┴───────────┴───────────┴──────────┴────────┘
                        │
                        ▼
                   G（撰写）──▶ H（审校）──▶ G（修订）
```

| 角色 | 一句话职责 | 副作用面 | 它能召唤谁 |
|---|---|---|---|
| **M** | 召唤、策略判定、并发调度、取消、写运行台账 | 只写 `tasks` | A–H + V 全部 |
| **A** | 文献检索 + 下载 + 登记 | `effect` = `read`/`write_local` × **`external=egress`**（3 件：`search.literature`/`providers`/`download`）；**不是唯一有外呼的角色**，见下 | B |
| **B** | 抽取概念与关系（含**引文逐字回验**） | `write_local` × **`external=egress`**（`ocr.run` 首次会下 easyocr 模型） | C |
| **C** | **只读**关系分析（最热/路径/冷门/缺口/矛盾/结构重复） | `read`（工具面 **21** 个只读工具，**零写工具**、`external` 恒 `none`） | **无**（连"请求"都不直接发） |
| **D** | 研究循环：把 C 的报告变成研究问题并回答 | `write_local`；`external` **恒为 `none`**（零 `egress`、零 `exec`） | A B C E F |
| **E** | 数值实验 + 形式化验证（**计算类拿不到 `proof`**） | `write_local` × **`external=exec`**（起 Lean/Coq/Isabelle 与实验脚本子进程） | B D |
| **F** | 多轮难题攻坚（预算不足即拒绝立项） | `write_local` × **`external=exec`**（`verify.run_experiment` / `verify.check_formal`；`attack.step` 经 `_deploy_e` 起 E 的脚本子进程，见 P-13 §4.3 第 10 条） | A B C D E V |
| **G** | 撰写：断言 / 依赖 / 稿件 / 修订 | `write_local` × **`external=exec`**（与 F 同源） | A D E F |
| **H** | **审校**：G1–G15 门、发现落库、状态更新 | `write_local`（**只有一个被钉死的写面**）；两根轴上 `external` **恒为 `none`**（零 `egress`、零 `exec`） | A E G |
| **V** | **证明级验证**：把 F 交回来的证明按写成后的样子整体重读，给三态结论（`成立`/`有毛病`/`看不出来`）并签五元位第 3 位 | `read`（工具面 **14** 个只读工具，**零写工具**、`external` 恒 `none`；唯一的产物是 `verifications/<命题号>.jsonl` 这个**文件**，不是表） | **只能召唤 F** |

> ⭐ **"副作用面"这一列在 B3 收官后是两根轴**（`effect` × `external`，`docs/PROPOSALS.md` **P-13**）。
> **"A 是唯一联网角色"这句话今天不成立** —— 已按实测更正（观测 2026-09-26T04:44）：
> `external != "none"` 的工具有 **6 件**（`ocr.run` / `search.download` / `search.literature` /
> `search.providers` / `verify.check_formal` / `verify.run_experiment`），它们分布在
> **`{'A','B','E','F','G'}`** 这五个角色上（C / D / H / V 一个都没有）。
> 复跑：`$env:PYTHONPATH='src'; python -m agentflow.cli tools`，再看某角色 `--role <X>`。
> ⚠️ 工具条数有**两个口径**，不许互换：`build_registry(store=None)` ⇒ **68**；
> 含 store 的完整装配（= `cli tools`）⇒ **81**。见 `docs/ROLE-SPECS.md` §0.3
> （观测 2026-10-06（角色 V 落地）；V 落地前是 62 / 78）。

**三层结构**（`DEVELOPMENT.md` §2.1）：

- **领域对象层**：`research_questions` / `attack_plans` / `experiments` / `documents` / `dependencies` / `review_findings`
- **知识层**：`literature` / `concepts` / `relations`
- **运行记录层**：`tasks`（编排台账） / `usage_ledger` / `eval_results` —— **与领域对象分层**，
  因为"跑过什么"和"知道了什么"是两件事（`status` 与 `outcome` 正交：
  `status ∈ pending/running/done/cancelled/failed` 回答"跑完没有"，
  `outcome ∈ ok/no_result/not_applicable/refused/failed/cancelled` 回答"产出了什么"。
  **`refused` 是一次成功执行** —— 框架正确地说了"不"）。

**贯穿全项目的三条纪律**（细节见 `DEVELOPMENT.md` §3）：

1. **三态纪律**：`True` / `False` / `None` + 受控 `reason`。**"没做" ≠ "做了没结果"**。
2. **单一来源**：同一判据只有一处实现，别处必须**转发**（不许多写一份并行的）。
3. **fail-closed**：未接线 / 依赖缺失 / 读不到 ⇒ **显式失败**，不许静默返回空。

---

## 2. 30 秒跑通（完全离线，不访问网络）

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
cd src
python -m agentflow.cli demo
```

`demo`（**旧路径**：保留可达 —— 它是唯一不需要模型 key 的端到端路径；主路径是 `run-agent`）
自建素材与独立工作区，把整条链路跑一遍并打印逐项判定；**退出码 0 = 全部通过**。

### 跑测试

```powershell
cd D:\Incubator\agentflow
python -m pytest -q                  # 离线套件（配置在 pyproject.toml：testpaths + addopts "-m 'not network'"）
python -m pytest -q -m network       # 联网套件（默认 deselect）
```

**为什么分两套**：日常套件必须离线、确定性、可重复 —— 否则一次上游限流就会把红灯搞成背景噪音，
久而久之没人再看。但有几个真实缺陷（Crossref `select` 字段名错导致全 400、`precise` 模式恒为 0）
**只有真实 HTTP 往返才能发现**，所以它们留在套件里、只是默认不跑。
**"进套件 + 默认 deselect"是两个诉求的唯一交集。**
联网套件里 HTTP 429 判 `skip`（环境状况），**400 一律判失败**（那是真 bug）。

### 每个模块都有独立自检

```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.agent_h              # 每个 agent_*.py 都能这样跑
python -m agentflow.capabilities         # （能力表在导入期自检；import 不进来就是自检失败）
```

`python scripts/release_check.py` 的第 2 项会跑**每一个**模块的自检，并对"**没有自检块**"的模块
报 `unknown`（不是 `pass` —— 把"没检查"读成"检查通过"是本项目反复踩过的坑）。

---

## 2.1 交互台：不带参数运行就是一份菜单（2026-09-28 新增）

```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.cli          # 不带任何参数 ⇒ 进交互台
```

它把常用的四件事列成一份菜单（项目 / 端到端主题 / 数据状态 / 角色工具面），
逐项问清参数再调对应的子命令 —— 于是"能用"这件事不必依赖记住十几个开关。
菜单里每一步都走**同一条实现**（它只是把回答翻成子命令的 argv），
所以手敲命令与走菜单的结果逐字一致。

呈现规则（都在 `src/agentflow/tty.py` 里，有 14 条判据守着）：

```text
· 管道里自动不带颜色（stdout 不是 tty / 设了 NO_COLOR / TERM=dumb ⇒ 关）；
  想强制关用 `--no-color`，想全 ASCII（老终端、粘进邮件）用 `--plain`。
· 框与表按"显示列数"对齐：中文在等宽终端里占两列，用 len() 补空格会差一截 ——
  判据是"同一个框里每一行的显示宽度必须相等"。
· 编码：先问当前编码能不能表示 ─│✓，不能就退成 +-| 与 [ok]；GBK 控制台下不会崩。
```

---

## 2.2 用户端网页（SPA）：六个页面读什么、怎么构建

`agentflow web` 起的是一个小服务（默认只听 `127.0.0.1:8788`）。页面的**皮**是从 DSH 抄的
（令牌整份照搬，来源与 MIT 见 `docs/USER-END-DSH-STYLE.md`），**面**是六个客户端路由，
数据一律从盘上派生（页面里不缓存）：

| 路由 | 页面 | 读哪条端点 |
|---|---|---|
| `/` | 全局待回答面板 + 会话概览 | `GET /api/state` |
| `/run/:sid` | 一趟详情（时间线 / 花销两个来源 / 索引对账 / 交付说明） | `GET /api/run/{sid}` + `GET /api/run-index` |
| `/evidence` | 证据链七栏 | `GET /api/evidence` |
| `/artifacts` | 产物（台账 / 交接 / 验收行 / 体例 / 六件产物 / 任务） | `GET /api/artifacts` |
| `/acceptance` | 收工门内容级验收（5 判据 + 5 辅助） | `GET /api/acceptance` |
| `/machine` | 本机（检查器 / Lean / Mathlib / 钥匙配没配） | `GET /api/machine` |

逐页逐栏的字段、空态与三态口径见 `docs/USER-END-DSH-STYLE.md` §3.1；判据在
`tests/test_webui_pages.py`（每页一条：真读数出现 + 空态 + 三态）。

`GET /` 与 `GET /index.html` 直接吐 SPA 外壳（裁定 P1 的第一块迁移：注入本进程的 CSRF 令牌、
`Cache-Control: no-store`）—— 浏览器地址栏因此进得了 SPA；`GET /run/{sid}` 这一批仍是服务端渲染的
旧壳（W5 再迁），它由 `tests/test_webui.py` 的 17 条守着。前端工程自己的说明见 `ui/README-DEV.md`。

**本机读数（2026-10-07，复算命令见括号）**：

- 路由表 `ROUTES` **13 行**、其中 JSON 端点 **9 条**（`python -B -c "import sys;sys.path.insert(0,'src');from agentflow.webui import routes;print(len(routes.ROUTES), len(routes.api_paths()))"`），
  其中 `/api/state` 按裁定 2b 归 B 线的 `readers.ROUTES`、`/api/run-index` 是 A 线自有的那一条；
- 前端源码 `ui/src/` **19 个文件、3656 行**（含两份生成物），其中六页 + 六组件 + `main.tsx` / `api.ts` / `sse.ts` / `live.tsx` / 两份 css；
- `ui/src/types.ts` 是生成物：**16,003 字节 / 39 个接口 + 2 个类型别名**（`python -B -m agentflow.web.emit_types`）；
- 事件词表 6 个 kind（`state` / `question` / `answered` / `checkpoint` / `stop` / `heartbeat`），前端 `sse.ts` 逐个注册并带 `?since=` 续传与"退避三次 ⇒ 降级轮询"；
- 入库的构建产物 3 个文件（`web/static/index.html` + `assets/` 下的一支 `.js` 与一支 `.css`，
  本次读数共 **81,491 字节** —— 六页面与 `live.tsx` 全进包之后 JS 那一支就有 60.3 KB；
  文件名带内容哈希 ⇒ **每次重建都会变**，所以这里刻意不写死哈希名；
  复算：`Get-ChildItem -Recurse -File src/agentflow/web/static | Measure-Object Length -Sum`）。

**要改前端**（`ui/`）：装依赖 → 改 `ui/src/` → **重建产物并一起提交**（裁定 B1：`src/agentflow/web/static/` 入库）
→ 跑门。三条命令：

```powershell
pnpm -C ui install          # 只跑一次（依赖：preact / vite / @preact/preset-vite / typescript）
pnpm -C ui build            # 产物落 src/agentflow/web/static/（index.html + assets/*.js|css，带内容哈希）
node ui/node_modules/typescript/bin/tsc --noEmit   # 类型门（= pnpm -C ui typecheck）
```

两条纪律：`ui/src/types.ts` 与 `ui/src/theme/generated/theme.css` 是**生成物，手改必红**
（生成器是 `python -m agentflow.web.emit_types` / `python -m agentflow.web.emit_theme`；
新鲜度判据在 `tests/test_webui_contracts.py`）；`ui/src/api.ts` 的路径字面量必须与
`webui/routes.py` 的 `ROUTES` 逐字相等（契约判据 A）。细节与踩过的坑见 `ui/README-DEV.md`。

> 沙箱提示：在没有"用管道 stdio 起子进程"权限的环境里，`pnpm build` 会以 `spawn EPERM`
> 失败（esbuild 的服务进程拉不起来），而那**不是** `pass` —— 发布门里这一步记 `unknown`（`draft/80` 题 7）。
> 产物本身已在盘上并入库，`tests/test_webui_static.py` 会真跑它的自洽与新鲜度判据。

---

## 3. 真实网络模式（会联网、会下载）
```powershell
cd D:\Incubator\agentflow\src
python -m agentflow.cli init
python -m agentflow.cli submit --topic "abelian group" --mode topical
python -m agentflow.cli run-a --provider openalex      # 检索 + 下载 PDF
python -m agentflow.cli run-b                          # 抽取概念与关系
python -m agentflow.cli status
python -m agentflow.cli verify --deep                  # 重新打开文献复核引文
python -m agentflow.cli tools --role H                 # 看某个角色的工具面（只读角色看不到写工具）
```

**已实测可用**：OpenAlex 检索、真实 PDF 下载（含 sha256）、Crossref / DOAJ / Europe PMC 客户端。

本机网络说明：`github.com` 系域名被 hosts 劫持到 `127.0.0.1`；镜像可用 `https://ghproxy.net/`、
`https://gh-proxy.com/`。`config.yaml` 的 `download.mirrors` 用于直连失败时的前缀回退。

### 3.1 项目式用法（本地书架）：已退场

> 这一段原先教的是「手里已经有整柜 PDF 时不必先联网检索」的旧流水线
> （`project list` / `project plan --books …` / `project run --books … --extract`），落点写在
> 仓库外的旧根 `D:\Incubator\projects\project<N>`。淘汰理由（`draft/44:89` 的 L-04b 与
> `draft/48-09:720-721`）：那是**一次单机真跑被写成了能力陈述** —— `draft/43-B:221` 逐字
> 「把一次历史真跑写成能力陈述」，而今天**没有任何判据或真机读数复现它**
> （新根 0 张项目卡；`--books` 的 15 次运行全落在旧根）。
> **四块留痕**（原先想做什么 / 怎么做 / 有没有被证明 work 过 / 为什么淘汰 + 教训）见
> `draft/65a` §A-2。今天的主路径是 `run-agent`（`python -m agentflow.cli run-agent <role> --task …`），
> 本地素材走 `search.shelf`。

#### 3.1.1 四层证据各自的强度（**读产物前先看这个**）

这套东西的产物同时印出四类东西，而它们的**可复核程度差得很远**。
2026-09-28 在 7 本书（2418 页）上实测的读数（`draft/28` §126.2）：

| 层 | 有没有回验门 | 实测读数 | 读的时候该怎么用 |
|---|---|---|---|
| 断言（`claims.json`） | 有：每条结论必须带一段逐字引文 | 主题那一跑 5/5 `verified`，级别 `fulltext`，逐条带页码 | 可以按"有原文依据"用 |
| 关系（`relations.json`） | 有：`quote` + `page_range`，回验不过标出来 | 110 条里 **98 条**引文逐字可达；另 12 条引文为真但页码恒偏 5（模型用了书里印的页码），已修提示词 | 按 `quote_verified` 那一列读；`False` 的先看页码 |
| 概念（`concepts.json`） | **没有**：只记"来自哪篇文献" + 模型写的定义 | 174 条里只有 **19%** 的定义能在被引书里找到成句原文（37% 部分重合、44% 找不到） | 把它读成"模型的概念名与措辞"，**不是**"都能在书里指出来" |
| 来源（`evidence.json`） | 有：全文 sha256 与库里的文件逐字节一致 | 7/7 条来源 `fulltext.status=ok` | 可以顺着 `fulltext.path` 自己复核 |

```text
最要紧的一句：**"概念定义没有逐字回验门"不等于"定义是错的"** ——
实测抽查（Yoneda 引理 / path integral / Hadamard product）显示，模型常常是
"书里确实有这个术语，但定义用了自己的措辞"，公式型定义还会因符号不同而字符级比对落空。
所以这一层的正确读法是"模型的措辞"，而不是"抄错了"。
```

---

## 4. 目录结构

```
agentflow/
├── DEVELOPMENT.md            ★ 项目开发规范（六条硬纪律 / DoD / 测试规范 / 禁止模式 / 发布检查 / FC 覆盖矩阵）
├── AGENTS.md                 ★ 禁 AI 区（FC-27）硬约束 —— 只覆盖这一节，与 .noai-paths 逐条一致
├── NOAI-REVIEW-REGISTER.md   ★ FC-27 人工复核登记表（哪一轮改了哪些禁改区文件、谁走查过）
├── README.md                 本文件
├── DESIGN.md / DESIGN-TOOLS.md / DESIGN-INTERACTIONS.md / DESIGN-ROLES.md / DESIGN-CONDUCTOR.md
│                             设计理由（不构成判据；现状导读见 ../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md）
├── config.yaml               运行时可调项（注释里注明各字段落到哪个模块）
├── settings.example.json     机器级设置的示例（本机工具链落点 / Mathlib 根 / 模型 key / projects 落点）：**复制成同目录的 `settings.json` 再改值**（那份被 git 忽略；改哪台机器就换那一份）。口径见 `src/agentflow/settings.py` 与 `docs/FORMAL-TOOLCHAIN.md` §6
├── .noai-paths               禁改区清单（**40** 条 glob / **37** 条唯一路径 / 7 类；**台账条目数与欠签不写定值**（每签一个字就变 —— 量法与当次值见 §6.2 那两格，别再往这一行抄数）；前两个数由 `tests/test_release_all.py::test_readme_file_tree_numbers_match_the_repo` 守着）
├── pyproject.toml            包元数据 + pytest 配置（**唯一**一处；不要再加 tests/pytest.ini）
├── docs/
│   ├── INDEX.md              docs/ 的索引与"按角色怎么读"
│   ├── READING-MAP.md        ★ 七层与各自的文件 + "想改什么 ⇒ 读哪几个文件"（3 跳以内）+ §3"这些文件为什么这么大"+ §4 判据在哪（**第一次读这个仓先看它**；判据 `tests/test_reading_map.py`）
│   ├── ROLE-SPECS.md         ★ 九个角色 + 主控（M）的详细规格（每节 10 条同构结构）
│   ├── NOAI-GOVERNANCE.md    FC-27 门的机制与人工批准流程
│   ├── PROPOSALS.md          已裁决的缺口与提案（P / G / N 三类）
│   ├── FORMAL-TOOLCHAIN.md   形式化后端（Lean）的工具链口径
│   ├── SCHEMA-DRAFT-management.md · SCHEMA-MIGRATION-PROPOSAL-claims.md
│   │   · SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md
│   │                         表结构与迁移提案（不是判据）
│   ├── ROLE-SPECS-DRAFT-N-O-Q.md · ROLE-SPECS-DRAFT-V.md · TOOLBOX-DRAFT-roles.md
│   │                         角色与工具栏的草案（不是判据；V 那份的原任务已落地，判据在 ROLE-SPECS.md §V）
│   ├── PROPOSAL-side-effect-axes.md
│   │                         副作用第二根轴（external：egress / exec）的提案
│   └── NOAI-CHANGE-LIST-management.md · NOAI-SUSPENSION-2026-09-25.md · NOAI-SUSPENSION-2026-09-28.md
│       · USER-END-DSH-STYLE.md（用户端设计依据：抄 DSH 的皮）
│       · USER-TEST.md（人实测清单：零成本自检 → 真机一趟 → 验收两道门）
│                             禁改区的变更清单与两次暂停记录 · 用户端设计依据 · 人实测清单
├── scripts/
│   ├── lint_rules.py         linter（**规则区间与条数以 `python scripts/lint_rules.py` 的摘要行为准**；当次 R001–R012、R004/R006 已退休；**有退出码**）
│   ├── noai_gate.py          FC-27 门（0=clean / 1=requires_human / 2=unknown）
│   ├── release_check.py      ★ 发布前八项检查（test-suite / selftests / tool-census / verify / linter / noai / contract / imports；本文件自身在禁改区里）
│   └── usage_ledger_audit.py usage_ledger 的存量重复账审计与清洗
├── src/agentflow/
│   ├── schema.py             ★ 数据模型 + 行级校验 + 全部跨模块词表（单一来源；SCHEMA_VERSION=1、17 张表）
│   ├── store.py              ★ 锁 / 原子写 / 事务 / 事件日志 / ID 分配 / 重建
│   ├── interactions.py       ★ 跨角色交互的冻结契约（I1–I7；纯函数、不接 store）+ 契约版本 CONTRACT_VERSION
│   ├── capabilities.py       角色能力表 + 写集 + 允许的召唤边（**A–H 调用矩阵的权威定义**；**导入期自检**）
│   ├── verify.py             ★ 全局不变量校验（审计的判据本身）
│   ├── policy.py             策略判定（四类上限、越权边、只读角色写面）
│   ├── conductor.py          M 的实现：召唤 / 台账 / 合并（Conductor + LocalBackend / SubagentBackend）
│   ├── host.py               接线层：把 A–H 接到 LocalBackend（build_role_registry / wired_* 五件）
│   ├── scheduler.py          波次调度器（写集相交 ⇒ 串行）
│   ├── cancellation.py       协作式取消（受控理由见该文件的 `CANCEL_CODES`；**份数按它当次读**、不写定值：观测 2026-09-27（`G3` 复测）⇒ 5 个取值，其中 `cancelled` 是"未分类、不要用"那一档 ⇒ 4 个真实停止来源；无自动重试）
│   ├── contextbudget.py      上下文预算（压缩 / 剪枝 / spill）
│   ├── tokenmeter.py         token 记账（**重试按次计费**）+ 开工前守卫
│   ├── artifacts.py          产物归属登记（谁在哪个路径产出了什么 + sha256 + 退出码）
│   ├── canonical.py          规范 JSON 字节串的**唯一实现**（稿件内容哈希与回执哈希共用的那一份口径）
│   ├── sessions.py           按项目存放的会话记录（`<项目根>/sessions/<会话号>.jsonl`；学 harness 的按工作区存放）
│   ├── fulltextstore.py      抽取正文的内容寻址库（整本书正文只存一份，产物里只留引用）
│   ├── claims.py / claimanatomy.py
│   │                         原子断言拆分 / 每条断言的字段规格与生命周期（claims 的唯一判据来源）
│   ├── signatures.py         稿件内容的规范哈希与签名链（DOC-SIGNATURES.jsonl）
│   ├── gates.py              ★ H 的 G1–G15 门引擎（四态结论：pass / fail / unknown / not_applicable）
│   ├── faculty_checks.py     十项官能里可机械判的那一半（引用落地 / 猜想卫生 / 体例）
│   ├── judge.py / judges.py  语义判定的唯一缝协议 / 判据注册表（6 条判据 × 三态词表 + 负控）
│   ├── deliver.py            交付前的判据闸门（机械半 ⇒ 结论、报告、可派回去的工作项）
│   ├── paperbuild.py         论文包的渲染 / 编译 / 锚核对（build = render → compile → anchor_check 三步）
│   ├── renderanchor.py       渲染锚与编译回执的本体（RENDER-ANCHOR.json / COMPILE-RECEIPT.json / BUILD-HISTORY.jsonl）
│   ├── promptkit.py          LLM 接入（一）：提示词装配（有序段 + 变量 + complete + 作用域遮蔽）
│   ├── agent_prompts.py      LLM 接入（二）：A–H 与主控的前置提示词（手写判断 + 现算的工具面/伙伴边；PROMPT_VERSION=p43，**以 `src/agentflow/agent_prompts.py` 顶部的常量与 `tests/test_agent_prompts.py` 的冻结表为准**）
│   ├── llmseam.py            LLM 接入（三）：统一的模型缝（一次调用一条审计记录 + 三态词表 + 预算守卫）
│   ├── agent_loop.py         LLM 接入（四）：模型驱动的循环（tool / summon / message / note / ask_user / final 六种形状）
│   ├── modelgw.py / modelclient.py / modelcost.py / llm.py
│   │                         模型网关（**key 的唯一入口**：环境变量 → 机器级设置文件 → 缺省）/ 抽取层客户端 / 花销入账 / 离线抽取器
│   ├── settings.py           机器级设置（**本机路径与模型 key 的一处定义**：`toolchain.*` / `model.*` / `workspace.projects_dir`；优先级 环境变量 > 设置文件 > 默认/自动探测）；配套示例 `settings.example.json`，真正那份（`settings.json`）被 git 忽略
│   ├── providers.py / fetch.py / extract.py / quoteverify.py / evidence.py / locallib.py
│   │                         检索 provider / 下载 / 文本抽取 / 引文回验 / 证据层 / 本地书架灌入
│   ├── formalgw.py           Lean 形式化后端（缺工具链 ⇒ inconclusive，不是 fail）
│   ├── dedup.py / textutil.py / canonical.py
│   │                         判重 / 文本规范化与相似度 / 规范字节串
│   ├── projects.py / pipeline.py / runflow.py / autonomy.py
│   │                         项目工作区 / A→B→C→D 流水线 / 端到端一条命令 / 自主轮次与周期汇报
│   ├── demo.py / userio.py / console.py / tty.py
│   │                         离线演示 / 用户频道（提问与"没答"三态）/ 输出编码 / 终端呈现原语
│   ├── cli.py / __main__.py  命令行入口（24 个子命令，`python -m agentflow.cli --help`）
│   ├── agent_a..h/ · agent_v/  九个角色（每个都能 `python -m agentflow.agent_x` 自检；V 是证明级验证，只读）
│   └── tools/                工具层（**14** 个 `*_tools.py`：table / fs / search / ocr / graph /
│                             trace / research / verify / attack / doc / review / conjecture /
│                             conductor / manuscript，外加 `base.py` 与装配点 `__init__.py`；
│                             组装结果与逐角色条数以 `python -m agentflow.cli tools` 为准）
├── tests/                    pytest（**267** 个 `test_*.py`，观测 2026-10-07；当次用 `(Get-ChildItem tests -Filter 'test_*.py').Count` 复跑 —— 这一格老得最快，**别把它当定值**；离线 + 联网两套；见 §2）
├── tools/                    开发期工具与探针（`release_all.py` 一键发布、`coverage_zero_test.py` 覆盖门、
│                             `run_each_test_file.py` 逐文件门、`verify_role_specs.py` 规格门、
│                             `vocab_census.py` = R011 判据本体，其余是 `probe_*` 探针）
└── data/ · library/ · demo/  运行时数据 / 下载的文献 / 演示素材
```

> ⚠️ 上面这份树**只列会在意的那些**；完整的顶层模块清单（以及"新增一个模块必须在哪登记"）
> 由 `tests/test_release_all.py::test_agentflow_top_level_modules_match_the_registry` 守着 ——
> 那份登记表是判据，这份树是导读（README 自己的第 7 节第 1 条就写着"与代码冲突时以代码为准"）。
> **逐项带路径的现状描述**见 [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)。

---

## 5. 数据文件速查

| 文件 | 内容 |
|---|---|
| `data/search_requests.json` | 检索请求清单（含 `claimed_by` / `lease_until` 租约字段） |
| `data/literature.json` | 文献表（含下载状态、sha256、`quote_verified`） |
| `data/concepts.json` / `relations.json` | 知识层（`related_concepts` 由关系**派生**，不是输入） |
| `data/research_questions.json` | D 的研究问题（状态机 + 证据链 + `relation_chain`） |
| `data/attack_plans.json` | F 的攻坚计划（子目标 + 预算 + 历史） |
| `data/experiments.json` | E 的实验记录（`method` 是计算类时 `evidence_kind` **不得**为 `proof`，schema 强制） |
| `data/documents.json` / `dependencies.json` | G 的稿件与外部依赖（`external_unavailable` 是一等状态） |
| `data/conjectures.json` | D 的猜想台账（`status` / `form` / 反例与证明实验的外键；依据 `draft/30` §T1） |
| `data/review_findings.json` | H 的审校发现 |
| `data/tasks.json` / `usage_ledger.json` / `eval_results.json` | **运行记录层**（编排台账 / token 记账 / 评测口径） |
| `data/counters.json` | 4 位 ID 分配器 |
| `data/events.jsonl` | **追加式事件日志，唯一事实源**；快照可从它重建 |
| `data/.locks/*.lock` | 跨进程排他锁（`store.LOCK_ORDER` 规定加锁顺序） |

**不在 `data/` 里、但同样属于工作区的七样**（都不是表，因此不进 `schema.TABLES`）：

| 文件 / 目录 | 内容 |
|---|---|
| `DOC-SIGNATURES.jsonl` | 稿件签名台账（append-only JSONL + 链式哈希；证据快照在 `doc-signatures/`）。实现：`src/agentflow/signatures.py` |
| `ARTIFACTS.jsonl` | **产物归属登记**：谁在哪个路径产出了什么（`sha256` + 字节 + 生产者 + 召唤号 + 退出码）；`changed/missing/unreadable` 四态由 `artifacts verify` 现算。实现：`src/agentflow/artifacts.py` |
| `sessions/<会话号>.jsonl` | **按项目存放的会话记录**（一次终态 = 一条叙事行；换项目就是另一段历史，互不污染）。实现：`src/agentflow/sessions.py` |
| `notes/<角色>.md` | 角色笔记（LLM 循环里 `note` 形状的落点；`inbox`/`notes` 一起构成角色的跨步记忆）。实现：`src/agentflow/agent_loop.py` |
| `runs/<角色>-<时间戳>-<序号>.json` | **子循环的长产出落盘**：上游拿到的是路径而不是被截断的摘要（`RUNS_DIR_NAME = "runs"`）。实现：`src/agentflow/agent_loop.py` |
| `.fulltext/` | 抽取正文的**内容寻址库**：整本书的正文只存一份，产物里只留引用。实现：`src/agentflow/fulltextstore.py` |
| `<项目>/out/paper/`（项目工作区里） | 论文包本体：`main.tex` / `main.pdf` / `ACCEPTANCE.md` / `CLAIMS-LEDGER.md` / `tables/*.tex` / `RENDER-ANCHOR.json` / `COMPILE-RECEIPT.json` / `BUILD-HISTORY.jsonl`。三维锚的实现在 `src/agentflow/renderanchor.py` |

> 快照被改坏时：`python -m agentflow.cli rebuild`（会先自动备份）。

---

## 6. 发布门（一键：`tools/release_all.py`）

用户点名的"一键发布检查"是 **全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter**。
`scripts/release_check.py` 覆盖其中五项（**没有验收测试**），所以正式入口是编排层：

> ⚠️ **"`release_check` 不含验收测试"是刻意的分工，不是缺项**（`P-11`，(b) 方案）：
> 验收测试由 `release_all` 的**独立 `acceptance` 步**承担，在 `release_check` 里再跑一遍
> 会让同一件事**有两个落点**（FC-03 的反面），而 `release_check` 本身在禁改区（加一项要人审）。
> **八项逐项**（`scripts/release_check.py` 的 `main` 里的 `runners` 元组，按此顺序）：
> `tests` / `selftests` / `tools` / `verify` / `lint` / `noai` / `contract` / `imports`。
> **验收测试不在其中，也不该在其中** —— 复跑：`python tools/release_all.py --only acceptance`。

> ⚠️ **写文件的纪律在这一区里已经收敛成一条（`D8` 落地，`R6-AN-5` 于 2026-09-27 复核）**：
> 三处 `--json` 出口 —— `tools/release_all.py`、`scripts/release_check.py`、
> `scripts/lint_rules.py` —— **都是** `with open(..., "w", encoding="utf-8", newline="")`，
> 没有一处用 `Path.write_text()`。`newline=""` 关掉平台的换行转换：在 Windows 上
> `Path.write_text()` 会把 LF 刷成 CRLF，而产物的 sha256 必须与"盘上那一版"对得上
> （见 `draft/22` §12.15.2 记的那次事故）。
>
> 实测（复跑：跑一次 `--json` 出口再数字节）：两处产物都是 **CR=0**
> （`R6-AN-5` 于 2026-09-27 复核并更正：这一段原写"`release_check` 的产物 CRLF=10"，
> 那是 `c-12` 修完之前的读数）。这里刻意只钉 **CR=0**、不写死行数：
> `lint_rules` 的产物行数随 findings 条数变化，写死就是下一个过期数字。
> `scripts/lint_rules.py` 的 `R012`（`rule_R012_write_text_newline`）在真树上报
> **0 条 warning**，唯一豁免是 `tools/make_demo_dataset.py`（它写的是工作区载荷，
> 逐条登记在 `R012_NEWLINE_EXEMPTIONS`，登记过期会被反向报出来）。
> 所以"整个发布区都禁 `write_text`"这句话今天**已经成立** ——
> 它由 `R012` 这条机器判据守着，不再只是一段散文（`G-42`）。

```powershell
python tools\release_all.py                   # 全跑（约 10~15 分钟）
python tools\release_all.py --json r.json
python tools\release_all.py --only role-specs  # 调试：只跑一项
```

| 步骤 | 是什么 |
|---|---|
| `release-check` | `scripts/release_check.py` 的八项：`tests` / `selftests` / `tools` / `verify` / `lint` / `noai` / `contract` / `imports` |
| `acceptance` | 验收测试 P1–P9（`test/test2/run_acceptance.py`，`AGENTFLOW_TARGET=formal`） |
| `repro` | 论文独立复现（5 个实验 + 7 条负控） |
| `role-specs` | `tools/verify_role_specs.py`：角色规格结构完整性（9 节 × 8 必备子节） |
| `coverage` | `tools/coverage_zero_test.py`：零测试公开函数的**风险分档**清单 |
| `per-file` | 逐文件单跑测试（把顺序依赖/跨文件状态泄漏变成可判定的门） |

**总判定三态**：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`；
退出码 0/1/2。⚠️ **两条刻意的取舍**：`--skip` 掉的步骤记成 `unknown`（**不是 `pass`**，
否则 `--skip acceptance` 就成了"发布门全绿"的捷径）；超时/起不来记成 `unknown`
（Windows 上被强杀的进程退出码常是 1，与"检查发现问题"的 1 无法区分）。

### 6.1 现在的真实判定：**`FAIL`**（不是"基本全绿"）

⚠️ **这一节是"如实"，不是"唱衰"**（`G-28`）。实测（观测 **2026-09-26T04:54:45 → 04:59:39**，
无并发干扰的那一次）：

```powershell
python tools/release_all.py --since 4293989 --only release-check --json D:\Incubator\temp\b6-release-check.json
```

```
[run  ] release-check  全量测试 + 全部自检 + verify + 工具普查 + linter + 禁 AI 区 + 契约 + 导入（预计 ~300s）
[fail  ] release-check  exit=1 293.0s
         发布检查总判定：FAIL    pass=6 fail=2 unknown=0
[skip ] acceptance / repro / role-specs / coverage / per-file
一键发布检查总判定：FAIL    pass=0 fail=1 unknown=5
```

**两条红里有一条是制度要求，不是代码坏**：

| 红项 | 性质 | 逐字判据 |
|---|---|---|
| `noai` | **制度要求（需人签字）** | `release-check` 那一项的红是"**禁改区命中待 2 名 reviewer 签字**" —— `consistency_exit=0`（两处清单逐条一致）而 `gate_exit=1`（`命中禁改区 ⇒ 需人编写或人逐行走查 + 2 名 reviewer 批准`）。**这一格在人来签字之前永远是红的**，与代码质量无关 |
| `tests` | **真红（可复现，但不是本批引入）** | **这是一条历史读数（原始观测时刻没记 ⇒ 只能当历史；权威读数是本格下面两组带时刻的区间）**：同一次运行 `2 failed, 1948 passed, 1 skipped, 8 deselected, 1 xfailed in 277.76s`；失败两条是 `tests/test_agent_f_step_outcomes.py::test_the_collection_is_actually_consumed_by_the_write_path` 与 `tests/test_core_audit_efgh.py::test_agent_e_resolve_accepts_absolute_inside_and_refuses_outside`。**两条单跑都绿**（`3 passed` / `1 passed`）⇒ 形态是**全量下的顺序依赖/并发态**（`G-27` 的族）。⚠️ **它随并发变动**：同一小时内两次**无并发**全量分别是 **`1925 passed`（观测 04:43:55→04:48:40）** 与 **`1956 passed, 1 skipped`（观测 05:10:23→05:15:43）**，两次退出码都是 0 —— 区间来自别的执行体在持续加测试。所以 `tests` 这一格的读法是"**区间 + 观测时刻 + 逐文件门（`per-file`）**"，不是"读一次就下结论" |

（**`G-28` 的处置就是这一段本身**：三处文档原先把它写成"基本全绿"，
现在写"总判定 `FAIL`，且 `noai` 那一格的红是禁改区命中待 2 名 reviewer 签字（制度要求，不是代码坏）"。）

### 单跑某一项

```powershell
python scripts/release_check.py                     # 八项发布检查
python scripts/release_check.py --changed <文件…>    # 同时判禁改区命中
python scripts/lint_rules.py                        # 规则区间与条数以该命令的摘要行为准（当次 R001–R012；R004/R006 已退休；`--strict` 加严）
python tools/verify_role_specs.py                   # 角色规格结构完整性（0/1/2）
python tools/coverage_zero_test.py                  # 零测试公开函数风险分档（0/1/2）
```

⚠️ **`unknown` 绝不是 `pass`。** 这是本项目的核心教训（`draft/17-…md:675-676` 记录成熟项目的同类问题：
*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*）。
本脚本自身位于 FC-27 禁改区，**发布前必须由人逐行走查 + 2 名 reviewer 批准** —— 这一条写在
[`NOAI-REVIEW-REGISTER.md`](NOAI-REVIEW-REGISTER.md) 里，**不要因为门是绿的而跳过**。
（`tools/release_all.py` 同样在禁改区：它决定"跳过的步骤算不算通过"。）

### 6.2 禁改区的**三个数**必须并列写（`X-5` 的口径）

`draft/25` 的 `D-4.2` **原写**"19 glob / 14 台账条目 / 7 类"——**这三个数今天都过期了**，
而它们过期的方式恰好说明为什么要**并列**写：它们量的**不是同一件事**。

| 数 | 量的是什么 | 实测（观测 **2026-09-27 15:1x（`FIX11` 题 3 落地后复测）**；这个时间戳是这一格的一部分 —— 数字会变，量法不会） | 复跑方式 |
|---|---|---:|---|
| **清单 glob 数** | `.noai-paths` 里的**条目行**数（同一个文件可以登记两次） | 由命令当次产出：**40**（**唯一路径 37**） | `(Select-String -Path .noai-paths -Pattern '^\S+\s+\[category:').Count` |
| **唯一路径数** | 上述 glob 去重 | 由命令当次产出：**37** | 同上再加 `ForEach-Object { ($_.Line -split '\s+')[0] } \| Select-Object -Unique` |
| **台账条目数** | `.noai-approvals.json` 里**有 hash 记录的路径**数（= 需要签字的行数） | **不写定值**（每签一个字就变）：当次由右列命令产出 | `python -c "import json;print(len(json.load(open('.noai-approvals.json', encoding='utf-8'))['entries']))"` |
| **禁改区类别数** | `.noai-paths` 的 `[category: …]` 分组数 | **7** | `Select-String -Path .noai-paths -Pattern '^\[category:'` |
| （派生）**欠签** | 台账条目 × 2 名 reviewer | **不写定值**（每签一个字就变）：由右列命令当次产出 `entries × 2 − Σ len(reviewers)`；**0 签的条目也随签字而变**（当次以 `python scripts/noai_gate.py --check-approvals` 的输出为准，这里不点名具体文件） | `python -c "import json;d=json.load(open('.noai-approvals.json',encoding='utf-8'));print(len(d['entries'])*2-sum(len(e['reviewers']) for e in d['entries']))"` |

**差集 = 「清单唯一路径数」−「台账条目数」**（两个数都见上表；**本行不写定值** —— 差集随人跑 `--baseline` 与新增登记而变，当次以 `python scripts/noai_gate.py --check-approvals` 报出的 `unregistered` 条目为准）逐条说清（`X-5` 要求"差集是哪几条"）：

| 不在台账里的路径 | 为什么它没有台账条目 |
|---|---|
| `src/agentflow/release_check.py` | **盘上不存在**（`Test-Path` ⇒ `False`）。它是**刻意先登记路径**的（"一旦有人在这里新建它，会自动落入清单而不是绕过门"）⇒ 没有文件就没有 hash 可言。判据面仍然有效：`--paths src/agentflow/release_check.py` ⇒ `unregistered`（`requires_human`, exit 1）。**当次它是唯一的一条**（差集是派生量：以 `python scripts/noai_gate.py --check-approvals` 的输出为准）：`.noai-approvals.json`、`scripts/noai_gate.py`、`scripts/lint_rules.py` 的台账条目都已由人跑 `--baseline` 补登记（早前版本把它们算作差集，那已过期） |

⚠️ **`ledger_self_approval` 这一档仍然成立**（只是它不再表现为"差集"）：`.noai-approvals.json` **在**清单里、也**在**判定输出里，但它**永远**是 `unapproved`，与 hash 是否一致、reviewers 有几个无关 —— 台账不能批准自己。

**另：清单两处本体的台账记录今天已经是"hash 一致 + 各 2 名 reviewer"**（观测 2026-09-27（`G3` 复测）：
`.noai-paths` 与 `AGENTS.md` 的台账 `sha256` 与盘上逐字节相同，各 2 名 reviewer）。
仍然 `unapproved` 的条目**随签字而变**：唯一**永远** 0 reviewer 的是**台账自身**（`.noai-approvals.json`
的台账 `sha256` 与盘上永远对不上 —— 它自己也在被写 —— 且它**不能自签**，见上一段）。
其余哪几条 0 签、哪几条 `stale`，一律以 `python scripts/noai_gate.py --check-approvals` 当次输出为准；
**本段不点名、不写定值**（旧版这里点名过 `pyproject.toml` 是 0 reviewer，它已由人补签 2/2 ⇒ 那个说法已过期）。
⚠️ **"哪些路径 stale / 谁是零 reviewer"随人签字而变 ⇒ 本段不写定值**，复跑口径：
读 `.noai-approvals.json` 的 `entries`，逐条把 `sha256` 与盘上 `hashlib.sha256(文件字节)` 比对
（**不经过门的任何写路径**）。
**门报得对，不是坏**；收敛它要重跑 `--baseline`，而那会改禁改区台账 ⇒ **必须由人做**（判据五）。

**其余两条曾被猜为"差集"的其实是台账条目**（这条更正很重要，`X-5` 原文的候选清单猜错了）：
`.noai-paths` 与 `AGENTS.md` **各自都有自己的台账条目**（`--baseline` 已登记），
所以"清单两处本体没有批准记录"这个猜测**不成立**。
**「清单条目行数 − 唯一路径数」= 同一文件登记两次的条数**（**派生量，不写定值**：
两个数都见上表）：`src/agentflow/dedup.py`、`src/agentflow/providers.py`
各登记两次；`src/agentflow/schema.py` 登记两次（`schema-migration` + `eval-criteria`）。

**判据**：本表的三个数与 `python scripts/noai_gate.py --check-consistency`（退出码 0）、
`.noai-paths`、`.noai-approvals.json` 的实测**逐条一致**。⚠️ **`--check-approvals --paths` 的入参是
「命中路径数」而不是「清单 glob 数」**——传清单的条目数进去，它报的是**台账条目数**，
**而那不是"清单有那么多条"**。**这两个数都不写定值**（每签一个字就变）。
把两个数读成一个数，就是 `X-5` 要防的那类口径混用。

---

## 7. 已知限制（**务必先读**）

1. **`README.md` 不是判据。** 与代码冲突时以代码为准；判据入口是 `DEVELOPMENT.md` 与 `docs/ROLE-SPECS.md`。
2. **抽取质量取决于抽取器。** 离线 `RuleExtractor` 只认定义句式，**真实论文上产出的概念名大多是垃圾**；
   它是**可测试的基线**，不是可用的抽取器。
   > ⚠️ **`R-56`（2026-09-29）之后它还是"框架的回退"，而 `AgentB` 见到它会直接拒抽**：
   > 无 LLM 时不会把它的产出灌进概念图（实测症状：`ANU` / `cingled property` / `Ultimately this`
   > 这类碎片进图，而 `quote_verified=True` 让它们看起来有证据）。跳过时行上留
   > `last_mine_error="no_llm_extractor"`，`run_once()` 的返回值里有 `skipped_no_extractor` 计数。
   > **要显式选离线基线**（演示 / 单测 / 自检）请用 `llm.OfflineFixtureExtractor`
   > ——与 `RuleExtractor` 同实现，只是声明自己**不是**回退；`cli` / `pipeline` / `host` 的默认装配
   > 仍然是 `RuleExtractor`（也就是：默认**不抽**）。
   > 口径是：**允许人明确选一条已知较弱的路径，不允许框架在被问到时假装那条路径没有被选过。**
   > ⚠️ **最重要的一条认知**：离线 demo 全绿 + 千条测试全绿 + 真实数据 `verify --deep` 零错误零警告，
   > **三个绿灯叠加仍然不能证明系统有用**，只能证明它**自洽**。不变量检查的是"结构自洽"，
   > 它不检查也无法检查"这个概念名是不是一个概念"。
3. **"下载成功"不等于"拿到的是论文"**：实测碰到以 `.pdf` 结尾的 URL 返回 12.4 MB HTML。
   下载器标 `content_type_mismatch`，A 降级为 `content_mismatch` 并**保留字节作为证据**，
   B 跳过并记 `last_mine_error`。**更广义的内容校验（是不是真 PDF、是不是目标论文）仍未做。**
4. **`suspect` 状态没有复核流程**（关系被标 `suspect` 后只是留在表里等人看）。
5. **4 位 ID 上限 10000 条/类**。用满会 fail-closed 报错，不会静默升位宽。
6. **A/B/D/E/F 是轮询式**，没有消息队列；主控的调度是**波次级**的，不是抢占式。
7. **扫描版 PDF（无文本层）**：`quote_verified` 会是 `null` 而非 `true`，`verify` 把它与"校验失败"
   区分开。这类文献需要 OCR 才能真正校验。
8. **`D:\Incubator\agentflow` 自己不是 git 仓库根**（`.git` 在**上一级** `D:\Incubator`）⇒
   `noai_gate.py --git` **不是** `unknown(2)`：实测 `--git` 与 `--git --since 4293989`
   都返回 **1（requires_human）**并逐条列出命中路径（`D-12` 更正；旧版这里写"不是 git 仓库
   ⇒ 恒为 unknown(2)"，两处都不成立）。漂移检测仍以 `.noai-approvals.json` 的 hash 台账为准
   （见 `NOAI-REVIEW-REGISTER.md`）；**不给 `--since` 时改动集为空会判 unknown(2)** ——
   那一条是真的，理由见 `AGENTS.md` 末节。
9. **本项目大量代码由 AI 编写，尚未经人逐行走查。** 禁改区台账里的**每一条**尤其如此
   （**份数不写定值**：口径是 `.noai-approvals.json` 的 `entries` 长度 vs `.noai-paths` 的唯一路径数 ——
   **两个口径不许互换**；两个数都由 §6.2 那两条命令当次产出）——
   当前值以本文 §6.2 与 `DEVELOPMENT.md` §1.5 的 `LIVE-READINGS` 为准；
   `NOAI-REVIEW-REGISTER.md` §0 是**历史档案**（它自己 §0/§7 逐字声明"当前值以那两处为准"），
   不当当前数字的真源（2026-09-28 集中审查 `R6-F4`：全仓 16 个引用里只有这一处用错）。
10. **"修订落进台账"与"论文包跟上"是两件事**（2026-09-30 实测）。台账变了而
    `out/paper/` 没重渲染时，`doc.paper_state` 会报 `drifted`（判据在
    `src/agentflow/renderanchor.py::check_package`），交付定义第 1 条当场不成立。
    提示词里已把"重渲染 → 重编译 → 锚回 `consistent`"写成收工判据
    （`src/agentflow/agent_prompts.py` 的 `PAPER_PACK` 第六节），但**这不是机器强制的**。
11. **`CAPABILITIES['G']` 里没有"重渲染论文包"这个可召唤动作**（`src/agentflow/capabilities.py`；
    G 只有 `compose_claim` / `register_dependency` / `build_document` / `render` /
    `refresh_markdown` / `revise`）。重渲染目前靠 **G 的 LLM 循环自己调**
    `doc.paper_render` / `doc.paper_compile`（`src/agentflow/tools/doc_tools.py`）——
    G 那一轮不被驱动时，主控结构上无法让包跟上台账。加动作要改禁改区（需 2 名 reviewer）。
12. **语义判据是单样本**（`src/agentflow/judges.py`）：同一份产物在不同轮给过不同结论
    （`brain.blocker_specificity` 实测出现过 `vague` / `vague` / `specific`）。
    "N 样本一致"或"至少一条落地发现才判 `fail`"这类修法**尚未落地**。
13. **三处已知边界**：论文包构建只认识 `out/paper/` 这一种布局（`src/agentflow/paperbuild.py`）；
    本地灌库的 `books_dir` 未进沙箱（`src/agentflow/locallib.py::ingest_directory`，
    调用面是 `src/agentflow/tools/search_tools.py` 的 `search.ingest_local`，A 专属）；
    锚与回执是"当前状态"而不是全历史（历史另存 `BUILD-HISTORY.jsonl`，无轮转与 actor 字段）。
14. **角色之间是"协同"而不是"接力"，但两件事要部署方显式打开**（2026-09-30）：
    - **角色要能自己唤起同伴**：被召唤的角色必须走 LLM 循环
      （`src/agentflow/agent_loop.py::LlmBackend`），而默认装配 `DEFAULT_LLM_LOOPS = {}`
      （`src/agentflow/host.py`，刻意的装配期纪律）⇒ 要用 `--drive` 或在驱动脚本里传 `loops=`。
      不打开时角色跑的是确定性动作，**不会有任何同伴召唤**。
    - **够不到的人**：`C` 没有任何出边（只读角色，设计如此）。越权召唤会被自动转成给 M 的
      `请代唤` 留言（`agent_loop._request_relay`），M 的提示词要求它本轮内受理。
      2026-09-30 起 `G → A`、`H → A`、`H → E` 三条边也已由人批准加上（`draft/28` §199）——
      在此之前"要证据"这条路在 G/H 身上是断的。
    - **同角色并发多实例**：`conductor.summon_many`（M 专属）一次派一批；同一角色的每个 target
      给不同的 `instance` 才会真的并波（`src/agentflow/policy.py::_same_role_other_instance`），
      返回里的 `waves` / `concurrent_peak` 是"到底并发了没有"的读数。
15. **`--semantic-review` 曾经会把"确定性角色"全部打成 `failed`**（2026-09-30 真机抓到、已修）：
    那个开关把 H 的语义判据缝当成了所有角色共用的 `llm=`，于是 `agent_b` 拿它去造
    `LLMExtractor` 而报 `TypeError`，还被 `LocalBackend.resolve` 的 `except TypeError`
    伪装成"factory(B) 需要一个 store"。现在缝按角色给、工厂按签名调用。
16. **`run-agent --subagents`**（2026-09-30 加）：把所有已声明的角色动作都交给模型驱动 ——
    "各角色像 subagent"的部署开关。**它会替换掉确定性动作**：真机实测把 `B.run_once`
    交给 LLM 循环后，3 个 B 实例各烧 7–8 步、以 `bad_json_limit` 收场、概念/关系一条没涨。
    批量消化这类活应当用"确定性动作 + 同角色多实例并发"（`conductor.summon_many`）。
17. **逐项带路径的现状描述另有一份**：
    [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)
    —— 它是导读（不构成判据），但每条都带工作区相对路径，便于拿它逐条核对本文与代码。

---

## 8. 环境

- Python 3.11+（实测 3.11.4）；依赖见 `pyproject.toml`（`filelock`、`PyYAML`、`PyPDF2`、
  `pdfminer.six`、`PyMuPDF`、`pytest`）。OCR 需要额外环境（`easyocr` + `torch`，装在 `.venv-ocr`）。
- 控制台是 GBK 时请设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`，否则中文输出会乱码。
- PowerShell 下**不要**在 `python -c` 里写嵌套引号（会炸）—— 写脚本文件再跑。
