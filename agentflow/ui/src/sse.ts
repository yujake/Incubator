/*
 * SSE 订阅（前端这一侧；后端广播器在 `webui/sse.py`，B 线已落地）。
 *
 * 契约是双向的：`KINDS` 是前端这一侧的声明，`tests/test_webui_contracts.py` 的 B 条
 * 拿它与后端的 `EVENT_KINDS` 逐字比对（两边都落地之后那条不再 skip，真跑）。
 *
 * 三条真接上的证据（都是可读的符号，不是形容词）：
 *
 * 1. `EventSource`：每个 kind 逐个 `addEventListener`（`KINDS` 里一个都不漏）；
 * 2. `since`：记住上一帧的 `lastEventId`，重连时作为 `?since=` 发回去 ——
 *    后端 `handle_stream` 就按这个值从环形缓冲里补发（补不齐会补一条全量 state）；
 * 3. `setInterval`：退避重连三次仍连不上 ⇒ 降级成轮询 `/api/state`，
 *    并**如实**把连接态报成 `degraded`（顶部横幅据此显示"实时已降级为轮询"）。
 *    流断了不算"没有事件"——页面上的读数必须继续动。
 */
import { api, ENDPOINTS } from "./api";

/** 事件种类（C2 契约的前端一侧；与后端 `webui/sse.py` 的 EVENT_KINDS 逐字相同）。 */
export const KINDS = [
  "state",
  "question",
  "answered",
  "checkpoint",
  "stop",
  "heartbeat",
] as const;

export type Kind = (typeof KINDS)[number];

export type Handlers = {
  [K in Kind]?: (data: unknown) => void;
};

/** 连接态（三档，页面顶部据此说清"现在这份读数是推来的还是轮来的"）。 */
export type Connection = "connecting" | "live" | "degraded";

/** 重连退避的上限（次）：到这个数还没连上就降级为轮询。 */
export const MAX_RETRIES = 3;

/**
 * 流端点的落点（与 `api.ts` 的 `ENDPOINTS.stream` 同源 —— 那个表是端点的唯一出口，
 * 这里不另写一份字面量，否则 A 条的两侧会各说各话）。
 */
export const STREAM_PATH: string = ENDPOINTS.stream;

export interface SubscribeOptions {
  since?: number;
  onStatus?: (state: Connection) => void;
}

/** 订阅一条流，返回退订函数（页面卸载时必须调它，否则连接会一直挂着）。 */
export function subscribe(
  sid: string | null,
  h: Handlers,
  opts: SubscribeOptions = {},
): () => void {
  let lastId = typeof opts.since === "number" ? opts.since : 0;
  let source: EventSource | null = null;
  let poll: number | null = null;
  let tries = 0;
  let closed = false;

  const stopPolling = (): void => {
    if (poll !== null) {
      window.clearInterval(poll);
      poll = null;
    }
  };

  const startPolling = (): void => {
    if (poll !== null || closed) {
      return;
    }
    opts.onStatus?.("degraded");
    poll = window.setInterval(() => {
      void api
        .getState()
        .then((snapshot) => {
          if (h.state) {
            h.state({ snapshot });
          }
        })
        .catch(() => {
          // 轮询也失败：连接态留在 degraded（那是"没查成"，不是"没有事件"）。
        });
    }, 2000);
  };

  const open = (): void => {
    if (closed) {
      return;
    }
    const url = new URL(STREAM_PATH, window.location.href);
    if (sid) {
      url.searchParams.set("sid", sid);
    }
    if (lastId > 0) {
      url.searchParams.set("since", String(lastId));
    }
    opts.onStatus?.("connecting");
    source = new EventSource(url.toString());
    for (const kind of KINDS) {
      source.addEventListener(kind, (ev) => {
        const frame = ev as MessageEvent;
        if (frame.lastEventId !== "") {
          const got = Number.parseInt(frame.lastEventId, 10);
          if (Number.isFinite(got)) {
            lastId = got;
          }
        }
        const fn = h[kind];
        if (!fn) {
          return;
        }
        try {
          fn(JSON.parse(frame.data));
        } catch {
          // 解不出的帧按"这一帧没读成"处置：不把它当成一条空事件。
        }
      });
    }
    source.addEventListener("open", () => {
      tries = 0;
      stopPolling();
      opts.onStatus?.("live");
    });
    source.addEventListener("error", () => {
      source?.close();
      source = null;
      if (closed) {
        return;
      }
      tries += 1;
      if (tries >= MAX_RETRIES) {
        startPolling();
        return;
      }
      window.setTimeout(open, 500 * Math.pow(2, tries));
    });
  };

  open();

  return () => {
    closed = true;
    stopPolling();
    source?.close();
    source = null;
  };
}
