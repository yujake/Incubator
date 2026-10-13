/*
 * 挂载点与客户端路由。
 *
 * `ROUTES` 是 C4 契约的前端一侧（`draft/75 §1.4`）：`tests/test_webui_contracts.py`
 * 的 D 条把这里的路由字面量集合与那张表逐字比对，并要求每条路由用到的端点 ∈
 * 后端 ROUTES、用到的 SSE kind ∈ `sse.ts` 的 `KINDS`。
 *
 * 数据流有两条，别混起来：
 *
 * - 全站只订阅**一次** SSE（`LiveProvider`），九页共享那份快照与连接态；
 * - 每页另取自己那一条端点（`Live.value.version` 变了就重取），于是"盘上新增 ⇒
 *   流里出现 ⇒ 页面出现"这条链是通的，而六个面不必挤进一条流。
 */
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

import { ConnectionBanner, LiveProvider, useLive } from "./live";
import { Acceptance } from "./pages/Acceptance";
import { Artifacts } from "./pages/Artifacts";
import { Budget } from "./pages/Budget";
import { Evidence } from "./pages/Evidence";
import { Help } from "./pages/Help";
import { Home } from "./pages/Home";
import { Live } from "./pages/Live";
import { Machine } from "./pages/Machine";
import { Run } from "./pages/Run";

/** 客户端路由表（逐字对应 `draft/75 §1.4` 的 C4 表）。 */
export const ROUTES = [
  "/",
  "/run/:sid",
  "/evidence",
  "/artifacts",
  "/acceptance",
  "/machine",
  "/budget",
  "/live",
  "/help",
] as const;

export type Route = (typeof ROUTES)[number];

/** 把 `location.pathname` 读成一个路由（读不出来就回首页 —— 服务端已按 Q1 回退）。 */
export function matchRoute(path: string): { route: Route; sid: string } {
  if (path.startsWith("/run/")) {
    return { route: "/run/:sid", sid: decodeURIComponent(path.slice("/run/".length)) };
  }
  const hit = ROUTES.find((r) => r === path);
  return { route: hit === undefined ? "/" : hit, sid: "" };
}

/** 顶部导航：每一条都是 C4 表里的一个客户端路由（`/run/:sid` 由会话行进入）。 */
const NAV: ReadonlyArray<{ path: string; label: string }> = [
  { path: "/", label: "待回答" },
  { path: "/live", label: "在飞" },
  { path: "/budget", label: "预算" },
  { path: "/evidence", label: "证据链" },
  { path: "/artifacts", label: "产物" },
  { path: "/acceptance", label: "验收" },
  { path: "/machine", label: "本机" },
  { path: "/help", label: "使用说明" },
];

function Top() {
  const live = useLive();
  const root =
    live.snapshot === null
      ? "（工作区根还没读到）"
      : live.snapshot.root;
  return (
    <header class="top">
      <div class="brand">agentflow 用户端</div>
      <div class="sub">
        状态一律从盘上派生（每次请求重新读，页面里不缓存）· 工作区根{" "}
        <span class="mono">{root}</span> · 连接{" "}
        <span class="mono">{live.connection}</span>
      </div>
      <nav class="nav">
        {NAV.map((item) => (
          <a class="nav-link" href={item.path} key={item.path}>
            {item.label}
          </a>
        ))}
      </nav>
    </header>
  );
}

function Body() {
  const [where, setWhere] = useState(() => matchRoute(window.location.pathname));

  useEffect(() => {
    const onPop = (): void => {
      setWhere(matchRoute(window.location.pathname));
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
    };
  }, []);

  return (
    <main class="wrap">
      <ConnectionBanner />
      {renderPage(where.route, where.sid)}
    </main>
  );
}

function renderPage(route: Route, sid: string) {
  switch (route) {
    case "/run/:sid":
      return <Run sid={sid} />;
    case "/evidence":
      return <Evidence />;
    case "/artifacts":
      return <Artifacts />;
    case "/acceptance":
      return <Acceptance />;
    case "/machine":
      return <Machine />;
    case "/budget":
      return <Budget />;
    case "/live":
      return <Live />;
    case "/help":
      return <Help />;
    default:
      return <Home />;
  }
}

function App() {
  return (
    <LiveProvider>
      <Top />
      <Body />
    </LiveProvider>
  );
}

function mount(): void {
  const host = document.getElementById("app");
  if (host === null) {
    throw new Error("页面里没有 #app 挂载点（index.html 被改过？）");
  }
  render(<App />, host);
}

mount();
