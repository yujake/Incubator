"""`rebuild` 的无损性。

背景（真实缺陷）：`rebuild()` 的事件折叠原本走 `S.row_from_dict()`，而它只保留
dataclass 字段 —— 于是带下划线前缀的诊断/扩展字段（`_keys`、`_quote_check`）
在重建后全部消失。功能上判重还能靠 `doi`/`dedup_key` 兜底，但
"能重建"不应该意味着"重建出更少的信息"：一旦丢字段，事后就无法回答
"当初这条文献是从哪些键命中/被判定为重复的"。

本文件把"无损"固定下来。
"""

from __future__ import annotations

import json

from agentflow.store import Store


def _seed(store: Store) -> None:
    """写一行带诊断字段的文献 + 一行带校验明细的关系。"""
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "0000", "title": "Probe paper", "type": "J", "summary": "",
            "path": None, "processed": True, "source_request_ids": [],
            "dedup_key": "doi:10.1/probe", "doi": "10.1/probe", "year": 2000,
            "authors": [], "venue": None, "language": None,
            "added_at": "2026-01-01T00:00:00+00:00", "download": {},
            "claimed_by": None, "lease_until": None, "mine_attempts": 0,
            "last_mine_error": None,
            "_keys": ["doi:10.1/probe", "title:probe paper|2000", "title:probe paper|*"],
        })
    with store.tx("concepts", "relations", actor="test") as tx:
        for cid, name, rel in (("0000", "group", ["0001"]), ("0001", "abelian group", ["0000"])):
            tx.upsert("concepts", {
                "concept_id": cid, "name": name, "definition": "d",
                "related_concepts": rel, "normalized_name": name, "aliases": [],
                "definition_source_lit_id": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
        tx.upsert("relations", {
            "relation_id": "0000", "concept_ids": ["0000", "0001"], "description": "d",
            "lit_id": "0000", "page_range": {"start": 1, "end": 1, "label": "p. 1"},
            "quote": "An abelian group is a group.",
            "quote_normalized": "an abelian group is a group",
            "quote_verified": True, "statement": "d",
            "concept_group_key": "0000|0001", "dedup_key": "0000|0001::x",
            "status": "active", "duplicate_of": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "_quote_check": {"verified": True, "reason": "substring_match"},
        })


def _row(store: Store, table: str) -> dict:
    return json.loads((store.data / f"{table}.json").read_text(encoding="utf-8"))["rows"][0]


def test_rebuild_preserves_diagnostic_fields(store):
    """重建后诊断字段不得丢失（否则无从追溯"当初为什么判成重复"）。

    同时断言 schema 字段仍然被规范化 —— 无损不等于"原样抄回"，
    校验后的规范值必须覆盖原始值。
    """
    _seed(store)
    before_keys = _row(store, "literature")["_keys"]
    before_qc = _row(store, "relations")["_quote_check"]

    out = store.rebuild(backup=False)
    assert out["applied"] == 4 and out["skipped"] == 0

    assert _row(store, "literature")["_keys"] == before_keys
    assert _row(store, "relations")["_quote_check"] == before_qc


def test_rebuild_is_idempotent_and_keeps_tables_valid(store):
    """连做两次 rebuild 结果必须逐字节一致（幂等），且不变量仍成立。"""
    _seed(store)

    store.rebuild(backup=False)
    first = {t: (store.data / f"{t}.json").read_bytes() for t in
             ("literature", "concepts", "relations", "search_requests")}
    store.rebuild(backup=False)
    second = {t: (store.data / f"{t}.json").read_bytes() for t in
              ("literature", "concepts", "relations", "search_requests")}

    assert first == second, "rebuild 必须幂等，否则反复重建会漂移"


def test_rebuild_ignores_corrupt_events_without_dying(store):
    """事件日志里混入坏行时应跳过并计数，而不是整次重建失败。

    崩溃时可能留下半行 JSON —— 那不应该让数据库变得不可恢复。
    """
    _seed(store)
    with open(store.events_path, "a", encoding="utf-8") as f:
        f.write('{"op":"upsert","table":"literature","row":{"lit_id":"0001"')  # 截断的坏行
        f.write("\n")
        f.write("这不是 JSON\n")

    out = store.rebuild(backup=False)
    # `I-5`（登记在 `draft/28`）：旧断言是 `out["skipped"] >= 0` —— 恒真
    # （`skipped` 在 `rebuild` 里只增不减），于是"日志里有坏行"这件事
    # 在被测判据里完全看不见，"没抛异常"就被读成"日志是好的"。
    # 现在返回值里有 `corrupt_events`（坏行条数），本用例钉住它。
    assert out["corrupt_events"] == 2, out  # 上面写进去的正是 2 行坏行
    assert len(store.rows("literature")) == 1, "好数据仍应重建出来"
