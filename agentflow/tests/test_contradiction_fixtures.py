# -*- coding: utf-8 -*-
"""矛盾与"文献错了"两个场景的夹具（`draft/37` §8/§9 的 R19/R20，§16 P4 场景三）。

## 为什么这一组全是夹具（不接模型）

§16 P4 逐字写着"先用夹具跑（不接模型），再决定要不要真机"。理由不是省钱，
而是判据的稳定性：这三种病因（读错文献 / 来源有争议 / 我们的证明有洞）如果让模型来
即兴产生，那么"判据红了"到底是判据错了还是这一次模型跑歪了，就分不开。

## 守什么

R19：三种病因各一个 code，而且把某一种摆进去时，红的必须正好是它；
R20：文献被证否时给污染面（谁跟着倒），并且"记下来了"与"出事了"要分得开 ——
如实登记一条 `refuted` 而没有任何结论压在它上面 ⇒ 一条都不许报。

这两条合起来才是 §9 的处置：不是"把这一条划掉"，而是"压在它上面的结论怎么办"。
"""
from __future__ import annotations

import pytest

from agentflow import closing as CL
from agentflow import schema as S
from conftest import TS, sync_counters
from agentflow.store import Store


def _stmt(store: Store, sid: str, **kw) -> dict:
    """一条命题（默认 active + external_lit + 逐字已核）。"""
    base = dict(stmt_id=sid, origin="external_lit", kind="theorem", label=f"Theorem {sid}",
                statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
                proof_text="Proof. 逐字摘录……", source_lit_id="0000",
                quote_verified=True, quote_reason="逐字比对通过", evidence_kind="cross_check",
                status="active", created_at=TS)
    base.update(kw)
    row = S.Statement(**base)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971",
                                             type="J", summary="室图随机游走",
                                             path=None, added_at=TS).to_dict())
    sync_counters(st)
    return st


def _codes(rep) -> list[str]:
    return sorted(f.code for f in rep.findings if f.check == "contradictions")


def _run(st: Store):
    """只跑矛盾那一条（其余四条与这两个场景无关，跑全门会引入无关噪音）。"""
    return CL.check_closing(st, checks=("contradictions",))


# ==================================================== R19 三种病因，各一条负控

def test_the_wrong_paper_cause_has_its_own_code(tmp_path):
    """病因①：我们读错了文献（下成另一篇），而它已经被消化。

    这一条与"来源有争议"是两件事：处置是重取（A 去把对的那一篇找回来），
    不是送裁决 —— 所以它必须有自己的 code。
    """
    st = _store(tmp_path)
    with st.tx("literature", actor="test") as tx:
        row = dict(st.rows("literature")[0])
        row["matched"] = "mismatch"          # 实测形态：Brown 1971 被下成 2022 年另一篇
        row["processed"] = True
        tx.upsert("literature", row)
    rep = _run(st)
    assert rep.status["contradictions"] == "fail"
    assert _codes(rep) == ["contradiction_wrong_paper"], _codes(rep)
    assert rep.readings["contradictions"]["wrong_paper"], rep.readings
    assert "重取" in rep.findings[0].detail, rep.findings[0].detail

    # 反真空：把它改回"核过、对得上" ⇒ 这一条必须消失
    with st.tx("literature", actor="test") as tx:
        row = dict(st.rows("literature")[0])
        row["matched"] = "exact"
        tx.upsert("literature", row)
    assert _run(st).status["contradictions"] == "pass"


def test_the_disputed_source_cause_has_its_own_code(tmp_path):
    """病因②：来源本身有争议（两篇文献两说）⇒ 送达裁决，处置不是重取。"""
    st = _store(tmp_path)
    row = S.Dependency(dep_id="0001", used_by="doc:0001#c1", kind="theorem",
                       label="两说之一的定理", status="disputed",
                       status_reason="两篇文献给出不同常数", created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict())
    sync_counters(st)
    rep = _run(st)
    assert _codes(rep) == ["contradiction_disputed_source"], _codes(rep)
    assert "ask_user" in rep.findings[0].detail, rep.findings[0].detail


def test_our_own_hole_has_its_own_code(tmp_path):
    """病因③：我们自己的证明有洞（proof 级命题压在一条 disputed 命题上）。

    处置是"补证明或降档"，与"文献有争议"（送裁决）也不同 —— 洞在我们这边。
    """
    st = _store(tmp_path)
    _stmt(st, "0001", status="disputed", quote_reason="我们这一版的证明缺一步")
    _stmt(st, "0002", evidence_kind="proof", derived_from=["0001"])
    rep = _run(st)
    assert "contradiction_own_hole" in _codes(rep), _codes(rep)
    assert "可挽救性评估" in " ".join(f.detail for f in rep.findings), [f.detail for f in rep.findings]


def test_an_unresolved_review_is_its_own_cause(tmp_path):
    """第四种（§14.4 的未决问题）：稿件审校未过 ⇒ 处置是回稿子，不是回证据。"""
    st = _store(tmp_path)
    doc = S.Document(doc_id="0001", kind="paper", title="未发表的论文",
                     status="unresolved_review",
                     claims=[{"claim_id": "c1", "text": "定理 1.5", "citations": ["lit:0000"],
                              "evidence_kind": "cross_check", "section": "§2",
                              "disclaimer": "数值交叉验证，不构成证明"}], created_at=TS)
    doc.validate()
    with st.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    sync_counters(st)
    rep = _run(st)
    assert _codes(rep) == ["review_unresolved"], _codes(rep)


def test_the_three_causes_do_not_collapse_into_one_code(tmp_path):
    """三种病因同时在场 ⇒ 三个 code 各报一次（折成一个就等于没有处置把手）。"""
    st = _store(tmp_path)
    with st.tx("literature", actor="test") as tx:
        row = dict(st.rows("literature")[0])
        row["matched"] = "mismatch"
        row["processed"] = True
        tx.upsert("literature", row)
    dep = S.Dependency(dep_id="0001", used_by="doc:0001#c1", kind="theorem",
                       label="有争议的定理", status="disputed", status_reason="两说",
                       created_at=TS)
    dep.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", dep.to_dict())
    _stmt(st, "0001", status="disputed", quote_reason="缺一步")
    _stmt(st, "0002", evidence_kind="proof", derived_from=["0001"])
    rep = _run(st)
    assert _codes(rep) == ["contradiction_disputed_source", "contradiction_own_hole",
                           "contradiction_wrong_paper"], _codes(rep)


# ==================================================== R20 污染面

def test_pollution_set_is_the_transitive_downstream(tmp_path):
    """R20 的污染面：A 被否 ⇒ 用到 A 的 B、用到 B 的 C 都要跟着倒（传递闭包）。"""
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _stmt(st, "0002", derived_from=["0001"])          # 用到 A
    _stmt(st, "0003", derived_from=["0002"])          # 用到 B ⇒ 间接用到 A
    _stmt(st, "0009")                                  # 与 A 无关
    assert CL.pollution_set(st, "0001") == ["0002", "0003"], CL.pollution_set(st, "0001")
    assert CL.pollution_set(st, "0009") == []


def test_a_refuted_statement_reports_its_pollution(tmp_path):
    """被否的命题必须在读数里带上"谁跟着倒"，而不只是自己那一行。"""
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _stmt(st, "0002", derived_from=["0001"])
    rep = _run(st)
    assert rep.readings["contradictions"]["pollution"] == {"0001": ["0002"]}, \
        rep.readings["contradictions"]["pollution"]
    assert "污染面" in " ".join(f.detail for f in rep.findings), [f.detail for f in rep.findings]


def test_recording_a_refutation_with_nothing_on_top_reports_nothing(tmp_path):
    """反真空（R20 的第二面）：如实记下"这条被证否了"、而没有结论压在它上面 ⇒ 不报。

    与 `test_a_mismatch_that_was_not_digested_is_not_an_issue` 同一条纪律：
    如果"如实登记"本身就要报错，那么正确的行为会被惩罚，于是没人再如实登记。
    """
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    rep = _run(st)
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    assert rep.readings["contradictions"]["pollution"] == {"0001": []}, \
        rep.readings["contradictions"]["pollution"]


def test_the_pollution_scope_limit_is_stated_in_the_readings(tmp_path):
    """污染面的已知边界必须是读数的一部分（"判不了"要说出来，不许沉默）。"""
    st = _store(tmp_path)
    rep = _run(st)
    scope = rep.readings["contradictions"]["pollution_scope"]
    assert "derived_from" in scope and "断言级" in scope, scope
