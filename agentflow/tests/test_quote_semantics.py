# -*- coding: utf-8 -*-
"""引文回验的两档（业主 2026-10-14）：「回验不应该是十分呆板的逐字验证，
而是保持语义相同即可」；落点是 B 唤起 H。

这一组守三件事：

1. 两栏的分工：`quote_verified` 是三态结论，`quote_mode` 是通过的方式
   （`verbatim` 逐字命中 / `semantic` 语义相同）。两栏互相冒充的行不许拿到学分。
2. 历史行不许被追溯性降级：`quote_mode` 这一栏是今天才有的，在那之前
   `quote_verified=True` 只可能来自 `quoteverify.check_quote`（逐字那一档）⇒
   空方式按 `verbatim` 读（判据 `test_a_legacy_external_lit_row_keeps_its_citation_credit`
   也钉着这条）。
3. 语义档不许被逐字档顶替：H 判的"语义相同"与"结论强于引文"是两件事，
   后者仍必须落 `mismatch`（判据见 `quote_state` 的表）。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S


# ============================================================ 1 五态表
#: 一个形状合法的区间（口径 `p{页}:norm[起:止]`，见 `quoteevidence.SPAN_SCHEME`）。
_SPAN = "p2:norm[4:44]"

@pytest.mark.parametrize("row, want", [
    # 还没查
    ({"quote_verified": None}, "unchecked"),
    ({}, "unchecked"),
    # 查过了、不一致（语义档也救不了它：H 的判据是"说同一件事"）
    ({"quote_verified": False}, "mismatch"),
    ({"quote_verified": False, "quote_mode": "semantic"}, "mismatch"),
    # 通过的两档（都带得出区间：区间是"核的是哪一段"的唯一载子）
    ({"quote_verified": True, "quote_mode": "verbatim", "quote_span": _SPAN}, "verbatim"),
    ({"quote_verified": True, "quote_mode": "semantic", "quote_span": "excerpt",
      "quote_call_sha256": "c0ffee"}, "semantic"),
    # 历史行：方式那一栏还没有的时代，True 只可能来自逐字那一档（区间仍要非空）
    ({"quote_verified": True, "quote_span": _SPAN}, "verbatim"),
    ({"quote_verified": True, "quote_mode": "", "quote_span": _SPAN}, "verbatim"),
    # 说不出方式的通过 ⇒ 按没查算（词表外的值就是"说不清"）
    ({"quote_verified": True, "quote_mode": "fuzzy"}, "unchecked"),
    ({"quote_verified": True, "quote_mode": "看起来一样"}, "unchecked"),
    # D1（2026-10-22 第二版）：说通过而拿不出区间 ⇒ 第五档 `no_evidence`。
    # 真机那 13 行就是这些形状（`true` + `verbatim` / 空方式 + 空 span）。
    ({"quote_verified": True, "quote_mode": "verbatim"}, "no_evidence"),
    ({"quote_verified": True}, "no_evidence"),
    ({"quote_verified": True, "quote_mode": "", "quote_span": ""}, "no_evidence"),
    # 语义档的第二件证据（调用指纹）缺了，同样拿不出"哪一次判的" ⇒ 同一档。
    ({"quote_verified": True, "quote_mode": "semantic", "quote_span": "excerpt"},
     "no_evidence"),
])
def test_the_quote_state_table(row: dict, want: str) -> None:
    """五态表（唯一读口径）：`unchecked` / `mismatch` / `verbatim` / `semantic` / `no_evidence`。"""
    assert EB.quote_state(row) == want, row
    assert EB.quote_explains_itself(row) == (want in S.QUOTE_MODES), row


# ============================================================ 2 写侧归一
def _stmt(**kw) -> S.Statement:
    base = dict(stmt_id="0001", origin="external_lit", statement_full="若 A 则 B",
                source_lit_id="0000", quote_reason="核对过")
    base.update(kw)
    return S.Statement(**base)


def test_a_bare_true_is_only_recorded_as_verbatim_when_it_has_a_span() -> None:
    """D1（2026-10-22 第二版）：空方式记实成 verbatim 的前提从"说了通过"收紧成"有区间"。

    改前：`quote_verified=True` 而 `quote_mode` 空 ⇒ 一律记成 `verbatim`（历史事实：
    这一栏出现之前 True 只可能来自逐字那一档）。但真机 13 行说明那个前提已经不成立：
    它们正是"空方式 + 空区间"，被记成逐字通过之后，读侧与收工门都按"核过了"算。
    所以现在只有拿得出区间时才记实；区间为空就留空串，由读侧读成 `no_evidence`。
    """
    bare = _stmt(quote_verified=True)
    bare.validate()
    assert bare.quote_mode == "", ("没有区间就不许记成 verbatim（D1）："
                                   f"{bare.to_dict()}")

    with_span = _stmt(quote_verified=True, quote_span=_SPAN)
    with_span.validate()
    assert with_span.quote_mode == "verbatim", with_span.to_dict()
    assert with_span.quote_span == _SPAN, with_span.to_dict()


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
    """业主 2026-10-14：「语义那一档必须留证据」—— 缺证据的 semantic 当场拒。

    两样缺一不可：对着哪一段原文（`quote_span`）、哪一次判的（`quote_call_sha256`）。
    这一条是"两栏不许互相冒充"在内容上的那一半：不是写个 `semantic` 就算过。
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
    # 逐字那一档不需要这两栏（它自己那一份证据是"逐字命中" + 区间，由 check_quote
    # 与 locate_span 给）；D1 起"没有区间"不再记实成 verbatim（见上面那条判据）。
    plain = _stmt(quote_verified=True)
    plain.validate()
    assert plain.quote_mode == "" and plain.quote_span == "", plain.to_dict()
    verbatim = _stmt(quote_verified=True, quote_span=_SPAN)
    verbatim.validate()
    assert verbatim.quote_mode == "verbatim", verbatim.to_dict()


# ============================================================ 3 学分
def test_the_citation_credit_needs_a_usable_mode() -> None:
    """引用命题的学分：两档都给（逐字 / 语义），说不清方式的不给、没有区间的不给。"""
    ok_v = {"stmt_id": "0001", "origin": "external_lit", "source_lit_id": "0001",
            "quote_verified": True, "quote_mode": "verbatim", "quote_span": _SPAN,
            "status": "active"}
    ok_s = {**ok_v, "stmt_id": "0002", "quote_mode": "semantic",
            "quote_call_sha256": "c0ffee"}
    bad = {**ok_v, "stmt_id": "0003", "quote_mode": "fuzzy"}
    # D1（2026-10-22）：说通过而拿不出区间 ⇒ 学分不给（那是 `no_evidence`）。
    no_span = {**ok_v, "stmt_id": "0004", "quote_span": ""}
    assert EB.bits_from_row(ok_v)["grade"] == EB.bits_from_row(ok_s)["grade"] != "conjecture"
    assert EB.bits_from_row(bad)["grade"] == "conjecture", EB.bits_from_row(bad)
    assert EB.bits_from_row(no_span)["grade"] == "conjecture", (
        "空区间仍拿到引用学分 ⇒ D1 的读侧那一半没生效", EB.bits_from_row(no_span))


def test_the_credit_reason_says_which_mode_it_was() -> None:
    """理由那一栏要把两档说开（读的人不该去猜"核过"是哪种核过）。"""
    rows = [{"stmt_id": "0001", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "verbatim",
             "quote_span": _SPAN},
            {"stmt_id": "0002", "kind": "theorem", "origin": "external_lit",
             "source_lit_id": "0001", "quote_verified": True, "quote_mode": "semantic",
             "quote_span": "excerpt", "quote_call_sha256": "c0ffee"}]
    from agentflow import evidencebits

    got = evidencebits.clean_statement_ids(rows)
    assert got["clean"] == ["0001", "0002"], got
    assert "逐字" in got["reasons"]["0001"], got
    assert "语义" in got["reasons"]["0002"], got
    # D1：没有区间的"通过"落不进干净集合，而且理由说的是"拿不出证据"（不是"没核过"）。
    bare = dict(rows[0], stmt_id="0003", quote_span="")
    got2 = evidencebits.clean_statement_ids([bare])
    assert got2["clean"] == [], got2
    assert "拿不出" in got2["reasons"]["0003"], got2


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


def test_the_closing_gate_counts_by_the_same_two_columns(tmp_path) -> None:
    """收工门那一格（`quote_verified_rows`）走的是同一个读口径，且分方式报数。

    为什么单列一条：这一格的旧实现直接读 `quote_verified is True`，于是"说了通过、
    却说不清怎么通过的"（`quote_mode` 空/认不出的词）照样算通过 —— 与 `quote_state`
    那条纪律分家。改成走 `quote_state` 之后，`true` = 逐字 + 语义两个数之和，
    并各自单独报一栏（前者不花钱、后者是 H 判的，混在一起就看不出钱花在哪）。

     真实踩过的坑：`_leg_reading` 是一个跨上千行的大 if 链，函数体里任何一处
    `from . import evidencebits as EB` 都会让整个函数的 `EB` 变局部名，
    于是这一档报 `UnboundLocalError`、收工门那一格从 `pass` 悄悄退成 `unknown`
    （`test_closing_gate.py` 当场红）。这一条把"读得出来 + 口径对"一起钉住。
    """
    from agentflow import closing as CL
    from agentflow.store import Store

    root = tmp_path / "ws-close"
    root.mkdir()
    store = Store(root)
    store.init()
    rows = [
        {"stmt_id": "0000", "origin": "external_lit", "kind": "theorem",
         "statement_full": "甲", "source_lit_id": "0000",
         "quote_verified": True, "quote_reason": "逐字比对通过",
         # D1（2026-10-22）：老行（True 无方式）按逐字读的前提是它拿得出区间。
         "quote_span": "p2:norm[4:44]"},
        {"stmt_id": "0001", "origin": "external_lit", "kind": "theorem",
         "statement_full": "乙", "source_lit_id": "0000",
         "quote_verified": True, "quote_mode": "semantic",
         "quote_span": "来源那一段", "quote_call_sha256": "abc",
         "quote_reason": "H 判语义相同"},
        {"stmt_id": "0002", "origin": "external_lit", "kind": "theorem",
         "statement_full": "丙", "source_lit_id": "0000",
         "quote_verified": None, "quote_reason": "（下面直接改盘上那份 JSON：手改行）"},
        {"stmt_id": "0003", "origin": "external_lit", "kind": "theorem",
         "statement_full": "丁", "source_lit_id": "0000",
         "quote_verified": None, "quote_reason": "还没查"},
        # D1：说通过而拿不出区间（真机那 13 行的形状）⇒ 单列一栏，不算 true。
        {"stmt_id": "0004", "origin": "external_lit", "kind": "theorem",
         "statement_full": "戊", "source_lit_id": "0000",
         "quote_verified": True, "quote_mode": "verbatim",
         "quote_span": "", "quote_reason": "逐字比对通过（没有区间）"},
    ]
    with store.tx("statements", actor="test") as tx:
        for row in rows:
            tx.upsert("statements", row)

    # ② 手改盘上那份 JSON 造一行"说了通过、方式认不出"的（写入侧本来会拒它 ——
    #    而 `quote_state` 要挡的正是绕过写入侧的行：手改的、旧版本写的、别的工具写的）。
    import json as _json

    data_path = root / "data" / "statements.json"
    doc = _json.loads(data_path.read_text(encoding="utf-8"))
    body = doc["rows"] if isinstance(doc, dict) and "rows" in doc else doc
    for row in body:
        if str(row.get("stmt_id")) == "0002":
            row["quote_verified"] = True
            row["quote_mode"] = "fuzzy"
            row["quote_reason"] = "说不清怎么通过的"
    data_path.write_text(_json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    count, reading = CL._leg_reading(Store(root), "quote_verified_rows", root)
    assert reading["verbatim"] == 1, reading      # 老行（True 无方式、有区间）按逐字读
    assert reading["semantic"] == 1, reading
    assert reading["true"] == 2, reading          # 逐字 + 语义
    assert reading["unchecked"] == 2, reading     # `fuzzy` 那一行 + 还没查那一行
    # D1（2026-10-22）：说通过而无区间单列一栏，且不计入 `true` 与 `judged`。
    assert reading["no_evidence"] == 1, reading
    assert count == 2, (count, reading)

    """每条判据的模板都要带上 `_JSON_RULES`（真机实测的教训，见那一处的 docstring）。

    第一版 `quote.same_meaning` 忘了接它：假缝夹具全绿，真机 5 条引文全部
    `judge_bad_json`（模型回散文）⇒ 那一档在真机上恒"没查成"。
    """
    from agentflow import judges as JG

    assert JG.json_rules_problems() == [], JG.json_rules_problems()


class _BadThenGood:
    """第一次回散文、第二次回合法 JSON 的替身（量"重试一次"那条）。"""

    spec = type("Spec", (), {"model": "fake", "api_key": "fake"})()

    def __init__(self, good: str) -> None:
        self.good = good
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: object) -> object:
        self.calls += 1
        self.prompts.append(prompt)
        text = "我觉得差不多吧（不是 JSON）" if self.calls == 1 else self.good
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 3,
                                  "tokens_out": 3, "error_detail": "", "error_kind": ""})()


def test_a_bad_first_answer_is_retried_once(tmp_path) -> None:
    """答歪一次 ⇒ 重试一次（真机那一档：思维链吃光预算 / 把 JSON 说成散文）。

    重试只在"模型答歪了"那两档上做，且只做一次；重试仍不成 ⇒ 三态里的"没查成"
    （`test_a_broken_answer_is_unchecked_not_a_pass` 钉着那一半）。
    """
    from agentflow import judges as JG
    from agentflow.llmseam import LlmSeam

    gate = _BadThenGood('{"verdict": "same_meaning", "why": "第二次答对了", "findings": []}')
    seam = LlmSeam(role="H", session_root=tmp_path, gateway=gate, price=(0.0, 0.0), sid="t")
    got = JG.judge("quote.same_meaning", "引文：a\n来源：a", seam=seam)
    assert gate.calls == 2, f"没有重试（调用 {gate.calls} 次）"
    assert got.ok is True and got.verdict == "same_meaning", got
    # 第二次的 prompt 里多一句"先给 JSON"（告诉模型这次该怎么答）
    assert len(gate.prompts) == 2 and "先" in gate.prompts[1], gate.prompts[1][-200:]


def test_a_rewritten_quote_passes_on_meaning_not_on_letters(tmp_path) -> None:
    """语义相同 ⇒ 通过（`quote_mode="semantic"`），并把这次调用留在证据里。

    这一条就是业主那句话的正面：改写、换记号也算通过 —— 逐字档会判它不通过，
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
    """引文把来源的结论加强了 ⇒ 不通过（语义档不是"放宽"，是换一把尺）。"""
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
    """没有模型缝（没有 key）⇒ 没查（既不是通过，也不是不通过）。"""
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
    """整条链跑通一次（不花模型钱）：H 判语义 → B 用自己的写面回填。

    这一条是"B 唤起 H"那件事的机器读数，三处一起量：

    1. H 的判定带着证据回来（`quote_span` 逐字来源片段 + `quote_call_sha256` 调用记录）；
    2. B 用 `table.update`（B 的面里有它，H 的面里没有）把判定写回 `relations`，
       写完之后那一行的 `quote_state` 是 `semantic`；
    3. 判与落分居两处：H 的可调用面里没有 `table.update`。
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
    """B 想写一个没有证据的 `semantic` ⇒ 写不进去（schema 当场拒）。

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

