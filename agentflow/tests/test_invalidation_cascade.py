# -*- coding: utf-8 -*-
"""I1 级联作废 + I4 `trusted`（不重验）（`draft/39` §3.21 二，用户 2026-10-05 裁定采纳）。

## I1 为什么必须有

五元位是逐条命题的读数，而命题之间有依赖（`derived_from`）。一条命题被真反例作废之后，
引用它的那些证明并不会自动失效 —— 除非有人手动去改。于是"作废"只对那一条生效，
而下游的"预备定理级"照旧挂在那里，读起来像是它们还站着。I1 就是那条闭包：
A 作废 ⇒ 引 A 的 B 的五位一并失效 ⇒ 引 B 的 C 也一样，且每一行都记着"根是谁"。

## I4 为什么必须有

"引用命题 ⇒ 第 2+3 位真"（§3.15 三）说的是怎么给凭据；I4 说的是什么时候不必再核：
来源已经验证过的（我方的预备定理级/正式定理、逐字核过的引用命题），引用它时如实呈现、不重验。
这一层把它做成一个干净集合：不在集合里的引用（还在猜想 / 已作废 / 没逐字核过）要小心 ——
而 `attackround.inherit_defects`（I11）正是拿这个集合判"这一步有没有继承缺陷"。
"""
from __future__ import annotations

from agentflow import attackround as AR
from agentflow import evidencebits as EB


def _own(stmt_id: str, *, deps: list[str] | None = None, graded: bool = False) -> dict:
    row: dict = {"stmt_id": stmt_id, "origin": "own_result", "derived_from": list(deps or [])}
    if graded:
        row["bits"] = {"proof": True, "reviewed": True,
                       "evidence": {"proof_process": f"{stmt_id} 的逐步论证",
                                    "reviewed_by": {"round": "V-0001", "verdict": "成立"}}}
    return row


def _citation(stmt_id: str, *, verified: bool = True) -> dict:
    return {"stmt_id": stmt_id, "origin": "external_lit", "source_lit_id": "0009",
            "quote_verified": verified, "quote_reason": "已逐字比对" if verified else "还没核"}


# ============================================================ I1 级联

def test_i1_the_cascade_reaches_transitive_dependents():
    """I1 正控：A 作废 ⇒ 引 A 的 B 失效 ⇒ 引 B 的 C 也失效（闭包逐层扩）。"""
    rows = [_own("0001"), _own("0002", deps=["0001"], graded=True), _own("0003", deps=["0002"]),
            _own("0004")]
    got = EB.cascade_void(rows, root="0001")
    assert got["dependents"] == ["0002", "0003"], got
    assert got["voided_by"]["0003"]["via"] == "0002", got["voided_by"]
    assert got["voided_by"]["0002"]["root"] == "0001", got["voided_by"]
    assert got["missing"] == [] and got["cycles"] == [], got
    out, _ = EB.apply_cascade(rows, root="0001")
    grades = {r["stmt_id"]: EB.bits_from_row(r)["grade"] for r in out}
    assert grades == {"0001": "conjecture", "0002": "conjecture",
                      "0003": "conjecture", "0004": "conjecture"}, grades
    # 不相干的那一条（0004）不许被顺手改：它本来就是"猜想"，而且它没有 voided_by
    unrelated = next(r for r in out if r["stmt_id"] == "0004")
    assert not EB.bits_from_row(unrelated).get("voided_by"), unrelated


def test_i1_the_dependent_loses_its_pre_theorem_grade():
    """I1 的要点：作废前那条是预备定理级，级联之后掉回"猜想"（证据链断了）。"""
    rows = [_own("0001"), _own("0002", deps=["0001"], graded=True)]
    before = {r["stmt_id"]: EB.bits_from_row(r)["grade"] for r in rows}
    assert before["0002"] == "pre_theorem", before
    out, _ = EB.apply_cascade(rows, root="0001")
    after = {r["stmt_id"]: EB.bits_from_row(r)["grade"] for r in out}
    assert after["0002"] == "conjecture", after
    # 作废是"读数失效"，不是"改写内容"：证明过程与审校记录都还在
    bits = EB.bits_from_row(next(r for r in out if r["stmt_id"] == "0002"))
    assert bits["evidence"]["proof_process"], bits
    assert bits["evidence"]["reviewed_by"], bits


def test_i1_cycles_do_not_hang_the_judge():
    """边界：A 引 B 且 B 引 A（外加 C 引 A）—— 闭包不许卡死，环本身要留读数。"""
    rows = [_own("0001", deps=["0002"]), _own("0002", deps=["0001"]), _own("0003", deps=["0001"])]
    got = EB.cascade_void(rows, root="0001")
    assert set(got["dependents"]) == {"0002", "0003"}, got
    assert got["cycles"], "环要被记下来（它是数据面的缺陷读数，不是崩溃）"


def test_i1_a_diamond_is_not_a_cycle():
    """反真空：菱形依赖（A←B、A←C、B←D、C←D）不是环 —— 不许误报。"""
    rows = [_own("0001"), _own("0002", deps=["0001"]), _own("0003", deps=["0001"]),
            _own("0004", deps=["0002", "0003"])]
    got = EB.cascade_void(rows, root="0001")
    assert set(got["dependents"]) == {"0002", "0003", "0004"}, got
    assert got["cycles"] == [], got


def test_i1_a_dangling_reference_is_reported_but_does_not_stop_the_walk():
    """三态：引了一条不在册的 id ⇒ 记进 `missing`，闭包照旧走完。"""
    rows = [_own("0001"), _own("0002", deps=["0001", "9999"]), _own("0003", deps=["0002"])]
    got = EB.cascade_void(rows, root="0001")
    assert got["dependents"] == ["0002", "0003"], got
    assert got["missing"] == ["0002→9999"], got


def test_i1_a_root_outside_the_rows_is_unknown_not_no_dependencies():
    """三态：根命题不在这一批行里 ⇒ 明确说"判不了"，不许读成"没有依赖"。"""
    rows = [_own("0002", deps=["0001"])]
    got = EB.cascade_void(rows, root="0001")
    assert got["dependents"] == [] and got["missing"] == ["0001"], got
    assert "没查成" in str(got.get("note") or ""), got


# ============================================================ I4 干净集合

def test_i4_the_clean_set_has_two_sources_with_reasons():
    """I4：干净集合的两类来源（我方已过审的命题 / 逐字核过的引用命题），理由逐条留下。"""
    rows = [_own("0001"), _own("0002", deps=["0001"], graded=True),
            _citation("0003", verified=True), _citation("0004", verified=False)]
    got = EB.clean_statement_ids(rows)
    assert set(got["clean"]) == {"0002", "0003"}, got
    assert "预备定理级" in got["reasons"]["0002"], got["reasons"]
    assert "lit:0009" in got["reasons"]["0003"], got["reasons"]
    assert "不许当依据" in got["reasons"]["0004"], got["reasons"]
    assert "引用它要小心" in got["reasons"]["0001"], got["reasons"]


def test_i4_a_voided_statement_is_never_clean():
    """I4 的硬边界：已作废的命题不许进干净集合（哪怕它够过预备定理级）。"""
    rows = [_own("0001", graded=True)]
    rows[0]["bits"]["voided_by"] = {"kind": "numeric_counterexample", "experiment_id": "exp-0009"}
    got = EB.clean_statement_ids(rows)
    assert got["clean"] == [] and "已作废" in got["reasons"]["0001"], got


def test_i1_and_i4_compose_a_cascaded_statement_is_no_longer_clean():
    """两条机制接起来（这是它们在真机上的用法）：级联之后那条不再干净 ⇒ 引用它会继承缺陷。"""
    rows = [_own("0001"), _own("0002", deps=["0001"], graded=True)]
    assert "0002" in EB.clean_statement_ids(rows)["clean"]
    out, _ = EB.apply_cascade(rows, root="0001")
    clean_after = EB.clean_statement_ids(out)
    assert clean_after["clean"] == [], clean_after
    assert "已作废" in clean_after["reasons"]["0002"], clean_after["reasons"]


def test_i4_feeds_the_attack_round_defect_judge():
    """I11 × I4：用干净集合判"这一步有没有继承缺陷" —— 引干净的不算，引不干净的算。"""
    rows = [_own("0001", graded=True), _citation("0008", verified=False)]
    clean = EB.clean_statement_ids(rows)["clean"]
    proof = AR.parse_round(
        '{"product": "proof", "strategy": "套用已知定理", "why_strategy": "直接引用",'
        ' "steps": [{"text": "由 0001 得到", "cites": ["0001"]},'
        '           {"text": "由 0008 得到", "cites": ["0008"]}]}')
    defects = AR.inherit_defects(proof, clean_ids=clean)
    assert [d["ref"] for d in defects] == ["0008"], defects
    assert defects[0]["step"] == 2, defects[0]
