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

from conftest import TS, add_literature, sync_counters
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


# ==================================================== 四、写侧搬运（sync_from_legacy）

def test_an_edit_on_the_old_row_is_synced_to_the_new_standard(store):
    """改一条老行（不是新建）也要落到新标准 —— 只搬"新建"那一支是最容易漏的。"""
    # 老写侧先建（新标准还没有）
    with store.tx(CR.LEGACY_TABLE, "statements", actor="test") as tx:
        legacy = S.Concept(concept_id="0003", name="群", definition="",
                           related_concepts=[], normalized_name="群", aliases=[],
                           created_at=TS, updated_at=TS)
        tx.upsert(CR.LEGACY_TABLE, legacy.to_dict())
        created = CR.sync_from_legacy(tx, legacy.to_dict(), actor="agent-B")
    assert created["stmt_id"] == "0003" and created["status"] == "pending_definition"

    # 定义到了（老行改）⇒ 新标准那一行回 active，且别名带过来
    legacy.definition = "带运算的集合"
    legacy.aliases = ["group"]
    with store.tx(CR.LEGACY_TABLE, "statements", actor="test") as tx:
        tx.upsert(CR.LEGACY_TABLE, legacy.to_dict())
        updated = CR.sync_from_legacy(tx, legacy.to_dict(), actor="agent-B")
    assert updated["status"] == "active", updated["status"]
    assert updated["statement_full"] == "带运算的集合" and updated["aliases"] == ["group"]
    assert updated["proof_text"] == created["proof_text"], (
        "新标准独有那几格（良定义性证明）不许被老表覆盖 —— 老表里根本没有它们")
    view = CR.view(store)
    assert view["counts"]["merged"] == 1 and view["counts"]["legacy_only"] == 0


def test_a_merge_tombstone_becomes_superseded(store):
    """老表的墓碑（`merged_into`）映射成 `superseded` + 理由（不许在新标准里消失）。"""
    with store.tx(CR.LEGACY_TABLE, "statements", actor="test") as tx:
        CR.sync_from_legacy(tx, {"concept_id": "0000", "name": "交换群",
                                 "definition": "运算可交换的群", "aliases": []}, actor="t")
        dead = {"concept_id": "0001", "name": "阿贝尔群", "definition": "同 0000",
                "aliases": [], "merged_into": "0000", "merge_reason": "结构等价 + 名字侧证据"}
        out = CR.sync_from_legacy(tx, dead, actor="t")
    assert out["status"] == "superseded", out["status"]
    assert "0000" in out["quote_reason"] and "结构等价" in out["quote_reason"], out["quote_reason"]
    assert out["status"] in S.STATEMENT_UNUSABLE_STATUSES, "被合并的那条不许再当依据"


def test_the_two_counters_are_pushed_past_the_shared_id(store):
    """过渡期是一个号空间、两个计数器 ⇒ 镜像完之后两个计数器都要在号之后。

    实测抓到的一条真缺陷：B 从 `concept` 计数器发号、镜像行落进 `statements`，
    而 `stmt` 计数器没动 ⇒ `verify` 当场报 `counter_behind`（"继续分配会撞号"）。
    """
    from agentflow.verify import verify_all

    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    sid = int(out["stmt_id"])
    counters = dict(store.read("counters")["counters"])
    assert counters["stmt"] > sid and counters["concept"] > sid, counters
    codes = [i["code"] for i in verify_all(store).to_dict()["errors"]]
    assert "counter_behind" not in codes, codes


def test_a_legacy_row_without_an_id_is_not_guessed(store):
    """反真空：老行没有 `concept_id` ⇒ 返回 `None`（不猜一个号出来）。"""
    with store.tx(CR.LEGACY_TABLE, "statements", actor="test") as tx:
        assert CR.sync_from_legacy(tx, {"name": "没有号的行"}, actor="t") is None
    assert store.rows("statements") == []


# ==================================================== 五、过渡投影（读侧一次只搬一件事）

def test_the_legacy_projection_keeps_real_data_and_names(store):
    """`shape="legacy"`：老字段名映射过来，而真实数据（`related_concepts`）不许丢。"""
    _legacy_write(store, "0002", "谱", definition="矩阵的谱")
    with store.tx(CR.LEGACY_TABLE, actor="test") as tx:
        row = dict(tx.find(CR.LEGACY_TABLE, concept_id="0002"))
        row["related_concepts"] = ["0003"]
        tx.upsert(CR.LEGACY_TABLE, row)
    view = CR.view(store, shape="legacy")
    assert view["shape"] == "legacy" and view["checked"]
    r = view["rows"][0]
    assert r["concept_id"] == "0002" and r["name"] == "谱" and r["definition"] == "矩阵的谱"
    assert r["related_concepts"] == ["0003"], "老表那一格是真的数据，投影不许折成空"
    assert r["normalized_name"] == "谱" and r["via"] == "legacy"
    # 新标准的字段名照旧带着（投影是单向的，不是"第二份老表"）
    assert r["aliases"] == [] and r["status"] == "active"


def test_the_projection_marks_what_the_new_standard_does_not_have(store):
    """反真空：新标准那一档没有 `related_concepts` 这一格 ⇒ 由 `via` 分辨，不许折平。"""
    out = CR.upsert(store, label="电导", definition="边上权重的倒数")
    sid = out["stmt_id"]
    r = CR.view(store, shape="legacy")["rows"][0]
    assert r["concept_id"] == sid and r["via"] == "statements"
    assert r["related_concepts"] == [], "新标准没有这一格 ⇒ 空列表（判据据 via 分辨）"
    assert r["normalized_name"] == "电导", "这一格现算（老表那格实测 640/2233 与现算不符）"


def test_verify_does_not_report_drift_for_the_new_standard(store):
    """`verify` 不许对"新标准没有那一格"报 `related_drift`（假红比不报更糟）。"""
    from agentflow.verify import verify_all

    CR.upsert(store, label="谱", definition="矩阵的谱")
    d = verify_all(store).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert "related_drift" not in codes, codes
    assert d["checked"]["related_concepts_skipped_new_standard"] == 1, d["checked"]


def test_a_corrupt_legacy_file_makes_verify_fail_loudly(store, monkeypatch):
    """三态：老文件坏了 ⇒ `verify` 大声失败（受控 StoreError），不许"照常通过"。

    这一条测的是既有行为（审计读任何一张表读不成都会抛受控错），摆在这里是因为
    它正是"并表过渡期最危险的那种沉默"的反面：老表坏了而审计照样绿。
    另一半（`concept_view_unreadable` 那条 issue）在下面单独测 —— 它走的是
    "视图判不了"这一支（`CR.view` 报 `checked=False`），而不是"文件坏了"。
    """
    from agentflow.store import StoreError
    from agentflow.verify import verify_all

    _legacy_write(store, "0005", "谱")
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    try:
        verify_all(store)
    except StoreError as exc:
        assert "concepts.json" in str(exc), str(exc)
    else:
        raise AssertionError("老表坏了而 verify 照常返回 ⇒ '读不成'被折成了'查过了没问题'")


def test_verify_reports_an_unreadable_view_instead_of_a_flood(store, monkeypatch):
    """视图判不了 ⇒ `verify` 报 `concept_view_unreadable`（不是满屏"指向不存在的概念"）。"""
    from agentflow import verify as V

    _legacy_write(store, "0005", "谱")
    monkeypatch.setattr(V.CR, "view", lambda *a, **kw: {
        "checked": False, "rows": [], "reason": "（判据夹具：老表读不成）", "counts": {}})
    d = V.verify_all(store).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert "concept_view_unreadable" in codes, codes
    assert "dangling_related" not in codes, "读不成不许变成'每一条关系都指向不存在的概念'"


# ==================================================== 六、读侧搬运（视图进事务 / 进图）

def test_the_view_inside_a_transaction_sees_its_own_writes(store):
    """`view_tx`：事务里刚写的概念立刻看得见（读己之写）—— `view` 做不到，这是它存在的理由。"""
    with store.tx("concepts", "relations", "statements", actor="test") as tx:
        data = CR.write_concept(tx, stmt_id=tx.alloc_id("concept"), label="群",
                                definition="带运算的集合", mirror=True)
        sid = data["stmt_id"]
        in_tx = CR.view_tx(tx, shape="legacy")
        assert in_tx["checked"], in_tx
        assert [r["concept_id"] for r in in_tx["rows"]] == [sid], (
            "事务内视图读不到本事务刚写的行 ⇒ B 的'读→改→写回'会基于上一次提交的版本")
    # 提交之后再读：`view` 与 `view_tx` 的结果必须一致（同一个合并实现）
    after = CR.view(store, shape="legacy")
    assert [r["concept_id"] for r in after["rows"]] == [sid]


def test_the_graph_sees_concepts_written_by_the_new_standard(store):
    """C 的图入口（`RelationGraph.from_store`）看得到新标准写进来的概念。"""
    from agentflow.tools.graph_tools import RelationGraph

    out = CR.upsert(store, label="电导", definition="边上权重的倒数")   # 新标准那一档
    sid = out["stmt_id"]
    other = CR.upsert(store, label="电阻", definition="电导的倒数")
    add_literature(store, "0000")
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", {"relation_id": "0000", "concept_ids": [sid, other["stmt_id"]],
                                "kind": "related", "description": "夹具",
                                "lit_id": "0000", "created_at": TS})
    g = RelationGraph.from_store(store)
    assert g.name_of(sid) == "电导", g.name_of(sid)
    assert g.degree(sid) == 1, "新标准写进来的概念没进图 ⇒ C 的六件分析一起瞎"


def test_the_graph_refuses_to_build_on_an_unreadable_view(store, monkeypatch):
    """反真空：视图判不了 ⇒ 图入口抛（不返回空图：空图会把"读不成"读成"没有概念"）。"""
    from agentflow.store import StoreError
    from agentflow.tools import graph_tools as G

    monkeypatch.setattr(G.CR, "view", lambda *a, **kw: {
        "checked": False, "rows": [], "reason": "（判据夹具）"})
    try:
        G.RelationGraph.from_store(store)
    except StoreError as exc:
        assert "合成视图" in str(exc), str(exc)
    else:
        raise AssertionError("视图判不了而图照样建出来 ⇒ 空图会被读成'库里没有概念'")
