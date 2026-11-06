# -*- coding: utf-8 -*-
"""业主裁定 ①：父可以撤自己直接子名下的板项，M 可以撤任意代理的板项（必须留痕）。

## 裁定原文（逐字）

    1.给父代理可以更改子代理板项状态的能力，可将不再需要做的任务标为撤销，
      特别地 M 可通过审计工具更改任意代理的板项状态。

## 这一组钉什么

旧口径（`Conductor.void_items` 的边界 2）：作废必须证明"收件人叫不醒了"
（已销号 / 兜底表被永久抑制），只是静默都不够 —— 拒信最后一句逐字是
「不许拿『它不会再看』当理由」。业主这一笔裁定把它按权限解除：

- 父（`tasks` 里那个直接父代理）可以把自己直接子名下的板项标撤销；
- M（`conductor`，`role=M` 的顶趟）可以撤任意代理的板项（不限直接子）；
- 两者都必须留痕：`by` / `owner` / `reason` / `from` / `to` / `at` 六格落进行
  的 `inputs`（append-only）与事件 note，并且写入口的读数里也查得到；
- 没有权限的人（兄弟 / 祖父 / 别人的项）仍受控拒绝 —— 权限不是"谁都能撤"。

## 六条判据（与任务单 a–f 对齐）

| 格 | 用例 |
|---|---|
| a | `test_a_parent_revokes_a_direct_childs_item_with_a_trace` |
| b | `test_the_conductor_m_may_revoke_any_agents_item` |
| c | `test_a_child_still_acks_its_own_item` |
| d | `test_a_sibling_or_a_grandparent_is_still_refused` |
| e | `test_the_authority_check_is_the_load_bearing_gate`（打桩成恒假 ⇒ a/b 红） |
| f | `test_the_board_readings_drop_the_revoked_item_at_once` |
| 接线 | `test_the_tool_route_revokes_an_arbitrary_agents_item` |

`revoke=True` 是这次裁定的那条路；不带它时 `Conductor.void_items` 仍是
2026-10-29 收窄之后的旧口径（叫不醒的 ack-only 通知才轮得到作废）——
那一档的行为由 `tests/test_the_silent_child_deadlock_has_a_way_out.py` 原样钉着，
本文件一个字都不动它。
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

from agentflow import conductor as C
from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry


# ---------------------------------------------------------------- 夹具


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor]:
    """M（根）→ D1（父）→ F1 / F2（兄弟）；F1 → G1（孙代）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, Conductor(st, policy=None, backend=LocalBackend({}))


def _agent(box: Conductor, *, role: str, parent: str | None, detail: str,
           status: str = "running") -> str:
    """一行代理实例（`kind` 空）——父子关系只由 `parent_task_id` 说话。"""
    ended = None if status in ("pending", "running") else "2026-11-06T08:00:00+08:00"
    return box._write_new_row({
        "role": role, "action": "run", "called_by": (parent and "M") or "user",
        "parent_task_id": parent, "depth": (1 if parent is None else 2),
        "input_key": f"test:{role}:{detail}", "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": detail, "error": None,
        "started_at": "2026-11-06T08:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note=f"test:agent:{role}")


def _item(box: Conductor, *, owner: str, role: str, expects: str,
          kind: str, summary: str) -> str:
    return box.open_item(kind=kind, role=role, expects=expects, action=kind,
                         summary=summary, called_by="test", parent_task_id=owner,
                         depth=2, input_key=f"test:{kind}:{owner}")


def _hierarchy(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Conductor,
                                                dict[str, str]]:
    """一棵足够判权限的树：M → D1 →（F1、F2），F1 → G1。"""
    ws, box = _workspace(tmp_path)
    ids = {
        "M": _agent(box, role="M", parent=None, detail="顶趟"),
        "D1": "",
        "F1": "",
        "F2": "",
        "G1": "",
    }
    ids["D1"] = _agent(box, role="D", parent=ids["M"], detail="D1")
    ids["F1"] = _agent(box, role="F", parent=ids["D1"], detail="F1")
    ids["F2"] = _agent(box, role="F", parent=ids["D1"], detail="F2")
    ids["G1"] = _agent(box, role="G", parent=ids["F1"], detail="G1")
    return ws, box, ids


def _row(box: Conductor, item_id: str) -> dict[str, Any]:
    return next(dict(r) for r in box._tasks()
                if str(r.get("task_id") or "") == str(item_id))


def _trace(got: Mapping[str, Any], item_id: str) -> dict[str, Any]:
    return next(dict(t) for t in (got.get("traces") or ())
                if str(t.get("item_id") or "") == str(item_id))


# ---------------------------------------------------------------- a —— 父撤直接子


def test_a_parent_revokes_a_direct_childs_item_with_a_trace(tmp_path: pathlib.Path) -> None:
    """a：D1 把 F1 名下"不再需要做"的两条项标撤销 —— 成功、终态、六格留痕。

    收件人此刻还在跑（不是静默、更不是叫不醒）：旧口径会拒（它自己会 ack），
    这一笔裁定把它按"改的人有权限"放开 —— 但理由必须逐字留下。
    """
    ws, box, ids = _hierarchy(tmp_path)
    queued = _item(box, owner=ids["F1"], role="F", expects="ack",
                   kind="notice", summary="到点通知：不再需要做")
    work = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="一件不再需要做的活")
    assert box.mark_item_seen(work, by_task_id=ids["F1"], step=3)[0] == "seen"

    got = box.void_items([queued, work], by_task_id=ids["D1"],
                         why="方向已砍：这两条不再需要做", revoke=True)
    assert got["checked"] is True, got
    assert got["voided"] == [queued, work], got
    assert not got["refused"], got

    for item_id, before in ((queued, "queued"), (work, "seen")):
        trace = _trace(got, item_id)
        assert trace["by"] == ids["D1"], trace
        assert trace["owner"] == ids["F1"], trace
        assert trace["reason"] == "方向已砍：这两条不再需要做", trace
        assert trace["from"] == before, trace
        assert trace["to"] == "done", trace
        assert str(trace["at"]).strip(), trace
        row = _row(box, item_id)
        assert str(row.get("item_state")) == "done", row
        assert str(row.get("item_close")) == "expired", (
            "撤销属于『作废』这一档收口（schema.ITEM_CLOSES 里唯一的撤销类），"
            "不许伪装成 acked / completed")
        mark = next((str(x) for x in (row.get("inputs") or ())
                     if str(x).startswith("revoke:expired:")), "")
        assert mark, row.get("inputs")
        assert f"by={ids['D1']}" in mark and f"owner={ids['F1']}" in mark, mark
        assert f"from={before}" in mark and "to=done" in mark, mark
        assert "at=" in mark and "reason=方向已砍" in mark, mark


# ---------------------------------------------------------------- b —— M 撤任意代理


def test_the_conductor_m_may_revoke_any_agents_item(tmp_path: pathlib.Path) -> None:
    """b：M 撤 G1（孙代，不是直接子）名下的项 —— 成功 + 留痕。

    同一棵树里 D1（G1 的祖父）撤同一条会被拒（用例 d），所以这一条证明的是
    "M 的权限面比父宽"，不是"随便一个上层都能撤"。
    """
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["G1"], role="G", expects="work",
                 kind="delegation", summary="孙代名下的一条活")
    got = box.void_items([item], by_task_id=ids["M"],
                         why="主控审计：全树不再需要这一条", revoke=True)
    assert got["checked"] is True and got["voided"] == [item], got
    trace = _trace(got, item)
    assert trace["by"] == ids["M"] and trace["owner"] == ids["G1"], trace
    assert trace["from"] == "queued" and trace["to"] == "done", trace
    assert str(trace["at"]).strip(), trace
    row = _row(box, item)
    assert str(row.get("item_state")) == "done"
    assert str(row.get("item_close")) == "expired"
    assert any(str(x).startswith("revoke:expired:")
               and f"by={ids['M']}" in str(x) for x in (row.get("inputs") or ())), row


# ---------------------------------------------------------------- c —— 子自己 ack


def test_a_child_still_acks_its_own_item(tmp_path: pathlib.Path) -> None:
    """c：既有行为不许坏 —— 收件人自己仍能把名下项 ack 成 done/acked。"""
    ws, box, ids = _hierarchy(tmp_path)
    mine = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="我自己读过了")
    got = box.ack_items([mine], by_task_id=ids["F1"], close="acked")
    assert got["state"] == "acked", got
    assert got["acked"] == [mine], got
    row = _row(box, mine)
    assert str(row.get("item_state")) == "done"
    assert str(row.get("item_close")) == "acked"


# ---------------------------------------------------------------- d —— 无权限仍拒


def test_a_sibling_or_a_grandparent_is_still_refused(tmp_path: pathlib.Path) -> None:
    """d：兄弟（F2）与祖父（D1 对 G1）改别人的项 ⇒ 仍受控拒绝，一个格都不动。"""
    ws, box, ids = _hierarchy(tmp_path)
    sibling_item = _item(box, owner=ids["F1"], role="F", expects="ack",
                         kind="notice", summary="F1 的通知")
    grandchild_item = _item(box, owner=ids["G1"], role="G", expects="work",
                            kind="delegation", summary="G1 的活")

    got = box.void_items([sibling_item], by_task_id=ids["F2"],
                         why="兄弟想替它撤", revoke=True)
    assert got["voided"] == [] and got["refused"], got
    refusal = got["refused"][0]
    assert str(refusal.get("code") or "") == "not_authorized", refusal
    assert "直接父代理" in str(refusal.get("why") or ""), refusal
    assert str(_row(box, sibling_item).get("item_state")) != "done"

    got2 = box.void_items([grandchild_item], by_task_id=ids["D1"],
                          why="祖父想替孙代撤", revoke=True)
    assert got2["voided"] == [] and got2["refused"], got2
    assert str(got2["refused"][0].get("code") or "") == "not_authorized", got2
    assert str(_row(box, grandchild_item).get("item_state")) != "done"


# ---------------------------------------------------------------- e —— 反真空


def test_the_authority_check_is_the_load_bearing_gate(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """e：把"有权限"那一条打桩成恒假 ⇒ a / b 当场红；打桩成恒真 ⇒ d 被放开。

    两向都做：只做"恒假"那一向，分不清"权限判据在起作用"与"整条路本来就不通"。
    """
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="一条通知")

    def _deny(self: Conductor, rows: Mapping[str, Mapping[str, Any]], *,
              by_task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        return {"checked": True, "allowed": False, "mode": "denied",
                "by": str(by_task_id), "owner": str(row.get("parent_task_id") or ""),
                "code": "not_authorized", "why": "打桩：恒无权限"}

    real = Conductor._item_authority
    monkeypatch.setattr(Conductor, "_item_authority", _deny)
    for actor in (ids["D1"], ids["M"]):
        got = box.void_items([item], by_task_id=actor,
                             why="打桩：应当被拒", revoke=True)
        assert got["voided"] == [], (actor, got)
        assert str(got["refused"][0].get("code") or "") == "not_authorized", got
        assert str(_row(box, item).get("item_state")) != "done"
    monkeypatch.setattr(Conductor, "_item_authority", real)

    def _allow(self: Conductor, rows: Mapping[str, Mapping[str, Any]], *,
               by_task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        return {"checked": True, "allowed": True, "mode": "stub",
                "by": str(by_task_id), "owner": str(row.get("parent_task_id") or ""),
                "code": "", "why": "打桩：恒有权限"}

    monkeypatch.setattr(Conductor, "_item_authority", _allow)
    got = box.void_items([item], by_task_id=ids["F2"],
                         why="打桩：无权限的人也被放开", revoke=True)
    assert got["voided"] == [item], got
    monkeypatch.setattr(Conductor, "_item_authority", real)


# ---------------------------------------------------------------- f —— 板面立刻反映


def test_the_board_readings_drop_the_revoked_item_at_once(tmp_path: pathlib.Path) -> None:
    """f：撤销之后，`open_items_*` / `board_view` / `tree` / patrol 口径立刻不再数它。"""
    from agentflow.tools import conductor_tools as CT

    ws, box, ids = _hierarchy(tmp_path)
    keep = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="还留着的一条")
    drop = _item(box, owner=ids["F1"], role="F", expects="work",
                 kind="delegation", summary="要撤掉的一条")
    before_open = [str(r.get("task_id")) for r in box.open_items_of(ids["F1"])]
    assert drop in before_open, before_open
    before_board = int(box.board_view(limit=100)["board_open_count"])
    before_patrol = int(CT._board_cell(box, ids["F1"])["child_open_count"])

    got = box.void_items([drop], by_task_id=ids["D1"],
                         why="这一条不做了", revoke=True)
    assert got["voided"] == [drop], got

    after_open = [str(r.get("task_id")) for r in box.open_items_of(ids["F1"])]
    assert drop not in after_open and keep in after_open, after_open
    assert int(box.board_view(limit=100)["board_open_count"]) == before_board - 1
    assert int(CT._board_cell(box, ids["F1"])["child_open_count"]) == before_patrol - 1
    node = next(n for n in box.tree() if str(n.get("task_id")) == ids["F1"])
    assert int(node.get("items") or 0) == len(after_open), node


# ---------------------------------------------------------------- 接线 —— 工具路


def test_the_tool_route_revokes_an_arbitrary_agents_item(tmp_path: pathlib.Path) -> None:
    """M 走审计面那件工具（`conductor.void_items`）撤孙代的项：成功且读数带留痕。

    这一条守的是"能力在真注册表里也拿得到"，不是只活在 `Conductor` 的方法里。
    """
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["G1"], role="G", expects="work",
                 kind="delegation", summary="孙代名下的活")
    reg = build_registry(store=box.store, conductor=box,
                         workspace_root=ws).registry
    reg.bound_role = "M"
    with calling_as(ids["M"]):
        res = reg.call("conductor.void_items", item_ids=[item],
                       why="主控审计：不再需要这一条")
    data = dict(res.data or {})
    assert data.get("state") == "voided", data
    assert data.get("voided") == [item], data
    reason = str(data.get("reason") or "")
    for needle in (f"by={ids['M']}", f"owner={ids['G1']}", "from=queued",
                   "to=done", "at=", "reason="):
        assert needle in reason, reason
    assert str(_row(box, item).get("item_state")) == "done"


# ---------------------------------------------------------------- 补充负控


def test_a_revoked_item_cannot_be_revoked_twice(tmp_path: pathlib.Path) -> None:
    """已经终态的项再撤 ⇒ 拒（幂等命中不是"再写一遍"）。"""
    ws, box, ids = _hierarchy(tmp_path)
    item = _item(box, owner=ids["F1"], role="F", expects="ack",
                 kind="notice", summary="撤一次")
    assert box.void_items([item], by_task_id=ids["D1"],
                          why="第一次", revoke=True)["voided"] == [item]
    again = box.void_items([item], by_task_id=ids["D1"],
                           why="第二次", revoke=True)
    assert again["voided"] == [] and again["refused"], again
    assert "终态" in str(again["refused"][0].get("why") or ""), again
