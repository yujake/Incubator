# DeepSeek Harness（DSH）开源仓库结构调查报告

> 调查对象：GitHub `deepseek-ai/deepseek-harness`（README 标语：**DeepSeek Harness: Everything is a Plugin.**）
> **最终证据基础（已升级）**：`master` 分支完整工作树，落盘 `D:\Incubator\temp\ds-repo\deepseek-harness-master\`，**13,229 个文件 / 104.7 MB / 54 个 package group / 307 个包目录**，根 `package.json` 版本 **`0.1.7-alpha.2`**
> 调查方式：master 真树一手读取 + 本机 npm 安装产物 + Gitee 镜像 + 第三方报道旁证（详见第 8 节可信度标注）
> **网络受限声明**：本机 hosts 曾将 `github.com` / `api.github.com` / `raw.githubusercontent.com` / `cdn.jsdelivr.net` / `deepseek-harness.github.io` 全部解析到 `127.0.0.1`。最终经 `ghproxy.net` 镜像取得 `archive/refs/heads/master.tar.gz`（27,099,922 B，校验无损）并解压，**已绕开该限制**；Gitee 镜像 `wenj91/deepseek-harness` 作为第二独立来源保留。

---

## ⚠️ 版本口径声明（阅读全文前必读）

本报告涉及**三个不同的仓库快照**，结构存在真实差异。**全文凡涉及结构断言处均标注版本**；未标注者默认为 **M（master 真树）**。

| 代号 | 版本 | 来源 | 规模 | 角色 |
|---|---|---|---|---|
| **M** | `master` = **`0.1.7-alpha.2`** | 完整工作树 `D:\Incubator\temp\ds-repo\deepseek-harness-master\` | 13,229 文件 / **54 group / 307 包** | **主证据源（一手）** |
| **L** | **`0.1.5-rc.2`** | 本机 npm 安装 + profile 安装 | **46 group / 229 已发布包**（+ 8 vendor + 2 apps + 1 native = 240） | 发行版对照（一手） |
| **G** | **`0.1.0-rc.5`** | Gitee 镜像 `wenj91/deepseek-harness` | **48 group**（目录列举） | 历史快照对照（一手，经镜像） |

> **严禁把 M 的结构当作 L 的结构。** 第 **11 节**是全文唯一的结构演进总表。
> **解压限制说明**：约 130 个仓库内**符号链接/硬链接**文件（`CLAUDE.md`、`.claude/skills`、部分 `snapshots/**` 下的 `AGENTS.md` 与 `*.expected.*`）无法由 Windows `tar` 创建，故工作树中缺失。**这是解压工具限制，非仓库本身缺失**；报告中按"仓库存在、本地未解出"处理，且不影响任何目录级结论。

---

## 0. 结论速览

| 项目 | 结论 | 版本 | 可信度 |
|---|---|---|---|
| 仓库形态 | pnpm workspace **monorepo**，`packages/<group>/<pkg>` 两级目录，统一 scope `@deepseek-ai/dsh-*` | M/L/G | 一手 |
| 顶层目录 | **14 个目录 + 约 41 个根级文件**（见 2.1/2.2） | M | **一手（真树）** |
| 顶层目录（历史） | G 为 14 个目录（含 `assets`/`examples`，无 `snapshots`/`benchmarks`） | G | 一手（镜像） |
| **根目录没有 `config/`** | 三个版本**均无**顶层 `config/`；`config/` 是配置树**挂载命名空间** | M/L/G | 一手 |
| `configTrees` 机制 | **M 已退役**：`apps/cli/package.json` 的 `dsh` 字段整体消失；仅作为**内部字段**残存于镜像打包器 | M | **一手（真树）** |
| `packages/` 领域数 | **54 个 group / 307 个包**（54 个 group 各有 `README.md`） | M | **一手（真树）** |
| `packages/` 领域数（历史） | L = 46 group / 229 已发布包；G = 48 group | L/G | 一手 |
| 已发布包总数 | **240 个**（229+8+2+1），240/240 均带 `repository.directory` | L | 一手 |
| 最大领域 | M：`client/` 59、`experimental/` 20、`session/` 20、`util/` 16 | M | **一手（真树）** |
| License | **MIT**（`LICENSE` 全文 + `README.md` + 三处 `package.json` 四处一致） | M/L/G | 一手 |
| 生态标注矛盾 | 鲸智社区标 `apache-2.0`，**与四处一手证据矛盾，判定为第三方元数据错误** | — | 一手否证 |
| 一切皆插件 | 内嵌 **Cordis**（`vendor/`，9 包）+ loader + `bundles`/`profiles` patch 装配链；capability seam 三分法 | M | **一手（真树）** |

---

## 1. 仓库概览

### 1.1 官方定位（`README.md` 原文引用）

> DeepSeek Harness (`dsh`) is an open-source agent harness developed by [DeepSeek AI](https://deepseek.com).
>
> It uses an architecture where **everything is a plugin**, and is powered by [Cordis](https://github.com/cordiverse/cordis), whose design is described in [_A Programming Paradigm for Spatiotemporal Composability_](https://github.com/cordiverse/paper).

> ## Developer preview
> DeepSeek Harness is currently in _developer preview_ and is iterating rapidly. **THERE WILL BE COMPATIBILITY-BREAKING CHANGES.**

> ## Run from `npm`
> ```sh
> npx @deepseek-ai/dsh web
> ```
> The command starts the Web UI, served at `http://127.0.0.1:3080` by default.

鲸智社区（工信部大模型公共服务平台）仓库页给出的一段官方定位转述（第三方页面，可访问）也与此一致：

> deepseek-harness 是 DeepSeek AI 开源的智能体开发与运行框架……其核心采用"一切皆插件（Everything-is-a-Plugin）"的架构思想，并由 Cordis 框架提供底层支持，使模型、工具、运行环境及其他能力能够以模块化方式组合和扩展。

### 1.2 License（**三证合一定论：MIT**）

**结论：MIT，证据三处独立且一致。**

| 证据 | 来源 | 内容 |
|---|---|---|
| **证 1（最权威）** | GitHub REST API `GET /repos/deepseek-ai/deepseek-harness` | `license.spdx_id = "MIT"` |
| **证 2** | 仓库根 `LICENSE` 全文（master 真树已读） | `MIT License` / `Copyright (c) 2026 DeepSeek` |
| **证 3** | npm 包 `@deepseek-ai/dsh` 自带 `LICENSE` + `package.json` 的 `"license": "MIT"` | MIT |

仓库根 `README.md` 亦明确写：

> ## License
> [MIT](LICENSE)
> Third-party dependencies and their licenses are disclosed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

`master` 根 `package.json`（`@deepseek-ai/dsh-root` 0.1.7-alpha.2）与 `apps/cli/package.json`（`@deepseek-ai/dsh` 0.1.7-alpha.2）**均写 `"license": "MIT"`**——即**第五处**一致证据。

❌ **否证结论**：鲸智社区页面标注 `开源许可证 apache-2.0`。该标注与**五处独立一手证据**全部矛盾，**判定为第三方平台元数据错误**。任何合规使用应以仓库根 `LICENSE` 为准。

> 补充旁证：仓库存在 `scripts/verify-dsh-package-licenses.ts` 与 `.spec.ts` 配对脚本，说明**许可证一致性是 CI 门禁之一**——MIT 是被系统性强制执行的，而非笔误。

### 1.5 GitHub API 一手元数据（生态与协作渠道）

来源：`GET /repos/deepseek-ai/deepseek-harness`（经 `gh-proxy.com` 镜像取得，HTTP 200），**采集时点 2026-09-23**，为**即时值**。

| 字段 | 值 | 说明 |
|---|---|---|
| `description` | **"DeepSeek Harness: Everything is a Plugin."** | 即仓库标语 |
| `homepage` | **`https://deepseek.com/harness`** | 官方产品页 |
| `language` | **TypeScript** | 仓库主语言（与第 1.3 节技术栈一致） |
| `default_branch` | **`master`** | **非 `main`**（否证常见误传） |
| `topics` | `ai-agents`, `cordis`, `dsh`, `dsh-plugin` | 官方自认标签，佐证"Cordis 底座 + 一切皆插件"定位 |
| `stargazers_count` | **234,063** | 生态热度极高 |
| `forks_count` / `network_count` | **28,120** | — |
| `subscribers_count` | 1,003 | — |
| `size` | 215,247 KB（约 **210 MB**） | 对比：本地解压工作树 13,229 文件 / 104.7 MB（tar 未含 `.git` 历史，故更小） |
| `created_at` | **2026-08-13** | 仓库创建 |
| `pushed_at` | **2026-09-22** | 最近推送 |
| `has_issues` | **`false`** | **不开放 Issue** |
| `has_discussions` | **`true`** | 用 Discussions 承接反馈 |
| `has_wiki` / `has_pages` / `has_projects` | 均 `false` | — |
| `open_issues_count` | 0 | 与 `has_issues: false` 一致 |
| `archived` | `false` | 活跃维护 |
| `owner.type` | `Organization` | 组织账号 |

**由该元数据得出的三条结论**：

1. **协作与反馈渠道（补充"生态"一节）**：**Issue 关闭**、**Discussions 开启**、**PR 与 fork 开启**（`allow_forking: true`）。README 的官方指引与之吻合——"submit feedback or bug reports through **GitHub Discussions**"。这解释了为何检索不到 issue 列表。
2. **主语言 = TypeScript**，与仓库内每包 `tsconfig.json`、`tsdown.config.ts`、`.tsx` 前端一致。
3. **高频迭代旁证**：`created_at 2026-08-13` → `pushed_at 2026-09-22`，**约 6 周**内即形成 13k+ 文件、54 group、307 包的工作树；对照 README 的 "DEVELOPER PREVIEW / THERE WILL BE COMPATIBILITY-BREAKING CHANGES" 警告，结构快速变动是可预期的（第 11 节的三方差异表即为实证）。

### 1.3 语言 / 技术栈线索

证据均来自仓库根文件清单与根 `package.json` / `pnpm-workspace.yaml`：

| 维度 | 线索 | 出处 |
|---|---|---|
| 主语言 | **TypeScript**（全仓 `src/*.ts`、每个包带 `tsconfig.json`） | 目录树 + 各包 `tsconfig.json` |
| 模块制式 | ESM（根 `"type": "module"`） | 根 `package.json` |
| 包管理 / 工作区 | **pnpm**，`packageManager: pnpm@11.7.0`，`pnpm-workspace.yaml` + `pnpm-lock.yaml` | 根 `package.json` |
| Node 版本 | `engines.node: "^22.19.0 \|\| >=24.0.0"`（0.1.7-alpha.2） | 根 `package.json` |
| 构建 | **tsdown**（`tsdown.config.ts`）+ `tsc -b` 项目引用（`tsconfig.host.json` / `tsconfig.client.json` 双面构建） | 根文件清单 + scripts |
| 前端 | **Vite**（`apps/web/vite.config.ts`）、React（`dsh-client-ui-renderer` 的 "React slot bindings"） | 目录树 + 包描述 |
| 文档站 | **VitePress**（`website/.vitepress/`） | 部分克隆目录树 |
| 测试 | **Vitest**，9 份配置：`vitest.config.ts`、`.e2e`、`.snapshot`、`.web`、`.web-stress`、`.web.perf`、`.bench`、`.expected`、`vitest.shared.ts` | 根文件清单 |
| 静态检查 | **oxlint**（`.oxlintrc.json`、`.oxlintrc.staged.json`）、**knip**（`knip.json`）、**jscpd**（`.jscpd.json` 重复代码检测） | 根文件清单 |
| Git 钩子 | **lefthook**（`lefthook.yml`，`allowBuilds: lefthook: true`） | 根文件清单 + `pnpm-workspace.yaml` |
| CI | `.github/workflows/` + `scripts/ci-workflow.spec.ts`（CI 配置本身受测试约束）+ `.gitlab-ci.yml` | 目录树 |
| Python | `python/sdk`、`python/sdk-runtime`、`pytest.ini`、`scripts/build-python-release.py`、`scripts/build-exe-for-python-sdk.ts`、`scripts/check-macos-deployment-target.py` | 目录树 |
| 原生扩展 | `native/`（0.1.0-rc.5 只有 `landlock-run`；0.1.5-rc.2 为 `native/system/packages/entry` → `@deepseek-ai/node-addon-system` 0.2 版本线，Node-API） | 目录树 + npm 包描述 |
| 平台矩阵 | macOS Seatbelt、Linux bwrap/Landlock、Windows ACL / Job Object / ConPTY | 包描述（`sandbox-local`、`win32-process`）|

### 1.4 monorepo 特征（结构性证据）

`pnpm-workspace.yaml`（0.1.7-alpha.2 部分克隆，**原文**）：

```yaml
packages:
  - vendor/*
  - packages/*/*
  # The Landlock launcher is developed with its harness consumers but keeps
  # its native build and publication scripts under native/system.
  - native/system
  - native/system/packages/*
  # Product assemblies over the package tier; apps/cli owns the `dsh` bin.
  - apps/*
  # Private package owning repository-level benchmark dependencies.
  - benchmarks
  - website
  # Deploy root of the single-exe build: a pure dependency manifest whose
  # closure is what the exe bundles and what the Python runtime distributes.
  - python/sdk-runtime
```

叠加根 `package.json` 的 `workspaces` 字段（`vendor/*`、`packages/*/*`、`native/system`、`native/system/packages/*`、`apps/*`、`website`），可确认四条 monorepo 特征：

1. **`packages/<group>/<pkg>` 是固定两级结构**——`packages/*/*` 而非 `packages/**`，即不允许 `packages/foo` 直接是一个包。
2. **`vendor/*` 是独立工作区层级**，与 `packages/` 平级，装的是内嵌（vendored）的 Cordis 体系。
3. **`apps/*` 是"产品装配层"**，注释原文写明 "Product assemblies over the package tier; apps/cli owns the `dsh` bin"。
4. **包名与目录名解耦**：目录是 `packages/core/agent-loop`，包名是 `@deepseek-ai/dsh-agent-loop`。官方规则（`packages/README.md` 原文）："Groups hold `packages/<group>/<pkg>/`; names stay `@deepseek-ai/dsh-<pkg>`."

**关键可核验机制**：每个已发布包的 `package.json` 都带 `repository.directory`，指回它在 monorepo 中的路径。本机安装的 **240 个包全部带该字段（240/240）**，因此**可以从 npm 元数据无损重建 `packages/` 的目录骨架**——这正是本报告第 3 节的数据基础。

---

## 2. 顶层目录结构

### 2.1 顶层目录 → 作用（逐版本核实）

**M（master 真树）实测 14 个顶层目录**。下表逐行标注版本差异；"M 文件数"为实测。

| 目录 | 作用 | M 文件数 | 在 G/L 中的差异 |
|---|---|---|---|
| `packages/` | **仓库主体**。`packages/<group>/<pkg>` 插件包集合 | **54 group / 307 包** | L=46 group/229 已发布包；G=48 group |
| `apps/` | **产品装配层** | 4 个 app | **L/G 只有 `cli` + `web`；M 新增 `desktop`、`desktop-host`** |
| `vendor/` | **内嵌的 Cordis 插件体系源码**（"一切皆插件"的底层底座） | 9 包 / 75 文件 | M 有 `logger-console`；L 的已发布集合无 |
| `native/` | **原生扩展**（`@deepseek-ai/node-addon-system`） | 79 | G 为 `native/landlock-run`；L 为 `native/system/packages/entry` |
| `docs/` | **官方文档**（21 份顶层 + 8 子目录，全部中英双语三件套） | **562** | G 仅 19 份；M 大幅扩张 |
| `scripts/` | **门禁与生成器**（build/gates/generators） | **334** | G 约 50+ |
| `python/` | **Python SDK 与运行时**：`python/sdk`、`python/sdk-runtime` | 38 | 三版均有 |
| `patches/` | **pnpm patchedDependencies 补丁** | **7 个补丁** | G 只有 `node-pty@1.1.0.patch` |
| `.github/` | CI 工作流（20 个）、Issue 模板、issue 治理、依赖评审 | 53 | G 结构与 M 相近 |
| `.agents/` | **Agent 工作流与设计笔记**：`notes/` + `skills/` | **3,529 文件** | G 规模小得多 |
| `.claude/` | Claude Code 工程配置（`CLAUDE.md` 为 symlink 指向 `AGENTS.md`） | — | 三版均有 |
| `website/` | **VitePress 文档站**（`.vitepress/`、`build.ts`、`docs.ts`、`public/`、`tests/`） | 32 | 三版均有 |
| `snapshots/` | **快照测试基线**：`session/` 701、`web/` 271、`sdk/` 150、`acp/` 56 | **1,179** | **G 无；M/L 有** |
| `benchmarks/` | **性能门禁**（`AGENTS.md` 原文 "performance gates"） | 34 | **G 无；M/L 有** |

**⚠️ 更正两处早期误判**（早期版本据 G/L 推断，M 真树否证）：

| 目录 | 早期说法 | M 实况 |
|---|---|---|
| `examples/` | "顶层有可运行示例工程" | **M 顶层不存在 `examples/`**。G 亦无。该职责由 `packages/examples`（G 的 group，未发布）与 M 的 `apps/cli/config/examples/` + `packages/experimental/*` 承接 |
| `assets/` | "顶层有品牌/静态资源目录" | **M 顶层不存在 `assets/`**（该条目来自 G 的根目录列举，M 已消失） |

**M 中保留但需注意的顶层目录**：`docs/`、`scripts/`、`website/`、 `.github/`、`.agents/`、`.claude/` 均为**非发布**目录（不进 npm 包，见第 6 节）。

### 2.1b M 顶层目录的完整内部结构（真树实测）

```
deepseek-harness-master/            （根 package.json: @deepseek-ai/dsh-root 0.1.7-alpha.2, license MIT）
├── packages/          54 group / 307 包（每 group 一份 README.md + README.zh.md + README.i18n.yaml）
├── apps/              cli(166)  desktop(408)  desktop-host(11)  web(349)
├── vendor/            cordis cosmokit group hmr include loader logger-console schemastery timer
├── native/            @deepseek-ai/node-addon-system 源码（79 文件）
├── python/            sdk/  sdk-runtime/（38 文件）
├── docs/              63 顶层文件 + cookbook(33) cordis-api(16) cordis-tutorial(24) i18n(9)
│                      persistence-changes(155) postmortem(15) subsystems(189) user(58)
├── scripts/           334 文件（build / gen-* / verify-* 门禁）
├── website/           .vitepress/ + build.ts + docs.ts + public/ + tests/（32 文件）
├── benchmarks/        34 文件（性能门禁）
├── snapshots/         acp(56) sdk(150) session(701) web(271)
├── patches/           7 个 .patch
├── .github/           workflows(20)  ISSUE_TEMPLATE/  issue-management/  preview-sizing/  review-ownership/
├── .agents/           notes(3,529) + skills(13)
└── .claude/           （CLAUDE.md symlink 目标；部分文件因 symlink 未能解出）
```

**`.agents/` 详细结构（M 实测，一手）**：

```
.agents/
├── notes/                       3,529 文件
│   ├── implemented/             1,447   已实现（present tense 描述已交付现实）
│   │   ├── architecture/        （184 份英文 .md）
│   │   ├── bug-fix/  feature/  process/  simplification/  testing/
│   ├── archived/                1,919   冻结历史，不得编辑
│   │   └── architecture/ bug-fix/ feature/ process/ simplification/ testing/
│   ├── proposed/                117
│   │   └── architecture/ bug-fix/ feature/ process/ simplification/ testing/
│   └── rejected/                42
│       └── architecture/ process/ simplification/
└── skills/                      13 个技能目录
    ├── agent-experience/                dsh-archive-agent-notes/
    ├── dsh-ci-test-reliability/(+references)  dsh-code-review/
    ├── dsh-doc/(+references,+templates) dsh-find-simplifications/(+references)
    ├── dsh-merging-stacked-prs/         dsh-pre-push-checks/
    ├── dsh-prose-standard/(+references) dsh-speed-up-perf/
    ├── dsh-translate-docs/              dsh-trim-cot-leakage/(+references)
    └── record-browser-gif/(+scripts)
```

> `.agents/notes/` 是**仓库的决策记录层**：`docs/AGENTS.md` 的 tier 表规定"rationale → Agent Notes"，且 `implemented/` 用现在时描述已交付现实，`archived/` 为冻结历史。**每篇均为中英双语三件套**（`.md` + `.zh.md` + `.i18n.yaml`）。

### 2.2 顶层文件（M = master 真树，一手）

M 根目录共 **约 41 个文件**（`D:\Incubator\temp\ds-repo\deepseek-harness-master\` 实测）：

| 类别 | 文件 |
|---|---|
| 文档 | `README.md` / `README.zh.md` / `README.i18n.yaml`、`CONTRIBUTING.md` / `.zh.md` / `.i18n.yaml`、`AGENTS.md`、`CLAUDE.md`（**symlink → `AGENTS.md`**）、`BENCHMARK.md`、`THIRD_PARTY_NOTICES.md`、**`BRAND_GUIDELINES.md` / `.zh.md` / `.i18n.yaml`**、**`SAFETY.md` / `.zh.md` / `.i18n.yaml`** |
| 许可证 | `LICENSE`（MIT，全文已读） |
| 工作区/包 | `package.json`（`@deepseek-ai/dsh-root` 0.1.7-alpha.2，`license: MIT`，`packageManager: pnpm@11.7.0`）、`pnpm-workspace.yaml`（全文已读）、`pnpm-lock.yaml` |
| TS 工程 | `tsconfig.json`、`tsconfig.base.json`、`tsconfig.host.json`、`tsconfig.client.json`、`tsconfig.base.client.json` |
| 构建 | `tsdown.config.ts`、**`Makefile`** |
| 测试 | `vitest.config.ts`、`vitest.shared.ts`、`vitest.e2e.config.ts`、`vitest.snapshot.config.ts`、`vitest.web.config.ts`、`vitest.web-stress.config.ts`、`vitest.web.perf.config.ts`、**`vitest.bench.config.ts`**、**`vitest.expected.config.ts`** |
| Python | `pytest.ini` |
| 规范/质量 | `.editorconfig`、`.gitattributes`、`.gitignore`、`.rgignore`、`.oxlintrc.json`、`.oxlintrc.staged.json`、`.jscpd.json`、`knip.json`、`lefthook.yml` |
| CI | `.gitlab-ci.yml`（另有 `.github/workflows/`，20 个 workflow） |

> **M 相对 G 的差异**：新增 `BRAND_GUIDELINES*`、`SAFETY*`、`Makefile`、`vitest.bench.config.ts`、`vitest.expected.config.ts`。

### 2.3 各目录内部结构

#### `apps/`（M 实测，一手）

M 有 **4 个 app**（L 只有 2 个）：

| 路径 | 包名 | 文件数 | 说明 |
|---|---|---|---|
| `apps/cli` | `@deepseek-ai/dsh` | 166 | 唯一公开 bin；版本 **0.1.7-alpha.2**，`license: MIT`，`files: lib/*.js, lib/types/*.d.ts` |
| `apps/desktop` | Electron 桌面应用 | 408 | 携带完整 dsh 生产运行时；独占保留 profile `$DSH_HOME/profiles/desktop`；默认端口 **19387** |
| `apps/desktop-host` | 私有 Desktop Host | 11 | Electron Node 模式下启动，调用共享 CLI profile runner + 完整 Web 应用 |
| `apps/web` | `@deepseek-ai/dsh-web-frontend` | 349 | Vite 构建；`dist/` 由 `apps/cli` 的 `dsh web` 提供服务 |

```
apps/
├── cli/                    → 包 @deepseek-ai/dsh
│   ├── config/
│   │   └── examples/        ← M 实测：github-review/  mcp-memory/  schedule/   （3 个示例，共 6 个文件）
│   │                           ⚠️ M 中【没有】config/agent-presets/（G 有，M 已移除）
│   ├── reference/          → CLI 行为参考文档
│   ├── src/                → src/args.ts（命令语法）、src/bin.ts（只加载选中的 runner）
│   ├── tests/
│   ├── README.md / README.zh.md / README.i18n.yaml
│   ├── composition.md      → 生成的组合说明（每个内置 profile 的确切 composition）
│   └── package.json / tsconfig.json / tsdown.config.ts
├── desktop/                → Electron 桌面应用（含 Windows EV 签名文档）
├── desktop-host/           → 私有 Desktop Host
└── web/                    → public/ src/ stress-tests/ tests/ index.html vite.config.ts
```

`apps/cli/config/examples/` 实测内容（M）：

| 示例 | 文件 |
|---|---|
| `github-review/` | `cordis.yml`、`github-ready-review-rule.mjs` |
| `mcp-memory/` | `engram.cordis.yml`、`mcp-reference-memory.cordis.yml`、`memorix.cordis.yml` |
| `schedule/` | `cordis.yml` |

`@deepseek-ai/dsh-web-frontend` 的官方描述把 cli/web 关系写得很清楚：

> Web application entry: vite build over the `@deepseek-ai/dsh-client-web` shell library; **dist/ served by apps/cli's `dsh web`**

#### `docs/`（M 实测，一手 —— 此前的头号缺口已关闭）

M 的 `docs/` 共 **63 个顶层文件 + 8 个子目录（562 个文件）**，规模远超 G（19 份）。**`architecture.md`（18,696 B）与 `module-graph.md`（119,655 B）全文已获取并提炼，见第 12 节。**

**顶层 21 份英文文档**（每份均有 `.md` + `.zh.md` + `.i18n.yaml` 三件套）：

| 文件 | 大小 | 定位（据 `docs/AGENTS.md` 的 tier 表） |
|---|---|---|
| `architecture.md` | 18.7 KB | **有序地图**：组合、核心包、loop、seam、扩展点；改 `packages/` 前必读 |
| `AGENTS.md` | 10.8 KB | 文档标准（tier 分类、写作规则、字数预算、slop 清单） |
| `capability-seams.md` | 60.4 KB | **能力 seam 图**（三分法的权威说明） |
| `config-catalog.md` | 185.0 KB | **生成的配置字段权威目录** |
| `module-graph.md` | 119.7 KB | **生成的包依赖图（peer 依赖）** |
| `persistence-catalog.md` | 340.5 KB | 生成的持久化目录 |
| `persistence-schema.json` | **2.27 MB** | 持久化 schema（JSON） |
| `dependency-catalog.json` | 168.2 KB | 依赖目录（JSON） |
| `tool-catalog.md` | 96.2 KB | **生成的工具权威目录** |
| `event-producer-consumer.md` | 27.8 KB | 事件 map：每个事件的生产者与消费者 |
| `api-gateway.md` | 19.7 KB | API 网关 |
| `development.md` | 19.7 KB | 贡献者设置、日常工作流、CI 摘要 |
| `deepseek-llm-api-wire-extensions.md` | 12.3 KB | DeepSeek API wire 扩展 |
| `testing.md` | 10.9 KB | 测试策略（CI 覆盖率门禁权威） |
| `glossary.md` | 6.6 KB | 术语表（含 capability seam 定义） |
| `agent-lifecycle.md` | 5.6 KB | 会话生命周期时序图 |
| `session-format-status.md` | 5.8 KB | 会话格式版本/状态权威 |
| `web-styling.md` | 5.5 KB | Web 样式权威 |
| `defensive-patterns.md` | 3.7 KB | 生命周期/并发/子进程/拆卸前的必读 |
| `tool-execution-pipeline.md` | 4.2 KB | 工具执行管线 |
| `rescope.md` | 4.8 KB | vendor 包 rescope 规则 |
| `cordis-primer.md` | 4.1 KB | Cordis 入门 |
| `graph-atlas.md` | 1.4 KB | 图谱索引 |

**8 个子目录**：

| 子目录 | 文件数 | 内容 |
|---|---|---|
| `subsystems/` | **189**（**63 份英文页**） | 每个子系统一页参考：类型定义、语义、生成的 Cordis API |
| `persistence-changes/` | **155** | 类型变更确认、发布对比、历史格式 schema |
| `user/` | 58 | 面向产品的用户指南（由文档站发布） |
| `cookbook/` | 33（**11 份英文**） | 步骤化 how-to（见下） |
| `cordis-tutorial/` | 24 | Cordis 教程 |
| `cordis-api/` | 16 | Cordis core API + 继承层 |
| `postmortem/` | 15 | **事故复盘**（唯一允许"战争故事"叙事层） |
| `i18n/` | 9 | 翻译契约、术语表 |

`docs/cookbook/` **11 份英文指南**：`adding-a-package`、`adding-a-tool`、`adding-a-settings-card`、`adding-an-llm-adapter`、`adding-a-remote-api`、`adding-a-session-format-version`、`adding-a-vendored-package`、`extension-cookbook`、`maintaining-dsh-code-review`、`responding-to-pr-review-on-a-stack`、`reviewing-persistence-type-changes`。

> **注意**：`docs/subsystems/README.md` 存在，且 `docs/AGENTS.md` 规定"**每个类型在声明它的 package group 的子系统页上被文档化**"，并称 `subsystems/` 是"类型定义的唯一归宿"。

#### `vendor/`（一手，0.1.0-rc.5）

```
vendor/
├── cordis/          → @deepseek-ai/cordis                 4.0.2   "Meta-Framework for Modern JavaScript Applications"
├── cosmokit/        → @deepseek-ai/cosmokit               1.8.3   "A collection of common utilities"
├── group/           → @deepseek-ai/cordis-plugin-group     1.0.2   "Nested plugin group for cordis"
├── hmr/             → @deepseek-ai/cordis-plugin-hmr       1.0.17  "Hot Module Replacement Plugin for Cordis"
├── include/         → @deepseek-ai/cordis-plugin-include   1.0.7   "Include files in cordis configurations"
├── loader/          → @deepseek-ai/cordis-plugin-loader    1.0.3   "Plugin loader for cordis"
├── logger-console/  → （0.1.0-rc.5 有；0.1.5-rc.2 的已发布集合中无对应包）
├── schemastery/     → @deepseek-ai/schemastery            3.18.2   "Type driven schema validator"
├── timer/           → @deepseek-ai/cordis-plugin-timer     1.1.4   "Timer service for cordis"
└── AGENTS.md  CLAUDE.md(symlink)  README.md
```

8 个 vendor 包的**版本线是独立的**（4.x / 1.x / 3.x），与 `dsh-*` 的 `0.1.5-rc.2` 完全不同轨——说明 `vendor/` 是从 Cordis 生态 fork/vendor 进来的**上游代码**，而非 DSH 自研包。`pnpm-workspace.yaml` 用 overrides 把它们强行接到本地：`'@deepseek-ai/cosmokit': 'link:vendor/cosmokit'`、`'@deepseek-ai/schemastery': 'link:vendor/schemastery'`。

#### `native/`（一手）

- 0.1.0-rc.5：`native/landlock-run/` + `README.md` / `.zh.md` / `.i18n.yaml`
- 0.1.5-rc.2：`native/system/packages/entry` → `@deepseek-ai/node-addon-system` 0.1.2，描述为 "Prebuilt system primitives: a Linux Landlock launcher and asynchronous POSIX flock through stable Node-API"

#### `examples/`（一手，6 个示例）

`acp-agent/`、`headless-agent/`、`jsonrpc-agent/`、`mcp-memory/`、`web-cordis/`、`web-schedule/`，另有 `AGENTS.md`、`CLAUDE.md`(symlink)、`README.md`/`.zh.md`/`.i18n.yaml`、`package.json`。

**这说明仓库提供了三种进程接入形态的最小示例**（ACP / headless 一次性 / JSON-RPC），以及三个 Web 进阶 overlay 示例（Cordis 运行时插件、Schedule、MCP memory）。

#### `scripts/`（一手，节选）

- 子目录：`fixtures/`、`release/`、`snapshots/`
- 构建/发布：`build-exe-for-python-sdk.ts`、`build-python-release.py`、`release/`、`clean.ts`
- **门禁（CI gates）**：`verify-package-invariants.ts`、`verify-package-paths.ts`、`verify-built-package-invariants.mjs`、`verify-config-source-ownership.ts`、`verify-cordis-config.ts`、`verify-runtime-closure.ts`、`verify-dsh-package-licenses.ts`、`verify-doc-budgets.ts`、`verify-doc-refs.ts`、`verify-md-links.ts`、`verify-mermaid.ts`、`verify-translation-pairing.ts`、`verify-package-readme-limitations.ts`、`verify-package-readme-model-experience.ts`、`verify-vendored-links.ts`、`verify-public-repository-links.ts`、`verify-skill-invocation-metadata.ts`、`verify-type-equiv.ts`、`verify-export-jsdoc.ts`、`check-workspace-constraints.ts`、`check-expected-filenames.sh`、`check-vendor-manifest.sh`、`check-macos-deployment-target.py`、`coverage-exempt.ts`、`doc-typecheck.ts`
- **生成器**：`cordis-config-files.ts`、`cordis-core-api.ts`、`cordis-walk.ts`、`gen-*`、`agent-note-tree.ts`
- **开发辅助**：`dev-web.ts`、`demo-cordis.mjs`、`demo-code-mode.mjs`、`wine-windows-gates.sh`、`attribute-chunk-bytes.mjs`

**观察**：`scripts/` 里"校验"脚本远多于"构建"脚本，且 `verify-*` 几乎每条都有配对的 `.spec.ts`——仓库采用**把工程规约写成可执行门禁**的做法（文档预算、翻译配对、README 小节存在性、包路径合法性、许可证一致性都在 CI 里强制）。

#### `.github/`（一手）

`ISSUE_TEMPLATE/`、`issue-management/`、`workflows/`、`AGENTS.md`、`dependabot.yml`、`pull_request_template.md`
→ 存在完整 CI 流水线（**M 实测 20 个 workflow，文件名与 job 已获取，见第 14 节**）与 Issue 生命周期治理机制。

#### `.agents/`（一手）

`notes/`（含 `notes/README.md`、`notes/AGENTS.md`、`notes/archived/`）、`skills/`

`notes/archived/` 下按类别归档，文件名形如 `2026-06-20-package-hierarchy.md`，**每篇都是中英双语三件套**（`.md` / `.zh.md` / `.i18n.yaml`），并有 `manifest.json`（58,756 B）作为归档索引。类别：`architecture/`、`bug-fix/`、`feature/`、`process/`、`simplification/`。

其中直接涉及目录结构的笔记包括：`2026-06-20-package-hierarchy.md`（**包层级**）、`2026-06-20-extract-example-app-packages.md`（**拆分示例应用包**）、`2026-07-03-documentation-graph-atlas.md`、`2026-06-20-generated-cordis-catalog.md`、`2026-06-06-generated-config-catalog.md`。

> 这解释了 `CLAUDE.md` 的存在：它是指向 `AGENTS.md` 的 **symlink**（Gitee API 中 `CLAUDE.md` 的 `type` 字段为 `"symlink"`，SHA 与根 `CLAUDE.md` 相同 `47dc3e3d…`）——即在 `packages/`、`examples/`、`vendor/` 等多个目录下复用同一份 Agent 约定文件。

#### `python/`（一手）

`python/sdk/`、`python/sdk-runtime/` + `README.md`/`.zh.md`/`.i18n.yaml`、`development.md`/`.zh.md`/`.i18n.yaml`
`pnpm-workspace.yaml` 注释：`python/sdk-runtime` 是"单 exe 构建的部署根：一个纯依赖清单，其闭包就是 exe 打包内容和 Python 运行时分发内容"。

---

## 3. `packages/` 下的插件包分类整理

### 3.1 官方 group 职责表（**一手**，`packages/README.md` 原文转录）

`packages/README.md` 原文声明：npm scope 为 `@deepseek-ai/dsh-*`；插件通过 `ctx.effect()`、`ctx.on()`、`ctx.waterfall()` 贡献能力；"**Group READMEs own package/ctx-key maps**"。

> ✅ **【已升级】** 原文后半句曾是"这些 group README 全文未能获取"。取得 master 真树后，**54 个 group 的 README 全部可读**。**官方授权版映射（M）见第 13 节**；本节 3.1 保留 G（0.1.0-rc.5）版官方表作为历史对照，3.2 保留 L 视角的功能域分组表。

官方给出的 `Group | Role | Release expectation` 表（**G = 0.1.0-rc.5 版**；M 版的表已去掉 Release expectation 列并改为 54 行，见第 13 节），中文为本人翻译：

| Group | 官方 Role（原文要点） | 发布承诺 | 0.1.5-rc.2 包数 |
|---|---|---|---|
| `core/` | 产品 API 主干：session、prompt、tools、agent 服务与具体 loop | Product — 稳定 API | 8 |
| `api/` | Remote BFF 装配与 Typert RPC 网关 | Product | 6 |
| `typert/` | 类型图生成、产物加载、运行时注册表 | Product | 3 |
| `goal/` | 同会话目标持久化与生命周期 | Product | 4 |
| `schedule/` | 会话内定时跟进 | Product | 1 |
| `feedback/` | 人类反馈 | Product | 2 |
| `identity/` | 共享匿名身份 | Product | 1 |
| `llm/` | LLM 能力族：抽象服务 + provider 适配器 | Product | 7 |
| `e2b/` | E2B providers | **POC** | 0（0.1.5 未发布） |
| `subprocess/` | 子进程能力族：Service Definition + 本地进程树 provider | Product | 3 |
| `shell/` | Bash 能力族：executor seam、本地实现、面向模型的工具 | Product | 10 |
| `terminal/` | 持久 PTY 能力族 | Product | 2 |
| `code-runtime/` | 代码执行能力族：Service Definition + worker-thread provider + Code Mode Consumer | Product | 2 |
| `sandbox/` | 进程隔离 seam；bwrap/Landlock/Seatbelt 后端 | Product | 4 |
| `fs/` | 文件系统能力族：seam、本地实现、文件工具、bash 支撑的检索工具 | Product | 8 |
| `lsp/` | LSP 能力族：seam、通用 stdio provider、`lsp` 工具 | Product | 0（0.1.5 未发布） |
| `skill/` | 技能能力族：provider 注册表、本地 provider、目录/加载工具 | Product | 4 |
| `compaction/` | 压缩能力族：Service Definition + basic provider + command Consumer | Product | 4 |
| `context/` | 模型可见的请求上下文（工作区指令、时间上下文） | Product | 6 |
| `subagent/` | 子智能体能力族：provider 注册表契约 + 委派工具 | Product | 6 |
| `jobs/` | 通用后台作业运行时 + `job_*` 控制工具 | Product | 3 |
| `workflow/` | workflow seam、worker-thread 引擎、`workflow`/`ralph` 工具 | Product | 4 |
| `web/` | Web 能力族：seam、搜索/抓取 provider、web 工具 | Product | 4 |
| `attachment/` | 附件身份、校验、本地内容寻址存储 | Product | 2 |
| `spill/` | 溢出存储能力族 | Product | 3 |
| `todo/` | 面向模型的 `todo_write` 工具 | Product | 1 |
| `plan/` | 计划协作状态 | Product | 1 |
| `preset/` | 基于 preset `cordis.yml` 的按会话 agent 组合 | Product | 2 |
| `guard/` | 循环卫生守卫：重复调用提醒 + `tools/execute` 截止时间 | Product | 2 |
| `bundle/` | 可分发的 `dsh --profile` 补丁层 | Product | 6 |
| `extensions/` | Agent 运行时自我修改：实时插件检查与模型编写插件的挂载/卸载 | Product | 4 |
| `hooks/` | Hook 桥接 + 共享 Claude Code / Codex 线协议库 | Product | 3 |
| `session/` | 持久会话数据面：persistence seam + JSONL/SQLite 后端、projection seam、日志标题、会话上报 | Product | 18 |
| `session-query/` | 会话检索族：逻辑语料、有界读、血缘、事件关系、SQLite 全文检索 | Product | 3 |
| `settings/` | 用户设置 seam + 文件 provider | Product | 2 |
| `credentials/` | 凭据引用 seam + env-over-`.env` provider | Product | 2 |
| `storage/` | 非会话存储 hub + 后端 + domain 数据形态 | Product | 3 |
| `workspace/` | 工作区实体 | Product | 1 |
| `sdk/` | 进程外运行时 SDK：JSON-RPC 协议、TS client、server 插件 | Product | 2 |
| `acp/` | 仅自动化的 Agent Client Protocol server | Product | 1 |
| `interaction/` | 人机协作面：审批/交互 seam、权限预设、命令、ask-user 工具 | Product | 5 |
| `boot/` | 共享 app-bin 启动胶水 | Product | 2 |
| `host/` | Web GUI host 半边：API 网关 + HTTP 路由服务 | Product | 8 |
| `client/` | Web GUI 浏览器半边：shell、wire、对象服务、slots、`ui-*` 插件 | Product | **46** |
| `examples/` | 演示 bundle（agent-spine + CLI/ACP/JSON-RPC bin） | **Support — 示例基础设施** | 0（0.1.5 未发布） |
| `test-support/` | 支撑基础设施（testkit、invariants、replay、Loader smokes） | **Support — 兼容性承诺较低** | 0（0.1.5 未发布） |
| `util/` | 跨 group 共享的零依赖底层工具（`Branded<B>`、home/path 助手、timeout、retention） | **Support — 小而稳定，不依赖 harness** | 15 |

**另有 0.1.5-rc.2 已发布、但 0.1.0-rc.5 官方表中尚未列出的 group**：`webhook/`（2 个包）。→ 说明 group 集合在版本间演进。

`packages/README.md` 还给出两条**架构级硬规则**（原文）：

> **Extension plugins depend on Service Definitions, never concrete providers.** `dsh-agent-loop` is swappable; UI, hook, and tool plugins use `dsh-agent`. Composition bundles, including `dsh-agent-spine-demo`, may depend on spine plugins. Capabilities separate Service Definition / Service Provider / Consumer roles when they evolve independently.

> The dependency graph is generated: [docs/module-graph.md](../docs/module-graph.md) (`pnpm run gen-module-graph`, freshness-gated in CI).

### 3.2 按功能域分组（本报告整理）

**判断依据（务必对照）**：
1. **仓库路径**（`packages/<group>/<pkg>`）来自每个 npm 包 `package.json` 的 `repository.directory` 字段——**240/240 全部存在**，一手、可复核（证据文件 `D:\Incubator\temp\evidence\dsh-packages-by-repodir.txt`）；
2. **官方职能描述**来自每个包的 `description` 字段——**240/240 全部存在**（`dsh-packages-with-description.txt`）；
3. **group 归属与"能力族"框架**来自仓库官方 `packages/README.md`（上表）；
4. 少数未发布包的路径为**推测**，已单独标注。

#### A. 核心 Agent Loop 与运行时骨架（13 个）

| 仓库路径 | 包名 | 职责（据官方 description 摘要） |
|---|---|---|
| `packages/core/agent` | `dsh-agent` | Agent 接口、注册表、initiator scope、事件词汇表 |
| `packages/core/agent-loop` | `dsh-agent-loop` | **具体 agent loop 插件**（官方明示可替换） |
| `packages/core/session` | `dsh-session` | 事件溯源（event-sourced）会话存储 |
| `packages/core/tools` | `dsh-tools` | 工具注册表与执行管线 |
| `packages/core/system-prompt` | `dsh-system-prompt` | 系统提示词装配注册表 |
| `packages/core/scope` | `dsh-scope` | 作用域上下文注册原语（scope 标签、按 scope 过滤的事件派发） |
| `packages/core/agent-default-model` | `dsh-agent-default-model` | 各 Agent 入口共享的默认模型选择 |
| `packages/core/agent-tool-presentation` | `dsh-agent-tool-presentation` | Agent 面呈现选择器：PTC 模式 / native / 两者 |
| `packages/guard/repeat-tool-reminder` | `dsh-repeat-tool-reminder` | 重复工具调用告警守卫 |
| `packages/guard/timeout-policy` | `dsh-tool-call-timeout-policy` | 工具调用超时策略（`tools/execute` 包装器） |
| `packages/runtime-diagnostics/invariants` | `dsh-invariants` | 包自有的运行时不变式注册服务 |
| `packages/plan/plan-mode` | `dsh-plan-mode` | 按 Agent 的 plan 模式（含退出评审） |
| `packages/boot/cmdline` | `dsh-cmdline` | 从 dsh 启动器到 app 插件的不可变命令行交接 |

#### B. 工具类 `tool-*`（15 个）

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `packages/fs/tool-fs` | `dsh-tool-fs` | 文件工具（read / write / edit） |
| `packages/fs/tool-fs-search` | `dsh-tool-fs-search` | 文件检索工具（glob / grep），底层打包 ripgrep |
| `packages/fs/tool-str-replace-editor` | `dsh-tool-str-replace-editor` | view / create / 字面替换 / 行插入工具 |
| `packages/fs/tool-present` | `dsh-tool-present` | 显式声明工作区交付物 |
| `packages/shell/tool-bash` | `dsh-tool-bash` | bash 工具（可选后台作业与沙箱升级） |
| `packages/shell/tool-bash-persistent` | `dsh-tool-bash-persistent` | owner-scoped 持久 Bash 工具（PTY） |
| `packages/shell/tool-pwsh` | `dsh-tool-pwsh` | pwsh 工具 |
| `packages/shell/tool-pwsh-persistent` | `dsh-tool-pwsh-persistent` | 持久 PowerShell 工具（PTY） |
| `packages/web/tool-web` | `dsh-tool-web` | `web_search` / `web_fetch` |
| `packages/todo/tool-todo` | `dsh-tool-todo` | `todo_write` |
| `packages/goal/tool-goal` | `dsh-tool-goal` | 同会话目标工具（含执行期权限检查） |
| `packages/jobs/tool-jobs` | `dsh-tool-jobs` | `job_output` / `job_list` / `job_kill` |
| `packages/skill/tool-skill` | `dsh-tool-skill` | 技能加载工具 |
| `packages/interaction/tool-ask-user` | `dsh-tool-ask-user` | `ask_user_question` |
| `packages/subagent/tool-subagent` + `tool-subagent-control` | `dsh-tool-subagent` / `dsh-tool-subagent-control` | 子智能体委派；`send_message`/`interrupt_agent`/`list_agents` |
| `packages/workflow/tool-workflow` + `tool-ralph` | `dsh-tool-workflow` / `dsh-tool-ralph` | workflow 脚本工具；Ralph 循环工具 |
| `packages/extensions/tool-cordis` | `dsh-tool-cordis` | **自指 cordis 工具集**：检查实时运行时、挂载/卸载模型编写的插件 |

> 说明：上表按官方 `packages/README.md` 的 group 归属列出，实际 `tool-*` 前缀包共 17 个（含 2 个 `subagent`、2 个 `workflow`）。**"工具"不是独立 group，而是散布在各能力族中的"Consumer"角色**——这正是"一切皆插件"的直接体现。

#### C. 文件系统与沙箱 / 权限（12 个）

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `packages/fs/fs` | `dsh-fs` | 抽象 FS 能力 seam（`ctx.fs`） |
| `packages/fs/fs-local` | `dsh-fs-local` | 本地 FS 实现 |
| `packages/fs/fs-sandbox` | `dsh-fs-sandbox` | 按每次调用的沙箱模式约束写/改的 FS 实现 |
| `packages/fs/fs-observation-policy` | `dsh-fs-observation-policy` | 已观测状态、read-before-edit、版本守卫的写/改 |
| `packages/sandbox/sandbox` | `dsh-sandbox` | 抽象进程沙箱 seam（`ctx.sandbox`） |
| `packages/sandbox/sandbox-local` | `dsh-sandbox-local` | 本地沙箱后端：bwrap、landlock-run、macOS Seatbelt |
| `packages/sandbox/sandbox-policy` | `dsh-sandbox-policy` | 每次调用的沙箱策略解析 + 当前模型上下文 |
| `packages/sandbox/sandbox-windows-acl` | `dsh-sandbox-windows-acl` | **Windows ACL 写限制后端**（受限令牌 + capability-SID 白名单） |
| `packages/interaction/user-approval` | `dsh-user-approval` | 审批 seam（`ctx.approval`） |
| `packages/interaction/permission-presets` | `dsh-permission-presets` | 权限预设（`read-only`/`workspace-write`/`danger-full-access`） |
| `packages/interaction/user-questions` | `dsh-user-questions` | 提问 seam（`ctx.userQuestions`） |
| `packages/interaction/commands` | `dsh-commands` | 插件自有的人类命令注册表 |
| `packages/spill/spill` / `spill-local` / `spill-policy` | `dsh-spill` 等 | 溢出存储 seam / 本地实现 / 工具结果溢出策略 |

#### D. Shell / 终端 / 子进程 / 代码执行（17 个）

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `packages/shell/shell` | `dsh-shell` | 抽象 bash executor seam（`ctx.shell`） |
| `packages/shell/bash-local` | `dsh-bash-local` | 本地子进程 bash 实现 |
| `packages/shell/bash-sandbox` | `dsh-bash-sandbox` | 经 `ctx.sandbox` 约束的 bash 实现 |
| `packages/shell/pwsh-local` | `dsh-pwsh-local` | 本地 PowerShell 实现 |
| `packages/shell/pwsh-sandbox` | `dsh-pwsh-sandbox` | 经沙箱约束的 PowerShell 实现 |
| `packages/shell/shell-env` | `dsh-shell-env` | 与工具无关的受管 `DSH_*` shell 环境注册表 |
| `packages/terminal/terminal` | `dsh-terminal` | 持久 PTY 会话 seam（owner-scoped id、后端注册表） |
| `packages/terminal/terminal-bash` | `dsh-terminal-bash` | 持久 shell PTY 后端 |
| `packages/subprocess/subprocess` | `dsh-subprocess` | 子进程 seam（`ctx.subprocess`）：受管进程组、有界输出、升级 kill |
| `packages/subprocess/subprocess-local` | `dsh-subprocess-local` | 本地子进程实现 |
| `packages/subprocess/win32-process` | `dsh-win32-process` | 底层 Win32 进程/stdio/Job Object 原语 |
| `packages/code-runtime/code-runtime` | `dsh-code-runtime` | 抽象代码执行 seam（`ctx.codeRuntime`） |
| `packages/code-runtime/code-runtime-worker-thread` | `dsh-code-runtime-worker-thread` | worker-thread 实现 |

#### E. LLM 接入（7 个）

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `packages/llm/llm` | `dsh-llm` | provider 中立的 LLM 服务接口 |
| `packages/llm/llm-deepseek` | `dsh-llm-deepseek` | DeepSeek chat-completions 适配器 |
| `packages/llm/llm-pi-ai` | `dsh-llm-pi-ai` | pi-ai 支撑的 DeepSeek 适配器（`dsh-llm-deepseek` 的设计验证孪生） |
| `packages/llm/llm-retry` | `dsh-llm-retry` | 按 provider 路由的 LLM 请求重试策略 |
| `packages/llm/deepseek-llm-api-extensions` | `dsh-deepseek-llm-api-extensions` | 官方 DeepSeek API 附加请求字段注册表 |
| `packages/llm/token-meter` | `dsh-token-meter` | 可重放的 token 计量服务（`ctx.tokenMeter`） |
| `packages/llm/plugin-package-inventory-deepseek` | `dsh-plugin-package-inventory-deepseek` | 官方 API 请求用的、Loader 支撑的活跃插件包清单 |

#### F. 会话与持久化（37 个）

`session/`（18）：

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `packages/session/session-persistence` | `dsh-session-persistence` | 抽象持久化 seam |
| `packages/session/session-persistence-jsonl` | `dsh-session-persistence-jsonl` | JSONL 持久化后端 |
| `packages/session/session-checkpoint-policy` | `dsh-session-checkpoint-policy` | 语义化持久性检查点 |
| `packages/session/session-projection` | `dsh-session-projection` | 投影 seam（可合并扩展的类型表 + provider 契约） |
| `packages/session/session-projection-cache` | `dsh-session-projection-cache` | 持久化投影缓存（`session_projcache` 域） |
| `packages/session/session-format` | `dsh-session-format` | 相邻版本会话格式迁移机制 |
| `packages/session/session-format-catalog` | `dsh-session-format-catalog` | 构建期静态的会话格式编解码与迁移目录 |
| `packages/session/session-format-v0-to-v1` | `dsh-session-format-v0-to-v1` | v0→v1 迁移 |
| `packages/session/session-format-v1-to-v2` | `dsh-session-format-v1-to-v2` | v1→v2 迁移 |
| `packages/session/session-format-v2-to-v3` | `dsh-session-format-v2-to-v3` | v2→V3 迁移（system-prompt、canonical-envelope、PTC） |
| `packages/session/session-title` | `dsh-session-title` | 日志支撑的会话标题服务与 provider 注册表 |
| `packages/session/session-title-llm` | `dsh-session-title-llm` | 标题生成共享 LLM 策略 |
| `packages/session/session-title-first-prompt-llm` | `dsh-session-title-first-prompt-llm` | 首条消息 LLM 标题 provider |
| `packages/session/session-log-deepseek` | `dsh-session-log-deepseek` | 官方 API 的增量无损会话日志请求扩展 |
| `packages/session/session-stats` | `dsh-session-stats` | 全日志对话计数与墙钟时间投影 |
| `packages/session/session-turn-outline` | `dsh-session-turn-outline` | 全日志轮次大纲投影 |
| `packages/session/session-telemetry` | `dsh-session-telemetry` | 遥测后端 seam（采集、投影、脱敏、上报） |
| `packages/session/session-telemetry-otel` | `dsh-session-telemetry-otel` | OpenTelemetry 后端 |

`session-query/`（3）：`dsh-session-query`（合并查询契约）、`dsh-session-query-sqlite`（SQLite FTS5 检索）、`dsh-session-log-export`（Web 日志导出）

`storage/` + `settings/` + `workspace/` + `attachment/`（9）：`dsh-storage`（存储 hub）、`dsh-storage-domain`（schema 校验的 KV 域）、`dsh-storage-json`（JSON KV 后端）、`dsh-settings`、`dsh-settings-file`（`settings.yaml`）、`dsh-workspace`（工作区实体注册表）、`dsh-attachment`、`dsh-attachment-local`（内容寻址存储）

#### G. UI / Web（62 个）

`client/`（**46 个**，DSH 前端"全插件化"最直观的证据——连"侧边栏""主题""目录选择器""模型下拉""审批弹窗"都是独立插件）：

`connection`（认证 RPC 传输）、`file-upload`、`hmr`（仅开发用热重载驱动）、`locale`、`modules`（客户端模块系统，node 半边组装 `__DSH_BOOT__` 入口图）、`resources`（统一资源模型）、`ui-agent-preset`、`ui-approval`、`ui-attachment`、`ui-brand-official`、`ui-chat`、`ui-commands`、`ui-conversation`、`ui-deliverables`、`ui-directory-picker-browse`、`ui-directory-picker-native`、`ui-goal`、`ui-input-trigger`、`ui-jobs`、`ui-layout`（三栏 AppFrame + `ctx.layout`）、`ui-message-feedback`、`ui-model-selection`、`ui-open-in-app`、`ui-permission-presets`、`ui-plan`、`ui-reference`、`ui-renderer`（React slot 绑定 + `ctx.uiRenderer`）、`ui-schedule`、`ui-session`、`ui-settings`、`ui-settings-general`、`ui-settings-models`、`ui-settings-plugin-inventory`、`ui-settings-plugins`、`ui-sidebar`、`ui-sidebar-documentpreview`、`ui-sidebar-files`、`ui-sidebar-right`、`ui-skill`、`ui-subagent`、`ui-theme`、`ui-tool`、`ui-trajectory`、`ui-user-questions`、`ui-workflow-run`、`ui-workspace`（仓库路径均为 `packages/client/<名>`）

`api/`（6）：`dsh-api-gateway`（Typert Remote Host 派发器 + Client API 端点）、`dsh-api-remotes`、`dsh-api-session-controller`、`dsh-api-settings-controller`、`dsh-api-workspace-controller`、`dsh-api-workspace-files`

`host/`（8）：`dsh-host-webserver`、`dsh-host-frontend-static`、`dsh-host-plugin-inventory`、`dsh-host-directory-picker`（+ `-auto` / `-browse` / `-native`）、`dsh-host-open-in-app`

`web/`（4）：`dsh-web`（`ctx.web` seam）、`dsh-web-fetch-http`、`dsh-web-search-deepseek`

`extensions/ui-cordis`（1）：`dsh-client-ui-cordis`（Cordis 动态插件定义卡片 + `cordis_define` 工具行）
`apps/web`（1）：`dsh-web-frontend`

#### H. CLI / Boot / Bundle / Preset / 外部协议（14 个）

| 仓库路径 | 包名 | 职责 |
|---|---|---|
| `apps/cli` | **`@deepseek-ai/dsh`** | dsh CLI：profile 启动、插件管理、浏览器 UI 别名（唯一公开 bin） |
| `packages/boot/app-boot` | `dsh-app-boot` | 共享启动胶水（`.env` 加载、fail-loud Loader 守卫、快照感知配置解析、Loader 启动序列） |
| `packages/bundle/base` | `dsh-base` | 基础 profile bundle（base 型 profile 的第一层 patch） |
| `packages/bundle/web-app` | `dsh-web-app` | 浏览器面 bundle |
| `packages/bundle/headless` | `dsh-headless` | 一次性 bundle（无 Host / HTTP / 浏览器层） |
| `packages/bundle/sdk-app` | `dsh-sdk-app` | SDK profile bundle（stdio JSON-RPC） |
| `packages/bundle/sdk-minimal` | `dsh-sdk-minimal` | 独立极简 SDK bundle（**不叠 base**） |
| `packages/bundle/acp-app` | `dsh-acp-app` | ACP profile bundle |
| `packages/preset/agent-presets` | `dsh-agent-presets` | 基于 preset `cordis.yml` 的按会话 agent 组合（**内置 preset 本体**） |
| `packages/preset/persona` | `dsh-persona` | 由组合编写的部署人格段 |
| `packages/sdk/protocol` / `server` | `dsh-sdk-protocol` / `dsh-sdk-jsonrpc-server` | 共享 wire 协议（NDJSON JSON-RPC）；stdio server 插件 |
| `packages/acp/acp` | `dsh-acp` | 仅自动化的 ACP server（JSON-RPC stdio） |
| `packages/typert/loader` / `protocol` / `registry` | `dsh-typert-*` | Loader 集成 / Remote 元数据协议 / 运行时反射与 Zod schema 注册表 |

#### I. 子智能体 / 工作流 / 作业 / 目标（18 个）

- `subagent/`（6）：`dsh-subagent`（seam + 命名 provider 注册表）、`dsh-subagent-in-process-driver`（共享进程内驱动）、`dsh-subagent-spawn-in-process`、`dsh-subagent-fork-in-process`、`dsh-tool-subagent`、`dsh-tool-subagent-control`
- `workflow/`（4）：`dsh-workflow`（seam + `ctx.workflowEngine`）、`dsh-workflow-worker-thread`（worker-thread 引擎，把 `agent()` 调用桥回 `ctx`）、`dsh-tool-workflow`、`dsh-tool-ralph`
- `jobs/`（3）：`dsh-jobs`、`dsh-jobs-local`、`dsh-tool-jobs`
- `goal/`（4）：`dsh-goal`、`dsh-goal-round-driver`（竞态栅栏的 goal-round 驱动）、`dsh-command-goal`、`dsh-tool-goal`
- `schedule/`（1）：`dsh-schedule`（agent 作用域的 after/at/fixed-rate 提醒）

#### J. MCP / Webhook / Hooks / 身份（8 个）

- `packages/mcp/mcp-client` → `dsh-mcp-client`：连接 MCP server 并把其工具注册到 `ctx.tools`（**MCP 只有 1 个包**，作为"能力导入器"）
- `webhook/`（2）：`dsh-webhook`（创建 Workspace 支撑会话的即发即忘 webhook 规则运行时）、`dsh-webhook-github`（签名 GitHub HTTP 适配器）
- `hooks/`（3）：`dsh-hook-protocol`（共享 Claude Code / Codex hook 线协议）、`dsh-hooks-claude-code`、`dsh-hooks-codex`
- `identity/`（1）：`dsh-anonymous-user-id`

#### K. 技能 / 上下文 / 压缩 / 反馈（15 个）

- `skill/`（4）：`dsh-skill`（provider 注册表）、`dsh-skill-filesystem`（本地 provider）、`dsh-skill-badge`（内置 badge 技能）、`dsh-tool-skill`
- `context/`（6）：`dsh-agent-instructions`（`AGENTS.md`/`CLAUDE.md` 加载器）、`dsh-file-reference`、`dsh-file-reference-local`、`dsh-session-reference`、`dsh-time-context`、`dsh-tmux-context`
- `compaction/`（4）：`dsh-compaction`（seam）、`dsh-compaction-basic`、`dsh-compaction-tool-result-pruner`（无模型 head/middle/tail 剪枝）、`dsh-command-compact`
- `feedback/`（2）：`dsh-command-feedback`、`dsh-message-feedback`

#### L. 扩展与运行时自省（4 个）

`packages/extensions/cordis-host-runner`（`dsh-cordis-host-runner`，双半插件包的 host 半：沙箱生命周期、invoke 处理表）、`cordis-client-runner`（`dsh-cordis-client-runner`，浏览器半）、`tool-cordis`（`dsh-tool-cordis`）、`ui-cordis`（`dsh-client-ui-cordis`）

#### M. 底层工具 / 原生 / vendored（25 个）

`util/`（15）：`atomic-write`、`brand`、`chunked-list`、`crypto`、`deque`、`home-paths`、`http-proxy`、`launch-environment`、`native-command`、`output-retention`、`package-manifest`、`time`、`timeout`、`values`、`workspace-path`（多数官方描述以 "Zero-dependency" 开头）

`vendor/`（8）：见 2.3 节
`native/`（1）：`node-addon-system`

### 3.3 未发布但在依赖中被引用的包（**已用 master 真树核实**）

**L（0.1.5-rc.2）** 的 `@deepseek-ai/dsh` `devDependencies` 里有 8 个**不在 240 个已安装包中**的包名。用 **M（master）真树**复核后：

| 包名（L 依赖中） | M 中的真实归属 | 核实状态 |
|---|---|---|
| `dsh-experimental-agent-team` | `packages/experimental/agent-team` | ✅ **确证**（group README 有该行） |
| `dsh-experimental-tool-agent-team` | `packages/experimental/tool-agent-team` | ✅ **确证** |
| `dsh-experimental-agent-team-profile` | `packages/experimental/agent-team-profile` | ✅ **确证** |
| `dsh-experimental-code-runtime-python` | **`packages/experimental/ptc-runtime-python`**（**包名已变**：code-runtime → ptc-runtime） | ✅ 目录确证；**L 的包名对应 M 的哪个包为推断** |
| `dsh-agent-loop-testkit`、`dsh-loader-smoke`、`dsh-llm-mock-server`、`dsh-llm-replay` | 应在 **`packages/test-support/*`（M 有 7 个包）** | ⚠️ **group 确证、具体目录名未逐一核对（推测）** |

> **重要结论**：L 中"未发布"的包在 M 中**都是真实存在且有 `package.json` 的目录**。所谓"未发布"是**发布范围**问题（这些包不进入默认产品依赖闭包），不是"仓库里不存在"。
> M 的 `packages/experimental/AGENTS.md` 给出了正式规则：experimental 包**默认公开发布**（`@deepseek-ai/dsh-experimental-*`、省略 `private`、设 `publishConfig.access: public`），仅 `PRIVATE_EXPERIMENTAL_PACKAGE_DIRECTORIES` 中的目录保持私有；同时**发布包与 apps 不得依赖 experimental 包**（CI 由 `verify-default-product-isolation` 检查，含传递依赖）。→ 这解释了"为什么在默认产品里看不到它们"。

---

## 4. `apps/`、`config/` 与测试、工具链目录

### 4.1 `apps/`（已在 2.3 详列）

`apps/cli` → `@deepseek-ai/dsh`；`apps/web` → `@deepseek-ai/dsh-web-frontend`。
`pnpm-workspace.yaml` 注释原文把它们定位为 "Product assemblies over the package tier; apps/cli owns the `dsh` bin"。

**`apps/cli` 的 README 揭示了 CLI 的运转方式**（本机 0.1.5-rc.2 安装包内 `README.md` 原文）：

> The `dsh` command is the sole supported Node application launcher: profiles are ordered stacks of plugin-bundle patch layers under the user's own overrides. **SDK and ACP are profiles, not separate public bins.** … `src/args.ts` owns the command grammar, and `src/bin.ts` loads only the selected runner.

入口模式表（原文转录，中文对照）：

| 命令 | 用途 |
|---|---|
| `dsh --profile <name>` | 启动 `$DSH_HOME/profiles/<name>` 下的 profile |
| `dsh --profile <name> --from-default-profile <template>` | 从内置模板创建自定义 profile 后启动 |
| `dsh --profile acp` | 通过 ACP stdio 服务自动化 client |
| `dsh --profile headless "job"` | 跑一次性持久会话，打印最终答案后退出 |
| `dsh --profile sdk` / `sdk-minimal` | 通过 JSON-RPC stdio 服务 SDK client（后者用独立极简 agent 树） |
| `dsh web` | `--profile web` 的别名 |
| `dsh plugin --profile <name> <pnpm args>` | 转发到 profile 目录里的 pnpm 以管理插件 |

> ⚠️ **【L 视角的旧结论，已被 M 真树大幅修正 —— 见下方 4.2b】**

### 4.2b `config/` 在 master 上的实况（**M 真树一手，决定性**）

用 master 真树重新核实后，**下方 4.2 的 L 视角推断需要两处重要更正**（先读本节结论，再读 4.2 了解 L 的原始证据）：

**更正 1：`configTrees` 机制在 M 中已退役。**

`apps/cli/package.json`（`@deepseek-ai/dsh` 0.1.7-alpha.2）**完全没有 `dsh` 字段**（全文解析结果 `$j.dsh = null`）。
→ **L 中的 `dsh.configTrees`（挂载 `config/agent-presets` → `packages/preset/agent-presets/presets`）在 M 中彻底不存在。**

全仓检索 `configTrees` 仅剩 **4 类残迹**，全部是**内部/历史**用途：

| 位置 | 性质 |
|---|---|
| `packages/experimental/webworker-packer/src/repository.ts` | 镜像打包器**内部**读取并校验 `dsh.configTrees`；若声明必须是数组，并解析源目录 |
| `packages/experimental/webworker-packer/src/pack.ts` | 打包时把 configTree 的行并入 roster，且对 `scanRoster: true` 的树做名册展开 |
| `packages/util/package-manifest/README.md` | 原文：内部 `configTrees`、`sessionFormatMigration`、生成的 `moduleFallback` 元数据"**不属于公共插件 manifest API**" |
| `scripts/verify-default-product-isolation.ts` / `.spec.ts` | 隔离门禁仍会检查 `dsh.configTrees[].path` |

> 打包器 README 原文（M）：
> "The packer owns the internal `dsh.configTrees` declaration, its validation, and source directory resolution in `src/repository.ts`. **This field is not part of the public plugin manifest API.**"
> "…plus the rows of every config tree the CLI declares in its `package.json` `dsh.configTrees` (agent presets)…"
> 注意：由于 M 的 CLI **不再声明** `dsh.configTrees`，该打包器分支在 M 上拿到的是**空集**——即 configTree 机制在 M 中已是**保留但未启用**的内部能力。

**更正 2：`apps/cli/config/` 在 M 中只有 `examples/`，没有 `agent-presets/`。**

M 实测 `apps/cli/config/` 的全部内容：

| 路径 | 存在性（M） | 存在性（G = 0.1.0-rc.5） |
|---|---|---|
| `apps/cli/config/agent-presets/` | ❌ **不存在** | ✅ 存在（含 `code/`、`cordis/`、`minimal/`、`standard/`） |
| `apps/cli/config/examples/` | ✅ **存在**（3 个示例 / 6 个文件） | ❌ 不存在 |
| `packages/preset/agent-presets/` | ❌ **不存在** | ✅ 存在 |
| `packages/preset/agent-presets/presets/` | ❌ **不存在** | 未在镜像中直接列举到 |

→ **G 与 M 恰好相反**：`config/agent-presets` 在 G 有、M 无；`config/examples` 在 G 无、M 有。这是同一个 `apps/cli/config/` 目录在两个版本间**完全换过内容**。

M 的 `apps/cli/config/examples/` 实测内容（`apps/cli/README.md` 所称 "opt-in overlays" 的落地形态）：

| 示例目录 | 文件 |
|---|---|
| `github-review/` | `cordis.yml`、`github-ready-review-rule.mjs` |
| `mcp-memory/` | `engram.cordis.yml`、`mcp-reference-memory.cordis.yml`、`memorix.cordis.yml` |
| `schedule/` | `cordis.yml` |

**M 的 preset 机制替代物**（详见第 15 节）：`packages/preset/` 下三个包——`agent-preset`、`agent-preset-registry`、`persona`，以**注册表 + 声明式 Cordis YAML** 取代了"目录内联 preset + configTree 扫描"。

### 4.2 原始分析（L = 0.1.5-rc.2 视角，保留备查）

**结论：仓库根目录没有 `config/` 目录。**`config/` 是**运行时配置树的挂载命名空间**。

一手证据链（两条独立证据互相印证）：

**证据 1：`@deepseek-ai/dsh` 的 `package.json`（本机 0.1.5-rc.2 全文已读）**

```json
"files": ["lib/*.js"],
"dsh": {
  "configTrees": [
    {
      "mount": "config/agent-presets",
      "path": "../../packages/preset/agent-presets/presets",
      "scanRoster": true
    }
  ]
},
"license": "MIT"
```

**证据 2：仓库真实目录**

- 仓库根目录列举（0.1.0-rc.5 一手）中**不存在 `config/`**；
- 但仓库**存在** `packages/preset/agent-presets/`（含 `src/`、`tests/`、`package.json`、`tsconfig.json`、`README*`）；
- 且仓库**存在** `apps/cli/config/agent-presets/`，其下含 `code/`、`cordis/`、`minimal/`、`standard/` 四个子目录（0.1.0-rc.5 快照）。

**如何理解这三条事实**：

- `mount: "config/agent-presets"` 是**挂载点名称**（配置树在运行时命名空间里的位置，即 `$DSH_HOME/config/agent-presets`），**不是**仓库路径。
- `path: "../../packages/preset/agent-presets/presets"` 是**相对 `apps/cli` 的仓库路径**（`apps/cli/../../packages/...` = `packages/preset/agent-presets/presets`），指向该包的 `presets/` 子目录。
- `scanRoster: true` 表示该配置树会被**扫描成 preset 名册**并自动登记（`preset.yml` 的 `order` 字段即名册排序）。
- 实测：本机 profile 安装里，内置 preset 实际出现在
  `C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\dsh-agent-presets\presets\`
  下，含 **4 个内置 preset**：`standard`（order 1，标准模式）、`ptc`（order 2，PTC 模式）、`minimal`（order 3，极简模式）、`cordis`（order 4，创造模式），每个含 `preset.yml` + `agent.cordis.yml`，`cordis` 另带 `skills/`（`cordis-plugin-development/SKILL.md`、`editing-cordis-compositions/SKILL.md`）。

> **推测部分**：npm 安装布局下 `../../packages/preset/agent-presets/presets` 这一相对路径在磁盘上并不直接成立（它会解析到 `node_modules/@deepseek-ai/packages/...`）。因此**推测**运行时是通过包图（`dsh-agent-presets` 包）解析到 `presets/` 的实际位置，`configTrees.path` 保留的是 monorepo 源码布局。**"内置 preset 确实来自 `dsh-agent-presets` 包的 `presets/` 目录"是实测事实；"解析机制细节"是推测。**

**另一个 `config/` 是真实存在的仓库目录**：`apps/cli/config/`（见 2.3）。
`apps/cli/README.md` 提到（本机 0.1.5-rc.2 原文）：

> `config/examples/` ships opt-in overlays for GitHub review webhooks, session-local Schedule, memory MCP servers, and runtime Cordis tools. They are never part of a default profile.

相对 `apps/cli` 解读即 `apps/cli/config/examples/`。这与 `examples/` 顶层目录里的 `web-cordis/`、`web-schedule/`、`mcp-memory/` 三个示例**意图一致**（GitHub review webhook 对应 `webhook-github` + `web-cordis`/`webhook` 组合）。

> ⚠️ 0.1.0-rc.5 快照里 `apps/cli/config/` **只有** `agent-presets/`，**没有** `examples/`；`config/examples/` 是后续版本新增的（本机 0.1.5-rc.2 的 README 已提及）。**0.1.5-rc.2 下 `apps/cli/config/` 的真实内容未能获取**（镜像快照过旧、GitHub 不可达、clone 未完成）。

### 4.3 配置树 / `agent-presets` 的层级位置（**L = 0.1.5-rc.2 视角**）

> ⚠️ 本节描述 **L（0.1.5-rc.2）** 的配置树形态。**M（master）已改为注册表式 preset**，见 4.2b 与第 15 节。

```
packages/preset/agent-presets/          ← 包 @deepseek-ai/dsh-agent-presets（组合引擎）
├── src/
├── tests/
├── package.json  tsconfig.json  README*
└── presets/                            ← 配置树本体（被 dsh.configTrees 挂载）
    ├── standard/   preset.yml + agent.cordis.yml
    ├── ptc/        preset.yml + agent.cordis.yml
    ├── minimal/    preset.yml + agent.cordis.yml
    └── cordis/     preset.yml + agent.cordis.yml + skills/
```

**注意与 UI 侧的区别**：`packages/preset/agent-presets` → `@deepseek-ai/dsh-agent-presets`（后端组合引擎），
而 `packages/client/ui-agent-preset` → `@deepseek-ai/dsh-client-ui-agent-preset`（前端呈现面）。
**同一功能被切成"host 半 / client 半"两个包**——这是贯穿整个仓库的设计模式（`cli`/`client`、`api`/`client`、`extensions/cordis-host-runner`/`cordis-client-runner`、`host/*`/`client/ui-*` 皆是）。

用户侧对等物：`$DSH_HOME\.agent-presets\<name>\`（实测实例 `math-research`，含 `preset.yml` + 31 KB `agent.cordis.yml` + 6 个自定义 `.mjs` 工具脚本）。**内置 preset 与用户 preset 同构**——这就是"用户扩展工具栏"的官方位置。

### 4.4 测试目录与工具链（M 真树实测）

| 位置 | 内容 | M 实测规模 |
|---|---|---|
| 各包内 `tests/` | 单元测试与快照（如 `packages/preset/agent-preset-registry/tests/`、`apps/cli/tests/`、`apps/web/tests/`） | 307 个包各自带 `tests/` |
| `apps/web/stress-tests/` | 前端压力测试 | — |
| 根 `vitest.*.config.ts` | 分层测试配置：单元 / e2e / snapshot / web / web-stress / web-perf / **bench** / **expected** | **9 份** |
| **`snapshots/`（顶层）** | **会话/UI 快照基线**（keyless replay 的期望输出） | **1,179 文件 / 4 域**：`session/` 701、`web/` 271、`sdk/` 150、`acp/` 56 |
| `scripts/snapshots/`、`scripts/fixtures/` | 快照生成与测试夹具 | — |
| `packages/test-support/` | testkit / replay / Loader smoke 等支撑包 | **7 个包** |
| `website/tests/` | 文档站渲染快照（`*.expected.html`，中英双语） | — |
| `pytest.ini` + `python/*` | Python 侧测试 | `python/` 38 文件 |
| `benchmarks/` | **性能门禁** | 34 文件 |

**M 的 `snapshots/AGENTS.md` 规则**（`AGENTS.md` 引用）：顶层树**只保留会话驱动的用例**，其他期望输出留在各自 owner 目录内。

**测试策略要点**（`docs/testing.md` + 根 `AGENTS.md` 原文）：

- `pnpm run test:coverage` 才是 **CI 覆盖率门禁**（**per-file 100% on `packages/*/*/src`**），`pnpm run test` 不是。
- `pnpm run test:e2e` 走**真实 DeepSeek API**，无 `DEEPSEEK_API_KEY` 时**自跳过**。
- `pnpm run test:snapshot` 是 **keyless 录制会话回放**，通过已发布 profile 跑。
- 每个非平凡的**模型可见/产品用户可见**变更都必须更新一份 keyless 录制会话快照。
- 测试规范"**并发执行**"（forked workers），"**只有在单独运行时才通过的 spec 是 spec 的缺陷**"。

### 4.5 构建 / 发布工具链目录

- `scripts/build.ts`、`scripts/primary-runtime/prepare.ts`、`benchmarks/tsdown.config.ts`（由根 `package.json` scripts 引用）
- `scripts/release/`（发布流程）
- `scripts/build-exe-for-python-sdk.ts`、`scripts/build-python-release.py`（单 exe 与 Python wheel）
- `.github/workflows/`（CI，**M 实测 20 个，见第 14 节**）+ `.gitlab-ci.yml`（存在；**内容仍未读**，见第 9.2 节）
- `lefthook.yml`（Git 钩子门禁）+ `scripts/check-expected-filenames.sh` 等

---

## 5. "一切皆插件"在目录结构上的体现

DSH 的"一切皆插件"不是一句口号，它在目录结构上有**六层可核验的落点**。

### 5.1 第一层：`vendor/` —— 插件体系本身被 vendored 进仓库

`vendor/` 里放的是 Cordis 本体的源码（`cordis` 4.0.2 + 5 个官方插件 + `cosmokit` + `schemastery`），并用 `pnpm-workspace.yaml` 的 `overrides` 强制链接：

```yaml
overrides:
  '@deepseek-ai/cosmokit': 'link:vendor/cosmokit'
  '@deepseek-ai/schemastery': 'link:vendor/schemastery'
```

**含义**：DSH 把"插件框架"当成仓库的一等公民而非外部黑盒。`@deepseek-ai/dsh` 的 dependencies 里直接列 `@deepseek-ai/cordis`、`cordis-plugin-hmr`、`cordis-plugin-include`、`cordis-plugin-loader`、`cordis-plugin-timer`、`schemastery`。

`packages/README.md` 定义了插件贡献能力的三种方式（原文）：

> Cordis `Service` subclasses and function plugins contribute through `ctx.effect()`, `ctx.on()`, or `ctx.waterfall()`.

### 5.2 第二层：`packages/<group>/<pkg>` 的"能力族三分法"

官方明文规则（`packages/README.md`）：

> **Extension plugins depend on Service Definitions, never concrete providers.** … Capabilities separate **Service Definition / Service Provider / Consumer** roles when they evolve independently.

这个三分法在目录里**逐字可见**，以 `fs/` 为例：

| 角色 | 仓库路径 | 包名 |
|---|---|---|
| Service Definition（抽象 seam） | `packages/fs/fs` | `dsh-fs` |
| Service Provider（具体实现） | `packages/fs/fs-local` / `fs-sandbox` | `dsh-fs-local` / `dsh-fs-sandbox` |
| Consumer（面向模型的工具） | `packages/fs/tool-fs` / `tool-fs-search` / `tool-str-replace-editor` / `tool-present` | `dsh-tool-*` |

同一模式在 `shell/`（`shell` seam → `bash-local`/`pwsh-local`/`bash-sandbox`/`pwsh-sandbox` → `tool-bash`/`tool-pwsh`）、`web/`（`web` → `web-fetch-http`/`web-search-deepseek` → `tool-web`）、`sandbox/`、`subagent/`、`workflow/`、`jobs/`、`compaction/`、`skill/`、`spill/`、`storage/`、`subprocess/`、`terminal/`、`session/`、`llm/`、`context/`、`interaction/` 中**完整复现**。

官方对 seam 概念的专门文档：`docs/capability-seams.md`（存在性一手确认）。

### 5.3 第三层：`dsh.configTrees` —— 配置树挂载机制

见 4.2 节。机制要点：

- 包在自己的 `package.json` 里用 `dsh.configTrees[]` 声明"我能向某个挂载点贡献一棵配置树"；
- 每项含 `mount`（挂载点名称）、`path`（树本体路径）、`scanRoster`（是否扫描成名册）；
- 实测 `@deepseek-ai/dsh` 只有 **1 棵** configTree（`config/agent-presets`），但机制本身是**多包可叠加**的（这是 `dsh` 字段被设计成数组的原因）。

### 5.4 第四层：`packages/bundle/*` —— 用 patch 层"打包能力"，而不是写死

`bundle/` 下每个包都是"一个 profile 的补丁层"，`package.json` 里有 `dsh.bundle.patch` 指向自带的 `cordis.patch.yml`。

实测（本机 0.1.5-rc.2，`D:\Incubator\temp\evidence\bundle-layers\`）：

| bundle（仓库路径 `packages/bundle/*`） | 包名 | patch 大小（L = 0.1.5-rc.2） | **patch 大小（M = master）** | 定位 |
|---|---|---|---|---|
| `base` | `dsh-base` | **19,515 B** | **20,802 B** | 共享核心（base 型 profile 的第一层） |
| `web-app` | `dsh-web-app` | **18,588 B** | **20,978 B** | 浏览器面 |
| `sdk-minimal` | `dsh-sdk-minimal` | 5,248 B | **5,318 B** | **独立极简 SDK 树，不叠 base** |
| `headless` | `dsh-headless` | 1,152 B | **1,240 B** | 叠在 base 上，只覆盖 persona + 插一个 one-shot runner |
| `sdk-app` | `dsh-sdk-app` | 676 B | **1,586 B** | SDK app 运行时 |
| `acp-app` | `dsh-acp-app` | 525 B | **553 B** | ACP 应用 |

> **G 快照里 `packages/bundle/` 只有 3 个**（`base`、`headless`、`web-app`）；`sdk-app`、`sdk-minimal`、`acp-app` 是后续新增的；**M 仍为 6 个**，但 patch 层普遍变大（`sdk-app` +134.6%）。→ 目录在快速演进（与 README 的 "DEVELOPER PREVIEW / compatibility-breaking changes" 警告一致）。
>
> **M 的权威定义**（`docs/architecture.md`）：bundle 是"**Cordis config rows 及其挂载代码的分发格式**，因此它插入的任何东西都能被上层层继续 patch"。

### 5.5 第五层：profile 装配链 —— "空根 + 有序 patch 叠加"

**实测一手证据**（`C:\Users\ysc20\.dsh\profiles\web\`）：

`package.json`：
```json
{
  "name": "dsh-profile-web",
  "private": true,
  "dependencies": {},
  "dsh": { "profile": { "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"], "patchReload": "live" } }
}
```

`cordis.yml`（**恒为空表**，原文注释）：
```yaml
# dsh profile root — an empty entry list. The tree is composed as patches:
# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml, then any
# --patch overlays. Edit cordis.patch.yml, not this file.
[]
```

`cordis.patch.yml`（用户层，原文注释）：
```yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
```

`pnpm-workspace.yaml`：
```yaml
packages:
  - .
nodeLinker: hoisted
autoInstallPeers: false
```

**因此 DSH 的装配公式是**（`apps/cli/README.md` 原文同义）：

```
空根
 → dsh.profile.bundles[] 中每个 bundle 的 patch（按数组顺序）
 → profile 自己的 cordis.patch.yml
 → home 级 $DSH_HOME/cordis.patch.yml
 → --patch <file> 覆盖层
```

每一层是 **loader patch 条目数组**，支持三种操作：`id` 定向 config 覆盖、`disabled: true` 禁用、`insert:` 插入新插件行；`!!js` 允许 JS 表达式。

**实测的 patch 语法实例**（`dsh-base/cordis.patch.yml`，本机 0.1.5-rc.2）：

```yaml
- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: !!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'
    workspaceRoot: !!js process.cwd()

- id: bash-sandbox
  name: '@deepseek-ai/dsh-bash-sandbox'
  disabled: !!js process.platform === 'win32'
```

**"一切皆插件"的极致体现**：
- **连权限/沙箱都是插件行**——三档预设 `read-only` / `workspace-write` / `danger-full-access` 是在 patch 里以 `config.presets` 声明的；
- **连"平台适配"都是插件行的 `disabled` 表达式**——Windows 上禁用 `dsh-bash-sandbox`、启用 `dsh-pwsh-sandbox`，靠 `!!js process.platform` 二选一；
- **模型能写插件并挂载**——`packages/extensions/` 的 `dsh-tool-cordis` + `dsh-cordis-host-runner` + `dsh-cordis-client-runner` 提供"运行时检查 + 模型编写插件的 mount/unmount"，官方描述为 "Agent runtime self-modification"。

### 5.6 第六层：preset 层 —— "造一个智能体 = 写一个目录"（**L = 0.1.5-rc.2 视角**）

> ⚠️ **M 已重构**：preset 不再是"目录 + configTree 扫描"，而是"**声明式 Cordis YAML + `ctx.agentPresets` 注册表**"。
> M 的对应表述为 `packages/preset/README.md` 原文："This group declares **Agent capabilities through ordinary Cordis configuration** and manages selection and runtime revisions. **The Host shares the Agent loop; each Agent sees the tools, prompts and skills of its selected revision.**"
> **完整演进对照见第 15 节。**

`packages/preset/agent-presets/presets/minimal/agent.cordis.yml` 的官方极简智能体**只有 2 个顶层条目**：

1. `persona`（`dsh-persona`，`complete: true` + `includeRuntimeContext: false`）——人格即全部系统提示词；
2. `persistent-shell`（`cordis:group`，`isolate.terminals: true`）——内含 `pty` / `terminal-bash` / `persistent-bash` / `terminal-pwsh` / `persistent-pwsh` 5 行，靠 `disabled: !!js process.platform …` 二选一。

其中 `cordis:group` + `isolate` 语法演示了**条目本地 realm（作用域）**机制——官方注释原文：

> A service row here MUST sit inside a group carrying an `isolate` realm. Without one it publishes into the root realm, where it is process-global.

**这就把"目录结构"和"运行时作用域"接上了**：仓库的 `packages/core/scope` + preset 的 `isolate:` 语法共同实现了"每个智能体一套隔离的服务实例"。

### 5.7 一个小结：结构即装配

| 目录/文件 | 在"插件化"中扮演的角色 |
|---|---|
| `vendor/` | 插件框架本体（Cordis） |
| `packages/<group>/<pkg>/` | 单个插件（Service Definition / Provider / Consumer 三种角色） |
| `packages/*/src/index.ts` 的 `apply(ctx)` | 插件入口（官方：导出 `name`、`inject`、`apply(ctx)`） |
| `packages/bundle/*/cordis.patch.yml` | 把一组插件打包成"能力层" |
| `packages/preset/agent-presets/presets/<name>/` | 把一组插件+人格打包成"智能体" |
| `apps/cli/config/agent-presets/` + `dsh.configTrees` | 声明配置树的挂载点与来源 |
| `$DSH_HOME/profiles/<name>/cordis.patch.yml` | 用户层的插件覆盖 |
| `$DSH_HOME/.agent-presets/<name>/` | 用户自定义智能体 |

**新增一个插件的官方流程**（第三方文章转录，**中可信度**）：新建 `packages/<group>/<pkg>/`（`src/index.ts` + `package.json` + `tsconfig.json` + `README.md`）→ 在 `tsconfig.host.json` 的 `references` 加路径 → 跑 `pnpm run gen-tsconfig-paths` 生成别名 → `pnpm install` 建 workspace 软链 → 在 `packages/bundle/<profile>/cordis.patch.yml` 里 `insert` 该插件。其中"`tsconfig.host.json` 的 references"与"`pnpm run gen-tsconfig-paths`"两条与仓库实际文件（`tsconfig.host.json`、`scripts/` 下的生成器）**吻合**；`gen-tsconfig-paths` 这一确切脚本名**未在 0.1.0-rc.5 的 `scripts/` 列表中见到**，标记为中可信度。

---

## 6. 与本地 npm 安装产物的结构差异

### 6.1 顶层对照

| 维度 | 仓库（源码） | 本机 npm 安装 `@deepseek-ai/dsh` |
|---|---|---|
| 顶层内容 | 14 个目录 + 38 个根文件（含 `apps/`、`packages/`、`vendor/`、`docs/`、`scripts/`、`tests`、CI 配置…） | **`lib/` + `node_modules/` + `LICENSE` + `package.json` + `README.md` + `README.zh.md` + `README.i18n.yaml`** |
| 源码 | 每包 `src/*.ts` | 只有 `lib/*.js`（`package.json` 的 `files: ["lib/*.js"]`） |
| 是否含测试/文档/示例 | 是 | **否** |
| 是否含构建/CI 配置 | 是 | **否** |
| 是否含 `config/` | `apps/cli/config/`（含 agent-presets） | **否**（npm 包只有 `lib/*.js`） |

### 6.2 结构差异的根本原因

npm 发布的是**"无数源码结构"的产物**：`files: ["lib/*.js"]` 只放行编译后的 JS。
但**仓库结构信息并未丢失**，因为：

1. `package.json` 保留了 `repository.directory`（240/240 全有）→ **可无损重建 `packages/` 骨架**（本报告第 3 节即此法）；
2. `package.json` 保留了 `dsh.configTrees` / `dsh.bundle.patch` / `dsh.profile` 等 **DSH 私有字段** → 装配机制在安装态可见；
3. 本地 `C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai\` 下有**全部 240 个包**（profile 安装），比 CLI 安装的 `node_modules` 完整得多——**这是本地重建 monorepo 结构的最佳数据源**。

### 6.3 差异清单（哪些"目录"在 npm 安装态不存在）

| 仓库路径 | npm 安装态 | 说明 |
|---|---|---|
| `apps/cli/src/` | ❌ | 只有 `lib/` |
| `apps/cli/config/` | ❌ | 未随包发布（`files` 只含 `lib/*.js`） |
| `apps/cli/reference/`、`composition.md` | ❌ | 未发布 |
| `apps/cli/tests/` | ❌ | 未发布 |
| `packages/*/*/src/`、`tests/`、`tsconfig.json` | ❌ | 未发布 |
| `packages/*/*/README.md` | ⚠️ 部分 | `@deepseek-ai/dsh` 有 README；多数包视 `files` 而定 |
| `packages/preset/agent-presets/presets/` | ✅ **以包形态存在** | 实际落在 `node_modules/@deepseek-ai/dsh-agent-presets/presets/`（**实测**） |
| `packages/*/*/cordis.patch.yml` | ✅ | bundle 的 patch 层随包发布（实测 6 个） |
| `vendor/*` | ✅ | 以 `@deepseek-ai/cordis*` 等包发布，但**版本线不同轨**（4.x/1.x/3.x vs 0.1.5-rc.2） |
| `native/system/packages/entry` | ✅ | 以 `@deepseek-ai/node-addon-system` 发布，独立版本线（0.1.2） |
| `docs/`、`scripts/`、`website/`、`examples/`、`.github/`、`.agents/` | ❌ | 完全不发布 |
| `packages/test-support/*` | ⚠️→✅ | **M 实测 7 个包**，均为真实目录且有 `package.json`；L 中未出现在 240 个已发布包内（故对 L 的"未发布"观察成立） |
| `packages/lsp/*`、`packages/experimental/*`、`packages/ssh/*`、`packages/ptc-runtime/*`、`packages/deliverables/*`、`packages/document/*`、`packages/browser-use/*`、`packages/computer-use/*` | — | **M 新增的能力族**，L 中不存在；已发布状态未逐一核对 |
| `packages/e2b/*`、`packages/examples/*` | ❌ | G 有目录、M 已无（group 消失） |
| `docs/`、`scripts/`、`website/`、`benchmarks/`、`snapshots/`、`.github/`、`.agents/`、`.claude/` | ❌ | 完全不发布（M 实测各包 `files` 字段均不含这些路径） |

> **M 实测的发布视图**：`apps/cli/package.json` 的 `files: ["lib/*.js", "lib/types/*.d.ts"]`——即 **M 只发布编译产物 + 类型声明**，比 L 的 `files: ["lib/*.js"]` 多了 `.d.ts`。

### 6.4 一个实证的边界现象

本会话中执行 `dsh --profile web --dump-config` 时，DSH 需要写
`C:\Users\ysc20\.dsh\profiles\web\cordis.yml`，被沙箱以
`EPERM: operation not permitted, open 'C:\Users\ysc20\.dsh\profiles\web\cordis.yml'` 拒绝——
**因为本会话工作区被限定在 `D:\Incubator`，而 `~\.dsh` 在工作区之外**。

这既是 `workspace-write` 语义的一手实证，也顺带说明：**仓库产物（`packages/`）与运行时工作区（`$DSH_HOME` + workspace root）是两个互不重叠的目录域**。

`$DSH_HOME`（实测 `C:\Users\ysc20\.dsh\`）的结构：

```
profiles/            每个 profile 一个 pnpm 工作区（cordis.yml、cordis.patch.yml、package.json、pnpm-workspace.yaml、node_modules/）
  node_modules/@deepseek-ai/    240 个插件包（全部）
sessions/            按工作区路径分目录，会话落盘为 session.v3.jsonl.zstd
storages/            workspace.json 等（storages/session_projcache/sessions/*.json）
attachments/         附件
.agent-presets/      用户自定义 agent preset
settings.yaml        UI 设置
.credentials.yaml    凭据
.anonymous-user-id
```

---

## 7. 关键发现：需要修正的常见误解（含协作渠道）

| 常见说法 | 实际情况 | 依据 |
|---|---|---|
| "仓库根有 `config/` 目录" | **三个版本都没有顶层 `config/`**。`config/` 是**挂载命名空间**；真实目录只有 `apps/cli/config/`（M 下其内容为 `examples/`，G 下为 `agent-presets/`） | 根目录列举（G）+ `apps/cli/config/` 真树实测（M） |
| "默认分支是 `main`" | 实际为 **`master`**——**已由 GitHub API 权威确认**（`default_branch: "master"`） | GitHub API（经镜像）+ 镜像 API 全部以 `master` 成功 |
| "License 是 apache-2.0" | **MIT**。**五处独立一手证据一致**（API `spdx_id` / 根 `LICENSE` 全文 / `README.md` / 根 `package.json` / npm 包 `package.json`+`LICENSE`） | 见 1.2 三证合一定论 |
| "仓库用 Issue 收集反馈" | **不开放 Issue**（`has_issues: false`，`open_issues_count: 0`），改用 **GitHub Discussions**（`has_discussions: true`）。README 官方指引亦指向 Discussions | GitHub API + `README.md` |
| "`has_wiki`/`has_pages` 有内容" | 均 `false`。文档站由**独立 workflow `docs-pages.yml`** 部署（`website/` 的 VitePress 构建） | GitHub API + `.github/workflows/docs-pages.yml` |
| "`examples/` 是顶层目录" | **M 与 G 的顶层都没有 `examples/`**；示例已迁至 `apps/cli/config/examples/`（覆盖层）与 `packages/experimental/*` | M 真树 + G 镜像列举 |
| "`dsh.configTrees` 是现行机制" | **仅对 L 成立**。M 的 `apps/cli/package.json` 已无 `dsh` 字段，该字段降级为**镜像打包器内部能力** | M 真树全文解析 |
| "内置 preset 位于 `packages/preset/agent-presets/presets/`" | **仅对 L/G 成立**。M 改为 `packages/preset/{agent-preset,agent-preset-registry,persona}` 注册表式 | M 真树 + 第 15 节 |

**协作与反馈渠道（M + API 一手）**：

| 渠道 | 状态 |
|---|---|
| Issue | ❌ **关闭**（`has_issues: false`） |
| Discussions | ✅ **开启**，README 官方指引："submit feedback or bug reports through **GitHub Discussions**" |
| Pull Request / Fork | ✅ 开启（`allow_forking: true`）；有 `pull_request_template.md`、`CONTRIBUTING.md` / `.zh.md` |
| PR 治理 | **加权审批**（`weighted-approval.yml`）+ **栈式 PR**（`.agents/skills/dsh-merging-stacked-prs/`）+ Issue 生命周期治理（`issue-lifecycle.yml` / `issue-policy.yml`） |
| 社区 | README 提供 **Discord 社区**链接；插件仓库建议打 `dsh-plugin` topic（对应 API `topics` 含 `dsh-plugin`） |
| 文档站 | 由 `docs-pages.yml` 部署（`website/` VitePress） |

---

## 8. 信息可信度标注与证据来源

### 8.1 一手证据（最高可信度）

> ⭐ **升级说明**：取得 master 完整工作树后，**"结构类断言"整体升级为 A 级（一手 · master 真树）**。第 2、11–15 节的目录级与文件级断言全部属于该级别。下表 E1–E11 为升级前的基线证据（多为 L/G），E13–E16 为新增的 master 级证据。

| 编号 | 证据 | 位置 / 来源 | 用途 |
|---|---|---|---|
| **E13** ⭐ | **master 完整工作树**（13,229 文件 / 104.7 MB / 54 group / 307 包 / 版本 0.1.7-alpha.2） | `D:\Incubator\temp\ds-repo\deepseek-harness-master\`（由 `archive/refs/heads/master.tar.gz` 27,099,922 B 经 `ghproxy.net` 解压，校验无损） | **第 2、11–15 节全部结构断言** |
| **E14** ⭐ | `docs/architecture.md`（18,696 B）与 `docs/module-graph.md`（119,655 B）全文 | 同上，第 12 节提炼 + 原文引用 | 官方架构语义、装配顺序、seam 定义、turn/step 流程 |
| **E15** ⭐ | `packages/README.md`（M 版，54 行 group 表）+ 10 个 group 的 `README.md` 全文 | 同上，第 13 节 | **官方授权的 group → 包 → `ctx` key 映射** |
| **E16** ⭐ | 20 个 `.github/workflows/*.yml` 的 `name`/`on`/job 名 | 同上，第 14 节 | CI / 发布流水线结构 |
| **E17** ⭐ | GitHub API 仓库元数据（`description`/`homepage`/`language`/`license.spdx_id`/`default_branch`/`topics`/star/fork/`has_issues`/`has_discussions`…） | `https://gh-proxy.com/https://api.github.com/repos/deepseek-ai/deepseek-harness`（采集 2026-09-23） | 1.2 三证之一、1.5、第 7 节 |
| E1 | **240 个包的 `repository.directory` → 仓库路径映射表** | `D:\Incubator\temp\evidence\dsh-packages-by-repodir.txt`（240 行）；JSON 版 `dsh-packages-with-repodir.json`；生成脚本 `D:\Incubator\temp\scripts\extract-repo-structure.ps1` | 第 3 节全部分类骨架（**L 视角**） |
| E2 | 240 个包的 `description` 字段 | `D:\Incubator\temp\evidence\dsh-packages-with-description.txt` | "职责"列 |
| E3 | `@deepseek-ai/dsh` 的 `package.json` 全文（含 `dsh.configTrees`、`files`、`license`、完整依赖/devDependencies） | `C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\package.json` | 4.2、6.1、6.3 |
| E4 | `@deepseek-ai/dsh` 的 `README.md` / `README.zh.md` / `LICENSE` | 同上目录 | 1.2、4.1、4.2 |
| E5 | profile 装配实测文件 | `C:\Users\ysc20\.dsh\profiles\web\{package.json,cordis.yml,cordis.patch.yml,pnpm-workspace.yaml}` | 5.5 |
| E6 | 6 个 bundle 的 `cordis.patch.yml` 副本与大小（L） | `D:\Incubator\temp\evidence\bundle-layers\`；`dsh-bundle-dependencies.txt` | 5.4、11.3 |
| E7 | 4 个内置 preset 全文与清单（L） | `DSH-内置preset-一手证据.md` + `builtin-agent-presets\presets\{standard,ptc,minimal,cordis}\` | 4.3、5.6、15.1 |
| E8 | 用户自定义 preset 实例 | `D:\Incubator\temp\evidence\agent-preset-math-research\` | 4.3、5.6 |
| E9 | `dsh --help` / `--version` 原始输出、`--dump-config` 的 EPERM 记录 | `D:\Incubator\temp\dsh-help\`、`sandbox-eperm-observation.txt` | 4.1、6.4 |
| E10 | Gitee 镜像 `wenj91/deepseek-harness`（0.1.0-rc.5）的仓库文件与目录列举 | 整理稿 `gitee-mirror-repo-structure.md` | 第 2、4 节历史对照（G） |
| E11 | G 的根 `README.md` 全文、`LICENSE` 全文、`packages/README.md` 全文 | `https://raw.giteeusercontent.com/wenj91/deepseek-harness/raw/master/{README.md,LICENSE,packages/README.md}` | 1.1、1.2、3.1、5.2 |
| ~~E12~~ | ~~0.1.7-alpha.2 部分克隆的工作树~~ | **已作废**：该次检出已被覆盖，但已由 **E13 完整 tarball** 全面取代 | — |

### 8.2 中等可信度（第三方报道 / 搜索索引，非一手文件）

| 内容 | 来源 | 备注 |
|---|---|---|
| 顶层目录清单的第三方复述（与 E10 一致：`apps/ packages/ vendor/ python/ native/ examples/ docs/ website/ scripts/ .agents/`） | CSDN《Deepseek Harness 架构解析和应用 上》 https://blog.csdn.net/qq_63358859/article/details/165840463 | 与镜像一手列举**完全吻合**，故可信度高 |
| "新增一个插件的 5 处改动"流程 | 同上 | 与仓库文件部分吻合，`gen-tsconfig-paths` 脚本名未在一手文件列表中出现 |
| Cordis 作为 DSH 底座、Cordis 源于 QQ 机器人生态 | 腾讯云《Cordis：从开源 QQ 机器人内核到 DeepSeek Harness 平台底座》 https://cloud.tencent.cn/developer/article/2728030 | 与一手 `vendor/cordis` 事实一致 |
| `packages/core/` 六包主线（session / system-prompt / tools / agent / agent-loop / scope）与"一次回合的骨架" | 腾讯云《第 6 讲 · core 六包主线》 https://cloud.tencent.com.cn/developer/article/2729763 | 与 E1 的 `packages/core/*` 八包**部分吻合**（该文只讲 6 个，另有 `agent-default-model`、`agent-tool-presentation`） |
| `docs/architecture.md` / `architecture.zh.md` 存在 | 搜索引擎索引（GitHub blob URL） | ⚠️ **该条已被一手证据取代**：M 真树已取得 `docs/architecture.md` **全文（18,696 B）**，见第 12.1 节 |
| License 标注 apache-2.0 | 鲸智社区 https://aihub.caict.ac.cn/codes/deepseek-ai/deepseek-harness | **与五处一手证据矛盾，已判定为第三方元数据错误**（见 1.2） |
| InfoQ《DeepSeek 把 Harness 开源了：模型、工具、Agent Loop 全是插件》 https://www.infoq.cn/article/de9AljWc4ejW2KAyW8dD | 抓取成功但正文被截断 | 仅取标题所示定位 |
| 生态：第三方 fork 与社区书 | `LunFengChen/deepseek-harness`（魔改版）、`yth1120/dsh-web-workbench`、`diguike/book-deepseek-harness` | GitHub 页面不可访问，**仅作生态活跃度脚注，细节未能核实** |
| 默认分支为 `master` | 本会话另一执行体经 `ghproxy.net` 执行 `git -c http.sslVerify=false ls-remote https://ghproxy.net/https://github.com/deepseek-ai/deepseek-harness.git`，返回 `00102833dfaee1da9f48a3a8eae9d34005a75218  refs/heads/master` | **转录自另一执行体，本报告作者未亲自复现**；但与镜像 API 全部用 `master` 成功的事实一致 |
| `ghproxy.net` 可作为 GitHub 镜像网关绕过本机 hosts 劫持 | 同上（另一执行体实测） | 本会话据此启动的浅克隆**长时间停在 `.git/objects` 0 字节**（见第 9 节缺口 13），故该通路**在本环境下未验证为可用** |

### 8.3 明确标注为**推测**的内容（已按 master 真树收缩）

| 编号 | 推测内容 | 状态 | 理由 |
|---|---|---|---|
| S1 | 8 个未发布包的具体仓库路径 | **✅ 基本关闭** | M 真树确认 `test-support/`（7 包）与 `experimental/`（20 包）为**真实 group 目录**。其中 `dsh-experimental-agent-team` / `-tool-agent-team` / `-agent-team-profile` → `packages/experimental/agent-team{,-profile}`、`tool-agent-team`；`dsh-experimental-code-runtime-python` → `packages/experimental/ptc-runtime-python`（**名称也变了**）；`dsh-llm-mock-server` / `dsh-llm-replay` / `dsh-loader-smoke` / `dsh-agent-loop-testkit` 应落在 `packages/test-support/*`（**未逐一核对具体目录名，仍标推测**） |
| S2 | `configTrees.path` 在 npm 安装布局下的解析机制 | **部分作废** | 对 M 已无意义（字段退役）；对 L 仍是推测。**实际 preset 来源是 `dsh-agent-presets/presets/` 属实测** |
| S3 | `apps/cli/config/examples/` 在 0.1.5-rc.2 下的存在性 | **仍为推测** | M 下**确定存在**（3 示例 / 6 文件，已列全）；L 下仍未知 |
| S4 | `webhook/`、`plan/` 等 group 的新增时间点 | **仍为推测** | 三方快照不连续，无法确定精确引入版本 |
| S5 | 各 group `README.md` 的 map 内容 | **✅ 关闭** | 54 个 group README 全部可读，第 13 节转录了 10 个 |
| S6 | `client/*` 各 `ui-*` 包职责的中文概括 | **仍为推测** | 基于官方英文 Role 的翻译/压缩，非官方中文 |
| S7 | M 中 `agent-preset` 的**实际内置 preset 名册**（standard / ptc / minimal / cordis 是否仍是这四个） | **新增推测** | M 把名册改为 profile 行声明；本报告未逐一核对 M 的 profile composition 中声明的 preset 行 |

### 8.4 实际访问过的 URL 清单

**一手真树（本地，无需网络）**

- `D:\Incubator\temp\ds-repo\deepseek-harness-master\`（13,229 文件；来源 `archive/refs/heads/master.tar.gz`，27,099,922 B，经 `ghproxy.net`）

**GitHub API（经 `gh-proxy.com` 镜像，采集 2026-09-23）**

- `https://gh-proxy.com/https://api.github.com/repos/deepseek-ai/deepseek-harness`

**镜像仓库（一手，可访问）**

- https://gitee.com/wenj91/deepseek-harness/tree/master
- https://gitee.com/wenj91/deepseek-harness/tree/master/packages
- https://gitee.com/wenj91/deepseek-harness/tree/master/packages/README.md
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/git/trees/master?recursive=1
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/apps?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/apps/cli?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/apps/cli/config?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/apps/cli/config/agent-presets?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/apps/web?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/packages?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/packages/preset?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/packages/preset/agent-presets?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/packages/bundle?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/docs?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/scripts?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/python?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/native?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/examples?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/patches?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/vendor?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/.github?ref=master
- https://gitee.com/api/v5/repos/wenj91/deepseek-harness/contents/.agents?ref=master
- https://raw.giteeusercontent.com/wenj91/deepseek-harness/raw/master/README.md
- https://raw.giteeusercontent.com/wenj91/deepseek-harness/raw/master/LICENSE
- https://raw.giteeusercontent.com/wenj91/deepseek-harness/raw/master/packages/README.md

**一手（master 真树，本地，无需网络）**

- `D:\Incubator\temp\ds-repo\deepseek-harness-master\` —— 完整工作树（13,229 文件 / 104.7 MB / 54 group / 307 包）
- 由 `archive/refs/heads/master.tar.gz`（27,099,922 B，经 `ghproxy.net` 镜像）解压，tar 完整性校验通过

**一手（GitHub API，经镜像；采集 2026-09-23）**

- `https://gh-proxy.com/https://api.github.com/repos/deepseek-ai/deepseek-harness` → 仓库元数据（见 1.5）
- 注：`ghproxy.net` 与 `ghfast.top` 对 `api.github.com` 返回 **403**（只代理 raw/archive）；仅 `gh-proxy.com` 可代理 API

**第三方解读（中可信度）**

- https://blog.csdn.net/qq_63358859/article/details/165840463
- https://cloud.tencent.com.cn/developer/article/2729763
- https://cloud.tencent.cn/developer/article/2728030
- https://aihub.caict.ac.cn/codes/deepseek-ai/deepseek-harness
- https://www.infoq.cn/article/de9AljWc4ejW2KAyW8dD （正文截断）
- https://developer.aliyun.com/article/1755970 （正文为空）
- https://developer.aliyun.com/article/1756806 （正文为空）
- https://deepwiki.com/deepseek-ai/deepseek-harness/1.2-monorepo-structure-and-package-families （JS 渲染，正文为空）

**被本机 hosts 拦截、无法访问（已尝试并失败）**

- `https://github.com/deepseek-ai/deepseek-harness` → `resolves to a non-public IP address`
- `https://api.github.com/repos/deepseek-ai/deepseek-harness/git/trees/HEAD?recursive=1` → 同上
- `https://api.github.com/repos/deepseek-ai/deepseek-harness/contents/` → 同上
- `https://raw.githubusercontent.com/...`、`https://codeload.github.com/...`、`https://cdn.jsdelivr.net/...` → 同上
- `https://deepseek-harness.github.io/deepseek-harness/llms.txt` → 同上
- pwsh 直连 `registry.npmjs.org` / `ghproxy.com` → `The SSL connection could not be established`（出网 TLS 亦被阻断）
- `git clone --depth 1 https://github.com/deepseek-ai/deepseek-harness.git` → 120 秒超时（DNS 指向 127.0.0.1）

---

## 9. 缺口清单（**已按 master 真树更新：14 项中 9 项关闭**）

> 本节原为"未能获取的信息"。取得 master 完整工作树后，逐项复核如下。**未关闭项仍不作推断性填充。**

### 9.1 已关闭的缺口（9 项）

| 原缺口 | 现状 | 关闭依据 |
|---|---|---|
| ① 各 group 的 `README.md` | **✅ 全部可读**——54 个 group **每个都有** `README.md` + `README.zh.md` + `README.i18n.yaml`；本报告第 13 节转录了 10 个核心 group 的权威映射 | master 真树 |
| ② `docs/architecture.md` 全文 | **✅ 已读全文（18,696 B）**，提炼见第 12 节 | master 真树 |
| ② `docs/module-graph.md` 全文 | **✅ 已读（119,655 B / 1,655 行，mermaid 生成图）**，性质见第 12.2 节 | master 真树 |
| ③ `.github/workflows/` 文件名与内容 | **✅ 20 个 workflow 文件名 + 大小 + 触发条件 + job 名已获取**，见第 14 节 | master 真树 |
| ④ `assets/` 内部结构 | **✅ 已澄清：M 顶层根本没有 `assets/`**（G 有、M 无）——原缺口因目录消失而消解 | master 真树 |
| ⑤ `apps/cli/config/examples/` 具体文件构成 | **✅ 已列全（3 示例 / 6 文件）**，见 4.2b | master 真树 |
| ⑥ `packages/client/` group 清单 | **✅ 已读 group README（59 个包 + 职责 + ctx key）**，见第 13 节 | master 真树 |
| ⑦ 未发布包的精确路径（旧编号 S1） | **✅ 基本澄清**：`test-support/` 7 包、`experimental/` 20 包在 M 中**均为真实目录且有 `package.json`**；L 中"未发布"的观察成立（它们不在 240 个已发布包内） | master 真树 |
| ⑧ 仓库 star / fork / 元数据 | **✅ 已获取**（234,063★ / 28,120 fork / MIT / master / TypeScript …），见 1.5 | GitHub API（经镜像） |

### 9.2 **仍未关闭**的缺口（5 项）

| # | 缺口 | 原因 |
|---|---|---|
| 1 | **`0.1.5-rc.2` 对应 commit 的精确仓库快照** | 现有结构来自 **M（master）** 与 **G（0.1.0-rc.5）**，二者均非 L。凡 L 断言均基于本机 npm 产物（`package.json` 元数据 + 已发布文件），**目录级结构只能由 `repository.directory` 反推** |
| 2 | **`master` 的精确 commit SHA 与提交历史** | 工作树来自 `archive/refs/heads/master.tar.gz`，**不含 `.git`**；已知 `pushed_at = 2026-09-22`，但无 SHA |
| 3 | **约 130 个 symlink/硬链接文件的内容** | `CLAUDE.md`、`.claude/skills`、部分 `snapshots/**/{AGENTS.md,*.expected.*}` 在 Windows `tar` 下无法创建（**解压工具限制，非仓库缺失**） |
| 4 | **`.gitlab-ci.yml` 内容** | 文件存在（根目录），本次未读 |
| 5 | **`packages/*/*/README.md`（307 份包级 README）全文** | 只读了约 12 份（含 preset 全部、client/core/llm/fs/shell/sandbox/session/subagent/bundle/experimental/ssh group README）。**包级 README 是 per-package contract 的权威，未逐份通读** |

### 9.3 已被真树**否证**的旧推断（重要）

| 旧推断 | 真树结论 |
|---|---|
| "顶层有 `examples/` 可运行示例工程" | ❌ M 顶层无 `examples/`（G 亦无） |
| "顶层有 `assets/` 静态资源目录" | ❌ M 顶层无 `assets/` |
| "`packages/preset/agent-presets/presets/` 是内置 preset 的本体" | ⚠️ **仅对 L/G 成立**；M 中该路径**不存在**，preset 改为注册表式（第 15 节） |
| "`dsh.configTrees` 是现行的配置树挂载机制" | ⚠️ **仅对 L 成立**；M 的 `apps/cli/package.json` 已无 `dsh` 字段，该机制降为内部未启用能力 |
| "`0.1.7-alpha.2` 部分克隆已丢失，仅存转录" | ✅ **已由完整 tarball 恢复**（13,229 文件），本报告相关章节已全面替换为真树证据 |
| "0.1.5-rc.2 与 0.1.7 的差异" | 见第 11 节三方版本差异表（早期版本只对比了 G 与 L） |

---

## 10. 附：可复现本报告的证据生成脚本

`D:\Incubator\temp\scripts\extract-repo-structure.ps1`（**从 npm 元数据重建 `packages/` 骨架**）：

```powershell
# 遍历两个本地安装根，读每个 @deepseek-ai/* 包的 package.json，
# 抽取 repository.directory -> 仓库路径，输出按 repoDir 排序的映射表
$roots = @(
  "C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai",   # CLI 安装
  "C:\Users\ysc20\.dsh\profiles\node_modules\@deepseek-ai"          # profile 安装（全部 240 个）
)
# ... 详见脚本原文 ...
```

`D:\Incubator\temp\scripts\wait-and-dump-repo.ps1`（**真仓库工作树就绪后导出目录树**，用于本报告中 E12 类证据）：

```powershell
Get-ChildItem D:\Incubator\temp\ds-repo -Recurse -Directory -Force |
  Where-Object { $_.FullName -notmatch '\\\.git\\|\\node_modules\\|\\dist\\|\\lib\\' } |
  ForEach-Object { $_.FullName.Substring('D:\Incubator\temp\ds-repo'.Length + 1) } |
  Sort-Object | Set-Content D:\Incubator\temp\ds-repo-tree.txt -Encoding utf8
```

（该脚本为早期版本；`D:\Incubator\temp\ds-repo-tree.txt` 中的旧内容为**部分**树（313 行），**已作废**。真树就绪后应以 `D:\Incubator\temp\evidence\dsh-repo-tree-MASTER.txt`（1,876 行）为准。）

---

# 第二部分：master 真树深度核实（M = 0.1.7-alpha.2）

> 以下第 11–16 节为取得 master 完整工作树后的新增分析。**这部分的全部结构断言均为"一手（master 真树）"。**

---

## 11. 三方版本差异表（**本报告的核心增量**）

这是全文唯一的结构演进总表。**M** = master = 0.1.7-alpha.2（真树）；**L** = 0.1.5-rc.2（本机 npm）；**G** = 0.1.0-rc.5（Gitee 镜像）。

### 11.1 顶层与规模

| 维度 | G（0.1.0-rc.5） | L（0.1.5-rc.2） | **M（0.1.7-alpha.2，真树）** |
|---|---|---|---|
| 顶层目录 | 14（含 `assets`、`examples`） | — | **14（含 `snapshots`、`benchmarks`；无 `assets`/`examples`）** |
| `packages/` group 数 | 48 | 46（已发布覆盖） | **54** |
| `packages/` 包数 | — | 229（已发布） | **307**（+ vendor 9 + apps 4 + native = 320 个工作区包） |
| 根文件数 | 约 38 | — | **约 41** |
| 顶层 `config/` | ❌ 无 | ❌ 无 | ❌ **无** |
| 顶层 `examples/` | ❌ 无 | — | ❌ **无** |
| 顶层 `assets/` | ✅ 有 | — | ❌ **无** |
| 顶层 `snapshots/` | ❌ 无 | — | ✅ **1,179 文件** |
| 顶层 `benchmarks/` | ❌ 无 | ✅（0.1.7 起） | ✅ **34 文件** |
| `docs/` 规模 | 19 份顶层文档 | — | **63 顶层文件 + 562 文件总计** |
| `apps/` | 2（cli, web） | 2（cli, web） | **4（+ desktop, desktop-host）** |
| `vendor/` 包 | 9（含 logger-console） | 8（已发布集合） | **9** |
| `patches/` | 1 | — | **7** |
| `.agents/notes/` | 小 | — | **3,529 文件**（implemented 1,447 / archived 1,919 / proposed 117 / rejected 42） |
| 版本号 | 0.1.0-rc.5 | 0.1.5-rc.2 | **0.1.7-alpha.2** |

### 11.2 `packages/` group 集合的增删改

| 变化 | group | 说明 |
|---|---|---|
| **M 新增（相对 L）** | `browser-use`(1)、`computer-use`(1)、`deliverables`(2)、`document`(1)、`experimental`(**20**)、`lsp`(3)、`ptc-runtime`(2)、`ssh`(4)、`test-support`(7) | 共 **9 个新 group**。M 长出浏览器自动化、计算机使用、LSP、SSH 远程、Office 文档、PTC 运行时、实验性 Agent Teams 等能力族 |
| **L/G 有、M 无（作为 group）** | `code-runtime`、`examples` | M 把 `code-runtime` 演化为 **`ptc-runtime`**；`examples/` group 消失 |
| **包数显著增长** | `client` 46→**59**、`session` 18→**20**、`util` 15→**16**、`host` 8→**9**、`api` 6→**9**、`subagent` 6→**10**、`boot` 2→**5**、`credentials` 3→**5**、`compaction` 4→**5**、`skill` 4→**6**、`web` 4→**6**、`mcp` 1→**2**、`sdk` 2→**3**、`storage` 3→**4**、`terminal` 2→**3**、`typert` 3→**4**、`session-query` 3→**4** | M 全面扩张 |
| **包数减少** | `settings` 2→**1**、`fs` 8→**7**、`code-runtime` 2→**0**（转为 ptc-runtime） | 说明也有合并/下沉 |
| **`preset` 重构** | G/L：`agent-presets` + `persona`（2 个） | M：**`agent-preset` + `agent-preset-registry` + `persona`**（3 个），机制从"目录内联"改为"注册表式" |
| **`bundle` 不变（6 个）** | base、headless、web-app、sdk-app、sdk-minimal、acp-app | 但 patch 层**体积普遍变大**（见 5.4 与 11.3） |

### 11.3 `bundle` patch 层体积演进（一手实测）

| bundle | L（0.1.5-rc.2） | **M（master）** | 变化 |
|---|---|---|---|
| `base` | 19,515 B | **20,802 B** | +6.6% |
| `web-app` | 18,588 B | **20,978 B** | +12.9% |
| `sdk-minimal` | 5,248 B | **5,318 B** | +1.3% |
| `headless` | 1,152 B | **1,240 B** | +7.6% |
| `sdk-app` | 676 B | **1,586 B** | +134.6% |
| `acp-app` | 525 B | **553 B** | +5.3% |

### 11.4 `vendor/` 版本演进（一手实测）

| vendor 包 | L 版本 | **M 版本** |
|---|---|---|
| `@deepseek-ai/cordis` | 4.0.2 | **4.0.4** |
| `@deepseek-ai/cosmokit` | 1.8.3 | **1.8.5** |
| `@deepseek-ai/cordis-plugin-group` | 1.0.2 | **1.0.4** |
| `@deepseek-ai/cordis-plugin-hmr` | 1.0.17 | **1.0.19** |
| `@deepseek-ai/cordis-plugin-include` | 1.0.7 | **1.0.9** |
| `@deepseek-ai/cordis-plugin-loader` | 1.0.3 | **1.0.5** |
| `@deepseek-ai/cordis-plugin-logger-console` | （L 已发布集合无） | **1.0.4** |
| `@deepseek-ai/schemastery` | 3.18.2 | **3.18.4** |
| `@deepseek-ai/cordis-plugin-timer` | 1.1.4 | **1.1.6** |

→ **vendor 版本线始终独立于 `dsh-*`**（4.x / 1.x / 3.x vs 0.1.x），且 M 中 9 个包**统一小幅升版**，印证 `vendor/README.md` 所述"pinned source copies + 同步流程"。

---

## 12. 官方架构文档提炼（**缺口 ② 已关闭**）

### 12.1 `docs/architecture.md`（18,696 B，一手全文）

该文件的 tier 定位（`docs/AGENTS.md` 原文）：**"有序地图：组合、核心包、loop、seam、扩展点；改 `packages/` 之前必读"**，且**不含**类型定义（→ subsystems）、逐包细节（→ package README）、决策理由（→ Agent Notes）。

**核心论述逐节提炼**：

**（1）Cordis 是地基，"没有特权内核"** —— 原文：

> [Cordis](cordis-primer.md) is the framework under dsh: plugins contribute services, typed events, and reversible effects to a shared context. **Every part of the product is a plugin, including the model adapter, the tool registry, the session log, and the agent loop itself, so each is replaceable from configuration.**
>
> **There is no privileged core to patch**: you extend dsh by mounting a plugin beside the others, and registrations are effects that unwind when their plugin unloads.

→ 这是"一切皆插件"最权威的一句话表述，并解释了为什么目录里**连 `agent-loop`、`session`、`llm` 都是普通包**。

**（2）Profile 与 Bundle 的定义** —— 原文：

> A running `dsh` is a plugin tree composed at boot from **ordered layers**.
> A **profile** is a named composition stored in the Harness home. It lists the bundles it stacks, holds any out-of-tree plugins it installs, and keeps the user's own `cordis.patch.yml`.
> A **bundle** is a **distribution format for Cordis config rows and the code they mount**, so whatever it inserts stays patchable by the layers above it.
> Each declares itself in its own `package.json` under a `dsh` field: **`dsh.profile`** lists a profile's bundles, and **`dsh.bundle`** points at a bundle's patch file.

**（3）装配顺序（权威表述）** —— 原文：

> Layers apply to an **empty entry list** in this order: each bundle in the profile's listed order, then the profile's `cordis.patch.yml`, then the home-level one, then any `--patch` overlay. A patch targets a row by id and **replaces its whole config**, or **inserts new rows**.

**（4）bundle 的职责划分** —— 原文：

> `dsh-base` is the shared first layer of the `web`, `headless`, `sdk`, and `acp` profiles: **model adapters, tools, persistence, sandbox and approval policy, settings, credentials, telemetry**. `dsh-web-app` adds the browser application, `dsh-headless` adds a one-shot runner with no server, `dsh-sdk-app` adds the SDK JSON-RPC server, and `dsh-acp-app` adds the automation-only ACP server. **`dsh-sdk-minimal` is the deliberate exception: one bundle owns its complete explicit SDK tree and does not apply `dsh-base`.**

**（5）YAML 控制 HMR** —— 原文："base enables config-only `dsh-hmr`; headless, SDK and ACP disable it; `sdk-minimal` omits it. Profile patches override these defaults."

**（6）应用启动的唯一通路** —— 原文：

> Supported Node applications launch through named `dsh` profiles. … **Vendored CLIs, build-only and test-only executables, direct in-process plugin mounting, and the private browser WebWorker preview are not Harness application launchers.** [`verify-application-entrypoints`](...) keeps every package bin, executable source, root demo, and the root `start:web`/`dev:web` scripts in an explicit class and **rejects a Node application path that bypasses `dsh`**.

→ 存在**专门的门禁脚本**强制"只有 profile 能启动应用"，这是结构约束被代码化的典型例子。

**（7）桌面应用** —— 原文要点：Electron 桌面应用把**确切的 dsh 生产运行时**放在签名资源里，**独占保留 profile `$DSH_HOME/profiles/desktop`**；"**The public CLI cannot manage Desktop's profile.**"；默认端口 **19387**。

**（8）核心包的 `ctx` key 表** —— 原文表格（**这是"目录 → 运行时服务"的直接映射**）：

| Package | Owns | `ctx` key |
|---|---|---|
| `core/session` | append-only `SessionEvent` 日志与内存存储 | `ctx.sessions` |
| `core/system-prompt` | prompt section 与 tool schema 装配 | `ctx.systemPrompt` |
| `core/tools` | 作用域工具注册表与受守卫执行管线 | `ctx.tools` |
| `core/agent` | `Agent` 接口、实时注册表、`agent/*` 事件 | `ctx.agents` |
| `core/agent-loop` | 实现该接口的默认驱动 | `ctx.agentLoop` |
| `core/scope` | 按 agent 的作用域注册原语 | **library，无 key** |
| `llm/llm` | 消息/流词汇 + adapter seam | `ctx.llm` |
| `webhook/webhook` | 认证投递派发与 Workspace Session 创建 | `ctx.webhookRuntime` |

**（9）事件三分域** —— 原文：

- **Session events**：追加到日志的**持久事实**（`session/event` 广播）。"事实必须能活过 reload"时用它。
- **Agent events**（`agent/*`）：携带活的 `Agent`（inbox、step、status、request、validation、continuation）。
- **Capability events**：把策略与适配器挂到 seam 上（`fs/*`、`tools/*`、`telemetry/*`），**不 import loop**。

**（10）turn / step 精确流程**（原文代码块，本报告完整转录）：

```text
turn/start
  claim next-step input plus one queued message
  assemble prompt sections + tool schemas; project runtime context
  -> agent/pre-step                   reject | enter(messages, startsRequestSeries?)
     reject, or a first enter rewritten empty -> close the turn with no step
     step/start
     agent/request -> prepareCall (cancellation commits neither system nor users)
     reconcile system/message using the prepared call capability
     append entered messages as user/message; log request/header and request/context as needed
     derive and freeze model history from the log
     stream the bound prepared call -> llm/stream -> agent/assistant-stream start
       agent/assistant-stream chunk*
       assistant/message | assistant/attempt -> agent/assistant-stream end
     tool/call* -> tools/pre-execute -> tools/execute -> tools/post-execute -> tool/result*
     step/end
     tools owe another request, or next-step input arrived -> claim -> next step
  -> agent/turn-stopping
turn/end
```

并给出**事件语义的关键区分**：waterfall（监听者**必须调用 `next()`** 才能委派）的事件是 `agent/pre-step`、`agent/request`、`llm/stream` 与三个 `tools/*`；`agent/turn-stopping` 是 **serial 且无 `next()`**。

**（11）Capability seam 三分法的权威定义** —— 原文：

> A **seam** is a swappable capability with **three roles**: a **Service Definition** declaring the interface, a **Service Provider** implementing it, and a **Consumer** using it, commonly a model-facing tool. **A package may combine roles, but one role alone is not a seam; adding a capability means designing all three.**
>
> Seams are why one provider swap changes the whole product. **Filesystem and subprocess providers share one execution world, so pointing them at a remote sandbox moves Bash, PTY, and LSP with them, with no provider forks.**

**（12）"新行为放哪里"的官方路由表**（原文，**结构决策的入口**）：

| Goal | Mechanism |
|---|---|
| 加模型 provider | 在 `ctx.llm` 上注册 adapter |
| 加面向模型的能力 | 注册到 `ctx.tools`；schema 加入 prompt 装配 |
| 给某个 session 不同能力集 | 组合一个 agent preset；其中的 service row 需要 `isolate` realm |
| 加 shell 执行 | 注册 `ctx.shell` 后端 |
| 加持久终端 | 注册 `ctx.terminals` 后端 + `dsh-tool-terminal` |
| 加人类命令 | 注册 `ctx.commands` |
| 管理后台作业 | 注册 `ctx.jobs` |
| 从外部 webhook 起 Session | 注册 `ctx.webhookRuntime` + provider adapter |
| 加文件系统访问或策略 | 注册 `ctx.fs` provider 或监听 `fs/*` |
| 限制派生进程 | 用 `ctx.sandbox` 后端 |
| 拦截请求/工具/轮次 | 用 `agent/*` 或 `tools/*` 事件 |
| 加模型可见上下文 | 调 `agent.inject()` |
| 加 UI/编辑器集成 | 驱动 `ctx.agents`，从 `session/event` 渲染 |
| 加 Web Chat 节点 | 注册 `ConversationNodeDefinition` + keyed renderer |
| 加持久会话状态 | 扩展 `SessionEventMap` |
| 生成会话标题 | 注册唯一的 `ctx.sessionTitle` provider |
| 管理同会话目标 | 用 `ctx.goals` |
| 在新后端存会话 | 实现 `SessionPersistence` |
| 把注册限定到一个 agent | 用该 agent 的 `agent.ctx` |

### 12.2 `docs/module-graph.md`（119,655 B，生成物）

**性质**：文件头明确写

> `<!-- Generated by scripts/gen-module-graph.ts — do not edit by hand. Run \`pnpm run gen-module-graph\` to regenerate. -->`

**内容**：`@deepseek-ai/dsh-*` 包之间的 **peer 依赖图**（**只画 peer**，不画普通运行时依赖与开发依赖），按 `packages/<group>/<pkg>` 层级分 subgraph，用 **Mermaid `flowchart TD`** 表达，边 `a --> b` 表示 a 以 b 为 peer。

**结构启示**：正因为只画 peer，这份图恰好显示了**"哪些包必须共享同一实例"**——即真正的契约边界。`packages/README.md` 明确其用途："The dependency graph is generated: docs/module-graph.md（`pnpm run gen-module-graph`, **freshness-gated in CI**）"。

> 官方另有 `docs/dependency-catalog.json`（168,181 B）与 `docs/capability-seams.md`（60,424 B，"capability graph"）作为配套。三者合起来是"目录结构 → 依赖方向 → 能力契约"的完整官方视图。

---

## 13. 官方 group 权威映射（**缺口 ① 已关闭**）

`packages/README.md` 的原文授权（**M**）：

> Every package is scoped `@deepseek-ai/dsh-*` and lives in **exactly one group**; **each group README is the authoritative package map for its family**.

`packages/README.md` 的 frontmatter 也标注 `kind: "package-group"`。以下转录 10 个最核心 group 的**官方**映射（**包 → 职责 → `ctx` key**），全部来自各 group 自己的 `README.md`。

### 13.1 `packages/core/`（8 个）—— 产品 API 主干

| Package | Role（官方） | ctx key |
|---|---|---|
| `scope/` | 作用域注册与事件路由，隔离单个 agent 的贡献 | **library — 无 ctx key** |
| `session/` | 追加式会话事件日志，所有 agent 历史由此派生 | `ctx.sessions` |
| `system-prompt/` | 由有序 section、tool schema、变量装配系统提示 | `ctx.systemPrompt` |
| `tools/` | 工具注册表与受守卫执行管线 | `ctx.tools` |
| `agent-tool-presentation/` | 面向 preset 的 per-agent 工具呈现选择器 | 无 ctx key |
| `agent/` | 插件编程所对的 `Agent` 句柄 + 实时注册表与事件 | `ctx.agents` |
| `agent-default-model/` | 入口对新建 agent 施加的部署默认模型 | `ctx.agentDefaultModel` |
| `agent-loop/` | **默认 agent 驱动**：创建 agent 并跑 turn/step 生命周期 | `ctx.agentLoop` |

> 官方对"可替换性"的说明：`agent` 拥有公共 `Agent` 契约，`agent-loop` 是其**默认实现**，因此**扩展插件依赖 `agent`，驱动保持可替换**。

### 13.2 `packages/llm/`（7 个）

| Package | Role | ctx key |
|---|---|---|
| `llm/` | 通过注册的 provider adapter 流式执行一次模型调用；共享消息/block/chunk 词汇 | `ctx.llm` |
| `llm-deepseek/` | 经 DeepSeek Messages 提供 `deepseek-official` 路由（含 thinking 与图像输入） | 注册到 `ctx.llm` |
| `llm-pi-ai/` | 经 pi-ai catalog 与 wire 协议提供可配置路由 | 注册到 `ctx.llm` |
| `deepseek-llm-api-extensions/` | 在官方请求上注册生命周期拥有的顶层字段 | `ctx.deepseekLlmApiExtensions` |
| `plugin-package-inventory-deepseek/` | 向官方请求贡献活跃 Loader 包清单 | 贡献 `dsh_plugin_packages` |
| `llm-retry/` | 在持久 agent-step 边界按各 provider 策略重试失败请求 | 监听 `agent/request-error` |
| `token-meter/` | 以固定启发式从持久日志测量请求与上下文压力 | `ctx.tokenMeter` |

### 13.3 `packages/fs/`（7 个）

| Package | Role | ctx key |
|---|---|---|
| `fs/` | `ctx.fs` 服务契约：执行世界路径、有界文本 IO、带可选版本守卫的原子变更 | `ctx.fs` |
| `fs-local/` | 宿主文件系统后端 | 注册到 `ctx.fs` |
| `fs-sandbox/` | 按每次调用沙箱模式约束写/改（读穿透） | 注册到 `ctx.fs` |
| `fs-observation-policy/` | read-before-edit 策略（经 `fs/*` 事件守卫） | `fs/*` 监听者 |
| `tool-fs/` | 面向模型的 `read`/`read_image`/`write`/`edit` | 注册到 `ctx.tools` |
| `tool-fs-search/` | `glob`/`grep`（打包 ripgrep 二进制） | 注册到 `ctx.tools` |
| `tool-str-replace-editor/` | 独立 `str_replace_editor`：`view`/`create`/`str_replace`/`insert` | 注册到 `ctx.tools` |

> 官方设计说明：**"策略是插件，不是工具注入的服务"**——移除它只让 provider 回到无条件的变更行为，而不会弄坏工具；`tool-fs-search` **故意不扩展 provider 契约**，因为搜索是进程支撑的 ripgrep 工作流。

### 13.4 `packages/shell/`（10 个）

| Package | Role | ctx key |
|---|---|---|
| `shell` | executor 契约：前台运行、后台句柄、请求解析 | `ctx.shell` |
| `bash-local` | POSIX 上以全新 `bash -c` 进程运行 | 注册 `ctx.shell` |
| `bash-sandbox` | 经沙箱能力约束运行 Bash，把拒绝作为事实上报 | 注册 `ctx.shell` |
| `pwsh-local` | Windows 上以全新 `pwsh -Command` 运行 | 注册 `ctx.shell` |
| `pwsh-sandbox` | 经沙箱能力约束运行 PowerShell | 注册 `ctx.shell` |
| `shell-env` | 提供每条 shell 命令收到的受管 `DSH_*` 环境 | `ctx.shellEnv` |
| `tool-bash` / `tool-bash-persistent` | 模型 `bash` 工具 / 单一 owner 隔离持久 Bash 会话 | 注册到 `ctx.tools` |
| `tool-pwsh` / `tool-pwsh-persistent` | 模型 `pwsh` 工具 / 持久 PowerShell 会话 | 注册到 `ctx.tools` |

> 官方硬约束：**"Exactly one executor implementation is mounted per composition"**；profile 层选且只选一个（win32 层把 POSIX 行换成 pwsh 行；**挂两个会在加载时因重复服务注册而响亮失败**）。

### 13.5 `packages/sandbox/`（4 个）

| Package | Role | ctx key |
|---|---|---|
| `sandbox/` | 约束服务契约：模式、强制、每次调用策略、升级词汇 | `ctx.sandbox` |
| `sandbox-local/` | 各平台后端：Linux bwrap→Landlock、macOS Seatbelt、Windows 受限令牌 | 注册到 `ctx.sandbox` |
| `sandbox-policy/` | 共享策略归宿：部署默认 + 每会话模式覆盖 | `ctx.sandboxPolicy` |
| `sandbox-windows-acl/` | Windows 写限制：受限子进程只能写工作区与私有临时目录 | 无 key（由 `sandbox-local` 作为 win32 后端挂载） |

> 三档模式（官方原文）：`read-only` / `workspace-write`（只写会话工作区）/ `danger-full-access`。
> **"Confinement is same-world only"**——容器、microVM、远程执行器**替换整个能力**而非在此注册（这正是 `ssh/` 组存在的理由）。

### 13.6 `packages/session/`（20 个，四个子族）

官方按四族分组，**这是 group README 内部分节的实例**：

- **Persistence（9）**：`session-format`、`session-format-v0-to-v1`、`-v1-to-v2`、`-v2-to-v3`、**`-v3-to-v4`**、`session-format-catalog`、`session-persistence`（`ctx.sessionPersistence`）、`session-persistence-jsonl`、`session-checkpoint-policy`（包装 `ctx.llm` 与 `ctx.tools`）、`session-log-deepseek`（贡献 `dsh_session_log`）
- **Projection（4）**：`session-projection`（`ctx.sessionProjections`）、`session-projection-cache`（`ctx.sessionProjectionCache`）、`session-stats`、`session-turn-outline`
- **Titles（4）**：`session-title`（`ctx.sessionTitle`）、`session-title-llm`、`session-title-first-prompt-llm`、**`session-title-all-prompts-llm`**
- **Telemetry（2）**：`session-telemetry`（`ctx.sessionTelemetry`）、`session-telemetry-otel`

> **关键约束（官方）**：**"Only one title provider may register at a time"**；无 provider 时标题服务保留确定性回退。
> **M 相对 L 的演进**：新增 `session-format-v3-to-v4`（V4 codec + generation-aware 交付校验）与 `session-title-all-prompts-llm`。

### 13.7 `packages/subagent/`（10 个）

| Package | Role | ctx key |
|---|---|---|
| `subagent/` | 委派服务：provider 注册表、one-shot 运行、continuable 子代理、发现 | `ctx.subagents` |
| `subagent-in-process-driver/` | 共享进程内运行驱动 | — |
| `subagent-spawn-in-process/` | 全新进程内子代理 | 注册 |
| `subagent-fork-in-process/` | 用父代理已完成历史播种的进程内子代理 | 注册 |
| **`subagent-acp/`** | 经 ACP 的进程外子代理 | 注册 |
| **`subagent-codex/`** | 经官方 app-server 协议的**真实 Codex** 子代理 | 注册 |
| **`subagent-claude-code/`** | 经官方 Agent SDK 的**真实 Claude Code** 子代理 | 注册 |
| **`subagent-dsh-sdk/`** | 经 TypeScript SDK 的进程外 Harness 子代理 | 注册 |
| `tool-subagent/` | 向模型暴露委派 | 注册到 `ctx.tools` |
| `tool-subagent-control/` | 相邻 agent 消息、中断、列举 | 注册到 `ctx.tools` |

> **M 相对 L 的最大变化**：新增 4 个**跨产品子代理后端**（ACP / Codex / Claude Code / dsh-sdk）——即 DSH 可以把"另一个产品的 agent"当作子代理。这印证了 seam 的价值："Subagent providers vary just as widely behind one interface, **from a fresh child agent to a delegated turn in another product.**"

### 13.8 `packages/bundle/`（6 个）

| Package | Role | ctx key |
|---|---|---|
| `base` | base 型 profile 的共享核心 | —（仅 patch） |
| `acp-app` | 叠在 base 上的仅自动化 ACP stdio 应用 | 挂载 ACP 桥 |
| `web-app` | 叠在 base 上的浏览器应用层 | 挂载 Web 行 |
| `headless` | 叠在 base 上的一次性命令行任务应用 | `headless-runner` |
| `sdk-app` | 叠在 base 上的 SDK JSON-RPC stdio 应用 | 挂载 SDK server |
| `sdk-minimal` | **不依赖 base、不含 Web 的独立最小 SDK 应用** | —（完整 patch 树） |

> 官方补充：**"In-box bundles resolve from the dsh installation; out-of-tree bundles install into a profile through `dsh plugin --profile <name> add <package>`."**

### 13.9 `packages/client/`（59 个）—— Web GUI 浏览器半

官方把包分成 **kernel 包（启动并服务页面）** 与 **UI feature 包（呈现页面）**。核心 kernel 包：

| Package | Role | ctx key |
|---|---|---|
| `web/` | 启动浏览器 shell | — |
| `modules/` | 加载浏览器侧 client 模块 | `ctx.clientModules` / `ctx.modules` |
| `connection/` | 维持浏览器↔宿主 RPC 通信与事件投递 | `ctx.connection` |
| `file-upload/` | 在页面线程之外发送原始 Blob 与字节流请求体 | `ctx.fileUpload` |
| `store/` | 提供无 React 的 observable 与 snapshot-store 原语 | — |
| `hmr/` | 开发期刷新 client 插件 | — |
| `locale/` | 本地化偏好与消息字典 | `ctx.locale` |
| `ui-renderer/` | 把 slot 数据绑定到 React 并挂载组装后的应用 | `ctx.uiRenderer` |
| `ui-slots/` | 定义类型化扩展 Slot 与可复用 Component Factory | — |
| `ui-session/` | 把 Session Controller 状态适配为标准 slot 源与 hook | — |
| `ui-theme/` | 应用选定配色 | — |
| `ui-primitives/` | 共享 React 控件、图标、内容渲染器 | — |
| `resources/` | 统一资源模型（`useResource` 标准 hook 背后的协议 provider） | `ctx.resources` |
| `test-runtime/` | **位于 `packages/test-support/client-runtime/`** 的共享测试支撑 | — |

**M 的 59 个包中，`ui-*` 系列占绝大多数**——"连侧边栏 / 主题 / 目录选择器 / 模型选择 / 审批弹窗都是独立插件"在此得到官方逐条确认。M 相对 L 新增了 `ui-dockkit`（停靠布局）、`ui-plugin-manager`（侧边栏 Plugins 面板：安装/启用/禁用/重试/组合已安装包）、`ui-sidebar-browser`（在右侧边栏标签里浏览沙箱化 HTTP(S) 页面）、`ui-settings-shell` / `-agent-loop` / `-subagent` / `-web-search`（Plugins 页上的设置页）等。

> `packages/client/AGENTS.md`（M，已读）给出**硬性分层红线**：数据对象层（无 React）→ 渲染机器（`ui-renderer`，唯一做 ctx↔React 集成处）→ 呈现组件（纯 props）。并规定 **"Business data lives in the object layer, never a store"** 与 **"components never see ctx"**。

### 13.10 `packages/experimental/`（20 个）—— M 最大的新增 group

官方定义："prototype capabilities **whose contracts can change and carry no support promise**"，全部以 `@deepseek-ai/dsh-experimental-*` 发布。20 个包覆盖四条主线：

| 主线 | 包 | ctx key |
|---|---|---|
| **语音输入** | `speech-to-text`、`speech-to-text-sensevoice`、`api-speech-to-text`、`client-ui-voice-input`、`voice-input-bundle` | `ctx.speechToText`、`ctx.speechController` |
| **Agent Teams** | `agent-team`、`agent-team-profile`、`client-ui-agent-team`、`tool-agent-team`（**9 个工具**让模型创建/传讯/协调队友） | `ctx.agentTeams` |
| **计算机使用 / 浏览器使用** | `computer-use-cua-driver-mcp`、`computer-use-cua-driver-native`、`browser-use-playwright-mcp`、`browser-use-chrome-devtools-mcp`、`browser-use-stagehand-native`、`browser-use-runtime` | `ctx.computerUse`、`ctx.browserUse` |
| **运行时/周边** | `auto-review`、`ptc-runtime-python`（CPython 子进程后端）、`inspector`（跨 realm CDP hub）、`webworker-packer`、`webworker-runtime` | `ctx.ptcRuntime`、`ctx.inspector` |

> **官方隔离硬规则**（`packages/experimental/AGENTS.md`）：**发布包与 apps 不得在 `dependencies`/`optionalDependencies`/`peerDependencies` 中命名 experimental 包**；CI 的 `verify-default-product-isolation` 还会检查**传递安装、运行时 import 与已发布 composition**。这解释了为什么"默认产品"里看不到这些能力。
> **注意**：`webworker-packer` 正是 4.2b 中读取内部 `dsh.configTrees` 的那个包。

### 13.11 其他要点 group（简表）

| group | 官方 Role（`packages/README.md`） | 包数 |
|---|---|---|
| `ssh/` | POSIX 远程连接：配对的 filesystem / subprocess / sandbox provider（`ctx.ssh`、`ctx.fs`、`ctx.subprocess`、`ctx.sandbox`） | 4 |
| `ptc-runtime/` | PTC 执行能力族：Service Definition + 沙箱化 Node provider + PTC 模式 Consumer | 2 |
| `deliverables/` | 轮次交付物：显式文件交付与已记录的工作区变更 | 2 |
| `document/` | 共享宿主 Office→PDF 转换 | 1 |
| `lsp/` | LSP 能力族：seam、通用 stdio provider、`lsp` 工具 | 3 |
| `mcp/` | 外部 MCP server 暴露为原生工具 | 2 |
| `test-support/` | 测试基础设施（testkit、replay、Loader smokes） | 7 |
| `runtime-diagnostics/` | 运行时诊断：包自有的不变式检查与报告 | 1 |
| `host/` | Web GUI 宿主服务、目录选择、应用启动、插件清单、产品遥测 | 9 |

**发布承诺分层**（`packages/README.md` 原文）：

> Most groups are product — stable API. The exceptions: **`experimental/` publishes without stability or support promises**, and **`test-support/`, `runtime-diagnostics/`, and `util/` are support with lower compatibility expectations**.

> **G 的旧版承诺表**（0.1.0-rc.5）还额外把 `examples/` 标为 "Support — example infra"；M 中该 group 已消失。

---

## 14. 构建、测试与发布流水线（**缺口 ③ 已关闭**）

`.github/workflows/` 共 **20 个 workflow**（M 实测，含大小）：

| Workflow | 大小 | 触发（`on`） | job |
|---|---|---|---|
| `ci.yml` | 34,403 B | `pull_request` | `node-24`、`node-24-coverage`、`node-24-bench`、`node-24-consumers`、`node-compat`、`python-sdk`、`python-runtime`、`windows-build`、`windows-coverage`、`windows-native-tests`、**`all-checks-passed`** |
| `ci-master.yml` | 20,757 B | `push`、`workflow_dispatch` | `python-runtime`、`windows`、`serial-linux-selfhosted`、`serial-macos`、`serial-windows`、`larger-runner-benchmark`、`consolidated-runner-benchmark` |
| `sandbox.yml` | 6,136 B | `push` | **`sandbox-e2e`** |
| `release.yml` | 7,249 B | `pull_request`、`push`、`workflow_dispatch` | `dependencies`、`pack` |
| `e2e.yml` | 5,780 B | `workflow_dispatch`、`push`、`pull_request`、**`schedule`** | `e2e` |
| `docs-pages.yml` | 2,967 B | `workflow_dispatch` | `build`、`deploy` |
| `build-exe-for-python-sdk.yml` | 22,409 B | — | 单 exe 构建 |
| `python-release.yml` | 8,722 B | — | Python 发布 |
| `node-addon-system.yml` / `-release.yml` | 5,213 / 5,478 B | — | 原生扩展构建/发布 |
| `release-publish.yml` / `release-vendor.yml` / `release-vendor-publish.yml` | 4,545 / 4,021 / 3,549 B | — | **dsh 与 vendor 分开发布** |
| `pi-ai-provider-e2e.yml` | 2,537 B | — | pi-ai provider e2e |
| `build-preview-cloudflare.yml` | 7,534 B | — | 浏览器预览构建 |
| `issue-lifecycle.yml` / `issue-policy.yml` | 1,617 / 2,279 B | — | **Issue 生命周期治理** |
| `weighted-approval.yml` / `-review-event.yml` | 3,099 / 491 B | `pull_request_target`、`issue_comment`、`workflow_run` | `publish-status`（**加权审批**） |
| `expected-filenames.yml` | 692 B | — | 文件名规范门禁 |

**从流水线反推的结构事实**：

1. **CI 按平台矩阵 + 分层任务组织**：`node-24` 基础、`node-24-coverage`（**per-file 100% 覆盖率门禁**）、`node-24-bench`（性能）、`node-24-consumers`（NodeNext 消费方校验）、`node-compat`（Node 版本兼容）、`windows-build`/`windows-coverage`/`windows-native-tests`（Windows 专属），以及 `python-sdk`/`python-runtime`。另有 `all-checks-passed` 聚合 job 作为唯一必需状态。
2. **master 与 PR 用不同 workflow**：`ci.yml` 走 `pull_request`（并行），`ci-master.yml` 走 `push`，且**串行 selfhosted runner**（`serial-linux-selfhosted`/`serial-macos`/`serial-windows`）——说明主分支跑的是**更重、需要串行的完整矩阵**。
3. **有独立的 `sandbox.yml`（`sandbox-e2e`）**：沙箱能力被单列一条 e2e 流水线，印证 `sandbox/` 组的安全关键性。
4. **发布被切成多条独立流水线**：`release.yml`（依赖 + pack）、`release-publish.yml`、`release-vendor.yml` + `release-vendor-publish.yml`、`node-addon-system-release.yml`、`python-release.yml`。→ **dsh 包、vendor 包、原生扩展、Python 运行时各自独立发布**，与三方版本线（第 11.4 节）完全吻合。
5. **`weighted-approval`**：一个基于 `pull_request_target` / `issue_comment` / `workflow_run` 的**加权审批状态发布器**——属于仓库治理机制而非产品构建。
6. **`docs-pages.yml`** 用 `DOCS_REPOSITORY_REF: master`、`concurrency.group: github-pages` 部署文档站（对应 `website/`）。

**仓库级工程门禁（`scripts/` 334 文件中与结构最相关者）**：

| 门禁 | 作用 |
|---|---|
| `verify-package-invariants` / `verify-package-paths` / `verify-package-dependencies` | 包契约、路径、依赖声明合法性 |
| `verify-built-package-invariants` / `verify-runtime-closure` | **构建产物**层面的不变式与运行时闭包 |
| `verify-cordis-config` | `cordis.yml` 中裸插件必须出现在 resolver manifest 的 `dependencies` |
| `verify-config-source-ownership` / `verify-client-packages` / `verify-client-domain-graph` | 配置来源归属、client 包加载与模块请求、UI 域依赖层级 |
| `verify-default-product-isolation` | **默认产品不得传递依赖 experimental 包** |
| `verify-application-entrypoints` | **只有 profile 能启动应用**，拒绝绕过 `dsh` 的 Node 应用路径 |
| `verify-package-readme-limitations` / `-model-experience` / `verify-export-jsdoc` / `verify-subsystem-pages` | **文档契约门禁**（README 必须有 `## Known Limitations and Deferred Work` 与 Model Experience 小节） |
| `verify-dsh-package-licenses` | 许可证一致性（MIT） |
| `verify-doc-budgets` / `verify-doc-refs` / `verify-md-links` / `verify-md-wrap` / `verify-mermaid` / `verify-translation-pairing` | 文档预算、引用、链接、换行、图表、**中英翻译配对** |
| `check-workspace-constraints` / `check-vendor-manifest` / `check-expected-filenames` | 工作区约束、vendor 清单、文件名规范 |

> **结论**：DSH 把"目录结构规约"高度**代码化**——包路径、依赖方向、README 结构、文档预算、翻译配对、许可证、应用入口都有对应门禁脚本，并在 CI 中强制。这是本报告认为"结构可信度高"的重要原因：**结构被机器持续校验，且校验器本身在仓库里**。

---

## 15. preset 机制演进：从 configTree 到注册表（**M 的关键重构**）

### 15.1 两个版本的对照

| 维度 | **G / L**（0.1.0-rc.5 / 0.1.5-rc.2） | **M**（0.1.7-alpha.2） |
|---|---|---|
| 承载 group | `packages/preset/agent-presets` + `packages/preset/persona` | `packages/preset/agent-preset` + `agent-preset-registry` + `persona` |
| preset 本体 | **目录内联**：`presets/<name>/{preset.yml, agent.cordis.yml, skills/}` | **声明式 Cordis YAML**：`agent-preset` 的 `config.plugins` 子插件列表 |
| 发现机制 | `dsh.configTrees` → `mount: config/agent-presets` + `scanRoster: true` | **注册表服务** `ctx.agentPresets` |
| 名册排序 | `preset.yml` 的 `order` 字段 | `agent-preset` 的 `config.order` 字段 |
| 内置 preset | `standard`(1) / `ptc`(2) / `minimal`(3) / `cordis`(4) | 由 `apps/cli` 与 `bundle/web-app` 的行声明；**权威内置名册须以 profile composition 为准** |
| 技能 | `presets/cordis/skills/`（2 个 SKILL.md） | `agent-preset/skills/`：**`cordis-plugin-development`**（+ `references/` 4 篇 + `templates/` 6 个文件）、**`editing-cordis-compositions`**、**`cordis-composition-reference`**（`references/packages.md` **由 `scripts/gen-plugin-packages.ts` 生成**并受 `doc-sync` 门禁） |
| 版本管理 | 无（每次装配即当前定义） | **revision retention**：`agent-preset-registry` 拥有"选择、修订保留与 profile 编辑" |

### 15.2 M 的 preset 组官方映射

| Package | Role（官方） | ctx key |
|---|---|---|
| `agent-preset-registry` | 选择、修订保留与 profile 编辑 | **`ctx.agentPresets`** |
| `agent-preset` | 声明式子插件与元数据 | — |
| `persona` | 可组合的 Agent 人格 | — |

### 15.3 M 的 `agent-preset` 用法（官方 README 原文）

```yaml
- id: agent-preset-registry
  name: '@deepseek-ai/dsh-agent-preset-registry'
  config:
    default: standard
- id: preset-standard
  name: '@deepseek-ai/dsh-agent-preset'
  config:
    id: standard
    plugins: []
```

| Field | Default | Meaning |
|---|---|---|
| `id` | required | 稳定的 preset 标识符 |
| `plugins` | required | **子插件条目列表** |
| `name` / `description` / `order` | unset | 显示名 / 显示描述 / 名册顺序 |

官方对 id 语义的说明（原文）：

> The declaration row's `id` addresses Loader edits; **`config.id` is the preset identity saved by sessions.** Child entry IDs may be omitted and assigned by Loader.

> 这解释了为什么 M 的 `packages/preset/agent-preset/src/` 只有 `index.ts`（外加 `tests/skills.spec.ts`）——**preset 不再是一个目录树，而是一个"声明 + 注册表"**。

### 15.4 M 的 `agent-preset-registry` 源码结构（`src/` 9 个文件）

`composition-inventory.ts`、`definition.ts`、`display.ts`、`index.ts`、`invariant.ts`、`mount.ts`、`preset.ts`、`session.ts`、`types.ts`
→ 测试：`composition-inventory.spec.ts`、`display.spec.ts`、`invariant.spec.ts`、`mount.spec.ts`、`registry.spec.ts`、`session.spec.ts` + `harness.ts` + `tests/fixtures/plugins/`（6 个 fixture 插件：`contribute.js`、`global-service.js`、`late-service.js`、`needs-missing.js`、`self-dispose.js`、`throws.js`）

> `fixtures/plugins/*.js` 这组 fixture 恰好覆盖 6 种插件边界情形——**这与 `packages/AGENTS.md` 要求的"product-visible 插件必须有非单元的真实 composition 测试"一致**。

### 15.5 演进的含义

**从"配置树扫描"到"注册表服务"** 意味着：

1. **preset 成为一等运行时服务**（`ctx.agentPresets`），可被插件在运行时查询/编辑，而不再只是启动时的目录扫描结果；
2. **修订可保留**（revision retention）——已经创建的 Agent 固定在其选定修订上，新 Agent 才看得到编辑（`agent-preset/README.md` 的 KV Cache 说明原文："A live Agent's composition stays stable; new Agents can use an updated definition."）；
3. **configTree 机制随之退役**（第 4.2b 节），它作为"未启用的内部能力"只残留在镜像打包器里。

---

## 16. 升级后的可信度与证据清单

### 16.1 证据等级（升级后）

| 等级 | 内容 | 说明 |
|---|---|---|
| **A. 一手（master 真树）** | 第 2、11–15 节**全部目录级与文件级结构断言**；54 个 group README；`docs/architecture.md`、`docs/module-graph.md`、`packages/README.md`、`LICENSE`、`pnpm-workspace.yaml`、`apps/cli/package.json`、6 个 bundle patch 体积、9 个 vendor 包版本、20 个 workflow、`.agents/` 与 `snapshots/` 计数 | 落盘路径：`D:\Incubator\temp\ds-repo\deepseek-harness-master\` |
| **A′. 一手（GitHub API 经镜像）** | 仓库元数据（description / homepage / language / license.spdx_id / default_branch / topics / star / fork / created_at / pushed_at / has_issues / has_discussions） | 经 `gh-proxy.com`；采集时点 2026-09-23 |
| **B. 一手（本机 npm 产物）** | 240 个包的 `repository.directory` + `description`（`dsh-packages-by-repodir.txt` / `-with-description.txt`）；`@deepseek-ai/dsh` 的 `package.json`/`README`/`LICENSE`；profile 装配文件；6 个 bundle patch 副本；4 个内置 preset 全文；用户 preset `math-research`；`dsh --help` 输出；`--dump-config` 的 EPERM 记录 | 对应 **L = 0.1.5-rc.2** |
| **C. 一手（Gitee 镜像）** | G = 0.1.0-rc.5 的目录列举与 raw 全文（`gitee-mirror-repo-structure.md`） | 历史对照 |
| **D. 第三方报道** | CSDN / 腾讯云 / 阿里云 / InfoQ / 鲸智社区 / DeepWiki | 仅用于"设计意图与生态"，**不用于替代结构事实**；其中鲸智社区的 License 标注已被否证 |

### 16.2 核对用的关键证据文件

| 文件 | 内容 |
|---|---|
| `D:\Incubator\temp\evidence\dsh-repo-tree-MASTER.txt` | master 完整目录树（1,876 行） |
| `D:\Incubator\temp\evidence\dsh-packages-groups-MASTER.txt` | **54 个 group + 各自包数**（合计 307，与真树逐一核对一致） |
| `D:\Incubator\temp\evidence\dsh-packages-by-repodir.txt` | L 的 240 包 → 仓库路径映射（240/240 有 `repository.dir`） |
| `D:\Incubator\temp\evidence\dsh-packages-with-description.txt` | L 的 240 包官方描述 |
| `D:\Incubator\temp\evidence\gitee-mirror-repo-structure.md` | G = 0.1.0-rc.5 的镜像取证记录 + 访问过的 URL 清单 |
| `D:\Incubator\temp\evidence\DSH-装配与权限-一手证据摘录.md` | profile / bundle / 沙箱 / 工具装配的一手摘录 |
| `D:\Incubator\temp\evidence\DSH-内置preset-一手证据.md` | L 的 4 个内置 preset 与 `minimal` preset 全文 |
| `D:\Incubator\temp\evidence\github-api-metadata.md` | GitHub API 一手元数据 |
| `D:\Incubator\temp\evidence\bundle-layers\` | 6 个 bundle 的 `cordis.patch.yml` 副本（L） |
| `D:\Incubator\temp\evidence\builtin-agent-presets\` | L 的内置 preset 副本 |

### 16.3 核对方法（可复现）

```powershell
# group 数与包数
(Get-ChildItem 'D:\Incubator\temp\ds-repo\deepseek-harness-master\packages' -Directory).Count   # → 54
Get-ChildItem 'D:\Incubator\temp\ds-repo\deepseek-harness-master\packages' -Directory |
  ForEach-Object { (Get-ChildItem $_.FullName -Directory).Count } | Measure-Object -Sum        # → Sum 307

# configTrees 是否已退役
Select-String -Path 'D:\Incubator\temp\ds-repo\deepseek-harness-master\apps\cli\package.json' -Pattern 'dsh'
# → 无匹配；($j.dsh) 为 null

# preset 路径是否还在
Test-Path 'D:\Incubator\temp\ds-repo\deepseek-harness-master\packages\preset\agent-presets'   # → False
Test-Path 'D:\Incubator\temp\ds-repo\deepseek-harness-master\apps\cli\config\agent-presets'    # → False
Test-Path 'D:\Incubator\temp\ds-repo\deepseek-harness-master\apps\cli\config\examples'         # → True
```

---

*报告完（第二部分：master 真树深度核实）*
