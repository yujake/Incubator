"""叫醒不许复制一个自己：目标正在跑 ⇒ 不另起同号循环（业主 2026-10-29）。

来由（实测，不是设想）：把兜底表接进 `run()` 之后，`test_timers_and_handoff_semantics`
超时挂死 —— 兜底表是在这一趟循环里被打掉的，这时 `wake_on_lifeline` 又去
`resume_dispatched`，于是同号起了第二个循环，两个自己互相喂事件。

三条判据：
  s1 目标正在跑 ⇒ 不叫（`started=False`，理由点名"它自己在跑"）
  s2 静默未销号 ⇒ 照旧叫（s1 不许把所有情况一起挡掉）
  s3 已销号 ⇒ 仍然叫不醒（P4 的边界不许被 s1 掩盖）
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


def _ws(tmp_path: pathlib.Path) -> dict:
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    calls: list[tuple[str, dict]] = []

    def _runner(tid: str, **kw):
        calls.append((tid, dict(kw)))
        return {"started": True}

    cond.resume_runner = _runner
    owner = str(cond.open_top_level_run("M", "夹具：别叫我自己"))
    return {"root": root, "cond": cond, "owner": owner, "calls": calls}


def _child(cond: Conductor, parent: str, *, status: str) -> str:
    row = {"role": "D", "action": "write_report", "called_by": "M",
           "parent_task_id": parent, "depth": 2, "input_key": f"自我唤醒:{status}",
           "status": status, "outcome": ("ok" if status == "done" else None),
           "ended_at": (TS if status == "done" else None),
           "started_at": TS, "detail": "夹具子代理"}
    return str(cond._write_new_row(row, note="fixture:selfwake"))


def test_s1_a_running_agent_is_not_resumed(tmp_path: pathlib.Path) -> None:
    """目标正在跑 ⇒ 不许再起一个同号循环（那会造出两个自己）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="running")
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is False, got
    assert env["calls"] == [], env["calls"]
    assert "在跑" in str(got.get("reason") or ""), got


def test_s2_a_silent_agent_is_still_resumed(tmp_path: pathlib.Path) -> None:
    """静默未销号 ⇒ 照旧要被叫起来（s1 不许把所有情况一起挡掉）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="done")
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is True, got
    assert env["calls"] and env["calls"][0][0] == child, env["calls"]


def test_s3_a_retired_agent_is_still_deaf(tmp_path: pathlib.Path) -> None:
    """已销号 ⇒ 叫不醒（P4 的边界不许被 s1 掩盖）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="done")
    env["cond"].secretary = type("S", (), {"retired_names": {child: "已销号"}})()
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is False, got
    assert "叫不醒" in str(got.get("reason") or ""), got
