# -*- coding: utf-8 -*-
"""过渡期的镜像完整性：新标准写进来的概念，老表那一份在不在。

## 为什么这是一条判据（而不是一句注释）

过渡期的读侧已经全部走合成视图了，但 B 的 pipeline 里还有几处 `tx.rows("concepts")`
（概念查重、别名合并、`related_concepts` 重算）读的是老表原始行 —— 它们要写回去、
要带老表专有字段（`updated_at`、合并载荷、`merged_into`），所以那一批留到落刀那一笔再改。

那个"留到落刀"之所以安全，唯一的前提是：写侧每一处都把新标准那一行镜像进老表。
一旦哪一处忘了镜像，那批概念就会在 pipeline 的查重里消失（静默漏判、可能重复建概念），
而盘上看起来一切正常（两边行数都"有增长"）。所以 `conceptrows.mirror_gaps` 是判据：
`statements_only` 非空就是一条真缺陷 —— 要么补镜像，要么把那一处写侧搬过来。

## 三个面

- 正控：B 的 pipeline 跑一趟 ⇒ 它写的每个概念两面都在（`statements_only` 为空）；
- 负控：绕过镜像直接写 `statements` ⇒ 那一号被点名（判据不许瞎）；
- 三态：老表读不成 ⇒ `checked=False` + 理由（"判不了"不等于"没有缺口"）。
"""

from __future__ import annotations

from conftest import add_literature, write_library_file
from agentflow import conceptrows as CR
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.llm import ConceptDraft


class _OneConcept:
    """确定性抽取器替身：每次返回同一个概念（与 `test_agent_b.py` 的同族）。"""

    def extract(self, doc, lit_id, meta):
        return ([ConceptDraft(name="群", definition=f"来自 {lit_id} 的定义",
                              aliases=["group"], source_lit_id=lit_id)], [])


def _agent_b(store) -> AgentB:
    return AgentB(store, extractor=_OneConcept(), extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def test_the_pipeline_mirrors_every_concept_it_writes(store):
    """正控：B 的 pipeline 写出来的概念，老表那一份必须在（否则查重会静默漏判）。"""
    write_library_file(store, "0000/a.txt", "A group is a set with a binary operation.")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    res = _agent_b(store).run_once()
    assert res.concepts_created == 1, res
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"], gaps
    assert gaps["statements_only"] == [], (
        "有新标准那一行却没有老表镜像 ⇒ B 的查重（读老表）看不见它："
        f"{gaps['statements_only']}")
    assert len(gaps["merged"]) == 1, gaps


def test_a_write_that_skips_the_mirror_is_named(store):
    """负控：绕过镜像直接写 `statements` ⇒ 那一号被点名（判据不许瞎）。"""
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", CR.concept_statement(
            stmt_id="0009", label="没镜像", definition="x").to_dict())
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] and gaps["statements_only"] == ["0009"], gaps
    # 另一个方向也要看得见：只有老表的行（老写侧还没搬完）不算缺口，但要单列
    from agentflow import schema as S

    with store.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", S.Concept(concept_id="0011", name="只有老表", definition="y",
                                        related_concepts=[], normalized_name="只有老表").to_dict())
    gaps = CR.mirror_gaps(store)
    assert gaps["legacy_only"] == ["0011"] and gaps["statements_only"] == ["0009"], gaps


def test_an_unreadable_legacy_table_is_not_a_clean_bill(store):
    """三态：老表读不成 ⇒ `checked=False` + 理由（"判不了"不等于"没有缺口"）。"""
    (store.data / "concepts.json").write_text("{ 这不是 JSON", encoding="utf-8")
    gaps = CR.mirror_gaps(store)
    assert gaps["checked"] is False and gaps["reason"], gaps
    assert gaps["statements_only"] == [] and gaps["legacy_only"] == [], (
        "判不了时不许给出一份「看起来干净」的空缺口表")
