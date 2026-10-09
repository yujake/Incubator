"""校验器：干净数据零错误，人为破坏后必须报出对应错误码（DESIGN.md §1 不变量 / §6.2）。"""

from __future__ import annotations

import json
from pathlib import Path

from agentflow import conceptrows as CR
from agentflow import dedup as D
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
    # 概念行并表之后住 `statements`（`kind="concept"`）⇒ 逐表读数那一格现在叫
    # `statements`（老写法读 `checked["concepts"]` 会当场 KeyError）。这里同时断
    # "审计真的读到了那 2 条概念"：只断表行数会漏掉"概念视图没读到、恰好语句表里
    # 有别的行把数补齐了"这一种坏法。
    assert rep.checked["statements"] == 2
    assert [c["concept_id"] for c in CR.view(clean_store, shape="legacy")["rows"]] == ["0000", "0001"]
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


def test_related_concepts_drift_has_no_home_in_the_new_standard(clean_store: Store) -> None:
    """`related_concepts` 不是新标准的一格：真相由 `relations` 表派生，"没判"必须看得见。

    改写自 `test_wrong_related_concepts_is_reported_as_related_drift`（原文：把
    `concepts.json` 里某行的 `related_concepts` 改错 → 断言 verify 报
    `related_drift`）。并表之后那一格在新标准里没有承载点：`view(shape="legacy")`
    对 `statements` 那一档一律投影成空列表并带 `legacy_related=False`，
    `verify._check_4` 据它跳过这条判据 ⇒ "改一格看它报红"没有可改的对象了
    （这不是判据被放宽，是那一格随老表退役）。

    保护意图仍在，三段都能失败：
    ① 真相可派生：一跳邻居由 `relations` 现算 —— 这正是 `verify` 的 `related_drift`
       拿去比的那一侧（新标准里没有"表里那一格"⇒ 派生值本身就是真相）；
    ② 跳过可见：verify 把"这一版没有这一格 ⇒ 这一条没判"的行数记进
       `checked["related_concepts_skipped_new_standard"]`（"没判"不许与
       "判过没问题"同形，这是本项目最贵的教训），且不许因此冒出假红；
    ③ 负控：①不恒真 —— 关系表一变，派生值真的会变。
    """
    relations = clean_store.rows("relations")
    assert D.derive_related_concepts("0000", relations, include_suspect=True) == ["0001"]
    assert D.derive_related_concepts("0001", relations, include_suspect=True) == ["0000"]

    view = CR.view(clean_store, shape="legacy")
    assert view["checked"] is True
    assert {c["concept_id"]: (c["legacy_related"], c["related_concepts"]) for c in view["rows"]} == {
        "0000": (False, []),
        "0001": (False, []),
    }, "新标准那一档没有这一格：投影必须明说'空是因为没有这一格'（legacy_related=False）"

    rep = verify_all(clean_store)
    assert rep.checked["related_concepts_skipped_new_standard"] == 2, (
        "'这一条没判'必须是一个读数（少判了几行不许悄悄消失）"
    )
    assert "related_drift" not in _codes(rep), "新标准里没有这一格 ⇒ 不许冒出假红"

    # ③ 负控：派生值随关系表变（否则 ① 是恒真的）
    _mutate_table(clean_store, "relations", lambda rows: rows.clear())
    assert D.derive_related_concepts("0000", clean_store.rows("relations"), include_suspect=True) == []


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
    """把 counters 调小（小于 max(已用 ID)+1）→ counter_behind（error，继续分配会撞号）。

    并表之后概念行吃的是 `stmt` 这一格计数器（`concept` 那一档随老表退役）。
    判据本身一个字没变：这一格守的是"概念/命题共用的那个 4 位号空间不许落后于
    表里已经用掉的号"。拿退役的 `concept` 那一格去调小，verify 已经不遍历它
    （`ID_COUNTERS` 里没有这一档）⇒ 那条断言会恒真。
    """
    path = clean_store.data / "counters.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["counters"]["stmt"] = 0        # 概念行（statements 里 kind="concept"）已用到 0001
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rep = verify_all(clean_store)
    issue = _issue(rep, "counter_behind")
    assert issue.level == "error"
    assert issue.row_id == "stmt"


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


def test_unsorted_set_field_is_reported_by_schema_and_verify(clean_store: Store) -> None:
    """未升序去重的集合字段：schema 级先报 schema_invalid，verify 不漏报。

    改写自 `test_unsorted_related_concepts_is_reported_by_schema_and_verify`（原文
    改的是概念行的 `related_concepts` —— 老表里它被声明为 set）：并表之后那一格在
    新标准里不存在，没有可改的对象了。声明面（`schema.ARRAY_FIELD_KINDS`）对概念行
    照旧在，只是换到了 `statements.derived_from`（同样声明为 set）⇒ 改它照样能失败：
    这一格不再被声明为 set、或表级校验不再转发 `_set_problems`，这条就红。
    （`statements.aliases` 是 seq，"未排序"对它是合法的 —— 不能拿它当替身。）
    """
    _mutate_table(
        clean_store,
        "statements",
        lambda rows: rows[0].__setitem__("derived_from", ["0001", "0001"]),
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
