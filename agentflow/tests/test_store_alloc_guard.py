"""`Tx.alloc_id` 的防覆盖守卫（一次真实缺陷的回归）。

## 缺陷

`counters.json` 是 ID 分配器的缓存，真源是各表里已用掉的号。两者漂移时
（手工建行、从台账恢复、外部脚本写入），分配器会发出已被占用的号，
而 `upsert` 按主键替换 ⇒ 新行静默覆盖旧行：不报重复 ID、不报错、数据凭空消失。

实测证据（D 侧报告）：`adjudicate` 新建的矛盾问题 (0002,0004) 被已存在的 0000 顶掉，
`new_question_ids` 仍返回 `["0000"]` —— 调用方看到"新建成功"，而库里少了一条问题。

## 修法

`alloc_id` 在已声明的事务表里查一遍该号是否被占用，占用就往后跳，
并把 `counters` 推到最终号 + 1（缓存自愈）。跳过而不是抛异常：
漂移是既成事实，崩溃修不好它；这里只负责"不破坏数据"，
失序由 `verify` 的 `counter_behind` / `id_gap` 负责报告。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.store import IdExhausted, Store


def _mk(cid: str, name: str = "X") -> dict:
    return S.Concept(concept_id=cid, name=name, definition="").to_dict()


def test_alloc_id_skips_occupied_ids_and_self_heals_counters(store):
    """正向回归：计数器为 0 而表里已有 0000–0002 ⇒ 必须发 0003，不能发 0000。"""
    store.init()
    with store.tx("concepts", "counters", actor="t") as tx:
        for i in range(3):
            tx.upsert("concepts", _mk(f"000{i}"))
    assert (store.read("counters") or {}).get("counters", {}).get("concept", 0) == 0

    with store.tx("concepts", "counters", actor="t") as tx:
        nid = tx.alloc_id("concept")
        tx.upsert("concepts", _mk(nid, "D"))

    assert nid == "0003", f"必须跳过已占用的 0000，实际发出 {nid}"
    assert sorted(r["concept_id"] for r in store.rows("concepts")) == ["0000", "0001", "0002", "0003"]
    # 缓存自愈：下一次 verify 不该再报 counter_behind
    assert (store.read("counters") or {}).get("counters", {}).get("concept") == 4


def test_alloc_id_does_not_overwrite_existing_row(store):
    """负控：被占用号那一行的内容必须一字不变（真的没被覆盖）。"""
    store.init()
    with store.tx("concepts", "counters", actor="t") as tx:
        tx.upsert("concepts", _mk("0000", "原始概念"))
    with store.tx("concepts", "counters", actor="t") as tx:
        nid = tx.alloc_id("concept")
        tx.upsert("concepts", _mk(nid, "新概念"))
    rows = {r["concept_id"]: r for r in store.rows("concepts")}
    assert rows["0000"]["name"] == "原始概念", "已占用的 0000 被静默覆盖了"
    assert rows[nid]["name"] == "新概念"
    assert nid != "0000"


def test_alloc_id_records_a_visible_event_when_it_jumps(store):
    """跳过号是"计数器已漂移"的直接证据 ⇒ 必须写进 `events.jsonl`，不许静默。"""
    store.init()
    with store.tx("concepts", "counters", actor="t") as tx:
        tx.upsert("concepts", _mk("0000"))
    with store.tx("concepts", "counters", actor="t") as tx:
        tx.alloc_id("concept")
    evs = [e for e in store.read_events() if e.get("op") == "info"
           and e.get("message") == "alloc_id_skipped_occupied"]
    assert len(evs) == 1, "跳号事件必须被记录（否则漂移只会以'数据莫名消失'的形式暴露）"
    assert evs[0]["kind"] == "concept" and evs[0]["jumped"] == 1


def test_alloc_id_without_table_declared_still_works(store):
    """防误伤：事务没声明目标表时不能崩 —— 只是没法查，仍按计数器发号。

    （这种用法本身值得怀疑，但把它变成崩溃会破坏既有调用方；
    真正的保障是"声明了表就一定会查"。）
    """
    store.init()
    with store.tx("counters", actor="t") as tx:
        first = tx.alloc_id("concept")
    with store.tx("counters", actor="t") as tx:
        second = tx.alloc_id("concept")
    assert (first, second) == ("0000", "0001")


def test_alloc_id_raises_when_space_exhausted(store):
    """4 位空间用尽 ⇒ fail-closed，不静默升位宽。

    用"计数器已被推到 10000"来构造用尽，而不是"表里塞满 9999" ——
    后者的跳过循环要跑一万次，而且它构造的场景不是我们要测的那个
    （计数器的越界判据）。测试要打在真正的判据上。
    """
    store.init()
    store._atomic_write(
        store.data / "counters.json",
        {"schema_version": S.SCHEMA_VERSION, "counters": {"concept": 10000}},
    )
    with pytest.raises(IdExhausted):
        with store.tx("concepts", "counters", actor="t") as tx:
            tx.alloc_id("concept")
