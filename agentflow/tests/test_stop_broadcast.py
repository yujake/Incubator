# -*- coding: utf-8 -*-
"""判据（`draft/37` §128）：优雅停止时，「M 的广播频道」能不能用来叫停所有同伴。

用户口径：

> 对于优雅停止，测试一下 M 的广播频道能不能用
> 优雅停止还要提醒那些 Agent 把发起的进程一起停掉

M 的广播是「循环形状」（不是工具）：主控输出 `{"message": {"to": "#public", …}}`
⇒ `agent_loop._do_message` 落一条 `agent_message` 事件（`to="#public"`）。
这一组判据钉三件事，三件分开报（三态纪律：通道通 / 通道没通 / 没人读过，不能折成一个布尔）：

1. 「发得出去」：`#public` 落成一条 `agent_message`，带 `msg_id`；
2. 「每个同伴都收得到」：A–H 各自的收件箱摘要里都能看到它（含"未投递"标记的初值）；
3. 「投递登记是真的」：某个角色读过之后它那条变成已投递，「没读过的仍然显示未投递」
   —— 这一条防的是"广播看起来发出了，其实谁都没看见"。

另有一条「边界」必须写下来（同一组里判）：广播「打断不了」正在循环里的同伴 ——
每个角色的收件箱是在 `run()` 开头读一次的（`inbox_digest`），不是每步读；
所以"叫停"要真正打断在飞的工作，靠的是停机开关（`.agentflow-stop`，`stopctl`），
广播是"提醒同伴收工并停掉自己起的进程"那一条「可见的、持久的」通道。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import (LlmBackend, PUBLIC, inbox_digest, mark_delivered,
                                  read_messages, run_role)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict[str, Any]] = {("D", "write_report"): {}}


class _Gateway:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _wired(tmp_path: pathlib.Path, replies: list[str], *, sid: str = "bc"):
    st = Store(tmp_path / "ws")
    st.init()
    gw = _Gateway(replies)

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=tmp_path / "ws", gateway=gw,
                       price=(0.0, 0.0), sid=sid)

    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=tmp_path / "ws",
                         seam_factory=seam_factory, max_steps=4, store=st, sid=sid)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    return st, cond, built.registry, gw, tmp_path / "ws"


def _events(root: pathlib.Path, sid: str) -> list[dict]:
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return events


def test_the_boss_can_broadcast_a_stop_notice_on_the_public_channel(tmp_path):
    """正控：M 用 `{"message": {"to": "#public"}}` 广播一条叫停通知 ⇒ 落到公共频道。"""
    note = {"message": {"to": PUBLIC, "subject": "叫停",
                        "body": "用户叫停：请各自收工，并把你自己起的子进程停掉。"}}
    st, cond, registry, gw, root = _wired(tmp_path, [json.dumps(note, ensure_ascii=False),
                                                     json.dumps({"final": "已广播", "evidence": []},
                                                                ensure_ascii=False)])
    run = run_role("M", "广播叫停", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="bc"),
                   session_root=root, workspace_root=str(root), sid="bc", max_steps=3,
                   from_env=False)
    assert run.stop_reason == "final", run.to_dict()
    msgs = [e for e in _events(root, "bc") if e.get("kind") == "agent_message"]
    assert len(msgs) == 1, msgs
    assert msgs[0]["to"] == PUBLIC and msgs[0]["from"] == "M", msgs[0]
    assert "子进程" in str(msgs[0]["body"]), msgs[0]


def test_every_partner_sees_the_broadcast_and_delivery_is_recorded(tmp_path):
    """正控 + 三态：A–H 每个角色都收得到；读过的标已投递，「没读过的仍是未投递」。"""
    note = {"message": {"to": PUBLIC, "subject": "叫停", "body": "停"}}
    st, cond, registry, gw, root = _wired(tmp_path, [json.dumps(note, ensure_ascii=False),
                                                     json.dumps({"final": "已广播", "evidence": []},
                                                                ensure_ascii=False)])
    run_role("M", "广播叫停", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="bc"),
             session_root=root, workspace_root=str(root), sid="bc", max_steps=3, from_env=False)

    seen: dict[str, bool] = {}
    for role in S.ROLES:
        msgs, problems = read_messages(root, role, sid="bc")
        assert not problems, problems
        mine = [m for m in msgs if m.get("to") == PUBLIC]
        assert mine, f"{role} 的收件箱里没有那条广播 ⇒ 广播没到达所有人"
        seen[role] = bool(mine[0].get("delivered"))
    assert not any(seen.values()), f"还没人读过，怎么会有已投递的：{seen}"

    # D 读一次（`run()` 的路径是 `inbox_digest` + `mark_delivered`）⇒ 只有 D 那条变成已投递
    _digest, fresh, problems = inbox_digest(root, "D", sid="bc")
    assert not problems, problems
    assert fresh, "D 的收件箱里应当有未投递的新留言"
    problem = mark_delivered(root, "D", fresh, sid="bc")
    assert not problem, problem
    after = {}
    for role in S.ROLES:
        msgs, _ = read_messages(root, role, sid="bc")
        mine = [m for m in msgs if m.get("to") == PUBLIC]
        after[role] = bool(mine and mine[0].get("delivered"))
    assert after["D"] is True, after
    assert not any(v for k, v in after.items() if k != "D"), after


def test_a_broadcast_does_not_interrupt_a_running_loop(tmp_path):
    """边界（必须写下来）：广播「打断不了」正在循环里的同伴 —— 叫停靠停机开关。

    每个角色的收件箱是 `run()` 开头读一次的（`inbox_digest`）：正在循环的 E 不会
    每个模型步都去看收件箱。所以"叫停"要真正打断在飞的工作，用的是
    `.agentflow-stop`（`stopctl`，`AgentLoop._user_stop_reason` 每步看一次）；
    广播负责的是"提醒同伴收工、并让它们停掉自己起的进程"那一条持久可见的通道。
    """
    from agentflow import stopctl

    note = {"message": {"to": PUBLIC, "subject": "叫停", "body": "停"}}
    st, cond, registry, gw, root = _wired(tmp_path, [json.dumps(note, ensure_ascii=False),
                                                     json.dumps({"final": "已广播", "evidence": []},
                                                                ensure_ascii=False)])
    run_role("M", "广播叫停", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="bc"),
             session_root=root, workspace_root=str(root), sid="bc", max_steps=3, from_env=False)

    # 广播已经躺在盘上了，但"叫停"这件事在停机开关里「还是没有」
    assert stopctl.read_stop(root) is None, "广播不该等价于停机开关（两件事，两种通道）"
