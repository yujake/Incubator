# draft/77 Web 端施工台账 + G2 签字包

> **这份文档两个用途**：① 逐批记**施工实况**（每批：范围 · 判据 · 状态 · 落点 sha · 读数）；② 把**题 G2 走回 FC-27 的两处改动**做成一个**可直接签的包**（我按 `draft/67` 的规矩只报备、不代签）。
> 相关文档：`draft/72`（设计）· `draft/73`（按文件施工图）· `draft/74`（前端×后端配合矩阵，带证据）· `draft/75`（伪代码与契约表）· `draft/76`（二十道裁定）。

---

## §1 批次台账（状态随施工更新）

| 批 | 范围（详 `draft/73`） | 判据（改前必须能红） | 状态（2026-10-07） | 落点 | 读数 |
|---|---|---|---|---|---|
| **W0** | **R1** `webui.py`→`webui/` 五文件拆包（公开面 re-export）· **Q1** 静态路由 `/static/*`（含目录穿越负控）+ SPA 回退（`/api/*` 未知 ⇒ JSON 404）· **M2** `emit_types.py`/`emit_theme.py` 两个生成器 · **A2/B1** `ui/` 骨架（Preact+Vite，dist 入库）· **S1** `tests/test_webui_contracts.py`（W0 新建）四条对齐判据 · **T1** CLI 两开关（先只解析透传） | ① 静态路由穿越负控 ② `/api/*` 未知不吐 HTML ③ 生成物新鲜度（手改必红）④ 契约 A–D（含负控）⑤ **现有 17 条 `test_webui.py` 全绿** | 🟡 **进行中**（独立线 `line-w0`，工作树 `temp/wt-w0`，基线 `65746a5`）；已落：`web/emit_theme.py`(2.9 KB) · `web/emit_types.py`(12.4 KB) · `ui/package.json` · `ui/vite.config.ts` · `ui/src/types.ts`(6.9 KB，生成物) · `ui/src/api.ts` · `ui/src/sse.ts`；**未落**：`webui/` 拆包、契约判据、dist 构建 | — | 待线回报（我按盘上产出核，不采信措辞） |
| **W1** | `webui/readers.py`（六面读模型）· 六条页面 · **O2** `sessions.run_index`（持久索引 + 与事件对账）· **L1** 待答/选项收敛到 `userio` · **J2/K2** 夹具造六件产物与 `verifications/<id>.jsonl` · 各页的"真读数出现 + 空态 + `unknown` 不写成 0" | 每面一条正控 + 一条"数据源不可读 ⇒ `tri=unreadable`"的负控；O2 索引对账（手改索引必红、删会话必报 drift）；L1 收敛后 `test_pending_list_is_never_filtered_by_session` 仍绿 | ⬜ 未开工（等 W0） | — | — |
| **W2** | `webui/sse.py`（`Broadcaster`/`format_event`/心跳/`since` 续传）· `ui/src/sse.ts` 的六 kind 注册 | 五条：content-type · 首个事件有界 · 心跳可注入 · `?since=` 补发 · **端到端"盘上新增 ⇒ 流里出现"** | ⬜ 未开工 | — | — |
| **W3** | 写面**三件**（`/answer` 既有 · `/api/stop` · `/api/submit`）· **D2** `web-actions.jsonl` 审计 · **C2** `--allow-writes` | 授权矩阵（无 CSRF⇒403/跨站⇒403/未开写面⇒403/未知 sid⇒404）· **每一次写都留审计** · **绕闸门负控**（把 `stopctl.request_stop_detail` 换桩 ⇒ 审计 `result` 必须跟着变） | ⬜ 未开工（**I1 已裁：`/api/task` 不做**；若触发 H1 ⇒ 停下问） | — | — |
| **W4** | **E1** `settings.write_settings()` + `Machine` 页写面 · **F1** Playwright `-m browser` · 文档同步（`USER-END-DSH-STYLE.md`/`README.md`/`INDEX.md`）· **G2 的两处禁改区 patch（需签）** | key 不回显（含响应/日志/事件流/构建产物四处）· 原子写 · 权限 · 浏览器五条 | ⬜ 未开工 | — | — |
| **W5** | **P1** 旧 `views.py` 清空（迁一面删一面）· 收尾：全量门 ·（若牵动面）一次性重冻 + 逐格归因 `draft/64 §8.12` · 台账回写 | 旧壳删净后 17 条仍全绿 | ⬜ 未开工 | — | — |

**每批收工的固定动作**（与 R 批同一纪律）：`python -B temp/_merge_gate.py --with-pytest`（逐节读数看 `temp/_merge_gate_report.md`）· **改前端 ⇒ 重建 dist 并提交后**才跑门 · 重冻只在必要且一次性做。

---

## §2 G2 签字包（两处 FC-27 改动；**我出 patch，人走查 + 2 名 reviewer 签**）

### §2.1 为什么这是禁改区
`tools/release_all.py` 与 `pyproject.toml` 都在 `.noai-paths` 的 `[category: release-deploy]` 里（"发出去就收不回来"）。按 `AGENTS.md`：**AI 可以写 patch，但必须由人逐行走查并留结论，且要 2 名 reviewer 批准**；`--approve` **只能由人跑**。

### §2.2 改动一：`pyproject.toml`（两处小改）
| 位置 | 现状（实测） | 要改成 | 为什么 |
|---|---|---|---|
| `[project.optional-dependencies]` | 已有一个可选依赖段（盘上已有若干组，组名以落地时为准） | 在**新增一个 dev/测试组**里加 `playwright`（若 `pytest-playwright` 也进，则一并加） | 题 F1 选的驱动要能被"按需安装"，而**不许进运行期依赖**（运行期仍然只有 `filelock`） |
| `[tool.pytest.ini_options] markers` | 现在有 `network` 等 marker（`pyproject.toml:70` 起） | 加一行 `browser: 需要 Playwright 与浏览器；默认排除，用 -m browser 显式运行（未装 ⇒ unknown，不是 pass）` | 题 F1 的 opt-in 通路；**"未装 ⇒ unknown"这句必须写进 marker 描述**（三态不许折平） |

> **落地形状**：**两处都是"加行"，不改任何既有行**（组名与位置照落地时的盘上结构抄）。若你更想"一个字节都不动 pyproject"，那就把 marker 注册改到 `tests/conftest.py` 的 `pytest_configure`（`draft/73 §2.8` 里有这条替代路径）—— 但那与题 G2 的裁定不符，需要你改口。

### §2.3 改动二：`tools/release_all.py`（加一步）
| 项 | 内容 |
|---|---|
| 现状 | `build_steps()` 现在给 **6 步**：`release-check · acceptance · repro · role-specs · coverage · per-file`（实测命令：`python -c "import sys,pathlib;sys.path.insert(0,'.');from tools.release_all import build_steps;print([s.key for s in build_steps(pathlib.Path('.').resolve())])"`） |
| 要加 | 第 **7** 步（建议 key：`frontend`）：① `pnpm -C agentflow/ui typecheck`（`tsc --noEmit`）② `pnpm -C agentflow/ui build` ③ **dist 与 src 一致**的新鲜度判据（`draft/75 §3-G`） |
| 三态（硬要求） | **没装 node/pnpm 或构建环境不可用 ⇒ 这一步记 `unknown`**，绝不记 `pass`（照 `overall()` 既有口径："跳过记 unknown 还是 pass"那一条取舍**不许被这次改动放松**） |
| 不许做的事 | 不许把这一步做成 `--skip` 的默认可跳过项；不许改 `overall()` 的判定语义；不许动既有 6 步 |

### §2.4 reviewer 该逐行走查什么（4 条，逐条要留结论）
1. **依赖只进 optional**：`playwright` 没出现在 `dependencies`（运行期）里 —— 运行期依赖仍然只有 `filelock`；
2. **marker 描述里有"unknown ≠ pass"**：拿掉那句就等于把三态折平；
3. **新步不放松既有取舍**：`--skip` 时那一步落 `unknown`（与既有六步同口径）；跑一次 `python -B tools/release_all.py --only frontend -q` 与**不装 node 的模拟**（把 `pnpm` 从 PATH 摘掉）各看一次读数；
4. **门自身仍报 requires_human**：落地后 `python -B scripts/noai_gate.py --git --since 6d9f0a3 --check-approvals` 里这两条会落 `stale`，是**预期**（签过的那一版不是现在这一版）。

### §2.5 签法（人在 `agentflow/` 下跑；我**不代签**）
```powershell
cd D:\Incubator\agentflow
# ① 登记（刷新 sha；**永远不写 reviewers** —— 登记 ≠ 批准）
python -B scripts\noai_gate.py --baseline --paths pyproject.toml --note "<谁写的这一段：release_all 的前端步 + dev 依赖；改了什么>"
python -B scripts\noai_gate.py --baseline --paths tools/release_all.py --note "<同上>"
# ② 批准（×2 名互相独立的 reviewer）
python -B scripts\noai_gate.py --approve pyproject.toml --reviewer <名字> --scope "<走查范围：§2.4 四条>"
python -B scripts\noai_gate.py --approve tools/release_all.py --reviewer <名字> --scope "<同上>"
# ③ 复核（必须带基线）
python -B scripts\noai_gate.py --git --since 6d9f0a3 --check-approvals
```

### §2.6 我（AI）在这件事上的边界
- **只报备、不代签**：两份 patch 由我写、由人逐行走查；
- 若你选"不加这一步"（题 G1），我**一个字节都不动**这两个文件，发布门对前端那一格记 `unknown`；
- 两处改动的**落地时机**：W4（前端与浏览器判据都在了之后）—— 在那之前动它会让门多两条待签而没有可验的东西。

---

## §3 W1–W5 的开工前置（等 W0 交什么）

| 后续批 | 需要 W0 先给 |
|---|---|
| W1 | `webui/` 包的公开面稳定 + `readers.py` 的落点已定（`webui/readers.py`）；`ui/src/types.ts` 由 `emit_types.py` 覆盖了六个只读面的行类型（W0 只覆盖到 snapshot 系，其余标 TODO ⇒ W1 补生成器） |
| W2 | `routes.py` 的 `ROUTES` 里已给 `/api/stream` 留位；`sse.py`/`sse.ts` 的 `EVENT_KINDS` 常量已成对存在 |
| W3 | `C2` 的 `--allow-writes` 已能透传到 `serve()`；`web-actions.jsonl` 的落点常量已在 `webui/audit.py` |
| W4 | `Machine` 页的只读半已能拿到 `toolchain_report()`/`settings.*`（W1）；`emit_types.py` 已覆盖 `MachineView` |
| W5 | 六条页面全部迁完（P1 才知道哪些旧函数可删） |
