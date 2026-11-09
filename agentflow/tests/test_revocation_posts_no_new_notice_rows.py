# -*- coding: utf-8 -*-
"""D13：撤销动作不再自己生成新的 `notice` 行（清理不该让"待办"变多）。

## 真机病灶（`_audit_steps_and_timeouts.md` §3.3 第 5 条）

M 花 1 步 `void_items` 撤 12 条（11:09:10），**撤销动作自身又落 12 条新 notice 行**
（t-000095..t-000106）。而那 12 行同样是板项行 ⇒ `status` 恒为 `pending`（叠上 D12
就是"12 条新待办"）⇒ 观感是「越清越多」。

改前读数（本仓夹具，N=5）：

    tasks 行数 8 → 13（+5）· revoke-notice@ 0 → 5（+5）· notified 5 条

## 改法（业主 2026-11-09 认的那一版）

撤销**不落新行**：提醒的载体是被撤那一行自己的 `inputs`
（`revoke:expired:by=…:owner=…:from=…:to=done:at=…:reason=…`，append-only 六格），
收件人那一侧的读口是 `Conductor.revoked_recent_of`（`agent_loop.mailbox_digest`
每一拍渲染成【最近被撤销的项】）。于是**新增 notice 行 = 0**，而
"谁撤的 / 为什么 / 你不需要再处理它"一个字都没少。

## 这一份钉什么

| 格 | 用例 |
|---|---|
| a | `test_a_revoking_n_items_adds_zero_task_rows`（新增行数 = 0，N=12 照真机） |
| b | `test_b_the_revoked_items_are_still_traceable`（可查性：状态 + 撤销者 + 理由） |
| c | `test_c_opening_the_old_branch_adds_n_rows_again`（反真空） |
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

N = 12          # 真机那一步撤的条数（t-000095..t-000106）
REVOKE_NOTICE_PREFIX = "revoke-notice@"
WHY = "这些板项是已收工子代理名下没人会再处理的收尾项"


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor, dict[str, str]]:
    """M（根）→ D1（父）→ F1：F1 名下 N 条待撤的 notice。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    box = Conductor(st, policy=None, backend=LocalBackend({}))
    ids = {"M": _agent(box, role="M", parent=None, detail="顶趟")}
    ids["D1"] = _agent(box, role="D", parent=ids["M"], detail="D1")
    ids["F1"] = _agent(box, role="F", parent=ids["D1"], detail="F1")
    return ws, box, ids


def _agent(box: Conductor, *, role: str, parent: str | None, detail: str) -> str:
    return box._write_new_row({
        "role": role, "action": "run", "called_by": (parent and "M") or "user",
        "parent_task_id": parent, "depth": (1 if parent is None else 2),
        "input_key": f"d13:{role}:{detail}", "status": "running", "outcome": None,
        "refusal_reason": None, "instance": "", "detail": detail, "error": None,
        "started_at": "2026-11-09T08:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note=f"d13:agent:{role}")


def _items(box: Conductor, ids: Mapping[str, str], n: int) -> list[str]:
    """收件人已经收工、名下 N 条 `seen` 未消项（真机那一屏的形状）。"""
    out: list[str] = []
    for i in range(1, n + 1):
        item = box.open_item(kind="notice", role="F", expects="ack", action="notice",
                             summary=f"第 {i} 条没人会再处理的收尾项",
                             called_by="clock", parent_task_id=ids["F1"], depth=2,
                             input_key=f"d13:notice:{i}")
        out.append(item)
    return out


def _rows(box: Conductor) -> list[dict[str, Any]]:
    return [dict(r) for r in box._tasks()]


def _notice_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """本次撤销会新增的那一种行（旧口径的 `revoke-notice@…`）。"""
    return [r for r in rows
            if str(r.get("input_key") or "").startswith(REVOKE_NOTICE_PREFIX)]


def _board_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """板项行（`kind` 非空）—— "notice 数" 的宽口径（含旧口径之外的任何新板项）。"""
    return [r for r in rows if str(r.get("kind") or "")]


def _revoke(box: Conductor, ids: Mapping[str, str], items: list[str]) -> dict[str, Any]:
    return box.void_items(items, by_task_id=ids["D1"], why=WHY, revoke=True)


# ---------------------------------------------------------------- a —— 新增行数 = 0


def test_a_revoking_n_items_adds_zero_task_rows(tmp_path: pathlib.Path) -> None:
    """a：撤销 N 条之后新增的 `tasks` 行数 = 0（两条口径：总行数 / notice 行数）。"""
    ws, box, ids = _ws(tmp_path)
    items = _items(box, ids, N)
    before = _rows(box)
    got = _revoke(box, ids, items)
    after = _rows(box)

    assert got["voided"] == items, got
    assert got["refused"] == [], got
    # 判据本体
    assert len(after) == len(before), (
        f"撤销 {N} 条新增了 {len(after) - len(before)} 行 tasks "
        f"（清理动作不该让台账变长）：{len(before)} → {len(after)}")
    assert len(_notice_rows(after)) == len(_notice_rows(before)) == 0, (
        f"撤销之后仍然落了 {len(_notice_rows(after))} 条 revoke-notice 行")
    assert len(_board_rows(after)) == len(_board_rows(before)), (
        "撤销之后板项行多了 ⇒ 新增的是别的名字的通知行")
    # 提醒没有消失：`notified` 逐条给出载体（不是一行新台账）
    notified = list(got["notified"])
    assert len(notified) == N, notified[:2]
    assert {str(x["item_id"]) for x in notified} == set(items), notified[:2]
    for one in notified:
        assert str(one["notice_id"]) == "", one
        assert str(one["carrier"]) == f"revoked_recent@{ids['F1']}", one


# ---------------------------------------------------------------- b —— 可查性


def test_b_the_revoked_items_are_still_traceable(tmp_path: pathlib.Path) -> None:
    """b：被撤条目仍可查 —— 状态 + 撤销者 + 理由（三格逐条给读数）。"""
    ws, box, ids = _ws(tmp_path)
    items = _items(box, ids, N)
    assert _revoke(box, ids, items)["voided"] == items
    rows = {str(r.get("task_id")): r for r in _rows(box)}

    for item in items:
        row = rows[item]
        assert (str(row["item_state"]), str(row["item_close"])) == ("done", "expired"), row
        assert str(row["expects"]) == "", row
        assert str(row["expects_was"]) == "ack", row
        marks = [str(x) for x in (row.get("inputs") or [])
                 if str(x).startswith("revoke:expired:")]
        assert len(marks) == 1, (item, marks)
        mark = marks[0]
        for needle in (f"by={ids['D1']}", f"owner={ids['F1']}", "from=queued",
                       "to=done", "at=", f"reason={WHY}"):
            assert needle in mark, (item, mark)
    # 收件人那一侧的读口：五格（编号 / 谁撤的 / 理由 / 何时 / 摘要）
    recent = box.revoked_recent_of(ids["F1"], limit=N)
    assert len(recent) == N, recent[:2]
    first = next(e for e in recent if str(e["item_id"]) == items[0])
    assert first["by"] == ids["D1"], first
    assert first["reason"] == WHY, first
    assert first["at"], first
    assert first["summary"] == "第 1 条没人会再处理的收尾项", first
    # 它不欠任何动作，也不冒充"名下还有未消项"
    assert items[0] not in {str(r.get("task_id")) for r in box.open_items_of(ids["F1"])}
    # 旧口径那种行一条都没有 ⇒ 也不存在"撤通知又生成通知"的环
    assert _notice_rows(_rows(box)) == []


# ---------------------------------------------------------------- c —— 反真空


def test_c_opening_the_old_branch_adds_n_rows_again(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """c：把"不生成通知"改回旧行为（`REVOKE_POSTS_NOTICE_ROW=True`）⇒ 新增数又变 N。"""
    assert Conductor.REVOKE_POSTS_NOTICE_ROW is False, (
        "默认口径必须是「不落通知行」（这个属性被改过 ⇒ c 条的反真空失去对照）")

    ws, box, ids = _ws(tmp_path / "new")
    items = _items(box, ids, N)
    before = _rows(box)
    _revoke(box, ids, items)
    assert len(_rows(box)) == len(before), "改后口径没有做到新增 0 行"

    monkeypatch.setattr(Conductor, "REVOKE_POSTS_NOTICE_ROW", True)
    ws2, box2, ids2 = _ws(tmp_path / "old")
    items2 = _items(box2, ids2, N)
    before2 = _rows(box2)
    got = _revoke(box2, ids2, items2)
    after2 = _rows(box2)
    assert got["voided"] == items2, got
    assert len(after2) - len(before2) == N, (
        f"旧行为打开之后新增行不是 {N} 条：{len(after2) - len(before2)}"
        " ⇒ a 条其实没在数行（反真空失败）")
    assert len(_notice_rows(after2)) == N, _notice_rows(after2)[:2]
