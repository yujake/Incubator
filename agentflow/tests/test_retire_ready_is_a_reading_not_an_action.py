# -*- coding: utf-8 -*-
"""S1f'：`retire_ready` 就绪读数（只报不动作）—— 业主 T22 的三分支，框架不替父退役。

## 口径（`draft/90` §1.9 逐字，`draft/92` §15.3）

业主：「子代理宣布收工后，由父代理决定是否消边」。所以框架只给就绪读数：

- `branch="active"`：这一项还在跑 ⇒ 父该先看它最近报了什么，不许退役；
- `branch="waiting_no_children"`：它不在跑、它自己名下没有活跃子代理 ⇒ 可以退役；
- `branch="waiting_with_children"`：它不在跑、但它自己名下还有活跃子代理 ⇒ 不退役。

（"无活跃子代理且自身完全停止"说的是它自己，不是父 —— `draft/92` §15.6 的订正。）`reading.items_open` 只报不拦（业主算法里没这一条，C2 的裁定）。

## 判据

正控 2：三分支各就各位；父读到板项那一步的结果里出现"可退役"。负控（本批最重要的一条）：`retire_ready` 与它接进循环之后，零写入（子行的 `inputs` 里没有 `edge-released:` 落痕、
板项状态一个字节不变）——没有这一条，"只报不动作"就只是注释里的一句话。反真空 1：读不成 ⇒ `checked=False`（不许折成"没有可退役的"）。边界 1：已记过消边的那些不再进候选。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s1fp"


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        text = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, Conductor(st, policy=None, backend=LocalBackend({})), ws


def _child(cond: Conductor, parent: str, *, role: str = "A", status: str = "done",
           key: str = "s1fp@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")


def _branches(ready: dict[str, Any]) -> dict[str, str]:
    return {r["task_id"]: r["branch"] for r in ready["ready"]}


def test_three_branches_are_classified(tmp_path: pathlib.Path):
    """正控：三分支各就各位（活跃 / 在等待且名下无活跃子 / 在等待但名下有活跃子）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    running = _child(cond, parent, status="running", key="s1fp@run")
    free = _child(cond, parent, status="done", key="s1fp@free")
    busy = _child(cond, parent, status="done", key="s1fp@busy")
    _child(cond, busy, status="running", key="s1fp@grand")     # busy 名下还有一个在跑的

    got = cond.retire_ready(parent)
    assert got["checked"] is True and got["reason"] == "", got
    table = _branches(got)
    assert table[running] == "active", table
    assert table[free] == "waiting_no_children", table
    assert table[busy] == "waiting_with_children", table
    # `reading.items_open` 只报不拦：给 free 挂一条未消的项，它仍然是"可以退役"
    cond.open_item(kind="notice", role="A", expects="ack", summary="子代理已收工",
                   called_by="A", parent_task_id=free, depth=3, input_key="s1fp@n")
    again = _branches(cond.retire_ready(parent))
    assert again[free] == "waiting_no_children", again
    reading = {r["task_id"]: r["reading"] for r in cond.retire_ready(parent)["ready"]}
    assert reading[free]["items_open"] == 1, reading[free]


def test_a_released_child_drops_out_of_the_candidates(tmp_path: pathlib.Path):
    """边界：已经记过消边的那些不再进候选（否则父会看到"它又变成可退役了"）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")
    free = _child(cond, parent, status="done", key="s1fp@free2")
    assert _branches(cond.retire_ready(parent))[free] == "waiting_no_children"
    mark, why = cond.note_edge_release(parent, child_task_id=free, attempt=1)
    assert mark and not why, (mark, why)
    assert free not in _branches(cond.retire_ready(parent)), cond.retire_ready(parent)


def test_retire_ready_is_three_state(tmp_path: pathlib.Path, monkeypatch):
    """反真空：台账读不成 ⇒ `checked=False`（不许折成"没有可退役的"）。"""
    _st, cond, _ws = _cond(tmp_path)
    parent = cond.open_top_level_run("M", "父那一趟")

    def boom() -> Any:
        raise RuntimeError("注入的台账故障")

    monkeypatch.setattr(cond, "_tasks", boom)
    got = cond.retire_ready(parent)
    assert got["checked"] is False and "RuntimeError" in got["reason"], got
    assert got["ready"] == [], got


def _run_loop(cond: Conductor, st: Store, ws: pathlib.Path, gate: _Gate, me: str) -> Any:
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    return loop.run("把这一趟做完", summoned_by="user", my_task_id=me, depth=1)


def test_the_loop_reports_ready_items_and_never_retires_them(tmp_path: pathlib.Path):
    """正控（接线）+ 负控（本批最重要的一条）：报得出来，但一个字节都不写。

    正控：父这一步渲染到了板项 ⇒ 结果里出现 `可退役`（含 branch）。
    负控（"零自动退役"的机器形态）：跑完之后
    ① 父那一行 `inputs` 里没有任何 `edge-released:` 落痕（`released_edges` 为空）
    ② 子那一行的 `status` 与 `inputs` 逐字不变（框架没替父把它划掉）
    ③ 那条板项确实被标了 `seen` —— 这一格是 S1i 的行为（"渲染即 seen"），
       与"退役"是两件事：把它写进断言是为了让人一眼看出两者的区别。
    """
    st, cond, ws = _cond(tmp_path)
    me = cond.open_top_level_run("M", "我这一趟的活")
    child = _child(cond, me, status="done", key="s1fp@reported")
    item = cond.open_item(kind="notice", role="M", expects="ack", summary="子代理已收工",
                          called_by="A", parent_task_id=me, depth=2, input_key="s1fp@item")
    child_before = next(r for r in st.rows("tasks") if str(r.get("task_id")) == child)
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    run = _run_loop(cond, st, ws, gate, me)

    merged = [s.result for s in run.steps]
    assert any("可退役" in r for r in merged), (
        "父读到板项那一步的结果里必须出现就绪读数", merged)
    ready = next(r["可退役"] for r in merged if "可退役" in r)
    assert {x["task_id"]: x["branch"] for x in ready} == {child: "waiting_no_children"}, ready

    # 负控①②：零写入（不许替父退役）
    assert cond.released_edges(me)["edges"] == [], (
        "框架不许替父退役（父侧不许留消边落痕）", cond.released_edges(me))
    child_after = next(r for r in st.rows("tasks") if str(r.get("task_id")) == child)
    assert (child_after["status"], list(child_after.get("inputs") or [])) == (
        child_before["status"], list(child_before.get("inputs") or [])), (
        "子那一行不许被动过", (child_before, child_after))
    # ③ 板项被标 seen（S1i 的行为）—— 与"退役"是两件事
    after_items = {r["task_id"]: r["item_state"] for r in cond.open_items_of(me)}
    assert after_items[item] == "seen", after_items
