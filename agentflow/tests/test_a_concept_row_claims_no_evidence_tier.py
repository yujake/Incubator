# -*- coding: utf-8 -*-
"""② 概念行的 `evidence_kind` 不是"证据档"（审计 §6-②：档位自报的残留）。

## 改前读数（`temp/_fix_concept_probe_before.json` 的 `2_evidence_kind`）

```
kind=concept / bits.grade=not_applicable / proof_text=""（0 字）
evidence_kind = "cross_check"      ← 调用方的缺省值原样落盘
evidencebits.kind_from_bits(bits, kind="concept") = ""（反算不出来）
```

`cross_check` 的定义是"数值 / 穷举交叉验证，不构成证明"（`schema.EVIDENCE_KINDS` 那句），
而这一行五位一件没做（`proof=false` / `reviewed=false`）。于是 `table.get` / 报告里
读这一格的人会得到"交叉核对过" —— 那是"档位自报"在概念这一档的残留。

## 改后口径

档位是等级的历史别名，唯一反算口是 `evidencebits.kind_from_bits`：概念行经
`derive_grade` 短路成 `not_applicable` ⇒ 反算给空串（"反算不出来就不写"）。空串不是
`schema.EVIDENCE_KINDS` 的值（`Statement.validate` 会拒），所以落词表里最弱的那一档
（`GRADE_TO_KIND["conjecture"] = "heuristic"`）—— 它与概念行现有唯一构造口
`conceptrows.concept_statement` 逐字同一个值，不声称任何一件证据位做过。

## 四条判据（含一条反真空、一条"不许溢出"）

| 条 | 它钉什么 | 改前红在哪 |
|---|---|---|
| a | 概念行落 `heuristic`；它等于"反算口的值（空串）落词表最弱档"；等级仍是 `not_applicable` | 改前落 `cross_check` |
| b | 调用方显式交 `cross_check` ⇒ 概念行仍落 `heuristic`（这一列不是调用方能声明的东西） | 改前跟着调用方走 |
| c | 反真空：把 `_concept_evidence_kind` 打桩成 `"cross_check"`（= 改前）⇒ a 的尺子当场红 | 证明 a 的绿是这一处反算带来的 |
| d | 不许溢出：命题行（conjecture）交 `cross_check` 仍落 `cross_check`（这一改只动概念那一档） | 改后不许把命题行的口径一起改掉 |
| e | 另一个写口（秘书载荷里的 `concepts`）落的概念行同样是 `heuristic` —— "概念行不会出现 `cross_check` / `proof` 这类档位"在两条写口上都成立 | 只改一处会在这里露出来 |

零真实模型调用：`extractor=None`、`extract_text=extract_text`；概念走 `register_statement`
与秘书载荷两条既有的写入口，工作区全在 `tmp_path`。
"""
from __future__ import annotations

import pytest

from agentflow import conceptrows as CR
from agentflow import evidencebits as EB
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store

from conftest import add_literature, write_library_file

PAPER = ("For convenience, a set of vertices K will be said to be a red interconnected "
         "set if all segments joining pairs of vertices in K are colored red.")

CONCEPT = {
    "kind": "concept",
    "label": "红色互连集（red interconnected set）",
    "origin": "external_lit",
    "source_lit_id": "000000",
    "page_range": {"start": 1, "end": 1},
    "quote_mode": "verbatim",
    "quote_verified": True,
    "statement_full": (
        "定义（红色互连集，red interconnected set）。给定顶点集 V，把完全图的每条边恰好"
        "染成红、蓝两色之一：若顶点子集 K 中任意两点之间的线段全部为红色，则称 K 为"
        "红色互连集。"),
    "statement_text": "a set of vertices K is a red interconnected set if all segments "
                      "joining pairs of vertices in K are colored red.",
}

#: 概念行不许出现的档位（前两档声称"有证明 / 有审阅"，第三档声称"交叉核对过"）。
PROOF_TIERS = ("proof", "proof_review", "cross_check")


def _prepared(store: Store) -> Store:
    write_library_file(store, "000000/a.txt", PAPER + "\n")
    add_literature(store, "000000", title="Combinatorial Relations and Chromatic Graphs",
                   path="000000/a.txt")
    return store


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _concept_row(store: Store) -> dict:
    rows = [r for r in _rows(store) if str(r.get("kind") or "") == "concept"]
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------- 尺子


def _assert_no_evidence_tier(row: dict) -> None:
    """a/b/e 的尺子：概念行的档位就是"反算不出来"落词表最弱那一档，不许是证据档。

    三件缺一不可：

    ① 不是 `cross_check` / `proof_review` / `proof` —— 这三档各自声称某件证据位做过；
    ② 与"反算口 + 词表最弱档"逐字一致（`kind_from_bits(...)` 为空串 ⇒ `heuristic`）：
       这样它就不是"另一个自报值"，而是同一条反算规则在概念这一档的落点；
    ③ 该行仍然没有证据位（`proof` / `reviewed` 为假、等级 `not_applicable`）——
       否则"档位弱"与"其实做了证据"会同时成立，读数还是假的。
    """
    kind = str(row.get("kind") or "")
    assert kind == "concept", f"这把尺子只量概念行：{kind!r}"
    got = str(row.get("evidence_kind") or "")
    assert got not in PROOF_TIERS, (
        f"概念行落成了证据档 {got!r} —— 而它五位一件没做：{row.get('bits')}")
    bits = dict(row.get("bits") or {})
    expected = (EB.kind_from_bits(bits, kind=kind)
                or EB.GRADE_TO_KIND["conjecture"])
    assert got == expected, (
        f"概念行的档位不是由等级反算出来的那一档：实得 {got!r}，反算 {expected!r}")
    assert bits.get("proof") is False, f"概念行不该有证明位：{bits}"
    assert bits.get("reviewed") is False, f"概念行不该有审阅位：{bits}"
    assert str(bits.get("grade")) == EB.GRADE_NOT_APPLICABLE, bits


# ================================================================ a 正控


def test_a_a_concept_row_lands_the_weakest_tier_instead_of_cross_check(store: Store) -> None:
    """a：概念行落 `heuristic`（词表最弱那一档），等级仍是"不适用"。

    改前读数：`evidence_kind="cross_check"`（`table.get` / 报告据此读成"交叉核对过"）。
    """
    _prepared(store)
    out = _b(store).register_statement(**CONCEPT)
    assert out.get("ok") is True, out
    row = _concept_row(store)
    _assert_no_evidence_tier(row)
    assert str(row.get("evidence_kind")) == "heuristic", row
    assert str(row.get("proof_text") or "") == "", row


# ================================================================ b 调用方说了不算


def test_b_the_caller_cannot_claim_a_tier_for_a_concept(store: Store) -> None:
    """b：调用方显式交 `cross_check` ⇒ 概念行仍落 `heuristic`。

    这一列按 `evidencebits` 的口径「不是」调用方能声明的东西（"任何调用方拿提交方声明的
    档位来写这一列，都是第二套真值"）。改前它跟着调用方走（缺省值就是 `cross_check`），
    于是"档位自报"在概念这一档原样落盘。
    """
    _prepared(store)
    out = _b(store).register_statement(**dict(CONCEPT, evidence_kind="cross_check"))
    assert out.get("ok") is True, out
    row = _concept_row(store)
    _assert_no_evidence_tier(row)
    assert str(row.get("evidence_kind")) == "heuristic", row


# ================================================================ c 反真空


def test_c_negative_control_writing_the_tier_back_turns_the_criterion_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：把 `_concept_evidence_kind` 打桩成 `"cross_check"`（= 改前）⇒ a 的尺子红。

    打桩的是判据本体（那一处唯一算点），不是重写一份夹具：于是这一笔走的正是改前那条
    "跟着调用方走"的路。红出来之后还要能看到"那一行真的落了 `cross_check`"——
    否则红可能来自别的拒绝，而不是来自这一格。
    """
    import agentflow.agent_b.register_statement as RS

    _prepared(store)
    monkeypatch.setattr(RS, "_concept_evidence_kind", lambda bits: "cross_check")
    out = _b(store).register_statement(**CONCEPT)
    assert out.get("ok") is True, out
    row = _concept_row(store)
    assert str(row.get("evidence_kind")) == "cross_check", (
        "打桩没有改变落盘的那一格 ⇒ c 证明不了 a 的红")
    with pytest.raises(AssertionError):
        _assert_no_evidence_tier(row)


# ================================================================ d 不许溢出


def test_d_proposition_rows_keep_the_tier_the_caller_gave(store: Store) -> None:
    """d：命题行（conjecture）交 `cross_check` 仍落 `cross_check`。

    这一改只动概念那一档：其他 kind 的档位行为一个字都不许变（那里 `cross_check`
    是真的有一份数值 / 穷举交叉验证时用的档）。
    """
    _prepared(store)
    theorem = {
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        "kind": "conjecture", "label": "红色互连集的存在性", "origin": "own_result", "derived_from": ["999999"],
        "statement_full": "设完全图的边被红蓝二染色；则存在一个二元红色互连集。",
        "evidence_kind": "cross_check",
        # 自产那一档必须写清"没回验 / 为什么"，以及正文与出处的那几格。
        "quote_reason": "自产（own_result）：没有外部引文可回验，故 quote_verified 留 None",
        "line_range": {"start": 1, "end": 1},
    }
    out = _b(store).register_statement(**theorem)
    assert out.get("ok") is True, out
    (row,) = _rows(store)
    assert str(row.get("kind")) == "conjecture", row
    assert str(row.get("evidence_kind")) == "cross_check", row


# ================================================================ e 另一个写口


def test_e_the_secretary_concept_mouth_lands_the_same_tier(store: Store) -> None:
    """e：秘书载荷里的 `concepts`（真机 mp3 的写侧）落的概念行同样是 `heuristic`。

    两个写口（`B.register_statement(kind="concept")` 与秘书载荷 `concepts`）都算"概念行"，
    所以"概念行不会出现 `cross_check` / `proof` 这类档位"这条判据要在两处都成立 ——
    只改一处的话，另一处会在这里露出来。
    """
    from agentflow.secretary import Secretary

    _prepared(store)
    sec = Secretary("B", root=store.root, store=store)
    got = sec.record_statement(
        {"statement_full": "定理：对任意群 G，命题 ph 成立。", "kind": "theorem",
         "origin": "external_lit", "source_lit_id": "000000",
         "page_range": {"start": 1, "end": 1},
         "quote_verified": True, "quote_mode": "verbatim",
         "concepts": [{"name": "电导", "definition": "边上权重的倒数",
                       "source_lit_id": "000000"}]},
        role="B")
    assert got.get("created"), got
    row = _concept_row(store)
    _assert_no_evidence_tier(row)
    # 反真空的边界：这一条不是靠"所有概念行都还没写"绿的 —— 它真在这一格里
    assert str(row.get("stmt_id") or ""), row
    assert str(row.get("evidence_kind")) == "heuristic", row
    # 与概念行的唯一构造口同一个值（两条写口不许各说一套）
    built = CR.concept_statement(stmt_id="000099", label="电导", definition="边上权重的倒数",
                                 source_lit_id="000000")
    assert built.evidence_kind == row.get("evidence_kind"), (built.evidence_kind,
                                                             row.get("evidence_kind"))
