/*
 * 挂载点与客户端路由。
 *
 * `ROUTES` 是 C4 契约的前端一侧（`draft/75 §1.4`）：`tests/test_webui_contracts.py`
 * 的 D 条把这里的路由字面量集合与那张表逐字比对，并要求每条路由用到的端点 ∈
 * 后端 ROUTES、用到的 SSE kind ∈ `sse.ts` 的 `KINDS`。
 *
 * 数据流有两条，别混起来：
 *
 * - 全站只订阅一次 SSE（`LiveProvider`），十页共享那份快照与连接态；
 * - 每页另取自己那一条端点（`Live.value.version` 变了就重取），于是"盘上新增 ⇒
 *   流里出现 ⇒ 页面出现"这条链是通的，而六个面不必挤进一条流。
 */
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

import { ConnectionBanner, LiveProvider, useLive } from "./live";
import { CacheBanner } from "./components/PromptCache";
import { Acceptance } from "./pages/Acceptance";
import { Artifacts } from "./pages/Artifacts";
import { Budget } from "./pages/Budget";
import { Evidence } from "./pages/Evidence";
import { Help } from "./pages/Help";
import { Home } from "./pages/Home";
import { Live } from "./pages/Live";
import { Machine } from "./pages/Machine";
import { RoleErrorsPage } from "./pages/RoleErrorsPage";
import { Run } from "./pages/Run";

/** 客户端路由表（逐字对应 `draft/75 §1.4` 的 C4 表）。 */
export const ROUTES = [
  "/",
  "/errors",
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
  { path: "/", label: "对话" },
  /*
   * 2026-10-24（业主：「ui侧加一个大栏专门显示各角色错误动作计数」；同日补正：
   * 「对话页和错误动作页完全一致是怎么回是？」）：这一格是它自己的一条路由 `/errors`。
   *
   * 上一版链的是 `/#role-errors` 锚点，并且刻意不新增路由 —— 想法是"加一格导航"
   * 不必变成"加一张契约表"。但 `matchRoute` 读的是 `window.location.pathname`，
   * 锚点不在里面：点这一格读到的仍是 `/`，画出来的仍是首页那一屏（对话 + 错误动作
   * 计数），两页因此一模一样。所以现在它有自己的路由与自己的页面文件，
   * C4 表（`draft/75 §1.4`）与 `ROUTES` 同步多了这一行。
   */
  { path: "/errors", label: "错误动作" },
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
        工作区根 <span class="mono">{root}</span> · 连接{" "}
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
      {/*
        换 key 的提醒（2026-10-23）：挂在全站最上面 —— 它说的是"整个工作区的提示词
        缓存作废了"，与在哪一页无关。可关掉；换 key 之后它会自己再出现一次
        （`reminder.dismiss_key` 带 key 指纹）。
      */}
      <CacheBanner />
      <ConnectionBanner />
      {renderPage(where.route, where.sid)}
    </main>
  );
}

function renderPage(route: Route, sid: string) {
  switch (route) {
    case "/errors":
      return <RoleErrorsPage />;
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
