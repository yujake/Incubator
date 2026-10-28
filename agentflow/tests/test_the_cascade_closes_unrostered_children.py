# -*- coding: utf-8 -*-
"""判据：连锁销号必须把"没名字的那个孩子"也收口（认边），否则收工闸永远过不去。

## 真机（2026-10-28 `projects/paper-rewrite-78c` 收工）

M 反复调 `conductor.retire_child`（级联），但 50 个代理行里只有 8 个在名册上、42 个没有
（V×19、B×14、G×4、A×2、E/F/H 各 1，全部 `done`）—— 那 42 个"未登记名册 ⇒ 没有名字可销"，
级联把它们跳过；而 `retire_integrity` 数的是子树里没被父认过的代理行 ⇒ 永远
`complete=False` ⇒ 3 次 `final_refused`。

业主口径：「任何一位父代理做『销号』时实际上都是要用连锁销号，单个销号会留下野孩子」。

## 修法

级联走到"名册里没有它"那一档时，不只记一笔 `unrostered` 就跳过 —— 还要写一条
认边（`Conductor.note_edge_release`，幂等；它自己核"子存在 / 父对 / 子不在跑"），
那正是 `retire_integrity` 读的那一格。名字没有、销号名单里没有它，但这条边从此被父认过。

## 这一组守什么

1. 正题：父 → 有名册名的子 → 没名册名的孙（都已 `done`）⇒ 级联之后
   `retire_integrity` 的 `complete` 为真；
2. 孙那一项在 `cascade` 里带 `edge_released=True`（读数看得见"它是被认边收口的"）；
3. 反真空：那个孙还在跑（`running`）⇒ 不许认边（`note_edge_release` 自己拒），
   于是 `complete` 仍为假。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry

TASK = "连锁销号"


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.roster_sink = Secretary("M", root=ws, store=st)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reg.bound_role = "M"
    return st, cond, reg, ws


def _agent(cond: Conductor, parent: str, *, role: str = "D", status: str = "done") -> str:
    ended = None if status in ("pending", "running") else "2026-10-28T09:00:05+08:00"
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"cascade@{role}",
        "status": status, "outcome": ("ok" if ended else None), "refusal_reason": None,
        "instance": "", "detail": "干完了", "error": None,
        "started_at": "2026-10-28T09:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}")


def _tree(tmp_path: pathlib.Path, *, grand_status: str = "done"):
    st, cond, reg, ws = _env(tmp_path)
    top = cond.open_top_level_run("M", TASK)
    child = _agent(cond, top, role="D")
    got = cond.roster_sink.roster_add(owner=top, role="D", task_id=child,
                                      brief="", task="干一件活", want_name="D1")
    assert got.get("problem") == "", got
    grand = _agent(cond, child, role="V", status=grand_status)
    return st, cond, reg, ws, top, child, grand


def test_the_cascade_closes_an_unrostered_grandchild(tmp_path: pathlib.Path):
    """正题：没名字的孙也要被认边收口 ⇒ `retire_integrity` 能 complete。"""
    st, cond, reg, ws, top, child, grand = _tree(tmp_path)
    with calling_as(top):
        res = reg.call("conductor.retire_child", child_name="D1", reason="收工")
    data = dict(res.data or {})
    assert data.get("retired") is True, data
    rows = [c for c in (data.get("cascade") or []) if str(c.get("task_id")) == grand]
    assert rows, data.get("cascade")
    assert rows[0].get("edge_released") is True, rows[0]
    integrity = cond.retire_integrity(top)
    assert integrity.get("complete") is True, integrity.get("nodes")


def test_a_running_grandchild_is_not_papered_over(tmp_path: pathlib.Path):
    """反真空：孙还在跑 ⇒ 不许认边（`note_edge_release` 自己拒）⇒ 仍不 complete。"""
    st, cond, reg, ws, top, child, grand = _tree(tmp_path, grand_status="running")
    with calling_as(top):
        res = reg.call("conductor.retire_child", child_name="D1", reason="收工")
    data = dict(res.data or {})
    rows = [c for c in (data.get("cascade") or []) if str(c.get("task_id")) == grand]
    if rows:
        assert rows[0].get("edge_released") is not True, rows[0]
    integrity = cond.retire_integrity(top)
    assert integrity.get("complete") is not True, integrity.get("nodes")
