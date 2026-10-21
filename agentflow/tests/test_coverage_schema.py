"""`schema.check_array_invariants` 的判据测试（补零测试公开函数，等级 2）。

## 为什么单独一个文件（而不是追加到 `tests/test_schema.py`）

`tests/test_schema.py` 已经存在且有 39 条既有断言。本任务的硬约束是"不要改既有测试文件里的既有断言"，而往一个既有文件中间插入新块，很容易在后续并行编辑中与别人的改动冲突（本仓库明确说 `src/` 下有别的 agent 在动）。`tests/test_coverage_<模块>.py` 这个命名让"哪个模块的覆盖缺口被补过"一眼可查，也把新增断言与既有断言物理隔离。本轮新增的 8 个 `test_coverage_*.py` 都采用同一取舍（见 `docs/PROPOSALS.md` G-9/G-10 的口径说明）。

## 被测函数在判据链上的位置

`check_array_invariants` 是"集合字段必须升序去重"这条判据的唯一权威检查点（docstring 逐字：由 `validate_table` 调用）。所以这里的断言必须打在判据上：哪个字段、因为什么原因（类型不是数组 vs 没升序去重）被判违规，而不是"返回了一个非空列表"。

## S1r 并表（`SCHEMA_VERSION=2`）之后的改动（两条用例改写，判据不变）

并表把 `concepts` 表从 `schema.TABLES` / `ARRAY_FIELD_KINDS` 里真删（概念行住 `statements`）⇒ 这两条挂在它上面的用例失去对象：

- `test_check_array_invariants_reports_mixed_type_elements_instead_of_raising`：原先拿 `concepts.related_concepts` 当混类型标本 ⇒ 换成 `relations.concept_ids`（另一张仍在的表上声明为 `set` 的字段；`related_concepts` 这个名字随表退役）。保护意图逐字不变：混类型数组要报"元素不是字符串"，不许让判据自己抛 `TypeError`（R-05），且不许被报成"未升序去重"。
- `test_validate_table_reports_a_mixed_type_row_as_value_error`：原先走 `validate_table("concepts", …)` 这条真正的入口 ⇒ 换成 `validate_table("statements", …)` + `derived_from`（同一张表上声明为 `set` 的字段）。入口与判据都不变：`row_from_dict` + `obj.validate()` + 集中检查这条链上任一处先比较异类型，`TypeError` 都会从 `except ValueError` 的缝里逃出去。"""

from __future__ import annotations

import pytest

from agentflow import schema as S


# ============================================================ 夹具的取法（§5.3）


def _set_fields(table: str) -> list[str]:
    """从 `schema.ARRAY_FIELD_KINDS` 反查某表的 set 字段 —— 不写死字段名。

    §5.3 的判据是"夹具不许写死表名/角色名/kind 列表"。字段名同理：
    写死 `supporting_lit_ids` 会在有人把它改成 seq 时静默失效。
    """
    return [f for f, k in S.array_kinds(table).items() if k == "set"]


def _a_table_with_set_fields() -> str:
    """挑一张真的有 set 字段的表。挑不到就是本文件的前提崩了，应当红。"""
    for table in S.TABLES:
        if _set_fields(table):
            return table
    pytest.fail("schema.TABLES 里没有任何声明为 set 的数组字段 ⇒ 本文件的判据失去对象")


# ============================================================ 正向


def test_check_array_invariants_accepts_sorted_and_deduped_set_field():
    """正向：集合字段升序且去重时零违规。

    为什么这条必须存在：一个"永远报违规"的实现能通过所有负控 ——
    正向断言是它的反面（`DEVELOPMENT.md` §5.1）。
    """
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, ["a", "b", "c"])
    assert S.check_array_invariants(table, obj) == []


def test_check_array_invariants_accepts_empty_set_field():
    """正向（边界）：空集合是合法的"升序去重"结果（空是"没有"，不是 None）。"""
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, [])
    assert S.check_array_invariants(table, obj) == []


# ============================================================ 负控


def test_check_array_invariants_rejects_unsorted_set_field():
    """负控：集合字段未升序必须被判违规，且 reason 指出是哪一个字段。

    为什么断言字段名而不是只断言"非空"：`validate_table` 会把这条违规
    当成表的错误报出来，人要靠字段名去改数据。只断言长度等于把定位信息丢掉。
    """
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, ["b", "a"])
    bad = S.check_array_invariants(table, obj)
    assert len(bad) == 1, bad
    assert bad[0].startswith(field), bad
    assert "未升序去重" in bad[0], bad


def test_check_array_invariants_rejects_duplicated_set_field():
    """负控：集合字段未去重必须被判违规（这是"集合"二字的另一半）。

    与上一条分开写是刻意的：`["b","a"]` 只测了排序，`["a","a"]` 只测了去重。
    合成一条会留下"只修了排序"的实现照样通过的空档。
    """
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, ["a", "a"])
    bad = S.check_array_invariants(table, obj)
    assert len(bad) == 1, bad
    assert bad[0].startswith(field) and "未升序去重" in bad[0], bad


def test_check_array_invariants_rejects_non_list_value_for_set_field():
    """负控：声明为集合却拿到非数组 ⇒ 报的是"类型不对"，不是"没排序"。

    这两种 reason 必须分得开（三态纪律的近亲）：把"值根本不是列表"报成
    "未升序去重"会让人去查一个不存在的排序问题。
    """
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, "abc")
    bad = S.check_array_invariants(table, obj)
    assert len(bad) == 1, bad
    assert "不是数组" in bad[0], bad
    assert "未升序去重" not in bad[0], bad


def test_check_array_invariants_ignores_seq_fields_and_unregistered_tables():
    """负控（防误伤）：seq 字段不排序也不去重；未登记的表一律零违规。

    为什么这是负控而不是"又一条正向"：`relation_chain` 这类 seq 字段
    顺序就是推理路径（schema 注释逐字："合成一个字段就必然丢掉一半信息"）。
    若 `check_array_invariants` 误把 seq 当 set 检查，它会把正确的数据判成坏数据
    ——"假报警比不校验更糟"（`LESSONS.md` C2）。
    """
    seq_pairs = [(t, f) for t in S.TABLES for f, k in S.array_kinds(t).items() if k == "seq"]
    assert seq_pairs, "schema 里没有任何 seq 字段 ⇒ 本断言失去对象"
    for table, field in seq_pairs:
        row_cls = S.TABLES[table]["row"]
        obj = row_cls.__new__(row_cls)
        setattr(obj, field, ["z", "a", "a"])  # 故意的乱序 + 重复
        assert S.check_array_invariants(table, obj) == [], f"{table}.{field} 是 seq，不该被查"
    assert S.check_array_invariants("__not_a_table__", object()) == []


def test_check_array_invariants_none_value_is_skipped_not_flagged():
    """三态纪律：字段缺失/None ≠ "集合违规"。

    `None` 是"这一行没给这个字段"，与"给了但没排序"是两件事。docstring 的实现
    对 `None` 是 `continue`。这条断言把它钉住：把 `None` 报成违规会让
    每一行新建的、尚未填该字段的数据都变红。
    """
    table = _a_table_with_set_fields()
    field = _set_fields(table)[0]
    row_cls = S.TABLES[table]["row"]
    obj = row_cls.__new__(row_cls)
    setattr(obj, field, None)
    assert S.check_array_invariants(table, obj) == []


def test_check_array_invariants_reports_mixed_type_elements_instead_of_raising():
    """R-05 负控（改前必红）：混类型数组要报问题，不许让判据自己抛 `TypeError`。

    改前形态（旧实现那一行表达式）在 `["0001", 2]` 上是 `TypeError: '<' not supported between instances of 'int' and 'str'` —— 那不是"库里有一条坏数据"，而是判据炸了：`validate_table` 只接 `ValueError`，`store.rebuild` 的灾难恢复链同样只接 `ValueError` ⇒ 一条混类型的行会以 `TypeError` 打断整次重建（重建不可逆）。

    三档必须分得开：这一条走"元素不是字符串"，不许被报成"未升序去重"（那会让人去查一个不存在的排序问题 —— `:110` 那条同族的理由）。

    并表之后标本是 `relations.concept_ids`（`related_concepts` 随 `concepts` 表退役；本条判据本来就与该字段的名字无关，只要求它是"声明为 set 的字段"）。"""
    obj = S.Relation.__new__(S.Relation)
    obj.concept_ids = ["0001", 2]
    bad = S.check_array_invariants("relations", obj)
    assert len(bad) == 1, bad
    assert bad[0].startswith("concept_ids"), bad
    assert "元素不是字符串" in bad[0], bad
    assert "未升序去重" not in bad[0], bad


def test_check_array_invariants_mixed_type_judge_covers_every_set_field():
    """反真空：混类型判据必须真的走遍每一个 set 字段（不是只照顾 concepts）。

    只测一个字段会让"另外 8 个 set 字段仍会 `TypeError`"这一格无人管 ——
    R-05 的根因恰恰是"7 处行级内联件 + 表级一处，任意漏一处 TypeError 仍会逃逸"。
    """
    checked = 0
    for table in S.TABLES:
        row_cls = S.TABLES[table]["row"]
        for field, kind in S.array_kinds(table).items():
            if kind != "set":
                continue
            obj = row_cls.__new__(row_cls)
            setattr(obj, field, ["0001", 2])
            bad = S.check_array_invariants(table, obj)
            assert len(bad) == 1 and "元素不是字符串" in bad[0], (table, field, bad)
            checked += 1
    assert checked >= 9, f"只查到 {checked} 个 set 字段 —— 判据的扫描面缩水了"


def test_validate_table_reports_a_mixed_type_row_as_value_error():
    """R-05（表级路径）：`validate_table` 上混类型的行必须是 `ValueError`，不是 `TypeError`。

    这一条走的是真正的入口（`row_from_dict` + `obj.validate()` + 集中检查），
    而不是直接调谓词 —— 根因就在这两条路径上：任意一处先比较异类型，
    `TypeError` 都会从 `except ValueError` 的缝里逃出去。

    并表之后标本是 `statements.derived_from`（`concepts` 表已删）。
    """
    doc = {"schema_version": S.SCHEMA_VERSION,
           "rows": [{"stmt_id": "0001", "origin": "own_result", "kind": "theorem",
                     "statement_full": "命题正文（夹具）",
                     "quote_verified": None, "quote_reason": "自产结果（测试夹具）",
                     "derived_from": ["0001", 2]}]}
    with pytest.raises(ValueError) as exc:
        S.validate_table("statements", doc)
    assert "元素不是字符串" in str(exc.value), exc.value
