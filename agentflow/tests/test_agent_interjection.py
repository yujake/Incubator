# -*- coding: utf-8 -*-
"""集体插话（`draft/39` §3.11 二 D07，用户 2026-10-05 裁定）—— 也是 E7 的演练。

用户口径（逐字）：

> D07 没听懂，优雅停不是广播 message 吗？
> ……D07 是"广播"动作没做好，应该是集体插话发送。

裁定（`draft/39` §3.11 二）：

1. 广播写成一个插话（`agent_interjection`）：发给所有在册角色（含 M）；
2. 每个在跑的循环在它的下一步开始时，把插话摆在最显眼的位置（单列一段【插话】，
   不混在消息列表里），并标明"优先于你自己的计划"；
3. 叫停类插话额外落一条读数（谁在第几步收到、它有没有改变那一步的做法）——
   这条读数正是"广播动作做好了没有"的证据。

这一组把三件事都钉住（全部离线可复跑）：

- 插话是一次事件、编号由脚本发；读者只拿到"自己没读过的那几条"；
- 循环在下一步才看到它（当步不被打断），并且确实出现在那一步的提示词里；
- 叫停类插话落 `agent_interjection_effect`：`changed_action` 按"调用键与上一步是否不同"判。
"""
from __future__ import annotations

import json
from typing import Any

from agentflow import sessions as SS
from agentflow.agent_loop import (
    LlmBackend, read_interjections, run_role, send_interjection,
)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _world(tmp_path, replies, *, role: str = "D", max_steps: int = 4, on_call=None):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies)
    if on_call is not None:
        original = gw.complete

        def wrapped(prompt, **kw):
            on_call(len(gw.prompts))
            return original(prompt, **kw)

        gw.complete = wrapped  # type: ignore[assignment]
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="ij"),
                         max_steps=max_steps, store=st, sid="ij")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    backend.registry = reg
    run = run_role(role, "插话演练", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid="ij"),
                   session_root=ws, workspace_root=str(ws), sid="ij",
                   max_steps=max_steps, from_env=False)
    return ws, run, gw


def _final(text: str = "收工") -> dict[str, Any]:
    return {"final": text, "notify": {"to": "M", "summary": text, "body": "完。\n"}}


# ============================================================ 插话本身

def test_an_interjection_is_an_event_with_a_script_allocated_id(tmp_path):
    """插话是一条 `agent_interjection` 事件，编号由脚本顺次发（模型不许自己编号）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    first, problem = send_interjection(ws, sender="用户", subject="口径变了",
                                       body="只在 n<=5 时成立。", sid="s")
    second, problem2 = send_interjection(ws, sender="M", subject="叫停",
                                         body="请各自收工。", sid="s")
    assert not problem and not problem2, (problem, problem2)
    assert (first, second) == ("i-0001", "i-0002"), (first, second)
    events, bad = SS.read_session(ws, sid="s")
    assert not bad, bad
    got = [e for e in events if e.get("kind") == "agent_interjection"]
    assert len(got) == 2, got
    assert got[0]["to"] == "ALL" and got[0]["from"] == "用户", got[0]
    assert got[1]["is_stop"] is True, got[1]


def test_a_role_only_gets_its_own_interjections_and_only_once(tmp_path):
    """读者只拿到"自己没读过的"那些：给别人的不给，读过的再读不给第二次。"""
    from agentflow.agent_loop import mark_interjections_seen

    ws = tmp_path / "ws"
    ws.mkdir()
    send_interjection(ws, sender="用户", subject="广播", body="所有人", sid="s")
    send_interjection(ws, sender="M", subject="只给 F", body="F 的事", to="F", sid="s")
    got_d, bad = read_interjections(ws, "D", sid="s")
    assert not bad and [i["interjection_id"] for i in got_d] == ["i-0001"], got_d
    got_f, _ = read_interjections(ws, "F", sid="s")
    assert [i["interjection_id"] for i in got_f] == ["i-0001", "i-0002"], got_f
    mark_interjections_seen(ws, "D", ["i-0001"], sid="s", step=3)
    again, _ = read_interjections(ws, "D", sid="s")
    assert again == [], again
    events, _bad = SS.read_session(ws, sid="s")
    seen = [e for e in events if e.get("kind") == "agent_interjection_seen"]
    assert seen and seen[0]["step"] == 3 and seen[0]["role"] == "D", seen


# ============================================================ E7：插话在下一步生效

def test_e7_an_interjection_arrives_at_the_next_step_not_mid_step(tmp_path):
    """E7：插话出现在下一步的提示词里（当步不被打断），并落"谁在第几步收到"。"""
    ws_holder: dict[str, Any] = {}

    def on_call(n: int) -> None:
        # 第一步之后（模型被问第二次之前）发一条插话
        if n == 1:
            send_interjection(ws_holder["ws"], sender="用户", subject="叫停",
                              body="请收工，别再开新的一轮。", sid="ij")

    ws_holder["ws"] = tmp_path / "ws"      # `_world` 用的就是它；on_call 在跑的过程中就会读
    ws, run, gw = _world(tmp_path, [
        {"tool": "table.list", "args": {"table": "tasks"}, "why": "先看一眼"},
        {"tool": "table.list", "args": {"table": "documents"}, "why": "换一件事做"},
        _final("照插话收工"),
    ], on_call=on_call)
    assert run.stop_reason == "final", run.to_dict()
    # 提示词层面：第一条提示词里没有插话，第二条里有（这就是"下一步开头"）
    prompts = gw.prompts
    assert "【插话】" not in prompts[0] and "【插话】" not in prompts[1], [p[-200:] for p in prompts[:2]]
    assert "【插话】" in prompts[2] and "优先于你自己的计划" in prompts[2], prompts[2][-400:]
    # 事件层面：消费登记带步号 ⇒ "谁在第几步收到"可查
    events, bad = SS.read_session(ws, sid="ij")
    assert not bad, bad
    seen = [e for e in events if e.get("kind") == "agent_interjection_seen"]
    assert seen and seen[0]["step"] == 2 and seen[0]["ids"] == ["i-0001"], seen
    effect = [e for e in events if e.get("kind") == "agent_interjection_effect"]
    assert effect, [e.get("kind") for e in events]
    assert effect[0]["step"] == 2 and effect[0]["ids"] == ["i-0001"], effect[0]


def test_e7_the_effect_reading_says_whether_the_step_changed(tmp_path):
    """E7 的读数：`changed_action` 按"这一步的调用键与上一步不同"判（自述不算数）。

    这一条造两次：① 收到插话后改了做法（换了一张表）⇒ `true`；
    ② 收到插话后照旧做同一件事 ⇒ `false` —— 两个方向都要能判，
    否则这条读数会退化成"永远是 true"。
    """
    def run_case(tmp_path_, *, second_table: str, name: str):
        holder: dict[str, Any] = {}

        def on_call(n: int) -> None:
            if n == 1:
                send_interjection(holder["ws"], sender="用户", subject="叫停",
                                  body="停下手上的事，改做别的。", sid="ij")

        holder["ws"] = tmp_path_ / name / "ws"
        # 三步工具 + 收工：插话在第 1 步的 ask 期间落下 ⇒ 它影响的是第 2 步
        # （那一步的回复就是这里第三条），于是"改没改做法"比较的正是第 1 步与第 2 步。
        ws, run, _gw = _world(tmp_path_ / name, [
            {"tool": "table.list", "args": {"table": "tasks"}, "why": "先看一眼"},
            {"tool": "table.list", "args": {"table": "tasks"}, "why": "照旧做同一件事"},
            {"tool": "table.list", "args": {"table": second_table}, "why": "接着做"},
            _final(),
        ], on_call=on_call)
        events, _bad = SS.read_session(ws, sid="ij")
        return next(e for e in events if e.get("kind") == "agent_interjection_effect")

    changed = run_case(tmp_path, second_table="documents", name="changed")
    assert changed["changed_action"] is True, changed
    same = run_case(tmp_path, second_table="tasks", name="same")
    assert same["changed_action"] is False, same


def test_e7_a_stop_interjection_is_what_conductor_stop_sends(tmp_path):
    """接线：`conductor.stop(notify=True)` 发出的就是插话（不是普通广播 message）。"""
    from agentflow.tools import ToolError  # noqa: F401  （只为断言类型可用性）

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    tool = reg.get("conductor.stop")
    result = tool.handler(reason="user", notify=True)
    data = result.data if hasattr(result, "data") else result
    assert data.get("notified", "").startswith("i-"), data
    events, bad = SS.read_session(ws, sid=None)
    # 没给 sid ⇒ 落在当天那段会话里；用 list_sessions 找到它
    from agentflow import sessions as SS2

    for info in SS2.list_sessions(ws):
        events, bad = SS2.read_session(ws, info["sid"])
        if [e for e in events if e.get("kind") == "agent_interjection"]:
            break
    assert not bad, bad
    ij = [e for e in events if e.get("kind") == "agent_interjection"]
    assert ij and ij[0]["is_stop"] is True and ij[0]["to"] == "ALL", ij
