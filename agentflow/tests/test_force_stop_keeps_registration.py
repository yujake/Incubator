# -*- coding: utf-8 -*-
"""强制停止：杀不成就把进程登记留着（`draft/37` §140 的真机读数）。

## 那个假绿长什么样

2026-10-05 真机（p6f）：`agentflow stop --force` 在受限环境里 `taskkill /T /F` 被拒
（`ERROR: Access denied`；换 `os.kill(SIGTERM)` 同样 `WinError 5`）。框架当时照删登记
（旧注释还写着"留着也会被 live_pids 滤掉"），于是紧接着的 `agentflow stop --status` 报

    登记着的活进程：0 个

而那个进程还活着（直到它自己在下一个步检查点消费开关才退）。这就是
"没杀成"被折叠成"没有活进程"——三态纪律里最忌的那一类假绿。

修法：只有"确实杀掉了"或"它本来就死了"才注销登记；杀不成的留着，
结果里多一栏 `kept`，CLI 把它念出来。
"""
from __future__ import annotations

import os
import pathlib

from agentflow import stopctl


def test_a_failed_kill_keeps_the_registration(tmp_path: pathlib.Path, monkeypatch):
    """正控（那个假绿的反面）：杀失败 ⇒ 登记留着，`live_pids` 仍报它在册。"""
    stopctl.register_pid(tmp_path, "M", "s", pid=os.getpid())
    assert [p["pid"] for p in stopctl.live_pids(tmp_path)] == [os.getpid()]

    def fake_kill(pid: int, timeout: float = 60) -> dict:
        return {"pid": pid, "killed": False, "via": "taskkill", "detail": "ERROR: Access denied"}

    monkeypatch.setattr(stopctl, "kill_tree", fake_kill)
    got = stopctl.kill_registered(tmp_path)
    assert got["killed"] == 0 and got["kept"] == [os.getpid()], got
    assert got["failed"] and got["failed"][0]["detail"].startswith("ERROR"), got
    # 登记还在 ⇒ status 不会假绿
    assert [p["pid"] for p in stopctl.live_pids(tmp_path)] == [os.getpid()]


def test_a_successful_kill_unregisters(tmp_path: pathlib.Path, monkeypatch):
    """正控（成功那一支照旧）：杀成了就注销登记，`kept` 为空。"""
    stopctl.register_pid(tmp_path, "M", "s", pid=os.getpid())

    def fake_kill(pid: int, timeout: float = 60) -> dict:
        return {"pid": pid, "killed": True, "via": "taskkill", "detail": "SUCCESS"}

    monkeypatch.setattr(stopctl, "kill_tree", fake_kill)
    got = stopctl.kill_registered(tmp_path)
    assert got["killed"] == 1 and got["kept"] == [], got
    assert stopctl.live_pids(tmp_path) == []


def test_an_already_dead_pid_is_cleaned_up(tmp_path: pathlib.Path, monkeypatch):
    """边界：登记里那个 pid 已经死了 ⇒ 即使"杀"返回 False 也要把它清掉（它不是活进程）。"""
    stopctl.register_pid(tmp_path, "M", "s", pid=os.getpid())
    monkeypatch.setattr(stopctl, "kill_tree",
                        lambda pid, timeout=60: {"pid": pid, "killed": False,
                                                 "via": "taskkill", "detail": "already gone"})
    monkeypatch.setattr(stopctl, "alive", lambda pid: False)
    got = stopctl.kill_registered(tmp_path)
    assert got["kept"] == [] and stopctl.live_pids(tmp_path) == [], got
