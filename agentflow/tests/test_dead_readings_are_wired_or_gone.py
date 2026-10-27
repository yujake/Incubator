# -*- coding: utf-8 -*-
"""判据：三条"写了没人读"的读数要么接进 `stats()`，要么删掉（2026-10-27）。

## 背景（这三条都是同一种形态）

写了、但全仓没有一个读者。这种形态不会报错：字段安静地存在，而它的 docstring 还写着
"读数的第二个落点"——下一个读代码的人会以为有人读它，于是再写一处依赖它、或者干脆不敢改。

1. 最近一次派活前摆出来的同 key 既有终态行（`stats()["last_duplicates"]`）：docstring 逐字写着"最近一次派活前摆出来的同 key 既有终态行
   （读数的第二个落点：日志之外）"，而"日志之外"那一半根本不存在 ⇒ 接进 `stats()`；
2. `conductor._consume_roster_problems`：兄弟格 `_consume_counts` 进了 `stats()`，它没进
   ⇒ 接进 `stats()`；
3. `secretary` 里那个存"闭环该不该介入"的布尔字段（名字里有 closure 与 engage 两段）：
   写两次、读零次，而 `should_engage` 是纯谓词（无副作用）⇒ 整句删掉（连字段一起）。

## 这条判据钉住什么

- `stats()` 必须带这两个格，而且值是那一次的读数（不是 `[]` 常量、不是 `None`）；
- 反真空：先真的造出读数（派发一次同 key 重复的召唤 / 让队列认领那一路记一条名册问题），
  再断言 `stats()` 里看得见 —— 否则"两格都在"可能只是"两格都永远是空的"；
- 三态：字段没人写时 `stats()` 给空容器（不是 `None`、不是缺格），读的人不必判 `KeyError`；
- 删掉的那一条不许回来：`secretary` 里不再有那个存布尔位的实例字段。
"""
from __future__ import annotations

import pathlib

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", S.Task(task_id="t-0001", role="M", action="run",
                                  called_by="user", status="running", outcome=None,
                                  input_key="M.run", detail="顶趟", started_at=TS,
                                  ended_at=None).to_dict())
    return st


def test_stats_carries_the_two_wired_readings(tmp_path) -> None:
    st = _ws(tmp_path)
    out = Conductor(st).stats()
    assert "last_duplicates" in out, "`stats()` 没有 `last_duplicates` 这一格"
    assert "consume_roster_problems" in out, "`stats()` 没有 `consume_roster_problems` 这一格"
    # 三态：没写过的时候是空容器（不是 None、也不是缺格）。
    assert out["last_duplicates"] == [], out["last_duplicates"]
    assert out["consume_roster_problems"] == [], out["consume_roster_problems"]


def test_the_two_readings_are_live_not_decorative(tmp_path) -> None:
    """反真空：把字段设成真读数，`stats()` 必须把它读出来（不是写死空表）。"""
    st = _ws(tmp_path)
    cond = Conductor(st)
    cond._last_duplicates = [{"task_id": "t-0002", "status": "done", "outcome": "ok"}]
    cond._consume_roster_problems = ["名册正文没写成：探针"]
    out = cond.stats()
    assert out["last_duplicates"] == [{"task_id": "t-0002", "status": "done",
                                       "outcome": "ok"}], out["last_duplicates"]
    assert out["consume_roster_problems"] == ["名册正文没写成：探针"], (
        out["consume_roster_problems"])
    # 返回的是副本：读的人就地改那一格，不许污染下一次读数。
    out["last_duplicates"].append({"task_id": "x"})
    assert cond.stats()["last_duplicates"] == [{"task_id": "t-0002", "status": "done",
                                               "outcome": "ok"}]


def test_the_dead_field_is_gone() -> None:
    """删掉的那一条不许回来（回来了就得连带一处读者，而它当时一个都没有）。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "agentflow" / "secretary.py")
    text = src.read_text(encoding="utf-8")
    hits = [i for i, ln in enumerate(text.splitlines(), 1)
            if "_last_closure" in ln and not ln.strip().startswith("#")]
    assert not hits, (
        f"那个'闭环该不该介入'的实例字段又回到了 secretary.py: {hits} —— "
        "它当时写两次、读零次；要用就先给它一个真读者")
