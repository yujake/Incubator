# -*- coding: utf-8 -*-
"""判据：账上已收口的程序（`outcome=exited`）不许再挡销号/收工闸。

## 真机（2026-10-28 `projects/paper-rewrite-78c` 收工，M 的 `CLOSE-OUT-BLOCKER.md`）

```
E1 的 extract_pdf.py（pid 24780）账上 state=fired / outcome=exited / exit_code=0 / 1.2 秒，
但读数里 live=true ⇒ 挡着 E1 销号；而 program.stop 从 M 侧回「我名下没有还在跑的程序」
（归属在 E1，M 不能停）⇒ 销号闸解不开，整趟只能 final_refused。
```

两件事叠在一起：

1. `live = (state == "pending") or alive` 把"账上已收口、pid 探活为真"也算进闸 —— 而
   `programs_reading` 自己的 docstring 写着 `orphans`（含 `finished_but_alive`）
   "只进读数、不进任何闸"：同一份读数里两处口径打架；
2. Windows 的 pid 会被复用，"账上收口而 pid 活着"很多时候根本不是那个进程（1.2 秒就
   exit_code=0 的脚本尤其如此）⇒ 这一格既挡人又不可靠。

## 修法（把"进闸"与"读数"两格分开）

- `live`（进闸那一格）= `state == "pending"`（账上说它还在跑）；
- "账上收口而 pid 还活着"仍然如实读出来：`alive=True` + `finished_but_alive=True` +
  进 `orphans.finished_but_alive`（M 的巡查看得到），但不再挡销号/收工。

## 这一组守什么

1. 收口且 pid 活着（用本进程 pid 造）⇒ `running_count == 0`、行上 `live=False` 而
   `alive=True`、并进 `orphans.finished_but_alive`；
2. 正控：`state="pending"` 的程序 ⇒ `running_count == 1`（真在跑的那一档不许被放宽）；
3. 无主（`task_id` 空）程序照旧单列 `unowned`，不进 `running`。
"""
from __future__ import annotations

import os
import pathlib

import pytest

from agentflow import clock as CLK
from agentflow.conductor import programs_reading
from agentflow.store import Store


@pytest.fixture()
def bench():
    CLK.reset()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall="2026-10-28T09:00:00+00:00", monotonic=1000.0))
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


def test_a_finished_program_does_not_block_the_close_out(tmp_path: pathlib.Path, bench):
    """正题：账上收口、pid 活着 ⇒ 不进闸（但读数里看得见）。"""
    ws = _ws(tmp_path)
    timer = CLK.start_program(ws, program="python", argv=["x.py"], task_id="t-000002",
                              role="E", pid=os.getpid())
    CLK.finish_program(ws, timer.timer_id, outcome="exited", exit_code=0, elapsed_sec=1.2)
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["checked"] is True, got
    assert got["running_count"] == 0, got["running"]
    row = next(r for r in got["rows"] if str(r.get("timer_id")) == timer.timer_id)
    assert row["live"] is False, row
    assert row["alive"] is True, row
    assert row["finished_but_alive"] is True, row
    assert [str(x.get("timer_id")) for x in got["orphans"]["finished_but_alive"]] == \
        [timer.timer_id], got["orphans"]


def test_a_pending_program_still_blocks(tmp_path: pathlib.Path, bench):
    """正控：真的在跑（`state=pending`）⇒ 照旧进闸，一条都不许放宽。"""
    ws = _ws(tmp_path)
    CLK.start_program(ws, program="python", argv=["y.py"], task_id="t-000002", role="E",
                      pid=os.getpid())
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["running_count"] == 1, got["running"]
    row = next(r for r in got["rows"] if str(r.get("live")) == "True")
    assert row["live"] is True, row


def test_an_unowned_program_is_listed_apart(tmp_path: pathlib.Path, bench):
    """无主程序：进 `unowned`，不进这一支的 `running`（谁的活谁认领）。"""
    ws = _ws(tmp_path)
    CLK.start_program(ws, program="python", argv=["z.py"], pid=os.getpid())
    got = programs_reading(ws, task_ids=["t-000002"])
    assert got["running_count"] == 0, got["running"]
    assert got["unowned_count"] == 1, got["unowned"]
