# -*- coding: utf-8 -*-
"""长跑预演（阶段 3）：离线多轮多角色跑一遍 —— 断言"零阻塞 ＋ 链闭合"。

业主口径（2026-10-17）：*"用离线真实模拟（多轮、多角色、桩 provider/桩模型）跑通一遍，
把会在哪停逐条找出来并修掉，再配判据守住。"*

这一条模拟的是最坏组合：零文献（台账空）＋ 源全挂（每次检索都抛）。
它断言两件事：

1. 零阻塞：A→B→D→F→E→V→G→H 每一格都返回读数（不抛异常）；"没查成"必须是读得出的三态，
   而不是把流程打断；
2. 链闭合：F 路线上的 `own_result` 自证命题，经 V 审核（注入假判定，稳定返"成立"）之后
   ⇒ 它是证明链的根（`proof_chain.closed=True`、`roots=[sid]`）。
"""

from __future__ import annotations

import json
import pathlib

from agentflow.agent_a import AgentA
from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.agent_d import AgentD
from agentflow.agent_e import AgentE
from agentflow.agent_f import AgentF
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.agent_v import AgentV
from agentflow.store import Store

PROOF = "Proof. n^2+n=n(n+1)，相邻两数必有一偶。"
BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
SUBGOALS = [{"sid": "s1", "text": "把命题约化到 n=3", "status": "todo", "owner": "E"},
            {"sid": "s2", "text": "在 n=3 上构造证明", "status": "todo", "owner": "E"}]


class _DeadProvider:
    """全挂的源（模拟"文献下载不下来"那一类）。"""

    name = "dead"

    def search(self, topic, mode, description="", limit=10):
        raise TimeoutError("模拟：上游超时")


class _FixedSeam:
    """桩模型：每次 `complete` 都回同一段 JSON —— 审核判定可复现。"""

    def __init__(self, verdict: str = "成立") -> None:
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str, **_kw) -> str:
        self.calls += 1
        payload = {"verdict": self.verdict, "findings": [], "proof_sha256": "0" * 64}
        if self.verdict != "成立":
            payload["defect_step"] = 1
        return json.dumps(payload, ensure_ascii=False)


def _as_dict(out) -> dict:
    if isinstance(out, dict):
        return out
    for attr in ("to_dict",):
        fn = getattr(out, attr, None)
        if callable(fn):
            return dict(fn())
    return {"raw": out}


def test_the_whole_pipeline_runs_without_literature_and_the_chain_closes(tmp_path):
    """最坏组合（零文献 ＋ 源全挂）下：每一步都返回读数，且证明链闭合。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    steps: list[str] = []

    # ① A：源全挂 ⇒ 上游异常必须被吸收成读数（不是抛出）
    a = AgentA(st, providers=[_DeadProvider()])
    got = _as_dict(a.search_literature(topic="modularity lifting", mode="topical"))
    steps.append("A.search_literature")
    assert got.get("ok") is True, f"A 的检索把上游异常抛出来了：{got}"
    assert len(st.rows("literature")) == 0          # 零文献：如实的空

    # ② B：没有正文可消化 ⇒ 返回读数、不抛
    b = AgentB(st, extractor=None, extract_text=None)
    _as_dict(b.run_once())
    steps.append("B.run_once")

    # ③ D：一句话立成研究问题
    d = AgentD(st)
    q = _as_dict(d.propose_question(question="模形式与费马大定理的关系是什么？",
                                    kind="gap", gap_reason="零文献起步", priority="medium"))
    assert len(st.rows("research_questions")) == 1, q
    steps.append("D.propose_question")

    # ④ F：立项 ＋ 连推到上限（必须有界，不许空转）
    f = AgentF(st)
    f.create_plan(problem="探针：缺文献下的独立攻坚", problem_key="probe:no-lit",
                  budget=BUDGET, subgoals=SUBGOALS)
    pid = str(st.rows("attack_plans")[0].get("plan_id"))
    for _ in range(int(BUDGET["max_rounds"]) + 1):
        _as_dict(f.step(pid))
    status = next((str(r.get("status")) for r in st.rows("attack_plans")
                   if str(r.get("plan_id")) == pid), "")
    assert status == "stalled", f"F 没有收束（status={status}）—— 长跑会空转"
    steps.append("F.create_plan/F.step")

    # ⑤ E：跑一个实验（离线脚本）
    script = ws / "scripts" / "probe.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print(2)\n", encoding="utf-8")
    e = AgentE(st)
    _as_dict(e.run_experiment(claim="1+1=2", claim_key="probe:arith",
                              script_path="scripts/probe.py", method="numeric"))
    steps.append("E.run_experiment")

    # ⑥ B 登记一条自证命题（零文献依赖）＋ V 审核（桩模型稳定判"成立"）
    #    2026-10-22（业主裁定 B-2「没有引文 / 自己编的命题必须从『猜想』注册」）：入口档
    #    写成 conjecture；"它是不是定理"由 V 签完之后 `evidencebits.derive_grade` 现算。
    req = dict(origin="own_result", statement_full="若 n≥3 则 n^2+n 是偶数（自证）。",
               kind="conjecture", proof_text=PROOF, line_range={"start": 1},
               doc_id="000000", quote_verified=False, quote_reason="自证：无外部引文")
    row = _as_dict(b.register_statement(**req))
    assert row.get("ok"), row
    sid = str(row.get("stmt_id") or "")
    verdict = _as_dict(AgentV(st, llm=_FixedSeam("成立")).verify_proof(sid, PROOF))
    assert verdict.get("verdict") == "成立", verdict
    steps.append("B.register_statement/V.verify_proof")

    # ⑦ 链闭合：经审核的自证定理 ⇒ 是根
    chain = _as_dict(AgentC(st).proof_chain(target=sid))
    payload = chain.get("payload") or {}
    assert payload.get("closed") is True, chain.get("summary")
    assert payload.get("roots") == [sid], payload
    steps.append("C.proof_chain")

    # ⑧ G 成稿 ＋ H 审校（都要返回读数、不抛）
    g = AgentG(st)
    # 零文献场景下，稿子的依据只能是我们自己刚审过的那条命题（`stmt:` 引用）——
    # 这也正是"缺文献也能把研究做完"的正面样子（FC-02：没有引用的断言不许进稿件）。
    claim = _as_dict(g.compose_claim(text="阿贝尔群是一种群。",
                                     citations=[f"stmt:{sid}"],
                                     evidence_kind="heuristic", section="引言"))
    doc = _as_dict(g.build_document(kind="paper", title="长跑探针稿", claims=[claim],
                                    sections=[{"heading": "引言", "text": "探针正文。"}]))
    did = str(doc.get("doc_id") or "")
    assert len(st.rows("documents")) == 1, doc
    _as_dict(AgentH(st).review(did))
    steps.append("G.build_document/H.review")

    assert steps == ["A.search_literature", "B.run_once", "D.propose_question",
                     "F.create_plan/F.step", "E.run_experiment",
                     "B.register_statement/V.verify_proof", "C.proof_chain",
                     "G.build_document/H.review"], steps
