# -*- coding: utf-8 -*-
"""判据（B4）：停机历史把「请求删除」与「确实已删」分开记，读侧只把后者当删除。

改前：`stopctl.consume_stop` 先写 `record["removed"] = bool(remove)`，再 `path.unlink()`，
撤不掉被 `except OSError: pass` 吞掉 ⇒ 历史说"删了"、文件还在盘上（审计说谎 +
下一趟被同一把开关再停一次，正是 `draft/37` §140 那个 bug 的反向复发）。
现场与最小反例②见 `temp/analysis/09-stop-switch.md` §3 B4 / §5。

这一条钉三件事：
1. 撤不掉 ⇒ 记「请求了、未删」（`remove_requested=True` / `removed=False` / 原因）；
2. 真删掉 ⇒ 记「已删」（`removed=True` + `removed_at`）；
3. 读侧（`stop_history` 的 `deletion_state`）只把第 2 档当删除；老记录只有请求值 ⇒
   `unknown_legacy`（不许当"已删"，也不许当"没停过"）。
"""
from __future__ import annotations

import pathlib

from agentflow import stopctl


def _row(ws: pathlib.Path) -> dict:
    rows = stopctl.stop_history(ws, limit=10)
    assert rows, "历史里一行都没有 —— 判据失去对象（不是通过）"
    return rows[-1]


def test_a_held_switch_is_recorded_as_requested_not_deleted(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """撤不掉（被占着）⇒ 历史必须记「请求了、未删」，而盘上文件确实还在。

    手法与反例②同形：Windows 上 `open()` 持有句柄即挡住 `unlink`。测试里用
    `PermissionError` 打桩是同一件事的确定性写法（不依赖跑测试的平台）。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    stopctl.request_stop(ws, reason="user", by="user")

    real_unlink = pathlib.Path.unlink

    def _blocked(self: pathlib.Path, *args, **kwargs):
        if self.name == stopctl.STOP_FILE_NAME:
            raise PermissionError("模拟：开关文件被别的进程占着（Windows 上 open() 持有句柄）")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", _blocked)
    record = stopctl.consume_stop(ws, sid="s-held", level="stop_file", remove=True)

    assert record["remove_requested"] is True, record
    assert record["removed"] is False, (
        "撤不掉却记成了已删 —— 审计与盘上事实相反（这正是 B4）", record)
    assert record.get("removed_at", "") == "", record
    assert "PermissionError" in str(record.get("remove_problem") or ""), record
    assert stopctl.stop_path(ws).is_file(), "文件还在盘上，历史不许说删了"
    row = _row(ws)
    assert row["deletion_state"] == "requested_not_deleted", row
    assert row["deleted"] is False, row


def test_a_real_deletion_is_recorded_as_deleted(tmp_path: pathlib.Path) -> None:
    """真删掉 ⇒ 记「已删」，并给删除时刻（不是请求时刻）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    stopctl.request_stop(ws, reason="user", by="user")
    record = stopctl.consume_stop(ws, sid="s-ok", level="stop_file", remove=True)

    assert record["remove_requested"] is True, record
    assert record["removed"] is True, record
    assert record["removed_at"], record
    assert not stopctl.stop_path(ws).is_file(), "记了已删，文件就必须真的不在"
    row = _row(ws)
    assert row["deletion_state"] == "deleted", row
    assert row["deleted"] is True, row


def test_a_member_that_keeps_the_switch_is_not_a_deletion(tmp_path: pathlib.Path) -> None:
    """成员只记一笔（`remove=False`）⇒ 「没请求删」，读作 `kept`，开关留给别人。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    stopctl.request_stop(ws, reason="user", by="user")
    record = stopctl.consume_stop(ws, sid="s-member", level="stop_file", remove=False)

    assert record["remove_requested"] is False, record
    assert record["removed"] is False, record
    assert stopctl.stop_path(ws).is_file(), "成员不许撤开关（同一棵树上别人还要读到它）"
    row = _row(ws)
    assert row["deletion_state"] == "kept", row
    assert row["deleted"] is False, row


def test_an_old_row_with_only_the_request_value_is_not_read_as_deleted(
        tmp_path: pathlib.Path) -> None:
    """老记录只有 `removed`（请求值）⇒ 读作 `unknown_legacy`，不许冒充"已删"。"""
    import json

    ws = tmp_path / "ws"
    ws.mkdir()
    hist = stopctl.history_path(ws)
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text(json.dumps({
        "reason": "user", "by": "user", "force": False, "at": "2026-11-14T22:00:27+08:00",
        "sid": "2026-11-14", "path": str(stopctl.stop_path(ws)),
        "consumed_at": "2026-11-14T22:01:38+08:00", "consumed_by_sid": "s1",
        "level": "stop_file", "removed": True,
    }, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    row = _row(ws)
    assert row["deletion_state"] == "unknown_legacy", row
    assert row["deleted"] is False, ("老记录的 `removed=True` 记的是请求值，"
                                     "不许被读成「确实已删」", row)


def test_anti_vacuum_stubbing_the_history_write_leaves_no_row(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把历史写入打桩成写不进去 ⇒ 上面那几条判据当场失去对象（必红）。

    手法：把 `history_path` 指到一个普通文件下面 —— `hist.parent.mkdir()` 抛
    `NotADirectoryError`（OSError），被 `consume_stop` 如实吞掉（历史写不下去不该让
    停机失效）⇒ `stop_history` 一行都读不到。这证明"记录真的写进去了"不是白给的。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    anchor = tmp_path / "anchor"
    anchor.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(stopctl, "history_path",
                        lambda root: anchor / "stop-history.jsonl")

    stopctl.request_stop(ws, reason="user", by="user")
    record = stopctl.consume_stop(ws, sid="s-vacuum", remove=True)

    assert record["removed"] is True, "删除结局仍然要在返回值里读得出来"
    assert stopctl.stop_history(ws, limit=10) == [], (
        "历史写不进去却读出了行 —— 打桩没生效，反真空不成立")
