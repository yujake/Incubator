/*
 * SSE 订阅（W0：只把订阅侧写好；后端的广播器在 W2 的 `webui/sse.py`）。
 *
 * 为什么 W0 就写它：契约是双向的。`KINDS` 是前端这一侧的声明，
 * `tests/test_webui_contracts.py` 的 B 条要拿它与后端的 `EVENT_KINDS` 逐字比对；
 * 后端那一半（W2）落地之前，B 条会 skip 并在理由里写明 —— 而不是静默算过。
 *
 * 降级路径是必须的（`draft/73 §2.1` 的文本级判据就是查这三个符号）：
 * `EventSource` / `since` / `setInterval`。流断了不算"没有事件"：
 * 退避重连三次之后改成轮询 `/api/state`，让页面上的读数继续动。
 */
import { api } from "./api";

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

/**
 * 流端点的落点。W0 后端还没有这条路由（W2 才有），所以它**不在** `api.ts` 的
 * ENDPOINTS 里 —— 契约判据 D 对"页面里出现的端点"要求 ∈ ROUTES，这一条是唯一
 * 被登记的例外（`tests/test_webui_contracts.py` 的 `_ENDPOINT_ALLOWLIST`，
 * 并在后端落地之后由反向断言要求把这条登记删掉）。
 */
export const STREAM_PATH = "/api/stream";

/** 订阅一条流，返回退订函数（页面卸载时必须调它，否则连接会一直挂着）。 */
export function subscribe(
  sid: string | null,
  h: Handlers,
  opts: { since?: number } = {},
): () => void {
  const url = new URL(STREAM_PATH, window.location.href);
  if (sid) {
    url.searchParams.set("sid", sid);
  }
  if (typeof opts.since === "number") {
    url.searchParams.set("since", String(opts.since));
  }
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
    poll = window.setInterval(() => {
      void api.getState().then((snapshot) => {
        if (h.state) {
          h.state({ snapshot });
        }
      });
    }, 2000);
  };

  const open = (): void => {
    if (closed) {
      return;
    }
    source = new EventSource(url.toString());
    for (const kind of KINDS) {
      source.addEventListener(kind, (ev) => {
        const fn = h[kind];
        if (fn) {
          fn(JSON.parse((ev as MessageEvent).data));
        }
      });
    }
    source.addEventListener("open", () => {
      tries = 0;
      stopPolling();
    });
    source.addEventListener("error", () => {
      source?.close();
      source = null;
      tries += 1;
      if (tries >= 3) {
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
