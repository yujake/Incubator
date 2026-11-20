# -*- coding: utf-8 -*-
"""判据：登记那一刻的 `kind` 与 `grade`（KINDGRADE 路，2026-11-20）。

## 现场（lp-ball-13，已取证）

`projects/lp-ball-13/data/statements.json`：13 行 = `concept` 7 + `conjecture` 6，
13 行全是 `origin=external_lit`。那 6 行 `conjecture` 的 label 逐字是
「Meyer–Pajor 定理 / Ball 立方体最大截面定理 / Grząślewicz p-cozonoid 定理 /
Aliev 立方体超平面截面体积最优上界 / Oleszkiewicz：Ball 结果对 2<p<p0 不成立 /
König 主定理」—— 文献里的定理被登记成了"（我们的）猜想"。
`runs/B-20261120-131024-001.json` 的 step#8/9/25/32 逐字显示：B 交的就是
`kind="conjecture"`，而登记路一个字都没判，原样落盘。

## 判据（五条）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 文献定理陈述（`external_lit` + 逐字引文，交来的 `kind=conjecture`）⇒ 行上 `kind=theorem` | 改前原样落 `conjecture` |
| b | 文献定义（`external_lit` + `kind=concept`）⇒ 行上 `kind=concept`（正控） | 改前也绿（这一条是"别把它改掉"） |
| c | 我们自己的未证猜想（`own_result` + 无签 + `kind=conjecture`）⇒ 行上 `kind=conjecture`（正控） | 改前也绿（同上） |
| d | 登记回执的 `grade` 非空、且等于行上 `bits.grade`；算不出来 ⇒ `unjudged` + `why` | 改前回执上根本没有 `grade` 这一格 |
| e | 反真空：把 ① 的判据打桩回旧默认（恒等）⇒ a 必红；把 ② 的判据打桩掉（返回空）⇒ d 必红 | — |

判据本体只有一处：`evidencebits.kind_at_registration`（kind）与
`evidencebits.grade_at_registration`（grade）。本文件不另写一份判定，只量
"写侧有没有真的用它"与"它判出来的东西有没有落到行上 / 回执上"。
"""
from __future__ import annotations

import pytest

from conftest import add_literature, b_form_gate_ok, sign_before_registration

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store

PROOF = ("证明（逐字摘录）：Meyer and Pajor considered the analogue in ln p for 1 <= p < inf. "
         "They proved that the normalized volume of central hyperplane sections is monotone "
         "increasing in p.")
STATEMENT = "设 1 <= p < 无穷。则归一化中心超平面截面函数 A_{n,p}(a) 关于 p 单调递增。"
CONCEPT = "概念（中心超平面截面）：过凸体中心、法向量为 a 的超平面截凸体所得的截面。"


def _b(store: Store) -> AgentB:
    """真 B 与真秘书；只把命题形态那一问钉成"已过"（与 b① 判据同一取舍）。"""
    return b_form_gate_ok(AgentB(store, extractor=None, extract_text=None))


def _cited(**kw) -> dict:
    """一条文献定理陈述的登记参数（`origin=external_lit` + 逐字引文）。"""
    base: dict = dict(
        statement_full=STATEMENT, origin="external_lit", kind="conjecture",
        label="Meyer–Pajor 定理", proof_text=PROOF,
        source_lit_id=S.format_id(0), page_range={"start": 2, "end": 2},
        quote_verified=True, quote_reason="逐字比对通过（page 2）",
        evidence_kind="cross_check")
    base.update(kw)
    return base


def _own(**kw) -> dict:
    """一条我们自己的、还没证的猜想（`origin=own_result` + 无签 + 空证明栏）。"""
    base: dict = dict(
        statement_full="设 n>=3，则 n^2+n 是偶数。", origin="own_result",
        kind="conjecture", label="偶数探针", proof_text="",
        doc_id=S.format_id(0), line_range={"label": "manuscripts/handoffs.jsonl#0042"},
        quote_verified=None, quote_reason="own_result：我方还没证，留着当猜想",
        evidence_kind="heuristic")
    base.update(kw)
    return base


def _row(store: Store, sid: str) -> dict:
    return next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)


def _register(store: Store, payload: dict) -> tuple[dict, dict]:
    add_literature(store, S.format_id(0)) if not any(
        str(r.get("lit_id")) == S.format_id(0) for r in store.rows("literature")) else None
    out = _b(store).register_statement(**payload)
    sid = str(out.get("stmt_id") or "")
    return out, (_row(store, sid) if sid else {})


# =================================================================== a 文献定理
def test_a_a_cited_theorem_is_not_registered_as_our_conjecture(store) -> None:
    """a：文献里的定理陈述登记成 `theorem`；交来的 `conjecture` 必须被记成一次改写。"""
    sign_before_registration(store.root, proof_text=PROOF)
    out, row = _register(store, _cited())
    assert out.get("ok") is True, out
    assert row.get("kind") == "theorem", (
        f"文献里的定理陈述落成了 {row.get('kind')!r}（改前就是这一格：原样落 conjecture）")
    judged = dict(out.get("kind_judgement") or {})
    assert judged.get("changed") is True, judged
    assert (judged.get("declared"), judged.get("kind")) == ("conjecture", "theorem"), judged
    assert judged.get("row_kind") == "theorem", judged
    # 依据必须是"origin + 正文形态"那一句，而不是"标签里有『定理』"这种词表打分。
    assert "external_lit" in str(judged.get("basis") or ""), judged


# =================================================================== b 文献定义（正控）
def test_b_a_cited_definition_stays_a_concept(store) -> None:
    """b（正控）：文献里来的定义 / 术语登记成 `concept`，一个字节不改。"""
    out, row = _register(store, _cited(
        statement_full=CONCEPT, kind="concept", label="概念（中心超平面截面）",
        proof_text="", quote_verified=None,
        quote_reason="概念行不带证明正文 ⇒ 没有可比对对象，本格未查",
        evidence_kind="heuristic"))
    assert out.get("ok") is True, out
    assert row.get("kind") == "concept", row.get("kind")
    judged = dict(out.get("kind_judgement") or {})
    assert judged.get("changed") is False, judged
    assert judged.get("declared") == judged.get("kind") == "concept", judged


# =================================================================== c 自己的猜想（正控）
def test_c_our_own_unproved_claim_stays_a_conjecture(store) -> None:
    """c（正控）：我们自己的、还没证的猜想登记成 `conjecture` —— 这一条不许被 a 改掉。"""
    out, row = _register(store, _own())
    assert out.get("ok") is True, out
    assert row.get("kind") == "conjecture", (
        f"自己的未证猜想被改成了 {row.get('kind')!r}：`conjecture` 这一档必须留得住")
    judged = dict(out.get("kind_judgement") or {})
    assert judged.get("changed") is False, judged
    assert "own_result" in str(judged.get("basis") or ""), judged


# =================================================================== d 等级现算
def test_d_the_registration_receipt_carries_the_computed_grade(store) -> None:
    """d：登记回执上的 `grade` 非空，且与行上 `bits.grade` 逐字相同（行上没有顶层 grade 列）。"""
    sign_before_registration(store.root, proof_text=PROOF)
    out, row = _register(store, _cited())
    assert out.get("ok") is True, out
    grade = str(out.get("grade") or "")
    assert grade, f"登记回执上 grade 是空的（改前就是这一形态）：{out.get('grade_reading')}"
    assert grade != EB.GRADE_UNJUDGED, out.get("grade_reading")
    row_grade = str((row.get("bits") or {}).get("grade") or "")
    assert row_grade == grade, (
        f"回执说 {grade!r}、行上说 {row_grade!r} ⇒ 判的与落的分家了")
    # 概念行走 `not_applicable`（不是"最弱那一档"），同一个判据给的。
    _, concept_row = _register(store, _cited(
        statement_full=CONCEPT, kind="concept", label="概念（截面）",
        proof_text="", quote_verified=None, quote_reason="概念行没有可比对的引文"))
    assert (concept_row.get("bits") or {}).get("grade") == EB.GRADE_NOT_APPLICABLE, \
        concept_row.get("bits")


def test_d2_uncomputable_bits_are_unjudged_not_the_lowest_grade() -> None:
    """d（第三态）：五元位读不出来 ⇒ `unjudged` + `why`，不许折成 `conjecture`。"""
    empty = EB.grade_at_registration({}, kind="theorem")
    assert empty["checked"] is False, empty
    assert empty["grade"] == EB.GRADE_UNJUDGED, empty
    assert empty["grade"] != "conjecture", empty
    assert str(empty["why"]).strip(), empty

    def _boom(*_a, **_kw):
        raise ValueError("夹具：五元位坏了")

    real = EB.derive_grade
    try:
        EB.derive_grade = _boom
        raised = EB.grade_at_registration({"proof": True}, kind="theorem")
    finally:
        EB.derive_grade = real
    assert raised["checked"] is False, raised
    assert raised["grade"] == EB.GRADE_UNJUDGED, raised
    assert "五元位算不出来" in str(raised["why"]), raised

    # 缓存与现算不一致 ⇒ mismatch（两个数并列，不静默取一个）。
    stale = EB.grade_at_registration(
        {"numeric": "na", "proof": False, "reviewed": False, "formal": "na",
         "audited": False, "origin": "own_result", "evidence": {}, "voided_by": {},
         "grade": "theorem"}, kind="conjecture")
    assert stale["checked"] is True, stale
    assert stale["mismatch"] is True, stale
    assert (stale["stored_grade"], stale["grade"]) == ("theorem", "conjecture"), stale


# =================================================================== e 反真空
def test_e_anti_vacuum_the_old_verbatim_kind_default_turns_a_red(
        monkeypatch: pytest.MonkeyPatch, store) -> None:
    """e（反真空 ①）：把 kind 判据打桩回旧默认（写什么落什么）⇒ a 必须红。"""
    sign_before_registration(store.root, proof_text=PROOF)

    def _verbatim(*, origin, kind="", cited_body=False):  # noqa: ANN001 - 与真身同签名
        declared = str(kind or "").strip()
        return {"checked": True, "kind": declared, "declared": declared,
                "changed": False, "basis": "打桩：旧默认（写什么落什么）", "why": ""}

    monkeypatch.setattr(EB, "kind_at_registration", _verbatim)
    out, row = _register(store, _cited())
    assert out.get("ok") is True, out
    assert row.get("kind") == "conjecture", (
        "打桩回旧默认之后行上仍是 theorem ⇒ a 量的不是那条判据（判据没有承重）")


def test_e_anti_vacuum_stubbing_the_grade_judgement_blanks_d(
        monkeypatch: pytest.MonkeyPatch, store) -> None:
    """e（反真空 ②）：把 grade 判据打桩成"什么都不判" ⇒ 回执上的 grade 必须变空。"""
    sign_before_registration(store.root, proof_text=PROOF)
    monkeypatch.setattr(
        EB, "grade_at_registration",
        lambda *_a, **_kw: {"checked": False, "grade": "", "stored_grade": "",
                            "mismatch": False, "why": "打桩：不判"})
    out, _row = _register(store, _cited())
    assert out.get("ok") is True, out
    assert out.get("grade") == "", (
        "把 grade 判据打桩掉之后回执上还有等级 ⇒ d 量的不是它（判据没有承重）")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
