# -*- coding: utf-8 -*-
"""Q22：派活之后欠模型一拍（"要不要返场"只有一处判据）。

## 这一份钉的是哪一件事

D-64 的要点是"派活是可抢占的"：派完下一拍就要给父代理一个回合。p206 的挂机口径是
"无事可做就挂在时钟上"。两条口径在改前正面相撞，撞点只有一个：返场没有落点 ——

真机探针（逐拍读数）：`summon_many` 派 3 个子、每个挂一条 `arm_child_waiter`
（`wait_for=task:<子>`）⇒ 从 step 1 起 `parked=3`，而 `_pending_work` 三条判据
（新投递 / 未消项 / 待消费的子产出）全不成立 ⇒ 每一拍都落进 `_park_gate` 的第 ④ 支
（"挂着等谁且本趟无事可做 ⇒ 挂机"）。睡眠退避 0.5 -> 1 -> 2 -> 4 -> 8 -> 16 秒，
`asked_sec=31.5 / 整趟 46 秒` = 86% 在挂机；真机缺省参数（`CHILD_RETURN_WAIT_SEC=300`、
`PARK_SLICE_MAX=300`）下 6 拍就上到半小时量级，而那 6 拍里一次模型回合都没有。

## 五条判据（a / b 改前红，c / d 是两条正控，e 是反真空）

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 派 2 个长活子 ⇒ 孩子结束之前至少有一次模型回合，且那一刻台账里两条子行都还是 running | 改前一次都没有：第二次模型调用注定落在孩子全部落定之后（Q22 的形态） |
| b | `woke` 那一拍本身仍不调模型（p206 第 4 条正控不破），但它之后的那一拍必须是模型回合：孩子回来之后不许再睡一拍 | 改前 `woke` 之后还有一条在飞的 waiter ⇒ 下一拍又落进第 ④ 支去睡 |
| c | 正控：只挂自己设的闹钟（`after_sec` + `clock.wait_any`，无子）⇒ 照旧挂机、不返场 | 改前也是挂机（这一条是"别把闹钟误判成我派的活"） |
| d | 正控：等的是一个历史子行（在跑，但不是这一趟派的）⇒ 照旧挂机、不返场 | 改前也是挂机（这一条守 p206 那条语义不被放宽） |
| e | 反真空：把返场判据打桩成恒 False ⇒ a 必红 | 这一条是"a 真的在读那一处判据"的机器证明 |

## 边界

全部 tmp 工作区、替身模型、替身后端（孩子的"跑很久"由 `threading.Event` 造，
不靠 `time.sleep` 的时长），零真实模型调用。挂机那一拍真睡的地方被换成"只记账"，
于是整份判据在毫秒级跑完 —— 与 `tests/test_park_is_a_real_stop.py` 同一档的替身缝。
"""
from __future__ import annotations

import json
import pathlib
import threading
from typing import Any, Callable, Mapping, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import stopctl
from agentflow.conductor import Conductor
from agentflow.store import Store

import test_summon_is_preemptible as TSP

SID = "q22"
TASK = "Q22 的判据夹具：派活之后欠模型一拍"
ROLE = TSP.ROLE
KID = TSP.KID
FINAL = TSP.FINAL
LOOK = TSP.LOOK
#: 子代理返场那一段的开头（`_children_round_trip` 的 `text` 逐字）。
RETURN_MARK = "【子代理返场】"

#: 一次派两个长活（与 `test_summon_is_preemptible.py` 的 MANY 同形，只是两件）。
TWO = [{"role": KID, "task": f"第 {i} 件长活", "instance": str(i)} for i in (1, 2)]
MANY2 = json.dumps({"summon_many": {"targets": TWO}}, ensure_ascii=False)

#: 派活之后最多空转几拍就放行孩子（改前红那一趟的出口：不然它会一直挂着）。
#: 数值只影响跑得多快，不影响任何一个判据的口径。
RELEASE_AFTER_SLICES = 10


# ------------------------------------------------------------------ 替身

class _SplitBackend:
    """一个"每个孩子各自卡住"的后端：判据自己决定先放谁、什么时候放。

    为什么不用 `test_summon_is_preemptible._BlockingBackend`：那一个是一条闸放全部，
    而判据 b 要的正是"一个先回来、另一个还在跑"那一档（woke 之后还有 waiter 在飞）。
    """

    name = "split"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gates: dict[str, threading.Event] = {}
        self.calls: list[dict[str, Any]] = []

    def known_roles(self) -> list[str]:
        return [KID]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover - 接口需要
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append({"role": str(role), "action": str(action),
                               "instance": str(instance), "task_id": str(task_id)})
            gate = self._gates.setdefault(str(task_id), threading.Event())
        if not gate.wait(timeout=60.0):
            return {"outcome": "no_result", "detail": "判据：这个孩子的放行超时了"}
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"llm_run_path": f"out/tasks/{task_id or 'x'}.json",
                            "final": f"{role}#{instance or '-'} 的结论"}}

    def entered(self) -> int:
        with self._lock:
            return len(self.calls)

    def release(self, task_id: str) -> None:
        with self._lock:
            gate = self._gates.get(str(task_id))
        if gate is not None:
            gate.set()

    def release_all(self) -> None:
        with self._lock:
            gates = list(self._gates.values())
        for gate in gates:
            gate.set()


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, _SplitBackend, Conductor, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _SplitBackend()
    cond = Conductor(st, policy=TSP.Policy(), backend=backend)
    me = cond.open_top_level_run(ROLE, TASK)
    return ws, st, backend, cond, me


def _loop(st: Store, ws: pathlib.Path, cond: Conductor, gate: Any, me: str) -> Any:
    return TSP._loop(st, ws, cond, gate, me, step_wait=0.02, return_wait=0.05, drain=0.2)


def _rows(st: Store, parent: str) -> list[dict[str, Any]]:
    return [r for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and not str(r.get("kind") or "")]


def _running(st: Store, parent: str) -> list[str]:
    return [str(r.get("task_id")) for r in _rows(st, parent)
            if str(r.get("status") or "") == "running"]


def _child(cond: Conductor, parent: str, key: str = "q22@child") -> str:
    """造一行还在飞的历史子行（不是这一趟派的：没有句柄、没有返场账）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-26T09:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def _tool(name: str, **args: Any) -> str:
    return json.dumps({"tool": name, "args": args}, ensure_ascii=False)


class _Gate:
    """照剧本回答的替身模型：记下每一次提示词，`on_call(index, prompt)` 在回答之前跑。"""

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


class _SliceWatch:
    """替身缝：挂机那一拍只记账、不真睡；到点了由剧本放行孩子 / 落停机开关。

    注意方法本身是"普通函数"而不是绑定方法：它要挂到 `AgentLoop._park_slice` 上，
    而绑定方法不是描述符 —— 直接挂上去时调用方只给关键字实参，会把 `_self` 漏掉
    （`TypeError: missing 1 required positional argument`，挂机支会把它折成
    "睡不下去"然后空转到上限）。`stub()` 返回的就是那个普通函数。

    `wait_until` 用来把"孩子在我睡着的时候回来"这件事钉成确定的顺序：真机上挂机那一拍
    是几百秒的睡，孩子当然是在睡里回来的；替身缝不睡，所以这里显式等到那一行落终态
    再返回 —— 于是"下一拍先吃唤醒、再取产出"这个顺序是判据造出来的，不是碰巧。
    """

    def __init__(self) -> None:
        self.asked: list[float] = []
        self.on_slice: Callable[[int], None] | None = None
        self.wait_until: Callable[[], bool] | None = None

    def stub(self) -> Callable[..., dict[str, Any]]:
        def park_slice(_self: Any, *, seconds: float, purpose: str) -> dict[str, Any]:
            assert "挂机等" in purpose, purpose
            assert seconds > 0, seconds
            self.asked.append(float(seconds))
            if self.on_slice is not None:
                self.on_slice(len(self.asked))
            if self.wait_until is not None:
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline and not self.wait_until():
                    time.sleep(0.01)
            return {"checked": True, "asked_sec": sum(self.asked)}

        return park_slice


class _Spy:
    """把 `_park_gate` 每一拍的结论抄一份（判据 b 断的是拍序，不是墙钟）。"""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.beats: list[dict[str, Any]] = []
        self.slices_at: Callable[[], int] = lambda: 0
        self.calls_at: Callable[[], int] = lambda: 0

    def stub(self) -> Callable[..., dict[str, Any]]:
        def gate(self_: Any, *, step: int, run: Any, mailbox: Any) -> dict[str, Any]:
            out = self.real(self_, step=step, run=run, mailbox=mailbox)
            self.beats.append({"step": int(step), "decision": str(out.get("decision") or ""),
                               "skip": bool(out.get("skip_model")),
                               "slices": int(self.slices_at()),
                               "calls": int(self.calls_at()),
                               "reason": str(out.get("reason") or "")[:200]})
            return out

        return gate


def _scenario(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
              replies: Sequence[str],
              on_call: Callable[[int, str, dict[str, Any]], None] | None = None,
              release_after: int = RELEASE_AFTER_SLICES,
              hook: Callable[[int, dict[str, Any]], None] | None = None,
              wait_until: Callable[[dict[str, Any]], bool] | None = None,
              stop_after: int = 0,
              spy: bool = False) -> dict[str, Any]:
    """一条剧本：派两个长活 -> 返场 -> ...... -> 孩子全回来 -> 收工。

    `hook(n, state)` 在"第 n 拍挂机"里跑（判据 b 用它造出"孩子说了一句话"那一档：
    那句话会唤醒父代理，但孩子本人还在跑 —— 于是 woke 之后还剩一条 waiter 在飞）。
    """
    ws, st, backend, cond, me = _ws(tmp_path)
    watch = _SliceWatch()
    state: dict[str, Any] = {"ws": ws, "st": st, "backend": backend, "me": me,
                             "watch": watch, "gate": None, "loop": None}

    def on_slice(n: int) -> None:
        if stop_after and n >= stop_after:
            stopctl.request_stop(ws, reason="判据：睡够了")
            return
        if hook is not None:
            hook(n, state)
        if release_after and n >= release_after:
            backend.release_all()

    watch.on_slice = on_slice
    watch.wait_until = (lambda: bool(wait_until(state))) if wait_until else None
    monkeypatch.setattr(AL.AgentLoop, "_park_slice", watch.stub())
    recorder = _Spy(AL.AgentLoop._park_gate)
    recorder.slices_at = lambda: len(watch.asked)
    recorder.calls_at = lambda: len(state["gate"].prompts) if state["gate"] else 0
    if spy:
        monkeypatch.setattr(AL.AgentLoop, "_park_gate", recorder.stub())
        state["spy"] = recorder

    def _on_call(index: int, prompt: str) -> None:
        if on_call is not None:
            on_call(index, prompt, state)

    gate = _Gate(list(replies), on_call=_on_call)
    loop = _loop(st, ws, cond, gate, me)
    state["loop"] = loop
    state["gate"] = gate
    state["run"] = TSP._run(loop, me)
    return state


# ------------------------------------------------------------------ a. 打发之后先返场

def _dispatch_two(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
                  stub_return: bool) -> dict[str, Any]:
    """判据 a 的那一趟（判据 e 复用同一趟，只把返场判据打桩成恒 False）。"""
    if stub_return:
        def no_return(self_: Any, **kw: Any) -> dict[str, Any]:
            return {"checked": True, "owed": False,
                    "why": "判据：把返场判据打桩成恒 False",
                    "own": [], "own_running": [], "waiters": [], "own_waiters": [],
                    "all_task_waiters": False, "woke_own": [], "woke_children": [],
                    "new_work": False, "return_owed": []}

        monkeypatch.setattr(AL.AgentLoop, "_return_reading", no_return, raising=False)

    seen: dict[str, Any] = {"turns": [], "field": []}

    def on_call(index: int, prompt: str, state: dict[str, Any]) -> None:
        running = _running(state["st"], state["me"])
        seen["turns"].append({"index": index, "running": running,
                              "slices": len(state["watch"].asked)})
        if len(running) == 2:
            seen["field"].append(index)
            state["backend"].release_all()

    state = _scenario(tmp_path, monkeypatch,
                      replies=[MANY2, LOOK, FINAL, FINAL, FINAL], on_call=on_call)
    seen["state"] = state
    return seen


def test_dispatch_owes_the_model_one_turn_before_the_children_end(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 a：派 2 个长活 ⇒ 孩子结束之前至少一次模型回合，且那一刻两条子行都 running。

    改前红：改前 `_pending_work` 三条都不成立 ⇒ 每一拍都进第 ④ 支去挂机，
    "第一次在孩子还在跑的时候被问模型"这件事结构上不会发生：
    探针读数就是 6 拍全 `skip_model=True`、`asked_sec=31.5`。
    """
    seen = _dispatch_two(tmp_path, monkeypatch, stub_return=False)
    got = seen["state"]
    run = got["run"]

    assert run.stop_reason == "final", run.to_dict()
    # 一、孩子结束之前真的有模型回合，而且那一刻台账里两条子行都还是 running。
    assert seen["field"], (
        "派活之后、孩子结束之前一次模型回合都没有（Q22 的形态）", seen["turns"])
    field = seen["turns"][seen["field"][0]]
    assert len(field["running"]) == 2, field
    # 二、"在孩子结束之前"：那个回合之后孩子才落定（最后两条都是 done）。
    rows = _rows(got["st"], got["me"])
    assert len(rows) == 2, rows
    assert all(str(r.get("status") or "") == "done" for r in rows), rows
    # 三、那一拍是返场：这一批"欠的那一拍"用回合还，不是用睡眠还（它之前一拍都没睡）。
    assert field["slices"] == 0, ("返场那一拍照样先睡了几拍", field, got["watch"].asked)
    # 四、读数里点名了那一批（"这一批已经给过回合"）。
    #     返场次数不钉成 1：孩子回来之后的那一拍按判据也该返场一次（第 ③ 支跳过的那一拍
    #     由下一拍补上），两次各是各的账；这里只要求"至少一次"，并把给过回合的那一批点名。
    assert int(run.park.get("reentry_turns") or 0) >= 1, run.park
    assert run.park.get("reentry_reasons"), run.park
    given = [str(x) for x in (run.park.get("return_given") or ())]
    assert sorted(given) == sorted(str(r.get("task_id")) for r in rows), (given, rows)


# ------------------------------------------------------------------ b. woke 之后那一拍

def test_the_beat_after_a_wake_is_a_model_turn(tmp_path: pathlib.Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 b：`woke` 那一拍仍不调模型；它之后的那一拍必须是模型回合。

    改前红：孩子回来时 `woke` 那一拍跳过（这一档是 p206 的正控，不许破），而下一拍
    还有一条在飞的 waiter（`parked=1`）⇒ 又落进第 ④ 支睡一拍 —— 那条返场的产物
    已经在上下文里，却要为它多睡一个 `PARK_SLICE`。

    夹具钉的是确定的顺序：第一个孩子在"挂机那一拍"里回来（替身缝等到它落终态才返回），
    于是下一拍的顺序固定为"先吃唤醒（③ 跳过）、同一拍取到产出"，再下一拍就是判据要
    断的那一拍。改前那一拍是第 ④ 支的睡眠；改后它必须是模型回合。
    """
    pick: dict[str, str] = {}
    seen: dict[str, Any] = {"turns": []}

    def hook(n: int, state: dict[str, Any]) -> None:
        if n != 1:
            return
        rows = _rows(state["st"], state["me"])
        if rows and not pick:
            pick["id"] = sorted(str(r.get("task_id")) for r in rows)[0]
            state["backend"].release(pick["id"])

    def on_call(index: int, prompt: str, state: dict[str, Any]) -> None:
        seen["turns"].append({"index": index, "back": RETURN_MARK in prompt})

    def came_back(state: dict[str, Any]) -> bool:
        tid = str(pick.get("id") or "")
        return bool(tid) and any(
            str(r.get("task_id")) == tid and str(r.get("status") or "") == "done"
            for r in _rows(state["st"], state["me"]))

    got = _scenario(tmp_path, monkeypatch,
                    replies=[MANY2, LOOK, LOOK, LOOK, FINAL, FINAL],
                    on_call=on_call, hook=hook, wait_until=came_back, spy=True)
    run = got["run"]
    beats = got["spy"].beats
    prompts = got["gate"].prompts

    assert run.stop_reason == "final", run.to_dict()
    assert pick, "夹具没放回任何一个孩子 ⇒ 判据没有对象"
    # 一、woke 那一档仍在（p206 第 4 条正控不破）：有一拍被记成"被唤醒"、没调模型。
    assert int(run.park.get("woke_turns") or 0) >= 1, (run.park, beats)
    woke = [i for i, b in enumerate(beats) if b["decision"] == "woke"]
    assert woke, ("这一趟没有 woke 那一拍 ⇒ 判据没有对象", beats)
    assert all(beats[i]["skip"] for i in woke), [beats[i] for i in woke]
    # 二、它的下一拍必须是模型回合，且中间一拍都没睡（"不许再吃掉一拍"）。
    nxt = beats[woke[0] + 1]
    assert nxt["skip"] is False, (
        "woke 之后的那一拍又跳过了（这一拍就是被吃掉的那一拍）", beats)
    assert nxt["slices"] == beats[woke[0]]["slices"], ("woke 之后先睡了一拍才问模型", beats)
    # 三、那一拍真的读到了孩子的返场（不是空回合）：它就是 woke 之后的第一句提示词。
    assert nxt["calls"] == beats[woke[0]]["calls"], (beats[woke[0]], nxt)
    assert RETURN_MARK in prompts[nxt["calls"]], (
        "woke 之后那一句提示词里没有【子代理返场】", prompts[nxt["calls"]][-600:])
    # 四、返场账：给过回合的那一批被点名，而"欠的那一拍"已经清掉。
    assert run.park.get("return_given"), run.park
    assert not run.park.get("return_owed"), run.park


# ------------------------------------------------------------------ c. 只有自己设的闹钟

def test_an_alarm_of_my_own_is_still_a_park_and_earns_no_return_beat(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 c：只挂自己设的闹钟（`after_sec` + `clock.wait_any`，名下没有子）⇒ 照旧挂机。

    "我设的闹钟"与"我派的活"是两件事：闹钟没有 `wait_for`（`Timer.is_park` 为假），
    所以它根本不该被返场判据看见；这一条钉的就是"没被误判"。
    """
    state = _scenario(
        tmp_path, monkeypatch,
        replies=[_tool("clock.timer_start", after_sec=60.0, reason="再看一眼"),
                 _tool("clock.wait_any", purpose="等任意计时器返回"),
                 LOOK, LOOK, LOOK],
        stop_after=2)
    run = state["run"]

    assert run.stop_reason == "stop_file", run.to_dict()
    assert int(run.park.get("parked_turns") or 0) >= 2, run.park
    assert int(run.park.get("reentry_turns") or 0) == 0, (
        "只有自己设的闹钟，却返场了 —— 闹钟被误判成我派的活", run.park)
    assert not run.park.get("return_given"), run.park
    rows = _rows(state["st"], state["me"])
    assert rows == [], ("这一趟名下居然有子行 ⇒ 这一条测的不是「无子」那一档", rows)


# ------------------------------------------------------------------ d. 历史行不返场

def test_a_parked_wait_on_a_child_i_did_not_dispatch_this_run_still_parks(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 d：等的是一个历史子行（在跑，但不是这一趟派的）⇒ 照旧挂机、不返场。

    p206 那条语义不许丢：`wait_for=task:<子>` 只说明"我在等谁"，不说明"那是我派的"。
    改前 `tests/test_park_is_a_real_stop.py` 第 3 条就是这一档；这里把它与返场判据
    并排钉住 —— 谁把判据放宽成"看着像就返场"，这一条立刻红。
    """
    ws, st, backend, cond, me = _ws(tmp_path)
    child = _child(cond, me)
    watch = _SliceWatch()

    def on_slice(n: int) -> None:
        if n >= 2:
            stopctl.request_stop(ws, reason="判据：挂够了 2 拍")

    watch.on_slice = on_slice
    monkeypatch.setattr(AL.AgentLoop, "_park_slice", watch.stub())
    gate = _Gate([_tool("clock.timer_start", wait_for=f"task:{child}",
                        reason="等一条历史子行")])
    loop = _loop(st, ws, cond, gate, me)
    run = TSP._run(loop, me)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert int(run.park.get("parked_turns") or 0) >= 2, run.park
    assert int(run.park.get("reentry_turns") or 0) == 0, (
        "等一个不是这一趟派的子行，却返场了 ⇒ p206 的语义被放宽了", run.park)
    assert not run.park.get("return_given"), run.park
    # 那一位确实还在跑（这一条的前提由判据自己读出来，不靠我以为）。
    row = next(r for r in st.rows("tasks") if str(r.get("task_id")) == child)
    assert str(row.get("status")) == "running", row


# ------------------------------------------------------------------ e. 反真空

def test_without_the_return_verdict_criterion_a_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 e：把返场判据打桩成恒 False ⇒ 判据 a 必红。

    这一条是"a 真的在读那一处判据"的机器证明：没有它，"孩子结束之前有模型回合"
    可能只是被别的东西（别的形状、别的投递通道）满足的，那样的判据什么都没钉住。
    """
    seen = _dispatch_two(tmp_path, monkeypatch, stub_return=True)
    run = seen["state"]["run"]

    assert run.stop_reason == "final", run.to_dict()
    assert seen["field"] == [], (
        "把返场判据打桩成恒 False 之后，孩子结束之前居然还有模型回合 —— "
        "这说明那一拍不是返场判据给的", seen["turns"])
    assert int(run.park.get("reentry_turns") or 0) == 0, run.park
    # 循环真的走了挂机那一支（不是空转）：睡过，而且孩子是在那之后才回来的。
    assert seen["state"]["watch"].asked, "打桩之后一次都没挂上 ⇒ 这条反真空没有对象"
