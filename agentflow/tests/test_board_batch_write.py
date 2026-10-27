# -*- coding: utf-8 -*-
"""判据：批量开板项与逐条开板项落盘逐字节一致，且整批同成同败（2026-10-27）。

## 为什么要有这条判据

`broadcast` / `notify_children_of_stop` 改成一笔事务开 N 条之后，性能从
「每条边两到三笔事务」变成「一次」（实测 `temp/r_be2_after_reads.py`：
`broadcast` 投 12 人 418.5 ms → 15.9 ms；`notify_children_of_stop` 12 条 657.9 ms → 35.3 ms）。
收益是 20 倍级的，代价是两条写路径并存：一条批量、一条逐条（其余调用方还在用）。

两条写路径并存时的失效形态不会报错 —— 它会静默地少一格、或多一条事件，而
`tasks` 表是审计面：少一格 `item_close` 与"这一项当时就没有那一格"长得一模一样。
所以这条判据用逐字节来钉：

1. 表内容：两个一模一样的工作区，一个走逐条路径、一个走批量路径 ⇒
   `data/tasks.json` 的 sha256 必须相同（与 I-9 的重建一致判据同一档强度）；
2. 事件流：把 `seq` / `ts` / `batch` 三个"每次运行都不同"的字段去掉之后，两条路径
   的事件序列必须逐条相同（含 `op` / `table` / `row` / `actor` / `note`）——
   唯一的差别只允许是提交标记：逐条路径 2N 条 `commit`，批量路径 1 条；
3. 同成同败：批里第二条的 `role` 不合法 ⇒ 整批抛，且 `tasks.json` 与
   `events.jsonl` 的 sha256 一个字节都不许变（逐条路径没有这个性质：它会把前一条留在盘上）；
4. 一笔事务：真的跑一次 `broadcast` 给 12 个人，新增的 `commit` 行必须恰好 1 条
   （这一格防的是"批量 API 存在但调用点没换"）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.conductor import Conductor, calling_as
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"
N_ITEMS = 6


def _ws(tmp_path: pathlib.Path, name: str) -> Store:
    st = Store(tmp_path / name)
    st.init()
    rows = [S.Task(task_id="t-0001", role="M", action="run", called_by="user",
                   status="running", outcome=None, input_key="M.run",
                   detail="顶趟", started_at=TS, ended_at=None).to_dict()]
    for i in range(N_ITEMS):
        rows.append(S.Task(task_id=f"t-{i + 2:04d}", role="D", action="run",
                           called_by="M", status="running", outcome=None,
                           input_key=f"D.run#{i}", detail="子代理在跑",
                           parent_task_id="t-0001", started_at=TS,
                           ended_at=None).to_dict())
    with st.tx("tasks", actor="fixture") as tx:
        for r in rows:
            tx.upsert("tasks", r)
    return st


def _specs() -> list[dict]:
    return [{"kind": "message", "role": "D", "expects": "ack", "action": "message",
             "summary": f"第{i}条", "called_by": "M", "parent_task_id": f"t-{i + 2:04d}",
             "depth": 2, "input_key": f"batch-probe:{i}"} for i in range(N_ITEMS)]


def _detail() -> str:
    return "批量的那一句说明"


def _tasks_bytes(st: Store) -> bytes:
    return (st.data / "tasks.json").read_bytes()


def _events_normalized(st: Store) -> list[dict]:
    """事件流去掉 `seq` / `ts` / `batch`（这三个每次运行都不同，包括同一条路径跑两次）。"""
    out = []
    for line in (st.data / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        rec.pop("seq", None)
        rec.pop("ts", None)
        rec.pop("batch", None)
        out.append(rec)
    return out


def _count_commits(st: Store) -> int:
    return sum(1 for r in _events_normalized(st) if r.get("op") == "commit")


# ---------------------------------------------------------------- 1. 表内容逐字节
def test_batch_writes_the_same_table_bytes(tmp_path) -> None:
    one = _ws(tmp_path, "one")
    many = _ws(tmp_path, "many")
    assert _tasks_bytes(one) == _tasks_bytes(many), "两个夹具工作区起点就不一样"

    cond_one = Conductor(one)
    for spec in _specs():
        item = cond_one.open_item(**spec)
        got, why = cond_one.set_item_detail(item, _detail())
        assert got and not why, (got, why)

    cond_many = Conductor(many)
    ids = cond_many.open_items_many(_specs(), details=[_detail()] * N_ITEMS)
    assert len(ids) == N_ITEMS

    a, b = _tasks_bytes(one), _tasks_bytes(many)
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest(), (
        "批量路径与逐条路径写出的 `tasks.json` 不是同一份字节 ⇒ 两条写路径已经分家"
        f"（逐条 {len(a)} 字节 / 批量 {len(b)} 字节）")


# ---------------------------------------------------------------- 2. 事件流逐条
def test_batch_emits_the_same_event_sequence(tmp_path) -> None:
    one = _ws(tmp_path, "one")
    many = _ws(tmp_path, "many")
    # 夹具自己也写了一笔事务（建那 N+1 行）⇒ 两边的基线各算进来，差值才是本次的写。
    base_one, base_many = _count_commits(one), _count_commits(many)
    cond_one = Conductor(one)
    for spec in _specs():
        item = cond_one.open_item(**spec)
        cond_one.set_item_detail(item, _detail())
    Conductor(many).open_items_many(_specs(), details=[_detail()] * N_ITEMS)

    ev_one = _events_normalized(one)
    ev_many = _events_normalized(many)
    body_one = [e for e in ev_one if e.get("op") != "commit"]
    body_many = [e for e in ev_many if e.get("op") != "commit"]
    assert body_one == body_many, (
        "两条路径的写事件序列不同 ⇒ 批量那一路漏写/多写了一条事件"
        f"（逐条 {len(body_one)} 条 / 批量 {len(body_many)} 条）")
    # 唯一允许的差别：提交标记的条数（逐条 1 笔=1 条，批量也是 1 笔；这里两边都是 N/1）。
    assert _count_commits(one) - base_one == 2 * N_ITEMS, (
        f"逐条路径的提交标记应该是 2N={2 * N_ITEMS} 条，实测 "
        f"{_count_commits(one) - base_one}")
    assert _count_commits(many) - base_many == 1, (
        f"批量路径应该只有 1 条提交标记，实测 {_count_commits(many) - base_many}"
        " ⇒ 不是一笔事务")


# ---------------------------------------------------------------- 3. 同成同败
def test_a_bad_item_rolls_back_the_whole_batch(tmp_path) -> None:
    st = _ws(tmp_path, "rollback")
    cond = Conductor(st)
    before_tasks = hashlib.sha256(_tasks_bytes(st)).hexdigest()
    before_events = hashlib.sha256((st.data / "events.jsonl").read_bytes()).hexdigest()
    bad = _specs()
    bad[1] = dict(bad[1], role="不是角色")          # `Task.validate` ⇒ ValueError
    with pytest.raises(Exception) as exc:
        cond.open_items_many(bad, details=[_detail()] * N_ITEMS)
    assert "role" in str(exc.value), exc.value
    assert hashlib.sha256(_tasks_bytes(st)).hexdigest() == before_tasks, (
        "整批失败之后 `tasks.json` 变了 ⇒ 有半截落了盘")
    assert hashlib.sha256((st.data / "events.jsonl").read_bytes()).hexdigest() == before_events, (
        "整批失败之后事件流变了 ⇒ 有半截落了盘（重建会看见那半截）")
    # 负控：把那条坏项修好，同一批必须能写成（否则上面只是"这个方法总是抛"）。
    good = _specs()
    assert len(cond.open_items_many(good, details=[_detail()] * N_ITEMS)) == N_ITEMS


# ---------------------------------------------------------------- 4. 调用点真的换了
def test_broadcast_opens_its_items_in_one_transaction(tmp_path) -> None:
    st = _ws(tmp_path, "broadcast")
    cond = Conductor(st)
    commits_before = _count_commits(st)
    with calling_as("t-0001", "M"):
        got = cond.broadcast(subject="停一下", body="正文", by="M")
    assert got.get("ok"), got
    assert len(got.get("recipients") or []) == N_ITEMS, got
    added = _count_commits(st) - commits_before
    assert added == 1, (
        f"`broadcast` 给 {N_ITEMS} 个人开了 {added} 笔事务（应为 1）⇒ 调用点没走批量路径")
