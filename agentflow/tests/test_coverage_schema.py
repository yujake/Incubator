"""`schema.check_array_invariants` 的判据测试（补零测试公开函数，等级 2）。

## 为什么单独一个文件（而不是追加到 `tests/test_schema.py`）

`tests/test_schema.py` 已经存在且有 39 条既有断言。本任务的硬约束是
"不要改既有测试文件里的既有断言"，而往一个既有文件中间插入新块，
很容易在后续并行编辑中与别人的改动冲突（本仓库明确说 `src/` 下有别的 agent 在动）。
`tests/test_coverage_<模块>.py` 这个命名让"哪个模块的覆盖缺口被补过"一眼可查，
也把新增断言与既有断言物理隔离。本轮新增的 8 个 `test_coverage_*.py`
都采用同一取舍（见 `docs/PROPOSALS.md` G-9/G-10 的口径说明）。

## 被测函数在判据链上的位置

`check_array_invariants` 是"集合字段必须升序去重"这条判据的唯一权威检查点
（docstring 逐字：由 `validate_table` 调用）。所以这里的断言必须打在
判据上：哪个字段、因为什么原因（类型不是数组 vs 没升序去重）被判违规，
而不是"返回了一个非空列表"。
"""

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
