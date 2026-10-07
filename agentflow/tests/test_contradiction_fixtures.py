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


# ==================================================== R5-组 4：断言级判不了 + 命题层三态

#: 边界那句话必须逐字出现在读数里（改这句话 = 改口径，判据在这里守着）。
#: 与 `closing.POLLUTION_SCOPE_BOUNDARY` 逐字一致：判据侧刻意不 import 那个常量，
#: 否则"把常量改成空串"就能让判据跟着一起变绿。
POLLUTION_BOUNDARY_SENTENCE = (
    "断言级污染面判不了：`documents.claims[].citations` 只认 `lit:`/`exp:`/`rel:`，"
    "没有引用命题的形式")


def _boundary_missing(text: str) -> bool:
    """读数里少了那句边界（判据与它的负控共用这一个谓词）。"""
    return POLLUTION_BOUNDARY_SENTENCE not in text


def test_the_assertion_level_boundary_is_verbatim_in_the_readings(tmp_path):
    """B 方案：断言级污染面今天判不了 —— 这句话必须在读数里逐字出现。

    `citations` 只认 `lit:`/`exp:`/`rel:` 三种前缀，没有"引用命题"的形式，
    所以"哪几条正文断言压在这条命题上"在数据面上无解。补法（加 `stmt:` 前缀）
    属字段取舍、且要动 `schema.py` ⇒ 留给人裁；在此之前不许沉默，
    也不许为了让"断言级"看起来有覆盖而去放宽前缀解析（那会把幻觉引文放进来）。
    """
    st = _store(tmp_path)
    rep = _run(st)
    r = rep.readings["contradictions"]
    assert not _boundary_missing(str(r["pollution_scope"])), r["pollution_scope"]
    assert not _boundary_missing(str(r["pollution_assertion_level"]["reason"])), \
        r["pollution_assertion_level"]

    # 负控：把那句话从读数里删掉 ⇒ 同一个判据必须看见（否则它是橡皮图章）
    stripped = str(r["pollution_scope"]).replace(POLLUTION_BOUNDARY_SENTENCE, "")
    assert stripped != str(r["pollution_scope"]), "夹具没删到那句话 ⇒ 这条负控是空转"
    assert _boundary_missing(stripped), "边界被删掉却没被看见"


def test_the_assertion_level_is_registered_as_not_judged_not_as_clean(tmp_path):
    """三层三态：`not_judged`（按设计不判）与 `unreadable`（没查成）与"没问题"都不同形。"""
    st = _store(tmp_path)
    rep = _run(st)
    a = rep.readings["contradictions"]["pollution_assertion_level"]
    assert a["state"] == "not_judged", a
    assert a["readable"] is True and a["documents"] == 0, a


def test_the_proposition_level_reading_counts_downstream_and_closure_sizes(tmp_path):
    """命题层要给出现算读数：多少命题有下游 + 闭包大小分布。"""
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _stmt(st, "0002", derived_from=["0001"])
    _stmt(st, "0003", derived_from=["0002"])
    rep = _run(st)
    r = rep.readings["contradictions"]
    lvl = r["pollution_proposition_level"]
    assert lvl["state"] == "computed", lvl
    assert lvl["statements"] == 3 and lvl["with_downstream"] == 2, lvl
    assert lvl["without_downstream"] == 1 and lvl["max_closure"] == 2, lvl
    assert lvl["closure_sizes"] == {"0": 1, "1": 1, "2": 1}, lvl
    # 有下游那一态的逐条读数：闭包 + state
    assert r["pollution_states"] == {"0001": "computed"}, r["pollution_states"]
    assert r["pollution"] == {"0001": ["0002", "0003"]}, r["pollution"]
    assert r["pollution_unreadable"] == [], r["pollution_unreadable"]


def test_a_refuted_statement_with_nothing_below_is_computed_not_unreadable(tmp_path):
    """无下游：state 仍是 `computed`（查过了、确实没有下游），只是闭包为空。"""
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    rep = _run(st)
    r = rep.readings["contradictions"]
    assert r["pollution_states"] == {"0001": "computed"}, r["pollution_states"]
    assert r["pollution"] == {"0001": []}, r["pollution"]
    assert r["pollution_proposition_level"]["with_downstream"] == 0, r["pollution_proposition_level"]
    assert r["pollution_unreadable"] == [], r["pollution_unreadable"]


def test_no_store_makes_the_pollution_reading_unreadable_instead_of_absent():
    """没查成：`store=None` ⇒ 两层的 state 都是 `unreadable`，而且读数那一格必须存在。

    改前 `store=None` 时整格读数缺席（`readings` 里连 `contradictions` 都没有）
    ⇒"没查成"与"没有这一格"同形，读的人只能去猜。
    """
    rep = CL.check_closing(None, checks=("contradictions",))
    assert rep.status["contradictions"] == "unknown"
    r = rep.readings["contradictions"]
    assert r["pollution_proposition_level"]["state"] == "unreadable", r
    assert r["pollution_assertion_level"]["state"] == "unreadable", r
    assert r["pollution_unreadable"], r
    assert "没查成" in str(r["pollution_proposition_level"]["reason"]), r
    assert not _boundary_missing(str(r["pollution_scope"])), r["pollution_scope"]


class _UnreadableStore:
    """一个读盘就抛的 store（"这一趟没查成"的机械形态）。"""

    def rows(self, table: str):  # noqa: D401 - 夹具
        raise RuntimeError(f"盘坏了：{table}")


def test_an_unreadable_ledger_is_not_reported_as_no_downstream(tmp_path):
    """函数级三态：读盘失败与"确实没有下游"必须给出不同的 state。"""
    one = CL.pollution_reading(_UnreadableStore(), "0001")
    assert one["state"] == "unreadable" and one["downstream"] == [], one
    assert "RuntimeError" in str(one["reason"]), one
    lvl = CL.proposition_level_pollution(_UnreadableStore())
    assert lvl["state"] == "unreadable", lvl
    absent = CL.pollution_reading(None, "0001")
    assert absent["state"] == "unreadable", absent
    # 与"这条命题不在账本里"也要分开：那是第三种 state，不是"没有下游"
    st = _store(tmp_path)
    _stmt(st, "0009")
    missing = CL.pollution_reading(st, "1234")
    assert missing["state"] == "no_such_statement", missing
    assert CL.pollution_reading(st, "0009")["state"] == "computed", "有这条命题就判得了"
