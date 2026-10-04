# -*- coding: utf-8 -*-
"""判据（`draft/37` §128）：停机开关、子进程登记，以及"优雅停止要把子进程一起停掉"。

用户口径：

> 优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉
> 优雅停止和强制停止应该是主控 M 的 tool

这一组钉四件事（三态纪律：每一格都要能单独分辨）：

1. 开关的三种状态分得开：没叫停 ⇒ `None`；叫停 ⇒ 带理由的负载；「文件坏了 ⇒ 带 `unreadable`
   的负载」（不许读成"没叫停"——那等于停机请求消失）；
2. 子进程登记：登记了才活着、注销之后不在了、「死 pid 不算活着」；
3. 强制停止「按登记」杀，且「把自己排除」（M 在自己这一趟里调强制停止时不能把自己杀掉，
   否则返回值与台账全丢）；
4. E 的实验子进程「在开关落盘后立刻被终止」（实测从 30 s 降到 0.36 s），
   并且台账记的是"用户叫停"而不是"超时"（两种事的处置方向完全不同）。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

from agentflow import stopctl
from agentflow.agent_e import AgentE
from agentflow.store import Store


def test_the_three_stop_states_are_distinguishable(tmp_path: pathlib.Path):
    """三态：没叫停 / 叫停 / 开关坏了（读不懂「不许」当成没叫停）。"""
    assert stopctl.read_stop(tmp_path) is None

    got = stopctl.request_stop(tmp_path, reason="user", by="M", sid="s1")
    assert got["reason"] == "user" and got["by"] == "M" and got["force"] is False, got
    assert stopctl.read_stop(tmp_path) is not None
    again = stopctl.request_stop(tmp_path, reason="budget", by="user")
    assert again["reason"] == "user", "幂等：第一次的理由不许被后来的覆盖"

    assert stopctl.clear_stop(tmp_path) is True
    assert stopctl.read_stop(tmp_path) is None

    stopctl.stop_path(tmp_path).write_text("{坏 JSON", encoding="utf-8")
    broken = stopctl.read_stop(tmp_path)
    assert broken is not None and "unreadable" in broken, (
        "坏掉的开关被读成『没叫停』= 停机请求消失 —— 三态纪律不允许")


def test_pid_registration_separates_live_from_dead(tmp_path: pathlib.Path):
    """登记 / 注销 / 死 pid：`live_pids` 只报真的还活着的那些。"""
    assert stopctl.live_pids(tmp_path) == []
    stopctl.register_pid(tmp_path, "M", "sid-1")
    live = stopctl.live_pids(tmp_path)
    assert [p["pid"] for p in live] == [os.getpid()], live
    assert live[0]["role"] == "M" and live[0]["sid"] == "sid-1", live

    # 造一条"进程早就没了"的登记：文件在，但不该被算成活进程
    dead = stopctl.pid_path(tmp_path, "E", "sid-2")
    dead.parent.mkdir(parents=True, exist_ok=True)
    dead.write_text('{"pid": 999999, "role": "E", "sid": "sid-2"}', encoding="utf-8")
    assert [p["pid"] for p in stopctl.live_pids(tmp_path)] == [os.getpid()]

    assert stopctl.unregister_pid(tmp_path, "M", "sid-1") is True
    assert stopctl.live_pids(tmp_path) == []


def test_force_stop_targets_registered_pids_and_excludes_the_caller(tmp_path: pathlib.Path):
    """强制停止：按登记杀、「排除调用者自己」（M 不能把自己杀了）。

    沙箱里 `taskkill` 可能被拒（实测 `ERROR: Access denied`）——所以这条判据断言的
    是"打了哪些 pid"这个「决定」，以及"返回里如实说杀没杀掉"；真被杀掉时再断言子进程没了。
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        stopctl.register_pid(tmp_path, "E", "child", pid=child.pid)
        stopctl.register_pid(tmp_path, "M", "me")
        out = stopctl.kill_registered(tmp_path, exclude_pid=os.getpid())
        assert child.pid in out["requested"], out
        assert os.getpid() not in out["requested"], "调用者自己不许被列进被杀名单"
        assert out["excluded"] == os.getpid(), out
        for res in out["results"]:
            assert set(res) >= {"pid", "killed", "via", "detail"}, res
            assert isinstance(res["killed"], bool), res
        if out["killed"]:
            time.sleep(0.5)
            assert not stopctl.alive(child.pid), "报了杀掉，进程却还在"
    finally:
        child.kill()
        child.wait(timeout=10)


def test_the_experiment_child_is_killed_when_the_stop_switch_appears(tmp_path: pathlib.Path):
    """E 的实验子进程：开关一落盘就终止，且记成"用户叫停"而不是"超时"。

    真机读数（第 4 趟）：两次 600 s 的枚举实验在"没人看"的情况下跑满 ——
    用户叫停之后它们照旧跑完，那 20 分钟白烧。这条判据用一个睡 30 s 的脚本钉住
    "立刻停"：修复前实测 30.1 s，修复后 0.36 s。
    """
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    (ws / "scripts").mkdir()
    (ws / "scripts" / "slow.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    stopctl.request_stop(ws, reason="user", by="test")

    t0 = time.monotonic()
    out = AgentE(st, workspace_root=ws).run_experiment("停机探针", "slow",
                                                       "scripts/slow.py", timeout=60)
    elapsed = time.monotonic() - t0
    assert elapsed < 10, f"开关在跑之前就落盘了，却跑了 {elapsed:.2f}s（脚本只睡 30 s）"
    assert "用户叫停" in str(out["notes"]), out["notes"]
    assert "[超时]" not in str(out["notes"]), "用户叫停与超时是两件事，不许折叠"
    assert out["result"] == "inconclusive", out
