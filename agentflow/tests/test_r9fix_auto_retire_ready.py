# -*- coding: utf-8 -*-
"""R9FIX · D5：收工前自动收尾（只销「静默且无未消项」的子树）。

## 现场（真机 lp-ball-9，10:00:59）

`final_refused`：名下 44/49 个节点还在册，`conductor.retire_child` 全程只调 2 次；
M 在 $1.00 保留线以内算过「44 个销号调用做不到」。产品没有批量销号，逐个 `retire_child`
在预算内不可行。

## 这一档为什么不动工具面

给 `conductor.retire_child` 加列表参数 / 新增批量工具都要动工具面（冻结快照重冻 +
抬版本），代价远大于这里要解决的问题。这一档把 M 在 `final` 那一步本可以逐个做的
动作一次做完 —— 判据一个字不放宽：只销静默、无未消项、无活跃子、无程序在跑的节点；
有未消项 / 在飞 / 待机 / 读不到的一律留给 M 按拒信逐条处置。

## 判据

1. 只销 `waiting_no_children` 且 `items_open == 0` 的节点；
2. 从最深的开始（父在子之后）；有未消项的子孙保留；
3. 反真空：没有秘书 / 子树读不成 ⇒ 一条都不销，返回 `checked=False` 或 problems。
"""
from __future__ import annotations

from agentflow import agent_loop as AL


class _FakeSecretary:
    def __init__(self) -> None:
        self.retired: list[str] = []
        self.done: set[str] = set()

    def name_of(self, *, owner: str, task_id: str) -> tuple[str, str]:
        return f"n-{task_id}", ""

    def retire(self, *, owner: str, name: str, by_task_id: str = "",
               reason: str = "") -> dict:
        if not name.startswith("n-"):
            return {"action": "refused", "why": ["没有名册名"]}
        tid = name[2:]
        self.retired.append(tid)
        self.done.add(tid)
        return {"action": "retired", "why": []}


class _FakeConductor:
    def __init__(self) -> None:
        self.secretary = _FakeSecretary()

    @property
    def done(self) -> set[str]:
        return self.secretary.done

    def subtree_postorder(self, root: str) -> dict:
        return {"checked": True,
                "order": ["t1", "t5", "t2", "t3", "t4"],
                "parent_of": {"t1": "", "t2": "t1", "t3": "t1",
                              "t4": "t1", "t5": "t4"},
                "reason": ""}

    def retire_ready(self, parent: str) -> dict:
        if parent == "t1":
            rows = [
                {"task_id": "t2", "branch": "waiting_no_children",
                 "reading": {"items_open": 0}},
                {"task_id": "t3", "branch": "waiting_no_children",
                 "reading": {"items_open": 2}},
                {"task_id": "t4",
                 "branch": ("waiting_no_children" if "t5" in self.done
                            else "waiting_with_children"),
                 "reading": {"items_open": 0}},
            ]
        elif parent == "t4":
            rows = [{"task_id": "t5", "branch": "waiting_no_children",
                     "reading": {"items_open": 0}}]
        else:
            rows = []
        return {"checked": True, "ready": [r for r in rows
                                           if r["task_id"] not in self.done],
                "reason": ""}


class _Run:
    def __init__(self) -> None:
        self.notes: list[str] = []


class _Loop:
    pass


def _auto(cond, run=None):
    return AL.AgentLoop._auto_retire_ready(_Loop(), cond, "t1", run)


def test_only_silent_children_without_open_items_are_retired():
    cond = _FakeConductor()
    run = _Run()
    got = _auto(cond, run)

    # t5（叶子）先销；t2（静默、无未消项）销；t4 在 t5 销掉之后才变可销。
    assert set(got["retired"]) == {"t2", "t4", "t5"}, got
    assert "t3" not in got["retired"], got          # 有 2 条未消项 ⇒ 留
    assert got["retired"].index("t5") < got["retired"].index("t4"), got
    assert cond.secretary.retired == got["retired"], cond.secretary.retired
    assert run.notes and "自动收尾" in run.notes[0], run.notes


def test_a_retired_parent_is_not_retired_before_its_child():
    """反真空（次序）：父在子之前被销 ⇒ 这一条必须红。"""
    cond = _FakeConductor()
    got = _auto(cond)
    assert got["retired"].index("t5") < got["retired"].index("t4"), got


def test_without_a_secretary_nothing_is_retired():
    cond = _FakeConductor()
    cond.secretary = None
    got = _auto(cond)
    assert got["checked"] is False and got["retired"] == [], got
    assert got["problems"], got


def test_an_unreadable_subtree_retires_nothing():
    cond = _FakeConductor()
    cond.subtree_postorder = lambda root: {"checked": False, "order": [],
                                           "reason": "台账读不成"}
    got = _auto(cond)
    assert got["checked"] is False and got["retired"] == [], got
    assert "台账读不成" in "；".join(got["problems"]), got
