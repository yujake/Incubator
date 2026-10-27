# -*- coding: utf-8 -*-
"""两档提示词缓存的网页面：一条只读端点加一条写端点（按钮走的就是它）。

## 两条端点

| 端点 | 作用 | 闸门 |
|---|---|---|
| `GET /api/cache` | 两档 × 四格的状态读数 + 当前使用哪一档（`active`）+ 换 key 那条提醒 + 写权限读数（`writes_allowed` / `writes_reason`）+ 最近一趟网页预热的三态（`warm`） | 只读（与其它读数面同一档） |
| `POST /api/cache/warm` | 真预热一档（花钱），`dry_run=1` 只给计划 | 真跑：`writes.authorize`（回环来源 → CSRF → `--allow-writes`）＋ `confirm=1`；试算：只保留回环来源那一层 ＋ `confirm=1` |

两条都只做转发：读的那一条把 `cachectl.status()` 原样吐给页面，写的那一条把
`cachectl.warm()` 起在 detached 子进程里（或在 `dry_run=1` 时同步算一份计划）——
于是"网页上看到的读数"与"命令行看到的读数"是同一份实现，不存在两套口径。
`active` 那一格（"这一趟会用哪一档"）不在这里算：它是 `cachectl.active_reading()` 的
产出，与 `cache status` 印的那一行是同一个函数。它按三层来源定，每一层都自报
（`active.source`）：这个工作区正在跑（或最近一趟）的运行记录（`run`）> 本进程开关
（`process`）> 读不出来（`unknown`）。工作区不从这里传：`cachectl` 自己从进程命令行
的 `--root`（起本服务的那个旗标）取 —— 于是网页进程读得到"正在跑的那一趟"的开关，
而不是它自己的。这一格此前在多进程下说反的那次误读，修的就是这一层。

## 写权限读数与试算放行（D-60 ① ②）

`writes_allowed` 说的是"本服务启动时带没带 `--allow-writes`"，判定口径只有一处
（`writes.writes_allowed`）—— 页面上说"不能写"、闸门说"放行"那种自相矛盾比没有
这一格更坏。没有开时 `writes_reason` 逐字给出重启提示，页面据此禁用真预热按钮
并把那一句写在按钮旁：不许让人按出 403 才知道自己没权限。

`dry_run=1` 走 `writes.authorize(read_only=True)`：它不写盘、不花钱、不起进程，
同步算完就回，所以不要求写权限，也不要求 CSRF 令牌（跨站浏览器请求由第一层
"回环来源"挡掉；本地进程本来就与网页同权，加令牌只会让"先看计划再决定"这一步
多一个找不到的门槛）。真跑那一档一层都不许少 —— 负控见
`tests/test_cache_warm_button_is_honest.py` 的 c 条。

## 三态跟踪（D-60 ③）

真预热与 `POST /api/run` 同一个形状：detached 子进程 + 日志落
`<工作区>/runs/web-cache-warm-<时间>.log`，回执里给 `pid` 与日志路径。
区别在"起完之后"：起的那一刻把这一趟记进 `<工作区>/runs/web-cache-warm.json`
（pid / 日志 / 档位），之后每一份 `GET /api/cache` 都按这份记录 + 日志尾 + 探活
现算三态（`state` ∈ `running` / `done` / `failed` / `unknown`，外加 `reason`、
`log` 与 `last_line`）：

| 判据 | `state` |
|---|---|
| 日志尾有 `[warmed]` 那一行 | `done` |
| 日志尾有 `[incomplete]` / `[unknown]` / `[failed]` / `[error]` 或 Traceback | `failed`（`last_line` 就是给按按钮的人看的那一行） |
| 都没有、进程还活着 | `running` |
| 都没有、进程已不在（或日志读不出来、或没有记录） | `unknown` ＋ 理由 |

三态由读侧现算而不是回执自报：页面刷新、换个人打开、过一小时再看，读到的都是
同一趟的真实结局；而"起好了"那一刻的 `running` 只是一个起点。
`dry_run=1` 不落这份记录（它没有跑起来的东西可跟踪）。

## 为什么真预热要 detached

一趟预热要发十二次请求（另有命中样本两次），几十秒到几分钟；跟着 HTTP 请求同步跑
会把"用户切走标签页"变成"预热中途被杀"，而那时读数文件里可能已经写了半趟。
所以真预热是 detached 子进程 + 日志；`dry_run=1` 不发请求也不起进程（同步算完就回），
所以"试算"这一档是零花费的。

## 请求字段与白名单

只有三个字段：`lean`（`on` / `off`，缺省 `off`；`both` 只给命令行，网页上一档一个按钮）、
`confirm`（硬要求）、`dry_run`（可选）。刻意没有 `targets` 字段：能预热的对象恒等于
`warm_prompt_cache.WARM_TARGETS`，请求方不能点名别的目标 —— 这是"目标白名单"，
不是"参数校验"。

## 三态与状态码

与写面其它端点逐条同形（`writes._finish` 统一回执 + 审计台账）：

| 情形 | 码 | `WriteResult.tri` | `WriteResult.state` |
|---|---|---|---|
| 起好了 | 200 | `computed` | `running` |
| 试算完了 | 200 | `computed` | `plan` |
| 真跑但未开写面 / CSRF 不对 / 非回环 | 403 | `not_applicable` | （不带） |
| 缺 `confirm=1` / `lean` 不在白名单 | 400 | `not_applicable` | （不带） |
| 起不来（子进程抛异常） | 500 | `unreadable` | （不带） |

`state` 与 `tri` 分处两根轴：`tri` 说"这次请求成没成"，`state` 说"被起的那件事
到哪一步了"。所以 200 的两种结局靠 `state` 分开，而不是靠 `reason` 的措辞。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..canonical import json_default

__all__ = ["HANDLERS", "ROUTES", "WARM_JOB_FILE",
           "WARM_JOB_STATES", "WARM_LEANS", "handle_cache_status", "handle_cache_warm",
           "warm_job", "writes_allowed"]

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

#: 这一趟预热的三态词表（加 `unknown` 那一档）。页面按它画"跑中 / 成 / 败 / 不知道"；
#: 词表住在这里而不是前端：三态由读侧判，页面只负责画。
WARM_JOB_STATES: tuple[str, ...] = ("running", "done", "failed", "unknown")

#: 预热记录的文件名（落在 `<工作区>/runs/` 下，与日志同目录）。
WARM_JOB_FILE = "web-cache-warm.json"

#: 日志里能判定"这一趟跑完了"的收尾标记（`cachectl.cmd_warm` 印的那几种）。
_WARM_DONE_MARKS: tuple[str, ...] = ("[warmed]",)

#: 日志里能判定"这一趟没成"的收尾标记（含预热脚本自己的异常收尾）。
_WARM_FAIL_MARKS: tuple[str, ...] = ("[incomplete]", "[unknown]", "[failed]", "[error]",
                                     "Traceback (most recent call last)")

#: 读日志尾的上限（预热一趟只印十几行；截断只为防一份失控的日志把页面拖死）。
_WARM_TAIL_BYTES = 16384

#: 回执里"这一趟跑到哪一步"的两档（与 `WARM_JOB_STATES` 不是同一套：`plan` 不是一个
#: 跑起来的任务，它说的是"这只是计划"）。
WARM_STATE_PLAN = "plan"
WARM_STATE_RUNNING = "running"


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


def sys_executable() -> str:
    """当前解释器（单独一层：判据要能替换它而不去 import sys 的副本）。"""
    import sys

    return sys.executable


def _warm_argv(root: Path, lean: str) -> list[str]:
    """网页按钮起来的那条命令（判据拿它比对；`dry_run` 那条路不经过它）。

    与 `writes._run_argv` 同一个形状：先 `--root`（全局开关必须在子命令之前），
    再 `cache warm --lean <档>`。刻意不带 `--readings`：真预热的落点是仓库里那一份
    读数文件（与命令行缺省同一个），换落点不是按钮该干的事。
    """
    return [sys_executable(), "-B", "-m", "agentflow", "--root", str(root),
            "cache", "warm", "--lean", str(lean)]


def _spawn_warm(root: Path, lean: str) -> tuple[int, str]:
    """detached 起一趟预热，stdout/stderr 追加进 `runs/web-cache-warm-*.log`。

    起进程那五件事住在 `writes._spawn_detached` 里（2026-10-27 业主裁定 W3：
    "起一趟"与"起一趟预热"此前各写了一遍同一套），这里只保留这一面自己的两格：
    日志前缀 `web-cache-warm`（预热记录的 `log` 与读侧都按它认）与要跑的那条命令。
    """
    from . import writes as WR

    return WR._spawn_detached(root, _warm_argv(root, lean), "web-cache-warm")


# ====================================================================== 写权限读数
def _writes_allowed(handler: Any) -> bool:
    """本服务有没有开写权限（判据打桩它来证明这一格不是恒值）。

    真身在 `writes.writes_allowed`：读侧与闸门必须取同一个事实。
    """
    from . import writes as WR

    return WR.writes_allowed(handler)


def _writes_reason(allowed: bool) -> str:
    """没开写权限时页面上那一句（逐字，真身在 `writes.WRITES_OFF_REASON`）。"""
    from . import writes as WR

    return "" if allowed else WR.WRITES_OFF_REASON


# ====================================================================== 三态跟踪
def _now_iso() -> str:
    """记录里那一格时间（UTC，秒级；与 `cachectl` 的读数同一格式）。"""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _record_path(root: Path) -> Path:
    """预热记录的落点（与日志同目录：`<工作区>/runs/`）。"""
    return Path(root) / "runs" / WARM_JOB_FILE


def _write_record(root: Path, payload: Mapping[str, Any]) -> tuple[bool, str]:
    """原子落一份记录；返回 `(写成没写成, 问题)`。写不成不抛（回执里照实说）。"""
    path = _record_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2,
                                  default=json_default) + "\n",
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _read_record(root: Path) -> tuple[dict[str, Any] | None, str]:
    """读那份记录；没有记录返回 `(None, "")`，读不懂返回 `(None, 问题)`。"""
    path = _record_path(root)
    if not path.is_file():
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "预热记录不是 JSON 对象"
    return data, ""


def _pid_alive(pid: int) -> bool:
    """这个 pid 还活着吗（探活只有一份真身：`stopctl.alive`，Windows 上也安全）。"""
    try:
        from .. import stopctl as SC

        return bool(SC.alive(int(pid or 0)))
    except Exception:  # noqa: BLE001 - 探不了就当"不活着"（最多把跑中读成 unknown）
        return False


def _log_tail(root: Path, log: str) -> tuple[list[str] | None, str]:
    """日志尾（非空行）；读不出来返回 `(None, 理由)`。

    只读最后 `_WARM_TAIL_BYTES` 字节：一趟预热只印十几行，而日志可能被别的东西追加过。
    """
    rel = str(log or "").strip()
    if rel == "":
        return None, "记录里没有日志路径"
    path = Path(root) / rel
    if not path.is_file():
        return None, f"日志不在盘上（{rel}）—— 这一趟的结局无从判定"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _WARM_TAIL_BYTES), os.SEEK_SET)
            raw = handle.read()
    except OSError as exc:
        return None, f"日志读不出来（{rel}）：{type(exc).__name__}: {exc}"
    text = raw.decode("utf-8", errors="replace")
    return [line.rstrip("\r") for line in text.splitlines() if line.strip()], ""


def _is_failure_line(line: str) -> bool:
    """这一行是"没成"的收尾标记吗（含 Traceback 那一行）。"""
    return any(line.startswith(mark) or mark in line for mark in _WARM_FAIL_MARKS)


def _decide_warm_state(record: Mapping[str, Any],
                       root: Path) -> dict[str, Any]:
    """按记录 + 日志尾 + 探活判这一趟的三态（判据打桩它来证明三态不是恒值）。

    顺序是要紧的：先认日志里的收尾标记（跑完的结局是写死的），再探活。反过来的话，
    一个刚跑完、pid 恰好被复用的进程会把它读回"跑中"，而"成 / 败"就永远读不出来。
    """
    tail, problem = _log_tail(root, str(record.get("log") or ""))
    pid = int(record.get("pid") or 0)
    if tail is None:
        return {"state": "unknown", "reason": problem, "last_line": "", "tail": []}
    # 日志在盘上、但一行非空内容都还没有：刚起的那一趟就是这样（父进程先 open 出文件，
    # 子进程还没写第一行）。这不是"读不出来"，所以不许走下面的收尾标记比对，
    # 更不许取 `tail[-1]`（空表上取下标会抛 IndexError，被 warm_job 接住后
    # 这一格会从"跑中"变成"不知道"，与实际状态正好相反）。
    last_line = tail[-1] if tail else ""
    for line in reversed(tail):
        if _is_failure_line(line):
            return {"state": "failed", "reason": f"这一趟没成：{line}",
                    "last_line": last_line, "tail": tail[-3:]}
        if any(line.startswith(mark) for mark in _WARM_DONE_MARKS):
            return {"state": "done", "reason": f"这一趟跑完了：{line}",
                    "last_line": last_line, "tail": tail[-3:]}
    if _pid_alive(pid):
        return {"state": "running", "reason": f"子进程还在跑（pid={pid}）；日志 {record.get('log')}",
                "last_line": last_line, "tail": tail[-3:]}
    return {"state": "unknown",
            "reason": (f"子进程（pid={pid}）已经结束，但日志里没有收尾标记"
                       f"（最后一行：{last_line}）"),
            "last_line": last_line, "tail": tail[-3:]}


def warm_job(root: Path | str) -> dict[str, Any]:
    """最近一趟网页预热的三态读数（`GET /api/cache` 的 `warm` 那一格）。

    没有起过就返回 `recorded=False` + `state="unknown"` + 理由：那一档说的是"还没从
    网页起过预热"（不是"失败了"，也不是空）。记录读不懂、日志读不出来同样是
    `unknown` 并带上原话 —— 三态纪律：把"没查成"折成"成"或"败"都是编结局。

    这一格现算不落盘：日志是追加写的，跑完之后它不再变，所以现算的结果是稳定的；
    而"现算"保证了页面刷新、换个人打开、过一小时再看都是同一趟的真实结局。
    """
    root = Path(root)
    out: dict[str, Any] = {"recorded": False, "state": "unknown", "reason": "",
                           "log": "", "log_path": "", "pid": 0, "tier": "", "at": "",
                           "last_line": "", "tail": []}
    try:
        record, problem = _read_record(root)
    except Exception as exc:  # noqa: BLE001 - 读侧不许把 /api/cache 打成 500
        out["reason"] = f"预热记录没读出来：{type(exc).__name__}: {exc}"
        return out
    if record is None:
        out["reason"] = (f"还没有从网页起过预热（记录不在：{WARM_JOB_FILE}）" if problem == ""
                         else f"预热记录读不出来：{problem}")
        return out
    out.update({"recorded": True,
                "log": str(record.get("log") or ""),
                "log_path": str((root / str(record.get("log") or "")).resolve()
                                if record.get("log") else ""),
                "pid": int(record.get("pid") or 0),
                "tier": str(record.get("tier") or record.get("lean") or ""),
                "at": str(record.get("at") or "")})
    try:
        decided = _decide_warm_state(record, root)
    except Exception as exc:  # noqa: BLE001 - 同上：读侧的三态只有 unknown 这一档兜底
        out.update({"state": "unknown",
                    "reason": f"这一趟的结局没判定出来：{type(exc).__name__}: {exc}"})
        return out
    out.update({key: decided.get(key) for key in ("state", "reason", "last_line", "tail")})
    return out


# ====================================================================== 端点
def handle_cache_status(handler: Any, params: Mapping[str, str],
                        query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/cache`：两档的四格读数 + 写权限读数 + 最近一趟预热的三态（零花费）。

    读不出来不许折成 200：那会把"没查成"画成"缓存好好的"。所以异常一律 500 +
    `tri="unreadable"` + 原话，页面据此画三态。

    三格是追加的（既有键名一个都不改，D-60 ① 的边界）：`writes_allowed` /
    `writes_reason` / `warm`。为什么要在这里带出来而不是另开一条端点：页面已经在读
    这一条，写按钮又只属于这一面 —— 多一条端点只会多一处"页面忘了读"的机会。
    """
    del params, query
    root = Path(handler.root)
    try:
        doc = _status()
    except Exception as exc:  # noqa: BLE001 - 失败不许折成 200
        handler._json(500, {"ok": False, "tri": "unreadable",
                           "reason": f"缓存状态没读出来：{type(exc).__name__}: {exc}"})
        return
    allowed = _writes_allowed(handler)
    if isinstance(doc, dict):
        out: Any = dict(doc)
        out["writes_allowed"] = allowed
        out["writes_reason"] = _writes_reason(allowed)
        out["warm"] = warm_job(root)
    else:
        out = doc
    handler._json(200, out)


def handle_cache_warm(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/cache/warm`：真预热一档（花钱），`dry_run=1` 只给计划。

    三态与状态码见模块 docstring。确认（`confirm=1`）是硬要求，两档都要：试算虽然
    不花钱，但它是"再决定要不要真跑"的那一步，与真跑走同一个按钮面（`draft/75`
    §1.1 第 8 行）。
    """
    del params, query
    from . import writes as WR

    form = handler._form()
    root = Path(handler.root)
    source, _why = WR._source_of(handler)  # noqa: SLF001 - 写面的审计栏与它同一份实现
    lean = (WR._one(form, "lean").strip().lower() or "off")  # noqa: SLF001
    dry = WR._flag(form, "dry_run")  # noqa: SLF001
    seen = {"lean": lean, "dry_run": dry, "confirm": WR._flag(form, "confirm")}  # noqa: SLF001
    # D-60 ②：试算走只读放行（只保留回环来源那一道）；真跑仍然四层全要。
    allowed, code, why = WR.authorize(handler, endpoint="POST /api/cache/warm",
                                      read_only=dry)
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
                          ok=True, state=WARM_STATE_PLAN,
                          extra={"dry_run": True, "plan": doc, "argv": argv})
    try:
        pid, log = _spawn_warm(root, lean)
    except Exception as exc:  # noqa: BLE001 - 起不来要如实报，不许静默
        return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                          code=500, result=f"起不来：{type(exc).__name__}: {exc}", ok=False,
                          extra={"argv": argv})
    extra: dict[str, Any] = {"pid": pid, "log": log, "argv": argv, "tier": lean}
    written, problem = _write_record(root, {"schema": 1, "kind": "cache_warm",
                                            "at": _now_iso(), "pid": pid, "log": log,
                                            "tier": lean})
    if not written:
        # 记录写不成不冒充失败（子进程真的起来了），但必须说出口：没有这份记录，
        # 页面那一格三态就只能说"不知道"。
        extra["record_problem"] = problem
    return WR._finish(handler, endpoint="/api/cache/warm", source=source, params=seen,  # noqa: SLF001
                      code=200,
                      result=(f"已起一趟预热（{lean} 档，pid={pid}）—— 页面会跟到跑完，"
                              f"跑完自动重取读数；日志 {log}"),
                      ok=True, ident=log, state=WARM_STATE_RUNNING, extra=extra)


HANDLERS.update({
    "handle_cache_status": handle_cache_status,
    "handle_cache_warm": handle_cache_warm,
})
