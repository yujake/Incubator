"""`D-1` 的回归判据：`evidence_kind="proof"` 必须有可复核的形式化证据锚。

## 缺陷（2026-09-26 全面体检 · 子代理 D 发现）

`citations` 有存在性判据（`doc_tools.check_citations`），而
`evidence_kind="proof"` 一条判据都没有：`temp/auditD-proof-selfreport.txt` 里
`proof_location="PROOF-DOES-NOT-EXIST.lean:1"` 照样写库 + 渲染，15 道门对这份稿件
G3/G1/G4 全 `pass`（`gate_g3` 只对 `proof_location` 做正则形态检查，不读盘）。

修法前的可达性探针（`temp/r2-d1-probe.txt`）确认四种形态全部写库成功：

  ① `proof_location` 指向一个不存在的文件；
  ② 连 `proof_location` 都不给；
  ③ 只引 `lit:`（一条 `exp:` 都没有 ⇒ 没有任何检查器参与过）；
  ④ 引一条 `cross_check` 的数值实验却声称 proof。

## 本文件守什么

四条判据各一组正控/负控，全部打在 `doc_tools.check_proofs` 与
`build_document` 的真实写入路径上（不是拿假表调函数）：

- 负控：① ② ③ ④ 必须整笔不写库（`documents` 表仍然为空），且报错里点名是哪一条断言；
- 正控：证据锚齐备的 proof 断言必须照旧写进去（别把判据做成"proof 永远写不进去"）；
- 边界：`cross_check` / `heuristic` 断言不受这套判据约束（它们没有 proof 级的义务）。

## 一条明确的边界（写给下一个人）

`check_proofs` 证明的是"文件在盘上"，不证明"文件里有那条证明" ——
后者是 `formalgw` 与形式化检查器的事。两者的区别被写进了那条判据自己的 docstring，
本文件不试图把它折叠掉。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_g import AgentG, DocumentError
from agentflow.store import Store
from agentflow.tools import doc_tools as DT

from conftest import add_literature

TS = "2026-01-01T00:00:00+00:00"
PROOF_REL = "proofs/real.lean"


def _add_experiment(st: Store, exp_id: str, *, method: str, kind: str,
                    verifier_output: str = "", subject: str = "") -> None:
    row = S.Experiment(
        experiment_id=exp_id,
        claim=f"命题 {exp_id}",
        claim_key=f"key-{exp_id}",
        method=method,
        evidence_kind=kind,
        result="supports",
        negation_kind="not_proved",
        verifier_output=verifier_output,
        verifier_subject_key=subject or (f"key-{exp_id}" if kind == "proof" else ""),
        created_at=TS,
    )
    with st.tx("experiments", actor="test", note="D-1 夹具") as tx:
        tx.upsert("experiments", row.to_dict())


@pytest.fixture
def ws(tmp_path: Path) -> Store:
    """一份最小自洽工作区：1 篇文献 + 1 条 formal/proof 实验 + 1 条 numeric 实验 + 一个真文件。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="Companion book", processed=True, sync=False)
    # `R2-AN-2` 的夹具处置：从前这条 proof 行的 `verifier_output` 是
    # `"Lean4: no goals"` —— 输出里没有绑定被检查声明名的诊断，行却标着 `proof`，
    # 那是夹具在说假话（本文件不跑 `verify_all`，所以变严的审计判据没有红它，
    # 但假话本身就是缺陷，`draft/28` §41.4：改夹具，不许放宽判据）。
    # 本夹具的 `claim_key` 是仓库风格的键（`key-0000`）而不是 Lean 标识符，
    # 且它没有 `notes`（没有"声明名"那一段）⇒ 审计会退回 `verifier_subject_key`，
    # 所以这里就按那个名字写成检查器真跑过时的绑名形态。
    _add_experiment(st, "0000", method="formal", kind="proof",
                    verifier_output="'key-0000' does not depend on any axioms")
    _add_experiment(st, "0001", method="numeric", kind="cross_check")
    proof_file = st.root / PROOF_REL
    proof_file.parent.mkdir(parents=True, exist_ok=True)
    proof_file.write_text("theorem real : True := trivial\n", encoding="utf-8")
    return st


@pytest.fixture
def g(ws: Store) -> AgentG:
    return AgentG(ws, config={"docs_subdir": "documents"})


def _proof_claim(g: AgentG, **kw):
    base = dict(
        text="由形式化检查器核验：P。",
        citations=["exp:0000", "lit:0000"],
        evidence_kind="proof",
        section="主要结果",
        proof_location=PROOF_REL,
    )
    base.update(kw)
    return g.compose_claim(**base)


# ============================================================ 负控：四种坏形态


def test_a_proof_claim_with_a_missing_proof_location_file_is_rejected(g: AgentG, ws: Store):
    """负控 ①：`proof_location` 指向不存在的文件 ⇒ 整笔不写库。

    这条正是审计者 D 的原始复现（`PROOF-DOES-NOT-EXIST.lean:1`）。
    """
    claim = _proof_claim(g, proof_location="PROOF-DOES-NOT-EXIST.lean:1")
    with pytest.raises(DocumentError) as ei:
        g.build_document("paper", "t", claims=[claim])
    msg = str(ei.value)
    assert "proof_location" in msg and "找不到" in msg, msg
    assert ws.rows("documents") == [], "被拒的稿件不得留下半成品"


def test_a_proof_claim_without_any_proof_location_is_rejected(g: AgentG, ws: Store):
    """负控 ②：连 `proof_location` 都不给 ⇒ 拒绝（读者没有任何可打开的落点）。"""
    claim = _proof_claim(g, proof_location=None)
    assert "proof_location" not in claim, "夹具前提：不给就不写这个键（三态）"
    with pytest.raises(DocumentError) as ei:
        g.build_document("paper", "t", claims=[claim])
    assert "没有 `proof_location`" in str(ei.value), str(ei.value)
    assert ws.rows("documents") == []


def test_a_proof_claim_citing_only_literature_is_rejected(g: AgentG, ws: Store):
    """负控 ③：只引 `lit:`（一条 `exp:` 都没有）⇒ 拒绝。

    这一档事后也查不出来：`verify.proof_claim_rests_on_weaker_evidence` 只在
    真的引了 `exp:` 时才比对等级。所以写入期这道闸是它唯一的判据。
    """
    claim = _proof_claim(g, citations=["lit:0000"])
    with pytest.raises(DocumentError) as ei:
        g.build_document("paper", "t", claims=[claim])
    assert "一条 `exp:` 引用都没有" in str(ei.value), str(ei.value)
    assert ws.rows("documents") == []


def test_a_proof_claim_resting_on_a_cross_check_experiment_is_rejected(g: AgentG, ws: Store):
    """负控 ④：引一条 `cross_check` 实验却声称 proof ⇒ 拒绝（断言不能强于它的依据）。"""
    claim = _proof_claim(g, citations=["exp:0001"])
    with pytest.raises(DocumentError) as ei:
        g.build_document("paper", "t", claims=[claim])
    assert "不能强于它的依据" in str(ei.value), str(ei.value)
    assert ws.rows("documents") == []


# ============================================================ 正控与边界


def test_a_proof_claim_with_a_real_anchor_is_still_written(g: AgentG, ws: Store):
    """正控：证据锚齐备 ⇒ 照旧写库（别把判据做成"proof 永远进不去"）。"""
    doc = g.build_document("paper", "t", claims=[_proof_claim(g)])
    assert doc["doc_id"] == "0000"
    assert (ws.root / doc["markdown_path"]).is_file()
    assert len(ws.rows("documents")) == 1
    # proof_location 必须渲染进 markdown —— 否则读者在稿件里看不到那个落点
    text = (ws.root / doc["markdown_path"]).read_text(encoding="utf-8")
    assert PROOF_REL in text, "proof_location 没有出现在渲染结果里"


def test_cross_check_and_heuristic_claims_are_not_subject_to_the_proof_gate(g: AgentG, ws: Store):
    """边界：`cross_check` / `heuristic` 不受这套判据约束（它们没有 proof 级的义务）。

    否则这套判据会顺手把所有稿件都拦下来 —— 那比原缺陷更糟。
    """
    cross = g.compose_claim("数值抽样支持 P。", citations=["exp:0001"],
                            evidence_kind="cross_check", section="数值证据")
    heur = g.compose_claim("本项目未能证明 P。", citations=["lit:0000"],
                           evidence_kind="heuristic", section="开放问题",
                           is_negative=True, negation_kind="not_proved")
    doc = g.build_document("paper", "t", claims=[cross, heur])
    assert len(doc["claims"]) == 2


def test_check_proofs_reports_three_states(tmp_path: Path, ws: Store):
    """判据本身的三态：`rows_of is None` ⇒ `checked=False`（没查成），不是"证据都齐"。"""
    out = DT.check_proofs(None, [])
    assert out["checked"] is False
    assert "没查" in out["reason"]
    assert out["problems"] == []


def test_check_proofs_separates_kinds_of_problems(ws: Store):
    """逐条判据的问题种类必须可分辨（读报告的人要知道该怎么修）。"""
    claims = [
        {"claim_id": "c1", "evidence_kind": "proof", "citations": ["lit:0000"],
         "proof_location": "proofs/real.lean"},
        {"claim_id": "c2", "evidence_kind": "proof", "citations": ["exp:0001"],
         "proof_location": "proofs/real.lean"},
    ]
    out = DT.check_proofs(ws.rows, claims, workspace_root=ws.root)
    assert out["checked"] is True
    kinds = {p["claim_id"]: p["kind"] for p in out["problems"]}
    assert kinds == {"c1": "proof_claim_without_formal_experiment",
                     "c2": "proof_claim_rests_on_weaker_evidence"}, kinds


# ============================================================ 改写那条路也必须过闸


def test_revise_cannot_smuggle_in_an_unanchored_proof_claim(g: AgentG, ws: Store):
    """负控 ⑤：`revise` 不许把一条没有证据锚的 proof 断言换进已合规的稿件。

    这条是本轮修 `D-1` 时顺手发现的绕过：`build_document` 上了闸，
    而 `revise` 走 `documents` 表的 `tx.upsert`，不经过 `check_proofs`。
    实测（`temp/r2-revise-bypass.txt`）改之前 `revise` 成功，
    库里出现一条 `evidence_kind='proof'`、`citations=['lit:0000']`、
    `proof_location=None` 的断言 —— 而 `agent_g.revise` 的 docstring 里
    已经写着"两条路复用同一个 `DT.check_citations`，不另写第二份判据"，
    所以这道闸的缺失与那条 docstring 是同一处遗漏。
    """
    doc = g.build_document("paper", "初稿", claims=[_proof_claim(g)])
    doc_id = doc["doc_id"]

    bad = g.compose_claim("（改写换进来的）由形式化检查器核验 P —— 但没有任何落点。",
                          citations=["lit:0000"], evidence_kind="proof",
                          section="主要结果", claim_id="claim-1")
    with pytest.raises(DocumentError) as ei:
        g.revise(doc_id, new_claims=[bad], note="探针：绕过 D-1")
    assert "proof" in str(ei.value) and "不成立" in str(ei.value), str(ei.value)

    # 整笔回滚：稿件仍是原来那条合规断言，review_rounds 没动
    row = ws.rows("documents")[0]
    assert row["review_rounds"] == 0, "被拒的修订不许把 review_rounds 推进"
    assert row["claims"][0]["citations"] == ["exp:0000", "lit:0000"]
    assert row["claims"][0]["proof_location"] == PROOF_REL


def test_revise_accepts_a_proof_claim_that_keeps_its_anchor(g: AgentG, ws: Store):
    """正控：带着证据锚改写的 proof 断言照旧能过（别把 `revise` 做成永远拒绝 proof）。"""
    doc = g.build_document("paper", "初稿", claims=[_proof_claim(g)])
    # 替换语义靠 `claim_id` 相等：`compose_claim` 不给 id 时按正文派生一个稳定代号，
    # 所以"改措辞"必然派生出另一个 id ⇒ 会被当成追加。这里显式沿用原来的 id。
    original_id = doc["claims"][0]["claim_id"]
    ok = _proof_claim(g, text="由形式化检查器核验：P（改后措辞）。", claim_id=original_id)
    out = g.revise(doc["doc_id"], new_claims=[ok], note="改措辞")
    assert out["review_rounds"] == 1
    assert out["replaced_claim_ids"] == [original_id], out
    assert ws.rows("documents")[0]["claims"][0]["text"].endswith("（改后措辞）。")
