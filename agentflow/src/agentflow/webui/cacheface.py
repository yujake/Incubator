# -*- coding: utf-8 -*-
"""两档提示词缓存的网页面：一条只读端点加一条写端点（按钮走的就是它）。

## 两条端点

| 端点 | 作用 | 闸门 |
|---|---|---|
| `GET /api/cache` | 两档 × 四格的状态读数 + 当前使用哪一档（`active`）+ 换 key 那条提醒 | 只读（与其它读数面同一档） |
| `POST /api/cache/warm` | 真预热一档（花钱），`dry_run=1` 只给计划 | `writes.authorize`（回环来源 → CSRF → `--allow-writes`）＋ `confirm=1` |

两条都只做转发：读的那一条把 `cachectl.status()` 原样吐给页面，写的那一条把
`cachectl.warm()` 起在 detached 子进程里（或在 `dry_run=1` 时同步算一份计划）——
于是"网页上看到的读数"与"命令行看到的读数"是同一份实现，不存在两套口径。
`active` 那一格（"这一趟会用哪一档"）不在这里算：它是 `cachectl.active_reading()` 的
产出，与 `cache status` 印的那一行是同一个函数。它按三层来源定，每一层都自报
（`active.source`）：这个工作区正在跑（或最近一趟）的运行记录（`run`）> 本进程开关
（`process`）> 读不出来（`unknown`）。工作区不从这里传：`cachectl` 自己从进程命令行
的 `--root`（起本服务的那个旗标）取 —— 于是网页进程读得到"正在跑的那一趟"的开关，
而不是它自己的。这一格此前在多进程下说反的那次误读，修的就是这一层。

## 为什么真预热要 detached

一趟预热要发十二次请求（另有命中样本两次），几十秒到几分钟；跟着 HTTP 请求同步跑
会把"用户切走标签页"变成"预热中途被杀"，而那时读数文件里可能已经写了半趟。
所以真预热与 `POST /api/run` 同一个形状：起 detached 子进程 + 日志落
`<工作区>/runs/web-cache-warm-<时间>.log`，回执里给 `pid` 与日志路径。
`dry_run=1` 不发请求也不起进程（同步算完就回），所以"试算"这一档是零花费的。

## 请求字段与白名单

只有三个字段：`lean`（`on` / `off`，缺省 `off`；`both` 只给命令行，网页上一档一个按钮）、
`confirm`（硬要求）、`dry_run`（可选）。刻意没有 `targets` 字段：能预热的对象恒等于
`warm_prompt_cache.WARM_TARGETS`，请求方不能点名别的目标 —— 这是"目标白名单"，
不是"参数校验"。

## 三态与状态码

与写面其它端点逐条同形（`writes._finish` 统一回执 + 审计台账）：

| 情形 | 码 | `WriteResult.tri` |
|---|---|---|
| 起好了（或试算完了） | 200 | `computed` |
| 未开写面 / CSRF 不对 / 非回环 | 403 | `not_applicable` |
| 缺 `confirm=1` / `lean` 不在白名单 | 400 | `not_applicable` |
| 起不来（子进程抛异常） | 500 | `unreadable` |
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = ["HANDLERS", "ROUTES", "handle_cache_status", "handle_cache_warm"]

#: 本模块挂到总路由表上的两条端点。总表由 `webui/routes.py` 拼出来（自有 +
#: `readers.ROUTES` + `writes.ROUTES`），而 `writes.ROUTES` 是本模块的入口 ——
#: 所以加这两条不需要碰 A 线的 `server.py`，也不需要动 `routes.py` 的拼接公式。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/cache", "handle_cache_status"),
    ("POST", "/api/cache/warm", "handle_cache_warm"),
)

#: 处理器表（键 = 上面第三元素）。`server._invoke` 先找 `WebHandler` 的方法、
#: 再找子表模块的这张表（`routes.handler_for`）。
HANDLERS: dict[str, Any] = {}

#: 这一档允许从网页起预热的形式化开关取值（`both` 故意不在里面：一个按钮一档）。
WARM_LEANS: tuple[str, ...] = ("on", "off")

#: `dry_run` 时同步算计划的调用（判据打桩它来证明"零调用零花费"）。
def _plan(**kw: Any) -> dict[str, Any]:
    """转发到 `cachectl.warm(dry_run=True)`（单独一层，判据可以打桩）。"""
    from .. import cachectl as C

    code, doc = C.warm(dry_run=True, **kw)
    return {"code": int(code), "doc": doc}


def _status() -> dict[str, Any]:
    """转发到 `cachectl.status()`（单独一层，判据可以打桩）。"""
    from .. import cachectl as C

    return C.status()


def handle_cache_status(handler: Any, params: Mapping[str, str],
                        query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/cache`：两档的四格读数 + 换 key 那条提醒（只读、零花费）。

    读不出来不许折成 200：那会把"没查成"画成"缓存好好的"。所以异常一律 500 +
    `tri="unreadable"` + 原话，页面据此画三态。
    """
    del params, query
    try:
        doc = _status()
    except Exception as exc:  # noqa: BLE001 - 失败不许折成 200
        handler._json(500, {"ok": False, "tri": "unreadable",
                           "reason": f"缓存状态没读出来：{type(exc).__name__}: {exc}"})
        return
    handler._json(200, doc)


def _warm_argv(root: Path, lean: str) -> list[str]:
    """网页按钮起来的那条命令（判据拿它比对；`dry_run` 那条路不经过它）。

    与 `writes._run_argv` 同一个形状：先 `--root`（全局开关必须在子命令之前），
    再 `cache warm --lean <档>`。刻意不带 `--readings`：真预热的落点是仓库里那一份
    读数文件（与命令行缺省同一个），换落点不是按钮该干的事。
    """
    return [sys_executable(), "-B", "-m", "agentflow", "--root", str(root),
            "cache", "warm", "--lean", str(lean)]


def sys_executable() -> str:
    """当前解释器（单独一层：判据要能替换它而不去 import sys 的副本）。"""
    import sys

    return sys.executable


def _spawn_warm(root: Path, lean: str) -> tuple[int, str]:
    """detached 起一趟预热，stdout/stderr 追加进 `runs/web-cache-warm-*.log`。"""
    import os
    import subprocess
    from datetime import datetime

    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    log = runs / f"web-cache-warm-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    handle = open(log, "ab")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(_warm_argv(root, lean), cwd=str(root), env=env,
                            stdout=handle, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags,
                            close_fds=True)
    return int(proc.pid), str(log.relative_to(root)).replace("\\", "/")


def handle_cache_warm(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/cache/warm`：真预热一档（花钱），`dry_run=1` 只给计划。

    三态与状态码见模块 docstring。确认是硬要求（`confirm=1`）：这一下会真的花钱，
    与叫停 / 改预算同一档（`draft/75` §1.1 第 8 行）。
    """
    del params, query
    from . import writes as WR

    form = handler._form()
    root = Path(handler.root)
    source, _why = WR._source_of(handler)  # noqa: SLF001 - 写面的审计栏与它同一份实现
    lean = (WR._one(form, "lean").strip().lower() or "off")  # noqa: SLF001
    dry = WR._flag(form, "dry_run")  # noqa: SLF001
    seen = {"lean": lean, "dry_run": dry, "confirm": WR._flag(form, "confirm")}  # noqa: SLF001
    allowed, code, why = WR.authorize(handler, endpoint="POST /api/cache/warm")
    if not allowed:
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=code, result=f"拒绝：{why}", ok=False)
    if lean not in WARM_LEANS:
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=400, result=(f"拒绝：lean 只认 {list(WARM_LEANS)}（收到 {lean!r}）"
                                            "—— 能预热的目标恒等于 WARM_TARGETS，请求方点不了别的"),
                          ok=False)
    if not WR._flag(form, "confirm"):  # noqa: SLF001
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=400,
                          result=("拒绝：真预热会真的花钱，必须带 confirm=1 一次显式确认"
                                  "（按钮上的二次确认就是它）"), ok=False)
    argv = _warm_argv(root, lean)
    if dry:
        try:
            got = _plan(tiers=(lean,))
        except Exception as exc:  # noqa: BLE001 - 计划算不出来属于"没查成"
            return WR._finish(handler, endpoint="/api/cache/warm", source=source,  # noqa: SLF001
                              params=seen, code=500,
                              result=f"试算失败：{type(exc).__name__}: {exc}", ok=False,
                              extra={"argv": argv})
        doc = got.get("doc") or {}
        tier = doc.get("tiers", {}).get(lean) if isinstance(doc.get("tiers"), dict) else None
        tier = tier or {}
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=200,
                          result=(f"试算（没有发请求、花费 0 美元）：要预热 "
                                  f"{len(tier.get('to_warm') or [])} 个目标，预计 "
                                  f"{float(tier.get('usd_est') or 0.0):.6f} 美元"),
                          ok=True, extra={"dry_run": True, "plan": doc, "argv": argv})
    try:
        pid, log = _spawn_warm(root, lean)
    except Exception as exc:  # noqa: BLE001 - 起不来要如实报，不许静默
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=500, result=f"起不来：{type(exc).__name__}: {exc}", ok=False,
                          extra={"argv": argv})
    return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                      code=200,
                      result=(f"已起一趟预热（{lean} 档，pid={pid}）—— 跑完刷新本页看读数；"
                              f"日志 {log}"),
                      ok=True, ident=log, extra={"pid": pid, "log": log, "argv": argv})


HANDLERS.update({
    "handle_cache_status": handle_cache_status,
    "handle_cache_warm": handle_cache_warm,
})
