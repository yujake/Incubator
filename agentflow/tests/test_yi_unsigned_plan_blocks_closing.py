# -*- coding: utf-8 -*-
"""乙（2026-11-11 业主裁定）：收工门按签拦 —— 未签未放弃才拦，签只是「可 finish」。

## 业主原话（逐字）

「是否有一旦手稿拿签就立即收工？是错误的，应该是拦收工前有计划号未产出 V 签稿
  且未放弃。如果一个计划号有 V 签稿，则被定义为可 finish 的。对于 E 和 B 同样只拦
  无签收工，不强制落签就收工。其中 E 侧对普通数值实验是拦无稿就收工，普通数值实验
  无签正常」

旧口径（「送审后必须起 `wait_for=V` 的计时器」）按同一条裁定重写：计时器是送审之后
的手段，不是收工门的判据。这一组只钉台账上的痕迹 —— 计划号有没有现行的 V 签稿、
有没有被明确放弃、E 的普通数值实验有没有稿。

| # | 造什么 | 期望 |
|---|---|---|
| a | 计划号下有稿、稿没有现行的签、计划没放弃 | 收工受控拒：点名计划号与那份稿 + 两条正路 |
| a2 | 同一个计划号，稿有现行的签 | 放行（`complete=True`）；且收工仍由模型决定（不签了就替它收工） |
| a3 | 计划号被明确放弃（终态 `abandoned`） | 放行；读数里 `abandoned=true` |
| a4 | E：`e-num` 有稿无签 ⇒ 放行；另一条实验没有稿 ⇒ 拒 | 两半都按业主的 e-num 口径 |
| a5 | 反真空：摘掉闸 ⇒ a 红；把「签即放行」翻成「签也要拦」⇒ a2 红 | 两条各打在自己那一半上 |

「签算不算签」只有一条口径：`manuscriptclosing.signed_candidates` 的
`state=="signed"`（签 sha == 现行正文 sha、签文件可复算）—— 夹具用真签（三行 pending
台账 + `vsigns.issue`），不写假签块。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import exhaustionreport as ER
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

TS = "2026-11-11T21:00:00+08:00"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
BODY = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
        "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")


# ---------------------------------------------------------------- 夹具
def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _plan(st: Store, *, plan_id: str = "000000", status: str = "attacking",
          manuscript_ids: tuple[str, ...] = ()) -> None:
    """一条形状合法的攻坚计划；`history` 里记它产出的稿号（现有痕迹）。"""
    history = [{"round": i + 1, "sid": "g1", "action": "proof", "outcome": "progress",
                "manuscript_id": mid, "detail": "夹具：这一轮落了稿", "evidence": [],
                "at": TS} for i, mid in enumerate(manuscript_ids)]
    with st.tx("attack_plans", actor="fixture") as tx:
        tx.upsert("attack_plans", {
            "plan_id": plan_id, "problem": "证明一致连续", "problem_key": f"key-{plan_id}",
            "status": status,
            "budget": {"max_rounds": 6, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [{"sid": "g1", "text": "证明一致连续", "owner": "F",
                          "status": "in_progress", "evidence_ids": [],
                          "experiment_ids": [], "proof_experiment_ids": [],
                          "blocked_reason": "", "attempts": 1, "negation_kind": None}],
            "history": history, "created_at": TS, "created_by": "fixture",
        })


def _manuscript(st: Store, mid: str, *, family: str = "f-proof",
                plan_id: str = "000000", statement_id: str = "") -> str:
    """一份真形状的稿（三节 + 稿头）。字体面与真写口同一个形状，签才盖得住。"""
    rel = f"reports/{family}-{mid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ["# 手稿（夹具）", ""]
    if family == "f-proof":
        head.append(f"- 计划：{plan_id} · 子目标：g1")
    head.append("- 依赖面洗稿：已洗=true；执行者=fixture")
    head += ["", "## 命题", "", FULL, "", "## 证明", "", BODY, "",
             DS.render_dependency_section([])]
    path.write_text("\n".join(head), encoding="utf-8")
    return rel


def _sign(st: Store, rel: str) -> dict:
    """走 V 那条真路（三行 pending 台账 + `vsigns.issue(store=...)`）。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    rows = [VR.record_pending_sign(
        st.root, proof_text=BODY, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _ in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    return VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                    artifact_path=rel,
                    ledger=f"verifications/pending/{key}.jsonl"
                           f"#{rows[-1]['verification_id']}",
                    statement_id="", passes=passes, by="secretary:F", store=st)


def _experiment(st: Store, eid: str) -> None:
    with st.tx("experiments", actor="fixture") as tx:
        tx.upsert("experiments", {
            "experiment_id": eid, "claim": "n≤18 的穷举没有反例", "claim_key": f"K-{eid}",
            "script_path": "code/x.py", "method": "numeric", "params": {},
            "exit_code": 0, "result": "supports", "evidence_kind": "cross_check",
            "negation_kind": "not_proved",
            "observations": {"n": 18}, "status": "active",
            "created_at": TS, "created_by": "fixture",
        })


class _Run:
    def __init__(self) -> None:
        self.notes: list[str] = []


class _Shell:
    """把 `AgentLoop._final_gate_reading` 挂到一个只有四格属性的壳上。"""

    max_final_refused = 3
    conductor = None

    def __init__(self, st: Store, role: str) -> None:
        self.role = role
        self.my_task_id = "t-000001"
        self.store = st
        self.workspace_root = str(st.root)

    def reading(self, run: _Run | None = None) -> dict:
        return AL.AgentLoop._final_gate_reading(self, run)

    def _v_wait_gate_reading(self) -> dict:
        return AL.AgentLoop._v_wait_gate_reading(self)


def _refused(reading: dict) -> bool:
    return bool(reading.get("applicable")) and not bool(reading.get("complete"))


# ============================================================ a：无签且未放弃 ⇒ 拒
def test_a_a_plan_without_a_signed_manuscript_is_refused(tmp_path):
    st = _ws(tmp_path)
    _plan(st, manuscript_ids=("000000",))
    rel = _manuscript(st, "000000")
    reading = _Shell(st, "F").reading(_Run())
    assert _refused(reading), reading
    why = str(reading.get("why") or "")
    # 拒信点名：哪个计划号、缺哪一份稿、两条正路
    assert "000000" in why, why
    assert "f-proof-000000" in why, why
    assert "放弃" in why and ("等 V" in why or "再送" in why), why
    assert reading["plans"][0]["plan_id"] == "000000", reading["plans"]
    assert reading["plans"][0]["signed_manuscripts"] == [], reading["plans"]
    assert rel in reading["manuscripts"][0]["manuscript"], reading["manuscripts"]


# ============================================================ a2：有签 ⇒ 放行，但不替它收工
def test_a2_a_signed_plan_is_finishable_and_closing_stays_the_models_choice(tmp_path):
    st = _ws(tmp_path)
    _plan(st, manuscript_ids=("000000",))
    rel = _manuscript(st, "000000")
    got = _sign(st, rel)
    assert got.get("written") is True, got
    reading = _Shell(st, "F").reading(_Run())
    assert not _refused(reading), reading
    assert reading["complete"] is True, reading
    assert reading["plans"][0]["signed_manuscripts"] == ["000000"], reading["plans"]
    assert reading["manuscripts"][0]["state"] == "signed", reading["manuscripts"]

    # 不因为「刚签」就把这一轮提前结束：真循环里模型不发 final，这一趟就不以 final 结束。
    from test_review_chain_loop import _Scripted, _world

    body = pathlib.Path(st.root) / rel
    loop_st, cond, reg, gw, backend = _world(tmp_path / "loop")
    loop_rel = _manuscript(loop_st, "000000", family="b-proof")
    assert _sign(loop_st, loop_rel).get("written") is True
    backend.seam_factory = lambda role: LlmSeam(
        role=role, session_root=loop_st.root, price=(0.0, 0.0), sid="t",
        gateway=_Scripted([json.dumps({"tool": "table.count",
                                       "args": {"table": "tasks"},
                                       "why": "夹具：还在干活"}, ensure_ascii=False)]))
    out = backend.call("B", "", {"task": "继续干活"}, token=None, task_id="")
    assert out["stop_reason"] != "final", out
    assert body.is_file()


# ============================================================ a3：显式放弃 ⇒ 放行
def test_a3_an_abandoned_plan_is_settled_and_the_reading_shows_it(tmp_path):
    st = _ws(tmp_path)
    _plan(st, status="abandoned", manuscript_ids=("000000",))
    _manuscript(st, "000000")
    reading = _Shell(st, "F").reading(_Run())
    assert not _refused(reading), reading
    assert reading["plans"][0]["abandoned"] is True, reading["plans"]
    gate = _Shell(st, "F")._v_wait_gate_reading()
    assert gate.get("complete") is True, gate
    assert "放弃" in str(gate.get("reason") or ""), gate.get("reason")


# ============================================================ a4：E 的 e-num 口径
def test_a4_e_numeric_is_settled_without_a_sign_but_missing_is_refused(tmp_path):
    st = _ws(tmp_path)
    _experiment(st, "000001")       # 有稿、没有签（普通数值实验：正常）
    _experiment(st, "000002")       # 没有稿（要拦）
    landed = ER.land_numeric_manuscript(
        st.root, experiment_id="000001", claim="n≤18 的穷举没有反例",
        claim_key="K-000001", method="numeric", result="supports",
        evidence_kind="cross_check")
    assert landed.get("ok") is True, landed
    reading = _Shell(st, "E").reading(_Run())
    assert _refused(reading), reading
    asked = "；".join(str(p.get("where") or "") for p in reading["problems"])
    assert "000002" in asked, reading["problems"]
    assert "000001" not in asked, reading["problems"]
    # 有稿无签那一半是放行的：它不在 problems 里，且 e-num 候选的 state 不是「已签」
    assert any(m["manuscript_id"] == landed.get("manuscript_id")
               and not m["signed"] for m in reading["manuscripts"]), reading["manuscripts"]
    # 补上稿之后同一把尺放行
    ER.land_numeric_manuscript(
        st.root, experiment_id="000002", claim="另一条数值实验", claim_key="K-000002",
        method="numeric", result="supports", evidence_kind="cross_check")
    ok = _Shell(st, "E").reading(_Run())
    assert not _refused(ok), ok


# ============================================================ a5：反真空
def test_a5_the_gate_is_what_makes_a_red_and_the_signed_branch_is_what_makes_a2_green(
        tmp_path, monkeypatch):
    st = _ws(tmp_path)
    _plan(st, manuscript_ids=("000000",))
    rel = _manuscript(st, "000000")

    # (1) 摘掉闸 ⇒ a 的那份读数变绿（a 的断言此时是红的）
    monkeypatch.setattr(AL.AgentLoop, "_v_wait_gate_reading",
                        lambda self: {"applicable": False, "checked": True,
                                      "complete": True, "why": "", "reason": "摘掉"})
    removed = _Shell(st, "F").reading(_Run())
    assert not _refused(removed), removed
    monkeypatch.undo()

    # (2) 把「签即放行」翻成「签也要拦」⇒ a2 的放行断言变红
    _sign(st, rel)
    signed = _Shell(st, "F").reading(_Run())
    assert not _refused(signed), signed
    monkeypatch.setattr(
        AL.AgentLoop, "_v_wait_gate_reading",
        lambda self: {"applicable": True, "checked": True, "complete": False,
                      "plans": [], "manuscripts": [],
                      "problems": [{"where": "计划 000000", "what": "签了也要等"}],
                      "why": "反真空：把「签即放行」翻成「签也要拦」",
                      "reason": "反真空"})
    inverted = _Shell(st, "F").reading(_Run())
    assert _refused(inverted), inverted
