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
from agentflow import clockwakes as WAKE


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


def test_the_cross_process_boundary_is_written_down() -> None:
    """业主 2026-10-29：不做自动唤醒/跨进程扫描，但"手上有活没结"的代理要能被动唤起。

    完整口径两句，缺一句都会读歪：
      · 停机之后再起进程，不许自动把盘上所有还挂着兜底表的代理拉起来 ——
        M 那一侧的记忆还停在"全组停机"，自动唤醒会让 M 非常意外；
      · 但那些代理是需要唤醒的：靠 M 发指令，或它接到别的指令后被动唤起。
    断三件：
      · 源码里留着这条边界（不做自动唤醒 / 靠 M 发指令 / 被动）；
      · `clock` 没有任何"唤醒全部"的入口（没有扫描器就不会自动拉起全组）；
      · 被动唤起那条路是活的：注销"在跑"登记之后，一条与它有关的事件仍然会叫醒它。
    """
    import inspect

    # 2026-11-20（拆 clock.py）：兜底计时器那一层搬进 `clockwakes`，那段边界注释
    # 跟着实现在那一份里 —— 判据读两个模块的源码（同一处断言、一个字没改）。
    src = inspect.getsource(CLK) + inspect.getsource(WAKE)
    assert "不做自动唤醒" in src, "边界那句话被删掉了"
    assert "M 侧发指令" in src and "被动" in src, "边界那句话被改写成了半边"
    assert "听上级指挥" in src, "「由上级指挥、不许无脑全重启」那条裁定被删掉了"
    for name in ("wake_all", "wake_all_lifelines", "sweep_lifelines"):
        assert not hasattr(CLK, name), f"出现了自动唤醒的入口：{name}"

    ws = _workspace()
    me = "t-000012"
    seen: list[str] = []
    CLK.set_lifeline_wake_handler(lambda tid: (seen.append(tid), {"reason": ""})[1])
    try:
        CLK.arm_lifeline(ws, task_id=me, role="D")
        CLK.loop_ended(me)          # 这一趟已经收工（不再是"在跑"）
        CLK.observe_event("message", task_id=me, from_task_id="t-000001", role="M",
                          content="接着做那件没结的活", message_id="m-resume")
        CLK.fire_due(ws)
        assert seen == [me], seen
    finally:
        CLK.set_lifeline_wake_handler(None)


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


def test_it_does_not_wake_its_own_running_loop() -> None:
    """它自己的循环在跑 ⇒ 不另起一个同号循环（消息会进它自己的收件箱）。

    这是 2026-10-29 两次挂死的根因：兜底表在本趟循环里被打掉，再 resume 就复制出
    第二个自己，两个循环互相喂事件。判"它是不是在跑"用的是进程内登记
    （`loop_started` / `loop_ended`），不读台账 status —— 起跑那一瞬那一行可能还没落。
    """
    ws = _workspace()
    me = "t-000011"
    seen: list[str] = []
    CLK.set_lifeline_wake_handler(lambda tid: (seen.append(tid), {"reason": ""})[1])
    try:
        CLK.arm_lifeline(ws, task_id=me, role="D")
        CLK.loop_started(me)
        CLK.observe_event("message", task_id=me, from_task_id="t-000001", role="M",
                          content="在跑时来的一条", message_id="m-live")
        CLK.fire_due(ws)
        assert seen == [], f"它自己在跑，却被叫了一次：{seen}"
        assert len(CLK.lifeline_of(ws, me)) == 1, CLK.lifeline_of(ws, me)

        CLK.loop_ended(me)
        CLK.observe_event("message", task_id=me, from_task_id="t-000001", role="M",
                          content="收工后来的一条", message_id="m-after")
        CLK.fire_due(ws)
        assert seen == [me], seen
    finally:
        CLK.loop_ended(me)
        CLK.set_lifeline_wake_handler(None)

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
