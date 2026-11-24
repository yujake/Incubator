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
import { Card } from "./components/Card";
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

/** 把 `location.pathname` 读成一个路由（读不出来就回首页 —— 服务端已按 Q1 回退）。
 *
 * `path` 那一格把原样路径带出去：回首页这件事本身是对的（服务端把未知路径回退成
 * 同一支外壳），但"回首页"不许等于"装作这一页存在" —— `Body` 用它判"是不是真的首页"。
 */
export function matchRoute(path: string): { route: Route; sid: string; path: string } {
  if (path.startsWith("/run/")) {
    return { route: "/run/:sid", sid: decodeURIComponent(path.slice("/run/".length)),
             path };
  }
  const hit = ROUTES.find((r) => r === path);
  return { route: hit === undefined ? "/" : hit, sid: "", path };
}

/** 顶部导航：每一条都是 C4 表里的一个客户端路由（`/run/:sid` 由会话行进入）。 */
const NAV: ReadonlyArray<{ path: string; label: string }> = [
  { path: "/", label: "对话" },
  /*
   * 业主：「ui侧加一个大栏专门显示各角色错误动作计数」（补正：「对话页和错误动作页
   * 完全一致是怎么回是？」）：这一格是它自己的一条路由 `/errors`。
   *
   * 它不能链 `/#role-errors` 锚点：`matchRoute` 读的是 `window.location.pathname`，
   * 锚点不在里面 —— 点这一格读到的仍是 `/`，画出来的仍是首页那一屏（两页一模一样）。
   * 所以它有自己的路由与自己的页面文件，
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
  const snap = live.snapshot;
  const root = snap === null ? "（工作区根还没读到）" : snap.root;
  // 「我在看哪个项目 / 哪一段会话 / 第几轮」—— 三格都来自同一份 `/api/state`
  // （`project` / `current` 两栏），不另取一条端点：顶栏每页都在，多一条请求就是
  // 每页多一份读盘。`current.sid` 与命令行 `start --watch` 印的是同一个号
  // （`serve(sid=…)` 交下来的那个），轮号两边都调 `sessions.round_of()`。
  // 顶栏只说"工作区 / 会话 / 轮 / 连接"这四件事。根**不是**项目文件夹时不再画一个
  // 「（不是项目文件夹）」——那是把内部概念（project vs workspace）摆到用户面前，
  // 而用户要的只是"我现在看的是哪个目录"（业主 2026-11-24）。
  const project =
    snap === null || !snap.project.is_project ? "" : snap.project.name;
  const sid = snap === null || snap.current.sid === "" ? "（还没有会话）" : snap.current.sid;
  const round = snap === null ? "（还没读到）" : String(snap.current.round);
  return (
    <header class="top">
      <div class="brand">agentflow 用户端</div>
      <div class="sub">
        {project === "" ? null : (
          <>
            项目 <b class="mono">{project}</b> ·{" "}
          </>
        )}
        工作区根 <span class="mono">{root}</span>
        {/* AUDIT F8：根在 `serve()` 那一刻钉死，页面**没有**切换入口（裁定：没有入口
            就不新增功能）。所以这里只如实说"怎么换"——停服务、换 `--root` 重启。
            不摆任何按钮/下拉：一个点了没反应的切换控件比没有更坏。 */}
        <span class="tri-reason">（启动时钉死；换工作区要重启服务并换 --root）</span>
      </div>
      <div class="sub">
        会话 <span class="mono">{sid}</span> · 第 <span class="mono">{round}</span> 轮 · 连接{" "}
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

/** 没有这一页：客户端路由里没有这个路径。

 * 为什么要有它（2026-11-21 USERGUIDE-WEB 的实测缺口）：服务端按 Q1 把未知路径回退成
 * 同一支 SPA 外壳，于是 `/compliance` 这种猜出来的路径会安静地渲染成首页那一屏 ——
 * 用户看到的是「对话」页，而不是"这一页不存在"。这里如实说，并把几处常被猜错的路径
 * 指到它真身那一页：合规/收工门那一块在「验收」（`/acceptance` 的 B 块），
 * 板项（任务板）在 `/live` 的名册卡与「产物」页的任务台账里。
 */
function UnknownPage(props: { path: string }) {
  return (
    <Card title="没有这一页">
      <div class="readings">
        路径 <span class="mono">{props.path}</span> 不在这一版的客户端路由里。
        服务端把未知路径回退成同一支外壳（`draft/73` §1.3 的 Q1 口径）—— 所以这一格说的是
        "这一页不存在"，不是"还在加载"。
      </div>
      <div class="readings">
        常被猜错的几处：合规 / 收工门那一块在 <a href="/acceptance">验收</a>（B 块）；
        板项（任务板）在 <a href="/live">/live</a> 页的名册卡与 <a href="/artifacts">/artifacts</a>
        页的任务台账里 —— 这一版没有单独的 /board 路由。
      </div>
    </Card>
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
        换 key 的提醒：挂在全站最上面 —— 它说的是"整个工作区的提示词
        缓存作废了"，与在哪一页无关。可关掉；换 key 之后它会自己再出现一次
        （`reminder.dismiss_key` 带 key 指纹）。
      */}
      <CacheBanner />
      <ConnectionBanner />
      {where.route === "/" && where.path !== "/" ? (
        <UnknownPage path={where.path} />
      ) : (
        renderPage(where.route, where.sid)
      )}
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
