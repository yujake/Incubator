# -*- coding: utf-8 -*-
"""停程序那一层：探活、两刀（温和 / 强制）、收口、唤醒等它的人。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十四刀（收口）。
停机这件事的判据只有一条：程序真的没了才算停掉。"真没了"要三步都给读数 ——
探活（`process_alive`）、两刀（`_terminate_pid` 先温和、`_force_kill_pid` 再强杀）、
停完再探一次（`_wait_until_gone` 的轮询）。三步写在两处就会有一处编出"已经杀了"的假读数
（`tests/test_a_program_i_started_is_a_program_i_can_stop.py` 的反真空钉的就是这个）。
收口之后还要把等它的人叫醒（`_wake_waiters` → `fire_due`）—— 否则"停了"这个消息
到不了父代理。

## 装了什么

`PROGRAM_STOP_GRACE_SEC` / `PROGRAM_STOP_POLL_SEC` / `PROGRAM_STOP_WAIT_SEC` /
`PROGRAM_STOP_RESULTS` / `process_alive` / `_exit_code_of` / `_terminate_pid` /
`_terminate_process_handle` / `_force_kill_pid` / `_wait_until_gone` / `_elapsed_of` /
`_wake_waiters` / `_stop_one_program` / `stop_program` / `programs_owned`。

## 依赖与可变量

本模块不写任何模块级可变量。依赖方向单向：`clockprogram`（收口口 / 归属判定）、
`clockfire`（`fire_due`）、`clockwaits`（`await_io`）、`clocktimer`（簿记）、
`clockbase`（词表与异常）。`tools/clock_tools` 的 `program.stop` 与 `stopctl`
都经 `from .clock import stop_program` 调用 —— 再导出之后调用点一个字没改。
纯搬移，逐名 AST dump 全等。
"""

from __future__ import annotations

import os
import signal
import time
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockStateError,
    _parse_iso,
)
from .clockevents import (  # noqa: F401 — 这些名字由 clockevents 定义
    _close_waiters_for_event,
)
from .clockfire import (  # noqa: F401 — 这些名字由 clockfire 定义
    fire_due,
)
from .clockprogram import (  # noqa: F401 — 这些名字由 clockprogram 定义
    finish_program,
    is_my_program,
    not_mine_refusal,
    program_message,
    program_owner,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    now,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    book,
)
from .clockwaits import (  # noqa: F401 — 这些名字由 clockwaits 定义
    await_io,
)

#: 停一条程序时给它的宽限秒数：先让它自己收尾，过了这个窗口才真杀。
#:
#: 为什么是常量而不是工具的参数（业主 2026-10-26 的 G1 施工单：「先 terminate、
#: 超时再 kill（给宽限秒数常量）」）：宽限是"这一刀的手感"，不是每一次调用该重新
#: 商量的口径。模型多给一个参数就多一种把宽限调成 0 的写法 —— 那是把"优雅"变成
#: "直接砍"，而读数上两者长得一样。
PROGRAM_STOP_GRACE_SEC: float = 3.0

#: 宽限与等待窗口里的轮询间隔（每一拍都进主时钟的等待账）。
PROGRAM_STOP_POLL_SEC: float = 0.1

#: 真杀之后最多再等它从进程表上消失多久；等不到就如实报 `timeout`。
PROGRAM_STOP_WAIT_SEC: float = 5.0

#: "停一条程序"的受控读数（`stop_program` 的 `result` 只取这几档，一档都不许折平）：
#:
#: - `killed`：真的把它停掉了（进程没了，那条程序计时器按 `outcome="killed"` 收口）；
#: - `already_exited`：它本来就结束了（幂等那一档：查过了、不是第二次杀成功，行不改）；
#: - `timeout`：杀不动 —— 窗口过了它还在跑（账上那条保持 pending，"它还在跑"必须读得出来）；
#: - `not_mine`：不是这一趟起的（受控拒绝；别人的与账上没有归属的都在这一档）；
#: - `not_found`：查过了、没有可停的那一条（编号不存在 / 不是程序计时器 / 账上没有 pid）。
#:
#: 为什么 `timeout` 与 `killed` 不许合并：合并之后"我杀了它"与"我没杀掉它"在读数上
#: 一样，而那正是这一批要修的东西（昨晚 15 个野进程是被"看起来杀了"留下的）。
PROGRAM_STOP_RESULTS: tuple[str, ...] = ("killed", "already_exited", "timeout",
                                         "not_mine", "not_found")


def process_alive(pid: int) -> bool:
    """这个 pid 还活着吗（唯一判法在 `stopctl.alive`，本模块不另写一份）。

    为什么不在这里写 `os.kill(pid, 0)`：Windows 上那不是探活，它会
    `TerminateProcess`（把被探测的进程杀掉）；`tasklist` 在受限环境里又拿不到读数。
    `stopctl.alive` 两条路都实测过（`OpenProcess(SYNCHRONIZE)` +
    `WaitForSingleObject`）。探不了时它说"不活着" —— 调用方据此不杀，绝不假装杀过。

    代价写在明处：探不了的那一档，`stop_program` 会落成 `already_exited`（不杀是安全
    方向，但"没查成"与"它已经自己走了"在这一格分不开 —— 探活是唯一判法，它没有三态口）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        from . import stopctl as SC
    except Exception:  # noqa: BLE001 - 连探活模块都读不到：按"不活着"处置
        return False
    try:
        return bool(SC.alive(pid_int))
    except Exception:  # noqa: BLE001 - 见 docstring 最后一句
        return False


def _exit_code_of(pid: int) -> int | None:
    """被杀进程的退出码（读得到就给，读不到就是 None —— 不是 0）。

    两种平台各一条路，都不用 subprocess（`program_census` 会把 clock.py 里新出现的
    起进程点报成"程序在跑而账上没有计时器"）：

    - Windows：`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
      `GetExitCodeProcess`；`STILL_ACTIVE`（259）说明它其实还在跑 ⇒ None。
      句柄一关进程对象就没了 ⇒ 这条常常读不到，那是诚实的 None。
    - POSIX：只有自家子进程收得到（`waitpid(WNOHANG)`）；不是自家子进程的
      `ChildProcessError` ⇒ None（"读不到"与"退出码是 0"必须分得开）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_int <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k32.OpenProcess(0x1000, 0, pid_int)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    return None
                value = int(code.value)
            finally:
                k32.CloseHandle(ctypes.c_void_p(handle))
            return None if value == 259 else value   # 259 = STILL_ACTIVE
        except Exception:  # noqa: BLE001 - 读不到就是 None
            return None
    try:
        got, status = os.waitpid(pid_int, os.WNOHANG)
    except (ChildProcessError, OSError):
        return None
    if got != pid_int:
        return None
    return int(os.waitstatus_to_exitcode(status)) if hasattr(os, "waitstatus_to_exitcode") \
        else None


def _terminate_pid(pid: int) -> dict[str, Any]:
    """第一刀：请它自己停。如实报"这一刀走了哪条路、有没有真的发出去"。

    ## Windows 上"优雅"到底指什么（业主 2026-10-26 的裁定）

    本平台没有"发给 console 子进程的请停信号"：`os.kill` 在这里就是
    `TerminateProcess`，与 kill 是同一个系统调用 —— 所以 Windows 上"先请停再强杀"
    在信号语义上没有任何差别。这一批里"优雅"指的是时机与告知，不是信号语义：

    1. 先落一条"有人喊停"的账（这一条程序计时器的 note 与 `program.stop` 的读数），
       并且先给它一个宽限窗口让它自己退出（有的程序会看自己的哨兵文件、或收到自己的
       停机条件就收尾）；
    2. 只有宽限窗口过了、它还在，才真动手；动手那一刻读数里写着 `force_kill`。
    3. 真要发 CTRL_BREAK 必须有进程组（`CREATE_NEW_PROCESS_GROUP`）——今天七个起程序
       的落点都没有开进程组（只有网页端的 detached 起法开了），所以这一档不假装发过：
       `sent=False` 逐字写着"没发"。

    POSIX 上这一刀是真信号（SIGTERM），收尾机会就落在这一步里。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"sent": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGTERM)
            return {"sent": True, "via": "SIGTERM", "why": ""}
        except OSError as exc:
            return {"sent": False, "via": "SIGTERM", "why": f"{type(exc).__name__}: {exc}"}
    return {"sent": False, "via": "",
            "why": ("Windows 上没有可发给 console 子进程的请停信号（这一档由宽限窗口"
                    "承担：先等它自己退，过了窗口才强杀）")}


def _terminate_process_handle(pid: int, *, exit_code: int = 9) -> dict[str, Any]:
    """最后一刀（只在没有作业对象时用）：`TerminateProcess`，只收根进程。"""
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x0001, 0, int(pid))   # PROCESS_TERMINATE
        if not handle:
            return {"killed": False, "via": "TerminateProcess",
                    "why": f"OpenProcess 失败（错误码 {ctypes.get_last_error()}）"}
        try:
            ok = bool(k32.TerminateProcess(ctypes.c_void_p(handle), int(exit_code)))
            why = "" if ok else f"TerminateProcess 失败（错误码 {ctypes.get_last_error()}）"
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
        return {"killed": ok, "via": "TerminateProcess", "why": why,
                "note": "这条路只收根进程：它已经生出来的子孙不在这一刀里"}
    except Exception as exc:  # noqa: BLE001 - 杀不成要如实报，不许假装
        return {"killed": False, "via": "TerminateProcess",
                "why": f"{type(exc).__name__}: {exc}"}


def _force_kill_pid(pid: int) -> dict[str, Any]:
    """第二刀：真收掉它（Windows 优先走作业对象，一次收掉整棵传递树）。"""
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"killed": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGKILL)
            return {"killed": True, "via": "SIGKILL", "why": ""}
        except OSError as exc:
            return {"killed": False, "via": "SIGKILL", "why": f"{type(exc).__name__}: {exc}"}
    job_why = ""
    try:
        from . import jobobject as JO

        if JO.available():
            job = JO.create_job(f"agentflow-program-stop-{pid_int}")
            try:
                placed = JO.assign_tree(job, pid_int)
                ok = bool(JO.terminate(job, exit_code=9))
                left = JO.assigned_pids(job)
                return {"killed": ok or not process_alive(pid_int), "via": "job",
                        "why": "", "assigned": list(placed.get("assigned") or ()),
                        "failed": list(placed.get("failed") or ()),
                        "left": list(left.get("pids") or ())}
            finally:
                try:
                    JO.close(job)
                except Exception:  # noqa: BLE001 - 关句柄失败不该带走调用方
                    pass
        job_why = f"作业对象用不了：{JO.unavailable_reason()}"
    except Exception as exc:  # noqa: BLE001 - 这条路走不通就退回下一刀（读数里留着）
        job_why = f"作业对象那条路失败：{type(exc).__name__}: {exc}"
    got = dict(_terminate_process_handle(pid_int))
    if job_why:
        got["job_attempt"] = job_why
    return got


def _wait_until_gone(pid: int, seconds: float, *, purpose: str) -> float:
    """等这个 pid 从进程表上消失，返回实际等了多久（不抛）。

    每一拍都走 `await_io`（主时钟的等待账是"所有等一会儿"的唯一入口，也是
    `raw_wait_census` 的判据：clock.py 里不许出现裸 `time.sleep`）。轮询次数由
    `PROGRAM_STOP_POLL_SEC` 与窗口长度算出来 —— 装上假时钟时 `await_io` 不真睡，
    光靠单调计数会把这里变成忙转，所以圈数也要有上限。
    """
    limit = max(0.0, float(seconds))
    step = max(0.01, float(PROGRAM_STOP_POLL_SEC))
    rounds = max(1, int(limit / step) + 2)
    started = time.monotonic()
    for _ in range(rounds):
        if not process_alive(int(pid)):
            break
        left = limit - (time.monotonic() - started)
        if left <= 0:
            break
        await_io(min(step, left), purpose, kind="program_stop",
                 where="clock._wait_until_gone", waited_for=f"pid:{int(pid)}")
    return max(0.0, time.monotonic() - started)


def _elapsed_of(timer: Timer) -> float | None:
    """这条程序从登记到现在过了多久（读不到时钟 => None，不是 0）。"""
    got = now()
    if got.status == "unknown" or got.wall is None:
        return None
    try:
        created = _parse_iso(timer.created_at)
    except ClockError:
        return None
    return max(0.0, (got.wall - created).total_seconds())


def _wake_waiters(workspace: str | Path, timer_id: str) -> dict[str, Any]:
    """把"等这条程序"的那几条表推一次到点（走既有的 `fire_due`，不另拼一条报醒）。

    为什么不是在 `finish_program` 里直接投递：收口与投递是两件事（一条程序计时器收口
    之后可能根本没人等它），而投递的唯一实现在到点动作那一处（`_deliver_due`：落
    mailbox 项 + 唤醒标记）。这里只是"别等到下一步才推"。
    """
    out: dict[str, Any] = {"checked": False, "watching": 0, "woken": 0,
                           "wake_ids": [], "reason": ""}
    wanted = f"program:{str(timer_id)}"
    try:
        bucket = book(workspace)
        watching = [t for t in bucket.all()
                    if t.state == "pending"
                    and str(t.wait_for_resolved or t.wait_for or "") == wanted]
    except ClockStateError as exc:
        out["reason"] = f"等它的那几条表读不成（{exc}）"
        return out
    out["watching"] = len(watching)
    # 程序收口是事件产生点（`EVENT_CLOSE_HOOKS["stop_program"]` 那一行）：按 `program:<号>`
    # 撞一次反查索引，把等它的那几条判进热表 —— 于是下面这一次 `fire_due` 只会投它们，
    # 不必扫全表（也因此在"什么都没到点"的拍上不会退化成 O(全表)）。
    try:
        _close_waiters_for_event("stop_program", [wanted])
    except Exception as exc:  # noqa: BLE001 - 消账炸了不带走下面这一次推进
        out["reason"] = f"消账没跑成（{type(exc).__name__}: {exc}）"
    try:
        report = fire_due(workspace)
    except Exception as exc:  # noqa: BLE001 - 推不成是"没查成"，不许折成"没人等它"
        out["reason"] = (f"到点动作没推成（{type(exc).__name__}: {exc}）⇒ "
                         "等它的那几条保持 pending，下一次步进会再推")
        return out
    out["checked"] = bool(report.get("checked", True))
    ids = {str(t.timer_id) for t in watching}
    woken = [r for r in (report.get("fired") or ()) if str(r.get("timer_id")) in ids]
    out["woken"] = len(woken)
    out["wake_ids"] = [str(r.get("wake_id") or "") for r in woken if r.get("wake_id")]
    if not out["checked"]:
        out["reason"] = f"时钟读不到 ⇒ 判不了 due（{report.get('reason') or '没查成'}）"
    elif watching and not woken:
        out["reason"] = "等它的那几条还在 pending（到点动作没接上或被推迟）⇒ 这一刀没把它们叫醒"
    return out


def _stop_one_program(workspace: str | Path, timer_id: str, *, task_id: str,
                      role: str, grace_sec: float, wait_sec: float,
                      reason: str) -> dict[str, Any]:
    """停一条（`stop_program` 的真身：逐条读数与四档判据都在这里）。"""
    out: dict[str, Any] = {
        "checked": True, "timer_id": str(timer_id), "result": "not_found",
        "program": "", "argv_digest": "", "pid": None, "state": "", "outcome": "",
        "elapsed_sec": None, "exit_code": None, "mine": False,
        "task_id": "", "role": "", "owner": {}, "terminate": {}, "force_kill": {},
        "waited_sec": 0.0, "still_alive": [], "watching": 0, "woken": 0,
        "wake_ids": [], "reason": "",
    }
    bucket = book(workspace)      # 读不成抛 ClockStateError：由工具层报 checked=False
    timer = bucket.get(str(timer_id))
    if timer is None:
        out["reason"] = f"没有 {timer_id} 这一条程序计时器（不是'已经结束了'）"
        return out
    if not timer.is_program:
        out["state"] = timer.state
        out["reason"] = (f"{timer_id} 是 kind={timer.kind!r} 的条目，不是程序计时器 —— "
                         "停程序只认 kind='program' 那一条（等时间/等谁的表用 clock.timer_cancel）")
        return out
    out.update({"program": timer.program, "argv_digest": timer.argv_digest,
                "pid": timer.pid, "state": timer.state, "outcome": timer.outcome,
                "elapsed_sec": timer.elapsed_sec, "exit_code": timer.exit_code,
                "task_id": str(timer.task_id or ""), "role": str(timer.role or ""),
                "owner": program_owner(timer),
                "mine": is_my_program(timer, task_id=task_id, role=role)})
    if not out["mine"]:
        out["result"] = "not_mine"
        out["reason"] = not_mine_refusal(timer, task_id=task_id, role=role)
        return out
    if timer.state != "pending":
        out["result"] = "already_exited"
        out["reason"] = (f"{timer_id} 早就收口了（state={timer.state}, "
                         f"outcome={timer.outcome or '没记'}）—— 查过了，不是第二次杀掉；"
                         "这一行一个字都不改（幂等）")
        return out
    try:
        pid = int(timer.pid or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        out["reason"] = ("这一条账上没有 pid（attach_program_pid 没补上）⇒ 没有可停的对象；"
                         "程序行保持 pending，它还在不在看 program.list 的 running 那一格")
        return out
    if not process_alive(pid):
        out["result"] = "already_exited"
        out["reason"] = (f"pid {pid} 已经不在进程表上了 —— 查过了、它自己走掉的；"
                         "账上那条还是 pending（收口归起它的 program_span，这一刀不改行）")
        return out
    # ---- 第一刀 + 宽限窗口（"优雅"= 时机与告知，见 `_terminate_pid` 的 docstring）
    terminate = _terminate_pid(pid)
    out["terminate"] = terminate
    waited = _wait_until_gone(pid, float(grace_sec),
                              purpose="停程序：宽限期里等它自己收尾")
    # ---- 第二刀：只有还活着才动手（读数里写着走了哪条路）
    force: dict[str, Any] = {}
    if process_alive(pid):
        force = _force_kill_pid(pid)
        out["force_kill"] = force
        waited += _wait_until_gone(pid, float(wait_sec),
                                   purpose="停程序：真杀之后等它从进程表上消失")
    out["waited_sec"] = round(waited, 3)
    if process_alive(pid):
        out["result"] = "timeout"
        out["still_alive"] = [pid]
        out["state"] = timer.state
        out["reason"] = (f"pid {pid} 在 {float(grace_sec):g}+{float(wait_sec):g} 秒里没有消失"
                         f"（杀不动：{force.get('why') or terminate.get('why') or '原因没有读数'}）"
                         "—— 账上那条保持 pending、程序行不改：它还在跑这件事必须读得出来")
        return out
    # ---- 真没了：按 killed 收口（走既有的 finish_program），再推一次等它的人
    elapsed = _elapsed_of(timer)
    exit_code = _exit_code_of(pid)
    note_bits = [f"被点名停下（program.stop，操作者台账号 {task_id or '（没给）'}）"]
    if str(reason or "").strip():
        note_bits.append(str(reason).strip())
    if terminate.get("via"):
        note_bits.append(f"第一刀 {terminate['via']}")
    elif terminate.get("why"):
        note_bits.append(f"第一刀没发（{terminate['why']}）")
    if force.get("via"):
        note_bits.append(f"第二刀 {force['via']}")
    closed, state = finish_program(workspace, timer_id, outcome="killed",
                                   exit_code=exit_code, elapsed_sec=elapsed,
                                   note="；".join(note_bits))
    out.update({"result": "killed", "state": getattr(closed, "state", ""),
                "outcome": getattr(closed, "outcome", ""),
                "elapsed_sec": getattr(closed, "elapsed_sec", None),
                "exit_code": getattr(closed, "exit_code", None),
                "finish_state": state})
    out["reason"] = program_message(program=timer.program, outcome="killed",
                                    exit_code=out["exit_code"],
                                    elapsed_sec=out["elapsed_sec"],
                                    purpose=timer.purpose)
    wake = _wake_waiters(workspace, timer_id)
    out.update({"watching": int(wake.get("watching") or 0),
                "woken": int(wake.get("woken") or 0),
                "wake_ids": list(wake.get("wake_ids") or ()),
                "wake_checked": bool(wake.get("checked")),
                "wake_reason": str(wake.get("reason") or "")})
    return out


def stop_program(workspace: str | Path, timer_id: str, *, task_id: str,
                 role: str = "", grace_sec: float = PROGRAM_STOP_GRACE_SEC,
                 wait_sec: float = PROGRAM_STOP_WAIT_SEC,
                 reason: str = "") -> dict[str, Any]:
    """停掉一条"我这一趟起的"程序：先宽限、再真杀，然后按 `killed` 收口并唤醒等它的人。

    业主 2026-10-26 的 G1（逐字）：「重点完善子代理杀自己发出去的程序进程的工具」。

    ## 这个函数做四件，缺一件就等于没做

    1. 受控拒绝：不是这一趟起的（别人的 / 账上没有归属的）⇒ `result="not_mine"`，
       一个进程都不碰（`is_my_program` 是唯一判据，`not_mine_refusal` 是唯一拒信）；
    2. 先 terminate、超时再 kill：宽限 `PROGRAM_STOP_GRACE_SEC` 秒（`_terminate_pid`），
       过了窗口还在才 `_force_kill_pid`（Windows 上优先走作业对象，一次收整棵树）；
    3. 等它真的消失（`_wait_until_gone`，上限 `PROGRAM_STOP_WAIT_SEC`）——
       等不到就 `result="timeout"` 并点名还在跑的 pid，账上那条保持 pending；
    4. 收口 + 唤醒：真没了才 `finish_program(outcome="killed", elapsed_sec=…,
       exit_code=…)`，再推一次 `fire_due` 把等它的那几条叫醒。

    ## 不抛异常

    这四档是读数，不是异常（`PROGRAM_STOP_RESULTS`）。唯一的抛出是簿记读不成
    （`ClockStateError`）—— 那是"没查成"，由工具层折成 `checked=False`，
    绝不折成"没有这一条"。

    ## 已知边界（两条，都不假装）

    - pid 复用：这个 pid 是起进程那一刻记下的，且只在 pending 的账上；账上那条如果
      已经被别的进程占着同一个 pid，这一刀还是会落下去 —— pid 级杀法没有更强的
      身份校验（`Popen` 对象早就不在手上了）。
    - Windows 上的"优雅"是时机而不是信号语义（见 `_terminate_pid`）。
    """
    grace = max(0.0, float(grace_sec))
    wait = max(0.0, float(wait_sec))
    out = _stop_one_program(workspace, str(timer_id), task_id=str(task_id or ""),
                            role=str(role or ""), grace_sec=grace, wait_sec=wait,
                            reason=str(reason or ""))
    out["grace_sec"] = round(grace, 3)
    out["wait_sec"] = round(wait, 3)
    return out


def programs_owned(workspace: str | Path, *, task_id: str = "",
                   role: str = "", include_done: bool = False) -> dict[str, Any]:
    """这个工作区的程序按归属分桶（`program.list` 的读侧，判据也读这里）。

    四桶，一格都不折平：

    - `mine`：我这一趟起的（`is_my_program` 为真；`include_done` 决定含不含已收口的）；
    - `unowned`：账上没有归属的（改前存量的形态：`task_id` 空）—— 它们不归任何人，
      既不算我的，也不许被 `program.stop` 杀掉；单列出来是为了让人看见"存量还在"；
    - `others`：别人的（有归属、但不是我的）—— 只给条数，不给 pid（别人的程序不该
      在我的读数里被点名）；
    - 三态：簿记读不成 => `checked=False`（"没查成"不是"没有程序在跑"）。
    """
    out: dict[str, Any] = {"checked": False, "mine": [], "unowned": [], "others": 0,
                           "others_running": 0, "count": 0, "running": 0,
                           "reason": ""}
    try:
        rows = [t for t in book(workspace).all() if t.is_program]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"程序计时器读不成：{type(exc).__name__}: {exc}"
        return out
    if not include_done:
        rows = [t for t in rows if t.state == "pending"]
    mine: list[Timer] = []
    unowned: list[Timer] = []
    others = 0
    others_running = 0
    running = 0
    for timer in rows:
        if timer.state == "pending":
            running += 1
        if not str(timer.task_id or ""):
            unowned.append(timer)
        elif is_my_program(timer, task_id=task_id, role=role):
            mine.append(timer)
        else:
            others += 1
            if timer.state == "pending":
                others_running += 1
    out.update({"checked": True, "mine": mine, "unowned": unowned,
                "others": others, "others_running": others_running,
                "count": len(rows),
                "running": running,
                "reason": ""})
    return out
