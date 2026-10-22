# -*- coding: utf-8 -*-
"""判据：签名这件事在读数上永远不许说谎（多证明签名链审计"最危险的一批"）。

## 这一份在治什么

`%TEMP%\\audit_ms\\` 那批探针量出的五种"签名说谎"形态，每一条都能让一次
没有落地的签名以 `signed_bit3=True` 出现在返回值里，而盘上没有凭据：

| 条 | 形态（改前读数） | 修完之后要读到什么 |
|---|---|---|
| ① 撤回 | 存量 `proof_review` 行的 canonical 未签，V 签 `#p2` ⇒ 写入期闸拒收、撤回抹掉台账那一行，而返回仍 `checked=True verdict='成立' signed_bit3=True`、台账 0 字节、R10=0 | 要么真的签住（台账有行、`#p2` 位翻、R10=1），要么 `checked=False` 并说明；不许返回说 sign 而盘上 0 字节 |
| ② 号与正文解耦 | `verify_proof(proof_no=2)` 不给正文 ⇒ 送进提示词的是 `#p1` 的正文，sha 却记在 `#p2` 上 | 提示词与 `proof_sha256` 都来自 `#p2`；`#p1` 不被牵连 |
| ③ 正文与号错配 | 给正文、漏 `proof_no` ⇒ 记到 `#p1` 上，而 sha 是 `#p2` 的 | 拒绝（或记到 `#p1` 且 sha 与 `#p1` 一致）；不许 sha 与号错配 |
| ④ 坏证明号 | `proof_no=0` / `'abc'` / `2.0` 被 `or 1` 静默折成 `#p1` ⇒ 签错一份证明 | 拒绝（不落台账、`checked=False`），`reason`/`detail` 点名"证明号认不出" |
| ⑤ 没签过 vs 没查成 | `state='unsigned'`（台账读得出、只是没签过）被报成 `checked=False`「台账读不出来（没查成）」 | `checked=True`、`state='unsigned'`；文案不许写"没查成" |
| ⑥ 追加失败 | 台账路径写不进去 ⇒ `writeback.reason` 说"台账那一行留着（签名确实发生过）"（而盘上 0 字节） | 三态 `append_state='failed'`、`written=False`、`re_sign_required=True`，理由串明说没写成；返回 `checked=False` |

## 三态纪律

这六条里最危险的不是"没签上"，而是"没签上却被读成签住了"：下游（论文档位、
收工门 R10、报告里的强度声明）全部读那一格。所以每条判据都断言"盘上有没有凭据"
与"返回值怎么说"这两件事必须一致，而不是只断言其中一边。

全部 tmp 工作区、零模型调用（V 的模型缝是一个只回一行 JSON 的假缝，成本 0）。
不读写 `projects/`，不跑 `run-agent`。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git show HEAD:…` 的旧文件铺到临时树的 `src/` 里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.store import Store

TS = "2026-10-22T00:00:00+08:00"
SID = S.format_id(0)
#: 两份证明的正文（含各自独有的字样，好判"提示词里到底是哪一份"）。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
P1_MARK = "由定义直接得到"
P2_MARK = "先证引理"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
SHORT = "弦长函数不是常值"

_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步直接用了结论"}]}


# ------------------------------------------------------------------ 小工具

class _Seam:
    """零成本模型缝：把提示词收下来，回一行固定 JSON。"""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload if payload is not None else dict(_OK)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _row(*, proof_text: str = P1, proofs: list | None = None,
         evidence_kind: str = "heuristic") -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": SHORT, "statement_full": FULL, "statement_text": SHORT,
        "proof_text": proof_text, "evidence_kind": evidence_kind, "status": "active",
        "quote_verified": None,
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof_text, kind="theorem"),
    }
    if proofs is not None:
        row[VR.PROOFS_KEY] = proofs
    return row


def _put(store: Store, **kw) -> dict:
    row = _row(**kw)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _get(store: Store) -> dict:
    return dict(next(r for r in store.rows("statements")
                     if str(r.get("stmt_id")) == SID))


def _make_stock_proof_review(store: Store) -> None:
    """造一条"存量 `proof_review` 行"：canonical 未签，而档位已经写成 proof_review。

    写入期闸不允许新造这种行（它正是那道闸要拦的形态），所以照真机 mp1 的来路：
    先按 heuristic 落盘，再把 `data/statements.json` 上那一格改成 proof_review
    （`rebuild` 与读侧都照读存量，审计期由 `verify._check_13` 点名）。
    """
    path = store.data / "statements.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    hit = next(r for r in doc["rows"] if str(r.get("stmt_id")) == SID)
    hit["evidence_kind"] = "proof_review"
    path.write_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def _ledger_bytes(store: Store) -> int:
    path = VR.verification_ledger_path(store.root, SID)
    return path.stat().st_size if path.is_file() else 0


def _ledger_rows(store: Store) -> list[dict]:
    rows, problems = VR.list_verifications(store.root, statement_id=SID, limit=None)
    assert problems == [], problems
    return rows


def _per_proof(store: Store) -> dict:
    return EB.reviewed_by_proof(_get(store))


def _r10(store: Store) -> tuple[int, dict]:
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


def _v(store: Store, seam: _Seam) -> AgentV:
    return AgentV(store, workspace_root=store.root, llm=seam)


# ============================================================ ① 撤回

def test_a_rolled_back_signature_is_never_reported_as_signed(tmp_path: pathlib.Path) -> None:
    """① 存量 `proof_review` 行 + V 签 `#p2` ⇒ 真签住，或 `checked=False` 并说明。

    改前读数（`%TEMP%\\audit_ms\\p9.py`）：`writeback.rolled_back=True`、台账 0 字节、
    R10=0，而返回是 `checked=True verdict='成立' signed_bit3=True` —— 撤回把权威记录
    抹掉了，而调用方读到的每一个字都说"签住了"。

    修法有两半，这条判据同时钉住：写入期闸改读"任一份 signed 即放行"（`#p2` 签完
    这一行就够格），且返回只看"台账那一行有没有落地"。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)
    assert _get(st)["evidence_kind"] == "proof_review"
    assert _ledger_bytes(st) == 0, "夹具前提：这一行一次都没签过"

    seam = _Seam()
    out = _v(st, seam).verify_proof(SID, proof_no=2)
    size = _ledger_bytes(st)

    # 不许出现"返回说签住、盘上 0 字节"（改前正是这个读数）。
    assert not (out["checked"] and out["signed_bit3"] and size == 0), (
        "返回说签住了第 3 位，而台账是 0 字节：" + json.dumps(out, ensure_ascii=False))
    assert out["proof_sha256"] == VR.proof_sha(P2), out

    if out["checked"] and out["signed_bit3"]:
        # 正控那一半：真的签住了 —— 台账有行、位翻了、R10 数得到。
        rows = _ledger_rows(st)
        assert len(rows) == 1 and rows[0]["proof_no"] == 2, rows
        assert rows[0]["proof_sha256"] == VR.proof_sha(P2), rows[0]
        assert _per_proof(st) == {1: False, 2: True}, _per_proof(st)
        n, detail = _r10(st)
        assert n == 1 and detail["review_states"]["signed"] == 1, detail
        assert detail["counted"][0]["proof_no"] == 2, detail
        assert out["review_write"]["written"] is True, out["review_write"]
        return
    # 另一条合法出口：拒了就如实说，且盘上同样没有这一签。
    assert out["checked"] is False and out["reason"], out
    assert "reviewed" in out["detail"] or "没" in out["detail"], out["detail"]
    assert _per_proof(st) == {1: False, 2: False}, _per_proof(st)


def test_the_write_gate_lets_through_a_row_where_any_proof_is_signed(
        tmp_path: pathlib.Path) -> None:
    """① 的另一半（写入期闸用的复数版）：任一份 signed ⇒ `proof_review_gaps` 返回空列表。

    `evidence_kind` 是命题级的声明，而每份证明各自有第 3 位：存量行（`#p1` 未签、
    `#p2` 已成立）再交一次时，闸不许整笔拒收 —— 否则"如实登记"这条路本身被堵死，
    而拒收之后的撤回还会把台账那一行抹掉（本批审计第 1 条的两半）。
    反真空：一份都没签时，同一个函数必须把它点出来（否则"放行"可能只是恒真）。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)
    probe = dict(_get(st), evidence_kind="proof_review")

    # 反真空：一份都没签 ⇒ 闸点名它。
    before_gap = VR.proof_review_gap(st.root, probe)
    assert before_gap["ok"] is False, before_gap
    assert [g["statement_id"] for g in VR.proof_review_gaps(st.root, [probe])] == [SID]

    VR.record_verification(st.root, statement_id=SID, proof_text=P2, verdict=dict(_OK),
                           verifier="agent-V", store=st, proof_no=2)
    signed = dict(_get(st), evidence_kind="proof_review")
    assert VR.proof_review_gap(st.root, signed)["ok"] is True, VR.proof_review_gap(st.root, signed)
    assert VR.proof_review_gaps(st.root, [signed]) == [], "任一份 signed 仍然整笔拒收"
    # 而逐条读数仍然说清"canonical 那一份没签"（放行不等于读成 signed）。
    reading = VR.statement_review_reading(st.root, signed)
    assert reading["proofs"][0]["state"] == "unsigned", reading["proofs"][0]
    assert reading["proofs"][1]["state"] == "signed", reading["proofs"][1]


def test_the_rolled_back_row_itself_reports_not_landed(tmp_path: pathlib.Path) -> None:
    """① 的同族（写入口那一侧）：撤回之后 `record_verification` 的返回行 `checked=False`。

    这一条直接调写入口（不经模型缝），并用"提交时写入期闸拒收"造一次真实的回滚
    （`sign_statement` 的 `except` 分支：`_rollback_append` 把刚追加的那一行撤掉）。
    改前它返回的是原样那一份 `verdict=成立` 的记录，没有任何一格说"没落地"。
    """
    from agentflow import store as ST

    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    _make_stock_proof_review(st)

    def _refuse(*_a, **_k):
        raise ValueError(f"{VR.CODE_WRITE}：夹具：让这一笔提交失败，好测撤回那一支")

    original = ST._refuse_fake_proof_review
    ST._refuse_fake_proof_review = _refuse
    try:
        row = VR.record_verification(st.root, statement_id=SID, proof_text=P2,
                                     verdict=dict(_OK), verifier="agent-V",
                                     store=st, proof_no=2)
    finally:
        ST._refuse_fake_proof_review = original

    wb = row["statement_writeback"]
    assert wb["append_state"] == "appended", wb
    assert wb["rolled_back"] is True, wb
    assert row["checked"] is False, row
    assert "台账那一行被撤回" in row["reason"], row["reason"]
    assert _ledger_bytes(st) == 0, "撤回之后台账里还有字节"
    assert _get(st)["bits"]["reviewed"] is False, _get(st)["bits"]
    # V 那一侧不许把"被撤回"读成"签住了"。
    assert not (wb["written"] and row["checked"]), wb


# ============================================================ ② 号与正文绑定

def test_proof_no_binds_the_text_that_reaches_the_model(tmp_path: pathlib.Path) -> None:
    """② `verify_proof(proof_no=2)` 不给正文 ⇒ 提示词与 sha 都来自 `#p2`，`#p1` 不被牵连。

    改前（`p1.py`）：送进提示词的是 `#p1` 的正文（`hit["proof_text"]`），却把
    `#p2` 记在台账行上 —— 于是一条"审过了 #p2"的假证据，加上 `#p1` 被读成
    "签过一份它没被审的正文"。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    out = _v(st, seam).verify_proof(SID, proof_no=2)

    assert seam.prompts, "没有问过模型 ⇒ 这条判据没有对象"
    prompt = seam.prompts[0]
    assert P2_MARK in prompt, "提示词里没有 #p2 的正文（给了别的证明的正文）"
    assert P1_MARK not in prompt, "提示词里混进了 #p1 的正文（号与正文解耦）"
    assert out["proof_no"] == 2, out
    assert out["proof_sha256"] == VR.proof_sha(P2), (
        f"sha 不是 #p2 那一份的（{out['proof_sha256'][:12]}… vs {VR.proof_sha(P2)[:12]}…）")
    assert _ledger_rows(st)[0]["proof_sha256"] == VR.proof_sha(P2), _ledger_rows(st)[0]
    # #p1 没有被牵连：它自己那一格仍是未签，签的凭据在 #p2 上。
    assert _per_proof(st) == {1: False, 2: True}, _per_proof(st)
    reading = VR.statement_review_reading(st.root, _get(st))
    assert reading["proofs"][0]["state"] == "unsigned", reading["proofs"][0]
    assert reading["proofs"][1]["state"] == "signed", reading["proofs"][1]


def test_a_missing_proof_number_is_refused_instead_of_borrowing_another(
        tmp_path: pathlib.Path) -> None:
    """② 的反面：`proof_no` 指向一份不存在的证明 ⇒ `no_such_proof`，一行都不落。"""
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    out = _v(st, seam).verify_proof(SID, proof_no=3)
    assert out["checked"] is False and out["reason"] == "no_such_proof", out
    assert seam.prompts == [], "没有那一份证明却问了模型（拿别的正文顶替）"
    assert _ledger_bytes(st) == 0, "没审却落了台账行"


# ============================================================ ③ 正文与号错配

def test_text_without_proof_no_never_mismatches_the_recorded_number(
        tmp_path: pathlib.Path) -> None:
    """③ 给了 `#p2` 的正文却漏 `proof_no` ⇒ 拒绝（或记到 `#p1` 且 sha 与 `#p1` 一致）。

    改前（`p12.py`）：记到 `#p1`，而 `proof_sha256` 是 `#p2` 那一份的 —— 号与 sha
    各说一件事，读侧"这一签盖住的是哪一份"从此无解。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    seam = _Seam()
    out = _v(st, seam).verify_proof(SID, proof_text=P2)      # 漏了 proof_no

    if out["checked"]:
        # 记到 #p1 那一支：sha 必须是 #p1 的，否则就是错配。
        assert out["proof_no"] == 1, out
        assert out["proof_sha256"] == VR.proof_sha(P1), (
            f"记到 #p1 上，sha 却是别的证明的（{out['proof_sha256'][:12]}…）")
    else:
        # 拒绝那一支：说清是哪一格不符，且台账里没有这一签。
        assert out["reason"] == "proof_text_mismatch", out
        assert "sha" in out["detail"] and "proof_no" in out["detail"], out["detail"]
        assert _ledger_bytes(st) == 0, "拒了却落了台账行"
        assert out["signed_bit3"] is False, out


# ============================================================ ④ 坏证明号

def test_a_bad_proof_number_is_refused_not_folded_to_p1(tmp_path: pathlib.Path) -> None:
    """④ `proof_no=0` / `'abc'` / `2.0` ⇒ 拒绝（不落台账、`checked=False`），理由点名。

    改前（`p3.py`）：`as_proof_no(x) or 1` 把三个坏号都折成 `#p1`，于是"号给错了"
    变成"签了 canonical"，而台账上写着 `verdict=成立`。
    """
    for bad in (0, "abc", 2.0):
        st = _ws(tmp_path / f"bad_{str(bad).replace('.', '_')}")
        _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
        seam = _Seam()
        out = _v(st, seam).verify_proof(SID, proof_text=P1, proof_no=bad)
        assert out["checked"] is False, (bad, out)
        assert out["signed_bit3"] is False, (bad, out)
        assert "证明号认不出" in (str(out["reason"]) + str(out["detail"])), (bad, out)
        assert seam.prompts == [], (bad, "号认不出却问了模型")
        assert _ledger_bytes(st) == 0, (bad, "号认不出却落了台账行")

    # 写入口那一侧同样是拒绝（不是折成 #p1）：`record_verification` 抛 VerificationError。
    st = _ws(tmp_path / "write_side")
    _put(st)
    for bad in (0, "abc", 2.0):
        try:
            VR.record_verification(st.root, statement_id=SID, proof_text=P1,
                                   verdict=dict(_OK), verifier="agent-V",
                                   store=st, proof_no=bad)
        except VR.VerificationError as exc:
            assert "证明号认不出" in str(exc), (bad, str(exc))
        else:
            raise AssertionError(f"坏证明号 {bad!r} 被接受了（折成了 #p1）")
    assert _ledger_bytes(st) == 0, "坏号被拒之后台账里仍有行"
    # 正控（防真空）：合法号照旧写得进去。
    VR.record_verification(st.root, statement_id=SID, proof_text=P1,
                           verdict=dict(_OK), verifier="agent-V", store=st, proof_no=1)
    assert len(_ledger_rows(st)) == 1, _ledger_rows(st)


# ============================================================ ⑤ unsigned 不是没查成

def test_unsigned_is_a_checked_conclusion_not_an_unchecked_ledger(
        tmp_path: pathlib.Path) -> None:
    """⑤ 台账读得出、只是没签过 ⇒ `checked=True`；文案不许写"没查成"。

    改前（`p8.py`）：`state='unsigned'` 与 `state='unreadable'` 一起掉进最后那一段，
    于是"查过了、没签过"（处置：派 V）被报成"台账读不出来"（处置：查 I/O）。
    """
    st = _ws(tmp_path)
    _put(st, proofs=[{"proof_no": 2, "proof_text": P2}])
    # 让台账存在、读得出、但 canonical 一次都没签：只在 #p2 上落一签"有毛病"。
    VR.record_verification(st.root, statement_id=SID, proof_text=P2, verdict=dict(_BAD),
                           verifier="agent-V", store=st, proof_no=2)
    assert VR.verification_ledger_path(st.root, SID).is_file()

    gap = VR.proof_review_gap(st.root, dict(_get(st), evidence_kind="proof_review"))
    assert gap["checked"] is True, gap
    assert gap["state"] == "unsigned", gap
    assert gap["ok"] is False, gap
    text = str(gap["why"]) + "".join(str(c.get("detail") or "") for c in gap["checklist"])
    assert "没查成" not in text, f"没签过被写成了「没查成」：{text}"
    assert "一次都没签" in text or "没有" in text, text
    # 对照：真正的坏行仍然是 checked=False（三态的另一半不许被这条修法顺手折平）。
    path = VR.verification_ledger_path(st.root, SID)
    path.write_bytes(path.read_bytes() + b"{broken line\n")
    gap2 = VR.proof_review_gap(st.root, dict(_get(st), evidence_kind="proof_review"))
    assert gap2["checked"] is False and gap2["problems"], gap2


# ============================================================ ⑥ 追加失败

def test_a_failed_append_says_so_and_never_claims_the_signature_happened(
        tmp_path: pathlib.Path) -> None:
    """⑥ 台账只读（追加失败）⇒ `append_state='failed'`、`re_sign_required=True`、`checked=False`。

    改前（`p6.py`）：`before = -1` 既是"追加前的字节数"又是"到底试没试过"，于是
    追加本身抛错时理由串照样写"台账那一行留着（签名确实发生过）"—— 而盘上 0 字节。

    造法：台账文件先落成空文件、再置只读（`open(..., "a")` 在 Windows 上抛
    `PermissionError`，POSIX 上抛 `EACCES`）；读它照旧成功，于是失败点正好落在
    "追加"这一格里。收尾前恢复可写，让 tmp 目录能删干净。
    """
    import os
    import stat

    def _make_readonly(store: Store) -> pathlib.Path:
        path = VR.verification_ledger_path(store.root, SID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        os.chmod(path, stat.S_IREAD)
        return path

    def _make_writable(path: pathlib.Path) -> None:
        if path.exists() and path.is_file():
            os.chmod(path, stat.S_IWRITE)

    st = _ws(tmp_path)
    _put(st)
    path = _make_readonly(st)
    try:
        row = VR.record_verification(st.root, statement_id=SID, proof_text=P1,
                                     verdict=dict(_OK), verifier="agent-V",
                                     store=st, proof_no=1)
        wb = row["statement_writeback"]
        assert wb["append_state"] == "failed", wb
        assert wb["written"] is False, wb
        assert wb["re_sign_required"] is True, wb
        assert "没写成" in wb["reason"], wb["reason"]
        assert "签名确实发生过" not in wb["reason"], (
            "追加本身失败了，理由串却说「签名确实发生过」：" + str(wb["reason"]))
        assert row["checked"] is False, row
        # V 那一侧：同一个失败必须读成 `checked=False`，不许报"签住了第 3 位"。
        out = _v(st, _Seam()).verify_proof(SID, proof_text=P1, proof_no=1)
        assert out["checked"] is False, out
        assert out["signed_bit3"] is False, out
        assert "台账那一行" in out["reason"], out["reason"]
        assert out["review_write"]["append_state"] == "failed", out["review_write"]
        assert out["review_write"]["re_sign_required"] is True, out["review_write"]
    finally:
        _make_writable(path)

    # 正控（防真空）：台账恢复可写之后，同一签必须写得进去（上面的红不是恒红）。
    ok_row = VR.record_verification(st.root, statement_id=SID, proof_text=P1,
                                    verdict=dict(_OK), verifier="agent-V",
                                    store=st, proof_no=1)
    assert ok_row["statement_writeback"]["append_state"] == "appended", ok_row
    assert ok_row["statement_writeback"]["written"] is True, ok_row
    assert ok_row["checked"] is True, ok_row
