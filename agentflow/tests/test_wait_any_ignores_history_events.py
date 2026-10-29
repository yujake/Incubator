# -*- coding: utf-8 -*-
"""判据：`wait_any` 的"起意之后回来几条"必须以起意那一刻的事件序号为基线。

## 真因（2026-10-29，两份 run 全量对比 + 读码交叉验证）

长前缀下 `clock.wait_any` 返回：

```
wait_id = "wa-000001"
reason  = "起意之后有 31 条回来了 ⇒ 该回模型了"
```

而这是刚刚起意的一条意图。原因在 `wait_any_reading` 那一支：

```python
seq_mark = 0                                            # 基线写死 0
events = observed_events(since_seq=seq_mark)["events"]  # 读到进程里全部历史事件
```

观测窗是进程全局的：长跑里前面几百个用例发过的消息全在里面，`task_id` 往往也是
`t-000001`（多数判据都在自己新建的工作区里开 t-000001），于是按台账号过滤挡不住；
再叠上"墙钟比较"——判据用的是 FakeClock（2026-01-01），真实事件时间是 2026-10-29，
旧事件反而"更新" ⇒ 全被算成"回来了" ⇒ 不挂机 ⇒ 后面打转收工（`no_progress_limit`）。

## 这一组守什么

1. 正题：先制造一批同台账号的历史事件，再起一条等待意图 ⇒ 读数必须是
   `waiting=True` / `woke=[]`（修前那一批历史事件会让它当场判"该回模型"）；
2. 反真空：把意图行的 `at_seq` 改回 0（= 旧实现）⇒ 同一条读数必须变成 `woke` 非空。
"""
from __future__ import annotations

import pathlib

from agentflow import clock as C


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    return ws


def _plant_history(tid: str, n: int = 31) -> None:
    """造 n 条"同台账号的历史事件"（= 长前缀下前面那些用例留下的东西）。"""
    for i in range(n):
        C.observe_event("message", task_id=tid, from_task_id=tid,
                        role="D", content=f"历史事件 {i}", message_id=f"m-{i:06d}")


def test_a_fresh_wait_is_not_woken_by_history(tmp_path: pathlib.Path):
    """正题：新起的等待不该被进程里的历史事件判成"已经回来了"。"""
    C.reset()
    C.reset_observed_events()
    ws = _ws(tmp_path)
    tid = "t-000001"
    C.start_timer(ws, after_sec=60.0, reason="再看一眼", task_id=tid, role="D")
    _plant_history(tid)
    row = C.request_wait_any(ws, task_id=tid, role="D", purpose="等任意计时器返回")
    assert row.get("at_seq"), row
    got = C.wait_any_reading(ws, tid)
    assert got.get("checked") is True, got
    assert got.get("woke") == [], got["woke"]
    assert got.get("waiting") is True, got


def test_the_old_baseline_still_reproduces_the_bug(tmp_path: pathlib.Path):
    """反真空：把 `at_seq` 抹成 0（= 旧实现）⇒ 历史事件立刻把它判成"回来了"。"""
    C.reset()
    C.reset_observed_events()
    ws = _ws(tmp_path)
    tid = "t-000002"
    C.start_timer(ws, after_sec=60.0, reason="再看一眼", task_id=tid, role="D")
    _plant_history(tid, 3)
    C.request_wait_any(ws, task_id=tid, role="D", purpose="等任意计时器返回")
    doc = C.read_wait_any(ws)
    rows = [dict(r) for r in (doc.get("rows") or [])]
    rows[-1]["at_seq"] = 0
    # 老行（没有基线）走墙钟那一支：把起意时刻挪到"很久以前"，
    # 等于真机里假时钟（2026-01-01）对着真实事件时间的效果。
    rows[-1]["at"] = "2026-01-01T00:00:00+00:00"
    C._atomic_json(C.wait_any_path(ws), {**doc, "rows": rows})  # noqa: SLF001
    got = C.wait_any_reading(ws, tid)
    assert got.get("woke"), "抹掉基线之后应当读到历史事件 —— 否则正题那条是恒真的假绿"
