/*
 * 实时层：全站**只订阅一次** SSE，把快照与"连接态"分发给各页。
 *
 * 为什么要有这一层（`draft/75 §2.4` 的一句）：六页各订阅一条流就是六条 TCP 连接、
 * 六份重复的快照，而它们看的是同一份盘上事实。这里订阅一次，页面从 context 读。
 *
 * 分发的两样东西各有用途，别把它们混起来：
 *
 * - `snapshot`：`/api/state` 的读数（Home 直接用；其余页的壳用它显示工作区根）；
 * - `version`：**每次流里来了事件就 +1** 的计数器。页面把它当 effect 的依赖项，
 *   于是"盘上新增 ⇒ 流里出现 ⇒ 页面重取自己那一面"这条链是通的，而每页仍然
 *   只取自己那一条端点（不把六个面堆进一条流）。
 *
 * 降级：`subscribe()` 三次重连失败后改成轮询 `/api/state`，并把连接态报成
 * `degraded`；顶部横幅据此显示"实时已降级为轮询"。轮询期间读数照样动。
 */
import { createContext } from "preact";
import type { ComponentChildren } from "preact";
import { useCallback, useContext, useEffect, useRef, useState } from "preact/hooks";

import { api, whyOf } from "./api";
import { subscribe } from "./sse";
import type { Connection } from "./sse";
import type { StateSnapshot } from "./types";

export interface LiveValue {
  /** 最近一次 `/api/state` 的读数；`null` = 还没读到（不是"空工作区"）。 */
  snapshot: StateSnapshot | null;
  /** 快照这一条链没查成的原因（空串 = 没出问题）。 */
  problem: string;
  /** 连接态：`connecting` / `live`（SSE 在推）/ `degraded`（已降级为轮询）。 */
  connection: Connection;
  /** 流里每来一条事件 +1（页面的取数 effect 依赖它）。 */
  version: number;
  /** 手动重取一次快照（Home 的"回答"之后用它把面板刷掉）。 */
  refresh: () => void;
}

const LIVE_ZERO: LiveValue = {
  snapshot: null,
  problem: "",
  connection: "connecting",
  version: 0,
  refresh: () => undefined,
};

export const LiveContext = createContext<LiveValue>(LIVE_ZERO);

/** 页面读实时层的那一个入口。 */
export function useLive(): LiveValue {
  return useContext(LiveContext);
}

/** 一个"流里来过事件就重取一次自己那一面"的 effect 依赖项。 */
export function useVersion(): number {
  return useLive().version;
}

/** 一页自己那一面的读数：`data` 为空且 `problem` 为空 = 还在读（不是"空工作区"）。 */
export interface FaceState<T> {
  data: T | null;
  problem: string;
  reload: () => void;
}

/**
 * 取一页自己那一条端点，并在流里来过事件之后自动重取。
 *
 * 为什么把 `load` 放进 ref 而不是 effect 的依赖：页面每次渲染都会新建一个闭包，
 * 把它当依赖就等于每次渲染都重取一次（自激循环）。真正的触发条件只有两个 ——
 * 挂载，以及 `live.version` 变了（流里来了一条事件）。
 */
export function useFace<T>(load: () => Promise<T>): FaceState<T> {
  const live = useLive();
  const [data, setData] = useState<T | null>(null);
  const [problem, setProblem] = useState<string>("");
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    let alive = true;
    loadRef
      .current()
      .then((got) => {
        if (alive) {
          setData(got);
          setProblem("");
        }
      })
      .catch((exc: unknown) => {
        if (alive) {
          setProblem(whyOf(exc));
        }
      });
    return () => {
      alive = false;
    };
  }, [live.version, tick]);
  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);
  return { data, problem, reload };
}

export interface LiveProviderProps {
  children?: ComponentChildren;
}

export function LiveProvider(props: LiveProviderProps) {
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [problem, setProblem] = useState<string>("");
  const [connection, setConnection] = useState<Connection>("connecting");
  const [version, setVersion] = useState(0);
  const alive = useRef(true);

  const pull = useCallback((): void => {
    void api
      .getState()
      .then((got) => {
        if (alive.current) {
          setSnapshot(got);
          setProblem("");
        }
      })
      .catch((exc: unknown) => {
        if (alive.current) {
          setProblem(whyOf(exc));
        }
      });
  }, []);

  useEffect(() => {
    alive.current = true;
    pull();
    const stop = subscribe(null, {
      state: (data) => {
        const payload = data as { snapshot?: StateSnapshot };
        if (payload && payload.snapshot) {
          setSnapshot(payload.snapshot);
          setProblem("");
        } else {
          // 后端补发时若补不齐会带 `reason`（见 `sse.handle_stream`）：
          // 那是"这一帧的读数没查成"，不是"工作区空了"。
          setProblem("流里的 state 帧没带快照（补发补不齐？）—— 这一份读数没查成");
        }
        setVersion((v) => v + 1);
      },
      question: () => {
        setVersion((v) => v + 1);
        pull();
      },
      answered: () => {
        setVersion((v) => v + 1);
        pull();
      },
      checkpoint: () => {
        setVersion((v) => v + 1);
      },
      stop: () => {
        setVersion((v) => v + 1);
        pull();
      },
      heartbeat: () => {
        // 心跳本身不是事件；它证明这条流还活着（连接态由 open/error 管）。
      },
    }, { onStatus: setConnection });
    return () => {
      alive.current = false;
      stop();
    };
  }, [pull]);

  const value: LiveValue = {
    snapshot,
    problem,
    connection,
    version,
    refresh: pull,
  };
  return <LiveContext.Provider value={value}>{props.children}</LiveContext.Provider>;
}

/** 连接态与快照问题的那一条横幅（六个页面共用一个，口径只有一处）。 */
export function ConnectionBanner() {
  const live = useLive();
  if (live.connection === "degraded") {
    return (
      <div class="card problem">
        <span class="badge badge-unknown">实时已降级为轮询</span>
        <span class="readings">
          SSE 三次重连都没接上 ⇒ 每隔 2 秒取一次 <span class="mono">/api/state</span>。
          读数照样在动，但它不再是推来的。
        </span>
      </div>
    );
  }
  if (live.problem !== "") {
    return (
      <div class="card problem">
        <span class="badge badge-unknown">快照没查成</span>
        <span class="readings">{live.problem}</span>
      </div>
    );
  }
  return null;
}
