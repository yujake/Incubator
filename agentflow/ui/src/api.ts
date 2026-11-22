/*
 * 网关层（前端唯一的网络出口）。
 *
 * 三条纪律：
 *
 * 1. 路径只在 ENDPOINTS 里写一次 —— `tests/test_webui_contracts.py` 的 A 条把
 *    这里的路径字面量集合与后端 `webui/routes.py` 的 ROUTES 逐字比对：后端有的
 *    前端必须逐条声明，前端多写一个后端没有的也会红。**谁有多少条不在这里抄** ——
 *    抄一份就会与那边漂移。
 * 2. 失败不许折成空读数：HTTP 非 2xx 与网络故障都抛 ApiError，三态走 `tri`
 *    （`unreadable` = 没查成），由页面渲染成 TriState。绝不返回空对象装作读到了。
 * 3. 写请求带 X-CSRF-Token（从 `<meta name="csrf-token">` 读；服务端每进程换一个）。
 */
import type {
  ActionsView,
  CacheView,
  RoleErrorsView,
  ErrorCategoryGlossary,
  AcceptanceView,
  ArtifactsView,
  BudgetView,
  EvidenceView,
  LibraryView,
  LiveView,
  MachineView,
  ObligationsView,
  PackageView,
  RosterView,
  RunEventsView,
  RunDigestView,
  RunIndexDrift,
  RunView,
  SourceWindow,
  StateSnapshot,
  StatusReportsView,
  ChatView,
  Tri,
  UsageView,
  WriteResult,
} from "./types";

/**
 * 后端端点表（与 `webui/routes.py` 的 `ROUTES` 逐字对齐）。
 *
 * 带 `{}` 的那条是路由模式：`runPath()` 拿它拼实参（判据会把拼出来的路径归一成
 * `{sid}` 再比，见 A 条的 `_literals`）。
 */
export const ENDPOINTS = {
  state: "/api/state",
  runIndex: "/api/run-index",
  // 裁定「甲」：趟次档案 —— 从事件流现算，不读也不落
  // `index/run-index.json`。与 runIndex 是两格并排的独立读数。
  runDigest: "/api/run-digest",
  run: "/api/run/{sid}",
  runEvents: "/api/run/{sid}/events",
  evidence: "/api/evidence",
  artifacts: "/api/artifacts",
  // 文献库那一面。
  // 只读一条：只算「正式入库」的文献，每条带「被哪些命题／哪一份证明用过」，
  // 且下载那一格要与盘上的文件核过（在 / 不在 / 读不到）。没有配对的 POST。
  literature: "/api/literature",
  acceptance: "/api/acceptance",
  machine: "/api/machine",
  answer: "/answer",
  stop: "/api/stop",
  submit: "/api/submit",
  settings: "/api/settings",
  budget: "/api/budget",
  runTask: "/api/run",
  interject: "/api/task",
  // 板项收口（写）：`POST /api/ack`。状态机在 `conductor.close_item` 那一处，
  // 这条端点只是它的门面 —— 前端不判"能不能收口"，只把结论画出来。
  ack: "/api/ack",
  // 板项作废（写）：`POST /api/void`（BOARDACK，2026-11-21）。`/api/ack` 对
  // `item_state=block` 的行只能回 409（迁移图里 `block → done` 是倒退，端点不许绕过），
  // 而"唤醒 ⇒ 再 ack"仍会被 A5 的空口 ack 闸拦 ⇒ 停在 block 的项走这一条。
  // 唯一实现是 `conductor.void_items_by_user`（作废本来就不走状态机）。
  void: "/api/void",
  // 撤销叫停（写）：`POST /api/stop/clear`。删开关的唯一写入口是
  // `stopctl.clear_stop`（它同时通知别的进程"叫停被撤销了"）。
  stopClear: "/api/stop/clear",
  live: "/api/live",
  usage: "/api/usage",
  statusReports: "/api/status-reports",
  chat: "/api/chat",
  // 整棵名册树（父/子/绝对编号/角色/深度/收件箱三格）。
  // 只读一条 —— 这个端点在路由表里没有配对的 POST，前端也不该有写它的函数。
  roster: "/api/roster",
  // 板上三族义务（b-register / v-resubmit / b-awake）的收件人读数。
  // 只读一条 —— 没有配对的 POST：销号只发生在 conductor 的收口那一路。
  obligations: "/api/obligations",
  // 两档提示词缓存的状态读数（只读）与预热（写，会花钱）。两条的形状与
  // `webui/cacheface.py` 的两个处理器逐字对应。
  cache: "/api/cache",
  cacheWarm: "/api/cache/warm",
  // 错误动作的两条只读端点：第一条是 `readouts.errors_readout(root)` 逐字（五个键），
  // 第二条是类目 → 那一句含义（真身 `errorstats.ERROR_CATEGORIES`）。
  errors: "/api/errors",
  errorCategories: "/api/errors/categories",
  // 论文包三块一次读（A 证明 / B 结构 / C 收工）+ 原文窗口。
  // 两条都只读；`package` 的入参与 `acceptance` 同源（project_dir / report_path /
  // cap_usd / sid），`source` 只吃 path / line / match。
  package: "/api/package",
  source: "/api/source",
  stream: "/api/stream",
  // 网页操作台账（`<工作区>/web-actions.jsonl`）的**读**侧（AUDIT F11）：
  // 写侧从 W3 起就在写（`writes.audit.record_action`），此前全仓没有读侧。
  // 只读一条 —— 它没有配对的 POST。
  actions: "/api/actions",
} as const;

export type EndpointName = keyof typeof ENDPOINTS;

/** 一趟详情的实参拼装（`/api/run/{sid}` 的那一个占位符）。 */
export function runPath(sid: string): string {
  return ENDPOINTS.run.replace("{sid}", encodeURIComponent(sid));
}

/**
 * 趟次档案（`/api/run-digest`）的实参拼装。
 *
 * `sid` 是查询参数而不是路径段：这一个端点是**两种作用域**共用的一条读数
 * （不给 `sid` = 整个工作区；给了 = 只算那一段会话）。页面的档案格传当前 `sid`。
 */
export function runDigestPath(sid: string): string {
  const q = new URLSearchParams();
  if (sid !== "") {
    q.set("sid", sid);
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.runDigest : `${ENDPOINTS.runDigest}?${tail}`;
}

/**
 * 一趟的逐条事件（`/api/run/{sid}/events`）的实参拼装。
 *
 * 两个查询参数逐字对应后端 `handle_run_events` 读的那两个：`since_index` 是游标
 * （左闭，填上一页的 `to_index` 就是续取），`limit` 是一页多少条（后端钳在
 * `[1, 500]`，超了按上限截断并在 `reason` 里说明）。
 */
export function runEventsPath(
  sid: string,
  opts: { sinceIndex?: number; limit?: number } = {},
): string {
  const q = new URLSearchParams();
  if (typeof opts.sinceIndex === "number") {
    q.set("since_index", String(opts.sinceIndex));
  }
  if (typeof opts.limit === "number") {
    q.set("limit", String(opts.limit));
  }
  const tail = q.toString();
  const base = ENDPOINTS.runEvents.replace("{sid}", encodeURIComponent(sid));
  return tail === "" ? base : `${base}?${tail}`;
}

/**
 * 对话那一段来回的实参拼装（`/api/chat`）。
 *
 * 两个查询参数逐字对应后端 `handle_chat` 读的那两个：`sid` 是会话号（不给就由后端取
 * **最近**的那一段，并在 `reason` 里写明这件事），`lines` 是最多几条线（后端默认 300）。
 */
export function chatPath(
  sid: string,
  opts: { lines?: number } = {},
): string {
  const q = new URLSearchParams();
  if (sid !== "") {
    q.set("sid", sid);
  }
  if (typeof opts.lines === "number") {
    q.set("lines", String(opts.lines));
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.chat : `${ENDPOINTS.chat}?${tail}`;
}

/** 收工门那条端点的查询串（三个可选输入，逐字对应后端的 `?project_dir=` 等）。 */export function acceptancePath(opts: {
  projectDir?: string;
  reportPath?: string;
  capUsd?: number | null;
}): string {
  const q = new URLSearchParams();
  if (opts.projectDir) {
    q.set("project_dir", opts.projectDir);
  }
  if (opts.reportPath) {
    q.set("report_path", opts.reportPath);
  }
  if (typeof opts.capUsd === "number") {
    q.set("cap_usd", String(opts.capUsd));
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.acceptance : `${ENDPOINTS.acceptance}?${tail}`;
}

/** `/api/package` 的查询串（与 `acceptancePath` 同一批入参，多一个 `sid`）。 */
export function packagePath(opts: {
  projectDir?: string;
  reportPath?: string;
  capUsd?: number | null;
  sid?: string;
}): string {
  const q = new URLSearchParams();
  if (opts.projectDir) {
    q.set("project_dir", opts.projectDir);
  }
  if (opts.reportPath) {
    q.set("report_path", opts.reportPath);
  }
  if (typeof opts.capUsd === "number") {
    q.set("cap_usd", String(opts.capUsd));
  }
  if (opts.sid) {
    q.set("sid", opts.sid);
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.package : `${ENDPOINTS.package}?${tail}`;
}

/** `/api/source` 的查询串（`line` 与 `match` 二选一；两个都给时 `line` 优先）。 */
export function sourcePath(opts: {
  path: string;
  line?: number;
  match?: string;
}): string {
  const q = new URLSearchParams();
  q.set("path", opts.path);
  if (typeof opts.line === "number" && opts.line > 0) {
    q.set("line", String(opts.line));
  }
  if (opts.match) {
    q.set("match", opts.match);
  }
  return `${ENDPOINTS.source}?${q.toString()}`;
}

/**
 * 两个"全量行"的面共用的分页参数（AUDIT F12：真机上 `/api/evidence` 2.1 MB /
 * `/api/artifacts` 1.3 MB，一进页面就卡）。
 *
 * 三档，语义都在后端（`readers._page_window`）：
 *
 * - 什么都不给 ⇒ **全量**（既有行为；判据与命令行读的就是这一档）；
 * - `summary: true` ⇒ 首屏摘要（每栏 `readers.SUMMARY_ROWS` 行）；
 * - `limit` / `offset` ⇒ 显式窗口（`limit: 0` 也是全量）。
 *
 * 摘要档不删字段：每一栏的**真实**总行数在响应的 `rows_total[栏]` 里，`rows_mode`
 * 说清这一份是哪一档 —— 页面因此不会把"首屏只给了 40 行"读成"一共就 40 行"。
 */
export interface RowPagingOptions {
  summary?: boolean;
  limit?: number;
  offset?: number;
}

/** 把 `RowPagingOptions` 拼成查询串（空 = 空串，不带一个多余的 `?`）。 */
function rowPagingQuery(opts: RowPagingOptions): string {
  const q = new URLSearchParams();
  if (opts.summary === true) {
    q.set("summary", "1");
  }
  if (typeof opts.limit === "number") {
    q.set("limit", String(opts.limit));
  }
  if (typeof opts.offset === "number" && opts.offset > 0) {
    q.set("offset", String(opts.offset));
  }
  const tail = q.toString();
  return tail === "" ? "" : `?${tail}`;
}

/** 证据链那一面的查询串（`?summary=1` / `?limit=` / `?offset=`；不给就是全量）。 */
export function evidencePath(opts: RowPagingOptions = {}): string {
  return `${ENDPOINTS.evidence}${rowPagingQuery(opts)}`;
}

/** 产物面那一面的查询串（多一个 `run_dir`；其余与 `evidencePath` 同一套）。 */
export function artifactsPath(opts: RowPagingOptions & { runDir?: string } = {}): string {
  const q = new URLSearchParams();
  if (opts.runDir) {
    q.set("run_dir", opts.runDir);
  }
  if (opts.summary === true) {
    q.set("summary", "1");
  }
  if (typeof opts.limit === "number") {
    q.set("limit", String(opts.limit));
  }
  if (typeof opts.offset === "number" && opts.offset > 0) {
    q.set("offset", String(opts.offset));
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.artifacts : `${ENDPOINTS.artifacts}?${tail}`;
}

/**
 * 网页操作台账那一面的查询串（`GET /api/actions`，AUDIT F11）。
 *
 * 行序由后端定（`order="newest_first"`，最新的在最上面）；`limit` / `offset` 是分页
 * 窗口，两个都非法时后端回 400 并把参数原样回显（与 `/api/run/{sid}/events` 同族）。
 */
export function actionsPath(opts: { limit?: number; offset?: number } = {}): string {
  const q = new URLSearchParams();
  if (typeof opts.limit === "number") {
    q.set("limit", String(opts.limit));
  }
  if (typeof opts.offset === "number" && opts.offset > 0) {
    q.set("offset", String(opts.offset));
  }
  const tail = q.toString();
  return tail === "" ? ENDPOINTS.actions : `${ENDPOINTS.actions}?${tail}`;
}

/** 请求失败时抛的那个东西：状态码 + 三态 + 人话理由（页面据此渲染 TriState）。 */export class ApiError extends Error {
  readonly code: number;
  readonly tri: Tri;
  readonly reason: string;
  /** 失败的种类（鲁棒 c：超时 / 网络 / HTTP / 正文不是 JSON 是四件不同的事）。 */
  readonly kind: ApiErrorKind;
  /** 后端给的失败档名（`kind` 字段；读请求不一定有，缺省空串）。 */
  readonly backendKind: string;
  /** 后端给的"怎么办"（`how_to_fix` 字段；缺省空串）。 */
  readonly howToFix: string;

  constructor(code: number, tri: Tri, reason: string, kind: ApiErrorKind = "http",
              backendKind: string = "", howToFix: string = "") {
    super(`${code} ${reason}`);
    this.name = "ApiError";
    this.code = code;
    this.tri = tri;
    this.reason = reason;
    this.kind = kind;
    this.backendKind = backendKind;
    this.howToFix = howToFix;
  }

  /** 这一次失败值不值得重试（幂等读才有这一档；写请求一律不自动重试）。 */
  get retryable(): boolean {
    if (this.kind === "timeout" || this.kind === "network") {
      return true;
    }
    return this.kind === "http" && this.code >= 500;
  }
}

/** 失败种类（`ApiError.kind` 的闭集）。 */
export type ApiErrorKind = "timeout" | "network" | "http" | "bad-json";

/** 一次读请求的超时（毫秒）。超时不是"没有数据"，页面据此写「没查成」。 */
export const REQUEST_TIMEOUT_MS = 15000;

/** 读请求的总重试次数（首次之外再试几次）；退避 400ms、800ms。 */
export const RETRY_LIMIT = 2;

/** 退避基数（毫秒）：第 n 次重试等 `RETRY_BASE_MS * 2^n`。 */
export const RETRY_BASE_MS = 400;

/** 等一会儿（重试退避；只在浏览器里跑）。 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * 带超时的 fetch（一次）。超时用 `AbortController` 真把请求掐掉，
 * 不靠"等它自己回来"—— 后者在 `/api/state` 慢或后端卡住时就是无限转圈。
 */
async function fetchOnce(
  url: string,
  init: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (exc) {
    if (controller.signal.aborted) {
      throw new ApiError(
        0,
        "unreadable",
        `请求超时（${timeoutMs} 毫秒没有响应）—— 这一份读数没查成，不是"没有数据"`,
        "timeout",
      );
    }
    throw new ApiError(0, "unreadable", `请求没发出去：${String(exc)}`, "network");
  } finally {
    window.clearTimeout(timer);
  }
}

/** 把任意异常读成一句人话（各页面统一用它，不各写一份文案）。 */
export function whyOf(exc: unknown): string {
  return exc instanceof ApiError ? exc.reason : String(exc);
}

function csrf(): string {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta instanceof HTMLMetaElement) {
    return meta.content === "__CSRF__" ? "" : meta.content;
  }
  return "";
}

async function readJSON<T>(resp: Response): Promise<T> {
  const text = await resp.text();
  if (!resp.ok) {
    // 鲁棒 e：后端把失败写成 JSON（`kind` / `how_to_fix` / `reason`）时原样读出来，
    // 页面据此渲染错误块；不是 JSON（或没有那几栏）就退回正文前 300 字。
    let reason = text.trim().slice(0, 300) || "服务端没有给正文";
    let backendKind = "";
    let howToFix = "";
    try {
      const body = JSON.parse(text) as Record<string, unknown>;
      if (body !== null && typeof body === "object") {
        if (typeof body.reason === "string" && body.reason.trim() !== "") {
          reason = body.reason;
        }
        if (typeof body.kind === "string") {
          backendKind = body.kind;
        }
        if (typeof body.how_to_fix === "string") {
          howToFix = body.how_to_fix;
        }
      }
    } catch {
      // 正文不是 JSON：保留正文前 300 字（那种情况后端没给 kind/how_to_fix）。
    }
    throw new ApiError(resp.status, "unreadable", reason, "http", backendKind, howToFix);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(
      resp.status,
      "unreadable",
      "正文不是 JSON（没查成，不是空读数）",
      "bad-json",
    );
  }
}

/**
 * 读一个 JSON 端点。失败抛 ApiError（不返回空对象）。
 *
 * 鲁棒 c：超时与断流不许变成无限转圈 —— 超时 15 秒、最多再重试 2 次
 * （网络 / 超时 / 5xx 才重试；4xx 与"正文不是 JSON"当场抛，重试也读不出来）。
 */
export async function getJSON<T>(url: string): Promise<T> {
  let last: unknown = null;
  for (let attempt = 0; attempt <= RETRY_LIMIT; attempt += 1) {
    try {
      const resp = await fetchOnce(url, { headers: { Accept: "application/json" } });
      return await readJSON<T>(resp);
    } catch (exc) {
      last = exc;
      const err = exc instanceof ApiError ? exc : null;
      if (err === null || !err.retryable || attempt === RETRY_LIMIT) {
        throw exc;
      }
      await sleep(RETRY_BASE_MS * Math.pow(2, attempt));
    }
  }
  throw last instanceof Error ? last : new ApiError(0, "unreadable", String(last), "network");
}

async function postForm(
  url: string,
  body: Record<string, string | string[]>,
  redirect: RequestRedirect,
): Promise<Response> {
  const form = new URLSearchParams();
  for (const [key, value] of Object.entries(body)) {
    if (Array.isArray(value)) {
      // 重复键（多选就是 `selected=A&selected=B`）：表单的既有口径，不许折成一个串。
      for (const one of value) {
        form.append(key, one);
      }
      continue;
    }
    form.append(key, value);
  }
  // 写请求只加超时，不自动重试：同一次写重放一次就是两次副作用（回答两次 / 追加两次预算）。
  return await fetchOnce(url, {
    method: "POST",
    redirect,
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      "X-CSRF-Token": csrf(),
      Accept: "application/json",
    },
    body: form.toString(),
  });
}

/** 写一个 JSON 端点（表单编码 + CSRF 头）。失败抛 ApiError。 */
export async function postJSON<T>(
  url: string,
  body: Record<string, string | string[]>,
): Promise<T> {
  const resp = await postForm(url, body, "follow");
  return await readJSON<T>(resp);
}

/** 一次写动作的结局（三态）。`/answer` 之外那几条写端点回的是 `WriteResult`（本结构是它的子集）。 */
export interface WriteOutcome {
  ok: boolean;
  tri: Tri;
  reason: string;
}

/**
 * 叫停（`POST /api/stop`）：落一个跨进程停机开关；`force` 再连子孙进程一起杀。
 *
 * `confirm: "1"` 是后端的硬要求（缺它一律 400，盘上零改动）。**前端不许替用户默认填上**
 * 真正的不可逆动作（`force`）——那是 `ConfirmButton` 的 `requireForce` 那一档。
 */
export async function postStop(opts: {
  reason?: string;
  force?: boolean;
} = {}): Promise<WriteResult> {
  const body: Record<string, string> = {
    reason: opts.reason ?? "user",
    confirm: "1",
  };
  if (opts.force === true) {
    body.force = "1";
  }
  return await postJSON<WriteResult>(ENDPOINTS.stop, body);
}

/**
 * 写机器级设置（`POST /api/settings`，本机页的「设置窗口」）。
 *
 * 表单键是 `段.键` 形状（`toolchain.lean_bin` / `model.api_key` / `workspace.projects_dir`），
 * 这是后端 `writes.handle_settings` 逐字读的那一套。`confirm: "1"` 由后端当硬要求。
 *
 * key 只写不读（裁定 E1）：传进去的 `model.api_key` 会落盘，而回执里恒为 `***`。
 * 空串表示"这一格不动"——后端 `settings.write_settings` 的口径是只写给了值的键。
 */
export async function postSettings(
  values: Record<string, string>,
): Promise<WriteResult> {
  const body: Record<string, string> = { confirm: "1" };
  for (const [key, value] of Object.entries(values)) {
    if (value !== "") {
      body[key] = value;
    }
  }
  return await postJSON<WriteResult>(ENDPOINTS.settings, body);
}

/**
 * 回答一个问题（`POST /answer` —— 写面七条里唯一回 PRG、不回 `WriteResult` 的那一条）。
 *
 * 为什么不用 `postJSON`：`/answer` 回的是 PRG（303 回首页），不是 `WriteResult`。
 * 跟着重定向走会拿到一支 HTML 而 `fetch` 把它当 200，于是"写成了"会被读成
 * "正文不是 JSON" —— 那正是三态纪律要挡的那种错读。
 *
 * 所以这里 `redirect: "manual"`，按响应分档：
 *
 * - `opaqueredirect` ⇒ 服务端回了 303：这次回答真的落盘了（`handle_answer` 只在
 *   `writes.answer` 成功时回 303）。`tri` 记 `not_applicable`：这一条端点没有
 *   `WriteResult` 那种"算出来的回执"，如实说明这一档，而不是假装拿到了 `ok`；
 * - 409 ⇒ 这条 qid 不待答（已答过 / 未知），按既有判据盘上零写入；
 * - 其余非 2xx ⇒ 按状态码如实报错。
 */
export async function postAnswer(body: Record<string, string | string[]>): Promise<WriteOutcome> {
  const resp = await postForm(ENDPOINTS.answer, body, "manual");
  if (resp.type === "opaqueredirect") {
    return {
      ok: true,
      tri: "not_applicable",
      reason: "服务端回了 PRG（303 回首页）⇒ 这次回答落盘了（这一条端点回的是重定向，不是 WriteResult）",
    };
  }
  if (resp.status === 409) {
    return {
      ok: false,
      tri: "unreadable",
      reason: "409：这条 qid 已经不待答（已答过或不存在）；按既有的 409 判据，盘上零写入",
    };
  }
  if (!resp.ok) {
    return { ok: false, tri: "unreadable", reason: `${resp.status}：写回答没有落地` };
  }
  return { ok: true, tri: "not_applicable", reason: `${resp.status}：服务端接受了这次回答` };
}

/**
 * 页面用的那几个调用（每个读端点一个，返回的都是后端那一面的字典逐字）。
 *
 * 九页各自只调自己那一面：Home（以及每页的壳）读 `getState()`，Run 读 `getRun()`
 * 与 `getRunIndex()`，Evidence / Artifacts / Acceptance / Machine 各读自己那一面。
 */
export const api = {
  getState: (): Promise<StateSnapshot> => getJSON<StateSnapshot>(ENDPOINTS.state),
  getRunIndex: (): Promise<RunIndexDrift> => getJSON<RunIndexDrift>(ENDPOINTS.runIndex),
  /**
   * 趟次档案（业主 2026-11-02 裁定「甲」）：从事件流**现算**的一份读数。
   *
   * 它与 `getRunIndex()` 是两格并排的独立来源：索引只在收工成功时建，而这一条
   * 在"被叫停 / 收工没做成"的趟上也有值；反过来，手改 / 删掉索引都不会让它动。
   * 三态在返回的 `tri` 上（`computed` / `unreadable` / `not_applicable`）。
   */
  getRunArchive: (sid: string): Promise<RunDigestView> =>
    getJSON<RunDigestView>(runDigestPath(sid)),
  getRun: (sid: string): Promise<RunView> => getJSON<RunView>(runPath(sid)),
  getRunEvents: (
    sid: string,
    opts: { sinceIndex?: number; limit?: number } = {},
  ): Promise<RunEventsView> => getJSON<RunEventsView>(runEventsPath(sid, opts)),
  getEvidence: (opts: RowPagingOptions = {}): Promise<EvidenceView> =>
    getJSON<EvidenceView>(evidencePath(opts)),
  getArtifacts: (opts: RowPagingOptions & { runDir?: string } = {}): Promise<ArtifactsView> =>
    getJSON<ArtifactsView>(artifactsPath(opts)),
  /**
   * 文献库那一面（`GET /api/literature`，2026-10-24 的 D-57）。
   *
   * 只算「正式入库」的那一档：判据**只有** `lit_candidates.status=admitted` 那一格
   * （业主 2026-10-24 追裁「老工作区就是读不出来」：不退回 `literature.matched`）。
   * 判不出入库/待入库的不显示，但 `problems[]` 里会留一条 `admission_undecidable`。
   * 每条带 `uses[]`：被哪条命题、第几份证明用过。
   *
   * 三态：`state === "unknown"` 有两支 —— 台账没读成（表不在盘上 / 坏 JSON），
   * 以及「没有候选台账 ⇒ 入库判不出」；两支的 `data.count` 都是 `null`，不是 0。
   * **只读**：没有写函数。
   */
  getLibrary: (): Promise<LibraryView> => getJSON<LibraryView>(ENDPOINTS.literature),
  getAcceptance: (opts: {
    projectDir?: string;
    reportPath?: string;
    capUsd?: number | null;
  } = {}): Promise<AcceptanceView> => getJSON<AcceptanceView>(acceptancePath(opts)),
  /**
   * 论文包三块（`GET /api/package`，2026-11-01 块 3）：A 证明 / B 结构 / C 收工。
   *
   * 一次请求拿三块：三块总是一起看，分成三个端点会让"已签 0 条"与"八格 pass"
   * 来自两个瞬间。三块各自带 `tri`（`computed` / `unreadable` / `not_applicable`），
   * 读不到时整块写"没查成"，不写 0。
   */
  getPackage: (opts: {
    projectDir?: string;
    reportPath?: string;
    capUsd?: number | null;
    sid?: string;
  } = {}): Promise<PackageView> => getJSON<PackageView>(packagePath(opts)),
  /**
   * 一格读数的原文窗口（`GET /api/source`）：只读、工作区内、文本后缀。
   *
   * 后端对越界/绝对路径/工作区外路径一律受控拒绝（`tri="unreadable"` + 理由），
   * 大文件只回前 N 行 + 总行数（`truncated`）。页面不许自己拼文件系统路径。
   */
  getSource: (opts: {
    path: string;
    line?: number;
    match?: string;
  }): Promise<SourceWindow> => getJSON<SourceWindow>(sourcePath(opts)),
  getMachine: (): Promise<MachineView> => getJSON<MachineView>(ENDPOINTS.machine),
  getBudget: (): Promise<BudgetView> => getJSON<BudgetView>(ENDPOINTS.budget),
  getLive: (): Promise<LiveView> => getJSON<LiveView>(ENDPOINTS.live),
  getUsage: (): Promise<UsageView> => getJSON<UsageView>(ENDPOINTS.usage),
  getStatusReports: (): Promise<StatusReportsView> =>
    getJSON<StatusReportsView>(ENDPOINTS.statusReports),
  getChat: (sid: string, opts: { lines?: number } = {}): Promise<ChatView> =>
    getJSON<ChatView>(chatPath(sid, opts)),
  /**
   * 名册那一棵树（`GET /api/roster`，2026-10-21）。
   *
   * 一个 agent 一个节点：父是谁、子有哪些、每个成员的绝对编号／名册名／角色／深度，
   * 外加收件箱那三格（未读 / 已读未 ack / 未消总数）。`/api/roster` 本身仍是**只读**的
   * （它没有配对的 POST）；收口收件箱里那一条走的是另一条写端点 `POST /api/ack`
   * （`postAck`，2026-11-21 WEBFIX2 F7）—— 状态机在 `conductor.close_item`，不在前端。
   *
   * 三态：`answer === "unknown"` 是"这份读数没拿到"（名册目录不在、或读不出来），
   * **不是**"这个工作区没有子代理"—— 面板必须把这两档画成两句话。
   */
  getRoster: (): Promise<RosterView> => getJSON<RosterView>(ENDPOINTS.roster),
  /**
   * 板上三族义务（`GET /api/obligations`，2026-11-19 的 ⑥）。
   *
   * 两条轴分开给：`recipient_instance`（收件实例 = 板项行的 `instance` 列，
   * 由 `obligations.recipient_reading` 判）与 `parent_task_id`（父台账号）。
   * 两轴都空 ⇒ `addressed="unowned"`（没人收）—— 名册收件箱看不见这种项，所以单开一面。
   * **只读**：没有写函数（销号只发生在 conductor 的写路径上）。
   */
  getObligations: (): Promise<ObligationsView> =>
    getJSON<ObligationsView>(ENDPOINTS.obligations),
  /**
   * 两档提示词缓存的状态（`GET /api/cache`，2026-10-23）。
   *
   * 两档 × 四格（落地 / 新鲜 / 覆盖几个 / 缺谁）加换 key 那条提醒。三态：某一档
   * `tri !== "found"` 时那一档的四格全是 `unknown`（附 `reason`），**不是**"没预热"。
   */
  getCache: (): Promise<CacheView> => getJSON<CacheView>(ENDPOINTS.cache),
  /**
   * 按角色 × 类目的错误动作计数（`GET /api/errors`，2026-10-24）。
   *
   * 形状是后端 `readouts.errors_readout(root)` 的返回值逐字（五个键）。三态：
   * `state === "checked"` 才谈得上"几个"；`state === "unknown"` 是"没读到"，
   * `reason` 说明为什么 —— 那一档不许画成 0 行（两张表会是同一个样子）。
   */
  getErrors: (): Promise<RoleErrorsView> => getJSON<RoleErrorsView>(ENDPOINTS.errors),
  /**
   * 错误类目 → 那一句含义（`GET /api/errors/categories`，只读）。
   *
   * 为什么单开一条：那句话的真身在 `errorstats.ERROR_CATEGORIES`，网页不许自己再写
   * 一份（写两份就迟早说两种话）。它没有三态：那是一张常量表。
   */
  getErrorCategories: (): Promise<ErrorCategoryGlossary> =>
    getJSON<ErrorCategoryGlossary>(ENDPOINTS.errorCategories),
  /**
   * 网页操作台账（`GET /api/actions`，AUDIT F11 的读侧）：最近 N 笔网页写操作。
   *
   * 每一行是写侧 `audit.record_action` 造的那十个键（时间 / 来源 / 端点 / 结果 /
   * HTTP / 脱敏后的参数摘要），行序是最新的在前。三态：`tri="unreadable"` 是
   * 「台账读不出来」（**不是**「没有操作」）；文件不在盘上是 `computed` + 0 行。
   * 分页用 `limit` / `offset`，`has_more` 说清还有没有下一页。**只读**：没有写函数。
   */
  getActions: (opts: { limit?: number; offset?: number } = {}): Promise<ActionsView> =>
    getJSON<ActionsView>(actionsPath(opts)),
};

/**
 * 追加一笔额度 / 重设总额（`POST /api/budget`，业主 2026-10-12 的预算窗口）。
 *
 * 与其它写端点同一条路：表单编码 + CSRF 头，回执是写面的统一形状 `WriteResult`。
 * `confirm: "1"` 由后端当硬要求（缺它一律 400，盘上零改动）——前端不许替用户默认填上。
 */
export async function postBudget(body: {
  action: "add" | "set";
  usd: number;
  note?: string;
  by?: string;
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.budget, {
    action: body.action,
    usd: String(body.usd),
    note: body.note ?? "",
    by: body.by ?? "web",
    confirm: "1",
  });
}

/**
 * 起一趟工作流（`POST /api/run`）：把一句话交给主控，等价 CLI 的
 * `run-agent M --task … --subagents`。后端 detached 起进程，回执里给 `pid` 与日志路径。
 */
/**
 * 起一趟（`POST /api/run`）。
 *
 * `sid` + `resume` 是 R91 补上的那一档：M **闲着**时对话页要让它接着说下去 ——
 * 先把用户那句话记进收件箱（`postInterject`），再用**同一句话任务**唤醒这一段
 * （`resume: true` + `sid`）。`resume` 必须配 `sid`（后端 400 拒绝裸 resume）。
 */
export async function postRun(body: {
  task: string;
  sid?: string;
  resume?: boolean;
  dryRun?: boolean;
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.runTask, {
    task: body.task,
    sid: body.sid ?? "",
    resume: body.resume === true ? "1" : "",
    confirm: "1",
    dry_run: body.dryRun === true ? "1" : "",
  });
}

/**
 * 往**正在跑**的那一趟插话（`POST /api/task`）：只有用户能发、只有 M 收，
 * 下一步开头读到，当前这一步不被打断。
 */
export async function postInterject(body: {
  body: string;
  subject?: string;
  sid?: string;
  dryRun?: boolean;
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.interject, {
    body: body.body,
    subject: body.subject ?? "用户插话",
    sid: body.sid ?? "",
    confirm: "1",
    dry_run: body.dryRun === true ? "1" : "",
  });
}


/**
 * 收口一条板项（`POST /api/ack`，2026-11-21 WEBFIX2 F7）。
 *
 * 参数只有两个：`task_id`（哪一条）与 `close`（`acked` / `completed` / `expired`）。
 * `confirm: "1"` 由后端当硬要求（缺它 400，盘上零改动）。
 *
 * 能不能收口**不在这里判**：状态机在 `conductor.close_item`（迁移图 + 空口 ack 闸）。
 * 后端回 409 时那句话就是状态机的原话（例如"已经到过 'block'（不许倒退）"），
 * 页面照原样显示 —— 前端自己判一次就是第二份口径。
 */
export async function postAck(body: {
  taskId: string;
  close?: "acked" | "completed" | "expired";
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.ack, {
    task_id: body.taskId,
    close: body.close ?? "acked",
    confirm: "1",
  });
}

/**
 * 作废一条板项（`POST /api/void`，2026-11-21 BOARDACK）。
 *
 * 什么时候用它、什么时候用「收口」：`/api/ack` 走的是板项状态机（`conductor.close_item`
 * → `item_move` 迁移图 + 业主 A5 的空口 ack 闸），`item_state=block` 的行在迁移图里
 * 没有出边 ⇒ 后端只能回 409（"已经到过 'block'（不许倒退）"）。而"唤醒 ⇒ 再 ack"
 * 也不行：唤醒把 `seen_by` 清空，收口就撞上空口 ack 闸。
 *
 * 所以停在 `block` 的项（优雅停止留下的）走这一条：它把这一条记成"不再需要做"
 * （`item_close=expired`），并写清**为什么**（`why` 必填、逐字进留痕）。
 *
 * 能不能作废**不在这里判**：唯一实现是 `conductor.void_items_by_user`
 * （≡ `void_items(revoke=True, by_human=True)`）。后端回 409 时那句话就是它的原话。
 */
export async function postVoid(body: {
  taskId: string;
  why: string;
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.void, {
    task_id: body.taskId,
    why: body.why,
    confirm: "1",
  });
}

/**
 * 撤销叫停（`POST /api/stop/clear`，2026-11-21 WEBFIX2 F9）。
 *
 * 为什么需要它：叫停之后那把开关会**一直留在盘上**（没有在跑的循环去消费它），
 * 于是"又叫停、又想再起一趟"时那一趟第一步就被旧开关停掉 —— 白起一趟。
 * 唯一写入口是 `stopctl.clear_stop`；盘上本来就没有开关时回 200 + `extra.cleared=false`
 * （"你要的状态已经成立" ≠ "撤掉了"），页面把这两档分开说。
 */
export async function postStopClear(): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.stopClear, { confirm: "1" });
}


/**
 * 预热一档（`POST /api/cache/warm`）：真发请求、真的花钱。
 *
 * `confirm: "1"` 由后端当硬要求（缺它一律 400，盘上零改动），前端不许替用户默认填上 ——
 * 按钮上的二次确认（`ConfirmButton`）就是那一步。
 *
 * `dryRun: true` 只算计划（零花费、同步返回，`extra.plan` 里是完整的计划）；
 * 不给它才是真预热：后端起 detached 子进程，回执里给 `pid` 与日志路径。
 */
export async function postCacheWarm(body: {
  lean: "on" | "off";
  dryRun?: boolean;
}): Promise<WriteResult> {
  return await postJSON<WriteResult>(ENDPOINTS.cacheWarm, {
    lean: body.lean,
    dry_run: body.dryRun === true ? "1" : "",
    confirm: "1",
  });
}


/*
 * 两档提示词缓存（`GET /api/cache`）与错误动作计数（`GET /api/errors`、
 * `/api/errors/categories`）那两族的类型住在 `types.ts`（生成物）。
 *
 * 2026-10-27（业主裁定 ⑥-5 / W4）：它们此前手写在这里 —— 同一件事两份口径，
 * 后端加一格 `tsc` 只会觉得"少了一个可选字段"，一声不吭。现在形状的唯一来源是
 * `webui/readers.py` 的 `_TS_TYPES`（真身仍是 `cachectl.status()` /
 * `readouts.errors_readout()`），本文件只 import 它自己点名用到的那三个。
 */
