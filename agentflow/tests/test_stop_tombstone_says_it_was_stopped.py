# -*- coding: utf-8 -*-
"""判据（B5）：删掉开关之后要留下"停过"的墓碑，三态读得出来。

改前：`consume_stop` 删完开关，`read_stop()` 返回 `None` —— 与"从来没有人叫停"同形。
停机之后往同一个工作区写盘既不拦也不标记（反例③；真机 22:54 那三份产物因此归不到
任何一行账上）。现在真删除时追加一行 `runs/stop-closed.jsonl`（时间 + 理由 + 哪一趟），
读口 `stop_closure` 三态：`none`（没停过）/ `closed`（停过且已消费）/ `unknown`
（墓碑读不出来 —— 不许当"没停过"）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import stopctl


def test_a_workspace_that_was_never_stopped_reads_as_no_record(tmp_path: pathlib.Path) -> None:
    """从没停过 ⇒ `none`，且理由逐字说"没有停机记录"（不是"读不出来"）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    got = stopctl.stop_closure(ws)
    assert got["checked"] is True, got
    assert got["state"] == "none", got
    assert "没有停机记录" in got["why"], got
    assert got["last"] == {}, got


def test_a_consumed_stop_reads_as_closed_with_time_reason_and_run(
        tmp_path: pathlib.Path) -> None:
    """停过且已删 ⇒ `closed`，墓碑读得出时间 / 理由 / 哪一趟；同时 `read_stop` 已是 None。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    stopctl.request_stop(ws, reason="业主：真机数据已够", by="user")
    record = stopctl.consume_stop(ws, sid="2026-11-14", level="force_stop", remove=True)

    assert record["removed"] is True, record
    assert record["tombstoned"] is True, record
    assert stopctl.read_stop(ws) is None, "开关本身已被消费"
    got = stopctl.stop_closure(ws)
    assert got["checked"] is True, got
    assert got["state"] == "closed", got
    assert got["count"] == 1, got
    last = got["last"]
    assert last["reason"] == "业主：真机数据已够", last
    assert last["sid"] == "2026-11-14", last
    assert last["level"] == "force_stop", last
    assert last["closed_at"], last
    assert last["force"] is False, last
    assert "2026-11-14" in got["why"] and "业主：真机数据已够" in got["why"], got


def test_a_kept_switch_leaves_no_tombstone(tmp_path: pathlib.Path) -> None:
    """成员只记一笔（开关留给别人）⇒ 不是"停了并已删"，不写墓碑。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    stopctl.request_stop(ws, reason="user", by="user")
    record = stopctl.consume_stop(ws, sid="s-member", remove=False)

    assert record["removed"] is False, record
    assert "tombstoned" not in record, record
    assert not stopctl.closed_path(ws).is_file(), "没删开关却写了墓碑"
    assert stopctl.stop_closure(ws)["state"] == "none"


def test_an_unreadable_tombstone_is_unknown_not_none(tmp_path: pathlib.Path) -> None:
    """三态：墓碑读不出来 ⇒ `unknown`，绝不许折成"没停过"。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    path = stopctl.closed_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{这不是 JSON\n", encoding="utf-8", newline="\n")

    got = stopctl.stop_closure(ws)
    assert got["checked"] is True, got
    assert got["state"] == "unknown", got
    assert "不许当" in got["why"], got
    assert got["problems"], got


def test_anti_vacuum_stubbing_the_tombstone_off_leaves_none(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把墓碑写入打桩成写不进去 ⇒ 删完读成 `none`（上一条判据当场必红）。

    手法：把 `closed_path` 指到一个普通文件下面 —— `parent.mkdir()` 抛
    `NotADirectoryError`，`_append_tombstone` 如实返回 `written=False`。这证明
    "墓碑读得出 closed" 不是白给的：那个文件必须真的被写过。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    anchor = tmp_path / "anchor"
    anchor.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(stopctl, "closed_path", lambda root: anchor / "stop-closed.jsonl")

    stopctl.request_stop(ws, reason="user", by="user")
    record = stopctl.consume_stop(ws, sid="s-vacuum", remove=True)

    assert record["removed"] is True, record
    assert record["tombstoned"] is False, record
    assert record.get("tombstone_problem"), (
        "墓碑写不进去必须留下原话（静默失败正是 B5 要消灭的那一档）", record)
    assert stopctl.stop_closure(ws)["state"] == "none", (
        "墓碑没写成却读出了 closed —— 打桩没生效，反真空不成立")


def test_the_tombstone_is_append_only_across_stops(tmp_path: pathlib.Path) -> None:
    """两次叫停 ⇒ 两行墓碑（`count=2`，`last` 是后一次），不是覆盖。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    for sid, reason in (("s-1", "第一次"), ("s-2", "第二次")):
        stopctl.request_stop(ws, reason=reason, by="user")
        stopctl.consume_stop(ws, sid=sid, remove=True)
    rows = [json.loads(x) for x in
            stopctl.closed_path(ws).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 2, rows
    got = stopctl.stop_closure(ws)
    assert got["count"] == 2, got
    assert got["last"]["sid"] == "s-2", got
    assert got["last"]["reason"] == "第二次", got
