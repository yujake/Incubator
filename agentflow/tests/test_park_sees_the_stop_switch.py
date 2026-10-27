# -*- coding: utf-8 -*-
"""Q21（2026-10-26）：挂机期间要看得见停机开关 —— 叫停 5 秒内这一趟收工。

## 改前的真身（探针读数，零模型钱、假时钟）

`_park_slice` 只做一件事：`return CLK.await_io(seconds, purpose, kind="park",
where="agent_loop.park")` —— 片内不读停机开关。片长由 `run.park["slice_sec"]` 的退避
决定（0.5 秒起、每拍翻倍到 `PARK_SLICE_MAX_SEC=300`），而停机判定 `_stop_applies`
只被 `_user_stop_reason` 调，且 `_user_stop_reason` 在循环里只有一个调用点（循环头）。
于是开关落在 300 秒那一片里时，这一趟要睡满那一片才可能看到它。

`agentflow/temp/_q21_probe.py` 的读数（改前）：挂机 11 拍、片长
`0.5,1,2,4,8,16,32,64,128,256,300`、`park_asked_sec=811.5`；开关投在 300 秒那一片
开始的时刻（假时钟 511.5）⇒ 开关之后又睡了 300.0 秒才收工，`run.notes` 里一句
"被叫停"都没有。更糟的形态是开关投在模型调用的回调里：挂机不调模型 ⇒ 开关永不出现
⇒ 空转到 CI 超时（`tests/test_timers_and_handoff_semantics.py:445-451` 记着那一次）。

## 五条判据（每条都写清"改前红在哪"）

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| `test_a_a_stop_switch_during_the_park_ends_the_run_within_one_poll` | a) 挂机 + 30 分钟后才有事件，开关投在长片里 ⇒ 一片之内（5 秒）收工；且假时钟读数是"每片都看了一次" | 改前那一片睡满 300 秒才回到循环头（同一条判据里的 `old` lane 逐字复刻它，当场红） |
| `test_b_the_reading_says_it_was_stopped_while_parked` | b) 读数：`run.notes` 里有"在挂机中被叫停（等了 X 秒）"，`stop_reason` 仍是既有那两档 | 改前 `run.notes` 里没有这一句（测不到"等了几秒"） |
| `test_c_without_a_stop_switch_the_backoff_is_byte_identical` | c) 正控：没有停机时片长退避与拍数逐字不变（0.5,1,2,4,8 不是定长 5 秒） | 正控 —— 改前也绿（它钉的是"不变"），改后必须仍绿 |
| `test_d_a_slow_slice_is_short_pieces_under_the_fake_clock` | d) 假时钟下不真睡：12 秒被切成 5+5+2 三片，账照记、`skipped` +3，墙钟几乎不走 | 改前只记一条、`calls=1`、`skipped=1` |
| `test_e_the_per_piece_stop_check_is_load_bearing` | e) 反真空：把"每片之后查停机"打桩成永远不停 ⇒ a 的读数必红 | 改前连那一处都不存在（判据在这一档当场红并点名） |

## 边界

全部 tmp 工作区、假时钟、替身缝（`_Gate` 照剧本回答），零真实模型调用、零真睡。
时间由 `CLK.await_io` 的包装拨（每片拨一格假时钟），停机开关投的时机由"假时钟走到
哪一秒"决定 —— 于是"开关落在长片里"是结构上可复现的，不是看运气。
"""

from __future__ import annotations

import json
import pathlib
import re
import time
from typing import Any, Callable, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import sessions as SS
from agentflow import stopctl
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from _d68_board_fixture import children_clean_their_boards  # noqa: E402 - D-68 夹具助手

SID = "q21"
TASK = "Q21：挂机期间投停机开关，这一趟要在一小片之内收工"

#: 这一片的上限（与 `agent_loop.PARK_STOP_POLL_SEC` 同值；那条常量本身由判据 d 钉住）。
#: 判据里不直接用 `AL.PARK_STOP_POLL_SEC` 是为了让"改前红"红在行为上（改前没有这条常量）。
POLL_SEC = 5.0

#: 被等的子代理"30 分钟后才有事件"：等谁的那条表带这个上限，本判据里它一直不说话。
#: 于是挂机只会被两件事打断：开关（判据要的）或这个上限（反真空那一条用它兜底）。
EVENT_AFTER_SEC = 1800.0

#: 开关落在假时钟的第几秒。591.5 落在"片长 300 秒"那一片里面
#:（片界：… 255.5, 511.5, 811.5；这一片的起点是 511.5）—— 改前正是这一片睡满才看得到。
SWITCH_AT_SEC = 600.0


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


def _stop_now(ws: pathlib.Path, why: str, *, force: bool = False) -> None:
    stopctl.request_stop(ws, reason=why, force=force)


def old_park_slice(self_: Any, *, seconds: float, purpose: str) -> dict[str, Any]:
    """改前那一行（逐字）：一次 `CLK.await_io`，片内不读停机开关。

    a / c 两条判据都跑同一个剧本的两条 lane，差的只有这一行 —— 于是"改前红"不是
    靠回忆，而是靠同一个夹具里当场跑出来的那一档。
    """
    return CLK.await_io(seconds, purpose, kind="park", where="agent_loop.park")


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
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    children_clean_their_boards(cond)
    return st, cond, ws


def _child(cond: Conductor, parent: str, key: str = "q21@child") -> str:
    """造一行还在飞的子代理（等谁的那一条的等待对象：它 30 分钟后才说话）。"""
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


# ------------------------------------------------------------------ 一个剧本两条 lane


def _park_run(tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch, *,
              name: str, lane: str = "live", stop_at_tick: int = 6,
              switch_at_sec: float | None = None, force: bool = False,
              stub_stop_check: bool = False) -> dict[str, Any]:
    """挂机的一趟：两种"收工"来源按 lane 装配，读数逐格带回。

    - `lane="live"`：真的 `_park_slice`（片内循环、片后读开关）；
    - `lane="old"`：把 `_park_slice` 换回改前那一行（`old_park_slice`，逐字）。

    收工的来源二选一：
    - `switch_at_sec` 给了 ⇒ 假时钟走到那一秒所在的那一片起点投停机开关
      （建模"开关落在这一片里"的最坏形态：这一片睡满之后才可能被读到）；
    - 没给 ⇒ 第 `stop_at_tick` 拍的信箱投递时投开关（拍边界上，两条 lane 完全一样，
      用来做"没有停机时逐字相同"的正控）。
    """
    st, cond, ws = _ws(tmp_path, name)
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me, key=f"q21@{name}")
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M", max_wait_sec=EVENT_AFTER_SEC)
    if lane == "old":
        monkeypatch.setattr(AgentLoop, "_park_slice", old_park_slice)

    state: dict[str, Any] = {"cum": 0.0, "pieces": [], "seen_at": [], "switch_at": None,
                             "beats": [], "stubbed": False}
    real_await = CLK.await_io

    def await_and_tick(seconds: float, purpose: str, **kw: Any) -> dict[str, Any]:
        """拨假时钟的那一格（只拨挂机的睡；别的等待原样放过）。"""
        if str(kw.get("kind") or "io") != "park":
            return real_await(seconds, purpose, **kw)
        piece = float(seconds)
        state["pieces"].append(round(piece, 6))
        if (switch_at_sec is not None and state["switch_at"] is None
                and state["cum"] < switch_at_sec <= state["cum"] + piece):
            state["switch_at"] = round(float(state["cum"]), 6)
            _stop_now(ws, "判据：挂机期间叫停", force=force)
        bench.advance(piece)
        state["cum"] = round(float(state["cum"]) + piece, 6)
        return real_await(seconds, purpose, **kw)

    monkeypatch.setattr(CLK, "await_io", await_and_tick)

    real_stop_reading = getattr(AgentLoop, "_park_stop_reading", None)

    def never_stop(self_: Any) -> dict[str, Any]:
        """反真空：把"每片之后查停机"打桩成永远不停。"""
        return {"checked": True, "stop": False, "stop_reason": "", "why": "打桩：不查"}

    if stub_stop_check:
        if real_stop_reading is not None:
            monkeypatch.setattr(AgentLoop, "_park_stop_reading", never_stop)
            state["stubbed"] = True
    elif real_stop_reading is not None:
        def spy(self_: Any) -> dict[str, Any]:
            """每一读记下"当时的假时钟"——判据 ② 要的是"每 5 秒看一次"，不是总时长。"""
            got = real_stop_reading(self_)
            state["seen_at"].append(round(float(state["cum"]), 6))
            return got

        monkeypatch.setattr(AgentLoop, "_park_stop_reading", spy)

    # 拍边界：挂机的一拍 = `_park_sleep_once` 的一次调用（`_park_gate` 第 ①/④ 支）。
    # 用这条缝而不动别处的读数：拍边界上的假时钟读数就是"这一拍从哪一秒开始"。
    real_sleep_once = AgentLoop._park_sleep_once

    def sleep_once(self_: AgentLoop, *, run: Any, parked: Any) -> dict[str, Any]:
        state["beats"].append(round(float(state["cum"]), 6))
        if switch_at_sec is None and len(state["beats"]) == stop_at_tick:
            _stop_now(ws, "判据：拍边界上叫停")
        return real_sleep_once(self_, run=run, parked=parked)

    monkeypatch.setattr(AgentLoop, "_park_sleep_once", sleep_once)

    gate = _Gate([_tool("clock.now")] * 8)
    t0 = time.monotonic()
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user",
                                            my_task_id=me, depth=1)
    wall = time.monotonic() - t0
    return {"run": run, "ws": ws, "me": me, "gate": gate, "state": state,
            "wall_sec": wall, "prompts": list(gate.prompts),
            "asked_sec": float(run.park.get("asked_sec") or 0.0),
            "beat_secs": _beat_secs(state["beats"], state["cum"], state["pieces"]),
            "notes": list(run.notes)}


def _beat_secs(beats: Sequence[float], total: float,
               pieces: Sequence[float]) -> list[float]:
    """每一拍请了多少秒（按拍边界的假时钟读数差算，最后再加一拍收尾的余量）。

    为什么不数 `_park_slice` 被调了几次：改后一拍是几片，改前是一整片 —— 这条读数
    要能跨这两种形态比"每一拍的总量"（那是退避的真身）。
    """
    edges = [round(float(x), 6) for x in beats] + [round(float(total), 6)]
    return [round(b - a, 6) for a, b in zip(edges, edges[1:])]


# ------------------------------------------------------------------ a) 5 秒内收工


def test_a_a_stop_switch_during_the_park_ends_the_run_within_one_poll(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) 挂机 + 30 分钟后才有事件；开关投在 300 秒那一片里 ⇒ 一片之内收工。

    改前红：同一条判据里的 `old` lane 把 `_park_slice` 换回改前那一行 ⇒ 开关之后
    又睡满 300 秒（这个数就是探针量到的 300.0）。改后 `live` lane 的读数必须是
    "开关之后 ≤ 5 秒"，而且 ② 要的是"每片都看了一次"—— `seen_at` 的相邻间隔
    必须都不超过 `POLL_SEC`（不是只看总时长）。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="q21a-live",
                     lane="live", switch_at_sec=SWITCH_AT_SEC)
    run, state = live["run"], live["state"]

    assert state["switch_at"] is not None, "这一趟没挂上机 ⇒ 判据没有对象"
    assert state["switch_at"] >= 500.0, state["switch_at"]     # 落在"300 秒那一片"里
    assert run.stop_reason == "stop_file", run.to_dict()
    assert live["prompts"] == [], ("挂着机还在问模型", len(live["prompts"]))
    latency = live["asked_sec"] - float(state["switch_at"])
    assert latency <= POLL_SEC + 1e-6, (
        f"开关之后还睡了 {latency:.1f} 秒（上限 {POLL_SEC}）", live["asked_sec"],
        state["switch_at"])
    assert max(state["pieces"]) <= POLL_SEC + 1e-6, max(state["pieces"])

    # ② "片内真的每 5 秒看了一次"（不是只看总时长）
    assert state["seen_at"], ("一片之内一次停机开关都没读", state["pieces"])
    first_after = [t for t in state["seen_at"] if t >= float(state["switch_at"])]
    assert first_after, state["seen_at"]
    assert first_after[0] - float(state["switch_at"]) <= POLL_SEC + 1e-6, (
        "开关落下之后隔了太久才读第一次", state["switch_at"], first_after[0])
    gaps = [round(b - a, 6) for a, b in zip(state["seen_at"], state["seen_at"][1:])]
    assert gaps and max(gaps) <= POLL_SEC + 1e-6, (
        "相邻两次读开关的间隔超过一片", max(gaps), state["seen_at"])

    # 改前那一档：同一个剧本、只换回那一行 ⇒ 必须红
    old = _park_run(tmp_path, bench, monkeypatch, name="q21a-old",
                    lane="old", switch_at_sec=SWITCH_AT_SEC)
    old_latency = old["asked_sec"] - float(old["state"]["switch_at"] or 0.0)
    assert old["state"]["switch_at"] is not None, old["state"]
    assert old_latency > POLL_SEC, (
        "改前那一行也 5 秒内收工 ⇒ 这条判据测的不是片内读开关", old_latency)
    assert old["run"].stop_reason == "stop_file", old["run"].to_dict()
    assert not [n for n in old["notes"] if "在挂机中被叫停" in n], old["notes"]


# ------------------------------------------------------------------ b) 读数


def test_b_the_reading_says_it_was_stopped_while_parked(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b) 读数：`run.notes` 里有"在挂机中被叫停（等了 X 秒）"，`stop_reason` 不新造档。

    改前红：`run.notes` 里没有这一句（挂机那几拍不落任何"被叫停"的读数）。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="q21b", switch_at_sec=SWITCH_AT_SEC)
    run = live["run"]
    notes = [n for n in live["notes"] if "在挂机中被叫停" in n]
    assert len(notes) == 1, ("'在挂机中被叫停'应当只落一条", live["notes"])
    hit = re.search(r"在挂机中被叫停（等了 ([0-9.]+) 秒）", notes[0])
    assert hit, notes[0]
    waited = float(hit.group(1))
    assert 0.0 < waited <= POLL_SEC + 1e-6, ("叫停之后等的那一段超过一片", notes[0])
    # 同一句里还带着"这一拍一共等了多久"（那是入参 `seconds` 的真身，不是判据要的那个数）
    total_hit = re.search(r"这一拍一共等了 ([0-9.]+) 秒", notes[0])
    assert total_hit, notes[0]
    assert waited <= float(total_hit.group(1)) <= 300.0 + 1e-6, notes[0]
    assert run.stop_reason == "stop_file", run.to_dict()
    assert int(run.park.get("stopped_in_park") or 0) == 1, run.park
    assert abs(float(run.park.get("stopped_sec") or 0.0) - waited) < 1e-6, run.park

    # 既有那一档的另一支：force ⇒ `force_stop`（不新造理由码）
    forced = _park_run(tmp_path, bench, monkeypatch, name="q21b-force",
                       switch_at_sec=SWITCH_AT_SEC, force=True)
    assert forced["run"].stop_reason == "force_stop", forced["run"].to_dict()
    assert [n for n in forced["notes"] if "在挂机中被叫停" in n], forced["notes"]


# ------------------------------------------------------------------ c) 正控：退避不变


def test_c_without_a_stop_switch_the_backoff_is_byte_identical(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 正控：没有停机时，挂机的片长与拍数逐字与今天相同（退避不许改成定长 5 秒）。

    两条 lane 走同一个剧本（第 6 拍挂机开始时投开关 ⇒ 前 5 拍一片没被叫停）：
    - `beat_secs[:5]` 两边都必须等于 `[0.5, 1.0, 2.0, 4.0, 8.0]`（退避的真身；
      改成定长 5 秒这一条当场红）；
    - `parked_turns` / `skip_calls` / `agent_park` 的 decision 序列两边逐一相等；
    - 前 5 拍没有任何"在挂机中被叫停"的读数（正控就是"没停机时什么也没变"）。

    改前红：不红 —— 这是正控（它钉的是"不改坏"）。改后必须仍绿。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="q21c-live", lane="live")
    old = _park_run(tmp_path, bench, monkeypatch, name="q21c-old", lane="old")

    expect = [0.5, 1.0, 2.0, 4.0, 8.0]
    assert live["beat_secs"][:5] == expect, live["beat_secs"]
    assert old["beat_secs"][:5] == expect, old["beat_secs"]
    assert live["beat_secs"][:5] == old["beat_secs"][:5], (live["beat_secs"],
                                                          old["beat_secs"])
    for key in ("parked_turns", "skip_calls"):
        assert int(live["run"].park.get(key) or 0) == int(old["run"].park.get(key) or 0), (
            key, live["run"].park, old["run"].park)
    assert int(live["run"].park.get("parked_turns") or 0) == 6, live["run"].park
    # 前 5 拍一个停机开关都没有 ⇒ 两条 lane 的逐拍等待量与 decision 逐字相等
    #（第 6 拍起开关才在盘上，那一拍的差别正是 a 条要的那件事）。
    events: dict[str, list[dict[str, Any]]] = {}
    for name, lane in (("live", live), ("old", old)):
        got, problems = SS.read_session(lane["ws"], sid=SID)
        assert not problems, problems
        parked_events = [e for e in got if e.get("kind") == AL.PARK_EVENT]
        assert [e.get("decision") for e in parked_events] == ["park"] * 6, parked_events
        assert [float(e.get("waited_sec") or 0.0) for e in parked_events][:5] == expect, (
            name, parked_events)
        assert not [e for e in parked_events[:5]
                    if "在挂机中被叫停" in str(e.get("reason") or "")], (name, parked_events)
        events[name] = parked_events
    assert [e.get("waited_sec") for e in events["live"]][:5] == \
        [e.get("waited_sec") for e in events["old"]][:5], (
            "两条 lane 的逐拍等待量不一样", events["live"], events["old"])




# ------------------------------------------------------------------ d) 假时钟下不真睡


def test_d_a_slow_slice_is_short_pieces_under_the_fake_clock(
        tmp_path: pathlib.Path, bench) -> None:
    """d) 假时钟替身下不真睡：12 秒 = 5 + 5 + 2 三片，账照记、`skipped` +3。

    这一条直接调真 `_park_slice`（不经替身缝），钉两件事：
    - 切片本身（12 秒不是一整条，而是三片，`asked_sec` 加起来还是 12.0）；
    - 既有那条"假时钟不真睡"的口径一个字没变（每片一条 `skipped`）。

    改前红：`calls=1`、`skipped=1`、返回值里没有 `stopped` 这一格。
    """
    st, cond, ws = _ws(tmp_path, "q21d")
    me = cond.open_top_level_run("M", TASK)
    loop = _loop(st, cond, ws, _Gate([_tool("clock.now")]), me)
    t0 = time.monotonic()
    got = loop._park_slice(seconds=12.0, purpose="判据：假时钟下不真睡")
    wall = time.monotonic() - t0

    assert AL.PARK_STOP_POLL_SEC == POLL_SEC, AL.PARK_STOP_POLL_SEC
    assert got.get("stopped") is False, got
    assert abs(float(got.get("asked_sec") or 0.0) - 12.0) < 1e-6, got
    rows = [r for r in CLK.waits()["rows"] if str(r.get("kind") or "") == "park"]
    assert len(rows) == 1, rows                      # 同一个 (kind, where, purpose) 聚合成一行
    row = rows[0]
    assert row["where"] == "agent_loop.park", row
    assert int(row["calls"]) == 3, ("12 秒没有切成 5 + 5 + 2", row)
    assert abs(float(row["asked_sec"]) - 12.0) < 1e-6, row
    assert int(row["skipped"]) == 3, ("假时钟下仍然真睡了", row)
    assert wall < 2.0, wall


# ------------------------------------------------------------------ e) 反真空


def test_e_the_per_piece_stop_check_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空：把"每片之后查停机"打桩成永远不停 ⇒ a 的读数必须红。

    打桩之后挂机会一直睡到 `EVENT_AFTER_SEC` 那道上限（那是另一条收工路，不是判据 a
    要的那条），于是"开关之后的等待量"必然远超一片 —— 这一条钉的是"a 读的正是那处"。
    """
    live = _park_run(tmp_path, bench, monkeypatch, name="q21e-live",
                     switch_at_sec=SWITCH_AT_SEC)
    assert live["asked_sec"] - float(live["state"]["switch_at"]) <= POLL_SEC + 1e-6

    stubbed = _park_run(tmp_path, bench, monkeypatch, name="q21e-stub",
                        switch_at_sec=SWITCH_AT_SEC, stub_stop_check=True)
    assert stubbed["state"]["stubbed"] is True, (
        "反真空的打桩点不存在（`_park_stop_reading`）⇒ 挂机期间根本没有'每片查停机'这一处")
    latency = stubbed["asked_sec"] - float(stubbed["state"]["switch_at"])
    assert latency > POLL_SEC, (
        "把'每片查停机'打桩掉之后仍然 5 秒内收工 ⇒ 判据 a 读的不是这一处",
        latency, stubbed["asked_sec"])
    assert stubbed["run"].stop_reason == "stop_file", stubbed["run"].to_dict()
    assert not [n for n in stubbed["notes"] if "在挂机中被叫停" in n], stubbed["notes"]
