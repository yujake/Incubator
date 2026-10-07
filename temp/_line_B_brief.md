# 线 B 开工简报（只读面与索引）—— 交给 B 线子代理的唯一施工说明书

> 设计与裁定索引（**文件名以盘上为准**）：`draft/78-Web端三条主线（零交）拆解.md`（分工与零交）· `draft/73-Web端加强（按文件细化方案）.md`（逐文件方案）· `draft/74-前端×后端配合矩阵（按前端文件）.md`（每页要什么、后端从哪读）· `draft/75-Web端伪代码（逐前端文件·互相对齐）.md`（契约 C1 端点 11 条 / C2 事件 6 个 kind / C3 类型字段 / 判据 A–G）· `draft/76-待裁选择题（Web端·全部待裁项）.md`（裁定）· `draft/77-Web端施工台账与G2签字包.md`（台账）。
> 施工前**先读这六份**。本简报只做索引、边界与纪律。

---

## 0. 身份与边界（**越界即整线返工**）

- 工作树：`temp/wt-b`（分支 `line-b`），**从 W0 合并后的 master 建**。
- 你**只许碰**这些路径（`draft/78 §2` 的 B 线 glob，与 A/C 零交，已由 `temp/_check_line_ownership.py` 机械核过）：
  - `agentflow/src/agentflow/webui/readers.py`（**新建**：六面只读模型 + 自己的 `ROUTES` + 自己的 `type_decls()`）
  - `agentflow/src/agentflow/webui/sse.py`（**新建**：广播器 + `EVENT_KINDS`）
  - `agentflow/src/agentflow/sessions.py`（只加"趟次索引"那一族函数）
  - `agentflow/src/agentflow/userio.py`（只加裁定 L1 的"收敛入口"）
  - `agentflow/tests/conftest.py`（**J2/K2 两份夹具造在这里**；你独有，A/C 不许改）
  - `agentflow/tests/test_webui_readers.py` · `tests/test_webui_sse.py` · `tests/test_run_index.py`（**三份都新建**）
- **绝对不碰**：`webui/{__init__,server,routes,state,views}.py`（A 的）· `webui/writes.py`/`webui/audit.py`/`settings.py`（C 的）· `ui/**`（A 的）· `cli.py`（A 的）· `pyproject.toml`/`tools/release_all.py`（**禁改区**）· `draft/**`（只读）· `.gitignore`（主控的）。
- 你要往总路由/总类型表里加东西时**不要改 A 的文件**：W0 已经把 `routes.py` 写成 `READER_ROUTES + WRITE_ROUTES` 的**拼接**，`emit_types.py` 写成 `state.type_decls() + readers.type_decls() + writes.type_decls()` 的**拼接**。你只在**自己的** `readers.py` / `sse.py` 里声明，A 的文件自动带上（这就是"零交"的技术前提，见 `draft/78 §3`）。
- 需要 A/C 的文件 ⇒ 写进报告（"需要 A 提供 X，期望签名 Y"），不要自己动。

## 1. 任务清单（按批次；每批做完就提交）

### B1 · 六面只读模型（`webui/readers.py`，新建）
1. 六个适配器，各自对应 `draft/75 §1.1` 的 C1 第 1–6 行，返回形状照 `draft/75 §1.3` 的 C3 字段表（**字段名逐字，不许改写**）：
   - `state`（`GET /api/state`）：今天已有 `webui.snapshot`（`webui.py:401`）—— 你的工作是把它从"HTML 壳里的一坨"变成**签名稳定、可单测**的读模型，键集合要与 W0 之前的公开面一致（主控用 `temp/_verify_w0.py` 对账，你别改键名）。
   - `run`（`GET /api/run/{sid}`）：今天的 HTML 渲染在 `webui.py:1148`，你出 `RunView`（`Run` + `report` + `checkpoint`）。
   - `evidence`（`GET /api/evidence`）：数据源 `store.rows(...)`（逐字字段见 `draft/74 §1` 的"证据"一节）。
   - `artifacts`（`GET /api/artifacts`）：`artifacts.read_ledger`（`artifacts.py:235`）· `manuscripts.rows`（`manuscripts.py:119`）· `secretary.decisions_path`（`secretary.py:89`）。
   - `acceptance`（`GET /api/acceptance`）：`reviewaccept.check_review`（`reviewaccept.py:534`）+ `closing` 的 `out/paper/ACCEPTANCE-CHECKS.json`（真机读数：8 行 C1–C8，键 `id/kind/min/name/note`）。
   - `machine`（`GET /api/machine`）：`toolchain.toolchain_report`（`toolchain.py:325`，顶层键 `can_do_formal/lean_path/lean_ready/lean_version/mathlib/model/provers`）+ `settings.load_settings`（`settings.py:157`）。
2. **三态口径（裁定 N1 + `draft/74` 的证据规则）**：数据源不可读 ⇒ 记 `tri="unreadable"` 并说明原因；**不许**把"读不到"渲染成 `0`／空数组／`false`。空工作区 ⇒ `unknown`。
3. 每面在 `readers.py` 里加自己的 `ROUTES` 表项与 `type_decls()`（返回本面接口的 TS 文本），**顺序无关**。

### B2 · 趟次索引（`sessions.py`）
4. 按裁定 O2 建"后端 run-index"：`sessions.run_index_*`（读写）+ `reconcile_run_index`（对账）。它必须与 `sessions/*.jsonl` 的事件**现算结果逐趟一致**；手改索引一个字节要能红，删一场会话而索引还在要报 `drift`。
5. 判据 `tests/test_run_index.py`：正控（造两场会话 ⇒ 索引逐趟一致）+ **两条负控**（手改索引 ⇒ 红；删会话留索引 ⇒ 报 drift）。
> **命名撞车提醒（我核出来的，别踩）**：仓里**已经**有一个 `run_index`，但它是**另一个概念** ——
> `projects.py:242` 的 `run_index: int` 是"这个项目第几趟"，配 `projects.py:309 _next_run_index` 与
> 产物目录 `out/run-<n>`（例：`tests/test_projects.py:180` 断言 `res["run"]["run_index"] == 1`）。
> 裁定 O2 要的是**每个会话内部**的趟次索引（`draft/73` 第 64 行给的四个名字：
> `run_index_path / load_run_index / rebuild_run_index / reconcile_run_index`）。
> 两者可以共存（不同模块、不同语义），但**不许**去改 `projects.py` 的字段含义、也不许把 O2 的表塞进
> `projects.py`；`readers`/TS 侧若需要一个"第几趟"的字段，名字要自己说清是全局趟次还是会话内趟次。
> 若你认为这条需要所有者裁一个新名字 ⇒ 写进报告，**不要自己改名**。

### B3 · SSE 后端（`webui/sse.py`，新建）
6. `EVENT_KINDS` 定义在**你这里**（`draft/75 §1.2` 的 6 个 kind：`state` `question` `answered` `checkpoint` `stop` `heartbeat`），并实现 `GET /api/stream`（`text/event-stream`）。
7. 触发点照 `draft/75 §1.2` 的"后端触发点"列（如 `sessions.append:87` 之后发 `state`、`userio.ask_user:438` 发 `question`）。
8. 判据 `tests/test_webui_sse.py`：五条（含端到端"盘上新增 ⇒ 流里出现"）+ 负控（把 `EVENT_KINDS` 改坏 ⇒ A 线的 **B 事件对齐** 判据必红 —— 这条跨线负控你只需给出可复现的命令，改坏 A 的文件由主控演示）。

### B4 · L1 收敛（`userio.py`）
9. 把"待答/选项"的读取收敛到 `userio`（裁定 L1）：读的事件 kind 是 `user_question`（常量 `userio.py:85 ASK_KIND`），配对的是 `user_answer`（`ANSWER_KIND`）。收敛后现有待答判据必须仍绿。
10. 真机样本在盘上，别自己造幻觉数据：`agentflow/projects/p5-run7/sessions/real*.jsonl` 里有**真实未答**的 `user_question` 若干；`agentflow/projects/p9b-post-fix-replay` 是主控的对账工作区（`temp/_verify_w0.py` 用它）。

### B5 · 夹具（`tests/conftest.py`）
11. 按裁定 J2/K2：**用夹具造**六件产物样本 + 验证样本（`out/{experiments,paper,review,secretary,tasks}`、`runs/agent-<角色>-<sid>.json`、`verifications/<4位>.jsonl`）。真机读数作参照（`draft/74 §1` 与 `draft/77 §1` 有逐条出处）。
12. 夹具必须**在导入期把机器设置钉掉**（`AGENTFLOW_SETTINGS` 指到不存在的路径、清掉相关环境变量）—— 这是既有纪律，`tests/conftest.py` 里已有 `_pin_settings_path()`，你接着它写，不要另起一套。

## 2. 你的收工门（自己跑）

```powershell
cd <worktree>\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="<worktree>\agentflow\src"
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_webui.py tests/test_webui_contracts.py tests/test_webui_readers.py tests/test_webui_sse.py tests/test_run_index.py
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_sessions.py tests/test_sid_scoped_questions.py   # 你动过 sessions/userio，这两族必须仍绿
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_settings.py   # 三态/设置面
python -B scripts/lint_rules.py                 # 必须 error 0
```

> 注：本仓**没有** `tests/test_userio.py`（我核过 `tests/` 目录），userio 的相邻判据散在 `tests/test_sid_scoped_questions.py`（sid 级待答可见性，3 条）、`tests/test_agent_loop.py`、`tests/test_autonomy.py`、`tests/test_release_all.py` 里 —— 上面挑的是与你改动最贴的那两份。**别照抄任何简报里的文件名**，动手前先 `Get-ChildItem tests -Filter 'test_*.py'` 自己核一遍。

## 3. 报告格式（**缺一项就算没交付**）

```
### 交付
- 改了哪些文件（逐条 file:line 级别的说明；新建的写"新建 + 公开名清单"）
### 判据读数
- 每条新判据：用例名 + 正控（造数据 ⇒ 绿）+ 负控（改坏 ⇒ 红，贴红的原文行，再撤回）
- 负控必须"红前绿后"
### 与 A/C 的接口
- 我在自己的模块里加了哪些 `ROUTES` 表项 / `type_decls()` / `EVENT_KINDS`；期望 A 做什么、期望 C 做什么
### 没做 / 阻塞 / 待裁
### 证据物
- 落盘探针/输出路径 + 重算命令
```

## 4. 纪律（违反了主控会打回，不代签）

1. **锚点纪律 A**：引用必须给盘上真存在的 `file:line` 或可重算命令；不确定就写"我没验"。
2. **负控红前绿后**：写不出负控的判据等于没有判据。
3. **三态不许塌成二态**：`unreadable` / `unknown` 就是它们本身；这是本项目最贵的一类缺陷（把"没读到"说成"0"）。
4. **不许自签禁改区**、不许 `noai_gate --approve`、不许逐条重冻 `tests/golden/*.json`（真红了写报告）。
5. **R009**：Python 注释/文档串里不许成对 `**` 或 emoji。
6. **`draft/` 只读**；`.gitignore`/`temp/` 探针归主控。
7. **不许"顺手"重构**：只做本线任务清单里的事。
