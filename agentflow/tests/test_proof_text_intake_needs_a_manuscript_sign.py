# -*- coding: utf-8 -*-
"""判据：证明正文进 `statements` 必须有一份「审的是手稿」的签（2026-11-04 业主裁定）。

## 为什么这一组存在

`proof_text` 是 `statements` 里唯一被 V 签过才算数的字段，而写它的路不止一条：
B 的 `register_statement`、`table.create` / `table.update` 的 `routed` 分支、秘书的
合并支、B 的 `_attach_proofs`（canonical 覆盖 / #p2 追加）。判据放在字段的收口处
（`Secretary.record_statement` + `B._attach_proofs` 共用
`secretary.proof_text_manuscript_sign_gate`），不按入口各写一份。

四条判据（每条都带反真空）：
| # | 判什么 | 改前 |
|---|---|---|
| a | `table.create` 带 `proof_text` 而签不是手稿签 ⇒ 拒、0 行 | 落盘、`bits={}`、0 依赖 |
| b | `table.update` 改 `statement_full` + `proof_text` ⇒ 拒，不许悄悄建新行 | 静默建 000001 |
| c | B 的 `register_statement(proofs=[…])` 用内联签 ⇒ 拒；换成手稿签 ⇒ 收 | 内联签也收 |
| d | 合并稿的依赖边与正文同一次事务落盘 | `deps_written=0`、新边静默丢 |

反真空的手法：把收口函数打桩成恒放行 ⇒ a/b/c 必须回到"写得进去"；把
`_write_dep_steps` 在合并那一笔打桩成 0 ⇒ d 必须回到"新边不在表里"。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.conductor import calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import table_tools as TT
from agentflow.tools.base import ToolRegistry

TS = "2026-11-04T00:00:00+00:00"
STATEMENT = "设 f 连续，则 f 在紧集上一致连续。"
PROOF = "证明。由定义直接得到。∎"
NEAR = "设 f 是连续函数；则 f 在紧集上一致连续。"
MERGED = "证明（合并稿）。由定义与紧性直接得到。∎"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _row(st: Store, sid: str) -> dict[str, Any]:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id") or "") == sid)


def _empty_conjecture(st: Store) -> str:
    sec = Secretary("B", root=st.root, store=st)
    got = sec.record_statement(
        {"origin": "own_result", "kind": "conjecture", "label": "X",
         "statement_full": STATEMENT, "proof_text": "",
         "line_range": {"start": 1, "end": 3}, "quote_verified": None,
         "quote_reason": "我方自证"}, role="B")
    assert got.get("created") is True, got
    return str(got["stmt_id"])


def _sign(st: Store, sid: str, text: str, *, manuscript: str = "") -> None:
    """签满门槛（`SIGN_STREAK_NEED` 次「成立」）；`manuscript` 空 = 内联签（今晚 14:22 那一档）。"""
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            str(st.root), statement_id=sid, proof_text=text,
            verdict={"verdict": "成立"},
            secretary_judge={"axis": "clean", "checked": True},
            proof_no=1, store=st, manuscript=manuscript)


def _reg(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="intake-gate")
    TT.register(reg, store=st)
    return reg


def _create(reg: ToolRegistry, row: dict[str, Any]) -> Any:
    with calling_as("t-000001", "B"):
        return reg.call("table.create", table="statements", row=row, role="B")


# ============================================================ a  table.create

def test_a_table_create_with_inline_proof_text_is_refused(tmp_path):
    st = _ws(tmp_path)
    reg = _reg(st)
    res = _create(reg, {"origin": "own_result", "kind": "theorem", "label": "直写",
                        "statement_full": STATEMENT, "proof_text": PROOF,
                        "line_range": {"start": 1, "end": 3},
                        "quote_verified": None, "quote_reason": "我方自证",
                        "evidence_kind": "heuristic"})
    assert res.ok is False, res
    assert "proof_text_needs_a_manuscript_sign" in (res.error or ""), res.error
    assert st.rows("statements") == [], st.rows("statements")
    # 反真空：把收口函数打桩成恒放行 ⇒ 同一笔必须回到"落盘"（改前形态）。
    import agentflow.secretary as SEC

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(SEC, "proof_text_manuscript_sign_gate",
                            lambda *a, **k: {"checked": True, "required": True,
                                             "ok": True, "refused": "", "reason": "",
                                             "statement_id": "", "proof_no": 1,
                                             "sha256": "", "covering": []})
        res2 = _create(reg, {"origin": "own_result", "kind": "theorem", "label": "直写",
                             "statement_full": STATEMENT, "proof_text": PROOF,
                             "line_range": {"start": 1, "end": 3},
                             "quote_verified": None, "quote_reason": "我方自证",
                             "evidence_kind": "heuristic"})
        assert res2.ok is True, res2
        assert len(st.rows("statements")) == 1, st.rows("statements")
    finally:
        monkeypatch.undo()


# ============================================================ b  table.update

def test_b_table_update_may_not_smuggle_a_new_row_with_proof_text(tmp_path):
    st = _ws(tmp_path)
    sid = _empty_conjecture(st)
    reg = _reg(st)
    with calling_as("t-000001", "B"):
        res = reg.call("table.update", table="statements", id=sid,
                       patch={"statement_full": "设 g 是连续函数；则 g 在闭区间上一致连续。",
                              "proof_text": PROOF}, role="B")
    assert res.ok is False, res
    assert "proof_text_needs_a_manuscript_sign" in (res.error or ""), res.error
    rows = st.rows("statements")
    assert len(rows) == 1, ("这一笔不是改，是建新行", rows)
    assert str(_row(st, sid).get("proof_text") or "") == "", _row(st, sid)


# ============================================================ c  B 的内联签

def test_c_b_register_accepts_only_a_manuscript_sign(tmp_path):
    st = _ws(tmp_path)
    sid = _empty_conjecture(st)
    _sign(st, sid, PROOF, manuscript="")          # 今晚 14:22 那一档：内联签
    b = AgentB(st, extractor=None, extract_text=None)
    inline = b.register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        proof_text=PROOF, line_range={"start": 1, "end": 3},
        quote_verified=None, quote_reason="我方自证")
    assert inline.get("ok") is False, inline
    assert inline.get("kind") == "proof_text_needs_a_manuscript_sign", inline
    assert str(_row(st, sid).get("proof_text") or "") == "", _row(st, sid)

    # 正控：同一份正文，签同一份稿（台账行带 `manuscript`）⇒ 收下。
    st2 = _ws(tmp_path / "signed")
    sid2 = _empty_conjecture(st2)
    _sign(st2, sid2, PROOF, manuscript="reports/f-proof-000000.md")
    b2 = AgentB(st2, extractor=None, extract_text=None)
    ok = b2.register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        proof_text=PROOF, line_range={"start": 1, "end": 3},
        quote_verified=None, quote_reason="我方自证")
    assert ok.get("ok") is True, ok
    assert _row(st2, sid2).get("proof_text") == PROOF, _row(st2, sid2)


# ============================================================ d  合并稿的依赖面

def _proof_review_lemma(st: Store, sec: Secretary, *, full: str, label: str) -> str:
    """落一条 `proof_review` 级的引理（依赖段要求被引命题到这个档）。"""
    got = sec.record_statement(
        {"origin": "own_result", "kind": "lemma", "label": label,
         "statement_full": full, "proof_text": "",
         "line_range": {"start": 1, "end": 1}, "quote_verified": None,
         "quote_reason": "我方自证"}, role="B")
    assert got.get("created") is True, got
    sid = str(got["stmt_id"])
    text = f"证明（{label}）。由定义直接得到。∎"
    _sign(st, sid, text, manuscript=f"reports/f-proof-{sid}.md")
    b = AgentB(st, extractor=None, extract_text=None)
    wrote = b.register_statement(
        statement_full=full, origin="own_result", kind="conjecture",
        proof_text=text, line_range={"start": 1, "end": 1},
        quote_verified=None, quote_reason="我方自证")
    assert wrote.get("ok") is True, wrote
    up = sec.record_statement(
        {"origin": "own_result", "kind": "conjecture", "label": label,
         "statement_full": full, "proof_text": text,
         "line_range": {"start": 1, "end": 1}, "quote_verified": None,
         "quote_reason": "我方自证", "evidence_kind": "proof_review"}, role="B")
    assert up.get("upgraded") is True, up
    return sid


def test_d_merge_writes_the_merged_texts_dependencies_in_the_same_transaction(tmp_path):
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    lemma1 = {"stmt_id": _proof_review_lemma(
        st, sec, full="引理 A：旧依赖。", label="引理 A")}
    lemma2 = {"stmt_id": _proof_review_lemma(
        st, sec, full="引理 B：合并稿新依赖。", label="引理 B")}
    sid = _empty_conjecture(st)
    _sign(st, sid, PROOF, manuscript="reports/f-proof-000000.md")
    from agentflow import depsection as DS

    manuscript = (
        "# F 的证明手稿\n\n- 命题号：stmt:" + sid + "\n\n## 命题\n\n" + STATEMENT
        + "\n\n## 证明\n\n" + PROOF + "\n\n"
        + DS.render_dependency_section([{
            "quote": "引理 A", "stmt_id": str(lemma1["stmt_id"]),
            "step": "第 1 步", "path_group": 1}]))
    b = AgentB(st, extractor=None, extract_text=None)
    first = b.register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        proof_text=PROOF, line_range={"start": 1, "end": 3},
        quote_verified=None, quote_reason="我方自证", proof_manuscript=manuscript)
    assert first.get("ok") is True, first
    assert len(st.rows("dependencies")) == 1, st.rows("dependencies")

    # 合并稿自己也要有手稿签（与"正文必须由手稿承载"同一条规则）。
    _sign(st, sid, MERGED, manuscript="reports/b-proof-000000.md")
    sec.adjudicate_proposition = lambda payload: {  # type: ignore[method-assign]
        "checked": True, "attempted": True, "verdict": "same",
        "canonical_name": "X", "same_as": sid, "basis": "夹具：判 same",
        "reason": "夹具", "reused": False, "cached": False,
        "seam_source": "fixture", "candidates": [{"stmt_id": sid}],
        "proposition_adjudication": {"checked": True, "attempted": True,
                                     "reason": "fixture", "seam_source": "fixture"}}
    merged = sec.record_statement(
        {"origin": "own_result", "kind": "theorem", "label": "X",
         "statement_full": NEAR, "proof_text": MERGED,
         "line_range": {"start": 1, "end": 3}, "quote_verified": None,
         "quote_reason": "我方自证", "merge": True, "proof_no": 1,
         "deps": [[{"kind": "theorem", "stmt_id": str(lemma2["stmt_id"]),
                    "label": "引理 B"}]]}, role="B")
    assert merged.get("merged") is True, (merged.get("refused"), merged.get("reason"),
                                          merged.get("proof_text_gate"))
    assert int(merged.get("deps_written") or 0) == 1, merged
    labels = [str(d.get("label") or "") for d in st.rows("dependencies")]
    assert any("引理 A" in x for x in labels), labels
    assert any("引理 B" in x for x in labels), labels
    assert str(_row(st, sid).get("proof_text")) == MERGED, _row(st, sid)

    # 反真空：把依赖写入打桩成 0 ⇒ 这一笔回到"新边不在表里"。
    from agentflow import secretary as SEC

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(SEC.Secretary, "_write_dep_steps",
                            lambda self, tx, steps, *, stmt_id, body: 0)
        # 再合并一次（换一份正文，绕开同 sha 早退）
        _sign(st, sid, MERGED + "\n（订正）", manuscript="reports/b-proof-000000.md")
        merged2 = sec.record_statement(
            {"origin": "own_result", "kind": "theorem", "label": "X",
             "statement_full": NEAR, "proof_text": MERGED + "\n（订正）",
             "line_range": {"start": 1, "end": 3}, "quote_verified": None,
             "quote_reason": "我方自证", "merge": True, "proof_no": 1,
             "deps": [[{"kind": "theorem", "stmt_id": str(lemma2["stmt_id"]),
                        "label": "引理 B（订正）"}]]}, role="B")
        assert int(merged2.get("deps_written") or 0) == 0, merged2
        labels2 = [str(d.get("label") or "") for d in st.rows("dependencies")]
        assert "引理 B（订正）" not in labels2, labels2
    finally:
        monkeypatch.undo()
