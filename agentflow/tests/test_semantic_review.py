"""§196：把三条"缺的路"接上，以及它们的判据。

用户口径：只发一次 ≤150 字的任务让系统核验论文里定理与引理的证明，产出更优质的论文包。
§195 的四次尝试证明卡点不是"模型不聪明"，而是动作面缺三条路：

1. 没人写核验脚本 ⇒ 复查后确认 `E` 的工具面里已有 `fs.write`（缺的是"
   脚本不存在就先写一个"这条指令，以及把 `E.run_experiment` 交给模型驱动）；
2. H 的审校作用不到论文包上 ⇒ `conductor.acceptance` 现在把验收表背后的
   `documents` 行一并给出来（此前主控只能从表标题里猜一个 `draft/31`，一猜就错）；
3. 语义判据没接进 H（`claims_semantically_judged` 恒 0）⇒ 接缝本来就在
   （`scan_document(semantic_judge=…)` + 三态），把 `judges.semantic_judge_for(seam)`
   接到了 `review_tools.register` / `AgentH(llm=…)` / `wired_llm_conductor(semantic_review=True)`。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import judges as JG
from agentflow import schema as S
from agentflow.agent_h import AgentH
from agentflow.host import wired_llm_conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools import review_tools as RV
from agentflow.tools.base import ToolRegistry
from agentflow.tools.conductor_tools import reset_cache


class _Model:
    """替身模型：按剧本回一条判定 JSON。"""

    spec = type("S", (), {"model": "fake"})()

    def __init__(self, verdict: str = "within_evidence", why: str = "措辞没有超出证据") -> None:
        self.verdict = verdict
        self.why = why
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """返回一段合规的判定 JSON。"""
        self.prompts.append(prompt)
        return type("R", (), {"ok": True, "tokens_in": 3, "tokens_out": 3, "error_detail": "",
                              "error_kind": "",
                              "text": json.dumps({"verdict": self.verdict, "why": self.why,
                                                  "findings": []}, ensure_ascii=False)})()


def _seam(root: pathlib.Path, model: Any) -> LlmSeam:
    return LlmSeam(role="H", session_root=root, gateway=model, price=(0.0, 0.0), sid="t")


def _doc(store: Store, claims: list[dict]) -> str:
    """放一份带断言的稿件，返回 doc_id。"""
    with store.tx("documents", "counters", actor="test") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="P2 断言台账", status="draft", claims=claims,
            markdown_path=None, created_at=S.now_iso(), created_by="test").to_dict())
    return "0000"


def _claim(cid: str, text: str, level: str = "cross_check") -> dict:
    return {"claim_id": cid, "text": text, "evidence_kind": level,
            "citations": ["lit:0001"], "section": "§1",
            "disclaimer": "" if level == "proof" else "数值交叉验证，不构成证明"}


# ============================================================ 适配器：两套词表，一个方向


def test_the_adapter_maps_the_criterion_vocabulary_onto_the_review_seam(tmp_path: pathlib.Path):
    """判据（词表映射）：`within_evidence`→`consistent`、`overclaimed`→`stronger_than_evidence`、
    判不了/没判成→`unknown`。两套词表各自对着自己的消费者，不合并 —— 这里只做单向映射。"""
    root = tmp_path / "ws"
    for verdict, want in (("within_evidence", "consistent"),
                          ("overclaimed", "stronger_than_evidence"),
                          ("unjudgeable", "unknown")):
        seam = _seam(root, _Model(verdict))
        got = JG.semantic_judge_for(seam)(_claim("C1", "x"), {"title": "T"})
        assert got["verdict"] == want, (verdict, got)


def test_the_adapter_says_not_checked_when_the_seam_is_unwired(tmp_path: pathlib.Path):
    """负控（三态）：模型没接线 ⇒ `unknown` + 逐字理由，绝不是 `consistent`。"""
    got = JG.semantic_judge_for(_seam(tmp_path / "ws", None))(_claim("C1", "x"), {})
    assert got["verdict"] == "unknown" and "judge_not_wired" in got["reason"], got


# ============================================================ 接进审校（H 那一侧）


def test_review_document_counts_semantically_judged_claims_when_wired(store: Store,
                                                                     tmp_path: pathlib.Path):
    """正控：接了判据之后 `coverage.claims_semantically_judged` 才是真读数（此前恒 0）。"""
    doc_id = _doc(store, [_claim("C1", "数值上与公式一致"), _claim("C2", "反例搜索未找到反例")])
    judge = JG.semantic_judge_for(_seam(tmp_path / "ws", _Model("within_evidence")))
    got = RV.review_document(store, doc_id, semantic_judge=judge)
    cov = got["coverage"]
    assert cov["claims_semantically_judged"] == 2, cov
    assert cov["claims_total"] == 2, cov


def test_review_document_reports_the_dimension_as_not_checked_without_a_judge(store: Store):
    """负控（三态）：不接判据 ⇒ 那一格是 0 且理由写明"没查"，不是"判过、没问题"。"""
    doc_id = _doc(store, [_claim("C1", "数值上与公式一致")])
    got = RV.review_document(store, doc_id)
    assert got["coverage"]["claims_semantically_judged"] == 0, got["coverage"]
    sc = got["semantic_check"]
    assert sc["checked"] is False, sc
    assert sc["claims_judged"] == 0, sc
    # 理由必须写明"没查"（以及怎么接），不能留白让读者误读成"判过、没问题"。
    assert "没接线" in sc["reason"], sc
    assert "没查" in sc["reason"], sc


def test_an_overclaim_lands_as_a_finding(store: Store, tmp_path: pathlib.Path):
    """正控（要抓的形态）：模型说这条断言强于证据 ⇒ 落一条 finding（不是悄悄通过）。"""
    doc_id = _doc(store, [_claim("C1", "我们证明了该结论")])
    judge = JG.semantic_judge_for(_seam(tmp_path / "ws", _Model("overclaimed", "把交叉验证说成证明")))
    got = RV.review_document(store, doc_id, semantic_judge=judge)
    assert got["coverage"]["claims_semantically_judged"] == 1, got["coverage"]
    rows = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    assert rows, "语义判据说它强于证据，却没有落任何发现"


def test_the_tool_layer_passes_the_judge_through(store: Store, tmp_path: pathlib.Path):
    """判据（接线到底）：`review_tools.register(semantic_judge=…)` 之后，
    经工具层调的 `review.review_document` 也带着判据（不是只有直接调用才带）。"""
    doc_id = _doc(store, [_claim("C1", "数值上与公式一致")])
    reg = ToolRegistry(name="h-writers")
    reg.bound_role = "H"
    RV.register(reg, store=store, include_writers=True, actor="agent-H",
                semantic_judge=JG.semantic_judge_for(_seam(tmp_path / "ws", _Model())))
    res = reg.call("review.review_document", doc_id=doc_id)
    assert res.ok, (res.error, res.meta)
    assert res.data["coverage"]["claims_semantically_judged"] == 1, res.data["coverage"]


def test_agent_h_uses_its_llm_socket_as_the_semantic_judge(store: Store, tmp_path: pathlib.Path):
    """正控（插座接上）：`AgentH(llm=…)` 时它的审校带上语义判据；`llm=None` 时不带。"""
    doc_id = _doc(store, [_claim("C1", "数值上与公式一致")])
    wired = AgentH(store, llm=_seam(tmp_path / "ws", _Model()))
    got = wired.review(doc_id)
    assert got["coverage"]["claims_semantically_judged"] == 1, got["coverage"]
    plain = AgentH(store)
    got2 = plain.review(doc_id)
    assert got2["coverage"]["claims_semantically_judged"] == 0, got2["coverage"]


def test_the_product_switch_defaults_off_and_is_explicit(tmp_path: pathlib.Path):
    """判据（默认不改变确定性行为）：`semantic_review` 默认 False；True 时 H 拿到模型缝。

    读法是实例上的：`build_role_registry(..., llm=…)` 把缝交给 `AgentH`，
    所以直接建 H 的实例看 `llm` 是不是 None。
    """
    from agentflow.host import build_role_registry

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    off = build_role_registry(st, llm=None)
    h_off = off["H"][1](store=st)
    assert h_off.llm is None, "默认路径不许有模型缝"
    seam = _seam(ws, _Model())
    on = build_role_registry(st, llm=seam)
    h_on = on["H"][1](store=st)
    assert h_on.llm is seam, "给了缝却没交给 H"


def test_the_cli_flag_exists_and_parses():
    """判据（产品路径）：`run-agent --semantic-review` 是可解析的开关。"""
    from agentflow.cli import build_parser

    args = build_parser().parse_args(["run-agent", "M", "--task", "x", "--semantic-review"])
    assert getattr(args, "semantic_review", False) is True
    args2 = build_parser().parse_args(["run-agent", "M", "--task", "x"])
    assert getattr(args2, "semantic_review", False) is False


# ============================================================ 第 2 条：验收表背后的 documents 行


def test_acceptance_reports_the_backing_document_rows(store: Store, tmp_path: pathlib.Path):
    """判据（§196 第 2 条）：验收表 + 它背后的 `documents` 行一起给出来。

    实测背景：M 拿表标题里的 `draft/31` 当 doc_id 去派 H，H 回"不在 documents 表" ⇒
    核验链在第一跳就断。表和行都在库里，工具就该一起给，而不是让主控猜号。
    """
    out = store.root / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ACCEPTANCE.md").write_text(
        "# 最终验收：P1–P11 逐条读数\n\n结论：**全部成立**（1/1）\n\n"
        "| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n| P1 | 真实检索 | 成立 | 38 条 |\n",
        encoding="utf-8")
    _doc(store, [_claim("C1", "数值上与公式一致")])
    reg = ToolRegistry(name="m")
    reg.bound_role = "M"
    CT.register(reg, store=store)
    res = reg.call("conductor.acceptance")
    assert res.ok, (res.error, res.meta)
    data = res.data
    assert data["row_count"] == 1, data
    assert [d["doc_id"] for d in data["documents"]] == ["0000"], data["documents"]
    assert data["documents"][0]["claims"] == 1, data["documents"]


# ============================================================ R-04：复审那一半（`draft/44` / D 族）

def test_the_tool_layer_passes_the_judge_through_verify_fixes(
        store: Store, tmp_path: pathlib.Path):
    """R-04-a：`review.verify_fixes` 也要拿到语义判据（此前那一格恒 0）。

    改前必红：`_review_verify_fixes_tool` 的注入元组只有三名
    (`_not_wired`,`store`,`actor`)，`verify_fixes` 的复扫走
    `scan_document(doc, dependencies=deps)` —— 不带判据 ⇒ 上一轮由语义判据
    产生的 `overclaim` 在这一轮结构上不可能复现 ⇒ 必然落进 `resolved` ⇒ 写成
    `status="fixed"`（真机 `p8d` 的 claim-3/claim-4 就是这样被"修好"的）。

    `semantic_judge` 不进模型参数表（`@tool` 的 properties /
    `additionalProperties: False` 一个字不改）：它只由装配期 `partial` 绑定。
    """
    doc_id = _doc(store, [_claim("C1", "数值上与公式一致")])
    reg = ToolRegistry(name="h-writers")
    reg.bound_role = "H"
    RV.register(reg, store=store, include_writers=True, actor="agent-H",
                semantic_judge=JG.semantic_judge_for(_seam(tmp_path / "ws", _Model())))
    res = reg.call("review.verify_fixes", doc_id=doc_id, round_no=2)
    assert res.ok, (res.error, res.meta)
    assert res.data["semantic_check"]["claims_judged"] == 1, res.data["semantic_check"]
    # 工具参数表里仍然没有 semantic_judge（装配期注入，不进模型面）
    import inspect

    params = inspect.signature(RV._review_verify_fixes_tool).parameters
    assert "semantic_judge" in params, list(params)
    assert params["semantic_judge"].default is None, params["semantic_judge"]


def test_verify_fixes_does_not_call_a_semantic_finding_fixed_without_rerunning_it(
        store: Store, tmp_path: pathlib.Path):
    """R-04-b（三态兜底）：没重跑语义判据 ⇒ 语义那一支留在 open，verdict 不是 accepted。

    改前必红：不接判据时 `resolved` 里那些语义发现被无条件写成 `fixed`
    —— "没查"被读成"修好了"，而那正是最贵的方向。
    """
    doc_id = _doc(store, [_claim("C1", "我们证明了该结论")])
    judge = JG.semantic_judge_for(_seam(tmp_path / "ws", _Model("overclaimed", "把交叉验证说成证明")))
    first = RV.review_document(store, doc_id, semantic_judge=judge)
    assert first["coverage"]["claims_semantically_judged"] == 1, first["coverage"]
    rows = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    sem = [r for r in rows if str(r.get("kind")) == "overclaim"
           and str(r.get("evidence") or "").startswith("语义判据（")]
    assert sem, [(r.get("kind"), str(r.get("evidence"))[:40]) for r in rows]
    # 把它们标成 fixed（模拟"上一轮自述修好了"）
    for r in sem:
        RV._apply_finding_status(store, [{"finding_id": r["finding_id"], "status": "fixed",
                                          "resolution_note": "自述"}], actor="agent-H",
                                 note="test")

    # 这一轮不接判据复审（"没查"那一档）
    got = RV.verify_fixes(store, doc_id, round_no=2)
    assert got["verdict"] != "accepted", got
    assert got["not_rechecked"], got
    item = got["not_rechecked"][0]
    assert item["source"] == "not_rechecked", item
    assert "未重跑语义判据" in item["note"], item
    assert "未重跑判据" in got["reason"] or "没查" in got["reason"], got["reason"]
    now = [dict(r) for r in store.rows("review_findings")
           if str(r.get("finding_id")) == sem[0]["finding_id"]]
    assert now and str(now[0].get("status")) == "open", now

    # 接上判据、且它不再报"强于证据" ⇒ 这时才允许落 fixed
    clean = JG.semantic_judge_for(_seam(tmp_path / "ws", _Model("within_evidence")))
    got2 = RV.verify_fixes(store, doc_id, round_no=3, semantic_judge=clean)
    assert not got2["not_rechecked"], got2["not_rechecked"]
    now2 = [dict(r) for r in store.rows("review_findings")
            if str(r.get("finding_id")) == sem[0]["finding_id"]]
    assert now2 and str(now2[0].get("status")) == "fixed", now2


def test_verify_fixes_still_marks_a_non_semantic_finding_fixed_when_fixed(
        store: Store, tmp_path: pathlib.Path):
    """反真空（R-04-b 不许扩大化）：机械那一支的发现照旧按现口径判 `fixed`。

    没有这条，"语义那一支不许判 fixed"会退化成"什么都不敢判 fixed"。
    """
    doc_id = _doc(store, [{"claim_id": "C1", "text": "我们证明了该结论",
                           "evidence_kind": "cross_check", "citations": ["lit:0001"],
                           "section": "§1", "disclaimer": "数值交叉验证，不构成证明"}])
    first = RV.review_document(store, doc_id)
    rows = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    # 机械那一支（措辞级 `overclaim`）：`evidence` 不是"语义判据（…" 那种形态
    mech = [r for r in rows if str(r.get("kind")) == "overclaim"
            and not str(r.get("evidence") or "").startswith("语义判据（")]
    assert mech, [(r.get("kind"), str(r.get("evidence"))[:40]) for r in rows]
    for r in mech:
        RV._apply_finding_status(store, [{"finding_id": r["finding_id"], "status": "fixed",
                                          "resolution_note": "自述"}], actor="agent-H",
                                 note="test")
    # 把措辞改干净（机械判据不再复现）⇒ 应判 fixed（R-04-b 只针对语义那一支）
    doc = dict([r for r in store.rows("documents")][0])
    doc["claims"] = [_claim("C1", "数值上与公式一致")]
    with store.tx("documents", actor="agent-H") as tx:
        tx.upsert("documents", doc)
    got = RV.verify_fixes(store, doc_id, round_no=2)
    assert not got["not_rechecked"], got["not_rechecked"]
    now = [dict(r) for r in store.rows("review_findings")
           if str(r.get("finding_id")) == mech[0]["finding_id"]]
    assert now and str(now[0].get("status")) == "fixed", now
