# -*- coding: utf-8 -*-
"""D12：`tasks` 台账的通用写口不许伪造"谁开的项 / 已收口 / 已读过"。

## 这一份钉住的是权限面，不是参数校验

`store.direct_write_refusal` 只拒 `statements` 与 `lit_candidates`（`store.py:251`），
`tasks` 不在其中 —— 于是 `table.create(table="tasks")` 对任何角色都是敞开的。
改前实测（`agentflow/temp/_d12_probe_write_width.py`，一个 D 角色，四档全部 ok=True）：
```
[1_给自己一条 work]   id=t-000004
[2_种到别人名下]      id=t-000005      ← 把一条 delegation 种进 E 的板，called_by 写成自己
[3_直接写成 done]     id=t-000006      ← 绕过状态机伪造一条"已收口"
[4_写成 seen]         id=t-000007
```
伪造的板项会让销号门的"板项没清"读数失真，也会让 `Conductor._set_item` 的两条
不变量（只许往后走 / 没 seen 不许 done）整个失效 —— 而盘上那一行看起来完全合法。

判据落在 `tools/table_tools.py::_tasks_write_refusal`（`table.create` 与 `table.update`
各调一次，同一组理由码）：

| 判据 | 守的是 | 理由码 |
|---|---|---|
| a) `test_a_the_owner_can_post_a_work_item_to_itself` | 正控：自己给自己落一条 work 项仍然可以（别把正路一起关掉） | 无（放行） |
| b) `test_b_posting_on_somebody_elses_board_is_refused` | 板项的收件人只能是调用者自己 | `tasks_are_posted_by_their_owner` |
| c) `test_c_forging_a_closed_item_is_refused` | 新行 / 补丁不许写 `item_close` 与 `item_state != queued` | `tasks_close_only_through_the_item_state_machine` |
| d) `test_d_forging_a_seen_item_is_refused` | 不许绕过投递写"已读" | `tasks_seen_only_through_delivery` |
| e) `test_e_the_update_door_is_the_same_door` | `table.update` 是同一形状的第二个口子 | 同上三条 |
| f) `test_f_the_gate_is_a_permission_surface_not_a_param_check` | 反真空：三条理由码都在模块里，且正路（`conductor.post_task` + `conductor.ack`）仍然能到 done | 无 |

## 为什么没有调用上下文也拒（fail-closed）

`_caller_task_id()` 空串 = 脚本 / 单测里没挂 `calling_as`。"不知道是谁"不能读成
"谁都可以"—— 任务台账是全树结构完整性的唯一台账。
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import table_tools as TT

TS = "2026-01-01T00:00:00+00:00"

POSTED = TT.TASKS_POSTED_BY_THEIR_OWNER
CLOSED = TT.TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE
SEEN = TT.TASKS_SEEN_ONLY_THROUGH_DELIVERY


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "D12：写口判据"))
    return {"root": root, "store": st, "cond": cond, "owner": owner,
            "reg": build_registry(store=st, conductor=cond, workspace_root=str(root)).registry}


def _agent(cond: Conductor, parent: str, *, role: str) -> str:
    return cond._write_new_row({
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"d12w:{role}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "子代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:agent")


def _row(to: str, *, role: str = "D", **over: Any) -> dict:
    """一条形状合法、语义非法的 `tasks` 行（改前它会被原样收下）。"""
    base: dict[str, Any] = {
        "role": role, "action": "post_task", "called_by": role,
        "parent_task_id": to, "depth": 3, "input_key": "forged@1",
        "status": "pending", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "伪造的板项", "error": None, "started_at": "",
        "ended_at": None, "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "delegation", "expects": "work", "item_state": "queued",
        "item_close": "", "seen_by": "", "seen_step": None, "keep_alive": False,
    }
    base.update(over)
    return base


def _call(env: dict[str, Any], *, as_task: str, role: str = "D",
          name: str = "table.create", args: dict | None = None) -> Any:
    with calling_as(as_task, role):
        return env["reg"].call(name, dict(args or {}), role=role)


def _codes(res: Any) -> str:
    return f"{getattr(res, 'meta', {}).get('kind') or ''} {getattr(res, 'error', '') or ''}"


def _items(cond: Conductor, to: str) -> set[str]:
    return {str(r["task_id"]) for r in cond.open_items_of(to)}


# ====================================================================== a) 正控
def test_a_the_owner_can_post_a_work_item_to_itself(tmp_path: pathlib.Path) -> None:
    """a) 正控：给自己落一条 work 项仍然可以（这条闸不许把正路一起关掉）。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    res = _call(env, as_task=me, args={"table": "tasks", "row": _row(me)})
    assert res.ok is True, (res.error, res.meta)
    assert str(res.data) in _items(env["cond"], me)


# ====================================================================== b) 别人名下
def test_b_posting_on_somebody_elses_board_is_refused(tmp_path: pathlib.Path) -> None:
    """b) 负控：把板项种到别人板上 ⇒ 受控拒绝（改前 red：实测 id=t-000005 落成了）。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    other = _agent(env["cond"], str(env["owner"]), role="E")
    res = _call(env, as_task=me, args={"table": "tasks",
                                       "row": _row(other, role="E")})
    assert res.ok is False and POSTED in _codes(res), (res.error, res.meta)
    assert _items(env["cond"], other) == set(), (
        "拒了却仍然在别人板上留下了一条项（零写入被破坏）", _items(env["cond"], other))
    # `called_by` 写成别人也拒（那是"谁开的项"这一格）
    forged = _row(me, called_by="E")
    res2 = _call(env, as_task=me, args={"table": "tasks", "row": forged})
    assert res2.ok is False and POSTED in _codes(res2), (res2.error, res2.meta)


# ====================================================================== c) 伪造收口
def test_c_forging_a_closed_item_is_refused(tmp_path: pathlib.Path) -> None:
    """c) 负控：直接写 done / item_close ⇒ 受控拒绝（改前 red：实测 id=t-000006）。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    for over in ({"item_state": "done", "item_close": "completed"},
                 {"item_close": "acked"},
                 {"item_state": "claimed"}):
        res = _call(env, as_task=me, args={"table": "tasks", "row": _row(me, **over)})
        assert res.ok is False and CLOSED in _codes(res), (over, res.error, res.meta)
    assert _items(env["cond"], me) == set(), "拒了却仍然落了一条行"


# ====================================================================== d) 伪造已读
def test_d_forging_a_seen_item_is_refused(tmp_path: pathlib.Path) -> None:
    """d) 负控：绕过投递写 seen / seen_by ⇒ 受控拒绝（改前 red：实测 id=t-000007）。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    for over in ({"item_state": "seen", "seen_by": me, "seen_step": 1},
                 {"seen_by": me, "seen_step": 1}):
        res = _call(env, as_task=me, args={"table": "tasks", "row": _row(me, **over)})
        assert res.ok is False and SEEN in _codes(res), (over, res.error, res.meta)
    assert _items(env["cond"], me) == set()


# ====================================================================== e) update 同一扇门
def test_e_the_update_door_is_the_same_door(tmp_path: pathlib.Path) -> None:
    """e) 负控：`table.update` 能把一行直接改成 done —— 同一形状的第二个口子。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    item = env["cond"].open_item(kind="delegation", role="D", expects="work",
                                summary="一条真的活", called_by="D",
                                parent_task_id=me, depth=3, input_key="real@1")
    for patch, code in (({"item_state": "done", "item_close": "completed"}, CLOSED),
                        ({"item_state": "seen", "seen_by": me, "seen_step": 2}, SEEN)):
        res = _call(env, as_task=me, name="table.update",
                    args={"table": "tasks", "id": item, "patch": patch})
        assert res.ok is False and code in _codes(res), (patch, res.error, res.meta)
    row = next(r for r in env["store"].rows("tasks") if str(r.get("task_id")) == item)
    assert (str(row.get("item_state")), str(row.get("item_close"))) == ("queued", ""), row


# ====================================================================== f) 反真空
def test_f_the_gate_is_a_permission_surface_not_a_param_check(
        tmp_path: pathlib.Path) -> None:
    """f) 反真空 + 正路连通：三条理由码都在模块里，且正路（post_task + ack）仍然到 done。"""
    assert POSTED and CLOSED and SEEN
    assert len({POSTED, CLOSED, SEEN}) == 3
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    with calling_as(me, "D"):
        posted = env["reg"].call("conductor.post_task",
                                 {"summary": "把第 2 步补上"}, role="D")
        assert posted.ok is True, (posted.error, posted.meta)
        item = str(posted.data["item_id"])
        assert env["cond"].mark_item_seen(item, by_task_id=me, step=1)[0] == "seen", (
            "work 项读了不许被代 ack（它的 expects 是 work，收口要 completed）")
        acked = env["reg"].call("conductor.ack",
                                {"item_ids": [item], "close": "completed"}, role="D")
        assert acked.ok is True and acked.data["state"] == "acked", acked.data
    row = next(r for r in env["store"].rows("tasks") if str(r.get("task_id")) == item)
    assert (str(row.get("item_state")), str(row.get("item_close"))) == ("done", "completed"), row


def test_f2_without_a_caller_context_the_gate_is_closed(tmp_path: pathlib.Path) -> None:
    """f 的附条（fail-closed）：没有台账号 ⇒ 拒（"不知道是谁"不是"谁都可以"）。"""
    env = _env(tmp_path)
    owner = str(env["owner"])
    res = env["reg"].call("table.create", {"table": "tasks", "row": _row(owner)}, role="D")
    assert res.ok is False and POSTED in _codes(res), (res.error, res.meta)


def test_f3_the_gate_does_not_touch_other_tables(tmp_path: pathlib.Path) -> None:
    """f 的负控：别的表照旧（这条判据只对 `tasks` 说话）。"""
    env = _env(tmp_path)
    me = _agent(env["cond"], str(env["owner"]), role="D")
    res = _call(env, as_task=me, args={
        "table": "conjectures",
        "row": {"statement": "对一切 m，谱落在区间 [-m, m] 内。", "form": "universal",
                "testable": {"params": {"m": [2, 3]}, "why": "逐 m 数值可判"},
                "origin": "report:0001", "status": "proposed"}})
    assert res.ok is True, (res.error, res.meta)
