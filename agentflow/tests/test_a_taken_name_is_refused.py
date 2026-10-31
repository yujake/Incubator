# -*- coding: utf-8 -*-
"""判据：父给的名字撞车时，登记必须受控拒绝（name_taken），不许静默顺延换名。

## 业主 2026-11-02 的裁定（`draft/150` §5.2-④）

改前 `Conductor._register_roster` 在 `want_name` 被占用时替父改主意：改发一个
顺延的新名字继续登记，只把换名写进 `note`。业主裁定去掉这条兜底 —— 撞名 = 受控
拒绝（`name_taken`），交父决定。它与名册写口"用过的名字不再发给另一个子代理"
是同一条口径的两端。

改前读数（`temp/probe_roster_one_row.py` G）：第二次登记回 `name=D2`、`problem=""`，
note 写「父给的名字 D1 已经绑在别的子代理上 ⇒ 改用框架顺延发的 D2」。

## 这一组守什么

1. 正题：第二次给 `D1` ⇒ `problem` 含 `name_taken`、`state="missing"`、名册只有一行；
2. 反真空：被拒的那一条也没有被兜底自愈换个名字补上（那个 `task_id` 在名册里 0 行）。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st)
    cond.roster_sink = cond.secretary
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top)


def test_a_taken_name_is_refused_not_renamed(tmp_path: pathlib.Path) -> None:
    """正题：名字被占用 ⇒ `name_taken` 受控拒绝，不许再发一个顺延名。"""
    cond, parent = _env(tmp_path)
    rec1 = cond._register_roster(task_id="t-000009", role="D", owner=parent,
                                 meta={"name": "D1", "brief": "研究包A", "task": "做研究"})
    assert rec1.get("problem") == "", rec1
    assert str(rec1.get("name")) == "D1", rec1
    rec2 = cond._register_roster(task_id="t-000012", role="D", owner=parent,
                                 meta={"name": "D1", "brief": "研究包B", "task": "做研究"})
    assert rec2.get("problem"), rec2
    assert "name_taken" in str(rec2.get("problem")), rec2
    assert str(rec2.get("state") or "") == "missing", rec2
    assert str(rec2.get("refusal_code") or "") == "name_taken", rec2
    assert "顺延发" not in str(rec2.get("note") or ""), rec2
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    assert [(str(r.get("name")), str(r.get("task_id"))) for r in rows] == [("D1", "t-000009")], rows


def test_the_second_task_is_not_smuggled_in_by_the_repair(tmp_path: pathlib.Path) -> None:
    """反真空：被拒的那一条也不许被兜底自愈换个名字补上。"""
    cond, parent = _env(tmp_path)
    first = cond.secretary.roster_add(owner=parent, role="D", task_id="t-000009",
                                      brief="研究包A", task="做研究", want_name="D1")
    assert first.get("problem") == "", first
    second = cond.secretary.roster_add(owner=parent, role="D", task_id="t-000012",
                                       brief="研究包B", task="做研究", want_name="D1")
    assert second.get("problem"), second
    assert str(second.get("refusal_code") or "") == "name_taken", second
    rows, _ = cond.secretary.roster_rows(parent)
    assert [(str(r.get("name")), str(r.get("task_id"))) for r in rows] == [("D1", "t-000009")], rows
    assert "t-000012" not in {str(r.get("task_id")) for r in rows}, rows
