/*
 * 网关层（前端唯一的网络出口）。
 *
 * 三条纪律：
 *
 * 1. 路径只在 ENDPOINTS 里写一次 —— `tests/test_webui_contracts.py` 的 A 条把
 *    这里的路径字面量集合与后端 `webui/routes.py` 的 ROUTES 逐字比对：后端有的
 *    前端必须逐条声明，前端多写一个后端没有的也会红。**谁有多少条不在这里抄** ——
 *    抄一份就会与那边漂移（这一段此前写着"写面只到 W3，停/提交/设置还没落地"、
 *    又漏了 /api/run 与 /api/task，而那七条写端点早已全部接线）。
 * 2. 失败不许折成空读数：HTTP 非 2xx 与网络故障都抛 ApiError，三态走 `tri`
 *    （`unreadable` = 没查成），由页面渲染成 TriState。绝不返回空对象装作读到了。
 * 3. 写请求带 X-CSRF-Token（从 `<meta name="csrf-token">` 读；服务端每进程换一个）。
 */
import type {
  AcceptanceView,
  ArtifactsView,
  BudgetView,
  EvidenceView,
  LiveView,
  MachineView,
  RosterView,
  RunEventsView,
  RunIndexDrift,
  RunView,
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
  run: "/api/run/{sid}",
  runEvents: "/api/run/{sid}/events",
  evidence: "/api/evidence",
  artifacts: "/api/artifacts",
  acceptance: "/api/acceptance",
  machine: "/api/machine",
  answer: "/answer",
  stop: "/api/stop",
  submit: "/api/submit",
  settings: "/api/settings",
  budget: "/api/budget",
  runTask: "/api/run",
  interject: "/api/task",
  live: "/api/live",
  usage: "/api/usage",
  statusReports: "/api/status-reports",
  chat: "/api/chat",
  // 2026-10-21（业主的「名册监视」）：整棵名册树（父/子/绝对编号/角色/深度/收件箱三格）。
  // 只读一条 —— 这个端点在路由表里没有配对的 POST，前端也不该有写它的函数。
  roster: "/api/roster",
  // 2026-10-23（业主：「把两档缓存落地为用户使用系统时可调用的工具」）：
  // 两档提示词缓存的状态读数（只读）与预热（写，会花钱）。两条的形状与
  // `webui/cacheface.py` 的两个处理器逐字对应。
  cache: "/api/cache",
  cacheWarm: "/api/cache/warm",
  stream: "/api/stream",
} as const;

export type EndpointName = keyof typeof ENDPOINTS;

/** 一趟详情的实参拼装（`/api/run/{sid}` 的那一个占位符）。 */
export function runPath(sid: string): string {
  return ENDPOINTS.run.replace("{sid}", encodeURIComponent(sid));
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

/** 请求失败时抛的那个东西：状态码 + 三态 + 人话理由（页面据此渲染 TriState）。 */
export class ApiError extends Error {
  readonly code: number;
  readonly tri: Tri;
  readonly reason: string;

  constructor(code: number, tri: Tri, reason: string) {
    super(`${code} ${reason}`);
    this.name = "ApiError";
    this.code = code;
    this.tri = tri;
    this.reason = reason;
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
    throw new ApiError(resp.status, "unreadable", text.trim().slice(0, 300) || "服务端没有给正文");
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(resp.status, "unreadable", "正文不是 JSON（没查成，不是空读数）");
  }
}

/** 读一个 JSON 端点。失败抛 ApiError（不返回空对象）。 */
export async function getJSON<T>(url: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (exc) {
    throw new ApiError(0, "unreadable", `请求没发出去：${String(exc)}`);
  }
  return await readJSON<T>(resp);
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
  try {
    return await fetch(url, {
      method: "POST",
      redirect,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-CSRF-Token": csrf(),
        Accept: "application/json",
      },
      body: form.toString(),
    });
  } catch (exc) {
    throw new ApiError(0, "unreadable", `请求没发出去：${String(exc)}`);
  }
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
  getRun: (sid: string): Promise<RunView> => getJSON<RunView>(runPath(sid)),
  getRunEvents: (
    sid: string,
    opts: { sinceIndex?: number; limit?: number } = {},
  ): Promise<RunEventsView> => getJSON<RunEventsView>(runEventsPath(sid, opts)),
  getEvidence: (): Promise<EvidenceView> => getJSON<EvidenceView>(ENDPOINTS.evidence),
  getArtifacts: (): Promise<ArtifactsView> => getJSON<ArtifactsView>(ENDPOINTS.artifacts),
  getAcceptance: (opts: {
    projectDir?: string;
    reportPath?: string;
    capUsd?: number | null;
  } = {}): Promise<AcceptanceView> => getJSON<AcceptanceView>(acceptancePath(opts)),
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
   * 外加收件箱那三格（未读 / 已读未 ack / 未消总数）。**只读**：这个端点在路由表里没有配对的 POST，所以这里
   * 只有取数函数，没有写函数。
   *
   * 三态：`answer === "unknown"` 是"这份读数没拿到"（名册目录不在、或读不出来），
   * **不是**"这个工作区没有子代理"—— 面板必须把这两档画成两句话。
   */
  getRoster: (): Promise<RosterView> => getJSON<RosterView>(ENDPOINTS.roster),
  /**
   * 两档提示词缓存的状态（`GET /api/cache`，2026-10-23）。
   *
   * 两档 × 四格（落地 / 新鲜 / 覆盖几个 / 缺谁）加换 key 那条提醒。三态：某一档
   * `tri !== "found"` 时那一档的四格全是 `unknown`（附 `reason`），**不是**"没预热"。
   */
  getCache: (): Promise<CacheView> => getJSON<CacheView>(ENDPOINTS.cache),
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
 * 两档提示词缓存的状态读数（`GET /api/cache` 的返回形状）。
 *
 * 为什么这几个接口写在这里而不是 `types.ts`：`types.ts` 是生成物（`agentflow/web/emit_types.py`
 * 拼三条零交线各自的 `type_decls()`，判据逐字节比对），本轮的判据只核对生成物里那些接口，
 * 所以它们不进生成物；而这一面的唯一消费者就是 `components/PromptCache.tsx`。形状与
 * `agentflow/cachectl.py::status()` 的键逐字相同（改名会让页面画出 `undefined`）。
 */
export interface CacheTargetCell {
  state: string;
  fresh: boolean | null;
  recorded_sha256: string;
  now_sha256: string;
  absent_reason: string;
}

/** 一档里 key 那一格：`same` / `stale` / `unknown`（旧读数没记指纹）。 */
export interface CacheKeyCell {
  tri: string;
  reason: string;
  changed: string[];
  affected: string[];
  affected_why: string;
  text: string;
  recorded: { fingerprint: string; model: string; base_url: string };
}

/** 一档的四格读数（`cachectl.tier_reading()` 的键逐字）。 */
export interface CacheTier {
  tier: string;
  label: string;
  lean_enabled: boolean;
  tri: string;
  reason: string;
  warmed: boolean;
  fresh: boolean | null;
  fresh_reason: string;
  not_fresh: string[];
  version_mismatch: boolean;
  covered: number;
  covered_fresh: number;
  total: number;
  missing: string[];
  absent: string[];
  absent_reason: Record<string, string>;
  at: string;
  prompt_version: string;
  readings_prompt_version: string;
  spent_usd: number | null;
  model: string;
  per_target: Record<string, CacheTargetCell>;
  key: CacheKeyCell;
}

/**
 * 当前这一趟会用哪一档（`cachectl.active_reading()` 的键逐字）。
 *
 * 为什么单独一格：`tiers` 回答"两档各自落没落地"，回答不了"我现在打开的这一档用的是
 * 哪一份缓存"。`tri` 是三态（`found` / `unknown`）：读不出来时 `why` 说理由、`text`
 * 是"当前没有可用缓存"那一句；这时 `fresh` 是 `false`，但它的意思是"这一趟不能当
 * 新鲜用"，不是"量过了发现变了" —— 先看 `tri`，再看 `fresh`。
 *
 * `text` 是给人看的那一行，命令行 `cache status` 印的是同一个字符串（同一个函数出）；
 * 页面只把里面的加粗标记画成粗体，不另拼文案。
 */
export interface CacheActive {
  tier: string;
  label: string;
  lean: boolean;
  strategy: string;
  run_at: string;
  prompt_version: string;
  readings_prompt_version: string;
  covered: string;
  covered_count: number;
  total: number;
  missing: string[];
  absent: string[];
  fresh: boolean;
  tri: string;
  why: string;
  text: string;
}

/** 网页顶部那条提醒（`cachectl.status()["reminder"]`）。 */
export interface CacheReminder {
  active: boolean;
  tri: string;
  tiers: string[];
  text: string;
  affected: string[];
  /** 这个提醒属于哪一片缓存（指纹 + 模型）：换 key 之后它变了，被关掉的横幅会再现。 */
  dismiss_key: string;
}

/** `GET /api/cache` 的整份读数。 */
export interface CacheView {
  schema: number;
  at: string;
  readings: string;
  lean_now: boolean;
  prompt_version: string;
  key: {
    configured: boolean;
    source: string;
    model: string;
    base_url: string;
    key_chars: number;
    fingerprint: string;
  };
  tiers: Record<string, CacheTier>;
  /** 按当前开关，这一趟会命中哪一档（顶部横幅与面板都先画这一行）。 */
  active: CacheActive;
  reminder: CacheReminder;
  verdict: {
    tri: string;
    unknown_tiers: string[];
    stale_tiers: string[];
    key_unknown_tiers: string[];
  };
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
