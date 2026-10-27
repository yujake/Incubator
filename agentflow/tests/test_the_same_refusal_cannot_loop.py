# -*- coding: utf-8 -*-
"""Q17：同一拒因连续 N 次 ⇒ 收工（被闸拒的步也进活性记账）。

## 病（真机读数）

`final` 被 `children_running` 拒的那条路不会自己停：实测同一趟 215 次一模一样的收工被拒、
217 次模型调用、31 秒，`dead_loop_stopped=False`，最后靠孩子后端超时收场。
c473bff2 的探针把根因量出来了：那一支在拒绝之后 `continue`，而 `dead` 计数器的更新点
在"这一步执行之后"（`_call_key` / `_call_reading` 那一处）—— 于是同一拒因连着 215 次
一次也不计入，判停永不触发。收工门（`children_running`）与 D-68 那两道闸都在执行之前
出口，所以这不是"某一支漏了一行计数"，而是"被拒的步没有活性记账"。

## 改后的口径

一处判据、三个入口（`AgentLoop._refusal_beat`）：

1. 拒因键只看"谁在拒"（`_refusal_key`：受控拒因码 / 工具层 `meta.kind`），稳定；
2. "拒的时候局面是什么样"是另一格（`refusal_reading`：那一步结果的规范化 JSON）——
   键相同而读数变了（子数在减、在册数在变）⇒ 那是进展，连击从头数；
3. 两个都相同、连到 `max_dead_loop`（5，与既有判停同一处阈值，本单不新造数）⇒ 收工：
   `stop_reason` 仍是 `no_progress_limit`（停止理由是另一张表上的三件事，不在这里加档），
   拒因写在 `run.final` 的正文与读数里；
4. 第 `dead_loop_nudge`（3）次点名一次（与"原地打转"同一套两段式），提醒与判停分开报。

与 Q12 的关系：D-68 那道闸的补救拍已经有自己的上限（`max_final_refused`），
`_refusal_key` 把带 `final_refused` 的结果键成空串 ⇒ 那几拍不进本 streak（判据 e）。

## 判据（每条都写清改前红在哪）

| # | 判据 | 改前红 |
|---|---|---|
| a | 某闸恒拒（同一拒因、每一拍的调用都不同）⇒ 至多 5 次后自己收工，收尾语点名拒因键 | 改前没有这一路：被闸拒的步不进 `dead`，这一趟走到夹具的逃生口（坏 JSON）才停 |
| b | 读数：`refusal_key` / `refusal_reading` / `refusal_streak` / `refusal_max` 在停之前就写在 `LoopRun` 上，第 3 次点名、第 5 次停 | 改前这五格不存在（`LoopRun` 里没有"拒因"这一档） |
| c | 正控：拒因每次不同（两道闸交替）⇒ 不触发；同一拒因而读数每次不同（子数 3→2→1）⇒ 也不触发 | 改前这两条也是绿的（它们守的是别把正当推进判成死循环） |
| d | 反真空：把 `_refusal_beat` 打桩成不记账 ⇒ a 必红 | —— |
| e | 与 Q12 不互吞：D-68 连拒 ⇒ 收尾理由来自 Q12 那一档（`final_refused`）、`refusal_max==0`、不出现"215 次"那种形状 | 改前也不适用（没有这一档）；这一条守的是"两套上限别互相冒充" |
| f | 本案原形：`final` 被 `children_running` 连拒 ⇒ 第 5 拍停（改前无界） | 改前跑到夹具的逃生口：`refusal_stopped` 读不到，且 `final` 步数远超 5 |

## 两个夹具约定

- "跑很久"不用 `time.sleep`：孩子那一档由 `_FakeWave` 直接摆出"名下还有几个在跑"这个
  结构状态（生产里由 `_register_child_handle` 造同一笔挂账）。为什么不走真实派活：
  那条路一撞上挂机那一支（Q22 的返场只给一拍，之后按"无事可做"挂机），于是
  "final 被连拒"这件事在夹具里根本发生不了，测到的就不是本单的判据。
- 剧本用完回 `{}`（一个坏 JSON）：那是夹具的逃生口 —— 它让"改前 / 打桩后"那一趟能够
  终止并被判据抓住。真机上这一步是"孩子后端超时"，那在夹具里等于赌时间。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Mapping, Sequence

import pytest

import test_a_refused_final_gets_another_beat as Q12
import test_agent_loop as TAL
from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop, run_role
from agentflow.llmseam import LlmSeam

SID = "q17"

#: 判停阈值（与既有那一档同一个数：本单不新造数，判据直接读它）。
N = AL.AgentLoop.max_dead_loop

#: 点名那一档（提醒写进第 3 步的结果里）。
NUDGE = AL.AgentLoop.dead_loop_nudge

#: 两条"恒拒"的闸：一条是工具面的角色闸（`meta.kind=role_denied`），
#: 一条是工具面的取名闸（`meta.kind=unknown_tool`）。两条都不写盘（不存在的工具 /
#: 不存在的行号），所以它们可以反复撞而不会在夹具里留下副作用。
DENIED = {"tool": "table.update", "args": {"table": "tasks", "row_id": "nope", "values": {}}}
UNKNOWN = {"tool": "conductor.not_a_tool", "args": {}}

#: 孩子的编号（只当名字用：`_FakeWave` 不落台账，走的也不是真实派活）。
CHILD_IDS = ("t-q17-001", "t-q17-002", "t-q17-003")

FINAL = json.dumps({"final": "都回来了，收工", "evidence": []}, ensure_ascii=False)
TASK = "Q17 判据夹具"

#: 夹具的逃生口：剧本用完就回它（坏 JSON ⇒ bad_json_limit 收工）。
ESCAPE = {"text": "{}"}


def _reply(obj: Mapping[str, Any]) -> dict[str, str]:
    return {"text": json.dumps(dict(obj), ensure_ascii=False)}


def _runaway(i: int) -> dict[str, str]:
    """第 i 拍：同一个闸、不同的调用（参数变了）⇒ `dead` 那条路永远不触发。"""
    return _reply({"tool": "table.update",
                   "args": {"table": "tasks", "row_id": f"nope-{i}", "values": {}}})


class _Gate:
    """照剧本回答的替身模型（剧本用完回 `{}`，见模块头"两个夹具约定"）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, script: Sequence[dict[str, str]],
                 on_call: Callable[[int], None] | None = None) -> None:
        self.script = list(script)
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(index)
        item = self.script.pop(0) if self.script else dict(ESCAPE)
        return type("Reply", (), {"ok": True, "text": item.get("text", ""),
                                  "tool_calls": tuple(item.get("tool_calls", ())),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


class _FakeWave:
    """一批"还在跑"的孩子（与 `scheduler.WaveHandle` 同形的那几样读数）。

    本单只需要它能如实回答三件事：还在跑哪几个（`running`）、全落定了没有（`done`）、
    有没有新结果可取（`take_settled`）。`release(n)` 是判据侧的"放行 n 个"。
    """

    def __init__(self, ids: Sequence[str]) -> None:
        self.ids = list(ids)

    # ---- 循环读的那几样
    def dispatched(self) -> list[dict[str, Any]]:
        return [{"task_id": tid, "role": "C"} for tid in self.ids]

    def running(self) -> list[str]:
        return list(self.ids)

    def done(self) -> bool:
        return not self.ids

    def take_settled(self) -> list[Any]:
        return []

    def wait_any(self, timeout: float | None = None) -> bool:
        return False

    def wait(self, timeout: float | None = None) -> bool:
        return False

    # ---- 判据侧
    def release(self, n: int = 1) -> None:
        self.ids = self.ids[n:]


# ====================================================================== 夹具（单角色）
def _run_scripted(tmp_path: pathlib.Path, script: Sequence[dict[str, str]], *,
                  role: str = "M", max_steps: int = 40) -> tuple[Any, _Gate]:
    """以 `role` 的身份跑一趟（`tests/test_agent_loop.py` 的同一条接线）。"""
    st, cond, registry, _gw, root = TAL._wired(tmp_path, {role: ["{}"]},
                                              max_steps=max_steps)
    gate = _Gate(script)
    run = run_role(role, TASK, store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role=role, session_root=root, gateway=gate,
                                price=(0.0, 0.0), sid=SID),
                   workspace_root=str(root), sid=SID, from_env=False)
    return run, gate


def _loop_with_children(tmp_path: pathlib.Path, *, role: str,
                        script: Sequence[dict[str, str]], wave: _FakeWave,
                        on_call: Callable[[int], None] | None = None) -> tuple[Any, _Gate]:
    """以 `role` 的身份跑一趟，名下挂着一批"还在跑"的孩子。"""
    st, cond, registry, _gw, root = TAL._wired(tmp_path, {role: ["{}"]}, max_steps=40)
    gate = _Gate(script, on_call=on_call)
    loop = AgentLoop(role=role, session_root=root, registry=registry, conductor=cond,
                     seam=LlmSeam(role=role, session_root=root, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     workspace_root=str(root), sid=SID, store=st)
    # 这一笔挂账就是"我这一趟派出去、还没回来"（生产里由 `_register_child_handle` 造）。
    loop._child_handles.append({"kind": "summon_many", "handle": wave,
                                "calls": [], "step": -1, "wait": None, "taken": False})
    loop.child_return_wait_sec = 0.02
    loop.child_exit_drain_sec = 0.0
    return loop, gate


# ====================================================================== a / d 的判据本体
def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    """a 的判据本体：某闸恒拒（同一拒因、每拍调用不同）⇒ 至多 N 次后自己收工。

    抽成函数是为了让 d（反真空）复用同一套断言 —— 否则它会变成"另写一份更松的判据"。
    """
    run, gate = _run_scripted(tmp_path, [_runaway(i) for i in range(12)])
    problems: list[str] = []
    refused = [s for s in run.steps if s.shape == "tool"]
    table = run.to_dict()
    if run.stop_reason != "no_progress_limit":
        problems.append(
            f"同一拒因连着 {N} 次之后该自己收工（no_progress_limit），"
            f"实际 stop_reason={run.stop_reason!r}；模型调用 {len(gate.prompts)} 次、"
            f"步数 {len(run.steps)}")
    if len(refused) > N:
        problems.append(f"至多 {N} 次之后该停，实际被同一道闸拒了 {len(refused)} 次")
    if run.refusal_stopped is not True:
        problems.append(f"`refusal_stopped` 该是 True（是这一档停的），实际 "
                        f"{run.refusal_stopped!r}（stop_reason={table.get('stop_reason')!r}）")
    if int(run.refusal_streak) != N or int(run.refusal_max) != N:
        problems.append(f"连击读数该是 {N}/{N}，实际 streak={run.refusal_streak!r} "
                        f"max={run.refusal_max!r}")
    if "role_denied" not in str(run.refusal_key):
        problems.append(f"拒因键该点名那道闸（role_denied），实际 {run.refusal_key!r}")
    if not str(run.refusal_reading):
        problems.append("拒因读数（`refusal_reading`）是空的：那一步的局面没被记下来")
    # b：停之前就能读到（第 3 次点名），且点名里带"连着几次"与上限。
    named = [s for s in refused if str(s.result.get("框架提醒") or "")]
    if not named:
        problems.append(f"连着第 {NUDGE} 次该点名一次（框架提醒），一次都没有")
    else:
        first = str(named[0].result.get("框架提醒") or "")
        if "同一个拒因" not in first:
            problems.append(f"点名那一句没说是同一个拒因：{first[:160]}")
        if f"第 {NUDGE} 次" not in first or f"连续 {N} 次" not in first:
            problems.append(f"点名那一句没说清连着几次与上限：{first[:160]}")
        if named[0].index != NUDGE - 1:
            problems.append(f"点名该落在第 {NUDGE} 拍（步号 {NUDGE - 1}），实际步号 "
                            f"{named[0].index}")
    # 收尾那一段必须点名拒因（stop_reason 复用既有那一档，拒因在正文与读数里）。
    if "同一个拒因" not in str(run.final) or "role_denied" not in str(run.final):
        problems.append(f"收尾语没点名拒因：{str(run.final)[:200]}")
    if not any("同一拒因" in str(n) for n in run.notes):
        problems.append(f"收工那一行的 notes 没留痕：{list(run.notes)[-3:]}")
    # 两档不许互相冒充：这一趟不是"原地打转"停的。
    if run.dead_loop_stopped:
        problems.append("`dead_loop_stopped` 也成了 True：两档的收工读数混了")
    # 交付面（`to_dict()`）上只留"能复算是哪一档停的"那三格：拒因键 / 那一步的读数 /
    # 当前连击。最长连击与"是不是因它停的"两格 2026-10-26 起不进 `to_dict()`
    # （F1a 第 ② 条：它们除了测试以外 0 个读者），读数由上面那两条断言从 `LoopRun`
    # 的属性上读 —— 字段仍在、判据仍然承重，只是不再往交付面上抄一份没人读的数。
    for key in ("refusal_key", "refusal_reading", "refusal_streak"):
        if key not in table:
            problems.append(f"`to_dict()` 里没有读数格 {key}")
    for key in ("refusal_max", "refusal_stopped"):
        if key in table:
            problems.append(f"`to_dict()` 里又出现了没人读的 {key}"
                            "（接上读者再进交付面，见字段说明）")
    return problems


def test_a_gate_that_always_refuses_the_same_way_stops_the_run(
        tmp_path: pathlib.Path) -> None:
    """判据 a：某闸恒拒 ⇒ 至多 N 次后自己收工，且收尾语点名拒因（改前红：跑到逃生口）。"""
    problems = _a_problems(tmp_path)
    assert not problems, "；".join(problems)


def test_the_fixture_really_hits_a_refusal_gate(tmp_path: pathlib.Path) -> None:
    """夹具前提（判据的可判性）：这条路真的是一道闸在拒，而不是"执行出错"。

    没有这一条，a 会在"这个工具哪天变得可调用了"之后悄悄变成测别的东西 ——
    那时 `_refusal_key` 读到的不是拒因，a 就成了一条真空绿的判据。
    """
    run, _gate = _run_scripted(tmp_path, [_runaway(0), _reply({"final": "收工"})])
    first = run.steps[0]
    assert first.shape == "tool", first
    assert first.result.get("ok") is False, first.result
    assert AL._refusal_key(first.result) == "role_denied", first.result
    # 负控（同一条判据的另一半）：正常成功的一步不是拒因。
    ok_step = {"tool": "conductor.state", "ok": True, "data": {}, "meta": {"kind": "ok"}}
    assert AL._refusal_key(ok_step) == "", ok_step
    # 三态：Q12 那道闸（`final_refused`）刻意键成空串 —— 它有自己的上限，不进本 streak。
    assert AL._refusal_key({"final_refused": {"count": 3}, "why": "还有节点在册"}) == ""


# ====================================================================== b
def test_the_refusal_readings_are_visible_before_the_stop(tmp_path: pathlib.Path) -> None:
    """判据 b：那几格读数在停之前就写在 `LoopRun` 上，且三态（没被拒 = 0/空，不是缺键）。"""
    run, _gate = _run_scripted(tmp_path, [_runaway(i) for i in range(3)]
                               + [_reply({"final": "收工"})])
    assert run.stop_reason == "final", run.to_dict()
    # 三拍之后还没停：读数说"连着 3 次、最长 3 次、还没因它停"。
    assert (run.refusal_streak, run.refusal_max, run.refusal_stopped) == (3, 3, False), \
        (run.refusal_streak, run.refusal_max, run.refusal_stopped)
    assert "role_denied" in run.refusal_key, run.refusal_key
    assert run.refusal_reading, "读数格是空的"
    blob = run.to_dict()
    assert (blob["refusal_key"], blob["refusal_streak"]) == (run.refusal_key, 3), blob
    # 2026-10-26（F1a 第 ② 条）：`refusal_max` / `refusal_stopped` 不进 `to_dict()`
    # —— 全仓 0 个非测试读者。它们的读数从属性上读（上面那一条），交付面上则不许再
    # 出现（"看起来交出去了、其实只有测试在读"是这一条要挡的那类缺陷）。
    assert "refusal_max" not in blob and "refusal_stopped" not in blob, sorted(blob)
    # 干净的一趟：五格照样在（缺键会逼读的人去猜"是没拒过还是没记"）。
    clean = AL.LoopRun(role="M", task="t")
    assert (clean.refusal_key, clean.refusal_reading, clean.refusal_streak,
            clean.refusal_max, clean.refusal_stopped) == ("", "", 0, 0, False)


# ====================================================================== c
def test_different_refusal_causes_do_not_stop_the_run(tmp_path: pathlib.Path) -> None:
    """判据 c1（正控）：两道闸交替拒 ⇒ 拒因每次不同 ⇒ 不触发收工。"""
    script: list[dict[str, str]] = []
    for i in range(8):
        script.append(_reply(DENIED if i % 2 == 0 else UNKNOWN))
    script.append(_reply({"final": "收工"}))
    run, _gate = _run_scripted(tmp_path, script)

    assert run.stop_reason == "final", run.to_dict()
    assert int(run.refusal_max) == 1, run.to_dict()
    assert run.refusal_stopped is False, run.to_dict()
    keys = {AL._refusal_key(s.result) for s in run.steps if s.shape == "tool"}
    assert len(keys) == 2, keys


def test_a_changing_reading_is_progress_not_a_loop(tmp_path: pathlib.Path) -> None:
    """判据 c2（正控，最贵的那一条）：同一个闸、子数在减 ⇒ 那是进展，不许判停。

    第 1 拍 3 个在跑、第 2 拍 2 个、第 3 拍 1 个、第 4 拍回齐 —— 拒因码一模一样，
    读数每次都在变。判据如果只看拒因码，这一趟会在第 3 拍被判停（那条判据把
    "父代理正在等孩子回来"判成了死循环）。
    """
    wave = _FakeWave(CHILD_IDS)

    def on_call(index: int) -> None:
        if index >= 1:
            wave.release(1)

    loop, _gate = _loop_with_children(
        tmp_path, role="D", script=[{"text": FINAL}] * 6, wave=wave, on_call=on_call)
    # 阈值压到 3：孩子只有 3 个，而"只看拒因码"那一版正好会在第 3 拍停。
    loop.max_dead_loop = 3
    run = loop.run(TASK, summoned_by="user")

    assert run.stop_reason == "final", run.to_dict()
    refused = [s.result for s in run.steps if s.shape == "final"
               and str(s.result.get("refused") or "")]
    assert len(refused) == 3, [s.shape for s in run.steps]
    readings = {AL._call_reading(r) for r in refused}
    assert len(readings) == 3, "夹具前提：三条拒信的读数必须各不一样（子数 3→2→1）"
    assert int(run.refusal_max) == 1, (
        "同一个闸、读数每次都在变（子数在减）⇒ 连击必须每次都从头数", run.to_dict())
    assert run.refusal_stopped is False, run.to_dict()


# ====================================================================== d
def test_without_the_refusal_counter_the_gate_loop_never_stops(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d（反真空）：把"计入 streak"那一步打桩掉 ⇒ a 必红。

    没有这一条，a 有可能只是被别的东西满足的（比如坏 JSON 那一档恰好同拍触发），
    那样的判据什么都没钉住。
    """
    monkeypatch.setattr(AgentLoop, "_refusal_beat",
                        lambda self, run, result, *, step, brief: {})
    problems = _a_problems(tmp_path)
    assert problems, "把判据打桩掉之后 a 照样绿 ⇒ 它测的不是这一处"
    assert any("该自己收工" in p or "该停" in p for p in problems), problems


# ====================================================================== e
def test_q12_remedy_beats_do_not_enter_the_refusal_streak(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 e（不互吞）：D-68 连拒 ⇒ 收尾理由来自 Q12 那一档，streak 一格都不计。

    夹具与 `tests/test_a_refused_final_gets_another_beat.py` 同一份（同一个"树没销净"
    的 M、同一条接线）：这一条不是重复测补救拍对不对（那有它自己的判据），
    测的是"那几拍不进本 streak，两套上限不打架"。
    """
    env = Q12._workspace(tmp_path)
    owner = str(env["owner"])
    child = Q12._child(env["cond"], owner)
    Q12._roster(env, child)
    run, gate = Q12._run_m(env, monkeypatch, [Q12._final_reply()] * 8)

    finals = [s for s in run.steps if str(s.shape) == "final"]
    assert run.stop_reason == "final_refused", run.to_dict()
    assert len(finals) <= AL.AgentLoop.max_final_refused + 1, (
        f"补救拍该由 max_final_refused={AL.AgentLoop.max_final_refused} 收，"
        f"实际被拒了 {len(finals)} 拍")
    assert len(gate.prompts) <= AL.AgentLoop.max_final_refused + 2, len(gate.prompts)
    # 本 streak 一格都没记：D-68 那几拍不是一个"拒因"。
    assert int(run.refusal_max) == 0, run.to_dict()
    assert int(run.refusal_streak) == 0 and run.refusal_key == "", run.to_dict()
    assert run.refusal_stopped is False, run.to_dict()
    assert int(run.final_refused_beats) > 0, run.to_dict()


# ====================================================================== f
def _f_problems(tmp_path: pathlib.Path) -> list[str]:
    """f 的判据本体：`final` 被 `children_running` 连拒 ⇒ 第 N 拍自己停。

    抽成函数是为了让"把闸拒那一条入口打桩掉"的反真空复用同一套断言。
    """
    wave = _FakeWave(CHILD_IDS)
    loop, gate = _loop_with_children(tmp_path, role="M",
                                     script=[{"text": FINAL}] * 12, wave=wave)
    run = loop.run(TASK, summoned_by="user")

    problems: list[str] = []
    finals = [s for s in run.steps if s.shape == "final"]
    if run.stop_reason != "no_progress_limit":
        problems.append(
            f"收工被同一道闸连拒之后该自己停（no_progress_limit），实际 "
            f"stop_reason={run.stop_reason!r}；模型调用 {len(gate.prompts)} 次、"
            f"final 步 {len(finals)} 个")
    if run.refusal_stopped is not True:
        problems.append(f"`refusal_stopped` 该是 True，实际 {run.refusal_stopped!r}")
    if len(finals) > N:
        problems.append(f"至多 {N} 次收工被拒之后该停，实际 {len(finals)} 次")
    if len(gate.prompts) > N:
        problems.append(f"模型调用该至多 {N} 次，实际 {len(gate.prompts)} 次")
    if "children_running" not in str(run.refusal_key):
        problems.append(f"拒因键该是 children_running，实际 {run.refusal_key!r}")
    if int(run.refusal_streak) < N or int(run.refusal_max) < N:
        problems.append(f"连击读数该至少 {N}，实际 streak={run.refusal_streak!r} "
                        f"max={run.refusal_max!r}")
    # 被拒的那几步都落了盘（不许静默丢），且拒因同名。
    if not finals or any(str(s.result.get("refused") or "") != "children_running"
                         for s in finals):
        problems.append(f"被拒的 final 步没逐条落盘/没带拒因："
                        f"{[s.result.get('refused') for s in finals]}")
    if "同一个拒因" not in str(run.final) or "children_running" not in str(run.final):
        problems.append(f"收尾语没点名拒因：{str(run.final)[:200]}")
    # 两档不许互相冒充：不是"原地打转"停的。
    if run.dead_loop_stopped:
        problems.append("`dead_loop_stopped` 也成了 True：两档的收工读数混了")
    return problems


def test_a_refused_final_against_running_children_stops_by_itself(
        tmp_path: pathlib.Path) -> None:
    """判据 f（本案原形）：`final` 被 `children_running` 连拒 ⇒ 第 N 拍自己停。

    真机形态（c473bff2）：215 次一模一样的收工被拒、217 次模型调用、31 秒，
    `dead_loop_stopped=False`，最后靠孩子后端超时收场 —— 这条路改前是无界的。
    """
    problems = _f_problems(tmp_path)
    assert not problems, "；".join(problems)


def test_without_the_refusal_call_in_the_gate_branch_the_run_runs_away(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（f 那一支）：把"闸拒"这条入口的打桩掉 ⇒ f 必红。

    为什么这一条与 d 分开：d 打桩的是判据本体（两条入口一起没了），而这一条只让
    `children_running` 那一支不记账 —— 它证明"闸拒的那一条调用点"自己是承重的，
    不是靠正常步那条入口顺带满足的。
    """
    real = AgentLoop._refusal_beat

    def gate_blind(self: Any, run: Any, result: Any, *, step: int, brief: str,
                   _real: Any = real) -> dict[str, Any]:
        if isinstance(result, Mapping) and str(result.get("refused") or "") == "children_running":
            return {}
        return _real(self, run, result, step=step, brief=brief)

    monkeypatch.setattr(AgentLoop, "_refusal_beat", gate_blind)
    problems = _f_problems(tmp_path)
    assert problems, "把闸拒那一条入口打桩掉之后 f 照样绿 ⇒ 它测的不是那一处"
    assert any("该自己停" in p or "该停" in p or "模型调用该至多" in p for p in problems), problems
