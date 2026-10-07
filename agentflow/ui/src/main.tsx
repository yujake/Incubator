/*
 * 挂载点与客户端路由。
 *
 * `ROUTES` 是 C4 契约的前端一侧（`draft/75 §1.4`）：`tests/test_webui_contracts.py`
 * 的 D 条把这里的路由字面量集合与那张表逐字比对，并要求每条路由用到的端点 ∈
 * 后端 ROUTES、用到的 SSE kind ∈ `sse.ts` 的 `KINDS`。
 *
 * W0 只有一个页面接真数据（Home → `/api/state`）；其余五页是诚实的空壳。
 * SSE 只在这里订阅一次（不逐页各开一条流）—— 那要等 W2 的后端广播器；
 * 现在不订阅，是因为"订阅一条后端的 404"只会让页面显红。
 */
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

import { Acceptance } from "./pages/Acceptance";
import { Artifacts } from "./pages/Artifacts";
import { Evidence } from "./pages/Evidence";
import { Home } from "./pages/Home";
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

function App() {
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

  switch (where.route) {
    case "/run/:sid":
      return <Run sid={where.sid} />;
    case "/evidence":
      return <Evidence />;
    case "/artifacts":
      return <Artifacts />;
    case "/acceptance":
      return <Acceptance />;
    case "/machine":
      return <Machine />;
    default:
      return <Home />;
  }
}

function mount(): void {
  const host = document.getElementById("app");
  if (host === null) {
    throw new Error("页面里没有 #app 挂载点（index.html 被改过？）");
  }
  const top = document.createElement("header");
  top.className = "top";
  const brand = document.createElement("div");
  brand.className = "brand";
  brand.textContent = "agentflow 用户端";
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = "状态一律从盘上派生（每次请求重新读，页面里不缓存）";
  top.appendChild(brand);
  top.appendChild(sub);

  const main = document.createElement("main");
  main.className = "wrap";
  document.body.insertBefore(top, host);
  document.body.insertBefore(main, host);
  main.appendChild(host);
  render(<App />, host);
}

mount();
