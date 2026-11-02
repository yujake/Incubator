# -*- coding: utf-8 -*-
"""2026-11-02（83）：自己的动作（`own.*`）要逐条落账；工具入口派出去的孩子要被清点。

## 这一份钉的是两件同源的事

83 的真机读数（只读复算）：B 的 `t-000219` 在 113 分钟里调了 27 次 `own.run_once`
（每次都真的 `processed=1`），而 `agent_step_call` 里「一行都没有」—— 逐条账只在
"一步多条调用"时才落（`agent_loop.run()` 那处 `dispatch.multi` 的闸）。于是读数上只剩
`ok=True` 加上空的文本（`llm_call.text_len=0`），"它在推进还是原地空转"在逐条账上答不出来。

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 单条 `own.run_once` ⇒ `agent_step_call` 里恰好一行（`tool=own.run_once`、`own_action` 标记、`calls=1`） | 改前单条调用一律不落逐条账（只有 multi 落） |
| b | 反真空：单条 `fs.list` 仍然不落（这把尺子认的是"自己的动作"，不是"所有单条"） | 没有它，"落了一行"可能只是把闸全放开了 |
| c | 工具入口（`conductor.summon_many`）派出去的孩子，在父退场时被清点成 `cut_off_by_parent` | 上一笔（可抢占）之前红：工具入口没有挂账，退场结算读成"没有孩子"；本笔把它钉住 |

## 夹具为什么不睡觉

"跑很久"仍由 `threading.Event` 造（与 `test_summon_is_preemptible.py` 同一手法）：
c 条要的是"父退场那一刻孩子还在跑"，放不放行由判据决定。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop, run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.base import ToolSpec

SID = "ownledger"
ROLE = "M"
KID = "C"
TASK = "2026-11-02 判据夹具：自己的动作逐条落账"

LOOK = json.dumps({"tool": "fs.list", "args": {"path": "."}}, ensure_ascii=False)
ASK = json.dumps({"ask_user": {"question": "口径用哪个？", "timeout_sec": 0}},
                 ensure_ascii=False)
OWN = json.dumps({"tool": "own.run_once", "args": {}}, ensure_ascii=False)
TARGETS = [{"target_role": KID, "task": f"第 {i} 件长活", "instance": str(i)}
           for i in (1, 2, 3)]
TOOL_MANY = json.dumps({"tool": "conductor.summon_many",
                        "args": {"targets": TARGETS}}, ensure_ascii=False)


class _BlockingBackend:
    """派出去就卡住的后端：它只保证"父退场那一刻子还在跑"。"""

    name = "blocks"

    def __init__(self, wait_timeout: float = 5.0) -> None:
        self.gate = threading.Event()
        self.wait_timeout = float(wait_timeout)
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def known_roles(self) -> list[str]:
        return [KID]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append(str(task_id))
        self.gate.wait(timeout=self.wait_timeout)
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"final": f"{role}#{instance or '-'} 的结论"}}

    def release(self) -> None:
        self.gate.set()


class _Gate:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


@pytest.fixture()
def fast_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AL.AgentLoop.__init__

    def patched(self: Any, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self.child_step_wait_sec = 0.05
        self.child_return_wait_sec = 0.05
        self.child_exit_drain_sec = 0.05

    monkeypatch.setattr(AL.AgentLoop, "__init__", patched)
    monkeypatch.setattr(
        AL.AgentLoop, "_park_gate",
        lambda self, **kw: {"skip_model": False, "decision": "run",
                            "checked": True, "reason": "判据：照常问模型"})


def _env(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor, _BlockingBackend]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _BlockingBackend()
    return ws, st, Conductor(st, policy=Policy(), backend=backend), backend


def _own_spec() -> ToolSpec:
    """一件"自己的动作"（与 `_own_action_tool` 同形：名字 `own.<动作>`）。"""
    return ToolSpec(
        name="own.run_once",
        summary="判据：做我自己的那个动作（run_once）",
        params={"type": "object", "properties": {}},
        handler=lambda **kw: {"ok": True, "data": {"processed": 1}, "error": "", "meta": {}},
        side_effect="none", roles=(ROLE,), returns="{'ok','data','error','meta'}",
        tags=("own_action",))


def _registry(st: Store, cond: Conductor, ws: pathlib.Path) -> Any:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reg.register(_own_spec())
    return reg


def _run(ws: pathlib.Path, st: Store, cond: Conductor, replies: list[str]) -> Any:
    return run_role(ROLE, TASK, store=st, registry=_registry(st, cond, ws),
                    conductor=cond, session_root=ws, sid=SID, from_env=False,
                    seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate(replies),
                                 price=(0.0, 0.0), sid=SID),
                    max_steps=6)


def _events(ws: pathlib.Path) -> list[dict]:
    rows, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    return rows


def _step_calls(ws: pathlib.Path) -> list[dict]:
    return [dict(e) for e in _events(ws) if e.get("kind") == "agent_step_call"]


# ============================================================ a + b：逐条账
def test_a_single_own_action_lands_one_per_call_row(tmp_path: pathlib.Path,
                                                    fast_loop: None) -> None:
    """判据 a + b：单条 `own.run_once` 落一行；单条 `fs.list` 仍然不落。

    改前红：闸是 `dispatch.multi`（`agent_loop.run()`），单条调用一律不落 ——
    83 上 B 的 27 次 `own.run_once` 在 `agent_step_call` 里一行都没有。
    """
    ws, st, cond, _backend = _env(tmp_path)
    run = _run(ws, st, cond, [OWN, LOOK, ASK, ASK])
    assert run.stop_reason == "waiting_for_user", run.to_dict()

    rows = _step_calls(ws)
    own = [r for r in rows if str(r.get("tool")) == "own.run_once"]
    assert len(own) == 1, ("单条 own.run_once 没有恰好落一行", rows)
    assert own[0]["ok"] is True, own[0]
    assert own[0].get("own_action") == "own.run_once", own[0]
    assert int(own[0].get("calls") or 0) == 1, own[0]
    assert int(own[0].get("call_index") or 0) == 0, own[0]
    assert not own[0].get("not_executed"), own[0]

    # b：反真空 —— 单条的普通工具（fs.list）仍然不落（否则"落了一行"只是闸全开了）。
    assert not [r for r in rows if str(r.get("tool")) == "fs.list"], (
        "单条的普通工具也落了逐条账 ⇒ 这把尺子认的不是'自己的动作'", rows)


# ============================================================ c：退场清点
def test_children_summoned_through_the_tool_are_counted_at_exit(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 c：工具入口派出去的孩子，父退场时被清点成 `cut_off_by_parent`。

    改前红：工具入口把句柄丢在工具里 ⇒ 本循环的挂账里没有它们 ⇒
    `_settle_children_at_exit` 的 `_children_running()` 读成空表（"没有孩子"），
    于是那几行永远 running、父行也不点名。
    """
    ws, st, cond, backend = _env(tmp_path)
    run = _run(ws, st, cond, [TOOL_MANY, ASK, ASK])
    assert run.stop_reason == "waiting_for_user", run.to_dict()
    try:
        parent = next(str(r["task_id"]) for r in st.rows("tasks")
                      if str(r.get("action") or "") == "run")
        assert parent, "台账里没有顶趟那一行"
        kids = {str(r["task_id"]): dict(r) for r in st.rows("tasks")
                if str(r.get("parent_task_id") or "") == parent
                and not str(r.get("kind") or "")}
        assert len(kids) == 3, kids
        written = list(run.cut_off_children)
        assert sorted(written) == sorted(kids), ("工具入口的孩子没有被清点", written, list(kids))
        for tid in written:
            row = kids[tid]
            assert row["status"] == "done", row
            assert row["outcome"] == "cut_off_by_parent", row
            assert row["settled_at_parent_exit"] is True, row
            assert row.get("ended_at"), row
    finally:
        backend.release()          # 放行，别把子线程挂在解释器退出上
