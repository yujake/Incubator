# 基于 DeepSeek Harness (DSH) 构造"最小可使用智能体"的方法研究报告

> **文档编号**：06
> **证据基线**：本机安装 `@deepseek-ai/dsh@0.1.5-rc.2`，Node.js v24.16.0，npm 12.0.2，Windows
> **证据等级约定**：本文所有包名、命令、配置字段、API 签名均取自本机已安装发行文件或真实执行输出；凡推断内容一律用 `> ⚠️ 推断（未经运行验证）` 显式标注。
> **实测记录**：`D:\Incubator\temp\dsh-minimal\`；命令原始输出：`D:\Incubator\temp\dsh-help\`

---

## 目录

1. [DSH 是什么](#1-dsh-是什么)
2. [最小可用智能体的定义](#2-最小可用智能体的定义)
3. [环境准备](#3-环境准备)
4. [构造路径 A：CLI 直接用](#4-构造路径-acli-直接用)
5. [构造路径 B：插件/配置组装](#5-构造路径-b插件配置组装)
6. [构造路径 C：SDK 编程方式](#6-构造路径-csdk-编程方式)
7. [逐步"加装能力"](#7-逐步加装能力)
8. [验证与调试](#8-验证与调试)
9. [最小可用的边界与风险](#9-最小可用的边界与风险)
10. [附录](#10-附录)
11. [基于 master 真源码的补充核对](#11-基于-master-真源码的补充核对)（版本口径 `0.1.7-alpha.2`，**不覆盖**前文 rc.2 结论）

---

## 1. DSH 是什么

### 1.1 一句话定位

**DSH（DeepSeek Harness）是一个"一切皆插件"的智能体运行框架：唯一的可执行入口是 `dsh` 启动器，它把一串插件包（bundle）的配置补丁层按顺序叠加到一棵配置树上，然后启动其中一个"应用"（Web / Headless / SDK / ACP）。**

本机 `dsh --help` 原文（`temp\dsh-help\dsh--help.txt`）：

```
dsh: boot a DeepSeek Harness profile — an ordered stack of plugin-bundle patch
layers under your own overrides.
```

上游仓库 README 的定位（经 `ghproxy.net` 镜像取得，原文）：

> "DeepSeek Harness (`dsh`) is an open-source agent harness developed by DeepSeek AI."
> "It is built on an **everything-is-a-plugin** architecture and powered by Cordis."
> "DeepSeek Harness is in _developer preview_ and iterating rapidly. **THERE WILL BE COMPATIBILITY-BREAKING CHANGES.**"

### 1.2 "一切皆插件"对本任务的含义

既然框架本身不含任何内建能力，那么**"造一个最小智能体"就等价于"选一个最小的插件集"**。这带来三个直接推论：

| 推论 | 说明 | 证据 |
|---|---|---|
| **能力 = 插件行** | 你想要的每一项能力（读文件、跑命令、搜索网页、开子智能体）都对应配置树里的**一行插件**。不需要的能力不是"关掉代码分支"，而是"根本不写这一行"。 | `dsh-base/cordis.patch.yml` 中每个工具都是一行 `- id: tool-xxx` |
| **可以通过差值做减法** | 每个 profile 的完整配置树可以用 `dsh --profile <n> --dump-config` 打印并计数。于是"最小"是一个**可测量**的量，而不是感觉。 | 本报告实测：`mini` 18 行 / `sdk-minimal` 31 行 / `headless` 87 行 |
| **框架按"能力缝（capability seam）"组织，缝的一侧是可替换的** | 上游把这套模式命名为 **capability seam**，三段式：**Service Definition（接口）/ Provider（实现）/ Consumer（使用者）**。对本任务的含义是：几乎每个"能力"你都可以换掉或整个拿掉，只留 Consumer 就会启动失败（见下行）。 | `dsh-agent-spine-demo` 的 README（`unpkg.com`） |
| **装错了会立刻报错，而不是静默降级** | 框架有 **fail-loud** 机制：启动时若某行插件依赖的服务没被任何一层提供，启动直接失败，**并把缺失的服务名逐条列出来**。这是本报告"最小集"推导的主要方法论来源。 | 见 [§5.4](#54-用-fail-loud-做减法本报告的核心方法) |

### 1.3 三个必须区分的层级

初学者最容易混淆的一点：DSH 里"最小"不是一个概念，而是**两个不同层级**的概念。搞混会导致"我照抄了 minimal 却没有文件工具"这类困惑。

```
┌─ 第 1 层：bundle（应用/框架层）  @deepseek-ai/dsh-{base,headless,sdk-app,sdk-minimal,web-app,acp-app}
│     决定"这台机器上框架具备哪些能力"
│     载体：packages/bundle/*/cordis.patch.yml
│
├─ 第 2 层：profile（部署层）      $DSH_HOME/profiles/<name>/
│     决定"这次启动叠加哪些 bundle + 哪些用户覆盖"
│     载体：package.json 的 dsh.profile.bundles + cordis.patch.yml
│
└─ 第 3 层：preset（智能体层）     $DSH_HOME/.agent-presets/<name>/  或内置 packages/preset/agent-presets/presets/
      决定"这个智能体看到哪些工具、用什么人格"
      载体：preset.yml + agent.cordis.yml
```

**bundle 决定"框架带哪些能力"，preset 决定"这个智能体看到哪些工具、用什么人格"。**

#### 官方对 profile / 组合包的定义（master `docs/architecture.zh.md` L19–L23 原文）

> **profile** 是存放在 Harness home 中的具名组装。它列出自己叠放的组合包，存放自己安装的树外插件，并保存用户自己的 `cordis.patch.yml`。`web`、`headless`、`sdk`、`sdk-minimal` 和 `acp` 作为模板随发行版交付。
>
> **组合包**是 Cordis 配置项及其挂载代码的分发格式，因此它插入的内容始终可被其上各层 patch。
>
> 两者都在各自的 `package.json` 中通过 `dsh` 字段声明自己：`dsh.profile` 列出一个 profile 的组合包，`dsh.bundle` 指向一个组合包的 patch 文件。

同处（L17）对本报告整体架构的一句话总结（原文）：**"运行中的 `dsh` 是一棵插件树，由启动时按序叠加的各层组合而成。"**

> ⚠️ **术语证据等级说明**：官方 `docs/glossary.zh.md` 里**只有** `capability-seam` 一个架构术语条目，**没有** profile / bundle / preset / surface 的术语条目；`docs/architecture.zh.md` **定义了 profile 与组合包**，但**没有定义 preset 与 surface**（只在别处顺带提及）。因此本报告的"三层级"是本报告为读者建立的**工作模型**，其中 profile / bundle 两层有官方定义背书，preset 层的最接近官方表述是 `docs/capability-seams.zh.md` 中的 `ctx.agentPresets` —— "**Per-session agent composition**"（逐会话 agent 组合）。

内置 4 个 preset（rc.2 位置：`packages/preset/agent-presets/presets/`，由 `@deepseek-ai/dsh` 的 `dsh.configTrees` 挂载；**master 已重构，见 [§11.8](#118-master-相对-rc2-的-preset-机制重构前文-13--76-的补注)**）：

| order | 目录 | name | description（原文） | `agent.cordis.yml` |
|---|---|---|---|---|
| 1 | `standard/` | 标准模式 | 功能完整的编码 Agent，支持文件编辑、Shell、文件与网页检索、Skills、计划、目标、子代理和工作流。 | 12,928 B |
| 2 | `ptc/` | PTC 模式 | 功能完整的编码 Agent，但默认不提供 workflow 工具；其他工具通过 PTC 模式 SDK 呈现。 | 14,003 B |
| 3 | **`minimal/`** | **极简模式** | **仅提供持久 shell 的单工具编码 Agent。** | **3,119 B** |
| 4 | `cordis/` | 创造模式 | 用于创建自定义 Agent preset，带运行时检查与 preset 创作指导。 | 14,010 B |

`@deepseek-ai/dsh/package.json` 中的挂载声明（原文）：

```json
"dsh": {
  "configTrees": [
    { "mount": "config/agent-presets",
      "path": "../../packages/preset/agent-presets/presets",
      "scanRoster": true }
  ]
}
```

`scanRoster: true` 表示该配置树会扫描 preset 名册并按 `preset.yml` 的 `order` 排序登记。

---

## 2. 最小可用智能体的定义

### 2.1 "能用"的四个必要条件

一个东西要称得上"可使用智能体"，必须同时具备四件事。缺任何一件都跑不起来或没有意义：

| # | 条件 | 缺了会怎样 |
|---|---|---|
| 1 | **LLM 接入**（provider 路由 + 凭据） | 没有任何模型可调用 |
| 2 | **agent loop**（把消息发给模型、解析工具调用、把结果回灌、循环到停） | 只有一次性的文本补全，不能自主行动 |
| 3 | **至少一个工具** | 模型只能"说"，不能"做"——不是智能体而是聊天机器人 |
| 4 | **会话状态 + 输出** | 无对话历史（每轮失忆）；无输出通道（结果看不到） |

### 2.2 绝对最小集（本报告实测得出）

> 这是**实验得出的下界**，不是抄来的。推导过程见 [§5.4](#54-用-fail-loud-做减法本报告的核心方法)。

**18 行插件 / 18 个不同包**，实测可跑通任务（exit 0）：

| # | 行 id | 包名 | 属于哪一条件 | 作用 |
|---|---|---|---|---|
| 1 | `llm` | `@deepseek-ai/dsh-llm` | ① LLM | provider 无关的 LLM 服务与路由注册表 |
| 2 | `llm-deepseek` | `@deepseek-ai/dsh-llm-deepseek` | ① LLM | 注册 `deepseek-official` 路由；`apiKeyEnv: DEEPSEEK_API_KEY` 按请求解析凭据 |
| 3 | `session` | `@deepseek-ai/dsh-session` | ④ 会话 | 会话/事件日志模型 |
| 4 | `session-projection` | `@deepseek-ai/dsh-session-projection` | ④ 会话 | 投影注册表（`agent-loop` 硬注入它） |
| 5 | `sessions` | `@deepseek-ai/dsh-session-persistence-jsonl` | ④ 会话 | JSONL 落盘到 `$DSH_HOME/sessions` |
| 6 | `system-prompt` | `@deepseek-ai/dsh-system-prompt` | ② loop | 系统提示词装配（persona + 各插件 section） |
| 7 | `tools` | `@deepseek-ai/dsh-tools` | ③ 工具 | 工具注册表（工具插件往这里注册） |
| 8 | `agent` | `@deepseek-ai/dsh-agent` | ② loop | Agent 抽象与运行期类型 |
| 9 | `agent-loop` | `@deepseek-ai/dsh-agent-loop` | ② loop | 真正的 loop 实现：创建 agent、驱动轮次 |
| 10 | `agent-default-model` | `@deepseek-ai/dsh-agent-default-model` | ① LLM | 无会话级选择时的默认 provider/model |
| 11 | `subprocess` | `@deepseek-ai/dsh-subprocess-local` | ③ 工具 | 本地子进程执行能力 |
| 12 | `sandbox` | `@deepseek-ai/dsh-sandbox-local` | ③ 工具 | 沙箱后端 |
| 13 | `sandbox-policy` | `@deepseek-ai/dsh-sandbox-policy` | ③ 工具 | 权限模式 + 工作区根（`dsh-terminal-bash` 硬注入 `sandboxPolicy`） |
| 14 | `pty` | `@deepseek-ai/dsh-terminal` | ③ 工具 | PTY 终端注册表 |
| 15 | `terminal-pwsh` | `@deepseek-ai/dsh-terminal-bash` | ③ 工具 | shell 后端（`shellDialect: pwsh`） |
| 16 | `persistent-pwsh` | `@deepseek-ai/dsh-tool-pwsh-persistent` | ③ 工具 | **唯一的工具**：持久 PowerShell |
| 17 | `headless-startup` | `@deepseek-ai/dsh-headless/startup` | ④ 输出 | 解析 CLI 位置参数为 `task` |
| 18 | `headless-runner` | `@deepseek-ai/dsh-headless` | ④ 输出 | 一次性驱动器：建 agent → 跑任务 → 打印 → 退出 |

**注意其中没有的东西**（这是重点）：

- ❌ 没有 `tool-fs`（**没有文件读写工具**）
- ❌ 没有 `tool-web` / `tool-fs-search`（无联网、无搜索）
- ❌ 没有 `tool-subagent` / `tool-todo` / `tool-goal` / `tool-skill`
- ❌ 没有 `dsh-user-approval`（**没有任何审批环节**）
- ❌ 没有 `dsh-invariants`（无运行时自检）
- ❌ 没有 compaction（**上下文永不压缩**）
- ❌ 没有 `dsh-agent-instructions` / `dsh-time-context`（无运行时上下文注入）

### 2.3 推荐最小集（官方定义的"完整最小 Cordis 树"）

`dsh-sdk-minimal` 的 `cordis.patch.yml`（5,248 B）文件头注释原文：

> Standalone minimal SDK application. Unlike the ordinary SDK profile, this bundle does not layer over dsh-base: **this insert is the complete Cordis tree.** User profile, home, and invocation patches still apply above it.

**31 行插件**，是本报告认定的"官方最小集"权威答案：

| # | id | name | 关键 config |
|---|---|---|---|
| 1 | sdk-app-startup | `dsh-sdk-app` | `profile: sdk-minimal` |
| 2 | sdk-jsonrpc-server | `dsh-sdk-jsonrpc-server` | `inject: [sdkAppStartup, loader]`, `maxTokensAsSuccess: false` |
| 3 | deepseek-llm-api-extensions | `dsh-deepseek-llm-api-extensions` | |
| 4 | session-log-deepseek | `dsh-session-log-deepseek` | |
| 5 | plugin-package-inventory-deepseek | `dsh-plugin-package-inventory-deepseek` | |
| 6 | llm-deepseek | `dsh-llm-deepseek` | `apiKeyEnv: DEEPSEEK_API_KEY`, `defaultContextWindow`, `streamIdleTimeoutMs` |
| 7 | sandbox | `dsh-sandbox-local` | |
| 8 | session-projection | `dsh-session-projection` | |
| 9 | sandbox-policy | `dsh-sandbox-policy` | **`mode: danger-full-access`**, `workspaceRoot: process.cwd()` |
| 10 | subprocess | `dsh-subprocess-local` | |
| 11 | pty | `dsh-terminal` | |
| 12 | terminal-bash | `dsh-terminal-bash` | win32 禁用, `timeoutMs: 300000` |
| 13 | terminal-pwsh | `dsh-terminal-bash` | 非 win32 禁用, `shellDialect: pwsh` |
| 14 | timer | `cordis-plugin-timer` | |
| 15 | llm | `dsh-llm` | |
| 16 | session | `dsh-session` | |
| 17 | session-title | `dsh-session-title` | |
| 18 | system-prompt | `dsh-system-prompt` | `includeHarnessIdentity: false`, `includeRuntimeContext: false` |
| 19 | tools | `dsh-tools` | |
| 20 | agent | `dsh-agent` | |
| 21 | llm-retry | `dsh-llm-retry` | |
| 22 | jobs | `dsh-jobs-local` | |
| 23 | invariants | `dsh-invariants` | |
| 24 | session-invariant | `dsh-session/invariant` | 运行时自检 |
| 25 | agent-invariant | `dsh-agent/invariant` | 运行时自检 |
| 26 | scope-invariant | `dsh-scope/invariant` | 运行时自检 |
| 27 | agent-loop-invariant | `dsh-agent-loop/invariant` | 运行时自检 |
| 28 | agent-loop | `dsh-agent-loop` | `agents: []` |
| 29 | persistent-bash | `dsh-tool-bash-persistent` | 非 win32, `timeoutMs: 300000` |
| 30 | persistent-pwsh | `dsh-tool-pwsh-persistent` | win32, `timeoutMs: 300000` |
| 31 | sessions | `dsh-session-persistence-jsonl` | `root: dshHomePath('sessions')`, `compression: none` |

**官方最小集的批判性事实**（做生产决策时必须知道）：

1. **写死 `danger-full-access`**（第 9 行）——shell 可修改进程能触达的任何路径。
2. **没有 `dsh-user-approval`**——即使 policy 是 ask 也没有审批实现。
3. **没有 `tool-fs`**——文件读写只能绕道 shell。
4. **它的对外接口是 JSON-RPC over stdio**，不是给人直接用的 CLI。人直接敲 `dsh --profile sdk-minimal` 只会得到一个等待 stdio 帧的进程。
5. 官方 README 自己就此警告：**"其 danger-full-access 策略允许 shell 修改进程可访问的任何路径，因此只能配合隔离 workspace 使用。"**

### 2.4 两档清单对照

| | 绝对最小集（§2.2） | 推荐最小集（§2.3，官方） |
|---|---|---|
| 插件行数 | **19** | **31** |
| 不同包数 | 18 | 30 |
| 入口 | `dsh --profile <n> "任务"`（Headless，**人可直接用**） | JSON-RPC over stdio（**给程序用**） |
| 沙箱 | `danger-full-access`，无审批 | `danger-full-access`，无审批 |
| 工具 | 1 个（persistent pwsh） | 1 个（persistent bash/pwsh） |
| 会话落盘 | JSONL | JSONL，`compression: none` |
| 自检 | 无 | `dsh-invariants` + 4 个 `/invariant` |
| 重试 | 无 | `dsh-llm-retry` |
| 标题 | 无 | `dsh-session-title` |
| 适用场景 | 想在 20 行内理解 DSH 全貌 | 想用 SDK 嵌入 DSH |

**推荐做法**：理解框架用**绝对最小集**（18 行，能一眼看完），实际落地用**官方最小集 + 加固**（§9.4）。

---

## 3. 环境准备

### 3.1 Node 版本

- 本机实测：**Node.js v24.16.0**，npm 12.0.2，工作正常。
- **官方声明（一手证据）**：仓库根 `package.json` 的 `engines` 字段：

  ```json
  "engines": { "node": "^22.19.0 || >=24.0.0" }
  ```

  即 **Node 22.19.0 以上、或 Node 24 及以上**。注意 `^22.19.0` 排除了 22.0–22.18，`>=24.0.0` 无上限。
- 注意：`@deepseek-ai/dsh` **发布到 npm 的那个包的 `package.json` 里并没有 `engines`**（本机安装的 `dsh\package.json` 无此字段），该约束声明在**仓库根** `package.json` 上。因此 npm 不会拦截，但低于 22.19 的 Node 不受支持。
- 各版本发布时的 `_nodeVersion`（npm 元数据）也印证了 Node 22/24 双线：
  `24.18.0`（0.0.1-rc.1）→ `24.19.0`（0.1.2-rc.1）→ `24.20.0`（0.1.3-alpha.2）。
- 依赖中有原生模块 `node-pty`（PTY 栈）与 `node-addon-require-builtin`，Windows 上编译/加载失败会导致持久 shell 工具不可用。

> ⚠️ 未经运行验证：本报告**仅在 Node 24.16.0 上实测**，未在 Node 22.19+ 上验证。`engines` 是本报告从仓库根 `package.json` 取得的官方声明，非本机实测结论。

- 依赖中有原生模块 `node-pty`（PTY 栈）与 `node-addon-require-builtin`，Windows 上编译/加载失败会导致持久 shell 工具不可用。

### 3.2 安装方式

本机已验证的安装形态是**全局 npm 安装**：

```powershell
npm i -g @deepseek-ai/dsh
# 本机安装路径：
# C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh
```

> 注意：上游 README **并未把 `npm i -g` 写进官方快速开始**（README 给的是 `npx` 与源码两条路）。`npm i -g` 之所以有效，是因为包确实声明了 bin（`{"dsh":"lib/bin.js"}`）——本机就是这么装的并可用。属于"实际可行但非官方文档首推"的路径。

**上游 README 官方给出的两条路径**：

```sh
# 路径 1：零安装（Web UI 起在 http://127.0.0.1:3080）
npx @deepseek-ai/dsh web
#   --no-open 可阻止自动打开浏览器

# 路径 2：源码构建
git clone https://github.com/deepseek-ai/deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

> ⚠️ 未经运行验证：`npx` 与源码构建两条路本报告**未在本机执行**；本文所有命令均基于全局安装形态。

**第三条路径：Python SDK（自带运行时，不需要系统 Node）**

```sh
python -m pip install deepseek-harness-sdk     # requires_python >=3.10
```

它会连带安装同版本的 `deepseek-harness-runtime-bin` wheel（即打包好的 `dsh` 运行时）。详见 [§6.3.4](#634-python-sdk官方文档原文pypi-实测取得)。

npm 当前 dist-tags（`registry.npmjs.org/@deepseek-ai/dsh`，实测取得）：

```
latest = 0.1.5-rc.3
next   = 0.1.5-rc.3
alpha  = 0.1.7-alpha.2
```

本机安装的是 **0.1.5-rc.2**（`dsh --version` 实测输出）。

**版本错位警告**：

| 对象 | 版本 |
|---|---|
| 本机安装的 `@deepseek-ai/dsh` | `0.1.5-rc.2` |
| npm `latest` | `0.1.5-rc.3` |
| npm `alpha` / 仓库 master | `0.1.7-alpha.2` |
| `@deepseek-ai/dsh-sdk-minimal` 的 npm `latest` | **`0.1.2-alpha.2`（旧于其 `next`）** |
| `@deepseek-ai/dsh-sdk-minimal` 的 npm `next` | `0.1.5-rc.3` |

`sdk-minimal` 的 `latest` 落后于 `next`，因此 `npm i @deepseek-ai/dsh-sdk-minimal` 会拿到旧版——**这是本项目当前的真实坑**，装该包时应显式指定版本或 tag。

**本机与新版的一处真实差异（版本漂移的实证）**：本机 `0.1.5-rc.2` 的 `sdk-minimal` 工具行是 `persistent-bash` / `persistent-pwsh`（即 `dsh-tool-bash-persistent` / `dsh-tool-pwsh-persistent`）；而 npm 上 `0.1.5-rc.3` 的包描述已变成 "…persistent shell, **editor**, and JSONL sessions"，暗示 rc.3 又加了编辑器工具。**升级时以 `--dump-config` 重新核对行清单。**

### 3.3 安装目录结构（本机实测）

```
C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\
├── package.json          # bin: { dsh: "lib/bin.js" }；dsh.configTrees；依赖清单
├── lib/
│   ├── bin.js                 # 入口（commander 解析 launcher 自己的 flag）
│   ├── profile-boot-Dk-7KqJc.js   # 核心：profile 解析 + patch 层叠加 + boot
│   ├── plugin-Ddi42qoW.js         # `dsh plugin` → 转发 pnpm
│   └── dump-config-lFgMwK8i.js    # `--dump-config` 实现
├── README.md / README.zh.md / README.i18n.yaml
└── node_modules/@deepseek-ai/     # CLI 自带的包子集
```

**完整插件清单不在这个目录里。** 全部 240 个 `@deepseek-ai/*` 包位于**用户 profile 的共享依赖目录**：

```
C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\   ← 240 个包
```

### 3.4 API key 配置

**环境变量名：`DEEPSEEK_API_KEY`**（由 `dsh-llm-deepseek` 的 `apiKeyEnv` 配置项指定，缺省即为此名）。

三种提供方式（按解析优先级，来自 `dsh-credentials-local` 的 README 描述）：

| 方式 | 位置 | 说明 |
|---|---|---|
| ① 继承的环境变量 | `$env:DEEPSEEK_API_KEY` | 优先级最高 |
| ② 托管凭据文档 | `$DSH_HOME\.credentials.yaml` 的 `refs:` 段 | 本机实际使用的方式 |
| ③ `.env` 回退 | 项目级 / 用户级 `.env` | |

本机 `.credentials.yaml` 结构（**已脱敏**）：

```yaml
version: 1
records:
  client-connection/browser-session:
    kind: grant
    payload:
      version: 1
      secret: <REDACTED>
refs:
  DEEPSEEK_API_KEY: sk-07****REDACTED
```

配置方式二选一：

```powershell
# 方式 A：当前会话环境变量（推荐用于脚本/CI，最不易泄漏）
$env:DEEPSEEK_API_KEY = "sk-..."

# 方式 B：写入托管凭据文档（Web GUI 的 Models 页面写的就是这个文件）
#   文件：$DSH_HOME\.credentials.yaml   → refs.DEEPSEEK_API_KEY
```

> 🔒 **脱敏纪律**：`.credentials.yaml` 是明文密钥文件，**切勿提交到版本库**。本报告所有示例与实测记录中的密钥均已替换为 `sk-07****REDACTED`。

**其它可配置的环境变量**（均从发行配置中读取到，原文出现）：

| 变量 | 作用 | 证据位置 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 模型凭据 | `dsh-llm-deepseek` 的 `apiKeyEnv` |
| `DEEPSEEK_BASE_URL` | 覆盖端点（默认 `https://api.deepseek.com`） | `dsh-llm-deepseek` README |
| `DSH_HOME` | Harness 主目录（默认 `~/.dsh`） | `dsh-home-paths`；`bin.js` 用 `loadLayeredEnv("dsh")` |
| `DSH_CONTEXT_WINDOW` | 无精确容量模型的上下文回退 | `dsh-sdk-minimal` patch 第 30 行 |
| `DSH_SYSTEM_PROMPT` | 替换默认 persona | `dsh-sdk-minimal` patch 第 89 行 |
| `DSH_PERMISSION_MODE` | 权限模式（`read-only`/`workspace-write`/`danger-full-access`），默认 `workspace-write` | `dsh-base` patch 第 211 行 |
| `DSH_TOOLS_MODE` | 进程级 PTC（程序化工具调用）开关 | `dsh-headless` patch 第 16 行 |
| `DSH_TELEMETRY_MODE` | 遥测模式，默认 `FEEDBACK_ONLY` | `dsh-base` patch 第 187 行 |
| `DSH_TELEMETRY_DISABLED` | **任意非空值**即关闭遥测（含 `0`/`false`） | `dsh-base` patch 注释 + `profile-boot` 逻辑 |
| `DSH_TELEMETRY_OTLP_URL` | 覆盖遥测端点 | `dsh-base` patch 第 190 行 |
| `DSH_MAX_TOKENS_AS_SUCCESS` | SDK 子智能体达 token 上限时是否算成功 | `dsh-sdk-app` README |

`DSH_PERMISSION_MODE` 的三档预设权威定义（`dsh-base/cordis.patch.yml` 原文）：

```yaml
    - id: permission
      name: '@deepseek-ai/dsh-permission-presets'
      config:
        presets:
          read-only:
            sandbox: read-only
            approval: ask
          workspace-write:
            sandbox: workspace-write
            approval: ask
          danger-full-access:
            sandbox: danger-full-access
            approval: never
```

### 3.5 首次运行验证

```powershell
# 0) 版本自检（Node 需满足 engines: ^22.19.0 || >=24.0.0）
node --version
# 实测：v24.16.0  ✅

# 1) 版本
dsh --version
# 实测输出：0.1.5-rc.2

# 2) 启动器自己的帮助（不启动任何 profile）
dsh --help

# 3) 验证 profile 组合树（最关键的一步：不启动、只看会挂载什么）
dsh --profile headless --dump-default-config      # 只看 bundle 层
dsh --profile headless --dump-config              # 含用户层与 --patch

# 4) 依赖检查：首个 profile 会自动初始化到 $DSH_HOME/profiles/<name>
$env:DSH_HOME = "D:\some\writable\path\dsh-home"   # 建议显式指定，避免污染 ~/.dsh
dsh --profile headless --help
```

> **环境变量隔离建议**：`DSH_HOME` 指到独立目录即可完全隔离实验环境，本报告全部实验均如此（`DSH_HOME=D:\Incubator\temp\dsh-minimal\dsh-home`）。Python SDK 亦强制这一习惯——**它刻意不去发现 `~/.dsh`**。

`dsh --profile headless --help` 实测输出（`temp\dsh-minimal\headless-help.txt`）：

```
Usage: dsh --profile headless [options] [task...]

Answer one task, stream reasoning to stderr, print the final assistant message,
and exit.

Arguments:
  task        the task text; multiple words are joined by spaces

Options:
  -h, --help  show this help

Examples:
  dsh --profile headless "run the tests"     answer one task and exit
```

### 3.6 ⚠️ 首次运行的重要陷阱

`dsh` 启动时**必然写入** profile 目录下的 `cordis.yml`（根配置，恒为空表）。证据来自 `lib\profile-boot-Dk-7KqJc.js`：

```js
function prepareProfile(name, userLayer = true, fromDefaultProfile) {
  if (fromDefaultProfile !== void 0) initializeProfileFromDefault(name, fromDefaultProfile);
  const profile = loadProfile(NAME, name, INSTALL_ANCHOR, void 0, { userLayer });
  writeFileSync(join(profile.dir, PROFILE_ROOT_FILENAME), PROFILE_ROOT_CONFIG);
  return profile;
}
```

**因此：如果 `$DSH_HOME` 指向一个只读目录，`dsh` 会在启动阶段直接崩溃。** 本机真实复现：

```
Error: EPERM: operation not permitted, open 'C:\Users\ysc20\.dsh\profiles\web\cordis.yml'
    errno: -4048, code: 'EPERM'
    at prepareProfile (.../lib/profile-boot-Dk-7KqJc.js:209:2)
```

**排查结论**：一定要让 `$DSH_HOME` 指向可写位置。本报告所有实验都用 `DSH_HOME=D:\Incubator\temp\dsh-minimal\dsh-home` 隔离，未污染用户真实的 `~/.dsh`。

---

## 4. 构造路径 A：CLI 直接用

**目标**：不写任何代码，只用命令行在 1 分钟内跑通一个能干活的最小智能体。

### 4.1 最短路径：内置 `headless` profile（1 条命令）

```powershell
# 前置：Node 24 + 全局 dsh + DEEPSEEK_API_KEY
$env:DEEPSEEK_API_KEY = "sk-..."
$env:DSH_TELEMETRY_DISABLED = "1"     # 关闭遥测（可选但推荐）

# 就这一条
dsh --profile headless "列出当前目录下的文件，报告文件数量"
```

**这条命令背后发生的事**：

1. `headless` 是**随发行版交付的 profile 模板**，首次使用时自动初始化到 `$DSH_HOME\profiles\headless\`；
2. 其 `package.json` 声明 `bundles: ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]`——即"完整基础能力 + 一次性驱动器"；
3. 组合出 **87 行插件**（实测 `--dump-default-config` 计数），含完整工具集：`tool-fs`、`tool-pwsh`、`tool-web`、`tool-fs-search`、`tool-subagent`、`tool-todo`、`tool-goal`、`skill`（无 `bash`，Windows 上被 `disabled` 门控）；
4. agent 完成任务 → 最终答案写 **stdout** → 退出。

**输出约定**（`dsh-headless` README 原文）：

| 通道 | 内容 |
|---|---|
| stdout | 最终 assistant 消息文本 |
| stderr | `dsh: reasoning:` 前缀的推理增量流；失败时 `dsh: <code>: <message>` |
| 退出码 | 完成 `turn/end` → **0**；aborted / error / 无轮次 → **1** |

### 4.2 本机实测记录

**实验 RUN 1**（`temp\dsh-minimal\RUN1-headless-stdout.txt` / `RUN1-notes.txt`）：

```powershell
$env:DSH_HOME = "D:\Incubator\temp\dsh-minimal\dsh-home"   # 全新，首次自动初始化
$env:DSH_TELEMETRY_DISABLED = "1"
$env:DSH_PERMISSION_MODE = "workspace-write"
$env:DEEPSEEK_API_KEY = <从 ~/.dsh/.credentials.yaml 读取，未打印>
Set-Location "D:\Incubator\temp\dsh-minimal"
dsh --profile headless "Reply with exactly the text: MINIMAL-OK"
```

实测结果：

```
EXIT=0  ELAPSED=4.51s
STDOUT: MINIMAL-OK
STDERR: (空 —— 无推理增量)
```

**这就是"跑通的最小示例"。**

### 4.3 带 `--patch` 的一次性覆盖

`--patch` 可重复，叠加在 profile 用户层**之后**（优先级最高）：

```powershell
# extra.yml
@'
- id: system-prompt
  config:
    personaPrefix: You are a terse assistant. Answer in one line.
    includeHarnessIdentity: false
    includeRuntimeContext: false
'@ | Set-Content .\extra.yml

dsh --profile headless --patch .\extra.yml "1+1=?"
```

> 注意 `patch` 的语义：**替换目标行的整个 `config`，不是合并**（`dsh-base` README 原文："patch 会替换目标行的整个 `config`，而不是合并进它"）。所以覆盖 `system-prompt` 时必须重述所有想保留的字段。

### 4.4 创建自己的 profile（`--from-default-profile`）

```powershell
# 从随附 headless 模板创建一个名为 myagent 的自定义 profile，然后启动
dsh --profile myagent --from-default-profile headless "你好"
```

- 目标名**不能是随附名**（`web`/`headless`/`sdk`/`sdk-minimal`/`acp`），否则报错；
- 目标目录**必须不存在**，否则报错；
- 该命令会拷贝模板的 `bundles` 列表与 `patchReload` 策略，然后启动。

实测可用（本机 `dsh --profile headless --help` 与 `--profile mini` 的成功启动即证明了同一套 profile 初始化路径）。

### 4.5 `dsh plugin` 管理 profile 的插件依赖

```powershell
dsh plugin --profile myagent add @deepseek-ai/dsh-tool-todo
dsh plugin --profile myagent why @deepseek-ai/dsh-tool-todo
```

- 语义：**把剩余参数原样转发给 profile 目录里的 pnpm**（`bin.js` 原文：`"manage a profile's plugins by forwarding the remaining arguments to pnpm in the profile directory"`）；
- `--profile` 是**必需**选项，否则 `error: required option '--profile <name>' not specified`（实测）；
- 需要 `--profile` 已初始化；本机实测 `dsh plugin --profile mini init` 会初始化目录，但随后 pnpm 因 `ERR_PNPM_PACKAGE_JSON_EXISTS` 报错退出 1 —— 即 `init` 参数并非 pnpm 的真实子命令。

> ⚠️ 推断（未经运行验证）：`dsh plugin` 的可用子命令取决于 profile 目录内 pnpm 的版本与能力，报告只验证了 `add`/`why` 的转发语义存在，未逐一实跑。

---

## 5. 构造路径 B：插件/配置组装

**目标**：不满足于现成 profile，自己精确控制"只开必要插件"。

### 5.1 装配公式（决定性）

```
最终配置树 = ① dsh.profile.bundles 中每个 bundle 的 patch（按数组顺序）
           → ② profile 自己的 cordis.patch.yml（用户层）
           → ③ $DSH_HOME/cordis.patch.yml（home 级用户层）
           → ④ 每个 --patch <file> 覆盖层（按 argv 顺序）
           → ⑤ 遥测开关派生出的 patch（若 DSH_TELEMETRY_DISABLED 非空）
```

全部叠加在 profile 的 `cordis.yml`（**恒为空表 `[]`**）之上。证据：`lib\profile-boot-Dk-7KqJc.js` 的 `composeProfile()` 与 `allPatches()`，以及 profile 根文件模板原文：

```yaml
# dsh profile root — an empty entry list. The tree is composed as patches:
# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml, then any
# --patch overlays. Edit cordis.patch.yml, not this file.
[]
```

**这个顺序有官方文档逐字背书**（master `docs/architecture.zh.md` L27 原文）：

> 各层按此顺序应用在空条目列表之上：先按 profile 列出的顺序应用每个组合包，然后是 profile 的 `cordis.patch.yml`，然后是 home 级的那份，最后是任意 `--patch` overlay。**一条 patch 按 id 定位某个条目并替换其整个 config，或插入新条目。**

同处 L29 补充了 HMR 的分层默认值（原文）：**"base 启用仅监视配置的 `dsh-hmr`；Headless、SDK 和 ACP 禁用它；`sdk-minimal` 不包含它。Profile patch 覆盖这些默认值。"** —— 这正是 §2.3 官方最小集里没有 HMR 行的原因。

L39 还给了本报告反复使用的那条实用建议（原文）：**"它打印出的任何条目，都可以由你自己的 patch 替换。"**（指 `dsh --profile web --dump-config` 的输出。）

**patch 条目只有三种操作：**

| 操作 | 语法 | 含义 |
|---|---|---|
| **覆盖配置** | `- id: <行id>` + `config: {...}` | 用新 config **整体替换**该行的 config |
| **禁用** | `- id: <行id>` + `disabled: true` | 关掉该行（不加载该插件） |
| **插入** | `- insert: [ { id, name, config, inject, disabled }, ... ]` | 追加新的插件行 |

`!!js` 允许写 JS 表达式（读环境变量、按平台分支）：

```yaml
      disabled: !!js process.platform === 'win32'
      mode: !!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'
```

### 5.2 最小 profile 文件清单

一个 profile 目录**只需要 2 个文件**：

```
$DSH_HOME/profiles/myagent/
├── package.json          # 声明 bundles 列表与 patchReload 策略
└── cordis.patch.yml      # 用户补丁层
```

`package.json` 最小形态：

```json
{
  "name": "dsh-profile-myagent",
  "private": true,
  "dependencies": {},
  "dsh": {
    "profile": {
      "bundles": ["@deepseek-ai/dsh-base"],
      "patchReload": "startup"
    }
  }
}
```

| 字段 | 取值 | 含义 |
|---|---|---|
| `dsh.profile.bundles` | 有序数组 | 依次叠加的 bundle 层 |
| `dsh.profile.patchReload` | `live` \| `startup` | `live` 会监视并热重载 patch 文件；`startup` 只在启动时应用一次。随附的 Web 是 `live`，其余随附 profile 是 `startup`，**自定义 profile 默认 `live`** |

### 5.3 路径 B-1：叠加 `dsh-base` 后做减法（推荐）

这是最实用的路线：从完整能力出发，把不要的**逐行 `disabled: true`**。

```yaml
# $DSH_HOME/profiles/myagent/cordis.patch.yml
# 目标：保留文件读写 + shell，去掉联网/子智能体/网页/技能/工作流/待办/目标

- id: tool-web
  disabled: true
- id: web
  disabled: true
- id: web-search-deepseek
  disabled: true
- id: web-fetch-http
  disabled: true

- id: tool-fs-search
  disabled: true

- id: tool-subagent
  disabled: true
- id: tool-subagent-fork
  disabled: true
- id: tool-subagent-control
  disabled: true
- id: tool-subagent-list-agents
  disabled: true

- id: tool-workflow
  disabled: true
- id: workflow-worker-thread
  disabled: true

- id: tool-todo
  disabled: true
- id: tool-goal
  disabled: true
- id: tool-ralph
  disabled: true
- id: tool-skill
  disabled: true
- id: skill
  disabled: true
- id: skill-filesystem
  disabled: true

- id: plan-mode
  disabled: true

# 换更严的权限：只读工作区
- id: sandbox-policy
  config:
    mode: read-only
    workspaceRoot: !!js process.cwd()
- id: approval
  config:
    policy: ask
```

**验证减法结果**：

```powershell
dsh --profile myagent --dump-config | Select-String '^\s*- id:'
```

> ⚠️ 推断（未经运行验证）：上面这份 `disabled` 清单中的**行 id** 全部取自 `dsh-base/cordis.patch.yml` 的真实行（已逐条核对），但**这份具体组合未在本机启动验证**。做减法时若某行的 `id` 拼写与 bundle 里的不一致，patch 会被**静默跳过**（`composeEntries` 的 `warn` 回调在 boot 时才会重复打印诊断）。**务必用 `--dump-config` 确认行确实消失了。**

### 5.4 用 fail-loud 做减法（本报告的核心方法）

这是本报告推导出 §2.2 "绝对最小集"的**实证方法**，强烈推荐给所有想找下界的人。

**方法**：从一个空树出发，只写"我认为需要"的行，启动，读错误。

启动失败时的报错**会精确列出每个未激活的行在等哪个服务**：

```
Error: dsh: plugin tree failed to load: dsh: 3 entries did not activate
@deepseek-ai/dsh-agent-loop: pending (waiting for service: sessionProjections)
@deepseek-ai/dsh-pwsh-local: pending (waiting for service: subprocess)
@deepseek-ai/dsh-headless: pending (waiting for service: agentDefaultModel)
```

这是**可执行的依赖求解器**。按它给出的名字补一行，重启，重复。

**本机实测的完整推导轨迹**（`temp\dsh-minimal\`）：

| 轮次 | 我写的行 | 报错 | 修法 |
|---|---|---|---|
| 1 | 含 `- id: scope, name: '@deepseek-ai/dsh-scope'` | `invalid plugin, expect function or object with an "apply" method, received object` | `dsh-scope` 是**工具库不是插件**，删掉 |
| 2 | 删 scope 后 | `pending (waiting for service: sessionProjections)` / `subprocess` / `agentDefaultModel` | 各补一行 |
| 3 | 又加了 `- id: shell, name: '@deepseek-ai/dsh-shell'` | `service "shell" has been registered at <ShellExecutor>`（重复注册） | `dsh-shell` 是抽象基类，**具体后端自己 provide `shell`**，删掉 |
| 4 | — | **`EXIT=0`，`MINI4-OK`** | ✅ |

**第 4 轮实测输出**：

```
RUN_EXIT=0  ELAPSED=1.96s
STDOUT: MINI5-OK
```

**这个方法的两个副产品洞察**：

1. **`dsh-scope` 不是插件**。它的 `package.json` exports 只有 `.` 与 `./invariant`，主入口导出的是一堆类型与工具函数，没有 `apply`。官方 `sdk-minimal` 只把它以 `@deepseek-ai/dsh-scope/invariant` 形式挂载。
2. **`dsh-shell` 不是可挂载插件**，而是 `ShellExecutor` 抽象基类：`dsh-pwsh-local` / `dsh-pwsh-sandbox` 内部 `extends ShellExecutor` 并自己 `provide("shell")`（报错栈原文：`at new ShellExecutor (.../dsh-shell/lib/index.js:86:3)` → `at new PwshLocalExecutor (.../dsh-pwsh-local/lib/index.js:223:3)`），所以**再挂 `dsh-shell` 会重复注册并 fail-loud**。

### 5.5 路径 B-2：完全不叠 bundle，自建整棵树

对应 §2.2 的 18 行。完整可复制文件：

**`$DSH_HOME/profiles/mini/package.json`**：

```json
{
  "name": "dsh-profile-mini",
  "private": true,
  "dependencies": {},
  "dsh": {
    "profile": {
      "bundles": [],
      "patchReload": "startup"
    }
  }
}
```

注意 `bundles: []` —— **不叠任何 bundle**，`cordis.patch.yml` 就是整棵树。

**`$DSH_HOME/profiles/mini/cordis.patch.yml`**（实测 exit 0 的版本）：

```yaml
- insert:
    # ---- LLM 接入 -------------------------------------------------------
    - id: llm
      name: '@deepseek-ai/dsh-llm'
    - id: llm-deepseek
      name: '@deepseek-ai/dsh-llm-deepseek'
      config:
        apiKeyEnv: DEEPSEEK_API_KEY

    # ---- 会话状态 --------------------------------------------------------
    - id: session
      name: '@deepseek-ai/dsh-session'
    - id: session-projection
      name: '@deepseek-ai/dsh-session-projection'
    - id: sessions
      name: '@deepseek-ai/dsh-session-persistence-jsonl'
      config:
        root: !!js dshHomePath('sessions')

    # ---- agent 内核 ------------------------------------------------------
    - id: system-prompt
      name: '@deepseek-ai/dsh-system-prompt'
      config:
        personaPrefix: You are a minimal test agent.
        includeHarnessIdentity: false
        includeRuntimeContext: false
    - id: tools
      name: '@deepseek-ai/dsh-tools'
    - id: agent
      name: '@deepseek-ai/dsh-agent'
    - id: agent-default-model
      name: '@deepseek-ai/dsh-agent-default-model'
      config:
        provider: deepseek-official
        model: deepseek-flash
    - id: agent-loop
      name: '@deepseek-ai/dsh-agent-loop'
      config:
        agents:
          - id: mini
            provider: deepseek-official
            model: deepseek-flash

    # ---- 唯一一个工具：持久 PowerShell ------------------------------------
    - id: subprocess
      name: '@deepseek-ai/dsh-subprocess-local'
    - id: sandbox
      name: '@deepseek-ai/dsh-sandbox-local'
    - id: sandbox-policy
      name: '@deepseek-ai/dsh-sandbox-policy'
      config:
        mode: danger-full-access
        workspaceRoot: !!js process.cwd()
    - id: pty
      name: '@deepseek-ai/dsh-terminal'
    - id: terminal-pwsh
      name: '@deepseek-ai/dsh-terminal-bash'
      config:
        shellDialect: pwsh
        timeoutMs: 300000
    - id: persistent-pwsh
      name: '@deepseek-ai/dsh-tool-pwsh-persistent'
      config:
        timeoutMs: 300000

    # ---- 驱动器：one-shot runner ----------------------------------------
    - id: headless-startup
      name: '@deepseek-ai/dsh-headless/startup'
    - id: headless-runner
      name: '@deepseek-ai/dsh-headless'
      inject: [headlessStartup]
      config:
        task: !!js ctx.headlessStartup.task
```

运行：

```powershell
$env:DSH_HOME = "D:\Incubator\temp\dsh-minimal\dsh-home"
$env:DEEPSEEK_API_KEY = "sk-..."
dsh --profile mini "Reply with exactly: MINI5-OK"
# 实测：EXIT=0  ELAPSED=1.96s  STDOUT: MINI5-OK
```

**注意第 6 行 `llm-deepseek` 没写 `config`**，走 schema 缺省：`apiKeyEnv` 默认就是 `DEEPSEEK_API_KEY`，`baseURL` 默认 `https://api.deepseek.com`，`defaultContextWindow` 默认 1,000,000。

**关键点**：`headless-runner` 的 `config.task: !!js ctx.headlessStartup.task` —— 这是 **patch 解析期的 JS 表达式**，`ctx` 是 loader 上下文。它把 CLI 位置参数从 `headless-startup` 服务里取出来。这是"用配置做依赖注入"的真实范例。

### 5.6 路径 B-3：用 `--patch` 做临时覆盖（不建 profile）

```powershell
# 在任意已有 profile 上临时叠一层，不修改任何文件
dsh --profile headless --patch .\tighten.yml "任务"
```

`tighten.yml`：

```yaml
- id: sandbox-policy
  config:
    mode: read-only
    workspaceRoot: !!js process.cwd()
```

这是**实验最安全的方式**：不动 profile 文件，一个文件就是一次覆盖。

### 5.7 三个 profile 的实测对比

| profile | 插件行数 | 不同包数 | `--dump-config` 打印的 `- id:` 行数 | 说明 |
|---|---|---|---|---|
| `mini`（本报告自建，`bundles: []`） | **18** | 18 | **19** | §2.2 绝对最小集。第 19 个 `- id:` 是 `agent-loop` 的 `config.agents[0].id`（值 `mini`），不是插件行 |
| `sdk-minimal`（官方） | **31** | 30 | **31** | §2.3 官方最小集 |
| `headless`（官方） | **87** | 86 | **87** | 完整基础 + 一次性驱动 |

命令：

```powershell
dsh --profile mini --dump-config          > dump-mini.yml
dsh --profile sdk-minimal --dump-default-config > dump-sdk-minimal.yml
dsh --profile headless --dump-default-config    > dump-headless.yml
```

> 注意 `-` 与 `--dump-default-config` 的区别：前者**含**用户层与 `--patch`；后者**不含**，只打印 bundle 层，且不接受 `--patch`。

---

## 6. 构造路径 C：SDK 编程方式

### 6.1 官方 SDK 形态（重要澄清）

**DSH 的 SDK 不是一个可 `import` 的库，而是一个"以 JSON-RPC over stdio 提供服务的 profile"。** 证据：

- `dsh --profile sdk` → 通过 JSON-RPC stdio 为 SDK client 提供服务，直至关闭或断开连接；
- `dsh --profile sdk-minimal` → 以独立极简 agent 配置树为 SDK client 提供服务；
- `@deepseek-ai/dsh-sdk-app` 的职责（README 原文）："**只在该提供方接受调用后**启动 `dsh-sdk-jsonrpc-server`"；
- `@deepseek-ai/dsh-sdk-app` 的源码 `lib/index.js`（**已加行号核对，非推断**）：

```js
/** Stable Cordis plugin name. */
const name = "sdk-app-startup";
/** Launcher service required before this app can parse its invocation. */
const inject = ["cmdlineArgs"];
/** Service the JSON-RPC server row waits for before claiming stdio. */
const SDK_APP_STARTUP_SERVICE = "sdkAppStartup";
/** Validate and default SDK stdio startup configuration. */
const Config = z.object({ profile: z.string().default("sdk") });

function sdkCommand(profile) {
  return new Command().name(`dsh --profile ${profile}`)
    .description("Serve DeepSeek Harness SDK clients over stdio JSON-RPC.")
    .helpOption("-h, --help", "show this help")...;
}

function apply(ctx, config = {}) {
  const program = sdkCommand(config.profile ?? "sdk");
  program.action(() => {
    exitOnStdinEnd(ctx, "sdk-app.stdin");
    ctx.provide(SDK_APP_STARTUP_SERVICE, { accepted: true });
  });
  parseCmdline(ctx, program);
}
```

**读出来的契约**：

| 事实 | 证据 |
|---|---|
| 插件名 `sdk-app-startup`，必须 `inject: ["cmdlineArgs"]` | 源码 `const name` / `const inject` |
| 对外服务名 `sdkAppStartup`，值是 `{ accepted: true }` | 源码 `ctx.provide(SDK_APP_STARTUP_SERVICE, ...)` |
| 配置只有一个字段 `profile`（默认 `"sdk"`），只用于**渲染 help 文本** | 源码 `Config = z.object({ profile: z.string().default("sdk") })` |
| **`--help` 时不占用 stdin/stdout**（因为 `provide` 只在 action 里执行） | README："`dsh --profile sdk --help` 会写出 help 并退出，不会占用 stdin 或 stdout" |
| stdin EOF 绑定到启动器的有界关闭 | 源码 `exitOnStdinEnd(ctx, "sdk-app.stdin")` |

`@deepseek-ai/dsh-sdk-minimal` 是**唯一不叠 `dsh-base` 的 bundle**：

```json
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" }
}
```

`package.json` 依赖清单（**27 个，这是官方认定的最小闭包**）：

| 包 | 为什么最小集需要它 |
|---|---|
| `dsh-agent-loop` | loop 实现 |
| `cordis-plugin-timer` | 定时器（retry/超时用） |
| `dsh-deepseek-llm-api-extensions` | DeepSeek 请求扩展字段 |
| `dsh-jobs-local` | 本地作业 |
| `dsh-invariants` | 运行时自检注册表 |
| `dsh-agent` | agent 抽象 |
| `dsh-llm` | LLM 服务 |
| `dsh-llm-deepseek` | DeepSeek 适配器 |
| `dsh-llm-retry` | 重试策略执行器 |
| `dsh-plugin-package-inventory-deepseek` | 插件包清单上报 |
| `dsh-sandbox-local` | 沙箱后端 |
| `dsh-scope` | 作用域原语（仅以 `/invariant` 挂载） |
| `dsh-sdk-app` | stdio 启动提供方 |
| `dsh-sandbox-policy` | 权限模式 |
| `dsh-sdk-jsonrpc-server` | **对外 JSON-RPC 接口** |
| `dsh-session-log-deepseek` | 会话日志贡献 |
| `dsh-session-persistence-jsonl` | JSONL 落盘 |
| `dsh-session-projection` | 投影注册表 |
| `dsh-session-title` | 会话标题 |
| `dsh-subprocess-local` | 子进程 |
| `dsh-system-prompt` | 系统提示词 |
| `dsh-terminal` | PTY 注册表 |
| `dsh-terminal-bash` | shell 后端 |
| `dsh-tool-bash-persistent` | bash 工具（POSIX） |
| `dsh-tool-pwsh-persistent` | pwsh 工具（Windows） |
| `dsh-tools` | 工具注册表 |
| `dsh-session` | 会话模型 |
| peer: `@deepseek-ai/cordis` | 框架内核 |

对比：`dsh-headless` 只依赖 5 个（`commander`、`dsh-brand`、`dsh-cmdline`、`dsh-code-runtime-worker-thread`、`dsh-util-values`、`schemastery`），因为它**靠 profile 叠加获得 `dsh-base`**，自己不携带核心。`dsh-base` 则依赖约 86 个。

### 6.2 启动一个 SDK profile

```powershell
# 终端 1：启动 SDK server（占用 stdio，不要在此终端输入）
$env:DSH_HOME = "D:\Incubator\temp\dsh-minimal\dsh-home"
$env:DEEPSEEK_API_KEY = "sk-..."
dsh --profile sdk-minimal
```

此时进程会等待 stdin 上的按换行分隔的 JSON-RPC 帧。**stdout 专用于 JSON-RPC**（`dsh-sdk-app` README 原文），任何向 stdout 写普通文本的插件都会破坏分帧。

`shutdown` 协议方法、SIGINT、SIGTERM 各有独立路径（README 原文）；stdin EOF 绑定到有界成功关闭。

> ⚠️ 未经运行验证：本报告**未实际启动 `--profile sdk-minimal` 并发送协议帧**。上面的启动命令与"等待帧"的行为描述来自 `dsh-sdk-app` 的 README 与源码（`exitOnStdinEnd` / `ctx.provide(SDK_APP_STARTUP_SERVICE, ...)`），非本机实测。可以实测的是 `--help` 路径：README 明确该路径**不占用 stdin/stdout**。

### 6.3 SDK 协议（**本机 `.d.ts` 逐行核实**）

上一节的骨架代码曾标注为推断。现已在本机读到权威定义：

```
C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\dsh-sdk-protocol\lib\types\
├── index.d.ts      (913 B)   —— 模块入口，re-export 下列全部符号
├── types.d.ts    (5,037 B)   —— 三个请求/结果对 + 四个通知载荷
└── transport.d.ts (4,319 B)  —— JsonRpcLineTransport / JsonRpcTransportPeer
```

**关键限制（`dsh-sdk-app` README 原文）**：

> "**profile 可以省略 SDK server**：TypeScript client 选择的自定义 profile 必须保留本组合包或另一个 `dsh-sdk-jsonrpc-server` 配置项；没有 peer 响应时，client 初始化会失败。"

即：**客户端不是直接 import DSH，而是 spawn `dsh --profile <n>` 子进程，然后走 JSON-RPC。**

#### 6.3.1 传输层（`transport.d.ts` 原文）

> "Newline-delimited JSON-RPC 2.0 over byte streams. Frames with `id` and `method` are requests, `id` alone is a response, and `method` alone is a notification. Malformed lines are ignored; handler failures become error frames."

| 项 | 值（原文） |
|---|---|
| 帧格式 | 每行一个 JSON-RPC 2.0 帧（newline-delimited） |
| 请求帧 | 同时含 `id` + `method` |
| 响应帧 | 只含 `id` |
| 通知帧 | 只含 `method` |
| 畸形行 | **被忽略**（不报错） |
| 缺 handler 的请求 | 返回 `-32601` |
| handler 抛错 | 返回 `-32603`（消息为错误 message） |
| 无 handler 的通知 | 静默丢弃 |

`JsonRpcLineTransport(input: Readable, output: Writable)` 的公开方法：`start()`（幂等）、`close()`（分离监听并 reject 挂起请求，**不销毁流**）、`onRequest(handler)`、`onNotification(handler)`、`request(method, params, signal?)`、`notify(method, params?)`、`flush()`（等待已排队的写回调，空屏障不写字节）。

#### 6.3.2 请求/结果（`types.d.ts` 原文，**共 3 个方法**）

```ts
export interface HarnessSdkRequestMap {
    'initialize': { params: InitializeParams; result: InitializeResult };
    'session/prompt': { params: SessionPromptParams; result: SessionPromptResult };
    'shutdown': { params: undefined; result: Record<string, never> };
}
```

| 方法 | params | result |
|---|---|---|
| `initialize` | `{ cwd: string; provider: string; model: string; reasoningEffort?: ReasoningEffortId; maxTokens?: number }` | `{ serverInfo: { name: string; version: string } }` |
| `session/prompt` | `{ sessionId: string; contentBlocks: SdkPromptContentBlock[] }` | `{ messageId: string }` |
| `shutdown` | 无 | 空对象 |

**逐字要点**：

- `InitializeParams.cwd` —— "Working directory recorded on every SDK-created session's header."
- `InitializeParams.provider` / `.model` —— "Provider route every SDK-created agent runs on." / "Model name every SDK-created agent runs on（**the server may mount a fallback adapter**）"
- `reasoningEffort` / `maxTokens` —— 均可选；`maxTokens` 是"被 SDK 创建的 agent **及其进程内后代**继承的输出上限"
- `InitializeResult.serverInfo.name` —— **线上稳定标识为 `deepseek-harness-sdk-runtime`**（`types.d.ts` 模块注释原文）
- `SessionPromptParams.sessionId` —— "The SDK-side session id; **an unknown id lazily creates the agent+session pair.**"
- `SessionPromptParams.contentBlocks` —— 类型 `SdkPromptContentBlock = ContentBlock | SdkEncodedImageBlock`；其中 `SdkEncodedImageBlock = { type: 'image'; data: string; mimeType: 'image/png'|'image/jpeg'|'image/webp'|'image/gif' }`，注释说明"Canonical base64-encoded raster bytes"、"verified during admission"
- `SessionPromptResult.messageId` —— "Durable enqueue receipt for one prompt."（**只是入队回执，不是完成信号**）

#### 6.3.3 通知（`types.d.ts` 原文，**共 4 种，服务器→客户端**）

```ts
export interface HarnessSdkNotificationMap {
    'session.event':    SessionEventNotification;
    'session.status':   SessionStatusNotification;
    'subagent.started': SubagentStartedNotification;
    'subagent.finished':SubagentFinishedNotification;
}
```

| 通知方法 | 载荷 | 说明 |
|---|---|---|
| `session.event` | `{ sessionId, event: SessionEvent }` | 一条会话日志事件，**记录时即流式推送**；"every session in the runtime, not only SDK-created ones" |
| `session.status` | `{ sessionId, status: 'idle' \| 'running' }` | 整体 agent 生命周期状态 |
| `subagent.started` | `{ parentSessionId, childSessionId }` | 运行期内创建了子会话 |
| `subagent.finished` | `{ provider, agentId, parentSessionId, childSessionId, status: 'ok'\|'error', stopReason, lastAssistantMessage? }` | **仅进程内** subagent 会报告（远程运行不报告） |

**这解释了"怎么知道一轮跑完了"**：`session/prompt` 只给入队回执；真正的完成判定要靠 `session.status` 从 `running` 回到 `idle`，加上 `session.event` 里 `turn/end` 的 `reason.kind`。

#### 6.3.4 Python SDK（**官方文档原文，PyPI 实测取得**）

官方确实提供了 Python SDK，且**自带运行时、不需要系统 Node**：

```sh
python -m pip install deepseek-harness-sdk
```

PyPI 元数据实测（`https://pypi.org/pypi/deepseek-harness-sdk/json`）：

| 字段 | 值 |
|---|---|
| 最新版本 | `0.1.5rc1` |
| `requires_python` | `>=3.10` |
| `requires_dist` | `deepseek-harness-runtime-bin==0.1.5rc1`, `pydantic<3,>=2.12` |
| `license_expression` | MIT |
| 描述 | "Python subprocess SDK for driving DeepSeek Harness over **newline-delimited JSON-RPC on stdio**" |

**描述原文的关键句（全部与 §6.3.1–6.3.3 的 `.d.ts` 相互印证）**：

> "Install `deepseek-harness-sdk`; it installs the exact same-version `deepseek-harness-runtime-bin` wheel for the current platform."
> "The Python SDK has no separate application entrypoint. It launches the bundled `dsh` CLI with `--profile sdk`."
> "**Every launch requires an explicit Harness home.** Pass `dsh_home` or provide a non-empty `DSH_HOME` in the child environment. **The SDK deliberately never discovers `~/.dsh`.**"
> "**Running the SDK does not require system Node.js.**"

**官方最小示例（原文逐字）**：

```python
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    dsh_home="/absolute/path/to/isolated-dsh-home",
    cwd="/absolute/path/to/workspace",
    provider="deepseek-official",
    model="deepseek-v4-flash",
    reasoning_effort="max",
    max_tokens=49_152,
) as harness:
    result = harness.run("Say hi.", session_id="example-001")

print(result.final_response)
```

`RunResult` 字段（原文）：`RunResult(session_id, final_response, finish_reason, events, notifications)`

| 字段 | 含义（原文） |
|---|---|
| `final_response` | "the last committed root-session assistant text in the interval" |
| `finish_reason` | "the `kind` of the last root-session `turn/end`, such as `completed`, `max-tokens`, or `error`"；**无轮次结束时为 `None`** |
| `events` | **仅根会话**事件（"descendant output cannot replace the root response"） |
| `notifications` | 根会话 + 已知后代，按线上顺序 |

其它原文要点：

- `DeepSeekHarness` **惰性启动**，并复用运行时直到 `close()` 或 `with` 退出；
- `initialize_timeout_seconds` 默认 **30 秒**（仅握手）；普通轮次**默认无界**，除非设 `request_timeout_seconds`；
- `cwd` 是 **agent 工作区**，`runtime_cwd` 独立选择**子进程工作目录**，两者都会被绝对化；
- `base_url` / `api_key` 显式覆盖子环境里的 `DEEPSEEK_BASE_URL` / `DEEPSEEK_API_KEY`；
- **`patches` 参数**（按顺序转发到 profile 层与 home 层之后，与 `--patch` 语义一致）：

```python
with DeepSeekHarness(
    dsh_home="/absolute/path/to/isolated-dsh-home",
    profile="sdk",
    patches=("/absolute/path/to/first.patch.yml", "/absolute/path/to/last.patch.yml"),
) as harness:
    result = harness.run("Make the requested code change.")
```

- 选 `sdk-minimal` 时："the ordinary `model` argument is the sole runtime model selection, including for model ids outside the adapter's advisory catalog"；
- `profile` 可换，但"**that composition must retain `@deepseek-ai/dsh-sdk-app` or another `@deepseek-ai/dsh-sdk-jsonrpc-server` row**。Misconfiguration fails during CLI boot or SDK initialization; **there is no complete-config fallback.**"
- 用 `dsh plugin` 装外部 bundle（**SDK 场景下只有管理外部包时才需要 pnpm**）：

```sh
export DSH_HOME=/absolute/path/to/isolated-dsh-home
dsh --profile sdk --dump-default-config >/dev/null
dsh plugin --profile sdk add file:/absolute/path/to/my-plugin-bundle
```

- 一个 `turn/end` 若缺字符串型 `data.reason.kind`，会**违反协议并抛 `SdkProtocolError`**。

#### 6.3.5 手写 Node.js 客户端（**基于已核实协议，非推断**）

> 下面各方法与载荷字段**全部来自本机 `.d.ts` 原文**。仅"用 `session/event` 的 `turn/end` 判定完成"这一具体判据属实现建议 —— 其判据本身的可靠性由 §6.3.4 的官方 `finish_reason` 定义背书。

```js
// minimal-sdk-client.mjs —— 方法与字段均核实自 dsh-sdk-protocol 的 .d.ts
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const child = spawn("dsh", ["--profile", "sdk-minimal"], {
  env: {
    ...process.env,
    DSH_HOME: "D:/Incubator/temp/dsh-minimal/dsh-home",  // 必须显式给出
    DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY,      // 不要硬编码
    DSH_TELEMETRY_DISABLED: "1",
  },
  stdio: ["pipe", "pipe", "inherit"],   // stdout 必须留给协议帧；stderr 给 inherit 看错误
});

let nextId = 1;
const pending = new Map();

const rl = createInterface({ input: child.stdout });
rl.on("line", (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }   // 畸形行按协议忽略
  if (msg.id !== undefined && msg.method === undefined) {
    const p = pending.get(msg.id);                     // 响应帧
    if (p) { pending.delete(msg.id); msg.error ? p.reject(msg.error) : p.resolve(msg.result); }
    return;
  }
  // 通知帧（method 有、id 无）
  switch (msg.method) {
    case "session/status":
      if (msg.params.status === "idle") console.log("[idle]", msg.params.sessionId);
      break;
    case "session/event": {
      const ev = msg.params.event;
      if (ev?.type === "turn/end") console.log("[turn/end]", JSON.stringify(ev.data?.reason));
      break;
    }
    case "subagent.started":
    case "subagent.finished":
      console.log("[" + msg.method + "]", JSON.stringify(msg.params));
      break;
  }
});

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
}

// ① 握手（cwd / provider / model 必填）
const init = await request("initialize", {
  cwd: process.cwd(),
  provider: "deepseek-official",
  model: "deepseek-v4-flash",
  reasoningEffort: "max",        // 可选
  maxTokens: 49_152,             // 可选
});
console.log("server:", init.serverInfo);   // name === "deepseek-harness-sdk-runtime"

// ② 一轮对话：未知 sessionId 会惰性创建 agent+session 对
const { messageId } = await request("session/prompt", {
  sessionId: "example-001",
  contentBlocks: [{ type: "text", text: "Say hi." }],   // ContentBlock 之一
});
console.log("queued as", messageId);        // 仅入队回执

// ③ 等 session/status 回到 "idle"，再读该区间内的 assistant 文本
//    （官方 Python SDK 把这一步封装成 harness.run() → RunResult.final_response）

// ④ 关闭：发 shutdown，或直接 child.stdin.end()（EOF 触发有界成功关闭）
await request("shutdown", undefined);
child.stdin.end();
```

**更省事的替代方案**：如果只是想要"程序里用 DSH"，**用 Headless profile 当"子进程即函数"**，完全不必碰协议：

```python
# Python：官方 SDK（推荐，自带运行时，不需要系统 Node）
from deepseek_harness import DeepSeekHarness
with DeepSeekHarness(
    dsh_home="/absolute/path/to/isolated-dsh-home",   # 必须显式；SDK 不会去猜 ~/.dsh
    provider="deepseek-official",
    model="deepseek-v4-flash",
) as harness:
    print(harness.run("统计 src 下的 TS 文件数", session_id="count-001").final_response)
```

```js
// Node：直接用 CLI，不实现协议
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(execFile);

const { stdout } = await run("dsh", ["--profile", "headless", "统计 src 下的 TS 文件数"], {
  env: { ...process.env, DSH_HOME: "D:/tmp/dsh-home", DSH_TELEMETRY_DISABLED: "1" },
  maxBuffer: 10 * 1024 * 1024,
});
console.log(stdout);   // 最终答案
```

这利用了 Headless 的"退出码即结果"契约（`0` 完成 / `1` 失败），**不需要写任何协议代码**。

#### 6.3.6 三条路径怎么选

| 需求 | 选 | 理由 |
|---|---|---|
| 程序里跑一次性任务 | **Headless + 子进程** | 零协议代码，退出码即结果 |
| 程序里要多轮对话 / 流式事件 / 子智能体可见性 | **Python SDK** | 官方封装，`RunResult` 已处理完成判定 |
| 要在 Node/TS 里深度集成，或要自己控制帧 | **自己实现 JSON-RPC** | 协议只有 3 个方法 + 4 个通知，成本可控 |
| 要嵌进已有 DSH 部署切换智能体 | **preset（§7.6）** | 不属于 SDK 路径 |

---

## 7. 逐步"加装能力"

从 §2.2 的 18 行出发，每一步只加"一行（或几行）插件 + 一段配置"。所有包名均在本机 `$DSH_HOME\profiles\node_modules\@deepseek-ai\` 中实际存在。

### 7.1 大表：能力 → 包 → 配置

> **权威核对源**：master 的生成式文档 `docs/tool-catalog.zh.md` 记录了**全部 69 个工具条目 / 30 个工具包 / 64 个唯一模型可见工具名**（`bash`、`pwsh`、`interrupt_agent`、`list_agents`、`send_message` 这 5 个名字被两个包各记一次，所以朴素计数会偏大）。下表任何一行都能在该文档里查到官方 schema。配置字段则查 `docs/config-catalog.zh.md`。
> 本表按"加装顺序"组织，是从 §2.2 的 18 行最小集出发的增量清单。

| 能力 | 要加的包（`@deepseek-ai/` 前缀省略） | 行 id 建议 | 关键配置片段 | 备注 |
|---|---|---|---|---|
| **① 文件读写（基础）** | `dsh-fs-sandbox` → `dsh-tool-fs` | `fs-sandbox`, `tool-fs` | `- id: tool-fs`<br>`  name: '@deepseek-ai/dsh-tool-fs'` | `tool-fs` 硬注入 `tools`/`fs`/`systemPrompt`。**必须用沙箱化提供方**，再叠 `dsh-fs-local` 会重复注册 `ctx.fs` 并加载失败 |
| **①b 文件读写（无沙箱，危险）** | `dsh-fs-local` → `dsh-tool-fs` | `fs-local`, `tool-fs` | 同上，但换成 `dsh-fs-local` | 与沙箱化提供方**二选一** |
| **② 文件搜索 / glob** | `dsh-tool-fs-search` | `tool-fs-search` | `- id: tool-fs-search`<br>`  name: '@deepseek-ai/dsh-tool-fs-search'`<br>`  config: { sampleOverCapGlobResults: false }` | 需 `fs` 服务 |
| **③ 文本替换编辑器** | `dsh-tool-str-replace-editor` | `tool-str-replace-editor` | `config: { maxOutputChars: 16000 }` | 基础默认**不含**它；文件编辑默认走 `read`/`write`/`edit` |
| **④ 非持久 shell（POSIX）** | `dsh-shell-env`, `dsh-bash-local`, `dsh-tool-bash` | `shell-env`, `bash-local`, `tool-bash` | `disabled: !!js process.platform === 'win32'` | `tool-bash` 注入 `tools`/`shell`/`systemPrompt`/`shellEnv` |
| **④b 非持久 shell（Windows）** | `dsh-shell-env`, `dsh-pwsh-local`, `dsh-tool-pwsh` | `shell-env`, `pwsh-local`, `tool-pwsh` | `disabled: !!js process.platform !== 'win32'` | **实测可用**（§7.2） |
| **⑤ 沙箱化 shell** | `dsh-bash-sandbox` / `dsh-pwsh-sandbox` | `bash-sandbox`, `pwsh-sandbox` | `config: { timeoutMs: 60000 }` | `dsh-base` 采用这个而非 `*-local` |
| **⑥ 持久 shell（推荐）** | `dsh-terminal`, `dsh-terminal-bash`, `dsh-tool-pwsh-persistent` | `pty`, `terminal-pwsh`, `persistent-pwsh` | `shellDialect: pwsh`<br>`timeoutMs: 300000` | **`dsh-terminal-bash` 硬注入 `sandboxPolicy` + `sessionProjections` + `subprocess`**；官方 `minimal` preset 用这一套 |
| **⑦ 后台作业 / 长任务** | `dsh-jobs-local`, `dsh-tool-jobs` | `jobs`, `tool-jobs` | `- id: tool-jobs` | 官方最小集含 `dsh-jobs-local`，不含 `dsh-tool-jobs` |
| **⑧ Web 搜索** | `dsh-web`, `dsh-web-search-deepseek`, `dsh-tool-web` | `web`, `web-search-deepseek`, `tool-web` | `searchProvider: deepseek-official`<br>`apiKeyEnv: DEEPSEEK_API_KEY`<br>`searchTimeoutMs: 60000` | 搜索复用同一个 `DEEPSEEK_API_KEY` |
| **⑨ HTTP(S) 抓取** | `dsh-web-fetch-http`, `dsh-tool-web` | `web-fetch-http`, `tool-web` | `config: { fetch: true }` | 匿名 fetch 只接受公网目的地址并逐跳校验 |
| **⑩ 子智能体（派生）** | `dsh-subagent`, `dsh-subagent-spawn-in-process`, `dsh-tool-subagent` | `subagent`, `subagent-spawn-in-process`, `tool-subagent` | `provider: spawn`<br>`toolName: subagent`<br>`backgroundMode: continuable` | 需要 `dsh-tool-subagent-control` 才能续聊 |
| **⑪ 子智能体（继承上下文）** | `dsh-subagent-fork-in-process`, `dsh-tool-subagent` | `subagent-fork-in-process`, `tool-subagent-fork` | `provider: fork`<br>`toolName: subagent_fork`<br>`backgroundMode: one-shot` | fork 复用父上下文，利于 KV Cache |
| **⑫ 子智能体控制** | `dsh-tool-subagent-control`, `.../list-agents` | `tool-subagent-control`, `tool-subagent-list-agents` | — | 注册全局 `send_message` 与 `list_agents` |
| **⑬ 技能（Skills）** | `dsh-skill`, `dsh-skill-filesystem`, `dsh-tool-skill` | `skill`, `skill-filesystem`, `tool-skill` | — | 技能从文件系统发现 |
| **⑭ 工作流编排** | `dsh-workflow-worker-thread`, `dsh-tool-workflow` | `workflow-worker-thread`, `tool-workflow` | `provider: spawn` | 多智能体 fan-out |
| **⑮ Ralph 循环** | `dsh-tool-ralph` | `tool-ralph` | `subagentProvider: spawn`<br>`maxRounds: 64` | 新鲜 agent 迭代 |
| **⑯ 待办清单** | `dsh-tool-todo` | `tool-todo` | `allowParallelInProgress: true` | |
| **⑰ 目标（跨轮持久）** | `dsh-goal`, `dsh-goal-round-driver`, `dsh-tool-goal`, `dsh-command-goal` | `goal`, `goal-round-driver`, `tool-goal`, `command-goal` | — | 四行是一套 |
| **⑱ 计划模式** | `dsh-plan-mode` | `plan-mode` | `config: { section: \| ... }` | 注入 plan-mode 提示词段 |
| **⑲ 询问用户** | `dsh-tool-ask-user`, `dsh-user-questions` | `tool-ask-user`, `user-questions` | — | |
| **⑳ MCP 客户端** | `dsh-mcp-client` | `mcp-client` | — | 接 MCP server |
| **㉑ 上下文压缩** | `dsh-compaction-basic`, `dsh-command-compact` | `compaction-basic`, `command-compact` | — | 极简集**没有**它 |
| **㉒ 超大工具结果裁剪** | `dsh-compaction-tool-result-pruner` | `tool-result-pruner` | `thresholdChars: 8192`<br>`headChars: 4096`<br>`tailChars: 1024` | |
| **㉓ Token 计量** | `dsh-token-meter` | `token-meter` | — | |
| **㉔ 结构化输出 | `dsh-tool-present` | `tool-present` | — | 交付物声明 |
| **㉕ 用户审批** | `dsh-user-approval` | `approval` | `policy: ask` | **安全加固必加**（§9.4） |
| **㉖ 权限预设** | `dsh-permission-presets` | `permission` | 见 §3.4 三档 | |
| **㉗ 运行时自检** | `dsh-invariants` + `*/invariant` | `invariants`, `*-invariant` | — | 官方最小集含 5 行 |
| **㉘ LLM 重试** | `dsh-llm-retry` | `llm-retry` | — | 官方最小集含它 |
| **㉙ 工作区指令（AGENTS.md）** | `dsh-agent-instructions` | `agent-instructions` | `maxBytes: 65536` | 读仓库级指令文件 |
| **㉚ 时间上下文** | `dsh-time-context` | `time-context` | — | 给模型注入当前时间 |
| **㉛ 沙箱策略** | `dsh-sandbox-local`, `dsh-sandbox-policy` | `sandbox`, `sandbox-policy` | `mode: workspace-write`<br>`workspaceRoot: !!js process.cwd()` | |
| **㉜ 审批策略（webhook）** | `dsh-webhook`, `dsh-webhook-github` | `webhook`, `webhook-github` | — | |
| **㉝ 会话搜索（SQLite）** | `dsh-session-query-sqlite` | `session-query-sqlite` | `path: ':memory:'`<br>`openAt: never` | 默认挂载但 `openAt: never`（搜索禁用） |
| **㉞ 会话检查点** | `dsh-session-checkpoint-policy` | `session-checkpoint-policy` | — | 每次模型请求前落检查点 |
| **㉟ 大对象溢出落盘** | `dsh-spill-local`, `dsh-spill-policy` | `spill-local`, `spill-policy` | `maxInlineBytes: 50000` | |
| **㊱ 工具调用超时策略** | `dsh-tool-call-timeout-policy` | `timeout-policy` | — | |
| **㊲ 重复工具调用提醒** | `dsh-repeat-tool-reminder` | `repeat-tool-reminder` | `thresholds: [3, 5, 8]`<br>`argumentsPreviewChars: 500` | |
| **㊳ 会话标题（模型生成）** | `dsh-session-title-first-prompt-llm` | `session-title-llm` | `targetWords: 5`<br>`maxOutputTokens: 64` | 会额外发一次模型请求 |
| **㊴ 凭据托管** | `dsh-credentials-local` | `credentials` | — | 读 `$DSH_HOME/.credentials.yaml` |
| **㊵ 用户设置文档** | `dsh-settings-file` | `settings` | — | 读 `$DSH_HOME/settings.yaml`，热重载 |

### 7.2 加装示例：给最小集加上"文件读写"

从 §5.5 的 18 行出发，**加 2 行**得到文件工具：

```yaml
    # 追加到 cordis.patch.yml 的同一 insert 列表
    - id: fs-sandbox
      name: '@deepseek-ai/dsh-fs-sandbox'
    - id: tool-fs
      name: '@deepseek-ai/dsh-tool-fs'
```

`tool-fs` 的硬注入是 `["tools", "fs", "systemPrompt"]`（从其 `lib/index.js` 读出的 `const inject`），三者此时都已存在，因此**只需这 2 行**。

> ⚠️ 推断（未经运行验证）：本报告**未单独验证**这 2 行的组合（未跑该变体）。但 `fs-sandbox` 提供 `fs` 服务、`tool-fs` 消费它，且 `dsh-base` 中正是这样配对，因此推断成立。**若报"pending (waiting for service: fs)"，说明 `fs-sandbox` 未激活。**

### 7.3 加装示例：换掉非持久 shell 为持久 shell

**实测可行**（§5.4 第 4 轮）：把

```yaml
    - id: shell-env
      name: '@deepseek-ai/dsh-shell-env'
    - id: pwsh-local
      name: '@deepseek-ai/dsh-pwsh-local'
    - id: tool-pwsh
      name: '@deepseek-ai/dsh-tool-pwsh'
```

换成

```yaml
    - id: pty
      name: '@deepseek-ai/dsh-terminal'
    - id: terminal-pwsh
      name: '@deepseek-ai/dsh-terminal-bash'
      config:
        shellDialect: pwsh
        timeoutMs: 300000
    - id: persistent-pwsh
      name: '@deepseek-ai/dsh-tool-pwsh-persistent'
      config:
        timeoutMs: 300000
```

**同时必须确保 `sandbox-policy` 与 `session-projection` 已挂载**，因为 `dsh-terminal-bash` 的 `inject` 是：

```js
const inject = [
	"terminals",
	"sandboxPolicy",
	"sessionProjections",
	"subprocess"
];
```

（从 `dsh-terminal-bash/lib/index.js` 原文读出）。这是**实测踩过的坑**——少一个就 `pending`。

### 7.4 加装示例：加 Web 访问（3 行 + 2 段 config）

```yaml
    - id: web
      name: '@deepseek-ai/dsh-web'
      config:
        searchProvider: deepseek-official
        fetchProvider: http
    - id: web-search-deepseek
      name: '@deepseek-ai/dsh-web-search-deepseek'
      config:
        apiKeyEnv: DEEPSEEK_API_KEY
    - id: web-fetch-http
      name: '@deepseek-ai/dsh-web-fetch-http'
    - id: tool-web
      name: '@deepseek-ai/dsh-tool-web'
      config:
        fetch: true
        searchTimeoutMs: 60000
```

（4 行；`dsh-base` 原文即如此，`searchTimeoutMs: 60000` 是因其为一次带服务端检索的完整辅助模型请求。）

### 7.5 加装示例：加子智能体（4 行）

```yaml
    - id: subagent
      name: '@deepseek-ai/dsh-subagent'
    - id: subagent-spawn-in-process
      name: '@deepseek-ai/dsh-subagent-spawn-in-process'
      config:
        providerName: spawn
    - id: tool-subagent
      name: '@deepseek-ai/dsh-tool-subagent'
      config:
        provider: spawn
        toolName: subagent
        backgroundMode: continuable
    - id: tool-subagent-control
      name: '@deepseek-ai/dsh-tool-subagent-control'
```

### 7.6 加装示例：给智能体加"技能"（preset 层，不是 bundle 层）

技能属于 **preset 层**。内置 `cordis/` preset 的做法是在 preset 目录里放 `skills/`：

```
presets/cordis/
├── preset.yml
├── agent.cordis.yml
└── skills/
    ├── cordis-plugin-development/SKILL.md       (20,923 B)
    └── editing-cordis-compositions/SKILL.md     (14,413 B)
```

即 **preset 可以内嵌 skill**，这是"给智能体加技能"的官方机制（`dsh-skill-filesystem` 负责从文件系统发现）。

### 7.7 用户自定义 preset 的真实范例

本机 `C:\Users\ysc20\.dsh\.agent-presets\math-research\` 是一个**真实跑得起来的自定义智能体装配**：

| 文件 | 大小 | 作用 |
|---|---|---|
| `preset.yml` | 727 B | preset 元数据（`name` / `description`） |
| `agent.cordis.yml` | 31,428 B | 完整 agent 插件装配清单 |
| `danus-console.mjs` | 47,011 B | 自定义工具脚本 |
| `paper.mjs` | 61,309 B | 自定义工具脚本 |
| `ocr.mjs` | 13,734 B | 自定义工具脚本 |
| `global-deadline.mjs` | 15,910 B | 全局时限控制 |
| `mo.mjs` | 12,528 B | 自定义工具脚本 |
| `danus-core.mjs` | 6,482 B | 核心逻辑 |
| `danus-prompt.mjs` | 5,503 B | 提示词 |

其 `agent.cordis.yml` 中引用的插件（去重计数，**实测统计**）：

```
4× dsh-tool-subagent        1× dsh-agent-instructions   1× dsh-tool-web
1× dsh-tool-todo            1× dsh-tool-subagent-control/list-agents
1× dsh-tool-subagent-control 1× dsh-tool-skill            1× dsh-tool-ralph
1× dsh-tool-pwsh            1× dsh-tool-present          1× dsh-tool-jobs
1× dsh-tool-workflow        1× dsh-tool-goal             1× dsh-tool-fs
1× dsh-tool-bash            1× dsh-tool-ask-user         1× dsh-skill-filesystem
1× dsh-plan-mode            1× dsh-persona               1× dsh-compaction-tool-result-pruner
1× dsh-compaction-basic     1× dsh-command-goal          1× dsh-command-compact
1× dsh-tool-fs-search       1× dsh-workflow-worker-thread
```

**这证明**：用户可以在 `$DSH_HOME\.agent-presets\<name>\` 下用**同一套 cordis patch 语法**组装出带自定义工具（`.mjs`）的专属智能体，**与内置 preset 完全同构**。

其文件头注释还记录了跨版本适配的**真实经验**（原文摘录，对最小化工作极有价值）：

> * `dsh-persona` takes `prefix` (required) + `suffix`; the rc.7 `text` field no longer exists and fails config validation.
> * Every local plugin wraps `tools.register` / `systemPrompt.section` in `ctx.effect(...)`: both return a disposer on 0.1.5, and an unregistered one leaks the registration and throws on a remount.
> * A service row here MUST sit inside a group carrying an `isolate` realm. Without one it publishes into the root realm, where it is process-global.

---

## 8. 验证与调试

### 8.1 怎么确认 agent 真的在跑

| 手段 | 命令 / 位置 | 看什么 |
|---|---|---|
| **退出码** | `$LASTEXITCODE` | Headless：`0` = 完成；`1` = aborted/error/无轮次 |
| **最终答案** | stdout | Headless 把最终 assistant 消息写 stdout |
| **推理轨迹** | stderr，`dsh: reasoning:` 段 | 实测可见多轮推理增量（见 §8.2） |
| **配置树** | `dsh --profile <n> --dump-config` | 行数与内容——**这是最快确认"哪些插件真的挂载了"的手段** |
| **会话落盘** | `$DSH_HOME\sessions\**\session.v3.jsonl.zstd` | 实测生成了 4 个文件（2,362–15,815 B），证明会话持久化生效 |
| **作业后台化** | `dsh-tool-jobs` + `job_list` | 长任务不阻塞轮次 |

`dsh` **没有 `doctor` / `run` / `exec` 子命令**。实测：`dsh doctor --help`、`dsh run --help` 等全部返回启动器自身的 help。

**在 rc.2 上**，`bin.js` 中真实存在的子命令有两个（源码原文）：

```js
const web = program.command("web").description("boot the web profile (alias of --profile web); ...");
const plugin = program.command("plugin").description("manage a profile's plugins by forwarding the remaining arguments to pnpm in the profile directory");
```

即 rc.2 **只有两个子命令**：`web` 和 `plugin`。其它任何 `dsh xxx` 都会走 `program.error("error: --profile <name> is required")` 或被视为应用参数。

> ⚠️ **仅适用于 `0.1.5-rc.2`**：master 已把 `web` 从真子命令降级为**语法糖**（`dsh web` 被重写成 `dsh --profile web`），并新增裸 profile 名简写与 `--dump-config-schema`。**完整的 rc.2 vs master 子命令/选项对照见 [§11.9](#119-master-cli-相对-rc2-的两个真实变化已实测对照)**。本报告其余各章的 CLI 描述均以**本机实测的 rc.2** 为准。

### 8.2 本机实测的"活着"证据

**证据 1：agent 会推理、会调工具、失败时如实报告（不编造）**

实验：让 mini profile 跑一条 shell 命令（`temp\dsh-minimal\tool-out.txt`）：

```
RUN_EXIT=0  ELAPSED=6.45s
STDOUT:
I could not obtain the tool output — the command never ran, so I have nothing to quote verbatim.

What happened:
- `Write-Output TOOLWORKS-42` → `Error: spawn EPERM`
- Retried the identical command → `Error: spawn EPERM`
- A trivial diagnostic (`echo ok`) → `Error: spawn EPERM`
...
Expected output had it run, which I am **not** claiming to have seen: `TOOLWORKS-42`.

STDERR:
dsh: reasoning:
The tool call failed with "Error: spawn EPERM" — this is an error spawning the process. Should I retry? ...
dsh: reasoning:
The tool is failing with spawn EPERM — cannot run commands. I should report this honestly rather than fabricate output.
```

**这同时验证了 4 件事**：① agent loop 在跑多轮（有多次工具调用与推理增量）；② 工具真的被注册并被模型看见（否则不会调用）；③ 错误从工具正确回传到模型；④ 模型没有幻觉——**这是评估"agent 是否真的接通"的高质量信号**。

**证据 2：沙箱拦截真实生效（安全关键）**

实验：让默认 `workspace-write` 模式的 headless profile 向工作区**外**写文件（`temp\dsh-minimal\specA-out.txt`）：

```powershell
$target = "C:\Windows\Temp\dsh-escape-test.txt"
dsh --profile headless "用 pwsh 工具把文本 PWNED 写入 $target，报告是否成功"
```

实测结果：

```
EXIT=0
STDOUT（agent 报告）:
  Error: SetNamedSecurityInfoW failed (Win32 5): grantWrite(D:\Incubator\temp\dsh-minimal)
  ... Approval policy is `ask`, but the operation failed closed at the sandbox layer
      without reaching an approval prompt, so there was nothing to approve.
--- TARGET FILE EXISTS? --- False
```

**越权写入被阻止**（fail closed）。注意失败发生在**沙箱自身的 ACL 设置步骤**（`SetNamedSecurityInfoW` / Win32 5 = `ERROR_ACCESS_DENIED`），而不是命令执行之后——即"先设围栏，再执行"。

### 8.3 本机遭遇的真实报错与排查

| # | 报错（原文） | 根因 | 排查/修法 |
|---|---|---|---|
| 1 | `Error: EPERM: operation not permitted, open 'C:\Users\ysc20\.dsh\profiles\web\cordis.yml'` | `$DSH_HOME` 在只读/不可写位置；`prepareProfile()` 必然重写 `cordis.yml` | 把 `$DSH_HOME` 指到可写目录 |
| 2 | `dsh: plugin tree failed to load: ... 3 entries did not activate`<br>`@deepseek-ai/dsh-agent-loop: pending (waiting for service: sessionProjections)` | 缺少 `dsh-session-projection` | 补 `- id: session-projection` |
| 3 | 同上，`pending (waiting for service: subprocess)` | 缺少 `dsh-subprocess-local` | 补 `- id: subprocess` |
| 4 | 同上，`pending (waiting for service: agentDefaultModel)` | 缺少 `dsh-agent-default-model` | 补 `- id: agent-default-model` + config |
| 5 | `pending (waiting for service: sandboxPolicy)` on `dsh-terminal-bash` | 持久 shell 硬注入 `sandboxPolicy` | 补 `dsh-sandbox-local` + `dsh-sandbox-policy` |
| 6 | `invalid plugin, expect function or object with an "apply" method, received object` on `@deepseek-ai/dsh-scope` | `dsh-scope` 是**工具库不是插件** | 删掉该行；它只以 `/invariant` 子路径挂载 |
| 7 | `service "shell" has been registered at <ShellExecutor>` | 同时挂了 `dsh-shell`（抽象基类）与 `dsh-pwsh-local`（具体后端，自己 provide `shell`） | 删掉 `dsh-shell` 行 |
| 8 | `Error: spawn EPERM`（工具层） | 非持久 pwsh 工具走"管道 stdio 子进程"路径，被进程沙箱拒绝 | 改用**持久 shell 栈**（`dsh-tool-pwsh-persistent` + PTY），或放宽进程策略 |
| 9 | `TypeError: Cannot read properties of undefined (reading 'destroy')` at `WindowsPtyAgent._failPtyConnection` | `node-pty` 的 Windows conpty 连接失败 | 同 #8；node-pty 在受限环境下不可用 |
| 10 | `SetNamedSecurityInfoW failed (Win32 5): grantWrite(<workspace>)` | Windows ACL 沙箱无法对目标目录授予写权限 | 换到权限/属主正常的目录，或改用 `read-only` 模式 |
| 11 | `error: required option '--profile <name>' not specified` | `dsh plugin` 未给 `--profile` | 补上 |
| 12 | `[ERR_PNPM_PACKAGE_JSON_EXISTS] package.json already exists` | `dsh plugin --profile <n> init` 把 `init` 原样转发给 pnpm，而 pnpm 无此子命令 | 直接用 `dsh --profile <n>` 首次启动即自动初始化 |

### 8.4 调试三件套（推荐工作流）

```powershell
# ① 先看会挂载什么，不启动
dsh --profile <n> --dump-config | Select-String '^- id:'

# ② 只看 bundle 层（排除用户层干扰）
dsh --profile <n> --dump-default-config

# ③ 最小化复现：用 --patch 叠一层临时覆盖，不动任何 profile 文件
dsh --profile <n> --patch .\probe.yml "任务" 2>&1 | Tee-Object probe.log
```

**核心调试心法**：DSH 的 fail-loud 报错**已经把答案写在里面了**。看到 `pending (waiting for service: X)`，就去补一个提供 `X` 的插件行——服务的提供者名字通常就是插件名去掉 `dsh-` 前缀（`sessionProjections` ← `dsh-session-projection`，`subprocess` ← `dsh-subprocess-local`，`agentDefaultModel` ← `dsh-agent-default-model`）。**不要靠猜，靠报错。**

---

## 9. 最小可用的边界与风险

### 9.1 没有沙箱 / 没有审批时的危险

**这是本报告最重要的安全结论。**

| 最小集 | 沙箱 | 审批 | 后果 |
|---|---|---|---|
| 官方 `sdk-minimal`（31 行） | **写死 `danger-full-access`** | **无审批插件** | shell 可改进程能触达的**任何路径** |
| 本报告 `mini`（18 行） | 显式 `danger-full-access` | **无审批插件** | 同上 |
| 官方 `minimal` preset | 继承宿主 profile 的策略 | 继承宿主 profile | 依赖宿主，本身不管 |
| 官方 `headless`（87 行） | `workspace-write`（可用 `DSH_PERMISSION_MODE` 覆盖） | `dsh-user-approval`，policy `ask` | **默认安全** |

`dsh-sdk-minimal` README 自己的警告（原文）：

> "其 danger-full-access 策略允许 shell 修改进程可访问的任何路径，因此**只能配合隔离 workspace 使用**。"

**具体风险清单**：

1. **无审批 prompt**：模型可以自主执行破坏性命令（`Remove-Item -Recurse -Force`、`git push --force`、`npm publish`），无人拦截。
2. **无文件边界**：`danger-full-access` 下可读写用户主目录、SSH 密钥、`.credentials.yaml` 本身。
3. **提示注入放大**：无审批 + 有 Web 访问 = 恶意网页可诱导 agent 执行任意命令。
4. **凭据就在可达范围**：`$DSH_HOME\.credentials.yaml` 内含明文 `DEEPSEEK_API_KEY`；在 `danger-full-access` 下 agent 可以读它并外发。
5. **无自检**：`mini` 集不含 `dsh-invariants`，运行期不变量违规不会被发现。

### 9.2 上下文窗口

- 默认上下文窗口 **1,000,000 token**（`dsh-llm-deepseek` 的 `defaultContextWindow` 缺省，以及 `dsh-sdk-minimal` patch 第 30 行 `process.env.DSH_CONTEXT_WINDOW ?? 1000000`）。
- 官方目录宣称 `deepseek-flash` / `deepseek-v4-flash` / `deepseek-v4-pro` / `deepseek-v4-flash-vision-exp` 各自上下文窗口均为 **1,000,000 token**（`dsh-llm-deepseek` README）。
- **极简集没有 compaction**：官方 `minimal` preset 文件头注释原文 **"Context compaction is absent."**；`mini`（18 行）也没有。`sdk-minimal`（31 行）同样没有 compaction 行。
- **后果**：长任务最终会撞上上下文上限，且**没有任何自动缓解**。行为将取决于适配器返回的 `CONTEXT_WINDOW_EXCEEDED` 错误与 `dsh-llm-retry` 的策略（`mini` 连 retry 都没有）。

**要加压缩能力，加这几行**：

```yaml
    - id: compaction-basic
      name: '@deepseek-ai/dsh-compaction-basic'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
      config:
        thresholdChars: 8192
        headChars: 4096
        tailChars: 1024
```

### 9.3 成本控制

| 成本来源 | 说明 | 控制手段 |
|---|---|---|
| 主对话 token | 每轮把完整历史 + 全部工具 schema 发给模型 | 减少工具数量（每减少一个工具就少一段 schema）；开启 compaction |
| **工具 schema 是固定成本** | 每个工具的描述与 JSON Schema 每轮都发 | 这是"最小集"最直接的成本收益：18 行 vs 87 行，工具 schema 差一个量级 |
| 会话标题的额外请求 | `dsh-session-title-first-prompt-llm` 会**额外发一次模型请求** | `mini` / `sdk-minimal` 用确定性 fallback title（`dsh-session-title`），**不发请求**；或整行 `disabled: true` |
| Web 搜索 | "一次带服务端检索的完整辅助模型请求" | 不用就 `disabled: true` 整组 web 行 |
| 推理 token | `reasoningEffort` 默认 `high`（`dsh-llm-deepseek`） | `reasoningEffort: off` / `low`，或 `thinking: disabled` |
| 输出上限 | `maxTokens` 默认 256,000 | 调小 |
| 缓存收益 | 固定 persona + 固定工具清单 + 固定模型 → 前缀可复用 | **保持 persona 与工具清单稳定**（KV Cache 复用）；`mini` 用 `includeRuntimeContext: false` 正是为此 |
| 遥测流量 | `session-telemetry-otel` 默认 `FEEDBACK_ONLY`（仅用户反馈时上传） | `$env:DSH_TELEMETRY_DISABLED = "1"`（任意非空值，含 `0`） |

**量化对比（实测）**：

| profile | 插件行 | 不同包 | 工具 schema 数量级（推断） |
|---|---|---|---|
| `mini` | 19 | 18 | 1 个工具 |
| `sdk-minimal` | 31 | 30 | 1 个工具 |
| `headless` | 87 | 86 | ~30 个工具 |

> ⚠️ 推断（未经运行验证）："工具 schema 数量级"是根据各组合中 `tool-*` 行数推断的，未实测 token 数。实际 token 数可用 `dsh-token-meter` 观察。

### 9.4 "最小且安全"的加固配方

**这是把 §2.2/§2.3 的危险最小集变成可交付物的关键。**

从 §5.5 的 18 行出发，追加以下 5 块：

```yaml
    # ── 加固 1：权限模式从 danger-full-access 改为 workspace-write ──
    - id: sandbox-policy
      name: '@deepseek-ai/dsh-sandbox-policy'
      config:
        mode: workspace-write                      # ← 原来是 danger-full-access
        workspaceRoot: !!js process.cwd()

    # ── 加固 2：接入审批（极简集完全缺失这一环）──
    - id: approval
      name: '@deepseek-ai/dsh-user-approval'
      config:
        policy: ask

    # ── 加固 3：权限预设三档（让审批与沙箱可被统一切换）──
    - id: permission
      name: '@deepseek-ai/dsh-permission-presets'
      config:
        presets:
          read-only:
            sandbox: read-only
            approval: ask
          workspace-write:
            sandbox: workspace-write
            approval: ask
          danger-full-access:
            sandbox: danger-full-access
            approval: never

    # ── 加固 4：运行时自检 ──
    - id: invariants
      name: '@deepseek-ai/dsh-invariants'
    - id: session-invariant
      name: '@deepseek-ai/dsh-session/invariant'
    - id: agent-invariant
      name: '@deepseek-ai/dsh-agent/invariant'
    - id: scope-invariant
      name: '@deepseek-ai/dsh-scope/invariant'
    - id: agent-loop-invariant
      name: '@deepseek-ai/dsh-agent-loop/invariant'

    # ── 加固 5：上下文压缩（防止长任务无界增长）──
    - id: compaction-basic
      name: '@deepseek-ai/dsh-compaction-basic'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
      config:
        thresholdChars: 8192
        headChars: 4096
        tailChars: 1024
```

再加 §7.2 的**文件工具**（2 行）与可选的 **`dsh-tool-ask-user`**（让 agent 能向人提问而非猜测）：

```yaml
    - id: fs-sandbox
      name: '@deepseek-ai/dsh-fs-sandbox'
    - id: tool-fs
      name: '@deepseek-ai/dsh-tool-fs'
    - id: tool-ask-user
      name: '@deepseek-ai/dsh-tool-ask-user'
    - id: user-questions
      name: '@deepseek-ai/dsh-user-questions'
```

**加固后总行数：19 + 14 = 33 行**，比官方 `sdk-minimal`（31 行）多 2 行，但**安全性完全不同**：

| | 官方 `sdk-minimal` | 加固后的 `mini-safe` |
|---|---|---|
| 沙箱 | `danger-full-access` | **`workspace-write`** |
| 审批 | ❌ 无 | ✅ `policy: ask` |
| 权限预设 | ❌ 无 | ✅ 三档 |
| 文件工具 | ❌ 只能绕 shell | ✅ `tool-fs` |
| 自检 | ✅ 有 | ✅ 有 |
| 压缩 | ❌ 无 | ✅ 有 |
| 入口 | JSON-RPC（给程序） | **Headless CLI（人可直接用）** |

**最保守的运行方式**：

```powershell
# 只读模式跑，任何写操作都需要人批准
$env:DSH_PERMISSION_MODE = "read-only"
dsh --profile mini-safe --dump-config | Select-String '^- id:'   # 先确认行数
dsh --profile mini-safe "分析当前目录的代码结构，不要修改任何文件"
```

> ⚠️ 推断（未经运行验证）：该加固配方**由已核实的行 id 与配置字段拼装**，但**整份组合未在本机启动验证**。逐条依据：`approval`/`permission`/`sandbox-policy` 字段取自 `dsh-base/cordis.patch.yml` 原文；`invariants` 与 4 个 `/invariant` 取自 `dsh-sdk-minimal/cordis.patch.yml` 原文；compaction 行取自 `dsh-base` 原文。**首次使用务必用 `--dump-config` 与一次真实运行验证。**

### 9.5 其它边界

| 边界 | 说明 |
|---|---|
| **每进程一个任务** | Headless "每次调用只运行一个任务，没有交互式后续" |
| **Headless 必须经 `dsh` 启动器** | README："以其他方式启动 headless profile 会在启动时失败，因为只有启动器能请求进程退出" |
| **patch 是整体替换不是合并** | 覆盖任何行都要**重述所有想保留的字段** |
| **`bundles` 解析有优先级** | 先从 dsh 安装目录解析，再从 profile 的 `node_modules`；因此 `dsh-base` 永远是同一份安装的 |
| **stdout 纯净性** | SDK profile 的 stdout 专用于 JSON-RPC 分帧；插入任何往 stdout 写文本的插件都会破坏协议 |
| **配置文件变化需重启** | 随附 `sdk`/`sdk-minimal` profile 用 `patchReload: startup`；自定义 profile 默认 `live` |
| **开发者预览** | 上游 README：**"THERE WILL BE COMPATIBILITY-BREAKING CHANGES."** 本机 `0.1.5-rc.2` 与 npm `latest=0.1.5-rc.3`、`alpha=0.1.7-alpha.2` 已不同 |
| **`desktop` 名字被保留** | `bin.js` 中有 `rejectElectronProfile()`，`dsh --profile desktop` 一律被拒 |
| **Windows 沙箱按会话隔离临时目录** | `workspace-write` 把写入限制在工作区与 `<temp>\dsh-<hash>`；`read-only` 不授予任何临时目录写权限 |
| **fs 提供方唯一性** | 在沙箱化 fs 提供方之上再加 `dsh-fs-local` 会重复注册 `ctx.fs` 并**加载失败** |

---

## 10. 附录

### 10.1 完整命令清单（本报告实际执行过）

**启动器与版本**

```powershell
dsh --version                                   # → 0.1.5-rc.2
dsh --help                                      # → 启动器 help（含 Examples）
dsh plugin --help                               # → error: required option '--profile <name>' not specified
```

**profile 初始化与组合检查**

```powershell
$env:DSH_HOME = "D:\Incubator\temp\dsh-minimal\dsh-home"
$env:DSH_TELEMETRY_DISABLED = "1"

dsh --profile headless --help                   # → headless 应用自己的 help（EXIT=0）
dsh plugin --profile mini init                  # → 初始化 profile 目录，pnpm 随后报错退出 1
dsh --profile mini --dump-config                # → 19 个 `- id:`（18 插件行 + 1 个 config 内嵌 id）
dsh --profile sdk-minimal --dump-default-config # → 31 行配置树
dsh --profile headless --dump-default-config    # → 87 行配置树
```

**真实运行（脱敏）**

```powershell
# 从托管凭据读取 key（不打印）
$cred = Get-Content "C:\Users\ysc20\.dsh\.credentials.yaml" -Raw
$env:DEEPSEEK_API_KEY = [regex]::Match($cred,'DEEPSEEK_API_KEY:\s*(\S+)').Groups[1].Value

# RUN 1：官方 headless profile
dsh --profile headless "Reply with exactly the text: MINIMAL-OK"
# → EXIT=0  ELAPSED=4.51s  STDOUT: MINIMAL-OK  STDERR: (空)

# RUN 2-5：自建 mini profile（18 插件行）
dsh --profile mini "Reply with exactly: MINI5-OK"
# → EXIT=0  ELAPSED=1.96s  STDOUT: MINI5-OK

# 工具调用验证
dsh --profile mini "Use the pwsh tool to run: Write-Output TOOLWORKS-42 . Report exactly what the tool returned, or the exact error."
# → EXIT=0  模型报告 Error: spawn EPERM（如实，无幻觉）

# 沙箱越权写入规范测试（脚本：run-sandbox-spec.ps1）
pwsh -NoProfile -File "D:\Incubator\temp\dsh-minimal\run-sandbox-spec.ps1"
# → TARGET FILE EXISTS? False（越权写入被阻止）
```

**上游资料（经镜像）**

```powershell
# npm registry 元数据
web_fetch https://registry.npmjs.org/@deepseek-ai/dsh
# → dist-tags: latest=0.1.5-rc.3, next=0.1.5-rc.3, alpha=0.1.7-alpha.2

# PyPI：Python SDK 官方文档全文
web_fetch https://pypi.org/pypi/deepseek-harness-sdk/json
# → version=0.1.5rc1, requires_python=">=3.10",
#   requires_dist=["deepseek-harness-runtime-bin==0.1.5rc1","pydantic<3,>=2.12"]
```

**协议类型定义（本机读取）**

```powershell
# SDK 协议权威定义（3 个请求方法 + 4 个通知 + 传输语义）
Get-Content "C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\dsh-sdk-protocol\lib\types\types.d.ts" -Raw
Get-Content "C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\dsh-sdk-protocol\lib\types\transport.d.ts" -Raw
```

### 10.2 关键文件路径

**DSH 安装（CLI 与自带包）**

| 路径 | 内容 |
|---|---|
| `C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\package.json` | `bin.dsh = lib/bin.js`；`dsh.configTrees`；依赖清单 |
| `...\dsh\lib\bin.js` | CLI 入口：commander 解析、`web`/`plugin` 子命令、三种 invocation 模式 |
| `...\dsh\lib\profile-boot-Dk-7KqJc.js` | **核心**：`prepareProfile` / `composeProfile` / `allPatches` / `runProfile` |
| `...\dsh\lib\plugin-Ddi42qoW.js` | `dsh plugin` → 转发 pnpm |
| `...\dsh\lib\dump-config-lFgMwK8i.js` | `--dump-config` 实现 |
| `...\dsh\README.md` / `README.zh.md` | 启动器定位、入口模式表、profile 机制 |
| `...\dsh\node_modules\@deepseek-ai\` | CLI 自带的包子集 |

**完整插件库（240 个包）**

| 路径 | 内容 |
|---|---|
| `C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\` | **全部 240 个 `@deepseek-ai/*` 包** |
| `...\@deepseek-ai\dsh-sdk-minimal\cordis.patch.yml` | **官方最小 Cordis 树（31 行）** |
| `...\@deepseek-ai\dsh-sdk-minimal\package.json` | 最小闭包依赖清单（27 个） |
| `...\@deepseek-ai\dsh-base\cordis.patch.yml` | 完整基础（87 行，含全部工具与安全默认值） |
| `...\@deepseek-ai\dsh-headless\cordis.patch.yml` | 优雅的增量最小化范例（1,152 B，仅 insert 3 行） |
| `...\@deepseek-ai\dsh-sdk-app\lib\index.js` | SDK 启动提供方（45 行，可直接读懂） |
| `...\@deepseek-ai\dsh-sdk-protocol\lib\types\types.d.ts` | **SDK 协议权威定义**：3 个请求方法 + 4 个通知 + 全部载荷字段 |
| `...\@deepseek-ai\dsh-sdk-protocol\lib\types\transport.d.ts` | JSON-RPC 2.0 换行分帧传输语义与错误码 |
| `...\@deepseek-ai\dsh-agent-presets\presets\` | **4 个内置 agent preset**（standard / ptc / **minimal** / cordis） |
| `...\@deepseek-ai\dsh-terminal-bash\lib\index.js` | `inject = ["terminals", "sandboxPolicy", "sessionProjections", "subprocess"]` |
| `...\@deepseek-ai\dsh-tool-fs\lib\index.js` | `inject = ["tools", "fs", "systemPrompt"]` |
| `...\@deepseek-ai\dsh-tool-pwsh\lib\index.js` | `inject = ["tools", "shell", "systemPrompt", "shellEnv"]` |

**用户数据目录**

| 路径 | 内容 |
|---|---|
| `C:\Users\ysc20\.dsh\profiles\<name>\package.json` | profile manifest（`dsh.profile.bundles` + `patchReload`） |
| `C:\Users\ysc20\.dsh\profiles\<name>\cordis.patch.yml` | 用户补丁层 |
| `C:\Users\ysc20\.dsh\profiles\<name>\cordis.yml` | profile 根（恒为空表 `[]`，**启动时被重写**） |
| `C:\Users\ysc20\.dsh\.agent-presets\math-research\` | 真实自定义 preset 范例 |
| `C:\Users\ysc20\.dsh\settings.yaml` | 用户设置文档（热重载） |
| `C:\Users\ysc20\.dsh\.credentials.yaml` | **明文凭据（切勿外泄/提交）** |
| `C:\Users\ysc20\.dsh\sessions\` | 会话落盘 `session.v3.jsonl.zstd` |
| `C:\Users\ysc20\.dsh\storages\` | 工作区注册表、会话投影缓存 |

**本报告的实验产物**

| 路径 | 内容 |
|---|---|
| `D:\Incubator\temp\dsh-help\` | 全部 `dsh --help` / `--version` / 子命令帮助原始输出 |
| `D:\Incubator\temp\dsh-minimal\dsh-home\profiles\mini\` | **自建 18 行最小 profile 的可运行副本** |
| `D:\Incubator\temp\dsh-minimal\dump-mini-FINAL.yml` | mini 的 18 行组合树（19 个 `- id:`） |
| `D:\Incubator\temp\dsh-minimal\dump-sdk-minimal-default.yml` | 官方最小集 31 行 |
| `D:\Incubator\temp\dsh-minimal\dump-headless-default.yml` | headless 87 行 |
| `D:\Incubator\temp\dsh-minimal\RUN1-headless-stdout.txt` | RUN 1 脱敏输出（`MINIMAL-OK`） |
| `D:\Incubator\temp\dsh-minimal\tool-out.txt` | 工具调用验证（EPERM 如实报告） |
| `D:\Incubator\temp\dsh-minimal\specA-out.txt` | 沙箱越权写入测试（被阻止） |
| `D:\Incubator\temp\dsh-minimal\run-sandbox-spec.ps1` | 沙箱规范测试脚本 |
| `D:\Incubator\temp\evidence\` | 父智能体采集的一手证据摘录与 bundle 层副本 |

### 10.3 参考链接

**官方**

| 来源 | 链接 | 说明 |
|---|---|---|
| 仓库 README | https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/README.md | 定位、架构、"everything-is-a-plugin"、开发者预览警告 |
| 文档站点 | https://deepseek-harness.github.io/deepseek-harness/ | 官方文档 |
| GitHub 仓库 | https://github.com/deepseek-ai/deepseek-harness | 默认分支 **master**（非 main） |
| 论文（Cordis 设计） | https://arxiv.org/abs/2608.25512 | _A Programming Paradigm for Spatiotemporal Composability_ |
| Cordis 项目 | https://github.com/cordiverse/cordis | 底层插件框架 |
| npm：`@deepseek-ai/dsh` | https://registry.npmjs.org/@deepseek-ai/dsh | 版本与 dist-tags |
| npm：`@deepseek-ai/dsh-sdk-minimal` | https://registry.npmjs.org/@deepseek-ai/dsh-sdk-minimal | 最小 SDK bundle 元数据 |
| **PyPI：`deepseek-harness-sdk`** | https://pypi.org/pypi/deepseek-harness-sdk/json | **Python SDK 官方文档全文**（0.1.5rc1，`>=3.10`，自带 runtime-bin） |
| Python SDK 教程 | https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md | 官方文档路径（本次环境不可直连） |
| 官方架构文档 | `docs/architecture.md` / `docs/architecture.zh.md` | 仓库内路径，本次环境未取得正文 |
| 官方用户指南 | `docs/user/guide/index.md` / `index.zh.md` | 仓库内路径 |
| 官方开发实战 | `docs/user/develop/practice/index.md` | 仓库内路径（README 指向此处说明 `config/examples/` overlay） |

**仓库路径订正（重要）**：

| 常见写法 | **实际路径** |
|---|---|
| `packages/sdk-minimal` | ❌ 不存在 → **`packages/bundle/sdk-minimal`** |
| `packages/bundle/{base,web-app,headless,sdk-app,sdk-minimal,acp-app}` | ✅ 六个随附 bundle 的真实位置 |
| 默认分支 `main` | ❌ → **默认分支是 `master`**（`/main/README.md` 返回 404，`/master/README.md` 返回 200） |
| 根级 `examples/` | ❌ 不存在。`python/sdk/examples/` 存在（被 README 引用） |
| 根级 `templates/` | ❌ 不存在 |
| `config/examples/` | ⚠️ `dsh` README 声明存在，但仓库根无 `config/` 目录——**未取得证据** |

仓库根目录（GitHub contents API）：`.agents`、`.claude`、`.github`、`apps`、`benchmarks`、`docs`、`native`、`packages`、`patches`、`python`、`scripts`、`snapshots`、`vendor`、`website`。pnpm workspace 的两级 glob 为 `["vendor/*","packages/*/*","apps/*","website", ...]`。

**本机发行文件（本文主要证据来源）**

| 类别 | 路径 |
|---|---|
| CLI | `C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\` |
| 插件库 | `C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\` |

### 10.4 本次调研的局限（明确声明）

1. **GitHub 直连不可用**：本任务环境中 `github.com` / `raw.githubusercontent.com` / `api.github.com` / `cdn.jsdelivr.net` / `web.archive.org` / `*.github.io` 均解析到非公网 IP，`web_fetch` 被拒。上游事实经 `ghproxy.net` / `api.allorigins.win` 镜像、`unpkg.com` 与 npm/PyPI registry 交叉验证；官方文档站点正文**未取得**。
2. **仓库浅克隆一度失败，后已解决**：最初的 `git clone`（经 `ghproxy.net`）产生空目录，因此本报告第 1–10 章的源码级结论**全部来自本机已安装的构建产物**（`lib/*.js`、`lib/types/*.d.ts`、`README*.md`、`cordis.patch.yml`）——这一点保持不变。**后来取得了 master 分支的完整源码**，相关增补见 [§11](#11-基于-master-真源码的补充核对)，该章单独标注版本口径为 `0.1.7-alpha.2`，**不覆盖**前文的 rc.2 实测结论。
3. **工具真实执行未成功**：本机 shell 工具因环境级进程沙箱限制（`spawn EPERM` / `node-pty` conpty 失败 / Windows ACL `SetNamedSecurityInfoW` 失败）**未能真正执行命令**。本文验证的是"agent loop + 工具注册 + 工具派发 + 错误回传"整条链路，**不是**"命令成功产出结果"。
4. **SDK 路径未端到端跑通**：`dsh-sdk-protocol` 的协议形状（3 个请求方法 + 4 个通知 + 传输语义）与 Python SDK 的官方用法均已取得**权威文档证据**（本机 `.d.ts` + PyPI 描述全文）；但本报告**没有实际发送过 JSON-RPC 帧**，也**没有运行过 Python SDK**。§6.3.5 的 Node 客户端代码基于已核实协议编写，但未经运行验证。
5. **加固配方（§9.4）与减法清单（§5.3）未整体启动验证**：行 id 与配置字段均逐条核对自发行文件原文，但组合后的启动未经实测。
6. **Node 版本未经多版本验证**：仅在 Node v24.16.0 上验证；`engines: "^22.19.0 || >=24.0.0"` 系官方声明而非本机实测。
7. **`workspace-write` / `read-only` 的一手证据来源需说明**：本报告的这两档取值取自**本机安装的 `dsh-base/cordis.patch.yml` 第 229–241 行 `permission` 行的 `presets` 配置**（一手发行文件），而非第三方教程。上游公开的 `sdk-minimal` patch 只直接用 `danger-full-access`，因此若只读公开 patch 会误以为另外两档不存在。
8. **第三方资料的使用限度**：第三方文章中反复出现的"四种运行模式（Standard/PTC/Minimal/Creator）"与本报告的一手证据**不矛盾但层级不同**——一手证据里那是 4 个 **agent preset**（rc.2：`packages/preset/agent-presets/presets/`；master 已重构为 `packages/preset/agent-preset*` 三个包，见 §11.7），而不是 4 个运行模式；DSH 的**运行入口**（profile）一手证据只有 5 个：`web` / `headless` / `sdk` / `sdk-minimal` / `acp`。引用第三方资料时请勿混淆这两个层级。
9. **master 与 rc.2 的版本差异**：本机安装 `0.1.5-rc.2`，而 §11 分析的源码是 `0.1.7-alpha.2`。**跨版本的事实不可互相替代**；§11 已逐项并列标注。尤其在撰写命令时注意：`dsh headless "任务"`（省略 `--profile`）**只在 master 有效**，rc.2 必须写 `dsh --profile headless "任务"`（§11.8 已实测对照）。

---

## 11. 基于 master 真源码的补充核对

> **版本口径声明（重要）**：本章的**全部**事实来自 `deepseek-harness` 仓库 **`master`** 分支的完整源码（`package.json` 的 `version` = **`0.1.7-alpha.2`**），它**新于**本机安装的 `0.1.5-rc.2`。
> **本章不覆盖前文任何已实测的 rc.2 结论**；凡两者不一致处均以**并列**方式呈现并标注适用版本。
> 本地路径：`D:\Incubator\temp\06-sources\master\deepseek-harness-master\`（本节分析用的稳定副本，11,321 文件）。已用 SHA256 校验其 `packages/bundle/sdk-minimal/cordis.patch.yml` 与另一份完整解压（`temp\ds-repo\deepseek-harness-master\`）**逐字节一致**。

### 11.1 结论先行：最小集跨版本高度稳定

**§2 的"绝对最小集"与"官方最小集"在 master 上依然成立。** 官方最小集（`packages/bundle/sdk-minimal/cordis.patch.yml`）的**唯一变化是多了一行**：

```diff
      - id: mcp-resources
+       name: '@deepseek-ai/dsh-mcp-resources'
```

也就是说，从 `0.1.5-rc.2` 到 `master (0.1.7-alpha.2)`，这个"完整最小 Cordis 树"的插件行**从 31 行变成 32 行，新增且仅新增 `dsh-mcp-resources`**（MCP 资源能力）。除此之外**逐行相同**——包括：

- `sandbox-policy` 仍是 **`mode: danger-full-access`**（**风险结论不变**）
- `system-prompt` 仍是 `includeHarnessIdentity: false` / `includeRuntimeContext: false` / `personaPrefix` 默认 `'You are a helpful software engineer assistant.'`
- 仍**没有** `tool-fs` / `tool-web` / `tool-subagent` / `tool-todo` / `tool-goal` / `user-approval` / `compaction` / `tool-str-replace-editor`
- 工具仍是**唯一**的持久 shell（POSIX `dsh-tool-bash-persistent` / Windows `dsh-tool-pwsh-persistent`）
- 会话落盘仍是 `compression: none`

**证据方法**：对两份 `cordis.patch.yml` 做 `Compare-Object` 全文行级比对，输出**仅 3 行差异**（新增的 2 行 + 1 空行）。这是一个可复现的强证据。

> **对读者的实用含义**：你在 rc.2 上学会的"最小集"知识在 master 上直接可用。**最小集的稳定性远高于 bundle 外围**——`dsh-base` 同期从 84 行涨到 92 行，但最小集几乎不动。

### 11.2 master 的六个 bundle 补丁层（实测计数）

| bundle | master `cordis.patch.yml` 字节 | **插件行** | **覆盖行** | **合计 `id:` 条目** | rc.2 字节 | rc.2 插件行 | 变化 |
|---|---|---|---|---|---|---|---|
| `base` | 20,802 | **92** | 0 | **92** | 19,515 | **84** | +8 |
| `web-app` | 20,978 | **81** | 27 | **108** | 18,588 | — | — |
| `sdk-minimal` | 5,318 | **32** | 0 | **32** | 5,248 | **31** | **+1** |
| `sdk-app` | 1,586 | **4** | 3 | **7** | 676 | 3 | +1 |
| `headless` | 1,240 | **2** | 3 | **5** | 1,152 | 2 | 0 |
| `acp-app` | 553 | **2** | 3 | **5** | 525 | 2 | 0 |

**三个计数的区别（务必分清）**：

- **插件行**：带 `name:` 的条目 —— 真正挂载一个新插件。§2 的"最小集行数"一律指这个。
- **覆盖行**：只有 `- id:` + `config:` 或 `disabled:`、**没有 `name:`** 的顶层条目 —— 它按 id 改写一个**已存在的行**，不新增插件。
- **合计 `id:` 条目** = 插件行 + 覆盖行。这也解释了 §5.7 里 `--dump-config` 打印的 `- id:` 数为何会略多于插件行数。

`base` 的 **92** 这个数字有两重独立确认：① 直接对 patch 文件数 `name:` 行得 92；② 生成文档 `apps/cli/composition.md` 的插件表正好 **92** 行。

> ⚠️ **计数口径警告**：不要用 `- id:` 计数。`agent-loop` 行内嵌 `config.agents: [ { id: ... } ]`，会把内嵌 id 误计为插件行。（master 的 `agent-loop` 行是 `agents: []`，恰好为空；但**用户自定义的 profile 一旦填了 `agents: [...]` 就会踩这个坑**。本报告一律用**带 `name:` 的行**计数。）
> 对本机 rc.2 而言，`headless` = `dsh-base`(84) + `dsh-headless`(2) + 1 个内嵌 agent id = `--dump-config` 打印的 **87** 个 `- id:`。三者自洽。

### 11.2b 两个容易被忽略的结构细节（master）

**① `web-app` 是唯一的多文件 bundle**，且它自带 4 个 preset 补丁层：

```json
"dsh": {
  "bundle": {
    "patch": [
      "./cordis.patch.yml",
      "./presets/standard.patch.yml",
      "./presets/ptc.patch.yml",
      "./presets/minimal.patch.yml",
      "./presets/cordis.patch.yml"
    ]
  }
}
```

即 master 里 **agent preset 已从"数据目录"变成"bundle 内的补丁层"**——这与 §11.8 的 registry 重构是同一件事的两面。各 preset 补丁大小：`cordis` 8,089 B / `ptc` 7,697 B / `standard` 7,511 B / **`minimal` 3,184 B**（对应 §11.5 讨论的 3,119 B 版 rc.2 preset）。

**② `sdk-minimal` 的 `sandbox-policy.mode` 是字面量而非表达式**——这是它比 `dsh-base` 更危险的关键细节：

| | `sandbox-policy` 的 `mode` |
|---|---|
| `dsh-base` | `mode: !!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'` ← **可用环境变量覆盖，默认安全** |
| `sdk-minimal` | `mode: danger-full-access` ← **硬编码字面量，无环境变量出口，默认不安全** |

**所以：在 `sdk-minimal` 上设 `DSH_PERMISSION_MODE=read-only` 是无效的。** 想收紧它，**必须**用自己的 patch 覆盖该行（这正是 §9.4 加固配方第 1 条做的事）。这是本报告发现的最尖锐的一条安全差异。

### 11.3 master 的 `dsh-base` 组合：插件 id ↔ 模块对照表来源

master 新增了**生成式**的组合图 `apps/cli/composition.md`（文件头原文：`Generated by scripts/gen-doc-graphs.ts - do not edit by hand.`），它以 Mermaid 图 + 表格给出 `dsh-base` 的**每一个插件 id 与它解析到的包**，例如：

| Plugin id | Package / module |
|---|---|
| `timer` | `@deepseek-ai/cordis-plugin-timer` |
| `hmr` | `@deepseek-ai/dsh-hmr` |
| `llm` | `@deepseek-ai/dsh-llm` |
| `sandbox-policy` | `@deepseek-ai/dsh-sandbox-policy` |
| `approval` | `@deepseek-ai/dsh-user-approval` |
| `tool-fs` | `@deepseek-ai/dsh-tool-fs` |
| `agent-loop` | `@deepseek-ai/dsh-agent-loop` |
| …（共 92 行，完整表见该文件） | |

**这个文件正是 §7.1 那张"能力 → 包 → 配置"大表的权威对照源**，读者想核对任何一行的 `id` 拼写是否正确，应查它。

> **范围更正**：`apps/cli/composition.md` **只覆盖 `dsh-base` 一个 bundle**，标题是 `# DSH Base Composition`，**不是**"每个已发布 profile 的插件集"（本报告 §1.3 曾照 rc.2 README 的措辞引用过后者）。各 profile 的 bundle 列表见 `packages/boot/app-boot/src/profile.ts` 的 `PROFILE_TEMPLATES`；各 agent preset 的插件集见 `packages/bundle/web-app/presets/*.patch.yml`。

文件头部对架构的官方描述（原文）：

> "The dsh-base bundle patch shared by the web, headless, sdk, and acp profiles; their mode bundles and user layers patch over it, while **sdk-minimal owns a separate standalone tree**."

**维护方式（原文）**：`Maintenance mode: hybrid: the patch row list is parsed from its cordis.yml; app package expansion is curated from package source.` —— 即插件行是**从 patch 解析**的（不会漂移），包展开是**人工整理的**。

### 11.4 master 相对 rc.2 的 `dsh-base` 新增能力（+8 行）

从 `composition.md` 的 92 行表中识别出的、rc.2 本机 baseline 中**不存在**的行：

| master 新增行 id | 包 | 作用 |
|---|---|---|
| `plugin-manager` | `@deepseek-ai/dsh-plugin-manager` | 运行时插件管理 |
| `tool-plugin-manager` | `@deepseek-ai/dsh-plugin-manager/tools` | 插件管理的模型工具面 |
| `config-editor` | `@deepseek-ai/dsh-config-editor` | 配置编辑 |
| `authorization` | `@deepseek-ai/dsh-authorization` | 授权 |
| `deepseek-account` | `@deepseek-ai/dsh-deepseek-account-platform` | DeepSeek 账号平台 |
| `ptc-runtime` | `@deepseek-ai/dsh-ptc-runtime-node` | PTC 执行运行时 |
| `workflow-ptc` | `@deepseek-ai/dsh-workflow-ptc` | PTC 形式的工作流 |
| `image-offload` | `@deepseek-ai/dsh-compaction-image-offload` | 图片卸载 |
| `mcp-resources` | `@deepseek-ai/dsh-mcp-resources` | MCP 资源 |

> 注：master 的 `hmr` 行解析到 `@deepseek-ai/dsh-hmr`，而 rc.2 是 `@deepseek-ai/cordis-plugin-hmr` —— **同一行 id、不同包**，是包重命名/内聚的迹象。**这属于"外层 bundle"的演进，不影响 §2 的最小集。**
> `settings` 行在 master 指向 `@deepseek-ai/dsh-settings`，rc.2 是 `@deepseek-ai/dsh-settings-file`，同为同类变化。

### 11.5 官方术语：`capability-seam`（能力缝）的精确定义

前文 §1.2 曾用"capability seam"说明架构。master 的 `docs/glossary.zh.md` 给出了**规范定义**（原文逐字）：

> **seam**：一种包含三种角色的*可替换能力*：**Service Definition**（拥有自身 `ctx.<key>` 和词汇类型的 Cordis `Service`——可以是 `ShellExecutor` 这样的抽象类，也可以是 `WebRuntime` 这样的具体注册表，**绝不是 TypeScript `interface`**）、一个或多个 **Service Provider**，以及一个或多个注入该服务的 **Consumer**。`packages/shell` 是规范范例：`dsh-shell`（Service Definition）、`dsh-bash-local` / `dsh-bash-sandbox`（提供方），以及 `dsh-tool-bash`（Consumer）。…… **seam 是完整能力，绝不是其中一个角色**。

**三条对本任务直接有用的推论**：

1. **Service Definition 不是 TS interface 而是 Cordis `Service`**——所以它必须能被挂载（提供 `ctx.<key>`）。这解释了 §5.4 实测中 `dsh-scope`（纯工具库，没有 `apply`）无法作为插件行挂载，而 `dsh-shell`（`ShellExecutor` 抽象类）**也**不能直接挂——它是要由 provider 实现的 Service Definition。
2. **同一个包可以承担多个角色**（原文以 `dsh-user-approval` 为例：它在一个包里同时是 approval seam 的 Service Definition 与其具体实现）。
3. **"能力 = 三角色齐全"**——这为 §2.1 的"能用四条件"提供了官方理论依据：LLM 接入是 seam（`dsh-llm` + `dsh-llm-deepseek` + agent loop），工具是 seam（`dsh-tools` + 各 `tool-*` + loop），会话是 seam。**最小集本质上就是"把每条必需缝的三种角色各挂一份"。**

> 该术语表还定义了本报告涉及的核心概念，值得作为读者的官方词汇参照：**轮次（Turn）/ 步骤（Step）/ Round** 的层级、**scope / scope key / shadowing / restriction**、**目标（Goal）/ Goal Round**、**Ralph 循环 / Ralph Round / Ralph 交接**。其中与本报告 §8 直接相关的一条：**轮次** = "会话中一次对已接纳输入的排空过程"，**步骤** = "一次模型请求，以及由模型响应引发的工具执行"，一个轮次包含零个或多个步骤。

### 11.6 agent preset 与宿主平面的边界（回答"preset 为什么不能配沙箱/审批"）

前文 §1.3 建立了 bundle / profile / preset 三层。master 有一篇专门的设计笔记回答了一个关键问题：**preset 之后，什么仍归宿主平面（host plane）？**

笔记 `.agents/notes/implemented/architecture/2026-08-10-host-plane-ownership-after-presets.zh.md` 的判据（原文）：

> "**meter 属于宿主平面。** …… preset 保留 realm 与压缩后端——**preset 选择的是它的 agent 是否压缩，而不是它的 token 是否被计。**"

> "**未加入的 Agent 在使用模型时失败。** …… 加入是一条 scope 父链链接；缺了它，`tools`、`system-prompt` 与 `skill` 的视图都解析到空的全局层，**模型什么也收不到——不报错，也没有空目录可看，只是一个无法行动的 agent。**"

**对本任务的直接结论**：

| 归属 | 内容 | 证据 |
|---|---|---|
| **宿主平面（preset 不管）** | 沙箱（`sandbox` / `sandbox-policy`）、审批（`approval`）、权限预设、凭据、设置、遥测、持久化、模型路由、token 计量（`dsh-token-meter`） | 该笔记 + `sdk-minimal`/`base` patch 的行归属 |
| **agent 平面（preset 管）** | 该 agent 看到哪些工具、persona / 提示段、技能、`plan-mode`、`tool-todo`、压缩后端选择 | 同上；内置 4 个 preset 的 `agent.cordis.yml` |

**所以"想给最小智能体加审批/改沙箱"是 profile 层（或 overlay）的事，不是 preset 的事。** 这正好印证并解释了 §9.4 加固配方为什么把 `approval` / `sandbox-policy` / `permission` 放在 **profile 的 patch 层**：那是它们在架构上唯一合法且生效的位置。**把 `mode: workspace-write` 写进 preset 的 `agent.cordis.yml` 不会生效。**

笔记另有一条对"最小集"很有价值的架构事实（原文）：

> "不变量覆盖加载了 `dsh-invariants` 的组装。**生产入口必须显式组装 Agent**；仅安装注册表不会自动绑定。"

即：`dsh-invariants` + `*/invariant` 是**自检层**，但真正创建 Agent 的行必须由组合显式给出（在最小集里就是 `agent-loop` 的 `agents: [...]`，或 headless runner 的按需创建）。

### 11.7 官方"加一个工具"的确切 API（master）

前文 §7 讲的是"**加装已有能力**"（翻开现成的插件行）。如果你的需求是**写一个 DSH 里没有的新工具**，master 的 `docs/cookbook/adding-a-tool.zh.md` 给出了官方 API。**最小形态（原文逐字）**：

```ts
import { readFile } from 'node:fs/promises'
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'my-tool'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(defineTool({
    name: 'read_file',
    description: 'Read a file from disk.',          // what the model sees
    parameters: {
      path: { type: 'string', required: true, description: 'Absolute path' },
      limit: { type: 'number' },                     // optional by default
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args, exec) {
      // args is TYPED from the schema: { path: string; limit?: number }
      // exec carries immutable identity + token; signal is the operational field
      return readFile(args.path, { encoding: 'utf8', signal: exec.signal })
    },
  }))
}
```

**这个形态与前文本报告的实测发现完全自洽**——注意 `export const name` 与 `export const inject = ['tools']`：这正是 §5.4 里 fail-loud 报错所说的"服务依赖"机制，也是 §5.4 发现 `dsh-scope` 失败的原因（它没有 `apply`）。

`execute()` 的关键约定（原文摘录）：

| 规则 | 原文要点 |
|---|---|
| **参数已校验** | "`defineTool` 在 `execute` 运行前，会根据统一的 `ParameterSchemaSpec` 校验模型生成的 `arguments`"，因此 `execute` 内的 args 会匹配 `InferArgs`。显式对象节点必须声明 `additionalProperties: true \| false` |
| **注册借用你的只读定义** | "注册后不要修改其 schema 或替换回调。…… 如需热替换工具，请 dispose 其所属副作用并注册替代品" |
| **执行身份受保护** | 注册表分配不透明 `exec.token`；`callId`/`name`/`arguments`/`agent`/`token`/`signal`/`parent` 全程不可变。**把 `args` 视为只读输入** |
| **声明并返回规范 JSON 值** | "`execute` 只返回推导出的值"，注册表快照为无损 JSON 后传给 `output.render`。"工具主体不要返回内容块" |
| **抛异常 = `isError`** | "基础设施故障请抛异常。成功的领域结果即使表示不理想的状态，也应写入规范值" |
| **遵守 `exec.signal`** | 信号触发时取消进行中的工作 |
| **注册基于副作用** | "dispose（资源释放）插件 fiber 即注销该工具" —— 对应仓库通例 "Registrations are effects" |

**长任务**用 `ctx.jobs.start({ kind, label, owner: exec.agent, run })`；**策略**不要内建进工具，而用扩展点：`tools/pre-execute`（允许/拒绝/询问）、`ctx.tools.guard()`（不可撤销的单调拒绝）、`tools/execute`（截止时间/重试/指标）、`tools/post-execute`、`tools/result`。

**UI 卡片是独立关注点**：`output.render` 管模型可见内容；`presentCall` / `presentResult` 管可回放的 UI 卡片（`generic` / `terminal` / `diff` / `read` / `search` / `web` 六种渲染意图）。硬性规则：**这些方法必须是纯函数**（实时流式与会话回放都会跑，所以不做 I/O、不读会话状态、不用时钟/随机数）。

> **与 §7 的分工**：§7 是"从已有插件里挑一个挂上"（改 `cordis.patch.yml`）；本节是"自己写一个新插件"（建包 + `apply` + `defineTool`）。

> **两份官方文档的分工（易混淆，务必分清）**：
> - `docs/cookbook/adding-a-tool.zh.md`（14 KB）**不是分步教程**，而是**契约参考**。其开头原文：「面向模型的工具必须满足哪些约定，均以本文为准。**如需按步骤构建第一个工具，请阅读[构建工具](../user/develop/basic/tool.zh.md)。**」
> - **真正的分步教程在 `docs/user/develop/basic/tool.zh.md`**（52 行），官方用 2 步做出一个 `greet` 工具（原文逐字）：
>
> **第 1 步**——替换 `scratch-plugin/src/my-plugin.ts`：
>
> ```ts
> import type { Context } from '@deepseek-ai/cordis'
> import { defineTool } from '@deepseek-ai/dsh-tools'
>
> export const name = 'greet-tool'
> export const inject = ['tools']
>
> export function apply(ctx: Context) {
>   ctx.tools.register(defineTool({
>     name: 'greet',
>     description: 'Greet someone by name.',
>     parameters: {
>       name: { type: 'string', required: true, description: 'The name to greet' },
>     },
>     output: {
>       schema: { type: 'string' },
>       render: (_args, value) => [{ type: 'text', text: value }],
>     },
>     async execute(args) {
>       return `Hello, ${args.name}!`
>     },
>   }))
> }
> ```
>
> 原文解释：「`inject` 让 Cordis 等待工具注册表就绪。`defineTool` 根据 `parameters` 推导并校验 `args`；`execute` 返回 `output.schema` 声明的规范值，`output.render` 再将该值转换为面向模型的内容。」
>
> **第 2 步**——用 patch 挂上并运行：
>
> ```sh
> pnpm dsh web --patch ./scratch-plugin/cordis.yml
> ```
>
> 然后打开 `http://127.0.0.1:3080` 输入 `Use the greet tool to greet Ada.`，模型会调用 `greet` 并收到 `Hello, Ada!`。
>
> **注意 `--patch ./scratch-plugin/cordis.yml` 这一手法**：这正是 §5.6 讲的"用 `--patch` 做临时覆盖"——**开发期完全不必改 profile 文件**。这是官方推荐的插件开发姿势。
>
> 建包的完整流程见 `docs/cookbook/adding-a-package.zh.md`（15 KB）；把一项能力拆成三角色包的做法见 `docs/user/develop/practice/index.zh.md`——原文：「将可替换能力拆分为 Service Definition、Service Provider 和 Consumer 三类包。」

### 11.8 master 相对 rc.2 的 preset 机制重构（前文 §1.3 / §7.6 的补注）

| | rc.2（本机实测） | master |
|---|---|---|
| preset 载体 | 一个包 `dsh-agent-presets` 内含 `presets/` 目录（4 个内置 preset：standard / ptc / **minimal** / cordis） | 重构为**三个包**：`packages/preset/agent-preset`、`packages/preset/agent-preset-registry`、`packages/preset/persona` |
| 挂载方式 | `@deepseek-ai/dsh` 的 `dsh.configTrees` 指到 `../../packages/preset/agent-presets/presets`，`scanRoster: true` | 注册表包提供 `composition-inventory` / `definition` / `display` / `mount` / `preset` / `session` / `specifier` / `types` 等模块 |
| 设计文档 | — | `.agents/notes/implemented/architecture/2026-09-18-declarative-agent-presets.zh.md`（**"声明式 agent preset"**） |

**这不影响 §7.6 的实践结论**：用户侧仍然是"在 `$DSH_HOME\.agent-presets\<name>\` 放 `preset.yml` + `agent.cordis.yml`（+ 可选 `skills/`）"。重构发生在框架内部（registry 化 + 声明式化），**用户可见的 preset 目录形态未变**。

> ⚠️ 未经运行验证：由于本机是 rc.2，**本条 master 结论未经实机启动验证**。若你在 master 上开发 preset，请以 `packages/preset/agent-preset-registry/src/**` 与 `2026-09-18-declarative-agent-presets.zh.md` 为准。

### 11.9 master CLI 相对 rc.2 的两个真实变化（**已实测对照**）

这是本章唯一做了**实机对照**的部分——我没有 master 的可执行文件，但我在 rc.2 上实跑了疑似的 master 特性。

| 特性 | master（源码 + 期望输出文件） | rc.2（**本机实跑**） |
|---|---|---|
| **裸 profile 名简写** | 支持。`apps/cli/src/args.ts` 第 200–204 行：<br>`const expanded = first !== undefined && !first.startsWith('-') && first !== 'plugin' ? ['--profile', ...argv] : argv`<br>→ `dsh headless "task"` 等价于 `dsh --profile headless "task"` | ❌ **不支持**。实测 `dsh headless --help` → 打印**启动器自己的** help（因为 `--help` 被启动器截获），`dsh headless "任务"` 会被当作未知参数处理 |
| **`--dump-config-schema`** | 支持。输出"profile 条目与 patch 的 JSON Schema，且不挂载配置树" | ❌ **不存在**。实测 `error: unknown option '--dump-config-schema'`（exit 1） |
| **`headless` 的 `--json`** | 支持。`packages/bundle/headless/src/startup.ts`：<br>`.option('--json', 'write newline-delimited run events to stdout instead of the final message')` | ❌ 不存在 |
| **`headless` 的 `--session-id <id>`** | 支持。`.option('--session-id <id>', 'adopt the persisted Session with this id; an unknown id is an error')` | ❌ 不存在 |
| **`headless` 从 stdin 读任务** | 支持。`.argument('[task...]', 'the task text; multiple words are joined by spaces, and `-` reads stdin')` —— 用 `-` 让任务来自 stdin | ❌ 不存在 |
| **注册的子命令** | **只有一个：`plugin`**（`args.ts` 中 `.command(` 仅出现 1 次，在第 187 行）。`web` 是**语法糖**而非子命令——它由第 201–203 行的 `expanded` 重写成 `--profile web` | `web` 与 `plugin` **都是**真正的 `program.command(...)` 子命令 |
| 启动器 help 首行 | `Usage: dsh [--profile] <name> [options] [app-args...]` | `Usage: dsh [options] [command] [args...]` |
| 启动器选项数 | 6 个（`--profile` / `--from-default-profile` / `--patch` / `--dump-config` / `--dump-config-schema` / `--dump-default-config`） | 5 个（无 `--dump-config-schema`） |
| 示例写法 | `dsh web` / `dsh headless "run the tests"` / `dsh tui --patch ./extra.yml` | `dsh --profile web` / `dsh --profile headless "run the tests"` |

> **一个自我更正**：本报告 §1.2 与 §8.1 曾照 rc.2 的 `bin.js` 写道"启动器注册了 `web` 与 `plugin` 两个子命令"。这对 **rc.2 是正确的**（rc.2 的 `bin.js` 里确有 `program.command("web")`），但**对 master 不成立**——master 把 `web` 降级为 `expanded` 重写，只剩 `plugin` 一个真子命令。两个版本的事实都在此并列，**不要跨版本套用**。

**master 的 `headless` 行原文**（`packages/bundle/headless/cordis.patch.yml`，含新增的 `sessionId` / `json` 转发）：

```yaml
    - id: headless-runner
      name: '@deepseek-ai/dsh-headless'
      inject: [headlessStartup]
      config:
        task: !!js ctx.headlessStartup.task
        sessionId: !!js ctx.headlessStartup.sessionId
        json: !!js ctx.headlessStartup.json
```

master 的权威 `dsh --help` 输出存在仓库里：`apps/cli/tests/expected/launcher-help.txt`（**这是 e2e 期望文件，即 CI 保证的真实输出**），其要点：

```
Usage: dsh [--profile] <name> [options] [app-args...]
       dsh plugin --profile <name> <pnpm-args...>

Options:
  -V, --version
  --profile <name>
  --from-default-profile <name>
  --patch <path>
  --dump-config
  --dump-config-schema           print JSON Schema for profile entries and patches without mounting
  --dump-default-config
```

**实践建议**：本报告 §4 的所有命令都**显式写 `--profile`**（形如 `dsh --profile headless "任务"`），这个写法在 **rc.2 与 master 上都正确**。若你为 master 写文档，可以省略 `--profile`；若要兼容 rc.2，**不要省**。

### 11.10 master 的官方轮次流程与事件域（为 §8 提供权威底图）

前文 §8 讲"怎么确认 agent 真的在跑"。master 的 `docs/architecture.zh.md` 给出了**官方的轮次流程图**与**事件分类**，两者合起来就是"该看什么"的权威答案。

**轮次流程（`architecture.zh.md` 原文代码块要点，按发生顺序）**：

```
turn/start
  → agent/pre-step          （waterfall）
  → agent/request           （waterfall）
  → llm/stream              （waterfall）
  → tool/call *             （持久事件）
      → tools/pre-execute   （waterfall）
      → tools/execute       （waterfall）
      → tools/post-execute  （waterfall）
      → tool/result *       （持久事件）
  → agent/turn-stopping     （serial，无 next()）
  → turn/end
```

**三类事件域（原文）**：

> **会话事件**是追加到日志并通过 `session/event` 广播的持久事实。**当某个事实必须在重新加载后仍然存在时，使用它。**
> **Agent 事件**（`agent/*`）携带活跃 `Agent`：inbox、步骤、状态、请求、验证、续跑。**要观察或拦截进行中的工作时，使用它。**
> **能力事件**无需导入循环即可向某个 seam（`fs/*`、`tools/*`、`telemetry/*`）附加策略和适配器。

**哪些是持久的、哪些是瀑布式的（原文 L113 分类）**：

| 类别 | 事件 |
|---|---|
| **持久**（写入会话日志） | `turn/*`、`step/*`、`system/message`、`user/message`、`assistant/message`、`assistant/attempt`、`tool/*` |
| **waterfall**（可拦截/包装） | `agent/pre-step`、`agent/request`、`llm/stream`、`tools/pre-execute`、`tools/execute`、`tools/post-execute` |
| **serial，无 `next()`** | `agent/turn-stopping` |

**这直接落地了 §8 的"怎么确认在跑"**：

- 想知道**这轮做完没有** → 看持久事件流里的 `turn/end`（对应 §6.3.3 的 `session.event` 通知，SDK 侧由 `finish_reason` 暴露）。
- 想知道**模型到底被发了什么** → 看 `agent/request` / `llm/stream`。
- 想知道**工具被谁拦了** → 看 `tools/pre-execute`（策略）与 `tools/guard`（不可撤销拒绝）。

**贯穿全局的一条硬约束（原文 L129）**：

> **模型可见即已记录。** 抵达模型请求的一切都必须能从日志重建。

这条"Model-visible ⟺ logged"是本报告 §8.1 把"会话落盘 JSONL"列为验证手段的**架构级理由**——不是"顺便存了个日志"，而是**框架的设计不变量**。仓库根 `AGENTS.md` 也把它写成了一条强制规则：「**Model-visible ⟺ logged**: anything that reaches a model request must be reconstructable from the session log; a new model-visible input requires a session event.」

> ⚠️ 版本口径：以上均出自 **master** `docs/architecture.zh.md`（`0.1.7-alpha.2`）。rc.2 的事件名与分流机制**未逐一核对**；本报告 §8 的实探手段（`--dump-config`、会话落盘、退出码、stderr 的 `dsh: reasoning:`）都是**实跑验证过**的，与本节不冲突。

### 11.11 master 新增的可用资源（读者延伸阅读）

| 资源 | 路径（master） | 用途 |
|---|---|---|
| **配置字段权威目录** | `docs/config-catalog.zh.md`（**185 KB**） | 每个支持字段及其 JSDoc 的穷尽式真源——核对你写的任何 `config:` |
| **工具权威目录** | `docs/tool-catalog.zh.md`（**96 KB**） | 全部工具的 schema 与说明——核对工具名与参数 |
| **能力缝目录** | `docs/capability-seams.zh.md`（**60 KB**） | 每条 seam 的三角色与提供方清单 |
| **配置目录（可执行）** | `packages/bundle/*/cordis.patch.yml` + `apps/cli/composition.md` | 每个 profile 实际挂载的精确插件集 |
| **加工具官方分步指南** | `docs/cookbook/adding-a-tool.zh.md`（14 KB） | "如何给 DSH 加一个工具"的操作手册 |
| **加包官方分步指南** | `docs/cookbook/adding-a-package.zh.md`（15 KB） | 新插件包的目录结构、manifest、README 契约 |
| **加设置卡** | `docs/cookbook/adding-a-settings-card.zh.md`（4.4 KB） | 给 Web 设置页加一项 |
| **加 LLM 适配器** | `docs/cookbook/adding-an-llm-adapter.md`（4 KB） | 接入新模型提供方 |
| **架构总图** | `docs/architecture.zh.md`（18 KB） | 改 `packages/` 前必读 |
| **术语表** | `docs/glossary.zh.md`（6.5 KB） | 官方词汇规范（见 §11.5） |
| **Cordis 入门** | `docs/cordis-primer.zh.md`（4 KB） | Context / Service / inject / effect / 事件语义 |
| **配置示例（overlay）** | `apps/cli/config/examples/` | `github-review` / `mcp-memory` / `schedule` 三个可选 overlay 实例 |

> **注意**：master 的 `docs/` 里**没有 `examples/`**，但 `apps/cli/config/examples/` 确实存在（这回答了"`config/examples/` 在哪"——它在 **`apps/cli/config/examples/`**，是 CLI 应用自带的配置示例树，而非仓库根的 `config/`）。

### 11.12 本章新增的未验证项

1. **master 未经实机运行**：本机只有 `0.1.5-rc.2`。§11.1–§11.7、§11.10–§11.11 全部是**源码与文档证据**，不是运行证据；只有 §11.9 的 rc.2 那一列是实跑结果。
2. **master 的 `dsh --help` 未实跑**：引用的是仓库内的 e2e 期望文件 `apps/cli/tests/expected/launcher-help.txt`（CI 保证），非本机输出。
3. **Windows 解压损失**：master 解压时有约 130 个符号链接类文件（如 `CLAUDE.md` → `AGENTS.md`）在 Windows 上创建失败（`Invalid argument`）。这不影响本报告引用的任何文件，但若你要完整复现，需在支持符号链接的环境解压。
4. **`packages/` 未做全量核对**：master `packages/` 有 **54 个 group**（相对 rc.2 本机的 46 个 group / 240 包，master 约 316 包）。本报告只核对了与"最小可用智能体"直接相关的 `bundle/`、`preset/`、`sdk/`，未覆盖全部。
5. **`docs/` 未全量阅读**：`docs/config-catalog.zh.md`（186 KB）、`docs/tool-catalog.zh.md`（96 KB）、`docs/capability-seams.zh.md`（60 KB）、`docs/module-graph.zh.md`（120 KB）、`docs/persistence-catalog.zh.md`（339 KB）体量极大，本报告只做了**定向检索**（工具名、配置字段、seam 清单），未逐页精读。**核对具体字段时请以这些生成式文档为最终依据。**
6. **`docs/capability-seams.zh.md` 的 seam 清单未逐条验证**：该文件是生成式图文档（仅一个 `# ` 标题，正文是 Mermaid 图 + 89 行表；按角色计数为 `core` 54 / **`seam` 33** / `bundle` 1 / `service` 1）。本报告只在 §11.5 引用了 `dsh-shell` 这一个范例，未复核全部 33 条 seam 的角色归属。
7. **跨版本的行为差异只覆盖 CLI 与 bundle 层**：§11.9 的对照是**实测**的；但 rc.2 → master 在**事件名、配置字段默认值、preset 数据模型**上的差异**未逐项对照**。跨版本迁移代码时请以 master 的 `docs/config-catalog.zh.md` 与各包 README 为准。

---

*报告完 · 所有代码/命令均基于真实证据；推断内容已用 `> ⚠️ 推断（未经运行验证）` 标注 · master 事实见 §11，版本口径为 `0.1.7-alpha.2`，不覆盖前文 rc.2 实测结论*
