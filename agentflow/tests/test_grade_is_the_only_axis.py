# -*- coding: utf-8 -*-
"""等级是唯一的轴（业主 2026-11-05 裁定）。

    逐字：「cross_check 等价于强猜想等价于有普通数值实验支撑的猜想（这很坏，为啥要叫
    cross_check）。不妨就用等级制平替掉」+「穷举证书相当于 lean 形式化，表示绝对正确」。

判据 a–e（`derive_grade` 的现算口径）：

| # | 输入 | 等级 |
|---|---|---|
| a | 穷举证书（numeric=verified）∧ proof ∧ reviewed | `theorem` |
| b | Lean（formal=verified）∧ proof ∧ reviewed | `theorem` |
| c | 文字证明 + V 签（numeric/formal 都没 verified） | `pre_theorem` |
| d | 只有数值实验、没签 | `strong_conjecture` |
| e | 什么都没 | `conjecture` |

反真空由 `temp/grade_probe.py` 的变异体承担（把 numeric 从 theorem 条件里摘掉 ⇒ a 红；
把 formal 摘掉 ⇒ b 红）：本文件只钉真身，变异体不在测试里另写一份逻辑 ——
测试里复制一份判定条件就等于造出第二套真值。

另外钉住"档位若还出现，只能由等级反算"（`kind_from_grade` / `kind_from_bits`），
以及"判不出就不写"（认不出的等级 ⇒ 空串，不是猜一档）。
"""
from __future__ import annotations

import pytest

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR


def _bits(**over):
    """五元位的最小构造（不经 `bits_of` 的凭据检查，只测派生本身）。"""
    base = {"numeric": "pending", "proof": False, "reviewed": False,
            "formal": "pending", "audited": False, "voided_by": {}}
    base.update(over)
    return base


# ============================================================ 判据 a–e

def test_a_an_exhaustion_certificate_is_a_theorem():
    """a：穷举证书（numeric=verified）+ 证明 + V 签 ⇒ 正式定理（与 Lean 同级）。"""
    bits = _bits(numeric="verified", proof=True, reviewed=True)
    assert EB.derive_grade(bits) == "theorem", bits
    assert EB.kind_from_bits(bits) == "proof", bits


def test_b_a_lean_verified_proof_is_a_theorem():
    """b：Lean 真编译过 + 证明 + V 签 ⇒ 正式定理。"""
    bits = _bits(proof=True, reviewed=True, formal={"1": "verified"})
    assert EB.derive_grade(bits) == "theorem", bits
    assert EB.kind_from_bits(bits) == "proof", bits


def test_c_a_prose_proof_with_a_v_sign_is_only_a_pre_theorem():
    """c：文字证明 + V 签、两条机器通道都没 verified ⇒ 预备定理级。"""
    bits = _bits(proof=True, reviewed=True, numeric="failed",
                 formal={"1": "pending"})
    assert EB.derive_grade(bits) == "pre_theorem", bits
    assert EB.kind_from_bits(bits) == "proof_review", bits


def test_d_numeric_evidence_without_a_sign_is_a_strong_conjecture():
    """d：只有普通数值实验（没 V 签、没证明）⇒ 强猜想（原 cross_check 那一档）。"""
    bits = _bits(numeric="verified")
    assert EB.derive_grade(bits) == "strong_conjecture", bits
    assert EB.kind_from_bits(bits) == "cross_check", bits


def test_e_nothing_at_all_is_a_conjecture():
    """e：五位全空 ⇒ 猜想（原 heuristic 那一档）。"""
    assert EB.derive_grade(_bits()) == "conjecture"
    assert EB.kind_from_bits(_bits()) == "heuristic"


# ============================================================ 反真空的正向半边
# （变异体那一半在 temp/grade_probe.py：把 numeric / formal 从 theorem 条件里摘掉，
#   a / b 必须变红。测试里不复制判定逻辑，只钉住"缺了那一件就到不了定理"。）

@pytest.mark.parametrize("without", ["both", "numeric", "formal"])
def test_a_missing_machine_channel_stops_at_a_pre_theorem(without):
    """两条机器通道都缺 ⇒ 停在预备定理级。

    这里只问"输入侧缺了那一件会怎样"；"把判定条件里那一支摘掉会红"由
    `temp/grade_probe.py` 的变异体证明（测试里不复制判定逻辑）。
    """
    bits = _bits(proof=True, reviewed=True)
    if without not in ("both", "numeric"):
        bits["numeric"] = "verified"
    if without not in ("both", "formal"):
        bits["formal"] = {"1": "verified"}
    if without == "both":
        assert EB.derive_grade(bits) == "pre_theorem", bits
    else:
        # 另一条通道还在 ⇒ 仍然到得了定理（这正是"两者同级"的意思）。
        assert EB.derive_grade(bits) == "theorem", bits


def test_numeric_alone_can_never_be_a_theorem_without_proof():
    """第 2 位是承重的：穷举证书再硬，也不能替第 2 位凭空捏出一份证明。

    这是 `theorem = 证明 ∧ 机器可核` 里的"证明"那一半 —— 抽掉它，两条通道都只剩
    强猜想 / 预备定理级。
    """
    for numeric in ("pending", "na", "failed", "verified"):
        for formal in ("pending", {"1": "verified"}):
            bits = _bits(numeric=numeric, formal=formal)
            assert EB.derive_grade(bits) in ("conjecture", "strong_conjecture"), (
                numeric, formal, bits)


def test_three_states_are_not_flattened():
    """三态：`pending`（还没做）与 `failed`（做了没成）都不构成机器可核。

    折平它们会让"没做"与"做了没过"在等级上长得一样，而两者欠的工序不同。
    """
    for state in ("pending", "na", "failed"):
        bits = _bits(proof=True, reviewed=True, numeric=state,
                     formal={"1": state})
        assert EB.derive_grade(bits) == "pre_theorem", (state, bits)


def test_grade_never_goes_down_when_a_bit_is_added():
    """只升不降：五元位从弱到强，等级序不许出现反向（业主裁定"只升不降"）。"""
    stages = [
        _bits(),
        _bits(numeric="verified"),
        _bits(numeric="verified", proof=True),
        _bits(numeric="verified", proof=True, reviewed=True),
        _bits(numeric="verified", proof=True, reviewed=True,
              formal={"1": "verified"}),
        _bits(numeric="verified", proof=True, reviewed=True,
              formal={"1": "verified"}, audited=True),
    ]
    order = {g: i for i, g in enumerate(EB.GRADES)}
    got = [order[EB.derive_grade(b)] for b in stages]
    assert got == sorted(got), (got, stages)


# ============================================================ 档位只能反算

def test_the_legacy_tier_vocabulary_is_exactly_the_reverse_map():
    """历史档位词表与等级序必须一一对应且互逆（没有第二套真值）。"""
    assert EB.LEGACY_KINDS == tuple(reversed(S.EVIDENCE_KINDS)), (
        EB.LEGACY_KINDS, S.EVIDENCE_KINDS)
    for grade in EB.GRADES:
        assert EB.kind_from_grade(grade) in S.EVIDENCE_KINDS, (grade,)


def test_kind_from_grade_refuses_to_guess():
    """反算不出来 ⇒ 空串：认不出的词 / 概念行都不许被猜成某一档。"""
    for bad in ("", "not_applicable", "proof", "THEOREM", None):
        assert EB.kind_from_grade(bad) == "", bad


def test_a_concept_row_has_no_legacy_tier_either():
    """概念行不参与等级链 ⇒ 也没有档位可反算（不是"最弱的猜想"）。"""
    bits = _bits(proof=True, reviewed=True)
    assert EB.derive_grade(bits, kind="concept") == EB.GRADE_NOT_APPLICABLE
    assert EB.kind_from_bits(bits, kind="concept") == ""


def test_a_voided_row_back_to_conjecture_and_heuristic():
    """作废 ⇒ 等级清零，档位反算也回到 heuristic（历史留在 voided_by 里）。"""
    bits = _bits(numeric="verified", proof=True, reviewed=True,
                 voided_by={"kind": "numeric_counterexample"})
    assert EB.derive_grade(bits) == "conjecture"
    assert EB.kind_from_bits(bits) == "heuristic"


# ============================================================ 可引门槛：两处门给出同一结论
# （2026-11-05 清点表：B 的 `depsection.CITATION_MIN_LEVEL` 与 V 的
# `verifications.CITATION_EVIDENCE_FLOOR` 曾是两份字面量，在"档位与等级不一致"的行上
# 给相反答案 —— 真机反例 `mp3-r3/000000`：B 拒、V 放行。）

def _row_with(*, evidence_kind: str, reviewed: bool, proof: bool = True) -> dict:
    return {"stmt_id": "000000", "kind": "theorem", "status": "active",
            "evidence_kind": evidence_kind, "proof_text": "（逐步论证）",
            "bits": {"numeric": "pending", "proof": proof, "reviewed": reviewed,
                     "formal": "pending", "audited": False,
                     "evidence": {"proof_process": "（逐步论证）",
                                  "reviewed_by": {"round": "V-1"} if reviewed else {}}}}


def _b_verdict(row: dict) -> str:
    gate = DS.gate_rows([{"stmt_id": row["stmt_id"], "line": 1}], [row])
    return "pass" if gate.get("ok") else str(gate.get("refused") or "refused")


def _v_verdict(row: dict) -> str:
    grade = EB.derive_grade(EB.bits_from_row(row), kind=str(row.get("kind") or ""))
    material = [{"stmt_id": row["stmt_id"], "statement_missing": False,
                 "grade": grade, "evidence_kind": row.get("evidence_kind"), "admissible": None}]
    checks = [{"stmt_id": row["stmt_id"], "verdict": "consistent",
               "quote_verbatim": False, "note": "", "in_material": True}]
    got = VR.reconcile_citation_checks(checks, material)[0]
    return "pass" if got.get("verdict") == "consistent" else str(got.get("verdict") or "refused")


def test_b_and_v_citation_gates_reach_the_same_verdict():
    """同一条行上，B 的洗稿门与 V 的签字门必须给同一结论（都读现算等级）。

    真机反例那一行：`evidence_kind="proof_review"` 而五元位没有 V 签 ⇒ 现算
    `conjecture` ⇒ 两处都必须拒（改前 B 拒、V 放行）。
    """
    unsigned = _row_with(evidence_kind="proof_review", reviewed=False)
    assert _b_verdict(unsigned) == "citation_below_proof_review", _b_verdict(unsigned)
    assert _v_verdict(unsigned) == "inadmissible", _v_verdict(unsigned)

    signed = _row_with(evidence_kind="heuristic", reviewed=True)
    assert _b_verdict(signed) == "pass", _b_verdict(signed)
    assert _v_verdict(signed) == "pass", _v_verdict(signed)


def test_the_two_gates_share_one_threshold_definition():
    """两处门槛不许各写一份字面量：V 的常量与允许集合都从 `depsection` 那一个定义取。"""
    assert VR.CITATION_EVIDENCE_FLOOR == DS.CITATION_MIN_LEVEL, VR.CITATION_EVIDENCE_FLOOR
    assert VR.CITATION_EVIDENCE_FLOOR == "pre_theorem", VR.CITATION_EVIDENCE_FLOOR
    assert set(VR.admissible_evidence_kinds()) == set(DS.CITATION_LEVELS), (
        VR.admissible_evidence_kinds(), DS.CITATION_LEVELS)


def test_anti_vacuum_the_old_kind_rule_would_disagree():
    """反真空：把任一处改回"读档位"的旧规则 ⇒ 上面那条一致性判据必红。

    这一行就是真机反例的形状：档位 `proof_review`（旧规则放行）、现算等级
    `conjecture`（新规则拒绝）。若某一处退回档位口径，两处结论就会分家 ——
    这条负控把那句话变成可跑的读数。
    """
    row = _row_with(evidence_kind="proof_review", reviewed=False)
    old_rule_v = str(row.get("evidence_kind")) in ("proof", "proof_review")
    assert old_rule_v is True, "夹具写错了：旧规则下这一行应当放行"
    assert _b_verdict(row) != "pass" and _v_verdict(row) != "pass", (
        "两处新口径必须都拒；若有一处放行，说明那一处又读回档位了")


# ============================================================ 收工门三支：同一个等级阈值
# （2026-11-05 清点表：承重命题支已改读等级，承重断言支 / T3 实验支仍读档位 ⇒
#  "半改比不改更坏"。）

def test_closing_three_branches_use_one_grade_threshold():
    """a：承重命题支、承重断言支、T3 实验支的判定都落在同一个 `theorem` 阈值上。

    - 命题支：`closing._statement_grade` 现算等级；
    - 断言 / 实验支：`closing._tier_grade` 把各自词表的档位经 `KIND_TO_GRADE` 反算成
      等级（它们的 `evidence_kind` 与命题等级不同名，不许直接比）。
    """
    from agentflow import closing as CL

    statement = _row_with(evidence_kind="proof", reviewed=True)      # 文字证明 + V 签
    assert CL._statement_grade(statement) == "pre_theorem", statement
    machine = _row_with(evidence_kind="proof", reviewed=True)
    machine["bits"]["numeric"] = "verified"                          # 穷举证书
    assert CL._statement_grade(machine) == "theorem", machine

    claim = {"evidence_kind": "proof"}
    assert CL._tier_grade(claim) == "theorem", claim
    assert CL._tier_grade({"evidence_kind": "cross_check"}) == "strong_conjecture"

    formal_exp = {"evidence_kind": "proof", "method": "formal",
                  "verifier_output": "no goals"}
    assert CL._has_t3(formal_exp) is True, formal_exp
    weak_exp = dict(formal_exp, evidence_kind="cross_check")
    assert CL._has_t3(weak_exp) is False, weak_exp

    # 三支的阈值是同一个词（不是三份字面量）：把任一支的档位改弱，判定必须跟着翻。
    assert CL._statement_grade(_row_with(evidence_kind="proof", reviewed=False)) != "theorem"
    assert CL._has_t3(dict(formal_exp, evidence_kind="heuristic")) is False


def test_closing_anti_vacuum_the_statement_branch_used_to_trust_the_kind():
    """b（反真空）：同一条命题，旧口径（`evidence_kind == "proof"`）与等级口径给出相反读法。

    这一行历史列写着 `proof`、五元位却只到 `conjecture`。若承重命题支退回读档位，
    它会被判成"承重定理"；读等级才判成"已降档"。两支的差是这条改造的可测量部分。
    """
    from agentflow import closing as CL

    row = _row_with(evidence_kind="proof", reviewed=False)
    old_rule = str(row.get("evidence_kind")) == "proof"
    assert old_rule is True
    assert CL._statement_grade(row) == "conjecture", row
    assert CL._statement_grade(row) != "theorem", "承重命题支又读回档位了"

