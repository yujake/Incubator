"""`draft/37` §37.4 ①（方案 A）的判据：外部论文的摄取链用既有工具就能走通。
## 这一条判据要挡的是什么
§37 那趟真机里，盘上明明有一篇论文，`documents` 表里却没有它 ——于是 `G.revise(doc_id="main")` / `H.review_report(doc_id="main")` /
`H.review(...)`四个审稿动作全部被拒（理由："稿件 main 不存在"）。缺的不是某个工具，而是"盘上的论文怎么进台账"这一步没有归属人。
用户 2026-10-02 裁定的方案 A把它定下来（零新增面）：
| 东西 | 落在哪 | 谁写 |
|---|---|---|
| 别人写的那份论文 | `literature`（`source_lit_id` 指向它） | A（`search.register` / `search.ingest_local`） |
| 论文里的定理/命题 | `statements`（`origin="external_lit"` + 逐字 `proof_text` + `page_range`） | B（`table.create`） |
| 我方修订稿 | `documents`（claims 的 citations 引 `lit:` / `exp:`） | G（`doc.build_document`） |
| 审阅发现 | `review_findings`（挂在我方稿件那一行上） | H（`review` 动作） |
## 两条由真机与探针逼出来的口径（写在这里免得下一个人再撞）
1. `Statements.origin` 的取值是 `external_lit` / `own_result`，
而 `evidence_kind` 是证据强度（`proof` / `cross_check` / `heuristic`），不是来源 —— 来源走 `source_lit_id`。第一版探针把 `origin` 写成
`literature`当场被 `validate()` 拒（`kind='validation'`）。
2. `ReviewFinding.doc_id` 是必填（`require_id(self.doc_id, "doc_id")`）⇒
发现只能挂在 `documents` 行上，挂不到 `literature` 行上。这正是方案 A 里"我方修订稿必须先有 `documents` 行"的结构原因 ——也是为什么"拿外部论文去
`revise`"不是一个可以绕过去的做法。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as SCHEMA
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.doc_tools import CROSS_CHECK_DISCLAIMER

#: 盘上的"外部论文"（只用来证明它真的在盘上；登记走的是台账那一侧）。
EXTERNAL_TEX = """\\documentclass{article}
\\begin{document}
\\begin{theorem}[主定理]
对任意有限群 $G$，某量 $c(G) \\le 1$。
\\end{theorem}
\\end{document}
"""

#: 外部论文里的那条定理（B 从正文里抽出来的三件套：完整假设 / 逐字证明 / 出处）。
EXTERNAL_STATEMENT = {
    "origin": "external_lit",
    "kind": "theorem",
    "label": "主定理",
    "statement_text": "对任意有限群 G，某量 c(G) ≤ 1",
    "statement_full": "设 G 是任意有限群，且 c 是某量；则 c(G) ≤ 1。",
    "proof_text": "Proof. 见第 3 节（外部论文的逐字摘录）。",
    "quote_verified": True,
    "quote_reason": "逐字比对通过（第 1 页）",
    "evidence_kind": "cross_check",
    "status": "active",
}


@pytest.fixture
def wired(tmp_path: Path):
    """一个工作区 + 真装配的工具面 + 接了线的 H（审阅动作要走 `conductor.summon`）。"""
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "source").mkdir(exist_ok=True)
    (tmp_path / "source" / "external.tex").write_text(EXTERNAL_TEX, encoding="utf-8")
    store = Store(tmp_path)
    store.init()
    # G 与 H 都真的接线：这样"拿外部来源的 id 当 doc_id"拒出来的理由是真的那句话
    # （"稿件 0000 不存在 ⇒ 不能修订一份不存在的稿件"），而不是"这个角色没接线"。
    conductor = Conductor(store, registry={"G": ("object", AgentG(store)),
                                          "H": ("object", AgentH(store))})
    reg = build_registry(store=store, conductor=conductor).registry
    return store, conductor, reg


def _register_external_paper(reg) -> str:
    """A 把外部论文登记成 `literature`，返回 lit_id。"""
    res = reg.call("search.register", role="A", title="外部论文（他人）", type_code="J",
                   summary="投影度量论方向的一篇外部稿")
    assert res.ok, res.error
    return str(res.data["lit_id"])


def _register_statement(store, lit_id: str) -> str:
    """B 把论文里的定理登记成 `statements`，返回 stmt_id（正路：B 交内容、秘书落盘）。

    这里不再用 `table.create(table="statements")`：那条约会被
    `store.direct_write_refusal` 受控拒绝（真机读数 `projects/mp2/sessions/mp2-7.jsonl`
    第 97 行 —— 手写 `bits={}` 的那一行），正路只有 `Secretary.record_statement`。
    """
    from agentflow.secretary import Secretary

    sec = Secretary("B", root=store.root, store=store)
    out = sec.record_statement({**EXTERNAL_STATEMENT, "source_lit_id": lit_id}, role="B")
    assert out["checked"] and out["created"], out
    return str(out["stmt_id"])


def _build_our_manuscript(reg, lit_id: str, *, text: str, evidence_kind: str = "cross_check") -> str:
    """G 写我方修订稿（`documents`），claims 引外部来源。"""
    res = reg.call("doc.build_document", role="G", kind="paper", title="我方修订稿",
                   claims=[{"claim_id": "c1", "section": "主定理", "text": text,
                            "evidence_kind": evidence_kind, "citations": [f"lit:{lit_id}"],
                            "disclaimer": CROSS_CHECK_DISCLAIMER
                            if evidence_kind == "cross_check" else ""}])
    assert res.ok, res.error
    return str(res.data["doc_id"])


def test_external_paper_intake_chain_is_walkable_with_existing_tools(wired):
    """    正控（① 的主判据）：盘上的论文 → `literature` → `statements` → 我方 `documents` → H 审过。

    四步全部经既有工具/动作走完，一步不新增；最后两条断言钉的是这件事的实质：可追溯的那条线：`statements.source_lit_id` 指外部来源，
    `documents.claims[].citations` 指同一条 `lit:` —— 两处指向同一个 id，才谈得上"改这篇论文时知道依据来自哪一篇"；
    - 审阅真的发生了（而不是"没报错"）：`checked is True`，且我方稿件的
    `documents.status` 由 `draft` 被推成 `accepted` —— 那是 H 记下它结论的地方（实测：`review` 动作在一份合规稿件上只改这一个键，`review_rounds` 不动）。
    这一条是刻意加的：干净的稿件产出零条发现，而"零条发现"与"根本没审"在读数上长得一模一样（本项目的三态纪律正是为这个而设；`test_agent_h.py` 里有那另一半：坏稿件必须被审出发现来）。

    顺带记一条写侧比读侧更早的事实：`doc.build_document` 在写入期就会拒掉"`cross_check` 却说已证明"这类过度声称（G12 的机械门），
    所以要造一份"有缺陷的稿件"必须绕过工具层（`test_agent_h.py` 的 `inject_raw_document` 就是这么做的）。也就是说：外部论文进来之后真正会出问题的地方，是语义那一半，不是机械那一半。
    """
    store, _conductor, reg = wired
    lit_id = _register_external_paper(reg)
    stmt_id = _register_statement(store, lit_id)
    doc_id = _build_our_manuscript(reg, lit_id, text="数值抽样与该结论一致（引自外部论文）。")
    # 这里刻意不断言 lit_id != doc_id：id 是按表分配的（`alloc_id` 的 id_kind），
    # 所以"第一篇文献"与"第一份稿件"都可能叫 `0000` —— 两个命名空间互不相干。
    # 这正是 §37 那次混得起来的原因，也是为什么拒信里那句"稿件 0000 不存在"必须点名
    # 是哪张表（判据在下面那条负控里）。

    # 2026-10-16（口径 S2）：这条考"确定性实现真的跑了"（稿件状态要变）⇒ 走内部 API；
    # 工具层那条路现在一律走角色自己的循环，不进确定性实现。
    res = _conductor.summon("H", "review", {"doc_id": doc_id}, by="M",
                            input_key="intake-chain")
    assert res.outcome == "ok", res
    assert res.status == "done", res
    assert res.checked is True, res

    doc = next(r for r in store.rows("documents") if str(r["doc_id"]) == doc_id)
    assert doc["status"] == "accepted", (
        f"H 审过之后稿件状态还是 {doc['status']!r} ⇒ 它没有留下任何结论（三态：没审 ≠ 审过没问题）")
    assert not [r for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id], (
        "这一份稿件是合规的，不该有发现；出现了说明判据的夹具坏了")

    # 可追溯的那条线：命题指向外部来源，我方稿件的断言也指向它。
    stmt = SCHEMA.row_from_dict("statements", next(r for r in store.rows("statements")
                                                 if str(r["stmt_id"]) == stmt_id))
    assert stmt.source_lit_id == lit_id
    assert f"lit:{lit_id}" in doc["claims"][0]["citations"]


def test_using_an_external_source_id_as_a_document_id_is_refused(wired):
    """负控（§37 那次的失败形态）：拿 `literature` 的 id 当 `doc_id` ⇒ 被拒，且不写任何东西。

    这是这次修复要挡住的具体动作：真机那趟 M 想"审这篇论文、polish 它"，
    手里只有盘上那份文件与一个来源 id 的概念，于是去 `revise` / `review_report`
    一个不存在的 doc_id。拒得明确比拒得含糊重要 —— 那条理由（"稿件 0000 不存在"）
    正是下一轮 M 该读到的东西：它说明"这条路不是给外部论文走的"，而不是"暂时不通"。
    """
    store, _conductor, reg = wired
    lit_id = _register_external_paper(reg)

    g = _conductor.summon("G", "revise", {"doc_id": lit_id}, by="M",
                          input_key="wrong-id-revise")
    assert g.outcome == "refused", g
    assert "不存在" in str(g.detail), g

    h = _conductor.summon("H", "review_report", {"doc_id": lit_id}, by="M",
                          input_key="wrong-id-review")
    assert h.outcome == "refused", h
    assert "不存在" in str(h.detail), h

    assert not [r for r in store.rows("documents")], "拒了却写出了稿件行"
    assert not [r for r in store.rows("review_findings")], "拒了却落下了发现"


def test_a_claimless_document_is_refused():
    """正控（方案 A 的结构原因）：没有 claims 的 `documents` 行写不进去。

    `Document.validate()` 逐字要求"claims 不能为空 —— 一份没有任何断言的稿件不是稿件"，
    而外部论文在抽取完成之前恰恰没有我们认可的 claims（它的定理是 B 的 `statements`）。
    于是"把外部论文直接登记成 `documents`"这条路不是"暂时没做"，是结构上不该走 ——
    这一条判据把那个理由钉在盘上，免得下次有人再试一遍（§37 的四个动作就是那么废掉的）。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="intake_claimless_") as td:
        root = Path(td)
        (root / "data").mkdir()
        store = Store(root)
        store.init()
        reg = build_registry(store=store).registry
        res = reg.call("doc.build_document", role="G", kind="paper", title="无断言的外部论文",
                       claims=[])
        assert res.ok is False, res
        assert "claims" in str(res.error), res.error
        assert not store.rows("documents"), "被拒的稿件不许留下半行"
