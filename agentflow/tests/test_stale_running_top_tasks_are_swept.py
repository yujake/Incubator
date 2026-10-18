# -*- coding: utf-8 -*-
"""被杀/崩溃的顶趟不许永远停在 `running`（缺陷 ⑫）。

## 现场（真机 `projects/t2s`，2026-10-18）

```
t-000001 | M | running | started 03:01:55 | ended=     ← 我 kill 掉的第一趟
t-000005 | M | running | started 03:19:26 | ended=     ← --resume 那趟（no_checkpoint 退出）
t-000006 | M | running | started 03:21:00 | ended=     ← 真正在跑的那一趟
```

同一角色三行同时 `running`，其中两行的**进程早已不在** ⇒「谁还没收工」「现在几个在跑」
这类读数全部说谎，收工门与验收表都会照着假读数算。

## 现在的口径

开新顶趟前，`Conductor._sweep_stale_top_running(role)` 把**同角色、`called_by=主控`** 的
遗留 `running` 行标成 `failed` ＋ `outcome="abandoned"` ＋ 写明原因。
子代理的行**不动**（它们有自己的收尾逻辑，误判会把同时在跑的子任务当成僵尸）。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.store import Store


@pytest.fixture()
def st(tmp_path):
    store = Store(tmp_path / "ws")
    store.init()
    return store


class _Stub:
    """只借 `_sweep_stale_top_running` 需要的两个属性（store / _log）。"""

    def __init__(self, store: Store) -> None:
        self.store = store

    def _log(self, *_a, **_k) -> None:  # noqa: D401 - 桩
        return None


def _add(st: Store, role: str, status: str, *, called_by: str, tid: str,
         parent: str | None = None) -> None:
    with st.tx("tasks", actor=S.CONDUCTOR_ROLE) as tx:
        tx.upsert("tasks", {
            "task_id": tid, "role": role, "action": "run", "called_by": called_by,
            "parent_task_id": parent, "depth": (1 if parent is None else 2), "input_key": f"k-{tid}",
            "status": status,
            "outcome": ({"done": "ok"}.get(status) if status != "running" else None),
            "refusal_reason": None,
            "instance": "", "detail": "d", "error": None,
            "started_at": S.now_iso(),
            # schema 硬约束：`done`/`failed` 必须有 ended_at（"每个 start 有且仅有一个 end"）
            "ended_at": (None if status == "running" else S.now_iso()),
            "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        })


def _status(st: Store, tid: str) -> str:
    return str(next(r for r in st.rows("tasks") if r["task_id"] == tid)["status"])


def test_stale_top_running_rows_become_failed(st: Store):
    """**正控**：同角色、主控开的旧 `running` 行 ⇒ 被标成 `failed`。"""
    _add(st, "M", "running", called_by=S.CONDUCTOR_ROLE, tid="t-000001")
    _add(st, "M", "running", called_by=S.CONDUCTOR_ROLE, tid="t-000005")
    n = Conductor._sweep_stale_top_running(_Stub(st), "M")
    assert n == 2, n
    assert _status(st, "t-000001") == "failed"
    assert _status(st, "t-000005") == "failed"


def test_live_child_tasks_are_not_touched(st: Store):
    """**负控**：子代理（`called_by != 主控`）与别的角色**不许**被误清。"""
    _add(st, "M", "running", called_by="agent-M", tid="t-000002",
         parent="t-000001")   # 子任务（有 parent ⇒ 不是顶趟）
    _add(st, "D", "running", called_by=S.CONDUCTOR_ROLE, tid="t-000003")  # 别的角色
    _add(st, "M", "done", called_by=S.CONDUCTOR_ROLE, tid="t-000004")     # 已收工
    n = Conductor._sweep_stale_top_running(_Stub(st), "M")
    assert n == 0, n
    assert _status(st, "t-000002") == "running"
    assert _status(st, "t-000003") == "running"
    assert _status(st, "t-000004") == "done"
