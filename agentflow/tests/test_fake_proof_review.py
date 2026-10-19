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

## 2026-10-19 晚补的那一批（"证明齐全、V 也签了，却只落 heuristic"）

上面那五条守的是**虚报**那一侧。真机 `projects/mp2` 的 `stmt:000003` 暴露的是**反方向**：
`proof_text` 1909 字、`verifications/000003.jsonl` 里 `v-000001` 签「成立」、
`proof_sha256` 与现行正文相符 —— 按定义这条**就是** `proof_review`，盘上却落 `heuristic`。
三条新判据（各带负控）：

- ⑥ **正控（写入路径）**：满足定义的行**必须写得进去** —— 而且**不许**顺手多要别的字段
  （`disclaimer` / `verification_id` / `reviewed_by` 一个都不是这一档的判据）。负控是
  "把闸改回要 `disclaimer` 才放行 ⇒ 这条红"（**实测过**：临时加一条
  `and not row.get("disclaimer")` 的判据，本文件 6 条变红）。
- ⑦ **作用域**：闸只核**这一笔改到的行**。别的行的历史缺陷挡住一笔无关写入时，
  "如实降档"这条出口本身也被堵死（`projects/mp1` 那种存量上任何 `statements` 写入
  都会撞 3 条历史 fake）—— 存量归审计期点名。
- ⑧ **降档告警**：够格却被写成 `heuristic` / `cross_check` ⇒ `verify_all` 报
  **warning** `weaker_than_evidence`（不是 error：降档是安全方向，但要让读数看见）。
  负控是"同一条凭据写成 `proof_review` ⇒ 这条告警不出现"（删掉判据则 ⑧ 红）。
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


# ============================================================================
# 2026-10-19 晚：反方向那一批（"证明齐全、V 也签了，却只落 heuristic"）
# ============================================================================

# ------------------------------------------------- ⑥ 正控：满足定义就必须写下
def test_a_row_meeting_the_definition_is_accepted_and_needs_nothing_else(ws: Store):
    """正控（⑥）：**只**按 `schema.EVIDENCE_KINDS` 那句定义判 ⇒ 这一行必须写得进去。

    "不多要别的字段"这件事在这里被钉成断言：行里**没有** `disclaimer`（`Statement`
    根本没有这一栏）、没有 `verification_id`、没有 `reviewed_by`、`bits` 是 `{}` ——
    而它照样得写得进去。**负控**：把写入期闸改回"要 `disclaimer` 才放行"，这条当场红
    （实测：临时给闸加一条 `and not row.get("disclaimer")` 的判据 ⇒
    `test_fake_proof_review.py` 里 6 条红，其中就有这一条）。
    """
    _sign(ws, "000000")
    row = _row()
    assert "disclaimer" not in row and "verification_id" not in row
    assert row.get("bits") in (None, {}), row.get("bits")
    _write(ws, row)
    written = ws.rows("statements")[0]
    assert written["evidence_kind"] == "proof_review", written
    # 审计侧对"够格且登记对了"的一行一个字都不说
    rep = VY.verify_all(ws)
    codes = [i.code for i in rep.issues if i.table == "statements"]
    assert VR.CODE_AUDIT not in codes and "weaker_than_evidence" not in codes, rep.issues


def test_the_refusal_message_lists_which_of_the_three_items_is_missing(ws: Store):
    """拒信要**逐项**说清缺哪一项（业主 2026-10-19：「拒收消息要能让人看懂」）。

    三条必填项各给一行 ✓/✗ —— 只给一段散文时，读的人得自己在里面找缺的是哪一格。
    这里没有任何一签 ⇒ 第 2、3 项是 ✗，第 1 项（`proof_text` 非空）是 ✓。
    """
    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    msg = str(exc.value)
    assert VR.CODE_WRITE in msg, msg
    assert "✗" in msg and "✓" in msg, msg
    assert "verifications/<命题号>.jsonl" in msg, msg
    assert "disclaimer" in msg, (
        "拒信要明说「这一档**不**要 disclaimer」——否则读的人会去补一个不在判据里的字段：" + msg)


# ------------------------------------------------------------------- ⑦ 作用域
def test_a_legacy_fake_row_does_not_block_writing_an_unrelated_row(ws: Store):
    """作用域（⑦）：**别的行**的历史缺陷不许挡住这一笔写入。

    改前这道闸核整张 `statements` 表 ⇒ `projects/mp1` 那种存量（10 条里有 3 条查不到
    「成立」那一签）上，**任何**写入都被拒 —— 连"如实降档成 heuristic"这条出口本身
    都写不进去（而它正是拒信推荐的处置）。存量归审计期点名（error 级），写入期只核
    这一笔真改到的行。
    """
    # 造一条"改前写进去的"存量：把闸拿掉写一条没有签的 proof_review。
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ST, "_refuse_fake_proof_review", lambda *a, **k: None)
        _write(ws, _row(stmt_id="000000"))
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]

    # 闸在时：写一条**无关**的新行（如实降档的那条出口）必须成功。
    _write(ws, _row(stmt_id="000001", evidence_kind="heuristic"))
    assert {str(r.get("stmt_id")) for r in ws.rows("statements")} == {"000000", "000001"}

    # 而存量那一条仍然被审计期点成 error（收窄作用域**没有**放松存量这一侧）。
    rep = VY.verify_all(ws)
    hits = [i for i in rep.issues if i.code == VR.CODE_AUDIT]
    assert [h.row_id for h in hits] == ["000000"], rep.issues
    assert hits[0].level == "error", hits[0]

    # 同一笔里改到那一条存量 ⇒ 仍然被拒（"改了它"就归写入期管）
    with pytest.raises(ValueError):
        _write(ws, _row(stmt_id="000000", statement_text="换了一句短版"))


# --------------------------------------------------------- ⑧ 降档告警（warning）
def test_a_signed_statement_written_as_heuristic_is_reported_as_a_downgrade(ws: Store):
    """降档告警（⑧）：凭据齐全却写成 `heuristic` ⇒ **warning** `weaker_than_evidence`。

    这是真机 `projects/mp2` 的 `stmt:000003` 的形态（`proof_text` 非空 ＋ V 签「成立」
    ＋ sha 相符，盘上落 `heuristic`）。降档是安全方向 ⇒ **不是 error**（它不该把
    `verify` 判成失败），但必须是**看得见的**：长期把强结果写成弱档，论文的强度声明
    会系统性偏低，而此前没有任何读数会指出这一点。

    **负控**：同一条凭据写成 `proof_review` ⇒ 这条告警**不出现**（所以它是"降档"那一格
    的判据，不是恒真的一句）。把 `verify._check_13` 里那一段删掉 ⇒ 本条红（实测过）。
    """
    _sign(ws, "000000")
    _write(ws, _row(evidence_kind="heuristic"))
    rep = VY.verify_all(ws)
    hits = [i for i in rep.issues if i.code == "weaker_than_evidence"]
    assert len(hits) == 1, rep.issues
    assert hits[0].level == "warning", hits[0]          # 降档是安全方向 ⇒ 不是 error
    assert hits[0].row_id == "000000", hits[0]
    assert "v-" in hits[0].message and "proof_review" in hits[0].message, hits[0].message
    # 它不是 error ⇒ 不把工作区判成失败，但报告里读得到（warning 计数 ≥1）
    assert not [i for i in rep.issues if i.code == "weaker_than_evidence" and i.level == "error"]
    assert len(rep.warnings) >= 1, rep.issues

    # 负控：同样凭据、写成 proof_review ⇒ 告警消失
    with pytest.MonkeyPatch.context():
        _write(ws, _row(evidence_kind="proof_review"))
    rep2 = VY.verify_all(ws)
    assert [i for i in rep2.issues if i.code == "weaker_than_evidence"] == [], rep2.issues


def test_a_heuristic_row_without_a_signature_is_not_reported(ws: Store):
    """三态旁支（⑧ 的反真空）：没有那一签的 `heuristic` 行**不许**被这条告警点名。

    "够格却写弱" 与 "确实没有凭据" 是两件事。把后者也报出来，这条告警会变成
    "所有猜想都是缺陷" —— 那是把读数变成噪音，而噪音会被训练成忽略。
    """
    _write(ws, _row(evidence_kind="heuristic"))
    rep = VY.verify_all(ws)
    assert [i for i in rep.issues if i.code == "weaker_than_evidence"] == [], rep.issues


def test_the_concept_rows_are_not_judged_by_the_grade_chain(ws: Store):
    """反真空（⑧）：概念行（`kind="concept"`）不参与等级链，跳过这条判据。

    概念没有真值（只有良定义没良定义），把它的 `proof_text` 读成"一份被审过的证明"
    是另一种口径错误（`evidencebits.derive_grade` 的 `not_applicable` 同一口径）。
    """
    _sign(ws, "000000")
    _write(ws, _row(kind="concept", evidence_kind="heuristic"))
    rep = VY.verify_all(ws)
    assert [i for i in rep.issues if i.code == "weaker_than_evidence"] == [], rep.issues


# --------------------------------------- ⑨ 正控走**真实的写者**：F 的 `_proof_outlet`
def test_fs_outlet_promotes_a_row_once_v_has_signed(ws: Store):
    """正控（⑨）：F 的 `_proof_outlet` 按 V 那一签定档，并在复用时**就地升档**。

    真机的时间线（`projects/mp2`）：F/B 在 21:06 落行（那一刻还没有签 ⇒ 只能
    `heuristic`），V 在 21:09 才签。**没有任何东西回头改那一行** —— 于是够格的强结果
    永远停在弱档。这条判据钉住修法：同样的论证再交一遍时，F 认出"这一行现在够格了"，
    就地升档（一行 update，走同一个写入闸），并报 `promoted=True`。
    """
    from agentflow.agent_f import AgentF

    f = AgentF(ws, config={"workspace_root": str(ws.root)})
    sg = {"sid": "s1", "text": "对每个内点 P，弦长函数不是常值", "testable": "L_P 不恒等"}
    product = {"product": "proof", "strategy": "三角多项式",
               "steps": [{"n": 1, "text": "由定义得 L²/4 = N/A²"}]}
    plan = {"plan_id": "000000"}

    first = f._proof_outlet(product, sg, plan=plan)
    assert first["ok"] and not first["reused"], first
    assert first["evidence_kind"] == "heuristic", first   # 还没有签 ⇒ 不许自报强档
    stmt_id = first["statement_id"]
    row = next(r for r in ws.rows("statements") if str(r.get("stmt_id")) == stmt_id)

    _sign(ws, stmt_id, proof_text=str(row["proof_text"]))

    second = f._proof_outlet(product, sg, plan=plan)     # 同样的论证再交一遍
    assert second["ok"] and second["reused"], second
    assert second["promoted"] is True, second
    assert second["evidence_kind"] == "proof_review", second
    after = [r for r in ws.rows("statements") if str(r.get("stmt_id")) == stmt_id]
    assert len(after) == 1, after                          # 升档不是登记第二行
    assert after[0]["evidence_kind"] == "proof_review", after[0]


def test_fs_outlet_does_not_promote_without_a_signature(ws: Store):
    """反真空（⑨）：没有那一签时 F **不许**升档 —— 走同一条路要落回 `heuristic`。

    这条与上一条成对：没有它，"升档"可能被写成"每次都写 proof_review"，
    而那正是这道闸要堵的虚报。
    """
    from agentflow.agent_f import AgentF

    f = AgentF(ws, config={"workspace_root": str(ws.root)})
    sg = {"sid": "s1", "text": "对每个内点 P，弦长函数不是常值", "testable": "L_P 不恒等"}
    product = {"product": "proof", "strategy": "三角多项式",
               "steps": [{"n": 1, "text": "由定义得 L²/4 = N/A²"}]}
    plan = {"plan_id": "000000"}
    first = f._proof_outlet(product, sg, plan=plan)
    _sign(ws, first["statement_id"], proof_text="这是**另一版**证明（不是被审的那一份）")
    second = f._proof_outlet(product, sg, plan=plan)
    assert second["ok"] and second["reused"] and second["promoted"] is False, second
    row = next(r for r in ws.rows("statements")
               if str(r.get("stmt_id")) == second["statement_id"])
    assert row["evidence_kind"] == "heuristic", row

