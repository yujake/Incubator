"""T4-B 的判据：签名台账（依据 `draft/30` §T4-B；`draft/29` §8.8）。

这一组回答三件事：

1. 正控：一条完整合法的链（G 落稿带哈希 → H 判 accepted 并自动签一条）⇒
   `verify` 在 documents 表上零 error，`signed(doc)` 与 `formal(doc)` 都为真；
2. 七条判据码各一条注入负控（`accepted_without_signature` / `stale_signature` /
   `signature_verdict_not_accepting` / `signer_not_reviewer` / `signature_inputs_mismatch` /
   `signature_evidence_unverifiable` / `signature_ledger_corrupt`）；
3. 写侧闸门：`append_signature` 拒非 H 的签名者、拒非接受档的判定、拒缺字段。

`draft/29` §8.8.8 的第 1、2 条（proof 级缺证据 / 命中禁用公理）是既有机制：
这里复跑它们的结构性事实，端到端复跑留给需要 Lean 的验收阶段（见 §T4-B 的"不做"）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import signatures as SIG
from agentflow import verify as V
from agentflow.agent_h import AgentH
from agentflow.store import Store

from conftest import add_concept, add_literature, add_relation

TS = "2026-01-01T00:00:00+00:00"
DISCLAIMER = "数值交叉验证，不构成证明"


def _store(tmp_path: Path) -> Store:
    """带最小知识表的工作区（否则引文会悬空，噪音盖过要测的东西）。"""
    st = Store(tmp_path)
    st.init()
    add_literature(st, "0000", title="某文献", path=None, processed=True, sync=False)
    add_concept(st, "0000", "谱", definition="d", sync=False)
    add_concept(st, "0001", "区间", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True,
                 sync=False)
    sync_counters(st)
    return st


def sync_counters(st: Store) -> None:
    """把 counters 对齐（夹具绕过 `alloc_id` 时必做，verify 会查 counters）。"""
    from conftest import sync_counters as _sync

    _sync(st)


def _claim(cid: str = "c1", cites: list[str] | None = None) -> dict:
    """一条合规断言（`cross_check` 必须带 disclaimer）。"""
    return {"claim_id": cid, "text": "谱落在区间内。",
            "citations": cites or ["rel:0000", "lit:0000"], "evidence_kind": "cross_check",
            "disclaimer": DISCLAIMER}


def _put(st: Store, table: str, row: dict) -> dict:
    """直接落库一行。"""
    with st.tx(table, actor="test") as tx:
        tx.upsert(table, row)
    return row


def _doc(st: Store, doc_id: str = "0000", *, status: str = "draft",
         claims: list[dict] | None = None, **kw) -> dict:
    """落一行稿件（内容哈希照写侧口径钉上）。"""
    row = {"doc_id": doc_id, "kind": "paper", "title": "稿", "sections": [],
           "claims": claims or [_claim()], "open_problems": [], "status": status,
           "created_at": TS, "updated_at": TS, **kw}
    row["content_sha256"] = SIG.content_sha256_of(row)
    return _put(st, "documents", row)


def _sign(st: Store, doc_row: dict, *, name: str = SIG.SIGNER_NAME,
          verdict: str = "accepted", **patch) -> dict:
    """给一行稿件签一条（默认是最合法的那一形态）。"""
    cur = SIG.content_sha256_of(doc_row)
    rec = {"doc_id": str(doc_row["doc_id"]), "content_sha256": cur, "name": name,
           "at": TS, "scope": "document", "verdict": verdict,
           "instance_id": f"test@{TS}",
           "inputs": {"doc_sha256": cur, "evidence_hashes": []},
           "basis": {"codes_checked": [], "finding_ids": [], "rounds": 1, "dimensions": []}}
    rec.update(patch)
    return SIG.append_signature(st.root, rec)


def _records(st: Store) -> list[dict]:
    """读回台账（坏行当失败：判据要用的是能解析的记录）。"""
    recs, bad = SIG.read_ledger(SIG.ledger_path(st.root))
    assert bad == [], bad
    return recs


def _codes(st: Store) -> list[str]:
    """`verify_all` 就 documents 表报出的判据码（排序）。"""
    return sorted(i.code for i in V.verify_all(st).issues if i.table == "documents")


# ---------------------------------------------------------------- ① 正控（走真实 review 路径）

def test_h_review_signs_the_accepted_revision(tmp_path: Path):
    """正控：H 判 accepted ⇒ 自动签一条；`verify` 零 error；`signed`/`formal` 为真。"""
    st = _store(tmp_path)
    _doc(st, "0000")
    h = AgentH(st)
    res = h.review("0000", dependencies=[])
    assert res["verdict"] == "accepted" and res["status"] == "accepted", res
    assert res["signature"] is not None, res.get("signature_error")
    assert res["signature_error"] is None
    doc = next(r for r in st.rows("documents") if r["doc_id"] == "0000")
    recs = _records(st)
    assert len(recs) == 1 and recs[0]["name"] == SIG.SIGNER_NAME
    assert SIG.signed(doc, recs, root=st.root) is True
    assert SIG.formal(doc, recs, root=st.root) is True
    assert _codes(st) == [], [i.to_dict() for i in V.verify_all(st).issues]
    # 证据快照真的落盘、且哈希对得上（不是只有一句声称）
    snap = Path(st.root) / str(recs[0]["evidence_path"])
    assert snap.is_file(), snap


def test_review_does_not_sign_a_document_it_did_not_accept(tmp_path: Path):
    """正控（反方向）：没判 accepted 就不签 —— "签了"必须是"接受了"的结果。

    用一条悬空依赖确定性地造出非接受判定：H 读到未闭合的依赖时 `verdict`
    落在 `unverified`（"依赖闭合没查/没闭合 ⇒ 不许判 accepted"），状态停在 `in_review`。
    """
    st = _store(tmp_path)
    _doc(st, "0000")
    _put(st, "dependencies", {"dep_id": "0000", "used_by": "doc:0000#c1", "kind": "theorem",
                              "label": "companion book [6] Thm 6.5", "status": "dangling",
                              "status_reason": "拿不到该书", "created_at": TS})
    h = AgentH(st)
    res = h.review("0000")          # 不给 dependencies ⇒ H 从库里读，读到悬空那条
    assert res["verdict"] != "accepted", res
    assert res["status"] != "accepted", res
    assert res["signature"] is None, res["signature"]
    assert _records(st) == []


# ---------------------------------------------------------------- ② 七条码各一条注入

def test_negative_accepted_without_signature_bites(tmp_path: Path):
    """注入：`accepted` 却一条签名都没有 ⇒ `accepted_without_signature`。"""
    st = _store(tmp_path)
    _doc(st, "0000", status="accepted")
    assert "accepted_without_signature" in _codes(st)


def test_negative_stale_signature_after_a_one_byte_change_bites(tmp_path: Path):
    """注入（§8.8.8 第 4 条）：改一个字节后旧签名仍挂在那里 ⇒ `stale_signature`。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    _sign(st, doc)
    assert _codes(st) == []
    with st.tx("documents", actor="test") as tx:
        row = dict(tx.find("documents", doc_id="0000"))
        row["title"] = "改了一个字节"
        tx.upsert("documents", row)
    assert "stale_signature" in _codes(st), _codes(st)


def test_negative_verdict_not_accepting_bites(tmp_path: Path):
    """注入：签名记录的 verdict 是 `unverified`（不是接受档）⇒ 读侧必须咬。

    走"直接塞台账"的路径：`append_signature` 的写侧闸门本来就拒它（见下面那组），
    这里要证的是读侧独立地拒 —— 两条防线各测各的。
    """
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    cur = SIG.content_sha256_of(doc)
    _append_raw(st, {"doc_id": "0000", "content_sha256": cur, "name": SIG.SIGNER_NAME,
                     "at": TS, "scope": "document", "verdict": "unverified",
                     "instance_id": "x", "evidence_path": "nope.json",
                     "evidence_sha256": "0" * 64,
                     "inputs": {"doc_sha256": cur}, "basis": {}})
    assert "signature_verdict_not_accepting" in _codes(st), _codes(st)


def test_negative_signer_not_reviewer_bites(tmp_path: Path):
    """注入（§8.8.8 第 3 条）：签名者不是 H ⇒ `signer_not_reviewer`。

    两条形态都测：别的角色名（G 自签）与作者本人（`name == created_by`）。
    注意这两条走的是"直接往台账里塞一条"的路径 —— `append_signature` 的写侧闸门
    会拒掉它们（见下面那组用例），这里测的是读侧也要独立地拒。
    """
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")   # created_by 默认 agent-G
    _append_raw(st, {"doc_id": "0000", "content_sha256": SIG.content_sha256_of(doc),
                     "name": "agent-G", "at": TS, "scope": "document", "verdict": "accepted",
                     "instance_id": "x", "evidence_path": "nope.json",
                     "evidence_sha256": "0" * 64,
                     "inputs": {"doc_sha256": SIG.content_sha256_of(doc)},
                     "basis": {}})
    assert "signer_not_reviewer" in _codes(st), _codes(st)


def test_negative_inputs_mismatch_bites(tmp_path: Path):
    """注入：签名的 `inputs.doc_sha256` 不是当前内容（"审的是另一版"）⇒ 必须咬。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    cur = SIG.content_sha256_of(doc)
    _append_raw(st, {"doc_id": "0000", "content_sha256": cur, "name": SIG.SIGNER_NAME,
                     "at": TS, "scope": "document", "verdict": "accepted",
                     "instance_id": "x", "evidence_path": "nope.json",
                     "evidence_sha256": "0" * 64,
                     "inputs": {"doc_sha256": "f" * 64}, "basis": {}})
    assert "signature_inputs_mismatch" in _codes(st), _codes(st)


def test_negative_evidence_tampered_bites(tmp_path: Path):
    """注入（§8.8.8 的六条之一）：证据快照被改一个字节 ⇒ `signature_evidence_unverifiable`。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    rec = _sign(st, doc)
    assert _codes(st) == []
    snap = Path(st.root) / str(rec["evidence_path"])
    snap.write_text(snap.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert "signature_evidence_unverifiable" in _codes(st), _codes(st)


def test_negative_evidence_outside_workspace_is_unverifiable(tmp_path: Path):
    """注入：证据锚写成越界路径（`../x`）⇒ 也判不可核（不许拿工作区外的文件当证据）。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    _append_raw(st, {"doc_id": "0000", "content_sha256": SIG.content_sha256_of(doc),
                     "name": SIG.SIGNER_NAME, "at": TS, "scope": "document",
                     "verdict": "accepted", "instance_id": "x",
                     "evidence_path": "../outside.json", "evidence_sha256": "0" * 64,
                     "inputs": {"doc_sha256": SIG.content_sha256_of(doc)}, "basis": {}})
    assert "signature_evidence_unverifiable" in _codes(st), _codes(st)


def test_negative_broken_chain_bites(tmp_path: Path):
    """注入：台账被插队/删行（`prev_hash` 对不上）⇒ `signature_ledger_corrupt`。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    _sign(st, doc)
    path = SIG.ledger_path(st.root)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines + [lines[-1]]) + "\n", encoding="utf-8")
    assert "signature_ledger_corrupt" in _codes(st), _codes(st)


def test_negative_unreadable_ledger_line_bites(tmp_path: Path):
    """注入：台账里有一行读不出来（JSON 坏了）⇒ 报 `signature_ledger_corrupt`，不静默跳过。"""
    st = _store(tmp_path)
    _doc(st, "0000", status="accepted")
    SIG.ledger_path(st.root).write_text("{ 这不是 JSON\n", encoding="utf-8")
    assert "signature_ledger_corrupt" in _codes(st), _codes(st)


def _append_raw(st: Store, record: dict) -> None:
    """绕过写侧闸门直接往台账追加一行（专测读侧判据）。"""
    recs, _bad = SIG.read_ledger(SIG.ledger_path(st.root))
    row = dict(record)
    row["prev_hash"] = SIG.line_hash(recs[-1]) if recs else ""
    with SIG.ledger_path(st.root).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":")) + "\n")


# ---------------------------------------------------------------- ③ 写侧闸门

def test_writer_refuses_a_non_reviewer(tmp_path: Path):
    """写侧闸门：`append_signature` 拒非 H 的签名者（禁自批）。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    with pytest.raises(ValueError, match="有资格签"):
        _sign(st, doc, name="agent-G")


def test_writer_refuses_a_non_accepting_verdict(tmp_path: Path):
    """写侧闸门：拒非接受档的判定。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    with pytest.raises(ValueError, match="接受档"):
        _sign(st, doc, verdict="rejected")


def test_writer_refuses_a_record_missing_required_fields(tmp_path: Path):
    """写侧闸门：缺必填字段（例如 `instance_id`）⇒ 拒，且不写半个文件。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    cur = SIG.content_sha256_of(doc)
    with pytest.raises(ValueError, match="缺必填字段"):
        SIG.append_signature(st.root, {"doc_id": "0000", "content_sha256": cur,
                                       "name": SIG.SIGNER_NAME, "at": TS, "scope": "document",
                                       "verdict": "accepted",
                                       "inputs": {"doc_sha256": cur}, "basis": {}})
    assert not SIG.ledger_path(st.root).exists(), "被拒的签名不许留下半个文件"


def test_writer_never_accepts_an_evidence_anchor_from_the_caller(tmp_path: Path):
    """写侧闸门：`evidence_path` / `evidence_sha256` 由函数自己产出，调用方填了也被覆盖。"""
    st = _store(tmp_path)
    doc = _doc(st, "0000", status="accepted")
    rec = _sign(st, doc, evidence_path="假装是证据.json", evidence_sha256="0" * 64)
    assert rec["evidence_path"].startswith(f"{SIG.EVIDENCE_DIR}/")
    assert rec["evidence_sha256"] != "0" * 64


# ---------------------------------------------------------------- §8.8.8 第 1、2 条（既有机制）

def test_existing_judges_for_proof_level_evidence_still_bite():
    """复跑 §8.8.8 第 1 条：`proof` 级的两条机械要件仍被 schema 拒（FC-22 同族）。"""
    base = dict(experiment_id="0000", claim="c", claim_key="k", method="formal",
                evidence_kind="proof", result="supports", negation_kind="not_proved",
                verifier_subject_key="k", code_path="code/x.py", code_hash="deadbeef")
    with pytest.raises(ValueError, match="verifier_output"):
        S.Experiment(**base).validate()
    with pytest.raises(ValueError, match="code_hash"):
        S.Experiment(**{**base, "verifier_output": "Lean: ok", "code_hash": ""}).validate()
    with pytest.raises(ValueError, match="formal"):
        S.Experiment(**{**base, "method": "numeric", "verifier_output": "x"}).validate()


def test_axiom_audit_still_forbids_sorry():
    """复跑 §8.8.8 第 2 条的结构性事实：`sorryAx` 在禁用侧、与允许集不相交。"""
    from agentflow import formalgw as FG

    assert "sorryAx" in FG.FORBIDDEN_AXIOMS, FG.FORBIDDEN_AXIOMS
    assert FG.FORBIDDEN_AXIOMS.isdisjoint(FG.ALLOWED_AXIOMS)
    # 绑名形态的解析（事后审计侧用它读"这条 proof 的依据"）
    got = FG._axioms_of("'probe' depends on axioms: [propext, sorryAx]", name="probe")
    assert "sorryAx" in got, got
