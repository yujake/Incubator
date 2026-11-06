# -*- coding: utf-8 -*-
"""挂机判据的第⑥格：整棵树里有没有（除 M 以外的）人在干活（业主 2026-11-06）。

## 业主口径（逐字）

    「只要整个树有人干活，且 M 自己暂无可直接做完的板项，它就能挂机」

    补充（同一日，业主刚指出）：
    「查在飞时肯定要除掉自己，不然就是看见自己在干活就允许给自己挂机」

⇒ 允许 park ⇔ 「整棵树里有人正在干活」 且 「M 自己没有可直接做完的板项」；
只有"整棵树都闲着"（没有任何在飞 / 未结项 / 刚落定待处理）时，研究未尽才拦它。

## 这一份钉的十条（a–j）

a. 树里有人干活（任一子代理在飞）+ M 无板项 + gaps 非空 ⇒ 允许 park
   （`decision="park"`、`tree.busy=True`、`working` 点名那个子、`research_blocked=False`）。
a2. "有未结项"也算有人干活：没人"在飞"，但别的台账号名下还有未结项 ⇒ 同样允许 park。
b. 整棵树闲着 + M 无板项 + gaps 非空 ⇒ 不许 park（`decision="run"`、`next_action` 有 target）。
c. 整棵树闲着 + gaps 空 ⇒ 允许 park。
d. M 自己「有」可直接做完的板项 ⇒ 照旧先做（`pending_work=True`、不 park）—— 既有行为不许改。
e. 反真空（a）：把"整棵树有人干活"那一条打桩成恒 False ⇒ 同一现场又变成拦（a 红）。
e2. 反真空（b）：把 gaps 打桩成空 ⇒ 同一现场又允许 park（b 红）。
f. 读数坏掉（`tree.checked=False`）⇒ 归到固定键、仍受 `RESEARCH_STALL_LIMIT` 上限：
   挡满上限之后报一次受控告警并放开（不静默放行，也不无限催）。
h. 只有 M 自己在跑（读数里它自己那一行被拨成"在飞"，其它角色全 idle）+ 无板项 + gaps 非空
   ⇒ 判"树闲着" ⇒ 不许 park；读数里点名"被排除的是谁"与"剩下的在飞名单"。
i. 只有 M 自己在跑 + gaps 空 ⇒ 允许 park（正常收工；排除自己不许把正常挂机挡坏）。
j. 反真空（h）：把"除掉 M 自己"那一步摘掉 ⇒ 同一现场读成"有人干活" ⇒ 允许 park（h 红）。
k. 两格读数有类级默认 `None`（R5 引用判据按真符号计数）：第一拍之前读它们返回空串、不抛。

边界：全部 tmp 工作区、假时钟、替身模型（`_Gate` 照剧本回答），零真实模型调用。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Mapping, Sequence

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import researchpending as RP
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "rmktree"
TASK = "R(m,k)-example：整棵树有没有人在干活（挂机判据第⑥格）"


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


@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（挂机视图是进程级的，串了会污染别的判据）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    fake = CLK.use(CLK.FakeClock(wall="2026-11-06T05:20:00+08:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path, name: str) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / name
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, ws


def _agent_row(cond: Conductor, parent: str, role: str = "D",
               key: str = "tree@child") -> str:
    """造一行还在跑的子代理（台账行 `running`，三态里 = 在飞）。"""
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key,
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "一个研究侧子代理",
        "error": None, "started_at": "2026-11-06T04:48:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _idle_agent(cond: Conductor, parent: str, role: str = "D",
                key: str = "tree@idle") -> str:
    """造一行「已交差」的子代理：台账行仍 `running`，三态读成"静默"。

    为什么用"交差"而不是 `finish`：`agent_state` 第 ⑦' 步把"交差账上有它那一行"
    判成静默（业主 2026-10-27 第四条），而台账行仍是 `running` ⇒ 挂着等它的计时器
    不会当场以 `target_closed` 到点，第 ④ 支才可达。这正是"父已经把它记为静默、
    台账行还没落终态"那个真机形状。
    """
    tid = _agent_row(cond, parent, role, key)
    CLK.record_handoff(str(cond.store.root), task_id=tid, parent_task_id=parent,
                       role=role, reason="研究侧子代理已交回（夹具：记为静默）")
    return tid


def _experiment(store: Store, eid: str, result: str) -> None:
    """插一条合法的 experiments 行（`refutes` 必须带反例，schema 会拒）。"""
    row = S.Experiment(
        experiment_id=eid, claim=f"候选族结论 {eid}", claim_key=f"rmk-{eid}",
        method="numeric", evidence_kind="cross_check", result=result,
        negation_kind=("disproved" if result == "refutes" else "not_proved"),
        counterexample=({"witness": eid} if result == "refutes" else None),
        code_path="code/e_rmk.py", code_hash="99359506a9b1a35a",
        created_at="2026-11-06T04:48:10+08:00",
    )
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())


def _seed_gap(store: Store) -> None:
    """研究型现场 + 一个未尽项：一条 inconclusive 实验、concept 行 0。"""
    _experiment(store, "000000", "inconclusive")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate,
          me: str) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=12, workspace_root=str(ws))


def _park_once_then_stop(bench, ws: pathlib.Path):
    """挂机替身缝：真睡改成拨假时钟；第一拍就落停机开关（判据只要"它挂上了"）。"""
    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        bench.advance(seconds)
        _stop_now(ws, "判据：看够一拍挂机了")
        return {"checked": True, "asked_sec": seconds}

    return park_slice


def _stop_on_first_call(ws: pathlib.Path):
    def on_call(index: int, prompt: str) -> None:
        if index == 0:
            _stop_now(ws, "判据：第一拍必须问模型")
    return on_call


def _park_events(ws: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    return [e for e in events
            if e.get("kind") == AL.PARK_EVENT and str(e.get("decision")) == "park"]


# ------------------------------------------------------------------ a / b 共用的断言

def _assert_allowed_to_park(run: Any, gate: _Gate, ws: pathlib.Path, me: str, *,
                            working_has: str = "") -> None:
    """a/h 共用的"允许 park"断言（e/j 用它证明"打桩之后 a/h 红"）。"""
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], ("本来允许 park 却问了模型", gate.prompts)
    tree = dict(run.park.get("tree") or {})
    assert tree.get("busy") is True, tree
    if working_has:
        assert working_has in (tree.get("working") or ()), tree
    assert (tree.get("excluded") or {}).get("task_id") == me, tree
    assert _park_events(ws), "允许 park 却没有落下 agent_park 事件"


def _assert_blocked_from_park(run: Any, gate: _Gate, ws: pathlib.Path) -> None:
    """b/h 共用的"不许 park"断言。"""
    assert str(run.park.get("decision") or "") == "run", run.park
    assert gate.prompts, "研究未尽 + 整棵树闲着，却一拍都没问模型 ⇒ 拦没生效"
    assert "【未尽研究" in gate.prompts[0], gate.prompts[0][-1500:]
    tree = dict(run.park.get("tree") or {})
    assert tree.get("busy") is False, tree
    assert tree.get("working") == [], tree
    action = dict((run.park.get("research") or {}).get("next_action") or {})
    assert str(action.get("target") or ""), ("next_action 没有 target", action)
    assert _park_events(ws) == [], ("不许 park 的那个现场落了 park 事件", _park_events(ws))


# ------------------------------------------------------------------ a 有人干活 ⇒ 允许 park

def test_a_a_flying_subagent_lets_m_park_while_research_is_unfinished(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：D 在飞 + M 无板项 + gaps 非空 ⇒ 允许 park（研究未尽这一档不拦）。"""
    st, cond, ws = _ws(tmp_path, "tree-flying")
    me = cond.open_top_level_run("M", TASK)
    child = _agent_row(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    gate = _Gate([_tool("clock.now")])
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_allowed_to_park(run, gate, ws, me, working_has=child)
    assert run.park["tree_busy"] is True, run.park
    assert run.park["tree_checked"] is True, run.park
    assert run.park["research"]["pending"] is True, run.park
    assert run.park["research_blocked"] is False, run.park
    # 允许 park 的那一拍要把"为什么可以睡"写进 `agent_park` 事件的 reason。
    parked = _park_events(ws)
    assert parked and "整棵树有人正在干活" in str(parked[-1].get("reason") or ""), parked
    assert parked[-1].get("tree_busy") is True, parked[-1]
    assert child in (parked[-1].get("tree", {}).get("working") or ()), parked[-1]
    tree = run.park["tree"]
    print("a 读数：excluded =", tree["excluded"], "| working =", tree["working"],
          "| unfinished =", tree["unfinished"])


def test_a2_open_items_elsewhere_count_as_someone_working(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """a2：没人"在飞"，但别的台账号名下还有未结项 ⇒ 同样算"树里有人干活"。"""
    st, cond, ws = _ws(tmp_path, "tree-open-items")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    cond.open_item(kind="delegation", role="D", expects="work", action="run_once",
                   summary="还没做完的一件事", parent_task_id=child)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    gate = _Gate([_tool("clock.now")])
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    tree = dict(run.park.get("tree") or {})
    assert tree.get("busy") is True, tree
    assert tree.get("working") == [], tree
    assert child in (tree.get("unfinished") or ()), tree
    assert int(tree.get("unfinished_count") or 0) >= 1, tree
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], gate.prompts


# ------------------------------------------------------------------ b 树闲着 ⇒ 不许 park

def test_b_idle_tree_with_unfinished_research_must_not_park(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：整棵树闲着 + M 无板项 + gaps 非空 ⇒ 不许 park，必须排一个动作。"""
    st, cond, ws = _ws(tmp_path, "tree-idle")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_blocked_from_park(run, gate, ws)
    assert "整棵树：都闲着" in gate.prompts[0], gate.prompts[0][-1500:]
    assert (run.park.get("research", {}).get("next_action") or {}).get("target") == "B", \
        run.park
    tree = run.park["tree"]
    print("b 读数：excluded =", tree["excluded"], "| working =", tree["working"])


# ------------------------------------------------------------------ c 树闲着 + gaps 空

def test_c_idle_tree_with_finished_research_still_parks(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：整棵树闲着 + gaps 空 ⇒ 允许 park（正常收工）。"""
    st, cond, ws = _ws(tmp_path, "tree-done")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    CLK.start_timer(ws, reason="等 D 收尾", wait_for=f"task:{child}",
                    task_id=me, role="M")
    gate = _Gate([_tool("clock.now")])
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], gate.prompts
    assert run.park["tree"]["busy"] is False, run.park
    assert run.park["research"]["pending"] is False, run.park


# ------------------------------------------------------------------ d M 自己有板项

def test_d_m_side_board_item_is_still_done_first(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：M 自己有可直接做完的板项 ⇒ 照旧先做（不 park）——既有行为一个字不改。"""
    st, cond, ws = _ws(tmp_path, "m-busy")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    cond.open_item(kind="message", role="M", expects="ack", action="message",
                   summary="用户留言：这件事你来做", parent_task_id=me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert str(run.park.get("decision") or "") == "run", run.park
    assert gate.prompts, ("M 自己有板项却一拍都没问模型", gate.prompts)
    # 判据：树是闲的、研究未尽这一档没被调用（`research_blocked` 仍是 False）⇒
    # 这一拍之所以不 park 只可能来自 `_pending_work` 的第 2 条（M 自己名下的板项）。
    assert run.park["tree"]["busy"] is False, run.park
    assert run.park["research_blocked"] is False, run.park
    assert run.park["research"]["pending"] is True, run.park
    assert "用户留言：这件事你来做" in gate.prompts[0], gate.prompts[0][-1500:]


# ------------------------------------------------------------------ e 反真空（a / b）

def test_e_the_tree_busy_criterion_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把"整棵树有人干活"打桩成恒 False ⇒ 同一现场又变成拦（a 的断言当场变红）。"""
    st, cond, ws = _ws(tmp_path, "vacuum-busy")
    me = cond.open_top_level_run("M", TASK)
    child = _agent_row(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    empty_tree = {"checked": True, "busy": False, "working": [], "unfinished": [],
                  "unfinished_count": 0, "unknown": [],
                  "excluded": {"task_id": me, "role": "M", "state": ""},
                  "why_text": "打桩：整棵树没人干活", "reason": ""}
    monkeypatch.setattr(AgentLoop, "_tree_busy_reading", lambda self_: dict(empty_tree))
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert str(run.park.get("decision") or "") == "run", run.park
    assert gate.prompts, "打桩成'没人干活'之后仍然 park 了 ⇒ 打桩没接上判据"
    with pytest.raises(AssertionError):
        _assert_allowed_to_park(run, gate, ws, me, working_has=child)


def test_e2_the_gaps_criterion_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e2：把 gaps 打桩成空 ⇒ 同一现场（树闲着）又允许 park（b 的断言当场变红）。"""
    st, cond, ws = _ws(tmp_path, "vacuum-gaps")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    _seed_gap(st)
    assert RP.pending_reading(st)["pending"] is True
    empty = {"checked": True, "pending": False, "gaps": [], "next_action": None,
             "counts": {}, "fingerprint": "", "reason": ""}
    monkeypatch.setattr(AgentLoop, "_research_reading", lambda self_: dict(empty))
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    CLK.start_timer(ws, reason="等 D 收尾", wait_for=f"task:{child}",
                    task_id=me, role="M")
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], ("gaps 打桩成空之后仍然问了模型", gate.prompts)
    with pytest.raises(AssertionError):
        _assert_blocked_from_park(run, gate, ws)


# ------------------------------------------------------------------ f 读数坏掉也有上限

def test_f_unreadable_tree_reading_blocks_with_a_fixed_key_then_releases(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：整棵树读不成 ⇒ 归固定键、照样挡，但挡满上限就报一次告警并放开。"""
    st, cond, ws = _ws(tmp_path, "tree-unreadable")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    broken = {"checked": False, "busy": False, "working": [], "unfinished": [],
              "unfinished_count": 0, "unknown": [],
              "excluded": {"task_id": me, "role": "M", "state": ""},
              "why_text": "", "reason": "打桩：整棵树的活动读数没查成"}
    monkeypatch.setattr(AgentLoop, "_tree_busy_reading", lambda self_: dict(broken))
    gate = _Gate([_tool("clock.now")])
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    limit = int(AL.RESEARCH_STALL_LIMIT)
    assert len(gate.prompts) == limit - 1, (
        f"挡了 {len(gate.prompts)} 拍（上限 {limit}）⇒ 固定键/上限没接上", gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    assert run.park["tree_checked"] is False, run.park
    assert run.park["research_stalled"] is True, run.park
    assert int(run.park["research_streak"]) == limit, run.park
    assert "tree-unreadable" in str(run.park.get("research_fp") or ""), run.park
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    warned = [e for e in events if e.get("kind") == AL.RESEARCH_STALL_EVENT]
    assert len(warned) == 1, warned
    assert "tree-unreadable" in str(warned[0].get("fingerprint") or ""), warned[0]
    assert warned[0].get("tree_checked") is False, warned[0]
    assert len(_park_events(ws)) == 1, _park_events(ws)


# ------------------------------------------------------------------ h 只有 M 自己在跑

def _snapshot_with_m_flying(monkeypatch: pytest.MonkeyPatch, me: str) -> None:
    """把读数里 M 自己那一行拨成"在飞"（其它行照旧）——h/j 的"只有自己在跑"现场。

    真实拍点上 M 挂着钟时自己的三态常读成待机（⑥ 被"挂在时钟上"压住），所以
    "看见自己在干活"这个错误形态要靠这一针造出来；判据要证明的是：即使它
    那一行读成在飞，读数也不许把 M 算成"别人在干活"。
    """
    real = Conductor.activity_snapshot

    def _patched(self_: Conductor, *, retired: Mapping[str, bool] | None = None) -> Any:
        snap = dict(real(self_, retired=retired))
        by_task = {str(k): dict(v) for k, v in (snap.get("by_task") or {}).items()}
        cell = by_task.get(str(me))
        if cell is not None:
            cell["state"] = "flying"
            cell["state_label"] = "在飞"
            by_task[str(me)] = cell
        snap["by_task"] = by_task
        return snap

    monkeypatch.setattr(Conductor, "activity_snapshot", _patched)


def test_h_only_m_itself_running_is_an_idle_tree(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """h：只有 M 自己在跑（读数拨成在飞）+ 无板项 + gaps 非空 ⇒ 树闲着 ⇒ 不许 park。"""
    st, cond, ws = _ws(tmp_path, "only-m")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    _snapshot_with_m_flying(monkeypatch, me)
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_blocked_from_park(run, gate, ws)
    tree = dict(run.park.get("tree") or {})
    excluded = dict(tree.get("excluded") or {})
    print("h 读数：被排除的那条 =", excluded, "| 剩下的在飞名单 =", tree.get("working"))
    assert excluded.get("task_id") == me, tree
    assert excluded.get("role") == "M", tree
    assert excluded.get("state") == "flying", tree
    assert tree.get("working") == [], tree
    assert "整棵树：都闲着" in gate.prompts[0], gate.prompts[0][-1500:]


# ------------------------------------------------------------------ i 只有 M 自己在跑 + gaps 空

def test_i_only_m_itself_running_with_finished_research_parks(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """i：只有 M 自己在跑 + gaps 空 ⇒ 允许 park（排除自己不许把正常收工挡坏）。"""
    st, cond, ws = _ws(tmp_path, "only-m-done")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    CLK.start_timer(ws, reason="等 D 收尾", wait_for=f"task:{child}",
                    task_id=me, role="M")
    _snapshot_with_m_flying(monkeypatch, me)
    gate = _Gate([_tool("clock.now")])
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], gate.prompts
    assert run.park["tree"]["busy"] is False, run.park
    assert run.park["tree"]["excluded"]["state"] == "flying", run.park


# ------------------------------------------------------------------ k 类级默认读数

def test_k_the_caches_have_a_class_default_and_read_before_the_first_beat(
        tmp_path: pathlib.Path) -> None:
    """k：两格读数有类级默认 `None` —— 第一拍之前读它们不炸、也不编出读数。

    这一条钉的是读法的形状（2026-11-06 的 R5 引用判据）：`_tree_cache` / `_research_cache`
    只被赋值一次、又被提示词那一侧读，若读侧写成 `getattr(self, "…", None)`，名字就成了
    字符串字面量，`test_r5_orchestration_cost` 按真符号计数时会把它读成悬空引用。
    类级默认让读侧就是普通属性访问；本用例跑"属性还没赋值就读"的那条路径：
    读数与改前逐字相同（`_research_block` 返回空串，不抛）。
    """
    st, cond, ws = _ws(tmp_path, "cache-default")
    me = cond.open_top_level_run("M", TASK)
    loop = _loop(st, cond, ws, _Gate([_tool("clock.now")]), me)
    loop.my_task_id = me

    assert loop._research_cache is None
    assert loop._tree_cache is None
    assert loop._research_block() == ""


# ------------------------------------------------------------------ j 反真空（除掉自己）

def _working_without_excluding_me(self_: AgentLoop, by_task: Mapping[str, Any], *,
                                  me: str) -> list[str]:
    """j 的打桩：摘掉"除掉 M 自己"那一步（其它逐字照旧）。"""
    return sorted(str(tid) for tid, cell in by_task.items()
                  if str((cell or {}).get("state") or "") == "flying")


def test_j_without_excluding_m_itself_the_tree_looks_busy_and_m_sleeps(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """j：把"除掉 M 自己"那一步摘掉 ⇒ 同一现场读成"有人干活" ⇒ 允许 park（h 红）。"""
    st, cond, ws = _ws(tmp_path, "no-exclusion")
    me = cond.open_top_level_run("M", TASK)
    child = _idle_agent(cond, me)
    _seed_gap(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    _snapshot_with_m_flying(monkeypatch, me)
    monkeypatch.setattr(AgentLoop, "_agents_working", _working_without_excluding_me)
    gate = _Gate([_tool("clock.now")], on_call=_stop_on_first_call(ws))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    tree = dict(run.park.get("tree") or {})
    print("j 读数（摘掉排除之后）：working =", tree.get("working"),
          "| busy =", tree.get("busy"))
    assert tree.get("working") == [me], tree
    assert tree.get("busy") is True, tree
    assert str(run.park.get("decision") or "") == "park", run.park
    assert gate.prompts == [], gate.prompts
    with pytest.raises(AssertionError):
        _assert_blocked_from_park(run, gate, ws)
