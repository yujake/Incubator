"""校验器：干净数据零错误，人为破坏后必须报出对应错误码（DESIGN.md §1 不变量 / §6.2）。"""

from __future__ import annotations

import json
from pathlib import Path

from agentflow import schema as S
from agentflow.store import Store
from agentflow.verify import verify_all


def _mutate_table(store: Store, table: str, fn) -> None:
    """直接改快照文件（模拟"人工编辑/外部脚本改坏了数据"）。"""
    path = store.data / S.TABLES[table]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc["rows"])
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _codes(report) -> list[str]:
    return [i.code for i in report.issues]


def _issue(report, code: str):
    hits = [i for i in report.issues if i.code == code]
    assert hits, f"未报出 {code}，实际错误码：{sorted(set(_codes(report)))}"
    return hits[0]


# --------------------------------------------------------------------------- 干净数据


def test_clean_data_has_no_errors(clean_store: Store) -> None:
    """自洽的数据集必须 ok=True、0 error（否则校验器本身不可信）。"""
    rep = verify_all(clean_store)
    assert rep.ok is True
    assert rep.errors == []
    assert rep.warnings == [], f"干净数据不应有警告：{[i.to_dict() for i in rep.warnings]}"
    assert rep.checked["literature"] == 1
    assert rep.checked["concepts"] == 2
    assert rep.checked["relations"] == 1


def test_demo_like_state_passes_deep_check(clean_store: Store) -> None:
    """deep 模式（重开文献复核引文）对自洽数据也必须零错误。"""
    from agentflow.extract import extract_text

    rep = verify_all(clean_store, deep=True, extract_text=extract_text)
    assert rep.ok is True, [i.to_dict() for i in rep.errors]
    assert rep.warnings == [], [i.to_dict() for i in rep.warnings]


# --------------------------------------------------------------------------- 人为破坏


def test_missing_literature_is_reported_as_dangling_lit(clean_store: Store) -> None:
    """删掉 relations.lit_id 指向的文献 → dangling_lit（error）。"""
    _mutate_table(clean_store, "literature", lambda rows: rows.clear())
    rep = verify_all(clean_store)
    issue = _issue(rep, "dangling_lit")
    assert issue.level == "error"
    assert issue.table == "relations"
    assert rep.ok is False


def test_wrong_related_concepts_is_reported_as_related_drift(clean_store: Store) -> None:
    """把某概念的 related_concepts 改错（仍升序）→ related_drift（warning，附"应为"）。"""
    _mutate_table(clean_store, "concepts", lambda rows: rows[0].__setitem__("related_concepts", []))
    rep = verify_all(clean_store)
    issue = _issue(rep, "related_drift")
    assert issue.level == "warning"
    assert issue.table == "concepts"
    assert "0001" in issue.message, "报告必须给出应派生的值，才能据以修复"


def test_wrong_group_key_is_reported_as_stale_group_key(clean_store: Store) -> None:
    """把 concept_group_key 改错 → stale_group_key（error，判重会因此失效）。"""
    _mutate_table(
        clean_store,
        "relations",
        lambda rows: rows[0].__setitem__("concept_group_key", "9998|9999"),
    )
    rep = verify_all(clean_store)
    issue = _issue(rep, "stale_group_key")
    assert issue.level == "error"
    assert rep.ok is False


def test_counter_behind_is_reported(clean_store: Store) -> None:
    """把 counters 调小（小于 max(已用 ID)+1）→ counter_behind（error，继续分配会撞号）。"""
    path = clean_store.data / "counters.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["counters"]["concept"] = 0
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rep = verify_all(clean_store)
    issue = _issue(rep, "counter_behind")
    assert issue.level == "error"
    assert issue.row_id == "concept"


def test_relation_on_unprocessed_literature_is_reported(clean_store: Store) -> None:
    """processed=false 的文献却拥有关系 → lit_not_processed（error，违反 §2.4 写入顺序）。"""
    _mutate_table(clean_store, "literature", lambda rows: rows[0].__setitem__("processed", False))
    rep = verify_all(clean_store)
    issue = _issue(rep, "lit_not_processed")
    assert issue.level == "error"
    assert issue.row_id == "0000"


def test_dangling_concept_reference_is_reported(clean_store: Store) -> None:
    """关系引用了不存在的概念 → dangling_concept（error）。"""
    _mutate_table(
        clean_store,
        "relations",
        lambda rows: rows[0].__setitem__("concept_ids", ["0000", "0007"]),
    )
    rep = verify_all(clean_store)
    assert _issue(rep, "dangling_concept").level == "error"


def test_missing_local_file_is_reported(clean_store: Store) -> None:
    """表里登记了 path 但文件不在 → file_missing（error，B 会跳过它）。"""
    (clean_store.library / "0000" / "source.txt").unlink()
    rep = verify_all(clean_store)
    assert _issue(rep, "file_missing").level == "error"


def test_duplicate_quote_inside_same_group_is_reported(clean_store: Store) -> None:
    """同概念组内出现两条相同引文的非 rejected 关系 → duplicate_quote（判重漏了）。"""
    from conftest import add_relation

    add_relation(
        clean_store,
        "0001",
        ["0000", "0001"],
        "0000",
        quote="An abelian group is a group in which the commutative law holds.",
        status="suspect",
    )
    rep = verify_all(clean_store)
    assert _issue(rep, "duplicate_quote").level == "error"


def test_unsorted_related_concepts_is_reported_by_schema_and_verify(clean_store: Store) -> None:
    """related_concepts 未升序：schema 级先报 schema_invalid，verify 不漏报。"""
    _mutate_table(
        clean_store,
        "concepts",
        lambda rows: rows[0].__setitem__("related_concepts", ["0001", "0001"]),
    )
    rep = verify_all(clean_store)
    assert "schema_invalid" in _codes(rep)
    assert rep.ok is False


def test_deep_verify_detects_quote_that_no_longer_matches(clean_store: Store) -> None:
    """deep 模式重开文献复核引文：把 quote 改坏后必须报 quote_not_found。"""
    from agentflow.extract import extract_text

    _mutate_table(clean_store, "relations", lambda rows: rows[0].__setitem__("quote", "彻底改写过的假引文"))
    rep = verify_all(clean_store, deep=True, extract_text=extract_text)
    issue = _issue(rep, "quote_not_found")
    assert issue.level == "error"


def test_verify_reports_id_gap_as_warning_not_error(tmp_path: Path) -> None:
    """ID 出现空洞只是 warning（空洞无害），不能因此让 ok=False 阻断流水线。"""
    from conftest import add_concept, sync_counters

    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "群")
    sync_counters(st)
    rep = verify_all(st)
    assert _issue(rep, "id_gap").level == "warning"
    assert rep.ok is True
