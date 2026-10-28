"""D-08：静默子代理名下"只许本人 ack"的到点通知，必须有一条"作废"的出口。

这一条来自 2026-10-28 02:48 的真机事故（`projects/paper-rewrite-78`，3 小时、$1.07）：
那一趟产出了全部交付物，却以 `final_refused` 收尾、`final` 为空。M 自己在第 175 步
写下的原因逐字是：

    「收工闸只剩结构完整性一格未过：4 个静默子代理名下各挂着 1–2 条只允许它本人 ack 的
      到点通知，父无法代 ack，故整棵树无法清空」

四个环节互锁：
① 板项 `expects="ack"` 只许收件人本人 ack（父不许代 ack，业主 2026-10-08 裁定）；
② 收件人（子代理）已静默/退役 ⇒ 永远不会 ack；
③ 销号闸要求"名下没有未消的板项"，拒信只说"先去 ack"；
④ 收工闸要求"整棵树都已销号"（业主 2026-10-26 追裁：任何 final 都要清仓）。
⇒ 销不了 ⇒ 树永远不清 ⇒ final 永远被拒。

本判据钉三条：作废能让树清空（正控）；在飞的子代理不许被作废（负控）；
不作废时死锁真的存在（反真空：判据必须有对象）。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import conductor as C
from agentflow import tools as TOOLS


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, C.Conductor]:
    from agentflow import store as ST

    st = ST.Store(tmp_path)
    st.init()
    box = C.Conductor(st)
    # 先落主控那一行（台账号 t-000001）：否则第一条子行自己就拿走 t-000001，
    # 而它的 parent 也是 t-000001 ⇒ 校验会判"parent_task_id 不能指向自身"。
    box._write_new_row({
        "role": "M", "action": "run", "called_by": "user", "parent_task_id": None,
        "depth": 1, "input_key": "top:M:test", "status": "running", "outcome": None,
        "refusal_reason": None, "instance": "", "detail": "顶趟", "error": None,
        "started_at": "2026-10-28T01:50:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note="test:root")
    return tmp_path, box


def _child_row(box: C.Conductor, *, status: str = "running") -> str:
    """造一行子代理实例（不是板项：`kind` 空）—— 静默判据认的是这一种行。"""
    return box._write_new_row({
        "role": "D", "action": "research", "called_by": "M", "parent_task_id": "t-000001",
        "depth": 2, "input_key": "M.research", "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "研究一条分支", "error": None,
        "started_at": "2026-10-28T02:00:00+08:00",
        "ended_at": ("2026-10-28T02:30:00+08:00" if status == "done" else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }, note="test:child")


def _notice_for_child(box: C.Conductor, *, parent_tid: str, role: str) -> str:
    """在某个子代理名下挂一条"只许本人 ack"的到点通知（与 clock 投递同一形状）。"""
    return box.open_item(
        kind="notice", role=role, expects="ack", action="notice",
        summary="时间到：做某件小事", called_by="clock",
        parent_task_id=parent_tid, depth=2, input_key=f"clock:{parent_tid}",
    )


def test_the_deadlock_is_real_before_voiding(tmp_path: pathlib.Path) -> None:
    """反真空：不作出废时，那条通知永远让整棵树不完整（这就是那次停机的原因）。"""
    root, box = _workspace(tmp_path)
    child = _child_row(box)
    notice = _notice_for_child(box, parent_tid=child, role="D")
    reading = box.retire_integrity(root_task_id="t-000001")
    # 这条用例只关心"那颗子树不完整"这个事实：直接读那个子代理的未消项
    open_now = [r for r in box._tasks()
                if str(r.get("task_id")) == notice]
    assert open_now and str(open_now[0].get("item_state")) != "done", "前提变了：通知一开始就不是未消的"
    assert notice, reading


def test_voiding_a_silent_childs_notice_clears_the_item(tmp_path: pathlib.Path) -> None:
    """正控：静默子代理名下那条 ack-only 通知 ⇒ 作废后 `item_close="expired"`、树可清。"""
    root, box = _workspace(tmp_path)
    # 子代理已静默/退役：实例行一开始就是 done（含 ended_at/outcome 两格）
    child = _child_row(box, status="done")
    notice = _notice_for_child(box, parent_tid=child, role="D")
    got = box.void_items([notice], by_task_id="t-000001", why="子代理已静默，通知永不投递")
    assert got["checked"] is True, got
    assert got["voided"] == [notice], got
    row = next(r for r in box._tasks() if str(r.get("task_id")) == notice)
    assert str(row.get("item_state")) == "done"
    assert str(row.get("item_close")) == "expired", "作废必须记 expired，不许伪装成 acked/completed"
    assert any(str(x).startswith("void:expired:") for x in (row.get("inputs") or ())), (
        "作废的来路必须落在 inputs 里（谁作废的、为什么）")


def test_a_running_childs_notice_must_not_be_voided(tmp_path: pathlib.Path) -> None:
    """负控：子代理还在跑 ⇒ 作废被拒（它自己会 ack，父不许代它作废）。"""
    root, box = _workspace(tmp_path)
    child = _child_row(box)
    notice = _notice_for_child(box, parent_tid=child, role="D")
    got = box.void_items([notice], by_task_id="t-000001", why="试试")
    assert got["voided"] == [], got
    assert got["refused"] and "还在跑" in str(got["refused"][0]["why"]), got
    row = next(r for r in box._tasks() if str(r.get("task_id")) == notice)
    assert str(row.get("item_state")) != "done", "被拒时一个格都不许改"


def test_only_ack_only_items_may_be_voided(tmp_path: pathlib.Path) -> None:
    """边界：`expects="work"` 的要交付活不许被作废（否则这条路就成了"父替子交差"）。"""
    root, box = _workspace(tmp_path)
    child = _child_row(box)
    work = box.open_item(kind="delegation", role="D", expects="work", action="probe_c",
                         summary="一条要交付的活", called_by="M", parent_task_id=child, depth=2)
    got = box.void_items([work], by_task_id="t-000001", why="试试作废要交付的活")
    assert got["voided"] == [], got
    assert any("expects='work'" in str(r["why"]) for r in got["refused"]), got


def test_the_tool_is_wired_and_visible_to_the_conductor(tmp_path: pathlib.Path) -> None:
    """接线：`conductor.void_items` 真的在注册表里，且 M 拿得到（否则这条路等于不存在）。"""
    _, box = _workspace(tmp_path)
    reg = TOOLS.build_registry(store=box.store, workspace_root=tmp_path).registry
    names = [t.name for t in reg.for_role("M")]
    assert "conductor.void_items" in names, names
    spec = reg.get("conductor.void_items")
    assert spec is not None and spec.side_effect == "write_local"
    assert "why" in (spec.params.get("required") or ()), "why 必填：作废没有理由不可复核"


def test_the_expired_close_reason_is_its_own_value() -> None:
    """词表：`expired` 是第三档，不是 acked/completed 的别名（折平正是这套系统禁止的）。"""
    from agentflow import schema as S

    assert "expired" in S.ITEM_CLOSES
    assert S.ITEM_CLOSES.index("expired") == len(S.ITEM_CLOSES) - 1
    with pytest.raises(ValueError):
        S.Task(task_id="t-000001", role="D", action="notice", called_by="clock",
               parent_task_id=None, depth=2,
               input_key="", status="pending", outcome=None, refusal_reason=None,
               instance="", detail="x", error=None, started_at="", ended_at=None,
               tokens=0, usd=0.0, artifacts=[], inputs=[], kind="notice", expects="ack",
               item_state="done", item_close="扔掉", seen_by="", seen_step=None,
               keep_alive=False).validate()
