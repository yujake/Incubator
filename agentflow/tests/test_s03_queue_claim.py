# -*- coding: utf-8 -*-
"""S-03（队列认领 · 乙形态）：提交的检索请求由 `conductor` 侧认领给 A 的 `run_once`。

裁定（主控）：形态选 (乙) —— 队列级消费，文件范围就是 `agent_a` + `conductor`。
(甲)（C/D 的处理体内递归召唤 + 动 `host.py`/FC-27）按现在的设计不做；
"提交那一刻就消费"的正确做法是改派活权的归属，那是另一个设计题、要人裁。

三件必须写在明面上的事：

1. "即"字的折扣：这里的"提交即被消费"读作"下一次 M 侧派活（`run_plan`）或 M
   收尾（`finish_top_level_run`）时被消费"；若 M 之后不再动，请求留着 pending ——
   由 F-05 消费端（`secretary.pending_inbox` / `inbox_todos`）与 `closing` 的
   研究链缺口读数让它可见（"不可见地挂着"这个最坏形态因此不成立）；
2. 两个消费点：派活时 + 收尾前（只挂"下一次派活"的话，最需要它的时候反而不会消费）；
3. 折扣可度量：`stats()["consume_counts"]` 分清两处各消费几条。

幂等是单独立的一条判据（同一 `request_id` 只唤起一次 ⇒ `role="A"` 的行恒为 1），
外加一条反负控（没有待办时不许产生任何 `role="A"` 的行 —— 防"为了消费而消费"）。
"""
from __future__ import annotations

import pathlib

from conftest import add_request

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store


class _FakeA:
    """A 的替身：只实现 `run_once`（S-03 认领的那个动作），返回"跑完了"。"""

    def __init__(self) -> None:
        self.calls = 0

    def run_once(self) -> dict:
        self.calls += 1
        return {"outcome": "ok", "detail": f"跑了一条（第 {self.calls} 次）", "checked": True,
                "payload": {"checked": True}}


def _cond(tmp_path: pathlib.Path) -> tuple[Store, Conductor, _FakeA]:
    st = Store(tmp_path / "ws")
    st.init()
    a = _FakeA()
    return st, Conductor(st, backend=LocalBackend({"A": a})), a


def _a_rows(st: Store) -> list[dict]:
    return [r for r in st.rows("tasks") if str(r.get("role")) == "A"]


def test_s03_a_submitted_request_is_claimed_exactly_once(tmp_path: pathlib.Path):
    """负控/正控：提交一条 pending ⇒ 被认领恰好一次（改前红：A 一次都没被唤起）。"""
    st, cond, a = _cond(tmp_path)
    add_request(st, "r-0001", topic="periodic elliptic operators")
    assert st.rows("search_requests")[0]["done"] is False, st.rows("search_requests")
    assert st.rows("search_requests")[0]["attempts"] == 0, st.rows("search_requests")
    # 改前：`consume_pending_search_requests` 不存在（AttributeError），
    # 而真机就是这个形态 —— 请求 `done=false attempts=0` 一直挂着没人做。
    got = cond.consume_pending_search_requests(trigger="dispatch")
    assert len(got) == 1, [getattr(r, "task_id", None) for r in got]
    rows = _a_rows(st)
    assert len(rows) == 1, rows
    assert rows[0]["action"] == "run_once" and rows[0]["called_by"] == "M", rows[0]
    assert rows[0]["status"] == "done" and rows[0]["outcome"] == "ok", rows[0]
    assert a.calls == 1, a.calls


def test_s03_the_same_request_is_never_claimed_twice(tmp_path: pathlib.Path):
    """幂等（单独一条）：同一条 `request_id` 触发两次 ⇒ `role="A"` 的行恒为 1。"""
    st, cond, a = _cond(tmp_path)
    add_request(st, "r-0001", topic="Floquet Bloch")
    first = cond.consume_pending_search_requests(trigger="dispatch")
    second = cond.consume_pending_search_requests(trigger="dispatch")
    assert len(first) == 1 and second == [], (len(first), second)
    assert len(_a_rows(st)) == 1, _a_rows(st)
    assert a.calls == 1, "同一条请求被做了两次（幂等失效）"
    keys = [str(r.get("input_key") or "") for r in _a_rows(st)]
    assert keys == ["consume:r-0001"], keys


def test_s03_nothing_pending_means_no_summon(tmp_path: pathlib.Path):
    """反负控（防"为了消费而消费"）：没有待办 ⇒ 不许产生任何 `role="A"` 的行。"""
    st, cond, a = _cond(tmp_path)
    # ① 队是空的
    assert cond.consume_pending_search_requests(trigger="dispatch") == []
    assert _a_rows(st) == [] and a.calls == 0, _a_rows(st)
    # ② 有行但已经做完 ⇒ 同样不许消费
    add_request(st, "r-0002", topic="已完成的", done=True, result_lit_ids=["0001"])
    assert cond.consume_pending_search_requests(trigger="dispatch") == []
    assert _a_rows(st) == [] and a.calls == 0, _a_rows(st)


def test_s03_both_consumption_points_are_counted(tmp_path: pathlib.Path):
    """两个消费点 + 可度量：派活时与收尾前各消费几条，都在读数里。"""
    st, cond, a = _cond(tmp_path)
    # 收尾点：顶趟收行前扫一次队（只挂"下一次派活"的话，这一趟要结束时反而不会消费）
    tid = cond.open_top_level_run("M", "顶趟")
    add_request(st, "r-0001", topic="收尾时该被认领")
    cond.finish_top_level_run(tid, stop_reason="final", detail="收工")
    assert len(_a_rows(st)) == 1, _a_rows(st)
    counts = cond.stats()["consume_counts"]
    assert counts.get("finish") == 1, counts
    # 派活点：再来一条 pending，跑一次 plan（空 plan 也算"派活时"这一次扫描）
    add_request(st, "r-0002", topic="派活时该被认领")
    cond.run_plan([])
    counts = cond.stats()["consume_counts"]
    assert counts.get("dispatch") == 1 and counts.get("finish") == 1, counts
    assert len(_a_rows(st)) == 2, _a_rows(st)
    assert a.calls == 2, a.calls
