# -*- coding: utf-8 -*-
"""判据：`evidence_kind="proof_review"` 必须有 V 那一签（2026-10-19，堵「假 proof_review」）。
## 为什么要有这一条（活证据）
`projects/mp1/data/statements.json` 里有 10 条 `evidence_kind="proof_review"`，它们的 `verification_id`
/ `reviewed_by` 全是 `null`、`bits`
是 `{}` —— 这 10 条自称「证明经逐行审阅」，而写入时没有任何东西核过它。`schema.py:1071`那段定义逐字要求「`statements` 表的 `proof_text` 非空 ＋ V
的 `verifications` 里那一条签「成立」」，但
2026-10-19之前没有任何代码强制（唯一被强制的是 `disclaimer`，而那句话作者自己就能写）。
## 判据落在哪一层（为什么不是 `Statement.validate`）
跨表（其实是跨文件账本）的校验需要工作区根，而 `Statement.validate` 是字段级、手上没有根；且它被 `rebuild` 重放与 `verify` 读侧共用 —— 把这条判据塞进去，
会让"读历史"变成"改历史"（存量那 10 条会当场把重建炸掉）。
所以判据本体是 `verifications.proof_review_gap`（一处口径，写入期 / 审计期都读它）；
写入期闸是 `store.tx`提交时的 `store._refuse_fake_proof_review`
⇒ `ValueError: proof_review_without_evidence`，整笔事务一行都不写；审计期档是 `verify._check_13`
的 `proof_review_without_verification`（error），逐条点名存量。
口径边界（业主 2026-10-19 裁定 A）：只按那句定义判，不要求在命题行回填 `verification_id`（那是更严的可选口径 B：需要 V 签完之后回写 `statements`，属新的写路径）。
## 两侧 + 负控（只测一侧的判据可能是一条恒真的判据）
① 有凭据的 `proof_review` 收：先落一条「成立」的签 ⇒ 这一行写得进去、`verify_all` 不点名；② 无凭据的 `proof_review` 拒：没有那一签 ⇒
提交当场 `ValueError`（错误码在消息里），且一行都没写进去，
审计期另一条网把它点成 error；③ 负控：把写入期那道闸拿掉（monkeypatch 成 no-op）⇒ 同一行写得进去 —— 于是"被拒"这件事只能来自那道闸，不是别的校验顺手挡的。④ 三态旁支：
最近一签是「有毛病」、
或签的是另一版证明（`proof_sha256` 不符）、或 `proof_text` 空 ⇒ 都算没有凭据（各有独立理由串）；⑤ 反真空：`heuristic` / `cross_check`
不受这条闸影响（它只管 `proof_review` 一档）。
⑥ 正控（写入路径，反方向的事实）：真机 `projects/mp2` 的 `stmt:000003` 有 `proof_text` 1909
字、`verifications/000003.jsonl`里 `v-000001` 签「成立」
、`proof_sha256` 与现行正文相符，按定义这条就是 `proof_review`，盘上却落 `heuristic`。所以满足定义的行必须写得进去，且不许顺手多要别的字段（`disclaimer`
/ `verification_id`
/ `reviewed_by` 一个都不是这一档的判据）；负控是"把闸改回要 `disclaimer` 才放行 ⇒这条红"（实测过：临时加一条 `and not row.get("disclaimer")` 的判据，
本文件 6 条变红）。⑦ 作用域：
闸只核这一笔改到的行。别的行的历史缺陷挡住一笔无关写入时，"如实降档"这条出口本身也被堵死（`projects/mp1` 那种存量上任何 `statements` 写入都会撞 3 条历史 fake）——
存量归审计期点名。⑧ 降档告警：
够格却被写成 `heuristic` / `cross_check` ⇒ `verify_all` 报 warning `weaker_than_evidence`（不是 error：降档是安全方向，但要让读数看见）；
负控是"同一条凭据写成 `proof_review` ⇒ 这条告警不出现"（删掉判据则 ⑧ 红）。"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import store as ST
from agentflow import verifications as VR
from agentflow import verify as VY
from agentflow.store import Store

from conftest import seed_statement_row


# ---------------------------------------------------------------- 命题形态闸的夹具答案
#
# 2026-11-07（业主裁定）：F 交稿之前多了一道"命题形态闸"
# （`agent_f/core.py::_proposition_form_gate` → `Secretary.judge_proposition_form`）。
# 它是一次模型调用，而这一份夹具里没有模型 ⇒ 判据会 fail-closed 拒收（那是对的行为）。
# 下面这个 autouse 夹具只替代那一次调用（给一个"形态合规"的答案），不摘闸：
# 闸照跑、判据仍是那一处实现；写成补丁而不是"让闸放行"，是为了让"夹具里没有模型"
# 这件事只在这一个地方被交代一次。
@pytest.fixture(autouse=True)
def _proposition_form_answers_ok(monkeypatch):
    from agentflow import secretary as _SEC

    monkeypatch.setattr(
        _SEC.Secretary, "judge_proposition_form",
        lambda self, **_kw: {"checked": True, "well_formed": True,
                             "conditions": "夹具：前提", "conclusion": "夹具：结论",
                             "problems": [], "decision": "夹具：形态合规",
                             "refused": "", "reason": "夹具：形态合规"})


def _judge_for(verdict: dict) -> dict:
    """夹具：按这一行的判词给秘书的轴（只给两态；「有毛病」⇒ fault）。

    2026-11-06 裁定 2 之后，台账的轴只能来自秘书。夹具写的是"这一行当年怎么判的"，
    所以轴跟着判词走：成立 ⇒ clean、有毛病 ⇒ fault、其余（看不出来一类）⇒ 空轴。
    这不是"按字面定轴"—— 这条断言在夹具里，是声明这一段是什么现场，不是判据。
    """
    word = str((verdict or {}).get("verdict") or "")
    if word == "成立":
        return {"checked": True, "axis": "clean", "decision": "没问题",
                "reason": "夹具：秘书判 clean"}
    if word == "有毛病":
        return {"checked": True, "axis": "fault", "decision": "有缺陷要指出",
                "reason": "夹具：秘书判 fault"}
    return {"checked": False, "axis": "", "decision": "",
            "reason": "夹具：判词不是两态，秘书没给轴"}

#: 一条「成立」的审校结论（`record_verification` 会把它规范化再落盘）。
_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}

_PROOF = "1. 由定义直接得到 c(G) ≤ 1。\n2. 由 1 与假设 n ≥ 3 得结论。"


def _bits(*, reviewed: bool = False, kind: str = "lemma",
          text: str = _PROOF) -> dict:
    """这条命中的五元位（2026-11-05 口径：先预置位，档位只由等级反算）。

    `_row()` 是有证明正文的一行 ⇒ 第 2 位为真；`reviewed` 说这一行有没有把 V
    那一签读进第 3 位（本文件量的正是"签在台账里、位/档位各读成什么"）。
    """
    return EB.bits_of(origin="own_result", proof=True, proof_process=text,
                      reviewed=reviewed, kind=kind,
                      reviewed_by=({"evidence": "verifications/000000.jsonl#v-000003"}
                                   if reviewed else None))


def _row(stmt_id: str = "000000", **kw) -> dict:
    """一条合法的 `statements` 行（除 `evidence_kind` 外都过 `Statement.validate`）。

    2026-11-05 起 `evidence_kind` 只是历史列：判定面读的是 `bits` 现算的等级。
    所以这里的默认行也带上第 2 位（有证明）；要第 3 位为真的行显式传
    `bits=_bits(reviewed=True)` —— 不再靠"只写历史列"造"已签"的现场。
    默认 `bits` 按这一行的 `kind` 现算（概念行是 `not_applicable`，与
    `Statement.validate` 用同一个 kind）。
    """
    kind = str(kw.get("kind") or "lemma")
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
    row = {"stmt_id": stmt_id, "origin": "own_result", "derived_from": ["999999"], "kind": kind,
           "statement_full": "设 G 是 3-正则图；则 c(G) ≤ 1。",
           "statement_text": "c(G) ≤ 1", "proof_text": _PROOF,
           "quote_reason": "我方自产命题，没有外部引文要比对",
           "evidence_kind": "proof_review", "status": "active",
           "bits": _bits(kind=kind), "created_at": "2026-10-19T00:00:00+08:00",
           "created_by": "test"}
    row.update(kw)
    S.Statement(**row).validate()
    return row


@pytest.fixture()
def ws(tmp_path: pathlib.Path) -> Store:
    """一个空的、已 init 的工作区（`data/` 就绪，`verifications/` 还不存在）。"""
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _sign(store: Store, stmt_id: str, proof_text: str = _PROOF, verdict: dict | None = None,
          *, times: int | None = None, flip: bool = False) -> dict:
    """替 V 落一签（与 `verify.verify_proof` 落盘的是同一行，只是不经模型）。

    2026-10-29（业主「V 签门槛 = 连续 3 次没问题」）之后，「成立」要连续
    `SIGN_STREAK_NEED` 次才签住 ⇒ 默认落三次（同一份正文）；「有毛病」那一档只落一次
    （它本来就不签）。返回最后一次那一行。

    `flip=True` 走真写口（`store`）：最后一转会把第 3 位翻进命题行 —— 那是 2026-11-05
    口径下"行上的五元位反映这一签"的唯一正路。默认 False 只落台账，用于"签在台账里、
    行上还没读进第 3 位"的历史形态（本文件量那两态的差）。
    """
    want = verdict or _OK
    n = int(times if times is not None
            else (VR.SIGN_STREAK_NEED if str(want.get("verdict")) == "成立" else 1))
    row: dict = {}
    flipped: dict = {}
    for _i in range(max(1, n)):
        row = VR.record_verification(store.root, statement_id=stmt_id,
                                     proof_text=proof_text, verdict=want,
                                     verifier="agent-V",
                                     store=(store if flip else None),
                                     proof_no=1, secretary_judge=_judge_for(want))
        # 翻位那一转才是"这一签"（后面再投的几票是复查读数，回填痕不会重写）
        if not flipped and bool((row.get("statement_writeback") or {}).get("written")):
            flipped = row
    return flipped or row


def _write(store: Store, row: dict) -> None:
    """走真正的写入路径（`store.tx` 的提交块 —— 闸就在那里）。"""
    with store.tx("statements", actor="test", note="proof_review gate") as tx:
        tx.upsert("statements", row)


# --------------------------------------------------------------- ① 有凭据的收
def test_a_proof_review_with_a_signature_is_accepted(ws: Store):
    """正控：先有「成立」那一签 ⇒ 这一行收（并且审计期不点名它）。

    改前断言 → 改后断言（为什么）：`gap["verification_id"] == v-000001` →
    `== v-000003`（最后一次那一签）。业主 2026-10-29 的连续 3 次口径下，"签住"的那一签
    必然是连续第 3 次（`_sign` 默认落三次），凭据那一格记的是最近那一签，
    所以它从第 1 行变成第 3 行；断言的意思（"凭据指向落盘的那一签"）一个字没变。
    """
    signed = _sign(ws, "000000")
    _write(ws, _row())
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]

    rep = VY.verify_all(ws)
    codes = [i.code for i in rep.issues if i.table == "statements"]
    assert VR.CODE_AUDIT not in codes, rep.issues
    assert not [i for i in rep.issues if i.code == "proof_review_unchecked"], rep.issues
    # 判据本身也给"够"的读数（三态：`checked=True` 且 `ok=True`）
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is True and gap["checked"] is True, gap
    assert gap["verification_id"] == str(signed["verification_id"]), gap
    assert gap["verification_id"] == f"v-{S.format_id(VR.SIGN_STREAK_NEED)}", gap
    assert gap["sha_matches"] is True, gap


# --------------------------------------------------------------- ② 无凭据的拒
def test_a_proof_review_without_a_signature_is_refused_at_write_time(ws: Store):
    """负控①（写入期）：没有那一签 ⇒ 当场拒收，且一行都没写进去。"""
    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    msg = str(exc.value)
    assert VR.CODE_WRITE in msg, msg
    assert "verifications" in msg and "verify_proof" in msg, msg
    # 整笔事务没生效（与其余校验失败同一处置）
    assert ws.rows("statements") == []


def test_the_same_row_stays_visible_to_the_audit_as_an_error(ws: Store):
    """负控②（审计期，管存量）：写入期之前就在盘上的那一行 ⇒ `error` 级点名。

        存量是怎么造出来的：把闸拿掉（等价于"改前写进去的那些"）—— 这也正是 ③ 的负控。"""
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
    """负控③：把写入期那道闸拿掉 ⇒ 同一行写得进去。

        这条判据必须能"证明它会红"：如果闸被删掉，上面那条 `pytest.raises` 会失败 ——
        也就是说，② 里那次拒收只能来自这道闸（不是 schema 顺手挡的）。"""
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
    """签的是另一版证明（`proof_sha256` 不符）⇒ 不算凭据，但不拦写入。

        台账记 `proof_sha256` 的唯一用途就是这个：不查它，"V 审过"会退化成
        "V 审过某个东西"—— 改完证明不再送审，签名照样成立，而没有任何读数能证伪。

        2026-10-22 口径变化（业主：哈希是读数，不是授权凭证）：这一条不再在写入期
        拒收 —— "正文改过了"是正常动作，任何写入路径都不许因为 sha 不符被拒。`gap` 仍判
        `ok=False`（这一行现在够不上 `proof_review`），但盘上那一行写得进去；"签过、
        签的是旧版"这件事由收工门 R10 的 `stale_ids` 与逐条证明的 `proofs_stale` 读出来
        （判据见 `tests/test_proof_review_reaches_the_statement.py` 的负控一）。"""
    _sign(ws, "000000", proof_text="1. （这是改之前那一版证明。）")
    gap = VR.proof_review_gap(ws.root, _row())
    assert gap["ok"] is False and gap["sha_matches"] is False, gap
    assert "另一版" in gap["why"], gap["why"]
    assert gap["state"] == "stale", gap
    # 写入期闸只问"有没有过「成立」那一签"：签的是旧版 ⇒ 是读数（待复核），不是拒收理由。
    assert VR.proof_review_gaps(ws.root, [_row()]) == [], "stale 不许被折成「没有凭据」"
    _write(ws, _row())
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]


def test_a_proof_review_without_proof_text_is_refused(ws: Store):
    """`proof_text` 空 ⇒ 没有被审的那份证明，「逐行审阅过」没有对象。"""
    _sign(ws, "000000", proof_text="")
    gap = VR.proof_review_gap(ws.root, _row(proof_text=""))
    assert gap["ok"] is False and gap["checked"] is True, gap
    assert "proof_text" in gap["why"], gap["why"]
    with pytest.raises(ValueError):
        _write(ws, _row(proof_text=""))


def test_an_unreadable_ledger_is_not_checked_rather_than_passed(ws: Store):
    """台账坏行 ⇒ `checked=False`（没查成）—— 同一处置（拒收/点名），但理由不同。"""
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
    """正控（⑥）：只按 `schema.EVIDENCE_KINDS` 那句定义判 ⇒ 这一行必须写得进去。

        "不多要别的字段"这件事在这里被钉成断言：行里没有 `disclaimer`（`Statement`
        根本没有这一栏）、没有 `verification_id`、没有 `reviewed_by` —— 而它照样得
        写得进去。负控：把写入期闸改回"要 `disclaimer` 才放行"，这条当场红
        （实测：临时给闸加一条 `and not row.get("disclaimer")` 的判据 ⇒
        `test_fake_proof_review.py` 里 6 条红，其中就有这一条）。

        2026-11-05：`bits` 不再是"可省的第 4 个字段"，而是判定面本身 ——
        这一行带着第 2、3 位的真（`proof ∧ reviewed` ⇒ 现算 `pre_theorem`），
        所以审计侧不会把它读成"够格却降档"。"""
    _sign(ws, "000000")
    row = _row(bits=_bits(reviewed=True))
    assert "disclaimer" not in row and "verification_id" not in row
    assert row["bits"]["proof"] is True and row["bits"]["reviewed"] is True, row["bits"]
    _write(ws, row)
    written = ws.rows("statements")[0]
    assert written["evidence_kind"] == "proof_review", written
    assert EB.derive_grade(EB.bits_from_row(written)) == "pre_theorem", written["bits"]
    # 审计侧对"够格且登记对了"的一行一个字都不说
    rep = VY.verify_all(ws)
    codes = [i.code for i in rep.issues if i.table == "statements"]
    assert VR.CODE_AUDIT not in codes and "weaker_than_evidence" not in codes, rep.issues


def test_the_refusal_message_lists_which_of_the_three_items_is_missing(ws: Store):
    """拒信要逐项说清缺哪一项（业主 2026-10-19：「拒收消息要能让人看懂」）。

        三条必填项各给一行 / —— 只给一段散文时，读的人得自己在里面找缺的是哪一格。
        这里没有任何一签 ⇒ 第 2、3 项是 ，第 1 项（`proof_text` 非空）是 。"""
    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    msg = str(exc.value)
    assert VR.CODE_WRITE in msg, msg
    assert "✗" in msg and "✓" in msg, msg
    assert "verifications/<命题号>.jsonl" in msg, msg
    assert "disclaimer" in msg, (
        "拒信要明说「这一档不要 disclaimer」——否则读的人会去补一个不在判据里的字段：" + msg)


# ------------------------------------------------------------------- ⑦ 作用域
def test_a_legacy_fake_row_does_not_block_writing_an_unrelated_row(ws: Store):
    """作用域（⑦）：别的行的历史缺陷不许挡住这一笔写入。

        改前这道闸核整张 `statements` 表 ⇒ `projects/mp1` 那种存量（10 条里有 3 条查不到
        「成立」那一签）上，任何写入都被拒 —— 连"如实降档成 heuristic"这条出口本身
        都写不进去（而它正是拒信推荐的处置）。存量归审计期点名（error 级），写入期只核
        这一笔真改到的行。"""
    # 造一条"改前写进去的"存量：把闸拿掉写一条没有签的 proof_review。
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ST, "_refuse_fake_proof_review", lambda *a, **k: None)
        _write(ws, _row(stmt_id="000000"))
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]

    # 闸在时：写一条无关的新行（如实降档的那条出口）必须成功。
    _write(ws, _row(stmt_id="000001", evidence_kind="heuristic"))
    assert {str(r.get("stmt_id")) for r in ws.rows("statements")} == {"000000", "000001"}

    # 而存量那一条仍然被审计期点成 error（收窄作用域没有放松存量这一侧）。
    rep = VY.verify_all(ws)
    hits = [i for i in rep.issues if i.code == VR.CODE_AUDIT]
    assert [h.row_id for h in hits] == ["000000"], rep.issues
    assert hits[0].level == "error", hits[0]

    # 同一笔里改到那一条存量 ⇒ 仍然被拒（"改了它"就归写入期管）
    with pytest.raises(ValueError):
        _write(ws, _row(stmt_id="000000", statement_text="换了一句短版"))


# --------------------------------------------------------- ⑧ 降档告警（warning）
def test_a_signed_statement_written_as_heuristic_is_reported_as_a_downgrade(ws: Store):
    """降档告警（⑧）：凭据齐全却写成 `heuristic` ⇒ warning `weaker_than_evidence`。

        这是真机 `projects/mp2` 的 `stmt:000003` 的形态（`proof_text` 非空 ＋ V 签「成立」
        ＋ sha 相符，盘上落 `heuristic`）。降档是安全方向 ⇒ 不是 error（它不该把
        `verify` 判成失败），但必须是看得见的：长期把强结果写成弱档，论文的强度声明
        会系统性偏低，而此前没有任何读数会指出这一点。

        负控：同一条凭据写成 `proof_review` ⇒ 这条告警不出现（所以它是"降档"那一格
        的判据，不是恒真的一句）。把 `verify._check_13` 里那一段删掉 ⇒ 本条红（实测过）。

        2026-11-05 改读等级之后，这条警告的判据是"第 2 位为真、V 那一签在台账里，
        而第 3 位没翻、现算等级仍低于 `pre_theorem`"：所以弱档那一行的 `bits` 只写
        第 2 位；负控那行把第 3 位也落真（档位由等级反算，历史列不再自己说话）。
        """
    _sign(ws, "000000")
    _write(ws, _row(evidence_kind="heuristic", bits=_bits(reviewed=False)))
    rep = VY.verify_all(ws)
    hits = [i for i in rep.issues if i.code == "weaker_than_evidence"]
    assert len(hits) == 1, rep.issues
    assert hits[0].level == "warning", hits[0]          # 降档是安全方向 ⇒ 不是 error
    assert hits[0].row_id == "000000", hits[0]
    assert "v-" in hits[0].message and "proof_review" in hits[0].message, hits[0].message
    # 它不是 error ⇒ 不把工作区判成失败，但报告里读得到（warning 计数 ≥1）
    assert not [i for i in rep.issues if i.code == "weaker_than_evidence" and i.level == "error"]
    assert len(rep.warnings) >= 1, rep.issues

    # 负控：同样凭据、把第 3 位也落真、写成 proof_review ⇒ 等级算出 pre_theorem，告警消失
    with pytest.MonkeyPatch.context():
        _write(ws, _row(evidence_kind="proof_review", bits=_bits(reviewed=True)))
    rep2 = VY.verify_all(ws)
    assert [i for i in rep2.issues if i.code == "weaker_than_evidence"] == [], rep2.issues


def test_a_heuristic_row_without_a_signature_is_not_reported(ws: Store):
    """三态旁支（⑧ 的反真空）：没有那一签的 `heuristic` 行不许被这条告警点名。

        "够格却写弱" 与 "确实没有凭据" 是两件事。把后者也报出来，这条告警会变成
        "所有猜想都是缺陷" —— 那是把读数变成噪音，而噪音会被训练成忽略。"""
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


# --------------------------------------- ⑨ 正控走真实的写者：F 的 `_proof_outlet`
#: `_proof_outlet` 按 steps 拼出来的那一份正文（`1. …（前提）`）；要铺历史行时，
#: 行上的 `proof_text` 必须与它逐字相同，F 才会把这一笔认成"同一条论证再交一遍"。
_OUTLET_BODY = "1. 由定义得 L²/4 = N/A²（前提）"


def _outlet_fixture(ws: Store) -> tuple[dict, dict, dict, str]:
    """⑨ 的现场：先铺一条无签历史行（真机 21:06 那一形态），返回 (f 的入参…)。

    为什么不能走"新建一行"那条路（2026-11-05）：严格准入闸下"无签的证明正文"
    不能经 `register_statement` 落盘；而 `signed_v_handoffs` 又会在登记入口给
    "即将写的那一份正文"补一份真 pending 签 —— 于是新建那一档会被 2026-11-05 的
    登记期回填（`verifications._grade_recomputed_from_signature`）当场升到
    `proof_review`（签是真的，不是 F 自报）。本组要量的"没有签时停在 `heuristic`"
    因此只能按真机历史行的形态造现场：直接铺一行（不经过准入闸）。改的是
    "怎么造现场"，不是判据与期望值（同 `test_f_unsigned_output_is_not_a_proof` 的
    现行做法）。
    """
    sg = {"sid": "s1", "text": "对每个内点 P，弦长函数不是常值", "testable": "L_P 不恒等"}
    product = {"product": "proof", "strategy": "三角多项式",
               "steps": [{"n": 1, "text": "由定义得 L²/4 = N/A²"}]}
    plan = {"plan_id": "000000"}
    full = sg["text"] + "；这一条的可检验形式：" + sg["testable"]
    seeded = seed_statement_row(
        ws, proof_text=_OUTLET_BODY, statement_full=full, statement_text=sg["text"],
        kind="conjecture", label="F 攻坚 000000 子目标 s1",
        evidence_kind="heuristic",
        # 2026-11-05：历史行也要带第 2 位 —— 这一行有证明正文；第 3 位留假（还没签）。
        # 只铺 proof_text / evidence_kind 的旧现场在新口径下现算仍是 conjecture。
        bits=_bits(reviewed=False, kind="conjecture", text=_OUTLET_BODY),
        quote_reason="F 交来的论证，V 还没签（历史形态：直接铺行）")
    return sg, product, plan, str(seeded["stmt_id"])


def test_fs_outlet_promotes_a_row_once_v_has_signed(ws: Store):
    """正控（⑨）：F 的 `_proof_outlet` 按 V 那一签定档，并在复用时就地升档。

        真机的时间线（`projects/mp2`）：F/B 在 21:06 落行（那一刻还没有签 ⇒ 只能
        `heuristic`），V 在 21:09 才签。改前那一签只进台账、没人回头改这一行 ——
        于是够格的强结果永远停在弱档。这条判据钉住修法：同样的论证再交一遍时，F
        认出"这一行现在够格了"，就地升档（一行 update，走同一个写入闸），并报
        `promoted=True`。

        2026-11-05：V 的签走真写口（`_sign(..., flip=True)`）会翻第 3 位，
        `_grade_recomputed` 的回填痕由那一笔落下；F 这一笔再把历史列按等级升上去。
    """
    from agentflow.agent_f import AgentF

    sg, product, plan, stmt_id = _outlet_fixture(ws)
    f = AgentF(ws, config={"workspace_root": str(ws.root)})

    first = f._proof_outlet(product, sg, plan=plan)
    assert first["ok"] and first["reused"], first
    assert first["promoted"] is False, first
    assert first["evidence_kind"] == "heuristic", first   # 还没有签 ⇒ 不许自报强档
    row = next(r for r in ws.rows("statements") if str(r.get("stmt_id")) == stmt_id)
    # B-2：首次登记没有 V 签 ⇒ 必须从猜想进；改前 F 直写 lemma（跳过这一阶段）。
    assert row["kind"] == "conjecture", row
    assert row["evidence_kind"] == "heuristic", row
    # 反真空：这一行真的还没有签 —— 凭据面判"不够格"，也没有登记期回填的痕。
    assert VR.proof_review_gap(ws.root, row).get("ok") is False, row
    assert VR.GRADE_RECOMPUTED_KEY not in row, row

    signed = _sign(ws, stmt_id, proof_text=str(row["proof_text"]), flip=True)
    assert signed.get("verification_id"), signed

    # 2026-11-07（业主裁定：登记与写证明解耦）：F 不再登记；"V 签之后按 sha 认领并升档"
    # 发生在 B 的收录那一笔（同一份稿、同一行、不新登记）。
    import pathlib

    from agentflow import depsection as DS
    from agentflow.agent_b import AgentB

    rel = str(first.get("manuscript_path") or "")
    mtext = pathlib.Path(ws.root, rel).read_text(encoding="utf-8")
    # 稿头那个号是"这一行已经在册"的号：交给 B 时去掉，免得被当成"新登记的候选号"
    # （D2 的 `stmt_id_taken` 判据管的是新建那一档；这里要的是同一行升档）。
    mtext = "\n".join(line for line in mtext.splitlines()
                      if not line.lstrip().startswith("- 命题号"))
    body = DS.proof_body(mtext).strip("\n")
    second = AgentB(ws, extractor=None, extract_text=None).register_statement(
        statement_full=str(row["statement_full"]),
        statement_text=str(row.get("statement_text") or ""),
        origin="own_result", derived_from=["999999"], kind="conjecture",
        # 档位按 V 的账本现算（`_proof_tier` → `proof_review`）：B 收到这个档之后
        # 仍会按盘上那一签复核，不是自报。
        evidence_kind="proof_review",
        label=f"F 攻坚 {plan.get('plan_id')} 子目标 {sg.get('sid')}",
        proof_text=body, proof_manuscript=mtext, line_range={"label": rel},
        quote_reason="F 交来的论证（V 已签，B 按 sha 认领）")
    assert second.get("ok") is True, second
    assert second.get("upgraded") is True, second
    assert second.get("evidence_kind") == "proof_review", second
    after = [r for r in ws.rows("statements") if str(r.get("stmt_id")) == stmt_id]
    assert len(after) == 1, after                          # 升档不是登记第二行
    assert after[0]["evidence_kind"] == "proof_review", after[0]
    # B-2 的升档那条路：首次按 conjecture 登记（没有 V 签），V 签完再交一次
    # 之后 kind 跟着证据升离 conjecture。改前 F 一进门就写 lemma（跳过 conjecture 阶段）。
    assert str(after[0].get("kind")) != "conjecture", after[0]
    # 升档的来路必须是盘上那一签（不是自报）：回填痕逐格点名台账与证明号。
    # 2026-11-05：`from` / `to` 是「等级」（`conjecture → pre_theorem`），历史档位
    # 由同一条回执的 `from_kind` / `to_kind` 反算给出（`heuristic → proof_review`）；
    # 判据的意思不变（"按盘上那一签现算"），只是轴换成了等级。
    trace = dict(after[0].get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("checked") is True, trace
    assert (trace.get("from"), trace.get("to")) == ("conjecture", "pre_theorem"), trace
    assert (trace.get("from_kind"), trace.get("to_kind")) == (
        "heuristic", "proof_review"), trace
    assert trace.get("proof_no") == 1, trace
    assert trace.get("basis") == (
        f"verifications/{stmt_id}.jsonl#{signed['verification_id']}"), trace


def test_fs_outlet_does_not_promote_without_a_signature(ws: Store):
    """反真空（⑨）：没有那一签时 F 不许升档 —— 走同一条路要落回 `heuristic`。

        这条与上一条成对：没有它，"升档"可能被写成"每次都写 proof_review"，
        而那正是这道闸要堵的虚报。签的是另一版证明（不是行上那一份）："有签"
        与"这次交的这一份有签"在这里被分开量。
    """
    from agentflow.agent_f import AgentF

    sg, product, plan, stmt_id = _outlet_fixture(ws)
    f = AgentF(ws, config={"workspace_root": str(ws.root)})
    first = f._proof_outlet(product, sg, plan=plan)
    assert first["ok"] and first["reused"], first
    assert first["promoted"] is False, first
    assert first["evidence_kind"] == "heuristic", first
    _sign(ws, stmt_id, proof_text="这是另一版证明（不是被审的那一份）")
    second = f._proof_outlet(product, sg, plan=plan)
    assert second["ok"] and second["reused"] and second["promoted"] is False, second
    assert second["evidence_kind"] == "heuristic", second
    row = next(r for r in ws.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    assert row["evidence_kind"] == "heuristic", row
    # 反真空：那一签盖的是另一版 ⇒ 现行这一份的凭据面仍然不成立，也没有回填痕。
    gap = VR.proof_review_gap(ws.root, row)
    assert gap.get("ok") is False, gap
    assert gap.get("state") != "signed", gap
    assert VR.GRADE_RECOMPUTED_KEY not in row, row


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
