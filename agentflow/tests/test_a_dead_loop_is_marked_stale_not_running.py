# -*- coding: utf-8 -*-
"""判据：进程已不在「如实标死」，进程还在 / 没登记「照旧在飞」。

业主的判据（这条目标的原文）：只许把"进程已不在"的行如实标死，不许伪造收工。

## 真机（2026-10-28 `projects/paper-rewrite-78c`）

上一趟以 `final_refused` 退出，M 进程（子循环跑在它里面，是线程）被带走时没写
`agent_run_end` ⇒ `--status` 一直报 3 条在飞（V/D/V），而进程早已不在。

## 三档（一条都不许折平）

1. 会话里 start 之后没有 end，且这个 sid 登记过的进程全都不在了 ⇒ `stale_rows`；
2. 登记过、pid 还活着 ⇒ 照旧 `running`；
3. 压根没登记 ⇒ 照旧 `running`（"没登记"不是"已死"，fail-closed；78c 当前就是这一档，
   它的 `runs/` 被优雅停清空了）。
"""
from __future__ import annotations

import pathlib

from agentflow import sessions as SESS
from agentflow import stopctl as SC


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    return ws


def _start_without_end(ws: pathlib.Path, *, sid: str, role: str, task_id: str) -> None:
    SESS.append(ws, {"kind": "agent_run_start", "role": role, "task_id": task_id,
                     "ts": "2026-10-28T09:00:00+08:00"}, sid=sid)


def _register(ws: pathlib.Path, *, pid: int, role: str, sid: str) -> None:
    SC.register_pid(ws, role=role, sid=sid, pid=pid)


def test_a_dead_registration_marks_the_row_stale(tmp_path: pathlib.Path):
    """① 正题：登记过、进程已死 ⇒ 归 stale_rows（不再冒充在飞）。"""
    ws = _ws(tmp_path)
    _start_without_end(ws, sid="s1", role="V", task_id="t-000156")
    _register(ws, pid=999_999, role="V", sid="s1")          # 这个 pid 一定不活
    got = SC.running_loops(ws)
    assert got["running"] == [], got["running"]
    assert [r["task_id"] for r in got["stale_rows"]] == ["t-000156"], got
    assert "不在" in str(got["stale_rows"][0].get("why")), got["stale_rows"]


def test_a_live_registration_still_counts_as_running(tmp_path: pathlib.Path):
    """② 正控：登记着、pid 还活着（用本进程 pid）⇒ 照旧在飞。"""
    import os

    ws = _ws(tmp_path)
    _start_without_end(ws, sid="s2", role="D", task_id="t-000176")
    _register(ws, pid=os.getpid(), role="D", sid="s2")
    got = SC.running_loops(ws)
    assert [r["task_id"] for r in got["running"]] == ["t-000176"], got["running"]
    assert got["stale_rows"] == [], got["stale_rows"]


def test_an_unregistered_loop_is_still_running(tmp_path: pathlib.Path):
    """③ 反真空：没登记 ⇒ 仍按在飞读（"没登记"不是"已死"）。"""
    ws = _ws(tmp_path)
    _start_without_end(ws, sid="s3", role="V", task_id="t-000195")
    got = SC.running_loops(ws)
    assert [r["task_id"] for r in got["running"]] == ["t-000195"], got["running"]
    assert got["stale_rows"] == [], got["stale_rows"]

