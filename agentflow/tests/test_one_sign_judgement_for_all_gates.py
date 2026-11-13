# -*- coding: utf-8 -*-
"""一个判据、四个门：`sign_reading` 说"签了"时，四个读点必须逐字同答案（D268 批 2）。

四门：`vsigns.bits_after_sign`（B 认签）/ `secretary.proof_text_manuscript_sign_gate`
（正文闸）/ `agent_b.register_statement._unsigned_proof_gate`（B 收录闸）/
`closing.statements_unsigned_reading`（收工门）。

反真空：同一夹具删掉凭据 ⇒ 四门必须同时翻成"没签"；若只翻一门，说明还有一门在
自己数"块/行/文件"。这是防"下一次又从别处长回来"的唯一判据。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b.register_statement import _RegisterStatement
from agentflow.store import Store

from _credential_fixture import issue_credential
from conftest import seed_statement_row

PROOF = "1. 由定义直接得到。\n2. 由 1 得结论。"
REL = "reports/f-proof-000001.md"
SID = "000001"
TS = "2026-11-10T00:00:00+08:00"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed(st: Store) -> dict:
    bits = EB.bits_of(proof=True, proof_process=PROOF, kind="theorem")
    ev = dict(bits.get("evidence") or {})
    ev[EB.REVIEWED_BY_PROOF_KEY] = {str(1): True}
    bits["evidence"] = ev
    # 第 3 位那一格由逐份表回答（`reviewed_by_proof`）；schema 的 reviewed=true
    # 还要求凭据对象，这一条夹具量的是逐份表，不写 reviewed。
    bits["reviewed"] = False
    bits["grade"] = EB.derive_grade(bits, kind="theorem")
    row = seed_statement_row(
        st, proof_text="", statement_full="夹具命题。", statement_text="夹具命题",
        kind="theorem", label="one-judgement", origin="own_result",
        evidence_kind="heuristic", bits=bits, stmt_id=SID,
        proofs=[{"proof_no": 1, "proof_text": PROOF}])
    (pathlib.Path(st.root) / REL).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(st.root) / REL).write_text(
        "# 证明手稿\n\n## 命题\n\n夹具命题。\n\n"
        "## 证明\n\n" + PROOF + "\n\n## 依赖\n\n| 依赖 | 类型 | 状态 | 说明 |\n"
        "|---|---|---|---|\n", encoding="utf-8")
    return row


def _answers(st: Store) -> dict[str, bool]:
    _bits, v_sign = VS.bits_after_sign(
        {}, root=st.root, proof_text=PROOF, statement_id=SID, proof_no=1,
        manuscript_path=REL, store=st)
    sec = SEC.proof_text_manuscript_sign_gate(
        st, proof_text=PROOF, statement_id=SID, proof_no=1)
    b = _RegisterStatement._unsigned_proof_gate(
        origin="own_result", lit_id="", proof_text=PROOF, proofs_listed=[],
        row={"stmt_id": SID, "proof_text": ""}, v_sign=v_sign, store=st, proof_no=1)
    closing = CL.statements_unsigned_reading(st)
    return {
        "bits": bool(v_sign.get("applied")),
        "secretary": bool(sec.get("ok")),
        "b_gate": not bool(b.get("refused")),
        "closing": int(closing.get("count") or 0) == 0,
    }


def test_four_gates_give_one_answer_on_a_recomputable_sign(
        tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _seed(st)
    issue_credential(st.root, proof_text=PROOF, statement_id=SID, manuscript=REL)
    answers = _answers(st)
    assert answers == {"bits": True, "secretary": True, "b_gate": True,
                       "closing": True}, answers


def test_four_gates_flip_together_when_the_credential_is_removed(
        tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _seed(st)
    issue_credential(st.root, proof_text=PROOF, statement_id=SID, manuscript=REL)
    sha = VS._sign_sha(PROOF)
    (pathlib.Path(st.root) / "out" / "vsigns" / f"{sha}.json").unlink()
    answers = _answers(st)
    assert answers == {"bits": False, "secretary": False, "b_gate": False,
                       "closing": False}, answers
