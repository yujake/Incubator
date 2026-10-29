# -*- coding: utf-8 -*-
"""判据（C-a）：真实栈里 instance 扇出 3 个 ⇒ 读侧 `coverage.unrostered == 0`。

这是业主在页面上看到的那个读数（"未落名册的子"）。前面几条判的是写侧逐行对得上，
这一条专门钉页面读的那个数：扇出之后它就是 0，不需要谁事后去补。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R


def test_the_page_reads_zero_unrostered_after_a_fan_out(tmp_path: pathlib.Path) -> None:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st)
    cond.roster_sink = cond.secretary
    parent = str(cond.open_top_level_run("M", "顶趟这一趟"))
    for i in range(1, 4):
        start = cond.summon_begin("D", "research", {"qid": str(i)},
                                  parent_task_id=parent, instance=f"D#{i}",
                                  roster={"brief": f"研究包{i}", "task": "做一件研究"})
        assert start.task_id, start
    face = R.roster_face(ws)
    coverage = face.get("coverage") or {}
    assert int(coverage.get("unrostered") or 0) == 0, (coverage, face.get("nodes"))
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    assert len(rows) == 3, rows
