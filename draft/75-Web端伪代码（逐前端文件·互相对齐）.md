# draft/75 Web 端伪代码（**逐前端文件 · 互相对齐**）

> **对齐是什么意思**：本文件里每个前端文件的伪代码，只允许使用**§1 契约表**里的名字；契约表里的每一行都必须能在**后端真实实现**上找到出处（`file:line`，证据规则见 `draft/74 §0.1`）。
> **对齐靠什么保证**（不是靠人记得）：**`tsc --noEmit`**（类型层）+ **§3 的四条契约判据**（名字层，正则级，改前能红）。
> **一句话纪律**：**契约表只有一份**（§1），页面与组件都从 `types.ts`/`api.ts` 读它；任何页面里出现契约表之外的名字 ⇒ 视为漂移。

---

## §1 契约表（唯一来源；每行都带后端出处）

### §1.1 C1 端点契约（`routes.py` ↔ `api.ts`）
| # | method + path | 请求字段（来自表单/JSON） | 响应类型 | 后端程序（出处） |
|---|---|---|---|---|
| 1 | `GET /api/state` | — | `StateSnapshot` | `webui.py:401 snapshot`（返回键逐字见 docstring `webui.py:404`） |
| 2 | `GET /api/run/{sid}` | — | `RunView`（`Run` + `report` + `checkpoint`） | 今天：`webui.py:1148` 渲染 HTML；W0 抽 JSON |
| 3 | `GET /api/evidence` | — | `EvidenceView` | W1 新增；数据源 `store.rows(...)`（见 §1.3） |
| 4 | `GET /api/artifacts` | 可选 `run_dir` | `ArtifactsView` | W1 新增；`artifacts.read_ledger:235` · `manuscripts.rows:119` · `secretary.decisions_path:89` |
| 5 | `GET /api/acceptance` | `project_dir` · `report_path` · `cap_usd?` | `AcceptanceView` | W1 新增；`reviewaccept.check_review:534` |
| 6 | `GET /api/machine` | — | `MachineView` | W1 新增；`toolchain.toolchain_report:325` · `settings.load_settings:157` |
| 7 | `POST /answer` | `qid` · `selected[]` \| `text` | `WriteResult` | `userio.answer_question:406`（经 `webui.py:974`） |
| 8 | `POST /api/stop` | `reason` · `confirm=1` · `force?` | `WriteResult` | `stopctl.request_stop_detail:65` / `kill_registered:392` |
| 9 | `POST /api/submit` | `topic` · `mode` · `content` · `providers[]?` | `WriteResult` + `request_id?` | `interactions.next_prefixed_id:1233` + `store.tx:890` + `row.validate()` |
| 10 | `POST /api/settings` | `toolchain.*` · `model.*` · `workspace.*` · `confirm=1` | `WriteResult`（**响应里 key 恒 `***`**） | W4 新增 `settings.write_settings(...)` |
| 11 | `GET /api/stream` | `sid?` · `since?` | `text/event-stream`（C2） | W2 新增 `webui.sse` |

> **对齐判据（§3-A）**：`api.ts` 里出现的路径字面量集合 **必须逐字等于** `routes.py` 的 `ROUTES` 里 `GET/POST` 的路径集合（`/api/*` 与 `/answer` 都算）。

### §1.2 C2 事件契约（`sse.py` ↔ `sse.ts`）
| kind | payload（字段） | 何时发 | 后端触发点 |
|---|---|---|---|
| `state` | `{ snapshot: StateSnapshot }` | 会话/台账有新行 | `sessions.append:87` 之后 |
| `question` | `{ qid, sid, role, text, options, multi, ts, timeout_sec }` | 新 `user_question` | `userio.ask_user:438`（写 `user_question`，常量 `userio.py:85 ASK_KIND`） |
| `answered` | `{ qid, sid }` | 新 `user_answer` | `userio.answer_question:406`（`ANSWER_KIND`） |
| `checkpoint` | `{ sid, role, step, stop_reason, waiting_for, spend }` | 检查点文件被改写 | `runs/agent-<角色>-<sid>.json`（`agent_loop.py:2922`） |
| `stop` | `{ stop_path, requested_by, at, live_pids, running_loops }` | 停机开关变化 | `stopctl.request_stop:105` / `clear_stop:215` |
| `heartbeat` | `{ at }` | 每 `heartbeat_sec` | 服务端计时器 |

> **对齐判据（§3-B）**：`sse.ts` 里 `EventSource` 注册的 kind 字符串集合 **必须逐字等于** `sse.py` 里 `EVENT_KINDS` 常量（一个模块级元组，两处比对）。

### §1.3 C3 类型契约（TS 接口 ↔ 后端真实字段；**字段名不许改写**）
> 下面的"字段"列**逐字来自盘上读数**（`draft/74 §1` 的证据规则），不是设计的臆想。

| TS 类型 | 字段（逐字） | 后端出处（真实读数） |
|---|---|---|
| `StateSnapshot` | `root, generated_at, sessions, pending_questions, runs, orphans, orphan_summary, last_run, ledger, problems` | `webui.py:404` docstring 逐字 |
| `SessionRow` | `sid, path, events_seen, events_listed, bad_lines, first_ts, last_ts, last_kind, last_seq, pending, runs, orphans` | `webui.py:438–451` |
| `PendingQuestion` | `qid, sid, role, ts, timeout_sec, text, options: string[], multi: boolean, index` | `webui.py:293–304`；事件侧样本 `projects/p5-run10/sessions/real10.jsonl`（键 `kind options qid role text timeout_sec ts`） |
| `RunRow` | `sid, role, task, start_index, start_ts, steps, llm_calls, usd, unknown_usd, stop_reason, final_chars, summons, messages, elapsed_sec, last_shape, end_index, end_ts, waiting_on: string[], waiting, events_in_run` | `webui.py:322–330`（基础 18 键）+ `:361–369`（后 3 键） |
| `OrphanRow` | `sid, index, kind, ts, role` | `webui.py:335` |
| `LedgerReading` | `path, events, tables, note, tables_note` | `webui.py:505–520` |
| `ReportReading` | `status: "ok"\|"missing"\|"unknown"`, `text` | `webui.py:527 _read_report`（三态逐字） |
| `Checkpoint` | `role, sid, task, fingerprint, step, stop_reason, waiting_for, spend{calls,tokens_in,tokens_out,usd,unknown_usd_calls}, at` | 真机 `projects/p9b-post-fix-replay/runs/agent-M-t9b.json`；出处 `agent_loop.py:2922` |
| `TaskRow` | `task_id, role, action, called_by, parent_task_id, depth, input_key, status, outcome, refusal_reason, detail, error, started_at, ended_at, tokens, usd, instance, artifacts[], inputs[]` | 真机 `p9b/data/tasks.json`（19 键） |
| `SearchRequestRow` | `request_id, topic, mode, content_description, providers[], done, outcome, priority, submitted_by, submit_note, for_question_id, claimed_by, lease_until, attempts, last_error, result_lit_ids[], timestamp` | 真机 `p9b/data/search_requests.json`（17 键） |
| `ConjectureRow` | `conjecture_id, statement, status, form, testable, origin, created_by, created_at, updated_at, experiment_ids[], counterexample_experiment_id, proof_experiment_id, negation_statement, known_lit_id, notes, promoted_to, withdraw_reason, duplicate` | 真机 `p9b/data/conjectures.json`（非空键含 `counterexample_experiment_id`） |
| `ExperimentRow` | `experiment_id, method, result, evidence_kind, negation_kind, claim, claim_key, certificate, counterexample, search_bound, verifier_output, verifier_subject_key, code_path, code_hash, exit_code, artifact_paths[], observations, params, runtime_sec, notes, created_at, created_by, for_question_id` | 真机 `p9b/data/experiments.json`（2 行） |
| `ArtifactRow` | `at, bytes, exit_code, kind, note, path, producer, sha256, task_id` | 真机 `p9b/ARTIFACTS.jsonl`（6 行） |
| `HandoffRow` | `id, to, sender, summary, body, refs[], sha256, sid, task_id, format, bytes, path, note, created_at` | 真机 `p9b/manuscripts/handoffs.jsonl`（9 行） |
| `SecretaryDecision` | `role, seq, at, kind, duty, decision, judge, reason, basis, before, target, from, fail_open` | 真机 `p9b/out/secretary/M.jsonl` 首行（13 键） |
| `AcceptanceCheck` | `id, kind, min, name, note` | 真机 `p9b/out/paper/ACCEPTANCE-CHECKS.json`（**8 行 C1–C8**）；读者 `closing.py:83/1391/1411` |
| `ReportStyle` | `sections: string[]` | 真机 `p9b/out/review/REPORT-STYLE.json`（四节名字） |
| `AcceptanceView` | `criteria: Record<string,string>`（5 条）· `auxiliary: Record<string,unknown>`（5 条） | `reviewaccept.py:71/73` + `CRITERIA:33` / `AUXILIARY_SIGNALS:51`；`to_dict():86` |
| `MachineView` | `can_do_formal, lean_path, lean_ready, lean_version, provers{available,available_names,checked,looked_in,probe_errors,reason,sources}, mathlib{checked,commit,import_mathlib,lean_path,lean_path_segments,pinned_commit,pinned_match,pinned_tag,reason,root,source,tag}, model{base_url,key_present,model}` | 真机 `toolchain_report()` 的键（本机读数；`toolchain.py:325`） |
| `UsageRow` | `usage_id, at, role, scope, task_id, idem_key, tokens_in, tokens_out, tokens_total, usd, attempts, note` | 真机 `p9b/data/usage_ledger.json`（37 行） |
| `WriteResult` | `ok: boolean, tri: Tri, reason: string, id?: string, extra?: Record<string,unknown>` | 各写端点（C1 第 7–10 行） |

> **`Tri` 的定义（三态，唯一的）**：`"computed" | "unreadable" | "not_applicable"`（`reviewaccept` 的词表）与 `"ok" | "missing" | "unknown"`（`_read_report` 的词表）**都映射到组件 `TriState` 的三种视觉态**，但**字符串不许互相顶替**：`ReportReading.status` 用后一组，其余用前一组。

### §1.4 C4 路由契约（`routes.py` 的 SPA 回退 ↔ `main.tsx`）
| 客户端路由 | 页面文件 | 用到的端点 | 用到的 SSE kind |
|---|---|---|---|
| `/` | `pages/Home.tsx` | 1 · 7 | `state` · `question` · `answered` |
| `/run/:sid` | `pages/Run.tsx` | 1 · 2 · 8 | `state` · `checkpoint` · `stop` |
| `/evidence` | `pages/Evidence.tsx` | 3 | `state` |
| `/artifacts` | `pages/Artifacts.tsx` | 4 | `state` |
| `/acceptance` | `pages/Acceptance.tsx` | 5 | `state` |
| `/machine` | `pages/Machine.tsx` | 6 · 10 | `state` |

> **对齐判据（§3-D）**：`main.tsx` 的路由字面量集合 == 本表的路由列；且每条路由用到的端点必须 ∈ C1、kind 必须 ∈ C2。

### §1.5 C5 组件 props 契约
| 组件 | props（逐字） | 谁用 |
|---|---|---|
| `TriState` | `{ tri: Tri; reason?: string; label?: string }` | 所有页面 |
| `Money` | `{ usd: number \| null; unknownCalls: number }` | Run · Machine |
| `Table` | `{ rows: T[]; columns: {key: keyof T; title: string}[]; empty: string }` | Evidence · Artifacts |
| `Card` | `{ title: string; subtitle?: string; children }` | 所有页面 |
| `Badge` | `{ kind: string; text: string }` | 所有页面 |
| `ConfirmButton` | `{ action: string; impact: string; onConfirm: () => void; requireForce?: boolean }` | Run（叫停）· Machine（写设置） |

---

## §2 逐前端文件伪代码

### §2.1 `ui/src/types.ts`（**唯一类型来源；裁定 M2：由 `agentflow/web/emit_types.py` 生成，不许手改**）
```ts
// ⚠️ 本文件是生成物（`python -m agentflow.web.emit_types`）；下面就是生成器的输出形状
export type Tri = "computed" | "unreadable" | "not_applicable";
export type ReportTri = "ok" | "missing" | "unknown";
// 其余类型逐字对应 §1.3 的每一行；**不许在这里改名、不许 optional 掉后端一定会给的键**
export interface Checkpoint { spend: { calls: number; tokens_in: number; tokens_out: number;
                                      usd: number | null; unknown_usd_calls: number } /* … */ }
export interface RunRow { /* §1.3 的 21 键 */ }
// …（§1.3 全部）
```
对齐点：**本文件是 C3 的落点**；`§3-C` 判据把它的键与后端读数的键逐字比对。

### §2.2 `ui/src/api.ts`
```ts
const ENDPOINTS = { state: "/api/state", run: (sid) => `/api/run/${sid}`, evidence: "/api/evidence",
                    artifacts: "/api/artifacts", acceptance: "/api/acceptance", machine: "/api/machine",
                    answer: "/answer", stop: "/api/stop", submit: "/api/submit", settings: "/api/settings",
                    stream: "/api/stream" } as const;         // ← 与 C1 逐字对齐（§3-A 判据）
function csrf(): string;                                     // 从 <meta name="csrf-token"> 读
async function getJSON<T>(url: string): Promise<T>;           // 4xx/5xx ⇒ throw ApiError
async function postJSON<T>(url: string, body: unknown): Promise<T>;  // 带 X-CSRF-Token
export const api = { getState, getRun, getEvidence, getArtifacts, getAcceptance, getMachine,
                     postAnswer, postStop, postSubmit, postSettings };
```
对齐点：**C1**（路径字面量集）；错误三态经 `ApiError{code, tri, reason}` 上抛，页面据此渲染 `TriState`。

### §2.3 `ui/src/sse.ts`
```ts
export const KINDS = ["state","question","answered","checkpoint","stop","heartbeat"] as const;  // ← C2
export function subscribe(sid: string | null, h: Handlers, opts?: { since?: number }): () => void {
  // new EventSource(`${ENDPOINTS.stream}?sid=…&since=…`)
  // 每个 kind 注册一个 listener（KINDS 里逐个注册，不许漏）
  // onerror：指数退避 3 次 ⇒ 降级 setInterval(() => h.onState(await getState()), 2000)
}
```
对齐点：**C2**；降级路径必须存在（判据：源码里同时出现 `EventSource`、`since`、`setInterval`）。

### §2.4 `ui/src/main.tsx`
```ts
const ROUTES = ["/", "/run/:sid", "/evidence", "/artifacts", "/acceptance", "/machine"] as const;  // ← C4
// 挂载：<App> 里按 pathname 选页；订阅一次 SSE，把 state 分发到各页（避免每页各订阅一条流）
```

### §2.5 `ui/src/pages/Home.tsx`
```ts
// 输入：api.getState() → StateSnapshot；SSE: state/question/answered
function Home() {
  const [snap, setSnap] = useState<StateSnapshot>();
  // 待答：snap.pending_questions（**全局，不按会话过滤**）
  //   每条：qid/sid/role/text/options/multi/timeout_sec/ts + 是否正被某趟等待（run.waiting_on 含 qid）
  // 回答：postAnswer({qid, selected}) ⇒ 成功移除该条；409 ⇒ 如实显示"已被答过/未知 qid"
  // 会话概览：snap.sessions（含 bad_lines>0 时显红）
  // 读数横幅：snap.problems.length ? 逐条显示 : 隐藏          ← 三态：读不到 ⇒ 显 problems，不是空
  // 空态：pending_questions === [] 且 problems === [] ⇒ "没有待回答的问题"（不是"没查成"）
}
```

### §2.6 `ui/src/pages/Run.tsx`
```ts
// 输入：api.getRun(sid) → RunView{runs[], report, checkpoint}；SSE: state/checkpoint/stop
function Run() {
  // ① 时间线：RunRow.events_in_run / steps / llm_calls / last_shape / stop_reason
  // ② 花销：**首选 checkpoint.spend**（usd / calls / tokens / unknown_usd_calls）
  //          第二读数：ΣRunRow.usd + RunRow.unknown_usd（事件求和）→ 两个并排，不一致就显红
  // ③ 停机：api.getState().stop → {stop_path, requested_by, at, live_pids, running_loops}
  //          叫停：postStop({reason, confirm:1[, force:1]}) ⇒ ConfirmButton（force 再确认一次）
  // ④ 交付说明：report.status ∈ {ok, missing, unknown} → 三态渲染（unknown 带 reason）
  // ⑤ 台账：ledger.events / ledger.tables（**必须显示 tables_note 那句"含顶趟行"**）
  // ⑥ 孤儿：orphans/orphan_summary ⇒ 单独一栏"轮次之外的零散事件"，**不许并进 runs**
  // ⑦ 检索腿：search_requests 行（providers[] 点名 + done/outcome/claimed_by）
}
```

### §2.7 `ui/src/pages/Evidence.tsx`
```ts
// 输入：api.getEvidence() → { statements[], conjectures[], experiments[], review_findings[],
//                            relations[], verifications[], secretary[] }；SSE: state
function Evidence() {
  // ① 命题：statements（stmt id / status / 被哪些正文断言引用）
  // ② 猜想+反例：conjectures；**status=refuted ⇒ 显 experiment_ids[] 与 counterexample_experiment_id**
  // ③ 实验：experiments（method / result / negation_kind / evidence_kind / exit_code / code_path）
  // ④ 审校：review_findings（round / verdict / 失败门号 → gates.GATES 的名字）
  // ⑤ 引文回验：relations.quote_verified 三数（真/假/未查）
  // ⑥ 证明级：verifications[]（**盘上暂无样本 ⇒ 空态写"这台机器还没有验证台账"，不是 0**）
  // ⑦ 秘书：secretary[]（duty/decision/judge/reason/fail_open）
}
```

### §2.8 `ui/src/pages/Artifacts.tsx`
```ts
// 输入：api.getArtifacts() → { ledger[], handoffs[], checks[], style, secretary[], products[], tasks[] }
function Artifacts() {
  // ① 台账：ledger[]（producer/sha256/exit_code/kind）＋"行里 sha 与盘上是否一致"（verify_entries）
  // ② 交接：handoffs[]（id/to/sender/summary/refs/sha256/sid/task_id；body 截断显示）
  // ③ 验收检查行：checks[]（**8 行 C1–C8**；id/name/kind/min/note + 现算读数）
  // ④ 体例：style.sections[]（四节名字）
  // ⑤ 六件产物：products[]（**本机无样本 ⇒ 三态写 missing 并附一句"这一路（run/project run）本机还没跑过"**）
  // ⑥ 任务产物：tasks[]（out/tasks/t-*.json 与台账行对应）
}
```

### §2.9 `ui/src/pages/Machine.tsx`
```ts
// 输入：api.getMachine() → MachineView；SSE: state
function Machine() {
  // ① provers{available_names, sources, checked, looked_in, probe_errors, reason}
  //    ⇒ **必须显示"从哪一档找到的"（sources）**；checked=false ⇒ TriState("unreadable")
  // ② mathlib{checked, root, import_mathlib, pinned_commit, pinned_match, reason}
  // ③ model{key_present, base_url, model} ⇒ **只显"配没配"+ base_url/model；永无 key 值**
  // ④ 设置：settings_path() 的落点 + 在不在盘上；三段键值（model.api_key 恒 "***"）
  // ⑤ 写设置：postSettings({...}) 需 ConfirmButton；响应里 key 只可能是 "***"
}
```

### §2.10 `ui/src/pages/Acceptance.tsx`
```ts
// 输入：api.getAcceptance({project_dir, report_path, cap_usd?}) → AcceptanceView；SSE: state
function Acceptance() {
  // ① criteria: Record<string,string>（5 条；键名来自 reviewaccept.CRITERIA）
  // ② auxiliary: Record<string,unknown>（5 条；键名来自 AUXILIARY_SIGNALS）
  // ③ 逐条 TriState；**不给 cap_usd ⇒ "在成本上限内"那一格 = "没查成"**
  // ④ 与工具面同源校验：显示 conductor.closing 的 review_acceptance 子树里同一个键的值是否相同
}
```

### §2.11 `ui/src/components/*.tsx`（六个）
```ts
// TriState: { tri, reason?, label? } —— 三种视觉态**一一对应**两种词表（§1.3 末尾那条纪律）
// Money: { usd, unknownCalls } —— usd===null ⇒ 显 "unknown"（不是 $0.00）；unknownCalls>0 ⇒ 附"（N 次算不出价钱）"
// Table: 泛型 T + columns[keyof T] ⇒ 列名不可能写成不存在的键（**类型层对齐**）
// Card / Badge: 纯呈现
// ConfirmButton: { action, impact, onConfirm, requireForce? } ⇒ 不可逆动作（叫停/写设置/覆盖 key）必须过它
```

### §2.12 `ui/src/theme/app.css` 与 `generated/theme.css`
```css
/* generated/theme.css：**不许手写** —— 由 python -m agentflow.web.emit_theme 从 web/assets.py 生成 */
/* app.css：只允许 color/spacing/radius/font 用 var(--…)；**不许出现字面色值**（判据扩自 test_app_css_uses_only_tokens） */
```

### §2.13 `ui/index.html` / `vite.config.ts` / `package.json` / `tsconfig.json`
```html
<!-- index.html：<div id="app"> + <meta name="csrf-token" content="{{CSRF}}">（服务端注入；**文件里不许有真 token**） -->
```
```ts
// vite.config.ts：base="/static/"；outDir="../src/agentflow/web/static"；哈希文件名；sourcemap=false
// package.json：scripts = { dev, build, typecheck: "tsc --noEmit" } —— **typecheck 是对齐的第二道门**
// tsconfig.json：strict、noUncheckedIndexedAccess（把"可能缺的键"逼成编译错误）
```

---

## §3 对齐的机械保证（四条判据 + 一道编译门；每条"改前能红"）

| 判据 | 查什么 | 怎么造负控（改前红） | 落在哪个文件（W0 建） |
|---|---|---|---|
| **A 端点对齐** | `api.ts` 的路径字面量集合 == `routes.py` 的 `ROUTES` 集合 | 删掉 `routes.py` 里一个端点 ⇒ 判据必须报"前端多出一个没实现的端点" | `tests/test_webui_contracts.py`（W0 新建） |
| **B 事件对齐** | `sse.ts` 的 kind 集合 == `sse.py` 的 `EVENT_KINDS` | 在 `EVENT_KINDS` 里加一个 kind 而 `sse.ts` 没注册 ⇒ 必红 | 同上（W0 新建） |
| **C 类型对齐** | `types.ts` 里每个接口的键集合 == **后端在夹具工作区上真读出来的键集合**（用 `readers.py` 现算） | 后端加一个键（如 `tasks` 多一列）而 `types.ts` 没加 ⇒ 必红；反向（TS 多了后端没有的键）也红 | 同上（正控用 `tests/` 夹具造工作区） |
| **D 路由对齐** | `main.tsx` 的路由集合 == C4 表；每条用到的端点 ∈ C1、kind ∈ C2 | 页面里写一个 C1 没有的端点 ⇒ 必红 | 同上 |
| **E 类型检查** | `pnpm typecheck`（`tsc --noEmit`） | 组件 props 不匹配 ⇒ 编译失败 | W0 起进构建链；**node 缺失 ⇒ 记 `unknown`（三态，不许记 pass）** |

> **这五条的关系**：A/B/C/D 是**名字层**（正则级，纯 Python 可跑，进常规全量）；E 是**类型层**（需要 node，opt-in）。少了 A–D，改名就会静默漂移；少了 E，"名字对但类型不对"（如把 `string[]` 写成 `string`）会漏。

---

## §4 改动影响矩阵（改后端 ⇒ 前端必须跟着改的文件）

| 后端改动 | 必须同步的前端文件 | 触发哪条判据 |
|---|---|---|
| `webui.snapshot()` 加/改键 | `types.ts`（`StateSnapshot`/`SessionRow`/`PendingQuestion`/`RunRow`/`LedgerReading`） | C |
| 新增一个只读面（如 `readers.handoffs`） | `api.ts` + `types.ts` + 对应页面 + C4 表 | A · C · D |
| 新增一个写端点 | `routes.py` + `api.ts` + 页面 + `writes.py` 的授权表 | A · D |
| SSE 加一种事件 | `sse.py`（`EVENT_KINDS`）+ `sse.ts`（注册 + handler）+ 用到它的页面 | B |
| 检查点字段变（`agent_loop`） | `types.ts`（`Checkpoint`）+ Run 页第②行 | C |
| `reviewaccept.CRITERIA/AUXILIARY_SIGNALS` 改名字 | Acceptance 页 + `types.ts` | C |
| `toolchain_report()` 键变 | `types.ts`（`MachineView`）+ Machine 页 | C |
| 组件 props 变 | 所有用到它的页面 | E（tsc） |

---

## §5 一句话
**伪代码里出现的每一个名字都来自 §1 契约表；契约表里每一行都有后端出处；§3 的五条判据把"契约表 ↔ 代码"钉死**。任何"页面里自造一个名字"或"后端改了名字而前端没跟上"都会以 A–E 里的某一条红出来 —— 这就是"互相对齐"的可执行含义。
