# -*- coding: utf-8 -*-
"""判据（端到端）：执行侧真的把"同号继续"做出来 —— 不新建行、名册与名字不动。

前面的判据钉的是"要不要叫醒"的判定；这一条钉 `Conductor.resume_dispatched`
（判定之后那个默认执行侧）真的：
1. 把同一行的 status 由 done 改回 running（然后后台跑，跑完写回终态）；
2. 不新建 tasks 行、不动名册行数与名字（业主：「它的号还在就一直用」）。

用一个只回固定 payload 的后端替身，避免真起角色循环。
"""
from __future__ import annotations

import pathlib
import time

from agentflow.conductor import Conductor
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


class _Backend:
    """只回一条 payload 的后端替身（`call` 的签名与真后端一致）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call(self, role, action, params, *, token=None, instance="", task_id=""):
        self.calls.append({"role": role, "action": action, "task_id": task_id})
        return {"status": "done", "outcome": "ok", "detail": "被叫起来之后干完了",
                "payload": None, "artifacts": [], "tokens": 0, "usd": 0.0}


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    be = _Backend()
    cond = Conductor(st, policy=None, backend=be)
    cond.secretary = Secretary("M", root=ws, store=st)
    cond.roster_sink = cond.secretary
    parent = str(cond.open_top_level_run("M", "顶趟这一趟"))
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@x", "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "D#1",
        "detail": "研究包已交回", "error": None, "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="probe:child")
    return cond, parent, child


def test_the_same_row_is_continued_not_a_new_one(tmp_path: pathlib.Path) -> None:
    cond, parent, child = _env(tmp_path)
    before_tasks = len(cond._tasks())
    before_roster, _ = cond.secretary.roster_rows(parent)
    got = cond.resume_dispatched(child, role="D", item_id="t-000099", kind="message",
                                 previous_status="done")
    assert got.get("started") is True, got
    assert "同号继续" in str(got.get("reason") or ""), got
    # 等后台那一段落定（替身后端只回一条 payload，很快）
    for _ in range(200):
        row = cond._task(child) or {}
        if str(row.get("status")) != "running":
            break
        time.sleep(0.02)
    row = cond._task(child) or {}
    assert str(row.get("status")) == "done", row          # 跑完写回终态
    assert len(cond._tasks()) == before_tasks, "不许新建 tasks 行"
    after_roster, _ = cond.secretary.roster_rows(parent)
    # 名册一行都不许多、也不许改（这一条只钉"号还在就一直用"）
    assert [str(r.get("task_id")) for r in after_roster] == \
        [str(r.get("task_id")) for r in before_roster], (after_roster, before_roster)
