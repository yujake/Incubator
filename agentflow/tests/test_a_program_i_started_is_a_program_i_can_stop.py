# -*- coding: utf-8 -*-
"""判据：我自己起的程序我能停掉，别人的（与没有归属的）我停不了（G1，业主 2026-10-26）。

## 业主原话（唯一权威）

    「重点完善子代理杀自己发出去的程序进程的工具（由于计时器监控着那些程序，
      我想实现起来不会太难），以及注销前检测的能力」

## 改前红在哪（机器形态）

改前工具面上一件能停"我起的某个程序"的都没有：`clock.*` 恰好九件（`clock.now` /
`timer_start` / `alarm_start` / `periodic_start` / `periodic_stop` / `timer_purpose` /
`timer_list` / `timer_cancel` / `wait_any`），没有一件带 `pid` 或"停程序"这种形参
（本文件第 0 条把它当清单逐个数过）；`program.list` / `program.stop` 这两个名字在
`registry.names()` 里根本不存在。于是：

- 第 1 条（a）改前红在工具不存在（`registry.call("program.list")` 是 `unknown_tool`）；
- 第 2 条（b）改前红在同一处，而且"程序计时器按 killed 收口"这件事只有框架内部的
  取消令牌/停机开关能产生（`cancellation.run_cancellable` 与 `agent_e._run_script`），
  智能体没有点名叫停的入口；
- 第 3 条（c）改前是"没有可拒绝的东西"（没有那个动作，就没有归属判据）；
- 第 4 条（d）幂等那一档改前不存在；
- 第 5 条（e）"三个都杀掉、逐个 pid 复核"改前不存在；
- 第 6 条（f）是反真空：把"真杀"与探活打桩掉之后，第 2 条用的那几条断言必须红。

## 六条判据

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| 0 | 老的九件 `clock.*` 上没有停程序的旋钮（清单逐个数） | 加一个 `pid` 形参 ⇒ 这一条红 |
| 1 (a) | 起一个睡 60 秒的程序 ⇒ `program.list` 看得到它（pid / argv / 计时器 id / 起于何时 / 已跑多久 / 目的齐全，`retire_ready=false`） | `include_done` 与 `running` 两格各钉一次 |
| 2 (b) | `program.stop` 它 ⇒ 进程真的没了、程序行 `outcome="killed"`、计时器 `fired`、等它的 waiter 被叫醒 | 第 6 条把"真杀"打桩掉 ⇒ 这里必红 |
| 3 (c) | 别人的程序 / 没有归属的旧行 ⇒ 受控拒绝 `not_mine`，进程一个都不许碰，行也不许改 | 正控：自己的那一条同形调用必须 `killed` |
| 4 (d) | 已经退出的再 stop ⇒ `already_exited`，不报错、不改行（幂等） | 也钉"pending 但进程已没了"那一档 |
| 5 (e) | 起 3 个 ⇒ `program_stop(all_programs=true)` ⇒ 三个都 killed，逐个 pid 复核没有一个还在跑 | 结束后 `program.list` 的 `running` 必须是 0 |

## 零模型钱

全部用例只起真的 `python -c "import time; time.sleep(60)"` 子进程并调确定性代码，
一次模型请求都没有。进程在 `finally` 里统一收尸，判据失败也不留野进程。
"""
from __future__ import annotations

import contextlib
import pathlib
import subprocess
import sys

import pytest

from agentflow import clock as C
from agentflow import stopctl as SC
from agentflow.conductor import Conductor, calling_as
from agentflow.store import Store
from agentflow.tools import ToolRegistry
from agentflow.tools import clock_tools as CT

#: 被停的那个程序：睡够久（60 秒）又不写任何东西。
#: 为什么不用 `time.sleep(5)`：判据要在"它还在跑"的时候动手，窗口短了会变成
#: 偶发假红（机器忙时 5 秒可能已经过完），而"它自己跑完了"与"被我停了"必须分得开。
SLEEPER = "import time; time.sleep(60)"

#: 判据里那一趟的串（只出现在 detail / purpose 里，用来认行）。
TASK_TEXT = "判据：G1 停我自己的程序"


# ------------------------------------------------------------------ 夹具

def _setup(tmp_path, name: str):
    """临时工作区 + 真时钟 + 已装配的工具面（`clock_tools.register` 会把到点动作接上）。"""
    root = pathlib.Path(tmp_path) / name
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    C.reset()
    C.reset_waits()
    C.reset_observed_events()
    reg = ToolRegistry(name="program-stop-judge")
    reg.bound_role = "E"
    CT.register(reg, store=store, root=root)
    return store, reg, root


def _me(store: Store) -> str:
    """这一趟的台账号（必须有台账行：到点项要按它解析收件人）。"""
    return Conductor(store).open_top_level_run("E", TASK_TEXT)


def _call(reg: ToolRegistry, name: str, me: str, **kw):
    """按生产路径调一次工具：身份由 `calling_as` 挂上（`AgentLoop._do_tool` 同一条路）。

    为什么必须挂：工具的形状里没有"我是谁"这一格（业主 2026-10-26 的裁定），
    `program.list` / `program.stop` 都按调用上下文判归属 —— 不挂上，"我的"那半边
    一条都读不到（那正是本判据要验的判据本身）。
    """
    with calling_as(me, "E"):
        return reg.call(name, role="E", **kw)


def _start_sleeper(root, *, task_id: str = "", role: str = "",
                   purpose: str = "判据：睡 60 秒的程序"):
    """走产品那一条路起一个真进程：`ProgramSpan.open` + `Popen` + `attach_pid`。

    为什么不用工具起：今天没有"起程序"的工具（起程序是角色实现内部的事，
    `program_span` 是唯一入口），所以判据照 `cancellation.run_cancellable` 的同一顺序
    手工做一遍。

    归属的三种形态各有一条路：给了 `task_id`/`role` 就按给的挂（别人起的那一档）；
    一个都不给就不套 `calling_as`，让 `start_program` 的归属兜底从当前上下文现取
    （我起的那一档）；在没有上下文的地方一个都不给，落账就是空归属（旧行那一档）。
    """
    cmd = [sys.executable, "-c", SLEEPER]
    scope = calling_as(task_id, role) if (task_id or role) else contextlib.nullcontext()
    with scope:
        span = C.ProgramSpan(program=sys.executable, argv=cmd, workspace=str(root),
                             where="judge.program_stop", purpose=purpose,
                             to="self", task_id="", role="").open()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        span.attach_pid(proc.pid)
    return span, proc


def _still_running(proc) -> bool:
    """这个子进程还在跑吗（两路一起判；psutil 不在依赖里）。

    ① `Popen.poll()` 给了退出码 ⇒ 它已经结束；
    ② 否则再到 os/ctypes 层探一次（`stopctl.alive` 是那层的唯一实现在本仓里的落点）。

    为什么直接读 `stopctl.alive` 而不是 `clock.process_alive`：后者是被检对象的一部分
    （第 6 条会把它打桩掉）。判据的探活若借被检对象的探活，打桩就能同时骗过两边 ——
    那样这条判据证不了"进程真的停了"。
    """
    if proc.poll() is not None:
        return False
    return bool(SC.alive(int(proc.pid)))


def _reap(proc) -> None:
    """收尸（判据失败也不许留野进程：昨晚那 15 个就是这么来的）。"""
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - 收不掉就在读数里留着
        pass


def _assert_program_is_really_gone(proc, timer) -> None:
    """(b) 的那几条断言（第 6 条拿它证明"把真杀打桩掉 ⇒ 这里必红"）。

    分开写成一个函数是刻意的：反真空必须打在同一条判据上，否则证明的是
    "另外某个断言红了"，与"这一条真的承重"无关。
    """
    assert not _still_running(proc), f"pid {proc.pid} 还在跑（它没有被真的停掉）"
    assert timer is not None, "账上找不到那条程序计时器"
    assert timer.state == "fired", f"程序计时器没有收口：state={timer.state}"
    assert timer.outcome == "killed", f"结局不是 killed：outcome={timer.outcome}"


# ------------------------------------------------------------------ 0 老面清单

def test_0_the_old_clock_surface_has_no_stop_knob(tmp_path) -> None:
    """老的九件 `clock.*` 上没有任何"停程序"的旋钮 —— 停口只能是新加的两件。

    这一条是 (a) 的"改前红"机器形态：改前它就是九件、形参里没有一个能指到 pid，
    所以"停掉我起的那个进程"在工具面上结构性地做不到（不是"没人想起来用"）。
    """
    _, reg, _root = _setup(tmp_path, "zero")
    names = list(reg.names())
    nine = sorted(n for n in names if n.startswith("clock."))
    assert nine == sorted([
        "clock.now", "clock.timer_start", "clock.alarm_start", "clock.timer_list",
        "clock.timer_cancel", "clock.periodic_start", "clock.periodic_stop",
        "clock.timer_purpose", "clock.wait_any"]), nine
    for name in nine:
        props = set(((reg.get(name).params or {}).get("properties") or {}))
        assert not (props & {"pid", "program", "kill", "terminate", "signal"}), (name, props)
    assert "program.list" in names and "program.stop" in names, sorted(names)


# ------------------------------------------------------------------ 1 (a) 看得到

def test_a_a_sleeping_program_is_visible_in_my_list(tmp_path) -> None:
    """(a) 起一个睡 60 秒的程序 ⇒ `program.list` 看得到它，业主点名的格齐全。"""
    store, reg, root = _setup(tmp_path, "a")
    me = _me(store)
    span, proc = _start_sleeper(root, task_id=me, role="E")
    try:
        got = _call(reg, "program.list", me)
        assert got.ok is True, got.error
        data = got.data
        assert data["checked"] is True, data
        assert data["count"] == 1 and data["running"] == 1, data
        assert data["task_id"] == me, data
        row = dict(data["programs"][0])
        for key in ("timer_id", "program", "argv_digest", "pid", "at", "age_sec",
                    "state", "alive", "purpose", "owner"):
            assert key in row, (key, sorted(row))
        assert row["timer_id"] == span.timer.timer_id, row
        assert row["pid"] == int(proc.pid), row
        assert "time.sleep(60)" in row["argv_digest"], row
        assert row["state"] == "pending", row
        assert row["alive"] is True, row
        assert row["purpose"] == "判据：睡 60 秒的程序", row
        assert row["at"], row
        assert isinstance(row["age_sec"], (int, float)) and row["age_sec"] >= 0.0, row
        assert row["owner"]["task_id"] == me, row
        # 注销前检测那一格：我还有程序在跑 ⇒ 不许读成"可以销号"。
        assert data["retire_ready"] is False, data
        assert data["running"] == 1 and "我名下还有 1 个程序在跑" in data["note"], data
        # `include_done` 那一档：已经收口的行只有在显式要的时候才出现（正控）。
        C.finish_program(str(root), span.timer.timer_id, outcome="exited", exit_code=0)
        default = _call(reg, "program.list", me).data
        assert default["count"] == 0 and default["retire_ready"] is True, default
        everything = _call(reg, "program.list", me, include_done=True).data
        assert everything["count"] == 1, everything
    finally:
        _reap(proc)


# ------------------------------------------------------------------ 2 (b) 真停

def test_b_stop_really_kills_it_and_wakes_the_waiter(tmp_path) -> None:
    """(b) 停它 ⇒ 进程真的没了、程序行按 killed 收口、等它的 waiter 被叫醒。"""
    store, reg, root = _setup(tmp_path, "b")
    me = _me(store)
    span, proc = _start_sleeper(root, task_id=me, role="E")
    try:
        # 一条等它的表（业主 2026-10-26：等程序也是"点名"的一种）。
        waiter = C.start_timer(str(root), reason="等那个 60 秒的程序跑完",
                               wait_for=f"program:{span.timer.timer_id}",
                               task_id=me, role="E")
        assert C.process_alive(int(proc.pid)) is True, "起完就不见了：这一条证不了什么"
        got = _call(reg, "program.stop", me, timer_id=span.timer.timer_id,
                    reason="判据：它没人等了")
        assert got.ok is True, got.error
        data = got.data
        assert data["killed"] == 1 and data["stopped"] == 1, data
        assert data["already_exited"] == 0 and data["timeout"] == 0, data
        assert data["note"].startswith("我杀了 1 个自己的程序"), data
        item = dict(data["items"][0])
        assert item["result"] == "killed", item
        assert item["still_alive"] == [], item
        timer = C.book(str(root)).get(span.timer.timer_id)
        _assert_program_is_really_gone(proc, timer)
        assert timer.elapsed_sec is not None and timer.elapsed_sec >= 0.0, timer.elapsed_sec
        assert "program.stop" in timer.note or "被点名停下" in timer.note, timer.note
        # 等它的那条表：收口被叫醒了（走的是既有的到点动作：板项 + 唤醒标记）。
        woken = C.book(str(root)).get(waiter.timer_id)
        assert woken.state == "fired", woken.state
        assert woken.woke_reason == "closed", woken.woke_reason
        assert woken.mailbox_item_id, "到点项没有落板（只有收口、没有叫醒）"
        assert woken.wake_id, "唤醒标记没置"
    finally:
        _reap(proc)


# ------------------------------------------------------------------ 3 (c) 不是我的

def test_c_someone_elses_program_is_refused_and_untouched(tmp_path) -> None:
    """(c) 别人的程序、与账上没有归属的旧行 ⇒ 受控拒绝 not_mine，一个进程都不许碰。"""
    store, reg, root = _setup(tmp_path, "c")
    me = _me(store)
    other, other_proc = _start_sleeper(root, task_id="t-other", role="E",
                                       purpose="判据：别人起的程序")
    legacy, legacy_proc = _start_sleeper(root, task_id="", role="",
                                         purpose="判据：没有归属的旧行")
    try:
        # 正控：我自己的那一条同形调用必须真的能停（否则下面两条拒绝证明不了"只许碰自己的"）。
        # 它走的是写侧的归属兜底：`task_id` / `role` 都不给，落账时从调用上下文现取。
        with calling_as(me, "E"):
            mine, mine_proc = _start_sleeper(root, task_id="", role="")
        try:
            listed = _call(reg, "program.list", me).data
            assert listed["count"] == 1, listed
            assert listed["unowned_count"] == 1, listed
            assert listed["others"] == 1 and listed["others_running"] == 1, listed
            assert [r["timer_id"] for r in listed["programs"]] == [mine.timer.timer_id], listed
            # 别人的：受控拒绝，逐字点名"不是你的"。
            refused = _call(reg, "program.stop", me, timer_id=other.timer.timer_id)
            assert refused.ok is True, refused.error
            data = refused.data
            assert data["not_mine"] == 1 and data["killed"] == 0, data
            assert data["items"][0]["result"] == "not_mine", data["items"]
            assert "not_mine" in data["items"][0]["reason"], data["items"][0]["reason"]
            assert "不是" in data["items"][0]["reason"], data["items"][0]["reason"]
            # 空归属的旧行：同样不许被任何一趟当成自己的。
            legacy_refused = _call(reg, "program.stop", me,
                                   timer_id=legacy.timer.timer_id).data
            assert legacy_refused["not_mine"] == 1 and legacy_refused["killed"] == 0, \
                legacy_refused
            assert "没记它的归属" in legacy_refused["items"][0]["reason"], legacy_refused
            # 两条被拒的都还在跑，账也没被改过。
            assert _still_running(other_proc) is True, "别人的进程被碰了"
            assert _still_running(legacy_proc) is True, "没有归属的进程被碰了"
            for span in (other, legacy):
                row = C.book(str(root)).get(span.timer.timer_id)
                assert row.state == "pending" and row.outcome == "", (row.state, row.outcome)
            # 正控：我自己的那条停得掉。
            mine_stopped = _call(reg, "program.stop", me,
                                 timer_id=mine.timer.timer_id).data
            assert mine_stopped["killed"] == 1, mine_stopped
            assert _still_running(mine_proc) is False, "我自己的进程没停掉"
        finally:
            _reap(mine_proc)
    finally:
        _reap(other_proc)
        _reap(legacy_proc)


# ------------------------------------------------------------------ 4 (d) 幂等

def test_d_stopping_an_exited_program_is_idempotent(tmp_path) -> None:
    """(d) 已经退出的程序再 stop ⇒ already_exited，不报错、不改行。"""
    store, reg, root = _setup(tmp_path, "d")
    me = _me(store)
    span, proc = _start_sleeper(root, task_id=me, role="E")
    try:
        # 它自己跑完（走既有的收口路），之后再停一次。
        assert _call(reg, "program.stop", me,
                     timer_id=span.timer.timer_id).data["killed"] == 1
        assert _still_running(proc) is False
        before = C.book(str(root)).get(span.timer.timer_id)
        snapshot = (before.state, before.outcome, before.fired_at, before.note,
                    before.exit_code, before.elapsed_sec)
        again = _call(reg, "program.stop", me, timer_id=span.timer.timer_id)
        assert again.ok is True, again.error
        data = again.data
        assert data["already_exited"] == 1 and data["killed"] == 0, data
        assert data["items"][0]["result"] == "already_exited", data["items"]
        after = C.book(str(root)).get(span.timer.timer_id)
        assert (after.state, after.outcome, after.fired_at, after.note,
                after.exit_code, after.elapsed_sec) == snapshot, "幂等那一档改了行"
        # 第二档：账上还是 pending、而进程早就没了（起它的那条 span 没来得及收口）。
        span2, proc2 = _start_sleeper(root, task_id=me, role="E")
        try:
            proc2.kill()
            proc2.wait(timeout=15)
            gone = _call(reg, "program.stop", me, timer_id=span2.timer.timer_id)
            assert gone.ok is True, gone.error
            assert gone.data["items"][0]["result"] == "already_exited", gone.data["items"]
            row2 = C.book(str(root)).get(span2.timer.timer_id)
            assert row2.state == "pending", "这一档不该替起它的 span 收口（行不改）"
        finally:
            _reap(proc2)
    finally:
        _reap(proc)


# ------------------------------------------------------------------ 5 (e) 全部

def test_e_stopping_all_mine_leaves_none_running(tmp_path) -> None:
    """(e) 起 3 个 ⇒ 停全部 ⇒ 三个都 killed，逐个 pid 复核没有一个还在跑。"""
    store, reg, root = _setup(tmp_path, "e")
    me = _me(store)
    spans = []
    procs = []
    try:
        for i in range(3):
            span, proc = _start_sleeper(root, task_id=me, role="E",
                                        purpose=f"判据：第 {i + 1} 个程序")
            spans.append(span)
            procs.append(proc)
        listed = _call(reg, "program.list", me).data
        assert listed["running"] == 3, listed
        got = _call(reg, "program.stop", me, all_programs=True,
                    reason="判据：一次停全部")
        assert got.ok is True, got.error
        data = got.data
        assert data["mode"] == "all", data
        assert data["killed"] == 3, data
        assert sorted(data["requested"]) == sorted(s.timer.timer_id for s in spans), data
        assert data["still_alive"] == [] and data["timeout"] == 0, data
        for proc in procs:
            assert _still_running(proc) is False, f"pid {proc.pid} 还在跑"
        for span in spans:
            timer = C.book(str(root)).get(span.timer.timer_id)
            assert timer.state == "fired" and timer.outcome == "killed", \
                (timer.state, timer.outcome)
        after = _call(reg, "program.list", me).data
        assert after["running"] == 0 and after["retire_ready"] is True, after
        # 再停一次"全部"：没有可停的（不是没查成），也不许报错。
        empty = _call(reg, "program.stop", me, all_programs=True)
        assert empty.ok is True, empty.error
        assert empty.data["count"] == 0 and empty.data["killed"] == 0, empty.data
        assert "没有可停的" in empty.data["reason"], empty.data
    finally:
        for proc in procs:
            _reap(proc)


# ------------------------------------------------------------------ 6 (f) 反真空

def test_f_stubbing_the_real_kill_makes_b_red(tmp_path, monkeypatch) -> None:
    """(f) 反真空：把"真杀"与探活打桩掉 ⇒ 第 2 条（b）那几条断言必红。

    两半都要：只打桩"杀"而留真的探活 ⇒ 读数必须落 `timeout`（账不许自己编一个 killed）；
    连探活一起打桩（假装它已经死了）⇒ 账上会写 killed，而进程其实还在跑 ⇒
    b 的 pid 复核必须当场红。第二半是这一条存在的理由：它证明承重的是"停完再探一次"
    这一步，不是"杀函数的返回值"。
    """
    store, reg, root = _setup(tmp_path, "f")
    me = _me(store)
    span, proc = _start_sleeper(root, task_id=me, role="E")
    try:
        # ---- 前半：只打桩两刀，探活是真的 ⇒ 账上只能写 timeout
        monkeypatch.setattr(C, "_terminate_pid",
                            lambda pid: {"sent": False, "via": "", "why": "判据：打桩"})
        monkeypatch.setattr(C, "_force_kill_pid",
                            lambda pid: {"killed": False, "via": "stub",
                                         "why": "判据：打桩（没有真杀）"})
        got = _call(reg, "program.stop", me, timer_id=span.timer.timer_id)
        assert got.ok is True, got.error
        assert got.data["items"][0]["result"] == "timeout", got.data["items"]
        assert got.data["timeout"] == 1 and got.data["killed"] == 0, got.data
        assert got.data["still_alive"] == [int(proc.pid)], got.data
        assert _still_running(proc) is True, "打桩之后进程居然没了：这一条证不了什么"
        row = C.book(str(root)).get(span.timer.timer_id)
        assert row.state == "pending" and row.outcome == "", (row.state, row.outcome)
        with pytest.raises(AssertionError):
            _assert_program_is_really_gone(proc, row)

        # ---- 后半：连探活一起打桩（第一次真、之后一律"已经死了"）⇒ 账写 killed 而进程还在
        real_alive = C.process_alive
        calls = {"n": 0}

        def lying(pid: int) -> bool:
            calls["n"] = int(calls["n"]) + 1
            return bool(real_alive(pid)) if calls["n"] <= 1 else False

        monkeypatch.setattr(C, "process_alive", lying)
        monkeypatch.setattr(C, "_terminate_pid",
                            lambda pid: {"sent": False, "via": "", "why": "判据：打桩"})
        monkeypatch.setattr(C, "_force_kill_pid",
                            lambda pid: {"killed": False, "via": "stub",
                                         "why": "判据：打桩（没有真杀）"})
        lied = _call(reg, "program.stop", me, timer_id=span.timer.timer_id)
        assert lied.ok is True, lied.error
        assert lied.data["items"][0]["result"] == "killed", lied.data["items"]
        fake = C.book(str(root)).get(span.timer.timer_id)
        assert fake.state == "fired" and fake.outcome == "killed", (fake.state, fake.outcome)
        assert _still_running(proc) is True, "后半的前提不成立：进程真的没了"
        with pytest.raises(AssertionError):
            _assert_program_is_really_gone(proc, fake)
    finally:
        monkeypatch.undo()
        _reap(proc)
