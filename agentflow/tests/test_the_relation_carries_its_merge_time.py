"""判据：`merged_at` 那一格（12-C=甲，业主 2026-10-10 裁定；禁改区改动，先改后审）。

## 这一格回答的是哪一个问题

旧标准每条关系有一格记"并表时间"，新标准没有 ⇒ 问"这条边是哪天进来的"答不出来。
`created_at` 不是它：那是"这一行什么时候建出来的"（连还没并进去的 `suspect` 行也有）。

## 四条判据（含三态与两处配对）

1. 正控：`active` 的关系写出来带 `merged_at`，而且它进得了 `to_dict()`（落盘那一份）
   —— 加了字段而没进序列化，等于加了一个只在内存里存在的格子。
2. 负控：`suspect` / `rejected` 的行不许带 `merged_at`（它还没并进图），
   连"带着它构造"都要在 `validate()` 当场拒 —— 判据在写入期，不在读的人眼里。
3. 三态：空串要能分成两档 —— `status != "active"` 且空 ⇒ 还没并进图；
   `status == "active"` 且空 ⇒ 这一格出现之前的历史行、并表时间未知。
   本判据按 `status` 读出这两种结论（折成一个空串会让老数据看起来像"没并进图"）。
4. 反真空（写路径真的写了）：主写路径（`agent_b.run_once`）在 `status == "active"` 时
   填这一格、否则留空 —— 源码级断言 + 行为级读数（真跑一条 B 的写入是另一件事，
   这里只钉"那两处赋值与状态同一个条件"）。
"""

from __future__ import annotations

import inspect
import pathlib
import re

from agentflow import schema as S

PR = S.PageRange(1, 2, "pp. 1-2")


def _relation(rid: str, *, status: str = "active", merged_at: str = "",
              created_at: str = "2026-01-01T00:00:00+08:00") -> S.Relation:
    return S.Relation(relation_id=rid, concept_ids=["0001", "0002"], description="两个概念有关系",
                      lit_id="0001", page_range=PR, status=status, created_at=created_at,
                      merged_at=merged_at)


def test_an_active_relation_carries_its_merge_time() -> None:
    """正控：`active` 的行带并表时间，且它进得了落盘那一份（`to_dict`）。"""
    row = _relation("0001", merged_at="2026-10-11T09:00:00+08:00")
    row.validate()
    blob = row.to_dict()
    assert blob["merged_at"] == "2026-10-11T09:00:00+08:00", blob
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}",
                        blob["merged_at"]), blob["merged_at"]
    # 与 `created_at` 是两格（不是同一个字段的两个名字）
    assert blob["created_at"] != "" and "merged_at" in blob, sorted(blob)


def test_a_row_that_is_not_merged_yet_must_not_carry_a_time() -> None:
    """负控：`suspect` / `rejected` 的行不许带并表时间（写入期就拒）。"""
    for status in ("suspect", "rejected"):
        with_time = _relation("0002", status=status, merged_at="2026-10-11T09:00:00+08:00")
        try:
            with_time.validate()
        except ValueError as exc:
            assert "merged_at" in str(exc) and "active" in str(exc), str(exc)
        else:                                       # pragma: no cover —— 走到这里就是漏了
            raise AssertionError(f"status={status} 的行带着 merged_at 却通过了 validate()："
                                 "那会让'哪天进来的'读出一个不存在的时刻")
        # 不带时间的那一档照常通过（还没并进图是合法状态）
        _relation("0003", status=status).validate()


def test_the_empty_cell_reads_as_two_different_things() -> None:
    """三态：空串按 `status` 读成"还没并进图"或"历史行、未知"（不许折成一个意思）。"""
    pending = _relation("0004", status="suspect")
    historic = _relation("0005", status="active")            # 这一格出现之前的老行
    assert pending.merged_at == "" and historic.merged_at == "", (pending, historic)

    def reading(row: S.Relation) -> str:
        """读法（与 `schema.Relation.merged_at` 的 docstring 逐字同一条口径）。"""
        if row.merged_at:
            return f"并入于 {row.merged_at}"
        return "还没并进图" if row.status != "active" else "并表时间未知（这一格出现之前的历史行）"

    assert reading(pending) == "还没并进图", reading(pending)
    assert reading(historic).startswith("并表时间未知"), reading(historic)
    assert reading(_relation("0006", merged_at="2026-10-11T09:00:00+08:00")).startswith("并入于")


def test_the_main_writer_fills_it_only_for_active_rows() -> None:
    """反真空（写路径）：主写路径把这一格与状态绑在同一个条件上。

    源码级断言（不是"我以为它写了"）：`merged_at` 的赋值必须与 `status == "active"`
    出现在同一处；`suspect` 那一支留空。真跑一条 B 的写入属于另一条线
    （`tests/test_agent_b_*.py`），这一条只钉"赋值条件"。
    """
    from agentflow.agent_b import run_once as RO

    src = inspect.getsource(RO)
    assert "merged_at=" in src, "主写路径完全没写这一格 ⇒ 加了字段但没人填"
    line = next(ln.strip() for ln in src.splitlines() if "merged_at=" in ln)
    assert 'status == "active"' in line, (
        f"`merged_at` 的赋值没有与状态绑在一起：{line} —— "
        "那样 suspect 的行也会带一个并表时间，而它还没并进图")
    # schema 那一格真的存在（禁改区那一处改动的机器读数）
    assert "merged_at" in pathlib.Path(S.__file__).read_text(encoding="utf-8")
