"""`agentflow.verify` 对 E/F/G/H 四张新表的检查（FC-02 / FC-13 / FC-22 / FC-23 / FC-25）。

## 为什么这些检查必须单独测

`schema.py` 的行校验只能保证本行内部自洽（字段非空、枚举合法、交叉字段一致），
它看不到别的表。而"这个 lit_id 真的存在吗"、"这个依赖闭合了吗"、"稿件被
accepted 了但它还有未修的 error 吗"这类问题，只有 `verify` 能发现。

每个检查都有两个方向（FC-09）：
- 好数据必须过（防误伤）；
- 注入坏数据必须报，且级别正确（FC-13：已知边界是 warning，谎报才是 error）。
"""

from __future__ import annotations

import pytest
from conftest import TS, add_concept, add_literature, add_relation, sync_counters
from agentflow import schema as S
from agentflow.verify import verify_all


# ------------------------------------------------------------------ 小工具


def _issues(store, *, level: str | None = None, kind: str | None = None):
    """取 verify 的 issue 列表。

    字段名是 `code` 而不是 `kind`（`Issue` 的定义在 `verify.py`），
    且 `to_dict()` 给的是已经分好档的 `errors` / `warnings` 两个列表 ——
    这就是 FC-10 三分档在这里的具体形态。用错字段名会静默取到空列表，
    于是所有"注入坏数据必须报错"的断言都会假绿。
    """
    rep = verify_all(store)
    d = rep.to_dict()
    out = list(d["errors"]) + list(d["warnings"])
    if level is not None:
        out = [i for i in out if i["level"] == level]
    if kind is not None:
        out = [i for i in out if i["code"] == kind]
    return out


def _experiment(store, eid: str, **kw) -> dict:
    base = dict(
        experiment_id=eid,
        claim="Spec K(m) = [-m, m]",
        claim_key="SpecK(m)=[-m,m]",
        method="numeric",
        evidence_kind="cross_check",
        result="supports",
        negation_kind="not_proved",
        code_path="code/exp.py",
        code_hash="deadbeefdeadbeef",
        exit_code=0,
        created_at=TS,
    )
    base.update(kw)
    row = S.Experiment(**base)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _dependency(store, did: str, **kw) -> dict:
    base = dict(dep_id=did, used_by="doc:0000#claim-1", kind="theorem", label="Companion book Thm 6.5",
                status="external_unavailable", status_reason="拿不到该书", created_at=TS)
    base.update(kw)
    row = S.Dependency(**base)
    row.validate()
    with store.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _document(store, did: str, **kw) -> dict:
    claim = {"claim_id": "c1", "text": "K(m) 是 m-正则的。", "citations": ["lit:0000"],
             "evidence_kind": "proof"}
    base = dict(doc_id=did, kind="reproduction_report", title="复现报告", claims=[claim],
                status="draft", created_at=TS)
    base.update(kw)
    row = S.Document(**base)
    row.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _finding(store, fid: str, **kw) -> dict:
    base = dict(finding_id=fid, doc_id="0000", kind="unsupported_claim", level="error",
                target="c1", evidence="citations=[]", message="无引用", created_at=TS)
    base.update(kw)
    row = S.ReviewFinding(**base)
    row.validate()
    with store.tx("review_findings", actor="test") as tx:
        tx.upsert("review_findings", row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ------------------------------------------------------------------ 依赖闭合（FC-23）


def test_dependency_external_unavailable_is_warning_not_error(store):
    """分级（FC-13）：拿不到的外部前提是已知边界，报 warning。

    报成 error 会把红灯训练成噪音，于是真正的 error 也会被忽略。
    """
    store.init()
    _dependency(store, "0000")
    assert _issues(store, level="error") == []
    ws = _issues(store, level="warning", kind="dangling_dep_external")
    assert len(ws) == 1
    assert "本框架可得范围之外" in ws[0]["message"] or "可得范围之外" in ws[0]["message"]


def test_dependency_dangling_is_error(store):
    """反向：登记了依赖却既没闭合、也没说明为什么拿不到 ⇒ error（没交代）。"""
    store.init()
    _dependency(store, "0000", status="dangling", status_reason="悬着")
    errs = _issues(store, level="error", kind="dangling_dep")
    assert len(errs) == 1


def test_dependency_closed_pointing_to_missing_lit_is_error(store):
    """负控（最重要的一条）：`closed` 但指向不存在的 lit ⇒ 空头支票 ⇒ error。

    schema 只能检查"`closed` 必须给了 id"，"那个 id 真的存在"只有 verify 能查。
    """
    store.init()
    _dependency(store, "0000", status="closed", status_reason="", source_lit_id="0099")
    errs = _issues(store, level="error", kind="dangling_dep")
    assert len(errs) == 1 and "空头支票" in errs[0]["message"]


def test_dependency_closed_with_real_lit_is_clean(store):
    """防误伤：`closed` 且 lit 真的存在 ⇒ 无 error，且计入 `dependencies_closed`。"""
    store.init()
    add_literature(store, "0000", title="某文献")
    _dependency(store, "0000", status="closed", status_reason="", source_lit_id="0000")
    assert _issues(store, level="error") == []
    rep = verify_all(store)
    assert rep.to_dict()["checked"]["dependencies_closed"] == 1


# ------------------------------------------------------------------ E 的实验（FC-22）


def test_experiment_with_valid_fields_is_clean(store):
    store.init()
    _experiment(store, "0000")
    assert _issues(store, level="error") == []


def test_experiment_without_hash_is_error(store):
    """负控：有 code_path 却没有 code_hash ⇒ error（"可复现"只是口号）。

    直接注入表里，不走 `Experiment.validate` —— 因为 schema 是第一道闸，
    它在写入前就会拒绝这种行。这里要验证的是第二道闸：
    `verify` 能不能抓到已经躺在表里的违规数据（历史数据、手工改过的快照、
    `rebuild` 之前的旧文件都不受 schema 保护）。
    """
    store.init()
    doc = store.read("experiments")
    doc["rows"].append({
        "experiment_id": "0000", "claim": "c", "claim_key": "k", "method": "numeric",
        "evidence_kind": "cross_check", "result": "supports", "negation_kind": "not_proved",
        "code_path": "code/exp.py", "code_hash": "", "created_at": TS,
    })
    store._atomic_write(store.data / "experiments.json", doc)
    errs = _issues(store, level="error", kind="unhashed_experiment_code")
    assert len(errs) == 1


def test_experiment_refutation_without_counterexample_is_error(store):
    """负控：`result='refutes'` 但没给反例 ⇒ '证否'不可复核。

    同样直接注入表里：schema 会在写入前拒绝它，我们要验的是 verify 这第二道闸。
    """
    store.init()
    doc = store.read("experiments")
    doc["rows"].append({
        "experiment_id": "0000", "claim": "c", "claim_key": "k", "method": "numeric",
        "evidence_kind": "cross_check", "result": "refutes", "negation_kind": "disproved",
        "counterexample": None, "created_at": TS,
    })
    store._atomic_write(store.data / "experiments.json", doc)
    errs = _issues(store, level="error", kind="refutation_without_counterexample")
    assert len(errs) == 1


def test_experiment_evidence_kind_overclaim_is_caught_by_schema_first(store):
    """schema 是第一道闸：计算类方法称 `proof` 在写入时就被拒。

    这条断言的要点不是"verify 也能查"，而是确认它根本进不了库 ——
    写入期拒绝比事后校验强得多（用户拿不到一条已经写坏的记录）。
    """
    store.init()
    with pytest.raises(ValueError):
        _experiment(store, "0000", method="numeric", evidence_kind="proof", verifier_output="x")


def test_experiment_evidence_kind_overclaim_in_stored_rows_is_caught(store):
    """第二道闸：手工塞进表里的违规数据仍会被 verify 抓到。

    为什么需要它：schema 只保护经过 schema 的写入路径。
    历史数据、外部工具改过的快照、以及 `rebuild` 之前的旧文件都不受它保护。
    """
    store.init()
    doc = store.read("experiments")
    doc["rows"].append({
        "experiment_id": "0000", "claim": "c", "claim_key": "k", "method": "numeric",
        "evidence_kind": "proof", "result": "supports", "negation_kind": "not_proved",
        "verifier_output": "", "created_at": TS,
    })
    store._atomic_write(store.data / "experiments.json", doc)
    errs = _issues(store, level="error", kind="evidence_kind_overclaim")
    assert len(errs) == 1


def test_experiment_dangling_question_ref_is_error(store):
    store.init()
    _experiment(store, "0000", for_question_id="0099")
    assert len(_issues(store, level="error", kind="dangling_question_ref")) == 1


# ------------------------------------------------------------------ F 的攻坚计划


def test_plan_dangling_experiment_ref_is_error(store):
    """负控：子目标引用的实验不存在 ⇒ "有数值支持"这句话不可核对。"""
    store.init()
    plan = S.AttackPlan(
        plan_id="0000", problem="p", problem_key="k", status="attacking", rounds=0,
        budget={"max_rounds": 4, "max_parallel_subgoals": 1, "max_persist_attempts": 1, "max_depth": 1},
        subgoals=[{"sid": "sg1", "text": "t", "owner": "E", "status": "todo",
                   "experiment_ids": ["0099"]}],
        created_at=TS, updated_at=TS,
    )
    with store.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", plan.to_dict())
    sync_counters(store)
    assert len(_issues(store, level="error", kind="dangling_experiment_ref")) == 1


def test_plan_subgoal_with_isolated_concepts_and_real_experiment_is_clean(store):
    store.init()
    _experiment(store, "0000")
    plan = S.AttackPlan(
        plan_id="0000", problem="p", problem_key="k", status="resolved", rounds=1,
        budget={"max_rounds": 4, "max_parallel_subgoals": 1, "max_persist_attempts": 1, "max_depth": 1},
        subgoals=[{"sid": "sg1", "text": "t", "owner": "E", "status": "supported_not_proved",
                   "experiment_ids": ["0000"]}],
        created_at=TS, updated_at=TS,
    )
    with store.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", plan.to_dict())
    sync_counters(store)
    assert _issues(store, level="error") == []


# ------------------------------------------------------------------ G/H 的稿件与审校


def test_document_citation_to_missing_relation_is_error(store):
    """负控：断言引用了不存在的关系 ⇒ error（悬空引用）。"""
    store.init()
    claim = {"claim_id": "c1", "text": "x", "citations": ["rel:0099"], "evidence_kind": "proof"}
    _document(store, "0000", claims=[claim])
    errs = _issues(store, level="error", kind="dangling_citation")
    assert len(errs) == 1


def test_document_cross_check_without_disclaimer_is_error(store):
    store.init()
    claim = {"claim_id": "c1", "text": "x", "citations": ["lit:0000"],
             "evidence_kind": "cross_check", "disclaimer": ""}
    doc = store.read("documents")
    doc["rows"].append({"doc_id": "0000", "kind": "note", "title": "t", "claims": [claim], "status": "draft"})
    store._atomic_write(store.data / "documents.json", doc)
    assert len(_issues(store, level="error", kind="overclaim")) == 1


def test_finding_without_evidence_is_error(store):
    """负控（本文件最要紧的一条）：审校发现没有 evidence ⇒ error。

    审校者的判断也需要证据 —— 否则审校会变成另一种幻觉的来源，
    而且因为它站在更高的位置，更难被纠正。
    """
    store.init()
    doc = store.read("review_findings")
    doc["rows"].append({"finding_id": "0000", "doc_id": "0000", "kind": "garbled", "level": "info",
                        "target": "c1", "evidence": "", "message": "m", "round": 1, "status": "open"})
    store._atomic_write(store.data / "review_findings.json", doc)
    errs = _issues(store, level="error", kind="finding_without_evidence")
    assert len(errs) == 1


def test_finding_pointing_to_missing_document_is_error(store):
    store.init()
    doc = store.read("review_findings")
    doc["rows"].append({"finding_id": "0000", "doc_id": "0099", "kind": "garbled", "level": "info",
                        "target": "c1", "evidence": "e", "message": "m", "round": 1, "status": "open"})
    store._atomic_write(store.data / "review_findings.json", doc)
    assert len(_issues(store, level="error", kind="dangling_doc_ref")) == 1


def test_accepted_document_with_open_error_finding_is_error(store):
    """负控：稿件 accepted 了，但它还有未处置的 error 级发现 ⇒ error。

    这条是"审校闭环能不能被绕过"的机械保证：修不修都可以，
    但不能一边挂着 error 一边说 accepted。
    """
    store.init()
    add_literature(store, "0000", title="某文献")
    _document(store, "0000", status="accepted")
    _finding(store, "0000", level="error", status="open")
    assert len(_issues(store, level="error", kind="accepted_with_open_error")) == 1


def test_accepted_document_with_fixed_finding_is_clean(store):
    """防误伤：error 级发现已 `fixed` ⇒ 不报。"""
    store.init()
    add_literature(store, "0000", title="某文献")
    _document(store, "0000", status="accepted")
    _finding(store, "0000", level="error", status="fixed")
    assert _issues(store, level="error", kind="accepted_with_open_error") == []


def test_accepted_document_with_wontfix_finding_is_clean(store):
    """防误伤：`wontfix`（带理由）也算已处置 —— 不是所有 error 都必须被修掉。"""
    store.init()
    add_literature(store, "0000", title="某文献")
    _document(store, "0000", status="accepted")
    _finding(store, "0000", level="error", status="wontfix", resolution_note="已知并接受")
    assert _issues(store, level="error", kind="accepted_with_open_error") == []


# ------------------------------------------------------------------ 干净库必须是干净的


def test_fully_clean_workspace_has_no_errors(store):
    """端到端防误伤：一个填了各种合法数据的库必须 0 error。

    没有这一条，上面那些"注入坏数据必须报错"的断言就可以靠"verify 对什么都报错"
    轻松通过 —— 那是假绿灯。
    """
    store.init()
    add_literature(store, "0000", title="某文献", path=None, processed=True)
    add_concept(store, "0000", "K(m)")
    add_concept(store, "0001", "S̃_m")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True)
    _experiment(store, "0000", for_question_id=None)
    _dependency(store, "0000", status="closed", status_reason="", source_experiment_id="0000")
    # 声明为 `cross_check` 而非 `proof`：它引用的实验本身就是 cross_check，
    # 而"断言不能强于它的依据"现在是一条 error（依赖的缺陷继承）。
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "x", "citations": ["exp:0000"],
                                      "evidence_kind": "cross_check",
                                      "disclaimer": "数值交叉验证，不构成证明"}])
    _finding(store, "0000", level="warning", status="open", kind="garbled")
    errs = _issues(store, level="error")
    assert errs == [], [f"{i['table']}/{i['code']}: {i['message'][:120]}" for i in errs]


# ------------------------------------------------------------------ 撤回级联
#
# 来自对本地先例 Danus 的观摩：它有明确的撤回（retraction）语义并强调撤回要级联。
# 我们此前只有行级的 `status="rejected"` / `duplicate_of`，却没有一条检查去问
# "引用了它的那些结论还站得住吗" —— 于是"关系被否决"与"稿件还在拿它当依据"
# 可以长期共存而没有任何报错。下面四条把这条级联钉死。


def test_claim_citing_a_rejected_relation_is_an_error(store):
    """核心：引用了 `status="rejected"` 的关系 ⇒ error（依据已被撤回）。"""
    store.init()
    add_literature(store, "0000", title="L", processed=True)
    add_concept(store, "0000", "K(m)")
    add_concept(store, "0001", "S")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q", status="rejected")
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "x", "citations": ["rel:0000"],
                                      "evidence_kind": "proof"}])
    errs = _issues(store, level="error", kind="citation_to_retracted_relation")
    assert len(errs) == 1
    assert "撤回必须级联" in errs[0]["message"]


def test_claim_citing_a_deduped_relation_is_an_error(store):
    """判重（`duplicate_of` 非空）也是撤回的一种形态 ⇒ 同样 error。"""
    store.init()
    add_literature(store, "0000", title="L", processed=True)
    add_concept(store, "0000", "K(m)")
    add_concept(store, "0001", "S")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q1")
    add_relation(store, "0001", ["0000", "0001"], "0000", quote="q2", duplicate_of="0000")
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "x", "citations": ["rel:0001"],
                                      "evidence_kind": "proof"}])
    errs = _issues(store, level="error", kind="citation_to_retracted_relation")
    assert len(errs) == 1 and "duplicate_of" in errs[0]["message"]


def test_claim_citing_a_suspect_relation_is_only_a_warning(store):
    """分级（FC-13）：`suspect` 是"依据可疑、未判定"，不是"已被撤回" ⇒ warning。

    把这两者报成同一个级别，会让"真的引用了被否决的知识"淹没在噪音里。
    """
    store.init()
    add_literature(store, "0000", title="L", processed=True)
    add_concept(store, "0000", "K(m)")
    add_concept(store, "0001", "S")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q", status="suspect")
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "x", "citations": ["rel:0000"],
                                      "evidence_kind": "proof"}])
    assert _issues(store, level="error", kind="citation_to_retracted_relation") == []
    assert len(_issues(store, level="warning", kind="citation_to_suspect_relation")) == 1


def test_question_based_on_a_retracted_relation_is_a_warning(store):
    """同一类级联作用在 D 的台账上：问题建立在已撤回的依据上 ⇒ warning。

    为什么是 warning 而不是 error：问题还开着不一定错（可能是有意保留以便重查），
    但必须被人看见 —— 这正是"不许静默"的形态。
    """
    store.init()
    add_literature(store, "0000", title="L", processed=True)
    add_concept(store, "0000", "K(m)")
    add_concept(store, "0001", "S")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q", status="rejected")
    with store.tx("research_questions", actor="t") as tx:
        tx.upsert("research_questions", S.ResearchQuestion(
            question_id="0000", question="这条关系成立吗？",
            related_concept_ids=["0000", "0001"], related_relation_ids=["0000"],
            status="researching", created_at=TS, updated_at=TS,
        ).to_dict())
    sync_counters(store)
    assert len(_issues(store, level="warning", kind="question_based_on_retracted_relation")) == 1


# ------------------------------------------------------------------ 依赖的缺陷继承
#
# 来自对本地先例 Danus 的观摩：让"前提不干净"沿着依赖链传播。
# 我们有 `dependencies` 表，缺的只是让它在前提变脏时说话。
# 三条检查，从"最容易被偷偷升级"到"最要紧"依次排。


def test_proof_claim_citing_a_cross_check_experiment_is_an_error(store):
    """核心：断言的证据等级不能强于它的依据。"""
    store.init()
    add_literature(store, "0000", title="L")
    _experiment(store, "0000", evidence_kind="cross_check", result="supports", negation_kind="not_proved")
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "已证明 x", "citations": ["exp:0000"],
                                      "evidence_kind": "proof"}])
    errs = _issues(store, level="error", kind="proof_claim_rests_on_weaker_evidence")
    assert len(errs) == 1 and "不能强于它的依据" in errs[0]["message"]


def test_proof_claim_citing_a_proof_experiment_is_clean(store):
    """防误伤：`proof` 断言引用 `proof` 实验 ⇒ 不报。"""
    store.init()
    add_literature(store, "0000", title="L")
    _experiment(store, "0000", method="formal", evidence_kind="proof",
                verifier_output="lean: no goals", verifier_subject_key="SpecK(m)=[-m,m]",
                result="supports", negation_kind="not_proved")
    _document(store, "0000", claims=[{"claim_id": "c1", "text": "已证明 x", "citations": ["exp:0000"],
                                      "evidence_kind": "proof"}])
    assert _issues(store, level="error", kind="proof_claim_rests_on_weaker_evidence") == []


def test_closed_dependency_on_inconclusive_experiment_is_an_error(store):
    """`closed` 的意思是"这条依赖有支撑"；没跑出结论的实验不是支撑。"""
    store.init()
    add_literature(store, "0000", title="L")
    _experiment(store, "0000", result="inconclusive", negation_kind="no_local_evidence",
                evidence_kind="cross_check")
    _dependency(store, "0000", status="closed", status_reason="", source_experiment_id="0000")
    assert len(_issues(store, level="error", kind="closed_dep_on_inconclusive_experiment")) == 1


def test_proof_claim_with_unclosed_dependency_is_an_error(store):
    """最要紧的一条：拿不到的前提撑不起 `proof` 级的主张。

    这正是论文 `main.pdf` 的形态：Theorem 1.5 的"同谱"一半挂在配套书 [6] 上，
    而那本书拿不到。框架允许"引用拿不到的外部定理"，但必须限制它的后果 ——
    它不能撑起一个 `proof` 级主张（`cross_check` 级则只维持 warning）。
    """
    store.init()
    add_literature(store, "0000", title="L")
    _document(store, "0000", claims=[
        {"claim_id": "c1", "text": "已证明 x", "citations": ["lit:0000"], "evidence_kind": "proof"},
    ])
    _dependency(store, "0000", status="external_unavailable", status_reason="拿不到",
                used_by="doc:0000#c1")
    assert len(_issues(store, level="error", kind="proof_claim_with_unclosed_dependency")) == 1


def test_cross_check_claim_with_unclosed_dependency_stays_a_warning(store):
    """分级（FC-13）：`cross_check` 断言挂在未闭合依赖上只维持 warning。

    把 `proof` 与 `cross_check` 报成同一级，会让"拿不到的前提撑起了已证明的主张"
    这一真问题淹没在正常的引用噪音里。
    """
    store.init()
    add_literature(store, "0000", title="L")
    _document(store, "0000", claims=[
        {"claim_id": "c1", "text": "x", "citations": ["lit:0000"], "evidence_kind": "cross_check",
         "disclaimer": "数值交叉验证，不构成证明"},
    ])
    _dependency(store, "0000", status="external_unavailable", status_reason="拿不到",
                used_by="doc:0000#c1")
    assert _issues(store, level="error", kind="proof_claim_with_unclosed_dependency") == []
    assert len(_issues(store, level="warning", kind="dangling_dep_external")) == 1
