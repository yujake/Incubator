# -*- coding: utf-8 -*-
"""R13 的最后一跳：E 的背书让收工门从"拦住"变成"放行"（离线，照剧本）。

## 为什么这一条比"再写一跳"值钱

R13 的整链要证明的是"这条线走得通"，而"走得通"最终要落到能不能交上 ——
收工门（§22）里最贵的那一条是 `load_bearing`：正文里 `evidence_kind="proof"` 的断言
必须有 T3 背书。所以这一组不满足于"E 写了一行实验"，而是断言：

1. 背书之前：门说 `load_bearing = fail`（承重结论缺 T3）；
2. 背书之后：同一份工作区，门说 `pass` —— 这一跳真的把门关上了；
3. 空口背书不算：E 想写一条 `evidence_kind="proof"` 而没有检查器原话 ⇒
   数据层当场拒（FC-22 的机械落地），门也不会因此变绿。

这三条合起来才是"E 的背书"这个动作的完整语义：它必须是一个能被验证器说的话撑住的产物。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict] = {("E", "run_experiment"): {}}

_T3_ROW: dict = {
    "claim": "Theorem 1.5 的形式化", "claim_key": "thm:1.5",
    "method": "formal", "evidence_kind": "proof", "result": "supports",
    "negation_kind": "not_proved", "code_path": "code/lean/thm.lean",
    "code_hash": "deadbeefdeadbeef", "exit_code": 0,
    "verifier_output": "'thm_1_5' does not depend on any axioms",
    "verifier_subject_key": "thm:1.5", "created_at": TS,
}


class _Scripted:
    """照剧本回答的替身模型。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        """记下这一问，回剧本里的下一条。"""
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _world(tmp_path: pathlib.Path, replies: list[str]):
    """一个"承重结论缺 T3"的工作区 + 一个能写 experiments 的 E 循环。"""
    st = Store(tmp_path / "ws")
    st.init()
    doc = S.Document(doc_id="0001", kind="paper", title="未发表的论文", status="in_review",
                     claims=[{"claim_id": "c1", "text": "已证明定理 1.5",
                              "citations": ["exp:0000"], "evidence_kind": "proof",
                              "section": "§2"}], created_at=TS)
    doc.validate()
    with st.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    sync_counters(st)
    gw = _Scripted(replies)
    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=gw, price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gw


def _gate(st: Store) -> str:
    """只跑承重那一条（其余四条与这一跳无关）。"""
    return CL.check_closing(st, checks=("load_bearing",)).status["load_bearing"]


def test_the_gate_blocks_before_e_endorses(tmp_path):
    """起手：正文里那条 proof 级断言没有 T3 背书 ⇒ 门拦。"""
    st, _cond, _reg, _gw = _world(tmp_path, [json.dumps({"final": "noop"})])
    assert _gate(st) == "fail", CL.check_closing(st, checks=("load_bearing",)).to_dict()


def test_e_endorsement_turns_the_gate_green(tmp_path):
    """这一跳的意义：E 写出那条 T3 实验之后，同一份工作区的门从 fail 变 pass。"""
    replies = [
        json.dumps({"tool": "table.create",
                    "args": {"table": "experiments", "row": dict(_T3_ROW)},
                    "why": "检查器原话在这里，作为 proof 级背书"}, ensure_ascii=False),
        json.dumps({"final": "已给出 T3 背书", "evidence": ["exp:0000"]}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    assert _gate(st) == "fail"
    run = run_role("E", "给定理 1.5 的形式化做背书", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="E", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert run.stop_reason == "final", run.to_dict()
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    got = rows[0]
    assert got["method"] == "formal" and got["evidence_kind"] == "proof", got
    assert got["verifier_output"].strip(), got
    assert str(got["experiment_id"]) == "0000", got
    # 门真的被这一跳关上了（断言的是同一个工作区、同一个判据）
    assert _gate(st) == "pass", CL.check_closing(st, checks=("load_bearing",)).to_dict()


def test_an_endorsement_without_the_checker_output_is_refused(tmp_path):
    """反真空：空口背书写不进去（`evidence_kind="proof"` 必须有检查器原话）。

    这一条挡的是"E 说它证明了"这类产物：数据层不让它落库，
    所以门也不可能因为一句空话变绿 —— 三态纪律在这里是结构性的，不靠自觉。
    """
    bad = dict(_T3_ROW)
    bad["verifier_output"] = ""
    replies = [
        json.dumps({"tool": "table.create",
                    "args": {"table": "experiments", "row": bad},
                    "why": "（故意不写检查器原话）"}, ensure_ascii=False),
        json.dumps({"final": "写不进去就如实说", "evidence": []}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run_role("E", "给定理 1.5 的形式化做背书", store=st, registry=reg, conductor=cond,
             seam=LlmSeam(role="E", session_root=st.root, gateway=gw, price=(0.0, 0.0), sid="t"),
             workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert st.rows("experiments") == [], "空口背书不许落库"
    assert _gate(st) == "fail", "一句空话不许把门变成绿的"
