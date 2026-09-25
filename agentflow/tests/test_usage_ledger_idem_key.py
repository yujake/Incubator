"""`usage_ledger.idem_key`：表级唯一性断言 + `Tx.insert_unique` + `verify` 判据。

## 这个文件守的是提案 A 的三处落地（`docs/SCHEMA-MIGRATION-PROPOSAL-usage-ledger-idem-key.md`）

1. `schema.UsageEntry.idem_key`：可选字段（默认空串 = "这一行没有幂等身份"）；
2. `schema.validate_table` 对非空幂等键断言整表唯一 —— 这是"同一笔账被记了两次"
   在本栈里唯一的自动防线（重复行的 `usage_id` 本来就不同，`duplicate_id` 不响）；
3. `store.Tx.insert_unique`：把判重与写入放进同一个临界区，
   并保证冲突时一个字节都不写、也不分配 ID。

## 两条陷阱各有专门的用例

- 混合版本窗口：未升级进程写下的行不带 `idem_key`（连这个键都没有），
  这些行不许被误报，也不许让唯一性失效；`idem_key=""` 的行同理，
  两张表里都能有无数条。
- 回滚陷阱：`row_from_dict` 按 dataclass 字段过滤，回滚代码之后一次
  `Store.rebuild()` 会把 `idem_key` 静默丢掉 —— 本文件把"它会丢"这件事
  和"丢了之后 `note` 里的文本标记还在"一起断言，免得复核人以为字段能扛过回滚。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.store import Store, StoreError
from agentflow.tokenmeter import Charge, TokenMeter, marker_of, note_tokens
from agentflow.verify import verify_all

TS = "2026-01-01T00:00:00+00:00"


# --------------------------------------------------------------------- 构造工具


def _entry(usage_id: str, *, idem_key: str = "", note: str = "测试") -> S.UsageEntry:
    return S.UsageEntry(
        usage_id=usage_id, scope="search", role="A", tokens_in=1, tokens_out=2,
        at=TS, note=note, idem_key=idem_key,
    )


def _raw(usage_id: str, *, idem_key: str | None = None, note: str = "测试") -> dict:
    """直接构造快照 dict（`idem_key=None` = 模拟未升级进程/历史写下的行）。"""
    row = {
        "usage_id": usage_id, "scope": "search", "role": "A", "task_id": None,
        "tokens_in": 1, "tokens_out": 2, "tokens_total": 3, "usd": 0.0,
        "attempts": 1, "at": TS, "note": note,
    }
    if idem_key is not None:
        row["idem_key"] = idem_key
    return row


def _doc(*rows: dict) -> dict:
    return {"schema_version": S.SCHEMA_VERSION, "rows": list(rows)}


def _write_snapshot(store: Store, *rows: dict) -> None:
    """绕过事务直接改快照 —— 模拟"外部脚本/旧版本写下的一行"。"""
    (store.data / "usage_ledger.json").write_text(
        json.dumps(_doc(*rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ============================================================ 字段形状


def test_idem_key_is_an_optional_dataclass_field():
    """判据①：默认值是空串，且是普通 dataclass 字段（不是 `default_factory`）。

    用 `default_factory` 会让 `asdict` 的形状变、也会让"老快照读回来"多一层解析；
    复核清单第 1 条问的正是这一件事。
    """
    assert S.UsageEntry.__dataclass_fields__["idem_key"].default == ""
    e = _entry("0000")
    assert e.idem_key == ""
    e.validate()
    assert e.to_dict()["idem_key"] == ""
    assert "idem_key" in S.row_from_dict("usage_ledger", _raw("0000")).to_dict()


# ============================================================ 唯一性断言（正控 / 负控）


def test_duplicate_non_empty_idem_key_is_rejected_with_both_ids():
    """正控（会红的负控）：两条同 `idem_key` 的行必须被表级断言抓到，且报出两个 `usage_id`。"""
    with pytest.raises(ValueError) as ei:
        S.validate_table("usage_ledger", _doc(_raw("0000", idem_key="idem-k"), _raw("0001", idem_key="idem-k")))
    msg = str(ei.value)
    assert "重复的幂等键" in msg
    assert "0000" in msg and "0001" in msg, "报错必须能定位到那两行"


def test_negative_control_empty_and_missing_keys_are_never_reported():
    """负控①（混合版本窗口）：空键 / 根本没有这个键的行都不许被误报，也不许互相冲突。

    未升级进程写下的行连 `idem_key` 这个键都没有；把它们算进唯一性会让
    整表提交直接炸（所有历史行"重复"），而那是比原缺陷更糟的形态。
    """
    S.validate_table("usage_ledger", _doc(_raw("0000"), _raw("0001"), _raw("0002", idem_key="")))
    assert S.row_from_dict("usage_ledger", _raw("0000")).idem_key == ""


def test_negative_control_distinct_keys_are_allowed():
    """负控②：不同的键必须都放行 —— 否则这条断言会退化成"表里只能有一行"。"""
    S.validate_table("usage_ledger", _doc(_raw("0000", idem_key="idem-a"), _raw("0001", idem_key="idem-b")))


@pytest.mark.parametrize("bad", ["  k", "k ", " k ", "\tk"])
def test_idem_key_with_surrounding_whitespace_is_rejected(bad: str):
    """判据②：首尾空白必须被拒（否则 '  k' 与 'k' 是两个键，唯一性形同虚设）。"""
    with pytest.raises(ValueError, match="idem_key 不许有首尾空白"):
        _entry("0000", idem_key=bad).validate()
    with pytest.raises(ValueError, match="idem_key 不许有首尾空白"):
        S.validate_table("usage_ledger", _doc(_raw("0000", idem_key=bad)))


def test_validate_table_keeps_working_for_rows_written_with_idem_key():
    """正控：一条带合法幂等键的行能正常过表级校验（这条断言不过，前两条就是空的）。"""
    S.validate_table("usage_ledger", _doc(_raw("0000", idem_key="idem-ok")))


# ============================================================ Tx.insert_unique


def test_insert_unique_writes_once_then_reports_conflict(store: Store):
    """正控：第一次 `True` 且真的落一行；第二次 `False` 且什么都没写。"""
    with store.tx("usage_ledger", actor="test") as tx:
        assert tx.insert_unique("usage_ledger", _raw("PENDING", idem_key="idem-x"),
                                "idem_key", id_kind="usage") is True
    rows = store.rows("usage_ledger")
    assert len(rows) == 1 and rows[0]["idem_key"] == "idem-x"

    with store.tx("usage_ledger", actor="test") as tx:
        assert tx.insert_unique("usage_ledger", _raw("PENDING", idem_key="idem-x"),
                                "idem_key", id_kind="usage") is False
    assert len(store.rows("usage_ledger")) == 1
    assert len([e for e in store.read_events() if e.get("table") == "usage_ledger"]) == 1, \
        "冲突路径一个事件都不许写（快照与事件流不许分家）"


def test_insert_unique_does_not_burn_an_id_on_conflict(store: Store):
    """正控：重复调用不分配 ID —— 否则每次重放都会在计数器上留下永久空洞。

    两次调用各开独立事务：ID 计数器是随事务落盘的，若判重放在 `alloc_id`
    之后，第二次即使什么都没写，`counters.json` 也已经被推着走过一格。
    """
    with store.tx("usage_ledger", actor="test") as tx:
        tx.insert_unique("usage_ledger", _raw("PENDING", idem_key="idem-y"), "idem_key",
                         id_kind="usage")
    first = dict(store.read("counters")["counters"])
    assert first.get("usage") == 1, first
    with store.tx("usage_ledger", actor="test") as tx:
        tx.insert_unique("usage_ledger", _raw("PENDING", idem_key="idem-y"), "idem_key",
                         id_kind="usage")
    assert dict(store.read("counters")["counters"]) == first


def test_insert_unique_on_distinct_keys_writes_two_rows(store: Store):
    """负控③：不同的键必须落两行 —— 防"装置本身写不进去"导致的假绿。"""
    for key in ("idem-p", "idem-q"):
        with store.tx("usage_ledger", actor="test") as tx:
            assert tx.insert_unique("usage_ledger", _raw("PENDING", idem_key=key),
                                    "idem_key", id_kind="usage") is True
    assert len(store.rows("usage_ledger")) == 2


def test_insert_unique_rejects_an_empty_key(store: Store):
    """负控④：空键必须抛，而不是静默"当作不冲突"（那会让唯一性完全失效）。"""
    with pytest.raises(StoreError, match="为空"):
        with store.tx("usage_ledger", actor="test") as tx:
            tx.insert_unique("usage_ledger", _raw("PENDING", idem_key="  "), "idem_key")
    assert store.rows("usage_ledger") == []


def test_negative_control_verifier_catches_what_insert_unique_cannot(store: Store):
    """负控⑤：`insert_unique` 管不住绕过它的两条写入。

    两条不同 `usage_id`、同一个非空键的行若通过其它路径落进表里（旧版本写入、
    手工改快照、两个进程各写一行），`insert_unique` 不会响 ——
    此时唯一能报警的是 `verify` 的 `duplicate_idem_key`。
    """
    _write_snapshot(store, _raw("0000", idem_key="idem-dup"), _raw("0001", idem_key="idem-dup"))
    codes = {i.code for i in verify_all(store).issues}
    assert "duplicate_idem_key" in codes


# ============================================================ verify 判据


def test_verify_reports_duplicate_idem_key(store: Store):
    """正控：审计必须报 `duplicate_idem_key`（error 级），并给出两个 `usage_id`。"""
    _write_snapshot(store, _raw("0000", idem_key="idem-dup"), _raw("0001", idem_key="idem-dup"))
    rep = verify_all(store)
    hits = [i for i in rep.issues if i.code == "duplicate_idem_key"]
    assert len(hits) == 1, rep.issues
    assert hits[0].level == "error"
    assert "idem-dup" in hits[0].message and "0000" in hits[0].message


def test_verify_does_not_report_rows_without_idem_key(store: Store):
    """负控⑥：历史行（无字段）与空键行都不许被报 —— 否则审计会被噪音淹没。"""
    _write_snapshot(store, _raw("0000"), _raw("0001"), _raw("0002", idem_key=""))
    rep = verify_all(store)
    assert [i for i in rep.issues if i.code == "duplicate_idem_key"] == []


def test_verify_allows_distinct_keys(store: Store):
    """负控⑦（与正控成对）：不同的键必须放行。"""
    _write_snapshot(store, _raw("0000", idem_key="idem-a"), _raw("0001", idem_key="idem-b"))
    rep = verify_all(store)
    assert [i for i in rep.issues if i.code == "duplicate_idem_key"] == []


def test_verify_surfaces_the_old_criterion_that_cannot_see_it(store: Store):
    """背景事实（写下来，免得复核人以为 duplicate_id 能兜住这件事）：

    重复记账的两行主键本来就不同，所以 `duplicate_id` 永远不响，
    也不会有 `id_gap`（0000/0001 是连续的）—— 这条缺陷只能靠新判据看见。
    """
    _write_snapshot(store, _raw("0000", idem_key="idem-dup"), _raw("0001", idem_key="idem-dup"))
    codes = {i.code for i in verify_all(store).issues}
    assert "duplicate_idem_key" in codes
    assert "duplicate_id" not in codes and "id_gap" not in codes


# ============================================================ 回滚陷阱


def test_rollback_drops_the_field_but_the_note_marker_survives(store: Store, monkeypatch) -> None:
    """回滚陷阱（真跑一遍 `rebuild`，不是推理）：

    `row_from_dict` 按 `__dataclass_fields__` 过滤，所以回滚代码之后
    一次 `rebuild` 会把 `idem_key` 静默丢掉；而 `note` 里的文本标记（提案 B 那一层）
    是老字段，回滚不丢 —— 这正是"两层都要留着"的操作性理由。

    回滚在这里是真的换成一个不认识 `idem_key` 的旧 dataclass 来跑 rebuild：
    只把键从 `__dataclass_fields__` 里删掉是模拟不出来的（`asdict` 另有一份字段表），
    所以用"旧类 + 按字段过滤的 row_from_dict"逐字复刻老代码。

    注意 `rebuild` 的"合并而非替换"那一行（`store.rebuild`）：若事件里本来就带着
    `idem_key`，它会被当作"其它键"原样保留 —— 丢字段只发生在事件流里也没有它
    的那一类行上（老版本写的事件、被清洗过的事件流、以及从快照而非事件恢复的行）。
    下面两条断言分别覆盖这两种形态。
    """
    key = marker_of("idem", "t-rollback", 0)
    meter = TokenMeter(store)
    meter.charge_once(Charge(role="A", scope="search", tokens_in=1500, note="x"), idem_key=key)
    with store.tx("usage_ledger", actor="test") as tx:
        r = tx.rows("usage_ledger")[0]
        r["idem_key"] = key
        tx.upsert("usage_ledger", r)
    assert store.rows("usage_ledger")[0]["idem_key"] == key

    @dataclass
    class OldUsageEntry:
        """回滚后的那一版 `UsageEntry`：没有 `idem_key`，其余字段逐字相同。"""

        usage_id: str
        scope: str
        role: str = "unknown"
        task_id: str | None = None
        tokens_in: int = 0
        tokens_out: int = 0
        tokens_total: int = 0
        usd: float = 0.0
        attempts: int = 1
        at: str = ""
        note: str = ""

        def validate(self) -> None:
            pass

        def to_dict(self) -> dict:
            return asdict(self)

    def old_row_from_dict(table: str, raw: dict):
        return OldUsageEntry(**{k: v for k, v in raw.items()
                                if k in OldUsageEntry.__dataclass_fields__})

    # (a) 事件流里也没有这个键的行（老版本写的事件）：rebuild 之后字段消失。
    row_without_key = {k: v for k, v in store.rows("usage_ledger")[0].items() if k != "idem_key"}
    obj = old_row_from_dict("usage_ledger", row_without_key)
    canonical = obj.to_dict()
    merged = {k: v for k, v in row_without_key.items() if k not in canonical}
    merged.update(canonical)
    assert "idem_key" not in merged, "回滚后 rebuild 会静默丢掉这个字段（无任何报错）"
    assert key in note_tokens(merged["note"]), "标记必须还在 —— 这是回滚后仍然有效的保护"

    # (b) 真跑一次 rebuild（事件里带着这个键）：字段能活下来，但不是因为老代码认识它，
    #     而是 rebuild 的"未知键原样保留"这一行。两件事必须分得开。
    monkeypatch.setitem(S.TABLES["usage_ledger"], "row", OldUsageEntry)
    monkeypatch.setattr(S, "row_from_dict", old_row_from_dict)
    store.rebuild()
    after = store.rows("usage_ledger")[0]
    assert after["idem_key"] == key
    assert after["idem_key"] not in asdict(old_row_from_dict("usage_ledger", after)), \
        "旧 dataclass 不认识它 —— 它的存活纯粹来自事件里的原始键"
    assert key in note_tokens(after["note"])


# ============================================================ 混合版本窗口（端到端）


def test_mixed_version_window_snapshot_still_commits(store: Store):
    """混合版本窗口②：老行（无字段）+ 新行（带键）在同一张表里必须能提交。

    新版进程与未升级进程并存时,这张表就是长这样。老行既不能让它炸，
    也不能给旧缺陷留洞：新行之间的重复仍然被抓住。
    """
    _write_snapshot(store, _raw("0000"), _raw("0001", idem_key="idem-new"))
    with store.tx("usage_ledger", actor="test") as tx:
        row = tx.rows("usage_ledger")[0]
        row["note"] = "旧版本写下的一行"
        tx.mark_dirty("usage_ledger")
    assert len(store.rows("usage_ledger")) == 2

    with pytest.raises(ValueError, match="重复的幂等键"):
        with store.tx("usage_ledger", actor="test") as tx:
            tx.upsert("usage_ledger", _raw("0002", idem_key="idem-new"))  # 收到第 3 行
    assert len(store.rows("usage_ledger")) == 2, "失败事务不许留下半成品"

    # 端到端：连旧行一起看，审计也对这张表给出正确的结论
    _write_snapshot(store, _raw("0000"), _raw("0001", idem_key="idem-new"),
                    _raw("0002", idem_key="idem-new"))
    codes = {i.code for i in verify_all(store).issues}
    assert "duplicate_idem_key" in codes
    assert "schema_invalid" in codes, "存储层断言与审计判据是两层，两层都该响"


def test_rebuild_keeps_the_field_when_the_dataclass_has_it(store: Store, tmp_path: Path):
    """正控：字段在 dataclass 里时，`rebuild` 不许丢它（与上面那条回滚陷阱成对）。"""
    key = "idem-rebuild"
    with store.tx("usage_ledger", actor="test") as tx:
        tx.insert_unique("usage_ledger",
                         {**_raw("PENDING"), "idem_key": key}, "idem_key", id_kind="usage")
    store.rebuild()
    assert [r["idem_key"] for r in store.rows("usage_ledger")] == [key]
