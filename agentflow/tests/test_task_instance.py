# -*- coding: utf-8 -*-
"""`tasks.instance`：多实例归因（`draft/37` §16 P1 的第三行 / R17 的前一半）。

## 为什么这一栏必须落到台账上

在它之前，`instance` 只活在日志行与后端调用的参数里：
`conductor.summon(..., instance="w1")` 会把标签写进日志，`LocalBackend.resolve`
也按 `(角色, 实例)` 建对象 —— 但台账里那一行没有这一栏。于是：
一轮里 N 个并行实例各自做了什么，在读台上无法归因；同角色同动作的多行长得一模一样。

`conductor.py` 里早有一段注释承认了这个缺口的症状（"并发多实例时『按角色找那条
running 行』会同时找到 N 条"），当时的补丁是把 `task_id` 传下去 —— 那是绕过去，
这一栏才是把事实记下来。

判据三面：记下来了（正控）/ 没标签时不许编一个（负控）/ 重建后台账逐字节不变
（I-9：往行字典里加键最容易踩的就是键序，而键序错了 `rebuild()` 会让
`tasks.json` 逐字节不同，本仓有一条判据盯着它）。
"""

from __future__ import annotations

import json
import types

from agentflow import capabilities as CAP
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


def _fake(role: str, action: str, outcome: str = "ok"):
    """造一个只实现该动作 handler 的替身（handler 名从声明表读，不写死）。"""
    spec = CAP.find_action(role, action)
    assert spec is not None, f"{role}.{action} 不在声明表里"

    def handler(**kw):
        """替身的 handler：回答一个最小合法载荷（带 `**kw` 以免被参数闸门拦下）。"""
        return {"outcome": outcome, "detail": f"{role}.{action}", "checked": True}

    obj = types.SimpleNamespace()
    setattr(obj, spec.handler_name, handler)
    return obj


def _world(tmp_path):
    st = Store(tmp_path / "ws")
    st.init()
    backend = LocalBackend({"C": ("object", _fake("C", "hottest"))})
    cond = Conductor(st, policy=None, backend=backend)
    return st, cond


def _rows(st: Store) -> list[dict]:
    return sorted(st.rows("tasks"), key=lambda r: str(r.get("task_id")))


def test_a_summon_records_its_instance_label(tmp_path):
    """正控：带标签的召唤，台账那一行必须有这个标签。"""
    st, cond = _world(tmp_path)
    res = cond.summon("C", "hottest", {"top_n": 1}, by="M", instance="w1")
    assert res.outcome == "ok", (res.status, res.outcome, res.error)
    rows = _rows(st)
    assert len(rows) == 1, rows
    assert rows[0]["instance"] == "w1", rows[0]
    # 逐行读回来也必须带着它（`row_from_dict` 那一处触点）
    from agentflow import schema as S

    assert S.row_from_dict("tasks", rows[0]).instance == "w1"


def test_the_default_instance_is_the_empty_label(tmp_path):
    """负控：不给标签时记空串，不许编一个（"单例"与"某个实例"是两回事）。"""
    st, cond = _world(tmp_path)
    cond.summon("C", "hottest", {"top_n": 1}, by="M")
    assert _rows(st)[0]["instance"] == "", _rows(st)[0]


def test_two_instances_of_one_role_are_distinguishable_in_the_ledger(tmp_path):
    """R17 的前一半：同一轮里 N 个实例的任务行，`instance` 各不相同。

    没有这一栏时，这两行在台账上完全同形（同角色、同动作、同 result），
    于是"哪个实例做的"只能靠读日志猜 —— 那正是这一轮要消掉的形态。
    """
    st, cond = _world(tmp_path)
    for label in ("w1", "w2", "w3"):
        cond.summon("C", "hottest", {"top_n": 1}, by="M", instance=label)
    rows = _rows(st)
    labels = [r["instance"] for r in rows]
    assert labels == ["w1", "w2", "w3"], labels
    assert len(set(labels)) == 3, "三个实例的台账行必须可区分"


def test_a_refused_summon_still_records_its_instance(tmp_path):
    """拒绝也是台账行，所以它同样要带标签（否则"谁被拒了"在并发下不可归因）。"""
    st, cond = _world(tmp_path)
    res = cond.summon("M", "x", {}, by="M", instance="w9")   # M 不可被召唤 ⇒ refused
    assert res.outcome == "refused" and res.status == "done", (res.status, res.outcome)
    row = _rows(st)[0]
    assert row["instance"] == "w9", row
    assert row["outcome"] == "refused" and row["refusal_reason"], row


def test_rebuild_keeps_tasks_json_byte_identical_with_instance(tmp_path):
    """I-9：加了这一栏之后，`rebuild()` 重建出的 `tasks.json` 必须逐字节不变。

    这一条盯的是键序：行字典的键顺序必须与 `Task` 的字段顺序一致
    （`conductor.py` 在 `task_id` 那里已经为此留过一条注记）。键序不齐时
    `rebuild()` 会用 dataclass 顺序重写，于是同一份事实两种字节 ——
    而 I-9 的判据会红，红得是对的。
    """
    st, cond = _world(tmp_path)
    cond.summon("C", "hottest", {"top_n": 1}, by="M", instance="w1")
    cond.summon("M", "x", {}, by="M", instance="w2")        # 一条 refused 行
    path = st.data / "tasks.json"
    before = path.read_bytes()
    assert json.loads(before.decode("utf-8"))["rows"], "台账里必须有行，否则这条判据是真空的"
    st.rebuild(backup=False)
    assert path.read_bytes() == before, (
        "rebuild 后 tasks.json 逐字节不一致（多半是行字典的键序与 Task 字段顺序分家了）")
