"""实验脚本的数据目录守卫（B2f 路）。

## 为什么需要它

真机取证（`projects/lp-ball-15`，DATAHYGIENE 2026-11-22）：4 个野表
（`data/lp_ball_*.json`）不是 `fs.write` 写的 —— 是 E 的实验脚本在子进程里
`open("data/lp_ball_3d_final.json", "w")` 写的。`fs.write` 的保留路径闸跑在父进程里，
管不到子进程的 `open()`；而实验读数本来就该落 `out/` 下（原始输出日志是
`out/exp-logs/<实验号>.log`，穷举三件套仍在 `out/experiments/<实验号>/`），
`data/` 只由表工具写。

## 它拦什么

用 `sys.addaudithook` 拦三类审计事件（Python 3.11 实测的事件形状）：

- `open(path, mode, flags)`：`builtins.open` / `io.open` / `os.open` 都发这一个事件。
  `os.open` 的 `mode` 是 `None`，此时按 `flags` 里的写位判读/写；
- `os.rename`：`os.rename` 与 `os.replace` 共用这一个事件名（实测），所以两者一起拦；
- `os.remove`：`os.remove` 与 `os.unlink` 共用这一个事件名（实测）。

命中（路径在 data 根下）⇒ 抛 `PermissionError`，消息里带一句出路。
读放行：`mode` 不含 `w` / `a` / `x` / `+`、且 `flags` 不含写位 ⇒ 直接返回
（脚本读 `data/tasks.json` 一类历史读数是允许的）。
路径解析失败也放行：守卫的目的是别让实验把表目录写脏，不是把跑得通的实验拦死。

## 谁装它

本模块只提供 `install()`。真正在子进程里调用它的是
`_experiment_guard/sitecustomize.py`：`agent_e/core.py::_run_script` 把那个目录
prepend 进子进程的 `PYTHONPATH`，并把 data 根写进 `AGENTFLOW_EXPERIMENT_GUARD`。
父进程一次都不装 —— 表工具写 `data/` 是它的正常工作，不能被自己的守卫拦住。

## 为什么 `install` 幂等

`sys.addaudithook` 没有对应的卸载接口（钩子一旦装上就跟着这个进程一辈子），
所以重复调用必须不重复挂钩。重复 install 同一个根是一次空操作。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 命中时给模型/人的一句话出路。判据按这句话做断言，改它要同步改判据。
#:
#: 两个落点必须在同一条消息里说清（2026-11-22 B2f-TAIL 取证）：原始输出日志已经
#: 搬到 `out/exp-logs/`（`agent_e.run_experiment._write_run_log` 的写点），而穷举三件套
#: （`exhaustion.md` 那份报告）不搬，仍在 `out/experiments/<实验号>/`
#: （`exhaustionreport.REPORT_DIR`）。只说前者 ⇒ 模型照它把报告也写到 `out/exp-logs/`
#: 下，而框架只从 `out/experiments/<号>/exhaustion.md` 读 ②③ ⇒ 这一条拿不到 proof；
#: 只说后者 ⇒ 模型以为日志还在老地方，去改一份框架已经不再写的那条路径。
WAY_OUT = ("实验读数落 out/exp-logs/<实验号>.log（原始输出）；穷举三件套（搜索空间 / "
           "穷尽的判据 / 边界处理）仍落 out/experiments/<实验号>/exhaustion.md；"
           "data/ 只由表工具写")

#: `open` 的 mode 里出现这些字符就是写（含 `+`：读写）。
_WRITE_MODE_CHARS = frozenset("wax+")
#: `os.open` 的 mode 是 None，只能按 flags 判；命中任意一个就按写处理。
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_RENAME_EVENTS = frozenset({"os.rename", "os.replace"})
_REMOVE_EVENTS = frozenset({"os.remove", "os.unlink"})

#: 已登记的 data 根：abspath 归一化与 realpath 归一化各一份（后者挡符号链接绕行）。
_ROOTS: set[str] = set()
_REAL_ROOTS: set[str] = set()
#: `sys.addaudithook` 实际被调用过几次。只给判据看：重复 install 不许再挂一次。
_hook_installs = 0


def _normalize(path: object, *, real: bool) -> str:
    """把路径归一化成可比较的字符串；解析不了就让它抛（由调用方决定放行）。"""
    raw = os.fspath(path)  # type: ignore[arg-type]
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    base = os.path.realpath(raw) if real else os.path.abspath(raw)
    return os.path.normcase(base)


def _under(norm: str, roots: set[str]) -> bool:
    """`norm` 是否等于某个根、或在它下面。"""
    for root in roots:
        if norm == root or norm.startswith(root + os.sep):
            return True
    return False


def _deny_write(path: object) -> None:
    """路径落在 data 根下就抛 `PermissionError`；解析不了就放行（不误伤）。"""
    if not _ROOTS:
        return
    try:
        norm = _normalize(path, real=False)
        real = _normalize(path, real=True)
    except Exception:  # noqa: BLE001 - 路径解析失败 ⇒ 放行，不误伤
        return
    if _under(norm, _ROOTS) or _under(real, _REAL_ROOTS):
        raise PermissionError(f"实验脚本不许写数据目录（{path}）。{WAY_OUT}")


def _guard_open(args: tuple[object, ...]) -> None:
    """判 `open` 事件是读还是写；写才查路径。"""
    path = args[0] if args else None
    if isinstance(path, int):
        # 已经拿到文件描述符的 open：路径在这一层不可见，放行（不误伤）。
        return
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    try:
        if mode is not None:
            if not any(ch in str(mode) for ch in _WRITE_MODE_CHARS):
                return
        elif not int(flags or 0) & _WRITE_FLAGS:
            return
    except Exception:  # noqa: BLE001 - 判不出读/写 ⇒ 放行，不误伤
        return
    _deny_write(path)


def _audit_hook(event: str, args: tuple[object, ...]) -> None:
    """装进进程的那一个审计钩子：命中就抛，自己出 bug 绝不波及其他 open。"""
    try:
        if event == "open":
            _guard_open(args)
        elif event in _RENAME_EVENTS:
            if len(args) > 0:
                _deny_write(args[0])
            if len(args) > 1:
                _deny_write(args[1])
        elif event in _REMOVE_EVENTS:
            if len(args) > 0:
                _deny_write(args[0])
    except PermissionError:
        raise
    except Exception:  # noqa: BLE001 - 守卫自己的 bug 不许把无关的 open 拦死
        return


def install(data_root: str | Path) -> None:
    """把 `data_root` 登记成受守卫的目录，并在本进程装上审计钩子（幂等）。

    重复 install 同一个根是空操作：钩子只挂一次，之后只加根（同一个进程里可以有
    多个受守卫的目录，判据与测试都会用到）。`data_root` 解析不了时让它抛 ——
    那是调用方给错了东西，应该在起进程的地方显形，而不是静默地不设防。
    """
    global _hook_installs
    norm = _normalize(data_root, real=False)
    real = _normalize(data_root, real=True)
    if norm in _ROOTS:
        return
    _ROOTS.add(norm)
    _REAL_ROOTS.add(real)
    if _hook_installs:
        return
    sys.addaudithook(_audit_hook)
    _hook_installs += 1


def guarded_roots() -> tuple[str, ...]:
    """已登记的 data 根（abspath 归一化形态，按字典序）—— 判据与排障用。"""
    return tuple(sorted(_ROOTS))
