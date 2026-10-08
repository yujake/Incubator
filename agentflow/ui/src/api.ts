/*
 * 网关层（前端唯一的网络出口）。
 *
 * 三条纪律：
 *
 * 1. 路径只在 ENDPOINTS 里写一次 —— `tests/test_webui_contracts.py` 的 A 条把
 *    这里的路径字面量集合与后端 `webui/routes.py` 的 ROUTES 逐字比对。
 *    后端有的（B 线六个只读面 + A 线的 /api/run-index + C 线既有的
 *    POST /answer + 题 T2-a 的 `/api/run/{sid}/events`）前端必须逐条声明；反过来，前端多写一个后端没有的端点也会红。
 *    `POST /api/stop` / `POST /api/submit` / `POST /api/settings`（契约 C1 第 8–10 行）
 *    属于 C 线 W3/W4，后端今天还没有那三条路由 —— 所以这里一条都不写：
 *    "前端声明了而后端没有"正是 A 条要抓的漂移。
 * 2. 失败不许折成空读数：HTTP 非 2xx 与网络故障都抛 ApiError，三态走 `tri`
 *    （`unreadable` = 没查成），由页面渲染成 TriState。绝不返回空对象装作读到了。
 * 3. 写请求带 X-CSRF-Token（从 `<meta name="csrf-token">` 读；服务端每进程换一个）。
 */
import type {
  AcceptanceView,
  ArtifactsView,
  EvidenceView,
  MachineView,
  RunEventsView,
  RunIndexDrift,
  RunView,
  StateSnapshot,
  Tri,
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

/** 收工门那条端点的查询串（三个可选输入，逐字对应后端的 `?project_dir=` 等）。 */
export function acceptancePath(opts: {
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

/** 一次写动作的结局（三态；写面的统一回执 `WriteResult` 要等 C 线 W3/W4）。 */
export interface WriteOutcome {
  ok: boolean;
  tri: Tri;
  reason: string;
}

/**
 * 回答一个问题（`POST /answer`，C 线今天唯一已有的写路径）。
 *
 * 为什么不用 `postJSON`：这一批的 `/answer` 回的是 PRG（303 回首页），不是
 * `WriteResult`。跟着重定向走会拿到一支 HTML 而 `fetch` 把它当 200，于是"写成了"
 * 会被读成"正文不是 JSON" —— 那正是三态纪律要挡的那种错读。
 *
 * 所以这里 `redirect: "manual"`，按响应分档：
 *
 * - `opaqueredirect` ⇒ 服务端回了 303：这次回答真的落盘了（`handle_answer` 只在
 *   `writes.answer` 成功时回 303）。`tri` 记 `not_applicable`：这一格现在没有
 *   "算出来的读数"，如实说明回执要等 W3，而不是假装拿到了 `ok`；
 * - 409 ⇒ 这条 qid 不待答（已答过 / 未知），按既有判据盘上零写入；
 * - 其余非 2xx ⇒ 按状态码如实报错。
 */
export async function postAnswer(body: Record<string, string | string[]>): Promise<WriteOutcome> {
  const resp = await postForm(ENDPOINTS.answer, body, "manual");
  if (resp.type === "opaqueredirect") {
    return {
      ok: true,
      tri: "not_applicable",
      reason: "服务端回了 PRG（303 回首页）⇒ 这次回答落盘了；写面的统一回执（WriteResult）要等 W3",
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
 * 六页各自只调自己那一面：Home（以及每页的壳）读 `getState()`，Run 读 `getRun()`
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
};
