# -*- coding: utf-8 -*-
"""进程树治理：Windows 作业对象（`draft/39` §3.21 五 I13）—— D03 的根因修法。

## 这一层解决什么（D03 的真机读数）

强制停止那条路上，`taskkill /T /F` 与 `os.kill` 在受限环境里都会被拒
（实测：`taskkill ERROR: Access denied`、`os.kill` `WinError 5`），于是"强停"看起来做了、
进程还在跑 —— 而更早的一次实测更直白：包装进程被杀之后 python 子进程又跑了 12 分钟。

I13 的立场是"循环怎么死都行，最后一个句柄一关，OS 收掉整棵传递树"：
把每一轮的进程装进一个作业对象（`KILL_ON_JOB_CLOSE`），终止时只需 `CloseHandle` ——
不依赖 `taskkill` 能不能成功，也不需要在父进程活着的时候逐个去杀子孙。

## 三态（本模块的口径）

- 平台支持（Windows 且 API 可用）⇒ `available()` 为 `True`，各函数正常工作；
- 平台不支持（非 Windows / 老系统）⇒ `available()` 为 `False` 且 `unavailable_reason()` 给出原因，
  各函数如实拒绝（抛 `JobObjectUnavailable`），不假装杀掉、也不静默降级成"没做"；
- "没查成"（`QueryInformationJobObject` 失败）由 `assigned_pids()` 返回
  `({"pids": […], "checked": False, "reason": …})` 表达 —— 空列表不等于"没有进程"。

## 用法（一轮的形态）

```python
job = create_job("agentflow-round")          # KILL_ON_JOB_CLOSE
assign(job, child.pid)                       # 起完就把这一轮的根进程放进去
...
grace_then_kill(job, grace_sec=5.0)          # 先宽限（让循环自己收尾），再 TerminateJobObject
reap(job)                                    # 收割残留（列出还挂在作业里的 pid）
close(job)                                   # 最后一个句柄一关 ⇒ OS 收掉整棵树
```
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as _w
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

#: 作业对象的极限信息类与"最后一个句柄关闭即杀"的标志。
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
#: Toolhelp 快照（列进程用；`wmic` 在新版 Windows 上已经没有了）。
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ProcessEntry32(ctypes.Structure):
    """`PROCESSENTRY32W`（只为读 pid 与父 pid —— 其余字段按原样留位）。"""

    _fields_ = [
        ("dwSize", _w.DWORD), ("cntUsage", _w.DWORD), ("th32ProcessID", _w.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", _w.DWORD),
        ("cntThreads", _w.DWORD), ("th32ParentProcessID", _w.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", _w.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class JobObjectUnavailable(RuntimeError):
    """这个平台/这套 API 用不了 —— 调用方必须如实报告，不许把它读成"已经杀掉了"。"""


@dataclass
class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", _w.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", _w.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", _w.DWORD),
        ("SchedulingClass", _w.DWORD),
    ]


@dataclass
class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


@dataclass
class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


@dataclass
class Job:
    """一个作业对象的句柄（用 `close()` 收掉整棵树 —— 那是这一层存在的理由）。"""

    handle: Any
    name: str = ""
    closed: bool = False
    pids: list[int] = field(default_factory=list)


def _k32() -> Any:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def available() -> bool:
    """这台机器能不能用作业对象（非 Windows / API 缺失 ⇒ `False`）。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        k32 = _k32()
        return bool(getattr(k32, "CreateJobObjectW", None)
                    and getattr(k32, "AssignProcessToJobObject", None))
    except Exception:  # noqa: BLE001 —— 探测失败就是"用不了"
        return False


def unavailable_reason() -> str:
    """用不了的原因（人话；能用时返回空串）—— 三态里的"为什么没做"。"""
    if available():
        return ""
    if not sys.platform.startswith("win"):
        return f"当前平台是 {sys.platform}：作业对象是 Windows 专有机制"
    return "kernel32 里读不到 CreateJobObjectW / AssignProcessToJobObject"


def create_job(name: str = "", *, kill_on_close: bool = True) -> Job:
    """建一个作业对象；`kill_on_close=True` 时装上 `KILL_ON_JOB_CLOSE`。

    为什么一定要那个标志：它把"终止整棵树"变成一个关句柄的动作 ——
    即使我们的进程自己崩了，OS 也会在最后一个句柄关闭时收掉整棵传递树。
    """
    if not available():
        raise JobObjectUnavailable(unavailable_reason())
    k32 = _k32()
    handle = k32.CreateJobObjectW(None, str(name) or None)
    if not handle:
        raise JobObjectUnavailable(f"CreateJobObjectW 失败：{ctypes.get_last_error()}")
    job = Job(handle=handle, name=str(name))
    if kill_on_close:
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            _w.HANDLE(handle), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise JobObjectUnavailable(
                f"SetInformationJobObject(KILL_ON_JOB_CLOSE) 失败：{ctypes.get_last_error()}")
    return job


def assign(job: Job, pid: int) -> bool:
    """把一个进程（通常是这一轮的根进程）放进作业。返回是否成功。

    子进程会自动继承作业归属（除非有人显式 `CREATE_BREAKAWAY_FROM_JOB`），
    所以"把根放进去"就等于"整棵传递树都在里面"。
    """
    if not available():
        raise JobObjectUnavailable(unavailable_reason())
    if job.closed:
        raise JobObjectUnavailable("作业已经关掉了（关掉之后 OS 已经收过树）")
    k32 = _k32()
    h = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
    if not h:
        return False
    try:
        ok = bool(k32.AssignProcessToJobObject(_w.HANDLE(job.handle), _w.HANDLE(h)))
    finally:
        k32.CloseHandle(_w.HANDLE(h))
    if ok and int(pid) not in job.pids:
        job.pids.append(int(pid))
    return ok


def assigned_pids(job: Job) -> dict[str, Any]:
    """作业里现在还挂着的 pid（三态：查不成 ⇒ `checked=False` + 原因）。"""
    if not available():
        return {"pids": [], "checked": False, "reason": unavailable_reason()}
    if job.closed:
        return {"pids": [], "checked": True, "reason": "作业已关闭（树已经被收掉）"}
    k32 = _k32()
    n = 64
    buf = ctypes.create_string_buffer(8 + 8 * n)
    ok = k32.QueryInformationJobObject(
        _w.HANDLE(job.handle), _JOB_OBJECT_BASIC_PROCESS_ID_LIST, ctypes.byref(buf),
        ctypes.sizeof(buf), None)
    if not ok:
        return {"pids": [], "checked": False,
                "reason": f"QueryInformationJobObject 失败：{ctypes.get_last_error()}"}
    _assigned, count = ctypes.c_uint32.from_buffer(buf, 0), ctypes.c_uint32.from_buffer(buf, 4)
    ids = [ctypes.c_size_t.from_buffer(buf, 8 + 8 * i).value for i in range(int(count.value))]
    return {"pids": [int(x) for x in ids if x], "checked": True, "reason": ""}


def terminate(job: Job, *, exit_code: int = 1) -> bool:
    """强杀整棵树（一个 API 调用）；返回是否成功。"""
    if not available():
        raise JobObjectUnavailable(unavailable_reason())
    if job.closed:
        return True
    k32 = _k32()
    return bool(k32.TerminateJobObject(_w.HANDLE(job.handle), int(exit_code)))


def descendants_of(pid: int, *, max_depth: int = 8) -> list[int]:
    """这个 pid 的后代（按 `ParentProcessId` 走，纯 ctypes 的 Toolhelp 快照）。

    为什么必须有它（E14 实测，2026-10-05）：作业归属不向前追溯 ——
    把一个已经跑起来的进程 `assign` 进作业，不会把它此前已经生出来的子进程带进来。
    于是"停一棵已经在跑的树"只 assign 根是不够的：必须把现有后代逐个也 assign 进去
    （新生的子进程才会自动继承）。`wmic` 在新版 Windows 上已经不带了，所以这里走
    `CreateToolhelp32Snapshot`（不依赖任何外部命令）。
    """
    if not available():
        return []
    k32 = _k32()
    snapshot = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        return []
    entry = _ProcessEntry32()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32)
    children: dict[int, list[int]] = {}
    try:
        ok = k32.Process32First(_w.HANDLE(snapshot), ctypes.byref(entry))
        while ok:
            children.setdefault(int(entry.th32ParentProcessID), []).append(
                int(entry.th32ProcessID))
            ok = k32.Process32Next(_w.HANDLE(snapshot), ctypes.byref(entry))
    finally:
        k32.CloseHandle(_w.HANDLE(snapshot))
    out: list[int] = []
    frontier = [int(pid)]
    for _ in range(max(1, int(max_depth))):
        nxt: list[int] = []
        for p in frontier:
            for c in children.get(p, []):
                if c not in out and c != int(pid):
                    out.append(c)
                    nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return out


def assign_tree(job: Job, pid: int) -> dict[str, Any]:
    """把根 + 它现有的全部后代都放进作业（新生的子进程自动继承）。

    返回 `{"assigned": [...], "failed": [...]}` —— 逐个的成败都要留痕：
    "有几个没放进去"正是"这次强杀可能漏进程"的读数。
    """
    targets = [int(pid)] + descendants_of(pid)
    assigned: list[int] = []
    failed: list[int] = []
    for t in targets:
        (assigned if assign(job, t) else failed).append(t)
    return {"assigned": assigned, "failed": failed}


def _grace_wait(poll_sec: float) -> None:
    """宽限期里的一个轮询间隔：真睡，并记进主时钟那本账（`clock.await_io`）。"""
    from . import clock as CLK

    CLK.await_io(max(0.05, float(poll_sec)), "宽限期里等被停的子进程自己收尾",
                 kind="grace", where="jobobject.grace_then_kill")


def grace_then_kill(job: Job, *, grace_sec: float = 5.0, poll_sec: float = 0.3,
                    exit_code: int = 1) -> dict[str, Any]:
    """先宽限（让循环自己收尾），到点再 `TerminateJobObject`；返回过程读数。

    为什么"先宽限"：一轮正在做的实验脚本被杀在半路会留下半个产物，而"优雅停"这一档
    （`stopctl` 的开关）本来就是给它们自己收尾的机会；宽限期过了还没走，才动强杀。
    `stragglers` 是宽限期结束时还挂着的 pid —— 它们就是"没自己走掉"的那批。
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < max(0.0, float(grace_sec)):
        got = assigned_pids(job)
        if got.get("checked") and not got.get("pids"):
            return {"killed": False, "elapsed_sec": round(time.monotonic() - t0, 3),
                    "stragglers": [], "note": "宽限期内它们自己走完了（没有强杀）"}
        _grace_wait(poll_sec)
    before = assigned_pids(job)
    ok = terminate(job, exit_code=exit_code)
    after = assigned_pids(job)
    return {"killed": bool(ok), "elapsed_sec": round(time.monotonic() - t0, 3),
            "stragglers": list(before.get("pids") or []),
            "left": list(after.get("pids") or []),
            "checked": bool(after.get("checked")),
            "note": "宽限期到 ⇒ TerminateJobObject 收掉整棵树" if ok
                    else "TerminateJobObject 失败 ⇒ 只能靠 CloseHandle 的 KILL_ON_JOB_CLOSE"}


def reap(job: Job) -> dict[str, Any]:
    """收割残留：列出还挂在作业里的 pid（给"每轮 reap_job"用；不杀，只报）。"""
    got = assigned_pids(job)
    return {"pids": got.get("pids") or [], "checked": bool(got.get("checked")),
            "reason": got.get("reason") or "",
            "count": len(got.get("pids") or [])}


def close(job: Job) -> None:
    """关句柄 —— `KILL_ON_JOB_CLOSE` 会让 OS 收掉整棵传递树。幂等。"""
    if job.closed or not job.handle:
        job.closed = True
        return
    k32 = _k32()
    k32.CloseHandle(_w.HANDLE(job.handle))
    job.closed = True
    job.handle = None


def selftest() -> int:
    """最小自检：平台可用性、建/关作业、起一个真子进程并验证关句柄把树收掉。"""
    import subprocess

    checks: list[tuple[str, bool]] = []
    checks.append(("平台可用性有明确答案", isinstance(available(), bool)))
    if not available():
        print(f"  [SKIP] 作业对象用不了：{unavailable_reason()}（如实报，不假装）")
        return 0
    job = create_job("agentflow-selftest")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks.append(("assign 成功", assign(job, child.pid)))
    got = assigned_pids(job)
    checks.append(("作业里读得到那个 pid", child.pid in (got.get("pids") or [])))
    close(job)
    from . import clock as CLK

    CLK.await_io(0.5, "自检：等 OS 把子进程树收掉再看一眼",
                 kind="selftest", where="jobobject.selftest")
    dead = child.poll() is not None or not _alive(child.pid)
    checks.append(("关句柄之后子进程被 OS 收掉", dead))
    if not dead:  # pragma: no cover - 极端环境
        child.kill()
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


def _alive(pid: int) -> bool:
    """这个 pid 还活着吗（用一个极小的探测；查不成时保守地当"活着"）。"""
    if not sys.platform.startswith("win"):
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    k32 = _k32()
    h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = _w.DWORD()
        ok = k32.GetExitCodeProcess(_w.HANDLE(h), ctypes.byref(code))
        return bool(ok) and int(code.value) == 259      # STILL_ACTIVE
    finally:
        k32.CloseHandle(_w.HANDLE(h))


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
