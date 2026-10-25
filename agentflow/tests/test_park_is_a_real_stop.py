# -*- coding: utf-8 -*-
"""挂机是"把进程挂在时钟上"：循环真的不调模型、不落回合，被叫醒时少一次调用。

## 这一份补的是哪一根线（`docs/WIRING-AUDIT-2026-10-27.md` 第三节 a / b）

审计实测（真机探针，零模型钱）：父代理第 1 步 `clock.timer_start(wait_for=…)` 起了表，
之后循环照旧每拍 `ask_step` —— 父起表后又走了 3 个回合，`clock.waiters()` 读到
`park_state=parked` 且 `parked_steps=3 / parked_calls=3`。同一份审计还量到第二件事：
`_take_wakes` 消费唤醒之后同一步紧接着仍然 `ask_step`，于是"被叫醒"这一拍只会
多花一次调用，不会少一次。

改前 `agent_loop.py` 全文 `park` 出现 0 次：`waiters()` 只被读数面（`clock.now` /
`clock.timer_list`）读，控制流里没有"这一拍不调模型"的那一支。

## 四条判据（每条都"改前红"）

1. `test_a_parked_parent_takes_no_model_calls_and_no_steps`：父挂机之后跑 4 拍
   ⇒ 一次模型调用都没有、`parked_steps == 0`、`parked_calls == 0`、`parked_sec > 0`。
   改前：每一拍都 `ask_step` ⇒ 4 次调用、`parked_steps == 4`。
   诊断性（2026-10-27 审计第十处）：挂机区间里模型调用上限 0、循环拍数上限 40 ——
   把挂机支掏空时这一条当场红并点名"哪一支没了"；改前它不红，它挂死到 1200 s 超时
   （`max_steps` 已不是循环出口，循环于是没有出口）。
2. `test_the_park_branch_is_load_bearing`（反真空）：把这一支打桩成"照常问模型" ⇒
   同一个读数必须 > 0。这一条钉的是"判据 1 真的在读那一支"；它复现的正是审计里
   那个 `parked_steps=3`。
3. `test_a_parent_that_starts_the_park_from_its_own_tool_call_stops_asking`：真机那条
   路径（模型自己调 `clock.timer_start(wait_for=…)`）—— 起表之后一拍都不再问模型，
   `parked_steps` 停在起表那一步（它自己的那条 `agent_step` 事件落在计时器登记之后，
   所以绝对读数是 1 而不是 0；判据用的是"挂机区间里的增量 == 0"）。
4. `test_a_wake_that_ends_the_park_costs_no_model_call`：子代理发一条消息唤醒挂机中的
   父 ⇒ 父那一拍不调模型（对比把"跳过"打桩成空的那一趟：调用数正好多 1）。
   改前红：唤醒被消费之后同一步紧接着 `ask_step`，那一拍就是多出来的那次调用。

## 边界

全部 tmp 工作区、假时钟、替身缝（`_Gate` 照剧本回答），零真实模型调用。
时间由 `AgentLoop._park_slice` 这条缝拨（判据把它换成"推进假时钟"），于是挂机区间
可以在毫秒级跑完 —— 与 `fetch._default_sleep` 同一档的替身缝，生产路径一字未改。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop, send_message
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from _d68_board_fixture import children_clean_their_boards  # noqa: E402 - D-68 夹具助手

SID = "park"
TASK = "挂机这一趟（业主口径：挂机是将进程挂在时钟上）"
#: 子代理那条留言的正文（判据靠它在提示词里认"唤醒的内容真的到了模型眼前"）。
MARKER = "命题 P 的证明已经落盘，见 out/proof.md"

#: 挂机区间里允许的模型调用次数（0：一次都不许）。
#:
#: 为什么是硬上限而不是"跑完再断"（2026-10-27 审计第十处）：把挂机那一支掏空之后
#: 循环照旧每拍 `ask_step`，而 `max_steps` 已经不是循环出口（它降级成"每满 N 步
#: 向父代理报一次账"的报告阈值）⇒ 这一趟没有出口，判据不是红而是挂死到 CI 的
#: 1200 s 超时。超时读数不说"哪一支没了"，诊断性最差。上限一落，"被掏空"在第一次
#: 模型调用那一刻就表现为红，且红的话直接点名那一支。
PARKED_MODEL_CALL_LIMIT = 0
#: 循环拍数上限：第二道保险（万一某次改动的形态是"不问模型但也不走挂机支"，
#: 那一趟会变成空转，模型调用上限拦不住它）。
PARKED_TICK_LIMIT = 40


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
    from agentflow import stopctl

    stopctl.request_stop(ws, reason=why)


# ------------------------------------------------------------------ 夹具

@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（挂机视图是进程级的，串了会污染别的判据）。"""
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
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    children_clean_their_boards(cond)
    return st, cond, ws


def _child(cond: Conductor, parent: str, key: str = "park@child") -> str:
    """造一行还在飞的子代理（等谁的那一条的等待对象）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-27T09:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate,
          me: str, *, max_steps: int = 12) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=max_steps, workspace_root=str(ws))


# ------------------------------------------------------------------ 1 真停摆

def test_a_parked_parent_takes_no_model_calls_and_no_steps(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """父已经挂在时钟上 ⇒ 跑 4 拍：零模型调用、零回合、`parked_sec > 0`。

    改前红：那 4 拍每一拍都 `ask_step` ⇒ `len(gate.prompts) == 4`、
    `parked_steps == 4`（审计的真机读数就是这个形态）。
    """
    st, cond, ws = _ws(tmp_path, "ws")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")
    readings: list[dict[str, Any]] = []

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        """替身缝：每一次挂机睡 = 拨一格假时钟；第 4 拍落停机开关（判据要收工）。"""
        assert "挂机等" in purpose, purpose
        assert seconds > 0, seconds
        readings.append(dict(CLK.waiters(ws)))
        bench.advance(seconds)
        if len(readings) == 4:
            _stop_now(ws, "判据：挂够了 4 拍")
        return {"checked": True, "asked_sec": seconds}

    real_slice = AgentLoop._park_slice
    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)

    def no_model_call_while_parked(index: int, prompt: str) -> None:
        """挂机区间里模型一次都不许被问；被问了就是"挂机那一支没接上"。

        为什么在这里当场 fail、而不是等 `run()` 返回再断 `gate.prompts == []`：
        掏空挂机支之后循环没有出口（`max_steps` 已不是出口），等返回就是等 1200 s
        超时。`pytest.fail` 抛的 `Failed` 是 `BaseException`，会越过 `LlmSeam.ask_step`
        那层 `except Exception`（否则它会被折成 `call.problem` 然后接着转）。
        """
        pytest.fail(
            f"挂机期间第 {index + 1} 次问模型（上限 {PARKED_MODEL_CALL_LIMIT} 次）"
            " ⇒ 挂机那一支被掏空了：这一拍 `_park_gate` 应当给出 skip_model=True。"
            f" 提示词开头：{prompt[:200]}")

    # 第二道保险：拍数上限（空转也拦得住）。
    real_mailbox = AgentLoop._deliver_mailbox
    ticks = {"n": 0}

    def capped_mailbox(self_: AgentLoop, *, step: int, messages: list[dict[str, Any]],
                       run: Any) -> dict[str, Any]:
        ticks["n"] = int(ticks["n"]) + 1
        if ticks["n"] > PARKED_TICK_LIMIT:
            pytest.fail(
                f"循环没有出口：已经第 {ticks['n']} 拍了（上限 {PARKED_TICK_LIMIT}）"
                " ⇒ 挂机支被掏空，而 `max_steps` 已不是循环出口（它只是报告阈值）")
        return real_mailbox(self_, step=step, messages=messages, run=run)

    monkeypatch.setattr(AgentLoop, "_deliver_mailbox", capped_mailbox)
    gate = _Gate([_tool("clock.now")], on_call=no_model_call_while_parked)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)
    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("挂着机还在问模型（改前的形态）", len(gate.prompts))
    assert run.steps == [], [s.shape for s in run.steps]
    assert int(run.park.get("parked_turns") or 0) == 4, run.park
    assert float(run.park.get("asked_sec") or 0.0) > 0.0, run.park
    assert int(run.park.get("skip_calls") or 0) == 4, run.park
    assert len(readings) == 4, readings
    last = readings[-1]
    assert int(last["parked"]) == 1, last
    assert int(last["parked_steps"]) == 0, ("挂机期间这一趟居然跑了回合", last)
    assert int(last["parked_calls"]) == 0, ("挂机期间这一趟居然调了模型", last)
    assert float(last["parked_sec"]) > 0.0, ("挂机时长没有走", last)
    # 真正的睡走的是主时钟的等待账（`clock.await_io`）：假时钟下不真睡，账照记。
    real_slice(None, seconds=3.0, purpose="判据：挂机那一拍要走时钟的账")  # type: ignore[arg-type]
    booked = [r for r in CLK.waits()["rows"] if str(r.get("kind") or "") == "park"]
    assert booked, CLK.waits()["rows"]
    assert booked[0]["where"] == "agent_loop.park", booked[0]
    assert int(booked[0]["skipped"]) == 1, ("假时钟下仍然真睡了", booked[0])
    # 挂机拍落了 append-only 事件（"这一拍为什么没问模型"在盘上可复核）。
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    parked = [e for e in events if e.get("kind") == AL.PARK_EVENT]
    assert len(parked) == 4, [e.get("decision") for e in parked]
    assert {e["decision"] for e in parked} == {"park"}, parked
    assert all(e["task_id"] == me for e in parked), parked


def test_the_park_branch_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把挂机那一支打桩成"照常问模型" ⇒ `parked_steps` 必须 > 0。

    判据 1 断言的是"0"。而 0 也可能来自"这一趟根本没挂上"—— 这一条把那一支拔掉，
    同一个读数必须变成 > 0（审计里那个真机读数就是 3）。
    """
    st, cond, ws = _ws(tmp_path, "novacuum")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")

    def no_park_gate(self_: AgentLoop, *, step: int, run: Any,
                     mailbox: Any) -> dict[str, Any]:
        """打桩：这一支什么也不做（改前的形态 —— 每一拍都问模型）。"""
        return {"skip_model": False, "decision": "run"}

    monkeypatch.setattr(AgentLoop, "_park_gate", no_park_gate)

    def stop_after_two(index: int, prompt: str) -> None:
        if index == 2:
            _stop_now(ws, "判据：看够 3 个回合了")

    gate = _Gate([_tool("clock.now"), _tool("clock.now"), _tool("clock.now")],
                 on_call=stop_after_two)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(gate.prompts) >= 3, ("打桩之后也只问了一两次 ⇒ 判据 1 读的不是这一支",
                                    gate.prompts)
    waiters = CLK.waiters(ws)
    assert int(waiters["parked"]) == 1, waiters
    assert int(waiters["parked_steps"]) > 0, (
        "把挂机那一支打桩成空之后 parked_steps 还是 0 —— 反真空不成立", waiters)
    assert int(waiters["parked_calls"]) > 0, waiters


# ------------------------------------------------------------------ 3 真机路径

def test_a_parent_that_starts_the_park_from_its_own_tool_call_stops_asking(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """真机那条路：模型自己调 `clock.timer_start(wait_for=…)`，之后一拍都不再问。

    两个读数是两件事，所以分开断：
    - 整趟只问过一次模型（起表那一步）；
    - `parked_steps` / `parked_calls` 在挂机区间里不涨（绝对读数是 1：起表那一步
      自己的 `agent_step` 事件落在计时器登记之后，它发生在"挂机"成为结果的那一瞬间，
      不属于挂机区间 —— 审计的探针读到 3 也正是"起表之后又走了 3 个回合"）。
    """
    st, cond, ws = _ws(tmp_path, "toolcall")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    readings: list[dict[str, Any]] = []

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        readings.append(dict(CLK.waiters(ws)))
        bench.advance(seconds)
        if len(readings) == 3:
            _stop_now(ws, "判据：起表之后再挂 3 拍")
        return {"checked": True, "asked_sec": seconds}

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)
    gate = _Gate([_tool("clock.timer_start", wait_for=f"task:{child}",
                        reason="等 D 交回结论")])
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(gate.prompts) == 1, ("起表之后仍然每一拍都问模型", len(gate.prompts))
    assert [s.payload.get("name") for s in run.steps] == ["clock.timer_start"], \
        [s.payload.get("name") for s in run.steps]
    assert int(run.park.get("parked_turns") or 0) == 3, run.park
    assert len(readings) == 3, readings
    first, last = readings[0], readings[-1]
    assert float(last["parked_sec"]) > 0.0, last
    assert int(last["parked_steps"]) == int(first["parked_steps"]), (
        "挂机区间里还在跑回合", first["parked_steps"], last["parked_steps"])
    assert int(last["parked_calls"]) == int(first["parked_calls"]), (
        "挂机区间里还在调模型", first["parked_calls"], last["parked_calls"])


# ------------------------------------------------------------------ 4 唤醒少一次

def _park_wake_run(tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch, *,
                   name: str, skip_is_live: bool) -> tuple[Any, int, dict[str, Any]]:
    """同一个剧本跑一趟：父起表 → 挂机 → 子发消息唤醒 → 收工。

    `skip_is_live=False` 是把"跳过"打桩成空的那一趟（唤醒一律按"等时间"算 ⇒
    改前形态：唤醒那一拍照旧问模型）。
    """
    st, cond, ws = _ws(tmp_path, name)
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me, key=f"park@{name}")
    sleeps: list[float] = []
    readings: list[dict[str, Any]] = []

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        sleeps.append(float(seconds))
        readings.append(dict(CLK.waiters(ws)))
        if len(sleeps) == 1:
            # 挂机中的第一次等待期间，子代理发一条消息（真实写路径：send_message ->
            # sessions.append -> 时钟旁路 `observe_message` 记下这个事件）。
            msg_id, problem = send_message(ws, sender="D", to="M", subject="交差",
                                           body=MARKER, from_task_id=child)
            assert problem == "" and msg_id.startswith("m"), (msg_id, problem)
        bench.advance(seconds)
        return {"checked": True, "asked_sec": seconds}

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)

    if not skip_is_live:
        live = AgentLoop._wake_readings

        def timed_only(self_: AgentLoop, wake_ids: Sequence[str]) -> dict[str, Any]:
            """打桩：把每一条唤醒都算成"等时间"的那一类 ⇒ 跳过这一支永远不成立。"""
            got = live(self_, wake_ids)
            wanted = list(wake_ids or ())
            if wanted:
                got["park"] = []
                got["timed"] = got["timed"] or [{"wake_id": w, "wait_for": "",
                                                 "woke_reason": ""} for w in wanted]
            return got

        monkeypatch.setattr(AgentLoop, "_wake_readings", timed_only)

    # 收工点钉在"第 5 拍"上（拍数按 `_deliver_mailbox` 现数 —— 它每个回合边界只跑一次）。
    # 为什么不按模型调用数停：那会把"少一次调用"这件事本身停掉 —— 两条路的收工点
    # 必须钉在同一个拍上，差值才看得见。
    real_mailbox = AgentLoop._deliver_mailbox
    ticks = {"n": 0}

    def mailbox_once(self_: AgentLoop, *, step: int, messages: list[dict[str, Any]],
                     run: Any) -> dict[str, Any]:
        ticks["n"] = int(ticks["n"]) + 1
        if ticks["n"] >= 5:
            _stop_now(ws, "判据：看够 5 拍了")
        return real_mailbox(self_, step=step, messages=messages, run=run)

    monkeypatch.setattr(AgentLoop, "_deliver_mailbox", mailbox_once)
    gate = _Gate([_tool("clock.timer_start", wait_for=f"task:{child}",
                        reason="等 D 交回结论")]
                 + [_tool("clock.now")] * 8)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)
    assert readings, "这一趟一次都没挂上机 ⇒ 判据没有对象"
    return run, len(gate.prompts), readings[-1]


def test_a_wake_that_ends_the_park_costs_no_model_call(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """子发消息唤醒父 ⇒ 父那一拍不调模型（对比打桩之后 +1）。

    改前红：唤醒被消费之后同一步紧接着 `ask_step` ⇒ 唤醒那一拍就多一次调用；
    本判据问的是"同一剧本、同一唤醒，调用数差 1"。
    """
    live_run, live_calls, live_wait = _park_wake_run(
        tmp_path, bench, monkeypatch, name="ws", skip_is_live=True)
    assert live_run.stop_reason == "stop_file", live_run.to_dict()
    # 那一拍被记成"被唤醒"，原因落在读数上（`event` = 等的人说话了）。
    assert int(live_run.park.get("woke_turns") or 0) == 1, live_run.park
    assert live_run.park.get("woke_reasons") == ["event"], live_run.park
    assert int(live_run.park.get("parked_turns") or 0) >= 1, live_run.park
    # 挂机区间那几拍的读数：零回合零调用（与判据 1 同一份口径）。
    assert int(live_wait["parked_steps"]) == 1, live_wait
    assert int(live_wait["parked_calls"]) == 1, live_wait

    # 反真空：把"跳过"打桩成空 ⇒ 同一个剧本多一次调用（这就是改前的那一次）。
    stubbed_run, stubbed_calls, _ = _park_wake_run(
        tmp_path, bench, monkeypatch, name="novacuum", skip_is_live=False)
    assert stubbed_run.stop_reason == "stop_file", stubbed_run.to_dict()
    assert int(stubbed_run.park.get("woke_turns") or 0) == 0, stubbed_run.park
    assert stubbed_calls == live_calls + 1, (
        "把'跳过'打桩成空之后调用数没有多 1 ⇒ 判据读的不是那一支",
        live_calls, stubbed_calls)
