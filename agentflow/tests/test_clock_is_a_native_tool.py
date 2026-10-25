"""D-53 的修法判据：时钟是系统原生工具，计时器/闹钟依附在它上面。

## 这个文件修的是什么

D-53 的业主原话（唯一权威）：

    「对于D53，把时钟做成系统原生工具，让M在派活完后启动计时器（计时器依托时钟实现），
      到点后时钟自动给M发消息检查，检查完成后M再启动计时器。如果其它人要看表
      （看时钟读数）或计时、定闹钟什么的也可以用。总之这是个通用工具。
      时钟只有一个，依附于其上的计时进程可以很多。」

改前红：`agentflow.clock` 与 `agentflow.tools.clock_tools` 都不存在 => 本文件
每一条用例都以 `ModuleNotFoundError` 失败（不是跳过、不是空集通过）。

## 八条判据（与施工单一一对应）

1. 假时钟前进 30 秒 => 计时器到点，收件人收到一条 mailbox 项 + 一条唤醒标记；
2. 至少 5 个不同到点时刻的计时器各自独立到点，互不吞并、不重复触发；
3. `clock.timer_cancel` 之后到点不触发（负控）；
4. 一次性：到点后再前进 10 分钟不产生第二条（负控）；
5. 时钟读数三态：读不到 => `unknown`，不折成 0；
6. 反真空：打桩掉"置唤醒标记" => 第 1 条红；打桩掉"落 mailbox 项" => 第 1 条也红；
7. 重启：状态落盘后再起，未到点的计时器仍在（用假时钟核 `now()` 与 `due`）；
8. 角色面：`for_role` 每个角色都拿得到 `clock.*`（含只读角色 C/H/V 与主控 M）。

## 读数从哪里取

- mailbox 项：`Store.rows("tasks")` 里 `kind == "notice"` 且 `detail` 以
  "计时器到点：" 开头的那一行；`parent_task_id` 是收件人的台账号。
- 唤醒标记：`clock.read_wakes(<工作区>)`（落盘在 `out/clock/wake.json`），
  每条带 `task_id` / `timer_id` / `mailbox_item_id`。
- 计时器状态：`out/clock/state.json` + `clock.timer_list` 的返回。

## 为什么第 6 条要把两件分别打桩

"两件都做"是 D-53 的核心修复：D-52 的 mailbox 投递还没修，如果只落 mailbox，
"正在等子的父"不会被唤醒；如果只置唤醒标记，事后没有可审计的收件项。两条
都断言的形态是：任缺一件，第 1 条就必须红。打桩打在 `clock_tools` 的模块属性上
（`_open_mailbox_item` / `_record_wake`），因为生产中真正被调用的就是这两个名字。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor, calling_as
from agentflow.store import Store
from agentflow.tools import ROLES, ToolRegistry

#: 工具层词汇里的全部角色 = 可召唤的 A-L + 主控 M（与 `tools.TOOL_ROLES` 同源）。
ROLES_WITH_M: tuple[str, ...] = tuple(ROLES) + (S.CONDUCTOR_ROLE,)

#: 这五件就是 D-53 要求的通用工具面。
CLOCK_TOOLS: frozenset[str] = frozenset({
    "clock.now",
    "clock.timer_start",
    "clock.alarm_start",
    "clock.timer_list",
    "clock.timer_cancel",
})

#: 到点动作落进 `tasks.detail` 的逐字前缀（判据按它认出"这是一条到点项"）。
#: 2026-10-25 业主把到点消息的格式定死成"时间到：…"，前缀随之改名（旧的是"计时器到点："）。
DUE_PREFIX = "时间到："


def _mods():
    """惰性导入两个被测模块。

    惰性导入是刻意的：改前红要能逐条看见（8 条各自 `ModuleNotFoundError`），
    而不是整个文件在 collection 阶段就停住、看起来像"一条都没写"。
    """
    from agentflow import clock as C
    from agentflow.tools import clock_tools as CT

    return C, CT


def _setup(tmp_path, C, CT):
    """一份已 init 的临时工作区 + 一个从 2026-01-01T00:00:00Z 起步的假时钟。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    C.reset()
    fake = C.FakeClock(wall="2026-01-01T00:00:00+00:00", monotonic=1000.0)
    C.use(fake)
    reg = ToolRegistry(name="clock-test")
    # 生产里注册表由 `scoped_to(role)` 绑定；判据这里按收件人角色 M 绑定，
    # 于是 `reg.call(...)` 与真实循环同一条调用期判据（不是绕过它）。
    reg.bound_role = "M"
    CT.register(reg, store=store, root=root)
    return store, fake, reg, root


def _open_task(store: Store, role: str = "M") -> str:
    """在台账里开一行收件人（顶趟），返回它的台账号。"""
    return Conductor(store).open_top_level_run(role, "时钟判据的收件人")


def _start(reg, task_id: str, *, role: str = "M", after: float = 30.0,
           reason: str = "检查子代理是否回来", to: str = "self"):
    """以 `task_id` 的身份起一个计时器；返回工具结果。"""
    with calling_as(task_id, role):
        return reg.call("clock.timer_start", after_sec=after, reason=reason, to=to)


def _due_notices(store: Store) -> list[dict]:
    """台账里所有"计时器到点"的 notice 行。"""
    return [
        r for r in store.rows("tasks")
        if str(r.get("kind") or "") == "notice"
        and str(r.get("detail") or "").startswith(DUE_PREFIX)
    ]


def _delivery_readings(store, fake, reg, root, C, *, after: float = 30.0,
                       reason: str = "检查子代理是否回来") -> dict:
    """起一个计时器 -> 前进 -> 读两处落点。第 1 条与第 6 条共用这一份读数。"""
    recipient = _open_task(store)
    started = _start(reg, recipient, after=after, reason=reason)
    assert started.ok is True, started.error
    timer_id = str(started.data["timer_id"])
    fake.advance(after)
    notices = _due_notices(store)
    wakes = C.read_wakes(root)
    return {
        "recipient": recipient,
        "timer_id": timer_id,
        "started": started,
        "notice_count": len(notices),
        "notice": notices[0] if notices else None,
        "wake_checked": bool(wakes.get("checked")),
        "wake_count": len(wakes.get("events") or []),
        "wake": (wakes.get("events") or [None])[0],
    }


def _assert_both_effects(store, fake, reg, root, C) -> None:
    """第 1 条的两件落点；第 6 条用它证明"任缺一件就红"。"""
    got = _delivery_readings(store, fake, reg, root, C)
    assert got["notice_count"] == 1, f"到点没有落一条 mailbox 项：{got}"
    assert got["wake_checked"] is True, f"唤醒标记读不成：{got}"
    assert got["wake_count"] == 1, f"到点没有置一条唤醒标记：{got}"


# ============================================================ ① 到点两件
def test_a_fake_clock_advance_delivers_both_a_mailbox_item_and_a_wake_marker(tmp_path) -> None:
    """假时钟前进 30 秒 => 一条 mailbox 项 + 一条唤醒标记，且都指向收件人。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    got = _delivery_readings(store, fake, reg, root, C)
    assert got["notice_count"] == 1, got
    notice = got["notice"]
    # mailbox 项：tasks 表的一行，收件人写在 parent_task_id 上，detail 可审计。
    assert notice["kind"] == "notice", notice
    assert notice["parent_task_id"] == got["recipient"], notice
    assert str(notice["detail"]).startswith(DUE_PREFIX), notice
    assert "检查子代理是否回来" in str(notice["detail"]), notice
    assert notice["item_state"] == "queued", notice
    assert notice["called_by"] == "clock", notice
    # 唤醒标记：同一趟到点要能被"正在等子的父"读出来。
    assert got["wake_checked"] is True, got
    assert got["wake_count"] == 1, got
    assert got["wake"]["task_id"] == got["recipient"], got["wake"]
    assert got["wake"]["timer_id"] == got["timer_id"], got["wake"]
    assert got["wake"]["mailbox_item_id"] == notice["task_id"], got["wake"]
    # 计时器是一次性的：状态已经落成 fired，不再排在待发里。
    listed = reg.call("clock.timer_list")
    assert listed.ok is True, listed.error
    row = next(t for t in listed.data["timers"] if t["timer_id"] == got["timer_id"])
    assert row["state"] == "fired", row


# ============================================================ ② 多个计时器
def test_many_timers_fire_independently_and_never_swallow_each_other(tmp_path) -> None:
    """5 个不同到点时刻的计时器各自独立到点；不吞并、不重复。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    recipient = _open_task(store)
    started: dict[str, float] = {}
    for index, after in enumerate((10.0, 20.0, 30.0, 40.0, 50.0)):
        res = _start(reg, recipient, after=after, reason=f"第 {index} 个计时器")
        assert res.ok is True, res.error
        started[str(res.data["timer_id"])] = after
    # 每前进一次，只有"到点的那些"被投递：10 / 20 / 30 / 40+50 两件同时到点。
    counts = []
    for step in (10.0, 10.0, 10.0, 20.0):
        fake.advance(step)
        counts.append(len(_due_notices(store)))
    assert counts == [1, 2, 3, 5], f"到点节奏不对：{counts}"
    notices = _due_notices(store)
    assert len(notices) == 5, notices
    # 每条对应一个 timer_id（input_key 是这次到点的可审计键），不重复、不吞并。
    keys = sorted(str(n.get("input_key") or "") for n in notices)
    assert keys == sorted(f"clock:{tid}" for tid in started), keys
    reasons = sorted(str(n.get("detail") or "") for n in notices)
    assert len(set(reasons)) == 5, reasons
    wakes = C.read_wakes(root)
    assert wakes["checked"] is True and len(wakes["events"]) == 5, wakes
    assert sorted(e["timer_id"] for e in wakes["events"]) == sorted(started), wakes
    # 再前进 100 秒：一个都不许重复触发。
    fake.advance(100.0)
    assert len(_due_notices(store)) == 5, "一次性计时器被重复触发了"
    assert len(C.read_wakes(root)["events"]) == 5, "唤醒标记被重复写了"


# ============================================================ ③ 取消负控
def test_a_cancelled_timer_never_fires(tmp_path) -> None:
    """负控：`clock.timer_cancel` 之后到点不触发（两处落点都为 0）。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    recipient = _open_task(store)
    started = _start(reg, recipient, after=30.0, reason="这条会被取消")
    assert started.ok is True, started.error
    timer_id = str(started.data["timer_id"])
    cancelled = reg.call("clock.timer_cancel", timer_id=timer_id)
    assert cancelled.ok is True, cancelled.error
    assert cancelled.data["cancelled"] is True, cancelled.data
    fake.advance(60.0)
    assert _due_notices(store) == [], "取消之后仍然落了 mailbox 项"
    assert len(C.read_wakes(root)["events"]) == 0, "取消之后仍然置了唤醒标记"
    listed = reg.call("clock.timer_list")
    row = next(t for t in listed.data["timers"] if t["timer_id"] == timer_id)
    assert row["state"] == "cancelled", row
    # 再取消一次是"查过了、已经取消"，不是第二次取消：不许折叠成成功。
    again = reg.call("clock.timer_cancel", timer_id=timer_id)
    assert again.ok is True and again.data["cancelled"] is False, again.data
    assert again.data["state"] == "cancelled", again.data


# ============================================================ ④ 一次性负控
def test_a_fired_timer_does_not_fire_a_second_time_after_ten_more_minutes(tmp_path) -> None:
    """负控：到点后再前进 10 分钟，不再产生第二条（到点即消耗、不自动重排）。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    recipient = _open_task(store)
    started = _start(reg, recipient, after=30.0, reason="只该响一次")
    assert started.ok is True, started.error
    fake.advance(30.0)
    assert len(_due_notices(store)) == 1
    assert len(C.read_wakes(root)["events"]) == 1
    fake.advance(600.0)
    assert len(_due_notices(store)) == 1, "一次性计时器自己重排了（业主口径：检查完成后 M 自己再启动）"
    assert len(C.read_wakes(root)["events"]) == 1, "唤醒标记被重复写了"
    listed = reg.call("clock.timer_list")
    row = next(t for t in listed.data["timers"] if t["timer_id"] == started.data["timer_id"])
    assert row["state"] == "fired", row


# ============================================================ ⑤ 三态读数
def test_an_unreadable_clock_is_unknown_and_never_folded_into_zero(tmp_path) -> None:
    """假时钟读不到 => `unknown`；墙钟与单调计数都是 None，不是 0。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    fake.set_mode("unknown", reason="判据：假时钟读不到")
    reading = C.now()
    assert reading.status == "unknown", reading
    assert reading.wall is None, "读不到的墙钟被折成了 0 / 某个具体时间"
    assert reading.monotonic is None, "读不到的单调计数被折成了 0"
    assert reading.reason, "unknown 必须带理由（没查成与查过了要分得开）"
    got = reg.call("clock.now")
    assert got.ok is True, got.error
    assert got.data["status"] == "unknown", got.data
    assert got.data["wall"] is None and got.data["monotonic"] is None, got.data
    assert got.data["elapsed_sec"] is None, "时钟读不到时，这一趟跑了多久也只能是 None"
    # 三态的第三档：只有一个来源可读 => partial（不是 ok，也不是 unknown）。
    fake.set_mode("mono_only", reason="判据：只有单调计数可读")
    partial = C.now()
    assert partial.status == "partial", partial
    assert partial.wall is None and partial.monotonic is not None, partial
    # 读不到时不许起计时器：到点判不了，就不许假装排上了。
    recipient = _open_task(store)
    fake.set_mode("unknown", reason="判据：起表时读不到")
    refused = _start(reg, recipient, after=10.0, reason="读不到时钟")
    assert refused.ok is False and refused.meta.get("kind") == "unreadable", refused.to_dict()


# ============================================================ ⑥ 反真空
def test_both_due_effects_are_load_bearing(tmp_path, monkeypatch) -> None:
    """任缺一件（mailbox 项 / 唤醒标记），第 1 条就必须红。"""
    C, CT = _mods()
    # 基线：同一份夹具在未打桩时必须两件都成立，否则下面的"红"证明不了任何事。
    store, fake, reg, root = _setup(tmp_path / "baseline", C, CT)
    _assert_both_effects(store, fake, reg, root, C)

    # 打桩掉"置唤醒标记" => 第 1 条红。
    store2, fake2, reg2, root2 = _setup(tmp_path / "no-wake", C, CT)
    with monkeypatch.context() as m:
        m.setattr(CT, "_record_wake", lambda *args, **kwargs: None, raising=True)
        with pytest.raises(AssertionError, match="唤醒标记"):
            _assert_both_effects(store2, fake2, reg2, root2, C)

    # 打桩掉"落 mailbox 项" => 第 1 条也红。
    store3, fake3, reg3, root3 = _setup(tmp_path / "no-mailbox", C, CT)
    with monkeypatch.context() as m:
        m.setattr(CT, "_open_mailbox_item", lambda *args, **kwargs: "", raising=True)
        with pytest.raises(AssertionError, match="mailbox"):
            _assert_both_effects(store3, fake3, reg3, root3, C)


# ============================================================ ⑦ 重启
def test_pending_timers_survive_a_restart_and_still_fire(tmp_path) -> None:
    """状态落盘后再起：未到点的计时器仍在；新时钟按墙钟比较 due，到点仍能投递。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    recipient = _open_task(store)
    started = _start(reg, recipient, after=600.0, reason="重启之后还要到点")
    assert started.ok is True, started.error
    timer_id = str(started.data["timer_id"])
    state_path = root / "out" / "clock" / "state.json"
    assert state_path.is_file(), f"计时器状态没有落盘：{state_path}"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert any(t["timer_id"] == timer_id for t in saved["timers"]), saved

    # 模拟重启：清掉进程内簿记，换一个墙钟前进了 300 秒、单调计数完全不同的新假时钟。
    C.reset_books()
    restarted = C.FakeClock(wall="2026-01-01T00:05:00+00:00", monotonic=50.0)
    C.use(restarted)
    C.reset_books()
    book = C.book(root)
    timer = book.get(timer_id)
    assert timer is not None and timer.state == "pending", timer
    now = C.now()
    due = datetime.fromisoformat(timer.due_at)
    assert now.status == "ok", now
    assert now.wall.astimezone(timezone.utc) < due, (now.wall, due)
    listed = reg.call("clock.timer_list")
    row = next(t for t in listed.data["timers"] if t["timer_id"] == timer_id)
    assert row["state"] == "pending" and row["remaining_sec"] > 0, row
    # 新进程的单调计数（50）比旧进程的 due_mono（1600）小得多：必须按墙钟判，
    # 否则这条会"永远不到点"。
    restarted.advance(300.0)
    assert len(_due_notices(store)) == 1, "重启后的计时器没有按墙钟到点"
    assert len(C.read_wakes(root)["events"]) == 1, "重启后的计时器没有置唤醒标记"


# ============================================================ ⑧ 角色面
def test_every_role_gets_the_clock_tools(tmp_path) -> None:
    """通用工具：A-L 与主控 M 都拿得到五件 `clock.*`（含只读角色 C/H/V）。"""
    C, CT = _mods()
    store, fake, reg, root = _setup(tmp_path, C, CT)
    for role in ROLES_WITH_M:
        names = {spec.name for spec in reg.for_role(role)}
        missing = CLOCK_TOOLS - names
        assert not missing, f"{role} 的工具面缺 {sorted(missing)}"
    # 只读角色不是"被声明了再剥掉"：它们真的拿得到（不是靠例外表放行）。
    for role in ("C", "H", "V"):
        names = {spec.name for spec in reg.for_role(role)}
        assert CLOCK_TOOLS <= names, role
