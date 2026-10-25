# -*- coding: utf-8 -*-
"""六条补线的读侧判据：每一格都必须真的由一只活工具念出来，且打桩成空之后会红。

## 这一份守的是什么

`docs/WIRING-AUDIT-2026-10-27.md` 第七节量到的六条 ORPHAN 是同一族：

    函数写好了、单测也绿了，但没有任何活路径会把那一格读数念给人看。

补线的落点是读数面（`clock.now` / `clock.wait_any` / `conductor.watch` /
`conductor.ledger` / `conductor.status_report`）加一格，或者循环的判据里加一句。
于是这一份判据只问两件事：

1. 那一格真的在：调那只工具，data 里点名的键存在，且它的值来自那条被判据
   （不是写死的常量 —— 例如 `programs.running` 必须随程序起落变化）；
2. 反真空：把产生那一格的那条路打桩成"什么也没有"，同一个断言必须红。
   少了这一条，"读数里真有这一格"可以靠一个恒返回空表的实现骗过去。

六条逐条对应（编号与审计第七节同一套）：

| # | 项 | 补线落点（读数面） |
|---|---|---|
| 1 | `programs` | `clock.now` 的 `programs`（checked / count / running / rows） |
| 2 | `program_census` | `clock.now` 的 `programs_outside_clock`（与 `waits_outside_clock` 同族） |
| 3 | `read_wait_any` | `clock.wait_any` 的 `intents`（全量意图账） |
| 4 | `cancel_wait_any` | `agent_loop._park_gate` 回模型那一拍撤意图（`run.park.wait_cancelled`） |
| 5 | `handoffs_reading` | `conductor.watch` / `conductor.ledger` 的 `silent_children` |
| 6 | `child_wait_invariant` | `conductor.watch` / `conductor.status_report` 的 `child_wait_invariant` |

## 边界

全部 tmp 工作区、假时钟、替身模型（零模型钱）；程序那一条用的是 `program_span`
的登记面（不真起进程），`program_census` 那一条用的是打桩的普查结果。
"""
from __future__ import annotations

import pathlib
import time
from typing import Any

import pytest

from agentflow import clock as CLK
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from _d68_board_fixture import children_clean_their_boards  # noqa: E402 - D-68 夹具助手

TASK = "六条补线的读侧判据（业主 2026-10-27 第二批）"


# ------------------------------------------------------------------ 夹具

@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（挂机视图/程序账/交差账都是进程级的）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    CLK.set_census_roots(None)
    fake = CLK.use(CLK.FakeClock(wall="2026-10-27T09:00:00+00:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()
        CLK.reset_programs()
        CLK.set_census_roots(None)


def _ws(tmp_path: pathlib.Path, name: str) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    children_clean_their_boards(cond)
    CLK.set_default_workspace(ws)
    return st, cond, ws


def _reg(st: Store, cond: Conductor, ws: pathlib.Path):
    return build_registry(store=st, conductor=cond, workspace_root=ws).registry


def _child(cond: Conductor, parent: str, key: str = "readouts@child") -> str:
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-27T09:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


class _Run:
    """`_park_gate` 只往 `run.park` / `run.notes` 上写，别的一格都不读。"""

    def __init__(self) -> None:
        self.park: dict[str, Any] = {}
        self.notes: list[str] = []


# ================================================================== 1 programs

def test_programs_are_visible_on_clock_now(tmp_path, bench, monkeypatch) -> None:
    """① 程序计时器的现读在 `clock.now` 的 `programs` 那一格（起落要跟着变）。"""
    st, cond, ws = _ws(tmp_path, "programs")
    reg = _reg(st, cond, ws)
    before = reg.call("clock.now", role="M").data
    assert before["programs"]["checked"] is True, before["programs"]
    assert before["programs"]["running"] == 0, before["programs"]

    timer = CLK.start_program(ws, program="probe-prog", argv=["probe-prog", "--x"],
                              task_id="t-probe", role="M")
    mid = reg.call("clock.now", role="M").data["programs"]
    assert mid["count"] == 1 and mid["running"] == 1, mid
    row = dict(mid["rows"][0])
    for key in ("program", "pid", "elapsed_sec", "state"):
        assert key in row, (key, sorted(row))
    assert row["program"] == "probe-prog" and row["state"] == "pending", row

    CLK.finish_program(ws, timer.timer_id, outcome="exited", exit_code=0)
    after = reg.call("clock.now", role="M").data["programs"]
    assert after["running"] == 0 and after["count"] == 1, after
    assert dict(after["rows"][0])["state"] == "fired", after["rows"][0]

    # 反真空：把程序那一格打桩成"永远空" ⇒ 同一个断言必须红。
    monkeypatch.setattr(CLK, "programs", lambda _ws: {
        "checked": True, "rows": [], "count": 0, "running": 0,
        "unbooked": [], "reason": "判据：打桩成空"})
    CLK.start_program(ws, program="probe-prog2", argv=["probe-prog2"], task_id="t-probe",
                      role="M")
    stubbed = reg.call("clock.now", role="M").data["programs"]
    assert stubbed["running"] == 0, ("打桩成空之后仍读到了程序 ⇒ 那一格不是从这里来的",
                                     stubbed)


# ================================================================== 2 program_census

def test_programs_outside_clock_is_on_the_coverage_readout(tmp_path, bench,
                                                           monkeypatch) -> None:
    """② `program_census` 的 findings 数折进 `coverage()`（`clock.now` 也念它）。"""
    st, cond, ws = _ws(tmp_path, "pcensus")
    reg = _reg(st, cond, ws)
    data = reg.call("clock.now", role="M").data
    assert data["programs_checked"] is True, data["programs_files_scanned"]
    assert data["programs_outside_clock"] == 0, data["programs_outside_where"]
    assert isinstance(data["programs_outside_where"], list), data["programs_outside_where"]

    # 反真空：让普查报两处"起进程没进账" ⇒ 同一格必须变成 2（证明它读的是普查，
    # 不是一个恒 0 的常量）。
    monkeypatch.setattr(CLK, "program_census", lambda **_kw: {
        "checked": True, "files": 7,
        "findings": [{"where": "a.py:1（f）"}, {"where": "b.py:2（g）"}],
        "governed": [], "spans": [], "unbooked": [], "reason": ""})
    got = CLK.coverage(refresh=True)
    assert got["programs_outside_clock"] == 2, got
    assert got["programs_outside_where"] == ["a.py:1（f）", "b.py:2（g）"], got

    # 普查"没查成"⇒ 这一格是 None，不是 0（三态不许折平）。
    monkeypatch.setattr(CLK, "program_census", lambda **_kw: {
        "checked": False, "files": 0, "findings": [], "governed": [], "spans": [],
        "unbooked": [], "reason": "判据：读不成"})
    broke = CLK.coverage(refresh=True)
    assert broke["programs_outside_clock"] is None, broke
    assert broke["programs_checked"] is False, broke


# ================================================================== 3 read_wait_any

def test_wait_any_hands_back_every_intent_in_the_workspace(tmp_path, bench,
                                                           monkeypatch) -> None:
    """③ `clock.wait_any` 的 `intents` 是那一本全量意图账（不只是自己那一条）。"""
    st, cond, ws = _ws(tmp_path, "waitany-read")
    reg = _reg(st, cond, ws)
    me = cond.open_top_level_run("M", TASK)
    other = _child(cond, me)
    CLK.request_wait_any(ws, task_id=other, role="D", purpose="别人的等待意图")

    with calling_as(me, "M"):
        got = reg.call("clock.wait_any", role="M", purpose="我这一趟的等待意图")
    data = dict(got.data)
    assert data["checked"] is True, data
    assert data["wait_id"], data
    assert data["requested"] is True, data
    intents = dict(data["intents"])
    assert intents["checked"] is True, intents
    assert intents["count"] >= 2, intents
    ids = sorted(str(r.get("task_id") or "") for r in intents["rows"])
    assert me in ids and other in ids, ids

    # 反真空：把全量读口打桩成空 ⇒ 同一格变成 0（证明它来自 `read_wait_any`）。
    from agentflow.tools import clock_tools as CT
    monkeypatch.setattr(CT.C, "read_wait_any", lambda _ws: {
        "checked": True, "rows": [], "count": 0, "reason": "判据：打桩成空"})
    with calling_as(me, "M"):
        stubbed = dict(reg.call("clock.wait_any", role="M").data)["intents"]
    assert stubbed["count"] == 0, ("打桩成空之后仍读到意图 ⇒ 那一格不是从这里来的", stubbed)


# ================================================================== 4 cancel_wait_any

def test_the_loop_drops_the_intent_when_it_goes_back_to_the_model(
        tmp_path, bench, monkeypatch) -> None:
    """④ 回模型那一拍撤掉等待意图（`_park_gate` 第 5 档；`run.park.wait_cancelled`）。

    夹具要落到第 5 档（"照常问模型"）而不是第 1 档（挂机），所以三件事同时成立：
    父名下还有一条 pending 的计时器（`parked.count > 0`）、这一拍有投递（"有活"）、
    并且起意之后已经有一条计时器回来了（`woke` 非空 ⇒ `requested` 已经是假）。
    这正是那条意图会变成"陈的"的那一档：`requested` 永远为假、`waiting` 也为假，
    不撤掉它，下一拍"我改主意了、手上有活"就会继续被旧意图拖着。
    """
    from agentflow.agent_loop import AgentLoop

    st, cond, ws = _ws(tmp_path, "cancel")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    reg = _reg(st, cond, ws)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")
    # 起意之后有一条计时器回来（`woke` 非空）：用一条 60 秒后到点的一次性计时器，
    # 起意之后把假时钟拨过去 —— 它到点、报醒，于是 `requested`/`waiting` 都为假。
    CLK.start_timer(ws, reason="60 秒后到点那一条", after_sec=60.0,
                    task_id=me, role="M")
    row = CLK.request_wait_any(ws, task_id=me, role="M", purpose="等任意计时器返回")
    assert row.get("wait_id"), row
    time.sleep(0)
    bench.advance(120.0)
    reading = dict(CLK.wait_any_reading(ws, me))
    assert reading["woke"], reading
    assert reading["requested"] is False and reading["waiting"] is False, reading

    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=None, store=st, sid="readouts", max_steps=2,
                     workspace_root=str(ws))
    loop.my_task_id = me
    run = _Run()
    out = loop._park_gate(step=0, run=run, mailbox={"item_ids": ["it-1"]})
    assert out["decision"] == "run", out
    assert out["skip_model"] is False, out
    assert out.get("wait_cancelled") == 1, out
    assert int(run.park.get("wait_cancelled") or 0) == 1, run.park
    assert CLK.read_wait_any(ws)["rows"] == [], CLK.read_wait_any(ws)

    # 反真空：把撤意图那一手打桩成"什么都不做" ⇒ 意图必须还在（同一条断言就红了）。
    monkeypatch.setattr(CLK, "cancel_wait_any",
                        lambda _ws, _tid: {"checked": True, "cancelled": 0, "reason": ""})
    CLK.request_wait_any(ws, task_id=me, role="M", purpose="再来一次")
    run2 = _Run()
    out2 = loop._park_gate(step=0, run=run2, mailbox={"item_ids": ["it-2"]})
    assert out2["decision"] == "run", out2
    assert out2.get("wait_cancelled") == 0, out2
    assert CLK.read_wait_any(ws)["rows"], ("打桩之后意图居然不在了 ⇒ 那一句不是承重的",
                                          CLK.read_wait_any(ws))


# ================================================================== 5 handoffs_reading

def test_the_silent_children_show_up_on_watch_and_ledger(tmp_path, bench,
                                                         monkeypatch) -> None:
    """⑤ `conductor.watch` / `conductor.ledger` 的 `silent_children`（交过差的那批）。"""
    st, cond, ws = _ws(tmp_path, "silent")
    reg = _reg(st, cond, ws)
    parent = cond.open_top_level_run("M", TASK)
    child = _child(cond, parent)
    CLK.record_handoff(ws, task_id=child, parent_task_id=parent, role="D",
                       reason="无事可做且没有任何计时器 ⇒ 交差")
    with calling_as(parent, "M"):
        watch = dict(reg.call("conductor.watch", role="M").data)
        ledger = dict(reg.call("conductor.ledger", role="M", view="tree").data)
    assert child in watch["silent_children"], watch["silent_children"]
    assert child in ledger["silent_children"], ledger["silent_children"]
    assert ledger["silent_children_checked"] is True, ledger["silent_children_reason"]

    # 反真空：把交差账读口打桩成空 ⇒ 两处都必须空（证明它们读的是那一本账）。
    monkeypatch.setattr(CLK, "read_handoffs", lambda _ws, **_kw: {
        "checked": True, "rows": [], "count": 0, "reason": "", "parent_task_id": ""})
    with calling_as(parent, "M"):
        watch2 = dict(reg.call("conductor.watch", role="M").data)
        ledger2 = dict(reg.call("conductor.ledger", role="M", view="tree").data)
    assert watch2["silent_children"] == [], watch2["silent_children"]
    assert ledger2["silent_children"] == [], ledger2["silent_children"]


# ================================================================== 6 child_wait_invariant

def test_the_invariant_is_read_out_by_watch_and_status_report(tmp_path, bench) -> None:
    """⑥ 不变量（活跃子代理 ⇒ 必有一条等它的计时器）在 watch / status_report 上念出来。"""
    st, cond, ws = _ws(tmp_path, "inv-read")
    reg = _reg(st, cond, ws)
    parent = cond.open_top_level_run("M", TASK)
    child = _child(cond, parent)
    # 写侧正常：派活时会自动起表；这里手工补上那一条（模拟 [5c] 已跑过）。
    armed = cond.arm_child_waiter(child, parent_task_id=parent, role="M",
                                  task_text="把 Sylow 定理的三处证据补齐")
    assert armed["armed"] is True, armed

    with calling_as(parent, "M"):
        watch = dict(reg.call("conductor.watch", role="M").data)
        report = dict(reg.call("conductor.status_report", role="M").data)
    inv = dict(watch["child_wait_invariant"])
    assert inv["checked"] is True, inv
    assert inv["unwaited"] == [], inv["problems"]
    assert child in (inv["by_parent"][parent]["active_children"]), inv["by_parent"]
    rep = dict(report["child_wait_invariant"])
    assert rep["checked"] is True, rep
    assert rep["unwaited"] == [], rep["problems"]

    # 反真空：把"派活时自动起表"那一支拔掉 ⇒ 不变量必须点名那个没人等的子代理。
    kid2 = _child(cond, parent, key="readouts@child2")
    with calling_as(parent, "M"):
        watch2 = dict(reg.call("conductor.watch", role="M").data)
    inv2 = dict(watch2["child_wait_invariant"])
    assert kid2 in inv2["unwaited"], ("没人等的子代理没有被点名 ⇒ 那一格没在判",
                                      kid2, inv2)
    assert any(kid2 in p for p in inv2["problems"]), inv2["problems"]
