# 线 C 开工简报（写面与设置写面）—— 交给 C 线子代理的唯一施工说明书

> 设计与裁定索引（**文件名以盘上为准**）：`draft/78-Web端三条主线（零交）拆解.md`（分工与零交）· `draft/73-Web端加强（按文件细化方案）.md`（逐文件方案）· `draft/74-前端×后端配合矩阵（按前端文件）.md`（每个按钮从哪读、写什么、配谁）· `draft/75-Web端伪代码（逐前端文件·互相对齐）.md`（契约 C1 端点 11 条 / C3 字段 / 判据 A–G）· `draft/76-待裁选择题（Web端·全部待裁项）.md`（裁定 C2/D2/E1/F1/G2/H1）· `draft/77-Web端施工台账与G2签字包.md`（**§2 就是你要照做的两份禁改区 patch**）。
> 施工前**先读这六份**。本简报只做索引、边界与纪律。

---

## 0. 身份与边界（**越界即整线返工；禁改区自签 = 直接打回**）

- 工作树：`temp/wt-c`（分支 `line-c`），**从 W0 合并后的 master 建**。
- 你**只许碰**这些路径（`draft/78 §2` 的 C 线 glob，与 A/B 零交，已由 `temp/_check_line_ownership.py` 机械核过）：
  - `agentflow/src/agentflow/webui/writes.py`（**新建**：三件写端点 + 授权 + 自己的 `ROUTES`/`type_decls()`）
  - `agentflow/src/agentflow/webui/audit.py`（**新建**：`web-actions.jsonl` 独立台账）
  - `agentflow/src/agentflow/settings.py`（**只加** `write_settings()`）
  - `agentflow/src/agentflow/web-actions.example.jsonl`（**新建**：示例/契约用的空台账）
  - `agentflow/tests/test_webui_writes.py` · `tests/test_webui_settings_write.py` · `tests/test_webui_browser.py`（**三份都新建**）
- **只能出 patch、不许落地**的两个文件（FC-27 禁改区）：
  - `pyproject.toml`（裁 F1：记 Playwright 依赖）
  - `tools/release_all.py`（裁 G2：发布门加前端步）
  ⇒ 你要做的是把 `draft/77 §2` 里那两份 patch **原样落到 `temp/` 下的 `.patch`/diff 文件**（带 `git apply --check` 的读数），交主控转 2 名 reviewer 签；**未签之前这两个文件一个字节都不许改**。
- **绝对不碰**：`webui/{__init__,server,routes,state,views}.py`（A 的）· `webui/readers.py`/`webui/sse.py`（B 的）· `sessions.py`/`userio.py`（B 的）· `tests/conftest.py`（B 的）· `ui/**` 与 `cli.py`（A 的；`--allow-writes` 这个开关由 **A 线**加，你只用它）· `draft/**`（只读）· `.gitignore`（主控的）。
- 加 `ROUTES`/`type_decls()` 只在自己的模块里声明（`routes.py`/`emit_types.py` 是拼接的，见 `draft/78 §3`），**不要改 A 的文件**。

## 1. 任务清单（按批次；每批做完就提交）

### C1 · 三个写端点（`webui/writes.py`，新建）
1. 照 `draft/75 §1.1` C1 的第 7–9 行实现（`/api/task` **不做**，裁定 I1）：
   - `POST /answer`（`qid` + `selected[]` | `text`）⇒ 走 **既有**函数 `userio.answer_question`（`userio.py:406`），不要另写一条写路径（今天的调用点在 `webui.py:974`）。
   - `POST /api/stop`（`reason` + `confirm=1` + 可选 `force`）⇒ `stopctl.request_stop_detail`（`stopctl.py:65`）/ `kill_registered`（`stopctl.py:392`）。
   - `POST /api/submit`（`topic`/`mode`/`content`/`providers[]?`）⇒ `interactions.next_prefixed_id`（`interactions.py:1233`）+ `store.tx`（`store.py:890`）+ 行对象的 `validate()`。**注意**：它**不走** `admit_search_request`（`interactions.py:1125`）—— 那是搜索请求的路，不是提交任务的路（这条曾经写错过，见 `draft/74` 的更正）。
2. **授权矩阵**（裁定 C2）：默认**只读**，写面必须显式开（`agentflow web --allow-writes`，开关由 A 线加在你的模块外）。四种拒绝情形都要有用例：未开写面 ⇒ 403；开了但没带确认 ⇒ 403/400（照 `draft/75` 定的口径）；未知端点 ⇒ 404；越权路径 ⇒ 404。**`/api/*` 的未知路径必须回 JSON 404，不许吐 HTML**（裁定 Q1）。
3. 每个写请求的响应形状是 `WriteResult`（`{ ok, tri, reason, id?, extra? }`，见 `draft/75 §1.3`）；**不许**在失败时假装成功（`ok=true` 而实际没写）。

### C2 · 独立审计台账（`webui/audit.py`，新建）
4. 裁定 D2：每次网页发起的写操作追加一行到 `<工作区>/web-actions.jsonl`（**独立于** `artifacts` 的台账）。字段照 `draft/74`/`draft/75` 的设计；要求：**每一次写都留档**（含被拒绝的尝试？—— 按 `draft/75` 的口径实现，若两处口径不一致就以 `draft/75` 为准并在报告里点名）。
5. `src/agentflow/web-actions.example.jsonl` 作为示例/契约样本入库（内容要是**真跑出来的一行**，不是手写的想象行）。

### C3 · 设置写面（`settings.py`）
6. 裁定 E1：`settings.write_settings()` 写机器级 `agentflow/settings.json`（既有 `settings.py:137 settings_path` / `:157 load_settings` 那一族；`AGENTFLOW_SETTINGS` 可覆盖）。硬要求：
   - **key 只写不读**：返回值里 `model.api_key` 恒 `***`；表单永不回填；判据要**正控**（写进去后文件里是真 key、响应里是 `***`）+ **负控**（把回显路径改坏 ⇒ 判据必红）。
   - **原子写**（写临时文件 + 替换）+ 文件权限收紧（Windows 上给出你能真跑出来的读数，别照抄 POSIX 说法）。
   - 未装/未配的分支要能返回 `unknown` 而不是崩。
7. 权限面与闸门：写设置这件事**必须**有既有闸门可走；**若你发现没有** ⇒ 按裁定 H1 **停下来报主控**（把"要不要新开一条闸门"做成选择题），**不许自己开路**。

### C4 · 浏览器端到端（opt-in）
8. 裁定 F1：`tests/test_webui_browser.py` 用 Playwright，**opt-in**（`-m browser`），默认不跑（本机没装 playwright 也应让整个套件正常收集/跳过——照既有 `pyproject.toml` 的 marker 约定；marker 的注册属于禁改区 ⇒ 若需要注册，写进 patch 交签，别自己加）。
   > **我核出来的一处不一致（已挂成待裁 T1，别自己拍）**：`pyproject.toml:69` 现在是 `addopts = "-m 'not network'"` —— 也就是说**只装了 playwright 的人跑 `pytest` 时，`browser` 用例会被真跑**，与"默认排除"并不等价（`marker` 描述写了"默认排除"，但没有任何一行把它排掉）。三种可能解法（① `addopts` 改 `not network and not browser` ⇒ 动了既有行，与 `draft/77 §2.2` 的"只加行"冲突；② `tests/conftest.py` 里注册 + 默认 deselect ⇒ 那是 B 的文件，跨线；③ 只靠"未装 ⇒ skip"来近似默认排除 ⇒ 与"opt-in"字面不符）**都还没裁**，写在 `draft/79` 的 T1 里。**你要做的**：按 `draft/73 §2.8` 的形状写（`pytestmark = [pytest.mark.browser]` + 未装 `⇒ skip` 且注明"这是 unknown 不是 pass"），**把三种解法的代价与你的读数写进报告**，等 `draft/79` 的 T1 裁下来再落那一行；**不许**自己去改 `addopts`、**不许**去改 B 的 `conftest.py`。
9. 判据五条照 `draft/73` 的表：至少要覆盖"开写面前点按钮 ⇒ 403 提示"、"确认后提交 ⇒ 台账多一行"、"key 填了但页面/响应都不回显"。

### C5 · G2 两份 patch
10. 从 `draft/77 §2` 抄成两个 diff 文件落在 `temp/`（例如 `temp/_g2_pyproject.patch`、`temp/_g2_release_all.patch`），并给出 `git apply --check` 的原文读数。**不许** `git apply` 到工作树、**不许** `noai_gate --approve`。

## 2. 你的收工门（自己跑）

```powershell
cd <worktree>\agentflow
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="<worktree>\agentflow\src"
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_webui.py tests/test_webui_contracts.py tests/test_webui_writes.py tests/test_webui_settings_write.py
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_settings.py tests/test_webui.py   # 你动过 settings，设置面必须仍绿
python -B -m pytest -q -p no:cacheprovider -p no:randomly tests/test_release_all.py                    # 发布面相邻（你出 patch 但不落地）
python -B scripts/lint_rules.py                 # 必须 error 0
python -B scripts/noai_gate.py --git            # 只能是你那两份"未落地 patch"以外的 1 条既有命中
```

> 动手前先自己 `Get-ChildItem tests -Filter 'test_*.py'` 核一遍文件名（简报里的名字我核过，但以盘上为准）。

## 3. 报告格式（**缺一项就算没交付**）

```
### 交付
- 改了哪些文件（逐条 file:line；新建的写"新建 + 公开名清单"）
### 判据读数
- 每条新判据：用例名 + 正控 + 负控（贴红的原文行，再撤回）；负控必须"红前绿后"
### 授权矩阵实测
- 四种拒绝情形各自的 HTTP 码 + 你跑出来的原始输出行
### key 不回显（裁定 E1）
- 文件里是什么、响应里是什么、页面里是什么 —— 三处读数
### G2 patch
- 两个 patch 文件的路径 + `git apply --check` 原文 + 一句"未落地、待人签"
### 没做 / 阻塞 / 待裁（H1 触发就写这里）
### 证据物
- 落盘探针/输出路径 + 重算命令
```

## 4. 纪律（违反了主控会打回，不代签）

1. **锚点纪律 A**：引用必须给盘上真存在的 `file:line` 或可重算命令；不确定就写"我没验"。
2. **负控红前绿后**：写不出负控的判据等于没有判据。
3. **禁改区不许自签**：`pyproject.toml` / `tools/release_all.py` **只出 patch**；不许 `noai_gate --approve`；不许"就一行"。
4. **不许新开写路径**：任何本次不在 `draft/75` C1 表里的写端点都不许做；H1 触发了就停下报主控。
5. **不许逐条重冻 `tests/golden/*.json`**（真红了写报告）。
6. **R009**：Python 注释/文档串里不许成对 `**` 或 emoji。
7. **`draft/` 只读**；`.gitignore`/`temp/` 探针归主控。
8. **不许"顺手"重构**：只做本线任务清单里的事。
