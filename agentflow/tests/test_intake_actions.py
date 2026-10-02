"""`draft/37` §46 的判据：两条可召唤的动作，把"工具层通、编排层不通"那一格补上。

## 这一条判据挡的是什么（§44.4 的真机读数）

第二趟真机（`draft/37` §44）把"审阅并 polish 一篇外部论文"这条链走了一遍，
主控自己在交付说明里把断点定位到动作表上：A 的动作表里没有把盘上文件登记成
`literature` 的入口，B 的动作表里没有写 `statements` 的入口 ——
而主控只能 `conductor.summon` 动作（它自己也不许产出领域对象）。
于是盘上有论文、台账里没有它，后面每一跳（G 建我方稿件 → H 审）全部落空。

本轮按用户裁定加了两条动作：`A.ingest_local`、`B.register_statement`。
判据分三层，缺一层这件事就没修好：

1. 动作自身（正控 + 三态负控）：登记成没成要看计数，不看 `ok`；
   扩展名不支持时不许假装登记成功；
2. 与既有工具同一口径：`A.ingest_local` 与工具 `search.ingest_local` 对同一个目录
   必须给出同一份读数（`already_present` + 同一个 `lit_id` + 逐字相同的 provenance）——
   两份口径漂移时读台账的人无法判断哪一份是真的；
3. 编排层真的通（本文件最重要的一条）：主控通过 `conductor.summon` 依次走
   `A.ingest_local → B.register_statement → G.build_document → H.review`，
   四跳全部 `outcome=ok` 且四张表各有行。§43 证明的是工具层通，这一条证明的是
   编排层通 —— 两者之间正是那趟真机掉下去的地方。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import locallib as LL
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.agent_b import AgentB
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import ROLES, build_registry

PAPER_MD = """# 外部论文（他人写的）

## 主定理

设 G 是任意有限群，且 c 是某量；则 c(G) ≤ 1。

证明见第 3 节。
"""

STATEMENT = {
    "statement_full": "设 G 是任意有限群，且 c 是某量；则 c(G) ≤ 1。",
    "proof_text": "Proof. 见第 3 节（外部论文逐字摘录）。",
    "kind": "theorem",
    "label": "主定理",
    "statement_text": "对任意有限群 G，c(G) ≤ 1",
    "origin": "external_lit",
    "evidence_kind": "cross_check",
    "quote_verified": True,
    "quote_reason": "逐字比对通过（第 1 页）",
}


def _store(tmp_path: Path) -> Store:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "source").mkdir(exist_ok=True)
    (tmp_path / "source" / "external.md").write_text(PAPER_MD, encoding="utf-8")
    st = Store(tmp_path)
    st.init()
    return st


def _agents(st: Store) -> dict:
    """四个角色都接线：A（providers 空，ingest_local 不联网所以够用）、B、G、H。"""
    from agentflow.extract import extract_text

    return {
        "A": ("object", AgentA(st, providers=[])),
        "B": ("object", AgentB(st, extractor=None, extract_text=extract_text)),
        "G": ("object", AgentG(st)),
        "H": ("object", AgentH(st)),
    }


# ============================================================ 一、A.ingest_local

def test_a_ingest_local_registers_a_local_paper(tmp_path: Path):
    """正控：A 的动作把盘上那份外部论文登记成 `literature` 行（不联网）。"""
    st = _store(tmp_path)
    a = AgentA(st, providers=[])
    res = a.ingest_local(books_dir="source", pattern="*.md")
    assert res["ok"] is True, res
    assert res["ingested"] == 1 and res["unreadable"] == 0, res
    assert res["literature_ids"], res
    assert len(st.rows("literature")) == 1, st.rows("literature")
    row = st.rows("literature")[0]
    assert str(row["lit_id"]) == res["literature_ids"][0]
    assert row["path"], "登记进来的行要指回盘上那份文件（否则'这篇在哪'无从回答）"


def test_a_ingest_local_is_idempotent_and_agrees_with_the_tool(tmp_path: Path):
    """正控（同一口径）+ 幂等：动作与工具对同一个目录给出同一份读数。

    这一条挡的是"两份口径漂移"：`A.ingest_local`（动作）与 `search.ingest_local`
    （工具）都调 `locallib.ingest_directory`，但 provenance 那三句话是各自传的 ——
    一旦有人改了一处，读台账的人就无法判断哪一份才是真的。
    """
    st = _store(tmp_path)
    a = AgentA(st, providers=[])
    first = a.ingest_local(books_dir="source", pattern="*.md")
    assert first["ingested"] == 1, first

    reg = build_registry(store=st, workspace_root=tmp_path, roles=tuple(ROLES)).registry
    tool = reg.call("search.ingest_local", role="A", books_dir="source", pattern="*.md")
    assert tool.ok, tool.error
    assert tool.data["already_present"] == 1, tool.data
    assert tool.data["provenance"] == first["provenance"], (tool.data["provenance"],
                                                           first["provenance"])
    # 幂等命中时不该多出一行：同一个 sha256 = 同一篇文献
    assert len(st.rows("literature")) == 1
    assert tool.data["books"][0]["lit_id"] == first["literature_ids"][0]


def test_a_ingest_local_separates_not_found_from_nothing_matched(tmp_path: Path):
    """三态负控：目录不在 / 一个都没匹配上 / 有文件但不支持 —— 三种"没进来"必须分得开。

    - 目录不在盘上 ⇒ `ok=False`、`kind="dir_not_found"`、零写入；
    - pattern 没匹配上 ⇒ `ok=True`、`kind="nothing_matched"`、零写入；
    - 文件在、扩展名不支持（`.tex`）⇒ `ok=True`、`kind="unsupported_format"`、
      `unreadable=1` —— 这一档最容易被读成"登记成功"，所以它必须有自己的 kind。
    """
    st = _store(tmp_path)
    (tmp_path / "source" / "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    a = AgentA(st, providers=[])

    missing = a.ingest_local(books_dir="nope")
    assert missing["ok"] is False and missing["kind"] == "dir_not_found", missing
    assert not st.rows("literature"), "目录不在盘上却写了行"

    empty = a.ingest_local(books_dir="source", pattern="*.pdf")
    assert empty["ok"] is True and empty["kind"] == "nothing_matched", empty
    assert empty["ingested"] == 0 and not st.rows("literature")

    bad = a.ingest_local(books_dir="source", pattern="*.tex")
    assert bad["ok"] is True and bad["kind"] == "unsupported_format", bad
    assert bad["unreadable"] == 1 and bad["ingested"] == 0, bad
    assert not st.rows("literature"), ".tex 不在支持面内 ⇒ 不许登记成文献行"

    blank = a.ingest_local(books_dir="   ")
    assert blank["ok"] is False and blank["kind"] == "bad_books_dir", blank


# ============================================================ 二、B.register_statement

def _lit(st: Store, tmp_path: Path) -> str:
    a = AgentA(st, providers=[])
    return a.ingest_local(books_dir="source", pattern="*.md")["literature_ids"][0]


def test_b_register_statement_writes_a_complete_row(tmp_path: Path):
    """正控：一条合规命题写进 `statements`，三件套与三态那一栏都读得回来。"""
    st = _store(tmp_path)
    lit_id = _lit(st, tmp_path)
    b = AgentB(st, extractor=None, extract_text=LL.extract_text if hasattr(LL, "extract_text") else None)
    res = b.register_statement(source_lit_id=lit_id, **STATEMENT)
    assert res["ok"] is True, res
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    got = S.row_from_dict("statements", rows[0])
    assert got.stmt_id == res["stmt_id"]
    assert got.source_lit_id == lit_id
    assert got.statement_full == STATEMENT["statement_full"]
    assert got.proof_text == STATEMENT["proof_text"]
    assert got.quote_verified is True and got.origin == "external_lit"


def test_b_register_statement_refuses_bad_input_without_writing(tmp_path: Path):
    """负控四条：出处不存在 / 缺完整假设 / 缺出处 / 三态没写理由 —— 一律零写入。

    "出处不存在"那一条是本动作最值钱的一个拒绝：它挡的是把参考文献代号编出来
    （与 `doc.build_document` 的 `check_citations` 同一条纪律）。
    """
    st = _store(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)
    lit_id = _lit(st, tmp_path)

    ghost = b.register_statement(source_lit_id="9999", **STATEMENT)
    assert ghost["ok"] is False and ghost["kind"] == "unknown_lit_id", ghost

    shallow = b.register_statement(source_lit_id=lit_id, **{**STATEMENT, "statement_full": " "})
    assert shallow["ok"] is False and shallow["kind"] == "bad_statement", shallow

    no_source = b.register_statement(**{**STATEMENT, "source_lit_id": ""})
    assert no_source["ok"] is False and no_source["kind"] == "missing_source", no_source

    silent = b.register_statement(source_lit_id=lit_id,
                                  **{**STATEMENT, "quote_verified": None, "quote_reason": ""})
    assert silent["ok"] is False and silent["kind"] == "missing_quote_reason", silent

    bad_kind = b.register_statement(source_lit_id=lit_id,
                                    **{**STATEMENT, "evidence_kind": "literature"})
    assert bad_kind["ok"] is False and bad_kind["kind"] == "bad_evidence_kind", bad_kind

    assert not st.rows("statements"), "被拒的命题不许留下半行"


# ============================================================ 三、编排层：主控真的走通

def test_the_whole_chain_is_walkable_through_conductor_summon(tmp_path: Path):
    """编排层的正控（本文件的重点）：主控逐跳 summon，四张表各有行。

    §43 的判据是我以角色身份调工具，证明的是工具层通；真机掉下去的地方在
    编排层（主控只能 summon 动作）。所以这一条每一步都走 `conductor.summon`：

        A.ingest_local    → literature 1 行（拿到 lit_id）
        B.register_statement → statements 1 行（三件套 + 出处）
        G.build_document  → documents 1 行（claims 引 lit:）
        H.review          → 我方稿件 status 由 draft 推成 accepted

    每一步都断言 `outcome == "ok"`（不是"没报错"）：`refused` 是允许的失败形态，
    但它不算走通 —— 这条链要么四跳全 ok，要么判据红。
    """
    st = _store(tmp_path)
    c = Conductor(st, registry=_agents(st))
    reg = build_registry(store=st, conductor=c).registry

    hops: list[dict] = []
    lit = reg.call("conductor.summon", role="M", target_role="A", action="ingest_local",
                   params={"books_dir": "source", "pattern": "*.md"}, input_key="hop-a")
    hops.append(lit.data)
    assert lit.data["outcome"] == "ok", lit.data
    lit_id = st.rows("literature")[0]["lit_id"]

    stmt = reg.call("conductor.summon", role="M", target_role="B", action="register_statement",
                    params={"source_lit_id": lit_id, **STATEMENT}, input_key="hop-b")
    hops.append(stmt.data)
    assert stmt.data["outcome"] == "ok", stmt.data
    assert len(st.rows("statements")) == 1

    doc = reg.call("conductor.summon", role="M", target_role="G", action="build_document",
                   params={"kind": "paper", "title": "我方修订稿",
                           "claims": [{"claim_id": "c1", "section": "主定理",
                                       "text": "数值抽样与该结论一致（引自外部论文）。",
                                       "evidence_kind": "cross_check",
                                       "citations": [f"lit:{lit_id}"],
                                       "disclaimer": "数值交叉验证，不构成证明"}]},
                   input_key="hop-g")
    hops.append(doc.data)
    assert doc.data["outcome"] == "ok", doc.data
    doc_id = st.rows("documents")[0]["doc_id"]

    review = reg.call("conductor.summon", role="M", target_role="H", action="review",
                      params={"doc_id": doc_id}, input_key="hop-h")
    hops.append(review.data)
    assert review.data["outcome"] == "ok", review.data
    assert st.rows("documents")[0]["status"] == "accepted"

    # 四跳都在台账里留了行（"走通"要能在台账上复核，不只看返回值）
    assert [h["action"] for h in hops] == ["ingest_local", "register_statement",
                                           "build_document", "review"]
    assert all(h["status"] == "done" for h in hops), hops
    assert len(st.rows("tasks")) == 4, st.rows("tasks")
