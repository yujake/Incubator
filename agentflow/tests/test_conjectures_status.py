"""T2 的判据：猜想的状态必须配得上它自己举出的证据（依据 `draft/30` §T2）。

T1 判"引用的代号在不在"；这里判"这个结论有没有它自称的那件证据撑着"。
五条码各一条正控 + 各一条注入负控，另有一条"注入无效"自检（改无关字段 ⇒ 不许报）。

两条用例刻意绕过 `validate` 直接写盘（`store._atomic_write`）：`proved` 无
`proof_experiment_id`、`refuted` 无 `counterexample_experiment_id` 这两种形态今天已被
`schema.validate` 挡住，但盘上的历史行与 `rebuild` 重放出来的行不受它管 ——
那两条守的是"判据的第二道防线"（第一道是写入期，第二道是审计期）。
"""
from __future__ import annotations

import json
from pathlib import Path

from agentflow import schema as S
from agentflow import verify as V
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"

#: 一条合法猜想（默认 `proposed`，各用例只覆盖它需要的字段）。
GOOD = {
    "conjecture_id": "0000",
    "statement": "对一切 m，谱落在区间 [-m, m] 内。",
    "form": "universal",
    "testable": {"params": {"m": [2, 3, 4]}, "why": "逐 m 数值可判"},
    "origin": "report:0001",
    "status": "proposed",
}


def _store(tmp_path: Path) -> Store:
    """初始化过的临时工作区。"""
    st = Store(tmp_path)
    st.init()
    return st


def _experiment(st: Store, eid: str, **patch) -> dict:
    """写一条实验（schema 硬约束照走）。"""
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
    base.update(patch)
    row = S.Experiment(**base)
    row.validate()
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    return row.to_dict()


def _proof_experiment(st: Store, eid: str) -> dict:
    """一条真正合规的形式化证明实验（`method=formal` + `evidence_kind=proof` + 非空输出）。"""
    return _experiment(st, eid, method="formal", evidence_kind="proof",
                       verifier_subject_key="SpecK(m)=[-m,m]",
                       verifier_output="Lean 4.7.0: no goals to be solved")


def _refutes_experiment(st: Store, eid: str) -> dict:
    """一条合规的反例实验（`result=refutes` 必须带 counterexample，且不得自称 proof）。"""
    return _experiment(st, eid, method="numeric", evidence_kind="cross_check",
                       result="refutes", negation_kind="disproved",
                       counterexample={"kind": "counterexample", "m": 7, "value": "越界"})


def _doc(st: Store, doc_id: str, claims: list[dict]) -> dict:
    """写一份带断言的稿件（`evidence_kind=proof` 的断言必须引 `exp:` 证据锚）。"""
    row = S.Document(doc_id=doc_id, kind="paper", title="稿", sections=[], claims=claims,
                     created_at=TS)
    row.validate()
    with st.tx("documents", actor="test") as tx:
        tx.upsert("documents", row.to_dict())
    return row.to_dict()


def _closed_dep(st: Store, dep_id: str, eid: str, **patch) -> dict:
    """一条已闭合、证据侧指向某实验的依赖。"""
    base = dict(dep_id=dep_id, used_by=f"doc:0000#{dep_id}", kind="experiment",
                label="由该实验支撑", status="closed", source_experiment_id=eid, created_at=TS)
    base.update(patch)
    row = S.Dependency(**base)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict())
    return row.to_dict()


def _conj(st: Store, **patch) -> dict:
    """把一条猜想直接写进表（绕开工具层，专测 verify）。"""
    row = {**GOOD, **patch}
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", row)
    return row


def _raw_conj(st: Store, row: dict) -> None:
    """绕过 `validate` 直接落盘一行（模拟历史行 / `rebuild` 重放出来的行）。"""
    path = st.data / "conjectures.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"] = [*doc.get("rows", []), row]
    st._atomic_write(path, doc)


def _codes(st: Store) -> list[str]:
    """`verify_all` 就 `conjectures` 表报出的判据码（排序后）。"""
    return sorted(i.code for i in V.verify_all(st).issues if i.table == "conjectures")


def _only(st: Store, code: str) -> None:
    """断言恰好只有这一个码（注入负控必须只咬该咬的那一条）。"""
    got = _codes(st)
    assert got == [code], f"期望恰好 ['{code}']，实得 {got}"


# ---------------------------------------------------------------- ① proved

def test_positive_proved_with_a_formal_proof_is_clean(tmp_path: Path):
    """正控：`proved` 挂着真正的形式化证明（formal + proof + 非空检查器输出）⇒ 一条都不报。"""
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _conj(st, status="proved", experiment_ids=["0000"], proof_experiment_id="0000")
    assert _codes(st) == []


def test_negative_proved_on_a_cross_check_is_not_a_proof(tmp_path: Path):
    """注入：把证明实验的 `evidence_kind` 从 `proof` 改成 `cross_check`（schema 合法）⇒ 必须咬。

    `method=numeric` + `evidence_kind=proof` 这种更露骨的形态已被 `Experiment.validate`
    挡住（FC-22 的写入期判据），所以这里注入的是写入期判不出来的那一种：
    行本身合法，但它不是一个证明。
    """
    st = _store(tmp_path)
    _experiment(st, "0000", method="formal", evidence_kind="cross_check",
                verifier_subject_key="SpecK(m)=[-m,m]", verifier_output="Lean: ok")
    _conj(st, status="proved", experiment_ids=["0000"], proof_experiment_id="0000")
    _only(st, "proved_without_formal_proof")


def test_negative_proved_without_any_proof_id_bites_even_past_validate(tmp_path: Path):
    """注入（绕过写入期）：盘上一行 `proved` 却没有任何证明实验 ⇒ 审计期仍必须咬。

   实测同时报两条：`schema_invalid`（`verify` 自己也会拿 `schema` 逐行复验 —— 这是
    第三道防线）与本条目的 `proved_without_formal_proof`。两条都要在：
    前者说"这一行不合 schema"，后者说"这个状态没有证据撑着"，是两件事。
    """
    st = _store(tmp_path)
    _raw_conj(st, {**GOOD, "status": "proved"})
    assert _codes(st) == ["proved_without_formal_proof", "schema_invalid"]


# ---------------------------------------------------------------- ② promoted

def _promotion_fixture(st: Store) -> None:
    """一条完整合法升格链：猜想 →(`promoted_to`) 断言 →(`citations`) proof 实验 →(依赖) 闭合。"""
    _proof_experiment(st, "0000")
    _doc(st, "0000", [{"claim_id": "C1", "text": "谱在区间内。", "evidence_kind": "proof",
                       "citations": ["exp:0000"]}])
    _closed_dep(st, "0000", "0000")
    _conj(st, status="promoted", experiment_ids=["0000"], proof_experiment_id="0000",
          promoted_to={"kind": "document_claim", "id": "0000#C1"})


def test_positive_promotion_on_a_closed_chain_is_clean(tmp_path: Path):
    """正控：两跳都真（断言是 proof 断言、引了那个实验，依赖已闭合）⇒ 不报。"""
    st = _store(tmp_path)
    _promotion_fixture(st)
    assert _codes(st) == []


def test_negative_promotion_whose_claim_does_not_cite_the_proof_bites(tmp_path: Path):
    """注入：把升格断言的 `citations` 从 `exp:0000` 换成一个无关引文 ⇒ 必须咬。"""
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _doc(st, "0000", [{"claim_id": "C1", "text": "谱在区间内。", "evidence_kind": "proof",
                       "citations": ["rel:0000"]}])
    _closed_dep(st, "0000", "0000")
    _conj(st, status="promoted", experiment_ids=["0000"], proof_experiment_id="0000",
          promoted_to={"kind": "document_claim", "id": "0000#C1"})
    _only(st, "promoted_without_closed_dep")


def test_negative_promotion_on_a_dangling_dependency_bites(tmp_path: Path):
    """注入：依赖还在，但状态不是 `closed` ⇒ 第二跳不成立，必须咬。"""
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _doc(st, "0000", [{"claim_id": "C1", "text": "谱在区间内。", "evidence_kind": "proof",
                       "citations": ["exp:0000"]}])
    _closed_dep(st, "0000", "0000", status="dangling", status_reason="还没拿到原文")
    _conj(st, status="promoted", experiment_ids=["0000"], proof_experiment_id="0000",
          promoted_to={"kind": "document_claim", "id": "0000#C1"})
    _only(st, "promoted_without_closed_dep")


def test_negative_promotion_onto_a_cross_check_claim_bites(tmp_path: Path):
    """注入：升格落点的断言是 `cross_check`（不是 proof）⇒ 必须咬。"""
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _doc(st, "0000", [{"claim_id": "C1", "text": "谱在区间内。", "evidence_kind": "cross_check",
                       "citations": ["exp:0000"], "disclaimer": "仅为交叉核对，不是证明。"}])
    _closed_dep(st, "0000", "0000")
    _conj(st, status="promoted", experiment_ids=["0000"], proof_experiment_id="0000",
          promoted_to={"kind": "document_claim", "id": "0000#C1"})
    _only(st, "promoted_without_closed_dep")


# ---------------------------------------------------------------- ③ refuted

def test_positive_refuted_with_a_counterexample_is_clean(tmp_path: Path):
    """正控：`refuted` 挂着一个真的反例实验（`result=refutes` + counterexample）⇒ 不报。"""
    st = _store(tmp_path)
    _refutes_experiment(st, "0000")
    _conj(st, status="refuted", experiment_ids=["0000"], counterexample_experiment_id="0000")
    assert _codes(st) == []


def test_negative_refuted_on_an_inconclusive_experiment_bites(tmp_path: Path):
    """注入：反例实验的 `result` 从 `refutes` 改成 `inconclusive` ⇒ 必须咬。

    三态纪律：没查成 ≠ 查过了、被否证。`inconclusive` 不得转 `refuted`。
    """
    st = _store(tmp_path)
    _experiment(st, "0000", result="inconclusive", negation_kind="not_proved")
    _conj(st, status="refuted", experiment_ids=["0000"], counterexample_experiment_id="0000")
    _only(st, "refuted_without_counterexample")


def test_negative_refuted_without_any_counterexample_id_bites_past_validate(tmp_path: Path):
    """注入（绕过写入期）：盘上一行 `refuted` 却没有反例实验号 ⇒ 审计期仍必须咬。

    同上一族：`schema_invalid`（`schema.validate` 的第三道防线）与本条目的
    `refuted_without_counterexample` 会同时出现，两条都要在。
    """
    st = _store(tmp_path)
    _raw_conj(st, {**GOOD, "status": "refuted"})
    assert _codes(st) == ["refuted_without_counterexample", "schema_invalid"]


# ---------------------------------------------------------------- ④ supported / ⑤ 冲突

def test_positive_supported_not_proved_with_a_supporting_experiment_is_clean(tmp_path: Path):
    """正控：`supported_not_proved` + 一个 `result=supports` 的实验 ⇒ 不报。"""
    st = _store(tmp_path)
    _experiment(st, "0000")
    _conj(st, status="supported_not_proved", experiment_ids=["0000"])
    assert _codes(st) == []


def test_negative_supported_not_proved_without_any_support_bites(tmp_path: Path):
    """注入：把实验的 `result` 从 `supports` 改成 `inconclusive` ⇒ 必须咬。"""
    st = _store(tmp_path)
    _experiment(st, "0000", result="inconclusive", negation_kind="not_proved")
    _conj(st, status="supported_not_proved", experiment_ids=["0000"])
    _only(st, "supported_without_support")


def test_negative_status_conflicting_with_a_listed_refuter_bites(tmp_path: Path):
    """注入：猜想列出的一条实验结果是 `refutes`，而状态自称成功 ⇒ 必须咬。

    这一条同时带一个 supports 实验，好让 ④ 成立 —— 于是咬的只能是 ⑤ 这一条。
    """
    st = _store(tmp_path)
    _experiment(st, "0000")
    _refutes_experiment(st, "0001")
    _conj(st, status="supported_not_proved", experiment_ids=["0000", "0001"])
    _only(st, "status_conflicts_with_experiment")


def test_injection_that_changes_nothing_relevant_does_not_bite(tmp_path: Path):
    """注入无效自检：改一个与被测码无关的字段（实验的 notes）⇒ 五条码一条都不许出现。

    没有这一条，上面那些负控可能是"任何改动都报"而非"这条判据在报"。
    """
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _conj(st, status="proved", experiment_ids=["0000"], proof_experiment_id="0000")
    assert _codes(st) == []
    _experiment(st, "0000", method="formal", evidence_kind="proof",
                verifier_subject_key="SpecK(m)=[-m,m]", verifier_output="Lean 4.7.0: no goals to be solved",
                notes="这次只加了一句备注")
    assert _codes(st) == []


def test_five_legal_states_coexist_in_one_store(tmp_path: Path):
    """正控（合）：五个状态各自合法地共处一库 ⇒ `conjectures` 表上一条都不报。

    这条守的是"判据之间不互相误伤"：② 的第二跳要扫 `dependencies`、⑤ 要扫
    `experiment_ids`，任一处的实现写歪都会在这里同时炸出好几条。
    """
    st = _store(tmp_path)
    _proof_experiment(st, "0000")
    _experiment(st, "0001")
    _refutes_experiment(st, "0002")
    _doc(st, "0000", [{"claim_id": "C1", "text": "谱在区间内。", "evidence_kind": "proof",
                       "citations": ["exp:0000"]}])
    _closed_dep(st, "0000", "0000")
    _conj(st, conjecture_id="0000", status="proved", experiment_ids=["0000"],
          proof_experiment_id="0000")
    _conj(st, conjecture_id="0001", status="promoted", experiment_ids=["0000"],
          proof_experiment_id="0000", promoted_to={"kind": "document_claim", "id": "0000#C1"})
    _conj(st, conjecture_id="0002", status="supported_not_proved", experiment_ids=["0001"])
    _conj(st, conjecture_id="0003", status="refuted", experiment_ids=["0002"],
          counterexample_experiment_id="0002")
    _conj(st, conjecture_id="0004", status="proposed")
    assert _codes(st) == []
