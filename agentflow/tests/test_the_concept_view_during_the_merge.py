# -*- coding: utf-8 -*-
"""并表过渡期的概念行读写口（`conceptrows`）：两处同号合并。

`concepts` 要并进 `statements`（`kind="concept"`），而这意味着动磁盘格式
（`SCHEMA_VERSION 1→2`、`TABLES` 删表）—— 属于"错误不可逆"的那一类
（`AGENTS.md` 七类之一）。所以中间必须有一层过渡，让读侧一个一个搬：
写的时候新标准先写、老表照旧镜像（同号），读的时候合成一个视图（新标准优先）。

## 这一组守什么

- 正控：写一条概念 ⇒ 两张表各一份、号相同、视图里只出现一次（`via="statements"`）；
  老写侧（B 的 pipeline 还没搬）写的行，视图照样看得到（折成新形状，`via="legacy"`）；
  秘书那条路也一样（B 的写入在两种表示里都在）。
- 负控：迁移之后老文件还留在盘上 ⇒ 必须点名（`stale_file`，它装着没搬完的行）；
  "新标准那行还空着定义、老行有" ⇒ 记成读数（`definition_only_in_legacy`），
  不自动合并（新标准优先）；老表读不成 ⇒ `checked=False`（不是"只有一边"）。
- 反真空：新工作区（老表文件还没建）也要镜像 —— `present` 判的是"这一版代码还认不认
  老表"，不是"文件在不在"（拿文件判会把'还没写过概念'读成'过渡期结束了'，
  而两种情形在盘上一模一样）；空库的读数要明说 0。
"""

from __future__ import annotations

import json

from conftest import TS, sync_counters
from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import secretary as SEC


def _legacy_rows(store) -> list[dict]:
    return list(store.rows(CR.LEGACY_TABLE))


def _stmt_rows(store) -> list[dict]:
    return list(store.rows("statements"))


def _legacy_write(store, cid: str, name: str, definition: str = "") -> dict:
    """模拟"还没搬完的老写侧"（B 的 pipeline 今天就是直接往 `concepts` 写）。"""
    row = S.Concept(concept_id=cid, name=name, definition=definition,
                    related_concepts=[], normalized_name=name, created_at=TS, updated_at=TS)
    row.validate()
    with store.tx(CR.LEGACY_TABLE, actor="test") as tx:
        tx.upsert(CR.LEGACY_TABLE, row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ==================================================== 一、两处同号（正控）

def test_a_new_concept_lands_in_both_tables_with_one_identity(store):
    """写一条概念 ⇒ 两张表各一份、号相同；视图里只出现一次（新标准优先）。"""
    out = CR.upsert(store, label="谱", definition="矩阵的谱", aliases=["spectrum"])
    assert out["checked"] and out["mirrored"], out
    assert out["tables"] == ["statements", CR.LEGACY_TABLE], out["tables"]
    stmts, legacy = _stmt_rows(store), _legacy_rows(store)
    assert len(stmts) == 1 and len(legacy) == 1
    assert stmts[0]["stmt_id"] == legacy[0]["concept_id"] == out["stmt_id"], (
        "两处同号是这一层的契约：不同号 ⇒ 读的人会把同一个概念数两遍")
    assert stmts[0]["kind"] == "concept" and stmts[0]["label"] == "谱"
    assert legacy[0]["name"] == "谱" and legacy[0]["definition"] == "矩阵的谱"

    view = CR.view(store)
    assert view["checked"] and len(view["rows"]) == 1, view["rows"]
    assert view["rows"][0]["via"] == "statements"
    assert view["counts"] == {"statements": 1, "legacy": 1, "merged": 1, "legacy_only": 0,
                              "definition_only_in_legacy": 0}, view["counts"]


def test_a_row_only_the_old_writer_knows_about_is_still_visible(store):
    """还没搬完的老写侧写进老表 ⇒ 视图照样看得到（折成新形状，逐行标 `via`）。"""
    _legacy_write(store, "0007", "老概念", definition="老定义")
    view = CR.view(store)
    assert view["checked"] and view["counts"]["legacy_only"] == 1, view["counts"]
    row = view["rows"][0]
    assert row["stmt_id"] == "0007" and row["via"] == "legacy"
    assert row["label"] == "老概念" and row["statement_full"] == "老定义"
    assert row["kind"] == "concept" and row["status"] == "active"
    # 反真空的另一半：空定义的老行折出来是"待补"（不是"定义就是空的"）
    _legacy_write(store, "0008", "没定义的老概念")
    view = CR.view(store)
    pending = [r for r in view["rows"] if r["stmt_id"] == "0008"][0]
    assert pending["status"] == "pending_definition"
    assert "concept:pending_search" in pending["quote_reason"], pending["quote_reason"]


def test_the_secretary_mirrors_the_concepts_it_writes(store):
    """秘书那条路（B 交内容）也两处同号 —— 老读侧立刻看得到新写进来的概念。"""
    sec = SEC.Secretary("B", root=store.root, store=store)
    out = sec.record_statement(
        {"origin": "own_result", "kind": "concept", "label": "电导",
         "statement_full": "边上权重的倒数", "proof_text": "concept:primitive",
         "quote_reason": "原始概念", "evidence_kind": "heuristic"}, role="B")
    assert out["checked"] and out["created"], out
    sid = out["stmt_id"]
    assert [r["stmt_id"] for r in _stmt_rows(store)] == [sid]
    assert [r["concept_id"] for r in _legacy_rows(store)] == [sid], "镜像没写或号不同"
    assert CR.view(store)["counts"]["merged"] == 1


# ==================================================== 二、迁移前后的三态（负控）

def test_after_the_flip_a_leftover_file_is_named(store, monkeypatch):
    """迁移之后：老表从 `TABLES` 里消失，而盘上那份老文件必须被点名。"""
    CR.upsert(store, label="谱", definition="矩阵的谱")
    assert CR.legacy_present(store)["present"] is True
    monkeypatch.delitem(S.TABLES, CR.LEGACY_TABLE)      # 模拟迁移那一笔（删表）
    state = CR.legacy_present(store)
    assert state["checked"] and state["present"] is False and state["stale_file"] is True, state
    assert "还没搬完" in state["reason"] or "老文件" in state["reason"], state["reason"]
    view = CR.view(store)
    assert view["checked"], view
    assert view["reason"], "残留文件这件事必须在视图读数里看得见"
    assert view["counts"]["statements"] == 1 and view["counts"]["legacy"] == 0
    assert all(r["via"] == "statements" for r in view["rows"])


def test_a_definition_only_in_the_old_table_is_a_reading_not_a_silent_merge(store):
    """新标准那行空着定义、老行有 ⇒ 记读数（新标准优先，不自动抹平差异）。"""
    out = CR.upsert(store, label="谱")                    # 定义待补
    sid = out["stmt_id"]
    with store.tx(CR.LEGACY_TABLE, actor="test") as tx:
        row = S.Concept(concept_id=sid, name="谱", definition="矩阵的谱",
                        related_concepts=[], normalized_name="谱", created_at=TS, updated_at=TS)
        row.validate()
        tx.upsert(CR.LEGACY_TABLE, row.to_dict())
    view = CR.view(store)
    assert view["counts"]["merged"] == 1, view["counts"]
    assert view["counts"]["definition_only_in_legacy"] == 1, view["counts"]
    row = view["rows"][0]
    assert row["via"] == "statements" and row["statement_full"] == "", (
        "新标准优先：差异记成读数，不自动把老行的定义搬过来")


def test_an_unreadable_old_table_is_not_read_as_only_one_side(store):
    """老表读不成 ⇒ `checked=False` + 理由（"没查成"不许折成"只有一边"）。"""
    CR.upsert(store, label="谱", definition="矩阵的谱")
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    view = CR.view(store)
    assert view["checked"] is False and view["rows"] == [], view
    assert "老表读不成" in view["reason"], view["reason"]
    state = CR.legacy_present(store)
    assert state["checked"] is True, "文件在不在还是判得了的（读不成的是内容）"


# ==================================================== 三、反真空

def test_a_fresh_workspace_still_mirrors(tmp_path):
    """反真空：老表文件还没建的新工作区也要镜像（`present` 判的是"代码还认不认老表"）。

    刻意不用 `store` 夹具：那个夹具自己就带一份演示数据（老文件已经在盘上），
    而这一条问的正是"文件还不存在时"那一态。
    """
    from agentflow.store import Store

    root = tmp_path / "fresh-ws"
    store = Store(str(root))
    state = CR.legacy_present(store)
    assert state["checked"] and state["present"] is True and state["file"] is False, state
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    assert out["mirrored"], "新工作区没镜像 ⇒ 老读侧看不到这个概念，而盘上看起来一切正常"
    assert json.loads((store.data / "concepts.json").read_text(encoding="utf-8"))["rows"]


def test_an_empty_view_says_zero(store):
    """反真空：空库的读数要明说 0（沉默会被读成"没问题"）。"""
    view = CR.view(store)
    assert view["checked"] and view["rows"] == []
    assert set(view["counts"]) == {"statements", "legacy", "merged", "legacy_only",
                                  "definition_only_in_legacy"}
    assert all(v == 0 for v in view["counts"].values()), view["counts"]
