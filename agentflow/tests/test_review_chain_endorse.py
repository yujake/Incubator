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
from agentflow import exhaustionreport as ER
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
                              # 举证的那一条是分配出来的号（当前宽度）——
                              # 这一行与 `_T3_ROW` 落库后拿到的号必须同一个。
                              "citations": [f"exp:{S.format_id(0)}"], "evidence_kind": "proof",
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


#: 这一条实验的号（`_T3_ROW` 落库后拿到的那个；`sync_counters` 从 0 起算）。
T3_EXPERIMENT_ID = S.format_id(0)


def _write_e_num_report(st: Store, *, experiment_id: str | None = None) -> str:
    """给这一条实验补一份 `e-num` 稿（族 `e-num`，无签，正常）。

    ## 为什么夹具必须补稿（改前缺的就是它）

    2026-11-11 业主裁定「按签拦收工」之后，E 的收工门有两条判据
    （`agent_loop._sign_gate_e`）：① `e-proof` 稿要有现行的 V 签；② 每一条没被撤销的
    实验都要有一份 E 稿（缺稿时门逐字写「这一条实验没有落任何 E 稿（`e-num` /
    `e-proof`）⇒ 普通数值实验也必须有稿」）。这一条用例原先只 `table.create` 了一条
    实验行、一份稿都没落 ⇒ 门按第 ② 条拒得对（`stop_reason="final_refused"`）。

    族为什么是 `e-num` 而不是 `e-proof`：`e-proof` 要 V 签（`manuscriptfamily.needs_sign`
    为真），而 `e-num` 这一族本来就不需要签（`needs_sign("e-num") == False`，业主
    2026-11-08）。补稿解决的是「有没有稿」，不是「签没签」—— 后者一个字没动。

    稿由框架自己的渲染口 `compose_numeric_manuscript` 拼（不手写正文），稿头
    `- 实验号：exp:000000` 正是 `find_manuscript_relpath(family="e-num")` 把稿钉回
    这条实验的唯一依据；所以"这份稿对得上那条 T3 实验"也是一条可核的读数。
    """
    eid = str(experiment_id or T3_EXPERIMENT_ID)
    rel = f"{ER.MANUSCRIPT_DIR}/e-num-{eid}.md"
    text = ER.compose_numeric_manuscript(
        experiment_id=eid, claim=_T3_ROW["claim"], claim_key=_T3_ROW["claim_key"],
        method=_T3_ROW["method"], params={}, observations={},
        result=_T3_ROW["result"], exit_code=_T3_ROW["exit_code"],
        evidence_kind=_T3_ROW["evidence_kind"])
    target = pathlib.Path(st.root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")
    return rel


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
        json.dumps({"final": "已给出 T3 背书", "evidence": ["exp:0000"], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    assert _gate(st) == "fail"
    # 这一条实验还欠一份 E 稿（2026-11-11 的按签收工门）；补上它才是"正常的一趟"
    report = _write_e_num_report(st)
    assert report == "reports/e-num-000000.md", report
    found = ER.find_manuscript_relpath(st.root, T3_EXPERIMENT_ID, family="e-num")
    assert found.get("found") is True and found.get("path") == report, found
    run = run_role("E", "给定理 1.5 的形式化做背书", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="E", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert run.stop_reason == "final", run.to_dict()
    assert run.final_refused_beats == 0, "有稿 ⇒ 收工门那一格一次都不该拒"
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    got = rows[0]
    assert got["method"] == "formal" and got["evidence_kind"] == "proof", got
    assert got["verifier_output"].strip(), got
    assert str(got["experiment_id"]) == S.format_id(0), got
    # 门真的被这一跳关上了（断言的是同一个工作区、同一个判据）
    assert _gate(st) == "pass", CL.check_closing(st, checks=("load_bearing",)).to_dict()


def test_finishing_without_an_e_report_is_refused(tmp_path):
    """反真空：同一条背书，没有 E 稿时收工被拒（普通数值实验也要有稿）。

    这条与上面那条正控只差一个 `reports/e-num-000000.md`，于是"门是不是真的在看稿"
    不再靠自觉：摘掉稿子，门必须当场红。它钉的是新收工门（2026-11-11 业主裁定
    「按签拦收工」）对 E 的第二条判据 —— 每一条没被撤销的实验都要有一份 E 稿
    （`e-num` / `e-proof`），普通数值实验也不能空着收工。
    """
    replies = [
        json.dumps({"tool": "table.create",
                    "args": {"table": "experiments", "row": dict(_T3_ROW)},
                    "why": "检查器原话在这里，作为 proof 级背书"}, ensure_ascii=False),
        json.dumps({"final": "已给出 T3 背书", "evidence": ["exp:0000"], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    assert _gate(st) == "fail"
    assert not list((pathlib.Path(st.root) / "reports").glob("e-*.md")), \
        "夹具前提：这一趟一份 E 稿都没有"
    run = run_role("E", "给定理 1.5 的形式化做背书", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="E", session_root=st.root, gateway=gw, price=(0.0, 0.0),
                                sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert run.stop_reason == "final_refused", run.to_dict()
    assert run.final == "", "被拒的收工不记 final"
    assert run.final_refused_beats >= 1, run.final_refused_beats
    assert any("没有落任何 E 稿" in n for n in run.notes), run.notes
    assert any(f"reports/e-num-{T3_EXPERIMENT_ID}.md" in n for n in run.notes), run.notes
    rows = st.rows("experiments")
    assert len(rows) == 1 and str(rows[0]["experiment_id"]) == T3_EXPERIMENT_ID, rows
    # 背书本身是成立的（`load_bearing` 已绿）—— 拦它的是"没有稿"，不是"没背书"
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
        json.dumps({"final": "写不进去就如实说", "evidence": [], "notify": {"to": "M", "summary": "收工：见 final", "body": "## 结论\n见 final。\n## 依据\n（见这一趟的步骤）\n"}}, ensure_ascii=False),
    ]
    st, cond, reg, gw = _world(tmp_path, replies)
    run_role("E", "给定理 1.5 的形式化做背书", store=st, registry=reg, conductor=cond,
             seam=LlmSeam(role="E", session_root=st.root, gateway=gw, price=(0.0, 0.0), sid="t"),
             workspace_root=str(st.root), sid="t", from_env=False, max_steps=4)
    assert st.rows("experiments") == [], "空口背书不许落库"
    assert _gate(st) == "fail", "一句空话不许把门变成绿的"
