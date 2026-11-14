# -*- coding: utf-8 -*-
"""判据（A / B2）：停机开关在盘上 ⇒ 派活被受控拒，不落 running 行、不调后端。

改前 `conductor` 的派活路径对停机开关零命中：开关 22:00:27 落盘之后，22:01:10 与
22:01:35 仍创建了两个子代理（`t-000095` / `t-000102`）。它们各跑到自己的第 0 步才
读到开关、0 步收工 —— 但"创建"这件事已经写进 tasks / events / usage_ledger。
现场见 `temp/analysis/09-stop-switch.md` §3 B2。

判据四件：
1. 开关在 ⇒ 四个派活入口（`summon_begin` / `summon` / `summon_preemptible` /
   `summon_many`）都给受控取消，`backend.calls == []`，台账里不多出一行；
2. 开关不在 ⇒ 派活照常（负控）；
3. 开关在 ⇒ `summon_run` 对"开关落盘之前就建好行"的那一趟按取消收口（不留僵尸）；
4. 反真空：把派活前那条停机查询打桩成恒"没停" ⇒ 第 1 条必红。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import stopctl
from agentflow.conductor import Conductor
from agentflow.scheduler import TaskCall
from agentflow.store import Store


class _Backend:
    """假后端：任何 (角色, 动作) 都跑成 ok，并把"这次调用"记下来。"""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call(self, role: str, action: str, params: Any, *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        self.calls.append({"role": role, "action": action, "task_id": str(task_id),
                           "instance": str(instance), "params": dict(params or {})})
        return {"outcome": "ok", "detail": "跑完了", "payload": {"ok": True}}


def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _Backend()
    cond = Conductor(st, policy=None, backend=backend)
    parent = str(cond.open_top_level_run("M", "顶趟这一趟"))
    return {"ws": ws, "st": st, "cond": cond, "backend": backend, "parent": parent}


def _task_rows(env: dict[str, Any]) -> list[dict[str, Any]]:
    return list(env["st"].rows("tasks"))


def test_the_stop_switch_refuses_every_dispatch_entry(tmp_path: pathlib.Path) -> None:
    """开关在 ⇒ 四个入口都受控拒：无后端调用、无 running 行、理由说清"不派新活"。"""
    env = _env(tmp_path)
    cond, backend, parent = env["cond"], env["backend"], env["parent"]
    before = len(_task_rows(env))
    stopctl.request_stop(env["ws"], reason="业主叫停", by="user")

    # ① 前半（`summon_begin`，`summon` / `summon_preemptible` 都从这里过）
    start = cond.summon_begin("D", "poll", {}, parent_task_id=parent)
    assert start.task_id is None, start
    assert start.refusal is not None, start
    assert start.refusal.status == "cancelled", start.refusal
    assert start.refusal.outcome == "cancelled", start.refusal
    assert "停机开关在" in start.refusal.detail, start.refusal.detail
    assert "不派新活" in start.refusal.detail, start.refusal.detail

    # ② 阻塞式入口
    res = cond.summon("D", "poll", {}, parent_task_id=parent)
    assert res.status == "cancelled" and res.task_id is None, res
    assert "停机开关在" in res.detail, res.detail

    # ③ 可抢占入口（不起线程、句柄立刻落定）
    handle = cond.summon_preemptible("D", "poll", {}, parent_task_id=parent)
    got = handle.poll()
    assert got is not None and got.status == "cancelled", (got, handle.start.refusal)
    assert handle.task_id is None, handle.describe()

    # ④ 整批入口
    wave = cond.summon_many([TaskCall(role="D", action="poll", params={},
                                      by="M", parent_task_id=parent)])
    results = wave.results()
    assert len(results) == 1, results
    assert results[0].status == "cancelled", results
    assert results[0].task_id is None, results

    assert backend.calls == [], ("停机之后仍调用了后端：", backend.calls)
    assert len(_task_rows(env)) == before, (
        "停机之后仍落了台账行：", [r["task_id"] for r in _task_rows(env)])


def test_without_the_stop_switch_dispatch_runs_as_usual(tmp_path: pathlib.Path) -> None:
    """负控：没有开关 ⇒ 派活照常（有后端调用、有行、结果是 done/ok）。"""
    env = _env(tmp_path)
    cond, backend, parent = env["cond"], env["backend"], env["parent"]
    assert stopctl.read_stop(env["ws"]) is None

    res = cond.summon("D", "poll", {}, parent_task_id=parent)
    assert res.status == "done" and res.outcome == "ok", res
    assert res.task_id, res
    assert [c["role"] for c in backend.calls] == ["D"], backend.calls
    rows = [r for r in _task_rows(env) if r["task_id"] == res.task_id]
    assert rows and rows[0]["status"] == "done", rows


def test_a_run_started_before_the_switch_is_closed_as_cancelled(
        tmp_path: pathlib.Path) -> None:
    """前半建行早于开关落盘 ⇒ 后半按取消收口：不调后端、不留 running 僵尸。"""
    env = _env(tmp_path)
    cond, backend = env["cond"], env["backend"]
    start = cond.summon_begin("D", "poll", {}, parent_task_id=env["parent"])
    assert start.task_id, start
    stopctl.request_stop(env["ws"], reason="user", by="user")

    res = cond.summon_run(start)
    assert res.status == "cancelled" and res.outcome == "cancelled", res
    assert "停机开关在" in res.detail, res.detail
    assert backend.calls == [], backend.calls
    row = [r for r in _task_rows(env) if r["task_id"] == start.task_id][0]
    assert row["status"] == "cancelled", row
    assert row["ended_at"], row


def test_anti_vacuum_stubbing_the_stop_query_sends_dispatch_through(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把派活前的停机查询打桩成恒"没停" ⇒ 开关在盘上也照派（第 1 条必红）。"""
    env = _env(tmp_path)
    cond, backend, parent = env["cond"], env["backend"], env["parent"]
    stopctl.request_stop(env["ws"], reason="user", by="user")
    monkeypatch.setattr(
        Conductor, "_dispatch_stop_gate",
        lambda self, **kw: {"checked": True, "stopped": False, "state": "none",
                            "reason": "", "path": str(stopctl.stop_path(env["ws"])),
                            "why": "打桩：恒「没停」"})

    res = cond.summon("D", "poll", {}, parent_task_id=parent)
    assert res.status == "done" and res.task_id, (
        "打桩之后仍然被拒 —— 打桩没生效，反真空不成立", res)
    assert len(backend.calls) == 1, backend.calls
