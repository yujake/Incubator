# -*- coding: utf-8 -*-
"""概念行的读写口（`conceptrows`）：并表落刀之后仍然作数的判据。

`concepts` 已经并进 `statements`（`kind="concept"`）：`SCHEMA_VERSION=2`、表从`schema.TABLES` / `store.LOCK_ORDER` /
`schema.ID_COUNTERS` / `schema.ARRAY_FIELD_KINDS`里真删，老表那些行由 `store.rebuild` 折进新家（折叠内核 `migrate_concepts`）
——这是一次动磁盘格式的迁移（`AGENTS.md` 七类之一），所以判据必须跟着走，而不是跟着删。

## 这一组守什么（两层，分开写清楚）

落刀之后仍然作数（不需要任何模拟）：正控：写一条概念 ⇒ 只落一处（`statements`，`kind="concept"`），盘上不多建老文件；秘书那条路（B 交内容）同样只落一处；- 三态：退役的老表读不了，
而那条错必须指路（新表名 + 统一入口 + 怎么迁）；盘上还留着迁移前那份 `data/concepts.json` ⇒ 必须被点名（`stale_file` + 视图读数里的`reason`），而里面的行不许悄悄合进视图；
那份文件坏掉之后"它还在"这件事照样判得了；- 写侧入口：`upsert_legacy_shaped` 对老形状的行写正好一行新标准，没有号就返回`None`（零行）；`tables_for_concept_write` 跟着
`TABLES` 走，调用方给的表一个不丢；- `raise_counter_to` 的语义：`stmt` 计数器抬到号之后、一个号都不烧（不报 `counter_behind`也不报 `id_gap`），退役的
`concept` 类别不许留在计数器里；- 视图（`view` / `view_tx`）与图入口（`RelationGraph.from_store`）的三态：读不成 ⇒ 明说，不许折成"库里没有概念"；-
`verify` 不对"新标准没有那一格"报假红，且"跳过几行"是一个看得见的读数。只在过渡期里作数（一律靠 `_pre_flip` 把老表按落刀前的形态装回 schema ⇒ 模拟，docstring 里逐条写明）：两处同号、
镜像、老写侧的行可见、`definition_only_in_legacy`那份读数、两个计数器、老表读不成那一态、以及"老表还在"时 `verify` 真的判 `related_concepts`。

为什么要留着这一层而不是随表一起删：`conceptrows` 的过渡层代码还在（`LEGACY_TABLE`、镜像、`_from_legacy`、`legacy_present` 的四态），
而"它当时为什么是对的"只有这些判据能守。删掉它们等于把那一层变成没有判据的活代码。
"""

from __future__ import annotations

import json

from conftest import TS, add_literature, sync_counters
from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import store as STORE
from agentflow.store import StoreError

#: 老表在落刀前的 `TABLES` 声明（`_pre_flip` 用它把那一格装回去）。
_CONCEPT_SPEC = {"file": "concepts.json", "row": S.Concept, "id_field": "concept_id",
                 "id_kind": "concept"}


def _pre_flip(monkeypatch) -> None:
    """把老表按落刀之前的形态装回 schema —— 只用于模拟过渡期，不是产品路径。

    为什么 `TABLES` 一处不够（四处都要装回去，缺一处模拟出来的就不是过渡期）：

    - `store.tx` 按 `LOCK_ORDER` 判"未知表"（它不查 `TABLES`）⇒ 不装它，
      `tx("concepts")` 会以"未知表"失败；
    - `Tx.raise_counter_to` 查 `ID_COUNTERS`（`push_counters` 会静默跳过没有的类别）；
    - `check_array_invariants` 查 `ARRAY_FIELD_KINDS`。

    落刀已经落了（`SCHEMA_VERSION=2`，表真删），真实工作区里没有"老表还在"这一态
    ⇒ 凡是要问"过渡期里那件事对不对"的判据，都只能靠这一手造出那一态。
    """
    monkeypatch.setitem(S.TABLES, CR.LEGACY_TABLE, dict(_CONCEPT_SPEC))
    order = list(STORE.LOCK_ORDER)
    order.insert(order.index("relations"), CR.LEGACY_TABLE)
    monkeypatch.setattr(STORE, "LOCK_ORDER", tuple(order))
    monkeypatch.setitem(S.ID_COUNTERS, "concept", "concept_id")
    monkeypatch.setitem(S.ARRAY_FIELD_KINDS, "concepts",
                        {"related_concepts": "set", "aliases": "seq"})


def _stale_concepts_file(store, cid: str = "0007", name: str = "还没搬完的老概念") -> None:
    """在盘上放一份迁移前的老文件（`data/concepts.json`）。

    它是"还有一份没搬"的证据：里面的行按设计不会被读进视图（老表已退役），
    所以它必须由 `legacy_present.stale_file` 与视图读数里的 `reason` 点名。
    """
    rows = [{"concept_id": cid, "name": name, "definition": "老定义",
             "related_concepts": [], "normalized_name": name, "aliases": [],
             "created_at": TS, "updated_at": TS}]
    (store.data / "concepts.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION - 1, "rows": rows},
                   ensure_ascii=False), encoding="utf-8")


def _legacy_rows(store) -> list[dict]:
    """老表那一份的行 —— 只在 `_pre_flip` 之后可用（落刀之后读它是受控错）。"""
    return list(store.rows(CR.LEGACY_TABLE))


def _rows(store, table: str) -> list[dict]:
    """表级原始读（这一组判据要知道"写到哪张表去了"，所以不用合成视图）。"""
    return list(store.rows(table))


def _stmt_rows(store) -> list[dict]:
    return list(store.rows("statements"))


def _legacy_write(store, cid: str, name: str, definition: str = "") -> dict:
    """模拟"还没搬完的老写侧"（B 的 pipeline 当年就是直接往 `concepts` 写）。

    只在 `_pre_flip` 之后可用（它写的就是那张已经退役的表）。
    """
    row = S.Concept(concept_id=cid, name=name, definition=definition,
                    related_concepts=[], normalized_name=name, created_at=TS, updated_at=TS)
    row.validate()
    with store.tx(CR.LEGACY_TABLE, actor="test") as tx:
        tx.upsert(CR.LEGACY_TABLE, row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ==================================================== 一、一次写只落一处（正控）

def test_a_new_concept_lands_once_in_the_new_standard(store):
    """写一条概念 ⇒ 只落一处（`statements`，`kind="concept"`），盘上不多一份。

    旧判据在这里断言的是"两张表各一份、号相同"（过渡期的契约 1）。落刀之后"两张表"
    不存在了，而要守的东西一个字没变：一次写只能产出一行 —— 写成两行就是
    "同一个概念被数两遍"；而"只落一处"的另一半是不许把老文件写出来
    （凭空多一份没有主人的数据，下一次迁移会把它读成"还有一份没搬"）。
    """
    out = CR.upsert(store, label="谱", definition="矩阵的谱", aliases=["spectrum"])
    assert out["checked"] and out["mirrored"] is False, out
    assert out["tables"] == ["statements"], out["tables"]
    stmts = _stmt_rows(store)
    assert len(stmts) == 1 and stmts[0]["stmt_id"] == out["stmt_id"], stmts
    assert stmts[0]["kind"] == "concept" and stmts[0]["label"] == "谱"
    assert stmts[0]["statement_full"] == "矩阵的谱" and stmts[0]["aliases"] == ["spectrum"]
    assert not (store.data / "concepts.json").exists(), "落刀之后不许再建老文件"

    view = CR.view(store)
    assert view["checked"] and len(view["rows"]) == 1, view["rows"]
    assert view["rows"][0]["via"] == "statements"
    assert view["counts"] == {"statements": 1, "legacy": 0, "merged": 0, "legacy_only": 0,
                              "definition_only_in_legacy": 0}, view["counts"]


def test_a_new_concept_still_mirrors_when_the_legacy_table_is_present(store, monkeypatch):
    """过渡期那一态（模拟，见 `_pre_flip`）：两张表各一份、号相同、视图只出现一次。

    这是旧正控的原样保留 —— 它守的是过渡期的契约 1（一个身份一个号）。
    落刀之后它不再适用（老表不存在），所以只能靠 monkeypatch 造出那一态；
    造不出来就等于把"两个落点必须同号"这条保护整条丢掉。
    """
    _pre_flip(monkeypatch)
    out = CR.upsert(store, label="谱", definition="矩阵的谱", aliases=["spectrum"])
    assert out["checked"] and out["mirrored"] is True, out
    assert out["tables"] == ["statements", CR.LEGACY_TABLE], out["tables"]
    stmts, legacy = _stmt_rows(store), _legacy_rows(store)
    assert len(stmts) == 1 and len(legacy) == 1
    assert stmts[0]["stmt_id"] == legacy[0]["concept_id"] == out["stmt_id"], (
        "两处同号是那一层的契约：不同号 ⇒ 读的人会把同一个概念数两遍")
    assert stmts[0]["kind"] == "concept" and stmts[0]["label"] == "谱"
    assert legacy[0]["name"] == "谱" and legacy[0]["definition"] == "矩阵的谱"

    view = CR.view(store)
    assert view["checked"] and len(view["rows"]) == 1, view["rows"]
    assert view["rows"][0]["via"] == "statements"
    assert view["counts"] == {"statements": 1, "legacy": 1, "merged": 1, "legacy_only": 0,
                              "definition_only_in_legacy": 0}, view["counts"]


def test_the_secretary_writes_the_concept_once(store):
    """秘书那条路（B 交内容）写在一处 —— 一次写入不许变成两行概念。"""
    sec = SEC.Secretary("B", root=store.root, store=store)
    out = sec.record_statement(
        # 2026-10-21（本批缺陷一）：概念行的 `origin` 不再默认 `own_result` ——
        # 确实是自己定义的新概念要显式声明 `self_authored`；概念行也不再带
        # `proof_text`（那个哨兵把"有没有证明"的读数全顶高了，见
        # `conceptrows.concept_statement` 的 docstring）。
        {"origin": "own_result", "self_authored": True, "kind": "concept",
         "label": "电导", "statement_full": "边上权重的倒数",
         "quote_reason": "原始概念", "evidence_kind": "heuristic"}, role="B")
    assert out["checked"] and out["created"], out
    sid = out["stmt_id"]
    assert [r["stmt_id"] for r in _stmt_rows(store)] == [sid]
    assert _stmt_rows(store)[0]["kind"] == "concept"
    assert not (store.data / "concepts.json").exists()
    view = CR.view(store)
    assert view["counts"]["statements"] == 1 and view["counts"]["merged"] == 0, view["counts"]
    assert [r["via"] for r in view["rows"]] == ["statements"], view["rows"]


def test_the_secretary_mirrors_when_the_legacy_table_is_present(store, monkeypatch):
    """过渡期那一态（模拟）：秘书写的概念两面都在，老读侧立刻看得到。"""
    _pre_flip(monkeypatch)
    sec = SEC.Secretary("B", root=store.root, store=store)
    out = sec.record_statement(
        # 2026-10-21（本批缺陷一）：概念行的 `origin` 不再默认 `own_result` ——
        # 确实是自己定义的新概念要显式声明 `self_authored`；概念行也不再带
        # `proof_text`（那个哨兵把"有没有证明"的读数全顶高了，见
        # `conceptrows.concept_statement` 的 docstring）。
        {"origin": "own_result", "self_authored": True, "kind": "concept",
         "label": "电导", "statement_full": "边上权重的倒数",
         "quote_reason": "原始概念", "evidence_kind": "heuristic"}, role="B")
    assert out["checked"] and out["created"], out
    sid = out["stmt_id"]
    assert [r["stmt_id"] for r in _stmt_rows(store)] == [sid]
    assert [r["concept_id"] for r in _legacy_rows(store)] == [sid], "镜像没写或号不同"
    assert CR.view(store)["counts"]["merged"] == 1


def test_a_row_only_the_old_writer_knows_about_is_still_visible(store, monkeypatch):
    """过渡期那一态（模拟）：只有老表有的行，视图照样看得到（`via="legacy"`）。

    落刀之后"只有老表有的行"不再存在（老表的行要么被折走、要么留在残留文件里而按设计
    不被读）；这一条守的是过渡期读侧那一支 —— 逐行折成新形状、`via` 标出来、
    空定义的行折成"待补"而不是"定义就是空的"。
    """
    _pre_flip(monkeypatch)
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


# ==================================================== 二、三态（负控）

def test_the_retired_table_is_unreadable_with_a_pointer(store):
    """退役的老表读不了，而那条错必须指路（不是笼统的"未知表"）。

    为什么这是一条判据：`store.rows(CR.LEGACY_TABLE)` 与"表名写错了"在结构上分不开，
    而处置完全不同（前者去读新家，后者查笔误）。指路里必须出现新表名、统一入口与
    迁移手段 —— 只报一句"未知表：concepts"，读的人不知道下一步该改代码还是查笔误。
    """
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    for call in (lambda: store.rows(CR.LEGACY_TABLE), lambda: store.read(CR.LEGACY_TABLE)):
        try:
            call()
        except StoreError as exc:
            text = str(exc)
            assert "已经并走" in text and "statements" in text, text
            assert "conceptrows" in text and "rebuild" in text, text
        else:
            raise AssertionError("退役的表被当普通表读了 ⇒ '并走'与'表名写错'再也分不开")
    # 反真空：这一条不是"什么表都读不了" —— 新家读得出来
    assert [r["stmt_id"] for r in _stmt_rows(store)] == [out["stmt_id"]]


def test_a_leftover_file_is_named_and_not_merged(store):
    """落刀之后盘上还留着老文件 ⇒ 必须被点名，而里面的行不许悄悄合进视图。

    这是旧判据 `test_after_the_flip_a_leftover_file_is_named` 的落刀后形态：那一份要
    `monkeypatch.delitem(S.TABLES, "concepts")` 才能造出"表没了、文件还在"，
    现在落刀已经落了 ⇒ 直接就是这一态。点名有两处（`legacy_present.stale_file` 与
    视图读数里的 `reason`），而"不许合"这一条同样要判：把残留行折进视图会让
    "还有一份没搬"读成"已经搬完了"。
    """
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    _stale_concepts_file(store, cid="0007", name="还没搬完的老概念")

    state = CR.legacy_present(store)
    assert state["checked"] and state["present"] is False and state["stale_file"] is True, state
    assert "老文件" in state["reason"] or "还没搬完" in state["reason"], state["reason"]

    view = CR.view(store)
    assert view["checked"] and view["reason"], "残留文件这件事必须在视图读数里看得见"
    assert view["counts"] == {"statements": 1, "legacy": 0, "merged": 0, "legacy_only": 0,
                              "definition_only_in_legacy": 0}, view["counts"]
    assert [r["stmt_id"] for r in view["rows"]] == [out["stmt_id"]], view["rows"]
    assert all(r["via"] == "statements" for r in view["rows"])

    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is False, gaps
    assert gaps["statements_only"] == [out["stmt_id"]], gaps
    # 反真空：写一条新的之后那份残留仍然被点名（不是"第一次之后就不再提"）
    again = CR.upsert(store, label="第二", definition="d")
    assert again["reason"] and "老文件" in again["reason"], again
    assert CR.legacy_present(store)["stale_file"] is True


def test_a_corrupt_stale_file_is_still_named(store):
    """三态：残留老文件坏掉之后，至少"它还在"这件事判得了（不是"没查成"，也不是"干净"）。

    这一态最容易折平：文件读不成 ⇒ 报"没有老文件"（把"没查成"读成"没有"）。
    `legacy_present` 判的是"文件在不在"（`is_file()`），与里面的内容读不读得成是两件事，
    所以坏文件仍然要给 `checked=True, stale_file=True` + 理由，而视图的读数不许变空。
    """
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    state = CR.legacy_present(store)
    assert state["checked"] is True and state["stale_file"] is True and state["reason"], state

    view = CR.view(store)
    assert view["checked"] and view["reason"], view
    assert [r["stmt_id"] for r in view["rows"]] == [out["stmt_id"]], view["rows"]

    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is False, gaps
    assert gaps["statements_only"] == [out["stmt_id"]], gaps


def test_a_definition_only_in_the_old_table_is_a_reading_not_a_silent_merge(store, monkeypatch):
    """过渡期那一态（模拟）：新标准那行空着定义、老行有 ⇒ 记读数，不自动抹平。

    这一条只在"两处同号"存在时才有内容（`definition_only_in_legacy` 数的是两边都有、
    而老行多一份定义的那些行）⇒ 靠 `_pre_flip` 造。它守的是"新标准优先，差异记成读数"
    —— 顺手把老行的定义搬过来同样是错的：那会让"两边不同步"这件事消失。
    """
    _pre_flip(monkeypatch)
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


def test_an_unreadable_old_table_is_not_read_as_only_one_side(store, monkeypatch):
    """过渡期那一态（模拟）：老表读不成 ⇒ `checked=False` + 理由。

    "没查成"不许折成"只有一边"。落刀之后没有"老表"这张表可读 ⇒ 这一态只能造出来；
    落刀之后的对应三态是"残留老文件"（`test_a_corrupt_stale_file_is_still_named`：
    文件在不在仍然判得了，尽管里面的内容读不成）。
    """
    _pre_flip(monkeypatch)
    CR.upsert(store, label="谱", definition="矩阵的谱")
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    view = CR.view(store)
    assert view["checked"] is False and view["rows"] == [], view
    assert "老表读不成" in view["reason"], view["reason"]
    state = CR.legacy_present(store)
    assert state["checked"] is True, "文件在不在还是判得了的（读不成的是内容）"


# ==================================================== 三、反真空

def test_a_fresh_workspace_does_not_mirror_a_retired_table(tmp_path):
    """反真空：老文件从来没建过的新工作区写概念 ⇒ 只落一处，不许凭空建老文件。

    刻意不用 `store` 夹具（理由与旧版一样）：夹具将来若带上演示数据就会把
    "老文件还不在盘上"这一态盖住，而这一条问的正是那一态。
    """
    from agentflow.store import Store

    root = tmp_path / "fresh-ws"
    store = Store(str(root))
    store.init()
    state = CR.legacy_present(store)
    assert state["checked"] and state["present"] is False and state["file"] is False, state
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    assert out["mirrored"] is False and out["tables"] == ["statements"], out
    assert [r["stmt_id"] for r in store.rows("statements")] == [out["stmt_id"]]
    assert not (store.data / "concepts.json").exists(), (
        "新工作区凭空建出一份老文件 ⇒ 下一次迁移会把它读成'还有一份没搬'")


def test_a_fresh_workspace_still_mirrors_when_the_legacy_table_is_present(tmp_path, monkeypatch):
    """过渡期那一态（模拟）：老文件还没建的新工作区也要镜像。

    `present` 判的是"这一版代码还认不认老表"，不是"文件在不在"：拿文件判会把
    "还没写过概念"读成"过渡期结束了"，于是那些工作区里新概念不被镜像、老读侧看不到
    它 —— 而两种情形在文件系统上长得一样（都没有那个文件）。所以这一条必须靠
    `_pre_flip` 造出"表在、文件不在"那一态，它才判得了这件事。
    """
    from agentflow.store import Store

    root = tmp_path / "fresh-pre"
    store = Store(str(root))
    store.init()           # 先按当前 schema init（于是盘上没有老文件）
    _pre_flip(monkeypatch)  # 再把老表装回来 —— 那一态正是"表在、文件不在"
    state = CR.legacy_present(store)
    assert state["checked"] and state["present"] is True and state["file"] is False, state
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    assert out["mirrored"], "老文件还没建就当作'过渡期结束' ⇒ 老读侧看不到这个概念"
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
    """改一条（老形状的）行 —— 不是新建 —— 也要落到新标准，且不覆盖新标准独有的那几格。

    这是写侧搬运最容易漏的一支：只把"新建"接上，改（合并别名、重算 `related_concepts`、
    结构重复合并）就只落在老表上 ⇒ 新标准那一份悄悄过期，而两边都有那一行。
    落刀之后 `sync_from_legacy` 仍是 `upsert_legacy_shaped`（夹具/探针的入口）的唯一实现
    ⇒ 这一条原样成立，只是不再需要"先往老表写一份"。
    """
    legacy = {"concept_id": "0003", "name": "群", "definition": "", "aliases": [],
              "related_concepts": [], "normalized_name": "群", "created_at": TS, "updated_at": TS}
    with store.tx(*CR.tables_for_concept_write("relations"), actor="test") as tx:
        created = CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    assert created["stmt_id"] == "0003" and created["status"] == "pending_definition"

    # 定义到了（老行改）⇒ 新标准那一行回 active，且别名带过来
    legacy = dict(legacy, definition="带运算的集合", aliases=["group"])
    with store.tx(*CR.tables_for_concept_write("relations"), actor="test") as tx:
        updated = CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    assert updated["stmt_id"] == "0003", "改一条不是再建一条（号要一样）"
    assert updated["status"] == "active", updated["status"]
    assert updated["statement_full"] == "带运算的集合" and updated["aliases"] == ["group"]
    assert updated["proof_text"] == created["proof_text"], (
        "新标准独有那几格（良定义性证明）不许被老形状的行覆盖 —— 老行里根本没有它们")
    assert len(_stmt_rows(store)) == 1, "改一条不许变成第二条"
    view = CR.view(store)
    assert view["counts"]["statements"] == 1 and view["counts"]["legacy_only"] == 0
    assert [r["via"] for r in view["rows"]] == ["statements"], view["rows"]


def test_a_merge_tombstone_becomes_superseded(store):
    """老表的墓碑（`merged_into`）映射成 `superseded` + 理由（不许在新标准里消失）。

    落刀之后这一支照样可达（`sync_from_legacy` 收的还是老形状的行）：一次真的合并在
    新标准那一边必须看得见 —— 否则 C 的依赖链与收工门会继续把被合并的那条当可用命题。
    """
    with store.tx(*CR.tables_for_concept_write(), actor="test") as tx:
        CR.sync_from_legacy(tx, {"concept_id": "0000", "name": "交换群",
                                 "definition": "运算可交换的群", "aliases": []}, actor="t")
        dead = {"concept_id": "0001", "name": "阿贝尔群", "definition": "同 0000",
                "aliases": [], "merged_into": "0000", "merge_reason": "结构等价 + 名字侧证据"}
        out = CR.sync_from_legacy(tx, dead, actor="t")
    assert out["status"] == "superseded", out["status"]
    assert "0000" in out["quote_reason"] and "结构等价" in out["quote_reason"], out["quote_reason"]
    assert out["status"] in S.STATEMENT_UNUSABLE_STATUSES, "被合并的那条不许再当依据"


def test_the_stmt_counter_is_pushed_past_the_used_id(store):
    """`raise_counter_to` 的语义：`stmt` 计数器抬到号之后，且一个号都不烧。

    实测抓到的真缺陷（过渡期）：行落进 `statements` 而 `stmt` 计数器没动 ⇒
    `verify` 当场报 `counter_behind`（"继续分配会撞号"）。第一版用"多调一次
    `alloc_id` 把计数器顶上去"来修 —— 那会烧掉一个没建行的号，于是同一张表出现
    `id_gap`（"分配了 ID 但未建成行"）。两种错这里都判。

    落刀之后只有一个计数器（`concept` 那一档随表退役），所以顺带钉住"退役的类别
    不许留在计数器 / `ID_COUNTERS` 里"；"两个计数器"的过渡期形态由下面那条模拟判据守。
    """
    from agentflow.verify import verify_all

    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    sid = int(out["stmt_id"])
    counters = dict(store.read("counters")["counters"])
    assert counters["stmt"] == sid + 1, counters   # 抬到号之后，不是"号之后再加一"（不烧号）
    assert "concept" not in counters, (
        "退役的类别留在计数器里 ⇒ 表没了而类别还在（`verify` 会反查不到表）", counters)
    assert "concept" not in S.ID_COUNTERS, S.ID_COUNTERS
    codes = [i["code"] for i in verify_all(store).to_dict()["errors"]]
    assert "counter_behind" not in codes and "id_gap" not in codes, codes


def test_the_two_counters_are_pushed_past_the_shared_id(store, monkeypatch):
    """过渡期那一态（模拟）：一个号空间、两个计数器 ⇒ 镜像完之后两个都要在号之后。

    实测抓到的一条真缺陷：B 从 `concept` 计数器发号、镜像行落进 `statements`，
    而 `stmt` 计数器没动 ⇒ `verify` 当场报 `counter_behind`（"继续分配会撞号"）；
    反过来（秘书那条路从 `stmt` 发号）是 `concept` 计数器落在后面。两个方向都要补。
    """
    from agentflow.verify import verify_all

    _pre_flip(monkeypatch)
    out = CR.upsert(store, label="谱", definition="矩阵的谱")
    sid = int(out["stmt_id"])
    counters = dict(store.read("counters")["counters"])
    assert counters["stmt"] > sid and counters["concept"] > sid, counters
    codes = [i["code"] for i in verify_all(store).to_dict()["errors"]]
    assert "counter_behind" not in codes and "id_gap" not in codes, codes


def test_a_legacy_row_without_an_id_is_not_guessed(store):
    """反真空：老形状的行没有 `concept_id` ⇒ 返回 `None`（不猜一个号出来），一行不写。"""
    with store.tx(*CR.tables_for_concept_write(), actor="test") as tx:
        assert CR.sync_from_legacy(tx, {"name": "没有号的行"}, actor="t") is None
    assert store.rows("statements") == []


# ==================================================== 七、夹具不牵连落刀（两个入口）

def test_the_concept_write_tables_follow_the_transition(monkeypatch):
    """`tables_for_concept_write`：跟着 `TABLES` 走，调用方给的表一个不丢。

    两态都要判：落刀之后只声明 `statements`；把老表装回来（模拟过渡期，见
    `_pre_flip`）它必须重新出现在声明里 —— 少声明一张表的后果不是"少写一份"，
    而是镜像那条写会以"未知表"让整笔事务失败（这正是"落刀牵连夹具"那件事的成因）。
    """
    tables = CR.tables_for_concept_write("relations", "literature")
    assert tables[0] == "statements" and "relations" in tables and "literature" in tables
    assert CR.LEGACY_TABLE not in tables, "老表已退役 ⇒ 声明它会让事务当场以'未知表'失败"
    assert CR.tables_for_concept_write() == ("statements",), CR.tables_for_concept_write()

    _pre_flip(monkeypatch)
    tables = CR.tables_for_concept_write("relations", "literature")
    assert CR.LEGACY_TABLE in tables, "老表还在却不声明 ⇒ 镜像那条写会以'未知表'失败"
    assert CR.tables_for_concept_write() == ("statements", CR.LEGACY_TABLE), \
        CR.tables_for_concept_write()


def test_a_legacy_shaped_write_lands_once_in_the_new_standard(store):
    """一条老形状的行 ⇒ 走过去入口之后只落一处；退役的表读不了、老文件不建。"""
    with store.tx(*CR.tables_for_concept_write("relations"), actor="test") as tx:
        out = CR.upsert_legacy_shaped(tx, {"concept_id": "0000", "name": "群",
                                           "definition": "带运算的集合", "aliases": ["group"],
                                           "related_concepts": []}, actor="test")
    assert out is not None and out["stmt_id"] == "0000", out
    assert [(r["stmt_id"], r["label"]) for r in _stmt_rows(store)] == [("0000", "群")]
    assert not (store.data / "concepts.json").exists()
    try:
        _rows(store, CR.LEGACY_TABLE)
    except StoreError as exc:
        assert "已经并走" in str(exc), str(exc)
    else:
        raise AssertionError("退役的老表被当普通表读了")
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is True, gaps


def test_a_legacy_shaped_write_still_writes_both_when_the_legacy_table_is_present(store, monkeypatch):
    """过渡期那一态（模拟）：一条老形状的行 ⇒ 老表那一份照旧写全，两处同号。"""
    _pre_flip(monkeypatch)
    with store.tx(*CR.tables_for_concept_write("relations"), actor="test") as tx:
        out = CR.upsert_legacy_shaped(tx, {"concept_id": "0000", "name": "群",
                                           "definition": "带运算的集合", "aliases": ["group"],
                                           "related_concepts": []}, actor="test")
    assert out is not None and out["stmt_id"] == "0000", out
    assert CR.mirror_gaps(store)["merged"] == ["0000"], CR.mirror_gaps(store)
    assert _rows(store, CR.LEGACY_TABLE)[0]["name"] == "群", "老表那一份要照旧写全"


def test_a_row_without_an_id_is_not_guessed(store):
    """负控：老形状的行没有 `concept_id` ⇒ 返回 `None` 且一行不写（不猜号）。"""
    with store.tx(*CR.tables_for_concept_write(), actor="test") as tx:
        assert CR.upsert_legacy_shaped(tx, {"name": "没有号"}, actor="test") is None
    assert _rows(store, "statements") == []


def test_the_entry_point_survives_the_flip(store, monkeypatch):
    """反真空（这就是它存在的理由）：老表在不在，这两个入口的行为都要对。

    落刀那一笔会把 `concepts` 从 `TABLES` 里删掉。凡是"声明了老表"或"直接往老表写"的
    夹具/测试在那一刻都会以"未知表"失败 —— 实测这样的地方去重后有 30 多处。
    走了这两个入口之后，老表在不在由过渡层判断：声明自动少一张、写自动只写新标准。

    两态各判一次。旧版只有"`delitem` 模拟落刀"那一态（落刀之后"删表"这一步已经落了，
    `delitem` 无事可做）⇒ 改成：不装老表 ⇒ 只写新标准（落刀后的真实形态）；
    装回老表（模拟过渡期）⇒ 两处都写。
    """
    # ---- 落刀之后的真实形态：只写新标准
    tables = CR.tables_for_concept_write("relations")
    assert CR.LEGACY_TABLE not in tables and tables == ("statements", "relations"), tables
    with store.tx(*tables, actor="test") as tx:
        out = CR.upsert_legacy_shaped(tx, {"concept_id": "0005", "name": "删表之后",
                                           "definition": "d", "related_concepts": []},
                                      actor="test")
    assert out is not None and out["stmt_id"] == "0005", out
    assert [r["stmt_id"] for r in _rows(store, "statements")] == ["0005"]
    view = CR.view(store, shape="legacy")
    assert [r["name"] for r in view["rows"]] == ["删表之后"], view["rows"]
    assert view["counts"] == {"statements": 1, "legacy": 0, "merged": 0, "legacy_only": 0,
                              "definition_only_in_legacy": 0}, view["counts"]

    # ---- 过渡期那一态（模拟）：同一个入口两处都写
    _pre_flip(monkeypatch)
    tables = CR.tables_for_concept_write("relations")
    assert tables == ("statements", "relations", CR.LEGACY_TABLE), tables
    with store.tx(*tables, actor="test") as tx:
        both = CR.upsert_legacy_shaped(tx, {"concept_id": "0006", "name": "老表还在",
                                            "definition": "d", "related_concepts": []},
                                       actor="test")
    assert both is not None and both["stmt_id"] == "0006", both
    assert [r["concept_id"] for r in _rows(store, CR.LEGACY_TABLE)] == ["0006"]
    assert sorted(r["stmt_id"] for r in _rows(store, "statements")) == ["0005", "0006"]


# ==================================================== 五、过渡投影（读侧一次只搬一件事）


def test_the_legacy_projection_keeps_real_data_and_names(store, monkeypatch):
    """过渡期那一态（模拟）：`shape="legacy"` 把老字段名映射过来，真数据不许丢。

    `related_concepts` 是老表专有的一格（并表之后那件事由 `relations` 表管），所以这一条
    只在"老表还在"时有内容 —— 靠 `_pre_flip` 造。它守的是投影单向但不丢数据：
    老名字映射回来，`related_concepts` 原样带着（`verify` 的 drift 判据与
    `agentflow repair --related` 都靠它），而新标准的字段名照旧也在
    （投影不是"第二份老表"）。
    """
    _pre_flip(monkeypatch)
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
    assert r["legacy_related"] is False, "空列表是'这一版没有这一格'，不是'表里写着空'"
    assert r["normalized_name"] == "电导", "这一格现算（老表那格实测 640/2233 与现算不符）"


def test_verify_does_not_report_drift_for_the_new_standard(store):
    """`verify` 不许对"新标准没有那一格"报 `related_drift`（假红比不报更糟）。

    新标准里 `related_concepts` 那一格不存在（那件事由 `relations` 表管）⇒ 这些行必须按
    "这一格没有权威值"跳过，而跳过几行是一个读数（"少判了几行"必须看得见）。
    反真空在这一条里也判：跳过数跟着行数走（不是恒等于某个数）——
    至于"有权威值的行真的被判"，由下一条模拟判据守（两条合起来才说明跳过是分档的，
    而不是整段不判了）。
    """
    from agentflow.verify import verify_all

    CR.upsert(store, label="谱", definition="矩阵的谱")
    d = verify_all(store).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert "related_drift" not in codes and "dangling_related" not in codes, codes
    assert d["checked"]["related_concepts_skipped_new_standard"] == 1, d["checked"]

    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", CR.concept_statement(
            stmt_id="0099", label="只在新标准", definition="x").to_dict())
    d2 = verify_all(store).to_dict()
    codes2 = [i["code"] for i in list(d2["errors"]) + list(d2["warnings"])]
    assert d2["checked"]["related_concepts_skipped_new_standard"] == 2, d2["checked"]
    assert "related_drift" not in codes2, codes2


def test_verify_judges_the_authoritative_related_concepts(store, monkeypatch):
    """过渡期那一态（模拟）：有权威值的行必须真的被判 ⇒ 跳过数是 0。

    为什么单列：上一条只断言"跳过了 N 行"。如果 `verify` 干脆整段不判了，那个数同样会涨
    —— 两条合起来才说明"跳过是按'这一格有没有权威值'分档的"。过渡期里 `upsert` 会镜像，
    于是老表那一份在 ⇒ 这一格有权威值 ⇒ 要判（这也是 `add_concept` 夹具改成两处同号
    之后 `test_wrong_related_concepts_is_reported_as_related_drift` 能继续红的原因）。
    """
    from agentflow.verify import verify_all

    _pre_flip(monkeypatch)
    CR.upsert(store, label="谱", definition="矩阵的谱")
    d = verify_all(store).to_dict()
    codes = [i["code"] for i in list(d["errors"]) + list(d["warnings"])]
    assert d["checked"]["related_concepts_skipped_new_standard"] == 0, d["checked"]
    assert "related_drift" not in codes and "dangling_related" not in codes, codes


def test_a_corrupt_legacy_file_makes_verify_fail_loudly(store, monkeypatch):
    """过渡期那一态（模拟）：老表文件坏了 ⇒ `verify` 大声失败（受控 `StoreError`）。

    这一条测的是既有行为（审计读任何一张表读不成都会抛受控错），摆在这里是因为它正是
    "并表过渡期最危险的那种沉默"的反面：老表坏了而审计照样绿。落刀之后 `verify` 不再读
    那份老文件（它不是 `TABLES` 里的一张表）⇒ 这一态只能靠 `_pre_flip` 造；
    落刀之后的对应读数是"残留老文件被点名"（`stale_file`，见
    `test_a_corrupt_stale_file_is_still_named`）。
    """
    from agentflow.store import StoreError
    from agentflow.verify import verify_all

    _pre_flip(monkeypatch)
    _legacy_write(store, "0005", "谱")
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    try:
        verify_all(store)
    except StoreError as exc:
        assert "concepts.json" in str(exc), str(exc)
    else:
        raise AssertionError("老表坏了而 verify 照常返回 ⇒ '读不成'被折成了'查过了没问题'")


def test_verify_reports_an_unreadable_view_instead_of_a_flood(clean_store, monkeypatch):
    """视图判不了 ⇒ `verify` 报一条 `concept_view_unreadable`，且它只报一次。

    这一条钉两件事：判不了有它自己的码（不是"库里没有概念"），以及"满屏"的反面 ——一条读数而不是每行一条。用 `clean_store`（两条概念 + 一条关系）而不是空库：空库上"没有假红"是真空的，判据根本判不出东西。

    【实测到的未修缺陷】（2026-10-10，只报不改：`src/agentflow/verify.py` 不在本判据的处置面内）：`_check_1` 报了
    `concept_view_unreadable` 之后没有抑制下游的关系段 ⇒ 每一条引用概念的 relation 仍会各报一条 `dangling_concept`（本仓实测：1 条关系 ⇒ 2 条
    `dangling_concept`）。`verify.py` 里那段注释写着"不许变成'每一条关系都指向不存在的概念'，满屏假红"，而那一半今天没有实现。所以本用例只断言"有自己的码 + 只报一次"，
    既不给出那个错误形态绿灯，也不把它锁死。
    """
    from agentflow import verify as V

    monkeypatch.setattr(V.CR, "view", lambda *a, **kw: {
        "checked": False, "rows": [], "reason": "（判据夹具：老表读不成）", "counts": {}})
    d = V.verify_all(clean_store).to_dict()
    issues = list(d["errors"]) + list(d["warnings"])
    codes = [i["code"] for i in issues]
    assert codes.count("concept_view_unreadable") == 1, codes
    assert "dangling_related" not in codes, "读不成不许变成'每一条关系都指向不存在的概念'"


# ==================================================== 六、读侧搬运（视图进事务 / 进图）

def test_the_view_inside_a_transaction_sees_its_own_writes(store):
    """`view_tx`：事务里刚写的概念立刻看得见（读己之写）—— `view` 做不到，这是它存在的理由。

    声明的表跟着过渡层走（`tables_for_concept_write`），`mirror` 也由那一态决定：
    老表不存在时传 `mirror=True` 会以"未知表"让整笔失败，而这件事该由调用方按
    `legacy_present` 决定（`conceptrows.upsert` 就是这么做的）。
    """
    tables = CR.tables_for_concept_write("relations")
    assert tables == ("statements", "relations"), tables
    with store.tx(*tables, actor="test") as tx:
        data = CR.write_concept(tx, stmt_id=tx.alloc_id(S.TABLES["statements"]["id_kind"]),
                                label="群", definition="带运算的集合",
                                mirror=CR.LEGACY_TABLE in S.TABLES)
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


# ==================================================== 八、墓碑（投影之后仍然是墓碑）


def test_a_superseded_row_is_projected_as_a_tombstone(store):
    """`status="superseded"` 的行在投影里必须带非空 `merged_into`。

    为什么这一格必须给非空（实测抓到的一次真缺陷）：读侧判"这一行是不是活节点"
    读的正是这一格的真值性 —— `dedup.find_concept` 是
    `if row.get("merged_into"): continue`，`agent_b.decide_structural_duplicate` 是
    `if a.get("merged_into") or b.get("merged_into")`。投影原先恒给 `None`
    （理由是"新标准里没有这一列"），于是墓碑重新变成活节点：新来的同名概念命中
    幽灵节点、survivor 永远接不到新知识，而盘上一切正常。
    哨兵不是编出来的目标号（目标号在新标准里没有机器可读的落点，只有
    `quote_reason` 里那句话）⇒ 断言它不是一个合法 id。
    """
    with store.tx("statements", actor="test") as tx:
        for sid, label, status in (("0000", "群", "active"), ("0001", "交换群", "superseded")):
            tx.upsert("statements", {"stmt_id": sid, "origin": "own_result", "kind": "concept",
                                     "label": label, "statement_full": f"{label}的定义",
                                     "proof_text": "concept:primitive", "quote_verified": None,
                                     "quote_reason": "（判据夹具）", "status": status,
                                     "created_at": TS, "created_by": "test"})
    rows = {r["concept_id"]: r for r in CR.view(store, shape="legacy")["rows"]}
    assert len(rows) == 2, rows
    assert rows["0001"]["status"] == "superseded"
    assert rows["0001"]["merged_into"], "墓碑在投影里不许变成活节点（`merged_into` 非空）"
    assert not S.is_valid_id(str(rows["0001"]["merged_into"])), (
        "哨兵不许长得像一个号：谁把它当目标号用都会去找一个不存在的概念")
    assert rows["0000"]["merged_into"] is None, "活节点不许被标成墓碑"


def test_find_concept_skips_the_tombstone_and_still_finds_the_live_row(store):
    """正控 + 反真空：墓碑不被匹配，而活节点必须被匹配到。

    这是上面那条投影判据的真判据（投影只是输入）：`find_concept` 是名字查重的唯一
    实现，`run_once.resolve_concept` 喂给它的就是视图的行。只判"墓碑没被返回"是真空的
    （一律返回 `None` 也能过）⇒ 同时正控：同名的活概念必须被返回。
    """
    from agentflow import dedup as D

    with store.tx("statements", actor="test") as tx:
        for sid, label, status, aliases in (("0000", "阿贝尔群", "active", ["交换群"]),
                                            ("0001", "交换群", "superseded", [])):
            tx.upsert("statements", {"stmt_id": sid, "origin": "own_result", "kind": "concept",
                                     "label": label, "statement_full": f"{label}的定义",
                                     "proof_text": "concept:primitive", "quote_verified": None,
                                     "quote_reason": "（判据夹具）", "status": status,
                                     "aliases": list(aliases),
                                     "created_at": TS, "created_by": "test"})
    rows = CR.view(store, shape="legacy")["rows"]
    hit = D.find_concept(rows, "交换群")
    assert hit is not None and hit["concept_id"] == "0000", (
        f"新知识挂到了墓碑上：find_concept 返回 {None if hit is None else hit['concept_id']}")
    # 反真空：换一个只有活节点才有的名字，仍然必须命中（证明上面不是"谁都不返回"）
    assert D.find_concept(rows, "阿贝尔群")["concept_id"] == "0000"
    # 负控：老表那一档的墓碑（真的带目标号）同样不参与匹配
    legacy = [{"concept_id": "0001", "name": "交换群", "definition": "",
               "merged_into": "0000", "merge_reason": "同义"}]
    assert D.find_concept(legacy, "交换群") is None


def test_the_tombstone_marker_is_not_written_back_as_a_target_id(store):
    """投影是单向的，但"投影的输出当输入用"这条路上，哨兵不许被当成目标号写进理由。

    `_to_legacy` 的输出正好是 `upsert_legacy_shaped` 的入参形状（老字段名），而
    `sync_from_legacy` 会把 `merged_into` 写进 `quote_reason`（"已并入 X"）。
    不拦这一下，一次往返就会把理由改成"已并入 superseded"这种没人看得懂的话 ——
    而真相（并入的是哪一条）已经写在那一格里了。
    """
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": "0001", "origin": "own_result", "kind": "concept",
                                 "label": "交换群", "statement_full": "交换群的定义",
                                 "proof_text": "concept:primitive", "quote_verified": None,
                                 "quote_reason": "已并入 0000（同步自老表的 merged_into）",
                                 "status": "superseded", "created_at": TS, "created_by": "test"})
    projected = CR.view(store, shape="legacy")["rows"][0]
    with store.tx("statements", actor="test") as tx:
        CR.upsert_legacy_shaped(tx, projected, actor="test")
    row = store.rows("statements")[0]
    assert row["status"] == "superseded", row
    assert "已并入 0000" in row["quote_reason"], row["quote_reason"]
    assert "superseded" not in row["quote_reason"], (
        f"哨兵被判成目标号写进了理由：{row['quote_reason']!r}")
