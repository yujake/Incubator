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
from agentflow import errorstate as ES
from agentflow import evidencebits as EB
from agentflow import schema as S
from conftest import TS, sync_counters
from agentflow.store import Store


def _stmt(store: Store, sid: str, *, level: str = "", voided_by: dict | None = None,
          **kw) -> dict:
    """一条命题（默认 active + external_lit + 逐字已核）。

    等级是唯一的轴（2026-11-05）：档位由五元位现算，不再由调用方声明。
    `level="theorem"` 预置「证明 + 机器可核（第 4 位某个证明号 verified）」那两格；
    别的档位只预置第 2 位（有证明）。

    2026-11-13（「状态=错误 ⇔ 等级=错误」恒等）：`status` 是错误那一档时必须带
    作废载荷 —— 一份"如实登记被证否"的夹具，凭据不能空着（空载荷的行现在读成
    "读不出来"，不再是"它错了"）。下面那几个用例只关心污染面，所以这里给一份最小
    可复核的构造凭据；要测坏行的用例自己传 `voided_by={}`。
    """
    base = dict(stmt_id=sid, origin="external_lit", kind="theorem", label=f"Theorem {sid}",
                statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
                proof_text="Proof. 逐字摘录……", source_lit_id="0000",
                quote_verified=True, quote_reason="逐字比对通过",
                status="active", created_at=TS)
    base.update(kw)
    body = str(base.get("proof_text") or "")
    status_now = str(base.get("status") or "")
    payload = dict(voided_by) if voided_by is not None else None
    if payload is None and status_now in ES.ERROR_WORDS:
        payload = {"kind": "construction", "construction": "夹具：原文条件少了正性假设",
                   "reason": "原文条件少了正性假设", "at": TS}
    bits = EB.bits_of(
        origin=str(base.get("origin") or "own_result"),
        source_lit_id=str(base.get("source_lit_id") or ""),
        quote_verified=base.get("quote_verified"),
        proof=bool(body.strip()), proof_process=body,
        formal=("verified" if level == "theorem" else None),
        formal_evidence=({"checker": "lean4"} if level == "theorem" else None),
        voided_by=dict(payload or {}),
        kind=str(base.get("kind") or ""))
    base["bits"] = bits
    # 档位是登记那一刻等级的反算名（历史列），不是"判它错之后"再反算一次：
    # 「错误」在 FC-27 词表补丁落地前还没有别名（`kind_from_grade("错误") == ""`），
    # 拿带载荷的 bits 现算会得到空串、撞 `Statement.validate`。生产路的
    # `refute_statement` 也不重算这一列（它只改 status / bits / 等级），所以这里照它来。
    plain = {**bits, "voided_by": {}}
    base["evidence_kind"] = EB.kind_from_bits(plain, kind=str(base.get("kind") or ""))
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
    _stmt(st, "0002", level="theorem", derived_from=["0001"])
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
    _stmt(st, "0002", level="theorem", derived_from=["0001"])
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


# ==================================================== R5-组 4 + `draft/68` 题 1：两层污染面

#: 残余边界那句话必须逐字出现在读数里（改这句话 = 改口径，判据在这里守着）。
#: 与 `closing.POLLUTION_SCOPE_BOUNDARY` 逐字一致：判据侧刻意不 import 那个常量，
#: 否则"把常量改成空串"就能让判据跟着一起变绿。
#:
#: 改前这句是"断言级污染面判不了：`documents.claims[].citations` 只认
#: `lit:`/`exp:`/`rel:`，没有引用命题的形式"。2026-10-07 所有者裁定 `draft/68`
#: 题 1 选 A（本次改动由所有者授权、主控代改）之后，`citations` 认 `stmt:<命题号>`
#: ⇒ 那句话不再成立，判据必须跟着改成新的（缩小后的）边界 —— 保留"判不了"
#: 的旧句会让这条判据与实现相反，而它守的本来是"边界必须说出来"。
POLLUTION_BOUNDARY_SENTENCE = (
    "断言级污染面只覆盖显式写了 `stmt:<命题号>` 的引用："
    "`documents.claims[].citations` 里没带 `stmt:` 前缀的引用指不到任何命题，"
    "它对命题层不可见")


def _boundary_missing(text: str) -> bool:
    """读数里少了那句边界（判据与它的负控共用这一个谓词）。"""
    return POLLUTION_BOUNDARY_SENTENCE not in text


def test_the_assertion_level_boundary_is_verbatim_in_the_readings(tmp_path):
    """断言级污染面的残余边界必须逐字出现在读数里（边界缩小了，不是消失了）。

    `citations` 现在认 `stmt:<命题号>`（`draft/68` 题 1），所以"哪几条正文断言压在
    这条命题上"判得了；仍然判不了的是没写 `stmt:` 的引用（裸号、或别的表的
    前缀）—— 它们指不到任何命题。这句话必须照样说出来：边界可见 ≠ 边界消失，
    而"没写前缀的引用看不见"这件事一旦沉默，读的人会把"这一层没有断言压着"
    读成"稿件里确实没有相关断言"。
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


def test_the_assertion_level_is_computed_not_judged(tmp_path):
    """三层三态：`computed`（查过了）与 `unreadable`（没查成）与"没问题"都不同形。

    改前这一格是 `not_judged`（"按设计不判"）：那时 `citations` 没有引用命题的写法，
    这一层连数据形式都没有。`draft/68` 题 1 选 A 之后它是现算读数 ——
    所以判据从「必须是 not_judged」改成「必须是 computed 且 0 是真 0（不是没查成）」；
    这一改是这次改动可见的后果，理由逐字写在这里（不是为了让红灯变绿）。
    """
    st = _store(tmp_path)
    rep = _run(st)
    a = rep.readings["contradictions"]["pollution_assertion_level"]
    assert a["state"] == "computed", a
    assert a["readable"] is True and a["documents"] == 0, a
    # 反真空：两格计数分开给 —— 0 / 0（没有稿件）与 0 / 40（扫了 40 条断言、一条没引命题）
    # 不是同一件事，而只给一个 0 时它们同形。
    assert a["claims_total"] == 0 and a["claims_citing_a_statement"] == 0, a
    assert a["statements_cited"] == 0 and a["by_statement"] == {}, a
    assert not _boundary_missing(str(a["reason"])), a


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


def test_a_too_large_ledger_blocks_the_closure_distribution_instead_of_reporting_zero(
        tmp_path, monkeypatch):
    """命题数超阈值 ⇒ `state="too_large"` 显式阻塞；"没算"不许折成"没有下游"。

    为什么必须有这一条（R5 组 4 的收尾复核，2026-10-07）：这一支此前没有任何判据看着 ——
    `grep -n too_large tests/` 命中的都是 E13/`attack_round`、`locallib`、`agent_f` 那一族，
    是另一个对象（预算超限），与污染面的"账本太大所以闭包分布不算"不是同一件事。
    它与本文件其余用例同族：把"没查成/没算"与"查成了、结果为空"折平，读的人就会得出
    一个错误结论（"这一层没有下游"），而实际上只是没算。

    两端都控：阈值压到 3 条以下 ⇒ 必须阻塞且理由行写明；阈值抬上去 ⇒ 必须真的算出来
    （否则上一条可能只是"永远 too_large"的真空判据）。
    """
    st = _store(tmp_path)
    _stmt(st, "0001", status="refuted", quote_reason="原文条件少了正性假设")
    _stmt(st, "0002", derived_from=["0001"])
    _stmt(st, "0003", derived_from=["0002"])

    monkeypatch.setattr(CL, "POLLUTION_CLOSURE_MAX_NODES", 2)   # 3 条 > 2 ⇒ 必须阻塞
    blocked = CL.proposition_level_pollution(st)
    assert blocked["state"] == "too_large", blocked
    assert blocked["closure_sizes"] is None and blocked["max_closure"] is None, blocked
    # 阻塞的是"闭包分布"那一格：有/没有下游那一格照样算得出来（不许一阻塞就整格作废）
    assert blocked["statements"] == 3 and blocked["with_downstream"] == 2, blocked
    assert blocked["without_downstream"] == 1, blocked
    assert "没有下游" in str(blocked["reason"]), blocked

    monkeypatch.setattr(CL, "POLLUTION_CLOSURE_MAX_NODES", 10)
    ok = CL.proposition_level_pollution(st)
    assert ok["state"] == "computed" and ok["max_closure"] == 2, ok
    assert ok["closure_sizes"] == {"0": 1, "1": 1, "2": 1}, ok


# ==================================================== I2 闭环：图上现算的对立对有没有裁决过
#
# 这一组守的是 `contradictions` 这一格的第五条病因（2026-11-14，业主拍板方向）：
# 前四种读的都是别人已经判过的状态，一条都不回答"图上现算出来的 strong 对立对，
# 有没有走过裁决闭环"。判据只有两条、且都复用已有实现：
#   读 relations → `interactions.detect_contradictions` 取 strong
#   → 每一对去 `research_questions` 找 `kind="contradiction"` 且 ids == {a,b} 的裁决行
#   → 没有行 = `contradiction_unadjudicated`；有行而 verdict 不在终态 = `contradiction_unresolved`。
# `persistent` 只进读数（业主尚未裁定它该不该拦，当前口径：不拦）。

#: 5 对 strong 对立（与 `R-mk-infinite-90` 的现场同形：5 对、双方 active、0 行裁决）。
#: 每一对占一个独立概念组 —— 不同概念组之间永不比较（`detect_contradictions` 的口径）。
STRONG_PAIRS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = tuple(
    ((f"{2 * i:04d}", f"{2 * i + 1:04d}"), (f"{100 + 2 * i:04d}", f"{101 + 2 * i:04d}"))
    for i in range(5))


def _rel(st: Store, rid: str, text: str, *, concept_ids: tuple[str, str] = ("0100", "0101"),
         status: str = "active", **kw) -> dict:
    """写一条关系行（默认 active；引文那一格默认 `None` = 还没核，别让它去撞引文回验那一档）。"""
    base = dict(relation_id=rid, concept_ids=list(concept_ids), description=text,
                statement=text, lit_id="0000", page_range=S.PageRange(start=1, end=2),
                status=status, quote_verified=None, created_at=TS)
    base.update(kw)
    row = S.Relation(**base)
    row.validate()
    with st.tx("relations", actor="test") as tx:
        tx.upsert("relations", row.to_dict())
    return row.to_dict()


def _seed_strong_pairs(st: Store) -> None:
    """落 5 对 strong 对立（同一概念组内一句肯定、一句否定）。"""
    for (a, b), group in STRONG_PAIRS:
        _rel(st, a, "A 是 B。", concept_ids=group)
        _rel(st, b, "A 不是 B。", concept_ids=group)


def _adjudication_row(st: Store, qid: str, pair: tuple[str, str], verdict: str | None,
                      *, status: str = "answered", rounds: int = 0, kind: str = "contradiction",
                      ) -> dict:
    """写一行裁决行；`needs_evidence` 那一档按 schema 必须带非空等待集。"""
    extra: dict = {}
    if status == "needs_evidence":
        extra["waiting_request_ids"] = ["r0000"]
    row = S.ResearchQuestion(
        question_id=qid,
        question=f"关系 {pair[0]} 与 {pair[1]} 的陈述互相矛盾，需要判定哪一方成立",
        origin=f"C:contradictions:{pair[0]}+{pair[1]}",
        related_relation_ids=sorted(pair),
        kind=kind,
        contradiction_relation_ids=sorted(pair) if kind == "contradiction" else [],
        contradiction_verdict=verdict,
        contradiction_rounds=rounds,
        status=status,
        priority="high",
        created_at=TS,
        **extra,
    )
    row.validate()
    with st.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions", row.to_dict())
    return row.to_dict()


def _pair_codes(rep) -> list[str]:
    return [f.code for f in rep.findings if f.check == "contradictions"]


def test_a_strong_pair_without_an_adjudication_row_blocks_the_gate(tmp_path):
    """判据 a：5 对 strong、0 行裁决 ⇒ fail，且 blocker 逐对点名（不是一句"有矛盾"）。

    这正是 `R-mk-infinite-90` 的现场：图上现算出 5 对 strong 对立，`research_questions`
    里 0 行 `kind=contradiction`，而这一格改前照样 `pass`。
    """
    st = _store(tmp_path)
    _seed_strong_pairs(st)
    rep = _run(st)
    assert rep.status["contradictions"] == "fail", rep.to_dict()
    assert _pair_codes(rep) == ["contradiction_unadjudicated"] * 5, _pair_codes(rep)
    r = rep.readings["contradictions"]
    assert [p["relation_ids"] for p in r["unadjudicated_pairs"]] == [
        ["0000", "0001"], ["0002", "0003"], ["0004", "0005"], ["0006", "0007"], ["0008", "0009"]]
    assert [p["cause"] for p in r["unadjudicated_pairs"]] == ["no_adjudication_row"] * 5
    assert r["persistent_pairs"] == [] and r["strong_pairs"] == 5, r
    assert r["suspect_relations"] == {"dedup": 0, "quote_failed": 0, "i6_conflict": 0}, r
    # 逐对点名：详情里必须出现那一对的关系号（处置把手要能落到具体某一对）
    details = [f.detail for f in rep.findings if f.check == "contradictions"]
    assert all(f"{a}+{b}" in " ".join(details) for (a, b), _ in STRONG_PAIRS), details


def test_resolved_adjudication_rows_turn_the_same_gate_green(tmp_path):
    """判据 b：同一个夹具落 5 行 `resolved` 裁决 ⇒ pass，两族 pair 读数归零。

    与上一条是同一个工作区形态，只多 5 行裁决 —— "红变绿"的差别必须全部来自裁决行。
    """
    st = _store(tmp_path)
    _seed_strong_pairs(st)
    for i, (pair, _group) in enumerate(STRONG_PAIRS):
        _adjudication_row(st, f"{i:04d}", pair, "resolved")
    rep = _run(st)
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    assert [f for f in rep.findings if f.level == "blocker"] == [], rep.to_dict()
    r = rep.readings["contradictions"]
    assert r["unadjudicated_pairs"] == [] and r["persistent_pairs"] == [], r
    assert r["strong_pairs"] == 5, r


def test_persistent_adjudication_is_a_reading_not_a_blocker(tmp_path):
    """判据 c：`persistent` 不产生 blocker（当前口径），但读数必须点名那 5 对。

    `persistent` 是裁决过的终态（追问预算用尽、双方仍对立、交人复核），不是"没裁决"。
    业主还没裁定它该不该拦门，所以这一条把当前口径钉住：要翻只改一处（读数已经在了）。
    """
    st = _store(tmp_path)
    _seed_strong_pairs(st)
    for i, (pair, _group) in enumerate(STRONG_PAIRS):
        _adjudication_row(st, f"{i:04d}", pair, "persistent")
    rep = _run(st)
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    assert not [f for f in rep.findings if f.level == "blocker"], rep.to_dict()
    r = rep.readings["contradictions"]
    assert r["unadjudicated_pairs"] == [], r
    assert [p["relation_ids"] for p in r["persistent_pairs"]] == [
        ["0000", "0001"], ["0002", "0003"], ["0004", "0005"], ["0006", "0007"], ["0008", "0009"]]
    assert all(p["question_id"] for p in r["persistent_pairs"]), r["persistent_pairs"]


def test_a_non_terminal_verdict_blocks_as_unresolved(tmp_path):
    """判据 a 的另一半：有裁决行但 verdict 不在终态 ⇒ `contradiction_unresolved`（带 rounds）。

    "有行"不等于"裁决过"：`unresolved` 是"还要继续追问"的中间态，它不许冒充终态。
    """
    st = _store(tmp_path)
    pair = STRONG_PAIRS[0][0]
    _rel(st, pair[0], "A 是 B。", concept_ids=STRONG_PAIRS[0][1])
    _rel(st, pair[1], "A 不是 B。", concept_ids=STRONG_PAIRS[0][1])
    _adjudication_row(st, "0000", pair, "unresolved", status="needs_evidence", rounds=1)
    rep = _run(st)
    assert rep.status["contradictions"] == "fail", rep.to_dict()
    assert _pair_codes(rep) == ["contradiction_unresolved"], _pair_codes(rep)
    r = rep.readings["contradictions"]
    assert r["unadjudicated_pairs"] == [{
        "relation_ids": ["0000", "0001"], "cause": "verdict_not_terminal",
        "question_id": "0000", "verdict": "unresolved", "rounds": 1}], r["unadjudicated_pairs"]
    assert "0000+0001" in rep.findings[0].detail and "0000" in rep.findings[0].detail, \
        rep.findings[0].detail


def test_stubbing_the_detector_turns_the_same_red_off(tmp_path, monkeypatch):
    """判据 d（反真空）：把 `IX.detect_contradictions` 打桩成恒 `[]` ⇒ 上面那条红变绿。

    这条读法钉住的是"红的来源"：红必须来自现算的检测器，而不是别的格串进来的噪音。
    所以正确形态是"打桩后 a 变绿"（说明 a 依赖它）；如果打桩后仍然 fail，说明红根本
    不是这条判据造出来的 —— 那才是判据失焦。
    """
    st = _store(tmp_path)
    _seed_strong_pairs(st)
    assert _run(st).status["contradictions"] == "fail", "打桩前它必须是红的（否则这条反真空空转）"
    monkeypatch.setattr(CL.IX, "detect_contradictions", lambda relations: [])
    rep = _run(st)
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    r = rep.readings["contradictions"]
    assert r["strong_pairs"] == 0 and r["unadjudicated_pairs"] == [], r
    assert [f for f in rep.findings if f.level == "blocker"] == [], rep.to_dict()


def test_suspect_rows_are_readings_and_never_fail_the_cell(tmp_path):
    """判据 e（负控，两个方向）：suspect 三族只进读数，fail 与否不受它们影响。

    14 条判重中间态 + 12 条引文回验失败，逐条核过 0 条是对立；把它们当"未裁决的矛盾"
    就是本项目最贵的假红（会训练人忽略告警）。两个方向都造：
    ① 只有 suspect ⇒ pass；② 同一批 suspect 留在/拿掉，5 对 strong 的 fail 与 blocker 逐条不变。
    """
    def _seed_suspects(st: Store) -> None:
        for i in range(14):                      # 判重中间态：duplicate_of 非空、引文已核
            _rel(st, f"{100 + i:04d}", "几乎相同的一条", status="suspect",
                 duplicate_of="0000", concept_ids=(f"{200 + 2 * i:04d}", f"{201 + 2 * i:04d}"))
        for i in range(12):                      # 引文回验失败：quote_verified=False
            _rel(st, f"{200 + i:04d}", "引文没核过的一条", status="suspect",
                 quote_verified=False, concept_ids=(f"{400 + 2 * i:04d}", f"{401 + 2 * i:04d}"))

    # ① 只有 suspect ⇒ 一条都不许拦（假红负控）
    only_suspect = _store(tmp_path / "a")
    _seed_suspects(only_suspect)
    clean = _run(only_suspect)
    assert clean.status["contradictions"] == "pass", clean.to_dict()
    assert clean.readings["contradictions"]["suspect_relations"] == \
        {"dedup": 14, "quote_failed": 12, "i6_conflict": 0}, clean.readings["contradictions"]

    # ② 5 对 strong 在场：留/拿掉同一批 suspect，fail 与 blocker 逐条不变
    without = _store(tmp_path / "b")
    _seed_strong_pairs(without)
    red = _run(without)
    with_suspect = _store(tmp_path / "c")
    _seed_strong_pairs(with_suspect)
    _seed_suspects(with_suspect)
    red_too = _run(with_suspect)
    assert red.status["contradictions"] == red_too.status["contradictions"] == "fail"
    assert _pair_codes(red) == _pair_codes(red_too) == ["contradiction_unadjudicated"] * 5
    assert red_too.readings["contradictions"]["suspect_relations"] == \
        {"dedup": 14, "quote_failed": 12, "i6_conflict": 0}


def test_unreadable_relations_make_the_cell_unknown_not_pass(tmp_path):
    """判据 f：relations 读不出来 ⇒ unknown（不是 pass），两族 pair 读数给 None 不是 []。

    `unknown` 既不是过也不是不过：坏表上给 pass 就是"没查成"被折成"没问题"。
    """
    st = _store(tmp_path)
    (st.root / "data" / "relations.json").write_text("{ 这不是 JSON", encoding="utf-8")
    rep = CL.check_closing(Store(st.root), checks=("contradictions",))
    assert rep.status["contradictions"] == "unknown", rep.to_dict()
    r = rep.readings["contradictions"]
    assert r["relations_reading"] == "unreadable", r
    assert r["unadjudicated_pairs"] is None and r["persistent_pairs"] is None, r
    assert r["suspect_relations"] is None, r
    assert "relation_contradictions_unreadable" in _pair_codes(rep), _pair_codes(rep)
    assert "StoreError" in " ".join(f.detail for f in rep.findings), rep.findings


def test_weak_and_dead_pairs_are_readings_not_blockers(tmp_path):
    """负控（假红）：weak 对与"一方已不在图里"的对立文本都不许拦门。

    - weak（只有否定标记出现与否不一致）在真实关系上假阳性极高 ⇒ 只进 `weak_pairs`；
    - 一方 `status=rejected` ⇒ 那场争议已被删边消解，不在册 ⇒ 不现算成"在册的对立对"。
    """
    st = _store(tmp_path)
    _rel(st, "0000", "|S| = 0 的见证是显式的。", concept_ids=("0100", "0101"))
    _rel(st, "0001", "端点 0 不必用数值搜索。", concept_ids=("0100", "0101"))
    _rel(st, "0002", "A 是 B。", status="rejected", concept_ids=("0200", "0201"))
    _rel(st, "0003", "A 不是 B。", concept_ids=("0200", "0201"))
    rep = _run(st)
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    r = rep.readings["contradictions"]
    assert r["strong_pairs"] == 0 and r["weak_pairs"] == 1, r
    assert r["active_relations"] == 3, "active 只有 0000 / 0001 / 0003（0002 已 rejected）"
    assert r["unadjudicated_pairs"] == [], r
