# 线 A 开工简报（骨架与前端）—— 交给 A 线子代理的唯一施工说明书

> 这份简报是**可独立执行**的：它自己说清"只许碰哪些文件、每件做什么、怎么算做完、报告怎么写"。
> 设计与裁定索引（**文件名以盘上为准**）：`draft/78-Web端三条主线（零交）拆解.md`（分工与零交）· `draft/73-Web端加强（按文件细化方案）.md`（逐文件方案）· `draft/74-前端×后端配合矩阵（按前端文件）.md`（每个功能从哪读、展示什么、配谁）· `draft/75-Web端伪代码（逐前端文件·互相对齐）.md`（伪代码 + 契约 C1–C5 + 判据 A–G）· `draft/76-待裁选择题（Web端·全部待裁项）.md`（二十道题的裁定栏）· `draft/77-Web端施工台账与G2签字包.md`（批次台账）。
> 施工前**先读这六份**，不要凭本简报的转述就动手 —— 本简报只做索引与纪律，细节以那六份为准。
> 两条最常被问的口径先给出来（都出自 `draft/75`）：**端点契约 C1 共 11 条**（`GET /api/state` · `GET /api/run/{sid}` · `GET /api/evidence` · `GET /api/artifacts` · `GET /api/acceptance` · `GET /api/machine` · `POST /answer` · `POST /api/stop` · `POST /api/submit` · `POST /api/settings` · `GET /api/stream`；`/api/task` 因裁定 I1 **不做**）；**事件契约 C2 共 6 个 kind**（`state` `question` `answered` `checkpoint` `stop` `heartbeat`）。

---

## 0. 身份与边界（**越界即整线返工**）

- 工作树：`temp/wt-a`（分支 `line-a`），**从 W0 合并后的 master 建**，不要从旧点建。
- 你**只许碰**这些路径（这是 `draft/78 §2` 的 A 线 glob，主控用 `temp/_check_line_ownership.py` 机械核过它与 B/C 零交）：
  - `agentflow/ui/**`（Preact + Vite 应用；含 `src/types.ts` —— 它是**生成物**，不许手改）
  - `agentflow/src/agentflow/webui/{__init__,server,routes,state,views}.py`
  - `agentflow/src/agentflow/web/assets.py` · `web/emit_theme.py` · `web/emit_types.py` · `web/static/**`
  - `agentflow/src/agentflow/cli.py`（只动 `web` 子命令）
  - `agentflow/tests/test_webui.py` · `tests/test_webui_contracts.py` · `tests/test_webui_static.py` · `tests/test_webui_pages.py` · `tests/test_release_all.py`
  - `agentflow/docs/READING-MAP.md` · `agentflow/docs/INDEX.md` · `agentflow/README.md` · `agentflow/docs/USER-END-DSH-STYLE.md` · `agentflow/ui/README-DEV.md`
- **绝对不碰**：`webui/readers.py`/`webui/sse.py`/`webui/writes.py`/`webui/audit.py`（B/C 的）· `sessions.py`/`userio.py`/`settings.py`（B/C 的）· `tests/conftest.py`（B 的）· `pyproject.toml`/`tools/release_all.py`（**禁改区**，只有 C 线出 patch 且要人签）· `draft/**`（只读；要改设计就写进报告，主控自己落）· `.gitignore`（主控的）。
- 需要 B/C 的文件（比如要一个读模型函数）⇒ **在报告里写"需要 B 提供 X（期望签名 Y）"**，不要自己去改他们的文件、也不要自己复制一份。

## 1. 任务清单（按批次；每批做完就提交）

### W1（若你接手时 W0 已合并，则 W1 即当前批次）
1. **六页面**：`ui/src/pages/{Home,Run,Evidence,Artifacts,Machine,Acceptance}.tsx` —— 每一页的每个字段来自哪、展示成什么，照 `draft/74 §1` 那张矩阵**逐行**落（矩阵里每一行都写了"后端 file:line"与真机读数）。
2. **六组件**：`ui/src/components/**`（含 W3 的 `ConfirmButton.tsx` —— 你先建壳、把"确认后再 POST"的逻辑做成 props 驱动；它接的是 C 线的写端点，端点没上线时显示 `unknown` 而不是假装成功）。
3. **前端数据层**：`ui/src/api.ts`（路径字面量必须与 `routes.py` 的 `ROUTES` 逐字一致）· `ui/src/types.ts`（**由 `web/emit_types.py` 生成**，生成物与源码不一致必红）。
4. **三态词汇**：`draft/76` 裁定 N1 —— 两套三态词汇 + 组件映射；页面里**不许**把 `unknown` 渲染成 `0`/`——`/`false`。
5. **判据**：`tests/test_webui_pages.py`（每页一条：真读数出现 + 空态 + 三态）。

### W2（前端 SSE）
6. `ui/src/sse.ts`：`EventSource` 接 `/api/stream`，kind 集合**必须**等于 `webui/sse.py` 的 `EVENT_KINDS`（B 线定义）。这条对齐全靠判据 **B（事件对齐）**，它在本线的 `tests/test_webui_contracts.py` 里：集合不等就红。
7. 断线重连与"流里出现 ⇒ 页面出现"的端到端判据（那条判据要与 B 的 `tests/test_webui_sse.py` 分工：**B 管后端流，你管前端消费**，别重复造）。

### W4（文档）
8. `docs/USER-END-DSH-STYLE.md`（照着现有 DSH 风格写用户视角的用法）· `README.md` · `docs/INDEX.md` · `docs/READING-MAP.md` · `ui/README-DEV.md`（怎么装、怎么 build、怎么改 dist）。
9. 数字与文件清单以**盘上真读数**为准（`python -B temp/_verify_w0.py check` 那种"自己算一遍"的方式），不许照抄旧文档里的数。

### W5（旧壳清理，**放最后**）
10. 删掉 `views.py` 里的手写 HTML 渲染与 `web/assets.py` 里被 Preact 取代的样式 —— **每删一件都要先确认没有判据在读它**（`grep` 全仓 + 跑 `tests/test_webui.py`）。
11. 删完仍要全绿；`docs/READING-MAP.md` 同步。

## 2. 你的收工门（自己跑，不占主控那 18 分钟）

```powershell
cd <worktree>\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="<worktree>\agentflow\src"
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_webui.py tests/test_webui_contracts.py tests/test_webui_static.py tests/test_webui_pages.py
python -B scripts/lint_rules.py                 # 必须 error 0
python -B tests/test_agent_surface_snapshot.py  # 提示词/工具面快照：动了就红（见纪律 4）
```

**改过前端**：先 `pnpm build` 把 `agentflow/ui/dist` 重新构建并**一起提交**（裁定 B1：dist 入库；新鲜度由判据 G 把关），再跑上面的门。

## 3. 报告格式（**缺一项就算没交付**）

```
### 交付
- 改了哪些文件（逐条 file:line 级别的说明，不写"优化了若干"）
### 判据读数
- 每条新判据：用例名 + 正控（造数据 ⇒ 绿）+ 负控（把该红的地方改坏 ⇒ 红，贴出红的原文行，再把改动撤回）
- 负控必须"红前绿后"：先跑给你看它红，再跑给你看它绿
### 与 B/C 的接口
- 我需要谁提供什么（函数名 + 签名 + 期望返回形状）；我提供了什么给别人（同样写清）
### 没做 / 阻塞 / 待裁
- 逐条写清"为什么没做、卡在哪、需要谁裁"
### 证据物
- 落盘的探针/输出路径（`temp/<名>`），以及重算它的那条命令
```

## 4. 纪律（违反了主控会打回，不代签）

1. **锚点纪律 A**：任何引用（代码位置、读数、判据）必须给出**盘上真存在的** `file:line` 或可重算命令；不确定就写"我没验"，不许编。
2. **负控红前绿后**：新判据必须证明"该红的会红"。写不出负控的判据等于没有判据。
3. **不许自签禁改区**：`pyproject.toml` / `tools/release_all.py` 里的任何改动都要走 `draft/77 §2` 的签字包（2 位评审），**不许** `noai_gate --approve`，不许"顺手"改一行。
4. **提示词/工具面快照**：`tests/golden/*.json` 是禁改区，**不许逐条重冻**。你的改动若真让快照红了，把红的原文写入报告交主控裁。
5. **R009**：Python 注释/文档串里不许出现成对的 `**` 或 emoji（这是本项目反复踩的 lint 规则）。
6. **禁改区不代签、draft 只读**：设计有意见 ⇒ 写报告，不许自己去改 `draft/`。
7. **不许"顺手"重构**：本线的价值是"按方案落地"，任何方案外的改动都会被当成噪声（合并时要逐行看）。
