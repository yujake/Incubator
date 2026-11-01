# -*- coding: utf-8 -*-
"""判据：召唤登记之前的"自愈"必须把"台账有、名册没有"的代理行补上。

## 真机（2026-10-29，paper-rewrite-80）

M 的名册 `out/roster/t-000001.jsonl` 只有 5 行（A1/A2/D1/D2/D3），台账里却有 8 个孩子：
`t-000012`/`t-000013`/`t-000014` 三条 D 实例（`instance="D#1"…`）`parent_task_id=t-000001`，
父名册里一行都没有 ⇒ 页面报"未落名册的子"。

`Secretary.roster_repair(owner)` 正是补这一档的自愈口，但此前一个调用点都没有
（全仓只有定义）。现在它挂在 `Conductor._register_roster` 的登记之前：
每次有人往这个父名册里登记，先把漏掉的补上。

## 这一组守什么

1. 正题：父名下先存在一条"没进名册"的代理行 ⇒ 走一次登记之后它进了名册；
2. 反真空：同样的行、只调 `roster_add` 不走自愈 ⇒ 它仍然不在名册里。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str]:
    """一个工作区 + 一个顶趟行（父）；返回 `(conductor, 父编号)`。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    # 秘书要拿到同一把 store 才能读台账（`Secretary._conductor` 就是这么造的）
    cond.secretary = Secretary("M", root=ws, store=st)
    cond.roster_sink = cond.secretary
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top)


def _orphan(cond: Conductor, parent: str) -> str:
    """在台账里造一条"有父、没进名册"的代理行（实例分派那条路留下的形态）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": "", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "D#1", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="probe:orphan")


def test_a_repair_before_registration_fills_the_hole(tmp_path: pathlib.Path) -> None:
    """正题：登记前自愈 ⇒ 那条漏掉的代理行进了父名册。"""
    cond, parent = _env(tmp_path)
    orphan = _orphan(cond, parent)
    rec = cond._register_roster(task_id="t-999999", role="D", owner=parent,
                                meta={"brief": "研究包", "task": "做一件研究"})
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    ids = {str(r.get("task_id")) for r in rows}
    assert orphan in ids, (orphan, rows)
    assert "t-999999" in ids, (rec, rows)


def test_one_summon_makes_exactly_one_roster_row(tmp_path: pathlib.Path) -> None:
    """（C-c）一次召唤恰好一行：instance 扇出 3 条 ⇒ 父名册 3 行、名字不跳号。

    这条钉的是我上一版兜底位置放错的形态：自愈跑在 `roster_add` 之前时，
    `_write_new_row` 刚写进台账、还没进名册的那一条会被自愈当成"漏掉的"补一次，
    于是同一条子行在名册里出现两行（实测 D1|t-000002 与 D2|t-000002，名字跳成 D2/D4/D6）。
    """
    cond, parent = _env(tmp_path)
    made = []
    for i, label in enumerate(("D#1", "D#2", "D#3"), start=1):
        start = cond.summon_begin("D", "research", {"qid": str(i)},
                                  parent_task_id=parent, instance=label,
                                  roster={"brief": f"研究包{i}", "task": "做一件研究"})
        assert start.task_id, start
        made.append(str(start.task_id))
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    ids = [str(r.get("task_id")) for r in rows]
    assert sorted(ids) == sorted(made), (ids, made)      # 每个编号恰好一行
    assert len(ids) == len(set(ids)), ids                # 没有重复行
    names = sorted(str(r.get("name")) for r in rows)
    assert names == ["D1", "D2", "D3"], names            # 名字连续、不跳号


def test_the_backstop_is_not_the_fix(tmp_path: pathlib.Path) -> None:
    """（C-d）把兜底自愈打桩成 no-op ⇒ 上面那条仍然成立（治本不依赖兜底）。"""
    cond, parent = _env(tmp_path)
    cond.secretary.roster_repair = lambda **kw: (0, "", [])  # type: ignore[assignment]
    made = []
    for i in range(1, 4):
        start = cond.summon_begin("D", "research", {"qid": str(i)},
                                  parent_task_id=parent, instance=f"D#{i}",
                                  roster={"brief": f"研究包{i}", "task": "做一件研究"})
        assert start.task_id, start
        made.append(str(start.task_id))
    rows, _ = cond.secretary.roster_rows(parent)
    ids = [str(r.get("task_id")) for r in rows]
    assert sorted(ids) == sorted(made), (ids, made)


def test_without_the_repair_the_hole_stays(tmp_path: pathlib.Path) -> None:
    """反真空：只登记、不走自愈 ⇒ 那条代理行仍然不在名册里。"""
    cond, parent = _env(tmp_path)
    orphan = _orphan(cond, parent)
    cond.secretary.roster_add(owner=parent, role="D", task_id="t-999998",
                              brief="研究包", task="做一件研究", new="D")
    rows, _ = cond.secretary.roster_rows(parent)
    ids = {str(r.get("task_id")) for r in rows}
    assert orphan not in ids, (orphan, rows)
    assert "t-999998" in ids, rows
