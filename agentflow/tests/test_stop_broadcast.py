# -*- coding: utf-8 -*-
"""判据（`draft/37` §128）：优雅停止时，「M 的广播频道」能不能用来叫停所有同伴。

用户口径：对于优雅停止，测试一下 M 的广播频道能不能用
> 优雅停止还要提醒那些 Agent 把发起的进程一起停掉M 的广播是「循环形状」（不是工具）：主控输出 `{"message": {"to": "#public", …}}`⇒
`agent_loop._do_message` 落一条 `agent_message` 事件（`to="#public"`）。这一组判据钉三件事，三件分开报（三态纪律：通道通 / 通道没通 / 没人读过，不能折成一个布尔）：

1. 「发得出去」：`#public` 落成一条 `agent_message`，带 `msg_id` 与发信人的台账号；
2. 「我名下的直接子代理收得到」：业主 T20/T21 附二 乙把公聊的可见面收窄成
"发信人的直接子代理" ⇒ 这条判据改成"是它的子级才收得到、不是的收不到"，并按 `parent_task_id` 逐个读者核（旧口径"每个同伴都收得到"是改前的事实，已作废）；
3. 「投递登记是真的」：某个收得到的角色读过之后它那条变成已投递，「没读过的仍然显示未投递」
—— 这一条防的是"广播看起来发出了，其实谁都没看见"。

叫停那一份有例外（安全件）：`conductor.stop(notify=True)` 发的叫停走框架档（`by_framework=True` ⇒ 所有角色可见）—— 工具层手上没有实例号，而"听不到叫停的子孙会继续烧钱跑实验"。
S4 的"沿边逐层下发"落地后这一档退休（`draft/86` §14.6）。

另有一条「边界」必须写下来（同一组里判）：广播「打断不了」正在循环里的同伴 ——每个角色的收件箱是在 `run()` 开头读一次的（`inbox_digest`），不是每步读；所以"叫停"要真正打断在飞的工作，
靠的是停机开关（`.agentflow-stop`，`stopctl`），广播是"提醒同伴收工并停掉自己起的进程"那一条「可见的、持久的」通道。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import (LlmBackend, ALL, inbox_digest, mark_delivered,
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


def _child_row(cond, parent: str, *, role: str, key: str) -> str:
    """造一个"挂在 parent 名下"的子实例行（S6-a 的可见面按它判）。"""
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-09T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:%s.run_once" % role)


def test_the_boss_can_broadcast_a_stop_notice_on_the_public_channel(tmp_path):
    """正控：M 用 `{"message": {"to": "#public"}}` 广播一条叫停通知 ⇒ 落到公共频道。

    S6-a 之后多钉一格：那一条带发信人的台账号（`from_task_id`）—— 公聊的
    可见面就靠它判，没有它这一条谁也认不出来（`_do_message` 那一层会受控拒绝）。
    """
    note = {"message": {"to": ALL, "subject": "叫停",
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
    assert msgs[0]["to"] == ALL and msgs[0]["from"] == "M", msgs[0]
    assert "子进程" in str(msgs[0]["body"]), msgs[0]
    boss = [r for r in st.rows("tasks") if str(r.get("role")) == "M"
            and str(r.get("action")) == "run"]
    assert len(boss) == 1, boss
    assert str(msgs[0].get("from_task_id") or "") == str(boss[0]["task_id"]), msgs[0]


def test_only_the_senders_children_receive_the_broadcast(tmp_path):
    """正控 + 三态（业主 T20/T21 附二 乙）：收得到的是发信人的直接子代理。

    改前的口径是"每个同伴都收得到"（`#public` = 全角色）—— 那正是 T20 要治的形态：
    任何角色随手 `to=#public` 就等于全树广播。现在：子级收得到、别的角色收不到、
    孙级也收不到（要全树就逐层向下转发，级联是收件人的动作）。
    """
    note = {"message": {"to": ALL, "subject": "叫停", "body": "停"}}
    st, cond, registry, gw, root = _wired(tmp_path, [json.dumps(note, ensure_ascii=False),
                                                     json.dumps({"final": "已广播", "evidence": []},
                                                                ensure_ascii=False)])
    run_role("M", "广播叫停", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="bc"),
             session_root=root, workspace_root=str(root), sid="bc", max_steps=3, from_env=False)
    boss = next(str(r["task_id"]) for r in st.rows("tasks")
                if str(r.get("role")) == "M" and str(r.get("action")) == "run")
    child = _child_row(cond, boss, role="D", key="s6a@child")
    grand = _child_row(cond, child, role="E", key="s6a@grand")

    # 子代理 D 按"我父是谁"读 ⇒ 收得到（可见面 = 发信人的直接子代理）
    mine, problems = read_messages(root, "D", sid="bc", parent_task_id=boss)
    assert not problems, problems
    assert [m for m in mine if m.get("to") == ALL], "子代理必须收得到父的广播"
    assert mine[0].get("visibility") == "instance", mine[0]

    # 不是它子级的读者收不到：孙级（父是 D）、以及不知道自己父是谁的读者
    below, _ = read_messages(root, "E", sid="bc", parent_task_id=child)
    assert not [m for m in below if m.get("to") == ALL], "孙级不该直接收到（要逐层向下）"
    stranger, _ = read_messages(root, "A", sid="bc", parent_task_id="")
    assert not [m for m in stranger if m.get("to") == ALL], "没有父的读者不该收到"

    # 逐层向下：D 自己发一条公聊 ⇒ 只有它的子级 E 收得到，M 反过来收不到
    from agentflow.agent_loop import send_message

    _mid, problem = send_message(root, sender="D", to=ALL, subject="转发", body="往下传",
                                sid="bc", from_task_id=child)
    assert not problem, problem
    from_child, _ = read_messages(root, "E", sid="bc", parent_task_id=child)
    assert [m for m in from_child if str(m.get("subject")) == "转发"], from_child
    from_boss, _ = read_messages(root, "M", sid="bc", parent_task_id="")
    assert not [m for m in from_boss if str(m.get("subject")) == "转发"], from_boss

    # 投递登记照旧认这条 id（三态：读过的与没读过的分开）
    _digest, fresh, problems = inbox_digest(root, "D", sid="bc", parent_task_id=boss)
    assert not problems and fresh, (fresh, problems)
    assert not mark_delivered(root, "D", fresh, sid="bc")
    after, _ = read_messages(root, "D", sid="bc", parent_task_id=boss)
    assert bool([m for m in after if m.get("to") == ALL][0].get("delivered"))
    bystander, _ = read_messages(root, "A", sid="bc", parent_task_id="")
    assert not [m for m in bystander if m.get("to") == ALL], bystander
    assert grand and S.ROLES


def test_a_broadcast_does_not_interrupt_a_running_loop(tmp_path):
    """边界（必须写下来）：广播「打断不了」正在循环里的同伴 —— 叫停靠停机开关。

    每个角色的收件箱是 `run()` 开头读一次的（`inbox_digest`）：正在循环的 E 不会
    每个模型步都去看收件箱。所以"叫停"要真正打断在飞的工作，用的是
    `.agentflow-stop`（`stopctl`，`AgentLoop._user_stop_reason` 每步看一次）；
    广播负责的是"提醒同伴收工、并让它们停掉自己起的进程"那一条持久可见的通道。
    """
    from agentflow import stopctl

    note = {"message": {"to": ALL, "subject": "叫停", "body": "停"}}
    st, cond, registry, gw, root = _wired(tmp_path, [json.dumps(note, ensure_ascii=False),
                                                     json.dumps({"final": "已广播", "evidence": []},
                                                                ensure_ascii=False)])
    run_role("M", "广播叫停", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="bc"),
             session_root=root, workspace_root=str(root), sid="bc", max_steps=3, from_env=False)

    # 广播已经躺在盘上了，但"叫停"这件事在停机开关里「还是没有」
    assert stopctl.read_stop(root) is None, "广播不该等价于停机开关（两件事，两种通道）"
