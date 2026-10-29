# -*- coding: utf-8 -*-
"""判据：父给的名字撞车时，登记不许失败 —— 改用框架顺延发的名字。

## 真因（2026-10-29，paper-rewrite-80，盘上证据）

M 第二批扇出沿用了第一批的名字：

```
第一批 targets： name=D1 instance=engine / name=D2 instance=detector / name=D3 instance=assembly
第二批 targets： name=D1 instance=''     / name=D2 instance=''         / name=D3 instance=''
```

`D1/D2/D3` 已经绑在第一批那三个 task_id 上 ⇒ 秘书按"用过的名字不再发给另一个子代理"
受控拒绝（实测 problem 原文：「D1 已经用过（已收口或还在用）⇒ 受控拒绝：用过的名字
不再发给另一个子代理」）⇒ 第二批三条子代理台账有、名册没有，页面报"未落名册的子"。

而这次拒绝只经 `Conductor._log`，本配置没有日志钩子 ⇒ 盘上一点痕迹都没有。

## 这一组守什么

1. 正题：名字被占用时登记仍然成功（改用顺延名），父名册里两条任务各有一行；
2. 反真空：同样的场景、但只调 `roster_add`（不走漏斗的改名补救）⇒ 第二条登记不进去。
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


def test_a_taken_name_falls_back_to_a_fresh_one(tmp_path: pathlib.Path) -> None:
    """正题：名字被占用 ⇒ 改用顺延名登记，两条任务各占一行。"""
    cond, parent = _env(tmp_path)
    rec1 = cond._register_roster(task_id="t-000009", role="D", owner=parent,
                                 meta={"name": "D1", "brief": "研究包A", "task": "做研究"})
    assert rec1.get("problem") == "", rec1
    rec2 = cond._register_roster(task_id="t-000012", role="D", owner=parent,
                                 meta={"name": "D1", "brief": "研究包B", "task": "做研究"})
    assert rec2.get("problem") == "", rec2
    assert rec2.get("name") and rec2.get("name") != "D1", rec2
    assert "已经绑在别的子代理上" in str(rec2.get("note") or ""), rec2
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    ids = {str(r.get("task_id")) for r in rows}
    assert ids == {"t-000009", "t-000012"}, rows


def test_without_the_fallback_the_second_row_is_lost(tmp_path: pathlib.Path) -> None:
    """反真空：只调 roster_add（不走改名补救）⇒ 第二条登记不进去。"""
    cond, parent = _env(tmp_path)
    first = cond.secretary.roster_add(owner=parent, role="D", task_id="t-000009",
                                      brief="研究包A", task="做研究", want_name="D1")
    assert first.get("problem") == "", first
    second = cond.secretary.roster_add(owner=parent, role="D", task_id="t-000012",
                                       brief="研究包B", task="做研究", want_name="D1")
    assert second.get("problem"), second       # 需要走到这里：名字确实被拒
    rows, _ = cond.secretary.roster_rows(parent)
    assert {str(r.get("task_id")) for r in rows} == {"t-000009"}, rows
