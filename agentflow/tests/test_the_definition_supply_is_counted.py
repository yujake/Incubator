# -*- coding: utf-8 -*-
"""S1o：定义"由谁来补"的三档必须分开计数，且与"还没补"严格分开（`draft/97` §14.13 / §15.4）。

业主 2026-10-09 的两句口径合成这一格：

> 「抽不到定义的概念就让A去网上搜，写入时定义内容留空，等A返回后写入；如果概念很基础，
>  是数学基本概念，允许B自己写定义」
> 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

判据的靶子只有一个：`conceptrows.definition_supply(store)` 的六个桶。
最容易悄悄做错的是折平：把 `ask_parent` 折进"定义到了"（于是"已经问了父"被读成
"父已经给了"），或者把"空定义且没有标记"折进 `pending_search`（那正是历史 94 条的病根 ——
空得没有交代，而读数里看不见）。
"""

from __future__ import annotations

from agentflow import conceptrows as CR
from agentflow import secretary as SEC


class _Stub:
    """只提供 `.rows(table)` 的替身：用来喂写不进真库的行（见下面第二条判据）。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def rows(self, table: str) -> list[dict]:
        return list(self._rows) if table == "statements" else []


class _Broken:
    def rows(self, table: str) -> list[dict]:
        raise RuntimeError("盘坏了")


def _concept(stmt_id: str, *, label: str, definition: str = "", reason: str = "",
             src: str | None = None) -> dict:
    return {"stmt_id": stmt_id, "kind": "concept", "label": label,
            "statement_full": definition, "quote_reason": reason, "source_lit_id": src}


def test_a_real_library_counts_each_supply_way_separately(store):
    """正控：定义来自文献 / B 自撰 / 等着 A 搜 —— 三档各归各的桶。"""
    sec = SEC.Secretary("B", root=store.root, store=store)
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {"lit_id": "0003", "title": "群论", "type": "J", "summary": "",
                                 "path": None, "processed": True,
                                 "added_at": "2026-01-01T00:00:00+00:00"})
    sec.record_statement({"kind": "concept", "label": "谱", "origin": "own_result",
                          "statement_full": "算子的谱是……", "source_lit_id": "0003",
                          "proof_text": "良定义性：略。"})
    sec.record_statement({"kind": "concept", "label": "群", "origin": "own_result",
                          "statement_full": "群是……", "proof_text": "良定义性：基本概念。"})
    sec.record_statement({"kind": "concept", "label": "生僻概念 X", "origin": "own_result"})
    got = CR.definition_supply(store)
    assert got["checked"] and got["rows"] == 3, got
    assert got["from_lit"] == 1 and got["self_authored"] == 1, got
    assert got["pending_search"] == 1 and got["ask_parent"] == 0, got
    assert got["waiting_ask_parent"] == 0, got
    assert got["unmarked_empty"] == 0, "真库上不许出现'空定义且没有标记'（那是历史病根）"


def test_an_unmarked_empty_definition_is_counted_as_the_disease():
    """负控：空定义而没有任何待补标记 ⇒ `unmarked_empty`（不许折进 `pending_search`）。

    这种行写不进真库（`Statement.validate` 当场拒），所以这一条喂的是替身：
    判据要防的是"分类器看不见它"，而不是"库里有没有它" —— 两件事都要有判据。
    """
    rows = [
        _concept("0000", label="没标记的空定义"),
        _concept("0001", label="等 A 搜", reason=f"还没抽到（{CR.PENDING_SEARCH}）"),
        _concept("0002", label="已经问了父", reason=f"（{CR.ASK_PARENT}）"),
    ]
    got = CR.definition_supply(_Stub(rows))
    assert got["checked"] and got["rows"] == 3, got
    assert got["unmarked_empty"] == 1, got
    assert got["pending_search"] == 1, got
    assert got["waiting_ask_parent"] == 1, got
    assert got["ask_parent"] == 0, "还没到的行不许算进'已由父给出'"


def test_the_two_halves_are_not_folded():
    """反真空：`ask_parent` 与 `waiting_ask_parent` 是两个桶（"父给了" ≠ "问了父"）。"""
    rows = [
        _concept("0000", label="父给了", definition="父就地给的定义", reason=f"（{CR.ASK_PARENT}）"),
        _concept("0001", label="问了父但还没回", reason=f"（{CR.ASK_PARENT}）"),
        _concept("0002", label="文献里抽到", definition="从文献抄的定义", src="0003"),
        _concept("0003", label="B 自撰", definition="群是……"),
    ]
    got = CR.definition_supply(_Stub(rows))
    assert (got["ask_parent"], got["waiting_ask_parent"]) == (1, 1), got
    assert (got["from_lit"], got["self_authored"]) == (1, 1), got
    assert got["pending_search"] == 0 and got["unmarked_empty"] == 0, got
    supplied = got["from_lit"] + got["self_authored"] + got["ask_parent"]
    waiting = got["pending_search"] + got["waiting_ask_parent"] + got["unmarked_empty"]
    assert supplied + waiting == got["rows"], (supplied, waiting, got)


def test_an_unreadable_table_is_not_a_library_full_of_zeroes():
    """三态：读不成 ⇒ `checked=False` + 理由，六个桶都是 0 但不许读成"全都干净"。"""
    got = CR.definition_supply(_Broken())
    assert got["checked"] is False and got["reason"], got
    assert got["rows"] == 0 and got["unmarked_empty"] == 0, got
    assert "读不成" in got["reason"], got
