# -*- coding: utf-8 -*-
"""业主 2026-11-13 补裁：逐字回验只卡引文录入那一遍；第二遍「优化」不卡逐字。

## 业主口径（逐字）

> 「逐字回验是正确的，要求引文录入时就是摘录相关原文。第二遍优化时不卡逐字回验。」

## 两遍的分工（本文件钉的就是它）

| 遍 | 是什么 | 逐字回验 |
|---|---|---|
| 第一遍：引文录入 | 从文献里摘一条命题（`origin="external_lit"`），`## 证明` 就是原文摘录 | 卡：说「逐字通过」就必须当场在全文里定位到（`quoteevidence.enforce_quote_evidence`；定位不到 ⇒ `quote_verified=False`，语义档缺区间 ⇒ 受控拒） |
| 第二遍：优化表述 | B 把已在册的证明换成自己读得懂的自然语言（`_rewrite_body` / `replace_existing` / `open_polish_copy` 那一线） | 不卡：引文四栏沿用第一遍（`quote_verified` / `quote_mode` / `quote_span` / `quote_reason`），不重新比对、也不再要求 `quote_reason` |

## 改前现场（本文件 a/b 的红）

- 第二遍不重新声明 `quote_verified` / `quote_reason` ⇒ 被
  `register_statement.py` 的 `missing_quote_reason` 挡住（三态纪律那条检查在第二遍上
  也生效）—— 优化这条路因此要求调用方把引文四栏再抄一遍；
- 第二遍若原样复用 `quote_verified=True` ⇒ `enforce_quote_evidence` 拿优化后的正文
  去比对原文 ⇒ `mismatch`（`quote_evidence.action="mismatch"`），把第一遍的结论冲掉。

改后：`_is_quote_second_pass`（在册 + 第一遍有 `quote_verified` + 正文换了）成立 ⇒
沿用第一遍，回执写 `quote_second_pass.action="kept_from_first_pass"`。

## 判据

| # | 判据 | 用例 |
|---|---|---|
| a1 | 第一遍：正文就是逐字引文 ⇒ 落 `quote_verified=True` + 区间 | `test_a1_*` |
| a2 | 第一遍：说「逐字通过」而全文里没有这一段 ⇒ 不许被记成通过（`quote_verified` 不是 True） | `test_a2_*` |
| a3 | 第一遍：语义档缺区间 ⇒ 仍受控拒（第一遍的硬闸没被放宽） | `test_a3_*` |
| b | 第二遍：优化后的正文（非逐字）⇒ 不拒；行上的引文四栏仍是第一遍的 | `test_b_*` |
| c | 反真空：把 `_is_quote_second_pass` 打桩成恒 `False` ⇒ b 必红（第二遍又被 `missing_quote_reason` 挡住） | `test_c_*` |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent
for _path in (_SRC, _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import conftest  # noqa: E402

from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T10:00:00+08:00"
LIT = "000000"
FULL = "设 G 是任意有限群，且 c 是某量；则 c(G) ≤ 1。"
QUOTE = "Theorem 1.2. Let G be a finite group. Then c(G) is at most 1."
#: B 优化之后的表述：不是原文摘录（第二遍不该拿它去比对原文）。
OPT = ("（B 优化后的表述）设 G 是任意有限群；把 c 看成该群的某个量，"
       "则 c(G) 不超过 1 —— 这是上面那条定理换了个说法的版本。")


class _Seam:
    """形态那一问的替身：本文件量的是引文回验，不是形态闸。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def ask_json(self, prompt, *, system="", task_id="", note=""):
        n = str(note or "")
        if n.endswith("secretary:proposition_form"):
            return ({"well_formed": True, "conditions": "夹具", "conclusion": "夹具",
                     "problems": [], "decision": "夹具"}, self._Call())
        return ({"decision": "different", "canonical_name": "夹具", "same_as": "",
                 "route": "", "condition": "夹具", "conclusion": "夹具",
                 "reason": "夹具：在册没有同一条", "basis": ["夹具"]}, self._Call())


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "library").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(st.root) / "library" / "paper.txt").write_text(
        "Preamble.\n" + QUOTE + "\n", encoding="utf-8", newline="\n")
    with st.tx("literature", actor="opt") as tx:
        tx.upsert("literature", {
            "lit_id": LIT, "title": "夹具文献", "type": "J", "summary": "夹具",
            "path": "paper.txt", "processed": True, "created_at": TS,
            "created_by": "opt"})
    return st


def _b(st: Store) -> AgentB:
    from agentflow.extract import extract_text

    sec = SEC.Secretary("B", root=st.root, store=st, seam=_Seam(), enable_model=True)
    return AgentB(st, extractor=None, extract_text=extract_text, config={},
                  secretary=sec)


def _first(st: Store, *, text: str = FULL, quote: str = QUOTE,
           quote_mode: str = "", quote_span: str = "") -> dict:
    return _b(st).register_statement(
        statement_full=text, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        quote_verified=True, quote_reason="逐字比对通过",
        quote_mode=quote_mode, quote_span=quote_span, proof_text=quote)


def _row(st: Store) -> dict:
    return dict(next(iter(st.rows("statements"))))


# ---------------------------------------------------------------- a1 第一遍记成通过
def test_a1_the_first_pass_records_the_verbatim_quote(tmp_path: pathlib.Path) -> None:
    """a1（正控）：第一遍的正文就是逐字引文 ⇒ `quote_verified=True` + 落出区间。"""
    st = _store(tmp_path)
    got = _first(st)
    assert got.get("ok") is True, got
    row = _row(st)
    assert row.get("quote_verified") is True, row
    assert str(row.get("quote_mode") or "") == "verbatim", row
    assert str(row.get("quote_span") or ""), row


# ---------------------------------------------------------------- a2 第一遍仍卡逐字
def test_a2_the_first_pass_cannot_claim_a_quote_that_is_not_there(
        tmp_path: pathlib.Path) -> None:
    """a2：第一遍说「逐字通过」而全文里没有这一段 ⇒ 不许被记成通过。"""
    st = _store(tmp_path)
    got = _first(st, quote="这一段原文里根本没有，是伪造的摘录（不是逐字）。")
    assert got.get("ok") is True, got
    row = _row(st)
    assert row.get("quote_verified") is not True, row
    evidence = dict(got.get("quote_evidence") or {})
    assert evidence.get("action") in ("mismatch", "downgrade"), evidence


# ---------------------------------------------------------------- a3 第一遍的硬闸仍在
def test_a3_a_semantic_quote_without_a_span_is_still_refused(
        tmp_path: pathlib.Path) -> None:
    """a3：第一遍走语义档却说不出对着哪一段 ⇒ 仍受控拒（没被第二遍的放行放宽）。"""
    st = _store(tmp_path)
    got = _first(st, quote_mode="semantic", quote_span="")
    assert got.get("ok") is False, got
    assert str(got.get("kind") or "") == "quote_evidence_missing", got
    assert not list(st.rows("statements")), list(st.rows("statements"))


# ---------------------------------------------------------------- b 第二遍不卡
def test_b_the_optimized_second_pass_keeps_the_first_quote_evidence(
        tmp_path: pathlib.Path) -> None:
    """b：第二遍（优化后的正文不是逐字）⇒ 不拒；引文四栏仍是第一遍的。"""
    st = _store(tmp_path)
    first = _first(st)
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    before = _row(st)
    assert before.get("quote_verified") is True, before
    span = str(before.get("quote_span") or "")
    assert span, before
    # 第二遍：签覆盖新正文（优化线本来就要 V 签），但不重新声明引文四栏。
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=OPT, store=st)
    got = _b(st).register_statement(
        statement_full=FULL, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        proof_text=OPT)

    assert got.get("ok") is True, got
    row = _row(st)
    assert str(row.get("proof_text") or "") == OPT, "第二遍的正文没换成优化后的那一版"
    assert row.get("quote_verified") is True, (
        "第二遍把第一遍的引文结论写坏了（优化后的正文本不该再比对原文）", row)
    assert str(row.get("quote_span") or "") == span, row
    read = dict(got.get("quote_second_pass") or {})
    assert read.get("action") == "kept_from_first_pass", read
    assert "不卡逐字" in str(read.get("why") or "") or "沿用" in str(read.get("why") or ""), read


# ---------------------------------------------------------------- c 反真空
def test_c_stubbing_the_second_pass_off_makes_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：把第二遍的识别打桩成恒 `False` ⇒ b 必红（第二遍又被 `missing_quote_reason` 挡住）。"""
    monkeypatch.setattr(AgentB, "_is_quote_second_pass", lambda self, **_kw: False)
    st = _store(tmp_path)
    first = _first(st)
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=OPT, store=st)
    got = _b(st).register_statement(
        statement_full=FULL, statement_text="", kind="theorem", label="主定理",
        origin="external_lit", source_lit_id=LIT, page_range={"start": 1},
        proof_text=OPT)

    assert got.get("ok") is False, (
        "把第二遍的识别摘掉之后仍然过了 ⇒ b 的绿证明不了这条分轴在承重", got)
    assert str(got.get("kind") or "") == "missing_quote_reason", got
    row = _row(st)
    assert str(row.get("proof_text") or "") != OPT, "被拒的第二遍却把正文换了"
