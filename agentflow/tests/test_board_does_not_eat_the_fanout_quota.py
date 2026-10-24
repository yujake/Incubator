# -*- coding: utf-8 -*-
"""S1e：板项不许吃扇出名额 / 两轴分开 / `dispose` 不碰板项（业主 T22 的"两轴分开"）。

`_in_flight_children_of` 旧口径只按 `parent_task_id` + `status ∈ {pending, running}` 数行，而板项行
（`open_item` 建的行，`kind` 非空）恰好 `status="pending"`，且板的状态机（`_set_item`）只改
`item_state`、从不改 `status` ⇒ 一条已 ack 的板项永远是在飞的子代理。

实测（`temp/_probe_board_vs_fanout_and_dispose.py` 与 `..._refusal_reason.py`，不是推测）：父名下挂
20 条"子代理已收工"的 `notice`（零代理）⇒ 该读数 = 20 ⇒ 同一父下派活被拒 `fanout_exceeded`，detail
逐字「此刻在飞 20 个子代理，达到发起方 M 的同时在飞上限 20」；负控（不挂板项）同一个调用走到执行
（`not_wired`）⇒ T1 会在累积约 20 次交差之后卡住。

本文件钉住四件事：
1. 正控：板项不再占名额 —— 20 条 `notice` 之下，同一个派活不被 `fanout_exceeded` 拒；
2. 负控（反真空）：真子代理行照旧占名额（这一批不许把分子改成"永远 0"）；
3. 边界（两轴分开）：`kind="delegation"` 的派活项不算在飞代理，但 `open_items_of(父)`
   （工作项轴，纯读数）数得到它；
4. `dispose` 不碰板项：dispose 之后板项行逐字不变 + 读数里有 `board_items_left`。

夹具都用真 `Conductor` + 真盘（`tmp_path`），不手写 dict 落盘。"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import policy as P
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.fanout_wait_sec = 0.0          # 不等：直接看拒绝读数（等是另一条判据的事）
    return st, cond


def _notices(cond: Conductor, owner: str, n: int) -> list[str]:
    """开 `n` 条挂在 `owner` 名下的 `notice`（形态与 `_emit_settlement` 落的一模一样）。"""
    return [cond.open_item(kind="notice", role="A", expects="ack",
                           summary=f"{i} 号子代理已收工", called_by="A",
                           parent_task_id=owner, depth=2, input_key=f"notice@A:{i}")
            for i in range(n)]


def test_board_items_do_not_eat_the_fanout_quota(tmp_path: pathlib.Path):
    """正控：父名下 20 条板项（零代理）之下，同一个派活不许被 `fanout_exceeded` 拒。

    改前必红（实测）：同一条调用在旧口径下被判"此刻在飞 20 个子代理" ⇒
    `done / refused / fanout_exceeded`。
    改后：读数 0 ⇒ 走到执行那一层（`not_wired`，因为夹具没给 A 接线）。
    """
    _st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    limit = P.direct_children_limit_for(P.Policy(), "M")
    _notices(cond, owner, limit)
    assert len(cond._in_flight_children_of(owner)) == 0, (
        "板项不是代理：20 条 notice 之后，代理轴读数必须是 0",
        cond._in_flight_children_of(owner))

    res = cond.summon("A", "run_once", {}, by="M", parent_task_id=owner, input_key="s1e@1")
    assert res.refusal_reason != "fanout_exceeded", (
        "板项吃掉了名额（旧口径的形态）", res.to_dict())
    assert str(res.detail).strip(), res.to_dict()      # 它走到了执行/拒绝那一层，有话说


def test_a_real_child_still_occupies_a_slot(tmp_path: pathlib.Path):
    """负控（反真空）：真代理行照旧占名额 —— 这一批不许把分子改成"永远 0"。

    做法：直接把代理轴读数与一条 running 代理行对上（不跑整个子循环）：
    写一行 `kind=""`、`status="running"`、挂在 owner 名下 ⇒ 分子 = 1。
    """
    _st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    kid = cond._write_new_row({
        "task_id": "", "role": "A", "action": "run_once", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "s1e@child", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "真子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")
    assert cond._in_flight_children_of(owner) == [kid], (
        "真子代理必须占名额（否则扇出上限形同虚设）", cond._in_flight_children_of(owner))
    # 它返回 ⇒ 名额还回去（既有语义，别被这一批改坏）
    cond.finish(kid, status="done", outcome="ok", detail="跑完了")
    assert cond._in_flight_children_of(owner) == [], cond._in_flight_children_of(owner)


def test_a_delegation_item_is_work_not_an_agent(tmp_path: pathlib.Path):
    """边界（两轴分开）：派活项归工作项轴，代理轴数不到它。

    这条同时是"两轴各有各的读数"的最小证据：同一条行，
    `_in_flight_children_of`（代理轴）看不到、`open_items_of`（工作项轴）看得到。
    """
    _st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    item = cond.open_item(kind="delegation", role="A", expects="work", action="run_once",
                          summary="派给 A 的活", called_by="M", parent_task_id=owner,
                          depth=2, input_key="s1e@work")
    assert cond._in_flight_children_of(owner) == [], (
        "工作项不是代理（两轴分开）", cond._in_flight_children_of(owner))
    assert item in {str(r["task_id"]) for r in cond.open_items_of(owner)}, (
        "工作项轴必须看得到它", cond.open_items_of(owner))


def test_dispose_leaves_board_items_alone(tmp_path: pathlib.Path):
    """正控（`dispose` 不碰板项）：dispose 前后那一行逐字不变，且读数里报"还剩几条"。

    改前必红（实测）：`dispose` 会把板项写成
    `status=cancelled / outcome=cancelled / item_state=queued`（两套状态机互相污染），
    而板面只读 `item_state` ⇒ 读的人看不见它被取消。
    """
    st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    item = cond.open_item(kind="notice", role="A", expects="ack", summary="子代理已收工",
                          called_by="A", parent_task_id=owner, depth=2, input_key="s1e@n1")

    def _row() -> dict[str, Any]:
        return next(r for r in st.rows("tasks") if str(r.get("task_id")) == item)

    before = dict(_row())
    out = cond.dispose()
    after = dict(_row())
    assert out["board_items_left"] == 1, out          # 读数：还剩一条没消
    assert after == before, {
        "dispose 不许改板项行（两套状态机不许在同一行上打架）":
            {k: (before.get(k), after.get(k)) for k in set(before) | set(after)
             if before.get(k) != after.get(k)}}


def test_dispose_still_closes_real_agent_rows(tmp_path: pathlib.Path):
    """负控（反真空）：`dispose` 仍然要收掉代理行（不许因为"不碰板项"漏了僵尸行）。"""
    st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    kid = cond._write_new_row({
        "task_id": "", "role": "A", "action": "run_once", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "s1e@zombie", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "真子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:A.run_once")
    out = cond.dispose()
    row = next(r for r in st.rows("tasks") if str(r.get("task_id")) == kid)
    assert kid in out["closed"], out
    assert row["status"] == "cancelled" and row["outcome"] == "cancelled", row
    assert "结果未知" in str(row["detail"]), row


def test_the_two_axes_have_two_names_not_one(tmp_path: pathlib.Path):
    """反真空（命名）：代理轴与工作项轴是两个不同名字的读数。

    为什么单列一条：这一批之前叫 `in_flight_items`，名字带 `in_flight` 会被读成
    "在飞的代理"（而它数的是工作项）—— 名实不符时下一个读代码的人（包括作者）
    就会按名字去用。这里把"改名之后两轴都在、且都读得到"钉住。
    """
    _st, cond = _cond(tmp_path)
    owner = cond.open_top_level_run("M", "顶层的活")
    cond.open_item(kind="notice", role="A", expects="ack", summary="x", called_by="A",
                   parent_task_id=owner, depth=2, input_key="s1e@n2")
    assert hasattr(cond, "open_items_of") and not hasattr(cond, "in_flight_items"), (
        "旧名字应当退场（它数的是工作项，名字却在说代理）")
    assert json.dumps(cond.board_readings(), ensure_ascii=False)      # 读数仍然可读
