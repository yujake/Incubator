# -*- coding: utf-8 -*-
"""引文回验的两档（业主 2026-10-14）：「回验不应该是十分呆板的逐字验证，
而是保持语义相同即可」；落点是 **B 唤起 H**。

这一组守三件事：

1. **两栏的分工**：`quote_verified` 是三态结论，`quote_mode` 是**通过的方式**
   （`verbatim` 逐字命中 / `semantic` 语义相同）。两栏互相冒充的行不许拿到学分。
2. **历史行不许被追溯性降级**：`quote_mode` 这一栏是今天才有的，在那之前
   `quote_verified=True` 只可能来自 `quoteverify.check_quote`（逐字那一档）⇒
   空方式按 `verbatim` 读（判据 `test_a_legacy_external_lit_row_keeps_its_citation_credit`
   也钉着这条）。
3. **语义档不许被逐字档顶替**：H 判的"语义相同"与"结论强于引文"是两件事，
   后者仍必须落 `mismatch`（判据见 `quote_state` 的表）。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S


# ============================================================ 1 四态表
@pytest.mark.parametrize("row, want", [
    # 还没查
    ({"quote_verified": None}, "unchecked"),
    ({}, "unchecked"),
    # 查过了、不一致（语义档也救不了它：H 的判据是"说同一件事"）
    ({"quote_verified": False}, "mismatch"),
    ({"quote_verified": False, "quote_mode": "semantic"}, "mismatch"),
    # 通过的两档
    ({"quote_verified": True, "quote_mode": "verbatim"}, "verbatim"),
    ({"quote_verified": True, "quote_mode": "semantic"}, "semantic"),
    # 历史行：方式那一栏还没有的时代，True 只可能来自逐字那一档
    ({"quote_verified": True}, "verbatim"),
    ({"quote_verified": True, "quote_mode": ""}, "verbatim"),
    # 说不出方式的通过 ⇒ 按没查算（词表外的值就是"说不清"）
    ({"quote_verified": True, "quote_mode": "fuzzy"}, "unchecked"),
    ({"quote_verified": True, "quote_mode": "看起来一样"}, "unchecked"),
])
def test_the_quote_state_table(row: dict, want: str) -> None:
    """四态表（唯一读口径）：`unchecked` / `mismatch` / `verbatim` / `semantic`。"""
    assert EB.quote_state(row) == want, row
    assert EB.quote_explains_itself(row) == (want in S.QUOTE_MODES), row


# ============================================================ 2 写侧归一
def _stmt(**kw) -> S.Statement:
    base = dict(stmt_id="0001", origin="external_lit", statement_full="若 A 则 B",
                source_lit_id="0000", quote_reason="核对过")
    base.update(kw)
    return S.Statement(**base)


def test_a_bare_true_is_recorded_as_verbatim_not_left_empty() -> None:
    """只说了"通过"、没说方式的行**记实成 verbatim**（历史事实），不许留白。"""
    row = _stmt(quote_verified=True)
    row.validate()
    assert row.quote_mode == "verbatim", row.to_dict()
    assert row.to_dict()["quote_mode"] == "verbatim"


def test_the_semantic_verdict_is_kept_verbatim() -> None:
    """H 判的语义档原样留着 —— 不许被逐字档"顺手改写成" verbatim。"""
    row = _stmt(quote_verified=True, quote_mode="semantic",
                quote_span="来源里那一段逐字正文", quote_call_sha256="c0ffee")
    row.validate()
    assert row.quote_mode == "semantic", row.to_dict()
    assert row.quote_span and row.quote_call_sha256, row.to_dict()


def test_a_mode_outside_the_vocabulary_is_refused() -> None:
    """词表外的值直接拒（两栏不许互相冒充这条靠它兜住）。"""
    with pytest.raises(ValueError) as got:
        _stmt(quote_verified=True, quote_mode="fuzzy").validate()
    assert "quote_mode" in str(got.value) and "verbatim" in str(got.value)


def test_a_row_that_did_not_pass_has_no_mode() -> None:
    """没通过/还没查的行，方式归空串 —— 留着会让人读成"用某种方式查过了"。"""
    for kw in ({"quote_verified": False, "quote_mode": "verbatim"},
               {"quote_verified": None, "quote_mode": "semantic"}):
        row = _stmt(**kw)
        row.validate()
        assert row.quote_mode == "", (kw, row.to_dict())


def test_the_relation_carries_the_same_two_columns() -> None:
    """关系行与命题行走同一对口径（引文挂在关系行上，那一栏才是主战场）。"""
    rel = S.Relation(relation_id="0001", concept_ids=["0001", "0002"],
                     description="d", lit_id="0000",
                     page_range=S.PageRange(1, 2, "p.1-2"),
                     quote_verified=True, quote_mode="semantic",
                     quote_span="来源里那一段逐字正文", quote_call_sha256="c0ffee")
    rel.validate()
    assert rel.quote_mode == "semantic"
    assert rel.to_dict()["quote_mode"] == "semantic"
    with pytest.raises(ValueError):
        S.Relation(relation_id="0002", concept_ids=["0001", "0002"], description="d",
                   lit_id="0000", page_range=S.PageRange(1, 2, "p.1-2"),
                   quote_verified=True, quote_mode="maybe").validate()


def test_the_semantic_mode_demands_its_evidence() -> None:
    """业主 2026-10-14：「语义那一档**必须留证据**」—— 缺证据的 semantic 当场拒。

    两样缺一不可：对着哪一段原文（`quote_span`）、哪一次判的（`quote_call_sha256`）。
    这一条是"两栏不许互相冒充"在**内容**上的那一半：不是写个 `semantic` 就算过。
    """
    with pytest.raises(ValueError) as got:
        _stmt(quote_verified=True, quote_mode="semantic").validate()
    assert "quote_span" in str(got.value) and "quote_call_sha256" in str(got.value), got.value
    with pytest.raises(ValueError):
        _stmt(quote_verified=True, quote_mode="semantic",
              quote_span="有片段，但没有调用记录").validate()
    with pytest.raises(ValueError):
        S.Relation(relation_id="0003", concept_ids=["0001", "0002"], description="d",
                   lit_id="0000", page_range=S.PageRange(1, 2, "p.1-2"),
                   quote_verified=True, quote_mode="semantic").validate()
    # 逐字那一档不需要这两栏（它自己那一份证据是"逐字命中"，由 check_quote 给）
    plain = _stmt(quote_verified=True)
    plain.validate()
    assert plain.quote_mode == "verbatim" and plain.quote_span == "", plain.to_dict()


# ============================================================ 3 学分
def test_the_citation_credit_needs_a_usable_mode() -> None:
    """引用命题的学分：两档都给（逐字 / 语义），说不清方式的不给。"""
    ok_v = {"stmt_id": "0001", "origin": "external_lit", "source_lit_id": "0001",
            "quote_verified": True, "quote_mode": "verbatim", "status": "active"}
    ok_s = {**ok_v, "stmt_id": "0002", "quote_mode": "semantic"}
    bad = {**ok_v, "stmt_id": "0003", "quote_mode": "fuzzy"}
    assert EB.bits_from_row(ok_v)["grade"] == EB.bits_from_row(ok_s)["grade"] != "conjecture"
    assert EB.bits_from_row(bad)["grade"] == "conjecture", EB.bits_from_row(bad)


def test_the_credit_reason_says_which_mode_it_was() -> None:
    """理由那一栏要把两档说开（读的人不该去猜"核过"是哪种核过）。"""
    rows = [{"stmt_id": "0001", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "verbatim"},
            {"stmt_id": "0002", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "semantic"}]
    from agentflow import evidencebits

    got = evidencebits.clean_statement_ids(rows)
    assert got["clean"] == ["0001", "0002"], got
    assert "逐字" in got["reasons"]["0001"], got
    assert "语义" in got["reasons"]["0002"], got


# ============================================================ 4 语义那一档（B 唤起 H）
class _FakeGateway:
    """按剧本回答的替身模型（与 `tests/test_judges.py` 同一个形态）。"""

    spec = type("Spec", (), {"model": "fake", "api_key": "fake"})()

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: object) -> object:
        self.prompts.append(prompt)
        return type("Reply", (), {"ok": True, "text": self.text, "tokens_in": 3,
                                  "tokens_out": 3, "error_detail": "",
                                  "error_kind": ""})()


def _seam(root, text: str):
    from agentflow.llmseam import LlmSeam

    gate = _FakeGateway(text)
    return LlmSeam(role="H", session_root=root, gateway=gate, price=(0.0, 0.0), sid="t"), gate


_MATERIAL = {"quote": "The distance is the number of walls crossed.",
             "span": "The distance equals the number of walls the walk crosses.",
             "statement": "腔室距离 = 穿过的墙数", "where": "out/paper/main.tex:120"}


def test_the_semantic_criterion_is_registered_with_negative_controls() -> None:
    """判据表准入：这一条在表里、有 ≥2 条负控、且整张表自检干净。"""
    from agentflow import judges as JG

    assert "quote.same_meaning" in JG.CRITERIA
    crit = JG.CRITERIA["quote.same_meaning"]
    assert crit.pass_verdicts == ("same_meaning",), crit
    assert "stronger_than_source" in crit.verdicts, crit
    assert len(JG.NEGATIVE_CONTROLS["quote.same_meaning"]) >= 2
    assert JG.registry_problems() == [], JG.registry_problems()


def test_every_criterion_tells_the_model_to_answer_json() -> None:
    """每条判据的模板都要带上 `_JSON_RULES`（真机实测的教训，见那一处的 docstring）。

    第一版 `quote.same_meaning` 忘了接它：假缝夹具全绿，真机 5 条引文全部
    `judge_bad_json`（模型回散文）⇒ 那一档在真机上恒"没查成"。
    """
    from agentflow import judges as JG

    assert JG.json_rules_problems() == [], JG.json_rules_problems()


def test_a_rewritten_quote_passes_on_meaning_not_on_letters(tmp_path) -> None:
    """语义相同 ⇒ 通过（`quote_mode="semantic"`），并把这次调用留在证据里。

    这一条就是业主那句话的正面：**改写、换记号也算通过** —— 逐字档会判它不通过，
    语义档必须放它过，而且要说清是谁判的（judge）、哪一次调用（prompt_sha256）。
    """
    from agentflow import judges as JG

    seam, gate = _seam(
        tmp_path,
        '{"verdict": "same_meaning", "why": "换了一种说法，但说的是同一件事", "findings": []}',
    )
    got = JG.quote_semantics_judge_for(seam)(_MATERIAL)
    assert got["verdict"] == "same_meaning", got
    verified, mode, reason = JG.quote_fields_from_verdict(got["verdict"], got["why"])
    assert (verified, mode) == (True, "semantic"), (verified, mode, reason)
    assert "语义相同" in reason, reason
    assert got["call"]["prompt_sha256"], got["call"]
    assert got["call"]["judge_version"], got["call"]
    assert "不要" in gate.prompts[0] or "字面" in gate.prompts[0], gate.prompts[0][:200]


def test_a_stronger_quote_still_fails(tmp_path) -> None:
    """引文把来源的结论加强了 ⇒ **不通过**（语义档不是"放宽"，是换一把尺）。"""
    from agentflow import judges as JG

    seam, _gate = _seam(
        tmp_path,
        '{"verdict": "stronger_than_source", "why": "来源只对连通图成立，引文写成了对所有图",'
        ' "findings": []}',
    )
    got = JG.quote_semantics_judge_for(seam)(_MATERIAL)
    verified, mode, reason = JG.quote_fields_from_verdict(got["verdict"], got["why"])
    assert got["verdict"] == "stronger_than_source", got
    assert (verified, mode) == (False, ""), (verified, mode, reason)
    assert "不通过" in reason, reason


def test_without_a_seam_it_says_unchecked(tmp_path) -> None:
    """没有模型缝（没有 key）⇒ **没查**（既不是通过，也不是不通过）。"""
    from agentflow import judges as JG

    got = JG.quote_semantics_judge_for(None)(_MATERIAL)
    assert got["verdict"] == "unknown", got
    assert "judge_not_wired" in got["why"], got
    verified, mode, reason = JG.quote_fields_from_verdict(got["verdict"], got["why"])
    assert (verified, mode) == (None, ""), (verified, mode)
    assert reason.startswith("还没查"), reason


def test_a_broken_answer_is_unchecked_not_a_pass(tmp_path) -> None:
    """模型回了坏 JSON ⇒ 没查成（不许折成通过）。"""
    from agentflow import judges as JG

    seam, _gate = _seam(tmp_path, "我认为差不多吧（不是 JSON）")
    got = JG.quote_semantics_judge_for(seam)(_MATERIAL)
    verified, mode, _reason = JG.quote_fields_from_verdict(got["verdict"], got["why"])
    assert (verified, mode) == (None, ""), got


# ============================================================ 5 H 那一件（B 唤起 H 的落点）
def _h(tmp_path):
    from agentflow.agent_h import AgentH
    from agentflow.store import Store

    root = tmp_path / "ws-h"
    root.mkdir()
    Store(root).init()
    return AgentH(Store(root))


def test_the_h_action_says_unchecked_without_a_key(tmp_path) -> None:
    """没有 key（H 默认没有模型缝）⇒ 如实回「没查」，`same_meaning=None`。

    真机默认路径就是这一档：缝只在 `run-agent --semantic-review` 时才接到 H 手上。
    这一条钉的是"没有 key 时如实回没查"（业主那一句的后半段），
    不是通过、也不是不通过。
    """
    got = _h(tmp_path).judge_quote_semantics(quote="The distance is the number of walls.",
                                             span="The distance equals the number of walls.",
                                             where="main.tex:120", relation_id="0001")
    assert got["tri"] == "unreadable", got
    assert got["same_meaning"] is None, got
    assert got["judge"] == "H", got
    assert "没判成" in got["reason"] or "judge_not_wired" in got["reason"], got
    verified, mode, _reason = __import__("agentflow.judges", fromlist=["x"]) \
        .quote_fields_from_verdict("unknown", got["reason"])
    assert (verified, mode) == (None, ""), (verified, mode)


def test_the_h_action_refuses_incomplete_material(tmp_path) -> None:
    """材料不全（缺引文或缺来源片段）⇒ 明确拒绝，不许"凭印象判一下"。"""
    got = _h(tmp_path).judge_quote_semantics(quote="只有引文，没有来源那一段")
    assert got["tri"] == "unreadable" and got["same_meaning"] is None, got
    assert "材料不全" in got["reason"], got


# ============================================================ 6 端到端：H 判 → B 落
def test_h_judges_and_b_writes_it_back(tmp_path) -> None:
    """整条链跑通一次（不花模型钱）：H 判语义 → B 用**自己的**写面回填。

    这一条是"B 唤起 H"那件事的机器读数，三处一起量：

    1. H 的判定带着**证据**回来（`quote_span` 逐字来源片段 + `quote_call_sha256` 调用记录）；
    2. B 用 `table.update`（B 的面里有它，H 的面里没有）把判定写回 `relations`，
       写完之后那一行的 `quote_state` 是 `semantic`；
    3. 判与落分居两处：H 的可调用面里**没有** `table.update`。
    """
    from agentflow import evidencebits
    from agentflow.agent_h import AgentH
    from agentflow.llmseam import LlmSeam
    from agentflow.store import Store
    from agentflow.tools import build_registry

    root = tmp_path / "ws-e2e"
    root.mkdir()
    store = Store(root)
    store.init()
    row = S.Relation(relation_id="0001", concept_ids=["0001", "0002"], description="d",
                     lit_id="0000", page_range=S.PageRange(1, 2, "p.1-2"),
                     quote="The distance is the number of walls crossed.",
                     quote_verified=None, quote_reason="还没查").to_dict()
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", row)

    seam, _gate = _seam(root, '{"verdict": "same_meaning", "why": "换了一种说法，'
                              '但说的是同一件事", "findings": []}')
    h = AgentH(Store(root), llm=seam)
    got = h.judge_quote_semantics(
        quote=row["quote"], span="The distance equals the number of walls it crosses.",
        statement="腔室距离 = 穿过的墙数", where="out/paper/main.tex:120",
        relation_id="0001")
    assert got["tri"] == "computed" and got["same_meaning"] is True, got
    assert got["quote_mode"] == "semantic" and got["judge"] == "H", got
    assert got["quote_span"].startswith("The distance equals"), got
    assert got["quote_call_sha256"], got

    built = build_registry(store=Store(root), workspace_root=root)
    reg = getattr(built, "registry", built)
    assert "table.update" in reg.call_surface("B"), "B 的面上没有 table.update"
    assert "table.update" not in reg.call_surface("H"), \
        "H 是只读角色，它的可调用面里不该出现写工具（判与落必须分居两处）"

    res = reg.call("table.update", role="B", table="relations", id="0001",
                   patch={"quote_verified": got["same_meaning"],
                          "quote_mode": got["quote_mode"],
                          "quote_reason": got["quote_reason"],
                          "quote_span": got["quote_span"],
                          "quote_call_sha256": got["quote_call_sha256"]})
    assert getattr(res, "ok", False) is True, getattr(res, "error", res)
    after = Store(root).rows("relations")[0]
    assert evidencebits.quote_state(after) == "semantic", after
    assert evidencebits.quote_explains_itself(after) is True, after


def test_b_cannot_write_a_bare_semantic_without_evidence(tmp_path) -> None:
    """B 想写一个**没有证据**的 `semantic` ⇒ 写不进去（schema 当场拒）。

    这是"两栏不许互相冒充"在写边界上的那一半：光声明"语义相同"不算过 ——
    必须带着"对着哪一段、哪一次判的"。
    """
    from agentflow.store import Store
    from agentflow.tools import build_registry

    root = tmp_path / "ws-bare"
    root.mkdir()
    store = Store(root)
    store.init()
    row = S.Relation(relation_id="0001", concept_ids=["0001", "0002"], description="d",
                     lit_id="0000", page_range=S.PageRange(1, 2, "p.1-2"),
                     quote="q", quote_verified=None, quote_reason="还没查").to_dict()
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", row)
    built = build_registry(store=Store(root), workspace_root=root)
    reg = getattr(built, "registry", built)
    res = reg.call("table.update", role="B", table="relations", id="0001",
                   patch={"quote_verified": True, "quote_mode": "semantic",
                          "quote_reason": "我说语义相同"})
    assert getattr(res, "ok", False) is False, "没有证据的 semantic 竟然写进去了"
    assert "quote_span" in str(getattr(res, "error", "")), getattr(res, "error", res)
    after = Store(root).rows("relations")[0]
    assert after.get("quote_verified") is None, after

