# -*- coding: utf-8 -*-
"""M 不许在「研究还没做完」时挂机干等（真机 R-mk-infinite-93）。

## 现场（只读取证，`projects/R-mk-infinite-93`）

    tasks=10（M4 / D3 / E2 / A1）· statements 0 · documents 0 · experiments 10
    （其中 7 条 result ∈ supports/refutes）· research_questions 1 条 open
    板上未结项 0
    会话：M agent_children → M agent_mailbox → agent_park（每 20 分钟醒一次再 park）

D 已交出「手稿 000001：C1/C2/C3 成立」，但没有任何人把「立命题 → 派 F 落稿 →
派 V 签 → 派 B 收录」排进板子。根本原因是 `agent_loop._pending_work` 的三条判据
（新投递 / 未消板项 / 待消费子产出）只问"有没有人找我"，不问"盘上的研究做完了
没有"：板上未结项 0 ⇒ 它每一拍都读成"无事可做" ⇒ 挂机。

## 这一份钉的六件事（a–e；f 是"只挡 M"；lint 另算）

a. 现场形状复刻：statements=0 + 有结论的实验 + 开着的 research_question
   ⇒ M 这一拍 `decision="run"`（不 park），提示词里逐字带着读数与 `next_action`
   （"立命题并派 F 落稿"）。
b. 反真空：把「研究未尽」读数打桩成空 ⇒ 同一个现场又允许 park（且 a 的断言
   当场变红）。没有这一条，a 可以靠"什么情况下都不 park"骗过去。
c. 真·无事可做（有命题、有签、有收录、有稿）⇒ 允许 park（M 不是永动机）。
d. 同一读数连续挡到 `RESEARCH_STALL_LIMIT` ⇒ 报一次受控告警并放开（不许无限空转）。
e. 读数坏掉（`checked=False` / fingerprint 为空）也走同一条上限，不许变成
   "没查成 ⇒ 永远挡"的无限空转。
f. 只挡 M：同一个现场换成 D 那一趟 ⇒ 照旧 park（`_pending_work` 的三条口径
   一个字没改）。

判据本身只有一处实现（`agentflow.researchpending.pending_reading`）：`conductor.patrol`
的异常清单与挂机判据读的是同一份，本文件另有一条直接读它；`conductor.state` 给的是
同一批表的逐表读数（`tables.statements / documents / experiments`），不另写第二套口径。

边界：全部 tmp 工作区、假时钟、替身模型（`_Gate` 照剧本回答），零真实模型调用。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Sequence

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

from conftest import seed_statement_row, sign_for_the_gate

SID = "rmkpark"
TASK = "R(m,k)-example：把 D 交回的候选族排成命题与证明（真机形状）"


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


def _child(cond: Conductor, parent: str, role: str = "D") -> str:
    """造一行还在飞的子代理（挂机等待的对象；与真机现场同形）。"""
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "rmk@child",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "一个研究侧子代理",
        "error": None, "started_at": "2026-11-06T04:48:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


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


def _seed_field_shape(store: Store) -> None:
    """复刻真机现场的台账形状：10 条实验（7 条有结论）+ 1 条开着的题，0 命题 0 稿。"""
    for eid, result in (("000001", "refutes"), ("000004", "refutes"),
                        ("000005", "refutes"), ("000006", "refutes"),
                        ("000009", "refutes"), ("000007", "supports"),
                        ("000008", "supports")):
        _experiment(store, eid, result)
    for eid in ("000000", "000002", "000003"):
        _experiment(store, eid, "inconclusive")
    with store.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions", {
            "question_id": "000000",
            "question": "这种图在顶点数无限时存不存在？",
            "status": "open", "kind": "gap",
            "created_at": "2026-11-06T04:32:00+08:00",
        })


def _seed_finished_research(store: Store, ws: pathlib.Path) -> dict[str, Any]:
    """真·无事可做：一条有证明的命题、V 签住、稿子落行。"""
    row = seed_statement_row(
        store, proof_text="Proof. 每条边恰好落在两个不同的 k-圈上。",
        statement_full="定理：R(6,3) 的候选族 C1 满足每条边恰有 2 个 3-圈。",
        statement_text="C1 满足 R(6,3)", kind="theorem", label="Theorem 1")
    sign_for_the_gate(ws, statement_id=str(row["stmt_id"]),
                      proof_text=str(row["proof_text"]), store=store)
    doc = S.Document(
        doc_id="000000", kind="note", title="研究手稿 000001", status="draft",
        claims=[{
            "claim_id": "c1",
            "text": "C1 满足 R(6,3)：每条边恰有 2 个 3-圈。",
            "citations": [f"stmt:{row['stmt_id']}"],
            "evidence_kind": "proof_review",
            "disclaimer": "逐行审阅过的证明，未经机器检查",
        }])
    doc.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    return row


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate,
          me: str, *, role: str = "M") -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role=role, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=role, session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=12, workspace_root=str(ws))


def _park_once_then_stop(bench, ws: pathlib.Path):
    """挂机替身缝：真睡改成拨假时钟；第一拍就落停机开关（判据只要"它挂上了"）。"""
    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        bench.advance(seconds)
        _stop_now(ws, "判据：看够一拍挂机了")
        return {"checked": True, "asked_sec": seconds}

    return park_slice


def _assert_a_holds(run: Any, gate: _Gate) -> None:
    """a 的那组断言（b 用它证明"打桩成空之后 a 会红"）。"""
    assert str(run.park.get("decision") or "") == "run", run.park
    assert gate.prompts, "研究未尽却一拍都没问模型 ⇒ 挂机支没被挡住"
    prompt = gate.prompts[0]
    assert "【未尽研究" in prompt, prompt[-1200:]
    assert "立命题" in prompt, prompt[-1200:]
    assert "派 F" in prompt, prompt[-1200:]
    assert "statements=0" in prompt, prompt[-1200:]
    assert "experiments_conclusive=7" in prompt, prompt[-1200:]


# ------------------------------------------------------------------ a 现场形状

def test_field_shape_does_not_park_and_names_the_next_action(
        tmp_path: pathlib.Path, bench) -> None:
    """a：D 已交候选族、statements=0、板上未结项 0 ⇒ M 这一拍不许 park。

    改前红：同一现场 `run.park["decision"] == "park"`、`gate.prompts == []`
    （真机的 `agent_park` 每一拍都在）。
    """
    st, cond, ws = _ws(tmp_path, "field")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_field_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")

    def stop_after_first(index: int, prompt: str) -> None:
        if index == 0:
            _stop_now(ws, "判据 a：第一拍不许 park")

    gate = _Gate([_tool("clock.now")], on_call=stop_after_first)
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_a_holds(run, gate)
    # 判据本身（与 conductor.state / patrol / 挂机判据同一份实现）
    reading = RP.pending_reading(st)
    assert reading["checked"] is True, reading
    assert reading["pending"] is True, reading
    assert reading["gaps"][0]["code"] == "candidate_unfiled", reading
    assert reading["next_action"]["code"] == "candidate_unfiled", reading
    assert reading["next_action"]["target"] == "D", reading
    assert reading["counts"]["statements"] == 0, reading
    assert reading["counts"]["experiments_conclusive"] == 7, reading
    assert reading["counts"]["questions_open"] == 1, reading
    # 同一份判据的底座必须能从 M 的两处看盘面上读到：state 给逐表读数，
    # patrol 的异常清单给这一句（顶层键集被冻结快照钉着，所以异常清单是既有出口）。
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    state = reg.call("conductor.state", role="M")
    assert state.ok, state.error
    assert state.data["tables"]["statements"] == 0, state.data.get("tables")
    assert state.data["tables"]["documents"] == 0, state.data.get("tables")
    assert state.data["tables"]["experiments"] == 10, state.data.get("tables")
    patrol = reg.call("conductor.patrol", role="M")
    assert patrol.ok, patrol.error
    assert any("未尽研究" in str(x) for x in (patrol.data.get("anomalies") or ())), \
        patrol.data.get("anomalies")
    # 挂机读数那一格：这一拍读到了什么、挡没挡、排了什么动作
    assert run.park["research"]["pending"] is True, run.park
    assert run.park["research"]["next_action"]["code"] == "candidate_unfiled", run.park
    assert run.park["research_blocked"] is True, run.park
    # 盘上没有"这一拍挂了机"的事件（改前是每一拍都有一条）
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    parked = [e for e in events
              if e.get("kind") == AL.PARK_EVENT and str(e.get("decision")) == "park"]
    assert parked == [], parked


# ------------------------------------------------------------------ b 反真空

def test_the_research_reading_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把「研究未尽」读数打桩成空 ⇒ 同一个现场又允许 park，且 a 的断言当场变红。

    没有这一条，a 可以靠"任何情况下都不 park"骗过去（那会把 M 变成永动机）。
    """
    st, cond, ws = _ws(tmp_path, "vacuum")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_field_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")

    empty = {"checked": True, "pending": False, "gaps": [], "next_action": None,
             "counts": {}, "fingerprint": "", "reason": "打桩：没有未尽研究"}
    monkeypatch.setattr(AgentLoop, "_research_reading", lambda self_: dict(empty))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("打桩成空之后仍然问了模型 ⇒ 判据 a 读的不是这一格",
                                gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    assert run.park["research"]["pending"] is False, run.park
    with pytest.raises(AssertionError):
        _assert_a_holds(run, gate)


# ------------------------------------------------------------------ c 真·无事可做

def test_finished_research_still_parks(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：有命题、有签、有收录义务清零、有稿 ⇒ 允许 park（不许变成永动机）。

    改前/改后都该 park；这一条钉的是"新判据不会把已完成的研究永远挡住"。
    """
    st, cond, ws = _ws(tmp_path, "done")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_finished_research(st, ws)
    CLK.start_timer(ws, reason="等 D 收尾", wait_for=f"task:{child}",
                    task_id=me, role="M")
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    reading = RP.pending_reading(st)
    assert reading["checked"] is True, reading
    assert reading["pending"] is False, reading
    assert reading["counts"]["statements"] == 1, reading
    assert reading["counts"]["statements_unsigned"] == 0, reading
    assert reading["counts"]["documents"] == 1, reading
    assert gate.prompts == [], ("研究已收工却还问了模型 ⇒ 允许 park 的那一档被挡坏了",
                                gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    assert run.park["research"]["pending"] is False, run.park


# ------------------------------------------------------------------ e 不许无限空转

def test_the_same_reading_only_blocks_for_a_bounded_number_of_beats(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：同一读数连续挡到 `RESEARCH_STALL_LIMIT` ⇒ 报一次受控告警并放开挂机。

    这一条钉的是"不许无限空转"：模型连着不排动作、读数也不变时，强迫它每一拍都
    问一次模型就是把睡 20 分钟换成 0.5 秒一次烧钱。到上限之后：事件只落一条、
    `decision` 回到 `park`、轮查计时器照旧；读数一变（下一次有进展）会重新从 1 数起。
    """
    st, cond, ws = _ws(tmp_path, "stall")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_field_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])  # 每一拍都只读一次钟，读数不变
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    limit = int(AL.RESEARCH_STALL_LIMIT)
    assert limit >= 2, limit
    assert len(gate.prompts) == limit - 1, (
        f"挡了 {len(gate.prompts)} 拍（上限 {limit}）⇒ 没有按上限放开", gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    assert run.park["research_stalled"] is True, run.park
    assert int(run.park["research_streak"]) == limit, run.park
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    warned = [e for e in events if e.get("kind") == AL.RESEARCH_STALL_EVENT]
    assert len(warned) == 1, ("同一读数只许报一次受控告警", warned)
    assert warned[0]["streak"] == limit, warned[0]
    assert warned[0]["next_action"]["code"] == "candidate_unfiled", warned[0]
    parked = [e for e in events
              if e.get("kind") == AL.PARK_EVENT and str(e.get("decision")) == "park"]
    assert len(parked) == 1, parked


def test_an_unreadable_reading_is_bounded_too(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """读不成那一档也要有上限：fail-closed 挡，但连续挡到上限同样放开并告警。

    没有这一条，`checked=False`（fingerprint 为空）会让 streak 永远从 1 数起 ——
    "没查成 ⇒ 不许挂机"在读数坏掉时就变成真正的无限空转。
    """
    st, cond, ws = _ws(tmp_path, "unreadable")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_field_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    broken = {"checked": False, "pending": True, "gaps": [], "next_action": None,
              "counts": {}, "fingerprint": "", "reason": "打桩：读数坏了"}
    monkeypatch.setattr(AgentLoop, "_research_reading", lambda self_: dict(broken))
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    limit = int(AL.RESEARCH_STALL_LIMIT)
    assert len(gate.prompts) == limit - 1, gate.prompts
    assert str(run.park.get("decision") or "") == "park", run.park
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    warned = [e for e in events if e.get("kind") == AL.RESEARCH_STALL_EVENT]
    assert len(warned) == 1, warned
    assert warned[0]["fingerprint"] == "unreadable", warned[0]


# ------------------------------------------------------------------ f 只挡 M

def test_the_new_block_is_m_side_only(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：同一个现场换成 D 那一趟 ⇒ 照旧 park（`_pending_work` 三条口径一个字没改）。"""
    st, cond, ws = _ws(tmp_path, "dside")
    me = cond.open_top_level_run("D", TASK)
    child = _child(cond, me, role="E")
    _seed_field_shape(st)
    CLK.start_timer(ws, reason="等 E 交回穷举读数", wait_for=f"task:{child}",
                    task_id=me, role="D")
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me, role="D").run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("非 M 也被挡住了 ⇒ 这一档越界了", gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    assert run.park["research"]["pending"] is False, run.park
