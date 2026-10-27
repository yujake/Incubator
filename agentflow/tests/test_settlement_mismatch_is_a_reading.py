"""结算核对读数（`litstage.settlement_mismatch` / `settlement_readings`）的判据。

## 它守的是什么

`apply_settlement` 里有两个 `continue`：决定指向的槽位读不到、或状态码不认 —— 那一笔
决定被静默丢掉。而调用方的 `admitted[]` 取自登记路径回来的 `lit_ids`，不是取自
结算结果 ⇒ 并发窗口里可以出现"报告说已入库、候选行还是 pending"。这两种形态此前
没有任何地方会说话。

## 这条判据钉什么

- 正常路径：读数必须是空（"结算与报告一致"是一个有内容的读数，不是"没查"）；
- 人为制造不一致 ⇒ 必须红（三种形态各一条：行上没写成、槽位读不到、决定被丢掉）；
- 它不改行为：判据里同时核"那一行真的还是 pending"—— 读数只加一条，不动盘。
"""

from __future__ import annotations

from typing import Any

import pytest

from agentflow import litstage as LS
from agentflow import schema as S
from agentflow.store import Store


def _seed(store: Store, *, slots: int, relevance: bool = True) -> list[str]:
    """造 `slots` 条 pending 候选（默认每条都带 relevance，于是它能过逐条判据）。"""
    out: list[str] = []
    with store.tx("lit_candidates", "counters", actor="probe", note="seed") as tx:
        for i in range(slots):
            slot = tx.alloc_id("candidate")
            tx.upsert("lit_candidates", {
                "slot": slot, "request_id": "r-000001", "batch": 1, "status": "pending",
                "title": f"a distinct probe paper {i} on zeta", "doi": f"10.9/x.{i}",
                "provider": "probe", "year": 2024, "type_code": "J", "summary": "s",
                "url": "", "relevance": ("判据：为什么相关" if relevance else ""),
                "added_at": S.now_iso()}, note="seed")
            out.append(slot)
    return out


def _row(store: Store, slot: str) -> dict:
    return next(r for r in store.rows("lit_candidates") if str(r.get("slot")) == slot)


@pytest.fixture(autouse=True)
def _clean_readings():
    """每条判据前后清空读数（进程内账，判据之间必须互不污染）。"""
    LS.settlement_readings(reset=True)
    yield
    LS.settlement_readings(reset=True)


def test_the_normal_path_leaves_the_reading_empty(store: Store) -> None:
    """正控：真的结算成功之后，读数必须是空的（且行上真的写成了 admitted）。"""
    slots = _seed(store, slots=2)
    decisions = [{"slot": s, "status": "admitted", "lit_id": "000000",
                  "relevance": "判据：为什么相关"} for s in slots]
    with store.tx("lit_candidates", actor="probe", note="settle") as tx:
        LS.apply_settlement(tx, decisions)

    got = LS.settlement_mismatch(store, decisions, request_id="r-000001")
    assert got["checked"] is True, got
    assert got["count"] == 0, got["rows"]
    assert got["reason"] == "", got
    assert LS.settlement_readings()["count"] == 0, LS.settlement_readings()
    for s in slots:
        assert _row(store, s)["status"] == "admitted", _row(store, s)


def test_a_decision_that_never_landed_is_named(store: Store) -> None:
    """负控 1：只写决定、不结算 ⇒ "报告说入库、行还是 pending"必须被点出来。

    这正是并发窗口里的那个形态：`lit_ids` 回来了（报告据此说已入库），
    而候选行那一笔没落盘。
    """
    slots = _seed(store, slots=1)
    decisions = [{"slot": slots[0], "status": "admitted", "lit_id": "000000"}]
    got = LS.settlement_mismatch(store, decisions)
    assert got["count"] == 1, got
    row = got["rows"][0]
    assert row["kind"] == "status_not_written" and row["slot"] == slots[0], row
    assert row["expected"] == "admitted" and row["got"] == "pending", row
    # 读数只加一条，不动盘（判据自己核这一条）
    assert _row(store, slots[0])["status"] == "pending", "读数把盘改了？"
    assert LS.settlement_readings()["count"] == 1


def test_a_decision_for_an_unknown_slot_is_named(store: Store) -> None:
    """负控 2：决定指向一个不存在的槽位 ⇒ `missing_row`。"""
    _seed(store, slots=1)
    got = LS.settlement_mismatch(store, [{"slot": "999999", "status": "admitted"}])
    assert got["count"] == 1 and got["rows"][0]["kind"] == "missing_row", got


def test_a_lit_id_that_was_not_written_is_named(store: Store) -> None:
    """负控 3：状态写成了、`lit_id` 却是另一个（或空）⇒ `lit_id_not_written`。"""
    slots = _seed(store, slots=1)
    with store.tx("lit_candidates", actor="probe", note="settle") as tx:
        LS.apply_settlement(tx, [{"slot": slots[0], "status": "admitted",
                                  "lit_id": "000000", "relevance": "判据：为什么相关"}])
    got = LS.settlement_mismatch(store, [{"slot": slots[0], "status": "admitted",
                                          "lit_id": "000042"}])
    assert got["count"] == 1 and got["rows"][0]["kind"] == "lit_id_not_written", got
    assert got["rows"][0]["expected"] == "000042", got["rows"][0]
    assert got["rows"][0]["got"] == "000000", got["rows"][0]


def test_a_dropped_decision_leaves_a_reading(store: Store) -> None:
    """①-3 的直接证据：`apply_settlement` 丢掉的决定必须留下 `dropped_*` 读数。

    两条 `continue` 都走一遍：槽位读不到、状态码不认。行为不变（仍然丢掉那一笔），
    但"丢掉了"这件事从此有据可查 —— 这正是"先要读数、再谈修不修行为"。
    """
    slots = _seed(store, slots=1)
    with store.tx("lit_candidates", actor="probe", note="settle") as tx:
        written = LS.apply_settlement(tx, [
            {"slot": "999999", "status": "admitted", "lit_id": "000000"},
            {"slot": slots[0], "status": "这不是一个合法状态"},
        ])
    assert written == [], written          # 行为不变：两笔都被丢掉
    kinds = [r["kind"] for r in LS.settlement_readings()["rows"]]
    assert kinds == ["dropped_slot", "dropped_status"], kinds
    assert _row(store, slots[0])["status"] == "pending", "丢掉的那一笔把行改了？"


def test_no_store_is_not_the_same_as_consistent() -> None:
    """三态：没有 store ⇒ `checked=False`（没查成），而不是"一致"。"""
    got = LS.settlement_mismatch(None, [{"slot": "000000", "status": "admitted"}])
    assert got["checked"] is False and got["count"] == 0, got
    assert "没查成" in got["reason"], got


def test_the_admit_path_goes_through_the_check(store: Store) -> None:
    """接线：`lit.admit` 真的会在结算之后调一次核对（不是只有测试直接调它）。

    做法：把 `settlement_mismatch` 打桩成一个记录调用次数的替身，跑一次真的
    `admit`，断言它被调过、且带了这一笔的 `request_id`。
    """
    slots = _seed(store, slots=1)
    calls: list[dict[str, Any]] = []
    real = LS.settlement_mismatch

    def spy(store_arg, decisions, *, request_id=""):
        calls.append({"slots": [str(d.get("slot") or "") for d in decisions],
                      "request_id": request_id})
        return real(store_arg, decisions, request_id=request_id)

    LS.settlement_mismatch = spy
    try:
        got = LS.admit(store, registrar=lambda row: {"lit_id": "000000"},
                       request_id="r-000001", slots=slots, write_report_file=False)
    finally:
        LS.settlement_mismatch = real
    assert got.get("ok") is True, got
    assert calls, "admit 结算之后没有回读核对（读数等于没人写）"
    assert calls[0]["slots"] == slots and calls[0]["request_id"] == "r-000001", calls
