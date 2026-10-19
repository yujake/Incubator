# -*- coding: utf-8 -*-
"""判据：`evidence_kind="proof_review"` 必须有 V 那一签（2026-10-19，堵「假 proof_review」）。

## 为什么要有这一条（活证据）

`projects/mp1/data/statements.json` 里有 10 条 `evidence_kind="proof_review"`，它们的
`verification_id` / `reviewed_by` 全是 `null`、`bits` 是 `{}` —— 也就是说这 10 条
**自称「证明经逐行审阅」**，而写入时没有任何东西核过它。`schema.py:1071` 那段定义
逐字要求「`statements` 表的 `proof_text` 非空 ＋ V 的 `verifications` 里那一条签「成立」」，
但 2026-10-19 之前**没有任何代码强制**（唯一被强制的是 `disclaimer`，而那句话作者自己就能写）。

## 判据落在哪一层（以及为什么不是 `Statement.validate`）

跨表（其实是跨**文件账本**）的校验需要工作区根，而 `Statement.validate` 是字段级、
手上没有根；且它被 `rebuild` 重放与 `verify` 读侧共用 —— 把这条判据塞进去，会让
"读历史"变成"改历史"（存量那 10 条会当场把重建炸掉）。所以：

- **判据本体**：`verifications.proof_review_gap`（一处口径，写入期 / 审计期都读它）；
- **写入期闸**：`store.tx` 提交时的 `store._refuse_fake_proof_review` ⇒
  `ValueError: proof_review_without_evidence`，**整笔事务一行都不写**；
- **审计期档**：`verify._check_13` 的 `proof_review_without_verification`（**error**），
  逐条点名存量。

口径边界（业主 2026-10-19 裁定 A）：**只按那句定义判**，**不要求**在命题行回填
`verification_id`（那是更严的可选口径 B：它需要 V 签完之后回写 `statements`，属新的写路径）。

## 两侧 + 负控（只测一侧的判据可能是一条恒真的判据）

- ① **有凭据的 `proof_review` 收**：先落一条「成立」的签 ⇒ 这一行写得进去、
  `verify_all` 不点名；
- ② **无凭据的 `proof_review` 拒**：没有那一签 ⇒ 提交当场 `ValueError`
  （错误码在消息里），且**一行都没写进去**；审计期另一条网把它点成 error；
- ③ **负控**：把写入期那道闸拿掉（monkeypatch 成 no-op）⇒ 同一行**写得进去** ——
  于是"被拒"这件事只能来自那道闸，不是别的校验顺手挡的；
- ④ 三态旁支：最近一签是「有毛病」、或签的是**另一版**证明（`proof_sha256` 不符）、
  或 `proof_text` 空 ⇒ 都算**没有凭据**（各有独立理由串）；
- ⑤ 反真空：`heuristic` / `cross_check` 不受这条闸影响（它只管 `proof_review` 一档）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import schema as S
from agentflow import store as ST
from agentflow import verifications as VR
from agentflow import verify as VY
from agentflow.store import Store

#: 一条「成立」的审校结论（`record_verification` 会把它规范化再落盘）。
_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}

_PROOF = "1. 由定义直接得到 c(G) ≤ 1。\n2. 由 1 与假设 n ≥ 3 得结论。"


def _row(stmt_id: str = "000000", **kw) -> dict:
    """一条**合法**的 `statements` 行（除 `evidence_kind` 外都过 `Statement.validate`）。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "lemma",
           "statement_full": "设 G 是 3-正则图；则 c(G) ≤ 1。",
           "statement_text": "c(G) ≤ 1", "proof_text": _PROOF,
           "quote_reason": "我方自产命题，没有外部引文要比对",
           "evidence_kind": "proof_review", "status": "active",
           "created_at": "2026-10-19T00:00:00+08:00", "created_by": "test"}
    row.update(kw)
    S.Statement(**row).validate()
    return row


@pytest.fixture()
def ws(tmp_path: pathlib.Path) -> Store:
    """一个空的、已 init 的工作区（`data/` 就绪，`verifications/` 还不存在）。"""
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _sign(store: Store, stmt_id: str, proof_text: str = _PROOF, verdict: dict | None = None) -> dict:
    """替 V 落一签（与 `verify.verify_proof` 落盘的是同一行，只是不经模型）。"""
    return VR.record_verification(store.root, statement_id=stmt_id,
                                  proof_text=proof_text, verdict=verdict or _OK,
                                  verifier="agent-V")


def _write(store: Store, row: dict) -> None:
    """走真正的写入路径（`store.tx` 的提交块 —— 闸就在那里）。"""
    with store.tx("statements", actor="test", note="proof_review gate") as tx:
        tx.upsert("statements", row)


# --------------------------------------------------------------- ① 有凭据的收
def test_a_proof_review_with_a_signature_is_accepted(ws: Store):
    """正控：先有「成立」那一签 ⇒ 这一行**收**（并且审计期不点名它）。"""
    _sign(ws, "000000")
    _write(ws, _row())
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]

    rep = VY.verify_all(ws)
    codes = [i.code for i in rep.issues if i.table == "statements"]
    assert VR.CODE_AUDIT not in codes, rep.issues
    assert not [i for i in rep.issues if i.code == "proof_review_unchecked"], rep.issues
    # 判据本身也给"够"的读数（三态：`checked=True` 且 `ok=True`）
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is True and gap["checked"] is True, gap
    assert gap["verification_id"] == f"v-{S.format_id(1)}" and gap["sha_matches"] is True, gap


# --------------------------------------------------------------- ② 无凭据的拒
def test_a_proof_review_without_a_signature_is_refused_at_write_time(ws: Store):
    """负控①（写入期）：没有那一签 ⇒ **当场拒收**，且一行都没写进去。"""
    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    msg = str(exc.value)
    assert VR.CODE_WRITE in msg, msg
    assert "verifications" in msg and "verify_proof" in msg, msg
    # 整笔事务没生效（与其余校验失败同一处置）
    assert ws.rows("statements") == []


def test_the_same_row_stays_visible_to_the_audit_as_an_error(ws: Store):
    """负控②（审计期，管**存量**）：写入期之前就在盘上的那一行 ⇒ `error` 级点名。

    存量是怎么造出来的：把闸拿掉（等价于"改前写进去的那些"）—— 这也正是 ③ 的负控。
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ST, "_refuse_fake_proof_review", lambda *a, **k: None)
        _write(ws, _row())
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]

    rep = VY.verify_all(ws)
    hits = [i for i in rep.issues if i.code == VR.CODE_AUDIT]
    assert len(hits) == 1 and hits[0].level == "error", rep.issues
    assert hits[0].row_id == "000000", hits[0]
    # 账本读得出来（坏行才算"没查成"，那是 `proof_review_unchecked` 那一档）
    assert not [i for i in rep.issues if i.code == "proof_review_unchecked"], rep.issues
    # 消息里要能读出"哪一条、为什么、怎么改"
    assert "verifications/000000.jsonl" in hits[0].message, hits[0].message
    assert "heuristic" in hits[0].message, hits[0].message


# --------------------------------------------------------------- ③ 负控
def test_removing_the_write_gate_is_what_lets_the_bad_row_through(ws: Store):
    """负控③：把写入期那道闸拿掉 ⇒ 同一行**写得进去**。

    这条判据必须能"证明它会红"：如果闸被删掉，上面那条 `pytest.raises` 会失败 ——
    也就是说，② 里那次拒收**只能**来自这道闸（不是 schema 顺手挡的）。
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ST, "_refuse_fake_proof_review", lambda *a, **k: None)
        _write(ws, _row())
        assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]
    # 闸在时，同一行一个字都写不进去（恢复之后立刻再试一次）
    with pytest.raises(ValueError):
        _write(ws, _row(stmt_id="000001"))


# --------------------------------------------------------------- ④ 三态旁支
def test_a_defective_last_signature_is_not_a_signature(ws: Store):
    """最近一签是「有毛病」⇒ 不算凭据（`unresolved_errors > 0` 也签不住第 3 位）。"""
    _sign(ws, "000000", verdict=_BAD)
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is False and gap["checked"] is True, gap
    assert "有毛病" in gap["why"] and "unresolved_errors=1" in gap["why"], gap["why"]
    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    assert VR.CODE_WRITE in str(exc.value), str(exc.value)


def test_a_signature_for_another_version_does_not_cover_this_one(ws: Store):
    """签的是**另一版**证明（`proof_sha256` 不符）⇒ 不算凭据。

    台账记 `proof_sha256` 的唯一用途就是这个：不查它，"V 审过"会退化成
    "V 审过某个东西"—— 改完证明不再送审，签名照样成立，而没有任何读数能证伪。
    """
    _sign(ws, "000000", proof_text="1. （这是改之前那一版证明。）")
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is False and gap["sha_matches"] is False, gap
    assert "另一版" in gap["why"], gap["why"]
    with pytest.raises(ValueError):
        _write(ws, _row())


def test_a_proof_review_without_proof_text_is_refused(ws: Store):
    """`proof_text` 空 ⇒ 没有被审的那份证明，「逐行审阅过」没有对象。"""
    _sign(ws, "000000", proof_text="")
    gap = VR.proof_review_gap(ws.root, _row(proof_text=""))
    assert gap["ok"] is False and gap["checked"] is True, gap
    assert "proof_text" in gap["why"], gap["why"]
    with pytest.raises(ValueError):
        _write(ws, _row(proof_text=""))


def test_an_unreadable_ledger_is_not_checked_rather_than_passed(ws: Store):
    """台账坏行 ⇒ `checked=False`（**没查成**）—— 同一处置（拒收/点名），但理由不同。"""
    path = VR.verification_ledger_path(ws.root, "000000")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{这不是 JSON\n", encoding="utf-8")
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is False and gap["checked"] is False, gap
    assert gap["problems"], gap
    with pytest.raises(ValueError):
        _write(ws, _row())


# --------------------------------------------------------------- ⑤ 反真空
def test_the_gate_only_talks_about_proof_review(ws: Store):
    """反真空：同一份工作区里 `heuristic` / `cross_check` 的行照写不误。

    这条闸只认 `proof_review` 一档 —— 它不许顺手把"没审过的猜想"也拒掉
    （那会把"如实登记"重新挡在门外，正是 `Statement.validate` 那段注释里踩过的坑）。
    """
    _write(ws, _row(stmt_id="000000", evidence_kind="heuristic"))
    _write(ws, _row(stmt_id="000001", evidence_kind="cross_check"))
    assert {str(r.get("stmt_id")) for r in ws.rows("statements")} == {"000000", "000001"}
    rep = VY.verify_all(ws)
    assert [i for i in rep.issues if i.code == VR.CODE_AUDIT] == [], rep.issues
    assert not [i for i in rep.issues if i.code == "proof_review_unchecked"], rep.issues
