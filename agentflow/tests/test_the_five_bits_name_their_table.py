# -*- coding: utf-8 -*-
"""五元位与它们各自的台账：位上说有，表里要查得到。
## 这一组守的是业主的一条点名（2026-10-09 逐字）
> 「再确认一条命题的五元状态是哪张表在维护，要做好映射（如果五元状态里说有证明，> 证明应该在 B 维护的表里可查）」
## 为什么这需要一条判据（而不是一句注释）
五元位是读数，表是凭据。在加这一条之前，"这一位是 `verified`"这句话在整个系统的数据面上只受一件事约束：位自己的形状（`evidencebits.bit_problems`要求 `verified` 带凭据）。
于是下面这种形态是允许的：
位里写 proof=true（或 numeric=verified 指着一个不存在的实验号），而 `statements.proof_text` 是空的 —— "位上说有证明，B 的表里却没有证明"。
它在报告里与"真的做过"长得一模一样，而这正是五元位当初要堵的洞（`bits_from_row`：「自报不算凭据」）。
所以映射必须落到判据上：`BIT_LEDGERS`说"哪一位去哪张表查"，`bit_evidence_gaps` 判"查得到吗"，`verify` 第 13 段把它翻成 issue。
## 判据的分工（三态纪律）
- 正控一：映射本身全不全（五位都在、owner 与 `BIT_OWNERS` 逐位一致、三栏都非空）—— 映射漏一位就等于那一位没有台账；- 正控二：好数据不误伤（自己证的命题 + 真实验号 ⇒ 一条 gap 都不许报）；-
负控：位说有、表里没有 ⇒ `bits_proof_without_evidence`（error）/`bits_evidence_pointer_dangling`（error）；- 负控：指针指的实验存在但类别不对 ⇒
`bits_evidence_method_mismatch`（warning，"查了别的东西"不是"没查"，所以看得见但不拦门）；- 反真空 / 三态：没有指针时不报（凭据缺失由 `bit_problems` 点名，
同一件事报两次会让"改哪里"变得不清楚）；引用命题不报（凭据是文献代号 + 逐字核验，证明过程在别人的文献里，不在我们的台账里）。
"""

from __future__ import annotations

from conftest import TS, add_literature, sync_counters
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.verify import verify_all


def _codes(store) -> list[str]:
    d = verify_all(store).to_dict()
    return [i["code"] for i in list(d["errors"]) + list(d["warnings"])]


def _bit_codes(store) -> list[str]:
    return [c for c in _codes(store) if c.startswith("bits_")]


def _exp(store, eid: str, *, method: str = "numeric") -> dict:
    row = S.Experiment(
        experiment_id=eid, claim="Spec K(m) = [-m, m]", claim_key="SpecK(m)=[-m,m]",
        method=method, evidence_kind="cross_check", result="supports",
        negation_kind="not_proved", code_path="code/exp.py",
        code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS,
    )
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _stmt(store, sid: str, **kw) -> dict:
    bits = kw.pop("bits", None)
    base = dict(
        stmt_id=sid, origin="own_result", kind="theorem", label="Theorem 3.1",
        statement_text="K(m) 的谱是 [-m, m]", statement_full="设 K 是 m-正则图，则 Spec K(m) = [-m, m]",
        proof_text="Proof. 逐边展开特征多项式……", evidence_kind="proof",
        quote_reason="自产结果，无需逐字回验", status="active", created_at=TS,
    )
    base.update(kw)
    if bits is not None:
        base["bits"] = bits
    row = S.Statement(**base)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ==================================================== 一、映射本身（正控）

def test_every_bit_names_a_table():
    """五位各有一位台账，owner 与 `BIT_OWNERS` 逐位一致，四栏都非空（反真空）。"""
    assert len(EB.BIT_LEDGERS) == len(EB.BIT_NAMES) == 5
    for bit in EB.BIT_NAMES:
        entry = EB.bit_ledger(bit)
        assert entry, f"第 {bit!r} 位没有台账映射 ⇒ 这一位在数据面上无处可查"
        assert entry["owner"] == EB.BIT_OWNERS[bit], f"{bit} 的 owner 与 BIT_OWNERS 分家了"
        for key in ("ledger", "pointer", "criteria"):
            assert entry[key].strip(), f"{bit} 的 {key} 不能为空（空 = 这条映射没有内容）"
    # 未知位 ⇒ 空 dict（调用方按"没查成"处理，不按"查过了没问题"）
    assert EB.bit_ledger("no_such_bit") == {}


# ==================================================== 二、好数据不误伤（正控）

def test_a_real_proof_and_a_real_experiment_are_clean(store):
    """自己证的命题（proof_text 在册）+ 指得着的数值实验 ⇒ 一条 gap 都不许报。"""
    add_literature(store, "0000")
    _exp(store, "0001", method="numeric")
    bits = EB.bits_of(
        proof=True, proof_process="逐边展开特征多项式……",
        numeric="verified", numeric_evidence={"experiment_id": "0001", "script": "code/exp.py"},
        reviewed=True, reviewed_by={"round": 2, "verdict": "pass"},
    )
    _stmt(store, "0001", bits=bits)
    assert EB.bit_evidence_gaps(store.rows("statements")[0],
                                experiments=store.rows("experiments")) == []
    assert _bit_codes(store) == []
    assert verify_all(store).to_dict()["checked"]["bit_ledger_gaps"] == 0


# ==================================================== 三、位说有、表里没有（负控）

def test_a_claimed_proof_must_be_in_bs_table(store):
    """`proof` 位为真而 `proof_text` 空 ⇒ error（业主点名的那一种形态）。

    注意这一行写入时是合规的：它的证明过程写在位自己的载荷里
    （`evidence.proof_process`，`bit_problems` 因此放行），而 B 维护的那张表
    （`statements.proof_text`）是空的。这正是要堵的形态：证明只活在"位"里，
    去表里查不到 —— 于是"位说有证明"与"真的有证明"在报告里长得一样。
    """
    row = _stmt(store, "0001", proof_text="",
                bits=EB.bits_of(proof=True, proof_process="逐边展开特征多项式，逐步论证……"))
    gaps = EB.bit_evidence_gaps(row, experiments=[])
    assert [g["code"] for g in gaps] == ["bits_proof_without_evidence"]
    assert gaps[0]["level"] == "error" and "B 维护" in gaps[0]["reason"]
    codes = _bit_codes(store)
    assert "bits_proof_without_evidence" in codes
    assert verify_all(store).to_dict()["checked"]["bit_ledger_gaps"] == 1


def test_a_dangling_evidence_pointer_is_an_error(store):
    """位里的凭据指名道姓写了实验号，表里却没有这一行 ⇒ error（复跑不了）。"""
    row = _stmt(store, "0001", bits=EB.bits_of(
        numeric="verified", numeric_evidence={"experiment_id": "9999", "script": "code/exp.py"}))
    gaps = EB.bit_evidence_gaps(row, experiments=[])
    assert [g["code"] for g in gaps] == ["bits_evidence_pointer_dangling"]
    assert gaps[0]["level"] == "error" and "9999" in gaps[0]["reason"]
    assert "bits_evidence_pointer_dangling" in _bit_codes(store)


def test_a_list_of_experiment_ids_is_checked_one_by_one(store):
    """凭据写成一列号时逐条查（整列不许被拼成一个号 —— 那会报出一条永远查不到的假指针）。"""
    _exp(store, "0002", method="numeric")
    ok = {"stmt_id": "0001", "proof_text": "Proof. ……", "bits": EB.bits_of(
        numeric="verified", numeric_evidence={"experiments": ["0001", "0002"]})}
    gaps = EB.bit_evidence_gaps(ok, experiments=store.rows("experiments"))
    # 0001 不在册、0002 在册 ⇒ 只报缺的那一条（不是把整列报成一条）
    assert [g["code"] for g in gaps] == ["bits_evidence_pointer_dangling"]
    assert "'0001'" in gaps[0]["reason"]


def test_an_experiment_of_the_wrong_kind_is_a_warning(store):
    """指针指的实验存在但 method 不是这一位该有的 ⇒ warning（看得见，不拦门）。"""
    _exp(store, "0001", method="formal")
    row = _stmt(store, "0001", bits=EB.bits_of(
        numeric="verified", numeric_evidence={"experiment_id": "0001"}))
    gaps = EB.bit_evidence_gaps(row, experiments=store.rows("experiments"))
    assert [g["code"] for g in gaps] == ["bits_evidence_method_mismatch"]
    assert gaps[0]["level"] == "warning" and gaps[0]["bit"] == "numeric"
    codes = _codes(store)
    assert "bits_evidence_method_mismatch" in codes


# ==================================================== 四、三态与边界（反真空）

def test_a_missing_pointer_is_left_to_bit_problems():
    """没有指针时这一条不报：凭据缺失由 `bit_problems` 点名（一件事只留一条话）。"""
    row = {"stmt_id": "0001", "proof_text": "Proof. ……",
           "bits": EB.bits_of(numeric="verified", numeric_evidence={})}
    assert EB.bit_evidence_gaps(row, experiments=[]) == []
    # 反真空：它不报，是因为别人报了 —— 若 `bit_problems` 也放行，
    # 这一格就真的没人管了（这条断言就是那个下限）。
    assert any("凭据" in p for p in EB.bit_problems(dict(row["bits"])))


def test_a_cited_proof_lives_in_the_other_paper(store):
    """引用命题：凭据是文献代号 + 逐字核验 ⇒ `proof_text` 空也不报（不在我们的台账里）。"""
    add_literature(store, "0000")
    row = _stmt(store, "0001", origin="external_lit", source_lit_id="0000",
                proof_text="", quote_verified=True, quote_reason="逐字比对通过（page 7）",
                bits=EB.bits_of(origin="external_lit", source_lit_id="0000",
                                quote_verified=True))
    assert EB.bit_evidence_gaps(row, experiments=[]) == []
    assert "bits_proof_without_evidence" not in _bit_codes(store)
