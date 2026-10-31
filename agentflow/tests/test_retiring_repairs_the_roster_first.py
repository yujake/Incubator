# -*- coding: utf-8 -*-
"""判据（D）：销号之前补名册 —— "台账有、名册没有"的那条，销号时先拿到名字。

真机形态（2026-10-29 paper-rewrite-80 / 79 都是同一个）：子行在台账里
`parent_task_id=<父>`、名册里一行都没有 ⇒ 父没有名字可用，`secretary.retire(name=…)`
连对象都解析不到（79 那趟 11 个节点卡住的那一档）。

分工：治本在登记侧（一件活登记一次；撞名字 ⇒ `name_taken` 受控拒绝，交父决定，
框架不替它换名 —— 2026-11-02 按 `4e2963b4` 更正；旧说法把撞名写成"框架替你换一个号
继续登记"，已经删掉），兜底在这里 —— 销号是"这一支要收口"的时刻。

这一组守什么：
1. 正题：父名下有一条没进名册的代理行 ⇒ 调一次 `retire(...)`（哪怕它先因为别的理由被拒）
   之后，那条已经在父名册里、能解析到名字；
2. 反真空：同样的行、不调 `retire` ⇒ 名册里仍然没有它（证明正题不是恒真）。
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


def _orphan(cond: Conductor, parent: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@x", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "D#1", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="probe:orphan")


def test_retiring_repairs_the_roster_first(tmp_path: pathlib.Path) -> None:
    """正题：销号入口先补名册，那条漏行有了名字。"""
    cond, parent = _env(tmp_path)
    orphan = _orphan(cond, parent)
    before, _ = cond.secretary.roster_rows(parent)
    assert not before, before                       # 起点：名册里一条都没有
    got = cond.secretary.retire(owner=parent, name="谁都不叫这个名字", by_task_id=parent)
    assert got.get("ok") is False, got              # 名字不存在 ⇒ 仍然被拒（不许当"退过了"）
    after, _ = cond.secretary.roster_rows(parent)
    assert {str(r.get("task_id")) for r in after} == {orphan}, after


def test_without_retire_the_hole_stays(tmp_path: pathlib.Path) -> None:
    """反真空：不调销号入口 ⇒ 名册里仍然没有那条。"""
    cond, parent = _env(tmp_path)
    orphan = _orphan(cond, parent)
    rows, _ = cond.secretary.roster_rows(parent)
    assert {str(r.get("task_id")) for r in rows} != {orphan}, rows
    assert not rows, rows
