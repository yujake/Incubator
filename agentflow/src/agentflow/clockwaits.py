# -*- coding: utf-8 -*-
"""等待账（`out/clock/waits.json`）与两把普查：原始等待 / 起进程。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十一刀。
业主 2026-10-25：「让老的未依赖时钟的计时工具退场」。这件事不能靠一句声明，要有机器判据：
`raw_wait_census()` 用 AST 扫 `src/agentflow` 下全部模块，把 `time.sleep` / 阻塞原语
的每一处点名；`program_census()` 扫"起进程却没进程序计时器"的地方。两把普查各自
只报读数，缺口为 0 才算"所有计时类工作都在主时钟的账上"。

等待账与两把普查放在同一个模块，是因为它们共用同一份"扫描根"可变量：`set_census_roots`
同时重设 `_CENSUS_ROOTS` / `_CENSUS_CACHE` / `_PROGRAM_CENSUS_CACHE` —— 三个写点与
读点跨模块就会 split-brain（`from .mod import X` 是快照）。

## 为什么 `await_io` 反而留在 `clock.py`

`ALLOWED_RAW_WAITS` 是按"路径 + 函数名"认的：主时钟本体那一条写的是
`agentflow/clock.py::await_io`（真睡那一句 + 那个 `= time.sleep` 的绑定）。
`await_io` 就是这本账的写入口。把它搬进本模块只有两条路：要么改豁免表的路径，
要么让主时钟本体的判定跟着换文件 —— 两条都等于让判据跟实现一起漂。
所以它留在主时钟本体，本模块只放账与普查（它调 `note_wait` 记账，见 `clock.py`）。

## 装了什么

等待账：`waits_path` / `_LEDGER` / `_LEDGER_LOCK` / `_LEDGER_WRITTEN` / `_ledger_key` /
`note_wait` / `note_process_wait` / `waits` / `reset_waits` / `flush_waits`；
原始等待普查：`CENSUS_FORMS` / `ALLOWED_RAW_WAITS` / `GOVERNED_PRIMITIVE_WAITS` /
`EXEMPT_PRIMITIVE_WAITS` / `_CENSUS_ROOTS` / `_CENSUS_CACHE` / `set_census_roots` /
`_census_roots` / `_wait_form` / `_WaitVisitor` / `_iter_source_files` / `_exempt_for` /
`_primitive_governed` / `raw_wait_census`；起进程普查：`PROGRAM_SPAWN_CALLS` /
`PROGRAM_OS_SPAWNS` / `PROGRAM_ALLOWED_RAW` / `_iter_py_files` / `_SpawnVisitor` /
`_PROGRAM_CENSUS_CACHE` / `program_census`；以及 `coverage`（两把普查 + 等待账的合成读数）。

## 等价性

逐名 AST dump 全等，`clock.py` 原样再导出；`coverage` 的调用点（`clock.now` 工具）
与判据都不用改。
"""

from __future__ import annotations

from pathlib import Path
import ast
import threading
import time
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockParamError,
    SCHEMA,
    WAITS_REL,
    _iso,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _PROGRAM_UNBOOKED,
    _atomic_json,
    current,
    now,
)

#: `program_census` 的缓存（按扫描根做键；`refresh=True` 强制重扫）。
#:
#: 为什么要缓存：`coverage()` 的 `programs_outside_clock` 那一格读它，而 `coverage()`
#: 又被 `clock.now` 每个回合读一次 —— 没有缓存就是每个回合把整棵 `src` AST 一遍。
_PROGRAM_CENSUS_CACHE: dict[str, Any] | None = None


#: "起了进程"的调用名（`program_census()` 认这一张表）。
#:
#: 只认 `subprocess.<这些>` 与 `os.spawn*` / `os.system` / `os.popen` 这两族；
#: 光看末段名字会把 `prov.call(...)`、`self.run(...)` 这些普通调用一起算进来
#: （实测：按末段名字认会报出 130 多处假的"起进程"）。
PROGRAM_SPAWN_CALLS: tuple[str, ...] = ("Popen", "run", "call", "check_call",
                                        "check_output", "getoutput", "getstatusoutput")

#: `os` 那一族里算"起进程"的名字。
PROGRAM_OS_SPAWNS: tuple[str, ...] = ("spawnv", "spawnl", "spawnve", "spawnle",
                                      "system", "popen", "startfile")


#: 允许不进程序计时器登记的起进程点，逐条登记（与 `ALLOWED_RAW_WAITS` 同一档纪律）。
#:
#: 每条必须写 `why`（为什么它不该进账）与 `blocked_by`（谁挡着没改）。
#: 空 `blocked_by` = 这一处本来就不该进账（"它起的东西不是我们在等的那个程序"）。
PROGRAM_ALLOWED_RAW: tuple[dict[str, str], ...] = (
    # 2026-10-27：这一条此前是两条（`webui/cacheface.py::_spawn_warm` 与
    # `webui/writes.py::_spawn_run`），两条的 `blocked_by` 都写着"webui/* 本轮禁改"。
    # 那一刻的边界已经撤了，而两个起进程点也按裁定 W3 收成了一个 `_spawn_detached`
    # —— 于是登记点跟着走：一处函数、一条登记（留着旧的两条会变成"永不生效的豁免"，
    # 那种表会腐烂成"看起来还在挡着什么"）。为什么仍然不进程序计时器：脱手进程
    # 起完立刻返回 pid 与日志路径，没有人等它；`with program_span(...)` 会在出作用域
    # 时收口成"程序已结束"——那是一条假读数（它还在跑）。真正在等的那一趟循环
    # 自己在时钟账上推时间。
    {"path": "agentflow/webui/writes.py", "func": "_spawn_detached",
     "why": ("网页端的两个脱手起进程点（「用一句话起一趟工作流」与「预热提示词缓存」）"
             "收在这一处：起完立刻返回 pid 与日志路径，没有人等它 —— 它不属于"
             "「起一个程序并等它」；真正在等的那一趟循环自己记时钟"),
     "blocked_by": ""},
    {"path": "agentflow/jobobject.py", "func": "selftest",
     "why": "作业对象那条路的自检（起一个睡的进程验证 job 句柄能把树收掉），不是生产路径",
     "blocked_by": ""},
)


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


class _SpawnVisitor(ast.NodeVisitor):
    """走一遍 AST，把"起进程"的调用点连它所在的函数一起记下来。"""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[dict[str, Any]] = []
        self.spans: list[str] = []

    def _enter(self, name: str) -> None:
        self.stack.append(str(name or "<anonymous>"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    @staticmethod
    def _dotted(node: ast.AST) -> str:
        """把 `a.b.c` 这种属性链还原成字符串（不是属性链 => 空串）。"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            head = _SpawnVisitor._dotted(node.value)
            return f"{head}.{node.attr}" if head else node.attr
        return ""

    @staticmethod
    def _spawn_of(node: ast.Call) -> str:
        """这个调用是不是"起进程"；是的话返回它的名字（`subprocess.run` 这种）。"""
        func = node.func
        if not isinstance(func, ast.Attribute):
            return ""
        owner = _SpawnVisitor._dotted(func.value)
        tail = owner.rsplit(".", 1)[-1] if owner else ""
        if tail == "subprocess" and func.attr in PROGRAM_SPAWN_CALLS:
            return func.attr
        if tail == "os" and func.attr in PROGRAM_OS_SPAWNS:
            return func.attr
        return ""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        func_name = "/".join(self.stack) or "<module>"
        spawn = self._spawn_of(node)
        if spawn:
            self.hits.append({"line": int(getattr(node, "lineno", 0) or 0),
                              "func": func_name, "call": spawn})
        else:
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if name == "program_span":
                self.spans.append(func_name)
        self.generic_visit(node)


def program_census(*, source_root: str | Path | Iterable[str | Path] | None = None,
                   refresh: bool = False) -> dict[str, Any]:
    """普查"起进程却没进程序计时器"的地方。返回 `{checked, findings, spans, files, reason}`。

    判据口径：一个起进程的调用点只要与某个 `program_span(...)` 落在同一个函数里，
    就算被管住了（`with` 把它包起来是调用方的事，这里是"这个函数里确实开了账"）。

    为什么用 AST 而不是正则：`program_span` 这几个字会出现在注释与 docstring 里
    （本文件就写着），正则会把说明文字算成"管住了"。

    ## 为什么要一份缓存（2026-10-27 补线时加的）

    它现在被 `coverage()` 调（`clock.coverage` 的 `programs_outside_clock` 那一格），
    而 `coverage()` 又被 `clock.now` 每个回合读一次 —— 没有缓存的话，一次 `clock.now`
    会把整棵 `src/agentflow` 重新 AST 一遍（实测 130 多个文件）。缓存与
    `raw_wait_census` 的 `_CENSUS_CACHE` 同一档：按扫描根做键、`refresh=True` 强制重扫。
    """
    global _PROGRAM_CENSUS_CACHE
    roots: list[Path]
    if source_root is None:
        roots = _census_roots()
    elif isinstance(source_root, (str, Path)):
        roots = [Path(source_root).resolve()]
    else:
        roots = [Path(r).resolve() for r in source_root]
    cache_key = "｜".join(str(r) for r in roots)
    if _PROGRAM_CENSUS_CACHE is not None and _PROGRAM_CENSUS_CACHE.get("key") == cache_key \
            and not refresh:
        return dict(_PROGRAM_CENSUS_CACHE["value"])
    findings: list[dict[str, Any]] = []
    governed: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    files = 0
    reasons: list[str] = []
    for root in roots:
        if not root.is_dir():
            reasons.append(f"扫描根不是目录：{root}")
            continue
        for path in _iter_py_files(root):
            files += 1
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception as exc:  # noqa: BLE001 - 读不成要说，不许当"没问题"
                reasons.append(f"{rel} 读不成：{type(exc).__name__}: {exc}")
                continue
            visitor = _SpawnVisitor()
            visitor.visit(tree)
            spanned = set(visitor.spans)
            for hit in visitor.hits:
                func = hit["func"]
                row = {"path": rel, "line": hit["line"], "func": func,
                       "call": hit["call"], "where": f"{rel}:{hit['line']}（{func}）"}
                if func in spanned:
                    governed.append(row)
                    continue
                allowed = next((r for r in PROGRAM_ALLOWED_RAW
                                if r["path"] == rel
                                and (r["func"] == func
                                     or func.endswith("/" + r["func"]))), None)
                if allowed is not None:
                    governed.append({**row, "why": allowed.get("why", ""),
                                     "blocked_by": allowed.get("blocked_by", "")})
                    continue
                findings.append(row)
            for func in sorted(spanned):
                spans.append({"path": rel, "func": func})
    findings.sort(key=lambda r: (r["path"], r["line"]))
    value = {"checked": not reasons, "files": files, "roots": [str(r) for r in roots],
             "findings": findings, "governed": governed, "spans": spans,
             "unbooked": list(_PROGRAM_UNBOOKED), "reason": "；".join(reasons)}
    _PROGRAM_CENSUS_CACHE = {"key": cache_key, "value": value}
    return dict(value)


def waits_path(workspace: str | Path) -> Path:
    """等待账的落盘路径（`<工作区>/out/clock/waits.json`）。"""
    return Path(workspace).resolve() / WAITS_REL


#: 进程内的等待账：`(kind, where, purpose, waited_for)` -> 一行聚合。
_LEDGER: dict[str, dict[str, Any]] = {}

_LEDGER_LOCK = threading.Lock()

_LEDGER_WRITTEN = 0


def _ledger_key(kind: str, where: str, purpose: str, waited_for: str) -> str:
    return "｜".join((str(kind or "io"), str(where or ""), str(purpose or ""),
                      str(waited_for or "")))


def note_wait(seconds: float, purpose: str, *, kind: str = "io", where: str = "",
              waited_for: str = "", slept: float | None = None,
              skipped: bool = False) -> dict[str, Any]:
    """记一条等待（不睡）。返回这一行聚合后的读数。

    `purpose` 在这里是必填的：调用点是框架自己的代码，写不出一句目的说明这个等待
    根本不该存在；缺了直接抛（与代理面"忘填目的不报错"刻意不同 —— 那边是人/
    模型的疏漏，这边是我们自己的账）。
    """
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "框架内部的等待必须写目的（purpose）：写不出目的的等待不许存在")
    try:
        asked = float(seconds)
    except (TypeError, ValueError):
        raise ClockParamError(f"等待时长必须是数，收到 {seconds!r}") from None
    if asked < 0:
        raise ClockParamError(f"等待时长不能是负数，收到 {seconds!r}")
    took = asked if slept is None else float(slept)
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    key = _ledger_key(kind, where, body, waited_for)
    global _LEDGER_WRITTEN
    with _LEDGER_LOCK:
        row = _LEDGER.get(key)
        if row is None:
            row = {"kind": str(kind or "io"), "where": str(where or ""),
                   "purpose": body, "waited_for": str(waited_for or ""),
                   "calls": 0, "asked_sec": 0.0, "slept_sec": 0.0,
                   "first_at": stamp, "last_at": stamp,
                   "skipped": 0}
            _LEDGER[key] = row
        row["calls"] = int(row["calls"]) + 1
        row["asked_sec"] = round(float(row["asked_sec"]) + asked, 6)
        row["slept_sec"] = round(float(row["slept_sec"]) + took, 6)
        row["last_at"] = stamp
        if skipped:
            row["skipped"] = int(row["skipped"]) + 1
        _LEDGER_WRITTEN += 1
        return dict(row)
def note_process_wait(elapsed_sec: float, *, where: str, waited_for: str = "",
                      purpose: str = "等外部进程退出（实测耗时，不是 timeout 上限）"
                      ) -> dict[str, Any]:
    """记一次"等外部进程"的实测耗时（`kind="external_process"`）。

    为什么这些点不换成 `await_io`：阻塞发生在 `Popen.communicate(timeout=…)` 里面，
    换成 sleep 会把"进程一退就返回"变成"睡满才返回"，取消语义随之坏掉。账要的是
    "这一次实际等了多久"，那不需要改阻塞方式 —— 所以记的是实测耗时，不是 timeout。

    `where` 必须点名到"哪一个 communicate"：同一个函数里两处 timeout 不同的等待
    要能分开读（`agent_e._run_script/poll` 与 `/final`），不许合成一行。
    """
    return note_wait(elapsed_sec, purpose, kind="external_process", where=where,
                     waited_for=waited_for, slept=elapsed_sec)


def waits(*, kind: str | None = None) -> dict[str, Any]:
    """读等待账（进程内聚合）。返回 `{rows, count, calls, asked_sec, slept_sec, checked}`。"""
    with _LEDGER_LOCK:
        rows = [dict(r) for r in _LEDGER.values()
                if kind is None or str(r.get("kind") or "") == str(kind)]
    rows.sort(key=lambda r: (str(r.get("kind") or ""), str(r.get("where") or ""),
                             str(r.get("purpose") or "")))
    return {
        "checked": True,
        "rows": rows,
        "count": len(rows),
        "calls": sum(int(r.get("calls") or 0) for r in rows),
        "asked_sec": round(sum(float(r.get("asked_sec") or 0.0) for r in rows), 6),
        "slept_sec": round(sum(float(r.get("slept_sec") or 0.0) for r in rows), 6),
        "skipped": sum(int(r.get("skipped") or 0) for r in rows),
        "reason": "",
    }


def reset_waits() -> None:
    """清空进程内的等待账（判据之间的隔离点；盘上的那一份不动）。"""
    global _LEDGER_WRITTEN
    with _LEDGER_LOCK:
        _LEDGER.clear()
        _LEDGER_WRITTEN = 0


def flush_waits(workspace: str | Path) -> dict[str, Any]:
    """把等待账落到 `<工作区>/out/clock/waits.json`。返回读数（写不成 => checked=False）。"""
    got = waits()
    doc = {"schema": SCHEMA, "saved_at": "", "rows": got["rows"],
           "count": got["count"], "calls": got["calls"],
           "asked_sec": got["asked_sec"], "slept_sec": got["slept_sec"]}
    reading = now()
    doc["saved_at"] = _iso(reading.wall) if reading.wall is not None else ""
    try:
        _atomic_json(waits_path(workspace), doc)
    except OSError as exc:
        return {"checked": False, "reason": f"等待账写不成：{type(exc).__name__}: {exc}",
                **{k: got[k] for k in ("rows", "count", "calls", "asked_sec", "slept_sec")}}
    return {"checked": True, "reason": "", "path": str(waits_path(workspace)),
            **{k: got[k] for k in ("rows", "count", "calls", "asked_sec", "slept_sec")}}


#: 普查认的三种形态。`sleep` 是"真睡"（计时类）；`wait` / `blocking_io` 是"阻塞在同步
#: 原语或子进程调用上"（等的是事件/进程本身，不是钟点）。
CENSUS_FORMS: tuple[str, ...] = ("sleep", "sleep_ref", "wait", "blocking_io")

#: 允许留在普查之外（不走 `await_io` / `note_wait`）的原始等待，逐条登记。
#:
#: 每条必须写 `why`（为什么它可以不记账）与 `blocked_by`（谁挡着没改）。
#: 空 `blocked_by` = 这一处本来就该留在账外（只有主时钟本体这一条）。
ALLOWED_RAW_WAITS: tuple[dict[str, str], ...] = (
    {"path": "agentflow/clock.py", "func": "await_io", "form": "sleep",
     "why": "主时钟本体的真睡：它就是这本账的写入口，不能再由别人来记",
     "blocked_by": ""},
    {"path": "agentflow/clock.py", "func": "await_io", "form": "sleep_ref",
     "why": "同上（`await_io` 里那个 `... else time.sleep` 的绑定是它的实现本体）",
     "blocked_by": ""},
)

#: 已经接上 `note_wait` 的原始等待（阻塞由原语完成，账照样记）。
#:
#: 登记在这里的作用是"普查能把它们与没人管的那些分开"：前者是记账的等待，
#: 后者才是缺口。`path/func` 用类名/函数名点路（行号会漂，名字不会）。
GOVERNED_PRIMITIVE_WAITS: tuple[tuple[str, str], ...] = (
    ("agentflow/conductor.py", "SummonHandle/wait"),
    ("agentflow/scheduler.py", "WaveHandle/wait_any"),
    ("agentflow/scheduler.py", "WaveHandle/wait_all"),
    ("agentflow/scheduler.py", "WaveHandle/_wait_wave"),
    ("agentflow/scheduler.py", "WaveHandle/_dispatch"),
    # 2026-10-25 第二批（业主放行）：三处 `communicate(timeout=)` 用
    # `note_wait(elapsed, kind="external_process")` 记账 —— 阻塞方式不变（换了会毁
    # 取消语义），账上记的是实测耗时。
    ("agentflow/cancellation.py", "run_cancellable"),
    # 2026-10-27（R-BE3）：`run_cancellable` 杀完子进程之后那两段等待搬进了独立函数
    # `_drain_after_kill`（`communicate(timeout=_KILL_GRACE_SEC)` 与 `wait(timeout=1.0)`），
    # 而这张表是按名字对齐的 ⇒ 需要单独登记这一条。
    # 这是"登记"不是"豁免"：那两段各自记一条 `kind="external_process"` 的等待
    # （`waited_for` 分得清是哪一处）；账上没有它们的话，它们就是缺口。
    ("agentflow/cancellation.py", "_drain_after_kill"),
    ("agentflow/agent_e/core.py", "_run_script"),
)

#: 明确留在账外的"阻塞型"等待（等的是进程/事件本身，换成 sleep 会改变语义）。
#:
#: 今天这一栏是空的：上一批的三处已经全部接上 `note_wait`。留这张表是为了
#: "下次有人要加一处例外"时有一个必须写理由的落点（而不是散在代码注释里）。
EXEMPT_PRIMITIVE_WAITS: tuple[dict[str, str], ...] = ()

#: 普查的默认扫描根（`src`，于是 rel 路径形如 `agentflow/clock.py`）。
_CENSUS_ROOTS: list[str] | None = None

_CENSUS_CACHE: dict[str, Any] | None = None


def set_census_roots(roots: Iterable[str | Path] | None) -> None:
    """换普查的扫描根（判据用；`None` = 回到默认的包目录）。"""
    global _CENSUS_ROOTS, _CENSUS_CACHE, _PROGRAM_CENSUS_CACHE
    _CENSUS_ROOTS = [str(Path(r).resolve()) for r in roots] if roots is not None else None
    _CENSUS_CACHE = None
    _PROGRAM_CENSUS_CACHE = None


def _census_roots() -> list[Path]:
    if _CENSUS_ROOTS:
        return [Path(r) for r in _CENSUS_ROOTS]
    return [Path(__file__).resolve().parent.parent]


def _wait_form(node: ast.Call) -> str:
    """这个调用算不算"原始等待"，算的话是哪一形态。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr == "sleep":
            return "sleep"
        if attr in ("wait", "wait_for"):
            # `self.wait(...)` 是方法自调用（原语在别处，普查会在那一处点到），
            # 不算"这里又有一个原始等待"。
            if attr == "wait" and isinstance(func.value, ast.Name) \
                    and func.value.id == "self":
                return ""
            return "wait"
        if attr in ("communicate", "join") and any(
                getattr(k, "arg", None) == "timeout" for k in node.keywords):
            return "blocking_io"
        return ""
    if isinstance(func, ast.Name) and func.id == "sleep":
        return "sleep"
    return ""


class _WaitVisitor(ast.NodeVisitor):
    """走一遍一棵 AST，把原始等待点全部记下来（带所在函数/方法的名字）。

    两种形态都记：调用（`.sleep(...)`）与裸引用（`= time.sleep`）。只记调用会漏掉
    最要命的那一种回退 —— `self._sleep = sleep or time.sleep` 只是把真睡绑回来，
    之后再调 `self._sleep(...)` 时普查看不见那个绑定（实测：fetch / modelgw 的
    默认等待正是这一形，改回它不会有任何调用点叫 `time.sleep`）。
    """

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[dict[str, Any]] = []
        self.refs: list[dict[str, Any]] = []

    def _enter(self, name: str) -> None:
        self.stack.append(str(name or "<anonymous>"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (node.attr == "sleep" and isinstance(node.value, ast.Name)
                and node.value.id == "time"):
            self.refs.append({
                "line": int(getattr(node, "lineno", 0) or 0),
                "form": "sleep_ref",
                "func": "/".join(self.stack) or "<module>",
            })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        form = _wait_form(node)
        if form:
            self.hits.append({
                "line": int(getattr(node, "lineno", 0) or 0),
                "form": form,
                "func": "/".join(self.stack) or "<module>",
            })
        self.generic_visit(node)

    def findings(self) -> list[dict[str, Any]]:
        """调用点 + 那些"不是某个调用的被调者"的裸引用。"""
        call_lines = {(int(h["line"]), h["func"]) for h in self.hits
                      if h["form"] == "sleep"}
        out = list(self.hits)
        for ref in self.refs:
            if (int(ref["line"]), ref["func"]) in call_lines:
                continue   # `time.sleep(...)` 已经在调用点里记过一次
            out.append(ref)
        return out


def _iter_source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _exempt_for(path: str, func: str, form: str) -> dict[str, str] | None:
    """这条原始等待是不是逐条登记过的例外。`func` 按名字尾对齐（类名会加前缀）。"""
    for row in ALLOWED_RAW_WAITS + EXEMPT_PRIMITIVE_WAITS:
        if row["path"] != path or row["form"] != form:
            continue
        want = str(row.get("func") or "")
        if not want or want == func or func.endswith("/" + want):
            return row
    return None


def _primitive_governed(path: str, func: str) -> bool:
    return any(p == path and (f == func or func.endswith("/" + f))
               for p, f in GOVERNED_PRIMITIVE_WAITS)


def raw_wait_census(*, source_root: str | Path | Iterable[str | Path] | None = None,
                    refresh: bool = False) -> dict[str, Any]:
    """普查"没走主时钟账的原始等待"。返回 `{checked, findings, files, reason}`。

    它认三种形态（`CENSUS_FORMS`）：`time.sleep(...)` / `.wait(...)` /
    `communicate(timeout=...)`。用 AST 而不是正则：正则会命中注释、docstring 与
    字符串里的 `time.sleep`（实测：本仓库有一处 docstring 讲 `sleep(30)`，
    正则会把那段话算成一个等待点）。
    """
    global _CENSUS_CACHE
    roots: list[Path]
    if source_root is None:
        roots = _census_roots()
    elif isinstance(source_root, (str, Path)):
        roots = [Path(source_root).resolve()]
    else:
        roots = [Path(r).resolve() for r in source_root]
    cache_key = "｜".join(str(r) for r in roots)
    if _CENSUS_CACHE is not None and _CENSUS_CACHE.get("key") == cache_key \
            and not refresh:
        return dict(_CENSUS_CACHE["value"])
    findings: list[dict[str, Any]] = []
    exempt: list[dict[str, Any]] = []
    files = 0
    reasons: list[str] = []
    for root in roots:
        if not root.is_dir():
            reasons.append(f"扫描根不是目录：{root}")
            continue
        for path in _iter_source_files(root):
            files += 1
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception as exc:  # noqa: BLE001 - 读不成要说，不许当"没问题"
                reasons.append(f"{rel} 读不成：{type(exc).__name__}: {exc}")
                continue
            visitor = _WaitVisitor()
            visitor.visit(tree)
            for hit in visitor.findings():
                func, form = hit["func"], hit["form"]
                row = {"path": rel, "line": hit["line"], "func": func,
                       "form": form,
                       "where": f"{rel}:{hit['line']}（{func}）"}
                allowed = _exempt_for(rel, func, form)
                if allowed is not None:
                    exempt.append({**row, "why": allowed.get("why", ""),
                                   "blocked_by": allowed.get("blocked_by", "")})
                elif form == "sleep":
                    findings.append(row)
                elif _primitive_governed(rel, func):
                    findings.append({**row, "governed": True})
                else:
                    findings.append(row)
    findings.sort(key=lambda r: (r["path"], r["line"]))
    exempt.sort(key=lambda r: (r["path"], r["line"]))
    value = {
        "checked": not reasons,
        "files": files,
        "roots": [str(r) for r in roots],
        "findings": findings,
        "exempt": exempt,
        "reason": "；".join(reasons),
    }
    _CENSUS_CACHE = {"key": cache_key, "value": value}
    return dict(value)


def coverage(*, source_root: str | Path | Iterable[str | Path] | None = None,
             refresh: bool = False) -> dict[str, Any]:
    """"主时钟控制了所有计时类工作没有"的机器判据。返回一份复合读数。

    读数分四层，刻意不折平：

    - `waits_outside_clock`：真睡（`time.sleep` 一类）里没走主时钟账的处数。
      它是业主点名的那个判据，目标 0。
    - `waits_on_primitives_ungoverned`：阻塞在同步原语/子进程上、既没记账也没登记的处数。
    - `waits_exempt`：逐条登记在 `ALLOWED_RAW_WAITS` / `EXEMPT_PRIMITIVE_WAITS` 里的例外，
      每条带 `why` 与 `blocked_by`（是谁挡着没改）。
    - `covers_all_timed_work`：前两层都空且没有例外时才为真。今天它是假的 ——
      例外里有两处是被禁改区挡住的，把它们并进 0 就等于把没做完的活报成做完了。
    - `programs_outside_clock`：起进程却没进程序计时器的处数（`program_census()` 的
      findings 数）。它与 `waits_outside_clock` 是同一档纪律的两件事：前者问"等了没记账"，
      后者问"程序在跑而账上没有计时器"（业主 2026-10-27：「运行一个程序时会自动启动
      一个计时器」）。它不并进 `covers_all_timed_work`：那一格的口径是"计时类工作"，
      而程序计时器是这次新加的一档，并进去等于悄悄改了那条既有判据的含义。
    """
    census = raw_wait_census(source_root=source_root, refresh=refresh)
    ledger = waits()
    pcensus = program_census(source_root=source_root, refresh=refresh)
    if not census["checked"]:
        return {
            "checked": False, "waits_outside_clock": None,
            "waits_outside_where": [], "waits_exempt": [], "waits_exempt_count": None,
            "waits_master_clock": [], "waits_master_clock_count": None,
            "waits_on_primitives": None, "waits_on_primitives_ungoverned": None,
            "waits_recorded": None, "waits_recorded_sec": None,
            "covers_all_timed_work": None, "files_scanned": census["files"],
            "programs_checked": bool(pcensus.get("checked")),
            "programs_outside_clock": (len(pcensus.get("findings") or ())
                                       if pcensus.get("checked") else None),
            "programs_outside_where": [f["where"] for f in (pcensus.get("findings") or ())],
            "programs_files_scanned": pcensus.get("files"),
            "reason": census["reason"] or "普查没查成",
        }
    outside = [f for f in census["findings"] if f["form"].startswith("sleep")]
    prims = [f for f in census["findings"] if not f["form"].startswith("sleep")]
    ungoverned = [f for f in prims if not f.get("governed")]
    # 主时钟本体那一条不是"绕过账的等待"：它就是这本账的写入口。单列一格，
    # 不并进 `waits_exempt`（并进去会让"还有几处没进账"这个读数虚高一处）。
    #
    # 2026-11-20（拆 clock.py 收口）：这一格的判定从"路径以 clock.py 结尾"改成
    # "函数名就是 `await_io`"。为什么：主时钟本体的实现会从一个模块搬到另一个模块
    # （`await_io` 已搬进本模块），按文件名认的判据会跟着实现漂、或在搬家那一步
    # 把写入口误报成缺口。按函数名认才是那句话的本意（"这本账的写入口"），
    # 函数名比文件名稳。豁免面一个字节没放宽（仍然是那两条 sleep / sleep_ref）。
    exempt_all = list(census["exempt"])
    master = [e for e in exempt_all if str(e.get("func") or "") == "await_io"]
    exempt = [e for e in exempt_all if str(e.get("func") or "") != "await_io"]
    blocked = [e for e in exempt if str(e.get("blocked_by") or "").strip()]
    reason = ""
    if outside:
        reason = f"还有 {len(outside)} 处真睡没走主时钟：{'; '.join(f['where'] for f in outside)}"
    elif ungoverned:
        reason = (f"还有 {len(ungoverned)} 处阻塞等待没记账也没登记："
                  f"{'; '.join(f['where'] for f in ungoverned)}")
    elif exempt:
        reason = (f"有 {len(exempt)} 处逐条登记的例外，其中 {len(blocked)} 处被禁改区挡着："
                  f"{'; '.join(e['where'] + '（' + (e.get('blocked_by') or '自带例外') + '）' for e in exempt)}")
    return {
        "checked": True,
        "waits_outside_clock": len(outside),
        "waits_outside_where": [f["where"] for f in outside],
        "waits_exempt": exempt,
        "waits_exempt_count": len(exempt),
        "waits_master_clock": master,
        "waits_master_clock_count": len(master),
        "waits_on_primitives": len(prims),
        "waits_on_primitives_ungoverned": len(ungoverned),
        "waits_recorded": int(ledger["calls"]),
        "waits_recorded_groups": int(ledger["count"]),
        "waits_recorded_sec": float(ledger["asked_sec"]),
        "covers_all_timed_work": not outside and not ungoverned and not exempt,
        "files_scanned": census["files"],
        "programs_checked": bool(pcensus.get("checked")),
        "programs_outside_clock": (len(pcensus.get("findings") or ())
                                   if pcensus.get("checked") else None),
        "programs_outside_where": [f["where"] for f in (pcensus.get("findings") or ())],
        "programs_files_scanned": pcensus.get("files"),
        "reason": reason,
    }
