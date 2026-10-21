# -*- coding: utf-8 -*-
"""过渡期的镜像完整性：新标准写进来的概念，老表那一份在不在。

## 为什么这是一条判据（而不是一句注释）

过渡期的读侧已经全部走合成视图了，但 B 的 pipeline 里还有几处 `tx.rows("concepts")`（概念查重、别名合并、`related_concepts` 重算）读的是老表原始行 —— 它们要写回去、
要带老表专有字段（`updated_at`、合并载荷、`merged_into`），所以那一批留到落刀那一笔再改。

那个"留到落刀"之所以安全，唯一的前提是：写侧每一处都把新标准那一行镜像进老表。一旦哪一处忘了镜像，那批概念就会在 pipeline 的查重里消失（静默漏判、可能重复建概念），而盘上看起来一切正常（两边行数都"有增长"）。所以
`conceptrows.mirror_gaps` 是判据：`statements_only` 非空就是一条真缺陷 —— 要么补镜像，要么把那一处写侧搬过来。

## 落刀之后这一格长什么样（S1r，`SCHEMA_VERSION=2`，2026-10-10）

`concepts` 不在 `TABLES` 里了 ⇒ 盘上没有"另一侧"可比，`mirror_gaps` 报 `transition_over=True` 且三个集合都空。这不是"缺口没有了"，而是"这一格不再适用"——
所以这一份必须用两个方向钉住它，缺一个都会让"空集合"变成万能的绿灯：正控（模拟过渡期，见 `_pre_flip`）：B 的 pipeline 跑一趟 ⇒ 每个概念两面都在；
- 落刀之后：`transition_over=True` 且盘上真的没有那份老文件
（老文件还在 ⇒ 不许报"过渡结束"）；
- 负控：绕过镜像直接写 `statements` ⇒ 那一号被点名（判据不许瞎）；
- 三态：老表读不成 ⇒ `checked=False` + 理由（"判不了"不等于"没有缺口"）。
"""

from __future__ import annotations

import json

from conftest import add_literature, write_library_file
from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import store as STORE
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.llm import ConceptDraft

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

    落刀已经落了（`SCHEMA_VERSION=2`，表真删），真实工作区里没有"老表还在"这一态⇒ 凡是要问"过渡期里镜像在不在"的判据，都只能靠这一手造出那一态，并在 docstring 里写清它是模拟。
    """
    monkeypatch.setitem(S.TABLES, CR.LEGACY_TABLE, dict(_CONCEPT_SPEC))
    order = list(STORE.LOCK_ORDER)
    order.insert(order.index("relations"), CR.LEGACY_TABLE)
    monkeypatch.setattr(STORE, "LOCK_ORDER", tuple(order))
    monkeypatch.setitem(S.ID_COUNTERS, "concept", "concept_id")
    monkeypatch.setitem(S.ARRAY_FIELD_KINDS, "concepts",
                        {"related_concepts": "set", "aliases": "seq"})


def _stale_concept_file(store, cid: str = "0009", name: str = "迁移前的老概念") -> None:
    """在盘上放一份老文件（迁移留下的 `data/concepts.json`）。

    它是"还有一份没搬"的证据：里面的行按设计不会被读进视图（老表已经退役），
    所以它必须由 `stale_file` / `transition_over` 这两处读数点名。
    """
    rows = [{"concept_id": cid, "name": name, "definition": "老定义",
             "related_concepts": [], "normalized_name": name, "aliases": [],
             "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00"}]
    (store.data / "concepts.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION - 1, "rows": rows},
                   ensure_ascii=False), encoding="utf-8")


class _OneConcept:
    """确定性抽取器替身：每次返回同一个概念（与 `test_agent_b.py` 的同族）。"""

    def extract(self, doc, lit_id, meta):
        return ([ConceptDraft(name="群", definition=f"来自 {lit_id} 的定义",
                              aliases=["group"], source_lit_id=lit_id)], [])


def _agent_b(store) -> AgentB:
    return AgentB(store, extractor=_OneConcept(), extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def test_the_pipeline_mirrors_every_concept_it_writes(store, monkeypatch):
    """正控（模拟过渡期，见 `_pre_flip`）：B 的 pipeline 写出来的概念两面都在。

    落刀之后盘上没有"另一侧"可比 ⇒ 这一条的过渡期形态只能造出来。它守的东西一个字
    没变：写侧每一处都镜像，那批读老表的查重代码才看得见这些概念；漏一处就是静默
    漏判（可能重复建概念），而两边行数都"有增长"，盘上看不出异常。
    """
    _pre_flip(monkeypatch)
    write_library_file(store, "0000/a.txt", "A group is a set with a binary operation.")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    res = _agent_b(store).run_once()
    assert res.concepts_created == 1, res
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is False, gaps
    assert gaps["statements_only"] == [], (
        "有新标准那一行却没有老表镜像 ⇒ B 的查重（读老表）看不见它："
        f"{gaps['statements_only']}")
    assert len(gaps["merged"]) == 1, gaps
    assert (store.data / "concepts.json").is_file(), "镜像那一份没落盘"


def test_after_the_flip_there_is_no_other_side_to_compare(store):
    """落刀之后：`transition_over=True`，而这一条不是真空的（盘上真有概念行）。

    反真空：不先写一条概念就断言"三个集合都空"，等于在比两个空集 —— 即使
    `mirror_gaps` 整个坏成"永远返回一份干净的读数"也照样绿。所以这里先钉住
    "新标准里确实有那一行"，再钉"没有另一侧"这个读数与它的理由。
    """
    out = CR.upsert(store, label="群", definition="带运算的集合")
    assert out["checked"] and out["mirrored"] is False, out
    rows = [r for r in store.rows("statements") if str(r.get("kind")) == "concept"]
    assert [r["stmt_id"] for r in rows] == [out["stmt_id"]], rows
    assert not (store.data / "concepts.json").exists(), "落刀之后不许再建老文件"

    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is True, gaps
    assert gaps["statements_only"] == [] and gaps["legacy_only"] == [], gaps
    assert gaps["merged"] == [], gaps
    assert gaps["reason"], "为什么'这一格不再适用'必须写在读数里（沉默会被读成没问题）"


def test_transition_over_is_false_the_moment_a_leftover_file_exists(store):
    """反真空（新加的一条，能被改坏）：盘上还留着老文件 ⇒ 不许报"过渡结束"。

    落刀干净与"还有一份没搬"在盘上不是同一件事：后者留着迁移前那份 `concepts.json`。
    把这两态折平（把 `stale_file` 一起并进 `transition_over`）之后，"老文件还在"
    这件事就只能靠人去翻目录，而 `statements_only` 那份告警会被静默掉。
    """
    CR.upsert(store, label="群", definition="带运算的集合")
    assert CR.mirror_gaps(store)["transition_over"] is True, "干净的一态先钉住"

    _stale_concept_file(store)
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["transition_over"] is False, gaps
    assert gaps["statements_only"] == [S.format_id(0)], (
        "老文件还在盘上 ⇒ 必须照旧按缺口报 —— 照这样才看得见「还有一份没搬」")


def test_a_write_that_skips_the_mirror_is_named(store, monkeypatch):
    """负控（模拟过渡期）：绕过镜像直接写 `statements` ⇒ 那一号被点名（判据不许瞎）。

    两个方向都要看得见：只有新标准的行是真缺口（`statements_only`），
    只有老表的行（老写侧还没搬完）不算缺口但要单列（`legacy_only`）——
    "两个方向都没有缺口"与"这一格根本不会报缺口"必须分得开。
    """
    _pre_flip(monkeypatch)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", CR.concept_statement(
            stmt_id="0009", label="没镜像", definition="x").to_dict())
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["statements_only"] == ["0009"], gaps

    with store.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", S.Concept(concept_id="0011", name="只有老表", definition="y",
                                        related_concepts=[], normalized_name="只有老表").to_dict())
    gaps = CR.mirror_gaps(store)
    assert gaps["legacy_only"] == ["0011"] and gaps["statements_only"] == ["0009"], gaps


def test_an_unreadable_legacy_table_is_not_a_clean_bill(store, monkeypatch):
    """三态（模拟过渡期）：老表读不成 ⇒ `checked=False` + 理由。

    落刀之后盘上没有"老表"这张表可读 ⇒ 这一态同样只能靠 `_pre_flip` 造出来；
    落刀之后的对应形态是"老文件还在盘上"（由
    `test_transition_over_is_false_the_moment_a_leftover_file_exists` 钉）。
    "判不了"与"没有缺口"不是同一件事：前者必须给 `checked=False` + 理由，
    而不是一份"看起来干净"的空缺口表。
    """
    _pre_flip(monkeypatch)
    CR.upsert(store, label="群", definition="带运算的集合")   # 真有一行，免得判据真空
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] is False and gaps["reason"], gaps
    assert gaps["statements_only"] == [] and gaps["legacy_only"] == [], (
        "判不了时不许给出一份「看起来干净」的空缺口表")
    assert gaps["transition_over"] is False, "判不了不是'过渡结束'"
