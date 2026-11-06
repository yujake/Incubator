# -*- coding: utf-8 -*-
"""M 不许在「研究还没做完」时挂机干等（真机 R-mk-infinite-93）。

## 现场（只读取证，`projects/R-mk-infinite-93`）

    tasks=M6 / D4 / E2 / A1 / C0 · statements 0 · experiments 11
    （其中 supports/refutes 是有结论的）· research_questions 有开着的
    板上未结项 0
    三次轮查（04:57 / 05:22 / 05:49）每次都只排"再做一轮实验/穷举"，
    概念行一行都没长出来（而概念行只由 B 经 `Secretary.write_concept_row` 写，
    C 的动作面只产 `AnalysisReport`）⇒ 这条"未尽"永远消不掉。

## 这一份钉的九件事

两个分支各一条"现场形状 ⇒ 必须排出该动作"、各一条反真空；其余是"真·无事可做"
与两条不空转的边界。判据本身只有一处实现（`agentflow.researchpending.pending_reading`）：

a1. 分支甲（无概念面）：研究型项目里 concept 行 = 0（现场有实验/问题）
    ⇒ M 这一拍 `decision="run"`（不 park），提示词逐字带 `concepts=0` 与
    `next_action=concept_missing`（"派 B 登记概念行"，动作对象是 B 不是 C ——
    概念行只由 B 经 `Secretary.write_concept_row` 写，C 只做分析）。
a2. 分支乙（有核验结论未命题化）：已有 concept，`experiments` 里有 7 条有结论的、
    而非概念 `statements` = 0 ⇒ `next_action=candidate_unfiled`
    （"立命题并派 F 落稿"）。
b1. 反真空（甲）：把 `_gap_concept_missing` 打桩成空 ⇒ 同一现场又允许 park，
    且 a1 的断言当场变红。
b2. 反真空（乙）：把 `_gap_candidate_unfiled` 打桩成空 ⇒ 同一现场又允许 park，
    且 a2 的断言当场变红。
c. 真·无事可做（有 concept、有命题、有签、有收录义务清零、有稿）⇒ 允许 park。
d. 同一读数连续挡到 `RESEARCH_STALL_LIMIT` ⇒ 报一次受控告警并放开（不许无限空转）。
e. 读数坏掉（`checked=False` / fingerprint 为空）也走同一条上限。
f. 只挡 M：同一个现场换成 D 那一趟 ⇒ 照旧 park（`_pending_work` 三条口径一个字没改）。

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


def _add_concepts(store: Store, n: int = 1) -> list[dict]:
    """铺 concept 行（concept 面的正控）。"""
    rows: list[dict] = []
    for i in range(n):
        rows.append(seed_statement_row(
            store, kind="concept",
            statement_full=f"定义 {i}：R(m,k)-example 是 m-正则、围长恰为 k、"
                           "每条边至少落在两个不同的 k-圈上的连通简单图。",
            statement_text=f"R(m,k)-example 的定义 {i}"))
    return rows


def _seed_conclusive_experiments(store: Store) -> None:
    """真机现场的 10 条实验（7 条有结论、3 条 inconclusive）。"""
    for eid, result in (("000001", "refutes"), ("000004", "refutes"),
                        ("000005", "refutes"), ("000006", "refutes"),
                        ("000009", "refutes"), ("000007", "supports"),
                        ("000008", "supports")):
        _experiment(store, eid, result)
    for eid in ("000000", "000002", "000003"):
        _experiment(store, eid, "inconclusive")


def _seed_branch_a_shape(store: Store) -> None:
    """分支甲现场：研究型项目、0 个 concept、有实验与开着的题。

    与 R-mk-infinite-93 同形（C0 / statements 0 / experiments 有结论 / 题开着）。
    """
    _seed_conclusive_experiments(store)
    with store.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions", {
            "question_id": "000000",
            "question": "这种图在顶点数无限时存不存在？",
            "status": "open", "kind": "gap",
            "created_at": "2026-11-06T04:32:00+08:00",
        })


def _seed_branch_b_shape(store: Store) -> None:
    """分支乙现场：已有 concept 面，有结论的实验还没有任何命题在册。"""
    _add_concepts(store)
    _seed_conclusive_experiments(store)


def _seed_concept_only_gap(store: Store) -> None:
    """只缺概念面的研究型现场（一条 inconclusive 实验 ⇒ 研究型；没有别的 gap）。"""
    _experiment(store, "000000", "inconclusive")


def _seed_finished_research(store: Store, ws: pathlib.Path) -> dict[str, Any]:
    """真·无事可做：concept 一行、有证明的命题一行、V 签住、稿子落行。"""
    _add_concepts(store)
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


def _assert_branch_holds(run: Any, gate: _Gate, *, action: str,
                         needles: Sequence[str]) -> None:
    """一个分支的 a 组断言（b 用它证明"打桩成空之后 a 会红"）。"""
    assert str(run.park.get("decision") or "") == "run", run.park
    assert gate.prompts, "研究未尽却一拍都没问模型 ⇒ 挂机支没被挡住"
    prompt = gate.prompts[0]
    assert "【未尽研究" in prompt, prompt[-1500:]
    for needle in needles:
        assert needle in prompt, (needle, prompt[-1500:])
    assert (run.park.get("research", {}).get("next_action") or {}).get("code") == action, \
        run.park


# ------------------------------------------------------------------ a1 分支甲

def test_branch_a_no_concept_face_dispatches_b(
        tmp_path: pathlib.Path, bench) -> None:
    """a1：concept=0 的研究型现场 ⇒ M 不许 park，必须排"派 B 登记概念行"。"""
    st, cond, ws = _ws(tmp_path, "branch-a")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_branch_a_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")

    def stop_after_first(index: int, prompt: str) -> None:
        if index == 0:
            _stop_now(ws, "判据 a1：第一拍不许 park")

    gate = _Gate([_tool("clock.now")], on_call=stop_after_first)
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_branch_holds(run, gate, action="concept_missing",
                         needles=("concepts=0", "派 B", "登记概念行",
                                  "write_concept_row"))
    reading = RP.pending_reading(st)
    assert reading["checked"] is True, reading
    assert reading["pending"] is True, reading
    assert reading["counts"]["concepts"] == 0, reading
    assert reading["counts"]["research_shaped"] is True, reading
    assert reading["gaps"][0]["code"] == "concept_missing", reading
    why = str(reading["gaps"][0]["why"])
    assert "write_concept_row" in why and "B 登记" in why, why
    assert "派 C" not in str(reading["next_action"]["summary"]), reading["next_action"]
    assert "梳理概念" not in str(reading["next_action"]["summary"]), reading["next_action"]
    assert reading["next_action"] == {
        "code": "concept_missing", "target": "B",
        "summary": ("派 B 从已读文献/文档里登记概念行（概念行只由 B 经 "
                    "`Secretary.write_concept_row` 写，C 只做分析）")}, reading
    # 同一份底座能从 M 的两处看盘面读到：state 给逐表读数，patrol 异常清单给这一句。
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    state = reg.call("conductor.state", role="M")
    assert state.ok, state.error
    assert state.data["tables"]["statements"] == 0, state.data.get("tables")
    patrol = reg.call("conductor.patrol", role="M")
    assert patrol.ok, patrol.error
    assert any("concept_missing" in str(x) for x in (patrol.data.get("anomalies") or ())), \
        patrol.data.get("anomalies")
    # 巡查那一句与挂机那一段共用同一份 `next_action`：口径换了，这里也必须是"派 B"。
    assert any("派 B" in str(x) and "write_concept_row" in str(x)
               for x in (patrol.data.get("anomalies") or ())), \
        patrol.data.get("anomalies")
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    parked = [e for e in events
              if e.get("kind") == AL.PARK_EVENT and str(e.get("decision")) == "park"]
    assert parked == [], parked


# ------------------------------------------------------------------ a2 分支乙

def test_branch_b_verified_conclusions_are_propositionalized(
        tmp_path: pathlib.Path, bench) -> None:
    """a2：concept 面在、7 条有结论的实验、非概念命题 0 ⇒ 必须排"立命题并派 F"。"""
    st, cond, ws = _ws(tmp_path, "branch-b")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_branch_b_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")

    def stop_after_first(index: int, prompt: str) -> None:
        if index == 0:
            _stop_now(ws, "判据 a2：第一拍不许 park")

    gate = _Gate([_tool("clock.now")], on_call=stop_after_first)
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    _assert_branch_holds(run, gate, action="candidate_unfiled",
                         needles=("concepts=1", "statements=0",
                                  "experiments_conclusive=7", "立命题", "派 F"))
    reading = RP.pending_reading(st)
    assert reading["pending"] is True, reading
    assert reading["counts"]["concepts"] == 1, reading
    assert reading["counts"]["statements"] == 0, reading
    assert reading["counts"]["experiments_conclusive"] == 7, reading
    assert reading["gaps"][0]["code"] == "candidate_unfiled", reading
    assert reading["next_action"]["code"] == "candidate_unfiled", reading
    assert reading["next_action"]["target"] == "D", reading
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    parked = [e for e in events
              if e.get("kind") == AL.PARK_EVENT and str(e.get("decision")) == "park"]
    assert parked == [], parked


# ------------------------------------------------------------------ b1 反真空（甲）

def test_branch_a_criterion_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b1：把 concept 面那一条打桩成空 ⇒ 同一现场又允许 park，且 a1 的断言变红。"""
    st, cond, ws = _ws(tmp_path, "vacuum-a")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_concept_only_gap(st)
    CLK.start_timer(ws, reason="等 D", wait_for=f"task:{child}", task_id=me, role="M")
    assert [g["code"] for g in RP.pending_reading(st)["gaps"]] == ["concept_missing"]
    monkeypatch.setattr(RP, "_gap_concept_missing", lambda counts: None)
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("concept 面板打桩成空之后仍然问了模型", gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    with pytest.raises(AssertionError):
        _assert_branch_holds(run, gate, action="concept_missing", needles=("派 B",))


# ------------------------------------------------------------------ b2 反真空（乙）

def test_branch_b_criterion_is_load_bearing(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """b2：把"有结论未命题化"那一条打桩成空 ⇒ 同一现场又允许 park，a2 变红。"""
    st, cond, ws = _ws(tmp_path, "vacuum-b")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_branch_b_shape(st)
    CLK.start_timer(ws, reason="等 D 交回候选族", wait_for=f"task:{child}",
                    task_id=me, role="M")
    assert [g["code"] for g in RP.pending_reading(st)["gaps"]] == ["candidate_unfiled"]
    monkeypatch.setattr(RP, "_gap_candidate_unfiled",
                        lambda counts, conclusive: None)
    monkeypatch.setattr(AgentLoop, "_park_slice", _park_once_then_stop(bench, ws))
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(
        TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("候选族那一判据打桩成空之后仍然问了模型", gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park
    with pytest.raises(AssertionError):
        _assert_branch_holds(run, gate, action="candidate_unfiled",
                             needles=("立命题", "派 F"))


# ------------------------------------------------------------------ c 真·无事可做

def test_finished_research_still_parks(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：有 concept、有命题、有签、有收录、有稿 ⇒ 允许 park（不变成永动机）。"""
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
    assert reading["counts"]["concepts"] == 1, reading
    assert reading["counts"]["statements"] == 1, reading
    assert reading["counts"]["statements_unsigned"] == 0, reading
    assert reading["counts"]["documents"] == 1, reading
    assert gate.prompts == [], ("研究已收工却还问了模型 ⇒ 允许 park 的那一档被挡坏了",
                                gate.prompts)
    assert str(run.park.get("decision") or "") == "park", run.park


# ------------------------------------------------------------------ d 同一读数有上限

def test_the_same_reading_only_blocks_for_a_bounded_number_of_beats(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：同一读数连续挡到 `RESEARCH_STALL_LIMIT` ⇒ 报一次受控告警并放开挂机。"""
    st, cond, ws = _ws(tmp_path, "stall")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_branch_b_shape(st)
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


# ------------------------------------------------------------------ e 读不成也有上限

def test_an_unreadable_reading_is_bounded_too(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：fail-closed 挡，但连续挡到上限同样放开并告警（读坏不是无限挡）。"""
    st, cond, ws = _ws(tmp_path, "unreadable")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    _seed_branch_b_shape(st)
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
    """f：同一个现场换成 D 那一趟 ⇒ 照旧 park（`_pending_work` 三条口径一个字没改）。"""
    st, cond, ws = _ws(tmp_path, "dside")
    me = cond.open_top_level_run("D", TASK)
    child = _child(cond, me, role="E")
    _seed_branch_a_shape(st)
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
