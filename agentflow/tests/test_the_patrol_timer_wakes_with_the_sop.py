# -*- coding: utf-8 -*-
"""L2：把"轮查"落成规范动作的那一半 —— 一个特殊计时器 + 到点的一套 SOP。

## 业主口径（唯一权威，逐字）

```
「20分钟计时 -> 时间到立刻进自动审阅工具 -> 审完后 M 自由行动 -> M 无事可做后启动轮查计时。
 注意：20分钟间隔内接收到任何其它消息 M 一样会被唤醒（这与计时器不阻塞进程的设计一致，
 轮查也不阻塞进程，轮查只是个特殊计时器，到点后不是返回一句提醒，而是一套需执行的规范动作）」
```

L1 已经把三个工具落地（`conductor.patrol` / `conductor.review_child` /
`conductor.patrol_verdict`），M 的提示词里也已经有了那两条 policy。这一份钉的是机制
那一半：计时器怎么起、到点那一下的正文是什么、下一轮什么时候挂。

## 七个判据与"改前红在哪"

| 条 | 守的是 | 改前红在哪 |
|---|---|---|
| a | M 挂机 ⇒ 恰好挂上一条轮查计时器；连挂三拍仍然只有一条 | 改前 `clock.PATROL_INTERVAL_SEC` / `start_patrol_timer` / `next_patrol` 都不存在，挂机路径上一条轮查计时器都不会出现 |
| b | 到点唤醒正文 = SOP 四步 + 既有异常清单；不含"时间到了 / 时间到，请"这类空提醒；四步整段进得了提示词 | 改前到点那条是 `时间到：轮查｜等了 20 分钟（…）`：只有提醒句，没有一步可执行的动作 |
| c | 20 分钟窗口里收到别的消息 ⇒ M 照样被唤醒（唤醒在轮查到点之前） | 改前没有轮查这一档，所以这一条"改前"没有对象；它的价值在改后：钉住"挂机不是阻塞"这条既有口径没被轮查打破 |
| d | 不阻塞：到点那一刻不 sleep（量 `await_io` 与墙钟） | 改前无从量起（没有轮查计时器）；改后如果谁把"到点"写成"睡满 20 分钟"，max 片长与墙钟两条当场红 |
| e1 | 反真空：把 SOP 正文渲染换成空串 ⇒ b 必红 | ——（守的是 b 真的在读 `clock.patrol_sop_text`） |
| e2 | 反真空：把"已经有一条就跳过"去掉 ⇒ a 的第二半必红 | ——（守的是 a 真的在读"恰好一条"这条规则） |
| f | 回归：Q21 的停机开关与 Q33 的返场判据仍然绿 | 由 `tests/test_park_sees_the_stop_switch.py` 与 `tests/test_the_return_beat_does_not_wait_for_children.py` 那两份文件负责，本文件只在 docstring 里点名 |
| g | 不许加 schema 列：`TIMER_KINDS` / `TIMER_STATES` 一个字都没动；轮查不是"等谁"，所以不进挂机读数 | 改前没有轮查这一档；改后若谁加了一个 `kind="patrol"`，第一行就红 |

## 三条口径在本文件里的落点

- 到点不是提醒句：`clock.due_message` 在 `patrol_sop` 非空时换抬头（`轮查到点：`）、
  正文接 SOP 四步；`b` 逐字断言"没有 `时间到了` / `时间到，请`"且"以 `轮查到点：` 开头"。
- 异常清单不写第二份：轮查那一段读的就是 `clock.patrol_section`（周期性巡查早就在用
  同一个落点），`b` 断言四类各有一句"条数"。
- 无事可做才挂、恰好一条、非 M 不挂：规则只有一处实现（`clock.start_patrol_timer`），
  挂点只有一处（`agent_loop._park_gate` 的第 ①/④ 支）。

## 边界

全部 tmp 工作区、假时钟、替身模型（`_Gate` 照剧本回答），零真实模型调用、零真睡
（`clock.await_io` 在假时钟下本来就不真睡；本文件的替身缝把"挂机的睡"换成拨假时钟）。
停机开关只用来"在某一拍边界上收工"，不构成本文件要钉的任何一件事。
"""

from __future__ import annotations

import json
import pathlib
import re
import time
from typing import Any, Callable, Mapping, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import schema as S
from agentflow import stopctl
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "patrol-l2"
TASK = "L2：轮查是一个特殊计时器，到点那一下的正文是一套规范动作"

#: SOP 四步的逐字关键句（判据按它们认出"这一步真的在正文里"）。
#: 取的是"工具名 + 动作"，不是装饰词：工具名写错了，判据也认不出来 —— 那正是要红的形态。
SOP_KEYS: tuple[str, ...] = (
    "conductor.patrol",
    "conductor.patrol_verdict",
    "自由行动",
    "挂上下一个轮查计时器",
)

#: 不许出现在轮查到点正文里的空提醒（业主：「不是返回一句提醒」）。
EMPTY_REMINDERS: tuple[str, ...] = ("时间到了", "时间到，请")

#: 异常清单四类在文本里的逐字开头（与 `clock.patrol_text` 同一份口径，本文件不另写一份）。
CHECKLIST_HEADS: tuple[str, ...] = ("① 停滞子 条数", "② 静默未销号的子 条数",
                                    "③ 未消板项 条数", "④ 被拦的结项原因 条数")

#: 被等的子代理"很久以后才有事件"：这条上限让挂机在判据里只会被两件事打断 ——
#: 停机开关（拍边界收工）或轮查到点（判据要看的那一件）。
WAITER_CAP_SEC = 86400.0


# ------------------------------------------------------------------ 改前红的落点


def _need(name: str) -> Any:
    """取 `clock` 上的一格；改前没有它 ⇒ 判据在这里红（不是 collection error）。

    为什么用这一层而不是直接写 `CLK.PATROL_INTERVAL_SEC`：改前那一版没有这些名字，
    直接引用会让整份文件在 import 期就炸掉 —— 那样"改前红"只是"文件装不进去"，
    而不是"这条判据要钉的那件事不存在"。判据要红在它自己那一行上。
    """
    if not hasattr(CLK, name):
        pytest.fail(f"clock.{name} 不存在 ⇒ 改前的树上车不了这一条（这就是改前红的落点）")
    return getattr(CLK, name)


# ------------------------------------------------------------------ 替身缝


class _Gate:
    """照剧本回答的替身模型：记 prompt，并在回答之前跑 `on_call(index, prompt)`。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: Sequence[str],
                 on_call: Callable[[int, str], None] | None = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(index, prompt)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def _tool(name: str, **args: Any) -> str:
    return json.dumps({"tool": name, "args": args}, ensure_ascii=False)


def _stop_now(ws: pathlib.Path, why: str) -> None:
    stopctl.request_stop(ws, reason=why)


# ------------------------------------------------------------------ 夹具


@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（挂机视图、等待账都是进程级的，串了会污染别的判据）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    fake = CLK.use(CLK.FakeClock(wall="2026-10-27T09:00:00+00:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path, name: str) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, ws


def _child(cond: Conductor, parent: str, key: str = "patrol@child") -> str:
    """造一行还在飞的子代理（等谁的那一条的等待对象：它在本判据里一直不说话）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-27T09:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate, me: str, *,
          max_steps: int = 40, role: str = "M") -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role=role, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=role, session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=max_steps, workspace_root=str(ws))


# ------------------------------------------------------------------ 一趟挂机


def _park_run(tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch, *,
              name: str, stop_at_beat: int | None = 4,
              deliver_at_beat: int = 0, deliver_text: str = "",
              stop_after_calls: int = 0, no_sop: bool = False,
              no_dedupe: bool = False) -> dict[str, Any]:
    """M 挂着机等一个子代理，轮查计时器在这条路径上起落；读数逐格带回。

    收工的两条路（与业主口径的两件事一一对应）：
    - `stop_at_beat` 给了 ⇒ 第 N 拍挂机开始时投停机开关（拍边界上收工，用来量"连挂几拍
      仍然只有一条"）；
    - `stop_after_calls` 给了 ⇒ 第 N 次模型调用之后投停机开关（用来量"到点之后真的回了
      模型"）。

    `deliver_at_beat` 给了 ⇒ 第 N 拍挂机开始时给 M 名下投一条别的事（判据 c：20 分钟窗口里
    收到别的消息，M 照样被唤醒）。它必须是"真投递"（走 conductor 的板项通道），
    不是打桩一个忙标志 —— 判据要证明的是信箱那一侧接得上。
    """
    st, cond, ws = _ws(tmp_path, name)
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me, key=f"patrol@{name}")
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M", max_wait_sec=WAITER_CAP_SEC)
    if no_sop:
        # 反真空（e1）：把 SOP 正文渲染换成空串。`fire_due` 按名字调模块级函数，
        # 于是这个桩打到的正是"到点那一下正文从哪来"那一处。
        monkeypatch.setattr(CLK, "patrol_sop_text", lambda **kw: "")
    if no_dedupe:
        # 反真空（e2）：让"已经有一条了吗"永远回答"没有" —— 恰好一条的判据就被拿掉了。
        monkeypatch.setattr(CLK, "next_patrol", lambda workspace: {
            "checked": True, "pending": False, "count": 0, "timer_id": "",
            "due_at": "", "remaining_sec": None, "reason": "打桩：永远说没有"})

    state: dict[str, Any] = {"beats": [], "slices": [], "patrols": [], "delivered": 0,
                             "prompt_secs": [], "wakes": [], "stubbed_sop": bool(no_sop),
                             "stubbed_dedupe": bool(no_dedupe), "deliver_at": None}
    real_await = CLK.await_io

    def await_and_tick(seconds: float, purpose: str, **kw: Any) -> dict[str, Any]:
        """拨假时钟的那一格（只拨挂机的睡；别的等待原样放过）。"""
        if str(kw.get("kind") or "io") != "park":
            return real_await(seconds, purpose, **kw)
        state["slices"].append({"at_sec": round(float(tick["cum"]), 6),
                                "asked_sec": round(float(seconds), 6)})
        bench.advance(float(seconds))
        tick["cum"] = round(float(tick["cum"]) + float(seconds), 6)
        return real_await(seconds, purpose, **kw)

    tick: dict[str, float] = {"cum": 0.0}
    monkeypatch.setattr(CLK, "await_io", await_and_tick)

    # 唤醒标记在"到点那一拍"就被下一拍的 `_take_wakes` 消费掉了（那是既有语义），
    # 所以读数要在写的时候抄一份 —— 事后读 `clock.read_wakes` 只会读到"已经消费"。
    real_record_wake = CLK.record_wake

    def record_wake(workspace: Any, timer: Any, mailbox_item_id: str = "",
                    **kw: Any) -> dict[str, Any]:
        event = real_record_wake(workspace, timer, mailbox_item_id=mailbox_item_id, **kw)
        state["wakes"].append(dict(event))
        return event

    monkeypatch.setattr(CLK, "record_wake", record_wake)

    real_sleep_once = AgentLoop._park_sleep_once

    def sleep_once(self_: AgentLoop, *, run: Any, parked: Any) -> dict[str, Any]:
        index = len(state["beats"])
        state["beats"].append(round(float(tick["cum"]), 6))
        # 这一拍开始时的轮查读数（a 条要的"恰好一条"就是它）。
        try:
            state["patrols"].append(dict(CLK.next_patrol(ws)))
        except Exception as exc:  # noqa: BLE001 - 读数坏掉要看得见
            state["patrols"].append({"checked": False, "pending": False,
                                     "reason": f"{type(exc).__name__}: {exc}"})
        if deliver_at_beat and index + 1 == deliver_at_beat:
            item = cond.open_item(kind="delegation", role="M", expects="work",
                                  action="run_once", summary=deliver_text or "别的消息",
                                  called_by="judge", parent_task_id=me,
                                  depth=1, input_key=f"patrol-l2:{name}:other")
            state["deliver_at"] = {"at_sec": round(float(tick["cum"]), 6), "item": item}
            state["delivered"] += 1
        if stop_at_beat is not None and index + 1 == stop_at_beat:
            _stop_now(ws, "判据：拍边界上收工")
        return real_sleep_once(self_, run=run, parked=parked)

    monkeypatch.setattr(AgentLoop, "_park_sleep_once", sleep_once)

    def stop_after(index: int, prompt: str) -> None:
        # 每一次模型调用落在假时钟的哪一秒（c 条要的"到点之前就醒了"靠这一格）。
        state["prompt_secs"].append(round(float(tick["cum"]), 6))
        if stop_after_calls and index + 1 >= stop_after_calls:
            _stop_now(ws, "判据：到点之后已经回过模型了")

    gate = _Gate([_tool("clock.now")] * 40, on_call=stop_after)
    t0 = time.monotonic()
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user",
                                            my_task_id=me, depth=1)
    wall = time.monotonic() - t0
    return {"run": run, "ws": ws, "me": me, "cond": cond, "gate": gate,
            "state": state, "tick": dict(tick), "wall_sec": wall,
            "prompts": list(gate.prompts),
            "notes": list(run.notes),
            "wakes": {"checked": True, "events": list(state["wakes"])},
            "wakes_left": dict(CLK.read_wakes(ws)),
            "patrol_timers": [t for t in CLK.book(ws).all() if CLK.is_patrol_timer(t)]}


def _patrol_wakes(got: Mapping[str, Any]) -> list[dict[str, Any]]:
    """这一趟落下的轮查到点唤醒（其它唤醒不算）。"""
    return [dict(e) for e in (got.get("wakes") or {}).get("events") or ()
            if CLK.is_patrol_timer(e)]


def _b_problems(message: str, prompt: str) -> list[str]:
    """b 条的四件事（正控与反真空共用同一份判据，避免"打桩之后测的是另一件事"）。"""
    out: list[str] = []
    for needle in SOP_KEYS:
        if needle not in message:
            out.append(f"到点正文里没有 SOP 的那一步：{needle!r}")
    for needle in EMPTY_REMINDERS:
        if needle in message:
            out.append(f"到点正文里有空提醒：{needle!r}")
    if message.startswith("时间到："):
        out.append("到点正文仍然是一句 `时间到：…` 的提醒（抬头要换）")
    if not message.startswith(_need("PATROL_DUE_HEAD")):
        out.append(f"到点正文没有以 {_need('PATROL_DUE_HEAD')!r} 开头")
    for head in CHECKLIST_HEADS:
        if head not in message:
            out.append(f"到点正文里没有异常清单的那一类：{head!r}（复用 patrol_section）")
    if str(prompt or ""):
        for needle in SOP_KEYS:
            if needle not in prompt:
                out.append(f"提示词里没有 SOP 的那一步：{needle!r}（正文没进上下文）")
    return out


# ================================================================== a) 恰好一条


def test_a_m_parking_arms_exactly_one_patrol_timer(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) M 挂机 ⇒ 恰好挂上一条轮查计时器；连挂三拍仍然只有一条。

    钉三件：
    1. 间隔是业主定的 20 分钟（`PATROL_INTERVAL_SEC`），且挂的那一条 `reason` 是受控常量
       `PATROL_REASON`（复用既有列、不新造 `kind`）；
    2. 第一拍挂机之后就有一条 pending 的轮查计时器，此后每一拍读数都是"一条"；
    3. 三拍之后簿记里仍然只有一条（`mounted` 只在第一拍为真，其余是 `skipped="already"`）。

    改前红：`PATROL_INTERVAL_SEC` / `PATROL_ROLE` / `next_patrol` / `is_patrol_timer` 都不存在
    （`_need` 那一行直接红），而挂机路径上一条轮查计时器都不会出现。
    """
    assert float(_need("PATROL_INTERVAL_SEC")) == 1200.0, _need("PATROL_INTERVAL_SEC")
    assert str(_need("PATROL_ROLE")) == str(S.CONDUCTOR_ROLE), (
        "轮查的角色常量与 schema 的主控角色分家了", _need("PATROL_ROLE"),
        S.CONDUCTOR_ROLE)
    assert callable(_need("is_patrol_timer")) and callable(_need("next_patrol"))
    assert callable(_need("start_patrol_timer"))

    got = _park_run(tmp_path, bench, monkeypatch, name="a", stop_at_beat=4)
    state = got["state"]
    assert len(state["beats"]) == 4, state["beats"]          # 四拍挂机（第 4 拍收到开关）
    assert got["run"].stop_reason == "stop_file", got["run"].to_dict()

    # 1) 挂的那一条是什么样：kind 仍是既有的 timer，标记落在 reason 上，间隔 20 分钟
    timers = got["patrol_timers"]
    assert len(timers) == 1, ("轮查计时器不是恰好一条", [t.row() for t in timers])
    timer = timers[0]
    assert str(timer.kind) == "timer", timer.row()
    assert str(timer.reason) == str(_need("PATROL_REASON")), timer.row()
    assert CLK.is_patrol_timer(timer) is True
    assert abs(float(timer.after_sec or 0.0) - 1200.0) < 1e-6, timer.row()

    # 2) 每一拍的读数：从第一拍起就有一条 pending 的
    readings = state["patrols"]
    assert len(readings) == len(state["beats"]), (readings, state["beats"])
    assert [r.get("pending") for r in readings] == [True] * 4, readings
    assert [int(r.get("count") or 0) for r in readings] == [1, 1, 1, 1], readings
    assert all(str(r.get("timer_id") or "") == timer.timer_id for r in readings), readings

    # 3) 只有第一拍真的挂，后三拍是"已经有一条 ⇒ 不再挂"
    assert int(got["run"].park.get("parked_turns") or 0) == 4, got["run"].park
    patrol = dict(got["run"].park.get("patrol") or {})
    assert patrol.get("skipped") == "already", (patrol, got["notes"])


def test_a2_non_m_roles_never_arm_a_patrol_timer(
        tmp_path: pathlib.Path, bench) -> None:
    """a 的第二半：非 M 角色不挂（规则在 `clock.start_patrol_timer` 一处，直接问它）。"""
    _need("start_patrol_timer")
    _, cond, ws = _ws(tmp_path, "a2")
    me = cond.open_top_level_run("M", TASK)
    for role in ("A", "D", "V"):
        got = CLK.start_patrol_timer(ws, task_id=me, role=role)
        assert got.get("mounted") is False, (role, got)
        assert got.get("skipped") == "role", (role, got)
    assert [t for t in CLK.book(ws).all() if CLK.is_patrol_timer(t)] == []
    # 正控：主控那一趟挂得上，且第二条被跳过
    first = CLK.start_patrol_timer(ws, task_id=me, role=S.CONDUCTOR_ROLE)
    assert first.get("mounted") is True, first
    second = CLK.start_patrol_timer(ws, task_id=me, role=S.CONDUCTOR_ROLE)
    assert second.get("mounted") is False and second.get("skipped") == "already", second
    assert len([t for t in CLK.book(ws).all() if CLK.is_patrol_timer(t)]) == 1


# ================================================================== b) 正文是 SOP


def test_b_the_wake_body_is_the_sop_not_a_reminder(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b) 到点唤醒正文 = SOP 四步 + 既有异常清单；不含空提醒；四步整段进得了提示词。

    改前红：到点那条是 `时间到：轮查｜等了 20 分钟（起于 …，到于 …）` —— 四步一句都没有，
    而且抬头正是业主点名不许的那一形（"只报一句到点了"）。
    """
    _need("patrol_sop_text")
    got = _park_run(tmp_path, bench, monkeypatch, name="b", stop_at_beat=None,
                    stop_after_calls=1)
    wakes = _patrol_wakes(got)
    assert len(wakes) == 1, [e.get("reason") for e in got["wakes"].get("events") or ()]
    wake = wakes[0]
    message = str(wake.get("message") or "")
    assert message, "轮查到点的那条唤醒没有正文"
    assert got["prompts"], "到点了却没有回模型（SOP 没人执行）"
    problems = _b_problems(message, got["prompts"][0])
    assert not problems, problems

    # 抬头那一句仍然带齐三样（目的 / 等了多久 / 到于何时）—— 换抬头不是丢格式
    assert "等了 20 分钟" in message, message
    assert "到于 " in message and "起于 " in message, message
    # 正文是"多行的一段"（抬头 + 四步 + 清单），不是一句
    assert message.count("\n") >= 4, message

    # 到点那一拍不是监控回合（监控回合的出口限定会把 SOP 的前两步拒掉）
    assert int(got["run"].monitor_turns) == 0, got["run"].monitor_turns
    assert "【监控回合】" not in got["prompts"][0], got["prompts"][0][:400]
    assert "【轮查的到点】" in got["prompts"][0], got["prompts"][0][:400]


def test_b2_the_same_body_lands_in_the_board_item(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b 的第二半：落成板项的那一句与唤醒里的那一句是同一句（单一拼法）。

    `clock_tools._deliver_due` 把 `timer.message` 原样写进 `tasks.detail`；本判据按
    `input_key="clock:<timer_id>"` 找到那一行，断言它带着 SOP 的四步与异常清单。
    改前红：那一行的 detail 是提醒句。
    """
    got = _park_run(tmp_path, bench, monkeypatch, name="b2", stop_at_beat=None,
                    stop_after_calls=1)
    wake = _patrol_wakes(got)[0]
    timer_id = str(wake.get("timer_id") or "")
    rows = [r for r in got["cond"].store.rows("tasks")
            if str(r.get("input_key") or "") == f"clock:{timer_id}"]
    assert len(rows) == 1, [r.get("input_key") for r in got["cond"].store.rows("tasks")]
    detail = str(rows[0].get("detail") or "")
    for needle in SOP_KEYS:
        assert needle in detail, (needle, detail[:400])
    assert str(wake.get("mailbox_item_id") or "") == str(rows[0].get("task_id") or "")


# ================================================================== c) 窗口里别的消息


def test_c_another_message_inside_the_window_wakes_m_anyway(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 20 分钟窗口里收到别的消息 ⇒ M 照样被唤醒（唤醒发生在轮查到点之前）。

    夹具：第 2 拍挂机开始时给 M 名下真的投一条别的活（走 conductor 的板项通道）。
    下一拍的 `_deliver_mailbox` 读到它 ⇒ `_pending_work` 说"手上有活" ⇒ 那一拍照常
    问模型（`_park_gate` 的第 ⑤ 支），而轮查计时器仍然是 pending。

    改前红：改前没有轮查这一档，所以"轮查没把进程阻塞住"这件事没有对象；它的价值在改后 ——
    钉住业主那半句「20分钟间隔内接收到任何其它消息 M 一样会被唤醒」没有被这一刀打破。
    """
    text = "判据：20 分钟窗口里到的一条别的消息"
    got = _park_run(tmp_path, bench, monkeypatch, name="c", stop_at_beat=None,
                    deliver_at_beat=2, deliver_text=text, stop_after_calls=1)
    state = got["state"]
    assert state["delivered"] == 1, state
    assert state["deliver_at"]["item"], state["deliver_at"]
    deliver_sec = float(state["deliver_at"]["at_sec"])
    interval = float(_need("PATROL_INTERVAL_SEC"))
    assert deliver_sec < interval, (deliver_sec, interval)

    # 真的醒了：那一拍之后有一个模型回合，而且它发生在轮查到点之前
    assert got["prompts"], ("窗口里收到别的消息却没醒", got["notes"])
    prompt = got["prompts"][0]
    assert text in prompt, prompt[:600]
    assert state["prompt_secs"], state
    first_prompt_sec = float(state["prompt_secs"][0])
    assert first_prompt_sec < interval, ("轮查到点之前没有醒", first_prompt_sec)
    assert _patrol_wakes(got) == [], ("还没到点就报了轮查", got["wakes"])
    # 轮查计时器没被这条消息顶掉：它还在账上，下一轮挂机不会再挂第二条
    timers = got["patrol_timers"]
    assert len(timers) == 1, [t.row() for t in timers]
    assert str(timers[0].state) == "pending", timers[0].row()


# ================================================================== d) 不阻塞


def test_d_firing_the_patrol_does_not_sleep(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 不阻塞：假时钟下到点那一刻不 sleep（量 `await_io` 的片与墙钟）。

    三件一起才算"不阻塞"：
    1. 挂机的一拍从来没睡过 20 分钟（最大的片 ≤ `PARK_SLICE_MAX_SEC`）；
    2. 轮查到点之后、回模型之前没有新的一片（到点那一下只推时钟，不睡）；
    3. 整趟的墙钟远小于任何"真睡"的量级（假时钟下不该有真实等待）。

    改前红：改前没有轮查计时器，`at_sec >= 1200` 那一段读数根本不存在；改后若谁把"到点"
    写成"再睡满 20 分钟"，第 1、2 条当场红（最大片 = 1200，或到点之后又出现一片）。
    """
    got = _park_run(tmp_path, bench, monkeypatch, name="d", stop_at_beat=None,
                    stop_after_calls=1)
    state = got["state"]
    slices = list(state["slices"])
    assert slices, "这一趟没有挂机（判据没有对象）"
    interval = float(_need("PATROL_INTERVAL_SEC"))
    biggest = max(float(s["asked_sec"]) for s in slices)
    assert biggest <= float(AL.PARK_SLICE_MAX_SEC) + 1e-6, (biggest, slices)
    assert biggest < interval, ("挂机的一拍睡过了轮查间隔", biggest, slices)

    # 到点之后、回模型之前：没有新的一片
    late = [s for s in slices if float(s["at_sec"]) >= interval - 1e-6]
    assert late == [], ("轮查到点之后又睡了", late)
    # 到点的那一片是"封顶在轮查到点"的那一片：不封顶的话它会一路睡到退避上限
    span = [s for s in slices if float(s["at_sec"]) < interval]
    assert span and abs(sum(float(s["asked_sec"]) for s in span) - interval) < 1e-3, (
        "挂机的片加起来没走到轮查到点那一刻", span)

    # 墙钟：假时钟下不该有真实等待（真睡 20 分钟在这里是 1200 秒量级）
    assert float(got["wall_sec"]) < 5.0, ("这一趟在真睡", got["wall_sec"])
    assert got["prompts"], "到点了却没有回模型"
    parks = [r for r in CLK.waits()["rows"] if str(r.get("kind") or "") == "park"]
    assert parks, CLK.waits()["rows"]
    assert int(parks[0]["skipped"]) == int(parks[0]["calls"]), (
        "假时钟下仍然真睡了", parks[0])


# ================================================================== e) 反真空


def test_e1_stubbing_the_sop_body_turns_b_red(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e1) 反真空：把 SOP 正文渲染换成空串 ⇒ b 必红。

    打桩打到的是 `clock.patrol_sop_text`（`fire_due` 按名字调它）。打桩之后：
    - 到点那份正文里四步必须一句不剩（否则 b 读的根本不是这一处）；
    - 异常清单仍然在（它走另一个落点 `patrol_section`）—— 这一条同时证明两半是分开的。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="e1-live", stop_at_beat=None,
                     stop_after_calls=1)
    live_wake = _patrol_wakes(live)[0]
    assert not _b_problems(str(live_wake.get("message") or ""), live["prompts"][0]), "正控红了"

    stubbed = _park_run(tmp_path, bench, monkeypatch, name="e1-stub", stop_at_beat=None,
                        stop_after_calls=1, no_sop=True)
    assert stubbed["state"]["stubbed_sop"] is True, "反真空的打桩点没装上"
    stub_wake = _patrol_wakes(stubbed)
    assert len(stub_wake) == 1, stubbed["wakes"]
    message = str(stub_wake[0].get("message") or "")
    problems = _b_problems(message, stubbed["prompts"][0] if stubbed["prompts"] else "")
    assert problems, ("把 SOP 正文换成空串之后 b 仍然绿 ⇒ b 读的不是那一处", message)
    # 四步真的一句不剩（不是"少了一句"）
    for needle in SOP_KEYS:
        assert needle not in message, (needle, message)
    # 异常清单不在同一个落点上死掉：它仍然在（两半分开）
    for head in CHECKLIST_HEADS:
        assert head in message, (head, message)


def test_e2_removing_the_dedupe_turns_a_red(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e2) 反真空：把"已经有一条就跳过"去掉 ⇒ a 的第二半必红。

    打桩的点是 `clock.next_patrol`（"已经有一条了吗"的唯一读口）。打掉之后每拍都会挂一条，
    于是"恰好一条"当场红 —— 这正是业主点名的那个后果（"一分钟能挂出几十个轮查计时器"）。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="e2-live", stop_at_beat=4)
    assert len(live["patrol_timers"]) == 1, [t.row() for t in live["patrol_timers"]]

    stubbed = _park_run(tmp_path, bench, monkeypatch, name="e2-stub", stop_at_beat=4,
                        no_dedupe=True)
    assert stubbed["state"]["stubbed_dedupe"] is True, "反真空的打桩点没装上"
    assert len(stubbed["patrol_timers"]) > 1, (
        "把「已经有一条就跳过」打桩掉之后仍然只有一条 ⇒ a 读的不是那一处",
        [t.row() for t in stubbed["patrol_timers"]])


# ================================================================== 常量与口径


def test_g_the_patrol_timer_reuses_the_existing_columns(
        tmp_path: pathlib.Path, bench) -> None:
    """g) 不许加 schema 列：`TIMER_KINDS` / `TIMER_STATES` 一个字都没动。

    轮查复用 `kind="timer"`，标记只落在 `reason` 上（`PATROL_REASON`）。这一条钉的是
    "这一刀没改落盘契约"：词表多一档就等于改了 `out/clock/state.json` 的每一行。
    """
    assert tuple(CLK.TIMER_KINDS) == ("timer", "alarm", "periodic", "program"), CLK.TIMER_KINDS
    assert tuple(CLK.TIMER_STATES) == ("pending", "fired", "cancelled"), CLK.TIMER_STATES
    _, cond, ws = _ws(tmp_path, "g")
    me = cond.open_top_level_run("M", TASK)
    got = CLK.start_patrol_timer(ws, task_id=me, role=S.CONDUCTOR_ROLE)
    assert got.get("mounted") is True, got
    timer = CLK.book(ws).get(str(got.get("timer_id") or ""))
    assert timer is not None and str(timer.kind) == "timer", got
    row = timer.row()
    assert str(row.get("purpose")) == str(_need("PATROL_REASON")), row
    # 这一条不是"等谁"，所以它不进挂机读数（`clock.waiters` 只认 `wait_for` 那一条）
    assert CLK.waiters(ws)["parked"] == 0, CLK.waiters(ws)
    next_got = CLK.next_patrol(ws)
    assert next_got["checked"] is True and next_got["pending"] is True, next_got
    assert re.match(r"^tm-\d+$", str(next_got["timer_id"]) or ""), next_got
    assert float(next_got["remaining_sec"] or 0.0) <= 1200.0, next_got
