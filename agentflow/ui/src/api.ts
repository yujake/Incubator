/*
 * 网关层（前端唯一的网络出口）。
 *
 * 三条纪律：
 *
 * 1. 路径只在 ENDPOINTS 里写一次 —— `tests/test_webui_contracts.py` 的 A 条把
 *    这里的路径字面量集合与后端 `webui/routes.py` 的 ROUTES 逐字比对。
 *    B 线已落地六个只读面，所以这里补齐对应的六条（`/api/task` 按裁定 I1 不做，
 *    因此表里没有它）：前端多写一个后端没有的端点、或后端有而前端没声明，A 条都会红。
 * 2. 失败不许折成空读数：HTTP 非 2xx 与网络故障都抛 ApiError，三态走 `tri`
 *    （`unreadable` = 没查成），由页面渲染成 TriState。绝不返回空对象装作读到了。
 * 3. 写请求带 X-CSRF-Token（从 `<meta name="csrf-token">` 读；服务端每进程换一个）。
 */
import type { StateSnapshot } from "./types";

/**
 * 后端端点表（与 `webui/routes.py` 的 `ROUTES` 逐字对齐）。
 *
 * 带 `{}` 的那几条是路由模式：`api.ts` 里用模板串拼实参，
 * 判据会把 `${sid}` 归一成 `{sid}` 再比（见 A 条的 `_literals`）。
 */
export const ENDPOINTS = {
  state: "/api/state",
  run: "/api/run/{sid}",
  evidence: "/api/evidence",
  artifacts: "/api/artifacts",
  acceptance: "/api/acceptance",
  machine: "/api/machine",
  answer: "/answer",
  stream: "/api/stream",
} as const;

export type EndpointName = keyof typeof ENDPOINTS;

/** 三态：算出来了 / 没查成 / 用不着（词表本体在 `types.ts`，生成物）。 */
import type { Tri } from "./types";

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

/** 写一个端点（表单编码 + CSRF 头）。失败抛 ApiError。 */
export async function postJSON<T>(url: string, body: Record<string, string>): Promise<T> {
  const form = new URLSearchParams();
  for (const [key, value] of Object.entries(body)) {
    form.append(key, value);
  }
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
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
  return await readJSON<T>(resp);
}

/**
 * 页面用的那几个调用。W0 只有 Home 真的调 `getState()`（"一处真数据"）。
 *
 * `postAnswer` 现在没有页面调它，而且它今天回的是 PRG（303 重定向回首页）或一段
 * HTML，不是 JSON —— 写面的三态回执（`WriteResult`）要等 W3 的写面落地。
 * 这里先留着它，是因为 A 条要的正是"前端声明的端点集合与后端路由表逐字相等"，
 * 而 `POST /answer` 是后端今天就有的那一个。
 */
export const api = {
  getState: (): Promise<StateSnapshot> => getJSON<StateSnapshot>(ENDPOINTS.state),
  postAnswer: (qid: string, sid: string, body: Record<string, string>): Promise<unknown> =>
    postJSON<unknown>(ENDPOINTS.answer, { qid, sid, ...body }),
};
