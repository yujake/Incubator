# -*- coding: utf-8 -*-
"""概念行登记必须把 `kind` 传进 `bits_of`：三条判据 + 一条反真空。

## 现场（`draft/152` 之二，真机 r34d 逐字复现过）

`agent_b/register_statement.py` 的生产端调 `evidencebits.bits_of(...)` 时没传 `kind`，
而落盘那一关（`schema.Statement.validate`）走的是
`evidencebits.bits_shape_problems(self.bits, kind=self.kind)`，一定带着这一行的 `kind`
重算等级。`derive_grade` 对 `kind="concept"` 有一条短路（概念不参与等级链，等级现算成
`not_applicable`），于是：

- 生产端算出的等级是 `conjecture`（或引用命题那一条的 `pre_theorem`）；
- 校验端按 `kind="concept"` 重算出 `not_applicable`；
- 两者一比就判"等级不许自报" ⇒ 任何 `kind=concept` 的登记 100% 被拒。

真机读数（`projects/r34d/sessions/r34d.jsonl:240` 与 `:245`）两次都是同一句：

    落盘没成（ValueError: bits 不合规：bits.grade 写的是 'conjecture'，
    按五位现算是 'not_applicable' —— 等级不许自报（判据永远现算）：
    要么删掉这个键，要么让它等于现算值）⇒ 这一笔按'没写成'读

B 随后在 `:242` 改用通用写口 `table.create` 直写 statements（被 `store.direct_write_refusal`
拒）。所以这条缺陷的代价不只是 5 条隐性失败，还有 1 条 `direct_write` 的根因。

## 判据

① 真机那条 concept payload 原样喂一次 ⇒ 落盘、等级 `not_applicable`（改前：被拒）；
② 别的 kind 行为不变（`theorem` / `lemma` / `definition` / 空串 的五个位逐字相同）；
③ 反真空：把 `kind` 打桩成空（= 改前那次调用）⇒ ① 必红，且红在"等级不许自报"那一句。
"""
from __future__ import annotations

import pytest

from agentflow import evidencebits as EB
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store

from conftest import add_literature, write_library_file

#: 真机 `r34d` 第 240 行那一步的 `payload.args`，逐字照抄。
#:
#: 只去掉 `why` 这一个键：它不是动作的参数，原生面解码时由 `ToolFace.to_shape`
#: 从参数里摘出来（`why = str(args.pop("why", ""))`），所以到达动作的正是这一份。
REAL_R34D_CONCEPT = {
    "evidence_kind": "heuristic",
    "kind": "concept",
    "label": "红色互连集 / 蓝色互连集（red / blue interconnected set）",
    "origin": "external_lit",
    "page_range": {"end": 2, "start": 2},
    "quote_mode": "verbatim",
    "quote_verified": True,
    "source_lit_id": "000000",
    "statement_full": (
        "定义（红色互连集 / 蓝色互连集，red interconnected set / blue interconnected "
        "set）。前提假设：给定顶点集 V，把完全图的每条边（每对顶点之间的线段）恰好染成"
        "红、蓝两色之一（即原文所谓 chromatic graph）。在此前提下，对任意顶点子集 "
        "K ⊆ V：若 K 中任意两个顶点之间的线段全部为红色，则称 K 为红色互连集；若全部为"
        "蓝色，则称 K 为蓝色互连集。后文所有二色结论（含 w(3,4)=9）都以这两个术语陈述"
        "上界与下界两面。"),
    "statement_text": (
        "For convenience, a set of vertices K will be said to be a red interconnected set "
        "if all segments joining pairs of vertices in K are colored red."),
}

#: 那一篇原文（`library/000000/a.txt`）：引文必须真的在盘上，`_quote_doc` 才打得到全文。
PAPER = (
    "For convenience, a set of vertices K will be said to be a red interconnected set "
    "if all segments joining pairs of vertices in K are colored red.")


def _store_with_paper(store: Store) -> Store:
    """一个带 `literature 000000` 与其全文的临时工作区（真机那一篇的替身）。"""
    write_library_file(store, "000000/a.txt", PAPER + "\n")
    add_literature(store, "000000", title="Combinatorial Relations and Chromatic Graphs",
                   path="000000/a.txt")
    return store


def _agent_b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


# ============================================================ ① 真机 payload 能过


def test_the_real_r34d_concept_payload_lands_with_grade_not_applicable(store: Store):
    """① 正控：r34d 那条概念登记原样喂一次 ⇒ 落盘，`bits.grade` 是 `not_applicable`。

    改前红：同一条 payload 返回 `ok=False`，`reason` 逐字是"bits 不合规：bits.grade
    写的是 'conjecture'，按五位现算是 'not_applicable'"（真机 :240 / :245 两次）。
    """
    _store_with_paper(store)
    out = _agent_b(store).register_statement(**REAL_R34D_CONCEPT)
    assert out.get("ok") is True, out
    assert "bits 不合规" not in str(out.get("error") or ""), out
    assert not out.get("refused") and not out.get("kind"), out
    stmt_id = str(out.get("stmt_id") or "")
    assert stmt_id, out
    (row,) = [r for r in _rows(store) if str(r.get("stmt_id")) == stmt_id]
    assert str(row.get("kind")) == "concept", row
    bits = dict(row.get("bits") or {})
    assert str(bits.get("grade")) == EB.GRADE_NOT_APPLICABLE, (
        f"概念行的等级必须是 {EB.GRADE_NOT_APPLICABLE!r}（不参与等级链）：{bits}")
    # 落盘那一关此刻会重走一次（`schema.Statement.validate` 的那一句），必须零问题
    assert EB.bits_shape_problems(bits, kind="concept") == [], bits


def test_a_concept_registration_does_not_carry_a_proof_text(store: Store):
    """① 的第二半：概念行落盘时 `proof_text` 仍为空（kind 传对了，概念那一支没退化）。

    这一条盯的是"修 kind 时顺手把概念行的证明栏塞上"那种反弹：概念不参与等级链，
    它没有"有没有证明"这一档。
    """
    _store_with_paper(store)
    out = _agent_b(store).register_statement(**REAL_R34D_CONCEPT)
    assert out.get("ok") is True, out
    (row,) = [r for r in _rows(store) if str(r.get("stmt_id")) == str(out.get("stmt_id"))]
    assert str(row.get("proof_text") or "") == "", row


# ============================================================ ② 其它 kind 不变


@pytest.mark.parametrize("kind", ["theorem", "lemma", "definition", "conjecture"])
def test_other_kinds_land_with_the_same_grade_as_before(kind: str, store: Store):
    """② 正控：非概念 kind 的落盘等级仍是 `pre_theorem`（与改前逐字相同）。

    `evidencebits.derive_grade` 只在 `concept` 那一支看 `kind`，所以把 `kind` 传进
    `bits_of` 对别的 kind 应当一个字都不动。这条走的是动作面（落盘那一行），因此
    它不依赖生产端那个新形参的签名 —— 改前改后都该是绿的：真正的"不变"读数。
    """
    _store_with_paper(store)
    payload = dict(REAL_R34D_CONCEPT)
    payload["kind"] = kind
    payload["label"] = f"{kind} 的那一行"
    # 给一段真在盘上的引文：第 2+3 位靠"引文回验通过"撑起来，等级才是 `pre_theorem`
    # （概念那一档的 `not_applicable` 短路不在这里发生）。
    payload["proof_text"] = PAPER
    out = _agent_b(store).register_statement(**payload)
    assert out.get("ok") is True, out
    (row,) = [r for r in _rows(store) if str(r.get("stmt_id")) == str(out.get("stmt_id"))]
    assert str(row.get("kind")) == kind, row
    bits = dict(row.get("bits") or {})
    assert str(bits.get("grade")) == "pre_theorem", row
    assert EB.bits_shape_problems(bits, kind=kind) == [], row


def test_theorem_and_definition_rows_get_byte_identical_evidence_bits(store: Store):
    """② 的第二半：同一条内容、只换 `theorem` 与 `definition` ⇒ 五个位逐字相同。

    这条是"kind 没有混进非概念行"的机器读数：两行的 `bits` 必须相等（等级相同、
    凭据相同），只有 `kind` 那一格不同。
    """
    _store_with_paper(store)
    seen: dict[str, dict] = {}
    for kind in ("theorem", "definition"):
        payload = dict(REAL_R34D_CONCEPT)
        payload["kind"] = kind
        payload["label"] = f"{kind} 的那一行"
        # 正文各带一个不同的尾注：秘书按规范化后的正文查重，同一条正文两次登记会
        # 折成 `duplicate_statement`。尾注不进五个位，所以下面那一比仍然有意义。
        payload["statement_full"] = REAL_R34D_CONCEPT["statement_full"] + f"（{kind}）"
        payload["proof_text"] = PAPER
        out = _agent_b(store).register_statement(**payload)
        assert out.get("ok") is True, out
        (row,) = [r for r in _rows(store)
                  if str(r.get("stmt_id")) == str(out.get("stmt_id"))]
        seen[kind] = dict(row.get("bits") or {})
    assert seen["theorem"] == seen["definition"], seen


# ============================================================ ③ 反真空


def test_negative_control_dropping_the_kind_turns_the_concept_registration_red(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """③ 反真空：把 `kind` 从 `bits_of` 那一次调用里拿掉 ⇒ ① 必红。

    这一格打桩的是"改前那次调用"本身（同一个函数、同一个输入，只少一个 `kind`），
    不是重写一份判据：它证明 ① 之所以能红，是因为这一条传参真的进了等级现算。
    红出来的是判据那一句原话（"等级不许自报"），而不是别的拒绝。
    """
    import agentflow.agent_b.register_statement as RS

    real_bits_of = RS._EB.bits_of

    def _kindless(**kwargs):
        kwargs.pop("kind", None)
        return real_bits_of(**kwargs)

    _store_with_paper(store)
    monkeypatch.setattr(RS._EB, "bits_of", _kindless)
    out = _agent_b(store).register_statement(**REAL_R34D_CONCEPT)
    assert out.get("ok") is False, out
    error = str(out.get("error") or "")
    assert "等级不许自报" in error, error
    assert "not_applicable" in error, error
    # 两种落点都是同一句判据：本地形状关（`bad_bits`）先拦，或者秘书落盘时
    # `schema.Statement.validate` 抛 ValueError 再被折成 `write_failed`。
    assert str(out.get("kind") or "") in ("bad_bits", "write_failed"), out
    assert not _rows(store), "被拒的那一笔不许留下半行"


def test_the_kind_reaches_bits_of_instead_of_being_swallowed_by_the_signature(
        store: Store, monkeypatch: pytest.MonkeyPatch):
    """③ 的第二半：传上去的 `kind` 真的到了 `bits_of`（而不是被形参截住）。

    只把签名改成"收一个 kind"、调用处却仍不传，是这次缺陷最像的复发形态：参数在、
    值没到。这里在 `bits_of` 上装一只探针，直接看它收到的是什么。
    """
    import agentflow.agent_b.register_statement as RS

    real_bits_of = RS._EB.bits_of
    seen: list[str] = []

    def _spy(**kwargs):
        seen.append(str(kwargs.get("kind") or ""))
        return real_bits_of(**kwargs)

    _store_with_paper(store)
    monkeypatch.setattr(RS._EB, "bits_of", _spy)
    out = _agent_b(store).register_statement(**REAL_R34D_CONCEPT)
    assert out.get("ok") is True, out
    assert seen == ["concept"], seen
