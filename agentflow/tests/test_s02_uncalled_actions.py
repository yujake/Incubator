# -*- coding: utf-8 -*-
"""S-02 的判据（纯读数）：声明了、但一条召唤行都没有的动作。

裁定（主控）：S-02 加读数、不加闸门 —— "该不该派这个动作"归秘书
（`J-37`/`J-40`：切勿全写死成机器判据），机器只把"声明了但没人召唤过"这件事
变成看得见的事实（`44 S-02`：D 的五个核心动作在声明表里、各有 handler，
而真机 4127 行 `tasks` 里 0 次召唤；`Conductor.stats()` 只有 `by_role`/`by_status`
/`by_outcome`/`by_depth`，没有 `by_action` ⇒ 这件事今天没有任何读数在说）。
"""
from __future__ import annotations

import pathlib

from agentflow import capabilities as C
from agentflow.conductor import uncalled_actions_reading
from agentflow.store import Store


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _call(st: Store, role: str, action: str, i: int = 1) -> None:
    with st.tx("tasks", actor="test", note="s02") as tx:
        tx.upsert("tasks", {
            "task_id": f"t-{i:04d}", "role": role, "action": action, "called_by": "M",
            "parent_task_id": None, "depth": 2, "input_key": f"k{i}", "status": "done",
            "outcome": "ok", "refusal_reason": None, "instance": "",
            "detail": f"测试造的一条召唤行（{role}.{action}）",
            "error": None, "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00", "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="s02")


def test_s02_declared_but_never_called_actions_are_listed(tmp_path: pathlib.Path):
    """判据（改前红：`uncalled_actions_reading` 不存在 ⇒ AttributeError）：

    "声明了但零召唤行"的清单必须从声明表现算（分母是声明面，不是硬编码名单），
    且真机那五个 D 的核心动作在空工作区里必须在清单里。
    """
    got = uncalled_actions_reading(_store(tmp_path))
    assert got["checked"] is True, got
    declared = {(str(r), str(getattr(s, "action", "") or ""))
                for r, specs in dict(C.CAPABILITIES).items() for s in specs}
    declared.discard(("", ""))
    assert got["declared_total"] == len(declared) and got["declared_total"] > 0, got
    assert got["called_total"] == 0 and got["count"] == got["declared_total"], got
    pairs = {(x["role"], x["action"]) for x in got["uncalled"]}
    for pair in (("D", "assess"), ("D", "submit_gaps"), ("D", "adjudicate"),
                 ("D", "trace_question"), ("D", "trace_l3")):
        assert pair in pairs, pair
    assert "不构成任何门的通过条件" in got["note"], got["note"]


def test_s02_a_called_action_disappears_from_the_list(tmp_path: pathlib.Path):
    """反负控（防"清单恒列出全部"）：造一条召唤行 ⇒ 该动作必须从清单里消失。"""
    st = _store(tmp_path)
    before = {(x["role"], x["action"]) for x in uncalled_actions_reading(st)["uncalled"]}
    assert ("D", "assess") in before, "前置：空工作区里它本来在清单里"
    _call(st, "D", "assess")
    got = uncalled_actions_reading(st)
    after = {(x["role"], x["action"]) for x in got["uncalled"]}
    assert ("D", "assess") not in after, "被召唤过的动作还在清单里（读数恒真）"
    assert got["called_total"] == 1 and got["count"] == got["declared_total"] - 1, got
    # `refused` 也算"真的提出过"（台账上留着行）
    _call(st, "D", "trace_l3", i=2)
    assert ("D", "trace_l3") not in {(x["role"], x["action"])
                                     for x in uncalled_actions_reading(st)["uncalled"]}


def test_s02_the_reading_admits_when_it_could_not_be_taken(tmp_path: pathlib.Path):
    """三态：`tasks` 读不出来 ⇒ `checked=False` + 理由 —— 不许折成"全都没被调用"。"""
    class _Broken:
        def rows(self, table):
            raise OSError("表读不出来")

    got = uncalled_actions_reading(_Broken())
    assert got["checked"] is False and "读不出来" in got["reason"], got
    assert got["uncalled"] == [] and got["declared_total"] == 0, got


def test_s02_the_reading_carries_its_own_caliber(tmp_path: pathlib.Path):
    """口径必须印在读数里（2026-10-02 主控现场更正）。

    为什么这是一条判据而不是一句文档：这条读数数的是 `tasks` 台账的落盘行，
    而权威读数是 `sessions/*.jsonl` 的 `events` 重放。两个口径的数差得很远
    （实测某个工作区 `tasks.json` 2 行、同目录 `events.jsonl` 1161 行），
    于是"不带口径的数字"必然被拿去互相比 —— 那是错的用法。

    读成与没读成都必须带口径：三态里只有一格是干净的，但"这一格说的是什么"
    对三格都成立。
    """
    got = uncalled_actions_reading(_store(tmp_path))
    assert "caliber" in got, "读数没带口径 ⇒ 读的人只能猜它数的是什么"
    caliber = got["caliber"]
    assert "tasks" in caliber and "events" in caliber, caliber
    assert "重放" in caliber and "不许互相比" in caliber, caliber

    class _Broken:
        def rows(self, table):
            raise OSError("表读不出来")

    assert "caliber" in uncalled_actions_reading(_Broken()), "读不成的那一格也要带口径"
