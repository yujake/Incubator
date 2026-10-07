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
    # `external_lit` 的第四个必填（`draft/37` §68）：出处页码。
    # 这一格此前不在夹具里 —— 而"夹具里没有的字段"正是真机上会空着的那一栏。
    "page_range": {"start": 1, "end": 2},
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


def test_an_unknown_lit_id_refusal_carries_the_literature_state(tmp_path: Path):
    """判据（`draft/37` §93）：`unknown_lit_id` 的拒绝必须带状态读数（几行、有哪些号）。

    真机读数（T1 第 8 趟）：这一条被拒了 20 次 —— 那一趟 `literature` 表 0 行
    （没人派 `A.ingest_local`），每一条 `external_lit` 命题都撞在同一堵墙上，
    而拒绝只说"没有这个 lit_id"，模型分不清"表是空的"与"号写错了"（处置完全不同），
    于是它换着号继续猜，20 次全废。读数里带上"表现在有几行、现有哪些 lit_id"，
    是这次调用失败所需要的那个事实（与 `draft/28` §196 给 documents 行同一口径）。
    """
    st = _store(tmp_path)  # 空 literature
    b = AgentB(st, extractor=None, extract_text=None)
    empty = b.register_statement(statement_full="设 G 是有限群。", origin="external_lit",
                                 source_lit_id="0000", page_range={"label": "全文未分页"},
                                 proof_text="Proof. 摘录。", quote_reason="还没查")
    assert empty["kind"] == "unknown_lit_id", empty
    assert empty["literature_rows"] == 0 and empty["available_lit_ids"] == [], empty
    assert "表是空的" in empty["error"], empty["error"]

    # 正控（有行时把真号列出来）：拿一个真的号就不会再撞这一堵墙
    lit_id = _lit(st, tmp_path)
    hit = b.register_statement(statement_full="设 G 是有限群。", origin="external_lit",
                               source_lit_id="9999", page_range={"label": "全文未分页"},
                               proof_text="Proof. 摘录。", quote_reason="还没查")
    assert hit["kind"] == "unknown_lit_id", hit
    assert hit["literature_rows"] == 1 and lit_id in hit["available_lit_ids"], hit


def test_b_register_statement_refuses_a_hollow_page_range(tmp_path: Path):
    """负控（§68 的真机形状）：`page_range` 在场但内容是空的 ⇒ 拒，且零写入。

    第十三趟真机就是这么写进六行的：`{"start": null, "end": null}` ——
    字段在、内容空 —— 而那六行在审稿判据里全部报了"缺 page_range（页码）"，
    整条验收不及格。这一条钉住"写入口与判据说同一件事"。
    """
    st = _store(tmp_path)
    lit_id = _lit(st, tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)

    hollow = b.register_statement(source_lit_id=lit_id,
                                  **{**STATEMENT, "page_range": {"start": None, "end": None}})
    assert hollow["ok"] is False and hollow["kind"] == "missing_page_range", hollow
    assert not st.rows("statements"), "被拒的命题不许留下半行"

    # 正控（逃生口）：没有页码但有别的定位（label）也算给了出处
    labeled = b.register_statement(source_lit_id=lit_id,
                                   **{**STATEMENT, "page_range": {"label": "全文未分页"}})
    assert labeled["ok"] is True, labeled
    assert len(st.rows("statements")) == 1

    # 边界（§68 甲档）：`own_result` 要的是「我们自己的」出处 —— 页码不算，
    # `doc_id` / `line_range` 才算；两者都没有就拒（否则它会编一个页码）。
    own_bare = b.register_statement(**{**STATEMENT, "origin": "own_result",
                                       "source_lit_id": "", "page_range": None})
    assert own_bare["ok"] is False and own_bare["kind"] == "missing_own_source", own_bare
    own = b.register_statement(**{**STATEMENT, "origin": "own_result", "source_lit_id": "",
                                  "page_range": None, "doc_id": "0000"})
    assert own["ok"] is True, own
    rows = st.rows("statements")
    assert len(rows) == 2, rows
    assert {r["origin"] for r in rows} == {"external_lit", "own_result"}, rows


def test_own_result_and_external_lit_want_different_source_fields(tmp_path: Path):
    """判据（甲档的两半）：`_c_statements` 按来源分档，两半各一条负控。

    为什么要分：从文献里摘的命题才有"第几页"；自有结果的出处是 `doc_id`/`line_range`。
    判据与写入口必须同档 —— 只改一处就会回到"台账看着有、判据说没有"（§68）。
    """
    from agentflow import reviewaccept as RA

    st = _store(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)

    def _crit() -> str:
        acc = RA.ReviewAcceptance()
        RA._c_statements(acc, st)
        return acc.criteria["statements_have_assumptions_and_source"]

    # 正控：自有结果给 doc_id ⇒ 通过（页空缺不扣分）
    b.register_statement(**{**STATEMENT, "origin": "own_result", "source_lit_id": "",
                            "page_range": None, "doc_id": "0000"})
    assert _crit() == "pass", st.rows("statements")

    # 负控：自有结果什么都不给 ⇒ fail（判据与写入口同一条规则）
    (tmp_path / "ws2").mkdir()
    st2 = _store(tmp_path / "ws2")
    with st2.tx("statements", actor="test") as tx:
        tx.upsert("statements", S.Statement(
            stmt_id="0000", origin="own_result", kind="theorem",
            statement_full="我们自己的结论", status="active",
            created_at="2026-01-01T00:00:00", source_lit_id=None,
            proof_text="证明：由定义直接推出（自产的，逐字证明见我方稿件）。",
            quote_verified=False, quote_reason="自有结果：没有可逐字比对的外部引文").to_dict())
    acc2 = RA.ReviewAcceptance()
    RA._c_statements(acc2, st2)
    assert acc2.criteria["statements_have_assumptions_and_source"] == "fail", acc2.details
    assert "own_result" in acc2.details["statements_have_assumptions_and_source"], acc2.details


def test_the_writer_and_the_reviewer_agree_on_page_range(tmp_path: Path):
    """判据（两处说同一件事）：写入口放行的行，审稿判据不许判它缺页码。

    这条判据的形状本身就是结论：`register_statement` 的预检与
    `reviewaccept._c_statements` 是同一件事的两个落点，一处放宽就会出现
    "台账上看着有出处、审稿时判没有"（第十三趟正是这样）。
    """
    from agentflow import reviewaccept as RA

    st = _store(tmp_path)
    lit_id = _lit(st, tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)
    res = b.register_statement(source_lit_id=lit_id, **STATEMENT)
    assert res["ok"] is True, res

    acc = RA.ReviewAcceptance()
    RA._c_statements(acc, st)
    assert acc.criteria["statements_have_assumptions_and_source"] == "pass", acc.details
    assert acc.readings["statements_missing_fields"] == [], acc.readings


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


def test_a_proofless_register_statement_is_recorded_and_marked_not_refused(tmp_path: Path):
    """新口径（P-06 / F-05 的主控裁定）：自产命题没有证明也登记，但如实标记。

    改前口径（本条原来钉的）：这一笔被 `_refuse("missing_proof_text")` 挡住、
    `tasks` 落 `refused/invalid_params`、`statements` 一行不许多。
    为什么改：`draft/53:181` 的消费端要的是"把待办摆出来"，而不是"把待办挡住" ——
    挡住了就永远没有一条待办能被秘书消费（真机后果就是"证明没做完"这件事在库里查不到）。
    硬顺序（主控点名）：本口径必须在 B 删掉 `schema.Statement.validate` 里那条
    `own_result` raise 之后才能落 —— 否则这一笔会在事务里抛 `ValueError`。

    新口径要六件同时成立：不拒 + 行落库 + `proof_text` 空 + `quote_verified is None` +
    `quote_reason` 非空 + 等级现算是"猜想"（不是证明级）；并且返回值里挂着
    `pending:[{kind:"missing_proof",…}]`（"没有静默接受"）。
    """
    from agentflow import evidencebits as EB

    st = _store(tmp_path)
    c = Conductor(st, registry=_agents(st))
    reg = build_registry(store=st, conductor=c).registry

    own = {**STATEMENT, "origin": "own_result", "source_lit_id": "",
           "page_range": None, "doc_id": "0000",
           "quote_verified": None, "quote_reason": "证明还没做完（推到第 3 步卡住）"}
    own.pop("proof_text")  # 自产命题、证明还没做完 ⇒ 登记 + 标记（不再拒绝）
    res = reg.call("conductor.summon", role="M", target_role="B", action="register_statement",
                   params=own, input_key="record-proof-text")
    assert res.ok, res.error
    assert res.data["outcome"] == "ok", res.data
    assert res.data["refusal_reason"] is None, res.data

    rows = st.rows("statements")
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("proof_text") or "") == "", row
    assert row.get("quote_verified") is None and str(row.get("quote_reason") or ""), row
    assert EB.derive_grade(row.get("bits") or {}) == "conjecture", row.get("bits")
    pending = res.data.get("payload", {}).get("pending") if isinstance(
        res.data.get("payload"), dict) else None
    if pending:                       # 返回值里挂着待办（形状取决于工具层的裁剪，能判就判）
        assert pending[0]["kind"] == "missing_proof", pending
        assert pending[0]["who"] == "F" and pending[0]["missing"] == "proof_text", pending
    # 真正的消费端判据（比读返回值那一格更硬）：F-05 的收件箱必须列出这一条
    # —— 生产端"如实标记"的意义就在"有人接得住它"（`draft/53:181` 的消费端）。
    from agentflow.secretary import Secretary

    inbox = Secretary("B", root=st.root, store=st).pending_inbox(window_sec=0)
    assert any(i["kind"] == "missing_proof" and i["id"] == row["stmt_id"]
               for i in inbox["items"]), inbox
    # 台账那一行也是 `ok`（它确实登记成功了）——"如实标记"落在 `pending` 与行里的三态上
    assert st.rows("tasks")[0]["outcome"] == "ok", st.rows("tasks")[0]
