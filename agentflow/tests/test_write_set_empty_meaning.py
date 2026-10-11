"""`write_set_of` 的三态：空写集的两种含义不许再折平（CS-14，批 R21）。

`WRITE_SETS[role] == frozenset()` 有两个完全不同的来源，而它们此前返回同一个值
（全部 16 张表），与"完全不认识的执行单元"也返回同一个值：

- M：召唤本身会写 `tasks`、派生的子任务可能写任何东西 ⇒ 并发上必须与任何人串行；
- V：台账是文件（`verifications/<4 位>.jsonl`）、没有子代理 ⇒ 真·空集，
  与任何人的表写集都不冲突；
- 未知（不在 `WRITE_SETS` 里）：不知道 ⇒ 保守 ⇒ 当它能写任何表。

四个方向都钉（正控两个 + 负控两个），因为这一格的缺陷形态就是"三种情形长得一样"：
看一眼返回值分不出是"没有表写集"还是"不写任何表"还是"不认识"。
"""

from __future__ import annotations

import pytest

from agentflow import capabilities as C


def test_a_role_with_a_real_write_set_keeps_it() -> None:
    """有写集的角色照旧返回它自己的那一份（本批不动这一档）。"""
    assert C.write_set_of("B") == C.WRITE_SETS["B"]
    assert C.write_set_of("B")


def test_the_two_empty_write_sets_do_not_collapse() -> None:
    """M 与 V 都是空写集，但并发含义相反 ⇒ 返回值必须不同（这就是 CS-14）。"""
    assert C.WRITE_SETS["M"] == frozenset(), "夹具前提崩了：M 的写集应当还是空集"
    assert C.WRITE_SETS["V"] == frozenset(), "夹具前提崩了：V 的写集应当还是空集"

    assert C.write_set_of("V") == frozenset(), (
        "V 写的是文件台账、没有子代理 ⇒ 真·空集（它不该与别人的表写集冲突）")
    assert C.write_set_of("M") == C.write_set_of("Z"), (
        "M 的空写集不是'不写任何表'：它派生的子任务可能写任何东西 ⇒ 并发上按全部表算")


def test_the_concurrency_reading_follows_the_meaning() -> None:
    """并发轴的读数跟着含义走：V 可与写者同波，M 不行。"""
    assert C.write_sets_intersect("V", "B") is False, (
        "V 是真·空集 ⇒ 与 B 的表写集不相交（本批之前它被判成'与所有人相交'）")
    assert C.write_sets_intersect("M", "B") is True, "M 必须与写者串行"


def test_an_unknown_role_is_still_conservative() -> None:
    """反真空之一：未知角色仍然保守（这一档是本批刻意保留的）。"""
    assert C.write_set_of("不存在的角色") == C.write_set_of("Z") == C.write_set_of("M")
    assert len(C.write_set_of("Z")) > 0, "未知角色必须被当成写者"


def test_an_unregistered_empty_write_set_falls_back_to_conservative(monkeypatch) -> None:
    """反真空之二：登记表里没有的空写集 ⇒ 退回保守那一档（不是真·空集）。

    这一条钉的是"新加了一个空写集角色、忘了登记并发含义"的形态：它必须落到
    '可能写任何表'，而不是静默地变成'与任何人可并发'。
    """
    monkeypatch.delitem(C.EMPTY_WRITE_SETS, "V")
    assert C.write_set_of("V") == C.write_set_of("Z"), (
        "没登记并发含义的空写集必须退回保守档（与'不认识'同形）")


def test_the_registry_matches_the_empty_write_sets_exactly() -> None:
    """登记表与盘上的空写集角色逐字对齐（`assert_capabilities` 的 [6b] 也查这个）。"""
    empty_roles = {r for r, ws in C.WRITE_SETS.items() if not ws}
    assert empty_roles == set(C.EMPTY_WRITE_SETS), (
        f"空写集角色 {sorted(empty_roles)} 与登记表 {sorted(C.EMPTY_WRITE_SETS)} 不一致")
    assert empty_roles, "一个空写集角色都没有 ⇒ 这条判据是真空的"
    for role, entry in C.EMPTY_WRITE_SETS.items():
        assert entry.why.strip(), f"{role} 的并发含义没写理由（读的人只能猜）"


def test_the_assertion_sees_a_missing_registration(monkeypatch) -> None:
    """反负控：把登记表挖掉一格 ⇒ `assert_capabilities` 必须当场红。"""
    monkeypatch.delitem(C.EMPTY_WRITE_SETS, "V")
    with pytest.raises(AssertionError) as err:
        C.assert_capabilities()
    assert "EMPTY_WRITE_SETS" in str(err.value) and "V" in str(err.value)
