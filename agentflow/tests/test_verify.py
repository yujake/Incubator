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


# ------------------------------------------------ 存量概念行的 `proof_text` 进审计
#
# 2026-10-21（本批缺陷三）：概念行带 `proof_text` 这件事此前**只在读侧**被点名
# （`verifications.proof_review_gap` 的 `why` 写着"概念行不该带证明文本"），
# 而 `verify._check_13` 的 error 清单里没有它 —— 于是"审计通过"这句话在一个
# 装满历史哨兵行的工作区面前是假的。下面三条把新增的那一条钉住：
# ① 有哨兵行 ⇒ **1 条** error 且点名 `stmt_id`；② 干净库 ⇒ 0 条；
# ③ 负控：把判据本体摘掉 / 把那条 issue 从报告里摘掉 ⇒ 判据红。
# 选择这组口径的理由：`verify_all` 是交付面上唯一被读成"没有问题"的那一栏，
# 它漏掉的类别不会在任何别处变成红。


def _first_concept_stmt_id(store: Store) -> str:
    """干净夹具里第一条概念行的 `stmt_id`（并表之后概念住在 `statements`）。"""
    rows = [r for r in store.rows("statements") if str(r.get("kind") or "") == "concept"]
    assert rows, "夹具里一条概念行都没有 ⇒ 这条判据没素材"
    return str(rows[0].get("stmt_id") or "")


def _concept_proof_issues(report) -> list:
    """只挑 `concept_row_carries_proof_text` 那一条的 issue（判据的读法一处）。"""
    from agentflow.verify import CONCEPT_PROOF_TEXT_CODE

    return [i for i in report.issues if i.code == CONCEPT_PROOF_TEXT_CODE]


def test_a_clean_library_has_no_concept_proof_text_error(clean_store: Store) -> None:
    """② 正控（反真空）：干净库 ⇒ 这一条 **0 条**（不是"查不了"）。

    只判"有哨兵行会红"而不判"干净库是绿的"，那条判据可以靠"永远报一条"通过 ——
    那是本仓最忌的假绿方向（审计天天报警，人就开始忽略它）。
    """
    rep = verify_all(clean_store)
    assert _concept_proof_issues(rep) == [], [i.to_dict() for i in _concept_proof_issues(rep)]
    assert rep.ok is True, [i.to_dict() for i in rep.errors]


def test_a_concept_row_carrying_proof_text_is_one_named_error(clean_store: Store) -> None:
    """① 正控：造一条带哨兵 `concept:primitive` 的概念行 ⇒ **1 条** error、点名 `stmt_id`。

    为什么把"恰好 1 条"也写进断言：`_check_13` 里已经有一条"假 proof_review"的点名
    （`proof_review_without_verification`），两条判据若在同一行上各报一次，
    读的人会以为"两处都坏了"，而其实是同一件事说两遍。
    """
    from agentflow.verify import CONCEPT_PROOF_TEXT_CODE

    stmt_id = _first_concept_stmt_id(clean_store)
    _mutate_table(clean_store, "statements",
                  lambda rows: [r.__setitem__("proof_text", "concept:primitive")
                                for r in rows if str(r.get("stmt_id") or "") == stmt_id])
    rep = verify_all(clean_store)
    hits = _concept_proof_issues(rep)
    assert len(hits) == 1, [i.to_dict() for i in rep.issues]
    issue = hits[0]
    assert issue.level == "error", issue.to_dict()
    assert issue.code == CONCEPT_PROOF_TEXT_CODE, issue.to_dict()
    assert issue.table == "statements", issue.to_dict()
    # 点名到行：`row_id` 就是那一条命题的号，`message` 里也逐字带着它。
    assert issue.row_id == stmt_id, (issue.to_dict(), stmt_id)
    assert stmt_id in issue.message, issue.message
    # 来源也要点名（`created_by`）—— "谁写进来的"是这一条读数的一半。
    assert "created_by" in issue.message, issue.message
    # 全库的 error 就这一条：没有把别的判据连累成红（否则这条读数是混的）。
    assert [i.code for i in rep.errors] == [CONCEPT_PROOF_TEXT_CODE], [
        i.to_dict() for i in rep.errors]


def test_removing_the_scan_makes_the_concept_proof_text_criterion_red(
        clean_store: Store, monkeypatch) -> None:
    """③ 负控（判据本体被摘）：把 `concept_rows_with_proof_text` 换成"永远没有" ⇒ 红。

    摘的是**判据本体**（`verify.concept_rows_with_proof_text`），不是某条断言的字符串：
    这样"红"才说明上面那条正控真的走这条扫描，而不是碰巧读了别处的数据。
    """
    from agentflow import verify as V

    stmt_id = _first_concept_stmt_id(clean_store)
    _mutate_table(clean_store, "statements",
                  lambda rows: [r.__setitem__("proof_text", "concept:primitive")
                                for r in rows if str(r.get("stmt_id") or "") == stmt_id])
    assert len(_concept_proof_issues(verify_all(clean_store))) == 1

    monkeypatch.setattr(V, "concept_rows_with_proof_text", lambda rows: [])
    assert _concept_proof_issues(verify_all(clean_store)) == [], (
        "把判据本体摘掉之后还报得出来 ⇒ 这一条不是那条扫描给的")


def test_removing_the_issue_from_the_report_makes_the_criterion_red(clean_store: Store) -> None:
    """③ 负控（issue 被摘）：从报告里删掉那一条 ⇒ 同一个读法必须红。

    与上一条负控分工：那条摘的是**扫描**（实现面），这条摘的是**报告里的那一格**
    （读数面）—— 两者都能让"审计说这一行有问题"这句话消失，而后者正是
    "有人把这条 issue 从 audit 里删掉"的那种改动。
    """
    stmt_id = _first_concept_stmt_id(clean_store)
    _mutate_table(clean_store, "statements",
                  lambda rows: [r.__setitem__("proof_text", "concept:primitive")
                                for r in rows if str(r.get("stmt_id") or "") == stmt_id])
    rep = verify_all(clean_store)
    assert len(_concept_proof_issues(rep)) == 1

    # 把那条 issue 从报告里摘掉（模拟"这一格被删"）。
    from agentflow.verify import CONCEPT_PROOF_TEXT_CODE

    rep.issues = [i for i in rep.issues if i.code != CONCEPT_PROOF_TEXT_CODE]
    assert _concept_proof_issues(rep) == [], (
        "删掉之后还读得到那一条 ⇒ 这条负控没摘到东西")


def test_a_concept_row_without_proof_text_is_not_flagged(clean_store: Store) -> None:
    """反真空：把**别的**行（非概念行）塞上 `proof_text` 不许被这一条抓。

    这一条守的是"扫描只挑 `kind == 'concept'`"：不限制的话，
    "所有带 `proof_text` 的行"都会被报成概念行污染，而那正是真正需要 `proof_text` 的
    那些命题 —— 判据一开就全是假红。
    """
    from agentflow.verify import concept_rows_with_proof_text

    others = [r for r in clean_store.rows("statements")
              if str(r.get("kind") or "") != "concept"]
    for row in others:
        row["proof_text"] = "一段真实的证明正文"
    assert concept_rows_with_proof_text(others) == [], (
        "非概念行被当成了'概念行带证明文本'")


# ------------------------ `active` 文献命题的逐字回验：概念行不在适用面里（2026-10-21）
#
# 起因（真机读数）：`real:fresh-demo` 的深验比冻结快照多出 **4 条**
# `active_stmt_quote_unverified`，4 条全是概念行（`origin=external_lit`、`status=active`、
# `quote_verified=None`）。判断的方向不是"把 demo 数据补上逐字出处"，而是**这一条规则对
# 概念行不适用** —— 三条依据（逐字）都写在 `verify.active_stmt_needs_quote_check` 上面：
# ① 概念行的 `source_lit_id` 是"术语从哪一篇抽出来的"，不是"定义逐字抄自那里"；
# ② `quote_verified` 的比对对象是 `proof_text`，而概念行结构上不许带 `proof_text`
#    （`conceptrows.concept_statement` 当场 `ValueError`）⇒ 这一条对概念行永远不可能满足；
# ③ 读侧 `verifications.proof_review_gap` / `weaker_than_evidence_gaps` 早就显式跳过概念行
#    （「概念不参与等级链」，`draft/97` §14.5）。
#
# 下面三条：① 概念行 ⇒ 不报；② 反真空 ⇒ 同一行换成**非概念**命题就照旧报；
# ③ 负控 ⇒ 把判据本体（`active_stmt_needs_quote_check`）换成"永远不适用"⇒ ② 红。


def _put_statement(store: Store, row) -> None:
    """把一条已经 `validate()` 过的 `Statement` 落进库（夹具的写侧，走正常事务）。

    落完立刻对齐计数器（`conftest.sync_counters`）：手工插行不同步它，`verify_all` 会报一条
    与"本次要验证的不变量"毫无关系的 `counter_behind` —— 那是噪音，不是判据。
    """
    from conftest import sync_counters

    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)


def _quote_unverified(rep) -> list:
    """只挑 `active_stmt_quote_unverified` 那一条的 issue（判据的读法一处）。"""
    return [i for i in rep.issues if i.code == "active_stmt_quote_unverified"]


def _concept_row_like_the_demo(store: Store, sid: str = "0002"):
    """造一条**与 demo 同形**的概念行：`external_lit` + `active` + `quote_verified=None`。

    刻意走生产写口（`conceptrows.concept_statement`），不手搓字段：这条判据的分界线
    必须建立在"真写进来的那种行"上，否则判的是一个不存在的形状。
    """
    lit = str(store.rows("literature")[0]["lit_id"])
    row = CR.concept_statement(stmt_id=sid, label="ring",
                               definition="a ring in which every nonzero element has an "
                                          "inverse（这条定义只为判据而造）",
                               source_lit_id=lit)
    assert row.origin == "external_lit" and row.status == "active", (row.origin, row.status)
    assert row.quote_verified is None and row.proof_text == ""
    return row


def test_a_concept_row_is_not_an_unverified_literature_quote(clean_store: Store) -> None:
    """① 正控：概念行（与 demo 同形）⇒ **不**报 `active_stmt_quote_unverified`。

    为什么这条不是"把规则放宽"：概念行既没有"原文摘录"（`source_lit_id` 记的是术语来路），
    也没有可比对的 `proof_text`（结构上不许带）⇒ 这一条对它恒不可满足，留着就是恒红。
    """
    _put_statement(clean_store, _concept_row_like_the_demo(clean_store))
    rep = verify_all(clean_store)
    assert _quote_unverified(rep) == [], [i.to_dict() for i in _quote_unverified(rep)]
    assert rep.ok is True, [i.to_dict() for i in rep.errors]


def test_an_unsourced_non_concept_statement_still_warns(clean_store: Store) -> None:
    """② 反真空：**非概念**命题真没逐字回验 ⇒ 这一条照旧出（证明规则没被整体摘掉）。

    素材与上一条只差 `kind` 一格 —— 分界线就是它，所以这一对判据读的是同一个事实的两面。
    """
    row = _concept_row_like_the_demo(clean_store)
    _put_statement(clean_store, row)
    # 把这一行的 `kind` 换成非概念（其余一个字段不动）：它现在是一条"文献命题"，
    # 说得出出处、却拿不出逐字回验 ⇒ 正是这一条 warning 的靶子。
    _mutate_table(clean_store, "statements",
                  lambda rows: [r.__setitem__("kind", "theorem")
                                for r in rows if str(r.get("stmt_id") or "") == "0002"])
    hits = _quote_unverified(verify_all(clean_store))
    assert [i.row_id for i in hits] == ["0002"], [i.to_dict() for i in hits]
    assert hits[0].level == "warning", hits[0].to_dict()
    assert "quote_verified" in hits[0].message, hits[0].message


def test_removing_the_quote_rule_makes_the_anti_vacuum_assertion_red(
        clean_store: Store, monkeypatch) -> None:
    """③ 负控：把判据本体换成"永远不适用" ⇒ ② 那条断言必须红。

    摘的是**判据本体**（`verify.active_stmt_needs_quote_check`），不是某条断言的字符串：
    这样"红"才说明 ② 真的走这一条判据，而不是碰巧读了别处的数据。
    """
    from agentflow import verify as V

    _put_statement(clean_store, _concept_row_like_the_demo(clean_store))
    _mutate_table(clean_store, "statements",
                  lambda rows: [r.__setitem__("kind", "theorem")
                                for r in rows if str(r.get("stmt_id") or "") == "0002"])
    assert [i.row_id for i in _quote_unverified(verify_all(clean_store))] == ["0002"]

    monkeypatch.setattr(V, "active_stmt_needs_quote_check", lambda row: False)
    assert _quote_unverified(verify_all(clean_store)) == [], (
        "把判据本体摘掉之后还报得出来 ⇒ ② 不是这条判据给的（那条断言是真空的）")
