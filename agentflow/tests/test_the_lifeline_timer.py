"""兜底计时器（lifeline）：框架的保活账，代理对它无感（业主 2026-10-29）。

三条判据：
① 被打断就续：一条事件把它判成到点、投递一次之后，立刻续一条新的，同一个台账号仍然恰好一条；
② 对模型不可见：它不进 `timers()`（模型查"我手上还有哪些表"读的就是它），也不进"缺目的"追问；
③ 不许被误判"目标已关"：它等的键是自己的台账号，而"我那一行已 done"是"收工后仍续"的常态 ——
   一旦去问 `target_state`，30 秒对账就把它打掉、零事件也醒，且一声不吭。
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from agentflow import clock as CLK


def _workspace() -> pathlib.Path:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="lifeline-"))
    (ws / "data").mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture(autouse=True)
def _handler():
    CLK.set_due_handler(lambda timer: {"note": "delivered"})
    yield
    CLK.set_due_handler(None)


def test_it_renews_itself_when_an_event_interrupts_it() -> None:
    ws = _workspace()
    me = "t-000001"
    first = CLK.arm_lifeline(ws, task_id=me, role="D")
    assert first.get("armed") is True, first
    rows = CLK.lifeline_of(ws, me)
    assert len(rows) == 1, rows
    again = CLK.arm_lifeline(ws, task_id=me, role="D")
    assert again.get("armed") is False and again.get("skipped") == "already", again

    CLK.observe_event("message", task_id=me, from_task_id="t-000002", role="M",
                      content="继续", message_id="m-1")
    timer = [t for t in CLK.book(ws).pending() if CLK.is_lifeline(t)][0]
    trigger, _why = timer.due_reason(CLK.now())
    assert "target_event" in trigger, trigger

    CLK.fire_due(ws)
    after = CLK.lifeline_of(ws, me)
    assert len(after) == 1, after
    assert after[0]["timer_id"] != rows[0]["timer_id"], (rows, after)


def test_the_model_cannot_see_it() -> None:
    ws = _workspace()
    me = "t-000001"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    assert CLK.timers_missing_purpose(ws, for_task_id=me) == []
    seen = {str(t.timer_id or "") for t in CLK.timers(ws)}
    mine = {str(r["timer_id"]) for r in CLK.lifeline_of(ws, me)}
    assert mine, "兜底计时器没挂上"
    assert not (seen & mine), (seen, mine)


def test_a_finished_account_is_not_read_as_a_closed_target() -> None:
    ws = _workspace()
    me = "t-000001"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    reasons = []
    for timer in CLK.book(ws).all():
        trigger, why = timer.due_reason(CLK.now(), ("closed", "", "目标已收工"))
        if trigger:
            reasons.append((timer.timer_id, trigger, why))
    assert reasons == [], reasons


def test_killing_it_is_permanent() -> None:
    """销号要把它撤掉，而且不许再长回来（"已销号 = 彻底没有了"）。

    这是三态里唯一不可逆的一步：撤掉 + 抑制标记必须同一次原子写落盘；
    此后 `arm_lifeline` 受控拒绝（skipped="suppressed"），连"被事件打断就续"那条路也走不通。
    """
    ws = _workspace()
    me = "t-000005"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    got = CLK.kill_lifeline(ws, task_id=me, reason="收工销号")
    assert got["checked"] is True and got["suppressed"] is True, got
    assert got["killed"], got
    assert CLK.lifeline_of(ws, me) == []
    assert CLK.lifeline_suppressed(ws, me) is True
    again = CLK.arm_lifeline(ws, task_id=me, role="D")
    assert again["armed"] is False and again["skipped"] == "suppressed", again

def test_consuming_it_calls_the_wake_hook_once() -> None:
    """兜底表被打掉 = 有与我有关的东西来了 ⇒ 叫醒钩子被调一次（带台账号）。

    时钟不 import 编排层：叫醒这件事由运行期注入的钩子做（`set_lifeline_wake_handler`）。
    没接钩子时也必须留可读理由，不许静默地"只续不叫"。
    """
    ws = _workspace()
    me = "t-000009"
    seen: list[str] = []
    CLK.set_lifeline_wake_handler(lambda tid: (seen.append(tid), {"reason": ""})[1])
    try:
        CLK.arm_lifeline(ws, task_id=me, role="D")
        CLK.observe_event("message", task_id=me, from_task_id="t-000001", role="M",
                          content="继续", message_id="m-9")
        CLK.fire_due(ws)
        assert seen == [me], seen
        assert len(CLK.lifeline_of(ws, me)) == 1, CLK.lifeline_of(ws, me)
    finally:
        CLK.set_lifeline_wake_handler(None)

def test_only_the_lifeline_is_silent_and_own_timers_are_standby() -> None:
    """只挂兜底计时器 ⇒ 静默；挂着模型自己起的表 ⇒ 待机（双向，防两档折平）。"""
    from agentflow import conductor as C

    ws = _workspace()
    me = "t-000001"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    row = {"task_id": me, "role": "D", "status": "done"}
    item = {"name": "D1", "task_id": me, "retired": False}

    first = C.agent_state(row=row, item=item,
                          wait=C.waiters_of(C.clock_waiters(str(ws)), [me]))
    assert first["state"] == C.AGENT_STATE_SILENT, first
    assert first["waiters"] == [], first

    CLK.start_timer(ws, after_sec=600.0, reason="等孩子回话", task_id=me, role="D")
    second = C.agent_state(row=row, item=item,
                           wait=C.waiters_of(C.clock_waiters(str(ws)), [me]))
    assert second["state"] == C.AGENT_STATE_STANDBY, second
    assert [w["id"] for w in second["waiters"]], second


def test_the_loop_start_entry_arms_exactly_one() -> None:
    """循环起跑处的入口 `_arm_lifeline_once`：挂上一条，第二次是 already。

    这一条只钉入口本身（用鸭子类型的替身，不跑真循环）。它和"接进 run()"是两件事：
    接进去之后 `test_timers_and_handoff_semantics` 仍然挂住（见 draft/113 的线索），
    所以入口可用、接线待定 —— 判据把这两件事分开写，免得以后误以为接线也验过了。
    """
    from agentflow.agent_loop import AgentLoop

    ws = _workspace()
    fake = type("L", (), {})()
    fake.my_task_id = "t-000007"
    fake.role = "D"
    fake.lifeline_reading = None
    fake._clock_root = lambda: str(ws)

    first = AgentLoop._arm_lifeline_once(fake)
    assert first["armed"] is True, first
    assert len(CLK.lifeline_of(ws, "t-000007")) == 1, CLK.lifeline_of(ws, "t-000007")
    second = AgentLoop._arm_lifeline_once(fake)
    assert second["skipped"] == "already", second
    assert fake.lifeline_reading == second, fake.lifeline_reading

def test_a_neighbours_event_does_not_wake_it() -> None:
    """射程：与它无关的事件不许把它叫醒（业主 2026-10-29 第 1 条）。

    兜底表等的是"与我有关"的东西；若写成通配（任何事件都算），一次广播会把所有
    静默代理一起叫醒，成本 = 事件 x 静默者数，"静默期间零模型调用"也就不成立了。
    """
    ws = _workspace()
    me, other = "t-000001", "t-000002"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    CLK.observe_event("message", task_id=other, from_task_id="t-000009", role="M",
                      content="与 D1 无关的一条广播", message_id="m-broadcast")
    timer = [t for t in CLK.book(ws).pending() if CLK.is_lifeline(t)][0]
    trigger, _why = timer.due_reason(CLK.now())
    assert trigger == "", f"无关事件把它叫醒了：{trigger}"


def test_only_one_lifeline_even_after_a_reload() -> None:
    """幂等：进程重启（重新从盘上装载）之后仍然恰好一条，重复挂不会再长一条。"""
    ws = _workspace()
    me = "t-000003"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    CLK.reset_books()
    again = CLK.arm_lifeline(ws, task_id=me, role="D")
    assert again["skipped"] == "already", again
    assert len(CLK.lifeline_of(ws, me)) == 1, CLK.lifeline_of(ws, me)


def test_the_purpose_exemption_does_not_leak() -> None:
    """豁免不外溢：只有框架那条兜底表免"缺目的"，模型自己起的表照样被追问。"""
    ws = _workspace()
    me = "t-000004"
    CLK.arm_lifeline(ws, task_id=me, role="D")
    CLK.start_timer(ws, after_sec=600.0, reason="", task_id=me, role="D")
    missing = CLK.timers_missing_purpose(ws, for_task_id=me)
    assert len(missing) == 1, missing
    assert str(missing[0]["kind"]) != CLK.LIFELINE_KIND, missing
