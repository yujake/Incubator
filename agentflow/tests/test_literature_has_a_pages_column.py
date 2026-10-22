# -*- coding: utf-8 -*-
"""`literature.pages`：页码栏（A 线缺陷 9 —— 结构上给不出 B 要的凭据）。

## 为什么补这一格

`register_statement(origin="external_lit")` 要求 `page_range` 非空，而 A 侧此前
在结构上给不出这个凭据：`literature` 表里没有页码/引文栏，只能往 `download` 那个
自由 dict 里塞。这一格补的就是 GB/T 7714 的页码那一栏。

## 为什么是字符串，且不抬 `SCHEMA_VERSION`、不加 `row_from_dict` 特例

`row_from_dict` 对 `literature` 只按 `__dataclass_fields__` 过滤、不做
`PageRange.from_dict`（对照 `relations` 那一支）；直接放 `PageRange` 字段会让盘上的
dict 原样贴进来。字符串 + 空串默认值也不需要迁移：老行缺这个键时由默认值接手
（理由与 `SearchRequest.providers` 那次同一套）。

## 四条判据

1. 老行（没有 `pages` 键）读出来 `pages == ""`，且其它字段逐字不变；
2. 新行写 `pages="45--52"` ⇒ `to_dict()` 里带这一格、`row_from_dict` 读回一致（含真落盘一遭）；
3. 负控：`to_dict()` 的键集 == 该 dataclass 的字段集（防「加了字段但 `to_dict` 不吐」）；
4. 反真空：把 `pages` 从 dataclass 里删掉 ⇒ 第 1 条必须红。

判据 3 的对照面：这份 schema 里没有叫 `resources` 的表（全仓 grep 零命中），
所以拿 `relations` 当对照 —— 它是另一张在 `row_from_dict` 里走 `PageRange.from_dict`
特例的表，`to_dict` 吐不吐这条判据在它身上同样有对象。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

import pytest
from conftest import TS, sync_counters
from agentflow import schema as S
from agentflow.store import Store

#: 一份手写的老行：这次改动之前盘上就长这样（20 个键，没有 `pages`）。
#: 每一格都给了与默认值不同的取值 —— 否则「其它字段逐字不变」这句话没有内容。
_OLD_ROW: dict = {
    "lit_id": "0007",
    "title": "Old row written before the pages column",
    "type": "J",
    "summary": "手写的老行：这一份 JSON 就是这次改动之前的形态",
    "path": "0007/paper.pdf",
    "processed": True,
    "source_request_ids": ["r-0001", "r-0002"],
    "dedup_key": "doi:10.1000/old.row",
    "doi": "10.1000/old.row",
    "year": 1971,
    "authors": ["Brown, K."],
    "venue": "Annals of Mathematics",
    "language": "en",
    "added_at": TS,
    "download": {"status": "ok", "http_status": 200, "bytes": 1234},
    "matched": "exact",
    "claimed_by": "A",
    "lease_until": TS,
    "mine_attempts": 2,
    "last_mine_error": "lease_expired",
}

#: 老行读回来之后应当逐字等于的那份 dict：老 JSON 原样 + 新字段的默认值。
_OLD_ROW_READ_BACK: dict = dict(_OLD_ROW, pages="")


def _read_old_row():
    """判据 1 的判据体（抽成函数是为了让判据 4 对同一段断言做反真空）。

    用 `getattr(obj, "pages", <哨兵>)` 而不是 `obj.pages`：把这一格从 dataclass 里
    删掉时，要红在一条断言上（可读的「这一格不在」），而不是红在 `AttributeError`。
    """
    obj = S.row_from_dict("literature", dict(_OLD_ROW))
    got = getattr(obj, "pages", "<这一格不在 dataclass 上>")
    assert got == "", (
        "老行（盘上没有 pages 键）读回来必须是空串 —— 空串是「还没记」，"
        f"不是「这篇没有页码」；实测 {got!r}"
    )
    dumped = obj.to_dict()
    changed = sorted(k for k in _OLD_ROW_READ_BACK
                     if k in dumped and dumped[k] != _OLD_ROW_READ_BACK[k])
    assert dumped == _OLD_ROW_READ_BACK, (
        "读回一行老行不许改动其它任何一格："
        f"多出 {sorted(set(dumped) - set(_OLD_ROW_READ_BACK))}、"
        f"缺少 {sorted(set(_OLD_ROW_READ_BACK) - set(dumped))}、"
        f"或取值变了 {changed}"
    )
    return obj


# ============================================================ 判据 1：老行


def test_an_old_row_without_the_key_reads_back_as_an_empty_string():
    """判据 1：老行（没有 `pages` 键）⇒ `pages == ""`，且其它字段逐字不变。

    这正是「不抬 `SCHEMA_VERSION`、不加 `row_from_dict` 特例」的可执行理由：
    老行由默认值接手，不需要任何迁移代码。
    """
    obj = _read_old_row()
    obj.validate()
    assert obj.pages == ""


def test_an_old_row_still_commits_through_a_real_store(store: Store):
    """判据 1 的落盘侧：把那份老 JSON 写成快照、真开一次事务，这一格与其它格都在。

    只读 `row_from_dict` 说服不了「老盘上的行不会把写路径弄炸」，所以这里真写一遍；
    同时钉住「默认值只在读的时候接手」—— 写回盘上的老行不许被凭空补上 `pages` 键。
    """
    (store.data / "literature.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": [_OLD_ROW]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    with store.tx("literature", actor="test") as tx:
        row = tx.rows("literature")[0]
        row["mine_attempts"] = 3
        tx.upsert("literature", row)
    on_disk = store.rows("literature")[0]
    assert on_disk["mine_attempts"] == 3 and "pages" not in on_disk, (
        "老行没被凭空补上 pages 键（默认值只在读的时候接手），也不许丢别的键"
    )
    back = S.row_from_dict("literature", on_disk)
    assert back.pages == "" and back.mine_attempts == 3


# ============================================================ 判据 2：新行


def _new_row(pages: str) -> S.Literature:
    return S.Literature(
        lit_id="0008", title="一篇期刊论文", type="J", summary="有页码的新行",
        path=None, doi="10.1000/new.row", year=1995, venue="Inventiones Mathematicae",
        authors=["Wiles, A."], added_at=TS, pages=pages,
    )


def test_a_new_row_carries_the_pages_column_in_to_dict():
    """判据 2（正控）：写 `pages="45--52"` ⇒ `to_dict()` 里带这一格，读回一致。"""
    row = _new_row("45--52")
    row.validate()
    dumped = row.to_dict()
    assert dumped["pages"] == "45--52"
    back = S.row_from_dict("literature", dumped)
    assert back == row
    assert back.to_dict() == dumped


def test_a_new_row_keeps_the_pages_column_on_disk(store: Store):
    """判据 2 的落盘侧：真写一行、真读回来，这一格与其它格一起活着。"""
    row = _new_row("45--52")
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())
    sync_counters(store)
    on_disk = store.rows("literature")[0]
    assert on_disk["pages"] == "45--52"
    assert S.row_from_dict("literature", on_disk) == row


def test_the_default_is_the_empty_string_not_none():
    """负控：默认值必须是空串，不是 `None`。

    为什么单独钉这一条：`None` 会把「还没记」与「这篇确实没有页码」折成同一格
    （三态纪律），而 B 侧要的是一个可判定的凭据。
    """
    assert S.Literature.__dataclass_fields__["pages"].default == ""
    bare = S.Literature(lit_id="0009", title="T", type="J", summary="", path=None)
    assert bare.pages == ""
    assert bare.to_dict()["pages"] == ""


# ============================================================ 判据 3：负控


def test_to_dict_emits_exactly_the_declared_fields():
    """判据 3（负控）：`to_dict()` 的键集 == 该 dataclass 的字段集。

    防的形态：有人给 dataclass 加了字段、而 `to_dict` 没吐 —— 于是盘上永远没有这一格，
    而「字段表里有」这件事在声明面上看起来一切正常。
    """
    literature = _new_row("45--52")
    relations = S.Relation(
        relation_id="0000", concept_ids=["0000", "0001"], description="对照面",
        lit_id="0007", page_range=S.PageRange(45, 52, "pp. 45-52"),
    )
    for obj in (literature, relations):
        cls = type(obj)
        declared = {f.name for f in fields(cls)}
        emitted = set(obj.to_dict())
        assert emitted == declared, (
            f"{cls.__name__}.to_dict() 的键集与字段表不一致："
            f"多 {sorted(emitted - declared)}、少 {sorted(declared - emitted)}"
        )
    # 这一格是本轮的新字段：它必须在声明面与吐出面同时在场 ——
    # 这正是「改了 dataclass 但 to_dict 不吐」能抓住的那一半。
    assert "pages" in S.Literature.__dataclass_fields__, "字段表里没有 pages"
    assert "pages" in literature.to_dict(), "to_dict 不吐 pages"


# ============================================================ 判据 4：反真空


def test_anti_vacuum_deleting_the_field_turns_criterion_one_red(monkeypatch):
    """判据 4（反真空）：把 `pages` 从 dataclass 里删掉 ⇒ 判据 1 必须红。

    怎么删：`row_from_dict` 的 `literature` 那一支在调用时按模块全局名 `Literature`
    取 `__dataclass_fields__` 并构造行对象，所以换成一份「没有 `pages` 的老版本类」
    就等于回滚了这一次改动 —— 不 monkeypatch `__dataclass_fields__` 本身
    （`asdict` 另有一份字段表，只删键模拟不出来，同族说明见 `test_usage_ledger_idem_key`）。
    """
    @dataclass
    class OldLiterature:
        """回滚后的那一版 `Literature`：没有 `pages`，其余字段逐字相同。"""

        lit_id: str
        title: str
        type: str
        summary: str
        path: str | None
        processed: bool = False
        source_request_ids: list | None = None
        dedup_key: str = ""
        doi: str | None = None
        year: int | None = None
        authors: list | None = None
        venue: str | None = None
        language: str | None = None
        added_at: str = ""
        download: dict | None = None
        matched: str = ""
        claimed_by: str | None = None
        lease_until: str | None = None
        mine_attempts: int = 0
        last_mine_error: str | None = None

        def to_dict(self) -> dict:
            return asdict(self)

    monkeypatch.setattr(S, "Literature", OldLiterature)
    obj = S.row_from_dict("literature", dict(_OLD_ROW))
    assert not hasattr(obj, "pages"), "装置没删掉这一格 ⇒ 下面的反真空是空转"
    assert obj.title == _OLD_ROW["title"], "装置造不出一行可读的老行 ⇒ 反真空也是空转"
    with pytest.raises(AssertionError):
        _read_old_row()
