# draft/73 Web 端加强 · 按文件细化方案

> ✅ **裁定已落地（2026-10-07）**：`A2 B1 C2 D2 E1 F1 G2 H1 | I1 J2 K2 L1 M2 N1 O2 | P1 Q1 R1 S1 T1` —— 逐题施工含义见 `draft/76` 顶部。
> 与本文件初版不同的四处（都标了 ⚠️）：**M2** `ui/src/types.ts` 改为**由 `agentflow/web/emit_types.py` 生成**（不是手写）；**J2 / K2** 六件产物与 V 的验证台账改为**用 `tests/` 夹具造样本**（页面要标明「夹具样本」）；**O2** 趟次改为**后端补索引**（不再每次从事件现切）。

> **这份文档是什么**：`draft/72`（详细设计）的**按文件落地版** —— 每个文件写清"现状 / 目标 / 要加的函数与签名 / 读什么写什么 / 判据怎么先在改前红 / 风险"。
> **默认口径**：`draft/72 §3` 那八道题**你还没点**，所以本文按我建议的那一列展开（题 A=`Preact+Vite` · B=`dist 入库` · C=`默认只读、写面显式开` · D=`独立网页操作台账` · E=`key 只写不读` · F=`Playwright opt-in` · G=`加发布门步（要你签）` · H=`停下来问`）。
> **若你改选**，受影响的行我在 §4 逐题点名（不用重写全文）。
> **本文不含实现**：它是施工图，不是施工。

---

## §0 三条会牵动既有判据的"形状事实"（先摆明）

1. **`webui.py` 要变成包 `webui/`** ⇒ 两处登记必须同步，否则**当场红**：
   - `tests/test_release_all.py` 的 `_AGENTFLOW_TOP_LEVEL_MODULES`（第 2387 行起；现在登记的是 `"webui.py"`）⇒ 改成 `"webui/"` 并改那行理由（判据 `test_agentflow_top_level_modules_match_the_registry` 逐名比对盘上与登记）。
   - `docs/READING-MAP.md`（判据 `test_every_filename_in_the_map_exists_on_disk`：**图里出现的每个文件名都必须真实存在**）⇒ 图里所有 `webui.py` 的写法要改成 `webui/` 或具体文件（`webui/server.py`）。
2. **静态资源（dist）默认不进 wheel**：打包是 `[tool.setuptools] package-dir={""="src"}` + `packages.find where=["src"]`，**没有** `package-data`。
   ⇒ 开发/可编辑安装（`pip install -e .` 或 `PYTHONPATH=src`）**照常工作**；只有"发布 wheel 也要带前端"时才需要动 `pyproject.toml` —— **那是 FC-27（release-deploy）**。见 §4 题 G。
3. **现在没有静态路由**：CSS 是 `webui.py:570` 把 `STYLESHEET` **内联**进 `<style>`；没有任何 `/static/*` 端点。W0 要新增静态路由（含 content-type、缓存、404）。

---

## §1 文件总览（新增 / 改动 / 删除，逐行：批次 · 一句话职责 · 碰不碰 FC-27）

### 1.1 前端工程（新目录 `agentflow/ui/`）

| 文件 | 批次 | 职责 | FC-27 |
|---|---|---|---|
| `ui/package.json` | W0 | 前端依赖与脚本（`dev`/`build`/`typecheck`） | 否 |
| `ui/pnpm-lock.yaml` | W0 | 锁定版本（可复现构建的前提） | 否 |
| `ui/vite.config.ts` | W0 | `base="/static/"`、`outDir=../src/agentflow/web/static`、哈希文件名、关 sourcemap | 否 |
| `ui/tsconfig.json` | W0 | TS 严格档（`strict`/`noUncheckedIndexedAccess`） | 否 |
| `ui/index.html` | W0 | 单入口壳（含 `<meta name="csrf-token">`） | 否 |
| `ui/src/main.tsx` | W0 | 挂载 + 客户端路由（六条页面） | 否 |
| `ui/src/types.ts` | W0 | **由 `agentflow/web/emit_types.py` 生成**（裁定 M2；手改必红） | 否 |
| `ui/src/api.ts` | W0/W1 | 全部 `/api/*` 的类型化封装 + CSRF + 错误三态 | 否 |
| `ui/src/sse.ts` | W2 | SSE 订阅 + `Last-Event-ID` 续传 + 降级轮询 | 否 |
| `ui/src/pages/Home.tsx` | W1 | 待回答面板（今天 `/` 的等价物） | 否 |
| `ui/src/pages/Run.tsx` | W1/W2 | 运行态：事件流 + 花销 + 停机状态 | 否 |
| `ui/src/pages/Evidence.tsx` | W1 | 证据链：命题/断言/猜想/实验/被拒 | 否 |
| `ui/src/pages/Artifacts.tsx` | W1 | 产物台账 + 六件产物 + 交接手稿/账本 | 否 |
| `ui/src/pages/Machine.tsx` | W1/W4 | 本机：doctor 读数（只读）+ 设置与 key（写面） | 否 |
| `ui/src/pages/Acceptance.tsx` | W1 | 收工门内容级验收（5 判据 + 5 辅助，逐条三态） | 否 |
| `ui/src/components/{Card,Badge,TriState,Table,Money,ConfirmButton}.tsx` | W0/W1 | 组件层（`TriState` 是"没查成"的视觉形态；`ConfirmButton` 管不可逆动作） | 否 |
| `ui/src/theme/app.css` | W0 | 应用样式（**只用令牌变量**） | 否 |
| `ui/src/theme/generated/theme.css` | W0 | **由 `assets.py` 生成的令牌文件**（见 §2.2） | 否 |

### 1.2 Python 服务层（`src/agentflow/webui.py` → 包 `src/agentflow/webui/`）

| 文件 | 批次 | 职责 | FC-27 |
|---|---|---|---|
| `webui/__init__.py` | W0 | **保持公开面不变**：`snapshot/render_root/render_run/serve/run/WebHandler/answer_text_of/option_view` | 否 |
| `webui/routes.py` | W0 | **路由表**（替掉 `if path == …` 链） | 否 |
| `webui/server.py` | W0 | `WebHandler` / `serve()` / `run()` / 静态路由 / 统一错误页 | 否 |
| `webui/state.py` | W0 | 今天的 `snapshot()` 与它的内部件（`_scan`/`_orphan_summary`/`_read_ledger`/`_read_report`/`_opts_view`…）**语义不变** | 否 |
| `webui/views.py` | W0→W5 | 旧的服务端渲染（`_page`/`_top`/`_question_card`/`_run_row`/`_event_card`/`render_root`/`render_run`/`_not_found`）——**并行期保留，逐面迁移后删** | 否 |
| `webui/readers.py` | W1 | **六个新面的读模型适配器**（见 §2.3） | 否 |
| `webui/sse.py` | W2 | 广播器 + 事件分帧 + 心跳 + 续传 | 否 |
| `webui/writes.py` | W3/W4 | 写面五个端点（answer/stop/submit/task/settings），**全部走既有闸门** | 否 |
| `webui/audit.py` | W3 | 网页操作台账 `web-actions.jsonl`（写 + 读） | 否 |
| `web/emit_theme.py`（新） | W0 | `assets.py` 的令牌 → `ui/src/theme/generated/theme.css`（确定性生成） | 否 |
| `web/assets.py` | W0 | **令牌单一来源**（语义不变；判据扩到"生成物与它一致"） | 否 |
| `web/static/`（新） | W0 | 构建产物落点（`index.html` + `assets/*.[hash].{js,css}`） | 否 |
| `settings.py`（改） | W4 | 新增 `write_settings(values, path=None, *, env=None)` —— **设置文件只有一个写入口** | 否 |
| `cli.py`（改） | W0/W3 | `agentflow web` 新增 `--allow-writes` / `--no-settings-write` / `--allow-host` 的说明与透传 | 否 |

### 1.3 判据（`tests/`）

| 文件 | 批次 | 判什么 | FC-27 |
|---|---|---|---|
| `tests/test_webui.py`（改） | W0 | 现有 17 条**保持全绿**（包化之后 import 路径不变） | 否 |
| `tests/test_webui_pages.py`（新） | W1 | 每页：该面的真读数出现 + 空态 + 三态 | 否 |
| `tests/test_webui_readers.py`（新） | W1 | 六个适配器：正控（造数据⇒读到）+ 负控（空工作区⇒`unknown`，不是 0） | 否 |
| `tests/test_webui_sse.py`（新） | W2 | SSE 五条（见 §2.4） | 否 |
| `tests/test_webui_writes.py`（新） | W3 | 授权矩阵 + 审计 + **不许绕闸门**的负控 | 否 |
| `tests/test_webui_settings_write.py`（新） | W4 | key 只写不读 / 原子写 / 权限 / 不回显（含扩展的 `_key_echo_problems`） | 否 |
| `tests/test_webui_static.py`（新） | W0 | 静态路由 + content-type + 哈希缓存 + **dist 新鲜度**（node 缺⇒`unknown`） | 否 |
| `tests/test_webui_browser.py`（新） | W4 | Playwright opt-in（`-m browser`） | 否 |
| `tests/test_release_all.py`（改） | W0 | 顶层模块登记：`"webui.py"` → `"webui/"` | 否 |
| `tests/conftest.py`（改） | W3 | 新增 `web_server` fixture（带 `allow_writes` 参数） | 否 |

### 1.4 文档与门

| 文件 | 批次 | 改什么 | FC-27 |
|---|---|---|---|
| `docs/USER-END-DSH-STYLE.md` | W4 | 新增"接口形状"一节：SSE 协议 / 写面端点 / 授权与审计 / 三态呈现 | 否 |
| `docs/READING-MAP.md` | W0/W4 | `webui.py` → `webui/`；新增 `ui/` 与 `web/static/` 的位置（**判据会核文件名真实存在**） | 否 |
| `README.md` · `docs/INDEX.md` | W0/W4 | `agentflow web` 的开关、`-m browser`、文件树 | 否 |
| `draft/72` · 本文 `draft/73` | 各批 | 实况与偏差回写 | 否 |
| `tools/release_all.py` | W4（仅题 G=B） | 加"前端构建/新鲜度"一步 | **是（要签）** |
| `pyproject.toml` | W4（仅题 G=B 或要发 wheel） | dev 依赖（Playwright）+ `package-data`（静态资源） | **是（要签）** |

---

## §2 逐文件细化

### §2.1 前端入口链（W0：先让"空壳 + 一条真数据"跑通）

**`ui/vite.config.ts`**
```ts
export default defineConfig({
  base: "/static/",                       // 与服务端静态路由前缀一致
  build: { outDir: "../src/agentflow/web/static", emptyOutDir: true,
           assetsDir: "assets", sourcemap: false,
           rollupOptions: { output: { entryFileNames: "assets/[name].[hash].js",
                                      assetFileNames: "assets/[name].[hash][extname]" } } },
  plugins: [preact()],
});
```
判据（`test_webui_static.py`）：产物里所有资源名带 `[hash]`；`index.html` 引用的每个 `assets/*` 都真的存在（**构建产物自洽**）。

**`ui/index.html`**：只留 `<div id="app">`、`<meta name="csrf-token" content="…">`（服务端渲染时注入）、`<link rel="stylesheet" href="/static/assets/app.[hash].css">`。
判据：**令牌不能写死**——断言 `index.html` 里没有任何真 token（服务端注入的是每进程随机值）。

**`ui/src/api.ts`**（六条页面共用的唯一出口）
```ts
export type Tri = "computed" | "unreadable" | "not_applicable";
export type ApiError = { code: number; reason: string; tri: Tri };
export async function getJSON<T>(url: string): Promise<T>;
export async function postJSON<T>(url: string, body: unknown): Promise<T>;  // 带 X-CSRF-Token
export const api = { state, run, evidence, artifacts, acceptance, machine,
                     answer, stop, submit, task, settings };
```
判据：每个端点在 `api.ts` 里**恰好出现一次**（反向：服务端路由表里的 `/api/*` 必须都能在 `api.ts` 找到调用者，或显式登记为"不给前端用"）。

**`ui/src/sse.ts`**
```ts
export function subscribe(sid: string, h: Handlers, opts?: { since?: number }): () => void;
```
内部：`new EventSource(\`/api/stream?sid=…&since=…\`)`；`onerror` **指数退避重连 3 次后降级**为 `setInterval(getJSON("/api/state"), 2000)`；返回 unsubscribe。
判据：`sse.ts` 里出现 `EventSource`、`Last-Event-ID`/`since`、以及**降级路径**三个符号（文本级断言）——这是"2B 真的接了"的最小机器读数（更强的在 §2.4）。

### §2.2 令牌单一来源（W0，关键：不重写 DSH 的皮）

**`web/assets.py`**（改）：保持 `THEME_CSS`/`APP_CSS`/`STYLESHEET` 三个常量与 `__all__` 不变；新增
```python
def theme_css() -> str: ...      # 今天的 THEME_CSS（语义不变，便于 emit 与判据共用）
```
**`web/emit_theme.py`**（新）
```python
def emit(target: pathlib.Path) -> bytes:      # 写 ui/src/theme/generated/theme.css
def main(argv=None) -> int:                   # python -m agentflow.web.emit_theme
```
生成物**确定性**（无时间戳、无随机、LF、末尾一个换行）。
判据（改 `test_webui.py::test_theme_css_keeps_dsh_tokens` 的邻居，新增）：
- 正控：`emit()` 的输出 == 盘上 `generated/theme.css`（**新鲜度**；不装 node 也能跑）；
- 负控：手改生成物一个字节 ⇒ 必红；
- 令牌纯度：`ui/src/theme/app.css` 里出现的颜色/间距值**必须是 `var(--…)`**（把现有 `test_app_css_uses_only_tokens` 的判据扩到前端源码）。

### §2.3 六个新面的读模型（W1 的主体）——`webui/readers.py`

一个面一个函数，**只读**、**三态**、**不吞异常**。统一返回形状：`{"tri": Tri, "rows": [...], "reason": str, "source": str}`。

| 函数（签名） | 读什么（既有实现，不另写一份） | 给哪一页 |
|---|---|---|
| `handoffs(root) -> dict` | `manuscripts.rows(root)` / `read_index(root)` / `handoffs_path(root)` | `Artifacts.tsx`（交接那一栏） |
| `artifact_ledger(root) -> dict` | `artifacts.read_ledger(root)` + `verify_entries(...)` + `owners_of(...)`/`unowned(...)` | `Artifacts.tsx` |
| `run_products(root, run_dir) -> dict` | 六件产物：`run-manifest.json`/`model-transcript.jsonl`/`evidence.json`/`claims.json`/`cost.json`/`report.md`（存在性 + `artifacts.sha256_of` + 行数/大小） | `Artifacts.tsx` / `Run.tsx` |
| `evidence_chain(store) -> dict` | `store.rows("statements"/"conjectures"/"experiments"/"review_findings")` + 计数与三态 | `Evidence.tsx` |
| `machine_readings(root) -> dict` | `toolchain.toolchain_report()` + `settings.load_settings()`（**key 走 `ModelSpec.redacted()`**）+ `settings.settings_path()` | `Machine.tsx` |
| `acceptance(root, *, project_dir, report_path, cap_usd) -> dict` | `reviewaccept.check_review(...)`，逐条用 `reviewaccept.CRITERIA`（5）与 `AUXILIARY_SIGNALS`（5）的名字 | `Acceptance.tsx` |
| `provider_states(store) -> dict` | `store.rows("search_requests")` 的 `providers` 点名 + 每条的三态 | `Run.tsx` 的"检索"那一栏 |
| `verifications(root) -> dict` | `verifications.list_verifications(root)`（V 的签位） | `Evidence.tsx` 的"证明级"那一栏 |

**判据**（`test_webui_readers.py`，每条两半）：
- 正控：在 `tmp_path` 造一份真数据（用 `tests/conftest.py` 的 `add_request/add_literature/…` 与 `manuscripts.record`？——**写手稿要走 `manuscripts` 的公开写入口**），断言读数出现在 JSON 与页面上；
- 负控（**这条最重要**）：把数据源清空/置不可读 ⇒ 该面必须是 `tri="unreadable"` + `reason` 非空，**不许**渲染成 `0` 或空白（"没查成 vs 查到 0"这条线是本仓库的老纪律）。

### §2.4 SSE（W2）——`webui/sse.py` + `test_webui_sse.py`

```python
def format_event(*, kind: str, data: Mapping[str, Any], event_id: int) -> bytes: ...
class Broadcaster:
    def __init__(self, *, max_subscribers: int = 8, heartbeat_sec: float = 15.0): ...
    def publish(self, kind: str, data: Mapping[str, Any]) -> None: ...
    def subscribe(self, sid: str | None) -> "Subscription": ...   # contextmanager
    def close_all(self) -> None: ...
```
`server.py` 的 `GET /api/stream`：校验 csrf（只读也要，防跨站读）→ 取 `since` → 先补发最近 N 条 → 进入循环（heartbeat / 新事件）→ 客户端断开或进程收尾时退出。
**五条判据**：① content-type + `Cache-Control: no-store`；② 首个事件在 1 s 内；③ 心跳周期（把心跳间隔做成可注入参数，判据用 0.2 s 跑）；④ `?since=N` 能补到 N 之后的事件；⑤ **端到端**：向工作区写一条新事件（`sessions.append`）⇒ 流里 1 s 内出现对应 `kind`。

### §2.5 写面（W3）——`webui/writes.py` + `webui/audit.py`

五个端点，**每一个都先问"既有闸门在哪"**：

| 端点 | 闸门（既有实现，必须走） | 返回三态 | 不可逆保护 |
|---|---|---|---|
| `POST /answer` | `userio.answer_question`（现状，不动） | 409/404 语义保持 | — |
| `POST /api/stop` | `stopctl.request_stop(...)`（优雅）/ 强制停也要经它 | `落开关了 / 没落成 + 理由` | `force` 需 `confirm=1` 二次确认（`ConfirmButton`） |
| `POST /api/submit` | **`cli.cmd_submit` 的等价物**：`interactions.next_prefixed_id(rows,"request_id","r")` + `store.tx("search_requests")` + `row.validate()`。⚠️ **更正**：I7 准入闸门（`interactions.admit_search_request`）**不在入队这一刻**，它在 A 领跑那一刻（`specs/a.py` 的 `search_literature`）——初版写错了，逐字读数见 `draft/74 §0.2` | `入队成功（回 request_id） / 整批不写 + 原因` | — |
| `POST /api/task` | ⚠️ **更正：没有既有后端入口**（`userio` 只有 M→user 的 `ask_user` 与 user→M 的 `answer_question`；CLI `inbox` 是"待答列表"不是信箱）⇒ 触发 `draft/72 §3` 题 H：**要么裁"新开一条用户→M 的通道"（可能落进权限面、要人审），要么这批不做** | （未定） | （未定） |
| `POST /api/settings` | `settings.write_settings(...)`（W4 新增，见 §2.6） | `written / refused / unknown` | 要求 `confirm=1` |

**授权（默认口径 C：只读默认、写面显式开）**
```python
def authorize(handler, *, root, allow_writes: bool, endpoint: str) -> tuple[bool, str]:
    # ① 必须是回环来源（Host/Origin 校验）② CSRF 令牌（复用今天的 _token_ok）
    # ③ allow_writes（--allow-writes 或网页里"启用控制"一次确认 + 会话 cookie）
```
判据（`test_webui_writes.py`）：
- 授权矩阵：无 CSRF⇒403 · 跨站 Origin⇒403 · `allow_writes=False`⇒403 · 未知 sid⇒404 · 闸门拒⇒**200/409 但正文如实回拒**（不是 500、也不是假装成功）；
- **审计**：每一次写（含被拒的）都落一条 `web-actions.jsonl`（`kind/端点/来源/参数摘要/结果/三态/时间`）；
- **不许绕闸门的负控**：把 `stopctl.request_stop` 换成"永远成功"的桩 ⇒ 审计里的 `result` 必须随之变（证明写路径真的经过它）；再用 monkeypatch 把 `interactions.admit_search_request` 改成"永远拒" ⇒ `/api/submit` 必须回拒 —— 两端都断言。

**`webui/audit.py`**
```python
def record(root, *, endpoint: str, source: str, params: Mapping[str, Any],
           result: str, tri: Tri) -> None     # 参数摘要：canonical JSON 后 sha256；api_key 等字段先替换成 "***"
def read(root) -> list[dict]                  # 读回来给人看（网页"操作历史"那一栏）
```
落点 `<工作区>/web-actions.jsonl`（**新建的文件名要在 `.gitignore` 的 §9/§10 家族里说明**：它是运行产物、不入库）。写用既有 `jsonlfile` 追加（单行原子追加 + 锁）。

### §2.6 设置写面（W4）——`settings.py` 加一个写入口 + `Machine.tsx`

**`settings.py`（改）**
```python
def write_settings(values: Mapping[str, Any], path: str | Path | None = None, *,
                   env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """合并写入设置文件（只认 TOOLCHAIN_KEYS/MODEL_KEYS/WORKSPACE_KEYS）；原子写；
    不返回 key（返回形状与 load_settings 同族，但 model.api_key 恒为 "***" 或 ""）。"""
```
判据（`test_webui_settings_write.py` + `test_settings.py` 各半）：
- 正控：写入 `toolchain.lean_bin` ⇒ 落盘内容正确（JSON 合法、其它段不丢）、`0600`（POSIX）/Windows 上如实说"靠 ACL"；
- key：写入后**响应里查不到真 key**（逐字符断言）、`load_settings()` 读到的是真值、`redacted()` 只给 `***`；
- 负控：写一半失败 ⇒ 原文件**逐字节不变**（原子写）；
- 未知键：直接拒（不悄悄写进去）。
**开关**：`--no-settings-write`（默认开；见题 E 的默认口径 A/B 差别）。
**风险如实写进 docstring**：这是"新增一条把密钥写到磁盘的路径"，所以它必须回环 + 审计 + 可关。

### §2.7 静态路由与错误页（W0）——`webui/server.py`

```python
def _static(self, path: str) -> bool:      # /static/<hash>：content-type 表 + immutable 缓存 + 404
```
- 命中规则：只允许 `/static/` 前缀 + 只允许 `web/static/` **之下**的真实文件（`Path.resolve()` 后必须仍在根内 —— 防目录穿越，判据要有负控 `..%2f`）；
- `index.html` 之外的未知路径 ⇒ 交给前端路由（吐 `index.html`），但 `/api/*` 未知 ⇒ JSON 404（**不要**吐 HTML，前端要能区分）；
- 错误页统一：`_error_page(code, reason, tri)`（沿用今天的 `_not_found` 的形态）。

### §2.8 浏览器端到端（W4）——`test_webui_browser.py`

```python
pytestmark = [pytest.mark.browser]
def test_the_panel_updates_without_a_reload(...)   # 打开 /，往盘上写一条待回答 ⇒ 页面 2 s 内出现（无刷新）
def test_the_settings_form_never_echoes_the_key(...)
def test_stop_requires_confirmation(...)
def test_no_console_errors(...)
```
- 驱动：Playwright（Python 包）；浏览器装在用户目录、**不进仓**；
- 没装 ⇒ `pytest.skip` **但要在标记登记处明说"这是 unknown 不是 pass"**（与 `-m network`、发布门 `unknown ≠ pass` 同一口径）；
- `pyproject.toml` 里加 `markers = ["browser: …"]` —— **若要把 marker 也登记进 pytest 配置，那要动 `pyproject.toml`（FC-27）**；替代做法：marker 只写在 `tests/conftest.py` 的 `pytest_configure` 里（不动禁改区）。**这一点在 §4 题 G 里一并裁。**

---

## §3 批次 × 文件 × 门

| 批 | 动到的文件 | 收工判据（改前必须能红） | 门 |
|---|---|---|---|
| **W0** | `ui/**`（骨架 6 个文件）· `webui/{__init__,routes,server,state,views}.py` · `web/emit_theme.py` · `web/assets.py` · `tests/test_webui_static.py` · `tests/test_release_all.py`（登记） · `docs/READING-MAP.md`（改名） | 静态路由/穿越负控 · 产物自洽 · 令牌新鲜度 · **现有 17 条全绿** | 全量门 |
| **W1** | `webui/readers.py` · `ui/src/pages/{Home,Run,Evidence,Artifacts,Machine,Acceptance}.tsx` · `ui/src/components/**` · `tests/test_webui_pages.py` · `tests/test_webui_readers.py` | 六个面各自的"真读数出现 + 空态 + `unknown` 不写成 0" | 全量门 |
| **W2** | `webui/sse.py` · `ui/src/sse.ts` · `tests/test_webui_sse.py` | SSE 五条（含端到端"盘上新增 ⇒ 流里出现"） | 全量门 |
| **W3** | `webui/writes.py` · `webui/audit.py` · `ui/src/components/ConfirmButton.tsx` · `tests/test_webui_writes.py` · `tests/conftest.py`（fixture） · `cli.py`（`--allow-writes`） | 授权矩阵 · 审计 · **绕闸门负控** | 全量门（若触发题 H=A ⇒ 停下等你裁） |
| **W4** | `settings.py`（`write_settings`） · `ui/src/pages/Machine.tsx` · `tests/test_webui_settings_write.py` · `tests/test_webui_browser.py` · `docs/USER-END-DSH-STYLE.md` · `README.md` · `docs/INDEX.md` · （题 G=B 时）`tools/release_all.py` · `pyproject.toml` | key 不回显/原子写/权限 | 全量门 + **重冻**（若牵动面） |
| **W5** | `webui/views.py`（删旧壳） · `draft/64`（§8.12） · `draft/71`·`72`·`73`（实况） | 旧壳删掉后 17 条仍全绿 | 全量门 |

---

## §4 你改选时，受影响的文件（对应 `draft/72 §3` 题 A–H）

| 题 | 若你改选 | 受影响的文件/行 |
|---|---|---|
| A 框架 | 选 Svelte / React / 纯 TS | 只有 `ui/**`（`package.json` 的 deps、`vite.config.ts` 的插件、`pages/*.tsx` 的后缀与写法）；Python 侧一行不改 |
| B dist 策略 | 选"不入库" | `ui/vite.config.ts`（产物流向 `temp/` 或 `web/static/` 但被忽略）· `tests/test_webui_static.py`（新鲜度判据改成"没构建⇒unknown"）· `README.md`（跑之前要 `pnpm build`）· `.gitignore` 加一行 |
| C 写面开关 | 选"默认开" | 只删 `webui/writes.py::authorize` 的第 ③ 条与 `cli.py` 的 `--allow-writes`；**风险面变大**（不可逆动作少一道门） |
| D 审计 | 选"只写既有事件" | 删 `webui/audit.py`，"操作历史"那一栏改读 `store.read_events()` |
| E key 策略 | 选 B（仅文件不存在时）或 C（每次 `--force`） | `settings.write_settings()` 的分支 + `Machine.tsx` 的表单状态机 |
| F 浏览器驱动 | 选 Selenium 或不上驱动 | 只有 `tests/test_webui_browser.py` 与（题 G 的）依赖 |
| G 发布门/依赖 | 选"不加" | `tools/release_all.py` 与 `pyproject.toml` **一行不动**；代价是发布门对前端记 `unknown` |
| H 无闸门时 | 选 B（网页层旁路） | **我会先把风险写成一页交你签**——因为那是在权限面之外开写路径（本仓库最硬的一条纪律） |

---

## §5 这份方案**不打算做**的事（免得范围漂移）

- 不动 `userio` / `stopctl` / `interactions` / `tools/base` 的既有语义（只调用，不改判据）。
- 不新开权限面条目（若需要 ⇒ 停下问你，见题 H）。
- 不把 CLI 搬进网页（`web` 仍是"用户端窗口"，不是"另一个 CLI"）。
- 不重写 DSH 的皮（令牌继续由 `assets.py` 单一来源，前端只消费）。
- 不改 `draft/` 与 `temp/` 里的历史读数（题 7A 继续生效）。
- 不在网页里做"跑一趟"的重活（启动 `run-agent` 属于编排动作，先不在这一批；要做另立一批并单裁）。
