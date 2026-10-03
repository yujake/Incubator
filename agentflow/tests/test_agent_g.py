"""智能体 G（`agent_g.py`）与 `tools/doc_tools.py` 的性质测试。

这里锁住五条最容易悄悄做错的性质（每条都配负控：既要"好数据必须过"，
也要"刻意造出来的坏数据必须被拦"——只有绿灯不能证明闸门在工作）：

1. `compose_claim` 的自动补全与构造时报错（FC-22 / FC-25 / FC-02）；
2. `build_document` 落库 + 渲染，且渲染里看得见三分档统计、否定分类表、
   依赖表与每条断言的引用；
3. `register_dependency` 的 `closed` 必须用真实数据核到已入库来源
   （这一点 schema 查不出来，是 FC-23 的第一道闸）；
4. `revise` 只动自己的稿、只动 finding 的 status/resolution_note；
5. `out_path` 越界即拒绝（沙箱边界不是建议）。

全部离线、确定性，不联网、不调 LLM、不依赖 `agent_e` / `agent_f`
（它们由另一路并行开发；G 需要的实验证据一律从 `experiments` 表直接读）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_g import AgentG, DocumentError
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import doc_tools as DT

from conftest import add_literature

TS = "2026-01-01T00:00:00+00:00"


# ============================================================ 辅助


def sync_all_counters(st: Store) -> None:
    """把 counters.json 对齐到"每张表 max(已用)+1"。

    conftest 的 `sync_counters` 只覆盖 lit/concept/relation（它当初只需要那三张表），
    而 G/H 会用到 experiment / doc / dep / finding；`verify` 会检查 counters 与
    已用 ID 的一致性，夹具不补这几张表就会引入与本用例无关的 `counter_behind` 噪音
    —— 而噪音比不校验更糟：它会训练人忽略告警。
    """
    counters: dict[str, int] = {}
    for kind, table in (
        ("lit", "literature"),
        ("concept", "concepts"),
        ("relation", "relations"),
        ("question", "research_questions"),
        ("report", "analysis_reports"),
        ("experiment", "experiments"),
        ("plan", "attack_plans"),
        ("doc", "documents"),
        ("dep", "dependencies"),
        ("finding", "review_findings"),
    ):
        field = S.TABLES[table]["id_field"]
        ids = [int(r[field]) for r in st.rows(table) if field in r]
        counters[kind] = (max(ids) + 1) if ids else 0
    (st.data / "counters.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "counters": counters}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_experiment(
    st: Store,
    exp_id: str,
    *,
    method: str = "numeric",
    evidence_kind: str = "cross_check",
    result: str = "supports",
    negation_kind: str = "not_proved",
    verifier_output: str = "",
    verifier_subject_key: str = "",
    sync: bool = True,
) -> dict:
    """插入一条合法的 experiments 行（conftest 里没有实验表的构造器）。

    `formal` + `proof` 时必须有 `verifier_subject_key`（新硬约束：
    检查器输出必须绑定到它管的那个命题）。默认填成本行的 `claim_key`。
    """
    row = S.Experiment(
        experiment_id=exp_id,
        claim="被检验的命题",
        claim_key=f"claim-key-{exp_id}",
        method=method,
        evidence_kind=evidence_kind,
        result=result,
        negation_kind=negation_kind,
        verifier_output=verifier_output,
        verifier_subject_key=verifier_subject_key or (
            f"claim-key-{exp_id}" if evidence_kind == "proof" else ""
        ),
        created_at=TS,
    )
    row.validate()
    with st.tx("experiments", actor="test", note="fixture") as tx:
        tx.upsert("experiments", row.to_dict())
    if sync:
        sync_all_counters(st)
    return row.to_dict()


def add_finding(
    st: Store,
    doc_id: str,
    *,
    kind: str = "overclaim",
    level: str = "error",
    target: str = "claim-1",
    evidence: str = "evidence_kind='cross_check' 但正文含 已证明",
    message: str = "把交叉验证写成了证明",
) -> dict:
    """插入一条合法的 ReviewFinding 行（模拟 H 的产出）。"""
    with st.tx("review_findings", actor="agent-H", note="fixture") as tx:
        row = S.ReviewFinding(
            finding_id="",
            doc_id=doc_id,
            kind=kind,
            level=level,
            target=target,
            evidence=evidence,
            message=message,
            round=1,
            status="open",
            created_at=TS,
        )
        row.finding_id = tx.alloc_id("finding")
        row.validate()
        tx.upsert("review_findings", row.to_dict())
    return row.to_dict()


#: proof 级断言必须给出的落点（`D-1` 写入期判据）：工作区里的一个真文件。
#:
#: 为什么这里要真的写一个 `.lean` 文件而不是编一个路径：新的 `check_proofs` 会在
#: `build_document` 里按工作区根解析它并 `is_file()`。编路径的夹具会红 ——
#: 而那样红说明的是"判据在起作用"，不是"夹具写错了"。这条夹具同时是那个判据的正控。
PROOF_REL = "proofs/fixture_proof.lean"


@pytest.fixture
def g_store(store: Store) -> Store:
    """最小可写稿的数据：1 篇文献 + 1 条 formal/proof 实验 + 1 条 numeric 实验。"""
    add_literature(store, "0000", title="Companion book：[6, Thm 6.5]", processed=True, sync=False)
    # `E-2`（人裁 = verify 侧事后加严）之后，proof 行的 `verifier_output` 里必须
    # 出现它自己的 `verifier_subject_key` —— 否则 `verify_all` 报 `selfreported_proof`
    # （"这条 proof 是自报的"）。夹具于是写成检查器真跑过的那种输出形态：
    # `formalgw` 真跑 Lean 时打印的正是它检查的那条 key。
    add_experiment(store, "0000", method="formal", evidence_kind="proof",
                   verifier_output="Lean4: 'claim-key-0000' does not depend on any axioms")
    add_experiment(store, "0001")
    # proof 级断言要有一个可复核的落点（`D-1`）：在工作区里放一份能被打开的文件。
    proof_file = Path(store.root) / PROOF_REL
    proof_file.parent.mkdir(parents=True, exist_ok=True)
    proof_file.write_text(
        "theorem fixture_proof : True := trivial  -- 夹具：仅用于证明落点存在\n",
        encoding="utf-8",
    )
    sync_all_counters(store)
    return store


@pytest.fixture
def g(g_store: Store) -> AgentG:
    return AgentG(g_store, config={"docs_subdir": "documents"})


def _clean_claims(g: AgentG) -> list[dict]:
    return [
        g.compose_claim(
            "由形式化检查器核验：Spec K(m) = [−m, m]。",
            citations=["exp:0000", "lit:0000"],
            evidence_kind="proof",
            section="主要结果",
            proof_location=PROOF_REL,
        ),
        g.compose_claim(
            "数值抽样在 10^4 个点上支持 Spec K(m) ⊆ [−m, m]。",
            citations=["exp:0001"],
            evidence_kind="cross_check",
            section="数值证据",
        ),
        g.compose_claim(
            "本项目未能证明该结论对非交换环成立。",
            citations=["lit:0000"],
            evidence_kind="heuristic",
            section="开放问题",
            is_negative=True,
            negation_kind="not_proved",
        ),
    ]


# ============================================================ [1] compose_claim


def test_compose_claim_autofills_cross_check_disclaimer(g: AgentG):
    """正向：`cross_check` 的「不构成证明」声明由结构自动填上，不靠调用方记得写。"""
    claim = g.compose_claim(
        "数值抽样支持该结论。", citations=["exp:0001"], evidence_kind="cross_check", section="数值证据"
    )
    assert claim["disclaimer"] == DT.CROSS_CHECK_DISCLAIMER
    assert claim["citations"] == ["exp:0001"]
    assert claim["evidence_kind"] == "cross_check"
    assert claim["is_negative"] is False and claim["negation_kind"] is None
    assert claim["claim_id"], "必须给一个可定位的断言代号"
    # 非 cross_check 的断言不该被塞进这句声明（否则它会变成噪音，H 也就无法精确匹配）
    proof = g.compose_claim("x", citations=["exp:0000"], evidence_kind="proof", section="s")
    assert proof["disclaimer"] == ""


def test_gate_rejects_claim_without_citations(g: AgentG):
    """负控：无引用的断言在构造时就炸（不是等写库才炸）。"""
    with pytest.raises(ValueError, match="citations"):
        g.compose_claim("没有引用的一句话。", citations=[], evidence_kind="heuristic", section="s")
    with pytest.raises(ValueError, match="空元素"):
        g.compose_claim("x", citations=[""], evidence_kind="heuristic", section="s")


def test_gate_rejects_cross_check_written_as_proof(g: AgentG):
    """负控：把交叉验证写成「已证明」必须抛 —— 这是本领域最危险也最自然的过度声称。

    同时验证防误伤：`proof` 级断言里出现"已证明"是允许的。
    """
    for text in ("我们已证明该结论。", "由此得证，定理成立。", "This is proved in the companion book."):
        with pytest.raises(ValueError, match="已证明|得证|proved"):
            g.compose_claim(text, citations=["exp:0001"], evidence_kind="cross_check", section="s")
    ok = g.compose_claim("我们已证明该结论。", citations=["exp:0000"], evidence_kind="proof", section="s")
    assert ok["evidence_kind"] == "proof"
    assert "已证明" in ok["text"]


def test_gate_rejects_negative_claim_without_classification(g: AgentG):
    """负控：否定型断言没给 `negation_kind` 必须抛（不静默填默认值）。"""
    with pytest.raises(ValueError, match="negation_kind"):
        g.compose_claim(
            "该推广不成立。", citations=["lit:0000"], evidence_kind="heuristic", section="s", is_negative=True
        )
    # 给了分类就通过，且分类被原样保留（不做任何"聪明"的推断）
    ok = g.compose_claim(
        "该推广不成立。",
        citations=["lit:0000"],
        evidence_kind="heuristic",
        section="s",
        is_negative=True,
        negation_kind="disproved",
    )
    assert ok["is_negative"] is True and ok["negation_kind"] == "disproved"
    # 非否定型却带 negation_kind 也要抛：否则"否定型结论"的计数会虚高（FC-25）
    with pytest.raises(ValueError, match="虚高"):
        g.compose_claim(
            "x", citations=["lit:0000"], evidence_kind="heuristic", section="s", negation_kind="not_proved"
        )


# ============================================================ [2] build_document


def test_build_document_writes_row_and_renders_required_tables(g: AgentG, g_store: Store):
    """正向：写库 + 渲染，且渲染里必须看得见 citations / disclaimer / 三张强制表。"""
    claims = _clean_claims(g)
    doc = g.build_document(
        "paper",
        "K(m) 的谱刻画",
        claims=claims,
        open_problems=["非交换环情形尚未处理"],
    )
    doc_id = doc["doc_id"]
    assert [r["doc_id"] for r in g_store.rows("documents")] == [doc_id]
    assert doc["status"] == "draft" and doc["review_rounds"] == 0
    assert doc["markdown_path"] == f"documents/{doc_id}.md"

    path = Path(g_store.root) / doc["markdown_path"]
    assert path.exists(), "渲染出来的 markdown 必须真的落盘（markdown_path 是追溯链的一环）"
    text = path.read_text(encoding="utf-8")

    # ---- 每条断言的引用与声明
    for c in doc["claims"]:
        for cite in c["citations"]:
            assert cite in text
    assert DT.CROSS_CHECK_DISCLAIMER in text, "cross_check 的「不构成证明」必须出现在稿件里"
    # ---- 证据等级三分档统计（FC-10，禁止单一通过率）
    assert "证据等级统计" in text
    for k in S.EVIDENCE_KINDS:
        assert f"| `{k}` |" in text, f"三分档统计缺 {k}"
    # ---- FC-25 的四种否定分开计数
    assert "否定型结论分类" in text
    for k in S.NEGATION_KINDS:
        assert k in text
    # ---- 依赖表（FC-23）
    assert "依赖（FC-23" in text
    assert "未分节" not in text, "断言都给了 section，不该落到兜底分组"
    assert "非交换环情形尚未处理" in text


def test_out_path_may_not_clobber_a_file_the_framework_does_not_own(g: AgentG, g_store: Store):
    """负控（`draft/37` §91 的真机读数）：`out_path` 指到既有文件 ⇒ 拒，且一个字节都不变。

    T1 第 5 趟实测：主控传 `out_path="out/paper/main.tex"` —— 它把"生成 markdown 的落点"
    当成了"论文本体该写在哪"（那个参数当时没有任何描述）—— 于是这一动作把 26,155 字节的
    论文正文整份覆盖成 3,992 字节的台账稿。此后 28 步都在试图把正文从 `source/` 拼回来，
    26 KB 的 `fs.write` 被输出额度截断 ⇒ 连续三次坏 JSON ⇒ 整趟作废（exit 1）。

    这一条判据的形状就是那次事故：预置一份"不属于框架的"文件（模拟论文主稿），
    把它当 `out_path`，然后断言 ①拒绝、②文件名点出来、③字节逐字未变、④零行落库。
    第 ③ 条不能省：只断言"返回体里有错"时，一个"先写后报错"的实现照样能过。
    """
    manuscript = Path(g_store.root) / "out" / "paper" / "main.tex"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    body = "\\documentclass{article}\n\\begin{document}\n论文正文\n\\end{document}\n"
    manuscript.write_text(body, encoding="utf-8")
    before = manuscript.read_bytes()

    with pytest.raises(DocumentError) as ei:
        g.build_document("paper", "想覆盖主稿的稿件", claims=_clean_claims(g),
                         out_path="out/paper/main.tex")
    problem = str(ei.value)
    assert "out/paper/main.tex" in problem, problem
    assert "覆盖" in problem, problem
    assert manuscript.read_bytes() == before, "被拒的那次调用改了盘上的文件 ⇒ 守卫是假的"
    assert g_store.rows("documents") == [], "被拒的调用不许留下 documents 行"

    # 正控（不许把守卫做成"什么都写不出去"）：换一个没被占用的路径照样能写。
    ok = g.build_document("paper", "另存一份", claims=_clean_claims(g),
                          out_path="documents/another.md")
    assert ok["markdown_path"] == "documents/another.md"
    assert (Path(g_store.root) / "documents" / "another.md").is_file()


def test_out_path_may_refresh_a_file_a_documents_row_owns(g: AgentG, g_store: Store):
    """边界（守卫的豁免面）：某个 `documents` 行自己登记的 `markdown_path` 允许再写。

    为什么必须有这一条：`refresh_markdown` 这条动作就是"把某行的 markdown 重渲染到它自己的
    `markdown_path`"。守卫若一票否决所有既有文件，那条路会立刻坏掉 —— 而它坏掉不会有人
    当场发现（刷新是低频动作）。所以豁免面要显式钉住：归属由 `documents` 行决定，
    不是由"文件存不存在"决定。
    """
    first = g.build_document("paper", "第一份", claims=_clean_claims(g),
                             out_path="documents/shared.md")
    assert first["markdown_path"] == "documents/shared.md"
    path = Path(g_store.root) / "documents" / "shared.md"
    assert path.is_file()

    second = g.build_document("paper", "第二份（同一落点）", claims=_clean_claims(g),
                              out_path="documents/shared.md")
    assert second["markdown_path"] == "documents/shared.md"
    assert "第二份（同一落点）" in path.read_text(encoding="utf-8")


def test_every_claim_citation_appears_in_the_rendered_markdown(g: AgentG, g_store: Store):
    """逐条断言（不是抽查）：每一条 claim 的每一个引用都出现在渲染结果里。"""
    claims = _clean_claims(g)
    claims.append(
        g.compose_claim(
            "区间端点由 companion book 给出。",
            citations=["lit:0000", "exp:0000"],
            evidence_kind="heuristic",
            section="依赖说明",
        )
    )
    doc = g.build_document("survey", "带四个断言的稿件", claims=claims)
    text = (Path(g_store.root) / doc["markdown_path"]).read_text(encoding="utf-8")
    assert len(doc["claims"]) == 4
    for c in doc["claims"]:
        assert c["text"] in text, f"{c['claim_id']} 的正文没有出现在稿件里"
        assert c["claim_id"] in text, f"{c['claim_id']} 的代号没有出现在稿件里（无法定位）"
        for cite in c["citations"]:
            assert cite in text, f"{c['claim_id']} 的引用 {cite} 丢失"


def test_schema_and_the_g_gate_both_reject_an_unsupported_claim(g: AgentG, g_store: Store):
    """负控（两层）：schema 一定拦得住，G 侧的闸门还要在写入前带上"哪一句话"。"""
    bad_claim = {
        "claim_id": "claim-1",
        "section": "s",
        "text": "这句话没有任何引用。",
        "evidence_kind": "heuristic",
        "citations": [],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
    }
    row = S.Document(doc_id="0000", kind="note", title="t", claims=[bad_claim])
    with pytest.raises(ValueError, match="citations"):
        row.validate()
    with pytest.raises(ValueError, match="citations"):
        with g_store.tx("documents", actor="test") as tx:
            tx.upsert("documents", row.to_dict())
    assert g_store.rows("documents") == [], "校验失败的事务不得留下半成品"

    # G 侧闸门：报错里必须指出是第几条/哪个代号，并带上断言原文
    with pytest.raises(ValueError) as ei:
        g.build_document("note", "t", claims=[bad_claim])
    msg = str(ei.value)
    assert "claim-1" in msg or "claims[1]" in msg
    assert "这句话没有任何引用" in msg
    assert g_store.rows("documents") == []


def test_build_document_rejects_an_out_of_workspace_out_path(g: AgentG, g_store: Store):
    """负控：`out_path` 越界必须拒绝（相对穿越与绝对路径两个方向）。"""
    claims = _clean_claims(g)
    with pytest.raises(ValueError, match="越界"):
        g.build_document("note", "t", claims=claims, out_path="../../escape.md")
    with pytest.raises(ValueError, match="越界"):
        g.build_document("note", "t", claims=claims, out_path=str(Path(g_store.root).parent / "escape.md"))
    assert not (Path(g_store.root).parent / "escape.md").exists(), "越界路径上不该真的写出文件"
    assert g_store.rows("documents") == []


# ============================================================ [3] register_dependency


def test_register_dependency_closed_against_a_real_literature_row(g: AgentG, g_store: Store):
    """正向：`closed` 指向真的存在的 lit_id / experiment_id。"""
    d1 = g.register_dependency(
        "doc:0000#claim-1",
        "theorem",
        "companion book [6, Thm 6.5]",
        source_lit_id="0000",
        page_range=(45, 46),
        quote="Spec S̃_m = [−m, m]",
        status="closed",
    )
    d2 = g.register_dependency(
        "doc:0000#claim-2",
        "experiment",
        "E 的形式化核验",
        source_experiment_id="0000",
        status="closed",
    )
    rows = {r["dep_id"]: r for r in g_store.rows("dependencies")}
    assert set(rows) == {d1["dep_id"], d2["dep_id"]}
    assert rows[d1["dep_id"]]["status"] == "closed"
    assert rows[d1["dep_id"]]["page_range"]["label"] == "pp. 45-46"
    assert rows[d2["dep_id"]]["source_experiment_id"] == "0000"


def test_register_dependency_rejects_closed_pointing_at_a_missing_source(g: AgentG, g_store: Store):
    """负控（本文件最重要的一条）：schema 只能查"字段非空"，查不出"这个来源不存在"。"""
    with pytest.raises(ValueError, match="literature"):
        g.register_dependency(
            "doc:0000#claim-1", "theorem", "不存在的文献", source_lit_id="9999", status="closed"
        )
    with pytest.raises(ValueError, match="experiments"):
        g.register_dependency(
            "doc:0000#claim-1", "experiment", "不存在的实验", source_experiment_id="9999", status="closed"
        )
    assert g_store.rows("dependencies") == [], "被拒的依赖不得留行"

    # 反证：同一个 lit_id 只要真的在库里，就能闭合 —— 说明拒绝的原因确实是"来源不存在"
    ok = g.register_dependency(
        "doc:0000#claim-1", "theorem", "存在的文献", source_lit_id="0000", status="closed"
    )
    assert ok["status"] == "closed"


def test_register_dependency_requires_reasons_for_open_statuses(g: AgentG, g_store: Store):
    """负控：`dangling` / `external_unavailable` 没有 `status_reason` 一律抛。"""
    for status in ("dangling", "external_unavailable"):
        with pytest.raises(ValueError, match="status_reason"):
            g.register_dependency("doc:0000#claim-1", "theorem", "外部前提", status=status)
    ext = g.register_dependency(
        "doc:0000#claim-1",
        "theorem",
        "companion book [6, Thm 6.5]",
        status="external_unavailable",
        status_reason="该书不在本项目可得范围内（Remark 1.6 自己这么说）",
    )
    assert ext["status"] == "external_unavailable"
    assert ext["status_reason"]
    # closed 却什么都不指：同样是"空头支票"
    with pytest.raises(ValueError, match="closed"):
        g.register_dependency("doc:0000#claim-1", "theorem", "空头支票", status="closed")


# ============================================================ [4] revise


def test_revise_bumps_round_marks_finding_fixed_and_replaces_a_claim(g: AgentG, g_store: Store):
    """正向：修订只动自己的稿 + finding 只动 status/resolution_note + 重渲染。"""
    claims = _clean_claims(g)
    doc = g.build_document("paper", "初稿", claims=claims)
    doc_id = doc["doc_id"]
    target = doc["claims"][0]["claim_id"]
    finding = add_finding(g_store, doc_id, target=target)

    replacement = g.compose_claim(
        "由形式化检查器核验：Spec K(m) = [−m, m]（修订措辞）。",
        citations=["exp:0000", "lit:0000"],
        evidence_kind="proof",
        section="主要结果",
        claim_id=target,
        proof_location=PROOF_REL,
    )
    out = g.revise(doc_id, fixed_findings=[finding["finding_id"]], new_claims=[replacement], note="按 H 意见改措辞")

    assert out["review_rounds"] == 1
    assert out["replaced_claim_ids"] == [target]
    assert out["appended_claim_ids"] == []
    row = g_store.rows("documents")[0]
    assert row["status"] == "revised" and row["review_rounds"] == 1
    assert len(row["claims"]) == len(claims), "替换语义下断言条数不变"
    assert row["claims"][0]["text"] == replacement["text"]

    f = g_store.rows("review_findings")[0]
    assert f["status"] == "fixed"
    assert "按 H 意见改措辞" in f["resolution_note"]
    # H 的判断依据一个字都不许被 G 改动
    assert f["kind"] == finding["kind"] and f["level"] == finding["level"]
    assert f["target"] == finding["target"] and f["evidence"] == finding["evidence"]
    assert f["message"] == finding["message"]
    # markdown 必须跟着更新（否则库与磁盘不一致）
    text = (Path(g_store.root) / row["markdown_path"]).read_text(encoding="utf-8")
    assert "（修订措辞）" in text


def test_revise_refuses_to_touch_a_finding_of_another_document(g: AgentG, g_store: Store):
    """负控：G 只能改自己稿件上的发现状态；跨稿改动是掩盖问题的入口。"""
    first = g.build_document("paper", "稿一", claims=_clean_claims(g))
    second = g.build_document("paper", "稿二", claims=_clean_claims(g))
    foreign = add_finding(g_store, first["doc_id"], target=first["claims"][0]["claim_id"])
    with pytest.raises(DocumentError, match="只能改自己"):
        g.revise(second["doc_id"], fixed_findings=[foreign["finding_id"]])
    # 整笔回滚：稿二既没被改，foreign 也没被标 fixed
    assert [r["status"] for r in g_store.rows("documents")].count("revised") == 0
    assert g_store.rows("review_findings")[0]["status"] == "open"


# ============================================================ [5] 工具装配


def test_doc_tools_are_registered_with_honest_side_effects(g_store: Store):
    """工具面（FC-06/FC-07）：写工具如实声明 `write_local`，且不挂给 H。"""
    build = build_registry(store=g_store, workspace_root=g_store.root)
    reg = build.registry
    # `P-14`：完整注册表默认不绑定角色 ⇒ `call` 一律被拒。本用例测的是
    # `doc.*` 的副作用声明与可用性，所以绑定写侧主人 G。
    reg.bound_role = "G"
    assert reg.get("doc.build_document").side_effect == "write_local"
    assert reg.get("doc.build_document").needs_approval is True
    assert reg.get("doc.register_dependency").side_effect == "write_local"
    assert reg.get("doc.compose_claim").side_effect == "none"
    assert reg.get("doc.list_documents").side_effect == "read"
    assert reg.get("doc.scan_claim").side_effect == "none"
    # H（审校）不许拿到写稿的手：否则"发现问题"与"掩盖问题"无法区分
    for name in ("doc.build_document", "doc.register_dependency"):
        assert "H" not in reg.get(name).roles, f"{name} 不该出现在 H 的角色面上"
    assert "G" in reg.get("doc.build_document").roles

    # 工具真的可用（不是摆设），且失败会变成结构化结果而不是抛穿
    ok_res = reg.call(
        "doc.compose_claim",
        text="数值支持该结论。",
        citations=["exp:0001"],
        evidence_kind="cross_check",
        section="s",
    )
    assert ok_res.ok and ok_res.data["disclaimer"] == DT.CROSS_CHECK_DISCLAIMER
    bad_res = reg.call(
        "doc.compose_claim", text="x", citations=[], evidence_kind="heuristic", section="s"
    )
    assert bad_res.ok is False
    # 无引用在工具边界就被拦下：`minItems: 1` 让它在进函数之前就失败（FC-04），
    # 因此 kind 是 param_error 而不是函数内的 validation_error —— 两种都是结构化失败，
    # 关键是不能"静默产出"一条无引用断言。
    assert bad_res.meta.get("kind") in ("param_error", "validation_error")
    assert "citations" in bad_res.error
    listed = reg.call("doc.list_documents")
    assert listed.ok and listed.data["count"] == 0


def test_doc_tools_fail_explicitly_when_the_store_is_not_wired():
    """FC-08：没接线必须显式失败（`not_wired`），不得静默返回空列表。"""
    reg = build_registry(store=None, workspace_root=None).registry
    reg.bound_role = "G"  # `P-14`：`doc.*` 的写侧主人是 G（见上一条用例的注释）
    res = reg.call("doc.list_documents")
    assert res.ok is False
    assert res.meta.get("kind") == "not_wired"
    assert "没查" in res.error
    res2 = reg.call("doc.build_document", kind="note", title="t", claims=[{"claim_id": "c", "text": "x"}])
    assert res2.ok is False and res2.meta.get("kind") == "not_wired"


def test_agent_g_selftest_passes(g: AgentG):
    """`AgentG.selftest()` 就地冒烟：构造 → 渲染 → 内容核对。"""
    assert g.selftest() == 0
    assert g.logs, "自检必须留下它做了什么（否则「跑过了」无法被复核）"


def test_render_marks_dependencies_as_unchecked_when_none_is_passed(g: AgentG):
    """三态：`dependencies=None` 表示没查，渲染里不得写成"0 条 = 都闭合"。"""
    claims = _clean_claims(g)
    doc = g.build_document("note", "t", claims=claims)
    text_none = g.render(doc, dependencies=None)
    assert "未提供（没查）" in text_none
    assert "不等于" in text_none
    text_read = g.render(doc)  # 不传 = 自己去库里读
    assert "0 条" in text_read
    assert "未提供" not in text_read.split("## 4")[1]


def test_g_and_h_output_passes_the_global_verify(g: AgentG, g_store: Store):
    """接线检查（N11：单元测试全绿不等于零件被接上）：G/H 的产出必须过 `verify` 的跨表检查。

    `verify` 是另一路交付的模块，它自己会重算：引用是否指向真实存在的关系/文献/实验
    （`dangling_citation`）、closed 依赖是否真的闭合、发现是否带证据、稿件是不是
    在还有未处置 error 的情况下被标成 accepted。G 侧的引用格式与 H 的状态口径
    必须与它对得上 —— 对不上就是一个没有任何报错的静默分裂。
    """
    from agentflow.agent_h import AgentH
    from agentflow.verify import verify_all

    doc = g.build_document("paper", "可被 verify 检查的稿件", claims=_clean_claims(g))
    g.register_dependency(
        f"doc:{doc['doc_id']}#claim-1",
        "theorem",
        "companion book [6, Thm 6.5]",
        source_lit_id="0000",
        page_range=(45, 46),
        status="closed",
    )
    assert AgentH(g_store).review(doc["doc_id"])["verdict"] == "accepted"
    errors = [(i.code, i.table, i.row_id, i.message[:70]) for i in verify_all(g_store).errors]
    assert errors == [], f"verify 在 G/H 的产出上报了 error：{errors}"
