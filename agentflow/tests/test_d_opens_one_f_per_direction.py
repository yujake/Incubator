# -*- coding: utf-8 -*-
"""R1 的读数：D 派了几个 F、各自方向（业主 2026-11-13 裁定 Q1）。

业主原话（逐字）：

> 「plan由F自己决定，所以D不可能做出按plan个数派F，于是D只能按研究方向开多个F而非把一堆
>   方向委托给一个F（……我们就做提示词侧和流程侧的工作，不再用一个比如说研究方向列表来
>   一对一绑定）。」

## 读数从哪来（Q1 的口径，逐条对上）

- 计数：名册（`out/roster/D.jsonl` 折叠后，未退役的 `role=F`）＋ `tasks`（`role=F`、
  `called_by=D`）现算 —— 不新开读数键；
- 方向：D 派活那一刻写下的原文（`dispatchpolicy.d_dispatch_records` 的
  `agent_step.payload.task`）。名册的 `task_text` 只是同一段原文的副本（按
  `TASK_TEXT_MAX` 截断），`roster.brief` 只作"同向性"对拍（≤60 字可能被压短）。
- 不用 `attack_plans.problem_key`：派了方向但还没立计划的 F 会漏掉（R1 的口径是
  "D 按方向开 F、plan 由 F 自己决定"）。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 两个 F ⇒ `count=2`，每个 `direction` 逐字是派活原文（`direction_source=dispatch`），brief 与方向对得上 | 改前没有这个读数（`dispatch_directions` 不存在） |
| b | 有派活原文却对不上在册 F ⇒ 记 `unmatched`，不许静默丢 | 同上 |
| c | 反真空：名册读口打桩成空 ⇒ `checked=False`（"没读成"不是"0 个 F"） | 同上 |
| d | 方向不取 `attack_plans.problem_key`：盘上有一条计划却没有任何派活原文 ⇒ 它不算方向 | 同上 |
| e | 空工作区（真没派过 F）⇒ `checked=True` + `count=0`（与 c 的三态分开） | 同上 |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import dispatchpolicy as DP
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import sessions as SS
from agentflow.store import Store

PARENT = "t-000001"
F1, F2 = "t-000002", "t-000003"
DIR1 = "方向一：把这一族在 n≤20 的界算出来；可以试母函数与 Fourier 两条路"
DIR2 = "方向二：把同构类的数目数出来，先枚举小参数"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _task(store: Store, task_id: str, *, role: str = "F",
          parent: str | None = PARENT, depth: int = 2) -> None:
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": task_id, "role": role, "action": "",
            "called_by": "D", "parent_task_id": parent, "depth": depth,
            "input_key": f"k-{task_id}", "status": "running", "outcome": None,
            "started_at": S.now_iso(), "ended_at": None, "detail": "跑着",
        })


def _dispatch(store: Store, *, task: str, index: int) -> None:
    SS.append(store.root, {
        "kind": "agent_step", "role": "D", "index": index, "shape": "summon",
        "payload": {"role": "F", "action": "", "task": task,
                    "params": {}, "why": "派方向"},
    }, sid="t-r1")


def _world(path: pathlib.Path) -> Store:
    store = _ws(path)
    _task(store, PARENT, role="D", parent=None, depth=1)
    _task(store, F1)
    _task(store, F2)
    sec = SEC.Secretary("D", root=store.root, store=store)
    a = sec.roster_add(owner=PARENT, role="F", task_id=F1,
                       brief="攻方向一：界", task=DIR1)
    b = sec.roster_add(owner=PARENT, role="F", task_id=F2,
                       brief="攻方向二：同构类", task=DIR2)
    assert a.get("name") and b.get("name"), (a, b)
    _dispatch(store, task=DIR1, index=0)
    _dispatch(store, task=DIR2, index=1)
    return store


# ============================================================ a：计数与方向
def test_a_two_fs_and_their_directions_are_read_from_existing_data(
        tmp_path: pathlib.Path) -> None:
    """a 判据：两个 F ⇒ count=2；方向逐字是派活原文；brief 与方向对得上。

    改前红：改前没有 `dispatch_directions` 这个读数（这条会以 AttributeError 失败），
    "派了几个 F、各自方向"只能靠人去翻名册与会话记录。
    """
    store = _world(tmp_path)
    got = DP.dispatch_directions(store.root)
    assert got.get("checked") is True, got
    assert got.get("count") == 2, got
    assert got.get("roster_f") == 2 and got.get("tasks_f") == 2, got
    by_name = {e["name"]: e for e in got["fs"]}
    assert len(by_name) == 2, by_name
    dirs = sorted(got["directions"])
    assert dirs == sorted([DIR1, DIR2]), dirs
    for entry in by_name.values():
        assert entry["direction"] in (DIR1, DIR2), entry
        # 方向的正本是派活原文（不是 brief、也不是 problem_key）
        assert entry["direction_source"] == "dispatch", entry
        assert entry["dispatch_task"] == entry["direction"], entry
        # 名册副本与原文同一段（截断不算矛盾）
        assert entry["direction_agrees"] is True, entry
        # brief 与方向"不矛盾"（机械读数：至少共享一个两字片段）
        assert entry["brief_overlap"] is not None and entry["brief_overlap"] > 0, entry


# ============================================================ b：对不上的派活
def test_b_a_dispatch_that_matches_no_roster_f_is_counted_not_dropped(
        tmp_path: pathlib.Path) -> None:
    """b 判据：有派活原文、对不上在册 F ⇒ `unmatched=1`（不许静默丢）。

    改前红：同 a。这条防的是"数出来的 F 少了一个而没人知道"。
    """
    store = _world(tmp_path)
    _dispatch(store, task="方向三：这条没有对应的在册 F", index=2)
    got = DP.dispatch_directions(store.root)
    assert got["checked"] is True, got
    assert got["count"] == 2, got
    assert got["unmatched"] == 1, got
    assert "对不上" in str(got.get("reason") or ""), got


# ============================================================ c：反真空
def test_c_an_unreadable_roster_is_unchecked_not_zero_fs(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 判据（反真空）：名册读口打桩成空 ⇒ `checked=False`（不是 `count=0`）。

    证明 a 的绿来自"名册真的读到了两个 F"，而不是"数了个 0 也算读成"。
    """
    store = _world(tmp_path)
    monkeypatch.setattr(DP, "_d_roster", lambda root, owners: ([], []))
    got = DP.dispatch_directions(store.root)
    assert got["checked"] is False, got
    assert "对不上" in str(got.get("reason") or ""), got
    # 名册读口直接抛：同样是"没读成"，不是 0 个 F
    def boom(root, owners):
        raise OSError("名册盘不在")

    monkeypatch.setattr(DP, "_d_roster", boom)
    got2 = DP.dispatch_directions(store.root)
    assert got2["checked"] is False and "名册读不出来" in got2["reason"], got2


# ============================================================ d：不取 problem_key
def test_d_a_plan_key_is_not_read_as_a_direction(tmp_path: pathlib.Path) -> None:
    """d 判据：盘上有一条计划（`problem_key=方向三`）但没有任何派活原文 ⇒ 它不算方向。

    改前红：同 a。这条钉住 Q1 的"不用 `attack_plans.problem_key`"——那一格是 F 落成
    计划之后的产物，派了方向还没立计划的 F 会漏掉。
    """
    store = _world(tmp_path)
    with store.tx("attack_plans", actor="agent-F") as tx:
        tx.upsert("attack_plans", {
            "plan_id": tx.alloc_id("plan"), "problem": "F 自己立的",
            "problem_key": "方向三：只有计划没有派活", "status": "open", "rounds": 0,
            "budget": {"max_rounds": 3, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 2},
            "subgoals": [], "history": [], "depth": 0, "created_by": "agent-F",
        })
    got = DP.dispatch_directions(store.root)
    assert got["checked"] is True, got
    assert "方向三：只有计划没有派活" not in " ".join(got["directions"]), got


# ============================================================ e：真 0 个 F
def test_e_a_workspace_with_no_f_dispatch_is_a_checked_zero(tmp_path: pathlib.Path) -> None:
    """e 判据（正控）：真没派过 F ⇒ `checked=True` + `count=0`（与 c 的"没读成"分开）。"""
    store = _ws(tmp_path)
    got = DP.dispatch_directions(store.root)
    assert got.get("checked") is True, got
    assert got.get("count") == 0 and got.get("directions") == [], got


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
