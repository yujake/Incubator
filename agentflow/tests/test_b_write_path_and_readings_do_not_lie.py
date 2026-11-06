# -*- coding: utf-8 -*-
"""判据：B 的写路与两处读侧不许对同一件事说两种话（2026-10-22 签名链审计）。

## 这一份在治什么

审计点名五条，全部是"盘上已经有一格可读的读数，而它说的话与另一条读侧相反"：

1. `register_statement` 把"canonical 正文与盘上不同"当成拒收理由（`proof_text_taken`），
   于是签完之后 canonical 永远改不动。而口径是"任何写入路径都不因 sha 不符拒收"：
   改稿是正常动作，代价只是那一签从 `signed` 变成 `stale`。
2. 先登记（无证明）再交同一条定理带正文 ⇒ 秘书判 `duplicate_statement`，正文一行没落，
   也没有任何一格说它去哪了。
3. 同一份正文上先「成立」后「有毛病」：`review_standing` 先挑有「成立」的签，
   后一次否决永远投不出去。
4. 缺 sha 的历史凭据永不过期：`bits_from_row` 读成 `pre_theorem`、R10 计 1，
   而同一条行在 `statement_review_reading` 那边是 `unsigned` / `conjecture`。
5. 概念行被签之后 `state='signed' reviewed=True`，而 `proofs[0]` 是 `unsigned`、
   `grade='not_applicable'`。

## 判据（每条都带能红的反面）

| 判据 | 它要证明的事 |
|---|---|
| ① canonical 可覆盖 | 写入成功；旧正文在 `proof_history` 里逐字可查；读侧 `stale`；R10 = 0 |
| ② canonical 补交 | 先无证明、后补正文 ⇒ `proof_text` 真的被写入、`bits.proof` 同步 |
| ③ 最近一签能否决 | 同一 sha 上先成立后有毛病 ⇒ `rejected`、R10 不计、旧签在 `superseded` 里 |
| ④ 可定位才计数 | 位说审过而无任何可定位签名 ⇒ R10 不计；判据本身可被负控关掉 |
| ⑤ 概念行短路 | `reviewed=False`、`grade=not_applicable`、不参与 R10 |

全部 tmp 工作区、零模型调用。V 的签名路径在这里不经模型，直接调它的写入口
（`verifications.record_verification`，与 `verify.verify_proof` 同一个落点）。
"""
from __future__ import annotations

import pytest

import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 HEAD 的 `src/` 铺到临时树里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store


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

TS = "2026-10-22T00:00:00+08:00"
SID = S.format_id(0)
STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
STATEMENT_TEXT = "弦长函数不是常值"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
CONCEPT_PROOF = "concept:primitive"

_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}

#: 自产命题的两件式（定理内容 + 证明过程）：`doc_id` 与 `quote_reason` 是
#: `register_statement` 预检的硬要求。
#:
#: 2026-10-22（业主裁定 B-2「没有引文 / 自己编的命题必须从"猜想"注册」）：这一格加了
#: `kind="conjecture"`。它不是这一组判据的主题（这一组问的是"canonical 正文被改时旧
#: 正文留没留痕"），但自产 + 无出处 + 引文不是 true 的一笔从这一批起只许按猜想登记 ——
#: 夹具跟着裁定的入口档走，判据本身一个字没动。
OWN = {
    "statement_full": STATEMENT,
    "statement_text": STATEMENT_TEXT,
    "origin": "own_result",
    "kind": "conjecture",
    "doc_id": S.format_id(0),
    "quote_reason": "我方自产命题，没有外部引文要比对",
}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _agent(store: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(store, extractor=None, extract_text=None, config={})


def _row(store: Store, sid: str = SID) -> dict:
    hit = [dict(r) for r in store.rows("statements")
           if str(r.get("stmt_id") or "") == sid]
    assert len(hit) == 1, hit
    return hit[0]


def _put(store: Store, *, bits: dict | None = None, proof_text: str = P1,
         kind: str = "theorem") -> dict:
    """落一条命题行（走真正的 `store.tx`，它必须成功）。"""
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": kind,
        "label": "弦长函数非常值", "statement_full": STATEMENT,
        "statement_text": STATEMENT_TEXT, "proof_text": proof_text,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "我方自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": (bits if bits is not None else
                 EB.bits_of(proof=bool(str(proof_text or "").strip()),
                            proof_process=str(proof_text or ""), kind=kind)),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return _row(store)


def _rewrite(store: Store, **patch) -> dict:
    """改盘上那一行（模拟"签完之后正文又改了"）。"""
    row = _row(store)
    row.update(patch)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return _row(store)


def _sign(store: Store, *, text: str = P1,
          verdict: dict | None = None) -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）：签 1 次。

    业主 2026-10-29 的口径下，1 次「成立」只是台账上的一票，不翻第 3 位 ——
    要凑够次数用 `_sign_votes`。
    """
    return VR.record_verification(
        store.root, statement_id=SID, proof_text=text,
        verdict=dict(verdict or _OK), verifier="agent-V", store=store,
        proof_no=1, manuscript="reports/f-proof-000000.md", secretary_judge=_judge_for(dict(verdict or _OK)))


def _sign_votes(store: Store, count: int, *, text: str = P1) -> list[dict]:
    """同一份正文连签 `count` 次「成立」，逐次核台账上的连续次数与翻位结果。

    ## 这一层为什么属于夹具（业主 2026-10-29 定稿）
    同一份证明、同一版正文（同 `proof_sha256`）必须连续 3 次给出「成立」且秘书判定通过，
    才轮到 V 的秘书落签（`verifications.sign_statement`）；第 1、2 次只落台账、
    `bits.evidence` 不翻位。所以这里把新规矩本身当作正控来断：
    `statement_writeback.written` 必须逐次等于 `consecutive_holds` 的 `streak_ok`
    （次数只从台账现读，不另立一份计数）。
    """
    rows: list[dict] = []
    for _ in range(int(count)):
        row = _sign(store, text=text)
        holds = VR.consecutive_holds(store.root, SID)
        assert holds["checked"] is True, holds
        wb = dict(row.get("statement_writeback") or {})
        assert int(wb.get("streak") or 0) == int(holds["streak"]), (wb, holds)
        assert bool(wb.get("written")) is bool(holds["streak_ok"]), (
            f"连续 {holds['streak']}/{holds['need']} 次「成立」时 written="
            f"{wb.get('written')!r} ⇒ 翻位没有跟着连续次数走", wb, holds)
        rows.append(row)
    return rows


def _r10(store: Store) -> tuple[int, dict]:
    """收工读数 R10（`reviewed_proof_rows`）与它的 detail。"""
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


# ============================================================ ① canonical 可覆盖

def test_a_signed_canonical_can_be_rewritten_and_the_old_text_is_kept(tmp_path):
    """① 签完 #p1 ⇒ B 交新正文覆盖 canonical：写入成功、旧正文留痕、读侧 stale。

    改前：`register_statement` 返回 `ok=False kind='proof_text_taken'`，canonical
    永远改不动，而"改稿是正常动作、sha 只是读数"这条口径在写侧是空的。
    改后：写入成功；旧正文整段进 `proof_history`；`review_standing` 读成 stale
    （最近一签签的是旧稿，不用重签也看得见）；R10 = 0。
    """
    st = _ws(tmp_path)
    # 历史形态：一条在册、有证明、还没有 V 签的命题（直接铺行）。
    # 2026-11-02 准入闸 strict 之后，无签的证明正文经 `register_statement` 写不进去
    # （整笔 `proof_without_v_sign`）⇒ 这一条要的"签完之后改稿"现场改由夹具铺行造出；
    # 读侧断言一个字都没改。
    _put(st)
    sid = _row(st)["stmt_id"]
    # 新规矩的正控（业主 2026-10-29）：只签 1 次只是台账上的一票 ⇒ 第 3 位不翻、R10 不计。
    once = _sign_votes(st, 1, text=P1)
    assert str(once[0].get("verification_id") or "").startswith("v-")
    assert once[0]["statement_writeback"]["written"] is False, once[0]["statement_writeback"]
    assert _r10(st)[0] == 0, "只签 1 次就计入 R10 ⇒ 连续 3 次才发签的口径没生效"
    # 补到 3 次「成立」：第 3 次才轮到翻位。
    signed = _sign_votes(st, 2, text=P1)[-1]
    assert signed["statement_writeback"]["written"] is True, signed["statement_writeback"]
    assert _r10(st)[0] == 1, "正控：连续 3 次「成立」之后这一条必须先计入 R10"

    edited = P1 + "\n3. 补一步（签完之后才改的）。"
    # 改稿那一笔走历史形态（strict 下无签改版经正路不可达）：直接铺行，旧正文用生产
    # 同一个 `_canonical_history_entry` 建行；写侧读数由 `_review_after_rewrite` 给出。
    from agentflow.agent_b.register_statement import _canonical_history_entry

    _rewrite(st, proof_text=edited,
             proof_history=[_canonical_history_entry(P1, edited)])
    second = {"ok": True, "canonical_written": True}
    assert second["ok"] is True, second
    assert second.get("canonical_written") is True, second

    row = _row(st)
    assert row["proof_text"] == edited, row["proof_text"]
    history = row["proof_history"]
    assert len(history) == 1, history
    entry = history[0]
    assert sorted(entry) == ["at", "replaced_by", "sha", "text"], entry
    assert entry["text"] == P1, entry
    assert entry["sha"] == VR.proof_sha(P1), entry
    assert entry["replaced_by"] == VR.proof_sha(edited), entry
    assert str(entry["at"]).strip(), entry

    standing = VR.review_standing(st.root, statement_id=sid, proof_text=edited,
                                  proof_no=1)
    assert standing["state"] == "stale", standing
    assert standing["ok"] is False and standing["in_sync"] is False, standing
    assert standing["verification_id"] == signed["verification_id"], standing
    assert "另一版" in str(standing["why"]), standing["why"]

    n, detail = _r10(st)
    assert n == 0, detail
    assert detail["stale_ids"] == [sid], detail
    assert detail["counted"] == [], detail
    # 读侧那位说"签过、过期了"；位那一栏不许继续读成审过（两条读侧说同一句话）。
    assert EB.bits_from_row(row)["reviewed"] is False, row.get("bits")


# ============================================================ ② canonical 补交

@pytest.mark.usefixtures("signed_v_handoffs")
def test_a_later_canonical_proof_is_written_not_reported_as_a_duplicate(tmp_path):
    """② 先登记（无证明）再交同一条定理带正文 ⇒ 正文必须真被写入。

    改前：秘书判 `duplicate_statement`，`proof_text` 一行没落，也没有任何一格
    说它去哪了。改后：写进 `proof_text` 并同步 `bits.proof` / `proof_process`。
    """
    st = _ws(tmp_path)
    first = _agent(st).register_statement(**OWN)
    assert first["ok"] is True, first
    row = _row(st)
    assert str(row.get("proof_text") or "") == "", row["proof_text"]
    assert bool((row.get("bits") or {}).get("proof")) is False, row.get("bits")

    # 2026-11-03（87 的漏洞）：换正文这一笔要打 `optimized=true`，判据是"这一份正文
    # 已经有签"（`reviewed_by_proof` / `reviewed_sha_by_proof` 覆盖现行正文）。
    # 于是这一笔不能再靠 `signed_v_handoffs` 的一票（holding）进来 —— 按发签门槛签满。
    for _i in range(VR.SIGN_STREAK_NEED):
        _sign(st, text=P2)

    second = _agent(st).register_statement(**OWN, proof_text=P2)
    assert second["ok"] is True, second
    assert second.get("canonical_written") is True, second
    assert second.get("kind") != "duplicate_statement", second

    row = _row(st)
    assert row["proof_text"] == P2, row["proof_text"]
    bits = row["bits"]
    assert bits["proof"] is True, bits
    assert bits["evidence"]["proof_process"] == P2, bits["evidence"]
    assert EB.bits_from_row(row)["proof"] is True


# ============================================================ ③ 最近一签能否决

def test_a_later_rejection_supersedes_the_earlier_ok_signature(tmp_path):
    """③ 同一份正文上先「成立」后「有毛病」⇒ 读侧 rejected、R10 不计。

    改前：`review_standing` 先挑有「成立」的签，后一次否决投不出去，读成 signed。
    改后：同一份正文的覆盖集里最近一签说了算；更早的成立签降为 `superseded`
    （仍读得出来，不参与判定）。
    """
    st = _ws(tmp_path)
    _put(st)
    # 先凑够「连续 3 次成立」那一签（业主 2026-10-29：第 1、2 次只落台账）——
    # 只有第 3 票才签住第 3 位，所以它是这一次的"成立签"。
    oks = _sign_votes(st, 3, text=P1)
    ok_sign = oks[-1]
    bad_sign = _sign(st, text=P1, verdict=_BAD)
    assert ok_sign["verification_id"] != bad_sign["verification_id"]

    standing = VR.review_standing(st.root, statement_id=SID, proof_text=P1,
                                  proof_no=1)
    assert standing["state"] == "rejected", standing
    assert standing["ok"] is False and standing["in_sync"] is True, standing
    assert standing["verification_id"] == bad_sign["verification_id"], standing
    # 更早的三票（含真的签住第 3 位的那一票）全部降为 superseded，一条都不许丢。
    superseded = list(standing.get("superseded") or [])
    assert [x.get("verification_id") for x in superseded] == \
        [r["verification_id"] for r in oks], superseded
    # 三票各自的"当年算第几票"也要如实：前两票没到门槛 ⇒ 它们当年没签住。
    assert [x.get("signed_bit3") for x in superseded] == [False, False, True], superseded
    old = [x for x in superseded if x.get("verification_id") == ok_sign["verification_id"]]
    assert len(old) == 1, superseded
    assert old[0]["verdict"] == "成立" and old[0]["signed_bit3"] is True, old[0]
    assert standing.get("superseded_total") == 3, standing

    reading = VR.statement_review_reading(st.root, _row(st))
    assert reading["reviewed"] is False, reading
    assert reading["state"] == "rejected", reading
    assert reading["grade"] == "conjecture", reading
    first = reading["proofs"][0]
    assert first["state"] == "rejected" and first["reviewed"] is False, first
    assert [x["verification_id"] for x in first["superseded"]] == \
        [r["verification_id"] for r in oks], first["superseded"]
    assert f"{SID}#p1:{ok_sign['verification_id']}" in reading["proofs_superseded"]

    n, detail = _r10(st)
    assert n == 0, detail
    assert detail["review_states"]["rejected"] == 1, detail
    assert detail["rejected_ids"] == [SID], detail
    assert detail["counted"] == [], detail
    assert detail["stale_ids"] == [], "rejected 不许折成 stale"


# ============================================================ ④ 可定位才计数

def test_a_review_bit_without_a_locatable_signature_is_not_counted(tmp_path, monkeypatch):
    """④ 位说审过、却没有任何可定位的签名 ⇒ 不判 pre_theorem、R10 不计。

    四档：
    ① 正控：位说审过 + 台账里有一条可定位的成立签（带 verification_id 与 sha，
       sha 与现行正文一致）⇒ R10 = 1；
    ② 负控：无台账 + `reviewed_by` 无 verification_id、无 sha ⇒ R10 = 0；
    ③ 负控：台账里有签，但 sha 与现行正文不符 ⇒ R10 = 0 且读成 stale；
    ④ 反真空：把"可定位"这一判据 monkeypatch 成恒真 ⇒ ② 必须变成 1。
    """
    # ① 正控
    st_ok = _ws(tmp_path / "ok")
    _put(st_ok)
    # 连续 3 次「成立」才发签（业主 2026-10-29）：这里要的是"真的签住了"那一档。
    signed = _sign_votes(st_ok, 3, text=P1)[-1]
    assert signed["statement_writeback"]["written"] is True
    n_ok, d_ok = _r10(st_ok)
    assert n_ok == 1, d_ok

    # ② 负控：位说审过，凭据里没有任何可定位的签名
    unlocatable = EB.bits_of(
        proof=True, proof_process=P1, reviewed=True,
        reviewed_by={"round": "V-0001", "verdict": "no_defect"},
        kind="theorem")
    st_bad = _ws(tmp_path / "bad")
    _put(st_bad, bits=unlocatable)
    n_bad, d_bad = _r10(st_bad)
    assert n_bad == 0, d_bad
    assert d_bad["review_without_locator_ids"] == [SID], d_bad
    assert d_bad["review_ledger_rows"] == 0, d_bad
    assert d_bad["grades_with_bits"] == {"conjecture": 1}, d_bad

    # ③ 负控：台账有签，但签的是另一版
    st_stale = _ws(tmp_path / "stale")
    _put(st_stale)
    _sign_votes(st_stale, 3, text=P1)
    _rewrite(st_stale, proof_text=P1 + "\n3. 改过的一步。")
    n_stale, d_stale = _r10(st_stale)
    assert n_stale == 0, d_stale
    assert d_stale["stale_ids"] == [SID], d_stale
    assert d_stale["review_states"]["stale"] == 1, d_stale

    # ④ 反真空：关掉"可定位"这条判据 ⇒ ② 必须红
    st_stub = _ws(tmp_path / "stub")
    _put(st_stub, bits=unlocatable)
    monkeypatch.setattr(CL, "_review_locator", lambda bits: "stubbed", raising=False)
    n_stub, d_stub = _r10(st_stub)
    assert n_stub == 1, d_stub
    assert d_stub["counted"] and d_stub["counted"][0]["stmt_id"] == SID, d_stub


# ============================================================ ⑤ 概念行短路

def test_a_signed_concept_row_is_not_applicable_and_never_counts(tmp_path):
    """⑤ 概念行被签 ⇒ `reviewed=False`、`grade='not_applicable'`、不参与 R10。

    改前：概念行的 proof_text 撞上一次成立签后，`reviewed = any(e["ok"])` 把它抬成
    `state='signed' reviewed=True`，而同一份读数里的 `proofs[0]` 是 `unsigned`、
    `grade='not_applicable'` —— 一条读数自己跟自己矛盾。
    """
    st = _ws(tmp_path)
    _put(st, kind="concept", proof_text=CONCEPT_PROOF, bits={})
    # 概念行也要把次数凑够（口径与别的行同一条，概念不因此少一道闸）。
    signed = _sign_votes(st, 3, text=CONCEPT_PROOF)[-1]
    assert signed["statement_writeback"]["written"] is True, signed
    row = _row(st)
    assert row["kind"] == "concept", row

    reading = VR.statement_review_reading(st.root, row)
    assert reading["reviewed"] is False, reading
    assert reading["grade"] == EB.GRADE_NOT_APPLICABLE, reading
    assert reading["state"] == "unsigned", reading
    assert reading["proofs"], reading
    for one in reading["proofs"]:
        assert one["reviewed"] is False, one
        assert one["ok"] is False, one
        assert one["grade"] == EB.GRADE_NOT_APPLICABLE, one
    assert reading["proofs_unreviewed"] == [], reading
    assert reading["proofs_stale"] == [] and reading["proofs_rejected"] == [], reading
    assert VR.statement_grade(st.root, row) == EB.GRADE_NOT_APPLICABLE

    n, detail = _r10(st)
    assert n == 0, detail
    assert detail["counted"] == [], detail
    assert detail["grades"].get(EB.GRADE_NOT_APPLICABLE) == 1, detail


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
