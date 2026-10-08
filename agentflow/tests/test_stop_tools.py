# -*- coding: utf-8 -*-
"""判据（`draft/37` §128）：「停机是主控 M 的工具」 —— 优雅与强制，都要在 `conductor` 面上能调。

用户口径：

> 优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉
> 优雅停止和强制停止应该是主控 M 的 tool

这一组从「工具面」判（不是直接调 `stopctl` —— 那是实现，判据要判"主控够不够得着"）：

1. `conductor.stop` 在 M 的工具表里，且 `force` / `notify` 在它声明的参数里；
2. 优雅停止：落停机开关 + 「在公共频道广播叫停」（提醒同伴停掉自己起的子进程）+ 续跑简报；
3. `force=True`：落 `force=true` 的开关、「不等待收尾」，并按进程登记杀子进程（「排除自己」）；
4. 幂等：第二次不改第一次的理由，但 `force` 可以从 false 升到 true（用户改主意要直接杀）；
5. 步循环真的会停：开关落盘之后，`AgentLoop` 的下一步判据给出 `stop_file` / `force_stop`。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from agentflow import stopctl
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry


def _wired(tmp_path: pathlib.Path, *, sid: str = "stop-tool"):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    c = Conductor(st)
    reg = build_registry(store=st, conductor=c).registry
    return ws, st, c, reg


def _stop_spec(reg):
    return next(t for t in reg.for_role("M") if t.name == "conductor.stop")


def test_stop_is_a_boss_tool_with_both_modes_declared(tmp_path: pathlib.Path):
    """广告面：`conductor.stop` 在 M 的工具表里，且 `force` / `notify` 都声明了。"""
    _ws, _st, _c, reg = _wired(tmp_path)
    spec = _stop_spec(reg)
    props = (spec.params or {}).get("properties") or {}
    assert {"reason", "drain_sec", "force", "notify"} <= set(props), props
    assert props["force"]["type"] == "boolean", props["force"]


def test_graceful_stop_writes_the_switch_and_broadcasts_the_reminder(tmp_path: pathlib.Path):
    """优雅停止：落开关 + 广播"把你起的子进程停掉" + 落续跑简报。

    2026-10-08 晚（所有者 T18）：广播是留言（`#public` 的 `agent_message`），
    不再是集体插话 —— 插话收窄成"只有用户 → M"。留言同样"下一步就看到"：
    步边界的 `_hear()` 会把它并进这一步的结果。
    """
    from agentflow.agent_loop import PUBLIC, read_interjections, read_messages

    ws, st, _c, reg = _wired(tmp_path)
    res = reg.call("conductor.stop", role="M", reason="user")
    assert res.ok, res.error or res.data
    data = res.data
    # ① 开关落盘，内容写清"谁/为什么/是不是强制"
    state = stopctl.read_stop(ws)
    assert state is not None and state["reason"] == "user" and state["force"] is False, state
    assert state["by"] == "M", state
    # ② 叫停走公共频道的留言：每个角色都读得到它，正文点名"子进程"，
    #    并且它带"叫停类"标记（留言没有 `is_stop` 那一格 —— 标记在标题上）。
    for role in ("A", "B", "C", "D", "E", "G", "H"):
        got, problems = read_messages(ws, role, sid=None)
        assert not problems, problems
        mine = [m for m in got if m.get("subject") == "叫停"]
        assert mine, f"{role} 没收到叫停广播 ⇒ 同伴不知道自己该收工"
        assert "子进程" in str(mine[0].get("body")), mine[0]
    # ③ 插话通道里没有新东西（T18：主控不能发插话）
    for role in ("A", "D"):
        ij, _ = read_interjections(ws, role, sid=None)
        assert ij == [], ij
    assert data["notified"].startswith("m"), data
    # ④ 续跑简报：优雅停止与 kill 的区别就在它
    assert data["resume_brief"], data
    # ⑤ 强制那一半这一趟没做
    assert data["killed_children"] == {}, data


def test_force_stop_kills_registered_children_and_excludes_the_caller(tmp_path: pathlib.Path):
    """`force=True`：开关写 `force=true`、不等待收尾、按登记杀子进程，「排除调用者自己」。"""
    ws, _st, _c, reg = _wired(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        stopctl.register_pid(ws, "E", "child", pid=child.pid)
        stopctl.register_pid(ws, "M", "me")            # 主控自己也在登记里
        res = reg.call("conductor.stop", role="M", reason="user", force=True)
        assert res.ok, res.error or res.data
        data = res.data
        state = stopctl.read_stop(ws)
        assert state is not None and state["force"] is True, state
        killed = data["killed_children"]
        assert child.pid in killed["requested"], killed
        assert os.getpid() not in killed["requested"], "调用者自己不许被列进被杀名单"
        assert data["drained_sec"] == 0, "强制档不等待收尾"
        for r in killed["results"]:
            assert isinstance(r["killed"], bool) and r["via"], r
    finally:
        child.kill()
        child.wait(timeout=10)


def test_the_stop_reason_survives_but_force_can_escalate(tmp_path: pathlib.Path):
    """幂等 + 单向升级：理由取第一次那份；`force` 允许 false→true 升级一次。"""
    ws, _st, _c, reg = _wired(tmp_path)
    reg.call("conductor.stop", role="M", reason="user")
    first = stopctl.read_stop(ws)
    again = reg.call("conductor.stop", role="M", reason="budget")
    assert stopctl.read_stop(ws)["reason"] == first["reason"] == "user", "理由不许被覆盖"
    assert again.ok, again.error
    forced = reg.call("conductor.stop", role="M", reason="user", force=True)
    assert forced.ok, forced.error
    after = stopctl.read_stop(ws)
    assert after["force"] is True and after["reason"] == "user", after
    assert after.get("escalated_at"), after


def test_the_loop_stops_when_the_boss_asks_it_to(tmp_path: pathlib.Path):
    """步循环真的停：`conductor.stop` 之后，`AgentLoop` 的停机判据给出 stop_file/force_stop。

    这条把"工具"与"循环"接起来 —— 光有开关而没有循环去看它，就是 §125 那条真机读数
    （用户叫停之后它继续跑到第 123 步）。
    """
    from agentflow.agent_loop import AgentLoop, LlmSeam

    ws, st, _c, reg = _wired(tmp_path)
    from agentflow.agent_loop import LoopRun

    loop = AgentLoop(role="M", session_root=ws, registry=reg, seam=LlmSeam(
        role="M", session_root=ws, gateway=None, price=(0.0, 0.0), sid="stop-tool"),
        max_steps=1, workspace_root=str(ws), sid="stop-tool", store=st)

    assert loop._user_stop_reason(LoopRun(role="M", task="t")) == ""
    reg.call("conductor.stop", role="M", reason="user")
    assert loop._user_stop_reason(LoopRun(role="M", task="t")) == "stop_file"
    stopctl.request_stop(ws, reason="user", by="user", force=True)
    assert loop._user_stop_reason(LoopRun(role="M", task="t")) == "force_stop"
