# -*- coding: utf-8 -*-
"""S1r-fold：`concepts` → `statements` 的折叠规则（纯函数，先于"真跑迁移"落地）。

业主 2026-10-09：「concept表真并进statements。由于你用"类型"标记了concept的身份，proof里就证这个概念为什么是良定义的」/「并表了就并干净」/「由于秘书会查重，D10的合并概念不会发生」
/「抽不到定义的概念就让A去网上搜，写入时定义内容留空，等A返回后写入；如果概念很基础，是数学基本概念，允许B自己写定义」。

判据（正控 2 / 负控 2 / 反真空 3）：

- 正控①：一条概念折成一条 `statements`（`kind="concept"`、`label=name`、
`statement_full=definition`、`aliases` 原样带过来），新号由分配器给（不是沿用旧号）；
- 正控②：`relations.concept_ids` 里的旧号被换成新号，改号逐条落账；
- 负控①：定义空着的行 ⇒ 落 `pending_search` 待补标记 + 进 `notes`（不许编定义），
且 `quote_reason` 非空（`Statement.validate` 的硬要求）；
- 负控②：迁移行不许出现"这是它的证明"那种字样（`proof_text` 只能是
`concept:primitive` 这一档；编一段良定义性证明 = 造假）；
- 反真空①：`merged_into` 非空的行走 `notes` 点名（并表后没有承载点，不静默丢）；
- 反真空②：关系表里挂着"概念表里没有的号" ⇒ 进 `missing` 点名，且原样留着
（丢掉会让"挂着一个不存在的号"这件事消失）；
- 反真空③：折叠出来的每一行都要过 `Statement.validate()`（形状受控，不是"先折了再说"）。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.migrate_concepts import (PENDING_DEFINITION, PENDING_SEARCH, PRIMITIVE_PROOF,
                                        fold_concepts, remap_concept_ids)

TS = "2026-10-09T00:00:00+08:00"


def _counter(start: int = 100):
    box = {"n": start}

    def _alloc() -> str:
        box["n"] += 1
        return f"{box['n']:04d}"

    return _alloc


def _concept(cid: str, name: str, definition: str = "", **kw) -> dict:
    row = {"concept_id": cid, "name": name, "definition": definition,
           "related_concepts": [], "normalized_name": name.lower(), "aliases": [],
           "definition_source_lit_id": "", "created_at": TS, "updated_at": TS}
    row.update(kw)
    return row


# ------------------------------------------------------------------ 正控


def test_a_concept_folds_into_a_statement_with_a_fresh_id():
    """正控①：折成 `kind="concept"` 的一行，新号由分配器给（业主 D2 的口径）。"""
    got = fold_concepts([_concept("0007", "Moore bound M(k, g)",
                                  "Moore 界：n ≥ 1 + k(1 + (k-1) + … )",
                                  aliases=["M(k, g)"], definition_source_lit_id="0009")],
                        alloc=_counter(100))
    (row,) = got["rows"]
    assert row["stmt_id"] == "0101" and row["kind"] == "concept"
    assert got["id_map"] == {"0007": "0101"}
    assert row["label"] == "Moore bound M(k, g)"
    assert row["statement_full"] == "Moore 界：n ≥ 1 + k(1 + (k-1) + … )"
    assert row["aliases"] == ["M(k, g)"] and row["source_lit_id"] == "0009"
    assert row["proof_text"] == PRIMITIVE_PROOF
    assert row["origin"] == "own_result" and row["quote_verified"] is None
    assert row["quote_reason"].strip(), "quote_verified=None ⇒ quote_reason 必须非空"
    assert got["pending_search"] == 0
    # `normalized_name` 丢弃这件事有读数（不是悄悄丢）—— 见反真空③
    assert any("normalized_name" in n for n in got["notes"]), got["notes"]
    # 反真空③：折出来的行必须真的过校验
    S.row_from_dict("statements", row).validate()


def test_relation_concept_ids_are_remapped_with_a_ledger():
    """正控②：关系里的旧号换成新号，改号逐条落账（业主：同表同分配器）。"""
    got = remap_concept_ids(
        [{"rel_id": "0001", "concept_ids": ["0007", "0008"]},
         {"rel_id": "0002", "concept_ids": ["0009"]}],
        {"0007": "0101", "0008": "0102"},
    )
    assert got["rows"][0]["concept_ids"] == ["0101", "0102"]      # 升序去重
    assert got["rows"][1]["concept_ids"] == ["0009"]              # 不在映射表 ⇒ 原样留着
    assert got["changed"] == [("0001", "0007", "0101"), ("0001", "0008", "0102")]
    assert got["missing"] == [("0002", "0009")]


# ------------------------------------------------------------------ 负控


def test_a_concept_without_a_definition_is_marked_pending_not_invented():
    """负控①：定义空着 ⇒ 落待补标记 + 点名，绝不编定义（业主的口径）。

    注意：这一行今天过不了 `Statement.validate()`（`active` 要求 `statement_full` 非空），
    而 schema.py 里有一条边界注释写着"为'待补'加一个 status 取值……那是人裁的事"
    ⇒ 折叠函数只把它标成 `pending_definition` 并列进待办（`pending`），
    最终落法等业主对 D12 点头（加取值 / 只落标记 / 延后建行）。
    """
    got = fold_concepts([_concept("0047", "diameter")], alloc=_counter())
    (row,) = got["rows"]
    assert row["statement_full"] == ""
    assert PENDING_SEARCH in row["quote_reason"]
    assert row["status"] == PENDING_DEFINITION, row["status"]
    assert got["pending_search"] == 1 and got["pending"][0]["concept_id"] == "0047"
    assert any("pending_search" in n for n in got["notes"])
    assert "编" not in row["statement_full"]


def test_a_migrated_row_never_carries_an_invented_proof():
    """负控②：`proof_text` 只能是 `concept:primitive`（编一段良定义性证明 = 造假）。"""
    got = fold_concepts([_concept("0091", "2-connected", "每个点对之间……")], alloc=_counter())
    (row,) = got["rows"]
    assert row["proof_text"] == PRIMITIVE_PROOF
    for bad in ("Proof", "证明", "证毕", "QED"):
        assert bad not in row["proof_text"], row["proof_text"]


# ------------------------------------------------------------------ 反真空


def test_a_merge_trace_is_named_not_dropped():
    """反真空①：`merged_into` 非空 ⇒ 进 `notes` 点名（并表后无承载点，不静默丢）。"""
    got = fold_concepts([_concept("0031", "perfect graph", "……",
                                  merged_into="0007", merge_reason="同一件事的两种叫法")],
                        alloc=_counter())
    assert got["rows"], got
    assert any("merged_into" in n for n in got["notes"]), got["notes"]
    assert any("merge_reason" in n for n in got["notes"]), got["notes"]


def test_a_dangling_concept_number_in_relations_is_named_and_kept():
    """反真空②：关系里挂着概念表没有的号 ⇒ `missing` 点名 + 原样留着。"""
    got = remap_concept_ids([{"rel_id": "0003", "concept_ids": ["9999"]}], {})
    assert got["missing"] == [("0003", "9999")], got
    assert got["rows"][0]["concept_ids"] == ["9999"], got["rows"]


def test_the_normalized_name_is_dropped_with_a_reading():
    """反真空③：`normalized_name` 一律丢弃，但要记一条读数（不是悄悄丢）。"""
    got = fold_concepts([_concept("0001", "Cage", "笼图")], alloc=_counter())
    assert "normalized_name" not in got["rows"][0], got["rows"][0].keys()
    assert any("normalized_name" in n for n in got["notes"]), got["notes"]


def test_a_row_without_a_concept_id_is_named_not_swallowed():
    """反真空③′：坏行（没有 `concept_id`）⇒ 进 `notes` 点名，不静默吞行。"""
    got = fold_concepts([{"name": "没有号的概念", "definition": "x"}], alloc=_counter())
    assert got["rows"] == [] and any("concept_id" in n for n in got["notes"]), got
