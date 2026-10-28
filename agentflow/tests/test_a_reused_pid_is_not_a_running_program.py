# -*- coding: utf-8 -*-
"""判据：pid 复用不许把"早已退出的程序"当成"还在跑"（闸不放松，只把读数测准）。

## 真机（2026-10-28 `projects/paper-rewrite-78c` 收工）

E1 的 `extract_pdf.py`：`state=fired / outcome=exited / exit_code=0 / elapsed 1.2 秒`，
读数却 `alive=true` ⇒ 销号闸被一台早就不存在的进程永久挡住；而业主两条裁定合起来是
「收工必须所有人停 + 所有进程停」且「不能为了着急收工强停」—— 既不能放松闸，也不能加停
的权力，只能把这个读数测准：Windows 的 pid 会被复用，账上那台退了之后，这个号可能属于
另一台刚起来的新进程。

## 这一组守什么

1. 复用号：创建时刻晚于计时器落账时刻 + 容差 ⇒ `alive=false` / `pid_reused=true`，
   不进闸（`running_count=0`）；
2. 真活着：创建时刻早于落账 ⇒ 照旧 `alive=true` / 进闸（闸一个字没放宽）；
3. fail-closed：创建时刻读不到 ⇒ 维持 `alive=true` / 进闸（"没读到"不许折成"没在跑"）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

from agentflow import clock as CLK
from agentflow import conductor as CD
from agentflow.conductor import programs_reading
from agentflow.store import Store

LOG_AT = "2026-10-28T09:00:00+00:00"


@pytest.fixture()
def bench():
    CLK.reset()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall=LOG_AT, monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_programs()


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    Store(ws).init()
    return ws


def _fired_program(ws: pathlib.Path, pid: int) -> str:
    timer = CLK.start_program(ws, program="python", argv=["x.py"], task_id="t-000002",
                              role="E", pid=pid)
    CLK.finish_program(ws, timer.timer_id, outcome="exited", exit_code=0, elapsed_sec=1.2)
    return timer.timer_id


def test_a_reused_pid_is_not_read_as_alive(tmp_path: pathlib.Path, bench,
                                          monkeypatch: pytest.MonkeyPatch):
    """正题：复用号（创建时刻晚于落账）⇒ 不进闸，且读数点名。"""
    ws = _ws(tmp_path)
    tid = _fired_program(ws, os.getpid())
    # 复用号：这个号现在挂着的是"另一台程序"
    monkeypatch.setattr(CD, "_process_image_name", lambda pid: "chrome", raising=True)
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["running_count"] == 0, got["running"]
    row = next(r for r in got["rows"] if str(r.get("timer_id")) == tid)
    assert row["pid_reused"] is True, row
    assert row["alive"] is False, row


def test_a_genuinely_live_program_still_blocks(tmp_path: pathlib.Path, bench,
                                              monkeypatch: pytest.MonkeyPatch):
    """正控：真活着（创建时刻早于落账）⇒ 照旧进闸（闸一个字没放宽）。"""
    ws = _ws(tmp_path)
    _fired_program(ws, os.getpid())
    monkeypatch.setattr(CD, "_process_image_name", lambda pid: "python", raising=True)
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["running_count"] == 1, got["running"]
    row = next(r for r in got["rows"] if r.get("pid") == os.getpid())
    assert row["pid_reused"] is False and row["alive"] is True, row


def test_an_unreadable_creation_time_keeps_blocking(tmp_path: pathlib.Path, bench,
                                                    monkeypatch: pytest.MonkeyPatch):
    """反真空：创建时刻读不到 ⇒ 维持进闸（"没读到"不许折成"没在跑"）。"""
    ws = _ws(tmp_path)
    _fired_program(ws, os.getpid())
    monkeypatch.setattr(CD, "_process_image_name", lambda pid: None, raising=True)
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["running_count"] == 1, got["running"]
