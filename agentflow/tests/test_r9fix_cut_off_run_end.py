# -*- coding: utf-8 -*-
"""R9FIX · D8：父的退场结算也要给子这一趟补一条 `agent_run_end`。

## 改前红（真机 lp-ball-9，V 的 t-000186 / t-000191）

两趟都只有 `agent_run_start`，没有 `agent_run_end` / `spend_usd`；`tasks` 行却是
`done + cut_off_by_parent`。`sessions.runs_in_session` 因此把 `spend_usd` 读成
`None`（不是 0），会话口径的 `unattributed_usd_of` 里 V 那 $0.615 没有主人。

根因：`AgentLoop._write_children_cut_off` 只写 `tasks` 行，不写会话收工行；
子线程被父的退场掐断，它自己那一行永远不会来。

## 反真空

1. 收工行必须带 `task_id`（否则 `runs_in_session` 配不上那一趟）；
2. 花销从账本抄（与 `tasks.usd` 同源），不是 0；
3. `settled_by=parent_exit` 说清是谁写的 —— 它不许冒充子代理自己的收工行。
"""
from __future__ import annotations

import pathlib

from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow.conductor import Conductor
from agentflow.store import Store


def _running_child(store: Store, tid: str, *, usd: float = 0.25,
                   role: str = "V", usage_id: str = "000001") -> None:
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": tid, "role": role, "action": "", "called_by": "F",
            "parent_task_id": "t-000001", "depth": 2, "input_key": f"@{tid}",
            "status": "running", "outcome": None, "refusal_reason": None,
            "instance": "", "detail": "", "error": None,
            "started_at": "2026-11-19T09:51:46+08:00", "ended_at": None,
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        })
    # 真机的现场：子代理开跑时落过 `agent_run_start`（缺的是收工那一行）。
    SS.append(store.root, {"kind": "agent_run_start", "role": role,
                           "task_id": tid}, sid="s1")
    with store.tx("usage_ledger", actor="test") as tx:
        tx.upsert("usage_ledger", {
            "usage_id": usage_id, "at": "2026-11-19T09:52:00+08:00",
            "task_id": tid, "scope": "reason", "usd": usd,
            "tokens_total": 10, "attempts": 1, "idem_key": f"k-{tid}",
        })


def _cut_off(root: pathlib.Path, store: Store, cond: Conductor,
             tids: list[str]):
    loop = AL.AgentLoop.__new__(AL.AgentLoop)
    loop.conductor = cond
    loop.session_root = root
    loop.sid = "s1"
    loop.store = store
    run = type("Run", (), {"cut_off_children": [], "notes": []})()
    out = AL.AgentLoop._write_children_cut_off(loop, tids, run=run)
    return out, run


def test_parent_exit_writes_a_run_end_with_spend_for_the_cut_off_child(
        tmp_path: pathlib.Path):
    """改前：`runs_in_session` 里这一趟 `end_index=None`、`spend_usd=None`。"""
    store = Store(tmp_path)
    store.init()
    cond = Conductor(store, registry={})
    _running_child(store, "t-000002")

    out, _run = _cut_off(tmp_path, store, cond, ["t-000002"])
    assert out["written"] == ["t-000002"], out

    events, _problems = SS.read_session(tmp_path, "s1")
    runs = SS.runs_in_session(events, sid="s1")
    mine = [r for r in runs if r["task_id"] == "t-000002"]
    assert len(mine) == 1, runs
    row = mine[0]
    assert row["end_index"] is not None, row
    assert row["stop_reason"] == "cut_off_by_parent", row
    assert row["spend_usd"] == 0.25, row
    assert row["spend_unknown_usd_calls"] == 0, row
    assert row["llm_calls"] == 1, row

    end = [e for e in events if e.get("kind") == "agent_run_end"
           and e.get("task_id") == "t-000002"]
    assert len(end) == 1 and end[0].get("settled_by") == "parent_exit", end
    assert end[0].get("synthetic") is True, end


def test_each_cut_off_child_gets_its_own_end_event(tmp_path: pathlib.Path):
    """两趟被掐断 ⇒ 两条收工行，各自的 task_id 与花销（不许并成一条）。"""
    store = Store(tmp_path)
    store.init()
    cond = Conductor(store, registry={})
    _running_child(store, "t-000002", usd=0.25)
    _running_child(store, "t-000003", usd=0.5, role="D", usage_id="000002")

    out, run = _cut_off(tmp_path, store, cond, ["t-000002", "t-000003"])
    assert sorted(out["written"]) == ["t-000002", "t-000003"], out
    assert sorted(run.cut_off_children) == ["t-000002", "t-000003"], run.cut_off_children

    events, _problems = SS.read_session(tmp_path, "s1")
    ends = {e["task_id"]: e for e in events if e.get("kind") == "agent_run_end"}
    assert set(ends) == {"t-000002", "t-000003"}, ends
    assert ends["t-000002"]["spend"]["usd"] == 0.25, ends
    assert ends["t-000003"]["spend"]["usd"] == 0.5, ends
