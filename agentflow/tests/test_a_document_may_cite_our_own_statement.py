# -*- coding: utf-8 -*-
"""T1 第 20 趟实测抓出来的缺口：稿件引用我们自己的命题（`stmt:`）曾经整笔写不进去。

`doc.build_document` 的事务原先只声明五张表（`documents`/`literature`/`relations`/
`experiments`/`eval_results`），而 `check_citations` 是按 `schema.CITATION_PREFIXES`
（六张）逐条核引用的 —— `stmt:` 指向的正是 `statements`。于是一份引用自家命题的稿件
（`citations: ["stmt:0001"]`，正是提示词教的那种写法）会在事务里读到一张没声明的表：

    存储故障：事务未声明表 statements（声明了 ('literature', 'relations',
    'experiments', 'documents', 'eval_results', 'counters')）

⇒ 整笔不写库、`documents` 永远是 0 行 ⇒ 收工门的 P9（我方稿件被审过）红了三趟
（`draft/83` §7.2 的 t1r/t1s/t1t）。这条判据就是那次真机读数的机器形态。

## 判据（正控 1 / 负控 1 / 反真空 1）

正控：库里有那条命题 ⇒ 引用它的稿件落库（`documents` +1）。
负控：库里没有那条命题 ⇒ 报 `dangling_citation`（"指向不存在的对象"），
  而不是存储故障 —— 证明这一格真的在核存在性，而不是"多声明一张表就放行"。
反真空：没有 store ⇒ 明确拒绝（`citation_check_not_possible`），不许当"引用都存在"。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools.doc_tools import build_document

TS = "2026-10-09T00:00:00+08:00"


def _store(tmp_path: pathlib.Path, *, with_statement: bool) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    if with_statement:
        lit = S.Literature(lit_id="0000", title="一篇外部论文", type="J",
                           summary="外部文献的一句话摘要", path=None, added_at=TS)
        lit.validate()
        with st.tx("literature", actor="test", note="lit probe") as tx:
            tx.upsert("literature", lit.to_dict(), note="lit probe")
        stmt = S.Statement(stmt_id="0000", origin="external_lit", kind="theorem",
                           label="Theorem 0.1", statement_text="命题短版",
                           statement_full="若假设 A 成立，则结论 B 成立",
                           proof_text="Proof. 逐字摘录……", source_lit_id="0000",
                           quote_verified=True, quote_reason="逐字比对通过",
                           evidence_kind="cross_check",
                           status="active", created_at=TS)
        stmt.validate()
        with st.tx("statements", actor="test", note="stmt probe") as tx:
            tx.upsert("statements", stmt.to_dict(), note="stmt probe")
    return st


def _claims() -> list[dict]:
    return [{"claim_id": "c1", "section": "Main", "text": "甲（引我们自己的命题）",
             "evidence_kind": "heuristic", "citations": ["stmt:0000"]}]


def test_a_document_may_cite_our_own_statement(tmp_path: pathlib.Path):
    """正控：引用自家命题的稿件要写得进去（事务必须声明 `statements`）。"""
    st = _store(tmp_path, with_statement=True)
    build_document(store=st, kind="paper", title="引自家命题的稿", claims=_claims(),
                   workspace_root=str(tmp_path), actor="test")
    rows = st.rows("documents")
    assert len(rows) == 1, rows
    assert str(rows[0]["kind"]) == "paper"
    assert rows[0]["claims"][0]["citations"] == ["stmt:0000"]


def test_a_dangling_statement_citation_is_refused_by_design(tmp_path: pathlib.Path):
    """负控：库里没有那条命题 ⇒ 拒绝的理由必须是"引用不存在"，不是存储故障。"""
    st = _store(tmp_path, with_statement=False)
    with pytest.raises(Exception) as err:
        build_document(store=st, kind="paper", title="引不存在的命题", claims=_claims(),
                       workspace_root=str(tmp_path), actor="test")
    text = str(err.value) + str(getattr(err.value, "details", ""))
    assert "不存在" in text, text
    assert "事务未声明表" not in text, ("这条不该再以存储故障的形态出现：", text)
    assert st.rows("documents") == [], "被拒的稿件一行都不许落"


# --------------------------------------------------------------------------------------
# 同族的第二处（真机 t1v 抓出来的）：`revise` 的事务也漏了 `statements`
# --------------------------------------------------------------------------------------

def _agent_g(st: Store):
    from agentflow.agent_g import AgentG

    return AgentG(st, config={"docs_subdir": "documents"})


def _revise_claims() -> list[dict]:
    return [{"claim_id": "c1", "section": "Main", "text": "甲（改后仍引自家命题）",
             "evidence_kind": "heuristic", "citations": ["stmt:0000"]}]


def test_a_revision_may_cite_our_own_statement(tmp_path: pathlib.Path):
    """正控：修订一条引用自家命题的断言也要写得进去（`revise` 的事务声明一样要含 `statements`）。

    真机 t1v 的现场（`draft/94` §10）：M 派 G 去按 H 的审校发现修订稿件，G 报
    「StoreError 事务未声明表 statements」⇒ 修订这条路整条不通，M 只能绕道
    （重建一份新稿）。同一个缺口在 `build_document` 上已经修过一次（`a3f4c83`），
    而 `revise` 是另一个入口 —— 一处改完、另一处没跟着改。
    """
    st = _store(tmp_path, with_statement=True)
    doc = build_document(store=st, kind="paper", title="引自家命题的稿", claims=_claims(),
                         workspace_root=str(tmp_path), actor="test")
    g = _agent_g(st)
    out = g.revise(str(doc["doc_id"]), new_claims=_revise_claims(), note="按 H 的意见改")
    row = next(r for r in st.rows("documents") if str(r["doc_id"]) == str(doc["doc_id"]))
    assert row["status"] == "revised" and int(row["review_rounds"]) == 1, row
    # 落进去的那条断言带着自家命题的引用（`claim_id` 由 `normalize_claims` 归一，
    # 所以这里判的是"新增或替换发生了一次"，不是那个代号字面）
    assert out["appended_claim_ids"] or out["replaced_claim_ids"], out
    assert any("stmt:0000" in (c.get("citations") or []) for c in row["claims"]), row["claims"]


def test_a_revision_citing_a_missing_statement_is_refused_by_design(tmp_path: pathlib.Path):
    """负控：修订引一条不存在的命题 ⇒ 理由必须是"引用不存在"，不是存储故障。"""
    st = _store(tmp_path, with_statement=True)
    doc = build_document(store=st, kind="paper", title="引自家命题的稿", claims=_claims(),
                         workspace_root=str(tmp_path), actor="test")
    g = _agent_g(st)
    bad = [{"claim_id": "c1", "section": "Main", "text": "甲（引不存在的命题）",
            "evidence_kind": "heuristic", "citations": ["stmt:9999"]}]
    with pytest.raises(Exception) as err:
        g.revise(str(doc["doc_id"]), new_claims=bad)
    text = str(err.value) + str(getattr(err.value, "details", ""))
    assert "不存在" in text and "事务未声明表" not in text, text
    row = next(r for r in st.rows("documents") if str(r["doc_id"]) == str(doc["doc_id"]))
    assert row["status"] != "revised" and int(row["review_rounds"] or 0) == 0, row


# --------------------------------------------------------------------------------------
# 业主 2026-10-09：「手稿不是正常引文」是对的；「必须从零重搭、不以引文格式落实」是错的
# --------------------------------------------------------------------------------------

def test_a_manuscript_may_cite_our_own_manuscript(tmp_path: pathlib.Path):
    """正控：研究手稿阶段可以互相引用我方手稿（两段式 `doc:<稿件>`）。

    业主逐字（2026-10-09）：「明确：研究手稿阶段可以互相引用，正式论文阶段只能引用
    真实论文，正式论文中手稿内容不可直接引用，必须重建」。

    改前的现场（`temp/_probe_own_manuscript_cite.py` 的读数）：
    `doc:0000` ⇒ `内部引用形状不对：应为 doc:<稿件>#<断言>@<内容哈希前 16 位>` ——
    两段式根本不合法，「用手稿里的成果」只剩"在正文里重搭一遍"一条路。
    """
    from agentflow import signatures as SIG
    from agentflow.tools.doc_tools import check_citations

    st = _store(tmp_path, with_statement=True)
    first = build_document(store=st, kind="note", title="第一份手稿", claims=_claims(),
                           workspace_root=str(tmp_path), actor="test")

    def _read(cite: str, *, kind: str = "note") -> dict:
        return check_citations(lambda t: st.rows(t),
                               [{"claim_id": "c9", "citations": [cite]}],
                               citing_kind=kind)

    did = str(first["doc_id"])
    whole = _read(f"doc:{did}")
    assert whole["missing"] == [] and whole["resolved"] == 1, whole
    # 读数：这是"引整份手稿"且没钉版本 ⇒ 两格都要看得见（不许与"钉过了"混作一谈）
    assert whole["doc_whole"] == [f"doc:{did}"], whole
    assert whole["doc_unpinned"] == [f"doc:{did}"], whole
    # 钉了版本的两段式：哈希对上 ⇒ 通过且不再是"没钉版本"；对不上 ⇒ 照旧失效
    pinned = _read(f"doc:{did}@{SIG.ref_hash_of(st.rows('documents')[0])}")
    assert pinned["missing"] == [] and pinned["doc_unpinned"] == [], pinned
    bad = _read(f"doc:{did}@{'0' * SIG.REF_HASH_LEN}")
    assert bad["missing"] and "改稿之后旧引用失效" in bad["missing"][0]["why"], bad
    # 三段式照旧（回归护栏）——断言代号取盘上那一行归一之后的值，不手抄
    row0 = st.rows("documents")[0]
    three = _read(SIG.doc_ref(did, str(row0["claims"][0]["claim_id"]), row0))
    assert three["missing"] == [], three
    # 手稿不是文献（业主"对的"那一半一个字没动）：`lit:` 走的是 `literature` 表，
    # 永远不会被读成"引我方手稿"这一档（这个夹具里 lit_id 与 doc_id 恰好都是
    # `0000`，所以这里判的是"通道分得开"，不是"这个号不存在"）
    lit_read = _read(f"lit:{did}")
    assert lit_read["doc_whole"] == [] and lit_read["doc_unpinned"] == [], lit_read


def test_a_formal_paper_may_not_cite_a_manuscript_directly(tmp_path: pathlib.Path):
    """负控：正式论文（`kind="paper"`）里 `doc:` 一律拒，理由必须说"重建"。

    业主逐字（2026-10-09）：「正式论文阶段只能引用真实论文，正式论文中手稿内容
    不可直接引用，必须重建」⇒ 论文要用手稿里的成果，就得在正文里重建，
    再以 `stmt:` / `exp:` / `rel:` 引它变成的台账行。
    """
    from agentflow.tools.doc_tools import check_citations

    st = _store(tmp_path, with_statement=True)
    first = build_document(store=st, kind="note", title="第一份手稿", claims=_claims(),
                           workspace_root=str(tmp_path), actor="test")
    did = str(first["doc_id"])
    got = check_citations(lambda t: st.rows(t),
                          [{"claim_id": "c9", "citations": [f"doc:{did}"]}],
                          citing_kind="paper")
    assert got["missing"], "论文引手稿必须被拒"
    why = got["missing"][0]["why"]
    assert "必须重建" in why and "lit:" in why, why
    assert got["doc_whole"] == [] and got["resolved"] == 0, got
    # 同一份引用在手稿阶段通过 ⇒ 这一条判的是"阶段"，不是"引谁都行"
    ok = check_citations(lambda t: st.rows(t),
                         [{"claim_id": "c9", "citations": [f"doc:{did}"]}],
                         citing_kind="note")
    assert ok["missing"] == [], ok
    # 论文引真实论文照旧（`lit:` 那一档一个字没动）
    with st.tx("literature", actor="test", note="lit") as tx:
        tx.upsert("literature", S.Literature(
            lit_id="7777", title="一篇真论文", type="J", summary="s", path=None,
            added_at=TS).to_dict(), note="lit")
    lit = check_citations(lambda t: st.rows(t),
                          [{"claim_id": "c9", "citations": ["lit:7777"]}],
                          citing_kind="paper")
    assert lit["missing"] == [], lit


def test_a_whole_manuscript_citation_needs_that_manuscript_to_exist(tmp_path: pathlib.Path):
    """负控：两段式放行的是形状，不是"引谁都行"—— 没有那份手稿照样拒，且理由分开。"""
    from agentflow.tools.doc_tools import check_citations

    st = _store(tmp_path, with_statement=True)
    got = check_citations(lambda t: st.rows(t),
                          [{"claim_id": "c9", "citations": ["doc:9999"]}])
    assert got["missing"] and "没有 doc_id" in got["missing"][0]["why"], got
    assert "形状不对" not in got["missing"][0]["why"], got
