# -*- coding: utf-8 -*-
"""S1p：手稿过审之后有没有被逐条消化（业主 2026-10-09 的口径）。

业主逐字（`draft/83` §5.3(3b)）：

> 「且观查 B 侧的"证明消化"和 D 的手稿过审后是否被 B 消化或研究成果逐条入库。
> 前置条件具备了，C 才能在里面找依赖链」

T2 第 22 趟（`t2a`）的真机现场就是这一档要治的：① 手稿成稿 + ② H 过审都成立，
而 `statements=0`（手稿里的成果一条都没变成台账行）—— 收工门只报得出"报告缺附件一件"，
没有任何一格说得出来缺的是"消化"这一环；而 C 的最短依赖链正建在它上面。

判据（`draft/97` §9.4）：分子 = `status ∈ accepted/revised` 且至少有一条断言落成
`statements` 行（`origin=own_result`、`doc_id` 指向它、`kind != "concept"`）的稿件份数；
明细分列 `{theorems, concepts, docs_reviewed, docs_digested}`；未消化时给出路文案。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

TS = "2026-10-09T00:00:00+08:00"


def _store(tmp_path: pathlib.Path) -> Store:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st


def _doc(st: Store, doc_id: str, *, status: str) -> None:
    from agentflow import signatures as SIG

    row = {"doc_id": doc_id, "kind": "note", "title": f"手稿 {doc_id}", "sections": [],
           "claims": [{"claim_id": "c1", "section": "Main", "text": "一条成果",
                       "evidence_kind": "heuristic", "citations": ["lit:0000"]}],
           "open_problems": [], "status": status, "created_at": TS, "updated_at": TS}
    if status in ("accepted", "revised"):
        # `accepted/revised` 必须带内容哈希（审批钉的是某一版）：夹具照写侧口径补上
        row["content_sha256"] = SIG.content_sha256_of(row)
    with st.tx("documents", actor="test") as tx:
        tx.upsert("documents", row)


def _stmt(st: Store, stmt_id: str, *, doc_id: str, kind: str = "theorem") -> None:
    row = S.Statement(stmt_id=stmt_id, origin="own_result", kind=kind,
                      label=f"{kind} {stmt_id}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text="Proof. 逐字……", source_lit_id="0000",
                      page_range=S.PageRange(), quote_verified=True,
                      quote_reason="逐字比对通过", evidence_kind="cross_check",
                      status="active", doc_id=doc_id, line_range="1-20",
                      created_at=TS, created_by="test")
    row.validate()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict(), note="stmt")


def _read(st: Store, tmp_path: pathlib.Path) -> tuple[int, dict]:
    return CL._leg_reading(st, "reviewed_then_digested_rows", tmp_path / "ws")  # noqa: SLF001


def test_a_reviewed_manuscript_with_registered_results_counts(tmp_path: pathlib.Path):
    """正控：审过的手稿 + 它的成果逐条入库 ⇒ 这一档计 1，明细里分列定理与定义。"""
    st = _store(tmp_path)
    _doc(st, "0000", status="accepted")
    _stmt(st, "0000", doc_id="0000")                       # 定理
    _stmt(st, "0001", doc_id="0000", kind="concept")       # 定义（依赖图上的节点）
    n, det = _read(st, tmp_path)
    assert n == 1, det
    assert det["docs_reviewed"] == 1 and det["docs_digested"] == 1, det
    # 定义也入库那一档要看得见：所以两格分开数
    assert det["theorems"] == 1 and det["concepts"] == 1, det
    assert det["undigested"] == [], det


def test_a_reviewed_manuscript_without_registration_is_named(tmp_path: pathlib.Path):
    """负控：审过而成果一条都没入库 ⇒ 计 0，且逐份点名 + 给出路。

    这正是 T2 `t2a` 的真机形态（手稿 1 行、H 审过、`statements=0`）。
    """
    st = _store(tmp_path)
    _doc(st, "0000", status="revised")
    n, det = _read(st, tmp_path)
    assert n == 0, det
    assert det["docs_reviewed"] == 1 and det["docs_digested"] == 0, det
    assert [d["doc_id"] for d in det["undigested"]] == ["0000"], det
    assert "register_statement" in det["next_step"], det


def test_a_concept_alone_is_not_a_registered_result(tmp_path: pathlib.Path):
    """三态/口径：只登记了概念（`kind="concept"`）⇒ 不算"成果逐条入库"。

    概念是依赖图上的节点（它那一档要的是良定义性证明），不是"手稿里的研究结果"
    —— 业主 2026-10-09：「concept表真并进statements……proof里就证这个概念为什么是良定义的」。
    """
    st = _store(tmp_path)
    _doc(st, "0000", status="accepted")
    _stmt(st, "0000", doc_id="0000", kind="concept")
    n, det = _read(st, tmp_path)
    assert n == 0 and det["concepts"] == 1 and det["theorems"] == 0, det


def test_an_unreviewed_manuscript_is_out_of_this_row(tmp_path: pathlib.Path):
    """反真空：没审过的手稿不进这一档（这一档问的是"审过之后"）。

    它的分母是 `signatures.SIGNABLE_STATUSES`（与 `reviewed_current_rows` 同一处口径）——
    两份口径分家的症状是"一个说审过、一个说没审"。
    """
    from agentflow import signatures as SIG

    st = _store(tmp_path)
    _doc(st, "0000", status="draft")
    _stmt(st, "0000", doc_id="0000")
    n, det = _read(st, tmp_path)
    assert n == 0 and det["docs_reviewed"] == 0, det
    assert "accepted" in SIG.SIGNABLE_STATUSES and "revised" in SIG.SIGNABLE_STATUSES, \
        SIG.SIGNABLE_STATUSES


def test_the_kind_is_a_registered_controlled_row(tmp_path: pathlib.Path):
    """反真空：这一档必须是受控档（写错名字会让整张验收表判"没查成"）。"""
    assert "reviewed_then_digested_rows" in CL.LEG_CHECK_KINDS, sorted(CL.LEG_CHECK_KINDS)
    assert "reviewed_current_rows" in CL.LEG_CHECK_KINDS
