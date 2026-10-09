# -*- coding: utf-8 -*-
"""S1r 的迁移计划：`concepts` 并进 `statements` 之前，先把"会长成什么样"算出来。

业主 2026-10-09：「concept表真并进statements……并表了就并干净」。并表要动的是磁盘格式
（`SCHEMA_VERSION 1→2`、`TABLES` 删 `concepts`、"读侧统一新标准"），所以它必须
一次做完；而它一旦做错就是不可逆的（`AGENTS.md`：迁移 = 错误不可逆的七类之一）。
于是顺序定成：先把计划算出来（纯函数、可复算、可在真盘上只读预演），
再照抄进 `store.rebuild` 那一笔（`draft/97` §13.2 / §15.2）。

## 这一组守什么

`plan_migration` 与将来的 `store.rebuild` 共用 `fold_concepts` / `remap_concept_ids`
两个内核 —— 判据因此分两半：

1. 计划本身对（正控三条）；
2. 计划的读数能分辨"算过了、没问题"与"算过了、有这些边界"（负控 + 反真空）：
   号冲突要点名（靠分配器跳号解决）、悬空概念号要点名并保留、定义待补要逐条标出来，
   而 0 条概念时必须明说 0（不是沉默）。
"""

from __future__ import annotations

from agentflow import migrate_concepts as M
from agentflow import schema as S


def _concept(cid: str, name: str, definition: str = "d", **kw) -> dict:
    return {"concept_id": cid, "name": name, "definition": definition,
            "aliases": [], "definition_source_lit_id": "", "created_at": "2026-10-09T00:00:00+08:00",
            **kw}


def _relation(rid: str, *cids: str) -> dict:
    return {"rel_id": rid, "concept_ids": list(cids), "kind": "related",
            "created_at": "2026-10-09T00:00:00+08:00"}


# ==================================================== 一、计划本身（正控）

def test_the_plan_folds_concepts_and_remaps_relations():
    """两张概念行 ⇒ 两条 `statements` 行（`kind="concept"`）+ 关系改号逐条落账。"""
    plan = M.plan_migration([_concept("0000", "谱"), _concept("0001", "区间")],
                            [_relation("0000", "0000", "0001")],
                            existing_stmt_ids=["0005"], start=0)
    counts = plan["counts"]
    assert counts["concepts"] == 2 and counts["relations"] == 1, counts
    assert counts["renumbered"] == count_renumbered(plan), counts
    rows = {s["stmt_id"]: s for s in plan["statements"]}
    assert len(rows) == 2 and set(rows) == set(plan["id_map"].values())
    for row in rows.values():
        assert row["kind"] == "concept" and row["origin"] == "own_result", row
        assert row["proof_text"] == M.PRIMITIVE_PROOF, row
        assert row["quote_reason"].strip(), "quote_verified 不是 True ⇒ 必须有理由"
    # 关系里的号跟着改（改一条就够：`relations_changed` 只数"真的换了号"的那些）
    rel = plan["relations"][0]
    assert rel["concept_ids"] == sorted(plan["id_map"][c] for c in ("0000", "0001")), rel
    assert counts["relations_changed"] == len(plan["changed"]) >= 0
    # 账要能逐条复算：每个概念一行 + 一条汇总
    ledger = plan["ledger"]
    assert [r["kind"] for r in ledger] == ["concept→statement"] * 2 + ["summary"]
    assert ledger[0]["old_id"] == "0000" and ledger[0]["new_id"] == plan["id_map"]["0000"]
    assert ledger[-1]["concepts"] == 2 and ledger[-1]["relations"] == 1


def count_renumbered(plan: dict) -> int:
    return sum(1 for o, n in plan["id_map"].items() if str(o) != str(n))


def test_the_plan_is_deterministic():
    """同一份输入算两次 ⇒ 逐字相同（预演与真跑共用一套口径的前提）。"""
    args = ([_concept("0000", "谱"), _concept("0001", "区间"), _concept("0002", "群")],
            [_relation("0000", "0000", "0002")])
    one = M.plan_migration(*args, existing_stmt_ids=["0001"], start=0)
    two = M.plan_migration(*args, existing_stmt_ids=["0001"], start=0)
    assert one == two, "计划必须是确定性的：算两次不一样 ⇒ '预演'与'真跑'不是同一件事"
    # 反真空：跳过被占的号这件事真的发生了（否则这条判据在"没有冲突"时是空的）
    assert "0001" in one["collisions"] and one["id_map"]["0001"] != "0001"


def test_an_empty_workspace_says_zero_instead_of_saying_nothing():
    """反真空：0 条概念 ⇒ 读数里明说 0（沉默会被读成"没问题"），且一行都不编出来。"""
    plan = M.plan_migration([], [], existing_stmt_ids=[], start=0)
    assert plan["statements"] == [] and plan["relations"] == []
    assert plan["counts"]["concepts"] == 0 and plan["counts"]["pending_search"] == 0
    assert plan["ledger"] == [{"kind": "summary", **plan["counts"]}], plan["ledger"]


# ==================================================== 二、边界读数（负控）

def test_a_concept_id_that_collides_is_renumbered_not_overwritten():
    """概念号与既有命题号撞上 ⇒ 换一个新号（不许覆盖），并在读数里点名。"""
    plan = M.plan_migration([_concept("0007", "谱")], [], existing_stmt_ids=["0007"])
    assert plan["collisions"] == ["0007"]
    new_id = plan["id_map"]["0007"]
    assert new_id != "0007", "撞号必须换号：按主键 upsert 会静默顶掉既有那一行"
    assert plan["counts"]["collisions_with_existing_statements"] == 1
    assert plan["counts"]["renumbered"] == 1


def test_a_dangling_concept_id_is_named_and_kept():
    """关系表挂着概念表里没有的号 ⇒ 点名 + 原样保留（丢掉它等于让那件事消失）。"""
    plan = M.plan_migration([_concept("0000", "谱")], [_relation("0000", "0000", "9999")])
    assert plan["counts"]["dangling_concept_ids"] == 1
    assert plan["missing"] == [("0000", "9999")], plan["missing"]
    assert "9999" in plan["relations"][0]["concept_ids"], "悬空号不许被删掉"
    ops = [r["op"] for r in M.ledger_lines(plan)]
    assert "relation_dangling_concept_id" in ops and ops[-1] == "relation_dangling_concept_id"


def test_a_definition_that_is_missing_is_marked_not_invented():
    """定义空着 ⇒ `pending_definition` + 待补标记（`D12` 甲），不编良定义性证明。"""
    plan = M.plan_migration([_concept("0000", "新概念", definition="")], [])
    row = plan["statements"][0]
    assert row["status"] == "pending_definition" and row["statement_full"] == ""
    assert M.PENDING_SEARCH in row["quote_reason"], row["quote_reason"]
    assert plan["counts"]["pending_search"] == 1
    assert plan["pending"][0]["concept_id"] == "0000"
    for word in ("证明", "Proof", "proof"):
        assert word not in row["proof_text"], "迁移不许给概念编良定义性证明"
    # 反真空的另一半：定义有的时候就该是 active（否则这一档永远不可达）
    ok = M.plan_migration([_concept("0000", "谱", definition="矩阵的谱")], [])
    assert ok["statements"][0]["status"] == "active"
    assert ok["counts"]["pending_search"] == 0


def test_duplicate_names_are_counted_on_the_way_in():
    """并表之后"同名两条"从两个表的常态变成同一张表里的重名 ⇒ 读数里先点名。"""
    plan = M.plan_migration([_concept("0000", "谱"), _concept("0001", " 谱 ")], [])
    assert plan["counts"]["duplicate_names"] == 1
    assert list(plan["duplicate_names"].values()) == [["0000", "0001"]]
    # 反真空：不同名的两条不算重复
    other = M.plan_migration([_concept("0000", "谱"), _concept("0001", "区间")], [])
    assert other["counts"]["duplicate_names"] == 0


def test_the_folded_rows_are_valid_statements():
    """折出来的行必须过 `Statement.validate()`（迁移不能靠"重建时没人校验"混过去）。"""
    plan = M.plan_migration([_concept("0000", "谱"), _concept("0001", "新概念", definition="")],
                            [])
    for row in plan["statements"]:
        obj = S.row_from_dict("statements", row)
        obj.validate()
        assert obj.status in S.STATEMENT_STATUSES
        assert (obj.status == "pending_definition") == (obj.statement_full == "")
