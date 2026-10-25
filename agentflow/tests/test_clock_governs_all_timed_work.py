"""判据：主时钟控制了所有计时类工作（业主 2026-10-25 的第二次裁定）。

## 这个文件修的是什么

业主原话（唯一权威，两段一起）：

    「主时钟是否控制了所有计时类工作？如果不是，请规范所有计时类任务申请的形式为：
      等待时间（或等待谁）+目的（必填），例如M的巡视叫等待20分钟+周期性巡查。」

    「注意：让老的未依赖时钟的计时工具退场，当智能体忘填目的时不报错，只是让它追加目的。
      计时到点后向智能体发送信息"目的+等待时间+时间到"」

    「对于"等待谁"这个口径，是将父代理挂机等子代理正式化，一样填目的，父代理靠时钟发回的
      信息"目的+等待时间（这个是现场读数）+时间到"唤醒，并接收到子代理的反馈信息。
      注：子代理向父代理发消息或收工提交都应被时钟观测到。同理，子代理等待父代理答复也是走时钟」

    「这就是说挂机是将进程挂在时钟上」

## 改前红在哪

改前 `clock.timer_start` 的 `required` 是 `["after_sec", "reason"]`：
只给 `wait_for` 会被参数校验判成"缺少必填参数：after_sec"（本文件第 1 条红）；
`clock.periodic_start` / `clock.timer_purpose` / `clock.raw_wait_census` / `clock.await_io`
都不存在（第 4/6/8/9 条 `AttributeError`）；缺目的会被 `ClockParamError` 硬拒
（第 3 条红）；到点消息是"计时器到点：<reason>"，三样里只有目的一样（第 5 条红）；
`wait_for` 这一形与 `observed_events` 读数都不存在（第 10–14 条红）。

## 每条判据叫什么

1. `test_a_wait_for_alone_is_accepted`：只给 `wait_for` 也能起表，读数带 wait_for；
2. `test_a2_no_time_and_no_target_is_refused`：两个都不给 => 受控拒绝；
3. `test_b_both_time_and_target_are_refused`（负控）：两个都给 => 受控拒绝并说清二选一；
4. `test_c_missing_purpose_is_accepted_then_appended`（业主第二句的软处理，含反真空）；
5. `test_d_periodic_fires_repeatedly_until_stopped`：周期性巡查到点连续报醒、停后不再报；
6. `test_e_waits_outside_clock_is_zero_and_a_raw_sleep_turns_it_red`（反真空）；
7. `test_f_m_patrol_demo_three_wakes`：M 的"等 20 分钟 + 周期性巡查"三次报醒读数；
8. `test_g_due_message_has_all_three_parts`（目的 + 等待时间 + 时间到）；
9. `test_g2_due_message_when_purpose_missing`（负控）；
10. `test_h_parent_parks_and_child_message_wakes_it`（挂机 + 子发消息 + 反馈内容）；
11. `test_h2_child_submit_wakes_the_parked_parent`（收工提交，负控"不许只在台账里发生"）；
12. `test_h3_child_parked_on_parent_reply_is_woken`（对称，正控）；
13. `test_h4_timeout_when_the_target_never_answers`（到点没等到，三样齐全并点名等的是谁）；
14. `test_i_parked_waiter_has_no_steps_and_polling_is_detected`（挂机 vs 轮询的分界）；
15. `test_j_observed_events_counts_all_three_kinds`（三档计数 + 反真空）；
16. `test_k_no_non_clock_timing_tool_on_the_agent_surface`（老计时工具退场）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from agentflow import clock as C
from agentflow import schema as S
from agentflow.agent_loop import send_message
from agentflow.conductor import Conductor, SummonHandle, SummonResult, SummonStart, calling_as
from agentflow.store import Store
from agentflow.tools import ROLES, ToolRegistry

ROLES_WITH_M: tuple[str, ...] = tuple(ROLES) + (S.CONDUCTOR_ROLE,)

#: 到点消息的两种前缀（业主定死的两种形）。
DUE_PREFIXES: tuple[str, ...] = ("时间到：", "巡查时间到：")


# ============================================================ 夹具


def _mods():
    from agentflow.tools import clock_tools as CT

    return C, CT


def _setup(tmp_path, *, role: str = "M"):
    """临时工作区 + 从 2026-01-01T00:00:00Z 起步的假时钟 + 已装配的工具面。"""
    C, CT = _mods()
    root = pathlib.Path(tmp_path) / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    C.reset()
    C.reset_waits()
    C.reset_observed_events()
    C.reset_parked()
    fake = C.FakeClock(wall="2026-01-01T00:00:00+00:00", monotonic=1000.0)
    C.use(fake)
    reg = ToolRegistry(name="clock-governs")
    reg.bound_role = role
    CT.register(reg, store=store, root=root)
    return store, fake, reg, root


def _open_task(store: Store, role: str = "M", detail: str = "顶趟") -> str:
    return Conductor(store).open_top_level_run(role, detail)


def _due_notices(store: Store) -> list[dict]:
    return [r for r in store.rows("tasks")
            if str(r.get("kind") or "") == "notice"
            and str(r.get("detail") or "").startswith(DUE_PREFIXES)]


def _fires(store: Store) -> list[str]:
    return [str(r.get("detail") or "") for r in _due_notices(store)]


# ============================================================ 1 / 2 / 3 申请形状


def test_a_wait_for_alone_is_accepted(tmp_path) -> None:
    """只给 wait_for（等谁）也能起表 —— 改前红：required 里逼着要 after_sec。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    child = _open_task(store, "D", "子代理的活")
    with calling_as(me, "M"):
        got = reg.call("clock.timer_start", wait_for=f"task:{child}",
                       reason="等子代理交差")
    assert got.ok is True, got.error
    assert got.data["wait_for"] == f"task:{child}", got.data
    assert got.data["wait_for_resolved"] == f"task:{child}", got.data
    assert got.data["after_sec"] is None, got.data
    assert got.data["due_at"] == "", "等谁的那一条没有钟点，due_at 必须是空串（不是假时刻）"
    assert got.data["park_state"] == "parked", got.data


def test_a2_no_time_and_no_target_is_refused(tmp_path) -> None:
    """两个都不给 => 受控拒绝（不是"起一条永不到点的表"）。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        got = reg.call("clock.timer_start", reason="没给时间也没给对象")
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == "param_error", got.to_dict()
    assert "after_sec" in str(got.error) and "wait_for" in str(got.error), got.error
    assert C.timers(root) == [], "受控拒绝不许留下半条计时器"


def test_b_both_time_and_target_are_refused(tmp_path) -> None:
    """负控：after_sec 与 wait_for 都给 => 受控拒绝，并说清只能选一个。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    child = _open_task(store, "D", "子代理的活")
    with calling_as(me, "M"):
        got = reg.call("clock.timer_start", after_sec=60.0,
                       wait_for=f"task:{child}", reason="两个都给")
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == "param_error", got.to_dict()
    text = str(got.error)
    assert "只能选一个" in text, text
    assert "after_sec" in text and "wait_for" in text, text
    assert C.timers(root) == [], "受控拒绝不许留下半条计时器"


# ============================================================ 4 缺目的：先受理再追加


def test_c_missing_purpose_is_accepted_then_appended(tmp_path, monkeypatch) -> None:
    """缺目的不报错：照常受理、读数追问；补一句之后同一条被填上（不是新建一条）。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        got = reg.call("clock.timer_start", after_sec=1200.0)
    assert got.ok is True, got.error
    assert got.data["purpose_missing"] is True, got.data
    assert got.data["purpose"] == "", got.data
    assert "补一句目的" in got.data["purpose_prompt"], got.data
    timer_id = str(got.data["timer_id"])

    # 下一次读数里还在追问（不是只在起表那一次说一声）。
    with calling_as(me, "M"):
        now = reg.call("clock.now")
    pending = now.data["purpose_pending"]
    assert any(item.get("id") == timer_id for item in pending), pending

    # 补一句目的：同一个编号，不是新建一条。
    with calling_as(me, "M"):
        filled = reg.call("clock.timer_purpose", entry_id=timer_id,
                          purpose="等待20分钟+周期性巡查")
    assert filled.ok is True, filled.error
    assert filled.data["filled"] is True, filled.data
    assert filled.data["purpose_missing"] is False, filled.data
    assert filled.data["purpose"] == "等待20分钟+周期性巡查", filled.data
    book = C.book(root)
    assert [t.timer_id for t in book.all()] == [timer_id], "补目的不许新建一条"
    assert book.get(timer_id).purpose == "等待20分钟+周期性巡查"

    # 反真空：把"补目的"打桩成"什么也没做" => 上面那条正控必须红。
    C2, _ = _mods()
    store2, fake2, reg2, root2 = _setup(tmp_path / "novacuum")
    me2 = _open_task(store2)
    with calling_as(me2, "M"):
        again = reg2.call("clock.timer_start", after_sec=60.0)
    tid2 = str(again.data["timer_id"])
    with monkeypatch.context() as m:
        m.setattr(C, "set_purpose", lambda *a, **k: (None, "not_found"), raising=True)
        with calling_as(me2, "M"):
            stubbed = reg2.call("clock.timer_purpose", entry_id=tid2, purpose="补一句")
        assert stubbed.data["filled"] is False, stubbed.data
        assert C.book(root2).get(tid2).purpose_missing is True, \
            "把补目的打桩成空之后，目的居然被填上了 —— 正控不承重"


# ============================================================ 5 / 7 周期性巡查


def test_d_periodic_fires_repeatedly_until_stopped(tmp_path) -> None:
    """周期性巡查：到点连续报醒、fires 递增、停后不再报 —— 改前红：没有这一形。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        started = reg.call("clock.periodic_start", every_sec=1200.0,
                           purpose="周期性巡查")
    assert started.ok is True, started.error
    periodic_id = str(started.data["periodic_id"])
    assert periodic_id.startswith("pd-"), started.data
    assert started.data["fires"] == 0 and started.data["stopped_reason"] == "", started.data
    assert started.data["purpose"] == "周期性巡查"

    fake.advance(1200.0)
    assert len(_fires(store)) == 1, _fires(store)
    fake.advance(1200.0)
    assert len(_fires(store)) == 2, _fires(store)
    # 一次前进 3600 秒（三拍）=> 三拍都要报出去，不许只报一次。
    fake.advance(3600.0)
    assert len(_fires(store)) == 5, _fires(store)
    with calling_as(me, "M"):
        listed = reg.call("clock.timer_list")
    row = next(p for p in listed.data["periodics"] if p["periodic_id"] == periodic_id)
    assert row["fires"] == 5, row
    assert row["every_sec"] == 1200.0 and row["purpose"] == "周期性巡查", row

    with calling_as(me, "M"):
        stopped = reg.call("clock.periodic_stop", periodic_id=periodic_id,
                           reason="这一轮巡视做完了")
    assert stopped.ok is True and stopped.data["stopped"] is True, stopped.data
    assert stopped.data["stopped_reason"] == "这一轮巡视做完了", stopped.data
    fake.advance(7200.0)
    assert len(_fires(store)) == 5, "停掉之后仍然在报醒"
    # 再停一次是"查过了、已经停过"，不是第二次停成功。
    with calling_as(me, "M"):
        again = reg.call("clock.periodic_stop", periodic_id=periodic_id)
    assert again.data["stopped"] is False and again.data["state"] == "stopped", again.data


def test_f_m_patrol_demo_three_wakes(tmp_path, capsys) -> None:
    """M 的巡视口径：等 20 分钟 + 周期性巡查（every_sec=1200），贴三次报醒读数。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        started = reg.call("clock.periodic_start", every_sec=1200.0,
                           purpose="周期性巡查")
    periodic_id = str(started.data["periodic_id"])
    readings = []
    for n in (1, 2, 3):
        fake.advance(1200.0)
        with calling_as(me, "M"):
            listed = reg.call("clock.timer_list")
        row = next(p for p in listed.data["periodics"] if p["periodic_id"] == periodic_id)
        readings.append({"第几次": n, "fires": row["fires"], "next_at": row["next_at"],
                         "报醒": _fires(store)[-1]})
    print("巡视读数：")
    for item in readings:
        print(f"  {item['第几次']} | fires={item['fires']} | next_at={item['next_at']}")
        print(f"       {item['报醒']}")
    assert [r["fires"] for r in readings] == [1, 2, 3], readings
    for item in readings:
        text = item["报醒"]
        assert text.startswith("巡查时间到：周期性巡查"), text
        assert re.search(r"第 \d+ 次", text), text
        assert "每 20 分钟一次" in text, text


# ============================================================ 6 等待账与普查


def test_e_waits_outside_clock_is_zero_and_a_raw_sleep_turns_it_red(tmp_path) -> None:
    """`waits_outside_clock` 改后为 0；把一处改回 time.sleep => 该读数 > 0 并点名位置。"""
    C, _ = _mods()
    real = C.coverage(refresh=True)
    assert real["checked"] is True, real
    assert real["waits_outside_clock"] == 0, real["waits_outside_where"]
    assert real["files_scanned"] > 100, real["files_scanned"]
    assert real["waits_on_primitives"] > 0, "普查连阻塞型等待都没扫到 => 判据在空转"
    # 业主那句话现在是成立的：所有计时类工作都在主时钟的账上（`covers_all_timed_work`
    # 的定义没有为凑它而改：零例外 + 零缺口才算）。将来谁加一处没进账的等待，本条红。
    assert real["covers_all_timed_work"] is True, real["reason"]
    assert real["waits_exempt_count"] == 0, real["waits_exempt"]
    assert real["waits_on_primitives_ungoverned"] == 0, real["waits_exempt"]

    # 反真空：造一棵"把退避重试改回 time.sleep"的树，同一个判据必须点出它。
    stub = pathlib.Path(tmp_path) / "stub"
    (stub / "agentflow").mkdir(parents=True)
    (stub / "agentflow" / "fetch.py").write_text(
        '"""桩：把 fetch 的退避重试改回 time.sleep（反真空用）。"""\n'
        "import time\n"
        "\n"
        "\n"
        "def _default_sleep(seconds: float) -> None:\n"
        "    time.sleep(seconds)\n",
        encoding="utf-8")
    stubbed = C.coverage(source_root=[stub], refresh=True)
    assert stubbed["waits_outside_clock"] == 1, stubbed
    where = stubbed["waits_outside_where"][0]
    assert where.startswith("agentflow/fetch.py:"), where
    assert "_default_sleep" in where, where
    assert stubbed["covers_all_timed_work"] is False, stubbed
    C.set_census_roots(None)
    C.raw_wait_census(refresh=True)


def test_e2_framework_waits_are_on_the_ledger(tmp_path) -> None:
    """框架内部的等待真的记进同一本账（读数是"记了几条、几秒"，不是一句声明）。"""
    C, _ = _mods()
    C.reset_waits()
    C.note_wait(12.5, "判据：记一条等待", kind="test", where="tests.test_clock_governs")
    got = C.waits()
    assert got["calls"] == 1, got
    assert abs(got["asked_sec"] - 12.5) < 1e-6, got
    # 假时钟下 await_io 不真等（判据不该等真时间），但账照记。
    fake = C.FakeClock()
    C.use(fake)
    C.await_io(30.0, "判据：假时钟下不真等", kind="test", where="tests.test_clock_governs")
    row = next(r for r in C.waits()["rows"] if r["purpose"] == "判据：假时钟下不真等")
    assert row["calls"] == 1 and row["skipped"] == 1, row
    assert abs(row["asked_sec"] - 30.0) < 1e-6, row


# ============================================================ 8 / 9 到点消息格式


def test_g_due_message_has_all_three_parts(tmp_path) -> None:
    """到点消息里三样齐全：目的 + 等待时间（现场读数）+ 时间到。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        started = reg.call("clock.timer_start", after_sec=1200.0,
                           reason="等待20分钟+周期性巡查")
    timer_id = str(started.data["timer_id"])
    fake.advance(1200.0)      # advance 自己会跑一次 fire_due（到点即投递）
    timer = C.book(root).get(timer_id)
    assert timer.state == "fired", timer.state
    text = timer.message
    assert text.startswith("时间到：等待20分钟+周期性巡查"), text
    assert "等了 20 分钟" in text, text
    assert re.search(r"起于 \d\d:\d\d:\d\d，到于 \d\d:\d\d:\d\d", text), text
    assert _fires(store)[0] == text, "mailbox 的 detail 必须是同一句"
    wake = C.read_wakes(root)["events"][0]
    assert wake["message"] == text, wake
    assert wake["purpose"] == "等待20分钟+周期性巡查", wake


def test_g2_due_message_when_purpose_missing(tmp_path) -> None:
    """负控：缺目的那一趟，目的位置写"（目的未填）"并追问补一句。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    me = _open_task(store)
    with calling_as(me, "M"):
        reg.call("clock.timer_start", after_sec=60.0)
    fake.advance(60.0)
    text = _fires(store)[0]
    assert text.startswith(f"时间到：{C.PURPOSE_MISSING_TEXT}｜等了 1 分钟"), text
    assert "补一句目的" in text, text
    assert C.PURPOSE_PROMPT in text, text


# ============================================================ 10–13 挂机与唤醒


def _park(reg, me: str, **kwargs):
    with calling_as(me, "M"):
        return reg.call("clock.timer_start", **kwargs)


def test_h_parent_parks_and_child_message_wakes_it(tmp_path) -> None:
    """父挂机等子；子发一条消息那一刻父被唤醒，消息带目的+现场时长+时间到+子的话。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父代理这一趟")
    child = _open_task(store, "D", "子代理这一趟")
    parked = _park(reg, parent, wait_for=f"task:{child}", reason="等 D 交回结论")
    assert parked.ok is True, parked.error
    timer_id = str(parked.data["timer_id"])
    fake.advance(90.0)          # 挂了 90 秒，子还没说话
    assert C.fire_due(root)["fired"] == [], "子还没说话，父不该被唤醒"

    # 子给父发消息（真实写路径：agent_loop.send_message -> sessions.append -> 时钟旁路）。
    msg_id, problem = send_message(
        root, sender="D", to="M", subject="交差",
        body="命题 P 的证明已经落盘，见 out/proof.md", from_task_id=child)
    assert problem == "", problem
    assert msg_id.startswith("m"), msg_id

    fires = C.fire_due(root)["fired"]
    assert [f["timer_id"] for f in fires] == [timer_id], fires
    fire = fires[0]
    assert fire["woke_reason"] == "event", fire
    text = fire["message"]
    assert text.startswith("时间到：等 D 交回结论"), text
    assert "等了 1 分钟 30 秒" in text, text
    assert "它说的是" in text and "命题 P 的证明已经落盘" in text, text
    assert C.book(root).get(timer_id).park_state == "woke"


def test_h2_child_submit_wakes_the_parked_parent(tmp_path) -> None:
    """负控：子收工提交也唤醒父（不许只在台账里悄悄发生），消息带交的摘要。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父代理这一趟")
    child = _open_task(store, "D", "子代理这一趟")
    parked = _park(reg, parent, wait_for=f"task:{child}", reason="等 D 收工")
    assert parked.ok is True, parked.error
    before = C.observed_events()["counts"]
    handle = SummonHandle(SummonStart(role="D", action="prove", params={},
                                      parent_task_id=parent, task_id=child))
    handle.settle(SummonResult(task_id=child, role="D", action="prove",
                               status="done", outcome="proved",
                               detail="交付：命题 P 已证，证据在 out/proof.md"))
    after = C.observed_events()["counts"]
    assert after["submit"] == before["submit"] + 1, (before, after)
    fires = C.fire_due(root)["fired"]
    assert [f["timer_id"] for f in fires] == [str(parked.data["timer_id"])], fires
    text = fires[0]["message"]
    assert "它交的是" in text and "命题 P 已证" in text, text
    assert fires[0]["woke_reason"] == "event", fires[0]


def test_h3_child_parked_on_parent_reply_is_woken(tmp_path) -> None:
    """对称正控：子挂机等父答复，父答复那一刻子被唤醒。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父代理这一趟")
    child = _open_task(store, "D", "子代理这一趟")
    with calling_as(child, "D"):
        parked = reg.call("clock.timer_start", wait_for=f"task:{parent}",
                          reason="等 M 答复要不要换方向")
    assert parked.ok is True, parked.error
    msg_id, problem = send_message(
        root, sender="M", to="D", subject="答复",
        body="不换方向，把这条引理补完", from_task_id=parent, reply_to="m-000009")
    assert problem == "", problem
    fires = C.fire_due(root)["fired"]
    assert [f["timer_id"] for f in fires] == [str(parked.data["timer_id"])], fires
    assert fires[0]["woke_reason"] == "event", fires[0]
    assert "不换方向" in fires[0]["message"], fires[0]


def test_h4_timeout_when_the_target_never_answers(tmp_path) -> None:
    """负控：到点还没等到 => timeout 那条三样齐全，并写清等的是谁。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父代理这一趟")
    child = _open_task(store, "D", "子代理这一趟")
    parked = _park(reg, parent, wait_for=f"task:{child}", max_wait_sec=600.0,
                   reason="等 D 交回结论（最多等 10 分钟）")
    assert parked.ok is True, parked.error
    timer_id = str(parked.data["timer_id"])
    fake.advance(600.0)       # 上限到了：advance 里的 fire_due 就把它叫醒了
    timer = C.book(root).get(timer_id)
    assert timer.state == "fired", timer.state
    assert timer.woke_reason == "timeout", timer.woke_reason
    text = timer.message
    assert text.startswith("时间到：等 D 交回结论"), text
    assert "等了 10 分钟" in text, text
    assert f"等的是 task:{child}" in text, text
    assert "它还没交/没说" in text, text


def test_i_parked_waiter_has_no_steps_and_polling_is_detected(tmp_path) -> None:
    """挂机 = 挂在时钟上（不是轮询）：挂机区间 steps/calls 为 0，parked_sec > 0。

    反真空：把"挂机"换成"每 5 秒轮一次"（`observe_work` 收到一条 agent_step）⇒
    `parked_steps` 必须 > 0，于是"== 0"那条断言红 —— 这个判据本身是承重的。
    """
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父代理这一趟")
    child = _open_task(store, "D", "子代理这一趟")
    parked = _park(reg, parent, wait_for=f"task:{child}", reason="等 D 交回结论")
    timer_id = str(parked.data["timer_id"])

    fake.advance(300.0)          # 挂 5 分钟，中间什么都不发生
    C.observe_work({"kind": "agent_step", "task_id": child, "role": "D"})
    waiter = next(w for w in C.waiters(root)["waiters"] if w["timer_id"] == timer_id)
    assert waiter["park_state"] == "parked", waiter
    assert float(waiter["parked_sec"]) == pytest.approx(300.0, abs=1.0), waiter
    assert int(waiter["parked_steps"]) == 0, "挂机期间这一趟居然跑了回合"
    assert int(waiter["parked_calls"]) == 0, "挂机期间这一趟居然调了模型"

    # 反真空：轮询会留下回合 => 同一个读数必须 > 0。
    C.observe_work({"kind": "agent_step", "task_id": parent, "role": "M"})
    waiter = next(w for w in C.waiters(root)["waiters"] if w["timer_id"] == timer_id)
    assert int(waiter["parked_steps"]) == 1, waiter
    assert int(waiter["parked_calls"]) == 1, waiter

    # `active = running + parked`：挂机仍算活跃，但要与"正在跑"分开列。
    with calling_as(parent, "M"):
        now = reg.call("clock.now")
    assert now.data["parked"] == 1, now.data
    assert now.data["active"] == (now.data["running"] or 0) + 1, now.data


def test_j_observed_events_counts_all_three_kinds(tmp_path, monkeypatch) -> None:
    """观测窗三档计数：a/b/c 跑过之后 message / submit / reply 都 > 0（反真空）。"""
    C, _ = _mods()
    store, fake, reg, root = _setup(tmp_path)
    parent = _open_task(store, "M", "父")
    child = _open_task(store, "D", "子")
    send_message(root, sender="D", to="M", subject="说话", body="我还在做",
                 from_task_id=child)
    SummonHandle(SummonStart(role="D", action="prove", parent_task_id=parent,
                             task_id=child)).settle(
        SummonResult(task_id=child, role="D", action="prove", status="done",
                     outcome="proved", detail="交付：做完了"))
    send_message(root, sender="M", to="D", subject="答复", body="继续",
                 from_task_id=parent, reply_to="m-000001")
    counts = C.observed_events()["counts"]
    assert counts["message"] >= 1, counts
    assert counts["submit"] >= 1, counts
    assert counts["reply"] >= 1, counts

    # 反真空：把"投事件"打桩成空 => 三档全 0，上面三条必红。
    C.reset_observed_events()
    with monkeypatch.context() as m:
        m.setattr(C, "observe_event", lambda *a, **k: None, raising=True)
        send_message(root, sender="D", to="M", subject="说话", body="我还在做",
                     from_task_id=child)
    assert C.observed_events()["counts"] == {"message": 0, "submit": 0, "reply": 0}, \
        "把投事件打桩成空之后计数还在涨 —— 反真空不成立"


# ============================================================ 老计时工具退场

#: 已经登记、但今天还没退掉的非时钟计时入口：工具名 -> (计时参数, 挡住没改的理由)。
#:
#: 业主 2026-10-25：「让老的未依赖时钟的计时工具退场」。今天代理可见面上一处都没有
#: （见下面 `CLOCK_BACKED_TIMING_PARAMS`：最后那一处的等待已经交给主时钟，只剩参数名）。
#: 这张表是封闭的：多一处就红。
DECLARED_LEGACY_TIMING: dict[str, tuple[str, str]] = {}

#: 还带"时间预算参数"、但等待已经交给主时钟的工具：工具名 -> (参数, 它改走的入口)。
#:
#: `conductor.stop(drain_sec=…)` 是最后退下来的那一处：它原来在
#: `tools/conductor_tools.py` 里就地 `time.sleep(0.05)` 排水（不在任何账上），
#: 2026-10-25 业主放行后改成 `clock.await_io(0.05, "等正在跑的活收工（优雅停止）",
#: kind="drain", where="conductor.stop")` —— 参数还是那个参数（上限仍然是 `drain_sec`），
#: 但每一次等待现在都记进 `out/clock/waits.json`。判据在下面同时读源码（那一行真的在）
#: 与普查（那个模块里真的没有原始 sleep 了）：
#: 一张永不生效的登记表会腐烂成"看起来还在挡着什么"，所以两处都要核。
CLOCK_BACKED_TIMING_PARAMS: dict[str, tuple[str, str]] = {
    "conductor.stop": ("drain_sec", 'kind="drain", where="conductor.stop"'),
}

#: 外部进程的超时预算不算"计时类任务"：它没有"到点报醒"这回事，等的是那个进程本身。
EXTERNAL_BUDGET_PARAMS: tuple[str, ...] = ("timeout", "timeout_sec")


def _full_registry(store, root):
    """整张工具面（`TOOL_ROLES` 那一档，含主控 M）—— 退场判据要扫全树，不许只看时钟。"""
    from agentflow.tools import build_registry

    build = build_registry(store=store, workspace_root=root,
                           roles=tuple(ROLES_WITH_M), strict=False)
    return build.registry


def test_k_no_non_clock_timing_tool_on_the_agent_surface(tmp_path) -> None:
    """代理可见面上，计时只有 clock.* 这一处（逐个点名今天有哪些、退到哪去了）。"""
    C, _ = _mods()
    store, fake, _partial, root = _setup(tmp_path)
    reg = _full_registry(store, root)
    names = list(reg.names())
    assert len(names) >= 100, f"工具面只装了 {len(names)} 件 —— 退场判据不完整"

    timing_param = re.compile(
        r"(timeout|wait|sleep|drain|poll|interval|every|delay)", re.I)
    timing_name = re.compile(r"(^|\.)(sleep|timer|wait|alarm|remind|schedule)$", re.I)
    found: dict[str, list[str]] = {}
    for name in names:
        if name.startswith("clock."):
            continue
        spec = reg.get(name)
        props = (spec.params or {}).get("properties") or {}
        timed = sorted(p for p in props if timing_param.search(str(p)))
        timed = [p for p in timed if p not in EXTERNAL_BUDGET_PARAMS]
        if timed or timing_name.search(name):
            found[name] = timed

    legacy = {name: [param] for name, (param, _why)
              in DECLARED_LEGACY_TIMING.items()}
    backed = {name: [param] for name, (param, _where)
              in CLOCK_BACKED_TIMING_PARAMS.items()}
    assert found == {**legacy, **backed}, (
        "代理可见面上的计时入口变了。今天只允许两类：已退掉的（"
        f"{sorted(legacy)}）与等待已交给主时钟的（{sorted(backed)}）；实际扫到 {found}。"
        "新增的必须退掉（改用 clock.periodic_start / clock.timer_start）或把等待改成"
        "clock.await_io 并登记在 CLOCK_BACKED_TIMING_PARAMS 里")

    # 交给主时钟的那一处：源码里真的有那一行；而那个模块里真的没有原始 sleep 了
    # （用 AST 普查判，不是 grep —— 上面那段注释里就写着 `time.sleep` 这几个字）。
    from agentflow.tools import conductor_tools as SC

    text = pathlib.Path(SC.__file__).read_text(encoding="utf-8")
    for name, (_param, marker) in CLOCK_BACKED_TIMING_PARAMS.items():
        assert "CLK.await_io(0.05" in text, f"{name} 的排水轮询没有走 clock.await_io"
        assert marker in text, f"{name} 的登记与源码对不上：找不到 {marker}"
    census = C.raw_wait_census(refresh=True)
    raw = [f["where"] for f in census["findings"] + census["exempt"]
           if f["path"] == "agentflow/tools/conductor_tools.py"
           and str(f["form"]).startswith("sleep")]
    assert not raw, f"conductor_tools 里还有原始 sleep：{raw}"

    # 老名字被拒，并指名改用 clock（退役提示是唯一落点）。
    retired = {"clock.sleep": "clock.timer_start", "clock.wait": "clock.timer_start",
               "sleep": "clock.timer_start", "clock.timer": "clock.timer_start",
               "clock.remind": "clock.periodic_start"}
    for old, new in retired.items():
        got = reg.call(old)
        assert got.ok is False, f"{old} 居然还能调"
        hint = C.retire_hint(old)
        assert new in hint, hint
        assert "计时只有主时钟这一处" in hint, hint

    # 时钟自己的九件都在，且周期性那两件在 M 的面上（业主点名的用法）。
    clock_names = sorted(n for n in names if n.startswith("clock."))
    assert clock_names == sorted([
        "clock.now", "clock.timer_start", "clock.alarm_start", "clock.timer_list",
        "clock.timer_cancel", "clock.periodic_start", "clock.periodic_stop",
        "clock.timer_purpose", "clock.wait_any"]), clock_names
    m_face = {s.name for s in reg.for_role("M")}
    assert "clock.periodic_start" in m_face and "clock.periodic_stop" in m_face, m_face


#: 时钟的九件（2026-10-27 第二批放行后）：D-53 的五件 + 周期性两件 + 补目的一件 +
#: 「等待任意计时器返回」那一件（业主第三条裁定的后半个动作）。
CLOCK_NINE: frozenset[str] = frozenset({
    "clock.now", "clock.timer_start", "clock.alarm_start", "clock.timer_list",
    "clock.timer_cancel", "clock.periodic_start", "clock.periodic_stop",
    "clock.timer_purpose", "clock.wait_any",
})


def test_l_readonly_roles_get_all_nine_clock_tools(tmp_path) -> None:
    """只读角色 C/H/V 也拿到九件 `clock.*`，且靠的是通用集合不是例外表。

    改前红（两档，都是实测过的形态）：
    - 2026-10-25 之前：三条登记补进 `tools.UNIVERSAL_TOOLS` 之前，C/H/V 的工具面上只有
      五件（`for_role` 按 `side_effect="write_local"` 把新加的三件剥掉）—— 那时红在
      `CLOCK_NINE - got == {periodic_start, periodic_stop, timer_purpose, wait_any}`；
    - 2026-10-27 第二批之前：`clock.wait_any` 这一件根本不存在，于是红在
      `CLOCK_NINE - got == {wait_any}`。它同时也是"通用轴不靠例外表"这条判据的
      第二个正样本：新增的通用工具必须同时满足"在 `UNIVERSAL_TOOLS` 里"与
      "不在 `READONLY_CALL_EXCEPTIONS` 里"。
    """
    from agentflow.tools import (BOOKKEEPING_TABLES, READONLY_CALL_EXCEPTIONS,
                                 UNIVERSAL_TOOLS, is_universal_tool,
                                 universal_tool_tables)

    C, _ = _mods()
    store, fake, _partial, root = _setup(tmp_path)
    reg = _full_registry(store, root)
    for role in ("C", "H", "V"):
        got = {s.name for s in reg.for_role(role)}
        missing = CLOCK_NINE - got
        assert not missing, f"只读角色 {role} 的面上缺 {sorted(missing)}"
        exempt = {n for n, _w in READONLY_CALL_EXCEPTIONS.get(role, ())}
        assert not (CLOCK_NINE & exempt), f"{role} 的例外表里出现了 clock 条目"
        not_universal = sorted(n for n in CLOCK_NINE if not is_universal_tool(n))
        assert not not_universal, f"这些 clock 工具没有登记成通用能力：{not_universal}"
        # 件数就是九件（不是"至少九件"里恰好被别的路径补上的）：这一格是业主施工单里
        # 那个 8 → 9 的读数本体。
        assert len({n for n in got if n.startswith("clock.")}) == len(CLOCK_NINE), \
            sorted(n for n in got if n.startswith("clock."))
    # 写集硬约束：登记的写集不许越出簿记表（`periodic_start` 写 tasks notice 行 = 簿记；
    # `wait_any` 只写 `out/clock/wait_any.json` 这份意图账 ⇒ 空集）。
    for name in sorted(CLOCK_NINE):
        tables = universal_tool_tables(name)
        assert tables is not None, name
        assert set(tables) <= set(BOOKKEEPING_TABLES), (name, tables)
    assert set(universal_tool_tables("clock.periodic_start") or ()) == {"tasks"}, \
        universal_tool_tables("clock.periodic_start")
    assert set(universal_tool_tables("clock.wait_any") or ()) == set(), \
        universal_tool_tables("clock.wait_any")
    assert set(UNIVERSAL_TOOLS) >= CLOCK_NINE, \
        sorted(CLOCK_NINE - set(UNIVERSAL_TOOLS))


def test_m_store_atomic_retry_is_on_the_ledger(tmp_path, monkeypatch) -> None:
    """store 的原子替换退避重试：语义一字不改（仍是重试到成功），且这一次等待记进账。

    业主 2026-10-25 放行 `store.py`（FC-27，由人审担保）之后，那处 `time.sleep` 换成
    `clock.await_io(kind="atomic_retry", where="store._atomic_write")`。本条同时钉两件：

    - 语义：`os.replace` 头一次失败仍会重试并最终写成（`calls == 2`）；
    - 账：这一次等待以 `kind="atomic_retry"` 出现在 `clock.waits()` 里。

    反真空：把那一处改回 `time.sleep` ⇒ 第二条断言立刻红（`calls` 仍是 2）。
    """
    import os

    from agentflow import clock as C2
    from agentflow.store import Store as StoreCls

    root = pathlib.Path(tmp_path) / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = StoreCls(root)
    store.init()
    C2.reset_waits()
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(32, "目标文件正被另一个进程拿着")
        return real_replace(src, dst)

    monkeypatch.setattr("agentflow.store.os.replace", flaky)
    store._atomic_write(root / "data" / "probe.json", {"rows": []})
    assert calls["n"] == 2, f"退避重试的语义变了：replace 只被调了 {calls['n']} 次"
    rows = [r for r in C2.waits()["rows"] if str(r["kind"]) == "atomic_retry"]
    assert rows, f"store 的退避重试没进主时钟的账：{C2.waits()['rows']}"
    assert rows[0]["where"] == "store._atomic_write", rows[0]
    assert "原子替换失败后的退避重试" in rows[0]["purpose"], rows[0]


def test_n_three_process_waits_are_on_the_ledger(tmp_path, monkeypatch) -> None:
    """三处 `communicate(timeout=)` 进账：一行一个位置，记的是实测耗时不是 timeout。

    业主 2026-10-25 放行后，`cancellation.run_cancellable` 与
    `agent_e._run_script` 的两处等待都用 `clock.note_process_wait(elapsed, where=…)`
    记一条（`kind="external_process"`）。阻塞方式一字未改（换成 `await_io` 会毁取消语义：
    "进程一退就返回"会变成"睡满才返回"）。

    三条读数长这样（`where` 各自独立，不许合成一行）：

    - `cancellation.run_cancellable`：子进程 3 秒、预算 0.3 秒 ⇒ 走超时路径；
    - `agent_e._run_script/poll`：0.2 秒的轮询片（脚本比它长）；
    - `agent_e._run_script/final`：看到停机开关之后最多 15 秒的收尾等待（实测远小于 15）。

    反真空：把 `note_process_wait` 打桩成"什么也不记" ⇒ 三条全没，本判据红。
    """
    import sys

    from agentflow import cancellation as CX
    from agentflow import clock as C2
    from agentflow import stopctl
    from agentflow.agent_e import core as EC

    root = pathlib.Path(tmp_path) / "ws"
    root.mkdir(parents=True, exist_ok=True)
    C2.reset_waits()

    # (1) cancellation：预算 0.3 秒、子进程睡 3 秒 => 一定走 TimeoutExpired 那一支。
    got = CX.run_cancellable([sys.executable, "-c", "import time; time.sleep(3)"],
                             timeout_sec=0.3)
    assert got["timed_out"] is True, got
    assert got["cancelled"] is False, got

    # (2)+(3) agent_e._run_script：先落停机开关，脚本比 0.2 秒长 => 轮询片先记一条，
    # 看到开关、杀掉子进程之后再记一条收尾等待。
    stopctl.request_stop(root, reason="判据", by="judge")
    script = root / "slow_probe.py"
    script.write_text("import time\ntime.sleep(3)\n", encoding="utf-8")
    core = EC._Core.__new__(EC._Core)      # 只借 `_run_script` + 它要的三格
    core.workspace_root = root
    core.python = sys.executable
    result = core._run_script(script, timeout=5)
    # 读数形态钉死（2026-10-27 实测，探针零模型钱跑出来就是这五格）：
    # `stopped_by_user=True`、`timed_out=False`、`exit_code` 这一格在、值是 `None`、
    # `launch_error=None`、`program_timer.outcome="killed"`。
    #
    # 为什么必须钉死而不是"两种形态里之一"：改前这里是
    # `assert result.get("stopped_requested") or result.get("stopped") or True` ——
    # 那两格在实现里根本不存在（返回的是 `stopped_by_user`），整条断言恒真，于是
    # "停机开关落盘之后这一趟到底被记成什么"从来没有被量过。恒真项已删。
    # 反真空：把 `_stop_requested` 打桩成恒 False（= 停机那一支被掏空）⇒ 脚本跑满
    # 3 秒正常退出，返回里 `stopped_by_user` 整格不存在、`exit_code` 是 0、
    # `program_timer.outcome` 是 `exited` ⇒ 下面四条全红。
    assert result.get("stopped_by_user") is True, result
    assert result.get("timed_out") is False, result
    assert "exit_code" in result and result["exit_code"] is None, result
    assert result.get("launch_error") is None, result
    timer = result.get("program_timer") or {}
    assert str(timer.get("outcome") or "") == "killed", timer

    rows = {str(r["where"]): r for r in C2.waits()["rows"]
            if str(r["kind"]) == "external_process"}
    expected = {"cancellation.run_cancellable",
                "agent_e._run_script/poll",
                "agent_e._run_script/final"}
    assert expected <= set(rows), f"这三处没有各记一行：{sorted(rows)}"
    # 记的是实测耗时，不是 timeout 上限：收尾那一处的预算 15 秒，实测远小于它。
    final = rows["agent_e._run_script/final"]
    assert float(final["asked_sec"]) < 5.0, final
    # 轮询片那条的预算 0.2 秒，实测也应当在同一量级（不是 15、也不是 0）。
    poll = rows["agent_e._run_script/poll"]
    assert 0.0 < float(poll["asked_sec"]) < 3.0, poll
    assert int(poll["calls"]) >= 1 and int(final["calls"]) >= 1, rows

    # 反真空：把 note_process_wait 打桩成空 => 三条全没，上面那组断言必红。
    C2.reset_waits()
    with monkeypatch.context() as m:
        m.setattr(C2, "note_process_wait", lambda *a, **k: {}, raising=True)
        CX.run_cancellable([sys.executable, "-c", "import time; time.sleep(3)"],
                           timeout_sec=0.3)
    assert [r for r in C2.waits()["rows"]
            if str(r["kind"]) == "external_process"] == [], \
        "把 note_process_wait 打桩成空之后账上还有行 —— 反真空不成立"
