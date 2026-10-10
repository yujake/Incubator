# -*- coding: utf-8 -*-
"""研究链某一环没达标时，门要把同一环里现在就能达标的其它成员档点出来。

## 守的是什么（T4 第 6 趟 `t4f` 的真机读数）

那一趟 M 把"想（猜想或判决性证据）"这一环声明成 `conjecture_rows`（这一趟 0 条），
而同一环的 `statement_rows` 有 448 条 —— 它选了唯一为 0 的那一档。收工门报了
`blocker acceptance_unmet`（"R4 conjecture_rows：0 条，要求 ≥ 1 条"），M 调 `closing` 三次、
看到之后仍按 `met=true` 收工。验收表的成员档本来就是可选的
（`closing.RESEARCH_CHAIN_GROUPS` 每一环给好几档），但"换一档就达标"这件事
当时门里一个字都没说 —— 这一批补上（只报数，不判：哪一档诚实仍归 M 判）。

判据：
* 正控：`conjecture_rows` 为 0 而 `statement_rows` 有货 ⇒ 那句话点名 `statement_rows` 与其读数；
* 负控：同一环里没有其它档达标 ⇒ 一句话都不加（不许凭空造出路）；
* 反真空：这一档不属于任何多成员环（例如 `document_rows`…）⇒ 也不加话；
* 三态：其它档读不出来 ⇒ 跳过它（"没查成"不许当成"它达标了"）。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

TS = "2026-10-10T00:00:00+08:00"


def _store(tmp_path: pathlib.Path, *, statements: int, conjectures: int) -> Store:
    store = Store(tmp_path)
    store.init()
    with store.tx("statements", "conjectures", "literature", actor="test", note="seed") as tx:
        tx.upsert("literature", {"lit_id": "0000", "title": "t", "type": "J", "summary": "s",
                                 "path": None, "processed": True, "added_at": TS}, note="seed")
        for i in range(statements):
            tx.upsert("statements", {"stmt_id": f"{i:04d}", "origin": "external_lit",
                                     "kind": "concept", "label": f"c{i}",
                                     "statement_full": f"概念 {i}", "source_lit_id": "0000",
                                     "quote_reason": "夹具：尚未逐字校验", "created_at": TS},
                      note="seed")
        for i in range(conjectures):
            tx.upsert("conjectures", {"conjecture_id": f"{i:04d}",
                                      "statement": f"猜想 {i}",
                                      "testable": {"criterion": "夹具"},
                                      "status": "testing", "created_at": TS}, note="seed")
    return store


def test_positive_the_note_names_the_sibling_that_would_pass(tmp_path: pathlib.Path) -> None:
    """正控：`conjecture_rows` 0 条而 `statement_rows` 有货 ⇒ 门点出后者与它的读数。"""
    store = _store(tmp_path, statements=3, conjectures=0)

    note = CL._alternatives_note(store, "conjecture_rows", tmp_path)

    assert "statement_rows" in note, note
    assert "3 ≥ 1" in note, note
    assert "可选的" in note, note


def test_negative_no_sibling_passes_no_sentence(tmp_path: pathlib.Path) -> None:
    """负控：同一环里没有其它档达标 ⇒ 一句话都不加（不许凭空造出路）。"""
    store = _store(tmp_path, statements=0, conjectures=0)

    assert CL._alternatives_note(store, "conjecture_rows", tmp_path) == ""


def test_anti_vacuum_a_kind_outside_the_chain_gets_nothing(tmp_path: pathlib.Path) -> None:
    """反真空：不属于任何研究链环的档 ⇒ 不加话（这句话只对研究链成员有意义）。

    用 `quote_verified_rows`（真档，但不在 `RESEARCH_CHAIN_GROUPS` 的任何一环里）——
    拿 `document_rows` 试是不行的：它在"交（手稿落盘）"那一环里（第一版就是这么写错的，
    判据当场把它照出来了）。
    """
    store = _store(tmp_path, statements=3, conjectures=0)

    assert CL._alternatives_note(store, "quote_verified_rows", tmp_path) == ""


def test_anti_vacuum_a_zero_threshold_sibling_is_not_an_alternative(tmp_path: pathlib.Path) -> None:
    """反真空：`got=0 / need=0` 的兄弟档不算"出路"（提它等于教人换一档空声明）。"""
    store = _store(tmp_path, statements=0, conjectures=0)

    note = CL._alternatives_note(store, "conjecture_rows", tmp_path)

    assert note == "", note


def test_anti_vacuum_unreadable_siblings_are_skipped_not_invented(tmp_path: pathlib.Path) -> None:
    """三态：其它档读不出来 ⇒ 跳过（"没查成"不许读成"它达标了"）。"""
    store = _store(tmp_path, statements=0, conjectures=0)
    # 把 statements 表文件写成坏 JSON ⇒ 那一档读不出来
    (tmp_path / "data" / "statements.json").write_text("{坏", encoding="utf-8")

    note = CL._alternatives_note(store, "conjecture_rows", tmp_path)

    assert "statement_rows" not in note, note


def test_the_groups_are_read_from_the_one_authority() -> None:
    """判据读的是唯一权威（`RESEARCH_CHAIN_GROUPS`），不另抄一份成员表。"""
    labels = {label: members for label, members in CL.RESEARCH_CHAIN_GROUPS}
    assert any("conjecture_rows" in members for members in labels.values()), labels
    assert sum(1 for members in labels.values() if len(members) > 1) >= 3, labels
    assert "conjectures" in S.TABLES and "statements" in S.TABLES
