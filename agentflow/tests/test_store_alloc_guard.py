"""`Tx.alloc_id` 的防覆盖守卫（一次真实缺陷的回归）。
## 缺陷
`counters.json` 是 ID 分配器的缓存，真源是各表里已用掉的号。两者漂移时（手工建行、从台账恢复、外部脚本写入），分配器会发出已被占用的号，而 `upsert` 按主键替换 ⇒ 新行静默覆盖旧行：不报重复 ID、
不报错、数据凭空消失。
实测证据（D 侧报告）：`adjudicate` 新建的矛盾问题 (0002,0004) 被已存在的 0000 顶掉，`new_question_ids` 仍返回 `["0000"]` —— 调用方看到"新建成功"，
而库里少了一条问题。
## 修法
`alloc_id` 在已声明的事务表里查一遍该号是否被占用，占用就往后跳，并把 `counters` 推到最终号 + 1（缓存自愈）。跳过而不是抛异常：漂移是既成事实，崩溃修不好它；这里只负责"不破坏数据"，失序由
`verify` 的 `counter_behind` / `id_gap` 负责报告。
## `F-2`（2026-09-26 追加）：那道守卫自己留了一个不报错的缺口
上面那句"在已声明的事务表里查一遍"曾经导致：没声明目标表时整段检查被跳过，而发号照旧（`if table is not None and table in self.tables:`）。于是同一条数据丢失路径在"只声明
counters"的调用形态下原样存在。实测见`temp/auditF-probe1.txt` 的 [D1]，回归判据见本文件
的`test_alloc_id_without_the_target_table_declared_raises`。
## S1r 并表（`SCHEMA_VERSION=2`）之后的改动
本文件守的是分配器判据（跳过占用号 / 自愈 / 跳号事件 / 未声明表 fail-closed /空间用尽），行只是标本。并表把 `concepts` 表真删 ⇒ 标本换成
`statements`的一行（`kind="stmt"` / 主键 `stmt_id`），断言逐条不变。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.store import IdExhausted, Store, StoreError


def _mk(sid: str, label: str = "X") -> dict:
    """一条合法的 `statements` 行（形状与 `schema.Statement.validate` 对齐）。"""
    return {"stmt_id": sid, "origin": "own_result", "kind": "theorem", "label": label,
            "statement_full": f"{label} 的命题正文（夹具）", "quote_verified": None,
            "quote_reason": "自产结果（测试夹具）"}


def test_alloc_id_skips_occupied_ids_and_self_heals_counters(store):
    """正向回归：计数器为 0 而表里已有前三个号 ⇒ 必须发第四个，不能发第一个。"""
    store.init()
    with store.tx("statements", "counters", actor="t") as tx:
        for i in range(3):
            tx.upsert("statements", _mk(S.format_id(i)))
    assert (store.read("counters") or {}).get("counters", {}).get("stmt", 0) == 0

    with store.tx("statements", "counters", actor="t") as tx:
        nid = tx.alloc_id("stmt")
        tx.upsert("statements", _mk(nid, "D"))

    assert nid == S.format_id(3), f"必须跳过已占用的那三个号，实际发出 {nid}"
    assert sorted(r["stmt_id"] for r in store.rows("statements")) == \
        [S.format_id(i) for i in range(4)]
    # 缓存自愈：下一次 verify 不该再报 counter_behind
    assert (store.read("counters") or {}).get("counters", {}).get("stmt") == 4


def test_alloc_id_does_not_overwrite_existing_row(store):
    """负控：被占用号那一行的内容必须一字不变（真的没被覆盖）。"""
    store.init()
    with store.tx("statements", "counters", actor="t") as tx:
        tx.upsert("statements", _mk(S.format_id(0), "原始命题"))
    with store.tx("statements", "counters", actor="t") as tx:
        nid = tx.alloc_id("stmt")
        tx.upsert("statements", _mk(nid, "新命题"))
    rows = {r["stmt_id"]: r for r in store.rows("statements")}
    assert rows[S.format_id(0)]["label"] == "原始命题", "已占用的首号被静默覆盖了"
    assert rows[nid]["label"] == "新命题"
    assert nid != S.format_id(0)


def test_alloc_id_records_a_visible_event_when_it_jumps(store):
    """跳过号是"计数器已漂移"的直接证据 ⇒ 必须写进 `events.jsonl`，不许静默。"""
    store.init()
    with store.tx("statements", "counters", actor="t") as tx:
        tx.upsert("statements", _mk(S.format_id(0)))
    with store.tx("statements", "counters", actor="t") as tx:
        tx.alloc_id("stmt")
    evs = [e for e in store.read_events() if e.get("op") == "info"
           and e.get("message") == "alloc_id_skipped_occupied"]
    assert len(evs) == 1, "跳号事件必须被记录（否则漂移只会以'数据莫名消失'的形式暴露）"
    assert evs[0]["kind"] == "stmt" and evs[0]["jumped"] == 1


def test_alloc_id_without_the_target_table_declared_raises(store):
    """    `F-2` 的负控：没声明目标表就发号 ⇒ 必须抛（改前这里返回一个已被占用的号）。

    旧版把占用检查写成 `if table is not None and table in self.tables:`，于是"没声明表"这一支整段跳过检查、照样发号。实测（`temp/auditF-probe1.txt`的
    [D1]）：把 `counters.lit` 拨回 0 后，只声明 `counters` 的事务给出 `0000`（已被占用），随后写回 `literature` ⇒
    `['first','second']` 变成`['OVERWRITER','second']`，行数不变、旧行静默消失。并表之后标本是 `stmt` / `statements`（`concept` 那一档随表退役）：
    这里只声明 `counters`，占用检查要查的 `statements` 不在声明里 ⇒ 必须抛。

    所以"不能崩"这个旧口径是错的：它保住的是调用方的方便，代价是静默覆盖。正确的口径是"要发这个号，就必须把那张表声明进来、让我能查占用"。

    本用例同时钉住"抛的是 `StoreError`"—— 调用方（与 `tx()`）读得懂这个类型；裸 `RuntimeError` 会被上游当成"未知异常"。
    """
    store.init()
    with pytest.raises(StoreError) as ei:
        with store.tx("counters", actor="t") as tx:
            tx.alloc_id("stmt")
    msg = str(ei.value)
    assert "statements" in msg and "声明" in msg, msg

    # 整笔不落盘：被拒的事务不该留下 counters 的推进
    assert (store.read("counters") or {}).get("counters", {}) == {}


def test_alloc_id_with_the_target_table_declared_still_works(store):
    """正控（与上一条成对）：声明了目标表 ⇒ 照旧发号，而且真的会跳过占用号。

    没有这一条，"一律抛"也能让上一条通过 —— 那就把判据做成了"谁也别想发号"。
    """
    store.init()
    with store.tx("statements", "counters", actor="t") as tx:
        tx.upsert("statements", _mk(S.format_id(0), "已被占用"))
    with store.tx("statements", "counters", actor="t") as tx:
        nid = tx.alloc_id("stmt")
        tx.upsert("statements", _mk(nid, "新的"))
    assert nid == S.format_id(1), nid
    rows = {r["stmt_id"]: r["label"] for r in store.rows("statements")}
    assert rows == {S.format_id(0): "已被占用", S.format_id(1): "新的"}, rows


def test_alloc_id_raises_when_space_exhausted(store):
    """编号空间用尽 ⇒ fail-closed，不静默升位宽。

    用"计数器已被推到上限 +1"来构造用尽，而不是"表里塞满全部号" ——
    后者的跳过循环要跑上百万次，而且它构造的场景不是我们要测的那个
    （计数器的越界判据）。测试要打在真正的判据上。
    """
    store.init()
    store._atomic_write(
        store.data / "counters.json",
        {"schema_version": S.SCHEMA_VERSION, "counters": {"stmt": 10 ** S.ID_DIGITS}},
    )
    with pytest.raises(IdExhausted):
        with store.tx("statements", "counters", actor="t") as tx:
            tx.alloc_id("stmt")
