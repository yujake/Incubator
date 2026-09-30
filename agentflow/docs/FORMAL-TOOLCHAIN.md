# 形式化验证工具链：装哪个版本、怎么装、装完怎么验

> **现状导读（不构成判据）**：本仓当前分层结构的逐项事实（含路径与复跑命令）见
> [`../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md`](../../draft/35-框架现状：正式版%20agentflow%20的分层结构（逐项带工作区相对路径）.md)。
> 本文只作现状导读、**不构成判据**；判据在 `agentflow/DEVELOPMENT.md` §6 与各门的实现里。
> 本文出现的路径一律**相对工作区根**（`D:\Incubator`）。

> 这份文档只回答三个问题：**装哪个**、**怎么装**、**装完怎么验**。
> "什么算证明"不在本文的范围里 —— 那是 `formalgw` 模块 docstring 的内容。
>
> 判据的实现只有一处：`agentflow/src/agentflow/formalgw.py` 的 `check_toolchain()`。
> 本文不重复其中的任何一条判据（两处各写一份判据的漂移是静默的）。
>
> 路径口径：本文路径一律**相对工作区根**（`D:\Incubator`）；命令在 `agentflow/` 下跑
> （`cd agentflow`）。

## 1. 装哪个版本（pin）

| 组件 | 要求 | 为什么是它 |
|---|---|---|
| Lean | `4.7.0`，commit `6fce8f7d5cd18a4419bca7fd51780c71c9b1cc5a` | 版本号是标签，`lean --version` 里带的是 commit 短哈希 —— 只有 commit 能逐位区分两次构建 |
| Mathlib | commit `a45ae63747140c1b2cbad9d46f518015c047047a`（tag `v4.7.0`） | Mathlib 与 Lean 版本必须配对；`import Mathlib` 的成功与否由这一对决定 |

两条判据是**独立**的：版本号对了、commit 不对，仍算版本不符（负控 C2 实测）。

**这些数字只写在一个地方**：`agentflow/src/agentflow/formalgw.py` 的
`PINNED_LEAN_VERSION` / `PINNED_LEAN_COMMIT` / `PINNED_MATHLIB_COMMIT` /
`PINNED_MATHLIB_TAG`（实测 2026-09-30：四个常量都在，值逐字与上表相同）。
本文上面的表格是它们的副本；
改 pin 时要同时改两处（代码是判据、文档是说明）。

## 2. 怎么装

### 2.1 Lean

1. 取 Lean `v4.7.0` 的官方发行包（Windows 是
   `lean-4.7.0-windows.zip`），解压到任意目录，把 `bin/` 放进 `PATH`。
2. 本机现有的那一份在 `temp/lean470/lean-4.7.0-windows/bin`（工作区根相对路径；
   绝对即 `D:\Incubator\temp\lean470\lean-4.7.0-windows\bin`，里面有 `lean.exe`）。

### 2.2 Mathlib

Mathlib 不是"库文件"，它是一个 **lake 工程**：只有拿到与 Lean 配对的
commit、并把它的 olean 缓存解出来，`import Mathlib` 才成立。

1. 取 tag `v4.7.0` 的源码树
   （`https://codeload.github.com/leanprover-community/mathlib4/tar.gz/refs/tags/v4.7.0`
   ，sha256 `29a4ca317e35ae74b81fc0ce252957f538d758cab2e59d8f890b58493362d5ec`）；
2. 按该树的 `lake-manifest.json` 逐个取六个依赖（`std` / `Qq` / `aesop` /
   `proofwidgets` / `Cli` / `importGraph`）到 `.lake/packages/`；
3. 取 olean 缓存并解包（官方 `lake exe cache get` + `unpack`），或本地
   `lake build Mathlib`（约一小时量级）；
4. **装完必须写一行 commit 到 `.lake/agentflow-mathlib-rev`**：

   ```text
   a45ae63747140c1b2cbad9d46f518015c047047a
   ```

   为什么这一步不能省：缓存解包出来的树**没有 `.git`**（本机实测的
   `temp/mathlib-pinned2/mathlib4-4.7.0` 就是这种形态），而"没有 git 元数据"不等于
   "不知道版本"。不写这一行，版本检查会报 `check_failed`（**未核实**）——
   它既不是"没装"也不是"版本不符"，是一个必须由人补上的事实。

   本机已有的两棵树（`temp/mathlib-pinned/mathlib4-4.7.0`、
   `temp/mathlib-pinned2/mathlib4-4.7.0`）已按上面这一条写好戳文件。

### 2.3 让检查器找得到它

`formalgw` 的 `imports` 默认是 `("Mathlib",)`，而**裸 `lean` 不会替你跑 `lake`**
—— 在非 lake 工程目录里跑 `lean x.lean` 会拿到 `error: unknown package 'Mathlib'`。
两个选择：

- 让检查走工程的 lake 环境（推荐）：把工程根告诉 `check_toolchain`、
  或让调用方走 `lake env lean`；
- 只用内核级命题（`imports=()`）：不依赖任何库，本机现状下**可用**
  （正控实测 `verified: true`）。

## 3. 装完怎么验（可跑）

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
cd D:\Incubator\agentflow
$env:PATH="D:\Incubator\temp\lean470\lean-4.7.0-windows\bin;$env:PATH"
$env:AGENTFLOW_MATHLIB_ROOT="D:\Incubator\temp\mathlib-pinned2\mathlib4-4.7.0"

python -m agentflow.formalgw --toolchain                  # 版本三态（秒级）
python -m agentflow.formalgw --toolchain --import-check    # 额外真跑一次 import Mathlib（约 1 分钟）
```

退出码是判据（不许只看文字）：

| 退出码 | 结论 | 处置 |
|---|---|---|
| 0 | `installed_ok` | 装了且版本与 pin 逐位一致，可以用 |
| 2 | `not_installed` | 没装 ⇒ 按 §2 装 |
| 3 | `version_mismatch` | 装了但版本不符 ⇒ 换版本（不是重装，也不是继续用） |
| 4 | `check_failed` | 探测自己没做成 ⇒ 我们不知道（**不许**读成上面任何一个） |
| 1 | 自检失败 | 本模块的判据有一条没红，必须有人看 |

三态**不许折叠**成"能用/不能用"：`not_installed` 要装，`version_mismatch` 要换，
两者处置相反；而 `check_failed` 是"没查成"，借用任何一态都是一句假话。

## 4. 库不可得会怎么报（与本文相关的相邻判据）

`formalgw.check_lean` 把"包不可得"归到 `import_unavailable`（带包名），
**不是** `compile_error`。理由：`unknown package 'Mathlib'` 说明编译根本没开始，
而 `compile_error` 的语义是"查了、没通过" —— 把前者说成后者是一句假话，
且"这个命题不成立"与"这次没查成"的处置完全相反。

## 5. 本机现状（观测，不是要求）

| 事实 | 值 | 怎么核的 |
|---|---|---|
| Lean | `4.7.0` / commit `6fce8f7d5cd1` / x86_64-w64-windows-gnu | `lean --version`、`lean --githash` |
| Lean 落在哪 | `temp/lean470/lean-4.7.0-windows/bin`（工作区根相对；**部署选择**，不是仓内可复现的钉法，见 `draft/35-…md` §9.2） | `Test-Path temp/lean470/lean-4.7.0-windows/bin` ⇒ `True` |
| Mathlib | 装了（`temp/mathlib-pinned2/mathlib4-4.7.0`，4100 个 olean，`Mathlib.olean` 在） | `check_toolchain` ⇒ `mathlib: installed_ok` |
| Mathlib commit | `a45ae63747140c1b2cbad9d46f518015c047047a` | 该树的 `.lake/agentflow-mathlib-rev` 戳（§2.2 第 4 步写入）；原始来源见 `temp/mathlib-pinned2/EVIDENCE.md` |

**复跑命令**（本文所有路径都相对工作区根 `D:\Incubator`）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
$env:PATH="D:\Incubator\temp\lean470\lean-4.7.0-windows\bin;$env:PATH"
$env:AGENTFLOW_MATHLIB_ROOT="D:\Incubator\temp\mathlib-pinned2\mathlib4-4.7.0"
cd D:\Incubator\agentflow
python -m agentflow.formalgw --toolchain
```

（上表的 `check_toolchain ⇒ mathlib: installed_ok` 就是这么读出来的；本文件不重抄判定逻辑，
判据唯一实现仍在 `agentflow/src/agentflow/formalgw.py` 的 `check_toolchain()`。）
