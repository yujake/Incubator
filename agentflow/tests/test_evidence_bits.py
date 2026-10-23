# -*- coding: utf-8 -*-
"""五元证据位与派生等级（`draft/39` §3.14/§3.15/§3.17/§3.18）。

这一份就是批① 的 E1（命题生命周期演练） 与 E2（数值封顶）：

- E1：五条命题各走一条路（纯猜想 / 强猜想（数值）/ 预备定理级 / 正式定理 / 作废），
  逐条断言五位读数与派生等级；
- E2：给一条命题堆 3 条数值实验 ⇒ 等级必须停在「强猜想」，且任何输入下
  `derive_grade` 都不许吐出 `theorem`（"数值验证不构成证明"是这一条的口径）。

另外三条纪律各自有负控：四态不许折平（`na`/`failed` 必须带理由或原文）、
引用命题凭文献代号进第 2+3 位（不许被当成"我们自己造的"）、作废四条缺一不可。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB


# ============================================================ E1：五条生命周期

def test_e1_lifecycle_1_a_bare_conjecture_stays_a_conjecture():
    """第 1 条：只有一句话、什么都没做 ⇒ 猜想（五位全空）。"""
    bits = EB.bits_of()
    assert [bits[b] for b in ("numeric", "proof", "reviewed", "formal", "audited")] == \
        ["pending", False, False, "pending", False], bits
    assert bits["grade"] == "conjecture", bits


def test_e1_lifecycle_2_numeric_verification_gives_a_strong_conjecture():
    """第 2 条：E 跑过数值实验且通过 ⇒ 强猜想（仍不是定理）。"""
    bits = EB.bits_of(numeric="verified", numeric_evidence={
        "experiment_id": "exp-0007", "script": "code/scan.py", "sha": "9f2c1a"})
    assert bits["grade"] == "strong_conjecture", bits
    assert EB.bit_problems(bits) == [], EB.bit_problems(bits)


def test_e1_lifecycle_3_proof_plus_review_is_a_pre_theorem():
    """第 3 条：F 写了证明过程、V 走查过 ⇒ 预备定理级（还没有形式化）。"""
    bits = EB.bits_of(proof=True, proof_process="设 G 是 m-正则图……（逐步论证，引 stmt-0004）",
                      reviewed=True, reviewed_by={"verdict": "no_defect",
                                                  "round": "V-0003", "evidence": "走查记录"})
    assert bits["grade"] == "pre_theorem", bits
    assert bits["audited_badge"] is False, bits
    assert EB.bit_problems(bits) == [], EB.bit_problems(bits)


def test_e1_lifecycle_4_proof_plus_formalisation_is_a_theorem():
    """第 4 条：证明过程 + E 的形式化通过 ⇒ 正式定理；H 审过再加一枚并列徽章。"""
    bits = EB.bits_of(proof=True, proof_process="（逐步论证）",
                      formal="verified", formal_evidence={"checker": "lean4",
                                                          "output": "no goals"})
    assert bits["grade"] == "theorem", bits
    assert bits["audited_badge"] is False, bits
    audited = EB.bits_of(proof=True, proof_process="（逐步论证）",
                         formal="verified", formal_evidence={"checker": "lean4"},
                         audited=True, audited_by={"round": "H-0011", "verdict": "采信"})
    assert audited["grade"] == "theorem" and audited["audited_badge"] is True, audited


def test_e1_lifecycle_5_a_voided_proposition_drops_back_to_a_conjecture():
    """第 5 条：数值路出真反例 ⇒ 作废；五位读数全部作废，但历史留在 `voided_by` 里。"""
    exp = {"experiment_id": "exp-0009", "exit_code": 0, "result": "refutes",
           "counterexample": "n=14 时该族不存在（枚举 262 个候选，无一满足）",
           "code_path": "code/scan.py", "code_hash": "aa11bb"}
    mark = EB.void(exp, verdict="refutes", counterexample_valid=True)
    bits = EB.bits_of(numeric="failed", numeric_evidence={"experiment_id": "exp-0009"},
                      numeric_reason="反例：n=14", proof=True, proof_process="（旧证明）",
                      reviewed=True, reviewed_by={"round": "V-0001"},
                      formal="verified", formal_evidence={"checker": "lean4"},
                      voided_by=mark)
    assert bits["grade"] == "conjecture", bits
    assert bits["voided_by"]["kind"] == "numeric_counterexample", bits
    assert bits["voided_by"]["counterexample"], bits
    # 作废是"等级清零"，不是"把记录抹掉"：原来的证明过程还在证据栏里（历史可查）。
    assert bits["evidence"]["proof_process"], bits


# ============================================================ E2：数值封顶

def _three_numeric_experiments() -> dict:
    return {"experiments": [
        {"experiment_id": "exp-0001", "script": "code/a.py", "sha": "1"},
        {"experiment_id": "exp-0002", "script": "code/b.py", "sha": "2"},
        {"experiment_id": "exp-0003", "script": "code/c.py", "sha": "3"},
    ], "max_n": 4096}


def test_e2_three_numeric_experiments_still_cap_at_strong_conjecture():
    """E2：数值验证堆到三条、界推到 4096 ⇒ 等级逐字停在「强猜想」。"""
    bits = EB.bits_of(numeric="verified", numeric_evidence=_three_numeric_experiments())
    assert bits["grade"] == "strong_conjecture", bits
    assert EB.GRADE_LABELS[bits["grade"]] == "强猜想", bits
    assert "定理" not in EB.GRADE_LABELS[bits["grade"]], bits


@pytest.mark.parametrize("formal_state", ["pending", "na", "failed", "verified"])
def test_e2_no_numeric_combination_can_reach_theorem_without_a_proof(formal_state):
    """E2 的负控：没有证明过程时，无论数值与形式化怎么填，`theorem` 都不许出现。

    这条把"数值验证不构成证明"写成机器判据：形式化通过但不给证明过程 ⇒ 也到不了定理
    （第 4 位是"证明被机器检查过"，它不能替第 2 位凭空捏出一个证明）。
    """
    for numeric in ("pending", "na", "failed", "verified"):
        bits = EB.bits_of(numeric=numeric, numeric_evidence=_three_numeric_experiments(),
                          formal=formal_state, formal_reason="环境缺该方向的库",
                          formal_evidence={"checker": "lean4"} if formal_state == "verified" else {"x": 1})
        assert bits["grade"] != "theorem", (numeric, formal_state, bits)
        assert bits["grade"] in ("conjecture", "strong_conjecture"), (numeric, formal_state, bits)


def test_the_cross_check_tier_does_not_exist_any_more():
    """旧口径的余毒：`cross_check` 那一档（"交叉验证"能顶 proof）不许留在这个模型里。

    理由（用户 2026-10-05）：数值验证不构成证明。旧的 `EVIDENCE_KINDS` 里有
    `cross_check` 一档、`CROSS_CHECK_DISCLAIMER` 一段措辞 —— 那套语义不进这个模型，
    这里把它钉成负控：五位里没有任何一位叫 `cross_check`。
    """
    assert "cross_check" not in EB.BIT_NAMES
    bits = EB.bits_of(numeric="verified", numeric_evidence={"experiments": [{"cross_check": True}]})
    assert bits["grade"] == "strong_conjecture", bits


# ============================================================ 四态纪律（不许折平）

def test_na_and_pending_are_different_things():
    """`na`（不适用）≠ `pending`（还没做）：只有 `na` 要理由，两者都不算"做过"。"""
    na = EB.bits_of(numeric="na", numeric_reason="本环境缺该方向的库，且命题含未形式化的定义")
    todo = EB.bits_of(numeric="pending")
    assert na["numeric"] == "na" and todo["numeric"] == "pending", (na, todo)
    assert [na["grade"], todo["grade"]] == ["conjecture", "conjecture"], (na, todo)
    assert EB.bit_problems(na) == [], EB.bit_problems(na)


def test_na_without_a_reason_is_a_problem():
    """`na` 必须写理由：不写 ⇒ 五位自身不合规（这一条防的是"用 na 把该做的事抹掉"）。"""
    bits = EB.bits_of(numeric="na", formal="na")
    problems = EB.bit_problems(bits)
    assert len(problems) == 2, problems
    assert all("必须写理由" in p for p in problems), problems


def test_failed_needs_the_raw_output_and_verified_needs_a_credential():
    """`failed` 要原文、`verified` 要凭据：三态里"做了没通过"与"做了通过了"都得留得下东西。"""
    failed = EB.bit_problems(EB.bits_of(numeric="failed"))
    assert len(failed) == 1 and "必须带原文" in failed[0], failed
    verified = EB.bit_problems(EB.bits_of(numeric="verified"))
    assert len(verified) == 1 and "必须带凭据" in verified[0], verified
    # `pending`（还没做）不报问题 —— 它是诚实的"还没做"，不是缺陷。
    assert EB.bit_problems(EB.bits_of(numeric="pending")) == []


def test_proof_and_review_without_evidence_are_problems():
    """第 2/3/5 位为真也必须带凭据（证明过程 / V 的结论 / H 的审校轮次）。"""
    problems = EB.bit_problems(EB.bits_of(proof=True, reviewed=True, audited=True))
    assert len(problems) == 3, problems
    joined = "；".join(problems)
    assert "证明过程" in joined and "审校轮次" in joined, problems


# ============================================================ 引用命题（§3.15 三）

def test_a_verified_citation_credits_bits_2_and_3_with_the_literature_id():
    """引用命题：逐字核过的文献 ⇒ 第 2+3 位真，凭据是文献代号，等级 = 预备定理级。"""
    bits = EB.bits_of(origin="external_lit", source_lit_id="lit-0042", quote_verified=True)
    assert bits["proof"] is True and bits["reviewed"] is True, bits
    assert bits["evidence"]["reviewed_by"] == {"evidence": "lit:lit-0042"}, bits
    assert bits["grade"] == "pre_theorem", bits
    assert EB.bit_problems(bits) == [], EB.bit_problems(bits)


def test_a_citation_without_verbatim_verification_credits_nothing():
    """没有逐字核过（`quote_verified` 为假或空）⇒ 一位都不给：引用也会是幻觉。"""
    for qv in (False, None):
        bits = EB.bits_of(origin="external_lit", source_lit_id="lit-0042", quote_verified=qv)
        assert bits["proof"] is False and bits["reviewed"] is False, bits
        assert bits["grade"] == "conjecture", bits


def test_a_citation_is_never_upgraded_to_a_theorem_by_itself():
    """引用命题不会被自动抬成定理：第 4 位（形式化）与第 5 位（H 审）它一样要自己挣。"""
    bits = EB.bits_of(origin="external_lit", source_lit_id="lit-0042", quote_verified=True)
    assert bits["grade"] != "theorem", bits


# ============================================================ 作废四条（§3.18）

def _refuting_experiment(**over: object) -> dict:
    exp = {"experiment_id": "exp-0009", "exit_code": 0, "result": "refutes",
           "counterexample": "n=14 时该族不存在", "code_path": "code/scan.py",
           "code_hash": "aa11bb"}
    exp.update(over)
    return exp


def test_voiding_needs_all_four_conditions():
    """四条齐 ⇒ 允许；`void()` 给出可落台账的载荷（含 script + sha + 反例）。"""
    mark = EB.void(_refuting_experiment(), verdict="refutes", counterexample_valid=True)
    assert mark == {"kind": "numeric_counterexample", "experiment_id": "exp-0009",
                    "script": "code/scan.py", "sha": "aa11bb",
                    "counterexample": "n=14 时该族不存在"}, mark


@pytest.mark.parametrize("broken,needle", [
    ({"exit_code": 1}, "没有正常退出"),
    ({"exit_code": None}, "没有正常退出"),
    ({"result": "inconclusive"}, "没有给出 refutes"),
    ({"counterexample": ""}, "反例为空"),
    ({"code_path": ""}, "不可复现"),
    ({"code_hash": ""}, "不可复现"),
])
def test_voiding_refuses_when_one_of_the_four_conditions_is_missing(broken, needle):
    """四条缺一 ⇒ 拒绝作废（脚本问题与命题为假必须分得开）。"""
    reason = EB.void_refusal(_refuting_experiment(**broken), verdict="refutes",
                             counterexample_valid=True)
    assert needle in reason, (broken, reason)
    with pytest.raises(ValueError, match="不许作废"):
        EB.void(_refuting_experiment(**broken), verdict="refutes", counterexample_valid=True)


def test_voiding_refuses_when_nobody_said_the_counterexample_holds():
    """第 4 条（反例确实是反例）没有结论 ⇒ 拒绝：`None`（看不出来）不许当成"成立"。"""
    for verdict in (None, "unclear", "defective"):
        reason = EB.void_refusal(_refuting_experiment(), verdict="refutes",
                                 counterexample_valid=verdict)
        assert "没有结论" in reason, (verdict, reason)
    assert EB.void_refusal(_refuting_experiment(), verdict="refutes",
                           counterexample_valid=False).startswith("反例是否成立没有结论")


def test_the_structured_verdict_must_be_the_scripts_own_words():
    """第 2 条：结论要来自脚本自己（`result` / stdout 的结构化行），不是谁替它说的。"""
    # 实验行里没写 result，只有人转述 ⇒ 不算
    assert "没有给出 refutes" in EB.void_refusal(_refuting_experiment(result=""),
                                                verdict="", counterexample_valid=True)
    # 脚本自己写了 ⇒ 算
    assert EB.void_refusal(_refuting_experiment(result="refutes"), verdict="",
                           counterexample_valid=True) == ""


def test_a_theoretical_construction_can_void_without_an_experiment():
    """第二条作废路（§3.15 四）：理论构造出反例 ⇒ 不用数值实验也能作废。"""
    mark = EB.void({}, construction="取 G = 完全二部图 K_{3,3}：满足前提、违反结论")
    assert mark["kind"] == "construction", mark


# ============================================================ 读台账那一行（bits_from_row）

def test_a_legacy_row_without_bits_credits_nothing():
    """旧行（没有 `bits`）一律按五位全空算：自报的 `status=proved` / `evidence_kind=proof` 不算凭据。

    这是整个模型的立身之本 —— 历史上正是那些自报字段把"数值支持"读成了"已证明"。
    """
    row = {"stmt_id": "stmt-0001", "origin": "own_result", "status": "proved",
           "evidence_kind": "proof", "proof_text": "（自报的证明）", "kind": "theorem"}
    bits = EB.bits_from_row(row)
    assert bits["grade"] == "conjecture", bits
    assert [bits[b] for b in ("numeric", "proof", "reviewed", "formal", "audited")] == \
        ["pending", False, False, "pending", False], bits


def test_a_legacy_external_lit_row_keeps_its_citation_credit_only_with_a_span():
    """旧行里唯一保留的读法：逐字核过的引用命题（凭据是文献代号 + 区间）。

    D1（2026-10-22 第二版）：空 `quote_mode` 仍按逐字读，但前提是有区间 ——
    区间是"核了哪一段、在第几页"的唯一载子。改前这一条断言的是"只要 quote_verified
    为真就给学分"，真机 13 行（true + verbatim + 空 span）正是靠那条读法拿到了学分。
    """
    with_span = {"stmt_id": "stmt-0002", "origin": "external_lit",
                 "source_lit_id": "lit-0042", "quote_verified": True,
                 "quote_span": "p2:norm[4:44]", "status": "active"}
    assert EB.bits_from_row(with_span)["grade"] == "pre_theorem", EB.bits_from_row(with_span)

    legacy = dict(with_span, quote_span="")
    bits = EB.bits_from_row(legacy)
    assert bits["grade"] == "conjecture", (
        "说通过而拿不出区间 ⇒ 不给引用学分（D1 的读侧那一半）", bits)
    assert EB.quote_state(legacy) == EB.QUOTE_NO_EVIDENCE, EB.quote_state(legacy)


def test_a_new_row_with_bits_is_re_normalised_and_the_grade_is_recomputed():
    """新行：盘上存的等级只当缓存 —— 判据读的那一份永远现算。"""
    row = {"stmt_id": "stmt-0003", "origin": "own_result",
           "bits": {"numeric": "true", "proof": True, "reviewed": True, "formal": "false",
                    "audited": False, "grade": "theorem",       # ← 自报的缓存，必须被推翻
                    "evidence": {"proof_process": "（逐步论证）",
                                 "reviewed_by": {"round": "V-0003"}}}}
    bits = EB.bits_from_row(row)
    assert bits["grade"] == "pre_theorem", bits          # 现算覆盖缓存
    assert bits["numeric"] == "verified", bits           # 四态规范化（"true" ⇒ verified）
    assert bits["formal"] == "failed", bits              # ("false" ⇒ failed)


def test_a_voided_row_stays_a_conjecture_even_with_a_cached_higher_grade():
    """作废行：等级清零（缓存的"定理"不算数），`refuted_by` 也能当 `voided_by` 读进来。"""
    row = {"stmt_id": "stmt-0004", "origin": "own_result",
           "refuted_by": {"kind": "numeric_counterexample", "experiment_id": "exp-0009"},
           "bits": {"proof": True, "reviewed": True, "grade": "theorem",
                    "evidence": {"proof_process": "（旧证明）", "reviewed_by": {"round": "V-1"}}}}
    bits = EB.bits_from_row(row)
    assert bits["grade"] == "conjecture", bits
    assert bits["voided_by"]["experiment_id"] == "exp-0009", bits


# ============================================================ 写台账之前把形状关（schema 边界）

def _statement(**over):
    """造一条能过 `Statement.validate` 的行（老约束先满足：quote_reason + proof_text）。"""
    from agentflow import schema as S

    base = dict(stmt_id="0000", origin="own_result", kind="theorem",
                statement_full="设 G 是 m-正则图；则……",
                proof_text="（逐步论证）", quote_verified=None,
                quote_reason="我方自产命题，没有外部引文要比对", created_at="2026-10-05T00:00:00")
    base.update(over)
    return S.Statement(**base)


def test_a_statement_with_well_formed_bits_validates():
    """正控：形状合规的 `bits` 能进台账（反真空 —— 免得把关做成了"什么都拒"）。"""
    row = _statement(bits={"numeric": "verified",
                           "evidence": {"numeric": {"experiment_id": "exp-0002",
                                                    "script": "code/scan.py", "sha": "aa11"}}})
    row.validate()


@pytest.mark.parametrize("bits,needle", [
    ({"numeric": "verified", "evidence": {"numeric": {"sha": "aa11"}}}, "没有指针"),
    ({"formal": "verified", "evidence": {"formal": {"output": "no goals"}}}, "哪个检查器"),
    ({"numeric": "na"}, "必须写理由"),
    ({"nueric": "verified"}, "不认识的键"),
    ({"proof": True, "reviewed": True, "grade": "theorem",
      "evidence": {"proof_process": "（证明）", "reviewed_by": {"round": "V-1"}}}, "不许自报"),
])
def test_the_bits_shape_gate_rejects_one_broken_thing_at_a_time(bits, needle):
    """负控：每一种坏形状都要单独被点名（未知键 / 自报等级 / 缺凭据 / `na` 无理由）。

    判据本体在 `evidencebits.bits_shape_problems`（唯一来源），schema 只转发 ——
    这一组测的是"转发到位了"，所以断言的是异常文本里那句人话。
    """
    with pytest.raises(ValueError) as exc:
        _statement(bits=bits).validate()
    assert needle in str(exc.value), str(exc.value)


def test_a_voided_statement_may_not_stay_active():
    """作废位与 `status='active'` 不许并存：等级清零与状态降档是两件事，必须都做。"""
    with pytest.raises(ValueError, match="不许留 status='active'"):
        _statement(bits={"voided_by": {"kind": "numeric_counterexample",
                                       "experiment_id": "exp-0009"}}).validate()
    _statement(status="refuted",
               bits={"voided_by": {"kind": "numeric_counterexample",
                                   "experiment_id": "exp-0009"}}).validate()


def test_a_cached_grade_in_bits_must_equal_the_live_derivation():
    """盘上那份等级只当缓存：与现算不符 ⇒ 写入期直接拒（省得读盘的人看到两个数）。"""
    good = {"proof": True, "reviewed": True, "grade": "pre_theorem",
            "evidence": {"proof_process": "（逐步论证）", "reviewed_by": {"round": "V-1"}}}
    _statement(bits=good).validate()
    bad = dict(good, grade="theorem")
    with pytest.raises(ValueError, match="按五位现算"):
        _statement(bits=bad).validate()


def test_an_empty_bits_field_stays_readable_as_all_blank():
    """空 `bits`（旧行/还没填）是合规的：它读成"五位全空"，不是"格式错"。"""
    _statement().validate()
    assert EB.bits_from_row({"bits": {}}).get("grade") == "conjecture"
