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
    # T4-A：每一行稿件都带内容哈希（G 的写侧口径是"每次写都钉"，不是只在 accepted 时补）。
    # 这个夹具扮演写侧，所以它照做；"accepted 却没有哈希"那种形态由
    # tests/test_internal_citations.py 直接构造行来测（不在这里被夹具顺手补上）。
    if not base.get("content_sha256"):
        from agentflow import signatures as _SIG

        base["content_sha256"] = _SIG.content_sha256_of(base)
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


# ------------------------------------------------------------------ 引用前缀词表（`D10`）


def _claim_with(citations: list[str]) -> dict:
    return {"claim_id": "c1", "text": "K(m) 是 m-正则的。", "citations": list(citations),
            "evidence_kind": "heuristic"}


def _eval_row(store, eid: str = "0000") -> None:
    """插一条字段齐全的评测结果（`eval:` 引用要能解析到它，否则会先报悬空引用）。"""
    row = S.EvalResult(
        eval_id=eid, claim_key="k", benchmark="miniF2F", benchmark_version="v1",
        split="test", k=1, value=0.5, decontamination="none",
        date="2026-01-01", source="self", created_at=TS,
    )
    row.validate()
    with store.tx("eval_results", actor="test") as tx:
        tx.upsert("eval_results", row.to_dict())
    sync_counters(store)


def test_unknown_citation_kind_message_lists_every_declared_prefix(store):
    """`D10` 正控：拒绝消息里的受控词表必须与判据元组双向包含。

    现状（`D10` 登记，登记册 :819-824）：判据收 `("rel","lit","exp","eval")` 四档，
    而消息写的是"应为 rel:/lit:/exp:" —— 漏了 `eval:`，而 `eval:` 正是上一行
    刚被单独检查过的那一档。调用方按消息改写法，会把一个合法的 `eval:` 引用
    当成非法引用。修法是让消息从判据元组派生（`FC-03`），这条断言就打在
    "两处逐字一致"上，所以它对任一方向的漂移都红：消息多写一档也红。

    期望词表在这里逐字写死（不从 `verify.CITATION_KINDS` 取）：判据要能回答
    "消息把人引向哪个写法"，而那个答案不该由被测对象自己提供 —— 从被测对象取
    词表会让"两边一起改错"照样绿。

    `stmt`（`R-03` / `draft/49` 裁"方案 A"）是后来补进来的第六档：命题台账也是可引的
    对象，而加它之前写入期会把 `stmt:0004` 这类合法引用判成"前缀无法识别"
    （`draft/49:868` 逐字："比不查更糟"）。补一档就要同轮改这里的逐字清单 ——
    它逐字写死正是为了拦住"词表变了而消息没跟上"。
    """
    expected_kinds = ("rel", "lit", "exp", "eval", "doc", "stmt")
    add_literature(store, "0000", title="某文献")
    _eval_row(store)
    _document(store, "0000", claims=[_claim_with(["lit:0000", "eval:0000", "foo:0000"])])

    ws = _issues(store, level="warning", kind="unknown_citation_kind")
    assert len(ws) == 1, ws
    msg = ws[0]["message"]
    for k in expected_kinds:
        assert f"{k}:" in msg, f"消息里少了合法前缀 {k!r}：{msg!r}"
    # 反向：消息里推荐的那一串前缀不许有词表之外的（多写一档同样是错的指引）。
    # 只看"应为 ..."那一节，不把被拒绝的那个引用本身算进来（它当然不在词表里）。
    import re as _re

    tail = msg.split("应为", 1)[-1]
    mentioned = set(_re.findall(r"\b([a-z]+):", tail))
    assert mentioned == set(expected_kinds), (
        f"消息推荐的前缀集合 {sorted(mentioned)} 与判据词表 {sorted(expected_kinds)} 不等 —— "
        "两处各写一份字面量就会这样漂（`D10`）"
    )
    # 正控的另一半：合法的 `eval:` 引用本身不许被判成未知前缀
    assert ws[0]["message"].count("foo:0000") == 1, "被拒绝的应该只有那个真未知的前缀"


def test_negative_control_the_old_message_would_be_caught(store):
    """`D10` 负控：把消息改回改前的字面量形态 ⇒ 上面那条判据必红。

    这里不重新实现一遍判据，而是逐字复算改前的那句话（`git show HEAD` 的
    `verify.py` 里那一行）并证明它在"每个前缀都在消息里"这一条上失败 ——
    也就是说上面那条断言真的能抓住这个缺陷，而不是碰巧绿。
    本用例只在当前实现下跑（它引用 `verify.CITATION_KINDS`），
    负控那一边由 `temp/batchL-probe.py` 的 D10 项负责。
    """
    add_literature(store, "0000", title="某文献")
    _document(store, "0000", claims=[_claim_with(["lit:0000", "foo:0000"])])
    ws = _issues(store, level="warning", kind="unknown_citation_kind")
    assert len(ws) == 1, ws

    old_message = "断言 c1 的引用 'foo:0000' 前缀无法识别（应为 rel:/lit:/exp:）"
    from agentflow.verify import CITATION_KINDS

    missing = [k for k in CITATION_KINDS if f"{k}:" not in old_message]
    # `T4-A` 把 `doc:` 加进词表之后，这句"改前的话"还多漏一档 —— 它当然漏：
    # 那句话写下时 `doc:` 这一档根本不存在。夹具的意图是"它确实漏了东西"，
    # 所以这里逐字列出漏项，而不是放宽成"漏了就都行"。
    # `R-03` 补 `stmt` 之后漏项再多一个 —— 同一个道理：那句话写下时 `stmt:` 也不存在。
    # 逐字列出（而不是 `len(missing) >= 2`）正是为了让"又补了一档"必须有人来改这一行。
    assert missing == ["eval", "doc", "stmt"], f"夹具算错了：{missing}"
    # 改前的那句话在当前的判据下必红 —— 而当前实现给的那句话不红
    assert all(f"{k}:" in ws[0]["message"] for k in CITATION_KINDS)
    assert "eval:" not in old_message, "改前形态确实漏了 eval:（D10 的现状）"


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


# ---------------------------------------------------------------- P-5：引用解析只有一份实现


def test_citation_ref_parts_has_exactly_one_implementation():
    """正控（`P-5`）：`doc_tools` 的入口与 `textutil` 的实现是同一个函数，逐字同结果。

    改前这是两份实现（`verify.py` 内联 + `doc_tools` 抄一份）。判据不只"结果相同"，
    而是"同一个对象" —— 结果相同可以由两份碰巧一致的实现造成，那正是漂移的前夜。
    """
    from agentflow import textutil as T
    from agentflow.tools import doc_tools as DT

    assert DT.citation_ref_parts is not T.citation_ref_parts, "转发体本身不该是同一个对象"
    # 但转发体必须只做转发（R003 的转发判据同款）：调用结果逐字相同。
    inputs = [
        "rel:0001#claim-1", "rel:0001", "lit:0002#c", "exp:0003#x#y", "eval:0004",
        "noColon", "", ":", ":0001", "rel:", "rel:#frag", "rel:00:01#c",
        "  rel:0001#c  ", "rel:0001#", "rel:0001#c#d", 123, None,
    ]
    for inp in inputs:
        # `verify.py` 改前那份内联口径作为第三方参照，逐字比对。
        k, _, r = str(inp).partition(":")
        assert T.citation_ref_parts(inp) == (k, r.split("#")[0]) == DT.citation_ref_parts(inp), inp
    # 单点语义：`#` 之后是断言内的锚点，不参与"代号存不存在"的判定。
    assert T.citation_ref_parts("rel:0001#claim-9") == ("rel", "0001")


def test_negative_control_breaking_the_one_implementation_reddens_both_entries(store, monkeypatch):
    """负控（`P-5`）：把唯一实现改坏 ⇒ 两个入口同时变红。

    只有一个红就说明还有第二份实现没接上。这里注入的是"忘了剥掉 `#` 锚点" ——
    正是 `rel:0001#claim-9` 这类真实引文会踩到的分支。

    两个入口分别是：
    - 工具层 `doc_tools.citation_ref_parts`（G 写稿时用的那个）；
    - `verify_all` 的悬空引用检查（审计时用的那个）。
    """
    from agentflow import textutil as T
    from agentflow.tools import doc_tools as DT

    store.init()
    add_concept(store, "0000", "k")
    add_concept(store, "0001", "S")
    add_literature(store, "0000", title="L")
    add_relation(store, "0000", ["0000", "0001"], "0000")
    claim = {"claim_id": "c1", "text": "x", "citations": ["rel:0000#claim-1"],
             "evidence_kind": "proof"}
    _document(store, "0000", claims=[claim])
    # 正控的一半：口径正确时，`rel:0000#claim-1` 指向存在的关系 0000 ⇒ 不报悬空。
    assert _issues(store, level="error", kind="dangling_citation") == []

    def broken(citation):
        # 注入：不做 split("#")[0]，于是 ref 变成 "0000#claim-1" ⇒ 查不到那一行。
        kind, _, ref = str(citation).partition(":")
        return kind, ref

    monkeypatch.setattr(T, "citation_ref_parts", broken)
    # 入口一：工具层转发体跟着坏掉（它是转发，所以必然跟着）。
    assert DT.citation_ref_parts("rel:0000#claim-1") == ("rel", "0000#claim-1")
    # 入口二：审计那条路也必须跟着红 —— 只有一个红就说明还有第二份实现。
    errs = _issues(store, level="error", kind="dangling_citation")
    assert len(errs) == 1, f"注入坏掉唯一实现后，verify 那条路没有跟着变红：{errs}"


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
    """防误伤：`proof` 断言引用 `proof` 实验 ⇒ 不报。

    夹具处置（`R2-AN-2`）：这条 proof 行的 `verifier_output` 从前是
    `"lean: no goals"` —— 没有绑定被检查声明名的诊断，而它标着 `proof`，
    那是夹具在说假话。本用例只筛 `proof_claim_rests_on_weaker_evidence`，
    所以变严的 `selfreported_proof` 判据并没有红它；但夹具仍然要写成
    检查器真跑过时的绑名形态（`draft/28` §41.4：改夹具，不许放宽判据）。
    这里的 `claim_key` 是一句人读的数学键（不是 Lean 标识符），
    且本行没有 `notes`（没有"声明名"那一段）⇒ 审计退回 `verifier_subject_key`。
    """
    store.init()
    add_literature(store, "0000", title="L")
    _experiment(store, "0000", method="formal", evidence_kind="proof",
                verifier_output="'SpecK(m)=[-m,m]' does not depend on any axioms",
                verifier_subject_key="SpecK(m)=[-m,m]",
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


# ============================================ `R2-AN-2`：proof 行的"绑名诊断"判据
#
# `E-2` 的 `selfreported_proof` 原来是子串判据（`verifier_subject_key in
# verifier_output`），两个方向都不严（`draft/28` §40.3 的 A1/A4 读数）：
#   - 太宽：`claim_key='L'` 是 `'Lean4: no goals'` 的子串 ⇒ 一条完全自报的 proof 不报；
#     名字只出现在一句与结论无关的告警里也算"检查器管过它"。
#   - 太窄（更危险）：不能绑 `claim_key` —— 生产路径上它与 Lean 声明名可以合法地
#     不同（`tests/test_agent_e_formal_path.py` 的正控：`claim_key='probe-eq'`、
#     Lean 声明 `probe_eq`，Lean 标识符不许带连字符）。
# 新判据绑 `notes` 里那个被检查的声明名（写入点 `agent_e._declared_name_note`），
# 并要求输出里有绑名的结构化诊断（读法只有 `formalgw.concluded_names` 一处）。
#
# 下面五条守两个方向：① 合规行不许报（尤其是 `claim_key ≠ 声明名` 那一条，
# 照 R2 的字面建议改会红掉它）；② 自报行必须报（含"名字只在无关注警里"那一形态）。


def _proof_row(store, eid: str, *, claim_key: str, verifier_output: str, notes: str = "",
               subject: str | None = None) -> None:
    """写一条 `method="formal"` + `evidence_kind="proof"` 的行（schema 硬约束照走）。"""
    _experiment(store, eid, method="formal", evidence_kind="proof",
                claim_key=claim_key, verifier_subject_key=subject or claim_key,
                verifier_output=verifier_output, notes=notes,
                result="supports", negation_kind="not_proved")


#: `agent_e._record_formal` 真写出来的那一段（形态与分词都照它）。
_NOTES_PROBE = ("[formal] 检查器状态 'verified'（本层受控理由 verified）；"
                "声明名 probe_eq；脚本 proofs/probe_eq.lean（sha256 前 16 位 deadbeef）；"
                "imports=[]")


def test_proof_row_bound_to_the_declared_name_in_notes_is_clean(store):
    """正控（`R2-AN-2`）：`claim_key` 与 Lean 声明名不同时也不许报。

    这条用例就是 §41.1 说的"判据过窄 ⇒ 红掉合规输入"的防线：本行的
    `claim_key='probe-eq'` 而检查器检查的声明名是 `probe_eq`，
    输出里只有 `probe_eq`。任何把判据绑到 `claim_key` 上的实现
    （包括旧的子串判据）都会在这里红 —— 而这是一条完全合规的行。
    """
    store.init()
    _proof_row(store, "0000", claim_key="probe-eq", notes=_NOTES_PROBE,
               verifier_output="'probe_eq' does not depend on any axioms")
    errs = _issues(store, level="error", kind="selfreported_proof")
    assert errs == [], f"合规的形式化 proof 行被误判成自报：{errs}"


def test_proof_row_whose_output_binds_the_claim_key_instead_is_reported(store):
    """负控（`R2-AN-2` 的反方向）：输出绑的是 `claim_key`、不是被检查的声明名 ⇒ 必须报。

    与上一条配对，证明判据真的绑在声明名上（而不是"两个名字随便哪一个命中就行"）。
    为什么这算缺陷而不是误伤：Lean 的标识符不许带连字符，
    所以 `'probe-eq' does not depend on any axioms` 这句话不可能是检查器为
    `probe_eq` 打印的诊断 —— 它说明这条输出来自别处。
    """
    store.init()
    _proof_row(store, "0000", claim_key="probe-eq", notes=_NOTES_PROBE,
               verifier_output="'probe-eq' does not depend on any axioms")
    errs = _issues(store, level="error", kind="selfreported_proof")
    assert len(errs) == 1 and "probe_eq" in errs[0]["message"], errs


def test_proof_row_without_any_bound_diagnostic_is_reported(store):
    """负控（`R2-AN-2` ①）：输出里根本没有绑名诊断 ⇒ 必须报（旧子串判据放行的那一条）。

    `"Lean4: no goals"` 这类自报输出里没有声明名 —— 行却标着 `proof`，
    所以它被报不是误伤，而是判据终于开始读"依据"。
    """
    store.init()
    _proof_row(store, "0000", claim_key="probe-eq", notes=_NOTES_PROBE,
               verifier_output="Lean4: no goals")
    errs = _issues(store, level="error", kind="selfreported_proof")
    assert len(errs) == 1 and "probe_eq" in errs[0]["message"], errs


def test_proof_row_whose_name_only_appears_in_an_unrelated_warning_is_reported(store):
    """负控（`R2-AN-2` ②）：名字只在无关注警里出现 ⇒ 必须报。

    `'probe_eq'` 出现在 `warning: unused variable 'probe_eq'` 里，
    与"检查器对这条声明下过公理结论"无关。旧子串判据会把它读成"检查器管过它"。
    """
    store.init()
    _proof_row(store, "0000", claim_key="probe-eq", notes=_NOTES_PROBE,
               verifier_output="Lean4: warning: unused variable 'probe_eq'; no goals")
    errs = _issues(store, level="error", kind="selfreported_proof")
    assert len(errs) == 1, errs


def test_proof_row_without_the_declared_name_falls_back_to_the_subject_key(store):
    """三态（`R2-AN-2`）：`notes` 里读不到声明名（历史行/手工行）⇒ 退回 `verifier_subject_key`。

    两个方向都要读出来：
    - 输出绑的正是本行声称的 `verifier_subject_key` ⇒ 不报（退回这一档不能变成恒报）；
    - 输出绑的是别人的名字 ⇒ 报（退回这一档也不能变成恒不报）。
    """
    store.init()
    _proof_row(store, "0000", claim_key="probe-eq",
               verifier_output="'probe-eq' does not depend on any axioms")
    assert _issues(store, level="error", kind="selfreported_proof") == []
    _proof_row(store, "0001", claim_key="other",
               verifier_output="'probe-eq' does not depend on any axioms")
    errs = _issues(store, level="error", kind="selfreported_proof")
    assert len(errs) == 1 and errs[0]["row_id"] == "0001", errs


def test_the_bound_diagnostic_reader_has_a_single_definition():
    """`FC-03`：绑名诊断的读法只有 `formalgw.concluded_names` 一处，审计从它取。

    判据要读"输出里有没有绑名诊断"，这件事只许有一个定义：
    在这里再写一份正则，两份判据早晚会漂移，而漂移的症状是审计静默放过。
    """
    import agentflow.formalgw as FG
    import agentflow.verify as V

    assert V.concluded_names is FG.concluded_names


def test_negative_control_a_counter_without_a_table_is_checked_not_silently_skipped(
    monkeypatch: pytest.MonkeyPatch, store
) -> None:
    """负控（`FINAL-R4-03`）：`ID_COUNTERS` 里某个 `id_field` 在 `TABLES` 里找不到表时，
    `verify_all` 必须把这一项记成没查成（`checked[kind] is None` + 一条 warning），
    而不是静默少查一项还报通过。

    这一支此前零测试覆盖（`grep -c counter_table_missing tests/*.py` = 0），
    而它正是"将来某次 schema 改名只改了 `ID_COUNTERS`"时唯一的报警器。
    注入方式是 monkeypatch 那张受控表（不动 `schema.py` 的字节）。

    装置自控：先证明未注入时这个键根本不在 `checked` 里（这一支只在缺表时写键）。

    注意判据用 `in` 而不是 `.get()`：`checked` 里"键不在"与"键在但值是 None"是两件事，
    而 `.get()` 会把它们折成一个 None —— 正是这一支要防的那种折平。
    """
    kind = "experiment"
    assert kind not in verify_all(store).checked, (
        "装置自控失败：未注入时这个键本来就出现在 checked 里 ⇒ 这条负控测不到东西"
    )

    tampered = dict(S.ID_COUNTERS)
    tampered[kind] = "no_such_id_field_xyz"
    monkeypatch.setattr(S, "ID_COUNTERS", tampered, raising=True)

    rep = verify_all(store)
    assert kind in rep.checked, (
        f"找不到对应表时这一项必须显式写进 checked（键在、值为 None）表示'没查成'；"
        f"实际 checked 里没有这个键：{sorted(rep.checked)}"
    )
    assert rep.checked[kind] is None, rep.checked[kind]
    issues = _issues(store, kind="counter_table_missing")
    assert issues, "必须留一条 counter_table_missing 的 issue —— 沉默少查一项才是最坏的形态"
    assert issues[0]["level"] == "warning", issues[0]
    assert kind in str(issues[0].get("row_id") or issues[0]), issues[0]
