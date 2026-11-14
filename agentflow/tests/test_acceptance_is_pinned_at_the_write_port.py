"""受控缺陷（DF 路，业主 2026-11-14「修缺陷」）：接受与钉版必须是同一次提交。

## 缺陷形态（真机现场）

`documents` 行被写成 `status=accepted`，而没有任何东西钉住"被接受的是哪一版"。
本仓没有 `signed_revision` / `accepted_at` 两列（`schema.Document` 在 FC-27 禁改区，
本批不动），既有口径是：

| 问题 | 既有数据落点 |
|---|---|
| 被接受的是哪一版 | `documents.content_sha256`（内容五字段的规范哈希，`signatures.CANONICAL_FIELDS`） |
| 这条审批钉在哪一版 | `DOC-SIGNATURES.jsonl` 里 `content_sha256` 等于它的那条签名（判据 `signatures.signed_revision`） |
| 接受时刻 | `documents.reviewed_at`（只有 `review_checked=True` 才写） |

所以"`signed_revision` 空"在本仓的读法是：台账里没有一条签名钉在当前这一版上。

## 根因

`review_document` 先把 `documents.status` 提交成 `accepted`，之后才写签名；
签名失败只回报 `signature_error`，状态不回滚 ⇒ 留下"accepted 但没钉住"
（`tests/test_rehearsal_c10_writing.py` 的断言只查成功终态，拦不住这个失败形态）。

## 判据（红 → 绿 + 反真空）

a) 正控：H.review 判 accepted ⇒ status=accepted、`signed_revision` 非空、`reviewed_at` 非空；
b) 红：把"写签名"打桩成抛 `OSError` ⇒ 必须受控拒（`status_error` 带受控码、
   status 不许变 accepted、`reviewed_at` 不许写）；
c) 反真空：撤掉 b 的打桩 ⇒ 同一份稿再 review ⇒ accepted 且钉住（证明 b 测的是这条收口）；
d) 旧盘：已经 accepted 却没有签名的行只被读成"终态未落全"
   （`verify` 的 `accepted_without_signature`），行本身一个字节不改。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentflow import signatures as SIG
from agentflow import verify as V
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import add_concept, add_literature, add_relation, sync_counters, write_paper

TS = "2026-01-01T00:00:00+00:00"
DISCLAIMER = "数值交叉验证，不构成证明"


def _store(tmp_path: Path) -> Store:
    """最小可审工作区：知识表 + 论文正文（H 审的对象是正文）。"""
    st = Store(tmp_path)
    st.init()
    write_paper(st, "\n".join([
        r"\documentclass{article}",
        r"\begin{document}",
        "谱落在区间内。",
        r"\end{document}",
        "",
    ]))
    add_literature(st, "0000", title="某文献", path=None, processed=True, sync=False)
    add_concept(st, "0000", "谱", definition="d", sync=False)
    add_concept(st, "0001", "区间", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True,
                 sync=False)
    sync_counters(st)
    return st


def _claim() -> dict:
    return {"claim_id": "c1", "text": "谱落在区间内。",
            "citations": ["rel:0000", "lit:0000"], "evidence_kind": "cross_check",
            "disclaimer": DISCLAIMER}


def _doc(st: Store, *, status: str = "draft") -> dict:
    """落一行稿件，内容哈希照写侧口径钉上（G 就是这样）。"""
    row: dict[str, Any] = {"doc_id": "0000", "kind": "paper", "title": "稿",
                           "sections": [], "claims": [_claim()], "open_problems": [],
                           "status": status, "created_at": TS, "updated_at": TS}
    row["content_sha256"] = SIG.content_sha256_of(row)
    with st.tx("documents", actor="fixture") as tx:
        tx.upsert("documents", row)
    return row


def _doc_now(st: Store) -> dict:
    return next(dict(r) for r in st.rows("documents") if str(r.get("doc_id")) == "0000")


def _records(st: Store) -> list[dict]:
    recs, bad = SIG.read_ledger(SIG.ledger_path(st.root))
    assert bad == [], bad
    return recs


# ====================================================================== a：正控
def test_a_review_accepts_with_a_pin_and_a_review_time(tmp_path: Path):
    """正常路径：H 复核通过 ⇒ accepted，且"哪一版"与"何时"都落了。"""
    st = _store(tmp_path)
    _doc(st)
    res = AgentH(st).review("0000", dependencies=[])
    assert res["verdict"] == "accepted" and res["status"] == "accepted", res
    assert res["status_updated"] is True
    doc = _doc_now(st)
    assert doc["status"] == "accepted"
    assert doc["reviewed_at"], "被接受了却没有接受时刻（reviewed_at 空）"
    assert SIG.signed_revision(doc, _records(st)) is not None, (
        "状态成了 accepted，而台账里没有签名钉住当前这一版")


# ====================================================================== b：红
def test_b_a_failed_signature_is_a_controlled_refusal_not_an_accepted_row(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """缺陷复现：签名没写成 ⇒ 受控拒；status 不许变 accepted。"""
    st = _store(tmp_path)
    _doc(st)

    def _boom(*_a: Any, **_kw: Any) -> dict:
        raise OSError("签名台账写不进去（本用例的打桩）")

    monkeypatch.setattr(SIG, "append_signature", _boom)
    res = AgentH(st).review("0000", dependencies=[])

    doc = _doc_now(st)
    assert res["signature"] is None, res["signature"]
    assert res["signature_error"] and "OSError" in res["signature_error"]
    assert res["status"] != "accepted", f"签名没写成却把状态置成 accepted：{res}"
    assert res["status_updated"] is False, res
    assert RV.CODE_ACCEPT_WITHOUT_PIN in str(res["status_error"]), res["status_error"]
    assert doc["status"] != "accepted", "盘上被置成 accepted —— 正是本缺陷的红"
    assert not str(doc.get("reviewed_at") or ""), "没接受却写了接受时刻"
    assert _records(st) == [], _records(st)


# ====================================================================== c：反真空
def test_c_undoing_the_stub_makes_the_same_document_accepted_and_pinned(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把 b 的打桩撤掉 ⇒ 同一份稿再 review ⇒ accepted 且钉住（b 不是恒红）。"""
    st = _store(tmp_path)
    _doc(st)
    h = AgentH(st)
    real = SIG.append_signature

    def _boom(*_a: Any, **_kw: Any) -> dict:
        raise OSError("签名台账写不进去（本用例的打桩）")

    monkeypatch.setattr(SIG, "append_signature", _boom)
    refused = h.review("0000", dependencies=[])
    assert refused["status"] != "accepted", refused

    monkeypatch.setattr(SIG, "append_signature", real)
    assert SIG.append_signature is real, "撤桩没生效 ⇒ 本用例会真空通过"
    accepted = h.review("0000", dependencies=[])
    doc = _doc_now(st)
    assert accepted["status"] == "accepted" and doc["status"] == "accepted", accepted
    assert accepted["signature"] is not None, accepted.get("signature_error")
    assert doc["reviewed_at"], "接受时刻没落"
    assert SIG.signed_revision(doc, _records(st)) is not None


# ====================================================================== d：旧盘
def test_d_an_accepted_row_without_a_pin_is_read_as_incomplete_and_never_rewritten(
        tmp_path: Path):
    """旧盘：accepted 而台账里没签名 ⇒ 只报读数，不自动改写历史行。"""
    st = _store(tmp_path)
    row = _doc(st, status="accepted")
    before = json.dumps(row, sort_keys=True, ensure_ascii=False)

    issues = [i for i in V.verify_all(st).issues
              if i.table == "documents" and i.code == "accepted_without_signature"]
    assert issues, [i.to_dict() for i in V.verify_all(st).issues]
    assert "签名" in issues[0].message, issues[0].message

    after = _doc_now(st)
    assert json.dumps(after, sort_keys=True, ensure_ascii=False) == before, (
        "读一遍就把历史行改了 —— 历史行冻结")
    assert after["status"] == "accepted", "历史行不许被自动改回 in_review"
