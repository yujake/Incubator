# 用户手册：从这里进

> 这份是**给用的人看的**（不是给改代码的人看的）。改代码的规范在 `DEVELOPMENT.md`，
> 角色与工具规格在 `docs/ROLE-SPECS.md`，判据在 `tests/`。
> 全程只用三条命令，其余都在网页里点。

---

## 0. 你需要什么

- Windows + Python 3.11（本机已验证的解释器就够）。
- 一个**工作区目录**：框架会把项目、台账、产物都放在它下面。推荐就用仓库的 `projects\`
  所在那一层（本机即 `D:\Incubator`），这样 `D:\Incubator\projects\<项目名>\` 就是你的项目。
- 一把模型 key（在环境变量或设置文件里；`agentflow doctor` 会告诉你现在读到的是什么）。

---

## 1. 从哪进：起网页

在 `D:\Incubator\agentflow` 下：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH='D:\Incubator\agentflow\src'
python -B -m agentflow --root D:\Incubator\projects\t1-review web --port 8792 --json
```

> ⚠️ **`agentflow` 现在没装进 site-packages**：不设 `PYTHONPATH` 就会报
> `No module named agentflow`（在哪个目录都一样）。上面这段**在任意目录**贴进去都能起来。
> 嫌每次写 `PYTHONPATH` 麻烦，二选一：
> ① 在 `D:\Incubator\agentflow` 下 `python -m pip install -e .`（装一次，之后到哪都能用）；
> ② `setx PYTHONPATH "D:\Incubator\agentflow\src"`（固化进用户环境变量，重开终端生效）。

`--json` 会打印确切地址，形如 `{"url": "http://127.0.0.1:8792/", "root": "…"}` ——
把它贴进浏览器就是用户端（本机已在跑一例）。

- `--root` 是**工作区**（不是 `agentflow` 包目录）；给项目目录本身也行，那就只看这一个项目。
- `--port` 不给就让系统挑一个空闲端口；`--open` 起来之后自动开浏览器。
- 别人（另一台机器）要访问才加 `--host 0.0.0.0`；要口令加 `--token <口令>`。

网页里你会用到这几页（左栏就是这些）：

| 页 | 看什么 |
|---|---|
| `/` 项目与一趟列表 | 有哪些项目、各跑过几趟、现在在不在跑 |
| `/run/:sid` 一趟详情 | 它每一步做了什么、调了哪个工具、结果是什么、**交付说明原文** |
| `/live` 实时 | 正在跑的那一趟的流（SSE），不用刷新 |
| `/budget` 预算 | 这一趟花了多少、上限多少、追加过几次 |
| `/evidence` `/artifacts` `/acceptance` | 证据、产物归属、验收表的逐条读数 |
| `/machine` 机器 | 这台机器上工具链（含 Lean 开关）的现算读数 |
| `/help` 帮助 | 上面这些页各自的说明 |

---

## 2. 怎么有一个"项目"

两种都可以，**推荐第一种**（你只管把材料丢进去）：

**甲、你自己建（不用管结构）**——在 `D:\Incubator\projects\` 下新建一个文件夹，
把论文或资料丢进去（`main.pdf`、几篇 PDF、笔记、数据都行，混着也行），然后起网页。
框架会把这个文件夹**收编**成项目：它原来有的东西**一个字节都不动**，只在旁边铺自己的
`data\`、`out\`，并把原有条目逐条记进 `project.json` 的 `user_files`。

**乙、让框架建**（你手上是一份现成的论文文件时）：

```powershell
python -B -m agentflow --root D:\Incubator project create --name t1-review --paper D:\path\to\paper.pdf
```

它建出 `projects\t1-review\`：`source\main.pdf`（+ 同名 `.tex`，**只读基线**）、
`out\paper\main.tex`（**可改正文**，起手是基线的逐字副本）、项目卡 `project.json`。
本机现有的一例就是它。

> 两种都**不会动你的原始文件**；"只读基线"是给判据当分母用的，改稿请改 `out\paper\main.tex`。

---

## 3. 怎么跟系统说话：一个对话框

网页首页（`/`，导航第一项**「对话」**）就是一个对话框：**你写一句、它回一段**，
来回逐条摆在同一页上（你的话、主控的话、它在问你的、你答的）。不用记哪个按钮干什么 ——
同一个输入框按当刻状态自动走对的那条路，按钮旁边也写清了这一下会做什么：

| 当刻状态 | 你说这一句会发生什么 |
|---|---|
| 还没有会话 | **起一趟**（等价命令行那条） |
| 主控**在飞** | **插话**：它下一步开头读到，当前这一步不被打断 |
| 主控**闲着**、这一段有原来的任务 | 这句话先记进它的收件箱，再**接着这一段跑**（续跑）—— 带上原来那句话，所以是同一趟对话的延续，不是新起一趟 |
| 有一条**提问在等回答** | 这一句就当**回答**提交（也可以直接点它给的选项） |

**一句话就够**，例如：

> 帮我把工作区里那篇论文从头到尾审核一遍，修改掉里面的错误和不恰当表述。

不用写步骤、不用指定谁做什么——**排工作流是主控（M）的活**：它会先扫一眼工作区认出你丢进来的
是什么，再决定派谁、按什么顺序做。越像平常说话越好；后面想补话，就在同一个框里接着说。

⚠️ 网页上的写动作（起一趟 / 续跑 / 插话 / 回答 / 改预算 / 叫停）需要起服务时带
`--allow-writes`，否则回 **403**（回执原文会说明是哪一档）。

启动之后：

- 进展：同一个对话页（来回逐条在长），或 `/live`（实时流）与那一趟的详情页；
- **叫停**：`/live` 页「停机开关与历史」那张卡里就有**「叫停这一趟」**（优雅停：在飞的活收尾、
  没做完的标成「停在这里」）；「一趟详情」页里是同一对按钮；
- 接着跑：在对话页里接着说一句就行（它就是 `run-agent M --task "…" --resume` 那件事，
  主控**先重新扫一遍工作区**，不靠上一次的记忆——隔天续跑是安全的）。

命令行等价的一条（不经过网页）：

```powershell
python -B -m agentflow --root D:\Incubator\projects\t1-review run-agent M --task "帮我把工作区里那篇论文从头到尾审核一遍，修改掉里面的错误和不恰当表述。" --subagents
```

---

## 4. 钱

- 默认**不限量**（不设上限）。要设：`agentflow budget --set 3`；跑到一半想加：`agentflow budget --add 2`
  （寄存器是项目下的 `budget.json`，追加历史留痕）。
- 花销与上限随时在 `/budget` 看，或 `agentflow budget --status`。
- 预算耗尽会**优雅停止**（在飞的活收尾、没做完的标成 `block`），追加预算后用 `--resume` 接着跑。
- ⚠️ **在网页上改预算（追加 / 重设）需要起服务时带 `--allow-writes`**：

  ```powershell
  python -B -m agentflow --root D:\Incubator\projects\t1-review web --port 8792 --allow-writes --json
  ```

  不带它时，网页上点"追加"会拿到 **403**：`拒绝：POST /api/budget：写面没开 —— 要用
  agentflow web --allow-writes 才允许写`（回执会落到项目下的 `web-actions.jsonl`，能复查）。
  改了立刻生效——闸门**下一次花钱之前**现读盘，不用重启、不用重跑。
  不想开写面就用命令行改（同一份寄存器）：`agentflow budget --add 2`。

---

## 5. 形式化（Lean）开关

- **默认关闭**（省钱，也不要求这台机器装 Lean）。关掉时"证明被核验"走的是
  **V 逐行走查**（`verifications` 表里签「成立」），不是机器检查器。
- 要开：设 `AGENTFLOW_LEAN_ENABLED=1` 再起进程；这台机器上到底有没有 Lean、
  Mathlib 在不在，看 `/machine` 那一页（那是现算读数，不是记忆）。

---

## 6. 东西都在哪

```
D:\Incubator\projects\<项目名>\
├─ source\            你给的原始材料（只读基线；收编时你原有的文件也在这儿或在工作区根）
├─ out\
│   ├─ review\        交付说明 REPORT.md / 审校报告 *-review.md / 状态报告 STATUS-*
│   └─ paper\         main.tex（正文，智能体写）· main.pdf（框架编）· COMPILE-RECEIPT.json
├─ data\              台账（JSON/JSONL：文献、命题、实验、稿件、任务、花销…）
├─ runs\ sessions\    每一趟的完整记录（模型每步的输入输出都在）
├─ manuscripts\       交接手稿
└─ project.json       项目卡（名字、创建的、收编进来的 user_files）
```

---

## 7. 出问题先看这三处

1. `/machine` 或 `agentflow doctor`：这台机器的工具链/模型/Key 现在读到了什么；
2. `runs\` 与 `sessions\`：那一趟到底调了什么、返回了什么（每一步都有落盘）；
3. `data\events.jsonl`：事件流（谁派了谁、谁拒了谁、停在哪一步）。

看不懂的读数就照着念给我（或写进 issue）：**"哪一页、哪一行、原文是什么"**——
框架里绝大多数"奇怪现象"都能在这三处找到出处，而不是"模型不行"。
